"""May this thing be NAMED in outbound content — and what does that mean here.

Eien's first letter-format campaign told a careful story about GLP-1 and closed
by recommending CitroBurn, a product that was not active and not in stock
(owner, 2026-08-22). Nothing in the pipeline was broken in the way that usually
means: the Shopify connection worked, the sync ran, the product came back from
the API with its `status` field in the payload. The code read `variants[]` for
inventory and discarded the rest, so the knowledge base recorded
`availability="available"` for a product nobody could buy, and every layer
downstream believed it.

Three lessons are baked into this module.

**1. "Available" is a composite, and the parts differ by business.** For a shop
it is: the product is active, it is published to the channel, and it is in
stock (or untracked). For a venue it is: the room still exists and is bookable.
For a spec business: it is still in the catalogue and has the numbers a
specifier needs. One boolean cannot be shared across those without meaning
something different in each — so the REQUIREMENT is declared per business
model here, while the FACTS stay on the entity.

**2. The check has to run against what was written, not against a parameter.**
`validator.entity_unavailable` has always been right and has always been
narrow: it takes ONE `entity_key` and campaigns pass none. The email that
caused this named its product in a sentence — "CitroBurn came out of that
process" — and no key was involved anywhere. So `named_unfit` reads the COPY.
A generator can mention anything; what governs is what the words say.

**3. Absence of a fact is not permission.** An entity whose status was never
recorded is not thereby fine to promote. Where a rule needs a fact the sync
never captured, this says so by name and treats it as unfit, because the
alternative is exactly the failure above.
"""
from __future__ import annotations

import re

#: What each business model requires before an entity may be named in outbound
#: content. `availability` lists the acceptable values of that field; `needs`
#: names attributes that must be present and non-empty, because a thing you
#: cannot quote a price or a capacity for is a thing you are not ready to sell
#: in an email.
#:
#: A model that is not listed falls back to `_DEFAULT`. That fallback is
#: deliberately strict: a new business type should refuse to promote something
#: it does not understand rather than promote it and find out.
#: `needs` is deliberately EMPTY everywhere today. It is the extension point
#: for per-business requirements the owner actually states — a venue that must
#: have a capacity on file before it is pitched, a spec business that must have
#: a lead time — and not a place to guess. The first draft of this required a
#: `price` for e-commerce and immediately refused real products whose price had
#: not synced, which is the failure mode that gets a check switched off. A rule
#: nobody asked for costs more than the case it catches.
FEATURABLE: dict[str, dict] = {
    "ecom_inventory": {"availability": ("available",), "needs": ()},
    "ecom_dtc": {"availability": ("available",), "needs": ()},
    # A room is not "in stock" — it exists and is bookable, which is what
    # `unbookable` records.
    "local_venue": {"availability": ("available",), "needs": ()},
    "b2b_spec": {"availability": ("available",), "needs": ()},
    "digital_products": {"availability": ("available",), "needs": ()},
}

_DEFAULT = {"availability": ("available",), "needs": ()}

#: Why each availability value means "do not promote this". Written for the
#: person reading the run, not for a log.
_REASON = {
    "oos": "it is out of stock",
    "draft": "it is a draft in the store, not published",
    "archived": "it is archived in the store",
    "unpublished": "it is not published to the online store",
    "unbookable": "it is not bookable",
}


def rules_for(model: str) -> dict:
    return FEATURABLE.get(str(model or ""), _DEFAULT)


def _val(entity, name: str):
    """Read a field off either an ORM row or a plain dict — both shapes reach
    here, and the caller should not have to care which."""
    if isinstance(entity, dict):
        if name in entity:
            return entity.get(name)
        return (entity.get("attributes") or {}).get(name)
    got = getattr(entity, name, None)
    if got is None:
        got = (getattr(entity, "attributes", None) or {}).get(name)
    return got


def unfit(model: str, entity) -> str:
    """Why this entity may not be named in outbound content, or "" if it may."""
    rules = rules_for(model)
    avail = str(_val(entity, "availability") or "").strip()
    if not avail:
        # Never recorded. Not the same as fine — see the module docstring.
        return ("its availability was never recorded — re-run the catalogue "
                "sync before featuring it")
    if avail not in rules["availability"]:
        return _REASON.get(avail, f"its availability is {avail!r}")
    for field in rules["needs"]:
        if not str(_val(entity, field) or "").strip():
            return f"it has no {field} on file, so it is not ready to feature"
    return ""


def screen(model: str, entities: list) -> tuple[list, list]:
    """Split entities into (may be featured, refused-with-reason)."""
    fit, refused = [], []
    for e in entities or []:
        why = unfit(model, e)
        if why:
            refused.append({"key": str(_val(e, "key") or ""),
                            "name": str(_val(e, "name") or ""), "why": why})
        else:
            fit.append(e)
    return fit, refused


def named_unfit(model: str, text: str, entities: list) -> list[dict]:
    """Entities NAMED in this copy that must not be promoted.

    The last line of defence, and the one that would have caught the Eien
    email: the product was never a parameter and never a product card, it was
    a sentence. Matching is on the entity's own name, whole-word and
    case-insensitive.

    Names shorter than four characters are skipped. A catalogue with a product
    called "Duo" or "Air" would otherwise flag every email containing the word,
    and a check that cries wolf gets switched off — which costs more than the
    rare miss it prevents.
    """
    body = str(text or "")
    out: list[dict] = []
    for e in entities or []:
        name = str(_val(e, "name") or "").strip()
        if len(name) < 4:
            continue
        why = unfit(model, e)
        if not why:
            continue
        if re.search(r"\b" + re.escape(name) + r"\b", body, re.I):
            out.append({"key": str(_val(e, "key") or ""), "name": name,
                        "why": why})
    return out
