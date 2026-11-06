"""FINDINGS — every disagreement and gap, computed by code, decided by a person.

`rebuild(tenant)` is pure bookkeeping over stored data: statements × the
approved truth (`truth.compare`) × the known answers. It runs after every
read and every decision. A finding whose condition no longer holds CLOSES
ITSELF with the reason ("the site now agrees") — it is never silently
deleted, so the record of what was wrong and when survives.

`decide(...)` is the question card's four answers (BUILD-MAP §7.1), each
with a required one-line reason and the reviewer's name:

  correct      "This value is right"   → it becomes the truth (pinned);
                                         every page stating otherwise is now
                                         a contradiction to fix.
  source       "This page is the source of truth" → the page is declared a
                                         source and the truth FOLLOWS it.
  scope        "Both right — different products/markets" → the page is ruled
                                         to speak for a narrower scope.
  escalate     "Needs legal review"    → held, out of the open queue.
"""
from __future__ import annotations

import datetime as dt

from . import db, statements, truth
from . import provenance as prov

DECISIONS = ("correct", "source", "scope", "escalate")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _fp(*parts) -> str:
    return prov.fingerprint("|".join(str(p) for p in parts))


def compute(tenant: str) -> list[dict]:
    """Every finding the stored data implies right now. Pure read."""
    # History (dated announcements, increments) is never compared with a
    # current total: "secures 6 new licences" is not a licence count.
    rows = [r for r in statements.rows(tenant) if (getattr(r, "about", "") or "") != "history"]
    scopes = truth.page_scopes(tenant)
    vals = truth.values(tenant)
    out: list[dict] = []
    by_subject_scope: dict[tuple, list] = {}
    for r in rows:
        sc = truth.statement_scope(r, scopes)
        by_subject_scope.setdefault((r.subject, sc["entity"], sc["market"]), []).append(r)
    for (subject, ent, mkt), group in sorted(by_subject_scope.items()):
        sc = truth.scope_of(ent, mkt)
        t = truth.resolve(tenant, subject, sc, _cache=vals)
        if t and not t.get("unknown"):
            wrong: dict[str, list] = {}
            for r in group:
                d = truth.compare(r, t)
                if d:
                    wrong.setdefault(r.value, []).append(r)
            for value, rs in wrong.items():
                binding = any(x.authority == "binding" for x in rs)
                kind = "binding_conflict" if binding else "contradiction"
                out.append({
                    "fingerprint": _fp(kind, subject, ent, mkt, value),
                    "kind": kind, "subject": subject, "scope": sc,
                    "severity": truth.severity(subject, binding), "value": value,
                    "urls": sorted({x.url for x in rs}),
                    "fact_value_id": t["id"],
                    "detail": {"true": t["value"], "examples": [x.text[:200] for x in rs[:3]],
                               "binding": binding, "source_url": t.get("source_url", "")}})
            continue
        distinct = {(r.number, r.qualifier, getattr(r, "currency", "") or "") for r in group}
        if len(distinct) > 1:
            vals_by: dict[str, dict] = {}
            for r in group:
                v = vals_by.setdefault(r.value, {"value": r.value, "number": r.number,
                                                 "qualifier": r.qualifier, "pages": [],
                                                 "binding": False, "example": r.text[:200],
                                                 "fields": set()})
                if r.url not in v["pages"]:
                    v["pages"].append(r.url)
                v["binding"] = v["binding"] or r.authority == "binding"
                v["fields"].add(r.field or "body")
            for v in vals_by.values():
                v["fields"] = sorted(v["fields"])
            binding = any(v["binding"] for v in vals_by.values())
            out.append({
                "fingerprint": _fp("unresolved", subject, ent, mkt),
                "kind": "unresolved", "subject": subject, "scope": sc,
                "severity": truth.severity(subject, binding), "value": "",
                "urls": sorted({r.url for r in group}), "fact_value_id": "",
                "detail": {"values": sorted(vals_by.values(), key=lambda v: (v["number"] or 0)),
                           "unknown_truth": bool(t and t.get("unknown"))}})
    # Known answers the capture got wrong.
    from .pipeline import checks
    for ka in checks.check_known(tenant, record=False)["results"]:
        if ka["severity"]:
            out.append({
                "fingerprint": _fp("missing_known", ka["id"], ka["result"]),
                "kind": "missing_known", "subject": ka["subject"], "scope": truth.scope_of(),
                "severity": "P1", "value": ka["expected"], "urls": ka["pages"] or
                ([ka["where_url"]] if ka["where_url"] else []), "fact_value_id": "",
                "detail": {"result": ka["result"], "captured": ka["captured"],
                           "where_url": ka["where_url"]}})
    return out


