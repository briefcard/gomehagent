"""CHANGE — a new truth, every place that states the old one, and proof it moved.

BUILD-MAP §4 CHANGE / owner, 2026-11-04: *"reconcile once and have the change
update across all pages (if available to Claude, otherwise identify exactly
where the changes need to be made manually)."*

`create` sets the new answer (it is QA's decision, with a reason) and lists
every LOCATION still stating something else:

* every stored page whose statement of the subject disagrees with the new
  answer for that page's scope — an `auto_edit` task when the page is a
  product, page or collection on a connected Shopify store (the exact old
  wording is replaced through an APPROVAL, never directly), otherwise a
  `manual` task carrying the sentence, the old wording and the replacement;
* every PENDING approval whose text states the subject otherwise (`draft`);
* the pages this account's sites list that were never readable
  (`unmonitored`) — nobody can say what they state, so a person checks them.

`verify` runs after every read: a page task is `verified` only when the
page's CURRENT statements agree with the answer. Nothing closes on the
strength of "we sent the edit".
"""
from __future__ import annotations

import datetime as dt
import json

from . import db, statements, truth


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _store_profile(tenant: str, url: str) -> dict | None:
    """The connected Shopify site this URL is on, when there is one."""
    try:
        from . import seo_guard, sites
        host = url.split("://", 1)[-1].split("/", 1)[0].lower().removeprefix("www.")
        for prof in sites.all_profiles().values():
            dom = (prof.get("domain") or "").lower().split("://", 1)[-1].strip("/").removeprefix("www.")
            if (prof.get("platform") == "shopify" and dom == host
                    and seo_guard.tenant_for(prof) == tenant):
                return prof
    except Exception:  # noqa: BLE001 — no profile means a manual task, never a crash
        return None
    return None


def _editable(url: str) -> bool:
    path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
    return any(path.startswith(p) for p in ("/products/", "/pages/", "/collections/"))


def _replacement(match: str, old_value: str, new_value: str) -> str:
    """'75 countries' -> '162+ countries': swap the figure, keep the words."""
    return match.replace(old_value, new_value, 1) if old_value in match else match


def locations(tenant: str, subject: str, fact_value_id: str) -> list[dict]:
    """Every place that disagrees with the answer `fact_value_id` governs."""
    scopes = truth.page_scopes(tenant)
    vals = truth.values(tenant)
    out = []
    for r in statements.rows(tenant, subject):
        sc = truth.statement_scope(r, scopes)
        t = truth.resolve(tenant, subject, sc, _cache=vals)
        if not t or t.get("unknown") or t["id"] != fact_value_id:
            continue
        if truth.compare(r, t) is None:
            continue
        if r.qualifier == "counted":
            # A counted table is not a figure anyone wrote: the fix is to the
            # table's rows, by a person.
            out.append({"kind": "manual", "location": r.url, "find": r.text,
                        "replace": f"make the table list {t['value']}", "sentence": r.text})
            continue
        match = next((f["match"] for f in statements.find(r.text) if f["value"] == r.value), r.value)
        kind = "auto_edit" if (_editable(r.url) and _store_profile(tenant, r.url)) else "manual"
        out.append({"kind": kind, "location": r.url, "find": match,
                    "replace": _replacement(match, r.value, t["value"]), "sentence": r.text})
    # Pending approvals still carrying another figure for this subject.
    t0 = next((v for v in vals if v.id == fact_value_id), None)
    with db.SessionLocal() as s:
        pend = (s.query(db.Approval).filter(db.Approval.tenant == tenant,
                                            db.Approval.status == "pending").all())
        for ap in pend:
            text = json.dumps(ap.payload or {}, ensure_ascii=False)
            for f in statements.find(text.replace("\\n", " ")):
                if f["subject"] != subject or t0 is None:
                    continue
                if not truth.agrees(f["number"], f["qualifier"], t0.number, t0.qualifier):
                    out.append({"kind": "draft", "location": f"approval:{ap.id}",
                                "find": f["match"], "replace": _replacement(f["match"], f["value"], t0.value),
                                "sentence": (ap.summary or "")[:300]})
                    break
    # Pages listed but never readable: what they state is unknown.
    with db.SessionLocal() as s:
        unreadable = [r.url for r in s.query(db.HarvestedPage)
                      .filter(db.HarvestedPage.tenant == tenant,
                              db.HarvestedPage.content_hash.in_(("", None))).limit(200)]
    if unreadable:
        out.append({"kind": "unmonitored", "location": "unreadable pages",
                    "find": "", "replace": "",
                    "sentence": f"{len(unreadable)} page(s) could not be read; check them by hand: "
                                + ", ".join(unreadable[:20])})
    return out


