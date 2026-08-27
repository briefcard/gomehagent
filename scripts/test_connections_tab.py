"""The Connections tab: no JSON dead-ends, and destructive actions ask.

Spec §11 counted six actions on this page that dead-ended on raw JSON —
Test connections, Create account, Grant access, Sign-in link, the raw-wiring
saves, and the purge dry-run (that one lives on Review and converts with
it). The page's own copy DOCUMENTED the defect twice ("Saving reloads to a
JSON response — hit back to return here"). This suite pins the rebuild:

  1. THREE VIEWS — Status (is it wired: chips, failed-first rows, the
     background Test with its result ON the card), People & links (portal
     people, sign-in/connect/intake links, all flashing on-page), Advanced
     (raw wiring with ui-flashes, add-account, the parked bot-access fold,
     the routes panel).
  2. EVERY CONVERTED ACTION LANDS BACK AS A FLASH — create-account, grant
     access, sign-in link, test connections. The bare JSON forms stay for
     hand calls; the console forms carry ui=1.
  3. DESTRUCTIVE ASKS FIRST — Disconnect and Revoke confirm, naming the
     consequence (unused sign-in links die with a revoke).
  4. PARKED READS AS PARKED — bot access is a neutral parked-by-choice
     fold with its switch-on condition inside, not a working form under a
     permanent error-styled warning.

Run: python3 scripts/test_connections_tab.py
"""
import os
import sys
import tempfile
import time

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ct.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui, db, tenants, web  # noqa: E402

KEY = "s3cret"
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


c = TestClient(web.app, base_url="https://testserver")


def page(sub="", tenant="baci"):
    return c.get(f"/admin/ui?key={KEY}&tab=accounts&tenant={tenant}"
                 + (f"&sub={sub}" if sub else "")).text


