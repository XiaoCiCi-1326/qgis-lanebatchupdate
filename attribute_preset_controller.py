# -*- coding: utf-8 -*-
"""按图层保存并应用属性预设。"""
import json
import math

from qgis.PyQt.QtCore import QMimeData, QPoint, QSettings, QTimer, Qt, pyqtSignal
from qgis.PyQt.QtGui import QDrag, QIcon, QColor
from qgis.PyQt.QtWidgets import (
    QAction,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsGeometry,
    QgsMessageLog,
    QgsPointLocator,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    NULL,
)
from qgis.gui import (
    QgsAttributeForm,
    QgsMapTool,
    QgsMapToolIdentifyFeature,
    QgsRubberBand,
    QgsSnapIndicator,
)


_ACTIVE_CONTROLLER = None


def init_attribute_form(dialog, layer, feature):
    if _ACTIVE_CONTROLLER is None:
        return
    if isinstance(layer, str):
        layer = QgsProject.instance().mapLayer(layer)
    _ACTIVE_CONTROLLER.add_form_preset_widget(dialog, layer)


class AddFeatureMapTool(QgsMapTool):
    def __init__(self, controller, layer):
        super().__init__(controller.iface.mapCanvas())
        self.controller = controller
        self.layer = layer
        self.canvas = controller.iface.mapCanvas()
        self.points = []
        self._paused = False
        self._cancelled = False
        self.mode = getattr(controller, "shape_mode", "line")
        self.snap_indicator = QgsSnapIndicator(self.canvas)
        self.snap_indicator.setMatch(QgsPointLocator.Match())
        self.rubber_band = QgsRubberBand(self.canvas, layer.geometryType())
        preview_color = QColor(255, 0, 0, 51 if layer.geometryType() == 2 else 255)
        self.rubber_band.setColor(preview_color)
        self.rubber_band.setWidth(2)
        self.rubber_band.setVisible(True)
        self.constraint_hint = QLabel(self.canvas)
        self.constraint_hint.setStyleSheet(
            "background: rgba(35, 35, 35, 210); color: white; "
            "border: 1px solid #777; border-radius: 3px; padding: 2px 5px;"
        )
        self.constraint_hint.hide()

    def set_mode(self, mode):
        if self.points:
            self.points.clear()
        self.mode = mode or "line"
        self._refresh_rubber_band()

    def _required_control_count(self):
        return {
            "circle": 2,
            "ellipse": 3,
            "arc": 3,
            "rectangle": 3,
            "triangle": 2,
            "regular_polygon": 2,
        }.get(self.mode)

    def _shape_points(self, cursor_point=None):
        controls = list(self.points)
        if cursor_point is not None:
            controls.append(cursor_point)
        if self.mode in ("line", "polygon"):
            return controls
        if self.mode in ("triangle", "regular_polygon"):
            if len(controls) < 2:
                return controls
            center, vertex = controls[0], controls[1]
            count = 3 if self.mode == "triangle" else self.controller.regular_polygon_sides
            radius_x = vertex.x() - center.x()
            radius_y = vertex.y() - center.y()
            radius = math.hypot(radius_x, radius_y)
            start_angle = math.atan2(radius_y, radius_x)
            polygon_points = [
                QgsPointXY(
                    center.x() + radius * math.cos(start_angle + 2.0 * math.pi * i / count),
                    center.y() + radius * math.sin(start_angle + 2.0 * math.pi * i / count),
                )
                for i in range(count)
            ]
            return polygon_points + [polygon_points[0]]
        if self.mode == "rectangle":
            if len(controls) < 2:
                return controls
            start, end = controls[0], controls[1]
            base_x = end.x() - start.x()
            base_y = end.y() - start.y()
            base_length = math.hypot(base_x, base_y)
            if base_length == 0.0 or len(controls) < 3:
                return controls
            width_point = controls[2]
            normal_x = -base_y / base_length
            normal_y = base_x / base_length
            width = (width_point.x() - start.x()) * normal_x + (width_point.y() - start.y()) * normal_y
            offset_x = normal_x * width
            offset_y = normal_y * width
            return [
                start,
                end,
                QgsPointXY(end.x() + offset_x, end.y() + offset_y),
                QgsPointXY(start.x() + offset_x, start.y() + offset_y),
                start,
            ]
        if self.mode == "circle":
            if len(controls) < 2:
                return controls
            center, edge = controls[0], controls[1]
            radius = math.hypot(edge.x() - center.x(), edge.y() - center.y())
            if radius == 0.0:
                return [center]
            return [
                QgsPointXY(
                    center.x() + radius * math.cos(2.0 * math.pi * i / 72.0),
                    center.y() + radius * math.sin(2.0 * math.pi * i / 72.0),
                )
                for i in range(72)
            ] + [QgsPointXY(center.x() + radius, center.y())]
        if self.mode == "ellipse":
            if len(controls) < 2:
                return controls
            center, axis = controls[0], controls[1]
            axis_x = axis.x() - center.x()
            axis_y = axis.y() - center.y()
            major = math.hypot(axis_x, axis_y)
            if len(controls) >= 3:
                minor_point = controls[2]
                normal_x = -axis_y / major if major else 0.0
                normal_y = axis_x / major if major else 0.0
                minor = abs((minor_point.x() - center.x()) * normal_x + (minor_point.y() - center.y()) * normal_y)
            else:
                minor = major
            angle = math.atan2(axis_y, axis_x)
            ellipse_points = [
                QgsPointXY(
                    center.x() + major * math.cos(t) * math.cos(angle) - minor * math.sin(t) * math.sin(angle),
                    center.y() + major * math.cos(t) * math.sin(angle) + minor * math.sin(t) * math.cos(angle),
                )
                for t in (2.0 * math.pi * i / 72.0 for i in range(72))
            ]
            return ellipse_points + [ellipse_points[0]]
        if self.mode == "arc":
            if len(controls) < 3:
                return controls
            start, through, end = controls[:3]
            denominator = 2.0 * ((start.x() - through.x()) * (through.y() - end.y()) + (through.x() - end.x()) * (end.y() - start.y()))
            if abs(denominator) < 1e-12:
                return controls
            start_sq = start.x() ** 2 + start.y() ** 2
            through_sq = through.x() ** 2 + through.y() ** 2
            end_sq = end.x() ** 2 + end.y() ** 2
            center_x = (start_sq * (through.y() - end.y()) + through_sq * (end.y() - start.y()) + end_sq * (start.y() - through.y())) / denominator
            center_y = (start_sq * (end.x() - through.x()) + through_sq * (start.x() - end.x()) + end_sq * (through.x() - start.x())) / denominator
            center = QgsPointXY(center_x, center_y)
            angles = [math.atan2(point.y() - center.y(), point.x() - center.x()) for point in (start, through, end)]
            start_angle, through_angle, end_angle = angles
            ccw_span = (end_angle - start_angle) % (2.0 * math.pi)
            through_span = (through_angle - start_angle) % (2.0 * math.pi)
            if through_span <= ccw_span:
                span = ccw_span
            else:
                span = ccw_span - 2.0 * math.pi
            return [
                QgsPointXY(
                    center.x() + math.hypot(start.x() - center.x(), start.y() - center.y()) * math.cos(start_angle + span * i / 48.0),
                    center.y() + math.hypot(start.x() - center.x(), start.y() - center.y()) * math.sin(start_angle + span * i / 48.0),
                )
                for i in range(49)
            ]
        return controls

    def _shape_is_complete(self):
        return {
            "circle": len(self.points) >= 2,
            "ellipse": len(self.points) >= 3,
            "arc": len(self.points) >= 3,
            "rectangle": len(self.points) >= 3,
            "regular_polygon": len(self.points) >= 2,
        }.get(self.mode, False)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            shift_pressed = bool(event.modifiers() & Qt.ShiftModifier)
            point = self._constrained_point(
                self._map_point(event.pos(), allow_snap=not shift_pressed), shift_pressed
            )
            required_controls = self._required_control_count()
            if required_controls is None or len(self.points) < required_controls:
                self.points.append(point)
                self._refresh_rubber_band()
        elif event.button() == Qt.RightButton:
            self._finish()

    def _self_snap_point(self, screen_pos):
        """普通绘制时，将光标吸附到当前要素的已有顶点或预览线。"""
        if not self.points:
            return None

        snap_tolerance = 12.0
        tolerance_sq = snap_tolerance * snap_tolerance
        cursor_x = float(screen_pos.x())
        cursor_y = float(screen_pos.y())
        best_screen = None
        best_point = None
        best_type = None
        best_distance_sq = tolerance_sq

        def consider_vertex(point):
            nonlocal best_screen, best_point, best_type, best_distance_sq
            canvas_point = self.toCanvasCoordinates(point)
            dx = float(canvas_point.x()) - cursor_x
            dy = float(canvas_point.y()) - cursor_y
            distance_sq = dx * dx + dy * dy
            if distance_sq <= best_distance_sq:
                best_screen = canvas_point
                best_point = QgsPointXY(point)
                best_type = QgsPointLocator.Vertex
                best_distance_sq = distance_sq

        for point in self.points:
            consider_vertex(point)

        segments = list(zip(self.points, self.points[1:]))
        if self.layer.geometryType() == 2 and len(self.points) >= 3:
            segments.append((self.points[-1], self.points[0]))
        for start, end in segments:
            start_screen = self.toCanvasCoordinates(start)
            end_screen = self.toCanvasCoordinates(end)
            segment_x = float(end_screen.x()) - float(start_screen.x())
            segment_y = float(end_screen.y()) - float(start_screen.y())
            segment_length_sq = segment_x * segment_x + segment_y * segment_y
            if segment_length_sq == 0.0:
                continue
            factor = (
                (cursor_x - float(start_screen.x())) * segment_x
                + (cursor_y - float(start_screen.y())) * segment_y
            ) / segment_length_sq
            factor = max(0.0, min(1.0, factor))
            projected_x = float(start_screen.x()) + factor * segment_x
            projected_y = float(start_screen.y()) + factor * segment_y
            dx = projected_x - cursor_x
            dy = projected_y - cursor_y
            distance_sq = dx * dx + dy * dy
            if distance_sq < best_distance_sq:
                best_screen = QPoint(round(projected_x), round(projected_y))
                best_point = self.toMapCoordinates(best_screen)
                best_type = QgsPointLocator.Edge
                best_distance_sq = distance_sq

        if best_screen is None:
            return None
        return best_point, QgsPointLocator.Match(best_type, self.layer, -1, 0.0, best_point)

    def _map_point(self, screen_pos, allow_snap=True):
        if allow_snap:
            self_snap = self._self_snap_point(screen_pos)
            if self_snap is not None:
                point, match = self_snap
                self.snap_indicator.setMatch(match)
                return point
            snapping_config = QgsProject.instance().snappingConfig()
            if snapping_config.enabled():
                match = self.canvas.snappingUtils().snapToMap(screen_pos)
                if match.isValid():
                    self.snap_indicator.setMatch(match)
                    return match.point()
        self.snap_indicator.setMatch(QgsPointLocator.Match())
        return self.toMapCoordinates(screen_pos)

    def _constrained_point(self, point, shift_pressed):
        """Shift 下首段锁定八方向，后续段沿上一段的前向射线延长。"""
        if not shift_pressed or not self.points:
            return point

        anchor = self.points[-1]
        dx = point.x() - anchor.x()
        dy = point.y() - anchor.y()
        if len(self.points) == 1:
            length = math.hypot(dx, dy)
            if length == 0.0:
                return anchor
            angle = math.atan2(dy, dx)
            snapped_angle = round(angle / (math.pi / 4.0)) * math.pi / 4.0
            return QgsPointXY(
                anchor.x() + length * math.cos(snapped_angle),
                anchor.y() + length * math.sin(snapped_angle),
            )

        previous = self.points[-2]
        direction_x = anchor.x() - previous.x()
        direction_y = anchor.y() - previous.y()
        direction_length_sq = direction_x * direction_x + direction_y * direction_y
        if direction_length_sq == 0.0:
            return anchor
        distance = max(0.0, (dx * direction_x + dy * direction_y) / direction_length_sq)
        return QgsPointXY(
            anchor.x() + distance * direction_x,
            anchor.y() + distance * direction_y,
        )

    def _constraint_hint_text(self, raw_point):
        if len(self.points) >= 2:
            return "沿上一段延长"
        anchor = self.points[-1]
        angle = math.degrees(math.atan2(raw_point.y() - anchor.y(), raw_point.x() - anchor.x()))
        snapped_angle = int(round(angle / 45.0) * 45) % 360
        return f"{snapped_angle}°"

    def _show_constraint_hint(self, text, screen_pos):
        self.constraint_hint.setText(text)
        self.constraint_hint.adjustSize()
        self.constraint_hint.move(screen_pos + QPoint(14, 14))
        self.constraint_hint.show()
        self.constraint_hint.raise_()

    def _hide_constraint_hint(self):
        self.constraint_hint.hide()

    def canvasMoveEvent(self, event):
        shift_pressed = bool(event.modifiers() & Qt.ShiftModifier)
        cursor_point = self._map_point(event.pos(), allow_snap=not shift_pressed)
        if self.points:
            if shift_pressed:
                self._show_constraint_hint(self._constraint_hint_text(cursor_point), event.pos())
                cursor_point = self._constrained_point(cursor_point, True)
            else:
                self._hide_constraint_hint()
            self._refresh_rubber_band(cursor_point)
        else:
            self._hide_constraint_hint()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancel()
        elif event.key() == Qt.Key_Backspace:
            if self.points:
                self.points.pop()
                self._refresh_rubber_band()
        else:
            super().keyPressEvent(event)

    def _refresh_rubber_band(self, cursor_point=None):
        active_layer = self.controller.iface.activeLayer()
        if isinstance(active_layer, QgsVectorLayer) and active_layer.isValid() and active_layer is not self.layer:
            self.layer = active_layer
            self.rubber_band.reset(self.layer.geometryType())
            self.rubber_band.setColor(QColor(255, 0, 0, 51 if self.layer.geometryType() == 2 else 255))
        points = self._shape_points(cursor_point)
        self.rubber_band.reset(self.layer.geometryType())
        if self.layer.geometryType() == 0:
            if points:
                self.rubber_band.setToGeometry(QgsGeometry.fromPointXY(points[-1]), self.layer.crs())
        elif self.layer.geometryType() == 1:
            if len(points) >= 2:
                self.rubber_band.setToGeometry(QgsGeometry.fromPolylineXY(points), self.layer.crs())
        elif len(points) >= 2:
            ring = points + [points[0]]
            self.rubber_band.setToGeometry(QgsGeometry.fromPolygonXY([ring]), self.layer.crs())

    def _finish(self):
        self._hide_constraint_hint()
        layer = self.controller.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            return
        geometry_type = layer.geometryType()
        if geometry_type not in (0, 1, 2):
            return
        if layer is not self.layer:
            self.layer = layer
            self.rubber_band.reset(geometry_type)
            self.rubber_band.setColor(QColor(255, 0, 0, 51 if geometry_type == 2 else 255))
        points = self._shape_points()
        minimum_points = 2 if geometry_type == 1 else 3
        if geometry_type == 0:
            if len(points) != 1:
                return
        elif len(points) < minimum_points:
            return
        geometry = {
            0: QgsGeometry.fromPointXY(points[0]),
            1: QgsGeometry.fromPolylineXY(points),
            2: QgsGeometry.fromPolygonXY([points + [points[0]]]),
        }[geometry_type]
        self.controller.finish_add_feature(layer, geometry)
        if not self._cancelled:
            self.points.clear()
            self.rubber_band.reset(self.layer.geometryType())
            self.rubber_band.setVisible(True)

    def pause(self):
        if self._cancelled:
            return
        self._paused = True
        self._hide_constraint_hint()
        self.snap_indicator.setMatch(QgsPointLocator.Match())
        self.rubber_band.setVisible(True)

    def resume(self):
        if self._cancelled:
            return
        self._paused = False
        self.rubber_band.setVisible(True)
        self._refresh_rubber_band()

    def cancel(self):
        if self._cancelled:
            return
        self._cancelled = True
        self._hide_constraint_hint()
        self.points.clear()
        self.snap_indicator.setMatch(QgsPointLocator.Match())
        self.rubber_band.reset(self.layer.geometryType())
        self.rubber_band.hide()
        self.canvas.unsetMapTool(self)
        self.deleteLater()


