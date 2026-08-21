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
    for ek in ents or {""}:
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