def main():
    db.init_db()
    tenants.seed()

    print("\n--- 1 · three views, one strip ---")
    st = page()
    ck("Status lands first with the strip",
       "People &amp; links" in st and "Advanced" in st
       and "Test connections" in st)
    ck("…and says it has never been live-tested rather than implying health",
       "Never live-tested" in st)
    ck("…and points at People & links for the human side",
       "sub=people" in st)
    pp = page("people")
    ck("People & links holds people, connect links and intake links",
       "People who can sign in" in pp and "Create a connect link" in pp
       and "Intake links —" in pp)
    adv = page("advanced")
    ck("Advanced holds the wiring, add-account, bot access and the routes "
       "panel", "Raw wiring" in adv and "Add an account" in adv
       and "Give someone bot access" in adv and "Connection routes" in adv)

    print("\n--- 2 · the dead-ends are flashes now ---")
    r = c.get(f"/admin/tenant_add?key={KEY}&tenant=acme&name=Acme+Co"
              f"&business_model=&ui=1", follow_redirects=False)
    loc = r.headers.get("location", "")
    ck("create-account lands back with a flash, not JSON",
       r.status_code == 303 and "tab=accounts" in loc and "ok=" in loc, loc)
    ck("…and the account exists", tenants.get("acme") is not None)
    r = c.get(f"/admin/tenant_add?key={KEY}&tenant=acme&name=Twice&ui=1",
              follow_redirects=False)
    ck("…a duplicate is refused as a flash",
       "err=" in r.headers.get("location", ""))
    r = c.get(f"/admin/tenant_add?key={KEY}&tenant=json-check&name=J",
              follow_redirects=False)
    ck("…the bare JSON form survives for hand calls", r.status_code == 200)

    r = c.get(f"/admin/user_add?key={KEY}&chat_id=555&name=Ellis&role=client"
              f"&tenant=baci&ui=1", follow_redirects=False)
    ck("grant-access lands back with a flash", r.status_code == 303
       and "ok=" in r.headers.get("location", ""),
       r.headers.get("location", ""))
    r = c.get(f"/admin/user_add?key={KEY}&chat_id=&role=client&tenant=baci"
              f"&ui=1", follow_redirects=False)
    ck("…and its refusals ride the flash too",
       "err=" in r.headers.get("location", ""))

    c.post("/admin/person_save",
           data={"key": KEY, "tenant": "baci", "email": "jane@x.com",
                 "name": "Jane", "access": "read_only"},
           follow_redirects=False)
    r = c.get(f"/admin/portal_link?key={KEY}&email=jane@x.com&ui=1"
              f"&tenant=baci", follow_redirects=False)
    loc = r.headers.get("location", "")
    ck("sign-in link flashes on People & links, not JSON",
       r.status_code == 303 and "sub=people" in loc and "plink=" in loc, loc)
    flashed = c.get(loc).text
    ck("…as a copyable field with the affordance labeled",
       "Sign-in link — send it to them yourself" in flashed
       and "click the field to select" in flashed)

    real_verify = tenants.verify
    tenants.verify = lambda tk: {
        "commerce": {"status": "ok", "detail": "Baci Milano"},
        "inbox": {"status": "FAIL", "detail": "RefreshError: token revoked"}}
    try:
        r = c.get(f"/admin/verify?key={KEY}&tenant=baci&ui=1",
                  follow_redirects=False)
        ck("Test connections lands back with a flash and runs in the "
           "background", r.status_code == 303
           and "background" in r.headers.get("location", ""),
           r.headers.get("location", ""))
        for _ in range(40):                       # the bg thread finishes
            with db.SessionLocal() as s:
                if s.get(db.Setting, "verify_result:baci"):
                    break
            time.sleep(0.1)
        st2 = page()
        ck("…and the per-provider result lands ON the Status card",
           "Last live test" in st2 and "commerce: ok" in st2
           and "inbox: FAIL" in st2)
        r = c.get(f"/admin/verify?key={KEY}&tenant=baci",
                  follow_redirects=False)
        ck("…the bare JSON probe survives for hand calls",
           r.status_code == 200 and "commerce" in r.text)
    finally:
        tenants.verify = real_verify

    ck("the raw-wiring saves carry ui — the page stops documenting its own "
       "dead-end", 'name="ui" value="1"' in adv
       and "Saving reloads to a JSON response" not in adv
       and "Saving reloads to a JSON response" not in st)

    print("\n--- 3 · destructive asks first ---")
    pp = page("people")
    # The BINDING is the pin, not the string — a confirm() that no longer
    # rides onsubmit is decoration, and the sabotage harness proved the
    # looser check passed right through it.
    ck("Revoke confirms, naming the consequence",
       'onsubmit="return confirm(' in pp and "dies with it" in pp)
    with db.SessionLocal() as s:
        s.add(db.Credential(tenant="baci", provider="wordpress",
                            status="active", secret="enc", site="x.com",
                            kind="api_key"))
        s.commit()
    st3 = page()
    ck("Disconnect confirms, naming the consequence",
       "Disconnect" in st3 and "connect it again" in st3
       and 'onsubmit="return confirm(' in st3)

    print("\n--- 4 · parked reads as parked ---")
    ck("bot access is parked by choice, with the switch-on condition inside",
       "parked by choice" in adv
       and "Switch-on condition" in adv)
    ck("…and the old error-styled warning is gone",
       "<strong>Not yet.</strong>" not in adv)

    print("\n--- 5 · failed connections sort first ---")
    from app import credentials as cred
    real_status = cred.status

    def _fake_status(t):
        row = {"covered_by": "", "detail": "", "last_verified": "",
               "kind": "api_key", "self_serve": False, "has_oauth": False,
               "oauth_too": False, "site_scoped": False, "shop_scoped": False,
               "connections": [], "blocked_by": "", "oauth_blocked_by": ""}
        return [dict(row, provider="alpha", name="Alpha", state="connected"),
                dict(row, provider="omega", name="Omega", state="failed"),
                dict(row, provider="beta", name="Beta", state="not_configured")]

    cred.status = _fake_status
    try:
        h = admin_ui._connections("baci", KEY)
        ck("the failed row renders before the healthy one",
           0 < h.find("Omega") < h.find("Alpha") < h.find("Beta"),
           f"omega@{h.find('Omega')} alpha@{h.find('Alpha')}")
        st4 = page()
        ck("…and the Status strip counts it",
           '<span class="cnt">1</span>' in st4)
    finally:
        cred.status = real_status

    print()
    if _fail:
        print(f"FAILED: {len(_fail)} — " + "; ".join(_fail[:8]))
        sys.exit(1)
    print("all green: Connections answers on the page, and asks before it "
          "severs")


if __name__ == "__main__":
    main()
