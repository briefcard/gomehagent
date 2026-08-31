"""Everything `systems.CATALOG` declares reaches something that reads it.

`kb_needs` is a vocabulary DECLARED in one file and ANSWERED in another, and
until 2026-08-31 nothing joined the two lists. `asset` was added to
`campaign_email`'s `kb_needs` in the walk that discovered the drafter had been
eating the approved asset library all along — and `kb.needs_met` had no answer
for it, defaulting to satisfied. On `baci`, an account with zero assets of any
kind, the install screen drew `asset` with a green tick.

That is the shape this codebase keeps closing: read by one place, supplied by
another, with nothing declaring the obligation. The answer is never a longer
checklist — it is a JOIN, computed from the declaration, that fails in the
commit that breaks it.

WHAT IS ASSERTED:

  · Every `kb_needs` token any system declares has an ANSWER in
    `kb.KB_SUPPLIERS`. Without one it is silently met and the system reports
    ready on knowledge nobody supplied.
  · Every token also has a LABEL in `systems.NEEDS` — the table the system
    card and the skill override both read to say what a person should go and
    do about it, and which queue holds it.
  · Every `constitutive` need a SKILL declares is answerable too. Those run
    through the same `kb.needs_met`, and a constitutive token with no answer
    does not merely mis-report: it lets a run proceed past the one gate that
    was supposed to stop it.
  · An unanswerable token names itself as a code defect rather than reporting
    met, so the branch is honest even if this suite is ever bypassed.
  · Every `sub` a need points at is a Review tab that exists — a "decide -->"
    link into a queue with no page is a fact reported with no control.

Only demand-without-supply fails. A supplier with no declaration (today:
`positioning`) is a real brand field a system may yet declare, and answering
one costs nothing.

Run: python3 scripts/test_catalog_vocabulary.py
"""
import os
import pathlib
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cv.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = pathlib.Path(__file__).resolve().parent.parent

from app import db, kb, skill, systems  # noqa: E402
import app.skill_pack  # noqa: F401,E402  (registers the skills)

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    answered = set(kb.KB_SUPPLIERS)
    labelled = set(systems.NEEDS)

    # Computed from the declaration, never listed here — a system added next
    # month is measured by the same walk.
    declared = {}
    for key, sp in systems.CATALOG.items():
        for tok in (sp.get("kb_needs") or ()):
            declared.setdefault(tok, []).append(key)
    ck("CATALOG declares a kb_needs vocabulary", len(declared) >= 5,
       f"{len(declared)} token(s) across {len(systems.CATALOG)} systems")

    unanswered = sorted(t for t in declared if t not in answered)
    ck("every declared kb_needs token has an answer", not unanswered,
       ", ".join(f"{t} (declared by {', '.join(declared[t])})"
                 for t in unanswered)
       or "a token with no supplier is silently MET, and the system reports "
          "ready on knowledge nobody gave it")

    unlabelled = sorted(t for t in declared if t not in labelled)
    ck("every declared kb_needs token has a label and a queue", not unlabelled,
       ", ".join(unlabelled)
       or "systems.NEEDS is what the card and the override both read")

    # The skill side of the same lookup. `skill.run` calls `kb.needs_met` with
    # `constitutive`, and that one BLOCKS — so an unanswerable token there is
    # not a mis-report, it is a gate that opens.
    const = {}
    for k, sk in skill.REGISTRY.items():
        for tok in (getattr(sk, "constitutive", ()) or ()):
            const.setdefault(tok, []).append(k)
    bad_const = sorted(t for t in const if t not in answered)
    ck("every constitutive need a skill declares is answerable", not bad_const,
       ", ".join(f"{t} (on {', '.join(const[t])})" for t in bad_const)
       or f"{len(const)} token(s) across the registry")

    # What being wrong looks like, asserted rather than assumed: if this branch
    # is ever reached it must not read as an account gap somebody can fill.
    said = kb.needs_met("no-such-tenant-x", ("definitely_not_a_token",))
    ck("an account with no brand row says so first", said == ["kb_brand row"],
       str(said))
    kb.ensure_brand("vocabtest", "Vocab Test")
    said = kb.needs_met("vocabtest", ("definitely_not_a_token",))
    ck("an unanswerable token names itself a code defect",
       len(said) == 1 and "code defect" in said[0], str(said))
    ck("an unanswerable token is never reported as met", said != [],
       "have.get(f, True) reported success for anything it did not know")

    # Design rule 1: the "decide -->" beside a need has to land somewhere.
    ui = (ROOT / "app" / "admin_ui.py").read_text()
    subs = sorted({m["sub"] for m in systems.NEEDS.values()})
    missing_sub = [s for s in subs if f'("{s}", ' not in ui]
    ck("every need points at a Review tab that exists", not missing_sub,
       ", ".join(missing_sub) or ", ".join(subs))

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print(f"all checks passed — {len(declared)} declared token(s), "
          f"{len(answered)} answered, {len(const)} constitutive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
