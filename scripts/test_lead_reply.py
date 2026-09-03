"""Every system the mail path routes to has a skill of its own.

`replies.ROUTES` sends `sales_leads` to `lead_responder` and order mail to
`service_desk`. The responder files each run under the system it was called
for, but a Skill binds one system_key — so only service_desk had a skill, and
lead_responder read as "no generator yet" to autonomy, readiness and the
effectiveness map while answering mail all day. One run function, two
envelopes, and a rule that says so for whatever ROUTES adds next.

Run: python3 scripts/test_lead_reply.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'lr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import replies, skill, skill_pack, systems  # noqa: E402, F401

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    by_system = {}
    for key, sk in skill.REGISTRY.items():
        by_system.setdefault(sk.system_key, []).append(key)

    # THE RULE. Derived from ROUTES, so a bucket routed to a new system next
    # month fails here until that system has a skill.
    routed = {v for v in replies.ROUTES.values() if v in systems.CATALOG}
    unbound = sorted(k for k in routed if not by_system.get(k))
    ck("every system the mail path routes to has a skill",
       not unbound, ", ".join(unbound) or f"routed: {sorted(routed)}")
    ck("  and the rule has something to bind — ROUTES is not empty",
       len(routed) >= 2, str(sorted(routed)))

    lead = skill.get("lead_reply")
    desk = skill.get("inbound_reply")
    ck("lead_reply is registered", lead is not None)
    ck("  bound to lead_responder, not service_desk",
       lead is not None and lead.system_key == "lead_responder",
       getattr(lead, "system_key", None))
    ck("  on the SAME run function as the service reply",
       lead is not None and desk is not None and lead.run is desk.run,
       "two drafting paths would drift; this is one act under two envelopes")
    ck("  accepting the same parameters",
       lead is not None and desk is not None and set(lead.params) == set(desk.params))

    ck("the catalogue names the skill",
       systems.CATALOG["lead_responder"]["workflow"].get("skill") == "lead_reply")
    row = next(r for r in systems.effectiveness() if r["system"] == "lead_responder")
    # Measured by the edit TREND since the learning axis landed (2026-09-03):
    # the share of edited sends was the old measure, the median change per
    # window is the one that can fall.
    ck("the effectiveness map measures it by the edit trend, and it learns",
       row["measure_fn"] == "edits.trend" and row["measure_ok"]
       and row["learns_into"] == "systems.guidance_block" and row["learns_ok"],
       str({k: row[k] for k in ("measure_fn", "learns_into")}))

    doc = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "SYSTEMS-REFERENCE.md")).read()
    ck("the reference shows lead_responder with a skill",
       "`lead_reply`" in doc, "regenerate with gen_systems_reference.py --write")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
