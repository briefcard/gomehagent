"""What was produced, from which brief, and what happened to it.

One table doing three jobs that would each otherwise need their own store:

    anti-repeat    has this claim been used for this product lately
    attribution    what varied between these two outputs
    hygiene        which claims has nothing ever selected

They are one table because they are one question asked three ways — *which
decisions did we make* — and splitting them would mean three records of the
same event drifting apart.

Nothing here writes an artifact. `body` is a short rendering kept so a human
can see what a row refers to; the ledger is a record of decisions, not a
content store.
"""
from __future__ import annotations

import datetime as dt
import hashlib

from . import db


def record(tenant: str, system_key: str, *, situation: str = "",
           entity_key: str = "", audience_key: str = "",
           objection_id: str = "", claim_ids: list[str] | None = None,
           media_ids: list[str] | None = None, theme: str = "",
           angle: str = "", format: str = "", status: str = "draft",
           blocked_on: list[str] | None = None, destination: str = "",
           body: str = "", conversation_id: str = "", touch_id: str = "",
           run_id: str = "") -> db.Output:
    """File one output and the brief behind it.

    A **blocked** run is recorded too, and that is the point of taking
    `status` rather than assuming success. `SystemRun` already learned this —
    it records blocked and failed runs so `blocked_reasons()` can rank the KB
    backlog by how often each gap actually cost an output. A ledger of only
    the things that worked cannot tell you what stopped.
    """
    body = (body or "").strip()
    row = db.Output(
        tenant=tenant, system_key=system_key, run_id=run_id,
        situation=situation, entity_key=entity_key, audience_key=audience_key,
        objection_id=objection_id, claim_ids=list(claim_ids or []),
        media_ids=list(media_ids or []), theme=theme, angle=angle,
        format=format, status=status, blocked_on=list(blocked_on or []),
        destination=destination, body=body[:2000],
        body_hash=hashlib.sha256(body.lower().encode()).hexdigest()[:32]
        if body else "",
        conversation_id=conversation_id, touch_id=touch_id)
    with db.SessionLocal() as s:
        s.add(row)
        s.commit()
        s.refresh(row)
        s.expunge_all()
    return row


def publish(tenant: str, output_id: str, destination: str = "") -> str:
    with db.SessionLocal() as s:
        row = (s.query(db.Output)
               .filter(db.tenant_filter(db.Output, tenant),
                       db.Output.id == output_id).first())
        if not row:
            return "No such output for this account."
        row.status, row.published_at = "published", db.utcnow()
        if destination:
            row.destination = destination
        s.commit()
    return "Published."


# ---------------------------------------------------------------------------
# 1. Anti-repeat
# ---------------------------------------------------------------------------

def used_recently(tenant: str, claim_id: str, entity_key: str = "",
                  within_days: int = 30, limit: int = 5) -> list[db.Output]:
    """Where this claim has already gone out, so it is not said twice.

    Scoped by entity because reuse is only repetition in the same place: the
    same proof on two different products is doing its job, and the same proof
    on the same product twice in a fortnight is a rut.

    Only PUBLISHED rows count. A blocked draft that mentioned a claim did not
    say it to anybody, and treating it as spent would starve the next run of
    proof it never used.
    """
    since = db.utcnow() - dt.timedelta(days=within_days)
    with db.SessionLocal() as s:
        q = (s.query(db.Output)
             .filter(db.tenant_filter(db.Output, tenant),
                     db.Output.status == "published"))
        if entity_key:
            q = q.filter(db.Output.entity_key == entity_key)
        rows = [r for r in q.order_by(db.Output.created_at.desc()).all()
                if claim_id in (r.claim_ids or [])
                and r.published_at and db.as_utc(r.published_at) >= since]
        s.expunge_all()
        return rows[:limit]


