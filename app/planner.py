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
import re

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
#: EVERY CADENCE KNOB, DECLARED ONCE — the number, its ceiling, and what it
#: means to a person. The form used to render three hardcoded inputs, all of
#: them the CAMPAIGN planner's, on a card that also serves the blog: an owner
#: looking at the blog system was offered "per segment / month" and never
#: shown `articles_monthly` at all, while the two numbers that actually pace
#: their refreshes were module constants no console could reach.
#:
#: Owner, 2026-09-02: *"That should be set in the UI based on the cadence."*
#: Right, and the fix is not three more inputs — it is one table the planner
#: reads and the form renders, so a knob cannot exist in one and not the
#: other.
KNOBS = {
    "horizon_days": dict(
        label="horizon, days", cap=90,
        why="How far ahead work is scheduled. Past this the planner stops and "
            "says so rather than filling a quarter nobody has looked at."),
    "per_segment_monthly": dict(
        label="per segment / month", cap=8,
        why="How often one cohort may be written to. The floor under fatigue."),
    "segment_rest_days": dict(
        label="rest between sends, days", cap=60,
        why="The minimum gap after a send to one cohort, so a bad week cannot "
            "be answered by writing to them again on Thursday."),
    "articles_monthly": dict(
        label="articles / month", cap=30,
        why="New articles the blog planner may file per calendar month."),
    "posts_weekly": dict(
        label="Business Profile posts / week", cap=3,
        why="How many posts the Business Profile planner files per ISO week. "
            "One keeps the listing fresh; three is a campaign week."),
    "reports_weekly": dict(
        label="reports / week", cap=2,
        why="How many client reports the reports planner may file per ISO "
            "week. One is the number; two is a mid-week and a Friday."),
    "refreshes_monthly": dict(
        label="refreshes / month", cap=12,
        why="Rewrites of pages already published. Its OWN budget, because "
            "under one cap the refresh always loses to a new article — a new "
            "page is visibly a thing that did not exist, and moving a page "
            "from position 6 is invisible until it moves."),
    "refresh_after_days": dict(
        label="settle before refreshing, days", cap=180,
        why="How long a page must be live before it may be refreshed at all. "
            "Below this the ranking has not settled and `progress` refuses to "
            "attribute movement anyway, so acting is the more expensive "
            "mistake. Raise it on a site Google crawls slowly."),
    "refresh_cooldown_days": dict(
        label="between refreshes, days", cap=365,
        why="How long after refreshing before the same page may be offered "
            "again. It has to be re-crawled before the refresh can be judged; "
            "sooner is asking for a decision nothing can inform."),
}


def knobs_for(sysrow) -> list[dict]:
    """The cadence fields THIS system actually uses, with its current values.

    Derived from the planner's own defaults rather than listed beside them, so
    the form cannot offer a knob the planner ignores — or hide one it reads.
    """
    fn = PLANNERS.get(sysrow.key)
    defaults = (BLOG_CADENCE if fn is blog_rollout else DEFAULT_CADENCE)
    if fn is blog_rollout:
        live = blog_cadence_for(sysrow)
    elif fn is campaign_rollout:
        live = cadence_for(sysrow)
        defaults = {**defaults, "segment_rest_days": SEGMENT_REST_DAYS}
        live = {**live, "segment_rest_days": rest_days_for(sysrow)}
    elif fn is report_rollout:
        defaults = REPORT_CADENCE
        live = report_cadence_for(sysrow)
    elif fn is gbp_post_rollout:
        defaults = GBP_CADENCE
        live = gbp_cadence_for(sysrow)
    else:
        return []
    return [{"key": k, "value": live.get(k, v), "default": v,
             **{kk: vv for kk, vv in KNOBS.get(k, {}).items()}}
            for k, v in defaults.items() if k in KNOBS]


#: THE MIX — what share of new articles each kind of keyword gets. Declared
#: once, like KNOBS: the planner reads it, the Plan tab renders it, and
#: `systems.set_mix` validates against it. Owner, 2026-09-04: *"I should be
#: able to adjust the plan based on the percent of long tail / branded / short
#: / specific topics etc and the app should recommend a base setting default
#: based on the current status of the brand and where the best opportunities
#: lie."* The recommendation is `keywords.mix_recommendation`; this is the
#: knob the owner sets from it, or over it.
#:
#: Three partitions. `group="tier"` is the trio that must sum to 100; the
#: other two are each a share of the whole against its complement (branded
#: against unbranded, buying against informational). No mix declared means
#: the planner plans by score alone — exactly what it did before the knob
#: existed, so an account that has set nothing behaves as it did.
MIX = {
    "head": dict(
        label="head terms, % of new articles", group="tier",
        why="Short, high-volume phrases. Won with a pillar page plus the "
            "supports that link into it — never with one article."),
    "body": dict(
        label="body terms, %", group="tier",
        why="Two- to four-word phrases with real demand. The middle of the "
            "map, and usually the fastest to move."),
    "long_tail": dict(
        label="long-tail, %", group="tier",
        why="Questions and five-word phrases. Low volume each, easy to win, "
            "and the supports that make a head term winnable."),
    "branded": dict(
        label="branded phrases, %", group="branded",
        why="Phrases that name the brand. The site ranks for its own name "
            "with or without an article, so this is usually small."),
    "buying": dict(
        label="buying intent, %", group="intent",
        why="Commercial and transactional phrases against informational ones. "
            "Informational pages earn links and answers; buying pages "
            "convert. Neither side should be empty."),
}
MIX_TIERS = tuple(k for k, v in MIX.items() if v["group"] == "tier")


