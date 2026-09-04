"""An article never gets stuck because nobody chose a blog.

Owner, 2026-09-04: *"Right now our system is not able to publish to shopify or
other sources until a blog is chosen. Firstly, we dont have that setting to set
it in our brand page but secondly if it's not set or doesn't exist we should
create a blog called MarketingThatWorks.co and publish to that so that it
doesn't get stuck in publishing due to a missing blog."*

Both stuck states are real and this suite reproduces each before proving it
gone:

  · TWO OR MORE BLOGS AND NO CHOICE — the run refused with "pick one on the
    Plan tab, then re-run", so every article this account ever wrote was
    written and never queued;
  · ZERO BLOGS — `sole_blog_id` needs exactly one, so a store whose News blog
    was deleted hit the same refusal, and the refusal said the store "holds
    more than one blog", which was the opposite of true.

And the third, which nothing caught at all: a blog id recorded at DRAFT time
and deleted before the approval was a 404 at the only moment that matters.

What must hold now: one resolver (`sites.ensure_blog`) answers for the run and
for the publish arm; it prefers what the owner chose, then the store's own
single blog, then a blog of ours — found or created once; a store it cannot
READ creates nothing, because a blog is not the repair for a credential; and
every automatic destination is SAID, on the run and on the Brand tab, with the
control to change it.

    python3 scripts/test_blog_destination.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'bd.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, shopify_seo, sites, tenants, web  # noqa: E402

KEY = "s3cret"
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


# ── the store, as a dict of blogs. The transport is stubbed at `_get`/`_send`
# so the REAL `blogs()`, `create_blog()` and `sole_blog_id()` run: a suite that
# stubs `blogs()` proves its own stub.
STORE: dict = {"blogs": [], "readable": True, "writable": True}
CALLS: list = []


def _fake_get(store, path, params=None):
    CALLS.append(("GET", path))
    if not STORE["readable"]:
        raise RuntimeError("401 Unauthorized")
    if path == "blogs.json":
        return {"blogs": list(STORE["blogs"])}
    return {}


def _fake_send(store, method, path, body):
    CALLS.append((method, path))
    if path == "blogs.json" and method == "POST":
        if not STORE["writable"]:
            raise RuntimeError("422 Unprocessable")
        new = {"id": 900 + len(STORE["blogs"]),
               "title": (body.get("blog") or {}).get("title", ""),
               "handle": "made"}
        STORE["blogs"].append(new)
        return {"blog": new}
    if "/articles.json" in path:
        bid = path.split("/")[1]
        if bid not in [str(b["id"]) for b in STORE["blogs"]]:
            raise RuntimeError(f"404 blog {bid} not found")
        return {"article": {"id": 5, "handle": "a"}}
    return {}


shopify_seo._get = _fake_get
shopify_seo._send = _fake_send
shopify_seo._ok = lambda profile: None
shopify_seo._store = lambda profile: "baci"
shopify_seo._store_url = lambda store: "https://baci.example"

PROFILE = {"key": "baci", "platform": "shopify", "creds_key": "baci"}
sites.get = lambda tenant: (PROFILE if tenant != "wp"
                            else {"key": "wp", "platform": "wordpress"})


def _blogs(*titles):
    STORE["blogs"] = [{"id": 100 + i, "title": t, "handle": t.lower()}
                      for i, t in enumerate(titles)]
    STORE["readable"] = STORE["writable"] = True


def _recorded(tenant="baci"):
    t = tenants.get(tenant)
    return str((getattr(t, "cms", None) or {}).get("blog_id") or "")


def _set_cms(tenant, **fields):
    with db.SessionLocal() as s:
        row = s.get(db.Tenant, tenant)
        row.cms = {"platform": "shopify", "creds_key": tenant, **fields}
        s.commit()


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— REPRODUCTION: what used to strand an article —")
    _blogs("News", "Guides")
    _set_cms("baci")
    ck("two blogs and no choice: `sole_blog_id` gives nothing",
       shopify_seo.sole_blog_id(PROFILE) == "",
       "the rule that refuses to guess, which is right, and was the whole answer")
    _blogs()
    ck("zero blogs: it gives nothing either, for a different reason",
       shopify_seo.sole_blog_id(PROFILE) == "",
       "and the run's refusal said the store 'holds more than one blog'")

    print("\n— the resolver prefers what the owner chose —")
    _blogs("News", "Guides")
    _set_cms("baci", blog_id="101")
    got = sites.ensure_blog("baci")
    ck("a recorded blog that still exists is used, untouched",
       got["ok"] and got["blog_id"] == "101" and got["source"] == "recorded"
       and not got["created"], str(got))
    ck("  and nothing is said, because nothing was decided for them",
       sites.blog_note(got) == "")

    print("\n— the store's own blog, when there is exactly one —")
    _blogs("News")
    _set_cms("baci")
    got = sites.ensure_blog("baci")
    ck("one blog is not a choice — it is used and RECORDED",
       got["ok"] and got["source"] == "sole" and got["blog_id"] == "100"
       and _recorded() == "100", str(got))
    ck("  and said, because an automatic destination must not be silent",
       "one blog" in sites.blog_note(got), sites.blog_note(got))
    ck("  no blog was created", len(STORE["blogs"]) == 1)

    print("\n— two blogs and no choice: ours is CREATED, once —")
    _blogs("News", "Guides")
    _set_cms("baci")
    CALLS.clear()
    got = sites.ensure_blog("baci")
    ck("it creates the fallback rather than guessing between theirs",
       got["ok"] and got["source"] == "fallback_created" and got["created"],
       str(got))
    ck(f"  named exactly {sites.FALLBACK_BLOG_TITLE!r}",
       any(b["title"] == sites.FALLBACK_BLOG_TITLE for b in STORE["blogs"]),
       str([b["title"] for b in STORE["blogs"]]))
    ck("  recorded, so the next run does not decide again",
       _recorded() == got["blog_id"])
    ck("  and said, naming what was made and where to change it",
       sites.FALLBACK_BLOG_TITLE in sites.blog_note(got)
       and "Brand tab" in sites.blog_note(got), sites.blog_note(got))
    made_id = got["blog_id"]
    _set_cms("baci")
    n_before = len(STORE["blogs"])
    again = sites.ensure_blog("baci")
    ck("a second account with no choice FINDS it instead of making another",
       again["blog_id"] == made_id and again["source"] == "fallback_found"
       and len(STORE["blogs"]) == n_before, str(again))
    ck("  and the POST was not repeated",
       [c for c in CALLS if c[0] == "POST"].__len__() == 1,
       str([c for c in CALLS if c[0] == "POST"]))

    print("\n— zero blogs: the same answer, not a different refusal —")
    _blogs()
    _set_cms("baci")
    got = sites.ensure_blog("baci")
    ck("an empty store gets one made", got["ok"] and got["created"]
       and got["source"] == "fallback_created", str(got))

    print("\n— a recorded blog that no longer exists is treated as absent —")
    _blogs("News", "Guides")
    _set_cms("baci", blog_id="777")
    got = sites.ensure_blog("baci")
    ck("the stale id is not used", got["ok"] and got["blog_id"] != "777",
       str(got))
    ck("  and the run SAYS the old one is gone",
       "no longer on the store" in sites.blog_note(got), sites.blog_note(got))
    ck("  the record is repointed", _recorded() == got["blog_id"])

    print("\n— A STORE THAT CANNOT BE READ CREATES NOTHING —")
    _blogs("News", "Guides")
    STORE["readable"] = False
    _set_cms("baci")
    n_before = len(STORE["blogs"])
    got = sites.ensure_blog("baci")
    ck("it refuses, rather than making a blog to fix a credential",
       not got["ok"] and len(STORE["blogs"]) == n_before, str(got))
    ck("  naming the connection as the thing that is wrong",
       "not the repair for a connection" in got["why"], got["why"])
    ck("  and the record is left alone", _recorded() == "")
    # …BUT A READ FAILURE MUST NOT DISCARD A CHOICE ALREADY MADE. An account
    # publishing happily for months should not be stranded by a slow morning
    # at Shopify, which is what confirming-or-refusing would have done.
    _set_cms("baci", blog_id="101")
    got = sites.ensure_blog("baci")
    ck("a recorded blog is used unconfirmed when the store cannot be read",
       got["ok"] and got["blog_id"] == "101" and got["source"] == "recorded",
       str(got))
    ck("  and the run says it could not be confirmed",
       "unconfirmed" in sites.blog_note(got), sites.blog_note(got))
    STORE["readable"] = True

    print("\n— a store that refuses the write says so and creates nothing —")
    _blogs("News", "Guides")
    _set_cms("baci")          # nothing chosen, so it must fall through to a write
    STORE["writable"] = False
    got = sites.ensure_blog("baci")
    ck("the failure is carried, not swallowed",
       not got["ok"] and "could not be created" in got["why"], str(got))
    STORE["writable"] = True

    print("\n— WordPress needs no blog, and is asked no questions —")
    CALLS.clear()
    got = sites.ensure_blog("wp")
    ck("it answers not_needed with no store call",
       got["ok"] and got["source"] == "not_needed" and not CALLS, str(got))

    print("\n— publishing no longer reports a missing blog as a gap —")
    _blogs("News", "Guides")
    _set_cms("baci")
    gap = sites.publish_gap("baci")
    ck("`publish_gap` is ok with no blog chosen", gap["ok"], str(gap))
    from app import credentials, keywords
    # THE PROBE, NOT THE VERDICT. `readiness` gates on the WIRED capability
    # (`credentials.wired_capabilities`), which needs a real stored token —
    # so a fixture that only writes `Tenant.cms` reads as "no CMS connected"
    # and the check below would fail for a reason that has nothing to do with
    # blogs. Stub the capability, exactly as the skill suites do.
    credentials.wired_capabilities = lambda t: {"cms": "shopify"}
    rd = keywords.readiness("baci", probe=False)
    pub = rd.get("publish") or {}
    ck("readiness says publishing is ready, and where it will go",
       pub.get("ok") is True and sites.FALLBACK_BLOG_TITLE in str(pub.get("detail")),
       str(pub))
    ck("  and still asks for the choice, so the control is not lost",
       pub.get("choose") is True, str(pub))

    print("\n— THE PUBLISH ARM re-resolves, so a deleted blog is not a 404 —")
    from app import approvals, kb, seo_guard, seo_tools, whatsapp
    approvals.notify_pending = lambda *a, **k: None
    _sent: list = []
    whatsapp.send_text = lambda t, *a, **k: _sent.append(t)
    seo_guard.tenant_for = lambda profile: "baci"
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.add_banned("baci", "hand-decorated")
    _blogs("News", "Guides")
    _set_cms("baci")
    out = seo_tools.dispatch(
        "propose_article",
        {"site": "baci", "blog_id": "9", "title": "Choosing an acrylic jug",
         "body_html": "<p>Acrylic holds cold longer.</p>"}, {})
    ck("an article queues carrying the blog id it was drafted against",
       "Queued" in out, out[:80])
    with db.SessionLocal() as s:
        ap = [a for a in s.query(db.Approval).all()
              if a.kind == "seo_new_article"][-1]
        ap_id, payload = ap.id, dict(ap.payload or {})
    ck("  and that id is the stale one", payload.get("blog_id") == "9")
    CALLS.clear()
    _sent.clear()
    approvals.apply_decision(ap_id, "approved")
    posted = [c for c in CALLS if c[0] == "POST" and "/articles.json" in c[1]]
    ck("the article was created, not 404'd on the dead blog",
       len(posted) == 1 and "/9/" not in posted[0][1], str(posted))
    ck("  into a blog that exists on the store",
       posted and posted[0][1].split("/")[1]
       in [str(b["id"]) for b in STORE["blogs"]], str(posted))
    ck("  which is ours, created because the store named none to use",
       any(b["title"] == sites.FALLBACK_BLOG_TITLE for b in STORE["blogs"]),
       str([b["title"] for b in STORE["blogs"]]))
    ck("  and the notification says where it went",
       any(sites.FALLBACK_BLOG_TITLE in t for t in _sent),
       str(_sent)[:200])

    print("\n— the setting is on the BRAND page, with its control —")
    # Back to nothing chosen: the publish arm above RECORDED the blog it
    # resolved, which is the point of it, and this section is about the page
    # an owner sees before any of that has happened.
    _set_cms("baci")
    c = TestClient(web.app)
    page = c.get(f"/admin/ui?key={KEY}&tab=brand&tenant=baci").text
    ck("Brand carries the destination", 'id="blog"' in page
       and "Where articles publish" in page)
    ck("  saying what happens when nothing is chosen",
       "not chosen" in page and sites.FALLBACK_BLOG_TITLE in page
       and "Nothing waits on this" in page)
    ck("  and offering the picker there",
       "Find the blogs on this store" in page and "tab=brand" in page)
    picked = c.get(f"/admin/ui?key={KEY}&tab=brand&tenant=baci&pick=1").text
    ck("the picker lists the store's blogs on Brand",
       "Guides" in picked and 'name="back" value="brand"' in picked, "")
    ck("  and no control hides inside a link — the Brand tab refuses that",
       "<button" not in picked.split('id="blog"')[1].split("</div>")[0]
       or "</a>" not in picked.split('id="blog"')[1].split("Find the blogs")[0],
       "a button inside an anchor is invalid and the anchor eats the click")
    r = c.get(f"/admin/blog_set?key={KEY}&tenant=baci&blog_id=101&back=brand",
              follow_redirects=False)
    ck("choosing one lands back on Brand, not on Plan",
       r.status_code == 303 and "tab=brand" in r.headers.get("location", "")
       and "#blog" in r.headers.get("location", ""),
       r.headers.get("location", ""))
    ck("  and it is recorded", _recorded() == "101")
    page = c.get(f"/admin/ui?key={KEY}&tab=brand&tenant=baci").text
    ck("  the page then names the blog it will use",
       "blog 101" in page and "not chosen" not in page)
    r = c.get(f"/admin/blog_set?key={KEY}&tenant=baci&blog_id=abc&back=brand",
              follow_redirects=False)
    ck("a junk id is refused where it was typed",
       "tab=brand" in r.headers.get("location", "")
       and "err=" in r.headers.get("location", ""), r.headers.get("location", ""))
    ck("  and the old choice survives", _recorded() == "101")
    r = c.get(f"/admin/blog_set?key={KEY}&tenant=baci&blog_id=102",
              follow_redirects=False)
    ck("without `back` it still lands on Plan, as it always did",
       "tab=plan" in r.headers.get("location", ""), r.headers.get("location", ""))

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
