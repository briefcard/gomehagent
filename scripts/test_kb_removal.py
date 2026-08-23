"""Taking things OUT of the knowledge base, and keeping drafts out of it.

Owner, 2026-08-23: "In the example with Eien Health, we have draft products
polluting our entities and therefore all of our systems. Lets add the ability to
remove entities from our knowledgebase and make sure that draft products are not
synced from Shopify. This is true for approved photos, claims, objections, etc."

Two halves, and the second one is the reason the first was needed.

THE SYNC. `sync_shopify` had exactly one skip in its whole loop — an empty
handle — so every product the API returned became a KbEntity with
`review=APPROVED`, its title, price, description and photograph imported, and
only `availability="draft"` to mark it. Labelling was the right first move
(§2.68 — it is what stopped a draft being RECOMMENDED) and it was not enough,
because a label only protects the readers that check it. The catalogue counts,
the completeness score, the entity picker and the coherence proof scopes all saw
a real product.

THE REMOVAL. There was no way to take one out. Rejection is what every read
accessor already filters on, so this is soft by design — and reversible, which
is what makes it safe to offer at all.

The part that is not obvious, and is pinned hardest here: removing an entity
STRANDS what was scoped to it. A claim whose `entity_key` names a row that is no
longer active cannot even be EDITED — the editor validates the key against
`entities()` and refuses — so it becomes unreachable rather than merely unused.
Anything scoped only to the entity comes out with it, and the caller is told how
many.

Run: python3 scripts/test_kb_removal.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'kbrm.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import catalog_sync, data_tools, db, kb, tenants  # noqa: E402
from app.web import app  # noqa: E402

KEY = "s3cret"
client = TestClient(app)
_fails = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def keys(tenant="baci"):
    return sorted(e.key for e in kb.entities(tenant, available_only=False))


def main() -> int:
    db.init_db()
    tenants.seed()
    _all = {c: True for c in tenants.CAPABILITIES}
    tenants.capabilities = lambda k: dict(_all)

    # ---------------------------------------------------------------- sync --
    print("— a draft is not a product yet —")
    PRODUCTS = {"products": [
        {"id": 1, "handle": "live-one", "title": "Live One", "status": "active",
         "published_at": "2026-01-01",
         "variants": [{"inventory_management": None, "price": "10"}]},
        {"id": 2, "handle": "draft-one", "title": "Draft One", "status": "draft",
         "variants": [{"inventory_management": None, "price": "20"}]},
        {"id": 3, "handle": "arch-one", "title": "Archived One",
         "status": "archived", "variants": []},
    ]}
    data_tools._shopify = lambda store, path, params=None: PRODUCTS
    out = catalog_sync.sync_shopify("baci")
    ck("a draft product is not catalogued at all",
       "draft-one" not in keys(), str(keys()))
    ck("…nor an archived one", "arch-one" not in keys())
    ck("…while the live one is", "live-one" in keys())
    ck("the sync SAYS what it left out, rather than silently importing less",
       out.get("drafts_skipped") == 2
       and any("Draft One" in x for x in out.get("drafts_skipped_examples", [])),
       str(out.get("drafts_skipped_examples")))

    print("\n— and a product that BECOMES a draft is taken back out —")
    # Without this the fix protects new accounts and leaves every existing one
    # polluted for ever, which is the half that actually bit this owner.
    PRODUCTS["products"][0]["status"] = "draft"
    out2 = catalog_sync.sync_shopify("baci")
    ck("it leaves the catalogue on the next sync",
       "live-one" not in keys(), str(keys()))
    ck("…and the sync names it, because a row vanishing unannounced is worse "
       "than one that stays", out2.get("retired_now_draft") == 1,
       str(out2.get("retired_now_draft_examples")))
    ck("draft and out-of-stock are still counted separately — one is real and "
       "coming back, the other was never a product",
       "drafts_skipped" in out2 and "out_of_stock" in out2)

    # ------------------------------------------------------------- removal --
    print("\n— removing an entity takes what was scoped to it —")
    kb.add_entity("baci", "product", "aqua", "Aqua pitcher", description="x")
    kb.add_claim("baci", "Only true of the Aqua pitcher.", "spec", [],
                 origin="human", status="active", entity_key="aqua")
    kb.add_claim("baci", "True of the whole brand.", "spec", [],
                 origin="human", status="active")
    kb.add_objection("baci", "Does the Aqua drip?", "No.", origin="human",
                     entity_key="aqua")
    kb.add_asset("baci", "https://cdn.example/aqua.jpg", rights=kb.OWNED,
                 title="Aqua on linen", entity_key="aqua", origin="human")
    ent = [e for e in kb.entities("baci", available_only=False)
           if e.key == "aqua"][0]

    before_brand = len([c for c in kb.claims("baci")])
    got = kb.remove("baci", "entity", ent.id)
    ck("it reports what came out with it",
       got["ok"] and got["also"].get("claims") == 1
       and got["also"].get("objections") == 1
       and got["also"].get("photographs") == 1, str(got.get("also")))
    ck("the entity is gone from the catalogue", "aqua" not in keys())
    ck("its photograph is out of the library",
       not [a for a in kb.assets("baci", publishable_only=True, kind="image")
            if a.entity_key == "aqua"])
    ck("its objection is out", not [o for o in kb.objections("baci")
                                    if o.entity_key == "aqua"])
    ck("the BRAND-WIDE claim is untouched — only what was scoped to it went",
       len([c for c in kb.claims("baci")]) == before_brand,
       f"{len(list(kb.claims('baci')))} vs {before_brand}")
    ck("nothing was deleted, and the message says so",
       "restored" in got["said"].lower(), got["said"])

    print("\n— and it can be put back —")
    back = kb.restore("baci", "entity", ent.id)
    ck("the entity returns", back["ok"] and "aqua" in keys())
    ck("…but its claims do NOT come back in bulk — that is one decision each",
       not [c for c in kb.claims("baci", entity_key="aqua")
            if "Only true of the Aqua" in c.claim],
       "a cascade undone in bulk resurrects what you meant to remove")

    print("\n— every kind can be removed, not just entities —")
    kb.add_audience("baci", "hosts", "Hosts", "runs out", "plain", origin="human")
    kb.add_situation("baci", "care", patterns=[["wash"]], origin="human")
    aud = kb.audiences("baci")[0]
    ck("an audience", kb.remove("baci", "audience", aud.id)["ok"]
       and not [a for a in kb.audiences("baci") if a.id == aud.id])
    sit = [s for s in kb.situation_rows("baci") if s.tag == "care"][0]
    ck("a situation", kb.remove("baci", "situation", sit.id)["ok"])
    # THE BUG THIS FOUND: `situations()` tested `!= PROPOSED`, so a tag a person
    # had explicitly rejected still passed and went on validating claims.
    ck("…and a removed tag stops being valid vocabulary",
       "care" not in kb.situations("baci"), str(sorted(kb.situations("baci"))))

    print("\n— an unknown kind is refused by name —")
    bad = kb.remove("baci", "spaceship", "x")
    ck("it says what it does not know", not bad["ok"] and "spaceship" in bad["error"])
    ck("…and lists what it does", "entity" in (bad.get("known") or []))
    ck("another account's row cannot be reached",
       not kb.remove("eien", "entity", ent.id)["ok"])

    print("\n— the console offers it, on every list —")
    # A fresh photograph: the cascade above removed the only one, so without
    # this the asset check runs against an empty library and passes or fails
    # for a reason that has nothing to do with the control.
    kb.add_asset("baci", "https://cdn.example/shelf.jpg", rights=kb.OWNED,
                 title="Tablescape", origin="human")
    h = client.get(f"/admin/ui?tab=kb&tenant=baci&key={KEY}").text
    ck("the photograph library actually rendered, so the next check means "
       "something", "Tablescape" in h)
    for kind in ("entity", "claim", "objection", "audience", "situation", "asset"):
        ck(f"a remove control for {kind}", f'value="{kind}"' in h)
    ck("…all posting to one route", "/admin/kb_remove" in h)
    ck("…and it is a POST, because a GET that changes state is fired by "
       "anything that loads a URL",
       'action="/admin/kb_remove"' in h and 'method="post"' in h)

    print("\n— the route works end to end —")
    e2 = [e for e in kb.entities("baci", available_only=False)][0]
    r = client.post("/admin/kb_remove",
                    data={"key": KEY, "tenant": "baci", "kind": "entity",
                          "id": e2.id}, follow_redirects=False)
    ck("it redirects back to Knowledge with what it did",
       r.status_code == 303 and "tab=kb" in str(r.headers.get("location")),
       str(r.headers.get("location"))[:90])
    ck("…and the row is actually gone", e2.key not in keys())

    print("\n" + ("all checks passed" if not _fails
                  else f"{len(_fails)} FAILED: " + "; ".join(_fails)))
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
