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
            for part in re.split(r"[|,;]", str(raw))
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
                if not target_field:
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
                    old_val = feat[target_field]
                    if action.action == "add":
                        new_val, changed = self._add_ids(old_val, action.mark_ids)
                    elif action.action == "remove":
                        new_val, changed = self._remove_ids(old_val, action.mark_ids)
                    else:
                        stats["skipped"] += 1
                        continue

                    if not changed:
                        self.log(
                            f"无变化 lane={action.match_value} {target_field} "
                            f"{action.action} {action.mark_ids}",
                            show_bar=False,
                        )
                        continue

                    feat[target_field] = new_val if new_val else None
                    self.lane_layer.updateFeature(feat)
                    touched.add(fid)
                    stats["applied"] += 1
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
