"""Planners — the top-up half of the workflow layer.

A planner proposes PLANS: it reads catalogs and ledgers and files work in
advance through `systems.open_plan`, and that is all it does. It never
consumes (the tick's other half does that, through every gate), never
invents a value (a field it cannot read from data stays absent and
`plan_complete` names it), and never writes over the owner (`open_plan`'s
carry-forward is structural). Deterministic code, no model call — which
angle to run to which segment is catalog data, not judgement.

One planner, deliberately. `campaign_rollout` proposes on a CALENDAR for
high-value segments, and on live PRESSURE for the common tier — the cohorts
(`cart_abandoners`, `hot_enquiries`, `win_back`) that are never worth a
scheduled campaign and are sometimes worth an urgent one.

**Why not a second planner for moments.** Because there is no second sending
surface for it to use. An Omnisend campaign targets a segment; a plan-per-
person would draft a campaign bound to that person's whole segment, so two
cold carts would become two identical sends to the entire list. The first cut
did exactly that. Moments therefore INFORM this planner rather than running
beside it — one queue, one decision about who gets written to, and no way for
a moment and a campaign to collide, because there is nothing to collide with.

The registry is what the tick and the console's "Propose now" button both
call, so a system gains a planner by adding a row here — never by teaching the
tick a new special case.

Cadence is the owner's number. `DEFAULT_CADENCE` is deliberately
conservative — one campaign per segment per month, a three-week horizon —
and `systems.set_cadence` stores the owner's override on the System row,
editable on the Planned section (a knob that exists only in code is a knob
that does not exist).
"""
from __future__ import annotations

import datetime as dt

from . import db, moments, segments, systems

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


#: Days a segment must rest between campaigns, however loudly the moments are
#: shouting.
#:
#: **This replaces the per-person cap, and the reason matters.** The owner set
#: two-per-person-per-seven-days on 2026-08-24, while the design still believed
#: it could send to one person. It cannot: every send goes to a segment, whose
#: membership Omnisend knows and we do not, so a per-person number is not a
#: rule this side of the wire can enforce — only claim. What IS enforceable is
#: how often a COHORT is written to, so that is what the knob does now.
#:
#: It binds the pressure path specifically. The calendar path already has
#: `per_segment_monthly`, and pressure must never be a way around it: a
#: segment does not earn extra campaigns by having a bad week.
SEGMENT_REST_DAYS = 6
MAX_SEGMENT_REST_DAYS = 60


def _cadence(sysrow, defaults: dict, caps: dict) -> dict:
    """Effective cadence: defaults ← workflow declaration ← the owner's
    System.config, each layer overriding the one before, junk ignored."""
    out = dict(defaults)
    out.update({k: v for k, v in
                (systems.workflow(sysrow.key).get("cadence") or {}).items()
                if k in defaults})
    cfg = ((sysrow.config or {}).get("cadence") or {})
    for k, cap in caps.items():
        try:
            v = int(cfg.get(k, out[k]))
        except (TypeError, ValueError):
            continue
        if 0 < v <= cap:
            out[k] = v
    return out


def cadence_for(sysrow) -> dict:
    """The calendar planner's cadence — horizon and per-segment monthly cap."""
    return _cadence(sysrow, DEFAULT_CADENCE,
                    {"horizon_days": MAX_HORIZON_DAYS,
                     "per_segment_monthly": MAX_PER_SEGMENT_MONTHLY})


def rest_days_for(sysrow) -> int:
    """How long a segment rests between campaigns on the pressure path."""
    return _cadence(sysrow, {"segment_rest_days": SEGMENT_REST_DAYS},
                    {"segment_rest_days": MAX_SEGMENT_REST_DAYS}
                    )["segment_rest_days"]


#: Articles are paced by the month like campaigns, but the unit is different
#: enough to need its own numbers: a cohort tires of being written TO, while a
#: site does not tire of being written ABOUT. The ceiling is higher and the
#: default is still conservative, because the constraint on publishing is
#: rarely appetite and almost always review.
BLOG_CADENCE = {"horizon_days": 45, "articles_monthly": 4}
MAX_ARTICLES_MONTHLY = 30


