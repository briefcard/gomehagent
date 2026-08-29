"""Bespoke, governed campaign visuals: the approved library first, a Canva
draft on a miss — never an unapproved pixel in a customer's inbox.

The owner's requirement (2026-08-21): campaign emails will often need a
bespoke marketing visual per email. The governed loop that delivers that
without breaking "launch is always human-approved":

1. **Select** — the hero image comes from the creative library via
   `kb.assets(publishable_only=True)`, which is the safe read: approved
   (review gate) AND `rights == owned` (a competitor's photograph saved for
   inspiration is structurally unreachable from here). Entity-scoped
   photographs beat brand-wide ones; logos are never heroes.

2. **Draft on miss** — when nothing usable exists and the caller opted in,
   a Canva design is CREATED (right-sized for an email hero, filed in the
   tenant's folder, recorded in the library as a `design`). A design is not
   pixels: it cannot be selected as a hero, so nothing generated here can
   leak into an email in the same run. The owner finishes it in Canva; the
   exported photograph enters the pictures review queue like any other
   candidate, and the NEXT campaign run selects it. Two steps, and the
   second one is the human.

3. **Absence survives** — no image is a labelled state, not a blank: the
   campaign email renders imageless (the renderer is built for it) and the
   run notes exactly why and what would change it.

Tenant-generic: nothing here names a client, sizes come from constants, and
the Canva transport (REST today, MCP as tool names are learned — see
ARCHITECTURE.md) is the adapter's business, not this module's.
"""
from __future__ import annotations

import re

from . import kb

#: Email-hero canvas, px. 1200×600 renders crisply at the renderer's 600px
#: width on 2× displays; 2:1 keeps the hero from swallowing the fold.
HERO_W, HERO_H = 1200, 600


def _usable(rows: list, entity_keys) -> list:
    """Publishable images, heroes only, in the caller's order of preference.

    `kb.assets` already enforced approved+owned; this layer only ORDERS and
    excludes logos — a brand mark as the hero reads as a letterhead, and the
    header already carries the logo from the theme.

    `entity_keys` is a SEQUENCE and its order is honoured: the caller passes
    the thing the artifact is actually about first, then whatever else it
    features. A set discarded that, so an email about the glasses could take a
    photograph scoped to a companion — technically "entity-scoped", and still
    the wrong picture. Ranking by position makes the caller's priority the
    picture's priority.
    """
    order = {k: i for i, k in enumerate(
        [k for k in (entity_keys or []) if k])}
    heroes = [r for r in rows if (r.subject or "") != kb.LOGO and (r.url or "")]
    scoped = sorted((r for r in heroes if (r.entity_key or "") in order),
                    key=lambda r: order[r.entity_key or ""])
    brandwide = [r for r in heroes if not (r.entity_key or "")]
    return scoped + brandwide


