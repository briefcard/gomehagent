"""Composing a creative that genuinely contains the product.

Canva's generator treats a supplied asset as inspiration. Tested against Baci's
own catalogue, it produced four ads with four invented pitchers — so a skill
that must be able to say "this is our product" cannot be built on it. What is
built here instead places the product because it draws it there; there is
nothing to verify afterwards.

Two treatments, because both are wanted and they fail differently:

  · `product_on_colour` — the cutout on a brand ground with the claim beside
    it. Catalogue-clean, ships with no dependency on anything generated.

  · `product_on_scene` — the cutout composited onto a styled plate: a laid
    table, linens, daylight. More authentic, and the one that looks cheap if
    done naively, because a cutout dropped onto a photograph reads as pasted.
    `_contact_shadow` is most of the difference: a real object darkens the
    surface it stands on, and without that the eye rejects the image long
    before it reads the words.

Baci's product photography is already what this needs — verified 1200×1200 with
a real alpha channel and fully transparent corners.

**A reference asset is refused.** `rights` is the gate everywhere else in the
library and it has to be the gate here too: compositing a competitor's
photograph into an ad is the exact outcome that axis exists to prevent, and it
would be invisible in the output.
"""
from __future__ import annotations

import io

from . import kb

# One width, three shapes. Meta wants 1:1 and 4:5 in feed and 9:16 in stories,
# and re-cropping one export by hand is how the story version ends up with the
# headline off the top.
SIZES: dict[str, tuple[int, int]] = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
}

# Tried in order. The chain exists because this runs on a Mac in development
# and Linux in production, and a missing font must not mean a missing image.
_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
)


def _font(size: int) -> tuple[object, str]:
    """A real font and its name, or the bitmap default and a loud label.

    The name is returned rather than kept, because rendering a brand's headline
    in whatever font happened to be installed is a brand violation that looks
    like a success. The caller reports it the same way `ad_copy` reports
    `basis` — the failure has to survive into the output.
    """
    from PIL import ImageFont
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size), path.rsplit("/", 1)[-1]
        except Exception:                                        # noqa: BLE001
            continue
    return ImageFont.load_default(), "PIL default (NO REAL FONT FOUND)"


def _surface_tint(plate, baseline: float) -> tuple[int, int, int]:
    """The colour of the surface the product will stand on.

    A shadow is not black, it is the surface with the light taken out of it.
    Tinting to the actual plate is what stops a composite reading as a sticker
    on a photograph — a neutral grey shadow on a warm linen table is the giveaway.
    """
    W, H = plate.size
    y = max(0, min(H - 2, int(H * baseline)))
    strip = plate.convert("RGB").crop((int(W * 0.25), y, int(W * 0.75),
                                       min(H, y + max(2, int(H * 0.04)))))
    small = strip.resize((1, 1))
    r, g, b = small.getpixel((0, 0))
    return int(r * 0.42), int(g * 0.40), int(b * 0.38)


def _contact_shadow(product, opacity: int = 150,
                    tint: tuple[int, int, int] = (28, 22, 16)):
    """A soft shadow under the product's footprint, from its own silhouette.

    Taking the bottom slice of the alpha mask rather than the whole shape is
    what makes it read as contact: a shadow shaped like the entire pitcher is a
    silhouette lying on the floor, which is the pasted look with an extra step.

    The first version was invisible. Two reasons, both worth keeping written
    down: the footprint of a pitcher is its narrow foot, so a shadow at the
    object's own width all but vanishes once blurred — a real one spreads
    WIDER than what casts it; and the blur radius was tied to a constant rather
    than to the shadow's height, so at any reasonable product size it washed
    out completely.
    """
    from PIL import Image, ImageFilter
    w, h = product.size
    alpha = product.getchannel("A")
    foot = alpha.crop((0, int(h * 0.80), w, h))
    # Wider than the object and shallow: light comes from above and to the
    # side, so contact spreads sideways rather than straight down.
    sw, sh = int(w * 1.25), max(14, int(h * 0.085))
    foot = foot.resize((sw, sh), Image.LANCZOS)
    foot = foot.point(lambda v: int(min(255, v) * opacity / 255))
    shadow = Image.new("RGBA", (sw, sh), (*tint, 0))
    shadow.putalpha(foot)
    pad = int(sh * 1.2)
    canvas = Image.new("RGBA", (sw + pad * 2, sh + pad * 2), (0, 0, 0, 0))
    canvas.paste(shadow, (pad, pad), shadow)
    return canvas.filter(ImageFilter.GaussianBlur(sh * 0.42))


