# -*- coding: utf-8 -*-
"""
车道批量刷值工具 v1.0.4.26
规则来源：更新日志.txt / UpdateShpLane.exe

按钮：
  限速刷值       → 规则 1.1~1.6（与原始软件一致）
  ROAD_TYPE=2    → 将 LANE 图层全部要素的 ROAD_TYPE 字段设为 2
  转向个数刷值   → VIRTUAL 规则 2.1~2.2
  移除所有图层   → 从当前 QGIS 工程中移除全部图层
"""
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import QgsProject, Qgis, QgsCoordinateTransform, QgsFeatureRequest, QgsSpatialIndex, QgsVectorLayer, QgsWkbTypes
from qgis.gui import QgsHighlight
from collections import defaultdict
from datetime import datetime
import math
import os
import re

from .lane_fix_controller import LaneFixController
from .excel_preview_controller import ExcelPreviewController
from .reconstruct_controller import ReconstructController
from .inertial_follow_controller import InertialFollowController
from .map_tile_snap_controller import MapTileSnapController
from .lane_stopline_snap_controller import LaneStoplineSnapController
from .lane_boundary_join_controller import LaneBoundaryJoinController
from .attribute_preset_controller import AttributePresetController
from .boundary_length_controller import BoundaryLengthController
from .error_results_controller import ErrorResultsController


