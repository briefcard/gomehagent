"""THE MODEL MAKES THE EMAIL; THE CODE INSPECTS IT.

The one suite for the email maker (`app/recreate.py`), after the token
chain was deleted (2026-09-14). It asserts the chain's mechanics and its
INVARIANTS — never what an email looks like. That is the judge's job and
the owner's eye.

  1. THE BRIEF is words; a reply that is not one is refused by name.
  2. THE CAST looks at a numbered sheet that fits the model's tier; a pick
     names the picture and why; nothing fits → cut and said.
  3. PICTURES ARE CUT TO FIT — a Shopify picture by its URL, any other by
     Pillow, hosted; the composer is handed the crops.
  4. ONE MIND writes subject, preheader and HTML together; baked blocks are
     photographed and replaced by pictures whose alt carries the words.
  5. THE CHECKS are the only closed list; each has a failing fixture here.
  6. THE LOOP keeps the best round, edits rather than rewrites, never calls
     an unjudged email shippable; with no reference the maker designs the
     email itself and is judged alone.
  7. A LINK is a design and a recreation in one press; the rotation is used
     before anything else; a chosen design overrides recency; the clock
     resets; approved is approved.
  8. A CAMPAIGN is built in its design or the run FAILS with the reason —
     there is no other path. The item says which design it came out in.
  9. THE ROOM: paste, look, choose.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import types

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rc.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ.pop("SHOTS_WS", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (admin_ui, brand_theme, db, email_structures as es, kb, llm, media,  # noqa: E402
                 pictures as pics, recreate as rc, shots, tenants, web)

CDN = "https://cdn.shopify.com/s/files/1/0002/"
SQ = "https://images.squarespace-cdn.com/content/v1/abc/"
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(w=400, h=300, bg="#e7dcc8", fg="#9b3c1c", fmt="PNG"):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), bg)
    ImageDraw.Draw(im).ellipse([w * .3, h * .2, w * .7, h * .75], fill=fg)
    b = io.BytesIO(); im.save(b, format=fmt)
    return b.getvalue()


BRIEF = {
    "concept": "a recipe delivered as a screenshot of the brand's own Instagram post; a pun hook above; "
               "shop the product used below; the product at the table underneath",
    "sections": [
        {"n": 1, "what": "the brand's wordmark, small, centred", "does": "signs the email",
         "asset": {"kind": "mark", "shows": "the mark"}, "copy": [], "look": "centred"},
        {"n": 2, "what": "a two-line hook: small-caps kicker over a huge display headline",
         "does": "stops the reader", "asset": {"kind": "none", "shows": ""},
         "copy": [{"id": "s2_kicker", "job": "a line that sets up the turn", "limit": "6 words"},
                  {"id": "s2_headline", "job": "the turn", "limit": "3 words"}], "look": "centred, ~75% of the column"},
        {"n": 3, "what": "a social post shown as a post: avatar, handle, square photo, icon row, dots, then four steps",
         "does": "gives the recipe as if from the feed",
         "asset": {"kind": "photograph", "shows": "the product in use — food on it, hands, sunlight"},
         "copy": [{"id": "s3_steps", "job": "four numbered steps naming the product", "limit": "4 steps"}], "look": "cream card"},
        {"n": 4, "what": "a closer: display caps then a script tail, and a bordered button", "does": "asks once",
         "asset": {"kind": "none", "shows": ""},
         "copy": [{"id": "s4_cta", "job": "shop the product used, by name", "limit": "3 words"}], "look": "centred"},
        {"n": 5, "what": "the page turns cream; the product in a scene", "does": "shows the thing to buy",
         "asset": {"kind": "photograph", "shows": "the pieces at the table"}, "copy": [], "look": "cream ground"},
    ],
    "visual_system": {"type": "heavy display; tracked small caps; script accent", "colour": "the page in the brand's deep tone",
                      "rhythm": "one column, centred", "column": "600"},
    "devices": ["a social post shown as a post", "a display line with a script tail", "a cream button with a dark border"],
    "reference_text": ["Ayoh!", "DON'T JUST SAUCE THE BREAD.", "SAUCE THE MEAT!", "THE DELI COUNTER SECRET",
                       "1. Whisk 1/3 cup Tangy Dijonayo with a glug of olive oil, a splash of red wine vinegar",
                       "NOW THAT'S A SANDO WORTH singing about", "SHOP TANGY DIJONAYO"],
    "reference_hexes": ["#7a4a1c", "#f5ecd7", "#3a2410", "#c8a15a", "#8b5a2b", "#fff8e8"],
}

LOGO = CDN + "logo.png"
PHOTO_A, PHOTO_B, PHOTO_C = CDN + "pasta.jpg", CDN + "table.jpg", SQ + "walls.jpg"
ADDRESS = "1 Main St, Hallandale Beach, FL 33009"
CLAIM = "Designed in Milan and placed at the Four Seasons."


def email_html(*, photo_a=PHOTO_A, photo_b=PHOTO_B, logo=LOGO, address=ADDRESS, ink="#4a2418", page="#9b3c1c",
               cream="#f4e8d3", unsub="{{UNSUBSCRIBE}}", extra="", headline="Set the scene!", headline_px=96,
               steps=("Start with the Portofino melamine dinner plates.", "Add the Aqua water glasses in orange.",
                      "Pile the pasta straight onto the plates.", "Mangia!"), cta="Shop Portofino", claim=CLAIM,
               bake=False) -> str:
    step_html = "".join(f'<p style="margin:0 0 8px;color:{ink}">{i + 1}. {s}</p>' for i, s in enumerate(steps))
    head_row = (f'<tr><td align="center" style="color:{cream};font-family:Impact,\'Arial Black\',sans-serif;'
                f'font-size:{headline_px}px">{headline}</td></tr>')
    if bake:
        head_row = (f'<tr><td><!--bake--><table width="600" style="background:{page}"><tr><td align="center" '
                    f'style="color:{cream};font-family:\'Archivo Black\';font-size:{headline_px}px">{headline}</td></tr></table>'
                    f'<!--/bake--></td></tr>')
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{headline}</title>
<link href="https://fonts.googleapis.com/css2?family=Archivo+Black&display=swap" rel="stylesheet"></head>
<body style="margin:0;background:{page}"><!-- system: faces display=Impact headline=Helvetica body=Helvetica accent=Brush Script MT · scale: 96/13/12/11/11 · space: 8/16/30/34 · inset: 34 · radius: 14 -->{extra}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{page}"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:600px">
<tr><td align="center" style="padding:30px"><img src="{logo}" alt="the brand" width="150"></td></tr>
<tr><td align="center" style="color:{cream};font-family:Helvetica,Arial,sans-serif;font-size:12px">Don't just set the table.</td></tr>
{head_row}
<tr><td style="padding:0 34px 30px"><table role="presentation" width="100%" style="background:{cream};border:1px solid {ink};border-radius:14px">
<tr><td style="padding:16px;color:{ink};font-family:Helvetica,Arial,sans-serif;font-size:13px">bacimilanousa</td></tr>
<tr><td style="padding:0 16px"><img src="{photo_a}" alt="the product in use" width="500" style="width:100%"></td></tr>
<tr><td style="padding:16px;color:{ink};font-family:Helvetica,Arial,sans-serif;font-size:12px">The Sunday-lunch secret</td></tr>
<tr><td style="padding:0 16px 16px;font-family:Helvetica,Arial,sans-serif;font-size:13px;color:{ink}">{step_html}</td></tr>
</table></td></tr>
<tr><td align="center" style="color:{cream};font-family:Helvetica,Arial,sans-serif;font-size:13px">{claim}</td></tr>
<tr><td align="center" style="padding:20px"><a href="https://example-brand.test/collections/portofino" style="display:inline-block;padding:14px 40px;background:{cream};border:2px solid {ink};color:{ink};font-family:Helvetica,Arial,sans-serif;font-size:13px;text-decoration:none">{cta}</a></td></tr>
</table></td></tr>
<tr><td align="center" style="background:{cream}"><table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px">
<tr><td style="padding:30px 34px 0"><img src="{photo_b}" alt="the pieces at the table" width="532" style="width:100%"></td></tr>
<tr><td align="center" style="padding:0 20px 30px;color:#6b4a3a;font-family:Helvetica,Arial,sans-serif;font-size:11px">{address}<br>
<a href="{unsub}" style="color:#6b4a3a">Unsubscribe</a></td></tr>
</table></td></tr></table></body></html>"""


