"""Section edges, drawn by code.

A shaped edge between two grounds — a wave, a curve, a slant — was drawn by
the model as an SVG path in a baked block, and hand-written geometry breaks:
the owner's run of 2026-09-26 shipped a wave whose path was never closed
along its bottom, so the fill ran back to the start in a straight diagonal
across the section. The composer now NAMES the edge —

    <!--divider: wave #29325a #f4f1ec-->

— the shape, then the ground above it, then the ground below — and this draws
it: one closed polygon per shape, at the column's width, supersampled so the
edge is smooth. The composer decides the design; the geometry is never its to
get wrong. The marker stands alone in a full-width cell with no padding, where
an <img> could go, and becomes that <img>.
"""
from __future__ import annotations

import functools
import io
import math
import re

#: The edges there are. A straight edge needs no divider.
SHAPES = ("wave", "curve", "slant", "zigzag", "scallop")
#: A divider's height at 1×; drawn at 2× like every baked picture.
HEIGHT, SCALE = 48, 2

MARK = re.compile(r"<!--\s*divider:\s*([a-z]+)\s+(#[0-9a-fA-F]{3,6})\s+(#[0-9a-fA-F]{3,6})\s*-->", re.I)
#: Anything the composer meant as a divider, well-formed or not.
_ANY = re.compile(r"<!--\s*divider\b.*?-->", re.I | re.S)


def _edge(shape: str, t: float) -> float:
    """Where the edge sits at `t` across the width, 0 (top) to 1 (bottom)."""
    if shape == "wave":
        return 0.5 + 0.3 * math.sin(2 * math.pi * 2 * t)
    if shape == "curve":
        return 0.15 + 0.7 * 4 * t * (1 - t)
    if shape == "slant":
        return 0.1 + 0.8 * t
    if shape == "zigzag":
        return 0.15 + 0.7 * abs((t * 16) % 1 * 2 - 1)
    u = (t * 12) % 1                                              # scallop
    return 0.2 + 0.6 * math.sqrt(max(0.0, 1 - (2 * u - 1) ** 2))


@functools.lru_cache(maxsize=64)
def draw(shape: str, above: str, below: str, width: int = 600) -> bytes:
    """The edge as a PNG, `width` × HEIGHT at 2×: the ground BELOW fills the
    picture and the ground ABOVE is one CLOSED polygon — along the top, down
    the right side, back along the edge, up the left — so there is no end left
    for the fill to run back from."""
    from PIL import Image, ImageDraw
    from . import palette
    ss = 4
    w, h = width * SCALE * ss, HEIGHT * SCALE * ss
    im = Image.new("RGB", (w, h), palette.parse(below))
    edge = [(x, _edge(shape, x / w) * h) for x in range(0, w + 1, 4)]
    if edge[-1][0] != w:
        edge.append((w, _edge(shape, 1.0) * h))
    ImageDraw.Draw(im).polygon([(0, 0), (w, 0)] + edge[::-1], fill=palette.parse(above))
    im = im.resize((width * SCALE, HEIGHT * SCALE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def place(html: str, tenant: str, width: int = 600) -> tuple[str, list[str]]:
    """Every divider marker drawn, hosted and replaced by its <img>. Notes as
    `bake` writes them; a marker that cannot be drawn is `divider: …` — a
    blocking finding in the maker's round, because a named edge that is not
    drawn leaves the two grounds meeting on a straight line nobody chose."""
    from . import media, palette
    notes: list[str] = []

    def one(m: re.Match) -> str:
        whole = m.group(0)
        good = MARK.fullmatch(whole)
        if not good or good.group(1).lower() not in SHAPES:
            notes.append(f"divider: {whole[4:-3].strip()[:60]!r} cannot be drawn — write "
                         f"<!--divider: SHAPE ABOVE BELOW-->, SHAPE one of {', '.join(SHAPES)}, "
                         f"ABOVE and BELOW the hex grounds it joins")
            return whole
        shape, above, below = good.group(1).lower(), palette.norm(good.group(2)), palette.norm(good.group(3))
        put = media.put(tenant, draw(shape, above, below, width), mime="image/png", origin="derived")
        if not put.get("ok"):
            notes.append(f"a {shape} divider could not be hosted — left out")
            return ""
        notes.append(f"drawn: a {shape} from {above} to {below}")
        return (f'<img src="{put["url"]}" width="{width}" alt="" data-divider="{above} {below}" '
                f'style="display:block;width:100%;max-width:{width}px;height:auto;border:0">')

    return _ANY.sub(one, html), notes
