"""The 56 unanswered questions get a control, and one filer files everything.

Owner, 2026-09-02, reading the Answer-engines block: *"0 of 56 question(s) in
the map are answered · 0 planned · 56 not yet written… What can I do about
this? Where can I look to see that this is being progressed?"*

NOTHING WAS WRONG WITH THE NUMBERS. 56 questions had been harvested and none
written, so the clicks and CTR beneath them were honestly zero rather than
missing — every figure was a true report of an account where nothing had
shipped. What was wrong is that the section stated a 56-item backlog and
offered nothing that acts on it: a fix instruction where a control belongs.

ONE FILER, NOT A SECOND ROUTE. The Plan-supports control had grown the filing
loop inline; cloning it for questions would put two copies of "how work gets
filed" in the codebase, and the thing they would drift on is the monthly cap —
which has already caused one silent overrun. `planner.file_articles` is that
loop and both controls go through it.

Run: python3 scripts/test_question_backlog.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'qb.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from urllib.parse import unquote_plus  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui, db, keywords, planner, systems, tenants, web  # noqa: E402

KEY = "s3cret"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _live(tenant):
    row = systems.find(tenant, "blog") or systems.create(tenant, "blog")
    with db.SessionLocal() as s:
        r = s.get(db.System, row.id)
        r.status = "live"
        cfg = dict(r.config or {})
        cfg["cadence"] = {"articles_monthly": 3, "horizon_days": 40}
        r.config = cfg
        s.commit()
    return systems.find(tenant, "blog")


def _press(tenant):
    r = TestClient(web.app).post(f"/admin/plan_questions?key={KEY}",
                                 data={"tenant": tenant},
                                 follow_redirects=False)
    return r.status_code, unquote_plus(r.headers.get("location", ""))


def main() -> int:
    db.init_db()
    tenants.seed()
    blog = _live("baci")

    print("— an account with no questions says which empty it is —")
    code, said = _press("baci")
    ck("it refuses by name",
       "no question-shaped keywords" in said, said[-90:])
    ck("  and points at where they come from",
       "Architecture" in said,
       "'none to plan' is true of a finished account and an unharvested one, "
       "and those are opposite situations")

    print()
    print("— with a backlog, the control appears and says how many —")
    for i in range(8):
        keywords.upsert("baci", f"how do i clean thing {i}", status="candidate",
                        priority=100 - i, role="support")
    keywords.upsert("baci", "acrylic jug", status="candidate", priority=99)
    page = " ".join(admin_ui._progress_section(KEY, "baci", 28).split())
    ck("the button is rendered", "/admin/plan_questions" in page)
    ck("  naming the backlog", "Plan 8 questions" in page,
       "eight question-shaped candidates; 'acrylic jug' is not one")
    ck("  and saying the cap will stop it first",
       "monthly cap the weekly run obeys" in page,
       "a button that files 8 into a cap of 3 must say so before it is "
       "pressed, not after")

    print()
    print("— pressing it files under the SAME cap the weekly run obeys —")
    code, said = _press("baci")
    ck("it lands back on Progress", code == 303 and "sub=progress" in said,
       said[:80])
    plans = [p for p in systems.plans("baci", "blog")]
    ck("  it filed something", len(plans) >= 1, str(len(plans)))
    months = {}
    for pl in plans:
        m = str((pl.brief or {}).get("planned_for", ""))[:7]
        months[m] = months.get(m, 0) + 1
    ck("  no month exceeds the cap",
       max(months.values()) <= 3, f"{months} against articles_monthly=3")
    ck("  and it says how many are waiting for a later month",
       "left for a later month" in said, said[-110:])
    ck("  only questions were filed",
       all("how do i clean" in ((p.brief or {}).get("plan") or {})
           .get("keyword", "") for p in plans),
       "'acrylic jug' is a candidate too and is not a question")
    ck("  and each is marked planned, so nothing offers it twice",
       all(k.status == "planned" for k in keywords.targets("baci")
           if k.phrase.startswith("how do i clean")
           and any(k.phrase == ((p.brief or {}).get("plan") or {})
                   .get("keyword") for p in plans)),
       "filing without marking is how the same work gets proposed again")

    print()
    print("— one filer, shared with the supports control —")
    ck("`file_articles` exists and both routes call it",
       hasattr(planner, "file_articles"),
       "a second copy would drift on the monthly cap, which has already "
       "caused one silent overrun")
    _src = __import__("pathlib").Path(web.__file__).read_text()
    ck("  neither route has its own filing loop",
       _src.count("plm.file_articles(") == 2
       and _src.count("nxt = plm.next_article_slot") == 0,
       f'{_src.count("plm.file_articles(")} call(s), '
       f'{_src.count("nxt = plm.next_article_slot")} inline loop(s)')

    print()
    print("— when the backlog is cleared, the control stands down —")
    page2 = " ".join(admin_ui._progress_section(KEY, "baci", 28).split())
    # THE EXACT COUNT. The first version was a three-way disjunction that
    # passed on almost anything — the shape this session keeps finding.
    left = len([r for r in keywords.targets("baci")
                if keywords.is_question(r.phrase) and r.status == "candidate"])
    ck("it offers only what is left",
       f"Plan {left} question" in page2,
       f"{left} still unwritten; the count has to follow the backlog, not "
       f"the original number")
    ck("  and that is fewer than before",
       left < 8, f"{left} of 8 — the rest are planned")

    print()
    print("— and with the backlog cleared it stands down entirely —")
    for r in keywords.targets("baci"):
        if keywords.is_question(r.phrase) and r.status == "candidate":
            keywords.upsert("baci", r.phrase, status="planned")
    page3 = " ".join(admin_ui._progress_section(KEY, "baci", 28).split())
    ck("no button when there is nothing to file",
       "/admin/plan_questions" not in page3,
       "a control that files nothing is a button reporting a failure")
    ck("  and it says the backlog is clear",
       "written or planned" in page3, page3[:0] or "")

    print()
    print("— and it is behind the admin key —")
    before = len(systems.plans("baci", "blog"))
    TestClient(web.app).post("/admin/plan_questions?key=wrong",
                             data={"tenant": "baci"}, follow_redirects=False)
    ck("a wrong key files nothing",
       len(systems.plans("baci", "blog")) == before)

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
