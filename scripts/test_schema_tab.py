"""The Data layer tab: act-where-you-report, mechanically.

Owner, 2026-08-23: the tab "doesnt allow us to fix data layer issues from
there, we have to navigate to the places where the data layer tells us needs
attention." Step 4 (spec §5) rebuilt it around that sentence, and this suite
pins the load-bearing behaviors:

  1. QUEUE & INSIGHTS LANDS FIRST, and its rows carry their controls: a
     missing objection gets an ANSWER BOX that files approved through the
     canonical writer; an entity gap gets its inline save; both land the
     reader back on the queue.
  2. ACTIVE LEARNING IS REAL — keep-as-guidance reaches the prompt channel,
     make-it-a-rule reaches the ban list, and dismiss removes the lesson
     from the DRAFTER'S BRIEF too (both doors read the same rows; a dismiss
     that only hid the card would be a control lying about its consequence).
  3. THE BADGE IS THE QUEUE — one computation feeds both (rule 8).
  4. DOMAIN VIEWS PAGE, SEARCH AND EDIT IN PLACE; claims gain the Removed
     filter with Restore (closing "restore is still an API call"), and every
     decision lands back on the view, filter and page it was made from.
  5. GROUNDED OUTPUT shows a claim working inside a kept artifact.
  6. ADVANCED keeps the schema reference — computed with aggregate queries,
     not full-table loads (asserted against the SQL actually executed).

Run: python3 scripts/test_schema_tab.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'st.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui, db, kb, resolve, systems, tenants, web  # noqa: E402

KEY = "s3cret"
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


c = TestClient(web.app, base_url="https://testserver")


def page(sub="", extra=""):
    return c.get(f"/admin/ui?tab=schema&tenant=baci&key={KEY}"
                 + (f"&sub={sub}" if sub else "") + extra).text


def main():
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.set_brand("baci", positioning="Italian-designed tableware.",
                 tone="direct, warm")
    kb.add_banned("baci", "hand-decorated")
    kb.add_situation("baci", "hosting_dinners", patterns=[["dinner"]],
                     description="Setting a table for guests", origin="human")
    kb.add_situation("baci", "gift_hunting", patterns=[["gift"]],
                     description="Buying a present", origin="human")
    kb.add_entity("baci", "product", "aqua-plate", "Aqua Plate",
                  description="A generous 32 cm plate.", origin="human")
    kb.add_entity("baci", "collection", "aqua-range", "The Aqua Range",
                  origin="human")
    # One answered situation, one missing — readiness must rank the gap.
    kb.add_objection("baci", "Is it dishwasher safe?", "Yes, at 65 degrees.",
                     situations=["hosting_dinners"], origin="human")
    for i in range(17):
        kb.add_claim("baci", f"Claim number {i} about acrylic strength.",
                     f"lab file {i}", ["hosting_dinners"], origin="human")

    print("\n--- 1 · the queue lands first, controls attached ---")
    h = page()
    ck("the strip lands on Queue & Insights", "Queue &amp; Insights" in h
       and "What to fix, in order" in h)
    ck("the missing situation gets an ANSWER BOX, not a link away",
       "No approved answer for" in h and "gift_hunting" in h
       and "objection_add" in h)
    r = c.post("/admin/objection_add",
               data={"key": KEY, "tenant": "baci",
                     "situations": "gift_hunting",
                     "objection": "Will it arrive gift-ready?",
                     "response": "Every order ships in the branded box.",
                     "back": "schema", "bsub": "queue"},
               follow_redirects=False)
    loc = r.headers.get("location", "")
    ck("answering lands back on the queue", r.status_code == 303
       and "tab=schema" in loc and "sub=queue" in loc, loc)
    filed = [o for o in kb.objections("baci", any_entity=True)
             if "gift-ready" in (o.objection or "")]
    ck("…filed APPROVED through the canonical writer — the next draft can "
       "use it", len(filed) == 1)
    ck("…and readiness now counts the situation answered",
       all("gift_hunting" not in str(a.get("fix", ""))
           for a in resolve.readiness("baci")["next_actions"]))

    kb.record_unknowns("baci", [{"basis": "unknown", "key": "aqua-plate",
                                 "name": "Aqua Plate",
                                 "attribute": "capacity"}],
                       asked_for="does the pitcher hold a litre?")
    h = page()
    ck("an entity gap renders with its inline save", "capacity unknown" in h
       and "kb_unknown" in h)
    u = kb.unknowns("baci")[0]
    r = c.get(f"/admin/kb_unknown?key={KEY}&tenant=baci&id={u.id}"
              f"&value=1.2 litres&back=schema&bsub=queue",
              follow_redirects=False)
    ck("saving the value lands back on the queue",
       r.status_code == 303 and "tab=schema" in r.headers.get("location", ""),
       r.headers.get("location", ""))
    ck("…and the gap is closed", not kb.unknowns("baci"))

    print("\n--- 2 · active learning: three verbs, three real channels ---")
    row = systems.find("baci", "campaign_email") or systems.create(
        "baci", "campaign_email")
    with db.SessionLocal() as s:
        for i, txt in enumerate(("- shortened the opening in 4 of 6 sends",
                                 "- dropped the second product block")):
            s.add(db.SystemRun(system_id=row.id, tenant="baci",
                               stage="sent", decision="edited",
                               edit_diff=txt,
                               created_at=db.utcnow()
                               - dt.timedelta(days=2 + i)))
        s.commit()
    lessons = systems.edit_lesson_rows("baci")
    ck("observed lessons reach the lane", len(lessons) == 2,
       str(len(lessons)))
    ck("…and the badge counts them the moment they exist (non-zero case)",
       admin_ui._badges("baci", full=True)["schema"]
       == admin_ui._schema_needs_you("baci")["n"] >= 2)
    h = page()
    ck("the lane says OBSERVED, never instruction",
       "Observed, never instruction" in h and "Keep as guidance" in h
       and "shortened the opening" in h)

    keep, drop = lessons[0], lessons[1]
    r = c.post("/admin/lesson_act",
               data={"key": KEY, "tenant": "baci", "act": "guidance",
                     "run_id": keep["run_id"],
                     "system_key": keep["system_key"],
                     "back": "schema", "bsub": "queue"},
               follow_redirects=False)
    ck("keep-as-guidance lands back on the queue", r.status_code == 303
       and "tab=schema" in r.headers.get("location", ""))
    ck("…and REACHES the prompt channel",
       "shortened the opening" in systems.feedback_block("baci",
                                                         "campaign_email"))
    ck("…and leaves the lane (it lives in the guidance now)",
       keep["run_id"] not in [x["run_id"]
                              for x in systems.edit_lesson_rows("baci")])

    c.post("/admin/lesson_act",
           data={"key": KEY, "tenant": "baci", "act": "dismiss",
                 "run_id": drop["run_id"], "system_key": drop["system_key"],
                 "back": "schema", "bsub": "queue"}, follow_redirects=False)
    ck("dismiss removes the lesson from the lane",
       not systems.edit_lesson_rows("baci"))
    ck("…and from the DRAFTER'S BRIEF — both doors read the same rows",
       "second product block" not in systems.edit_lessons("baci",
                                                          "campaign_email"))

    r = c.post("/admin/lesson_act",
               data={"key": KEY, "tenant": "baci", "act": "rule",
                     "run_id": "x", "system_key": "campaign_email",
                     "phrase": "cheapest ever", "back": "schema",
                     "bsub": "queue"}, follow_redirects=False)
    b = kb.brand("baci")
    ck("make-it-a-rule reaches the ban list",
       any("cheapest ever" in str(x) for x in (b.banned_claims or [])))

    r = c.get(f"/admin/exclude_term?key={KEY}&tenant=baci&term=rental"
              f"&back=schema&bsub=queue", follow_redirects=False)
    ck("a mute-lesson accept lands back on the queue",
       r.status_code == 303 and "tab=schema" in r.headers.get("location", ""),
       r.headers.get("location", ""))
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, "baci")
        terms = list((t.analytics or {}).get("exclude_terms") or [])
    ck("…and the term is excluded", "rental" in terms)

    print("\n--- 3 · the badge IS the queue ---")
    need = admin_ui._schema_needs_you("baci")
    badge = admin_ui._badges("baci", full=True)["schema"]
    ck("one computation feeds both (rule 8)", badge == need["n"],
       f"badge {badge} vs queue {need['n']}")
    ck("…and it counts the four actionable parts",
       need["n"] == (len(need["actions"]) + len(need["unknowns"])
                     + len(need["lessons"]) + len(need["mutes"])))

    print("\n--- 4 · domain views: page, search, edit, restore ---")
    h = page("claims")
    ck("claims page 15 of 17, pager says so",
       h.count('class="anchor" id="cl-') == 15 and "of 17" in h)
    h2 = page("claims", "&page=2")
    ck("page 2 holds the rest", h2.count('class="anchor" id="cl-') == 2)
    h3 = page("claims", "&q=number+13")
    ck("search narrows the list", h3.count('class="anchor" id="cl-') == 1)

    kb.add_claim("baci", "Proposed by the crawler.", "site", [],
                 origin="crawl", status="pending")
    h4 = page("claims", "&state=awaiting")
    ck("the awaiting filter shows the proposal with Approve/Reject",
       "Proposed by the crawler." in h4 and "claim_review" in h4
       and "back=schema" in h4)
    prop = [r for r in kb.claim_inventory("baci")["pending"]][0]
    r = c.get(f"/admin/claim_review?key={KEY}&tenant=baci&ui=1&back=schema"
              f"&bsub=claims&bstate=awaiting&claim_id={prop.id}&approve=yes",
              follow_redirects=False)
    ck("deciding from the view lands back on the view",
       r.status_code == 303
       and "tab=schema" in r.headers.get("location", "")
       and "state=awaiting" in r.headers.get("location", ""),
       r.headers.get("location", ""))

    victim = kb.claim_inventory("baci")["selectable"][0]
    kb.remove("baci", "claim", victim.id)
    h5 = page("claims", "&state=removed")
    ck("the Removed filter lists it with RESTORE — no more API-call-only "
       "undo", "kb_restore" in h5 and "Restore" in h5)
    r = c.post("/admin/kb_restore",
               data={"key": KEY, "tenant": "baci", "kind": "claim",
                     "id": victim.id, "back": "schema", "bsub": "claims",
                     "bstate": "removed"}, follow_redirects=False)
    ck("restore lands back on the removed view", r.status_code == 303
       and "state=removed" in r.headers.get("location", ""))
    ck("…and the claim is selectable again",
       any(r_.id == victim.id
           for r_ in kb.claim_inventory("baci")["selectable"]))

    r = c.post("/admin/kb_row_add",
               data={"key": KEY, "tenant": "baci", "kind": "audience",
                     "akey": "hosts", "name": "Hosts who entertain",
                     "pains": "dull tables", "vocabulary": "colour\nset",
                     "back": "schema", "bsub": "audiences"},
               follow_redirects=False)
    ck("the structured add form files an audience", r.status_code == 303
       and any(a.key == "hosts" for a in kb.audiences("baci")))
    aud = [a for a in kb.audiences("baci") if a.key == "hosts"][0]
    r = c.post("/admin/audience_update",
               data={"key": KEY, "tenant": "baci", "row_id": aud.id,
                     "name": "Hosts and entertainers",
                     "pains": "dull tables\nmismatched sets",
                     "vocabulary": "colour\nset",
                     "buying_trigger": "a dinner on the calendar",
                     "back": "schema", "bsub": "audiences"},
               follow_redirects=False)
    aud2 = [a for a in kb.audiences("baci") if a.key == "hosts"][0]
    ck("the audience editor saves — the last display-only kind has one",
       aud2.name == "Hosts and entertainers"
       and "mismatched sets" in (aud2.pains or []),
       f"{aud2.name} / {aud2.pains}")

    h6 = page("catalogue")
    ck("the catalogue offers per-row group assignment",
       "Add to group" in h6 and "aqua-range" in h6)
    r = c.post("/admin/entity_group",
               data={"key": KEY, "tenant": "baci", "entity_keys": "aqua-plate",
                     "group": "aqua-range", "back": "schema",
                     "bsub": "catalogue"}, follow_redirects=False)
    ck("assigning lands back on the catalogue view", r.status_code == 303
       and "tab=schema" in r.headers.get("location", ""),
       r.headers.get("location", ""))
    ck("…and the membership is real",
       "aqua-range" in kb.ancestors("baci", "aqua-plate"))

    r = c.get(f"/admin/situation_add?key={KEY}&tenant=baci&tag=wedding_prep"
              f"&description=Planning a wedding table&back=schema"
              f"&bsub=situations", follow_redirects=False)
    ck("adding a situation lands back on the view", r.status_code == 303
       and "tab=schema" in r.headers.get("location", ""))
    ck("…and the tag exists", "wedding_prep" in kb.situations("baci"))

    print("\n--- 5 · grounded output: the fact, working ---")
    cl = kb.claim_inventory("baci")["selectable"][0]
    with db.SessionLocal() as s:
        out = db.Output(tenant="baci", system_key="blog", format="cms_article",
                        status="drafted", claim_ids=[cl.id],
                        body="short ledger rendering")
        s.add(out)
        s.flush()
        s.add(db.ArtifactBody(
            tenant="baci", output_id=out.id, system_key="blog",
            format="cms_article",
            body=(f"<h1>Care guide</h1><p>Every piece holds up because "
                  f"{cl.claim.rstrip('.')} in daily use.</p>"),
            draft_body="<p>d</p>", bytes=100))
        s.commit()
        oid = out.id
    h = page()
    ck("the queue shows the claim used, with where",
       "used 1&times; / 90d" in h and f"/admin/work/{oid}" in h)
    ck("…with the carrying sentence highlighted",
       "<b>" in h and "Care guide" not in h.split("Grounded output")[0])
    ck("…and its editor one click away", f"#cl-{cl.id}" in h)

    print("\n--- 6 · advanced: reference, computed with aggregates ---")
    stmts: list[str] = []

    from sqlalchemy import event

    @event.listens_for(db.engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, parameters, context, executemany):
        stmts.append(statement)

    body = admin_ui._schema_advanced(KEY, "baci")
    event.remove(db.engine, "before_cursor_execute", _capture)
    ck("the reference content survives", "kb_claims" in body
       and "no foreign keys anywhere" in body
       and "APPROVED rows only" in body)
    # The tables completeness() does not read must NEVER be full-loaded by
    # the fill bars — before step 4 every row of every table was.
    bare = [st for st in stmts
            if any(f"FROM {t}" in st for t in
                   ("kb_unknowns", "kb_conflicts", "kb_embeddings",
                    "kb_assets", "kb_situations"))
            and "count(" not in st.lower() and "sum(" not in st.lower()]
    ck("fill bars come from aggregate queries, not full-table loads",
       not bare, (bare[0][:120] if bare else ""))

    print("\n--- 7 · photos say where the decision lives ---")
    from app import provenance as prov
    with db.SessionLocal() as s:
        s.add(db.KbAsset(tenant="baci", kind="image", title="candidate",
                         url="https://example.com/x.jpg",
                         review=prov.PROPOSED))
        s.commit()
    h = page("photos")
    ck("a waiting candidate names its queue",
       "waiting" in h and "decide on Review" in h)

    print()
    if _fail:
        print(f"FAILED: {len(_fail)} — " + "; ".join(_fail[:8]))
        sys.exit(1)
    print("all green: the Data layer acts where it reports")


if __name__ == "__main__":
    main()
