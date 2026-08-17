"""A skill that cannot be governed is a script with extra steps.

What this proves, in order of how badly it would hurt to get wrong:

  * **No output escapes the validator.** `Context.emit` is the only exit, and
    a banned phrase coming back through a skill body is still blocked.
  * **`empty` is not `blocked`.** A sweep that found nothing and a sweep that
    could not run must not arrive the same way. This codebase has collapsed
    absence into a value five times (DEFECTS 2.5, 2.6, 2.11, 2.24) and this is
    the sixth place it could.
  * **A field that could not be read is not a clean field.** The metafield
    read failing must never be reported as "no violation here".
  * **The rung decides disposition, the validator outranks the rung.** `auto`
    does not mean "send the thing that failed".
  * **Every run leaves a row**, including the blocked ones, because
    `blocked_reasons()` is the KB backlog and it is only as good as what got
    recorded.

    python3 scripts/test_skill.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sk.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, ledger, skill, skill_pack, systems, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CLEAN = {"id": "1", "handle": "aqua-plate", "title": "Aqua Plate",
         "body": "A generous 32 cm plate.", "seo_title": "Aqua Plate",
         "seo_description": "Aqua Plate from an Italian design house.",
         "status": "active"}
DIRTY = {"id": "2", "handle": "gipsy-bowl", "title": "Gipsy Bowl",
         "body": "Hand-decorated in Italy by our artisans.",
         "seo_title": "Gipsy Bowl",
         "seo_description": "Hand-decorated bowl, made in Italy.",
         "status": "active"}
ASKS = {"id": "3", "handle": "faq-mug", "title": "FAQ Mug",
        "body": "Is it made in Italy? It is Italian-designed.",
        "seo_title": "FAQ Mug", "seo_description": "An Italian-designed mug.",
        "status": "active"}
UNREAD = {"id": "4", "handle": "ghost-cup", "title": "Ghost Cup",
          "body": "A cup.", "seo_title": None, "seo_description": None,
          "status": "active"}


def _draft_ad_live_unavailable(bundle, claim, angle, objections):
    """What `_draft_ad_live` returns with no key — the honest offline case."""
    return "", "ANTHROPIC_API_KEY is not set"


def _fake_model(text):
    """Stand in for the model so the gate around it can be tested.

    The point is not to test the model. It is to prove that whatever comes back
    from it is still checked — including when what comes back is a banned claim.
    """
    def _f(bundle, claim, angle, objections):
        return text, ""
    return _f


def fake_fetch(products, total=None, complete=False):
    def _f(profile, limit):
        return list(products), {"scanned": len(products),
                                "catalogue_total": total, "complete": complete}
    return _f


# `capabilities` is credential-backed and there are no credentials offline, so
# the connection check is stubbed at its boundary. Stubbing it rather than
# loosening `catalog_compliance.requires` keeps the production gate honest: a
# real account with no Shopify still cannot run this skill.
_ALL_WIRED = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL_WIRED) if tenants.get(key) else \
    {c: False for c in tenants.CAPABILITIES}


def seed(tenant, banned=(), claim=""):
    kb.ensure_brand(tenant, tenant.title())
    kb.set_brand(tenant, positioning="Italian-designed tableware.",
                 tone="direct, warm")
    for p in banned:
        kb.add_banned(tenant, p)
    if claim:
        # An untagged claim can never be selected, and `add_claim` says so in
        # its return rather than raising. The first version of this helper
        # dropped that return on the floor and every claim silently vanished —
        # DEFECTS §2.1 exactly, in the harness written to catch it. The count
        # is asserted for that reason.
        kb.add_situation(tenant, "quality", patterns=[["quality"]],
                         description="Is it any good?", origin="seed")
        before = len(kb.claim_inventory(tenant)["selectable"])
        said = kb.add_claim(tenant, claim, "brand brief 2026", ["quality"],
                            origin="human", status="active")
        after = len(kb.claim_inventory(tenant)["selectable"])
        assert after == before + 1, f"claim did not land: {said!r}"
    # The validator resolves an entity by key, and `catalog_sync` keys one on
    # the lowercased product handle — so the fixture products must exist as
    # entities exactly as they would after a real sync.
    for p in (CLEAN, DIRTY, ASKS, UNREAD):
        kb.add_entity(tenant, "product", p["handle"], p["title"],
                      description=p["body"], origin="seed")
    return (systems.find(tenant, "catalog_compliance")
            or systems.create(tenant, "catalog_compliance"))


def contract(row, autonomy="shadow", live=True):
    """Fill the 8-part contract so `ready()` stops blocking on it.

    Two calls, deliberately: `update` refuses to set `status="live"` while the
    contract is still empty, which is the gate doing its job. Both returns are
    asserted — a helper that ignored them would be DEFECTS §1 silent loss in
    the test harness itself, and every assertion after it would be meaningless.
    """
    first = systems.update(row.id,
                           **{f: "declared for the test"
                              for f, _l, _h in systems.CONTRACT})
    assert first.get("ok"), f"contract fill refused: {first}"
    if live:
        second = systems.update(row.id, status="live", autonomy=autonomy)
        assert second.get("ok"), f"go-live refused: {second}"
    return systems.get(row.id)


# ---------------------------------------------------------------------------

def main():
    db.init_db()
    tenants.seed()

    print("\n--- registry ---")
    ck("four skills registered", len(skill.REGISTRY) >= 4,
       ", ".join(sorted(skill.REGISTRY)))
    ck("every skill names a system in the catalogue",
       all(s.system_key in systems.CATALOG for s in skill.REGISTRY.values()),
       str([s.system_key for s in skill.REGISTRY.values()]))

    print("\n--- refusals are named, before any work happens ---")
    r = skill.run("no_such_skill", "baci")
    ck("unknown skill is refused, not crashed", r["status"] == "refused")
    ck("  and the known ones are listed",
       "no skill keyed" in r["blocked_on"][0])

    r = skill.run("catalog_compliance", "nobody")
    ck("unknown account is refused", r["status"] == "refused")

    row = seed("baci", banned=("made in Italy", "hand-decorated", "artisan"),
               claim="Designed in Milan and produced at scale")
    r = skill.run("catalog_compliance", "baci")
    ck("an incomplete contract blocks the run", r["status"] == "blocked")
    ck("  and names the contract, not 'error'",
       any("contract" in b for b in r["blocked_on"]), str(r["blocked_on"]))

    row = contract(row)
    r = skill.run("catalog_compliance", "baci", nonsense=1)
    ck("an unknown parameter is refused, never ignored",
       r["status"] == "refused" and "nonsense" in r["blocked_on"][0])

    print("\n--- the sweep ---")
    skill_pack.fetch_products = fake_fetch([CLEAN], total=1, complete=True)
    r = skill.run("catalog_compliance", "baci")
    ck("a clean catalogue reports EMPTY, not blocked", r["status"] == "empty",
       r["status"])
    ck("  and emits nothing", not r["items"])

    skill_pack.fetch_products = fake_fetch([CLEAN, DIRTY], total=2, complete=True)
    r = skill.run("catalog_compliance", "baci")
    ck("a dirty catalogue produces a report", r["status"] == "produced")
    groups = r["detail"]["groups"]
    ck("  violations are grouped by field and phrase", bool(groups))
    ck("  the SEO description breach is found",
       any(g["field"] == "seo_description" for g in groups),
       str([g["field"] for g in groups]))
    ck("  the body breach is found too",
       any(g["field"] == "body" for g in groups))

    skill_pack.fetch_products = fake_fetch([ASKS], total=1, complete=True)
    r = skill.run("catalog_compliance", "baci")
    ck("a QUESTION about a banned phrase is not a violation",
       r["status"] == "empty",
       str([f["kind"] for f in r["detail"]["findings"]]))
    ck("  but it is still surfaced for review",
       any(f["kind"] == "review" for f in r["detail"]["findings"]))

    skill_pack.fetch_products = fake_fetch([UNREAD], total=1, complete=True)
    r = skill.run("catalog_compliance", "baci")
    ck("an unreadable field is NOT reported as clean",
       bool(r["detail"]["unread"]), str(r["detail"]["unread"]))
    ck("  and the operator is told", any("not counted as clean" in n
                                         for n in r["notes"]))

    skill_pack.fetch_products = fake_fetch([CLEAN], total=900, complete=False)
    r = skill.run("catalog_compliance", "baci")
    ck("partial coverage is stated, never implied complete",
       any("of 900" in n for n in r["notes"]), str(r["notes"]))

    print("\n--- the validator cannot be bypassed ---")
    def _rogue(ctx):
        return ctx.emit("This is hand-decorated in Italy by our artisans.",
                        require_citation=False)
    rogue = skill.Skill(key="_rogue", name="rogue", does="tries to smuggle",
                        system_key="catalog_compliance", tier=1,
                        needs=(), params=(), run=_rogue)
    skill.register(rogue)
    r = skill.run("_rogue", "baci")
    ck("a skill body cannot return an unchecked draft",
       r["items"] and r["items"][0]["status"] == "blocked",
       str(r["items"][0]["failures"] if r["items"] else "no item"))
    ck("  and the failure names the phrase",
       any(f["rule"] == "banned_claim" for f in r["items"][0]["failures"]))

    print("\n--- the rung decides, the validator outranks it ---")
    contract(row, autonomy="auto")
    r = skill.run("_rogue", "baci")
    ck("`auto` does not clear a draft that failed the check",
       r["items"][0]["disposition"] == "blocked",
       r["items"][0]["disposition"])

    def _fine(ctx):
        return ctx.emit("Designed in Milan.", require_citation=False)
    skill.register(skill.Skill(key="_fine", name="fine", does="clean output",
                               system_key="catalog_compliance", tier=1,
                               needs=(), params=(), run=_fine))
    r = skill.run("_fine", "baci")
    ck("`auto` clears a draft that passed",
       r["items"][0]["disposition"] == "cleared",
       r["items"][0]["disposition"])
    contract(row, autonomy="shadow")
    r = skill.run("_fine", "baci")
    ck("`shadow` records and does not release",
       r["items"][0]["disposition"] == "recorded")
    contract(row, autonomy="approve_all")
    r = skill.run("_fine", "baci")
    ck("`approve_all` asks", r["items"][0]["disposition"] == "needs_approval")
    contract(row, autonomy="approve_exceptions")
    r = skill.run("_fine", "baci")
    ck("`approve_exceptions` clears a read-only skill",
       r["items"][0]["disposition"] == "cleared")

    print("\n--- the rewrite ---")
    contract(row, autonomy="shadow")
    skill_pack.fetch_products = fake_fetch([DIRTY], total=1, complete=True)
    r = skill.run("catalog_seo_rewrite", "baci")
    ck("a replacement is drafted", r["status"] == "produced", r["status"])
    item = r["items"][0]
    ck("  it cites the claim it was composed from", bool(item["claim_ids"]))
    ck("  it passes the ban list it was written to fix", item["ok"],
       str(item["failures"]))
    ck("  it fits a meta description", len(item["body"]) <= 155,
       f"{len(item['body'])} chars: {item['body']}")
    ck("  it names where it would be written",
       "description_tag" in (ledger.recent("baci", "catalog_compliance", 1)[0]
                             .destination or ""))
    ck("  a WRITING skill still needs approval at approve_exceptions",
       skill._disposition("approve_exceptions", True, writes=True)
       == "needs_approval")

    print("\n--- the rewrite refuses rather than inventing proof ---")
    # coverings is deliberately thin: rules, but nothing approved to say.
    contract(seed("coverings", banned=("made in Italy", "hand-decorated")))
    skill_pack.fetch_products = fake_fetch([DIRTY], total=1, complete=True)
    r = skill.run("catalog_seo_rewrite", "coverings")
    ck("with no approved claim, nothing is drafted", not r["items"])
    ck("  and the product is named as the authoring backlog",
       bool(r["detail"].get("unwritable")), str(r["detail"].get("unwritable")))

    print("\n--- an account with no ban list cannot be swept at all ---")
    # It cannot even go live: `catalog_compliance` declares banned_claims as a
    # kb_need, so the go-live gate refuses first. That is the earlier and
    # better refusal, and it is asserted here rather than worked around.
    nrow = seed("eien")
    live = systems.update(nrow.id, status="live")
    ck("an account with no ban list cannot even go live",
       live.get("error") == "not ready to go live",
       str(live))
    nrow = contract(nrow, live=False)
    r = skill.run("catalog_compliance", "eien")
    ck("no ban list blocks the skill", r["status"] == "blocked", r["status"])
    ck("  and says the validator would have nothing to check against",
       any("banned_claims" in b or "ban list" in b for b in r["blocked_on"]),
       str(r["blocked_on"]))

    print("\n--- an untagged claim is inferred, never refused ---")
    # The write gate used to refuse an untagged approved claim on the premise
    # that it "can never be selected". `claims()` says otherwise: it filters on
    # situation only when a caller asks for one, so untagged proof is
    # brand-wide proof. Refusing it threw away real evidence.
    n0 = len(kb.claim_inventory("baci")["selectable"])
    said = kb.add_claim("baci", "Dishwasher safe at 65 degrees.",
                        "lab report 2026", [], origin="human", status="active")
    n1 = len(kb.claim_inventory("baci")["selectable"])
    ck("an untagged claim lands instead of being refused", n1 == n0 + 1,
       said.splitlines()[0] if said else "")
    ck("  and the return says what happened to its situations",
       "inferred" in said or "brand-wide proof" in said, said)
    untagged = [c for c in kb.claim_inventory("baci")["selectable"]
                if c.claim.startswith("Dishwasher safe")]
    ck("  it is selectable when no situation is asked for",
       any(c.id == untagged[0].id for c in kb.claims("baci")) if untagged
       else False)

    print("\n--- ad copy: the model writes, the validator still decides ---")
    kb.add_audience("baci", "hosts", "Hosts who entertain",
                    ["dull tables"], ["colour", "set"], origin="human")
    ad = systems.find("baci", "ad_creative") or systems.create("baci", "ad_creative")
    ad = contract(ad, autonomy="shadow")
    gate = skill.preflight("ad_copy", "baci")
    ck("ad_copy is runnable once its system is installed",
       gate["status"] == "ready", str(gate.get("blocked_on")))

    # -- degraded: no API key in this session, which is the real offline case
    skill_pack.draft_ad = _draft_ad_live_unavailable
    r = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                  audience_key="hosts", variants=2)
    ck("with no model, it still produces something grounded",
       r["status"] == "produced", r["status"])
    ck("  and every variant admits it was composed, not written",
       all(i["meta"]["basis"].startswith("composed") for i in r["items"]),
       str([i["meta"]["basis"] for i in r["items"]]))
    ck("  the operator is told it is a placeholder, not ad copy",
       any("not ad copy" in n for n in r["notes"]), str(r["notes"]))

    # -- the model path
    skill_pack.draft_ad = _fake_model("Set a table people photograph.\n\n"
                                      "Designed in Milan, made to be used.")
    r = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                  audience_key="hosts", variants=2)
    ck("with a model, the model's words are what get filed",
       all(i["meta"]["basis"] == "model" for i in r["items"]),
       str([i["meta"]["basis"] for i in r["items"]]))
    ck("  each variant cites the one claim it was built from",
       all(len(i["claim_ids"]) == 1 for i in r["items"]))
    ck("  and they passed the ban list", all(i["ok"] for i in r["items"]),
       str([i["failures"] for i in r["items"]]))

    # -- the one that matters: the model is not trusted
    skill_pack.draft_ad = _fake_model("Every piece is hand-decorated by our "
                                      "artisans and made in Italy.")
    r = skill.run("ad_copy", "baci", entity_key="aqua-plate", variants=1)
    ck("a model that breaks the ban list is BLOCKED, not softened",
       r["items"] and r["items"][0]["status"] == "blocked",
       str(r["items"][0]["failures"] if r["items"] else "nothing emitted"))
    ck("  the blocked draft is still on the ledger, with its reason",
       ledger.recent("baci", "ad_creative", 1)[0].status == "blocked")
    skill_pack.draft_ad = skill_pack._draft_ad_live

    print("\n--- a rejection explains and adjusts, it does not queue a human ---")
    # A model that says the banned thing once, then fixes it when told.
    _tries = {"n": 0}

    def _self_correcting(bundle, claim, angle, objections):
        _tries["n"] += 1
        if "previous attempt was rejected" in str(bundle.get("rules", {})):
            return "Designed in Milan, made to be used every day.", ""
        return "Every piece is hand-decorated by our artisans.", ""

    skill_pack.draft_ad = _self_correcting
    r = skill.run("ad_copy", "baci", entity_key="aqua-plate", variants=1)
    it = r["items"][0]
    ck("a banned draft is repaired rather than left for someone to rewrite",
       it["ok"] and it["repairs"] == 1, f"ok={it['ok']} repairs={it['repairs']}")
    ck("  the rule was NOT relaxed — the final text is genuinely clean",
       "hand-decorated" not in it["body"].lower(), it["body"][:60])
    ck("  the rejected attempt is kept, so the repair is auditable",
       it["repair_history"] and "hand-decorated"
       in it["repair_history"][0]["body"].lower())
    ck("  and it is filed as 'repaired', not 'blocked' — a self-correction "
       "must not inflate the KB backlog",
       ledger.recent("baci", "ad_creative", 5)[1].status == "repaired",
       ledger.recent("baci", "ad_creative", 5)[1].status)

    # A model that keeps rewording and keeps breaking the same rule.
    _n = {"i": 0}

    def _never_learns(bundle, claim, angle, objections):
        _n["i"] += 1
        return f"Truly hand-decorated, version {_n['i']}.", ""

    skill_pack.draft_ad = _never_learns
    r = skill.run("ad_copy", "baci", entity_key="aqua-plate", variants=1)
    it = r["items"][0]
    ck("a draft that cannot be fixed is still blocked", it["status"] == "blocked")
    ck("  and it gives up after MAX_REPAIRS, not forever",
       it["repairs"] == skill.MAX_REPAIRS, str(it["repairs"]))

    # A drafter that returns the same string is not repairing; spending the
    # remaining attempt on it buys latency and API spend, not a better answer.
    skill_pack.draft_ad = _fake_model("Truly hand-decorated, made in Italy.")
    r = skill.run("ad_copy", "baci", entity_key="aqua-plate", variants=1)
    ck("an unchanged redraft stops the loop immediately",
       r["items"][0]["repairs"] == 1, str(r["items"][0]["repairs"]))

    # An unfixable-by-wording failure names the knowledge instead.
    skill_pack.draft_ad = _fake_model("A plate we have no proof about at all.")
    r = skill.run("ad_copy", "baci", entity_key="ghost-sku", variants=1)
    if r["items"]:
        it = r["items"][0]
        ck("when no rewrite can work, it names the MISSING KNOWLEDGE",
           bool(it["needs"]), str(it["failures"])[:90])
        ck("  and says why, so the fix lands in the KB not in this one draft",
           all(n.get("why") for n in it["needs"]),
           str(it["needs"])[:110])
        ck("  the operator note points at the gap, not at a review queue",
           any("repair attempt" in n for n in r["notes"]), str(r["notes"])[-140:])
    skill_pack.draft_ad = skill_pack._draft_ad_live

    print("\n--- every run is on the record, blocked ones included ---")
    runs = systems.runs(row.id, limit=100)
    ck("runs were recorded", len(runs) >= 5, f"{len(runs)} runs")
    blocked_runs = [x for x in systems.runs(nrow.id, limit=10) + runs
                    if x.stage == "blocked" and x.blocked_on]
    ck("  blocked runs carry their reason", bool(blocked_runs),
       f"{len(blocked_runs)} blocked run(s) with a recorded reason")
    with db.SessionLocal() as s:
        outs = s.query(db.Output).filter(db.Output.tenant == "baci").count()
    ck("outputs were ledgered", outs > 0, f"{outs} rows")

    print("\n--- the catalogue an agent is shown ---")
    cat = skill.catalogue("baci")
    ck("each entry states whether it can run here",
       all("status" in c for c in cat))
    blocked = [c for c in cat if c["status"] == "blocked"]
    ck("  a blocked skill names what is missing",
       all(c["blocked_on"] for c in blocked), str(blocked[:1]))

    print()
    if _fail:
        print(f"FAILED {len(_fail)}: " + "; ".join(_fail))
        return 1
    print("all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
