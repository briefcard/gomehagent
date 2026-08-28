"""The one list that blocks every draft can now be subtracted from — safely.

`banned_claims` is the hard compliance boundary: the validator rejects any
draft containing one of these strings, and for Baci they are the difference
between "Italian-designed" and a made-in-Italy claim that is not true. It
could be ADDED to and never subtracted from. A phrase typed by mistake, or one
that stopped being true, was permanent — the only way out was editing the
database by hand, which is a fix instruction that lives nowhere on the surface
(design rule 1) and in practice means nobody ever removes one.

Two properties, and the second is why this file exists rather than a couple of
extra checks in `test_brand_theme.py`:

  1. **Lifting is not deleting, and restoring is not duplicating.** The phrase
     moves to `lifted_claims` with who and when; adding it back CLEARS that
     entry, so the tab never says "enforced" and "lifted" about the same rule.

  2. **ONE WRITER, COMPUTED.** `systems.promote_rule` kept its own copy of the
     append for months — a second writer to this list. That is survivable
     while the list only grows; the moment removal exists it is a path that
     can silently contradict the lifted record. So this file does not assert
     that there is one writer, it PARSES app/ with `ast` and fails if any
     assignment to `.banned_claims` appears outside `kb.py`'s two named
     functions. SYSTEMS-REFERENCE §6b: a claim about EVERY instance has to be
     derived from the code, because the instance you did not think of is
     precisely the one that is broken.

    python3 scripts/test_ban_list.py
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ban.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = pathlib.Path(__file__).resolve().parent.parent

from fastapi.testclient import TestClient        # noqa: E402

from app import admin_ui, db, kb, systems, web   # noqa: E402

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _writers() -> list[tuple[str, str]]:
    """Every assignment to a `.banned_claims` attribute in app/, as
    (file, enclosing function). Derived, never listed."""
    out: list[tuple[str, str]] = []
    for path in sorted(ROOT.joinpath("app").glob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target] if isinstance(node, ast.AugAssign)
                           else [])
                for t in targets:
                    if isinstance(t, ast.Attribute) and t.attr == "banned_claims":
                        out.append((path.name, fn.name))
    return out


def main() -> int:
    db.init_db()
    with db.SessionLocal() as s:
        s.add(db.Tenant(key="baci", name="Baci Milano USA",
                        domain="bacimilanousa.com"))
        s.commit()
    kb.ensure_brand("baci", "Baci Milano USA")

    # ── 1. one writer, computed from the source ────────────────────────────
    writers = _writers()
    print(f"— assignments to .banned_claims in app/: {writers} —")
    ck("the sweep found a real population, not an empty parse", len(writers) >= 2,
       str(writers))
    ck("every writer of the ban list lives in kb.py",
       all(f == "kb.py" for f, _ in writers),
       "; ".join(f"{f}:{fn}" for f, fn in writers if f != "kb.py")
       or "a second writer can contradict the lifted record")
    ck("there is exactly one appender and one subtractor",
       sorted(fn for _f, fn in writers) == ["add_banned", "remove_banned"],
       str(sorted(fn for _f, fn in writers)))

    # ── 2. lift, restore, and the record between them ──────────────────────
    kb.add_banned("baci", "made in Italy")
    kb.add_banned("baci", "hand-decorated")
    ck("rules go on", kb.banned_claims("baci") == ["made in Italy",
                                                   "hand-decorated"])

    said = kb.remove_banned("baci", "MADE IN ITALY")
    ck("lifting matches case-insensitively, the way the validator does",
       "made in Italy" not in kb.banned_claims("baci"), said)
    ck("…and says the CONSEQUENCE, not that a row changed",
       "no longer blocked" in said, said)
    lifted = kb.lifted_claims("baci")
    ck("nothing was deleted — the lift is recorded with who and when",
       len(lifted) == 1 and lifted[0]["phrase"] == "made in Italy"
       and lifted[0]["by"] == "owner" and lifted[0]["at"], str(lifted))
    ck("the phrase is stored AS WRITTEN, not as typed into the control",
       lifted[0]["phrase"] == "made in Italy")
    ck("lifting something that is not a rule refuses with a reason",
       "not a hard rule" in kb.remove_banned("baci", "nonesuch"))
    ck("lifting on an account with no brand row refuses rather than raising",
       "No brand record" in kb.remove_banned("no-such-tenant", "x"))

    kb.add_banned("baci", "made in Italy")
    ck("restoring puts it back in front of every draft",
       "made in Italy" in kb.banned_claims("baci"))
    # The guard `a_lifted_rule_stays_lifted` breaks exactly this line.
    ck("…and CLEARS the lifted record — enforced and lifted are opposites",
       kb.lifted_claims("baci") == [],
       "a rule listed as both is the same fact stated twice, in contradiction")

    # ── 3. promotion routes through the one writer ─────────────────────────
    # The guard `one_writer_owns_the_ban_list` restores the second writer.
    kb.remove_banned("baci", "hand-decorated")
    ck("a lifted rule is lifted before promotion runs",
       kb.lifted_claims("baci") and "hand-decorated" not in kb.banned_claims("baci"))
    systems.promote_rule("baci", "hand-decorated")
    ck("promoting a lifted phrase re-enforces it AND clears the lifted record",
       "hand-decorated" in kb.banned_claims("baci")
       and kb.lifted_claims("baci") == [],
       "promotion kept its own append for months; a second writer leaves the "
       "rule enforced while the tab still lists it as lifted")
    ck("promotion's own vocabulary is unchanged for its callers",
       "Already a rule" in systems.promote_rule("baci", "hand-decorated"))
    ck("promotion still REFUSES an account with no brand row (it does not "
       "conjure one — /admin/system_rule branches on this sentence)",
       systems.promote_rule("ghost", "x").startswith("No KB brand row"))

    # ── 4. the console: every rule carries its own lift ─────────────────────
    kb.remove_banned("baci", "hand-decorated")
    page = admin_ui.render_brand("s3cret", "baci")
    ck("each enforced rule folds open to its own lift, on the same surface",
       'name="drop_banned" value="made in Italy"' in page
       and "Lift this rule" in page)
    ck("the fold states the consequence before the button",
       "no longer blocked" in page or "may say it" in page)
    ck("what was lifted is listed, with the way back",
       "Lifted rules (1)" in page
       and 'name="add_banned" value="hand-decorated"' in page
       and "Restore this rule" in page)

    c = TestClient(web.app)
    c.get("/admin/ui", params={"key": "s3cret"})           # session cookie
    r = c.post("/admin/brand_update",
               data={"tenant": "baci", "drop_banned": "made in Italy"},
               follow_redirects=False)
    ck("the lift round-trips through the console and lands on Brand",
       r.status_code == 303 and "tab=brand" in r.headers["location"]
       and "made in Italy" not in kb.banned_claims("baci"))
    ck("…and the flash says what happened",
       "no+longer+blocked" in r.headers["location"]
       or "no%20longer%20blocked" in r.headers["location"]
       or "not+blocked" in r.headers["location"], r.headers["location"][:160])
    c.post("/admin/brand_update",
           data={"tenant": "baci", "add_banned": "made in Italy"},
           follow_redirects=False)
    ck("the restore round-trips through the same one writer",
       "made in Italy" in kb.banned_claims("baci")
       and all(x["phrase"] != "made in Italy" for x in kb.lifted_claims("baci")))

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
