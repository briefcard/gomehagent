"""Pre-send edits become standing guidance — through the owner, never around.

For weeks `edits.record` wrote what the owner changed before every send and no
drafter read one. This is the loop that closes it, held to the shape that
converges: a move must recur across MIN_RECURRENCE distinct sends (code, not
a model, decides that), the model writes one sentence from the evidence, the
sentence is an approval, and approving is what puts it where the drafter
reads. Then `effect` says whether the delta fell.

Run: python3 scripts/test_learning.py
"""
import datetime as dt
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ln.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import approvals, db, edits, kb, learning, llm, systems, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


EXCL = ("-Thanks so much for reaching out!!\n+Thanks for reaching out.\n"
        "-We'd love to help!\n+We can help with that.")
NUMS = "-It ships soon.\n+It ships in 3 to 5 days."
SHORT = "-Line one\n-Line two\n-Line three\n+One line"


def _run(row, sample: str, when=None):
    run = systems.start_run(row.id, "service_desk", trigger="inbound_email", ref="t")
    rid = run if isinstance(run, str) else run.id
    with db.SessionLocal() as s:
        r = s.get(db.SystemRun, rid)
        r.decision, r.edit_diff = "approved", sample
        if when:
            r.created_at = when
        s.commit()
    return rid


def _approval(row, similarity: float, when):
    ap_id = approvals.request_approval("send_email", "reply", {"to": "x@y", "similarity": similarity,
                                                                 "as_is": similarity >= 0.995},
                                       notify=False, system_id=row.id)
    with db.SessionLocal() as s:
        a = s.get(db.Approval, ap_id)
        a.status, a.decided_at = "approved", when
        s.commit()


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci Milano")
    row = systems.find("baci", "service_desk") or systems.create("baci", "service_desk")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()

    # ---- moves are decided by code ------------------------------------------
    ck("an exclamation removed is classified as such", "exclamation_removed" in learning.moves(EXCL))
    ck("numbers added are 'specifics added'", "specifics_added" in learning.moves(NUMS))
    ck("three lines to one is 'shortened'", "shortened" in learning.moves(SHORT))
    ck("nothing changed is no move", learning.moves("") == set())

    # ---- recurrence is the gate ---------------------------------------------
    for _ in range(4):
        _run(row, EXCL)
    _run(row, NUMS)                       # once — a customer, not a habit
    asked = {"n": 0}
    real_ask = llm.ask
    llm.ask = lambda purpose, prompt, **k: (asked.__setitem__("n", asked["n"] + 1) or
                                            llm.Reply(text="Never use exclamation marks in a reply.", ok=True))
    try:
        got = learning.propose_for("baci")
    finally:
        pass
    with db.SessionLocal() as s:
        pend = (s.query(db.Approval)
                .filter(db.Approval.kind == "guidance_rule",
                        db.Approval.status == "pending").all())
        payloads = [dict(a.payload or {}) for a in pend]
        ap_id = pend[0].id if pend else ""
    ck("a move that recurs across four sends is proposed once",
       got["proposed"] == 1 and len(pend) == 1, str(got))
    ck("  as the recurring move, with its evidence and count",
       payloads and payloads[0]["move"] == "exclamation_removed"
       and payloads[0]["n"] == 4 and len(payloads[0]["evidence"]) >= 3,
       str({k: payloads[0].get(k) for k in ("move", "n")} if payloads else {}))
    ck("  and the move seen once is NOT proposed — the pair",
       not any(p["move"] == "specifics_added" for p in payloads),
       "one edit about one customer is not a habit")
    ck("  the model was asked once, for the sentence only", asked["n"] == 1, str(asked))

    # ---- approving is what the drafter reads --------------------------------
    before = systems.guidance_block("baci", "service_desk")
    ck("before approval the drafter does not see the rule",
       "exclamation marks" not in before.lower())
    said = approvals.apply_decision(ap_id, "approved")
    after = systems.guidance_block("baci", "service_desk")
    ck("approving writes it into the guidance the drafter reads",
       "exclamation marks" in after.lower(), after[:160])
    ck("  and says so", "standing guidance" in said.lower(), said[:100])

    # ---- no re-proposal of a standing rule ----------------------------------
    got2 = learning.propose_for("baci")
    ck("a standing rule is not proposed again",
       got2["proposed"] == 0 and "already" in str(got2["systems"].get("service_desk", "")),
       str(got2))
    llm.ask = real_ask

    # ---- the measure --------------------------------------------------------
    now = db.utcnow()
    for sim, when in ((0.6, now - dt.timedelta(days=10)), (0.7, now - dt.timedelta(days=9)),
                      (0.9, now - dt.timedelta(days=1)), (1.0, now - dt.timedelta(hours=1))):
        _approval(row, sim, when)
    tr = edits.trend("baci", "service_desk", windows=(7, 30))
    w7, w30 = tr["windows"]["7"], tr["windows"]["30"]
    ck("the 7-day window reads the two recent sends",
       w7["n"] == 2 and w7["median_change"] == 0.05 and w7["as_is_rate"] == 0.5, str(w7))
    ck("the 30-day window reads all four — and is worse, as it should be",
       w30["n"] == 4 and w30["median_change"] == 0.2, str(w30))

    # ---- the effect of a rule -----------------------------------------------
    eff = learning.effect("baci", "service_desk", days=14)
    ck("the accepted rule reports its before and after",
       eff and eff[0]["rule"].startswith("Never use exclamation") and eff[0]["n_before"] + eff[0]["n_after"] >= 1,
       str(eff)[:200])

    # ---- retirement: a rule that changed nothing is archived ---------------
    # The accepted rule was noted "now". Give it three sends before and three
    # after; first the after-side is BETTER (kept), then worse sends arrive
    # and the same judge retires it. One rule, two verdicts — the pair.
    with db.SessionLocal() as s:
        note_at = max(n.created_at for n in systems.notes("baci", "service_desk")
                      if "[learned from" in (n.content or ""))
    note_at = db.as_utc(note_at)
    for sim, d in ((0.6, 3), (0.7, 2), (0.65, 1)):
        _approval(row, sim, note_at - dt.timedelta(days=d))
    for sim, h in ((0.95, 1), (0.96, 2), (0.97, 3)):
        _approval(row, sim, note_at + dt.timedelta(hours=h))
    kept = learning.retire_for("baci")
    ck("a rule after which the delta fell is kept",
       kept["kept"] == 1 and kept["retired"] == 0
       and "exclamation marks" in systems.guidance_block("baci", "service_desk").lower(),
       str(kept["rules"]))
    for sim, h in ((0.4, 4), (0.45, 5), (0.5, 6), (0.42, 7)):
        _approval(row, sim, note_at + dt.timedelta(hours=h))
    gone = learning.retire_for("baci")
    ck("the same rule, once the delta rose after it, is retired",
       gone["retired"] == 1 and gone["kept"] == 0
       and "exclamation marks" not in systems.guidance_block("baci", "service_desk").lower(),
       str(gone["rules"]))
    ck("  and it says which and why",
       gone["rules"] and "did not fall" in gone["rules"][0]["verdict"], str(gone["rules"])[:120])

    # ---- a retired move is not re-proposed from the same edits --------------
    llm.ask = lambda purpose, prompt, **k: llm.Reply(text="Never use exclamation marks in a reply.", ok=True)
    again = learning.propose_for("baci")
    llm.ask = real_ask
    ck("the retired move is inside its cooldown and is not proposed again",
       again["proposed"] == 0, str(again))

    # ---- wired weekly, sharded -----------------------------------------------
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "worker.py")).read()
    ck("the sweep is registered weekly and sharded per account",
       bool(re.search(r'_safe\(learning_sharded, "learning sweep", sharded=True\)', src))
       and 'day_of_week="sun"' in src)
    ck("  and it judges what stands before proposing what recurs",
       "learning.sweep_for" in src, "retire, then propose")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
