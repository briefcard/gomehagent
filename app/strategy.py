"""What this brand has actually been saying, to whom, and how often.

`ledger.record` has written `theme`, `angle`, `shape`, the claims and the
featured entity on every send since it was written. Until now exactly one
thing read any of it: `skill_pack._recent_sends`, which takes four rows for
ONE segment and shows them to the drafter so the next email differs from the
last. Nothing aggregated it, and nothing showed it to the owner.

So the drafter avoids repeating itself and nobody can answer the questions
that actually decide a programme: which lists have we neglected, are we
telling one story or five, is this brand giving before it asks, and did any
of it work. All four are queries over rows we already have.

**Deterministic, like the planner.** No model call. Which cohort has gone
longest without a send is arithmetic, not judgement, and a number a person can
check beats a paragraph they have to trust.

**Findings are named, not scored.** A single "strategy health: 62%" tells
nobody what to do. Each finding says what is true, why it matters and what
would change it — the same shape `systems.ready()` uses for blockers, for the
same reason.

Read by `planner.campaign_rollout` (which cohort is most owed a send) and by
the console. Both go through `read()`.
"""
from __future__ import annotations

import datetime as dt

from . import ledger, segments

#: Gives per ask this brand should be running at. Three gives then an ask is
#: what `skill_pack._campaign_craft` already rotates towards at draft time;
#: this is the same rule measured across the whole programme, where it can
#: actually be checked. Below it, the list is being asked too often.
GIVE_ASK_TARGET = 3.0

#: Intents that ask for something. Everything else gives. Kept as a set rather
#: than imported from `skill_pack` on purpose — importing the skill pack pulls
#: the whole generator in, and this module is read by the planner.
ASKING_INTENTS = {"offer"}

#: A cohort with no send in this many days is being neglected rather than
#: rested. Longer than the default monthly cadence, so a segment on a normal
#: schedule never trips it.
NEGLECT_DAYS = 45

#: One product or one claim carrying more than this share of the sends that
#: had one is a brand telling a single story by accident.
CONCENTRATION = 0.6


def _ratio(gives: int, asks: int) -> float | None:
    """Gives per ask. None when nothing has asked yet — which is not infinity,
    it is "no evidence", and the two read very differently in a report."""
    return None if asks == 0 else round(gives / asks, 2)


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else round((xs[mid - 1] + xs[mid]) / 2, 1)


def read(tenant: str, *, days: int = 90) -> dict:
    """The programme, per cohort and as a whole, with what to do about it.

    Every catalogue segment appears even with zero sends — a cohort nobody has
    written to is the most actionable row in the table and it is invisible in
    any view built from sends alone. Cohorts written to but no longer in the
    catalogue appear too, flagged, because a send nobody can account for is
    worth more attention than one they can.
    """
    got = segments.for_tenant(tenant)
    known = {s["key"]: s for s in got.get("segments", [])} if got.get("ok") else {}
    written = ledger.audiences_written_to(tenant, days=days)
    now = dt.datetime.now(dt.timezone.utc)

    rows: list[dict] = []
    for key in sorted(set(known) | set(written)):
        sends = ledger.sends_to(tenant, key, days=days)
        intents = {}
        entities: dict[str, int] = {}
        claims: dict[str, int] = {}
        shapes: list[str] = []
        for s in sends:
            i = s["intent"] or "unknown"
            intents[i] = intents.get(i, 0) + 1
            if s["entity_key"]:
                entities[s["entity_key"]] = entities.get(s["entity_key"], 0) + 1
            for c in s["claim_ids"]:
                claims[c] = claims.get(c, 0) + 1
            shapes.append("|".join(s["shape"]))
        gives = sum(n for i, n in intents.items() if i not in ASKING_INTENTS
                    and i != "unknown")
        asks = sum(n for i, n in intents.items() if i in ASKING_INTENTS)
        last = sends[-1]["at"] if sends else None
        rows.append({
            "segment": key,
            "name": known.get(key, {}).get("name", key),
            "tier": known.get(key, {}).get("tier", ""),
            "in_catalogue": key in known,
            "sends": len(sends),
            "last_at": last,
            "days_since": (round((now - last).total_seconds() / 86400, 1)
                           if last else None),
            "median_gap_days": _median([s["gap_days"] for s in sends
                                        if s["gap_days"] is not None]),
            "intents": dict(sorted(intents.items())),
            "gives": gives, "asks": asks,
            "give_ask_ratio": _ratio(gives, asks),
            "entities": dict(sorted(entities.items(), key=lambda kv: -kv[1])),
            "claims_used": len(claims),
            # The same layout twice running is what the shape column was added
            # to make answerable. Two is enough to be worth saying; the drafter
            # is already shown the last four.
            "repeats_shape": len(shapes) >= 2 and shapes[-1] == shapes[-2]
                             and bool(shapes[-1]),
        })

    brand = _brand(rows, days)
    out = {"ok": True, "tenant": tenant, "days": days,
           "business_model": got.get("business_model", ""),
           "segments": sorted(rows, key=lambda r: (-r["sends"], r["segment"])),
           "brand": brand,
           "findings": _findings(rows, brand, days)}
    # Only when there IS one. An `error: ""` key reads as a failed call to
    # anything checking for the key rather than its value, which is most
    # things — including a check in this repo's own suite, which it tripped.
    if got.get("error"):
        out["error"] = got["error"]
    return out


