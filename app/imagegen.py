"""Generated imagery, with the product checked rather than trusted.

Two jobs, and the difference between them is the whole point.

`plate()` generates scenery — a laid table, linen, daylight — with **no product
in it**. There is nothing to get wrong: the product arrives later, from
`compose`, and is correct because we draw it. This is the safe route and it is
what the inspiration reference is for.

`place_product()` is the one Gomeh has done by hand: hand the model the clean
cutout, describe the setting, let it build the scene around the object.

It is done with a **mask**, and that choice came from measuring the
alternative. The first version generated freely and then scored the result
against the source to catch drift — a model given your pitcher can return
something 95% like it, and that is more dangerous than the obviously invented
pitchers Canva produced because it survives a glance and ships. The score
turned out to be far too weak to gate on: the real product scored 0.433 and a
different-coloured, handleless impostor scored 0.356, a gap of 0.077 that
ordinary lighting variation would swamp.

**That mask turned out to be advisory, and this module overclaimed.** It was
written asserting the product's pixels come back exactly as sent. Gomeh tested
it and they do not: the pitcher's clear acrylic handle came back opaque white
and the body lost its depth. The alpha tells the story — only 0.77% of that
image is partially transparent, so the handle is opaque pixels with pale RGB,
comfortably inside the protected region. The model repainted it regardless.
`gpt-image-1`'s edit endpoint regenerates a frame; it is not a classical
inpaint that guarantees untouched pixels.

So `place_product` is the *fast, integrated* route and it can be wrong about
the product. `scene_with_real_product` is the one that cannot: the model paints
an empty plate, and the real product is composited onto it by us. Guaranteed
fidelity now costs a compositing step rather than a promise.

`similarity()` survives as a REPORTED diagnostic, never a gate. It is honest
about what it is: a coarse screen that catches a wholly different object and
misses a faithfully redrawn one.
"""
from __future__ import annotations

import base64
import io

from . import config

BASE = "https://api.openai.com/v1"
MODEL = "gpt-image-1"
TIMEOUT = 180

# What the model will actually return. Asking it for 9:16 gets a refusal or a
# stretched frame, so generation happens at a native size and `compose` cuts the
# ad shapes from it — that is already its job for a photographic plate.
SIZES = {"square": "1024x1024", "landscape": "1536x1024", "portrait": "1024x1536"}

# Reported alongside every candidate, never used as a gate — see the module
# docstring for why the measurement failed as one.
MIN_SIMILARITY = 0.62


def _key() -> tuple[str, str]:
    if not config.OPENAI_API_KEY:
        return "", ("OPENAI_API_KEY is not set — the same key `embed.py` uses "
                    "for embeddings.")
    return config.OPENAI_API_KEY, ""


def _post(path: str, *, json_body: dict | None = None,
          files: list | None = None, data: dict | None = None) -> dict:
    key, why = _key()
    if why:
        return {"ok": False, "error": why}
    import httpx
    try:
        r = httpx.post(f"{BASE}{path}", timeout=TIMEOUT,
                       headers={"Authorization": f"Bearer {key}"},
                       json=json_body, files=files, data=data)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
    if r.status_code >= 400:
        try:
            msg = (r.json().get("error") or {}).get("message", "")
        except Exception:                                        # noqa: BLE001
            msg = r.text[:200]
        return {"ok": False, "error": f"{r.status_code}: {msg}"[:300]}
    try:
        body = r.json()
    except Exception:                                            # noqa: BLE001
        return {"ok": False, "error": "the image API returned no JSON"}
    out = []
    for item in body.get("data") or []:
        b64 = item.get("b64_json")
        if b64:
            out.append(base64.b64decode(b64))
    if not out:
        return {"ok": False, "error": "the image API returned no image data"}
    return {"ok": True, "images": out}


post = _post          # replaceable, so the suite can drive every path


# ---------------------------------------------------------------------------
# Is the thing in the picture the thing we sent?
# ---------------------------------------------------------------------------

