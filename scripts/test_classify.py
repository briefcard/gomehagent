"""A tag nobody stands behind must not read like one somebody does.

`suggest_tags` was written to seed a review queue: a human reads `basis`,
sees a bad guess and fixes it. It is also the only classifier an account has,
so anything routing on situations — a service desk picking which objections to
answer with, a voice caller choosing a script branch — inherits it. There,
nobody reads `basis`.

The defect that made those two uses incompatible: the score was computed and
thrown away, and the gate was "shared any word at all". So a one-word overlap
returned a tag with exactly the authority of a twelve-word one. That is
DEFECTS 2.5 in a second place — a keyword match asserting `fits: True` —
and the fix is the same one: absence is a third state and it has to survive
to the caller.

    python3 scripts/test_classify.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cls.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import kb, tenants  # noqa: E402
from app.web import app  # noqa: E402

T = "baci"
_fail = []

#: The learned vocabulary under test. Every word of 4+ characters in this
#: claim becomes an example of what `gifting` means for this account.
GIFTING = "Arrives in a rigid presentation box suitable for wedding registry gifting."

#: Shares five of its five informative words with the claim above.
STRONG = "Arrives in a rigid presentation box, suitable for gifting."

#: Shares exactly ONE word — `registry`. Four informative words, so its
#: normalised score is 1/sqrt(4) = 0.50, which lands exactly ON the score
#: floor. It is refused by the shared-word floor instead, which is the whole
#: reason there are two floors rather than one.
ONE_WORD = "The registry of our warehouse locations changed."

#: Shares two words with a long sentence: 2/sqrt(22) = 0.43, under the score
#: floor. Refused by the other floor, independently.
THIN_ON_LONG = (
    "Wedding registry aside, the logistics team reviewed inbound freight "
    "schedules, customs paperwork, warehouse throughput, seasonal staffing "
    "levels, carrier contracts and returns handling this quarter.")

CONTRACT = {"tags", "basis", "confident", "score", "candidates",
            "similar_to_rejected"}


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    with TestClient(app) as cl:  # noqa: F841 — startup builds the schema
        tenants.seed()

        # `dishwasher` is a PATTERN, so it is a decision. `gifting` has no
        # pattern at all and can only ever be reached by resemblance, which is
        # what puts it under test.
        kb.add_situation(T, "durability", patterns=[["dishwasher"]],
                         description="Will it survive real use?", origin="seed")
        kb.add_situation(T, "gifting", patterns=[],
                         description="They are buying it for someone else.",
                         origin="seed")

        kb.add_claim(T, GIFTING, "photographed on the product page",
                     ["gifting"], proof_type="data", source="test",
                     origin="human")
        for row in kb.pending_claims(T):
            kb.review_claim(row.id, approve=True)
        ck("the learned vocabulary is in place",
           len(kb.claims(T)) == 1, f"{len(kb.claims(T))} selectable claims")

        print("\n— every caller gets the same keys, whichever path ran —")
        for name, text in (("pattern", "Dishwasher safe on a normal cycle."),
                           ("strong", STRONG), ("thin", ONE_WORD),
                           ("empty", "")):
            got = set(kb.suggest_tags(T, text))
            ck(f"the {name} path returns the full contract",
               got == CONTRACT, str(sorted(CONTRACT - got)) or "complete")

        print("\n— a pattern hit is a decision, not a confidence —")
        g = kb.suggest_tags(T, "Dishwasher safe on a normal cycle, all 6 pieces.")
        ck("it places the tag", g["tags"] == ["durability"], str(g["tags"]))
        ck("and says the basis was a pattern", g["basis"] == "pattern")
        ck("it is confident", g["confident"] is True)
        ck("and carries NO score — a decision does not have one",
           g["score"] is None,
           "a number here would be metadata dressed as evidence")

        print("\n— a strong resemblance still places the tag —")
        g = kb.suggest_tags(T, STRONG)
        ck("the tag is inherited from the approved claim",
           g["tags"] == ["gifting"], str(g["tags"]))
        ck("it is confident", g["confident"] is True)
        ck("and the score is now visible to the caller",
           isinstance(g["score"], float) and g["score"] >= kb.MIN_LEARNED_SCORE,
           str(g["score"]))
        ck("it says what it resembled",
           "resembles approved" in g["basis"], g["basis"][:48])

        print("\n— THE DEFECT: one shared word must not assert a tag —")
        g = kb.suggest_tags(T, ONE_WORD)
        ck("no tag is placed", g["tags"] == [], str(g["tags"]))
        ck("and it says so plainly", g["confident"] is False)
        ck("the score alone would have let this through",
           g["score"] == 0.5, f"score {g['score']} == the floor exactly")
        ck("so the shared-word floor is what refuses it",
           g["candidates"] and g["candidates"][0]["shared"] == 1,
           str(g["candidates"]))

        print("\n— and the near-miss survives to the caller —")
        ck("the tag it wondered about is still visible",
           [c["tag"] for c in g["candidates"]] == ["gifting"],
           str(g["candidates"]))
        ck("the reason is legible rather than blank",
           "too thin to place" in g["basis"] and "gifting" in g["basis"],
           g["basis"][:70])

        print("\n— two shared words in a long sentence fails the other floor —")
        g = kb.suggest_tags(T, THIN_ON_LONG)
        ck("no tag is placed", g["tags"] == [], str(g["tags"]))
        ck("this time the shared-word floor was cleared",
           g["candidates"] and g["candidates"][0]["shared"] >= kb.MIN_SHARED_WORDS,
           str(g["candidates"][0] if g["candidates"] else "(none)"))
        ck("and the normalised score is what refused it",
           g["score"] < kb.MIN_LEARNED_SCORE, str(g["score"]))

        print("\n— nothing to read is unclassified, not a crash —")
        g = kb.suggest_tags(T, "of a to in")   # nothing 4+ characters
        ck("no tag", g["tags"] == [])
        ck("not confident", g["confident"] is False)
        ck("no score to report", g["score"] is None)
        ck("and no candidates were invented", g["candidates"] == [])

        print("\n— the rejection warning still rides along both paths —")
        kb.add_claim(T, "Dishwasher safe on a normal cycle, all 6 pieces.", "",
                     ["durability"], proof_type="data", source="test",
                     status="pending", origin="crawl")
        row = [c for c in kb.pending_claims(T)
               if c.claim.startswith("Dishwasher safe")][0]
        kb.review_claim(row.id, approve=False)
        g = kb.suggest_tags(T, "Dishwasher safe on a normal cycle, all 6 pieces.")
        ck("a pattern hit still reports what was turned down before",
           bool(g["similar_to_rejected"]), g["similar_to_rejected"][:40])

    print()
    if _fail:
        print(f"FAILED {len(_fail)}:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
