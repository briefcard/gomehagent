"""Did the data layer do anything, and did it help?

Two questions, and they are not the same question. This module is careful to
keep them apart, because conflating them is how a dashboard starts flattering
the thing it is supposed to measure.

**Did it run** is a counting problem and this answers it completely: how many
drafts were checked, by which rules, at which point in the system, and how many
carried a claim_id.

**Did it help** is a comparison, and counting one arm cannot produce one. What
CAN be said honestly is bounded, so it is stated in exactly three ways and no
further:

  1. **Catches are a real counterfactual.** A `banned_claim` row is a phrase
     the model wrote and deterministic code stopped. Without the layer it
     would have gone out. That is not a proxy for value, it IS the value, and
     it is the only number here that needs no interpretation.

  2. **Repairs are a weaker one.** A draft that failed, was handed its own
     failures and passed on attempt 2 is an output the model alone would have
     got wrong once. It says the loop works; it does not say the final draft
     is good.

  3. **Edit distance is the honest measure of quality, and it is mostly
     missing.** `SystemRun.edit_diff` is what a human changed before sending,
     which is the only signal of where the generator is actually wrong.
     `edited_share()` reports it and will report `unknown` until something
     writes that column. Reporting an unmeasured thing as zero is how a
     dashboard lies, so it reports coverage first and the number second.

What this module will NOT do is compare a grounded draft against an ungrounded
one, because nothing here has ever produced both for the same input.
`scripts/ab_context.py` is the harness for that and has never been run.
"""
from __future__ import annotations

import datetime as dt

from . import db

#: Where a check happened. Kept as data so a new call site cannot be counted
#: as an existing one by accident.
SOURCES = ("skill", "bridge", "mail", "console")


def record(tenant: str, *, source: str, checked: list[str],
           caught: list[str], verdict: str, system_key: str = "",
           run_id: str = "", output_id: str = "", attempt: int = 0,
           grounded: bool | None = None,
           thin: list[str] | None = None) -> str:
    """File one check. Never raises — assurance must not cost an output.

    A logging call that can break the thing it observes is worse than no
    logging, so every failure here is swallowed. The one thing it does not do
    is swallow silently in a way that reads as "no checks ran": `coverage()`
    reports the count of events beside every rate, so an empty table looks
    empty rather than looking clean.
    """
    try:
        with db.SessionLocal() as s:
            row = db.AssuranceEvent(
                tenant=tenant, system_key=system_key, run_id=run_id,
                output_id=output_id, source=source,
                checked=list(checked or []), caught=list(caught or []),
                attempt=str(attempt), verdict=verdict,
                grounded="" if grounded is None else ("yes" if grounded else "no"),
                thin=list(thin or []))
            s.add(row)
            s.commit()
            return row.id
    except Exception:                                            # noqa: BLE001
        return ""


def _rows(tenant: str = "", days: int = 30) -> list[db.AssuranceEvent]:
    since = db.utcnow() - dt.timedelta(days=days)
    with db.SessionLocal() as s:
        q = s.query(db.AssuranceEvent).filter(
            db.AssuranceEvent.created_at >= since)
        if tenant:
            q = q.filter(db.AssuranceEvent.tenant == tenant)
        return q.order_by(db.AssuranceEvent.created_at.desc()).all()


def report(tenant: str = "", days: int = 30) -> dict:
    """Everything the console shows, computed rather than stored."""
    rows = _rows(tenant, days)
    if not rows:
        # Not zeros. Zero checks and zero catches look identical to a healthy
        # system with nothing to catch, and they mean opposite things.
        return {"tenant": tenant, "days": days, "events": 0,
                "verdict": "nothing has been checked in this window",
                "by_source": {}, "caught": {}, "repairs": {},
                "grounding": {}, "thin": {}, "edited": edited_share(tenant, days)}

    by_source: dict[str, dict] = {}
    for r in rows:
        b = by_source.setdefault(r.source or "unknown",
                                 {"checks": 0, "caught": 0, "blocked": 0})
        b["checks"] += 1
        if r.caught:
            b["caught"] += 1
        if r.verdict == "blocked":
            b["blocked"] += 1

    caught: dict[str, int] = {}
    for r in rows:
        for rule in r.caught or []:
            caught[rule] = caught.get(rule, 0) + 1

    first = [r for r in rows if str(r.attempt) == "0"]
    repaired = [r for r in rows if r.verdict == "repaired"]
    blocked = [r for r in rows if r.verdict == "blocked"]

    grounded_known = [r for r in rows if r.grounded in ("yes", "no")]
    grounded_yes = [r for r in grounded_known if r.grounded == "yes"]

    thin_counts: dict[str, int] = {}
    for r in rows:
        for t in r.thin or []:
            thin_counts[t] = thin_counts.get(t, 0) + 1

    return {
        "tenant": tenant, "days": days, "events": len(rows),
        "by_source": by_source,
        # The counterfactual. Every one of these is a phrase the model wrote
        # and the layer stopped.
        "caught": dict(sorted(caught.items(), key=lambda kv: -kv[1])),
        "caught_total": sum(caught.values()),
        "repairs": {"attempted": len(rows) - len(first),
                    "succeeded": len(repaired),
                    "still_blocked": len(blocked)},
        "grounding": {
            "measured": len(grounded_known),
            "with_a_claim_id": len(grounded_yes),
            "rate": (round(len(grounded_yes) / len(grounded_known), 3)
                     if grounded_known else None)},
        "thin": dict(sorted(thin_counts.items(), key=lambda kv: -kv[1])[:10]),
        "edited": edited_share(tenant, days),
    }


def edited_share(tenant: str = "", days: int = 30) -> dict:
    """How much a human changed before approving — coverage FIRST.

    `SystemRun.edit_diff` is declared, is on `finish_run`'s writable list, and
    nothing has ever passed it. Until something does, this reports
    `coverage: 0` and a null rate rather than 0% edited, because "nobody
    edited anything" and "nobody recorded whether anyone edited anything" are
    opposite findings and a dashboard that shows them the same way is lying in
    the direction that flatters it.
    """
    since = db.utcnow() - dt.timedelta(days=days)
    with db.SessionLocal() as s:
        q = s.query(db.SystemRun).filter(db.SystemRun.created_at >= since,
                                         db.SystemRun.decision != None)  # noqa: E711
        if tenant:
            q = q.filter(db.SystemRun.tenant == tenant)
        decided = q.all()
    with_diff = [r for r in decided if (r.edit_diff or "").strip()]
    return {"decided_runs": len(decided),
            "coverage": len(with_diff),
            "edited_rate": (round(len(with_diff) / len(decided), 3)
                            if decided and with_diff else None),
            "note": ("edit_diff is never written, so quality change cannot be "
                     "measured yet — this is a gap in the instrumentation, not "
                     "a finding about the drafts"
                     if not with_diff else "")}


def catches(tenant: str = "", days: int = 30, limit: int = 50) -> list[dict]:
    """The list to show somebody who asks what the layer is for."""
    return [{"when": db.as_utc(r.created_at).date().isoformat(),
             "tenant": r.tenant, "where": r.source, "system": r.system_key,
             "rules": r.caught, "verdict": r.verdict, "run_id": r.run_id}
            for r in _rows(tenant, days) if r.caught][:limit]
