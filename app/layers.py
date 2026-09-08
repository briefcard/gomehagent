"""A frame as LAYERS Canva can edit — photo, logo, headline, CTA — not a
picture of them.

Owner, 2026-09-07: *"the text and components are not separate layers on Canva
they are burned on — is there a way to layer them so we can adjust as
needed?"* And: *"how do we ensure that final approved assets get created in
the different ratios needed for the meta placements?"*

THE ROUTE IS THE CONNECTION THAT ALREADY WORKS. Canva's Connect API has no
call that adds a text box or a shape to a design; the editor's own tools sit
behind a separate service that wants a sign-in of its own (its published
metadata names only itself as the issuer of the tokens it takes). But the
Connect API IMPORTS a design from a file — PowerPoint among the documented
types — and each picture, text box and shape in that file arrives as its own
editable element:
https://www.canva.dev/docs/connect/api-reference/design-imports/
So this module writes a one-slide .pptx, by hand, with no dependency: the
photograph cover-cropped to the placement, the brand mark, the headline and
the CTA pill, each a separate object. `canva.import_design` sends it.

ONE DECK PER PLACEMENT, because a layout is a fact about a ratio. Meta's Reels
and Stories keep the top 14%, the bottom 35% and 6% of each side clear of
text and logos (`compose.META_PLACEMENTS`), so the 9:16 deck puts its type
inside that band; the 4:5 and 1:1 decks use the whole frame with a margin.
The placement exports are then plain PNGs at Meta's recommended sizes,
pulled back through `canva.harvest`.

UNITS. PowerPoint measures in EMU: 914,400 to the inch, 9,525 to a pixel at
96 dpi. Everything here is laid out in pixels of the placement and converted
at the edge; type sizes are hundredths of a point (a pixel is three quarters
of a point).
"""
from __future__ import annotations

import io
import math
import re
import zipfile
from xml.sax.saxutils import escape as _x

EMU_PER_PX = 9525
PT_PER_PX = 0.75

#: Layer names, in stacking order (first = bottom). The suite reads them back
#: off the slide, so a layer that stops being written is a failing check.
LAYERS = ("Photo", "Scrim", "Logo", "Headline", "CTA")

#: Type sizes as fractions of the placement's WIDTH — a headline that is
#: 6.5% of the width reads as a headline on a phone at every ratio.
HEADLINE_MAX, HEADLINE_MIN, HEADLINE_LINES = 0.065, 0.040, 3
CTA_RATIO, CTA_MIN = 0.42, 0.032
MARGIN = 0.06                 # the edge kept clear when a placement has no safe zone
LOGO_HEIGHT, LOGO_MAX_WIDTH = 0.055, 0.30

#: The default ask when a frame carries no copy of its own — a real button
#: the designer retitles, not an empty pill.
DEFAULT_ASK = "Shop now"

_GENERIC_FONTS = {"serif", "sans-serif", "monospace", "cursive", "fantasy",
                  "system-ui", "-apple-system", "blinkmacsystemfont", "ui-serif",
                  "ui-sans-serif", "ui-monospace"}


def family(stack: str, fallback: str = "Georgia") -> str:
    """The first REAL family in a CSS font stack — the name Canva can map to
    one of its own fonts. Generic and system names are skipped."""
    for part in str(stack or "").split(","):
        name = part.strip().strip("'\"").strip()
        if name and name.lower() not in _GENERIC_FONTS:
            return name
    return fallback


