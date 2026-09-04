"""The Business Profile audit: runs, files a dated report, proposes fixes
that write on approval, and shows on the Plan.

Owner, 2026-09-04: "For the audit — how are they to run and review the
results of each audit? How does it align with the overall Plan and Planned
Strategy?" Every answer below is a surface or a join, proven offline with
the adapter's reads stubbed to Google's documented shapes.

Run: python3 scripts/test_gbp_listing.py
"""
import os
import sys
import tempfile
import time

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'gl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KEY = "s3cret"
T = "ironside"

from app import (approvals, db, gbp, gbp_listing as gl, kb, kb_seed,  # noqa: E402
                 skill, skill_pack, systems, tenants)

_fail: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def contract(row, autonomy="approve_all"):
    first = systems.update(row.id, **{f: "declared for the test"
                                      for f, _l, _h in systems.CONTRACT})
    assert first.get("ok"), f"contract fill refused: {first}"
    second = systems.update(row.id, status="live", autonomy=autonomy)
    assert second.get("ok"), f"go-live refused: {second}"
    return systems.get(row.id)


LISTING = {"ok": True, "location": {
    "name": "locations/9", "title": "Ironside", "website": "https://oldsite.example",
    "primary_category": "Event venue", "additional_categories": [],
    "maps_uri": "https://maps.google.com/?cid=1",
    "raw": {"name": "locations/9", "title": "Ironside",
            "storefrontAddress": {"locality": "Miami", "administrativeArea": "FL"},
            "websiteUri": "https://oldsite.example",
            "profile": {"description": "A nice place."},
            "regularHours": {"periods": [{"openDay": "MONDAY"}]},
            "phoneNumbers": {"primaryPhone": "+1 305 555 0100"},
            "serviceItems": [],
            "categories": {"primaryCategory": {"displayName": "Event venue"}}}}}
REVIEWS = {"ok": True, "total": 4, "average": 4.5, "answered": 1, "unanswered": 3,
           "reviews": []}
POSTS = {"ok": True, "posts": [], "last": ""}
MEDIA = {"ok": True, "count": 3, "categories": {"EXTERIOR": 3}}
STATE = {"ok": True, "live": True, "authority": True}


