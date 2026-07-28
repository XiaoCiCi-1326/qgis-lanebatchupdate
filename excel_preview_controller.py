# -*- coding: utf-8 -*-
"""Excel 边线改错的预览控制器：选文件 → 解析 → 弹对话框 → 执行勾选。

复用 LaneFixController / LaneFixEngine 的引擎，dry_run 标志由 engine 接管。
"""
from __future__ import annotations

import csv
import json
import os
import re
import traceback
from datetime import datetime
from typing import Dict, List, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QFileDialog,
    QMessageBox,
    QProgressDialog,
)

from qgis.core import QgsProject, QgsVectorLayer

from .excel_preview_dialog import ExcelPreviewDialog
from .lane_fix_engine import GenericLayerFixer, LaneFixEngine
from .lane_fix_excel import (
    LaneFixAction,
    load_table_rows,
    parse_error_texts,
    sort_fix_actions,
)
from .reconstruct_config import load_algorithm_ids
from .reconstruct_feedback import ReconstructFeedback
from .reconstruct_workflow import ReconstructWorkflow


class ExcelPreviewController:
    """Excel 边线改错：解析 → 弹对话框多选 → 一键修复（可 dry-run）。"""

    def __init__(self, iface, plugin_dir: str, log_fn):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.log = log_fn
        self.log_lines: List[str] = []
        self.actions = []

    def initGui(self, actions_master: list):
        icon_path = os.path.join(self.plugin_dir, "icon_lane_fix.png")
        action = QAction(QIcon(icon_path), "预览后修复", self.iface.mainWindow())
        action.setToolTip("解析 Excel 后弹出错误清单，可勾选/全选/反选，再一键修复")
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

    # ---------- 日志 ----------

    def _log(self, text: str, level: str = "INFO", show_bar: bool = True):
        line = f"{datetime.now():%H:%M:%S} [{level}] {text}"
        self.log_lines.append(line)
        self.log(text, level=level, show_bar=show_bar)

    def _save_log(self) -> Optional[str]:
        if not self.log_lines:
            return None
        log_dir = os.path.join(self.plugin_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"log_preview_{datetime.now():%Y-%m-%d}.txt")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(self.log_lines) + "\n")
        return path

    # ---------- 图层 ----------

    @staticmethod
    def _get_layer_by_name(name: str):
        project = QgsProject.instance()
        layers = project.mapLayersByName(name)
        if layers:
            return layers[0]
        for layer in project.mapLayers().values():
            src = os.path.basename(layer.source().split("|", 1)[0])
            if src.lower() == f"{name.lower()}.shp":
                return layer
        return None

    # ---------- 解析 + 行号 ----------

    def _parse_with_rows(self, path: str) -> List[LaneFixAction]:
        """与 parse_fix_actions 等价，但每个 action 附带 source_text 所在 Excel 行号。"""
        rows = load_table_rows(path)
        actions: List[LaneFixAction] = []
        seen = set()

        for row_idx, cells in enumerate(rows, start=1):
            header_hint = "".join(cells)
            if "检查分组" in header_hint or (
                "问题描述" in header_hint and "检查项" in header_hint
            ):
                continue

            problem_cells = [
                c
                for c in cells
                if "【问题" in c or "互为对方left_rvs" in c.lower()
            ]
            if not problem_cells:
                problem_cells = [
                    c
                    for c in cells
                    if re.search(
                        r"linkid|laneid|left_rvs|lmark_[lr]|缺失|错误|不应记录|顺序不对",
                        c,
                        re.I,
                    )
                ]

            for desc in problem_cells:
                for action in parse_error_texts(desc):
                    action.excel_row = row_idx
                    key = (
                        action.action,
                        action.target_field,
                        action.target_field_to,
                        action.match_field,
                        action.match_value,
                        tuple(action.mark_ids),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    actions.append(action)
        return sort_fix_actions(actions)

    # ---------- 主流程 ----------

    def run(self):
        lane_layer = self._get_layer_by_name("LANE")
        if lane_layer is None:
            QMessageBox.critical(None, "图层缺失", "请先在 QGIS 中加载 LANE 图层")
            return

        roadlink_layer = self._get_layer_by_name("ROAD_LINK")
        signal_layer = self._get_layer_by_name("SIGNAL")

        excel_path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "选择 3.16 质检导出的错误表格",
            "",
            "表格文件 (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv);;所有文件 (*.*)",
        )
        if not excel_path:
            return

        self.log_lines = []
        self._log(f"错误表格: {excel_path}")
        self._log(f"LANE 图层: {lane_layer.name()} ({lane_layer.source()})")
        if roadlink_layer:
            self._log(f"ROAD_LINK 图层: {roadlink_layer.name()}", show_bar=False)
        if signal_layer:
            self._log(f"SIGNAL 图层: {signal_layer.name()}", show_bar=False)

        try:
            all_actions = self._parse_with_rows(excel_path)
        except Exception as exc:
            self._log(traceback.format_exc(), level="ERROR", show_bar=False)
            QMessageBox.critical(None, "解析失败", f"{exc}")
            return

        if not all_actions:
            QMessageBox.warning(
                None,
                "未识别到可修复项",
                "表格中没有解析到可自动修复的错误。",
            )
            return

        progress = QProgressDialog("加载预览", "取消", 0, 0, self.iface.mainWindow())
        progress.setWindowTitle("Excel 边线改错")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.setAutoReset(True)
        progress.show()

        try:
            dlg = ExcelPreviewDialog(
                self.iface.mainWindow(),
                actions=all_actions,
                excel_path=excel_path,
                on_apply=lambda selected, dry_run: self._apply_selected(
                    selected,
                    dry_run,
                    lane_layer,
                    roadlink_layer,
                    signal_layer,
                ),
            )
            progress.close()
            progress.deleteLater()
            dlg.exec_()
        except Exception as exc:
            self._log(traceback.format_exc(), level="ERROR", show_bar=False)
            QMessageBox.critical(None, "预览失败", f"{exc}")
        finally:
            if progress is not None:
                try:
                    progress.close()
                    progress.deleteLater()
                except RuntimeError:
                    pass

        log_path = self._save_log()
        if log_path:
            self._log(f"日志: {log_path}", show_bar=False)

    # ---------- 执行勾选 ----------

    def _apply_selected(
        self,
        selected: List[LaneFixAction],
        dry_run: bool,
        lane_layer: QgsVectorLayer,
        roadlink_layer: Optional[QgsVectorLayer],
        signal_layer: Optional[QgsVectorLayer],
    ) -> Optional[Dict]:
        if not selected:
            return None

        mode = "[预览] " if dry_run else "[执行] "
        self._log(f"{mode}===== 用户勾选 {len(selected)} 条，开始执行 =====")

        lane_actions = [a for a in selected if (a.layer or "LANE") == "LANE"]
        roadlink_actions = [a for a in selected if a.layer == "ROAD_LINK"]
        signal_actions = [a for a in selected if a.layer == "SIGNAL"]

        per_action_status: Dict[int, str] = {}
        stats: Dict[str, Dict] = {}

        try:
            if lane_actions:
                self._log(f"{mode}LANE {len(lane_actions)} 条")
                engine = LaneFixEngine(lane_layer, self._log, dry_run=dry_run)
                stats["LANE"] = engine.apply_all(lane_actions)
                lane_layer.triggerRepaint()
                # 给每条 action 写状态
                for a in lane_actions:
                    row_no = getattr(a, "excel_row", None)
                    if row_no is None:
                        continue
                    note = a.note or a.action
                    per_action_status[row_no] = "OK" if note else "?"

            if roadlink_actions:
                if roadlink_layer is None:
                    self._log(
                        f"{mode}ROAD_LINK 图层未加载，忽略 {len(roadlink_actions)} 条",
                        level="WARN",
                    )
                else:
                    self._log(f"{mode}ROAD_LINK {len(roadlink_actions)} 条")
                    fixer = GenericLayerFixer(
                        roadlink_layer, self._log, dry_run=dry_run
                    )
                    stats["ROAD_LINK"] = fixer.apply_actions(roadlink_actions)
                    roadlink_layer.triggerRepaint()
                    for a in roadlink_actions:
                        row_no = getattr(a, "excel_row", None)
                        if row_no is not None:
                            per_action_status[row_no] = "OK"

            if signal_actions:
                if signal_layer is None:
                    self._log(
                        f"{mode}SIGNAL 图层未加载，忽略 {len(signal_actions)} 条",
                        level="WARN",
                    )
                else:
                    self._log(f"{mode}SIGNAL {len(signal_actions)} 条")
                    fixer = GenericLayerFixer(
                        signal_layer, self._log, dry_run=dry_run
                    )
                    stats["SIGNAL"] = fixer.apply_actions(signal_actions)
                    signal_layer.triggerRepaint()
                    for a in signal_actions:
                        row_no = getattr(a, "excel_row", None)
                        if row_no is not None:
                            per_action_status[row_no] = "OK"

            # 写改动报告
            self._write_report(selected, stats, dry_run)

            if not dry_run:
                # 真执行：跑步骤 8/9 并保存
                self._log(f"{mode}正在执行步骤 8、9 并保存…")
                workflow = ReconstructWorkflow(self.iface, self.plugin_dir, self._log)
                algorithm_ids = load_algorithm_ids(self.plugin_dir)
                progress = QProgressDialog(
                    "步骤 8、9 执行中…", "取消", 0, 0, self.iface.mainWindow()
                )
                progress.setWindowTitle("步骤 8、9")
                progress.setWindowModality(Qt.WindowModal)
                progress.setMinimumDuration(0)
                progress.setAutoClose(True)
                progress.setAutoReset(True)
                progress.show()
                fb = ReconstructFeedback(progress, self._log)
                try:
                    workflow.run_steps_8_9_and_save(fb, algorithm_ids)
                finally:
                    progress.close()
                    progress.deleteLater()

            summary_lines = [f"{mode}完成"]
            for ln in ("LANE", "ROAD_LINK", "SIGNAL"):
                if ln in stats:
                    s = stats[ln]
                    summary_lines.append(
                        f"  {ln}: applied={s.get('applied', 0)} "
                        f"updated={s.get('features_updated', 0)} "
                        f"not_found={s.get('not_found', 0)}"
                    )
            self._log("  ".join(summary_lines))
            return {"per_action_status": per_action_status, "stats": stats}
        except Exception as exc:
            self._log(traceback.format_exc(), level="ERROR", show_bar=False)
            QMessageBox.critical(
                None,
                "执行失败",
                f"{exc}\n\n日志已写入。",
            )
            return None

    # ---------- 报告 csv ----------

    def _write_report(
        self, actions: List[LaneFixAction], stats: Dict[str, Dict], dry_run: bool
    ):
        log_dir = os.path.join(self.plugin_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = "preview" if dry_run else "fix"
        path = os.path.join(log_dir, f"report_{prefix}_{stamp}.csv")
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "Excel 行",
                        "图层",
                        "动作",
                        "目标字段",
                        "→字段",
                        "匹配字段",
                        "匹配值",
                        "边线 ID",
                        "说明",
                        "状态",
                    ]
                )
                for a in actions:
                    writer.writerow(
                        [
                            getattr(a, "excel_row", ""),
                            a.layer or "LANE",
                            a.action,
                            a.target_field,
                            a.target_field_to,
                            a.match_field,
                            a.match_value,
                            ";".join(a.mark_ids),
                            a.note or "",
                            "[预览] OK" if dry_run else "OK",
                        ]
                    )
                writer.writerow([])
                for ln, s in stats.items():
                    writer.writerow([f"[{ln}]", json.dumps(s, ensure_ascii=False)])
            self._log(f"改动报告已写入: {path}", show_bar=False)
        except Exception as exc:
            self._log(f"写报告失败: {exc}", level="WARN", show_bar=False)