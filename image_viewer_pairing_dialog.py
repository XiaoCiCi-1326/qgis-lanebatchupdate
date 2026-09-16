# -*- coding: utf-8 -*-
"""惯导图层 - 照片目录配对管理对话框

一张表，每个图层对应一个图片目录和一个图片名字段。
支持添加/删除/上下移行、保存到 QSettings。
"""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsProject, QgsVectorLayer


# 自动检测时使用的图片名字段候选
IMG_FIELD_CANDIDATES = ("IMG", "Image_Name", "PHOTO", "IMAGE", "图片名", "文件名")
# 自动推断图片目录时的候选名
DIR_CANDIDATES = ("front", "images", "image", "photo", "photos", "img")


class _LayerCell(QComboBox):
    """图层选择单元格"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(False)
        self._populate()

    def _populate(self):
        current_id = self.currentData()
        self.blockSignals(True)
        self.clear()
        self.addItem("-- 请选择图层 --", "")
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                self.addItem(layer.name(), layer.id())
        self.blockSignals(False)
        if current_id:
            idx = self.findData(current_id)
            if idx >= 0:
                self.setCurrentIndex(idx)

    def refresh(self):
        self._populate()


class _FieldCell(QComboBox):
    """图片名字段单元格 - 由所在行的图层驱动"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)

    def update_for_layer(self, layer_id, preferred=None):
        current_text = preferred or self.currentText()
        self.blockSignals(True)
        self.clear()
        if not layer_id:
            self.blockSignals(False)
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        if not isinstance(layer, QgsVectorLayer):
            self.blockSignals(False)
            return
        field_names = [f.name() for f in layer.fields()]
        # 候选字段优先
        for cand in IMG_FIELD_CANDIDATES:
            if cand in field_names:
                self.insertItem(0, cand)
        # 追加其它字段
        for name in field_names:
            if self.findText(name) < 0:
                self.addItem(name)
        # 尝试恢复原值
        if current_text and self.findText(current_text) >= 0:
            self.setCurrentText(current_text)
        else:
            idx = self.findText("IMG")
            if idx >= 0:
                self.setCurrentIndex(idx)
        self.blockSignals(False)


