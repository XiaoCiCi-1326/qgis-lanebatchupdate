# -*- coding: utf-8 -*-
"""一键重构：工具栏按钮与进度对话框。"""

from datetime import datetime
import os
import traceback

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QProgressDialog

from .reconstruct_config import DIR_ORIGINAL, load_algorithm_ids
from .reconstruct_feedback import ReconstructFeedback
from .reconstruct_workflow import ReconstructWorkflow


class ReconstructController:
    """独立于限速/转向/ROAD_TYPE 三个按钮的重构功能入口。"""

    MODE_PREP = "reconstruct_prep"
    MODE_FULL = "reconstruct_full"
    MODE_OPEN_ORIG = "reconstruct_open_orig"
    MODE_FILL_RBDY = "fill_rbdy"

    def __init__(self, iface, plugin_dir, log_fn):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.log = log_fn
        self.actions = []
        self.log_lines = []

    def initGui(self, actions_master):
        buttons = (
            (self.MODE_PREP, "准备三份数据", "icon_reconstruct_prep.png", "run"),
            (self.MODE_FULL, "一键重构(全程)", "icon_reconstruct_full.png", "run"),
            (self.MODE_FILL_RBDY, "全量补空RBDY", "icon_fill_rbdy.png", "fill_rbdy"),
            (self.MODE_OPEN_ORIG, "打开原始文件", "icon_reconstruct_open.png", "open"),
        )
        for mode, label, icon_name, action_type in buttons:
            icon_path = os.path.join(self.plugin_dir, icon_name)
            action = QAction(QIcon(icon_path), label, self.iface.mainWindow())
            if action_type == "open":
                action.triggered.connect(self.open_original_folder)
            elif action_type == "fill_rbdy":
                action.triggered.connect(self.fill_empty_rbdy)
            else:
                action.triggered.connect(lambda checked=False, m=mode: self.run(m))
            self.iface.addVectorToolBarIcon(action)
            self.iface.addPluginToVectorMenu("车道处理工具", action)
            self.actions.append(action)
            actions_master.append(action)

    def unload(self):
        for action in self.actions:
            self.iface.removeVectorToolBarIcon(action)
            self.iface.removePluginFromVectorMenu("车道处理工具", action)
        self.actions = []

    def _log(self, text, level="INFO", show_bar=True):
        line = f"{datetime.now():%H:%M:%S} [{level}] {text}"
        self.log_lines.append(line)
        self.log(text, level=level, show_bar=show_bar)

    def _save_log(self, prefix):
        if not self.log_lines:
            return None
        log_dir = os.path.join(self.plugin_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"log_{prefix}_{datetime.now():%Y-%m-%d}.txt")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(self.log_lines) + "\n")
        return path

    def fill_empty_rbdy(self):
        """全量扫描 LANE 补空 RBDY：独立按钮，在一键重构之后使用。"""
        from .lane_fix_engine import LaneFixEngine
        from qgis.core import(QgsProject, QGIS_VERSION)
        import re

        self._log("===== 全量补空RBDY =====")

        # 找 LANE 图层
        lane_layer = None
        for name, layer in list(QgsProject.instance().mapLayers().items()):
            if re.search(r"(?:^|_)lane(?:s)?(?:_|$|layer)", name, re.I) and layer.geometryType() in (1, 2):
                if lane_layer is None or (layer.type() == 0 and layer.storageType() == "ESRI Shapefile"):
                    lane_layer = layer
                    break

        if lane_layer is None:
            self._log("未找到 LANE 图层", level="WARN")
            QMessageBox.warning(self.iface.mainWindow(), "未找到图层", "请先加载 LANE/边线图层")
            return

        if not lane_layer.isEditable() and not lane_layer.startEditing():
            self._log("无法开启图层编辑", level="WARN")
            return

        engine = LaneFixEngine(lane_layer, self._log)
        result = engine.scan_and_fill_all_empty_rbdy()

        total = result["left"] + result["right"] + result["fallback"]
        self._log(f"全量补空RBDY完成: left={result['left']} right={result['right']} fallback={result['fallback']} 总计={total}")
        self._log("注意：此步骤建议在修复 Excel 错误之后执行，避免填入错误关联", level="WARN")
        self._save_log("fill_rbdy")

        QMessageBox.information(
            self.iface.mainWindow(), "全量补空RBDY",
            f"补空完成\n左侧={result['left']} 右侧={result['right']} fallback={result['fallback']}\n总计={total} 条"
        )

    def _pick_source_dir(self, workflow):
        """未自动识别源目录时，弹出文件夹选择。"""
        start = workflow.data_dir or workflow.detect_data_dir() or self.plugin_dir
        folder = QFileDialog.getExistingDirectory(
            self.iface.mainWindow(),
            "选择原始数据目录（含 LANE.shp、BOUNDARY.shp 等）",
            start,
        )
        if not folder:
            return None
        return folder

    def _resolve_source_with_dialog(self, workflow, require_source=False):
        """自动识别；失败则询问是否手动选目录。"""
        try:
            return workflow.resolve_source_dir(require_source=require_source), False
        except RuntimeError as exc:
            reply = QMessageBox.question(
                None,
                "未找到原始数据",
                f"{exc}\n\n是否手动选择原始数据文件夹？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                raise RuntimeError("已取消：未指定原始数据目录")
            picked = self._pick_source_dir(workflow)
            if not picked:
                raise RuntimeError("已取消：未选择数据目录")
            return workflow.resolve_source_dir(picked, require_source=require_source), True

    def _confirm(self, title, message):
        reply = QMessageBox.question(
            None,
            title,
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def open_original_folder(self):
        """在资源管理器中打开插件目录下的「原始文件」文件夹。"""
        folder = os.path.join(self.plugin_dir, DIR_ORIGINAL)
        if not os.path.isdir(folder):
            QMessageBox.warning(
                None,
                "打开原始文件",
                f"「原始文件」目录尚不存在：\n{folder}\n\n请先执行「准备三份数据」或「一键重构」。",
            )
            return
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        if ok:
            self.log(f"已打开文件夹: {folder}", show_bar=False)
        else:
            QMessageBox.warning(None, "打开原始文件", f"无法打开文件夹:\n{folder}")

    def run(self, mode):
        self.log_lines = []
        titles = {
            self.MODE_PREP: "准备三份数据",
            self.MODE_FULL: "一键重构(全程)",
        }
        title = titles.get(mode, "一键重构")

        if mode == self.MODE_PREP:
            confirm_msg = (
                "将把源目录全部文件直接覆盖复制三份到插件目录：\n"
                "  原始文件 / 删除129 / 删除11以外\n\n"
                "仅卸载指向上述目录的图层（不清空整个工程）。\n\n"
                "是否继续？"
            )
        else:
            confirm_msg = (
                "一键重构将分步处理（中间会重新加载图层）。\n"
                "三份副本直接覆盖写入插件目录：\n"
                "  原始文件 / 删除129 / 删除11以外\n\n"
                "收尾会重新加载「原始文件」全部 shp，执行步骤 8、9 并保存，"
                "完成后图层保留在工程中。\n"
                "步骤 6~9 依赖 Z Attribute / Z Tools 工具栏按钮。\n\n"
                "是否继续？"
            )

        if not self._confirm(title, confirm_msg):
            return

        progress = QProgressDialog(f"正在执行: {title}", "取消", 0, 0, self.iface.mainWindow())
        progress.setWindowTitle("车道一键重构")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        feedback = ReconstructFeedback(progress, self._log)
        workflow = ReconstructWorkflow(self.iface, self.plugin_dir, self._log)
        algorithm_ids = load_algorithm_ids(self.plugin_dir)

        try:
            if mode == self.MODE_PREP:
                source, _ = self._resolve_source_with_dialog(workflow, require_source=True)
                workflow.data_dir = source
                workflow.copy_three_workdirs(source, keep_project_layers=True)
                done = f"三份数据已覆盖复制到插件目录\n源: {source}"
            elif mode == self.MODE_FULL:
                source, _ = self._resolve_source_with_dialog(workflow, require_source=False)
                workflow.run_full(
                    feedback,
                    algorithm_ids,
                    copy_only=False,
                    source_dir=source,
                )
                done = "一键重构全部完成（含步骤 8、9，图层已保留在工程中）"
            else:
                return

            log_path = self._save_log("reconstruct")
            hint = log_path or os.path.join(self.plugin_dir, "log")
            QMessageBox.information(None, "完成", f"{done}\n日志: {hint}")
        except Exception as exc:
            self._log(traceback.format_exc(), level="ERROR", show_bar=False)
            log_path = self._save_log("reconstruct")
            QMessageBox.critical(
                None,
                "重构失败",
                f"{exc}\n\n请检查:\n"
                "1. 是否已安装 Z Attribute / Z Tools 且工具栏四按钮可见\n"
                "2. 是否从「原始数据目录」而非插件副本加载/选择数据\n"
                "3. 若工具栏找不到按钮，可配置 reconstruct_algorithms.json\n"
                f"4. 日志: {log_path or '无'}",
            )
        finally:
            progress.close()
