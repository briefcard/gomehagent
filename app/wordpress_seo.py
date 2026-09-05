"""WordPress implementation backend for the `seo` role (e.g. MarketingThatWorks,
a service-based site). Same function surface as shopify_seo, so the SEO tools and
approval executors don't care about the platform.

Uses the WordPress REST API with Application Passwords (Basic auth). Credentials
resolve through `app/connections.py` — the client's own connection first, the
WORDPRESS_SITES env group second. This module read the env group directly until
2026-08-20, which made every client-connected install unpublishable.

Platform differences vs Shopify, handled here:
- WordPress KEEPS <script> in post content, so JSON-LD is embedded inline
  (INLINE_JSONLD = True) — no theme snippet needed (install_schema_renderer is a
  no-op).
- "collections" map to categories; "items" are pages/posts (services on a
  service site). create_collection falls back to a landing PAGE.
- SEO is handled with NATIVE WordPress fields — no SEO plugin required: the
  <title> tag follows the post title, and the meta description is written to the
  native `excerpt` field (themes/SEO plugins read the excerpt as the description).
  If Yoast/RankMath happen to be REST-exposed we ALSO set their precise meta as a
  bonus, but nothing depends on it (best-effort, never fatal).
"""
import json
import re

import httpx

from . import toolcalls as _tc


INLINE_JSONLD = True  # WordPress content keeps <script> -> embed JSON-LD inline


def _cfg(profile: dict) -> dict | None:
    """`{base_url, user, app_password}`, the client's own connection first.

    Was `config.WORDPRESS_SITES` and nothing else — so a WordPress install the
    client connected on `/connect/<token>` was stored encrypted, probed, shown
    as connected and granted `cms`, and every publish still refused. The
    connection was real and unreadable, which `credentials.google_config` had
    already written down as worse than absent. Resolution is by tenant now; see
    `app/connections.py`.
    """
    from . import connections
    cfg, _ = connections.platform_config(profile)
    return cfg or None


def _ok(profile: dict) -> str | None:
    from . import connections
    cfg, refusal = connections.platform_config(profile)
    return None if cfg else refusal


def _api(profile: dict) -> str:
    return _cfg(profile)["base_url"].rstrip("/") + "/wp-json/wp/v2"


def _auth(profile: dict) -> tuple:
    c = _cfg(profile)
    return (c["user"], c["app_password"])


def _tenant(profile: dict) -> str:
    from . import connections
    return connections.tenant_for_site((profile or {}).get("key", ""))


@_tc.http_seam("wordpress", _tenant, method="GET")
def _get(profile: dict, path: str, params: dict | None = None):
    r = httpx.get(f"{_api(profile)}/{path}", params=params or {},
                  auth=_auth(profile), timeout=30)
    r.raise_for_status()
    return r.json()


@_tc.http_seam("wordpress", _tenant)
def _send(profile: dict, method: str, path: str, body: dict) -> dict:
    r = httpx.request(method, f"{_api(profile)}/{path}", json=body,
                      auth=_auth(profile), timeout=30)
    r.raise_for_status()
    return r.json()


def put_image(profile: dict, blob: bytes, *, filename: str,
              alt: str = "") -> dict:
    """Put a picture in the client's OWN media library and return their URL.

    Owner, 2026-08-30: an approved frame belongs on the client's CMS, "so it's
    accessible to us". This is the WordPress half, and it needs nothing new —
    the application password already authenticates, and `upload_files` is a
    capability of the user it belongs to rather than a scope we have to ask
    for again.

    NOT `_send`: the media endpoint takes the file as the BODY with a
    `Content-Disposition` naming it, not JSON. A picture posted as JSON is
    accepted and stored as a zero-byte attachment, which is worse than a
    refusal because the URL works and the image does not.
    """
    why = _ok(profile)
    if why:
        return {"ok": False, "error": why}
    if not blob:
        return {"ok": False, "error": "no image to upload"}
    name = (filename or "image.png").replace('"', "")
    try:
        r = httpx.post(f"{_api(profile)}/media", content=blob,
                       auth=_auth(profile), timeout=60,
                       headers={"Content-Disposition": f'attachment; filename="{name}"',
                                "Content-Type": "image/png"})
        r.raise_for_status()
        got = r.json()
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"WordPress refused the upload: "
                                      f"{exc.__class__.__name__}"}
    url = str(got.get("source_url") or "")
    if not url:
        return {"ok": False, "error": "WordPress stored it but returned no URL"}
    # ALT TEXT IS ACCESSIBILITY, and it is one more call rather than a field on
    # the upload. Failing it does not fail the upload: a picture with no alt
    # text is a smaller problem than a picture that did not arrive.
    if alt:
        try:
            _send(profile, "POST", f"media/{got.get('id')}", {"alt_text": alt})
        except Exception:                                        # noqa: BLE001
            pass
    return {"ok": True, "url": url, "id": got.get("id"), "platform": "wordpress"}


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def _seo_meta(fields: dict) -> dict:
    """SEO title/description in the common WP SEO plugins' keys — set ONLY as a
    bonus if the site exposes them over REST (see _apply_plugin_meta)."""
    meta = {}
    if fields.get("seo_title") is not None:
        meta["_yoast_wpseo_title"] = fields["seo_title"]
        meta["rank_math_title"] = fields["seo_title"]
    if fields.get("seo_description") is not None:
        meta["_yoast_wpseo_metadesc"] = fields["seo_description"]
        meta["rank_math_description"] = fields["seo_description"]
    return meta