def hero_for_campaign(tenant: str, *, segment_key: str = "",
                      entity_keys: list[str] | None = None,
                      title: str = "", draft_if_missing: bool = False) -> dict:
    """The hero image for one campaign email, or the governed path to one.

    Returns one of:
      {ok, basis: "approved_asset", image: {url, alt}, asset_id}
      {ok, basis: "drafted_in_canva", image: None, drafted: {...}, note}
      {ok, basis: "none", image: None, why}   — absence, named
    """
    ordered = list(dict.fromkeys(k for k in (entity_keys or []) if k))
    ents = set(ordered)
    rows: list = []
    # The brand-wide shelf ("" ) is ALWAYS fetched alongside the scoped keys.
    # It used to be fetched only when no entity was named — so the moment a
    # campaign carried entities, an approved brand photograph became
    # structurally unreachable and the email went imageless past a perfectly
    # good hero. Ordering still prefers scoped over brand-wide (`_usable`).
    for ek in ents | {""}:
        rows += kb.assets(tenant, publishable_only=True, kind="image",
                          entity_key=ek or "")
    seen: set[str] = set()
    rows = [r for r in rows if not (r.id in seen or seen.add(r.id))]
    pick = next(iter(_usable(rows, ordered)), None)
    if pick is not None:
        # Belt to the braces `kb.assets` already provides: the use-gate names
        # its own refusal, and a row that fails it is skipped, not shipped.
        allowed, why = kb.may_publish(pick.id)
        if allowed:
            # WHAT THIS IS A PICTURE OF, carried out with the picture. The
            # caller placing a hero had no way to know whether it depicted the
            # product the email is about or a brand-wide shelf photograph, so
            # nothing could tell a fitting hero from a tablecloth on an email
            # about glasses (owner, 2026-08-22). `coherence.review` reads this
            # field; without it an image is unattributed and reported as such.
            return {"ok": True, "basis": "approved_asset",
                    "asset_id": pick.id,
                    "subject_key": (getattr(pick, "entity_key", "") or ""
                                    ) or "brand-wide",
                    "image": {"url": pick.url,
                              "alt": pick.title or segment_key or ""}}

    if not draft_if_missing:
        return {"ok": True, "basis": "none", "image": None,
                "why": ("no approved, owned photograph fits this campaign "
                        "(entity-scoped or brand-wide) — approve one in the "
                        "pictures queue, or pass draft_visual to have a "
                        "bespoke Canva draft created for review.")}

    from . import canva, credentials as cred
    if not (cred.resolve(tenant, "canva") or {}).get("secret"):
        return {"ok": True, "basis": "none", "image": None,
                "why": ("no approved photograph fits, and no Canva is "
                        "connected to draft one — connect Canva on the "
                        "Accounts tab, or approve a picture in the queue.")}
    made = canva.create_design(
        tenant, title=(title or f"Email hero — {segment_key or 'campaign'}")[:120],
        entity_key=next(iter(ents), ""), width=HERO_W, height=HERO_H)
    if not made.get("ok"):
        return {"ok": True, "basis": "none", "image": None,
                "why": f"Canva could not draft a hero: {made.get('error', '')[:200]}"}
    return {"ok": True, "basis": "drafted_in_canva", "image": None,
            "drafted": {"design_id": made.get("design_id", ""),
                        "edit_url": made.get("edit_url", "")},
            "note": ("a bespoke hero was drafted in Canva — finish it there, "
                     "export it, and the picture lands in the review queue; "
                     "the next run of this campaign will use it once "
                     "approved. Nothing unapproved ships meanwhile.")}


# ---------------------------------------------------------------------------
# Photographs the client already has, in Drive
# ---------------------------------------------------------------------------

#: Image types worth filing. Anything else in a Drive folder is a document.
_DRIVE_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")


#: What a generated image is filed as. `owned` because the client
#: commissioned it and the model's output is theirs to publish; `generated` as
#: the origin so it is never mistaken for a photograph somebody took.
GENERATED_RIGHTS = "owned"
GENERATED_ORIGIN = "generated"


def brief_for(tenant: str, *, entity_key: str = "", claim: str = "",
              situation: str = "", audience_key: str = "") -> dict:
    """The prompt, built from what this account knows.

    Owner's standing rule: every build starts by asking what the data layer
    contributes. For an image the answer is unusually direct — a typed prompt
    produces the interchangeable stock look the owner has been complaining
    about since the first email, and each of these is a fact nobody has to
    invent:

      the ENTITY      what is in frame, and its own description
      the CLAIM       what the picture must not contradict — a photograph
                      arguing something the copy cannot say is worse than no
                      photograph
      the SITUATION   the setting, in the account's own words
      the BRAND THEME the palette, so the frame belongs to this brand rather
                      than to whatever the model finds pretty this week
      the AUDIENCE    who is meant to see themselves in it

    Returns `{prompt, palette, entity, thin}`. `thin` names what was missing,
    because a brief built from three of five inputs is a weaker brief and the
    run is the only place that can say so.
    """
    from . import kb as kbmod
    parts, thin = [], []

    ent = None
    if entity_key:
        try:
            ent = next((e for e in kbmod.entities(tenant, available_only=False)
                        if getattr(e, "key", "") == entity_key), None)
        except Exception:                                        # noqa: BLE001
            ent = None
    if ent is not None:
        parts.append(f"The subject is {ent.name}"
                     + (f" — {str(ent.description or '')[:200]}"
                        if ent.description else "") + ".")
    elif entity_key:
        thin.append(f"no catalogue entry for {entity_key!r}, so the frame has "
                    f"nothing to be OF")

    if claim:
        parts.append(f"The picture must be consistent with this, which the "
                     f"copy beside it says: “{claim[:180]}”. Show nothing "
                     f"that would contradict it.")
    else:
        thin.append("no claim, so nothing constrains what the picture implies")

    if situation:
        parts.append(f"The moment is: {situation[:160]}.")

    palette = []
    try:
        b = kbmod.brand(tenant)
        theme = (getattr(b, "theme", None) or {}) if b else {}
        colours = theme.get("colors") or theme.get("colours") or {}
        palette = [v for v in colours.values()
                   if isinstance(v, str) and v.startswith("#")][:4]
    except Exception:                                            # noqa: BLE001
        palette = []
    if palette:
        parts.append("Use this brand palette: " + ", ".join(palette) + ".")
    else:
        thin.append("no brand theme colours on file, so the palette is the "
                    "model's taste rather than the brand's")

    if audience_key:
        try:
            a = next((x for x in kbmod.audiences(tenant)
                      if getattr(x, "key", "") == audience_key), None)
        except Exception:                                        # noqa: BLE001
            a = None
        if a is not None and (a.pains or []):
            parts.append(f"It is for {a.name}, who care about: "
                         + "; ".join(list(a.pains)[:3]) + ".")

    parts.append("Photographic, natural light, no text of any kind in the "
                 "image, no logos, nothing that reads as an advertisement.")
    return {"prompt": " ".join(parts), "palette": palette,
            "entity": getattr(ent, "key", ""), "thin": thin}


