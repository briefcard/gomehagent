"""Shopify implementation backend for the `seo` role.

One of the pluggable site backends (see sites.backend): same function surface as
wordpress_seo, so the SEO tools and approval executors are platform-agnostic.
Every function takes a site *profile* (sites.get) and uses profile['creds_key']
as the SHOPIFY_STORES key. The agent PROPOSES; write helpers run ONLY from the
approval executor after Gomeh approves.

Shopify strips <script> from body_html, so JSON-LD rides on the
seo.structured_data metafield and is rendered into <head> by a one-time theme
snippet (install_schema_renderer). Hence INLINE_JSONLD = False.
"""
import json

import httpx

from . import data_tools

API_VERSION = data_tools.API_VERSION
SEO_KEYS = ("title_tag", "description_tag")
INLINE_JSONLD = False  # Shopify body_html drops <script>; use the metafield path


def _store(profile: dict) -> str:
    return profile["creds_key"]


def _cfg(store: str) -> dict:
    """`{domain, token}` for a store key, the client's own connection first.

    Was `config.SHOPIFY_STORES[store]` — the env group and nothing else. A
    store the client connected themselves has no entry there, so the domain
    lookup raised `KeyError` on a connection that was live and verified.
    `credentials.shopify_config` is the same precedence `data_tools` already
    reads the TOKEN through; the domain was simply never brought with it, which
    is how one credential ended up half-resolved.
    """
    from . import credentials
    return credentials.shopify_config(store) or {}


def _base(store: str) -> str:
    return f"https://{_cfg(store)['domain']}/admin/api/{API_VERSION}"


def _headers(store: str) -> dict:
    return {"X-Shopify-Access-Token": data_tools._shopify_token(store),
            "Content-Type": "application/json"}


