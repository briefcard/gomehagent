"""The Overview — one account at a glance (INITIATIVE-review-surface §3.D, Phase 1).

Owner, 2026-11-07: *"We need to be able to clearly understand what AI is
crawling and determining, what users are finding, what gaps need filling."*
Four answers, each computed from tables that already exist — nothing here is
stored, so nothing here can drift:

* `read`       — what the crawl and the model did (stage reports + page tables);
* `determined` — what code and Claude decided about the claims, and how much of
                 it a person has confirmed;
* `people`     — what reviewers decided and found;
* `gaps`       — what is missing, how much, who fills it, and where.

Read-only. Every gap names the surface that closes it.
"""
from __future__ import annotations

import collections

from . import db

#: Who fills each gap (INITIATIVE-review-surface §3.E).
OWNER = {"reviewer": "Reviewer", "proof": "Proof", "owner": "Account owner",
         "claude": "Claude (proposes) → Reviewer", "editor": "Site editor"}


def _claims(tenant: str) -> list:
    with db.SessionLocal() as s:
        return (s.query(db.KbClaim.id, db.KbClaim.subject, db.KbClaim.review, db.KbClaim.status,
                        db.KbClaim.entity_key, db.KbClaim.also_entities, db.KbClaim.statement,
                        db.KbClaim.scope, db.KbClaim.scope_origin, db.KbClaim.approved_by,
                        db.KbClaim.record_status, db.KbClaim.origin, db.KbClaim.claim,
                        db.KbClaim.source)
                .filter(db.KbClaim.tenant == tenant).all())


