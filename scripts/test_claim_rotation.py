"""Every approved claim is reachable, and the receipt says how much was not.

A GENERATIVE system — a campaign, an article, an ad — has no question to be
relevant to. Nothing is detected, so `overlap` is 0 for every row, `depth` is
equal across the brand-wide ones and `strength` defaults to "strong". All
three ranking keys tie, `sort` is stable, and the tie therefore broke on
insertion order: the claims offered were the OLDEST rows on file, for ever.
Measured on ten claims with a limit of six: 01–06, every single time. The
seventh claim an account authors could never be reached, however good it was.

That is the failure mode of a knowledge base that only grows — adding proof
stops changing anything, the best-researched claim is usually the newest and
therefore the most permanently invisible, and nothing says so.

Rotation is least-recently-used, never "first one unused": the same correction
`_campaign_craft` already applies to intent rotation, because once everything
has been used "first unused" finds none and falls back to insertion order.

Run: python3 scripts/test_claim_rotation.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, ledger, resolve, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _offered(t):
    b = resolve.resolve(t, system="campaign_email", tier=3)
    return [c["claim"] for c in b["claims"]], b


def _sent(t, cid):
    ledger.record(t, "campaign_email", format="campaign_email", status="sent",
                  body="x", claim_ids=[cid])


def main() -> int:
    db.init_db()
    tenants.seed()
    t = "baci"
    kb.ensure_brand(t, "Baci")
    kb.set_brand(t, positioning="Italian-designed tableware.", tone="warm")
    kb.add_banned(t, "made in Italy")
    for i in range(1, 11):
        kb.add_claim(t, f"Claim number {i:02d} about the brand.", f"ev {i}",
                     [], origin="human", status="active")
    ids = [c.id for c in kb.claims(t)]

    print("— a generative system has nothing to rank on, so it rotates —")
    first, _ = _offered(t)
    ck("six of ten are offered", len(first) == 6, str(len(first)))
    ck("  the first pass takes them in order",
       "01" in first[0], first[0])
    for cid in ids[:6]:
        _sent(t, cid)
    second, _ = _offered(t)
    ck("the next pass reaches the ones never used",
       all(f"{n:02d}" in " ".join(second) for n in (7, 8, 9, 10)),
       str([c[13:15] for c in second]))
    ck("  which the old ordering could never do",
       set(second) != set(first),
       "insertion order returned 01-06 for ever; claim 07 was unreachable")
    for cid in ids[6:]:
        _sent(t, cid)
    third, _ = _offered(t)
    ck("and once all have been used it keeps turning, least-recent first",
       "01" in third[0], str([c[13:15] for c in third]))

    print("\n— rotation is the LAST key, never the first —")
    kb.add_situation(t, "gifting", patterns=[["gift"]], description="a gift",
                     origin="seed")
    newest = kb.add_claim(t, "Arrives in a rigid presentation box.",
                          "photographed", ["gifting"], origin="human",
                          status="active")
    ck("the tagged claim was filed last", "Submitted" not in str(newest))
    b = resolve.resolve(t, system="lead_responder", tier=3,
                        utterance="is this any good as a gift?")
    got = [c["claim"] for c in b["claims"]]
    ck("a claim that answers the question outranks rotation",
       any("presentation box" in c for c in got), str(got)[:120])

    kb.add_entity(t, "product", "aqua-jug", "Aqua Jug", price="40")
    kb.add_claim(t, "The Aqua jug holds 1.5 litres.", "spec", [],
                 entity_key="aqua-jug", origin="human", status="active")
    b2 = resolve.resolve(t, system="campaign_email", tier=3,
                         entity_key="aqua-jug")
    ck("  and so does a claim about the thing being written about",
       any("1.5 litres" in c["claim"] for c in b2["claims"]),
       "specificity is a correctness rule, not a preference")

    print("\n— the receipt says how much was held back —")
    _, b3 = _offered(t)
    c = b3["coverage"]["counts"]
    ck("it reports what was offered", c.get("claims_offered") == 6, str(c))
    ck("  out of what is selectable", c.get("claims_selectable", 0) >= 10,
       str(c.get("claims_selectable")))
    ck("  and how many can never be narrowed",
       c.get("claims_unnarrowable", 0) >= 10,
       "a brand-wide untagged claim competes on every single draft")
    gap = [g for g in b3["gaps"] if "narrow" in g.get("means", "")]
    ck("a pile that cannot be narrowed is NAMED as the problem", bool(gap),
       str(b3["gaps"])[:120])
    ck("  and the fix is tagging, not authoring more",
       gap and "authoring more will not help" in gap[0]["fix"],
       str(gap[:1])[:140])

    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED:\n  - " + "\n  - ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
