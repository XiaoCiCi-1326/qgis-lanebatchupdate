# -*- coding: utf-8 -*-
"""将选中的 LANE/BOUNDARY 线要素约束到 MAP_TILE 范围。"""
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
)


class MapTileSnapController(QObject):
    """只处理当前激活图层中选中的线要素。"""

    def __init__(self, iface, plugin_dir):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.action = None
        self.settings = QSettings()
        self.distance_key = "LaneBatchUpdate/mapTileSnapDistance"
        self.distance_limit = self._load_distance_limit()

    def _load_distance_limit(self):
        try:
            return max(0.0, float(self.settings.value(self.distance_key, 10.0)))
        except (TypeError, ValueError):
            return 10.0

    def _set_distance_limit(self):
        value, accepted = QInputDialog.getDouble(
            self.iface.mainWindow(), "设置 MAP_TILE 吸附范围", "附近范围（米）",
            self.distance_limit, 0.0, 1e9, 2
        )
        if accepted:
            self.distance_limit = value
            self.settings.setValue(self.distance_key, value)
            self.iface.messageBar().pushMessage(
                "车道工具", f"MAP_TILE 吸附范围已设置为 {value:g} 米。", Qgis.Info, duration=4
            )

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonDblClick:
            self._set_distance_limit()
            return True
        return False

    def initGui(self, actions_master):
        icon_path = os.path.join(self.plugin_dir, "icon_map_tile_snap.svg")
        self.action = QAction(QIcon(icon_path), "吸附到范围框", self.iface.mainWindow())
        self.action.setToolTip(
            "将每个选中 LANE/BOUNDARY 的最近端点吸附到 MAP_TILE 边界"
        )
        self.action.triggered.connect(self.snap_selected)
        # 不直接添加到工具栏，由主文件根据 toolbar_mode 控制
        # self.iface.addVectorToolBarIcon(self.action)
        toolbar = self.iface.vectorToolBar()
        button = None  # toolbar.widgetForAction(self.action) if toolbar is not None else None
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
        layers = QgsProject.instance().mapLayersByName(name)
        return layers[0] if layers else None

    def _tile_geometry(self, target_layer):
        tile_layer = self._layer_by_name("MAP_TILE")
        if not isinstance(tile_layer, QgsVectorLayer):
            return None, "请先加载 MAP_TILE 图层。"
        if tile_layer.geometryType() != 2:
            return None, "MAP_TILE 必须是面图层。"

        geometries = [feature.geometry() for feature in tile_layer.getFeatures()]
        geometries = [geometry for geometry in geometries if geometry and not geometry.isEmpty()]
        if not geometries:
            return None, "MAP_TILE 没有有效的范围面。"
        tile_geometry = QgsGeometry.unaryUnion(geometries)
        if tile_geometry.isEmpty():
            return None, "无法读取 MAP_TILE 的范围。"

        if tile_layer.crs() != target_layer.crs():
            transform = QgsCoordinateTransform(
                tile_layer.crs(), target_layer.crs(), QgsProject.instance()
            )
            tile_geometry.transform(transform)
        return tile_geometry, None

    @staticmethod
    def _tile_boundary(tile_geometry):
        """返回 Polygon/MultiPolygon 的边界坐标环，避免使用新版本专有 API。"""
        rings = []
        if tile_geometry.isMultipart():
            polygons = tile_geometry.asMultiPolygon()
            for polygon in polygons:
                rings.extend(polygon)
        else:
            rings.extend(tile_geometry.asPolygon())
        return [
            [QgsPointXY(point) for point in ring]
            for ring in rings
            if len(ring) >= 2
        ]

    @staticmethod
    def _nearest_on_boundary(point, rings):
        """计算点到所有边界线段的最近投影点和距离平方。"""
        best_point = None
        best_distance_sq = float("inf")
        px, py = point.x(), point.y()
        for ring in rings:
            segments = zip(ring, ring[1:])
            if ring[0] != ring[-1]:
                segments = list(segments) + [(ring[-1], ring[0])]
            for start, end in segments:
                ax, ay = start.x(), start.y()
                bx, by = end.x(), end.y()
                dx, dy = bx - ax, by - ay
                length_sq = dx * dx + dy * dy
                if length_sq <= 0.0:
                    candidate = start
                else:
                    ratio = ((px - ax) * dx + (py - ay) * dy) / length_sq
                    ratio = max(0.0, min(1.0, ratio))
                    candidate = QgsPointXY(ax + ratio * dx, ay + ratio * dy)
                distance_sq = (px - candidate.x()) ** 2 + (py - candidate.y()) ** 2
                if distance_sq < best_distance_sq:
                    best_distance_sq = distance_sq
                    best_point = candidate
        return best_point, best_distance_sq

    @staticmethod
    def _crossing_position(line_geometry, boundary_geometry, endpoint_index, tolerance):
        intersections = line_geometry.intersection(boundary_geometry)
        if intersections is None or intersections.isEmpty():
            return None
        positions = []
        for point in intersections.vertices():
            position = line_geometry.lineLocatePoint(QgsGeometry.fromPointXY(QgsPointXY(point)))
            if position >= 0:
                positions.append(position)
        if not positions:
            return None
        length = line_geometry.length()
        positions = [p for p in positions if tolerance < p < length - tolerance]
        if not positions:
            return None
        return min(positions) if endpoint_index == 0 else max(positions)

    @staticmethod
    def _truncated_geometry(line_geometry, crossing_position, endpoint_index, tolerance):
        vertices = [QgsPointXY(point) for point in line_geometry.vertices()]
        travelled = 0.0
        for index, (start, end) in enumerate(zip(vertices, vertices[1:])):
            segment_length = start.distance(end)
            if segment_length <= tolerance:
                continue
            if travelled + segment_length + tolerance < crossing_position:
                travelled += segment_length
                continue
            ratio = max(0.0, min(1.0, (crossing_position - travelled) / segment_length))
            crossing = QgsPointXY(
                start.x() + (end.x() - start.x()) * ratio,
                start.y() + (end.y() - start.y()) * ratio,
            )
            retained = ([crossing] + vertices[index + 1:]) if endpoint_index == 0 else (vertices[:index + 1] + [crossing])
            result = QgsGeometry.fromPolylineXY(retained)
            return result if not result.isEmpty() and result.length() > tolerance else None
        return None

    def snap_selected(self):
        target_layer = self.iface.activeLayer()
        if not isinstance(target_layer, QgsVectorLayer):
            QMessageBox.warning(self.iface.mainWindow(), "图层类型不支持", "请先激活 LANE 或 BOUNDARY 图层。")
            return
        if target_layer.name().upper() not in ("LANE", "BOUNDARY"):
            QMessageBox.warning(self.iface.mainWindow(), "目标图层不正确", "当前激活图层必须是 LANE 或 BOUNDARY。")
            return
        if target_layer.geometryType() != 1:
            QMessageBox.warning(self.iface.mainWindow(), "几何类型不支持", "LANE 或 BOUNDARY 必须是线图层。")
            return

        selected_ids = target_layer.selectedFeatureIds()
        if not selected_ids:
            QMessageBox.information(self.iface.mainWindow(), "没有选中要素", "请先选中需要吸附的线要素。")
            return

        tile_geometry, error = self._tile_geometry(target_layer)
        if error:
            QMessageBox.warning(self.iface.mainWindow(), "MAP_TILE 不可用", error)
            return

        boundary_rings = self._tile_boundary(tile_geometry)
        if not boundary_rings:
            QMessageBox.warning(self.iface.mainWindow(), "范围框无效", "MAP_TILE 没有可用的边界线。")
            return

        canvas = self.iface.mapCanvas()
        tolerance = canvas.mapSettings().mapUnitsPerPixel() * 0.01
        distance_limit_sq = self.distance_limit * self.distance_limit
        boundary_geometry = QgsGeometry.unaryUnion(
            [QgsGeometry.fromPolylineXY(ring) for ring in boundary_rings]
        )
        if boundary_geometry.isEmpty():
            QMessageBox.warning(self.iface.mainWindow(), "范围框无效", "无法构造 MAP_TILE 边界线。")
            return
        if not target_layer.isEditable() and not target_layer.startEditing():
            QMessageBox.warning(self.iface.mainWindow(), "无法编辑", f"无法开启 {target_layer.name()} 图层编辑。")
            return

        changed = 0
        vertices_changed = 0
        target_layer.beginEditCommand("选中要素吸附到 MAP_TILE")
        try:
            for feature_id in selected_ids:
                feature = target_layer.getFeature(feature_id)
                geometry = feature.geometry()
                if not feature.isValid() or geometry.isEmpty():
                    continue
                new_geometry = QgsGeometry(geometry)
                vertices = list(geometry.vertices())
                if len(vertices) < 2:
                    continue
                # 最外侧顶点指当前线的两个端点；不论端点位于 MAP_TILE 内外。
                endpoint_indexes = (0, len(vertices) - 1)
                nearest_vertex_index = -1
                nearest_distance_sq = float("inf")
                nearest_point = None
                for vertex_index in endpoint_indexes:
                    point, distance_sq = self._nearest_on_boundary(
                        QgsPointXY(vertices[vertex_index]), boundary_rings
                    )
                    if distance_sq < nearest_distance_sq:
                        nearest_distance_sq = distance_sq
                        nearest_vertex_index = vertex_index
                        nearest_point = point
                # 只处理最近端点在配置范围内的要素，避免远距离误吸附。
                if nearest_vertex_index < 0 or nearest_point is None or nearest_distance_sq > distance_limit_sq:
                    continue
                crossing_position = self._crossing_position(
                    geometry, boundary_geometry, nearest_vertex_index, tolerance
                )
                if crossing_position is not None:
                    new_geometry = self._truncated_geometry(
                        geometry, crossing_position, nearest_vertex_index, tolerance
                    )
                    if new_geometry is not None and target_layer.changeGeometry(feature_id, new_geometry):
                        changed += 1
                        vertices_changed += 1
                    continue
                feature_changed = (
                    nearest_distance_sq > tolerance * tolerance
                    and new_geometry.moveVertex(
                        nearest_point.x(), nearest_point.y(), nearest_vertex_index
                    )
                )
                if feature_changed and target_layer.changeGeometry(feature_id, new_geometry):
                    changed += 1
                    vertices_changed += 1
            target_layer.endEditCommand()
        except Exception:
            target_layer.destroyEditCommand()
            raise

        if changed:
            target_layer.triggerRepaint()
            canvas.refresh()
            self.iface.messageBar().pushMessage(
                "车道工具",
                f"已处理 {changed} 个选中要素，吸附/截断 {vertices_changed} 个；范围 {self.distance_limit:g} 米，修改已进入编辑会话，可撤销。",
                level=Qgis.Info,
                duration=6,
            )
        else:
            self.iface.messageBar().pushMessage(
                "车道工具", f"附近 {self.distance_limit:g} 米内没有可以吸附的 MAP_TILE 边界。", level=Qgis.Warning, duration=6
            )