def mix_for(sysrow) -> dict:
    """The declared mix on this system, or {} when none is set.

    Only the keys MIX declares, only whole numbers 0–100, and only when the
    tier trio sums to 100 — anything else on the row is ignored as junk, the
    same rule `_cadence` keeps, so a bad write cannot bend the planner."""
    cfg = ((getattr(sysrow, "config", None) or {}).get("mix") or {})
    out: dict[str, int] = {}
    for k in MIX:
        try:
            v = int(cfg.get(k))
        except (TypeError, ValueError):
            continue
        if 0 <= v <= 100:
            out[k] = v
    if any(k not in out for k in MIX) or sum(out[k] for k in MIX_TIERS) != 100:
        return {}
    return out


def _mix_classes(tenant: str, row, brand: set) -> dict[str, str]:
    """Which class of each partition one keyword falls in."""
    from . import keywords as _kw
    tier = row.tier if row.tier in MIX_TIERS else "body"
    return {"tier": tier,
            "branded": "branded" if _kw.is_branded(tenant, row.phrase, brand)
            else "unbranded",
            "intent": "buying" if (row.intent or "") in _kw.BUYING_INTENTS
            else "informational"}


def _mix_order(tenant: str, order: list[str], by_phrase: dict, mix: dict,
               needs_first: dict[str, str], seed_rows: list) -> tuple[list[str], list[str]]:
    """Re-order the planner's queue so the OPEN queue holds the declared mix.

    A budget walk, not a quota walk: candidates stay in score order and each
    is taken the first time its classes are inside their budgets — the share
    times the items placed so far, rounded up — so the top-scoring keyword is
    always placed first whenever its class has any share at all, and a class
    at 0% is placed only when nothing else remains. The mix shapes WHICH
    keywords fill the horizon; the score still decides the order within a
    class. Seeded with the plans already open, so a daily top-up of one
    article respects the mix over the queue rather than over itself.

    A promoted pillar stays ahead of its support whatever the budgets say:
    `needs_first` maps a support to the pillar that must precede it, and
    taking the support takes the pillar first. The rule the walk must never
    bend is the one `blog_rollout` exists to enforce — and every pull is
    RETURNED as a sentence, because silently planning something other than
    the thing the mix picked is the same unauditable helpfulness the
    promotion rule refuses.

    Returns `(order, pulled)`.
    """
    import math
    from . import keywords as _kw
    brand = _kw.brand_tokens_for(tenant)
    shares = {
        "tier": {t: mix[t] for t in MIX_TIERS},
        "branded": {"branded": mix["branded"], "unbranded": 100 - mix["branded"]},
        "intent": {"buying": mix["buying"], "informational": 100 - mix["buying"]},
    }
    filled: dict[str, dict[str, int]] = {d: {} for d in shares}
    n = 0

    def _take(row) -> None:
        nonlocal n
        for d, c in _mix_classes(tenant, row, brand).items():
            filled[d][c] = filled[d].get(c, 0) + 1
        n += 1

    def _fits(row, dims=("tier", "branded", "intent")) -> bool:
        for d, c in _mix_classes(tenant, row, brand).items():
            if d not in dims:
                continue
            budget = math.ceil(shares[d][c] / 100.0 * (n + 1))
            if filled[d].get(c, 0) >= budget:
                return False
        return True

    for row in seed_rows:
        _take(row)
    pending = [ph for ph in order if ph in by_phrase]
    out: list[str] = []
    pulled: list[str] = []
    while pending:
        # THE TIER IS THE SPINE. Branded and buying shape the plan within it
        # as far as the map allows: when nothing left fits all three (a map
        # with few buying phrases, a queue already full of informational
        # ones), the tier budgets alone decide, and only when nothing fits
        # those either does score order resume. The mix is a preference
        # among what exists, never a refusal to plan — and a share that the
        # map cannot supply bends the two secondary dimensions before it
        # bends the one the owner named first.
        pick = next((ph for ph in pending if _fits(by_phrase[ph])), None)
        if pick is None:
            pick = next((ph for ph in pending
                         if _fits(by_phrase[ph], dims=("tier",))), None)
        if pick is None:
            pick = pending[0]
        pillar = needs_first.get(pick)
        if pillar and pillar in pending:
            pending.remove(pillar)
            out.append(pillar)
            _take(by_phrase[pillar])
            pulled.append(f"{pillar!r} goes first — the mix picked "
                          f"{pick!r}, which supports it and would have "
                          f"nothing to link to")
        pending.remove(pick)
        out.append(pick)
        _take(by_phrase[pick])
    return out, pulled


def _open_article_rows(sysrow) -> list:
    """The keyword rows behind this system's open article plans — what the
    mix walk is seeded with."""
    from . import keywords as _kw
    phrases = set()
    for p in systems.plans(sysrow.tenant, sysrow.key):
        if str(p.ref or "").startswith(f"article:{sysrow.tenant}:"):
            phrases.add(str(((p.brief or {}).get("plan") or {}).get("keyword") or ""))
    return [r for r in _kw.targets(sysrow.tenant) if r.phrase in phrases]


