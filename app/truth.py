"""THE TRUTH — one value per subject × scope, set by QA from a named source.

BUILD-MAP §3.3 / INITIATIVE-claims-reconciliation.md §4. Statements are what
the site SAYS (`statements`); a fact value is what is TRUE, and only a person
sets one. Two functions are the whole interface every reader uses:

* `resolve(tenant, subject, scope)` — the most specific approved value for a
  scope. A product-level value beats the brand-level one; brand-level is the
  fallback. `follows_source` values are read from the source page's current
  statements, so updating the source of truth on the site moves the truth.
* `compare(statement, truth)` — the ONLY judge of agreement. Pure. "Over 100
  countries" agrees with a truth of 162 (true, if understated); "200+
  countries" does not (an overclaim); "75 countries" does not.

Nothing here decides what is true. `set_value`, `make_source` and
`scope_page` are called by a person's decision (`findings.decide`).
"""
from __future__ import annotations

import datetime as dt

from . import db, statements

#: How bad a disagreement on a subject is, by its area. Legal is P1; a
#: coverage or availability figure is P2 (a customer acts on it); scale
#: figures are P3. Any disagreement with a BINDING (legal-page) value is P1.
CRITICALITY = {"legal": "P1", "coverage": "P2", "scale": "P3"}
#: The plain question a reviewer is asked about each subject.
QUESTIONS = {
    "coverage.countries": "How many countries do we say we serve?",
    "coverage.states": "How many U.S. states do we say we serve?",
    "coverage.crypto_assets": "How many crypto assets do we say we support?",
    "coverage.blockchains": "How many blockchains do we say we support?",
    "coverage.fiat_currencies": "How many fiat currencies do we say we support?",
    "coverage.payment_methods": "How many payment methods do we say we offer?",
    "coverage.markets": "How many markets or regions do we say we serve?",
    "coverage.languages": "How many languages do we say we support?",
    "coverage.currencies": "How many currencies do we say we support?",
    "legal.licences": "How many licences or registrations do we say we hold?",
    "scale.users": "How many users or customers do we say we have?",
    "scale.apps": "How many apps or wallets do we say we are in?",
    "scale.partners": "How many partners or clients do we say we have?",
}


def question(subject: str) -> str:
    return QUESTIONS.get(subject) or f"What is the right figure for {subject.replace('.', ' › ')}?"


def severity(subject: str, binding: bool = False) -> str:
    if binding:
        return "P1"
    return CRITICALITY.get((subject or "").split(".", 1)[0], "P3")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def scope_of(entity: str = "", market: str = "", channel: str = "") -> dict:
    return {"entity": entity or "", "market": (market or "").upper(), "channel": channel or ""}


def scope_label(scope: dict) -> str:
    bits = [f"product {scope['entity']}" if scope.get("entity") else "",
            f"market {scope['market']}" if scope.get("market") else "",
            f"channel {scope['channel']}" if scope.get("channel") else ""]
    return ", ".join(b for b in bits if b) or "brand-wide"


# --- reading the truth ----------------------------------------------------

def values(tenant: str, subject: str = "", include_retired: bool = False) -> list:
    with db.SessionLocal() as s:
        q = s.query(db.KbFactValue).filter(db.tenant_filter(db.KbFactValue, tenant))
        if subject:
            q = q.filter(db.KbFactValue.subject == subject)
        if not include_retired:
            q = q.filter(db.KbFactValue.status == "approved")
        rows = q.order_by(db.KbFactValue.subject, db.KbFactValue.decided_at).all()
        s.expunge_all()
        return rows


def _live(v) -> dict | None:
    """A fact value as {value, number, qualifier}, following its source when
    it follows one. A source that no longer states the subject (or states it
    two ways) yields None — the truth is then unknown, never guessed."""
    if v.mode != "follows_source" or not v.source_url:
        return {"value": v.value, "number": v.number, "qualifier": v.qualifier}
    rows = [r for r in statements.rows_for_url(v.tenant, v.source_url) if r.subject == v.subject]
    distinct = {(r.number, r.qualifier): r for r in rows}
    if len(distinct) != 1:
        return None
    r = next(iter(distinct.values()))
    return {"value": r.value, "number": r.number, "qualifier": r.qualifier}


def resolve(tenant: str, subject: str, scope: dict | None = None,
            _cache: list | None = None) -> dict | None:
    """The most specific approved value for `scope`, or None.

    A value applies when every dimension it names matches the scope (empty
    = any). Among those, the one naming the most dimensions wins."""
    sc = scope_of(**{k: (scope or {}).get(k, "") for k in ("entity", "market", "channel")})
    best, best_n = None, -1
    for v in (_cache if _cache is not None else values(tenant, subject)):
        if v.subject != subject:
            continue
        dims = {"entity": v.scope_entity, "market": (v.scope_market or "").upper(),
                "channel": v.scope_channel}
        if any(d and d != sc[k] for k, d in dims.items()):
            continue
        n = sum(1 for d in dims.values() if d)
        if n > best_n:
            best, best_n = v, n
    if best is None:
        return None
    live = _live(best)
    if live is None:
        return {"id": best.id, "unknown": True, "mode": best.mode,
                "source_url": best.source_url, "scope": scope_label(
                    {"entity": best.scope_entity, "market": best.scope_market,
                     "channel": best.scope_channel})}
    return {"id": best.id, **live, "mode": best.mode, "source_url": best.source_url,
            "decided_by": best.decided_by, "reason": best.reason,
            "scope": scope_label({"entity": best.scope_entity, "market": best.scope_market,
                                  "channel": best.scope_channel})}