def _apply_plugin_meta(profile: dict, ptype: str, rid, fields: dict) -> None:
    """Best-effort: if Yoast/RankMath meta is REST-exposed, set the precise SEO
    title/description too. NEVER fatal — the native post title (title tag) and
    excerpt (meta description) already carry SEO, so this is pure upside."""
    meta = _seo_meta(fields)
    if not meta:
        return
    try:
        _send(profile, "PUT", f"{ptype}/{rid}", {"meta": meta})
    except Exception:  # noqa: BLE001 — meta not REST-exposed; native fields suffice
        pass


# ---------------------------------------------------------------------------
# Read (no approval)
# ---------------------------------------------------------------------------
def list_collections(profile: dict) -> str:
    err = _ok(profile)
    if err:
        return err
    cats = _get(profile, "categories", {"per_page": 100,
                "fields": "id,name,slug,link,count"})
    out = [{"id": c["id"], "title": c.get("name"), "handle": c.get("slug"),
            "url": c.get("link"), "type": "category", "count": c.get("count")}
           for c in cats]
    return json.dumps(out)


def find_items(profile: dict, query: str = "", limit: int = 20) -> str:
    """Search pages and posts (real ids/slugs/URLs) — what to link to or optimize."""
    err = _ok(profile)
    if err:
        return err
    out = []
    for ptype in ("pages", "posts"):
        try:
            items = _get(profile, ptype, {"search": query, "per_page": int(limit or 20),
                                          "_fields": "id,title,slug,link,type"})
            out += [{"id": i["id"], "title": i.get("title", {}).get("rendered", ""),
                     "handle": i.get("slug"), "url": i.get("link"),
                     "type": i.get("type", ptype[:-1])} for i in items]
        except Exception:  # noqa: BLE001 — a post type may be disabled
            continue
    return json.dumps(out[:int(limit or 20)]) if out else f"No content matching '{query}'."


def get_seo(profile: dict, resource: str, resource_id: str) -> str:
    err = _ok(profile)
    if err:
        return err
    ptype = "posts" if resource == "post" else "pages"
    obj = _get(profile, f"{ptype}/{resource_id}",
               {"_fields": "id,title,slug,link,content,excerpt,meta"})
    meta = obj.get("meta", {}) or {}
    title = obj.get("title", {}).get("rendered", "")
    return json.dumps({
        "id": obj.get("id"), "title": title,
        "handle": obj.get("slug"), "url": obj.get("link"),
        "description_html": (obj.get("content", {}).get("rendered", "") or "")[:1500],
        # title tag follows the post title; meta description follows the excerpt
        "seo_title": meta.get("_yoast_wpseo_title") or meta.get("rank_math_title") or title,
        "seo_description": (meta.get("_yoast_wpseo_metadesc")
                            or meta.get("rank_math_description")
                            or _text(obj.get("excerpt", {}).get("rendered", "")))})


