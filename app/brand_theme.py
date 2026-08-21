"""Derive each client's visual identity into an owner-reviewed email THEME.

`email_render` made "looks like the brand" a per-client ``theme`` dict; this
module is where that dict comes from. The owner's design (2026-08-21): pull the
identity from what already exists — the **Canva brand kit** first (a designer
already maintains it), then the **Shopify store** (its brand settings, its
theme's social links, and the business address Shopify already holds — the
CAN-SPAM line), then the **site itself** (structured data, header logo, footer
links) — and let the owner review the result before any customer sees it.

Three rules, all inherited from the rest of this codebase:

* **Derived, never invented.** Every field the deriver fills names its source
  (`sources`, per field); a source that could not be consulted is named with
  why (`unavailable`); and a field no source could fill stays ABSENT — the
  renderer falls back to its plain defaults rather than to a guessed brand
  colour, and `missing_to_send` keeps naming the address gap. Absence survives
  to the output.

* **Proposed, never live.** `derive()` writes `KbBrand.theme_proposed` and
  nothing else. What emails actually render with is `KbBrand.theme`, written
  only by `approve()` — the owner's review, with their edits winning over
  anything derived. `live_theme()` never reads the proposal: an unreviewed
  logo, palette or mailing address must not ship because a crawler found it.
  Same rule as the send gate, applied to appearance.

* **Tenant-generic.** Nothing here names a client. Which Canva kit, which
  Shopify store and which site are all read off the tenant row, and the three
  source readers are module seams (`canva_kit`, `shop_json`, `shop_brand`,
  `shop_settings`, `fetch_page`) so the suite drives every path offline.

Precedence is the owner's stated order — Canva > Shopify > site — applied
field by field with first-set-wins, so a missing Canva kit costs exactly the
fields it would have supplied and nothing else. `colors.accent_text` is the
one computed value (readable text on the accent, by luminance arithmetic);
it is labelled as computed in the provenance, not attributed to a source.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from urllib.parse import urljoin, urlparse

from . import db, email_render, kb, tenants

# ---------------------------------------------------------------------------
# Small mechanics: dotted paths, contrast, font stacks
# ---------------------------------------------------------------------------


def _set(d: dict, path: str, value) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def _get(d: dict, path: str):
    for k in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _on(hexv: str) -> str:
    """Readable text colour on a fill — luminance arithmetic, not taste."""
    h = str(hexv or "").lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:                                            # noqa: BLE001
        return "#ffffff"
    return "#1c1e22" if (0.299 * r + 0.587 * g + 0.114 * b) > 160 else "#ffffff"


def _stack(family: str, kind: str) -> str:
    """A brand font as an email-safe stack: the family first, the renderer's
    default stack as the fallback — most email clients will not load a custom
    face, and a stack with no fallback renders Times."""
    fam = str(family or "").strip().strip("'\"")
    default = email_render._DEFAULT["font"].get(kind, "")
    if not fam:
        return ""
    if fam.lower() in default.lower():
        return default
    return f"'{fam}', {default}"


def _shopify_font(handle: str) -> str:
    """Shopify's font handle → a family name: 'assistant_n4' → 'Assistant'."""
    h = str(handle or "").strip()
    if not h:
        return ""
    h = re.sub(r"_[nib]\d+$", "", h)
    return h.replace("_", " ").strip().title()


_SOCIAL_HOSTS = (("instagram.com", "Instagram"), ("facebook.com", "Facebook"),
                 ("tiktok.com", "TikTok"), ("pinterest.com", "Pinterest"),
                 ("youtube.com", "YouTube"), ("linkedin.com", "LinkedIn"),
                 ("twitter.com", "X"), ("x.com", "X"))