BLOG_CADENCE = {"horizon_days": 45, "articles_monthly": 4,
                # REFRESHES DO NOT SHARE THE ARTICLE BUDGET. Under one cap the
                # two compete, and the loser is always the refresh: a new
                # article is visibly a thing that did not exist, while fixing
                # a page that already ranks at 6 is invisible until it moves.
                # A separate, small number is what keeps the lane from either
                # starving or eating the month.
                "refreshes_monthly": 2,
                # THE TWO WINDOWS THAT PACE THE REFRESH LANE, per account
                # rather than per platform. A site Google crawls weekly and one
                # it crawls monthly cannot share a settle time, and these were
                # module constants no console could reach.
                "refresh_after_days": 30,
                "refresh_cooldown_days": 60}
MAX_ARTICLES_MONTHLY = 30
MAX_REFRESHES_MONTHLY = 12


def blog_cadence_for(sysrow) -> dict:
    return _cadence(sysrow, BLOG_CADENCE,
                    {"horizon_days": MAX_HORIZON_DAYS,
                     "articles_monthly": MAX_ARTICLES_MONTHLY,
                     "refreshes_monthly": MAX_REFRESHES_MONTHLY,
                     "refresh_after_days": 180,
                     "refresh_cooldown_days": 365})


def _month(d: dt.date) -> str:
    return d.strftime("%Y-%m")


def _next_month(d: dt.date) -> dt.date:
    return (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)


def _existing_by_month(sysrow, prefix: str) -> dict[str, int]:
    """How many items already exist per calendar month for one segment.

    EVERY stage counts — an open plan, a consumed run, and a SKIPPED one.
    A skip was the owner's decision about that month, and a planner that
    re-proposes a declined item is a nag wearing an algorithm.

    THE MONTH IS READ FROM `planned_for`, not parsed out of the ref. It was
    parsed out of the ref, which is a date only for campaigns: a campaign's
    ref ends in its slot, an article's ends in a keyword slug. So every blog
    row raised ValueError and was skipped, this returned {} on every call,
    and `articles_monthly` only ever bound WITHIN a single run — three runs
    in one month filed three articles against a cap of one. `planned_for` is
    the field the cap is about and both planners set it, so one reader
    answers for both; for a campaign it is the same value the ref carried,
    which is why nothing about campaign pacing moves.
    """
    out: dict[str, int] = {}
    with db.SessionLocal() as s:
        rows = (s.query(db.SystemRun.brief)
                .filter(db.SystemRun.system_id == sysrow.id,
                        db.SystemRun.ref.like(prefix + "%")).all())
    for (brief,) in rows:
        try:
            d = dt.date.fromisoformat(str((brief or {}).get("planned_for") or ""))
        except ValueError:
            continue
        out[_month(d)] = out.get(_month(d), 0) + 1
    return out


def _reader_for(sysrow, segment: str) -> str:
    """Which persona the next campaign to this cohort should be written for.

    A PLANNER THAT FILES INCOMPLETE WORK IS A NAG. `audience_key` became a
    required plan field the moment one-to-many work had to name its reader,
    and a proposal that arrives missing it puts the decision back on the owner
    for every send — which is exactly what proposing is supposed to remove.

    So it proposes one, and the owner overrides it on the plan like any other
    field. Least recently proposed to this cohort, never "the first one":
    ordering by the roster would write to the same persona for ever and the
    other two would never be spoken to.

    Read from the PLANS rather than from the ledger on purpose.
    `Output.audience_key` still carries the SEGMENT for campaigns — the two
    vocabularies the audit found in one column — so reading persona history
    from it would rank on the wrong thing entirely.
    """
    from . import kb
    people = [a.key for a in kb.audiences(sysrow.tenant)]
    if not people:
        return ""                # nothing to choose; the run says so instead
    seen: dict[str, str] = {}
    with db.SessionLocal() as s:
        rows = (s.query(db.SystemRun.brief, db.SystemRun.created_at)
                .filter(db.SystemRun.system_id == sysrow.id).all())
    for brief, at in rows:
        plan = ((brief or {}).get("plan") or {})
        if plan.get("segment") != segment:
            continue
        who = str(plan.get("audience_key") or "")
        when = db.as_utc(at).isoformat()
        if who and when > seen.get(who, ""):
            seen[who] = when
    # Never proposed to this cohort sorts first, then longest ago.
    return sorted(people, key=lambda k: (k in seen, seen.get(k, "")))[0]


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
                          "goal": seg.get("angle", ""),
                          "audience_key": _reader_for(sysrow, seg["key"])},
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
        # A pressure plan is a campaign like any other, so it names its reader
        # too — an incomplete proposal is a nag whichever path filed it.
        plan = {"segment": seg, "audience_key": _reader_for(sysrow, seg)}
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
def file_articles(sysrow, phrases: list, *, role: str = "support",
                  cluster: str = "", trigger: str = "console") -> dict:
    """File a named set of keywords as blog plans, under the run's own cap.

    ONE FILER. The Plan-supports control grew this loop inline, and the
    Answer-engines control needed the identical thing for a different set —
    two copies of "how work gets filed" drift on the day either learns
    something, and the thing they would drift ON is the monthly cap, which has
    already been the source of one silent overrun.

    Everything the weekly run obeys is obeyed here: `article_window` for what
    each month already holds, `next_article_slot` to skip a full month and
    stop at the horizon, `open_plan` under the same `article:` ref space, and
    the keyword marked `planned` so nothing offers it twice. A plan filed from
    a console button is indistinguishable from one the planner proposed, which
    is the point — there is no second way to create work.

    Returns what happened rather than a bare count: filed, deferred because
    the calendar is full, and refused with reasons.
    """
    from . import keywords as kwm
    win = article_window(sysrow)
    slot = win["slot"]
    filed, refused, deferred = 0, [], 0
    for phrase in phrases:
        nxt = next_article_slot(win, slot)
        if nxt is None:
            # NOT A FAILURE, AND SAID AS SUCH. The rest are still worth
            # writing; the calendar is simply full, which is the same answer
            # the weekly run gives and for the same reason.
            deferred = len(phrases) - filed - len(refused)
            break
        slot = nxt
        got = systems.open_plan(
            sysrow.tenant, "blog",
            ref=f"article:{sysrow.tenant}:{kwm.slug(phrase)}",
            plan={"keyword": phrase, "role": role, "cluster": cluster},
            planned_for=slot.isoformat(), trigger=trigger)
        if got.get("error"):
            refused.append(got["error"])
            continue
        if got.get("created"):
            filed += 1
            kwm.upsert(sysrow.tenant, phrase, status="planned")
            slot = took_slot(win, slot)
    return {"filed": filed, "deferred": deferred, "refused": refused,
            "cap": win["cadence"]["articles_monthly"]}


