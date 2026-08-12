"""Shopify catalogue -> KbEntity, with a compliance pass on the way in.

Baci had one entity against a real catalogue of hundreds, because the only ways
into `KbEntity` were the seed and someone typing. The catalogue already exists,
structured and live, in a store this platform is connected to — crawling a
storefront to recover what an API serves properly would be strictly worse.

Two things happen in one pass:

  1. SYNC — products become entities with `source="shopify"` and a
     `verified_at` stamp, so `freshness_days` can do its job: past that, the
     assembler blocks rather than quietly using stale prices.

  2. COMPLIANCE — every title and description is checked against the account's
     `banned_claims`, and a hit is reported. A brand's own product copy is
     exactly where its banned phrases live, which is why they are banned; the
     sync surfaces them rather than importing them silently.

The rule the compliance pass follows: **the knowledge base wins.** A phrase the
account has banned does not become sayable because it appears on the storefront.
Selection may still return the product — it exists and it sells — but its prose
is quarantined, so nothing downstream can quote copy the brand has ruled out.
The real fix is the product page, and this is what tells you which ones.
"""
from __future__ import annotations

from . import db, kb, tenants

# Attribute keys the sync owns. Anything else on an entity was authored by a
# human and is never touched.
_SYNCED_ATTRS = ("vendor", "product_type", "tags", "variants", "sku")


def _available(product: dict) -> str:
    """available | oos, from live inventory.

    A variant with no inventory tracking is available — Shopify reports
    `inventory_quantity: 0` for untracked items, and reading that as
    out-of-stock would hide most of a catalogue that does not track stock.
    """
    variants = product.get("variants") or []
    if not variants:
        return "available"
    for v in variants:
        if not v.get("inventory_management"):
            return "available"          # not tracked
        if int(v.get("inventory_quantity") or 0) > 0:
            return "available"
    return "oos"


def _price(product: dict) -> str:
    prices = []
    for v in product.get("variants") or []:
        try:
            prices.append(float(v.get("price") or 0))
        except (TypeError, ValueError):
            continue
    prices = [p for p in prices if p > 0]
    if not prices:
        return ""
    lo, hi = min(prices), max(prices)
    return f"${lo:,.0f}" if lo == hi else f"${lo:,.0f}–${hi:,.0f}"


def _text(product: dict) -> str:
    """Title + body, tags stripped — what a generator could end up quoting."""
    import re
    body = re.sub(r"<[^>]+>", " ", product.get("body_html") or "")
    return f"{product.get('title', '')} {body}"


def check_compliance(tenant: str, text: str) -> list[str]:
    """Which of this account's banned phrases appear in some copy."""
    low = (text or "").lower()
    return [p for p in kb.banned_claims(tenant) if p and p.lower() in low]


def sync_shopify(tenant: str, limit: int = 250, dry_run: bool = False) -> dict:
    """Pull the catalogue into the knowledge base. Idempotent.

    `dry_run` reports what would change and writes nothing — the same discipline
    as the tenant backfill, because a bulk write over a knowledge base someone
    has been editing deserves a preview.
    """
    t = tenants.get(tenant)
    if not t:
        return {"error": f"unknown tenant {tenant!r}"}
    if not tenants.capabilities(tenant).get("commerce"):
        return {"error": f"{tenant} has no commerce connection"}

    from . import data_tools
    try:
        raw = data_tools._shopify(t.shopify_store, "products.json",
                                  {"limit": min(int(limit or 250), 250)})
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{exc.__class__.__name__}: {str(exc)[:200]}"}
    products = raw.get("products") or []

    added = updated = skipped = 0
    violations: list[dict] = []
    oos: list[str] = []

    with db.SessionLocal() as s:
        existing = {e.key: e for e in s.query(db.KbEntity).filter(
            db.KbEntity.tenant == tenant).all()}

        for p in products:
            key = (p.get("handle") or str(p.get("id") or "")).strip().lower()
            if not key:
                continue
            hits = check_compliance(tenant, _text(p))
            if hits:
                violations.append({"product": p.get("title", ""),
                                   "handle": key, "phrases": hits,
                                   "url": f"https://{t.domain}/products/{key}"})

            row = existing.get(key)
            human = bool(row and (row.source or "") not in ("shopify", ""))
            if dry_run:
                if row:
                    updated += 1
                else:
                    added += 1
                if _available(p) == "oos":
                    oos.append(p.get("title", key))
                continue

            if not row:
                row = db.KbEntity(tenant=tenant, key=key, type="product")
                s.add(row)
                added += 1
            else:
                updated += 1

            # The store owns price and stock, always — that is the whole point
            # of syncing rather than typing. It owns the prose only when it
            # wrote it: a description someone edited through intake is human
            # work and a sync must not silently overwrite it.
            row.name = p.get("title") or row.name or key
            row.price = _price(p) or row.price
            row.availability = _available(p)
            if row.availability == "oos":
                oos.append(row.name)
            if not human:
                # Copy carrying a banned phrase is not imported as description.
                # It exists on the storefront; that does not make it sayable.
                row.description = ("" if hits else
                                   _text(p).replace(p.get("title", ""), "").strip()[:600])
            attrs = dict(row.attributes or {})
            attrs.update({
                "vendor": p.get("vendor", ""),
                "product_type": p.get("product_type", ""),
                "tags": p.get("tags", ""),
                "variants": len(p.get("variants") or []),
            })
            if hits:
                attrs["_compliance"] = f"storefront copy uses: {', '.join(hits)}"
            else:
                attrs.pop("_compliance", None)
            row.attributes = attrs
            row.source = row.source if human else "shopify"
            row.verified_at = db.utcnow()
            row.freshness_days = row.freshness_days or "7"
        if not dry_run:
            s.commit()

    return {
        "tenant": tenant, "dry_run": dry_run,
        "products_seen": len(products),
        "added": added, "updated": updated, "skipped": skipped,
        "out_of_stock": len(oos),
        "out_of_stock_examples": oos[:8],
        "compliance_violations": violations,
        "note": ("Products whose storefront copy uses a banned phrase are listed "
                 "under compliance_violations. They are still catalogued and "
                 "sellable — their copy is not imported, so nothing downstream "
                 "can quote it. Fix the product page to clear the flag."),
    }
