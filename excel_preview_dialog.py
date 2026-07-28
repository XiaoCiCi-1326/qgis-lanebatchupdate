# -*- coding: utf-8 -*-
"""Excel 边线改错的预览对话框：列出全部解析动作，多选 + 一键执行。

设计：
- 顶部：仅预览勾选框 + 过滤框 + 全选/全不选/反选三个按钮
- 中部：QTableWidget，每行一个 LaneFixAction（行号 / 图层 / 动作 / 字段 / 目标 / 备注）
- 底部：执行 / 关闭
"""
from __future__ import annotations

from typing import Callable, List, Optional

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QBrush, QColor, QColor
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .lane_fix_excel import LaneFixAction, sort_fix_actions

# 列定义
COL_CHECK = 0
COL_ROW = 1
COL_LAYER = 2
COL_ACTION = 3
COL_FIELD = 4
COL_TARGET = 5
COL_NOTE = 6
COL_STATUS = 7
COL_SOURCE = 8  # 隐藏列，存 source_text 给状态/报告用

ACTION_LABELS = {
    "add": "添加",
    "remove": "删除",
    "swap": "交换",
    "move": "侧位",
    "set": "设置",
    "skip": "跳过",
    "fill_from_lrvs": "五级补全",
}

ACTION_COLORS = {
    "add": QColor("#1e7d34"),
    "remove": QColor("#a83232"),
    "swap": QColor("#a06800"),
    "move": QColor("#5a3a8c"),
    "fill_from_lrvs": QColor("#1e5a8a"),
    "skip": QColor("#666666"),
}


