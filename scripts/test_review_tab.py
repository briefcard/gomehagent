"""Review restructured: the primary control decides in place, at any depth.

Spec §4's opening finding: "the most dangerous queue is the least built" —
May-it-ship capped at 25 rows with no pager, its decisions exiting the
console to an unstyled page with no way back, and five of seven queues
unable to show their own depth. This suite pins the rebuild:

  1. SHIP DECIDES IN CONSOLE — POST /admin/ship_decide runs the SAME
     executor as the signed links and flashes ITS OWN sentence back; the
     approve button states its consequence per kind; the row previews the
     thing itself (the kept artifact, not a stripped summary).
  2. EVERY QUEUE PAGES — ship 15, pictures past 60, everything-else 15,
     conflicts 15, plans 15 — honest "X–Y of N" everywhere.
  3. SOURCES LEAD — the three feeders with last-ran state and their
     actions at the top; a failure renders loud; the empty picture queue
     still renders, with the action that fills it.
  4. THE PROSE DEDUPES — the per-card explainers read once, in a legend
     fold; bulk results render as the flash, not muted grey.
  5. STORE SYNC is named what it is, and parks its button when no store
     is connected instead of offering one that can only fail.

Run: python3 scripts/test_review_tab.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rt.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui, approvals, db, kb, systems, tenants, web  # noqa: E402

KEY = "s3cret"
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


c = TestClient(web.app, base_url="https://testserver")


def page(sub="", extra=""):
    return c.get(f"/admin/ui?key={KEY}&tab=content&tenant=baci"
                 + (f"&sub={sub}" if sub else "") + extra).text


def main():
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")

    print("\n--- 1 · ship decides in console, previewing the thing ---")
    for i in range(18):
        approvals.request_approval(
            "skill_output", f"Ad copy for baci: variant {i}",
            {"tenant": "baci", "skill": "ad_copy", "output_id": f"o-{i}",
             "body": f"Ad line {i}."}, notify=False)
    approvals.request_approval(
        "seo_new_article", "[baci] New article: All about jugs",
        {"tenant": "baci", "output_id": "art-1",
         "fields": {"body_html": "<h1>All about jugs</h1>"}}, notify=False)
    approvals.request_approval(
        "skill_output", "Campaign email for baci: Restock",
        {"tenant": "baci", "skill": "campaign_email", "output_id": "camp-1",
         "body": "restock copy",
         "esp_push": {"provider": "omnisend", "subject": "Back in stock"}},
        notify=False)
    with db.SessionLocal() as s:
        s.add(db.ArtifactBody(tenant="baci", output_id="camp-1",
                              system_key="campaign_email",
                              format="campaign_email",
                              body="<h1>Restock hero</h1>",
                              draft_body="<h1>d</h1>", bytes=20))
        s.commit()

    h = page("ship")
    ck("the queue pages at 15 and says its depth",
       h.count('value="approved"') == 15 and "of 20" in h,
       f"approve buttons: {h.count(chr(34) + 'approved' + chr(34))}")
    ck("decisions POST back into the console",
       'action="/admin/ship_decide"' in h and "/decide/" not in h)
    h2 = page("ship", "&page=2")
    ck("page 2 holds the rest", h2.count('value="approved"') == 5)
    ck("the approve button states its consequence per kind",
       "Approve — pushes the draft to omnisend" in (h + h2)
       and "Approve &amp; publish" in (h + h2)
       and "Approve — marks it reviewed, ready" in h)
    ck("an artifact-backed row previews the thing itself",
       "srcdoc=" in (h + h2) and "Restock hero" in (h + h2))

    ap_id = None
    with db.SessionLocal() as s:
        ap_id = (s.query(db.Approval)
                 .filter(db.Approval.summary.like("%variant 0%")).first().id)
    r = c.post("/admin/ship_decide",
               data={"key": KEY, "tenant": "baci", "approval_id": ap_id,
                     "verdict": "approved", "page": "1"},
               follow_redirects=False)
    loc = r.headers.get("location", "")
    ck("deciding lands back on the ship queue with the executor's sentence",
       r.status_code == 303 and "sub=ship" in loc and "ok=" in loc
       and "Approved" in loc, loc[:120])
    with db.SessionLocal() as s:
        st = s.get(db.Approval, ap_id).status
    ck("…and the decision is REAL — the same executor as the signed links",
       st in ("approved", "executed"), st)

    print("\n--- 2 · sources lead the page, and say when they ran ---")
    with db.SessionLocal() as s:
        s.add(db.Setting(key="bg:harvest:baci", value=json.dumps(
            {"state": "finished", "at": "2026-08-27T09:00",
             "detail": "12 proposals filed"})))
        s.add(db.Setting(key="bg:email:baci", value=json.dumps(
            {"state": "failed", "at": "2026-08-27T10:00",
             "detail": "RefreshError: token revoked"})))
        s.commit()
    h = page("ship")
    ck("the Sources block names the feeders with their state",
       "Sources — what fills these queues" in h
       and "ran 2026-08-27 09:00" in h)
    ck("…and a failure renders loud, not folded",
       "Mine sent mail failed" in h or "Sent mail failed" in h)

    print("\n--- 3 · pictures: empty state renders, and #61 is reachable ---")
    h = page("pictures")
    ck("the empty queue still renders, action attached",
       "Nothing waiting — the crawler files what it finds here" in h
       and "Run harvest" in h)
    from app import provenance as prov
    with db.SessionLocal() as s:
        for i in range(65):
            s.add(db.KbAsset(tenant="baci", kind="image", title=f"pic {i}",
                             url=f"https://x.com/{i}.jpg",
                             review=prov.PROPOSED))
        s.commit()
    h = page("pictures")
    ck("the picture queue pages past 60",
       "pictures 1&ndash;60 of 65" in h)
    h2 = page("pictures", "&page=2")
    # 5 tiles + 1: the select-all script's querySelector carries the same
    # literal string.
    ck("…and page 2 reaches #61", h2.count('name="asset_ids"') == 6,
       str(h2.count('name="asset_ids"')))
    ck("the add-form folds, with the entity picker as a select",
       "Add a photograph by URL" in h and '<select name="entity_key">' in h)

    print("\n--- 4 · everything else pages, one datalist, legend once ---")
    for i in range(20):
        kb.add_objection("baci", f"Question {i}?", f"Answer {i}.",
                         origin="crawl", review=prov.PROPOSED)
    h = page("other")
    ck("the queue pages at 15", "proposals 1&ndash;15 of 20" in h)
    ck("…every card carrying the entity picker as a select fed from the "
       "table — no datalist, no typed slug",
       h.count('<select name="entity_key">') >= 15 and "<datalist" not in h,
       str(h.count('<select name="entity_key">')))
    ck("…and kind chips narrow it",
       ">objections</a>" in h
       and page("other", "&flt=objection").count("proposal_review") >= 1)
    for i in range(3):
        kb.add_claim("baci", f"Claim {i} strength.", f"file {i}", [],
                     origin="crawl", status="pending")
    h = page("claims")
    ck("the claims legend reads once, and the per-card copies are gone",
       h.count("How to read these cards") == 1
       and "invisible once approved" in h
       and "The one field here the model WROTE" not in h)

    print("\n--- 4b · claims: slim cards, filters that survive deciding ---")
    import datetime as _dt
    with db.SessionLocal() as s:
        rows_ = (s.query(db.KbClaim)
                 .filter(db.KbClaim.tenant == "baci",
                         db.KbClaim.review == prov.PROPOSED).all())
        rows_[0].entity_key = "aqua-plate"
        rows_[0].source = "crawl-src-marker"
        rows_[1].approved_at = db.utcnow() - _dt.timedelta(days=370)
        s.commit()
        due_id = rows_[1].id
    h = page("claims")
    ck("the metadata folds at the bottom of the card — essentials lead",
       "Details — where it" in h
       and h.count("crawl-src-marker") == 1
       and h.index('value="reject"') < h.index("crawl-src-marker"))
    ck("the filter bar offers the priorities as chips",
       ">came due</a>" in h and ">brand-level</a>" in h
       and ">product-scoped</a>" in h and 'name="corigin"' in h)
    hd = page("claims", "&flt=due")
    ck("came-due narrows to the reconfirmations",
       hd.count('class="anchor" id="c-') == 1 and "of 3 pending (filtered)"
       in hd.replace("showing 1 ", "showing 1 "))
    hs = page("claims", "&flt=scoped")
    ck("product-scoped narrows by scope",
       hs.count('class="anchor" id="c-') == 1 and "aqua-plate" in hs)
    hq = page("claims", "&q=crawl-src-marker")
    ck("search matches the folded metadata too",
       hq.count('class="anchor" id="c-') == 1)
    r = c.post("/admin/claim_edit",
               data={"key": KEY, "claim_id": due_id, "tenant": "baci",
                     "action": "reject", "cpage": "1", "flt": "due"},
               follow_redirects=False)
    ck("a decision keeps the filter — the reader keeps their narrowed view",
       "flt=due" in r.headers.get("location", ""),
       r.headers.get("location", ""))

    print("\n--- 4c · the ship queue filters too ---")
    h = page("ship", "&flt=ad")
    ck("the kind chips narrow the primary queue",
       ">campaigns</a>" in h and ">ads</a>" in h
       and "Campaign email for baci" not in h)
    h = page("ship", "&q=Restock")
    ck("search matches the summary, and says it filtered",
       "Campaign email for baci: Restock" in h
       and "pending (filtered)" in h
       and h.count('value="approved"') == 1)
    with db.SessionLocal() as s:
        ap2 = (s.query(db.Approval)
               .filter(db.Approval.status == "pending",
                       db.Approval.summary.like("%variant 1%")).first().id)
    r = c.post("/admin/ship_decide",
               data={"key": KEY, "tenant": "baci", "approval_id": ap2,
                     "verdict": "denied", "page": "1", "flt": "ad",
                     "q": "variant"}, follow_redirects=False)
    ck("a ship decision keeps its filter and search",
       "flt=ad" in r.headers.get("location", "")
       and "q=variant" in r.headers.get("location", ""),
       r.headers.get("location", ""))

    print("\n--- 5 · conflicts page; plans decide in place ---")
    with db.SessionLocal() as s:
        for i in range(16):
            s.add(db.KbConflict(tenant="baci", table_name="kb_claims",
                                row_id=f"r{i}", field="claim",
                                approved_value="ours",
                                incoming_value="theirs", origin="crawl",
                                status="open"))
        s.commit()
    h = page("conflicts")
    ck("conflicts page at 15", "conflicts 1&ndash;15 of 16" in h)

    real_plans = systems.plans_needing_action
    systems.plans_needing_action = lambda t: [
        {"system_name": "Campaign email", "system_key": "campaign_email",
         "ref": "restock-sep", "planned_for": "Sep 02", "need": "approve",
         "detail": "complete — needs your go-ahead", "run_id": "run-1"}]
    try:
        h = page("plans")
        ck("a decidable plan gets Approve and Skip IN PLACE",
           'action="/admin/plan_approve"' in h
           and 'action="/admin/plan_skip"' in h
           and 'name="back" value="content"' in h)
    finally:
        systems.plans_needing_action = real_plans
    r = c.get(f"/admin/plan_approve?key={KEY}&tenant=baci&id=missing"
              f"&back=content", follow_redirects=False)
    ck("…and the decision lands back on Review's plans queue",
       r.status_code == 303 and "tab=content" in r.headers.get("location", "")
       and "sub=plans" in r.headers.get("location", ""),
       r.headers.get("location", ""))

    print("\n--- 6 · store sync is named and parks honestly ---")
    h = page("catalogue")
    ck("the sub-tab and heading say Store sync",
       "Store sync" in h and "<h2>Store sync</h2>" in h)
    ck("…and with no store the button parks instead of failing — in the "
       "section AND in Sources",
       "parked — no store connected" in h and "Sync from store" not in h
       and ">Sync store</button>" not in h)

    print("\n--- 7 · reports are flashes; the dry run flashes too ---")
    h = page("ship", "&ok=approved 3, refused 1 (untagged)")
    ck("a bulk result renders as the flash, not muted grey",
       '<div class="ok">approved 3, refused 1 (untagged)</div>' in h)
    r = c.get(f"/admin/purge_harvested?key={KEY}&tenant=baci&ui=1",
              follow_redirects=False)
    loc = r.headers.get("location", "")
    ck("the purge dry-run lands back as a flash, not JSON",
       r.status_code == 303 and "dry run" in loc.replace("%20", " "), loc[:120])

    # ---------------------------------------------------------------------
    # A QUEUED DECISION IS CALLED WHAT IT IS (owner, 2026-08-28: real names
    # "both in the Review tab and inside the workflow drafts tab").
    #
    # A skill_output approval's summary is "{skill} for {tenant}: {body[:80]}"
    # — for a campaign that is the head of its HTML — so a queue whose whole
    # job is choosing between things named several of them almost the same.
    # ---------------------------------------------------------------------
    print("\n— the queue names the thing, not the skill and 80 bytes of body —")
    with db.SessionLocal() as s:
        out = db.Output(tenant="baci", system_key="campaign_email",
                        format="campaign_email", status="draft")
        s.add(out)
        s.flush()
        oid_c = out.id
        s.add(db.ArtifactBody(
            tenant="baci", output_id=oid_c, system_key="campaign_email",
            format="campaign_email", body="<p>hi</p>", draft_body="<p>hi</p>",
            meta={"subject": "Your table, ready for August",
                  "segment": "lapsed_buyers", "intent": "offer"},
            bytes=9))
        s.commit()
    ap_c = approvals.request_approval(
        "skill_output", "Campaign email for baci: <!doctype html><html><head>",
        {"tenant": "baci", "skill": "campaign_email", "output_id": oid_c},
        notify=False)
    with db.SessionLocal() as s:
        s.get(db.Approval, ap_c).tenant = "baci"
        s.commit()
    page_n = admin_ui.render_content("s3cret", tenant="baci", sub="ship")
    ck("the row is named by the email's SUBJECT",
       "Your table, ready for August" in page_n,
       "it was the skill name and the head of the HTML")
    ck("  with who it is for and what it is for",
       "to lapsed_buyers" in page_n and "offer" in page_n)
    ck("  and the raw body head is gone", "&lt;!doctype" not in page_n)

    with db.SessionLocal() as s:
        row_c = s.get(db.Approval, ap_c)
        arts = admin_ui._artifacts_for([row_c])
        ck("an approval with NO artifact keeps its own summary",
           admin_ui.approval_title(
               type("A", (), {"payload": {}, "summary": "[RFQ] quote request",
                              "kind": "send_email"})(), arts)
           == "[RFQ] quote request",
           "those summaries are already written for a person")

    print()
    if _fail:
        print(f"FAILED: {len(_fail)} — " + "; ".join(_fail[:8]))
        sys.exit(1)
    print("all green: the day's tab decides in place, at any depth")


if __name__ == "__main__":
    main()
