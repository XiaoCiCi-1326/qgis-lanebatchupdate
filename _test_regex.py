import re

# Simulate what lane_fix_excel.py does
compact = "问题#1：laneID=4211819 lmark_r记录顺序不对（边线4211704与4211705顺序错误）"
print("compact:", compact)
print()

# Test regex
if re.search(r"lmark_[lr]记录顺序不对", compact):
    print("1. lmark_[lr]记录顺序不对 MATCH")

    # Extract lane_id
    m = re.search(r"(?:laneid|lane)[【\[]?\s*[:：]?\s*(\d{6,})", compact, re.IGNORECASE)
    if not m:
        m = re.search(r"(?:laneid|lane)[【\[]?\s*(\d{6,})", compact, re.IGNORECASE)
    print(f"   lane_id match: {m.group(1) if m else None}")

    seg = re.search(r"边线[（(](\d[\d,，、\s]+?)与(\d[\d,，、\s]+?)顺序错误[）)]", compact)
    print(f"   seg (with parens): {seg}")
    if not seg:
        seg = re.search(r"(\d{6,})与(\d{6,})顺序错误", compact)
        print(f"   seg (fallback): {seg.group(1) if seg else None}, {seg.group(2) if seg else None}")
