"""Every system reports to two audiences, and says what it cannot report.

Owner's framing: *"for each of these systems there are technical reports and
business reports"* — and in his own list of service-desk figures, three are not
ours to compute at all. That split IS the design.

  technical  "is this working" -- checks, catches, coverage. Ours.
  business   "what did it do for me" -- replies, objections, money. Theirs,
             and what they are paying for.

Three sources tell the truth about a missing number instead of hiding it:
`blocked` (we could, if something upstream were written), `provider` (their
platform holds it and the reports system is not built), and `asked` (not ours
to compute, ever — what a support reply costs in staff time is a fact about
their business, and a platform that guesses it puts an invented number in a
document the client forwards on).

`asked` is also the privacy path: a client who declines to connect still gets a
complete report, because the figures move to a single request.

    python3 scripts/test_metrics.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'mt.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import client_report, db, ledger, metrics, systems, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def find(vals, key):
    return next((m for m in vals if m["key"] == key), None)


def main() -> int:
    db.init_db()
    tenants.seed()
    systems.create("baci", "service_desk")

    print("— both audiences are declared, per system —")
    vals = metrics.compute("baci", "service_desk", 30)
    ck("business metrics exist", any(m["kind"] == "business" for m in vals))
    ck("technical metrics exist", any(m["kind"] == "technical" for m in vals))
    ck("a metric a system does not declare is not invented",
       metrics.for_system("no_such_system") == [])

    print("\n— what we CAN compute, we compute —")
    for i in range(3):
        ledger.record("baci", "service_desk", body=f"reply {i}", format="reply",
                      status="published", situation="shipping",
                      objection_id=f"obj-{i % 2}")
    vals = metrics.compute("baci", "service_desk", 30)
    ck("replies are counted", find(vals, "replies_sent")["value"] == 3)
    ck("  grouped by what was asked about",
       find(vals, "situations_seen")["value"] == {"shipping": 3})
    ck("  and distinct objections, not repeats",
       find(vals, "objections_handled")["value"] == 2,
       "three replies drew on two objections")

    print("\n— what we cannot, we NAME —")
    m = find(vals, "sent_as_is")
    ck("'% sent as-is' is reported as not measurable",
       m["value"] is None and m["unavailable"] == "not measurable yet")
    ck("  naming the column that would fix it",
       "edit_diff" in m["why"], m["why"])
    ck("  and how to fix it", "Gmail" in m.get("fix", ""))
    m = find(vals, "revenue_saved")
    ck("money we cannot know is 'waiting on the client'",
       m["unavailable"] == "waiting on the client")
    ck("  and it carries the question to ask", "staff time" in m["ask"])
    ck("  and WHY, so the client sends a considered number",
       "fact about your business" in m["why"])
    ck("nothing unmeasurable is silently dropped",
       len(vals) == len(metrics.for_system("service_desk")),
       "skipping them makes a short report look complete")

    print("\n— the client's own answer is used, with provenance —")
    end = db.utcnow().date().isoformat()
    metrics.record_figure("baci", "revenue_saved", "about £18",
                          period_start="2026-08-01", period_end=end,
                          unit="per reply", supplied_by="Ops at Baci")
    m = find(metrics.compute("baci", "service_desk", 30), "revenue_saved")
    ck("the supplied figure appears", m["value"] == "about £18")
    ck("  stored AS GIVEN, not coerced to a number",
       isinstance(m["value"], str),
       "'about £18' tells us something a float would destroy")
    ck("  attributed to whoever said it", "Ops at Baci" in m["source"])

    print("\n— a stale answer does not leak into a new period —")
    with db.SessionLocal() as s:
        r = s.query(db.ReportedFigure).first()
        r.period_end = "2020-01-01"
        s.commit()
    m = find(metrics.compute("baci", "service_desk", 30), "revenue_saved")
    ck("last year's figure is not reported as this period's",
       m["value"] is None,
       "silently carrying one forward is how a report becomes fiction the "
       "client signed off on")

    print("\n— one ask, not five —")
    req = metrics.request_email("baci", 30, to="ops@baci.example")
    ck("it asks for both open figures at once", req["needed"] == 2)
    ck("  in a single message", req["body"].count("Hello,") == 1)
    ck("  each with its reason", req["body"].count("Why we ask") == 2)
    ck("  and it offers to connect instead of asking again",
       "stop asking" in req["body"])
    ck("nothing is sent — it is composed only", not req["queued"])
    q = metrics.request_email("baci", 30, to="ops@baci.example", queue=True)
    ck("queueing puts it in the approval queue", q["queued"] and q["approval_id"],
       "anything leaving the building belongs in front of a person")

    print("\n— it reaches the client report —")
    rep = client_report.assemble("baci", 30)
    sd = next((s for s in rep["systems"] if s["system"] == "service_desk"), None)
    ck("the report is split per system", sd is not None)
    ck("  with the two audiences apart",
       bool(sd["business"]) and bool(sd["technical"]))
    ck("  and what the client still owes us is listed",
       any(a["metric"] == "revenue_saved" for a in rep["awaiting_client"]))

    print("\n— an account with nothing installed asks for nothing —")
    ck("no systems means no asks", metrics.request_email("coverings")["needed"] == 0)

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
