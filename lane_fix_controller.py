# -*- coding: utf-8 -*-
"""Excel 边线改错：选表格 + 自动使用工程内 LANE 图层。"""

from datetime import datetime
import os
import traceback

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QProgressDialog

from qgis.core import QgsProject, QgsVectorLayer

from .lane_fix_engine import GenericLayerFixer, LaneFixEngine
from .lane_fix_excel import parse_fix_actions
from .reconstruct_config import load_algorithm_ids
from .reconstruct_feedback import ReconstructFeedback
from .reconstruct_workflow import ReconstructWorkflow


class LaneFixController:
    """对齐 ProcessShpFiles：读取质检 Excel，自动修复 LANE 边线关联。"""

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
    def _get_layer_by_name(name):
        project = QgsProject.instance()
        layers = project.mapLayersByName(name)
        if layers:
            return layers[0]
        for layer in project.mapLayers().values():
            src = os.path.basename(layer.source().split("|", 1)[0])
            if src.lower() == f"{name.lower()}.shp":
                return layer
        return None

    def run(self):

        self.log_lines = []



        lane_layer = self._get_layer_by_name("LANE")

        if lane_layer is None:

            QMessageBox.critical(None, "图层缺失", "请先在 QGIS 中加载 LANE 图层")

            return



        roadlink_layer = self._get_layer_by_name("ROAD_LINK")

        signal_layer = self._get_layer_by_name("SIGNAL")

        if roadlink_layer:

            self._log("ROAD_LINK 图层: " + roadlink_layer.name(), show_bar=False)

        if signal_layer:

            self._log("SIGNAL 图层: " + signal_layer.name(), show_bar=False)



        excel_path, _ = QFileDialog.getOpenFileName(

            self.iface.mainWindow(),

            "选择 3.16 质检导出的错误表格",

            "",

            "表格文件 (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv);;所有文件 (*.*)",

        )

        if not excel_path:

            return



        self._log("错误表格: " + excel_path)

        self._log("LANE 图层: " + lane_layer.name() + " (" + lane_layer.source() + ")")



        progress = QProgressDialog("Excel边线改错", "取消", 0, 0, self.iface.mainWindow())

        progress.setWindowTitle("Excel边线改错")

        progress.setWindowModality(Qt.WindowModal)

        progress.setMinimumDuration(0)

        progress.show()



        feedback = ReconstructFeedback(progress, self._log)

        workflow = ReconstructWorkflow(self.iface, self.plugin_dir, self._log)

        algorithm_ids = load_algorithm_ids(self.plugin_dir)



        try:

            all_actions = parse_fix_actions(excel_path)

            if not all_actions:

                QMessageBox.warning(

                    None,

                    "未识别到可修复项",

                    "表格中没有解析到可自动修复的错误。\n\n"

                    "当前支持：\n"

                    "· left_rvs 互挂补充 / 顺序交换\n"

                    "· RBDY/BDY 缺失、左右侧位错误、错误关联删除\n"

                    "· LINKID= 格式 2.2/2.3 不应记录与缺失边线\n"

                    "· BDYID_L/R 为空：从对向车道 LEFT_RVS 推断 RBDY\n"

                    "· 路口 lane BDYID 错误关联/缺失（ROAD_LINK 层）\n"

                    "· 虚拟路口 SIGNAL LANES 关联错误（SIGNAL 层）\n\n"

                    "路沿石冲突(2.1)等仍需手动处理。",

                )

                return



            lane_actions = [a for a in all_actions if a.layer == "LANE"]

            roadlink_actions = [a for a in all_actions if a.layer == "ROAD_LINK"]

            signal_actions = [a for a in all_actions if a.layer == "SIGNAL"]

            auto_count = sum(1 for a in all_actions if a.action != "skip")

            skip_count = len(all_actions) - auto_count

            layers_info = "LANE({})".format(len(lane_actions))

            if roadlink_actions:

                layers_info += " ROAD_LINK({})".format(len(roadlink_actions))

            if signal_actions:

                layers_info += " SIGNAL({})".format(len(signal_actions))

            reply = QMessageBox.question(

                None,

                "Excel边线改错",

                "已解析 {} 条指令\n"

                "  可自动修复: {} 条\n"

                "  需手动处理: {} 条\n"

                "  分布: {}\n\n"

                "按 Excel 指令修复（先删后移后补），然后执行步骤 8、9 并保存。\n\n"

                "是否继续？".format(len(all_actions), auto_count, skip_count, layers_info),

                QMessageBox.Yes | QMessageBox.No,

                QMessageBox.No,

            )

            if reply != QMessageBox.Yes:

                return



            all_stats = {}



            # Excel 中的 fill_from_lrvs 指令已由 apply_all 处理，此处不再全量扫描
            self._log("===== 解析完成，开始执行 Excel 指令 =====")

            # LANE 层

            if lane_actions:

                progress.setLabelText("正在修复 LANE 边线字段（可多轮）…")

                engine = LaneFixEngine(lane_layer, self._log)

                stats = engine.apply_all(lane_actions)

                # 强制提交 LANE，确保修改落盘，防止步骤 8/9 覆盖
                try:
                    if lane_layer.isEditable() and not lane_layer.commitChanges():
                        errors = "; ".join(lane_layer.commitErrors())
                        self._log(f"LANE 提交失败: {errors}", level="WARN")
                    else:
                        lane_layer.triggerRepaint()
                        self._log("LANE 修改已提交", show_bar=False)
                except Exception as exc:
                    self._log(f"LANE 提交异常: {exc}", level="WARN")

                all_stats["LANE"] = stats

            else:

                all_stats["LANE"] = {"total":0,"applied":0,"skipped":0,"not_found":0,"features_updated":0,"rounds":0}



            # ROAD_LINK 层

            if roadlink_actions:

                if roadlink_layer is None:

                    self._log("ROAD_LINK 图层未加载，忽略 2.5/2.6 错误", level="WARN")

                else:

                    progress.setLabelText("正在修复 ROAD_LINK BDYID 字段…")

                    fixer = GenericLayerFixer(roadlink_layer, self._log)

                    stats = fixer.apply_actions(roadlink_actions)

                    try:
                        if roadlink_layer.isEditable() and not roadlink_layer.commitChanges():
                            errors = "; ".join(roadlink_layer.commitErrors())
                            self._log(f"ROAD_LINK 提交失败: {errors}", level="WARN")
                        else:
                            roadlink_layer.triggerRepaint()
                            self._log("ROAD_LINK 修改已提交", show_bar=False)
                    except Exception as exc:
                        self._log(f"ROAD_LINK 提交异常: {exc}", level="WARN")

                    all_stats["ROAD_LINK"] = stats



            # SIGNAL 层

            if signal_actions:

                if signal_layer is None:

                    self._log("SIGNAL 图层未加载，忽略 4.2 错误", level="WARN")

                else:

                    progress.setLabelText("正在修复 SIGNAL LANES 字段…")

                    fixer = GenericLayerFixer(signal_layer, self._log)

                    stats = fixer.apply_actions(signal_actions)

                    try:
                        if signal_layer.isEditable() and not signal_layer.commitChanges():
                            errors = "; ".join(signal_layer.commitErrors())
                            self._log(f"SIGNAL 提交失败: {errors}", level="WARN")
                        else:
                            signal_layer.triggerRepaint()
                            self._log("SIGNAL 修改已提交", show_bar=False)
                    except Exception as exc:
                        self._log(f"SIGNAL 提交异常: {exc}", level="WARN")

                    all_stats["SIGNAL"] = stats






            # 步骤 8、9

            progress.setLabelText("边线修复完成，正在执行步骤 8、9…")

            saved = workflow.run_steps_8_9_and_save(feedback, algorithm_ids)



            log_path = self._save_log()

            log_hint = log_path or os.path.join(self.plugin_dir, "log")



            lines = ["解析指令 {} 条".format(len(all_actions))]

            for ln in ("LANE", "ROAD_LINK", "SIGNAL"):

                if ln in all_stats:

                    s = all_stats[ln]

                    lines.append("{}层: applied={} updated={} not_found={}".format(

                        ln, s.get("applied",0), s.get("features_updated",0), s.get("not_found",0)))

            lines.append("步骤 8、9 后保存图层 {} 个".format(saved))

            QMessageBox.information(

                None,

                "修复完毕",

                "\n".join(lines) + "\n\n"

                "若仍有错误，请再导出表格后重跑一遍。\n"

                "日志: " + log_hint,

            )

        except Exception as exc:

            self._log(traceback.format_exc(), level="ERROR", show_bar=False)

            log_path = self._save_log()

            QMessageBox.critical(

                None,

                "改错失败",

                "{} \n\n请检查 Z Tools 步骤 8、9 按钮是否可见。\n"

                "日志: {}".format(exc, log_path or "无"),

            )

        finally:

            progress.close()



