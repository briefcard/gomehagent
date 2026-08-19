"""The ban list, on the path that publishes to a live customer site.

The audit that opened this session measured the inversion this closes:
`grep -c "banned|validator|compliance"` across `shopify_seo`, `wordpress_seo`
and `seo_tools` returned 0, 0, 0 — and those three are the only modules that
write to customer-facing properties. Everything that merely REPORTED had every
guarantee; the thing that PUBLISHED had none.

It is worse than "SEO metadata", which is how it was described for most of that
session and was wrong: `update_seo` writes `body_html`, and on WordPress with
`resource="post"` it replaces an article's entire `content`. Baci's own audit is
110 flagged strings, 96 of them one templated meta description, in exactly the
field this path writes.

    python3 scripts/test_seo_guard.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sg.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
# A configured store, so `_ok` does not short-circuit before the checks under
# test. Nothing here reaches the network: every assertion is on a refusal
# returned BEFORE the HTTP call, which is what proves the guard runs first.
os.environ["SHOPIFY_STORES_JSON"] = (
    '{"baci": {"domain": "baci.myshopify.com", "token": "shpat_test"}}')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import assurance, db, kb, seo_guard, shopify_seo, tenants, wordpress_seo  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


BACI = {"key": "baci", "domain": "bacimilanousa.com", "platform": "shopify",
        "creds_key": "baci"}


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.add_banned("baci", "hand-decorated")
    kb.add_banned("baci", "made in Italy")

    print("— the site is matched to an account, or nothing publishes —")
    ck("a known domain resolves", seo_guard.tenant_for(BACI) == "baci")
    unknown = seo_guard.check({"key": "x", "domain": "nowhere.example"},
                              {"title": "hand-decorated"})
    ck("an unmatched site is REFUSED, not waved through",
       "no ban list" in unknown.lower(),
       "a site nobody has matched has no ban list, and publishing to it "
       "unchecked is the same hole one layer down")

    print("\n— what the field actually is —")
    ck("clean copy passes",
       seo_guard.check(BACI, {"title": "Aqua jug", "body_html": "Acrylic."}) == "")
    bad = seo_guard.check(BACI, {"body_html": "Every piece is hand-decorated."})
    ck("a banned phrase in the BODY is caught", bad != "",
       "body_html is description copy, not metadata")
    ck("  and the field is named, not just the rule",
       "body_html" in bad, bad[:90])
    ck("  it says nothing was published",
       "Nothing was published" in bad)
    ck("a banned phrase in the meta description is caught",
       seo_guard.check(BACI, {"seo_description": "Made in Italy since 1994"}) != "",
       "96 of Baci's 110 violations are one templated meta description")
    ck("empty fields are not an error", seo_guard.check(BACI, {}) == "")

    print("\n— citation is NOT demanded —")
    ck("an SEO title with no claim behind it still passes",
       seo_guard.check(BACI, {"seo_title": "Italian-designed tableware"}) == "",
       "a guard that fires on everything is a guard somebody removes")

    print("\n— every check is on the record —")
    rep = assurance.report("baci", 30)
    ck("the seo path reports as its own source", "seo" in rep["by_source"])
    ck("  passes are counted too, not only catches",
       rep["by_source"]["seo"]["checks"] > rep["by_source"]["seo"]["caught"])

    print("\n— every writer goes through it —")
    # No network: a refusal is returned before any HTTP call is attempted, so
    # reaching the refusal IS the proof the guard runs first.
    dirty = {"title": "Hand-decorated jug", "body_html": "x"}
    for name, fn in (
            ("shopify update_seo", lambda: shopify_seo.update_seo(BACI, "product", 1, dirty)),
            ("shopify create_page", lambda: shopify_seo.create_page(BACI, dirty)),
            ("shopify create_collection", lambda: shopify_seo.create_collection(BACI, dirty)),
            ("shopify create_article", lambda: shopify_seo.create_article(BACI, 9, dirty)),
            ("shopify update_article", lambda: shopify_seo.update_article(BACI, 9, 1, dirty)),
    ):
        ck(f"  {name} refuses before it calls out",
           "Refused" in fn() or "not configured" in fn(), "")

    # A domain no tenant claims — marketingthatworks.co is the AGENCY's, so it
    # matches and would be checked against the agency's ban list instead.
    WP = {"key": "stranger", "domain": "nobody-owns-this.example",
          "platform": "wordpress"}
    ck("an unmatched WordPress site refuses too",
       "no ban list" in wordpress_seo.create_article(WP, fields=dirty).lower(),
       wordpress_seo.create_article(WP, fields=dirty)[:70])

    print("\n— the blog path exists at all —")
    for fn in ("list_blogs", "list_articles", "get_article", "create_article",
               "update_article"):
        ck(f"  shopify.{fn}", hasattr(shopify_seo, fn))
        ck(f"  wordpress.{fn}", hasattr(wordpress_seo, fn),
           "the backends are duck-typed, so a missing one is an AttributeError "
           "mid-publish")

    print("\n— a new article is a DRAFT unless somebody says otherwise —")
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "shopify_seo.py")).read()
    ck("shopify create_article defaults published to false",
       '"published": bool(fields.get("published"))' in src)
    wsrc = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "wordpress_seo.py")).read()
    ck("wordpress create_article defaults to draft",
       '"publish" if fields.get("published") else "draft"' in wsrc,
       "this is the one call that can put unread prose on a public site")

    print("\n— an article needs a body —")
    ck("no title is refused", "needs a title" in
       shopify_seo.create_article(BACI, 9, {"body_html": "x"}),
       shopify_seo.create_article(BACI, 9, {"body_html": "x"})[:60])
    ck("no body is refused", "worse than none" in
       shopify_seo.create_article(BACI, 9, {"title": "x"}),
       shopify_seo.create_article(BACI, 9, {"title": "x"})[:60])

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