def hexcolor(value: str, fallback: str = "1F2937") -> str:
    """`#abc` / `#aabbcc` / `aabbcc` → `AABBCC`, or the fallback."""
    v = str(value or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", v):
        v = "".join(ch * 2 for ch in v)
    return v.upper() if re.fullmatch(r"[0-9a-fA-F]{6}", v) else fallback


def _luminance(rgb) -> float:
    r, g, b = rgb[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def cover_crop(width: int, height: int, W: int, H: int) -> dict:
    """The cover-fit crop of a `width×height` picture into a `W×H` frame, as
    the fraction cut from each side. Cover, never stretch, and centred —
    `compose.crop_placements` cuts pixels the same way; this describes the
    same cut as a crop Canva keeps adjustable."""
    if not (width and height and W and H):
        return {"l": 0.0, "t": 0.0, "r": 0.0, "b": 0.0}
    r = max(W / width, H / height)
    shown_w, shown_h = W / r / width, H / r / height          # fractions kept
    lr, tb = (1 - shown_w) / 2, (1 - shown_h) / 2
    return {"l": max(0.0, lr), "t": max(0.0, tb), "r": max(0.0, lr), "b": max(0.0, tb)}


def _cropped(img, crop: dict, W: int, H: int):
    """The picture as it will show in the frame, resized to the frame, so the
    pixels under a text block can be measured where the text will sit."""
    w, h = img.size
    box = (int(w * crop["l"]), int(h * crop["t"]),
           int(w * (1 - crop["r"])), int(h * (1 - crop["b"])))
    return img.crop(box).resize((max(1, W // 4), max(1, H // 4)))


def _wrap(text: str, chars_per_line: int) -> list[str]:
    words, lines, cur = str(text or "").split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if cur and len(trial) > max(1, chars_per_line):
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [""]


def fit_headline(text: str, area_w: int, W: int) -> tuple[int, list[str]]:
    """A type size (px) at which the headline sets in at most HEADLINE_LINES
    lines across `area_w`, shrinking from HEADLINE_MAX to HEADLINE_MIN of
    the width. Estimated at half an em per glyph — Canva substitutes the
    face, so the estimate is honest about being one."""
    size = int(W * HEADLINE_MAX)
    floor = int(W * HEADLINE_MIN)
    while True:
        lines = _wrap(text, int(area_w / (0.52 * size)))
        if len(lines) <= HEADLINE_LINES or size <= floor:
            return max(size, floor), lines
        size = max(floor, int(size * 0.92))


def layout(W: int, H: int, *, headline: str, ask: str, safe: dict | None,
           logo_aspect: float = 0.0) -> dict:
    """Where every layer sits, in pixels of the placement.

    Bottom-left inside the safe band: the ask at the bottom, the headline
    above it, the mark at the top. `safe` is Meta's Reels/Stories rule
    (fractions of the frame kept clear); without it, MARGIN of each edge.
    """
    safe = safe or {}
    side = int(W * max(MARGIN, float(safe.get("sides", 0) or 0)))
    top = int(H * max(MARGIN, float(safe.get("top", 0) or 0)))
    bottom = H - int(H * max(MARGIN, float(safe.get("bottom", 0) or 0)))
    area_w = W - 2 * side

    size, lines = fit_headline(headline, area_w, W) if headline else (int(W * HEADLINE_MIN), [])
    cta_size = max(int(W * CTA_MIN), int(size * CTA_RATIO))
    cta_h = int(cta_size * 2.2)
    cta_w = min(area_w, int(len(ask) * 0.58 * cta_size + 2.4 * cta_size)) if ask else 0

    y = bottom
    out: dict = {"size": (W, H), "side": side, "top": top, "bottom": bottom}
    if ask:
        out["cta"] = {"x": side, "y": y - cta_h, "w": cta_w, "h": cta_h, "font_px": cta_size}
        y -= cta_h + int(size * 0.6)
    if headline:
        line_h = int(size * 1.08)
        box_h = line_h * len(lines) + int(size * 0.25)
        out["headline"] = {"x": side, "y": y - box_h, "w": area_w, "h": box_h,
                           "font_px": size, "lines": lines}
        y -= box_h
    out["text_top"] = y
    if logo_aspect:
        lh = int(H * LOGO_HEIGHT)
        lw = int(lh * logo_aspect)
        if lw > W * LOGO_MAX_WIDTH:
            lw = int(W * LOGO_MAX_WIDTH)
            lh = int(lw / logo_aspect) if logo_aspect else lh
        out["logo"] = {"x": side, "y": top, "w": lw, "h": lh}
    return out


def _colour_for(img, crop: dict, W: int, H: int, region: dict | None,
                dark_text: str) -> tuple[str, str]:
    """The text colour that reads on the pixels under the type, and whether a
    scrim is needed: `(hex, scrim)` with scrim in {"", "dark", "light"}.

    Measured, not chosen: white on a pale tablecloth and charcoal on a
    night shot are the two ways a burned-in headline used to vanish.
    """
    if region is None:
        return "FFFFFF", ""
    small = _cropped(img.convert("RGB"), crop, W, H)
    sw, sh = small.size
    box = (max(0, int(region["x"] / W * sw)), max(0, int(region["y"] / H * sh)),
           min(sw, int((region["x"] + region["w"]) / W * sw) + 1),
           min(sh, int((region["y"] + region["h"]) / H * sh) + 1))
    px = list(small.crop(box).getdata()) or [(128, 128, 128)]
    lum = [_luminance(p) for p in px]
    mean = sum(lum) / len(lum)
    spread = math.sqrt(sum((v - mean) ** 2 for v in lum) / len(lum))
    white = mean < 150
    busy = spread > 55 or 95 < mean < 185
    return ("FFFFFF" if white else dark_text), (("dark" if white else "light") if busy else "")


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _image(blob: bytes):
    from PIL import Image
    return Image.open(io.BytesIO(blob))


def _emu(px: float) -> int:
    return int(round(px * EMU_PER_PX))


def _hpt(px: float) -> int:
    """Hundredths of a point from pixels."""
    return max(100, int(round(px * PT_PER_PX * 100)))


# --------------------------------------------------------------------------
# The parts of the package
# --------------------------------------------------------------------------

_NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
       'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"

_EMPTY_TREE_HEAD = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
                    '</p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/>'
                    '<a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/>'
                    '</a:xfrm></p:grpSpPr>')


def _content_types() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '</Types>')


def _rels(pairs: list[tuple[str, str, str]]) -> str:
    body = "".join(f'<Relationship Id="{i}" Type="{t}" Target="{_x(tg)}"/>' for i, t, tg in pairs)
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{_PKG}">{body}</Relationships>')


def _presentation(W: int, H: int) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<p:presentation {_NS}>'
            f'<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
            f'<p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>'
            f'<p:sldSz cx="{_emu(W)}" cy="{_emu(H)}"/>'
            f'<p:notesSz cx="6858000" cy="9144000"/></p:presentation>')


def _master() -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<p:sldMaster {_NS}><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/>'
            f'</p:bgRef></p:bg><p:spTree>{_EMPTY_TREE_HEAD}</p:spTree></p:cSld>'
            f'<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
            f'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
            f'accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
            f'<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
            f'<p:txStyles><p:titleStyle><a:lvl1pPr/></p:titleStyle>'
            f'<p:bodyStyle><a:lvl1pPr/></p:bodyStyle><p:otherStyle><a:lvl1pPr/></p:otherStyle>'
            f'</p:txStyles></p:sldMaster>')


def _layout_part() -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<p:sldLayout {_NS} type="blank" preserve="1"><p:cSld name="Blank">'
            f'<p:spTree>{_EMPTY_TREE_HEAD}</p:spTree></p:cSld>'
            f'<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')