class LaneBatchUpdateTool:
    MODE_SPEED = "speed"
    MODE_SET_ROAD2 = "set_road2"
    MODE_VIRTUAL = "virtual"
    MODE_REMOVE_ALL = "remove_all"
    MODE_CHECK_RIGHT_STRAIGHT = "check_right_straight"
    MODE_SHOW_ERROR_RESULTS = "show_error_results"
    MODE_CLEAR_ALL_HIGHLIGHTS = "clear_all_highlights"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.log_lines = []
        self.shp_dir = ""
        self.field_names = {}
        self.overlap_highlights = []
        self.reconstruct = ReconstructController(iface, self.plugin_dir, self.log)
        self.lane_fix = LaneFixController(iface, self.plugin_dir, self.log)
        self.excel_preview = ExcelPreviewController(iface, self.plugin_dir, self.log)
        self.inertial_follow = InertialFollowController(iface, self.plugin_dir)
        self.map_tile_snap = MapTileSnapController(iface, self.plugin_dir)
        self.lane_stopline_snap = LaneStoplineSnapController(iface, self.plugin_dir)
        self.lane_boundary_join = LaneBoundaryJoinController(iface, self.plugin_dir)
        self.attribute_preset = AttributePresetController(iface, self.plugin_dir)
        self.error_results = ErrorResultsController(iface)
        self.boundary_length = BoundaryLengthController(iface, self.plugin_dir, self.error_results)
        self.error_results.configure_checkers(
            self.run_check_right_straight_overlap,
            self.boundary_length.apply_filter,
            self.clear_all_highlights,
            self.run_check_speedlimit,
            self.run_check_virtual,
            self.run_check_duplicate_vertices,
            self.run_check_extra_boundary_endpoints,
            self.run_check_dangling_points,
            self.run_check_overlapping_lines,
        )

    def initGui(self):
        buttons = (
            (self.MODE_SPEED, "限速刷值", "icon_speed.png"),
            (self.MODE_SET_ROAD2, "ROAD_TYPE=2", "icon_road2.png"),
            (self.MODE_VIRTUAL, "转向个数刷值", "icon_virtual.png"),
            (self.MODE_SHOW_ERROR_RESULTS, "全部规则", "icon_error_results.svg"),
            (self.MODE_CLEAR_ALL_HIGHLIGHTS, "取消全部高亮", "icon_clear_right_straight.svg"),
            (self.MODE_REMOVE_ALL, "移除所有图层", "icon_remove_layers.svg"),
        )
        for mode, label, icon_name in buttons:
            icon_path = os.path.join(self.plugin_dir, icon_name)
            action = QAction(QIcon(icon_path), label, self.iface.mainWindow())
            action.triggered.connect(lambda checked=False, m=mode: self.run(mode=m))
            self.iface.addVectorToolBarIcon(action)
            self.iface.addPluginToVectorMenu("车道处理工具", action)
            self.actions.append(action)
        self.reconstruct.initGui(self.actions)
        self.lane_fix.initGui(self.actions)
        self.excel_preview.initGui(self.actions)
        self.inertial_follow.initGui(self.actions)
        self.map_tile_snap.initGui(self.actions)
        self.lane_stopline_snap.initGui(self.actions)
        self.lane_boundary_join.initGui(self.actions)
        self.attribute_preset.initGui(self.actions)
        self.boundary_length.initGui(self.actions, register_action=False)

    def unload(self):
        self.clear_overlap_highlights()
        for action in self.actions:
            self.iface.removeVectorToolBarIcon(action)
            self.iface.removePluginFromVectorMenu("车道处理工具", action)
        self.actions = []
        self.reconstruct.unload()
        self.lane_fix.unload()
        self.excel_preview.unload()
        self.inertial_follow.unload()
        self.map_tile_snap.unload()
        self.lane_stopline_snap.unload()
        self.lane_boundary_join.unload()
        self.attribute_preset.unload()
        self.boundary_length.unload()
        self.error_results.unload()

    def clear_overlap_highlights(self):
        for highlight in self.overlap_highlights:
            try:
                self.iface.mapCanvas().scene().removeItem(highlight)
            except (AttributeError, RuntimeError):
                pass
            try:
                highlight.hide()
                highlight.deleteLater()
            except (AttributeError, RuntimeError):
                pass
        self.overlap_highlights = []

    def clear_all_highlights(self):
        self.clear_overlap_highlights()
        self.boundary_length.clear_highlights()

    def show_error_results(self):
        self.error_results.show("全部规则")

    @staticmethod
    def line_endpoints(geometry):
        parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
        endpoints = []
        for part in parts:
            if part:
                endpoints.extend((part[0], part[-1]))
        return endpoints

    @staticmethod
    def point_matches_endpoint(point, endpoints, tolerance=1e-8):
        return any(
            abs(point.x() - endpoint.x()) <= tolerance
            and abs(point.y() - endpoint.y()) <= tolerance
            for endpoint in endpoints
        )

    @classmethod
    def has_shared_endpoint(cls, right_geometry, straight_geometry):
        right_endpoints = cls.line_endpoints(right_geometry)
        straight_endpoints = cls.line_endpoints(straight_geometry)
        return any(
            cls.point_matches_endpoint(point, straight_endpoints)
            for point in right_endpoints
        )

    def has_non_endpoint_intersection(self, right_geometry, straight_geometry):
        intersection = right_geometry.intersection(straight_geometry)
        if intersection.isEmpty():
            return False
        if intersection.type() != 0:
            return True
        right_endpoints = self.line_endpoints(right_geometry)
        straight_endpoints = self.line_endpoints(straight_geometry)
        intersection_points = list(intersection.vertices())
        return any(
            not (
                self.point_matches_endpoint(point, right_endpoints)
                and self.point_matches_endpoint(point, straight_endpoints)
            )
            for point in intersection_points
        )

    def run_check_right_straight_overlap(self):
        lane_layer = self.get_project_layer("LANE")
        if not lane_layer:
            QMessageBox.critical(None, "图层缺失", "请在 QGIS 中加载 LANE 图层")
            return

        self.field_names, missing = self.resolve_field_map(
            lane_layer, ["ID", "TYPE", "TURN_TYPE"]
        )
        if missing:
            QMessageBox.critical(None, "字段缺失", f"LANE 缺少字段：{', '.join(missing)}")
            return

        self.clear_overlap_highlights()
        lane_groups = {1: ([], []), 2: ([], [])}
        for feat in lane_layer.getFeatures():
            lane_type = self.to_int(self.feat_val(feat, "TYPE"))
            if lane_type not in lane_groups:
                continue
            turn_type = self.to_int(self.feat_val(feat, "TURN_TYPE"))
            if turn_type == 2:
                lane_groups[lane_type][0].append(feat)
            elif turn_type == 1:
                lane_groups[lane_type][1].append(feat)

        right_lanes = [feat for right, _ in lane_groups.values() for feat in right]
        straight_lanes = [feat for _, straight in lane_groups.values() for feat in straight]
        conflicts = {}
        conflict_features = {}
        for lane_type, (group_right_lanes, group_straight_lanes) in lane_groups.items():
            for right_feat in group_right_lanes:
                right_geometry = right_feat.geometry()
                if right_geometry is None or right_geometry.isEmpty():
                    continue
                for straight_feat in group_straight_lanes:
                    straight_geometry = straight_feat.geometry()
                    if straight_geometry is None or straight_geometry.isEmpty():
                        continue
                    if not self.has_shared_endpoint(right_geometry, straight_geometry):
                        continue
                    if not right_geometry.boundingBox().intersects(straight_geometry.boundingBox()):
                        continue
                    if not right_geometry.intersects(straight_geometry):
                        continue
                    if not self.has_non_endpoint_intersection(
                        right_geometry, straight_geometry
                    ):
                        continue
                    right_id = self.norm_id(self.feat_val(right_feat, "ID"))
                    straight_id = self.norm_id(self.feat_val(straight_feat, "ID"))
                    conflicts.setdefault(right_id, set()).add(straight_id)
                    conflict_features.setdefault(right_id, {"right": right_feat.id(), "straight": set()})["straight"].add(straight_feat.id())

        canvas = self.iface.mapCanvas()
        for right_feat in right_lanes:
            right_id = self.norm_id(self.feat_val(right_feat, "ID"))
            if right_id not in conflicts:
                continue
            highlight = QgsHighlight(canvas, right_feat.geometry(), lane_layer)
            highlight.setColor(QColor("#20a05a"))
            highlight.setWidth(4)
            highlight.show()
            self.overlap_highlights.append(highlight)
        straight_ids = {item for values in conflicts.values() for item in values}
        for straight_feat in straight_lanes:
            straight_id = self.norm_id(self.feat_val(straight_feat, "ID"))
            if straight_id not in straight_ids:
                continue
            highlight = QgsHighlight(canvas, straight_feat.geometry(), lane_layer)
            highlight.setColor(QColor("#f2c94c"))
            highlight.setWidth(4)
            highlight.show()
            self.overlap_highlights.append(highlight)

        if conflicts:
            self.log(
                f"发现同类车道右转线与直行线有交叉：右转 {len(conflicts)} 条，直行 {len(straight_ids)} 条",
                level="ERROR",
                show_bar=False,
            )
            details = "\n".join(
                f"右转 {right_id} ↔ 直行 {', '.join(sorted(straight_ids))}"
                for right_id, straight_ids in sorted(conflicts.items())
            )
            records = [
                {
                    "type": "右转压直行",
                    "message": "右转ID为 %s 压直行ID为 %s" % (
                        right_id,
                        ', '.join(sorted(straight_ids)),
                    ),
                    "selections": {
                        lane_layer.id(): [
                            conflict_features[right_id]["right"],
                            *sorted(conflict_features[right_id]["straight"]),
                        ]
                    },
                    "display_layers": {lane_layer.id(): lane_layer.name()},
                    "display_ids": {
                        lane_layer.id(): [
                            right_id,
                            *sorted(straight_ids),
                        ]
                    },
                }
                for right_id, straight_ids in sorted(conflicts.items())
            ]
            if self.error_results is not None:
                self.error_results.replace_records(records, "右转压直行")
            self.iface.messageBar().pushMessage(
                "车道工具",
                "右转压直行检测完成：发现右转 %d 条、直行 %d 条。" % (
                    len(conflicts), len(straight_ids)
                ),
                Qgis.Warning,
                duration=8,
            )
        else:
            self.iface.messageBar().pushMessage(
                "车道工具",
                "右转压直行检测完成：未发现错误。",
                Qgis.Info,
                duration=6,
            )
        canvas.refresh()

    def run_check_speedlimit(self):
        lane_layer = self.get_project_layer("LANE")
        if lane_layer is None:
            QMessageBox.critical(None, "图层缺失", "请在 QGIS 中加载 LANE 图层")
            return
        fields, missing = self.resolve_field_map(lane_layer, ["ID", "SPEEDLIMIT"])
        if missing:
            QMessageBox.critical(None, "字段缺失", "LANE 缺少字段：%s" % ", ".join(missing))
            return

        records = []
        for feature in lane_layer.getFeatures():
            speedlimit = feature[fields["SPEEDLIMIT"]]
            if not self.is_empty(speedlimit) and self.to_int(speedlimit) != 40:
                continue
            lane_id = self.norm_id(feature[fields["ID"]]) or str(feature.id())
            reason = "不能为空" if self.is_empty(speedlimit) else "不能为40"
            records.append(
                {
                    "type": "SPEEDLIMIT检查",
                    "message": "LANE ID为 %s 的 SPEEDLIMIT%s" % (lane_id, reason),
                    "selections": {lane_layer.id(): [feature.id()]},
                    "display_layers": {lane_layer.id(): lane_layer.name()},
                    "display_ids": {lane_layer.id(): [lane_id]},
                }
            )
        self.error_results.replace_records(records, "SPEEDLIMIT检查")

    def run_check_extra_boundary_endpoints(self, short_segment_only=False, short_segment_threshold=0.0):
        """查找 TYPE 和 COLOR 一致、在端点相接的多个 BOUNDARY 要素。"""
        layer = self.get_project_layer("BOUNDARY")
        record_type = "BOUNDARY多余端点检查"
        if layer is None or layer.geometryType() != 1:
            QMessageBox.critical(None, "图层缺失", "请在 QGIS 中加载线类型 BOUNDARY 图层")
            self.error_results.replace_records([], record_type)
            return

        fields, missing = self.resolve_field_map(layer, ["TYPE", "COLOR"])
        if missing:
            QMessageBox.critical(None, "字段缺失", "BOUNDARY 缺少字段：%s" % ", ".join(missing))
            self.error_results.replace_records([], record_type)
            return

        tolerance = 1e-6
        clusters = self._endpoint_clusters(self._line_endpoint_entries(layer), tolerance)
        records = []
        for cluster in clusters:
            by_attributes = defaultdict(list)
            for entry in cluster:
                feature = entry["feature"]
                attribute_key = (
                    str(feature[fields["TYPE"]]).strip(),
                    str(feature[fields["COLOR"]]).strip(),
                )
                by_attributes[attribute_key].append(entry)
            for (type_value, color_value), entries in by_attributes.items():
                features = {entry["feature"].id(): entry["feature"] for entry in entries}
                if len(features) < 2:
                    continue
                feature_list = list(features.values())
                if short_segment_only and not any(
                    feature.geometry().length() < short_segment_threshold
                    for feature in feature_list
                ):
                    continue
                location = cluster[0]["point"]
                feature_ids = [self._quality_feature_id(feature) for feature in feature_list]
                records.append({
                    "type": record_type,
                    "message": "BOUNDARY 在端点处连接了 %d 个 TYPE=%s、COLOR=%s 一致的要素，可能存在多余断点" % (
                        len(feature_list), type_value, color_value
                    ),
                    "selections": {layer.id(): [feature.id() for feature in feature_list]},
                    "display_layers": {layer.id(): layer.name()},
                    "display_ids": {layer.id(): feature_ids},
                    "location": (location.x(), location.y()),
                })
        self.error_results.replace_records(records, record_type)
        text = "%s完成：发现 %d 处可能的多余断点。" % (record_type, len(records))
        self.iface.messageBar().pushMessage("车道工具", text, Qgis.Warning if records else Qgis.Info, duration=8)

    def run_check_dangling_points(self):
        """检查 BOUNDARY 和 LANE 的每个线部件端点是否贴合另一根线的端点。"""
        record_type = "BOUNDARY/LANE悬挂点检查"
        layers = []
        for name in ("BOUNDARY", "LANE"):
            layer = self.get_project_layer(name)
            if layer is not None and layer.geometryType() == 1:
                layers.append(layer)
        if not layers:
            QMessageBox.critical(None, "图层缺失", "请在 QGIS 中加载 BOUNDARY 或 LANE 线图层")
            self.error_results.replace_records([], record_type)
            return

        tolerance = 1e-6
        records = []
        for layer in layers:
            layer_entries = self._line_endpoint_entries(layer)
            for entry in layer_entries:
                matches = [
                    other for other in layer_entries
                    if other is not entry
                    and other["feature"].id() != entry["feature"].id()
                    and self._points_close(entry["point"], other["point"], tolerance)
                ]
                if matches:
                    continue
                feature = entry["feature"]
                feature_id = self._quality_feature_id(feature)
                point = entry["point"]
                records.append({
                    "type": record_type,
                    "message": "%s 要素 ID=%s 的%s端点未贴合其他线端点" % (layer.name(), feature_id, entry["end_name"]),
                    "selections": {layer.id(): [feature.id()]},
                    "display_layers": {layer.id(): layer.name()},
                    "display_ids": {layer.id(): [feature_id]},
                    "location": (point.x(), point.y()),
                })
        self.error_results.replace_records(records, record_type)
        text = "%s完成：发现 %d 个悬挂点。" % (record_type, len(records))
        self.iface.messageBar().pushMessage("车道工具", text, Qgis.Warning if records else Qgis.Info, duration=8)

    def run_check_overlapping_lines(self, check_minimum_length=True, minimum_length=0.0, check_exact=True):
        """检查 BOUNDARY 和 LANE 图层内相互重合的线要素。"""
        record_type = "BOUNDARY/LANE重合线检查"
        if not check_minimum_length and not check_exact:
            self.error_results.replace_records([], record_type)
            self.iface.messageBar().pushMessage(
                "车道工具", "请至少启用重合长度或完全重合条件。", Qgis.Warning, duration=8
            )
            return

        layers = []
        for name in ("BOUNDARY", "LANE"):
            layer = self.get_project_layer(name)
            if layer is not None and layer.geometryType() == QgsWkbTypes.LineGeometry:
                layers.append(layer)
        if not layers:
            QMessageBox.critical(None, "图层缺失", "请在 QGIS 中加载 BOUNDARY 或 LANE 线图层")
            self.error_results.replace_records([], record_type)
            return

        tolerance = 1e-6
        records = []
        for layer in layers:
            features = {}
            spatial_index = QgsSpatialIndex()
            for feature in layer.getFeatures():
                geometry = feature.geometry()
                if geometry is None or geometry.isEmpty() or geometry.length() <= tolerance:
                    continue
                features[feature.id()] = feature
                spatial_index.addFeature(feature)

            seen_pairs = set()
            for feature_id, feature in features.items():
                geometry = feature.geometry()
                for candidate_id in spatial_index.intersects(geometry.boundingBox()):
                    if candidate_id == feature_id:
                        continue
                    pair = tuple(sorted((feature_id, candidate_id)))
                    if pair in seen_pairs or candidate_id not in features:
                        continue
                    seen_pairs.add(pair)
                    other = features[candidate_id]
                    other_geometry = other.geometry()
                    try:
                        overlap_geometry = geometry.intersection(other_geometry)
                    except Exception:
                        continue
                    if overlap_geometry is None or overlap_geometry.isEmpty():
                        continue
                    overlap_length = overlap_geometry.length()
                    if overlap_length <= tolerance:
                        continue
                    feature_length = geometry.length()
                    other_length = other_geometry.length()
                    fully_overlapped = (
                        abs(overlap_length - feature_length) <= tolerance
                        and abs(overlap_length - other_length) <= tolerance
                    )
                    matched_minimum = check_minimum_length and overlap_length >= minimum_length
                    if not (matched_minimum or (check_exact and fully_overlapped)):
                        continue
                    try:
                        point = overlap_geometry.centroid().asPoint()
                        location = (point.x(), point.y())
                    except Exception:
                        location = None
                    first_display_id = self._quality_feature_id(feature)
                    second_display_id = self._quality_feature_id(other)
                    description = "完全重合" if fully_overlapped else "重合长度 %.6f 米" % overlap_length
                    records.append({
                        "type": record_type,
                        "message": "%s 的要素 ID=%s 与 ID=%s %s" % (
                            layer.name(), first_display_id, second_display_id, description
                        ),
                        "selections": {layer.id(): [feature_id, candidate_id]},
                        "display_layers": {layer.id(): layer.name()},
                        "display_ids": {layer.id(): [first_display_id, second_display_id]},
                        "location": location,
                    })
        self.error_results.replace_records(records, record_type)
        text = "%s完成：发现 %d 组重合线。" % (record_type, len(records))
        self.iface.messageBar().pushMessage("车道工具", text, Qgis.Warning if records else Qgis.Info, duration=8)

    @staticmethod
    def _quality_feature_id(feature):
        names = {field.name().upper(): field.name() for field in feature.fields()}
        field_name = names.get("ID")
        value = feature[field_name] if field_name else None
        return LaneBatchUpdateTool.norm_id(value) or str(feature.id())

    @staticmethod
    def _line_endpoint_entries(layer):
        entries = []
        for feature in layer.getFeatures():
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue
            parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
            for part_number, vertices in enumerate(parts, 1):
                if len(vertices) < 2:
                    continue
                entries.append({"layer": layer, "feature": feature, "point": vertices[0], "inner": vertices[1], "end_name": "起点", "part": part_number})
                entries.append({"layer": layer, "feature": feature, "point": vertices[-1], "inner": vertices[-2], "end_name": "终点", "part": part_number})
        return entries

    @staticmethod
    def _points_close(first, second, tolerance):
        return math.hypot(first.x() - second.x(), first.y() - second.y()) <= tolerance

    @staticmethod
    def _endpoint_clusters(entries, tolerance):
        clusters = []
        for entry in entries:
            cluster = next((items for items in clusters if LaneBatchUpdateTool._points_close(entry["point"], items[0]["point"], tolerance)), None)
            if cluster is None:
                clusters.append([entry])
            else:
                cluster.append(entry)
        return clusters

    @staticmethod
    def _same_non_geometry_attributes(first, second):
        for field in first.fields():
            name = field.name().upper()
            if name in ("ID", "FID", "OBJECTID", "SHAPE_LENGTH", "SHAPE_AREA"):
                continue
            if str(first[field.name()]).strip() != str(second[field.name()]).strip():
                return False
        return True

    @staticmethod
    def _endpoint_directions_are_continuous(first, second):
        first_dx = first["inner"].x() - first["point"].x()
        first_dy = first["inner"].y() - first["point"].y()
        second_dx = second["inner"].x() - second["point"].x()
        second_dy = second["inner"].y() - second["point"].y()
        first_length = math.hypot(first_dx, first_dy)
        second_length = math.hypot(second_dx, second_dy)
        if first_length == 0 or second_length == 0:
            return False
        dot = (first_dx * second_dx + first_dy * second_dy) / (first_length * second_length)
        return dot <= -math.cos(math.radians(20))

    def run_check_duplicate_vertices(self):
        """检查全部矢量图层中同一几何部件内的重复顶点。"""
        records = []
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            id_index = layer.fields().indexFromName("ID")
            if id_index < 0:
                id_index = next(
                    (
                        index
                        for index, field in enumerate(layer.fields())
                        if field.name().upper() == "ID"
                    ),
                    -1,
                )
            transform = None
            if layer.crs() != canvas_crs:
                try:
                    transform = QgsCoordinateTransform(
                        layer.crs(), canvas_crs, QgsProject.instance()
                    )
                except Exception:
                    transform = None
            for feature in layer.getFeatures():
                geometry = feature.geometry()
                if geometry is None or geometry.isEmpty():
                    continue
                feature_id = self.norm_id(feature[id_index]) if id_index >= 0 else ""
                feature_id = feature_id or str(feature.id())
                for part_number, vertices in enumerate(
                    self._geometry_vertex_parts(geometry), 1
                ):
                    seen = {}
                    for vertex_number, point in enumerate(vertices, 1):
                        key = (point.x(), point.y())
                        first_vertex = seen.get(key)
                        if first_vertex is None:
                            seen[key] = vertex_number
                            continue
                        location = point
                        if transform is not None:
                            try:
                                location = transform.transform(point)
                            except Exception:
                                location = point
                        records.append(
                            {
                                "type": "重复顶点检查",
                                "message": (
                                    "%s 的要素 ID=%s，第%d部分顶点%d 与顶点%d重复，坐标=(%.8f, %.8f)"
                                    % (
                                        layer.name(),
                                        feature_id,
                                        part_number,
                                        vertex_number,
                                        first_vertex,
                                        point.x(),
                                        point.y(),
                                    )
                                ),
                                "selections": {layer.id(): [feature.id()]},
                                "display_layers": {layer.id(): layer.name()},
                                "display_ids": {layer.id(): [feature_id]},
                                "location": (location.x(), location.y()),
                            }
                        )
        self.error_results.replace_records(records, "重复顶点检查")
        level = Qgis.Warning if records else Qgis.Info
        text = "重复顶点检查完成：发现 %d 个重复顶点。" % len(records)
        if not records:
            text = "重复顶点检查完成：未发现重复顶点。"
        self.iface.messageBar().pushMessage("车道工具", text, level, duration=8)

    @staticmethod
    def _geometry_vertex_parts(geometry):
        """返回逐个独立几何部件或面环的顶点，排除合法面环闭合点。"""
        geometry_type = geometry.type()
        if geometry_type == QgsWkbTypes.PointGeometry:
            points = geometry.asMultiPoint() if geometry.isMultipart() else [geometry.asPoint()]
            return [[point] for point in points]
        if geometry_type == QgsWkbTypes.LineGeometry:
            return geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
        polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]
        parts = []
        for polygon in polygons:
            for ring in polygon:
                vertices = list(ring)
                if len(vertices) > 1 and vertices[0] == vertices[-1]:
                    vertices.pop()
                parts.append(vertices)
        return parts

    def run_check_virtual(self):
        lane_layer = self.get_project_layer("LANE")
        intersection_layer = self.get_project_layer("INTERSECTION")
        lane_node_layer = self.get_project_layer("LANE_NODE")
        if lane_layer is None or intersection_layer is None or lane_node_layer is None:
            missing_layers = []
            if lane_layer is None:
                missing_layers.append("LANE")
            if intersection_layer is None:
                missing_layers.append("INTERSECTION")
            if lane_node_layer is None:
                missing_layers.append("LANE_NODE")
            QMessageBox.critical(None, "图层缺失", "请在 QGIS 中加载图层：%s" % ", ".join(missing_layers))
            return
        lane_fields, missing = self.resolve_field_map(
            lane_layer, ["ID", "ROAD_ID", "VIRTUAL", "TURN_TYPE", "LANE_DIR", "FROM_NODE", "TO_NODE"]
        )
        intersection_fields, intersection_missing = self.resolve_field_map(
            intersection_layer, ["ROADS"]
        )
        lane_node_fields, lane_node_missing = self.resolve_field_map(
            lane_node_layer, ["ID", "LANES"]
        )
        missing.extend("INTERSECTION.%s" % name for name in intersection_missing)
        missing.extend("LANE_NODE.%s" % name for name in lane_node_missing)
        if missing:
            QMessageBox.critical(None, "字段缺失", "缺少字段：%s" % ", ".join(missing))
            return

        intersection_roads = set()
        intersection_features = {}
        for feature in intersection_layer.getFeatures():
            road_ids = self.split_ids(feature[intersection_fields["ROADS"]])
            for road_id in road_ids:
                intersection_roads.add(road_id)
                intersection_features.setdefault(road_id, []).append(feature.id())

        lane_by_id = {}
        for feature in lane_layer.getFeatures():
            lane_id = self.norm_id(feature[lane_fields["ID"]])
            if lane_id:
                lane_by_id[lane_id] = feature

        node_to_lane_ids = defaultdict(list)
        node_lane_seen = defaultdict(set)
        for node_feature in lane_node_layer.getFeatures():
            node_id = self.norm_id(node_feature[lane_node_fields["ID"]])
            if not node_id:
                continue
            for related_id in self.split_ids(node_feature[lane_node_fields["LANES"]]):
                if related_id not in node_lane_seen[node_id]:
                    node_to_lane_ids[node_id].append(related_id)
                    node_lane_seen[node_id].add(related_id)

        records = []
        for feature in lane_layer.getFeatures():
            lane_id = self.norm_id(feature[lane_fields["ID"]]) or str(feature.id())
            road_id = self.norm_id(feature[lane_fields["ROAD_ID"]])
            virtual = self.to_int(feature[lane_fields["VIRTUAL"]])
            is_intersection_lane = road_id in intersection_roads
            if is_intersection_lane and virtual != 9:
                selections = {lane_layer.id(): [feature.id()]}
                related_intersections = intersection_features.get(road_id, [])
                if related_intersections:
                    selections[intersection_layer.id()] = related_intersections
                records.append(
                    {
                        "type": "路口LANE与VIRTUAL检查",
                        "message": "路口 LANE ID为 %s（ROAD_ID=%s）的 VIRTUAL 必须为9，当前为%s"
                        % (lane_id, road_id, feature[lane_fields["VIRTUAL"]]),
                        "selections": selections,
                        "display_layers": {
                            lane_layer.id(): lane_layer.name(),
                            intersection_layer.id(): intersection_layer.name(),
                        },
                        "display_ids": {lane_layer.id(): [lane_id]},
                    }
                )
            elif not is_intersection_lane:
                lane_dir = self.to_int(feature[lane_fields["LANE_DIR"]])
                current_end_node = self.norm_id(
                    feature[lane_fields["FROM_NODE"]]
                    if lane_dir == 2
                    else feature[lane_fields["TO_NODE"]]
                )
                node_lane_ids = node_to_lane_ids.get(current_end_node, [])
                next_lanes = [
                    lane_by_id[related_id]
                    for related_id in node_lane_ids
                    if related_id != lane_id
                    and related_id in lane_by_id
                    and self.norm_id(
                        lane_by_id[related_id][lane_fields["TO_NODE"]]
                        if self.to_int(lane_by_id[related_id][lane_fields["LANE_DIR"]]) == 2
                        else lane_by_id[related_id][lane_fields["FROM_NODE"]]
                    ) == current_end_node
                ]
                has_intersection_next = any(
                    self.norm_id(following[lane_fields["ROAD_ID"]]) in intersection_roads
                    for following in next_lanes
                )
                if has_intersection_next:
                    turn_types = {
                        self.to_int(following[lane_fields["TURN_TYPE"]])
                        for following in next_lanes
                        if self.to_int(following[lane_fields["TURN_TYPE"]]) not in (None, 0)
                    }
                    expected_virtual = len(turn_types)
                    reason = "下一条为路口LANE，下一条LANE的不同非零TURN_TYPE数量为%d" % expected_virtual
                else:
                    expected_virtual = 9
                    reason = "没有下一条LANE或下一条不是路口 LANE"
                if virtual != expected_virtual:
                    records.append(
                        {
                            "type": "路口LANE与VIRTUAL检查",
                            "message": "非路口 LANE ID为 %s 的 VIRTUAL 应为%d（%s），当前为%s"
                            % (lane_id, expected_virtual, reason, feature[lane_fields["VIRTUAL"]]),
                            "selections": {lane_layer.id(): [feature.id()]},
                            "display_layers": {lane_layer.id(): lane_layer.name()},
                            "display_ids": {lane_layer.id(): [lane_id]},
                        }
                    )
        self.error_results.replace_records(records, "路口LANE与VIRTUAL检查")

    @staticmethod
    def is_empty(value):
        if value is None:
            return True
        text = str(value).strip()
        return text in ("", "None", "NULL")

    @staticmethod
    def norm_id(value):
        if LaneBatchUpdateTool.is_empty(value):
            return ""
        text = str(value).strip()
        try:
            num = float(text)
            if num == int(num):
                return str(int(num))
        except (TypeError, ValueError):
            pass
        return text

    @staticmethod
    def split_ids(raw):
        if LaneBatchUpdateTool.is_empty(raw):
            return []
        return [
            LaneBatchUpdateTool.norm_id(part)
            for part in re.split(r"[|,;]", str(raw))
            if LaneBatchUpdateTool.norm_id(part)
        ]

    @staticmethod
    def to_int(value, default=None):
        if LaneBatchUpdateTool.is_empty(value):
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    # UpdateShpLane.exe 规则 1.6：按 turn_type 在节点/方向查找关联路段限速（见 cross_lane_speed）
    def is_invalid_speed(self, value):
        if self.is_empty(value):
            return True
        speed = self.to_int(value)
        return speed is None or speed <= 0

    @staticmethod
    def layer_source_path(layer):
        src = layer.source()
        if "|" in src:
            src = src.split("|", 1)[0]
        return os.path.normpath(src)

    @staticmethod
    def get_project_layer(*names):
        project = QgsProject.instance()
        for name in names:
            layers = project.mapLayersByName(name)
            if layers:
                return layers[0]

        targets = {n.lower() for n in names}
        shp_targets = {f"{n.lower()}.shp" for n in names}
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if layer.name().lower() in targets:
                return layer
            src = layer.source().split("|", 1)[0]
            if os.path.basename(src).lower() in shp_targets:
                return layer
        return None

    def ensure_editing(self, layer):
        if layer.isEditable():
            return
        if not layer.startEditing():
            raise RuntimeError(f"无法开启图层编辑：{layer.name()}")

    def resolve_field_map(self, layer, required_names):
        mapping = {}
        upper = {field.name().upper(): field.name() for field in layer.fields()}
        missing = []
        for name in required_names:
            actual = upper.get(name.upper())
            if actual is None:
                missing.append(name)
            else:
                mapping[name.upper()] = actual
        return mapping, missing

    def feat_val(self, feat, logical_name):
        actual = self.field_names.get(logical_name.upper())
        if not actual:
            return None
        return feat[actual]

    def set_feat_val(self, feat, logical_name, value):
        actual = self.field_names.get(logical_name.upper())
        if actual:
            feat[actual] = value

    def qfield(self, logical_name):
        actual = self.field_names.get(logical_name.upper(), logical_name)
        return f'"{actual}"'

    def log(self, text, level="INFO", show_bar=True):
        line = f"{datetime.now():%H:%M:%S} [{level}] {text}"
        self.log_lines.append(line)
        if show_bar:
            qgis_level = Qgis.Critical if level == "ERROR" else Qgis.Info
            self.iface.messageBar().pushMessage("车道工具", text, qgis_level, duration=12)

    def save_log_file(self, mode):
        if not self.log_lines:
            return None
        log_dir = os.path.join(self.plugin_dir, "log")
        os.makedirs(log_dir, exist_ok=True)
        prefix = {
            self.MODE_SPEED: "speed",
            self.MODE_SET_ROAD2: "roadtype2",
            self.MODE_VIRTUAL: "virtual",
        }.get(mode, "lane")
        log_path = os.path.join(log_dir, f"log_{prefix}_{datetime.now():%Y-%m-%d}.txt")
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(self.log_lines) + "\n")
        return log_path

    @staticmethod
    def commit_layer(layer):
        if not layer.isEditable():
            return True, []
        if not layer.commitChanges():
            return False, layer.commitErrors()
        return True, []

    def begin_run(self):
        self.log_lines = []
        self.field_names = {}

    def log_startup(self, lane_layer):
        self.shp_dir = os.path.dirname(self.layer_source_path(lane_layer))
        self.log("程序启动成功!")
        self.log(f".shp目录：{self.shp_dir}")

    def load_lane_only(self):
        lane_layer = self.get_project_layer("LANE")
        if not lane_layer:
            QMessageBox.critical(None, "图层缺失", "请在 QGIS 中加载 LANE 图层")
            return None

        self.log_startup(lane_layer)
        self.field_names, missing = self.resolve_field_map(lane_layer, ["ID", "ROAD_TYPE"])
        if missing:
            QMessageBox.critical(None, "字段缺失", f"LANE 缺少字段：{', '.join(missing)}")
            return None

        return {"lane_layer": lane_layer}

    def load_context(self):
        lane_layer = self.get_project_layer("LANE")
        lane_node_layer = self.get_project_layer("LANE_NODE")
        inter_layer = self.get_project_layer("INTERSECTION")

        if not lane_layer:
            QMessageBox.critical(None, "图层缺失", "请在 QGIS 中加载 LANE 图层")
            return None
        if not lane_node_layer:
            QMessageBox.critical(None, "图层缺失", "请在 QGIS 中加载 LANE_NODE 图层")
            return None

        self.log_startup(lane_layer)

        lane_required = [
            "ID", "TYPE", "ROAD_TYPE", "TURN_TYPE", "ROAD_ID", "SECTION_ID", "LANE_DIR", "FROM_NODE", "TO_NODE", "SPEEDLIMIT",
        ]
        self.field_names, missing = self.resolve_field_map(lane_layer, lane_required)
        if missing:
            QMessageBox.critical(None, "字段缺失", f"LANE 缺少字段：{', '.join(missing)}")
            return None

        node_fields, node_missing = self.resolve_field_map(lane_node_layer, ["ID", "LANES"])
        if node_missing:
            QMessageBox.critical(None, "字段缺失", f"LANE_NODE 缺少字段：{', '.join(node_missing)}")
            return None

        inter_road_set = set()
        inter_by_node = {}
        inter_fields = {}
        if not inter_layer:
            self.log("未找到 INTERSECTION 图层，规则1.6 路口车道将跳过", show_bar=False)
        else:
            inter_fields, inter_missing = self.resolve_field_map(
                inter_layer, ["ID", "ROADS", "ROADS1"]
            )
            if inter_missing:
                self.log(
                    f"INTERSECTION 缺少字段 {', '.join(inter_missing)}，规则1.6 将跳过",
                    show_bar=False,
                )
            else:
                for optional in ("LANES", "ONLINE_LAN", "LOG_LAN"):
                    extra, missing = self.resolve_field_map(inter_layer, [optional])
                    if not missing:
                        inter_fields.update(extra)
                id_field = inter_fields["ID"]
                for feat in inter_layer.getFeatures():
                    node_id = self.norm_id(feat[id_field])
                    if node_id:
                        inter_by_node[node_id] = feat
                    inter_road_set.update(self.split_ids(feat[inter_fields["ROADS"]]))
                    inter_road_set.update(self.split_ids(feat[inter_fields["ROADS1"]]))

        lane_by_id = {}
        lane_fid_by_id = {}
        for feat in lane_layer.getFeatures():
            lane_id = self.norm_id(self.feat_val(feat, "ID"))
            if lane_id:
                lane_by_id[lane_id] = feat
                lane_fid_by_id[lane_id] = feat.id()

        node_to_lane_ids = defaultdict(list)
        node_lane_order = {}
        seen_lane_on_node = defaultdict(set)
        lanes_field = node_fields["LANES"]
        id_field = node_fields["ID"]
        for node_feat in lane_node_layer.getFeatures():
            node_id = self.norm_id(node_feat[id_field])
            if not node_id:
                continue
            ordered_ids = self.split_ids(node_feat[lanes_field])
            node_lane_order[node_id] = ordered_ids
            for lane_id in ordered_ids:
                if lane_id in lane_by_id and lane_id not in seen_lane_on_node[node_id]:
                    node_to_lane_ids[node_id].append(lane_id)
                    seen_lane_on_node[node_id].add(lane_id)

        return {
            "lane_layer": lane_layer,
            "lane_by_id": lane_by_id,
            "lane_fid_by_id": lane_fid_by_id,
            "node_to_lane_ids": node_to_lane_ids,
            "node_lane_order": node_lane_order,
            "inter_road_set": inter_road_set,
            "inter_by_node": inter_by_node,
            "inter_fields": inter_fields,
        }

    def load_context_virtual(self):
        ctx = self.load_context()
        if ctx is None:
            return None
        extra, missing = self.resolve_field_map(ctx["lane_layer"], ["VIRTUAL"])
        if missing:
            QMessageBox.critical(None, "字段缺失", f"LANE 缺少字段：{', '.join(missing)}")
            return None
        self.field_names.update(extra)
        return ctx

    def update_feature(self, ctx, feat, updates):
        """与转向刷值相同的写入方式：set 字段 + updateFeature。"""
        lane_layer = ctx["lane_layer"]
        lane_id = self.norm_id(self.feat_val(feat, "ID"))
        for logical_name, value in updates.items():
            self.set_feat_val(feat, logical_name, value)
        if not lane_layer.updateFeature(feat):
            raise RuntimeError(f"写入失败 laneid={lane_id}")
        if lane_id and "lane_by_id" in ctx:
            ctx["lane_by_id"][lane_id] = feat
            for logical_name, value in updates.items():
                self.set_feat_val(ctx["lane_by_id"][lane_id], logical_name, value)

    def get_min_speed(self, ctx, node_id, visited, mode):
        lane_by_id = ctx["lane_by_id"]
        node_to_lane_ids = ctx["node_to_lane_ids"]

        node_id = self.norm_id(node_id)
        if not node_id or node_id in visited:
            return None
        visited.add(node_id)

        speed_values = []
        next_nodes = []
        for lane_id in node_to_lane_ids.get(node_id, []):
            lane = lane_by_id.get(lane_id)
            if lane is None:
                continue
            lane_type = self.to_int(self.feat_val(lane, "TYPE"))
            road_type = self.to_int(self.feat_val(lane, "ROAD_TYPE"))
            turn_type = self.to_int(self.feat_val(lane, "TURN_TYPE"))
            from_node = self.norm_id(self.feat_val(lane, "FROM_NODE"))
            to_node = self.norm_id(self.feat_val(lane, "TO_NODE"))

            if lane_type == 2 and road_type == 2 and turn_type == 0:
                speed = self.to_int(self.feat_val(lane, "SPEEDLIMIT"))
                use_lane = (
                    mode == "any"
                    or (mode == "in" and to_node == node_id)
                    or (mode == "out" and from_node == node_id)
                )
                if use_lane and not self.is_invalid_speed(speed):
                    speed_values.append(speed)
                else:
                    if mode == "any":
                        other = to_node if from_node == node_id else from_node
                        if other and other not in visited:
                            next_nodes.append(other)
                    elif mode == "in":
                        if to_node == node_id and from_node not in visited:
                            next_nodes.append(from_node)
                        elif from_node == node_id and to_node not in visited:
                            next_nodes.append(to_node)
                    elif mode == "out":
                        if from_node == node_id and to_node not in visited:
                            next_nodes.append(to_node)
                        elif to_node == node_id and from_node not in visited:
                            next_nodes.append(from_node)
            else:
                if mode == "any":
                    other = to_node if from_node == node_id else from_node
                    if other and other not in visited:
                        next_nodes.append(other)
                elif mode == "in" and to_node == node_id and from_node not in visited:
                    next_nodes.append(from_node)
                elif mode == "out" and from_node == node_id and to_node not in visited:
                    next_nodes.append(to_node)

        candidates = []
        if speed_values:
            candidates.append(min(speed_values))
        for next_node in next_nodes:
            result = self.get_min_speed(ctx, next_node, visited, mode)
            if not self.is_invalid_speed(result):
                candidates.append(result)
        return min(candidates) if candidates else None

    def get_min_speed_no_turn(self, ctx, node_id, visited, mode):
        """get_min_speed 变体：不穿越 turn!=0 车道，仅沿直行车道延伸。"""
        lane_by_id = ctx["lane_by_id"]
        node_to_lane_ids = ctx["node_to_lane_ids"]

        node_id = self.norm_id(node_id)
        if not node_id or node_id in visited:
            return None
        visited.add(node_id)

        speed_values = []
        next_nodes = []
        for lane_id in node_to_lane_ids.get(node_id, []):
            lane = lane_by_id.get(lane_id)
            if lane is None:
                continue
            lane_type = self.to_int(self.feat_val(lane, "TYPE"))
            road_type = self.to_int(self.feat_val(lane, "ROAD_TYPE"))
            turn_type = self.to_int(self.feat_val(lane, "TURN_TYPE"))
            from_node = self.norm_id(self.feat_val(lane, "FROM_NODE"))
            to_node = self.norm_id(self.feat_val(lane, "TO_NODE"))

            if lane_type == 2 and road_type == 2 and turn_type == 0:
                speed = self.to_int(self.feat_val(lane, "SPEEDLIMIT"))
                use_lane = (
                    mode == "any"
                    or (mode == "in" and to_node == node_id)
                    or (mode == "out" and from_node == node_id)
                )
                if use_lane and not self.is_invalid_speed(speed):
                    speed_values.append(speed)
                elif mode == "in":
                    if to_node == node_id and from_node not in visited:
                        next_nodes.append(from_node)
                    elif from_node == node_id and to_node not in visited:
                        next_nodes.append(to_node)
                elif mode == "out":
                    if from_node == node_id and to_node not in visited:
                        next_nodes.append(to_node)
                    elif to_node == node_id and from_node not in visited:
                        next_nodes.append(from_node)
                elif mode == "any":
                    other = to_node if from_node == node_id else from_node
                    if other and other not in visited:
                        next_nodes.append(other)
            elif mode == "any":
                other = to_node if from_node == node_id else from_node
                if other and other not in visited:
                    next_nodes.append(other)

        candidates = []
        if speed_values:
            candidates.append(min(speed_values))
        for next_node in next_nodes:
            result = self.get_min_speed_no_turn(ctx, next_node, visited, mode)
            if not self.is_invalid_speed(result):
                candidates.append(result)
        return min(candidates) if candidates else None

    def turn_count_at(self, ctx, node_id):
        lane_by_id = ctx["lane_by_id"]
        node_to_lane_ids = ctx["node_to_lane_ids"]
        node_id = self.norm_id(node_id)
        count = 0
        for lane_id in node_to_lane_ids.get(node_id, []):
            lane = lane_by_id.get(lane_id)
            if lane is None:
                continue
            if self.to_int(self.feat_val(lane, "TURN_TYPE")):
                count += 1
        return count

    def sibling_turn_speed_max(self, ctx, node_id, exclude_lane_id):
        """同节点上已刷值的转向车道最高限速（用于 tt=4 同 from 节点 sibling）。"""
        lane_by_id = ctx["lane_by_id"]
        node_to_lane_ids = ctx["node_to_lane_ids"]
        node_id = self.norm_id(node_id)
        exclude_lane_id = self.norm_id(exclude_lane_id)
        best = None
        for lane_id in node_to_lane_ids.get(node_id, []):
            if self.norm_id(lane_id) == exclude_lane_id:
                continue
            lane = lane_by_id.get(lane_id)
            if lane is None:
                continue
            if self.to_int(self.feat_val(lane, "TYPE")) != 2:
                continue
            if self.to_int(self.feat_val(lane, "ROAD_TYPE")) != 2:
                continue
            if not self.to_int(self.feat_val(lane, "TURN_TYPE")):
                continue
            speed = self.to_int(self.feat_val(lane, "SPEEDLIMIT"))
            if not self.is_invalid_speed(speed):
                best = speed if best is None else max(best, speed)
        return best

    def has_tt3_speed_70(self, ctx, to_node):
        lane_by_id = ctx["lane_by_id"]
        node_to_lane_ids = ctx["node_to_lane_ids"]
        to_node = self.norm_id(to_node)
        for lane_id in node_to_lane_ids.get(to_node, []):
            lane = lane_by_id.get(lane_id)
            if lane is None:
                continue
            if self.to_int(self.feat_val(lane, "TURN_TYPE")) != 3:
                continue
            speed = self.to_int(self.feat_val(lane, "SPEEDLIMIT"))
            if speed is not None and speed >= 70:
                return True
        return False

    def direct_in_straight_max(self, ctx, to_node):
        """to_node 上直接驶入的直行车道（turn_type=0）的最高限速。"""
        lane_by_id = ctx["lane_by_id"]
        node_to_lane_ids = ctx["node_to_lane_ids"]
        to_node = self.norm_id(to_node)
        best = None
        for lane_id in node_to_lane_ids.get(to_node, []):
            lane = lane_by_id.get(lane_id)
            if lane is None:
                continue
            if self.to_int(self.feat_val(lane, "TYPE")) != 2:
                continue
            if self.to_int(self.feat_val(lane, "ROAD_TYPE")) != 2:
                continue
            if self.to_int(self.feat_val(lane, "TURN_TYPE")) != 0:
                continue
            if self.norm_id(self.feat_val(lane, "TO_NODE")) != to_node:
                continue
            speed = self.to_int(self.feat_val(lane, "SPEEDLIMIT"))
            if not self.is_invalid_speed(speed):
                best = speed if best is None else max(best, speed)
        return best

    def intersection_lane_ids(self, ctx, node_id):
        """FUN_00423610 / FUN_004226c0：INTERSECTION.lanes，缺失时回退 LANE_NODE.LANES。"""
        node_id = self.norm_id(node_id)
        inter_fields = ctx.get("inter_fields") or {}
        inter_feat = ctx.get("inter_by_node", {}).get(node_id)
        if inter_feat is not None:
            for logical in ("LANES", "ONLINE_LAN", "LOG_LAN"):
                field = inter_fields.get(logical)
                if not field:
                    continue
                lane_ids = self.split_ids(inter_feat[field])
                if lane_ids:
                    return lane_ids
        return ctx.get("node_lane_order", {}).get(node_id, [])

    def speed_from_node_lane_list(self, ctx, lane_id, node_id, end="from"):
        """
        FUN_004226c0 规则 1.6：按 LANE_NODE.lanes 顺序在直行/转向索引查 speedlimit。

        直行索引（local_80）：turn_type==0，读已刷好的 speed（含 ROAD_TYPE=1 的 30）。
        驶出端仅 2 条 lane 时，可回退读转向索引（LAB_004230ac）。
        驶入端仅 2 条且只有转向 lane 时失败（LAB_00422df3）。
        """
        lane_ids = ctx.get("node_lane_order", {}).get(self.norm_id(node_id), [])
        if len(lane_ids) < 2:
            return None
        lane_by_id = ctx["lane_by_id"]
        for other_id in lane_ids:
            if other_id == lane_id:
                continue
            other = lane_by_id.get(other_id)
            if other is None:
                continue
            turn_type = self.to_int(self.feat_val(other, "TURN_TYPE"))
            if turn_type == 0:
                speed = self.to_int(self.feat_val(other, "SPEEDLIMIT"))
                if not self.is_invalid_speed(speed):
                    return speed
                continue
            if len(lane_ids) == 2:
                if end == "from":
                    return None
                speed = self.to_int(self.feat_val(other, "SPEEDLIMIT"))
                if not self.is_invalid_speed(speed):
                    return speed
        return None

    def split_turn_lane_speed(self, ctx, lane_id, node_id, end):
        """跨越同 SECTION_ID 的双转向断点，查询同一路径另一段的外侧节点。"""
        node_id = self.norm_id(node_id)
        lane_ids = ctx.get("node_lane_order", {}).get(node_id, [])
        if len(lane_ids) != 2:
            return None

        lane_by_id = ctx["lane_by_id"]
        lane = lane_by_id.get(lane_id)
        if lane is None:
            return None
        section_id = self.norm_id(self.feat_val(lane, "SECTION_ID"))
        if not section_id:
            return None

        other_id = next((item for item in lane_ids if item != lane_id), None)
        other = lane_by_id.get(other_id)
        if other is None:
            return None
        if not self.to_int(self.feat_val(other, "TURN_TYPE")):
            return None
        if self.norm_id(self.feat_val(other, "SECTION_ID")) != section_id:
            return None

        other_from = self.norm_id(self.feat_val(other, "FROM_NODE"))
        other_to = self.norm_id(self.feat_val(other, "TO_NODE"))
        outside_node = other_to if other_from == node_id else other_from
        if not outside_node:
            return None
        return self.speed_from_node_lane_list(ctx, other_id, outside_node, end=end)

    def cross_lane_speed(self, ctx, feat):
        """FUN_004226c0 规则 1.6：from/to 节点各取关联限速，再取 min。"""
        lane_id = self.norm_id(self.feat_val(feat, "ID"))
        from_node = self.norm_id(self.feat_val(feat, "FROM_NODE"))
        to_node = self.norm_id(self.feat_val(feat, "TO_NODE"))
        speed_from = self.speed_from_node_lane_list(ctx, lane_id, from_node, end="from")
        speed_to = self.speed_from_node_lane_list(ctx, lane_id, to_node, end="to")
        if speed_from is None:
            speed_from = self.split_turn_lane_speed(ctx, lane_id, from_node, end="from")
        if speed_to is None:
            speed_to = self.split_turn_lane_speed(ctx, lane_id, to_node, end="to")
        if speed_from is None:
            self.log(
                f"路口laneid={lane_id},未找到关联的驶入lane",
                level="ERROR",
                show_bar=False,
            )
        if speed_to is None:
            self.log(
                f"路口laneid={lane_id},未找到关联的驶出lane",
                level="ERROR",
                show_bar=False,
            )
        if speed_from is None or speed_to is None:
            return None
        return min(speed_from, speed_to)

    def refill_invalid_turn_speeds(self, ctx):
        """补刷：turn!=0 且 speedlimit 仍为空或 0 的要素。"""
        lane_layer = ctx["lane_layer"]
        count = 0
        for feat in lane_layer.getFeatures():
            turn_type = self.to_int(self.feat_val(feat, "TURN_TYPE"))
            if not turn_type:
                continue
            if not self.is_invalid_speed(self.feat_val(feat, "SPEEDLIMIT")):
                continue

            lane_id = self.norm_id(self.feat_val(feat, "ID"))
            lane_type = self.to_int(self.feat_val(feat, "TYPE"))
            road_type = self.to_int(self.feat_val(feat, "ROAD_TYPE"))
            speed = None

            if lane_type == 2 and road_type == 2:
                speed = self.cross_lane_speed(ctx, feat)
            elif lane_type == 1 and road_type == 2:
                speed = 25
            elif lane_type == 1 and road_type == 1:
                speed = 15
            elif lane_type == 1 and road_type == 3:
                speed = 5
            elif lane_type == 4:
                speed = 70
            elif lane_type == 2 and road_type == 1:
                speed = 15
            elif lane_type == 2 and road_type == 3:
                speed = 5

            if self.is_invalid_speed(speed):
                self.log(
                    f"路口laneid={lane_id},turntype={turn_type},补刷失败,speedlimit仍无效",
                    level="ERROR",
                    show_bar=False,
                )
                continue

            self.update_feature(ctx, feat, {"SPEEDLIMIT": speed})
            self.log(
                f"laneid={lane_id},speedlimit={speed}(补刷,turntype={turn_type})",
                show_bar=False,
            )
            count += 1
        return count

    def run_set_road_type_2(self, ctx):
        lane_layer = ctx["lane_layer"]
        self.ensure_editing(lane_layer)

        count = 0
        for feat in lane_layer.getFeatures():
            lane_id = self.norm_id(self.feat_val(feat, "ID"))
            old_val = self.to_int(self.feat_val(feat, "ROAD_TYPE"))
            self.update_feature(ctx, feat, {"ROAD_TYPE": 2})
            self.log(f"laneid={lane_id},road_type={old_val}->2", show_bar=False)
            count += 1

        ok, errors = self.commit_layer(lane_layer)
        if not ok:
            lane_layer.rollBack()
            raise RuntimeError("\n".join(errors))
        return count

    def run_speed(self, ctx):
        lane_layer = ctx["lane_layer"]
        self.ensure_editing(lane_layer)

        count = 0
        all_feats = list(lane_layer.getFeatures())

        for feat in all_feats:
            lane_type = self.to_int(self.feat_val(feat, "TYPE"))
            road_type = self.to_int(self.feat_val(feat, "ROAD_TYPE"))
            lane_id = self.norm_id(self.feat_val(feat, "ID"))
            speed = None
            log_line = None

            if lane_type == 1 and road_type == 2:
                speed = 25
                log_line = f"laneid={lane_id},speedlimit={speed}(type=1,roadtype=2)"
            elif lane_type == 1 and road_type == 1:
                speed = 15
                log_line = f"laneid={lane_id},speedlimit={speed}(type=1,roadtype=1)"
            elif lane_type == 1 and road_type == 3:
                speed = 5
                log_line = f"laneid={lane_id},speedlimit={speed}(type=1,roadtype=3)"
            elif lane_type == 4:
                speed = 70
                log_line = f"laneid={lane_id},speedlimit={speed}(type=4,roadtype={road_type})"
            elif lane_type == 2 and road_type == 1:
                speed = 15
                log_line = f"laneid={lane_id},speedlimit={speed}(type=2,roadtype=1)"
            elif lane_type == 2 and road_type == 3:
                speed = 5
                log_line = f"laneid={lane_id},speedlimit={speed}(type=2,roadtype=3)"

            if speed is not None:
                self.update_feature(ctx, feat, {"SPEEDLIMIT": speed})
                self.log(log_line, show_bar=False)
                count += 1

        straight_feats = [
            feat for feat in all_feats
            if self.to_int(self.feat_val(feat, "TYPE")) == 2
            and self.to_int(self.feat_val(feat, "ROAD_TYPE")) == 2
            and self.to_int(self.feat_val(feat, "TURN_TYPE")) == 0
        ]
        road_count = defaultdict(int)
        for feat in straight_feats:
            road_count[self.norm_id(self.feat_val(feat, "ROAD_ID"))] += 1

        for feat in straight_feats:
            lane_id = self.norm_id(self.feat_val(feat, "ID"))
            group_count = road_count[self.norm_id(self.feat_val(feat, "ROAD_ID"))]
            speed = 30 if group_count == 1 else 50 if group_count == 2 else 70
            self.update_feature(ctx, feat, {"SPEEDLIMIT": speed})
            self.log(
                f"laneid={lane_id},speedlimit={speed}(type=2,roadtype=2,turntype=0)",
                show_bar=False,
            )
            count += 1

        # 规则 1.6：type=2 roadtype=2 且 turn!=0，按 lane ID 顺序覆盖写入
        turn_feats = [
            feat for feat in all_feats
            if self.to_int(self.feat_val(feat, "TYPE")) == 2
            and self.to_int(self.feat_val(feat, "ROAD_TYPE")) == 2
            and self.to_int(self.feat_val(feat, "TURN_TYPE"))
        ]
        turn_feats.sort(key=lambda feat: self.to_int(self.feat_val(feat, "ID")) or 0)

        for feat in turn_feats:
            lane_id = self.norm_id(self.feat_val(feat, "ID"))
            speed = self.cross_lane_speed(ctx, feat)
            if self.is_invalid_speed(speed):
                self.log(
                    f"路口laneid={lane_id},无法计算speedlimit,待补刷",
                    level="ERROR",
                    show_bar=False,
                )
                continue
            self.update_feature(ctx, feat, {"SPEEDLIMIT": speed})
            self.log(
                f"laneid={lane_id},speedlimit={speed}(type=2,roadtype=2,turntype!=0) ",
                show_bar=False,
            )
            count += 1

        count += self.refill_invalid_turn_speeds(ctx)

        ok, errors = self.commit_layer(lane_layer)
        if not ok:
            lane_layer.rollBack()
            raise RuntimeError("\n".join(errors))
        return count

    def virtual_field_empty(self, feat):
        raw = self.feat_val(feat, "VIRTUAL")
        if self.is_empty(raw):
            return True
        text = str(raw).strip()
        if text in ("0", "0.0"):
            return True
        return False

    def run_virtual(self, ctx):
        """FUN_00423610：INTERSECTION.lanes 规则 2.1 + road_id 成组规则 2.2。"""
        lane_layer = ctx["lane_layer"]
        lane_by_id = ctx["lane_by_id"]
        inter_road_set = ctx.get("inter_road_set") or set()
        self.ensure_editing(lane_layer)

        straight_by_id = {}
        turn_by_id = {}
        turn_by_from = defaultdict(list)
        road_id_lanes = defaultdict(list)

        for feat in lane_layer.getFeatures():
            lane_id = self.norm_id(self.feat_val(feat, "ID"))
            if not lane_id:
                continue
            road_id = self.norm_id(self.feat_val(feat, "ROAD_ID"))
            turn_type = self.to_int(self.feat_val(feat, "TURN_TYPE"))
            lane_dir = self.to_int(self.feat_val(feat, "LANE_DIR"))
            from_node = self.norm_id(self.feat_val(feat, "FROM_NODE"))
            to_node = self.norm_id(self.feat_val(feat, "TO_NODE"))
            travel_start_node = to_node if lane_dir == 2 else from_node
            in_inter = bool(road_id and road_id in inter_road_set)

            if turn_type == 0 or not in_inter:
                straight_by_id[lane_id] = feat
            else:
                turn_by_id[lane_id] = feat
                if travel_start_node:
                    turn_by_from[travel_start_node].append(feat)
            if road_id:
                try:
                    if int(road_id) >= 0:
                        road_id_lanes[road_id].append(feat)
                except (TypeError, ValueError):
                    road_id_lanes[road_id].append(feat)

        virtual_by_lane = {}

        # 规则 2.1：按 from_node 的 lanes 列表统计转向类型数，写到直行 lane
        for from_node in turn_by_from:
            lane_ids = self.intersection_lane_ids(ctx, from_node)
            if len(lane_ids) <= 1:
                continue
            straight_feat = None
            turn_types = set()
            for listed_id in lane_ids:
                if listed_id in straight_by_id:
                    straight_feat = straight_by_id[listed_id]
                elif listed_id in turn_by_id:
                    tt = self.to_int(self.feat_val(turn_by_id[listed_id], "TURN_TYPE"))
                    if tt:
                        turn_types.add(tt)
            if straight_feat is not None and turn_types:
                straight_id = self.norm_id(self.feat_val(straight_feat, "ID"))
                virtual_by_lane[straight_id] = len(turn_types)

        written = set()
        for lane_id, virtual_count in virtual_by_lane.items():
            feat = lane_layer.getFeature(lane_by_id[lane_id].id())
            self.update_feature(ctx, feat, {"VIRTUAL": virtual_count})
            self.log(f"laneid={lane_id},virtual={virtual_count}", show_bar=False)
            written.add(lane_id)

        # 规则 2.2：同 road_id 车道组（exe local_cc 遍历全部 road_id）
        for road_id, feats in road_id_lanes.items():
            pending = []
            any_nonempty = False
            for feat in feats:
                lane_id = self.norm_id(self.feat_val(feat, "ID"))
                if lane_id in written:
                    continue
                if self.virtual_field_empty(feat):
                    pending.append(feat)
                else:
                    any_nonempty = True
            if not pending:
                continue
            value = 0 if any_nonempty else 9
            for feat in pending:
                lane_id = self.norm_id(self.feat_val(feat, "ID"))
                self.update_feature(ctx, feat, {"VIRTUAL": value})
                self.log(f"laneid={lane_id},virtual={value}", show_bar=False)
                written.add(lane_id)

        # 规则 2.2 收尾：2.1/2.2 未覆盖的要素一律写 9（与 exe 日志 laneid=*,virtual=9 一致）
        for feat in lane_layer.getFeatures():
            lane_id = self.norm_id(self.feat_val(feat, "ID"))
            if not lane_id or lane_id in written:
                continue
            self.update_feature(ctx, feat, {"VIRTUAL": 9})
            self.log(f"laneid={lane_id},virtual=9", show_bar=False)
            written.add(lane_id)

        ok, errors = self.commit_layer(lane_layer)
        if not ok:
            lane_layer.rollBack()
            raise RuntimeError("\n".join(errors))

    def remove_all_layers(self):
        project = QgsProject.instance()
        layer_count = len(project.mapLayers())
        if layer_count == 0:
            QMessageBox.information(None, "移除所有图层", "当前工程没有已加载图层。")
            return

        answer = QMessageBox.question(
            self.iface.mainWindow(),
            "确认移除所有图层",
            f"确定要从当前工程移除全部 {layer_count} 个图层吗？\n\n此操作不会删除磁盘上的源数据文件。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        project.removeAllMapLayers()
        self.log(f"已从当前工程移除全部 {layer_count} 个图层")
        QMessageBox.information(None, "操作完成", f"已移除 {layer_count} 个图层。\n源数据文件未删除。")

    def run(self, mode):
        if mode == self.MODE_REMOVE_ALL:
            self.remove_all_layers()
            return

        self.begin_run()

        try:
            if mode == self.MODE_SET_ROAD2:
                ctx = self.load_lane_only()
                if ctx is None:
                    return
                count = self.run_set_road_type_2(ctx)
                done_text = f"ROAD_TYPE=2 设置完成！共更新 {count} 条"
            elif mode == self.MODE_SPEED:
                ctx = self.load_context()
                if ctx is None:
                    return
                count = self.run_speed(ctx)
                done_text = f"限速刷值完成！共更新 {count} 条"
            elif mode == self.MODE_VIRTUAL:
                ctx = self.load_context_virtual()
                if ctx is None:
                    return
                self.run_virtual(ctx)
                done_text = "转向个数刷值完成！"
            elif mode == self.MODE_CHECK_RIGHT_STRAIGHT:
                self.run_check_right_straight_overlap()
                return
            elif mode == "boundary_length":
                self.boundary_length.show()
                return
            elif mode == self.MODE_SHOW_ERROR_RESULTS:
                self.show_error_results()
                return
            elif mode == self.MODE_CLEAR_ALL_HIGHLIGHTS:
                self.clear_all_highlights()
                self.iface.mapCanvas().refresh()
                return
            else:
                return
        except RuntimeError as exc:
            QMessageBox.critical(None, "操作失败", str(exc))
            return

        ctx["lane_layer"].triggerRepaint()
        log_path = self.save_log_file(mode)
        log_hint = log_path or os.path.join(self.plugin_dir, "log")
        QMessageBox.information(
            None,
            "执行完成",
            f"{done_text}\n数据目录：{self.shp_dir}\n日志：{log_hint}",
        )
