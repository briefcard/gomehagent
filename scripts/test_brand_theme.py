"""The brand-theme deriver: Canva → Shopify → site, owner-reviewed, then live.

What is checked is the GOVERNANCE, not any live API: every source is a module
seam this suite replaces. The invariants: precedence is Canva > Shopify > site
per field with provenance recorded; a source that cannot be consulted is named
with why and costs only its own fields; a field no source fills stays absent
(no invented colours, no invented address); `derive` writes the PROPOSAL only
and the live theme — the one `skill_pack._theme_for` renders with — changes
ONLY through `approve`, where the owner's edits win. sabotage.theme_review_gate
removes the proposed/live distinction and this suite must fail when it does.

Run: python3 scripts/test_brand_theme.py
"""
import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'bt.db')}"
os.environ["APPROVAL_SECRET"] = "test-secret"
# Only baci has a store in the env blob, so eien's Shopify source refuses.
os.environ["SHOPIFY_STORES_JSON"] = json.dumps(
    {"baci": {"domain": "baci.example.myshopify.com", "token": "shpat_test"}})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import brand_theme, db, email_render, kb, tenants  # noqa: E402

_fail: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


# ---------------------------------------------------------------------------
# Stub sources. Only baci has a Canva kit; only ironside has a readable site.
# ---------------------------------------------------------------------------

_KIT = {"ok": True, "brand_kit_id": "bk1",
        "kit": {"logo_url": "https://cdn.canva.example/baci-logo.png",
                "colors": ["#7A1E3A", "#F5EFE6"],
                "fonts": {"heading": "Cormorant Garamond", "body": "Lato"}}}

_SHOP = {"name": "Baci Milano USA", "address1": "2875 NE 191st St",
         "city": "Aventura", "province_code": "FL", "zip": "33180",
         "country_name": "United States"}

_BRAND = {"slogan": "La tavola, vestita.",
          "logo": {"image": {"url": "https://cdn.shopify.example/baci-logo.svg"}},
          "colors": {"primary": [{"background": "#123456",
                                  "foreground": "#fafafa"}],
                     "secondary": []}}

_SETTINGS = {"type_header_font": "cormorant_n4", "type_body_font": "lato_n4",
             "social_instagram_link": "https://instagram.com/bacimilanousa",
             "social_facebook_link": "https://www.facebook.com/bacimilanousa",
             "social_pinterest_link": ""}

_SITE_HTML = """<!doctype html><html><head>
<meta name="theme-color" content="#0b3d2e">
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"EventVenue","name":"Ironside stub"},
 {"@type":"LocalBusiness","name":"MIAMI IRONSIDE",
  "logo":"/img/ironside-logo.png",
  "sameAs":["https://www.instagram.com/miamironside",
            "https://facebook.com/share/xyz"],
  "address":{"@type":"PostalAddress","streetAddress":"7580 NE 4th Ct",
   "addressLocality":"Miami","addressRegion":"FL","postalCode":"33138",
   "addressCountry":"US"}}]}
</script></head><body>
<header><img class="site-logo" src="/img/header.png" alt="logo mark"></header>
<footer><a href="https://twitter.com/intent/tweet?u=x">share</a>
<a href="https://x.com/miamironside">X</a>
<a href="https://www.youtube.com/@ironside">YouTube</a></footer>
</body></html>"""

_canva_on = {"baci"}
_shopify_on = {"baci"}


def _stub_kit(tenant):
    if tenant in _canva_on:
        return dict(_KIT)
    return {"ok": False, "error": f"{tenant} has no Canva connection, and "
                                  f"neither has the agency — connect one."}


def _stub_shop(store):
    if store.split(".")[0] in ("baci",) or store == "baci":
        return dict(_SHOP)
    raise RuntimeError("no such store")


def _stub_brand(store):
    return dict(_BRAND)


def _stub_settings(store):
    return dict(_SETTINGS)


def _stub_fetch(url):
    if "ironside" in url:
        return _SITE_HTML
    raise RuntimeError(f"connect refused for {url}")


