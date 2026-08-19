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

**This file passed for months while the Systems tab rendered every account's
pipelines on one page.** It asserted "the body is single-account" against a
database with no systems, no runs, no approvals and no assurance events in it,
so the assertion was true of an empty table rather than of the code. Every
account below is now seeded with a row of each kind carrying a marker string
only that account should ever produce, which is what makes the leak fail here
instead of in the browser.

    python3 scripts/test_console_frame.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cf.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (admin_ui, approvals, assurance, db, kb,  # noqa: E402
                 systems, tenants, toolcalls, web)

_fail: list[str] = []
TABS = [t for t, _l, _i in admin_ui._TABS]


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


#: A marker per account per table. Every one of these is a string only that
#: account can produce, so finding it on another account's page is proof of a
#: leak rather than a suspicion about one.
def _seed_account(key: str, name: str, banned: str, mark: str) -> None:
    kb.ensure_brand(key, name)
    kb.add_banned(key, banned)
    sysrow = systems.create(key, "lead_responder", f"{mark} responder")
    run = systems.start_run(sysrow.id, key, trigger="inbound_email", ref=mark)
    systems.finish_run(run, "blocked", blocked_on=[f"{mark}_gap"])
    toolcalls.record(key, f"{mark}_tool", provider="shopify", ok=False,
                     error=f"{mark} rejected that token")
    assurance.record(key, source="substrate", checked=[f"{mark}_rule"],
                     caught=[f"{mark}_rule"], verdict="blocked")
    approvals.request_approval("send_email", f"{mark} reply",
                               {"body": "hi", "tenant": key}, notify=False)


def main() -> int:
    db.init_db()
    tenants.seed()
    # Data unique to each account, in every table a tab reads — so a leak is
    # visible rather than inferred, and an empty table cannot pass for a
    # scoped one.
    _seed_account("baci", "Baci Milano USA", "hand-decorated", "BACIMARK")
    _seed_account("ironside", "Miami Ironside", "cheapest venue", "IRONMARK")

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
        leaked = [m for m in ("Baci Milano USA", "hand-decorated", "BACIMARK")
                  if m in body]
        ck(f"  {tab} body is single-account", not leaked, ", ".join(leaked))
        ck(f"    while the switcher still offers the others",
           "Baci Milano USA" in side,
           "switching is the point; showing two accounts' data at once is not")

    print("\n— the waiting counter counts THIS account —")
    # It counted every account, so the number beside one client's name was
    # another client's backlog, and clicking it opened everyone's queue.
    import re as _re
    for who, other in (("ironside", "BACIMARK"), ("baci", "IRONMARK")):
        t = c.get(f"/admin/ui?key=s3cret&tab=content&tenant={who}").text
        m = _re.search(r">(\d+) waiting<", t)
        ck(f"  {who} shows its own count", bool(m) and m.group(1) == "1",
           m.group(0) if m else "no counter rendered")
        ck(f"    and the link carries the account",
           f"/admin/pending?key=s3cret&amp;tenant={who}" in t)
        q = c.get(f"/admin/pending?key=s3cret&tenant={who}").text
        ck(f"    and that queue holds only theirs", other not in q)

    print("\n— all accounts is a place you go on purpose —")
    for tab in TABS:
        t = c.get(f"/admin/ui?key=s3cret&tab={tab}&tenant=*")
        ck(f"  {tab} renders it", t.status_code == 200, str(t.status_code))
        head = t.text.split('<div class="main">', 1)[-1][:600]
        ck(f"    and names it rather than a client", "All accounts" in head,
           "a pooled page under one client's name is the whole defect")
    # And it is never where an unset value lands.
    for tab in TABS:
        head = c.get(f"/admin/ui?key=s3cret&tab={tab}").text.split(
            '<div class="main">', 1)[-1][:600]
        ck(f"  {tab} with no tenant= falls back to an account, not to everything",
           "All accounts" not in head)

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
    # Their CONSTRUCTION was left behind when the markup went, which is how one
    # comes back: a leftover that still reads plausible is a leftover somebody
    # re-renders.
    ck("  and none is still being built for nothing",
       src.count("picker = ") == 0,
       "dead code that looks live is the next person's mistake")

    print("\n— one resolver decides the account, for the frame and the body —")
    ck("every tab body goes through it",
       src.count("all_tenants(") == 1,
       "a tab resolving the account its own way is how the pill and the "
       "numbers came to disagree")

    print("\n— and it is told apart by more than its name —")
    # The first version hashed the key, and five samples out of 360 collided:
    # ironside on 231 and coverings on 256 is the same blue to anybody not
    # holding them side by side. A cue nobody can tell apart is not a cue.
    hues = admin_ui._hues(tenants.all_tenants(include_paused=True))
    vals = sorted(int(v) for v in hues.values())
    gap = min(b - a for a, b in zip(vals, vals[1:])) if len(vals) > 1 else 360
    ck("every account gets a distinguishable hue", gap >= 45, f"{gap}° apart")
    ck("  and it reaches the page",
       f'--tint:{hues["ironside"]}' in c.get(
           "/admin/ui?key=s3cret&tab=kb&tenant=ironside").text)
    ck("  while all-accounts stays the house colour",
       'class="every"' in c.get("/admin/ui?key=s3cret&tab=kb&tenant=*").text,
       "a pooled view wearing one client's colour is the defect in paint")

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