def _socials(urls: list[str]) -> list[dict]:
    """Recognisable social PROFILE links, one per platform, first seen wins.
    Share/intent links are skipped — a 'share this page' button is not the
    brand's profile."""
    seen: set[str] = set()
    out: list[dict] = []
    for u in urls:
        low = str(u or "").lower()
        if not low.startswith("http") or "share" in low or "intent" in low:
            continue
        net = urlparse(low).netloc
        net = net[4:] if net.startswith("www.") else net
        for host, label in _SOCIAL_HOSTS:
            if (net == host or net.endswith("." + host)) and label not in seen:
                seen.add(label)
                out.append({"name": label, "url": str(u)})
                break
    return out


# ---------------------------------------------------------------------------
# The three sources. Each returns {ok, fields: {dotted_path: (value, source)}}
# or {ok: False, why} — a refusal that names what to fix. `partial` carries
# per-read failures inside a source that still yielded something.
# ---------------------------------------------------------------------------

def _canva_kit(tenant: str) -> dict:
    from . import canva
    return canva.brand_kit(tenant)


canva_kit = _canva_kit           # seam the suite replaces


def _from_canva(tenant: str) -> dict:
    got = canva_kit(tenant)
    if not got.get("ok"):
        return {"ok": False, "why": got.get("error", "Canva did not answer.")}
    kit = got.get("kit") or {}
    f: dict = {}
    if kit.get("logo_url"):
        f["logo_url"] = (kit["logo_url"], "canva brand kit")
    cols = kit.get("colors") or []
    if cols:
        f["colors.accent"] = (cols[0], "canva brand kit (first brand colour)")
        f["colors.accent_text"] = (_on(cols[0]), "computed for contrast on the accent")
    fonts = kit.get("fonts") or {}
    if fonts.get("heading"):
        f["font.heading"] = (_stack(fonts["heading"], "heading"), "canva brand kit")
    if fonts.get("body"):
        f["font.body"] = (_stack(fonts["body"], "body"), "canva brand kit")
    if not f:
        return {"ok": False, "why": ("the Canva brand kit was readable but held "
                                     "nothing usable (no logo, colours or fonts "
                                     "recognised in it).")}
    return {"ok": True, "fields": f}


def _store_for(tenant: str) -> tuple[str, str]:
    """The Shopify store key this tenant's calls go through, or ("", why)."""
    t = tenants.get(tenant)
    if not t:
        return "", f"unknown tenant {tenant!r}"
    store = t.shopify_store or tenant
    from . import config, credentials
    if credentials.shopify_config(store) or config.SHOPIFY_STORES.get(store):
        return store, ""
    return "", (f"{tenant} has no Shopify store connected (neither a client "
                f"credential nor SHOPIFY_STORES_JSON knows {store!r}).")


def _shop_json(store: str) -> dict:
    """The shop record — the registered business name/address Shopify holds."""
    from . import data_tools
    return data_tools._shopify(store, "shop.json").get("shop", {})


