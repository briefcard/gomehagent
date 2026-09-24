"""THE BRAND'S PICTURES — read, filed, fetched and cut for the model to look at.

What survived of the token email chain when it was deleted (2026-09-14):
the readings kept on each picture (its tones by arithmetic, its kind by one
look, the owner's hand outranking both), the bounded fetch that never pulls
a client's master file whole, and the strips and contact sheets a vision
model reads at its tier. Nothing here decides how an email looks.
"""
from __future__ import annotations

import base64 as _b64
import io
import json as _json
import re

import httpx
from PIL import Image

from . import db

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


IMAGERY = ("packshot-on-plain", "packshot-on-colour", "lifestyle", "flat-lay",
           "portrait", "texture")


PICTURE_KINDS = IMAGERY + ("mark",)


STRIP_OVERLAP = 120


MAX_IMAGE_BLOCKS = 20


FETCH_MAX = 6 * 1024 * 1024


SHOT_MAX = 24 * 1024 * 1024


_KIND_READ = """You are looking at one picture from a brand's own library. Answer as JSON only:
{"kind": one of %s — "packshot-on-plain" is a product alone on a plain ground; "packshot-on-colour"
 a product alone on a coloured ground; "lifestyle" a product among other things or in a setting;
 "flat-lay" things arranged from above; "portrait" a person is the subject; "texture" a surface or
 material with no product; "mark" a logo or wordmark, not a photograph,
 "alone": true when one product is the whole subject, else false,
 "person": true when a person is in the picture}
Nothing outside the JSON — never a brand name, never words from the picture."""


def _json_of(text: str) -> dict:
    import json as _json
    m = re.search(r"\{.*\}", str(text or ""), re.S)
    if not m:
        return {}
    try:
        got = _json.loads(m.group(0))
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def _aspect_of(w: int, h: int) -> str:
    if not w or not h:
        return ""
    r = w / h
    return "square" if 0.9 <= r <= 1.1 else "portrait" if r < 0.9 else "wide" if r >= 1.9 else "landscape"


def _kind_filed(asset) -> str:
    """The kind the filing already says, when it says one: the sync's
    packshot tag, a surface, a logo. '' when only a look could tell."""
    tags = [str(t) for t in (getattr(asset, "tags", None) or [])]
    subj = str(getattr(asset, "subject", "") or "")
    if subj == "logo":
        return "mark"
    if "packshot" in tags:
        return "packshot-on-plain"
    if subj == "surface":
        return "texture"
    return ""


def _fetch(url: str) -> bytes:
    """A swipe's screenshot, whole: one file, on the owner's press, capped."""
    import httpx
    try:
        r = httpx.get(url, headers={"User-Agent": _UA}, timeout=25, follow_redirects=True)
        if r.status_code != 200 or len(r.content) > SHOT_MAX:
            return b""
        return r.content
    except Exception:                                            # noqa: BLE001
        return b""


def _fetch_bounded(url: str, *, cap: int = FETCH_MAX) -> bytes:
    """The bytes at `url`, streamed and STOPPED at `cap` — a picture too big
    to read cheaply comes back empty rather than into memory whole. The
    Render instance was restarted twice on 2026-09-12 by a preview that
    pulled every store image at full size in one request."""
    import httpx
    try:
        with httpx.stream("GET", url, headers={"User-Agent": _UA}, timeout=25,
                          follow_redirects=True) as r:
            if r.status_code != 200:
                return b""
            declared = int(r.headers.get("content-length") or 0)
            if declared > cap:
                return b""
            chunks, n = [], 0
            for chunk in r.iter_bytes():
                n += len(chunk)
                if n > cap:
                    return b""
                chunks.append(chunk)
            return b"".join(chunks)
    except Exception:                                            # noqa: BLE001
        return b""


def _small_url(url: str) -> str:
    """A Shopify CDN picture asked for at 600 px — the size a colour read
    needs and a fraction of the master's bytes."""
    u = str(url or "")
    if "cdn.shopify.com" not in u and "/cdn/shop/" not in u:
        return u
    base, sep, query = u.partition("?")
    stem, dot, ext = base.rpartition(".")
    if not dot or len(ext) > 5 or "/" in ext or re.search(r"_\d+x\d*$", stem):
        return u
    return f"{stem}_600x{dot}{ext}{sep}{query}"


