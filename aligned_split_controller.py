# -*- coding: utf-8 -*-
"""Native-style split tool with optional aligned batch splitting."""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QCursor, QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointLocator,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand, QgsSnapIndicator


class AlignedSplitMapTool(QgsMapTool):
    """Capture a snapping-aware cutter, or split a line at a snapped vertex."""

    def __init__(self, controller, layer):
        super().__init__(controller.iface.mapCanvas())
        self.controller = controller
        self.layer = layer
        self.canvas = controller.iface.mapCanvas()
        self.points = []
        self.last_match = QgsPointLocator.Match()
        self.snap_indicator = QgsSnapIndicator(self.canvas)
        self.fixed_band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.fixed_band.setColor(QColor(220, 40, 40, 220))
        self.fixed_band.setWidth(2)
        self.preview_band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.preview_band.setColor(QColor(220, 40, 40, 115))
        self.preview_band.setWidth(1)
        self.preview_band.setLineStyle(Qt.DashLine)
        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasPressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._finish(bool(event.modifiers() & Qt.ShiftModifier))
            return
        if event.button() != Qt.LeftButton:
            return
        point = self._map_point(event.pos())
        if not self.points and self._try_split_at_vertex(point):
            return
        if self.points and point.distance(self.points[-1]) <= self._click_tolerance():
            return
        self.points.append(point)
        self.fixed_band.addPoint(point, True)
        self.preview_band.reset(QgsWkbTypes.LineGeometry)

    def canvasMoveEvent(self, event):
        point = self._map_point(event.pos())
        if self.points:
            self._update_preview_segment(point, bool(event.modifiers() & Qt.ShiftModifier))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reset()
            self.controller.iface.messageBar().pushMessage(
                "平齐打断", "已取消当前切割线。", Qgis.Info, duration=3
            )
            return
        if event.key() == Qt.Key_Backspace and self.points:
            self.points.pop()
            self.fixed_band.removeLastPoint()
            self.preview_band.reset(QgsWkbTypes.LineGeometry)
            return
        super().keyPressEvent(event)

    def deactivate(self):
        self._reset()
        super().deactivate()

    def _map_point(self, screen_pos):
        self.last_match = QgsPointLocator.Match()
        if QgsProject.instance().snappingConfig().enabled():
            match = self.canvas.snappingUtils().snapToMap(screen_pos)
            if match.isValid():
                self.last_match = match
                self.snap_indicator.setMatch(match)
                return QgsPointXY(match.point())
        self.snap_indicator.setMatch(self.last_match)
        return self.toMapCoordinates(screen_pos)

    def _try_split_at_vertex(self, point):
        if self.layer.geometryType() != QgsWkbTypes.LineGeometry:
            return False
        if not self.last_match.isValid() or self.last_match.type() != QgsPointLocator.Vertex:
            return False
        try:
            match_layer = self.last_match.layer()
        except AttributeError:
            match_layer = self.layer
        if match_layer is not self.layer:
            return False
        try:
            transform = QgsCoordinateTransform(
                self.canvas.mapSettings().destinationCrs(), self.layer.crs(), QgsProject.instance()
            )
            layer_point = QgsPointXY(transform.transform(point))
        except Exception:
            return False
        return self.controller.split_line_at_vertex(self.layer, self.last_match.featureId(), layer_point)

    def _update_preview_segment(self, cursor_point, aligned):
        self.preview_band.reset(QgsWkbTypes.LineGeometry)
        if aligned:
            ray = self._ray_from_last_segment(cursor_point)
            if ray is not None:
                self.preview_band.addPoint(ray[0], False)
                self.preview_band.addPoint(ray[1], True)
            return
        self.preview_band.addPoint(self.points[-1], False)
        self.preview_band.addPoint(cursor_point, True)

    def _ray_from_last_segment(self, cursor_point):
        return self._extended_ray(self.points[-1], cursor_point)

    def _extended_ray(self, anchor_point, direction_point):
        delta_x = direction_point.x() - anchor_point.x()
        delta_y = direction_point.y() - anchor_point.y()
        if abs(delta_x) <= self._click_tolerance() and abs(delta_y) <= self._click_tolerance():
            return None
        extent = self.canvas.extent()
        span = max(extent.width(), extent.height()) * 2
        length = (delta_x * delta_x + delta_y * delta_y) ** 0.5
        scale = span / length
        return (
            QgsPointXY(anchor_point.x() - delta_x * scale, anchor_point.y() - delta_y * scale),
            QgsPointXY(anchor_point.x() + delta_x * scale, anchor_point.y() + delta_y * scale),
        )

    def _finish(self, aligned):
        cutter_points = self.points
        if aligned and len(self.points) >= 2:
            cutter_points = self._extended_ray(self.points[-2], self.points[-1])
        if cutter_points is not None and len(cutter_points) >= 2:
            self.controller.split_crossed_features(self.layer, cutter_points, aligned)
        else:
            self.controller.iface.messageBar().pushMessage(
                "平齐打断", "至少需要两个点才能完成切割线。", Qgis.Info, duration=3
            )
        self._reset()

    def _reset(self):
        self.points = []
        self.last_match = QgsPointLocator.Match()
        self.snap_indicator.setMatch(self.last_match)
        self.fixed_band.reset(QgsWkbTypes.LineGeometry)
        self.preview_band.reset(QgsWkbTypes.LineGeometry)

    def _click_tolerance(self):
        return self.canvas.mapSettings().mapUnitsPerPixel() * 0.25


