"""A claim knows what it is about — on entry, in selection, and in the ad.

THE ZODIAC BATCH, 2026-09-07. The owner made an ad for the Libra Zodiac Vibe
cup — a porcelain cup with lid and saucer — and got: *"This is 18 pieces chosen
so you don't have to guess … Shatterproof, so she takes it outside."* Zodiac
cups are not shatterproof. The batch record shows how:

  entity_key  cup-with-lid-saucer-libra-zodiac-vibe        (correct — he picked it)
  variant 1   claim "yes. it is shatterproof and suited to indoor & outdoor use."
  variant 2   claim "Designed in Milan by the Italian design house Baci Milano"

Three holes, each reproduced below on today's code before it is fixed:

  ENTRY.  `email_harvest` files a harvested support reply with no entity, so
          it becomes a BRAND-WIDE proposal. The approval gate already refuses
          an unscoped machine-origin answer — for `kind == "objection"` only.
          Claims skip the rule that was written for exactly this sentence.
  SELECT. `claims()` ranks by specificity and then the rotation key re-sorts
          the whole list by last-used, discarding specificity. A cup's own
          claim, used once, sorts behind a never-used acrylic answer.
  AD.     The ad run builds concept N from claim N in that order, so concept 1
          was "shatterproof"; and an entity with no claims of its own becomes
          a brand mood piece with nothing saying so.

    python3 scripts/test_a_claim_knows_what_it_is_about.py
"""
from __future__ import annotations

import ast
import inspect
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ck.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import db, email_harvest, kb, skill, skill_pack, systems, tenants  # noqa: E402

_fail: list[str] = []
ZODIAC = "cup-libra-zodiac"
SHATTER = "yes. it is shatterproof and suited to indoor & outdoor use."
BY_SIGN = "The Zodiac Vibe cup is sold by sign — the piece is chosen for the person."


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else \
    {c: False for c in tenants.CAPABILITIES}
LOG: list[tuple] = []


class FakePanel:
    def __init__(self):
        self.concepts: list = []
        self.bundles: list = []

    def __call__(self, bundle, concepts):
        LOG.append(("panel", len(concepts)))
        self.concepts.append(list(concepts))
        self.bundles.append(bundle)
        return ({"variants": {c["n"]: {"hormozi": "h", "piliero": "p",
                                       "brief": f"PANELBRIEF-{c['n']}"}
                              for c in concepts},
                 "batch": {"piliero": "distinct", "verdict": "distinct"}}, "")


class FakeDraft:
    def __init__(self):
        self.n = 0

    def __call__(self, bundle, claim, angle, objections):
        self.n += 1
        return (f"HEADLINE: Which host are you\nLEVERS: dream_outcome, effort\n---\n"
                f"Ad line {self.n}: {str(claim.get('claim') or '')[:40]}\n\n"
                f"Tap to shop it.", "")


def contract(row, autonomy):
    systems.update(row.id, **{f: "declared for the test"
                              for f, _l, _h in systems.CONTRACT})
    systems.update(row.id, status="live", autonomy=autonomy)
    return systems.get(row.id)


def _claim_id(text: str) -> str:
    with db.SessionLocal() as s:
        row = (s.query(db.KbClaim).filter(db.KbClaim.tenant == "baci",
                                          db.KbClaim.claim == text).first())
        return row.id if row else ""


