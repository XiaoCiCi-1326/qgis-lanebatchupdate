# -*- coding: utf-8 -*-
"""生成全量补空RBDY工具栏图标"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(PLUGIN_DIR, "icon_fill_rbdy.png")
SIZE = 32


def _font(size):
    for path in (
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/msyhbd.ttc",
    ):
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_fill_rbdy_icon(size=SIZE):
    """全量补空RBDY：填充图标风格，圆形底+填充箭头+R标识"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆形底（蓝色）
    r = size // 2 - 1
    cx, cy = size // 2, size // 2
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=(70, 130, 180, 255),
        outline=(50, 100, 150, 255),
        width=1,
    )

    # 填充箭头（向下填充的漏斗/水桶形状）
    arrow_w = size * 0.5
    arrow_h = size * 0.35
    ax = size // 2
    ay_top = size * 0.25
    ay_bot = ay_top + arrow_h

    # 倒三角形/漏斗
    draw.polygon([
        (ax - arrow_w / 2, ay_top),
        (ax + arrow_w / 2, ay_top),
        (ax + arrow_w / 4, ay_bot),
        (ax - arrow_w / 4, ay_bot),
    ], fill=(255, 255, 255, 255))

    # R 字母（表示 RBDY）
    font = _font(max(8, int(size * 0.4)))
    text = "R"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        (cx - tw / 2, cy - th / 2 + size * 0.05),
        text,
        fill=(255, 255, 255, 255),
        font=font,
    )

    return img


def main():
    img = draw_fill_rbdy_icon(SIZE)
    img.save(OUT_PATH, "PNG")
    print(f"已生成: {OUT_PATH} ({SIZE}x{SIZE})")


if __name__ == "__main__":
    main()
