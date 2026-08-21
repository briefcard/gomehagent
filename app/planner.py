"""Planners — the top-up half of the workflow layer.

A planner proposes PLANS: it reads catalogs and ledgers and files work in
advance through `systems.open_plan`, and that is all it does. It never
consumes (the tick's other half does that, through every gate), never
invents a value (a field it cannot read from data stays absent and
`plan_complete` names it), and never writes over the owner (`open_plan`'s
carry-forward is structural). Deterministic code, no model call — which
angle to run to which segment is catalog data, not judgement.

One planner exists today: the campaign rollout. The registry is what the
tick and the console's "Propose now" button both call, so a system gains a
planner by adding a row here — never by teaching the tick a new special
case.

Cadence is the owner's number. `DEFAULT_CADENCE` is deliberately
conservative — one campaign per segment per month, a three-week horizon —
and `systems.set_cadence` stores the owner's override on the System row,
editable on the Planned section (a knob that exists only in code is a knob
that does not exist).
"""
from __future__ import annotations

import datetime as dt

from . import db, segments, systems

#: First proposal lands this many days out — never today, so a fresh proposal
#: is reviewable before the tick can consume it.
LEAD_DAYS = 2

#: Days between one segment's slot and the next, so four segments do not all
#: land in the same inbox week.
SPACING_DAYS = 5

DEFAULT_CADENCE = {"horizon_days": 21, "per_segment_monthly": 1}

#: Hard ceilings for the owner's overrides. A typo'd 900-day horizon or a
#: 50-per-month cap should be refused at the knob, not discovered as a full
#: queue.
MAX_HORIZON_DAYS = 90
MAX_PER_SEGMENT_MONTHLY = 8


def cadence_for(sysrow) -> dict:
    """Effective cadence: defaults ← workflow declaration ← the owner's
    System.config, each layer overriding the one before, junk ignored."""
    out = dict(DEFAULT_CADENCE)
    out.update({k: v for k, v in
                (systems.workflow(sysrow.key).get("cadence") or {}).items()
                if k in DEFAULT_CADENCE})
    cfg = ((sysrow.config or {}).get("cadence") or {})
    for k, cap in (("horizon_days", MAX_HORIZON_DAYS),
                   ("per_segment_monthly", MAX_PER_SEGMENT_MONTHLY)):
        try:
            v = int(cfg.get(k, out[k]))
        except (TypeError, ValueError):
            continue
        if 0 < v <= cap:
            out[k] = v
    return out


def _month(d: dt.date) -> str:
    return d.strftime("%Y-%m")


def _next_month(d: dt.date) -> dt.date:
    return (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)


def _existing_by_month(sysrow, prefix: str) -> dict[str, int]:
    """How many items already exist per calendar month for one segment.

    EVERY stage counts — an open plan, a consumed run, and a SKIPPED one.
    A skip was the owner's decision about that month, and a planner that
    re-proposes a declined item is a nag wearing an algorithm.
    """
    out: dict[str, int] = {}
    with db.SessionLocal() as s:
        rows = (s.query(db.SystemRun.ref)
                .filter(db.SystemRun.system_id == sysrow.id,
                        db.SystemRun.ref.like(prefix + "%")).all())
    for (ref,) in rows:
        try:
            d = dt.date.fromisoformat((ref or "")[len(prefix):])
        except ValueError:
            continue
        out[_month(d)] = out.get(_month(d), 0) + 1
    return out


def campaign_rollout(sysrow) -> dict:
    """Propose the next campaigns: one per HIGH-VALUE segment, monthly-capped.

    What each field comes from: `segment` and `goal` are the business-model
    catalog's own key and angle (`segments.CATALOG`), the date is cadence
    arithmetic, and `subject` is deliberately NOT proposed — no source holds
    one, so it stays blank for the owner to set or the skill's drafter to
    write, rather than a template pretending to be a decision.

    At most one new item per segment per run — the daily tick paces the rest.
    Common-tier segments are flows-in-waiting (cart, welcome) and are not
    proposed as campaigns.
    """
    got = segments.for_tenant(sysrow.tenant)
    if not got.get("ok"):
        return {"ok": False, "proposed": 0, "refreshed": 0,
                "refusals": [got.get("error", "segments unavailable")]}
    cad = cadence_for(sysrow)
    today = dt.date.today()
    horizon_end = today + dt.timedelta(days=cad["horizon_days"])
    slot = today + dt.timedelta(days=LEAD_DAYS)

    proposed = refreshed = 0
    refusals: list[str] = []
    for seg in got["high_value"]:
        prefix = f"campaign:{sysrow.tenant}:{seg['key']}:"
        have = _existing_by_month(sysrow, prefix)
        d = slot
        while d <= horizon_end:
            if have.get(_month(d), 0) < cad["per_segment_monthly"]:
                out = systems.open_plan(
                    sysrow.tenant, sysrow.key, ref=prefix + d.isoformat(),
                    plan={"segment": seg["key"],
                          "goal": seg.get("angle", "")},
                    planned_for=d.isoformat(), trigger="planner")
                if out.get("error"):
                    refusals.append(out["error"])
                elif out.get("created"):
                    proposed += 1
                else:
                    refreshed += 1
                break
            # This month is at its cap — the next candidate is next month's
            # first day inside the horizon, never a denser packing of this
            # one. Strictly month-forward, so the walk always terminates.
            d = _next_month(d)
        slot += dt.timedelta(days=SPACING_DAYS)
    return {"ok": True, "proposed": proposed, "refreshed": refreshed,
            "refusals": refusals}


#: system key -> planner. The tick and the console both resolve through this,
#: so a new planner is a row here and nothing else.
PLANNERS = {
    "campaign_email": campaign_rollout,
}


def top_up(sysrow):
    """Run the system's planner, if it has one. None means 'no planner' —
    which is a different fact from a planner that proposed nothing."""
    fn = PLANNERS.get(sysrow.key)
    if fn is None:
        return None
    if not systems.is_on(sysrow):
        # The switch dictates at the queue: open_plan would refuse each item
        # anyway, but one named refusal beats four identical ones.
        return {"ok": False, "proposed": 0, "refreshed": 0,
                "refusals": [f"the {sysrow.key} system is "
                             f"{sysrow.status or 'off'} — nothing is proposed "
                             f"for a system that is off"]}
    return fn(sysrow)
