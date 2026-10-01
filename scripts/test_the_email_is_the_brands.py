"""The email is the BRAND'S: its header, its type, its products whole, its
rows even, its buttons where their words say, its taste in stickers — and a
revision is a set of edits, not the whole email written out again.

Owner, 2026-09-29, on a campaign email that took thirty minutes: "It started
off with … a wavy transition instead of a strong email header with a
consistent layout for navigating to the website … The different fonts …
don't work together … there should be a network of complimentary fonts so
that you dont just guess. The product photo is cut off on the top and bottom.
That should not happen. There is still a little star with a 'New' text on it.
That doesnt look good. … poorly aligned blocks in the same section. And the
buttons dont correspond with the correct links like 'Request a Partnership'
should take you to the wholesale page not the collections page."
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import types

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'b.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
os.environ.pop("SHOTS_WS", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (admin_ui as ui, brand_theme, db, email_header as eh, kb, links, llm,  # noqa: E402
                 recreate as rc, tenants, type_system as ts, web)

_fail: list = []
T = "baci"
CDN = "https://cdn.shopify.com/s/files/1/0001/"
LOGO = CDN + "logo.png"
SCENE = CDN + "table_scene.jpg"
PACK = CDN + "plates_packshot.png"
NAV = [{"label": "Shop", "url": "https://bacimilanousa.com/collections/shop"},
       {"label": "Wholesale", "url": "https://bacimilanousa.com/pages/wholesale"},
       {"label": "Contact", "url": "https://bacimilanousa.com/pages/contact"}]


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def email(body: str, system: str = "scale: 48/32/20/15/12 · space: 8/16/32/48 · inset: 32 · radius: 0") -> str:
    return ('<!DOCTYPE html><html><head></head><body style="margin:0;background:#f4efe9">'
            f'<!-- system: faces headline=Georgia body=Helvetica · {system} -->'
            '<table width="100%"><tr><td align="center">'
            '<table width="600" style="max-width:600px;background:#1b1d2b">' + body
            + '</table></td></tr></table></body></html>')


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand(T, "Baci")
    brand_theme.approve(T, {"logo_url": LOGO, "name": "Baci Milano",
                            "footer.address": "1 Main St, Hallandale Beach, FL 33009"})
    with db.SessionLocal() as s:
        row = s.get(db.KbBrand, T)
        row.theme = {**(row.theme or {}), "nav": NAV}
        s.commit()
    eh._mark_size = lambda url: (400, 100)            # a wide mark, 4:1
    kit = {"tenant": T, "name": "Baci Milano", "theme": brand_theme.filled(brand_theme.live_theme(T)),
           "logo_tone": "dark"}

    print("— the header is the brand's: its mark over its pages, the same every email —")
    marked = email('<tr><td style="padding:0"><!--brand-header: #f4efe9 #1b1d2b--></td></tr>'
                   '<tr><td style="padding:0 32px">Hello</td></tr>')
    out, note = eh.place(marked, T, kit, 600)
    head = out.split("Hello")[0]
    ck("drawn where the maker marked it, in the email's own colours",
       'data-brand-header="1"' in head and "background-color:#f4efe9" in head and "color:#1b1d2b" in head, note)
    ck("  the mark, sized to its own proportions, over the approved pages",
       f'src="{LOGO}"' in head and 'width="160" height="40"' in head
       and all(n["url"] in head and n["label"] in head for n in NAV))
    ck("  on the email's own inset and type scale — one rhythm with what follows",
       "padding:28px 32px" in head and "font-size:12px" in head, head[-400:])
    unmarked = email('<tr><td style="padding:0 32px;background:#1b1d2b">Hello</td></tr>')
    out2, note2 = eh.place(unmarked, T, kit, 600)
    ck("placed first in the column when the maker did not mark it — and said",
       out2.index('data-brand-header="1"') < out2.index("Hello") and "placed first" in note2, note2)
    ck("  on the ground the column opens on, the ink chosen to read on it",
       "background-color:#1b1d2b" in out2 and "color:#ffffff" in out2)
    ck("  and a dark mark on that dark ground becomes the brand's name in type",
       f'src="{LOGO}"' not in out2.split("Hello")[0] and ">Baci Milano</a>" in out2)
    bad_ink, note3 = eh.place(email('<tr><td style="padding:0"><!--brand-header: #ffffff #f0f0f0--></td></tr>'),
                              T, kit, 600)
    ck("an ink that would not read on its ground is corrected, and said",
       "color:#1c1e22" in bad_ink and "did not read" in note3, note3)
    ck("the wave that opened the email cannot come first — the maker is told the header is",
       "no band, no divider, no wave opens the email" in rc._COMPOSE_PROMPT
       and "<!--brand-header: GROUND INK-->" in rc._COMPOSE_PROMPT)

    print("\n— the type: a vetted pairing per brand, never guessed per email —")
    own = ts.for_theme(kit["theme"])
    ck("a brand with no faces of its own gets the system pair, by name",
       own["key"] == "system" and own["headline"]["family"] == "Georgia" and own["body"]["family"] == "Helvetica", str(own))
    ck("  its own faces, when on file, are its pairing — matched to the network when they are one of it",
       ts.for_theme({"font": {"heading": "'Playfair Display', Georgia, serif",
                              "body": "'Source Sans 3', Helvetica, sans-serif"}})["key"] == "editorial"
       and ts.for_theme({"font": {"heading": "'Inter'", "body": "'Karla'"}})["key"] == "own")
    ck("  a pairing chosen on the Brand tab wins",
       ts.for_theme({"font": {"heading": "Georgia", "pairing": "luxe"}})["headline"]["family"] == "Cormorant Garamond")
    ck("no pairing offers an accent face — a script line is set in the headline's italic",
       all("accent" not in p for p in ts.PAIRINGS.values()) and "no accent face" in ts.prompt_text(own))
    ck("the three faces of the owner's headline are named, a baked one included",
       ts.faces_off(["'Open Sans', sans-serif", "Georgia, serif"] + ts.baked_families(
           '<!--bake--><td style="font-family:\'Caveat\', cursive">Points</td><!--/bake-->'), own)
       == ["Open Sans", "Caveat"])
    ck("  while the pair's own faces and their fallbacks pass",
       ts.faces_off(["Georgia, 'Times New Roman', serif", "Helvetica, Arial, sans-serif", "Arial"], own) == [])
    ck("the maker is told THE TYPE, not invited to choose a display or an accent face",
       "THE TYPE — this brand's" in rc._COMPOSE_PROMPT and "at most ONE accent face" not in rc._COMPOSE_PROMPT
       and "'Brush Script MT'" not in rc._COMPOSE_PROMPT)

    print("\n— a product is shown whole —")
    scene = {"url": SCENE, "subject": "photo", "title": "the table set for lunch"}
    pack = {"url": PACK, "subject": "object", "title": "Aqua dinner plates", "tags": ["packshot"]}
    got = rc.fits(T, {"picks": {1: scene, 2: pack}})
    ck("a scene is offered in every cut; a packshot whole, and only whole",
       set(got[1]) == {"original", "1x1", "4x5", "3x2", "16x9"} and got[2] == {"whole": PACK}, str(got[2]))
    kit_p = {**kit, "pictures": [scene, pack], "hosts": {"cdn.shopify.com"}}
    cut = email(f'<tr><td><img src="{CDN}plates_packshot_1200x675_crop_center.png" alt="plates" width="600"></td></tr>')
    ck("a crop of a packshot blocks, by name",
       any(f["code"] == "product_cropped" for f in rc.check(cut, kit_p, {}, {})))
    ck("  a crop of a scene does not",
       not any(f["code"] == "product_cropped" for f in rc.check(
           email(f'<tr><td><img src="{CDN}table_scene_1200x675_crop_center.jpg" alt="t" width="600"></td></tr>'),
           kit_p, {}, {})))
    shot = {"texts": [], "images": [{"src": PACK, "natural": [1200, 1200], "box": [600, 300], "shown": [600, 300],
                                     "fit": "cover"}], "rows": []}
    ck("a packshot cut by its box on the screen blocks — the render is read, not only the URL",
       any(f["code"] == "product_cropped" and "cut to its box" in f["what"]
           for f in rc.render_check(shot, kit_p, {"picks": {2: pack}})))
    whole = {"texts": [], "images": [{"src": PACK, "natural": [1200, 1200], "box": [600, 600], "shown": [600, 600],
                                      "fit": "fill"}], "rows": []}
    ck("  and shown whole it passes", not any(f["code"] == "product_cropped"
                                              for f in rc.render_check(whole, kit_p, {"picks": {2: pack}})))

    print("\n— a row holds what it has —")
    rows = {"texts": [], "images": [], "rows": [{"text": "Set of 6 Acrylic Water Glasses",
                                                 "cells": [{"w": 300, "h": 380, "has": True, "paints": True},
                                                           {"w": 300, "h": 380, "has": False, "paints": False}]}]}
    ck("a card beside an empty column blocks, naming the row",
       any(f["code"] == "empty_column" and "Acrylic" in f["where"] for f in rc.render_check(rows, kit_p, {})))

    print("\n— a button goes where its words say —")
    dests = [{"kind": "home", "key": "", "label": "Home", "url": "https://bacimilanousa.com"},
             {"kind": "collection", "key": "shop", "label": "Shop", "url": "https://bacimilanousa.com/collections/shop"},
             {"kind": "collection", "key": "aqua", "label": "Aqua", "url": "https://bacimilanousa.com/collections/aqua"}] + \
            [{"kind": "page", "key": "", **n} for n in NAV]
    ck("'Request a Partnership' names the wholesale page",
       (links.for_words("Request a Partnership", dests) or {}).get("url") == NAV[1]["url"])
    ck("  'Get in touch' the contact page, 'Shop the Aqua collection' that collection",
       (links.for_words("Get in touch", dests) or {}).get("url") == NAV[2]["url"]
       and (links.for_words("Shop the Aqua collection", dests) or {}).get("url") == dests[2]["url"])
    ck("  and 'Shop now' names no page — the fallback's to answer", links.for_words("Shop now", dests) is None)
    moved, changes = links.match_buttons(
        '<a href="https://bacimilanousa.com/collections/shop" style="background:#1b1d2b">REQUEST A PARTNERSHIP</a>'
        '<a href="https://bacimilanousa.com/collections/shop">Shop now</a>', dests)
    ck("the owner's button is sent to the page it names, and said; the plain one is left",
       'href="https://bacimilanousa.com/pages/wholesale" style="background:#1b1d2b">REQUEST A PARTNERSHIP' in moved
       and 'href="https://bacimilanousa.com/collections/shop">Shop now' in moved and len(changes) == 1, str(changes))

    print("\n— stickers are the brand's taste —")
    ck("Baci's default is never; another brand's is unset (allowed)",
       brand_theme.setting(T, {}, "design.stickers") == "never"
       and brand_theme.setting("eien", {}, "design.stickers") == "")
    ck("  an approved choice on the Brand tab wins over the default",
       brand_theme.setting(T, {"design": {"stickers": "allowed"}}, "design.stickers") == "allowed")
    seen_p: list = []
    real_ask = llm.ask
    llm.ask = lambda purpose, prompt, **k: (seen_p.append(prompt[-1]["text"] if isinstance(prompt, list) else prompt)
                                            or types.SimpleNamespace(ok=True, stop_reason="end_turn", error="",
                                                                     text="Subject: S\nPreheader: p\n" + email("")))
    try:
        rc.compose({}, {**kit, "pictures": []}, {"picks": {}}, None, tenant=T, fitted={})
        rc.compose({}, {**kit, "tenant": "eien", "pictures": []}, {"picks": {}}, None, tenant="eien", fitted={})
    finally:
        llm.ask = real_ask
    ck("the maker is told this brand uses none — and not told a sticker may sit beside the words",
       len(seen_p) == 2 and "THIS BRAND USES NO STICKERS" in seen_p[0]
       and "a badge, a star, a sticker — sits beside words" not in seen_p[0], str(len(seen_p)))
    ck("  while a brand with no such rule keeps the old one",
       "a badge, a star, a sticker — sits beside words" in seen_p[1] and "THIS BRAND USES NO STICKERS" not in seen_p[1])

    print("\n— a revision is edits, not the whole email again —")
    base = email('<tr><td style="padding:0 32px"><h1 style="font-size:32px">Set the scene</h1></td></tr>')
    edited, placed, missed = rc._apply_edits(base, (
        "<<<<<<< FIND\n<h1 style=\"font-size:32px\">Set the scene</h1>\n=======\n"
        "<h1 style=\"font-size:48px\">Set the scene</h1>\n>>>>>>> REPLACE\n"
        "<<<<<<< FIND\n<p>not in the email</p>\n=======\n<p>x</p>\n>>>>>>> REPLACE"))
    ck("an edit is placed where its FIND occurs once; one that is not there is named, not guessed",
       'font-size:48px">Set the scene' in edited and placed == 1 and missed == ["<p>not in the email</p>"], str(missed))
    loose, n_, _ = rc._apply_edits(base, "<<<<<<< FIND\n<h1   style=\"font-size:32px\">Set  the scene</h1>\n=======\n<h1>X</h1>\n>>>>>>> REPLACE")
    ck("  its spacing is forgiven, its words are not", "<h1>X</h1>" in loose and n_ == 1)
    asked: list = []

    def _ask(purpose, prompt, **k):
        asked.append(prompt[-1]["text"] if isinstance(prompt, list) else prompt)
        return types.SimpleNamespace(ok=True, stop_reason="end_turn", error="", text=(
            "Subject: Set the scene\nPreheader: p\n<<<<<<< FIND\n<h1 style=\"font-size:32px\">Set the scene</h1>\n"
            "=======\n<h1 style=\"font-size:48px\">Set the scene</h1>\n>>>>>>> REPLACE"))
    real = llm.ask
    llm.ask = _ask
    try:
        made = rc.compose({}, kit_p, {"picks": {}}, None, tenant=T, fitted={}, html=base,
                          findings=[{"severity": "blocks", "where": "headline", "what": "too small"}])
    finally:
        llm.ask = real
    ck("the maker is asked for CHANGES and its edits are placed — one call, the email not written out",
       made["ok"] and 'font-size:48px">Set the scene' in made["html"] and "edit(s) placed" in made.get("how", "")
       and len(asked) == 1 and "the CHANGES, not the whole email" in asked[0], made.get("how", ""))
    calls: list = []

    def _ask2(purpose, prompt, **k):
        calls.append(prompt[-1]["text"] if isinstance(prompt, list) else prompt)
        if len(calls) == 1:
            return types.SimpleNamespace(ok=True, stop_reason="end_turn", error="", text=(
                "<<<<<<< FIND\n<p>nowhere</p>\n=======\n<p>x</p>\n>>>>>>> REPLACE"))
        return types.SimpleNamespace(ok=True, stop_reason="end_turn", error="",
                                     text="Subject: S\nPreheader: p\n" + base.replace("32px\">Set", "40px\">Set"))
    llm.ask = _ask2
    try:
        made2 = rc.compose({}, kit_p, {"picks": {}}, None, tenant=T, fitted={}, html=base,
                           findings=[{"severity": "blocks", "where": "headline", "what": "too small"}])
    finally:
        llm.ask = real
    ck("  when no edit can be placed, the whole email is asked for once — never a round with nothing",
       made2["ok"] and 'font-size:40px">Set' in made2["html"] and len(calls) == 2
       and "the complete HTML document" in calls[1], str(len(calls)))

    print("\n— the Brand tab carries both choices —")
    c = TestClient(web.app)
    c.cookies.set("console", web._console_token())
    page = ui.render_brand("s3cret", T)
    ck("a type pairing and a sticker choice, each saying what its default is",
       "<select name='font.pairing'>" in page and "<select name='design.stickers'>" in page
       and "own faces — System" in page and "default — never" in page)
    c.post("/admin/brand_theme/approve", data={"tenant": T, "font.pairing": "luxe",
                                                "footer.address": "1 Main St, Hallandale Beach, FL 33009"},
           follow_redirects=False)
    ck("choosing a pairing saves it", ts.for_theme(brand_theme.live_theme(T))["key"] == "luxe",
       str((brand_theme.live_theme(T).get("font") or {}).get("pairing")))
    c.post("/admin/brand_theme/approve", data={"tenant": T, "font.pairing": "(default)",
                                                "footer.address": "1 Main St, Hallandale Beach, FL 33009"},
           follow_redirects=False)
    ck("  and choosing the default goes back to the brand's own faces — the field cleared, not the word saved",
       ts.for_theme(brand_theme.live_theme(T))["key"] == "system"
       and (brand_theme.live_theme(T).get("font") or {}).get("pairing") == "",
       str((brand_theme.live_theme(T).get("font") or {}).get("pairing")))

    print("\n— the site's own pages and menu, read by the worker, filed for the email —")
    # The theme's nav was never filled — nothing derived it, nothing set it —
    # so on the deployed account the header had one link and "Request a
    # Partnership" had no wholesale page to find (found on the ship, 2026-09-29).
    dom = "bacimilanousa.com"
    # NO PAGES SET ON THE BRAND TAB — the state the deployed account is in, so
    # what follows can only have come from the site itself.
    with db.SessionLocal() as s:
        row = s.get(db.KbBrand, T)
        row.theme = {**(row.theme or {}), "nav": []}
        s.commit()
    ck("(the account has no pages set on the Brand tab, and none reach the destinations)",
       not any(d["url"].endswith("/pages/wholesale") for d in links.destinations(T, fetch=False)))
    sitemap = [f"https://{dom}/pages/wholesale", f"https://{dom}/pages/contact-us", f"https://{dom}/products/aqua-plate",
               f"https://{dom}/collections/aqua", f"https://{dom}/blogs/news/a-post", f"https://{dom}/collections",
               f"https://{dom}/search"]
    ck("the sitemap's pages are the site's pages — never a product, a collection or a post",
       links.pages_from(sitemap, dom) == [{"label": "Wholesale", "url": f"https://{dom}/pages/wholesale"},
                                          {"label": "Contact Us", "url": f"https://{dom}/pages/contact-us"}])
    home = (f'<header><a href="/"><img alt="Baci"></a><a href="/collections/shop">Shop</a>'
            f'<a href="/collections/new-arrivals">New <span>arrivals</span></a><a href="/pages/wholesale">Wholesale</a>'
            f'<a href="/cart">Cart</a><a href="/account/login">Log in</a></header><main><a href="/pages/x">X</a></main>')
    ck("the header's own links are the menu — in order, in their words, never the cart or the account",
       [m["label"] for m in links.menu_from(home, dom)] == ["Shop", "New arrivals", "Wholesale"],
       str(links.menu_from(home, dom)))
    from app import compliance
    real_sm, real_fp = compliance._sitemap_urls, brand_theme.fetch_page
    compliance._sitemap_urls = lambda base, limit=300: [{"url": u} for u in sitemap]
    brand_theme.fetch_page = lambda url: home
    try:
        from app import worker
        swept = worker.site_pages_sharded()
    finally:
        compliance._sitemap_urls, brand_theme.fetch_page = real_sm, real_fp
    ck("the worker's sweep reads each site and files what it found",
       swept.get(T) == {"pages": 2, "menu": 3} and links.site_pages(T).get("menu"), str(swept.get(T)))
    d2 = links.destinations(T, fetch=False)
    ck("the filed pages join the site's destinations, read with no network",
       any(d["url"] == f"https://{dom}/pages/wholesale" and d["kind"] == "page" for d in d2))
    ck("  so 'Request a Partnership' finds the wholesale page from what the site itself says",
       (links.for_words("Request a Partnership", d2) or {}).get("url") == f"https://{dom}/pages/wholesale")
    ck("a header with no pages set on the Brand tab carries the site's own menu",
       [i["label"] for i in eh.nav(T, {"nav": []})] == ["Shop", "New arrivals", "Wholesale"],
       str(eh.nav(T, {"nav": []})))
    page = ui.render_brand("s3cret", T)
    ck("the Brand tab has a Header pages box, saying what blank means",
       "<textarea name='nav'" in page and "own menu — Shop, New arrivals, Wholesale" in page)
    c.post("/admin/brand_theme/approve", data={"tenant": T, "nav": "Wholesale | https://bacimilanousa.com/pages/wholesale\nnot a line",
                                                "footer.address": "1 Main St, Hallandale Beach, FL 33009"},
           follow_redirects=False)
    ck("  its lines are filed as the header's pages — a line without a URL is dropped",
       brand_theme.live_theme(T).get("nav") == [{"label": "Wholesale", "url": "https://bacimilanousa.com/pages/wholesale"}],
       str(brand_theme.live_theme(T).get("nav")))
    c.post("/admin/brand_theme/approve", data={"tenant": T, "nav": "",
                                                "footer.address": "1 Main St, Hallandale Beach, FL 33009"},
           follow_redirects=False)
    ck("  and an emptied box goes back to the site's own menu",
       brand_theme.live_theme(T).get("nav") == [] and [i["label"] for i in eh.nav(T, brand_theme.live_theme(T))][:1] == ["Shop"])

    print("\n— one masthead, a mark that can be seen, no figure drawn from boxes (2026-09-30) —")
    # Owner: "there are two headers in the email because of the programmed one
    # and the one that is read from an email", with a slate mark on a navy
    # band, a 90px "BACI MILANO" under it, and a figure of a circle and two
    # rectangles standing on the "Apply to Stock" button.
    slate = dict(kit, logo_ink="#35556e", logo_tone="dark")
    on_navy, _n = eh.place(email('<tr><td style="padding:0"><!--brand-header: #1b1c2e #f0ede6--></td></tr>'
                                 '<tr><td>Hello</td></tr>'), T, slate, 600)
    on_cream, _n = eh.place(email('<tr><td style="padding:0"><!--brand-header: #f0ede6 #1b1c2e--></td></tr>'
                                  '<tr><td>Hello</td></tr>'), T, slate, 600)
    ck("a slate mark on a navy band is set as the name in type — judged by its measured contrast",
       f'src="{LOGO}"' not in on_navy.split("Hello")[0] and ">Baci Milano</a>" in on_navy)
    ck("  and the same mark on a cream band is shown", f'src="{LOGO}"' in on_cream.split("Hello")[0])
    import io as _io
    from PIL import Image as _Im
    _buf = _io.BytesIO()
    _mark = _Im.new("RGBA", (200, 60), (0, 0, 0, 0))
    _mark.paste((0x35, 0x55, 0x6e, 255), (20, 20, 180, 40))
    _mark.save(_buf, "PNG")
    from app import pictures as _pics
    _real_fetch = _pics._fetch_bounded
    _pics._fetch_bounded = lambda url, **k: _buf.getvalue()
    try:
        tone_, ink_ = rc._logo_read("https://cdn.example.test/mark.png")
    finally:
        _pics._fetch_bounded = _real_fetch
    ck("  the mark's colour is read off its own opaque pixels", (tone_, ink_) == ("dark", "#35556e"), f"{tone_} {ink_}")

    brief_ = {"concept": "x", "sections": [{"what": "x"}], "reference_text": []}
    twice = eh.place(email('<tr><td style="padding:0"><!--brand-header: #f0ede6 #1b1c2e--></td></tr>'
                           f'<tr><td align="center"><img src="{LOGO}" alt="Baci" width="160"></td></tr>'
                           f'<tr><td><img src="{SCENE}" alt="the table" width="600"></td></tr>'), T, kit, 600)[0]
    signed = eh.place(email('<tr><td style="padding:0"><!--brand-header: #f0ede6 #1b1c2e--></td></tr>'
                            f'<tr><td><img src="{SCENE}" alt="the table" width="600"></td></tr>'
                            '<tr><td><a href="https://bacimilanousa.com/collections/all">Shop</a></td></tr>'
                            f'<tr><td align="center"><img src="{LOGO}" alt="Baci" width="100"></td></tr>'), T, kit, 600)[0]
    pics_kit = dict(kit, pictures=[{"url": SCENE, "kind": "lifestyle"}])
    ck("the mark drawn again under the header is a second masthead, and blocks",
       any(f["code"] == "second_masthead" and f["severity"] == "blocks" for f in rc.check(twice, pics_kit, brief_)))
    ck("  a sign-off mark in the footer, after the pictures and the links, is not",
       not any(f["code"] == "second_masthead" for f in rc.check(signed, pics_kit, brief_)))
    read = {"texts": [{"text": "BACI", "size": 90, "weight": 700, "color": "rgb(240,237,230)", "rects": [],
                       "covered": 0},
                      {"text": "Baci Milano", "size": 28, "weight": 400, "color": "rgb(240,237,230)", "rects": [],
                       "covered": 0},
                      {"text": "Room for a few American stockists", "size": 56, "weight": 700,
                       "color": "rgb(240,237,230)", "rects": [], "covered": 0}]}
    shouted = [f for f in rc.render_check(read, kit) if f["code"] == "second_masthead"]
    ck("the brand's name set as a 90px headline under the header blocks — read off the render",
       len(shouted) == 1 and shouted[0]["severity"] == "blocks" and "90px" in shouted[0]["what"])
    ck("  while the header's own name (28px) and a 56px headline of the email's idea do not",
       "BACI" in shouted[0]["where"] if shouted else False)
    big_steps = eh.render(T, dict(kit, logo_ink="#35556e"), "#1b1c2e", "#f0ede6", 600, scale=[11, 38, 72])
    ck("  the header's name in type is capped under the masthead size, whatever the email's scale",
       "font-size:32px" in big_steps, big_steps[:200])
    ck("position:absolute blocks — Gmail and Outlook drop it",
       any(f["code"] == "positioned" for f in rc.check(email(
           '<tr><td><div style="position:absolute;top:-20px">x</div></td></tr>'), kit, brief_)))
    figure = ('<!--bake--><table><tr><td>'
              '<div style="width:30px;height:30px;border-radius:50%;background:#2330f0"></div>'
              '<div style="width:40px;height:60px;background:#2330f0;margin-top:-6px"></div>'
              '<a style="display:inline-block;padding:14px 40px;border-radius:40px;background:#2330f0;'
              'color:#fff">Apply to Stock</a></td></tr></table><!--/bake-->')
    one_dot = '<div style="width:30px;height:30px;border-radius:50%;background:#2330f0"></div>'
    framed = ('<div style="width:200px;height:200px;border-radius:50%;background:#f0ede6">'
              f'<img src="{PACK}" alt="plates" width="180"></div>')
    got = rc.drawn_shapes(figure)
    ck("a figure of empty painted boxes blocks — inside a baked block too, read before baking",
       len(got) == 1 and got[0]["severity"] == "blocks" and "2 empty painted boxes" in got[0]["what"],
       str(got)[:200])
    ck("  one decorative dot, a pill button with its words, a product on a round ground do not",
       rc.drawn_shapes(one_dot) == [] and rc.drawn_shapes(framed) == []
       and rc.drawn_shapes('<a style="display:inline-block;width:200px;height:48px;border-radius:40px;'
                           'background:#2330f0">Apply</a>') == [])
    ck("the maker is told the header IS the reference's masthead, and a figure is a picture",
       "THE HEADER IS THE REFERENCE'S MASTHEAD" in rc._COMPOSE_PROMPT
       and "the reference's opening is recreated BELOW" not in rc._COMPOSE_PROMPT
       and "NEVER built from boxes, circles and borders" in rc._COMPOSE_PROMPT
       and "a drawn thing" not in rc._COMPOSE_PROMPT)
    ck("  and the judge that a generic stand-in BLOCKS, in the owner's own examples",
       "instance in disguise BLOCKS" in rc._JUDGE_PROMPT and '"Bellissimo!"' in rc._JUDGE_PROMPT)

    print("\n— the column is ours and the mark is the header's (2026-10-01) —")
    # Owner: "Off-center, not limited to the correct design? double logo at
    # the top?" — a headline block flush left, a wave across half the page,
    # and the mark drawn again under the header inside a link round it.
    loose = ('<!DOCTYPE html><html><body style="margin:0;background:#f4efe9"><!-- system: faces x · scale: 48/16 -->'
             '<table width="600"><tr><td>Flush left, at any width</td></tr></table></body></html>')
    framed = rc.frame(loose, 600)
    ck("whatever the maker writes is set inside one centred column of the email's width",
       'data-frame="1"' in framed and '<td align="center" style="padding:0">' in framed
       and 'width="600"' in framed and "max-width:600px" in framed
       and framed.index("Flush left") > framed.index('data-frame="1"'))
    ck("  its system comment stays first, and framing twice changes nothing",
       re.search(r"<body[^>]*><!-- system:", framed) is not None and rc.frame(framed, 600) == framed)
    linked = f'<a href="https://bacimilanousa.com"><img src="{LOGO}" alt="Baci" width="160"></a>'
    maker = email(f'<tr><td align="center">{linked}</td></tr>'
                  f'<tr><td><img src="{SCENE}" alt="the table" width="600"></td></tr>'
                  '<tr><td><a href="https://bacimilanousa.com/collections/all">Shop</a></td></tr>'
                  f'<tr><td align="center"><img src="{LOGO}" alt="Baci" width="100"></td></tr>')
    cleaned, said_ = rc.drop_top_marks(maker, kit)
    ck("the maker's own mark at the top is taken out — the link round it with it — and said",
       linked not in cleaned and "the header carries it" in said_)
    ck("  the sign-off mark in the footer, after the pictures and the links, stays",
       f'<img src="{LOGO}" alt="Baci" width="100">' in cleaned)
    with_head = eh.place(email('<tr><td style="padding:0"><!--brand-header: #f0ede6 #1b1c2e--></td></tr>'
                               f'<tr><td align="center">{linked}</td></tr>'
                               f'<tr><td><img src="{SCENE}" alt="the table" width="600"></td></tr>'), T, kit, 600)[0]
    ck("a mark in a link under the header is a second masthead — the gap the double logo came through",
       any(f["code"] == "second_masthead" for f in rc.check(with_head, pics_kit, brief_)))
    baked_name = ('<!--bake--><table><tr><td style="font-family:Gelasio;font-size:72px;color:#1b1c2e">BACI<br>MILANO'
                  '</td></tr></table><!--/bake-->')
    baked_idea = ('<!--bake--><table><tr><td style="font-family:Gelasio;font-size:72px">Joke Set</td></tr></table>'
                  '<!--/bake-->')
    ck("the brand's name as a baked headline blocks — read off the maker's HTML, where the render cannot see it",
       [f["code"] for f in rc.baked_masthead(baked_name, kit)] == ["second_masthead"]
       and rc.baked_masthead(baked_idea, kit) == [])
    off = {"texts": [{"text": "Over 500 retailers", "size": 32, "weight": 400, "color": "rgb(27,28,46)",
                      "rects": [[0, 400, 480, 40]], "covered": 0}],
           "images": [{"src": SCENE, "at": [0, 553]}]}
    in_col = {"texts": [{"text": "Over 500 retailers", "size": 32, "weight": 400, "color": "rgb(27,28,46)",
                         "rects": [[44, 400, 480, 40]], "covered": 0}],
              "images": [{"src": SCENE, "at": [20, 620]}]}
    got_off = [f for f in rc.render_check(off, kit) if f["code"] == "off_column"]
    ck("a line or a picture outside the centred column blocks, read off the render",
       len(got_off) == 1 and got_off[0]["severity"] == "blocks" and "2 line(s) or picture(s)" in got_off[0]["what"],
       str(got_off)[:200])
    ck("  and one inside it does not", not any(f["code"] == "off_column" for f in rc.render_check(in_col, kit)))
    css_fig = ('<style>.hd{width:30px;height:30px;border-radius:50%;background:#2330f0}'
               'div.bd{width:40px;height:60px;background:#2330f0;margin-top:-6px}</style>'
               '<!--bake--><div class="hd"></div><div class="bd"></div><a class="btn">Apply</a><!--/bake-->')
    ck("a figure drawn from a <style> block's classes blocks as one drawn inline does",
       [f["code"] for f in rc.drawn_shapes(css_fig)] == ["drawn_figure"])

    print()
    print("ALL GREEN" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
