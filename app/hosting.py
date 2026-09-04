"""Where a picture lives, and the two moves that change it.

Owner, 2026-08-30: *"It should be on canva until edited & approved or just
approved, then it can be hosted on shopify / wordpress / another cms of the
client's so it's accessible to us."*

That is a LIFECYCLE, and it had no owner. `media` said of itself that it is "a
handoff, not a CDN", and it was — except for approved pictures, which it kept
for ever. So the one case the disclaimer did not cover was the only one that
accumulates.

    ours        we hold the bytes. Cheap, and they expire unreviewed after a
                fortnight. Every generated frame starts here.
    editable    a Canva design exists for it, so the type and layout can be
                changed by somebody who can see it. Optional, and the reason
                it is optional is that twenty-four designs for a set of which
                two will be kept is twenty-two canvases nobody opens.
    hosted      the client's own CMS serves it and `url` points at their copy.
                Ours is dropped.

**THE STAGE IS DERIVED, NEVER STORED.** A column saying "hosted" beside a URL
that is still ours is a row that disagrees with itself, and the disagreement
would surface as a 404 a fortnight later when the sweep ran.

**APPROVAL IS THE GATE, AND IT IS THE CLIENT'S PLATFORM.** Publishing an
unapproved frame to a client's media library puts our draft in their store
where their staff can find it and use it. So `publish` refuses anything that
is not approved, in the same words `creative.placements` uses, because it is
the same rule.

**A REFUSAL KEEPS THE PICTURE.** An account with no CMS connected, a store
that never granted `write_files`, a WordPress that will not take the upload —
every one of those leaves the bytes with us and says so. The alternative is a
row pointing at a CMS that does not have it.
"""
from __future__ import annotations

from . import db, kb, media, provenance as prov

#: The three stages, in order. Named so a surface can render them without
#: re-deriving the vocabulary and disagreeing about it.
STAGES = ("ours", "editable", "hosted")

STAGE_WORDS = {
    "ours": "we are holding it",
    "editable": "editable in Canva",
    "hosted": "on the client's own site",
}


def stage(row) -> str:
    """Which stage this picture is at. Read off the row, in one place."""
    if (getattr(row, "hosted", None) or {}).get("url"):
        return "hosted"
    if getattr(row, "canva_design_id", "") or "":
        return "editable"
    return "ours"


def _row(tenant: str, asset_id: str):
    return next((a for a in kb.assets(tenant, publishable_only=False)
                 if a.id == asset_id), None)


def _bytes(row) -> tuple:
    """The picture's pixels, wherever they are. `(blob, why_not)`."""
    url = str(row.url or "")
    if "/media/" in url:
        blob, _mime = media.get(url.rsplit("/", 1)[-1])
        if blob:
            return blob, ""
        return b"", "the picture's bytes are gone"
    # Somebody else already hosts it — a crawled photograph, a Shopify product
    # shot. Fetched rather than refused, because "host this on the client's
    # site" is a reasonable thing to ask of a picture we did not generate.
    try:
        import httpx
        r = httpx.get(url, timeout=45, follow_redirects=True)
        r.raise_for_status()
        return r.content, ""
    except Exception as exc:                                     # noqa: BLE001
        return b"", f"could not fetch it: {exc.__class__.__name__}"


def to_canva(tenant: str, asset_id: str) -> dict:
    """Hand a frame to Canva so the type and layout can be changed.

    ON DEMAND, not for every frame at generation. A set is up to thirty
    variations and two of them get kept; making thirty Canva designs up front
    is twenty-eight canvases nobody opens, several minutes of upload polling,
    and a client folder that becomes unusable within a week. So the button is
    per frame, and the set-wide version is the same call in a loop.

    The design is recorded ON the frame, so the frame that comes back from
    Canva is the frame that went — `canva.harvest` files the export against
    the same design id, and without that join a finished design becomes a
    second, unrelated picture.
    """
    from . import canva
    row = _row(tenant, asset_id)
    if row is None:
        return {"ok": False, "error": "no such picture"}
    if row.canva_design_id:
        return {"ok": True, "design_id": row.canva_design_id, "reused": True,
                "edit_url": f"https://www.canva.com/design/{row.canva_design_id}/edit",
                "note": "it is already open in Canva"}
    blob, why = _bytes(row)
    if why:
        return {"ok": False, "error": why}
    made = canva.editable_from_image(
        tenant, blob, title=(row.title or "Ad frame")[:120],
        entity_key=row.entity_key or "",
        # The frame IS the record: the design id lands on it below. A second
        # row of kind="design" with the same thumbnail read as another
        # picture to review.
        record=False)
    if not made.get("ok"):
        return made
    design_id = str(made.get("design_id") or "")
    with db.SessionLocal() as s:
        got = s.get(db.KbAsset, asset_id)
        if got is not None:
            got.canva_design_id = design_id
            s.commit()
    return {"ok": True, "design_id": design_id, "reused": False,
            "edit_url": made.get("edit_url", ""),
            "note": "the picture is fixed; the text and layout are editable. "
                    "Nothing is published."}