class _DirCell(QWidget):
    """图片目录选择单元格（行内编辑）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(2)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("选择图片目录")
        self.btn = QToolButton()
        self.btn.setText("...")
        self.btn.setToolTip("浏览选择目录")
        self.btn.clicked.connect(self._browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.btn)

    def set_dir(self, d):
        self.edit.setText(d or "")

    def get_dir(self):
        return self.edit.text().strip()

    def _browse(self):
        start = self.edit.text() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "选择图片目录", start)
        if chosen:
            # 智能识别：如果用户选了 images 且其下有 front/side/back 等子目录，自动进入第一个
            final_dir = self._smart_infer_dir(chosen)
            self.edit.setText(final_dir)
    
    def _smart_infer_dir(self, chosen_dir):
        """智能识别：用户选 images 时，自动找 front 等子目录"""
        if not os.path.isdir(chosen_dir):
            return chosen_dir
        dir_name = os.path.basename(chosen_dir).lower()
        # 如果用户直接选了 front/side/back 等，直接用
        if dir_name in ("front", "side", "back", "left", "right"):
            return chosen_dir
        # 如果用户选了 images/image/photo/photos，尝试找子目录
        if dir_name in ("images", "image", "photo", "photos"):
            subdirs = []
            for name in os.listdir(chosen_dir):
                full = os.path.join(chosen_dir, name)
                if os.path.isdir(full):
                    subdirs.append((name.lower(), full))
            # 优先 front
            for priority in ("front", "side", "back", "left", "right"):
                for sname, spath in subdirs:
                    if sname == priority:
                        return spath
            # 否则返回第一个子目录
            if subdirs:
                return subdirs[0][1]
        return chosen_dir


class ImageViewerPairingDialog(QDialog):
    """图层 ↔ 图片目录配对管理

    用法：
        dlg = ImageViewerPairingDialog(iface, pairs=[], on_save=callback)
        dlg.show()
    """

    def __init__(self, iface, pairs, on_save):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.pairs = list(pairs) if pairs else []
        self.on_save = on_save
        self.setWindowTitle("图层 - 照片目录配对管理")
        self.resize(820, 360)
        self._setup_ui()
        self._populate_table()

        # 工程变化时刷新图层下拉
        self._project = QgsProject.instance()
        self._project.layersAdded.connect(self._refresh_layer_cells)
        self._project.layersRemoved.connect(self._refresh_layer_cells)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        tip = QLabel(
            "一张表，每个矢量图层对应一个图片目录和一个图片名字段（如 IMG）。\n"
            "· 选好图层后，配置文件目录、确认字段；保存后即可在地图上选要素自动查看照片。"
        )
        tip.setStyleSheet("color: #555;")
        layout.addWidget(tip)

        # 工具条
        toolbar = QHBoxLayout()
        self.btn_add = QPushButton("+ 添加行")
        self.btn_remove = QPushButton("- 删除选中行")
        self.btn_up = QPushButton("▲ 上移")
        self.btn_down = QPushButton("▼ 下移")
        self.btn_scan = QPushButton("自动扫描当前工程")
        for b in (self.btn_add, self.btn_remove, self.btn_up, self.btn_down, self.btn_scan):
            toolbar.addWidget(b)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        # 表格
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["图层", "图片目录", "图片名字段", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(2, 140)
        layout.addWidget(self.table, 1)

        self.btn_add.clicked.connect(lambda: self._append_row())
        self.btn_remove.clicked.connect(self._remove_selected_row)
        self.btn_up.clicked.connect(lambda: self._move_selected_row(-1))
        self.btn_down.clicked.connect(lambda: self._move_selected_row(1))
        self.btn_scan.clicked.connect(self._auto_scan)

        # 底部按钮
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_save = QPushButton("保存")
        self.btn_save.setDefault(True)
        self.btn_cancel = QPushButton("取消")
        self.btn_save.clicked.connect(self._on_save_clicked)
        self.btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self.btn_save)
        bottom.addWidget(self.btn_cancel)
        layout.addLayout(bottom)

    # ---------- 表格操作 ----------
    def _populate_table(self):
        """用现有 pairs 填表"""
        self.table.setRowCount(0)
        for p in self.pairs:
            self._append_row(prefilled=p)

    def _append_row(self, prefilled=None):
        """在末尾追加一行；行内 cellWidget 通过闭包记录 row"""
        row = self.table.rowCount()
        self.table.insertRow(row)

        # 0: 图层下拉
        layer_combo = _LayerCell(self.table)
        if prefilled and prefilled.get("layer_id"):
            idx = layer_combo.findData(prefilled["layer_id"])
            if idx >= 0:
                layer_combo.setCurrentIndex(idx)
        self.table.setCellWidget(row, 0, layer_combo)

        # 1: 目录
        dir_widget = _DirCell(self.table)
        if prefilled:
            dir_widget.set_dir(prefilled.get("img_dir", ""))
        self.table.setCellWidget(row, 1, dir_widget)

        # 2: 字段
        field_combo = _FieldCell(self.table)
        self.table.setCellWidget(row, 2, field_combo)

        # 图层变化时刷新字段候选
        def on_layer_changed(_idx, lc=layer_combo, fc=field_combo):
            fc.update_for_layer(lc.currentData())
        layer_combo.currentIndexChanged.connect(on_layer_changed)

        # 首次填充字段
        layer_id = layer_combo.currentData()
        if layer_id:
            preferred = prefilled.get("img_field") if prefilled else None
            field_combo.update_for_layer(layer_id, preferred=preferred)

        # 3: 删除按钮（用 lambda 捕获当前 row）
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(lambda _=False, r=row: self._delete_row(r))
        self.table.setCellWidget(row, 3, del_btn)

    def _delete_row(self, row):
        if 0 <= row < self.table.rowCount():
            self.table.removeRow(row)
            # 删除后，下方所有行的删除按钮需要重新指向正确 row
            # 由于闭包已捕获旧 row，按钮在按下时 row 已变化会指向错行
            # 解决：遍历所有行，重新绑定删除按钮 row
            self._rebind_delete_buttons()

    def _rebind_delete_buttons(self):
        for r in range(self.table.rowCount()):
            btn = self.table.cellWidget(r, 3)
            if btn is not None:
                try:
                    btn.clicked.disconnect()
                except (TypeError, RuntimeError):
                    pass
                btn.clicked.connect(lambda _=False, r=r: self._delete_row(r))

    def _remove_selected_row(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一行。")
            return
        self._delete_row(row)

    def _move_selected_row(self, delta):
        row = self.table.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= self.table.rowCount():
            return
        # 把两行的 data 交换
        data_a = self._read_row(row)
        data_b = self._read_row(new_row)
        self._delete_row(max(row, new_row))
        self._delete_row(min(row, new_row))
        # 先插入 new_row（较小）再插入 row
        first = min(row, new_row)
        second = max(row, new_row)
        # 让 second 位置放 data_a（原 row 的），first 放 data_b
        if new_row > row:
            # 上移 -> new_row 是 row-1, delta=-1
            # 期望：原 row 行的内容上移到 new_row
            data_first = data_b   # new_row 位置放 data_b（原 row 下方）
            data_second = data_a  # row 位置放 data_a（原 row）
        else:
            # 下移 -> new_row 是 row+1
            data_first = data_a   # new_row(上方) 放 data_a
            data_second = data_b  # row(下方) 放 data_b
        self.table.insertRow(first)
        self._append_row(prefilled=data_first)
        # _append_row 是末尾追加，把它移到 first 位置
        last = self.table.rowCount() - 1
        self._swap_to_position(last, first)
        self.table.insertRow(second if second < first else second)
        # 计算第二个插入位置（行数已变）
        second_pos = second if second > first else second + 1
        last = self.table.rowCount() - 1
        self._swap_to_position(last, second_pos)
        self._rebind_delete_buttons()
        self.table.selectRow(second_pos if new_row > row else first)

    def _swap_to_position(self, src_row, dst_row):
        """把 src_row 的所有 cell 内容移动到 dst_row，并删除 src_row"""
        if src_row == dst_row:
            return
        # 先取出 src 的所有 widget 和 item
        widgets = []
        items = []
        for col in range(self.table.columnCount()):
            w = self.table.cellWidget(src_row, col)
            it = self.table.takeItem(src_row, col)
            widgets.append(w)
            items.append(it)
        # 暂时释放 dst 的内容（先删除 dst 行再插入新空行）
        # 简化做法：把 dst 的内容移动到 src，然后 dst 重新填充
        dst_widgets = []
        dst_items = []
        for col in range(self.table.columnCount()):
            dw = self.table.cellWidget(dst_row, col)
            di = self.table.takeItem(dst_row, col)
            dst_widgets.append(dw)
            dst_items.append(di)
        # 把 src 的内容写到 dst
        for col in range(self.table.columnCount()):
            w = widgets[col]
            it = items[col]
            if w is not None:
                w.setParent(self.table)
            self.table.setCellWidget(dst_row, col, w)
            if it is not None:
                self.table.setItem(dst_row, col, it)
        # 把 dst 的内容放回 src（这样 src 行依然存在，只是内容被替换）
        for col in range(self.table.columnCount()):
            w = dst_widgets[col]
            it = dst_items[col]
            if w is not None:
                w.setParent(self.table)
            self.table.setCellWidget(src_row, col, w)
            if it is not None:
                self.table.setItem(src_row, col, it)

    def _read_row(self, row):
        layer_combo = self.table.cellWidget(row, 0)
        dir_widget = self.table.cellWidget(row, 1)
        field_combo = self.table.cellWidget(row, 2)
        return {
            "layer_id": layer_combo.currentData() if layer_combo else "",
            "img_dir": dir_widget.get_dir() if dir_widget else "",
            "img_field": field_combo.currentText().strip() if field_combo else "",
        }

    def _refresh_layer_cells(self, *_args):
        for r in range(self.table.rowCount()):
            cell = self.table.cellWidget(r, 0)
            if isinstance(cell, _LayerCell):
                cell.refresh()

    def _auto_scan(self):
        """扫描当前工程中含候选图片名字段的图层，按推断的图片目录自动添加"""
        existing_ids = set()
        for r in range(self.table.rowCount()):
            layer_combo = self.table.cellWidget(r, 0)
            if layer_combo:
                lid = layer_combo.currentData()
                if lid:
                    existing_ids.add(lid)
        added = 0
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue
            if layer.id() in existing_ids:
                continue
            fields = [f.name().upper() for f in layer.fields()]
            img_field = None
            for cand in IMG_FIELD_CANDIDATES:
                if cand.upper() in fields:
                    img_field = cand
                    break
            if not img_field:
                continue
            inferred_dir = self._infer_dir(layer)
            if not inferred_dir or not os.path.isdir(inferred_dir):
                continue
            self._append_row(prefilled={
                "layer_id": layer.id(),
                "img_dir": inferred_dir,
                "img_field": img_field,
            })
            added += 1
        if added:
            QMessageBox.information(self, "扫描完成", f"自动添加了 {added} 行配对。\n请确认后保存。")
        else:
            QMessageBox.information(self, "扫描完成", "没有新的可自动添加配对的图层。")

    @staticmethod
    def _infer_dir(layer):
        """从图层源路径推断图片目录"""
        src = layer.source() or ""
        if "|" in src:
            src = src.split("|", 1)[0]
        shp_dir = os.path.dirname(src)
        for name in DIR_CANDIDATES:
            test = os.path.join(shp_dir, name)
            if os.path.isdir(test):
                return test
        parent = os.path.dirname(shp_dir)
        for name in DIR_CANDIDATES:
            test = os.path.join(parent, name)
            if os.path.isdir(test):
                return test
        return None

    def _on_save_clicked(self):
        rows = []
        for r in range(self.table.rowCount()):
            data = self._read_row(r)
            if not data["layer_id"]:
                continue
            if not data["img_dir"]:
                QMessageBox.warning(self, "校验失败", f"第 {r + 1} 行未填写图片目录。")
                return
            if not os.path.isdir(data["img_dir"]):
                QMessageBox.warning(self, "校验失败", f"第 {r + 1} 行的图片目录不存在：\n{data['img_dir']}")
                return
            if not data["img_field"]:
                QMessageBox.warning(self, "校验失败", f"第 {r + 1} 行未选择图片名字段。")
                return
            layer = QgsProject.instance().mapLayer(data["layer_id"])
            if not isinstance(layer, QgsVectorLayer):
                QMessageBox.warning(self, "校验失败", f"第 {r + 1} 行的图层已不存在（可能被移除）。")
                return
            field_names = [f.name() for f in layer.fields()]
            if data["img_field"] not in field_names:
                QMessageBox.warning(
                    self, "校验失败",
                    f"第 {r + 1} 行：图层 {layer.name()} 中没有字段 {data['img_field']}",
                )
                return
            rows.append(data)
        try:
            if callable(self.on_save):
                self.on_save(rows)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", "保存配对时出错：%s" % exc)
            return
        self.accept()

    def refresh_from_project(self):
        """重新刷新所有图层下拉（工程变化后调用）"""
        self._refresh_layer_cells()

    def closeEvent(self, event):
        try:
            self._project.layersAdded.disconnect(self._refresh_layer_cells)
            self._project.layersRemoved.disconnect(self._refresh_layer_cells)
        except (TypeError, RuntimeError):
            pass
        super().closeEvent(event)
