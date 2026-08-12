"""The console credential should be supplied once, not on every request.

Every admin route used to require `?key=<APPROVAL_SECRET>`, so the credential
rode in browser history, Referer headers and every access log, and the ten
console forms re-embedded it to keep navigation working.

What this locks down: the key still works, a header works, one use establishes
a session, the session survives without the key, and the cookie is NOT the
secret — because APPROVAL_SECRET also signs approval decision links, so a
cookie carrying it verbatim would widen a stolen session into forging approvals.

    python3 scripts/test_console_auth.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ca.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret-console"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, web  # noqa: E402

SECRET = "s3cret-console"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    # --- no credential at all --------------------------------------------
    print("— unauthenticated —")
    with TestClient(web.app) as c:
        r = c.get("/admin/tenants")
        ck("no key is refused", r.json().get("error") == "unauthorized")
        ck("and sets no cookie", "console" not in r.cookies)
        r = c.get("/admin/tenants", params={"key": "wrong"})
        ck("a wrong key is refused", r.json().get("error") == "unauthorized")
        ck("a wrong key sets no cookie", "console" not in r.cookies)

    # --- the key, once ----------------------------------------------------
    print("\n— the key, supplied once —")
    with TestClient(web.app) as c:
        r = c.get("/admin/tenants", params={"key": SECRET})
        ck("the key still works", "error" not in r.json())
        ck("and a session cookie is issued", "console" in c.cookies)

        cookie = c.cookies.get("console")
        ck("the cookie is NOT the secret", cookie != SECRET, cookie[:16] + "…")
        ck("nor does it contain it", SECRET not in cookie)
        ck("it is the derived token", cookie == web._console_token())

        # The whole point: subsequent requests carry no key.
        r = c.get("/admin/tenants")
        ck("the next request needs no key", "error" not in r.json())
        r = c.get("/admin/seed_kb", params={"report_only": "1"})
        ck("a different route needs no key either", "error" not in r.json())

    # --- the header -------------------------------------------------------
    print("\n— the header —")
    with TestClient(web.app) as c:
        r = c.get("/admin/tenants", headers={"X-Admin-Key": SECRET})
        ck("X-Admin-Key authenticates", "error" not in r.json())
        ck("and also establishes the session", "console" in c.cookies)
    with TestClient(web.app) as c:
        r = c.get("/admin/tenants", headers={"X-Admin-Key": "nope"})
        ck("a wrong header is refused", r.json().get("error") == "unauthorized")

    # --- a forged cookie --------------------------------------------------
    print("\n— a forged cookie —")
    with TestClient(web.app) as c:
        c.cookies.set("console", "not-the-token")
        ck("a bogus cookie is refused",
           c.get("/admin/tenants").json().get("error") == "unauthorized")
    with TestClient(web.app) as c:
        c.cookies.set("console", SECRET)   # the secret is not the token
        ck("the raw secret as a cookie is refused",
           c.get("/admin/tenants").json().get("error") == "unauthorized")

    # --- logout -----------------------------------------------------------
    print("\n— logout —")
    with TestClient(web.app) as c:
        c.get("/admin/tenants", params={"key": SECRET})
        ck("session established", "console" in c.cookies)
        c.get("/admin/logout")
        ck("logout clears it", not c.cookies.get("console"))
        ck("and access is refused again",
           c.get("/admin/tenants").json().get("error") == "unauthorized")

    # --- the console stops threading the key through links ---------------
    print("\n— the console's own links —")
    with TestClient(web.app) as c:
        html = c.get("/admin/ui", params={"key": SECRET}).text
        ck("first load renders", "Accounts" in html)
        html2 = c.get("/admin/ui").text          # now on the cookie
        ck("second load still renders", "Accounts" in html2)
        ck("and no longer embeds the secret in links", SECRET not in html2,
           "secret found in rendered HTML")
        ck("(it was embedded on the first, key-bearing load)", SECRET in html)

    # --- routes that return a Response directly still get the cookie ------
    print("\n— redirect routes —")
    with TestClient(web.app) as c:
        r = c.get("/admin/kb_add", params={"key": SECRET, "tenant": "agency",
                                           "step": "tone", "text": "direct, warm"},
                  follow_redirects=False)
        ck("a redirecting route also establishes the session",
           "console" in c.cookies, f"status {r.status_code}")

    # --- non-admin paths are untouched ------------------------------------
    print("\n— unrelated paths —")
    with TestClient(web.app) as c:
        r = c.get("/health")
        ck("/health still open", r.status_code == 200 and r.json().get("ok"))
        ck("and sets no console cookie", "console" not in r.cookies)

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
