"""Correct a claim before filing it, without leaving the draft.

Owner, 2026-08-31: *"'Glassbox has the capacity for 250 people' this statement
is false, but I would like the ability to change it to 'Glassbox has the
capacity for 180 people' and then adding this correct claim to the system for
future reference. I also dont want to have to leave the system screen to
approve the claim, can it happen as a pop up within the system screens?"*

Add-claim posted the sentence VERBATIM, so the case that matters most — the
drafter got a number wrong and you know the right one — had no path at all:
file the wrong claim, or drop the sentence and retype the fact somewhere else.

WHAT IS ASSERTED:

  · the panel is ON the draft, prefilled and EDITABLE
  · what is filed is what came BACK, not what the draft said
  · approving there is a person's decision, so it lands approved, `human`, and
    skips the background filter — a corrected figure is not an observation
  · proposing there is unchanged: inert until reviewed
  · it never leaves the workroom, either way

Run: python3 scripts/test_claim_fix.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cf.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui, db, kb, tenants, web  # noqa: E402

KEY = "s3cret"
WRONG = "Glassbox has the capacity for 250 people."
RIGHT = "Glassbox has the capacity for 180 people."
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _draft(tenant="baci"):
    with db.SessionLocal() as s:
        out = db.Output(tenant=tenant, system_key="blog", format="cms_article",
                        status="recorded", body=WRONG)
        s.add(out)
        s.commit()
        art = db.ArtifactBody(tenant=tenant, output_id=out.id,
                              system_key="blog", format="cms_article",
                              body=f"<p>{WRONG}</p>", draft_body=WRONG,
                              bytes=40)
        s.add(art)
        s.commit()
        return out.id


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.add_entity("baci", "product", "glassbox", "Glassbox")
    c = TestClient(web.app, base_url="https://testserver")
    oid = _draft()

    print("— the panel is on the draft, prefilled and editable —")
    panel = admin_ui._fix_claim_panel(KEY, "baci", oid, WRONG)
    ck("it is a panel, not a bare button", "<details" in panel
       and "claim_from_note" in panel)
    ck("  the sentence is in a TEXTAREA, not a hidden field",
       "<textarea" in panel and WRONG in panel,
       "a hidden field is the wrong number, filed faster")
    ck("  with somewhere to put the evidence and the entity",
       'name="evidence"' in panel and 'name="entity_key"' in panel
       and "Glassbox" in panel)
    ck("  and both answers, each saying what it does",
       'value="approve"' in panel and 'value="propose"' in panel
       and "citable" in panel)
    ck("  it needs no script to be reachable",
       "showModal" not in panel and "<dialog" not in panel,
       "this console's rule is that script enhances and never gates — a "
       "<dialog> with no showModal() is a control nobody can reach")

    print("\n— the CORRECTION is what gets filed —")
    r = c.post(f"/admin/claim_from_note?key={KEY}",
               data={"output_id": oid, "sentence": RIGHT,
                     "evidence": "fire certificate 2026",
                     "entity_key": "glassbox", "action": "approve"},
               follow_redirects=False)
    ck("it lands back on the draft", r.status_code == 303
       and f"/admin/work/{oid}" in r.headers.get("location", ""),
       r.headers.get("location", "")[:80])
    live = kb.claims("baci", entity_key="glassbox")
    ck("  the corrected number is on file", any("180" in x.claim for x in live),
       "; ".join(x.claim[:40] for x in live) or "nothing")
    ck("  and the wrong one never was",
       not any("250" in x.claim for x in live),
       "posting the original would make the box a decoration")
    _row = [x for x in live if "180" in x.claim][0]
    ck("  with the evidence it was given",
       (_row.evidence or "") == "fire certificate 2026", _row.evidence)
    ck("  scoped to the entity that was picked",
       (_row.entity_key or "") == "glassbox", _row.entity_key)

    print("\n— an approval there is a PERSON'S, and is recorded as one —")
    ck("origin is human, not agent", (_row.origin or "") == "human",
       "`origin` is what precedence is computed from — filed as `agent`, the "
       "next crawl or store sync overwrites the correction with 250 again")
    ck("  and it is citable immediately",
       any("180" in x.claim for x in kb.claims("baci", entity_key="glassbox")),
       "approving where the evidence is on screen IS the review")

    print("\n— and the background filter does not re-ask —")
    oid2 = _draft()
    c.post(f"/admin/claim_from_note?key={KEY}",
           data={"output_id": oid2,
                 "sentence": "Guests always ask about the capacity.",
                 "evidence": "", "entity_key": "", "action": "approve"},
           follow_redirects=False)
    ck("an approved correction is never routed to background",
       any("Guests always ask" in x.claim for x in kb.claims("baci")),
       "assess_kind would call that an observation; a person who corrected it "
       "and pressed approve has already answered that question")

    print("\n— and the DRAFT is corrected too, once approved —")
    oid4 = _draft()
    with db.SessionLocal() as s_:
        _a = (s_.query(db.ArtifactBody)
              .filter(db.ArtifactBody.output_id == oid4).first())
        # Markup THROUGH the sentence, which is the normal case: the claim
        # margin reads plain text, so the sentence is not a literal substring
        # of the body it came from.
        _a.body = ("<p>A bright room. <strong>Glassbox</strong> has the "
                   "capacity for 250&nbsp;people.</p>")
        s_.commit()
    r4 = c.post(f"/admin/claim_from_note?key={KEY}",
                data={"output_id": oid4, "original": WRONG, "sentence": RIGHT,
                      "evidence": "", "entity_key": "glassbox",
                      "action": "approve"},
                follow_redirects=False)
    with db.SessionLocal() as s_:
        body = (s_.query(db.ArtifactBody)
                .filter(db.ArtifactBody.output_id == oid4).first()).body
    ck("the draft now says the corrected number", "180" in body, body[:90])
    ck("  and no longer says the wrong one", "250" not in body, body[:90])
    ck("  the markup is still balanced",
       body.count("<strong>") == body.count("</strong>"),
       "a sentence opening inside <strong> and closing after it would leave "
       "the tag unclosed and the rest of the article bold")
    ck("  the flash says the draft changed",
       "draft now says it too" in r4.headers.get("location", "").replace("%20", " ")
       or "draft%20now%20says" in r4.headers.get("location", ""),
       r4.headers.get("location", "")[-90:])
    with db.SessionLocal() as s_:
        vs = (s_.query(db.ArtifactVersion)
              .filter(db.ArtifactVersion.output_id == oid4).all())
    ck("  and it is a VERSION, not a silent overwrite",
       any((v.note or "") == "claim corrected" for v in vs),
       "the draft-vs-published delta is the blog system's declared measure "
       "and a history that can lose a step cannot tell it")

    print("\n— when the sentence has moved on, it SAYS so —")
    oid5 = _draft()
    with db.SessionLocal() as s_:
        _a = (s_.query(db.ArtifactBody)
              .filter(db.ArtifactBody.output_id == oid5).first())
        _a.body = "<p>Something else entirely.</p>"
        s_.commit()
    r5 = c.post(f"/admin/claim_from_note?key={KEY}",
                data={"output_id": oid5, "original": WRONG, "sentence": RIGHT,
                      "evidence": "", "entity_key": "", "action": "approve"},
                follow_redirects=False)
    ck("a miss is reported, not passed over",
       "NOT%20changed" in r5.headers.get("location", ""),
       "a reader told 'approved' while the article still reads 250 has been "
       "told the wrong thing by omission")

    print("\n— a correction meets the ban list like any other edit —")
    kb.add_banned("baci", "handmade")
    oid6 = _draft()
    r6 = c.post(f"/admin/claim_from_note?key={KEY}",
                data={"output_id": oid6, "original": WRONG,
                      "sentence": "Glassbox is handmade.", "evidence": "",
                      "entity_key": "", "action": "approve"},
                follow_redirects=False)
    ck("the draft is not rewritten with a banned phrase",
       "ban%20list%20forbids" in r6.headers.get("location", ""),
       "the one edit path that skipped the ban list would be the one nobody "
       "typed into")

    print("\n— proposing is unchanged: inert until reviewed —")
    oid3 = _draft()
    n_before = len(kb.pending_claims("baci"))
    c.post(f"/admin/claim_from_note?key={KEY}",
           data={"output_id": oid3, "original": WRONG,
                 "sentence": "Ceilings are 6.2 metres.",
                 "evidence": "", "entity_key": "", "action": "propose"},
           follow_redirects=False)
    ck("it is proposed, not approved",
       len(kb.pending_claims("baci")) == n_before + 1)
    ck("  and nothing may cite it yet",
       not any("6.2 metres" in x.claim for x in kb.claims("baci")),
       "a path from text a model wrote to a row every draft may assert stays "
       "closed unless a person opens it")

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
