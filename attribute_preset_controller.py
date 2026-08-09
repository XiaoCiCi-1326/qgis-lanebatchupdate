# -*- coding: utf-8 -*-
"""按图层保存并应用属性预设。"""
import json

from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsVectorLayer, NULL


class AttributePresetDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent or controller.iface.mainWindow())
        self.iface = controller.iface
        self.controller = controller
        self.fields = {}
        self.setWindowTitle("属性预设")
        self.setMinimumWidth(560)
        self._horizontal_size_restored = False
        self._build_ui()
        self._reload_layers()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layer_row = QHBoxLayout()
        layer_row.addWidget(QLabel("图层"))
        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self._layer_changed)
        layer_row.addWidget(self.layer_combo, 1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._reload_layers)
        layer_row.addWidget(refresh)
        layout.addLayout(layer_row)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("预设"))
        self.preset_combo = QComboBox()
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        preset_row.addWidget(self.preset_combo, 1)
        new_button = QPushButton("新建")
        new_button.clicked.connect(self._new_preset)
        self.delete_button = QPushButton("删除")
        self.delete_button.clicked.connect(self._delete_preset)
        preset_row.addWidget(new_button)
        preset_row.addWidget(self.delete_button)
        layout.addLayout(preset_row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("名称"))
        self.name_edit = QLineEdit()
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(self.form)

        self.attribute_table = QTableWidget()
        self.attribute_table.setAlternatingRowColors(True)
        self.attribute_table.setMinimumHeight(360)
        self.attribute_table.itemChanged.connect(self._table_item_changed)
        self.attribute_table.hide()
        layout.addWidget(self.attribute_table)

        self.table_filter_bar = QWidget()
        filter_row = QHBoxLayout(self.table_filter_bar)
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.addWidget(QLabel("显示要素"))
        self.table_feature_scope = QComboBox()
        self.table_feature_scope.addItem("选中要素", "selected")
        self.table_feature_scope.addItem("所有要素", "all")
        self.table_feature_scope.currentIndexChanged.connect(self._table_scope_changed)
        filter_row.addWidget(self.table_feature_scope)
        filter_row.addWidget(QLabel("字段"))
        self.table_field_filter = QComboBox()
        self.table_field_filter.currentIndexChanged.connect(self._table_filter_changed)
        filter_row.addWidget(self.table_field_filter)
        self.table_filter_text = QLineEdit()
        self.table_filter_text.setPlaceholderText("输入筛选内容")
        self.table_filter_text.textChanged.connect(self._table_filter_changed)
        filter_row.addWidget(self.table_filter_text)
        filter_row.addStretch(1)
        self.table_filter_bar.hide()
        layout.addWidget(self.table_filter_bar)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("应用范围"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("选中要素", "selected")
        self.scope_combo.addItem("所有要素", "all")
        scope_row.addWidget(self.scope_combo, 1)
        layout.addLayout(scope_row)
        layout.addWidget(QLabel("空白字段不会写入；修改保留在编辑状态，可用 Ctrl+Z 撤回。"))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.save_button = buttons.addButton("保存预设", QDialogButtonBox.ActionRole)
        self.apply_button = buttons.addButton("应用属性", QDialogButtonBox.AcceptRole)
        self.save_button.clicked.connect(self._save_preset)
        self.apply_button.clicked.connect(self._apply_preset)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _reload_layers(self, prefer_active=True):
        active_layer = self.iface.activeLayer()
        active_id = active_layer.id() if isinstance(active_layer, QgsVectorLayer) else None
        current = self.layer_combo.currentData()
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        self.layer_combo.addItem("所有图层（共同字段）", self.controller.ALL_LAYERS_ID)
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                self.layer_combo.addItem(layer.name(), layer.id())
        self.layer_combo.blockSignals(False)
        index = self.layer_combo.findData(active_id) if prefer_active else -1
        if index < 0:
            index = self.layer_combo.findData(current)
        self.layer_combo.setCurrentIndex(index if index >= 0 else 0)
        self._layer_changed()

    def _is_all_layers(self):
        return self.layer_combo.currentData() == self.controller.ALL_LAYERS_ID

    def _current_layer(self):
        layer_id = self.layer_combo.currentData()
        return QgsProject.instance().mapLayer(layer_id) if layer_id else None

    def _target_layers(self):
        if self._is_all_layers():
            return self.controller.vector_layers()
        layer = self._current_layer()
        return [layer] if layer else []

    def _preset_key(self):
        return self.controller.ALL_LAYERS_ID if self._is_all_layers() else self._current_layer()

    def _layer_changed(self):
        self._clear_fields()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        preset_key = self._preset_key()
        if preset_key:
            self.controller.ensure_empty_presets()
            for name in self.controller.preset_names(preset_key):
                self.preset_combo.addItem(name)
        self.preset_combo.blockSignals(False)
        self.delete_button.setEnabled(False)
        # 默认不选预设，使表单可直接读取、编辑当前选中的一条要素。
        self.preset_combo.setCurrentIndex(-1)
        self._new_preset()

    def _clear_fields(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = {}
        self.name_edit.clear()

    def _show_table(self, layer, preserve_scope=False):
        self._clear_fields()
        if not preserve_scope:
            has_selection = layer.selectedFeatureCount() > 0
            self.table_feature_scope.blockSignals(True)
            self.table_feature_scope.setCurrentIndex(0 if has_selection else 1)
            self.table_feature_scope.blockSignals(False)
        self.attribute_table.show()
        self.table_filter_bar.show()
        if not self._horizontal_size_restored:
            saved_size = QSettings().value("LaneBatchUpdate/attribute_table_size")
            if saved_size:
                self.resize(saved_size)
            else:
                self.resize(1200, 720)
            self._horizontal_size_restored = True
        self.attribute_table.blockSignals(True)
        self.attribute_table.clear()
        features = (
            list(layer.selectedFeatures())
            if self.table_feature_scope.currentData() == "selected"
            else list(layer.getFeatures())
        )
        fields = list(layer.fields())
        self.table_field_filter.blockSignals(True)
        current_field = self.table_field_filter.currentData()
        self.table_field_filter.clear()
        self.table_field_filter.addItem("所有字段", "")
        for field in fields:
            self.table_field_filter.addItem(
                self.controller.field_label(layer, field), field.name()
            )
        field_index = self.table_field_filter.findData(current_field)
        self.table_field_filter.setCurrentIndex(field_index if field_index >= 0 else 0)
        self.table_field_filter.blockSignals(False)
        filter_field = self.table_field_filter.currentData()
        filter_text = self.table_filter_text.text().strip().casefold()
        if filter_text:
            features = [
                feature for feature in features
                if self._feature_matches_filter(feature, fields, filter_field, filter_text)
            ]
        self.attribute_table.setRowCount(len(features))
        self.attribute_table.setColumnCount(len(fields))
        self.attribute_table.setHorizontalHeaderLabels(
            [self.controller.field_label(layer, field) for field in fields]
        )
        self.attribute_table.setVerticalHeaderLabels([str(feature.id()) for feature in features])
        for row, feature in enumerate(features):
            for column, field in enumerate(fields):
                value = feature[field.name()]
                item = QTableWidgetItem("" if value is NULL or value is None else str(value))
                item.setData(Qt.UserRole, feature.id())
                item.setData(Qt.UserRole + 1, field.name())
                self.attribute_table.setItem(row, column, item)
        self.attribute_table.resizeColumnsToContents()
        self.attribute_table.blockSignals(False)

    @staticmethod
    def _feature_matches_filter(feature, fields, field_name, filter_text):
        candidate_fields = [
            field for field in fields
            if not field_name or field.name() == field_name
        ]
        for field in candidate_fields:
            value = feature[field.name()]
            if value is not NULL and value is not None and filter_text in str(value).casefold():
                return True
        return False

    def _table_scope_changed(self):
        layer = self._current_layer()
        if layer and not self._is_all_layers() and self.attribute_table.isVisible():
            self._show_table(layer, preserve_scope=True)

    def _table_filter_changed(self):
        layer = self._current_layer()
        if layer and not self._is_all_layers() and self.attribute_table.isVisible():
            self._show_table(layer, preserve_scope=True)

    def closeEvent(self, event):
        if self.attribute_table.isVisible():
            QSettings().setValue("LaneBatchUpdate/attribute_table_size", self.size())
        super().closeEvent(event)

    def _table_item_changed(self, item):
        layer = self._current_layer()
        if not layer or self._is_all_layers():
            return
        feature_id = item.data(Qt.UserRole)
        field_name = item.data(Qt.UserRole + 1)
        field_index = layer.fields().indexFromName(field_name)
        if field_index < 0:
            return
        command_started = False
        try:
            value = self.controller._convert(layer.fields().at(field_index), item.text())
            if not layer.isEditable() and not layer.startEditing():
                raise RuntimeError(f"无法开启图层编辑：{layer.name()}")
            layer.beginEditCommand("修改属性")
            command_started = True
            if not layer.changeAttributeValue(feature_id, field_index, value):
                raise RuntimeError(f"更新要素失败：{feature_id}，字段：{field_name}")
            layer.endEditCommand()
            layer.triggerRepaint()
        except (RuntimeError, ValueError) as exc:
            if command_started:
                layer.destroyEditCommand()
            QMessageBox.critical(self, "修改失败", str(exc))
            self._show_table(layer)

    def _populate_fields(self, values=None):
        self.attribute_table.hide()
        self.table_filter_bar.hide()
        self._clear_fields()
        layers = self._target_layers()
        if not layers:
            return
        values = values or {}
        field_names = self.controller.available_field_names(layers, self._is_all_layers())
        for name in field_names:
            edit = QLineEdit()
            edit.setPlaceholderText("不修改此字段")
            if name in values and values[name] is not None:
                edit.setText(str(values[name]))
            self.form.addRow(self.controller.field_label(layers[0], name), edit)
            self.fields[name] = edit

    def _preset_changed(self):
        preset_key = self._preset_key()
        name = self.preset_combo.currentText()
        self.delete_button.setEnabled(
            bool(preset_key and name and name != self.controller.EMPTY_PRESET_NAME)
        )
        if not preset_key or not name:
            return
        values = self.controller.get_preset(preset_key, name)
        self.name_edit.setText(name)
        self._populate_fields(values)

    def _new_preset(self):
        self.preset_combo.setCurrentIndex(-1)
        self.name_edit.clear()
        layer = self._current_layer()
        if not self._is_all_layers() and layer and layer.selectedFeatureCount() != 1:
            self._show_table(layer)
            return
        values = self._single_selected_feature_values()
        self._populate_fields(values)

    def _single_selected_feature_values(self):
        if self._is_all_layers():
            return {}
        layer = self._current_layer()
        if not layer or layer.selectedFeatureCount() != 1:
            return {}
        feature = next(layer.getSelectedFeatures(), None)
        if feature is None:
            return {}
        return {
            field.name(): feature[field.name()]
            for field in layer.fields()
            if feature[field.name()] is not None and feature[field.name()] is not NULL
        }

    def _values(self):
        return {name: edit.text() for name, edit in self.fields.items() if edit.text() != ""}

    def _save_preset(self):
        preset_key = self._preset_key()
        name = self.name_edit.text().strip()
        if not preset_key:
            QMessageBox.warning(self, "无法保存", "当前工程没有可用的矢量图层。")
            return
        if not name:
            QMessageBox.warning(self, "无法保存", "请输入预设名称。")
            return
        if name == self.controller.EMPTY_PRESET_NAME:
            QMessageBox.warning(self, "无法保存", "“空预设”为系统默认预设，不能修改。")
            return
        self.controller.save_preset(preset_key, name, self._values())
        self._layer_changed()
        self.preset_combo.setCurrentText(name)
        QMessageBox.information(self, "保存成功", f"已保存预设：{name}")

    def _delete_preset(self):
        preset_key = self._preset_key()
        name = self.preset_combo.currentText()
        if not preset_key or not name:
            return
        if name == self.controller.EMPTY_PRESET_NAME:
            QMessageBox.information(self, "无法删除", "“空预设”为系统默认预设，不能删除。")
            return
        answer = QMessageBox.question(self, "确认删除", f"删除预设“{name}”？")
        if answer == QMessageBox.Yes:
            self.controller.delete_preset(preset_key, name)
            self._layer_changed()

    def _apply_preset(self):
        layers = self._target_layers()
        if not layers:
            QMessageBox.warning(self, "无法应用", "请选择图层。")
            return
        values = self._values()
        if not values:
            QMessageBox.warning(self, "无法应用", "请先填写至少一个要修改的字段。")
            return
        name = self.preset_combo.currentText().strip() or "直接修改"
        try:
            count = self.controller.apply(layers, values, self.scope_combo.currentData())
        except (RuntimeError, ValueError) as exc:
            QMessageBox.critical(self, "应用失败", str(exc))
            return
        self.controller.log_application(layers, name, count)
        for layer in layers:
            layer.triggerRepaint()


class AttributePresetController:
    SETTINGS_KEY = "LaneBatchUpdate/attribute_presets"
    ALL_LAYERS_ID = "__ALL_LAYERS__"
    EMPTY_PRESET_NAME = "空预设"
    LOG_TAG = "车道处理工具"

    def __init__(self, iface, plugin_dir):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.dialog = None

    def initGui(self, actions):
        icon_path = f"{self.plugin_dir}/icon_attribute_preset.svg"
        action = QAction(QIcon(icon_path), "属性预设", self.iface.mainWindow())
        action.setToolTip("保存和应用图层属性预设")
        action.triggered.connect(self.show)
        self.iface.addVectorToolBarIcon(action)
        self.iface.addPluginToVectorMenu("车道处理工具", action)
        actions.append(action)

    def unload(self):
        if self.dialog:
            self.dialog.close()
            self.dialog = None

    def show(self):
        if self.dialog is None:
            self.dialog = AttributePresetDialog(self)
        else:
            # 每次打开均以图层面板中当前激活的矢量图层为准。
            self.dialog._reload_layers(prefer_active=True)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    @staticmethod
    def _layer_key(layer):
        if isinstance(layer, str):
            return layer
        return layer.source().split("|", 1)[0] or layer.id()

    @staticmethod
    def vector_layers():
        return [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and layer.isValid()
        ]

    @staticmethod
    def field_label(layer, field):
        field_name = field.name() if hasattr(field, "name") else field
        field_index = layer.fields().indexFromName(field_name)
        alias = layer.attributeAlias(field_index) if field_index >= 0 else ""
        if alias:
            return f"{alias} ({field_name})"
        lane_labels = {
            "ID": "车道编号",
            "FROM_NODE": "起点节点",
            "TO_NODE": "终点节点",
            "ROAD_TYPE": "道路类型",
            "TURN_TYPE": "转向类型",
            "SPEEDLIMIT": "限速",
            "VIRTUAL": "虚拟车道类型",
            "RBDY_L": "左侧边界",
            "RBDY_R": "右侧边界",
            "BDY_LEFT": "左侧边线",
            "BDY_RIGHT": "右侧边线",
            "LEFT_RVS": "左侧关联",
            "RIGHT_RVS": "右侧关联",
        }
        label = lane_labels.get(field_name.upper())
        return f"{label} ({field_name})" if label else field_name

    @staticmethod
    def available_field_names(layers, allow_partial):
        if not layers:
            return []
        field_counts = {}
        field_order = []
        for layer in layers:
            for field in layer.fields():
                name = field.name()
                if name not in field_counts:
                    field_counts[name] = 0
                    field_order.append(name)
                field_counts[name] += 1
        minimum_count = 6 if allow_partial else 1
        return [name for name in field_order if field_counts[name] >= minimum_count]

    def _all(self):
        raw = QSettings().value(self.SETTINGS_KEY, "{}")
        try:
            return json.loads(raw or "{}")
        except (TypeError, ValueError):
            return {}

    def _write_all(self, data):
        QSettings().setValue(self.SETTINGS_KEY, json.dumps(data, ensure_ascii=False))
        QSettings().sync()

    def ensure_empty_presets(self):
        """Ensure every current vector layer has its immutable empty preset."""
        data = self._all()
        keys = [self.ALL_LAYERS_ID] + [
            self._layer_key(layer) for layer in self.vector_layers()
        ]
        changed = False
        for key in keys:
            if self.EMPTY_PRESET_NAME not in data.setdefault(key, {}):
                data[key][self.EMPTY_PRESET_NAME] = {}
                changed = True
        if changed:
            self._write_all(data)

    def preset_names(self, layer):
        self.ensure_empty_presets()
        names = self._all().get(self._layer_key(layer), {}).keys()
        return sorted(names, key=lambda name: (name != self.EMPTY_PRESET_NAME, name))

    def get_preset(self, layer, name):
        return self._all().get(self._layer_key(layer), {}).get(name, {})

    def save_preset(self, layer, name, values):
        data = self._all()
        data.setdefault(self._layer_key(layer), {})[name] = values
        self._write_all(data)

    def delete_preset(self, layer, name):
        if name == self.EMPTY_PRESET_NAME:
            return
        data = self._all()
        layer_data = data.get(self._layer_key(layer), {})
        layer_data.pop(name, None)
        if layer_data:
            data[self._layer_key(layer)] = layer_data
        else:
            data.pop(self._layer_key(layer), None)
        self._write_all(data)

    def log_application(self, layers, preset_name, count):
        layer_names = "、".join(layer.name() for layer in layers)
        QgsMessageLog.logMessage(
            f"属性预设已应用：图层={layer_names}，预设={preset_name}，要素数={count}。"
            "图层保持编辑状态，可使用 Ctrl+Z 撤回本次修改。",
            self.LOG_TAG,
            Qgis.Info,
        )

    @staticmethod
    def _convert(field, raw):
        if raw == "":
            return NULL
        field_type = field.typeName().lower()
        try:
            if field_type in ("integer", "int", "int2", "int4", "int8", "smallint", "long"):
                return int(raw)
            if field_type in ("real", "double", "float", "numeric", "decimal"):
                return float(raw)
            if field_type in ("boolean", "bool"):
                return str(raw).strip().lower() in ("1", "true", "yes", "y")
        except (TypeError, ValueError):
            raise ValueError(f"字段 {field.name()} 的值“{raw}”格式不正确")
        return raw

    def apply(self, layers, values, scope):
        if scope not in ("selected", "all"):
            raise ValueError("请选择有效的应用范围。")

        valid_layers = [
            layer for layer in layers
            if isinstance(layer, QgsVectorLayer) and layer.isValid()
        ]
        if not valid_layers:
            raise RuntimeError("当前没有可用的矢量图层。")

        total = 0
        for layer in valid_layers:
            features = (
                list(layer.selectedFeatures())
                if scope == "selected"
                else list(layer.getFeatures())
            )
            if not features:
                continue

            fields = layer.fields()
            updates = {}
            for name, raw in values.items():
                field_index = fields.indexFromName(name)
                if field_index >= 0:
                    updates[field_index] = self._convert(fields.at(field_index), raw)
            if not updates:
                continue

            if not layer.isEditable() and not layer.startEditing():
                raise RuntimeError(f"无法开启图层编辑：{layer.name()}")

            # 每个图层都保留为其撤销栈中的一条独立记录。
            layer.beginEditCommand("应用属性预设")
            try:
                for feature in features:
                    for field_index, value in updates.items():
                        if not layer.changeAttributeValue(feature.id(), field_index, value):
                            field_name = fields.at(field_index).name()
                            raise RuntimeError(
                                f"更新要素失败：{feature.id()}，字段：{field_name}"
                            )
                layer.endEditCommand()
            except Exception:
                layer.destroyEditCommand()
                raise
            total += len(features)

        if total == 0:
            if scope == "selected":
                raise RuntimeError("所选图层中没有选中要素。")
            raise RuntimeError("所选图层中没有可修改的要素。")
        return total
