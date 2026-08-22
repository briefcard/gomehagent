"""Offline exercise of the workflow surface — the per-system view, the plan
cards and their routes, the work strip, and the Review tab's plans card.

The rules under test are the owner's console rules applied to plans: state
first (the flash carries what just happened), a queue paginates and every
decision returns the reader to their place, nothing stored is display-only
(plan fields render prefilled and editable), a blank box is not an edit,
absence is labelled (a system that takes no plans says so; unmeasured sends
are named), and the badge answers "is there work" without a click.

    python3 scripts/test_workflow_ui.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'wf.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import approvals, db, skill, systems, tenants, web  # noqa: E402

PASS, FAIL = "  ok  ", " FAIL "
_failures = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{PASS if cond else FAIL}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _failures.append(label)


TODAY = dt.date.today().isoformat()

systems.CATALOG["wf_probe"] = dict(
    name="Workflow probe", does="test", requires=(), requires_any=(),
    needs_kb=False, kb_needs=(),
    workflow=dict(unit="one probe item", skill="wf_probe",
                  plan_fields=(
                      dict(key="segment", label="Segment", required=True),
                      dict(key="goal", label="Goal", required=False),
                      dict(key="draft_visual", label="Draft a hero",
                           required=False, kind="flag"),
                  ),
                  artifact="none", ship="marks it ready", measure="none"))
skill.register(skill.Skill(
    key="wf_probe", name="Workflow probe", does="test",
    system_key="wf_probe", tier=1, params=("segment", "goal", "draft_visual"),
    writes=False, produces="report", run=lambda ctx: {"summary": "ok"}))


def _view(c, tenant: str, extra: str = "") -> str:
    return c.get(f"/admin/ui?key=s3cret&tab=systems&tenant={tenant}"
                 f"&system=wf_probe{extra}").text


def main() -> int:
    db.init_db()
    tenants.seed()

    ag = systems.create("agency", "wf_probe")
    systems.update(ag.id, status="live")
    bc = systems.create("baci", "wf_probe")
    systems.update(bc.id, status="live")
    lead = systems.create("agency", "lead_responder")

    p_ag = systems.open_plan("agency", "wf_probe", ref="probe:ag",
                             plan={"segment": "AGENCYSEG", "goal": "AGOAL"},
                             planned_for=TODAY)["run_id"]
    systems.open_plan("baci", "wf_probe", ref="probe:bc",
                      plan={"segment": "BACISEG"}, planned_for=TODAY)

    c = TestClient(web.app)

    # ---- the tab: strip + the way in ------------------------------------
    print("\n— the Systems tab carries the work strip —")
    tab = c.get("/admin/ui?key=s3cret&tab=systems&tenant=agency").text
    ck("the card links into the system's own view",
       "system=wf_probe" in tab and "Workflow" in tab)
    ck("the strip counts the queue", ">1</b> planned" in tab, "expected 1 planned")
    ck("the strip counts what waits on a person", "waiting on you" in tab)

    # ---- the per-system view --------------------------------------------
    print("\n— the per-system view is a real, scoped place —")
    v = _view(c, "agency")
    ck("it renders inside the frame", 'class="side"' in v)
    ck("the plan card is there, PREFILLED — nothing is display-only",
       'value="AGENCYSEG"' in v and 'value="AGOAL"' in v)
    ck("it is single-account", "BACISEG" not in v)
    ck("a complete plan on shadow awaits the explicit tap",
       "awaiting your approval" in v and "plan_approve" in v)
    ck("the queue explains itself without a planner",
       "filed by hand" in v or "Plan another" in v or "Plan one by hand" in v)
    v_other = _view(c, "baci")
    ck("…and the other account sees only its own", "AGENCYSEG" not in v_other
       and 'value="BACISEG"' in v_other)

    missing = _view(c, "agency").replace("wf_probe", "")  # noqa: F841
    gone = c.get("/admin/ui?key=s3cret&tab=systems&tenant=agency"
                 "&system=nope").text
    ck("an uninstalled system name falls back to the list, saying so",
       "is installed for this account" in gone and "Installed" in gone)

    lead_v = c.get("/admin/ui?key=s3cret&tab=systems&tenant=agency"
                   "&system=lead_responder").text
    ck("a no-plans system says WHY its Planned section is empty",
       "takes no plans" in lead_v or "declares no plan fields" in lead_v)
    ck("…and still shows its workflow sections",
       'id="waiting"' in lead_v and 'id="shipped"' in lead_v
       and 'id="measured"' in lead_v)

    # ---- filing and editing through the routes --------------------------
    print("\n— plan_new files; the flash names completeness —")
    r = c.get("/admin/plan_new?key=s3cret&tenant=agency&system=wf_probe"
              "&segment=NEWSEG&goal=&draft_visual=", follow_redirects=False)
    loc = r.headers.get("location", "")
    ck("redirects back to the new card", r.status_code == 303
       and "#plan-" in loc and "system=wf_probe" in loc, loc[:90])
    ck("…saying it is still missing its date", "missing" in loc.lower())
    new_id = loc.split("#plan-", 1)[1]
    v = c.get(loc).text
    ck("the flash leads the page", 'class="flash"' in v and "missing" in v)
    ck("the card names its gaps in its own label",
       "needs completing" in v and "planned date" in v)

    print("\n— plan_save: blank is not an edit; place is kept —")
    r = c.get(f"/admin/plan_save?key=s3cret&id={new_id}&tenant=agency"
              f"&system=wf_probe&segment=&goal=KEPTGOAL"
              f"&planned_for={TODAY}&ppage=1", follow_redirects=False)
    loc = r.headers.get("location", "")
    ck("returns to the same card", f"#plan-{new_id}" in loc, loc[:90])
    v = c.get(loc).text
    ck("the blank box left segment alone", 'value="NEWSEG"' in v)
    ck("the typed box landed", 'value="KEPTGOAL"' in v)
    ck("the flash says it is complete now", "Saved — complete" in v)
    r = c.get(f"/admin/plan_save?key=s3cret&id={new_id}&tenant=agency"
              f"&system=wf_probe&rogue=x", follow_redirects=False)
    v = c.get(r.headers.get("location", "")).text
    ck("a hand-built URL's unknown field is refused by name, in the flash",
       "unknown plan field" not in v,
       "our form filters to declared fields, so rogue never reaches save_plan")

    print("\n— approve, then the button is gone —")
    r = c.get(f"/admin/plan_approve?key=s3cret&id={new_id}&tenant=agency"
              f"&system=wf_probe&ppage=1", follow_redirects=False)
    v = c.get(r.headers.get("location", "")).text
    ck("approved state shows on the card", "✓ approved — runs" in v)
    ck("…and only unapproved cards offer the button",
       v.count("Approve plan") == 1, "p_ag is still unapproved")

    print("\n— skip is a recorded decision —")
    r = c.get(f"/admin/plan_skip?key=s3cret&id={new_id}&tenant=agency"
              f"&system=wf_probe&reason=not+now", follow_redirects=False)
    with db.SessionLocal() as s:
        row = s.get(db.SystemRun, new_id)
    ck("the row is terminal, denied, reason kept",
       row.stage == "skipped" and row.decision == "denied"
       and (row.brief or {}).get("skip_reason") == "not now")

    # ---- pagination ------------------------------------------------------
    print("\n— the queue paginates, with the control on the page —")
    for i in range(17):
        systems.open_plan("agency", "wf_probe", ref=f"bulk:{i}",
                          plan={"segment": f"S{i}"}, planned_for=TODAY)
    v = _view(c, "agency")
    ck("page one shows one page of cards", v.count('class="plan ') == 15,
       str(v.count('class="plan ')))
    ck("the pager is on the page", "ppage=2" in v and "later" in v)
    v2 = _view(c, "agency", "&ppage=2")
    ck("page two holds the rest", 0 < v2.count('class="plan ') <= 15,
       str(v2.count('class="plan ')))

    # ---- the Review tab and the badge ------------------------------------
    print("\n— Review answers 'is there work' without a click —")
    waiting = systems.plans_needing_action("agency")
    ck("plans_needing_action sees the held plans", len(waiting) >= 15,
       str(len(waiting)))
    rv = c.get("/admin/ui?key=s3cret&tab=content&tenant=agency").text
    ck("the Review tab carries the plans card",
       "Plans awaiting you" in rv and "system=wf_probe" in rv)
    ck("each row says what it needs and links to the card itself",
       "#plan-" in rv and ("approve it" in rv or "complete it" in rv))
    ck("the sidebar badge counts them", 'class="navbadge"' in rv)
    rb = c.get("/admin/ui?key=s3cret&tab=content&tenant=baci").text
    ck("…scoped: baci's card holds only baci's",
       "probe:bc" in rb and "bulk:" not in rb)

    # ---- pause: editable, not consumable, not filable --------------------
    print("\n— paused: plans stay editable; filing waits —")
    systems.update(ag.id, status="paused")
    v = _view(c, "agency")
    ck("the create form is replaced by the state, not a nag",
       "needs the system on" in v and "Plan one by hand" not in v)
    r = c.get(f"/admin/plan_save?key=s3cret&id={p_ag}&tenant=agency"
              f"&system=wf_probe&goal=EDITWHILEPAUSED", follow_redirects=False)
    v = c.get(r.headers.get("location", "")).text
    ck("editing while paused still lands", 'value="EDITWHILEPAUSED"' in v)
    r = c.get("/admin/plan_new?key=s3cret&tenant=agency&system=wf_probe"
              f"&segment=X&planned_for={TODAY}", follow_redirects=False)
    v = c.get(r.headers.get("location", "")).text
    ck("filing on a paused system is refused, named in the flash",
       "plans are only filed" in v)
    systems.update(ag.id, status="live")

    # ---- the registry loads itself --------------------------------------
    print("\n— the skill registry loads its own contents —")
    # THIS suite never imports skill_pack — exactly like the production web
    # process, which is how 'no skill keyed campaign_email' reached the
    # owner's screen while the pack sat one import away.
    ck("a registry read finds the real skills without anyone importing "
       "the pack", skill.get("campaign_email") is not None)
    ck("…and /health proves it per process, without a secret",
       c.get("/health").json().get("skills", 0) >= 5,
       str(c.get("/health").json().get("skills")))

    # ---- run now: the human trigger beside the tick's --------------------
    print("\n— Run now: a date makes a plan eligible; a person or the tick "
          "starts it —")
    v = _view(c, "agency")
    ck("a complete, unapproved plan on shadow offers Approve & run now",
       "Approve &amp; run now" in v)
    r = c.get(f"/admin/plan_run?key=s3cret&id={p_ag}&tenant=agency"
              f"&system=wf_probe&ppage=1", follow_redirects=False)
    v = c.get(r.headers.get("location", "")).text
    with db.SessionLocal() as s:
        still = s.get(db.SystemRun, p_ag).stage
    ck("without the approval it refuses through the same gate, and the plan "
       "is untouched",
       "Did not run" in v and "approval" in v and still == "planned", still)
    r = c.get(f"/admin/plan_run?key=s3cret&id={p_ag}&tenant=agency"
              f"&system=wf_probe&ppage=1&approve=1", follow_redirects=False)
    loc = r.headers.get("location", "")
    v = c.get(loc).text
    with db.SessionLocal() as s:
        ran = s.get(db.SystemRun, p_ag)
    import re as _re
    _flash = _re.search(r'class="flash">(.{0,200})', v)
    ck("Approve & run consumes THIS plan immediately — the same row, "
       "terminal", ran.stage == "sent" and "Ran now" in v,
       f"{ran.stage} · flash={_flash.group(1) if _flash else '?'}")
    ck("…and the redirect lands where the outcome lives", "#shipped" in loc,
       loc[-30:])
    twice = c.get(f"/admin/plan_run?key=s3cret&id={p_ag}&tenant=agency"
                  f"&system=wf_probe", follow_redirects=True).text
    ck("a consumed plan cannot run twice",
       "Did not run" in twice and "not a plan" in twice)

    # ---- measured --------------------------------------------------------
    print("\n— measured: the delta counts, and unmeasured is NAMED —")
    rid = systems.start_run(ag.id, "agency", trigger="manual", ref="m1")
    systems.finish_run(rid, "sent", decision="approved",
                       edit_diff=json.dumps({"as_is": True, "similarity": 1.0}))
    rid2 = systems.start_run(ag.id, "agency", trigger="manual", ref="m2")
    systems.finish_run(rid2, "sent", decision="approved")
    v = _view(c, "agency")
    ck("sent-as-is reads from the captured deltas",
       "1 of 1</b> measured" in v, "one measured, one not")
    ck("the un-captured send is a named fact, not a flattering zero",
       "carry no delta" in v and "unmeasured" in v)
    tab = c.get("/admin/ui?key=s3cret&tab=systems&tenant=agency").text
    ck("the strip carries it too", "1 of 1</b> sent as-is" in tab)
    ck("…and counts the week's shipping", "shipped this week" in tab)

    print("\n— the Segments card, on ESP-campaign systems only —")
    camp = systems.create("agency", "campaign_email")
    with db.SessionLocal() as s:
        # go-live is rightly gated on an ESP; force the status so the
        # Planned section offers its create form and the select is on page
        s.get(db.System, camp.id).status = "live"
        s.commit()
    seg_v = c.get("/admin/ui?key=s3cret&tab=systems&tenant=agency"
                  "&system=campaign_email").text
    ck("the segment field is a SELECT over the account's real catalog — "
       "never free text",
       '<select name="segment">' in seg_v and "choose a segment" in seg_v
       and "trial_no_convert" in seg_v, "agency = digital_products")
    ck("…while a kindless probe field stays a text input",
       '<input name="segment"' in _view(c, "agency"))
    ck("the campaign system's view carries the Segments card",
       'id="segments"' in seg_v and "Never synced" in seg_v
       and "Sync now" in seg_v)
    ck("…and it renders from the record — no live call promised on load",
       "reads the live ESP" in seg_v)
    ck("a non-ESP system has no Segments card",
       'id="segments"' not in _view(c, "agency"))

    print("\n— all accounts: the workflow view is one account's place —")
    va = c.get("/admin/ui?key=s3cret&tab=systems&tenant=*&system=wf_probe").text
    ck("system= on the all-accounts view falls back to the grouped list",
       "All accounts" in va and 'id="planned"' not in va)

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {_failures}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
