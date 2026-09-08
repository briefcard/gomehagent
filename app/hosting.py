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


def _copy_for(tenant: str, row) -> dict:
    """The words this frame was made for — `{headline, ask, output_id}` off the
    ad variant that asked for it (`batch` tags every frame `output:<id>`), or
    empty when the frame is not an ad's.

    THE AD'S OWN WORDS, read from the batch record, because that is the one
    copy `ad_variant_save` edits; a headline stored beside the frame would
    ship the pre-edit words. `ad_export` reads the same record.
    """
    import json as _json
    oid = next((str(t)[len("output:"):] for t in list(row.tags or [])
                if str(t).startswith("output:")), "")
    out = {"headline": "", "ask": "", "output_id": oid}
    if not oid:
        return out
    from . import layers
    with db.SessionLocal() as s:
        arts = (s.query(db.ArtifactBody)
                .filter(db.ArtifactBody.tenant == tenant,
                        db.ArtifactBody.format == "ad_batch")
                .order_by(db.ArtifactBody.id.desc()).all())
        for art in arts:
            try:
                batch = _json.loads(art.body or "") or {}
            except Exception:                                    # noqa: BLE001
                continue
            for v in (batch.get("variants") or []):
                if str(v.get("output_id") or "") != oid:
                    continue
                text = str(v.get("text") or "")
                out["headline"] = (str(v.get("headline") or "").strip()
                                   or layers.first_line(text))
                out["ask"] = layers.ask_line(text)
                return out
    return out


def _theme(tenant: str) -> dict:
    """The brand's theme with every field filled — the SAME record the
    emails and the site read their colours and faces from, so a layer set in
    Canva and a button in a campaign agree."""
    from . import email_render
    b = kb.brand(tenant)
    return email_render._theme(dict(getattr(b, "theme", None) or {}))


def _logo(theme: dict) -> bytes:
    """The brand mark's bytes, or nothing. A seam: the suite hands one in."""
    url = str((theme or {}).get("logo_url") or "")
    if not url:
        return b""
    try:
        import httpx
        r = httpx.get(url, timeout=30, follow_redirects=True)
        return r.content if r.status_code < 400 else b""
    except Exception:                                            # noqa: BLE001
        return b""


def _fallback_headline(tenant: str, row) -> str:
    """When a frame carries no copy: the thing it shows, by name, so the
    headline layer exists and reads as a real one to be retitled."""
    key = str(getattr(row, "entity_key", "") or "")
    if key:
        for e in kb.entities(tenant, available_only=False):
            if str(getattr(e, "key", "")) == key and getattr(e, "name", ""):
                return str(e.name)[:60]
    return "Headline"


FLAT_TAG = "canva-flat:"


def is_flat(row, fmt: str) -> bool:
    """Whether this placement's design in Canva is the flat fallback."""
    return f"{FLAT_TAG}{fmt}" in [str(t) for t in (getattr(row, "tags", None) or [])]


def mark_flat(asset_id: str, fmt: str, on: bool) -> None:
    """Record on the frame that a placement went to Canva flat (or that the
    layers replaced it). A tag, like the boards: the fact rides the row."""
    with db.SessionLocal() as s:
        got = s.get(db.KbAsset, asset_id)
        if got is None:
            return
        tags = [str(t) for t in (got.tags or []) if str(t) != f"{FLAT_TAG}{fmt}"]
        if on:
            tags.append(f"{FLAT_TAG}{fmt}")
        got.tags = tags
        s.commit()


