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

from sqlalchemy import or_

from . import db


#: Formats whose body IS the deliverable, kept whole however short. A reply
#: or a report is summarised by its ledger row; an article and a campaign are
#: the thing itself, and there may be nowhere else they exist.
ARTIFACT_FORMATS = ("cms_article", "esp_campaign", "cms_page")
# Campaign emails are NOT in that tuple on purpose: `emit` carries the
# validated COPY, and the reviewable artifact — the rendered HTML — is only
# final after render/personalize/rehost. The campaign path writes its own
# ArtifactBody at the end of the run (skill_pack, review-before-push), and
# two writers for one artifact would race over `draft_body`.


def record(tenant: str, system_key: str, *, situation: str = "",
           entity_key: str = "", audience_key: str = "",
           objection_id: str = "", claim_ids: list[str] | None = None,
           media_ids: list[str] | None = None, theme: str = "",
           angle: str = "", format: str = "", status: str = "draft",
           blocked_on: list[str] | None = None, destination: str = "",
           body: str = "", conversation_id: str = "", touch_id: str = "",
           run_id: str = "", lookups: list[str] | None = None,
           shape: list[str] | None = None,
           meta: dict | None = None) -> db.Output:
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
        lookups=list(lookups or []),
        media_ids=list(media_ids or []), theme=theme, angle=angle,
        shape=list(shape or []),
        format=format, status=status, blocked_on=list(blocked_on or []),
        destination=destination, body=body[:2000],
        body_hash=hashlib.sha256(body.lower().encode()).hexdigest()[:32]
        if body else "",
        conversation_id=conversation_id, touch_id=touch_id)
    with db.SessionLocal() as s:
        s.add(row)
        # FLUSH, not a second commit. `row.id` is needed to key the artifact
        # and a flush assigns it without ending the transaction — committing
        # twice expired this row's attributes, and since `record` returns it
        # detached, every caller then hit DetachedInstanceError on `.id`. One
        # transaction, one commit, both rows or neither.
        s.flush()
        # THE ARTIFACT ITSELF, whole, when there is one.
        #
        # `body[:2000]` above is deliberate and stays — this table is a ledger
        # of decisions and its queries depend on staying narrow. But an email
        # or article that is drafted, checked and approved with no CMS or ESP
        # connected then existed nowhere in full: the run said "1 item(s)" and
        # the item was a summary of itself. Kept beside the row rather than in
        # it, and only for things that ARE artifacts — a rendered body with a
        # format behind it, not every reply.
        # An ARTICLE is kept whatever its length. The `> 2000` guard was
        # there to stop every short reply being copied, and it also threw away
        # the short article — which is the case this table exists for, since
        # an account with no CMS has nowhere else for it to live. Format
        # first, length only as the catch-all for everything else.
        if body and format and "<" in body and (
                format in ARTIFACT_FORMATS or len(body) > 2000):
            s.add(db.ArtifactBody(
                tenant=tenant, output_id=row.id, run_id=run_id,
                system_key=system_key, format=format,
                destination=destination, body=body, draft_body=body,
                # Identity travels WITH the thing, from birth. Kept on the
                # approval too until every consumer reads it from here.
                meta=dict(meta or {}),
                bytes=len(body)))
        s.commit()
        s.refresh(row)
        s.expunge_all()
    return row


def publish(tenant: str, output_id: str, destination: str = "") -> str:
    """Mark an output as gone out, and credit the assets that carried it.

    Refuses if any attached asset is reference-only. Publishing is the last
    place the distinction can still be caught, and catching it here rather than
    trusting whoever attached the media is the difference between a rule and a
    convention — the media on an output may have been chosen by a generator
    several steps upstream.

    Usage is recorded as a side effect of publishing rather than as its own
    step, because a signal that has to be remembered is a signal that will be
    missing exactly when somebody asks which creative actually worked.
    """
    from . import kb
    with db.SessionLocal() as s:
        row = (s.query(db.Output)
               .filter(db.tenant_filter(db.Output, tenant),
                       db.Output.id == output_id).first())
        if not row:
            return "No such output for this account."
        media = list(row.media_ids or [])

    for aid in media:
        ok, why = kb.may_publish(aid)
        if not ok:
            return (f"Not published — the attached asset cannot go out: {why}")

    with db.SessionLocal() as s:
        row = (s.query(db.Output)
               .filter(db.tenant_filter(db.Output, tenant),
                       db.Output.id == output_id).first())
        row.status, row.published_at = "published", db.utcnow()
        if destination:
            row.destination = destination
        s.commit()
    for aid in media:
        kb.mark_asset_used(aid, destination)
    return "Published." + (f" {len(media)} asset(s) credited." if media else "")