def rebuild(tenant: str) -> dict:
    """Bring the stored findings in line with `compute`."""
    now_found = {f["fingerprint"]: f for f in compute(tenant)}
    opened = closed = 0
    with db.SessionLocal() as s:
        existing = {r.fingerprint: r for r in s.query(db.Finding)
                    .filter(db.Finding.tenant == tenant)}
        for fp, f in now_found.items():
            row = existing.get(fp)
            if row is None:
                row = db.Finding(tenant=tenant, fingerprint=fp)
                s.add(row)
                opened += 1
            elif row.status == "closed":
                row.status, row.decision, row.reason = "open", "", "it came back"
                opened += 1
            for k in ("kind", "subject", "scope", "severity", "value", "urls",
                      "fact_value_id", "detail"):
                setattr(row, k, f[k])
            row.last_seen = _now()
        for fp, row in existing.items():
            if fp not in now_found and row.status != "closed":
                row.status = "closed"
                if not row.decision:
                    row.decision, row.reason = "resolved", "the site now agrees"
                row.decided_at = row.decided_at or _now()
                closed += 1
        s.commit()
    return {"open_now": len(now_found), "opened": opened, "closed": closed}


def listing(tenant: str, status: str = "open") -> list[dict]:
    order = {"P1": 0, "P2": 1, "P3": 2}
    with db.SessionLocal() as s:
        q = s.query(db.Finding).filter(db.tenant_filter(db.Finding, tenant))
        if status != "all":
            q = q.filter(db.Finding.status == status)
        rows = q.all()
        out = [{"id": r.id, "kind": r.kind, "severity": r.severity, "subject": r.subject,
                "question": truth.question(r.subject), "scope": r.scope or {},
                "scope_label": truth.scope_label(r.scope or truth.scope_of()),
                "value": r.value, "urls": r.urls or [], "detail": r.detail or {},
                "status": r.status, "decision": r.decision, "reason": r.reason,
                "decided_by": r.decided_by,
                "first_seen": r.first_seen.isoformat() if r.first_seen else ""} for r in rows]
    return sorted(out, key=lambda f: (order.get(f["severity"], 3), f["subject"], f["value"]))


def decide(tenant: str, finding_id: str, decision: str, reason: str, by: str = "",
           value: str = "", url: str = "", entity: str = "", market: str = "") -> dict:
    """A reviewer answers a question card. Reason and reviewer are required."""
    if decision not in DECISIONS:
        return {"error": f"decision must be one of {', '.join(DECISIONS)}"}
    if not (reason or "").strip():
        return {"error": "a one-line reason is required — it is the audit trail"}
    with db.SessionLocal() as s:
        f = s.get(db.Finding, finding_id)
        if f is None or f.tenant != tenant:
            return {"error": "no such finding for this account"}
        subject, scope = f.subject, dict(f.scope or {})
        detail = dict(f.detail or {})
    by = by or "owner"
    if decision == "escalate":
        with db.SessionLocal() as s:
            f = s.get(db.Finding, finding_id)
            f.status, f.decision, f.reason, f.decided_by, f.decided_at = (
                "escalated", "escalate", reason, by, _now())
            s.commit()
        return {"ok": True, "decision": "escalate"}
    if decision == "correct":
        pick = _pick_value(tenant, subject, value, detail)
        if not pick:
            return {"error": "name the value that is correct"}
        truth.set_value(tenant, subject, pick["value"], pick["number"], pick["qualifier"],
                        scope=scope, reason=reason, by=by)
    elif decision == "source":
        if not url:
            return {"error": "name the page that is the source of truth"}
        rows = [r for r in statements.rows_for_url(tenant, url) if r.subject == subject]
        if len({(r.number, r.qualifier) for r in rows}) != 1:
            return {"error": "that page does not state one value for this subject — "
                             "choose a page that does, or mark a value correct"}
        sid = truth.make_source(tenant, url, [subject], by=by)
        r = rows[0]
        truth.set_value(tenant, subject, r.value, r.number, r.qualifier, scope=scope,
                        mode="follows_source", source_url=url, source_id=sid,
                        reason=reason, by=by)
    elif decision == "scope":
        if not url or not (entity or market):
            return {"error": "name the page and the product or market it speaks for"}
        rows = [r for r in statements.rows_for_url(tenant, url) if r.subject == subject]
        if len({(r.number, r.qualifier) for r in rows}) != 1:
            return {"error": "that page does not state one value for this subject"}
        truth.scope_page(tenant, url, subject, entity=entity, market=market, by=by,
                         reason=reason)
        # "Both right" means the page's value IS the truth for that scope.
        r = rows[0]
        truth.set_value(tenant, subject, r.value, r.number, r.qualifier,
                        scope={"entity": entity, "market": market}, reason=reason, by=by)
    with db.SessionLocal() as s:
        f = s.get(db.Finding, finding_id)
        f.decision, f.reason, f.decided_by, f.decided_at = decision, reason, by, _now()
        s.commit()
    out = rebuild(tenant)
    return {"ok": True, "decision": decision, **out}


def _pick_value(tenant: str, subject: str, value: str, detail: dict) -> dict | None:
    for v in detail.get("values", []):
        if v["value"] == value:
            return v
    for r in statements.rows(tenant, subject):
        if r.value == value:
            return {"value": r.value, "number": r.number, "qualifier": r.qualifier}
    # A value no page states (QA knows better than every page): parse it.
    import re
    m = re.search(r"\d[\d,]*(?:\.\d+)?", value or "")
    if not m:
        return None
    return {"value": value.strip(), "number": float(m.group(0).replace(",", "")),
            "qualifier": "at least" if "+" in value or "over" in value.lower() else ""}


def job(tenant: str, progress=None) -> dict:
    return rebuild(tenant)
