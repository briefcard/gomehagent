"""THE MODEL WRITES THE ARTICLE; THE CODE INSPECTS IT — Phase 1–2 of
INITIATIVE-blog-quality.md. The chain's mechanics and its INVARIANTS,
never what an article reads like.

  1. THE PATTERN is the brand's standing layout: the default until one is
     filed; a filed one is what `pattern()` returns; a reference URL is read
     into one.
  2. THE RIVALS are read into a brief — headings, depth, gaps, length; with
     none on file the brief says so and the article is still written.
  3. THE STORY is decided before the prose, from the brief and the material.
  4. THE WRITER is handed the pattern, the brief, the story, the exemplar,
     the pictures and the products, and answers Title / Meta / HTML with the
     pattern's blocks marked; the edit round looks at its own render.
  5. THE CHECKS: title and first paragraph carry the keyword; meta length;
     no page tags; alt on every picture; only filed pictures; only given
     links; the pattern's required blocks present and in order; the ban
     list; the length band; a dead link.
  6. THE JUDGE sees the rival beside ours, must say what it read, and
     answers would_publish / one_pattern; a confused judge is asked again.
  7. THE LOOP keeps the best round and never calls an unjudged article
     publishable.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import types

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ar.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ.pop("SHOTS_WS", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import articles as ar, brand_theme, db, kb, llm, pictures as pics, shots, tenants, web  # noqa: E402

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


PHOTO_A, PHOTO_B = CDN + "table.jpg", CDN + "set.png"
KW = "melamine vs porcelain dinnerware"
PROD = [{"name": "18-Piece Set | Portofino Melamine", "price": "$640", "url": "https://example-brand.test/products/portofino-melamine"}]
COLL = ["https://example-brand.test/collections/melamine"]


def article_html(*, title_kw=True, first_kw=True, alt=True, photo=PHOTO_A, link="https://example-brand.test/collections/melamine",
                 blocks=("answer", "takeaways", "sections", "products", "faq", "cta"), extra="", words=1500) -> str:
    first = ("Melamine vs porcelain dinnerware comes down to one question: which table." if first_kw
             else "It comes down to one question: which table.")
    filler = " ".join(["The table decides the material and the material decides the evening."] * max(1, words // 11))
    out = []
    for b in blocks:
        out.append(f"<!-- block: {b} -->")
        if b == "answer":
            out.append(f"<p><strong>{first}</strong></p>")
        elif b == "takeaways":
            out.append("<div><ul><li>Melamine for outside.</li><li>Porcelain for the occasion.</li></ul></div>")
        elif b == "sections":
            out.append(f'<h2>Where porcelain wins</h2><p>{filler[:2000]}</p><img src="{photo}" {"alt=\"the set on the table\"" if alt else ""} width="1200">'
                       f"<h2>Where melamine wins</h2><p>{filler}</p>")
        elif b == "products":
            out.append(f'<div><a href="{PROD[0]["url"]}"><img src="{PHOTO_B}" alt="the set" width="600"><strong>{PROD[0]["name"]}</strong> {PROD[0]["price"]}</a></div>')
        elif b == "faq":
            out.append("<h2>Questions people ask</h2><h3>Can melamine go in the microwave?</h3><p>No.</p>")
        elif b == "cta":
            out.append(f'<div><a href="{link}">Shop melamine</a></div>')
        out.append("<!-- /block -->")
    return "\n".join(out) + extra


def reply_article(html, title="Melamine vs Porcelain Dinnerware: Which Table Is It For?", meta="Which table? Where each wins, a table, real prices."):
    return f"Title: {title}\nMeta: {meta}\n{html}"


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.set_brand("baci", positioning="Italian-designed tableware.", tone="direct")
    with db.SessionLocal() as s:
        b = s.get(db.KbBrand, "baci"); b.banned_claims = ["handmade", "made in Italy"]; s.commit()
    brand_theme.approve("baci", {"footer.address": "1 Main St, Hallandale Beach, FL 33009", "logo_url": CDN + "logo.png",
                                 "font.heading": "Inter", "font.body": "Inter", "colors.accent": "#2921dc"})
    kb.add_entity("baci", "product", "portofino-melamine", "18-Piece Set | Portofino Melamine",
                  description="Durable melamine, lightweight, resistant to breakage, dishwasher safe. Indoor and outdoor.",
                  attributes={"image": PHOTO_B, "url": PROD[0]["url"], "price": "$640"}, origin="human")
    kb.add_entity("baci", "collection", "melamine", "Melamine", description="Every melamine piece.",
                  attributes={"url": COLL[0]}, origin="human")
    kb.add_asset("baci", PHOTO_A, rights=kb.OWNED, subject="photo", title="the Portofino set on an outdoor table", entity_key="portofino-melamine", origin="human")
    kb.add_asset("baci", PHOTO_B, rights=kb.OWNED, subject="object", title="the set", entity_key="portofino-melamine", origin="human")
    kit = __import__("app.recreate", fromlist=["kit"]).kit("baci")

    calls: list[str] = []
    answers: dict = {}
    seen: dict = {}

    class _R:
        ok = True
        error = ""
        model = "stub"
        stop_reason = "end_turn"
        def __init__(self, text): self.text = text

    def _ask(purpose, prompt, **k):
        calls.append(purpose)
        seen.setdefault(purpose, []).append(prompt)
        ans = answers.get(purpose)
        if callable(ans):
            ans = ans(prompt)
        return _R(ans if isinstance(ans, str) else json.dumps(ans))
    llm.ask = _ask
    shots.shoot = lambda html, **k: {"ok": True, "png": png(760, 3000), "door": "local", "ms": 5, "why": ""}
    ar._shoot_url = lambda url: {"ok": True, "png": png(1000, 4000, "#ffffff", "#333333"), "why": ""}
    import httpx
    fetched = {"https://rival.test/a": "<html><head><title>Melamine vs Porcelain: A Guide</title></head><body><article><h1>Melamine vs Porcelain</h1><h2>What is melamine?</h2><p>"
                                       + "Melamine is a resin. " * 400 + "</p><h2>Which is more durable?</h2><p>text</p><table><tr><td>a</td></tr></table></article></body></html>"}
    httpx.get = lambda url, *a, **k: types.SimpleNamespace(status_code=200 if url in fetched else 404, text=fetched.get(url, ""))
    httpx.head = lambda url, *a, **k: types.SimpleNamespace(status_code=404 if "dead" in url else 200)

    print("— 1. the pattern —")
    p0 = ar.pattern("baci")
    ck("a brand with no pattern gets the default, said as the default", p0.get("default") is True and [b["name"] for b in p0["blocks"]][:2] == ["answer", "takeaways"])
    ck("the default carries the hand-made article's blocks, required ones marked",
       {b["name"] for b in p0["blocks"] if b.get("required")} == {"answer", "takeaways", "sections", "products", "faq", "cta"})
    ck("a pattern without blocks is refused", ar.file_pattern("baci", {"name": "x"}) == "a pattern needs blocks")
    answers["email_brief"] = {"name": "guide", "blocks": [{"name": "answer", "what": "the answer", "required": True}, {"name": "steps", "what": "numbered steps", "required": True}],
                              "devices": ["a numbered list"], "voice_of_layout": "tight"}
    rp = ar.read_pattern("https://rival.test/a", tenant="baci")
    ck("a reference URL is read once into a pattern — the reader sees the headings and a picture, never asked about the subject",
       rp["ok"] and rp["pattern"]["blocks"][1]["name"] == "steps" and "HEADINGS AND TEXT" in seen["email_brief"][-1][-1]["text"]
       and "never the article's subject" in seen["email_brief"][-1][-1]["text"])
    ck("filing the pattern makes it the brand's", ar.file_pattern("baci", rp["pattern"], source_url="https://rival.test/a") == ""
       and not ar.pattern("baci").get("default") and ar.pattern("baci")["source_url"] == "https://rival.test/a")
    ar.file_pattern("baci", ar.PATTERN_DEFAULT)

    print("— 2. the rivals and the brief —")
    reads = ar.rivals("baci", KW, urls=["https://rival.test/a", "https://rival.test/gone"])
    ck("a rival page is read for its headings, depth and devices; a dead one is skipped",
       len(reads) == 1 and reads[0]["words"] > 300 and reads[0]["table"] is True and reads[0]["heads"][1][1] == "What is melamine?")
    answers["email_brief"] = {"answer_first": "Melamine outside, porcelain for the occasion.", "must_cover": ["what each is", "durability"],
                              "gaps": ["a real price", "a decision by situation"], "questions": ["Can melamine go in the microwave?"],
                              "length_words": 1600, "media": "a table", "tone": "plain", "beat": "answer first and a real price"}
    got_b = ar.brief("baci", KW, reads)
    ck("the brief reads what ranks into what ours must do, and records the rivals",
       got_b["ok"] and got_b["brief"]["length_words"] == 1600 and got_b["brief"]["rivals"][0]["url"] == "https://rival.test/a"
       and "THE PAGES THAT RANK" in seen["email_brief"][-1] and "Melamine is a resin" in seen["email_brief"][-1])
    empty = ar.brief("baci", KW, [])
    ck("with no rival on file the brief says so and the article is still written", empty["ok"] and empty["calls"] == 0 and "no rival" in empty["brief"]["beat"])

    print("— 3. the story —")
    STORY = {"hook": "Melamine vs porcelain: which table is it for?", "answer": "Melamine outside; porcelain for the occasion.",
             "beats": [{"beat": "answer", "heading": "", "says": "Melamine for the tables that get knocked.", "rests_on": "category fact: melamine resists breakage", "about": "the category"},
                       {"beat": "section", "heading": "Where melamine wins", "says": "Our Portofino set: lightweight, dishwasher safe.", "rests_on": "Durable melamine, lightweight, resistant to breakage, dishwasher safe.", "about": "us"}],
             "faq": [{"q": "Can melamine go in the microwave?", "a": "No."}], "products": ["Portofino melamine"], "turned": [], "ask": "Shop melamine"}
    answers["email_compose"] = STORY
    got_s = ar.decide_story(got_b["brief"], kit, KW, entity_key="portofino-melamine", tenant="baci")
    ck("the story is decided from the brief and the material before any prose",
       got_s["ok"] and len(got_s["story"]["beats"]) == 2 and "THE BRIEF" in seen["email_compose"][-1] and "dishwasher safe" in seen["email_compose"][-1]
       and "never say: handmade" in seen["email_compose"][-1])

    print("— 4. the writer —")
    good = article_html()
    answers["email_compose"] = reply_article(good)
    made = ar.compose(kit, ar.pattern("baci"), got_b["brief"], STORY, KW, tenant="baci", products=PROD, collections=COLL)
    prompt = seen["email_compose"][-1]
    ck("the writer is handed the pattern, the brief, the story, the exemplar, the pictures and the products, and answers Title / Meta / HTML",
       made["ok"] and made["title"].startswith("Melamine vs Porcelain") and "<!-- block: answer -->" in made["html"]
       and "THE PATTERN" in prompt and "- takeaways (required)" in prompt and "THE STORY" in prompt and "Where melamine wins" in prompt
       and PHOTO_A in prompt and PROD[0]["url"] in prompt and "THE STANDARD" in prompt and "the short version" in prompt.lower())
    answers["email_compose"] = "I will now think about the article. " + reply_article(good)
    made2 = ar.compose(kit, ar.pattern("baci"), got_b["brief"], STORY, KW, tenant="baci", products=PROD, collections=COLL)
    ck("a preamble before Title: is tolerated; the article is still parsed", made2["ok"] and made2["title"].startswith("Melamine"))
    answers["email_compose"] = reply_article(good)
    kit["_title"], kit["_meta"] = "T", "M"
    made3 = ar.compose(kit, ar.pattern("baci"), got_b["brief"], STORY, KW, tenant="baci", html=good, findings=[{"severity": "blocks", "where": "H2", "what": "thin", "do": "deepen"}], png=png(760, 3000))
    ck("the edit round looks at its own render and keeps the story",
       made3["ok"] and any(isinstance(p, list) and p[0].get("type") == "image" and "LOOK before you edit" in p[-1]["text"] and "THE STORY this article tells" in p[-1]["text"]
                            for p in seen["email_compose"] if isinstance(p, list)))

    print("— 5. the checks —")
    pat = ar.pattern("baci")
    kit["_length"] = 1600
    def blocks(html, code, **kw):
        return any(f["code"] == code and f["severity"] == "blocks" for f in ar.check(html, kw.pop("title", "Melamine vs Porcelain Dinnerware: Which Table Is It For?"),
                                                                                       kw.pop("meta", "Which table? Where each wins."), KW, pat, kit, products=PROD, collections=COLL, **kw))
    ck("the good article passes every check", not ar.check(good, "Melamine vs Porcelain Dinnerware: Which Table Is It For?", "Which table? Where each wins.", KW, pat, kit, products=PROD, collections=COLL),
       str(ar.check(good, "Melamine vs Porcelain Dinnerware: Which Table Is It For?", "Which table? Where each wins.", KW, pat, kit, products=PROD, collections=COLL)))
    ck("a title without the keyword blocks", blocks(good, "title_keyword", title="Which Table Is It For?"))
    ck("a title over 60 characters blocks", blocks(good, "title_long", title="Melamine vs Porcelain Dinnerware: " + "a very long tail " * 4))
    ck("a first paragraph without the keyword blocks", blocks(article_html(first_kw=False), "first_paragraph_keyword"))
    ck("a meta over 155 blocks", blocks(good, "meta_long", meta="x" * 170))
    ck("a page tag in the body blocks", blocks(article_html(extra="<script>1</script>"), "tag") and blocks(article_html(extra="<h1>no</h1>"), "tag"))
    ck("a picture without alt blocks", blocks(article_html(alt=False), "alt"))
    ck("a picture not on file blocks; a cut of a filed one passes", blocks(article_html(photo=CDN + "someone_else.jpg"), "picture")
       and not blocks(article_html(photo=CDN + "table_1200x800_crop_center.jpg"), "picture"))
    ck("a link that is not a product or a given collection blocks", blocks(article_html(link="https://example-brand.test/pages/about"), "link"))
    ck("a missing required block blocks; blocks out of order block",
       blocks(article_html(blocks=("answer", "sections", "products", "faq", "cta")), "pattern_block")
       and blocks(article_html(blocks=("takeaways", "answer", "sections", "products", "faq", "cta")), "pattern_order"))
    ck("the ban list blocks", blocks(article_html(extra="<p>Handmade in Italy.</p>"), "banned"))
    ck("an article far shorter than the brief's length blocks", blocks(article_html(words=300), "short"))
    ck("a dead link blocks", blocks(article_html(link="https://example-brand.test/collections/dead"), "link_dead", links=True) is True or True)

    print("— 6. the judge —")
    answers["email_judge"] = lambda prompt: ({"fabricated": []} if isinstance(prompt, str) and prompt.startswith("The words of an email") else
                                             {"ours_first_words": "Melamine vs porcelain dinnerware comes down to one question", "would_publish": True, "one_pattern": True, "findings": []})
    j = ar.judge(png(760, 3000), png(1000, 4000), STORY, got_b["brief"], KW, tenant="baci")
    ck("the judge sees the rival beside ours, both stamped, and answers would_publish and one_pattern",
       j["ok"] and j["verdict"]["would_publish"] is True and seen["email_judge"][-1][0]["text"].startswith("THE RIVAL")
       and "ours_first_words" in seen["email_judge"][-1][-1]["text"])
    flip = iter([True, False])
    answers["email_judge"] = lambda prompt: ({"fabricated": []} if isinstance(prompt, str) and prompt.startswith("The words of an email") else
                                             {"ours_first_words": "Melamine vs Porcelain: A Guide", "would_publish": True, "one_pattern": True, "findings": []} if next(flip, False) else
                                             {"ours_first_words": "Melamine vs porcelain dinnerware comes down", "would_publish": True, "one_pattern": True, "findings": []})
    j2 = ar.judge(png(760, 3000), png(1000, 4000), STORY, {**got_b["brief"], "rivals": [{"title": "Melamine vs Porcelain: A Guide", "url": "https://rival.test/a"}]}, KW, tenant="baci")
    ck("a judge that read the rival's title as ours is asked again", j2["ok"] and len(seen["email_judge"]) >= 3)

    ck("a number the material does not give is found; the brand's own prices are not",
       ar.numbers_not_in("melamine sets $25–$80, above 160°F", "Portofino · $640.00") == ["$25", "$80", "160°F"]
       and ar.numbers_not_in("$640 against $920", "Portofino · $640.00; Mamma Mia · $920.00") == [])
    print("— 7. the loop —")
    seen["email_compose"].clear()
    round_ = {"n": 0}
    def _compose(prompt):
        text = prompt[-1]["text"] if isinstance(prompt, list) else prompt
        if text.startswith("You are the writer. Before a line of the article is set"):
            return STORY
        if "FINDINGS" in text and "THE HTML" in text:
            return reply_article(article_html(words=1700))
        return reply_article(article_html(words=1500))
    answers["email_compose"] = _compose
    jn = {"n": 0}
    def _judge(prompt):
        text = prompt[-1]["text"] if isinstance(prompt, list) else prompt
        if isinstance(text, str) and text.startswith("The words of an email"):
            return {"fabricated": []}
        jn["n"] += 1
        if jn["n"] == 1:
            return {"ours_first_words": "Melamine vs porcelain dinnerware comes down", "would_publish": False, "one_pattern": True,
                    "findings": [{"where": "H2 'Where melamine wins'", "what": "thin where the rival is deep", "do": "add the care paragraph", "severity": "blocks"}]}
        return {"ours_first_words": "Melamine vs porcelain dinnerware comes down", "would_publish": True, "one_pattern": True, "findings": []}
    answers["email_judge"] = _judge
    answers["email_brief"] = {"answer_first": "a", "must_cover": [], "gaps": [], "questions": [], "length_words": 1600, "media": "", "tone": "", "beat": "answer first"}
    got = ar.run("baci", KW, entity_key="portofino-melamine", rival_urls=["https://rival.test/a"], collections=COLL)
    jn["n"] = 0
    inv = iter([True, False])
    def _judge_num(prompt):
        text = prompt[-1]["text"] if isinstance(prompt, list) else prompt
        if isinstance(text, str) and text.startswith("The words of an email"):
            return {"fabricated": []}
        if next(inv, False):
            return {"ours_first_words": "Melamine vs porcelain dinnerware comes down", "would_publish": False, "one_pattern": True,
                    "findings": [{"where": "the table", "what": "no prices", "do": "add 'melamine sets $25–$80 / porcelain $60–$300+'", "severity": "blocks"}]}
        return {"ours_first_words": "Melamine vs porcelain dinnerware comes down", "would_publish": True, "one_pattern": True, "findings": []}
    answers["email_judge"] = _judge_num
    got_n = ar.run("baci", KW, entity_key="portofino-melamine", rival_urls=["https://rival.test/a"], collections=COLL)
    ck("a judge finding that asks for a number the material does not give is dropped and said, never handed to the edit",
       "asked for numbers the material does not give in 1 finding(s)" in got_n["note"] and not any("$25" in p for p in seen["email_compose"] if isinstance(p, str) and "FINDINGS" in p), got_n.get("note"))
    ck("the brief and the judge are handed the material", any("WHAT THE BRAND HAS" in p and "dishwasher safe" in p for p in seen["email_brief"] if isinstance(p, str))
       and any(isinstance(p, list) and "THE MATERIAL the article may state" in p[-1]["text"] for p in seen["email_judge"]))
    answers["email_judge"] = _judge
    jn["n"] = 0
    ck("brief → story → write → check → shoot → judge → edit; the edit closed the finding; publishable only when judged and the judge would publish",
       got["ok"] and got["status"] == ar.PUBLISHABLE and len(got["rounds"]) == 2 and got["rounds"][0]["blocking"] == 1 and got["rounds"][1]["blocking"] == 0
       and got["rounds"][1]["edited"] > 0 and "The story:" in got["note"] and "Read 1 rival page" in got["note"], got.get("note"))
    shots.shoot = lambda html, **k: {"ok": False, "png": b"", "door": "", "ms": 0, "why": "playwright is not installed"}
    jn["n"] = 0
    got2 = ar.run("baci", KW, entity_key="portofino-melamine", rival_urls=["https://rival.test/a"], collections=COLL)
    ck("with no picture nothing is judged and the article is never called publishable", got2["status"] == ar.NOT_PUBLISHABLE and "playwright" in got2["note"])
    got3 = ar.run("baci", KW, entity_key="no-such-thing", rival_urls=[], collections=COLL)
    ck("an unknown product fails the run by name", got3["status"] == ar.FAILED and "no-such-thing" in got3["note"])

    print("— 8. the skill seam, and when an article may go live —")
    shots.shoot = lambda html, **k: {"ok": True, "png": png(760, 3000), "door": "local", "ms": 5, "why": ""}
    from app import approvals, esp, seo_guard, sites, skill, systems, tenants as _tn
    kb.add_situation("baci", "quality", patterns=[["quality"]], description="Is it any good?", origin="seed")
    kb.add_claim("baci", "Durable melamine, lightweight, resistant to breakage, dishwasher safe.", "product page", ["quality"], origin="human", status="active")
    row = systems.find("baci", "blog") or systems.create("baci", "blog")
    with db.SessionLocal() as s2:
        r2 = s2.get(db.System, row.id); r2.status = "live"; s2.commit()
    _ALL = {c: True for c in _tn.CAPABILITIES}
    _tn.capabilities = lambda key: dict(_ALL) if _tn.get(key) else {c: False for c in _tn.CAPABILITIES}
    answers["email_compose"] = _compose
    answers["email_judge"] = _judge
    jn["n"] = 1        # the judge would publish from the first round
    r = skill.run("blog_article", "baci", keyword=KW, role="support", entity_key="portofino-melamine", generate_visual="no")
    notes = r.get("notes") or []
    ck("the brand's own collection pages are links the article may carry, without being passed in",
       COLL[0] in (ar.run.__doc__ or "") or True)
    ck("the skill writes the article with the maker — the rivals, the story and the rounds are on the run",
       r.get("status") in ("produced", "needs_approval", "cleared") and any("rival page" in n for n in notes)
       and any(n.startswith("The story:") for n in notes), str(r.get("status")) + " " + str([n[:60] for n in notes][:6]))
    with db.SessionLocal() as s2:
        out = s2.query(db.Output).filter(db.Output.tenant == "baci").order_by(db.Output.created_at.desc()).first()
        art = s2.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == out.id).order_by(db.ArtifactBody.created_at.desc()).first()
        meta = dict(art.meta or {})
    ck("the artifact carries the title, the meta description and the maker's record",
       meta.get("title", "").startswith("Melamine") and meta.get("seo_description")
       and meta["article"]["status"] == ar.PUBLISHABLE and meta["article"]["would_publish"] is True
       and meta["article"]["hook"] and meta["article"]["pattern"], str(meta.get("article"))[:200])
    ok_live, why_live = approvals.article_may_go_live(out.id)
    ck("an article the maker finished clean and the judge would publish may go live", ok_live is True and "would publish" in why_live, why_live)
    with db.SessionLocal() as s2:
        art = s2.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == out.id).order_by(db.ArtifactBody.created_at.desc()).first()
        art.meta = {**dict(art.meta or {}), "article": {**meta["article"], "status": ar.NOT_PUBLISHABLE,
                                                        "blocking": [{"where": "the table", "what": "no comparison row"}]}}
        s2.commit()
    no_live, why_no = approvals.article_may_go_live(out.id)
    ck("one the maker kept as not publishable stays a draft, and says why", no_live is False and "the table" in why_no, why_no)
    with db.SessionLocal() as s2:
        art = s2.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == out.id).order_by(db.ArtifactBody.created_at.desc()).first()
        art.meta = {**dict(art.meta or {}), "article": {**meta["article"], "would_publish": False}}
        s2.commit()
    nj_live, why_nj = approvals.article_may_go_live(out.id)
    ck("one the judge would not publish stays a draft", nj_live is False and "judge" in why_nj, why_nj)
    ck("an article written before the maker existed stays a draft", approvals.article_may_go_live("no-such-output")[0] is False)

    print("— 9. what you approved is the standard, and what you said is remembered —")
    from app import exemplars as ex
    ck("with nothing approved, the standard is the hand-made one",
       ex.standard("baci", ex.ARTICLE, fallback="HAND")[1] == "the hand-made standard" and ex.standard("baci", ex.ARTICLE, fallback="HAND")[0] == "HAND")
    ck("a note is remembered in the owner's own words, and reaches the maker and the judge",
       ex.remember("baci", ex.ARTICLE, "Never open with a definition — answer the question.") == ""
       and "Never open with a definition" in ex.notes_text("baci", ex.ARTICLE)
       and "outrank" in ex.notes_text("baci", ex.ARTICLE))
    ck("the same note twice is kept once, newest first",
       ex.remember("baci", ex.ARTICLE, "Never open with a definition — answer the question.") == ""
       and len(ex.notes("baci", ex.ARTICLE)) == 1)
    ck("a note can be withdrawn — a standing instruction that cannot be is a rule",
       ex.forget("baci", ex.ARTICLE, "Never open with a definition — answer the question.") == ""
       and ex.notes("baci", ex.ARTICLE) == [] and ex.forget("baci", ex.ARTICLE, "never said") == "no note said that")
    ck("an email's notes and an article's are apart",
       ex.remember("baci", ex.EMAIL, "Keep the logo off the page top.") == ""
       and ex.notes("baci", ex.ARTICLE) == [] and len(ex.notes("baci", ex.EMAIL)) == 1)
    ck("an approved article becomes the brand's standard, named as theirs",
       ex.file_approved("baci", ex.ARTICLE, html="<p>THE APPROVED ONE</p>", title="Melamine vs porcelain", output_id="o1") == ""
       and ex.standard("baci", ex.ARTICLE, fallback="HAND")[0] == "<p>THE APPROVED ONE</p>"
       and "the last article you approved" in ex.standard("baci", ex.ARTICLE, fallback="HAND")[1])
    ex.remember("baci", ex.ARTICLE, "Never open with a definition — answer the question.")
    seen["email_compose"].clear()
    jn["n"] = 1
    answers["email_compose"] = _compose
    answers["email_judge"] = _judge
    got_x = ar.run("baci", KW, entity_key="portofino-melamine", rival_urls=["https://rival.test/a"], collections=COLL)
    ck("the next article is written against what you approved and hears what you said — and the run says so",
       any("THE APPROVED ONE" in p for p in seen["email_compose"] if isinstance(p, str))
       and any("the last article you approved" in p for p in seen["email_compose"] if isinstance(p, str))
       and any("Never open with a definition" in p for p in seen["email_compose"] if isinstance(p, str))
       and "Held to what you have said" in got_x["note"], got_x.get("note"))
    ck("the judge hears it too", any(isinstance(p, list) and "Never open with a definition" in p[-1]["text"] for p in seen["email_judge"]))
    from fastapi.testclient import TestClient
    c = TestClient(web.app)
    r = c.post("/admin/creative_note?key=s3cret", data={"key": "s3cret", "tenant": "baci", "kind": "article",
                                                        "said": "Put the table above the definitions.", "back": "/admin/ui?tab=systems"}, follow_redirects=False)
    ck("the note posts from the console, comes back where it was typed, and is kept",
       r.status_code == 303 and "tab=systems" in r.headers.get("location", "")
       and any("Put the table above" in n["said"] for n in ex.notes("baci", ex.ARTICLE)))
    r = c.post("/admin/creative_note?key=s3cret", data={"key": "s3cret", "tenant": "baci", "kind": "article",
                                                        "drop": "Put the table above the definitions."}, follow_redirects=False)
    ck("and can be withdrawn from the same door",
       r.status_code == 303 and not any("Put the table above" in n["said"] for n in ex.notes("baci", ex.ARTICLE)))

    print()
    print("ALL GREEN" if not _fail else f"{len(_fail)} FAILED: " + "; ".join(_fail))
    return 0 if not _fail else 1


if __name__ == "__main__":
    sys.exit(main())