def delivered(tenant: str, output_id: str, destination: str) -> bool:
    """Correct `destination` to where the artifact ACTUALLY landed.

    **This is not `publish`.** It does not touch `status`, and it must not: for
    a campaign the thing this system creates is a DRAFT in the sending
    platform, and the owner launches it there. Approving one means "reviewed",
    which `apply_decision` goes out of its way to say — calling it published
    here would undo that in the one table anybody later queries.

    It exists because `destination` was written at `emit` time, roughly ninety
    lines before the ESP call that may refuse, raise, or be skipped entirely.
    Every campaign row therefore read `esp:omnisend` whether or not anything
    reached Omnisend, so the column recorded an INTENTION and was indexed,
    displayed and believed as an outcome. A row that names a campaign id can be
    checked; a row that says the draft was never made is a fact somebody can
    act on. Both are worth more than a uniform claim that is sometimes false.
    """
    with db.SessionLocal() as s:
        row = (s.query(db.Output)
               .filter(db.tenant_filter(db.Output, tenant),
                       db.Output.id == output_id).first())
        if not row:
            return False
        row.destination = destination
        s.commit()
    return True


#: Statuses that are NOT a send. `repaired` is the trap: it marks a rejected
#: attempt whose SUCCESSOR passed, so the email it describes was never seen by
#: anybody — but it keeps `angle` and `format` and loses `theme` and `shape`,
#: which makes it look exactly like a real send with an empty intent. Counting
#: one is counting a draft the validator threw away.
NOT_A_SEND = ("blocked", "superseded", "repaired")


def audiences_written_to(tenant: str, *, days: int = 90,
                         fmt: str = "campaign_email") -> list[str]:
    """Every cohort this account has actually sent to in the window.

    Read from the rows rather than from the catalogue, so a segment that was
    written to and later removed from `segments.CATALOG` still shows up. A
    strategy view built only from the catalogue would quietly omit exactly the
    sends nobody remembers making.
    """
    since = db.utcnow() - dt.timedelta(days=days)
    with db.SessionLocal() as s:
        rows = (s.query(db.Output.audience_key, db.Output.angle)
                .filter(db.tenant_filter(db.Output, tenant),
                        db.Output.format == fmt,
                        db.Output.created_at >= since,
                        db.Output.status.notin_(NOT_A_SEND)).all())
    return sorted({(aud or ang or "") for aud, ang in rows} - {""})


def sends_to(tenant: str, audience_key: str, *, days: int = 90,
             fmt: str = "campaign_email") -> list[dict]:
    """What this list has actually been sent, in order, with the gaps.

    The question the ledger has always held the answer to and never been asked:
    for one audience over a window, which intents went out, about which
    products, drawing on which proof, at what spacing. Every field was already
    on the row — `record` has taken all of them since it was written — but for
    a campaign three of them were never passed, so the answer came back empty
    in a way that looked like "nothing was sent" rather than "nobody wrote it
    down".

    Matched on `audience_key` OR `angle`. `angle` carried the segment for every
    campaign row written before `audience_key` was passed, and a strategy read
    that silently began at the fix would show a brand with no history — the
    most misleading possible answer to "what have we been telling these
    people". Both are read until the old rows age out of every window.

    `gap_days` is from the PREVIOUS send in the list, and is None on the
    earliest — the spacing before it is outside the window and unknown, which
    is different from zero.
    """
    since = db.utcnow() - dt.timedelta(days=days)
    with db.SessionLocal() as s:
        rows = (s.query(db.Output)
                .filter(db.tenant_filter(db.Output, tenant),
                        db.Output.format == fmt,
                        db.Output.created_at >= since,
                        or_(db.Output.audience_key == audience_key,
                            db.Output.angle == audience_key),
                        db.Output.status.notin_(NOT_A_SEND))
                .order_by(db.Output.created_at.asc()).all())
        out, prev = [], None
        for r in rows:
            at = db.as_utc(r.created_at)
            theme_intent, _, theme_fmt = str(r.theme or "").partition("|")
            out.append({
                "output_id": r.id,
                "at": at,
                "gap_days": None if prev is None else round(
                    (at - prev).total_seconds() / 86400, 1),
                # `situation` is where the intent is filed now; `theme` is where
                # it was filed before, and still is. Reading both means the
                # window does not go blank across the change.
                "intent": (r.situation or theme_intent or ""),
                "shape_format": theme_fmt,
                "entity_key": r.entity_key or "",
                "claim_ids": list(r.claim_ids or []),
                "angle": r.angle or "",
                "shape": list(r.shape or []),
                "media_ids": list(r.media_ids or []),
                "status": r.status,
                "destination": r.destination or "",
            })
            prev = at
    return out


