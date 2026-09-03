"""Every system names what measures it and what learns from it — or the gap.

`measure` in the CATALOG is a sentence and was read nowhere. `edits.record`
wrote draft-vs-sent deltas for weeks and no generator read one. This file holds
the contract that makes that class of absence visible: one EFFECTIVENESS row
per system, every named function resolving to a callable, every blank
explained, and the map rendered where a person reads it.

Run: python3 scripts/test_effectiveness.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ef.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import systems  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    rows = systems.effectiveness()
    keys = {r["system"] for r in rows}
    ck("every CATALOG system has a row", keys == set(systems.CATALOG),
       f"missing: {sorted(set(systems.CATALOG) - keys)}")
    undeclared = [r["system"] for r in rows if "undeclared" in r["gap"]]
    ck("and every row was declared, not synthesised as missing",
       not undeclared, ", ".join(undeclared))

    # Every named function must be real. A dotted name nobody can import is a
    # measurement that exists only in the table.
    bad_m = [r["system"] for r in rows if r["measure_fn"] and not r["measure_ok"]]
    bad_l = [r["system"] for r in rows if r["learns_into"] and not r["learns_ok"]]
    ck("every named measure resolves to a callable", not bad_m, ", ".join(bad_m))
    ck("every named learner resolves to a callable", not bad_l, ", ".join(bad_l))

    # A blank must be a named gap. Blank AND unexplained is the omission this
    # table exists to refuse.
    silent = [r["system"] for r in rows
              if (not r["measure_fn"] or not r["learns_into"])
              and not (r["gap"] or r["how"]).strip()]
    ck("every blank cell names its gap", not silent, ", ".join(silent))

    # The paired negatives: the resolver must say no to a made-up name and to
    # a real module with a made-up function — else the checks above pass on
    # anything.
    ck("a made-up module does not resolve", systems._resolves("nowhere.fn") is False)
    ck("a real module, made-up function does not resolve",
       systems._resolves("keywords.no_such_function") is False)
    ck("a real function does resolve", systems._resolves("keywords.progress") is True,
       "the pair with the two above")

    # A system with no row is reported as a row that says so — never dropped.
    real = systems.EFFECTIVENESS
    systems.EFFECTIVENESS = {k: v for k, v in real.items() if k != "blog"}
    try:
        r = next(x for x in systems.effectiveness() if x["system"] == "blog")
    finally:
        systems.EFFECTIVENESS = real
    ck("a system with no row appears as an undeclared row, not as absence",
       "undeclared" in r["gap"] and r["measure_ok"] is False, r["gap"])

    # THE FINDING THIS TABLE WAS BUILT ON, and its closing. Until 2026-09-03
    # the mail systems recorded every pre-send edit and nothing read one; this
    # line used to hold that as a fact and fail toward good news. The good
    # news arrived: both now measure by the edit trend and learn into the
    # guidance the drafter reads.
    for k in ("service_desk", "lead_responder"):
        r = next(x for x in rows if x["system"] == k)
        ck(f"{k} measures by the edit trend and learns into the drafter's guidance",
           r["measure_fn"] == "edits.trend" and r["measure_ok"]
           and r["learns_into"] == "systems.guidance_block" and r["learns_ok"],
           str({kk: r[kk] for kk in ("measure_fn", "measure_ok", "learns_into", "learns_ok")}))

    # It renders where somebody reads it.
    doc = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "SYSTEMS-REFERENCE.md")).read()
    ck("the map is in the reference", "2c. The effectiveness map" in doc)
    ck("  with every system in it",
       all(f"| `{k}` |" in doc for k in systems.CATALOG),
       str([k for k in systems.CATALOG if f"| `{k}` |" not in doc]))

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
