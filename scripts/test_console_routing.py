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

    print("\n— and NOTHING hand-writes a console address any more —")
    # THE RATCHET. A link built by hand is a link that will still be built by
    # hand after the next rename — and the address bar drifts back one card at
    # a time. The population is derived from the source, so a new one fails
    # here rather than on the owner's screen.
    import pathlib
    root = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    offenders = []
    for f in (root / "app").glob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            if "/admin/ui?" not in line:
                continue
            bare = line.strip()
            # A COMMENT MAY QUOTE THE OLD SHAPE — that is history, and the
            # commit that explains a change has to be allowed to name what it
            # changed. A tenant or a tab in a LIVE string is the defect.
            if bare.startswith(("#", "*", "Owner,", "(`", "`")) or '"""' in line:
                continue
            if "tab=" in line or "tenant=" in line:
                offenders.append(f"{f.name}:{n}")
    ck("no module hand-writes a console link with a tab or an account in it",
       not offenders, ", ".join(offenders[:6]))
    ck("  the one exception is the address with no account at all — "
       "the console, wherever you last were",
       '"/admin/ui?err="' in (root / "app" / "web.py").read_text(encoding="utf-8"))
    for f in ("app/admin_ui.py", "app/web.py"):
        src_ = (root / f).read_text(encoding="utf-8")
        ck(f"  {f} carries no key into a link either",
           "key={_esc(key)}&amp;tab=" not in src_ and "?key={key}&tab=" not in src_)

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}\n  " + "\n  ".join(_fail))
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
