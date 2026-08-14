"""Filling a knowledge base must work for a client nobody has thought about.

The first version of this was an orchestrator that named five sources in order
inside an if-tree. It worked for the five accounts that existed. Adding the
spreadsheet upload would have meant editing it, which is the
customisation-in-code pattern decision #3 forbids and which has already caused
three separate defects here — the hardcoded `diagnostic` offer key, the shared
situation constant, and the literal "how fast" objection lookup.

So what is asserted here is not that the four current sources work. It is that
the RUNNER KNOWS NOTHING ABOUT THEM: a source declares itself, an account that
has none of them wired gets honest skips rather than a crash, and what is still
missing comes from `kb.gaps` rather than from prose written per source.

    python3 scripts/test_sources.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'src.db')}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, kb_seed, sources, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    # ---- the registry is a contract, not a convention --------------------
    print("— every source declares itself the same way —")
    for src in sources.SOURCES:
        ck(f"{src['key']} declares the full shape",
           {"key", "label", "produces", "capability", "precondition",
            "run"} <= set(src), str(sorted(src)))
        ck(f"{src['key']} names what it produces", bool(src["produces"]))
        ck(f"{src['key']} is callable", callable(src["run"]))
    keys = [s["key"] for s in sources.SOURCES]
    ck("keys are unique", len(keys) == len(set(keys)), str(keys))
    ck("the seed is NOT a source",
       "seed" not in keys,
       "kb_seed is bootstrap data for the original five, not something a "
       "sixth client has")

    # ---- a client nobody has thought about -------------------------------
    print("\n— an account with nothing wired —")
    with db.SessionLocal() as s:
        s.add(db.Tenant(key="acme", name="Acme Co"))
        s.commit()

    avail = sources.available("acme")
    ck("every source is reported, not silently omitted",
       len(avail) == len(sources.SOURCES))
    ck("none are usable", not any(a["usable"] for a in avail))
    ck("and each says WHY, in words a person can act on",
       all(a["blocked_by"] for a in avail),
       str([a["blocked_by"][:34] for a in avail]))

    r = sources.fill("acme")
    ck("filling it does not raise", isinstance(r, dict) and "sources" in r)
    ck("it reports every source as skipped",
       all(not s["ran"] for s in r["sources"]))
    ck("and it still says what a human must answer",
       len(r["still_needs_a_human"]) > 0,
       f"{len(r['still_needs_a_human'])} questions")
    ck("those questions come from the intake steps, not from prose here",
       {q["field"] for q in r["still_needs_a_human"]}
       <= {s["id"] for s in kb.INTAKE_STEPS})
    ck("an unknown account is refused rather than half-run",
       "unknown tenant" in sources.fill("nope").get("error", ""))

    # ---- one failing source must not stop the rest -----------------------
    print("\n— a source that throws —")
    original = sources.SOURCES[:]
    def _boom(tenant, apply, budget):
        raise RuntimeError("the store is unreachable")
    sources.SOURCES.append({"key": "explodes", "label": "Broken",
                            "produces": "nothing", "capability": "",
                            "precondition": None, "run": _boom})
    r2 = sources.fill("baci")
    broke = next(s for s in r2["sources"] if s["key"] == "explodes")
    ck("the failure is caught and named", "unreachable" in broke.get("error", ""))
    ck("and the other sources still ran",
       len(r2["sources"]) == len(sources.SOURCES),
       "an account whose store is down should still get its website read")

    # ---- adding a source changes no code but the registry ----------------
    ck("a source added at runtime is picked up with no runner change",
       any(s["key"] == "explodes" for s in sources.available("baci")))
    sources.SOURCES[:] = original
    ck("and removing it leaves the registry clean",
       "explodes" not in [s["key"] for s in sources.SOURCES])

    # ---- `only` narrows without special-casing ---------------------------
    print("\n— running one source —")
    r3 = sources.fill("baci", only=["website"])
    ck("only the named source is considered",
       [s["key"] for s in r3["sources"]] == ["website"], str(r3["sources"])[:60])

    # ---- nothing is approved by filling ----------------------------------
    print("\n— filling proposes; it never approves —")
    before = len(kb.claims("baci"))
    sources.fill("baci", apply=False)
    ck("a rehearsal writes nothing", len(kb.claims("baci")) == before)
    ck("and the report says so", "PROPOSALS" in sources.fill("baci")["note"])

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
