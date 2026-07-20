# -*- coding: utf-8 -*-
"""读取 3.16 质检导出的 Excel/CSV，解析可自动修复的边线错误。"""

from __future__ import annotations

import csv
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass
class LaneFixAction:
    """单条改错指令。"""

    action: str  # add / remove / skip / move / infer_bdy
    target_field: str
    match_field: str  # ID / ROAD_ID
    match_value: str
    mark_ids: List[str]
    source_text: str
    target_field_to: str = ""
    note: str = ""


def _norm_cell(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _row_texts(row: Iterable) -> List[str]:
    return [_norm_cell(c) for c in row if _norm_cell(c)]


def _digits_from_segment(text: str) -> List[str]:
    """从描述片段提取边线/lane ID（6 位以上数字，排除坐标小片段）。"""
    if not text:
        return []
    ids = re.findall(r"\d{6,}", text)
    return list(dict.fromkeys(ids))


def _pick_problem_cells(cells: List[str]) -> List[str]:
    """只取「问题描述」单元格，避免把 X/Y 坐标误当边线 ID。"""
    for cell in cells:
        if "【问题" in cell or "互为对方left_rvs" in cell.lower():
            return [cell]
    cands = [
        c
        for c in cells
        if re.search(r"linkid|laneid|left_rvs|缺失|错误|不应记录", c, re.I)
    ]
    return cands


def parse_error_texts(text: str) -> List[LaneFixAction]:
    """从单条问题描述解析改错动作（可返回多条，如 left_rvs 互挂）。"""
    raw = _norm_cell(text)
    if not raw or "未发现问题" in raw:
        return []

    compact = re.sub(r"\s+", " ", raw)

    # 1.1 LEFT_RVS 互挂缺失
    mutual = re.search(
        r"(\d{6,})与(\d{6,})互为对方left_rvs.*?均未被对方记录",
        compact,
        re.IGNORECASE,
    )
    if mutual:
        lane_a, lane_b = mutual.group(1), mutual.group(2)
        note = "left_rvs 互相补充"
        return [
            LaneFixAction("add", "LEFT_RVS", "ID", lane_a, [lane_b], raw, note=note),
            LaneFixAction("add", "LEFT_RVS", "ID", lane_b, [lane_a], raw, note=note),
        ]

    link_m = re.search(r"link\s*id\s*[：:\s]*(\d{6,})", compact, re.IGNORECASE)
    link_id = link_m.group(1) if link_m else None
    lane_m = re.search(r"lane\s*id\s*[=:：]?\s*(\d{6,})", compact, re.IGNORECASE)

    # 2.6 缺失边线（支持多个 ID，分号/逗号分隔）
    if link_id and "缺失了边线" in compact:
        seg = re.search(r"缺失了边线[：:\s]*(.+)", compact)
        mark_ids = _digits_from_segment(seg.group(1) if seg else compact)
        if "bdyid_r" in compact.lower() or "右侧" in compact:
            field = "RBDY_R"
        elif "bdyid_l" in compact.lower() or "左侧" in compact:
            field = "RBDY_L"
        else:
            field = "RBDY_R" if "右侧" in compact else "RBDY_L"
        if mark_ids:
            return [
                LaneFixAction(
                    "add", field, "ROAD_ID", link_id, mark_ids, raw,
                    note=f"补 {len(mark_ids)} 个边线",
                )
            ]

    # 2.5 左右侧位错误（多个边线 ID 一次移动）
    if link_id and "左右侧位错误" in compact:
        seg = re.search(
            r"关联的边线\s*id?\s*([^左右]+?)左右侧位错误",
            compact,
            re.IGNORECASE,
        )
        mark_ids = _digits_from_segment(seg.group(1) if seg else compact)
        if mark_ids:
            if "bdyid_l" in compact.lower() or "左侧" in compact:
                return [
                    LaneFixAction(
                        "move", "RBDY_L", "ROAD_ID", link_id, mark_ids, raw,
                        target_field_to="RBDY_R",
                        note=f"左右侧位：{len(mark_ids)} 个 ID 左→右",
                    )
                ]
            if "bdyid_r" in compact.lower() or "右侧" in compact:
                return [
                    LaneFixAction(
                        "move", "RBDY_R", "ROAD_ID", link_id, mark_ids, raw,
                        target_field_to="RBDY_L",
                        note=f"左右侧位：{len(mark_ids)} 个 ID 右→左",
                    )
                ]

    # 2.5/2.2 关联错误（非侧位错误）→ 从对应侧删除
    if link_id and "关联的边线" in compact and "错误" in compact and "左右侧位错误" not in compact:
        seg = re.search(r"关联的边线\s*id?\s*([^错]+?)错误", compact, re.IGNORECASE)
        mark_ids = _digits_from_segment(seg.group(1) if seg else compact)
        if mark_ids:
            if "bdyid_r" in compact.lower() or "右侧" in compact:
                return [
                    LaneFixAction(
                        "remove", "RBDY_R", "ROAD_ID", link_id, mark_ids, raw,
                        note="删除错误关联",
                    )
                ]
            if "bdyid_l" in compact.lower() or "左侧" in compact:
                return [
                    LaneFixAction(
                        "remove", "RBDY_L", "ROAD_ID", link_id, mark_ids, raw,
                        note="删除错误关联",
                    )
                ]

    # lane 级 lmark 左右侧位
    if lane_m and "左右侧位错误" in compact:
        seg = re.search(
            r"关联的边线\s*id?\s*([^左右]+?)左右侧位错误",
            compact,
            re.IGNORECASE,
        )
        mark_ids = _digits_from_segment(seg.group(1) if seg else compact)
        lane_id = lane_m.group(1)
        if mark_ids and ("lmark_l" in compact.lower() or "左侧" in compact):
            return [
                LaneFixAction(
                    "move", "BDY_LEFT", "ID", lane_id, mark_ids, raw,
                    target_field_to="BDY_RIGHT",
                )
            ]

    # 不应记录边线
    if link_id and "不应记录边线" in compact:
        seg = re.search(r"lanemark\s*id\s*[=:：]?\s*([\d,，；;\s]+)", compact, re.I)
        mark_ids = _digits_from_segment(seg.group(1) if seg else compact)
        if mark_ids:
            field = "RBDY_L" if "bdyid_l" in compact.lower() or "左侧" in compact else "RBDY_R"
            return [LaneFixAction("remove", field, "ROAD_ID", link_id, mark_ids, raw)]

    # 旧版单 ID 模式（兼容 ProcessShpFiles 文案）
    legacy = _parse_legacy_patterns(compact, raw)
    return legacy


def _parse_legacy_patterns(compact: str, raw: str) -> List[LaneFixAction]:
    """兼容旧版错误描述（单 ID）。"""
    patterns = (
        (r"lane\s*id\s*=\s*(\d+).*?lmark_l缺失边线\s*(\d+)", "add", "BDY_LEFT", "ID", ""),
        (r"lane\s*id\s*=\s*(\d+).*?lmark_r缺失边线\s*(\d+)", "add", "BDY_RIGHT", "ID", ""),
        (r"lane\s*id\s*=\s*(\d+).*?lmark_l为空", "skip", "BDY_LEFT", "ID", ""),
        (r"lane\s*id\s*=\s*(\d+).*?lmark_r为空", "skip", "BDY_RIGHT", "ID", ""),
        (r"lane\s*id\s*[=:：]?\s*(\d+).*?lmark_r关联了错误的边线[：:\s]*(\d+)", "remove", "BDY_RIGHT", "ID", ""),
        (r"当前\s*lane\s*id\s*(\d+).*?lmark_r关联了错误的边线[：:\s]*(\d+)", "remove", "BDY_RIGHT", "ID", ""),
        (r"link\s*id\s*[=:：]?\s*(\d+).*?bdyid_r缺失了边线[：:\s]*(\d+)", "add", "RBDY_R", "ROAD_ID", ""),
        (r"link\s*id\s*[=:：]?\s*(\d+).*?左侧缺失边线\s*(\d+)", "add", "RBDY_L", "ROAD_ID", ""),
    )
    for pat, action, field, match_field, field_to in patterns:
        m = re.search(pat, compact, re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        groups = m.groups()
        mark_ids = list(groups[1:]) if len(groups) > 1 else []
        note = "表格未给出应补充的边线 ID，需手动处理" if action == "skip" else ""
        return [
            LaneFixAction(
                action=action,
                target_field=field,
                match_field=match_field,
                match_value=groups[0],
                mark_ids=mark_ids,
                source_text=raw,
                target_field_to=field_to,
                note=note,
            )
        ]
    return []


def parse_error_text(text: str) -> Optional[LaneFixAction]:
    """兼容：返回第一条改错动作。"""
    items = parse_error_texts(text)
    return items[0] if items else None


def read_csv_rows(path: Path) -> List[List[str]]:
    rows = []
    for encoding in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with open(path, "r", encoding=encoding, newline="") as handle:
                reader = csv.reader(handle)
                for row in reader:
                    cells = _row_texts(row)
                    if cells:
                        rows.append(cells)
            return rows
        except UnicodeDecodeError:
            rows = []
            continue
    raise RuntimeError(f"无法读取 CSV 编码: {path}")


def _xlsx_col_ref(cell_ref: str) -> int:
    letters = re.sub(r"\d+", "", cell_ref)
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch.upper()) - ord("A") + 1)
    return value - 1