def _mark_used(claim_id: str):
    with db.SessionLocal() as s:
        s.add(db.Output(tenant="baci", system_key="ad_creative", format="ad_copy",
                        status="published", body="went out", claim_ids=[claim_id]))
        s.commit()


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.set_brand("baci", positioning="Italian-designed tableware.", tone="direct")
    kb.add_banned("baci", "hand-decorated")
    kb.add_audience("baci", "hosts", "Hosts who entertain", ["dull tables"],
                    ["colour"], origin="human")
    kb.add_entity("baci", "product", ZODIAC, "Cup with Lid/Saucer - Libra - Zodiac Vibe",
                  description="Porcelain cup with lid and saucer.", origin="human")
    kb.add_entity("baci", "product", "plain-plate", "Plain Plate",
                  description="A plate with no claims on file.", origin="human")

    # ── ENTRY ────────────────────────────────────────────────────────────────
    print("— ENTRY: a harvested answer with no scope cannot be approved brand-wide —")
    kb.add_claim("baci", SHATTER, "said in an email thread about the acrylic set",
                 [], origin="email", status="pending")
    sid = _claim_id(SHATTER)
    ck("the harvested reply is filed as a PROPOSAL with no entity", bool(sid), "")
    sig = inspect.signature(kb.review_claim).parameters
    said = kb.review_claim(sid, approve=True)
    ck("approving it brand-wide with no scope is REFUSED, as it is for an objection",
       "scope" in str(said).lower() or "true of" in str(said).lower(),
       f"got: {str(said)[:90]!r}")
    ck("  and the refusal says what to do — pick the item, or tick brand-wide",
       "brand" in str(said).lower() and ("pick" in str(said).lower()
                                        or "tick" in str(said).lower()), "")
    if "brand_wide" in sig:
        said2 = kb.review_claim(sid, approve=True, brand_wide=True)
        ck("  a person saying 'really brand-wide' is allowed through",
           "refus" not in str(said2).lower() and "scope" not in str(said2).lower(),
           str(said2)[:80])
    else:
        ck("  review_claim can take the brand-wide decision", False,
           f"params: {list(sig)}")

    # ── SELECT ───────────────────────────────────────────────────────────────
    print("\n— SELECT: the cup's own claim leads, however recently it was used —")
    kb.add_claim("baci", "Designed in Milan by the Italian design house Baci Milano.",
                 "brand file", [], origin="human", status="active")
    kb.add_claim("baci", BY_SIGN, "product page", [], origin="human",
                 status="active", entity_key=ZODIAC)
    zid = _claim_id(BY_SIGN)
    ck("the cup has a claim of its own on file", bool(zid), "")
    first_free = kb.claims("baci", entity_keys=[ZODIAC])
    ck("with no rotation pressure, specificity already puts it first",
       first_free and first_free[0].id == zid,
       str([(c.entity_key or 'brand', c.claim[:24]) for c in first_free[:3]]))
    _mark_used(zid)                       # the cup's claim went out once
    pressed = kb.claims("baci", entity_keys=[ZODIAC], limit=1)
    ck("USED ONCE and under a limit, the cup's own claim STILL leads — rotation "
       "must rotate within a specificity tier, never across tiers",
       pressed and pressed[0].id == zid,
       str([(c.entity_key or 'brand', c.claim[:24]) for c in pressed]))
    brand_only = kb.claims("baci", limit=1)
    ck("  and a brand-wide query with no subject still rotates as before",
       brand_only and brand_only[0].id != zid, "rotation is right where there is no subject")

    # ── AD ───────────────────────────────────────────────────────────────────
    # ROTATION PRESSURE, as in production: Baci carries dozens of brand-wide
    # claims, so `len(out) > limit` is true and the re-sort fires. With three
    # claims it did not, and this section passed on today's code for the
    # wrong reason. The direct `claims()` assertion above is the one that
    # reproduced the defect; this one proves the fix holds one layer up.
    for i in range(12):
        kb.add_claim("baci", f"Brand-wide fact number {i} about Baci Milano.",
                     "brand file", [], origin="human", status="active")
    print("\n— AD: concept 1 is built on the cup's own claim —")
    row = systems.find("baci", "ad_creative") or systems.create("baci", "ad_creative")
    contract(row, autonomy="approve_all")
    fp = FakePanel()
    skill_pack.panel_ad, skill_pack.draft_ad = fp, FakeDraft()
    skill_pack.panel_check = lambda b, d: ({}, "")
    r = skill.run("ad_copy", "baci", entity_key=ZODIAC, audience_key="hosts", variants=2)
    ck("the run produced", r.get("status") == "produced", f"{r.get('status')} {r.get('blocked_on')}")
    c1 = (fp.concepts[0][0]["claim"] if fp.concepts else {})
    ck("concept 1's claim is the CUP's claim, not a brand-wide one",
       c1.get("claim_id") == zid, f"concept 1 = {str(c1.get('claim'))[:50]!r}")
    print("\n— AD: an entity with no claim of its own is SAID, not silently a mood piece —")
    fp2 = FakePanel()
    skill_pack.panel_ad = fp2
    r2 = skill.run("ad_copy", "baci", entity_key="plain-plate", audience_key="hosts", variants=2)
    notes = " ".join(str(n) for n in (r2.get("notes") or []))
    ck("the run says the entity has no claim on file and every concept is brand-wide",
       "no claim" in notes.lower() and "plain plate" in notes.lower(),
       f"notes: {notes[:120]!r}")

    # ── CONSOLE ──────────────────────────────────────────────────────────────
    print("\n— CONSOLE: the refusal has an answer on the queue, not only in an editor —")
    from fastapi.testclient import TestClient
    from app import web as _web
    kb.add_claim("baci", "yes. the lids are sold separately.", "said in an email",
                 [], origin="email", status="pending")
    lid = _claim_id("yes. the lids are sold separately.")
    c = TestClient(_web.app)
    r_no = c.post("/admin/claims_decide?key=s3cret",
                  data={"tenant": "baci", "action": "approve", "claim_ids": [lid]},
                  follow_redirects=False)
    with db.SessionLocal() as s:
        row = s.get(db.KbClaim, lid)
        still_proposed = (row.review or "") != kb.prov.APPROVED
    ck("approving an unscoped machine claim from the queue WITHOUT the box does not approve it",
       r_no.status_code in (200, 303) and still_proposed,
       f"status={r_no.status_code} review={row.review!r}")
    # WHILE IT IS STILL PENDING: the bulk bar — and the box on it — renders only
    # when the queue has rows. The first version fetched the page after the
    # approval below had emptied the queue and reported the box missing.
    page = c.get("/admin/ui?key=s3cret&tab=content&sub=claims&tenant=baci").text
    ck("  the box is on the claims queue, on the bulk form, while a proposal is pending",
       'name="brand_wide"' in page and 'form="bulk"' in page, "")
    r_yes = c.post("/admin/claims_decide?key=s3cret",
                   data={"tenant": "baci", "action": "approve", "claim_ids": [lid],
                         "brand_wide": "1"}, follow_redirects=False)
    with db.SessionLocal() as s:
        row = s.get(db.KbClaim, lid)
        now_approved = (row.review or "") == kb.prov.APPROVED
    ck("  and WITH the box it is approved — a person made the scope decision",
       r_yes.status_code in (200, 303) and now_approved,
       f"status={r_yes.status_code} review={row.review!r}")

    # ── HARVEST ──────────────────────────────────────────────────────────────
    print("\n— HARVEST: a mined reply carries the product the thread was about —")
    ck("email_harvest.entity_for exists", hasattr(email_harvest, "entity_for"), "")
    if hasattr(email_harvest, "entity_for"):
        got = email_harvest.entity_for("baci", "Hi — is the Zodiac Vibe cup dishwasher safe? Thanks")
        ck("  a thread naming the Zodiac Vibe cup resolves to its entity",
           got == ZODIAC, repr(got))
        ck("  a thread naming nothing resolves to nothing — never a guess",
           email_harvest.entity_for("baci", "Where is my order?") == "", "")
    src = open(os.path.join(ROOT, "app", "email_harvest.py")).read()
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
             and ast.unparse(n.func).endswith("add_claim")]
    ck("the mail harvester's add_claim call passes entity_key",
       calls and all(any(k.arg == "entity_key" for k in c.keywords) for c in calls),
       f"{len(calls)} call(s); kwargs: {[sorted(k.arg for k in c.keywords if k.arg) for c in calls]}")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
