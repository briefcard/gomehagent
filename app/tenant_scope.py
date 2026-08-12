"""Attribute the operational tables to a client.

Twenty of the thirty-one models predate the tenant registry. `_auto_migrate`
adds the column but cannot know what belongs in it — the §2.8 failure mode,
where a migration lands, the tests pass, and behaviour silently regresses
because every existing row came back empty.

So this fills what is *derivable* and refuses the rest:

    account / alias  ->  Tenant.gmail_alias      an inbox belongs to one client
    domain           ->  Tenant.domain           a site belongs to one client
    scope / thread   ->  Tenant.key              'system:baci:blog' names it
    Approval.payload ->  either of the above     the call sites record one
    Contact.entity   ->  Tenant.key              the old vocabulary, mapped

Everything else — shipments, RFQs, documents, usage, WhatsApp lines — has no
field that says whose it is. Those rows stay `UNASSIGNED` and are counted in
`report()`. Guessing an owner for a shipment is precisely the invention the
platform exists to refuse, and a wrongly attributed row is worse than an
unattributed one because nothing downstream will ever question it.

Note the distinction that matters for the ones left over: for `doc_index` the
client was *known at write time* (Drive is looked up per inbox) and simply not
persisted. That is not missing history, it is a missing column on the writer —
and no backfill can recover it. Fix those at the source; the past stays blank.

Idempotent: only ever writes rows that are still unassigned.
"""
from __future__ import annotations

from . import db

# Rows we cannot attribute from any field they carry. Named explicitly so the
# list is a decision rather than an oversight.
UNDERIVABLE = {
    "shipments": "an import is Gomeh's own or a client's — only he knows which",
    "rfqs": "follows its shipment",
    "doc_index": "the alias WAS known when the file was filed (Drive is per-inbox) "
                 "but was never stored — fix the writer, not the history",
    "usage": "attribute at call time; historical rows cannot be recovered",
    "wa_messages": "one WhatsApp line, no client context",
}

# Approval payloads are free-form JSON, but the call sites are not: they carry
# the inbox as `account`/`alias` or the site profile as `site`. Only these keys
# are read, and only an unambiguous result is used.
_PAYLOAD_INBOX_KEYS = ("account", "alias")
_PAYLOAD_KEY_KEYS = ("site", "tenant", "client")

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


def resolve(alias: str = "", payload: dict | None = None, key: str = "") -> str:
    """Best-effort tenant for a row about to be written, or "".

    The same rules the backfill uses, available at write time — which is the
    only place attribution is ever cheap. Every row written without it becomes
    history that no later pass can recover: `usage` and `doc_index` both knew
    their client at the moment they were created and stored it nowhere.

    Returns "" rather than a guess, and "" rather than a coin-flip when two
    signals disagree.
    """
    by_alias, _by_domain, keys = _lookups()
    found = set()
    if alias:
        hit = by_alias.get(alias)
        if hit:
            found.add(hit)
    if key:
        raw = str(key).strip().lower()
        hit = raw if raw in keys else _ENTITY_MAP.get(raw, "")
        if hit:
            found.add(hit)
    if isinstance(payload, dict):
        for k in _PAYLOAD_INBOX_KEYS:
            hit = by_alias.get(str(payload.get(k) or ""))
            if hit:
                found.add(hit)
        for k in _PAYLOAD_KEY_KEYS:
            raw = str(payload.get(k) or "").strip().lower()
            hit = raw if raw in keys else _ENTITY_MAP.get(raw, "")
            if hit:
                found.add(hit)
    return found.pop() if len(found) == 1 else ""