def create(tenant: str, subject: str, new_value: str, reason: str, by: str = "",
           scope: dict | None = None) -> dict:
    """QA changes an answer: set it, then list everything that must follow."""
    if not (reason or "").strip():
        return {"error": "a one-line reason is required — it is the audit trail"}
    from .findings import _pick_value, rebuild
    pick = _pick_value(tenant, subject, new_value, {})
    if not pick:
        return {"error": "the new value needs a number, e.g. 20 or 160+"}
    old = truth.resolve(tenant, subject, scope or {})
    fid = truth.set_value(tenant, subject, pick["value"], pick["number"], pick["qualifier"],
                          scope=scope, reason=reason, by=by)
    with db.SessionLocal() as s:
        ch = db.ChangeRequest(tenant=tenant, subject=subject, scope=truth.scope_of(**{
            k: (scope or {}).get(k, "") for k in ("entity", "market", "channel")}),
            old_value=(old or {}).get("value", ""), new_value=pick["value"],
            fact_value_id=fid, reason=reason, requested_by=by)
        s.add(ch)
        s.commit()
        cid = ch.id
    n = _add_tasks(tenant, cid, locations(tenant, subject, fid))
    rebuild(tenant)
    return {"ok": True, "change_id": cid, "tasks": n, "old_value": (old or {}).get("value", ""),
            "new_value": pick["value"]}


def _add_tasks(tenant: str, cid: str, locs: list[dict]) -> int:
    with db.SessionLocal() as s:
        have = {(t.location, t.find) for t in s.query(db.ChangeTask)
                .filter(db.ChangeTask.tenant == tenant, db.ChangeTask.change_id == cid)}
        n = 0
        for loc in locs:
            if (loc["location"], loc["find"]) in have:
                continue
            have.add((loc["location"], loc["find"]))
            s.add(db.ChangeTask(tenant=tenant, change_id=cid, **loc))
            n += 1
        s.commit()
    return n


def propose(tenant: str, task_id: str, by: str = "") -> dict:
    """File the exact replacement for an auto_edit task as an APPROVAL."""
    from . import approvals
    with db.SessionLocal() as s:
        t = s.get(db.ChangeTask, task_id)
        if t is None or t.tenant != tenant:
            return {"error": "no such task for this account"}
        if t.kind != "auto_edit" or t.status not in ("open", "failed"):
            return {"error": "only an open auto-edit task can be proposed"}
        ch = s.get(db.ChangeRequest, t.change_id)
        prof = _store_profile(tenant, t.location)
        if not prof:
            return {"error": "that page is not on a connected store any more — edit it by hand"}
        ap_id = approvals.request_approval(
            "fact_fix",
            f"[Facts/{tenant}] {t.location.split('://', 1)[-1]}: “{t.find}” → “{t.replace}”",
            {"tenant": tenant, "site": prof.get("key", ""), "url": t.location,
             "find": t.find, "replace": t.replace, "task_id": t.id,
             "change_id": t.change_id, "subject": ch.subject if ch else "",
             "reason": ch.reason if ch else "", "bucket": "seo"})
        t.status, t.approval_id, t.done_by, t.updated_at = "proposed", ap_id, by, _now()
        s.commit()
    return {"ok": True, "approval_id": ap_id}