def _shop_brand(store: str) -> dict:
    """Shopify's own Brand settings (admin → Settings → Brand): semantically
    labelled colours, the uploaded logos, the slogan. GraphQL only — the REST
    surface never exposed it. First GraphQL call in this codebase; if the
    app's scopes don't cover it the error is reported by name and the deriver
    falls through, which is the designed behaviour for every source here."""
    import httpx

    from . import data_tools
    cfg = data_tools._store_cfg(store)
    r = httpx.post(
        f"https://{cfg['domain']}/admin/api/{data_tools.API_VERSION}/graphql.json",
        headers={"X-Shopify-Access-Token": data_tools._shopify_token(store),
                 "Content-Type": "application/json"},
        json={"query": ("{ shop { brand { slogan shortDescription "
                        "logo { image { url } } squareLogo { image { url } } "
                        "colors { primary { background foreground } "
                        "secondary { background foreground } } } } }")},
        timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(str(data["errors"])[:200])
    return ((data.get("data") or {}).get("shop") or {}).get("brand") or {}


def _shop_settings(store: str) -> dict:
    """The published theme's settings_data.json `current` block — where the
    social_*_link keys and the store's typography actually live."""
    from . import data_tools
    themes = data_tools._shopify(store, "themes.json").get("themes", [])
    main = next((t for t in themes if t.get("role") == "main"), None)
    if not main:
        return {}
    asset = data_tools._shopify(store, f"themes/{main['id']}/assets.json",
                                {"asset[key]": "config/settings_data.json"})
    raw = (asset.get("asset") or {}).get("value") or "{}"
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else {}
    except Exception:                                            # noqa: BLE001
        return {}
    current = parsed.get("current")
    if isinstance(current, str):                 # "current" can name a preset
        current = (parsed.get("presets") or {}).get(current)
    return current if isinstance(current, dict) else {}


shop_json = _shop_json           # seams the suite replaces
shop_brand = _shop_brand
shop_settings = _shop_settings


def _addr_from_shop(shop: dict) -> str:
    parts = [str(shop.get("address1") or ""), str(shop.get("city") or "")]
    region = " ".join(x for x in (str(shop.get("province_code")
                                      or shop.get("province") or ""),
                                  str(shop.get("zip") or "")) if x)
    parts += [region, str(shop.get("country_name") or shop.get("country") or "")]
    return ", ".join(p.strip() for p in parts if p and p.strip())


def _from_shopify(tenant: str) -> dict:
    store, why = _store_for(tenant)
    if why:
        return {"ok": False, "why": why}
    f: dict = {}
    partial: list[str] = []

    try:
        shop = shop_json(store) or {}
        addr = _addr_from_shop(shop)
        if addr:
            f["footer.address"] = (addr, "shopify shop record")
    except Exception as exc:                                     # noqa: BLE001
        partial.append(f"shop record: {exc.__class__.__name__}: {str(exc)[:120]}")

    try:
        brand = shop_brand(store) or {}
        prim = (brand.get("colors") or {}).get("primary")
        if isinstance(prim, list):
            prim = prim[0] if prim else {}
        bg = str((prim or {}).get("background") or "")
        fg = str((prim or {}).get("foreground") or "")
        if bg:
            f.setdefault("colors.accent", (bg, "shopify brand settings"))
            f.setdefault("colors.accent_text",
                         (fg, "shopify brand settings") if fg
                         else (_on(bg), "computed for contrast on the accent"))
        logo = (((brand.get("logo") or {}).get("image") or {}).get("url", "")
                or ((brand.get("squareLogo") or {}).get("image") or {}).get("url", ""))
        if logo:
            f.setdefault("logo_url", (logo, "shopify brand settings"))
        if brand.get("slogan"):
            f["footer.tagline"] = (str(brand["slogan"]), "shopify brand settings")
    except Exception as exc:                                     # noqa: BLE001
        partial.append(f"brand settings: {exc.__class__.__name__}: {str(exc)[:120]}")

    try:
        settings = shop_settings(store) or {}
        urls = [str(v) for k, v in settings.items()
                if k.startswith("social_") and k.endswith("_link") and v]
        soc = _socials(urls)
        if soc:
            f["footer.socials"] = (soc, "shopify theme settings")
        for key, path in (("type_header_font", "font.heading"),
                          ("type_body_font", "font.body")):
            fam = _shopify_font(settings.get(key) or "")
            if fam:
                f.setdefault(path, (_stack(fam, path.split(".")[1]),
                                    "shopify theme settings"))
    except Exception as exc:                                     # noqa: BLE001
        partial.append(f"theme settings: {exc.__class__.__name__}: {str(exc)[:120]}")

    if not f:
        return {"ok": False,
                "why": ("; ".join(partial)
                        or "Shopify answered with nothing usable.")}
    return {"ok": True, "fields": f, "partial": partial}


def _fetch_page(url: str) -> str:
    import httpx

    from . import compliance
    r = httpx.get(url, timeout=25, follow_redirects=True,
                  headers=compliance.HEADERS)
    r.raise_for_status()
    return r.text


fetch_page = _fetch_page         # seam the suite replaces

_LD_RE = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>",
                    re.S | re.I)
_ORG_TYPES = {"organization", "localbusiness", "store", "onlinestore",
              "corporation", "restaurant", "eventvenue"}