def confirm_sent(tenant: str, output_id: str, *, at=None,
                 outcome: dict | None = None) -> dict:
    """The platform says this went out. Record that, and what it did.

    **Not `publish`, and the difference is the whole point.** `publish` is us
    deciding to send something, so it refuses when an attached asset is
    reference-only — that is the last place the decision can still be caught.
    This is a REPORT that a send already happened, from the platform that did
    it. Refusing here would change nothing about the world and would leave the
    ledger claiming an email was never sent that a thousand people received.

    So it records, and if something went out that should not have, it says so
    loudly rather than quietly declining. A rights problem discovered after
    the fact is still a rights problem somebody has to act on.

    Assets are NOT re-credited. `mark_asset_used` increments a counter and the
    draft path already counted this one; what goes on the asset here is
    `record_asset_outcome` — feedback signal two, the one that exists to say
    which photograph actually earned its opens.
    """
    from . import kb
    warn: list[str] = []
    with db.SessionLocal() as s:
        row = (s.query(db.Output)
               .filter(db.tenant_filter(db.Output, tenant),
                       db.Output.id == output_id).first())
        if not row:
            return {"ok": False, "why": "No such output for this account."}
        media = list(row.media_ids or [])
        row.outcome = {**(row.outcome or {}), **(outcome or {}),
                       "confirmed_at": db.utcnow().isoformat()}
        # `published` at last, and from the only source entitled to say so.
        # Until now this status was written on the reply path alone, so
        # `used_recently` and `is_repeat` were blind to every campaign email
        # ever sent — the anti-repeat half of this table could not see the
        # half of the programme that goes out at scale.
        if row.status != "published":
            row.status = "published"
            row.published_at = at or db.utcnow()
        s.commit()

    for aid in media:
        ok, why = kb.may_publish(aid)
        if not ok:
            warn.append(f"asset {aid[:8]} went out and should not have: {why}")
        if outcome:
            kb.record_asset_outcome(aid, "email", dict(outcome))
    return {"ok": True, "warnings": warn, "assets": len(media)}


# ---------------------------------------------------------------------------
# 1. Anti-repeat
# ---------------------------------------------------------------------------

def perishable(tenant: str, conversation_id: str = "",
               within_days: int = 90) -> list[dict]:
    """Past replies whose live facts have gone stale, and which ones.

    This is the join that closes Gomeh's cup. `resolve` pulls prior
    correspondence into the bundle for a follow-up, and it arrives as prose —
    "we told them it is out of stock" reads exactly as true in September as it
    was in August. Nothing in a sentence says which half of it was a reading
    from a store and which half was a fact about the brand.

    So the OUTPUT is asked instead of the sentence. Every lookup that fed a
    body has a half-life declared in `lookups.STALE_AFTER_HOURS`; past it, that
    reply may not be repeated without checking. The reply is not hidden and not
    corrected — it is flagged, because what was said is a fact about the
    conversation and stays true no matter what the stock does now.
    """
    from .lookups import STALE_AFTER_HOURS
    since = db.utcnow() - dt.timedelta(days=within_days)
    out = []
    with db.SessionLocal() as s:
        q = (s.query(db.Output)
             .filter(db.Output.tenant == tenant,
                     db.Output.created_at >= since)
             .order_by(db.Output.created_at.desc()))
        if conversation_id:
            q = q.filter(db.Output.conversation_id == conversation_id)
        for row in q.limit(50).all():
            used = list(row.lookups or [])
            if not used:
                continue        # nothing live went in; the reply keeps
            age_h = (db.utcnow() - db.as_utc(row.created_at)).total_seconds() / 3600
            stale = [t for t in used
                     if age_h > STALE_AFTER_HOURS.get(t, float("inf"))]
            if not stale:
                continue
            out.append({
                "output_id": row.id,
                "said_on": db.as_utc(row.created_at).date().isoformat(),
                "hours_old": round(age_h),
                "stale_lookups": stale,
                "body": (row.body or "")[:160],
                "warning": ("this reply quoted "
                            + ", ".join(t.replace("_", " ") for t in stale)
                            + " — true when it was sent, and not to be "
                              "repeated without reading it again")})
    return out


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
