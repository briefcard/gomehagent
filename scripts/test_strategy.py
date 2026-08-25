"""The strategy substrate, read at last — phases 2.2, 2.3 and 2.4.

`ledger.record` has written the intent, the angle, the shape, the claims and
the featured entity on every send since it was written, and exactly one thing
ever read any of it: the drafter, four rows at a time, for one segment. So the
next email differed from the last and nobody could answer the questions that
decide a programme — which lists have we neglected, is this brand giving
before it asks, is one product carrying everything, and did any of it work.

What this pins:

  2.2  THE READER. `strategy.read` aggregates what was already there, per
       cohort and brand-wide, and names findings rather than scoring them. A
       cohort with ZERO sends is the most actionable row in the table, so it
       appears; a view built from sends alone would omit exactly the ones
       worth acting on.
  2.3  THE PLANNER PROPOSES AGAINST IT. The proof the initiative asks for is
       that "the planner's choice of segment changes when the ledger
       changes" — so this writes history, plans, rewrites history, and checks
       the order moved.
  2.4  THE RESULT COMES BACK. `published` was written on the reply path only,
       so anti-repeat was blind to every campaign ever sent. The platform is
       now the authority, and only a FINISHED campaign counts: a send still
       going out already has opens, and filing those as its result records a
       number that is wrong and never looks again.

Run: python3 scripts/test_strategy.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'st.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (db, esp, kb, ledger, performance, planner,  # noqa: E402
                 segments, strategy, systems, tenants)

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _force(sys_id: str, **fields) -> None:
    with db.SessionLocal() as s:
        r = s.get(db.System, sys_id)
        for k, v in fields.items():
            setattr(r, k, v)
        s.commit()


def _send(tenant, segment, *, days_ago, intent="story", entity="",
          claims=(), shape=("hero", "text", "cta"), dest="", status="cleared"):
    o = ledger.record(tenant, "campaign_email", situation=intent,
                      entity_key=entity, audience_key=segment,
                      claim_ids=list(claims), angle=segment,
                      format="campaign_email", status=status,
                      theme=f"{intent}|designed", shape=list(shape),
                      destination=dest, body="x")
    with db.SessionLocal() as s:
        r = s.get(db.Output, o.id)
        r.created_at = db.utcnow() - dt.timedelta(days=days_ago)
        s.commit()
    return o.id


def _finding(rep, needle):
    return next((f for f in rep["findings"] if needle in f["what"]), None)


def main() -> int:
    db.init_db()
    tenants.seed()

    # ---------------------------------------------------------------- 2.2 --
    print("— 2.2  the reader: a cohort nobody wrote to is the loudest row —")
    rep = strategy.read("baci", days=90)
    ck("with no sends at all it says so, rather than reporting balance",
       rep["brand"]["sends"] == 0
       and _finding(rep, "nothing has been sent") is not None,
       str(rep["findings"])[:90])
    ck("and every catalogue cohort is present at zero",
       len(rep["segments"]) >= 8 and all(r["sends"] == 0 for r in rep["segments"]),
       str(len(rep["segments"])))

    # A programme that asks too often, about one product, ignoring one cohort.
    for i, d in enumerate((70, 56, 42, 28, 14)):
        _send("baci", "reorder_due", days_ago=d,
              intent="offer" if i % 2 == 0 else "story",
              entity="aqua-pitcher", claims=["c1"])
    _send("baci", "vip_high_aov", days_ago=60, intent="offer",
          entity="aqua-pitcher", claims=["c1"])
    rep = strategy.read("baci", days=90)

    seg = next(r for r in rep["segments"] if r["segment"] == "reorder_due")
    ck("per cohort: how many, how often, how long since",
       seg["sends"] == 5 and seg["median_gap_days"] == 14.0
       and 13 < seg["days_since"] < 16,
       f"n={seg['sends']} gap={seg['median_gap_days']} since={seg['days_since']}")
    ck("and what it was told — intents counted, not guessed",
       seg["intents"] == {"offer": 3, "story": 2}, str(seg["intents"]))

    ck("brand-wide give:ask is measured",
       rep["brand"]["gives"] == 2 and rep["brand"]["asks"] == 4
       and rep["brand"]["give_ask_ratio"] == 0.5,
       str(rep["brand"]["give_ask_ratio"]))
    f = _finding(rep, "gives to")
    ck("being asked more often than given to is a named finding",
       f is not None and "unsubscribe" in f["why"], str(f)[:80])
    ck("and it says what would change it, not just that it is wrong",
       bool(f and f["fix"]), str(f and f["fix"])[:60])

    f = _finding(rep, "high-value cohorts with nothing recent")
    ck("a neglected high-value cohort is named",
       f is not None and "lapsed_60_90" in f["what"], str(f and f["what"])[:90])

    f = _finding(rep, "aqua-pitcher")
    ck("one product carrying the programme is named, with its share",
       f is None, "single-product catalogue — nothing to concentrate against")
    _send("baci", "repeat_buyers", days_ago=20, intent="story",
          entity="other-thing", claims=["c2"])
    rep = strategy.read("baci", days=90)
    f = _finding(rep, "aqua-pitcher")
    ck("with a second product on file the concentration IS named",
       f is not None and "%" in f["what"], str(f and f["what"])[:90])
    ck("measured against sends that featured a product, not all sends",
       rep["brand"]["top_entity_share"] == 0.86,
       str(rep["brand"]["top_entity_share"]))

    _send("baci", "win_back", days_ago=9, intent="story", shape=("text", "cta"))
    _send("baci", "win_back", days_ago=2, intent="education", shape=("text", "cta"))
    rep = strategy.read("baci", days=90)
    f = _finding(rep, "same layout twice running")
    ck("the same shape twice running is caught — the owner's own complaint",
       f is not None and "win_back" in f["what"], str(f and f["what"])[:80])

    # ---------------------------------------------------------------- 2.3 --
    print("\n— 2.3  the planner's choice changes when the ledger changes —")
    camp = systems.create("baci", "campaign_email")
    _force(camp.id, status="live", autonomy="approve_all")
    camp = systems.get(camp.id)

    order_a = [s["key"] for s in planner._by_neglect(
        "baci", segments.for_tenant("baci")["high_value"])]
    ck("the most-neglected high-value cohort is first",
       order_a[0] == "lapsed_60_90", str(order_a))
    ck("and the one written to a fortnight ago is last",
       order_a[-1] == "reorder_due", str(order_a))

    # Change the ledger. Nothing else.
    _send("baci", "lapsed_60_90", days_ago=0, intent="story")
    order_b = [s["key"] for s in planner._by_neglect(
        "baci", segments.for_tenant("baci")["high_value"])]
    ck("writing to it moves it to the BACK — the order followed the ledger",
       order_b[-1] == "lapsed_60_90" and order_a != order_b,
       f"{order_a} -> {order_b}")

    out = planner.top_up(camp)
    with db.SessionLocal() as s:
        refs = sorted((r.ref, (r.brief or {}).get("planned_for", ""))
                      for r in s.query(db.SystemRun)
                      .filter(db.SystemRun.stage == systems.PLANNED,
                              db.SystemRun.tenant == "baci").all())
    first = min(refs, key=lambda x: x[1])[0] if refs else ""
    ck("the earliest slot went to the cohort most owed a send",
       "vip_high_aov" in first, f"{first} of {[r for r, _ in refs]}")
    ck("a strategy read that fails does not stop planning",
       planner._by_neglect("nosuchtenant",
                           segments.CATALOG["ecom_inventory"][:2]) is not None)

    # ---------------------------------------------------------------- 2.4 --
    print("\n— 2.4  the platform says what happened, and only when it is over —")
    # `add_asset` returns a human message, not an id — the id comes from the
    # library. Getting this wrong made the warning path fire on a nonexistent
    # asset, which is exactly the false-positive it exists to avoid.
    kb.add_asset("baci", "https://cdn.example/hero.jpg", rights=kb.OWNED,
                 title="Hero", origin="human")
    aid = kb.assets("baci")[0].id
    mid = _send("baci", "reorder_due", days_ago=1, intent="offer",
                entity="aqua-pitcher", claims=["c9"],
                dest="esp:omnisend:campaign/camp_A")
    ck("before confirmation, anti-repeat cannot see that send at all",
       ledger.used_recently("baci", "c9", entity_key="aqua-pitcher") == [],
       "no campaign row has ever been `published`")
    sending = _send("baci", "repeat_buyers", days_ago=0, intent="story",
                    dest="esp:omnisend:campaign/camp_B")
    dead = _send("baci", "win_back", days_ago=1, intent="story",
                 dest="esp:omnisend:campaign/camp_C")
    with db.SessionLocal() as s:
        s.get(db.Output, mid).media_ids = [aid]
        s.commit()

    calls = {"metrics": 0}

    class _Mod:
        FINISHED = ("sent",)
        DEAD = ("canceled", "stopped", "expired", "error", "onHold")

        @staticmethod
        def campaign(tenant, cid):
            state = {"camp_A": "sent", "camp_B": "paused",
                     "camp_C": "canceled"}[cid]
            return {"ok": True, "campaign_id": cid, "status": state,
                    "sent_at": "2026-08-23T10:00:00Z"}

        @staticmethod
        def campaign_metrics(tenant, *, days=30):
            calls["metrics"] += 1
            return {"ok": True, "campaigns": {
                "camp_A": {"sent": 1200, "openedUnique": 384, "openRate": 32.0,
                           "clickedUnique": 61, "clickRate": 5.1},
                "camp_B": {"sent": 40, "openedUnique": 30, "openRate": 75.0}}}
    esp.provider_for = lambda t: "omnisend"
    esp.backend = lambda t: (_Mod, "")

    got = performance.sync("baci")
    ck("the finished campaign is confirmed", got["confirmed"] == 1, str(got))
    ck("ONE analytics call for the whole account — the limit is 55 a day",
       calls["metrics"] == 1, str(calls["metrics"]))

    with db.SessionLocal() as s:
        a = s.get(db.Output, mid)
        b = s.get(db.Output, sending)
        c = s.get(db.Output, dead)
    ck("it is published at last — the first campaign row ever to be",
       a.status == "published" and a.published_at is not None, a.status)
    ck("the platform's own send time is used, not the moment we asked",
       db.as_utc(a.published_at).date().isoformat() == "2026-08-23",
       str(a.published_at))
    ck("and the numbers are on the row",
       (a.outcome or {}).get("openRate") == 32.0
       and a.outcome.get("campaign_id") == "camp_A", str(a.outcome)[:80])

    ck("a campaign still SENDING is not confirmed, though it has opens",
       b.status != "published" and got["waiting"] == 1,
       f"{b.status} / waiting={got['waiting']}")
    ck("a canceled one stops being asked about, and says what became of it",
       c.status != "published" and c.destination.endswith(":canceled"),
       c.destination)

    ck("the photograph learned what it earned",
       (kb.assets("baci")[0].outcome or {}).get("email", {}).get("openRate") == 32.0,
       str(kb.assets("baci")[0].outcome)[:70])
    ck("and no false alarm was raised about it — it was publishable",
       not got.get("warnings"), str(got.get("warnings")))
    ck("but its use counter was not double-counted",
       str(kb.assets("baci")[0].uses or "0") in ("0", "1"),
       str(kb.assets("baci")[0].uses))

    again = performance.sync("baci")
    ck("a confirmed send is not re-confirmed on the next sweep",
       again["confirmed"] == 0, str(again))

    print("\n  anti-repeat can finally see a campaign that went out")
    seen = ledger.used_recently("baci", "c9", entity_key="aqua-pitcher")
    ck("the claim that went out is now spent, and scoped to its product",
       [r.id for r in seen] == [mid], str([r.id[:8] for r in seen]))
    ck("and a claim on a still-sending campaign is NOT spent yet",
       ledger.used_recently("baci", "c1", entity_key="aqua-pitcher") == [],
       "only a finished send counts")

    # ---------------------------------------------------------------- auth --
    print("\n— the two new reads are behind the console key —")
    from fastapi.testclient import TestClient
    from app import web

    # A FRESH CLIENT PER REQUEST. `admin_key` also accepts a session cookie,
    # and TestClient keeps a cookie jar — so reusing one authenticates the
    # "unauthenticated" call and the assertion passes for the wrong reason.
    # This codebase has been caught by that exact false pass before.
    for path in ("/admin/strategy?tenant=baci", "/admin/moments?tenant=baci"):
        shut = TestClient(web.app).get(path).json()
        ck(f"{path.split('?')[0]} refuses without a key",
           shut == {"error": "unauthorized"}, str(shut)[:70])
        opened = TestClient(web.app).get(path + "&key=s3cret").json()
        ck("  and answers with one", "error" not in opened, str(opened)[:60])
    leak = TestClient(web.app).get("/admin/moments?tenant=baci").text
    ck("no customer address can be read out of the closed door",
       "@" not in leak, leak[:80])

    print("\n" + ("FAILURES: " + ", ".join(_fail) if _fail else "all good"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