def _tier_edge() -> tuple[str, int]:
    from . import config, llm
    tier, _why = llm.image_tier(config.CREATIVE_REVIEW_MODEL)
    return tier, llm.IMAGE_TIERS[tier]["max_edge"]


def _max_pixels() -> int:
    """The model's picture budget in pixels: tokens × 750 at this tier. The
    API refused a 1280×1568 strip on the owner's run (2026-09-17) — inside
    the edge, over the budget — and the judge never looked."""
    from . import llm
    tier, _ = _tier_edge()
    return int(llm.IMAGE_TIERS[tier]["max_tokens"]) * 750


def strips(blob: bytes, max_edge: int, overlap: int = STRIP_OVERLAP) -> list[dict]:
    """The screenshot as strips that fit `max_edge` AND the pixel budget, each
    `{png, top, bottom, width, height}`, overlapping by `overlap` px so a
    section cut by a strip edge is seen whole in one of them. A picture
    that already fits is one strip. Lossless PNG: this is the one place
    the type has to stay legible."""
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(blob)).convert("RGB")
    W, H = im.size
    if W > max_edge:
        im = im.resize((max_edge, max(1, round(H * max_edge / W))), Image.LANCZOS)
        W, H = im.size
    strip_h = max(200, min(max_edge, _max_pixels() // max(1, W)))
    out = []
    top = 0
    while True:
        bottom = min(H, top + strip_h)
        crop = im.crop((0, top, W, bottom))
        buf = io.BytesIO()
        crop.save(buf, format="PNG", optimize=True)
        out.append({"png": buf.getvalue(), "top": top, "bottom": bottom,
                    "width": W, "height": bottom - top})
        if bottom >= H:
            break
        top = bottom - overlap
    return out


def contact_sheet(blob: bytes, max_edge: int) -> bytes:
    """The whole email at the size the reviewer's tier can hold — the view
    for the overall key, the frame and the rhythm, never for the type."""
    import io
    from PIL import Image
    from . import llm
    im = Image.open(io.BytesIO(blob)).convert("RGB")
    tier, _ = _tier_edge()
    w, h = llm.resized_size(*im.size, max_edge, llm.IMAGE_TIERS[tier]["max_tokens"])
    if (w, h) != im.size:
        im = im.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _image_block(png: bytes) -> dict:
    import base64
    from . import llm
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/png",
                       "data": base64.standard_b64encode(png).decode()},
            # A strip that would be downscaled is REFUSED, not shrunk.
            "transformations": dict(llm.OVERSIZED_IMAGE_ERROR)}


def fetch(url: str) -> bytes:
    """A picture's bytes, small when the host can serve it small, capped
    either way. THE way anything fetches an image for the model.

    Store image URLs arrive HTML-escaped from the page they were read off
    (`?v=…&amp;width=3840`), so the literal `&amp;` reached Shopify, the
    parameter was ignored, and the full-size original came back."""
    import html as _html
    u = _html.unescape(str(url or "")).strip()
    if not u:
        return b""
    small = _small_url(u)
    return _fetch_bounded(small) or (_fetch_bounded(u) if small != u else b"")


def for_model(blob: bytes) -> dict | None:
    """ANY picture as the model takes it — decoded whatever its format,
    fitted to the reviewer's edge and pixel budget, sent as the PNG it now
    is. THE way a picture reaches the model.

    `creative` built its own blocks: whole originals, declared `image/png`
    whatever the bytes were. The API refuses a block whose bytes do not
    match its type, or that is over five megabytes — four such 400s in one
    campaign run on 2026-09-23."""
    if not blob:
        return None
    try:
        _tier, edge = _tier_edge()
        return _image_block(contact_sheet(blob, edge))
    except Exception:                                            # noqa: BLE001
        return None                                  # not a picture


