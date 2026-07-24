# -*- coding: utf-8 -*-
"""根据解析结果修改 LANE 图层边线字段。"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

from qgis.core import QgsVectorLayer

from .lane_fix_excel import LaneFixAction


# 逻辑字段 → LANE 常见字段名（含 lmark 别名）
_FIELD_ALIASES = {
    "BDY_LEFT": ("BDY_LEFT", "LMARK_L", "lmark_l"),
    "BDY_RIGHT": ("BDY_RIGHT", "LMARK_R", "lmark_r"),
    "RBDY_L": ("RBDY_L", "BDYID_L", "bdyid_l"),
    "RBDY_R": ("RBDY_R", "BDYID_R", "bdyid_r"),
    "ID": ("ID",),
    "ROAD_ID": ("ROAD_ID", "LINKID", "LINK_ID"),
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

    def __init__(self, lane_layer: QgsVectorLayer, log_fn: Callable):
        self.lane_layer = lane_layer
        self.log = log_fn
        self.field_map = self._build_field_map(lane_layer)
        self.lane_by_id: Dict[str, int] = {}
        self.lane_by_road: Dict[str, List[int]] = {}
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
            LaneFixEngine.norm_id(part)
            for part in re.split(r"[|,;；]", str(raw))
            if LaneFixEngine.norm_id(part)
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

        if not self.lane_layer.startEditing():
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
                elif not filled:
                    self.log(f"  [lane {lane_id}] 无法填充：所有策略都失败（5条路都走不通）", show_bar=False)

            if not self.lane_layer.commitChanges():
                self.lane_layer.rollBack()
                self.log(f"[fill_from_lrvs] 保存失败", show_bar=False)
                return 0
        except Exception as e:
            self.lane_layer.rollBack()
            self.log(f"[fill_from_lrvs] 异常: {e}", show_bar=False)
            return 0
        return updated

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
            method = f"rev{idx}" if idx <= 2 else f"fwd{idx-2}"
            return True, method

        # 策略 5：本车道 BDY 兜底
        own_bdy_f = self._resolve_actual_field(own_bdy_field)
        if own_bdy_f:
            bdy_val = feat[own_bdy_f]
            if not self.is_empty(bdy_val):
                feat[rbdy_f] = bdy_val
                return True, "fallback"

        return False, ""

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

                target_field = self._resolve_actual_field(action.target_field)
                target_field_to = self._resolve_actual_field(action.target_field_to)
                if action.action == "move":
                    if not target_field or not target_field_to:
                        stats["skipped"] += 1
                        self.log(
                            f"跳过(move 缺字段): {action.target_field}->{action.target_field_to}",
                            show_bar=False,
                        )
                        continue
                elif not target_field:
                    stats["skipped"] += 1
                    self.log(f"跳过(无字段): {action.target_field}", show_bar=False)
                    continue

                if not action.mark_ids and action.action not in ("skip", "fill_from_lrvs"):
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

                feat_ids = self._find_feature_ids(action)
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
                    if action.action == "add":
                        prepend = (
                            action.target_field == "LEFT_RVS"
                            and "互挂" in (action.note or "")
                        )
                        new_val, changed = self._add_ids(
                            feat[target_field], action.mark_ids, prepend=prepend
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
                if not self.lane_layer.commitChanges():
                    errors = "; ".join(self.lane_layer.commitErrors())
                    self.lane_layer.rollBack()
                    raise RuntimeError(f"LANE 保存失败: {errors}")
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
            stats = self.apply_actions(actions)
            total["rounds"] = round_no
            for key in ("applied", "skipped", "not_found", "features_updated"):
                total[key] += stats[key]
            self._index_features()
            if stats["applied"] == 0:
                break
            self.log(f"第 {round_no} 轮改错完成，继续检查…", show_bar=False)
        return total


class GenericLayerFixer:
    """
    通用矢量图层字段修复工具。
    支持 ROAD_LINK（BDYID_L/R）、SIGNAL（LANES）等图层。
    """

    def __init__(self, layer, log_fn: Callable):
        self.layer = layer
        self.log = log_fn
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
                if not self.layer.commitChanges():
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
        return ";".join(merged), True

    @staticmethod
    def _remove_ids(existing, to_remove: List[str]) -> Tuple[str, bool]:
        existing_list = GenericLayerFixer.split_ids(existing)
        remove_set = set(to_remove)
        new_list = [x for x in existing_list if x not in remove_set]
        if new_list == existing_list:
            return str(existing) if existing else "", False
        return ";".join(new_list), True