class ExcelPreviewDialog(QDialog):
    """Excel 边线改错预览对话框（多选 + 一键修复）。"""

    def __init__(
        self,
        parent,
        actions: List[LaneFixAction],
        excel_path: str,
        on_apply: Optional[Callable[[List[LaneFixAction], bool], dict]] = None,
    ):
        """
        :param actions: 解析后的动作列表（已 sort_fix_actions）
        :param excel_path: 当前 Excel 文件路径（仅用于显示）
        :param on_apply: 点击「执行」时回调，签名 (selected_actions, dry_run) -> 统计 dict
                        返回 None 表示取消。返回 stats 显示在状态栏。
        """
        super().__init__(parent)
        self.setWindowTitle("Excel 边线改错预览")
        self.resize(1100, 600)

        self._on_apply = on_apply
        self._actions: List[LaneFixAction] = list(actions)
        self._status_map: dict[int, str] = {}

        # ---------- 顶部工具栏 ----------
        top = QHBoxLayout()

        top.addWidget(QLabel("过滤："))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("按字段名 / ROAD_ID / 行号 过滤，留空显示全部")
        self.filter_edit.setMaximumWidth(360)
        self.filter_edit.textChanged.connect(self._apply_filter)
        top.addWidget(self.filter_edit)

        top.addStretch(1)

        self.btn_all = QPushButton("全选")
        self.btn_none = QPushButton("全不选")
        self.btn_invert = QPushButton("反选")
        self.btn_fixable = QPushButton("只选可修复")
        self.btn_all.clicked.connect(lambda: self._set_check_state(lambda i: True))
        self.btn_none.clicked.connect(lambda: self._set_check_state(lambda i: False))
        self.btn_invert.clicked.connect(self._invert_check)
        self.btn_fixable.clicked.connect(self._select_fixable)
        for b in (self.btn_all, self.btn_none, self.btn_invert, self.btn_fixable):
            top.addWidget(b)

        # ---------- 中部表格 ----------
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["✓", "Excel 行", "图层", "动作", "字段", "目标", "说明", "执行状态", "源"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_ROW, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_LAYER, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_ACTION, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_FIELD, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_TARGET, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_NOTE, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeToContents)
        self.table.setColumnHidden(COL_SOURCE, True)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)  # 支持 Shift / Ctrl 多选框选
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemChanged.connect(self._on_item_changed)

        # ---------- 底部按钮 ----------
        bottom = QHBoxLayout()
        self.status_label = QLabel(f"待执行：{len(self._actions)} 条（已勾选 0 条）")
        bottom.addWidget(self.status_label)
        bottom.addStretch(1)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        self.btn_apply = QPushButton("一键修复（仅勾选项）")
        self.btn_apply.clicked.connect(self._on_apply_clicked)
        self.btn_apply.setDefault(True)
        bottom.addWidget(self.btn_close)
        bottom.addWidget(self.btn_apply)

        # ---------- 整体布局 ----------
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table)
        layout.addLayout(bottom)

        self._populate_table()

    # ---------- 表格填充 ----------

    def _populate_table(self):
        """把 actions 灌进表格。Excel 行号：source_text 里没原始行号，
        我们退而求其次：source_text 行号 = 第几次 parse_error_texts 返回的第几条动作。
        为了保留行号信息，controller 在传入前会 setattr(action, 'excel_row', row)。"""
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            for idx, action in enumerate(self._actions):
                row_no = getattr(action, "excel_row", idx + 1)
                self._append_row(idx, action, row_no)
            self._refresh_status_label()
        finally:
            self.table.blockSignals(False)

    def _append_row(self, idx: int, action: LaneFixAction, row_no: int):
        r = self.table.rowCount()
        self.table.insertRow(r)

        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
        chk.setCheckState(Qt.Checked)  # 默认全选
        chk.setData(Qt.UserRole, idx)
        self.table.setItem(r, COL_CHECK, chk)

        self.table.setItem(r, COL_ROW, QTableWidgetItem(str(row_no)))

        layer_item = QTableWidgetItem(action.layer or "LANE")
        self.table.setItem(r, COL_LAYER, layer_item)

        action_label = ACTION_LABELS.get(action.action, action.action)
        action_item = QTableWidgetItem(action_label)
        if action.action in ACTION_COLORS:
            action_item.setForeground(QBrush(ACTION_COLORS[action.action]))
        self.table.setItem(r, COL_ACTION, action_item)

        field_text = action.target_field
        if action.target_field_to:
            field_text = f"{action.target_field} → {action.target_field_to}"
        self.table.setItem(r, COL_FIELD, QTableWidgetItem(field_text))

        target_parts = []
        if action.match_value:
            target_parts.append(f"{action.match_field}={action.match_value}")
        if action.mark_ids:
            target_parts.append("边线=" + ",".join(action.mark_ids))
        self.table.setItem(r, COL_TARGET, QTableWidgetItem("  ".join(target_parts)))

        self.table.setItem(r, COL_NOTE, QTableWidgetItem(action.note or ""))

        status_item = QTableWidgetItem("")
        self.table.setItem(r, COL_STATUS, status_item)

        self.table.setItem(r, COL_SOURCE, QTableWidgetItem(action.source_text or ""))

    # ---------- 过滤 / 状态 ----------

    def _apply_filter(self, _text: str = ""):
        text = self.filter_edit.text().strip().lower()
        for r in range(self.table.rowCount()):
            if not text:
                self.table.setRowHidden(r, False)
                continue
            row_text = self.table.item(r, COL_FIELD).text().lower()
            row_text += "|" + self.table.item(r, COL_TARGET).text().lower()
            row_text += "|" + self.table.item(r, COL_ROW).text().lower()
            row_text += "|" + self.table.item(r, COL_LAYER).text().lower()
            row_text += "|" + self.table.item(r, COL_NOTE).text().lower()
            self.table.setRowHidden(r, text not in row_text)

    def _on_item_changed(self, item):
        if item.column() == COL_CHECK:
            self._refresh_status_label()

    def _on_selection_changed(self):
        """框选行（Shift / Ctrl / 普通多选）→ 同步勾选列状态。
        选中行 → 勾选对应行的 ✓；取消选中 → 取消勾选。
        """
        self.table.blockSignals(True)
        try:
            for r in range(self.table.rowCount()):
                chk_item = self.table.item(r, COL_CHECK)
                if chk_item is None:
                    continue
                want = chk_item.isSelected()  # 整行选中时该 cell 也被选中
                cur = chk_item.checkState() == Qt.Checked
                if want != cur:
                    chk_item.setCheckState(Qt.Checked if want else Qt.Unchecked)
        finally:
            self.table.blockSignals(False)
        self._refresh_status_label()

    def _refresh_status_label(self):
        total = self.table.rowCount()
        selected = self._selected_indices()
        self.status_label.setText(f"待执行：{total} 条（已勾选 {len(selected)} 条）")

    def _selected_indices(self) -> List[int]:
        result = []
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
                continue
            chk = self.table.item(r, COL_CHECK)
            if chk and chk.checkState() == Qt.Checked:
                result.append(self.table.item(r, COL_CHECK).data(Qt.UserRole))
        return result

    def _set_check_state(self, predicate):
        self.table.blockSignals(True)
        try:
            for r in range(self.table.rowCount()):
                if self.table.isRowHidden(r):
                    continue
                idx = self.table.item(r, COL_CHECK).data(Qt.UserRole)
                chk = self.table.item(r, COL_CHECK)
                chk.setCheckState(Qt.Checked if predicate(idx) else Qt.Unchecked)
        finally:
            self.table.blockSignals(False)
        self._refresh_status_label()

    def _invert_check(self):
        self.table.blockSignals(True)
        try:
            for r in range(self.table.rowCount()):
                if self.table.isRowHidden(r):
                    continue
                chk = self.table.item(r, COL_CHECK)
                chk.setCheckState(
                    Qt.Unchecked if chk.checkState() == Qt.Checked else Qt.Checked
                )
        finally:
            self.table.blockSignals(False)
        self._refresh_status_label()

    def _select_fixable(self):
        """一键勾选所有可修复项（action != skip），其余取消。"""
        self.table.blockSignals(True)
        try:
            for r in range(self.table.rowCount()):
                if self.table.isRowHidden(r):
                    continue
                idx = self.table.item(r, COL_CHECK).data(Qt.UserRole)
                action = self._actions[idx]
                check = action.action != "skip"
                self.table.item(r, COL_CHECK).setCheckState(
                    Qt.Checked if check else Qt.Unchecked
                )
        finally:
            self.table.blockSignals(False)
        self._refresh_status_label()

    # ---------- 应用 ----------

    def _on_apply_clicked(self):
        selected_indices = self._selected_indices()
        if not selected_indices:
            QMessageBox.warning(self, "未勾选", "请至少勾选一条要修复的错误。")
            return
        selected_actions = [self._actions[i] for i in selected_indices]
        if not self._on_apply:
            QMessageBox.warning(self, "未实现", "未注入 on_apply 回调。")
            return
        result = self._on_apply(selected_actions, False)
        if result is None:
            return
        # 用 result 写回每行状态
        self._apply_status(selected_actions, result, False)
        # 真实执行完成后清空勾选（防止误点第二次）
        self._set_check_state(lambda i: False)
        self._refresh_status_label()

    def _apply_status(self, actions: List[LaneFixAction], result: dict, dry_run: bool):
        """根据 controller 返回的统计填回每行状态列。
        result.per_action_status: {action_excel_row: 'OK/SKIP/...'}"""
        per = result.get("per_action_status", {})
        prefix = "[预览] " if dry_run else ""
        for r in range(self.table.rowCount()):
            row_idx = self.table.item(r, COL_CHECK).data(Qt.UserRole)
            action = self._actions[row_idx]
            row_no = getattr(action, "excel_row", None)
            if row_no is None:
                continue
            status = per.get(row_no, "")
            self.table.item(r, COL_STATUS).setText(prefix + status)

    # ---------- 公共 API ----------

    def set_action_status(self, idx: int, status: str):
        """controller 在执行过程中更新单行状态。"""
        for r in range(self.table.rowCount()):
            if self.table.item(r, COL_CHECK).data(Qt.UserRole) == idx:
                self.table.item(r, COL_STATUS).setText(status)
                break

    def get_selected_actions(self) -> List[LaneFixAction]:
        return [self._actions[i] for i in self._selected_indices()]