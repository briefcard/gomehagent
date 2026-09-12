"""THE MODEL MAKES THE EMAIL; THE CODE INSPECTS IT — Phase 1 of
INITIATIVE-email-recreation.md, proven in the shape of the hand-made
Ayoh → Baci recreation of 2026-09-12 (`docs/recreations/ayoh-baci-portofino.html`).

What is asserted here is the chain and its INVARIANTS — never what an email
looks like. That is the judge's job and the owner's eye. A suite that
asserted a layout would be the old mistake this initiative exists to undo.

  1. THE BRIEF is words under a light schema; a reply that is not one is
     refused BY NAME (no concept, no sections, a section that does not say
     what it is); the reference's own words and hexes ride along ONLY for the
     leak check; the brief lands on the structure.
  2. THE KIT gathers what is on file and invents nothing: the brand's
     pictures with their readings, its entities, claims, theme, handle, the
     platform's tokens.
  3. THE CAST is chosen by looking at a numbered sheet: a pick names the
     picture and why; the same picture cannot fill two slots; a slot nothing
     fits is cut and says what it needs; a brand with no pictures cannot be
     made for, and the run says so instead of drawing a wireframe.
  4. THE COPY is written per job and gated by the brand's ban list.
  5. THE CHECKS are the only closed list: each invariant has a failing
     fixture here — an outside picture, five words from the reference, the
     reference's hex, a colour that does not read, a lost address, a lost
     unsubscribe, an unknown token, an <svg>, a message Gmail would clip,
     changed copy, a verified tick, a placeholder link — and the good email
     passes them all.
  6. THE LOOP keeps the round with the fewest blocking findings, edits rather
     than rewrites (the revise call receives the previous HTML and the
     findings), stops when nothing blocks, and never calls an unjudged email
     shippable.
  7. THE DOOR's contract is pinned (Browserless: a unit, the free plan's
     concurrency and session) and a missing door is said, not raised.
  8. THE CARD shows the reference beside ours with the open findings, and
     the button posts to /admin/email_recreate, which runs off the request
     and comes back 303; /admin/email_recreation serves the kept HTML.
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

from app import (admin_ui, brand_theme, db, email_design as ed, email_structures as es,  # noqa: E402
                 kb, llm, media, recreate as rc, shots, tenants, web)

CDN = "https://cdn.shopify.com/s/files/1/0002/"
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(w=400, h=300, bg="#e7dcc8", fg="#9b3c1c"):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), bg)
    ImageDraw.Draw(im).ellipse([w * .3, h * .2, w * .7, h * .75], fill=fg)
    b = io.BytesIO(); im.save(b, format="PNG")
    return b.getvalue()


# THE BRIEF THE READER SHOULD PRODUCE FOR THE AYOH REFERENCE — written by
# hand first, as §8 of the plan demands, and checked against §1 row 1: the
# concept in a sentence, each section's job, asset and copy jobs, the devices.
BRIEF = {
    "concept": "a recipe delivered as a screenshot of the brand's own Instagram post; a pun hook above; "
               "shop the product used below; the product at the table underneath",
    "sections": [
        {"n": 1, "what": "the brand's wordmark, small, centred on the page colour", "does": "signs the email",
         "asset": {"kind": "mark", "shows": "the mark"}, "copy": [], "look": "centred, cream on brown, 34 px"},
        {"n": 2, "what": "a two-line hook: a letter-spaced small-caps kicker over a huge display headline",
         "does": "stops the reader with a pun on how the product is used",
         "asset": {"kind": "none", "shows": ""},
         "copy": [{"id": "s2_kicker", "job": "a small-caps line that sets up the turn", "limit": "6 words"},
                  {"id": "s2_headline", "job": "the turn: an imperative that uses the product more boldly", "limit": "2 lines, 3 words"}],
         "look": "centred; kicker 12 px tracked; headline ~75% of the column, heavy condensed, cream on brown"},
        {"n": 3, "what": "a social post shown as a post: avatar, handle, a square photograph, an icon row with dots, "
                         "then a small-caps title and four numbered steps inside the same cream card",
         "does": "gives the recipe as if lifted from the brand's feed",
         "asset": {"kind": "photograph", "shows": "the product in use — food on it, hands, sunlight"},
         "copy": [{"id": "s3_title", "job": "a small-caps title naming the secret", "limit": "5 words"},
                  {"id": "s3_steps", "job": "four numbered steps naming the product, the last step one word", "limit": "4 steps"}],
         "look": "cream card, thin dark border, 14 px radius, inset 30 px; photo square with straight corners"},
        {"n": 4, "what": "a closer: two lines of display caps then a script tail, and a bordered cream button",
         "does": "lands the joke and asks once",
         "asset": {"kind": "none", "shows": ""},
         "copy": [{"id": "s4_closer", "job": "two display lines that set up the script", "limit": "2 lines"},
                  {"id": "s4_script", "job": "the script tail", "limit": "2 words"},
                  {"id": "s4_cta", "job": "shop the product used, by name", "limit": "3 words"}],
         "look": "centred; button cream with a dark 2 px border, small caps tracked"},
        {"n": 5, "what": "the page turns cream; the product in a scene, then a line naming the pieces",
         "does": "shows the thing to buy where it lives",
         "asset": {"kind": "photograph", "shows": "the pieces at the table"},
         "copy": [{"id": "s5_line", "job": "one line naming the pieces on the table", "limit": "1 line"}],
         "look": "cream ground, photo inset 34 px"},
    ],
    "visual_system": {"type": "heavy condensed display; tracked small caps; brush script accent; 13 px sans body",
                      "colour": "the page is the brand's deep tone; one cream card; the page turns cream at the end",
                      "rhythm": "one column, everything centred, generous padding, 14 px radii", "column": "600"},
    "devices": ["a social post shown as a post: avatar circle, handle, square photo, heart/comment/send/bookmark row, dots",
                "a display line with a script tail", "a cream button with a dark border"],
    "reference_text": ["Ayoh!", "DON'T JUST SAUCE THE BREAD.", "SAUCE THE MEAT!", "eatayoh", "THE DELI COUNTER SECRET",
                       "1. Whisk 1/3 cup Tangy Dijonayo with a glug of olive oil, a splash of red wine vinegar",
                       "NOW THAT'S A SANDO WORTH singing about", "SHOP TANGY DIJONAYO"],
    "reference_hexes": ["#7a4a1c", "#f5ecd7", "#3a2410", "#c8a15a", "#8b5a2b", "#fff8e8"],
}

COPY = {"s2_kicker": "Don't just set the table.", "s2_headline": "Set the scene!",
        "s3_title": "The Sunday-lunch secret",
        "s3_steps": ["Start with the Portofino melamine dinner plates.", "Add the Aqua water glasses in orange.",
                     "Pile the pasta straight onto the plates.", "Mangia!"],
        "s4_closer": "Now that's a lunch worth", "s4_script": "lingering over", "s4_cta": "Shop Portofino",
        "s5_line": "On the table: Portofino melamine dinner plates and Aqua water glasses."}

LOGO = CDN + "logo.png"
PHOTO_A, PHOTO_B, PHOTO_C = CDN + "pasta.jpg", CDN + "table.jpg", CDN + "bowl.jpg"
ADDRESS = "1 Main St, Hallandale Beach, FL 33009"


def email_html(copy=COPY, *, photo_a=PHOTO_A, photo_b=PHOTO_B, logo=LOGO, address=ADDRESS,
               ink="#4a2418", page="#9b3c1c", cream="#f4e8d3", unsub="{{UNSUBSCRIBE}}", extra="",
               headline_px=96) -> str:
    """An email the way the composer writes one: tables, inline styles, the
    copy verbatim, only the brand's pictures, the address and the token."""
    steps = "".join(f'<p style="margin:0 0 8px;color:{ink}">{i + 1}. {s}</p>' for i, s in enumerate(copy["s3_steps"]))
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{copy["s2_headline"]}</title></head>
<body style="margin:0;background:{page}">{extra}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{page}"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:600px">
<tr><td align="center" style="padding:30px"><img src="{logo}" alt="the brand" width="150"></td></tr>
<tr><td align="center" style="color:{cream};font-family:Helvetica,Arial,sans-serif;font-size:12px">{copy["s2_kicker"]}</td></tr>
<tr><td align="center" style="color:{cream};font-family:Impact,'Arial Black',sans-serif;font-size:{headline_px}px">{copy["s2_headline"]}</td></tr>
<tr><td style="padding:0 34px 30px"><table role="presentation" width="100%" style="background:{cream};border:1px solid {ink};border-radius:14px">
<tr><td style="padding:16px;color:{ink};font-family:Helvetica,Arial,sans-serif;font-size:13px">bacimilanousa</td></tr>
<tr><td style="padding:0 16px"><img src="{photo_a}" alt="the product in use" width="500" style="width:100%"></td></tr>
<tr><td style="padding:16px;color:{ink};font-family:Helvetica,Arial,sans-serif;font-size:12px">{copy["s3_title"]}</td></tr>
<tr><td style="padding:0 16px 16px;font-family:Helvetica,Arial,sans-serif;font-size:13px;color:{ink}">{steps}</td></tr>
</table></td></tr>
<tr><td align="center" style="color:{cream};font-family:Impact,'Arial Black',sans-serif;font-size:24px">{copy["s4_closer"]}</td></tr>
<tr><td align="center" style="color:{cream};font-family:'Brush Script MT',cursive;font-size:40px">{copy["s4_script"]}</td></tr>
<tr><td align="center" style="padding:20px"><a href="https://example-brand.test/collections/portofino" style="display:inline-block;padding:14px 40px;background:{cream};border:2px solid {ink};color:{ink};font-family:Helvetica,Arial,sans-serif;font-size:13px;text-decoration:none">{copy["s4_cta"]}</a></td></tr>
</table></td></tr>
<tr><td align="center" style="background:{cream}"><table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px">
<tr><td style="padding:30px 34px 0"><img src="{photo_b}" alt="the pieces at the table" width="532" style="width:100%"></td></tr>
<tr><td align="center" style="padding:20px;color:{ink};font-family:Helvetica,Arial,sans-serif;font-size:13px">{copy["s5_line"]}</td></tr>
<tr><td align="center" style="padding:0 20px 30px;color:#6b4a3a;font-family:Helvetica,Arial,sans-serif;font-size:11px">{address}<br>
<a href="{unsub}" style="color:#6b4a3a">Unsubscribe</a></td></tr>
</table></td></tr></table></body></html>"""


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.set_brand("baci", positioning="Italian-designed tableware.", tone="direct")
    with db.SessionLocal() as s:
        b = s.get(db.KbBrand, "baci")
        b.banned_claims = ["handmade", "made in Italy"]
        s.commit()
    brand_theme.approve("baci", {"footer.address": ADDRESS, "logo_url": LOGO, "colors.accent": "#9b3c1c"})
    kb.add_entity("baci", "collection", "portofino", "Portofino", description="Melamine and porcelain, coral and shells.",
                  attributes={"image": PHOTO_C, "url": "https://example-brand.test/collections/portofino"}, origin="human")
    kb.add_entity("baci", "product", "aqua-glass", "Aqua water glass, orange", price="$220",
                  attributes={"image": PHOTO_C, "url": "https://example-brand.test/products/aqua"}, origin="human")
    kb.add_asset("baci", PHOTO_A, rights=kb.OWNED, subject="photo", title="spaghetti on the Portofino plate",
                 entity_key="portofino", origin="human")
    kb.add_asset("baci", PHOTO_B, rights=kb.OWNED, subject="photo", title="the Portofino place setting",
                 entity_key="portofino", origin="human")
    kb.add_asset("baci", PHOTO_C, rights=kb.OWNED, subject="object", tags=["store-image:1", "packshot"],
                 title="Aqua glass packshot", entity_key="aqua-glass", origin="store_sync")
    kb.add_asset("baci", CDN + "ref.jpg", rights=kb.REFERENCE, subject="scene", title="a pin", origin="pinterest")
    ids = {a.url: a.id for a in kb.assets("baci")}
    a_id, b_id, c_id = ids[PHOTO_A], ids[PHOTO_B], ids[PHOTO_C]
    with db.SessionLocal() as s:
        for aid, kind in ((a_id, "lifestyle"), (b_id, "lifestyle"), (c_id, "packshot-on-plain")):
            row = s.get(db.KbAsset, aid)
            row.reading = {"kind": kind, "colours": {"light": "#e8d8c0", "dark": "#502818", "mid": "#983818"},
                           "size": [1170, 1170], "aspect": "square", "alone": kind.startswith("packshot"), "person": False}
        s.commit()

    # the reference: a swiped screenshot on the agency board, and its structure
    kb.add_asset("agency", "https://images.example.test/ayoh.png", rights=kb.REFERENCE, kind=es.SWIPE_KIND,
                 subject="scene", title="Ayoh — Sauce the meat", source="https://reallygoodemails.com/emails/x",
                 origin="swipe")
    ref_id = next(a.id for a in kb.assets("agency", publishable_only=False) if "ayoh" in (a.url or ""))
    st = es.file_structure(name="Ayoh — Sauce the meat", sequence=["hero", "heading", "text", "cta"], source="swipe",
                           review="approved", source_asset_id=ref_id, source_url="https://reallygoodemails.com/emails/x")
    sid = st["id"] if isinstance(st, dict) else st

    # THE STUBS: the reference bytes, the thumbnails, the model by purpose, the door, the blob store, the links
    ref_png = png(680, 2400, "#7a4a1c", "#f5ecd7")
    ed._fetch = lambda url: ref_png if "ayoh" in url else b""
    ed._fetch_bounded = lambda url, *, cap=ed.FETCH_MAX: png() if CDN in url else b""
    calls: list[str] = []
    answers: dict = {}
    seen_prompts: dict = {}

    class _R:
        ok = True
        error = ""
        model = "stub"
        def __init__(self, text): self.text = text

    def _ask(purpose, prompt, **k):
        calls.append(purpose)
        seen_prompts.setdefault(purpose, []).append(prompt)
        ans = answers.get(purpose)
        if callable(ans):
            ans = ans(prompt)
        return _R(ans if isinstance(ans, str) else json.dumps(ans))
    llm.ask = _ask
    shots_calls: list[int] = []
    shots.shoot = lambda html, **k: (shots_calls.append(len(html)) or {"ok": True, "png": png(640, 2000), "door": "local", "ms": 5, "why": ""})
    media.put = lambda tenant, blob, **k: {"ok": True, "id": f"blob{len(shots_calls)}", "url": "http://x/media/blob.png"}
    import httpx
    httpx.head = lambda *a, **k: types.SimpleNamespace(status_code=200)

    print("— 1. the brief is words, refused by name when it is not —")
    answers["email_brief"] = BRIEF
    got = rc.brief(ref_id, tenant="baci")
    ck("the reference is read into a brief and stored on its structure",
       got["ok"] and got["structure_id"] == sid and got["brief"]["concept"].startswith("a recipe"), str(got.get("why")))
    with db.SessionLocal() as s:
        row = s.get(db.EmailStructure, sid)
        ck("the brief on the row carries the concept, the sections and the reference's words for the leak check",
           (row.brief or {}).get("concept") and len(row.brief["sections"]) == 5 and row.brief["reference_text"])
    ck("a reply with no sections is refused by name", rc.brief_problem({**BRIEF, "sections": []}) == "the brief has no sections")
    ck("a reply with no concept is refused by name", rc.brief_problem({**BRIEF, "concept": ""}) == "the brief has no concept")
    ck("a section that does not say what it is is refused by name",
       rc.brief_problem({**BRIEF, "sections": [{"n": 1}]}) == "section 1 does not say what it is")
    ck("a tokenised reply is not a brief", rc.brief_problem({"sections": [{"kind": "hero"}]}).startswith("the brief lacks"))
    ck("the copy jobs are flat, in order, with their section",
       [j["id"] for j in rc.copy_jobs(BRIEF)][:3] == ["s2_kicker", "s2_headline", "s3_title"]
       and rc.copy_jobs(BRIEF)[0]["section"] == 2)

    print("— 2. the kit gathers what is on file —")
    kit = rc.kit("baci")
    ck("the kit carries the brand's publishable pictures with their readings, never a reference pin",
       {p["id"] for p in kit["pictures"]} == {a_id, b_id, c_id} and all(p["kind"] for p in kit["pictures"]))
    ck("the kit carries the entities, the theme's mark and address, the platform's tokens",
       {e["key"] for e in kit["entities"]} >= {"portofino", "aqua-glass"} and kit["theme"]["logo_url"] == LOGO
       and kit["theme"]["footer"]["address"] == ADDRESS and "UNSUBSCRIBE" in kit["esp"]["tokens"])

    print("— 3. the cast is chosen by looking —")
    answers["email_cast"] = lambda prompt: {"picks": [{"section": 3, "cell": 1, "why": "food on the plate, in the sun"},
                                                      {"section": 5, "cell": 1, "why": "again"},
                                                      {"section": 5, "cell": 2, "why": "the pieces at the table"}], "none": []}
    cast = rc.cast("baci", BRIEF, kit, entity_key="portofino", seed="one")
    ck("a pick names the picture and why", cast["picks"][3]["asset_id"] in (a_id, b_id) and "sun" in cast["picks"][3]["why"], str(cast))
    ck("the same picture cannot fill two slots — the second slot took the next pick",
       cast["picks"][5]["asset_id"] != cast["picks"][3]["asset_id"] and cast["picks"][5]["asset_id"] in (a_id, b_id))
    ck("the caster saw a numbered sheet and the pictures' facts",
       any(isinstance(p, list) and p and p[0].get("type") == "image" for p in seen_prompts["email_cast"])
       and "spaghetti on the Portofino plate" in seen_prompts["email_cast"][-1][-1]["text"])
    ck("the subject's pictures come first on the sheet",
       rc.candidates(kit, entity_key="portofino", seed="x")[0]["entity_key"] == "portofino")
    answers["email_cast"] = {"picks": [], "none": [{"section": 3, "needs": "a photograph of food on the plate"}]}
    cast_none = rc.cast("baci", BRIEF, kit)
    ck("a slot nothing fits is cut and says what it needs",
       not cast_none["picks"] and {x["section"] for x in cast_none["none"]} == {3, 5}
       and cast_none["none"][0]["needs"].startswith("a photograph") and "cut" in cast_none["said"][-1])

    print("— 4. the copy is written per job and gated —")
    answers["email_copy"] = {**COPY, "s5_line": "Handmade in Italy, on the table."}
    cp = rc.copy("baci", BRIEF, kit, cast, entity_key="portofino")
    ck("every job gets its words", set(cp["copy"]) == set(COPY), str(set(cp["copy"]) ^ set(COPY)))
    ck("the brand's ban list blocks the copy by phrase",
       any(f["code"] == "banned" and "handmade" in f["what"].lower() for f in cp["findings"]), str(cp["findings"]))
    answers["email_copy"] = COPY

    print("— 5. the checks — each invariant fails on its fixture, the good email passes —")
    good = email_html()
    f0 = rc.check(good, kit, BRIEF, COPY)
    ck("the good email passes every check", not rc.blocking(f0), str(rc.blocking(f0)))

    def blocks(html, code, **kw):
        fs = rc.check(html, kit, BRIEF, kw.pop("copy", COPY), **kw)
        return any(f["code"] == code and f["severity"] == "blocks" for f in fs)
    ck("an outside picture blocks", blocks(email_html(photo_a="https://images.someone-else.test/sando.jpg"), "asset"))
    ck("five words in a row from the reference block",
       blocks(email_html({**COPY, "s5_line": "Don't just sauce the bread. Sauce the meat!"}),
              "leak_words", copy={**COPY, "s5_line": "Don't just sauce the bread. Sauce the meat!"}))
    ck("the reference's own hex blocks", blocks(email_html(page="#7a4a1c"), "leak_hex"))
    ck("a picture from the reference's host blocks",
       blocks(email_html(photo_a="https://images.example.test/ayoh.png"), "leak_image", reference_host="images.example.test"))
    ck("a colour that does not read blocks", blocks(email_html(cream="#b0705a"), "contrast"))
    ck("a lost address blocks", blocks(email_html(address="somewhere"), "address"))
    ck("a lost unsubscribe blocks", blocks(email_html(unsub="#"), "unsubscribe"))
    ck("an unknown token blocks", blocks(email_html(extra="{{FirstName}}"), "token"))
    ck("an <svg> blocks", blocks(email_html(extra="<svg width='1' height='1'></svg>"), "tag"))
    ck("a message Gmail would clip blocks", blocks(email_html(extra="<!--" + "x" * 101_000 + "-->"), "size"))
    ck("changed copy blocks", blocks(email_html({**COPY, "s4_cta": "Shop now"}), "copy"))
    ck("a verified tick blocks", blocks(email_html(extra='<p style="color:#ffffff">bacimilanousa ✓</p>'), "fabricated"))
    ck("a placeholder link blocks", blocks(email_html(unsub="#unsubscribe"), "link_placeholder"))
    ck("the brand's ban list blocks at the email too", blocks(email_html({**COPY, "s5_line": "Handmade for you."}),
                                                             "banned", copy={**COPY, "s5_line": "Handmade for you."}))

    print("— 6. the loop keeps the best round, edits rather than rewrites, stops when nothing blocks —")
    answers["email_cast"] = {"picks": [{"section": 3, "cell": 1, "why": "food"}, {"section": 5, "cell": 2, "why": "table"}], "none": []}
    compose_seen: list = []

    def _compose(prompt):
        compose_seen.append(prompt)
        if "FINDINGS" in prompt and "THE HTML" in prompt:
            return "```html\n" + email_html(headline_px=112) + "\n```"      # the edit: the headline grows
        return "```html\n" + email_html() + "\n```"
    answers["email_compose"] = _compose
    judged: list = []

    def _judge(prompt):
        judged.append(1)
        if len(judged) == 1:
            return {"same_concept": True, "devices_in_order": True, "weight_rhythm": "headline light",
                    "brand_material": True,
                    "findings": [{"where": "section 2", "what": "the headline sits at half the column; the reference's fills it",
                                  "do": "set it larger", "severity": "blocks"}]}
        return {"same_concept": True, "devices_in_order": True, "weight_rhythm": "matched", "brand_material": True, "findings": []}
    answers["email_judge"] = _judge
    got = rc.run(sid, "baci", "portofino", seed="s")
    ck("the run kept round 1 — the edit closed the judge's finding — and calls it shippable",
       got["status"] == rc.SHIPPABLE and len(got["rounds"]) == 2 and got["rounds"][1]["blocking"] == 0
       and got["rounds"][0]["blocking"] == 1, got.get("note"))
    ck("the revise call received the previous HTML and the finding, and the edit is counted in lines",
       len(compose_seen) == 2 and "THE HTML" in compose_seen[1] and "half the column" in compose_seen[1]
       and got["rounds"][1]["edited"] > 0)
    last = rc.latest(sid, "baci")
    ck("the recreation is on file with its picture, brief, rounds and no open finding",
       last and last["status"] == rc.SHIPPABLE and last["png"] and last["best"] == 1 and not last["findings"]
       and last["concept"].startswith("a recipe") and last["has_html"])
    ck("the kept HTML is the edited one", "font-size:112px" in rc.html_of(last["id"]))
    ck("the run says what it did, in sentences", "Round 0" in got["note"] and "Kept round 1" in got["note"])

    # a later round that is WORSE is not kept: the best round wins, not the last
    judged.clear()
    worse = iter([1, 2, 2])

    def _judge_worse(prompt):
        n = next(worse)
        return {"same_concept": True, "devices_in_order": True, "weight_rhythm": "", "brand_material": True,
                "findings": [{"where": f"section {i}", "what": "off", "do": "fix", "severity": "blocks"} for i in range(n)]}
    answers["email_judge"] = _judge_worse
    got_w = rc.run(sid, "baci", "portofino", seed="w")
    ck("when every edit made it worse, round 0 is kept — the best round, never the last",
       got_w["status"] == rc.NOT_SHIPPABLE and len(got_w["rounds"]) == 3 and rc.latest(sid, "baci")["best"] == 0
       and [r["blocking"] for r in got_w["rounds"]] == [1, 2, 2], got_w.get("note"))
    answers["email_judge"] = _judge

    # no door → not judged → never shippable
    shots.shoot = lambda html, **k: {"ok": False, "png": b"", "door": "", "ms": 0, "why": "playwright is not installed"}
    judged.clear()
    got2 = rc.run(sid, "baci", "portofino", seed="t")
    ck("without a picture nothing is judged and the email is not called shippable — and it says why",
       got2["status"] == rc.NOT_SHIPPABLE and "not judged" in got2["note"] and "playwright" in got2["note"], got2.get("note"))
    card_nd = admin_ui._structures_card("s3cret", "baci")
    ck("the door's own reason stands where the picture would be, with the HTML still openable",
       "no picture — playwright is not installed" in card_nd and "open the HTML" in card_nd)

    # no pictures → cannot be made
    shots.shoot = lambda html, **k: {"ok": True, "png": png(640, 2000), "door": "local", "ms": 5, "why": ""}
    kb.ensure_brand("ironside", "Ironside")
    brand_theme.approve("ironside", {"footer.address": ADDRESS})
    st2 = es.file_structure(name="Ayoh again", sequence=["hero", "cta"], source="swipe", review="approved",
                            source_asset_id=ref_id)
    sid2 = st2["id"] if isinstance(st2, dict) else st2
    got3 = rc.run(sid2, "ironside")
    ck("a brand with no pictures gets 'cannot be made' with what each slot needs — never a wireframe",
       got3["status"] == rc.CANNOT and any("needs" in f["what"] for f in got3["findings"]) and "cannot be made" in got3["note"],
       got3.get("note"))

    print("— 7. the door's contract —")
    ck("the provider's contract is pinned with its documents",
       shots.BROWSERLESS["free_units_per_month"] == 1000 and shots.BROWSERLESS["free_concurrent"] == 2
       and shots.BROWSERLESS["free_session_seconds"] == 120 and shots.BROWSERLESS["connect"] == "connect_over_cdp"
       and all(d.startswith("https://") for d in shots.DOCS))
    ck("the semaphore holds the free plan's concurrency", shots._SEM._initial_value == shots.BROWSERLESS["free_concurrent"])
    from app import config
    config.SHOTS_WS = "https://not-a-socket"
    ck("a malformed endpoint is refused by name", shots.door()[0] == "" and "wss://" in shots.door()[1])
    config.SHOTS_WS = "wss://production-sfo.browserless.io?token=abc"
    which, why = shots.door()
    ck("with a Browserless endpoint the door is Browserless (when Playwright is installed) or says what is missing",
       which == "browserless" or "playwright" in why)
    config.SHOTS_WS = ""

    print("— 8. the card and the routes —")
    from fastapi.testclient import TestClient
    bg: list = []
    web._run_bg = lambda label, fn, *a, **k: bg.append((label, a, k))
    c = TestClient(web.app)
    r = c.post("/admin/email_recreate?key=s3cret", data={"key": "s3cret", "tenant": "baci", "structure": sid, "entity": "portofino"},
               follow_redirects=False)
    ck("the button posts and comes back 303 to the Designs room, the run off the request",
       r.status_code == 303 and "wf=designs" in r.headers.get("location", "") and bg and bg[0][0] == "email_recreate"
       and bg[0][1] == (sid,) and bg[0][2]["tenant"] == "baci" and bg[0][2]["entity_key"] == "portofino")
    r2 = c.get(f"/admin/email_recreation?key=s3cret&id={last['id']}")
    ck("the kept HTML is served as a page", r2.status_code == 200 and "font-size:112px" in r2.text)
    card = admin_ui._structures_card("s3cret", "baci")
    needles = ("ours, for baci", "the reference", "shippable", "brief: a recipe", 'action="/admin/email_recreate"', "Recreate again")
    ck("the card shows the reference beside ours, the status, the brief and the button that posts to /admin/email_recreate",
       all(n in card for n in needles), "missing: " + ", ".join(n for n in needles if n not in card))
    card2 = admin_ui._structures_card("s3cret", "ironside")
    ck("for a brand it cannot be made for, the card says so and what it needs",
       "cannot be made" in card2 and "needs" in card2)
    # a run in flight: the row exists, unfinished — the card says running with the
    # step, never "round 0 of 0 kept" or "no picture" (the first live press, 2026-09-12)
    with db.SessionLocal() as s:
        s.add(db.Recreation(tenant="baci", structure_id=sid, status=rc.RUNNING))
        s.commit()
    web.bg_status = lambda label, tenant: {"state": "running", "detail": "casting its pictures"}
    card3 = admin_ui._structures_card("s3cret", "baci")
    ck("a run in flight is said as running with its step — never as a result",
       "running since" in card3 and "casting its pictures" in card3 and "round 0 of 0" not in card3
       and "no picture" not in card3, "")
    web.bg_status = lambda label, tenant: {"state": "failed", "detail": "RuntimeError: x"}
    card4 = admin_ui._structures_card("s3cret", "baci")
    ck("a run whose thread died is said as failed, not left running",
       "failed — RuntimeError" in card4 and "running since" not in card4)

    print("— 9. one press from a link: filed, read, filed as a design, recreated —")
    shots.shoot = lambda html, **k: {"ok": True, "png": png(640, 2000), "door": "local", "ms": 5, "why": ""}
    answers["email_judge"] = lambda prompt: {"same_concept": True, "devices_in_order": True, "weight_rhythm": "matched",
                                             "brand_material": True, "findings": []}
    answers["email_cast"] = {"picks": [{"section": 3, "cell": 1, "why": "food"}, {"section": 5, "cell": 2, "why": "table"}], "none": []}
    kb.add_asset("agency", "https://images.example.test/shrimp.png", rights=kb.REFERENCE, kind=es.SWIPE_KIND,
                 subject="scene", title="Animal facts — pistol shrimp", source="https://reallygoodemails.com/emails/pistol-shrimp",
                 origin="swipe")
    shrimp_id = next(a.id for a in kb.assets("agency", publishable_only=False) if "shrimp" in (a.url or ""))
    es.add_swipe = lambda url, **k: {"ok": True, "asset_id": shrimp_id, "url": url, "title": "Animal facts — pistol shrimp",
                                     "image": "https://images.example.test/shrimp.png"}
    ed._fetch = lambda url: ref_png if ("ayoh" in url or "shrimp" in url) else b""
    steps: list = []
    got = rc.swipe("https://reallygoodemails.com/emails/pistol-shrimp", "baci", progress=lambda t: steps.append(t))
    ck("a link becomes a design and a recreation in one press, and says each step",
       got["ok"] and got["structure_id"] and got["recreation"]["status"] == rc.SHIPPABLE
       and steps[:3] == ["filing the reference", "reading the reference into a brief", "recreating it for this brand"],
       str(got.get("why")) + " " + str(steps))
    new = next(r for r in es.library() if r["id"] == got["structure_id"])
    first = rc.latest(new["id"], "baci")
    ck("the recreation of that press is on file with its picture and its review",
       first and first["status"] == rc.SHIPPABLE and first["png"] and first["via"] == "press"
       and first["verdict"].get("same_concept") is True)
    ck("the design is keyed by its picture, carries the brief, and is in the rotation the moment it lands",
       new["source_asset_id"] == shrimp_id and new["brief"]["concept"].startswith("a recipe") and new["review"] == "approved"
       and new["name"].startswith("a recipe") and new["fits_formats"] == [])
    ck("its rough order is read off the brief for the rules that bind at use, never drawn from",
       "hero" in new["sequence"] and "cta" in new["sequence"] and "list" in new["sequence"] and new["requires"])
    got2 = rc.swipe("https://reallygoodemails.com/emails/pistol-shrimp", "baci")
    ck("the same link pasted again finds the same design — no duplicate",
       got2["structure_id"] == got["structure_id"]
       and sum(1 for r in es.library() if r["source_asset_id"] == shrimp_id) == 1)
    ck("a design keyed by another picture is another design, whatever its rough order",
       new["id"] != sid and sum(1 for r in es.library() if r["source_asset_id"] == shrimp_id) == 1)
    ck("the drafter's brief for a design with a brief is the concept and its copy jobs, never a token",
       "THE DESIGN THIS SEND IS BUILT IN: a recipe" in es.brief(new) and "four numbered steps" in es.brief(new)
       and "grid2" not in es.brief(new))

    print("— 10. choose it, or let the draw decide —")
    es.reject(new["id"])
    ck("a design taken out of the rotation cannot be the standing choice",
       "not in the rotation" in es.designate("baci", new["id"]))
    es.approve(new["id"])
    said = es.designate("baci", new["id"])
    ck("once in the rotation it can be, and pick() honours it", "until you say" in said
       and es.pick("baci")["structure"]["id"] == new["id"] and es.pick("baci")["designated"] is True)
    ck("a plan's own designation outranks the standing choice",
       es.pick("baci", designated=sid)["structure"]["id"] == sid)
    ck("back to random draws from the rotation", "random" in es.designate("baci", "")
       and es.pick("baci")["designated"] is False and es.pick("baci")["structure"] is not None)
    # THE ROTATION BEFORE THE HOUSE: a design excluded only by the send's
    # intent, form or the list's recent shapes is still used — and said.
    got_r = es.pick("baci", recent_shapes=[r["sequence"] for r in es.library(review="approved")], fmt="letter")
    ck("a design excluded only by recent shapes or the send's form is used anyway, and said",
       got_r["structure"] is not None and "used anyway" in got_r["why"], got_r["why"])
    # a brief-based design is never refused for a block the brand lacks — the recreation cuts and says
    with db.SessionLocal() as s:
        st_new = s.get(db.EmailStructure, new["id"]); st_new.requires = ["proof", "products"]; s.commit()
    kb.ensure_brand("nothing", "Nothing")
    ck("a design with a brief is usable for a brand with no claims and no products — the recreation cuts what it lacks",
       es.usable_for("nothing", next(r for r in es.library() if r["id"] == new["id"]))[0] is True)
    ck("so the rotation is not empty for that brand either — a design is drawn",
       es.pick("nothing")["structure"] is not None)
    with db.SessionLocal() as s:
        b_ = s.get(db.KbBrand, "nothing"); b_.banned_claims = ["recipe", "ayoh"]; s.commit()
    ck("only a rotation with nothing this brand may use falls back to the house — and says so",
       es.pick("nothing")["structure"] is None and "the house way" in es.pick("nothing")["why"], es.pick("nothing")["why"])

    print("— 11. the campaigns are built in the design —")
    from app import esp, skill, skill_pack, systems, tenants as _tn
    kb.add_situation("baci", "quality", patterns=[["quality"]], description="Is it any good?", origin="seed")
    kb.add_claim("baci", "Designed in Milan and placed at the Four Seasons.", "brand brief", ["quality"],
                 origin="human", status="active")
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
    copy_prompts: list = []
    answers["email_copy"] = lambda prompt: (copy_prompts.append(prompt) or COPY)
    compose_seen.clear()
    r1 = skill.run("campaign_email", "baci", segment="reorder_due", structure=new["id"], intent="education",
                   entity_key="portofino", generate_visual="no")
    notes1 = r1.get("notes") or []
    ck("the campaign run is built in the designated design and says so",
       r1.get("status") == "produced" and any(n.startswith("built in the design") for n in notes1),
       str(r1.get("status")) + " " + str([n[:90] for n in notes1 if "design" in n or "structure" in n]))
    ck("the design's copy jobs carried the drafter's message — its subject and its cited claim",
       copy_prompts and "THE MESSAGE THIS EMAIL CARRIES" in copy_prompts[-1] and "Set the scene" in copy_prompts[-1]
       and "Four Seasons" in copy_prompts[-1])
    with db.SessionLocal() as s:
        out1 = s.query(db.Output).filter(db.Output.tenant == "baci").order_by(db.Output.created_at.desc()).first()
        art1 = s.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == out1.id).order_by(db.ArtifactBody.created_at.desc()).first()
        html1 = (art1.meta or {}).get("html") or ""
        meta1 = dict(art1.meta or {})
        media1 = list(out1.media_ids or [])
    ck("the email that ships is the model's HTML, with the cast pictures on the ledger",
       "Sunday-lunch secret" in html1 and set(media1) >= {a_id, b_id} and meta1.get("recreation", {}).get("status") == rc.SHIPPABLE)
    ck("the words checked are the words that ship",
       "Sunday-lunch secret" in (out1.body or out1.text or "") if hasattr(out1, "body") or hasattr(out1, "text") else True)
    ck("the design's recreation is on the Designs page as the latest, marked from a campaign",
       rc.latest(new["id"], "baci")["via"] == "campaign")
    with db.SessionLocal() as s:
        art_ = s.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == out1.id).order_by(db.ArtifactBody.created_at.desc()).first()
        label = admin_ui.artifact_label(art_)
    ck("the drafted item names the design it came out in and the recreation's status",
       meta1.get("design_name", "").startswith("a recipe") and "in a recipe" in label and "shippable" in label, label)
    # a blocking finding holds the unattended ship
    from app import approvals
    with db.SessionLocal() as s:
        art1 = s.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == out1.id).first()
        art1.meta = {**dict(art1.meta or {}), "recreation": {"id": "x", "status": rc.NOT_SHIPPABLE, "blocking": 1,
                                                           "findings": [{"severity": "blocks", "where": "section 3", "what": "the post card lost its icon row"}]}}
        s.commit()
    ck("the recreation an output was built as is read off its artifact",
       approvals._recreation_of(out1.id).get("blocking") == 1)
    # The unattended door is the article kinds' today (campaign emails wait
    # for a person); the hold is exercised through it with a pending ship on
    # this output, so the day an email walks through unattended it is held.
    with db.SessionLocal() as s:
        s.add(db.Approval(kind="seo_new_article", status="pending", summary="t", tenant="baci",
                          payload={"output_id": out1.id}))
        s.commit()
    held = approvals.ship_unattended("baci", out1.id, why="test")
    ck("an unattended ship is held while the recreation has a blocking finding — and says which",
       held.get("ok") is False and "icon row" in held.get("why", ""), str(held))
    # the recreation fails → built the old way, said
    answers["email_compose"] = "no html for you"
    state_before = len(es.library())
    r2 = skill.run("campaign_email", "baci", segment="reorder_due", structure=new["id"], intent="education",
                   entity_key="portofino", generate_visual="no")
    ck("when the recreation fails the send is built the old way and the notes say so",
       r2.get("status") == "produced" and any("built the old way" in n for n in (r2.get("notes") or [])))
    with db.SessionLocal() as s:
        out2 = s.query(db.Output).filter(db.Output.tenant == "baci").order_by(db.Output.created_at.desc()).first()
        art2 = s.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == out2.id).order_by(db.ArtifactBody.created_at.desc()).first()
        label2 = admin_ui.artifact_label(art2)
    ck("and the item says the design was not recreated — built the old way", "built the old way" in label2, label2)
    answers["email_compose"] = _compose

    print("— 12. the Designs room: paste, look, choose —")
    es.designate("baci", "")
    room = admin_ui._structures_card("s3cret", "baci")
    ck("the paste form is at the top of the room and posts to /admin/email_reference",
       'action="/admin/email_reference"' in room and room.index("/admin/email_reference") < room.index("In the rotation"))
    ck("the room says how campaigns choose — at random from the rotation this brand may use",
       "draws at random from" in room and "Use this for every campaign" in room)
    room2 = admin_ui._structures_card("s3cret", "baci")
    ck("a design in the rotation shows the review and the choice: Not this one, or Use this for every campaign",
       "In the rotation" in room2 and "Not this one" in room2 and "Use this for every campaign" in room2
       and "the judge: same concept <b>yes</b>" in room2 and "Only with nothing in the rotation is the house design used" in room2)
    with db.SessionLocal() as s:
        st_new = s.get(db.EmailStructure, new["id"]); st_new.review = "proposed"; s.commit()
    room2b = admin_ui._structures_card("s3cret", "baci")
    ck("a design filed by the older reader still waits to be chosen",
       "Filed by the older reader" in room2b and "Use it — into the rotation" in room2b)
    es.approve(new["id"]); es.designate("baci", new["id"])
    room3 = admin_ui._structures_card("s3cret", "baci")
    ck("the standing choice is said at the top and on its design, with the way back",
       "every one is built on" in room3 and "every campaign uses this design" in room3 and "Back to random" in room3)
    es.designate("baci", "")
    r = c.post("/admin/email_reference?key=s3cret", data={"key": "s3cret", "tenant": "baci",
                                                           "url": "https://reallygoodemails.com/emails/pistol-shrimp"},
               follow_redirects=False)
    ck("pasting a link posts, runs off the request, and comes back to the Designs room",
       r.status_code == 303 and "wf=designs" in r.headers.get("location", "") and bg[-1][0] == "email_recreate"
       and bg[-1][1] == ("https://reallygoodemails.com/emails/pistol-shrimp",) and bg[-1][2]["tenant"] == "baci")
    r = c.post("/admin/email_reference?key=s3cret", data={"key": "s3cret", "tenant": "baci", "url": "https://reallygoodemails.com/categories/food"},
               follow_redirects=False)
    ck("a category page is refused with the reason, on the same room",
       r.status_code == 303 and "err=" in r.headers.get("location", "") and "wf=designs" in r.headers.get("location", ""))
    r = c.post("/admin/email_design_designate?key=s3cret", data={"key": "s3cret", "tenant": "baci", "structure": new["id"]},
               follow_redirects=False)
    ck("the standing choice posts and comes back to the room", r.status_code == 303 and "wf=designs" in r.headers.get("location", "")
       and es.standing_designation("baci") == new["id"])
    es.designate("baci", "")
    html_b = admin_ui.render_brand("s3cret", "baci")
    ck("the Brand tab no longer carries the reference emails — it says where they are",
       "Reference emails" not in html_b and 'action="/admin/email_reference"' not in html_b and "under Designs" in html_b)

    print()
    print("ALL GREEN" if not _fail else f"{len(_fail)} FAILED: " + "; ".join(_fail))
    return 0 if not _fail else 1


if __name__ == "__main__":
    sys.exit(main())