def is_repeat(tenant: str, claim_ids: list[str], entity_key: str = "",
              within_days: int = 30) -> dict:
    """The check a validator makes: would this say the same thing again."""
    hits = {}
    for cid in claim_ids or []:
        prior = used_recently(tenant, cid, entity_key, within_days)
        if prior:
            hits[cid] = [{"output_id": p.id, "at": p.published_at} for p in prior]
    return {"repeat": bool(hits), "claims": hits,
            "within_days": within_days, "entity_key": entity_key}


# ---------------------------------------------------------------------------
# 2. Hygiene
# ---------------------------------------------------------------------------

def unused_claims(tenant: str, min_outputs: int = 20) -> dict:
    """Approved claims nothing has ever selected.

    A claim unused across a real run of outputs is wrong, redundant, or tagged
    for a situation that never comes up — all three are worth knowing and none
    is visible anywhere else.

    `min_outputs` guards the conclusion rather than the list, the same way
    `CALIBRATION_MIN_N` does: with four outputs on file, everything looks
    unused and that means nothing.
    """
    from . import kb
    with db.SessionLocal() as s:
        rows = (s.query(db.Output)
                .filter(db.tenant_filter(db.Output, tenant)).all())
        s.expunge_all()
    used = {c for r in rows for c in (r.claim_ids or [])}
    claims = kb.claim_inventory(tenant)["selectable"]
    never = [{"id": c.id, "claim": c.claim[:90],
              "situations": sorted(c.situations or []),
              "entity_key": c.entity_key or ""}
             for c in claims if c.id not in used]
    return {
        "tenant": tenant, "outputs_on_file": len(rows),
        "enough_to_conclude": len(rows) >= min_outputs,
        "min_outputs": min_outputs,
        "claims": len(claims), "used": len(used & {c.id for c in claims}),
        "never_used": never,
        "note": ("" if len(rows) >= min_outputs else
                 f"{len(rows)} outputs on file — everything looks unused at "
                 f"this volume. Read the list, do not act on the ratio."),
    }


# ---------------------------------------------------------------------------
# 3. Attribution
# ---------------------------------------------------------------------------

BRIEF_FIELDS = ("situation", "entity_key", "audience_key", "objection_id",
                "claim_ids", "media_ids", "theme", "angle", "format")


def diff(tenant: str, a_id: str, b_id: str) -> dict:
    """What varied between two outputs — the whole basis of a hypothesis.

    Comparing rendered text tells you the words changed. Comparing briefs tells
    you *which decision* changed, which is the only thing a next run can act on.
    """
    with db.SessionLocal() as s:
        rows = {r.id: r for r in
                s.query(db.Output)
                .filter(db.tenant_filter(db.Output, tenant),
                        db.Output.id.in_([a_id, b_id])).all()}
        s.expunge_all()
    a, b = rows.get(a_id), rows.get(b_id)
    if not a or not b:
        return {"error": "one or both outputs are not on this account"}

    changed, same = {}, []
    for f in BRIEF_FIELDS:
        va, vb = getattr(a, f), getattr(b, f)
        if isinstance(va, list) or isinstance(vb, list):
            va, vb = sorted(va or []), sorted(vb or [])
        if va != vb:
            changed[f] = {"a": va, "b": vb}
        else:
            same.append(f)
    return {
        "a": a_id, "b": b_id, "varied": changed, "held_constant": same,
        "interpretable": len(changed) == 1,
        "note": ("one field differs — a difference in outcome is "
                 "attributable to it" if len(changed) == 1 else
                 f"{len(changed)} fields differ — an outcome cannot be "
                 f"attributed to any one of them"),
    }


def recent(tenant: str, system_key: str = "", limit: int = 20) -> list[db.Output]:
    with db.SessionLocal() as s:
        q = s.query(db.Output).filter(db.tenant_filter(db.Output, tenant))
        if system_key:
            q = q.filter(db.Output.system_key == system_key)
        rows = q.order_by(db.Output.created_at.desc()).limit(limit).all()
        s.expunge_all()
        return rows
