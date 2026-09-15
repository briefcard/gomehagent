"""Colour arithmetic — luminance, contrast, a photograph's tones.

What survived of the twelve-role palette when the token email chain was
deleted (2026-09-14): the WCAG maths the checks use, and `signature` —
the tones a picture is made of, kept on its reading for the model to be
told. Nothing here fills a role or chooses a colour for an email.
"""
from __future__ import annotations

import colorsys
import io
import re


_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse(hexv) -> tuple[int, int, int] | None:
    m = _HEX.match(str(hexv or "").strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def to_hex(rgb) -> str:
    r, g, b = (max(0, min(255, int(round(x)))) for x in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def norm(hexv) -> str:
    """`#rrggbb`, lower-case, or '' when it is not a colour."""
    rgb = parse(hexv)
    return to_hex(rgb) if rgb else ""


def luminance(hexv) -> float:
    """WCAG relative luminance, 0 (black) to 1 (white)."""
    rgb = parse(hexv)
    if not rgb:
        return 0.0
    def _lin(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    """WCAG contrast ratio between two colours, 1 to 21."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def on(hexv, dark: str = "#1c1e22", light: str = "#ffffff") -> str:
    """The readable ink on a ground — whichever of the two contrasts more.
    (`brand_theme._on`'s luminance rule, kept: light type on anything that
    is not clearly light.)"""
    return dark if luminance(hexv) > 0.35 else light


def mix(a, b, t: float) -> str:
    """`a` moved `t` of the way towards `b`."""
    ra, rb = parse(a), parse(b)
    if not ra or not rb:
        return norm(a) or norm(b)
    return to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def saturation(hexv) -> float:
    rgb = parse(hexv)
    if not rgb:
        return 0.0
    return colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb))[1]


def signature(blob: bytes) -> dict:
    """What a picture is made of, small enough to key an email to: its
    dominant colour, its most frequent LIGHT tone (a ground a page can take),
    its deepest tone (a ground the dark can take), its most frequent
    saturated mid-tone (a second colour), its average luminance as `key`,
    and a warmth from -1 (cool) to 1 (warm). `{}` when it is not a picture.
    Quantised to sixteen colours on a 64-pixel thumbnail, as `from_pictures`
    is — a tone that does not survive that is not one the eye reads."""
    import io
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(blob)).convert("RGB")
    except Exception:                                            # noqa: BLE001
        return {}
    q = im.resize((64, 64), Image.LANCZOS).quantize(colors=16).convert("RGB")
    cols = sorted(q.getcolors(64 * 64) or [], key=lambda t: -t[0])
    if not cols:
        return {}
    total = sum(f for f, _ in cols)
    hexes = [(f, to_hex(rgb)) for f, rgb in cols]
    dominant = hexes[0][1]
    light = next((h for f, h in hexes if 0.7 < luminance(h) <= 0.97), "")
    dark = next((h for f, h in hexes if luminance(h) < 0.2), "")
    mid = next((h for f, h in hexes if 0.2 <= luminance(h) <= 0.7 and saturation(h) >= 0.18), "")
    avg_l = sum(f * luminance(h) for f, h in hexes) / total
    warmth = 0.0
    for f, h in hexes:
        r, g, b = parse(h)
        warmth += f * ((r - b) / 255.0)
    warmth = round(max(-1.0, min(1.0, warmth / total)), 2)
    return {"dominant": dominant, "light": light, "dark": dark, "mid": mid,
            "key": "light" if avg_l > 0.6 else "dark" if avg_l < 0.3 else "mid",
            "luminance": round(avg_l, 3), "warmth": warmth}
