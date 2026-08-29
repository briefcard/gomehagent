"""Did it work — asked of the data layer, and the same answer everywhere.

Owner, 2026-08-29: "Make sure we leverage this data correctly when evaluating
the success on the plan tab and in the reports system that we will be making."

THE POINT IS THE DIMENSION, NOT THE METRIC. "Clicks were up" is a fact about a
month and tells nobody what to do next. "The positioning that set the testing
claim against the food-safety objection beat the design-led one, to the same
audience" is a fact about the KNOWLEDGE BASE, and it says what to author next.

Three properties are asserted here, and each has cost this codebase something
before:

  * AN UNMEASURED ROW IS NOT A ZERO. An ad nobody has run did not perform
    badly. Averaging the two makes a new idea look like a failed one, which is
    backwards for the thing this exists to encourage.
  * ONE WRITER, TWO READERS. The Plan tab and the report call the same
    function, so they cannot drift into disagreeing about one number.
  * THE JOIN COSTS NOTHING AND WRITES NOTHING. An ad is found by its own copy
    rather than created, so no budget moves and no permission beyond read is
    needed.

    python3 scripts/test_results.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'res.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb_seed, meta_ads, results, tenants  # noqa: E402

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _ad(pos, aud, stage, *, body="", imps=0, clicks=0, gp=-1, claims=()):
    with db.SessionLocal() as s:
        row = db.Output(
            tenant="baci", system_key="ad_creative", format="ad_copy",
            positioning=pos, audience_key=aud, funnel_stage=stage,
            grounded_pct=gp, claim_ids=list(claims), angle="objection",
            body=body,
            outcome=({"impressions": imps, "clicks": clicks, "spend": 12.5}
                     if imps else None))
        s.add(row)
        s.commit()
        return row.id


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    print("— nothing to show is said once, not shown as empty tables —")
    empty = results.by("baci", "positioning")
    ck("an account with no results says so",
       empty["groups"] == [] and "nothing to compare yet" in empty["note"])
    from app import admin_ui as ui
    ck("…and the card states it rather than rendering blanks",
       "no results to group" in ui._working_card("baci")
       and "<table" not in ui._working_card("baci"),
       "a scoreboard of empty tables trains people to stop looking")

    _ad("Food-safe beats price", "hosts", "consideration",
        imps=1000, clicks=40, gp=100, claims=["C1"])
    _ad("Food-safe beats price", "hosts", "consideration",
        imps=1000, clicks=30, gp=100, claims=["C1", "C2"])
    _ad("Design-led", "hosts", "awareness", imps=1000, clicks=10, gp=0)
    _ad("Untried idea", "gifters", "interest")

    print("\n— grouped by the things the knowledge base is made of —")
    got = results.by("baci", "positioning")
    top = got["groups"][0]
    ck("the measured winner leads", top["key"] == "Food-safe beats price")
    ck("…with the rate, not the raw clicks", top["ctr_pct"] == 3.5,
       str(top["ctr_pct"]))
    ck("…and how grounded that work was",
       top["grounded_pct"] == 100,
       "'the ads that stood on a claim did better' is the most useful thing "
       "this can say about whether filling the KB is worth it")
    ck("an unmeasured idea sorts last, never as a zero",
       got["groups"][-1]["key"] == "Untried idea"
       and got["groups"][-1]["ctr_pct"] is None
       # The GROUP's own count, not the total: sabotage showed that
       # asserting only the top-level tally stayed green while every
       # unmeasured row was being counted as a measurement of zero.
       and got["groups"][-1]["measured"] == 0
       and got["groups"][-1]["variants"] == 1,
       f"an ad nobody ran did not perform badly — it has not performed "
       f"({got['groups'][-1]})")
    ck("…and is counted, not hidden",
       got["unmeasured"] == 1 and got["measured"] == 3)

    print("\n— every axis the owner named, and one call for all of them —")
    board = results.scoreboard("baci")
    ck("all six dimensions are computed",
       set(board) == set(results.DIMENSIONS), str(sorted(board)))
    ck("audience groups", {g["key"] for g in board["audience"]["groups"]}
       == {"hosts", "gifters"})
    ck("funnel stage groups",
       {g["key"] for g in board["funnel_stage"]["groups"]}
       == {"consideration", "awareness", "interest"},
       "without this nobody can ask whether the consideration work pays")
    ck("a claim cited by two ads is credited to both",
       next(g["variants"] for g in board["claim"]["groups"]
            if g["key"] == "C1") == 2,
       "forcing a multi-claim ad into one group loses half the signal")
    ck("an unsupported dimension refuses by name",
       "cannot group results by" in results.by("baci", "colour")["error"])

    print("\n— the headline, or an honest silence —")
    ck("it names the winner against the runner-up",
       "Food-safe beats price" in results.headline("baci")
       and "Design-led" in results.headline("baci"))
    ck("…and says nothing when there is nothing to say",
       results.headline("ironside") == "",
       "a report that manufactures a sentence every week teaches people to "
       "skip the first paragraph")

    print("\n— one writer, so the tab and the report cannot disagree —")
    card = ui._working_card("baci")
    ck("the card renders the same winner",
       "Food-safe beats price" in card and "3.5" in card)
    ck("…leads with the three axes an ad IS",
       all(f"By {d}".replace("_", " ") in card.replace("_", " ")
           for d in ("positioning", "audience", "funnel stage")),
       "audience, part of the funnel, positioning")
    ck("…and the tab computes nothing of its own",
       "results.by" not in card and "_res.scoreboard" not in card)

    print("\n— the join is found, never created —")
    ck("copy is matched on a comparable form",
       meta_ads.comparable("Third-party tested.  Every batch. ​")
       == meta_ads.comparable("Third-party tested. Every batch. \U0001f331"),
       "whitespace, emoji and the odd pasted character are invisible to the "
       "person who pasted and fatal to an equality test")
    ck("…and different copy does not collide",
       meta_ads.comparable("Third-party tested.")
       != meta_ads.comparable("Designed in Milan."))
    src = (os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "meta_ads.py"))
    body = open(src).read()
    ck("the client cannot write to the ad account",
       "httpx.post" not in body and "httpx.put" not in body
       and '"POST"' not in body,
       "creating an ad to get an id spends the client's budget on copy "
       "nobody approved in the place it matters")

    print("\n— and it matches real rows, with the API stubbed —")
    oid = _ad("Matched later", "hosts", "bottom",
              body="Third-party tested, every batch.")
    _real = meta_ads.live_ads
    try:
        meta_ads.live_ads = lambda tenant, **k: {"ok": True, "why": "", "ads": [
            {"ad_id": "120", "name": "n", "status": "ACTIVE",
             "body": "Third-party tested, every batch.",
             "key": meta_ads.comparable("Third-party tested, every batch."),
             "metrics": {"impressions": 500, "clicks": 25, "spend": 9.0}},
            {"ad_id": "121", "name": "theirs", "status": "ACTIVE",
             "body": "Copy nobody here wrote.",
             "key": meta_ads.comparable("Copy nobody here wrote."),
             "metrics": {}}]}
        res = meta_ads.match("baci")
        ck("our copy is joined to the live ad", res["matched"] == 1, str(res))
        ck("…and an ad running copy we did not write is REPORTED",
           res["unmatched_live"] == 1 and "did not write" in res["note"],
           "usually the owner writing their own, which is worth knowing "
           "beside a system that claims to be drafting them")
        with db.SessionLocal() as s:
            row = s.get(db.Output, oid)
            ck("the row now points at the ad", row.destination == "meta:120")
            ck("…and carries what it did", (row.outcome or {})["clicks"] == 25)
        again = meta_ads.match("baci")
        ck("a second sweep does not re-join what is already joined",
           again["matched"] == 0,
           "a join made once is a fact; re-deriving it lets a later edit to "
           "the copy quietly break a link that was correct when made")
    finally:
        meta_ads.live_ads = _real

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
