"""A reorder prompt is a campaign email whose segment is not a choice.

`reorder_engine` was declared with no generator. The pieces existed —
`segments.reorder_due`, the ESP segment condition, the whole campaign run —
so `reorder_prompt` delegates to `_run_campaign_email` with the segment
forced. What had to change for that to be honest is one literal: the campaign
run wrote `system_key="campaign_email"` on its artifact, so a delegating skill
would have filed under the wrong system's ledger.

The fixture is `test_campaign_email`'s own, loaded by path — one seed, one
fake ESP, so the two suites cannot drift on what "a live campaign account" is.

Run: python3 scripts/test_reorder_skill.py
"""
import importlib.util
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ro.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

_spec = importlib.util.spec_from_file_location("tce", os.path.join(_HERE, "test_campaign_email.py"))
tce = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tce)          # seeds nothing yet; defines the fixtures

from app import db, planner, skill, systems, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _artifact_system(run_id: str) -> str:
    with db.SessionLocal() as s:
        row = (s.query(db.ArtifactBody)
               .filter(db.ArtifactBody.run_id == run_id).first())
        return row.system_key if row else ""


def main() -> int:
    db.init_db()
    tenants.seed()
    tce._seed_live("baci")
    tce._fake_esp()
    row = systems.find("baci", "reorder_engine") or systems.create("baci", "reorder_engine")
    with db.SessionLocal() as s:
        r = s.get(db.System, row.id)
        r.status = "live"
        s.commit()

    sk = skill.get("reorder_prompt")
    ck("reorder_prompt is registered on reorder_engine",
       sk is not None and sk.system_key == "reorder_engine")

    # ---- the segment is not a choice --------------------------------------
    got = skill.run("reorder_prompt", "baci", segment="vip_high_aov")
    run_id = got.get("run_id") or ""
    ck("a run completes", got.get("status") in ("produced", "done", "ok")
       or bool(got.get("items")), str({k: got.get(k) for k in ('status', 'blocked_on', 'notes')})[:200])
    with db.SessionLocal() as s:
        run = s.get(db.SystemRun, run_id) if run_id else None
        art = (s.query(db.ArtifactBody)
               .filter(db.ArtifactBody.run_id == run_id).first())
        push_seg = ((art.push or {}).get("segment_key") if art else None)
    items = got.get("items") or []
    meta_seg = (items[0].get("meta") or {}).get("segment") if items else None
    # Read where the executor reads: `push_campaign_to_esp` binds the ESP
    # audience from the artifact's push recipe, and the item's meta is what
    # the campaign suite itself asserts on. Not the approval payload — it
    # was checked there first and found nothing, for the wrong reason.
    ck("the send is bound to the reorder segment, not the one that was asked for",
       push_seg == "reorder_due" and meta_seg == "reorder_due",
       f"push.segment_key={push_seg!r} meta.segment={meta_seg!r} — "
       f"vip_high_aov was passed")

    # ---- it files under its own system ----------------------------------
    ck("the artifact is filed under reorder_engine",
       _artifact_system(run_id) == "reorder_engine", _artifact_system(run_id) or "(none)")
    ck("  and the run is too",
       run is not None and run.system_id == row.id,
       f"run.system_id={getattr(run, 'system_id', None)!r} vs reorder_engine {row.id!r}")
    # THE PAIR: the campaign skill itself still files under campaign_email —
    # the literal was replaced by the skill's own system, not by "reorder".
    crow = systems.find("baci", "campaign_email") or systems.create("baci", "campaign_email")
    with db.SessionLocal() as s:
        c = s.get(db.System, crow.id)
        c.status = "live"
        s.commit()
    got_c = skill.run("campaign_email", "baci", segment="reorder_due")
    ck("a campaign run still files under campaign_email",
       _artifact_system(got_c.get("run_id") or "") == "campaign_email",
       _artifact_system(got_c.get("run_id") or "") or "(none)")

    # ---- the planner files one a month, and only one --------------------
    def _count():
        with db.SessionLocal() as s:
            return (s.query(db.SystemRun)
                    .filter(db.SystemRun.system_id == row.id,
                            db.SystemRun.trigger == "planner").count())

    p1 = planner.reorder_rollout(systems.find("baci", "reorder_engine"))
    n1 = _count()
    p2 = planner.reorder_rollout(systems.find("baci", "reorder_engine"))
    ck("the planner proposes reorder prompts", p1.get("proposed", 0) >= 1 and n1 >= 1, str(p1))
    # One a month means a full month is skipped, not refreshed — the campaign
    # planner re-touches a ref within a month because it walks by spacing;
    # this one walks by month. "Does not double" is proposed == 0 AND the
    # count unchanged, which is what is held.
    ck("  and a second pass files nothing more",
       p2.get("proposed", 0) == 0 and _count() == n1,
       f"{p2} — {_count()} plan(s) after, {n1} before")
    with db.SessionLocal() as s:
        plans = (s.query(db.SystemRun)
                 .filter(db.SystemRun.system_id == row.id,
                         db.SystemRun.trigger == "planner").all())
        briefs = [dict(getattr(r, "brief", None) or {}) for r in plans]
    # THE PAIR of "the segment is not a choice": the plan carries no segment
    # field at all — `open_plan` refuses one the system does not declare —
    # and the run above forced reorder_due regardless of what was passed.
    ck("  a filed plan carries no segment field — the run supplies it",
       plans and all("segment" not in b for b in briefs),
       str([sorted(b) for b in briefs][:2]))

    # ---- the map and the register ----------------------------------------
    eff = next(r for r in systems.effectiveness() if r["system"] == "reorder_engine")
    ck("the effectiveness map measures it by provider stats",
       eff["measure_fn"] == "performance.sync" and eff["measure_ok"])
    ck("the catalogue's ship resolves to the campaign executor",
       systems._resolves("approvals.apply_decision".replace(".apply_decision", ".apply_decision"))
       and systems.CATALOG["reorder_engine"]["workflow"]["ship_by"].endswith("push_campaign_to_esp"))

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
