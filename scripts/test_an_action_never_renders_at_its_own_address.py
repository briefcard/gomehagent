"""An action route never renders a page at its own address, and a wrong method
on one lands somewhere rather than on JSON.

Owner, 2026-09-11, trying to approve photographs:

    https://assistant-web-zm2d.onrender.com/admin/assets_decide
    {"detail":"Method Not Allowed"}

Twenty-five POST-only console routes answered a request without a session by
rendering "<h3>unauthorized</h3>" AT THEIR OWN ADDRESS. Once that page is
showing, the address bar reads `/admin/assets_decide`; a reload or a return to
it is a GET to a route that only takes form posts, and the framework's raw 405
is what a person sees — a dead end with no way out and no way to know why.

Three claims, each driven through the real HTTP client:

  1. A POST action without a session REDIRECTS to sign-in, remembering the
     page it came from. Never a page at the action's address.
  2. Sign-in returns the person to that page, and only to one of ours — a
     return address off our host is dropped, because an open redirect on a
     sign-in page is the classic phishing hop.
  3. A GET on any console action lands on the console with a sentence,
     never on `{"detail":"Method Not Allowed"}`.

And the first is COMPUTED across every route, so the twenty-sixth cannot
regress it.

    python3 scripts/test_an_action_never_renders_at_its_own_address.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'aa.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, tenants, web  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    c = TestClient(web.app, follow_redirects=False)

    print("— the sequence the owner hit —")
    r = c.post("/admin/assets_decide", data={"tenant": "baci", "action": "approve"},
               headers={"referer": "http://testserver/admin/ui?tab=content&tenant=baci"})
    ck("a post without a session is a redirect, not a page at the action's address",
       r.status_code == 303 and r.headers.get("location", "").startswith("/admin/signin"),
       f"{r.status_code} {r.headers.get('location', '')[:60]}")
    ck("and the redirect remembers the page the action came from",
       "next=" in r.headers.get("location", "")
       and "tab%3Dcontent" in r.headers.get("location", ""),
       r.headers.get("location", "")[:90])
    r = c.get("/admin/assets_decide")
    ck("a GET on the action lands on the console with a sentence, never raw JSON",
       r.status_code == 303 and r.headers.get("location", "").startswith("/admin/ui?err=")
       and "form+submission" in r.headers.get("location", "").replace("%20", "+"),
       f"{r.status_code} {r.headers.get('location', '')[:80]}")
    r = c.get("/admin/ui?tab=content", follow_redirects=False)
    ck("while an ordinary page without a session still goes to sign-in",
       r.status_code in (303, 307) and "/admin/signin" in r.headers.get("location", ""))

    print("\n— sign-in takes the person back to where they were —")
    nxt = "/admin/ui?tab=content&tenant=baci"
    page = c.get(f"/admin/signin?next={nxt}").text
    ck("the sign-in page carries the return address in the form, not the URL",
       'name="next"' in page and "tab=content" in page
       and "middle of something" in page)
    r = c.post("/admin/signin", data={"key": "s3cret", "next": nxt})
    ck("a good key lands on that page", r.status_code == 303
       and r.headers.get("location") == nxt, r.headers.get("location", ""))
    ck("and sets the session",
       web.ADMIN_COOKIE + "=" in "".join(r.headers.get_list("set-cookie")))
    r = c.post("/admin/signin", data={"key": "s3cret", "next": "https://evil.example/steal"})
    ck("a return address off our host is dropped — the door is not a hop",
       r.headers.get("location") == "/admin/ui", r.headers.get("location", ""))
    r = c.post("/admin/signin", data={"key": "s3cret", "next": "//evil.example/x"})
    ck("a protocol-relative one is dropped too", r.headers.get("location") == "/admin/ui")
    r = c.post("/admin/signin", data={"key": "s3cret",
                                      "next": "http://testserver/admin/ui?tab=plan"})
    ck("an absolute URL to our own host is reduced to its path",
       r.headers.get("location") == "/admin/ui?tab=plan", r.headers.get("location", ""))
    r = c.post("/admin/signin", data={"key": "wrong", "next": nxt})
    ck("a bad key is still refused, one shape for every failure", r.status_code == 401)

    print("\n— with a session, the same action proceeds as before —")
    c2 = TestClient(web.app, follow_redirects=False)
    c2.post("/admin/signin", data={"key": "s3cret"})
    r = c2.post("/admin/assets_decide", data={"tenant": "baci", "action": "approve"})
    ck("the action runs and returns to the content tab",
       r.status_code == 303 and "/admin/ui" in r.headers.get("location", "")
       and "signin" not in r.headers.get("location", ""), r.headers.get("location", "")[:60])

    print("\n— computed: no console action renders a page at its own address on a bad key —")
    src = open(os.path.join(ROOT, "app", "web.py")).read()
    bare = len(re.findall(r'return HTMLResponse\([\'"]<h3>unauthorized</h3>', src))
    ck("the bare unauthorized page is gone from every route", bare == 0, f"{bare} left")
    # COMPUTED PER POST ROUTE. For every `@app.post("/admin/...")`, the key
    # check inside its body must answer with the sign-in redirect and never
    # with a page. A GET page may still render a refusal — a person can land
    # on it by address, and a page at its own address is what a GET is FOR.
    bodies = re.split(r'(?=^@app\.(?:get|post)\()', src, flags=re.M)
    offenders = []
    for body in bodies:
        head = body.split("\n", 1)[0]
        if not head.startswith('@app.post("/admin/'):
            continue
        for m in re.finditer(r'if key != config\.APPROVAL_SECRET:\n\s+return ([^\n]+)', body):
            if "HTMLResponse" in m.group(1):
                offenders.append(head[:50] + " -> " + m.group(1)[:50])
    ck("every POST action answers a missing session with the sign-in redirect",
       not offenders, "; ".join(offenders[:3]))
    ck("and there are POST routes for this to protect",
       sum(1 for b in bodies if b.startswith('@app.post("/admin/')) >= 20)

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
