"""Shopify commerce events, turned into moments. One producer, one vertical.

This file knows about carts, checkouts and orders. It knows **nothing** about
what a moment is for, which planner will read it, or that a venue exists — it
files rows into `moments` and stops. Its sibling producer watches conversations
going quiet and has no concept of a cart. That mutual ignorance is the whole
proof that the moment spine is real rather than a commerce feature with a
generic name on it: if either producer had to know what the other was for, the
abstraction would already have failed.

**The rule that matters most here is the one that CLOSES moments.** A cart
going cold and the same person checking out twenty minutes later are the same
story, and a system that files the first and never hears the second writes to
somebody about a basket they already paid for. That is not a wasted send; it is
the send that tells a customer nobody is paying attention. So `orders/create`
suppresses the open cart moment for that person, and it is the reason this
producer subscribes to a topic it files nothing from.
"""
from __future__ import annotations

from . import db, moments

#: Topics this producer can do something with. Anything else is acknowledged
#: and ignored — an unknown topic is not an error, and refusing it would look
#: like a broken endpoint to Shopify's retries.
TOPICS = ("checkouts/create", "checkouts/update", "orders/create",
          "orders/paid", "orders/fulfilled")


def _email(payload: dict) -> str:
    """The buyer's address, wherever this topic happens to carry it."""
    for path in (("customer", "email"), ("email",), ("contact_email",)):
        cur: object = payload
        for k in path:
            cur = (cur or {}).get(k) if isinstance(cur, dict) else None
        if isinstance(cur, str) and cur.strip():
            return cur.strip().lower()
    return ""


def _entity_key(payload: dict) -> str:
    """The FIRST line item's handle — what the message would be about.

    One, not all of them. A moment is about a thing; a message that opens by
    listing everything in a basket is a receipt, and the person already has
    one. The rest of the basket stays in `payload` for anything that wants it.
    """
    items = payload.get("line_items") or []
    if not items or not isinstance(items[0], dict):
        return ""
    it = items[0]
    return str(it.get("handle") or it.get("product_handle")
               or it.get("sku") or "").strip()


def handle(topic: str, shop: str, payload: dict) -> dict:
    """One verified Shopify delivery — file, close, or do nothing.

    Never raises and never refuses. This is a webhook: Shopify retries for days
    on anything that is not a 200, so a payload we cannot read is a row we do
    not file, not a flood we invite.
    """
    from . import shopify_webhooks as swh
    tenant = swh._tenant_for_shop(shop)
    if not tenant:
        return {"ok": False, "why": f"no account is connected to {shop!r}"}
    who = _email(payload)
    if not who:
        # Genuinely common and not a fault: an anonymous checkout has nobody
        # to write to. A moment without an identity would be a signal nothing
        # could ever act on.
        return {"ok": True, "filed": [], "why": "no customer email on the "
                                                "payload — nobody to write to"}

    if topic in ("orders/create", "orders/paid"):
        return {"ok": True, "filed": [], "closed": _order_supersedes(tenant, who)}

    if topic == "orders/fulfilled":
        # `orders_count` is Shopify's own tally for this customer and is on the
        # order payload. Reading it rather than counting orders ourselves keeps
        # this producer stateless, which is what lets it be replayed safely.
        n = ((payload.get("customer") or {}).get("orders_count") or 0)
        if int(n or 0) != 1:
            return {"ok": True, "filed": [],
                    "why": f"not a first order (orders_count={n})"}
        got = moments.record(
            tenant, "first_order_landed", who,
            dedup_key=f"first_order_landed:{payload.get('id') or payload.get('order_number')}",
            entity_key=_entity_key(payload), source="commerce",
            payload={"order_number": payload.get("order_number"),
                     "line_items": len(payload.get("line_items") or [])})
        return {"ok": True, "filed": [got], "closed": 0}

    if topic in ("checkouts/create", "checkouts/update"):
        # ONE MOMENT PER CHECKOUT, not per delivery. Shopify sends
        # `checkouts/update` on every edit, so the dedup key is the checkout
        # itself — otherwise a shopper changing their mind four times becomes
        # four identical moments and, later, four emails.
        token = payload.get("token") or payload.get("id")
        if not token:
            return {"ok": True, "filed": [], "why": "no checkout token"}
        got = moments.record(
            tenant, "cart_cooling", who, dedup_key=f"cart_cooling:{token}",
            entity_key=_entity_key(payload), source="commerce",
            payload={"items": len(payload.get("line_items") or []),
                     "currency": payload.get("currency") or ""})
        return {"ok": True, "filed": [got], "closed": 0}

    return {"ok": True, "filed": [], "why": f"nothing to do for {topic!r}"}


def _order_supersedes(tenant: str, who: str) -> int:
    """They bought. Close every open cart moment for this person.

    The one thing this producer does that files nothing. Without it the cart
    moment stays open, comes due five hours later, and asks somebody to finish
    a purchase they have already made — which reads, correctly, as nobody
    watching.

    Closed as `suppressed` with a reason rather than deleted: "we chose not to
    write to this person, because they bought" is exactly the kind of fact a
    frequency rule has to be auditable against.
    """
    n = 0
    with db.SessionLocal() as s:
        rows = (s.query(db.Moment)
                .filter(db.tenant_filter(db.Moment, tenant),
                        db.Moment.person_key == who,
                        db.Moment.kind == "cart_cooling",
                        db.Moment.status == "open").all())
        ids = [r.id for r in rows]
    for mid in ids:
        if moments.close(mid, "suppressed", "they ordered — the cart is not cold"):
            n += 1
    return n
