"""A past reply can stop being true, and the follow-up has to know.

Gomeh's case, in his words: *"an email about a cup that's out of stock is
answered now and we save that context for follow up emails. What about when
it's back in stock? That response is no longer valid."*

The stock FACT was always handled — `resolve` declares it as a lookup and
`responder` refuses to answer it from knowledge, so it is read from the store
at the moment of asking and never stored as a claim. What was not handled is
the REPLY. It sits in the ledger and comes back in the bundle for a follow-up
as prose, reading exactly as true in September as it was in August, with
nothing in the sentence marking which half was a reading and which half was a
fact about the brand.

So the output is asked instead of the sentence.

    python3 scripts/test_perishable.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pf.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, ledger, lookups, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def age(row_id, hours):
    with db.SessionLocal() as s:
        r = s.get(db.Output, row_id)
        r.created_at = db.utcnow() - dt.timedelta(hours=hours)
        s.commit()


def _count_with_lookups() -> int:
    with db.SessionLocal() as s:
        return sum(1 for r in s.query(db.Output).all() if (r.lookups or []))


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— every lookup declares how long an answer built on it keeps —")
    ck("no tool can quietly have no half-life",
       all(t in lookups.STALE_AFTER_HOURS for t in lookups.TOOLS),
       "a missing one would read as 'never goes stale', which is the silent "
       "default this codebase keeps meeting")
    ck("stock is the shortest, because it is",
       lookups.STALE_AFTER_HOURS["shopify_inventory"]
       < lookups.STALE_AFTER_HOURS["shopify_customer"])

    print("\n— the cup —")
    cup = ledger.record("baci", "service_desk", conversation_id="c1",
                        body="The Aqua cup is out of stock at the moment.",
                        lookups=["shopify_inventory"], status="published")
    age(cup.id, 2)
    ck("answered two hours ago, it is still quotable",
       not ledger.perishable("baci", "c1"))
    age(cup.id, 72)
    hits = ledger.perishable("baci", "c1")
    ck("three days later it is flagged", len(hits) == 1, str(len(hits)))
    ck("  naming the lookup that aged",
       hits[0]["stale_lookups"] == ["shopify_inventory"])
    ck("  and saying what to do about it",
       "not to be repeated without reading it again" in hits[0]["warning"],
       hits[0]["warning"][:70])
    ck("  the reply itself is KEPT, not hidden or corrected",
       "out of stock" in hits[0]["body"],
       "what was said is a fact about the conversation and stays true "
       "whatever the stock does now")
    ck("  and it says when it was said",
       hits[0]["said_on"] and hits[0]["hours_old"] >= 72)

    print("\n— a reply with no live data in it keeps —")
    brand = ledger.record("baci", "service_desk", conversation_id="c2",
                          body="Every Aqua piece is acrylic.",
                          claim_ids=["x"], status="published")
    age(brand.id, 24 * 400)
    ck("a year-old brand answer is not perishable",
       not ledger.perishable("baci", "c2"),
       "a claim is true until somebody changes it; only lookups decay")

    print("\n— slow-moving facts are not treated like stock —")
    who = ledger.record("baci", "service_desk", conversation_id="c3",
                        body="You have ordered from us four times.",
                        lookups=["shopify_customer"], status="published")
    age(who.id, 72)
    ck("three days does not stale a customer-history answer",
       not ledger.perishable("baci", "c3"))
    age(who.id, 24 * 45)
    ck("  but forty-five days does", len(ledger.perishable("baci", "c3")) == 1)

    print("\n— scoping —")
    ck("one conversation does not see another's",
       len(ledger.perishable("baci", "c1")) == 1)
    ck("  and the whole account can be asked at once",
       len(ledger.perishable("baci")) >= 2)
    ck("another tenant sees none of it", not ledger.perishable("eien"))

    print("\n— the column is WRITTEN, not merely accepted —")
    # The point of this block. `Output.lookups` accepting a value proves
    # nothing: `Approval.system_id`, `SystemRun.edit_diff` and `expires_at` all
    # accepted values for months while no writer passed one, and each read as
    # a working feature. So this drives the real path and then asks the
    # DATABASE what landed.
    from app import kb, responder
    kb.ensure_brand("baci", "Baci")
    kb.add_banned("baci", "made in Italy")
    kb.set_brand("baci", tone="direct")
    # A lookup is only declared when a SITUATION says it needs one -- that is
    # the design: which questions need live data is per-tenant data, not a
    # hardcoded list. Without this the responder has nothing to declare and
    # `lookups_used` is correctly empty, which is what the first version of
    # this test measured.
    kb.add_situation("baci", "order_status",
                     patterns=[["where", "order"]],
                     description="asking after an order",
                     needs=[{"tool": "shopify_order",
                             "params": ["order_number"]}])
    before = _count_with_lookups()
    res = responder.answer(
        "baci", "where is my order 1234?",
        system_key="service_desk", contact_id="c9",
        facts={"status": "shipped yesterday"})
    ck("the responder reports which lookups it used",
       res.get("lookups_used") == ["shopify_order"],
       f"stage={res.get('stage')} used={res.get('lookups_used')}")
    after = _count_with_lookups()
    ck("  and a row lands carrying them", after > before,
       "accepting a parameter is not the same as writing a column — "
       "`Approval.system_id` and `edit_diff` both accepted values for months "
       "while nothing wrote one")

    print("\n— it reaches the bundle a follow-up is drafted from —")
    from app import resolve as rs
    b = rs.resolve("baci", system="service_desk", tier=3,
                   utterance="is the cup back yet?")
    ck("the bundle carries perishable facts", "perishable" in b)
    ck("  and names them when there are any", isinstance(b["perishable"], list))

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
