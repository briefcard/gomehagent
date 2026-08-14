"""The extractor's benchmark: recall and precision on real homepages.

Where the numbers came from
---------------------------
Five client homepages were fetched and read by hand, and what the deterministic
filter proposed was compared against what is actually on the page. The result:

    baci      system 0 claims   ·  2 real claims on the page   ·   0% recall
    ironside  system 0 claims   ·  6 real claims on the page   ·   0% recall
    eien      system 12 claims  ·  several mistyped or risky
    agency    unreadable — HTTP 403 to our user agent
    coverings unreadable — TLS chain

Every miss came from one rule: "a claim carries a number". It was written for
the agency's case-study proof ($6M to $20M) and is wrong for the attribute
claims every other client actually differentiates on — "Designed in Milan",
"No PFAS. No seed oils.", "Original sections of the Berlin Wall".

That differential is checked in below rather than left as an anecdote, because
an argument about whether extraction is good enough should be settled by a
number. Any change — model or regex — is measured against this.

What runs offline, and what needs a key
---------------------------------------
The default run makes NO network call. It tests the guarantee that matters:
`_verify` keeps only spans that genuinely appear in the source, so a model
cannot make the pipeline assert something the page does not say. That is code,
so it is testable without a model.

    python3 scripts/test_extract.py          # offline: the guarantees
    python3 scripts/test_extract.py --live   # + score the real model

`--live` needs ANTHROPIC_API_KEY and costs a few cents.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

os.environ.setdefault("DATABASE_URL",
                      f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ex.db')}")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, extract, kb_seed, tenants  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "homepages"

# What a person finds on each homepage, as a distinctive substring per claim.
# Substrings rather than whole sentences on purpose: a good extractor may
# return a tighter span than the whole block, and scoring on exact equality
# would punish it for being more precise than the fixture.
GROUND_TRUTH = {
    "baci": [
        ("origin, compliance-safe", "Designed in Milan"),
        ("material durability", "shatter-resistant Melamine"),
        ("collection positioning", "Mamma Mia Collection explores"),
    ],
    "ironside": [
        ("longevity positioning", "designed around longevity"),
        ("independent tenants", "independently owned"),
        ("events positioning", "backdrop for experiences"),
        ("food standards", "No PFAS"),
        ("adaptive reuse", "not demolished"),
        ("Berlin Wall asset", "Berlin Wall"),
    ],
    "eien": [
        ("GLP-1 mechanism", "GLP-1"),
        ("omega-3 benefit", "EPA and DHA"),
    ],
}

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def blocks_for(name: str) -> list[str]:
    return [b for b in (FIXTURES / f"{name}.txt").read_text().split("\n") if b.strip()]


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    # ---- the guarantee: a span that is not on the page cannot survive ------
    print("— verbatim verification (this is what makes a model safe here) —")
    blocks = ["Designed in Milan, the Joke Collection is pearl-rimmed.",
              "Every shop at Ironside is independently owned."]
    cands = [
        {"text": "Designed in Milan", "proof_type": "spec", "evidence": ""},
        {"text": "Designed in Rome", "proof_type": "spec", "evidence": ""},
        {"text": "Our tableware is handmade by Italian artisans",
         "proof_type": "data", "evidence": ""},
        {"text": "Every shop at Ironside is independently owned.",
         "proof_type": "data", "evidence": "independently owned"},
        {"text": "Every shop at Ironside is independently owned.",
         "proof_type": "data", "evidence": "in 400 stores"},
        {"text": "Designed in Milan", "proof_type": "nonsense", "evidence": ""},
    ]
    kept, rejected = extract._verify(cands, blocks)
    texts = [k["text"] for k in kept]

    ck("a real span is kept", "Designed in Milan" in texts)
    ck("an altered span is discarded", "Designed in Rome" not in texts)
    ck("an invented sentence is discarded",
       not any("handmade" in t for t in texts),
       "the page never said it, so it cannot become a proposal")
    ck("both discards are reported, not silent", len(rejected) == 2, str(rejected))
    ck("evidence not present in the span is dropped",
       any(k["evidence"] == "" for k in kept
           if k["text"].startswith("Every shop")),
       "a figure the page does not contain is exactly what must not survive")
    ck("an unknown proof_type falls back rather than propagating",
       all(k["proof_type"] in extract.PROOF_TYPES for k in kept))

    print("\n— entity scope —")
    scoped, _ = extract._verify(
        [{"text": "Designed in Milan", "proof_type": "spec", "entity_scoped": True}],
        blocks, entity_key="joke-plate")
    ck("a product-page claim carries its entity",
       scoped and scoped[0]["entity_key"] == "joke-plate")
    unscoped, _ = extract._verify(
        [{"text": "Designed in Milan", "proof_type": "spec", "entity_scoped": False}],
        blocks, entity_key="joke-plate")
    ck("a brand-level claim does not",
       unscoped and unscoped[0]["entity_key"] == "")

    print("\n— behaviour with no key —")
    if not extract.available():
        r = extract.extract("baci", "https://x/", blocks)
        ck("it says so rather than returning an empty result",
           r["used"] == "unavailable" and "note" in r, r.get("note", "")[:60])
    else:
        print("[ skip ] a key is set in this environment")

    # ---- the fixture itself ----------------------------------------------
    print("\n— the benchmark fixture —")
    for name, expected in GROUND_TRUTH.items():
        bl = blocks_for(name)
        missing = [lab for lab, needle in expected
                   if not any(needle in b for b in bl)]
        ck(f"{name}: all {len(expected)} known claims are present in the fixture",
           not missing, str(missing))

    # ---- scoring --------------------------------------------------------
    if "--live" not in sys.argv:
        print("\n— scoring —")
        print("  Skipped. Re-run with --live to score the real extractor:")
        print("      python3 scripts/test_extract.py --live")
        print("  Baseline to beat, measured on these same pages with the")
        print("  deterministic filter:  baci 0/3, ironside 0/6.")
    else:
        if not extract.available():
            print("\n  --live needs ANTHROPIC_API_KEY."); return 1
        print("\n— scoring the model against the fixture —")
        total_found = total_expected = total_proposed = 0
        for name, expected in GROUND_TRUTH.items():
            bl = blocks_for(name)
            res = extract.extract(name, f"https://{name}.example/", bl)
            got = [c["text"] for c in res["claims"]]
            hits = [lab for lab, needle in expected
                    if any(needle in g for g in got)]
            total_found += len(hits)
            total_expected += len(expected)
            total_proposed += len(got)
            print(f"\n  {name}: recall {len(hits)}/{len(expected)}"
                  f"   proposed {len(got)}"
                  f"   discarded as not-verbatim {res['not_verbatim_count'] if 'not_verbatim_count' in res else len(res['rejected_not_verbatim'])}")
            for lab, needle in expected:
                mark = "hit " if lab in hits else "MISS"
                print(f"    [{mark}] {lab}")
            for g in got:
                print(f"      + {g[:104]}")
            ck(f"{name}: nothing proposed that is not on the page",
               all(any(g in b for b in bl) for g in got))
        print(f"\n  TOTAL recall {total_found}/{total_expected}"
              f"   ({100*total_found//max(total_expected,1)}%)"
              f"   from {total_proposed} proposals")
        ck("beats the deterministic baseline of 0 on baci and ironside",
           total_found > 0, f"{total_found} of {total_expected}")

    print("\n— a product description is not a claim —")
    check_claim_definition(ck)

    print("\n— a cut-off reply must not cost the whole page —")
    check_truncation_salvage(ck)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0



def check_claim_definition(ck):
    """A product description is not a claim.

    Reported from a live Baci queue:

        "Taupe acrylic pitcher from the Aqua collection, designed to combine
         functionality with minimalist elegance."

    Nothing there is contestable. Colour, material and collection belong on
    the product record, and "functionality with minimalist elegance" is what
    every brand in the category writes — a draft can never use it as proof of
    anything. The prompt invited it twice: the claim definition listed
    `materials` as a claim type, so "acrylic" qualified, and the skip rule
    only excluded spans that were PURELY specification, so a sentence mixing
    spec with evaluative prose passed both.

    The discriminator is now stated as a test the model can apply: could a
    competitor selling the same category honestly write this identical
    sentence? "Designed in Milan" — no. "Minimalist elegance" — yes, and
    routinely does.

    This is prompt-level on purpose. A keyword filter for marketing adjectives
    is the same mistake as the deterministic claim filter measured at 0%
    recall: deciding whether a sentence asserts anything is open-class
    judgement, and a word list cannot do it.
    """
    from app import extract as ex

    ck("the definition demands a checkable assertion",
       "CHECKABLE" in ex._SYSTEM)
    ck("and one a competitor could not equally make",
       "CONTESTABLE" in ex._SYSTEM)
    ck("the competitor test is spelled out as a test, not a preference",
       "competitor test" in ex._SYSTEM)
    ck("the reported sentence is named in the rules as the negative example",
       "minimalist elegance" in ex._SYSTEM,
       "the case that prompted the rule should survive a future rewrite")
    ck("and its passing counterpart is named beside it",
       "Designed in Milan" in ex._SYSTEM,
       "an exclusion with no contrasting positive over-corrects")
    ck("`materials` no longer stands alone as a claim type",
       "any checkable assertion: origin, materials" not in ex._SYSTEM,
       "listing materials invited the colour/material/collection sentence")


def check_truncation_salvage(ck):
    """A reply cut off at max_tokens must not cost the whole page.

    Reported as "only 5 claims from the Baci scrape". Two causes, both ours —
    not an API limit. `max_tokens` was 2000, sized before the response schema
    grew `situations`, `context` and `proves`, so a claim costs roughly twice
    what it did and about five fit. And when the array was cut mid-object the
    parser took the span from the first `[` to the last `]` and handed it to
    json.loads — no closing bracket meant `[]`, a partial object meant a raise
    and `[]`. The page's richest replies were the ones most likely to return
    nothing at all, silently, while the run still reported the model had run.
    """
    from app import config, extract as ex

    ck("the ceiling is sized to the schema, not to 2000",
       config.EXTRACT_MAX_TOKENS >= 8000, str(config.EXTRACT_MAX_TOKENS))

    whole = '[{"text": "a", "proves": "x"}, {"text": "b", "proves": "y"}]'
    ck("a complete array still parses", len(ex._parse(whole)) == 2)

    # Exactly what a max_tokens cut looks like: two good objects, then a
    # fragment, and no closing bracket.
    cut = '[{"text": "a", "proves": "x"}, {"text": "b", "proves": "y"}, {"text": "c", "prov'
    got = ex._parse(cut)
    ck("a truncated array keeps every COMPLETE object", len(got) == 2,
       f"{len(got)} — the old parser returned 0 and lost the page")
    ck("and drops only the fragment",
       [g["text"] for g in got] == ["a", "b"], str(got))

    ck("a reply with no array at all is still empty", ex._parse("sorry, none") == [])
    ck("and fenced JSON still parses",
       len(ex._parse('```json\n[{"text": "a"}]\n```')) == 1)


if __name__ == "__main__":
    raise SystemExit(main())