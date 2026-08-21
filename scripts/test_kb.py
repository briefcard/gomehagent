"""Offline exercise of the knowledge base: seeding, guided intake, console.

The checks that matter here are the refusals. A KB that accepts a misrouted
answer stores plausible-looking garbage that no later stage can detect — a
pipe-formatted objection became a four-word brand "voice" the first time this
ran, which is exactly the silent corruption the write layer exists to prevent.

    python3 scripts/test_kb.py
"""
import os, sys, tempfile
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(),'kb.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient
from app import config, db, kb, kb_seed, ops_commands, systems, tenants
from app.web import app
config.GMAIL_ACCOUNTS.setdefault("personal", {"email":"t@e.com"})

fails=[]
def ck(l,c,d=""):
    print(f"[{'  ok  ' if c else ' FAIL '}] {l}" + (f"  — {d}" if d else ""))
    if not c: fails.append(l)

with TestClient(app) as cl:
    tenants.seed(); kb.seed_agency(); systems.seed_from_tenants()
    kb_seed.seed_all()

    print("\n— seeded state —")
    for t in ("agency","baci","eien","coverings","ironside"):
        c = kb.completeness(t); g = kb.gaps(t)
        print(f"  {t:10s} ready={str(c['ready']):5s} {c['counts']} gaps={len(g)}")

    ck("baci has the origin rules", "made in Italy" in kb.banned_claims("baci"))
    ck("baci handcraft banned", "handmade" in kb.banned_claims("baci"))
    ck("eien has a compliance boundary", len(kb.banned_claims("eien"))>10,
       f"{len(kb.banned_claims('eien'))} rules")
    ck("ironside has all 8 venues", len(kb.entities("ironside","space"))==8)
    ck("ironside cannot imply a quote", "per person" in kb.banned_claims("ironside"))
    ck("baci audiences from real ad data", len(kb.audiences("baci"))==3)

    # --- telegram guided intake ---
    print("\n— telegram intake —")
    tenants.seed_owner("999","Gomeh")
    u = tenants.user_for_chat("999"); tenants.switch(u,"ironside")
    r1 = ops_commands.handle("/next","999")
    step0 = kb.gaps("ironside")[0]["id"]
    ck("/next poses the top gap", "still missing" in r1 and step0=="tone", f"asked {step0}")

    # answer the wrong shape on purpose — the guard must catch it
    bad = ops_commands.handle("Corporate planners hate slow replies | We answer in an hour","999")
    ck("a misrouted pipe answer is refused", "different question" in bad, bad.split("\n")[0][:60])
    ck("and nothing was written", not (kb.brand("ironside").voice or {}).get("tone"))
    ck("the question stays open", "Still open" in bad)

    r2 = ops_commands.handle("direct, warm, unhurried","999")
    ck("the right shape is accepted", (kb.brand("ironside").voice or {}).get("tone")==["direct","warm","unhurried"])
    ck("and it immediately asks the next", "still missing" in r2)

    r3 = ops_commands.handle("Corporate planners hate slow replies | We answer inside the hour","999")
    ck("objection landed", len(kb.objections("ironside"))==1, r3.split("\n")[0][:60])

    r4 = ops_commands.handle("/clients","999")
    ck("a command is never eaten as an answer", "Miami Ironside" in r4)

    r5 = ops_commands.handle("ban: cheapest venue in Miami","999")
    ck("ban: adds a hard rule", "cheapest venue" in " ".join(kb.banned_claims("ironside")))

    ck("ironside KB completed through Telegram alone", kb.completeness("ironside")["ready"])

    # a structured step, answered with prose that has no pipes
    ops_commands._pending_set("999","eien","objection")
    r6 = ops_commands.handle("people say we are expensive","999")
    ck("a malformed structured answer re-opens", r6 and "Still open" in r6, str(r6)[:46])
    ck("and the question is genuinely still pending",
       ops_commands._pending_get("999").get("step")=="objection")

    # --- web surfaces ---
    print("\n— console —")
    # "accounts" needle CHANGED DELIBERATELY (2026-08-21): it was the literal
    # h1 "Accounts", renamed by the Connections-tab redesign. "Connection
    # routes" is body-specific to that tab (renders in both its branches),
    # which "Connections" alone would not prove — the sidebar nav carries that
    # word on every tab.
    for tab,needle in (("kb","Knowledge"),("systems","Systems"),("accounts","Connection routes")):
        r = cl.get("/admin/ui", params={"key":"s3cret","tab":tab})
        ck(f"{tab} tab renders", r.status_code==200 and needle in r.text, f"{len(r.text)}b")
    r = cl.get("/admin/ui", params={"key":"s3cret","tab":"kb","tenant":"baci"})
    ck("kb tab shows baci's rules", "handmade" in r.text and "Zodiac" in r.text)
    r = cl.get("/admin/kb", params={"key":"s3cret","tenant":"ironside"})
    j = r.json()
    ck("kb json exposes everything", len(j["entities"])==8 and j["brand"] is not None)
    r = cl.get("/admin/kb_add", params={"key":"s3cret","tenant":"coverings",
        "step":"objection","text":"You're not local | We ship nationwide from Miami"},
        follow_redirects=False)
    ck("console capture writes", r.status_code==303 and len(kb.objections("coverings"))==1)

print()
print(f"{len(fails)} FAILED: {fails}" if fails else "all checks passed")
raise SystemExit(1 if fails else 0)
