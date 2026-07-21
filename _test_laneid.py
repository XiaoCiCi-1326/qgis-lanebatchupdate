# -*- coding: utf-8 -*-
import re
import sys
sys.path.insert(0, r"E:\刷转向与限速\lanebatchupdate")

from lane_fix_excel import _extract_lane_id

# Test with actual content from errorlog (simulated)
compact = "问题#1：laneID=4211819 lmark_r记录顺序不对（边线4211704与4211705顺序错误）"
print("Testing _extract_lane_id:")
print(f"  Input: {repr(compact)}")
print(f"  Output: {_extract_lane_id(compact)}")
print()

# Also test the lmark_r section directly
print("Testing regex patterns:")
pat1 = r"lmark_[lr]记录顺序不对"
print(f"  lmark_[lr] match: {bool(re.search(pat1, compact))}")

pat2 = r"边线[（(](\d[\d,，、\s]+?)与(\d[\d,，、\s]+?)顺序错误[）)]"
seg2 = re.search(pat2, compact)
print(f"  seg (with parens): {seg2}")

pat3 = r"(\d{6,})与(\d{6,})顺序错误"
seg3 = re.search(pat3, compact)
if seg3:
    print(f"  seg fallback: {seg3.group(1)}, {seg3.group(2)}")
