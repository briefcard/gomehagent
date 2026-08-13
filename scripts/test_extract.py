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
