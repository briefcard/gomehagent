"""THE OWNER'S DIAGNOSTICS, ANSWERED IN THE WORKER.

Owner, 2026-10-01: "This needs to be the approach with every single heavy
operation." Five addresses the owner types — ask an agent, the nightly
sweep on demand, a brand voice proposed from the site, a reply rehearsed on
real threads, the vocabulary read by a model — did their model's work inside
the request. Each now queues a `probe` job; the route answers with where the
result will be (`/admin/probe/<id>`), and the whole answer is kept on the
row (`jobs.KINDS["probe"]["keep_result"]`).
"""
from __future__ import annotations


def run(tenant: str = "", *, name: str, params: dict | None = None, progress=None) -> dict:
    """The queue's door: one named diagnostic, with the parameters it was
    asked with."""
    fn = PROBES.get(name)
    if fn is None:
        return {"ok": False, "status": "failed", "why": f"no such diagnostic: {name}"}
    return fn(tenant, **dict(params or {}))


def _ask(tenant: str, *, q: str, role: str = "admin", thread: str = "") -> dict:
    """An agent, asked over HTTP — its own conversation thread per role."""
    from . import kernel
    from .roles import get as get_role
    thread_key = f"{role}:{thread}" if thread else role
    return {"ok": True, "answer": kernel.run(get_role(role), q, thread=thread_key)}


def _sweep(tenant: str, *, days: int = 7) -> dict:
    """The nightly sweep, delivered as the scheduled job would."""
    from . import correlate
    got = correlate.nightly(max(1, min(int(days), 90)))
    return got if isinstance(got, dict) else {"ok": True, "result": got}


def _propose_voice(tenant: str, *, limit: int = 25) -> dict:
    """A brand voice suggested from what this account has published. Writes
    nothing — `set_brand` is still the only way a voice lands."""
    from . import voice as vc
    texts, how = vc.gather(tenant, limit=int(limit))
    if not texts:
        return {"tenant": tenant, "error": how, "applied": False}
    out = vc.propose(tenant, texts)
    out["source"] = how
    return out


def _draft_test(tenant: str, *, message_id: str = "", pick: str = "", limit: int = 3) -> dict:
    """A reply rehearsed on REAL threads from this inbox, with the working.
    Nothing is sent and nothing is filed on the thread."""
    from . import db, replies, responder, systems
    with db.SessionLocal() as s:
        q = (s.query(db.EmailLog)
             .filter(db.tenant_filter(db.EmailLog, tenant),
                     db.EmailLog.body_excerpt.isnot(None)))
        if message_id:
            q = q.filter(db.EmailLog.gmail_message_id == message_id)
        if pick:
            q = q.filter(db.EmailLog.category == pick)
        rows = q.order_by(db.EmailLog.seen_at.desc()).limit(int(limit)).all()
        s.expunge_all()
    if not rows:
        return {"error": "no thread with a stored body matches — run "
                         "/admin/archive_fetch first, or widen `pick`"}
    out = []
    for r in rows:
        body = (r.body_excerpt or "").strip()
        # DRAFT UNDER THE SYSTEM THAT OWNS THIS MAIL: a lead is drafted as a
        # lead, and inbox_triage's own mail stays with the service desk.
        _owner = replies.route(r.category or "")
        res = responder.answer(tenant, body[:2000],
                               system_key=(_owner if _owner in systems.CATALOG
                                           else "service_desk"),
                               draft_with_model=True)
        out.append({
            "thread": {"subject": r.subject, "from": r.sender,
                       "bucket": r.category, "when": r.seen_at,
                       "they_wrote": body[:400]},
            "mode": res.get("mode") or res.get("stage") or "answered",
            "grounding": (res.get("grounding") or {}).get("level"),
            "draft": res.get("draft") or "",
            "blocked": res.get("draft_blocked_by") or res.get("blocked_on") or "",
            "validated": res.get("validated"),
            "checks_run": res.get("checks_run", []),
            "prior_threads_used": [
                h.get("subject") for h in
                ((res.get("bundle") or {}).get("correspondence")
                 or (res.get("context") or {}).get("correspondence") or [])],
            "gaps": [g.get("missing") for g in (res.get("gaps") or [])],
        })
    return {"tenant": tenant, "tested": len(out), "results": out,
            "note": ("nothing was sent and nothing was filed on the thread. "
                     "Read `blocked` — a draft the validator threw away is "
                     "the system working, not failing.")}


def _vocabulary(tenant: str) -> dict:
    """The model's pass over the situation vocabulary — two tags meaning the
    same thing in different words, which no lexical measure can see."""
    from . import extract
    return {"tenant": tenant, "model_review": extract.review_vocabulary(tenant)}


PROBES = {"ask": _ask, "sweep": _sweep, "propose_voice": _propose_voice,
          "draft_test": _draft_test, "vocabulary": _vocabulary}