def _ld_nodes(html: str) -> list[dict]:
    out: list[dict] = []
    for m in _LD_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:                                        # noqa: BLE001
            continue
        stack = [data]
        while stack:
            n = stack.pop()
            if isinstance(n, list):
                stack.extend(n)
            elif isinstance(n, dict):
                out.append(n)
                stack.extend(v for v in n.values() if isinstance(v, (dict, list)))
    return out


def _is_org(node: dict) -> bool:
    t = node.get("@type")
    names = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
    return any(str(x).lower() in _ORG_TYPES for x in names)


def _addr_from_ld(a: dict) -> str:
    parts = [str(a.get("streetAddress") or ""), str(a.get("addressLocality") or "")]
    region = " ".join(x for x in (str(a.get("addressRegion") or ""),
                                  str(a.get("postalCode") or "")) if x)
    country = a.get("addressCountry") or ""
    if isinstance(country, dict):
        country = country.get("name", "")
    parts += [region, str(country)]
    return ", ".join(p.strip() for p in parts if p and p.strip())


def _meta_content(html: str, name: str) -> str:
    for m in re.finditer(r"<meta\b[^>]*>", html or "", re.I):
        tag = m.group(0)
        if re.search(rf'name=["\']{name}["\']', tag, re.I):
            c = re.search(r'content=["\']([^"\']*)', tag, re.I)
            if c:
                return c.group(1).strip()
    return ""


def _logo_img(html: str) -> str:
    """The first <img> that says it is the logo. Header images only — the
    scan stops at 40k characters so a 'logo' in a footer badge wall does not
    become the brand mark."""
    for m in re.finditer(r"<img\b[^>]*>", (html or "")[:40_000], re.I):
        tag = m.group(0)
        if re.search(r"logo", tag, re.I) and not re.search(r"payment|badge", tag, re.I):
            src = re.search(r'src=["\']([^"\']+)', tag, re.I)
            if src:
                return src.group(1).strip()
    return ""


def _from_site(tenant: str) -> dict:
    t = tenants.get(tenant)
    dom = (t.domain or "").strip() if t else ""
    if not dom:
        return {"ok": False, "why": (f"{tenant} has no domain on its tenant "
                                     f"row, so there is no site to read.")}
    url = dom if dom.startswith("http") else f"https://{dom}"
    try:
        page = fetch_page(url)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "why": (f"the site at {url} could not be fetched: "
                                     f"{exc.__class__.__name__}: {str(exc)[:120]}")}
    f: dict = {}
    # Of the organization-shaped nodes, read the one that actually carries
    # identity — a page can hold several (@graph), and the first in walk order
    # is often a bare stub beside a complete LocalBusiness.
    orgs = [n for n in _ld_nodes(page) if _is_org(n)]
    org = max(orgs, key=lambda n: sum(1 for k in ("logo", "address", "sameAs")
                                      if n.get(k)), default={})

    logo = org.get("logo", "")
    if isinstance(logo, dict):
        logo = logo.get("url", "")
    via = "site (structured data)"
    if not logo:
        logo, via = _logo_img(page), "site (header image)"
    if logo:
        f["logo_url"] = (urljoin(url, str(logo)), via)

    addr = org.get("address")
    if isinstance(addr, dict):
        line = _addr_from_ld(addr)
        if line:
            f["footer.address"] = (line, "site (structured data)")

    hrefs = re.findall(r'href=["\']([^"\']+)', page or "", re.I)
    soc = _socials([str(u) for u in (org.get("sameAs") or [])] + hrefs)
    if soc:
        f["footer.socials"] = (soc, "site (footer links)")

    tc = _meta_content(page, "theme-color")
    if tc.startswith("#"):
        f["colors.accent"] = (tc, "site (theme-color)")
        f["colors.accent_text"] = (_on(tc), "computed for contrast on the accent")

    if not f:
        return {"ok": False, "why": (f"the site at {url} was read but held "
                                     f"nothing recognisable (no structured "
                                     f"data, logo image, social links or "
                                     f"theme colour).")}
    return {"ok": True, "fields": f}