class AlignedSplitController:
    """Split the active line or polygon layer using one user-drawn cutter."""

    def __init__(self, iface, plugin_dir):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.action = None
        self.map_tool = None

    def initGui(self, actions_master):
        icon_path = os.path.join(self.plugin_dir, "icon_aligned_split.svg")
        self.action = QAction(QIcon(icon_path), "平齐打断", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip("普通分割；按住 Shift 按最近两点方向使用射线平齐打断")
        self.action.toggled.connect(self._toggle_tool)
        self.iface.mapCanvas().mapToolSet.connect(self._on_map_tool_set)
        self.iface.addPluginToVectorMenu("车道处理工具", self.action)
        actions_master.append(self.action)

    def unload(self):
        if self.action is not None:
            try:
                self.iface.mapCanvas().mapToolSet.disconnect(self._on_map_tool_set)
            except (TypeError, RuntimeError):
                pass
            self.iface.removeVectorToolBarIcon(self.action)
            self.iface.removePluginFromVectorMenu("车道处理工具", self.action)
        self.action = None
        self.map_tool = None

    def _toggle_tool(self, enabled):
        if enabled:
            self.start()
        elif self.iface.mapCanvas().mapTool() is self.map_tool:
            self.iface.mapCanvas().unsetMapTool(self.map_tool)

    def _on_map_tool_set(self, new_tool, old_tool):
        if old_tool is self.map_tool and new_tool is not self.map_tool:
            self.action.setChecked(False)

    def start(self):
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            self._reject_layer("请先激活需要分割的线或面图层。")
            return
        if layer.geometryType() not in (QgsWkbTypes.LineGeometry, QgsWkbTypes.PolygonGeometry):
            self._reject_layer("平齐打断仅支持线图层和面图层。")
            return
        if not layer.isEditable() and not layer.startEditing():
            self._reject_layer(f"无法开启 {layer.name()} 图层编辑。", "无法编辑")
            return
        self.map_tool = AlignedSplitMapTool(self, layer)
        self.iface.mapCanvas().setMapTool(self.map_tool)
        self.iface.messageBar().pushMessage(
            "平齐打断",
            "左键绘制切割线，右键普通分割；按住 Shift 按最近两点方向显示射线并平齐打断；点击吸附线顶点可直接拆线。",
            Qgis.Info,
            duration=10,
        )

    def _reject_layer(self, message, title="图层类型不支持"):
        QMessageBox.warning(self.iface.mainWindow(), title, message)
        self.action.setChecked(False)

    def split_line_at_vertex(self, layer, feature_id, point):
        selected_ids = set(layer.selectedFeatureIds())
        if selected_ids and feature_id not in selected_ids:
            return False
        feature = layer.getFeature(feature_id)
        geometry = feature.geometry()
        if geometry is None or geometry.isEmpty():
            return False
        parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
        tolerance = self._vertex_tolerance(layer)
        for part_index, part in enumerate(parts):
            vertex_index = next(
                (index for index, vertex in enumerate(part) if QgsPointXY(vertex).distance(point) <= tolerance),
                None,
            )
            if vertex_index is None or vertex_index == 0 or vertex_index == len(part) - 1:
                continue
            first_part = [QgsPointXY(vertex) for vertex in part[:vertex_index + 1]]
            second_part = [QgsPointXY(vertex) for vertex in part[vertex_index:]]
            replacement_parts = [[QgsPointXY(vertex) for vertex in item] for item in parts]
            replacement_parts[part_index] = first_part
            replacement = self._line_geometry(replacement_parts)
            new_parts = [self._line_geometry([second_part])]
            self._apply_splits(layer, [(feature, replacement, new_parts)], "从顶点打断线要素")
            return True
        return False

    @staticmethod
    def _line_geometry(parts):
        return QgsGeometry.fromMultiPolylineXY(parts) if len(parts) > 1 else QgsGeometry.fromPolylineXY(parts[0])

    def _vertex_tolerance(self, layer):
        canvas_tolerance = self.iface.mapCanvas().mapSettings().mapUnitsPerPixel() * 8
        transform = QgsCoordinateTransform(
            self.iface.mapCanvas().mapSettings().destinationCrs(), layer.crs(), QgsProject.instance()
        )
        origin = self.iface.mapCanvas().center()
        nearby = QgsPointXY(origin.x() + canvas_tolerance, origin.y())
        return max(1e-12, QgsPointXY(transform.transform(origin)).distance(QgsPointXY(transform.transform(nearby))))

    def split_crossed_features(self, layer, canvas_points, aligned):
        try:
            transform = QgsCoordinateTransform(
                self.iface.mapCanvas().mapSettings().destinationCrs(), layer.crs(), QgsProject.instance()
            )
            cutter_points = [QgsPointXY(transform.transform(point)) for point in canvas_points]
            cutter = QgsGeometry.fromPolylineXY(cutter_points)
        except Exception as exc:
            QMessageBox.warning(self.iface.mainWindow(), "坐标转换失败", str(exc))
            return
        if cutter.isEmpty() or cutter.length() == 0.0:
            return

        selected_ids = set(layer.selectedFeatureIds())
        if selected_ids and not aligned:
            source = (layer.getFeature(feature_id) for feature_id in selected_ids)
            scope = "选中的"
        else:
            source = layer.getFeatures(QgsFeatureRequest().setFilterRect(cutter.boundingBox()))
            scope = "所有相交"
        candidates = self._split_candidates(source, cutter, cutter_points)
        if not candidates:
            self.iface.messageBar().pushMessage("平齐打断", "切割线没有穿过可分割的要素。", Qgis.Warning, duration=5)
            return
        command = "按同一切割线平齐分割要素" if aligned else "分割要素"
        if self._apply_splits(layer, candidates, command):
            self.iface.messageBar().pushMessage(
                "平齐打断", f"已分割 {len(candidates)} 个{scope}要素，可用 Ctrl+Z 一次撤销。", Qgis.Info, duration=7
            )

    @staticmethod
    def _split_candidates(features, cutter, cutter_points):
        candidates = []
        for feature in features:
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty() or not geometry.intersects(cutter):
                continue
            first_part = QgsGeometry(geometry)
            result, new_parts, _ = first_part.splitGeometry(cutter_points, False)
            if int(result) == 0 and new_parts:
                candidates.append((feature, first_part, new_parts))
        return candidates

    def _apply_splits(self, layer, candidates, command):
        layer.beginEditCommand(command)
        try:
            for feature, first_part, new_parts in candidates:
                if not layer.changeGeometry(feature.id(), first_part):
                    raise RuntimeError(f"无法更新要素 {feature.id()} 的第一段几何。")
                for part in new_parts:
                    new_feature = QgsFeature(layer.fields())
                    new_feature.setAttributes(feature.attributes())
                    new_feature.setGeometry(part)
                    if not layer.addFeature(new_feature):
                        raise RuntimeError(f"无法新增要素 {feature.id()} 的分割段。")
            layer.endEditCommand()
        except Exception as exc:
            layer.destroyEditCommand()
            QMessageBox.critical(self.iface.mainWindow(), "分割失败", str(exc))
            return False
        layer.triggerRepaint()
        self.iface.mapCanvas().refresh()
        return True
