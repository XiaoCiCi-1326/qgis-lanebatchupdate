# -*- coding: utf-8 -*-
"""仅生成插件管理器主图标 icon.png（不改动三按钮工具栏图标）。"""

import os

from PIL import Image, ImageDraw, ImageFont

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(PLUGIN_DIR, "icon.png")
SIZE = 48


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


def draw_plugin_icon(size=SIZE):
    """车道刷值：道路底 + 限速牌 + 小箭头（与工具栏风格一致）。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角底
    pad = 2
    draw.rounded_rectangle(
        (pad, pad, size - pad - 1, size - pad - 1),
        radius=max(6, size // 6),
        fill=(235, 245, 255, 255),
        outline=(70, 130, 180, 255),
        width=1,
    )

    # 道路
    road_y = size * 0.62
    draw.polygon(
        [
            (size * 0.18, road_y),
            (size * 0.82, road_y),
            (size * 0.72, size * 0.88),
            (size * 0.28, size * 0.88),
        ],
        fill=(90, 90, 90, 255),
    )
    cx = size * 0.5
    for offset in (-0.06, 0.06):
        draw.line(
            [(cx + size * offset, road_y + 2), (cx + size * offset, size * 0.86)],
            fill=(250, 220, 60, 255),
            width=max(1, size // 24),
        )

    # 限速牌（红圈 30）
    sign_r = size * 0.22
    sign_cx, sign_cy = size * 0.36, size * 0.38
    draw.ellipse(
        (
            sign_cx - sign_r,
            sign_cy - sign_r,
            sign_cx + sign_r,
            sign_cy + sign_r,
        ),
        fill=(255, 255, 255, 255),
        outline=(210, 35, 35, 255),
        width=max(2, size // 16),
    )
    font = _font(max(8, int(size * 0.22)))
    text = "30"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        (sign_cx - tw / 2, sign_cy - th / 2 - 1),
        text,
        fill=(20, 20, 20, 255),
        font=font,
    )

    # 转向箭头（右下，呼应 VIRTUAL）
    ax, ay = size * 0.68, size * 0.32
    draw.arc(
        (ax - 8, ay - 4, ax + 10, ay + 14),
        start=200,
        end=340,
        fill=(0, 100, 200, 255),
        width=max(2, size // 14),
    )
    draw.polygon(
        [(ax + 9, ay + 10), (ax + 14, ay + 4), (ax + 6, ay + 5)],
        fill=(0, 100, 200, 255),
    )

    return img


def main():
    img = draw_plugin_icon(SIZE)
    img.save(OUT_PATH, "PNG")
    print(f"已生成: {OUT_PATH} ({SIZE}x{SIZE})")


if __name__ == "__main__":
    main()
