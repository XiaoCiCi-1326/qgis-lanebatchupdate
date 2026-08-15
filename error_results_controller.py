# -*- coding: utf-8 -*-
"""显示检测错误记录，并支持点击记录选中相关要素。"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qgis.core import QgsProject, QgsVectorLayer


class ErrorResultsController:
    def __init__(self, iface):
        self.iface = iface
        self.dialog = None
        self.records = []

    def replace_records(self, records, record_type, title=None):
        self.records = [record for record in self.records if record.get("type") != record_type]
        self.records.extend(records)
        self.show(title or "检测错误结果")
        self.dialog.refresh(self.records)

    def add_records(self, records, title=None):
        if not records:
            return
        for record_type in {record.get("type") for record in records}:
            self.records = [record for record in self.records if record.get("type") != record_type]
        self.records.extend(records)
        self.show(title or "检测错误结果")
        self.dialog.refresh(self.records)

    def clear(self):
        self.records = []
        if self.dialog is not None:
            self.dialog.refresh(self.records)

    def show(self, title="检测错误结果"):
        if self.dialog is None:
            self.dialog = ErrorResultsDialog(self, self.iface.mainWindow())
        self.dialog.setWindowTitle(title)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def select_record(self, record):
        project = QgsProject.instance()
        layers_to_select = {}
        for layer_key, feature_ids in record.get("selections", {}).items():
            layer = project.mapLayer(layer_key)
            if layer is None:
                layers = project.mapLayersByName(layer_key)
                layer = next(
                    (candidate for candidate in layers if isinstance(candidate, QgsVectorLayer)),
                    None,
                )
            if isinstance(layer, QgsVectorLayer):
                layers_to_select[layer.id()] = (layer, [int(feature_id) for feature_id in feature_ids])
        for layer in project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                layer.removeSelection()
        for layer, feature_ids in layers_to_select.values():
            layer.selectByIds(feature_ids)
        if layers_to_select:
            first_layer = next(iter(layers_to_select.values()))[0]
            self.iface.setActiveLayer(first_layer)
        self.iface.mapCanvas().refresh()

    def unload(self):
        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None
        self.records = []


class ErrorResultsDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("检测错误结果")
        self.setMinimumSize(760, 420)
        layout = QVBoxLayout(self)
        self.summary = QLabel(self)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["检测类型", "错误记录", "涉及图层", "涉及要素"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._select_current_record)
        layout.addWidget(self.table, 1)
        button_row = QHBoxLayout()
        self.clear_button = QPushButton("清空结果", self)
        self.clear_button.clicked.connect(self._clear_results)
        close_button = QPushButton("关闭", self)
        close_button.clicked.connect(self.close)
        button_row.addWidget(self.clear_button)
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def refresh(self, records):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row, record in enumerate(records):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(record.get("type", "")))
            self.table.setItem(row, 1, QTableWidgetItem(record.get("message", "")))
            selections = record.get("selections", {})
            display_ids = record.get("display_ids", {})
            display_layers = record.get("display_layers", {})
            layers = ", ".join(
                display_layers.get(layer_key, layer_key)
                for layer_key in selections.keys()
            )
            involved = "; ".join(
                "%s: %s" % (
                    display_layers.get(layer_key, layer_key),
                    ", ".join(str(value) for value in display_ids.get(layer_key, ids)),
                )
                for layer_key, ids in selections.items()
            )
            self.table.setItem(row, 2, QTableWidgetItem(layers))
            self.table.setItem(row, 3, QTableWidgetItem(involved))
            self.table.item(row, 0).setData(Qt.UserRole, record)
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)
        self.summary.setText("共 %d 条错误记录，点击一行可选中涉及要素。" % len(records))

    def _select_current_record(self):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is not None:
            self.controller.select_record(item.data(Qt.UserRole))

    def _clear_results(self):
        self.controller.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                layer.removeSelection()
        self.controller.iface.mapCanvas().refresh()
