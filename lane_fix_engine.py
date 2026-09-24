# -*- coding: utf-8 -*-
"""根据解析结果修改 LANE 图层边线字段。"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

from qgis.core import QgsVectorLayer

from .lane_fix_excel import LaneFixAction


# 逻辑字段 → LANE 常见字段名（含 lmark 别名）
_FIELD_ALIASES = {
    "BDY_LEFT": ("BDY_LEFT", "LMARK_L", "lmark_l", "LMARK_LEFT"),
    "BDY_RIGHT": ("BDY_RIGHT", "LMARK_R", "lmark_r", "LMARK_RIGHT"),
    "RBDY_L": ("RBDY_L", "BDYID_L", "bdyid_l"),
    "RBDY_R": ("RBDY_R", "BDYID_R", "bdyid_r"),
    "ID": ("ID",),
    "ROAD_ID": ("ROAD_ID", "LINKID", "LINK_ID"),
    "FROM_NODE": ("FROM_NODE", "FROMNODE", "FROM"),
    "TO_NODE": ("TO_NODE", "TONODE", "TO"),
    "TURN_TYPE": ("TURN_TYPE", "TURNTYPE"),
    "LEFT_RVS": ("LEFT_RVS", "left_rvs"),
    "RIGHT_RVS": ("RIGHT_RVS", "right_rvs"),
    "LEFT_FWD": ("LEFT_FWD", "left_fwd"),
    "RIGHT_FWD": ("RIGHT_FWD", "right_fwd"),
}

# SIGNAL 层字段别名
_SIGNAL_FIELD_ALIASES = {
    "ID": ("ID", "SIGNALID", "signal_id", "SIGNAL_ID", "signalid"),
    "LANES": ("LANES", "lanes", "Lanes", "LANE"),
}


class LaneFixEngine:
    """对齐 ProcessShpFiles：按 Excel 错误表批量改 LANE 边线字段。"""

    # 邻居车道补充 RBDY 时允许保留的 BOUNDARY.TYPE
    _KEEP_BOUNDARY_TYPES = {"1", "2", "5", "6"}
    # 邻居车道补充 RBDY 时排除的 BOUNDARY.TYPE
    _DROP_BOUNDARY_TYPES = {"3", "4", "7", "8", "9", "11"}

    def __init__(
        self,
        lane_layer: QgsVectorLayer,
        log_fn: Callable,
        dry_run: bool = False,
        road_layer: Optional[QgsVectorLayer] = None,
        lane_node_layer: Optional[QgsVectorLayer] = None,
        boundary_layer: Optional[QgsVectorLayer] = None,
    ):
        self.lane_layer = lane_layer
        self.road_layer = road_layer
        self.lane_node_layer = lane_node_layer
        self.boundary_layer = boundary_layer
        self.log = log_fn
        self.dry_run = dry_run
        self.field_map = self._build_field_map(lane_layer)
        self.road_field_map = self._build_road_field_map(road_layer) if road_layer else {}
        self.lane_node_field_map = (
            self._build_simple_field_map(lane_node_layer, {"ID": "ID", "LANES": "LANES"})
            if lane_node_layer
            else {}
        )
        self.boundary_field_map = (
            self._build_simple_field_map(boundary_layer, {"ID": "ID", "TYPE": "TYPE"})
            if boundary_layer
            else {}
        )
        self.lane_by_id: Dict[str, int] = {}
        self.lane_by_road: Dict[str, List[int]] = {}
        self.road_by_id: Dict[str, int] = {}
        self.lane_node_by_id: Dict[str, int] = {}
        self.boundary_by_id: Dict[str, int] = {}
        self._index_features()

    @staticmethod
    def is_empty(value) -> bool:
        if value is None:
            return True
        text = str(value).strip()
        return text in ("", "None", "NULL")

    @staticmethod
    def norm_id(value) -> str:
        if LaneFixEngine.is_empty(value):
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
    def split_ids(raw) -> List[str]:
        if LaneFixEngine.is_empty(raw):
            return []
        return [
            LaneFixEngine.norm_id(part.strip().strip("'\"[](){}"))
            for part in re.split(r"[|,;；]", str(raw))
            if LaneFixEngine.norm_id(part.strip().strip("'\"[](){}"))
        ]

    def _build_field_map(self, layer: QgsVectorLayer) -> Dict[str, str]:
        upper = {field.name().upper(): field.name() for field in layer.fields()}
        resolved = {}
        for logical, aliases in _FIELD_ALIASES.items():
            for alias in aliases:
                actual = upper.get(alias.upper())
                if actual:
                    resolved[logical] = actual
                    break
        return resolved
    
    def _build_road_field_map(self, layer: QgsVectorLayer) -> Dict[str, str]:
        """构建ROAD图层字段映射"""
        if not layer:
            return {}
        upper = {field.name().upper(): field.name() for field in layer.fields()}
        resolved = {}
        # ROAD图层字段别名
        road_aliases = {
            "ID": ("ID", "ROAD_ID", "LINKID", "LINK_ID"),
            "RBDY_L": ("RBDY_L", "BDYID_L", "bdyid_l"),
            "RBDY_R": ("RBDY_R", "BDYID_R", "bdyid_r"),
        }
        for logical, aliases in road_aliases.items():
            for alias in aliases:
                actual = upper.get(alias.upper())
                if actual:
                    resolved[logical] = actual
                    break
        return resolved

    @staticmethod
    def _build_simple_field_map(
        layer: Optional[QgsVectorLayer],
        aliases: Dict[str, Tuple[str, ...]],
    ) -> Dict[str, str]:
        """按指定别名表构建简单的「逻辑名 → 实际字段名」映射。
        用法：LANE_NODE 需要 ID / LANES，BOUNDARY 需要 ID / TYPE。
        aliases 既支持元组 ("ID", ("id", "ID2")) 也支持裸字符串 ("LANES", "lanes")。"""
        if not layer:
            return {}
        upper = {field.name().upper(): field.name() for field in layer.fields()}
        resolved = {}
        for logical, alias_list in aliases.items():
            # 兼容「裸字符串别名」：自动包成单元素元组
            if isinstance(alias_list, str):
                alias_iter = (alias_list,)
            else:
                alias_iter = alias_list
            for alias in alias_iter:
                actual = upper.get(alias.upper())
                if actual:
                    resolved[logical] = actual
                    break
        return resolved

    def _index_features(self):
        id_field = self.field_map.get("ID")
        road_field = self.field_map.get("ROAD_ID")
        for feat in self.lane_layer.getFeatures():
            if id_field:
                lane_id = self.norm_id(feat[id_field])
                if lane_id:
                    self.lane_by_id[lane_id] = feat.id()
            if road_field:
                road_id = self.norm_id(feat[road_field])
                if road_id:
                    self.lane_by_road.setdefault(road_id, []).append(feat.id())

        # 索引ROAD图层
        if self.road_layer:
            road_id_field = self.road_field_map.get("ID")
            if road_id_field:
                for feat in self.road_layer.getFeatures():
                    road_id = self.norm_id(feat[road_id_field])
                    if road_id:
                        self.road_by_id[road_id] = feat.id()

        # 索引 LANE_NODE：按 ID 找节点 → 读 LANES 关联
        if self.lane_node_layer:
            node_id_field = self.lane_node_field_map.get("ID")
            if node_id_field:
                for feat in self.lane_node_layer.getFeatures():
                    nid = self.norm_id(feat[node_id_field])
                    if nid:
                        self.lane_node_by_id[nid] = feat.id()

        # 索引 BOUNDARY：按 ID 找 → 读 TYPE 过滤
        if self.boundary_layer:
            bdy_id_field = self.boundary_field_map.get("ID")
            if bdy_id_field:
                for feat in self.boundary_layer.getFeatures():
                    bid = self.norm_id(feat[bdy_id_field])
                    if bid:
                        self.boundary_by_id[bid] = feat.id()

    def _resolve_actual_field(self, logical: str) -> Optional[str]:
        # 先按逻辑名查
        result = self.field_map.get(logical)
        if result:
            return result
        # 再反向查别名表：target_field 本身可能是别名（如 LMARK_R）
        upper = {field.name().upper(): field.name() for field in self.lane_layer.fields()}
        for name_upper, actual in upper.items():
            for logical_key, aliases in _FIELD_ALIASES.items():
                if name_upper in (a.upper() for a in aliases):
                    return actual
        return None

    def _find_feature_ids(self, action: LaneFixAction) -> List[int]:
        if action.match_field == "ID":
            fid = self.lane_by_id.get(action.match_value)
            return [fid] if fid is not None else []
        if action.match_field == "ROAD_ID":
            return list(self.lane_by_road.get(action.match_value, []))
        return []

    @staticmethod
    def _join_ids(ids: List[str]) -> str:
        return "|".join(ids)

    def _add_ids(self, current, add_list: List[str], prepend: bool = False) -> Tuple[str, bool]:
        existing = self.split_ids(current)
        changed = False
        for mark_id in add_list:
            if mark_id and mark_id not in existing:
                if prepend:
                    existing.insert(0, mark_id)
                else:
                    existing.append(mark_id)
                changed = True
        return self._join_ids(existing), changed

    @staticmethod
    def _swap_ids(current, id_a: str, id_b: str) -> Tuple[str, bool]:
        if LaneFixEngine.is_empty(current):
            return "", False
        existing = LaneFixEngine.split_ids(current)
        if id_a not in existing or id_b not in existing:
            return LaneFixEngine._join_ids_static(existing), False
        idx_a, idx_b = existing.index(id_a), existing.index(id_b)
        if idx_a == idx_b:
            return LaneFixEngine._join_ids_static(existing), False
        existing[idx_a], existing[idx_b] = existing[idx_b], existing[idx_a]
        return LaneFixEngine._join_ids_static(existing), True

    @staticmethod
    def _join_ids_static(ids: List[str]) -> str:
        return "|".join(ids)

    def _remove_ids(self, current, remove_list: List[str]) -> Tuple[str, bool]:
        existing = self.split_ids(current)
        remove_set = set(remove_list)
        new_ids = [item for item in existing if item not in remove_set]
        changed = len(new_ids) != len(existing)
        return self._join_ids(new_ids), changed

    def _move_ids(self, from_val, to_val, move_list: List[str]):
        from_ids = self.split_ids(from_val)
        to_ids = self.split_ids(to_val)
        changed = False
        remove_set = set(move_list)
        new_from = [item for item in from_ids if item not in remove_set]
        if len(new_from) != len(from_ids):
            changed = True
        for mark_id in move_list:
            if mark_id and mark_id not in to_ids:
                to_ids.append(mark_id)
                changed = True
        return self._join_ids(new_from), self._join_ids(to_ids), changed

    # move RBDY 时同步 lmark（BDY_LEFT/BDY_RIGHT）
    _LMARK_SYNC = {
        "RBDY_L": ("BDY_LEFT", "BDY_RIGHT"),
        "RBDY_R": ("BDY_RIGHT", "BDY_LEFT"),
        "BDY_LEFT": ("RBDY_L", "RBDY_R"),
        "BDY_RIGHT": ("RBDY_R", "RBDY_L"),
    }

    def _apply_field_move(self, feat, field_from, field_to, mark_ids):
        """单字段或成对字段移动边线 ID，返回需要写入的改动 dict {field_name: new_val}。"""
        changes = {}  # {actual_field_name: new_val}
        pairs = [(field_from, field_to)]
        sync = self._LMARK_SYNC.get(field_from)
        if sync:
            src_lmark, dst_lmark = sync
            if self._resolve_actual_field(src_lmark) and self._resolve_actual_field(dst_lmark):
                pairs.append((src_lmark, dst_lmark))

        for logical_from, logical_to in pairs:
            actual_from = self._resolve_actual_field(logical_from)
            actual_to = self._resolve_actual_field(logical_to)
            if not actual_from or not actual_to:
                continue
            new_from, new_to, changed = self._move_ids(
                feat[actual_from], feat[actual_to], mark_ids
            )
            if not changed:
                continue
            if new_from:
                changes[actual_from] = new_from
            if new_to:
                changes[actual_to] = new_to
        return changes

    def _fill_empty_rbdy_from_lrvs(self, road_id: str, logical_rbdy: str) -> int:
        """
        RBDY_L/R 为空时推断补全（Excel边线改错使用），五级递进策略：
        - RBDY_L:
          1. LEFT_RVS → 对向车道 RBDY_R
          2. RIGHT_RVS → 对向车道 RBDY_R
          3. LEFT_FWD → 同向车道 RBDY_L
          4. RIGHT_FWD → 同向车道 RBDY_L
          5. 本车道 BDY_LEFT 兜底
        - RBDY_R:
          1. RIGHT_RVS → 对向车道 RBDY_L
          2. LEFT_RVS → 对向车道 RBDY_L
          3. RIGHT_FWD → 同向车道 RBDY_R
          4. LEFT_FWD → 同向车道 RBDY_R
          5. 本车道 BDY_RIGHT 兜底
        """
        if logical_rbdy == "RBDY_L":
            strategies = [
                ("LEFT_RVS", "RBDY_R"),    # 1. LEFT_RVS → 对向车道 RBDY_R
                ("RIGHT_RVS", "RBDY_R"),   # 2. RIGHT_RVS → 对向车道 RBDY_R
                ("LEFT_FWD", "RBDY_L"),    # 3. LEFT_FWD → 同向车道 RBDY_L
                ("RIGHT_FWD", "RBDY_L"),   # 4. RIGHT_FWD → 同向车道 RBDY_L
            ]
            own_bdy_field = "BDY_LEFT"     # 5. 兜底用本车道 BDY_LEFT
        else:  # RBDY_R
            strategies = [
                ("RIGHT_RVS", "RBDY_L"),   # 1. RIGHT_RVS → 对向车道 RBDY_L
                ("LEFT_RVS", "RBDY_L"),    # 2. LEFT_RVS → 对向车道 RBDY_L
                ("RIGHT_FWD", "RBDY_R"),   # 3. RIGHT_FWD → 同向车道 RBDY_R
                ("LEFT_FWD", "RBDY_R"),     # 4. LEFT_FWD → 同向车道 RBDY_R
            ]
            own_bdy_field = "BDY_RIGHT"    # 5. 兜底用本车道 BDY_RIGHT

        rbdy_field = self._resolve_actual_field(logical_rbdy)
        if not rbdy_field:
            self.log(f"[fill_from_lrvs] 跳过：RBDY 字段不存在: {logical_rbdy}", show_bar=False)
            return 0

        feat_ids = self.lane_by_road.get(road_id, [])
        if not feat_ids:
            self.log(f"[fill_from_lrvs] 跳过：未找到 ROAD_ID={road_id} 的车道", show_bar=False)
            return 0

        if not self.lane_layer.isEditable() and not self.lane_layer.startEditing():
            self.log(f"[fill_from_lrvs] 跳过：无法开启图层编辑", show_bar=False)
            return 0
        updated = 0
        try:
            for fid in feat_ids:
                feat = self.lane_layer.getFeature(fid)
                if not self.is_empty(feat[rbdy_field]):
                    continue

                lane_id = self.norm_id(feat['ID'])
                filled = False

                # 策略 1~4：从对向/同向车道推断
                for idx, (nav_field, target_rbdy) in enumerate(strategies, 1):
                    nav_f = self._resolve_actual_field(nav_field)
                    target_rbdy_f = self._resolve_actual_field(target_rbdy)
                    if not nav_f:
                        self.log(f"  [lane {lane_id}] 跳过：字段 {nav_field} 不存在", show_bar=False)
                        continue
                    if not target_rbdy_f:
                        self.log(f"  [lane {lane_id}] 跳过：字段 {target_rbdy} 不存在", show_bar=False)
                        continue
                    nav_ids = self.split_ids(feat[nav_f])
                    if not nav_ids:
                        self.log(f"  [lane {lane_id}] 跳过：{nav_field} 为空", show_bar=False)
                        continue
                    nav_fid = self.lane_by_id.get(nav_ids[0])
                    if nav_fid is None:
                        self.log(f"  [lane {lane_id}] 跳过：{nav_field}={nav_ids[0]} 在图层中未找到", show_bar=False)
                        continue
                    nav_feat = self.lane_layer.getFeature(nav_fid)
                    rbdy_val = nav_feat[target_rbdy_f]
                    if self.is_empty(rbdy_val):
                        self.log(f"  [lane {lane_id}] 跳过：{nav_field}={nav_ids[0]}.{target_rbdy} 为空", show_bar=False)
                        continue
                    feat[rbdy_field] = rbdy_val
                    self.lane_layer.updateFeature(feat)
                    updated += 1
                    method = f"rev{idx}" if idx <= 2 else f"fwd{idx-2}"
                    self.log(
                        f"[lane {lane_id}] {logical_rbdy}={rbdy_val} "
                        f"(←{nav_field}→{nav_ids[0]}.{target_rbdy} 推断-{method})",
                        show_bar=False,
                    )
                    filled = True
                    break

                # 策略 5：本车道 BDY 兜底
                if not filled and own_bdy_field:
                    own_bdy = self._resolve_actual_field(own_bdy_field)
                    if own_bdy:
                        bdy_val = feat[own_bdy]
                        if not self.is_empty(bdy_val):
                            feat[rbdy_field] = bdy_val
                            self.lane_layer.updateFeature(feat)
                            updated += 1
                            self.log(
                                f"[lane {lane_id}] {logical_rbdy}={bdy_val} "
                                f"(←本车道 {own_bdy} 兜底-fallback)",
                                show_bar=False,
                            )
                        else:
                            self.log(f"  [lane {lane_id}] 无法填充：{own_bdy} 也为空", show_bar=False)
                    else:
                        self.log(f"  [lane {lane_id}] 无法填充：字段 {own_bdy_field} 不存在", show_bar=False)

                # 策略 6：同 link 上其他车道 RBDY 复用
                # 一条 link 共享同一组边线 ID，任意车道有 RBDY 值时其他车道可复用
                if not filled:
                    for other_fid in feat_ids:
                        if other_fid == fid:
                            continue
                        other_feat = self.lane_layer.getFeature(other_fid)
                        other_val = other_feat[rbdy_field]
                        if not self.is_empty(other_val):
                            feat[rbdy_field] = other_val
                            self.lane_layer.updateFeature(feat)
                            updated += 1
                            self.log(
                                f"[lane {lane_id}] {logical_rbdy}={other_val} "
                                f"(←同link {lane_id}→{self.norm_id(other_feat['ID'])} RBDY 复用)",
                                show_bar=False,
                            )
                            filled = True
                            break
                    if not filled:
                        self.log(
                            f"  [lane {lane_id}] 无法填充：策略 1~6 全失败（同 link 上无有效 RBDY）",
                            show_bar=False,
                        )
                elif not filled:
                    self.log(
                        f"  [lane {lane_id}] 无法填充：策略 1~4 全失败，BDY 也为空",
                        show_bar=False,
                    )

            # 注意：不在此处 commit，由外层 apply_actions 统一保存，
            # 避免嵌套编辑会话重复提交导致 commitChanges 报"图层不可编辑"。
            if self.dry_run:
                self.lane_layer.rollBack()
        except Exception as e:
            self.lane_layer.rollBack()
            self.log(f"[fill_from_lrvs] 异常: {e}", show_bar=False)
            return 0
        return updated

    # ==================== 【问题#6】边线数量不足 专用 ====================

    def _lookup_neighbor_lane_rbdy(
        self,
        lane_id: str,
        side_node_field: str,
        logical_rbdy: str,
    ) -> List[str]:
        """
        在 lane_id 的 FROM/TO_NODE 节点处，按以下链路找候选车道，
        收集其 RBDY_L/R 的所有值作为补充来源：

          lane_id.FROM_NODE (or TO_NODE)
            → LANE_NODE[ID=node].LANES  → 多个 lane ID
              → 排除 lane_id 自身 + TURN_TYPE=4
              → 取候选 lane 的 BDY_LEFT
                → BOUNDARY[ID=BDY_LEFT].TYPE
                  → 保留 TYPE ∈ {1, 2, 5, 6}；过滤 ∈ {3, 4, 7, 8, 9, 11}
                  → 保留下的 lane 是「合格邻居」

        返回所有合格邻居 RBDY 的并集（按出现顺序，去重）。
        """
        if not (self.lane_node_layer and self.boundary_layer):
            self.log(
                f"  [lane {lane_id}] {side_node_field} 侧跳过：LANE_NODE 或 BOUNDARY 图层未加载",
                show_bar=False,
            )
            return []
        node_id_field = self.lane_node_field_map.get("ID")
        node_lanes_field = self.lane_node_field_map.get("LANES")
        bdy_id_field = self.boundary_field_map.get("ID")
        bdy_type_field = self.boundary_field_map.get("TYPE")
        lane_bdy_left_field = self.field_map.get("BDY_LEFT")
        lane_turn_field = self.field_map.get("TURN_TYPE")
        missing = []
        if not node_id_field: missing.append("LANE_NODE.ID")
        if not node_lanes_field: missing.append("LANE_NODE.LANES")
        if not bdy_id_field: missing.append("BOUNDARY.ID")
        if not bdy_type_field: missing.append("BOUNDARY.TYPE")
        if not lane_bdy_left_field: missing.append("LANE.BDY_LEFT")
        if missing:
            self.log(
                f"  [lane {lane_id}] {side_node_field} 侧跳过：缺字段 {missing}",
                level="WARN", show_bar=False,
            )
            return []

        # 当前 lane 的 FROM/TO_NODE 节点 ID
        node_id_field_lane = self.field_map.get(side_node_field)
        if not node_id_field_lane:
            self.log(
                f"  [lane {lane_id}] {side_node_field} 侧跳过：LANE 无 {side_node_field} 字段",
                level="WARN", show_bar=False,
            )
            return []
        fid_self = self.lane_by_id.get(lane_id)
        if fid_self is None:
            self.log(
                f"  [lane {lane_id}] 未在 LANE 图层找到",
                level="WARN", show_bar=False,
            )
            return []
        feat_self = self.lane_layer.getFeature(fid_self)
        node_id = self.norm_id(feat_self[node_id_field_lane])
        if not node_id:
            self.log(
                f"  [lane {lane_id}] {side_node_field} 为空",
                show_bar=False,
            )
            return []

        # 找 LANE_NODE 节点
        node_fid = self.lane_node_by_id.get(node_id)
        if node_fid is None:
            self.log(
                f"  [lane {lane_id}] {side_node_field}={node_id} 未在 LANE_NODE 中找到",
                show_bar=False,
            )
            return []
        node_feat = self.lane_node_layer.getFeature(node_fid)
        related_lane_ids = self.split_ids(node_feat[node_lanes_field])
        if not related_lane_ids:
            self.log(
                f"  [lane {lane_id}] LANE_NODE[{node_id}].LANES 为空",
                show_bar=False,
            )
            return []

        # 找这些 lane，排除自身 + TURN_TYPE=4
        candidates: List[Tuple[str, int]] = []  # (lane_id_str, feature_id)
        for rid in related_lane_ids:
            if rid == lane_id:
                continue
            cand_fid = self.lane_by_id.get(rid)
            if cand_fid is None:
                continue
            cand_feat = self.lane_layer.getFeature(cand_fid)
            if lane_turn_field:
                try:
                    turn_val = cand_feat[lane_turn_field]
                    if str(turn_val).strip() == "4":
                        continue
                except KeyError:
                    pass
            candidates.append((rid, cand_fid))

        if not candidates:
            self.log(
                f"  [lane {lane_id}] {side_node_field} 侧候选 lane 全部被排除（自身或 TURN_TYPE=4）",
                show_bar=False,
            )
            return []

        # 对每个候选 lane：用其 BDY_LEFT 找 BOUNDARY，过滤 TYPE
        kept: List[Tuple[str, int]] = []
        for rid, cand_fid in candidates:
            cand_feat = self.lane_layer.getFeature(cand_fid)
            bdy_left_ids = self.split_ids(cand_feat[lane_bdy_left_field])
            if not bdy_left_ids:
                self.log(
                    f"    候选 lane {rid} BDY_LEFT 为空，跳过",
                    show_bar=False,
                )
                continue
            # AND 语义：候选 lane 的所有 BDY_LEFT ID 都必须映射到
            # 合格 BOUNDARY（TYPE ∈ KEEP 或不在 DROP），任一不通过就丢弃整个候选。
            all_ok = True
            per_id_results: List[Tuple[str, str]] = []
            for bdy_id in bdy_left_ids:
                bdy_fid = self.boundary_by_id.get(bdy_id)
                if bdy_fid is None:
                    per_id_results.append((bdy_id, "未在 BOUNDARY 中找到"))
                    all_ok = False
                    continue
                bdy_feat = self.boundary_layer.getFeature(bdy_fid)
                type_val = str(bdy_feat[bdy_type_field]).strip()
                if type_val in self._DROP_BOUNDARY_TYPES:
                    per_id_results.append((bdy_id, f"TYPE={type_val!r} ∈ DROP"))
                    all_ok = False
                    continue
                if type_val in self._KEEP_BOUNDARY_TYPES:
                    per_id_results.append((bdy_id, f"TYPE={type_val!r} ∈ KEEP"))
                    continue
                # 其他 TYPE 也保留（保守）：例如空字符串、未知值
                # 仅在显式属于 DROP 集合时才排除
                per_id_results.append((bdy_id, f"TYPE={type_val!r} 保守通过"))
            if all_ok:
                kept.append((rid, cand_fid))
                if len(bdy_left_ids) > 1:
                    self.log(
                        f"    候选 lane {rid} 多 BDY_LEFT 全部合格：{per_id_results}",
                        show_bar=False,
                    )
            else:
                self.log(
                    f"    候选 lane {rid} 因部分 BDY_LEFT 不合格被排除（AND 语义）：{per_id_results}",
                    show_bar=False,
                )

        if not kept:
            self.log(
                f"  [lane {lane_id}] {side_node_field} 侧无合格邻居（BOUNDARY.TYPE 过滤后为空）",
                show_bar=False,
            )
            return []

        # 取每个合格邻居的 RBDY 字段，聚合去重
        rbdy_field = self.field_map.get(logical_rbdy)
        if not rbdy_field:
            return []
        result: List[str] = []
        seen: set = set()
        for rid, cand_fid in kept:
            cand_feat = self.lane_layer.getFeature(cand_fid)
            for v in self.split_ids(cand_feat[rbdy_field]):
                if v and v not in seen:
                    seen.add(v)
                    result.append(v)
        self.log(
            f"  [lane {lane_id}] {side_node_field} 侧：候选 {len(candidates)} → 合格 {len(kept)}，"
            f"聚合 RBDY={result}",
            show_bar=False,
        )
        return result

    def _fill_rbdy_from_neighbor_lanes(
        self,
        lane_id: str,
        logical_rbdy: str,
    ) -> Tuple[bool, int]:
        """
        【问题#6】RBDY 数量不足的修复入口：

        1. 清空目标 lane 的 RBDY 字段
        2. 分别从 FROM_NODE 侧和 TO_NODE 侧的 LANE_NODE.LANES 出发，
           经过 TURN_TYPE=4 与 BOUNDARY.TYPE 过滤后，聚合邻居的 RBDY 值
        3. 把两侧聚合结果拼到目标 lane 的 RBDY 上（按 FROM → TO 顺序拼接）

        返回 (success, applied_count)
        """
        if logical_rbdy not in ("RBDY_L", "RBDY_R"):
            self.log(
                f"[fill_from_neighbor_rbdy] 不支持的目标字段: {logical_rbdy}",
                level="ERROR", show_bar=False,
            )
            return False, 0

        if self.lane_node_layer is None or self.boundary_layer is None:
            self.log(
                "[fill_from_neighbor_rbdy] 缺少 LANE_NODE 或 BOUNDARY 图层，跳过",
                level="WARN", show_bar=False,
            )
            return False, 0

        fid = self.lane_by_id.get(lane_id)
        if fid is None:
            self.log(
                f"[fill_from_neighbor_rbdy] 未找到车道 ID={lane_id}",
                level="WARN", show_bar=False,
            )
            return False, 0

        # 进入编辑模式（外部已开则保持）
        was_editing = self.lane_layer.isEditable()
        if not was_editing and not self.lane_layer.startEditing():
            self.log(
                f"[fill_from_neighbor_rbdy] LANE 图层无法进入编辑模式",
                level="ERROR", show_bar=False,
            )
            return False, 0

        try:
            # 1) 收集 FROM/TO 两侧邻居的 RBDY 值
            from_values = self._lookup_neighbor_lane_rbdy(
                lane_id, "FROM_NODE", logical_rbdy
            )
            to_values = self._lookup_neighbor_lane_rbdy(
                lane_id, "TO_NODE", logical_rbdy
            )
            merged: List[str] = []
            seen: set = set()
            for v in from_values + to_values:
                if v and v not in seen:
                    seen.add(v)
                    merged.append(v)

            rbdy_field = self.field_map.get(logical_rbdy)
            feat = self.lane_layer.getFeature(fid)
            old_val = feat[rbdy_field]
            new_val = "|".join(merged) if merged else None

            self.log(
                f"[fill_from_neighbor_rbdy] lane {lane_id} {logical_rbdy}: "
                f"清空 {old_val!r} → 写入 {new_val!r} (FROM={len(from_values)}, TO={len(to_values)})",
                show_bar=False,
            )

            if not merged:
                # 两侧都没找到合格邻居：不动原值（避免把「数量不足」改
                # 成「为空」，否则数据更糟）。只记录日志供定位。
                self.log(
                    f"[fill_from_neighbor_rbdy] lane {lane_id} {logical_rbdy}: "
                    f"两侧均无合格邻居，保留原值 {old_val!r} 不动",
                    show_bar=False,
                )
                return False, 0

            # 2) 写入：清空原值再设新值（用 changeAttributeValue 避免 updateFeature 在 shapefile 上写盘失败）
            if old_val == new_val:
                self.log(
                    f"  值未变化，跳过写入",
                    show_bar=False,
                )
                return True, 0
            self.lane_layer.changeAttributeValue(
                fid, feat.fieldNameIndex(rbdy_field), new_val
            )
            # 同步写入 BDY_RIGHT：填入 RBDY_R 后，将其值覆盖到 BDY_RIGHT（shapefile 也用 changeAttributeValue）
            bdy_right_field = self._resolve_actual_field("BDY_RIGHT")
            if logical_rbdy == "RBDY_R" and bdy_right_field:
                old_bdy = feat[bdy_right_field]
                self.lane_layer.changeAttributeValue(
                    fid, feat.fieldNameIndex(bdy_right_field), new_val
                )
                self.log(
                    f"[fill_from_neighbor_rbdy] lane {lane_id} BDY_RIGHT: "
                    f"同步 {old_bdy!r} → 写入 {new_val!r} ✓",
                    show_bar=False,
                )
            self.log(
                f"[fill_from_neighbor_rbdy] lane {lane_id} {logical_rbdy}: "
                f"清空 {old_val!r} → 写入 {new_val!r} ✓",
                show_bar=False,
            )
            # ==================== 【问题#6】边线数量不足 专用 ====================
            # 同步：把同 ROAD_ID 组内锚点车道的 4 个 BDY/RBDY 字段覆盖到其他车道
            # 例如 lane 4046501 与 4046502 同 ROAD_ID=4046501，修复 4046501 后
            # 把它的 BDY_LEFT/BDY_RIGHT/RBDY_L/RBDY_R 也写到 4046502 上。
            self._sync_bdy_rbdy_to_link_group(lane_id)
            # ==================== 【问题#6】边线数量不足 专用 结束 ====================
            return True, 1
        except Exception as exc:
            self.log(
                f"[fill_from_neighbor_rbdy] 异常: {exc}",
                level="ERROR", show_bar=False,
            )
            return False, 0

    def scan_and_fill_all_empty_rbdy(self) -> Dict[str, int]:
        """
        全量扫描所有 lane，对 RBDY_L/R 为空的字段按五级策略补全。
        """
        rbdy_l_field = self._resolve_actual_field("RBDY_L")
        rbdy_r_field = self._resolve_actual_field("RBDY_R")
        if not (rbdy_l_field and rbdy_r_field):
            return {"rev1": 0, "rev2": 0, "fwd1": 0, "fwd2": 0, "fallback": 0}

        result = {"rev1": 0, "rev2": 0, "fwd1": 0, "fwd2": 0, "fallback": 0}
        was_editing = self.lane_layer.isEditable()
        if not was_editing and not self.lane_layer.startEditing():
            return result

        try:
            for feat in self.lane_layer.getFeatures():
                # RBDY_L
                if self.is_empty(feat[rbdy_l_field]):
                    filled, method = self._try_fill_rbdy(feat, "RBDY_L")
                    if filled:
                        self.lane_layer.updateFeature(feat)
                        result[method] += 1
                        self.log(
                            f"全量补RBDY laneid={self.norm_id(feat['ID'])} "
                            f"RBDY_L={feat[rbdy_l_field]} ({method})",
                            show_bar=False,
                        )
                # RBDY_R
                if self.is_empty(feat[rbdy_r_field]):
                    filled, method = self._try_fill_rbdy(feat, "RBDY_R")
                    if filled:
                        self.lane_layer.updateFeature(feat)
                        result[method] += 1
                        self.log(
                            f"全量补RBDY laneid={self.norm_id(feat['ID'])} "
                            f"RBDY_R={feat[rbdy_r_field]} ({method})",
                            show_bar=False,
                        )

            if not was_editing and not self.lane_layer.commitChanges():
                self.lane_layer.rollBack()
                return {"rev1": 0, "rev2": 0, "fwd1": 0, "fwd2": 0, "fallback": 0}
        except Exception:
            if not was_editing:
                self.lane_layer.rollBack()
            return {"rev1": 0, "rev2": 0, "fwd1": 0, "fwd2": 0, "fallback": 0}

        total = sum(result.values())
        self.log(
            f"[全量补RBDY] 完成: 共填充 {total} 条 "
            f"(rev1={result['rev1']} rev2={result['rev2']} "
            f"fwd1={result['fwd1']} fwd2={result['fwd2']} fallback={result['fallback']})",
            show_bar=False,
        )
        return result

    def _try_fill_rbdy(self, feat, logical_rbdy: str):
        """
        对单个 feature 尝试填充指定 RBDY 字段。
        返回 (filled: bool, method: str)  filled=True 时 feat 已被修改。

        五级递进策略：
        - RBDY_L:
          1. LEFT_RVS → 对向车道 RBDY_R
          2. RIGHT_RVS → 对向车道 RBDY_R
          3. LEFT_FWD → 同向车道 RBDY_L
          4. RIGHT_FWD → 同向车道 RBDY_L
          5. 本车道 BDY_LEFT 兜底
        - RBDY_R:
          1. RIGHT_RVS → 对向车道 RBDY_L
          2. LEFT_RVS → 对向车道 RBDY_L
          3. RIGHT_FWD → 同向车道 RBDY_R
          4. LEFT_FWD → 同向车道 RBDY_R
          5. 本车道 BDY_RIGHT 兜底
        """
        # 策略 1~4：对向/同向车道推断
        if logical_rbdy == "RBDY_L":
            strategies = [
                ("LEFT_RVS", "RBDY_R"),    # 1. LEFT_RVS → 对向车道 RBDY_R
                ("RIGHT_RVS", "RBDY_R"),   # 2. RIGHT_RVS → 对向车道 RBDY_R
                ("LEFT_FWD", "RBDY_L"),    # 3. LEFT_FWD → 同向车道 RBDY_L
                ("RIGHT_FWD", "RBDY_L"),   # 4. RIGHT_FWD → 同向车道 RBDY_L
            ]
            own_bdy_field = "BDY_LEFT"     # 5. 兜底用本车道 BDY_LEFT
        else:  # RBDY_R
            strategies = [
                ("RIGHT_RVS", "RBDY_L"),   # 1. RIGHT_RVS → 对向车道 RBDY_L
                ("LEFT_RVS", "RBDY_L"),    # 2. LEFT_RVS → 对向车道 RBDY_L
                ("RIGHT_FWD", "RBDY_R"),   # 3. RIGHT_FWD → 同向车道 RBDY_R
                ("LEFT_FWD", "RBDY_R"),     # 4. LEFT_FWD → 同向车道 RBDY_R
            ]
            own_bdy_field = "BDY_RIGHT"    # 5. 兜底用本车道 BDY_RIGHT

        rbdy_f = self._resolve_actual_field(logical_rbdy)

        # 策略 1~4：从对向/同向车道推断
        for idx, (nav_field, target_rbdy) in enumerate(strategies, 1):
            nav_f = self._resolve_actual_field(nav_field)
            target_rbdy_f = self._resolve_actual_field(target_rbdy)
            if not (nav_f and target_rbdy_f):
                continue
            nav_ids = self.split_ids(feat[nav_f])
            if not nav_ids:
                continue
            nav_fid = self.lane_by_id.get(nav_ids[0])
            if nav_fid is None:
                continue
            nav_feat = self.lane_layer.getFeature(nav_fid)
            rbdy_val = nav_feat[target_rbdy_f]
            if self.is_empty(rbdy_val):
                continue
            feat[rbdy_f] = rbdy_val
            # 同步：当 RBDY_R 写入时，把 BDY_RIGHT 覆盖成同样的值
            self._sync_bdy_from_rbdy(feat, logical_rbdy, rbdy_val)
            method = f"rev{idx}" if idx <= 2 else f"fwd{idx-2}"
            return True, method

        # 策略 5：本车道 BDY 兜底
        own_bdy_f = self._resolve_actual_field(own_bdy_field)
        if own_bdy_f:
            bdy_val = feat[own_bdy_f]
            if not self.is_empty(bdy_val):
                feat[rbdy_f] = bdy_val
                # 兜底本身就是 BDY 写 RBDY，BDY 已对齐，无需再同步
                return True, "fallback"

        # 策略 6：同 link 上其他车道 RBDY 复用
        # 同 link 上多条车道共享同一组边线 ID，任意车道有 RBDY 值即可复用
        road_id = self.norm_id(feat[self.field_map.get("ROAD_ID")]) if self.field_map.get("ROAD_ID") else None
        if road_id:
            other_fids = self.lane_by_road.get(road_id, [])
            fid_self = feat.id()
            for other_fid in other_fids:
                if other_fid == fid_self:
                    continue
                other_feat = self.lane_layer.getFeature(other_fid)
                if not other_feat.isValid():
                    continue
                other_val = other_feat[rbdy_f]
                if not self.is_empty(other_val):
                    feat[rbdy_f] = other_val
                    # 同步：当 RBDY_R 写入时，把 BDY_RIGHT 覆盖成同样的值
                    self._sync_bdy_from_rbdy(feat, logical_rbdy, other_val)
                    return True, "link_share"

        return False, ""

    def _sync_bdy_from_rbdy(self, feat, logical_rbdy: str, new_val):
        """
        当 RBDY_R 被填入时，把 BDY_RIGHT 覆盖为同样的值（与原 _LMARK_SYNC 区别：这里是覆盖，不是并入）。
        仅作用于 RBDY_R（与 BDY_RIGHT 配对）。
        """
        if logical_rbdy != "RBDY_R":
            return
        bdy_right_field = self._resolve_actual_field("BDY_RIGHT")
        if not bdy_right_field:
            return
        old_bdy = feat[bdy_right_field]
        if old_bdy == new_val:
            return
        # 直接写 feat[...]；调用方最后会 updateFeature 上盘（scan_and_fill_all_empty_rbdy 走 updateFeature 路径）
        feat[bdy_right_field] = new_val

    def _sync_bdy_rbdy_to_link_group(self, primary_lane_id: str) -> int:
        """
        【同 ROAD_ID 同步】把同 ROAD_ID 组内「锚点车道」的
        BDY_LEFT / BDY_RIGHT / RBDY_L / RBDY_R 四个字段覆盖到组内所有其他车道上。

        锚点选取规则：
        1. 优先 lane ID == ROAD_ID 的「主车道」（数据模型里 ROAD 本身的车道）
        2. 兜底取 lane ID 数值最小的车道

        用途：例如 lane 4046501 与 lane 4046502 都 ROAD_ID=4046501 时，
        两条车道的 BDY_LEFT/BDY_RIGHT/RBDY_L/RBDY_R 应保持一致；
        修复某一条车道后，自动把它的 4 字段覆盖到同 ROAD 的其他车道。

        调用方：`_fill_rbdy_from_neighbor_lanes` / `_try_fill_rbdy` 在写入成功后调用。
        返回实际写入的车道数（不含锚点自身）。
        """
        road_field = self.field_map.get("ROAD_ID")
        id_field = self.field_map.get("ID")
        if not (road_field and id_field):
            return 0

        primary_fid = self.lane_by_id.get(primary_lane_id)
        if primary_fid is None:
            return 0
        primary_feat = self.lane_layer.getFeature(primary_fid)
        if not primary_feat.isValid():
            return 0
        road_id = self.norm_id(primary_feat[road_field])
        if not road_id:
            return 0

        group_fids = self.lane_by_road.get(road_id, [])
        if len(group_fids) < 2:
            return 0

        # 收集组内所有 (fid, norm_lane_id) 对
        group_members: List[Tuple[int, str]] = []
        for fid in group_fids:
            feat = self.lane_layer.getFeature(fid)
            if not feat.isValid():
                continue
            norm_id = self.norm_id(feat[id_field])
            if norm_id:
                group_members.append((fid, norm_id))
        if len(group_members) < 2:
            return 0

        # 锚点：优先 lane ID == ROAD_ID，否则按 lane ID 数值升序
        anchor_fid: Optional[int] = None
        anchor_id: Optional[str] = None
        for fid, lid in group_members:
            if lid == road_id:
                anchor_fid = fid
                anchor_id = lid
                break
        if anchor_fid is None:
            def _key(lid: str):
                try:
                    return (0, int(lid))
                except (TypeError, ValueError):
                    return (1, lid)
            group_members.sort(key=lambda x: _key(x[1]))
            anchor_fid, anchor_id = group_members[0]

        anchor_feat = self.lane_layer.getFeature(anchor_fid)
        if not anchor_feat.isValid():
            return 0

        # 解析要同步的 4 个字段（按逻辑名 → 实际字段名）
        sync_pairs: List[Tuple[str, object]] = []  # [(actual_field, anchor_val), ...]
        for logical in ("BDY_LEFT", "BDY_RIGHT", "RBDY_L", "RBDY_R"):
            actual = self._resolve_actual_field(logical)
            if actual:
                sync_pairs.append((actual, anchor_feat[actual]))
        if not sync_pairs:
            return 0

        # 同步到所有非锚点车道（用 changeAttributeValue 写盘）
        other_members = [(fid, lid) for fid, lid in group_members if fid != anchor_fid]
        synced_count = 0
        synced_ids: List[str] = []
        for other_fid, other_id in other_members:
            other_feat = self.lane_layer.getFeature(other_fid)
            if not other_feat.isValid():
                continue
            any_changed = False
            for actual_field, anchor_val in sync_pairs:
                new_val = anchor_val if not self.is_empty(anchor_val) else None
                cur = other_feat[actual_field]
                cur_norm = None if self.is_empty(cur) else cur
                if cur_norm == new_val:
                    continue
                self.lane_layer.changeAttributeValue(
                    other_fid,
                    self.lane_layer.fields().indexFromName(actual_field),
                    new_val,
                )
                any_changed = True
            if any_changed:
                synced_count += 1
                synced_ids.append(other_id)

        if synced_count:
            self.log(
                f"[sync_link_group] ROAD_ID={road_id} 锚点 lane={anchor_id}: "
                f"已把 BDY_LEFT/BDY_RIGHT/RBDY_L/RBDY_R 4 字段覆盖到 {synced_count} 条同 ROAD 车道 "
                f"({', '.join(synced_ids)})",
                show_bar=False,
            )
        return synced_count

    def apply_actions(self, actions: List[LaneFixAction]) -> Dict[str, int]:
        """执行改错，返回统计。"""
        stats = {
            "total": len(actions),
            "applied": 0,
            "skipped": 0,
            "not_found": 0,
            "features_updated": 0,
        }
        required = ("ID", "BDY_LEFT", "BDY_RIGHT", "RBDY_L", "RBDY_R")
        missing = [name for name in required if name not in self.field_map]
        if missing:
            raise RuntimeError(f"LANE 缺少字段: {', '.join(missing)}")

        was_editing = self.lane_layer.isEditable()
        if not was_editing and not self.lane_layer.startEditing():
            raise RuntimeError("LANE 图层无法进入编辑模式")

        touched = set()
        try:
            for action in actions:
                if action.action == "skip":
                    stats["skipped"] += 1
                    self.log(
                        f"跳过(需手动): {action.source_text[:80]} {action.note}".strip(),
                        show_bar=False,
                    )
                    continue

                # 质检规则：LANE_MARKING marktype=11。全局扫描 LANE 的两侧
                # RBDY 字段并只移除指定 ID，保留其它关联及分隔符结构。
                if action.action == "remove_mark_global":
                    changed_count = 0
                    scanned_count = 0
                    field_names = []
                    value_samples = []
                    for logical in ("RBDY_L", "RBDY_R"):
                        resolved = self._resolve_actual_field(logical)
                        if resolved:
                            field_names.append(resolved)
                    self.log(
                        f"全局移除开始: mark_ids={action.mark_ids}, fields={field_names}, "
                        f"lane_features={self.lane_layer.featureCount()}", show_bar=False
                    )
                    if not field_names:
                        self.log("全局移除失败: 未解析到 RBDY_L/R 字段", level="ERROR", show_bar=False)
                    for feat in self.lane_layer.getFeatures():
                        scanned_count += 1
                        feature_changed = False
                        for logical in ("RBDY_L", "RBDY_R"):
                            field = self._resolve_actual_field(logical)
                            if not field:
                                continue
                            if len(value_samples) < 20 and not self.is_empty(feat[field]):
                                value_samples.append(f"fid={feat.id()} {field}={feat[field]!r}")
                            new_val, changed = self._remove_ids(feat[field], action.mark_ids)
                            if changed:
                                self.lane_layer.changeAttributeValue(
                                    feat.id(), feat.fieldNameIndex(field), new_val or None
                                )
                                feature_changed = True
                                touched.add(feat.id())
                        if feature_changed:
                            changed_count += 1
                    if changed_count:
                        stats["applied"] += changed_count
                        stats["features_updated"] += changed_count
                        self.log(
                            f"全局移除 RBDY_L/R 边线ID={action.mark_ids}，更新 {changed_count} 条 LANE",
                            show_bar=False,
                        )
                    else:
                        stats["skipped"] += 1
                        self.log(
                            f"未找到 RBDY_L/R 中的边线ID={action.mark_ids}（已扫描 {scanned_count} 条）；"
                            f"样例: {value_samples}", show_bar=False
                        )
                    continue

                target_field = self._resolve_actual_field(action.target_field)
                target_field_to = self._resolve_actual_field(action.target_field_to)
                if action.action in ("move", "copy"):
                    if not target_field or not target_field_to:
                        stats["skipped"] += 1
                        self.log(
                            f"跳过({action.action} 缺字段): "
                            f"{action.target_field}->{action.target_field_to}",
                            show_bar=False,
                        )
                        continue
                elif not target_field:
                    stats["skipped"] += 1
                    self.log(f"跳过(无字段): {action.target_field}", show_bar=False)
                    continue

                if not action.mark_ids and action.action not in ("skip", "copy", "fill_from_lrvs", "fill_from_neighbor_rbdy", "sync_from_road", "set"):
                    stats["skipped"] += 1
                    self.log(f"跳过(无边线ID): {action.source_text[:80]}", show_bar=False)
                    continue

                if action.action == "fill_from_lrvs":
                    count = self._fill_empty_rbdy_from_lrvs(
                        action.match_value, action.target_field
                    )
                    if count:
                        stats["applied"] += count
                        stats["features_updated"] += count
                    else:
                        stats["skipped"] += 1
                        self.log(
                            f"跳过(无法从对向车道补): ROAD_ID={action.match_value} "
                            f"{action.target_field} {action.source_text[:60]}",
                            show_bar=False,
                        )
                    continue

                if action.action == "fill_from_neighbor_rbdy":
                    # 【问题#6】边线数量不足：清空 RBDY，再从 FROM/TO_NODE
                    # 邻居 LANE（经 BOUNDARY.TYPE 过滤）补充
                    ok, applied_count = self._fill_rbdy_from_neighbor_lanes(
                        action.match_value, action.target_field
                    )
                    if ok:
                        stats["applied"] += max(1, applied_count)
                        stats["features_updated"] += max(1, applied_count)
                    else:
                        stats["skipped"] += 1
                        self.log(
                            f"跳过(无法从邻居车道补): lane={action.match_value} "
                            f"{action.target_field} {action.source_text[:60]}",
                            show_bar=False,
                        )
                    continue

                feat_ids = self._find_feature_ids(action)
                # 某些 SHP 的 ID 字段被导出为文本/浮点格式，按 lane ID
                # 索引可能找不到；顺序修复可退回按目标字段中两个边线 ID 定位。
                if not feat_ids and action.action == "swap" and target_field:
                    wanted = set(action.mark_ids[:2])
                    for candidate in self.lane_layer.getFeatures():
                        if wanted.issubset(set(self.split_ids(candidate[target_field]))):
                            feat_ids.append(candidate.id())
                    if feat_ids:
                        self.log(
                            f"swap 按 {target_field} 中边线ID回退定位: {action.mark_ids} -> {feat_ids}",
                            level="WARN", show_bar=False,
                        )
                if not feat_ids:
                    stats["not_found"] += 1
                    self.log(
                        f"未找到车道 {action.match_field}={action.match_value}: "
                        f"{action.source_text[:80]}",
                        show_bar=False,
                    )
                    continue

                for fid in feat_ids:
                    feat = self.lane_layer.getFeature(fid)
                    if not feat.isValid():
                        continue
                    new_val = None
                    changed = False
                    if action.action == "copy":
                        source_val = feat[target_field]
                        if not self.is_empty(source_val) and feat[target_field_to] != source_val:
                            feat[target_field_to] = source_val
                            self.lane_layer.changeAttributeValue(
                                fid, feat.fieldNameIndex(target_field_to), source_val
                            )
                            touched.add(fid)
                            stats["applied"] += 1
                            self.log(
                                f"laneid={action.match_value} {action.target_field}"
                                f"->{action.target_field_to} copy OK",
                                show_bar=False,
                            )
                        else:
                            stats["skipped"] += 1
                            self.log(
                                f"跳过(copy源为空或无变化): lane={action.match_value} "
                                f"{action.target_field}->{action.target_field_to}",
                                show_bar=False,
                            )
                        continue
                    if action.action == "add":
                        new_val, changed = self._add_ids(
                            feat[target_field], action.mark_ids, prepend=False
                        )
                        if changed:
                            feat[target_field] = new_val if new_val else None
                    elif action.action == "remove":
                        new_val, changed = self._remove_ids(feat[target_field], action.mark_ids)
                        if changed:
                            feat[target_field] = new_val if new_val else None
                    elif action.action == "swap":
                        if len(action.mark_ids) >= 2:
                            current_val = feat[target_field]
                            new_val, changed = self._swap_ids(
                                current_val, action.mark_ids[0], action.mark_ids[1]
                            )
                            if changed:
                                feat[target_field] = new_val
                                self.lane_layer.changeAttributeValue(
                                    fid,
                                    feat.fieldNameIndex(target_field),
                                    new_val,
                                )
                                touched.add(fid)
                                stats["applied"] += 1
                                self.log(
                                    f"swap OK: lane={action.match_value} {target_field} "
                                    f"{current_val!r} -> {new_val!r}",
                                    show_bar=False,
                                )
                            else:
                                self.log(
                                    f"swap 跳过: lane={action.match_value} {target_field} "
                                    f"当前值={current_val!r} 需交换={action.mark_ids} "
                                    f"(norm后={LaneFixEngine.split_ids(current_val)})",
                                    show_bar=False,
                                )
                            continue
                        else:
                            changed = False
                    elif action.action == "move":
                        field_changes = self._apply_field_move(
                            feat,
                            action.target_field,
                            action.target_field_to,
                            action.mark_ids,
                        )
                        for fname, fval in field_changes.items():
                            self.lane_layer.changeAttributeValue(fid, feat.fieldNameIndex(fname), fval)
                        if not field_changes:
                            self.log(
                                f"无变化 lane={action.match_value} {action.target_field} "
                                f"move {action.mark_ids}",
                                show_bar=False,
                            )
                            continue
                        touched.add(fid)
                        stats["applied"] += 1
                        self.log(
                            f"laneid={action.match_value} move {action.mark_ids} "
                            f"{action.target_field}->{action.target_field_to} OK",
                            show_bar=False,
                        )
                        continue
                    elif action.action == "set":
                        # 少数服从多数：查询同组（相同ROAD_ID）中的target_field值，统计出现次数，把少数改成多数
                        road_field = self._resolve_actual_field("ROAD_ID")
                        if not road_field:
                            self.log(
                                f"跳过(无ROAD_ID字段): lane={action.match_value} set {action.target_field}",
                                show_bar=False,
                            )
                            stats["skipped"] += 1
                            continue
                        
                        # 获取当前lane的ROAD_ID
                        current_road_id = self.norm_id(feat[road_field])
                        if not current_road_id:
                            self.log(
                                f"跳过(无ROAD_ID): lane={action.match_value} set {action.target_field}",
                                show_bar=False,
                            )
                            stats["skipped"] += 1
                            continue
                        
                        # 获取同组所有lane的target_field值
                        group_feat_ids = self.lane_by_road.get(current_road_id, [])
                        if len(group_feat_ids) <= 1:
                            self.log(
                                f"跳过(组内只有1条): lane={action.match_value} ROAD_ID={current_road_id}",
                                show_bar=False,
                            )
                            stats["skipped"] += 1
                            continue
                        
                        # 统计target_field值出现次数
                        value_counts = {}
                        for group_fid in group_feat_ids:
                            group_feat = self.lane_layer.getFeature(group_fid)
                            if not group_feat.isValid():
                                continue
                            field_val = self.norm_id(group_feat[target_field])
                            if field_val:  # 只统计非空值
                                value_counts[field_val] = value_counts.get(field_val, 0) + 1
                        
                        if not value_counts:
                            self.log(
                                f"跳过(组内都为空): lane={action.match_value} ROAD_ID={current_road_id} {action.target_field}",
                                show_bar=False,
                            )
                            stats["skipped"] += 1
                            continue
                        
                        # 找出出现次数最多的值（多数）
                        majority_value = max(value_counts, key=value_counts.get)
                        majority_count = value_counts[majority_value]
                        
                        # 如果当前值已经是多数，跳过
                        current_val = self.norm_id(feat[target_field])
                        if current_val == majority_value:
                            self.log(
                                f"无需改: lane={action.match_value} {action.target_field}={current_val} 已是多数({majority_count}/{len(group_feat_ids)})",
                                show_bar=False,
                            )
                            continue
                        
                        # 改成多数值
                        new_val = majority_value
                        changed = True
                        self.lane_layer.changeAttributeValue(fid, feat.fieldNameIndex(target_field), new_val)
                        touched.add(fid)
                        stats["applied"] += 1
                        self.log(
                            f"set OK: lane={action.match_value} {target_field} {current_val!r} -> {new_val!r} (多数={majority_count}/{len(group_feat_ids)})",
                            show_bar=False,
                        )
                        continue
                    elif action.action == "sync_from_road":
                        # 从ROAD图层同步RBDY字段到LANE的BDY字段
                        if not self.road_layer:
                            self.log(
                                f"跳过(无ROAD图层): lane={action.match_value} sync_from_road",
                                show_bar=False,
                            )
                            stats["skipped"] += 1
                            continue
                        
                        # 获取ROAD_ID
                        road_field = self._resolve_actual_field("ROAD_ID")
                        if not road_field:
                            self.log(
                                f"跳过(无ROAD_ID字段): lane={action.match_value}",
                                show_bar=False,
                            )
                            stats["skipped"] += 1
                            continue
                        
                        current_road_id = self.norm_id(feat[road_field])
                        if not current_road_id:
                            self.log(
                                f"跳过(ROAD_ID为空): lane={action.match_value}",
                                show_bar=False,
                            )
                            stats["skipped"] += 1
                            continue
                        
                        # 从ROAD图层获取RBDY值
                        road_fid = self.road_by_id.get(current_road_id)
                        if not road_fid:
                            self.log(
                                f"跳过(ROAD图层无此ID): ROAD_ID={current_road_id}",
                                show_bar=False,
                            )
                            stats["skipped"] += 1
                            continue
                        
                        road_feat = self.road_layer.getFeature(road_fid)
                        if not road_feat.isValid():
                            self.log(
                                f"跳过(ROAD要素无效): ROAD_ID={current_road_id}",
                                show_bar=False,
                            )
                            stats["skipped"] += 1
                            continue
                        
                        # 确定ROAD图层的源字段（RBDY_L或RBDY_R）
                        if target_field.endswith("LEFT") or target_field.endswith("_L") or "lmark_l" in target_field.lower():
                            road_source_field = self.road_field_map.get("RBDY_L")
                        else:
                            road_source_field = self.road_field_map.get("RBDY_R")
                        
                        if not road_source_field:
                            self.log(
                                f"跳过(ROAD图层无RBDY字段): {target_field}",
                                show_bar=False,
                            )
                            stats["skipped"] += 1
                            continue
                        
                        # 读取ROAD的RBDY值
                        road_rbdy_value = road_feat[road_source_field]
                        if self.is_empty(road_rbdy_value):
                            self.log(
                                f"跳过(ROAD的RBDY为空): ROAD_ID={current_road_id} {road_source_field}",
                                show_bar=False,
                            )
                            stats["skipped"] += 1
                            continue
                        
                        # 同步到LANE的BDY字段
                        current_val = feat[target_field]
                        normalized_road_val = str(road_rbdy_value).strip()
                        normalized_current = str(current_val).strip() if not self.is_empty(current_val) else ""
                        
                        if normalized_current == normalized_road_val:
                            self.log(
                                f"无需改: lane={action.match_value} {target_field}={normalized_current} 已与ROAD一致",
                                show_bar=False,
                            )
                            continue
                        
                        # 写入LANE图层
                        # 同步到所有同组的lane
                        group_feat_ids = self.lane_by_road.get(current_road_id, [])
                        sync_count = 0
                        for group_fid in group_feat_ids:
                            self.lane_layer.changeAttributeValue(
                                group_fid,
                                self.lane_layer.fields().indexFromName(target_field),
                                normalized_road_val
                            )
                            touched.add(group_fid)
                            sync_count += 1
                        
                        stats["applied"] += sync_count
                        self.log(
                            f"sync_from_road OK: ROAD_ID={current_road_id} {road_source_field}={normalized_road_val} -> {sync_count}条LANE.{target_field}",
                            show_bar=False,
                        )
                        continue
                    else:
                        stats["skipped"] += 1
                        continue

                    if not changed:
                        self.log(
                            f"无变化 lane={action.match_value} {action.target_field} "
                            f"{action.action} {action.mark_ids}",
                            show_bar=False,
                        )
                        continue

                    self.lane_layer.changeAttributeValue(fid, feat.fieldNameIndex(target_field), new_val)
                    touched.add(fid)
                    stats["applied"] += 1
                    self.log(
                        f"laneid={action.match_value} {target_field} "
                        f"{action.action} {action.mark_ids} OK",
                        show_bar=False,
                    )

            if not was_editing:
                if self.dry_run:
                    self.lane_layer.rollBack()
                    self.log("[dry-run] 已回滚，未写盘", show_bar=False)
                elif not self.lane_layer.commitChanges():
                    errors = "; ".join(self.lane_layer.commitErrors())
                    self.lane_layer.rollBack()
                    raise RuntimeError(f"LANE 保存失败: {errors}")
            else:
                # 外部已开启编辑模式：不要替用户 commit/rollback，保留其会话
                pass
        except Exception:
            if not was_editing:
                self.lane_layer.rollBack()
            raise

        stats["features_updated"] = len(touched)
        return stats

    def infer_rbdy_from_bdy(self, road_ids: List[str]) -> int:
        """同 link 上汇总各 lane 的 BDY_LEFT/BDY_RIGHT，补全 RBDY_L/RBDY_R 并集。"""
        if not road_ids:
            return 0
        bdy_l = self._resolve_actual_field("BDY_LEFT")
        bdy_r = self._resolve_actual_field("BDY_RIGHT")
        rbdy_l = self._resolve_actual_field("RBDY_L")
        rbdy_r = self._resolve_actual_field("RBDY_R")
        if not all([bdy_l, bdy_r, rbdy_l, rbdy_r]):
            self.log("跳过 BDY→RBDY 推断：缺少 BDY 或 RBDY 字段", show_bar=False)
            return 0

        updated = 0
        if not self.lane_layer.startEditing():
            raise RuntimeError("LANE 图层无法进入编辑模式（推断 BDY→RBDY）")

        try:
            for road_id in road_ids:
                feat_ids = self.lane_by_road.get(road_id, [])
                if not feat_ids:
                    continue
                union_l: List[str] = []
                union_r: List[str] = []
                for fid in feat_ids:
                    feat = self.lane_layer.getFeature(fid)
                    union_l.extend(self.split_ids(feat[bdy_l]))
                    union_r.extend(self.split_ids(feat[bdy_r]))
                union_l = list(dict.fromkeys(union_l))
                union_r = list(dict.fromkeys(union_r))
                if not union_l and not union_r:
                    continue
                for fid in feat_ids:
                    feat = self.lane_layer.getFeature(fid)
                    new_l, changed_l = self._add_ids(feat[rbdy_l], union_l)
                    new_r, changed_r = self._add_ids(feat[rbdy_r], union_r)
                    if not changed_l and not changed_r:
                        continue
                    if changed_l:
                        feat[rbdy_l] = new_l if new_l else None
                    if changed_r:
                        feat[rbdy_r] = new_r if new_r else None
                    self.lane_layer.updateFeature(feat)
                    updated += 1
            if not self.lane_layer.commitChanges():
                errors = "; ".join(self.lane_layer.commitErrors())
                self.lane_layer.rollBack()
                raise RuntimeError(f"BDY→RBDY 推断保存失败: {errors}")
        except Exception:
            self.lane_layer.rollBack()
            raise

        if updated:
            self.log(
                f"BDY→RBDY 推断：link {len(road_ids)} 组，更新 {updated} 条要素",
                show_bar=False,
            )
        return updated

    def apply_all(self, actions: List[LaneFixAction]) -> Dict[str, int]:
        """按 Excel 指令多轮应用（不跑 BDY 推断 / ROAD_LINK 全量同步，避免新增关联错误）。"""
        total = {
            "total": len(actions),
            "applied": 0,
            "skipped": 0,
            "not_found": 0,
            "features_updated": 0,
            "rounds": 0,
        }
        for round_no in range(1, 3):
            # swap 不是幂等操作，第二轮重复执行会把顺序交换回来。
            round_actions = (
                actions
                if round_no == 1
                else [action for action in actions if action.action != "swap"]
            )
            if not round_actions:
                break

            stats = self.apply_actions(round_actions)
            total["rounds"] = round_no
            for key in ("applied", "skipped", "not_found", "features_updated"):
                total[key] += stats[key]
            self._index_features()
            if stats["applied"] == 0:
                break

            has_next_round_actions = any(
                action.action != "swap" for action in actions
            )
            if has_next_round_actions and round_no < 2:
                self.log(f"第 {round_no} 轮改错完成，继续检查…", show_bar=False)
        return total


class GenericLayerFixer:
    """
    通用矢量图层字段修复工具。
    支持 ROAD_LINK（BDYID_L/R）、SIGNAL（LANES）等图层。
    """

    def __init__(self, layer, log_fn: Callable, dry_run: bool = False):
        self.layer = layer
        self.log = log_fn
        self.dry_run = dry_run
        self.field_map: Dict[str, str] = {}
        if layer:
            self._build_field_map()

    def _build_field_map(self):
        upper = {f.name().upper(): f.name() for f in self.layer.fields()}
        resolved = {}
        for aliases in (_FIELD_ALIASES, _SIGNAL_FIELD_ALIASES):
            for logical, alias_list in aliases.items():
                if logical in resolved:
                    continue
                for alias in alias_list:
                    actual = upper.get(alias.upper())
                    if actual:
                        resolved[logical] = actual
                        break
        self.field_map = resolved

    def _resolve(self, logical_field: str) -> str:
        return self.field_map.get(logical_field, logical_field)

    def apply_actions(self, actions: List[LaneFixAction]) -> Dict[str, int]:
        stats = {"total": len(actions), "applied": 0, "skipped": 0, "not_found": 0}
        if not self.layer:
            stats["not_found"] = len(actions)
            self.log("GenericLayerFixer: 图层未加载", level="WARN")
            return stats

        was_editing = self.layer.isEditable()
        if not was_editing and not self.layer.startEditing():
            self.log("GenericLayerFixer: 无法进入编辑模式", level="WARN")
            return stats

        touched = set()
        try:
            for action in actions:
                if action.action == "skip":
                    stats["skipped"] += 1
                    continue

                if not action.match_value:
                    stats["skipped"] += 1
                    continue

                fid = self._find_feature_id(action)
                if fid is None:
                    stats["not_found"] += 1
                    self.log(
                        f"未找到要素 {action.target_field}={action.match_value}: "
                        f"{action.source_text[:80]}", show_bar=False,
                    )
                    continue

                feat = self.layer.getFeature(fid)
                if not feat.isValid():
                    stats["not_found"] += 1
                    continue

                target_field = self._resolve(action.target_field)
                changed = False

                if action.action == "set":
                    feat[target_field] = action.mark_ids[0] if action.mark_ids else None
                    changed = True
                elif action.action == "remove":
                    new_val, changed = self._remove_ids(feat[target_field], action.mark_ids)
                    if changed:
                        feat[target_field] = new_val if new_val else None
                elif action.action == "add":
                    new_val, changed = self._add_ids(feat[target_field], action.mark_ids)
                    if changed:
                        feat[target_field] = new_val if new_val else None
                elif action.action == "move":
                    new_val, changed = self._remove_ids(feat[target_field], action.mark_ids)
                    if changed and action.target_field_to:
                        to_field = self._resolve(action.target_field_to)
                        to_existing = feat[to_field] or ""
                        merged, _ = self._add_ids(to_existing, action.mark_ids)
                        feat[to_field] = merged
                    if changed:
                        feat[target_field] = new_val if new_val else None

                if changed:
                    self.layer.updateFeature(feat)
                    touched.add(fid)
                    stats["applied"] += 1
                    self.log(
                        f"GenericLayerFixer {action.action} "
                        f"{target_field}={action.match_value} {action.mark_ids}: OK",
                        show_bar=False,
                    )
                else:
                    stats["skipped"] += 1

            if not was_editing:
                if self.dry_run:
                    self.layer.rollBack()
                elif not self.layer.commitChanges():
                    errors = "; ".join(self.layer.commitErrors())
                    self.layer.rollBack()
                    self.log(f"GenericLayerFixer 保存失败: {errors}", level="ERROR")
                    return stats
        except Exception:
            if not was_editing:
                self.layer.rollBack()
            raise

        stats["features_updated"] = len(touched)
        return stats

    def _find_feature_id(self, action: LaneFixAction) -> Optional[int]:
        for fname in (action.match_field, "ID", "LINKID", "LINK_ID", "ROAD_ID"):
            actual = self._resolve(fname)
            if actual not in self.layer.fields().names():
                continue
            for feat in self.layer.getFeatures():
                val_str = self.norm_id(feat[actual])
                if val_str == action.match_value:
                    return feat.id()
        return None

    @staticmethod
    def is_empty(value) -> bool:
        if value is None:
            return True
        text = str(value).strip()
        return text in ("", "None", "NULL")

    @staticmethod
    def norm_id(value) -> str:
        if GenericLayerFixer.is_empty(value):
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
    def split_ids(raw) -> List[str]:
        if GenericLayerFixer.is_empty(raw):
            return []
        return [
            GenericLayerFixer.norm_id(p)
            for p in re.split(r"[|,;；]", str(raw))
            if GenericLayerFixer.norm_id(p)
        ]

    @staticmethod
    def _add_ids(existing, new_ids: List[str], prepend=False) -> Tuple[str, bool]:
        if not new_ids:
            return str(existing) if existing else "", False
        existing_list = GenericLayerFixer.split_ids(existing)
        added = [nid for nid in new_ids if nid not in existing_list]
        if not added:
            return str(existing) if existing else "", False
        merged = (added + existing_list) if prepend else (existing_list + added)
        return "|".join(merged), True

    @staticmethod
    def _remove_ids(existing, to_remove: List[str]) -> Tuple[str, bool]:
        existing_list = GenericLayerFixer.split_ids(existing)
        remove_set = set(to_remove)
        new_list = [x for x in existing_list if x not in remove_set]
        if new_list == existing_list:
            return str(existing) if existing else "", False
        return "|".join(new_list), True