def blog_cadence_for(sysrow) -> dict:
    return _cadence(sysrow, BLOG_CADENCE,
                    {"horizon_days": MAX_HORIZON_DAYS,
                     "articles_monthly": MAX_ARTICLES_MONTHLY})


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
    """Propose the next campaigns. Two paths into ONE queue.

    **The calendar**, for high-value segments: one per segment per month,
    spaced, so four cohorts do not land in the same inbox week — and ordered
    by how long each has actually gone without, so the earliest slot goes to
    the cohort most owed a send rather than to whichever was typed first.

    **Live pressure**, for the common tier: cart abandoners, warm enquiries,
    win-back. These are deliberately NOT on the calendar — writing to them
    monthly whether or not anything happened is how a list gets tired — and
    they become worth a campaign exactly when a lot of people are in the same
    window at once. `moments.pressure` is what measures that, and
    `_pressure_plans` below is the only thing that reads it.

    Both write through `systems.open_plan` against the same `campaign:` ref
    space and the same monthly cap, which is what makes a collision between
    them impossible rather than merely unlikely: two proposals for one segment
    in one month are one plan, whichever path found it first.

    What each field comes from: `segment` and `goal` are the business-model
    catalog's own key and angle (`segments.CATALOG`), the date is cadence
    arithmetic or the closing window, `entity_key` on the pressure path is
    whatever most of those people were looking at, and `subject` is
    deliberately NOT proposed — no source holds one, so it stays blank for the
    owner to set or the drafter to write, rather than a template pretending to
    be a decision.
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
    # Kept per segment so the pressure pass below sees what the calendar pass
    # just filed — otherwise both could propose for the same cohort in the
    # same run and only the ref collision would save it.
    have_by_segment: dict[str, dict] = {}
    for seg in _by_neglect(sysrow.tenant, got["high_value"]):
        prefix = f"campaign:{sysrow.tenant}:{seg['key']}:"
        have = have_by_segment[seg["key"]] = _existing_by_month(sysrow, prefix)
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
                    have[_month(d)] = have.get(_month(d), 0) + 1
                else:
                    refreshed += 1
                break
            # This month is at its cap — the next candidate is next month's
            # first day inside the horizon, never a denser packing of this
            # one. Strictly month-forward, so the walk always terminates.
            d = _next_month(d)
        slot += dt.timedelta(days=SPACING_DAYS)

    # Now the common tier, against whatever the calendar pass has already
    # claimed. Any segment it has never seen gets its history read on demand.
    for seg in got["common"]:
        have_by_segment.setdefault(
            seg["key"],
            _existing_by_month(sysrow, f"campaign:{sysrow.tenant}:{seg['key']}:"))
    p_made, p_ref, p_why = _pressure_plans(sysrow, cad, have_by_segment)
    return {"ok": True, "proposed": proposed + p_made,
            "refreshed": refreshed + p_ref,
            "from_pressure": p_made,
            "refusals": refusals + p_why}


def _by_neglect(tenant: str, segs: list[dict]) -> list[dict]:
    """High-value cohorts, most-owed-a-send first.

    The planner used to walk the catalogue in its own order and hand out the
    earliest slots in that order, for ever. So the cohort listed first got
    written to first every month regardless of whether it had just been
    written to, and the one listed last drifted — a programme shaped by the
    order somebody typed the segments in.

    Ordering by how long each has actually gone without is the whole of
    "propose against strategy state": the ledger changes, and the planner's
    choice changes with it. Never sent outranks everything, because a cohort
    with no history at all is the most neglected there is.

    A read failure is not a planning failure — an account whose strategy view
    cannot be built still gets its campaigns, in catalogue order, as before.
    """
    try:
        from . import strategy
        seen = {r["segment"]: r["days_since"]
                for r in strategy.read(tenant, days=90)["segments"]}
    except Exception:                                            # noqa: BLE001
        return list(segs)

    def rank(seg: dict):
        d = seen.get(seg["key"])
        # `None` means never sent in the window. Sorting it as "infinitely
        # long ago" is the honest reading and puts it first.
        return (0 if d is None else 1, -(d or 0), seg["key"])
    return sorted(segs, key=rank)


def _nearest_campaign(tenant: str, segment: str, when: dt.date) -> int | None:
    """Days between `when` and the closest campaign to this cohort, either way.

    **Either way** is the whole point, and the first cut got it wrong: it took
    the LATEST ref date and subtracted, so a campaign already scheduled for
    next month came back as "written to -12 days ago" and tripped the rest
    check with a negative number. A plan three days in the future collides
    with a proposal exactly as much as one three days in the past; the
    recipient cannot tell which of the two arrived first.

    Reads plan refs rather than the ledger on purpose: a plan the owner
    SKIPPED was still a decision about that cohort for that week, and
    proposing again two days later is a nag wearing an algorithm.
    """
    prefix = f"campaign:{tenant}:{segment}:"
    with db.SessionLocal() as s:
        rows = (s.query(db.SystemRun.ref)
                .filter(db.SystemRun.tenant == tenant,
                        db.SystemRun.ref.like(prefix + "%")).all())
    gaps = []
    for (ref,) in rows:
        try:
            d = dt.date.fromisoformat((ref or "")[len(prefix):])
        except ValueError:
            continue
        gaps.append(abs((d - when).days))
    return min(gaps) if gaps else None


def _open_plan_ref(tenant: str, segment: str) -> str:
    """The ref of an OPEN plan for this cohort, if one is already queued."""
    prefix = f"campaign:{tenant}:{segment}:"
    refs = sorted(r.ref for r in systems.plans(tenant, "campaign_email")
                  if (r.ref or "").startswith(prefix))
    return refs[0] if refs else ""


def _known_entity(tenant: str, key: str) -> bool:
    """Is this handle actually a thing in our catalogue right now?"""
    from . import kb as _kb
    return any(e.key == key for e in _kb.entities(tenant, available_only=False))


def _pressure_plans(sysrow, cad: dict, have_by_segment: dict) -> tuple[int, int, list]:
    """Propose for the COMMON tier, where and only where the signal is real.

    The `common` cohorts — cart abandoners, warm enquiries, win-back — are
    deliberately not on the calendar: writing to them monthly regardless of
    whether anything happened is how a list gets tired. What makes one worth a
    campaign is that a lot of people are in the same window RIGHT NOW, which
    is exactly what `moments.pressure` measures.

    Four gates, and each one is a way this could otherwise conflict with the
    calendar path or with itself:

    1. **The watcher must be on.** No `moment_email` system, no pressure — an
       account that has not switched moments on does not get campaigns it
       never asked for.
    2. **`ready`** — under `MIN_PRESSURE` nothing is proposed, because a
       segment send on behalf of three people is a message to a thousand about
       something true of three.
    3. **The monthly cap still binds.** Pressure decides WHETHER and WHEN
       inside the allowance; it never buys extra campaigns. A segment does not
       earn more sends by having a bad week.
    4. **The rest period.** However loud the signal, a cohort written to four
       days ago is not written to again today.
    """
    from . import moments as _mo
    if not (systems.find(sysrow.tenant, "moment_email")
            and systems.is_on(systems.find(sysrow.tenant, "moment_email"))):
        return 0, 0, []

    today = dt.date.today()
    rest = rest_days_for(sysrow)
    proposed = refreshed = 0
    refusals: list[str] = []

    for g in _mo.pressure(sysrow.tenant):
        if not g["ready"]:
            continue
        seg = g["segment"]

        # ALREADY QUEUED? Then inform THAT plan rather than filing a second
        # one. This is the case that matters most and it is not rare: for a
        # venue every moment segment is also a high-value calendar segment, so
        # the calendar has usually claimed the cohort already. Adding a second
        # campaign would be the collision this whole design exists to make
        # impossible — so the evidence goes onto the existing plan instead,
        # as the featured entity it may still be missing.
        #
        # `open_plan` with the SAME ref updates only the fields the owner has
        # not edited, so this can never overwrite a decision somebody made.
        queued = _open_plan_ref(sysrow.tenant, seg)
        if queued:
            plan = {"segment": seg}
            if g["top_entity"] and _known_entity(sysrow.tenant, g["top_entity"]):
                plan["entity_key"] = g["top_entity"]
            out = systems.open_plan(sysrow.tenant, sysrow.key, ref=queued,
                                    plan=plan, trigger="moment")
            if out.get("error"):
                refusals.append(out["error"])
                continue
            refreshed += 1
            refusals.append(f"{seg}: {g['people']} people are in a window — "
                            f"attached to the plan already queued for "
                            f"{queued.rsplit(':', 1)[1]} rather than adding a "
                            f"second send")
            _mo.consumed_for(sysrow.tenant, g["moment_ids"], queued)
            continue

        if have_by_segment.get(seg, {}).get(_month(today), 0) >= cad["per_segment_monthly"]:
            refusals.append(f"{seg}: {g['people']} people are in a window, but "
                            f"this cohort is at its monthly cap — pressure "
                            f"does not buy extra sends")
            continue
        near = _nearest_campaign(sysrow.tenant, seg,
                                 today + dt.timedelta(days=LEAD_DAYS))
        if near is not None and near < rest:
            refusals.append(f"{seg}: {g['people']} people are in a window, but "
                            f"another campaign to it is {near} day(s) away and "
                            f"this cohort rests for {rest}")
            continue

        # WHEN: as soon as a plan can honestly be run. Pressure IS urgency,
        # so there is nothing to space out — `LEAD_DAYS` is the floor, and it
        # is a floor rather than a preference because a proposal has to be
        # reviewable before the tick can consume it.
        #
        # And if the window shuts before then, say so rather than filing work
        # that is dead on arrival. It is a real limit worth reading in the
        # refusals: with a two-day lead, a window narrower than two days
        # cannot be served by this path at all.
        slot = today + dt.timedelta(days=LEAD_DAYS)
        closes = g["earliest_expiry"]
        if closes and closes.date() < slot:
            refusals.append(
                f"{seg}: {g['people']} people are in a window that closes "
                f"{closes.date().isoformat()}, before the soonest a reviewable "
                f"plan can run ({slot.isoformat()})")
            continue

        ref = f"campaign:{sysrow.tenant}:{seg}:" + slot.isoformat()
        plan = {"segment": seg}
        if g["top_entity"] and _known_entity(sysrow.tenant, g["top_entity"]):
            # What most of them have in common, handed over as the featured
            # entity. The drafter still owns the copy; this is the subject.
            #
            # CHECKED FIRST, because these keys did not come from our
            # catalogue — the commerce producer files whatever handle Shopify
            # put on the line item, and a store can rename or retire a product
            # without telling us. `open_plan` refuses an unknown entity, and
            # it is right to, so passing one unchecked would throw away the
            # whole plan over a field that was only ever a suggestion. A blank
            # here is already handled: the drafter picks, and records which.
            plan["entity_key"] = g["top_entity"]
        out = systems.open_plan(sysrow.tenant, sysrow.key, ref=ref, plan=plan,
                                planned_for=slot.isoformat(), trigger="moment")
        if out.get("error"):
            refusals.append(out["error"])
            continue
        if out.get("created"):
            proposed += 1
        else:
            refreshed += 1
        have_by_segment.setdefault(seg, {})
        have_by_segment[seg][_month(slot)] = \
            have_by_segment[seg].get(_month(slot), 0) + 1
        _mo.consumed_for(sysrow.tenant, g["moment_ids"], ref)
    return proposed, refreshed, refusals


#: system key -> planner. The tick and the console both resolve through this,
#: so a new planner is a row here and nothing else.
def blog_rollout(sysrow) -> dict:
    """Propose the next articles, off the keyword map, in cluster order.

    `keywords.score` already ranks what is worth writing — striking distance,
    then cluster completion, then demand minus difficulty — so this does not
    re-rank. It applies the ONE rule a score cannot express, and then paces.

    **A support is never planned before its pillar.** A cluster of five
    supports pointing at a page that does not exist is five articles with
    nothing to link to and a head term still unwon; it is also the single
    most common way this work produces motion and no result. When the top of
    the queue is a support whose pillar is still a candidate, the PILLAR is
    filed instead — and the run says so, because silently planning something
    other than the thing that ranked first is the kind of helpfulness nobody
    can audit.

    Everything else is `campaign_rollout`'s shape: one `article:` ref space,
    idempotent per keyword, monthly cap, `open_plan` carrying owner edits
    forward. `angle` is deliberately NOT proposed — no source holds one, and a
    template pretending to be a decision is worse than a blank the drafter
    fills and records.
    """
    from . import keywords
    cad = blog_cadence_for(sysrow)
    today = dt.date.today()
    horizon_end = today + dt.timedelta(days=cad["horizon_days"])

    rows = [r for r in keywords.targets(sysrow.tenant, status="candidate")
            if (r.owner_priority or "") != "muted"]
    # MUTED MEANS NOT PROPOSED, not proposed-and-ranked-last. A keyword the
    # owner has ruled out reappearing at the bottom of every week's queue is
    # a decision he has to make again every week, which is how a queue stops
    # being worked.
    if not rows:
        return {"ok": True, "proposed": 0, "refreshed": 0,
                "refusals": ["no candidate keywords — run keywords.harvest "
                             "first, or every candidate is already planned"]}

    # Who is a pillar, and has it been dealt with. Read once: asking per
    # keyword would be a query per row on a map of several hundred.
    by_cluster_pillar = {r.cluster_key: r for r in keywords.targets(sysrow.tenant)
                         if r.role == "pillar"}

    prefix = f"article:{sysrow.tenant}:"
    have = _existing_by_month(sysrow, prefix)
    proposed = refreshed = 0
    refusals: list[str] = []
    promoted: list[str] = []
    filed: set[str] = set()
    slot = today + dt.timedelta(days=LEAD_DAYS)

    # ORDER FIRST, FILE SECOND. The first cut promoted the pillar in place of
    # the support and moved on, so the highest-priority keyword in the whole
    # map was silently never queued at all — it was CONSUMED by the promotion
    # rather than delayed by it. A pillar goes AHEAD of its support, not
    # instead of it.
    order: list[str] = []
    by_phrase = {r.phrase: r for r in rows}
    for row in rows:                     # already priority-ordered
        if row.role == "support":
            pillar = by_cluster_pillar.get(row.cluster_key)
            if pillar is not None and pillar.status == "candidate" \
                    and pillar.phrase not in order:
                order.append(pillar.phrase)
                by_phrase.setdefault(pillar.phrase, pillar)
                promoted.append(f"{pillar.phrase!r} goes first — "
                                f"{row.phrase!r} supports it and would have "
                                f"nothing to link to")
        if row.phrase not in order:
            order.append(row.phrase)

    for phrase in order:
        target = by_phrase[phrase]
        if target.phrase in filed:
            continue

        while slot <= horizon_end and have.get(_month(slot), 0) >= cad["articles_monthly"]:
            slot = _next_month(slot)     # strictly month-forward: it terminates
        if slot > horizon_end:
            refusals.append(f"horizon full at {cad['articles_monthly']}/month "
                            f"— {len(order) - len(filed)} keyword(s) still waiting")
            break

        out = systems.open_plan(
            sysrow.tenant, sysrow.key,
            ref=prefix + keywords.slug(target.phrase),
            plan={"keyword": target.phrase,
                  "role": target.role or "support",
                  "cluster": target.cluster_key or ""},
            planned_for=slot.isoformat(), trigger="planner")
        if out.get("error"):
            refusals.append(out["error"])
            continue
        filed.add(target.phrase)
        if out.get("created"):
            proposed += 1
            have[_month(slot)] = have.get(_month(slot), 0) + 1
            # Marked so the next run does not re-rank something already
            # queued, and so `score` stops offering it as available work.
            keywords.upsert(sysrow.tenant, target.phrase, status="planned")
        else:
            refreshed += 1
        slot += dt.timedelta(days=max(1, 30 // cad["articles_monthly"]))

    return {"ok": True, "proposed": proposed, "refreshed": refreshed,
            "pillar_first": promoted, "refusals": refusals}


PLANNERS = {
    "campaign_email": campaign_rollout,
    "blog": blog_rollout,
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
