"""Word overlap cannot see that two sentences are the same question.

    "Every piece survives a normal dishwasher cycle."
    "Will these mugs make it through the washer without chipping?"

Not one informative word in common. The first is an approved durability claim;
the second is a customer asking the question it answers, and the learned
tagger scores it zero — correctly, on its own terms, and uselessly.

That is the gap this closes, and the reason it closes it *behind* the existing
contract: `confident` / `score` / `basis` mean what they meant before, so
`resolve()`, the coverage receipt and the refusal never learn that anything
changed.

The provider is stubbed here with a hand-built geometry. That is deliberate —
these suites run offline, and what is testable without a network is the
plumbing and the decision order, not the quality of somebody's embedding
model. Quality is measured by `kb.calibration()` against real claims.

    python3 scripts/test_embed.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'em.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import embed, kb, tenants  # noqa: E402
from app.web import app  # noqa: E402

_fail = []

DURABLE = "Every piece survives a normal dishwasher cycle."
PARAPHRASE = "Will these mugs make it through the washer without chipping?"
GIFT = "Arrives in a rigid presentation box for wedding registry gifting."
UNRELATED = "Do you deliver on Tuesdays during the winter?"

#: A tiny concept space, so the geometry under test is known rather than
#: guessed. Three concepts plus a constant floor dimension, which keeps a text
#: matching nothing from having a zero norm.
CONCEPTS = [
    {"dishwasher", "washer", "cycle", "survives", "chipping", "breaks", "heat"},
    {"gift", "gifting", "present", "wedding", "registry", "box", "wrapped"},
    {"price", "pricing", "cost", "expensive", "cheaper", "afford"},
]

_calls = {"n": 0}


def stub(texts):
    _calls["n"] += 1
    out = []
    for t in texts:
        words = set(re.findall(r"[a-z]+", (t or "").lower()))
        v = [float(len(words & c)) for c in CONCEPTS] + [0.15]
        out.append(v)
    return out, ""


def unavailable(texts):
    return None, "OPENAI_API_KEY is not set"


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    with TestClient(app) as cl:  # noqa: F841
        tenants.seed()
        kb.add_situation("baci", "durability", patterns=[["dishwasher", "safe"]],
                         description="Will it survive real use?", origin="seed")
        kb.add_situation("baci", "gifting", patterns=[],
                         description="Buying for someone else.", origin="seed")
        kb.add_claim("baci", DURABLE, "tested across the range", ["durability"],
                     proof_type="data", source="t", origin="human")
        kb.add_claim("baci", GIFT, "photographed", ["gifting"],
                     proof_type="data", source="t", origin="human")
        for r in kb.pending_claims("baci"):
            kb.review_claim(r.id, approve=True)
        approved = {c.claim: c.id for c in kb.claims("baci")}
        ck("two approved claims to index", len(approved) == 2)

        print("\n— with no provider, nothing is indexed and it SAYS so —")
        embed.set_provider(unavailable)
        ok, why = embed.available()
        ck("availability is reported, not assumed", not ok and "OPENAI" in why, why)
        res = embed.backfill("baci", "claim",
                             [(i, t) for t, i in approved.items()])
        ck("nothing was written", res["wrote"] == 0 and res["failed"] == 2)
        ck("and the reason travels with it", "OPENAI" in res["why"], res["why"])

        g = kb.suggest_tags("baci", PARAPHRASE)
        ck("the paraphrase is unplaceable by words alone", g["tags"] == [],
           "not one informative word in common with the claim")
        ck("the path taken is named", g["path"] in ("overlap", "none"), g["path"])
        ck("and the degraded reason is carried, not swallowed",
           "OPENAI" in g["degraded"],
           "a fallback that looks like the real path is the 0%-recall bug")

        print("\n— with a provider, the same sentence places —")
        embed.set_provider(stub)
        res = embed.backfill("baci", "claim",
                             [(i, t) for t, i in approved.items()])
        ck("both claims indexed", res["wrote"] == 2, str(res))

        g = kb.suggest_tags("baci", PARAPHRASE)
        ck("THE POINT: the paraphrase now places", g["tags"] == ["durability"],
           str(g["tags"]))
        ck("by meaning, and it says so", g["path"] == "semantic", g["path"])
        ck("with the basis a human can read",
           "means the same as" in g["basis"], g["basis"][:52])
        ck("confident, with a cosine behind it",
           g["confident"] and g["score"] >= embed.MIN_SEMANTIC_SCORE,
           str(g["score"]))
        ck("and nothing is degraded", g["degraded"] == "")

        print("\n— but a pattern still outranks it —")
        g = kb.suggest_tags("baci", "Is this dishwasher safe on a normal cycle?")
        ck("a declared pattern is still the decision", g["path"] == "pattern",
           "semantic is the second authority, never the first")
        ck("and carries no score", g["score"] is None)

        print("\n— an unrelated question is still refused —")
        g = kb.suggest_tags("baci", UNRELATED)
        ck("no tag is placed", g["tags"] == [], str(g["tags"]))
        ck("semantic did not rescue it past the floor",
           g["path"] != "semantic", g["path"])

        print("\n— gifting and durability do not bleed into each other —")
        g = kb.suggest_tags("baci", "Can you wrap it as a present for a wedding?")
        ck("it places gifting, not durability", g["tags"] == ["gifting"],
           str(g["tags"]))

        print("\n— re-embedding is gated on the text, not the clock —")
        before = _calls["n"]
        again = embed.backfill("baci", "claim",
                               [(i, t) for t, i in approved.items()])
        ck("unchanged rows are skipped", again["skipped"] == 2 and again["wrote"] == 0,
           str(again))
        ck("and the provider was never called",
           _calls["n"] == before,
           "otherwise every harvest re-pays for the whole corpus")
        cid = approved[DURABLE]
        wrote, _ = embed.ensure("baci", "claim", cid, DURABLE + " Now amended.")
        ck("but changed text is re-embedded", wrote)

        print("\n— one account's vectors are invisible to another —")
        ck("nothing is indexed for eien", embed.BACKEND.rows("eien", "claim") == [])
        hits, why = embed.search("eien", "claim", PARAPHRASE)
        ck("and a search there returns nothing, with a reason",
           hits == [] and "nothing embedded" in why, why)

        print("\n— vectors from another model are skipped, not compared —")
        embed.BACKEND.upsert("eien", "claim", "x", [1.0, 0.0, 0.0, 0.15],
                             "some-other-model", 4, "h")
        hits, why = embed.search("eien", "claim", DURABLE)
        ck("no cross-model score is produced", hits == [],
           "cosine between two models is a number with no meaning")
        ck("and the caller is told why", "another model" in why, why)

        print("\n— leave-one-out reaches the semantic path too —")
        g = kb.suggest_tags("baci", GIFT, exclude_claim_id=approved[GIFT])
        ck("a claim excluded cannot place itself",
           "gifting" not in g["tags"] or g["path"] != "semantic",
           f"{g['tags']} via {g['path']} — calibration depends on this")

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
