"""Background: true here, and not proof.

Owner, 2026-08-31: *"Sometimes there are claims that come up that are not
false or true, they're just statements sometimes relevant sometimes not. How
can i file them without affecting the system?"*

There was nowhere. `KbClaim` is "a fact the brand is ALLOWED TO ASSERT" — filed
there an observation becomes selectable, gets cited in copy, appears in the
brand document under "Proof you may lean on", and counts toward the `claim`
token in `kb_needs`, which can flip a thin account to ready on the strength of
a note. Guidance was the only other home and it is the INSTRUCTION channel:
capped at eight, injected on every draft whether it bears or not, headed
"treat as current instruction".

WHAT IS ASSERTED, and every one of these is a way the new row must be WEAKER
than a claim:

  · it is retrieved by entity and by situation, so a sometimes-relevant note
    is present sometimes — the difference from guidance
  · a note filed against an entity is out of scope for every other one, and a
    brand-wide note is in scope always — the same convention claims use
  · it reaches every drafter through the one block they all read, and that
    block SAYS it is not proof
  · it is absent from `kb.KB_SUPPLIERS` and from every `kb_needs` — an
    omission ON PURPOSE, so no volume of background can make a system ready.
    This suite fails if anybody adds it.
  · the console can file one and retire one, and says next to the box exactly
    what filing does not do

Run: python3 scripts/test_context.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ctx.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (bundle, db, dossier, kb, resolve as rs,  # noqa: E402
                 systems, tenants, web)

KEY = "s3cret"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.set_brand("baci", positioning="Italian-designed tableware.", tone="warm")
    kb.add_banned("baci", "made in Italy")
    kb.add_entity("baci", "product", "aqua", "Aqua Plate")
    kb.add_entity("baci", "product", "vera", "Vera Bowl")
    c = TestClient(web.app, base_url="https://testserver")

    print("— filing, and what it refuses —")
    brand_id = kb.add_context("baci", "Buyers ask about lead time before price.")
    ck("a brand-wide statement files", len(brand_id) == 32, brand_id[:40])
    ent_id = kb.add_context("baci", "Photographs badly under warm light.",
                            entity_key="aqua")
    ck("  and one about a thing files against it", len(ent_id) == 32)
    ck("  an empty one is refused",
       kb.add_context("baci", "   ") == "Nothing to file.")
    bad = kb.add_context("baci", "x", entity_key="not-a-thing")
    ck("  and an entity nobody approved is refused, by name",
       "not an entity" in bad, bad[:60])

    print("\n— scope: the row says which, so nobody had to decide in advance —")
    ck("a brand-wide note is in scope for any entity",
       len(kb.contexts("baci", entity_key="vera")) == 1,
       "empty entity_key means the brand, the same convention claims use")
    ck("  and an entity's note is out of scope for another",
       all(x.entity_key != "aqua"
           for x in kb.contexts("baci", entity_key="vera")))
    ck("  and in scope for its own",
       len(kb.contexts("baci", entity_key="aqua")) == 2)

    print("\n— it reaches every drafter, and the block says what it is not —")
    b = rs.resolve("baci", tier=3, entity_key="aqua")
    ck("the bundle carries it", len(b.get("context") or []) == 2,
       str(len(b.get("context") or [])))
    blk = (b.get("rules") or {}).get("block") or ""
    ck("  in the one block every skill, the responder and mail all read",
       "lead time" in blk, "one append beats seven")
    ck("  under a heading that refuses it as proof",
       "NOT proof" in blk and "may not state it as a fact" in blk)
    ck("  and it is declared in the package",
       "context" in bundle.PARTS
       and bundle.PARTS["context"]["supplies"] == "resolve.resolve",
       "a part supplied by nobody is the defect bundle.py exists for")

    print("\n— and it is NOT proof, in every place that decides —")
    ck("it carries no claim id a draft could cite",
       all("claim_id" not in x for x in (b.get("context") or [])),
       "the validator requires a factual sentence to cite an approved claim")
    ck("it is absent from KB_SUPPLIERS, on purpose",
       "context" not in kb.KB_SUPPLIERS,
       "adding it would let background make a thin account look ready")
    ck("  and no system declares it as a need",
       not any("context" in (v.get("kb_needs") or ())
               for v in systems.CATALOG.values()))
    ck("  so an account with background and no claims is still short a claim",
       "claim" in kb.needs_met("baci", ("claim",)),
       str(kb.needs_met("baci", ("claim",))))

    print("\n— the compiled document names it and separates it —")
    md = dossier.build("baci", "blog")["markdown"]
    ck("the document carries a Background section",
       "Background — true here, and NOT proof" in md)
    ck("  and it is not under Proof you may lean on",
       md.index("Background — true here") > md.index("## Hard rules"),
       "put under proof it would be quoted")

    print("\n— the console files one, and says what filing does not do —")
    page = c.get(f"/admin/ui?key={KEY}&tab=content&sub=context&tenant=baci").text
    ck("the Background card renders", "Background" in page
       and "context_add" in page)
    ck("  and states the three things it does NOT do",
       "citable proof" in page and "count toward" in page
       and "every draft" in page,
       "the whole reason this row exists is that the other homes do more")
    r = c.post(f"/admin/context_add?key={KEY}",
               data={"tenant": "baci", "text": "Trade buyers order in threes.",
                     "entity_key": "", "situation": ""},
               follow_redirects=False)
    ck("filing from the console works", r.status_code == 303
       and any("Trade buyers" in x.text for x in kb.contexts("baci")),
       r.headers.get("location", "")[:90])
    r2 = c.post(f"/admin/context_add?key={KEY}",
                data={"tenant": "baci", "text": "x",
                      "entity_key": "not-a-thing", "situation": ""},
                follow_redirects=False)
    ck("  and a refusal comes back as a refusal",
       "err=" in r2.headers.get("location", ""),
       r2.headers.get("location", "")[:90])

    print("\n— a claim can be demoted to background, from both surfaces —")
    kb.add_claim("baci", "Buyers compare us with melamine.",
                 "tested 200 cycles", [], entity_key="aqua")
    with db.SessionLocal() as s_:
        cid = [r.id for r in s_.query(db.KbClaim).all()
               if "melamine" in (r.claim or "")][0]
    n_ctx = len(kb.contexts("baci"))
    r3 = c.post(f"/admin/claim_edit?key={KEY}",
                data={"claim_id": cid, "tenant": "baci", "action": "background",
                      "claim": "Buyers compare us with melamine."},
                follow_redirects=False)
    ck("the proposal queue's third button files it",
       r3.status_code == 303 and len(kb.contexts("baci")) == n_ctx + 1,
       "reject threw the sentence away; approve made it citable")
    moved = [x for x in kb.contexts("baci") if "melamine" in x.text][0]

    ck("  scope travels with it", moved.entity_key == "aqua", moved.entity_key)
    ck("  the EVIDENCE does not travel into the text",
       "200 cycles" not in moved.text and "200 cycles" in (moved.source or ""),
       "'X — tested 200 cycles' as background is proof wearing another hat; "
       "`source` is documented as internal provenance a customer never sees")
    ck("  it is no longer selectable as proof",
       not any("melamine" in x.claim for x in kb.claims("baci")))
    with db.SessionLocal() as s_:
        was = s_.get(db.KbClaim, cid)
        ck("  and the claim row SURVIVES, retired",
           was is not None and was.status == "retired",
           "outputs on the ledger cite claim ids — a deleted row turns a past "
           "draft's provenance into a dangling reference")
    ck("  doing it twice says so rather than filing twice",
       "already retired" in kb.claim_to_context(cid),
       kb.claim_to_context(cid))

    # The same control on an APPROVED claim: a sentence that turned out to be
    # true and not proof does not stop being that because somebody approved it.
    kb.add_claim("baci", "People assume the glaze is plastic.", "", [])
    with db.SessionLocal() as s_:
        cid2 = [r.id for r in s_.query(db.KbClaim).all()
                if "glaze" in (r.claim or "")][0]
    n2 = len(kb.contexts("baci"))
    r4 = c.post(f"/admin/claim_update?key={KEY}",
                data={"claim_id": cid2, "tenant": "baci",
                      "action": "background"},
                follow_redirects=False)
    ck("the approved-claim editor has it too",
       r4.status_code == 303 and len(kb.contexts("baci")) == n2 + 1,
       r4.headers.get("location", "")[:90])

    print("\n— retiring keeps the record —")
    n_before = len(kb.contexts("baci"))
    c.get(f"/admin/context_retire?key={KEY}&tenant=baci&id={brand_id}",
          follow_redirects=False)
    ck("it leaves the live set", len(kb.contexts("baci")) == n_before - 1)
    ck("  and is archived, not deleted",
       any(x.id == brand_id for x in kb.contexts("baci", include_archived=True)),
       "what was on file when a draft was written is part of why it reads so")

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
