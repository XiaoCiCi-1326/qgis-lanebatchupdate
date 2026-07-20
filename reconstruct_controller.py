# -*- coding: utf-8 -*-
"""一键重构：工具栏按钮与进度对话框。"""

from datetime import datetime
import os
import traceback

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QProgressDialog

from .reconstruct_config import load_algorithm_ids
from .reconstruct_feedback import ReconstructFeedback
from .reconstruct_workflow import ReconstructWorkflow


class ReconstructController:
    """独立于限速/转向/ROAD_TYPE 三个按钮的重构功能入口。"""

    MODE_PREP = "reconstruct_prep"
    MODE_PASS1 = "reconstruct_pass1"
    MODE_PASS2 = "reconstruct_pass2"
    MODE_FULL = "reconstruct_full"

    def __init__(self, iface, plugin_dir, log_fn):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.log = log_fn
        self.actions = []
        self.log_lines = []

    def initGui(self, actions_master):
        buttons = (
            (self.MODE_PREP, "准备三份数据", "icon_reconstruct_prep.png"),
            (self.MODE_PASS1, "第一次重构", "icon_reconstruct_pass1.png"),
            (self.MODE_PASS2, "第二次重构", "icon_reconstruct_pass2.png"),
            (self.MODE_FULL, "一键重构(全程)", "icon_reconstruct_full.png"),
        )
        for mode, label, icon_name in buttons:
            icon_path = os.path.join(self.plugin_dir, icon_name)
            action = QAction(QIcon(icon_path), label, self.iface.mainWindow())
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

    def run(self, mode):
        self.log_lines = []
        titles = {
            self.MODE_PREP: "准备三份数据",
            self.MODE_PASS1: "第一次重构",
            self.MODE_PASS2: "第二次重构",
            self.MODE_FULL: "一键重构(全程)",
        }
        title = titles.get(mode, "一键重构")

        if not self._confirm(
            title,
            "将清空当前 QGIS 工程中的图层（不删除磁盘文件）。\n"
            "三份副本写入插件目录：\n"
            "  原始文件 / 删除129 / 删除11以外\n\n"
            "请勿从上述副本目录加载图层作为源数据。\n"
            "步骤 6~9 依赖您已安装的 QGIS 插件，耗时较长。\n"
            "若自动找不到工具，请配置 reconstruct_algorithms.json\n\n"
            "是否继续？",
        ):
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
                workflow.copy_three_workdirs(source)
                done = f"三份数据已复制到插件目录\n源: {source}"
            elif mode == self.MODE_PASS1:
                workflow.ensure_workdirs()
                workflow.run_pass(1, feedback, algorithm_ids)
                workflow.remove_all_layers()
                done = "第一次重构完成，LANE 已写回「原始文件」"
            elif mode == self.MODE_PASS2:
                workflow.ensure_workdirs()
                workflow.run_pass(2, feedback, algorithm_ids)
                workflow.remove_all_layers()
                done = "第二次重构完成，LANE 已写回「原始文件」"
            elif mode == self.MODE_FULL:
                source, _ = self._resolve_source_with_dialog(workflow, require_source=False)
                workflow.run_full(
                    feedback,
                    algorithm_ids,
                    copy_only=False,
                    source_dir=source,
                )
                done = "一键重构（两次）全部完成"
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
