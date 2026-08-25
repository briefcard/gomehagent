"""Moments — a known person is in a window where a message is welcome.

Every email this system sends today is SCHEDULED: `planner.campaign_rollout`
picks a segment and a date. Competitors trigger on shopper events, which reads
as better copy and mostly is better TIMING. This is the spine for triggered
sends.

**The constraint that shapes all of it:** this platform serves an e-commerce
store, a venue, a B2B specifier and a digital-products account. A property
rental has no carts; it has enquiries that go quiet and dates that expire. So
the abstraction is the WINDOW, never "abandoned cart" — name it after the cart
and the venue can never use it.

Keyed on `Tenant.business_model`, exactly like `segments.CATALOG`, and for the
same reason: what counts as a moment follows from what KIND of business it is,
so onboarding a client of a known model gets that model's moments for free and
adding a model is a row here rather than a per-client fork.

Each moment declares:

    key                 stable id, and the `Moment.kind` a producer files
    name                what an operator calls it
    definition          the window in plain words — the criteria, not a query
    source              the CAPABILITY a producer needs to see it at all:
                        "commerce" | "inbox" | "esp" | "crm". Note this is the
                        capability axis from `tenants.CAPABILITIES`, NOT the
                        `segments.CATALOG` source axis — a segment may come
                        from "lifecycle", which is a way of reading data we
                        already hold; a moment needs something to be WATCHING.
    segment             the `segments.CATALOG` key this moment belongs to
    producer            the module that FILES it, or "" — see below

    due_after_hours     how long after the signal a message becomes welcome
    expires_after_hours after which it must not be acted on at all

**Why two delays and not one.** A cart is not cold the instant it is abandoned
— writing then reads as surveillance rather than service, and the person is
very often still in the tab. And a moment is perishable by definition: acting
on a fortnight-old enquiry is worse than missing it, because it proves nobody
was looking. `due_after_hours` is manners; `expires_after_hours` is honesty.

**`producer` is declared because absence is invisible otherwise.** A moment
kind with nothing watching for it looks exactly like a moment kind whose
window has simply not opened for anybody yet: the table is empty either way.
Naming the producer turns "nothing is watching for this" into something
`for_tenant` can report and a test can check, which is the difference between
a catalogue and a wish list. `""` is an honest, expected value — several
entries below are declared and unwatched on purpose, so the shape of the model
is complete before the plumbing is.

**`segment` is the bridge, and it is what keeps this cheap.** A moment does not
get its own drafter, its own claims or its own validator. It resolves to a
segment, and the campaign path takes it from there — same coherence contract,
same banned-claims check, same repair loop. A second generator would be a
second place for a false claim to get out.

**A MOMENT DOES NOT SEND. IT INFORMS THE PLAN.** This is the correction that
matters most here, and it was learned the expensive way: the first cut filed
one plan per PERSON, and every one of those plans drafted a campaign bound to
`segments.esp_id_for(...)` — the whole segment. Two people with cold carts
became two identical sends to the entire list, and one venue enquiry going
quiet would have written to every warm enquiry on file.

That is not a bug in the planner, it is what the sending surface is. Omnisend
campaigns target a SEGMENT; per-contact logic lives in Automations, which this
codebase does not push events to (`esp.py` says so at the top). Until it does,
1:1 triggered email is not a thing this system can do, and pretending
otherwise sends the mistake to real customers.

So moments aggregate. `pressure()` answers "how many people are in the same
window right now, and what are they about", and `planner.campaign_rollout`
reads it to decide WHICH segment is worth a campaign and WHEN. One planner,
one queue, one decision about who gets written to — which is why a moment and
a campaign cannot collide: there is no second sender to collide with.

**`MIN_PRESSURE` is the honesty floor.** Below it nothing is proposed. A
segment send on behalf of three people is a message to a thousand about
something true of three, and the right response to a handful of stalled
enquiries is a person answering them, not a campaign. Those moments stay open
and are reported, rather than being spent.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.exc import IntegrityError

from . import db, tenants

# ---------------------------------------------------------------------------
# The catalog.
#
# `ecom_inventory` and `local_venue` are both here from the first line on
# purpose. With one vertical the vertical bakes into the generic layer and
# nobody finds out for a year — the venue's moments are the proof that nothing
# above this file knows what a cart is.
# ---------------------------------------------------------------------------
CATALOG: dict[str, list[dict]] = {
    "ecom_inventory": [
        dict(key="cart_cooling", name="Cart gone cold", source="commerce",
             segment="cart_abandoners", producer="commerce_events",
             definition="Added to a cart and did not check out. Cold, not "
                        "abandoned — most of these people are still deciding.",
             due_after_hours=5, expires_after_hours=72),
        dict(key="browsed_no_cart", producer="", name="Looked, did not add", source="commerce",
             segment="engaged_non_buyers",
             definition="Repeated views of one product with nothing added. "
                        "Interest without a decision — usually a question "
                        "nobody answered.",
             due_after_hours=24, expires_after_hours=7 * 24),
        dict(key="first_order_landed", name="First order just arrived",
             source="commerce", segment="first_time_buyers",
             producer="commerce_events",
             definition="A first order was delivered. The window where a "
                        "buyer is most willing to hear from the brand, and "
                        "the one most often spent on nothing.",
             due_after_hours=48, expires_after_hours=14 * 24),
        dict(key="back_in_stock", producer="", name="Back in stock, and they wanted it",
             source="commerce", segment="engaged_non_buyers",
             definition="Something a known person looked at while it was "
                        "unavailable can be bought again. The rare moment "
                        "where the message is unambiguously useful.",
             due_after_hours=1, expires_after_hours=10 * 24),
    ],
    "local_venue": [
        # THE CHEAPEST SECOND PRODUCER, and the one that proves the
        # abstraction: it needs only `Conversation.last_touch_at`, which is
        # already maintained, and it shares no concept whatsoever with a cart.
        dict(key="enquiry_quiet", name="Enquiry gone quiet", source="inbox",
             segment="hot_enquiries", producer="inbox_events",
             definition="An open enquiry we have not replied to in days. Not "
                        "a lost booking yet — a conversation that stalled, "
                        "usually on one unanswered question.",
             due_after_hours=72, expires_after_hours=21 * 24),
        dict(key="date_approaching", producer="", name="Held date coming up", source="inbox",
             segment="corporate_planners",
             definition="A date discussed in an enquiry is near and nothing "
                        "is confirmed. The window closes on its own, which is "
                        "what makes the urgency real rather than invented.",
             due_after_hours=0, expires_after_hours=14 * 24),
        dict(key="event_just_held", producer="", name="Their event just happened",
             source="inbox", segment="past_bookers",
             definition="An event has taken place. The one moment a venue can "
                        "ask for a review or a rebooking and be welcome.",
             due_after_hours=48, expires_after_hours=21 * 24),
    ],
    "b2b_spec": [
        dict(key="sample_no_followup", producer="", name="Sample sent, nothing since",
             source="inbox", segment="sample_requested",
             definition="A sample went out and the thread stopped. The "
                        "specifier is usually mid-project and waiting on "
                        "something else entirely.",
             due_after_hours=7 * 24, expires_after_hours=45 * 24),
        dict(key="quote_ageing", producer="", name="Quote going stale", source="inbox",
             segment="quote_no_order",
             definition="A quote was issued and has neither been accepted nor "
                        "refused. Quotes have real expiry dates, which is the "
                        "only honest urgency in this catalogue.",
             due_after_hours=5 * 24, expires_after_hours=30 * 24),
    ],
    "digital_products": [
        dict(key="trial_stalling", producer="", name="Trial not being used", source="crm",
             segment="trial_no_convert",
             definition="A trial started and the product has barely been "
                        "opened. Converting this is a help problem, not a "
                        "sales one.",
             due_after_hours=3 * 24, expires_after_hours=21 * 24),
        dict(key="limit_reached", producer="", name="Reached what their tier allows",
             source="crm", segment="upsell_candidates",
             definition="Hit a ceiling the next tier lifts. The upgrade is a "
                        "thing they are already reaching for.",
             due_after_hours=2, expires_after_hours=14 * 24),
    ],
}

#: Every status a moment can be in, and the three that are not `open`.
CLOSED = ("consumed", "expired", "suppressed")


# ---------------------------------------------------------------------------
# The catalog, read
# ---------------------------------------------------------------------------

def by_model(model: str) -> list[dict]:
    """The moment templates for one business model, soonest-due first."""
    rows = list(CATALOG.get(model or "", []))
    rows.sort(key=lambda m: (m["due_after_hours"], m["name"]))
    return rows


def spec(model: str, kind: str) -> dict:
    """One moment template, or {} — the declaration behind a filed row."""
    return next((m for m in CATALOG.get(model or "", [])
                 if m["key"] == kind), {})


def for_tenant(tenant: str) -> dict:
    """The moments this client's model has, and which it can actually watch.

    Refuses BY NAME when `business_model` is unset, and names the control that
    sets it — the same refusal `segments.for_tenant` makes, for the same
    reason: guessing the model (a venue is not a shop) is the one error that
    makes every row below it wrong.

    `watchable` is the honest split. A moment whose `source` capability is not
    connected is not missing and not broken — nothing is WATCHING for it, which
    is a one-connection fix and a different problem from "this model has no
    such moment".
    """
    t = tenants.get(tenant)
    if not t:
        return {"ok": False, "error": f"unknown account {tenant!r}"}
    model = (t.business_model or "").strip()
    if not model:
        return {"ok": False, "error": (
            f"{tenant} has no business_model set — the control is on the "
            f"Connections tab, on this account's card (“Business "
            f"model”, one save); its moments follow from it.")}
    rows = by_model(model)
    if not rows:
        return {"ok": False, "error": (
            f"no moment catalog for business model {model!r} yet — add one in "
            f"moments.CATALOG.")}
    caps = tenants.capabilities(tenant)
    # THREE STATES, NOT TWO. "Live" needs both a connection AND something
    # watching; a moment can fail either test, and the fixes are completely
    # different — one is a client connecting their store, the other is a
    # producer nobody has written yet. Collapsing them into "not available"
    # is how a missing producer gets mistaken for a missing integration and
    # waits a year for the wrong person to fix it.
    return {"ok": True, "tenant": tenant, "business_model": model,
            "moments": rows,
            "live": [m for m in rows
                     if caps.get(m["source"]) and m["producer"]],
            "unwatched": [dict(m, why=f"no {m['source']} connection")
                          for m in rows
                          if m["producer"] and not caps.get(m["source"])],
            "unproduced": [dict(m, why="declared, but nothing files it yet")
                           for m in rows if not m["producer"]]}


# ---------------------------------------------------------------------------
# The producer's door
# ---------------------------------------------------------------------------

def record(tenant: str, kind: str, person_key: str, *, dedup_key: str,
           source: str = "", entity_key: str = "", contact_id: str = "",
           conversation_id: str = "", occurred_at=None,
           payload: dict | None = None) -> dict:
    """File one moment. Idempotent on `dedup_key`, and refuses unknown kinds.

    **The kind is checked against the catalogue for THIS account's model.** A
    producer filing `cart_cooling` for a venue is a wiring mistake, and the
    only moment it can be caught cheaply is here — a row that no planner can
    ever be asked to consume would otherwise sit in the table looking like
    work nobody got to.

    `due_at` and `expires_at` are computed from the declaration, never passed
    in. A producer knows that something happened; when a message about it
    becomes welcome, and when it stops being honest, are properties of the
    KIND, and letting a caller override them is how two producers end up with
    two different ideas of a cold cart.

    A duplicate returns the row that already exists, with `created: False`.
    Webhooks retry and pollers overlap; that is normal traffic, not an error.
    """
    t = tenants.get(tenant)
    model = (getattr(t, "business_model", "") or "").strip() if t else ""
    sp = spec(model, kind)
    if not sp:
        known = ", ".join(m["key"] for m in by_model(model)) or "none"
        return {"ok": False, "error": (
            f"{kind!r} is not a moment for a {model or 'model-less'} account "
            f"— {tenant} can have: {known}. Add it to moments.CATALOG or file "
            f"the right kind.")}
    person_key = (person_key or "").strip().lower()
    if not person_key:
        return {"ok": False, "error": (
            "a moment is a message to a NAMED person — without an identity "
            "there is nobody to write to, and a row here would be a signal "
            "nothing could ever act on.")}

    at = occurred_at or db.utcnow()
    row = db.Moment(
        tenant=tenant, kind=kind, person_key=person_key,
        contact_id=contact_id, entity_key=entity_key,
        conversation_id=conversation_id, source=source or sp["source"],
        dedup_key=dedup_key, occurred_at=at,
        due_at=at + dt.timedelta(hours=sp["due_after_hours"]),
        expires_at=at + dt.timedelta(hours=sp["expires_after_hours"]),
        status="open", payload=dict(payload or {}))
    with db.SessionLocal() as s:
        s.add(row)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            prior = (s.query(db.Moment)
                     .filter(db.Moment.tenant == tenant,
                             db.Moment.dedup_key == dedup_key).first())
            return {"ok": True, "created": False,
                    "moment_id": prior.id if prior else "",
                    "note": "already filed"}
        s.refresh(row)
        s.expunge_all()
    return {"ok": True, "created": True, "moment_id": row.id,
            "kind": kind, "due_at": row.due_at, "expires_at": row.expires_at}


# ---------------------------------------------------------------------------
# The consumer's door
# ---------------------------------------------------------------------------

def due(tenant: str = "", *, kind: str = "", limit: int = 200) -> list[db.Moment]:
    """Open moments whose window is OPEN NOW — due has passed, expiry has not.

    Oldest first: a moment that has been waiting longest is the one closest to
    going stale, and serving the newest first is how a backlog quietly turns
    into a table of things that expired while something newer was answered.
    """
    now = db.utcnow()
    with db.SessionLocal() as s:
        q = (s.query(db.Moment)
             .filter(db.Moment.status == "open",
                     db.Moment.due_at <= now,
                     db.Moment.expires_at > now))
        if tenant:
            q = q.filter(db.tenant_filter(db.Moment, tenant))
        if kind:
            q = q.filter(db.Moment.kind == kind)
        rows = q.order_by(db.Moment.due_at.asc()).limit(limit).all()
        s.expunge_all()
    return rows


#: How many people must be in the same window before a SEGMENT campaign is an
#: honest response to it. Below this, the moments stay open and are reported
#: for a person to handle one at a time.
#:
#: Five is a judgement, not a measurement, and it is deliberately on the shy
#: side: the cost of proposing too early is a thousand people receiving a
#: message that was true of four, and the cost of waiting is that a window
#: closes with nobody written to — which is the same outcome as today.
MIN_PRESSURE = 5


def pressure(tenant: str) -> list[dict]:
    """How much live signal each SEGMENT is carrying right now.

    The whole of what a moment contributes to planning. Not "send this person
    an email" — there is no surface for that — but "twenty-three people are in
    the same window, the earliest of them closes on Thursday, and nine of them
    are about the same product".

    Ordered by how many people, because that is the order a planner should
    care about. `ready` says whether the count clears `MIN_PRESSURE`; a caller
    that ignores it will propose a campaign to a whole list on behalf of three
    people, which is the failure this function exists to make hard.
    """
    rows = due(tenant, limit=2000)
    if not rows:
        return []
    from . import tenants as _tn
    model = (getattr(_tn.get(tenant), "business_model", "") or "").strip()
    by_seg: dict[str, dict] = {}
    for m in rows:
        sp = spec(model, m.kind)
        if not sp:
            continue                 # catalogue moved under a filed row
        got = by_seg.setdefault(sp["segment"], {
            "segment": sp["segment"], "people": set(), "kinds": {},
            "entities": {}, "moment_ids": [], "earliest_expiry": None})
        got["people"].add(m.person_key)
        got["kinds"][m.kind] = got["kinds"].get(m.kind, 0) + 1
        if m.entity_key:
            got["entities"][m.entity_key] = got["entities"].get(m.entity_key, 0) + 1
        got["moment_ids"].append(m.id)
        exp = db.as_utc(m.expires_at)
        if got["earliest_expiry"] is None or exp < got["earliest_expiry"]:
            got["earliest_expiry"] = exp

    out = []
    for g in by_seg.values():
        ents = sorted(g["entities"].items(), key=lambda kv: (-kv[1], kv[0]))
        n = len(g["people"])
        out.append({
            "segment": g["segment"],
            # PEOPLE, not moments. One person who abandoned four carts is one
            # reason to write, and counting the carts would let a single
            # indecisive shopper trip a campaign to the whole list.
            "people": n,
            "moments": len(g["moment_ids"]),
            "kinds": dict(sorted(g["kinds"].items())),
            # The thing most of them have in common, when there is one — the
            # planner hands it to the drafter as the featured entity.
            "top_entity": ents[0][0] if ents else "",
            "top_entity_people": ents[0][1] if ents else 0,
            "earliest_expiry": g["earliest_expiry"],
            "moment_ids": g["moment_ids"],
            "ready": n >= MIN_PRESSURE,
            "why_not": "" if n >= MIN_PRESSURE else (
                f"{n} person(s) in this window — under {MIN_PRESSURE}, a "
                f"campaign to the whole segment would be a message to "
                f"everyone about something true of {n}"),
        })
    out.sort(key=lambda g: (-g["people"], g["segment"]))
    return out


def consumed_for(tenant: str, moment_ids: list[str], ref: str) -> int:
    """Mark the moments that informed one plan. Returns how many closed.

    Closed at PLAN time, not at send time, and closed even though no email is
    addressed to any of these people individually. What the row now records is
    true and useful: this window was seen, and it is why that campaign exists.
    Leaving them open would mean the same evidence re-proposing the same
    campaign on every tick for as long as the window lasted.
    """
    n = 0
    for mid in moment_ids:
        if close(mid, "consumed", f"informed {ref}", consumed_by=ref):
            n += 1
    return n


def close(moment_id: str, status: str, why: str = "",
          consumed_by: str = "") -> bool:
    """Take one moment out of the open set, and say which way it went.

    `suppressed` is a real outcome and not a deletion — "we chose not to write
    to this person" is a fact a frequency rule has to be auditable against, and
    a row that vanishes when a cap declines it makes that impossible.
    """
    if status not in CLOSED:
        return False
    with db.SessionLocal() as s:
        row = s.get(db.Moment, moment_id)
        if not row or row.status != "open":
            return False
        row.status, row.closed_reason = status, why
        row.closed_at = db.utcnow()
        if consumed_by:
            row.consumed_by = consumed_by
        s.commit()
    return True


def expire_stale(tenant: str = "") -> int:
    """Close every moment whose window has passed. Returns how many.

    Run on the tick. Without it the table only ever grows and `due()` gets
    slower for ever — but the real cost is that "what is open" stops meaning
    anything, and an operator looking at the queue cannot tell live work from
    a year of things nobody got to.
    """
    now = db.utcnow()
    n = 0
    with db.SessionLocal() as s:
        q = (s.query(db.Moment)
             .filter(db.Moment.status == "open", db.Moment.expires_at <= now))
        if tenant:
            q = q.filter(db.tenant_filter(db.Moment, tenant))
        for row in q.all():
            row.status, row.closed_at = "expired", now
            row.closed_reason = "the window closed before anything used it"
            n += 1
        if n:
            s.commit()
    return n


# ---------------------------------------------------------------------------
# Caught at import, because every one of these is a link that reaches nothing
# and stays invisible until the day something tries to follow it.
#
# The `segment` bridge is the load-bearing one. A moment does not draft its own
# email — it resolves to a segment and goes through the unchanged
# `campaign_email` path. A typo here is a moment that files perfectly, sits in
# the queue looking like work, and dies at the moment of consumption with a
# key nothing recognises.
# ---------------------------------------------------------------------------
def _check_catalog() -> None:
    from . import segments as _seg
    for _model, _rows in CATALOG.items():
        _known = {s["key"] for s in _seg.CATALOG.get(_model, [])}
        assert _known, (f"moments.CATALOG has {_model!r} and segments.CATALOG "
                        f"does not — a moment for a model with no segments "
                        f"can never be drafted")
        for _m in _rows:
            assert _m["segment"] in _known, (
                f"moment {_m['key']!r} points at segment {_m['segment']!r}, "
                f"which {_model} does not have — it would file and then die "
                f"unconsumable. Known: {sorted(_known)}")
            assert _m["source"] in tenants.CAPABILITIES, (
                f"moment {_m['key']!r} needs capability {_m['source']!r}, "
                f"which is not one of {tenants.CAPABILITIES} — nothing could "
                f"ever report it as unwatched")
            assert "producer" in _m, (
                f"moment {_m['key']!r} declares no producer — use \"\" to say "
                f"plainly that nothing files it yet, so it can be REPORTED as "
                f"unproduced instead of looking like a window that has not "
                f"opened")
            # A DAY OF SLACK, NOT A MINUTE. The tick that plans and consumes
            # these runs daily, so a window narrower than 24 hours could open
            # and close between two ticks — filed, never served, and invisible
            # except as a rising count of `expired`. Tying the catalogue to
            # the tick's cadence here is what stops somebody declaring a
            # two-hour moment that silently never fires.
            assert (_m["expires_after_hours"] - _m["due_after_hours"]) >= 24, (
                f"moment {_m['key']!r} is open for "
                f"{_m['expires_after_hours'] - _m['due_after_hours']}h, which "
                f"a DAILY tick can step straight over — widen the window or "
                f"give this kind its own consumer")


_check_catalog()
