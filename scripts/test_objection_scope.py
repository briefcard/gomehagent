"""An answer about one product must never be claimed of the catalogue.

Reported from the live Knowledge tab: six objections harvested off Baci product
pages, every one rendered "applies to everyone" —

    Is it dishwasher safe?    Yes — dishwasher safe (top rack only).
    How many pieces?          This is sold as a set of 6 pieces.

Baci sells gold-rim porcelain, which is NOT dishwasher safe, and plenty that is
not sold in sixes. Both answers are true of the page they were scraped from and
false of the catalogue they were filed against.

Four failures in one chain, each checked below:

  1. harvest set entity_key="" when it could not resolve a product, and ""
     already meant "true of the whole brand" — unknown collapsed into a value,
     in the one place where being wrong misinforms a customer.
  2. the objection review form offered Approve and Reject and no way to say
     what the answer was about, so a reviewer who SAW the problem could only
     approve it wrong or throw away a real answer.
  3. the Knowledge tab rendered audience_key and never entity_key, so a
     correctly scoped answer still displayed "applies to everyone".
  4. that page called objections() with no entity, which filters to the
     brand-wide subset — so every product-scoped answer was invisible on the
     one page whose job is showing what the account knows.

    python3 scripts/test_objection_scope.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'os.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, kb, provenance as prov, tenants  # noqa: E402
from app.web import app  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _obj(tenant, q):
    with db.SessionLocal() as s:
        return (s.query(db.KbObjection)
                .filter(db.KbObjection.tenant == tenant,
                        db.KbObjection.objection == q).first())


def main() -> int:
    with TestClient(app) as cl:
        tenants.seed()
        cl.get(f"/admin/ui?key={os.environ['APPROVAL_SECRET']}")

        kb.add_entity("baci", "product", "gold-rim-porcelain-cup",
                      "Gold Rim Porcelain Cup", origin="human")
        kb.add_entity("baci", "product", "acrylic-tumbler",
                      "Acrylic Tumbler", origin="human")

        DISH = "Is it dishwasher safe?"
        kb.add_objection("baci", DISH, "Yes — dishwasher safe (top rack only).",
                         origin="crawl", source="/products/acrylic-tumbler")

        print("— an unscoped machine answer cannot go final —")
        row = _obj("baci", DISH)
        ck("it lands proposed, not approved", row.review == prov.PROPOSED,
           str(row.review))
        ck("and its scope is recorded as undecided", kb.scope_unconfirmed(row))
        msg = kb.approve("objection", row.id)
        ck("approving it is REFUSED", msg.startswith("Say what"), msg)
        ck("and the refusal names the real consequence",
           "porcelain" in msg, msg)
        ck("nothing was approved",
           _obj("baci", DISH).review == prov.PROPOSED)

        print("\n— scoping it is what makes it approvable —")
        bad = kb.update_objection(row.id, entity_key="no-such-product")
        ck("a scope that is not in the catalogue is refused",
           "nothing in its catalogue" in bad, bad)
        ck("because selection would never reach it",
           not _obj("baci", DISH).entity_key)

        ck("a real product is accepted",
           kb.update_objection(row.id, entity_key="acrylic-tumbler") == "Saved.")
        ck("and now it approves", kb.approve("objection", row.id)
           .startswith("Approved"))

        print("\n— and it reaches only what it is true of —")
        acrylic = [o.objection for o in
                   kb.objections("baci", entity_key="acrylic-tumbler")]
        porcelain = [o.objection for o in
                     kb.objections("baci", entity_key="gold-rim-porcelain-cup")]
        ck("the tumbler is told it is dishwasher safe", DISH in acrylic)
        ck("THE PORCELAIN IS NOT", DISH not in porcelain,
           "a gold-rim porcelain buyer would be told to put it in the dishwasher")
        ck("and neither is a brand-level draft with no product in mind",
           DISH not in [o.objection for o in kb.objections("baci")])

        print("\n— a deliberate brand-wide answer is still allowed —")
        SHIP = "How long does delivery take?"
        kb.add_objection("baci", SHIP, "Two to five business days.",
                         origin="crawl", source="/pages/shipping")
        r2 = _obj("baci", SHIP)
        ck("it is refused by default too", kb.approve("objection", r2.id)
           .startswith("Say what"))
        ck("but ticking brand-wide approves it",
           kb.approve("objection", r2.id, brand_wide=True).startswith("Approved"))
        ck("and it does reach every product",
           SHIP in [o.objection for o in
                    kb.objections("baci", entity_key="gold-rim-porcelain-cup")])
        ck("a human-authored one was never blocked at all",
           not kb.scope_unconfirmed(
               type("R", (), {"entity_key": "", "origin": "human",
                              "review": prov.APPROVED})()))

        print("\n— the page a person actually reads —")
        page = cl.get("/admin/ui?tab=kb&tenant=baci").text
        ck("a scoped answer says what it is true of",
           "Acrylic Tumbler" in page, "the entity is not rendered")
        ck("it no longer claims to apply to everyone",
           "applies to everyone" not in page)
        ck("a brand-wide one says so plainly",
           "true of everything they sell" in page)
        ck("product-scoped answers are visible at all",
           DISH in page, "objections() filtered them off the page")
        ck("and every row can be re-scoped from here",
           'action="/admin/objection_edit"' in page)

        print("\n— fixing one that is already approved and wrong —")
        WRONG = "How many pieces are included?"
        kb.add_objection("baci", WRONG, "This is sold as a set of 6 pieces.",
                         origin="crawl", source="/products/acrylic-tumbler",
                         review=prov.APPROVED)
        ck("the old code's rows reach every product",
           WRONG in [o.objection for o in
                     kb.objections("baci", entity_key="gold-rim-porcelain-cup")])
        r = cl.post("/admin/objection_edit",
                    data={"row_id": _obj("baci", WRONG).id, "tenant": "baci",
                          "entity_key": "acrylic-tumbler"},
                    follow_redirects=False)
        ck("re-scoping from the console works", r.status_code == 303)
        ck("and it stops reaching the porcelain",
           WRONG not in [o.objection for o in
                         kb.objections("baci", entity_key="gold-rim-porcelain-cup")],
           "the approved-and-wrong rows cannot be fixed")
        ck("while still answering for the item it is true of",
           WRONG in [o.objection for o in
                     kb.objections("baci", entity_key="acrylic-tumbler")])

        print("\n— clearing what a rescrape refills, and only that —")
        kb.add_claim("baci", "Designed in Milan since 1993.", "about page",
                     ["credibility"], origin="crawl", source="/pages/about")
        before_ents = len(kb.entities("baci", available_only=False))
        before_ban = len(kb.banned_claims("baci"))

        rep = kb.purge_harvested("baci")
        ck("a dry run reports and deletes nothing", rep["dry_run"])
        ck("it counts the approved rows, which purge_proposals cannot touch",
           rep["would_delete"]["objection"]["approved"] >= 1,
           str(rep.get("would_delete")))
        ck("and the objections are still there",
           len(kb.objections("baci", any_entity=True)) > 0)

        ck("it refuses to run across every account at once",
           "error" in kb.purge_harvested(""))
        ck("and refuses to delete what a person authored",
           "human origin" in kb.purge_harvested("baci",
                                                origins=("human",)).get("error", ""))

        done = kb.purge_harvested("baci", dry_run=False)
        ck("applying it clears the harvested rows",
           not kb.objections("baci", any_entity=True, include_proposed=True),
           "harvested objections survived")
        ck("including the approved ones", "objection" in done["deleted"])

        # The three the rescrape depends on. Losing the catalogue is the worst
        # of them: harvest scopes a product page by looking its handle up in
        # `owned`, so with entities gone every re-harvested answer returns
        # unscoped and the bug this purge exists to clear comes straight back.
        ck("the catalogue is untouched",
           len(kb.entities("baci", available_only=False)) == before_ents,
           "a rescrape would then scope nothing at all")
        ck("the ban list is untouched",
           len(kb.banned_claims("baci")) == before_ban,
           "a rescrape would reintroduce what the rules exist to keep out")
        ck("the tag vocabulary is untouched", len(kb.situations("baci")) > 0)
        ck("and the report says what it kept and why",
           done["kept"]["entities_kept"]["baci"] == before_ents
           and any("handmade" in n for n in done["kept_note"]))

        print("\n— the wider blast radius, when it is asked for —")
        # Tags are validated per tenant, so borrow one eien actually has —
        # an invalid tag is refused and the row would never exist to purge.
        etag = sorted(kb.situations("eien"))[:1]
        msg = kb.add_claim("eien", "No PFAS.", "label", etag,
                           origin="crawl", source="/pages/about")
        ck("the fixture claim was really written", msg.startswith("Added"), msg)
        rep = kb.purge_harvested("*")
        ck("'*' reaches every account",
           len(rep["accounts"]) > 1, str(rep["accounts"]))
        ck("and names which ones actually have rows to lose",
           "eien" in rep["would_delete"]["claim"]["accounts"],
           str(rep["would_delete"].get("claim")))

        # A synced row, which is what "the catalogue" actually means — the
        # test's other entities are human-authored and must survive.
        kb.add_entity("baci", "product", "synced-plate", "Synced Plate",
                      origin="store_sync")
        rep = kb.purge_harvested("baci", include_entities=True)
        ck("including entities matches the SYNCED catalogue, not just crawl",
           "entity" in rep.get("would_delete", {}),
           "store_sync was not included, so this would delete nothing")
        ck("and the report leads with what that costs",
           "unscoped" in rep["kept_note"][0].lower(), rep["kept_note"][0][:80])
        ck("ordering the catalogue sync BEFORE the harvest",
           "catalog_sync" in rep["next"][0], str(rep["next"][0]))
        ck("a seeded venue is still not a synced catalogue row",
           "seed" not in rep["origins"] and "human" not in rep["origins"])
        ck("it targets the synced row",
           rep["would_delete"]["entity"]["total"] == 1,
           str(rep["would_delete"]["entity"]))
        kb.purge_harvested("baci", include_entities=True, dry_run=False)
        left = {e.key for e in kb.entities("baci", available_only=False)}
        ck("which is gone", "synced-plate" not in left)
        ck("while the hand-authored ones survive",
           {"acrylic-tumbler", "gold-rim-porcelain-cup"} <= left, str(left))

    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED: " + ", ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
