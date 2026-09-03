"""The weekly report: read off the record, held for approval, sent on it.

`reports` was declared with no generator and no executor. `client_report
.assemble` already computed the number; what was missing was the rest — a
rendering in the client's vocabulary, an approval that carries the whole
message, and an executor that sends it. Building it found a live defect on
the door it leaves by: `_execute` indexes `p["account"]` and the one other
`send_email` approval this codebase constructed (metrics.request_email) never
set it, so approving the figures request raised KeyError instead of sending.

Run: python3 scripts/test_reports_skill.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rp.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (approvals, client_report, db, gmail_client, metrics,  # noqa: E402
                 skill, skill_pack, systems, tenants)  # noqa: F401

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, "baci")
        t.gmail_alias = "baci"
        s.commit()
    # `reports` requires ANY of analytics/ads/commerce, and the gate is real:
    # with nothing wired the run blocks by name (it did, twice, building
    # this). The gate reads the WIRED view — a live credential — not the
    # declaration, so the suite's idiom applies: stand in for the wiring.
    _real_caps = tenants.capabilities
    tenants.capabilities = lambda k: {**_real_caps(k), "commerce": True}
    # The validator fails closed: with no ban list "nothing can be sent
    # safely", and a bare tenant has none — the first run of this suite filed
    # a BLOCKED output and no approval. A report leaves the building, so the
    # rule stands; the fixture gives the brand its rules.
    from app import kb
    kb.ensure_brand("baci", "Baci Milano")
    kb.add_banned("baci", "handmade")
    row = systems.find("baci", "reports") or systems.create("baci", "reports")
    with db.SessionLocal() as s:
        r = s.get(db.System, row.id)
        r.status = "live"
        s.commit()

    sent: list[dict] = []
    gmail_client.send_email = lambda alias, to, subject, body, thread_id=None, html=None, cc="": (
        sent.append({"alias": alias, "to": to, "subject": subject,
                     "body": body, "html": html}) or "msg_1")

    # ---- render ----------------------------------------------------------
    rep = client_report.assemble("baci", 7)
    msg = client_report.render_email(rep)
    ck("the report renders a subject, text and html",
       msg["subject"] and msg["text"] and "<" in msg["html"], msg["subject"])
    ck("  and leads with the client's name, not ours",
       rep["account"]["name"] in msg["subject"])
    ck("  and names what is not yet measured rather than omitting it",
       "not yet measured" in msg["text"].lower() or not rep.get("not_yet_measured"),
       "a report silent about revenue reads as 'we did not move revenue'")

    # ---- the skill files an output and an approval that carries the send --
    sk = skill.get("weekly_report")
    ck("weekly_report is registered on `reports`",
       sk is not None and sk.system_key == "reports")
    got = skill.run("weekly_report", "baci", days=7, to="client@example.com")
    run_id = got.get("run_id") or ""
    ck("the run completes with a subject", bool(got.get("subject")) or bool(got.get("summary")),
       str(got)[:120])
    with db.SessionLocal() as s:
        aps = (s.query(db.Approval)
               .filter(db.Approval.run_id == run_id,
                       db.Approval.status == "pending").all())
        payloads = [dict(a.payload or {}) for a in aps]
        ap_id = aps[0].id if aps else ""
    ck("one approval is pending for the run", len(aps) == 1, f"{len(aps)} (run {run_id[:8]})")
    send = (payloads[0].get("send_mail") if payloads else None) or {}
    ck("  and it carries the whole message: account, to, subject",
       send.get("account") == "baci" and send.get("to") == "client@example.com"
       and bool(send.get("subject")), str({k: send.get(k) for k in ('account', 'to')}))
    ck("  nothing was sent by producing it", not sent, str(sent))

    # ---- approving IS the send --------------------------------------------
    said = approvals.apply_decision(ap_id, "approved")
    ck("approving sends exactly once", len(sent) == 1, f"{len(sent)} send(s)")
    ck("  from the account's alias, to the client",
       sent and sent[0]["alias"] == "baci" and sent[0]["to"] == "client@example.com")
    ck("  and says so", "sent to client@example.com" in said, said[:100])

    # ---- the pair: no recipient means no send is attached, and it says why --
    sent.clear()
    got2 = skill.run("weekly_report", "baci", days=7)
    with db.SessionLocal() as s:
        aps2 = (s.query(db.Approval)
                .filter(db.Approval.run_id == (got2.get("run_id") or ""),
                        db.Approval.status == "pending").all())
        has_send = any((a.payload or {}).get("send_mail") for a in aps2)
    ck("with no recipient the report still renders but no send is attached",
       aps2 and not has_send,
       f"{len(aps2)} approval(s), send attached={has_send}")
    said2 = approvals.apply_decision(aps2[0].id, "approved") if aps2 else ""
    ck("  and approving it sends nothing, saying so",
       not sent and "Nothing was sent" in said2, said2[:100])

    # ---- the live defect this found: the figures request had no account ---
    real_asks = metrics.asks
    metrics.asks = lambda tenant, days: [{"key": "revenue", "label": "Revenue",
                                         "why": "we divide by it"}]
    try:
        req = metrics.request_email("baci", 30, to="client@example.com", queue=True)
    finally:
        metrics.asks = real_asks
    with db.SessionLocal() as s:
        ap = s.get(db.Approval, req.get("approval_id") or "")
        pl = dict(ap.payload or {}) if ap else {}
    ck("the figures request now names its sending account",
       req.get("queued") and pl.get("account") == "baci",
       f"queued={req.get('queued')} payload keys={sorted(pl)}")
    sent.clear()
    approvals.apply_decision(ap.id, "approved")
    ck("  so approving it sends instead of raising", len(sent) == 1 and sent[0]["alias"] == "baci",
       f"{len(sent)} send(s) — KeyError('account') was the behaviour before")

    # ---- the map knows --------------------------------------------------
    eff = next(r for r in systems.effectiveness() if r["system"] == "reports")
    ck("the effectiveness map measures reports by assemble",
       eff["measure_fn"] == "client_report.assemble" and eff["measure_ok"])
    ck("the catalogue's ship resolves", systems._resolves("approvals.send_report"))

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
