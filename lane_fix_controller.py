# -*- coding: utf-8 -*-
"""Excel 边线改错：选表格 + 自动使用工程内 LANE 图层。"""

from datetime import datetime
import os
import traceback

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QProgressDialog

from qgis.core import QgsProject, QgsVectorLayer

from .lane_fix_engine import LaneFixEngine
from .lane_fix_excel import parse_fix_actions
from .reconstruct_config import load_algorithm_ids
from .reconstruct_feedback import ReconstructFeedback
from .reconstruct_workflow import ReconstructWorkflow


class LaneFixController:
    """对齐 ProcessShpFiles：读取质检 Excel，自动修复 LANE 边线关联。"""

    MODE_FIX = "lane_fix_excel"

    def __init__(self, iface, plugin_dir, log_fn):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.log = log_fn
        self.actions = []
        self.log_lines = []

    def initGui(self, actions_master):
        icon_path = os.path.join(self.plugin_dir, "icon_lane_fix.png")
        action = QAction(QIcon(icon_path), "Excel边线改错", self.iface.mainWindow())
        action.triggered.connect(self.run)
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

    def _save_log(self):
        if not self.log_lines:
            return None
        log_dir = os.path.join(self.plugin_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"log_lane_fix_{datetime.now():%Y-%m-%d}.txt")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(self.log_lines) + "\n")
        return path

    @staticmethod
    def _get_lane_layer():
        project = QgsProject.instance()
        for name in ("LANE",):
            layers = project.mapLayersByName(name)
            if layers and isinstance(layers[0], QgsVectorLayer):
                return layers[0]
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            src = layer.source().split("|", 1)[0]
            if os.path.basename(src).lower() == "lane.shp":
                return layer
        return None

    def run(self):
        self.log_lines = []
        lane_layer = self._get_lane_layer()
        if lane_layer is None:
            QMessageBox.critical(None, "图层缺失", "请先在 QGIS 中加载 LANE 图层")
            return

        excel_path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "选择 3.16 质检导出的错误表格",
            "",
            "表格文件 (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv);;所有文件 (*.*)",
        )
        if not excel_path:
            return

        self._log(f"错误表格: {excel_path}")
        self._log(f"LANE 图层: {lane_layer.name()} ({lane_layer.source()})")

        progress = QProgressDialog("Excel边线改错", "取消", 0, 0, self.iface.mainWindow())
        progress.setWindowTitle("Excel边线改错")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        feedback = ReconstructFeedback(progress, self._log)
        workflow = ReconstructWorkflow(self.iface, self.plugin_dir, self._log)
        algorithm_ids = load_algorithm_ids(self.plugin_dir)

        try:
            actions = parse_fix_actions(excel_path)
            if not actions:
                QMessageBox.warning(
                    None,
                    "未识别到可修复项",
                    "表格中没有解析到可自动修复的边线错误。\n\n"
                    "请确认导出的是 3.16 扳手/边线类错误，且含类似以下描述：\n"
                    "· lmark_l/lmark_r 缺失或关联错误\n"
                    "· RBDY_L/RBDY_R 缺失或不应记录的边线\n\n"
                    "信号灯、left_rvs 顺序等错误需手动处理。",
                )
                return

            auto_count = sum(1 for item in actions if item.action != "skip")
            skip_count = len(actions) - auto_count
            reply = QMessageBox.question(
                None,
                "Excel边线改错",
                f"已解析 {len(actions)} 条记录\n"
                f"  可自动修复: {auto_count} 条\n"
                f"  需手动处理: {skip_count} 条\n\n"
                f"将修改当前 LANE 图层，然后自动执行步骤 8、9（Z Tools）\n"
                f"并保存工程中全部矢量图层。\n\n"
                f"请确认已安装 Z Tools 且工具栏按钮可见。\n\n"
                f"是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

            progress.setLabelText("正在修复边线字段…")
            engine = LaneFixEngine(lane_layer, self._log)
            stats = engine.apply_actions(actions)
            lane_layer.triggerRepaint()

            progress.setLabelText("边线修复完成，正在执行步骤 8、9…")
            saved = workflow.run_steps_8_9_and_save(feedback, algorithm_ids)

            log_path = self._save_log()
            log_hint = log_path or os.path.join(self.plugin_dir, "log")
            QMessageBox.information(
                None,
                "修复完毕",
                f"解析 {stats['total']} 条\n"
                f"成功改字段 {stats['applied']} 次\n"
                f"更新要素 {stats['features_updated']} 条\n"
                f"未找到车道 {stats['not_found']} 条\n"
                f"跳过 {stats['skipped']} 条\n"
                f"步骤 8、9 后保存图层 {saved} 个\n\n"
                f"日志: {log_hint}",
            )
        except Exception as exc:
            self._log(traceback.format_exc(), level="ERROR", show_bar=False)
            log_path = self._save_log()
            QMessageBox.critical(
                None,
                "改错失败",
                f"{exc}\n\n请检查 Z Tools 步骤 8、9 按钮是否可见。\n"
                f"日志: {log_path or '无'}",
            )
        finally:
            progress.close()