def generate(tenant: str, *, entity_key: str = "", claim: str = "",
             situation: str = "", audience_key: str = "",
             shape: str = "landscape", prompt: str = "") -> dict:
    """Make one image and FILE IT, so something can attach it.

    This is the seam. `imagegen` has had exactly one caller — the manual
    endpoint that returns a PNG and files nothing — so no generated image has
    ever become a `KbAsset` and nothing downstream could reach one. The
    attaching machinery already exists on both the email and the article side
    and needs no changes; it only ever needed an asset id to exist.

    IT PROPOSES. `review=proposed`, the same as a claim, and for the same
    reason written larger: a generated photograph of a product asserts more
    than a sentence about it does. We spent this week making sure a model
    cannot author its own evidence, and a picture is evidence.

    Uses the product's OWN pixels when the account has a photograph of it —
    `place_product` masks them, so what comes back is the real product in a
    generated setting rather than the model's idea of the product.
    """
    from . import imagegen, kb as kbmod, media

    brief = brief_for(tenant, entity_key=entity_key, claim=claim,
                      situation=situation, audience_key=audience_key)
    text = prompt.strip() or brief["prompt"]

    # The product's own photograph, when there is one to protect.
    source, source_id = b"", ""
    if entity_key:
        try:
            rows = [a for a in kbmod.assets(tenant, publishable_only=True)
                    if getattr(a, "entity_key", "") == entity_key
                    and (a.url or "")]
            if rows:
                import httpx
                got = httpx.get(rows[0].url, timeout=60, follow_redirects=True)
                if got.status_code < 400:
                    source, source_id = got.content, rows[0].id
        except Exception:                                        # noqa: BLE001
            source, source_id = b"", ""

    if source:
        res = imagegen.place_product(source, text, shape=shape, n=1)
        best = (res.get("candidates") or [{}])[0] if res.get("ok") else {}
        blob = best.get("image") or b""
        basis = "product masked — its pixels are the real ones"
    else:
        res = imagegen.plate(text, shape=shape, n=1)
        blob = (res.get("images") or [b""])[0] if res.get("ok") else b""
        basis = "generated scenery — no product in frame"
        if entity_key:
            brief["thin"].append(
                f"no usable photograph of {entity_key!r} on file, so the "
                f"frame is scenery and the product is not in it")

    if not res.get("ok") or not blob:
        return {"ok": False, "error": res.get("error", "generation failed"),
                "thin": brief["thin"]}

    put = media.put(tenant, blob, mime="image/png",
                    origin=GENERATED_ORIGIN)
    if not put["ok"]:
        return {"ok": False, "error": put["error"], "thin": brief["thin"]}

    said = kbmod.add_asset(
        tenant, put["url"], rights=GENERATED_RIGHTS,
        title=(f"Generated: {entity_key or situation or 'scene'}")[:120],
        kind="image", subject=entity_key or "", source="generated",
        prompt=text[:2000], entity_key=entity_key,
        derived_from=[source_id] if source_id else [],
        origin=GENERATED_ORIGIN)

    asset_id = ""
    try:
        rows = [a for a in kbmod.assets(tenant, publishable_only=False)
                if (a.url or "") == put["url"]]
        asset_id = rows[0].id if rows else ""
    except Exception:                                            # noqa: BLE001
        asset_id = ""

    return {"ok": True, "url": put["url"], "asset_id": asset_id,
            "reused": put["reused"], "basis": basis, "said": said,
            "prompt": text, "thin": brief["thin"],
            "review": "proposed — it cannot be used until somebody approves "
                      "it on Review · Pictures"}


