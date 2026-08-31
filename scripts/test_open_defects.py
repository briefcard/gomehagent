"""The open defects, as assertions that PASS while they are still broken.

A handoff written in prose rots. `SYSTEMS-REFERENCE.md` is the proof: it still
describes a `kb_needs` list that gained three tokens, and nothing told anyone.
So the code facts a thread hands to the next thread live HERE, not in a
document — every entry asserts the defect is still present, and the moment
someone fixes it this suite FAILS and says which paragraph of
`WALKTHROUGH-PROMPT.md` §5 to delete.

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


def still_broken(what, cond, fixed_msg):
    """PASSES while the defect stands. Fails — loudly — once it is fixed."""
    if cond:
        print(f"  [ open  ] {what}")
    else:
        _fail.append(f"{what}\n      FIXED — now delete it from {LEDGER}: {fixed_msg}")
        print(f"  [ FIXED ] {what}")


def main():
    from app import dossier, systems  # noqa: E402

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

    # 2b — dossier.SCOPES has drifted from systems.CATALOG.
    scopes, catalog = set(dossier.SCOPES), set(systems.CATALOG)
    orphan_scopes = sorted(s for s in scopes - catalog if s)
    uncovered = sorted(catalog - scopes)
    still_broken(
        f"dossier.SCOPES drift: {len(orphan_scopes)} orphan key(s) {orphan_scopes}, "
        f"{len(uncovered)} system(s) with no scope",
        bool(orphan_scopes or uncovered),
        "SCOPES is derived from CATALOG, so drift is impossible",
    )

    # 2c — SYSTEMS-REFERENCE.md is stale: it names fewer kb_needs for
    #      campaign_email than the code declares.
    # Scanned against campaign_email's OWN "KB:" line. Searching the whole
    # 31KB document finds "tone" and "claim" somewhere on every page and
    # reports the doc current when its own line lists four of seven.
    ref = (ROOT / "SYSTEMS-REFERENCE.md").read_text()
    declared = set(systems.CATALOG["campaign_email"].get("kb_needs") or ())
    _kb_line = ""
    _lines = ref.splitlines()
    for _i, _ln in enumerate(_lines):
        if _ln.strip().rstrip(":").endswith("campaign_email") and _ln.startswith("#"):
            for _next in _lines[_i + 1 : _i + 25]:
                if _next.startswith("#"):
                    break
                _m = re.search(r"KB:([^\n.]*)", _next)
                if _m:
                    _kb_line = _m.group(1)
                    break
            break
    assert _kb_line, "could not locate campaign_email's KB line — fix this check, not the doc"
    missing_from_doc = sorted(t for t in declared if t not in _kb_line)
    still_broken(
        f"SYSTEMS-REFERENCE.md omits {len(missing_from_doc)} declared kb_needs "
        f"token(s) for campaign_email: {missing_from_doc}",
        bool(missing_from_doc),
        "the reference is regenerated from CATALOG rather than hand-written",
    )

    # 3 — the `auto` rung cannot actually push.
    #     It produces "cleared", and nothing consumes that word.
    # The bare word appears in seven modules for unrelated reasons (digest
    # counts, cleared concerns, keyword priority). What matters is whether any
    # PRODUCTION module BRANCHES on the disposition. Only scripts/test_skill.py
    # does, and a test reading it is not a consumer.
    _branch = re.compile(r'(==|!=|\bis)\s*"cleared"|"cleared"\s*(==|!=)')
    consumers = sorted(
        p.name for p in (ROOT / "app").glob("*.py") if _branch.search(p.read_text())
    )
    emits = '"cleared"' in (ROOT / "app" / "skill.py").read_text()
    still_broken(
        'the `auto` rung emits "cleared", which no production module branches on',
        emits and not consumers,
        f"{consumers} now act on it — auto can push",
    )

    # 4 — five CATALOG systems have no skill, so no contract reaches them.
    from app import skill  # noqa: E402

    import app.skill_pack  # noqa: F401,E402  (registers the skills)

    skilled = {
        (getattr(s, "system", None) or getattr(s, "system_key", None))
        for s in skill.REGISTRY.values()
    }
    unskilled = sorted(k for k in catalog if k not in skilled)
    still_broken(
        f"{len(unskilled)} CATALOG system(s) have no skill: {unskilled}",
        bool(unskilled),
        "every declared system has a generator, so the contract reaches all of them",
    )

    print(
        "\n"
        + (
            f"all {5} defects still open — ledger is accurate"
            if not _fail
            else f"{len(_fail)} entry(s) are STALE:\n  - " + "\n  - ".join(_fail)
        )
    )
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
