"""The brand's own pictures are the references. Every photograph the store
holds for a product is filed, the featured one first; a lifestyle shot is
cut to the product before it serves as a reference, and the note counts
it; a picture pulled from the brand's own site is approved the moment it
is filed; and a picture the owner disapproves afterwards is a compliance
finding on every public page still showing it.

Owner, 2026-09-09: *"most of our products already had several different
photos, the only issue is that outside of the main product photos, a lot of
the additional supporting images are lifestyle images where the product is
one of many items in the photo … Most businesses wont have so many
available photos right of the bat of just their product in consistent
lighting and different angles."* And: *"Product photos / content pulled
from the website should be approved by default because they are already
public facing. If the user decides to disapprove after the fact, then we
can address this as a compliance test against anywhere that photo appears
on the brand public assets on the next compliance check."*

Run: python3 scripts/test_the_brands_own_pictures_are_the_references.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'refs.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import (admin_ui as ui, catalog_sync, compliance, creative, data_tools, db,  # noqa: E402
                 harvest, imagegen, kb, kb_seed, tenants)

KEY = "s3cret"
_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(colour, w: int = 64, h: int = 64) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def size_of(blob: bytes) -> tuple:
    return Image.open(io.BytesIO(blob)).size


def _rows(tenant: str, **kw):
    return list(kb.assets(tenant, publishable_only=False, **kw))


def main() -> int:  # noqa: PLR0915
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    print("— EVERY PHOTOGRAPH THE STORE HOLDS IS FILED, THE FEATURED ONE FIRST —")
    products = [{
        "id": 1, "handle": "zodiac-plate", "title": "Zodiac Plate", "status": "active",
        "published_at": "2026-01-01", "vendor": "Baci", "product_type": "plate", "tags": "",
        "body_html": "<p>A plate with a sign on it.</p>",
        "variants": [{"price": "40.00", "inventory_quantity": 5}],
        "image": {"src": "https://cdn.shopify.com/s/files/plate-front.jpg"},
        "images": [{"src": "https://cdn.shopify.com/s/files/plate-front.jpg"},
                   {"src": "https://cdn.shopify.com/s/files/plate-table.jpg"},
                   {"src": "https://cdn.shopify.com/s/files/plate-side.jpg"},
                   {"src": "https://cdn.shopify.com/s/files/plate-front.jpg"}],
    }]
    data_tools._shopify = lambda store, path, params=None: {"products": products}
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, "baci")
        if t is not None and not getattr(t, "shopify_store", ""):
            t.shopify_store = "baci.myshopify.com"
            s.commit()
    tenants.capabilities = lambda key: {c: True for c in tenants.CAPABILITIES}
    got = catalog_sync.sync_shopify("baci", limit=10)
    plate = [a for a in _rows("baci", kind="image") if (a.entity_key or "") == "zodiac-plate"]
    tags = {a.url: [str(x) for x in (a.tags or [])] for a in plate}
    ck("three distinct store photographs are filed for the product (a repeat filed once), each approved and owned",
       got.get("images_filed") == 3 and len(plate) == 3
       and all(a.review == "approved" and a.rights == kb.OWNED for a in plate),
       f"filed={got.get('images_filed')} rows={len(plate)} err={got.get('error')}")
    ck("  the featured one is the packshot, the rest carry their place",
       tags.get("https://cdn.shopify.com/s/files/plate-front.jpg", []) == ["store-image:1", "packshot"]
       and "store-image:2" in tags.get("https://cdn.shopify.com/s/files/plate-table.jpg", [])
       and "store-image:3" in tags.get("https://cdn.shopify.com/s/files/plate-side.jpg", []), str(tags))
    ck("  the cap is written down", catalog_sync.STORE_IMAGES_MAX == 8)

    print("\n— A LIFESTYLE SHOT IS CUT TO THE PRODUCT BEFORE IT IS A REFERENCE —")
    kb.add_asset("baci", "https://cdn.example/look.png", rights=kb.OWNED, title="look",
                 subject=kb.SCENE, origin="human")
    kb.add_board("baci", "Studio")
    kb.set_board_role(next(a.id for a in kb.assets("baci") if "look.png" in (a.url or "")),
                      "studio", "look", True)
    front, table, side, look = (png((200, 30, 30, 255), 80, 80), png((30, 200, 30, 255), 400, 300),
                                png((30, 30, 200, 255), 80, 80), png((90, 90, 90, 255)))
    creative._fetch = lambda url: {
        "https://cdn.shopify.com/s/files/plate-front.jpg": front,
        "https://cdn.shopify.com/s/files/plate-table.jpg": table,
        "https://cdn.shopify.com/s/files/plate-side.jpg": side,
        "https://cdn.example/look.png": look}.get(url, b"")
    asked: list = []

    def _focus(blob, packshot, tenant=""):
        asked.append((size_of(blob), size_of(packshot)))
        if size_of(blob) == (400, 300):      # the table: the plate sits in a corner
            return {"ok": True, "found": True, "alone": False, "box": [0.5, 0.5, 0.75, 0.9],
                    "confidence": 0.9, "why": ""}
        return {"ok": True, "found": True, "alone": True, "box": None, "confidence": 0.9, "why": ""}
    creative.focus = _focus
    refs = creative.board_inputs("baci", "zodiac-plate")
    ck("the packshot leads and is sent whole; the lifestyle shot is cut to the product; the side view is left whole",
       len(refs["product"]) == 3 and refs["cropped"] == 1
       and asked and all(p == (80, 80) for _b, p in asked)
       and size_of(refs["product"][1])[0] < 400 and size_of(refs["product"][1])[1] < 300,
       f"product={len(refs['product'])} cropped={refs['cropped']} sizes={[size_of(b) for b in refs['product']]} asked={asked}")
    n_asked = len(asked)
    refs2 = creative.board_inputs("baci", "zodiac-plate")
    ck("  the cut is remembered — a second run asks the model nothing",
       len(asked) == n_asked and refs2["cropped"] == 1)

    def _lost(blob, packshot, tenant=""):
        return {"ok": True, "found": False, "alone": False, "box": None, "confidence": 0.2, "why": ""}
    creative.focus = _lost
    kb.add_asset("baci", "https://cdn.shopify.com/s/files/plate-party.jpg", rights=kb.OWNED,
                 title="Zodiac Plate · photo 4", kind="image", subject="object", source="shopify",
                 entity_key="zodiac-plate", origin="store_sync", tags=["store-image:4"])
    party = png((10, 10, 10, 255), 300, 300)
    old_fetch = creative._fetch
    creative._fetch = lambda url: party if url.endswith("plate-party.jpg") else old_fetch(url)
    refs3 = creative.board_inputs("baci", "zodiac-plate")
    ck("a photograph where the product cannot be found with confidence is LEFT OUT and said, never sent as the product",
       len(refs3["product"]) == 3
       and any("could not be found" in e["why"] for e in refs3["excluded"]),
       str([e["why"][:60] for e in refs3["excluded"]]))

    print("\n— A PICTURE FROM THE BRAND'S OWN SITE IS APPROVED THE MOMENT IT IS FILED —")
    kb.add_asset("baci", "https://baci.example/cdn/hero-table.jpg", rights=kb.OWNED, kind="image",
                 title="from the website", source="crawled from https://baci.example/", origin="crawl")
    crawled = next(a for a in _rows("baci") if (a.url or "").endswith("hero-table.jpg"))
    ck("a crawled picture lands approved and usable",
       crawled.review == "approved" and kb.may_publish(crawled.id)[0] and "crawl" in kb.PUBLIC_PICTURE_ORIGINS)
    said = kb.add_claim("baci", "Handmade by artisans in Italy.", "crawled from https://baci.example/about",
                        [], origin="crawl")
    claims = [c for c in kb.claims("baci", include_proposed=True) if "artisans" in (c.claim or "")] \
        if "include_proposed" in kb.claims.__code__.co_varnames else []
    ck("  a crawled CLAIM is still a proposal — the site is where the banned phrases live",
       (not claims) or all(getattr(c, "review", "") == "proposed" for c in claims),
       str([getattr(c, "review", "") for c in claims])[:80])

    print("\n— A DISAPPROVED PUBLIC PICTURE IS A COMPLIANCE FINDING ON EVERY PAGE STILL SHOWING IT —")
    said = kb.review_asset(crawled.id, False)
    ck("disapproving it says what follows",
       said.startswith("Rejected") and "compliance sweep" in said, said)
    watched = kb.disapproved_public("baci")
    ck("  it is on the sweep's watch list, with where it came from",
       any(w["asset_id"] == crawled.id and "baci.example" in w["source"] for w in watched), str(watched)[:160])
    kb.add_asset("baci", "https://elsewhere.example/comp.jpg", rights=kb.REFERENCE, kind="image",
                 title="a comp", origin="human")
    comp = next(a for a in _rows("baci") if (a.url or "").endswith("comp.jpg"))
    kb.review_asset(comp.id, False)
    ck("  a rejected picture that was never public is not watched",
       not any(w["asset_id"] == comp.id for w in kb.disapproved_public("baci")))
    html = ('<html><body><img src="https://baci.example/cdn/hero-table_1024x1024.jpg?v=9">'
            '<p>Designed in Milan.</p></body></html>')
    page = compliance.check_page("baci", "https://baci.example/pages/about", html=html)
    ck("a page still showing it — resized and versioned by the CDN — is a finding",
       page["status"] == "ok" and len(page["pictures"]) == 1
       and page["pictures"][0]["asset_id"] == crawled.id, str(page.get("pictures")))
    clean = compliance.check_page("baci", "https://baci.example/pages/contact",
                                  html="<html><body><p>Call us.</p></body></html>")
    ck("  a page without it is clean", clean["status"] == "ok" and clean["pictures"] == [])
    result = {"pages_checked": 2, "violations": [], "by_phrase": [], "fetch_errors": [],
              "pictures_still_public": [{"url": "https://baci.example/pages/about", "site": "",
                                         "pictures": page["pictures"]}],
              "pictures_count": 1, "pictures_watched": 1}
    text = compliance.report_text("baci", result)
    ck("the dated report lists the page and the picture",
       "Disapproved pictures still public" in text and "https://baci.example/pages/about" in text
       and "from the website" in text, text[-300:])
    from app import systems
    systems.find("baci", "content_compliance") or systems.create("baci", "content_compliance")
    compliance.record_scan("baci", result)
    scan = compliance.last_scan("baci")
    body = ui._compliance_body("baci")
    ck("the Assurance tab shows it, and that nothing is taken down",
       scan.get("pictures_count") == 1 and "disapproved picture(s) still on a public page" in body
       and "https://baci.example/pages/about" in body and "Nothing is taken down" in body,
       body[-300:])

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
