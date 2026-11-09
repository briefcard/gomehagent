"""Stage reports — what each pipeline stage did, per run (INITIATIVE-review-surface §3.A).

Owner, 2026-11-07: *"We need to be able to clearly understand what AI is
crawling and determining."* Every stage already computed its own account —
the harvest returns pages discovered / read / skipped-and-why and claims
proposed / dropped-and-why — and it lived only in a job's result blob. This
keeps one row per stage per run, so the Overview can say, for an account:
what was read, what was found, what was dropped and why, and what it cost.

Recording never fails the stage it records (`record` swallows its own errors).
"""
from __future__ import annotations

import collections
import datetime as dt
import uuid

from . import db

STAGES = ("crawl", "read", "record", "group")
STAGE_LABEL = {
    "crawl": "Crawl — pages found and fetched",
    "read": "Read — claims taken off the pages (the model)",
    "record": "Record — who / what / where / when, derived by code",
    "group": "Group — the same claim worded differently, or inconsistently",
}


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def new_run() -> str:
    return uuid.uuid4().hex


def record(tenant: str, stage: str, *, run_id: str = "", started_at=None,
           n_in: int = 0, n_out: int = 0, dropped: dict | None = None,
           cost_usd: float = 0.0, details: dict | None = None) -> None:
    try:
        with db.SessionLocal() as s:
            s.add(db.StageReport(
                tenant=tenant, stage=stage, run_id=run_id or new_run(),
                started_at=started_at, finished_at=now(), n_in=int(n_in or 0),
                n_out=int(n_out or 0),
                dropped={str(k): int(v) for k, v in (dropped or {}).items() if v},
                cost_usd=round(float(cost_usd or 0), 4), details=details or {}))
            s.commit()
    except Exception:  # noqa: BLE001 — accounting never breaks the work
        pass


def cost_between(tenant: str, start, end=None, purposes: tuple[str, ...] = ()) -> float:
    """Model spend attributed to this account between two instants."""
    from . import usage
    end = end or now()
    with db.SessionLocal() as s:
        q = s.query(db.Usage).filter(db.Usage.tenant == tenant, db.Usage.at >= start,
                                     db.Usage.at <= end)
        if purposes:
            q = q.filter(db.Usage.purpose.in_(purposes))
        total = 0.0
        for r in q.all():
            total += usage._cost(r.model or "", int(r.input_tokens or 0), int(r.output_tokens or 0),
                                 int(r.cache_read or 0), int(r.cache_write or 0))
    return round(total, 4)


def from_harvest(tenant: str, res: dict, started_at, run_id: str) -> None:
    """The harvest's own result, kept as two stage reports."""
    if not isinstance(res, dict) or res.get("error"):
        return
    skipped = collections.Counter()
    for sk in res.get("skipped_examples") or []:
        why = str(sk.get("why") or "")
        skipped["unchanged since last read" if why.startswith("unchanged") else
                ("could not be fetched" if why.startswith(("HTTP", "Error", "Timeout")) else why[:60])] += 1
    crawl_drop = {
        "skipped (all reasons)": int(res.get("pages_skipped") or 0),
        "unchanged since last read": int(res.get("pages_unchanged") or 0),
        "template copies not read": int(res.get("template_pages_skipped") or 0),
        "needs a browser to read": int(res.get("pages_needing_render_count") or 0),
    }
    record(tenant, "crawl", run_id=run_id, started_at=started_at,
           n_in=int(res.get("pages_discovered") or res.get("pages_enumerated") or 0),
           n_out=int(res.get("pages_read") or 0), dropped=crawl_drop,
           details={"pages_known": res.get("pages_known"),
                    "pages_remaining": res.get("pages_remaining"),
                    "pages_by_tier": res.get("pages_by_tier") or {},
                    "partly_read": int(res.get("truncated_page_count") or 0),
                    "documents_read": int(res.get("documents_read_count") or 0),
                    "sources": [s.get("label") or s.get("url") for s in (res.get("sources") or [])
                                if isinstance(s, dict)]})
    read_drop = dict(res.get("dropped_by_reason") or {})
    read_drop["banned phrase"] = len(res.get("rejected_for_banned_claim") or [])
    read_drop["not word-for-word on the page"] = int(res.get("not_verbatim_count") or 0)
    read_drop["refused when filing"] = int(res.get("write_refused_count") or 0)
    record(tenant, "read", run_id=run_id, started_at=started_at,
           n_in=int(res.get("pages_read") or 0),
           n_out=int(res.get("filed_count") or res.get("proposed_count") or 0),
           dropped=read_drop,
           cost_usd=cost_between(tenant, started_at, purposes=("harvest_extract",)),
           details={"proposed": int(res.get("proposed_count") or 0),
                    "filed": int(res.get("filed_count") or 0),
                    "already_on_file": int(res.get("corroborated_count") or 0),
                    "figures_found": int(res.get("statements_found") or 0),
                    "figures_not_understood": int(res.get("unaccounted_figures") or 0),
                    "extractor": res.get("extractor") or ""})


def latest(tenant: str, limit: int = 12) -> list[dict]:
    """The most recent reports, newest first."""
    with db.SessionLocal() as s:
        rows = (s.query(db.StageReport).filter(db.StageReport.tenant == tenant)
                .order_by(db.StageReport.finished_at.desc()).limit(limit).all())
        return [{"stage": r.stage, "label": STAGE_LABEL.get(r.stage, r.stage), "run_id": r.run_id,
                 "started_at": r.started_at.isoformat() if r.started_at else "",
                 "finished_at": r.finished_at.isoformat() if r.finished_at else "",
                 "in": r.n_in, "out": r.n_out, "dropped": dict(r.dropped or {}),
                 "cost_usd": r.cost_usd or 0.0, "details": dict(r.details or {})} for r in rows]


def last_of_each(tenant: str) -> dict:
    out = {}
    for r in latest(tenant, limit=60):
        out.setdefault(r["stage"], r)
    return out