# ---------------------------------------------------------------------------
# Derive → propose. Review → approve. Read → live.
# ---------------------------------------------------------------------------

_SOURCES = (("canva", _from_canva), ("shopify", _from_shopify),
            ("site", _from_site))


def derive(tenant: str) -> dict:
    """Read every reachable source and write the PROPOSED theme, with
    per-field provenance and every unreachable source named. Never touches the
    live theme — `approve` is the only writer of that, because the owner is.
    """
    t = tenants.get(tenant)
    if not t:
        return {"ok": False, "error": f"unknown tenant {tenant!r}"}
    b = kb.ensure_brand(tenant, t.name)
    name = b.display_name or t.name or tenant

    theme: dict = {}
    provenance: dict = {}
    _set(theme, "name", name)
    provenance["name"] = "brand KB"
    _set(theme, "footer.brand", name)
    provenance["footer.brand"] = "brand KB"

    unavailable: dict = {}
    partial: dict = {}
    for src, fn in _SOURCES:
        got = fn(tenant)
        if not got.get("ok"):
            unavailable[src] = got.get("why", "")
            continue
        if got.get("partial"):
            partial[src] = got["partial"]
        for path, (value, sub) in got["fields"].items():
            if _get(theme, path) in ("", None, [], {}):
                _set(theme, path, value)
                provenance[path] = sub

    proposed = {"theme": theme, "sources": provenance,
                "unavailable": unavailable, "partial": partial,
                "gaps": email_render.missing_to_send(theme),
                "derived_at": dt.datetime.now(dt.timezone.utc)
                .isoformat(timespec="seconds")}
    kb.set_brand(tenant, theme_proposed=proposed)
    return {"ok": True, "tenant": tenant, **proposed}


def proposed(tenant: str) -> dict:
    row = kb.brand(tenant)
    return dict((row.theme_proposed if row else None) or {})


def live_theme(tenant: str) -> dict:
    """The approved theme emails render with, or {} when none is approved yet.

    NEVER falls back to `theme_proposed`: the proposal is machine-derived and
    unreviewed, and the substrate does not ship a look the owner has not seen —
    the same rule as the send gate, applied to appearance. `sabotage.
    theme_review_gate` removes exactly this distinction and the suite must
    notice.
    """
    row = kb.brand(tenant)
    if not row:
        return {}
    return dict(row.theme or {})


def _allowed_edits() -> dict[str, type]:
    """The editable theme fields, derived from the renderer's own default
    shape rather than typed out here — rule 4; a hand-kept list is how the
    form and the renderer drift."""
    out: dict[str, type] = {}
    for k, v in email_render._DEFAULT.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out[f"{k}.{k2}"] = type(v2)
        else:
            out[k] = type(v)
    return out


