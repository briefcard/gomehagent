"""Shopify's three mandatory privacy webhooks.

Every public app must handle `customers/data_request`, `customers/redact` and
`shop/redact`, and app review checks it. They are not optional and they carry a
legal deadline — thirty days — which is the reason this module records rather
than only acts: a compliance obligation nobody can prove was met is one that
was not met.

**Verified before it is believed.** Shopify signs each delivery with an HMAC of
the RAW body under the app's client secret. Verification runs on the bytes as
received, before any parsing, because `json.loads` then `json.dumps` does not
round-trip byte-for-byte and a digest computed over re-serialised JSON fails on
valid deliveries and — worse — could be made to pass on crafted ones. An
unverified request is answered **401**, which is what Shopify's own tests look
for; answering 200 to anything that arrives is the failure this check exists to
prevent.

**What code can decide, code does. What it cannot, a person is told about.**

`shop/redact` is mechanical: the store's credential and everything we derived
from that store's catalogue are ours to delete, and we delete them.

The customer topics are not. This system stores no Shopify customer records —
customers are read live at the moment of asking, which is why `lookups` exists
— but it does store REPLIES, and a reply may quote an address, an order number
or a name. Deciding whether a sentence in a drafted email is "the customer's
personal data" is a judgement about content, and a redactor that guesses would
either delete a client's correspondence or claim a deletion it did not make.
Both are worse than saying plainly what we hold and asking. So those topics
record the request, report exactly where the address appears, and are queued
for the owner.

Never 500. A webhook endpoint that errors gets retried, and Shopify retries for
days; an exception here would turn one malformed payload into a flood.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

from . import config, db

#: The three Shopify requires. Anything else on this endpoint is recorded and
#: acknowledged rather than refused — a topic we do not know about is not an
#: error, and 401/404 on it would look like a broken endpoint to their tests.
MANDATORY = ("customers/data_request", "customers/redact", "shop/redact")


def verify(raw: bytes, header: str) -> bool:
    """Is this delivery really Shopify's? Over the RAW body, always.

    `compare_digest` rather than `==`: a byte-at-a-time comparison on a
    signature is a timing oracle, and this one is reachable by anybody who
    finds the URL.
    """
    secret = (config.SHOPIFY_CLIENT_SECRET or "").encode()
    if not secret or not header:
        return False
    want = base64.b64encode(
        hmac.new(secret, raw, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(want, header)


def _tenant_for_shop(shop: str) -> str:
    """Which account this store belongs to, or "" if none does."""
    if not shop:
        return ""
    with db.SessionLocal() as s:
        rows = s.query(db.Credential).filter(
            db.Credential.provider == "shopify").all()
        for r in rows:
            if (r.meta or {}).get("domain") == shop:
                return r.tenant
    return ""


def handle(topic: str, shop: str, payload: dict) -> dict:
    """Record the request, do what is unambiguous, name what is not."""
    tenant = _tenant_for_shop(shop)
    acted: list[str] = []
    needs = ""

    if topic == "shop/redact":
        acted, needs = _redact_shop(tenant, shop)
    elif topic == "customers/redact":
        needs = _customer_note(tenant, payload,
                               "delete or redact what is listed above")
    elif topic == "customers/data_request":
        needs = _customer_note(tenant, payload,
                               "send the merchant what is listed above")
    else:
        needs = f"unrecognised topic {topic!r} — recorded, nothing was done"

    with db.SessionLocal() as s:
        s.add(db.ComplianceEvent(topic=topic, shop=shop, tenant=tenant,
                                 payload=payload, acted=acted,
                                 needs_human=needs))
        s.commit()

    # The owner has thirty days and no other way to learn this arrived. Sent
    # through the existing queue rather than directly: this codebase has had
    # the incident where a path that notified per item became a flood.
    if needs:
        try:
            from . import approvals
            approvals.request_approval(
                "privacy_request",
                f"[Shopify] {topic} for {shop or 'an unknown store'}"
                + (f" ({tenant})" if tenant else ""),
                {"topic": topic, "shop": shop, "tenant": tenant,
                 "what_to_do": needs, "body": needs},
                notify=False)
        except Exception:                                        # noqa: BLE001
            pass        # the row is written either way; the queue is a courtesy
    return {"acted": acted, "needs_human": needs, "tenant": tenant}


def _redact_shop(tenant: str, shop: str) -> tuple[list[str], str]:
    """Everything that store gave us, removed. This part IS mechanical.

    Deliberately NOT a tenant wipe. `shop/redact` asks for the shop's data, and
    an account here is a client relationship that may have a mailbox, a
    knowledge base and years of correspondence which did not come from Shopify.
    Deleting those on an uninstall would destroy the client's own material to
    satisfy a request that never covered it.
    """
    acted: list[str] = []
    if not shop:
        return acted, "no shop on the payload — nothing could be identified"
    with db.SessionLocal() as s:
        creds = [r for r in s.query(db.Credential).filter(
            db.Credential.provider == "shopify").all()
            if (r.meta or {}).get("domain") == shop]
        for r in creds:
            s.delete(r)
        if creds:
            acted.append(f"deleted {len(creds)} Shopify credential(s)")
        # What we copied out of that store's catalogue. Matched on
        # `origin="store_sync"`, which is what `catalog_sync` stamps — NOT on
        # the domain, because `source` is sometimes the literal "shopify" and a
        # URL match would silently spare half the rows. Entities are rebuilt by
        # a re-sync if the store ever reconnects, so this loses nothing that is
        # not recoverable from the source.
        if tenant:
            n = (s.query(db.KbEntity)
                 .filter(db.KbEntity.tenant == tenant,
                         db.KbEntity.origin == "store_sync")
                 .delete(synchronize_session=False))
            if n:
                acted.append(f"deleted {n} catalogue entities read from {shop}")
        s.commit()
    if not acted:
        acted.append("nothing was held for that store")
    # The env-group path is not ours to delete from here.
    from . import config as _cfg
    if any((v or {}).get("domain") == shop
           for v in (_cfg.SHOPIFY_STORES or {}).values()):
        return acted, (f"{shop} is ALSO configured in SHOPIFY_STORES_JSON — "
                       f"remove it from the env group by hand; this endpoint "
                       f"cannot edit the service's environment")
    return acted, ""


def _customer_note(tenant: str, payload: dict, verb: str) -> str:
    """Where this customer appears in what we hold, stated rather than guessed.

    Reports a COUNT and the places, never the bodies: the point is to tell a
    person what to look at, and copying correspondence into a compliance row
    would create a second store of exactly the data being asked about.
    """
    who = (payload.get("customer") or {})
    email = str(who.get("email") or "").strip().lower()
    orders = payload.get("orders_requested") or payload.get("orders_to_redact") or []
    if not email:
        return (f"no customer email on the payload — {verb}, using the shop's "
                f"own record of who was asked about")
    hits = []
    with db.SessionLocal() as s:
        q = s.query(db.Output).filter(db.Output.body.ilike(f"%{email}%"))
        if tenant:
            q = q.filter(db.Output.tenant == tenant)
        n = q.count()
        if n:
            hits.append(f"{n} drafted/sent output(s) mention {email}")
        c = s.query(db.Contact).filter(db.Contact.email == email)
        if tenant:
            c = c.filter(db.Contact.tenant == tenant)
        if c.count():
            hits.append(f"a contact record for {email}")
    if orders:
        hits.append(f"{len(orders)} order id(s) named in the request")
    if not hits:
        return (f"we hold no Shopify customer records — they are read live at "
                f"the moment of asking — and nothing here mentions {email}. "
                f"Confirm and close.")
    return (f"{'; '.join(hits)}. These are OUR correspondence, not Shopify "
            f"records; a person must {verb}.")
