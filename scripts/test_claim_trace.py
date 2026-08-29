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

    print("\n— a MENTION is allowed; only the RECOMMENDATION is flagged —")
    # The owner's constraint, and the reason this is not a ban-list entry:
    # "we may want to generate articles that point out the deficits in the
    # competition", which requires naming what the brand does not sell.
    vocab = claim_trace.vocabulary("eien")
    ck("the account's vocabulary is read from its whole knowledge base",
       len(vocab) > 3, str(len(vocab)))
    ck("recommending something never mentioned is flagged",
       "glucosamine" in claim_trace.off_catalogue(
           "Glucosamine and chondroitin remain the benchmark for joint support.",
           vocab))
    ck("…merely NAMING it is not — a competitor comparison must be possible",
       claim_trace.off_catalogue(
           "Some competitors lead with glucosamine and chondroitin.", vocab) == [],
       "banning the word would kill the comparison articles too")
    ck("the trigger word is not itself reported as unknown",
       "benchmark" not in claim_trace.off_catalogue(
           "Glucosamine remains the benchmark.", vocab),
       "noise makes the real entries harder to see")
    ck("our own claim's words are known",
       claim_trace.off_catalogue(
           "Look for third-party testing in a US facility.", vocab) == []
       or "test" not in claim_trace.off_catalogue(
           "Look for third-party testing in a US facility.", vocab))

    print("\n— the number is recorded on every output, by ONE writer —")
    from app import ledger
    cid2 = kb.claims("eien")[0].id
    bad = ledger.record("eien", "blog", claim_ids=[cid2], format="cms_article",
                        body="Glucosamine rebuilds cartilage and is most studied.")
    good = ledger.record("eien", "blog", claim_ids=[cid2], format="cms_article",
                         body="Every batch is third-party tested in a US facility.")
    prose = ledger.record("eien", "blog", claim_ids=[cid2], format="cms_article",
                          body="You stood up from your desk.")
    ck("an unsupported output records 0", bad.grounded_pct == 0,
       str(bad.grounded_pct))
    ck("a supported one records 100", good.grounded_pct == 100,
       str(good.grounded_pct))
    ck("one that asserts NOTHING records -1, not 0", prose.grounded_pct == -1,
       "averaging 'needed no claim' with 'has no claim' is how a trend lies")

    print("\n— and the trend reads what was true AT THE TIME —")
    t = claim_trace.trend("eien", 90)
    blog = next((x for x in t if x["system"] == "blog"), None)
    ck("the trend groups by system", blog is not None, str(t))
    ck("…counts only outputs that asserted something",
       blog and blog["outputs"] == 2,
       "the prose row must not drag the average down")
    ck("…and carries a series to draw", blog and len(blog["series"]) == 2)
    ck("claim usage is one query, not one per claim",
       claim_trace.usage_counts("eien").get(cid2, 0) >= 3,
       str(claim_trace.usage_counts("eien")))

    print("\n— the shape follows the asset —")
    from app import admin_ui as ui

    class Long:
        tenant = "eien"; format = "cms_article"; system_key = "blog"
        output_id = "L"
        body = " ".join(
            ["Glucosamine remains the benchmark for joints."] * 4
            + ["You stood up from your desk."] * 6)

    class Short:
        tenant = "eien"; format = "ad_batch"; system_key = "ad_creative"
        output_id = "S"
        body = '{"variants":[{"text":"Rebuilds cartilage fast."}]}'

    long_card, short_card = ui._grounding_card("eien", Long()), ui._grounding_card("eien", Short())
    ck("long-form gets the claim gutter", 'class="gutter"' in long_card)
    ck("a short ad does not — inline is readable at that length",
       'class="gutter"' not in short_card and bool(short_card))
    ck("both carry the at-a-glance bar",
       'class="meter"' in long_card and 'class="meter"' in short_card)

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
