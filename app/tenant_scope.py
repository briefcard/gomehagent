"""Attribute the operational tables to a client.

Twenty of the thirty-one models predate the tenant registry. `_auto_migrate`
adds the column but cannot know what belongs in it — the §2.8 failure mode,
where a migration lands, the tests pass, and behaviour silently regresses
because every existing row came back empty.

So this fills what is *derivable* and refuses the rest:

    account / alias  ->  Tenant.gmail_alias      an inbox belongs to one client
    domain           ->  Tenant.domain           a site belongs to one client
    scope / thread   ->  Tenant.key              'system:baci:blog' names it
    Contact.entity   ->  Tenant.key              the old vocabulary, mapped

Everything else — shipments, RFQs, expenses, documents, approvals, usage — has
no field that says whose it is. Those rows stay `UNASSIGNED` and are counted in
`report()`. Guessing an owner for a shipment is precisely the invention the
platform exists to refuse, and a wrongly attributed row is worse than an
unattributed one because nothing downstream will ever question it.

Idempotent: only ever writes rows that are still unassigned.
"""
from __future__ import annotations

from . import db

# Rows we cannot attribute from any field they carry. Named explicitly so the
# list is a decision rather than an oversight.
UNDERIVABLE = {
    "approvals": "no field names the client; set it when the approval is created",
    "shipments": "an import is Gomeh's own or a client's — only he knows which",
    "rfqs": "follows its shipment",
    "expenses": "captured from a receipt, which names a vendor, not a client",
    "doc_index": "the anchor (PO / shipment) implies it, but not reliably",
    "usage": "attribute at call time; historical rows cannot be recovered",
    "wa_messages": "one WhatsApp line, no client context",
}

# Old Contact.entity vocabulary -> tenant key. 'shared' is deliberately absent:
# it meant "applies to all", which is not a tenant, and picking one would be a
# guess. Those rows surface in report() for a human to split.
_ENTITY_MAP = {"saias": "agency", "personal": "agency", "mtw": "agency"}


def _norm_domain(d: str) -> str:
    d = (d or "").strip().lower()
    for prefix in ("https://", "http://", "sc-domain:", "www."):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.rstrip("/").removeprefix("www.")


def _lookups() -> tuple[dict, dict, set]:
    """(gmail_alias -> key, normalised domain -> key, all keys)."""
    with db.SessionLocal() as s:
        rows = s.query(db.Tenant).all()
        by_alias = {t.gmail_alias: t.key for t in rows if t.gmail_alias}
        by_domain = {_norm_domain(t.domain): t.key for t in rows if t.domain}
        keys = {t.key for t in rows}
    return by_alias, by_domain, keys


def _tenant_in(text: str, keys: set) -> str:
    """A tenant key appearing as a whole segment of a scope/thread/doc key.

    Segment-wise, never substring: 'agency' must not be found inside a word,
    and a thread called 'admin' must not match a tenant called 'admin' by
    accident of spelling. Only an exact segment counts.
    """
    if not text:
        return ""
    parts = [p for chunk in str(text).split(":") for p in chunk.split("/")]
    hits = {p for p in parts if p in keys}
    return hits.pop() if len(hits) == 1 else ""   # ambiguous names nothing


def backfill() -> dict:
    """Fill every derivable tenant. Returns per-table counts of what was set."""
    by_alias, by_domain, keys = _lookups()
    filled: dict[str, int] = {}

    def _bump(table: str, n: int) -> None:
        if n:
            filled[table] = filled.get(table, 0) + n

    with db.SessionLocal() as s:
        # --- an inbox belongs to exactly one client ---------------------
        for model, field in ((db.EmailLog, "account"), (db.Deadline, "account"),
                             (db.FollowUp, "account"), (db.VoiceProfile, "alias")):
            n = 0
            for r in s.query(model).filter(model.tenant == db.UNASSIGNED).all():
                key = by_alias.get(getattr(r, field) or "")
                if key:
                    r.tenant, n = key, n + 1
            _bump(model.__tablename__, n)

        # --- a site belongs to exactly one client ------------------------
        n = 0
        for r in s.query(db.SeoSnapshot).filter(
                db.SeoSnapshot.tenant == db.UNASSIGNED).all():
            key = by_domain.get(_norm_domain(r.domain))
            if key:
                r.tenant, n = key, n + 1
        _bump("seo_snapshots", n)

        n = 0
        for r in s.query(db.SeoSiteConfig).filter(
                db.SeoSiteConfig.tenant == db.UNASSIGNED).all():
            key = (r.site if r.site in keys else "") or by_domain.get(_norm_domain(r.domain))
            if key:
                r.tenant, n = key, n + 1
        _bump("seo_site_config", n)

        # --- the key already names the client ---------------------------
        for model, field in ((db.Memory, "scope"), (db.ChatMessage, "thread"),
                             (db.Lesson, "scope"), (db.SystemDoc, "key")):
            n = 0
            for r in s.query(model).filter(model.tenant == db.UNASSIGNED).all():
                key = _tenant_in(getattr(r, field), keys)
                if key:
                    r.tenant, n = key, n + 1
            _bump(model.__tablename__, n)

        # --- the superseded Contact vocabulary --------------------------
        n = 0
        for r in s.query(db.Contact).filter(db.Contact.tenant == db.UNASSIGNED).all():
            raw = (r.entity or "").strip().lower()
            key = raw if raw in keys else _ENTITY_MAP.get(raw, "")
            if key:
                r.tenant, n = key, n + 1
        _bump("contacts", n)

        s.commit()
    return filled


_SCOPED = (db.Approval, db.EmailLog, db.Contact, db.Deadline, db.ChatMessage,
           db.Memory, db.FollowUp, db.Shipment, db.RFQ, db.Expense, db.DocIndex,
           db.Usage, db.WaMessage, db.Lesson, db.SystemDoc, db.SeoSnapshot,
           db.SeoSiteConfig, db.VoiceProfile)


def report() -> dict:
    """What is still unattributed, and whether that is expected.

    An unassigned count is not automatically a problem — most of these tables
    are empty. It is a problem when a system that reports per client is about
    to read one of them.
    """
    out = {}
    with db.SessionLocal() as s:
        for model in _SCOPED:
            table = model.__tablename__
            total = s.query(model).count()
            if not total:
                continue
            blank = s.query(model).filter(model.tenant == db.UNASSIGNED).count()
            out[table] = {
                "total": total, "unassigned": blank,
                "derivable": table not in UNDERIVABLE,
                "why": UNDERIVABLE.get(table, ""),
            }
    return out


def print_report() -> None:
    rows = report()
    if not rows:
        print("every scoped table is empty — nothing to attribute yet")
        return
    print(f"{'table':<20} {'rows':>6} {'unassigned':>11}   note")
    for table, r in sorted(rows.items()):
        note = "" if not r["unassigned"] else (
            r["why"] or "derivable — re-run backfill() once the tenant is wired")
        print(f"{table:<20} {r['total']:>6} {r['unassigned']:>11}   {note}")
