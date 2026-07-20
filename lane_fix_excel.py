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

    action: str  # add / remove / skip / move
    target_field: str  # BDY_LEFT / BDY_RIGHT / RBDY_L / RBDY_R
    match_field: str  # ID / ROAD_ID
    match_value: str
    mark_ids: List[str]
    source_text: str
    target_field_to: str = ""  # move：目标字段
    note: str = ""


# 与 ProcessShpFiles / 3.16扳手错误汇总 对齐的错误描述模式
_ERROR_PATTERNS = (
    # lane 级：lmark 缺失/错误（BDY_LEFT / BDY_RIGHT）
    (
        re.compile(
            r"lane\s*id\s*=\s*(\d+).*?lmark_l缺失边线\s*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "add",
        "BDY_LEFT",
        "ID",
        "",
    ),
    (
        re.compile(
            r"lane\s*id\s*=\s*(\d+).*?lmark_r缺失边线\s*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "add",
        "BDY_RIGHT",
        "ID",
        "",
    ),
    (
        re.compile(
            r"lane\s*id\s*=\s*(\d+).*?lmark_l为空",
            re.IGNORECASE | re.DOTALL,
        ),
        "skip",
        "BDY_LEFT",
        "ID",
        "",
    ),
    (
        re.compile(
            r"lane\s*id\s*=\s*(\d+).*?lmark_r为空",
            re.IGNORECASE | re.DOTALL,
        ),
        "skip",
        "BDY_RIGHT",
        "ID",
        "",
    ),
    (
        re.compile(
            r"lane\s*id\s*[=:：]?\s*(\d+).*?lmark_l关联了错误的边线[：:\s]*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "remove",
        "BDY_LEFT",
        "ID",
        "",
    ),
    (
        re.compile(
            r"lane\s*id\s*[=:：]?\s*(\d+).*?lmark_r关联了错误的边线[：:\s]*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "remove",
        "BDY_RIGHT",
        "ID",
        "",
    ),
    (
        re.compile(
            r"当前\s*lane\s*id\s*(\d+).*?lmark_l关联了错误的边线[：:\s]*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "remove",
        "BDY_LEFT",
        "ID",
        "",
    ),
    (
        re.compile(
            r"当前\s*lane\s*id\s*(\d+).*?lmark_r关联了错误的边线[：:\s]*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "remove",
        "BDY_RIGHT",
        "ID",
        "",
    ),
    # link/road 级：RBDY 缺失/不应记录
    (
        re.compile(
            r"link\s*id\s*[=:：]?\s*(\d+).*?bdyid_l.*?不应记录边线.*?lanemark\s*id\s*[=:：]?\s*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "remove",
        "RBDY_L",
        "ROAD_ID",
        "",
    ),
    (
        re.compile(
            r"link\s*id\s*[=:：]?\s*(\d+).*?bdyid_r.*?不应记录边线.*?lanemark\s*id\s*[=:：]?\s*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "remove",
        "RBDY_R",
        "ROAD_ID",
        "",
    ),
    (
        re.compile(
            r"link\s*id\s*[=:：]?\s*(\d+).*?左侧缺失边线\s*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "add",
        "RBDY_L",
        "ROAD_ID",
        "",
    ),
    (
        re.compile(
            r"link\s*id\s*[=:：]?\s*(\d+).*?右侧缺失边线\s*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "add",
        "RBDY_R",
        "ROAD_ID",
        "",
    ),
    (
        re.compile(
            r"link\s*id\s*[=:：]?\s*(\d+).*?bdyid_l缺失了边线[：:\s]*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "add",
        "RBDY_L",
        "ROAD_ID",
        "",
    ),
    (
        re.compile(
            r"link\s*id\s*[=:：]?\s*(\d+).*?bdyid_r缺失了边线[：:\s]*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "add",
        "RBDY_R",
        "ROAD_ID",
        "",
    ),
    (
        re.compile(
            r"link\s*id\s*[=:：]?\s*(\d+).*?缺失了边线[：:\s]*(\d+)",
            re.IGNORECASE | re.DOTALL,
        ),
        "add",
        "RBDY_L",
        "ROAD_ID",
        "",
    ),
    # link 级：左右侧位错误（边线 ID 挂反了左右侧）→ 从 RBDY_L 移到 RBDY_R 等
    (
        re.compile(
            r"link\s*id\s*[：:\s]*(\d+)[，,]?.*?左侧\s*bdyid_l[，,]?.*?关联的边线\s*id?\s*(\d+).*?左右侧位错误",
            re.IGNORECASE | re.DOTALL,
        ),
        "move",
        "RBDY_L",
        "ROAD_ID",
        "RBDY_R",
    ),
    (
        re.compile(
            r"link\s*id\s*[：:\s]*(\d+)[，,]?.*?右侧\s*bdyid_r[，,]?.*?关联的边线\s*id?\s*(\d+).*?左右侧位错误",
            re.IGNORECASE | re.DOTALL,
        ),
        "move",
        "RBDY_R",
        "ROAD_ID",
        "RBDY_L",
    ),
    (
        re.compile(
            r"lane\s*id\s*[：:\s]*(\d+)[，,]?.*?左侧\s*lmark_l[，,]?.*?关联的边线\s*id?\s*(\d+).*?左右侧位错误",
            re.IGNORECASE | re.DOTALL,
        ),
        "move",
        "BDY_LEFT",
        "ID",
        "BDY_RIGHT",
    ),
    (
        re.compile(
            r"lane\s*id\s*[：:\s]*(\d+)[，,]?.*?右侧\s*lmark_r[，,]?.*?关联的边线\s*id?\s*(\d+).*?左右侧位错误",
            re.IGNORECASE | re.DOTALL,
        ),
        "move",
        "BDY_RIGHT",
        "ID",
        "BDY_LEFT",
    ),
)


def _norm_cell(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _row_texts(row: Iterable) -> List[str]:
    return [_norm_cell(c) for c in row if _norm_cell(c)]


def _parse_structured_row(cells: List[str]) -> Optional[LaneFixAction]:
    """尝试从带列名的表格行解析（若质检导出含结构化列）。"""
    if not cells:
        return None
    lower_map = {c.lower(): c for c in cells}
    joined = " | ".join(cells)

    # 常见列：错误描述 / laneid / linkid / 字段 / 操作 / 边线id
    desc = ""
    for key in ("错误描述", "错误信息", "描述", "message", "error"):
        for cell in cells:
            if cell.lower() == key.lower():
                continue
        # 找最长中文单元格当描述
    desc_candidates = [c for c in cells if len(c) >= 8]
    desc = max(desc_candidates, key=len, default=joined) if desc_candidates else joined

    action = parse_error_text(desc)
    if action:
        return action

    # 结构化：laneid + field + mark_id + op
    text_blob = " ".join(cells).lower()
    lane_m = re.search(r"(?:lane\s*id|laneid)\s*[=:：]?\s*(\d+)", text_blob, re.I)
    link_m = re.search(r"(?:link\s*id|linkid|road_id)\s*[=:：]?\s*(\d+)", text_blob, re.I)
    mark_m = re.search(r"(?:lanemark\s*id|边线)\s*[=:：]?\s*(\d+)", joined, re.I)
    if not mark_m:
        nums = re.findall(r"\b(\d{5,})\b", joined)
        mark_ids = nums[-1:] if nums else []
    else:
        mark_ids = [mark_m.group(1)]

    if "左右侧位错误" in joined:
        mark_m = re.search(r"关联的边线\s*id?\s*(\d+)", joined, re.I)
        mark_ids = [mark_m.group(1)] if mark_m else []
        if lane_m:
            if "lmark_l" in text_blob or "左侧" in joined:
                return LaneFixAction(
                    "move", "BDY_LEFT", "ID", lane_m.group(1), mark_ids, joined,
                    target_field_to="BDY_RIGHT",
                )
            if "lmark_r" in text_blob or "右侧" in joined:
                return LaneFixAction(
                    "move", "BDY_RIGHT", "ID", lane_m.group(1), mark_ids, joined,
                    target_field_to="BDY_LEFT",
                )
        if link_m:
            if "bdyid_l" in text_blob or "左侧" in joined:
                return LaneFixAction(
                    "move", "RBDY_L", "ROAD_ID", link_m.group(1), mark_ids, joined,
                    target_field_to="RBDY_R",
                )
            if "bdyid_r" in text_blob or "右侧" in joined:
                return LaneFixAction(
                    "move", "RBDY_R", "ROAD_ID", link_m.group(1), mark_ids, joined,
                    target_field_to="RBDY_L",
                )

    if "删除" in joined or "不应记录" in joined or ("错误" in joined and "左右侧位" not in joined):
        op = "remove"
    elif "补充" in joined or "缺失" in joined or "添加" in joined:
        op = "add"
    else:
        return None

    field = None
    for name in ("BDY_LEFT", "BDY_RIGHT", "RBDY_L", "RBDY_R", "LMARK_L", "LMARK_R"):
        if name.lower() in text_blob.replace("_", ""):
            field = name
            break
    if not field:
        if "lmark_l" in text_blob or "左侧" in joined or "bdyid_l" in text_blob:
            field = "BDY_LEFT" if "lmark" in text_blob else "RBDY_L"
        elif "lmark_r" in text_blob or "右侧" in joined or "bdyid_r" in text_blob:
            field = "BDY_RIGHT" if "lmark" in text_blob else "RBDY_R"
        else:
            return None

    if lane_m:
        return LaneFixAction(op, field, "ID", lane_m.group(1), mark_ids, joined)
    if link_m:
        return LaneFixAction(op, field, "ROAD_ID", link_m.group(1), mark_ids, joined)
    return None


def parse_error_text(text: str) -> Optional[LaneFixAction]:
    """从错误描述文本解析改错动作。"""
    raw = _norm_cell(text)
    if not raw:
        return None
    compact = re.sub(r"\s+", " ", raw)

    for pattern, action, field, match_field, field_to in _ERROR_PATTERNS:
        match = pattern.search(compact)
        if not match:
            continue
        groups = match.groups()
        match_value = groups[0]
        mark_ids = list(groups[1:]) if len(groups) > 1 else []
        note = ""
        if action == "skip":
            note = "表格未给出应补充的边线 ID，需手动处理"
        elif action == "move":
            note = f"从 {field} 移到 {field_to}"
        return LaneFixAction(
            action=action,
            target_field=field,
            match_field=match_field,
            match_value=match_value,
            mark_ids=mark_ids,
            source_text=raw,
            target_field_to=field_to or "",
            note=note,
        )
    return None


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
    """不依赖 openpyxl，直接解析 xlsx。"""
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
        cells = []
        for col_idx in range(max_col + 1):
            val = grid.get((row_idx, col_idx), "")
            if val:
                cells.append(val)
        if cells:
            rows.append(cells)
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
        # 跳过表头行
        header_hint = "".join(cells)
        if "检查分组" in header_hint or ("问题描述" in header_hint and "检查项" in header_hint):
            continue

        candidates = []
        for cell in cells:
            parsed = parse_error_text(cell)
            if parsed:
                candidates.append(parsed)
        if not candidates:
            parsed = _parse_structured_row(cells)
            if parsed:
                candidates.append(parsed)
        if not candidates:
            joined = " ".join(cells)
            parsed = parse_error_text(joined)
            if parsed:
                candidates.append(parsed)

        for action in candidates:
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
