"""Live reports and logs, per account — where a system is breaking, and how.

Assurance answers "is the *output* safe". Nothing answered "is this *running*,
and if not, at which layer did it stop" — the question you have at the moment
something is wrong, when the answer is spread across four tables nobody joins:
`SystemRun` (what the pipeline did), `ToolCall` (what its platforms said),
`AssuranceEvent` (what the validator did to the draft) and `Approval` (whether
a person ever decided). Reading one of those tells you an outcome; reading the
four in time order tells you the cause.

**Three layers, because a breakdown lands in exactly one of them.**

* *functionality* — the call did not come back. A dead token, a 500, a
  refusal because the account never connected that platform.
* *logic* — everything worked and the result was still wrong or refused: a
  run blocked on missing knowledge, a validator catch, a repair that could
  not repair.
* *performance* — it worked and it was slow, or it cost more than it should.

They want different fixes and get confused with each other constantly ("the
system is broken" is usually a blocked run, which is the system working). Every
event this module emits is classified into one, and the classification is on
the record rather than in the reader's head.

**Two rules taken from the rest of this codebase, and they are load-bearing.**

Absence is a third state. A window with no events reports *nothing was
recorded*, never zeros: an account nobody ran and an account that ran cleanly
produce identical zeros and mean opposite things. Every figure that cannot be
computed says which and why rather than being left out — a diagnostic page
with a silent hole in it is read as an all-clear.

And it stores nothing. Every number here is computed from rows other layers
already wrote, so this module can be wrong about an interpretation but never
about a fact, and switching it off loses no data.

**What is deliberately NOT measured, and named in the output as such.** There
is no per-step timing inside a run — `SystemRun` carries `created_at` and
`finished_at` and nothing between — so "which stage was slow" is not
answerable, only "the run took this long". And a tool call records a round
trip, not a queue wait, so a slow tool and a slow provider look the same here.
"""
from __future__ import annotations

import datetime as dt

from . import db

#: A round trip past this is reported as slow. One number, named once, rather
#: than a threshold repeated at three call sites that drift apart.
SLOW_MS = 4000

#: A run open longer than this without a terminal stage did not finish — it
#: died, or the process that owned it went away. Distinguished from "still
#: running" by the clock, because nothing writes a heartbeat.
STALE_RUN_HOURS = 6

#: Ordered worst-first. The log sorts by time, but a filter offers these in the
#: order somebody triaging actually wants them.
LEVELS = ("fail", "warn", "ok", "info")

#: Which layer a breakdown belongs to. See the module docstring — a blocked run
#: is `logic` and NOT a failure, and conflating the two is why "it's broken"
#: gets reported for a system that is refusing exactly as designed.
LAYERS = ("functionality", "logic", "performance")

_TERMINAL = ("sent", "approved", "blocked", "failed")


def _since(days: int) -> dt.datetime:
    return db.utcnow() - dt.timedelta(days=max(1, days))


def _scope(q, model, tenant: str):
    """One place decides what "this account" means for a diagnostic query.

    `tenant=""` means every account and is only ever reached by asking for it
    by name in the console — see `admin_ui.ALL`. It is not the fallback for an
    unset value, because a page pooling five clients' failures under one
    client's heading is the defect this whole pass exists to close.
    """
    return q.filter(model.tenant == tenant) if tenant else q


# ---------------------------------------------------------------------------
# Per-system health
# ---------------------------------------------------------------------------

