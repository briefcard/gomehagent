"""A draft is not a published page, and nothing counts it as one.

`approvals._published(res)` asks "did the write happen?" and answers it with
`str(res).startswith("http")`. That is correct for the question it asks — and
a DRAFT returns a URL too. Both backends prove it in their own replies:

    https://example.com/a-long-lunch — saved as a draft (pass published=true …)

That string starts with "http", so `keywords.mark_published` fired. It stamps
`KeywordTarget.status = "published"`, writes `published_at`, and starts the
30-day refresh clock. `progress` then feeds `planner.blog_rollout` and the
monthly client report — so next month's work was chosen, and SEO progress was
reported to a paying client, from rank readings for URLs nobody outside that
client can open.

And this was not an edge case. `skill_pack` sets `"published": False` and is
the only writer of that field on the blog path, so EVERY article this platform
writes lands as a draft. Every row.

The state now travels structurally, on the reply, next to the id — the
convention `with_article_id` already established. Only the STAGED case is
marked: an unmarked reply is treated as live, so any backend this does not
touch behaves exactly as before. Failing closed would re-starve `progress`,
which is the defect the 2026-08-26 audit existed to fix.

    python3 scripts/test_written_is_not_published.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'wp2.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import approvals, db, seo_guard, sites, tenants  # noqa: E402
from app import wordpress_seo as wp  # noqa: E402

db.init_db()
tenants.seed()
seo_guard.check = lambda *a, **k: ""

_fail: list[str] = []
PROFILE = {"platform": "wordpress", "site": "https://example.com",
           "user": "u", "app_password": "p"}


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _wp(published: bool) -> str:
    wp._send = lambda profile, method, path, body: (
        {"id": 7, "link": "https://example.com/a-long-lunch"}
        if path == "posts" else {})
    wp._apply_plugin_meta = lambda *a, **k: None
    wp._featured_media = lambda profile, fields: (0, "")
    return wp.create_article(PROFILE, fields={
        "title": "A long lunch", "body_html": "<p>words</p>",
        "published": published})


def main() -> int:
    print("— the reply carries the state, not just the address —")
    draft, live = _wp(False), _wp(True)
    ck("a draft still starts with a URL, which is why this was missed",
       draft.startswith("http"), draft[:52])
    ck("  so the old test cannot tell them apart",
       approvals._published(draft) and approvals._published(live),
       "both are True: `_published` asks a different question")
    ck("but `is_live` can", sites.is_live(live) and not sites.is_live(draft),
       f"live={sites.is_live(live)} draft={sites.is_live(draft)}")
    ck("  the draft is marked, the live page is not",
       "staged" in draft and "staged" not in live, draft[-40:])

    print("\n— and the id still rides on both —")
    ck("the platform id survives the state mark",
       sites.article_id_in(draft) == "7" and sites.article_id_in(live) == "7",
       f"{sites.article_id_in(draft)!r} / {sites.article_id_in(live)!r}")
    ck("  the human-readable words are untouched",
       "saved as a draft" in draft and "published" in live, "")

    print("\n— an unmarked reply is treated as live, on purpose —")
    ck("a bare URL from any other backend still counts as published",
       sites.is_live("https://x/y — created"),
       "failing closed here would re-starve `progress`, the 2026-08 defect")
    ck("  and a refusal is still not a publication",
       not sites.is_live("Refused — banned_claim: ...")
       and not sites.is_live(""), "")

    print("\n— shopify says it the same way, and this is CALLED not grepped —")
    # The first version of this assertion grepped shopify_seo.py for
    # "with_state" and the sabotage run reported MISSED: the name survives
    # `live=True`. A check that passes on the mutation is the hollow
    # assertion this repo has a whole harness about.
    from app import shopify_seo as sp
    sp.seo_guard = type("g", (), {"check": staticmethod(lambda *a, **k: "")})
    sp._ok = lambda profile: ""
    sp._store = lambda profile: {"shop": "s", "token": "t"}
    sp._store_url = lambda store: "https://shop.example.com"
    sp._get = lambda store, path: {"blog": {"handle": "news"}}

    def _shop(published_at):
        sp._send = lambda store, method, path, body: {
            "article": {"handle": "a-long-lunch",
                        "published_at": published_at}}
        return sp.create_article(
            {"platform": "shopify", "site": "https://shop.example.com"}, 1,
            {"title": "A long lunch", "body_html": "<p>words</p>"})

    s_draft, s_live = _shop(None), _shop("2026-09-05T00:00:00Z")
    ck("a Shopify draft is marked staged",
       not sites.is_live(s_draft) and "staged" in s_draft, s_draft[-46:])
    ck("  and a published one is not",
       sites.is_live(s_live) and "staged" not in s_live, s_live[-46:])
    ck("  both backends answer `is_live` the same way",
       sites.is_live(s_live) == sites.is_live(live)
       and sites.is_live(s_draft) == sites.is_live(draft),
       "two vocabularies for one idea is how this defect happened")

    print("\n— and the arm will not record a draft as ranking —")
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "approvals.py")).read()
    ck("mark_published is gated on the page being live",
       'if p.get("output_id") and sites.is_live(res):' in src, "")
    ck("  and the notification SAYS a page was staged",
       "Staged, not live" in src,
       "real work that is not yet earning, and only a person can chase it")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