def read_picture(asset, *, vision: bool = True, fetch: bool = True) -> dict:
    """The picture's reading — from the row when it has one, else read now
    and STORED ON THE ROW. Colours, size and aspect by arithmetic; the kind
    by the filing when it says (a packshot tag, a surface, a logo), else by
    one vision call (`creative_review`), ever, with `how.kind` saying which.
    The owner's hand (`set_picture_kind`) outranks both and is never
    re-read. `{}` when the bytes cannot be fetched or are not a picture."""
    import base64 as _b64
    import io
    import json as _json
    from . import db, imagegen, llm, palette as _pal
    aid = getattr(asset, "id", "")
    have = dict(getattr(asset, "reading", None) or {})
    if have.get("colours") and have.get("kind"):
        return have
    if not fetch:
        # NEVER FROM A PAGE OR A RUN. A reading is made by the Brand tab's
        # control, a few pictures at a time; a preview or a campaign reads
        # only what is already on the row, and says what is unread.
        return have
    url = getattr(asset, "url", "") or ""
    blob = _fetch_bounded(_small_url(url)) or (_fetch_bounded(url) if _small_url(url) != url else b"")
    if not blob:
        return have
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(blob))
        w, h = im.size
        im.draft("RGB", (256, 256))      # decode small: a JPEG master is not read whole
        im = im.convert("RGB")
        im.thumbnail((256, 256))
        small = io.BytesIO(); im.save(small, format="PNG")
        blob_small = small.getvalue()
    except Exception:                                            # noqa: BLE001
        return have
    colours = have.get("colours") or _pal.signature(blob_small)
    if not colours:
        return have
    blob = blob_small
    reading = {**have, "colours": colours, "size": [w, h], "aspect": _aspect_of(w, h),
               "how": dict(have.get("how") or {"colours": "arithmetic"})}
    if not reading.get("kind"):
        kind = _kind_filed(asset)
        if kind:
            reading["kind"], reading["how"]["kind"] = kind, "filed"
            reading["alone"] = kind.startswith("packshot")
        elif vision:
            small, mime = imagegen.input_image(blob)
            blocks = [{"type": "image", "source": {"type": "base64", "media_type": mime or imagegen._mime(blob),
                                                   "data": _b64.standard_b64encode(small or blob).decode()}},
                      {"type": "text", "text": _KIND_READ % ", ".join(f'"{k}"' for k in PICTURE_KINDS)}]
            reply = llm.ask("creative_review", blocks, tenant=getattr(asset, "tenant", "") or "", max_tokens=200)
            got = _json_of(getattr(reply, "text", "")) if getattr(reply, "ok", False) else {}
            k = str(got.get("kind") or "").strip().lower()
            if k in PICTURE_KINDS:
                reading["kind"], reading["how"]["kind"] = k, "vision"
                reading["alone"] = bool(got.get("alone"))
                reading["person"] = bool(got.get("person"))
            else:
                reading["how"]["kind"] = "unread — " + (str(getattr(reply, "error", "")) or "the picture reviewer did not answer with a kind")
        else:
            reading["how"]["kind"] = "unread — the look was not asked for"
    reading["read_at"] = db.utcnow().isoformat(timespec="seconds")
    if aid:
        try:
            with db.SessionLocal() as s:
                row = s.get(db.KbAsset, aid)
                if row is not None:
                    row.reading = reading
                    s.commit()
        except Exception:                                        # noqa: BLE001
            pass
    try:
        asset.reading = reading
    except Exception:                                            # noqa: BLE001
        pass
    return reading


def set_picture_kind(asset_id: str, kind: str, *, by: str = "owner") -> str:
    """The owner's word on what a picture is — kept on the row, outranks
    every reading, never re-read. Refuses a kind that is not one."""
    from . import db
    k = str(kind or "").strip().lower()
    if k not in PICTURE_KINDS:
        return f"{kind!r} is not a kind of picture ({', '.join(PICTURE_KINDS)})"
    with db.SessionLocal() as s:
        row = s.get(db.KbAsset, asset_id)
        if row is None:
            return "no such picture"
        r = dict(row.reading or {})
        r["kind"] = k
        r["how"] = {**(r.get("how") or {}), "kind": f"hand ({by})"}
        r["alone"] = k.startswith("packshot")
        row.reading = r
        s.commit()
    return f"{k}: set by hand"


def read_pictures(tenant: str, *, limit: int = 6, vision: bool = True) -> dict:
    """Read every publishable picture of this brand that has no reading
    yet, up to `limit` per press — the Brand tab's control. Says how many
    were read and how many are still unread."""
    from . import kb
    rows = [a for a in kb.assets(tenant) if (a.kind or "image") == "image"]   # publishable only: a pin is never read
    unread = [a for a in rows if not ((a.reading or {}).get("colours") and (a.reading or {}).get("kind"))]
    done = 0
    for a in unread[:limit]:
        if read_picture(a, vision=vision).get("kind"):
            done += 1
    left = max(0, len(unread) - done)
    return {"ok": True, "read": done, "left": left,
            "total": len(rows), "said": f"read {done} of {len(unread)} unread picture(s)"
                                         + (f"; {left} left — press again" if left else "")}