def harvest_drive(tenant: str, *, folder: str = "", limit: int = 40) -> dict:
    """File the client's own Drive photographs into the pictures queue.

    A brand's real photography — the shoot, the lifestyle set, the founder
    portrait — sits in Drive, and the creative library only ever contained
    Shopify product shots. So an email could be imageless while a folder of
    perfectly good pictures sat one connection away (owner, 2026-08-22).

    **These land PROPOSED, not approved, and that is the point.** A Shopify
    product photo is published on the client's own storefront, which is why
    `store_sync` is auto-approved. A file in Drive has no such provenance: it
    may be a supplier's catalogue shot, a stock image, a competitor's picture
    saved for reference, or a photograph of a customer who never agreed to
    appear in an advertisement. The rights gate exists for exactly that, so
    these go to the queue for a human, and `hero_for_campaign` cannot select
    one until somebody says yes.
    """
    from . import data_tools, tenants
    t = tenants.get(tenant)
    alias = (getattr(t, "gmail_alias", "") or "").strip()
    if not alias:
        return {"ok": False, "error": f"{tenant} has no Google account wired"}
    try:
        from googleapiclient.discovery import build
        from . import gmail_client
        svc = build("drive", "v3", credentials=gmail_client.creds_for(alias),
                    cache_discovery=False)
        q = ["trashed=false",
             "(" + " or ".join(f"mimeType='{m}'" for m in _DRIVE_IMAGE_TYPES) + ")"]
        if folder:
            q.append(f"'{folder}' in parents")
        resp = svc.files().list(
            q=" and ".join(q), pageSize=min(int(limit or 40), 100),
            orderBy="modifiedTime desc",
            fields="files(id,name,mimeType,webViewLink,imageMediaMetadata/width,"
                   "imageMediaMetadata/height)").execute()
        files = resp.get("files") or []
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False,
                "error": f"Drive not readable for {alias} ({exc.__class__.__name__})"}

    # WHICH PRODUCT IS THIS A PICTURE OF? A filename usually says — "firenze
    # -set-table.jpg", "Portofino pitcher hero.png" — and an approver should
    # be shown that guess rather than made to type it. It is a RECOMMENDATION:
    # entity-scoped assets are preferred as heroes for that product, so a
    # wrong guess would put the wrong photograph on the wrong email. The
    # suggestion rides on the row for review; nothing acts on it unsupervised.
    prods = [(e.key, (e.name or "").lower()) for e in
             kb.entities(tenant, available_only=False) if (e.type or "") != "collection"]

    def _guess(name: str) -> str:
        low = re.sub(r"[^a-z0-9]+", " ", (name or "").lower())
        best, score = "", 0
        for key, pname in prods:
            words = [w for w in re.split(r"[^a-z0-9]+", pname) if len(w) > 3]
            hits = sum(1 for w in words if w in low)
            if key.replace("-", " ") in low:
                hits += 2
            if hits > score:
                best, score = key, hits
        return best if score >= 1 else ""

    filed, skipped, guessed = 0, 0, 0
    for f in files:
        meta = f.get("imageMediaMetadata") or {}
        # A hero is 1200 wide. Anything under 600 is a thumbnail, an icon or a
        # screenshot, and filing it only makes the queue longer.
        if int(meta.get("width") or 0) and int(meta["width"]) < 600:
            skipped += 1
            continue
        hit = _guess(f.get("name", ""))
        said = kb.add_asset(
            tenant, f"https://drive.google.com/uc?id={f['id']}",
            rights=kb.REFERENCE, title=f.get("name", "")[:160], kind="image",
            subject="photo", source=f.get("webViewLink", "") or "Google Drive",
            entity_key=hit, origin="drive_sync")
        if str(said).startswith("Filed"):
            filed += 1
            guessed += 1 if hit else 0
    return {"ok": True, "seen": len(files), "filed": filed,
            "skipped_small": skipped, "matched_to_a_product": guessed,
            "note": ("filed as REFERENCE and awaiting review — Drive carries "
                     "no proof of who owns a picture, so each needs 'Approve "
                     "for use' in the pictures queue before an email can "
                     "select it. Where the filename named a product, that "
                     "product is suggested on the row; check it before "
                     "approving, since a wrong match puts the wrong "
                     "photograph on that product's emails.")}