def _load(data: bytes):
    from PIL import Image
    return Image.open(io.BytesIO(data)).convert("RGBA")


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = (text or "").split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _draw_text(img, headline: str, subline: str, *, colour: str,
               top_frac: float, margin_frac: float = 0.09,
               shadow: bool = False) -> str:
    """Set the type. `shadow` is a whisper, not a panel.

    An earlier version laid a gradient scrim behind the text so it would be
    readable on anything. It worked and it looked like a template — a band
    across every image regardless of what was underneath. Contrast does the
    same job: the colour is already chosen from the brightness of the band the
    text lands in, and where that is not quite enough a soft offset shadow at
    low opacity carries it without putting a shape on the picture.
    """
    from PIL import Image, ImageDraw, ImageFilter
    W, H = img.size
    margin = int(W * margin_frac)
    h_font, fname = _font(int(W * 0.085))
    s_font, _ = _font(int(W * 0.036))

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def _lines():
        y = int(H * top_frac)
        for line in _wrap(d, headline, h_font, W - margin * 2):
            yield line, h_font, y
            y += int(W * 0.098)
        if subline:
            y += int(W * 0.018)
            for line in _wrap(d, subline, s_font, W - margin * 2):
                yield line, s_font, y
                y += int(W * 0.048)

    if shadow:
        dark_text = colour.lower() in ("#16130f", "#1a1a1a", "#2a241c")
        glow = (255, 255, 255, 90) if dark_text else (0, 0, 0, 95)
        sl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sl)
        off = max(1, int(W * 0.0022))
        for line, font, y in _lines():
            sd.text((margin + off, y + off), line, font=font, fill=glow)
        img.alpha_composite(sl.filter(ImageFilter.GaussianBlur(off * 1.6)))

    for line, font, y in _lines():
        d.text((margin, y), line, font=font, fill=colour)
    img.alpha_composite(layer)
    return fname


