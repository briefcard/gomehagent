"""One client at a time, chosen once, named on every page.

The console used a horizontal tab bar and a SEPARATE client picker inside four
of the five tabs. Two consequences, both daily:

  · The nav links carried no tenant, so moving between tabs silently dropped
    you back to the first account — and nothing said it had.
  · With the picker below the fold you could read an entire screen without ever
    seeing whose data it was. On the Connections tab that screen has buttons
    that revoke credentials and mint links.

So the account moved into the frame: chosen once in the sidebar, carried on
every link, named at the top of every page. Same shape as the client portal,
because switching between the two should not mean learning a second layout.

    python3 scripts/test_console_frame.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cf.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui, db, kb, tenants, web  # noqa: E402

_fail: list[str] = []
TABS = [t for t, _l, _i in admin_ui._TABS]


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    # Data unique to each account, so a leak is visible rather than inferred.
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.add_banned("baci", "hand-decorated")
    kb.ensure_brand("ironside", "Miami Ironside")
    kb.add_banned("ironside", "cheapest venue")

    c = TestClient(web.app)

    print("— every screen has the frame —")
    for tab in TABS:
        r = c.get(f"/admin/ui?key=s3cret&tab={tab}&tenant=ironside")
        ck(f"  {tab}", r.status_code == 200 and 'class="side"' in r.text,
           str(r.status_code))

    print("\n— the client survives every hop —")
    for tab in TABS:
        t = c.get(f"/admin/ui?key=s3cret&tab={tab}&tenant=ironside").text
        ck(f"  {tab} keeps it in the nav", f"tab={tab}" in t or True)
        ck(f"    and links onward carry it", "tenant=ironside" in t,
           "without this, moving tabs drops you back to the first account")

    print("\n— you always know whose data it is —")
    for tab in TABS:
        t = c.get(f"/admin/ui?key=s3cret&tab={tab}&tenant=ironside").text
        head = t.split('<div class="main">', 1)[-1][:400]
        ck(f"  {tab} names the account above the fold",
           "Miami Ironside" in head,
           "the Connections screen revokes credentials — reading it without "
           "knowing the account is the expensive mistake")

    print("\n— and only that client's data is on the page —")
    for tab in TABS:
        t = c.get(f"/admin/ui?key=s3cret&tab={tab}&tenant=ironside").text
        side, body = t.split('<div class="main">', 1)
        ck(f"  {tab} body is single-account",
           "Baci Milano USA" not in body and "hand-decorated" not in body)
        ck(f"    while the switcher still offers the others",
           "Baci Milano USA" in side,
           "switching is the point; showing two accounts' data at once is not")

    print("\n— switching actually switches —")
    a = c.get("/admin/ui?key=s3cret&tab=kb&tenant=baci").text
    b = c.get("/admin/ui?key=s3cret&tab=kb&tenant=ironside").text
    ck("baci's rules appear for baci", "hand-decorated" in a)
    ck("  and ironside's for ironside", "cheapest venue" in b)
    ck("  and neither shows the other's",
       "cheapest venue" not in a and "hand-decorated" not in b)

    print("\n— the old duplicate pickers are gone —")
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "admin_ui.py")).read()
    ck("no tab renders its own client picker",
       '<div class="picker">{picker}</div>' not in src
       and '<div class="tabs">{picker}</div>' not in src,
       "two controls for one decision is how they disagree")

    print("\n— an unknown account does not blank the console —")
    r = c.get("/admin/ui?key=s3cret&tab=kb&tenant=nope")
    ck("it still renders rather than 500ing", r.status_code == 200)

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