# ---------------------------------------------------------------------------
# Write — called ONLY by the approval executor, after Gomeh approves
# ---------------------------------------------------------------------------
def update_seo(profile: dict, resource: str, resource_id, fields: dict) -> str:
    from . import seo_guard
    if (refusal := seo_guard.check(profile, fields, what="SEO update")):
        return refusal
    ptype = "posts" if resource == "post" else "pages"
    body: dict = {}
    if fields.get("title") is not None:
        body["title"] = fields["title"]          # drives the <title> tag natively
    if fields.get("handle") is not None:
        body["slug"] = fields["handle"]
    if fields.get("body_html") is not None:
        body["content"] = fields["body_html"]
    if fields.get("seo_description") is not None:
        body["excerpt"] = fields["seo_description"]  # native meta-description path
    obj = _send(profile, "PUT", f"{ptype}/{resource_id}", body)
    _apply_plugin_meta(profile, ptype, resource_id, fields)  # bonus, never fatal
    return obj.get("link", "(updated)")


def create_page(profile: dict, fields: dict) -> str:
    from . import seo_guard
    if (refusal := seo_guard.check(profile, fields, what="new page")):
        return refusal
    body = {"title": fields["title"], "content": fields.get("body_html", ""),
            "status": "publish"}
    if fields.get("handle"):
        body["slug"] = fields["handle"]
    if fields.get("seo_description") is not None:
        body["excerpt"] = fields["seo_description"]
    obj = _send(profile, "POST", "pages", body)
    _apply_plugin_meta(profile, "pages", obj.get("id"), fields)
    return obj.get("link", "(created)")


def list_articles(profile: dict, blog_id=None, limit: int = 20) -> str:
    """Published posts, newest first. `blog_id` is accepted and ignored —
    WordPress has one post type where Shopify has many blogs, and keeping the
    signatures identical is what lets `sites.backend()` stay duck-typed."""
    # `_get`, not `_send`. This called `_send(profile, "GET", "posts",
    # params=...)` — and `_send` takes `body` positionally and has no `params`,
    # so it raised TypeError before reaching WordPress. Same in `get_article`
    # below. Both were written to mirror `shopify_seo`'s shape, both are reads,
    # and neither has ever been called for real — which is the only reason a
    # TypeError on the happy path survived being shipped.
    posts = _get(profile, "posts",
                 {"per_page": min(int(limit or 20), 100),
                  "status": "publish,draft"}) or []
    if not posts:
        return "No posts."
    return "\n".join(
        f"{p.get('id')}  [{p.get('status')}]  "
        f"{(p.get('title') or {}).get('rendered', '')}  {p.get('link', '')}"
        for p in posts)


def get_article(profile: dict, blog_id=None, article_id=None) -> str:
    """The full post, body included — a revision that has not read the current
    text is a rewrite, and rewriting a page that ranks loses the position."""
    post = _get(profile, f"posts/{article_id}", {"context": "edit"})
    if not post:
        return f"No post {article_id}."
    return json.dumps({
        "id": post.get("id"), "status": post.get("status"),
        "title": (post.get("title") or {}).get("raw")
                 or (post.get("title") or {}).get("rendered", ""),
        "handle": post.get("slug"), "link": post.get("link"),
        "seo_description": (post.get("excerpt") or {}).get("raw", ""),
        "body_html": (post.get("content") or {}).get("raw")
                     or (post.get("content") or {}).get("rendered", ""),
    }, indent=2)


def sole_blog_id(profile: dict) -> str:
    """WordPress has one blog by definition, so there is never anything to
    pick. Present so callers can ask the question of any backend rather than
    branching on the platform name — the same duck-typing the rest of this
    module holds to."""
    return "wordpress"


def create_article(profile: dict, blog_id=None, fields: dict | None = None) -> str:
    """Write a NEW post. DRAFT unless `published` is explicitly true.

    Nothing here could create one before: `update_seo(resource="post")` revises
    an existing post and `create_page` writes to the `pages` endpoint, so the
    `blog` system — declared in `systems.CATALOG`, installed on Ironside — had
    no way to publish a new article at all.

    Note `create_page` next to this publishes immediately. That is a separate
    decision and left alone; an article defaults to draft because it is the
    longest piece of prose this platform writes and the one nobody skims.
    """
    fields = fields or {}
    if not (fields.get("title") or "").strip():
        return "A post needs a title."
    if not (fields.get("body_html") or "").strip():
        return "A post needs a body — an empty post is worse than none."
    from . import seo_guard
    if (refusal := seo_guard.check(profile, fields, what="new post")):
        return refusal

    body = {"title": fields["title"], "content": fields["body_html"],
            "status": "publish" if fields.get("published") else "draft"}
    if fields.get("handle"):
        body["slug"] = fields["handle"]
    if fields.get("seo_description") is not None:
        body["excerpt"] = fields["seo_description"]
    media_id, note = _featured_media(profile, fields)
    if media_id:
        body["featured_media"] = media_id
    obj = _send(profile, "POST", "posts", body)
    _apply_plugin_meta(profile, "posts", obj.get("id"), fields)
    from . import sites
    return sites.with_article_id(
        f"{obj.get('link', '(created)')} — "
        + ("published" if fields.get("published") else
           "saved as a draft (pass published=true to publish)")
        + note,
        obj.get("id"))


