"""Sent mail is where the objections already are.

A website says what a brand claims. A mailbox contains what it has actually
told customers — and, paired with the message it replies to, the objection it
was answering. Objections are zero on all five accounts and have been described
throughout this codebase as human-authored and underivable. That is true of a
crawl and false of a mailbox.

The risk is the opposite of the crawler's. A website is public prose; an inbox
is mostly newsletters, receipts and cold outreach, plus other people's words
quoted underneath our own. So the invariants worth locking down are about what
must NOT be read: the wrong bucket, somebody else's sentence, a banned phrase
that a colleague already said to a customer.

    python3 scripts/test_email_harvest.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'eh.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db, email_harvest as eh, extract, kb, kb_seed, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


# A mailbox, as `fetch_sent_threads` returns it. Every body below is shaped like
# real mail: our reply on top, their message quoted underneath, a signature.
THREADS = [
    {   # a real customer question, answered — this is an objection pair
        "thread_id": "t1",
        "reply": {"id": "m1", "date": "Mon, 3 Mar 2026", "subject": "Re: dishwasher",
                  "body": "Yes, every piece is dishwasher safe on a normal cycle.\n"
                          "We ship from Miami in 2 business days.\n\n"
                          "On Mon, Dana wrote:\n> Is this dishwasher safe?\n"
                          "--\nBest regards\nGomeh"},
        "inbound": {"id": "m0", "subject": "dishwasher", "from": "dana@x.com",
                    "body": "Hi — is this dishwasher safe? I broke my last set."},
    },
    {   # promotional noise: must never be opened
        "thread_id": "t2",
        "reply": {"id": "m3", "date": "", "subject": "Re: newsletter",
                  "body": "Thanks for subscribing! Here is 10% off your first "
                          "order, plus free shipping over $95."},
        "inbound": {"id": "m2", "subject": "newsletter", "from": "noreply@x.com",
                    "body": "Your weekly digest"},
    },
    {   # our own words, but they break the brand's rules
        "thread_id": "t3",
        "reply": {"id": "m5", "date": "", "subject": "Re: wholesale",
                  "body": "Every piece is handmade in Italy by our artisans, "
                          "so the lead time is 4 weeks."},
        "inbound": {"id": "m4", "subject": "wholesale", "from": "buyer@x.com",
                    "body": "Where are these produced?"},
    },
]


def _stub_fetch(alias, days=365, max_threads=120):
    return THREADS


def _stub_extract(tenant, url, blocks, entity_key=""):
    """Stands in for the model: returns verbatim spans, as the real one must."""
    out = []
    for b in blocks:
        if "dishwasher safe" in b or "ship from Miami" in b:
            out.append({"text": b, "proof_type": "spec", "evidence": "",
                        "entity_key": "", "source": url})
        if "handmade in Italy" in b:
            out.append({"text": b, "proof_type": "data", "evidence": "",
                        "entity_key": "", "source": url})
    return {"claims": out, "rejected_not_verbatim": [], "used": "model"}


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    from app import gmail_client
    gmail_client.fetch_sent_threads = _stub_fetch
    eh.extract.extract = _stub_extract
    eh.extract.available = lambda: True
    config.GMAIL_ACCOUNTS["baci"] = {"email": "hi@bacimilanousa.com"}
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, "baci")
        t.gmail_alias = "baci"
        # The bucket triage already assigned. Reading this rather than
        # reclassifying is the whole efficiency argument.
        s.add(db.EmailLog(account="baci", gmail_message_id="m0", thread_id="t1",
                          sender="dana@x.com", subject="dishwasher",
                          category="order_routine", action="labeled"))
        s.add(db.EmailLog(account="baci", gmail_message_id="m2", thread_id="t2",
                          sender="noreply@x.com", subject="newsletter",
                          category="promo", action="labeled"))
        s.add(db.EmailLog(account="baci", gmail_message_id="m4", thread_id="t3",
                          sender="buyer@x.com", subject="wholesale",
                          category="sales_leads", action="labeled"))
        s.commit()

    print("— the noise is already sorted —")
    r = eh.mine("baci", apply=False)
    ck("it reads sent mail, not the inbox", r["mailbox"] == "baci")
    ck("promotional threads are never opened",
       not any("10%" in c["text"] or "subscrib" in c["text"].lower()
               for c in r["claims"]), str([c["text"][:40] for c in r["claims"]]))
    ck("and it says which bucket it skipped and why",
       any("promo" in k for k in r["skipped_by_reason"]),
       str(r["skipped_by_reason"]))
    ck("only the mineable buckets were read", r["threads_mined"] == 2,
       f"{r['threads_mined']} of {r['threads_seen']}")

    print("\n— our words, not theirs —")
    ck("a claim from our reply is proposed",
       any("dishwasher safe" in c["text"] for c in r["claims"]))
    ck("the quoted question is NOT proposed as our claim",
       not any("I broke my last set" in c["text"] for c in r["claims"]),
       "quoting a customer must not attribute their words to the brand")
    ck("nor is the signature", not any("Best regards" in c["text"]
                                       for c in r["claims"]))

    print("\n— the brand's rules still bind, in email too —")
    ck("a banned phrase we ourselves sent is refused",
       not any("handmade" in c["text"].lower() for c in r["claims"]))
    ck("and it is reported, because someone already told a customer",
       any("handmade" in x["banned_phrase"].lower()
           or "made in italy" in x["banned_phrase"].lower()
           for x in r["rejected_for_banned_claim"]),
       str(r["rejected_for_banned_claim"])[:120])

    print("\n— the objection nobody could derive from a website —")
    ck("their question and our answer become a pair",
       r["objections_count"] >= 1, str(r["objections"])[:150])
    if r["objections"]:
        o = r["objections"][0]
        ck("the objection is what THEY asked",
           "dishwasher safe" in o["objection"].lower())
        ck("the answer is what WE said",
           "dishwasher safe" in o["response"].lower()
           and "I broke my last set" not in o["response"])
        ck("and it cites the message it came from", "email m1" in o["source"])

    print("\n— nothing is asserted —")
    before = len(kb.claims("baci")), len(kb.objections("baci"))
    ck("a dry run writes nothing",
       not r["applied"] and (len(kb.claims("baci")),
                             len(kb.objections("baci"))) == before)

    r2 = eh.mine("baci", apply=True)
    ck("applying files proposals, not facts",
       (len(kb.claims("baci")), len(kb.objections("baci"))) == before,
       "approved counts must not move")
    filed = [c for c in kb.pending_claims("baci") if c.origin == "email"]
    ck("claims are attributed to email", filed and all(
        c.review == "proposed" for c in filed))
    ck("and carry the message they came from",
       filed and all("email m" in (c.source or "") for c in filed))
    props = kb.objections("baci", include_proposed=True)
    ck("objections land as proposals too",
       any(o.origin == "email" and o.review == "proposed" for o in props))

    print("\n— running it twice —")
    r3 = eh.mine("baci", apply=True)
    ck("the same message is not mined into a second copy",
       r3["claims_count"] == 0 and r3["objections_count"] == 0,
       f"{r3['claims_count']} claims, {r3['objections_count']} objections")

    print("\n— accounts with no mailbox —")
    ck("an account with no connected inbox is refused, not guessed at",
       "no connected mailbox" in eh.mine("coverings").get("error", ""))
    ck("an unknown account is refused", "unknown tenant" in
       eh.mine("nope").get("error", ""))

    print("\n— the bucket list is explicit in both directions —")
    ck("noise buckets are named, so a new bucket fails safe",
       set(eh.EXCLUDED) & set(config.BUCKETS.keys()) == set(eh.EXCLUDED))
    ck("no bucket is both mineable and excluded",
       not (set(eh.MINEABLE) & set(eh.EXCLUDED)))

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