def _brand(rows: list[dict], days: int) -> dict:
    sends = sum(r["sends"] for r in rows)
    gives = sum(r["gives"] for r in rows)
    asks = sum(r["asks"] for r in rows)
    ents: dict[str, int] = {}
    for r in rows:
        for k, n in r["entities"].items():
            ents[k] = ents.get(k, 0) + n
    with_entity = sum(ents.values())
    top = max(ents.items(), key=lambda kv: kv[1]) if ents else ("", 0)
    return {
        "sends": sends,
        "cohorts_written_to": sum(1 for r in rows if r["sends"]),
        "cohorts_known": len(rows),
        "gives": gives, "asks": asks,
        "give_ask_ratio": _ratio(gives, asks),
        "top_entity": top[0],
        # Share of the sends that featured ANY product, not of all sends — a
        # brand whose emails are mostly stories is not concentrated just
        # because the two that showed a product showed the same one.
        "top_entity_share": (round(top[1] / with_entity, 2)
                             if with_entity else None),
        "products_featured": len(ents),
    }


def _findings(rows: list[dict], brand: dict, days: int) -> list[dict]:
    """What is true, why it matters, and what would change it."""
    out: list[dict] = []

    if not brand["sends"]:
        out.append({
            "what": f"nothing has been sent in {days} days",
            "why": "there is no strategy to read yet — every figure below is "
                   "zero because nothing has happened, which is different "
                   "from a programme that is balanced",
            "fix": "switch on campaign_email for this account, or check the "
                   "Planned list for items waiting on approval"})
        return out

    starved = [r for r in rows
               if r["tier"] == "high_value"
               and (r["days_since"] is None or r["days_since"] > NEGLECT_DAYS)]
    if starved:
        out.append({
            "what": "high-value cohorts with nothing recent: "
                    + ", ".join(r["segment"] for r in starved[:5]),
            "why": f"these are the lists worth the most and none has been "
                   f"written to in {NEGLECT_DAYS} days — a programme drifts "
                   f"towards whichever segment is easiest to write for",
            "fix": "the planner now orders by neglect, so these come first on "
                   "the next tick; nothing to do by hand"})

    ratio = brand["give_ask_ratio"]
    if ratio is not None and ratio < GIVE_ASK_TARGET:
        out.append({
            "what": f"{brand['gives']} gives to {brand['asks']} asks "
                    f"({ratio} per ask)",
            "why": f"below {GIVE_ASK_TARGET} the list is being asked more "
                   f"often than it is given to, which is the pattern that "
                   f"precedes a rising unsubscribe rate rather than a falling "
                   f"open rate — it looks fine until it does not",
            "fix": "the drafter rotates intent per segment; a brand-wide "
                   "imbalance means several segments are asking at once"})
    elif brand["asks"] == 0 and brand["sends"] >= 4:
        out.append({
            "what": f"{brand['sends']} sends and not one of them asked",
            "why": "giving without ever asking is the other failure, and the "
                   "quieter one — a list can be well fed and never told what "
                   "to buy",
            "fix": "set intent=offer on a plan for a warm cohort"})

    share = brand["top_entity_share"]
    if share is not None and share > CONCENTRATION and brand["products_featured"] > 1:
        out.append({
            "what": f"{brand['top_entity']} was the subject of "
                    f"{int(share * 100)}% of the sends that featured a product",
            "why": "one product carrying the programme is a story told by "
                   "accident — usually because it is the one with a "
                   "photograph on file, not the one worth pushing",
            "fix": "run the catalogue sync so more products have imagery, or "
                   "set Featured entity on the next few plans"})

    repeat = [r["segment"] for r in rows if r["repeats_shape"]]
    if repeat:
        out.append({
            "what": "same layout twice running for: " + ", ".join(repeat[:5]),
            "why": "the owner's complaint about the first live sends was that "
                   "every email was the same shape; this is that, measured",
            "fix": "nothing by hand — the drafter is shown recent shapes and "
                   "asked to differ. Recurring here means the format is "
                   "narrow, not that the check is off"})

    stray = [r["segment"] for r in rows if r["sends"] and not r["in_catalogue"]]
    if stray:
        out.append({
            "what": "sends to cohorts this business model does not have: "
                    + ", ".join(stray[:5]),
            "why": "either the model changed under a running programme or "
                   "something is targeting a segment by hand — both are worth "
                   "knowing, and neither shows up in a catalogue-shaped view",
            "fix": "check Business model on the account, or the plans that "
                   "named those segments"})
    return out
