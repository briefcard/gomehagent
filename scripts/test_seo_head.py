"""The title that ships is a title, not the search query.

Owner, 2026-08-29: *"Did you handle the SEO title / Title / Meta description
etc issue? For some reason you just put in the keyword instead of optimizing
with a human-facing name that incorporates the optimized keywords."*

Reproduced, and the cause was one line upstream of the SEO helpers:

    title = keyword[:1].upper() + keyword[1:]

The article's Title was set to the capitalised SEARCH QUERY, and the H1 the
drafter is explicitly asked for ("an H1 that is the article's title",
`_ARTICLE_SYSTEM`) was written into the body and never read. `_seo_title` then
saw the keyword already "in" the title, returned it unchanged, and BOTH fields
shipped as the raw phrase — which looked like a deliberate optimisation rather
than a bug.

Two further defects fell out of the same read:

  · `_seo_title` matched the keyword by EXACT SUBSTRING, so "Melamine and
    Acrylic Dinnerware, Compared" counted as missing "acrylic dinnerware
    sets" and got the query stapled on — after which the 60-character trim
    ate the human half, leaving the query plus a fragment.
  · `_meta_description` stripped every tag and took the opening text, so the
    snippet began by repeating the H1 directly above it in the result.

    python3 scripts/test_seo_head.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sh.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.skill_pack import (_ARTICLE_SYSTEM, _h1_of,  # noqa: E402
                            _meta_description, _seo_title, _targets_keyword)

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    print("— the model's own H1 is the title —")
    ck("the H1 is read out of the body",
       _h1_of("<h1>Melamine vs Acrylic: What Actually Lasts</h1><p>x</p>")
       == "Melamine vs Acrylic: What Actually Lasts")
    ck("markup inside it is stripped",
       _h1_of("<h1>Acrylic <em>vs</em> Melamine</h1>") == "Acrylic vs Melamine")
    ck("no H1 is reported as no H1, not as an empty success",
       _h1_of("<p>no heading here</p>") == "")
    ck("the drafter is TOLD the H1 ships as the title",
       "THE H1 IS THE TITLE THAT SHIPS" in _ARTICLE_SYSTEM)
    ck("…and told not to hand back the bare query",
       "bare search query" in _ARTICLE_SYSTEM
       or "Buy acrylic dinnerware" in _ARTICLE_SYSTEM)

    print("\n— a title that already targets the query is LEFT ALONE —")
    # The exact case the old substring test got wrong.
    kw, good = "acrylic dinnerware sets", "Melamine and Acrylic Dinnerware, Compared"
    ck("token coverage sees that this title targets the query",
       _targets_keyword(kw, good), "'sets' is missing and it still targets it")
    ck("…so it ships unchanged, unstuffed",
       _seo_title(kw, good) == good, _seo_title(kw, good))
    ck("one incidental shared word is NOT targeting",
       not _targets_keyword("miami event space for corporate events",
                            "Miami: A Love Letter"),
       "otherwise every title about anything counts")

    print("\n— when it genuinely misses, BOTH halves survive —")
    off = "Ten Ideas for a Summer Table"
    out = _seo_title(kw, off)
    ck("the query is added", "Acrylic dinnerware sets" in out, out)
    ck("…and the human title is still there — the old code trimmed the joined "
       "string, so the half that disappeared was the readable one",
       "Summer Table" in out, out)
    ck("…within the budget", len(out) <= 60, f"{len(out)} chars")

    print("\n— a long query never eats the title —")
    long_kw = "best melamine dinnerware vs acrylic for outdoor entertaining"
    human = "Which Dinnerware Actually Survives a Season Outdoors"
    got = _seo_title(long_kw, human)
    ck("with no room for both, the HUMAN title wins",
       got == human,
       "a page that ranks slightly worse and gets clicked beats one that "
       "ranks and does not")

    print("\n— the title tag is never the bare query when a title exists —")
    for kw2, t2 in ((kw, good), (kw, off), (long_kw, human)):
        ck(f"  {kw2[:28]!r} → not the bare query",
           _seo_title(kw2, t2).strip().lower() != kw2.strip().lower(),
           _seo_title(kw2, t2))
    ck("with NO title at all it falls back to the query — and the run says so",
       _seo_title(kw, "") == "Acrylic dinnerware sets",
       "the note is asserted in test_blog's run, not here")

    print("\n— the description does not repeat the title —")
    body = ("<h1>A Summer Table</h1><p>There is a certain kind of evening "
            "where the table matters more than the food.</p>")
    d = _meta_description("acrylic dinnerware sets", body)
    ck("the H1 is dropped before the snippet is taken",
       not d.lower().startswith("a summer table"), d[:70])
    ck("…and the snippet is the article's own prose", "certain kind" in d)
    withkw = ("<h1>Melamine vs Acrylic</h1><p>Outdoor tables take a beating.</p>"
              "<p>Acrylic dinnerware sets survive 1200 dishwasher cycles.</p>")
    d2 = _meta_description("acrylic dinnerware sets", withkw)
    ck("it still starts at the sentence carrying the query",
       d2.startswith("Acrylic dinnerware sets survive"), d2[:70])
    ck("…and stays inside the snippet budget", len(d2) <= 155, str(len(d2)))

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
