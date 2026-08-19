"""One period, one client: what we did, what we reached, what stopped us.

The report Gomeh sends. It has to survive being read by the person paying for
it, which sets a higher bar than an internal dashboard: every number needs a
source, and anything that cannot be measured has to say so rather than be
quietly left out. A report with a hole in it is recoverable; a report that
implies completeness it does not have is not.

Three sections, in the order a client cares about:

  · **Work** — what was produced, checked and caught. From `SystemRun`,
    `Output` and `AssuranceEvent`.
  · **Reach** — which of THEIR systems we actually read, and which failed.
    From `ToolCall`. "We read your store 42 times" is a fact about the work;
    "Shopify is connected" is a fact about a settings page.
  · **Blocked** — what the work is waiting on, ranked by what it cost.

**What this deliberately does NOT do is call anything.** Assembling a report
must not be the moment a Shopify token is discovered to be dead, and a report
that takes forty seconds and half-fails is worse than one built from what is
already on record. Live platform figures — revenue, sessions, ad spend — belong
to the `reports` system, which is declared in `systems.CATALOG` and NOT built;
where they would go is marked `not_yet_measured` rather than omitted, so the
gap is visible in the output instead of only in this docstring.
"""
from __future__ import annotations

import datetime as dt

from . import db


def assemble(tenant: str, days: int = 30) -> dict:
    """Everything on record for one account over one window."""
    from . import assurance, kb, systems, tenants, toolcalls

    t = tenants.get(tenant)
    if not t:
        return {"error": f"no account keyed {tenant!r}"}
    since = db.utcnow() - dt.timedelta(days=days)

    # --- work -------------------------------------------------------------
    with db.SessionLocal() as s:
        runs = (s.query(db.SystemRun)
                .filter(db.SystemRun.tenant == tenant,
                        db.SystemRun.created_at >= since).all())
        outs = (s.query(db.Output)
                .filter(db.Output.tenant == tenant,
                        db.Output.created_at >= since).all())

    by_system: dict[str, dict] = {}
    for r in runs:
        b = by_system.setdefault(r.system_id or "?",
                                 {"runs": 0, "blocked": 0, "decided": 0})
        b["runs"] += 1
        if r.stage == "blocked":
            b["blocked"] += 1
        if r.decision:
            b["decided"] += 1

    produced = [o for o in outs if o.status in ("draft", "approved", "published")]
    blocked_out = [o for o in outs if o.status == "blocked"]
    # `repaired` is a self-correction, not a loss, and counting it as either a
    # success or a failure would misdescribe it. It is its own line.
    repaired = [o for o in outs if o.status == "repaired"]

    checks = assurance.report(tenant, days)

    # --- reach ------------------------------------------------------------
    tools = toolcalls.report(tenant, days)
    reached = toolcalls.reached(tenant, days)

    # --- blocked ----------------------------------------------------------
    gaps = systems.blocked_reasons(tenant, days)
    inv = kb.claim_inventory(tenant)

    return {
        "account": {"key": tenant, "name": t.name},
        "period": {"days": days,
                   "from": since.date().isoformat(),
                   "to": db.utcnow().date().isoformat()},
        "work": {
            "runs": len(runs),
            "by_system": by_system,
            "produced": len(produced),
            "blocked": len(blocked_out),
            "self_corrected": len(repaired),
            "decisions_recorded": sum(1 for r in runs if r.decision),
        },
        "assurance": {
            "checks": checks.get("events", 0),
            "caught": checks.get("caught", {}),
            "caught_total": checks.get("caught_total", 0),
            "grounding": checks.get("grounding", {}),
        },
        "reach": {
            "calls": tools.get("calls", 0),
            "platforms_read": reached,
            "failing": tools.get("failing", []),
        },
        "knowledge": {
            "selectable": len(inv.get("selectable", [])),
            "awaiting_review": len(inv.get("pending", [])),
            "expired": len(inv.get("expired", [])),
        },
        # Per system, split by AUDIENCE. Technical answers "is it working" and
        # belongs to us; business answers "what did it do for me" and is what
        # the client is paying for. A report that leads with validator counts
        # is a report about ourselves.
        "systems": _per_system(tenant, days),
        "blocked_on": [{"reason": why, "cost": n} for why, n in gaps[:8]],
        # Figures only the client can give us — the privacy path. One message
        # asks for all of them; see `metrics.request_email`.
        "awaiting_client": _asks(tenant, days),
        # Named, not omitted. A client report that silently leaves out revenue
        # reads as "we did not move revenue"; one that says the figure is not
        # wired reads as what it is.
        "not_yet_measured": _unmeasured(tenant),
    }


def _unmeasured(tenant: str) -> list[dict]:
    """What this report cannot say yet, and what would make it able to.

    Kept as data rather than prose so the console can render it as a to-do and
    the next person can delete entries as they wire them, instead of a
    paragraph nobody updates.
    """
    from . import credentials as cred

    wired = cred.wired_capabilities(tenant)
    out = [{"figure": "quality change over time",
            "why": "SystemRun.edit_diff is never written, so how much a human "
                   "changed before sending cannot be measured",
            "fix": "capture sent-vs-draft in Gmail"}]
    for cap, figure, fix in (
            ("commerce", "revenue and orders in the period",
             "the reports system is declared in systems.CATALOG and not built"),
            ("analytics", "sessions and search impressions", "same"),
            ("ads", "ad spend and return", "same"),
            ("esp", "sends, opens and clicks", "same")):
        if cap in wired:
            out.append({"figure": figure,
                        "why": f"{cap} is connected, but nothing reads it into "
                               f"a report yet", "fix": fix})
        else:
            out.append({"figure": figure,
                        "why": f"{cap} is not connected for this account",
                        "fix": "connect it on the Accounts tab"})
    return out


def _per_system(tenant: str, days: int) -> list[dict]:
    from . import metrics, systems
    out = []
    for row in systems.for_tenant(tenant):
        vals = metrics.compute(tenant, row.key, days)
        if not vals:
            continue
        out.append({
            "system": row.key, "name": row.name or row.key,
            "status": row.status, "autonomy": row.autonomy,
            "business": [m for m in vals if m["kind"] == "business"],
            "technical": [m for m in vals if m["kind"] == "technical"],
        })
    return out


def _asks(tenant: str, days: int) -> list[dict]:
    from . import metrics
    return [{"system": m["system"], "metric": m["key"], "label": m["label"],
             "ask": m.get("ask", ""), "why": m.get("why", "")}
            for m in metrics.asks(tenant, days)]
