"""The pictures lead, the brand supports — and what was read off a picture
stays with it in the knowledge base.

Owner, 2026-09-12: *"the main media assets should be chosen based on the
email we are trying to recreate and then the colors lean first on the themes
in the photos … This way we optimize each email first for the main featured
assets and then apply our branding to support that."* And: *"once you
validate photos that meta information should stick with them in the
knowledgebase."* And: *"we will want different emails about the same
entities to use different order / choice of photos which will affect the
color palette of the email. This way emails of the same base layout don't
look exactly the same."*

  1. THE READING STAYS ON THE PICTURE: colours, size and aspect by
     arithmetic; the kind from the filing when it says, else by ONE look,
     kept on the row and never read again; the owner's hand outranks both.
  2. THE READER COUNTS EVERY PHOTOGRAPH and says each section's kind; a
     logo band is a mark, not a photograph.
  3. THE CHOOSER'S ORDER: the campaign's entities first (brand-wide when
     it names none), the design's kind per section, not seen lately by
     this list, fit and coherence, ties by the run's seed; reference pins
     never; a mark slot takes the brand's mark.
  4. THE PALETTE FROM THE PHOTOS, the brand supporting: the hero's tones
     become the page, surface, tint, dark and secondary; the accent is the
     brand's always; the ink the brand's while it reads; every role says
     where it came from; a tone that will not carry its ink is replaced
     and said; the switch on the Brand tab turns it off.
  5. THE SEAM: a run chooses with its entities and what the list saw, a
     drawn hero stands, the palette follows, the note says all of it.
  6. TWO SENDS, SAME LAYOUT, SAME ENTITY, DIFFERENT PICTURES, DIFFERENT
     PALETTE — the thing the owner asked for, as a check.
  7. THE PREVIEW is the same chain on an entity you pick, and the card
     shows the pictures, the steps and the palette's derivation.
  8. THE BRAND TAB shows every picture with its reading, a select to
     correct the kind (/admin/picture_kind) and a control to read the
     unread (/admin/pictures_read).

    python3 scripts/test_the_pictures_lead_the_palette.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (admin_ui, brand_theme, db, email_design as ed, email_render as er,  # noqa: E402
                 esp, kb, llm, palette as P, skill, skill_pack, systems, tenants)

CDN = "https://cdn.shopify.com/s/files/1/0001/"
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def pic(bg, fg, dark=None, size=(400, 300)):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    d.ellipse([size[0] * .3, size[1] * .2, size[0] * .7, size[1] * .75], fill=fg)
    if dark:
        d.rectangle([0, size[1] * .87, size[0], size[1]], fill=dark)
    b = io.BytesIO(); im.save(b, format="JPEG", quality=90)
    return b.getvalue()


BLOBS = {CDN + "sand.jpg": pic("#e7dcc8", "#7fa3c4", "#1b2438"),      # the table at lunch: sand, soft blue, navy
         CDN + "window.jpg": pic("#f2ece0", "#a8b8c8", "#2b3340"),    # the table by the window: lighter still
         CDN + "night.jpg": pic("#1b2438", "#2f3f5c"),                 # the table at night
         CDN + "linen.jpg": pic("#efe6d6", "#9fb8a8", "#2a3a2f"),      # a second lunch: linen, sage, deep green
         CDN + "bowl.jpg": pic("#ffffff", "#7fa3c4"),                  # packshots on white
         CDN + "plate.jpg": pic("#ffffff", "#c9b8a3"),
         CDN + "logo.png": pic("#ffffff", "#1e2a44", size=(180, 60)),
         CDN + "ref.jpg": pic("#ff0000", "#00ff00")}                   # a reference pin — never used


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    fetches: list = []
    def _fetch(url):
        fetches.append(url)
        return BLOBS.get(url, b"")
    ed._fetch = _fetch
    calls: list = []

    class _R:
        ok = True
        def __init__(self, text): self.text = text
    vision = {CDN + "sand.jpg": "lifestyle", CDN + "night.jpg": "lifestyle", CDN + "linen.jpg": "flat-lay"}

    def _ask(purpose, blocks, **k):
        calls.append(purpose)
        return _R(json.dumps({"kind": "lifestyle", "alone": False, "person": False}))
    real_ask = llm.ask
    llm.ask = _ask

    print("— 1. the reading stays on the picture —")
    kb.add_asset("baci", CDN + "sand.jpg", rights=kb.OWNED, subject="photo", title="the table at lunch",
                 entity_key="aqua-bowl", origin="human")
    kb.add_asset("baci", CDN + "linen.jpg", rights=kb.OWNED, subject="photo", title="the table on linen",
                 entity_key="aqua-bowl", origin="human")
    kb.add_asset("baci", CDN + "night.jpg", rights=kb.OWNED, subject="photo", title="the table at night", origin="human")
    kb.add_asset("baci", CDN + "window.jpg", rights=kb.OWNED, subject="photo", title="the table by the window",
                 entity_key="aqua-bowl", origin="human")
    kb.add_asset("baci", CDN + "bowl.jpg", rights=kb.OWNED, subject="object", tags=["store-image:1", "packshot"],
                 title="Aqua Bowl", entity_key="aqua-bowl", origin="store_sync")
    kb.add_asset("baci", CDN + "plate.jpg", rights=kb.OWNED, subject="object", tags=["store-image:1", "packshot"],
                 title="Aqua Plate", entity_key="aqua-plate", origin="store_sync")
    kb.add_asset("baci", CDN + "ref.jpg", rights=kb.REFERENCE, subject="scene", title="a pin", origin="pinterest")
    ck("the column is on the asset", hasattr(db.KbAsset, "reading"))
    got = ed.read_pictures("baci")
    rows = {a.title: a for a in kb.assets("baci")}
    ck("the control reads every unread publishable picture and says how many",
       got["read"] == 6 and got["left"] == 0 and "read 6 of 6" in got["said"], str(got))
    r = rows["the table at lunch"].reading
    ck("colours, size and aspect are read by arithmetic and kept on the row",
       r["colours"]["light"] and r["colours"]["dark"] and r["colours"]["mid"]
       and r["size"] == [400, 300] and r["aspect"] == "landscape" and r["how"]["colours"] == "arithmetic")
    ck("the kind of a packshot comes from the filing — no look spent",
       rows["Aqua Bowl"].reading["kind"] == "packshot-on-plain" and rows["Aqua Bowl"].reading["how"]["kind"] == "filed"
       and rows["Aqua Bowl"].reading["alone"] is True)
    ck("the kind of a photograph comes from one look, kept on the row",
       r["kind"] == "lifestyle" and r["how"]["kind"] == "vision" and r["alone"] is False)
    n, nf = len(calls), len(fetches)
    ed.read_picture(rows["the table at lunch"]); ed.read_pictures("baci")
    ck("a picture is read once — a second read spends nothing: no look, not even a fetch",
       len(calls) == n and n == 4 and len(fetches) == nf, f"{n} looks, {len(fetches) - nf} extra fetches")
    ck("the reference pin is never read — it is not the brand's to use",
       not any(a.reading for a in kb.assets("baci", publishable_only=False) if a.rights == kb.REFERENCE))
    said = ed.set_picture_kind(rows["the table on linen"].id, "flat-lay")
    with db.SessionLocal() as s:
        row = s.get(db.KbAsset, rows["the table on linen"].id)
        rr = dict(row.reading)
    ck("the owner's hand sets the kind, is labelled, and outranks every reading",
       "set by hand" in said and rr["kind"] == "flat-lay" and rr["how"]["kind"].startswith("hand")
       and ed.read_picture(row)["kind"] == "flat-lay")
    ck("a kind that is not one is refused by name", "not a kind of picture" in ed.set_picture_kind(rows["Aqua Bowl"].id, "hologram"))

    print("\n— 2. the reader counts every photograph —")
    pb = ed.prompt_strip(1, 2, 0, 1568, 2180)
    ck("pass B tells the reader to count every photograph and name each section's kind, a logo band as a mark",
       "COUNT EVERY PHOTOGRAPH" in pb and "image_kind" in pb and '"mark"' in pb)
    d, dropped = ed.normalize({"sections": [
        {"kind": "hero", "image_kind": "lifestyle", "slots": ["headline", "image:1", "body", "cta"]},
        {"kind": "feature", "layout": "collage", "image_kind": "flat-lay", "slots": ["headline", "image:3"]},
        {"kind": "closing", "layout": "band", "bg": "dark", "image_kind": "mark", "slots": ["image:1"]}]})
    ck("a section's picture kind, its count and a mark are all in the vocabulary — nothing dropped",
       not dropped and d["sections"][1]["image_kind"] == "flat-lay" and d["sections"][1]["slots"] == ["headline", "image:3"]
       and d["sections"][2]["image_kind"] == "mark")
    ck("a section that says nothing inherits the design's imagery default",
       ed.normalize({"sections": [{"kind": "feature", "slots": ["image:1"]}]})[0]["sections"][0]["image_kind"] == "inherit")
    ck("the RUNBOOK's generated table carries the field",
       "`section.image_kind`" in (ed.__file__ and open(os.path.join(os.path.dirname(ed.__file__), "..", "RUNBOOK.md")).read()))

    print("\n— 3. the chooser's order —")
    design, _ = ed.normalize({"palette": {"mood": "light"}, "sections": [
        {"kind": "hero", "slots": ["kicker", "headline", "image:1", "body", "cta"]},
        {"kind": "feature", "layout": "split-left", "image_kind": "flat-lay", "slots": ["headline", "body", "image:1"]},
        {"kind": "products", "layout": "grid3", "slots": ["products:3"]},
        {"kind": "closing", "layout": "band", "bg": "dark", "image_kind": "mark", "slots": ["image:1"]}]})
    c1 = ed.choose_media("baci", design, entities=["aqua-bowl"], seed="run-1")
    ck("an entity-specific campaign's hero is a picture of that entity, of the design's kind, fitting the key best",
       c1["hero"].title == "the table by the window" and c1["why"][0].startswith("scope: 4 picture(s) of aqua-bowl"),
       str(c1["why"][:2]))
    ck("a complementary slot takes the entity's picture of ITS kind — the flat-lay — not the hero's kind",
       [a.title for a in c1["by_section"][1]] == ["the table on linen"])
    ck("a mark slot takes the brand's mark, never a photograph", c1["by_section"][3] == "mark")
    ck("every step is said", len(c1["why"]) == 4 and "not seen lately" in c1["why"][1])
    c2 = ed.choose_media("baci", design, entities=["aqua-bowl"], recent_media=[c1["hero"].id], seed="run-2")
    ck("a picture this list saw lately ranks below one it has not — the entity's other lifestyle picture leads",
       c2["hero"].title == "the table at lunch" and "not seen lately" in c2["why"][1], str(c2["why"][1]))
    both = [a.id for a in kb.assets("baci") if a.title in ("the table at lunch", "the table by the window")]
    c2b = ed.choose_media("baci", design, entities=["aqua-bowl"], recent_media=both, seed="run-3")
    ck("with every fitting picture of the entity seen lately it repeats one and says so — never a picture of "
       "something else", c2b["hero"].title in ("the table at lunch", "the table by the window")
       and "seen lately — every fitting picture has been" in c2b["why"][1], str(c2b["why"][1]))
    c3 = ed.choose_media("baci", design, seed="story")
    ck("a campaign that names no entity chooses brand-wide, the light key preferring the lightest picture",
       c3["why"][0].startswith("scope: brand-wide") and c3["hero"].title == "the table by the window")
    dark_d, _ = ed.normalize({"palette": {"mood": "dark"}, "sections": [{"kind": "hero", "slots": ["image:1"]}]})
    ck("a dark key prefers the dark picture", ed.choose_media("baci", dark_d, seed="x")["hero"].title == "the table at night")
    ck("a reference pin never enters", all(a.title != "a pin" for v in c3["by_section"].values() if v != "mark" for a in v))
    kb.add_asset("baci", CDN + "night2.jpg", rights=kb.OWNED, subject="photo", title="the table at night, again", origin="human")
    BLOBS[CDN + "night2.jpg"] = BLOBS[CDN + "night.jpg"]
    ed.read_pictures("baci")
    picks = {ed.choose_media("baci", dark_d, seed=f"send-{i}")["hero"].title for i in range(6)}
    ck("two pictures that fit alike are chosen by the run's seed — not always the same one",
       len(picks) == 2, str(picks))

    print("\n— 4. the palette from the photos, the brand supporting —")
    brand = er._DEFAULT["palette"] | {"page": "#f1ede6", "accent": "#b8302f", "ink": "#1c1a17", "dark": "#1e2a44",
                                      "secondary": "#c9b8a3"}
    sand = rows["the table at lunch"].reading["colours"]
    window = rows["the table by the window"].reading["colours"]
    pal, how = P.from_photos([sand], brand)
    ck("the page is the hero's light tone, the surface white warmed to it, the tint its soft tone over the surface",
       pal["page"] == sand["light"] and "hero photograph's light tone" in how["page"]
       and P.contrast(pal["surface"], "#ffffff") < 1.2 and "twelve per cent" in how["tint"])
    ck("the dark is the hero's deepest tone and the secondary its saturated mid-tone",
       pal["dark"] == sand["dark"] and pal["secondary"] == sand["mid"])
    ck("the accent is the brand's, always; the ink the brand's while it reads",
       pal["accent"] == "#b8302f" and pal["ink"] == "#1c1a17" and "always" in how["accent"] and "reads" in how["ink"])
    ck("every role says where it came from", all(how.get(r) for r in ("page", "surface", "tint", "dark", "secondary", "ink", "accent", "muted", "border")))
    import ast as _ast, inspect as _inspect
    _tree = _ast.parse(_inspect.getsource(P.from_photos))
    _writes = {t.slice.value for n in _ast.walk(_tree) if isinstance(n, _ast.Assign)
               for t in n.targets if isinstance(t, _ast.Subscript) and isinstance(t.value, _ast.Name)
               and t.value.id == "out" and isinstance(t.slice, _ast.Constant)}
    ck("from_photos never writes the accent — the brand's by construction, not by a rule that could be removed",
       "accent" not in _writes and "accent_ink" not in _writes, str(sorted(_writes)))
    night = rows["the table at night"].reading["colours"]
    pal2, how2 = P.from_photos([night], brand, mood="dark")
    ck("on a dark key the page is the deepest tone, the ink computed because the brand's would not read",
       pal2["page"] == night["dark"] and pal2["ink"] == "#ffffff" and how2["ink"].startswith("computed"))
    ck("a complementary photograph supplies a tone the hero lacks, and is named",
       "complementary photograph 1" in P.from_photos([{"dominant": "#eeeeee", "light": "#eeeeee", "dark": "", "mid": "",
                                                       "key": "light", "luminance": .9, "warmth": 0},
                                                      sand], brand)[1]["dark"])
    ck("nothing to lead is the brand's palette as approved",
       P.from_photos([], brand)[0]["page"] == "#f1ede6" and "_" in P.from_photos([], brand)[1])
    ck("no palette a photograph leads has a ground that will not carry its ink",
       not [f for f in P.findings(pal) if "below" in f and "accent" not in f]
       and not [f for f in P.findings(pal2) if "below" in f and "accent" not in f], str(P.findings(pal2)))
    theme = {"palette": brand, "keyed_grounds": False}
    ck("the switch off is the palette as approved, said",
       ed.palette_for(theme, design, {"signatures": [sand]})[1]["_"].startswith("the pictures do not lead"))
    ck("the switch on leads with the photographs",
       ed.palette_for({"palette": brand}, design, {"signatures": [sand]})[0]["palette"]["page"] == sand["light"])

    print("\n— 5. the seam —")
    kb.set_brand("baci", positioning="Italian-designed tableware.", tone="direct")
    kb.add_banned("baci", "made in Italy")
    kb.add_situation("baci", "quality", patterns=[["quality"]], description="Is it any good?", origin="seed")
    kb.add_claim("baci", "Designed in Milan and placed at the Four Seasons.", "brand brief", ["quality"],
                 origin="human", status="active")
    for k_, n_, img in (("aqua-bowl", "Aqua Bowl", "bowl.jpg"), ("aqua-plate", "Aqua Plate", "plate.jpg")):
        kb.add_entity("baci", "product", k_, n_, price="$40", attributes={"image": CDN + img, "url": "https://bacimilanousa.com/products/" + k_}, origin="human")
    row = systems.find("baci", "campaign_email") or systems.create("baci", "campaign_email")
    with db.SessionLocal() as s:
        rr_ = s.get(db.System, row.id); rr_.status = "live"; s.commit()
    _ALL = {c: True for c in tenants.CAPABILITIES}
    tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else {c: False for c in tenants.CAPABILITIES}
    esp.provider_for = lambda t: "omnisend"
    esp.personalize = lambda t, html: {"ok": True, "html": html}

    class _Mod:
        @staticmethod
        def draft_from_html(tenant, *, name, subject, sender_name, html, preheader="", include_segments=None):
            return {"ok": True, "campaign_id": "c", "stage": "done"}
    esp.backend = lambda t: (_Mod, "")
    brand_theme.approve("baci", {"footer.address": "1 Main St", "logo_url": CDN + "logo.png",
                                 **{f"palette.{k}": v for k, v in brand.items()}})
    from app import email_structures as es
    st = es.file_structure(name="photo-led test", sequence=["hero", "heading", "text", "cta", "heading", "text", "products", "ps"],
                           source="hand", review="approved", design=design)

    def _drafter(bundle, seg, goal, craft=None):
        claims = bundle.get("claims") or []
        cid = claims[0]["claim_id"] if claims else ""
        keys = [e["key"] for e in (bundle.get("entities") or [])][:3]
        return ({"subject": "Three pieces, one table", "preheader": "sample",
                 "blocks": [{"type": "hero"}, {"type": "heading", "text": "New", "level": 2},
                            {"type": "heading", "text": "Three pieces, one table", "level": 1},
                            {"type": "text", "html": "<p>Body words for the table.</p>"},
                            {"type": "cta", "label": "See the set", "url": "https://bacimilanousa.com/collections/aqua"},
                            {"type": "divider"}, {"type": "heading", "text": "On the table", "level": 1},
                            {"type": "text", "html": "<p>More words.</p>"}, {"type": "divider"},
                            {"type": "products", "keys": keys}, {"type": "divider"},
                            {"type": "text", "html": "<p>Forwarded?</p>"}],
                 "claim_ids": [cid] if cid else [], "cta_label": "See the set",
                 "cta_url": "https://bacimilanousa.com/collections/aqua"}, "model", "")
    skill_pack.draft_campaign = _drafter
    r1 = skill.run("campaign_email", "baci", segment="reorder_due", structure=st["id"], intent="education",
                   entity_key="aqua-bowl", generate_visual="no")
    notes1 = r1.get("notes") or []
    ck("the run chose its pictures with its entity and said every step",
       r1.get("status") == "produced" and any("pictures — scope: " in n and "aqua-bowl" in n for n in notes1), str([n[:80] for n in notes1 if "pictures" in n]))
    ck("the palette the run rendered with is led by the pictures, the brand supporting — and the note says which tone each role took",
       any("palette led by the pictures" in n and "hero photograph" in n and "always" in n for n in notes1))
    with db.SessionLocal() as s:
        out1 = s.query(db.Output).filter(db.Output.tenant == "baci").order_by(db.Output.created_at.desc()).first()
        art1 = s.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == out1.id).order_by(db.ArtifactBody.created_at.desc()).first()
        html1 = (art1.meta or {}).get("html") or ""
        media1 = list(out1.media_ids or [])
    hero_url1 = next((u for u in re.findall(r'<img src="([^"]+)"', html1) if "logo" not in u), "")
    print("  run 1 hero:", hero_url1[-40:], "| media:", media1)
    ck("the email's grounds are the photograph's tones, not the approved palette's",
       (sand["light"] in html1 or window["light"] in html1) and "#f1ede6" not in html1 and "#b8302f" in html1)
    ck("the brand's mark stands where the design has a mark band", CDN + "logo.png" in html1)

    print("\n— 6. two sends, same layout, same entity —")
    ck("the ledger the next send reads carries the pictures the first one used",
       any(h.get("media") == media1 for h in skill_pack._recent_sends("baci", "reorder_due")))
    r2 = skill.run("campaign_email", "baci", segment="reorder_due", structure=st["id"], intent="education",
                   entity_key="aqua-bowl", generate_visual="no")
    with db.SessionLocal() as s:
        out2 = s.query(db.Output).filter(db.Output.tenant == "baci").order_by(db.Output.created_at.desc()).first()
        art2 = s.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == out2.id).order_by(db.ArtifactBody.created_at.desc()).first()
        html2 = (art2.meta or {}).get("html") or ""
    def _hero_src(h):
        return next((u for u in re.findall(r'<img src="([^"]+)"', h) if "logo" not in u), "")
    hero1, hero2 = _hero_src(html1), _hero_src(html2)
    ck("the second send on the same layout and entity leads with a different photograph of that entity — "
       "the one the list has not seen",
       out2.id != out1.id and hero1 != hero2 and {hero1.split("/")[-1].split("_")[0], hero2.split("/")[-1].split("_")[0]}
       == {"sand", "window"}, f"{hero1.split('/')[-1]} → {hero2.split('/')[-1]}")
    ck("the first send recorded the pictures it carried, so the second could avoid them",
       media1 and any(a.id in media1 for a in kb.assets("baci") if a.title in ("the table at lunch", "the table by the window")))
    lead2 = window if "sand" in hero1 else sand
    lead1 = sand if "sand" in hero1 else window
    ck("and its palette follows the new photograph", lead2["light"] in html2 and lead1["light"] not in html2)
    ck("the run's note says the first was seen lately",
       any("seen lately" in n for n in (r2.get("notes") or [])))

    print("\n— 7. the preview is the same chain —")
    html_p, note_p = ed.preview_html("baci", design, entity_key="aqua-bowl")
    last = ed.preview_html.last
    ck("the preview chooses with the entity, leads its palette with the photograph, and says its steps",
       last["entity"] == "aqua-bowl" and last["why"][0].startswith("scope: ") and "aqua-bowl" in last["why"][0]
       and last["keyed"].get("page") and last["palette"]["page"] in (sand["light"], window["light"]))
    ck("the preview's blocks are the design's own shape — a divider between sections, a hero, the products",
       html_p.count("Aqua Bowl") >= 1 and "own photograph" in html_p and html_p.count("height:1px") >= 2)
    card = admin_ui._structures_card("s3cret", "baci", preview_entity="aqua-bowl")
    ck("the card carries the entity picker, the pictures chosen, the steps and the palette's derivation",
       'name="preview_entity"' in card and "The pictures it chose" in card and "scope: " in card
       and "The palette they lead" in card and "hero photograph" in card)

    print("\n— 8. the Brand tab —")
    html_b = admin_ui.render_brand("s3cret", "baci")
    ck("every picture is shown with its reading and a select to correct its kind",
       "The pictures, and what was read off them" in html_b and 'action="/admin/picture_kind"' in html_b
       and "the table at lunch" in html_b and "kind: lifestyle — vision" in html_b
       and "kind: flat-lay — hand" in html_b and "the product alone" in html_b)
    kb.add_asset("baci", CDN + "new.jpg", rights=kb.OWNED, subject="photo", title="a new one", origin="human")
    BLOBS[CDN + "new.jpg"] = BLOBS[CDN + "sand.jpg"]
    html_b2 = admin_ui.render_brand("s3cret", "baci")
    ck("an unread picture puts the read control on the tab, with the count",
       'action="/admin/pictures_read"' in html_b2 and "Read the 1 unread picture" in html_b2)
    from app import web

    class _Req:
        def __init__(self, form): self._f = form
        async def form(self): return self._f
    from urllib.parse import unquote
    resp = asyncio.run(web.pictures_read(_Req({"tenant": "baci"}), key="s3cret"))
    ck("pressing it reads them and comes back to the Brand tab saying how many",
       resp.status_code == 303 and "read 1 of 1" in unquote(resp.headers["location"])
       and next(a for a in kb.assets("baci") if a.title == "a new one").reading.get("kind"))
    aid = next(a for a in kb.assets("baci") if a.title == "a new one").id
    resp2 = asyncio.run(web.picture_kind(_Req({"tenant": "baci", "asset_id": aid, "kind": "texture"}), key="s3cret"))
    ck("the select's route sets the kind by hand and comes back",
       resp2.status_code == 303 and "set by hand" in unquote(resp2.headers["location"])
       and next(a for a in kb.assets("baci") if a.id == aid).reading["kind"] == "texture")
    resp3 = asyncio.run(web.picture_kind(_Req({"tenant": "baci", "asset_id": aid, "kind": "hologram"}), key="s3cret"))
    ck("a kind that is not one is refused on the route too", "err=" in resp3.headers["location"])
    ck("the Brand tab carries the switch that turns the pictures' lead off",
       'name="keyed_grounds"' in html_b and "Key each email" in html_b)
    llm.ask = real_ask

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
