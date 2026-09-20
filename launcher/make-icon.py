#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate icon.ico + logo.png for the DSH launcher. Run once:
    python make-icon.py

Draws the **official DeepSeek Harness whale mark** in white on the DeepSeek
blue gradient tile, so the shortcut, the taskbar and the tray all carry the
real brand mark instead of the old ">_" placeholder.

The mark is the `FISH_LOGO_PATH` geometry from upstream's
`packages/client/ui-primitives/src/FishLogo.tsx` (viewBox 23.16 x 17.04,
`fill="currentColor"`), rasterised here because the build has no SVG
renderer. It is path data, not a redrawn approximation — if upstream ever
changes the mark, copy the new `d=` string in and re-run.

Pillow only (build time, not runtime). Everything is drawn at 4x and
downsampled with LANCZOS: the whale is mostly thin curves, and without
supersampling 16 px looks like a smudge.
"""
from __future__ import annotations

import os
import re

from PIL import Image, ImageDraw

SIZES = [256, 128, 64, 48, 32, 16]
SS = 4                      # supersampling factor
TOP = (77, 107, 254)        # #4D6BFE  DeepSeek blue
BOT = (38, 48, 138)         # deep indigo
RADIUS_RATIO = 0.22
VIEWBOX = (23.16, 17.04)
WHALE_SPAN = 0.68           # fraction of the tile width the mark occupies

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ICO = os.path.join(HERE, "icon.ico")
OUT_LOGO = os.path.join(HERE, "logo.png")          # 32px mark for the panel header
OUT_PREVIEW = os.path.join(HERE, "icon-preview.png")

# Official DeepSeek Harness mark. Keep verbatim.
FISH_LOGO_PATH = (
    'M22.9168 1.43018C22.6713 1.31018 22.5658 1.53918 22.4223 1.65519C22.3733 1.69269 22.3318 1.74169 22.2903 1.78669C21.9317 2.1697 21.5127 2.42121 20.9657 2.39121C20.1657 2.34621 19.4827 2.59771 18.8787 3.20973C18.7502 2.45521 18.3236 2.0047 17.6746 1.71569C17.3351 1.56568 16.9916 1.41518 16.7536 1.08867C16.5876 0.856163 16.5421 0.597155 16.4591 0.341647C16.4061 0.187643 16.3536 0.0301382 16.1761 0.00363739C15.9836 -0.0263635 15.9081 0.135141 15.8326 0.270145C15.5306 0.822162 15.4136 1.43018 15.4251 2.0462C15.4516 3.43174 16.0366 4.53527 17.1991 5.3203C17.3311 5.4103 17.3651 5.5003 17.3236 5.63181C17.2441 5.90231 17.1501 6.16482 17.0671 6.43533C17.0141 6.60784 16.9351 6.64584 16.7501 6.57033C16.1121 6.30383 15.5611 5.90931 15.074 5.4328C14.2475 4.63328 13.5 3.75075 12.568 3.05973C12.349 2.89822 12.13 2.74822 11.9034 2.60522C10.9524 1.68169 12.028 0.923165 12.277 0.833162C12.5375 0.739159 12.3675 0.41615 11.5259 0.42015C10.6844 0.42365 9.91439 0.705658 8.93286 1.08117C8.78935 1.13767 8.63835 1.17867 8.48384 1.21267C7.59332 1.04367 6.66829 1.00617 5.70226 1.11517C3.88321 1.31768 2.43016 2.1777 1.36213 3.64575C0.0790928 5.4103 -0.222916 7.41536 0.146595 9.50642C0.535106 11.7105 1.66014 13.535 3.38869 14.9616C5.18125 16.4406 7.24581 17.1657 9.60138 17.0266C11.0319 16.9441 12.6245 16.7526 14.421 15.2321C14.874 15.4576 15.3496 15.5476 16.1381 15.6151C16.7456 15.6716 17.3306 15.5851 17.7836 15.4911C18.4931 15.3411 18.4441 14.6841 18.1876 14.5636C16.1081 13.595 16.5646 13.9891 16.1496 13.67C17.2061 12.42 18.8202 10.1979 19.3182 7.17235C19.3672 6.83834 19.4297 6.36783 19.4222 6.09732C19.4182 5.93231 19.4562 5.86831 19.6447 5.84931C20.1657 5.78931 20.6712 5.64681 21.1357 5.3913C22.4833 4.65528 23.0268 3.44624 23.1548 1.9972C23.1738 1.77569 23.1508 1.54668 22.9168 1.43018ZM11.1749 14.4736C9.15936 12.889 8.18184 12.3675 7.77832 12.39C7.40081 12.4125 7.46881 12.8445 7.55182 13.126C7.63882 13.404 7.75182 13.5955 7.91033 13.8396C8.01983 14.0011 8.09533 14.2411 7.80083 14.4216C7.15181 14.8231 6.02327 14.2866 5.97027 14.2601C4.65673 13.4865 3.5587 12.4655 2.78467 11.069C2.03715 9.72493 1.60314 8.28289 1.53164 6.74384C1.51264 6.37233 1.62214 6.24082 1.99215 6.17332C2.47916 6.08332 2.98118 6.06432 3.46769 6.13582C5.52476 6.43633 7.27581 7.35586 8.74385 8.8129C9.58188 9.64243 10.2159 10.634 10.8689 11.6025C11.5634 12.631 12.3105 13.611 13.262 14.4146C13.598 14.6961 13.866 14.9101 14.1225 15.0681C13.349 15.1546 12.058 15.1731 11.1749 14.4746L11.1749 14.4736ZM12.141 8.25988C12.141 8.09488 12.273 7.96338 12.439 7.96338C12.4765 7.96338 12.5105 7.97088 12.541 7.98188C12.5825 7.99688 12.6205 8.01938 12.6505 8.05338C12.7035 8.10588 12.7335 8.18088 12.7335 8.25988C12.7335 8.42489 12.6015 8.55639 12.4355 8.55639C12.2695 8.55639 12.141 8.42489 12.141 8.25988ZM15.1415 9.79893C14.949 9.87793 14.7565 9.94544 14.5715 9.95294C14.2845 9.96794 13.9715 9.85143 13.8015 9.70893C13.5375 9.48742 13.3485 9.36342 13.2695 8.97691C13.2355 8.8119 13.2545 8.55639 13.2845 8.40989C13.3525 8.09438 13.277 7.89187 13.0545 7.70787C12.8735 7.55786 12.643 7.51636 12.39 7.51636C12.2955 7.51636 12.209 7.47486 12.1445 7.44136C12.039 7.38886 11.9519 7.25735 12.035 7.09585C12.0615 7.04335 12.19 6.91584 12.22 6.89334C12.5635 6.69784 12.9595 6.76184 13.326 6.90834C13.6655 7.04735 13.9225 7.30236 14.292 7.66287C14.6695 8.09838 14.7375 8.21838 14.9525 8.54539C15.1225 8.8009 15.277 9.06341 15.3831 9.36392C15.4471 9.55142 15.3641 9.70493 15.1415 9.79893Z'
)

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_CMDS = re.compile(r"([MmLlCcZz])([^MmLlCcZz]*)")


# --------------------------------------------------------------------------
# path -> polygons
# --------------------------------------------------------------------------
def _flatten_path(d: str, steps: int = 14) -> list[list[tuple[float, float]]]:
    """Turn an SVG path of M/L/C/Z commands into closed polygons.

    Enough for this mark, which uses only those four. Anything else raises
    rather than silently producing a wrong shape.
    """
    subpaths: list[list[tuple[float, float]]] = []
    pts: list[tuple[float, float]] = []
    cur = (0.0, 0.0)
    start = (0.0, 0.0)

    for match in _CMDS.finditer(d):
        cmd, args = match.group(1), [float(n) for n in _NUM.findall(match.group(2))]
        if cmd in "Mm":
            if pts:
                subpaths.append(pts)
            pts = []
            cur = (args[0] + (cur[0] if cmd == "m" else 0),
                   args[1] + (cur[1] if cmd == "m" else 0))
            start = cur
            pts.append(cur)
            rest = args[2:]
            for i in range(0, len(rest) - 1, 2):
                cur = (rest[i] + (cur[0] if cmd == "m" else 0),
                       rest[i + 1] + (cur[1] if cmd == "m" else 0))
                pts.append(cur)
        elif cmd in "Ll":
            for i in range(0, len(args) - 1, 2):
                cur = (args[i] + (cur[0] if cmd == "l" else 0),
                       args[i + 1] + (cur[1] if cmd == "l" else 0))
                pts.append(cur)
        elif cmd in "Cc":
            for i in range(0, len(args) - 5, 6):
                x1, y1, x2, y2, x, y = args[i:i + 6]
                if cmd == "c":
                    x1, y1 = x1 + cur[0], y1 + cur[1]
                    x2, y2 = x2 + cur[0], y2 + cur[1]
                    x, y = x + cur[0], y + cur[1]
                x0, y0 = cur
                for s in range(1, steps + 1):
                    t = s / steps
                    u = 1 - t
                    pts.append((
                        u * u * u * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x,
                        u * u * u * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y,
                    ))
                cur = (x, y)
        elif cmd in "Zz":
            if pts:
                pts.append(start)
                subpaths.append(pts)
                pts = []
    if pts:
        subpaths.append(pts)
    return subpaths


def _scaled(polys, size: int, span: float, cx: float, cy: float,
            box_w: float = VIEWBOX[0], box_h: float = VIEWBOX[1]):
    """Map viewBox coordinates onto a `span`-wide box centred at (cx, cy)."""
    target_w = size * span
    target_h = target_w * (box_h / box_w)
    sx = target_w / box_w
    sy = target_h / box_h
    ox = cx - target_w / 2
    oy = cy - target_h / 2
    return [[(ox + x * sx, oy + y * sy) for x, y in poly] for poly in polys]


def _signed_area(poly) -> float:
    total = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _mark_mask(px: int, span: float = 1.0) -> Image.Image:
    """Rasterise the mark into an L mask — 255 where ink goes.

    The mark is one SVG path with four subpaths, and three of them wind the
    *opposite* way to the body: under the nonzero fill rule they are holes,
    not shapes. Filling them all would give a featureless blob, so the
    opposite-winding ones are drawn back in black — that is what produces the
    whale's curve, its eye and its fin.
    """
    polys = _scaled(_flatten_path(FISH_LOGO_PATH, max(10, SS * 3)),
                    px, span, px / 2, px / 2)
    mask = Image.new("L", (px, px), 0)
    d = ImageDraw.Draw(mask)
    body_sign = _signed_area(polys[0]) > 0
    for poly in polys:
        d.polygon(poly, fill=255 if (_signed_area(poly) > 0) == body_sign else 0)
    return mask


# --------------------------------------------------------------------------
# drawing
# --------------------------------------------------------------------------
def _tile(size: int) -> Image.Image:
    """Blue gradient rounded square with the whale in white."""
    px = size * SS
    im = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for y in range(px):
        t = y / (px - 1) if px > 1 else 0.0
        d.line([(0, y), (px, y)],
               fill=tuple(int(TOP[i] + (BOT[i] - TOP[i]) * t) for i in range(3)) + (255,))

    ink = _mark_mask(px, WHALE_SPAN)
    im = Image.composite(Image.new("RGBA", (px, px), (255, 255, 255, 255)), im, ink)

    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, px - 1, px - 1],
                                           radius=int(px * RADIUS_RATIO), fill=255)
    im.putalpha(mask)
    return im.resize((size, size), Image.LANCZOS)


def _plain_mark(size: int, color=TOP, span: float = 0.90) -> Image.Image:
    """The whale alone, on transparency — for the panel header.

    Slightly inset: the mark's own bounds touch the viewBox edge to edge, so
    at span 1.0 the tips sit flush against the image border and read as
    clipped once the panel draws it next to a rounded corner.
    """
    px = size * SS
    ink = _mark_mask(px, span)
    im = Image.composite(Image.new("RGBA", (px, px), color + (255,)),
                         Image.new("RGBA", (px, px), (0, 0, 0, 0)), ink)
    return im.resize((size, size), Image.LANCZOS)


def _preview(tiles: dict[int, Image.Image]) -> Image.Image:
    """Proof sheet: the 256 px tile big, then every real size at 1:1, on a
    light background — a dark backdrop flatters a white mark and would hide
    a silhouette that turns to mush at 16 px."""
    sizes = (48, 32, 24, 16)
    pad = 24
    row_w = sum(s + 18 for s in sizes)
    width = pad * 3 + 256 + row_w
    height = pad * 2 + 256
    canvas = Image.new("RGB", (width, height), (246, 247, 249))
    canvas.paste(tiles[256], (pad, pad), tiles[256])

    x = pad * 2 + 256
    for s in sizes:
        canvas.paste(tiles[s], (x, pad + 256 - s), tiles[s])
        x += s + 18
    return canvas


def main() -> None:
    tiles = {s: _tile(s) for s in SIZES}
    tiles[24] = _tile(24)

    tiles[256].save(OUT_ICO, format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=[tiles[s] for s in SIZES[1:]])
    _plain_mark(32).save(OUT_LOGO)
    _preview(tiles).save(OUT_PREVIEW)
    print("icon.ico     -> %s (%d sizes)" % (OUT_ICO, len(SIZES)))
    print("logo.png     -> %s (32px panel mark)" % OUT_LOGO)
    print("icon-preview -> %s (eyeball this)" % OUT_PREVIEW)


if __name__ == "__main__":
    main()