def overview(tenant: str) -> dict:
    from . import claim_groups, stages
    rows = _claims(tenant)
    live = [r for r in rows if r.review != "rejected"]
    proposed = [r for r in rows if r.review == "proposed"]
    with db.SessionLocal() as s:
        pages_known = s.query(db.HarvestedPage).filter(db.HarvestedPage.tenant == tenant).count()
        pages_with_claims = (s.query(db.HarvestedPage)
                             .filter(db.HarvestedPage.tenant == tenant,
                                     db.HarvestedPage.claims_found > 0).count())
        pages_partly = (s.query(db.HarvestedPage)
                        .filter(db.HarvestedPage.tenant == tenant,
                                db.HarvestedPage.truncated == "yes").count())
        pages_stored = s.query(db.PageSnapshot).filter(db.PageSnapshot.tenant == tenant).count()
        with_proof = {t for (t,) in s.query(db.KbEvidence.target_id)
                      .filter(db.KbEvidence.tenant == tenant, db.KbEvidence.status == "active")}
        figures_open = (s.query(db.UnaccountedNumber)
                        .filter(db.UnaccountedNumber.tenant == tenant,
                                db.UnaccountedNumber.status == "open").count())
        findings_open = collections.Counter(
            f.severity or "" for f in s.query(db.Finding)
            .filter(db.Finding.tenant == tenant, db.Finding.status == "open"))
        known = s.query(db.KnownAnswer).filter(db.KnownAnswer.tenant == tenant).count()
        audits = (s.query(db.AuditSample).filter(db.AuditSample.tenant == tenant,
                                                 db.AuditSample.status == "complete").count())
        groups_open = (s.query(db.KbClaimGroup)
                       .filter(db.KbClaimGroup.tenant == tenant, db.KbClaimGroup.status == "open",
                               db.KbClaimGroup.kind == "inconsistency").count())
        changes_open = (s.query(db.ChangeTask)
                        .filter(db.ChangeTask.tenant == tenant,
                                db.ChangeTask.status.notin_(("verified", "skipped"))).count())
    need_browser = 0
    try:
        from .pipeline import checks
        need_browser = len(checks.trust(tenant).get("pages_needing_render") or [])
    except Exception:  # noqa: BLE001
        pass

    subj = collections.Counter(r.subject or "" for r in live)
    origin_subject = collections.Counter((r.scope_origin or {}).get("subject", "") or "" for r in live
                                         if r.subject)
    origin_entity = collections.Counter((r.scope_origin or {}).get("entity", "") or "" for r in live
                                        if r.entity_key)
    self_live = [r for r in live if r.subject == "self"]
    hist = [r for r in live if (r.scope or {}).get("history")]
    approved = [r for r in rows if r.review == "approved"]

    read = {
        "pages_known": pages_known, "pages_stored": pages_stored,
        "pages_with_claims": pages_with_claims, "pages_partly_read": pages_partly,
        "pages_need_browser": need_browser, "claims_found": len(rows),
        "figures_not_understood": figures_open, "last": stages.last_of_each(tenant),
    }
    determined = {
        "subject": {"the account": subj.get("self", 0), "another company": subj.get("other", 0),
                    "market fact (skips review)": subj.get("market", 0),
                    "not decided": subj.get("", 0)},
        "subject_by": dict(origin_subject), "entity_by": dict(origin_entity),
        "with_entity": sum(1 for r in live if r.entity_key),
        "on_several_entities": sum(1 for r in live if r.also_entities),
        "with_statement": sum(1 for r in live if (r.statement or "").strip()),
        "dated_history": len(hist),
        "sandbox_only": sum(1 for r in live if (r.scope or {}).get("environment")),
        "accuracy": _accuracy(tenant, claim_groups),
    }
    people = {
        "approved": len(approved), "rejected": sum(1 for r in rows if r.review == "rejected"),
        "approved_by": dict(collections.Counter(r.approved_by or "?" for r in approved)),
        "records_confirmed": sum(1 for r in rows if r.record_status == "confirmed"),
        "claims_with_proof": len(with_proof & {r.id for r in rows}),
        "known_answers": known, "audits_done": audits,
    }
    gaps = [g for g in [
        _gap("subject", "Claims nobody has said whose they are",
             sum(1 for r in proposed if not r.subject), "claude",
             "Claude proposes over MCP (propose_claim_records); you confirm on Claims.", "claims"),
        _gap("entity", "The account's claims with no product (entity)",
             sum(1 for r in self_live if not r.entity_key and not (r.scope or {}).get("brand_wide")),
             "reviewer", "Pick the product, or rule it brand-wide — Claims, or the workbook.",
             "byentity"),
        _gap("statement", "The account's claims with no standalone statement",
             sum(1 for r in self_live if not (r.statement or "").strip()), "claude",
             "What prompts receive. Claude drafts; you confirm.", "claims"),
        _gap("decide", "Proposed claims waiting for a decision", len(proposed), "reviewer",
             "Approve, fix or reject.", "claims"),
        _gap("proof", "Approved claims with no proof on file",
             sum(1 for r in approved if r.id not in with_proof), "proof",
             "Noted, not required (owner, 2026-11-07); added after approval.", "claims"),
        _gap("inconsistent", "Sentences the site states inconsistently", groups_open, "reviewer",
             "Pick the right wording once; every page gets a task.", "wording"),
        _gap("findings", "Questions the site disagrees on" +
             (f" ({findings_open.get('P1', 0)} P1)" if findings_open.get("P1") else ""),
             sum(findings_open.values()), "reviewer", "Set the answer once.", "truth"),
        _gap("figures", "Figures on the site no reader understood", figures_open, "reviewer",
             "Say what a figure is once; it is recorded on every page.", "checks"),
        _gap("browser", "Pages that need a browser to be read", need_browser, "owner",
             "Turn on rendering, or accept they are unread.", "checks"),
        _gap("known", "Known answers (to test the capture)", 0 if known else 1, "reviewer",
             "None set — the capture is untested. Add a few.", "checks", is_missing=not known),
        _gap("changes", "Site edits not yet verified", changes_open, "editor",
             "Closed only when the page, read again, agrees.", "changes"),
    ] if g["count"]]
    market = [{"id": r.id, "claim": (r.claim or "")[:220],
               "page": (r.source or "").replace("stated on ", "").strip()}
              for r in live if r.subject == "market"][:6]
    return {"ok": True, "tenant": tenant, "read": read, "determined": determined,
            "people": people, "gaps": gaps, "market_skipped_sample": market,
            "runs": stages.latest(tenant, limit=12), "cost": _cost(tenant)}


def _gap(key, label, count, owner, how, sub, is_missing=False) -> dict:
    return {"key": key, "label": label, "count": int(count or 0), "owner": OWNER[owner],
            "how": how, "sub": sub, "missing_flag": is_missing}


def _accuracy(tenant: str, claim_groups) -> dict:
    """Measured precision per automated step. Only what is measured is shown
    as a number; the rest says so (decision log: Phase 2)."""
    out = {}
    try:
        for m, a in claim_groups.accuracy(tenant).items():
            out[f"grouping · {m}"] = {"labels": a["labels"], "precision": a["precision"],
                                      "lower_bound": a["lower_bound"]}
    except Exception:  # noqa: BLE001
        pass
    for step in ("subject (code)", "entity (code)", "kind (code)", "page date (htmldate)",
                 "Claude proposals"):
        out.setdefault(step, {"labels": 0, "precision": None, "lower_bound": None,
                              "note": "not measured yet — the decision log (Phase 2) and the "
                                      "client's sample sheet measure it"})
    return out


def _cost(tenant: str) -> dict:
    try:
        from . import usage
        r = usage.report(days=30, tenant=tenant)
        return {"days": 30, "est_cost_usd": r.get("est_cost_usd"),
                "by_purpose": {k: v.get("cost_usd") for k, v in (r.get("by_purpose") or {}).items()},
                "calls": r.get("calls")}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}