def _get(store: str, path: str, params: dict | None = None) -> dict:
    r = httpx.get(f"{_base(store)}/{path}", headers=_headers(store),
                  params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def _send(store: str, method: str, path: str, body: dict) -> dict:
    r = httpx.request(method, f"{_base(store)}/{path}", headers=_headers(store),
                      json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def _store_url(store: str) -> str:
    return f"https://{_cfg(store)['domain']}"


def _ok(profile: dict) -> str | None:
    """The gate in front of every read and every publish.

    Membership in `config.SHOPIFY_STORES` used to BE this check, so a client who
    connected their store through the console passed every other layer —
    stored, probed, `commerce` granted, shown connected — and was refused here
    and told to edit an env var. Resolution is by tenant now (see
    `app/connections.py`), which is the only form that can find a store
    connected by OAuth, since that store has no env key to be keyed by.
    """
    from . import connections
    cfg, refusal = connections.platform_config(profile)
    return None if cfg else refusal


def _seo_metafields(fields: dict) -> list:
    """SEO title/meta tags + JSON-LD (seo.structured_data) as a metafields array."""
    mfs = []
    if fields.get("seo_title") is not None:
        mfs.append({"namespace": "global", "key": "title_tag",
                    "type": "single_line_text_field", "value": fields["seo_title"]})
    if fields.get("seo_description") is not None:
        mfs.append({"namespace": "global", "key": "description_tag",
                    "type": "single_line_text_field", "value": fields["seo_description"]})
    sd = fields.get("structured_data")
    if sd:
        mfs.append({"namespace": "seo", "key": "structured_data", "type": "json",
                    "value": sd if isinstance(sd, str) else json.dumps(sd)})
    return mfs


# ---------------------------------------------------------------------------
# Read (no approval) — the real catalog, so links/product references are grounded
# ---------------------------------------------------------------------------
def list_collections(profile: dict) -> str:
    err = _ok(profile)
    if err:
        return err
    store = _store(profile)
    out = []
    for kind in ("custom_collections", "smart_collections"):
        cols = _get(store, f"{kind}.json",
                    {"limit": 250, "fields": "id,title,handle"}).get(kind, [])
        out += [{"id": c["id"], "title": c["title"], "handle": c["handle"],
                 "url": f"{_store_url(store)}/collections/{c['handle']}", "type": kind}
                for c in cols]
    return json.dumps(out)


def find_items(profile: dict, query: str = "", limit: int = 20) -> str:
    """Find products by title substring — real ids/handles/URLs to link to."""
    err = _ok(profile)
    if err:
        return err
    store = _store(profile)
    prods = _get(store, "products.json",
                 {"limit": 250, "fields": "id,title,handle,product_type"}).get("products", [])
    q = (query or "").lower()
    hits = [{"id": p["id"], "title": p["title"], "handle": p["handle"],
             "url": f"{_store_url(store)}/products/{p['handle']}",
             "type": p.get("product_type", "")}
            for p in prods if q in p["title"].lower()]
    return json.dumps(hits[:int(limit or 20)]) if hits else f"No products matching '{query}'."


def get_seo(profile: dict, resource: str, resource_id: str) -> str:
    err = _ok(profile)
    if err:
        return err
    store = _store(profile)
    if resource == "product":
        obj = _get(store, f"products/{resource_id}.json",
                   {"fields": "id,title,handle,body_html"}).get("product", {})
        owner, kind = f"products/{resource_id}", "products"
    else:
        obj = _get(store, f"collections/{resource_id}.json").get("collection", {})
        owner, kind = f"collections/{resource_id}", "collections"
    mfs = _get(store, f"{owner}/metafields.json",
               {"namespace": "global"}).get("metafields", [])
    seo = {m["key"]: m["value"] for m in mfs if m["key"] in SEO_KEYS}
    return json.dumps({
        "id": obj.get("id"), "title": obj.get("title"), "handle": obj.get("handle"),
        "url": f"{_store_url(store)}/{kind}/{obj.get('handle')}",
        "description_html": (obj.get("body_html") or "")[:1500],
        "seo_title": seo.get("title_tag", ""),
        "seo_description": seo.get("description_tag", "")})


# ---------------------------------------------------------------------------
# Write — called ONLY by the approval executor, after Gomeh approves
# ---------------------------------------------------------------------------
def _collection_endpoint(store: str, collection_id) -> tuple[str, str]:
    try:
        _get(store, f"custom_collections/{collection_id}.json", {"fields": "id"})
        return "custom_collections", "custom_collection"
    except httpx.HTTPStatusError:
        return "smart_collections", "smart_collection"


def update_seo(profile: dict, resource: str, resource_id, fields: dict) -> str:
    from . import seo_guard
    if (refusal := seo_guard.check(profile, fields, what="SEO update")):
        return refusal
    store = _store(profile)
    if resource == "product":
        endpoint, root, kind = "products", "product", "products"
    else:
        endpoint, root = _collection_endpoint(store, resource_id)
        kind = "collections"
    body = {root: {"id": resource_id}}
    for k in ("title", "handle", "body_html"):
        if fields.get(k) is not None:
            body[root][k] = fields[k]
    mfs = _seo_metafields(fields)
    if mfs:
        body[root]["metafields"] = mfs
    res = _send(store, "PUT", f"{endpoint}/{resource_id}.json", body).get(root, {})
    return f"{_store_url(store)}/{kind}/{res.get('handle')}"


def create_collection(profile: dict, fields: dict, item_ids: list | None = None) -> str:
    from . import seo_guard
    if (refusal := seo_guard.check(profile, fields, what="new collection")):
        return refusal
    store = _store(profile)
    body = {"custom_collection": {"title": fields["title"]}}
    for k in ("handle", "body_html"):
        if fields.get(k):
            body["custom_collection"][k] = fields[k]
    mfs = _seo_metafields(fields)
    if mfs:
        body["custom_collection"]["metafields"] = mfs
    coll = _send(store, "POST", "custom_collections.json", body).get("custom_collection", {})
    cid = coll.get("id")
    for pid in (item_ids or []):
        _send(store, "POST", "collects.json",
              {"collect": {"collection_id": cid, "product_id": pid}})
    return f"{_store_url(store)}/collections/{coll.get('handle')}"


def create_page(profile: dict, fields: dict) -> str:
    from . import seo_guard
    if (refusal := seo_guard.check(profile, fields, what="new page")):
        return refusal
    store = _store(profile)
    body = {"page": {"title": fields["title"], "body_html": fields.get("body_html", "")}}
    if fields.get("handle"):
        body["page"]["handle"] = fields["handle"]
    mfs = _seo_metafields(fields)
    if mfs:
        body["page"]["metafields"] = mfs
    page = _send(store, "POST", "pages.json", body).get("page", {})
    return f"{_store_url(store)}/pages/{page.get('handle')}"


# ---------------------------------------------------------------------------
# The blog. Articles were missing entirely: `update_seo` reaches products and
# collections, `create_page` makes a PAGE, and nothing in this file had ever
# touched `blogs/{id}/articles.json`. A store's blog is where most SEO copy
# actually lives, so the whole content half of the plan had no publish path.
# ---------------------------------------------------------------------------

def list_blogs(profile: dict) -> str:
    """A store can have several blogs ("News", "Guides"); the id is needed for
    everything else here, and guessing it publishes into the wrong one."""
    if (why := _ok(profile)):
        return why
    store = _store(profile)
    blogs = _get(store, "blogs.json").get("blogs", [])
    if not blogs:
        return ("This store has no blog. Shopify creates one named 'News' by "
                "default — if it was deleted, add one in admin before "
                "publishing articles.")
    return "\n".join(f"{b['id']}  {b['title']}  /blogs/{b['handle']}"
                      for b in blogs)


def list_articles(profile: dict, blog_id, limit: int = 20) -> str:
    """What is already published, so a revision starts from the real text."""
    if (why := _ok(profile)):
        return why
    store = _store(profile)
    arts = _get(store, f"blogs/{blog_id}/articles.json",
                {"limit": min(int(limit or 20), 250)}).get("articles", [])
    if not arts:
        return f"No articles on blog {blog_id}."
    out = []
    for a in arts:
        state = "published" if a.get("published_at") else "DRAFT"
        out.append(f"{a['id']}  [{state}]  {a.get('title', '')}  "
                   f"/blogs/{a.get('handle', '')}")
    return "\n".join(out)


def get_article(profile: dict, blog_id, article_id) -> str:
    """The full article, INCLUDING its body.

    The body is returned rather than summarised because a revision that has not
    read the current text is a rewrite, and a rewrite of a page that already
    ranks is how a site loses positions it had.
    """
    if (why := _ok(profile)):
        return why
    store = _store(profile)
    a = _get(store, f"blogs/{blog_id}/articles/{article_id}.json").get("article", {})
    if not a:
        return f"No article {article_id} on blog {blog_id}."
    mf = _get(store, f"articles/{article_id}/metafields.json",
              {"namespace": "global"}).get("metafields", [])
    seo = {m["key"]: m.get("value", "") for m in mf}
    return json.dumps({
        "id": a.get("id"), "title": a.get("title"), "handle": a.get("handle"),
        "author": a.get("author"), "tags": a.get("tags"),
        "published_at": a.get("published_at"),
        "summary_html": a.get("summary_html"),
        "seo_title": seo.get("title_tag", ""),
        "seo_description": seo.get("description_tag", ""),
        "body_html": a.get("body_html", ""),
    }, indent=2)


def create_article(profile: dict, blog_id, fields: dict) -> str:
    """Write a NEW article. Unpublished unless `published` is explicitly true.

    A draft by default is the whole point: this is the one call here that can
    put prose nobody has read on a public site, and `published=True` has to be
    a decision somebody made rather than the absence of one.
    """
    if (why := _ok(profile)):
        return why
    if not (fields.get("title") or "").strip():
        return "An article needs a title."
    if not (fields.get("body_html") or "").strip():
        return "An article needs a body — an empty post is worse than none."
    from . import seo_guard
    if (refusal := seo_guard.check(profile, fields, what="new article")):
        return refusal

    store = _store(profile)
    art = {"title": fields["title"], "body_html": fields["body_html"],
           "published": bool(fields.get("published"))}
    for k in ("handle", "author", "tags", "summary_html"):
        if fields.get(k):
            art[k] = fields[k]
    mfs = _seo_metafields(fields)
    if mfs:
        art["metafields"] = mfs
    res = _send(store, "POST", f"blogs/{blog_id}/articles.json",
                {"article": art}).get("article", {})
    state = "published" if res.get("published_at") else "saved as a draft"
    return (f"{_store_url(store)}/blogs/{res.get('handle')} — {state}"
            + ("" if res.get("published_at") else
               " (publish it from admin, or pass published=true)"))


def update_article(profile: dict, blog_id, article_id, fields: dict) -> str:
    """Revise an existing article. Only the fields given are touched.

    Partial by design: a revision that sends every field rewrites the ones it
    was not asked to change, and an untouched `body_html` arriving as an empty
    string would blank a live page.
    """
    if (why := _ok(profile)):
        return why
    from . import seo_guard
    if (refusal := seo_guard.check(profile, fields, what="article revision")):
        return refusal

    store = _store(profile)
    art = {"id": article_id}
    for k in ("title", "handle", "body_html", "author", "tags",
              "summary_html", "published"):
        if fields.get(k) is not None:
            art[k] = fields[k]
    mfs = _seo_metafields(fields)
    if mfs:
        art["metafields"] = mfs
    if len(art) == 1 and not mfs:
        return "Nothing to change — give a title, body_html, tags or SEO fields."
    res = _send(store, "PUT", f"blogs/{blog_id}/articles/{article_id}.json",
                {"article": art}).get("article", {})
    return f"{_store_url(store)}/blogs/{res.get('handle')} — updated"


# ---------------------------------------------------------------------------
# One-time theme setup: render seo.structured_data into <head>
# ---------------------------------------------------------------------------
SNIPPET_KEY = "snippets/seo-structured-data.liquid"
SNIPPET_VALUE = """{%- liquid
  assign sd = nil
  if request.page_type == 'collection' and collection.metafields.seo.structured_data
    assign sd = collection.metafields.seo.structured_data
  elsif request.page_type == 'product' and product.metafields.seo.structured_data
    assign sd = product.metafields.seo.structured_data
  elsif request.page_type == 'page' and page.metafields.seo.structured_data
    assign sd = page.metafields.seo.structured_data
  endif
-%}
{%- if sd -%}
<script type="application/ld+json">{{ sd.value | json }}</script>
{%- endif -%}
"""
RENDER_TAG = "{% render 'seo-structured-data' %}"


def _main_theme_id(store: str):
    themes = _get(store, "themes.json", {"fields": "id,role"}).get("themes", [])
    main = next((t for t in themes if t.get("role") == "main"), None)
    return main["id"] if main else (themes[0]["id"] if themes else None)


def install_schema_renderer(profile: dict) -> str:
    """Create the snippet and include it before </head> in the main theme.
    Idempotent; reversible via Shopify's theme versions."""
    err = _ok(profile)
    if err:
        return err
    store = _store(profile)
    tid = _main_theme_id(store)
    if not tid:
        return "No theme found to install the structured-data renderer."
    _send(store, "PUT", f"themes/{tid}/assets.json",
          {"asset": {"key": SNIPPET_KEY, "value": SNIPPET_VALUE}})
    layout = _get(store, f"themes/{tid}/assets.json",
                  {"asset[key]": "layout/theme.liquid"}).get("asset", {}).get("value", "")
    if RENDER_TAG in layout:
        return f"Structured-data renderer already installed (theme {tid})."
    if "</head>" not in layout:
        return (f"Snippet created (theme {tid}), but couldn't find </head> in "
                "layout/theme.liquid — add {% render 'seo-structured-data' %} "
                "before </head> manually.")
    layout = layout.replace("</head>", f"  {RENDER_TAG}\n</head>", 1)
    _send(store, "PUT", f"themes/{tid}/assets.json",
          {"asset": {"key": "layout/theme.liquid", "value": layout}})
    return f"Installed structured-data renderer (snippet + <head> include) in theme {tid}."