def _theme_part(accent: str, heading: str, body: str) -> str:
    def clr(name, val):
        return f"<a:{name}><a:srgbClr val=\"{val}\"/></a:{name}>"
    fills = "".join('<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' for _ in range(3))
    lines = "".join(f'<a:ln w="{w}"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
                    for w in (9525, 25400, 38100))
    effects = "".join("<a:effectStyle><a:effectLst/></a:effectStyle>" for _ in range(3))
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="gomehagent">'
            f'<a:themeElements><a:clrScheme name="gomehagent">'
            + clr("dk1", "000000") + clr("lt1", "FFFFFF") + clr("dk2", "1C1E22") + clr("lt2", "F2F3F5")
            + "".join(clr(f"accent{i}", accent) for i in range(1, 7))
            + clr("hlink", "0563C1") + clr("folHlink", "954F72")
            + f'</a:clrScheme><a:fontScheme name="gomehagent">'
            f'<a:majorFont><a:latin typeface="{_x(heading)}"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
            f'<a:minorFont><a:latin typeface="{_x(body)}"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>'
            f'</a:fontScheme><a:fmtScheme name="gomehagent">'
            f'<a:fillStyleLst>{fills}</a:fillStyleLst><a:lnStyleLst>{lines}</a:lnStyleLst>'
            f'<a:effectStyleLst>{effects}</a:effectStyleLst><a:bgFillStyleLst>{fills}</a:bgFillStyleLst>'
            f'</a:fmtScheme></a:themeElements></a:theme>')


def _xfrm(box: dict) -> str:
    return (f'<a:xfrm><a:off x="{_emu(box["x"])}" y="{_emu(box["y"])}"/>'
            f'<a:ext cx="{_emu(box["w"])}" cy="{_emu(box["h"])}"/></a:xfrm>')


