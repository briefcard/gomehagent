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

BASE = config.IMAGE_API_BASE
MODEL = config.IMAGE_MODEL
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
    """One image-API call, RECORDED. This is the single door, and until
    2026-09-04 nothing that went through it was written to the ledger: a
    missing key or a failing model degraded to a placeholder with `basis`
    saying so inside the batch, and no surface anywhere said "images are
    failing". Same defect the Semrush client was fixed for, and the same fix —
    every call lands in `db.ToolCall` under provider `openai_images`, the
    refusal included, so Diagnostics shows it as a failing provider."""
    import time as _clock
    from . import toolcalls as _tc
    _t0 = _clock.monotonic()

    def _log(ok: bool, err: str = "", size: int = 0) -> None:
        _tc.record("", f"images{path}", source="creative", provider="openai_images",
                   ok=ok, error=err, ms=int((_clock.monotonic() - _t0) * 1000),
                   bytes_back=size)

    key, why = _key()
    if why:
        _log(False, why)
        return {"ok": False, "error": why}
    import httpx
    try:
        r = httpx.post(f"{BASE}{path}", timeout=TIMEOUT,
                       headers={"Authorization": f"Bearer {key}"},
                       json=json_body, files=files, data=data)
    except Exception as exc:                                     # noqa: BLE001
        _log(False, exc.__class__.__name__)
        return {"ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
    if r.status_code >= 400:
        try:
            msg = (r.json().get("error") or {}).get("message", "")
        except Exception:                                        # noqa: BLE001
            msg = r.text[:200]
        _log(False, f"{r.status_code}: {msg}"[:160])
        return {"ok": False, "error": f"{r.status_code}: {msg}"[:300]}
    try:
        body = r.json()
    except Exception:                                            # noqa: BLE001
        _log(False, "no JSON")
        return {"ok": False, "error": "the image API returned no JSON"}
    # Size from whatever the response object has: the spend suite stubs the
    # transport with an object that carries `.json()` and no `.content`.
    _log(True, size=len(getattr(r, "content", b"") or b""))
    out = []
    for item in body.get("data") or []:
        b64 = item.get("b64_json")
        if b64:
            out.append(base64.b64decode(b64))
    if not out:
        return {"ok": False, "error": "the image API returned no image data"}
    # CHARGED HERE, at the one seam every generation returns through, so a
    # generator added next month cannot be added without it. Images are the
    # most expensive single thing this system does — roughly two thousand
    # text calls each — and were the one thing the spend report could not
    # see, because generation went to OpenAI over raw HTTP and logged nothing.
    try:
        from . import usage
        usage.log_image("image_edit" if "edits" in path else "image_generate",
                        MODEL, len(out))
    except Exception:                                            # noqa: BLE001
        pass
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

#: ONE STRING WAS CARRYING TWO UNRELATED PROHIBITIONS, and they have opposite
#: scopes. "Invent no product" must hold for EVERY frame — a generated pitcher
#: is not this client's pitcher, and that is the failure this whole
#: architecture was built after. "No people, the foreground is empty" is true
#: only of a plate that is about to RECEIVE a photograph. Concatenating them
#: unconditionally meant `'no people' in prompt` was 8/8 across the grid,
#: including the `person_led` cell whose own brief says a person is the
#: subject — and Miami Ironside, which gets only the person-led and context
#: cells, had every single frame commissioned as an empty room with nobody in
#: it. Splitting them is the fix; merging them again is the regression.
_NO_INVENTED_PRODUCT = (
    "Do not invent or depict any branded or identifiable product — no "
    "tableware, no jug, no pitcher, no glass, no bowl, no plate, no bottle, "
    "no packaging, no product of any kind. Any product in the finished piece "
    "is a real photograph placed by hand; one you invent is the wrong one."
)

#: Only when a photograph is going INTO this frame afterwards.
_EMPTY_FOR_PLACEMENT = (
    "The surface in the centre foreground must be COMPLETELY EMPTY, and there "
    "must be no people in the frame. This image is a background onto which a "
    "product will be placed afterwards; anything already standing there ruins "
    "it."
)

#: And the positive half. Deleting a prohibition is not the same as asking for
#: the thing — a cell briefed "a person is the subject" that merely stops
#: being told "no people" still tends to return an empty room, because the
#: rest of the prompt describes a place.
_PEOPLE_ARE_THE_SUBJECT = (
    "A PERSON IS THE SUBJECT of this frame. Show them using, holding, "
    "choosing or living with the thing the piece is about — hands, posture "
    "and attention doing the work. Not a portrait, and not an empty room."
)


#: EXTRA DIRECTION WHEN A REAL PRODUCT IS GOING INTO THIS PLATE. The generic
#: rule above only says "leave the surface empty", which produces a pretty
#: room the product then sits on top of — the "pasted onto another image"
#: the owner reported. A plate meant to receive a photograph has to be LIT
#: and FRAMED for it: one dominant light with a direction a shadow can
#: follow, a continuous surface where the object will stand, and the camera
#: at the height the product was shot at. None of this makes the composite
#: perfect; it is what makes it possible.
_PLATE_FOR_PRODUCT = (
    "A REAL PHOTOGRAPH OF A PRODUCT WILL BE PLACED INTO THIS SCENE, standing "
    "on the surface in the centre foreground. Compose for that: leave the "
    "middle of the frame clear across about half its width and the lower "
    "third of its height, with the surface continuous and unpatterned there. "
    "Light the whole scene from ONE dominant soft source, high and slightly "
    "to the left, so everything in frame casts a shadow in the same "
    "direction and an object added later can match it. Shoot at table "
    "height, lens level with the surface, not looking down at it. Keep the "
    "colour temperature neutral daylight."
)


def plate(prompt: str, *, shape: str = "square", n: int = 1,
          inspiration: str = "", for_product: bool = False,
          with_people: bool = False, model: str = "") -> dict:
    """Scenery with no product in it. The safe half of the generative route.

    `inspiration` is a description of a reference — a Pinterest board, a shot
    the client likes — put into words rather than uploaded. That keeps a
    reference image out of the generation entirely, which matters: a scene
    generated FROM someone else's photograph is a derivative of it, and it
    would arrive with no marker saying so.
    """
    if shape not in SIZES:
        return {"ok": False, "error": f"unknown shape {shape!r}"}
    rules = [_NO_INVENTED_PRODUCT]
    if for_product:
        rules += [_EMPTY_FOR_PLACEMENT, _PLATE_FOR_PRODUCT]
    if with_people:
        rules.append(_PEOPLE_ARE_THE_SUBJECT)
    body = {"model": model or MODEL, "size": SIZES[shape],
            "n": max(1, min(4, n)),
            "prompt": "\n\n".join(
                [prompt]
                + (["Styling reference: " + inspiration] if inspiration else [])
                + rules).strip()}
    res = post("/images/generations", json_body=body)
    if not res["ok"]:
        return res
    return {"ok": True, "images": res["images"], "shape": shape,
            "note": "background only — no product was generated, so there is "
                    "nothing here that could be the wrong product"}


# ---------------------------------------------------------------------------
# Drawn FROM the brand's own pictures. Owner, 2026-09-06, on a set of frames:
# *"just some generic photo of someone drinking out of a nameless white mug…
# We have photos of this product for examples and existing product assets to
# reference for vibe and quality. So why are we doing this so poorly?"*
#
# Because the model had never seen them. Every generation went out as a JSON
# body — prompt, size, n — and the only thing it was ever told about the
# product was "do not invent one". This is the route where it is HANDED the
# product and the look, as image inputs, and the prompt says which is which
# because the API does not.
# ---------------------------------------------------------------------------

def _this_exact_product(k: int) -> str:
    """THE OTHER HALF OF `_NO_INVENTED_PRODUCT`. "Invent nothing" was the
    right rule when the model had never seen this product; given its
    photographs, the rule is the opposite — draw exactly this, and nothing
    like it."""
    return (f"THE PRODUCT IN THIS FRAME IS THE ONE IN THE FIRST {k} REFERENCE "
            f"IMAGE{'S' if k != 1 else ''}, reproduced EXACTLY: its shape, "
            "proportions, colours, pattern, material and finish. Do not "
            "redesign, simplify, recolour or restyle it, and do not substitute "
            "a generic item of the same type. Show it once, and make it the "
            "thing the eye lands on.")


_THE_LOOK = (
    "The remaining reference images are THE LOOK, not the contents: match "
    "their styling, lighting, palette, surfaces, props, camera height and "
    "framing. Nothing from inside them — no object, person, room or text — is "
    "copied into this frame; they say how it should feel, not what is in it.")

#: How hard the model is asked to match its inputs. `high` is what makes a
#: reference a reference rather than a mood — at `low`, the API's default, a
#: hand-painted cup comes back as "a cup". Only the full gpt-image models take
#: the parameter; the mini refuses the whole request, so it is left off there
#: rather than sent and refused.
INPUT_FIDELITY = "high"
#: Longest side of an input. The API takes far larger; a Shopify master is
#: 4000px and five of them is a slow upload on a call that already takes a
#: minute, and nothing above this size reaches the model anyway.
INPUT_MAX_SIDE = 1536


def _fidelity_for(model: str) -> str:
    return "" if "mini" in (model or "") else INPUT_FIDELITY


def _trim_margins(im, pad: float = 0.04):
    """The picture cropped to its subject: the alpha's bounding box for a
    cutout, the non-white box for a shot on white. A catalogue cutout is
    mostly margin, and the margin was what the model spent its attention
    matching. Left alone when nothing can be found or the box is the whole
    picture."""
    from PIL import ImageChops
    box = None
    try:
        if im.mode in ("RGBA", "LA", "P"):
            a = im.convert("RGBA").getchannel("A").point(lambda v: 255 if v > 16 else 0)
            box = a.getbbox()
        else:
            rgb = im.convert("RGB")
            from PIL import Image as _I
            diff = ImageChops.difference(rgb, _I.new("RGB", rgb.size, (255, 255, 255)))
            box = diff.convert("L").point(lambda v: 255 if v > 24 else 0).getbbox()
    except Exception:                                            # noqa: BLE001
        return im
    if not box:
        return im
    w, h = im.size
    bw, bh = box[2] - box[0], box[3] - box[1]
    if bw * bh < 0.01 * w * h or (bw >= 0.96 * w and bh >= 0.96 * h):
        return im
    px, py = int(bw * pad) + 1, int(bh * pad) + 1
    return im.crop((max(0, box[0] - px), max(0, box[1] - py),
                    min(w, box[2] + px), min(h, box[3] + py)))


def input_image(blob: bytes, max_side: int = INPUT_MAX_SIDE,
                trim: bool = False) -> tuple[bytes, str]:
    """One input at a size the API takes quickly: `(bytes, mime)`, or
    `(b"", "")` if the bytes are not an image — a caller drops that one and
    SAYS so, rather than sending it. A cutout keeps its alpha (PNG); a
    photograph goes as JPEG, which halves the upload. `trim` crops to the
    subject first — for a product input, never for a look pin."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(blob))
        im.load()
    except Exception:                                            # noqa: BLE001
        return b"", ""
    if trim:
        im = _trim_margins(im)
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    if im.mode in ("RGBA", "LA", "P"):
        im.convert("RGBA").save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    im.convert("RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"


def _mime(blob: bytes) -> str:
    return "image/png" if blob[:4] == b"\x89PNG" else "image/jpeg"


def with_references(prompt: str, *, product: list[bytes], look: list[bytes],
                    shape: str = "square", n: int = 1,
                    with_people: bool = False, model: str = "",
                    checklist: list | None = None) -> dict:
    """A frame generated FROM the brand's own pictures.

    `product` is the thing itself, photographed; `look` is the board. Both go
    into the request as image inputs — the one route where the model sees
    pixels — under one field name, because the API takes a list.

    RIGHTS ARE NOT CHECKED HERE, and cannot be: this function takes bytes.
    Every byte string reaching it came through `creative.board_inputs`,
    which fetches nothing `kb.may_publish` refuses — the gate that keeps a
    reference photograph out of a composite. A reference pin therefore never
    arrives here, and the guard on that gate is what says so.
    """
    if shape not in SIZES:
        return {"ok": False, "error": f"unknown shape {shape!r}"}
    product = [b for b in (product or []) if b]
    look = [b for b in (look or []) if b]
    if not product and not look:
        return {"ok": False, "error": "No reference images supplied."}
    rules = []
    if product:
        rules.append(_this_exact_product(len(product)))
        # WHAT TO PRESERVE, IN WORDS. "Reproduce exactly" names nothing; the
        # checklist a careful observer would use does — and it is the same
        # list the judge holds afterwards (`creative.compare_product`).
        if checklist:
            rules.append("WHAT A CAREFUL OBSERVER CHECKS ON THIS PRODUCT — keep "
                         "every one exactly as the reference images show it:\n"
                         + "\n".join(f"- {c}" for c in checklist))
        if look:
            rules.append(_THE_LOOK)
    else:
        # A look with no product: the setting is drawn from the board and
        # the product rule is the old one, because the model still has not
        # seen the product and must not make one up.
        rules += [_NO_INVENTED_PRODUCT,
                  _THE_LOOK.replace("The remaining reference images",
                                    "The reference images")]
    if with_people:
        rules.append(_PEOPLE_ARE_THE_SUBJECT)
    files = ([("image[]", (f"product-{i + 1}", b, _mime(b)))
              for i, b in enumerate(product)]
             + [("image[]", (f"look-{i + 1}", b, _mime(b)))
                for i, b in enumerate(look)])
    model = model or MODEL
    data = {"model": model, "size": SIZES[shape],
            "n": str(max(1, min(4, n))),
            "prompt": "\n\n".join([prompt] + rules).strip()}
    fid = _fidelity_for(model)
    if fid:
        data["input_fidelity"] = fid
    res = post("/images/edits", files=files, data=data)
    if not res["ok"]:
        return res
    return {"ok": True, "images": res["images"], "shape": shape,
            "inputs": {"product": len(product), "look": len(look)},
            "note": "drawn from the brand's own pictures — the product from "
                    "its photographs, the setting from the board"}


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