def _dhash(im, size: int = 16) -> int:
    """A difference hash. Structure, not pixels — robust to light and scale."""
    from PIL import Image
    g = im.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            left = px[row * (size + 1) + col]
            right = px[row * (size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def _trim(im):
    """Crop a cutout to its own silhouette, so padding is not compared."""
    if im.mode != "RGBA":
        return im
    box = im.getchannel("A").getbbox()
    return im.crop(box) if box else im


def similarity(product_png: bytes, generated_png: bytes,
               region: tuple[float, float, float, float] =
               (0.18, 0.22, 0.82, 0.94)) -> float:
    """0..1, how much the generated frame's product area resembles the source.

    Structure (a difference hash) and palette (a coarse colour histogram) are
    both counted, because either alone is fooled in an obvious way: a hash
    matches a pitcher-shaped object of any colour, and a histogram matches any
    picture with the same amount of white in it.

    The region is where a composed product ad puts the object. It is a
    heuristic — see the module docstring. It catches a different product; it
    will not catch a faithfully redrawn one.
    """
    from PIL import Image
    src = _trim(Image.open(io.BytesIO(product_png)).convert("RGBA"))
    gen = Image.open(io.BytesIO(generated_png)).convert("RGB")
    W, H = gen.size
    crop = gen.crop((int(W * region[0]), int(H * region[1]),
                     int(W * region[2]), int(H * region[3])))

    # On white, so a transparent cutout and a product on a bright table are
    # compared on the same ground rather than on alpha.
    flat = Image.new("RGB", src.size, (255, 255, 255))
    flat.paste(src, (0, 0), src)

    a, b = _dhash(flat), _dhash(crop)
    bits = bin(a ^ b).count("1")
    structure = 1.0 - (bits / 256.0)

    def _hist(im):
        q = im.resize((64, 64), Image.LANCZOS).quantize(colors=16).convert("RGB")
        h = q.histogram()
        total = sum(h) or 1
        return [v / total for v in h]

    ha, hb = _hist(flat), _hist(crop)
    palette = 1.0 - sum(abs(x - y) for x, y in zip(ha, hb)) / 2.0
    return round(max(0.0, min(1.0, structure * 0.6 + palette * 0.4)), 3)


# ---------------------------------------------------------------------------
# The two jobs
# ---------------------------------------------------------------------------

_PLATE_RULE = (
    "The surface in the centre foreground must be COMPLETELY EMPTY — no "
    "tableware, no jug, no pitcher, no glass, no bowl, no plate, no product of "
    "any kind, and no people. This image is a background onto which a product "
    "will be placed afterwards; anything already standing there ruins it."
)


def plate(prompt: str, *, shape: str = "square", n: int = 1,
          inspiration: str = "") -> dict:
    """Scenery with no product in it. The safe half of the generative route.

    `inspiration` is a description of a reference — a Pinterest board, a shot
    the client likes — put into words rather than uploaded. That keeps a
    reference image out of the generation entirely, which matters: a scene
    generated FROM someone else's photograph is a derivative of it, and it
    would arrive with no marker saying so.
    """
    if shape not in SIZES:
        return {"ok": False, "error": f"unknown shape {shape!r}"}
    body = {"model": MODEL, "size": SIZES[shape], "n": max(1, min(4, n)),
            "prompt": f"{prompt}\n\n{('Styling reference: ' + inspiration) if inspiration else ''}"
                      f"\n\n{_PLATE_RULE}".strip()}
    res = post("/images/generations", json_body=body)
    if not res["ok"]:
        return res
    return {"ok": True, "images": res["images"], "shape": shape,
            "note": "background only — no product was generated, so there is "
                    "nothing here that could be the wrong product"}


def _protect_mask(product_png: bytes, canvas: tuple[int, int]) -> tuple[bytes, bytes]:
    """The base frame and the mask that keeps the product out of the model's hands.

    OpenAI's edit endpoint repaints where the mask is TRANSPARENT and leaves
    the rest alone. So the mask is opaque exactly over the product silhouette,
    slightly grown: a mask cut tight to the alpha leaves a one-pixel rim of the
    original background for the model to blend against, and that rim is what
    makes a composite look cut out.
    """
    from PIL import Image, ImageFilter
    W, H = canvas
    src = Image.open(io.BytesIO(product_png)).convert("RGBA")
    box = src.getchannel("A").getbbox()
    if box:
        src = src.crop(box)
    scale = min((W * 0.52) / src.width, (H * 0.58) / src.height)
    src = src.resize((max(1, int(src.width * scale)),
                      max(1, int(src.height * scale))), Image.LANCZOS)
    x, y = (W - src.width) // 2, int(H * 0.86) - src.height

    base = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    base.alpha_composite(src, (x, y))

    silhouette = Image.new("L", (W, H), 0)
    silhouette.paste(src.getchannel("A"), (x, y))
    # Erode, then dilate — a morphological opening. Product photography carries
    # a few stray non-transparent pixels in its alpha (dust, a rescue-from-JPEG
    # rim), and dilating those directly turns each speck into a protected island
    # that survives as a white fleck in the middle of the generated scene. The
    # erosion removes anything thinner than itself before the growth restores
    # the real silhouette.
    despeckled = silhouette.filter(ImageFilter.MinFilter(3))
    grown = despeckled.filter(ImageFilter.MaxFilter(7))
    mask = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mask.putalpha(grown.point(lambda v: 255 if v > 8 else 0))

    b1, b2 = io.BytesIO(), io.BytesIO()
    base.save(b1, format="PNG")
    mask.save(b2, format="PNG")
    return b1.getvalue(), b2.getvalue()


def place_product(product_png: bytes, prompt: str, *, shape: str = "square",
                  n: int = 2, inspiration: str = "") -> dict:
    """Build a scene around the real product, which the mask keeps untouched.

    Every candidate still carries a similarity score, because a mask the API
    honours in principle is worth checking in practice — but the score is
    reported, not enforced. It is too coarse to be a gate; the mask is the
    guarantee.
    """
    if shape not in SIZES:
        return {"ok": False, "error": f"unknown shape {shape!r}"}
    if not product_png:
        return {"ok": False, "error": "No product image supplied."}
    w, h = (int(v) for v in SIZES[shape].split("x"))
    base, mask = _protect_mask(product_png, (w, h))

    instruction = (
        f"{prompt}\n\n"
        f"{('Styling reference: ' + inspiration) if inspiration else ''}\n\n"
        "Build the surroundings around the object already in the frame and "
        "light them to match it. Give it a believable contact shadow on the "
        "surface it stands on. Do not add a second one of the same item."
    ).strip()

    res = post("/images/edits",
               files=[("image", ("base.png", base, "image/png")),
                      ("mask", ("mask.png", mask, "image/png"))],
               data={"model": MODEL, "size": SIZES[shape],
                     "n": str(max(1, min(4, n))), "prompt": instruction})
    if not res["ok"]:
        return res

    out = []
    for img in res["images"]:
        out.append({"image": img, "similarity": similarity(product_png, img)})
    return {
        "ok": True, "candidates": out,
        "best": max((c["similarity"] for c in out), default=0.0),
        "protected": False,
        "note": "the mask is ADVISORY to this endpoint, not binding — it "
                "regenerates the frame rather than preserving pixels. Check "
                "every candidate against the real product.",
        "caveat": "measured failure: a clear acrylic handle came back opaque "
                  "white and the form lost its depth. For guaranteed fidelity "
                  "use scene_with_real_product(), which composites the actual "
                  "photograph onto a generated empty plate.",
    }


def scene_with_real_product(product_png: bytes, prompt: str, *,
                            headline: str = "", subline: str = "",
                            inspiration: str = "", shape: str = "square",
                            text_colour: str = "#2A241C",
                            formats: list[str] | None = None) -> dict:
    """A generated setting with the ACTUAL product photograph composited on.

    The route that cannot be wrong about the product, because no model ever
    sees it: `plate()` paints an empty table, and `compose` alpha-composites
    the real cutout onto it. The clear handle stays clear because those are the
    photographed pixels.

    What it gives up is integration — the light on the product is the light
    from the product shoot, not from the generated scene. `compose` grounds it
    with a contact shadow tinted to the plate, which carries most of the way;
    a product shot under very different light will still read as inserted.
    """
    from . import compose
    made = plate(prompt, shape=shape, inspiration=inspiration, n=1)
    if not made["ok"]:
        return made
    out = compose.composite_on_plate(
        product_png, made["images"][0], headline=headline, subline=subline,
        text_colour=text_colour, formats=formats)
    if not out["ok"]:
        return out
    return {**out, "plate_generated": True,
            "note": "the product is the photograph, pixel for pixel — no model "
                    "drew it. Only the setting was generated."}
