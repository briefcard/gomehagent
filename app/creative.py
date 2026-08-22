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


def _usable(rows: list, entity_keys: set[str]) -> list:
    """Publishable images, heroes only, entity-scoped first.

    `kb.assets` already enforced approved+owned; this layer only ORDERS and
    excludes logos — a brand mark as the hero reads as a letterhead, and the
    header already carries the logo from the theme.
    """
    heroes = [r for r in rows if (r.subject or "") != kb.LOGO and (r.url or "")]
    scoped = [r for r in heroes if (r.entity_key or "") in entity_keys]
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
    ents = {k for k in (entity_keys or []) if k}
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
    pick = next(iter(_usable(rows, ents)), None)
    if pick is not None:
        # Belt to the braces `kb.assets` already provides: the use-gate names
        # its own refusal, and a row that fails it is skipped, not shipped.
        allowed, why = kb.may_publish(pick.id)
        if allowed:
            return {"ok": True, "basis": "approved_asset",
                    "asset_id": pick.id,
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
