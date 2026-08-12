"""The catalogue comes from the store, and the knowledge base still wins.

Baci had one entity against a real catalogue of hundreds. The store is
connected, structured and live, so the products come from there — but a brand's
own product copy is exactly where its banned phrases live, which is why they
are banned. A sync that imported that copy would automate the propagation of
the thing the banned list exists to stop.

So the rule: the product is catalogued and sellable, its non-compliant copy is
not imported, and the page is reported so it can be fixed.

    python3 scripts/test_catalog_sync.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cs.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import catalog_sync, db, kb, kb_seed, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


# A catalogue shaped like Shopify's, including the awkward cases.
PRODUCTS = {"products": [
    {"id": 1, "handle": "aqua-set", "title": "Aqua Dinner Set",
     "body_html": "<p>A colourful six-piece set for the table.</p>",
     "vendor": "Baci Milano", "product_type": "Tableware", "tags": "set,aqua",
     "variants": [{"price": "180.00", "inventory_management": "shopify",
                   "inventory_quantity": 12}]},
    # Copy that violates the brand's own rules.
    {"id": 2, "handle": "rosa-plate", "title": "Rosa Plate",
     "body_html": "<p>Handmade in Italy by our artisans.</p>",
     "vendor": "Baci Milano", "product_type": "Tableware", "tags": "plate",
     "variants": [{"price": "45.00", "inventory_management": "shopify",
                   "inventory_quantity": 4}]},
    # Sold out.
    {"id": 3, "handle": "zodiac-cup", "title": "Zodiac Cup",
     "body_html": "<p>Seasonal cup.</p>", "vendor": "Baci Milano",
     "product_type": "Drinkware", "tags": "zodiac",
     "variants": [{"price": "30.00", "inventory_management": "shopify",
                   "inventory_quantity": 0}]},
    # Stock not tracked — must NOT read as out of stock.
    {"id": 4, "handle": "verde-bowl", "title": "Verde Bowl",
     "body_html": "<p>A bowl.</p>", "vendor": "Baci Milano",
     "product_type": "Tableware", "tags": "bowl",
     "variants": [{"price": "60.00", "inventory_management": None,
                   "inventory_quantity": 0}]},
    # Price range across variants.
    {"id": 5, "handle": "mamma-range", "title": "Mamma Range",
     "body_html": "<p>Several sizes.</p>", "vendor": "Baci Milano",
     "product_type": "Tableware", "tags": "range",
     "variants": [{"price": "20.00", "inventory_management": "shopify",
                   "inventory_quantity": 3},
                  {"price": "95.00", "inventory_management": "shopify",
                   "inventory_quantity": 1}]},
]}


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    with db.SessionLocal() as s:
        t = s.get(db.Tenant, "baci")
        t.shopify_store = "baci"
        s.commit()

    # Stand in for the store. Everything else is real.
    from app import data_tools
    real_shopify, real_caps = data_tools._shopify, tenants.capabilities
    data_tools._shopify = lambda store, path, params=None: PRODUCTS
    tenants.capabilities = lambda k: {**real_caps(k), "commerce": True}

    banned = kb.banned_claims("baci")
    ck("baci has banned phrases to enforce", bool(banned), f"{len(banned)}")
    ck("including the one this test turns on", "handmade" in [b.lower() for b in banned])

    # ---- dry run writes nothing ------------------------------------------
    print("\n— the dry run —")
    before = len(kb.entities("baci", available_only=False))
    prev = catalog_sync.sync_shopify("baci", dry_run=True)
    ck("it reports what it would add", prev["added"] + prev["updated"] == 5,
       str(prev.get("added")) + "/" + str(prev.get("updated")))
    ck("and wrote nothing",
       len(kb.entities("baci", available_only=False)) == before)
    ck("it finds the non-compliant page before touching anything",
       len(prev["compliance_violations"]) == 1,
       str(prev["compliance_violations"]))

    # ---- the real sync ----------------------------------------------------
    print("\n— the sync —")
    r = catalog_sync.sync_shopify("baci")
    ents = {e.key: e for e in kb.entities("baci", available_only=False)}
    ck("the catalogue landed", r["products_seen"] == 5 and len(ents) >= 5,
       f"{len(ents)} entities")
    ck("everything is typed as a product",
       all(e.type == "product" for k, e in ents.items() if k in
           {"aqua-set", "rosa-plate", "zodiac-cup", "verde-bowl", "mamma-range"}))
    ck("named from the store", ents["aqua-set"].name == "Aqua Dinner Set")
    ck("single price", ents["aqua-set"].price == "$180")
    ck("a price range reads as a range", ents["mamma-range"].price == "$20–$95")
    ck("stamped so freshness can expire it",
       ents["aqua-set"].verified_at is not None and ents["aqua-set"].freshness_days)
    ck("attributed to the store", ents["aqua-set"].source == "shopify")

    # ---- stock ------------------------------------------------------------
    print("\n— stock —")
    ck("a sold-out product is marked oos",
       ents["zodiac-cup"].availability == "oos")
    ck("untracked inventory is NOT read as sold out",
       ents["verde-bowl"].availability == "available",
       "would hide most of a catalogue that does not track stock")
    live = {e.key for e in kb.entities("baci", available_only=True)}
    ck("selection cannot offer what is sold out", "zodiac-cup" not in live)
    ck("but can offer the rest", "aqua-set" in live and "verde-bowl" in live)

    # ---- the knowledge base wins -----------------------------------------
    print("\n— banned claims override the storefront —")
    rosa = ents["rosa-plate"]
    ck("the product is still catalogued and sellable",
       rosa.availability == "available" and rosa.price == "$45")
    ck("its non-compliant copy is NOT imported",
       "handmade" not in (rosa.description or "").lower(),
       repr(rosa.description))
    ck("nothing else picked the phrase up either",
       not any("handmade" in (e.description or "").lower() for e in ents.values()))
    ck("the entity carries the flag", "_compliance" in (rosa.attributes or {}),
       str(rosa.attributes.get("_compliance")))
    ck("the report names the page to fix",
       r["compliance_violations"][0]["handle"] == "rosa-plate"
       and "handmade" in [p.lower() for p in r["compliance_violations"][0]["phrases"]])
    ck("compliant copy IS imported",
       "colourful" in (ents["aqua-set"].description or "").lower(),
       repr(ents["aqua-set"].description))

    # ---- human work survives ----------------------------------------------
    print("\n— a description someone wrote by hand —")
    kb.add_entity("baci", "product", "aqua-set", "Aqua Dinner Set",
                  description="Gomeh's own wording for this set.",
                  source="captured")
    r2 = catalog_sync.sync_shopify("baci")
    again = {e.key: e for e in kb.entities("baci", available_only=False)}
    ck("a hand-authored description is not overwritten",
       again["aqua-set"].description == "Gomeh's own wording for this set.",
       repr(again["aqua-set"].description))
    ck("but its price and stock still update from the store",
       again["aqua-set"].price == "$180"
       and again["aqua-set"].availability == "available")

    # ---- idempotent --------------------------------------------------------
    print("\n— running it twice —")
    ck("a second sync updates rather than duplicating",
       r2["added"] == 0 and r2["updated"] == 5, f"{r2['added']}/{r2['updated']}")
    ck("the catalogue did not grow", len(again) == len(ents))

    # ---- refusing ----------------------------------------------------------
    print("\n— accounts with no store —")
    tenants.capabilities = real_caps
    out = catalog_sync.sync_shopify("ironside")
    ck("a venue with no commerce is refused, not guessed at",
       "no commerce connection" in out.get("error", ""), str(out)[:80])
    out = catalog_sync.sync_shopify("nosuchclient")
    ck("an unknown account is refused", "unknown tenant" in out.get("error", ""))
    data_tools._shopify = real_shopify

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
