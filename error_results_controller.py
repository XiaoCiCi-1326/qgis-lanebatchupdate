# -*- coding: utf-8 -*-
"""管理检测规则并显示错误记录。"""
from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsProject, QgsRectangle, QgsVectorLayer


class ErrorResultsController:
    def __init__(self, iface):
        self.iface = iface
        self.dialog = None
        self.records = []
        self.right_straight_checker = None
        self.boundary_checker = None
        self.speed_checker = None
        self.virtual_checker = None
        self.clear_highlights_callback = None

    def configure_checkers(
        self,
        right_straight_checker,
        boundary_checker,
        clear_highlights_callback,
        speed_checker=None,
        virtual_checker=None,
    ):
        self.right_straight_checker = right_straight_checker
        self.boundary_checker = boundary_checker
        self.speed_checker = speed_checker
        self.virtual_checker = virtual_checker
        self.clear_highlights_callback = clear_highlights_callback

    def replace_records(self, records, record_type, title=None):
        self.records = [record for record in self.records if record.get("type") != record_type]
        self.records.extend(records)
        if self.dialog is not None:
            self.dialog.refresh(self.records)

    def add_records(self, records, title=None):
        if not records:
            return
        for record_type in {record.get("type") for record in records}:
            self.records = [record for record in self.records if record.get("type") != record_type]
        self.records.extend(records)
        if self.dialog is not None:
            self.dialog.refresh(self.records)

    def clear(self):
        self.records = []
        if self.clear_highlights_callback is not None:
            self.clear_highlights_callback()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                layer.removeSelection()
        self.iface.mapCanvas().refresh()
        if self.dialog is not None:
            self.dialog.refresh(self.records)

    def show(self, title="全部规则"):
        if self.dialog is None:
            self.dialog = ErrorResultsDialog(self, self.iface.mainWindow())
        self.dialog.setWindowTitle(title)
        self.dialog.show_rules()
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
            self.iface.setActiveLayer(next(iter(layers_to_select.values()))[0])
        canvas = self.iface.mapCanvas()
        extent = QgsRectangle()
        has_extent = False
        for layer, _ in layers_to_select.values():
            for feature in layer.selectedFeatures():
                geometry = feature.geometry()
                if geometry is None or geometry.isEmpty():
                    continue
                feature_extent = geometry.boundingBox()
                if not has_extent:
                    extent = QgsRectangle(feature_extent)
                    has_extent = True
                else:
                    extent.combineExtentWith(feature_extent)
        if has_extent:
            canvas.setExtent(extent)
            canvas.zoomScale(canvas.scale() * 1.25)
        canvas.refresh()

    def unload(self):
        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None
        self.records = []


class ErrorResultsDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.settings = QSettings()
        self.size_key = "LaneBatchUpdate/errorResultsDialogSize"
        self.boundary_operator_key = "LaneBatchUpdate/boundaryLengthOperator"
        self.boundary_threshold_key = "LaneBatchUpdate/boundaryLengthThreshold"
        self.setWindowTitle("全部规则")
        self.setMinimumSize(760, 420)
        saved_size = self.settings.value(self.size_key)
        if saved_size is not None and hasattr(saved_size, "isValid") and saved_size.isValid():
            self.resize(saved_size)
        else:
            self.resize(900, 520)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        self.rules_page = self._build_rules_page()
        self.results_page = self._build_results_page()
        self.tabs.addTab(self.rules_page, "全部规则")
        self.tabs.addTab(self.results_page, "错误记录")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        buttons = QHBoxLayout()
        self.close_button = QPushButton("关闭", self)
        self.close_button.clicked.connect(self.close)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def _build_rules_page(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("规则列表", page))

        batch_buttons = QHBoxLayout()
        select_all_button = QPushButton("全部选择", page)
        select_all_button.clicked.connect(lambda: self._set_all_rules(Qt.Checked))
        clear_all_button = QPushButton("全部取消", page)
        clear_all_button.clicked.connect(lambda: self._set_all_rules(Qt.Unchecked))
        invert_button = QPushButton("反选", page)
        invert_button.clicked.connect(self._invert_rule_selection)
        batch_buttons.addWidget(select_all_button)
        batch_buttons.addWidget(clear_all_button)
        batch_buttons.addWidget(invert_button)
        batch_buttons.addStretch(1)
        layout.addLayout(batch_buttons)

        self.rules_list = QListWidget(page)
        self.right_straight_rule = self._add_rule("右转压直行")
        self.boundary_rule = self._add_rule("BOUNDARY长度检测")
        self.speed_rule = self._add_rule("SPEEDLIMIT不能为空且不能为40")
        self.virtual_rule = self._add_rule("路口LANE与VIRTUAL检查")
        self.rules_list.currentItemChanged.connect(self._update_rule_options)
        layout.addWidget(self.rules_list, 1)

        self.boundary_options = QWidget(page)
        options_layout = QHBoxLayout(self.boundary_options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.addWidget(QLabel("BOUNDARY 长度条件", self.boundary_options))
        self.boundary_operator = QComboBox(self.boundary_options)
        self.boundary_operator.addItems(["小于", "大于", "等于"])
        saved_operator = self.settings.value(self.boundary_operator_key, "小于")
        operator_index = self.boundary_operator.findText(str(saved_operator))
        self.boundary_operator.setCurrentIndex(max(0, operator_index))
        self.boundary_operator.currentTextChanged.connect(self._save_boundary_settings)
        options_layout.addWidget(self.boundary_operator)
        self.boundary_threshold = QDoubleSpinBox(self.boundary_options)
        self.boundary_threshold.setRange(0, 1e12)
        self.boundary_threshold.setDecimals(6)
        self.boundary_threshold.setSingleStep(1.0)
        try:
            saved_threshold = float(self.settings.value(self.boundary_threshold_key, 10.0))
        except (TypeError, ValueError):
            saved_threshold = 10.0
        self.boundary_threshold.setValue(saved_threshold)
        self.boundary_threshold.valueChanged.connect(self._save_boundary_settings)
        options_layout.addWidget(QLabel("长度", self.boundary_options))
        options_layout.addWidget(self.boundary_threshold)
        options_layout.addStretch(1)
        layout.addWidget(self.boundary_options)

        self.progress_label = QLabel("尚未执行规则。", page)
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar(page)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        buttons = QHBoxLayout()
        self.run_rules_button = QPushButton("执行选中规则", page)
        self.run_rules_button.clicked.connect(self._run_selected_rules)
        buttons.addWidget(self.run_rules_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.rules_list.setCurrentItem(self.right_straight_rule)
        return page

    def _build_results_page(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        self.summary = QLabel(page)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 4, page)
        self.table.setHorizontalHeaderLabels(["检测类型", "错误记录", "涉及图层", "涉及要素"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._select_current_record)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        clear_button = QPushButton("清空记录", page)
        clear_button.clicked.connect(self._clear_results)
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return page

    def _add_rule(self, name):
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Unchecked)
        self.rules_list.addItem(item)
        return item

    def show_rules(self):
        self.tabs.setCurrentWidget(self.rules_page)

    def show_results(self):
        self.refresh(self.controller.records)
        self.tabs.setCurrentWidget(self.results_page)

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
                display_layers.get(layer_key, layer_key) for layer_key in selections.keys()
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

    def _on_tab_changed(self, index):
        if self.tabs.widget(index) is self.results_page:
            self.refresh(self.controller.records)

    def _update_rule_options(self, current, previous):
        self.boundary_options.setVisible(current is self.boundary_rule)

    def _set_all_rules(self, state):
        for row in range(self.rules_list.count()):
            self.rules_list.item(row).setCheckState(state)

    def _invert_rule_selection(self):
        for row in range(self.rules_list.count()):
            item = self.rules_list.item(row)
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    def _save_boundary_settings(self, *args):
        self.settings.setValue(self.boundary_operator_key, self.boundary_operator.currentText())
        self.settings.setValue(self.boundary_threshold_key, self.boundary_threshold.value())
        self.settings.sync()

    def _set_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.progress_label.setText(message)
        QApplication.processEvents()

    def _run_selected_rules(self):
        selected_rules = []
        if self.right_straight_rule.checkState() == Qt.Checked:
            selected_rules.append(("右转压直行", self.controller.right_straight_checker))
        if self.boundary_rule.checkState() == Qt.Checked:
            selected_rules.append(("BOUNDARY长度检测", self.controller.boundary_checker))
        if self.speed_rule.checkState() == Qt.Checked:
            selected_rules.append(("SPEEDLIMIT不能为空且不能为40", self.controller.speed_checker))
        if self.virtual_rule.checkState() == Qt.Checked:
            selected_rules.append(("路口LANE与VIRTUAL检查", self.controller.virtual_checker))
        if not selected_rules:
            self._set_progress(0, "请至少选择一条规则。")
            self.rules_list.setFocus()
            return

        self._save_boundary_settings()
        self.run_rules_button.setEnabled(False)
        self._set_progress(0, "准备执行规则...")
        total = len(selected_rules)
        try:
            for index, (name, checker) in enumerate(selected_rules, 1):
                self._set_progress(
                    int((index - 1) * 100 / total), "正在执行：%s" % name
                )
                if checker is None:
                    continue
                if name == "BOUNDARY长度检测":
                    checker(
                        self.boundary_operator.currentText(),
                        self.boundary_threshold.value(),
                    )
                else:
                    checker()
                self._set_progress(int(index * 100 / total), "已完成：%s" % name)
        finally:
            self.run_rules_button.setEnabled(True)
        self.refresh(self.controller.records)
        self.tabs.setCurrentWidget(self.results_page)

    def _select_current_record(self):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is not None:
            self.controller.select_record(item.data(Qt.UserRole))

    def closeEvent(self, event):
        self._save_boundary_settings()
        self.settings.setValue(self.size_key, self.size())
        self.settings.sync()
        super().closeEvent(event)

    def _clear_results(self):
        self.controller.clear()
