# -*- coding: utf-8 -*-
"""通过 QGIS 3.16 子进程自动运行 jdchecker 质检插件。"""
from __future__ import annotations

import glob
import os
import subprocess
import tempfile
import shutil
import time
from datetime import datetime

from qgis.PyQt.QtCore import QSettings, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QProgressDialog


REQUIRED_SHP = (
    "CLEARAREA", "CROSSWALK", "FREEAREA", "GATE", "INTERSECTION",
    "LANE_GROUP", "LANE_MARKING", "LANE_NODE", "LANE", "PARKING",
    "PILLAR", "PROHIBITED_AREA", "ROAD_LINK", "SAFETYISLAND",
    "SPEEDBUMP", "STOPLINE", "TRAFFICLIGHT",
)
REQUIRED_REL = ("CROSSWALK_LANE_REL.dbf", "INTERSECTION_SIGNAL_REL.dbf")


class JdCheckerController:
    def __init__(self, iface, plugin_dir, log_fn=None):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.log = log_fn or print
        self.action = None
        self._process = None
        self._running = False
        self._cancelled = False
        self._run_started_at = 0.0
        self._log_path = None
        self._child_log_path = None
        self._progress = None
        self._progress_timer = None
        self._default_input_dir = os.path.join(plugin_dir, "转换数据", "output")
        self._input_dir_key = "LaneBatchUpdate/jdcheckerInputDir"
        self._plugin_stage_dir = None
        os.makedirs(self._default_input_dir, exist_ok=True)

    def _cleanup_run_ui(self):
        progress_timer = self._progress_timer
        self._progress_timer = None
        if progress_timer is not None:
            try:
                progress_timer.stop()
                progress_timer.deleteLater()
            except RuntimeError:
                pass
        progress = self._progress
        self._progress = None
        if progress is not None:
            try:
                progress.close()
                progress.deleteLater()
            except RuntimeError:
                pass
        stage_dir = self._plugin_stage_dir
        self._plugin_stage_dir = None
        if stage_dir:
            shutil.rmtree(stage_dir, ignore_errors=True)

    def _stop_process(self):
        """Stop the child QGIS process before releasing its Popen object."""
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass

    def initGui(self, actions_master):
        icon = QIcon(os.path.join(self.plugin_dir, "icon_jdchecker.svg"))
        self.action = QAction(icon, "自动走3.16质检错", self.iface.mainWindow())
        self.action.setToolTip("将19个数据文件交给 QGIS 3.16 jdchecker 自动质检")
        self.action.triggered.connect(self.run)
        self.iface.addPluginToVectorMenu("车道处理工具", self.action)
        actions_master.append(self.action)

    def unload(self):
        self._stop_process()
        self._cleanup_run_ui()
        if self.action is not None:
            try:
                self.iface.removeVectorToolBarIcon(self.action)
                self.iface.removePluginMenu("车道处理工具", self.action)
            except (AttributeError, RuntimeError):
                pass
        self.action = None

    @staticmethod
    def _find_files(folder):
        paths, missing = [], []
        for name in REQUIRED_SHP:
            path = os.path.join(folder, name + ".shp")
            (paths if os.path.isfile(path) else missing).append(path if os.path.isfile(path) else name + ".shp")
        for name in REQUIRED_REL:
            path = os.path.join(folder, name)
            (paths if os.path.isfile(path) else missing).append(path if os.path.isfile(path) else name)
        return paths, missing

    def _find_qgis_316(self):
        configured = str(QSettings().value("LaneBatchUpdate/qgis316Executable", "") or "")
        candidates = [configured] if configured else []
        candidates += [
            r"D:\qgis3.16\bin\qgis-bin.exe",
            r"D:\qgis3.16\bin\qgis-ltr-bin.exe",
            r"C:\Program Files\QGIS 3.16.16\bin\qgis-bin.exe",
            r"C:\Program Files\QGIS 3.16.15\bin\qgis-bin.exe",
            r"C:\Program Files\QGIS 3.16.14\bin\qgis-bin.exe",
            r"C:\OSGeo4W64\bin\qgis-bin.exe",
            r"C:\OSGeo4W\bin\qgis-bin.exe",
        ]
        for root in (r"C:\Program Files", r"C:\Program Files (x86)", r"D:\software"):
            candidates.extend(glob.glob(os.path.join(root, "QGIS 3.16*", "bin", "qgis-bin.exe")))
            candidates.extend(glob.glob(os.path.join(root, "QGIS3.16*", "bin", "qgis-bin.exe")))
        return next((os.path.abspath(path) for path in candidates if path and os.path.isfile(path)), "")

    def _write_log(self, lines):
        log_dir = os.path.join(self.plugin_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        self._log_path = os.path.join(log_dir, "jdchecker_316_%s.log" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        try:
            with open(self._log_path, "w", encoding="utf-8-sig") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass

    def _update_progress(self):
        if self._progress is None:
            return
        text = self._read_child_log()
        self._set_progress_from_log(text)
        if self._process is not None and self._process.poll() is None and not text:
            self._progress.setValue(min(15, self._progress.value() + 1))
            self._progress.setLabelText("正在启动 QGIS 3.16 VectorDataCheck…")

    def _start_progress(self):
        self._progress = QProgressDialog("正在启动 QGIS 3.16 jdchecker…", "取消", 0, 100, self.iface.mainWindow())
        self._progress.setWindowTitle("自动走3.16质检错")
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setValue(5)
        self._progress.canceled.connect(self._cancel_run)
        self._progress.show()
        self._progress_timer = QTimer(self._progress)
        self._progress_timer.timeout.connect(self._update_progress)
        self._progress_timer.start(1000)

    def _cancel_run(self):
        self._cancelled = True
        self._stop_process()
        self._cleanup_run_ui()

    def _read_child_log(self):
        if not self._child_log_path or not os.path.isfile(self._child_log_path):
            return ""
        try:
            with open(self._child_log_path, "r", encoding="utf-8-sig", errors="replace") as handle:
                return handle.read()
        except OSError:
            return ""

    def _set_progress_from_log(self, text):
        if self._progress is None:
            return
        # Use the furthest reached stage so later log lines cannot leave the
        # progress dialog showing the earlier 全选 state.
        stage = (0, "正在启动 QGIS 3.16 jdchecker…")
        markers = (
            (("loaded DLL",), 20, "已加载 jdchecker 插件"),
            (("triggered jdchecker action", "triggered Plugins -> jdchecker"), 35, "已点击 jdchecker 按钮"),
            (("VectorDataCheck window not found", "waiting for VectorDataCheck 全选"), 40, "等待 VectorDataCheck 窗口…"),
            (("clicked VectorDataCheck button: 全选", "selected all VectorDataCheck items"), 45, "已完成全选"),
            (("waiting for VectorDataCheck 执行检查",), 48, "等待执行检查按钮…"),
            (('clicked VectorDataCheck button: 执行检查', 'clicked VectorDataCheck button: 执行', 'execute_clicked:', '执行检查'), 60, '正在执行检查…'),
            (('closed VectorDataCheck window', 'closed native completion message', '检查完毕', '检查完成', '质检完毕', '质检完成', 'finished'), 100, '检查完毕'),
        )
        for markers_for_stage, value, label in markers:
            if any(marker in text for marker in markers_for_stage) and value > stage[0]:
                stage = (value, label)
        self._progress.setValue(max(self._progress.value(), stage[0]))
        if stage[0] >= self._progress.value():
            self._progress.setLabelText(stage[1])

    def run(self):
        if self._process is not None and self._process.poll() is None:
            QMessageBox.information(self.iface.mainWindow(), "3.16质检错", "质检正在后台执行，请等待当前任务完成。")
            return
        folder = str(QSettings().value(self._input_dir_key, self._default_input_dir) or self._default_input_dir)
        if not os.path.isdir(folder):
            folder = QFileDialog.getExistingDirectory(self.iface.mainWindow(), "选择转换后的数据目录", self._default_input_dir)
        if not folder:
            return
        paths, missing = self._find_files(folder)
        if missing:
            QMessageBox.warning(self.iface.mainWindow(), "输入文件不完整", "缺少以下文件：\n" + "\n".join(missing))
            return
        executable = self._find_qgis_316()
        if not executable:
            executable, _ = QFileDialog.getOpenFileName(self.iface.mainWindow(), "选择 QGIS 3.16 qgis-bin.exe", r"D:\qgis3.16", "QGIS 程序 (qgis-bin.exe);;所有文件 (*)")
        if not executable:
            return
        QSettings().setValue(self._input_dir_key, folder)
        runner = os.path.join(self.plugin_dir, "jdchecker_runner.py")
        dll = os.path.join(self.plugin_dir, "jdcheckerplugin.dll")
        if not os.path.isfile(dll):
            QMessageBox.warning(self.iface.mainWindow(), "缺少 jdchecker 插件", "未找到：%s\n请将 jdcheckerplugin.dll 放到插件目录。" % dll)
            return
        log_path = os.path.join(self.plugin_dir, "log", "jdchecker_child_%s.log" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        env = os.environ.copy()
        self._child_log_path = log_path
        env.update({
            "LANEBATCH_JDCHECKER_INPUT": folder,
            "LANEBATCH_JDCHECKER_DLL": dll,
            "LANEBATCH_JDCHECKER_LOG": log_path,
        })
        self._run_started_at = time.time()
        self._cancelled = False
        lines = ["输入目录: %s" % folder, "已确认19个输入文件", "jdchecker DLL: %s" % dll]
        try:
            qgis_root = os.path.abspath(os.path.join(os.path.dirname(executable), os.pardir))
            qgis_plugin_dir = os.path.join(qgis_root, "apps", "qgis", "plugins")
            if not os.path.isdir(qgis_plugin_dir):
                raise FileNotFoundError("未找到 QGIS 3.16 原生插件目录: %s" % qgis_plugin_dir)
            installed_dll = os.path.join(qgis_plugin_dir, "jdcheckerplugin.dll")
            shutil.copy2(dll, installed_dll)
            env["LANEBATCH_JDCHECKER_DLL"] = installed_dll
            lines.append("已安装 jdchecker 到 QGIS 原生插件目录: %s" % installed_dll)
            self._log_path = log_path
            self._start_progress()
            startupinfo = None
            creationflags = 0
            if os.name == "nt":
                startupinfo = None
                creationflags = 0
            self._process = subprocess.Popen(
                [executable, "--nologo", "--noversioncheck", "--new-instance", "--profile", "default", "--code", runner],
                cwd=os.path.dirname(executable), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                startupinfo=startupinfo, creationflags=creationflags,
            )
            self._running = True
            lines.append("已启动 QGIS 3.16 后台质检")
            self._write_log(lines)
            QTimer.singleShot(2000, self._poll)
        except Exception as exc:
            self._stop_process()
            self._cleanup_run_ui()
            lines.append("启动失败: %r" % (exc,))
            self._write_log(lines)
            QMessageBox.critical(self.iface.mainWindow(), "无法启动3.16质检错", "无法启动 QGIS 3.16。\n日志：%s" % self._log_path)

    def _poll(self):
        process = self._process
        if process is not None and process.poll() is None:
            self._set_progress_from_log(self._read_child_log())
            QTimer.singleShot(2000, self._poll)
            return
        if process is not None:
            try:
                process.wait(timeout=1)
            except (OSError, subprocess.SubprocessError):
                pass
        self._process = None
        self._running = False
        text = self._read_child_log()
        self._set_progress_from_log(text)
        completed = any(marker in text for marker in (
            "质检完成", "质检完毕", "检查完成", "检查完毕",
            "closed VectorDataCheck window", "closed native completion message", "finished"
        ))
        self._cleanup_run_ui()
        if self._cancelled:
            return
        if completed:
            QMessageBox.information(self.iface.mainWindow(), "3.16质检错完成", "质检完毕！")
        else:
            QMessageBox.warning(self.iface.mainWindow(), "3.16质检错", "质检进程已结束，请查看日志：\n%s" % (self._child_log_path or "无日志"))
