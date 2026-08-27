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


said = seed_ad_batch()
print(f"demo seeded: {made} · accounts: "
      f"{', '.join(t.key for t in tenants.all_tenants())} · {said}")
