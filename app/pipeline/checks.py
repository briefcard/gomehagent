"""CHECKS — how far the capture can be trusted, measured (BUILD-MAP §4, §7.4-5).

Three checks and one score, all computed from stored data:

* **known answers** — facts QA wrote down in advance ("19 licences on
  /compliance"). After every read each is `found`, `different`, `missing`
  (the page was read and the figure was not captured) or `not_read`.
  `different` and `missing` are P1: the capture got something QA already
  knew wrong, so nothing else it says is safe to rely on yet.
* **audit samples** — random stored pages, higher tiers first, put beside
  what was recorded from them for a person to mark complete or name what
  was missed. The share marked complete is the measured recall.
* **trust** — one panel per account: pages stored by tier, high-risk pages
  read in full, known answers passing, audit recall, open unaccounted
  figures. A grade with its reasons, never a bare number.

Decisions record WHO (`by`): the reviewer named in the console. QA is the
owner for now (INITIATIVE-claims-reconciliation.md §6); the field is there
so a second reviewer changes nothing but the name.
"""
from __future__ import annotations

import datetime as dt
import random
import re

from .. import db, statements
from . import account, fetch, policy


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _num(text: str):
    m = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    return float(m.group(0).replace(",", "")) if m else None


# --- known answers --------------------------------------------------------

def add_known(tenant: str, subject: str, expected: str, where_url: str = "",
              note: str = "", by: str = "") -> dict:
    subject, expected = (subject or "").strip(), (expected or "").strip()
    if not re.fullmatch(r"[a-z_]+\.[a-z_]+", subject):
        return {"error": "subject must look like area.name, e.g. legal.licences"}
    if _num(expected) is None:
        return {"error": "the expected value needs a number, e.g. 19 or 160+"}
    with db.SessionLocal() as s:
        row = (s.query(db.KnownAnswer)
               .filter(db.KnownAnswer.tenant == tenant, db.KnownAnswer.subject == subject,
                       db.KnownAnswer.where_url == (where_url or "")).one_or_none())
        if row is None:
            row = db.KnownAnswer(tenant=tenant, subject=subject, where_url=where_url or "")
            s.add(row)
        row.expected, row.number, row.note, row.set_by = expected, _num(expected), note, by
        row.last_result = ""
        s.commit()
        return {"id": row.id, "subject": subject, "expected": expected,
                "where_url": where_url or ""}


def remove_known(tenant: str, ka_id: str) -> bool:
    with db.SessionLocal() as s:
        r = s.get(db.KnownAnswer, ka_id)
        if r is None or r.tenant != tenant:
            return False
        s.delete(r)
        s.commit()
        return True


def known_answers(tenant: str) -> list:
    with db.SessionLocal() as s:
        rows = (s.query(db.KnownAnswer).filter(db.tenant_filter(db.KnownAnswer, tenant))
                .order_by(db.KnownAnswer.subject).all())
        s.expunge_all()
        return rows


def check_known(tenant: str, record: bool = True) -> dict:
    """Every known answer against what the capture recorded."""
    stored = {r.url for r in fetch.snapshots(tenant)}
    out = []
    for ka in known_answers(tenant):
        rows = [r for r in statements.rows(tenant, ka.subject)
                if not ka.where_url or r.url.rstrip("/") == ka.where_url.rstrip("/")]
        want = (ka.number, "+" in ka.expected)
        same = [r for r in rows if r.number == ka.number
                and (r.qualifier == "at least") == want[1]]
        if same:
            result = "found"
        elif rows:
            result = "different"
        elif ka.where_url and ka.where_url.rstrip("/") not in {u.rstrip("/") for u in stored}:
            result = "not_read"
        else:
            result = "missing"
        out.append({"id": ka.id, "subject": ka.subject, "expected": ka.expected,
                    "where_url": ka.where_url, "result": result,
                    "severity": "P1" if result in ("different", "missing") else "",
                    "captured": sorted({r.value for r in rows}),
                    "pages": sorted({r.url for r in rows})[:5], "note": ka.note})
    if record:
        with db.SessionLocal() as s:
            for o in out:
                r = s.get(db.KnownAnswer, o["id"])
                if r is not None:
                    r.last_result, r.last_checked = o["result"], _now()
            s.add(db.CheckResult(tenant=tenant, check="known_answers",
                                 passed=sum(o["result"] == "found" for o in out),
                                 failed=sum(o["severity"] == "P1" for o in out),
                                 details={"results": out}))
            s.commit()
    return {"results": out, "passed": sum(o["result"] == "found" for o in out),
            "failed": sum(o["severity"] == "P1" for o in out),
            "not_read": sum(o["result"] == "not_read" for o in out)}


# --- audit samples --------------------------------------------------------

def draw_sample(tenant: str, n: int = 3, seed: int | None = None) -> list[dict]:
    """N stored pages not yet audited at their current content, legal and
    coverage pages weighted first (they are where a miss costs most)."""
    rng = random.Random(seed)
    with db.SessionLocal() as s:
        done = {(r.url, r.content_hash) for r in s.query(db.AuditSample)
                .filter(db.AuditSample.tenant == tenant)}
    pool = [r for r in fetch.snapshots(tenant) if (r.url, r.content_hash) not in done]
    rng.shuffle(pool)
    pool.sort(key=lambda r: policy.rank(r.risk_tier or policy.tier(r.url)))
    picked = pool[:n]
    with db.SessionLocal() as s:
        for r in picked:
            s.add(db.AuditSample(tenant=tenant, url=r.url, content_hash=r.content_hash,
                                 risk_tier=r.risk_tier or policy.tier(r.url),
                                 statements_n=len(statements.rows_for_url(tenant, r.url))))
        s.commit()
    return open_audits(tenant)


