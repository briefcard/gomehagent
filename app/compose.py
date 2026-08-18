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
               top_frac: float, margin_frac: float = 0.09) -> str:
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    W, H = img.size
    margin = int(W * margin_frac)
    h_font, fname = _font(int(W * 0.085))
    s_font, _ = _font(int(W * 0.036))
    y = int(H * top_frac)
    for line in _wrap(d, headline, h_font, W - margin * 2):
        d.text((margin, y), line, font=h_font, fill=colour)
        y += int(W * 0.098)
    if subline:
        y += int(W * 0.018)
        for line in _wrap(d, subline, s_font, W - margin * 2):
            d.text((margin, y), line, font=s_font, fill=colour)
            y += int(W * 0.048)
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
