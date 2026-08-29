# -*- coding: utf-8 -*-
"""3.16 扳手错质检桥接。

负责把转换结果目录中的 17 个 SHP + 2 个关系 DBF 交给 QGIS 3.16 子进程，
调用 shpchecker，然后读取其 ERROR_LOG 并导出 Excel。QGIS 3.28 工程不加载这些图层。
shpchecker 是 QGIS 3.16 专用的编译扩展，因此这里不复制检查算法，
而是在 QGIS 运行时通过插件 API/界面触发，避免 Python 版本冲突。
"""
from __future__ import annotations

import importlib
import inspect
import os
import re
import sys
import traceback
import zipfile
import subprocess
import glob
import tempfile
import shutil
import time
from datetime import datetime
from html import escape
from xml.sax.saxutils import escape as xml_escape

from qgis.PyQt.QtCore import QTimer, Qt, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QApplication, QDialog, QPushButton, QToolButton
from qgis.core import QgsProject, QgsVectorLayer


REQUIRED_SHP = (
    "CLEARAREA", "CROSSWALK", "FREEAREA", "GATE", "INTERSECTION",
    "LANE_GROUP", "LANE_MARKING", "LANE_NODE", "LANE", "PARKING",
    "PILLAR", "PROHIBITED_AREA", "ROAD_LINK", "SAFETYISLAND",
    "SPEEDBUMP", "STOPLINE", "TRAFFICLIGHT",
)
REQUIRED_REL = ("CROSSWALK_LANE_REL.dbf", "INTERSECTION_SIGNAL_REL.dbf")


