"""A WordPress article carries the featured image that was chosen for it.

`approvals._article_image_for` computes the hero, RIGHTS-CHECKS it, and hands
it over in `fields["image"]`. `shopify_seo.create_article` writes it. The word
"image" did not appear anywhere in `wordpress_seo.create_article`, which built
a payload of title, content, status, slug and excerpt — so every WordPress
article this platform ever published went out with a hero chosen, cleared and
discarded. Silently, which is why nobody found it by reading a post.

WordPress will not take a URL: `featured_media` is an ATTACHMENT ID. So the
hero has to be fetched and re-hosted into the client's own library first —
`put_image` already existed for exactly that and had never been called from
this path.

    python3 scripts/test_wordpress_carries_its_hero.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'wp.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, seo_guard, tenants  # noqa: E402
from app import wordpress_seo as wp  # noqa: E402

db.init_db()
tenants.seed()
# `create_article` imports the guard INSIDE the function, so the stub has to
# land on the module object itself, not on this module's name for it.
seo_guard.check = lambda *a, **k: ""

_fail: list[str] = []
PROFILE = {"platform": "wordpress", "site": "https://example.com",
           "user": "u", "app_password": "p"}
FIELDS = {"title": "A long lunch", "body_html": "<p>words</p>",
          "image": {"src": "https://cdn/hero.png", "alt": "a set table"}}


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _stub(*, fetch_ok=True, upload_ok=True):
    sent: dict = {}
    uploaded: dict = {}

    class _Resp:
        content = b"PNGBYTES"
        def raise_for_status(self): pass

    def _get(url, **kw):
        if not fetch_ok:
            raise RuntimeError("boom")
        uploaded["fetched"] = url
        return _Resp()

    wp.httpx.get = _get
    wp.put_image = lambda profile, blob, *, filename, alt="": (
        uploaded.update(blob=blob, filename=filename, alt=alt)
        or ({"ok": True, "id": 4242, "url": "https://example.com/h.png"}
            if upload_ok else {"ok": False, "error": "WordPress refused it"}))

    def _send(profile, method, path, body):
        if path == "posts":
            sent.update(body)
            return {"id": 7, "link": "https://example.com/a-long-lunch"}
        return {}
    wp._send = _send
    wp._apply_plugin_meta = lambda *a, **k: None
    return sent, uploaded


def main() -> int:
    print("— the hero reaches the post —")
    sent, up = _stub()
    out = wp.create_article(PROFILE, fields=dict(FIELDS))
    ck("the payload carries featured_media", "featured_media" in sent,
       str(sorted(sent)))
    ck("  set to the ATTACHMENT ID, not the URL",
       sent.get("featured_media") == 4242, repr(sent.get("featured_media")))
    ck("  because WordPress will not take a src URL",
       not any(str(v).startswith("https://cdn/") for v in sent.values()), "")
    ck("the picture was fetched from where the hero actually lives",
       up.get("fetched") == "https://cdn/hero.png", str(up.get("fetched")))
    ck("  and re-hosted in the CLIENT's own library with its alt text",
       up.get("blob") == b"PNGBYTES" and up.get("alt") == "a set table",
       str({k: v for k, v in up.items() if k != "blob"}))
    ck("  under a filename taken from the source, not a guess",
       up.get("filename") == "hero.png", str(up.get("filename")))
    ck("the article still reports where it landed", "a-long-lunch" in out, out[:70])

    print("\n— an article with no hero is not broken by asking —")
    sent2, up2 = _stub()
    wp.create_article(PROFILE, fields={"title": "t", "body_html": "<p>b</p>"})
    ck("no image means no featured_media and no upload",
       "featured_media" not in sent2 and not up2, str(sorted(sent2)))

    print("\n— a hero that does not arrive is SAID, never dropped quietly —")
    sent3, _ = _stub(upload_ok=False)
    out3 = wp.create_article(PROFILE, fields=dict(FIELDS))
    ck("the post is still published — the prose is the article",
       "a-long-lunch" in out3 and "featured_media" not in sent3, out3[:60])
    ck("  and the reply says the hero did not make it, and why",
       "no hero" in out3 and "WordPress refused it" in out3, out3[-90:])
    sent4, _ = _stub(fetch_ok=False)
    out4 = wp.create_article(PROFILE, fields=dict(FIELDS))
    ck("a hero that could not be FETCHED is named too",
       "could not be fetched" in out4 and "featured_media" not in sent4,
       out4[-90:])
    ck("  which is the whole point: replacing a silent drop with a silent "
       "drop would be no fix",
       "no hero" in out4, "")

    print("\n— and the id still rides on the reply —")
    from app import sites
    ck("the platform id survives the added note",
       sites.article_id_in(out) == "7", repr(sites.article_id_in(out)))
    ck("  even when the hero failed",
       sites.article_id_in(out3) == "7", repr(sites.article_id_in(out3)))

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