def agrees(number, qualifier: str, t_number, t_qualifier: str) -> bool:
    """Does a stated figure agree with the true one? Pure; the one rule."""
    if number is None or t_number is None:
        return False
    q, tq = (qualifier or ""), (t_qualifier or "")
    if q in ("", "counted") and tq in ("", "counted"):
        return number == t_number
    if q == "at least":
        # "over 100" is true of 162; "200+" is not. Against a truth that is
        # itself a floor ("160+"), only the same floor or a lower one is safe.
        return number <= t_number
    if q == "about":
        return abs(number - t_number) <= 0.1 * max(abs(t_number), 1)
    if q == "up to":
        return t_number <= number
    if tq == "at least":
        # The page states an exact figure, the truth only a floor: an exact
        # figure at or above the floor cannot be said to be wrong.
        return number >= t_number
    return number == t_number


def compare(stmt, truth: dict | None) -> dict | None:
    """None when the statement agrees with the truth (or there is none);
    otherwise what the disagreement is."""
    if not truth or truth.get("unknown"):
        return None
    if agrees(stmt.number, stmt.qualifier, truth["number"], truth["qualifier"]):
        return None
    return {"subject": stmt.subject, "stated": stmt.value, "true": truth["value"],
            "url": stmt.url, "text": stmt.text, "binding": stmt.authority == "binding",
            "fact_value_id": truth["id"]}


# --- page scopes ----------------------------------------------------------

def page_scopes(tenant: str) -> dict:
    """(url, subject) -> scope; subject "" applies to every subject on the page."""
    with db.SessionLocal() as s:
        rows = s.query(db.KbPageScope).filter(db.tenant_filter(db.KbPageScope, tenant)).all()
        return {(r.url, r.subject): scope_of(r.scope_entity, r.scope_market) for r in rows}


def statement_scope(stmt, scopes: dict) -> dict:
    return (scopes.get((stmt.url, stmt.subject)) or scopes.get((stmt.url, ""))
            or scope_of(stmt.entity_key or "", stmt.market or ""))


# --- QA's decisions (called by findings.decide) ---------------------------

def set_value(tenant: str, subject: str, value: str, number, qualifier: str,
              scope: dict | None = None, mode: str = "pinned", source_url: str = "",
              source_id: str = "", reason: str = "", by: str = "") -> str:
    """Approve a value for subject × scope; the previous one is retired."""
    sc = scope_of(**{k: (scope or {}).get(k, "") for k in ("entity", "market", "channel")})
    with db.SessionLocal() as s:
        for old in (s.query(db.KbFactValue)
                    .filter(db.KbFactValue.tenant == tenant, db.KbFactValue.subject == subject,
                            db.KbFactValue.status == "approved",
                            db.KbFactValue.scope_entity == sc["entity"],
                            db.KbFactValue.scope_market == sc["market"],
                            db.KbFactValue.scope_channel == sc["channel"])):
            old.status, old.retired_at = "retired", _now()
        row = db.KbFactValue(tenant=tenant, subject=subject, value=value, number=number,
                             qualifier=qualifier, scope_entity=sc["entity"],
                             scope_market=sc["market"], scope_channel=sc["channel"],
                             mode=mode, source_url=source_url, source_id=source_id,
                             reason=reason, decided_by=by)
        s.add(row)
        s.commit()
        return row.id


def make_source(tenant: str, url: str, subjects: list[str], by: str = "",
                label: str = "") -> str:
    with db.SessionLocal() as s:
        row = (s.query(db.KbSource).filter(db.KbSource.tenant == tenant,
                                           db.KbSource.kind == "page",
                                           db.KbSource.ref == url).one_or_none())
        if row is None:
            row = db.KbSource(tenant=tenant, kind="page", ref=url, created_by=by,
                              label=label or url.split("://", 1)[-1][:80], governs=[])
            s.add(row)
        row.governs = sorted(set(row.governs or []) | set(subjects))
        s.commit()
        return row.id


def sources(tenant: str) -> list:
    with db.SessionLocal() as s:
        rows = (s.query(db.KbSource).filter(db.tenant_filter(db.KbSource, tenant))
                .order_by(db.KbSource.ref).all())
        s.expunge_all()
        return rows


def scope_page(tenant: str, url: str, subject: str, entity: str = "", market: str = "",
               by: str = "", reason: str = "") -> None:
    with db.SessionLocal() as s:
        row = (s.query(db.KbPageScope).filter(db.KbPageScope.tenant == tenant,
                                              db.KbPageScope.url == url,
                                              db.KbPageScope.subject == subject).one_or_none())
        if row is None:
            row = db.KbPageScope(tenant=tenant, url=url, subject=subject)
            s.add(row)
        row.scope_entity, row.scope_market = entity or "", (market or "").upper()
        row.decided_by, row.reason = by, reason
        s.commit()


def table(tenant: str) -> list[dict]:
    """The approved truth, for the console, MCP and drafts."""
    out = []
    for v in values(tenant):
        live = _live(v)
        out.append({"id": v.id, "subject": v.subject, "question": question(v.subject),
                    "value": (live or {}).get("value", ""), "unknown": live is None,
                    "number": (live or {}).get("number"), "qualifier": (live or {}).get("qualifier", ""),
                    "scope": scope_label({"entity": v.scope_entity, "market": v.scope_market,
                                          "channel": v.scope_channel}),
                    "mode": v.mode, "source_url": v.source_url, "reason": v.reason,
                    "decided_by": v.decided_by,
                    "decided_at": v.decided_at.isoformat() if v.decided_at else ""})
    return out