def publish(tenant: str, asset_id: str) -> dict:
    """Move an APPROVED picture onto the client's own CMS, and let ours go.

    Owner: hosted on the client's platform "so it's accessible to us" — which
    is the point. Their URL outlives our blob store, their platform serves it,
    and every consumer we have takes a URL.

    THE PLACEMENTS TRAVEL WITH IT. A frame whose 1:1 is on the client's store
    and whose 9:16 is on ours is half-moved, and the half nobody looked at is
    the half that breaks.
    """
    from . import sites
    row = _row(tenant, asset_id)
    if row is None:
        return {"ok": False, "error": "no such picture"}
    if str(row.review or "") != prov.APPROVED:
        return {"ok": False, "error": (
            "only an approved picture goes to the client's site — this one is "
            f"{row.review or 'unreviewed'}, and putting a draft in their media "
            f"library is putting it where their staff will find and use it")}
    if (row.hosted or {}).get("url"):
        return {"ok": True, "url": row.url, "reused": True,
                "note": "already hosted by the client"}

    try:
        profile = sites.get(tenant)
        back = sites.backend(profile)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "keeps": True, "error": str(exc)[:300]}
    if not hasattr(back, "put_image"):
        return {"ok": False, "keeps": True, "error": (
            f"{profile.get('platform', 'that platform')} has a backend but no "
            f"way to store an image, so this stays with us")}

    blob, why = _bytes(row)
    if why:
        return {"ok": False, "error": why}
    alt = (row.subject or row.title or "")[:120]
    got = back.put_image(profile, blob, filename=_filename(row), alt=alt)
    if not got.get("ok"):
        return {**got, "keeps": True}

    # THE CROPS FIRST, then the row. If a placement upload fails the frame
    # stays ours and nothing has been rewritten — a half-moved frame is worse
    # than one that did not move.
    moved: dict = {}
    for fmt, purl in (row.placements or {}).items():
        pb, pwhy = media.get(str(purl).rsplit("/", 1)[-1])
        if not pb:
            continue
        one = back.put_image(profile, pb, filename=_filename(row, fmt), alt=alt)
        if not one.get("ok"):
            return {"ok": False, "keeps": True, "error": (
                f"the frame uploaded but its {fmt} crop did not "
                f"({one.get('error', '')[:120]}) — nothing was moved")}
        moved[fmt] = one["url"]

    where = {"platform": got.get("platform", ""), "id": got.get("id"),
             "url": got["url"], "at": db.utcnow().isoformat()}
    kb.set_asset_hosted(asset_id, where, url=got["url"])
    if moved:
        kb.set_asset_placements(asset_id, moved)

    # AND OURS GOES. This is the whole point: the blob store said it was a
    # handoff and approved pictures were the one case where it was not.
    dropped = _drop(tenant, [str(row.url or "")]
                    + [str(u) for u in (row.placements or {}).values()])
    return {"ok": True, "url": got["url"], "platform": where["platform"],
            "placements": moved, "dropped": dropped,
            "note": f"{1 + len(moved)} picture(s) now served by the client's "
                    f"{where['platform'] or 'site'}; {dropped} of ours dropped"}


def _filename(row, fmt: str = "") -> str:
    """A name a person can find again in a media library.

    Not the uuid. Somebody scrolling their own Files needs to know which ad
    this was, and `a3f9c1…png` tells them nothing.
    """
    import re
    stem = re.sub(r"[^a-z0-9]+", "-",
                  (row.title or row.subject or "ad-frame").lower()).strip("-")
    tail = "-" + fmt.replace(":", "x") if fmt else ""
    return f"{(stem or 'ad-frame')[:60]}{tail}.png"


def _drop(tenant: str, urls: list) -> int:
    """Let go of our copies. Only ours, and only these."""
    n = 0
    ids = [u.rsplit("/", 1)[-1].split(".", 1)[0] for u in urls if "/media/" in u]
    if not ids:
        return 0
    with db.SessionLocal() as s:
        for blob_id in ids:
            got = s.get(db.MediaBlob, blob_id)
            if got is not None and got.tenant == tenant:
                s.delete(got)
                n += 1
        s.commit()
    return n


def publish_all(tenant: str, *, limit: int = 40) -> dict:
    """Every approved picture we are still holding. The sweep's other half.

    Runs after a review, because approving is when pictures become eligible
    and a person who has just approved six should not have to press a second
    button six times.
    """
    out = {"hosted": 0, "kept": 0, "reasons": []}
    for row in kb.assets(tenant, publishable_only=True)[:max(1, limit)]:
        if (row.hosted or {}).get("url") or "/media/" not in str(row.url or ""):
            continue
        got = publish(tenant, row.id)
        if got.get("ok"):
            out["hosted"] += 1
            continue
        out["kept"] += 1
        why = str(got.get("error") or "")[:160]
        if why and why not in out["reasons"]:
            out["reasons"].append(why)
    out["note"] = (f"{out['hosted']} moved to the client's site"
                   + (f"; {out['kept']} stayed with us" if out["kept"] else ""))
    return out