def health(tenant: str = "", days: int = 30) -> dict:
    """One row per installed system: did it run, did it finish, did it work.

    Runs are counted by stage rather than reduced to a pass rate. `blocked` and
    `failed` are kept apart on purpose: a blocked run is the pipeline refusing
    a named missing thing, which is the design working and points at the
    knowledge base; a failed run is an exception, which points at the code or a
    connection. One percentage covering both would send you to the wrong place.
    """
    from . import systems as sysmod

    since = _since(days)
    with db.SessionLocal() as s:
        q = _scope(s.query(db.SystemRun).filter(
            db.SystemRun.created_at >= since), db.SystemRun, tenant)
        runs = q.all()
        sq = _scope(s.query(db.System), db.System, tenant)
        rows = sq.order_by(db.System.tenant, db.System.key).all()
        s.expunge_all()

    by_system: dict[str, list] = {}
    for r in runs:
        by_system.setdefault(r.system_id, []).append(r)

    now = db.utcnow()
    out = []
    for sysrow in rows:
        mine = by_system.pop(sysrow.id, [])
        stages: dict[str, int] = {}
        for r in mine:
            stages[r.stage or "brief"] = stages.get(r.stage or "brief", 0) + 1
        # Milliseconds, not seconds. Rounded to seconds, every run that took
        # under a second reported "0s median · 0s slowest", which reads as a
        # measurement that is not working rather than as a fast pipeline --
        # and a number a reader distrusts is worse than no number.
        durations = [
            max(0, int((db.as_utc(r.finished_at)
                        - db.as_utc(r.created_at)).total_seconds() * 1000))
            for r in mine if r.finished_at and r.created_at]
        # A run with no terminal stage and no finish, older than the window
        # that any real run takes, did not end — it was lost. That is a
        # different finding from "failed", which at least recorded why.
        stuck = [r for r in mine
                 if (r.stage or "") not in _TERMINAL and not r.finished_at
                 and (now - db.as_utc(r.created_at)).total_seconds()
                 > STALE_RUN_HOURS * 3600]
        last = max((db.as_utc(r.created_at) for r in mine), default=None)
        errs = [r for r in mine if (r.error or "").strip()]
        out.append({
            "tenant": sysrow.tenant,
            "key": sysrow.key,
            "name": sysrow.name or sysrow.key,
            "status": sysrow.status or "designed",
            "autonomy": sysrow.autonomy or "shadow",
            "runs": len(mine),
            "stages": dict(sorted(stages.items(), key=lambda kv: -kv[1])),
            "blocked": stages.get("blocked", 0),
            "failed": stages.get("failed", 0),
            "decided": sum(1 for r in mine if r.decision),
            "unfinished": len(stuck),
            "last_run": last.isoformat() if last else None,
            "last_error": (errs[-1].error or "")[:200] if errs else "",
            "median_ms": (sorted(durations)[len(durations) // 2]
                          if durations else None),
            "slowest_ms": max(durations) if durations else None,
            # Named rather than omitted: a system with no timed run is not a
            # fast system, and a blank cell reads like one.
            "timing_note": ("" if durations else
                            "no run in this window reached a finish, so "
                            "duration cannot be computed"),
            "verdict": _verdict(len(mine), stages, len(stuck)),
        })

    # Runs whose system row is gone. Never silently dropped: a run filed
    # against an id nothing owns is itself the finding — a system was deleted
    # under a live pipeline, or a run is being written with the wrong id.
    orphans = [{"system_id": sid, "runs": len(rs),
                "tenant": rs[0].tenant if rs else "",
                "last": max((db.as_utc(r.created_at) for r in rs)).isoformat()}
               for sid, rs in by_system.items()]

    return {"tenant": tenant, "days": days, "systems": out,
            "orphan_runs": orphans,
            "note": ("" if rows else
                     "no system is installed on this account, so there is "
                     "nothing here to be working or broken")}


def _verdict(n: int, stages: dict, stuck: int) -> str:
    """One line a person can act on, or an admission that there is none."""
    if not n:
        return "nothing ran in this window — this is not a clean bill of health"
    if stuck:
        return f"{stuck} run(s) never finished — check the worker"
    if stages.get("failed"):
        return f"{stages['failed']} run(s) raised — a connection or the code"
    if stages.get("blocked"):
        return (f"{stages['blocked']} run(s) refused on something missing — "
                f"working as designed, fix from the knowledge queue")
    return "ran clean"


# ---------------------------------------------------------------------------
# Platforms — the functionality layer, and the only real performance signal
# ---------------------------------------------------------------------------

def platforms(tenant: str = "", days: int = 30) -> dict:
    """What the client's own systems said back, and how long they took.

    Failure RATE leads rather than failure count, because a provider failing
    most of the time is a broken connection and one failing occasionally is the
    internet, and a raw count buries the first under the second.
    """
    since = _since(days)
    with db.SessionLocal() as s:
        rows = _scope(s.query(db.ToolCall).filter(db.ToolCall.at >= since),
                      db.ToolCall, tenant).all()
        s.expunge_all()

    if not rows:
        return {"tenant": tenant, "days": days, "calls": 0, "providers": [],
                "slow": [],
                "note": ("no tool call was recorded in this window — the "
                         "platforms were not reached, which is not the same "
                         "as them being healthy")}

    prov: dict[str, dict] = {}
    tool: dict[str, dict] = {}
    for r in rows:
        ms = int(r.ms) if (r.ms or "").isdigit() else 0
        t = tool.setdefault(r.tool or "?", {"calls": 0, "failed": 0, "ms": []})
        t["calls"] += 1
        if r.ok != "yes":
            t["failed"] += 1
        if ms:
            t["ms"].append(ms)
        if not r.provider:
            continue        # our own tables say nothing about their stack
        p = prov.setdefault(r.provider, {"calls": 0, "failed": 0, "ms": [],
                                         "last_error": ""})
        p["calls"] += 1
        if r.ok != "yes":
            p["failed"] += 1
            p["last_error"] = p["last_error"] or (r.error or "")[:200]
        if ms:
            p["ms"].append(ms)

    def _timed(d: dict) -> dict:
        m = sorted(d.pop("ms"))
        return {**d,
                "median_ms": m[len(m) // 2] if m else None,
                "slowest_ms": m[-1] if m else None,
                # A call recorded with no duration is not a fast call.
                "timed": len(m)}

    providers = sorted(
        ({"provider": k, **_timed(v),
          "failure_rate": round(v["failed"] / v["calls"], 3)}
         for k, v in prov.items()),
        key=lambda x: (-x["failure_rate"], -x["calls"]))

    slow = sorted(
        ({"tool": k, **_timed(v)} for k, v in tool.items()),
        key=lambda x: -(x["median_ms"] or 0))
    slow = [t for t in slow if (t["median_ms"] or 0) >= SLOW_MS][:10]

    return {"tenant": tenant, "days": days, "calls": len(rows),
            "providers": providers, "slow": slow, "slow_after_ms": SLOW_MS,
            "note": ""}


def spend(tenant: str = "", days: int = 30) -> dict:
    """What the model cost this account — the other half of performance.

    Reported beside latency deliberately: "slow" and "expensive" are the two
    ways a working system is still a problem, and they are usually the same
    run seen twice.
    """
    from . import usage
    rep = usage.report(days=days, tenant=tenant)
    return {"calls": rep.get("calls", 0),
            "cost_usd": rep.get("est_cost_usd", 0),
            "projected_monthly_usd": rep.get("projected_monthly_usd", 0),
            "cache_hit_rate_pct": rep.get("cache_hit_rate_pct", 0),
            "by_purpose": rep.get("by_purpose", {}),
            "note": ("" if rep.get("calls") else
                     "no model call was attributed to this account in the "
                     "window — either nothing ran, or it ran before "
                     "per-client attribution was wired")}


# ---------------------------------------------------------------------------
# The log — four tables, one timeline
# ---------------------------------------------------------------------------

def events(tenant: str = "", days: int = 7, level: str = "",
           system: str = "", limit: int = 200) -> list[dict]:
    """Everything that happened, newest first, classified and filterable.

    Merged in Python rather than in SQL: these are four unrelated tables with
    four different time columns, and a UNION over them would have to agree on
    a shape they do not share. The window bounds the cost — a diagnostic log
    is read over hours and days, never over the life of the account.

    Bodies are never carried. A run's output and an approval's payload are the
    client's own copy; what this shows is a summary and the identifiers to go
    and look with, which is the same rule `toolcalls` keeps one layer down.
    """
    since = _since(days)
    out: list[dict] = []

    with db.SessionLocal() as s:
        names = {r.id: (r.key, r.name or r.key)
                 for r in _scope(s.query(db.System), db.System, tenant).all()}

        for r in _scope(s.query(db.SystemRun).filter(
                db.SystemRun.created_at >= since), db.SystemRun, tenant).all():
            key, name = names.get(r.system_id, ("", "unknown system"))
            stage = r.stage or "brief"
            if stage == "failed":
                lvl, layer = "fail", "functionality"
                detail = (r.error or "raised with no error recorded")[:300]
            elif stage == "blocked":
                lvl, layer = "warn", "logic"
                detail = ("refused on: " + ", ".join(r.blocked_on or [])
                          if r.blocked_on else
                          "blocked without naming what was missing — that is "
                          "itself a defect, the refusal is supposed to name it")
            elif stage in ("sent", "approved"):
                lvl, layer = "ok", "logic"
                detail = f"decision: {r.decision or 'none recorded'}"
            else:
                lvl, layer = "info", "logic"
                detail = f"stage: {stage}"
            out.append(_ev(r.created_at, "run", lvl, layer, r.tenant, key,
                           f"{name} — {stage}", detail, r.id, trigger=r.trigger or ""))

        for r in _scope(s.query(db.ToolCall).filter(db.ToolCall.at >= since),
                        db.ToolCall, tenant).all():
            ms = int(r.ms) if (r.ms or "").isdigit() else 0
            if r.ok != "yes":
                lvl, layer = "fail", "functionality"
                detail = (r.error or "failed with no error recorded")[:300]
            elif ms >= SLOW_MS:
                lvl, layer = "warn", "performance"
                detail = f"{ms} ms — over the {SLOW_MS} ms line"
            else:
                lvl, layer = "ok", "functionality"
                detail = f"{ms} ms" if ms else "no duration recorded"
            out.append(_ev(r.at, "tool", lvl, layer, r.tenant, "",
                           f"{r.tool or '?'}" + (f" · {r.provider}" if r.provider else ""),
                           detail, r.ref or "", source=r.source or ""))

        for r in _scope(s.query(db.AssuranceEvent).filter(
                db.AssuranceEvent.created_at >= since),
                db.AssuranceEvent, tenant).all():
            if r.verdict == "blocked":
                lvl = "fail"
            elif r.caught:
                lvl = "warn"
            else:
                lvl = "ok"
            caught = ", ".join(r.caught or []) or "nothing"
            out.append(_ev(r.created_at, "check", lvl, "logic", r.tenant,
                           r.system_key or "",
                           f"{r.source or 'unknown'} — {r.verdict or 'checked'}",
                           f"caught: {caught}", r.run_id or "",
                           attempt=str(r.attempt or "0")))

        for r in _scope(s.query(db.Approval).filter(
                db.Approval.created_at >= since), db.Approval, tenant).all():
            key = names.get(r.system_id, ("", ""))[0]
            lvl = {"denied": "warn", "pending": "info"}.get(r.status or "", "ok")
            out.append(_ev(r.created_at, "approval", lvl, "logic", r.tenant,
                           key, f"{r.kind} — {r.status or 'pending'}",
                           (r.summary or "")[:300], r.run_id or ""))

    if system:
        out = [e for e in out if e["system"] == system]
    if level == "problems":
        # The filter somebody triaging actually wants, and the reason it is
        # one name rather than two clicks: "failures" alone hides the blocked
        # runs and the catches, which are where most real breakdowns are
        # visible first.
        out = [e for e in out if e["level"] in ("fail", "warn")]
    elif level:
        out = [e for e in out if e["level"] == level]
    out.sort(key=lambda e: e["at"], reverse=True)
    return out[:max(1, limit)]


def _ev(when, kind: str, level: str, layer: str, tenant: str, system: str,
        summary: str, detail: str, ref: str, **extra) -> dict:
    return {"at": db.as_utc(when).isoformat() if when else "",
            "kind": kind, "level": level, "layer": layer,
            "tenant": tenant or "", "system": system or "",
            "summary": summary, "detail": detail, "ref": ref or "",
            **{k: v for k, v in extra.items() if v}}


def report(tenant: str = "", days: int = 7, level: str = "",
           system: str = "", limit: int = 200) -> dict:
    """Everything the Diagnostics tab shows, in one call.

    Assembled from the record and calling NOTHING — the same rule
    `client_report.assemble` keeps. Opening a diagnostics page must not be the
    moment a dead token is discovered: a page that half-fails while reporting
    on failures is worse than one built from what was already written down.
    """
    # Read once, filter in memory. The counts beside each filter have to be
    # of the UNFILTERED window or the chips agree with nothing -- pick
    # "failures" and the warnings chip would read 0, because there are no
    # warnings among failures. So the level filter is applied after counting
    # rather than by a second query.
    everything = events(tenant, days, system=system, limit=limit)
    counts = {lv: sum(1 for e in everything if e["level"] == lv) for lv in LEVELS}
    layers = {ly: sum(1 for e in everything if e["layer"] == ly) for ly in LAYERS}
    if level == "problems":
        ev = [e for e in everything if e["level"] in ("fail", "warn")]
    elif level:
        ev = [e for e in everything if e["level"] == level]
    else:
        ev = everything
    return {"tenant": tenant, "days": days, "level": level, "system": system,
            "health": health(tenant, days),
            "platforms": platforms(tenant, days),
            "spend": spend(tenant, days),
            "events": ev, "counts": counts, "layers": layers,
            "truncated": len(ev) >= limit,
            "silent": not ev,
            "note": ("nothing at all was recorded for this account in the "
                     "window — no run, no tool call, no check and no "
                     "approval. That is a finding about the plumbing, not a "
                     "clean report" if not ev else "")}