def execute_fix(payload: dict) -> dict:
    """The approved fix, applied — called only by the approval executor."""
    from . import shopify_seo, sites, validator
    tenant = payload.get("tenant", "")
    prof = sites.get(payload.get("site", ""))
    res = shopify_seo.replace_text(prof, payload["url"], payload["find"], payload["replace"],
                                   check=lambda body: validator.check(
                                       tenant, body, require_citation=False))
    with db.SessionLocal() as s:
        t = s.get(db.ChangeTask, payload.get("task_id", ""))
        if t is not None:
            t.status = "published" if res.get("ok") else "failed"
            t.note = "" if res.get("ok") else str(res.get("error", ""))[:500]
            t.updated_at = _now()
            s.commit()
    return res


def mark(tenant: str, task_id: str, status: str, note: str = "", by: str = "") -> dict:
    """A person closes a task by hand: done (they edited it) or skipped (why)."""
    if status not in ("done_by_hand", "skipped"):
        return {"error": "status must be done_by_hand or skipped"}
    if status == "skipped" and not note.strip():
        return {"error": "say why it is skipped"}
    with db.SessionLocal() as s:
        t = s.get(db.ChangeTask, task_id)
        if t is None or t.tenant != tenant:
            return {"error": "no such task for this account"}
        t.status, t.note, t.done_by, t.updated_at = status, note[:500], by, _now()
        s.commit()
    verify(tenant)
    return {"ok": True}


def verify(tenant: str) -> dict:
    """Close what the site now proves. Runs after every read.

    A page task (auto_edit or manual, including one marked done by hand) is
    verified only when that page's current statements of the subject agree
    with the answer. A draft task is verified when its approval is no longer
    pending. An unmonitored task needs a person (done_by_hand)."""
    verified = 0
    with db.SessionLocal() as s:
        changes = {c.id: c for c in s.query(db.ChangeRequest)
                   .filter(db.ChangeRequest.tenant == tenant, db.ChangeRequest.status == "open")}
        for t in s.query(db.ChangeTask).filter(db.ChangeTask.tenant == tenant,
                                               db.ChangeTask.change_id.in_(list(changes) or [""]),
                                               db.ChangeTask.status.notin_(("verified", "skipped"))):
            ch = changes[t.change_id]
            ok = False
            if t.kind in ("auto_edit", "manual"):
                # THIS task's wording, on the page as last read: verified when
                # no statement of the subject that still disagrees with the
                # answer carries it. Another wrong figure on the same page is
                # its own task and does not hold this one open.
                scopes = truth.page_scopes(tenant)
                stored = fetch_stored(tenant, t.location)
                if stored:
                    still = [r for r in statements.rows_for_url(tenant, t.location)
                             if r.subject == ch.subject
                             and truth.compare(r, truth.resolve(
                                 tenant, ch.subject, truth.statement_scope(r, scopes))) is not None
                             and (t.find in r.text or t.find == r.text)]
                    ok = not still
            elif t.kind == "draft":
                ap = s.get(db.Approval, t.location.removeprefix("approval:"))
                ok = ap is None or ap.status != "pending"
            elif t.kind == "unmonitored":
                ok = t.status == "done_by_hand"
            if ok:
                t.status, t.verified_at = "verified", _now()
                verified += 1
        for cid, ch in changes.items():
            left = (s.query(db.ChangeTask).filter(db.ChangeTask.change_id == cid,
                                                  db.ChangeTask.status.notin_(("verified", "skipped")))
                    .count())
            if left == 0:
                ch.status, ch.closed_at = "done", _now()
        s.commit()
    return {"verified": verified}


def fetch_stored(tenant: str, url: str) -> bool:
    """Has the page been read at all? A task on a page never read cannot be
    verified by its absence."""
    from .pipeline import fetch
    return fetch.latest(tenant, url) is not None