def article_window(sysrow) -> dict:
    """Everything needed to place an article legally: the cadence, what each
    month already holds, the first candidate slot, and where the horizon ends.

    ONE READER, so the console's Plan-supports control and the weekly run
    cannot disagree about when an article may be planned. The control shipped
    with a docstring claiming "the monthly cap that governs one governs the
    other" — and it read `articles_monthly` only to SPACE the plans, never to
    stop. Twelve supports filed in one press put 8 into a month capped at 4
    and three past the horizon; the overrun persisted, so the next weekly run
    read the month as full and refused entirely. A claim about a cap, with no
    cap behind it, in a docstring: exactly the shape this repo keeps paying
    for.
    """
    cad = blog_cadence_for(sysrow)
    today = dt.date.today()
    return {"cadence": cad,
            "have": _existing_by_month(sysrow, f"article:{sysrow.tenant}:"),
            "slot": today + dt.timedelta(days=LEAD_DAYS),
            "horizon_end": today + dt.timedelta(days=cad["horizon_days"])}


def next_article_slot(win: dict, slot: dt.date):
    """The next date an article may be planned for, or None when the horizon
    is full. Month-forward only, so it terminates."""
    cap = win["cadence"]["articles_monthly"]
    while slot <= win["horizon_end"] and win["have"].get(_month(slot), 0) >= cap:
        slot = _next_month(slot)
    return slot if slot <= win["horizon_end"] else None


