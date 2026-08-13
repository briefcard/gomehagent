"""Everything in the knowledge base has to be visible in the Knowledge tab.

The console used to render four of the twelve things the KB stores. A field you
cannot read is a field nobody maintains, and two of the defects in DEFECTS.md
(§2.8 the migration that silently emptied `next_steps`, §2.1 the seed that
dropped claims tagged outside a vocabulary nobody could see) were invisible for
exactly that reason.

So this asserts against the rendered HTML, per tenant, using the real seed data:
if a fact is in the KB and not on the page, this fails.

    python3 scripts/test_kb_ui.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'kbui.db')}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import admin_ui, db, kb, kb_seed, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def has(page: str, needle: str) -> bool:
    """Present in the rendered output, HTML-escaping accounted for."""
    import html
    return needle in page or html.escape(needle, quote=True) in page


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.seed_agency()
    kb_seed.seed_all()

    KEY = "testkey"

    # ---- 1. every seeded row type reaches the page, per tenant -------------
    for t in ("agency", "baci", "ironside", "eien", "coverings"):
        page = admin_ui.render_kb(KEY, t)
        b = kb.brand(t)

        for r in kb.claims(t):
            ck(f"{t}: claim on page", has(page, r.claim), r.claim[:45])
            if r.evidence:
                ck(f"{t}: its evidence too", has(page, r.evidence), r.evidence[:45])
        for r in kb.audiences(t):
            ck(f"{t}: audience {r.key}", has(page, r.name))
            if r.buying_trigger:
                ck(f"{t}: {r.key} buying trigger", has(page, r.buying_trigger),
                   r.buying_trigger[:40])
            if r.decision_timeline:
                ck(f"{t}: {r.key} timeline", has(page, r.decision_timeline))
        for r in kb.objections(t):
            ck(f"{t}: objection", has(page, r.objection), r.objection[:40])
            ck(f"{t}: its approved answer", has(page, r.response), r.response[:40])
        for r in kb.entities(t, available_only=False):
            ck(f"{t}: entity {r.key}", has(page, r.name))
            for k, v in (r.attributes or {}).items():
                ck(f"{t}: {r.key}.{k} value shown", has(page, str(v)), f"{k}={v}")
        for r in kb.situation_rows(t):
            ck(f"{t}: situation {r.tag}", has(page, r.tag))
            if r.description:
                ck(f"{t}: {r.tag} described", has(page, r.description),
                   r.description[:40])
        for p in (b.banned_claims or []) if b else []:
            ck(f"{t}: hard rule shown", has(page, p), p[:40])
        for stage, v in ((b.next_steps or {}) if b else {}).items():
            ck(f"{t}: next step '{stage}'", has(page, (v or {}).get("ask", "")),
               stage)
        if b and (b.selection or {}).get("primary_type"):
            ck(f"{t}: selection primary_type",
               has(page, b.selection["primary_type"]))
        for tone in ((b.voice or {}).get("tone") or []) if b else []:
            ck(f"{t}: voice tone", has(page, tone))

    # ---- 2. non-selectable proof is shown as such, not hidden --------------
    import datetime as _dt
    with db.SessionLocal() as s:
        # `status` is the lifecycle axis and `review` is the approval axis;
        # they used to be one column, which is why a pending claim also had to
        # be lifecycle-nonactive to stay out of selection.
        s.add(db.KbClaim(tenant="baci", claim="STALE PROOF ROW",
                         evidence="last year", situations=["gift_moment"],
                         status="active", review="approved",
                         expires_at=db.utcnow() - _dt.timedelta(days=2)))
        s.add(db.KbClaim(tenant="baci", claim="RETIRED PROOF ROW",
                         evidence="withdrawn", situations=["gift_moment"],
                         status="retired", review="rejected"))
        s.add(db.KbClaim(tenant="baci", claim="PENDING PROOF ROW",
                         evidence="submitted", situations=["gift_moment"],
                         status="active", review="proposed"))
        s.commit()

    inv = kb.claim_inventory("baci")
    ck("inventory splits expired", [r for r in inv["expired"]
                                    if r.claim == "STALE PROOF ROW"] != [])
    ck("inventory splits retired", [r for r in inv["retired"]
                                    if r.claim == "RETIRED PROOF ROW"] != [])
    ck("inventory splits pending", [r for r in inv["pending"]
                                    if r.claim == "PENDING PROOF ROW"] != [])
    ck("selection still excludes all three",
       not [r for r in kb.claims("baci")
            if r.claim.endswith("PROOF ROW")])

    page = admin_ui.render_kb(KEY, "baci")
    for row in ("STALE PROOF ROW", "RETIRED PROOF ROW", "PENDING PROOF ROW"):
        ck(f"{row} visible on the page", has(page, row))
    ck("expired proof is labelled, not just listed",
       "past its expiry date" in page)
    ck("pending proof says it is not selectable",
       "not selectable until approved" in page)

    # ---- 3. an unavailable item cannot look sellable -----------------------
    with db.SessionLocal() as s:
        e = s.query(db.KbEntity).filter(db.KbEntity.tenant == "baci").first()
        e.availability, ekey = "oos", e.name
        s.commit()
    page = admin_ui.render_kb(KEY, "baci")
    ck("out-of-stock item is flagged on the page",
       has(page, ekey) and "oos" in page, ekey)

    # ---- 4. the gap queue surfaces in the console --------------------------
    kb.record_unknowns("ironside", [
        {"key": "glassbox", "name": "Glassbox", "fits": None,
         "basis": "unknown", "attribute": "seated_capacity"}],
        asked_for="220 seated in March")
    page = admin_ui.render_kb(KEY, "ironside")
    open_gaps = kb.unknowns("ironside")
    if open_gaps:
        ck("open gap named on the page", has(page, "Glassbox"))
        ck("gap says what was asked for", has(page, "220 seated in March"))
    else:
        ck("record_unknowns logged the gap", False, "nothing logged")

    # ---- 5. an empty account still renders and says what is missing --------
    with db.SessionLocal() as s:
        s.add(db.Tenant(key="blank", name="Blank Co"))
        s.commit()
    kb.ensure_brand("blank", "Blank Co")
    page = admin_ui.render_kb(KEY, "blank")
    ck("empty account renders", "Knowledge" in page and len(page) > 500)
    ck("empty account warns about inherited vocabulary",
       "silently inherits" in page)

    # ---- 6. the Content tab surfaces what the JSON routes produce --------
    # These three were built as JSON routes and nothing else, which is §2.13
    # again: a compliance report that lives only in the response that triggered
    # it has to be re-run to be read twice.
    print("\n— the Content tab —")
    from app import compliance, systems
    systems.seed_from_tenants()
    systems.create("baci", "content_compliance")
    compliance.record_scan("baci", {
        "pages_checked": 12,
        "violations": [{"url": "https://bacimilanousa.com/pages/about",
                        "lastmod": "", "hits": [
                            {"phrase": "handmade",
                             "context": "Every piece is handmade in Italy."}]}],
        "by_phrase": [("handmade", 1)]})
    kb.add_claim("baci", "PROPOSED CLAIM AWAITING REVIEW", "some evidence",
                 ["gifting"], proof_type="testimonial",
                 source="review on /products/x", status="pending")

    page = admin_ui.render_content(KEY, "baci")
    ck("the Content tab renders", "Content" in page and len(page) > 800)
    ck("a pending proposal is shown", has(page, "PROPOSED CLAIM AWAITING REVIEW"))
    ck("with its provenance", has(page, "review on /products/x"))
    ck("and can be edited, tagged and approved without leaving the page",
       all(x in page for x in ("/admin/claim_edit", 'name="claim"',
                               'name="evidence"', 'name="tags"',
                               "Save &amp; approve", "Reject")))
    ck("the tag options are the account's own vocabulary",
       all(f'value="{t}"' in page for t in list(kb.situations("baci"))[:3]))
    ck("the compliance finding names the live URL",
       has(page, "https://bacimilanousa.com/pages/about"))
    ck("and quotes the sentence, so it is fixable without opening the page",
       has(page, "Every piece is handmade in Italy."))
    ck("the phrase is ranked", has(page, "handmade"))
    ck("each action can be run from the tab",
       all(r in page for r in ("/admin/harvest", "/admin/compliance_scan",
                               "/admin/catalog_sync")))
    ck("an account never scanned says so rather than looking clean",
       "Never scanned" in admin_ui.render_content(KEY, "coverings"))

    # ---- 4. the work the provenance spine creates is visible --------------
    # A conflict nobody can see is worse than the silent overwrite it replaced:
    # the data is correct and the work is invisible. Same for a proposal in one
    # of the four tables that never had a review queue.
    from app import provenance as prov
    kb.add_entity("baci", "product", "aqua", "Aqua Set",
                  description="Store copy.", origin="store_sync")
    kb.add_entity("baci", "product", "aqua", "Aqua Set",
                  description="Gomeh's own wording for this set.", origin="human")
    kb.add_entity("baci", "product", "aqua", "Aqua Set",
                  description="Handmade in Italy, artisanal.",
                  origin="store_sync",
                  source="https://bacimilanousa.com/products/aqua")
    kb.add_objection("baci", "Is it dishwasher safe?", "Yes, every piece.",
                     origin="client", source="submitted by Dana")
    page = admin_ui.render_content(KEY, "baci")

    ck("a disagreement between sources reaches the page",
       "Sources disagree" in page and len(prov.conflicts("baci")) == 1)
    ck("it shows the value in use", has(page, "Gomeh's own wording for this set."))
    ck("and the value that was refused", has(page, "Handmade in Italy, artisanal."))
    ck("attributed to the source that disagreed", has(page, "store_sync"))
    ck("with both resolutions offered, without leaving the page",
       all(x in page for x in ("/admin/conflict_resolve", 'value="approved"',
                               'value="incoming"')))
    ck("a proposal from a table that never had a review queue is shown",
       "Everything else awaiting you" in page
       and has(page, "Is it dishwasher safe?"))
    ck("attributed to whoever submitted it", has(page, "submitted by Dana"))
    ck("and approvable from the tab",
       "/admin/proposal_review" in page
       and 'name="action" value="approve"' in page)
    ck("nothing proposed is usable in the meantime",
       not [o for o in kb.objections("baci")
            if o.objection == "Is it dishwasher safe?"])

    # ---- 5. an entity-scoped claim says so, on the page ------------------
    # A claim harvested from a product page is attached to that product, and
    # `entity_key` was set correctly from the first run — but the card rendered
    # only `proof_type · source`, so a reviewer approving "Generous 32 cm
    # footprint…" had no way to see what it was true OF. That is the same class
    # of defect as 2.13: a field the pipeline uses and the maintainer cannot see.
    kb.add_entity("baci", "product", "cake-stand-cover",
                  "Clear Cake Stand with Cover", origin="store_sync")
    kb.add_claim("baci", "Generous 32 cm footprint: ample room for a layer cake.",
                 "", [], proof_type="data", status="pending", origin="crawl",
                 source="stated on https://bacimilanousa.com/products/cake-stand-cover",
                 entity_key="cake-stand-cover")
    page = admin_ui.render_content(KEY, "baci")
    ck("the card names what the claim is true of",
       has(page, "Clear Cake Stand with Cover"))
    ck("and says what that restricts it to",
       "only ever appear in content about that" in page)
    ck("the scope is editable against the account's own catalogue",
       'name="entity_key"' in page and 'list="ents"' in page)
    scoped = [c for c in kb.pending_claims("baci")
              if c.entity_key == "cake-stand-cover"]
    ck("a product-page claim is attached at capture, not left brand-level",
       len(scoped) == 1)
    ck("a scope that is not in the catalogue is refused by name",
       "catalogue" in kb.update_claim(scoped[0].id, entity_key="no-such-key"))

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
