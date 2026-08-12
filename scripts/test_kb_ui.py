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
        s.add(db.KbClaim(tenant="baci", claim="STALE PROOF ROW",
                         evidence="last year", situations=["gift_moment"],
                         status="active",
                         expires_at=db.utcnow() - _dt.timedelta(days=2)))
        s.add(db.KbClaim(tenant="baci", claim="RETIRED PROOF ROW",
                         evidence="withdrawn", situations=["gift_moment"],
                         status="retired"))
        s.add(db.KbClaim(tenant="baci", claim="PENDING PROOF ROW",
                         evidence="submitted", situations=["gift_moment"],
                         status="pending"))
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
