"""The Measured section has a producer for campaigns. It never had one.

`SystemRun.edit_diff` is the number Measured is built from — "the share of
sends nobody had to touch". `edits.record` has exactly two call sites and both
are Gmail, so a campaign approval (kind="skill_output") reached neither and the
section was structurally empty for this system since it was written.

The declared measure was "generated HTML vs the ESP draft at launch", which
cannot be taken: `omnisend.campaign()` returns status, name, sent_at and
segment ids and no content. What CAN be seen is what the owner changed in the
workroom before approving — the same question asked where the answer is.

Run: python3 scripts/test_campaign_measured.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cm.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (brand_theme, db, esp, kb, skill,  # noqa: E402
                 skill_pack, systems, tenants)

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda k: dict(_ALL) if tenants.get(k) else \
    {c: False for c in tenants.CAPABILITIES}


def _seed():
    db.init_db()
    tenants.seed()
    t = "baci"
    kb.ensure_brand(t, "Baci")
    kb.set_brand(t, positioning="Italian-designed tableware.", tone="warm")
    kb.add_banned(t, "made in Italy")
    row = systems.find(t, "campaign_email") or systems.create(t, "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    brand_theme.approve(t, {"footer.address": "2875 NE 191st St, Aventura, FL"})
    esp.provider_for = lambda x: "omnisend"
    esp.personalize = lambda x, h: {"ok": True, "html": h}

    class _M:
        @staticmethod
        def draft_from_html(tenant, *, name, subject, sender_name, html,
                            preheader="", include_segments=None):
            return {"ok": True, "campaign_id": "c1"}
    esp.backend = lambda x: (_M, "")
    skill_pack.draft_campaign = lambda b, seg, goal, craft=None: (
        {"subject": "S", "preheader": "p", "claim_ids": [],
         "body_html": "<p>the original wording</p>",
         "cta_label": "Shop", "cta_url": "https://x/s"}, "model", "")
    return t


def _draft(t):
    r = skill.run("campaign_email", t, segment="reorder_due")
    oid = (r.get("items") or [{}])[0]["output_id"]
    with db.SessionLocal() as s:
        art = (s.query(db.ArtifactBody)
               .filter(db.ArtifactBody.output_id == oid).first())
        run_id = art.run_id
    return oid, run_id


def _diff(run_id):
    with db.SessionLocal() as s:
        run = s.get(db.SystemRun, run_id)
        return (run.edit_diff or ""), (run.decision or "")


def main() -> int:
    t = _seed()

    print("— the declared measure is one that can actually be taken —")
    m = systems.CATALOG["campaign_email"]["workflow"]["measure"]
    ck("it no longer promises an ESP comparison nothing can make",
       "ESP draft at launch" not in m, m)
    ck("  and names what is compared", "approved" in m, m)

    print("\n— an edited draft records what the person changed —")
    oid, run_id = _draft(t)
    ck("nothing is measured before it ships", not _diff(run_id)[0])
    with db.SessionLocal() as s:
        art = (s.query(db.ArtifactBody)
               .filter(db.ArtifactBody.output_id == oid).first())
        art.body = (art.body or "").replace("the original wording",
                                            "the owner's own wording")
        s.commit()
    ck("the push succeeds", skill_pack.push_campaign_to_esp(t, oid).get("ok"))
    diff, decision = _diff(run_id)
    ck("the delta is on the RUN, which is what Measured reads", bool(diff),
       "edits.record has two call sites and both are Gmail")
    ck("  and it is recorded as edited, not as sent as-is",
       decision == "edited", decision)
    ck("  with a READABLE sample of what changed",
       ("owner's own wording" in diff or "original wording" in diff)
       and "DOCTYPE" not in diff,
       diff[:90])

    print("\n— an untouched draft is measured as sent as-is —")
    oid2, run2 = _draft(t)
    skill_pack.push_campaign_to_esp(t, oid2)
    d2, dec2 = _diff(run2)
    ck("it is measured", bool(d2), "unmeasured and as-is are different facts")
    ck("  as approved, not edited", dec2 == "approved", dec2)

    print("\n— measured WITHOUT an approval behind it —")
    # The shadow and auto rungs queue nothing. Requiring an approval to
    # measure would leave the systems trusted most as the ones nobody checks.
    with db.SessionLocal() as s:
        n = s.query(db.Approval).count()
    ck("no approval was ever queued on this rung", n == 0, str(n))
    ck("  and the delta was still recorded", bool(_diff(run_id)[0]))

    print("\n— and the section renders the number —")
    from app import admin_ui
    row = systems.find(t, "campaign_email")
    html = admin_ui._measured_section(row)
    ck("Measured shows a measured send, not an empty promise",
       "measured send" in html and "no delta has been measured" not in html,
       html[:130])

    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED:\n  - " + "\n  - ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