def read_xlsx_rows(path: Path) -> List[List[str]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared: List[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for si in root.findall(".//m:si", ns):
                parts = [node.text or "" for node in si.findall(".//m:t", ns)]
                shared.append("".join(parts))
        sheet_name = "xl/worksheets/sheet1.xml"
        for name in archive.namelist():
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                sheet_name = name
                break
        sheet = ET.fromstring(archive.read(sheet_name))

    grid = {}
    max_row = 0
    max_col = 0
    for cell in sheet.findall(".//m:c", ns):
        ref = cell.attrib.get("r", "")
        if not ref:
            continue
        col = _xlsx_col_ref(ref)
        row = int(re.sub(r"\D+", "", ref) or "0") - 1
        cell_type = cell.attrib.get("t")
        value_node = cell.find("m:v", ns)
        inline = cell.find("m:is", ns)
        text = ""
        if cell_type == "s" and value_node is not None and value_node.text is not None:
            idx = int(value_node.text)
            text = shared[idx] if 0 <= idx < len(shared) else ""
        elif inline is not None:
            text = "".join(node.text or "" for node in inline.findall(".//m:t", ns))
        elif value_node is not None and value_node.text is not None:
            text = value_node.text
        grid[(row, col)] = _norm_cell(text)
        max_row = max(max_row, row)
        max_col = max(max_col, col)

    rows = []
    for row_idx in range(max_row + 1):
        cells = [grid.get((row_idx, col_idx), "") for col_idx in range(max_col + 1)]
        while cells and not cells[-1]:
            cells.pop()
        if any(x.strip() for x in cells):
            rows.append([c for c in cells if c.strip()])
    return rows


def load_table_rows(path: str) -> List[List[str]]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return read_csv_rows(file_path)
    if suffix in (".xlsx", ".xlsm"):
        return read_xlsx_rows(file_path)
    if suffix == ".xls":
        raise RuntimeError("暂不支持旧版 .xls，请在 Excel 中另存为 .xlsx 或 .csv")
    raise RuntimeError("请选择 .xlsx / .csv 格式的错误表格")


def parse_fix_actions(path: str) -> List[LaneFixAction]:
    """读取表格并解析全部可识别改错项。"""
    rows = load_table_rows(path)
    actions: List[LaneFixAction] = []
    seen = set()

    for cells in rows:
        header_hint = "".join(cells)
        if "检查分组" in header_hint or ("问题描述" in header_hint and "检查项" in header_hint):
            continue

        for desc in _pick_problem_cells(cells):
            for action in parse_error_texts(desc):
                key = (
                    action.action,
                    action.target_field,
                    action.target_field_to,
                    action.match_field,
                    action.match_value,
                    tuple(action.mark_ids),
                )
                if key in seen:
                    continue
                seen.add(key)
                actions.append(action)
    return actions


def collect_infer_road_ids(actions: List[LaneFixAction]) -> List[str]:
    """收集需要从 BDY 推断 RBDY 的 link（缺失/补边线类）。"""
    ids = []
    for action in actions:
        if action.match_field != "ROAD_ID":
            continue
        if action.action in ("add", "move") and action.target_field in ("RBDY_L", "RBDY_R"):
            ids.append(action.match_value)
    return list(dict.fromkeys(ids))
