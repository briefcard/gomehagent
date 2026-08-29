"""An article publishes with its picture, or says why it has none.

Owner, 2026-08-29: "Eien health has shown that despite having a connected
shopify we cannot push automatically with images and structure to shopify from
within the app."

Three separate causes, and fixing any one alone would have changed nothing:

  1. `shopify_seo.create_article` never sent an `image` field. Shopify shows
     the featured image on the blog index, in the article header and in every
     share card, so an article without one is not a smaller version of the
     same post — it is the one that looks broken beside the rest of the blog.
  2. `_run_blog_article` attached no media at all. Only `campaign_email` ever
     called the hero picker, so there was nothing to send even once the field
     existed.
  3. A store with exactly ONE blog was refused for having no `blog_id`. The
     rule ("a store can hold several blogs and guessing writes to the wrong
     place") is right and was applied one step too widely: it also refused the
     case where there is nothing to guess. Shopify creates one blog by default
     and most stores never add a second, so the commonest account drafted
     articles that could never be queued.

AND THE RIGHTS GATE HAS A SECOND DOOR. `ledger.publish` refuses an output
whose attached asset is reference-only, and it is the last place that can be
caught — but the SEO arm does not go through `ledger.publish`. Without the
same check in the approval executor, a comp image would have had exactly one
route to a public page.

    python3 scripts/test_article_image.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ai.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import approvals, db, kb, kb_seed, shopify_seo, tenants  # noqa: E402
from app import wordpress_seo  # noqa: E402

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    print("— the field the store was never sent —")
    ck("a prepared image is passed through",
       shopify_seo._article_image(
           {"image": {"src": "https://x/a.png"}, "title": "T"})
       == {"src": "https://x/a.png", "alt": "T"})
    ck("…and a bare URL works too",
       shopify_seo._article_image({"image": "https://x/b.png", "title": "T"})
       == {"src": "https://x/b.png", "alt": "T"},
       "the obvious way somebody passes one by hand")
    ck("no image means no field, not an empty one",
       shopify_seo._article_image({"title": "T"}) == {},
       "an empty image object would blank a live article's picture")
    ck("alt text falls back to the title, never to nothing",
       shopify_seo._article_image(
           {"image": {"src": "https://x/c.png"}, "title": "Third-party tested"}
       )["alt"] == "Third-party tested",
       "a featured image with no alt is an accessibility failure on a public "
       "page and a wasted ranking signal on the one surface built for ranking")

    print("\n— and the rights gate gets its second door —")
    kb.add_asset("baci", "https://x/comp.png", rights="reference",
                 title="a comp", kind="image")
    kb.add_asset("baci", "https://x/owned.png", rights="owned",
                 title="our photograph", kind="image")
    rows = {a.url: a for a in kb.assets("baci", publishable_only=False)}
    comp, owned = rows["https://x/comp.png"], rows["https://x/owned.png"]

    with db.SessionLocal() as s:
        bad = db.Output(tenant="baci", system_key="blog",
                        format="cms_article", media_ids=[comp.id])
        good = db.Output(tenant="baci", system_key="blog",
                         format="cms_article", media_ids=[owned.id])
        both = db.Output(tenant="baci", system_key="blog",
                         format="cms_article", media_ids=[comp.id, owned.id])
        s.add_all([bad, good, both])
        s.commit()
        bad_id, good_id, both_id = bad.id, good.id, both.id

    ck("a reference-only asset cannot reach a public blog",
       approvals._article_image_for(bad_id) == {},
       "the SEO arm does not go through ledger.publish, so this is the only "
       "place it could still have been caught")
    ck("an owned one does",
       approvals._article_image_for(good_id).get("src") == "https://x/owned.png")
    ck("…and a mixed list skips the unusable and keeps going",
       approvals._article_image_for(both_id).get("src") == "https://x/owned.png",
       "refusing the whole article because one attachment is a comp would "
       "throw away a perfectly good photograph")
    ck("no media means no image field",
       approvals._article_image_for("") == {})

    print("\n— what was reviewed is what is pushed —")
    with db.SessionLocal() as s:
        s.add(db.ArtifactBody(tenant="baci", output_id=good_id,
                              system_key="blog", format="cms_article",
                              body="<p>The edited body.</p>",
                              meta={"title": "Edited title"}))
        s.commit()
    fields = approvals._fields_from_artifact(good_id, {"handle": "h",
                                                       "published": False})
    ck("the artifact's body and title win over the payload",
       fields["body_html"] == "<p>The edited body.</p>"
       and fields["title"] == "Edited title")
    ck("…and the image rides with them",
       fields.get("image", {}).get("src") == "https://x/owned.png",
       "joined at the one place the payload and the artifact already meet")
    ck("the machine-set half survives",
       fields["handle"] == "h" and fields["published"] is False)

    print("\n— what the store is actually SENT —")
    # THE HELPER IS NOT THE REQUEST, and sabotage said so: asserting on
    # `_article_image` stayed green when `create_article` stopped putting its
    # result in the body. Stub the two seams and read the payload.
    sent: dict = {}
    _real_send, _real_get, _real_ok = (shopify_seo._send, shopify_seo._get,
                                       shopify_seo._ok)
    _real_url = shopify_seo._store_url
    import app.seo_guard as _sg
    _real_check = _sg.check
    try:
        shopify_seo._ok = lambda profile: None
        shopify_seo._store_url = lambda store: "https://shop.example"
        _sg.check = lambda *a, **k: None
        shopify_seo._send = lambda store, method, path, body: (
            sent.update(body=body, path=path) or {"article": {
                "id": 1, "handle": "h", "published_at": "2026-08-29"}})
        shopify_seo._get = lambda store, path, params=None: (
            {"blog": {"handle": "news"}})
        shopify_seo.create_article(
            {"key": "baci", "platform": "shopify", "creds_key": "baci"}, 99,
            {"title": "T", "body_html": "<p>b</p>",
             "image": {"src": "https://x/owned.png"}})
        art = (sent.get("body") or {}).get("article", {})
        ck("the request carries the image",
           art.get("image", {}).get("src") == "https://x/owned.png",
           str(art.get("image")))
        ck("…with alt text",
           art.get("image", {}).get("alt") == "T")

        sent.clear()
        shopify_seo.create_article(
            {"key": "baci", "platform": "shopify", "creds_key": "baci"}, 99,
            {"title": "T", "body_html": "<p>b</p>"})
        ck("and no image key at all when there is none",
           "image" not in (sent.get("body") or {}).get("article", {}),
           "an empty image object blanks a live article's picture")

        print("\n— nothing to guess is not a choice —")
        shopify_seo._get = lambda store, path, params=None: (
            {"blogs": [{"id": 7, "title": "News"}]})
        ck("one blog resolves without asking",
           shopify_seo.sole_blog_id({"key": "baci", "platform": "shopify", "creds_key": "baci"}) == "7",
           "the commonest account drafted articles that could never be queued")
        shopify_seo._get = lambda store, path, params=None: (
            {"blogs": [{"id": 7, "title": "News"}, {"id": 8, "title": "Guides"}]})
        ck("two blogs still means ASK",
           shopify_seo.sole_blog_id({"key": "baci", "platform": "shopify", "creds_key": "baci"}) == "",
           "guessing between two writes into the wrong one")
        shopify_seo._get = lambda store, path, params=None: {"blogs": []}
        ck("no blog at all is not a blog",
           shopify_seo.sole_blog_id({"key": "baci", "platform": "shopify", "creds_key": "baci"}) == "")
    finally:
        shopify_seo._send, shopify_seo._get = _real_send, _real_get
        shopify_seo._ok, _sg.check = _real_ok, _real_check
        shopify_seo._store_url = _real_url

    ck("wordpress answers the question without a picker",
       wordpress_seo.sole_blog_id({}) == "wordpress",
       "asked of the backend rather than branched on the platform name")
    ck("an unreachable store stays silent rather than guessing",
       shopify_seo.sole_blog_id({"key": "nope", "platform": "shopify"}) == "",
       "a wrong blog id publishes into the wrong place, which is worse than "
       "not publishing")

    print("\n— one writer for where articles go —")
    ck("the choice is recorded", tenants.set_blog("baci", "12345") == "12345")
    t = tenants.get("baci")
    ck("…on the tenant, where every reader looks",
       (t.cms or {}).get("blog_id") == "12345")
    ck("an unknown account is refused by name",
       "unknown account" in tenants.set_blog("nobody", "1"))
    ck("an empty id changes nothing",
       "No blog id" in tenants.set_blog("baci", "")
       and (tenants.get("baci").cms or {}).get("blog_id") == "12345")

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
