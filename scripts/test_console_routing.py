"""The address bar says where you are, and never what your key is.

Owner, 2026-09-23, pasting a live console URL into a chat to show how bad it
had got — `/admin/ui?tab=systems&tenant=baci&system=campaign_email&wf=designs
&key=<the secret>` — *"We need to fix the way we do routing … Isn't this
ridiculous?"*

Two faults, and this suite holds both shut:

  1. THE CREDENTIAL RODE IN THE URL. The cookie was only ever set by the
     sign-in POST, so arriving with `?key=` authenticated every request and
     the console kept threading the key through every link it drew. One visit
     to a `?key=` link and the secret was in the address bar, the history,
     the referrer of every outbound click, and anything the owner pasted.
  2. THE PATH SAID NOTHING. Four query parameters carried the identity of the
     page. `/admin/baci/systems/campaign_email/designs` says it instead, and
     the query keeps only what is a VIEW of that page.

Old URLs are NOT redirected — bookmarks, older pages and every suite go on
resolving. What changed is what the console emits.

    python3 scripts/test_console_routing.py
"""
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'route.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret-console"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient                        # noqa: E402

from app import admin_ui as ui, db, systems, tenants, web        # noqa: E402

KEY = "s3cret-console"
BROWSER = {"accept": "text/html,application/xhtml+xml"}
_fail: list = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    systems.create("baci", "campaign_email")
    with db.SessionLocal() as s:
        a = db.KbAsset(tenant="baci", kind="image", subject="reference",
                       rights="reference", title="ref", url="https://x/y.png",
                       review="approved")
        s.add(a); s.flush()
        st = db.EmailStructure(name="A design", source="reallygoodemails.com",
                               source_asset_id=a.id, review="approved",
                               sequence=["hero"])
        s.add(st); s.flush(); design = st.id
        s.commit()

    print("— the key leaves the address bar on the way in —")
    c = TestClient(web.app)
    r = c.get("/admin/ui?tab=systems&tenant=baci&system=campaign_email&wf=designs"
              f"&key={KEY}", headers=BROWSER, follow_redirects=False)
    ck("a browser arriving with a key is bounced to the same page without it",
       r.status_code == 303 and "key=" not in r.headers.get("location", ""),
       f"{r.status_code} -> {r.headers.get('location')}")
    ck("  and everything else about the page survives the bounce",
       "wf=designs" in r.headers.get("location", "")
       and "tenant=baci" in r.headers.get("location", ""))
    ck("  carrying the session, so the next request needs no key at all",
       "console=" in r.headers.get("set-cookie", ""))
    page = c.get("/admin/ui?tab=brand&tenant=baci", headers=BROWSER)
    ck("  and no page then draws the key into its own links",
       page.status_code == 200 and KEY not in page.text)

    fresh = TestClient(web.app)
    r = fresh.get(f"/admin/ui?tab=brand&tenant=baci&key={KEY}", follow_redirects=False)
    ck("a script or a deploy check is NOT bounced — it is not owed a cookie jar",
       r.status_code == 200, str(r.status_code))
    r = fresh.get("/admin/ui?tab=brand&tenant=baci&key=wrong", headers=BROWSER,
                  follow_redirects=False)
    ck("a WRONG key is not bounced either — it is refused",
       r.status_code != 303 or "signin" in r.headers.get("location", ""),
       f"{r.status_code} {r.headers.get('location', '')}")

    print("\n— the path is the page —")
    ck("the builder puts the identity in the path and the view in the query",
       ui.url("baci", "systems", "campaign_email", "designs", dstate="out")
       == "/admin/baci/systems/campaign_email/designs?dstate=out",
       ui.url("baci", "systems", "campaign_email", "designs", dstate="out"))
    ck("  and the cross-account view is a word, not a punctuation mark",
       ui.url("", "content") == "/admin/all/content")
    for path in ("/admin/baci/brand", "/admin/baci/systems",
                 "/admin/baci/systems/campaign_email/designs",
                 f"/admin/baci/systems/campaign_email/designs/{design}",
                 "/admin/all/content"):
        got = c.get(path, headers=BROWSER)
        ck(f"  {path} answers", got.status_code == 200, str(got.status_code))
    room = c.get("/admin/baci/systems/campaign_email/designs", headers=BROWSER)
    ck("the room named in the PATH is the room that renders",
       "Designs" in room.text and "Add this reference" in room.text)
    one = c.get(f"/admin/baci/systems/campaign_email/designs/{design}", headers=BROWSER)
    ck("  and one design has an address of its own that says what it is",
       "A design" in one.text and "every design" in one.text)

    print("\n— what the console EMITS —")
    brand = c.get("/admin/baci/brand", headers=BROWSER).text
    ck("every tab in the frame is a path",
       'href="/admin/baci/systems"' in brand and "/admin/ui?tab=systems" not in brand)
    sysp = c.get("/admin/baci/systems/campaign_email", headers=BROWSER).text
    ck("  and so is every room on a system's rail",
       "/admin/baci/systems/campaign_email/designs" in sysp
       and "wf=designs" not in sysp)
    ck("  the shelf's own rows and its search keep the path",
       f"/admin/baci/systems/campaign_email/designs/{design}" in room.text)

    print("\n— nothing that already worked stopped working —")
    for old in ("/admin/ui?tab=brand&tenant=baci",
                "/admin/ui?tab=systems&tenant=baci&system=campaign_email&wf=designs"):
        ck(f"  {old[:52]} still resolves",
           c.get(old, headers=BROWSER).status_code == 200)
    ck("a named route is not shadowed by the path pattern",
       c.get("/admin/work/nope", headers=BROWSER, follow_redirects=False).status_code != 404)

    print("\n— the pattern routes are declared LAST, or they eat what comes after —")
    paths = [getattr(r_, "path", "") for r_ in web.app.routes]
    pattern_at = [i for i, p in enumerate(paths) if p.startswith("/admin/{tenant}/{tab}")]
    named_admin = [i for i, p in enumerate(paths)
                   if p.startswith("/admin/") and not p.startswith("/admin/{")]
    ck("every named admin route is registered before them",
       max(named_admin) < min(pattern_at),
       "Starlette matches in declaration order: a route added below these "
       "would answer the console instead of itself")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}\n  " + "\n  ".join(_fail))
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
