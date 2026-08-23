"""The Systems Check view: what is unwell, since when, and what actually went wrong.

What this replaces (owner, 2026-08-23): the Systems tab opened on a flat list
reading "12× no_ban_list" — no dates, nothing clickable, no way to see a single
example, and sitting ABOVE the systems it was about. `blocked_reasons` collapsed
every run to `(reason, count)`, so the console could RANK the backlog and never
show you one instance of anything on it. The content was on the `SystemRun` row
the whole time and was never joined.

Pinned here:

  1. THE JOIN EXISTS. `systems.attention` returns, per reason, the runs
     themselves — when, which system, which stage, the platform's own error,
     and the head of what the run produced.
  2. QUALITY IS INCLUDED HERE AND EXCLUDED FROM THE AUTHORING BACKLOG. Those
     two lists disagree ON PURPOSE, and both behaviours are asserted together
     so neither can be "fixed" into agreement by someone who meets only one.
  3. EVERY ITEM KNOWS WHERE ITS FIX LIVES. A diagnosis you cannot act on is
     the thing being replaced, not a smaller version of it.
  4. IT IS PER SYSTEM AND OVER TIME. Filterable by system, bounded by the
     window, and a run outside the window is not counted.

Run: python3 scripts/test_systems_check.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sc.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, systems, tenants  # noqa: E402
from app.web import app  # noqa: E402

KEY = "s3cret"
client = TestClient(app)
_fails = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    ce = systems.find("baci", "campaign_email") or systems.create("baci", "campaign_email")
    ir = systems.find("baci", "inbound_reply") or systems.create("baci", "inbound_reply")
    old = db.utcnow() - dt.timedelta(days=60)

    with db.SessionLocal() as s:
        s.add(db.SystemRun(tenant="baci", system_id=ce.id, stage="blocked",
                           blocked_on=["no_ban_list"], ref="plan-7",
                           error="the validator had nothing to check against"))
        s.add(db.SystemRun(tenant="baci", system_id=ce.id, stage="blocked",
                           blocked_on=["no_ban_list"],
                           output="Subject: Glasses that go where you go"))
        s.add(db.SystemRun(tenant="baci", system_id=ce.id, stage="sent",
                           blocked_on=["dead_link"],
                           output="shipped with a dead button"))
        s.add(db.SystemRun(tenant="baci", system_id=ce.id, stage="sent",
                           blocked_on=["coherence:image_off_subject"]))
        s.add(db.SystemRun(tenant="baci", system_id=ir.id, stage="blocked",
                           blocked_on=["no_ban_list"]))
        s.add(db.SystemRun(tenant="baci", system_id=ce.id, stage="sent"))
        # OUTSIDE the window. Without this the "over time" claim is untested.
        s.add(db.SystemRun(tenant="baci", system_id=ce.id, stage="blocked",
                           blocked_on=["ancient_problem"], created_at=old))
        s.commit()

    print("— the runs are joined, not collapsed to a count —")
    need = systems.attention("baci", days=30)
    top = need[0]
    ck("the most frequent thing is first", top["reason"] == "no_ban_list"
       and top["count"] == 3, f'{top["reason"]} x{top["count"]}')
    ck("…and it names every system it happened to",
       top["systems"] == {"campaign_email": 2, "inbound_reply": 1},
       str(top["systems"]))
    ck("…and carries the runs themselves", len(top["examples"]) >= 2)
    ck("…with the error in the platform's own words",
       any("nothing to check against" in e["error"] for e in top["examples"]))
    ck("…and the head of what the run produced",
       any("Glasses that go where you go" in e["output"] for e in top["examples"]))
    ck("…each example identifying its run, stage and time",
       all(e["run_id"] and e["stage"] and e["at"] for e in top["examples"]))
    ck("first and last seen are recorded, so a spike is visible",
       top["first_at"] is not None and top["last_at"] is not None
       and top["first_at"] <= top["last_at"])

    print("\n— over time: the window actually bounds it —")
    ck("a run older than the window is not counted",
       not any(a["reason"] == "ancient_problem" for a in need))
    ck("…and widening the window finds it",
       any(a["reason"] == "ancient_problem"
           for a in systems.attention("baci", days=90)))

    print("\n— per system —")
    only = systems.attention("baci", days=30, system_key="inbound_reply")
    ck("filtering by system keeps only that system's runs",
       len(only) == 1 and only[0]["reason"] == "no_ban_list"
       and only[0]["count"] == 1, str([(a["reason"], a["count"]) for a in only]))
    rows = {r["key"]: r for r in systems.per_system("baci", days=30)}
    ck("each system reports what it did", rows["campaign_email"]["runs"] == 5,
       str(rows["campaign_email"]))
    ck("…blocked and defective are counted separately",
       rows["campaign_email"]["blocked"] == 2
       and rows["campaign_email"]["defective"] == 2,
       str(rows["campaign_email"]))
    ck("…because a run that SHIPPED with a defect is invisible otherwise",
       rows["campaign_email"]["shipped"] == 3)

    print("\n— the two lists disagree on purpose —")
    backlog = dict(systems.blocked_reasons("baci", 30))
    attn = {a["reason"] for a in need}
    ck("a quality failure IS on the attention list",
       "coherence:image_off_subject" in attn)
    ck("…and is NOT on the authoring backlog, because authoring cannot fix it",
       "coherence:image_off_subject" not in backlog)
    ck("a real authoring gap is on both", "no_ban_list" in attn
       and backlog.get("no_ban_list") == 3)

    print("\n— every item knows where its fix lives —")
    kinds = {a["reason"]: (a["kind"], a["where"]) for a in need}
    ck("a missing ban list sends you to Knowledge",
       kinds["no_ban_list"] == ("knowledge", "kb"), str(kinds.get("no_ban_list")))
    ck("a quality failure stays here", kinds["dead_link"][0] == "quality")
    ck("an uninstalled system sends you to Systems",
       systems.classify_reason(
           "the campaign_email system is not installed for baci")["where"]
       == "systems")
    ck("a missing connection sends you to Connections",
       systems.classify_reason("Omnisend is not connected")["where"] == "accounts")
    ck("something unrecognised is not forced into a bucket",
       systems.classify_reason("a thing nobody has seen before")["kind"] == "other")

    print("\n— the page —")
    h = client.get(f"/admin/ui?tab=diagnostics&view=systems&tenant=baci&key={KEY}").text
    ck("Systems check renders", "Systems check" in h and "Needs attention" in h)
    ck("…the reason is on the page", "no_ban_list" in h)
    ck("…with the run's own error, not just a count",
       "nothing to check against" in h)
    ck("…and what the run produced", "Glasses that go where you go" in h)
    ck("…and a way to act on it", "tab=kb" in h and "Knowledge" in h)
    ck("…and the per-system table separates blocked from defective",
       "defective" in h and "Every system, last" in h)

    sysview = client.get(f"/admin/ui?tab=systems&tenant=baci&key={KEY}").text
    ck("the Systems tab no longer carries the flat refused list",
       "What the systems refused on" not in sysview)
    ck("…but still says something needs attention, and where to look",
       "Something needs attention" in sysview
       and "view=systems" in sysview)

    print("\n" + ("all checks passed" if not _fails
                  else f"{len(_fails)} FAILED: " + "; ".join(_fails)))
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
