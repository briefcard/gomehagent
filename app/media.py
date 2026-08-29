"""Bytes get a URL. The one thing that stopped generation reaching a system.

`kb.add_asset(tenant, url, …)` takes a URL, because every asset until now came
from somewhere that already hosted it. `imagegen` returns BYTES. That gap is
the entire reason `/admin/creative` returns a PNG to a terminal and files
nothing, and why the email hero and the article image can only ever use
photographs somebody else already put on the internet.

**A HANDOFF, NOT A CDN.** Both consumers copy the image at publish time —
Shopify fetches `image.src` into its own files, `omnisend._rehost_images`
uploads by URL — so these bytes are served roughly once each and then the
client's own platform owns the copy people actually load. That is what makes
serving them ourselves reasonable rather than a promise to run a CDN.

**The URL is public and unguessable, and that is deliberate.** It has to be
fetchable by Shopify and by an ESP, neither of which will hold our admin key,
so it cannot sit behind one. What protects it is that the id is a uuid, the
route serves only what it was given, and the content is by definition
something about to be published anyway.

**Content-addressed.** The same generation asked for twice is one row. Without
that, one image filed under two ids is two assets in "which creative worked",
and the answer to that question is the point of filing them at all.
"""
from __future__ import annotations

import hashlib

from . import config, db

#: What may be stored and served. An allowlist rather than a sniff: this route
#: is public, and the set of things worth hosting here is small and known.
MIME = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

#: Refused above this. A generated frame is one to three megabytes; ten is not
#: a bigger picture, it is a mistake, and the database is not the place to
#: discover that.
MAX_BYTES = 10 * 1024 * 1024


def put(tenant: str, blob: bytes, *, mime: str = "image/png",
        origin: str = "generated") -> dict:
    """Store bytes and return `{ok, url, id, sha, reused}`.

    `reused` is not a detail: a caller that generated four candidates and kept
    one should be able to tell that it stored one image, and a sweep that
    re-ran should be able to tell it stored none.
    """
    if not blob:
        return {"ok": False, "error": "nothing to store"}
    if len(blob) > MAX_BYTES:
        return {"ok": False, "error": (
            f"{len(blob) // 1024}KB is over the {MAX_BYTES // 1024 // 1024}MB "
            f"limit — that is not a bigger picture, it is a mistake")}
    if mime not in MIME:
        return {"ok": False, "error": (
            f"{mime!r} is not stored here — {', '.join(sorted(MIME))}")}

    sha = hashlib.sha256(blob).hexdigest()
    with db.SessionLocal() as s:
        row = (s.query(db.MediaBlob)
               .filter(db.MediaBlob.tenant == tenant,
                       db.MediaBlob.sha == sha).first())
        reused = row is not None
        if row is None:
            row = db.MediaBlob(tenant=tenant, mime=mime, sha=sha,
                               bytes_=blob, origin=origin)
            s.add(row)
            s.commit()
        blob_id = row.id
    return {"ok": True, "id": blob_id, "sha": sha, "reused": reused,
            "url": url_for(blob_id, mime)}


def url_for(blob_id: str, mime: str = "image/png") -> str:
    """The absolute URL. ABSOLUTE because the fetchers are Shopify and an ESP,
    not a browser that already knows where it is."""
    ext = MIME.get(mime, "png")
    return f"{config.PUBLIC_BASE_URL.rstrip('/')}/media/{blob_id}.{ext}"


def get(blob_id: str) -> tuple[bytes, str]:
    """`(bytes, mime)` or `(b"", "")`. The id is taken from a URL path, so it
    is stripped of any extension the caller wrote onto it."""
    ident = str(blob_id or "").split(".", 1)[0].strip()
    if not ident:
        return b"", ""
    with db.SessionLocal() as s:
        row = s.get(db.MediaBlob, ident)
        if row is None:
            return b"", ""
        return bytes(row.bytes_ or b""), str(row.mime or "image/png")


def sweep(days: int = 120) -> dict:
    """Drop blobs nothing points at any more.

    The handoff makes this safe and eventually necessary: once Shopify or the
    ESP has copied an image, our bytes are a spare, and a table of spares grows
    for ever. Only rows NO asset still references are dropped, so an asset
    somebody has not published yet keeps its bytes however old they are.
    """
    import datetime as dt
    cutoff = db.utcnow() - dt.timedelta(days=max(1, int(days or 1)))
    with db.SessionLocal() as s:
        referenced = {u for (u,) in s.query(db.KbAsset.url).all() if u}
        old = (s.query(db.MediaBlob)
               .filter(db.MediaBlob.created_at < cutoff).all())
        dropped = 0
        for row in old:
            if url_for(row.id, row.mime or "image/png") in referenced:
                continue
            s.delete(row)
            dropped += 1
        if dropped:
            s.commit()
    return {"dropped": dropped, "kept_referenced": len(referenced)}
