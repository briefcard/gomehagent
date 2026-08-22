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

from . import db, kb, provenance as prov, tenants

# Attribute keys the sync owns. Anything else on an entity was authored by a
# human and is never touched.
_SYNCED_ATTRS = ("vendor", "product_type", "tags", "variants", "sku",
                 "status", "published")


def _available(product: dict) -> str:
    """available | draft | archived | unpublished | oos — can a customer buy it.

    This used to read inventory ALONE, and that is how Eien's first letter
    campaign came to recommend CitroBurn, a product that was not active and not
    in stock (owner, 2026-08-22). The Shopify call was fine and the payload
    carried `status` and `published_at` the whole time; the code looked only at
    `variants[]`, so an unpublished draft with untracked inventory was recorded
    as `available` and every layer downstream believed it.

    Order matters: status first, publication second, stock last. A draft that
    happens to have stock is still a draft, and saying "out of stock" about it
    would send someone to check the warehouse for a problem that is in the
    store's admin. The value is the REASON, so whoever reads it — the
    validator, the console, a run note — can say something true.

    A variant with no inventory tracking counts as in stock: Shopify reports
    `inventory_quantity: 0` for untracked items, and reading that as
    out-of-stock would hide most of a catalogue that does not track stock.
    """
    status = str(product.get("status") or "").strip().lower()
    if status == "draft":
        return "draft"
    if status == "archived":
        return "archived"
    # `published_at` is null for a product not published to the online store.
    # Only trusted when the key is actually present: a payload that never
    # carried it must not be read as "unpublished".
    if "published_at" in product and not product.get("published_at"):
        return "unpublished"

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


