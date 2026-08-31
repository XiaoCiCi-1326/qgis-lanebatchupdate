# -*- coding: utf-8 -*-
"""Layer switching, visibility schemes, and side-button visibility toggling."""
import json
import os

from qgis.PyQt.QtCore import QEvent, QObject, QSettings, Qt
from qgis.PyQt.QtGui import QIcon, QKeySequence
from qgis.PyQt.QtWidgets import (
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
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
from qgis.core import Qgis, QgsLayerTreeNode, QgsProject

try:
    from qgis.PyQt.QtWidgets import QKeySequenceEdit, QShortcut
except ImportError:
    from qgis.PyQt.QtGui import QKeySequenceEdit, QShortcut

MENU_NAME = u"车道处理工具"
try:
    LEFT = int(Qt.MouseButton.LeftButton)
    RIGHT = int(Qt.MouseButton.RightButton)
    MIDDLE = int(Qt.MouseButton.MiddleButton)
    BACK = int(Qt.MouseButton.BackButton)
    FORWARD = int(Qt.MouseButton.ForwardButton)
except AttributeError:
    LEFT = int(Qt.LeftButton)
    RIGHT = int(Qt.RightButton)
    MIDDLE = int(getattr(Qt, "MiddleButton", Qt.MidButton))
    BACK = int(Qt.BackButton)
    FORWARD = int(Qt.ForwardButton)

MOUSE_BUTTONS = [
    (BACK, u"侧键后退 (X1)"),
    (FORWARD, u"侧键前进 (X2)"),
    (MIDDLE, u"鼠标中键"),
    (RIGHT, u"鼠标右键 (拦截右键菜单)"),
    (LEFT, u"鼠标左键 (打断画线!)"),
]


class _CanvasEventFilter(QObject):
    def __init__(self, callback, buttons):
        super().__init__()
        self.callback = callback
        self.buttons = set(buttons)

    def eventFilter(self, obj, event):
        if event.type() in (
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseButtonDblClick,
        ) and int(event.button()) in self.buttons:
            if event.type() == QEvent.MouseButtonPress:
                self.callback()
            return True
        return False


class LayerToolsController:
    """Integrates the three tools from combined_layertools into this plugin."""

    def __init__(self, iface, plugin_dir):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.canvas = iface.mapCanvas()
        self.actions = []
        self.switch_actions = []
        self.vis_actions = []
        self.status_switch = None
        self.status_vis = None
        self.efilter = None
        self.shortcut = None
        self.target = "group2"
        self.btn_set = {BACK}
        self.use_key = False
        self.key_seq = ""
        self.restrict = False
        self.active_layer = "BOUNDARY"

    def initGui(self, actions_master):
        entries = (
            ("图层快捷切换", "icon_layer_switch.png", self.open_switch_settings),
            ("图层显隐方案", "icon_layer_visibility.png", self.open_visibility_settings),
            ("侧键切换图层", "icon_side_button_toggle.svg", self.open_toggle_settings),
        )
        for label, icon_name, callback in entries:
            action = QAction(QIcon(os.path.join(self.plugin_dir, icon_name)), label, self.iface.mainWindow())
            action.triggered.connect(callback)
            self.iface.addPluginToVectorMenu(MENU_NAME, action)
            self.actions.append(action)
            actions_master.append(action)

        self._create_status_widgets()
        self._load_switch_shortcuts()
        self._load_visibility_shortcuts()
        self._load_toggle_settings()
        self._update_status_widgets()
        if QSettings().value("ToggleLayerSideButton/enabled", False, type=bool):
            self._start_toggle_filter()
            if self.use_key and self.key_seq:
                self._start_toggle_shortcut()

    def unload(self):
        self._clear_switch_shortcuts()
        self._clear_visibility_shortcuts()
        self._stop_toggle_filter()
        self._stop_toggle_shortcut()
        for action in self.actions:
            try:
                self.iface.removePluginMenu(MENU_NAME, action)
            except (AttributeError, RuntimeError):
                pass
        self.actions = []
        for widget in (self.status_switch, self.status_vis):
            if widget is not None:
                self.iface.mainWindow().statusBar().removeWidget(widget)
                widget.deleteLater()
        self.status_switch = None
        self.status_vis = None

    def _create_status_widgets(self):
        bar = self.iface.mainWindow().statusBar()
        self.status_switch = QLabel(bar)
        self.status_switch.setStyleSheet("QLabel { color: #1976d2; font-weight: bold; padding: 0 8px; }")
        bar.addPermanentWidget(self.status_switch)
        self.status_vis = QLabel(bar)
        self.status_vis.setStyleSheet("QLabel { color: #00838f; font-weight: bold; padding: 0 8px; }")
        bar.addPermanentWidget(self.status_vis)

    @staticmethod
    def _read_json(key):
        raw = QSettings().value(key, "")
        if not raw:
            return {}
        try:
            return json.loads(str(raw))
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _write_json(key, value):
        settings = QSettings()
        settings.setValue(key, json.dumps(value, ensure_ascii=False))
        settings.sync()

    def _layer_names(self):
        return sorted(layer.name() for layer in QgsProject.instance().mapLayers().values())

    def _create_shortcut_action(self, label, shortcut, callback, collection):
        action = QAction(label, self.iface.mainWindow())
        action.setShortcut(QKeySequence(shortcut))
        action.setShortcutContext(Qt.ApplicationShortcut)
        action.triggered.connect(callback)
        self.iface.mainWindow().addAction(action)
        collection.append(action)

    def _clear_shortcuts(self, collection):
        window = self.iface.mainWindow()
        for action in collection:
            try:
                action.setShortcut(QKeySequence())
                window.removeAction(action)
                action.deleteLater()
            except RuntimeError:
                pass
        del collection[:]

    def _load_switch_shortcuts(self):
        self._clear_switch_shortcuts()
        for layer_name, shortcut in self._read_json("LayerSwitch/bindings").items():
            if shortcut:
                self._create_shortcut_action(
                    u"切换到: " + layer_name,
                    shortcut,
                    lambda checked=False, name=layer_name: self.switch_to_layer(name),
                    self.switch_actions,
                )

    def _clear_switch_shortcuts(self):
        self._clear_shortcuts(self.switch_actions)

    def switch_to_layer(self, layer_name):
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == layer_name:
                self.iface.setActiveLayer(layer)
                if QSettings().value("LayerSwitch/autoEdit", False, type=bool):
                    try:
                        layer.startEditing()
                    except RuntimeError:
                        pass
                self._message(u"图层切换", u"已切换到: " + layer_name)
                return
        self._warning(u"图层切换", u"未找到图层: " + layer_name)

    def open_switch_settings(self):
        bindings = self._read_json("LayerSwitch/bindings")
        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle(u"图层快捷切换设置")
        dialog.resize(520, 420)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        layer_combo = QComboBox()
        layer_combo.addItems(self._layer_names())
        key_edit = QKeySequenceEdit()
        auto_edit = QCheckBox(u"切换图层时自动开启编辑模式")
        auto_edit.setChecked(QSettings().value("LayerSwitch/autoEdit", False, type=bool))
        form.addRow(u"图层", layer_combo)
        form.addRow(u"快捷键", key_edit)
        layout.addLayout(form)
        add_button = QPushButton(u"添加或更新")
        layout.addWidget(add_button)
        table = QTableWidget(0, 3, dialog)
        table.setHorizontalHeaderLabels([u"图层", u"快捷键", u"操作"])
        table.setColumnWidth(0, 220)
        table.setColumnWidth(1, 130)
        layout.addWidget(table)
        layout.addWidget(auto_edit)

        def refresh_table():
            table.setRowCount(len(bindings))
            for row, (name, shortcut) in enumerate(sorted(bindings.items())):
                table.setItem(row, 0, QTableWidgetItem(name))
                table.setItem(row, 1, QTableWidgetItem(shortcut))
                delete_button = QPushButton(u"删除")
                delete_button.clicked.connect(lambda checked=False, n=name: (bindings.pop(n, None), refresh_table()))
                table.setCellWidget(row, 2, delete_button)

        def add_binding():
            name = layer_combo.currentText()
            shortcut = key_edit.keySequence().toString()
            if not name or not shortcut:
                QMessageBox.warning(dialog, u"提示", u"请选择图层并设置快捷键。")
                return
            bindings[name] = shortcut
            key_edit.clear()
            refresh_table()

        add_button.clicked.connect(add_binding)
        refresh_table()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() == QDialog.Accepted:
            self._write_json("LayerSwitch/bindings", bindings)
            settings = QSettings()
            settings.setValue("LayerSwitch/autoEdit", auto_edit.isChecked())
            settings.sync()
            self._load_switch_shortcuts()
            self._update_status_widgets()

    def _set_layer_visible(self, layer_name, visible):
        root = QgsProject.instance().layerTreeRoot()
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == layer_name:
                node = root.findLayer(layer.id())
                if node is not None:
                    node.setItemVisibilityChecked(visible)
                return

    @staticmethod
    def _set_all_visible(visible):
        for node in QgsProject.instance().layerTreeRoot().findLayers():
            node.setItemVisibilityChecked(visible)

    def apply_visibility_scheme(self, scheme_name):
        scheme = self._read_json("LayerVis/schemes").get(scheme_name)
        if not scheme:
            self._warning(u"显隐方案", u"未找到方案: " + scheme_name)
            return
        mode = scheme.get("mode", "only")
        layers = scheme.get("layers", [])
        if mode == "only":
            self._set_all_visible(False)
            for name in layers:
                self._set_layer_visible(name, True)
        elif mode == "add":
            for name in layers:
                self._set_layer_visible(name, True)
        elif mode == "hide":
            for name in layers:
                self._set_layer_visible(name, False)
        elif mode == "all":
            self._set_all_visible(True)
        self.canvas.refresh()
        self._message(u"显隐方案", u"已切换: " + scheme_name, duration=3)

    def _load_visibility_shortcuts(self):
        self._clear_visibility_shortcuts()
        for name, scheme in self._read_json("LayerVis/schemes").items():
            shortcut = scheme.get("shortcut", "")
            if shortcut:
                self._create_shortcut_action(
                    u"显隐方案: " + name,
                    shortcut,
                    lambda checked=False, scheme_name=name: self.apply_visibility_scheme(scheme_name),
                    self.vis_actions,
                )

    def _clear_visibility_shortcuts(self):
        self._clear_shortcuts(self.vis_actions)

    def open_visibility_settings(self):
        schemes = self._read_json("LayerVis/schemes")
        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle(u"图层显隐方案设置")
        dialog.resize(600, 600)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        name_edit = QLineEdit()
        mode_combo = QComboBox()
        mode_combo.addItem(u"只显示选中图层", "only")
        mode_combo.addItem(u"追加显示选中图层", "add")
        mode_combo.addItem(u"隐藏选中图层", "hide")
        mode_combo.addItem(u"显示全部图层", "all")
        shortcut_edit = QKeySequenceEdit()
        form.addRow(u"方案名", name_edit)
        form.addRow(u"模式", mode_combo)
        form.addRow(u"快捷键", shortcut_edit)
        layout.addLayout(form)
        layer_list = QListWidget()
        for layer_name in self._layer_names():
            item = QListWidgetItem(layer_name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            layer_list.addItem(item)
        layout.addWidget(layer_list)
        add_button = QPushButton(u"保存方案")
        layout.addWidget(add_button)
        table = QTableWidget(0, 4, dialog)
        table.setHorizontalHeaderLabels([u"方案", u"模式", u"快捷键", u"操作"])
        table.setColumnWidth(0, 150)
        table.setColumnWidth(1, 140)
        table.setColumnWidth(2, 110)
        layout.addWidget(table)

        mode_names = {"only": u"只显示", "add": u"追加显示", "hide": u"隐藏", "all": u"全部显示"}

        def refresh_table():
            table.setRowCount(len(schemes))
            for row, (name, scheme) in enumerate(sorted(schemes.items())):
                table.setItem(row, 0, QTableWidgetItem(name))
                table.setItem(row, 1, QTableWidgetItem(mode_names.get(scheme.get("mode"), "")))
                table.setItem(row, 2, QTableWidgetItem(scheme.get("shortcut", "")))
                cell = QWidget()
                cell_layout = QHBoxLayout(cell)
                cell_layout.setContentsMargins(2, 2, 2, 2)
                apply_button = QPushButton(u"应用")
                apply_button.clicked.connect(lambda checked=False, n=name: self.apply_visibility_scheme(n))
                delete_button = QPushButton(u"删除")
                delete_button.clicked.connect(lambda checked=False, n=name: (schemes.pop(n, None), refresh_table()))
                cell_layout.addWidget(apply_button)
                cell_layout.addWidget(delete_button)
                table.setCellWidget(row, 3, cell)

        def save_scheme():
            name = name_edit.text().strip()
            mode = mode_combo.currentData()
            layers = [layer_list.item(i).text() for i in range(layer_list.count()) if layer_list.item(i).checkState() == Qt.Checked]
            if not name:
                QMessageBox.warning(dialog, u"提示", u"请输入方案名。")
                return
            if mode != "all" and not layers:
                QMessageBox.warning(dialog, u"提示", u"请至少选择一个图层。")
                return
            schemes[name] = {"mode": mode, "layers": layers, "shortcut": shortcut_edit.keySequence().toString()}
            name_edit.clear()
            shortcut_edit.clear()
            for i in range(layer_list.count()):
                layer_list.item(i).setCheckState(Qt.Unchecked)
            refresh_table()

        add_button.clicked.connect(save_scheme)
        refresh_table()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() == QDialog.Accepted:
            self._write_json("LayerVis/schemes", schemes)
            self._load_visibility_shortcuts()
            self._update_status_widgets()

    def _load_toggle_settings(self):
        settings = QSettings()
        self.target = settings.value("ToggleLayerSideButton/target", "group2", type=str)
        self.btn_set = {button for button, _ in MOUSE_BUTTONS if settings.value("ToggleLayerSideButton/btn_%d" % button, button == BACK, type=bool)}
        self.use_key = settings.value("ToggleLayerSideButton/use_key", False, type=bool)
        self.key_seq = settings.value("ToggleLayerSideButton/key_seq", "", type=str)
        self.restrict = settings.value("ToggleLayerSideButton/restrict", False, type=bool)
        self.active_layer = settings.value("ToggleLayerSideButton/active_layer", "BOUNDARY", type=str)

    def _toggle_targets(self):
        root = QgsProject.instance().layerTreeRoot()
        targets = []

        def add_groups(group, prefix=""):
            for child in group.children():
                if child.nodeType() == QgsLayerTreeNode.NodeGroup:
                    targets.append(child.name())
                    add_groups(child, prefix + child.name() + "/")

        add_groups(root)
        targets.extend(self._layer_names())
        return sorted(set(targets))

    def open_toggle_settings(self):
        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle(u"侧键切换图层设置")
        layout = QVBoxLayout(dialog)
        enabled = QCheckBox(u"启用切换图层")
        enabled.setChecked(self.efilter is not None)
        layout.addWidget(enabled)
        form = QFormLayout()
        target_combo = QComboBox()
        target_combo.setEditable(True)
        target_combo.addItems(self._toggle_targets())
        target_combo.setCurrentText(self.target)
        active_combo = QComboBox()
        active_combo.setEditable(True)
        active_combo.addItems(self._layer_names())
        active_combo.setCurrentText(self.active_layer)
        form.addRow(u"目标图层或分组", target_combo)
        layout.addLayout(form)
        button_group = QGroupBox(u"鼠标按键（可多选）")
        button_layout = QVBoxLayout(button_group)
        button_checks = {}
        for value, label in MOUSE_BUTTONS:
            checkbox = QCheckBox(label)
            checkbox.setChecked(value in self.btn_set)
            button_layout.addWidget(checkbox)
            button_checks[value] = checkbox
        layout.addWidget(button_group)
        keyboard_group = QGroupBox(u"键盘快捷键")
        keyboard_layout = QHBoxLayout(keyboard_group)
        use_key = QCheckBox(u"启用")
        use_key.setChecked(self.use_key)
        key_edit = QKeySequenceEdit(QKeySequence(self.key_seq))
        keyboard_layout.addWidget(key_edit)
        keyboard_layout.addWidget(use_key)
        layout.addWidget(keyboard_group)
        restrict = QCheckBox(u"仅当活动图层为以下图层时生效")
        restrict.setChecked(self.restrict)
        layout.addWidget(restrict)
        form.addRow(u"限定活动图层", active_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() != QDialog.Accepted:
            return
        settings = QSettings()
        settings.setValue("ToggleLayerSideButton/enabled", enabled.isChecked())
        settings.setValue("ToggleLayerSideButton/target", target_combo.currentText())
        for value, checkbox in button_checks.items():
            settings.setValue("ToggleLayerSideButton/btn_%d" % value, checkbox.isChecked())
        settings.setValue("ToggleLayerSideButton/use_key", use_key.isChecked())
        settings.setValue("ToggleLayerSideButton/key_seq", key_edit.keySequence().toString())
        settings.setValue("ToggleLayerSideButton/restrict", restrict.isChecked())
        settings.setValue("ToggleLayerSideButton/active_layer", active_combo.currentText())
        settings.sync()
        self._stop_toggle_filter()
        self._stop_toggle_shortcut()
        self._load_toggle_settings()
        if enabled.isChecked():
            self._start_toggle_filter()
            if self.use_key and self.key_seq:
                self._start_toggle_shortcut()

    def _start_toggle_filter(self):
        if self.efilter is None:
            self.efilter = _CanvasEventFilter(self._toggle_layer, self.btn_set)
            self.canvas.viewport().installEventFilter(self.efilter)

    def _stop_toggle_filter(self):
        if self.efilter is not None:
            self.canvas.viewport().removeEventFilter(self.efilter)
            self.efilter = None

    def _start_toggle_shortcut(self):
        if self.shortcut is None:
            self.shortcut = QShortcut(QKeySequence(self.key_seq), self.iface.mainWindow())
            self.shortcut.activated.connect(self._toggle_layer)

    def _stop_toggle_shortcut(self):
        if self.shortcut is not None:
            self.shortcut.setParent(None)
            self.shortcut.deleteLater()
            self.shortcut = None

    def _toggle_layer(self):
        if self.restrict:
            layer = self.iface.activeLayer()
            if layer is None or layer.name() != self.active_layer:
                return
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(self.target)
        if group is not None:
            visible = not group.itemVisibilityChecked()
            group.setItemVisibilityChecked(visible)
        else:
            node = next((root.findLayer(layer.id()) for layer in QgsProject.instance().mapLayers().values() if layer.name() == self.target), None)
            if node is None:
                self._warning(u"切换图层", u"未找到图层或分组: " + self.target)
                return
            visible = not node.itemVisibilityChecked()
            node.setItemVisibilityChecked(visible)
        self.canvas.refresh()
        self._message(u"切换图层", u"'%s' %s" % (self.target, u"已显示" if visible else u"已隐藏"))

    def _update_status_widgets(self):
        switch_parts = [u"%s=%s" % (shortcut, name[:8]) for name, shortcut in self._read_json("LayerSwitch/bindings").items() if shortcut]
        vis_parts = [u"%s=%s" % (scheme.get("shortcut"), name[:6]) for name, scheme in self._read_json("LayerVis/schemes").items() if scheme.get("shortcut")]
        if self.status_switch is not None:
            self.status_switch.setText(u"  |  ".join(switch_parts))
        if self.status_vis is not None:
            self.status_vis.setText(u"  |  ".join(vis_parts))

    def _message(self, title, text, duration=2):
        self.iface.messageBar().pushMessage(title, text, level=Qgis.Info, duration=duration)

    def _warning(self, title, text):
        self.iface.messageBar().pushMessage(title, text, level=Qgis.Warning, duration=3)