class ShpCheckerController:
    def __init__(self, iface, plugin_dir, error_results, log_fn=None):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.error_results = error_results
        self.log = log_fn or print
        self.action = None
        self.toolbar_button = None
        self._checker = None
        self._input_dir = ""
        self._loaded_layers = []
        self._log_path = None
        self._all_log_lines = []
        self._collect_attempts = 0
        self._process = None
        self._profile_root = None
        self._child_log_path = None
        self._run_started_at = 0.0
        self._default_input_dir = os.path.join(self.plugin_dir, "转换数据", "output")
        self._input_dir_key = "LaneBatchUpdate/shpcheckerInputDir"
        try:
            os.makedirs(self._default_input_dir, exist_ok=True)
        except OSError:
            pass

    def initGui(self, actions_master):
        icon_path = os.path.join(self.plugin_dir, "icon_316_wrench.svg")
        self.action = QAction(QIcon(icon_path), "3.16扳手错质检", self.iface.mainWindow())
        self.action.setToolTip("加载转换后的19个数据文件，调用 shpchecker 自动质检并导出 Excel")
        self.action.triggered.connect(self.run)
        self.iface.addPluginToVectorMenu("车道处理工具", self.action)
        actions_master.append(self.action)
        class _InputButton(QToolButton):
            def mouseDoubleClickEvent(button_self, event):
                self.configure_input_dir()
                event.accept()
        self.toolbar_button = _InputButton(self.iface.mainWindow())
        self.toolbar_button.setDefaultAction(self.action)
        self.toolbar_button.setToolTip("单击运行 3.16 扳手错；双击配置转换数据目录")
        toolbar = self.iface.vectorToolBar()
        if toolbar is not None:
            toolbar.addWidget(self.toolbar_button)

    def unload(self):
        if self.action is not None:
            try:
                self.iface.removeVectorToolBarIcon(self.action)
                self.iface.removePluginToVectorMenu("车道处理工具", self.action)
            except (AttributeError, RuntimeError):
                pass
        if self.toolbar_button is not None:
            try:
                self.toolbar_button.deleteLater()
            except RuntimeError:
                pass
            self.toolbar_button = None
        self.action = None

    def configure_input_dir(self):
        current = str(QSettings().value(self._input_dir_key, self._default_input_dir) or self._default_input_dir)
        folder = QFileDialog.getExistingDirectory(self.iface.mainWindow(), "选择转换后的数据目录", current)
        if folder:
            QSettings().setValue(self._input_dir_key, folder)
            self._input_dir = folder
            self.log("已保存 3.16 扳手错数据目录: %s" % folder)
            return folder
        return current

    def _write_log(self, lines):
        if lines:
            self._all_log_lines.extend(lines)
        log_dir = os.path.join(self.plugin_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        self._log_path = os.path.join(log_dir, "shpchecker_316_%s.log" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        try:
            with open(self._log_path, "w", encoding="utf-8-sig") as handle:
                handle.write("\n".join(self._all_log_lines) + "\n")
        except OSError:
            pass

    def _find_qgis_316(self):
        configured = str(QSettings().value("LaneBatchUpdate/qgis316Executable", "") or "")
        candidates = [configured] if configured else []
        candidates.extend([
            r"C:\Program Files\QGIS 3.16.16\bin\qgis-bin.exe",
            r"C:\Program Files\QGIS 3.16.15\bin\qgis-bin.exe",
            r"C:\Program Files\QGIS 3.16.14\bin\qgis-bin.exe",
            r"C:\OSGeo4W64\bin\qgis-bin.exe",
            r"C:\OSGeo4W\bin\qgis-bin.exe",
            r"D:\software\QGIS3.16\bin\qgis-bin.exe",
            r"D:\software\QGIS3.16\bin\qgis-ltr-bin.exe",
            r"D:\qgis3.16\bin\qgis-bin.exe",
        ])
        for root in (r"C:\Program Files", r"C:\Program Files (x86)", r"D:\software"):
            candidates.extend(glob.glob(os.path.join(root, "QGIS 3.16*", "bin", "qgis-bin.exe")))
            candidates.extend(glob.glob(os.path.join(root, "QGIS3.16*", "bin", "qgis-bin.exe")))
        for path in candidates:
            if path and os.path.isfile(path):
                return os.path.abspath(path)
        return ""

    def _launch_external_runner(self, lines):
        executable = self._find_qgis_316()
        if not executable:
            executable, _ = QFileDialog.getOpenFileName(
                self.iface.mainWindow(), "选择 QGIS 3.16 qgis-bin.exe", r"C:\Program Files", "QGIS 程序 (qgis-bin.exe);;所有文件 (*)"
            )
            if not executable:
                lines.append("未找到 QGIS 3.16 可执行文件")
                return False
            QSettings().setValue("LaneBatchUpdate/qgis316Executable", executable)
        runner = os.path.join(self.plugin_dir, "shpchecker_runner.py")
        vendor_parent = os.path.join(self.plugin_dir, "vendor")
        if not os.path.isfile(runner) or not os.path.isdir(os.path.join(vendor_parent, "shpchecker")):
            lines.append("发布包缺少 shpchecker_runner.py 或 vendor/shpchecker")
            return False
        log_dir = os.path.join(self.plugin_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        runner_log = os.path.join(log_dir, "shpchecker_child_%s.log" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        env = os.environ.copy()
        env_file = os.path.splitext(executable)[0] + ".env"
        if os.path.isfile(env_file):
            try:
                with open(env_file, "r", encoding="utf-8", errors="replace") as handle:
                    for raw in handle:
                        if "=" not in raw or raw.lstrip().startswith("rem "):
                            continue
                        key, value = raw.strip().split("=", 1)
                        if key:
                            env[key] = value
            except OSError as exc:
                lines.append("读取 QGIS 环境文件失败: %r" % (exc,))
        env.update({
            "LANEBATCH_SHPCHECKER_INPUT": self._input_dir,
            "LANEBATCH_SHPCHECKER_VENDOR": vendor_parent,
            "LANEBATCH_SHPCHECKER_LOG": runner_log,
        })
        try:
            self._run_started_at = time.time()
            lines.append("使用 QGIS 3.16 default 用户配置；为避免单实例转发，任务进程使用 --new-instance")
            startupinfo = None
            creationflags = 0
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._process = subprocess.Popen(
                [
                    executable, "--nologo", "--noversioncheck", "--noplugins", "--new-instance", "--profile", "default",
                    "--code", runner,
                ],
                cwd=os.path.dirname(executable), env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                startupinfo=startupinfo, creationflags=creationflags,
            )
            self._child_log_path = runner_log
            lines.append("已启动 QGIS 3.16: %s" % executable)
            lines.append("子进程日志: %s" % runner_log)
            QTimer.singleShot(1500, self._poll_external_runner)
            return True
        except Exception as exc:
            lines.append("启动 QGIS 3.16 失败: %r" % (exc,))
            return False

    def _poll_external_runner(self):
        if self._process is not None and self._process.poll() is None:
            QTimer.singleShot(2000, self._poll_external_runner)
            return
        self._process = None
        if self._profile_root:
            shutil.rmtree(self._profile_root, ignore_errors=True)
            self._profile_root = None
        self._collect_attempts += 1
        found = any(
            name.lower().startswith("errorlog")
            and name.lower().endswith((".xlsx", ".sqlite"))
            and os.path.getmtime(os.path.join(root, name)) >= self._run_started_at
            for root, _dirs, names in os.walk(self._input_dir)
            for name in names
        )
        if not found and self._collect_attempts < 30:
            QTimer.singleShot(2000, self._poll_external_runner)
            return
        self._collect_checker_results()

    @staticmethod
    def _find_files(folder):
        missing = []
        paths = []
        for name in REQUIRED_SHP:
            path = os.path.join(folder, name + ".shp")
            if not os.path.isfile(path):
                missing.append(name + ".shp")
            else:
                paths.append(path)
        for name in REQUIRED_REL:
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                missing.append(name)
            else:
                paths.append(path)
        return paths, missing

    def _load_input_layers(self, paths, lines):
        project = QgsProject.instance()
        loaded = []
        for path in paths:
            base = os.path.splitext(os.path.basename(path))[0]
            existing = [layer for layer in project.mapLayers().values() if isinstance(layer, QgsVectorLayer) and os.path.abspath(layer.source().split("|", 1)[0]) == os.path.abspath(path)]
            if existing:
                loaded.append(existing[0])
                lines.append("已存在图层: %s" % path)
                continue
            layer = QgsVectorLayer(path, base, "ogr")
            if not layer.isValid():
                lines.append("加载失败: %s" % path)
                continue
            project.addMapLayer(layer)
            loaded.append(layer)
            lines.append("已加载: %s (%d 要素)" % (path, layer.featureCount()))
        self._loaded_layers = loaded
        return loaded

    def _locate_checker_package(self):
        try:
            return importlib.import_module("shpchecker")
        except ImportError:
            pass
        # QGIS 插件目录可能未加入 sys.path。
        try:
            from qgis.core import QgsApplication
            root = QgsApplication.qgisSettingsDirPath()
            for profile in ("default",):
                parent = os.path.join(root, "profiles", profile, "python", "plugins")
                if parent not in sys.path:
                    sys.path.insert(0, parent)
            return importlib.import_module("shpchecker")
        except Exception:
            pass
        configured = str(QSettings().value("LaneBatchUpdate/shpcheckerPluginDir", "") or "")
        if configured and os.path.isdir(configured) and configured not in sys.path:
            sys.path.insert(0, configured)
        try:
            return importlib.import_module("shpchecker")
        except ImportError:
            return None

    def _start_checker(self, lines):
        return self._launch_external_runner(lines)

    @staticmethod
    def _button_text(button):
        try:
            return "%s %s" % (button.text(), button.toolTip())
        except Exception:
            return ""

    def _automate_checker_dialog(self):
        """对不同 shpchecker 小版本做宽松的按钮匹配。匹配不到时保留界面供手动执行。"""
        lines = []
        dialogs = [w for w in QApplication.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]
        dialog = dialogs[-1] if dialogs else None
        if dialog is None:
            lines.append("未发现可见的 shpchecker 对话框，请手动执行检查")
            self._write_log(lines)
            return
        buttons = [w for w in dialog.findChildren(QPushButton)]
        texts = [(self._button_text(w), w) for w in buttons]
        def click_matching(patterns):
            for text, button in texts:
                if any(re.search(pattern, text, re.I) for pattern in patterns):
                    button.click()
                    lines.append("自动点击: %s" % text)
                    return True
            return False
        click_matching((r"全选", r"全部选择", r"select.*all"))
        click_matching((r"执行", r"开始检查", r"检查", r"run", r"check"))
        QTimer.singleShot(3500, self._export_and_collect)
        self._write_log(lines)

    def _export_and_collect(self):
        """尝试调用 shpchecker 的导出方法；找不到时仍收集其 ERROR_LOG。"""
        lines = []
        self._collect_attempts += 1
        dialogs = [w for w in QApplication.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]
        dialog = dialogs[-1] if dialogs else None
        export_path = os.path.join(self._input_dir, "3.16扳手错结果", "shpchecker_error_log.xlsx")
        os.makedirs(os.path.dirname(export_path), exist_ok=True)
        targets = [dialog, self._checker]
        exported = False
        for target in targets:
            if target is None:
                continue
            for name in ("export_error_log", "exportErrorLog", "export_results", "export_excel"):
                fn = getattr(target, name, None)
                if not callable(fn):
                    continue
                for args in ((export_path,), tuple()):
                    try:
                        result = fn(*args)
                        lines.append("调用导出: %s(%s) -> %r" % (name, args, result))
                        exported = True
                        break
                    except TypeError:
                        continue
                    except Exception as exc:
                        lines.append("导出调用失败 %s: %r" % (name, exc))
                        break
                if exported:
                    break
            if exported:
                break
        if not exported:
            lines.append("未找到可调用的 shpchecker 导出方法，将使用 ERROR_LOG 生成 Excel")
        self._write_log(lines)
        # 检查可能需要较长时间；等待本次运行生成的 errorlog.xlsx，最多约 60 秒。
        has_result_file = False
        for root, _dirs, names in os.walk(self._input_dir):
            for name in names:
                path = os.path.join(root, name)
                if (name.lower().startswith("errorlog") and name.lower().endswith(".xlsx")
                        and os.path.getmtime(path) >= self._run_started_at):
                    has_result_file = True
                    break
            if has_result_file:
                break
        if not has_result_file and self._collect_attempts < 30:
            QTimer.singleShot(2000, self._export_and_collect)
            return
        self._collect_checker_results()

    def _collect_checker_results(self):
        lines = []
        try:
            QSettings().setValue("LaneBatchUpdate/shpcheckerOutputDir", self._input_dir)
            fresh = []
            for root, _dirs, names in os.walk(self._input_dir):
                for name in names:
                    path = os.path.join(root, name)
                    if name.lower().startswith("errorlog") and name.lower().endswith(".xlsx"):
                        try:
                            if os.path.getmtime(path) >= self._run_started_at:
                                fresh.append(path)
                        except OSError:
                            pass
            if not fresh:
                raise FileNotFoundError("本次运行未生成新的 errorlog.xlsx")
            path = max(fresh, key=os.path.getmtime)
            lines.append("3.16 扳手错已生成 errorlog.xlsx: %s" % path)
            QMessageBox.information(
                self.iface.mainWindow(), "3.16扳手错质检完成",
                "errorlog.xlsx 已生成。\n文件夹：%s\n日志：%s" % (os.path.dirname(path), self._log_path or ""),
            )
        except Exception as exc:
            lines.append("收集结果失败: %r" % (exc,))
            lines.append(traceback.format_exc())
            QMessageBox.warning(self.iface.mainWindow(), "3.16扳手错质检", "检查已执行，但未找到本次生成的 errorlog.xlsx。\n请查看 shpchecker 界面和日志。")
        self._write_log(lines)

    @staticmethod
    def _export_records_xlsx(records, folder):
        out_dir = os.path.join(folder, "3.16扳手错结果")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "3.16扳手错质检_%s.xlsx" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        headers = ["序号", "检测类型", "错误记录", "涉及图层", "涉及要素"]
        rows = [headers]
        for index, record in enumerate(records, 1):
            layers = record.get("display_layers", {})
            ids = record.get("display_ids", {})
            keys = list(dict.fromkeys(list(ids.keys()) + list(record.get("selections", {}).keys())))
            layer_text = ", ".join(layers.get(k, k) for k in keys)
            id_text = "; ".join("%s: %s" % (layers.get(k, k), ", ".join(map(str, ids.get(k, [])))) for k in keys)
            rows.append([index, record.get("type", ""), record.get("message", ""), layer_text, id_text])
        def cell(value):
            text = xml_escape(str(value if value is not None else ""))
            return '<c t="inlineStr"><is><t>%s</t></is></c>' % text
        sheet_rows = []
        for row_no, row in enumerate(rows, 1):
            sheet_rows.append('<row r="%d">%s</row>' % (row_no, "".join(cell(v) for v in row)))
        content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'''
        rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'''
        workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="质检结果" sheetId="1" r:id="rId1"/></sheets></workbook>'''
        workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'''
        sheet = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % "".join(sheet_rows)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", rels)
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)
        return path

    def run(self):
        folder = str(QSettings().value(self._input_dir_key, self._default_input_dir) or self._default_input_dir)
        if not os.path.isdir(folder):
            answer = QMessageBox.question(
                self.iface.mainWindow(), "转换数据目录不存在",
                "默认目录不存在，是否重新选择目录？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                return
            folder = self.configure_input_dir()
            if not folder or not os.path.isdir(folder):
                return
        self._input_dir = folder
        QSettings().setValue(self._input_dir_key, folder)
        self._all_log_lines = []
        paths, missing = self._find_files(folder)
        if missing:
            QMessageBox.warning(self.iface.mainWindow(), "输入文件不完整", "缺少以下文件：\n" + "\n".join(missing))
            return
        lines = ["输入目录: %s" % folder, "文件数量: %d" % len(paths)]
        lines.append("3.28 不加载输入图层；由 QGIS 3.16 子进程加载 19 个文件")
        if not self._start_checker(lines):
            self._write_log(lines)
            QMessageBox.critical(self.iface.mainWindow(), "无法启动 3.16 扳手错", "未能启动 shpchecker。\n请确认已安装并启用 shpchecker 插件。\n日志：%s" % (self._log_path or ""))
            return
        self._write_log(lines)
