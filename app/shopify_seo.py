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

from . import config, data_tools

API_VERSION = data_tools.API_VERSION
SEO_KEYS = ("title_tag", "description_tag")
INLINE_JSONLD = False  # Shopify body_html drops <script>; use the metafield path


def _store(profile: dict) -> str:
    return profile["creds_key"]


def _base(store: str) -> str:
    return f"https://{config.SHOPIFY_STORES[store]['domain']}/admin/api/{API_VERSION}"


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
    return f"https://{config.SHOPIFY_STORES[store]['domain']}"


def _ok(profile: dict) -> str | None:
    if _store(profile) not in config.SHOPIFY_STORES:
        return (f"Shopify store '{_store(profile)}' not configured for site "
                f"'{profile['key']}'. Available: {list(config.SHOPIFY_STORES)}")
    return None


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
