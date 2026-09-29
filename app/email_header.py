"""THE BRAND'S HEADER — one layout on every email, drawn by code.

Owner, 2026-09-29: "It started off with … a wavy transition instead of a
strong email header with a consistent layout for navigating to the website.
We need this to be streamlined per brand — even if the colors change to match
the look and feel of the email." Nothing defined a header: the maker
recreated whatever the reference opened with, and this reference opened with
a wave.

So the header is the BRAND'S, like the footer: its mark over the pages the
owner approved on the Brand tab (`theme["nav"]`), the same layout every time.
The maker only chooses its two colours from the email's own palette, by
writing `<!--brand-header: GROUND INK-->` as the column's first row; this
draws it there. A missing marker is placed for it, on the ground the column
opens on. A mark that would vanish on the ground (a light mark on a light
ground) is set as the brand's name in the headline face instead.
"""
from __future__ import annotations

import functools
import re

MARK_HEIGHT = 40      # px — the mark's height in the header
MARK_MAX_WIDTH = 220  # px — a very wide mark is held to this
NAV_MAX = 4           # links in the nav row

_MARKER = re.compile(r"<!--\s*brand-header\s*:?\s*(#[0-9a-fA-F]{3,8})?\s*(#[0-9a-fA-F]{3,8})?\s*-->", re.I)
_COLUMN_PAT = r"<table\b[^>]*(?:width=[\"']?%d[\"']?|max-width:\s*%dpx)[^>]*>(\s*<tbody[^>]*>)?"
_GROUND = re.compile(r"(?:bgcolor=[\"']?|background(?:-color)?:\s*)(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\b", re.I)


def _rgb(hexv: str) -> tuple[int, int, int] | None:
    h = str(hexv or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) not in (6, 8):
        return None
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))      # type: ignore[return-value]
    except ValueError:
        return None