def sync_collections(tenant: str, adopt: list[str] | None = None,
                     dry_run: bool = False) -> dict:
    """Import Shopify collections as groups. Parentage is **opt-in**.

    Every collection lands as a `type="collection"` entity, which is always
    safe — it is a thing that exists. What does NOT happen automatically is
    members being assigned to it, because a Shopify collection is as often a
    merchandising bucket as a product range. "Sale", "New Arrivals" and "Under
    $50" sit in the same list as "Aqua", and a claim scoped to a group is a
    claim asserted about every member: "shatterproof acrylic" is true of the
    Aqua range and meaningless of everything currently discounted.

    So `adopt` names the collections that are real ranges, and only those get
    parentage. Getting this wrong is not a tidiness problem — it would put a
    material claim on the wrong products with nothing to catch it, because a
    group claim is approved once and inherited silently.
    """
    t = tenants.get(tenant)
    if not t:
        return {"error": f"unknown tenant {tenant!r}"}
    if not tenants.capabilities(tenant).get("commerce"):
        return {"error": f"{tenant} has no commerce connection"}

    from . import data_tools
    adopt_set = {a.strip().lower() for a in (adopt or []) if a.strip()}

    found: list[dict] = []
    try:
        for path, kind in (("custom_collections.json", "custom"),
                           ("smart_collections.json", "smart")):
            raw = data_tools._shopify(t.shopify_store, path, {"limit": 250})
            for c in (raw.get(path.split(".")[0]) or []):
                handle = (c.get("handle") or "").strip().lower()
                if handle:
                    found.append({"id": c.get("id"), "handle": handle,
                                  "title": c.get("title") or handle,
                                  "kind": kind})
    except Exception as exc:                                     # noqa: BLE001
        return {"error": f"{exc.__class__.__name__}: {str(exc)[:200]}"}

    created, adopted, refused = 0, 0, []
    for c in found:
        if not dry_run:
            kb.add_entity(tenant, "collection", c["handle"], c["title"],
                          description=f"Shopify {c['kind']} collection",
                          source=f"https://{t.domain}/collections/{c['handle']}",
                          origin="store_sync")
        created += 1
        if c["handle"] not in adopt_set:
            continue

        try:
            raw = data_tools._shopify(t.shopify_store, "products.json",
                                      {"collection_id": c["id"], "limit": 250,
                                       "fields": "id,handle"})
        except Exception as exc:                                 # noqa: BLE001
            refused.append(f"{c['handle']}: could not list members "
                           f"({exc.__class__.__name__})")
            continue
        members = [(p.get("handle") or "").strip().lower()
                   for p in (raw.get("products") or [])]
        # Membership is additive. A product sitting in `aqua`, `acrylics-
        # polycarbonate` and `italian-pitchers-carafes` belongs in all three,
        # and adopting a second collection must not evict it from the first.
        for m in [m for m in members if m]:
            if dry_run:
                adopted += 1
                continue
            msg = kb.join_group(tenant, m, c["handle"])
            if "is now in" in msg or "already in" in msg:
                adopted += 1
            else:
                refused.append(msg)

    return {"collections_found": created,
            "adopted": sorted(adopt_set),
            "members_assigned": adopted,
            "refused": refused,
            "available_to_adopt": sorted(
                c["handle"] for c in found if c["handle"] not in adopt_set),
            "dry_run": dry_run,
            "note": ("collections are imported as entities either way; only "
                     "the ones named in `adopt` get members, because a group "
                     "claim is asserted about every member and a merchandising "
                     "bucket is not a range")}


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
    held: list[dict] = []      # fields the store wanted to change and could not
    to_file: list[dict] = []   # product photos for the creative library

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
            if dry_run:
                if row:
                    updated += 1
                else:
                    added += 1
                if _available(p) == "oos":
                    oos.append(p.get("title", key))
                continue

            ref = f"https://{t.domain}/products/{key}"
            if not row:
                # The store is the system of record for what exists, so a new
                # product lands usable rather than queued — 250 products in a
                # review queue is a review queue nobody opens. What the store
                # does NOT get is the right to change copy a human has since
                # approved; that is `may_write`'s job on the next pass.
                row = db.KbEntity(
                    tenant=tenant, key=key, type="product",
                    name=p.get("title") or key,   # NOT NULL, and flush is next
                    origin="store_sync", review=prov.APPROVED,
                    approved_by="store_sync", approved_at=db.utcnow(),
                    fingerprint=prov.fingerprint(key), source="shopify")
                s.add(row)
                s.flush()          # needs an id before a conflict can name it
                added += 1
            else:
                updated += 1

            # Copy carrying a banned phrase is never imported. It exists on the
            # storefront; that does not make it sayable.
            desc = ("" if hits else
                    _text(p).replace(p.get("title", ""), "").strip()[:600])

            # One shared precedence rule instead of this file's own. The store
            # owns price and availability outright, forever. Everything else it
            # may refresh only while the row is still store-owned — the moment
            # a human edits or approves the prose, a disagreeing sync records a
            # conflict and changes nothing.
            res = prov.apply_fields(
                row, {"name": p.get("title") or key, "price": _price(p),
                      "description": desc},
                "store_sync", ref, table="kb_entities", tenant=tenant)
            for field in res["conflicts"]:
                held.append({"product": p.get("title", ""), "handle": key,
                             "field": field, "url": ref})

            row.availability = _available(p)   # owned outright — never blocked
            if row.availability != "available":
                oos.append(f"{row.name} ({row.availability})")

            attrs = dict(row.attributes or {})
            attrs.update({
                "vendor": p.get("vendor", ""),
                "product_type": p.get("product_type", ""),
                "tags": p.get("tags", ""),
                "variants": len(p.get("variants") or []),
                # The RAW facts behind `availability`, kept so the reason is
                # auditable rather than a verdict nobody can check. These were
                # in every payload already and were being dropped.
                "status": p.get("status", ""),
                "published": bool(p.get("published_at")),
            })
            # The product's own photograph — what the campaign's product
            # cards and entity-scoped heroes render. The store publishes it
            # on the product page already, so reading it invents nothing;
            # a product without one simply carries no image.
            img = ((p.get("image") or {}).get("src")
                   or next((i.get("src") for i in (p.get("images") or [])
                            if i.get("src")), ""))
            if img:
                attrs["image"] = img
                to_file.append({"key": key, "url": img,
                                "title": p.get("title") or key})
            if hits:
                attrs["_compliance"] = f"storefront copy uses: {', '.join(hits)}"
            else:
                attrs.pop("_compliance", None)
            row.attributes = attrs
            row.verified_at = db.utcnow()
            row.freshness_days = row.freshness_days or "7"
        if not dry_run:
            s.commit()

    # File each product photo in the creative library, OUTSIDE the entity
    # session (add_asset opens its own). rights=owned is a fact, not a guess:
    # these are the client's photographs of the client's products, already
    # published on their own storefront — and `origin="store_sync"` lands
    # them usable for the same reason the entities themselves do, so the
    # campaign hero can be a real, RELEVANT product shot instead of an
    # imageless send. `add_asset` is duplicate-safe by URL, so a re-sync
    # re-files nothing.
    images_filed = 0
    if not dry_run:
        from . import kb
        for f in to_file:
            said = kb.add_asset(tenant, f["url"], rights="owned",
                                title=f["title"], kind="image",
                                subject="object", source="shopify",
                                entity_key=f["key"], origin="store_sync")
            if said.startswith("Filed"):
                images_filed += 1

    return {
        "tenant": tenant, "dry_run": dry_run,
        "products_seen": len(products),
        "images_filed": images_filed,
        "added": added, "updated": updated, "skipped": skipped,
        "out_of_stock": len(oos),
        "out_of_stock_examples": oos[:8],
        "compliance_violations": violations,
        "held_back": held,
        "held_back_count": len(held),
        "note": ("Products whose storefront copy uses a banned phrase are listed "
                 "under compliance_violations. They are still catalogued and "
                 "sellable — their copy is not imported, so nothing downstream "
                 "can quote it. Fix the product page to clear the flag. "
                 "`held_back` is the other direction: fields the store wanted to "
                 "change on a row a human has approved. Those were not written — "
                 "each is a conflict on the Knowledge tab, to keep or discard."),
    }