def _place_product(canvas, product, *, width_frac: float, baseline: float,
                   shadow: bool, tint: tuple[int, int, int] | None = None):
    """Scale the cutout, ground it, paste it. Bottom-anchored, not centred.

    Anchoring to where the object MEETS THE SURFACE is why this takes a
    baseline: centring a pitcher and a low bowl the same way floats one and
    buries the other, and the surface line is the thing both share.
    """
    from PIL import Image
    W, H = canvas.size
    target_w = int(W * width_frac)
    scale = target_w / product.width
    p = product.resize((target_w, int(product.height * scale)), Image.LANCZOS)
    x = (W - p.width) // 2
    bottom = int(H * baseline)
    if shadow:
        sh = _contact_shadow(p, tint=tint or (28, 22, 16))
        canvas.alpha_composite(
            sh, (x - (sh.width - p.width) // 2,
                 bottom - sh.height // 2 - int(sh.height * 0.06)))
    canvas.alpha_composite(p, (x, bottom - p.height))
    return canvas


def _render(size_key: str, *, product: bytes, headline: str, subline: str,
            background: str | bytes, text_colour: str, width_frac: float,
            baseline: float, shadow: bool, top_frac: float) -> tuple[bytes, str]:
    from PIL import Image
    W, H = SIZES[size_key]
    if isinstance(background, bytes):
        plate = _load(background)
        # Cover, not stretch: a laid table squashed into 9:16 stops looking
        # like a photograph of anything.
        r = max(W / plate.width, H / plate.height)
        plate = plate.resize((int(plate.width * r), int(plate.height * r)),
                             Image.LANCZOS)
        canvas = Image.new("RGBA", (W, H))
        canvas.paste(plate, ((W - plate.width) // 2, (H - plate.height) // 2))
    else:
        canvas = Image.new("RGBA", (W, H), background)

    tint = _surface_tint(canvas, baseline) if shadow else None
    canvas = _place_product(canvas, _load(product), width_frac=width_frac,
                            baseline=baseline, shadow=shadow, tint=tint)
    fname = _draw_text(canvas, headline, subline, colour=text_colour,
                       top_frac=top_frac)
    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue(), fname


def _guard(tenant: str, asset_id: str) -> tuple[bytes, str]:
    """The product's pixels, or a refusal. Rights are checked here too."""
    if not asset_id:
        return b"", "Name the product asset to place."
    ok, why = kb.may_publish(asset_id)
    if not ok:
        return b"", f"that asset cannot be used in an ad: {why}"
    from . import db
    with db.SessionLocal() as s:
        row = s.get(db.KbAsset, asset_id)
        if not row or row.tenant != tenant:
            return b"", "no such asset for this account"
        url = row.url
    import httpx
    try:
        r = httpx.get(url, timeout=45, follow_redirects=True)
        r.raise_for_status()
    except Exception as exc:                                     # noqa: BLE001
        return b"", f"could not fetch the product image: {exc.__class__.__name__}"
    return r.content, ""


def product_on_colour(tenant: str, asset_id: str, *, headline: str,
                      subline: str = "", background: str = "#EFEAE3",
                      text_colour: str = "#1A1A1A",
                      formats: list[str] | None = None) -> dict:
    """The cutout on a flat brand ground. No dependency on anything generated."""
    product, why = _guard(tenant, asset_id)
    if why:
        return {"ok": False, "error": why}
    out, font_used = {}, ""
    for k in (formats or ["1:1", "4:5", "9:16"]):
        if k not in SIZES:
            return {"ok": False, "error": f"unknown format {k!r}"}
        out[k], font_used = _render(
            k, product=product, headline=headline, subline=subline,
            background=background, text_colour=text_colour,
            width_frac=0.62, baseline=0.90, shadow=False, top_frac=0.08)
    return {"ok": True, "images": out, "font": font_used,
            "treatment": "product_on_colour",
            "real_font": "NO REAL FONT" not in font_used}


def product_on_scene(tenant: str, asset_id: str, plate: bytes, *,
                     headline: str, subline: str = "",
                     text_colour: str = "#FFFFFF",
                     formats: list[str] | None = None) -> dict:
    """The cutout composited onto a styled plate, grounded with a shadow.

    The plate is scenery only — a laid table, linens, daylight — and must be
    generated or shot WITHOUT a product in it. Asking a generator for a table
    with a pitcher on it and then pasting a second pitcher beside it is the
    failure this whole approach exists to avoid.
    """
    product, why = _guard(tenant, asset_id)
    if why:
        return {"ok": False, "error": why}
    if not plate:
        return {"ok": False, "error": "No background plate supplied."}
    out, font_used = {}, ""
    for k in (formats or ["1:1", "4:5", "9:16"]):
        if k not in SIZES:
            return {"ok": False, "error": f"unknown format {k!r}"}
        out[k], font_used = _render(
            k, product=product, headline=headline, subline=subline,
            background=plate, text_colour=text_colour,
            width_frac=0.52, baseline=0.86, shadow=True, top_frac=0.07)
    return {"ok": True, "images": out, "font": font_used,
            "treatment": "product_on_scene",
            "real_font": "NO REAL FONT" not in font_used}


def composite_on_plate(product_png: bytes, plate_png: bytes, *, headline: str,
                       subline: str = "", text_colour: str = "#2A241C",
                       formats: list[str] | None = None) -> dict:
    """The real product photograph onto a supplied plate. No KB lookup.

    Separate from `product_on_scene` because that one resolves an asset id and
    enforces rights, which is right when a skill calls it and wrong when the
    caller already holds the bytes — as `imagegen.scene_with_real_product`
    does, having just generated the plate itself.
    """
    if not product_png or not plate_png:
        return {"ok": False, "error": "Both a product and a plate are needed."}
    out, font_used = {}, ""
    for k in (formats or ["1:1", "4:5", "9:16"]):
        if k not in SIZES:
            return {"ok": False, "error": f"unknown format {k!r}"}
        out[k], font_used = _render(
            k, product=product_png, headline=headline, subline=subline,
            background=plate_png, text_colour=text_colour,
            width_frac=0.52, baseline=0.86, shadow=True, top_frac=0.07)
    return {"ok": True, "images": out, "font": font_used,
            "treatment": "real_product_on_generated_plate",
            "real_font": "NO REAL FONT" not in font_used}


# ---------------------------------------------------------------------------
# The treatment that works for every client
#
# Cutout compositing only ever fitted one shape of business. Baci sells objects
# with a silhouette; Coverings sells surfaces, where the tile IS the surface and
# standing it on a table is meaningless; Ironside sells places, and a room
# cannot be cut out at all. What all three have is a photograph somebody took
# on purpose, and a thing to say over it.
# ---------------------------------------------------------------------------

def _quiet_band(img, bands: int = 6, avoid_bottom: float = 0.12) -> int:
    """Which horizontal band of the photograph is calmest, as an index.

    Type over a busy region is unreadable, and where the calm region sits is
    not a house style — it is a fact about each photograph. A packed venue
    interior is quiet at the ceiling; a tiled wall may be quiet nowhere; a
    product on a sweep is quiet everywhere but the middle. Measuring beats
    choosing a corner and hoping.

    Variance of a downsampled greyscale, which is cheap and good enough: it
    finds flat sky, plain wall and empty tablecloth, and correctly refuses to
    call a mosaic quiet.
    """
    from PIL import Image
    g = img.convert("L").resize((64, 64 * bands // bands), Image.LANCZOS)
    W, H = g.size
    usable = int(H * (1 - avoid_bottom))          # keep clear of a logo strip
    best, best_var = 0, None
    for i in range(bands):
        top = int(usable * i / bands)
        bot = int(usable * (i + 1) / bands)
        px = list(g.crop((0, top, W, max(top + 1, bot))).getdata())
        if not px:
            continue
        mean = sum(px) / len(px)
        var = sum((p - mean) ** 2 for p in px) / len(px)
        if best_var is None or var < best_var:
            best, best_var = i, var
    return best


def photo_with_headline(photo: bytes, *, headline: str, subline: str = "",
                        formats: list[str] | None = None,
                        force_band: int | None = None) -> dict:
    """Any photograph, any client, plus something to say.

    The one treatment that fits a plate, a tile and a venue identically, because
    it makes no assumption about what is in the picture. No cutout, no
    generation, nothing to hallucinate — the image is the client's own.

    Text lands in the calmest band of each crop and gets a scrim tuned to that
    band's brightness, so the same call produces readable type over a white
    studio sweep and a dark restaurant without anyone picking a colour.
    """
    if not photo:
        return {"ok": False, "error": "No photograph supplied."}
    from PIL import Image, ImageStat
    out, font_used = {}, ""
    placements = {}
    for k in (formats or ["1:1", "4:5", "9:16"]):
        if k not in SIZES:
            return {"ok": False, "error": f"unknown format {k!r}"}
        W, H = SIZES[k]
        src = _load(photo)
        r = max(W / src.width, H / src.height)
        src = src.resize((int(src.width * r), int(src.height * r)), Image.LANCZOS)
        canvas = Image.new("RGBA", (W, H))
        canvas.paste(src, ((W - src.width) // 2, (H - src.height) // 2))

        bands = 6
        band = force_band if force_band is not None else _quiet_band(canvas, bands)
        block_h = int(H * 0.30)
        top = min(int(H * (1 - 0.12)) - block_h,
                  max(0, int(H * (band / bands))))

        region = canvas.crop((0, top, W, min(H, top + block_h))).convert("L")
        stat = ImageStat.Stat(region)
        dark_bg = stat.mean[0] < 128
        colour = "#FFFFFF" if dark_bg else "#16130F"
        # A shadow only where contrast alone will not carry it: a busy or
        # mid-toned band. On a clean sweep or a flat dark wall the type is
        # legible unaided, and adding a shadow there is decoration.
        busy = stat.stddev[0] > 34 or 92 < stat.mean[0] < 168
        font_used = _draw_text(canvas, headline, subline, colour=colour,
                               top_frac=(top + int(H * 0.035)) / H,
                               shadow=busy)
        placements[k] = {"band": band, "dark_background": dark_bg,
                         "text_colour": colour, "shadow": busy,
                         "contrast": round(stat.stddev[0], 1)}
        buf = io.BytesIO()
        canvas.convert("RGB").save(buf, format="PNG", optimize=True)
        out[k] = buf.getvalue()
    return {"ok": True, "images": out, "font": font_used,
            "treatment": "photo_with_headline", "placement": placements,
            "real_font": "NO REAL FONT" not in font_used,
            "note": "the photograph is the client's own and untouched — nothing "
                    "was generated or composited, so there is nothing here that "
                    "could be the wrong product, tile or room"}
