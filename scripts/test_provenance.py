"""Three sources fill one knowledge base. This is what stops them fighting.

Every check below started as a measured defect in the write layer, not a
hypothetical. Before the provenance spine existed:

  1. Two of five KB tables had an approval state; the other three went live the
     instant anything wrote to them, a client's intake link included.
  2. `add_claim` and `add_objection` inserted unconditionally, so re-running a
     seed or a harvest duplicated every row it had already written.
  3. The same fact from a crawl and from an upload became two unrelated rows.
  4. Approval left no trace — no who, no when — so "approved is final" was a
     convention rather than a property of the row.
  5. `catalog_sync` decided ownership by testing `source not in ("shopify","")`,
     so owner-approved copy on a store-supplied row was overwritten next sync.

The invariant all five serve: **approved is final, and only approved is usable.**
A machine that disagrees with an approved row records a conflict and changes
nothing.

    python3 scripts/test_provenance.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pv.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, provenance as prov  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


db.init_db()
T = "probe"
kb.ensure_brand(T, "Probe Co")
kb.add_situation(T, "gifting", [["gift"]], "buying for someone else")


# --------------------------------------------------------------------------
print("\n— every table can hold an unapproved row —")
# The original hole: only claims and entities had any notion of review, so a
# client could redefine a buyer segment through an intake link and it was live
# before anyone read it.
for kind, model in (("claim", db.KbClaim), ("audience", db.KbAudience),
                    ("objection", db.KbObjection), ("entity", db.KbEntity),
                    ("situation", db.KbSituation)):
    cols = {c.name for c in model.__table__.columns}
    ck(f"{kind} carries provenance",
       {"origin", "review", "approved_by", "approved_at", "fingerprint"} <= cols)


# --------------------------------------------------------------------------
print("\n— a client proposes; they do not publish —")
kb.add_audience(T, "gift_buyer", "Gift buyer", ["price"], ["gift"],
                origin="client", source="submitted by Dana")
kb.add_objection(T, "Too expensive", "Here is the value.", origin="client")
ck("a client's audience is not usable", len(kb.audiences(T)) == 0)
ck("but it IS recorded", len(kb.audiences(T, include_proposed=True)) == 1)
ck("a client's objection is not usable", len(kb.objections(T)) == 0)
# The distinction that keeps an intake form finishable: the question has been
# answered even though the answer is not yet usable, so it is not re-asked.
ck("intake does not re-ask what they already answered",
   "objection" not in [g["id"] for g in kb.gaps(T)])
ck("readiness names the review, not an absence",
   any("waiting for review" in m for m in kb.completeness(T)["missing"]),
   str(kb.completeness(T)["missing"]))

aud = kb.audiences(T, include_proposed=True)[0]
ck("approving it makes it usable",
   "final" in kb.approve("audience", aud.id, by="gomeh")
   and len(kb.audiences(T)) == 1)
ck("and records who, and when",
   (kb.audiences(T)[0].approved_by == "gomeh"
    and kb.audiences(T)[0].approved_at is not None))


# --------------------------------------------------------------------------
print("\n— the same fact twice is one row —")
kb.add_claim(T, "Shipped 1,200 orders in 2025", "1,200", ["gifting"])
again = kb.add_claim(T, "Shipped 1,200 orders in 2025", "1,200", ["gifting"])
ck("a repeated claim does not duplicate", len(kb.claims(T)) == 1, again.splitlines()[0])

before = len(kb.objections(T, include_proposed=True))
kb.add_objection(T, "Too expensive", "Here is the value.", origin="client")
ck("a repeated objection does not duplicate",
   len(kb.objections(T, include_proposed=True)) == before)


# --------------------------------------------------------------------------
print("\n— two sources, one fact —")
# The crawl and the spreadsheet say the same thing in different words. One row,
# with both sources recorded: collapsing a duplicate must not lose the
# corroboration, which is the reason to have two sources at all.
msg = kb.add_claim(T, "We shipped 1200 orders in 2025.", "row 14 of specs.xlsx",
                   ["gifting"], origin="upload", source="specs.xlsx#14",
                   status="pending")
ck("a differently-worded identical fact collapses",
   len(kb.claims(T)) + len(kb.pending_claims(T)) == 1, msg.splitlines()[0])
row = kb.claims(T)[0]
ck("and both sources are kept",
   {e["origin"] for e in (row.also_seen or [])} == {"human", "upload"},
   str([e["origin"] for e in (row.also_seen or [])]))

ck("a genuinely different fact is NOT collapsed",
   "Added" in kb.add_claim(T, "Shipped 4,000 orders in 2026", "4,000", ["gifting"])
   and len(kb.claims(T)) == 2)

# Similar-but-not-identical is a human's call, never an automatic merge —
# merging two nearly-identical sentences invents a third that neither said.
A, B = "Shipped 1200 orders in 2025", "Shipped 1250 orders in 2025"
ck("a contradicting number is flagged as a near-duplicate",
   prov.similarity(A, B) >= prov.NEAR_DUPLICATE,
   f"{prov.similarity(A, B):.2f} vs threshold {prov.NEAR_DUPLICATE}")
ck("but never merged — the fingerprints differ",
   prov.fingerprint(A) != prov.fingerprint(B))


# --------------------------------------------------------------------------
print("\n— approved is final —")
ent = "aqua-set"
kb.add_entity(T, "product", ent, "Aqua Set", description="Store copy.",
              price="$100", origin="store_sync")
kb.add_entity(T, "product", ent, "Aqua Set",
              description="Gomeh's own wording.", origin="human")
e = kb.entities(T, available_only=False)[0]
ck("a human edit takes ownership of the row", e.origin == "human", e.origin)

res = kb.add_entity(T, "product", ent, "Aqua Set",
                    description="Store copy, changed again.", price="$120",
                    origin="store_sync")
e = kb.entities(T, available_only=False)[0]
ck("the store cannot overwrite approved copy",
   e.description == "Gomeh's own wording.", e.description)
ck("and says so rather than failing silently", "recorded" in res, res)
ck("but price still updates — the store owns it forever", e.price == "$120", e.price)

cf = prov.conflicts(T)
ck("the disagreement is on file", len(cf) == 1 and cf[0].field == "description")
ck("with both values kept",
   cf[0].approved_value == "Gomeh's own wording."
   and cf[0].incoming_value == "Store copy, changed again.")

# A nightly sync that keeps disagreeing must raise the count, not the row count.
kb.add_entity(T, "product", ent, "Aqua Set",
              description="Store copy, changed again.", origin="store_sync")
ck("a repeat disagreement counts, it does not pile up",
   len(prov.conflicts(T)) == 1 and int(prov.conflicts(T)[0].hits) == 2)

ck("resolving in the store's favour writes through",
   "updated" in prov.resolve_conflict(cf[0].id, "incoming")
   and kb.entities(T, available_only=False)[0].description
   == "Store copy, changed again.")
ck("and the conflict closes", not prov.conflicts(T))


# --------------------------------------------------------------------------
print("\n— a source may refresh its own row —")
# Without this a nightly catalogue sync would raise a conflict every time a
# product description changed, burying the conflicts that mean something.
kb.add_entity(T, "product", "mug", "Mug", description="First copy.",
              origin="store_sync")
kb.add_entity(T, "product", "mug", "Mug", description="Second copy.",
              origin="store_sync")
mug = [x for x in kb.entities(T, available_only=False) if x.key == "mug"][0]
ck("the store may update a row no human has touched",
   mug.description == "Second copy." and not prov.conflicts(T))


# --------------------------------------------------------------------------
print("\n— the review queue is one queue —")
kb.add_entity(T, "product", "bowl", "Bowl", origin="upload",
              source="specs.xlsx#22")
q = kb.proposals(T)
ck("proposals from every table land in one place",
   "entity" in q and len(q["entity"]) == 1, str(sorted(q)))
ck("nothing proposed is usable",
   not [x for x in kb.entities(T, available_only=False) if x.key == "bowl"])


# --------------------------------------------------------------------------
print("\n— a proposal cannot reach a generator by accident —")
# `review` has no column default on purpose: a row written without one is
# invisible to selection rather than silently usable.
with db.SessionLocal() as s:
    s.add(db.KbClaim(tenant=T, claim="ROW WITH NO REVIEW STATE",
                     evidence="none", situations=["gifting"], status="active"))
    s.commit()
ck("a row created without a review state is not selectable",
   not [c for c in kb.claims(T) if c.claim == "ROW WITH NO REVIEW STATE"])


# --------------------------------------------------------------------------
print("\n— similar wording is not the same fact —")
# Two products can carry facts that read alike and are not interchangeable.
# Treating those as duplicates would invite a reviewer to reject one and delete
# a real product's answer.
kb.add_entity(T, "product", "plate", "Plate", origin="store_sync")
kb.add_entity(T, "product", "pouf", "Pouf", origin="store_sync")
kb.add_claim(T, "Dishwasher safe on a normal cycle, all 6 pieces.", "6",
             ["gifting"], entity_key="plate")
kb.add_claim(T, "Dishwasher safe on a normal cycle, all 6 pieces.", "6",
             ["gifting"], entity_key="pouf", status="pending", origin="crawl")
kb.add_claim(T, "Every piece is tested to 2,000 dishwasher cycles.", "2,000",
             ["gifting"])
kb.add_claim(T, "Every piece is tested to 2,000 dishwasher cycles.", "2,000",
             ["gifting"], entity_key="plate", status="pending", origin="crawl")

by_ent = {e["row"].entity_key: e for e in kb.proposals(T, kind="claim")["claim"]}
ck("the same wording on another item is not a duplicate",
   not by_ent["pouf"]["near_duplicates"])
ck("it is surfaced as a parallel fact instead",
   len(by_ent["pouf"]["parallel_on_other_entities"]) == 1)
ck("a narrower copy of a brand-level claim IS redundant, and says so",
   len(by_ent["plate"]["covered_by_brand_level"]) == 1)

kb.review_claim(by_ent["pouf"]["row"].id, approve=False)
ck("a rejection does not carry to another item's identical claim",
   not kb.suggest_tags(T, "Dishwasher safe on a normal cycle, all 6 pieces.",
                       entity_key="plate")["similar_to_rejected"])
ck("but it does carry within the same item",
   bool(kb.suggest_tags(T, "Dishwasher safe on a normal cycle, all 6 pieces.",
                        entity_key="pouf")["similar_to_rejected"]))

print("\n— clearing out proposals from an older parser —")
before_usable = len(kb.claims(T))
kb.add_claim(T, "Junk the old parser thought was checkable 8217.", "",
             ["gifting"], status="pending", origin="crawl")
kb.add_objection(T, "An old proposal", "x", origin="client")

before_pending = len(kb.pending_claims(T))
dry = kb.purge_proposals(T)
ck("a dry run reports and deletes nothing",
   dry["total"] >= 2 and dry["dry_run"]
   and len(kb.pending_claims(T)) == before_pending,
   str(dry["deleted"]))

real = kb.purge_proposals(T, dry_run=False)
ck("the proposals are gone", not kb.pending_claims(T), str(real["deleted"]))
ck("approved rows are untouched", len(kb.claims(T)) == before_usable)
# Deleted, not rejected, and this is the reason: suggest_tags learns what a bad
# claim looks like from retired rows, so filing parser noise as "rejected"
# would teach the tagger that noise is what rejection looks like.
ck("and they leave no trace to poison the tagger",
   not [r for r in kb.claim_inventory(T)["retired"]
        if "old parser" in (r.claim or "")])
ck("scoped to one account by default",
   kb.purge_proposals("some-other-tenant")["total"] == 0)

# The console surface for the same thing. A queue filled by an older crawler is
# cleared in one action rather than card by card — but the route that deletes
# must be a POST. A GET that deletes is fired by a browser prefetch or a link
# preview, and this one is destructive.
import os as _os
_os.environ.setdefault("APPROVAL_SECRET", "s3cret")
from fastapi.testclient import TestClient  # noqa: E402
from app import admin_ui, kb_seed, tenants, web  # noqa: E402

tenants.seed(); kb_seed.seed_all()
kb.add_claim("baci", "Junk the old parser proposed 8217.", "", ["gifting"],
             status="pending", origin="crawl")
kb.add_objection("baci", "An old proposal", "x", origin="client")
approved_baci = len(kb.claims("baci"))

with TestClient(web.app) as cl:
    page = admin_ui.render_content("s3cret", "baci")
    ck("the console offers a one-click clear, with the count",
       "Clear all 2 proposals" in page)
    ck("and it is a POST, not a link",
       'action="/admin/purge_proposals"' in page and 'method="post"' in page)
    r = cl.get("/admin/purge_proposals",
               params={"key": "s3cret", "tenant": "baci", "dry_run": "0"})
    ck("the GET route cannot delete, even when asked to",
       r.json()["dry_run"] is True and len(kb.pending_claims("baci")) == 1)
    r = cl.post("/admin/purge_proposals", data={"tenant": "baci"},
                params={"key": "s3cret"}, follow_redirects=False)
    ck("the POST clears the whole queue",
       r.status_code == 303 and not kb.pending_claims("baci"))
    ck("and leaves approved rows alone", len(kb.claims("baci")) == approved_baci)
    ck("the button disappears once the queue is empty",
       "Clear all" not in admin_ui.render_content("s3cret", "baci"))

ck("an unauthenticated purge is refused",
   "unauthorized" in TestClient(web.app).post(
       "/admin/purge_proposals", data={"tenant": "baci"},
       params={"key": "wrong"}).text)

# ---------------------------------------------------------------------------
# The fingerprint had to agree with itself — found live on Baci
#
# These checks must sit ABOVE the summary below. Appended after it they still
# printed, still said FAIL, and still exited 0 — a test that cannot fail the
# run is decoration, and this file reports by falling off the end rather than
# from inside a main().
# ---------------------------------------------------------------------------
print("\n— an edited claim keeps a fingerprint a fresh add would produce —")
# Use a tag this tenant actually has. The first version of this test picked
# `collector` for the second add, which that vocabulary does not contain — so
# it was refused for an unrelated reason and the check failed while the code
# under test was correct. A test that fails for the wrong reason is worse than
# no test: it sent me looking for a bug I had already fixed.
_tag = sorted(kb.situations(T))[0]
kb.add_entity(T, "product", "set-5", "Set of 5", origin="human")
kb.add_claim(T, "This is sold as a set of 5 pieces.", "counted",
             [_tag], proof_type="data", source="t", origin="human",
             entity_key="set-5")
row = [c for c in kb.claims(T, entity_key="set-5")
       if c.claim.startswith("This is sold")][0]
kb.update_claim(row.id, evidence="counted twice")
again = kb.add_claim(T, "This is sold as a set of 5 pieces.", "counted",
                     [_tag], proof_type="data", source="t",
                     origin="human", entity_key="set-5")
ck("after an edit, the same claim is still recognised as a duplicate",
   "Already on file" in again,
   "update_claim wrote fingerprint(claim) where add_claim writes "
   "fingerprint(claim, entity_key) — so Baci has this row twice")

rep = kb.repair_fingerprints(T, apply=False)
ck("the repair reports without writing",
   rep["applied"] is False and "duplicate_groups" in rep)
ck("and it merges nothing",
   "nothing was merged" in rep["note"],
   "the surviving id is what every objection's claim_id points at")

print("\n— approval freezes a row whatever wrote it first —")
# may_write said "same origin may refresh", justified by "a human editing the
# row makes its origin theirs". True of update_claim; NOT of approve(), which
# leaves origin alone. So a machine-authored row a human APPROVED stayed
# machine-origin and that machine could overwrite the sign-off for ever.
ck("a proposed row is still refinable by its own source",
   prov.may_write("response", "agent", prov.PROPOSED, "agent"))
ck("but once approved, its author is locked out",
   not prov.may_write("response", "agent", prov.APPROVED, "agent"),
   "approve() does not change origin, so origin cannot be the guard")
ck("a human may still correct it",
   prov.may_write("response", "agent", prov.APPROVED, "human"))
ck("and a store sync may still refresh its own approved rows",
   prov.may_write("description", "store_sync", prov.APPROVED, "store_sync"),
   "250 products through a review queue is a queue nobody opens")

print()
if _fail:
    print(f"{len(_fail)} FAILED: {_fail}")
    raise SystemExit(1)
print("all checks passed")