def approve(tenant: str, edits: dict | None = None) -> dict:
    """The owner's review: promote the proposal to the LIVE theme, their edits
    winning over anything derived. The only writer of `KbBrand.theme`.

    Approving with gaps still open is allowed — an approved theme with no
    address renders a plainer email that `missing_to_send` keeps calling
    un-sendable, and blocking the approval would gatekeep rather than enrich.
    The gaps are returned so the decision is made knowingly, never silently.
    """
    t = tenants.get(tenant)
    if not t:
        return {"ok": False, "error": f"unknown tenant {tenant!r}"}
    row = kb.brand(tenant)
    prop = dict((row.theme_proposed if row else None) or {})
    base = dict(prop.get("theme") or {})
    already = dict((row.theme if row else None) or {})
    if not base and not already and not edits:
        return {"ok": False, "error": (
            f"nothing to approve for {tenant} — run the deriver first, or "
            f"supply the fields by hand (footer.address at minimum).")}
    theme = json.loads(json.dumps(base or already))   # a deep copy, plainly
    theme.pop("_meta", None)

    applied: list[str] = []
    allowed = _allowed_edits()
    for path, value in (edits or {}).items():
        if path not in allowed:
            return {"ok": False, "error": (
                f"unknown theme field {path!r} — the theme's shape is "
                f"email_render's; editable fields are "
                + ", ".join(sorted(allowed)))}
        if isinstance(value, str) and not value.strip():
            continue                       # a blank form input is not an edit
        want = allowed[path]
        if want is list and not isinstance(value, list):
            return {"ok": False, "error": f"{path} takes a list, got "
                                          f"{type(value).__name__}"}
        if want is int:
            try:
                value = int(value)
            except Exception:                                   # noqa: BLE001
                return {"ok": False, "error": f"{path} takes a number"}
        _set(theme, path, value)
        applied.append(path)

    # "Approved is final, whatever wrote it first." A field the owner ever
    # edited by hand survives a machine re-derive: promoting a fresh proposal
    # carries the previous approval's edited values forward unless this
    # approval explicitly re-edits them. Without this, correcting the mailing
    # address once would silently revert on the next derive-and-approve.
    carried: list[str] = []
    if base and already:
        for path in (already.get("_meta") or {}).get("edited", []):
            prev_val = _get(already, path)
            if path in allowed and path not in applied \
                    and prev_val not in ("", None):
                _set(theme, path, prev_val)
                carried.append(path)

    # Identity comes from the brand KB whatever the form said nothing about.
    if not theme.get("name"):
        _set(theme, "name", (row.display_name if row else "") or tenant)
    if not _get(theme, "footer.brand"):
        _set(theme, "footer.brand", theme["name"])

    theme["_meta"] = {"approved_at": dt.datetime.now(dt.timezone.utc)
                      .isoformat(timespec="seconds"),
                      "derived_at": prop.get("derived_at", ""),
                      "sources": prop.get("sources", {}),
                      # Owner-decided fields, cumulative — this is what the
                      # carry-forward above reads on the NEXT approval.
                      "edited": sorted(set(applied) | set(carried))}
    kb.set_brand(tenant, theme=theme, theme_proposed={})
    gaps = email_render.missing_to_send(theme)
    return {"ok": True, "tenant": tenant, "theme": theme, "gaps": gaps,
            "edited": applied, "carried": carried,
            "note": ("" if not gaps else
                     "approved, and still not sendable: " + "; ".join(gaps))}


def status(tenant: str) -> dict:
    """Where this client's theme stands — for the review page and for anything
    deciding whether a campaign can be sendable yet."""
    t = tenants.get(tenant)
    if not t:
        return {"ok": False, "error": f"unknown tenant {tenant!r}"}
    live = live_theme(tenant)
    prop = proposed(tenant)
    return {"ok": True, "tenant": tenant,
            "live": bool(live),
            "live_gaps": email_render.missing_to_send(live) if live else [],
            "approved_at": (live.get("_meta") or {}).get("approved_at", ""),
            "proposed": bool(prop.get("theme")),
            "derived_at": prop.get("derived_at", ""),
            "proposed_gaps": prop.get("gaps", []),
            "sources": prop.get("sources", {}),
            "unavailable": prop.get("unavailable", {}),
            "partial": prop.get("partial", {}),
            "note": ("" if live else
                     "no approved theme yet — campaign emails render on the "
                     "default look with no mailing address and stay marked "
                     "not-yet-sendable")}


#: What the review page renders through each theme so the owner judges a real
#: email rather than a swatch table. Neutral tokens stay visible — the preview
#: is upstream of `esp.personalize` by design.
PREVIEW_BLOCKS = [
    {"type": "hero", "headline": "A sample campaign",
     "sub": "This is how this brand's emails will look — logo, colours, type "
            "and the legal footer all come from the theme under review."},
    {"type": "text", "html": "<p>Hi {{FIRST_NAME}},</p><p>Body copy renders in "
                             "the brand's body face at a comfortable measure. "
                             "The button below carries the accent colour.</p>"},
    {"type": "cta", "label": "Visit the store", "url": "#"},
]