def _derive(s) -> list[tuple[str, object, str]]:
    """Every unassigned row we can attribute, as (table, row, derived key).

    The single source of truth for what the backfill would do. `backfill()`
    applies these and `preview()` counts them, so a dry run cannot disagree
    with the write it is previewing — the two drifting apart is how a preview
    becomes worse than no preview at all.
    """
    by_alias, by_domain, keys = _lookups()
    out: list[tuple[str, object, str]] = []

    def _scan(model, resolve) -> None:
        for r in s.query(model).filter(model.tenant == db.UNASSIGNED).all():
            key = resolve(r)
            if key:
                out.append((model.__tablename__, r, key))

    # An inbox belongs to exactly one client.
    for model, field in ((db.EmailLog, "account"), (db.Deadline, "account"),
                         (db.FollowUp, "account"), (db.VoiceProfile, "alias"),
                         (db.Expense, "account")):
        _scan(model, lambda r, f=field: by_alias.get(getattr(r, f) or ""))

    # An approval records what it was about. The payload is free-form, but the
    # call sites consistently put the inbox or the site profile in it.
    def _from_payload(r):
        p = r.payload if isinstance(r.payload, dict) else {}
        found = set()
        for k in _PAYLOAD_INBOX_KEYS:
            hit = by_alias.get(str(p.get(k) or ""))
            if hit:
                found.add(hit)
        for k in _PAYLOAD_KEY_KEYS:
            raw = str(p.get(k) or "").strip().lower()
            hit = raw if raw in keys else _ENTITY_MAP.get(raw, "")
            if hit:
                found.add(hit)
        return found.pop() if len(found) == 1 else ""   # ambiguity names nothing

    _scan(db.Approval, _from_payload)

    # A site belongs to exactly one client.
    _scan(db.SeoSnapshot, lambda r: by_domain.get(_norm_domain(r.domain)))
    _scan(db.SeoSiteConfig,
          lambda r: (r.site if r.site in keys else "")
          or by_domain.get(_norm_domain(r.domain)))

    # The key already names the client.
    for model, field in ((db.Memory, "scope"), (db.ChatMessage, "thread"),
                         (db.Lesson, "scope"), (db.SystemDoc, "key")):
        _scan(model, lambda r, f=field: _tenant_in(getattr(r, f), keys))

    # The superseded Contact vocabulary.
    def _from_entity(r):
        raw = (r.entity or "").strip().lower()
        return raw if raw in keys else _ENTITY_MAP.get(raw, "")

    _scan(db.Contact, _from_entity)
    return out


def preview() -> dict:
    """What `backfill()` would write, without writing it.

    Per table: how many rows would be attributed, to whom, and how many would
    still be left over. A table-level "derivable" flag is not this — most
    chat threads are called `admin` and name no client at all, so a rule
    existing for the table says nothing about the rows in it.
    """
    out: dict[str, dict] = {}
    with db.SessionLocal() as s:
        for model in _SCOPED:
            total = s.query(model).filter(model.tenant == db.UNASSIGNED).count()
            if total:
                out[model.__tablename__] = {
                    "unassigned": total, "would_attribute": 0,
                    "would_remain": total, "by_tenant": {}}
        for table, _row, key in _derive(s):
            e = out[table]
            e["would_attribute"] += 1
            e["would_remain"] -= 1
            e["by_tenant"][key] = e["by_tenant"].get(key, 0) + 1
        s.rollback()   # nothing here may persist
    return out


def backfill() -> dict:
    """Fill every derivable tenant. Returns per-table counts of what was set."""
    filled: dict[str, int] = {}
    with db.SessionLocal() as s:
        for table, row, key in _derive(s):
            row.tenant = key
            filled[table] = filled.get(table, 0) + 1
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


def print_preview() -> None:
    rows = preview()
    if not rows:
        print("nothing unassigned — nothing to do")
        return
    print(f"{'table':<20} {'would set':>10} {'left':>7}   to")
    for table, r in sorted(rows.items()):
        if not r["would_attribute"]:
            continue
        who = ", ".join(f"{k}:{n}" for k, n in sorted(r["by_tenant"].items()))
        print(f"{table:<20} {r['would_attribute']:>10} {r['would_remain']:>7}   {who}")
    untouched = {t: r for t, r in rows.items() if not r["would_attribute"]}
    if untouched:
        print("\nno rule reaches these rows — they stay unassigned:")
        for table, r in sorted(untouched.items()):
            print(f"  {table:<18} {r['unassigned']:>6}   {UNDERIVABLE.get(table, '')}")
