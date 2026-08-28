"""What part of an output is confirmed by a claim — and what is not.

Owner, 2026-08-29, after an Eien Health article recommended glucosamine and
chondroitin (which Eien does not sell) and discussed knee pain:

    "I don't want to see it as 'never say glucosamine & chondroitin' because
     we may want to generate articles that point out the deficits in the
     competition, but how come it doesn't know that? … we should have a
     feature in our review of all assets — blogs, ads, emails — that shows
     what part of the output is confirmed by a claim."

WHY IT DID NOT KNOW, pinned below: `validator.check`'s citation rule is
`if require_citation and body.strip() and not ids` — are ANY claim_ids
attached. The blog attaches every claim the account owns to every article, so
it passes whatever the body says. Nothing verified CORRESPONDENCE.

    python3 scripts/test_claim_trace.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ct.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import claim_trace, db, kb, kb_seed, tenants, validator  # noqa: E402

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


DOSE = {"id": "c2", "claim": "Each serving contains 1000mg of omega-3 fatty acids.",
        "evidence": "spec sheet"}
TEST = {"id": "c1", "claim": "Every batch is third-party tested in a US facility.",
        "evidence": "COA 2026"}


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    print("— the gap this exists for: citation is PRESENCE, not correspondence —")
    kb.add_claim("eien", "Every batch is third-party tested in a US facility.",
                 "COA 2026", [], proof_type="certification", origin="human",
                 status="active")
    cid = kb.claims("eien")[0].id
    off_topic = ("<p>Glucosamine and chondroitin are the most studied "
                 "supplements for knee pain, and they rebuild cartilage.</p>")
    res = validator.check("eien", off_topic, claim_ids=[cid])
    ck("the validator passes an article about something else entirely",
       res.get("ok") is True,
       "attaching a true claim licenses any body — that is the defect")

    print("\n— and this reading catches it —")
    rep = claim_trace.annotate(off_topic, kb.claims("eien"))
    ck("the assertion is seen as an assertion", rep["assertions"] >= 1)
    ck("…and nothing stands behind it", rep["coverage_pct"] == 0,
       str(rep["coverage_pct"]))
    ck("…and it is named, so it can be acted on",
       any("glucosamine" in u.lower() for u in rep["unbacked_assertions"]),
       str(rep["unbacked_assertions"])[:90])

    print("\n— a dosage claim does NOT back an efficacy sentence —")
    # The first false positive this hit on the real article, and the worst
    # error available: a green mark on an unapproved health claim.
    eff = "Omega-3 fatty acids are widely researched for moderating inflammation."
    ck("research prose is not backed by a milligram figure",
       not claim_trace.annotate(eff, [DOSE])["sentences"][0]["backed"],
       "they share the ingredient and nothing else")
    ck("…while a sentence that states the dose IS backed",
       claim_trace.annotate("Each serving contains 1000mg of omega-3 fatty "
                            "acids.", [DOSE])["sentences"][0]["backed"])
    ck("a digit inside a name is not a quantity",
       claim_trace._FIGURE.findall("omega-3 and GLP-1") == [],
       "matching '3' out of 'omega-3' defeated the guard on its first run")
    ck("…but a real quantity still is",
       claim_trace._FIGURE.findall("contains 1000mg") == ["1000"])

    print("\n— three states, so the loud one stays loud —")
    mixed = ("You just stood up from your desk. "
             "Every batch is third-party tested in a US facility. "
             "Glucosamine rebuilds cartilage and is the most studied option.")
    r = claim_trace.annotate(mixed, [TEST])
    kinds = [("backed" if s["backed"] else
              "unbacked" if s["assertion"] else "prose") for s in r["sentences"]]
    ck("prose, backed and unbacked are told apart",
       kinds == ["prose", "backed", "unbacked"], str(kinds))
    ck("coverage counts ASSERTIONS, not prose",
       r["assertions"] == 2 and r["coverage_pct"] == 50, str(r["coverage_pct"]))
    ck("an output with no assertions is not scored 0%",
       claim_trace.annotate("You stood up from your desk.",
                            [TEST])["coverage_pct"] is None,
       "'nothing needed a claim' and '0% grounded' are different facts")
    ck("…and says so in words",
       "no claim was needed" in claim_trace.summary(
           claim_trace.annotate("You stood up from your desk.", [TEST])))

    print("\n— it under-credits rather than over-credits —")
    ck("one shared topic word is not a citation",
       not claim_trace.annotate("Testing matters.", [TEST])["sentences"][0]["backed"],
       "a topic is not support")
    ck("markup never reaches the reader as text",
       "<p>" not in claim_trace.plain_text("<p>hello</p>")
       and "hello" in claim_trace.plain_text("<p>hello</p>"))
    ck("a heading asserts as loudly as a paragraph and is read",
       claim_trace.annotate("<h2>Glucosamine rebuilds cartilage</h2>",
                            [TEST])["assertions"] == 1)

    print("\n— the review surface renders it for ANY artifact —")
    from app import admin_ui

    class Art:
        tenant = "eien"; body = off_topic; format = "cms_article"
        system_key = "blog"; output_id = "o1"

    card = admin_ui._grounding_card("eien", Art())
    ck("the workroom shows the card", bool(card))
    ck("…with the coverage on the head", "0% grounded" in card)
    ck("…marks the unbacked assertion", "nothing on file says this" in card)
    ck("…and says the fix is the CLAIM, not a ban",
       "correct or add the CLAIM" in card or "add the CLAIM" in card,
       "banning the word would stop competitor-deficit articles too")

    class Ad:
        tenant = "eien"; body = '{"variants":[{"text":"Rebuilds cartilage."}]}'
        format = "ad_batch"; system_key = "ad_creative"; output_id = "o2"

    ck("an ad batch is annotated on its variants, not its JSON",
       "variants" not in admin_ui._grounding_card("eien", Ad()),
       "annotating raw JSON would mark up field names")

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
