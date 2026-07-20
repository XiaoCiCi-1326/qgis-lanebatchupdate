# -*- coding: utf-8 -*-
"""
车道批量刷值工具 - 对齐 UpdateShpLane v1.0.1.3
规则来源：更新日志.txt / UpdateShpLane.exe

按钮：
  限速刷值       → 规则 1.1~1.6（与原始软件一致）
  ROAD_TYPE=2    → 将 LANE 图层全部要素的 ROAD_TYPE 字段设为 2
  转向个数刷值   → VIRTUAL 规则 2.1~2.2
"""
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import QgsProject, Qgis, QgsFeatureRequest, QgsVectorLayer
from collections import defaultdict
from datetime import datetime
import os
import re


class LaneBatchUpdateTool:
    MODE_SPEED = "speed"
    MODE_SET_ROAD2 = "set_road2"
    MODE_VIRTUAL = "virtual"

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.log_lines = []
        self.shp_dir = ""
        self.field_names = {}

    def initGui(self):
        buttons = (
            (self.MODE_SPEED, "限速刷值", "icon_speed.png"),
            (self.MODE_SET_ROAD2, "ROAD_TYPE=2", "icon_road2.png"),
            (self.MODE_VIRTUAL, "转向个数刷值", "icon_virtual.png"),
        )
        for mode, label, icon_name in buttons:
            icon_path = os.path.join(self.plugin_dir, icon_name)
            action = QAction(QIcon(icon_path), label, self.iface.mainWindow())
            action.triggered.connect(lambda checked=False, m=mode: self.run(mode=m))
            self.iface.addVectorToolBarIcon(action)
            self.iface.addPluginToVectorMenu("车道处理工具", action)
            self.actions.append(action)

    def unload(self):
        for action in self.actions:
            self.iface.removeVectorToolBarIcon(action)
            self.iface.removePluginFromVectorMenu("车道处理工具", action)
        self.actions = []

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
            "ID", "TYPE", "ROAD_TYPE", "TURN_TYPE", "ROAD_ID", "FROM_NODE", "TO_NODE", "SPEEDLIMIT",
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

    def speed_from_node_lane_list(self, ctx, lane_id, node_id):
        """FUN_004226c0：在 LANE_NODE.lanes 顺序中找第一条直行车道 speedlimit。"""
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
            if (
                self.to_int(self.feat_val(other, "TYPE")) == 2
                and self.to_int(self.feat_val(other, "ROAD_TYPE")) == 2
                and self.to_int(self.feat_val(other, "TURN_TYPE")) == 0
            ):
                speed = self.to_int(self.feat_val(other, "SPEEDLIMIT"))
                if not self.is_invalid_speed(speed):
                    return speed
            if len(lane_ids) == 2 and self.to_int(self.feat_val(other, "TURN_TYPE")):
                return None
        return None

    def cross_lane_speed(self, ctx, feat):
        """FUN_004226c0 规则 1.6：from/to 节点 LANE_NODE.lanes 各取一直行限速，再取 min。"""
        lane_id = self.norm_id(self.feat_val(feat, "ID"))
        from_node = self.norm_id(self.feat_val(feat, "FROM_NODE"))
        to_node = self.norm_id(self.feat_val(feat, "TO_NODE"))
        speed_from = self.speed_from_node_lane_list(ctx, lane_id, from_node)
        speed_to = self.speed_from_node_lane_list(ctx, lane_id, to_node)
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
            elif lane_type == 1:
                speed = 25
            elif lane_type == 4:
                speed = 70
            elif lane_type == 2 and road_type == 1:
                speed = 30
            elif lane_type == 2 and road_type == 3:
                speed = 15

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

            if lane_type == 1:
                speed = 25
                log_line = f"laneid={lane_id},speedlimit={speed}(type=1,roadtype={road_type})"
            elif lane_type == 4:
                speed = 70
                log_line = f"laneid={lane_id},speedlimit={speed}(type=4,roadtype={road_type})"
            elif lane_type == 2 and road_type == 1:
                speed = 30
                log_line = f"laneid={lane_id},speedlimit={speed}(type=2,roadtype=1)"
            elif lane_type == 2 and road_type == 3:
                speed = 15
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
            from_node = self.norm_id(self.feat_val(feat, "FROM_NODE"))
            in_inter = bool(road_id and road_id in inter_road_set)

            if turn_type == 0 or not in_inter:
                straight_by_id[lane_id] = feat
            else:
                turn_by_id[lane_id] = feat
                if from_node:
                    turn_by_from[from_node].append(feat)
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

    def run(self, mode):
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