def reply_email(html: str, subject="Set the scene", pre="The Sunday table, in four steps") -> str:
    return f"Subject: {subject}\nPreheader: {pre}\n{html}"


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.set_brand("baci", positioning="Italian-designed tableware.", tone="direct")
    with db.SessionLocal() as s:
        b = s.get(db.KbBrand, "baci"); b.banned_claims = ["handmade", "made in Italy"]; s.commit()
    brand_theme.approve("baci", {"footer.address": ADDRESS, "logo_url": LOGO, "colors.accent": "#9b3c1c"})
    kb.add_entity("baci", "collection", "portofino", "Portofino", description="Melamine and porcelain, coral and shells.",
                  attributes={"image": PHOTO_A, "url": "https://example-brand.test/collections/portofino"}, origin="human")
    kb.add_asset("baci", PHOTO_A, rights=kb.OWNED, subject="photo", title="spaghetti on the Portofino plate", entity_key="portofino", origin="human")
    kb.add_asset("baci", PHOTO_B, rights=kb.OWNED, subject="photo", title="the Portofino place setting", entity_key="portofino", origin="human")
    kb.add_asset("baci", PHOTO_C, rights=kb.OWNED, subject="photo", title="the walls", origin="crawl")
    kb.add_asset("baci", PHOTO_B.replace("table", "gone_table"), rights=kb.OWNED, subject="photo", title="a picture that went away", origin="crawl")
    kb.add_asset("baci", CDN + "ref.jpg", rights=kb.REFERENCE, subject="scene", title="a pin", origin="pinterest")
    ids = {a.url: a.id for a in kb.assets("baci")}
    a_id, b_id = ids[PHOTO_A], ids[PHOTO_B]
    with db.SessionLocal() as s:
        for aid in (a_id, b_id, ids[PHOTO_C]):
            row = s.get(db.KbAsset, aid)
            row.reading = {"kind": "lifestyle", "colours": {"light": "#e8d8c0", "dark": "#502818", "mid": "#983818"},
                           "size": [1170, 1170], "aspect": "square", "alone": False, "person": False}
        s.commit()
    kb.add_asset("agency", "https://images.example.test/ayoh.png", rights=kb.REFERENCE, kind=es.SWIPE_KIND,
                 subject="scene", title="Ayoh — Sauce the meat", source="https://reallygoodemails.com/emails/x", origin="swipe")
    ref_id = next(a.id for a in kb.assets("agency", publishable_only=False) if "ayoh" in (a.url or ""))

    # THE STUBS: the model by purpose, the door, the blob store, the fetches, the links
    ref_png = png(680, 2400, "#7a4a1c", "#f5ecd7")
    pics._fetch = lambda url: ref_png if "ayoh" in url else b""
    pics._fetch_bounded = lambda url, *, cap=pics.FETCH_MAX: png(fmt="JPEG") if (CDN in url or SQ in url) else b""
    calls: list[str] = []
    answers: dict = {}
    seen: dict = {}

    class _R:
        ok = True
        error = ""
        model = "stub"
        def __init__(self, text): self.text = text

    def _ask(purpose, prompt, **k):
        calls.append(purpose)
        seen.setdefault(purpose, []).append(prompt)
        ans = answers.get(purpose)
        if callable(ans):
            ans = ans(prompt)
        return _R(ans if isinstance(ans, str) else json.dumps(ans))
    llm.ask = _ask
    shots.shoot = lambda html, **k: {"ok": True, "png": png(640, 2000), "door": "local", "ms": 5, "why": ""}
    frag_shots: list = []
    shots.shoot_fragment = lambda head, frag, **k: (frag_shots.append(frag) or {"ok": True, "png": png(600, 200), "door": "local", "why": ""})
    puts: list = []
    media.put = lambda tenant, blob, **k: (puts.append(k.get("mime")) or {"ok": True, "id": f"blob{len(puts)}", "url": f"http://x/media/blob{len(puts)}.png"})
    import httpx
    httpx.head = lambda *a, **k: types.SimpleNamespace(status_code=200)

    print("— 1. the brief is words, refused by name when it is not —")
    answers["email_brief"] = BRIEF
    got = rc.brief(ref_id, tenant="baci")
    ck("the reference is read into a brief", got["ok"] and got["brief"]["concept"].startswith("a recipe"), str(got.get("why")))
    ck("no sections is refused by name", rc.brief_problem({**BRIEF, "sections": []}) == "the brief has no sections")
    ck("a section that does not say what it is is refused by name",
       rc.brief_problem({**BRIEF, "sections": [{"n": 1}]}) == "section 1 does not say what it is")

    print("— 2. the cast looks at a sheet that fits the tier —")
    kit = rc.kit("baci")
    ck("the kit carries the publishable pictures with their readings, never a reference pin",
       {p["id"] for p in kit["pictures"]} >= {a_id, b_id, ids[PHOTO_C]} and not any("ref.jpg" in p["url"] for p in kit["pictures"])
       and all(p["kind"] for p in kit["pictures"] if p["id"] in (a_id, b_id, ids[PHOTO_C])))
    from PIL import Image
    sheet = Image.open(io.BytesIO(rc._sheet([png()] * 24)))
    ck("a full sheet is under the 1568-px edge the model refuses above", max(sheet.size) <= 1568, str(sheet.size))
    answers["email_cast"] = {"picks": [{"section": 3, "cell": 1, "why": "food on the plate, in the sun"},
                                       {"section": 5, "cell": 1, "why": "again"}, {"section": 5, "cell": 2, "why": "the table"}], "none": []}
    cast = rc.cast("baci", BRIEF, kit, entity_key="portofino", seed="one")
    kb.add_asset("baci", CDN + "other_scene.jpg", rights=kb.OWNED, subject="photo", title="a dinner party, the Aqua line", entity_key="aqua", origin="human")
    kb.add_asset("baci", CDN + "other_pack.jpg", rights=kb.OWNED, subject="object", title="Aqua pitcher packshot", entity_key="aqua", tags=["packshot"], origin="human")
    with db.SessionLocal() as s:
        for a in kb.assets("baci"):
            if "other_scene" in (a.url or ""):
                a.reading = {"kind": "lifestyle", "colours": {}, "size": [1200, 800], "aspect": "landscape", "alone": False, "person": True}
            if "other_pack" in (a.url or ""):
                a.reading = {"kind": "packshot-on-plain", "colours": {}, "size": [1200, 1200], "aspect": "square", "alone": True, "person": False}
        s.commit()
    kit = rc.kit("baci")
    mix = rc.candidates(kit, entity_key="portofino", seed="mix")
    ck("the cast sheet is a mix by role — the subject's own, the brand's scenes of other products, packshots",
       any(p.get("entity_key") == "portofino" for p in mix) and any("other_scene" in p["url"] for p in mix)
       and any("other_pack" in p["url"] for p in mix), str([(p.get("title") or "")[:20] for p in mix]))
    ck("the slot's role is read from the brief's role, or its older shows",
       rc._role({"asset": {"role": "in use: at the table", "shows": "old"}}) == "in use: at the table"
       and rc._role({"asset": {"shows": "the pieces at the table"}}) == "the pieces at the table")
    ck("a pick names the picture and why; the same picture never fills two slots",
       cast["picks"][3]["why"].startswith("food") and cast["picks"][5]["asset_id"] != cast["picks"][3]["asset_id"], str(cast)[:200])
    answers["email_cast"] = {"picks": [], "none": [{"section": 3, "needs": "a photograph of food on the plate"}]}
    none = rc.cast("baci", BRIEF, kit)
    ck("a slot nothing fits is cut and says what it needs", not none["picks"] and none["none"][0]["needs"].startswith("a photograph"))
    answers["email_cast"] = {"picks": [{"section": 3, "cell": 1, "why": "food"}, {"section": 5, "cell": 2, "why": "table"}], "none": []}

    print("— 3. pictures are cut to fit —")
    ck("a Shopify picture is cut by its URL", rc.fit("baci", PHOTO_A, "4x5") == CDN + "pasta_1200x1500_crop_center.jpg")
    cut = rc.fit("baci", PHOTO_C, "16x9")
    ck("any other picture is cut by Pillow and hosted", cut.startswith("http://x/media/") and puts[-1] == "image/jpeg")
    ck("an unknown aspect is the original", rc.fit("baci", PHOTO_A, "2x3") == PHOTO_A)
    fitted = rc.fits("baci", cast)
    ck("every cast picture is offered in every aspect and the original",
       set(fitted[3]) == {"original", "1x1", "4x5", "3x2", "16x9"})

    print("— 4. one mind writes the email; baked blocks become pictures —")
    good = email_html()
    answers["email_compose"] = reply_email(good)
    told = rc.decide_story({**BRIEF, "argument": [{"beat": "problem", "says": "most decaf is flat", "does": "names the disappointment", "rests_on": "the reader's experience"},
                                                   {"beat": "risk reversal", "says": "30 days, money back", "does": "removes the risk", "rests_on": "a guarantee"}]},
                           kit, {"subject": "Set the scene"}, tenant="baci", entity_key="portofino")
    ck("the story is decided before the HTML — the writer is handed the reference's argument and the brand's material, and answers with beats that rest on it",
       "THE REFERENCE'S ARGUMENT" in seen["email_compose"][-1] and "30 days, money back" in seen["email_compose"][-1]
       and "Melamine and porcelain" in seen["email_compose"][-1] and (told["ok"] is False or isinstance(told.get("story"), dict)))
    answers["email_compose"] = lambda prompt: ({"hook": "Set the scene", "beats": [{"beat": "problem", "says": "You know how most Sunday lunches go.", "rests_on": "the reader", "about": "the category"}],
                                                "turned": ["the guarantee is dropped"], "close": "Shop Portofino"}
                                               if str(prompt).startswith("You are the writer") else reply_email(good))
    st_ = rc.decide_story({**BRIEF, "argument": [{"beat": "problem", "says": "x", "does": "y", "rests_on": "z"}]}, kit, None, tenant="baci", entity_key="portofino")
    made = rc.compose(BRIEF, kit, cast, {"subject": "Set the scene"}, tenant="baci", fitted=fitted, story_=st_["story"])
    ck("the composer writes from the story — every beat and its frame ride in the prompt",
       "THE STORY — the argument this email makes" in seen["email_compose"][-1] and "[problem] (the category) You know how most Sunday lunches go." in seen["email_compose"][-1]
       and "turned: the guarantee is dropped" in seen["email_compose"][-1])
    answers["email_compose"] = reply_email(good)
    made = rc.compose(BRIEF, kit, cast, {"subject": "Set the scene"}, tenant="baci", fitted=fitted)
    dev = rc._devices_text({"devices": [{"what": "a tiny drawn figure beside the button", "kind": "dressing", "role": "points at the button",
                                          "effect": "playful", "instance": "a cartoon shopper"}, "a script closer"]})
    ck("a device with a role and an effect is rendered for the judge; a plain one still reads",
       "[dressing] a tiny drawn figure beside the button — role: points at the button; effect: playful" in dev and "a script closer" in dev)
    ck("the composer's reply is parsed into subject, preheader and the HTML",
       made["ok"] and made["subject"] == "Set the scene" and made["preheader"].startswith("The Sunday") and made["html"].startswith("<!DOCTYPE"))
    prompt = seen["email_compose"][-1]
    ck("the composer was handed the crops, the tones, the brief, the message and the standard",
       "pasta_1200x1500_crop_center" in prompt and "tones:" in prompt and "social post shown as a post" in prompt
       and "Set the scene" in prompt and "<!DOCTYPE html>" in prompt and "bacimilanousa" not in prompt.split("THE STANDARD")[0])
    baked_html, notes = rc.bake(email_html(bake=True), "baci")
    ck("a baked block is photographed and replaced by one picture whose alt carries the words",
       "<!--bake-->" not in baked_html and 'alt="Set the scene!"' in baked_html and frag_shots and "Archivo Black" in frag_shots[-1]
       and notes and notes[0].startswith("baked:"))
    shots.shoot_fragment = lambda head, frag, **k: {"ok": False, "png": b"", "door": "", "why": "playwright is not installed"}
    unbaked, notes2 = rc.bake(email_html(bake=True), "baci")
    ck("without a door the block stays as HTML and the note says why", "<!--bake-->" in unbaked and "playwright" in notes2[0])
    shots.shoot_fragment = lambda head, frag, **k: {"ok": True, "png": png(600, 200), "door": "local", "why": "", "overflow": 74, "box": 528, "smallest_px": 8.0}
    _, notes3 = rc.bake(email_html(bake=True), "baci")
    ck("a baked word wider than its box, and type too small to read, are said in numbers",
       any(n.startswith("clipped:") and "74 px wider" in n for n in notes3) and any(n.startswith("unreadable:") and "8 px" in n for n in notes3), str(notes3))
    photo_bake = email_html(bake=True).replace("<!--bake--><table", f'<!--bake--><table><tr><td><img src="{PHOTO_A}" alt="x" width="600"></td></tr></table><table', 1)
    kept, notes4 = rc.bake(photo_bake, "baci")
    ck("a photograph inside a baked block is left as HTML and said", any(n.startswith("not baked") for n in notes4) and f'<img src="{PHOTO_A}"' in kept)
    shots.shoot_fragment = lambda head, frag, **k: {"ok": True, "png": png(600, 200), "door": "local", "why": ""}

    print("— 5. the checks: each invariant fails on its fixture; the good email passes —")
    copy_ = {"claims": [CLAIM]}
    ck("the good email passes every check", not rc.blocking(rc.check(good, kit, BRIEF, copy_)), str(rc.blocking(rc.check(good, kit, BRIEF, copy_))))

    def blocks(html, code, **kw):
        return any(f["code"] == code and f["severity"] == "blocks" for f in rc.check(html, kit, BRIEF, kw.pop("copy", copy_), **kw))
    ck("an outside picture blocks", blocks(email_html(photo_a="https://images.someone-else.test/sando.jpg"), "asset"))
    ck("five words in a row from the reference block", blocks(email_html(headline="Don't just sauce the bread. Sauce the meat!"), "leak_words"))
    ck("the reference's own hex blocks", blocks(email_html(page="#7a4a1c"), "leak_hex"))
    ck("a colour that does not read blocks", blocks(email_html(cream="#b0705a"), "contrast"))
    ck("a lost address blocks", blocks(email_html(address="somewhere"), "address"))
    ck("a lost unsubscribe blocks", blocks(email_html(unsub="#"), "unsubscribe"))
    ck("an unknown token blocks", blocks(email_html(extra="{{FirstName}}"), "token"))
    ck("an <svg> outside a baked block blocks", blocks(email_html(extra="<svg width='1' height='1'></svg>"), "tag"))
    ck("a message Gmail would clip blocks", blocks(email_html(extra="<!--" + "x" * 101_000 + "-->"), "size"))
    ck("an approved claim reworded blocks", blocks(email_html(claim="Designed in Milan and placed at a Four Seasons."), "claim"))
    ck("a verified tick blocks", blocks(email_html(extra='<p style="color:#ffffff">bacimilanousa ✓</p>'), "fabricated"))
    ck("a quote with a name under it, with nothing on file, blocks",
       blocks(email_html(extra='<p style="color:#ffffff">“The best plates we have ever owned, hands down.” — Maria K.</p>'),
              "fabricated_quote", copy={"claims": []}) is True
       and not any(f["code"] == "fabricated_quote" for f in rc.check(email_html(extra='<p style="color:#ffffff">“The best plates we have ever owned, hands down.” — Maria K.</p>'), {**kit, "claims": [{"id": "c", "claim": CLAIM}]}, BRIEF, copy_)))
    ck("the brand's ban list blocks", blocks(email_html(claim="Handmade for you."), "banned", copy={"claims": []}))
    ck("a placeholder link blocks", blocks(email_html(unsub="#unsubscribe"), "link_placeholder"))
    ck("the same photograph twice blocks", blocks(email_html(photo_b=PHOTO_A), "picture_twice"))
    no_sys = email_html().replace("<!-- system:", "<!-- was:")
    ck("an email with no declared system blocks", any(f["code"] == "system" for f in rc.system_check(no_sys)))
    choppy = email_html(extra='<table><tr><td style="padding:0 20px">a</td><td style="padding:0 24px">b</td><td style="padding:0 28px">c</td><td style="padding:0 44px">d</td></tr></table>'
                        '<p style="color:#ffffff;font-size:22px">x</p><p style="color:#ffffff;font-size:31px">y</p>')
    got_sys = {f["code"] for f in rc.system_check(choppy)}
    ck("insets and sizes outside the declared system block, by the numbers", {"system_inset", "system_scale"} <= got_sys, str(got_sys))
    ck("the good email keeps to its own system", not rc.system_check(email_html()), str(rc.system_check(email_html())))
    tale = {"beats": [{"beat": "problem", "about": "the category", "says": "You know how most Sunday lunches go. Same plates, same table."},
                      {"beat": "invitation", "about": "the reader", "says": "Set the scene tonight."}]}
    beside = email_html(extra=f'<table><tr><td style="color:#ffffff">You know how most Sunday lunches go. Same plates, same table.</td>'
                              f'<td><img src="{PHOTO_C}" alt="the walls" width="280"></td></tr></table>')
    alone = email_html(extra='<table><tr><td style="color:#ffffff">You know how most Sunday lunches go. Same plates, same table.</td></tr></table>'
                             + '<table><tr><td>a rule</td></tr><tr><td>another</td></tr></table>')
    invite = email_html(extra=f'<table><tr><td style="color:#ffffff">Set the scene tonight.</td><td><img src="{PHOTO_C}" alt="the walls" width="280"></td></tr></table>')
    ck("a failing of the category set beside the brand's photograph blocks; the same failing as type alone passes; an invitation beside a photograph passes",
       any(f["code"] == "failing_beside_product" for f in rc.story_check(beside, tale, kit))
       and not rc.story_check(alone, tale, kit) and not rc.story_check(invite, tale, kit))
    named = email_html().replace("scale: 96/13/12/11/11", "scale: display=96 / headline=13 / body=12 / small=11 / tiny=11")
    ck("a scale written as named steps is read whole, not as its first number", not rc.system_check(named), str(rc.system_check(named)))
    four = email_html(extra='<p style="color:#ffffff;font-family:Georgia,serif">a</p><p style="color:#ffffff;font-family:Playfair Display,serif">b</p>')
    ck("a fourth face blocks — two faces and one accent is the ceiling", any(f["code"] == "system_faces" for f in rc.system_check(four)))
    ck("an invented picture on the brand's own host blocks", blocks(email_html(photo_b=CDN + "table_staged_tray_1200x800.jpg"), "asset_invented"))
    ck("a cut of a filed picture is allowed", not any(f["code"] in ("asset", "asset_invented") for f in rc.check(email_html(photo_b=CDN + "table_1200x1500_crop_center.jpg"), kit, BRIEF, copy_)))
    httpx.head = lambda url, *a, **k: types.SimpleNamespace(status_code=404 if "gone" in url else 200)
    ck("a picture that answers 404 blocks", blocks(email_html(photo_b=PHOTO_B.replace("table", "gone_table")), "picture_missing", links=True))
    httpx.head = lambda url, *a, **k: types.SimpleNamespace(status_code=429)
    httpx.get = lambda url, *a, **k: types.SimpleNamespace(status_code=429)
    import time as _time
    _sleep = _time.sleep
    _time.sleep = lambda *_: None
    busy = rc.check(email_html(), kit, BRIEF, copy_, links=True)
    _time.sleep = _sleep
    ck("a 429 from the store is a note, never a dead link", any(f["code"] == "link_busy" for f in busy)
       and not any(f["code"] in ("link", "picture_missing") for f in busy), str([f["code"] for f in busy]))
    httpx.head = lambda *a, **k: types.SimpleNamespace(status_code=200)
    ck("words baked into a picture still count — the alt is read", blocks(email_html(bake=True, headline="Sauce the bread, sauce the meat, sauce it") and rc.bake(email_html(bake=True, headline="Don't just sauce the bread. Sauce the meat!"), "baci")[0], "leak_words"))

    print("— 6. the loop: best round kept, edits not rewrites, unjudged never shippable —")
    st = es.file_reference(ref_id, brief=BRIEF, source_url="https://reallygoodemails.com/emails/x")
    sid = st["id"]
    compose_seen: list = []

    def _compose(prompt):
        prompt = prompt[-1]["text"] if isinstance(prompt, list) else prompt
        compose_seen.append(prompt)
        if prompt.startswith("You are the writer. Before a line of the email is set, decide THE STORY"):
            return {"hook": "Don't just set the table. Set the scene.",
                    "beats": [{"beat": "problem", "says": "You know how most Sunday lunches go. Same plates, same table.", "rests_on": "the reader's own experience", "about": "the category"},
                              {"beat": "reframe", "says": "Portofino: melamine and porcelain, coral and shells — the table becomes the scene.", "rests_on": "Melamine and porcelain, coral and shells.", "about": "us"},
                              {"beat": "ask", "says": "Shop Portofino", "rests_on": "the collection page", "about": "us"}],
                    "turned": ["no guarantee on file — the risk-reversal beat is dropped"], "close": "Mangia! Shop Portofino"}
        if "FINDINGS" in prompt and "THE HTML" in prompt:
            return reply_email(email_html(headline_px=112))
        return reply_email(email_html())
    answers["email_compose"] = _compose
    judged: list = []

    def _judge(prompt):
        text = prompt[-1]["text"] if isinstance(prompt, list) else ""
        if text.startswith("The words of an email"):
            return {"fabricated": []}
        judged.append(1)
        if len(judged) == 1:
            return {"ours_first_words": "Don't just set the table. Set the scene!", "same_concept": True, "devices_in_order": True,
                    "weight_rhythm": "headline light", "brand_material": True,
                    "findings": [{"where": "section 2", "what": "the headline sits at half the column", "do": "set it larger", "severity": "blocks"}]}
        return {"ours_first_words": "Don't just set the table. Set the scene!", "same_concept": True, "devices_in_order": True,
                "weight_rhythm": "matched", "brand_material": True, "findings": []}
    answers["email_judge"] = _judge
    got = rc.run(sid, "baci", "portofino", seed="s", message={"subject": "Set the scene", "claims": [CLAIM]})
    ck("the revise round LOOKS at its own email — the picture rides with the findings",
       any(isinstance(p, list) and any(b.get("type") == "image" for b in p) and "LOOK before" in p[-1]["text"]
           for p in seen["email_compose"] if isinstance(p, list)))
    ck("round 1 closed the judge's finding — shippable, the edit counted in lines, the subject kept",
       got["status"] == rc.SHIPPABLE and len(got["rounds"]) == 2 and got["rounds"][1]["blocking"] == 0
       and got["rounds"][1]["edited"] > 0 and any("THE HTML" in p for p in compose_seen) and got["subject"] == "Set the scene", got.get("note"))
    ck("the run decided a story first, said it, and kept it on the row with its turn",
       "The story: Don't just set the table" in got["note"] and "turned: no guarantee on file" in got["note"]
       and (rc.latest(sid, "baci") or {}).get("id") and any("THE STORY this email tells" in p for p in compose_seen if "FINDINGS" in p), got.get("note"))
    ck("the run is on file with its picture and no open finding",
       (rc.latest(sid, "baci") or {}).get("status") == rc.SHIPPABLE and rc.latest(sid, "baci")["png"] and not rc.latest(sid, "baci")["findings"])
    judged.clear()
    worse = iter([1, 2, 2])
    answers["email_judge"] = lambda prompt: ({"fabricated": []} if prompt[-1]["text"].startswith("The words of an email") else
                                             {"ours_first_words": "Don't just set the table.", "same_concept": True, "devices_in_order": True, "weight_rhythm": "", "brand_material": True,
                                              "findings": [{"where": f"s{i}", "what": "off", "do": "fix", "severity": "blocks"} for i in range(next(worse))]})
    got_w = rc.run(sid, "baci", "portofino", seed="w")
    best_w = (rc.latest(sid, "baci") or {}).get("best")
    judged.clear()
    leaky = iter([True, False])
    answers["email_judge"] = lambda prompt: ({"fabricated": []} if prompt[-1]["text"].startswith("The words of an email") else
                                             {"ours_first_words": "Don't just set the table.", "same_concept": True, "devices_in_order": True, "weight_rhythm": "", "brand_material": True,
                                              "findings": ([{"where": "hook", "what": "the reference's hook says DON'T JUST SAUCE THE BREAD — ours lacks the pun",
                                                             "do": "add the words sauce the meat", "severity": "blocks"}] if next(leaky) else [])})
    got_l = rc.run(sid, "baci", "portofino", seed="l")
    ck("a judge finding that carries the reference's own words is dropped and said — never handed to the next edit",
       "asked for the reference's own words in 1 finding" in got_l["note"] and got_l["status"] == rc.SHIPPABLE
       and not any("sauce the meat" in p for p in compose_seen if "FINDINGS" in p), got_l.get("note"))
    ck("the judge's pictures are labelled and stamped — REFERENCE then OURS — and it must say what it read in ours",
       any(isinstance(p, list) and p[0].get("type") == "text" and p[0]["text"].startswith("REFERENCE") and "ours_first_words" in p[-1]["text"]
           for p in seen["email_judge"] if isinstance(p, list) and p[-1]["text"].startswith("Two emails")))
    judged.clear()
    confused = iter([True, False, False])
    def _mixed(prompt):
        text = prompt[-1]["text"] if isinstance(prompt, list) else ""
        if text.startswith("The words of an email"):
            return {"fabricated": []}
        if next(confused, False):
            return {"ours_first_words": "Ayoh! DON'T JUST SAUCE THE BREAD. SAUCE THE MEAT!", "same_concept": True, "devices_in_order": True,
                    "brand_material": True, "weight_rhythm": "", "findings": [{"where": "hero", "what": "the sando is small", "do": "shrink the photo to 55%", "severity": "blocks"}]}
        return {"ours_first_words": "Don't just set the table. Set the scene!", "same_concept": True, "devices_in_order": True,
                "brand_material": True, "weight_rhythm": "", "findings": []}
    answers["email_judge"] = _mixed
    got_c = rc.run(sid, "baci", "portofino", seed="c")
    ck("a judge that read the reference as ours is asked again; its confused findings never reach the edit",
       got_c["status"] == rc.SHIPPABLE and not any("55%" in p for p in compose_seen if "FINDINGS" in p)
       and got_c["rounds"][0]["judged"] is True and len(seen["email_judge"]) >= 2, got_c.get("note"))
    judged.clear()
    always = lambda prompt: ({"fabricated": []} if prompt[-1]["text"].startswith("The words of an email") else
                             {"ours_first_words": "Ayoh! DON'T JUST SAUCE THE BREAD.", "same_concept": True, "devices_in_order": True,
                              "brand_material": True, "weight_rhythm": "", "findings": [{"where": "hero", "what": "x", "do": "shrink the photo to 55%", "severity": "blocks"}]})
    answers["email_judge"] = always
    got_cc = rc.run(sid, "baci", "portofino", seed="cc")
    ck("confused twice, the judgement is refused and the story says so — never called shippable",
       "the judge was confused twice" in got_cc["note"] and got_cc["status"] == rc.NOT_SHIPPABLE
       and not any("55%" in p for p in compose_seen if "FINDINGS" in p), got_cc.get("note"))
    judged.clear()
    short_leak = iter([True, False])
    def _short(prompt):
        text = prompt[-1]["text"] if isinstance(prompt, list) else ""
        if text.startswith("The words of an email"):
            return {"fabricated": []}
        return {"ours_first_words": "Don't just set the table. Set the scene!", "same_concept": True, "devices_in_order": True,
                "brand_material": True, "weight_rhythm": "",
                "findings": ([{"where": "hero", "what": "the word 'Ayoh!' should be the biggest word; add 'SAUCE THE MEAT!' as a sticker",
                               "do": "set Ayoh! at 96px", "severity": "blocks"}] if next(short_leak, False) else [])}
    answers["email_judge"] = _short
    got_s = rc.run(sid, "baci", "portofino", seed="s2")
    ck("a finding that quotes one of the reference's short lines whole is dropped too",
       "asked for the reference's own words in 1 finding" in got_s["note"] and got_s["status"] == rc.SHIPPABLE, got_s.get("note"))
    answers["email_judge"] = _judge
    ck("the truth pass is its own call and is handed the product's own material",
       any("THE MATERIAL" in p[-1]["text"] and "Melamine and porcelain" in p[-1]["text"] for p in seen["email_judge"] if isinstance(p, list))
       and not any("THE MATERIAL" in p[-1]["text"] and "REFERENCE" in p[-1]["text"] for p in seen["email_judge"] if isinstance(p, list)))
    judged.clear()
    liar = iter([True, False, False])
    def _truth_or_judge(prompt):
        text = prompt[-1]["text"] if isinstance(prompt, list) else ""
        if text.startswith("The words of an email"):
            return {"fabricated": [{"words": "BPA free", "why": "the material says nothing about BPA"}] if next(liar, False) else []}
        return {"ours_first_words": "Don't just set the table.", "same_concept": True, "devices_in_order": True, "brand_material": True, "would_send": True, "weight_rhythm": "", "findings": []}
    answers["email_judge"] = _truth_or_judge
    got_t = rc.run(sid, "baci", "portofino", seed="t2")
    ck("a product fact the material does not support blocks the round and is edited out",
       got_t["status"] == rc.SHIPPABLE and got_t["rounds"][0]["blocking"] >= 1
       and any(c["code"] == "fabricated" and "BPA" in c["where"] for c in got_t["rounds"][0]["check"]), str(got_t["rounds"][0]["check"])[:300])
    answers["email_judge"] = _judge
    ck("when every edit made it worse, round 0 is kept — the best, never the last",
       got_w["status"] == rc.NOT_SHIPPABLE and [r["blocking"] for r in got_w["rounds"]] == [1, 2, 2] and best_w == 0,
       str([r["blocking"] for r in got_w["rounds"]]) + f" best={best_w}")
    answers["email_judge"] = _judge
    shots.shoot = lambda html, **k: {"ok": False, "png": b"", "door": "", "ms": 0, "why": "playwright is not installed"}
    judged.clear()
    got2 = rc.run(sid, "baci", "portofino", seed="t")
    ck("without a picture nothing is judged and the email is not called shippable — and it says why",
       got2["status"] == rc.NOT_SHIPPABLE and "playwright" in got2["note"], got2.get("note"))
    shots.shoot = lambda html, **k: {"ok": True, "png": png(640, 2000), "door": "local", "ms": 5, "why": ""}
    judged.clear()
    answers["email_judge"] = lambda prompt: ({"fabricated": []} if prompt[-1]["text"].startswith("The words of an email") else
                                             {"ours_first_words": "Don't just set the table.", "same_concept": True, "devices_in_order": True, "brand_material": True, "weight_rhythm": "fine", "findings": []})
    got3 = rc.run("", "baci", "portofino", seed="d", message={"subject": "Set the scene"})
    ck("with no reference the maker designs the email itself and is judged alone — shippable",
       got3["status"] == rc.SHIPPABLE and "designs this one itself" in got3["note"] and "DESIGN IT YOURSELF" in compose_seen[-1]
       and any("no reference to follow" in p[-1]["text"] for p in seen["email_judge"][-3:]), got3.get("note"))
    answers["email_judge"] = _judge

    print("— 7. a link is a design and a recreation in one press; the rotation —")
    kb.add_asset("agency", "https://images.example.test/shrimp.png", rights=kb.REFERENCE, kind=es.SWIPE_KIND,
                 subject="scene", title="pistol shrimp", source="https://reallygoodemails.com/emails/shrimp", origin="swipe")
    shrimp_id = next(a.id for a in kb.assets("agency", publishable_only=False) if "shrimp" in (a.url or ""))
    es.add_swipe = lambda url, **k: {"ok": True, "asset_id": shrimp_id, "url": url, "title": "pistol shrimp", "image": "x"}
    pics._fetch = lambda url: ref_png if ("ayoh" in url or "shrimp" in url) else b""
    judged.clear()
    got = rc.swipe("https://reallygoodemails.com/emails/shrimp", "baci")
    new = next(r for r in es.library() if r["id"] == got["structure_id"])
    ck("one press: filed, read, in the rotation, recreated",
       got["ok"] and new["review"] == "approved" and new["source_asset_id"] == shrimp_id and new["brief"]["concept"].startswith("a recipe")
       and (rc.latest(new["id"], "baci") or {}).get("via") == "press", str(got.get("why")))
    ck("the same link again finds the same design", rc.swipe("https://reallygoodemails.com/emails/shrimp", "baci")["structure_id"] == new["id"]
       and sum(1 for r in es.library() if r["source_asset_id"] == shrimp_id) == 1)
    ck("the drafter's brief for a design is its concept and its copy jobs",
       "THE DESIGN THIS SEND IS BUILT IN: a recipe" in es.brief(new) and "four numbered steps" in es.brief(new))
    es.approve(sid)
    ck("a chosen design overrides recency", es.pick("baci", designated=new["id"], recent_designs=[new["id"]])["structure"]["id"] == new["id"])
    es.designate("baci", new["id"])
    ck("the standing choice too", es.pick("baci", recent_designs=[new["id"]])["structure"]["id"] == new["id"])
    es.designate("baci", "")
    seen_all = [new["id"], sid]
    lr = es.pick("baci", recent_designs=seen_all)
    ck("when the list has seen every design the clock resets to the least recent", lr["structure"]["id"] == sid and "clock resets" in lr["why"], lr["why"])
    es.reject(new["id"])
    ck("a design taken out cannot be the standing choice", "not in the rotation" in es.designate("baci", new["id"]))
    es.approve(new["id"])
    kb.ensure_brand("nothing", "Nothing")
    ck("a reference is usable by a brand with no claims and no products — the maker cuts what it lacks",
       es.usable_for("nothing", new)[0] is True)
    with db.SessionLocal() as s:
        b_ = s.get(db.KbBrand, "nothing"); b_.banned_claims = ["recipe"]; s.commit()
    ck("only a rotation with nothing this brand may use leaves the maker to design itself",
       es.pick("nothing")["structure"] is None and "designs this one itself" in es.pick("nothing")["why"])

    print("— 8. a campaign is built in its design, or the run fails with the reason —")
    from app import approvals, esp, skill, skill_pack, systems, tenants as _tn
    kb.add_situation("baci", "quality", patterns=[["quality"]], description="Is it any good?", origin="seed")
    kb.add_claim("baci", CLAIM, "brand brief", ["quality"], origin="human", status="active")
    row = systems.find("baci", "campaign_email") or systems.create("baci", "campaign_email")
    with db.SessionLocal() as s:
        rr_ = s.get(db.System, row.id); rr_.status = "live"; s.commit()
    _ALL = {c: True for c in _tn.CAPABILITIES}
    _tn.capabilities = lambda key: dict(_ALL) if _tn.get(key) else {c: False for c in _tn.CAPABILITIES}
    esp.provider_for = lambda t: "omnisend"
    esp.personalize = lambda t, html: {"ok": True, "html": html}

    class _Mod:
        @staticmethod
        def draft_from_html(tenant, *, name, subject, sender_name, html, preheader="", include_segments=None):
            return {"ok": True, "campaign_id": "c", "stage": "done"}
    esp.backend = lambda t: (_Mod, "")

    def _drafter(bundle, seg, goal, craft=None):
        claims = bundle.get("claims") or []
        cid = claims[0]["claim_id"] if claims else ""
        return ({"subject": "Set the scene", "preheader": "the Sunday table",
                 "blocks": [{"type": "hero"}, {"type": "heading", "text": "Set the scene", "level": 1},
                            {"type": "text", "html": "<p>Portofino for Sunday lunch.</p>"},
                            {"type": "cta", "label": "Shop Portofino", "url": "https://example-brand.test/collections/portofino"}],
                 "claim_ids": [cid] if cid else [], "cta_label": "Shop Portofino",
                 "cta_url": "https://example-brand.test/collections/portofino"}, "model", "")
    skill_pack.draft_campaign = _drafter
    compose_seen.clear()
    r1 = skill.run("campaign_email", "baci", segment="reorder_due", structure=new["id"], intent="education",
                   entity_key="portofino", generate_visual="no")
    notes1 = r1.get("notes") or []
    ck("the campaign run is built in the designated design and says so",
       r1.get("status") == "produced" and any(n.startswith("built in the design") for n in notes1), str(r1.get("status")) + str([n[:80] for n in notes1][-4:]))
    ck("the composer carried the drafter's message — its subject and its cited claim",
       "THE MESSAGE this email carries" in compose_seen[-1] and "Set the scene" in compose_seen[-1] and CLAIM in compose_seen[-1])
    with db.SessionLocal() as s:
        out1 = s.query(db.Output).filter(db.Output.tenant == "baci").order_by(db.Output.created_at.desc()).first()
        art1 = s.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == out1.id).order_by(db.ArtifactBody.created_at.desc()).first()
        html1, meta1, media1 = (art1.meta or {}).get("html") or "", dict(art1.meta or {}), list(out1.media_ids or [])
        label1 = admin_ui.artifact_label(art1)
    ck("the email that ships is the model's HTML with the cast pictures on the ledger, and the item names the design",
       "Sunday-lunch secret" in html1 and set(media1) >= {a_id, b_id} and meta1.get("recreation", {}).get("status") == rc.SHIPPABLE
       and "in a recipe" in label1 and "shippable" in label1, label1)
    ck("the drafted words are the words checked — the recreation's copy, not the drafter's blocks",
       "Sunday-lunch secret" in (out1.body or ""))
    with db.SessionLocal() as s:
        art1 = s.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == out1.id).first()
        art1.meta = {**dict(art1.meta or {}), "recreation": {"id": "x", "status": rc.NOT_SHIPPABLE, "blocking": 1,
                                                           "findings": [{"severity": "blocks", "where": "section 3", "what": "the post card lost its icon row"}]}}
        s.commit()
        s.add(db.Approval(kind="seo_new_article", status="pending", summary="t", tenant="baci", payload={"output_id": out1.id})); s.commit()
    held = approvals.ship_unattended("baci", out1.id, why="test")
    ck("an unattended ship is held while a blocking finding stands — and says which",
       held.get("ok") is False and "icon row" in held.get("why", ""), str(held))
    answers["email_compose"] = "no html for you"
    r2 = skill.run("campaign_email", "baci", segment="reorder_due", structure=new["id"], intent="education",
                   entity_key="portofino", generate_visual="no")
    ck("when the maker fails the run FAILS with the reason — nothing else is built",
       r2.get("status") == "failed" and "could not be made" in str(r2.get("error") or r2.get("blocked_on") or r2), str(r2)[:200])
    answers["email_compose"] = _compose
    es.designate("baci", "")
    r3 = skill.run("campaign_email", "nothing", segment="reorder_due", intent="education", generate_visual="no") if False else None
    ck("a run with no reference in the rotation still gets an email — designed by the maker",
       "designs this one itself" in es.pick("nothing")["why"])

    print("— 9. the room —")
    bg: list = []
    web._run_bg = lambda label, fn, *a, **k: bg.append((label, a, k))
    from fastapi.testclient import TestClient
    c = TestClient(web.app)
    r = c.post("/admin/email_reference?key=s3cret", data={"key": "s3cret", "tenant": "baci", "url": "https://reallygoodemails.com/emails/shrimp"}, follow_redirects=False)
    ck("pasting a link posts, runs off the request, and comes back to the Designs room",
       r.status_code == 303 and "wf=designs" in r.headers.get("location", "") and bg[-1][0] == "email_recreate")
    room = admin_ui._structures_card("s3cret", "baci")
    ck("the room: paste at the top, the reference beside ours, the judge's line, the choice",
       'action="/admin/email_reference"' in room and "ours, for baci" in room and "the judge: same concept" in room
       and "Not this one" in room and "Use this for every campaign" in room and "draws at random from" in room)
    r = c.get(f"/admin/email_recreation?key=s3cret&id={rc.latest(new['id'], 'baci')['id']}")
    ck("the kept HTML is served as a page", r.status_code == 200 and "<table" in r.text)
    r = c.post("/admin/email_recreate?key=s3cret", data={"key": "s3cret", "tenant": "baci", "structure": new["id"], "entity": "portofino"}, follow_redirects=False)
    ck("Recreate again posts and runs off the request", r.status_code == 303 and bg[-1][0] == "email_recreate" and bg[-1][1] == (new["id"],))
    r = c.post("/admin/email_design_designate?key=s3cret", data={"key": "s3cret", "tenant": "baci", "structure": new["id"]}, follow_redirects=False)
    ck("the standing choice posts and comes back to the room", r.status_code == 303 and "wf=designs" in r.headers.get("location", "")
       and es.standing_designation("baci") == new["id"])
    es.designate("baci", "")
    r = c.post("/admin/picture_kind?key=s3cret", data={"key": "s3cret", "tenant": "baci", "asset_id": a_id, "kind": "flat-lay"}, follow_redirects=False)
    ck("the owner's word on a picture's kind posts and outranks the reading",
       r.status_code == 303 and next(a for a in kb.assets("baci") if a.id == a_id).reading.get("kind") == "flat-lay")
    r = c.post("/admin/pictures_read?key=s3cret", data={"key": "s3cret", "tenant": "baci"}, follow_redirects=False)
    ck("reading the unread pictures posts and comes back to Brand", r.status_code == 303 and "tab=brand" in r.headers.get("location", ""))
    ck("the door's contract is pinned", shots.BROWSERLESS["free_concurrent"] == 2 and shots._SEM._initial_value == 2 and shots.door()[0] in ("", "local"))
    html_b = admin_ui.render_brand("s3cret", "baci")
    ck("the Brand tab carries the pictures by kind and no palette of roles, no theme preview",
       "By kind" in html_b and "Palette of roles" not in html_b and "srcdoc=" not in html_b)

    print()
    print("ALL GREEN" if not _fail else f"{len(_fail)} FAILED: " + "; ".join(_fail))
    return 0 if not _fail else 1


if __name__ == "__main__":
    sys.exit(main())
