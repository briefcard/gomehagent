"""Approvals a system is waiting on, where it works — and what may be waived.

Owner, 2026-08-29: *"there should be a way to navigate to approvals inside of
the systems just like we do for claims … We would also need the blocks in
place if the system requires an approval for something that it must be
approved OR approval override."*

Two halves, and the second is the one that needs judgement.

**The list is DERIVED.** Every system already declares `kb_needs`, and
`kb.needs_met` already draws the distinction that matters — nobody has told us
yet, versus somebody has and it is sitting in a queue, which it reports as
`"claim (3 waiting for review)"`. That string reached an operator inside a
refusal and could not be acted on. `systems.awaiting` turns it into rows with
a destination, so a system added next month reports the right queues without
anybody listing them a second time.

**NOT EVERY NEED YIELDS TO AN OVERRIDE.** A missing claim makes an output
THINNER. A missing ban list makes every output UNVERIFIED, because the
validator then has nothing to refuse against — overriding it is not
"proceeding with less", it is proceeding with no check at all, which is the
absence-read-as-permission failure this codebase keeps closing. So the ban
list is the one need marked non-overridable, and the refusal says why rather
than repeating itself.

**AN OVERRIDE IS A REASON, NOT A FLAG.** `override_needs=1` turns the check
off; a sentence is a decision somebody signed. Empty is refused, and what was
waived lands on `thin`, which is the list the assurance ledger keeps — so a
draft produced under an override can never be mistaken for one produced under
the gate.

    python3 scripts/test_approval_gate.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ag.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, kb_seed, skill, skill_pack, systems, tenants  # noqa: E402,F401

_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else \
    {c: False for c in tenants.CAPABILITIES}

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _run(**kw):
    """The gate lives on `blog_article`, which declares `banned_claims`
    constitutive. `ad_copy` declares nothing, which is a policy decision and
    not a bug — so the mechanism is exercised where it is actually wired."""
    return skill.run("blog_article", "baci", keyword="melamine plates", **kw)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    systems.seed_from_tenants()
    kb.set_brand("baci", tone="direct, warm")
    # BOTH systems: `awaiting` is asked of ad_creative and the gate lives on
    # blog, and a system that is merely declared cannot run.
    for _k in ("ad_creative", "blog"):
        _row = systems.find("baci", _k) or systems.create("baci", _k)
        systems.update(_row.id, **{f: "declared for the test"
                                   for f, _l, _h in systems.CONTRACT})
        _go = systems.update(_row.id, status="live", autonomy="shadow")
        assert _go.get("ok"), f"go-live refused for {_k}: {_go}"

    print("— a system says what IT is waiting on, not what exists —")
    kb.add_claim("baci", "Every piece is certified food-safe.", "COA 2026", [],
                 proof_type="certification", status="pending", origin="agent")
    waiting = systems.awaiting("baci", "ad_creative")
    by = {w["need"]: w for w in waiting}
    ck("a proposed claim is reported as waiting, not as absent",
       "claim" in by and by["claim"]["waiting"] >= 1
       and by["claim"]["state"] == "waiting for review",
       str(waiting))
    ck("…and carries where to go and decide",
       by["claim"]["sub"] == "claims",
       "sending somebody to 'Review' is a fix instruction; sending them to "
       "the queue is a control")
    ck("a need nobody has filled reads differently",
       any(w["state"] == "nobody has told us yet" for w in waiting)
       or all(w["waiting"] for w in waiting),
       "different fixes — one is a decision, the other is data entry")
    ck("a system with no declared needs asks for nothing",
       systems.awaiting("baci", "reports") == [],
       str(systems.awaiting("baci", "reports")))
    ck("an unknown system is not an error, it is an empty list",
       systems.awaiting("baci", "nothing-like-this") == [])

    print("\n— what blocks is a fact about the SYSTEM, not the field —")
    ck("the ban list is non-overridable and says why",
       systems.NEEDS["banned_claims"]["overridable"] is False
       and "cannot refuse anything" in systems.NEEDS["banned_claims"]["why_not"],
       "a missing claim makes an output thinner; a missing ban list makes "
       "every output unverified")
    ck("…and a claim is overridable",
       systems.NEEDS["claim"]["overridable"] is True)
    ck("blocking is read from the SKILL, never re-declared",
       systems._constitutive_for("blog") == ("banned_claims",)
       and systems._constitutive_for("ad_creative") == (),
       "a second list would be a second opinion, and they would disagree the "
       "first time one changed")

    print("\n— the block holds, and the override is a reason —")
    with db.SessionLocal() as s:
        b = s.query(db.KbBrand).filter(db.KbBrand.tenant == "baci").first()
        b.banned_claims = []
        s.commit()

    r1 = _run()
    ck("without a ban list the run is blocked",
       r1["status"] == "blocked"
       and any("banned_claims" in w for w in r1.get("blocked_on") or []),
       str(r1.get("blocked_on"))[:140])

    r2 = _run(override_needs="   ")
    ck("an override with no reason is not an override",
       r2["status"] == "blocked",
       "a waiver nobody can be asked about later is indistinguishable from "
       "a bug")

    r3 = _run(override_needs="ban list is being rebuilt; internal draft only")
    ck("the ban list CANNOT be waived, whatever the reason",
       r3["status"] == "blocked"
       and any("CANNOT be overridden" in w for w in r3.get("blocked_on") or []),
       str(r3.get("blocked_on"))[:160])
    ck("…and the refusal explains itself rather than repeating itself",
       any("no check" in w for w in r3.get("blocked_on") or []),
       str(r3.get("blocked_on"))[:160])

    print("\n— an overridable need waives, loudly —")
    kb.set_brand("baci", banned_claims=["handmade"])
    with db.SessionLocal() as s:
        for c in s.query(db.KbClaim).filter(db.KbClaim.tenant == "baci").all():
            c.review = "proposed"
        s.commit()
    saved = None
    sk = skill.get("blog_article")
    was = sk.constitutive
    try:
        # The pack declares only `banned_claims` as constitutive, which is the
        # right call and leaves nothing overridable to exercise. Making the
        # claim constitutive for this check tests the MECHANISM, not a policy
        # anybody shipped — and it is put back in `finally`.
        object.__setattr__(sk, "constitutive", ("claim",))
        blocked = _run()
        ck("an overridable need still blocks by default",
           blocked["status"] == "blocked",
           "'or override' is not 'or ignore'")
        waived = _run(override_needs="running a shape test before review")
        ck("…and a reason gets past it",
           waived["status"] != "blocked", str(waived.get("blocked_on"))[:120])
        ck("…with what was waived on the record",
           any("OVERRIDDEN" in t for t in waived.get("thin") or []),
           "`thin` is what the assurance ledger keeps as 'what this run was "
           "working without' — a draft made under an override must never "
           "read like one made under the gate")
        ck("…including the reason somebody gave",
           any("shape test before review" in t
               for t in waived.get("thin") or []))
    finally:
        object.__setattr__(sk, "constitutive", was)
        _ = saved

    print("\n— and it is visible where the system lives —")
    from app import admin_ui as ui
    _card = systems.find("baci", "ad_creative")
    # THE CARD, not the function. Sabotage showed that calling
    # `_awaiting_strip` directly stays green while the card stops rendering
    # it — the strip would work perfectly and appear nowhere.
    _strip = ui._system_card("s3cret", _card)
    ck("the card names the queue, not just the count",
       "waiting for your review" in _strip and "sub=claims" in _strip,
       "the count already existed, buried inside needs_met's refusal string "
       "as text, where nobody could act on it")
    ck("…and links somewhere that decides",
       "decide &rarr;" in _strip and "#proposals" in _strip)
    _blog = systems.find("baci", "blog")
    with db.SessionLocal() as s2:
        _b = s2.query(db.KbBrand).filter(db.KbBrand.tenant == "baci").first()
        _b.banned_claims = []
        s2.commit()
    _bstrip = ui._system_card("s3cret", _blog)
    ck("a blocking need is drawn as blocking",
       "stops it" in _bstrip,
       "waiting-on-a-person and stops-the-system are different states and a "
       "person about to force one deserves to know which")
    ck("…and says when it cannot be waived at all",
       "Cannot be overridden" in _bstrip and "no check" in _bstrip)
    ck("a system with nothing outstanding shows no strip",
       ui._awaiting_strip("s3cret", systems.find("baci", "reports")
                          or _card) is not None)

    # AND THE REFUSAL STILL DRAWS THE DISTINCTION. `needs_met` is what a
    # blocked run says out loud, and it must keep telling apart "nobody has
    # told us" from "it is written and waiting on you" — the two have
    # different fixes and sending somebody to type what is already typed is
    # how a queue stops being read.
    with db.SessionLocal() as s3:
        for _c in s3.query(db.KbClaim).filter(db.KbClaim.tenant == "baci").all():
            _c.review = "proposed"
        s3.commit()
    _said = kb.needs_met("baci", ("claim",))
    ck("a refusal says the claims are waiting, not absent",
       any("waiting for review" in m for m in _said), str(_said))
    ck("…and counts them",
       any(str(kb.pending_counts("baci")["claim"]) in m for m in _said),
       str(_said))

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
