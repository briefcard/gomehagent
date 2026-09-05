"""Every criterion asks a question whose good answer is YES, and `pass` says so.

`_ASSESS` never defined what `pass` meant — it said only "Answer each question
about the image". Two of the four spine criteria were then phrased so that the
HONEST answer sets `pass: true` on a failure:

    claim_safe  "Does it show anything that would contradict … the claim?"
    no_text     "Is there any text, lettering, watermark or logo …?"

A picture that contradicts the claim answers YES, and was filed as passing.
Two more were or-questions with no stated good half ("… or like generic
stock?", "… Or does it read as cut out and pasted on?"), which is the same
defect wearing a question mark.

Fixing one and not the others is WORSE than fixing none: the failure list gets
less trustworthy while looking more so. So all of them move together, and the
pass-line moves in the same commit.

And the assertion this suite exists for: the reviewer's output had never once
been tested against a known answer. `llm.ask` is stubbed with a fixed payload
and the resulting `failed` list is asserted.

    python3 scripts/test_the_review_answers_one_question.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rq.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import creative, db, llm, systems, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _answer(verdicts: dict):
    class _R:
        ok, degraded, error = True, "", ""
        text = json.dumps({
            "verdicts": [{"key": k, "pass": v, "why": "because"}
                         for k, v in verdicts.items()],
            "overall": "o", "fix": "f"})
    llm.ask = lambda *a, **k: _R()


def main() -> int:
    db.init_db()
    tenants.seed()
    systems.create("baci", "ad_creative")

    print("— no criterion is phrased so that YES means broken —")
    # A question whose good answer is NO is one that starts by asking whether
    # something UNWANTED is present. These are the two shapes that were wrong.
    bad = {}
    for key, ask in creative.CRITERIA.items():
        low = ask.lower()
        if re.match(r"^(is there any|does it show anything)", low):
            bad[key] = ask
    ck("no criterion asks whether something unwanted is PRESENT",
       not bad, str(list(bad)))
    ck("  claim_safe asks for consistency, not for contradiction",
       creative.CRITERIA["claim_safe"].lower().startswith("is everything"),
       creative.CRITERIA["claim_safe"][:60])
    ck("  no_text asks whether it is FREE of lettering",
       "completely free of text" in creative.CRITERIA["no_text"],
       creative.CRITERIA["no_text"][:60])

    print("\n— and none of them is an or-question with no good half —")
    ors = [k for k, v in creative.CRITERIA.items()
           if re.search(r"\?\s*Or\b", v) or " or like " in v.lower()]
    ck("no criterion offers two answers without saying which is good",
       not ors, str(ors))
    ad = creative.brief_for("baci", fmt="ad_frame", positioning="p")
    ck("  including the ad's own craft question",
       " or is it " not in {c["key"]: c["ask"] for c in ad["criteria"]}["craft"],
       "this one was written in a054632 with the same flaw")

    print("\n— the prompt states what `pass` means, which it never did —")
    ck("the assessor is told YES is the good answer",
       "YES** IS THE GOOD ANSWER" in creative._ASSESS
       or "YES IS THE GOOD ANSWER" in creative._ASSESS.replace("**", ""), "")
    ck("  and told which way to set the flag",
       '"pass": true when the honest answer to the question is yes'
       in creative._ASSESS, "")
    ck("  and told not to reverse it for any question",
       "Do not reverse this" in creative._ASSESS, "")

    print("\n— THE ASSERTION THAT NEVER EXISTED: a known answer in, a known "
          "failure list out —")
    brief = creative.brief_for("baci", fmt="ad_frame", positioning="p",
                               claim="dishwasher safe melamine")
    keys = [c["key"] for c in brief["criteria"]]
    _answer({k: True for k in keys})
    v = creative.assess(b"PNG", brief, "baci")
    ck("all-yes is an empty failure list",
       v["ok"] and v["failed"] == [], str(v.get("failed")))
    _answer({**{k: True for k in keys}, "claim_safe": False, "no_text": False})
    v = creative.assess(b"PNG", brief, "baci")
    ck("a NO on claim_safe and no_text fails exactly those two",
       sorted(v["failed"]) == ["claim_safe", "no_text"], str(v["failed"]))
    ck("  and the others are not swept in with them",
       "on_subject" not in v["failed"] and "craft" not in v["failed"], "")

    print("\n— the questions actually reach the model —")
    seen: list = []

    class _R2:
        ok, degraded, error = True, "", ""
        text = '{"verdicts": [], "overall": "", "fix": ""}'

    llm.ask = lambda purpose, blocks, **k: (seen.append(blocks) or _R2())
    creative.assess(b"PNG", brief, "baci")
    text = " ".join(b.get("text", "") for b in seen[0] if isinstance(b, dict))
    ck("every criterion the brief named is asked",
       all(creative.CRITERIA.get(k, brief and "") [:24] in text
           or k in text for k in keys), str(keys))
    ck("  and the pass-line rides with them",
       "YES" in text and "pass" in text, "")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