def open_audits(tenant: str) -> list[dict]:
    with db.SessionLocal() as s:
        rows = (s.query(db.AuditSample)
                .filter(db.tenant_filter(db.AuditSample, tenant),
                        db.AuditSample.status == "open")
                .order_by(db.AuditSample.sampled_at).all())
        s.expunge_all()
    out = []
    for r in rows:
        st = statements.rows_for_url(tenant, r.url)
        out.append({"id": r.id, "url": r.url, "tier": r.risk_tier,
                    "recorded": [{"subject": x.subject, "value": x.value, "text": x.text[:160],
                                  "field": x.field} for x in st][:40],
                    "recorded_n": len(st)})
    return out


def decide_audit(tenant: str, audit_id: str, complete: bool, missed: str = "",
                 by: str = "") -> bool:
    with db.SessionLocal() as s:
        r = s.get(db.AuditSample, audit_id)
        if r is None or r.tenant != tenant:
            return False
        r.status = "complete" if complete else "missed"
        r.missed_note, r.decided_by, r.decided_at = (missed or "")[:2000], by, _now()
        s.commit()
        return True


def audit_recall(tenant: str) -> dict:
    with db.SessionLocal() as s:
        rows = (s.query(db.AuditSample).filter(db.tenant_filter(db.AuditSample, tenant),
                                               db.AuditSample.status != "open").all())
        missed = [{"url": r.url, "note": r.missed_note, "by": r.decided_by} for r in rows
                  if r.status == "missed"]
        n = len(rows)
    return {"audited": n, "complete": n - len(missed),
            "recall": round((n - len(missed)) / n, 2) if n else None, "missed": missed[:20]}


# --- trust ----------------------------------------------------------------

def trust(tenant: str) -> dict:
    """The capture's trustworthiness for one account, with its reasons."""
    snaps = fetch.snapshots(tenant)
    by_tier: dict[str, int] = {}
    for r in snaps:
        t = r.risk_tier or policy.tier(r.url)
        by_tier[t] = by_tier.get(t, 0) + 1
    with db.SessionLocal() as s:
        partly = {r.url for r in s.query(db.HarvestedPage)
                  .filter(db.HarvestedPage.tenant == tenant, db.HarvestedPage.truncated == "yes")}
        unread = s.query(db.HarvestedPage).filter(db.HarvestedPage.tenant == tenant).count()
    high = [r.url for r in snaps if (r.risk_tier or policy.tier(r.url)) in ("legal", "coverage")]
    high_partly = sorted(u for u in high if u in partly)
    ka = check_known(tenant, record=False)
    rec = audit_recall(tenant)
    n_figs = account.open_count(tenant)
    reasons, grade = [], "green"
    if not snaps:
        grade = "red"
        reasons.append("no pages stored yet — run a harvest")
    if ka["failed"]:
        grade = "red"
        reasons.append(f"{ka['failed']} known answer(s) not captured correctly")
    if high_partly:
        grade = "red"
        reasons.append(f"{len(high_partly)} legal/coverage page(s) only partly read")
    if grade != "red":
        if not ka["results"]:
            grade = "amber"
            reasons.append("no known answers set — the capture is untested")
        if (rec["audited"] or 0) < 3:
            grade = "amber"
            reasons.append(f"{rec['audited']} audit(s) done — 3 needed for a recall figure")
        elif rec["recall"] is not None and rec["recall"] < 0.9:
            grade = "amber"
            reasons.append(f"audit recall {int(rec['recall'] * 100)}% (below 90%)")
        if n_figs:
            grade = "amber"
            reasons.append(f"{n_figs} figure(s) on the site not yet understood")
        unrendered = [r.url for r in snaps if (r.rendered or 0) == 2]
        if unrendered:
            grade = "amber"
            reasons.append(f"{len(unrendered)} page(s) need a browser to be read in full "
                           f"(RENDER_JS is off) — what they show is unread")
    if not reasons:
        reasons.append("known answers pass, high-risk pages read in full, audits complete, "
                       "every figure accounted for")
    return {"tenant": tenant, "grade": grade, "reasons": reasons,
            "pages_stored": len(snaps), "pages_by_tier": by_tier,
            "high_risk_pages": len(high), "high_risk_partly_read": high_partly[:20],
            "known_answers": ka, "audit": rec, "unaccounted_open": n_figs,
            "pages_needing_render": [r.url for r in snaps if (r.rendered or 0) == 2][:20],
            "pages_remembered": unread}


def job(tenant: str, progress=None) -> dict:
    """The queued form: run the known answers and record trust."""
    ka = check_known(tenant, record=True)
    tr = trust(tenant)
    with db.SessionLocal() as s:
        s.add(db.CheckResult(tenant=tenant, check="trust",
                             passed=1 if tr["grade"] == "green" else 0,
                             failed=1 if tr["grade"] == "red" else 0,
                             details={"grade": tr["grade"], "reasons": tr["reasons"]}))
        s.commit()
    return {"known_answers_failed": ka["failed"], "grade": tr["grade"],
            "reasons": tr["reasons"]}
