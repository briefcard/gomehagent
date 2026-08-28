"""Seed the DEMO database — the preview-before-push ritual's data.

There is no staging environment: every push to main is a production deploy.
The demo server (launch.json entry `gomehagent-demo`) is the answer — a local
instance against a throwaway database, clicked through before `ship.sh`. This
script gives it something to render.

v1 seeds the five accounts (the same `tenants.seed()` production uses) plus a
brand row per account so every tab has a spine to stand on. Representative
rows — plans, drafts, pending claims, pictures, conflicts, a defective run —
get added here the first time a step's preview needs them (INITIATIVE-
ui-overhaul §3 names the target set); each addition uses the module's own
public writer, never raw INSERTs, so the demo exercises the same code paths
production does.

Refuses to run against anything that does not look like a throwaway database,
because "seed the demo" pointed at production is a bad afternoon.

    DATABASE_URL=sqlite:////tmp/gomeh-demo.db python3 scripts/seed_demo.py
"""
import os
import sys

url = os.environ.get("DATABASE_URL", "")
if "sqlite" not in url or "demo" not in url:
    sys.exit("refusing: DATABASE_URL must be a sqlite database with 'demo' in "
             f"its name (got {url!r}) — this script is for the preview "
             "server, never a real database")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The demo must never spend: the ad batch below is produced by the REAL
# skill (its own public writer, per this file's rule), and with a key in the
# environment that would be a live model call from a seeding script. The
# composed fallback is the honest offline path — every variant carries
# basis='composed', which is itself worth previewing.
os.environ.pop("ANTHROPIC_API_KEY", None)

from app import config, db, kb, tenants  # noqa: E402

config.ANTHROPIC_API_KEY = ""

db.init_db()
made = tenants.seed()
for t in tenants.all_tenants():
    kb.ensure_brand(t.key, t.name)


def seed_ad_batch() -> str:
    """One representative ad batch for baci — the step-3.4 board's preview.

    Through the real writers end to end: KB rows land via kb.*, the system
    goes live at approve_all via systems.update (so the batch queues real
    approvals for the ship queue), and the batch itself is produced by
    skill.run — the same path production takes.
    """
    from app import skill, systems

    with db.SessionLocal() as s:
        if (s.query(db.ArtifactBody)
                .filter(db.ArtifactBody.format == "ad_batch").count()):
            return "ad batch: already seeded"
    kb.set_brand("baci", positioning="Italian-designed tableware.",
                 tone="direct, warm")
    kb.add_banned("baci", "hand-decorated")
    for c, ev in (("Dishwasher safe at 65 degrees.", "lab report 2026"),
                  ("Made of shatter-resistant acrylic.", "spec sheet"),
                  ("Designed in Milan.", "brand file")):
        kb.add_claim("baci", c, ev, [], origin="human", status="active")
    kb.add_audience("baci", "hosts", "Hosts who entertain",
                    ["dull tables"], ["colour", "set"], origin="human")
    kb.add_entity("baci", "product", "aqua-plate", "Aqua Plate",
                  description="A generous 32 cm plate.", origin="human")
    row = (systems.find("baci", "ad_creative")
           or systems.create("baci", "ad_creative"))
    filled = systems.update(row.id, **{f: "seeded for the demo"
                                       for f, _l, _h in systems.CONTRACT})
    if not filled.get("ok"):
        return f"ad batch: contract refused ({filled})"
    # Capabilities are credential-backed and the demo database has no
    # credentials — the one boundary the offline suites also stub. Stubbed
    # only for this seeding call; the demo SERVER runs unstubbed, so its
    # Systems tab honestly shows ad_creative waiting on a connection while
    # the already-produced batch stays reviewable on its board.
    _orig = tenants.capabilities
    tenants.capabilities = lambda key: {c: True for c in tenants.CAPABILITIES}
    try:
        live = systems.update(row.id, status="live", autonomy="approve_all")
        if not live.get("ok"):
            return f"ad batch: go-live refused ({live})"
        r = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                      audience_key="hosts", variants=3)
    finally:
        tenants.capabilities = _orig
    if r.get("status") != "produced":
        return f"ad batch: run came back {r.get('status')}"
    return (f"ad batch: {len(r.get('items') or [])} variant(s) on the board "
            f"(anchor {r['items'][0]['output_id'][:8]}…)")