def to_canva(tenant: str, asset_id: str, fmt: str = "1:1") -> dict:
    """Hand a frame to Canva AS LAYERS, for one placement.

    Owner, 2026-09-07: *"the text and components are not separate layers on
    Canva they are burned on — is there a way to layer them so we can adjust
    as needed?"* There is, through the connection that already works: the
    Connect API imports a PowerPoint file as a design, and each object in it
    arrives as its own editable element (`layers` says where that is
    documented). So the frame goes as a one-slide deck — the photograph,
    the brand mark, the headline and the CTA pill, each a layer — rather
    than as one flattened picture the type was painted into.

    ONE DESIGN PER PLACEMENT (`fmt`), because a layout is a fact about a
    ratio: the 9:16 keeps Meta's safe zones, the others use the frame. The
    1:1 stays on `canva_design_id`, where `stage`, `harvest` and the console
    have always read it; the rest are on `canva_designs`.

    ON DEMAND, not for every frame at generation — a set is up to thirty
    variations and two get kept — and reused: a frame already in Canva for
    that placement opens the design it has rather than making a second.
    """
    from . import canva, compose, layers
    row = _row(tenant, asset_id)
    if row is None:
        return {"ok": False, "error": "no such picture"}
    if fmt not in compose.SIZES:
        return {"ok": False, "error": f"unknown placement {fmt!r} — one of "
                                      f"{', '.join(compose.SIZES)}"}
    have = dict(row.canva_designs or {})
    if row.canva_design_id and not have.get("1:1"):
        have["1:1"] = row.canva_design_id
    # A FLAT FALLBACK IS NOT A DESIGN TO REUSE. When the layered import
    # failed and the frame went as one picture, a second press tries the
    # layers again rather than opening the flat one for ever.
    if have.get(fmt) and not is_flat(row, fmt):
        did = str(have[fmt])
        return {"ok": True, "design_id": did, "reused": True, "fmt": fmt,
                "edit_url": f"https://www.canva.com/design/{did}/edit",
                "note": "it is already open in Canva"}
    blob, why = _bytes(row)
    if why:
        return {"ok": False, "error": why}

    copy = _copy_for(tenant, row)
    theme = _theme(tenant)
    made = layers.deck(
        blob, size=compose.SIZES[fmt],
        headline=copy["headline"] or _fallback_headline(tenant, row),
        ask=copy["ask"], theme=theme, logo=_logo(theme),
        safe=(compose.META_PLACEMENTS.get(fmt) or {}).get("safe"),
        title=f"{row.title or 'Ad frame'} · {fmt}")
    if not made.get("ok"):
        return {"ok": False, "error": str(made.get("error") or "the layers could not be built")}
    # Canva caps a design title at 50 characters, unencoded (IMPORTS_DOC).
    title = f"{(row.title or 'Ad frame')[:canva.UPLOAD_NAME_MAX - len(fmt) - 3]} · {fmt}"
    sent = canva.import_design(tenant, made["pptx"], title=title)
    flat_said = ""
    if not sent.get("ok"):
        # THE DOOR STAYS OPEN. Canva's importer answered 500 on every deck
        # for a day (owner, 2026-09-08) and the button was dead with it. A
        # failed import falls back to the route that has always worked —
        # the picture as one flat image in a custom design — SAID as such
        # on the frame and in the note, so nobody mistakes it for layers,
        # and the next press tries the layers again.
        why = str(sent.get("error") or "the import failed")[:160]
        if have.get(fmt) and is_flat(row, fmt):
            did = str(have[fmt])
            return {"ok": True, "design_id": did, "reused": True, "fmt": fmt, "flat": True,
                    "edit_url": f"https://www.canva.com/design/{did}/edit",
                    "note": f"the layers could not be imported again ({why}); the flat "
                            f"picture already in Canva is opened instead"}
        flat = canva.editable_from_image(tenant, blob, title=title, entity_key=row.entity_key or "",
                                         record=False)
        if not flat.get("ok"):
            return {"ok": False, "error": f"the layers could not be imported ({why}), and the "
                                          f"flat picture could not be opened either: "
                                          f"{str(flat.get('error') or '')[:120]}"}
        kb.set_asset_design(row.id, fmt, str(flat.get("design_id") or ""))
        mark_flat(row.id, fmt, True)
        acct = canva.which_account(tenant)
        return {"ok": True, "design_id": str(flat.get("design_id") or ""), "reused": False,
                "fmt": fmt, "flat": True, "edit_url": flat.get("edit_url", ""),
                "account": acct.get("source", ""), "layers": [], "skipped": {},
                "note": (f"the layers could not be imported — Canva answered: {why}. The "
                         f"picture is open in Canva as ONE flat image instead; press "
                         f"'layer in Canva' again later to try the layers."
                         + (f" It went to the agency's Canva — {acct['note']}"
                            if acct.get("note") else ""))}
    design_id = str(sent.get("design_id") or "")
    kb.set_asset_design(row.id, fmt, design_id)
    mark_flat(row.id, fmt, False)
    # WHOSE CANVA IT WENT INTO, when that is not the obvious answer. A frame
    # that opened in the agency's Canva because the client's own connection
    # was revoked is a fact the person editing it needs, and the design's
    # folder is the only place it would otherwise show.
    acct = canva.which_account(tenant)
    skipped = dict(made.get("skipped") or {})
    note = (f"{', '.join(made['layers'])} are separate layers in Canva"
            + (f" (no {'/'.join(skipped)}: " + "; ".join(skipped.values()) + ")"
               if skipped else "")
            + ". Nothing is published."
            + (f" It went to the agency's Canva, in this account's folder — "
               f"{acct['note']}" if acct.get("note") else ""))
    return {"ok": True, "design_id": design_id, "reused": False, "fmt": fmt,
            "edit_url": sent.get("edit_url", ""), "account": acct.get("source", ""),
            "layers": list(made["layers"]), "skipped": skipped,
            "colour": made.get("colour", ""), "note": note}


def layer_placements(tenant: str, asset_id: str) -> dict:
    """Every Meta placement of one kept frame, as its own layered design in
    Canva. Owner, 2026-09-07: *"how do we ensure that final approved assets
    get created in the different ratios needed for the meta placements?"* —
    by making each ratio on approval, with the layers reflowed to it, so what
    the designer adjusts is the ratio that runs. `{ok, designs, errors}`."""
    from . import compose
    out: dict = {"ok": False, "designs": {}, "errors": {}}
    for fmt in compose.META_PLACEMENTS:
        got = to_canva(tenant, asset_id, fmt)
        if got.get("ok"):
            out["designs"][fmt] = got["design_id"]
        else:
            out["errors"][fmt] = str(got.get("error") or "")[:160]
    out["ok"] = bool(out["designs"])
    out["note"] = (f"{len(out['designs'])} of {len(compose.META_PLACEMENTS)} placements "
                   f"are layered designs in Canva"
                   + (f"; not made: " + "; ".join(f"{k}: {v}" for k, v in out["errors"].items())
                      if out["errors"] else ""))
    return out


def layer_kept(tenant: str, asset_ids: list) -> dict:
    """The approval's other half, off the request: each kept frame's three
    placements as layered designs. One line per frame, so a failure to make
    them is a sentence in the run strip rather than a silence."""
    out = {"made": 0, "frames": 0, "reasons": []}
    for aid in list(asset_ids or []):
        got = layer_placements(tenant, str(aid))
        out["frames"] += 1
        out["made"] += len(got.get("designs") or {})
        for why in (got.get("errors") or {}).values():
            if why and why not in out["reasons"]:
                out["reasons"].append(why)
    out["note"] = (f"{out['made']} layered design(s) in Canva for {out['frames']} kept frame(s)"
                   + (f" — {'; '.join(out['reasons'][:3])}" if out["reasons"] else ""))
    return out


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