def _featured_media(profile: dict, fields: dict) -> tuple[int, str]:
    """The article's hero, re-hosted in the client's library, as an id.

    THE WORD "image" DID NOT APPEAR IN THIS MODULE'S ARTICLE WRITER.
    `approvals._article_image_for` computes the hero, rights-checks it and
    hands it over in `fields["image"]`; `shopify_seo` writes it; this built a
    payload of title, content, status, slug and excerpt and dropped it. Every
    WordPress article this platform has ever published went out with a
    featured image chosen, cleared and discarded — silently, which is why
    nobody found it by looking at a post.

    WordPress will not take a URL. `featured_media` is an ATTACHMENT ID, so a
    hero that exists as a URL — which is exactly what the field carries, and
    what Shopify accepts directly — has to be fetched and re-hosted first.
    `put_image` already does the hard half.

    Returns `(id, note)`. A picture that fails NEVER fails the article: the
    prose is the article, and refusing to publish it over a hero is a worse
    outcome than publishing without one. But it is always SAID — a hero that
    quietly did not arrive is the defect this function exists about, and
    replacing a silent drop with a different silent drop would be no fix.
    """
    img = fields.get("image")
    if isinstance(img, str):
        img = {"src": img.strip()} if img.strip() else None
    if not isinstance(img, dict):
        return 0, ""
    src = str(img.get("src") or img.get("url") or "").strip()
    if not src:
        return 0, ""
    alt = str(img.get("alt") or fields.get("title") or "").strip()
    try:
        r = httpx.get(src, timeout=30, follow_redirects=True)
        r.raise_for_status()
        blob = r.content
    except Exception as exc:                                     # noqa: BLE001
        return 0, (f" — the featured image could not be fetched from "
                   f"{src[:60]} ({exc.__class__.__name__}), so the post has "
                   f"no hero")
    name = (src.rsplit("/", 1)[-1].split("?")[0] or "hero.png")[:96]
    got = put_image(profile, blob, filename=name, alt=alt)
    if not got.get("ok") or not got.get("id"):
        return 0, (f" — the featured image did not upload "
                   f"({got.get('error', 'unknown')}), so the post has no hero")
    return int(got["id"]), ""


def update_article(profile: dict, blog_id=None, article_id=None,
                   fields: dict | None = None) -> str:
    """Revise an existing post, through the same guard as everything else."""
    fields = fields or {}
    from . import seo_guard
    if (refusal := seo_guard.check(profile, fields, what="post revision")):
        return refusal
    return update_seo(profile, "post", article_id, fields)


def list_blogs(profile: dict) -> str:
    """WordPress has one stream of posts, not several blogs. Answered rather
    than raising, so an agent written against the Shopify shape gets a sentence
    instead of an AttributeError."""
    return ("WordPress has a single posts stream — no blog id is needed. "
            "Use list_articles directly.")


def create_collection(profile: dict, fields: dict, item_ids: list | None = None) -> str:
    """WordPress has no product collection; create a landing PAGE instead. If
    item_ids (page/post ids) are given, append links to them in the body so the
    'collection' references real content."""
    if item_ids:
        links = []
        for iid in item_ids:
            try:
                it = _get(profile, f"pages/{iid}", {"_fields": "title,link"})
                links.append(f'<li><a href="{it.get("link")}">'
                             f'{it.get("title", {}).get("rendered", "")}</a></li>')
            except Exception:  # noqa: BLE001
                continue
        if links:
            fields = {**fields, "body_html": (fields.get("body_html", "")
                      + "\n<ul>" + "\n".join(links) + "</ul>")}
    return create_page(profile, fields)


def install_schema_renderer(profile: dict) -> str:
    return ("WordPress renders JSON-LD inline in page content — no theme setup "
            "needed (structured data is embedded directly when the page is created).")
