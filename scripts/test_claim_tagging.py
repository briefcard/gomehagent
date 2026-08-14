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

        print("\n— a number is not a claim until you know whose it is —")
        # Reported: "1,652 residential & hotel units" arrived with an empty
        # interpretation and, on its own, means nothing. It is an Opus
        # Communities development, and that name is in the block ABOVE — so the
        # span-only evidence rule threw the one fact that made it usable.
        PAGE = ["Opus Communities — Hallandale Beach",
                "1,652 residential & hotel units",
                "Delivered across three phases."]
        kept, _ = extract._verify(
            [{"text": "1,652 residential & hotel units", "proof_type": "data",
              "evidence": "1,652",
              "context": "Opus Communities — Hallandale Beach",
              "proves": "They marketed a 1,652-unit residential and hotel "
                        "development.",
              "situations": [], "_url": "https://x/work"}],
            PAGE, valid_situations=set(kb.situations("agency")))
        ck("the claim is still the verbatim span",
           kept[0]["text"] == "1,652 residential & hotel units")
        ck("and it now carries whose development it was",
           "Opus" in kept[0]["context"], kept[0]["context"] or "(empty)")
        ck("so the interpretation has something to work from",
           "1,652-unit" in kept[0]["proves"], kept[0]["proves"])

        print("\n— the page's own wording, not the comparison form —")
        # Matching must be whitespace-insensitive (a claim can span a line
        # break in the HTML), so _verify compares normalised forms — and then
        # stored the normalised form. `norm` mapped it back to the original
        # block for exactly this purpose and nothing read it, so every claim
        # was silently reflowed away from what the page said.
        WRAPPED = ["15,000 +   Trained across\n30+ seminars worldwide"]
        got, _ = extract._verify(
            [{"text": "15,000 + Trained across 30+ seminars worldwide",
              "proof_type": "data", "_url": "x"}], WRAPPED)
        ck("the match still succeeds across the line break", got,
           "whitespace-insensitive matching is what makes the claim findable")
        ck("and what is stored is the source, verbatim",
           got[0]["text"] == WRAPPED[0],
           repr(got[0]["text"]))
        ck("which is NOT the collapsed form",
           got[0]["text"] != "15,000 + Trained across 30+ seminars worldwide")

        import app.provenance as _pv
        ck("dedupe is unaffected — normalise collapses whitespace anyway",
           _pv.fingerprint(got[0]["text"])
           == _pv.fingerprint("15,000 + Trained across 30+ seminars worldwide"),
           "storing the source form must not split one fact into two")

        print("\n— but context is checked, not taken —")
        bad, _ = extract._verify(
            [{"text": "1,652 residential & hotel units", "proof_type": "data",
              "context": "a landmark development for a prestige client",
              "_url": "x"}], PAGE)
        ck("invented context is dropped, like an invented span",
           bad[0]["context"] == "", bad[0]["context"])

        # A portfolio page lists a dozen projects. Verifying context page-wide
        # would attach one development's name to another's unit count — and the
        # result would be verbatim, checkable, and wrong.
        FAR = PAGE + ["filler"] * 6 + ["Sunrise Harbour — Fort Lauderdale"]
        far, _ = extract._verify(
            [{"text": "1,652 residential & hotel units", "proof_type": "data",
              "context": "Sunrise Harbour — Fort Lauderdale", "_url": "x"}], FAR)
        ck("a heading from the far end of the page is refused",
           far[0]["context"] == "",
           "another project's name was attached to this project's number")

        print("\n— the deterministic path cannot interpret anything —")
        from app import harvest as hv
        rows = hv._claims_from("We delivered 1,652 units in 2024.", "x", [])
        ck("it produces no interpretation, by construction",
           all(not r.get("proves") for r in rows),
           "so an empty `proves` means the model never ran, not that it had "
           "nothing to say")

        print("\n— two tags doing one job —")
        # The real agency vocabulary, which is where the reported pair lives.
        kb.seed_agency()
        # The reported pair. Measured before anything was built: tag-to-tag
        # similarity 0.00, triggers 0.00, descriptions 0.25, against a 0.65
        # threshold. No lexical measure will ever pair these, which is the
        # whole reason the empirical signal and the model pass exist.
        import app.provenance as _p
        rows = {r.tag: r for r in kb.situation_rows("agency")}
        if "solo_operator_doubt" in rows and "team_exists" in rows:
            a, b = rows["solo_operator_doubt"], rows["team_exists"]
            ck("lexical similarity genuinely cannot see the reported pair",
               _p.similarity(a.description or "", b.description or "")
               < _p.NEAR_DUPLICATE,
               "if this ever passes, the deterministic guard got better and "
               "this test should be re-read rather than deleted")

        # Empirical: same rows tagged, however differently they read.
        wrote = 0
        for i in range(3):
            msg = kb.add_claim("agency", f"Proof number {i} of capacity.", f"{i}",
                               ["solo_operator_doubt", "team_exists"],
                               proof_type="data", origin="human")
            wrote += msg.startswith("Added")
        # §2.1: a writer returns a status nobody reads and rows vanish. The
        # first version of this test ignored it and reported an empty overlap
        # as a finding about the detector.
        ck("the fixture claims were really written", wrote == 3,
           f"{wrote}/3 — the tags do not exist for this account")
        over = {(o["keep"], o["drop"]) for o in kb.situation_overlaps("agency")}
        ck("but shared USE catches them",
           ("solo_operator_doubt", "team_exists") in over
           or ("team_exists", "solo_operator_doubt") in over,
           str(sorted(over)))

        # Thin data makes a ratio meaningless: two tags on one shared claim
        # score 100%. Measured on the agency seed, co-occurrence alone paired
        # food_bev with no_traffic off a single row.
        ck("a pair backed by too few rows is NOT reported",
           not any({"food_bev", "no_traffic"} == {o["keep"], o["drop"]}
                   for o in kb.situation_overlaps("agency")),
           "a coincidence with a percent sign on it")

        nb = kb.situation_neighbours("agency", "solo_operator_doubt")
        ck("and the neighbour map ranks it first",
           nb and nb[0]["tag"] == "team_exists", str(nb[:2]))
        ck("naming WHY, so widened context is never mistaken for matched",
           nb[0]["basis"] == "used_together", nb[0]["basis"])
        ck("a tag with no relation to anything returns nothing",
           kb.situation_neighbours("agency", "no_such_tag") == [])

        print("\n— folding one into the other —")
        dry = kb.merge_situations("agency", "solo_operator_doubt", "team_exists")
        ck("a dry run says what it would move", dry["retagged"]["claims"] >= 3,
           str(dry["retagged"]))
        ck("and moves nothing", "team_exists" in kb.situations("agency"))
        ck("an unknown tag is refused",
           "error" in kb.merge_situations("agency", "nope", "team_exists"))

        kb.merge_situations("agency", "solo_operator_doubt", "team_exists",
                            dry_run=False)
        ck("the folded tag is gone", "team_exists" not in kb.situations("agency"))
        ck("and nothing is left holding it",
           not [c for c in kb.claims("agency")
                if "team_exists" in (c.situations or [])],
           "a claim left holding a retired tag can never be re-approved and "
           "can never be selected — silent retirement of real proof")
        ck("while the surviving tag still selects them",
           len(kb.claims("agency", situations=["solo_operator_doubt"])) >= 3)

    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED: " + ", ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
