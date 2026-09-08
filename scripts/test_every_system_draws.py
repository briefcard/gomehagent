"""Every system draws. The brand's default image model on the Brand tab;
`generate` judged against the product's photographs like an ad frame; the
email hero and the article's pictures DRAWN FIRST when the brand's own
pictures allow it, filed PROPOSED, and approved by the approval of the email
or the article that carries them; a flagged one never ships unattended.

Owner, 2026-09-08: *"I want this on all the systems. Emails and blogs are
still not leveraging this generative feature at all."*

Run: python3 scripts/test_every_system_draws.py
"""
from __future__ import annotations

import base64
import io
import os
import sys
import tempfile
from types import SimpleNamespace
from urllib.parse import unquote

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'draws.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import (admin_ui as ui, approvals, coherence, config, creative, db,  # noqa: E402
                 esp, gemini_images, imagegen, kb, kb_seed, keywords, seo_guard,
                 sites, skill, skill_pack, systems, tenants, web, whatsapp)

KEY = "s3cret"
_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(colour, w: int = 64, h: int = 64) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def _asset(tenant: str, asset_id: str):
    return next((a for a in kb.assets(tenant, publishable_only=False) if a.id == asset_id), None)


_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else \
    {c: False for c in tenants.CAPABILITIES}


def _fake_esp():
    esp.provider_for = lambda t: "omnisend"
    esp.personalize = lambda t, html: {"ok": True, "html": html}

    class _Mod:
        @staticmethod
        def draft_from_html(tenant, *, name, subject, sender_name, html,
                            preheader="", include_segments=None):
            return {"ok": True, "campaign_id": "camp_1"}
    esp.backend = lambda t: (_Mod, "")


