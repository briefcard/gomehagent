"""The open defects, as assertions that PASS while they are still broken.

A handoff written in prose rots. `SYSTEMS-REFERENCE.md` was the proof: it
described a `kb_needs` list that had gained three tokens and nothing told
anyone — fixed 2026-08-31 by generating the half that describes the code and
byte-comparing it, which is the same move as this file one level up. The code
facts a thread hands to the next thread live HERE, not in a document: every
entry asserts the defect is still present, and the moment someone fixes it
this suite FAILS and says which paragraph of `WALKTHROUGH-PROMPT.md` §5 to
delete.

That inversion is the point. A test that goes red on GOOD news cannot rot
quietly: the fix cannot land without the ledger being updated in the same
commit. This file should shrink to nothing.

Run: python3 scripts/test_open_defects.py
"""
import os
import pathlib
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'od.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER = "WALKTHROUGH-PROMPT.md §5"

_fail = []
#: The entries that reported open, counted rather than asserted. The summary
#: line said "all 3 defects still open" from a hardcoded 3, so closing one left
#: it claiming three while printing two — a count written beside the thing it
#: counts, in the one file whose entire job is refusing exactly that.
_open = []


def still_broken(what, cond, fixed_msg):
    """PASSES while the defect stands. Fails — loudly — once it is fixed."""
    if cond:
        _open.append(what)
        print(f"  [ open  ] {what}")
    else:
        _fail.append(f"{what}\n      FIXED — now delete it from {LEDGER}: {fixed_msg}")
        print(f"  [ FIXED ] {what}")


def main():
    from app import systems  # noqa: E402

    print("\nopen defects — each PASSES while still broken\n")

    # 1 — the archive holds inbound mail only.
    #     `EmailLog.body_excerpt` is written from the customer's words; our
    #     reply goes into an Approval payload and is never indexed. So the
    #     mail path can answer "what did they ask before" and never "how did
    #     we answer" — the response-pattern context the owner asked for.
    src = (ROOT / "app" / "worker.py").read_text()
    indexes_our_reply = "body_excerpt" in src and (
        "draft" in src.split("body_excerpt")[0][-400:].lower()
    )
    still_broken(
        "the correspondence archive indexes inbound mail only",
        not indexes_our_reply,
        "worker.py now indexes a sent reply — response patterns are assembled context",
    )

    # 3 — CLOSED 2026-09-02. The `auto` rung now pushes: `blog` decides its own
    #     pending ship through `approvals.ship_unattended`, which goes through
    #     `apply_decision` and the same executor arm a person would trigger, and
    #     marks the run `auto` so an unattended publish is distinguishable from
    #     a human one. `systems.AUTO_SHIPS` holds the per-system answer —
    #     `campaign_email` is off there by the owner's decision ("Leave it
    #     human, in the ESP"), and `ad_creative` because no ad-platform write
    #     exists to turn on.
    #
    #     The check that held this entry open looked for a branch on the word
    #     "cleared". It was a PROXY, and the fix does not take that shape — the
    #     rung is read, not the disposition string — so the proxy would have
    #     gone on reporting the defect after it was fixed. A ledger that fails
    #     on good news has to be measuring the news.

    # 4 — five CATALOG systems have no skill, so no contract reaches them.
    from app import skill  # noqa: E402

    import app.skill_pack  # noqa: F401,E402  (registers the skills)

    skilled = {
        (getattr(s, "system", None) or getattr(s, "system_key", None))
        for s in skill.REGISTRY.values()
    }
    unskilled = sorted(k for k in systems.CATALOG if k not in skilled)
    still_broken(
        f"{len(unskilled)} CATALOG system(s) have no skill: {unskilled}",
        bool(unskilled),
        "every declared system has a generator, so the contract reaches all of them",
    )

    print(
        "\n"
        + (
            f"all {len(_open)} defect(s) still open — ledger is accurate"
            if not _fail
            else f"{len(_fail)} entry(s) are STALE:\n  - " + "\n  - ".join(_fail)
        )
    )
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
