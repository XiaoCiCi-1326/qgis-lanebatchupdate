# -*- coding: utf-8 -*-
"""管理检测规则并显示错误记录。"""
from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtGui import QColor, QKeySequence
import os
import re
import sqlite3
from datetime import datetime
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsRubberBand
from .lane_fix_excel import LaneFixAction, parse_error_texts
from .lane_fix_engine import LaneFixEngine


class CopyableTableWidget(QTableWidget):
    """不可编辑但可选择单元格文本，并支持 Ctrl+C 复制。"""

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            indexes = self.selectedIndexes()
            if indexes:
                rows = {}
                for index in indexes:
                    rows.setdefault(index.row(), {})[index.column()] = index.data(Qt.DisplayRole) or ""
                text = "\n".join(
                    "\t".join(cols.get(col, "") for col in range(self.columnCount()))
                    for _, cols in sorted(rows.items())
                )
                QApplication.clipboard().setText(text)
                return
        super().keyPressEvent(event)


class ErrorResultsController:
    def __init__(self, iface):
        self.iface = iface
        self.dialog = None
        self.records = []
        self.right_straight_checker = None
        self.boundary_checker = None
        self.speed_checker = None
        self.virtual_checker = None
        self.duplicate_vertex_checker = None
        self.extra_endpoint_checker = None
        self.dangling_point_checker = None
        self.overlapping_line_checker = None
        self.lane_num_checker = None
        self.clear_highlights_callback = None
        self.location_marker = None
        self._fix_log_path = None
        self._fix_log_lines = []

    def _log(self, text, level="INFO", show_bar=True):
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [{level}] {text}"
        if self._fix_log_path is not None:
            self._fix_log_lines.append(line)
        if show_bar:
            self.iface.messageBar().pushMessage("车道工具", str(text), duration=4)

    def fix_quality_records(self, records):
        """修复选中的 3.16 质检记录；当前支持 marktype=11 全局移除规则。"""
        self._fix_log_lines = []
        log_dir = os.path.join(os.path.dirname(__file__), "log")
        os.makedirs(log_dir, exist_ok=True)
        self._fix_log_path = os.path.join(log_dir, f"quality_fix_{datetime.now():%Y%m%d_%H%M%S}.log")
        actions = []
        for record in records:
            source = record.get("quality_source") or {}
            detail = str(source.get("DETAIL") or record.get("message") or "")
            # 质检库常把 LANE_MARKING、LANEMARKID 放在独立列，DETAIL
            # 只保存“marktype 是 11 ...”的描述；组合字段后再解析。
            combined = " ".join(
                str(source.get(key) or "")
                for key in ("LAYER", "FEATUREID", "LANEMARKID", "MARKTYPE", "DETAIL")
            )
            parsed = parse_error_texts(combined)
            self._log(
                "质检原始字段: LAYER=%r FEATUREID=%r LANEMARKID=%r MARKTYPE=%r DETAIL=%r"
                % (source.get("LAYER"), source.get("FEATUREID"), source.get("LANEMARKID"), source.get("MARKTYPE"), detail),
                show_bar=False,
            )
            self._log(f"组合解析文本: {combined}", show_bar=False)
            if not parsed:
                layer = str(source.get("LAYER") or "").upper()
                mark_type = str(source.get("MARKTYPE") or "")
                is_marktype11 = re.search(r"(?:是|=|:)\s*11\b|\b11\b", mark_type + " " + detail)
                is_outer_type_error = re.search(
                    r"最外侧边界.*?边线类型\s*(?:为|是|=|:)\s*[19](?:\s*或\s*[19])?",
                    detail,
                    re.IGNORECASE,
                )
                if layer == "LANE_MARKING" and (is_marktype11 or is_outer_type_error):
                    mark_id_match = re.search(r"LANEMARKID\s*[=:：]?\s*(\d{6,})", combined, re.I)
                    if not mark_id_match:
                        mark_id_match = re.search(r"\b(\d{6,})\b", str(source.get("FEATUREID") or ""))
                    if mark_id_match and re.search(r"最外侧边界|外侧边界", detail):
                        parsed = [LaneFixAction(
                            "remove_mark_global", "RBDY_L/R", "", "",
                            [mark_id_match.group(1)], combined,
                            note=f"marktype=11：从 LANE 的 RBDY_L/R 移除 {mark_id_match.group(1)}",
                        )]
            actions.extend(parsed)
            self._log(
                "解析动作: %s" % ([{"action": a.action, "mark_ids": a.mark_ids, "field": a.target_field} for a in parsed]),
                show_bar=False,
            )
        actions = [a for a in actions if a.action == "remove_mark_global"]
        if not actions:
            self._write_fix_log()
            QMessageBox.information(self.iface.mainWindow(), "没有可修复记录", "选中的记录中没有当前支持的自动修复规则。")
            return None
        layers = QgsProject.instance().mapLayersByName("LANE")
        lane = next((x for x in layers if isinstance(x, QgsVectorLayer)), None)
        if lane is None:
            self._log("未找到名称为 LANE 的矢量图层", level="ERROR", show_bar=False)
            self._write_fix_log()
            QMessageBox.warning(self.iface.mainWindow(), "缺少 LANE 图层", "请先加载 LANE 图层。")
            return None
        try:
            self._log("LANE图层: name=%r source=%r feature_count=%d" % (lane.name(), lane.source(), lane.featureCount()), show_bar=False)
            self._log("LANE字段: %s" % [field.name() for field in lane.fields()], show_bar=False)
            stats = LaneFixEngine(lane, self._log).apply_all(actions)
            lane.triggerRepaint()
            self._log("修复统计: %s" % stats, show_bar=False)
            self._write_fix_log()
            QMessageBox.information(self.iface.mainWindow(), "修复完成", "已处理 %d 条记录，更新 %d 条 LANE 要素。\n日志：%s" % (len(actions), stats.get("features_updated", 0), self._fix_log_path))
            return stats
        except Exception as exc:
            self._log("异常: %r" % (exc,), level="ERROR", show_bar=False)
            self._write_fix_log()
            QMessageBox.critical(self.iface.mainWindow(), "修复失败", str(exc))
            return None

    def _write_fix_log(self):
        if not self._fix_log_path:
            return
        try:
            with open(self._fix_log_path, "w", encoding="utf-8-sig") as handle:
                handle.write("\n".join(self._fix_log_lines) + "\n")
        except OSError:
            pass

    def configure_checkers(
        self,
        right_straight_checker,
        boundary_checker,
        clear_highlights_callback,
        speed_checker=None,
        virtual_checker=None,
        duplicate_vertex_checker=None,
        extra_endpoint_checker=None,
        dangling_point_checker=None,
        overlapping_line_checker=None,
        lane_num_checker=None,
    ):
        self.right_straight_checker = right_straight_checker
        self.boundary_checker = boundary_checker
        self.speed_checker = speed_checker
        self.virtual_checker = virtual_checker
        self.duplicate_vertex_checker = duplicate_vertex_checker
        self.extra_endpoint_checker = extra_endpoint_checker
        self.dangling_point_checker = dangling_point_checker
        self.overlapping_line_checker = overlapping_line_checker
        self.lane_num_checker = lane_num_checker
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
        self._clear_location_marker()
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
        try:
            self.load_latest_quality_errors()
        except (FileNotFoundError, RuntimeError, sqlite3.Error):
            pass
        self.dialog.setWindowTitle(title)
        self.dialog.show_rules()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def load_latest_quality_errors(self, folder=r"D:\check_error"):
        """读取最新的 QGIS 3.16/JD 质检库并转换为错误记录。"""
        candidates = []
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                if name.lower().startswith("temp.sqlite") and os.path.isfile(path):
                    candidates.append(path)
        if not candidates:
            raise FileNotFoundError("未找到 D:\\check_error\\temp.sqlite* 质检文件")

        database_path = max(candidates, key=os.path.getmtime)
        records = []
        connection = sqlite3.connect("file:%s?mode=ro" % database_path.replace("\\", "/"), uri=True)
        try:
            columns = [row[1].upper() for row in connection.execute("PRAGMA table_info(ERROR_LOG)")]
            if not columns:
                raise RuntimeError("质检库缺少 ERROR_LOG 表")
            rows = connection.execute("SELECT * FROM ERROR_LOG ORDER BY ID").fetchall()
            for row in rows:
                data = dict(zip(columns, row))
                record = self._quality_error_record(data)
                if record is not None:
                    records.append(record)
        finally:
            connection.close()

        self.records = [record for record in self.records if "quality_source" not in record]
        self.records.extend(records)
        if self.dialog is not None:
            self.dialog.refresh(self.records)
        return database_path, records

    @staticmethod
    def _quality_error_record(data):
        layer_names = {
            "LANE_MARKING": "BOUNDARY",
            "LANE": "LANE",
            "TRAFFICLIGHT": "SIGNAL",
        }
        source_layer = str(data.get("LAYER") or "").strip().upper()
        primary_layer = layer_names.get(source_layer, source_layer)
        selections = {}
        display_ids = {}
        display_layers = {}

        def add_selection(source_name, raw_ids):
            target_name = layer_names.get(str(source_name or "").strip().upper(), str(source_name or "").strip().upper())
            ids = [
                item.strip().strip("'\"")
                for item in re.split(r"[,;|]", str(raw_ids or ""))
                if item.strip().strip("'\"")
            ]
            if not target_name or not ids:
                return
            layer = ErrorResultsController._find_vector_layer(target_name)
            feature_ids = []
            if layer is not None:
                field_names = {field.name().upper(): field.name() for field in layer.fields()}
                id_field = field_names.get("ID")
                if id_field:
                    wanted = set(ids)
                    for feature in layer.getFeatures():
                        value = str(feature[id_field]).strip()
                        if value in wanted:
                            feature_ids.append(feature.id())
                else:
                    feature_ids = [int(value) for value in ids if value.lstrip("-").isdigit()]
            display_key = layer.id() if layer is not None else target_name
            display_ids[display_key] = ids
            display_layers[display_key] = layer.name() if layer is not None else target_name
            if feature_ids and layer is not None:
                selections[layer.id()] = list(dict.fromkeys(feature_ids))

        add_selection(primary_layer, data.get("FEATUREID"))
        add_selection(data.get("REF_LAYER_1"), data.get("RL_1_FIELD_1_IS"))
        add_selection(data.get("REF_LAYER_2"), data.get("RL_1_FIELD_2_IS"))
        detail = str(data.get("DETAIL") or "").strip()
        rule = str(data.get("RULENO") or "").strip()
        level = str(data.get("ERRORLEVEL") or "").strip()
        return {
            "type": "3.16质检规则 %s" % rule if rule else "3.16质检错误",
            "message": "[%s] %s" % (level, detail) if level else detail,
            "selections": selections,
            "display_layers": display_layers,
            "display_ids": display_ids,
            "quality_source": data,
        }

    @staticmethod
    def _find_vector_layer(name):
        if not name:
            return None
        project = QgsProject.instance()
        layers = project.mapLayersByName(name)
        if layers:
            return next((layer for layer in layers if isinstance(layer, QgsVectorLayer)), None)
        target = "%s.shp" % name.lower()
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            source = layer.source().split("|", 1)[0]
            if os.path.basename(source).lower() == target:
                return layer
        return None

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
        location = record.get("location")
        if location is not None:
            point = QgsPointXY(float(location[0]), float(location[1]))
            self._show_location_marker(point)
            canvas.setCenter(point)
            canvas.zoomScale(canvas.scale() * 0.15)
        else:
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

    def _show_location_marker(self, point):
        self._clear_location_marker()
        canvas = self.iface.mapCanvas()
        self.location_marker = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        self.location_marker.setToGeometry(QgsGeometry.fromPointXY(point), None)
        self.location_marker.setColor(QColor("#e53935"))
        self.location_marker.setWidth(5)
        self.location_marker.show()

    def _clear_location_marker(self):
        if self.location_marker is not None:
            try:
                self.iface.mapCanvas().scene().removeItem(self.location_marker)
            except (AttributeError, RuntimeError):
                pass
            self.location_marker = None

    def unload(self):
        self._clear_location_marker()
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
        self.extra_endpoint_short_enabled_key = "LaneBatchUpdate/extraEndpointShortEnabled"
        self.extra_endpoint_short_threshold_key = "LaneBatchUpdate/extraEndpointShortThreshold"
        self.overlap_length_enabled_key = "LaneBatchUpdate/overlapLengthEnabled"
        self.overlap_length_threshold_key = "LaneBatchUpdate/overlapLengthThreshold"
        self.overlap_exact_enabled_key = "LaneBatchUpdate/overlapExactEnabled"
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
        self.duplicate_vertex_rule = self._add_rule("重复顶点检查")
        self.extra_endpoint_rule = self._add_rule("BOUNDARY多余端点检查")
        self.dangling_point_rule = self._add_rule("BOUNDARY/LANE悬挂点检查")
        self.overlapping_line_rule = self._add_rule("BOUNDARY/LANE重合线检查")
        self.lane_num_rule = self._add_rule("LANE_NUM字段检测")
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

        self.extra_endpoint_options = QWidget(page)
        extra_options_layout = QHBoxLayout(self.extra_endpoint_options)
        extra_options_layout.setContentsMargins(0, 0, 0, 0)
        self.extra_endpoint_short_enabled = QCheckBox("仅检查至少一条线长度小于", self.extra_endpoint_options)
        self.extra_endpoint_short_enabled.setChecked(self._setting_bool(self.extra_endpoint_short_enabled_key, False))
        self.extra_endpoint_short_enabled.toggled.connect(self._save_extra_endpoint_settings)
        extra_options_layout.addWidget(self.extra_endpoint_short_enabled)
        self.extra_endpoint_short_threshold = QDoubleSpinBox(self.extra_endpoint_options)
        self.extra_endpoint_short_threshold.setRange(0, 1e12)
        self.extra_endpoint_short_threshold.setDecimals(6)
        self.extra_endpoint_short_threshold.setSingleStep(1.0)
        self.extra_endpoint_short_threshold.setValue(self._setting_float(self.extra_endpoint_short_threshold_key, 5.0))
        self.extra_endpoint_short_threshold.valueChanged.connect(self._save_extra_endpoint_settings)
        extra_options_layout.addWidget(self.extra_endpoint_short_threshold)
        extra_options_layout.addWidget(QLabel("米", self.extra_endpoint_options))
        extra_options_layout.addStretch(1)
        layout.addWidget(self.extra_endpoint_options)

        self.overlap_options = QWidget(page)
        overlap_options_layout = QHBoxLayout(self.overlap_options)
        overlap_options_layout.setContentsMargins(0, 0, 0, 0)
        self.overlap_length_enabled = QCheckBox("重合长度不少于", self.overlap_options)
        self.overlap_length_enabled.setChecked(self._setting_bool(self.overlap_length_enabled_key, True))
        self.overlap_length_enabled.toggled.connect(self._save_overlap_settings)
        overlap_options_layout.addWidget(self.overlap_length_enabled)
        self.overlap_length_threshold = QDoubleSpinBox(self.overlap_options)
        self.overlap_length_threshold.setRange(0, 1e12)
        self.overlap_length_threshold.setDecimals(6)
        self.overlap_length_threshold.setSingleStep(1.0)
        self.overlap_length_threshold.setValue(self._setting_float(self.overlap_length_threshold_key, 1.0))
        self.overlap_length_threshold.valueChanged.connect(self._save_overlap_settings)
        overlap_options_layout.addWidget(self.overlap_length_threshold)
        overlap_options_layout.addWidget(QLabel("米", self.overlap_options))
        self.overlap_exact_enabled = QCheckBox("检查完全重合", self.overlap_options)
        self.overlap_exact_enabled.setChecked(self._setting_bool(self.overlap_exact_enabled_key, True))
        self.overlap_exact_enabled.toggled.connect(self._save_overlap_settings)
        overlap_options_layout.addWidget(self.overlap_exact_enabled)
        overlap_options_layout.addStretch(1)
        layout.addWidget(self.overlap_options)

        self.progress_label = QLabel("尚未执行规则。", page)
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar(page)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        buttons = QHBoxLayout()
        self.run_quality_button = QPushButton("读取最新 3.16 质检错误", page)
        self.run_quality_button.clicked.connect(self._load_quality_errors)
        buttons.addWidget(self.run_quality_button)
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
        self.table = CopyableTableWidget(0, 4, page)
        self.table.setHorizontalHeaderLabels(["检测类型", "错误记录", "涉及图层", "涉及要素"])
        self.table.setSelectionBehavior(QTableWidget.SelectItems)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._select_current_record)
        self.table.itemDoubleClicked.connect(self._fix_double_clicked)
        layout.addWidget(self.table, 1)
        self.detail_edit = QPlainTextEdit(page)
        self.detail_edit.setReadOnly(True)
        self.detail_edit.setPlaceholderText("选中错误记录后，可在此按字符选择并复制错误文本。")
        self.detail_edit.setMaximumHeight(90)
        self.detail_edit.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        layout.addWidget(self.detail_edit)
        buttons = QHBoxLayout()
        clear_button = QPushButton("清空记录", page)
        clear_button.clicked.connect(self._clear_results)
        buttons.addWidget(clear_button)
        fix_button = QPushButton("修复选中错误", page)
        fix_button.setToolTip("支持 Shift/Ctrl 多选；双击单条记录也可修复")
        fix_button.clicked.connect(self._fix_selected_records)
        buttons.addWidget(fix_button)
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
            display_keys = list(dict.fromkeys(list(display_ids.keys()) + list(selections.keys())))
            layers = ", ".join(
                display_layers.get(layer_key, layer_key) for layer_key in display_keys
            )
            involved = "; ".join(
                "%s: %s" % (
                    display_layers.get(layer_key, layer_key),
                    ", ".join(str(value) for value in display_ids.get(layer_key, selections.get(layer_key, []))),
                )
                for layer_key in display_keys
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
        self.extra_endpoint_options.setVisible(current is self.extra_endpoint_rule)
        self.overlap_options.setVisible(current is self.overlapping_line_rule)

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

    def _setting_bool(self, key, default):
        value = self.settings.value(key, default)
        return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes")

    def _setting_float(self, key, default):
        try:
            return float(self.settings.value(key, default))
        except (TypeError, ValueError):
            return default

    def _save_extra_endpoint_settings(self, *args):
        self.settings.setValue(self.extra_endpoint_short_enabled_key, self.extra_endpoint_short_enabled.isChecked())
        self.settings.setValue(self.extra_endpoint_short_threshold_key, self.extra_endpoint_short_threshold.value())
        self.settings.sync()

    def _save_overlap_settings(self, *args):
        self.settings.setValue(self.overlap_length_enabled_key, self.overlap_length_enabled.isChecked())
        self.settings.setValue(self.overlap_length_threshold_key, self.overlap_length_threshold.value())
        self.settings.setValue(self.overlap_exact_enabled_key, self.overlap_exact_enabled.isChecked())
        self.settings.sync()

    def _set_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.progress_label.setText(message)
        QApplication.processEvents()

    def _load_quality_errors(self):
        try:
            path, records = self.controller.load_latest_quality_errors()
        except (FileNotFoundError, RuntimeError, sqlite3.Error) as exc:
            QMessageBox.critical(self, "读取质检错误失败", str(exc))
            return
        self.refresh(self.controller.records)
        self.tabs.setCurrentWidget(self.results_page)
        self.summary.setText(
            "已读取最新质检库：%s，共 %d 条错误记录。点击一行可选中涉及要素。"
            % (os.path.basename(path), len(records))
        )

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
        if self.duplicate_vertex_rule.checkState() == Qt.Checked:
            selected_rules.append(("重复顶点检查", self.controller.duplicate_vertex_checker))
        if self.extra_endpoint_rule.checkState() == Qt.Checked:
            selected_rules.append(("BOUNDARY多余端点检查", self.controller.extra_endpoint_checker))
        if self.dangling_point_rule.checkState() == Qt.Checked:
            selected_rules.append(("BOUNDARY/LANE悬挂点检查", self.controller.dangling_point_checker))
        if self.overlapping_line_rule.checkState() == Qt.Checked:
            selected_rules.append(("BOUNDARY/LANE重合线检查", self.controller.overlapping_line_checker))
        if self.lane_num_rule.checkState() == Qt.Checked:
            selected_rules.append(("LANE_NUM字段检测", self.controller.lane_num_checker))
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
                elif name == "BOUNDARY多余端点检查":
                    checker(
                        self.extra_endpoint_short_enabled.isChecked(),
                        self.extra_endpoint_short_threshold.value(),
                    )
                elif name == "BOUNDARY/LANE重合线检查":
                    checker(
                        self.overlap_length_enabled.isChecked(),
                        self.overlap_length_threshold.value(),
                        self.overlap_exact_enabled.isChecked(),
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
            record = item.data(Qt.UserRole)
            self.controller.select_record(record)
            source = record.get("quality_source", {}) if isinstance(record, dict) else {}
            detail = str(source.get("DETAIL") or record.get("message") or "")
            self.detail_edit.setPlainText(detail)

    def _selected_records(self):
        records = []
        seen = set()
        rows = sorted({index.row() for index in self.table.selectionModel().selectedIndexes()})
        for row in rows:
            item = self.table.item(row, 0)
            record = item.data(Qt.UserRole) if item else None
            if record is not None and id(record) not in seen:
                records.append(record)
                seen.add(id(record))
        return records

    def _fix_double_clicked(self, item):
        record = self.table.item(item.row(), 0).data(Qt.UserRole)
        if record:
            self.controller.fix_quality_records([record])

    def _fix_selected_records(self):
        records = self._selected_records()
        if not records:
            QMessageBox.warning(self, "未选择记录", "请使用 Ctrl/Shift 选择要修复的错误记录。")
            return
        self.controller.fix_quality_records(records)

    def closeEvent(self, event):
        self._save_boundary_settings()
        self._save_extra_endpoint_settings()
        self._save_overlap_settings()
        self.settings.setValue(self.size_key, self.size())
        self.settings.sync()
        super().closeEvent(event)

    def _clear_results(self):
        self.controller.clear()