class NewFeatureDialog(QDialog):
    def __init__(self, controller, layer, feature, parent=None):
        super().__init__(parent or controller.iface.mainWindow())
        self.controller = controller
        self.layer = layer
        self.feature = feature
        self.form = None
        self._preset_attributes = {}
        self.preset_buttons = []
        self.preset_grid = None
        self.setWindowTitle(f"新增要素属性 - {layer.name()}")
        self.setMinimumSize(560, 520)
        saved_size = QSettings().value("LaneBatchUpdate/new_feature_dialog_size")
        if saved_size:
            self.resize(saved_size)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        preset_group = QGroupBox("属性预设", self)
        preset_layout = QVBoxLayout(preset_group)
        self.preset_panel = QWidget(preset_group)
        self.preset_grid = QGridLayout(self.preset_panel)
        self.preset_grid.setContentsMargins(0, 0, 0, 0)
        self.preset_grid.setHorizontalSpacing(6)
        self.preset_grid.setVerticalSpacing(6)
        preset_layout.addWidget(self.preset_panel)
        names = [name for name in self.controller.ordered_preset_names(self.layer, self.controller.preset_names(self.layer)) if name != self.controller.EMPTY_PRESET_NAME]
        for name in names:
            button = PresetButton(name, self.preset_panel)
            button.setMinimumWidth(92)
            button.clicked.connect(lambda checked=False, n=name: self.apply_preset(n))
            button.doubleClicked.connect(lambda n=name: self._apply_preset_and_accept(n))
            self.preset_buttons.append(button)
        if not names:
            self.preset_grid.addWidget(QLabel("当前图层还没有可用预设。"), 0, 0)
        layout.addWidget(preset_group)
        self.form = QgsAttributeForm(self.layer, self.feature, parent=self)
        self.form_scroll = QScrollArea(self)
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setWidget(self.form)
        layout.addWidget(self.form_scroll, 1)
        self._layout_preset_buttons()
        QTimer.singleShot(0, self._layout_preset_buttons)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.preset_grid:
            self._layout_preset_buttons()

    def _layout_preset_buttons(self):
        if not self.preset_buttons:
            return
        available_width = max(1, self.preset_panel.width())
        button_width = max(button.sizeHint().width() for button in self.preset_buttons)
        columns = max(1, (available_width + 6) // (button_width + 6))
        while self.preset_grid.count():
            item = self.preset_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(self.preset_panel)
        for index, button in enumerate(self.preset_buttons):
            self.preset_grid.addWidget(button, index // columns, index % columns)

    def _apply_preset_and_accept(self, name):
        self.apply_preset(name)
        self.accept()

    def apply_preset(self, name):
        try:
            values = self.controller.get_preset(self.layer, name)
            for field_name, raw in values.items():
                index = self.layer.fields().indexFromName(field_name)
                if index >= 0:
                    value = self.controller._convert(self.layer.fields().at(index), raw)
                    # 新要素尚未加入图层，预设值需要直接同步到临时要素。
                    self._preset_attributes[index] = value
                    self.feature.setAttribute(index, value)
                    self.form.changeAttribute(field_name, value)
        except (RuntimeError, ValueError) as exc:
            QMessageBox.warning(self, "加载预设失败", str(exc))

    def accept(self):
        # 将编辑控件的当前值同步回这个尚未加入图层的临时要素。
        if not self.form.save():
            QMessageBox.warning(self, "新增失败", "无法保存属性表单中的修改。")
            return
        updated_feature = self.form.feature()
        if updated_feature is None:
            QMessageBox.warning(self, "新增失败", "无法读取属性表单中的要素。")
            return
        self.feature.setAttributes(updated_feature.attributes())
        for index, value in self._preset_attributes.items():
            self.feature.setAttribute(index, value)
        if self.layer.addFeature(self.feature):
            QSettings().setValue("LaneBatchUpdate/new_feature_dialog_size", self.size())
            super().accept()
        else:
            QMessageBox.warning(self, "新增失败", f"无法向图层“{self.layer.name()}”添加要素。")

    def reject(self):
        QSettings().setValue("LaneBatchUpdate/new_feature_dialog_size", self.size())
        super().reject()


class AttributeBrushMapTool(QgsMapToolIdentifyFeature):
    """将预设字段写入地图画布中点击的线要素。"""

    def __init__(self, controller, layer, values, preset_name):
        super().__init__(controller.iface.mapCanvas(), layer)
        self.controller = controller
        self.layer = layer
        self.values = values
        self.preset_name = preset_name
        self.featureIdentified.connect(self._apply_to_feature)

    def _apply_to_feature(self, feature):
        try:
            changed = self.controller.apply_to_feature(self.layer, feature.id(), self.values)
        except (RuntimeError, ValueError) as exc:
            QMessageBox.critical(self.controller.iface.mainWindow(), "格式刷失败", str(exc))
            return
        if changed:
            self.layer.triggerRepaint()
            self.controller.iface.messageBar().pushMessage(
                "属性格式刷",
                f"已将预设“{self.preset_name}”应用到要素 {feature.id()}。",
                Qgis.Info,
                duration=4,
            )


class PresetButton(QPushButton):
    doubleClicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            event.buttons() & Qt.LeftButton
            and (event.pos() - self._drag_start).manhattanLength() >= 12
        ):
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(self.text())
            drag.setMimeData(mime)
            drag.exec_(Qt.MoveAction)
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class PresetPanel(QWidget):
    orderChanged = pyqtSignal(list)
    resized = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.buttons = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        source = event.source()
        if not isinstance(source, PresetButton) or source not in self.buttons:
            event.ignore()
            return
        target = self.childAt(event.pos())
        target_index = self.buttons.index(target) if target in self.buttons else len(self.buttons)
        source_index = self.buttons.index(source)
        self.buttons.insert(target_index, self.buttons.pop(source_index))
        self.orderChanged.emit([button.text() for button in self.buttons])
        event.acceptProposedAction()


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

        self.preset_hint_label = QLabel("常用预设（单击加载，双击直接应用，可拖动排序）")
        self.preset_hint_label.setWordWrap(False)
        self.preset_hint_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.preset_hint_label.setFixedHeight(self.preset_hint_label.sizeHint().height())
        layout.addWidget(self.preset_hint_label)
        self.preset_panel = PresetPanel()
        self.preset_panel.orderChanged.connect(self._preset_order_changed)
        self.preset_grid = QGridLayout(self.preset_panel)
        self.preset_grid.setContentsMargins(0, 0, 0, 0)
        self.preset_grid.setHorizontalSpacing(6)
        self.preset_grid.setVerticalSpacing(6)
        self.preset_grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.preset_panel.resized.connect(self._layout_preset_buttons)
        layout.addWidget(self.preset_panel)

        self.name_row_widget = QWidget()
        name_row = QHBoxLayout(self.name_row_widget)
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.addWidget(QLabel("名称"))
        self.name_edit = QLineEdit()
        name_row.addWidget(self.name_edit, 1)
        layout.addWidget(self.name_row_widget)

        self.form_panel = QWidget()
        self.form = QFormLayout(self.form_panel)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.form_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.form_scroll.setMinimumHeight(180)
        self.form_scroll.setMaximumHeight(260)
        self.form_scroll.setWidget(self.form_panel)
        layout.addWidget(self.form_scroll)

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

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.save_button = QPushButton("保存预设")
        self.brush_button = QPushButton("格式刷")
        self.apply_button = QPushButton("应用属性")
        self.apply_button.setDefault(True)
        self.apply_button.setAutoDefault(True)
        self.close_button = QPushButton("关闭")
        for button in (self.save_button, self.brush_button, self.apply_button, self.close_button):
            button.setAutoDefault(False)
        self.save_button.clicked.connect(self._save_preset)
        self.brush_button.clicked.connect(self._start_brush)
        self.apply_button.clicked.connect(self._apply_preset)
        self.close_button.clicked.connect(self.reject)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.apply_button)
        button_row.addWidget(self.brush_button)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

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
        self._reload_presets()
        self.delete_button.setEnabled(False)
        # 默认不选预设，使表单可直接读取、编辑当前选中的一条要素。
        self.preset_combo.setCurrentIndex(-1)
        self._new_preset()

    def _reload_presets(self):
        preset_key = self._preset_key()
        preset_names = []
        if preset_key:
            self.controller.ensure_empty_presets()
            preset_names = self.controller.preset_names(preset_key)

        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(preset_names)
        self.preset_combo.blockSignals(False)

        while self.preset_grid.count():
            item = self.preset_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        preset_names = self.controller.ordered_preset_names(preset_key, preset_names)
        self.preset_panel.buttons = []
        for name in preset_names:
            if name == self.controller.EMPTY_PRESET_NAME:
                continue
            button = PresetButton(name, self.preset_panel)
            button.setMinimumWidth(96)
            button.setMinimumHeight(28)
            button.setToolTip("单击加载预设；双击直接应用；拖动调整位置")
            button.clicked.connect(lambda checked=False, n=name: self._select_preset(n))
            button.doubleClicked.connect(lambda n=name: self._apply_named_preset(n))
            self.preset_panel.buttons.append(button)
        self._layout_preset_buttons()

    def _layout_preset_buttons(self):
        if not self.preset_panel.buttons:
            self.preset_panel.setMinimumHeight(0)
            self.preset_panel.setMaximumHeight(0)
            return
        button_width = max(
            button.sizeHint().width() for button in self.preset_panel.buttons
        )
        available_width = max(self.preset_panel.width(), self.width() - 24)
        columns = max(1, (available_width + 6) // (button_width + 6))
        rows = (len(self.preset_panel.buttons) + columns - 1) // columns
        row_height = max(button.sizeHint().height() for button in self.preset_panel.buttons)
        panel_height = rows * row_height + max(0, rows - 1) * 6
        self.preset_panel.setMinimumHeight(panel_height)
        self.preset_panel.setMaximumHeight(panel_height)
        for index, button in enumerate(self.preset_panel.buttons):
            self.preset_grid.addWidget(button, index // columns, index % columns)
        self.preset_panel.updateGeometry()

    def _preset_order_changed(self, names):
        self._layout_preset_buttons()
        self.controller.save_preset_order(self._preset_key(), names)

    def _select_preset(self, name):
        index = self.preset_combo.findText(name)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)

    def _apply_named_preset(self, name):
        self._select_preset(name)
        self._apply_preset()

    def _clear_fields(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = {}
        self.name_edit.clear()

    def _show_table(self, layer, preserve_scope=False):
        self._clear_fields()
        self.name_row_widget.hide()
        self.form_scroll.hide()
        self.layout().invalidate()
        self.layout().activate()
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
        # 隐藏表格会触发布局重算，切换期间冻结尺寸避免窗口出现跳变。
        previous_size = self.size() if self.attribute_table.isVisible() else None
        previous_minimum = self.minimumSize()
        previous_maximum = self.maximumSize()
        if previous_size is not None:
            self.setUpdatesEnabled(False)
            self.setFixedSize(previous_size)
        try:
            self.attribute_table.hide()
            self.table_filter_bar.hide()
            self.preset_hint_label.show()
            self.preset_panel.show()
            self.name_row_widget.show()
            self.form_scroll.show()
            self.layout().invalidate()
            self.layout().activate()
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
        finally:
            if previous_size is not None:
                self.setMinimumSize(previous_minimum)
                self.setMaximumSize(previous_maximum)
                self.resize(previous_size)
                self.setUpdatesEnabled(True)
                self.update()

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
        self._reload_presets()
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
            self._reload_presets()
            self.delete_button.setEnabled(False)
            self._new_preset()

    def _start_brush(self):
        layer = self._current_layer()
        values = self._values()
        name = self.preset_combo.currentText().strip() or self.name_edit.text().strip()
        if self._is_all_layers():
            QMessageBox.warning(self, "无法启动格式刷", "请先选择一个具体的线图层。")
            return
        if not layer or layer.geometryType() != 1:
            QMessageBox.warning(self, "无法启动格式刷", "当前图层必须是线图层。")
            return
        if not values:
            QMessageBox.warning(self, "无法启动格式刷", "请先选择预设或填写至少一个属性值。")
            return
        self.controller.start_brush(layer, values, name or "直接修改")
        self.close()

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
        self.accept()


class AttributePresetController:
    SETTINGS_KEY = "LaneBatchUpdate/attribute_presets"
    ORDER_SETTINGS_KEY = "LaneBatchUpdate/attribute_preset_order"
    ALL_LAYERS_ID = "__ALL_LAYERS__"
    EMPTY_PRESET_NAME = "空预设"
    LOG_TAG = "车道处理工具"
    BUILTIN_PRESETS = {
        "BOUNDARY": {
            "单虚线": {"COLOR": "0", "TYPE": "1"},
            "双虚线": {"COLOR": "0", "TYPE": "2"},
            "单实线": {"COLOR": "0", "TYPE": "3"},
            "双实线": {"COLOR": "0", "TYPE": "4"},
            "左虚右实": {"COLOR": "0", "TYPE": "5"},
            "左实右虚": {"COLOR": "0", "TYPE": "6"},
            "95": {"COLOR": "95", "TYPE": "11", "LAYER_NUM": "2"},
            "0": {"COLOR": "0", "TYPE": "11", "LAYER_NUM": "2"},
            "防护栏": {"COLOR": "95", "TYPE": "8"},
            "马路牙": {"COLOR": "15", "TYPE": "7"},
            "虚拟线": {"COLOR": "0", "TYPE": "9"},
        },
        "STOPLINE": {
            "红绿灯停止线": {"TYPE": "1"},
            "减速让行": {"TYPE": "2"},
            "停车让行": {"TYPE": "3"},
        },
        "LANE": {
            "社会道路": {"ROAD_TYPE": "2"},
            "园区道路": {"ROAD_TYPE": "1"},
            "室内道路": {"ROAD_TYPE": "3"},
            "直行": {"TURN_TYPE": "1"},
            "右转": {"TURN_TYPE": "2"},
            "左转": {"TURN_TYPE": "3"},
            "掉头": {"TURN_TYPE": "4"},
            "右前": {"TURN_TYPE": "5"},
            "右后": {"TURN_TYPE": "6"},
            "左前": {"TURN_TYPE": "7"},
            "左后": {"TURN_TYPE": "8"},
        },
        "GATE": {
            "道闸杆": {"TYPE": "0"},
        },
        "PROHIBITED_AREA": {
            "绿化带": {"TYPE": "1", "HEIGHT": "95"},
            "站台": {"TYPE": "2", "HEIGHT": "15"},
        },
    }

    def __init__(self, iface, plugin_dir):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.dialog = None
        self.brush_tool = None
        self.add_feature_action = None
        self.add_feature_tool = None
        self.shape_mode = "line"
        self.shape_combo = None

    def initGui(self, actions):
        global _ACTIVE_CONTROLLER
        _ACTIVE_CONTROLLER = self
        self._remove_previous_form_hooks()
        preset_icon_path = f"{self.plugin_dir}/icon_attribute_preset.svg"
        add_feature_icon_path = f"{self.plugin_dir}/icon_add_feature_preset.svg"
        self.iface.mapCanvas().mapToolSet.connect(self._on_map_tool_set)
        self.shape_combo = QComboBox()
        self.shape_combo.setToolTip("添加要素形状")
        for label, mode in (
            ("普通线", "line"),
            ("圆", "circle"),
            ("椭圆", "ellipse"),
            ("矩形", "rectangle"),
        ):
            self.shape_combo.addItem(label, mode)
        self.shape_combo.currentIndexChanged.connect(self._shape_mode_changed)
        self.iface.addVectorToolBarWidget(self.shape_combo)
        self.add_feature_action = QAction(QIcon(add_feature_icon_path), "添加要素", self.iface.mainWindow())
        self.add_feature_action.setCheckable(True)
        self.add_feature_action.setToolTip("点击开启绘制工具，再点击关闭")
        self.add_feature_action.triggered.connect(self._toggle_add_feature)
        # 不直接添加到工具栏，由主文件根据 toolbar_mode 控制
        # self.iface.addVectorToolBarIcon(self.add_feature_action)
        self.iface.addPluginToVectorMenu("车道处理工具", self.add_feature_action)
        actions.append(self.add_feature_action)

        action = QAction(QIcon(preset_icon_path), "属性预设", self.iface.mainWindow())
        action.setToolTip("保存和应用图层属性预设")
        action.triggered.connect(self.show)
        # 不直接添加到工具栏，由主文件根据 toolbar_mode 控制
        # self.iface.addVectorToolBarIcon(action)
        self.iface.addPluginToVectorMenu("车道处理工具", action)
        actions.append(action)

    def unload(self):
        global _ACTIVE_CONTROLLER
        if _ACTIVE_CONTROLLER is self:
            _ACTIVE_CONTROLLER = None
        try:
            self.iface.mapCanvas().mapToolSet.disconnect(self._on_map_tool_set)
        except (TypeError, RuntimeError):
            pass
        self.stop_add_feature()
        self.stop_brush()
        if self.shape_combo:
            self.shape_combo.deleteLater()
            self.shape_combo = None
        if self.dialog:
            self.dialog.close()
            self.dialog = None

    def _remove_previous_form_hooks(self):
        for layer in self.vector_layers():
            config = layer.editFormConfig()
            if config.initFunction() != "attribute_preset_controller.init_attribute_form":
                continue
            config.setInitFunction("")
            config.setInitCode("")
            layer.setEditFormConfig(config)

    def _on_layers_added(self, layers):
        for layer in layers:
            self._install_form_hook(layer)

    def _install_form_hooks(self):
        for layer in self.vector_layers():
            self._install_form_hook(layer)

    def _install_form_hook(self, layer):
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            return
        if layer.id() in self._connected_layers:
            config = layer.editFormConfig()
            if config.initFunction() == "attribute_preset_controller.init_attribute_form":
                return
        config = layer.editFormConfig()
        if layer.id() not in self._form_originals:
            self._form_originals[layer.id()] = (
                config.initFunction(),
                config.initCode(),
                getattr(config, "initCodeSource", lambda: None)(),
            )
        config.setInitFunction("attribute_preset_controller.init_attribute_form")
        config.setInitCode("")
        layer.setEditFormConfig(config)
        self._connected_layers.add(layer.id())

    def _restore_form_hooks(self):
        for layer_id, original in self._form_originals.items():
            layer = QgsProject.instance().mapLayer(layer_id)
            if not layer:
                continue
            config = layer.editFormConfig()
            if config.initFunction() != "attribute_preset_controller.init_attribute_form":
                continue
            config.setInitFunction(original[0])
            config.setInitCode(original[1])
            if len(original) > 2:
                config.setInitCodeSource(original[2])
            layer.setEditFormConfig(config)
        self._form_originals.clear()
        self._connected_layers.clear()

    def add_form_preset_widget(self, dialog, layer):
        if not isinstance(layer, QgsVectorLayer) or layer.geometryType() not in (0, 1, 2):
            return
        if dialog.findChild(QWidget, "lane_batch_attribute_preset_group"):
            return
        form = dialog.attributeForm() if hasattr(dialog, "attributeForm") else dialog
        if not form or not hasattr(form, "changeAttribute"):
            return
        group = QGroupBox("属性预设", dialog)
        group.setObjectName("lane_batch_attribute_preset_group")
        row = QHBoxLayout(group)
        buttons = []
        names = [
            name for name in self.ordered_preset_names(layer, self.preset_names(layer))
            if name != self.EMPTY_PRESET_NAME
        ]

        def apply_preset(name):
            try:
                values = self.get_preset(layer, name)
                for field_name, raw in values.items():
                    index = layer.fields().indexFromName(field_name)
                    if index >= 0:
                        form.changeAttribute(
                            field_name,
                            self._convert(layer.fields().at(index), raw),
                        )
            except (RuntimeError, ValueError) as exc:
                QMessageBox.warning(dialog, "加载预设失败", str(exc))

        for name in names:
            button = PresetButton(name, group)
            button.setMinimumWidth(92)
            button.setToolTip("单击加载；双击直接应用")
            button.clicked.connect(lambda checked=False, n=name: apply_preset(n))
            button.doubleClicked.connect(lambda n=name: apply_preset(n))
            row.addWidget(button)
            buttons.append(button)
        if not buttons:
            row.addWidget(QLabel("当前图层还没有可用预设。"))
        row.addStretch(1)
        layout = dialog.layout()
        if layout:
            layout.insertWidget(max(0, layout.count() - 1), group)

    def _regular_polygon_sides_changed(self, value):
        return

    def _shape_mode_changed(self, index):
        self.shape_mode = self.shape_combo.itemData(index) if self.shape_combo else "line"
        if self.add_feature_tool and not self.add_feature_tool._cancelled:
            self.add_feature_tool.set_mode(self.shape_mode)

    def _on_map_tool_set(self, tool, _old_tool=None):
        if tool is not self.add_feature_tool and self.add_feature_tool is not None:
            self.add_feature_tool.pause()
            if self.add_feature_action:
                self.add_feature_action.setChecked(False)

    def _resume_add_feature(self):
        if self.add_feature_tool and not self.add_feature_tool._cancelled:
            self.add_feature_tool.resume()
            self.iface.mapCanvas().setMapTool(self.add_feature_tool)
            if self.add_feature_action:
                self.add_feature_action.setChecked(True)
            return True
        return False

    def _toggle_add_feature(self, checked):
        if checked:
            self.add_feature()
        else:
            self._deactivate_add_feature()

    def _deactivate_add_feature(self):
        self.stop_add_feature()
        if self.add_feature_action:
            self.add_feature_action.setChecked(False)

    def add_feature(self):
        if self._resume_add_feature():
            return
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            QMessageBox.warning(self.iface.mainWindow(), "无法添加要素", "请先在图层面板中选择一个矢量图层。")
            return
        if layer.geometryType() not in (0, 1, 2):
            QMessageBox.warning(self.iface.mainWindow(), "无法添加要素", "当前图层几何类型不支持绘制。")
            return
        if not layer.isEditable() and not layer.startEditing():
            QMessageBox.warning(self.iface.mainWindow(), "无法添加要素", f"无法开启图层编辑：{layer.name()}")
            return
        self.stop_add_feature()
        self.add_feature_tool = AddFeatureMapTool(self, layer)
        self.iface.mapCanvas().setMapTool(self.add_feature_tool)
        self.iface.messageBar().pushMessage(
            "添加要素（带属性预设）",
            "左键绘制，右键结束；Shift 显示方向约束；Backspace 删除最后一点；Esc 取消。",
            Qgis.Info,
            duration=6,
        )

    def stop_add_feature(self):
        if self.add_feature_tool:
            tool = self.add_feature_tool
            self.add_feature_tool = None
            tool.cancel()

    def finish_add_feature(self, layer, geometry):
        feature = QgsFeature(layer.fields())
        feature.setGeometry(geometry)
        dialog = NewFeatureDialog(self, layer, feature)
        result = dialog.exec_()
        if result == QDialog.Accepted:
            layer.updateExtents()
            layer.triggerRepaint()

    def show(self):
        if self.dialog is None:
            self.dialog = AttributePresetDialog(self)
        else:
            # 每次打开均以图层面板中当前激活的矢量图层为准。
            self.dialog._reload_layers(prefer_active=True)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def start_brush(self, layer, values, preset_name):
        self.stop_brush()
        self.brush_tool = AttributeBrushMapTool(self, layer, values, preset_name)
        self.iface.mapCanvas().setMapTool(self.brush_tool)
        self.iface.messageBar().pushMessage(
            "属性格式刷",
            f"当前使用预设“{preset_name}”，请点击 {layer.name()} 线要素；按 Esc 结束。",
            Qgis.Info,
            duration=8,
        )

    def stop_brush(self):
        if self.brush_tool is None:
            return
        canvas = self.iface.mapCanvas()
        if canvas.mapTool() is self.brush_tool:
            canvas.unsetMapTool(self.brush_tool)
        self.brush_tool = None

    def _layer_key(self, layer):
        if isinstance(layer, str):
            return layer
        return f"layer-name:{layer.name()}"

    @staticmethod
    def _instance_layer_key(layer):
        return f"layer:{layer.id()}"

    @staticmethod
    def _field_signature(layer):
        return tuple(field.name() for field in layer.fields())

    def _legacy_layer_key(self, layer):
        return f"fields:{self._field_signature(layer)}"

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
        changed = self._migrate_legacy_presets(data)
        for key in keys:
            if self.EMPTY_PRESET_NAME not in data.setdefault(key, {}):
                data[key][self.EMPTY_PRESET_NAME] = {}
                changed = True
        if changed:
            self._write_all(data)

    def _migrate_legacy_presets(self, data):
        """将旧版字段结构键和图层 ID 键迁移为图层名称键。"""
        changed = False
        for layer in self.vector_layers():
            target_key = self._layer_key(layer)
            layer_presets = data.setdefault(target_key, {})
            for source_key in (
                self._legacy_layer_key(layer),
                self._instance_layer_key(layer),
            ):
                source_presets = data.get(source_key)
                if not source_presets:
                    continue
                for name, values in source_presets.items():
                    if name not in layer_presets:
                        layer_presets[name] = values
                        changed = True
                if source_key != target_key:
                    data.pop(source_key, None)
                    changed = True
        obsolete_keys = [
            key for key in data
            if isinstance(key, str)
            and (key.startswith("fields:") or key.startswith("layer:"))
        ]
        for key in obsolete_keys:
            data.pop(key, None)
            changed = True
        return changed

    def _builtin_for(self, layer):
        if isinstance(layer, str):
            return self.BUILTIN_PRESETS.get(layer, {})
        return self.BUILTIN_PRESETS.get(layer.name(), {})

    def preset_names(self, layer):
        self.ensure_empty_presets()
        stored = self._all().get(self._layer_key(layer), {})
        names = set(stored) | set(self._builtin_for(layer))
        return sorted(names, key=lambda name: (name != self.EMPTY_PRESET_NAME, name))

    def ordered_preset_names(self, layer, names):
        raw = QSettings().value(self.ORDER_SETTINGS_KEY, "{}")
        try:
            orders = json.loads(raw or "{}")
        except (TypeError, ValueError):
            orders = {}
        saved = orders.get(self._layer_key(layer), [])
        saved_names = [name for name in saved if name in names]
        return saved_names + [name for name in names if name not in saved_names]

    def save_preset_order(self, layer, names):
        if not layer:
            return
        raw = QSettings().value(self.ORDER_SETTINGS_KEY, "{}")
        try:
            orders = json.loads(raw or "{}")
        except (TypeError, ValueError):
            orders = {}
        orders[self._layer_key(layer)] = list(names)
        QSettings().setValue(self.ORDER_SETTINGS_KEY, json.dumps(orders, ensure_ascii=False))
        QSettings().sync()

    def get_preset(self, layer, name):
        stored = self._all().get(self._layer_key(layer), {})
        if name in stored:
            return stored[name]
        return self._builtin_for(layer).get(name, {})

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
        if raw is None or raw is NULL or (
            isinstance(raw, str) and raw.strip().lower() in ("", "null")
        ):
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

    def apply_to_feature(self, layer, feature_id, values):
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            raise RuntimeError("目标图层不可用。")
        updates = {}
        fields = layer.fields()
        for name, raw in values.items():
            field_index = fields.indexFromName(name)
            if field_index >= 0:
                updates[field_index] = self._convert(fields.at(field_index), raw)
        if not updates:
            raise RuntimeError("预设中的字段在目标图层中不存在。")
        if not layer.isEditable() and not layer.startEditing():
            raise RuntimeError(f"无法开启图层编辑：{layer.name()}")

        layer.beginEditCommand("属性格式刷")
        try:
            for field_index, value in updates.items():
                if not layer.changeAttributeValue(feature_id, field_index, value):
                    field_name = fields.at(field_index).name()
                    raise RuntimeError(f"更新要素失败：{feature_id}，字段：{field_name}")
            layer.endEditCommand()
        except Exception:
            layer.destroyEditCommand()
            raise
        return bool(updates)

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
