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
# The deck
# --------------------------------------------------------------------------



def deck(frame: bytes, *, size: tuple[int, int], headline: str = "", ask: str = "",
         theme: dict | None = None, logo: bytes = b"", safe: dict | None = None,
         title: str = "Ad") -> dict:
    """One slide, four to five layers, as .pptx bytes: `{ok, pptx, layers,
    skipped, colour, scrim, font, size}`.

    WRITTEN WITH python-pptx, not by hand. The first version assembled the
    package itself — thirteen parts, the minimum PowerPoint opens — and
    Canva's importer answered `500 server error` on it (owner, 2026-09-08).
    A package the mature writer produces carries the parts every importer
    expects (presentation defaults, view and presentation properties, table
    styles, a real master and theme), and it is what those importers see
    all day. The layout is computed here; the writer only sets it down.

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

    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(_emu(W)), Emu(_emu(H))
    blank = prs.slide_layouts[6]          # the template's "Blank" layout
    slide = prs.slides.add_slide(blank)
    made = []

    def _rgb(hexv: str):
        return RGBColor(int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16))

    def _box(b: dict) -> tuple:
        return Emu(_emu(b["x"])), Emu(_emu(b["y"])), Emu(_emu(b["w"])), Emu(_emu(b["h"]))

    pic = slide.shapes.add_picture(io.BytesIO(photo_png), *_box({"x": 0, "y": 0, "w": W, "h": H}))
    pic.name = "Photo"
    # THE COVER CROP, kept adjustable: the same cut `compose.crop_placements`
    # makes in pixels, expressed as a crop Canva keeps on the element.
    # Only a real cut is written: the library writes an empty <a:srcRect/>
    # for a zero crop, which reads as a crop to anything that looks.
    for side, attr in (("l", "crop_left"), ("r", "crop_right"), ("t", "crop_top"), ("b", "crop_bottom")):
        if crop.get(side, 0) > 0.0005:
            setattr(pic, attr, float(crop[side]))
    made.append("Photo")

    if scrim and (lay.get("headline") or lay.get("cta")):
        top = lay["text_top"] - int(H * 0.04)
        sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, *_box({"x": 0, "y": top, "w": W, "h": H - top}))
        sh.name = "Scrim"
        sh.fill.solid()
        sh.fill.fore_color.rgb = _rgb("000000" if scrim == "dark" else "FFFFFF")
        sh.line.fill.background()
        # python-pptx has no alpha API; the DrawingML element does.
        ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        srgb = sh.fill._xPr.find(f".//{ns}srgbClr")
        if srgb is not None:
            from lxml import etree
            alpha = etree.SubElement(srgb, f"{ns}alpha")
            alpha.set("val", "38000")
        sh.text_frame.text = ""
        made.append("Scrim")

    if logo_img is not None and lay.get("logo"):
        lg = slide.shapes.add_picture(io.BytesIO(_png(logo_img.convert("RGBA"))), *_box(lay["logo"]))
        lg.name = "Logo"
        made.append("Logo")

    if lay.get("headline"):
        hb = lay["headline"]
        tb = slide.shapes.add_textbox(*_box(hb))
        tb.name = "Headline"
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.BOTTOM
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Emu(0)
        for i, line in enumerate(hb["lines"]):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.alignment = PP_ALIGN.LEFT
            para.line_spacing = 0.95
            run = para.add_run()
            run.text = line
            run.font.name = heading_face
            run.font.size = Pt(hb["font_px"] * PT_PER_PX)
            run.font.bold = True
            run.font.color.rgb = _rgb(colour)
        made.append("Headline")

    if lay.get("cta"):
        cb = lay["cta"]
        pill = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, *_box(cb))
        pill.name = "CTA"
        pill.adjustments[0] = 0.5
        pill.fill.solid()
        pill.fill.fore_color.rgb = _rgb(accent)
        pill.line.fill.background()
        pt = pill.text_frame
        pt.vertical_anchor = MSO_ANCHOR.MIDDLE
        pt.margin_left = pt.margin_right = Emu(_emu(cb["font_px"]))
        pt.margin_top = pt.margin_bottom = Emu(0)
        para = pt.paragraphs[0]
        para.alignment = PP_ALIGN.CENTER
        run = para.add_run()
        run.text = ask
        run.font.name = body_face
        run.font.size = Pt(cb["font_px"] * PT_PER_PX)
        run.font.bold = True
        run.font.color.rgb = _rgb(accent_text)
        made.append("CTA")

    prs.core_properties.title = title[:120]
    prs.core_properties.author = "gomehagent"
    out = io.BytesIO()
    prs.save(out)
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
            "cropped": any(int(v or 0) for v in ((el.find(".//a:srcRect", ns).attrib.values())
                                                 if el.find(".//a:srcRect", ns) is not None else []))})
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
