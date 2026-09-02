"""A rung describes what it actually does, computed rather than asserted.

Ledger entry: *the `auto` rung emits "cleared", which no production module
branches on.*

`_disposition` returns `cleared` for everything on `auto`, and for non-writing
work on `approve_exceptions`. `Context.emit` queues an approval only on
`needs_approval` — so a `cleared` item is drafted, filed, and acted on by
nothing at all. An owner who promoted a system to the top of the ladder got
exactly the outcome they got at the bottom of it.

Meanwhile the console said `auto` "Sends without asking. Alerts on anomaly.
Kill criteria are armed." and `approve_exceptions` "Routine output sends
itself". Both false, both hand-written, and that is precisely why it survived:
the PROMISE lived in a string and the BEHAVIOUR lived in a branch nobody had.

SO THE SENTENCE IS DERIVED FROM THE BRANCH. Hand-correcting the string would
rot the other way the moment somebody wires the push — telling an owner their
automatic system does nothing while it publishes to a live site. This asserts
BOTH directions, so neither drift is possible.

Run: python3 scripts/test_rung_truth.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rt.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import skill, systems  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    print("— the disposition the upper rungs produce —")
    ck("auto clears", skill._disposition("auto", True, True) == "cleared")
    ck("  and so does non-writing work a rung down",
       skill._disposition("approve_exceptions", True, False) == "cleared",
       "both rungs promise sending, and both arrive at the same word")
    ck("a write at approve_exceptions still asks",
       skill._disposition("approve_exceptions", True, True) == "needs_approval")
    ck("and a validator failure outranks every rung",
       skill._disposition("auto", False, True) == "blocked",
       "`auto` does not mean send the thing that failed the check")

    print()
    print("— whether anything acts on it is COMPUTED —")
    wired = systems.CLEARED_IS_WIRED
    ck("the answer is a boolean about the source, not a written-down claim",
       isinstance(wired, bool))
    ck("  and it agrees with a fresh scan",
       systems._cleared_has_a_consumer() == wired,
       "one reader, so the card and the ledger cannot disagree")
    # THE SCANNER ITSELF. Without this, breaking the search is invisible: the
    # codebase currently has no consumer, so a scanner that can no longer FIND
    # one returns the same answer as a working one and the card tells the
    # truth by accident — until the day somebody wires the push, which is the
    # one day it matters. Reported [ MISSED ] on exactly that mutation.
    ck("it recognises a real consumer",
       systems.branches_on_cleared('if item["disposition"] == "cleared":'),
       "a comparison against the word is what wiring looks like")
    ck("  in either order",
       systems.branches_on_cleared('if "cleared" != d: pass'))
    ck("  and does not count a mention",
       not systems.branches_on_cleared('n = counts["cleared"] + 1')
       and not systems.branches_on_cleared('note("cleared the queue")'),
       "the bare word occurs for unrelated reasons — digest counts, cleared "
       "concerns, keyword priority — and counting those would report the rung "
       "as wired the day somebody renames a variable")

    print()
    print("— and the sentence follows it, in BOTH directions —")
    auto = systems.AUTONOMY_MEANING["auto"]
    exc = systems.AUTONOMY_MEANING["approve_exceptions"]
    if wired:
        ck("wired: auto says it sends", "Sends without asking" in auto, auto)
        ck("  and the rung below says routine output sends itself",
           "sends itself" in exc, exc)
    else:
        ck("unwired: auto does not claim to send",
           "Sends without asking." not in auto and "Meant to" in auto,
           auto[:90] + " — an owner at the top of the ladder gets the same "
           "outcome as the bottom, and the card used to say otherwise")
        ck("  and it names what is missing",
           "cleared" in auto and "drafted and waits" in auto,
           "'nothing happens' is a complaint; naming the disposition and the "
           "absent consumer is something somebody can act on")
        ck("  the rung below stops claiming routine output sends",
           "sends itself" not in exc, exc[:90])
        ck("  while still describing what it DOES do",
           "waits for you" in exc, exc[:90])

    print()
    print("— the learning rung was always honest and stays untouched —")
    ck("shadow still says every draft waits",
       "waits for your tap" in systems.AUTONOMY_MEANING["shadow"],
       "it was the one rung whose sentence was true")

    print()
    print("— every rung has a meaning and a label —")
    ck("no rung is undescribed",
       all(systems.AUTONOMY_MEANING.get(r) for r in systems.AUTONOMY),
       str(systems.AUTONOMY))
    ck("  and none is unnamed",
       all(systems.autonomy_label(r) != r for r in systems.AUTONOMY),
       "a rung rendering as its stored value is a card with a column name on "
       "it")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