def _pic(sid: int, name: str, rid: str, box: dict, crop: dict | None = None) -> str:
    src = ""
    if crop and any(crop.get(k, 0) > 0.0005 for k in ("l", "t", "r", "b")):
        src = "<a:srcRect " + " ".join(
            f'{k}="{int(round(crop.get(k, 0) * 100000))}"' for k in ("l", "t", "r", "b")) + "/>"
    return (f'<p:pic><p:nvPicPr><p:cNvPr id="{sid}" name="{_x(name)}"/>'
            f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="{rid}"/>{src}<a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f'<p:spPr>{_xfrm(box)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')


def _rect(sid: int, name: str, box: dict, fill: str, alpha: int) -> str:
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{_x(name)}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr>{_xfrm(box)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f'<a:solidFill><a:srgbClr val="{fill}"><a:alpha val="{alpha}"/></a:srgbClr></a:solidFill>'
            f'<a:ln><a:noFill/></a:ln></p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody></p:sp>')


def _text(sid: int, name: str, box: dict, lines: list[str], *, font_px: int,
          colour: str, face: str, align: str = "l", anchor: str = "b") -> str:
    paras = "".join(
        f'<a:p><a:pPr algn="{align}"><a:lnSpc><a:spcPct val="95000"/></a:lnSpc></a:pPr>'
        f'<a:r><a:rPr lang="en-US" sz="{_hpt(font_px)}" b="1" dirty="0">'
        f'<a:solidFill><a:srgbClr val="{colour}"/></a:solidFill>'
        f'<a:latin typeface="{_x(face)}"/></a:rPr><a:t>{_x(line)}</a:t></a:r></a:p>'
        for line in lines)
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{_x(name)}"/><p:cNvSpPr txBox="1"/>'
            f'<p:nvPr/></p:nvSpPr><p:spPr>{_xfrm(box)}<a:prstGeom prst="rect"><a:avLst/>'
            f'</a:prstGeom><a:noFill/></p:spPr><p:txBody><a:bodyPr wrap="square" lIns="0" '
            f'tIns="0" rIns="0" bIns="0" anchor="{anchor}"><a:normAutofit/></a:bodyPr>'
            f'<a:lstStyle/>{paras}</p:txBody></p:sp>')


def _pill(sid: int, name: str, box: dict, text: str, *, font_px: int, fill: str,
          colour: str, face: str) -> str:
    pad = _emu(font_px * 1.0)
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{_x(name)}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr>{_xfrm(box)}<a:prstGeom prst="roundRect"><a:avLst>'
            f'<a:gd name="adj" fmla="val 50000"/></a:avLst></a:prstGeom>'
            f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="{pad}" tIns="0" rIns="{pad}" bIns="0" '
            f'anchor="ctr"/><a:lstStyle/><a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="en-US" '
            f'sz="{_hpt(font_px)}" b="1" dirty="0"><a:solidFill><a:srgbClr val="{colour}"/>'
            f'</a:solidFill><a:latin typeface="{_x(face)}"/></a:rPr><a:t>{_x(text)}</a:t></a:r>'
            f'</a:p></p:txBody></p:sp>')


