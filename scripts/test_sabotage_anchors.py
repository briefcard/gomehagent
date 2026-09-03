"""Every sabotage entry still patches code that exists.

`sabotage.py` reports a STALE entry loudly — but only when somebody runs it,
and running all of them takes many minutes because each one executes real
suites. So in practice a guard whose target moved goes quiet for weeks, and a
quiet guard is indistinguishable from a passing one. That is the failure the
sabotage harness exists to find, one level up: coverage that silently stopped
covering.

This is the cheap half. No suites run and nothing is patched — it only asks
whether each entry's `find` still appears EXACTLY ONCE in the file it names.
Once, not merely at least once: an anchor matching twice patches the wrong
copy as readily as the right one.

Written 2026-08-28, the day the bidirectional Schedule rewrote a section and
`a_dateless_plan_is_not_scheduled` went stale in a shipped commit without
anybody noticing until the next sweep.

    python3 scripts/test_sabotage_anchors.py
"""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Entries known to be stale, each with the date it was found. This list may
#: SHRINK and must NEVER grow — the same contract as the render-smoke suite's
#: ALLOWED_BARE. A new stale anchor is a guard that stopped covering something
#: in the commit that moved its code, which is exactly when it is cheap to fix.
#:
#: 2026-08-27: found stale at HEAD, predating the UI overhaul's step 4. Each
#: needs its target located and the entry repointed, or the entry deleted with
#: a reason if the behaviour genuinely no longer exists.
#: Suites no guard names yet. May shrink; must never grow. Counted, not
#: remembered — see the check in main().
UNGUARDED: set = set()