def _lum(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _ratio(a: str, b: str) -> float:
    ra, rb = _rgb(a), _rgb(b)
    if not (ra and rb):
        return 0.0
    la, lb = sorted((_lum(ra), _lum(rb)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@functools.lru_cache(maxsize=64)
def _mark_size(url: str) -> tuple[int, int] | None:
    """The mark's own pixel size, read once — so the header can set a width
    for a fixed height without stretching it."""
    if not url:
        return None
    try:
        import io
        from PIL import Image
        from . import pictures
        blob = pictures._fetch_bounded(url)
        if not blob:
            return None
        w, h = Image.open(io.BytesIO(blob)).size
        return (w, h) if w and h else None
    except Exception:                                             # noqa: BLE001
        return None


def nav(tenant: str, theme: dict) -> list[dict]:
    """The pages the header links: the owner-approved nav, else the shop."""
    items = [{"label": str(i.get("label") or "").strip(), "url": str(i.get("url") or "").strip()}
             for i in (theme.get("nav") or []) if isinstance(i, dict)]
    items = [i for i in items if i["label"] and i["url"].startswith("http")][:NAV_MAX]
    if items:
        return items
    from . import links
    shop = links.shop_url(tenant)
    return [{"label": "Shop", "url": shop}] if shop else []


_SYSTEM = re.compile(r"<!--\s*system:(.*?)-->", re.S | re.I)


def system_of(html: str) -> tuple[int | None, list[int]]:
    """`(inset, scale)` from the email's own <!-- system --> comment — so the
    header sits on the same side inset and sizes as everything under it: one
    layout on every email, set in each email's own rhythm."""
    m = _SYSTEM.search(html or "")
    if not m:
        return None, []
    decl = m.group(1)
    seg = lambda key: (re.search(key + r"\s*:?(.*?)(?:·|\n|$)", decl, re.I | re.S) or [None, ""])[1]  # noqa: E731
    nums = lambda t: [int(float(x)) for x in re.findall(r"\d+(?:\.\d+)?", t)]  # noqa: E731
    inset = nums(seg("inset"))[:1]
    return (inset[0] if inset and 8 <= inset[0] <= 64 else None), [x for x in nums(seg("scale")) if x >= 8]


def render(tenant: str, kit_: dict, ground: str, ink: str, width: int, *,
           inset: int | None = None, scale: list[int] | None = None) -> str:
    """The header table: the mark over the nav, in these two colours, on the
    email's own inset and type scale where it declared them."""
    side = inset or 24
    steps = sorted(set(scale or []))
    nav_px = next((x for x in steps if x >= 11), 12) if steps else 12
    in_range = [x for x in steps if 18 <= x <= 32]
    name_px = (max(in_range) if in_range else
               min(steps, key=lambda x: abs(x - 26)) if steps else 26)
    from . import type_system
    theme = kit_.get("theme") or {}
    pairing = type_system.for_theme(theme)
    name = str(theme.get("name") or kit_.get("name") or "").strip()
    from . import links
    home_url = links.shop_url(tenant) or next((d["url"] for d in nav(tenant, theme)), "") or "#"
    ground_light = _lum(_rgb(ground) or (255, 255, 255)) > 0.5
    tone = str(kit_.get("logo_tone") or "")
    logo = str(theme.get("logo_url") or "")
    vanishes = (tone == "light" and ground_light) or (tone == "dark" and not ground_light)
    if logo and not vanishes:
        size = _mark_size(logo)
        if size:
            w = round(MARK_HEIGHT * size[0] / size[1])
            h = MARK_HEIGHT if w <= MARK_MAX_WIDTH else round(MARK_MAX_WIDTH * size[1] / size[0])
            w = min(w, MARK_MAX_WIDTH)
            dims = f' width="{w}" height="{h}"'
            style = f"display:block;border:0;outline:none;width:{w}px;height:{h}px;max-width:100%"
        else:
            dims = ' width="160"'
            style = "display:block;border:0;outline:none;width:160px;height:auto;max-width:100%"
        mark = (f'<a href="{home_url}" style="text-decoration:none;display:inline-block">'
                f'<img src="{logo}" alt="{name or "Home"}"{dims} style="{style}"></a>')
    else:
        mark = (f'<a href="{home_url}" style="font-family:{pairing["headline"]["stack"]};font-size:{name_px}px;'
                f'line-height:{round(name_px * 1.25)}px;color:{ink};text-decoration:none;letter-spacing:1px">'
                f'{name or "Home"}</a>')
    items = nav(tenant, theme)
    links_html = "".join(
        f'<a href="{i["url"]}" style="color:{ink};text-decoration:none;display:inline-block;'
        f'padding:4px 12px">{i["label"]}</a>' for i in items)
    nav_row = (f'<tr><td align="center" style="padding:0 {side}px 22px {side}px;font-family:{pairing["body"]["stack"]};'
               f'font-size:{nav_px}px;line-height:{nav_px + 6}px;letter-spacing:2px;text-transform:uppercase;color:{ink}">'
               f'{links_html}</td></tr>') if items else ""
    return (f'<table role="presentation" data-brand-header="1" width="{width}" cellpadding="0" cellspacing="0" '
            f'border="0" style="width:100%;max-width:{width}px;background-color:{ground};border-collapse:collapse">'
            f'<tr><td align="center" style="padding:28px {side}px {"12" if items else "24"}px {side}px">{mark}</td></tr>'
            f'{nav_row}</table>')


def place(html: str, tenant: str, kit_: dict, width: int) -> tuple[str, str]:
    """`(html, note)` — the brand header drawn where the maker marked it, or
    placed first in the column when it did not. `note` says which, and why a
    colour or the mark was changed."""
    from . import brand_theme
    m = _MARKER.search(html or "")
    notes = []
    if m:
        ground = m.group(1) or ""
        ink = m.group(2) or ""
    else:
        col = _COLUMN_RE(width).search(html or "")
        after = (html or "")[col.end():] if col else (html or "")
        g = _GROUND.search(after)
        ground, ink = (g.group(1) if g else "#ffffff"), ""
    if not _rgb(ground):
        ground = "#ffffff"
    if not ink or _ratio(ink, ground) < 4.5:
        if ink:
            notes.append(f"the header's ink {ink} did not read on {ground} — set to {brand_theme._on(ground)}")
        ink = brand_theme._on(ground)
    inset, scale = system_of(html)
    head = render(tenant, kit_, ground, ink, width, inset=inset, scale=scale)
    if not nav(tenant, kit_.get("theme") or {}):
        notes.append("no pages on file for the header — add the site's pages to the nav on the Brand tab")
    if m:
        out = html[:m.start()] + head + _MARKER.sub("", html[m.end():])
        return out, "; ".join(notes)
    col = _COLUMN_RE(width).search(html or "")
    row = f'<tr><td style="padding:0">{head}</td></tr>'
    if col:
        out = html[:col.end()] + row + html[col.end():]
        notes.insert(0, "the brand header was placed first in the column (the maker did not mark it)")
    else:
        b = re.search(r"<body[^>]*>", html or "", re.I)
        at = b.end() if b else 0
        out = (html or "")[:at] + head + (html or "")[at:]
        notes.insert(0, "the brand header was placed at the top (no column was found to hold it)")
    return out, "; ".join(notes)


def _COLUMN_RE(width: int):
    """The email's column table — the first table held to the column width."""
    return re.compile(_COLUMN_PAT % (width, width), re.I)
