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

    # 4 — SPLIT 2026-09-03. "N CATALOG systems have no skill" counted three
    #     different things as one defect, so this ledger would have gone red
    #     on the WRONG good news and stayed green on the right one:
    #
    #     - BY DESIGN: `moment_email` and `content_compliance` declare no
    #       skill because there is nothing to draft and nothing to review —
    #       `workflow.ship_by` names the code that performs the ship and the
    #       register resolves it. Giving one of these a skill would be a
    #       design change, and must not read as a fix.
    #     - UNBUILT: `gbp_post` and `gbp_listing` declare `ship_by=""` —
    #       NOTHING performs the ship, because the `gbp` capability is wired
    #       for no account until Google API access is applied for. THAT is
    #       the defect, and the good news is either of them naming what
    #       performs its ship.
    #
    #     The buckets are computed from the declaration (`ship_by`, resolved
    #     by `register.system_ships`), never listed here — a thirteenth system
    #     lands in the right bucket by what it declares. What IS written here
    #     is the CLAIM: which systems the ledger says are unbuilt. A count
    #     would have stayed "open" while one of the two was built (2 -> 1 is
    #     still truthy); the set goes red the moment either moves.
    from app import skill  # noqa: E402

    import app.skill_pack  # noqa: F401,E402  (registers the skills)
    import register as _reg  # noqa: E402  (scripts/ is sys.path[0] when run)

    skilled = {
        (getattr(s, "system", None) or getattr(s, "system_key", None))
        for s in skill.REGISTRY.values()
    }
    unskilled = sorted(k for k in systems.CATALOG if k not in skilled)
    ships = {r["system"]: r for r in _reg.system_ships()}
    unbuilt = sorted(
        k for k in unskilled
        if not (systems.CATALOG[k].get("workflow") or {}).get("ship_by")
    )
    by_design = sorted(k for k in unskilled if ships[k]["ok"])
    stray = sorted(set(unskilled) - set(unbuilt) - set(by_design))
    print(f"  [design ] {len(by_design)} system(s) have no skill BY DESIGN — "
          f"nothing to draft, and ship_by resolves: {by_design}")

    # EMPTY since 2026-09-04: gbp_post (the publish arm + skill) and
    # gbp_listing (the audit + fixes) both name what performs their ship.
    # Kept as the claim so a system declared without a performer lands
    # here as unrecorded news rather than nowhere.
    RECORDED_UNBUILT: set = set()
    built = sorted(RECORDED_UNBUILT - set(unbuilt))
    new_unbuilt = sorted(set(unbuilt) - RECORDED_UNBUILT)
    if RECORDED_UNBUILT:
        still_broken(
            f"{len(unbuilt)} CATALOG system(s) are UNBUILT — no skill, and "
            f"nothing performs the ship (ship_by empty): {unbuilt}",
            not built,
            f"{built} now name(s) what performs its ship — shrink RECORDED_UNBUILT here",
        )
    else:
        print("  [ built ] every declared system names what performs its ship")
    if new_unbuilt:
        _fail.append(
            f"{new_unbuilt} declare(s) no skill AND no ship_by, and the ledger "
            f"does not record it — a new unbuilt system: add it to {LEDGER} "
            f"and to RECORDED_UNBUILT here, or declare what performs its ship"
        )
    if stray:
        _fail.append(
            f"{stray} declare(s) no skill and a ship_by the register cannot "
            f"resolve: {[ships[k]['why'] for k in stray]} — neither by design "
            f"nor unbuilt; fix the declaration"
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