KNOWN_STALE = {
    "drafted_is_not_published",
    "withhold_false_or_forbidden",
    "data_layer_says_what_to_fix",
}

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def entries() -> list[dict]:
    tree = ast.parse((ROOT / "scripts" / "sabotage.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) \
                and getattr(node.targets[0], "id", "") == "SABOTAGES":
            out = []
            for e in node.value.elts:
                d = {k.value: v for k, v in zip(e.keys, e.values)}
                # `replace` is extracted too. Without it the parseability
                # check below skipped every entry on `"replace" not in e` and
                # reported clean while seven mutations were syntax errors — a
                # hollow assertion written in the act of removing hollow
                # assertions, which is the whole argument for checking rather
                # than asserting.
                out.append({k: ast.literal_eval(v) for k, v in d.items()
                            if k in ("name", "file", "find", "replace",
                                     "suites")})
            return out
    return []


def _run_suite_src() -> str:
    """`sabotage.run_suite`'s BODY, as source — the docstring stripped.

    Stripped because the docstring explains the string-matching this replaced,
    and a check that reads the explanation as if it were the code would fail on
    the commit that fixed it. What is asserted is what RUNS.
    """
    tree = ast.parse((ROOT / "scripts" / "sabotage.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_suite":
            body = [n for n in node.body
                    if not (isinstance(n, ast.Expr)
                            and isinstance(n.value, ast.Constant)
                            and isinstance(n.value.value, str))]
            return "\n".join(ast.unparse(n) for n in body)
    return ""


def main() -> int:
    rows = entries()
    ck("the sabotage list parses and is populated", len(rows) > 100, str(len(rows)))

    stale, ambiguous = [], []
    for e in rows:
        try:
            text = (ROOT / e["file"]).read_text()
        except OSError:
            stale.append(e["name"])
            continue
        n = text.count(e["find"])
        if n == 0:
            stale.append(e["name"])
        elif n > 1:
            ambiguous.append(f"{e['name']} ({n}×)")

    new_stale = sorted(set(stale) - KNOWN_STALE)
    ck("no NEW guard has gone stale", not new_stale,
       ", ".join(new_stale) or "a guard whose code moved is a guard that "
       "stopped covering it, silently")
    # A MUTATION THAT DOES NOT PARSE PROVES NOTHING. The suite then dies at
    # IMPORT — before it reaches the assertion the guard is named for — so
    # `[ caught ]` is unconditional and would print for a guard pointed at a
    # blank line. Seven guards were in this state when it was first checked,
    # two of them a day old; the pattern is a `\` continuation or a bracket
    # left open by the replacement.
    #
    # This is the check that makes the class impossible rather than the seven
    # fixes, which is why it is here and not a note in a commit message.
    import ast as _ast
    unparseable = []
    for e in rows:
        f = ROOT / e["file"]
        if not f.exists():
            continue
        src = f.read_text()
        if (e["find"] not in src or "replace" not in e
                or f.suffix != ".py"):
            # Only Python can be parsed. A guard on REGISTER.md is mutating
            # markdown, and calling that unparseable would be the check being
            # wrong rather than the guard.
            continue        # staleness, and delete-only entries, handled above
        try:
            _ast.parse(src.replace(e["find"], e["replace"], 1))
        except SyntaxError:
            unparseable.append(e["name"])
    ck("every mutation leaves the file parseable", not unparseable,
       ", ".join(unparseable) or "a mutation that breaks the syntax fails the "
       "suite at import, so [ caught ] is printed without the assertion ever "
       "running")

    # A NAME IS AN ADDRESS. Two guards sharing one means `sabotage.py <name>`
    # runs whichever comes first and the other cannot be reached at all —
    # it is in the list, it is counted, and it can never be run on purpose.
    # Found by an audit: two genuinely different claims (audiences reaching
    # the bundle, and their vocabulary reaching the brief) under one name.
    import collections as _c
    dup_names = sorted(n for n, c in _c.Counter(
        e["name"] for e in rows).items() if c > 1)
    ck("every guard has its own name", not dup_names,
       ", ".join(dup_names) or "a shared name makes one of them "
       "unaddressable, while still being counted as coverage")

    ck("no anchor matches more than once", not ambiguous,
       ", ".join(ambiguous) or "an anchor matching twice patches whichever "
       "copy comes first, which may not be the one under test")

    fixed = sorted(KNOWN_STALE - set(stale))
    ck("the known-stale list has not grown",
       set(stale) <= KNOWN_STALE | set(new_stale),
       "it may shrink; it must never grow")
    if fixed:
        print(f"[  ok  ] {len(fixed)} known-stale entr(y/ies) now resolve — "
              f"remove from KNOWN_STALE: {', '.join(fixed)}")

    ck("every entry names at least one suite",
       all(e.get("suites") for e in rows),
       "an entry with no suite can never be caught or missed")

    # A SUITE NO GUARD NAMES IS A SUITE NOBODY HAS PROVED CAN FAIL. Fifty of
    # 165 were in that state on 2026-09-03 — a third of the suite — and the
    # number was known only from a sentence in a handoff note, which is the
    # exact "claim in a comment" this file exists to refuse. Same shape as
    # KNOWN_STALE and the render smoke's UNWRAPPED_TABLES: named, so a new
    # suite cannot join the list silently, and allowed to shrink only.
    named = {s for e in rows for s in (e.get("suites") or [])}
    unguarded_now = sorted(p.name for p in (ROOT / "scripts").glob("test_*.py")
                           if p.name not in named)
    newly = sorted(set(unguarded_now) - UNGUARDED)
    ck("no NEW suite ships without a guard", not newly,
       ", ".join(newly) or "a suite nothing mutates against is a suite whose "
       "assertions have never been shown to fail")
    now_guarded = sorted(UNGUARDED - set(unguarded_now))
    ck("the unguarded list has not grown",
       set(unguarded_now) <= UNGUARDED | set(newly),
       "it may shrink; it must never grow")
    if now_guarded:
        print(f"[  ok  ] {len(now_guarded)} suite(s) now guarded — remove from "
              f"UNGUARDED: {', '.join(now_guarded)}")

    # THE SUITE HAS TO EXIST. `test_blog.py` and `test_campaign.py` were named
    # by three guards and neither file was in the tree. A suite that cannot be
    # run cannot pass, and `sabotage.py` scored "did not pass" as "the mutation
    # was caught" — so those three printed `[ caught ]` no matter what the
    # mutation did. Removing the phantoms revealed all three as MISSED: the
    # behaviours were never guarded at all. Cheapest possible check, and it
    # runs in the full suite rather than in a sweep nobody has time for.
    phantom = sorted({s for e in rows for s in (e.get("suites") or [])
                      if not (ROOT / "scripts" / s).exists()})
    ck("every suite a guard names exists", not phantom,
       ", ".join(phantom) or "a guard pointing at a missing suite reports "
       "[ caught ] unconditionally, which is worse than no guard")

    # HOW A GUARD IS JUDGED. `run_suite` read two strings out of stdout, which
    # is SYSTEMS-REFERENCE §6's string-matching-instead-of-state-checking rule
    # broken inside the harness that proves the rules are kept: eight suites
    # print neither string, so 42 of 324 guards could never fail. `test_all.sh`
    # has judged the same suites by exit code all along.
    rs = _run_suite_src()
    ck("a guard is judged by the suite's EXIT CODE", "returncode" in rs,
       "run_suite must read the exit status")
    ck("a guard is not judged by matching text in stdout",
       "stdout" not in rs and "all checks passed" not in rs,
       "a suite whose success line does not match reports [ caught ] forever")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print(f"all checks passed — {len(rows)} anchors, "
          f"{len(KNOWN_STALE)} known-stale carried")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