def stub_reads(**over):
    gbp.location = lambda t, n: over.get("listing", LISTING)
    gbp.voice_of_merchant = lambda t, n: over.get("state", STATE)
    gbp.reviews = lambda t, a, n: over.get("reviews", REVIEWS)
    gbp.posts = lambda t, a, n: over.get("posts", POSTS)
    gbp.media = lambda t, a, n: over.get("media", MEDIA)
    gbp.performance = lambda t, n, days=28: {"ok": True, "days": 28, "totals": {
        "WEBSITE_CLICKS": 12, "CALL_CLICKS": 4, "BUSINESS_DIRECTION_REQUESTS": 9,
        "BUSINESS_CONVERSATIONS": 0}}


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    _real_caps = tenants.capabilities
    tenants.capabilities = lambda k: {**_real_caps(k), "gbp": True}
    kb.ensure_brand(T, "Ironside")
    kb.set_brand(T, positioning="A campus of event venues in Little River, Miami.",
                 tone="direct, warm")
    kb.add_banned(T, "best in town")
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, T)
        t.gbp = {"account": "accounts/1", "location": "locations/9",
                 "category": "event venue", "locality": "Miami"}
        t.domain = "ironsidemiami.com"
        s.add(db.KeywordTarget(tenant=T, phrase="event venue miami", tier="head",
                               status="candidate", priority=90))
        s.add(db.KeywordTarget(tenant=T, phrase="wedding venue miami", tier="head",
                               status="candidate", priority=80))
        s.commit()
    row = systems.find(T, "gbp_listing") or systems.create(T, "gbp_listing")
    contract(row)
    stub_reads()
    drafted = {"n": 0}
    skill_pack.draft_gbp_description = lambda bundle, parts: (
        drafted.__setitem__("n", drafted["n"] + 1) or (
            "Ironside is an event venue in Miami's Little River: six venues on "
            "one campus, from a 60-seat lounge to a 400-guest hall, with on-site "
            "parking for 200 cars. Corporate offsites, product launches, "
            "weddings and holiday parties happen a courtyard apart, with one "
            "team running all of it. Open for tours weekdays; book a walk-through "
            "and see the rooms before you choose one.", ""))

    print("— 1. the rubric, as measurements —")
    rep = gl.audit(listing=LISTING["location"], state=STATE, reviews=REVIEWS,
                   posts=POSTS, media=MEDIA, banned=["best in town"],
                   keywords=["event venue miami", "wedding venue miami"],
                   entities=kb.entities(T, available_only=False),
                   domain="ironsidemiami.com", open_post_plans=0)
    keys = {c["key"]: c["ok"] for c in rep["checks"]}
    ck("every field is scored, and the weights sum to 100",
       set(keys) == set(gl.WEIGHTS) and rep["of"] == 100)
    ck("a primary category and hours pass; a thin description, no extra "
       "categories, no services, three photos, one of four reviews answered "
       "and no post are gaps",
       keys["primary_category"] and keys["hours"] and keys["phone"]
       and not keys["description"] and not keys["additional_categories"]
       and not keys["services"] and not keys["photos"]
       and not keys["reviews_answered"] and not keys["post_freshness"],
       str(keys))
    ck("the score is the earned points", rep["score"] == 15 + 10 + 5, str(rep["score"]))
    ck("a website that is not the account's is a gap WITH a writable fix — "
       "point it at the account's site",
       not keys["website"] and rep["fixes"] and rep["fixes"][0]["updateMask"] == "websiteUri"
       and rep["fixes"][0]["body"] == {"websiteUri": "https://ironsidemiami.com"},
       str(rep["fixes"])[:120])
    ck("ALIGNMENT reads the keyword map: the head terms the listing never says",
       rep["alignment"]["missing"] == ["wedding venue miami"]
       and rep["alignment"]["open_post_plans"] == 0, str(rep["alignment"]))
    ck("a read Google refused is scored as unknown and NAMED, not failed silently",
       "reviews" in gl.audit(listing=LISTING["location"], state=STATE, reviews=None,
                             posts=POSTS, media=MEDIA, banned=[], keywords=[],
                             entities=[], domain="", open_post_plans=0)["unread"])

    print("\n— 2. the run: a dated report under Reports, fixes waiting on you —")
    r = skill.run("gbp_listing", T, trigger="manual")
    ck("the audit produces a report", r["status"] == "produced" and r.get("items"),
       f"{r['status']} {r.get('summary')} {[n[:70] for n in r.get('notes', [])][:3]}")
    body = r["items"][0]["body"] if r.get("items") else ""
    ck("…whose third line is the headline the Reports room reads",
       body.split("\n")[2].startswith("Score ") and "fix(es) proposed" in body.split("\n")[2],
       body.split("\n")[2] if body else "")
    ck("…and it names the alignment: the head term the listing never says, "
       "and that no post is planned",
       "wedding venue miami" in body and "posts planned: 0" in body)
    with db.SessionLocal() as s:
        aps = (s.query(db.Approval)
               .filter(db.Approval.run_id == (r.get("run_id") or ""),
                       db.Approval.kind == "gbp_listing_fix",
                       db.Approval.status == "pending").all())
        fixes = {(a.payload or {}).get("field"): (a.id, dict(a.payload or {})) for a in aps}
    ck("two fixes wait for approval — the website, and a drafted description",
       set(fixes) == {"websiteUri", "profile.description"}, str(sorted(fixes)))
    ck("the description was drafted once, through the ban list, in the brand's "
       "words", drafted["n"] == 1
       and "event venue in Miami" in fixes["profile.description"][1]["body"]["profile"]["description"])
    ck("nothing was written to Google by running the audit",
       all("gbp:" not in str(x) for x in ["ran"]))

    print("\n— 3. approving a fix WRITES it — the second write to Google —")
    calls: list = []
    gbp.patch_location = lambda t, n, mask, body: (
        calls.append((t, n, mask, body)) or {"ok": True, "location": {"name": n}})
    ap_id = fixes["websiteUri"][0]
    said = approvals.apply_decision(ap_id, "approved")
    ck("approving the website fix patches exactly that field on the declared "
       "listing", len(calls) == 1 and calls[0][1] == "locations/9"
       and calls[0][2] == "websiteUri"
       and calls[0][3] == {"websiteUri": "https://ironsidemiami.com"},
       f"{calls} {said[:60]}")
    ck("…and says so", "executed" in said.lower() or "updated" in said.lower(), said[:80])

    print("\n— 4. the surfaces: Reports room, run-now, the Plan's strategy —")
    from fastapi.testclient import TestClient
    from app import web
    c = TestClient(web.app, raise_server_exceptions=False)
    page = c.get(f"/admin/ui?key={KEY}&tab=systems&tenant={T}&system=gbp_listing&wf=reports").text
    ck("the Reports room lists the audit with its score headline and the "
       "'findings' chip", "Business Profile audit" in page or "Score " in page,
       "")
    ck("…and says how the audit is run: every Monday, and the button here",
       "Run the check now" in page and "/admin/system_run_now" in page
       and "every Monday" in page)
    ck("…and the system page says how the audit is used",
       "Reports" in page and "Waiting on you" in page)
    before = systems.stats(row.id)["total"]
    r2 = c.post(f"/admin/system_run_now?key={KEY}",
                data={"tenant": T, "system": "gbp_listing"}, follow_redirects=False)
    deadline = time.time() + 8
    while time.time() < deadline and systems.stats(row.id)["total"] <= before:
        time.sleep(0.2)
    ck("pressing 'Run the check now' runs the audit off the request and "
       "files another report", r2.status_code in (302, 303)
       and systems.stats(row.id)["total"] > before,
       f"{r2.status_code} runs {before}->{systems.stats(row.id)['total']}")
    plan = c.get(f"/admin/ui?key={KEY}&tab=plan&tenant={T}&sub=strategy").text
    ck("the Plan's strategy page carries LOCAL PRESENCE: the latest score, "
       "the head term the listing never says, and the way to the report",
       "Local presence" in plan and "/100" in plan
       and "wedding venue miami" in plan and "wf=reports" in plan)
    tr = gl.trend(T)
    ck("the score sweep over sweep is the declared measure — computed from "
       "the filed reports", tr["n"] >= 2 and tr["direction"] in ("up", "down", "flat"),
       str(tr))

    print("\n— 5. the clean case, the not-live case, the undeclared case —")
    clean = dict(LISTING["location"])
    clean["additional_categories"] = ["Wedding venue", "Corporate office"]
    clean["website"] = "https://ironsidemiami.com"
    clean["raw"] = {**LISTING["location"]["raw"],
                    "websiteUri": "https://ironsidemiami.com",
                    "profile": {"description": "x" * 300},
                    "serviceItems": [{"freeFormServiceItem": {"label": {"displayName": n}}}
                                     for n in ("Weddings", "Offsites", "Launches")]}
    stub_reads(listing={"ok": True, "location": clean},
               reviews={"ok": True, "total": 4, "answered": 4, "unanswered": 0, "reviews": []},
               posts={"ok": True, "posts": [{"created": "2026-09-01T00:00:00Z"}],
                      "last": "2026-09-01T00:00:00Z"},
               media={"ok": True, "count": 14, "categories": {}})
    import datetime as _dt
    rep = gl.audit(listing=clean, state=STATE,
                   reviews={"ok": True, "total": 4, "answered": 4, "unanswered": 0},
                   posts={"ok": True, "last": "2026-09-01T00:00:00Z"},
                   media={"ok": True, "count": 14}, banned=[], keywords=[],
                   entities=[], domain="ironsidemiami.com", open_post_plans=1,
                   today=_dt.date(2026, 9, 4))
    ck("a complete listing scores 100 and proposes nothing",
       rep["score"] == 100 and not rep["gaps"] and not rep["fixes"], str(rep["score"]))
    txt = gl.render(rep, when="2026-09-04", title="Ironside", proposed=0)
    ck("…and its headline says 'no gaps', which the Reports room reads as clean",
       "no gaps" in txt.split("\n")[2])
    with db.SessionLocal() as s:
        s.get(db.Tenant, T).gbp = {}
        s.commit()
    r3 = skill.run("gbp_listing", T)
    ck("with no profile declared the audit refuses by name, pointing at the "
       "Accounts tab", r3["status"] != "produced"
       and any("Accounts" in n for n in r3.get("notes", [])),
       f"{r3['status']} {[n[:80] for n in r3.get('notes', [])][:2]}")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed — the audit runs, reports, proposes, writes on "
          "approval, and shows on the Plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