def main() -> int:  # noqa: PLR0915
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    config.OPENAI_API_KEY = "sk-test"
    config.GEMINI_API_KEY = ""

    print("— THE BRAND'S DEFAULT MODEL, ON THE BRAND TAB —")
    ck("blank means the system default", creative.brand_model("baci") == (imagegen.MODEL, ""),
       str(creative.brand_model("baci")))
    said = kb.set_image_model("baci", imagegen.BOTH)
    ck("'both' is refused for a brand default — one picture is one model",
       said.startswith("A brand default is one model") and kb.image_model("baci") == "", said)
    said = kb.set_image_model("baci", "gemini:gemini-3-pro-image")
    ck("a model without its key is refused by the variable's name",
       "GEMINI_API_KEY" in said and kb.image_model("baci") == "", said)
    config.GEMINI_API_KEY = "gk-test"
    said = kb.set_image_model("baci", "gemini:gemini-3-pro-image")
    ck("with the key set it is saved through one writer, and said",
       said.startswith("Every system now draws with gemini:gemini-3-pro-image")
       and kb.image_model("baci") == "gemini:gemini-3-pro-image", said)
    ck("  and every system reads it", creative.brand_model("baci") == ("gemini:gemini-3-pro-image", ""))
    page = ui.render_brand(KEY, "baci")
    ck("the Brand tab carries the card, preselected, with 'both' not offered",
       'id="model"' in page and 'name="image_model"' in page
       and 'value="gemini:gemini-3-pro-image" selected' in page
       and 'value="both"' not in page and "approving the email" in page)
    config.GEMINI_API_KEY = ""
    model, why = creative.brand_model("baci")
    ck("when the key goes away the system default draws, and WHY is said",
       model == imagegen.MODEL and "GEMINI_API_KEY" in why and "brand's default" in why, why)
    ck("  the card says it too", "GEMINI_API_KEY" in ui.render_brand(KEY, "baci"))
    r = TestClient(web.app).post(f"/admin/brand_update?key={KEY}",
                                 data={"tenant": "baci", "image_model": imagegen.MODEL},
                                 follow_redirects=False)
    loc = unquote(r.headers.get("location", ""))
    ck("the Brand form saves it and lands back on the card",
       r.status_code == 303 and kb.image_model("baci") == imagegen.MODEL
       and "Every system now draws with" in loc and loc.endswith("#model"), loc[-120:])
    kb.set_image_model("baci", "")

    print("\n— ONE PICTURE, JUDGED LIKE A SET —")
    ck("the generated origin is one word in two modules",
       kb.GENERATED_ORIGIN == creative.GENERATED_ORIGIN == "generated")
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Cup", description="a cup", origin="human")
    kb.add_asset("baci", "https://cdn.example/cup.png", rights=kb.OWNED, title="cup",
                 subject=kb.OBJECT, entity_key="zodiac-cup", origin="human")
    kb.add_asset("baci", "https://cdn.example/look.png", rights=kb.OWNED, title="look",
                 subject=kb.SCENE, origin="human")
    kb.add_board("baci", "Studio")
    kb.set_board_role(next(a.id for a in kb.assets("baci") if "look" in (a.url or "")),
                      "studio", "look", True)
    cup_row = next(a for a in kb.assets("baci") if "cup.png" in (a.url or ""))
    prod, look = png((200, 30, 30, 255)), png((30, 30, 200, 255))
    creative._fetch = lambda url: {"https://cdn.example/cup.png": prod,
                                   "https://cdn.example/look.png": look}.get(url, b"")
    creative.assess = lambda blob, brief, tenant="": {"ok": True, "verdicts": [], "overall": "",
                                                      "failed": [], "fix": ""}
    creative.product_features = lambda tenant, entity_key, product, **k: {
        "ok": True, "features": ["a gold rim"], "cached": False}
    verdicts: list = []

    def _judge(c, p, f, tenant="", **k):
        v = verdicts.pop(0) if verdicts else {"match": 96, "differences": []}
        return {"ok": True, "same": v.get("match", 0) >= 90, "lettering": False,
                "invented": False, "why": "", **v}
    creative.compare_product = _judge
    counter = [0]
    asked: list = []

    def _openai(path, **kw):
        counter[0] += 1
        n_ = int((kw.get("data") or {}).get("n") or (kw.get("json_body") or {}).get("n") or 1)
        asked.append(n_)
        return {"ok": True, "images": [png((counter[0] * 7 % 250, i * 50 + 5, 1, 255))
                                       for i in range(n_)]}
    imagegen.post = _openai
    gcalls: list = []

    def _gpost(url, *, headers, json_body):
        gcalls.append(json_body["model"])
        counter[0] += 1
        return SimpleNamespace(status_code=200, text="", json=lambda: {"outputs": [
            {"type": "image", "mime_type": "image/png",
             "data": base64.b64encode(png((counter[0] * 7 % 250, 3, 200, 255))).decode()}]})
    gemini_images.post = _gpost
    cup = coherence.commit("entity", "zodiac-cup", label="Zodiac Cup")

    verdicts[:] = [{"match": 70, "differences": ["the rim is plain"]},
                   {"match": 80, "differences": ["the handle is square"]},
                   {"match": 96, "differences": []},
                   {"match": 75, "differences": ["the cup is taller"]}]
    got = creative.generate("baci", commitment=cup, fmt="email_hero", entity_key="zodiac-cup",
                            prominent="The cup for your sign")
    ck("four candidates are asked for and judged; the closest is kept",
       got.get("ok") and asked and asked[0] == creative.CANDIDATES
       and got["judged"]["judged"] == 4 and (got.get("fidelity") or {}).get("match") == 96,
       f"ok={got.get('ok')} asked={asked[:1]} judged={got.get('judged')} fid={got.get('fidelity')}")
    ck("  and the picture says so", "4 candidate(s) judged" in got.get("basis", ""), got.get("basis"))
    row = _asset("baci", got.get("asset_id", ""))
    ck("the picture carries the model that drew it, like a frame",
       row is not None and f"model:{imagegen.MODEL}" in (row.tags or []) and got.get("model") == imagegen.MODEL,
       str(row.tags if row else None))
    ck("  the judge's word is filed with it",
       row is not None and (row.assessment or {}).get("fidelity", {}).get("match") == 96)
    ck("  and it is PROPOSED, generated",
       row is not None and row.review == "proposed" and row.origin == "generated")

    before = len(kb.assets("baci", publishable_only=False))
    miss = {"match": 60, "differences": ["the rim is plain"]}
    verdicts[:] = [dict(miss) for _ in range(creative.CANDIDATES + creative.PER_PROMPT * creative.REDRAFTS)]
    got2 = creative.generate("baci", commitment=cup, fmt="email_hero", entity_key="zodiac-cup",
                             prominent="The cup for your sign")
    ck("a near miss is redrawn with its fault named, then DROPPED and said — never filed",
       not got2.get("ok") and got2.get("dropped") and "NOT the product" in got2.get("error", "")
       and "the rim is plain" in got2.get("error", "")
       and got2["judged"]["not_the_product"] == 1 and got2["judged"]["redrafted"] == 0
       and len(kb.assets("baci", publishable_only=False)) == before,
       str(got2)[:200])

    config.GEMINI_API_KEY = "gk-test"
    kb.set_image_model("baci", "gemini:gemini-3-pro-image")
    verdicts[:] = []
    got3 = creative.generate("baci", commitment=cup, fmt="article_hero", entity_key="zodiac-cup",
                             prominent="The cup")
    ck("the brand's default reaches the generator when no form says otherwise",
       got3.get("ok") and gcalls and set(gcalls) == {"gemini-3-pro-image"}
       and got3.get("model") == "gemini:gemini-3-pro-image"
       and "model:gemini:gemini-3-pro-image" in (_asset("baci", got3["asset_id"]).tags or []),
       f"gcalls={gcalls} model={got3.get('model')}")
    n_g = len(gcalls)
    got4 = creative.generate("baci", commitment=cup, fmt="article_hero", entity_key="zodiac-cup",
                             prominent="The cup, again", image_model=imagegen.MODEL)
    ck("  and a form's explicit choice beats it",
       got4.get("ok") and got4.get("model") == imagegen.MODEL and len(gcalls) == n_g,
       f"model={got4.get('model')} gcalls={len(gcalls)} (was {n_g})")
    kb.set_image_model("baci", "")
    config.GEMINI_API_KEY = ""

    print("\n— THE EMAIL HERO IS DRAWN FIRST, AND THE LADDER STANDS BELOW IT —")
    ck("drawable: a product with a photograph on a brand with a board",
       creative.drawable("baci", "zodiac-cup") and creative.drawable("baci", "", ["studio"]))
    ck("  not drawable: a brand with no boards",
       not creative.drawable("eien", "omega-3"))
    verdicts[:] = []
    hero = creative.hero_for_campaign("baci", segment_key="reorder_due", entity_keys=["zodiac-cup"],
                                      draw_first=True, commitment=cup, prominent="Back in stock")
    ck("with draw_first the hero is generated — proposed, attributed, and it says approving approves it",
       hero.get("basis") == "generated" and hero.get("subject_key") == "zodiac-cup"
       and hero.get("image", {}).get("url", "").startswith("https://example.test/")
       and "approving this email approves the picture" in hero.get("note", "")
       and _asset("baci", hero["asset_id"]).review == "proposed", str(hero)[:200])
    hero0 = creative.hero_for_campaign("baci", segment_key="reorder_due", entity_keys=["zodiac-cup"])
    ck("without it the approved photograph serves, exactly as before",
       hero0.get("basis") == "approved_asset" and hero0.get("asset_id") == cup_row.id, str(hero0)[:120])
    verdicts[:] = [dict(miss) for _ in range(creative.CANDIDATES + creative.PER_PROMPT * creative.REDRAFTS)]
    hero2 = creative.hero_for_campaign("baci", segment_key="reorder_due", entity_keys=["zodiac-cup"],
                                       draw_first=True, commitment=cup)
    ck("a dropped drawing falls to the photograph, and the drop is said",
       hero2.get("basis") == "approved_asset" and "drawn and dropped" in hero2.get("drawn_why", ""),
       str(hero2)[:200])
    real_generate = creative.generate
    spy = [0]
    creative.generate = lambda *a, **k: (spy.__setitem__(0, spy[0] + 1) or real_generate(*a, **k))
    none = creative.hero_for_campaign("eien", segment_key="week_one", entity_keys=["omega-3"], draw_first=True)
    ck("a brand with nothing to draw from is not drawn for — no call, the named absence as before",
       spy[0] == 0 and none.get("basis") == "none" and "pictures queue" in none.get("why", ""), str(none)[:160])
    creative.generate = real_generate

    print("\n— THE WHOLE EMAIL: the drawn hero in the draft, approved by the push —")
    kb.set_brand("baci", positioning="Italian-designed tableware.", tone="direct, warm")
    kb.add_banned("baci", "made in Italy")
    kb.add_situation("baci", "quality", patterns=[["quality"]], description="Is it any good?", origin="seed")
    kb.add_claim("baci", "Designed in Milan and used in leading hotels.", "brand brief", ["quality"],
                 origin="human", status="active")
    row_ = systems.find("baci", "campaign_email") or systems.create("baci", "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, row_.id).status = "live"
        s.commit()
    _fake_esp()
    from app import brand_theme
    okt = brand_theme.approve("baci", {"footer.address": "2875 NE 191st St, Aventura, FL 33180"})
    assert okt.get("ok") and okt["gaps"] == [], okt
    skill_pack.draft_campaign = lambda bundle, seg, goal, craft=None: (
        {"subject": "Back in stock", "preheader": "the cup returns",
         "body_html": "<p>Hi {{FIRST_NAME}}, Designed in Milan and used in leading hotels.</p>",
         "claim_ids": [], "cta_label": "Shop", "cta_url": "https://x/s"}, "model", "")
    verdicts[:] = []
    r = skill.run("campaign_email", "baci", segment="reorder_due", entity_key="zodiac-cup",
                  audience_key="core_hostess")
    item = (r.get("items") or [{}])[0]
    html = item.get("meta", {}).get("html", "")
    hero_id = str(r.get("detail", {}).get("hero", {}).get("asset_id") or "")
    hero_row = _asset("baci", hero_id) if hero_id else None
    ck("the run produced, with a GENERATED hero in the HTML",
       r.get("status") == "produced" and (r.get("detail") or {}).get("hero", {}).get("basis") == "generated"
       and hero_row is not None and (hero_row.url or "") in html,
       f"status={r.get('status')} hero={(r.get('detail') or {}).get('hero')} "
       f"blocked_on={r.get('blocked_on')} notes={str(r.get('notes'))[:400]}")
    ck("  the run says approving the email approves the picture",
       any("approving this email approves the picture" in str(n) for n in (r.get("notes") or [])),
       str(r.get("notes"))[:300])
    ck("  and it is still PROPOSED while the owner reviews",
       hero_row is not None and hero_row.review == "proposed" and not kb.may_publish(hero_id)[0])
    got_push = skill_pack.push_campaign_to_esp("baci", item.get("output_id", ""))
    a = _asset("baci", hero_id) if hero_id else None
    ck("the push that follows the owner's approval approves the picture — owned, usable",
       got_push.get("ok") is True and a is not None and a.review == "approved" and a.rights == kb.OWNED
       and kb.may_publish(hero_id)[0] and a.uses == "1",
       f"{str(got_push)[:120]} review={getattr(a, 'review', None)} rights={getattr(a, 'rights', None)}")
    r_off = skill.run("campaign_email", "baci", segment="reorder_due", entity_key="zodiac-cup",
                      audience_key="core_hostess", generate_visual="no")
    ck("generate_visual: no keeps the email to approved photographs",
       (r_off.get("detail") or {}).get("hero", {}).get("basis") == "approved_asset",
       f"status={r_off.get('status')} hero={(r_off.get('detail') or {}).get('hero')} "
       f"blocked_on={r_off.get('blocked_on')} notes={str(r_off.get('notes'))[:300]}")

    print("\n— A CRAWLED CANDIDATE NEVER COMES THROUGH THE SIDE DOOR —")
    kb.add_asset("baci", "https://x/crawl.png", rights=kb.REFERENCE, title="a find", origin="crawl")
    crawl = next(a for a in kb.assets("baci", publishable_only=False) if (a.url or "") == "https://x/crawl.png")
    said = kb.approve_generated(crawl.id, via="test")
    ck("approve_generated refuses anything not generated",
       said.startswith("Not a generated picture") and not kb.may_publish(crawl.id)[0], said)

    print("\n— THE ARTICLE DRAWS: the hero first, a body picture on a miss —")
    blog = systems.find("baci", "blog") or systems.create("baci", "blog")
    with db.SessionLocal() as s:
        s.get(db.System, blog.id).status = "live"
        b = s.get(db.KbBrand, "baci")
        b.banned_claims = ["handmade"]
        s.commit()
    kb.add_entity("baci", "product", "zodiac-plate", "Zodiac Plate", description="a plate", origin="human")
    kb.add_asset("baci", "https://cdn.example/plate.png", rights=kb.OWNED, title="plate",
                 subject=kb.OBJECT, entity_key="zodiac-plate", origin="human")
    plate = png((30, 200, 30, 255))
    creative._fetch = lambda url: {"https://cdn.example/cup.png": prod, "https://cdn.example/look.png": look,
                                   "https://cdn.example/plate.png": plate}.get(url, b"")
    GOOD = ("<h1>Zodiac plates</h1><p>A zodiac plate is a plate with a sign on it, and this "
            "sentence exists so the body is long enough to be an article rather than "
            "a stub.</p>\n<!--IMAGE: the plate on a breakfast table-->\n<p>More.</p>")
    skill_pack._draft_article_live = lambda bundle, keyword, role, angle, questions, links, entity, avoid=None: (GOOD, "")
    verdicts[:] = []
    ra = skill.run("blog_article", "baci", keyword="zodiac plate", role="pillar", entity_key="zodiac-plate")
    oid = (ra.get("items") or [{}])[0].get("output_id", "")
    with db.SessionLocal() as s:
        out = s.get(db.Output, oid) if oid else None
        media = list((out.media_ids or []) if out is not None else [])
    notes = [str(n) for n in (ra.get("notes") or [])]
    ck("a product piece: the hero is DRAWN first, judged, and carried on the output",
       ra.get("status") == "produced" and len(media) == 1
       and getattr(_asset("baci", media[0]), "origin", "") == "generated"
       and any("picture: generated" in n and "candidate(s) judged" in n
               and "approving this article approves it" in n for n in notes),
       f"status={ra.get('status')} media={media} blocked_on={ra.get('blocked_on')} notes={str(notes)[:500]}")
    ck("  a body marker an approved photograph fits is FILLED, not drawn — a real photograph beats a rendering",
       any("pictures in the piece" in n and "(photograph)" in n for n in notes), str(notes)[:400])

    GOOD_B = ("<h1>Setting a table for a long lunch</h1><p>A long lunch wants a table set "
              "before anyone sits, and this sentence exists so the body is long enough "
              "to be an article rather than a stub.</p>\n<!--IMAGE: a set table at dusk-->\n<p>More.</p>")
    skill_pack._draft_article_live = lambda bundle, keyword, role, angle, questions, links, entity, avoid=None: (GOOD_B, "")
    rb = skill.run("blog_article", "baci", keyword="table setting ideas", role="pillar")
    oid = (rb.get("items") or [{}])[0].get("output_id", "")
    with db.SessionLocal() as s:
        out = s.get(db.Output, oid) if oid else None
        media = list((out.media_ids or []) if out is not None else [])
    notes = [str(n) for n in (rb.get("notes") or [])]
    ck("a topic piece: the hero AND the body picture are drawn from the look, hero first, both on the output",
       rb.get("status") == "produced" and len(media) == 2
       and all(getattr(_asset("baci", m), "origin", "") == "generated" for m in media)
       and any("pictures in the piece" in n and "(generated)" in n for n in notes),
       f"status={rb.get('status')} media={media} blocked_on={rb.get('blocked_on')} notes={str(notes)[:500]}")
    ck("  the body picture is in the article",
       '<figure><img src="https://example.test/' in (rb.get("items") or [{}])[0].get("body", "")
       or '<figure><img src="https://example.test/' in (rb.get("items") or [{}])[0].get("meta", {}).get("body", ""),
       str((rb.get("items") or [{}])[0].keys()))
    from app.web import _article_bundle
    art, kw, ap = _article_bundle(oid)
    page = " ".join(ui.render_workroom(KEY, oid, art, kw, ap).split())
    ck("the article's page shows the pictures and where they stand",
       "Pictures on this article" in page and "PROPOSED" in page
       and "approving this article approves it" in page and "Generate the picture" not in page)

    ap_id = approvals.request_approval(
        "seo_new_article", "[SEO/baci] New article: Setting a table",
        {"site": "baci", "blog_id": "1", "output_id": oid, "run_id": "",
         "fields": {"title": "Setting a table for a long lunch", "body_html": GOOD_B,
                    "handle": "setting-a-table", "published": False}}, notify=False)
    hero_a = media[0] if media else ""
    kb.set_asset_assessment(hero_a, {"ok": True, "failed": ["off_subject"], "verdicts": []})
    held = approvals.ship_unattended("baci", oid, why="test")
    ck("a generated picture its reviewer flagged does not ship unattended",
       held.get("ok") is False and "needs a person" in held.get("why", "") and "off_subject" in held.get("why", ""),
       str(held))
    kb.set_asset_assessment(hero_a, {"ok": True, "failed": [], "verdicts": []})

    sent: dict = {}

    class _B:
        @staticmethod
        def create_article(profile, blog_id, fields):
            sent.update(fields)
            return "https://shop.example/blogs/news/setting-a-table (created)"
    sites.get = lambda key: {"key": "baci", "platform": "shopify", "creds_key": "baci"}
    sites.ensure_blog = lambda t: {"blog_id": 1}
    sites.blog_note = lambda b: ""
    sites.backend = lambda profile: _B
    sites.is_live = lambda res: True
    sites.article_id_in = lambda res: "1"
    seo_guard.tenant_for = lambda profile: "baci"
    whatsapp.send_text = lambda *a, **k: None
    said = approvals.apply_decision(ap_id, "approved")
    rows = {m: _asset("baci", m) for m in media}
    ck("approving the article approves the pictures it carries — hero and body, owned",
       rows and all(r.review == "approved" and r.rights == kb.OWNED for r in rows.values()), str(said)[:160])
    ck("  and the featured image the store receives is the drawn hero",
       (sent.get("image") or {}).get("src") == (rows[hero_a].url if hero_a in rows else "?"),
       str(sent.get("image")))

    print("\n— THE WORKROOM CONTROL OFFERS THE MODEL, ONE PICTURE ONE MODEL —")
    with db.SessionLocal() as s:
        out2 = db.Output(tenant="baci", system_key="blog", format="cms_article", status="draft", media_ids=[])
        s.add(out2)
        s.commit()
        oid2 = out2.id
        s.add(db.ArtifactBody(tenant="baci", system_key="blog", format="cms_article", output_id=oid2,
                              body="<h1>Jugs</h1><p>A jug.</p>", meta={"keyword": "acrylic jug", "title": "Jugs"}))
        s.commit()
    keywords.upsert("baci", "acrylic jug")
    with db.SessionLocal() as s:
        kr = (s.query(db.KeywordTarget).filter(db.KeywordTarget.tenant == "baci",
                                                db.KeywordTarget.phrase == "acrylic jug").first())
        kr.output_id = oid2
        s.commit()
    art2, kw2, ap2 = _article_bundle(oid2)
    page2 = " ".join(ui.render_workroom(KEY, oid2, art2, kw2, ap2).split())
    ck("the Generate form carries the model, without 'both'",
       "Generate the picture" in page2 and 'name="image_model"' in page2 and 'value="both"' not in page2)
    config.GEMINI_API_KEY = "gk-test"
    rr = TestClient(web.app).post(f"/admin/article_picture?key={KEY}",
                                  data={"output_id": oid2, "image_model": imagegen.BOTH},
                                  follow_redirects=False)
    ck("the route refuses 'both' for one picture, by name",
       rr.status_code == 303 and "one picture, one model" in unquote(rr.headers.get("location", "")),
       unquote(rr.headers.get("location", ""))[-160:])
    config.GEMINI_API_KEY = ""
    seen_model: list = []
    creative.generate = lambda tenant, **k: (seen_model.append(k.get("image_model")) or
                                             {"ok": True, "url": "https://cdn/x.png", "asset_id": "a1",
                                              "assessment": {"ok": True, "failed": []}, "model": k.get("image_model")})
    rr2 = TestClient(web.app).post(f"/admin/article_picture?key={KEY}",
                                   data={"output_id": oid2, "image_model": imagegen.MODEL},
                                   follow_redirects=False)
    creative.generate = real_generate
    ck("  and a chosen model reaches the generator",
       rr2.status_code == 303 and seen_model == [imagegen.MODEL]
       and f"generated by {imagegen.MODEL}" in unquote(rr2.headers.get("location", "")),
       f"{seen_model} {unquote(rr2.headers.get('location', ''))[-160:]}")

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
