"""A claim nobody can place is a claim no draft will ever use.

Reported from a real harvest of the agency site:

    "15,000 + Trained across 30+ seminars worldwide"

Picked up correctly, and filed with NO situations — so nothing downstream knows
it is credibility, or when to reach for it. Reproduced before it was fixed:

    agency situation PATTERNS : {}
    approved agency claims    : 0
    suggest_tags(...)         -> tags: []   basis: (nothing matched)

The cause was architectural, not a bad heuristic. `extract` asked the model
"is this a claim" — open-class semantic judgement — and then handed "what is
this claim FOR", the same class of problem, to a keyword matcher that runs
after the call and cannot see the page. extract.py's own docstring records
that the deterministic path was measured at 0% recall for the first question.
The lesson was not carried to the second.

    python3 scripts/test_claim_tagging.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ct.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, extract, kb, provenance as prov, tenants  # noqa: E402
from app.web import app  # noqa: E402

CLAIM = "15,000 + Trained across 30+ seminars worldwide"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    with TestClient(app) as cl:
        tenants.seed()
        kb.add_situation("agency", "credibility", patterns=[],
                         description="They doubt we can actually do this.",
                         origin="seed")

        print("— the vocabulary reaches the model —")
        ctx = extract._context("agency", "https://marketingthatworks.co/")
        ck("the account's situations are put in front of it",
           "credibility" in ctx, "the model was told to pick from a list it "
                                 "could not see")
        ck("and named as the only valid values",
           "ONLY valid values" in ctx)

        print("\n— tags are verified in code, like the spans are —")
        blocks = [CLAIM]
        kept, _rej = extract._verify(
            [{"text": CLAIM, "proof_type": "data", "evidence": "15,000",
              "situations": ["credibility", "not_a_real_tag"],
              "proves": "They have taught this at scale, not only practised it.",
              "_url": "https://marketingthatworks.co/"}],
            blocks, valid_situations=set(kb.situations("agency")))
        ck("a real tag survives", kept[0]["situations"] == ["credibility"],
           str(kept[0]["situations"]))
        ck("an invented one is dropped, not stored",
           "not_a_real_tag" not in kept[0]["situations"],
           "a tag that does not exist can never be selected on")
        ck("the interpretation comes through",
           "at scale" in kept[0]["proves"], kept[0]["proves"])

        print("\n— a genuine no-fit asks for a tag instead of going untagged —")
        kept2, _ = extract._verify(
            [{"text": CLAIM, "proof_type": "data", "situations": [],
              "needs_situation": "Proof Of Scale!", "_url": "x"}],
            blocks, valid_situations=set(kb.situations("agency")))
        ck("it is normalised to a usable tag",
           kept2[0]["needs_situation"] == "proof_of_scale",
           kept2[0]["needs_situation"])
        kept3, _ = extract._verify(
            [{"text": CLAIM, "proof_type": "data", "situations": ["credibility"],
              "needs_situation": "proof_of_scale", "_url": "x"}],
            blocks, valid_situations=set(kb.situations("agency")))
        ck("but a claim that DID get placed asks for nothing",
           kept3[0]["needs_situation"] == "",
           "a usable tag plus a wishlist entry would grow the vocabulary for "
           "no reason")

        print("\n— a machine may not quietly edit the vocabulary —")
        kb.add_situation("agency", "proof_of_scale", patterns=[],
                         origin="crawl", source="read off the site")
        row = [r for r in kb.situation_rows("agency")
               if r.tag == "proof_of_scale"][0]
        ck("a crawl-proposed tag lands PROPOSED, not approved",
           (row.review or "") == prov.PROPOSED, str(row.review))
        ck("so it cannot yet be used to tag anything",
           "proof_of_scale" not in kb.situations("agency"),
           "the vocabulary that decides what claims are accepted was edited "
           "by a machine")
        kb.approve("situation", row.id)
        ck("and once approved it is usable",
           "proof_of_scale" in kb.situations("agency"))

        print("\n— what the claim carries into a draft —")
        msg = kb.add_claim("agency", CLAIM, "15,000", ["credibility"],
                           proof_type="data", origin="crawl", status="pending",
                           source="stated on marketingthatworks.co",
                           proves="They have taught this at scale, not only "
                                  "practised it.")
        ck("it is filed", "review" in msg.lower() or "Added" in msg, msg)
        with db.SessionLocal() as s:
            row = s.query(db.KbClaim).filter(
                db.KbClaim.tenant == "agency",
                db.KbClaim.claim == CLAIM).first()
        ck("the wording is still exactly what the site said",
           row.claim == CLAIM, row.claim)
        ck("it knows WHEN to be used", row.situations == ["credibility"],
           str(row.situations))
        ck("and WHAT it proves — which is the part a drafter needs",
           "at scale" in (row.proves or ""), row.proves or "(empty)")
        ck("it still lands as a proposal, not a fact",
           (row.review or "") == prov.PROPOSED)

        print("\n— the old path, kept as a fallback and shown to be one —")
        g = kb.suggest_tags("agency", CLAIM)
        ck("the keyword matcher STILL cannot place this claim",
           g["tags"] == [] or g["basis"] != "pattern",
           f"tags={g['tags']} basis={g['basis']!r}")
        print("       ^ this is the bug being routed around, not fixed —")
        print("         which is why the model now tags at extraction time.")

        print("\n— the vocabulary must not grow a synonym for every phrasing —")
        # Without this the no-fit path is a tag generator: proof_of_scale,
        # scale_proof and training_volume all mean one thing, and a vocabulary
        # of near-synonyms is worse than a short one — selection splits across
        # them and no single tag accumulates the approved examples the learned
        # tagger needs.
        ck("an exact match is recognised",
           kb.similar_situation("agency", "credibility") == "credibility")
        ck("a reordered synonym is caught",
           kb.similar_situation("agency", "scale_of_proof") == "proof_of_scale",
           kb.similar_situation("agency", "scale_of_proof") or "(none)")
        ck("and a genuinely new idea is NOT caught",
           kb.similar_situation("agency", "seasonal_dip") == "",
           kb.similar_situation("agency", "seasonal_dip"))

        msg = kb.add_situation("agency", "scale_proof", patterns=[],
                               origin="crawl")
        ck("a machine is refused a synonym, and told which tag to use",
           "already has" in msg and "proof_of_scale" in msg, msg)
        ck("nothing was written",
           "scale_proof" not in kb.situations("agency", include_proposed=True))
        ck("but a HUMAN may still add one deliberately",
           kb.add_situation("agency", "scale_proof", patterns=[],
                            origin="human").startswith(("Added", "Updated")),
           "a person may have a reason, and can see both")

        # Matching on the DESCRIPTION, not the slug: 'credibility' and
        # 'proof_of_expertise' share no characters at all.
        ck("a slug is matched against what existing tags MEAN, not just spelling",
           kb.similar_situation("agency", "doubt_we_can_do_this") == "credibility",
           kb.similar_situation("agency", "doubt_we_can_do_this") or "(none)")

        ck("and there is a cap, so a bad vocabulary cannot be papered over",
           kb.MAX_NEW_SITUATIONS <= 5, str(kb.MAX_NEW_SITUATIONS))

    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED: " + ", ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