def took_slot(win: dict, slot: dt.date) -> dt.date:
    """Record that a slot was used, and return where to look next."""
    win["have"][_month(slot)] = win["have"].get(_month(slot), 0) + 1
    return slot + dt.timedelta(
        days=max(1, 30 // max(1, win["cadence"]["articles_monthly"])))


def _links_up(row, pillars: dict) -> bool:
    """Can this row link up, or is it going to ship pointing nowhere?

    True for a pillar — it IS the top of its cluster and links sideways, so it
    is never waiting on one. True for a support whose pillar has a resolving
    `target_url`, which is the only form of "the pillar exists" the drafter
    can see: the link pool is built from `target_url` alone.

    AND TRUE FOR A SUPPORT WHOSE PILLAR IS STILL A CANDIDATE, which is the
    distinction that keeps this rule from swallowing the older one. That case
    is already handled, and handled BETTER, by the pillar-before-support rule
    below: the pillar gets promoted ahead of it and the run SAYS so. Demoting
    here as well would reach the same order by a silent route and cost the
    sentence — and "silently planning something other than the thing that
    ranked first is the kind of helpfulness nobody can audit" is why that
    sentence exists. Caught by `test_blog_skill`, which asserts the run
    reports its own reordering.

    So this fires on the case nothing in the run can fix: a pillar that has
    been WRITTEN — approved, even published — and still has no address. No
    promotion helps, because there is nothing left to promote.
    """
    if (row.role or "") != "support":
        return True
    pillar = pillars.get(row.cluster_key)
    if pillar is None or pillar.status == "candidate":
        return True
    return bool((pillar.target_url or "").strip())


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
        # STILL RUN THE REFRESH PASS. Returning here skipped it, and "every
        # candidate is already planned" is not a quiet month — it is the
        # steady state this lane was built for, when the only writing left is
        # fixing pages that already shipped.
        ref_out = _blog_refreshes(sysrow, cad,
                                  today + dt.timedelta(days=cad["horizon_days"]))
        return {"ok": True, "proposed": 0, "refreshed": 0,
                "refresh_plans": ref_out["filed"],
                "refresh_reasons": ref_out["reasons"],
                "refusals": ["no candidate keywords — press Build the map "
                             "first, or every candidate is already planned"]
                            + ref_out["refusals"]}

    # Who is a pillar, and has it been dealt with. Read once: asking per
    # keyword would be a query per row on a map of several hundred.
    by_cluster_pillar = {r.cluster_key: r for r in keywords.targets(sysrow.tenant)
                         if r.role == "pillar"}

    prefix = f"article:{sysrow.tenant}:"
    _win = article_window(sysrow)
    have = _win["have"]
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
    needs_first: dict[str, str] = {}
    # A SUPPORT WHOSE PILLAR HAS A REAL URL COMES FIRST. Owner, 2026-09-01:
    # *"Lets prioritize linked support articles."* The pillar-before-support
    # rule below handles the pillar that has not been WRITTEN; this handles the
    # one that has been written and approved and still has no address, which
    # `_run_blog_article` treats identically to not existing — it offers only
    # siblings whose `target_url` resolves. So a support written into that
    # cluster ships pointing nowhere and needs a second pass later, while one
    # whose pillar is addressable can do its whole job the first time.
    #
    # A REORDER, NOT A REFUSAL, for the reason the ordering is stable
    # everywhere else here: the unlinkable support is still real work and still
    # gets written; it just does not go first when something else can land
    # complete. Refusing it would punish the account for a fact about its CMS.
    rows = sorted(rows, key=lambda r: 0 if _links_up(r, by_cluster_pillar) else 1)
    for row in rows:                     # priority order, linkable first
        if row.role == "support":
            pillar = by_cluster_pillar.get(row.cluster_key)
            if pillar is not None and pillar.status == "candidate" \
                    and pillar.phrase not in order:
                order.append(pillar.phrase)
                by_phrase.setdefault(pillar.phrase, pillar)
                promoted.append(f"{pillar.phrase!r} goes first — "
                                f"{row.phrase!r} supports it and would have "
                                f"nothing to link to")
            if pillar is not None and pillar.status == "candidate":
                needs_first[row.phrase] = pillar.phrase
        if row.phrase not in order:
            order.append(row.phrase)

    # THE MIX, IF ONE IS DECLARED. Read here, on the order the rules above
    # produced, so the pillar-before-support rule and the linkable-first rule
    # hold inside every class and the owner's shares decide only which classes
    # fill the horizon. No mix means the score order stands — an account that
    # has set nothing plans exactly as it did before the knob existed.
    mix = mix_for(sysrow)
    if mix:
        order, pulled = _mix_order(sysrow.tenant, order, by_phrase, mix,
                                   needs_first, _open_article_rows(sysrow))
        promoted.extend(p for p in pulled if p not in promoted)
    filed_mix: dict[str, dict[str, int]] = {"tier": {}, "branded": {}, "intent": {}}

    for phrase in order:
        target = by_phrase[phrase]
        if target.phrase in filed:
            continue

        nxt = next_article_slot(_win, slot)
        if nxt is None:
            refusals.append(f"horizon full at {cad['articles_monthly']}/month "
                            f"— {len(order) - len(filed)} keyword(s) still waiting")
            break
        slot = nxt

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
            slot = took_slot(_win, slot)
            # Marked so the next run does not re-rank something already
            # queued, and so `score` stops offering it as available work.
            keywords.upsert(sysrow.tenant, target.phrase, status="planned")
            for d, c in _mix_classes(sysrow.tenant, target,
                                     keywords.brand_tokens_for(sysrow.tenant)).items():
                filed_mix[d][c] = filed_mix[d].get(c, 0) + 1
        else:
            refreshed += 1
            slot += dt.timedelta(days=max(1, 30 // cad["articles_monthly"]))

    ref_out = _blog_refreshes(sysrow, cad, horizon_end)
    refusals.extend(ref_out["refusals"])
    return {"ok": True, "proposed": proposed, "refreshed": refreshed,
            "pillar_first": promoted, "refusals": refusals,
            "refresh_plans": ref_out["filed"],
            "refresh_reasons": ref_out["reasons"],
            # What this pass filed, by class, beside what was declared — so
            # the run can say the mix took effect rather than leaving it to
            # be inferred from the queue.
            "mix": {"declared": mix, "filed": filed_mix}}


def _blog_refreshes(sysrow, cad: dict, horizon_end: dt.date) -> dict:
    """File a plan for each published page whose ranking says refresh THIS one.

    THE ACTION IS READ, NOT RE-DERIVED. `keywords.attention` already decides
    what each published page is owed, from one band table; this asks it and
    files the rows whose action is `refresh`. Re-testing `position <= 10`
    here would put the bands in two places, and the console would go on
    saying "supports in its cluster" while the planner quietly filed a
    rewrite — the same split-contract defect as everything else this week.

    Only `refresh` is filed. The other actions are real answers that are not
    a blog plan: `supports` is a different keyword's article and gets planned
    as one, `index` is a Search Console question, `reread` is a judgement
    nobody should automate into a queue. Filing them all as "refresh" would
    make the lane look productive and be wrong three times in four.

    Its own ref space and its own monthly cap, so a refresh can never be
    mistaken for — or displace — a new article on the same keyword.
    """
    from . import keywords

    prefix = f"refresh:{sysrow.tenant}:"
    have = _existing_by_month(sysrow, prefix)
    cap = cad["refreshes_monthly"]
    slot = dt.date.today() + dt.timedelta(days=LEAD_DAYS)
    filed = 0
    reasons: list[str] = []
    refusals: list[str] = []

    for item in keywords.attention(sysrow.tenant, top=50):
        if item["action"] != "refresh":
            continue
        while slot <= horizon_end and have.get(_month(slot), 0) >= cap:
            slot = _next_month(slot)
        if slot > horizon_end:
            refusals.append(f"refresh horizon full at {cap}/month — "
                            f"more pages are owed one")
            break
        # THE READING IS THE INSTRUCTION. A redraft brief that says only
        # "refresh this" is a rewrite with no target; the position, the state
        # and the move the band argues for are what make it a revision
        # somebody can check afterwards.
        why = (f"This page is published and not working: {item['state']}"
               + (f" at position {item['position']:.0f}"
                  if item.get("position") is not None else "")
               + f". {item['owed']}")
        out = systems.open_plan(
            sysrow.tenant, sysrow.key,
            ref=prefix + keywords.slug(item["phrase"]),
            plan={"keyword": item["phrase"],
                  "role": item["role"] or "support",
                  "cluster": item["cluster"] or "",
                  "revision_notes": why},
            planned_for=slot.isoformat(), trigger="planner")
        if out.get("error"):
            refusals.append(out["error"])
            continue
        if out.get("created"):
            filed += 1
            have[_month(slot)] = have.get(_month(slot), 0) + 1
            reasons.append(f"{item['phrase']!r} — {item['state']}")
        slot += dt.timedelta(days=max(1, 30 // cap))
    return {"filed": filed, "reasons": reasons, "refusals": refusals}


def reorder_rollout(sysrow) -> dict:
    """One replenishment prompt a month, against the cadence knobs.

    The campaign planner walks every high-value segment by neglect; this one
    walks one segment, because the system has one. A business model with no
    `reorder_due` segment refuses by name — reorder prompts are for
    consumables, and filing one for a venue would be a plan nothing can run.
    """
    import datetime as _dt
    from . import segments, systems
    cad = cadence_for(sysrow)
    got = segments.for_tenant(sysrow.tenant)
    if not got.get("ok"):
        return {"proposed": 0, "refreshed": 0,
                "refusals": [got.get("error", "segments unavailable")]}
    seg = next((x for x in got.get("segments", []) if x["key"] == "reorder_due"), None)
    if seg is None:
        return {"proposed": 0, "refreshed": 0,
                "refusals": ["this business model has no reorder_due segment — "
                             "reorder prompts are for consumables"]}
    prefix = f"reorder:{sysrow.tenant}:reorder_due:"
    have = _existing_by_month(sysrow, prefix)
    today = db.utcnow().date()
    d, horizon_end = today, today + _dt.timedelta(days=cad["horizon_days"])
    proposed = refreshed = 0
    refusals: list[str] = []
    while d <= horizon_end:
        if have.get(_month(d), 0) < cad["per_segment_monthly"]:
            out = systems.open_plan(
                sysrow.tenant, sysrow.key, ref=prefix + d.isoformat(),
                # No `segment` on the plan: the system's plan_fields do not
                # carry one because the segment is not a choice, and
                # `open_plan` refuses a field the system does not declare —
                # it did, on the first run. `_run_reorder` forces it.
                plan={"goal": seg.get("angle", ""),
                      "audience_key": _reader_for(sysrow, "reorder_due")},
                planned_for=d.isoformat(), trigger="planner")
            if out.get("error"):
                refusals.append(out["error"])
            elif out.get("created"):
                proposed += 1
                have[_month(d)] = have.get(_month(d), 0) + 1
            else:
                refreshed += 1
        d = _next_month(d)
    return {"proposed": proposed, "refreshed": refreshed, "refusals": refusals}


REPORT_CADENCE = {"horizon_days": 14, "reports_weekly": 1}
MAX_REPORTS_WEEKLY = 2


def report_cadence_for(sysrow) -> dict:
    """The reports planner's cadence — the blog pattern, not the campaign one:
    its own defaults and caps, so `knobs_for` renders the knob it reads."""
    return _cadence(sysrow, REPORT_CADENCE,
                    {"horizon_days": MAX_HORIZON_DAYS,
                     "reports_weekly": MAX_REPORTS_WEEKLY})


def report_rollout(sysrow) -> dict:
    """One client report per ISO week, across the horizon.

    The unit is the week and the ref names it (`report:<tenant>:<year>-W<nn>`),
    so `open_plan`'s idempotence per ref is the whole calendar: a second pass
    refreshes the week already filed and creates nothing. `to` is a required
    plan field the planner cannot read from data, so it is left absent and
    `plan_complete` names it — the owner fills it once on the plan.
    """
    import datetime as _dt
    from . import systems
    cad = report_cadence_for(sysrow)
    today = db.utcnow().date()
    horizon_end = today + _dt.timedelta(days=cad["horizon_days"])
    per_week = int(cad.get("reports_weekly", 1) or 1)
    proposed = refreshed = 0
    refusals: list[str] = []
    d = today
    seen_weeks: set[str] = set()
    while d <= horizon_end:
        y, w, _ = d.isocalendar()
        week = f"{y}-W{w:02d}"
        if week not in seen_weeks:
            seen_weeks.add(week)
            for i in range(per_week):
                ref = f"report:{sysrow.tenant}:{week}" + (f":{i + 1}" if i else "")
                out = systems.open_plan(
                    sysrow.tenant, sysrow.key, ref=ref,
                    plan={"days": 7},
                    planned_for=d.isoformat(), trigger="planner")
                if out.get("error"):
                    refusals.append(out["error"])
                elif out.get("created"):
                    proposed += 1
                else:
                    refreshed += 1
        d += _dt.timedelta(days=7)
    return {"proposed": proposed, "refreshed": refreshed, "refusals": refusals,
            "weeks": sorted(seen_weeks)}


GBP_CADENCE = {"horizon_days": 21, "posts_weekly": 1}
MAX_POSTS_WEEKLY = 3


def gbp_cadence_for(sysrow) -> dict:
    return _cadence(sysrow, GBP_CADENCE,
                    {"horizon_days": MAX_HORIZON_DAYS,
                     "posts_weekly": MAX_POSTS_WEEKLY})


def gbp_sources(tenant: str, key: str = "gbp_post") -> dict:
    """What is left to post — derived and native — with what has already been
    used taken out, so the planner never files the same source twice.

    Used = an existing post artifact made from it, or an open plan naming it.
    """
    from . import kb, systems
    used: set[str] = set()
    with db.SessionLocal() as s:
        for a in (s.query(db.ArtifactBody)
                  .filter(db.tenant_filter(db.ArtifactBody, tenant),
                          db.ArtifactBody.format == "gbp_post").all()):
            m = dict(a.meta or {})
            for k in ("derived_from", "objection_id", "claim_id"):
                if m.get(k):
                    used.add(str(m[k]))
        # A claim a post already CITED — inherited from an article, say — is
        # spent too: the ledger's repetition window would refuse it, so the
        # planner must not propose it.
        for o in (s.query(db.Output)
                  .filter(db.tenant_filter(db.Output, tenant),
                          db.Output.format == "gbp_post").all()):
            used.update(str(c) for c in (o.claim_ids or []))
    for p in systems.plans(tenant, key):
        plan = dict(((p.brief or {}).get("plan") or {}))
        for k in ("source", "objection_id", "claim_id"):
            if plan.get(k):
                used.add(str(plan[k]))
    derived = [x for x in systems.approved_sources(tenant) if x["id"] not in used]
    objections = [o for o in kb.objections(tenant, any_entity=True)
                  if o.id not in used and (o.response or "").strip()]
    claims = [c for c in kb.claims(tenant) if c.id not in used]
    return {"derived": derived, "objections": objections, "claims": claims}


def _local_keyword(tenant: str, declared: dict) -> str:
    """The post's local keyword, from the SAME keyword map the blog plans
    read: the highest-priority target whose phrase names the locality or the
    listing's category. '' when the map has none — the skill then falls back
    to 'category in locality' from the declared profile."""
    from . import keywords
    loc = str(declared.get("locality") or "").strip().lower()
    cat = str(declared.get("category") or "").strip().lower()
    cat_words = [w for w in re.findall(r"[a-z0-9]+", cat) if len(w) > 3]
    for r in keywords.targets(tenant):
        if (getattr(r, "owner_priority", "") or "") == "muted":
            continue
        phrase = str(r.phrase or "").lower()
        if (loc and loc in phrase) or (cat_words and all(w in phrase for w in cat_words)):
            return str(r.phrase or "")
    return ""


def gbp_post_rollout(sysrow) -> dict:
    """One Business Profile post per ISO week across the horizon, alternating
    what it is made from: an approved artifact one week (the newest not yet
    posted), an objection or a claim the next (INITIATIVE-gbp §5's two
    producers). The ref names the week, so `open_plan`'s idempotence per ref
    is the calendar — a second pass refreshes, never doubles. A week with
    nothing left to make a post from is SAID, not filled with a blank."""
    import datetime as _dt
    from . import systems
    from . import tenants as _tn
    cad = gbp_cadence_for(sysrow)
    today = db.utcnow().date()
    horizon_end = today + _dt.timedelta(days=cad["horizon_days"])
    posts_per_week = int(cad.get("posts_weekly", 1) or 1)
    pool = gbp_sources(sysrow.tenant, sysrow.key)
    _t = _tn.get(sysrow.tenant)
    local = _local_keyword(sysrow.tenant,
                           dict((getattr(_t, "gbp", None) or {}) if _t else {}))
    existing = {p.ref for p in systems.plans(sysrow.tenant, sysrow.key)}
    proposed = refreshed = 0
    refusals: list[str] = []
    d, n = today, 0
    seen_weeks: set[str] = set()
    while d <= horizon_end:
        y, w, _ = d.isocalendar()
        week = f"{y}-W{w:02d}"
        if week not in seen_weeks:
            seen_weeks.add(week)
            for i in range(posts_per_week):
                ref = f"gbp:{sysrow.tenant}:{week}" + (f":{i + 1}" if i else "")
                if ref in existing:
                    # A week already filed keeps its source; refreshing it
                    # would re-pick and double what the owner edited.
                    refreshed += 1
                    n += 1
                    continue
                plan: dict = {"kind": "update", "cta": "learn_more"}
                if local:
                    # SEO is the plan's spine: the keyword comes from the map.
                    plan["keyword"] = local
                want_native = (n % 2 == 1)
                if not want_native and pool["derived"]:
                    plan["source"] = pool["derived"].pop(0)["id"]
                elif pool["objections"]:
                    plan["objection_id"] = pool["objections"].pop(0).id
                elif pool["claims"]:
                    plan["claim_id"] = pool["claims"].pop(0).id
                elif pool["derived"]:
                    plan["source"] = pool["derived"].pop(0)["id"]
                else:
                    refusals.append(f"{week}: nothing left to make a post "
                                    f"from — approve an article, an email or "
                                    f"an ad, or add an objection or a claim")
                    n += 1
                    continue
                out = systems.open_plan(sysrow.tenant, sysrow.key, ref=ref,
                                        plan=plan, planned_for=d.isoformat(),
                                        trigger="planner")
                n += 1
                if out.get("error"):
                    refusals.append(out["error"])
                elif out.get("created"):
                    proposed += 1
                else:
                    refreshed += 1
        d += _dt.timedelta(days=7)
    return {"proposed": proposed, "refreshed": refreshed, "refusals": refusals,
            "weeks": sorted(seen_weeks)}


PLANNERS = {
    "campaign_email": campaign_rollout,
    "blog": blog_rollout,
    "reorder_engine": reorder_rollout,
    "reports": report_rollout,
    "gbp_post": gbp_post_rollout,
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


# ---------------------------------------------------------------------------
# Reset and refresh — the two controls the Plan lacked (owner, 2026-09-04:
# "I will need to refresh the plan to add new systems and to reset the
# schedule if the initial schedule doesn't make sense.")
# ---------------------------------------------------------------------------

#: Which planners lay their plans on a schedule that can be re-laid. Each
#: entry is (ref prefix, how the lane is paced): the knob and the period it
#: is per, so the step between plans is `period // knob`. The calendar
#: planners are absent ON PURPOSE — a Business Profile post and a client
#: report are planned PER WEEK and the week IS the ref, so moving one to
#: another date would leave the next pass filing that week again. Changing
#: their cadence is the reset: the next pass follows it.
RESETTABLE = {
    "blog": (("article", "articles_monthly", 30),
             ("refresh", "refreshes_monthly", 30)),
    "campaign_email": (("campaign", "per_segment_monthly", 30),),
    "reorder_engine": (("reorder", "per_segment_monthly", 30),),
}
NOT_RESETTABLE_WHY = ("planned on the calendar — the week is the item, so "
                      "its date is not re-laid; change the cadence and the "
                      "next pass follows it")


def resettable(sysrow) -> bool:
    return sysrow is not None and sysrow.key in RESETTABLE


def _lane_cadence(sysrow) -> dict:
    fn = PLANNERS.get(sysrow.key)
    if fn is blog_rollout:
        return blog_cadence_for(sysrow)
    return cadence_for(sysrow)


def reset_schedule(sysrow) -> dict:
    """Re-date every OPEN plan of this system from today, under its cadence.

    The items stay; only their dates move. Walked in the order they were
    already in (soonest first), from `LEAD_DAYS` out, `period // knob` apart
    — the pacing the planner itself uses — so a queue laid down against a
    cadence the owner has since changed comes out laid against the one they
    have now. Campaign plans are re-laid PER SEGMENT, `SPACING_DAYS` apart,
    the way the calendar pass lays them, and their ref follows the date
    because the ref carries it.

    NEVER OVER THE OWNER. A plan whose date the owner set (`planned_for` in
    `brief["edited"]`) keeps it and is named in `kept` — the carry-forward
    rule `open_plan` keeps, applied to the one field this touches.
    """
    if sysrow is None:
        return {"error": "unknown system"}
    if not resettable(sysrow):
        return {"error": f"{sysrow.key}: {NOT_RESETTABLE_WHY}"}
    cad = _lane_cadence(sysrow)
    today = dt.date.today()
    start = today + dt.timedelta(days=LEAD_DAYS)
    opened = systems.plans(sysrow.tenant, sysrow.key)
    redated, kept, moved = 0, [], []
    with db.SessionLocal() as s:
        for prefix, knob, period in RESETTABLE[sysrow.key]:
            lane = [p for p in opened
                    if str(p.ref or "").startswith(f"{prefix}:{sysrow.tenant}:")]
            if not lane:
                continue
            rate = max(1, int(cad.get(knob) or 1))
            step = max(1, period // rate)
            # Campaigns and reorders run one lane per SEGMENT, each paced by
            # the month; articles run one lane for the account. Grouping on
            # the ref's third field gives the segment for the first two and
            # one group for the third, so one walk serves all.
            groups: dict[str, list] = {}
            for p in lane:
                parts = str(p.ref).split(":")
                gkey = parts[2] if prefix in ("campaign", "reorder") and len(parts) > 3 else ""
                groups.setdefault(gkey, []).append(p)
            for gi, (gkey, items) in enumerate(groups.items()):
                base = start + dt.timedelta(days=gi * SPACING_DAYS if gkey else 0)
                k = 0
                for p in items:
                    row = s.get(db.SystemRun, p.id)
                    brief = dict(row.brief or {})
                    if "planned_for" in (brief.get("edited") or []):
                        kept.append(str(row.ref or ""))
                        continue
                    when = base + dt.timedelta(days=k * step)
                    k += 1
                    before = str(brief.get("planned_for") or "")
                    brief["planned_for"] = when.isoformat()
                    row.brief = brief
                    if prefix in ("campaign", "reorder") and before:
                        # The ref carries the date for these lanes; a ref
                        # that names a day the plan no longer sits on would
                        # let the next pass file that day again.
                        row.ref = str(row.ref).rsplit(":", 1)[0] + ":" + when.isoformat()
                    redated += 1
                    moved.append((str(row.ref or ""), before, when.isoformat()))
        s.commit()
    return {"ok": True, "redated": redated, "kept": kept, "moved": moved,
            "cadence": cad}


def refresh(tenant: str) -> dict:
    """Bring every declared planner into this account's Plan, now.

    For each system in `PLANNERS`: install it when it is absent and its
    prerequisites are met (a system whose needs are unmet is NAMED with the
    need, never installed blind); then run the planner for every one that is
    on. A system that is installed and off is named as off — the switch is
    the owner's, and a refresh that turned systems on would be a planner
    deciding what runs.
    """
    installed, off, unmet, topped = [], [], [], {}
    for key in PLANNERS:
        row = systems.find(tenant, key)
        if row is None:
            pre = systems.prerequisites(tenant, key)
            if not pre["ready"]:
                unmet.append(f"{key}: needs "
                             + ", ".join(i["name"] for i in pre["missing"])[:120])
                continue
            row = systems.create(tenant, key)
            installed.append(key)
        if not systems.is_on(row):
            off.append(key)
            continue
        got = top_up(row) or {}
        topped[key] = {"proposed": int(got.get("proposed") or 0),
                       "refreshed": int(got.get("refreshed") or 0),
                       "refusals": list(got.get("refusals") or [])}
    return {"ok": True, "installed": installed, "off": off, "unmet": unmet,
            "topped": topped}
