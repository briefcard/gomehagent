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
    # Money moved OUT of the system metrics entirely — it is an account-level
    # outcome that depends on the business model, not a service-desk figure.
    rev = next((o for o in metrics.outcomes("baci", 30)
                if o["key"] == "revenue"), None)
    ck("money is an account outcome, not a system metric",
       rev is not None and find(vals, "revenue_saved") is None)
    ck("  and it is not ours to invent",
       rev["value"] is None and rev["unavailable"] in
       ("waiting on the client", "not wired"), str(rev.get("unavailable")))
    ck("nothing unmeasurable is silently dropped",
       len(vals) == len(metrics.for_system("service_desk")),
       "skipping them makes a short report look complete")

    print("\n— the client's own answer is used, with provenance —")
    end = db.utcnow().date().isoformat()
    metrics.record_figure("ironside", "avg_event_value", "about £18k",
                          period_start="2026-08-01", period_end=end,
                          unit="per event", supplied_by="Ops at Ironside")
    m = next(o for o in metrics.outcomes("ironside", 30)
             if o["key"] == "avg_event_value")
    ck("the supplied figure appears", m["value"] == "about £18k")
    ck("  stored AS GIVEN, not coerced to a number",
       isinstance(m["value"], str),
       "'about £18k' tells us something a float would destroy")
    ck("  attributed to whoever said it", "Ops at Ironside" in m["source"])

    print("\n— a stale answer does not leak into a new period —")
    with db.SessionLocal() as s:
        r = s.query(db.ReportedFigure).first()
        r.period_end = "2020-01-01"
        s.commit()
    m = next(o for o in metrics.outcomes("ironside", 30)
             if o["key"] == "avg_event_value")
    ck("last year's figure is not reported as this period's",
       m["value"] is None,
       "silently carrying one forward is how a report becomes fiction the "
       "client signed off on")

    print("\n— outcomes follow the BUSINESS, not the system —")
    # Owner's correction: the first version asked "what does one support reply
    # cost you in staff time". They won't have that answer — it is an
    # ops-accounting question we wanted answered so we could derive a number
    # OURSELVES. Asking a client to do our arithmetic gets no reply.
    venue = {o["key"] for o in metrics.outcomes("ironside", 30)}
    shop = {o["key"] for o in metrics.outcomes("baci", 30)}
    ck("a venue is measured in events booked",
       {"enquiries", "events_booked", "avg_event_value"} <= venue, str(venue))
    ck("a store in revenue and average order value",
       {"revenue", "aov"} <= shop, str(shop))
    ck("  and the two vocabularies do not overlap",
       not (venue & shop),
       "reporting a venue's 'average order value' is the client concluding we "
       "do not know what their business is")
    ck("no ops-accounting question survives",
       not any("staff time" in (o.get("why", "") + o.get("label", ""))
               for o in metrics.compute("baci", "service_desk", 30)))

    print("\n— we never ask for what we could read —")
    with db.SessionLocal() as s_:
        s_.add(db.Credential(tenant="baci", provider="shopify", kind="api_key",
                             secret="x", meta={}, status="active"))
        s_.commit()
    shop = {o["key"]: o for o in metrics.outcomes("baci", 30)}
    ck("with commerce connected, revenue is OURS to read",
       shop["revenue"]["unavailable"] == "not wired",
       shop["revenue"].get("why", "")[:60])
    ck("  so it is not on the list of things to ask the client",
       "revenue" not in {a["key"] for a in metrics.asks("baci", 30)},
       "asking for a number we have access to is asking them to do our work")

    print("\n— an unclassified account says so —")
    with db.SessionLocal() as s_:
        t = s_.get(db.Tenant, "eien")
        t.business_model = ""
        s_.commit()
    o = metrics.outcomes("eien", 30)[0]
    ck("it reports the model is unset, rather than defaulting to a shop",
       o["unavailable"] == "unknown business model", str(o["unavailable"]))

    print("\n— one ask, not five —")
    systems.create("ironside", "service_desk")
    req = metrics.request_email("ironside", 30, to="ops@ironside.example")
    ck("every open figure is asked in one go", req["needed"] >= 4, str(req["needed"]))
    ck("  in a single message", req["body"].count("Hello,") == 1)
    ck("  in the venue's own words",
       "Events booked" in req["body"] and "order value" not in req["body"])
    ck("  and it offers to connect instead of asking again",
       "stop asking" in req["body"])
    ck("  round numbers are explicitly fine",
       "Round numbers are fine" in req["body"],
       "a client who thinks we want precision sends nothing")
    ck("nothing is sent — it is composed only", not req["queued"])
    q = metrics.request_email("ironside", 30, to="ops@ironside.example", queue=True)
    ck("queueing puts it in the approval queue", q["queued"] and q["approval_id"],
       "anything leaving the building belongs in front of a person")

    print("\n— it reaches the client report —")
    rep = client_report.assemble("baci", 30)
    sd = next((s for s in rep["systems"] if s["system"] == "service_desk"), None)
    ck("the report is split per system", sd is not None)
    ck("  with the two audiences apart",
       bool(sd["business"]) and bool(sd["technical"]))
    ck("  the headline outcomes are carried separately",
       rep["outcomes"]["model"] == "ecom_inventory"
       and rep["outcomes"]["figures"])

    iron = client_report.assemble("ironside", 30)
    ck("  and what the client still owes us is listed",
       any(a["metric"] == "events_booked" for a in iron["awaiting_client"]),
       str([a["metric"] for a in iron["awaiting_client"]])[:80])

    print("\n— outcomes do not depend on what we installed —")
    # Deliberate, and a change from the first version: a client's headline
    # numbers are facts about their business. Coverings has no system installed
    # and is still a b2b_spec business with projects won.
    ck("an account with no systems still has outcomes to ask for",
       metrics.request_email("coverings")["needed"] == 4,
       str(metrics.request_email("coverings")["needed"]))
    ck("  in ITS vocabulary, not a shop's",
       "Projects won" in metrics.request_email("coverings")["body"])

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
