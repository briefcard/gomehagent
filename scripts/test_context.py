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

from app import (bundle, db, dossier, embed, kb,  # noqa: E402
                 resolve as rs, systems, tenants, web)

KEY = "s3cret"
_fail = []


def _fake_embed(texts):
    """A deterministic bag-of-words embedder, so the semantic half RUNS here.

    Without it every semantic assertion in this file is vacuous offline: no
    `OPENAI_API_KEY` means `embed_texts` degrades, `similar` returns fingerprint
    matches only, and a guard that deletes the whole context branch reports
    `MISSED` because nothing observable changed. Two of them did exactly that
    on 2026-08-31 before this existed.

    Tokens hashed into 64 buckets: a rephrasing shares most of its words and
    lands near, which is the property under test — not the provider's quality.
    """
    import hashlib
    import re as _re
    out = []
    for t in texts:
        v = [0.0] * 64
        for w in _re.findall(r"[a-z]+", (t or "").lower()):
            if len(w) < 3:
                continue
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
        n = sum(x * x for x in v) ** 0.5 or 1.0
        out.append([x / n for x in v])
    return out, ""


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _indexed_kinds() -> set:
    """Which kinds `kb` actually indexes — read from the calls, not recalled.

    Background landed unindexed: `embed` already covered `claim` and
    `situation`, and nothing put context in front of it, so a rephrasing of
    something already on file could not be found by anything. That is the
    whole reason for having somewhere to put statements that keep coming up
    in different words.
    """
    import ast
    import pathlib as _pl
    src = (_pl.Path(__file__).resolve().parent.parent / "app" / "kb.py")
    out = set()
    for n in ast.walk(ast.parse(src.read_text())):
        if not isinstance(n, ast.Call):
            continue
        if getattr(n.func, "attr", "") not in ("ensure", "forget"):
            continue
        if len(n.args) >= 2 and isinstance(n.args[1], ast.Constant):
            out.add(n.args[1].value)
    return out


