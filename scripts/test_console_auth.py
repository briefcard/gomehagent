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

    # --- the front door: public landing, POST sign-in, no dead ends -------
    print("\n— the front door —")
    with TestClient(web.app) as c:
        r = c.get("/")
        ck("the root is a branded page, not a 404 JSON",
           r.status_code == 200 and "MarketingThatWorks" in r.text)
        leaks = [x for x in ("Baci", "baci", "Eien", "eien", SECRET,
                             "/admin/ui") if x in r.text]
        ck("and it is public-safe — no client, no secret, no console route",
           not leaks, ", ".join(leaks))
        r = c.get("/admin/ui", follow_redirects=False)
        ck("an unauthenticated console visit lands on sign-in, not 'bad key'",
           r.status_code == 303 and r.headers["location"] == "/admin/signin")
        r = c.post("/admin/signin", data={"key": "wrong"},
                   follow_redirects=False)
        ck("a wrong key is one 401 shape with no cookie",
           r.status_code == 401 and "console" not in r.cookies)
        r = c.post("/admin/signin", data={"key": SECRET},
                   follow_redirects=False)
        ck("the right key becomes the session via POST body — never a URL",
           r.status_code == 303 and bool(r.cookies.get("console")))
        ck("and the console renders on that session",
           'class="side"' in c.get("/admin/ui").text)

    # --- the console stops threading the key through links ---------------
    print("\n— the console's own links —")
    with TestClient(web.app) as c:
        # CHANGED DELIBERATELY (2026-08-21): the marker was the literal page
        # heading "Accounts", which the Connections-tab redesign renamed. The
        # assertion's intent is "the console frame rendered, not an error
        # page" — so it now checks the frame's own sidebar marker, the same
        # one test_console_frame uses, which no copy edit can knock over.
        html = c.get("/admin/ui", params={"key": SECRET}).text
        ck("first load renders", 'class="side"' in html)
        html2 = c.get("/admin/ui").text          # now on the cookie
        ck("second load still renders", 'class="side"' in html2)
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

        # WHAT IT MAY SAY WITHOUT A KEY. The unauthenticated half is a
        # heartbeat, not a roster — it used to name every Gmail alias and
        # every redirect URI on a page that promises each client sees only
        # their own workspace. The capability report names infrastructure, so
        # it belongs on the other side of the key.
        ck("no capability report without the key",
           "capabilities" not in r.json(),
           str(sorted(r.json())))
        keyed = c.get("/health?key=s3cret-console").json()
        cap = keyed.get("capabilities") or {}
        ck("…and with the key it says what can actually run",
           set(cap.get("can") or {}) >= {"generate_images",
                                         "review_generated_images"},
           "the owner had to ask what was connected and nothing could "
           "answer him")
        ck("…named as the JOB, not as the variable",
           "OPENAI_API_KEY" not in str(cap.get("can")),
           "'is OPENAI_API_KEY set' is not the question anybody has")
        ck("…and never leaks a value",
           all(isinstance(v, bool) for v in (cap.get("keys_present") or {}).values()),
           "presence only — anything more is a credential leak wearing a "
           "diagnostic's clothes")
        ck("…and says creative needs two different providers",
           "BOTH" in str(cap.get("note", "")),
           "images generate on OpenAI and are reviewed on Anthropic; one key "
           "missing fails quietly")

    # --- dependencies nothing in app/ imports by name ----------------------
    #
    # This exists because of a real outage. Starlette imports `python-multipart`
    # lazily, from inside `request.form()`. No file in app/ says
    # `import multipart`, so it is invisible to an import audit, and every test
    # here passed because the dev machine had it installed as somebody else's
    # transitive dependency. It was missing from requirements.txt, so on Render
    # every form POST raised
    #     AssertionError: The `python-multipart` library must be installed
    # — which meant the console's approve/reject buttons AND the client-facing
    # connect page, where a client pastes their own API keys, had never worked
    # in production. Both of them 500'd from the day form parsing landed.
    #
    # An import audit cannot catch this class. Matching the FEATURE to the
    # package it silently requires can.
    print("\n— implicit runtime dependencies —")
    import pathlib as _pl
    import re as _re

    root = _pl.Path(__file__).resolve().parent.parent
    src = "\n".join(p.read_text() for p in (root / "app").glob("*.py"))
    reqs = (root / "requirements.txt").read_text().lower()
    LAZY = [
        (r"\.form\(\)|UploadFile|File\(", "python-multipart",
         "form POSTs and file uploads"),
        (r"Jinja2Templates", "jinja2", "server-side templates"),
        (r"SessionMiddleware", "itsdangerous", "signed session cookies"),
        (r"EmailStr", "email-validator", "pydantic email fields"),
    ]
    for pattern, package, why in LAZY:
        if not _re.search(pattern, src):
            continue
        ok = package in reqs
        ck(f"{package} is declared — {why} need it at runtime", ok,
           "" if ok else "app/ uses it; requirements.txt does not list it")

    # ---- the WhatsApp webhook verifies Meta's signature ------------------
    # It approves, executes, and commands the agent, and its only gate used to
    # be `msg["from"]` — a field of the caller's own JSON. A forged POST reached
    # approve/execute with no cryptographic check. It now verifies HMAC over the
    # raw body and fails CLOSED when no app secret is set.
    print("\n— whatsapp webhook signature —")
    import hashlib as _hl
    import hmac as _hmac

    c = TestClient(web.app)
    raw = b'{"entry":[]}'
    config.META_APP_SECRET = ""
    r = c.post("/webhooks/whatsapp", content=raw)
    ck("unsigned delivery refused when no app secret is set (fail closed)",
       r.status_code == 401, f"got {r.status_code}")

    config.META_APP_SECRET = "app-secret-xyz"
    r = c.post("/webhooks/whatsapp", content=raw,
               headers={"x-hub-signature-256": "sha256=deadbeef"})
    ck("a forged signature is refused", r.status_code == 401, f"got {r.status_code}")
    good = "sha256=" + _hmac.new(b"app-secret-xyz", raw, _hl.sha256).hexdigest()
    r = c.post("/webhooks/whatsapp", content=raw,
               headers={"x-hub-signature-256": good})
    ck("a validly-signed delivery is accepted", r.status_code == 200,
       f"got {r.status_code}")
    config.META_APP_SECRET = ""

    # ---- the Telegram webhook (the live ops channel) fails closed --------
    from app import telegram as _tg
    config.TELEGRAM_WEBHOOK_SECRET = ""
    r = c.post("/telegram/webhook", json={"update_id": 1, "message": {}})
    ck("telegram delivery refused when no secret is set (fail closed)",
       r.json().get("status") == "forbidden", str(r.json()))
    config.TELEGRAM_WEBHOOK_SECRET = "tg-secret-abc"
    wire = _tg.wire_secret()
    r = c.post("/telegram/webhook", json={"update_id": 2, "message": {}},
               headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
    ck("a wrong telegram secret is refused",
       r.json().get("status") == "forbidden", str(r.json()))
    r = c.post("/telegram/webhook",
               json={"update_id": 3, "message": {"chat": {"id": 999999}}},
               headers={"X-Telegram-Bot-Api-Secret-Token": wire})
    ck("a valid telegram secret passes gate 1 (allowlist still applies after)",
       r.json().get("status") != "forbidden", str(r.json()))
    config.TELEGRAM_WEBHOOK_SECRET = ""

    # --- the two pages that MUST be public ------------------------------
    #
    # Google fetches these anonymously while saving the OAuth consent screen,
    # so a key on either one is not a hardening — it is a consent screen that
    # will not save. They sit in the auth suite because "which routes are open"
    # is exactly what this file is for.
    import re as _re
    print("\n— the policy pages Google has to be able to read —")
    with TestClient(web.app) as c:
        for path, must in (("/privacy", ("Limited Use requirements",
                                         "api-services-user-data-policy",
                                         "gmail.modify", "webmasters.readonly")),
                           ("/terms", ("Your responsibilities",))):
            r = c.get(path)
            ck(f"{path} is reachable with NO key", r.status_code == 200,
               f"got {r.status_code}")
            flat = _re.sub(r"\s+", " ", r.text)
            for phrase in must:
                ck(f"  {path} states {phrase!r}", phrase in flat)
        priv, terms = c.get("/privacy").text, c.get("/terms").text
        ck("the privacy policy names a contact",
           "mailto:" in priv and "@" in priv)
        ck("each links to the other",
           '"/terms"' in priv and '"/privacy"' in terms)

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
