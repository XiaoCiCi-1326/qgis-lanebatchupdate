# -*- coding: utf-8 -*-
"""根据解析结果修改 LANE 图层边线字段。"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

from qgis.core import QgsProject, QgsVectorLayer

from .lane_fix_excel import LaneFixAction


# 逻辑字段 → LANE 常见字段名（含 lmark 别名）
_FIELD_ALIASES = {
    "BDY_LEFT": ("BDY_LEFT", "LMARK_L", "lmark_l"),
    "BDY_RIGHT": ("BDY_RIGHT", "LMARK_R", "lmark_r"),
    "RBDY_L": ("RBDY_L", "BDYID_L", "bdyid_l"),
    "RBDY_R": ("RBDY_R", "BDYID_R", "bdyid_r"),
    "ID": ("ID",),
    "ROAD_ID": ("ROAD_ID", "LINKID", "LINK_ID"),
    "LEFT_RVS": ("LEFT_RVS", "LEFT_RVS", "left_rvs"),
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
        return self.field_map.get(logical)

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

    def _add_ids(self, current, add_list: List[str]) -> Tuple[str, bool]:
        existing = self.split_ids(current)
        changed = False
        for mark_id in add_list:
            if mark_id and mark_id not in existing:
                existing.append(mark_id)
                changed = True
        return self._join_ids(existing), changed

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

    def _classify_move_ids(self, from_val, to_val, mark_ids: List[str]):
        """区分侧位移动与错误关联删除（如 ID 仅在目标侧出现）。"""
        from_ids = self.split_ids(from_val)
        to_ids = self.split_ids(to_val)
        move_list = []
        remove_list = []
        for mark_id in mark_ids:
            if not mark_id:
                continue
            in_from = mark_id in from_ids
            in_to = mark_id in to_ids
            if in_from:
                move_list.append(mark_id)
            elif in_to:
                remove_list.append(mark_id)
        return move_list, remove_list

    def _apply_field_move(self, feat, field_from, field_to, mark_ids):
        """单字段或成对字段移动边线 ID；不在源侧但在目标侧则改为删除。"""
        changed_any = False
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
            move_list, remove_list = self._classify_move_ids(
                feat[actual_from], feat[actual_to], mark_ids
            )
            cur_from = feat[actual_from]
            cur_to = feat[actual_to]
            changed = False
            if move_list:
                cur_from, cur_to, moved = self._move_ids(cur_from, cur_to, move_list)
                changed = changed or moved
            if remove_list:
                cur_to, removed = self._remove_ids(cur_to, remove_list)
                changed = changed or removed
            if not changed:
                continue
            feat[actual_from] = cur_from if cur_from else None
            feat[actual_to] = cur_to if cur_to else None
            changed_any = True
        return changed_any

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

        if not self.lane_layer.startEditing():
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

                if not action.mark_ids and action.action != "skip":
                    stats["skipped"] += 1
                    self.log(f"跳过(无边线ID): {action.source_text[:80]}", show_bar=False)
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
                    changed = False
                    if action.action == "add":
                        new_val, changed = self._add_ids(feat[target_field], action.mark_ids)
                        if changed:
                            feat[target_field] = new_val if new_val else None
                    elif action.action == "remove":
                        new_val, changed = self._remove_ids(feat[target_field], action.mark_ids)
                        if changed:
                            feat[target_field] = new_val if new_val else None
                    elif action.action == "move":
                        changed = self._apply_field_move(
                            feat,
                            action.target_field,
                            action.target_field_to,
                            action.mark_ids,
                        )
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

                    self.lane_layer.updateFeature(feat)
                    touched.add(fid)
                    stats["applied"] += 1
                    if action.action == "move":
                        self.log(
                            f"laneid={action.match_value} move/remove {action.mark_ids} "
                            f"{action.target_field}->{action.target_field_to} OK",
                            show_bar=False,
                        )
                    else:
                        self.log(
                            f"laneid={action.match_value} {target_field} "
                            f"{action.action} {action.mark_ids} OK",
                            show_bar=False,
                        )

            if not self.lane_layer.commitChanges():
                errors = "; ".join(self.lane_layer.commitErrors())
                self.lane_layer.rollBack()
                raise RuntimeError(f"LANE 保存失败: {errors}")
        except Exception:
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

    @staticmethod
    def _find_road_link_layer():
        """从工程内查找 ROAD_LINK 图层。"""
        project = QgsProject.instance()
        for name in ("ROAD_LINK", "ROAD"):
            layers = project.mapLayersByName(name)
            for layer in layers:
                if isinstance(layer, QgsVectorLayer) and layer.isValid():
                    return layer
        return None

    def _resolve_road_link_fields(self, layer: QgsVectorLayer):
        """解析 ROAD_LINK 的 link 与 BDYID 字段名。"""
        upper = {field.name().upper(): field.name() for field in layer.fields()}
        link_field = None
        for alias in ("LINKID", "LINK_ID", "ID", "ROAD_ID"):
            if alias in upper:
                link_field = upper[alias]
                break
        bdy_l = None
        bdy_r = None
        for alias in ("BDYID_L", "RBDY_L"):
            if alias in upper:
                bdy_l = upper[alias]
                break
        for alias in ("BDYID_R", "RBDY_R"):
            if alias in upper:
                bdy_r = upper[alias]
                break
        return link_field, bdy_l, bdy_r

    def sync_road_link_rbdy(self, road_ids: List[str]) -> int:
        """将 LANE 上汇总的 RBDY_L/R 写回 ROAD_LINK 的 BDYID_L/R（质检读 link 层）。"""
        if not road_ids:
            return 0
        road_layer = self._find_road_link_layer()
        if road_layer is None:
            self.log("未加载 ROAD_LINK 图层，跳过 link 同步", show_bar=False)
            return 0

        link_field, bdy_l_field, bdy_r_field = self._resolve_road_link_fields(road_layer)
        rbdy_l = self._resolve_actual_field("RBDY_L")
        rbdy_r = self._resolve_actual_field("RBDY_R")
        missing = [
            name
            for name, val in (
                ("link", link_field),
                ("BDYID_L", bdy_l_field),
                ("BDYID_R", bdy_r_field),
                ("LANE.RBDY_L", rbdy_l),
                ("LANE.RBDY_R", rbdy_r),
            )
            if not val
        ]
        if missing:
            self.log(f"跳过 ROAD_LINK 同步，缺少字段: {', '.join(missing)}", show_bar=False)
            return 0

        road_set = set(road_ids)
        link_to_fid = {}
        for feat in road_layer.getFeatures():
            link_id = self.norm_id(feat[link_field])
            if link_id in road_set:
                link_to_fid[link_id] = feat.id()

        if not link_to_fid:
            self.log("ROAD_LINK 中未找到待同步 link", show_bar=False)
            return 0

        if not road_layer.startEditing():
            raise RuntimeError("ROAD_LINK 图层无法进入编辑模式")

        updated = 0
        try:
            for road_id in road_ids:
                fid = link_to_fid.get(road_id)
                feat_ids = self.lane_by_road.get(road_id, [])
                if fid is None or not feat_ids:
                    continue
                union_l: List[str] = []
                union_r: List[str] = []
                for lane_fid in feat_ids:
                    lane_feat = self.lane_layer.getFeature(lane_fid)
                    union_l.extend(self.split_ids(lane_feat[rbdy_l]))
                    union_r.extend(self.split_ids(lane_feat[rbdy_r]))
                union_l = list(dict.fromkeys(union_l))
                union_r = list(dict.fromkeys(union_r))
                link_feat = road_layer.getFeature(fid)
                new_l = self._join_ids(union_l)
                new_r = self._join_ids(union_r)
                cur_l = set(self.split_ids(link_feat[bdy_l_field]))
                cur_r = set(self.split_ids(link_feat[bdy_r_field]))
                if cur_l == set(union_l) and cur_r == set(union_r):
                    continue
                link_feat[bdy_l_field] = new_l if new_l else None
                link_feat[bdy_r_field] = new_r if new_r else None
                road_layer.updateFeature(link_feat)
                updated += 1
            if not road_layer.commitChanges():
                errors = "; ".join(road_layer.commitErrors())
                road_layer.rollBack()
                raise RuntimeError(f"ROAD_LINK 同步保存失败: {errors}")
        except Exception:
            road_layer.rollBack()
            raise

        if updated:
            road_layer.triggerRepaint()
            self.log(
                f"ROAD_LINK 同步：{updated} 条 link 的 BDYID_L/R 已与 LANE 对齐",
                show_bar=False,
            )
        return updated

    def apply_all(self, actions: List[LaneFixAction], infer_road_ids: List[str]) -> Dict[str, int]:
        """多轮应用 + BDY 推断 + ROAD_LINK 同步（尽量一次刷完）。"""
        total = {
            "total": len(actions),
            "applied": 0,
            "skipped": 0,
            "not_found": 0,
            "features_updated": 0,
            "infer_updated": 0,
            "road_link_updated": 0,
            "rounds": 0,
        }
        sync_roads = list(dict.fromkeys(infer_road_ids))
        for action in actions:
            if action.match_field == "ROAD_ID" and action.match_value not in sync_roads:
                sync_roads.append(action.match_value)

        for round_no in range(1, 4):
            stats = self.apply_actions(actions)
            total["rounds"] = round_no
            for key in ("applied", "skipped", "not_found", "features_updated"):
                total[key] += stats[key]
            self._index_features()
            infer_count = self.infer_rbdy_from_bdy(infer_road_ids)
            total["infer_updated"] += infer_count
            self._index_features()
            link_count = self.sync_road_link_rbdy(sync_roads)
            total["road_link_updated"] += link_count
            self._index_features()
            if stats["applied"] == 0 and infer_count == 0 and link_count == 0:
                break
            self.log(f"第 {round_no} 轮改错完成，继续检查…", show_bar=False)
        return total