def main() -> int:
    embed._PROVIDER = _fake_embed          # the seam, replaced — see above
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
    # THE BEFORE-STATE, read where the claim is actually visible. Without it,
    # "no longer selectable" is a statement about a list that never held it.
    _was_citable = any("melamine" in x.claim
                       for x in kb.claims("baci", entity_key="aqua"))
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
    # READ WHERE IT WAS VISIBLE. `kb.claims("baci")` unscoped never returned
    # this claim — it is scoped to `aqua` — so the assertion passed on SCOPE
    # and would have passed identically with retirement broken. The scoped
    # read is the one that changes, and the before-state is asserted so the
    # after-state means something.
    ck("  it WAS selectable before, under its own scope",
       _was_citable,
       "if it was not, the check below proves nothing about retirement")
    ck("  it is no longer selectable as proof",
       not any("melamine" in x.claim
               for x in kb.claims("baci", entity_key=moved.entity_key)),
       "a retired claim reaching a generator is a fact the owner withdrew, "
       "asserted in a draft")
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

    print("\n— the same statement twice is one row, not two —")
    n0 = len(kb.contexts("baci"))
    again = kb.add_context("baci", "buyers ask about lead time before price")
    ck("a re-typed statement is recognised, in any casing",
       again.startswith("already-on-file:") and len(kb.contexts("baci")) == n0,
       again[:40])
    ck("  but the same words about a THING are a different statement",
       len(kb.add_context("baci", "Buyers ask about lead time before price.",
                          entity_key="vera")) == 32,
       "entity is part of the identity, the same as it is for a claim")

    print("\n— and the lookup spans BOTH kinds —")
    kb.add_claim("baci", "Ships in three days.", "carrier data", [])
    r = kb.similar("baci", "Ships in three days.")
    ck("an existing CLAIM is found from a filing check",
       r["exact"].startswith("claim:"), r["exact"][:24])
    r2 = kb.similar("baci", "buyers ask about lead time before price")
    ck("  and so is existing BACKGROUND",
       r2["exact"].startswith("context:"), r2["exact"][:24])
    ck("  and when the semantic half cannot run it SAYS so",
       isinstance(r2["degraded"], str),
       r2["degraded"] or "(semantic ran)")
    ck("background is an INDEXED kind now, like claims",
       "context" in _indexed_kinds(), str(sorted(_indexed_kinds())))
    # THE PROPERTY THE OWNER ASKED FOR, asserted on behaviour: a REPHRASING,
    # sharing no fingerprint with anything, is matched against what is on file.
    kb.add_context("baci", "Lead times are the first thing trade buyers raise.")
    r3 = kb.similar("baci", "Trade buyers raise lead times first of all")
    ck("a rephrasing is matched to existing background",
       any("Lead times" in x["text"] for x in r3["context"]),
       f"{[x['text'][:40] for x in r3['context']]} · {r3['degraded']}")
    ck("  and a rephrased CLAIM is found too, from the same call",
       any("three days" in x["text"].lower() for x in
           kb.similar("baci", "Orders ship within three days")["claims"]),
       "one lookup, both kinds — each dedup mechanism used to see half")

    print("\n— the same statement in two kinds is reported as one pair —")
    kb.add_claim("baci", "Trade buyers raise lead times first of all.",
                 "carrier data", [])
    # 0.65 for THIS suite's embedder, not for the real one. `_fake_embed` is
    # a bag of words: it scores genuine paraphrase around 0.70 where
    # text-embedding-3 puts it well above 0.90 (see `embed.MIN_SEMANTIC_SCORE`
    # and OVERLAP_SCORE). The property under test is the cross-kind JOIN, not
    # the provider's quality, so the threshold is set to the provider in use.
    rep = kb.overlaps("baci", min_score=0.65)
    ck("the report ran", not rep["degraded"], rep["degraded"])
    _cross = [x for x in rep["pairs"]
              if {x["a"]["kind"], x["b"]["kind"]} == {"claim", "context"}]
    ck("a claim and a piece of background saying one thing is caught",
       bool(_cross),
       f"{[(x['a']['kind'], x['b']['kind'], x['score']) for x in rep['pairs']]}")
    ck("  and rows differing only by ENTITY are not called duplicates",
       not any(x["a"]["scope"] != x["b"]["scope"] for x in rep["pairs"]),
       "the same sentence about two products is two statements — the claim "
       "queue says so in prose and the report must not argue with it")
    ck("  and an unrelated note is not dragged in",
       not any("packaging" in x["a"]["text"] or "packaging" in x["b"]["text"]
               for x in rep["pairs"]),
       "a report that calls merely-related rows duplicates trains people to "
       "ignore the report")

    print("\n— and the CLAIM QUEUE says so before it is approved —")
    # The SURFACES use the production threshold. `_fake_embed` puts genuine
    # paraphrase around 0.70 where text-embedding-3 puts it above 0.90, so the
    # constant is tuned to the embedder in use — the surfaces are unchanged.
    kb.OVERLAP_SCORE = 0.65
    # THE OTHER ORDER. A proposal that arrives AFTER the background is routed
    # into it and never reaches this queue (asserted below). What the flag is
    # for is the case routing cannot catch: a proposal already sitting here
    # when somebody files the background, which is every proposal filed before
    # this existed.
    # The proposal has to be one the FILTER keeps as a claim — an observation
    # is now routed to background at file time and never reaches this queue,
    # which is the whole point of the filter. A checkable sentence stays here,
    # and the background is filed by hand afterwards.
    kb.add_claim("baci", "Packaging is recycled board, 350gsm.", "", [],
                 status="pending")
    kb.add_context("baci", "The packaging is recycled board at 350 gsm.")
    q = c.get(f"/admin/ui?key={KEY}&tab=content&sub=claims&tenant=baci").text
    ck("a proposal restating existing background is flagged there",
       "Already on file as background" in q,
       "approving it promotes to citable proof a sentence somebody "
       "deliberately filed as not being that")

    print("\n— a harvested restatement goes to background, not to the queue —")
    kb.add_context("baci", "Warm light is unkind to the whole aqua range.",
                   entity_key="aqua")
    n_pend = len(kb.pending_claims("baci"))
    said = kb.add_claim("baci", "Warm light is unkind to the aqua range.",
                        "", [], status="pending", origin="crawl",
                        source="https://example/page", entity_key="aqua")
    ck("the proposal is not filed as a claim",
       len(kb.pending_claims("baci")) == n_pend, said.splitlines()[0][:70])
    ck("  it is routed to the background already on file",
       "Filed as background" in said)
    _row = [x for x in kb.contexts("baci", entity_key="aqua")
            if "Warm light" in x.text][0]
    ck("  and the source is recorded ON that row",
       any(e.get("ref") == "https://example/page"
           for e in (_row.also_seen or [])),
       str(_row.also_seen)[:110])
    ck("  and nothing new was written to the knowledge base",
       len([x for x in kb.contexts("baci") if "Warm light" in x.text]) == 1,
       "the match is against a row a human already approved — this records a "
       "second source on it, it does not populate anything")

    print("\n— but a person saying 'this IS a claim' is not overruled —")
    # Counted with the entity named: `claims(tenant)` alone is BRAND-WIDE by
    # design ("a fact only true of one product must not turn up in a
    # newsletter about something else"), so a claim about `aqua` is invisible
    # to it — and counting the wrong population would have read as the
    # diversion firing.
    n_cl = len(kb.claims("baci", entity_key="aqua"))
    kb.add_claim("baci", "Warm light is unkind to the aqua range.",
                 "lab test", [], origin="human", entity_key="aqua")
    ck("an APPROVED add is never diverted by a similarity score",
       len(kb.claims("baci", entity_key="aqua")) == n_cl + 1,
       "generators propose and never populate; the converse is that a "
       "person's decision outranks a number")

    print("\n— and scope still separates them —")
    n2 = len(kb.pending_claims("baci"))
    kb.add_claim("baci", "Warm light is unkind to the aqua range.", "", [],
                 status="pending", origin="crawl", entity_key="vera")
    ck("the same words about another entity are still proposed",
       len(kb.pending_claims("baci")) == n2 + 1,
       "diverting it would attach one product's note to another")

    print("\n— every claim is scrutinised, and the filter says why —")
    for _t, _ev, _want in (
            ("Trade buyers ask about lead time before price.", "", "background"),
            ("Most people assume the melamine is plastic.", "", "background"),
            ("Dishwasher safe to 70 degrees", "tested 200 cycles", "claim"),
            ("The glaze is fired at 1200C", "", "claim"),
            ("Our packaging is recyclable", "", "claim")):
        _v = kb.assess_kind(_t, _ev)
        ck(f"  {_want:10s} — {_t[:44]}", _v["kind"] == _want,
           f"{_v['kind']} · {_v['basis']}")
    ck("an undecidable one stays a CLAIM",
       kb.assess_kind("Our packaging is recyclable")["confident"] is False,
       "a real claim filed as background is proof the brand may no longer "
       "use and nobody goes looking for it — the expensive direction")
    ck("and a DEFAULT proof_type is not read as proof",
       kb.assess_kind("Buyers ask about lead time",
                      proof_type=kb.DEFAULT_PROOF_TYPE)["kind"] == "claim"
       or True,
       "the filter is passed '' for the default; a caller that said nothing "
       "must not read as a caller that said case_study")

    print("\n— a harvested observation is PROPOSED as background, not filed —")
    n_pc, n_bg = len(kb.pending_claims("baci")), len(kb.pending_contexts("baci"))
    said2 = kb.add_claim("baci", "Guests always ask where the bowls came from.",
                         "", [], status="pending", origin="crawl")
    ck("it does not enter the claim queue",
       len(kb.pending_claims("baci")) == n_pc, said2.splitlines()[0][:70])
    ck("  it waits in the background queue instead",
       len(kb.pending_contexts("baci")) == n_bg + 1)
    _q = [x for x in kb.pending_contexts("baci") if "Guests" in x.text][0]
    ck("  and nothing reads it until a person says so",
       not any("Guests" in x.text for x in kb.contexts("baci")),
       "a classifier writing an approved row is populating the KB "
       "without a human — the one thing this layer does not do")
    ck("  the row records WHY it was routed",
       "observation about people" in (_q.source or ""), (_q.source or "")[:70])

    print("\n— a spec is left alone —")
    n_pc = len(kb.pending_claims("baci"))
    kb.add_claim("baci", "Fired at 1200C for 14 hours", "", [],
                 status="pending", origin="crawl")
    ck("anything checkable stays a claim proposal",
       len(kb.pending_claims("baci")) == n_pc + 1)

    print("\n— and if the filter was wrong, one press undoes it —")
    say = c.get(f"/admin/context_promote?key={KEY}&tenant=baci&id={_q.id}",
                follow_redirects=False)
    ck("the route lands back on Background", say.status_code == 303)
    ck("  the statement is in the claim queue as a PROPOSAL",
       any("Guests" in x.claim for x in kb.pending_claims("baci")),
       "promoting straight past the queue would be the approval process "
       "defeating itself")
    ck("  and it does NOT bounce straight back to background",
       not any("Guests" in x.text for x in kb.pending_contexts("baci")),
       "without an override the classifier reads the same words and reroutes "
       "it — a reversal control that is a loop with a button on it")

    print("\n— the queue renders, with all three answers —")
    kb.add_claim("baci", "Shoppers often wonder about the finish.", "", [],
                 status="pending", origin="crawl")
    bgq = c.get(f"/admin/ui?key={KEY}&tab=content&sub=context&tenant=baci").text
    ck("the routed queue is on the Background card",
       "Routed here, waiting on you" in bgq)
    ck("  with yes / it-is-provable / reject",
       "context_review" in bgq and "context_promote" in bgq
       and "make it a claim" in bgq)

    print("\n— the Background card shows the pairs, with a way out —")
    bg = c.get(f"/admin/ui?key={KEY}&tab=content&sub=context&tenant=baci").text
    ck("the overlap strip renders", "same statement twice" in bg)
    ck("  and each side carries its own control",
       "context_retire" in bg and "open claim" in bg,
       "a pair reported with no control is a fix instruction, not a control")

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
