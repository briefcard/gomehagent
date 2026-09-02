"""No assertion in any suite is the literal True with nothing behind it.

Owner, 2026-09-02: *"please make sure that you have no more mismatched
assertions."*

A `ck(label, True)` prints [ ok ] and tests nothing. It is worse than no
assertion, because the suite reports one more passing check than it has and
the label reads as coverage of a behaviour nobody exercised. Six were found
across 163 suites — two were claims that could simply be checked, three were
NOTES dressed as checks, and one summarised a loop that would have passed
identically over zero models.

THE LEGITIMATE FORM IS KEPT, and telling them apart is the whole of this
check. This is honest:

    try:
        sites.get("nope")
        ck("unknown site raises", False, "it returned a profile instead")
    except UnknownSite:
        ck("unknown site raises", True)

because the success path fails loudly — the `True` marks reaching a line only
an exception reaches. Five of the eleven were that. So a bare `True` is
allowed exactly when the same label appears with `False` somewhere in the same
file, and refused otherwise.

Run: python3 scripts/test_assertions_can_fail.py
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def hollow_in(source: str) -> list:
    """Bare `ck(label, True)` calls with no `False` counterpart, by line.

    Separate from the file walk so the DETECTOR can be tested against a
    literal. Without that it is untestable the moment the codebase is clean:
    with nothing left to find, breaking the search returns the same empty
    answer as a working search, and the guard reports [ MISSED ] — which is
    exactly what happened, and is the same lesson `branches_on_cleared`
    taught this morning. A check nobody can prove works is a check.
    """
    tree = ast.parse(source)
    false_labels = set()
    for n in _ck_calls(tree):
        if isinstance(n.args[1], ast.Constant) and n.args[1].value is False:
            try:
                false_labels.add(ast.unparse(n.args[0]))
            except Exception:                                    # noqa: BLE001
                pass
    out = []
    for n in _ck_calls(tree):
        if not (isinstance(n.args[1], ast.Constant)
                and n.args[1].value is True):
            continue
        try:
            lbl = ast.unparse(n.args[0])
        except Exception:                                        # noqa: BLE001
            continue
        if lbl not in false_labels:
            out.append((n.lineno, lbl))
    return out


def paired_in(source: str) -> int:
    """How many bare `True`s ARE paired — the honest try/except form."""
    tree = ast.parse(source)
    false_labels = set()
    for n in _ck_calls(tree):
        if isinstance(n.args[1], ast.Constant) and n.args[1].value is False:
            try:
                false_labels.add(ast.unparse(n.args[0]))
            except Exception:                                    # noqa: BLE001
                pass
    n_paired = 0
    for n in _ck_calls(tree):
        if (isinstance(n.args[1], ast.Constant) and n.args[1].value is True):
            try:
                if ast.unparse(n.args[0]) in false_labels:
                    n_paired += 1
            except Exception:                                    # noqa: BLE001
                pass
    return n_paired


def _ck_calls(tree):
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ck"
                and len(n.args) >= 2):
            yield n


def main() -> int:
    suites = sorted(ROOT.glob("scripts/test_*.py"))
    ck("there are suites to check", len(suites) > 100, str(len(suites)))

    hollow, paired, checked = [], 0, 0
    for f in suites:
        if f.name == pathlib.Path(__file__).name:
            continue
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        checked += 1
        src = f.read_text()
        paired += paired_in(src)
        hollow += [f"{f.name}:{ln} {lbl[:60]}" for ln, lbl in hollow_in(src)]

    ck("every suite parsed", checked >= len(suites) - 1, f"{checked} parsed")
    ck("the try/except form is recognised, not banned",
       paired > 0,
       f"{paired} paired True(s) — if this were 0 the check below would be "
       f"passing because it found nothing, not because nothing is wrong")
    # THE DETECTOR ITSELF, against literals. With the codebase clean, breaking
    # the search returns the same empty answer as a working one — so the check
    # below would pass on a scanner that finds nothing at all.
    HOLLOW = 'ck("a claim nobody checked", True)\n'
    HONEST = ('try:\n    boom()\n    ck("it raises", False, "it did not")\n'
              'except Exception:\n    ck("it raises", True)\n')
    ck("it recognises a bare True with nothing behind it",
       len(hollow_in(HOLLOW)) == 1, str(hollow_in(HOLLOW)))
    ck("  and does not flag the try/except form",
       hollow_in(HONEST) == [] and paired_in(HONEST) == 1,
       "five honest assertions in this codebase use it; a check that cried "
       "wolf on them would be turned off")

    ck("no assertion is the literal True with nothing behind it",
       not hollow,
       "; ".join(hollow) or "a `ck(label, True)` prints [ ok ] and tests "
       "nothing — the suite reports a passing check it does not have")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
