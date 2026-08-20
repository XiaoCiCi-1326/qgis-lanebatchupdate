# -*- coding: utf-8 -*-
"""将选中的 LANE 端点吸附到最近 STOPLINE，并截断越过停止线的部分。"""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import QEvent, QObject, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QInputDialog, QMessageBox
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)


class LaneStoplineSnapController(QObject):
    """每条选中 LANE 仅处理距离 STOPLINE 最近的一个端点。"""

    def __init__(self, iface, plugin_dir):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.action = None
        self.settings = QSettings()
        self.distance_key = "LaneBatchUpdate/laneStoplineSnapDistance"
        self.distance_limit = self._load_distance_limit()

    def _load_distance_limit(self):
        try:
            return max(0.0, float(self.settings.value(self.distance_key, 10.0)))
        except (TypeError, ValueError):
            return 10.0

    def _set_distance_limit(self):
        value, accepted = QInputDialog.getDouble(
            self.iface.mainWindow(), "设置 STOPLINE 吸附范围", "附近范围（米）",
            self.distance_limit, 0.0, 1e9, 2
        )
        if accepted:
            self.distance_limit = value
            self.settings.setValue(self.distance_key, value)
            self.iface.messageBar().pushMessage(
                "车道工具", f"STOPLINE 吸附范围已设置为 {value:g} 米。", Qgis.Info, duration=4
            )

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonDblClick:
            self._set_distance_limit()
            return True
        return False

    def initGui(self, actions_master):
        icon_path = os.path.join(self.plugin_dir, "icon_lane_stopline_snap.svg")
        self.action = QAction(QIcon(icon_path), "LANE 吸附 STOPLINE", self.iface.mainWindow())
        self.action.setToolTip(
            "将选中 LANE 的最近端点吸附到最近 STOPLINE；端点越过 STOPLINE 时截断越界部分"
        )
        self.action.triggered.connect(self.snap_selected)
        self.iface.addVectorToolBarIcon(self.action)
        toolbar = self.iface.vectorToolBar()
        button = toolbar.widgetForAction(self.action) if toolbar is not None else None
        if button is not None:
            button.installEventFilter(self)
        self.iface.addPluginToVectorMenu("车道处理工具", self.action)
        actions_master.append(self.action)

    def unload(self):
        if self.action is not None:
            toolbar = self.iface.vectorToolBar()
            button = toolbar.widgetForAction(self.action) if toolbar is not None else None
            if button is not None:
                button.removeEventFilter(self)
            self.iface.removeVectorToolBarIcon(self.action)
            self.iface.removePluginFromVectorMenu("车道处理工具", self.action)
        self.action = None

    @staticmethod
    def _layer_by_name(name):
        return next(
            (
                layer
                for layer in QgsProject.instance().mapLayers().values()
                if isinstance(layer, QgsVectorLayer) and layer.name().upper() == name
            ),
            None,
        )

    @staticmethod
    def _distance_sq(first, second):
        return (first.x() - second.x()) ** 2 + (first.y() - second.y()) ** 2

    @staticmethod
    def _intersection_points(geometry):
        if geometry is None or geometry.isEmpty() or geometry.type() != QgsWkbTypes.PointGeometry:
            return []
        return [QgsPointXY(point) for point in geometry.vertices()]

    def _stopline_geometries(self, lane_layer):
        stopline_layer = self._layer_by_name("STOPLINE")
        if not isinstance(stopline_layer, QgsVectorLayer):
            return None, "请先加载 STOPLINE 图层。"
        if stopline_layer.geometryType() != QgsWkbTypes.LineGeometry:
            return None, "STOPLINE 必须是线图层。"

        transform = None
        if stopline_layer.crs() != lane_layer.crs():
            transform = QgsCoordinateTransform(
                stopline_layer.crs(), lane_layer.crs(), QgsProject.instance()
            )
        geometries = []
        for feature in stopline_layer.getFeatures():
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue
            geometry = QgsGeometry(geometry)
            if transform is not None:
                geometry.transform(transform)
            geometries.append(geometry)
        if not geometries:
            return None, "STOPLINE 没有有效的线要素。"
        return geometries, None

    def _nearest_stopline(self, endpoint, stopline_geometries):
        endpoint_geometry = QgsGeometry.fromPointXY(endpoint)
        best_geometry = None
        best_point = None
        best_distance_sq = float("inf")
        for stopline_geometry in stopline_geometries:
            nearest_geometry = stopline_geometry.nearestPoint(endpoint_geometry)
            if nearest_geometry is None or nearest_geometry.isEmpty():
                continue
            point = QgsPointXY(nearest_geometry.asPoint())
            distance_sq = self._distance_sq(endpoint, point)
            if distance_sq < best_distance_sq:
                best_geometry = stopline_geometry
                best_point = point
                best_distance_sq = distance_sq
        return best_geometry, best_point, best_distance_sq

    @staticmethod
    def _crossing_position(lane_geometry, stopline_geometry, endpoint_index, tolerance):
        intersections = lane_geometry.intersection(stopline_geometry)
        positions = []
        for point in LaneStoplineSnapController._intersection_points(intersections):
            position = lane_geometry.lineLocatePoint(QgsGeometry.fromPointXY(point))
            if position >= 0:
                positions.append(position)
        if not positions:
            return None
        line_length = lane_geometry.length()
        candidates = [
            position
            for position in positions
            if tolerance < position < line_length - tolerance
        ]
        if not candidates:
            return None
        return min(candidates) if endpoint_index == 0 else max(candidates)

    @staticmethod
    def _truncated_geometry(lane_geometry, crossing_position, endpoint_index, tolerance):
        vertices = [QgsPointXY(point) for point in lane_geometry.vertices()]
        if len(vertices) < 2:
            return None
        travelled = 0.0
        for index, (start, end) in enumerate(zip(vertices, vertices[1:])):
            segment_length = start.distance(end)
            if segment_length <= tolerance:
                continue
            if travelled + segment_length + tolerance < crossing_position:
                travelled += segment_length
                continue
            ratio = max(0.0, min(1.0, (crossing_position - travelled) / segment_length))
            crossing_point = QgsPointXY(
                start.x() + (end.x() - start.x()) * ratio,
                start.y() + (end.y() - start.y()) * ratio,
            )
            if endpoint_index == 0:
                retained = [crossing_point] + vertices[index + 1:]
            else:
                retained = vertices[:index + 1] + [crossing_point]
            result = QgsGeometry.fromPolylineXY(retained)
            if result.isEmpty() or result.length() <= tolerance:
                return None
            return result
        return None

    def snap_selected(self):
        lane_layer = self.iface.activeLayer()
        if not isinstance(lane_layer, QgsVectorLayer) or lane_layer.name().upper() != "LANE":
            QMessageBox.warning(self.iface.mainWindow(), "目标图层不正确", "请先激活线类型 LANE 图层。")
            return
        if lane_layer.geometryType() != QgsWkbTypes.LineGeometry:
            QMessageBox.warning(self.iface.mainWindow(), "几何类型不支持", "LANE 必须是线图层。")
            return

        selected_ids = lane_layer.selectedFeatureIds()
        if not selected_ids:
            QMessageBox.information(self.iface.mainWindow(), "没有选中要素", "请先选中需要吸附的 LANE 要素。")
            return
        stopline_geometries, error = self._stopline_geometries(lane_layer)
        if error:
            QMessageBox.warning(self.iface.mainWindow(), "STOPLINE 不可用", error)
            return
        if not lane_layer.isEditable() and not lane_layer.startEditing():
            QMessageBox.warning(self.iface.mainWindow(), "无法编辑", f"无法开启 {lane_layer.name()} 图层编辑。")
            return

        tolerance = self.iface.mapCanvas().mapSettings().mapUnitsPerPixel() * 0.01
        snapped = 0
        truncated = 0
        lane_layer.beginEditCommand("LANE 吸附 STOPLINE")
        try:
            for feature_id in selected_ids:
                feature = lane_layer.getFeature(feature_id)
                geometry = feature.geometry()
                if not feature.isValid() or geometry is None or geometry.isEmpty():
                    continue
                vertices = list(geometry.vertices())
                if len(vertices) < 2 or geometry.length() <= tolerance:
                    continue

                candidates = []
                for endpoint_index in (0, len(vertices) - 1):
                    endpoint = QgsPointXY(vertices[endpoint_index])
                    stopline_geometry, point, distance_sq = self._nearest_stopline(
                        endpoint, stopline_geometries
                    )
                    if stopline_geometry is not None and distance_sq <= self.distance_limit * self.distance_limit:
                        candidates.append((distance_sq, endpoint_index, point, stopline_geometry))
                if not candidates:
                    continue
                _, endpoint_index, target_point, stopline_geometry = min(
                    candidates, key=lambda item: item[0]
                )

                crossing_position = self._crossing_position(
                    geometry, stopline_geometry, endpoint_index, tolerance
                )
                if crossing_position is not None:
                    new_geometry = self._truncated_geometry(
                        geometry, crossing_position, endpoint_index, tolerance
                    )
                    if new_geometry is not None and lane_layer.changeGeometry(feature_id, new_geometry):
                        truncated += 1
                    continue

                endpoint = QgsPointXY(vertices[endpoint_index])
                if self._distance_sq(endpoint, target_point) <= tolerance * tolerance:
                    continue
                new_geometry = QgsGeometry(geometry)
                if new_geometry.moveVertex(target_point.x(), target_point.y(), endpoint_index) and lane_layer.changeGeometry(feature_id, new_geometry):
                    snapped += 1
            lane_layer.endEditCommand()
        except Exception:
            lane_layer.destroyEditCommand()
            raise

        if snapped or truncated:
            lane_layer.triggerRepaint()
            self.iface.mapCanvas().refresh()
            self.iface.messageBar().pushMessage(
                "车道工具",
                f"已吸附 {snapped} 条 LANE，截断越过 STOPLINE 的 {truncated} 条；修改已进入编辑会话，可撤销。",
                Qgis.Info,
                duration=8,
            )
        else:
            self.iface.messageBar().pushMessage(
                "车道工具", f"附近 {self.distance_limit:g} 米内没有可以吸附的 STOPLINE。", Qgis.Warning, duration=6
            )
