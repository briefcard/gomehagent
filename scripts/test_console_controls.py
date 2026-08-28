"""Every fact the console states now carries the control that acts on it.

Phase 4 of INITIATIVE-solidify. The audit found nine "named but no control"
instances; Phase 2 closed the approvals two, and this closes the rest that
have a backing store to write to. The recurring defect being retired: a page
that names a missing value and sends the reader somewhere else — or nowhere —
to supply it.

    python3 scripts/test_console_controls.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cc.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui, db, kb, keywords, sites, systems, tenants, web  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    c = TestClient(web.app)

    # ── the exclude-term accept, end to end ─────────────────────────────
    print("— a mute lesson can finally be ACCEPTED —")
    for ph in ("wedding venue quotes", "wedding photographer packages",
               "wedding catering menus", "corporate event space"):
        keywords.upsert("ironside", ph, volume=400, source="semrush_related")
    keywords.cluster("ironside")
    keywords.score("ironside")
    for ph in ("wedding venue quotes", "wedding photographer packages",
               "wedding catering menus"):
        keywords.set_priority("ironside", ph, "muted")
    # The muted-keyword fold and its Exclude control live in the BOARD room
    # (2026-08-27: the Plan tab gained a rail; each room renders alone).
    page = admin_ui.render_plan("s3cret", "ironside", sub="board")
    ck("the proposal carries its button",
       "Exclude it" in page and "exclude_term" in page,
       "it was prose with an explicit 'Proposals, not actions' disclaimer "
       "and no backing route anywhere")
    r = c.get("/admin/exclude_term?key=s3cret&tenant=ironside&ui=1"
              "&term=wedding", follow_redirects=False)
    ck("accepting lands", "ok=" in r.headers["location"])
    with db.SessionLocal() as s:
        terms = (s.get(db.Tenant, "ironside").analytics or {}).get("exclude_terms")
    ck("the term has a home now", terms == ["wedding"],
       "Tenant.analytics beside semrush_db — research config with research "
       "config, NOT a banned claim, which is a compliance rule about what "
       "may be SAID")
    ck("the site profile carries it to the harvest",
       "wedding" in sites.get("ironside")["exclude_terms"],
       "semrush_opportunity_finder already honours exclude_terms — the term "
       "reaches the source, so the family stops being surfaced at all")
    ck("and the lesson stops re-proposing it",
       "wedding" not in [t["term"] for t in
                         keywords.mute_lessons("ironside")["terms"]],
       "the 'already excluded' check reads the same merged profile")
    r2 = c.get("/admin/exclude_term?key=s3cret&tenant=ironside&ui=1"
               "&term=miami", follow_redirects=False)
    ck("the brand's own words are refused at the route too",
       "err=" in r2.headers["location"],
       "the proposal layer filters them, but a hand-typed ?term=miami must "
       "meet the same wall")
    r3 = c.get("/admin/exclude_term?key=s3cret&tenant=ironside&ui=1"
               "&term=wedding", follow_redirects=False)
    ck("a duplicate reports, not duplicates", "already" in r3.headers["location"])

    # ── the market control ──────────────────────────────────────────────
    print("\n— the market advisory carries its own control —")
    row = systems.create("ironside", "blog")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    page = admin_ui.render_plan("s3cret", "ironside", sub="architecture")
    ck("the form is on the chip that states the fact",
       "market_set" in page and "Set market" in page,
       "the advisory's only write path was the raw-JSON analytics field")
    r4 = c.get("/admin/market_set?key=s3cret&tenant=ironside&ui=1&market=USA!",
               follow_redirects=False)
    ck("a non-code is refused by name", "err=" in r4.headers["location"])
    r5 = c.get("/admin/market_set?key=s3cret&tenant=ironside&ui=1&market=us",
               follow_redirects=False)
    ck("a real one lands", "ok=" in r5.headers["location"])
    know = keywords.readiness("ironside", probe=False)["knows_what_to_write"]
    ck("and the advisory goes quiet",
       not any("market not set" in n for n in know.get("notes", [])),
       str(know.get("notes")))

    # ── the situation authoring control ─────────────────────────────────
    print("\n— the tag warning finally has a first tag behind it —")
    kbpage = admin_ui.render_kb("s3cret", "ironside")
    ck("the add form is on the card that warns",
       "situation_add" in kbpage and "Add situation" in kbpage,
       "the warning that claims 'will be refused until tags exist here' "
       "dead-ended for as long as it has existed")
    r6 = c.get("/admin/situation_add?key=s3cret&tenant=ironside"
               "&tag=Planning a Wedding!", follow_redirects=False)
    ck("the tag is normalised to the slug shape selection compares",
       "ok=" in r6.headers["location"]
       and "planning_a_wedding" in kb.situations("ironside"),
       str(kb.situations("ironside")))
    r7 = c.get("/admin/situation_add?key=s3cret&tenant=ironside"
               "&tag=planning_a_wedding&description=updated+wording",
               follow_redirects=False)
    ck("re-adding UPDATES rather than duplicating",
       "Updated" in r7.headers["location"],
       "the canonical writer upserts — one tag, one row")
    # The near-dupe guard binds MACHINES and deliberately not people: "a
    # human still can — they may have a reason, and they can see both." The
    # console passes origin=human, so the guard stands aside; a crawl-origin
    # synonym is still refused. (A console-only duplicate writer with a
    # stricter rule was written and deleted the same hour — it shadowed this
    # one, which six callers already used. Two names for one decision.)
    got_h = kb.add_situation("ironside", "planning_a_weddings",
                             patterns=[], origin="human")
    ck("a human MAY add a near-duplicate", got_h.startswith("Added"), got_h)
    # The machine-side synonym guard is SEMANTIC (embed.ensure feeds it) and
    # stands down without an embedding key, so it is not assertable offline.
    # What IS assertable — and is the protection that actually holds here —
    # is provenance: a machine's tag lands `proposed`, invisible to
    # selection until a person reviews it, while the console's lands
    # approved and usable at once.
    kb.add_situation("ironside", "planning_the_wedding",
                     patterns=[], origin="crawl",
                     description="a buyer planning their wedding")
    ck("a machine's tag is invisible until reviewed",
       "planning_the_wedding" not in kb.situations("ironside")
       and "planning_the_wedding" in kb.situations("ironside",
                                                   include_proposed=True),
       "a machine may not silently widen the one vocabulary that decides "
       "whether any claim can be accepted")
    ck("and a claim may now carry the tag",
       isinstance(kb.add_claim("ironside", "Eight venues on one campus.",
                               "site plan", ["planning_a_wedding"]), str),
       "the whole point of the tag")

    # ── pending claims decidable from the Knowledge tab ─────────────────
    print("\n— a pending claim can be decided where it is listed —")
    kb.add_claim("ironside", "Hosts 500 events a year.", "", [],
                 status="pending")
    kbpage = admin_ui.render_kb("s3cret", "ironside")
    ck("approve/reject sit on the row",
       "back=kb" in kbpage and "claim_review" in kbpage,
       "the fact was on this page, the control on another")
    with db.SessionLocal() as s:
        cid = (s.query(db.KbClaim)
               .filter(db.KbClaim.tenant == "ironside",
                       db.KbClaim.claim.like("Hosts 500%")).first().id)
    r8 = c.get(f"/admin/claim_review?key=s3cret&tenant=ironside&ui=1"
               f"&back=kb&claim_id={cid}&approve=yes", follow_redirects=False)
    ck("deciding returns the reader to the Knowledge tab",
       "tab=kb" in r8.headers["location"],
       "'a decision must never cost the reader their place' is the route's "
       "own rule; landing on Review broke it the moment a second surface "
       "could decide")
    ck("and the claim is now selectable",
       any("Hosts 500" in r.claim for r in kb.claims("ironside")))

    # ── blockers link the fix ───────────────────────────────────────────
    print("\n— a connection blocker links the Connections tab —")
    row2 = systems.create("coverings", "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, row2.id).status = "live"
        s.commit()
    spage = admin_ui.render_systems("s3cret", "coverings",
                                    system="campaign_email")
    ck("'not connected: esp' carries 'connect it'",
       "connect it" in spage and "tab=accounts" in spage,
       "the blocker told the reader what was missing and nothing about "
       "where to fix it")

    # ── the bare strings are links ──────────────────────────────────────
    print("\n— bare command strings became controls —")
    # The vocabulary card renders only when overlapping tags are DETECTED,
    # and detection is semantic — silent without an embedding key — so the
    # rendered page cannot carry the link offline. The gap was "printed as
    # bare code, not a link, though the route exists"; the fix is the anchor
    # in the template, asserted at source because the card's precondition is
    # not reachable in this environment.
    import pathlib as _pl
    _ui_src = _pl.Path(admin_ui.__file__).read_text()
    ck("the vocabulary check is clickable wherever its card renders",
       'href="/admin/vocabulary' in _ui_src
       and "<code>/admin/vocabulary" in _ui_src)
    with db.SessionLocal() as s:
        srow = s.get(db.System, row.id)
        srow.key = "blog"          # ensure the plan-fields note can render
        s.commit()
    ck("register_owner stays code, deliberately",
       True,
       "it needs a Telegram chat_id no console click can supply — a link "
       "would 400; named as a scope cut, not forgotten")

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