def listing(tenant: str, status: str = "open") -> list[dict]:
    with db.SessionLocal() as s:
        q = s.query(db.ChangeRequest).filter(db.tenant_filter(db.ChangeRequest, tenant))
        if status != "all":
            q = q.filter(db.ChangeRequest.status == status)
        out = []
        for c in q.order_by(db.ChangeRequest.created_at.desc()).all():
            tasks = (s.query(db.ChangeTask).filter(db.ChangeTask.change_id == c.id)
                     .order_by(db.ChangeTask.kind, db.ChangeTask.location).all())
            done = sum(1 for t in tasks if t.status in ("verified", "skipped"))
            out.append({"id": c.id, "subject": c.subject, "question": truth.question(c.subject),
                        "scope": truth.scope_label(c.scope or truth.scope_of()),
                        "old_value": c.old_value, "new_value": c.new_value, "reason": c.reason,
                        "requested_by": c.requested_by, "status": c.status,
                        "created_at": c.created_at.isoformat() if c.created_at else "",
                        "progress": f"{done}/{len(tasks)}",
                        "tasks": [{"id": t.id, "kind": t.kind, "location": t.location,
                                   "find": t.find, "replace": t.replace, "sentence": t.sentence,
                                   "status": t.status, "note": t.note, "approval_id": t.approval_id,
                                   "done_by": t.done_by} for t in tasks]})
        return out


def audit_log(tenant: str) -> list[dict]:
    """Every QA decision, oldest first: answers set, findings decided, changes
    made, audits marked — who, when, why. The export a compliance reviewer
    keeps (CSV via the console)."""
    rows = []
    with db.SessionLocal() as s:
        for v in s.query(db.KbFactValue).filter(db.tenant_filter(db.KbFactValue, tenant)):
            rows.append({"at": v.decided_at, "who": v.decided_by, "what": "answer set",
                         "subject": v.subject, "detail": f"{v.value} ({truth.scope_label({'entity': v.scope_entity, 'market': v.scope_market, 'channel': v.scope_channel})}, {v.mode}"
                                                         + (f", retired {v.retired_at:%Y-%m-%d}" if v.retired_at else "") + ")",
                         "why": v.reason})
        for f in s.query(db.Finding).filter(db.tenant_filter(db.Finding, tenant),
                                            db.Finding.decided_at.isnot(None)):
            rows.append({"at": f.decided_at, "who": f.decided_by or "system", "what": f"finding {f.decision}",
                         "subject": f.subject, "detail": f"{f.kind} {f.value}".strip(), "why": f.reason})
        for c in s.query(db.ChangeRequest).filter(db.tenant_filter(db.ChangeRequest, tenant)):
            rows.append({"at": c.created_at, "who": c.requested_by, "what": "change requested",
                         "subject": c.subject, "detail": f"{c.old_value or '—'} → {c.new_value}", "why": c.reason})
        for t in s.query(db.ChangeTask).filter(db.tenant_filter(db.ChangeTask, tenant),
                                               db.ChangeTask.status.in_(("done_by_hand", "skipped", "verified"))):
            rows.append({"at": t.verified_at or t.updated_at, "who": t.done_by or "system",
                         "what": f"task {t.status}", "subject": "", "detail": f"{t.location}: {t.find} → {t.replace}",
                         "why": t.note})
        for a in s.query(db.AuditSample).filter(db.tenant_filter(db.AuditSample, tenant),
                                                db.AuditSample.decided_at.isnot(None)):
            rows.append({"at": a.decided_at, "who": a.decided_by, "what": f"audit {a.status}",
                         "subject": "", "detail": a.url, "why": a.missed_note})
    epoch = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    rows.sort(key=lambda r: (r["at"].replace(tzinfo=dt.timezone.utc) if r["at"] and r["at"].tzinfo is None
                             else (r["at"] or epoch)))
    for r in rows:
        r["at"] = r["at"].isoformat() if r["at"] else ""
    return rows
