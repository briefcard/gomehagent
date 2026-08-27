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

from app import db, kb, tenants  # noqa: E402

db.init_db()
made = tenants.seed()
for t in tenants.all_tenants():
    kb.ensure_brand(t.key, t.name)
print(f"demo seeded: {made} · accounts: "
      f"{', '.join(t.key for t in tenants.all_tenants())}")