def deck(frame: bytes, *, size: tuple[int, int], headline: str = "", ask: str = "",
         theme: dict | None = None, logo: bytes = b"", safe: dict | None = None,
         title: str = "Ad") -> dict:
    """One slide, four to five layers, as .pptx bytes: `{ok, pptx, layers,
    skipped, colour, scrim, font, size}`.

    `frame` is the kept picture (PNG/JPEG bytes). `theme` is the brand's
    email/brand theme (`colors.accent`, `colors.accent_text`, `colors.text`,
    `font.heading`, `font.body`) — the same record every other surface
    draws its brand from. `logo` is the mark's bytes, or nothing.
    """
    W, H = int(size[0]), int(size[1])
    if not frame or W <= 0 or H <= 0:
        return {"ok": False, "error": "no picture, or no size, to lay out"}
    try:
        img = _image(frame)
        img.load()
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"the picture could not be read: {exc.__class__.__name__}"}

    t = theme or {}
    cols, fonts = (t.get("colors") or {}), (t.get("font") or {})
    accent = hexcolor(cols.get("accent"), "1F2937")
    accent_text = hexcolor(cols.get("accent_text"), "FFFFFF")
    dark_text = hexcolor(cols.get("text"), "1C1E22")
    heading_face = family(fonts.get("heading", ""), "Georgia")
    body_face = family(fonts.get("body", ""), "Helvetica")

    headline = " ".join(str(headline or "").split())[:120]
    ask = " ".join(str(ask or "").split())[:40] or DEFAULT_ASK

    logo_img, logo_aspect, skipped = None, 0.0, {}
    if logo:
        try:
            logo_img = _image(logo)
            logo_img.load()
            logo_aspect = logo_img.width / max(1, logo_img.height)
        except Exception:                                        # noqa: BLE001
            logo_img, skipped["Logo"] = None, ("the mark is not a bitmap Canva's import "
                                               "takes (an SVG, say) — add it in Canva")
    else:
        skipped["Logo"] = "the brand has no mark on file"
    if not headline:
        skipped["Headline"] = "the frame carries no copy — set the words in Canva"

    crop = cover_crop(img.width, img.height, W, H)
    lay = layout(W, H, headline=headline, ask=ask, safe=safe, logo_aspect=logo_aspect)
    region = lay.get("headline") or lay.get("cta")
    colour, scrim = _colour_for(img, crop, W, H, region, dark_text)

    photo_png = frame if frame[:8] == b"\x89PNG\r\n\x1a\n" else _png(img.convert("RGBA"))
    media = {"image1.png": photo_png}
    rels = [("rId1", f"{_REL}/slideLayout", "../slideLayouts/slideLayout1.xml"),
            ("rId2", f"{_REL}/image", "../media/image1.png")]
    shapes = [_pic(2, "Photo", "rId2", {"x": 0, "y": 0, "w": W, "h": H}, crop)]
    made = ["Photo"]
    sid = 3
    if scrim and (lay.get("headline") or lay.get("cta")):
        top = lay["text_top"] - int(H * 0.04)
        shapes.append(_rect(sid, "Scrim", {"x": 0, "y": top, "w": W, "h": H - top},
                            "000000" if scrim == "dark" else "FFFFFF", 38000))
        made.append("Scrim")
        sid += 1
    if logo_img is not None and lay.get("logo"):
        media["image2.png"] = _png(logo_img.convert("RGBA"))
        rels.append(("rId3", f"{_REL}/image", "../media/image2.png"))
        shapes.append(_pic(sid, "Logo", "rId3", lay["logo"]))
        made.append("Logo")
        sid += 1
    if lay.get("headline"):
        hb = lay["headline"]
        shapes.append(_text(sid, "Headline", hb, hb["lines"], font_px=hb["font_px"],
                            colour=colour, face=heading_face))
        made.append("Headline")
        sid += 1
    if lay.get("cta"):
        cb = lay["cta"]
        shapes.append(_pill(sid, "CTA", cb, ask, font_px=cb["font_px"], fill=accent,
                            colour=accent_text, face=body_face))
        made.append("CTA")
        sid += 1

    slide = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             f'<p:sld {_NS}><p:cSld name="{_x(title[:60])}"><p:spTree>{_EMPTY_TREE_HEAD}'
             + "".join(shapes) +
             f'</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _content_types())
        z.writestr("_rels/.rels", _rels([
            ("rId1", f"{_REL}/officeDocument", "ppt/presentation.xml"),
            ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
             "docProps/core.xml"),
            ("rId3", f"{_REL}/extended-properties", "docProps/app.xml")]))
        z.writestr("docProps/core.xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{_x(title[:120])}</dc:title><dc:creator>gomehagent</dc:creator>'
            '</cp:coreProperties>'))
        z.writestr("docProps/app.xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            '<Application>gomehagent</Application><Slides>1</Slides></Properties>'))
        z.writestr("ppt/presentation.xml", _presentation(W, H))
        z.writestr("ppt/_rels/presentation.xml.rels", _rels([
            ("rId1", f"{_REL}/slideMaster", "slideMasters/slideMaster1.xml"),
            ("rId2", f"{_REL}/slide", "slides/slide1.xml"),
            ("rId3", f"{_REL}/theme", "theme/theme1.xml")]))
        z.writestr("ppt/slideMasters/slideMaster1.xml", _master())
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _rels([
            ("rId1", f"{_REL}/slideLayout", "../slideLayouts/slideLayout1.xml"),
            ("rId2", f"{_REL}/theme", "../theme/theme1.xml")]))
        z.writestr("ppt/slideLayouts/slideLayout1.xml", _layout_part())
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _rels([
            ("rId1", f"{_REL}/slideMaster", "../slideMasters/slideMaster1.xml")]))
        z.writestr("ppt/theme/theme1.xml", _theme_part(accent, heading_face, body_face))
        z.writestr("ppt/slides/slide1.xml", slide)
        z.writestr("ppt/slides/_rels/slide1.xml.rels", _rels(rels))
        for name, blob in media.items():
            z.writestr(f"ppt/media/{name}", blob)
    return {"ok": True, "pptx": out.getvalue(), "layers": made, "skipped": skipped,
            "colour": f"#{colour}", "scrim": scrim, "size": (W, H),
            "font": {"heading": heading_face, "body": body_face},
            "crop": crop, "layout": {k: v for k, v in lay.items()
                                     if k in ("headline", "cta", "logo", "side", "top", "bottom")}}


