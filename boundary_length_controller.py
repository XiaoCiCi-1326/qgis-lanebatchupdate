# -*- coding: utf-8 -*-
"""按线几何长度筛选并高亮 BOUNDARY 要素。"""
import os

from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import (
    QAction,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import QgsProject, QgsUnitTypes, QgsVectorLayer
from qgis.gui import QgsHighlight


class BoundaryLengthController:
    """筛选当前工程中名为 BOUNDARY 的线图层并高亮匹配要素。"""

    def __init__(self, iface, plugin_dir, error_results=None):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.error_results = error_results
        self.action = None
        self.dialog = None
        self.highlights = []

    def initGui(self, actions_master, register_action=True):
        if not register_action:
            return
        icon_path = os.path.join(self.plugin_dir, "icon_boundary_length.svg")
        self.action = QAction(QIcon(icon_path), "BOUNDARY长度筛选", self.iface.mainWindow())
        self.action.setToolTip("按 BOUNDARY 线要素长度筛选并高亮")
        self.action.triggered.connect(self.show)
        # 不直接添加到工具栏，由主文件根据 toolbar_mode 控制
        # self.iface.addVectorToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu("车道处理工具", self.action)
        actions_master.append(self.action)

    def unload(self):
        self.clear_highlights()
        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None
        if self.action is not None:
            self.iface.removeVectorToolBarIcon(self.action)
            self.iface.removePluginFromVectorMenu("车道处理工具", self.action)
        self.action = None

    @staticmethod
    def _boundary_layer():
        layers = [
            layer for layer in QgsProject.instance().mapLayersByName("BOUNDARY")
            if isinstance(layer, QgsVectorLayer) and layer.isValid()
        ]
        return layers[0] if layers else None

    def show(self):
        layer = self._boundary_layer()
        if layer is None:
            QMessageBox.warning(self.iface.mainWindow(), "BOUNDARY 不可用", "当前工程中没有有效的 BOUNDARY 图层。")
            return
        if layer.geometryType() != 1:
            QMessageBox.warning(self.iface.mainWindow(), "图层类型不支持", "BOUNDARY 必须是线图层。")
            return
        if self.dialog is None:
            self.dialog = BoundaryLengthDialog(self)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def apply_filter(self, operator, threshold, color=None, highlight=False):
        layer = self._boundary_layer()
        if layer is None or layer.geometryType() != 1:
            return 0
        self.clear_highlights()
        matched = 0
        records = []
        tolerance = max(1e-9, abs(threshold) * 1e-9)
        for feature in layer.getFeatures():
            geometry = feature.geometry()
            if not geometry or geometry.isEmpty():
                continue
            length = geometry.length()
            if operator == "小于" and not length < threshold:
                continue
            if operator == "大于" and not length > threshold:
                continue
            if operator == "等于" and abs(length - threshold) > tolerance:
                continue
            if highlight:
                highlight_item = QgsHighlight(self.iface.mapCanvas(), geometry, layer)
                highlight_item.setColor(color or QColor("#e53935"))
                highlight_item.setWidth(4)
                highlight_item.show()
                self.highlights.append(highlight_item)
            boundary_id = self._feature_id(feature)
            records.append(
                {
                    "type": "BOUNDARY长度",
                    "message": "BOUNDARY ID %s 长度 %.6f，%s %.6f" % (
                        boundary_id,
                        length,
                        operator,
                        threshold,
                    ),
                    "selections": {layer.id(): [feature.id()]},
                    "display_ids": {layer.id(): [boundary_id]},
                    "display_layers": {layer.id(): layer.name()},
                }
            )
            matched += 1
        if self.error_results is not None:
            self.error_results.replace_records(records, "BOUNDARY长度")
        return matched

    @staticmethod
    def _feature_id(feature):
        field_names = {field.name().upper(): field.name() for field in feature.fields()}
        id_field = field_names.get("ID")
        if id_field:
            value = feature[id_field]
            if value not in (None, ""):
                return str(value)
        return str(feature.id())

    def clear_highlights(self):
        canvas = self.iface.mapCanvas()
        for highlight in self.highlights:
            try:
                canvas.scene().removeItem(highlight)
                highlight.hide()
                highlight.deleteLater()
            except (AttributeError, RuntimeError):
                pass
        self.highlights = []


class BoundaryLengthDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent or controller.iface.mainWindow())
        self.controller = controller
        self.color = QColor("#e53935")
        self.setWindowTitle("BOUNDARY 长度筛选")
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.operator = QComboBox(self)
        self.operator.addItems(["小于", "大于", "等于"])
        form.addRow("筛选条件", self.operator)
        self.threshold = QDoubleSpinBox(self)
        self.threshold.setRange(0, 1e12)
        self.threshold.setDecimals(6)
        self.threshold.setSingleStep(1.0)
        self.threshold.setValue(10.0)
        form.addRow("长度数值", self.threshold)
        self.unit_label = QLabel(self)
        form.addRow("图层单位", self.unit_label)
        self.color_button = QPushButton(self)
        self.color_button.clicked.connect(self.choose_color)
        form.addRow("高亮颜色", self.color_button)
        layout.addLayout(form)
        self.result_label = QLabel("尚未执行筛选。", self)
        layout.addWidget(self.result_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        self.apply_button = buttons.addButton("应用筛选", QDialogButtonBox.AcceptRole)
        self.clear_button = buttons.addButton("清除高亮", QDialogButtonBox.ResetRole)
        self.apply_button.clicked.connect(self.apply)
        self.clear_button.clicked.connect(self.clear)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self._refresh_layer_info()
        self._refresh_color_button()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_layer_info()

    def _refresh_layer_info(self):
        layer = self.controller._boundary_layer()
        if layer is None:
            self.unit_label.setText("未找到 BOUNDARY")
            return
        self.unit_label.setText(QgsUnitTypes.toString(layer.crs().mapUnits()))

    def choose_color(self):
        from qgis.PyQt.QtWidgets import QColorDialog
        color = QColorDialog.getColor(self.color, self, "选择高亮颜色")
        if color.isValid():
            self.color = color
            self._refresh_color_button()

    def _refresh_color_button(self):
        self.color_button.setText(self.color.name().upper())
        self.color_button.setStyleSheet(
            "QPushButton { background-color: %s; color: %s; font-weight: bold; }"
            % (self.color.name(), "white" if self.color.lightness() < 140 else "black")
        )

    def apply(self):
        self._refresh_layer_info()
        count = self.controller.apply_filter(
            self.operator.currentText(), self.threshold.value(), self.color, highlight=True
        )
        self.result_label.setText("已高亮 %d 个 BOUNDARY 要素。" % count)
        self.controller.iface.mapCanvas().refresh()

    def clear(self):
        self.controller.clear_highlights()
        self.result_label.setText("已清除高亮。")
        self.controller.iface.mapCanvas().refresh()

    def closeEvent(self, event):
        super().closeEvent(event)