def main() -> int:  # noqa: PLR0915
    db.init_db()
    tenants.seed()
    brand_theme.canva_kit = _stub_kit
    brand_theme.shop_json = _stub_shop
    brand_theme.shop_brand = _stub_brand
    brand_theme.shop_settings = _stub_settings
    brand_theme.fetch_page = _stub_fetch

    # Deterministic tenant wiring, independent of what seed() chose.
    with db.SessionLocal() as s:
        for key, domain, store in (("baci", "", "baci"),
                                   ("eien", "", ""),
                                   ("ironside", "miamiironside.example", ""),
                                   ("coverings", "", "")):
            row = s.get(db.Tenant, key)
            row.domain = domain
            row.shopify_store = store
        s.commit()
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.ensure_brand("ironside", "Miami Ironside")

    print("— refusals name the missing thing —")
    ck("derive refuses an unknown tenant",
       not brand_theme.derive("nope").get("ok")
       and "unknown tenant" in brand_theme.derive("nope").get("error", ""))
    ck("approve refuses an unknown tenant",
       "unknown tenant" in brand_theme.approve("nope").get("error", ""))
    ck("status refuses an unknown tenant",
       "unknown tenant" in brand_theme.status("nope").get("error", ""))

    print("\n— the full chain: Canva > Shopify > site, field by field —")
    got = brand_theme.derive("baci")
    ck("derive succeeds with sources available", got.get("ok") is True)
    t = got["theme"]
    src = got["sources"]
    ck("logo comes from Canva, not Shopify",
       t.get("logo_url") == _KIT["kit"]["logo_url"]
       and src.get("logo_url") == "canva brand kit", str(t.get("logo_url")))
    ck("accent is Canva's first brand colour",
       t["colors"]["accent"] == "#7A1E3A"
       and "canva" in src.get("colors.accent", ""))
    ck("accent text is computed for contrast (dark accent → white)",
       t["colors"]["accent_text"] == "#ffffff"
       and "computed" in src.get("colors.accent_text", ""))
    ck("heading font is Canva's, as a stack with email-safe fallbacks",
       t["font"]["heading"].startswith("'Cormorant Garamond', ")
       and "serif" in t["font"]["heading"], t["font"]["heading"])
    ck("mailing address comes from the Shopify shop record",
       t["footer"]["address"] == "2875 NE 191st St, Aventura, FL 33180, "
                                 "United States"
       and src.get("footer.address") == "shopify shop record",
       t["footer"].get("address", ""))
    ck("tagline is the Shopify brand slogan",
       t["footer"]["tagline"] == "La tavola, vestita."
       and src.get("footer.tagline") == "shopify brand settings")
    ck("socials come from theme settings, empty links dropped",
       [x["name"] for x in t["footer"]["socials"]] == ["Instagram", "Facebook"]
       and src.get("footer.socials") == "shopify theme settings",
       str(t["footer"].get("socials")))
    ck("name and footer.brand are brand-KB identity",
       t["name"] == "Baci Milano USA" and t["footer"]["brand"] == "Baci Milano USA"
       and src.get("name") == "brand KB")
    ck("site was unavailable and says why (no domain)",
       "no domain" in got["unavailable"].get("site", ""),
       got["unavailable"].get("site", ""))
    ck("a fully-derived theme has no send gaps", got["gaps"] == [])

    print("\n— derive proposes; NOTHING ships until the owner approves —")
    ck("derive wrote the proposal", brand_theme.proposed("baci").get("theme") is not None)
    ck("the live theme is still empty after derive",
       brand_theme.live_theme("baci") == {})
    from app import skill_pack
    fb = skill_pack._theme_for("baci")
    ck("campaign emails still render on the fallback (no address)",
       fb["footer"].get("address", "") == "" and fb["name"] == "Baci Milano USA")
    html_before = email_render.render(fb, brand_theme.PREVIEW_BLOCKS)
    ck("…and the rendered email carries the loud NOT-SENDABLE placeholder",
       "NO MAILING ADDRESS ON FILE" in html_before)

    print("\n— approval promotes, and the owner's edits win —")
    ok = brand_theme.approve("baci", {"footer.address":
                                      "999 Owner St, Miami, FL 33101, USA",
                                      "width": "640"})
    ck("approve succeeds", ok.get("ok") is True, ok.get("error", ""))
    live = brand_theme.live_theme("baci")
    ck("the owner's address beat the derived one",
       live["footer"]["address"] == "999 Owner St, Miami, FL 33101, USA")
    ck("numeric fields are coerced (width '640' → 640)", live.get("width") == 640)
    ck("provenance and edit trail ride on the approved theme",
       live.get("_meta", {}).get("sources", {}).get("logo_url") == "canva brand kit"
       and live["_meta"]["edited"] == ["footer.address", "width"])
    ck("the proposal is cleared once reviewed",
       brand_theme.proposed("baci") == {})
    themed = skill_pack._theme_for("baci")
    ck("campaign emails now render the approved theme",
       themed["colors"]["accent"] == "#7A1E3A"
       and themed["footer"]["address"].startswith("999 Owner St"))
    html_after = email_render.render(themed, brand_theme.PREVIEW_BLOCKS)
    ck("…sendable: real address in the footer, no placeholder",
       "999 Owner St" in html_after
       and "NO MAILING ADDRESS ON FILE" not in html_after)
    ck("missing_to_send agrees", email_render.missing_to_send(themed) == [])

    print("\n— re-derive must not touch what the owner approved —")
    kit2 = json.loads(json.dumps(_KIT))
    kit2["kit"]["colors"] = ["#000000"]
    brand_theme.canva_kit = lambda t: kit2 if t in _canva_on else _stub_kit(t)
    got2 = brand_theme.derive("baci")
    ck("re-derive updates the proposal",
       got2["theme"]["colors"]["accent"] == "#000000")
    ck("…and the LIVE theme is unchanged (approved is final)",
       brand_theme.live_theme("baci")["colors"]["accent"] == "#7A1E3A")
    brand_theme.canva_kit = _stub_kit

    print("\n— edits are validated against the renderer's own shape —")
    bad = brand_theme.approve("baci", {"colors.primary": "#000"})
    ck("an unknown field is refused by name",
       "unknown theme field" in bad.get("error", "")
       and "colors.primary" in bad.get("error", ""), bad.get("error", "")[:80])
    bad = brand_theme.approve("baci", {"nav": "not-a-list"})
    ck("a list field refuses a string", "takes a list" in bad.get("error", ""))
    ck("a refused approval writes nothing",
       brand_theme.live_theme("baci")["colors"]["accent"] == "#7A1E3A"
       and brand_theme.proposed("baci").get("theme", {})
       .get("colors", {}).get("accent") == "#000000")

    print("\n— approving the new proposal: owner-edited fields carry forward —")
    ok3 = brand_theme.approve("baci", {"footer.address": "   "})
    ck("a blank form input is not an edit", ok3.get("ok") is True
       and ok3.get("edited") == [], str(ok3.get("edited")))
    live2 = brand_theme.live_theme("baci")
    ck("the fresh proposal was promoted",
       live2["colors"]["accent"] == "#000000")
    ck("…but the owner's earlier corrections SURVIVED the machine re-derive",
       live2["footer"]["address"] == "999 Owner St, Miami, FL 33101, USA"
       and live2.get("width") == 640
       and sorted(ok3.get("carried", [])) == ["footer.address", "width"],
       str(ok3.get("carried")))
    ck("the owner-decided set stays on the approved theme",
       live2["_meta"]["edited"] == ["footer.address", "width"])

    print("\n— one source down costs exactly its fields —")
    _canva_on.clear()
    got3 = brand_theme.derive("baci")
    ck("canva refusal is named", "Canva" in got3["unavailable"].get("canva", ""))
    ck("logo falls to Shopify brand settings",
       got3["theme"]["logo_url"] == "https://cdn.shopify.example/baci-logo.svg"
       and got3["sources"]["logo_url"] == "shopify brand settings")
    ck("accent falls to Shopify's labelled primary colour",
       got3["theme"]["colors"]["accent"] == "#123456"
       and got3["theme"]["colors"]["accent_text"] == "#fafafa")
    ck("fonts fall to the theme's own typography",
       got3["theme"]["font"]["heading"].startswith("'Cormorant', "),
       got3["theme"]["font"]["heading"])
    _canva_on.add("baci")

    print("\n— nothing reachable: derive still answers, honestly —")
    ck("eien's rows were untouched by baci's work",
       brand_theme.live_theme("eien") == {} and brand_theme.proposed("eien") == {})
    got4 = brand_theme.derive("eien")
    ck("derive succeeds with every source down", got4.get("ok") is True)
    ck("all three sources named with why",
       set(got4["unavailable"]) == {"canva", "shopify", "site"}
       and "no Shopify store connected" in got4["unavailable"]["shopify"]
       and "no domain" in got4["unavailable"]["site"])
    ck("the theme is identity-only — nothing invented",
       got4["theme"].get("name") and "colors" not in got4["theme"]
       and "logo_url" not in got4["theme"])
    ck("the CAN-SPAM gap is named",
       any("footer.address" in g for g in got4["gaps"]))

    print("\n— the site source: structured data first, links deduped —")
    got5 = brand_theme.derive("ironside")
    t5, s5 = got5["theme"], got5["sources"]
    ck("logo from JSON-LD, absolutized against the page",
       t5["logo_url"] == "https://miamiironside.example/img/ironside-logo.png"
       and s5["logo_url"] == "site (structured data)", t5.get("logo_url", ""))
    ck("address assembled from PostalAddress",
       t5["footer"]["address"] == "7580 NE 4th Ct, Miami, FL 33138, US")
    ck("accent from theme-color, contrast computed (dark → white text)",
       t5["colors"]["accent"] == "#0b3d2e"
       and t5["colors"]["accent_text"] == "#ffffff")
    names = [x["name"] for x in t5["footer"]["socials"]]
    ck("socials: profiles kept, share/intent links dropped, x.com is X",
       names == ["Instagram", "X", "YouTube"], str(names))

    print("\n— approving by hand, with no derive at all —")
    no = brand_theme.approve("coverings")
    ck("nothing to approve refuses by name",
       "nothing to approve" in no.get("error", ""))
    ok2 = brand_theme.approve("coverings",
                              {"footer.address": "1 Trade Ct, Miami, FL"})
    ck("hand-supplied address approves and is sendable",
       ok2.get("ok") is True and ok2["gaps"] == []
       and brand_theme.live_theme("coverings")["footer"]["address"]
       == "1 Trade Ct, Miami, FL")
    ck("identity was backfilled from the brand KB",
       brand_theme.live_theme("coverings").get("name", "") != "")

    print("\n— small mechanics —")
    ck("light accent gets dark text", brand_theme._on("#F5EFE6") == "#1c1e22")
    ck("shopify font handles parse", brand_theme._shopify_font("abril_fatface_n7")
       == "Abril Fatface")
    ck("a font already in the default stack is not doubled",
       brand_theme._stack("Georgia", "heading")
       == email_render._DEFAULT["font"]["heading"])
    from app import data_tools
    _orig = data_tools._shopify

    def _fake(store, path, params=None):
        if path == "themes.json":
            return {"themes": [{"id": 5, "role": "main"}]}
        return {"asset": {"value": json.dumps(
            {"current": "Default",
             "presets": {"Default": {"type_header_font": "abril_fatface_n4"}}})}}
    data_tools._shopify = _fake
    try:
        cur = brand_theme._shop_settings("baci")
        ck("settings_data 'current' as a preset NAME resolves through presets",
           cur.get("type_header_font") == "abril_fatface_n4")
    finally:
        data_tools._shopify = _orig

    st = brand_theme.status("baci")
    ck("status reports both halves",
       st["live"] is True and st["proposed"] is True and st["approved_at"])

    print("\n— identity lives on the Brand tab, editable, derivable —")
    # Owner (2026-08-21): positioning/tone/hard-rules were read-only fossils
    # of the intake era, and "all those things should live in Brand".
    from fastapi.testclient import TestClient

    from app import admin_ui, web
    kb.set_brand("baci", positioning="Italian-designed tableware for the table.",
                 tone="direct, warm")
    kb.add_banned("baci", "made in Italy")
    page = admin_ui.render_brand("test-secret", "baci")
    ck("the identity editor renders PREFILLED — an edit, not a blank set-form",
       'action="/admin/brand_update"' in page
       and 'value="Italian-designed tableware for the table."' in page
       and "direct, warm" in page)
    ck("hard rules render with an adder", "made in Italy" in page
       and 'name="add_banned"' in page)
    ck("the voice deriver is a button, not a typed URL",
       'name="derive_voice"' in page
       and "Derive voice from the site" in page)

    c = TestClient(web.app)
    c.get("/admin/ui", params={"key": "test-secret"})   # session cookie
    r = c.post("/admin/brand_update",
               data={"tenant": "baci",
                     "positioning": "Set the table like Milan does.",
                     "elevator_sentence": "Milanese tableware, shipped from Miami.",
                     "tone": "confident, playful",
                     "do_say": "la tavola\nset the table",
                     "never_say": "cheap\nluxury for less"},
               follow_redirects=False)
    b2 = kb.brand("baci")
    ck("saving the identity lands every field",
       r.status_code == 303 and "#identity" in r.headers["location"]
       and b2.positioning == "Set the table like Milan does."
       and (b2.elevator or {}).get("sentence") == "Milanese tableware, shipped from Miami."
       and (b2.voice or {}).get("tone") == ["confident", "playful"]
       and (b2.voice or {}).get("do_say") == ["la tavola", "set the table"]
       and (b2.voice or {}).get("never_say") == ["cheap", "luxury for less"])
    c.post("/admin/brand_update", data={"tenant": "baci",
                                        "tone": "measured, warm"},
           follow_redirects=False)
    b3 = kb.brand("baci")
    ck("a tone-only apply touches tone and NOTHING else",
       (b3.voice or {}).get("tone") == ["measured", "warm"]
       and (b3.voice or {}).get("do_say") == ["la tavola", "set the table"]
       and b3.positioning == "Set the table like Milan does.")
    c.post("/admin/brand_update", data={"tenant": "baci",
                                        "add_banned": "artisanal"},
           follow_redirects=False)
    ck("the hard-rule adder writes through the one ban-list path",
       "artisanal" in (kb.brand("baci").banned_claims or []))

    from app import voice as vc
    vc.gather = lambda tenant, limit=25: (["We set tables the Milanese way."],
                                          "3 pages read")
    vc.propose = lambda tenant, texts: {
        "tenant": tenant, "tone": ["assured", "warm"],
        "exemplars": ["We set tables the Milanese way."]}
    dpage = admin_ui.render_brand("test-secret", "baci", derive_voice=True)
    ck("the derive panel shows the proposal — tone, verbatim exemplars",
       "assured, warm" in dpage and "Milanese way" in dpage
       and "Nothing was written" in dpage)
    ck("…and truly wrote nothing",
       (kb.brand("baci").voice or {}).get("tone") == ["measured", "warm"])

    # The owner's actual click path, end to end: the first shipped control
    # was a button nested inside an anchor inside the identity form — invalid
    # HTML whose click did NOTHING ("I pressed it and it's not populating").
    import re as _re
    ck("no button hides inside an anchor anywhere on the tab",
       not _re.search(r"<a [^>]*>\s*<button", page))
    ck("the derive control is a real form the dispatcher honours",
       'name="derive_voice"' in page)
    clicked = c.get("/admin/ui", params={"key": "test-secret", "tab": "brand",
                                         "tenant": "baci",
                                         "derive_voice": "1"}).text
    ck("clicking it through the console actually populates the proposal",
       "assured, warm" in clicked and "Nothing was written" in clicked)

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
