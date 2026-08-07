# -*- coding: utf-8 -*-
"""将当前选中的 LANE/BOUNDARY 端点接到另一份同类线数据。"""
from __future__ import annotations

import os
import re

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)


class LaneBoundaryJoinController:
    """只移动当前激活图层中选中线要素的两个端点。"""

    def __init__(self, iface, plugin_dir):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self.action = None

    def initGui(self, actions_master):
        icon_path = os.path.join(self.plugin_dir, "icon_lane_boundary_join.svg")
        self.action = QAction(QIcon(icon_path), "LANE/BOUNDARY 接边", self.iface.mainWindow())
        self.action.setToolTip(
            "将选中线两个端点中距离另一份数据最近的一个端点吸附到目标端点"
        )
        self.action.triggered.connect(self.join_selected)
        self.iface.addVectorToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu("车道处理工具", self.action)
        actions_master.append(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removeVectorToolBarIcon(self.action)
            self.iface.removePluginFromVectorMenu("车道处理工具", self.action)
        self.action = None

    @staticmethod
    def _base_layer_name(layer_name):
        match = re.match(r"^(LANE|BOUNDARY)(?:[_ -].*)?$", layer_name.upper())
        return match.group(1) if match else ""

    @classmethod
    def _other_line_layers(cls, source_layer):
        base_name = cls._base_layer_name(source_layer.name())
        return [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer)
            and layer.id() != source_layer.id()
            and layer.geometryType() == 1
            and cls._base_layer_name(layer.name()) == base_name
        ]

    @staticmethod
    def _endpoints(geometry):
        if not geometry or geometry.isEmpty():
            return []
        vertices = list(geometry.vertices())
        if len(vertices) < 2:
            return []
        return [QgsPointXY(vertices[0]), QgsPointXY(vertices[-1])]

    @staticmethod
    def _distance_sq(first, second):
        return (first.x() - second.x()) ** 2 + (first.y() - second.y()) ** 2

    def _target_endpoints(self, source_layer, target_layers):
        endpoints = []
        for target_layer in target_layers:
            transform = None
            if target_layer.crs() != source_layer.crs():
                transform = QgsCoordinateTransform(
                    target_layer.crs(), source_layer.crs(), QgsProject.instance()
                )
            for feature in target_layer.getFeatures():
                geometry = QgsGeometry(feature.geometry())
                if geometry.isEmpty():
                    continue
                if transform is not None:
                    geometry.transform(transform)
                endpoints.extend(self._endpoints(geometry))
        return endpoints

    def join_selected(self):
        source_layer = self.iface.activeLayer()
        if not isinstance(source_layer, QgsVectorLayer):
            QMessageBox.warning(self.iface.mainWindow(), "图层类型不支持", "请先激活 LANE 或 BOUNDARY 图层。")
            return
        if not self._base_layer_name(source_layer.name()):
            QMessageBox.warning(
                self.iface.mainWindow(),
                "目标图层不正确",
                "当前激活图层必须是 LANE 或 BOUNDARY（允许带 _1 等副本后缀）。",
            )
            return
        if source_layer.geometryType() != 1:
            QMessageBox.warning(self.iface.mainWindow(), "几何类型不支持", "LANE 或 BOUNDARY 必须是线图层。")
            return

        selected_ids = source_layer.selectedFeatureIds()
        if not selected_ids:
            QMessageBox.information(self.iface.mainWindow(), "没有选中要素", "请先选中需要接边的线要素。")
            return

        target_layers = self._other_line_layers(source_layer)
        if not target_layers:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "缺少另一份数据",
                f"请再加载一份名称为 {source_layer.name()} 的线图层作为接边目标。",
            )
            return
        target_endpoints = self._target_endpoints(source_layer, target_layers)
        if not target_endpoints:
            QMessageBox.warning(self.iface.mainWindow(), "目标数据无效", "另一份线图层没有可用的两个端点。")
            return

        canvas = self.iface.mapCanvas()
        tolerance = canvas.mapSettings().mapUnitsPerPixel() * 0.01
        if not source_layer.isEditable() and not source_layer.startEditing():
            QMessageBox.warning(self.iface.mainWindow(), "无法编辑", f"无法开启 {source_layer.name()} 图层编辑。")
            return

        changed = 0
        vertices_changed = 0
        source_layer.beginEditCommand("选中 LANE/BOUNDARY 接边")
        try:
            for feature_id in selected_ids:
                feature = source_layer.getFeature(feature_id)
                geometry = feature.geometry()
                source_endpoints = self._endpoints(geometry)
                if not feature.isValid() or len(source_endpoints) != 2:
                    continue

                vertex_count = len(list(geometry.vertices()))
                endpoint_indexes = (0, vertex_count - 1)
                # 当前线首尾端点各自寻找最近目标端点，最终只取距离更小的一个。
                candidates = []
                for endpoint, vertex_index in zip(source_endpoints, endpoint_indexes):
                    target_point = min(
                        target_endpoints,
                        key=lambda candidate: self._distance_sq(endpoint, candidate),
                    )
                    candidates.append(
                        (
                            self._distance_sq(endpoint, target_point),
                            vertex_index,
                            target_point,
                        )
                    )
                nearest_distance_sq, nearest_vertex_index, nearest_point = min(
                    candidates, key=lambda item: item[0]
                )
                if nearest_distance_sq <= tolerance * tolerance:
                    continue

                new_geometry = QgsGeometry(geometry)
                feature_changed = new_geometry.moveVertex(
                    nearest_point.x(), nearest_point.y(), nearest_vertex_index
                )
                if feature_changed and source_layer.changeGeometry(feature_id, new_geometry):
                    changed += 1
            source_layer.endEditCommand()
        except Exception:
            source_layer.destroyEditCommand()
            raise

        if changed:
            source_layer.triggerRepaint()
            canvas.refresh()
            self.iface.messageBar().pushMessage(
                "车道工具",
                f"已接边 {changed} 个选中要素，吸附 {vertices_changed} 个最近端点；修改已进入编辑会话，可撤销。",
                level=Qgis.Info,
                duration=6,
            )
        else:
            self.iface.messageBar().pushMessage(
                "车道工具", "选中要素无需接边。", level=Qgis.Info, duration=4
            )