def seed_data_layer() -> str:
    """Representative rows for the step-4 Data layer walkthrough — every
    queue lane and domain state has something to click.

    Public writers throughout, with one named exception: the two SystemRun
    rows that stand in for edited sends. Their production writer is
    `edits.delta` at launch time, which needs a live send to diff — the
    demo fakes the ROW, not the reader, and the comment is the label.
    """
    import datetime as dt

    from app import systems

    if len([r for r in kb.claim_inventory("baci")["selectable"]]) > 10:
        return "data layer: already seeded"
    kb.add_situation("baci", "hosting_dinners", patterns=[["dinner"]],
                     description="Setting a table for guests", origin="human")
    kb.add_situation("baci", "gift_hunting", patterns=[["gift"]],
                     description="Buying a present with a deadline",
                     origin="human")
    kb.add_objection("baci", "Is it dishwasher safe?",
                     "Yes — tested at 65 degrees.",
                     situations=["hosting_dinners"], origin="human")
    for i in range(16):
        kb.add_claim("baci", f"Piece {i} survives {1200 + i} dishwasher "
                             f"cycles in lab testing.",
                     f"lab report {i}", ["hosting_dinners"], origin="human")
    kb.add_claim("baci", "A claim the owner walked back.", "old flyer", [],
                 origin="human")
    walked = [r for r in kb.claim_inventory("baci")["selectable"]
              if "walked back" in r.claim]
    if walked:
        kb.remove("baci", "claim", walked[0].id)
    kb.record_unknowns("baci", [{"basis": "unknown", "key": "aqua-plate",
                                 "name": "Aqua Plate",
                                 "attribute": "capacity"}],
                       asked_for="does the pitcher hold a litre?")
    row = (systems.find("baci", "campaign_email")
           or systems.create("baci", "campaign_email"))
    with db.SessionLocal() as s:
        for i, txt in enumerate((
                "- shortened the opening in 4 of 6 edited sends",
                "- swapped the hero for a lifestyle shot, twice")):
            s.add(db.SystemRun(system_id=row.id, tenant="baci", stage="sent",
                               decision="edited", edit_diff=txt,
                               created_at=db.utcnow()
                               - dt.timedelta(days=3 + i)))
        s.commit()
    return "data layer: claims×17 (1 removed), objection, gap, 2 lessons"


def seed_landing_pages() -> str:
    """One account with a SECOND source, so the Brand tab's source editor and
    the claim card's "read off …" line have something to be about.

    Only one account gets one: the single-source case is the one every other
    account is in, and both states have to be clickable — a demo where every
    account looks the same cannot show that the site name appears on a claim
    card only when there is more than one site to tell apart.
    """
    res = tenants.set_sources("baci", [
        {"url": "https://spring.bacimilanousa.com",
         "label": "Spring campaign landing page"}])
    # And one claim read off it, waiting on Review — the visible half of the
    # feature is the Details fold saying WHICH site a card came from, and a
    # queue with nothing from a second source cannot show it.
    kb.add_claim("baci", "The spring set ships within 2 working days.",
                 "2 working days", ["gift_hunting"], proof_type="data",
                 source="stated on https://spring.bacimilanousa.com/offer",
                 status="pending", origin="crawl")
    return f"baci reads {res['landing_pages'] + 1} sources"


def seed_mail_queue() -> str:
    """Both halves of the 2026-08-27 rule, so the walkthrough can see the
    difference: a drafted reply (which must NOT appear on Review) and an
    email that exists nowhere but the queue (which must).
    """
    from app import approvals
    approvals.request_approval(
        "send_email", "Re: is the Aqua set dishwasher safe?",
        {"account": "baci", "to": "marisa@example.com",
         "subject": "Re: is the Aqua set dishwasher safe?",
         "body": "Hi Marisa,\n\nYes — tested at 65 degrees.\n\nBest,\nBaci",
         "thread_id": "demo-t1", "draft_id": "demo-d1"}, notify=False)
    approvals.request_approval(
        "send_email", "[Invoice reminder] studio@example.com: Invoice 1042",
        {"account": "baci", "to": "studio@example.com",
         "subject": "Re: Invoice 1042",
         "body": "Hi,\n\nJust following up on the invoice.\n\nBest,\nGomeh"},
        notify=False)
    return "mail: 1 drafted reply (hidden) + 1 queue-only email (shown)"


def seed_keyword_map() -> str:
    """Enough of a keyword map that the Plan tab's tables actually render.

    Not decoration: `.grp` — the tier/pillar heading row those tables emit —
    was the last of the Plan tab's undefined classes, and the render-smoke
    class check never saw it because it walks an account with no keywords.
    A class that only appears when there is DATA is invisible to a check run
    against emptiness, which is the same shape as the bug the smoke suite was
    written to catch. So the demo has data.
    """
    from app import keywords as kw
    seeded = 0
    for phrase, vol, tier in (
            ("italian tableware", 2400, "head"),
            ("colorful dinnerware sets", 880, "body"),
            ("melamine plates for outdoor dining", 320, "long_tail"),
            ("are melamine plates dishwasher safe", 210, "long_tail"),
            ("best plates for hosting dinner parties", 170, "long_tail"),
            ("acrylic stemware", 590, "body")):
        kw.upsert("baci", phrase, volume=vol, source="seed_demo",
                  database="us")
        seeded += 1
    return f"keyword map: {seeded} phrases for baci"


said = seed_ad_batch()
said2 = seed_data_layer()
said3 = seed_landing_pages()
said4 = seed_mail_queue()
said5 = seed_keyword_map()
print(f"demo seeded: {made} · accounts: "
      f"{', '.join(t.key for t in tenants.all_tenants())} · {said} · {said2}"
      f" · {said3} · {said4} · {said5}")
