#!/usr/bin/env python3
"""Generate icon.ico for the DSH launcher. Run once:  python make-icon.py

Draws a deep-blue -> indigo vertical gradient rounded square with a white
">_" monospace glyph. Pillow only (used at build time, not at runtime).
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

SIZES = [256, 128, 64, 48, 32, 16]
TOP = (77, 107, 254)      # #4D6BFE  DeepSeek blue
BOT = (38, 48, 138)       # deep indigo
RADIUS_RATIO = 0.22
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\consolab.ttf",   # Consolas Bold (monospace)
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\seguisb.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
]


def _font(px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, px)
    return ImageFont.load_default()


def make(size: int) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    # Vertical gradient background.
    for y in range(size):
        t = y / (size - 1) if size > 1 else 0.0
        col = tuple(int(TOP[i] + (BOT[i] - TOP[i]) * t) for i in range(3))
        d.line([(0, y), (size, y)], fill=col + (255,))

    # White ">_" glyph, centered.
    font = _font(max(8, int(size * 0.36)))
    text = ">_"
    bbox = d.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - w) / 2 - bbox[0]
    y = (size - h) / 2 - bbox[1]
    d.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    # Rounded-corner alpha mask (corners become transparent).
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * RADIUS_RATIO), fill=255)
    im.putalpha(mask)
    return im


def main() -> None:
    imgs = [make(s) for s in SIZES]
    imgs[0].save(
        OUT,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=imgs[1:],
    )
    print(f"icon.ico written -> {OUT} ({len(SIZES)} sizes)")


if __name__ == "__main__":
    main()
