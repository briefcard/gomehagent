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


#: How long an unreviewed picture keeps its bytes. Long enough that a queue
#: looked at weekly never loses anything somebody meant to keep; short enough
#: that a generator left running does not fill a database with images nobody
#: ever opened.
UNREVIEWED_DAYS = 14

#: And how long bytes nothing points at survive. Only reachable if an asset row
#: was deleted outright, which nothing does today — kept as a floor rather than
#: a promise that it cannot happen.
ORPHAN_DAYS = 30


def sweep(*, unreviewed_days: int = UNREVIEWED_DAYS,
          orphan_days: int = ORPHAN_DAYS) -> dict:
    """Keep the bytes behind APPROVED pictures. Nothing else earns storage.

    Owner, 2026-08-29: *"lets make sure we are only storing long term the
    images that have been approved. no need to store / reference unapproved
    assets."*

    Four cases, and the difference between them is who decided and when:

      APPROVED    kept while we are the only copy — and COUNTED SEPARATELY
                  from the moment the client's own site holds it. Owner,
                  2026-08-30: an approved picture belongs on the client's CMS,
                  and once `hosting.publish` has moved it there this store has
                  no business keeping a second copy. So "kept because somebody
                  said yes" and "kept because nowhere else would take it" stop
                  looking alike: the second is a connection that needs fixing,
                  and it read as normal for as long as they shared a number.
      REJECTED    dropped now. The decision is made, and a rejected image must
                  not be loadable — the ROW stays, because `review_asset`
                  retires rather than deletes so a second crawl does not
                  re-propose what was already turned down, and the row is that
                  memory. It just no longer has megabytes attached.
      PROPOSED    kept while the decision is still open, dropped after
                  `unreviewed_days`, and the ASSET IS RETIRED WITH IT. Dropping
                  bytes under a live row is the worse failure: a queue full of
                  pictures that 404 when opened teaches people the queue is
                  broken. Retired with `review` left at `proposed`, so a timer's
                  decision stays distinguishable from a person's.
      ORPHAN      no asset points at it at all; dropped after `orphan_days`.

    Reports each count separately, because "12 dropped" answers nothing: an
    account whose proposals are expiring unreviewed has a different problem
    from one clearing rejections.
    """
    import datetime as dt

    from . import provenance as prov
    now = db.utcnow()
    stale = now - dt.timedelta(days=max(1, int(unreviewed_days or 1)))
    orphan_cut = now - dt.timedelta(days=max(1, int(orphan_days or 1)))

    out = {"kept_approved": 0, "dropped_rejected": 0, "expired_unreviewed": 0,
           "dropped_orphan": 0, "unhosted": 0}
    with db.SessionLocal() as s:
        by_url = {}
        for a in s.query(db.KbAsset).all():
            if a.url:
                by_url.setdefault(a.url, a)

        for row in s.query(db.MediaBlob).all():
            # `as_utc` because SQLite hands back naive datetimes and Postgres
            # does not — comparing the two raises, and it would raise in the
            # nightly job rather than in a test.
            made = db.as_utc(row.created_at) if row.created_at else None
            asset = by_url.get(url_for(row.id, row.mime or "image/png"))
            if asset is None:
                if made and made < orphan_cut:
                    s.delete(row)
                    out["dropped_orphan"] += 1
                continue
            review = str(asset.review or "")
            if review == prov.APPROVED:
                out["kept_approved"] += 1
                if not (asset.hosted or {}).get("url"):
                    out["unhosted"] += 1
                continue
            if review == prov.REJECTED:
                s.delete(row)
                out["dropped_rejected"] += 1
                continue
            # Proposed, or anything that never got a review state.
            if made and made < stale:
                s.delete(row)
                asset.status = "retired"
                out["expired_unreviewed"] += 1
        s.commit()
    notes = []
    if out["expired_unreviewed"]:
        notes.append(f"{out['expired_unreviewed']} picture(s) expired "
                     f"unreviewed — nobody opened them in {unreviewed_days} "
                     f"days, and they can be generated again")
    if out["unhosted"]:
        notes.append(f"{out['unhosted']} approved picture(s) are still ours "
                     f"because no client site would take them — connect a CMS, "
                     f"or re-connect a Shopify store to grant write_files")
    out["note"] = " · ".join(notes)
    return out
