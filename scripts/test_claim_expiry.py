"""Claims expire by default, and an expired one is asked about, never dropped.

Owner's rule, 2026-08-18: *"we should just require expired claims to go back
into the approval queue and some claims can be set as unexpirable"*, and
*"but by default they expire"*.

The old behaviour read `expires_at` directly and skipped the row in selection.
Since nothing could SET that column, every claim lived for ever — and if one
ever had been dated, it would have vanished from drafts with nobody told: still
on the Knowledge tab looking approved, never surfacing anywhere that asks
whether it is still true.

    python3 scripts/test_claim_expiry.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ce.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, provenance as prov, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def mk(claim, **kw):
    """An approved claim, straight in, so the dates are the only variable."""
    with db.SessionLocal() as s:
        row = db.KbClaim(tenant="baci", claim=claim, evidence="e",
                         proof_type="spec", situations=[], origin="human",
                         review=prov.APPROVED, status="active",
                         approved_at=db.utcnow(), **kw)
        s.add(row)
        s.commit()
        return row.id


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    now = db.utcnow()

    print("— by default, a claim expires —")
    fresh = mk("Designed in Milan.", verified_at=now)
    old = mk("Won an award in 2019.",
             verified_at=now - dt.timedelta(days=kb.CLAIM_TTL_DAYS + 5))
    with db.SessionLocal() as s:
        ck("a recent claim is dated, not timeless",
           kb.claim_expiry(s.get(db.KbClaim, fresh))["state"] == "dated")
        ck("  and is not expired yet",
           not kb.claim_expiry(s.get(db.KbClaim, fresh))["expired"])
        e = kb.claim_expiry(s.get(db.KbClaim, old))
        ck("one past the default interval IS expired",
           e["expired"], e["why"])
        ck("  even though nothing ever set expires_at",
           s.get(db.KbClaim, old).expires_at is None,
           "the default interval is what makes 'expire by default' real")

    print("\n— expired proof leaves selection, but is not lost —")
    sel = [c.id for c in kb.claims("baci")]
    ck("the expired claim is not selectable", old not in sel)
    ck("  the fresh one still is", fresh in sel)
    ck("  and it is bucketed as expired, not retired",
       old in [r.id for r in kb.claim_inventory("baci")["expired"]])

    print("\n— it goes BACK TO THE QUEUE, which is the owner's rule —")
    dry = kb.expire_due("baci")
    ck("a dry run reports without changing anything",
       dry["expired"] == 1 and not dry["applied"])
    with db.SessionLocal() as s:
        ck("  nothing moved yet",
           s.get(db.KbClaim, old).review == prov.APPROVED)
    done = kb.expire_due("baci", apply=True)
    ck("applying returns it to proposed", done["expired"] == 1)
    with db.SessionLocal() as s:
        r = s.get(db.KbClaim, old)
        ck("  it is in the queue now", r.review == prov.PROPOSED)
        ck("  approved_at is KEPT, so the queue can say when it was approved",
           r.approved_at is not None,
           "'you approved this a year ago, is it still true' is a much easier "
           "question than 'is this true' asked cold")
    ck("  and nothing was deleted",
       old in [r.id for r in kb.claim_inventory("baci")["pending"]])

    print("\n— some claims can be set unexpirable —")
    timeless = mk("Italian-designed.",
                  verified_at=now - dt.timedelta(days=kb.CLAIM_TTL_DAYS * 3))
    with db.SessionLocal() as s:
        ck("before marking, an ancient claim is expired",
           kb.claim_expiry(s.get(db.KbClaim, timeless))["expired"])
    kb.set_claim_expiry(timeless, never=True)
    with db.SessionLocal() as s:
        e = kb.claim_expiry(s.get(db.KbClaim, timeless))
        ck("marked never, it stops expiring", e["state"] == "timeless"
           and not e["expired"], e["why"])
    ck("  and it is selectable again", timeless in
       [c.id for c in kb.claims("baci")])
    ck("  the sweep leaves it alone", kb.expire_due("baci")["expired"] == 0)

    print("\n— approving a came-due claim does not re-expire it —")
    # Without this, the sweep returns it to the queue, approval stamps
    # `approved_at` but leaves the old `verified_at`, `claim_expiry` reads
    # `verified_at` first — and the same claim comes back every single sweep,
    # for ever. Found before it shipped, by asking what happens next.
    stale = mk("Ranged at the Four Seasons.",
               verified_at=now - dt.timedelta(days=kb.CLAIM_TTL_DAYS + 30))
    kb.expire_due("baci", apply=True)
    kb.review_claim(stale, approve=True)
    with db.SessionLocal() as s:
        r = s.get(db.KbClaim, stale)
        ck("approving re-dates it", not kb.claim_expiry(r)["expired"],
           kb.claim_expiry(r)["why"])
    ck("  so the next sweep leaves it alone",
       stale not in [c["claim_id"] for c in kb.expire_due("baci")["claims"]],
       "otherwise the same claim returns to the queue every sweep, for ever")

    print("\n— re-confirming resets the clock —")
    kb.set_claim_expiry(old, on="")
    with db.SessionLocal() as s:
        r = s.get(db.KbClaim, old)
        ck("verified today, due again in a year",
           not kb.claim_expiry(r)["expired"] and r.expires_at is None)

    print("\n— an explicit date wins over the default —")
    dated = mk("Stock of the 2026 line.", verified_at=now)
    kb.set_claim_expiry(dated, on=(now - dt.timedelta(days=1)).date().isoformat())
    with db.SessionLocal() as s:
        ck("a date in the past expires it immediately",
           kb.claim_expiry(s.get(db.KbClaim, dated))["expired"])
    ck("  a malformed date is refused, not guessed",
       "not a date" in kb.set_claim_expiry(dated, on="last tuesday"))

    print("\n— a row with no dates at all is UNDATABLE, not expired —")
    with db.SessionLocal() as s:
        r = db.KbClaim(tenant="baci", claim="Older than the timestamps.",
                       evidence="e", proof_type="spec", situations=[],
                       origin="seed", review=prov.APPROVED, status="active")
        s.add(r)
        s.commit()
        blind = r.id
        e = kb.claim_expiry(s.get(db.KbClaim, blind))
    ck("it is reported as undatable", e["state"] == "undatable", e["why"])
    ck("  NOT as expired", not e["expired"],
       "a missing timestamp is our bookkeeping gap, not evidence the claim "
       "went false — dropping it would destroy real proof to punish that")
    ck("  so it stays selectable",
       blind in [c.id for c in kb.claims("baci")])
    ck("  and it is listed for somebody to date",
       blind in [c["claim_id"] for c in kb.undatable_claims("baci")])
    ck("  the expiry sweep does not touch it",
       blind not in [c["claim_id"] for c in kb.expire_due("baci")["claims"]])

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
