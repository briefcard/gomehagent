"""Conversations going quiet, turned into moments. The second producer.

This file knows about threads, last touches and open enquiries. It has no
concept of a cart, a checkout or an order, and it will never acquire one — its
sibling producer watches Shopify and knows nothing about conversations. Neither
knows what a moment is FOR. That is the point: a venue enquiry going quiet and
a cart going cold land in the same table from two watchers with no shared
vocabulary, which is the only real evidence that the spine underneath them is
vertical-neutral rather than a commerce feature wearing a general name.

**Why a sweep and not an event.** There is no notification when nothing
happens. Going quiet is the absence of a touch, so it can only be noticed by
looking — which makes this producer a tick job, and makes `last_touch_at` the
signal's timestamp rather than the moment we happened to look. Filing with
`occurred_at=last_touch_at` is what makes the catalogue's `due_after_hours`
mean "three days after they last heard from us" instead of "three days after a
cron happened to run".

**KNOW WHAT `last_touch_at` ACTUALLY MEANS.** It has exactly one writer —
`conversation.record_touch`, called from exactly one place, `responder.send`,
on an OUTBOUND reply. Nothing records an inbound message against it. So this
producer detects "we have not replied in N days", not "the thread has been
silent for N days", and the catalogue entry is worded that way deliberately.

Two consequences worth carrying:

  · A thread where the customer wrote last and we never answered looks quiet
    here, and the right response to it is a person replying, not a marketing
    nudge. Today it would file a moment.
  · A reply the owner sends from Gmail by hand never moves `last_touch_at`, so
    the thread reads as quiet when it is not.

Both are fixed by the same thing — recording inbound touches, and outbound
ones sent outside this system — and neither is fixed here, because inventing a
second writer for a field with one owner is how two ideas of "last touch" get
into one column.
"""
from __future__ import annotations

import datetime as dt

from . import db, moments, tenants

#: What this producer files. Named here so `moments.CATALOG` can be checked
#: against something rather than trusted.
PRODUCES = ("enquiry_quiet",)


def sweep(tenant: str = "", *, limit: int = 500) -> dict:
    """Open enquiries nobody has touched lately, filed as moments.

    Only for accounts whose model actually declares the moment — a shop has
    conversations too, and filing `enquiry_quiet` for one would be this
    producer deciding what a moment means for a vertical it knows nothing
    about. `moments.record` would refuse it anyway; asking first keeps the
    refusals out of the logs.
    """
    keys = ([tenant] if tenant
            else [t.key for t in tenants.all_tenants()])
    filed, skipped = [], 0
    for key in keys:
        t = tenants.get(key)
        model = (getattr(t, "business_model", "") or "").strip()
        sp = moments.spec(model, "enquiry_quiet")
        if not sp:
            continue
        filed_here, n = _sweep_one(key, sp, limit)
        filed += filed_here
        skipped += n
    return {"ok": True, "filed": len(filed), "moments": filed,
            "already_open": skipped}


def _sweep_one(tenant: str, sp: dict, limit: int) -> tuple[list, int]:
    now = db.utcnow()
    quiet_before = now - dt.timedelta(hours=sp["due_after_hours"])
    # PAST THIS, IT IS NOT A MOMENT, IT IS A POST-MORTEM. A thread quiet for
    # longer than the whole window would file already-expired — a row that can
    # never be served and only makes `due()` slower. The honest answer to a
    # six-week-old stalled enquiry is that this system missed it.
    too_old = now - dt.timedelta(hours=sp["expires_after_hours"])

    out, skipped = [], 0
    with db.SessionLocal() as s:
        rows = (s.query(db.Conversation)
                .filter(db.tenant_filter(db.Conversation, tenant),
                        db.Conversation.status == "open",
                        db.Conversation.last_touch_at.isnot(None),
                        db.Conversation.last_touch_at <= quiet_before,
                        db.Conversation.last_touch_at > too_old)
                .order_by(db.Conversation.last_touch_at.asc())
                .limit(limit).all())
        seen = [(c.id, c.contact_id, c.entity_key, c.subject,
                 db.as_utc(c.last_touch_at)) for c in rows]
        emails = {}
        ids = [c[1] for c in seen if c[1]]
        if ids:
            for con in s.query(db.Contact).filter(db.Contact.id.in_(ids)).all():
                emails[con.id] = (con.email or "").strip().lower()

    for conv_id, contact_id, entity_key, subject, last in seen:
        who = emails.get(contact_id or "", "")
        if not who:
            skipped += 1
            continue
        # The dedup key carries the DAY THE SILENCE STARTED, not the
        # conversation alone. A thread that stalls, gets a reply, and stalls
        # again a month later is two moments and should be; the same thread
        # seen by four sweeps in four days is one.
        got = moments.record(
            tenant, "enquiry_quiet", who,
            dedup_key=f"enquiry_quiet:{conv_id}:{last.date().isoformat()}",
            entity_key=entity_key or "", contact_id=contact_id or "",
            conversation_id=conv_id, source="inbox", occurred_at=last,
            payload={"subject": subject or "",
                     "quiet_since": last.isoformat()})
        if got.get("ok") and got.get("created"):
            out.append(got["moment_id"])
        else:
            skipped += 1
    return out, skipped