def read_layers(pptx: bytes) -> dict:
    """What a deck holds, read back off the package — the suite's eyes and
    the console's note: `{size, layers: [{name, kind, box, text, font, colour,
    fill}]}` with boxes in pixels."""
    import xml.etree.ElementTree as ET
    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
          "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(pptx)) as z:
        pres = ET.fromstring(z.read("ppt/presentation.xml"))
        slide = ET.fromstring(z.read("ppt/slides/slide1.xml"))
        parts = set(z.namelist())
    sz = pres.find("p:sldSz", ns)
    size = (int(int(sz.get("cx")) / EMU_PER_PX), int(int(sz.get("cy")) / EMU_PER_PX))
    tree = slide.find("p:cSld/p:spTree", ns)
    layers = []
    for el in list(tree):
        tag = el.tag.split("}")[-1]
        if tag not in ("pic", "sp"):
            continue
        name = (el.find(".//p:cNvPr", ns).get("name") or "")
        off, ext = el.find(".//a:xfrm/a:off", ns), el.find(".//a:xfrm/a:ext", ns)
        box = {"x": int(int(off.get("x")) / EMU_PER_PX), "y": int(int(off.get("y")) / EMU_PER_PX),
               "w": int(int(ext.get("cx")) / EMU_PER_PX), "h": int(int(ext.get("cy")) / EMU_PER_PX)}
        text = " ".join(t.text or "" for t in el.findall(".//a:t", ns)).strip()
        latin = el.find(".//a:rPr/a:latin", ns)
        rpr_fill = el.find(".//a:rPr/a:solidFill/a:srgbClr", ns)
        sp_fill = el.find("p:spPr/a:solidFill/a:srgbClr", ns)
        geom = el.find("p:spPr/a:prstGeom", ns)
        layers.append({
            "name": name, "kind": "picture" if tag == "pic" else "shape",
            "box": box, "text": text,
            "font": latin.get("typeface") if latin is not None else "",
            "colour": rpr_fill.get("val") if rpr_fill is not None else "",
            "fill": sp_fill.get("val") if sp_fill is not None else "",
            "geometry": geom.get("prst") if geom is not None else "",
            "cropped": el.find(".//a:srcRect", ns) is not None})
    return {"size": size, "layers": layers, "parts": sorted(parts)}


# --------------------------------------------------------------------------
# The words a frame carries — the ad's own, never a summary
# --------------------------------------------------------------------------

def first_line(body: str) -> str:
    """The ad's own opening line, for any frame that sets type. Not a summary
    and not the subject: if words go on a frame they should be the words the
    ad actually says, or the picture and the post argue two different
    things."""
    for line in str(body or "").splitlines():
        t = line.strip().lstrip("#").strip()
        if t:
            return t[:90]
    return ""


ASK_MAX = 40


def ask_line(body: str) -> str:
    """The ad's ask — its last short line that is not a hashtag row or a
    link — as the CTA's label. A closing sentence is not an ask, and gets
    nothing: the pill then says DEFAULT_ASK, which the designer retitles."""
    lines = [ln.strip() for ln in str(body or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.startswith("#") or "http" in ln.lower():
            continue
        t = re.sub(r"[\s→>›»:.!\-–—]+$", "", ln).strip().strip("*_")
        return t if 0 < len(t) <= ASK_MAX else ""
    return ""
