"""THE MODEL WRITES THE ARTICLE; THE CODE INSPECTS IT; AN EDITOR LOOKS.

INITIATIVE-blog-quality.md, 2026-09-18 — the email maker's loop
(`recreate.py`) applied to the blog, on top of the keyword map, the plan,
the claims, the pictures and the Shopify arm that already exist.

The reference, for an article, is three things (§0a of the plan):
  - THE PATTERN — the brand's standing layout, once per brand: the blocks an
    article carries and in what order. Read from a URL the owner likes, or
    declared by the maker and filed on the first approval. `pattern()`.
  - THE SERP BRIEF — what ranks for this keyword, per article: the rivals'
    structure, depth, gaps, media, the length that wins. `rivals()` + `brief()`.
  - AN APPROACH REFERENCE — optional: an article the owner likes for its way
    in, read for its concept and argument, never its layout. `approach()`.

Then, as for the email: the STORY before the prose (`decide_story`), the
article written whole (`compose`), the INVARIANTS (`check` — the only closed
list), the render (`shoot`), the JUDGE with eyes (`judge`, an editor and an
SEO: would you publish?), ≤ ROUNDS of edits, the best round kept (`run`).
Nothing here is a rule about good writing; the standard is the exemplar and
the SERP brief, the owner's approvals the thing that raises it.
"""
from __future__ import annotations

import json
import re

from . import config, db
from .recreate import (_Walk_words, _ask, _devices_text, _json, _material, _norm,  # noqa: F401
                       blocking, truth)

ROUNDS = 2
#: The rivals read for a brief — the pages a searcher sees first.
RIVALS_READ = 4
#: A rival page fetched at most this many bytes; a listicle can run to megabytes.
FETCH_MAX = 1_500_000
#: The pattern's blocks are marked so the check can see them.
_BLOCK = re.compile(r"<!--\s*block:\s*([a-z_\-]+)\s*-->", re.I)

PUBLISHABLE, NOT_PUBLISHABLE, FAILED = "publishable", "not publishable", "failed"

#: THE DEFAULT PATTERN — the hand-made Baci article's blocks (Phase 0,
#: `docs/recreations/baci-melamine-vs-porcelain.html`), in words a maker can
#: lay out from. A brand with no pattern of its own starts here; the first
#: approved article files the brand's own.
PATTERN_DEFAULT = {
    "name": "answer, takeaways, sections, table, products, choose, care, faq, cta",
    "blocks": [
        {"name": "answer", "what": "the first paragraph answers the query in plain words, the key sentence in bold", "required": True},
        {"name": "takeaways", "what": "a short box, 3–4 bullets, headed 'The short version' — the whole article in a glance", "required": True},
        {"name": "sections", "what": "H2 sections that are the reader's real sub-questions, short paragraphs, one photograph in the two or three sections that most need one", "required": True},
        {"name": "table", "what": "a side-by-side table where two things are compared — plain rows, a header row on a light ground", "required": False},
        {"name": "products", "what": "a callout of the brand's own pieces the article is about: picture, name, what it is, price, one link each — two or three cards side by side", "required": True},
        {"name": "choose", "what": "'How to choose' — an if/then list by the reader's situation", "required": False},
        {"name": "care", "what": "care or use notes when the subject is a thing", "required": False},
        {"name": "faq", "what": "'Questions people ask' — the searched questions as H3 + one paragraph each", "required": True},
        {"name": "cta", "what": "a closing band: one line, one or two buttons to the collection pages", "required": True},
    ],
    "devices": ["a bordered takeaways box with the accent colour on its left edge", "a comparison table",
                "product cards with a thin border and radius", "a soft grey CTA band with solid buttons"],
    "voice_of_layout": "generous white space, short paragraphs, headings that are questions or plain statements, nothing decorative",
}

PATTERN_FIELD = "article_pattern"


# ---------------------------------------------------------------------------
# THE PATTERN — the brand's standing layout
# ---------------------------------------------------------------------------

def pattern(tenant: str) -> dict:
    """The brand's article pattern, or the default with `default: True`."""
    from . import kb
    b = kb.ensure_brand(tenant, tenant)
    got = dict(((getattr(b, "visual", None) or {}).get(PATTERN_FIELD)) or {})
    if got.get("blocks"):
        return got
    return {**PATTERN_DEFAULT, "default": True}


def file_pattern(tenant: str, pattern_: dict, *, source_url: str = "", by: str = "owner") -> str:
    """The brand's pattern, filed — on approval of an article laid out in it,
    or from a reference read. The one writer."""
    from . import kb
    if not pattern_.get("blocks"):
        return "a pattern needs blocks"
    b = kb.ensure_brand(tenant, tenant)
    visual = dict(getattr(b, "visual", None) or {})
    visual[PATTERN_FIELD] = {k: v for k, v in pattern_.items() if k != "default"} | {
        "source_url": source_url, "filed_by": by, "filed_at": db.utcnow().isoformat()}
    kb.set_brand(tenant, visual=visual)
    return ""


_PATTERN_PROMPT = """You are a senior editor reading an article's LAYOUT for a colleague who will lay out every
article of another brand the same way. You have the page's headings and text in order, and a
picture of it. Describe the pattern — the blocks, top to bottom, in words a designer can lay out
from — as JSON:
{"name": a short name for the pattern,
 "blocks": [{"name": a short key (answer, takeaways, sections, table, products, quote, steps,
             faq, cta …), "what": what the block is and how it is set, "required": true|false}],
 "devices": [each distinct device you see, described so it can be drawn],
 "voice_of_layout": one line on spacing, headings, density}
Describe the layout only — never the article's subject, words or brand. Return the JSON only."""


def read_pattern(url: str, *, tenant: str = "") -> dict:
    """A reference article's layout, read once into a pattern. `{ok, pattern, why, calls}`."""
    page = _fetch_page(url)
    if not page.get("ok"):
        return {"ok": False, "pattern": {}, "why": page.get("why"), "calls": 0}
    blocks = []
    shot = _shoot_url(url)
    if shot.get("png"):
        from . import pictures as ed
        try:
            _, edge = ed._tier_edge()
            blocks.append(ed._image_block(ed.contact_sheet(shot["png"], edge)))
        except Exception:                                         # noqa: BLE001
            pass
    blocks.append({"type": "text", "text": "HEADINGS AND TEXT, in order:\n" + page["outline"][:6000] + "\n\n" + _PATTERN_PROMPT})
    reply = _ask("email_brief", blocks, tenant=tenant, max_tokens=3000)
    got = _json(reply.text) if getattr(reply, "ok", False) else None
    if not isinstance(got, dict) or not got.get("blocks"):
        return {"ok": False, "pattern": {}, "calls": 1, "why": "the reader did not answer with a pattern — " + str(getattr(reply, "error", "") or "no JSON")}
    return {"ok": True, "pattern": got, "why": "", "calls": 1}


# ---------------------------------------------------------------------------
# THE SERP — what ranks, read into a brief
# ---------------------------------------------------------------------------

def _fetch_page(url: str) -> dict:
    """A public page: its title, H1, headings in order, word count, images,
    a table or not, question headings, and the text — for a brief.
    `{ok, url, title, outline, words, images, table, questions, why}`."""
    import httpx
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"})
        if r.status_code >= 400:
            return {"ok": False, "url": url, "why": f"answers {r.status_code}"}
        html = r.text[:FETCH_MAX]
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "url": url, "why": f"{type(e).__name__}"}
    body = re.sub(r"<(script|style|nav|footer|header|noscript)\b.*?</\1>", " ", html, flags=re.S | re.I)
    m = re.search(r"<(article|main)\b[^>]*>(.*?)</\1>", body, re.S | re.I)
    main = m.group(2) if m else body
    title = _norm(re.sub(r"<[^>]+>", "", (re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I) or [None, ""])[1]))
    heads = [(h.lower(), _norm(re.sub(r"<[^>]+>", "", t))) for h, t in re.findall(r"<(h[1-3])\b[^>]*>(.*?)</\1>", main, re.S | re.I)]
    heads = [(h, t) for h, t in heads if t]
    text = _norm(re.sub(r"<[^>]+>", " ", main))
    words = len(text.split())
    images = len(re.findall(r"<img\b", main, re.I))
    outline = f"TITLE: {title}\n" + "\n".join(f"{h.upper()}: {t}" for h, t in heads) + "\n\nTEXT (first 2,500 words):\n" + " ".join(text.split()[:2500])
    return {"ok": True, "url": url, "title": title, "heads": heads, "outline": outline, "words": words, "images": images,
            "table": bool(re.search(r"<table\b", main, re.I)), "faq": any("?" in t for _, t in heads),
            "questions": [t for _, t in heads if "?" in t][:8]}


def rivals(tenant: str, keyword: str, *, urls: list | None = None) -> list[dict]:
    """The pages that rank for the keyword, read. `urls` overrides what is
    on file (the local runner; a plan item with a hand-picked rival)."""
    from . import keywords
    if not urls:
        row = keywords.latest_serp(tenant, keyword)
        urls = [str(r.get("url") or r.get("Url") or "") for r in (row.rivals or []) if isinstance(r, dict)] if row else []
        urls = [u for u in urls if u.startswith("http")]
    out = []
    for u in urls[:RIVALS_READ + 2]:
        got = _fetch_page(u)
        if got.get("ok"):
            out.append(got)
        if len(out) >= RIVALS_READ:
            break
    return out


_BRIEF_PROMPT = """You are an editor briefing a writer who must beat these pages for the search "%(keyword)s".
Read them as a rival does. Then write the brief as JSON:
{"answer_first": the one-sentence answer the article must open with (the searcher's question,
    answered plainly),
 "must_cover": [the sub-questions and sections every strong page covers — in the reader's words],
 "gaps": [what NONE of them does well — the angle that wins: a real price, a decision by
    situation, the design question, a table nobody has, a question nobody answers],
 "questions": [the questions a searcher asks around this, for the FAQ],
 "length_words": the length that wins here — the depth of the best page, not the longest,
 "media": what pictures or tables the best pages carry and what ours should,
 "tone": one line on how the best page reads (plain, expert, salesy) and how ours should differ,
 "beat": the single line that says how ours will be better}
Never copy a rival's words. Return the JSON only.

THE PAGES THAT RANK
%(pages)s"""


def brief(tenant: str, keyword: str, reads: list[dict]) -> dict:
    """The SERP brief: what ranks, read into what ours must do. `{ok, brief, why, calls}`."""
    if not reads:
        return {"ok": True, "brief": {"answer_first": "", "must_cover": [], "gaps": [], "questions": [], "length_words": 1400,
                                      "media": "", "tone": "", "beat": "no rival pages were on file — write the best page you can",
                                      "rivals": []}, "why": "no rivals read", "calls": 0}
    pages = "\n\n".join(f"--- {p['url']} — {p['words']} words, {p['images']} pictures, "
                        f"{'a table' if p.get('table') else 'no table'}, {'an FAQ' if p.get('faq') else 'no FAQ'}\n{p['outline'][:4500]}"
                        for p in reads)
    reply = _ask("email_brief", _BRIEF_PROMPT % {"keyword": keyword, "pages": pages}, tenant=tenant, max_tokens=2500)
    got = _json(reply.text) if getattr(reply, "ok", False) else None
    if not isinstance(got, dict):
        return {"ok": False, "brief": {}, "calls": 1, "why": "the editor did not answer with a brief — " + str(getattr(reply, "error", "") or "no JSON")}
    got["rivals"] = [{"url": p["url"], "title": p["title"], "words": p["words"], "table": p.get("table"), "faq": p.get("faq")} for p in reads]
    return {"ok": True, "brief": got, "why": "", "calls": 1}


_APPROACH_PROMPT = """An article another writer wrote, that our owner likes for its WAY IN. Read it for its concept and
argument — never its layout, never its subject's facts — as JSON:
{"concept": what this article IS, in a sentence ("two materials compared by the table you set",
    "the five mistakes buyers make", "a season's guide"),
 "argument": [{"beat": "...", "says": what the beat does, "does": what it does to the reader}],
 "devices_of_writing": [the writing devices — a direct answer first, a decision list, a
    myth-then-truth, a price reveal]}
Return the JSON only.

%(outline)s"""


def approach(url: str, *, tenant: str = "") -> dict:
    """An approach reference, read for its concept and argument. `{ok, approach, why, calls}`."""
    page = _fetch_page(url)
    if not page.get("ok"):
        return {"ok": False, "approach": {}, "why": page.get("why"), "calls": 0}
    reply = _ask("email_brief", _APPROACH_PROMPT % {"outline": page["outline"][:7000]}, tenant=tenant, max_tokens=2000)
    got = _json(reply.text) if getattr(reply, "ok", False) else None
    if not isinstance(got, dict):
        return {"ok": False, "approach": {}, "calls": 1, "why": "the reader did not answer — " + str(getattr(reply, "error", "") or "no JSON")}
    got["url"] = url
    return {"ok": True, "approach": got, "why": "", "calls": 1}


# ---------------------------------------------------------------------------
# THE STORY — the argument before the prose
# ---------------------------------------------------------------------------

_STORY_PROMPT = """You are the writer. Before a line of the article is set, decide THE STORY — the argument
this article makes for %(name)s about "%(keyword)s" — the way a good editor does: the searcher's
question, the answer, what has to be covered to be the best page, what we alone can add, the ask.

THE BRIEF — what ranks, read by an editor:
%(brief)s
%(approach)s
THE BRAND
name: %(name)s — %(positioning)s
%(rules_brand)s
THE MATERIAL — the only facts available about what the brand sells (its own product text, the
approved claims); a fact not here is not stated:
%(material)s
%(questions)s
Write the story as JSON:
{"hook": the title's idea in a line — carries "%(keyword)s" naturally, means something alone,
 "answer": the first paragraph's answer in one or two sentences,
 "beats": [{"beat": "answer" | "section" | "contrast" | "proof" | "choose" | "faq" | "ask",
            "heading": the H2 it becomes (a question or a plain statement in the reader's words),
            "says": what it says — the gist in at most 40 words, not the prose (the article is written
                    after, from this),
            "rests_on": the fact it rests on — quoted from the material, or "category fact:" + a
                        statement that is true of the category and not a claim about our product,
            "about": "the category" | "the reader" | "us"}],
 "faq": [{"q": ..., "a": one or two sentences}],
 "products": [the brand's own pieces the article shows, by name, with why],
 "turned": [anything the brief asked for that the material cannot support, and what you did],
 "ask": the closing line and the buttons}
Rules: a contrast beat names WHOSE failing it is; nothing implies what is untrue of our product;
category facts are said as the category's and are ones you would bet on without a source — never
a number, a price band, a statistic or a study you cannot quote from the material; the beat
marked "the reader" or "the category" is never a claim about us. Eight beats at most. Length:
plan for about %(length)s words. Answer with the JSON only, nothing before it."""


def decide_story(brief_: dict, kit_: dict, keyword: str, *, entity_key: str = "", questions: list | None = None,
                 approach_: dict | None = None, tenant: str = "") -> dict:
    from .recreate import kb_ban
    voice = kit_.get("voice") or {}
    never = list(voice.get("never_say") or []) + list((kb_ban(kit_.get("tenant", "")) or [])[:30])
    rules_brand = ("never say: " + ", ".join(map(str, never[:24])) + "\n") if never else ""
    if (kit_.get("rules") or {}).get("channel"):
        rules_brand += "the brand's writing instructions: " + kit_["rules"]["channel"][:600] + "\n"
    prompt = _STORY_PROMPT % {
        "name": kit_.get("name") or "the brand", "positioning": kit_.get("positioning") or "", "keyword": keyword,
        "rules_brand": rules_brand, "material": (_material(kit_, entity_key) or "(nothing beyond the product names)")[:3500],
        "brief": json.dumps({k: brief_.get(k) for k in ("answer_first", "must_cover", "gaps", "questions", "media", "tone", "beat")},
                            ensure_ascii=False, indent=1)[:4000],
        "approach": ("\nTHE APPROACH the owner likes — its concept and argument, not its layout or facts:\n"
                     + json.dumps(approach_, ensure_ascii=False)[:2000] + "\n") if approach_ else "",
        "questions": ("\nQUESTIONS PEOPLE SEARCH, to answer:\n" + "\n".join(f"- {q}" for q in (questions or [])[:8]) + "\n") if questions else "",
        "length": brief_.get("length_words") or 1400}
    reply = _ask("email_compose", prompt, tenant=tenant, max_tokens=8000)
    got = _json(reply.text) if getattr(reply, "ok", False) else None
    if not isinstance(got, dict) or not got.get("beats"):
        cut = getattr(reply, "stop_reason", "") == "max_tokens"
        return {"ok": False, "story": {}, "calls": 1, "why": "the writer did not answer with a story — "
                + (f"it ran past the length limit ({len(reply.text or '')} characters)" if cut else str(getattr(reply, "error", "") or "no JSON"))}
    return {"ok": True, "story": got, "why": "", "calls": 1}


def _story_text(st: dict | None) -> str:
    if not st:
        return ""
    lines = [f"hook: {st.get('hook', '')}", f"answer: {st.get('answer', '')}"]
    for b in st.get("beats") or []:
        lines.append(f"- [{b.get('beat', '')}] ({b.get('about', '')}) H2 \"{b.get('heading', '')}\": {b.get('says', '')}"
                     + (f"  — rests on: {b['rests_on']}" if b.get("rests_on") else ""))
    for q in st.get("faq") or []:
        lines.append(f"- [faq] {q.get('q', '')} — {q.get('a', '')}")
    if st.get("products"):
        lines.append("products: " + "; ".join(map(str, st["products"])))
    if st.get("ask"):
        lines.append(f"ask: {st['ask']}")
    if st.get("turned"):
        lines.append("turned: " + "; ".join(map(str, st["turned"])))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# THE EXEMPLAR and THE COMPOSE
# ---------------------------------------------------------------------------

def exemplar() -> str:
    """THE STANDARD — the article written by hand on 2026-09-18 (Baci,
    melamine vs porcelain), shown as an example of the craft: a direct
    answer, a real table, the brand's own prices, a decision by situation.
    Never a subject to copy."""
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(here, "docs", "recreations", "baci-melamine-vs-porcelain.html"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


_COMPOSE_PROMPT = """You are the writer AND the editor. Write the finished article for %(name)s on "%(keyword)s":
the title, the meta description and the complete body HTML — laid out in the brand's PATTERN,
told from THE STORY decided below, better than the pages that rank (THE BRIEF), with the
brand's own pictures and products, and nothing stated that the material does not hold.

THE PATTERN — the brand's standing layout; every article of this brand is laid out in it.
Emit each block wrapped in <!-- block: <name> --> … <!-- /block --> so the layout can be seen:
%(pattern)s

THE BRIEF — what ranks, and how ours is better:
%(brief)s

THE STORY — decided first; every H2 is a beat, every line belongs to one:
%(story)s

THE BRAND
name: %(name)s — %(positioning)s
faces on file: heading %(heading_face)s · body %(body_face)s · accent colour %(accent)s
%(rules_brand)s
THE PICTURES — the brand's own, the only ones allowed, each with what it shows; use the cut that
fits (`_1200x800_crop_center` before the extension for a wide picture, `_600x600_crop_center` for
a card), alt text that says what is in it, width set:
%(pictures)s

THE PRODUCTS — name · price · url, the only links allowed besides the collection pages:
%(products)s
collection pages you may link: %(collections)s

THE STANDARD — an article written by hand for this brand on another subject. Copy its CRAFT (a
direct answer first, a table that is really a table, real prices, a decision by the reader's
situation, a question answered per FAQ item), NOT its subject and not its sentences:
%(exemplar)s

RULES
- Body HTML only: no <html>, <head>, <body>, no <h1> (the title is the H1 the theme sets), no
  <script>, <style> blocks, no <iframe>. Inline styles only for the pattern's devices; the theme
  styles headings and paragraphs.
- About %(length)s words. Short paragraphs. H2s in the reader's words. H3 + one paragraph for each
  FAQ question. Every picture has alt text. No links but the ones listed.
- The keyword "%(keyword)s" appears in the title and in the first paragraph, naturally — never
  stuffed. Meta ≤ 155 characters, says what the reader gets.
- Every product fact is in the material; a category fact is said as the category's; a contrast
  is framed as whose it is; nothing implied that is untrue (melamine is plastic).
- Never "handmade", "artisanal", "crafted", "made in" a country, unless the material says so.

OUTPUT, exactly — the FIRST characters of your answer are "Title:":
Title: <≤ 60 characters, carries the keyword, worth clicking>
Meta: <≤ 155 characters>
<the body HTML>. Nothing after it."""


_REVISE_PROMPT = """Below is the article you wrote and the findings after it was checked and judged. EDIT the
HTML to close each finding. Change only what a finding requires; every other line stays.
%(story)s
FINDINGS
%(findings)s

OUTPUT, exactly — the FIRST characters of your answer are "Title:":
Title: <unchanged unless a finding names it>
Meta: <unchanged unless a finding names it>
<the complete body HTML>. Nothing after it.

THE HTML
%(html)s"""


def _pattern_text(p: dict) -> str:
    lines = [f"pattern: {p.get('name', '')}" + (" (the default — this brand has not filed its own yet)" if p.get("default") else "")]
    for b in p.get("blocks") or []:
        lines.append(f"- {b.get('name')}{' (required)' if b.get('required') else ''}: {b.get('what', '')}")
    if p.get("devices"):
        lines.append("devices: " + "; ".join(map(str, p["devices"])))
    if p.get("voice_of_layout"):
        lines.append("layout voice: " + str(p["voice_of_layout"]))
    return "\n".join(lines)


def _parse_article(text: str) -> tuple[str, str, str]:
    t = str(text or "")
    m = re.search(r"```(?:html)?\s*(.*?)```", t, re.S)
    if m and "<h2" in m.group(1).lower():
        t = t[:m.start()] + m.group(1) + t[m.end():]
    tm = re.search(r"^\s*Title:\s*(.+)$", t, re.M) or re.search(r"Title:\s*([^\n]+)", t)
    mm = re.search(r"^\s*Meta:\s*(.+)$", t, re.M) or re.search(r"Meta:\s*([^\n]+)", t)
    title = tm.group(1).strip() if tm else ""
    meta = mm.group(1).strip() if mm else ""
    k = mm.end() if mm else (tm.end() if tm else -1)
    html = t[k:].strip() if k >= 0 else t.strip()
    return title, meta, html


def compose(kit_: dict, pattern_: dict, brief_: dict, story_: dict, keyword: str, *, tenant: str = "",
            products: list | None = None, collections: list | None = None, html: str = "", findings=(),
            png: bytes = b"") -> dict:
    """`{ok, title, meta, html, why, edited}` — the article written whole, or
    edited to findings while LOOKING at its own render."""
    from .recreate import kb_ban
    theme = kit_.get("theme") or {}
    voice = kit_.get("voice") or {}
    seen_blocks: list = []
    if html and findings:
        prompt = _REVISE_PROMPT % {
            "findings": "\n".join(f'- [{f.get("severity", "")}] {f.get("where", "")}: {f.get("what", "")}'
                                  + (f' → {f["do"]}' if f.get("do") else "") for f in findings),
            "html": f"Title: {kit_.get('_title', '')}\nMeta: {kit_.get('_meta', '')}\n{html}",
            "story": ("THE STORY this article tells — an edit never changes a beat's meaning or drops its frame:\n"
                      + _story_text(story_) + "\n") if story_ else ""}
        if png:
            from . import pictures as ed
            try:
                _, edge = ed._tier_edge()
                seen_blocks = [ed._image_block(ed.contact_sheet(png, edge))] + [ed._image_block(p["png"]) for p in ed.strips(png, edge)[:3]]
                prompt = ("YOUR ARTICLE AS A READER SEES IT is above — whole, then top to bottom. LOOK before you edit: "
                          "walls of text, a table that broke, a picture in the wrong place, a block missing.\n\n") + prompt
            except Exception:                                     # noqa: BLE001
                seen_blocks = []
    else:
        never = list(voice.get("never_say") or []) + list((kb_ban(kit_.get("tenant", "")) or [])[:30])
        rules_brand = ("never say: " + ", ".join(map(str, never[:24])) + "\n") if never else ""
        if (kit_.get("rules") or {}).get("channel"):
            rules_brand += "the brand's writing instructions: " + kit_["rules"]["channel"][:600] + "\n"
        pics = []
        for p in (kit_.get("pictures") or [])[:30]:
            pics.append(f"- {p['url']}  — {p.get('title') or ''}" + (f" ({p['kind']})" if p.get("kind") else "")
                        + (f", about {p['entity_key']}" if p.get("entity_key") else ""))
        prods = [f"- {p.get('name')} · {p.get('price') or ''} · {p.get('url')}" for p in (products or [])[:12]]
        prompt = _COMPOSE_PROMPT % {
            "name": kit_.get("name") or "the brand", "positioning": kit_.get("positioning") or "", "keyword": keyword,
            "pattern": _pattern_text(pattern_), "brief": json.dumps({k: brief_.get(k) for k in ("answer_first", "must_cover", "gaps", "media", "tone", "beat", "length_words")}, ensure_ascii=False, indent=1)[:3500],
            "story": _story_text(story_), "heading_face": (theme.get("font") or {}).get("heading") or "(the theme's)",
            "body_face": (theme.get("font") or {}).get("body") or "(the theme's)", "accent": (theme.get("colors") or {}).get("accent") or "(the theme's)",
            "rules_brand": rules_brand, "pictures": "\n".join(pics) or "(none on file)", "products": "\n".join(prods) or "(none named)",
            "collections": ", ".join(collections or []) or "(none)", "exemplar": exemplar()[:12000],
            "length": brief_.get("length_words") or 1400}
    asked = seen_blocks + [{"type": "text", "text": prompt}] if seen_blocks else prompt
    reply = _ask("email_compose", asked, tenant=tenant, max_tokens=16000)
    if not getattr(reply, "ok", False) and "Connection" in str(getattr(reply, "error", "")):
        reply = _ask("email_compose", asked, tenant=tenant, max_tokens=16000)
    if not getattr(reply, "ok", False):
        return {"ok": False, "title": "", "meta": "", "html": "", "edited": 0, "why": "the writer did not answer — " + str(getattr(reply, "error", ""))}
    title, meta, out = _parse_article(reply.text)
    if "<h2" not in out.lower() or getattr(reply, "stop_reason", "") == "max_tokens":
        cut = getattr(reply, "stop_reason", "") == "max_tokens"
        return {"ok": False, "title": title, "meta": meta, "html": "", "edited": 0,
                "why": (f"the writer ran past the length limit ({len(reply.text or '')} characters)" if cut else "the writer did not return an article")
                + (f" — it began: {(reply.text or '').strip()[:120]!r}" if not (reply.text or "").lstrip().startswith("Title:") else "")}
    edited = 0
    if html:
        import difflib
        edited = sum(1 for d in difflib.unified_diff(html.splitlines(), out.splitlines(), lineterm="") if d.startswith(("+", "-")) and not d.startswith(("+++", "---")))
    return {"ok": True, "title": title or kit_.get("_title", ""), "meta": meta or kit_.get("_meta", ""), "html": out, "edited": edited, "why": ""}


# ---------------------------------------------------------------------------
# THE CHECKS — the invariants, the only closed list
# ---------------------------------------------------------------------------

def check(html: str, title: str, meta: str, keyword: str, pattern_: dict, kit_: dict, *,
          products: list | None = None, collections: list | None = None, links: bool = False) -> list[dict]:
    """`{code, severity, where, what}` — each an invariant, never a taste."""
    from . import keywords as _kw
    out: list[dict] = []
    add = lambda code, sev, where, what: out.append({"code": code, "severity": sev, "where": str(where)[:100], "what": str(what)[:300]})  # noqa: E731
    words = _Walk_words(html)
    want = set(_kw.tokens(keyword))
    if not title:
        add("title", "blocks", "title", "no title")
    elif len(title) > 65:
        add("title_long", "blocks", title[:60], f"{len(title)} characters — 60 is the edge of what a result shows")
    elif want and not want <= set(_kw.tokens(title)):
        add("title_keyword", "blocks", title[:60], f"the title does not carry {keyword!r}")
    first = _norm(re.sub(r"<[^>]+>", " ", (re.search(r"<p\b[^>]*>(.*?)</p>", html, re.S | re.I) or [None, ""])[1]))
    if want and not want <= set(_kw.tokens(first)):
        add("first_paragraph_keyword", "blocks", first[:60], f"the first paragraph does not carry {keyword!r} — the answer comes first, in the searcher's words")
    if not meta:
        add("meta", "blocks", "meta", "no meta description")
    elif len(meta) > 160:
        add("meta_long", "blocks", meta[:60], f"{len(meta)} characters — 155 is the edge")
    for tag in ("html", "head", "body", "script", "style", "iframe", "h1"):
        if re.search(rf"<{tag}\b", html, re.I):
            add("tag", "blocks", f"<{tag}>", f"<{tag}> does not belong in an article body")
    n_words = len(words.split())
    target = int(kit_.get("_length") or 0)
    if target and n_words < target * 0.6:
        add("short", "blocks", "length", f"{n_words} words against a brief of about {target} — the pages that rank are longer and deeper")
    for im in re.findall(r"<img\b[^>]*>", html, re.I):
        if not re.search(r'alt="[^"]+"', im):
            add("alt", "blocks", im[:60], "a picture without alt text")
    allowed_pics = {re.sub(r"\?.*$", "", p["url"]) for p in kit_.get("pictures") or []}
    stem = lambda u: re.sub(r"_\d+x\d*(?:_crop_\w+)?(\.\w+)$", r"\1", re.sub(r"\?.*$", "", u))  # noqa: E731
    for src in re.findall(r'<img[^>]*src="([^"]+)"', html, re.I):
        if src.startswith("data:"):
            continue
        if stem(src) not in allowed_pics and not any(a.startswith(stem(src).rsplit(".", 1)[0]) for a in allowed_pics):
            add("picture", "blocks", src[:90], "not one of the brand's own pictures on file")
    ok_links = {str(p.get("url") or "").split("?")[0].rstrip("/") for p in (products or [])} | {c.split("?")[0].rstrip("/") for c in (collections or [])}
    for href in re.findall(r'href="([^"]+)"', html, re.I):
        h = href.split("?")[0].rstrip("/")
        if href.startswith("#"):
            continue
        if h not in ok_links:
            add("link", "blocks", href[:90], "a link that is not one of the products or collection pages given")
    names = [m.lower() for m in _BLOCK.findall(html)]
    for b in pattern_.get("blocks") or []:
        if b.get("required") and str(b.get("name") or "").lower() not in names:
            add("pattern_block", "blocks", b.get("name"), f"the pattern's '{b.get('name')}' block is missing — {b.get('what', '')[:80]}")
    order = [str(b.get("name") or "").lower() for b in pattern_.get("blocks") or []]
    seen_i = [order.index(n) for n in names if n in order]
    if seen_i != sorted(seen_i):
        add("pattern_order", "blocks", ", ".join(names), "the blocks are not in the pattern's order")
    from . import validator
    for h in validator._banned(kit_.get("tenant", ""), words) or []:
        add("banned", "blocks", "copy", f"the brand's ban list: {h.get('phrase') or h}")
    if links:
        import httpx
        for href in sorted(set(re.findall(r'href="(https?://[^"]+)"', html, re.I))):
            try:
                r = httpx.head(href, timeout=8, follow_redirects=True)
                if r.status_code in (429, 405):
                    r = httpx.get(href, timeout=12, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code >= 400 and r.status_code != 429:
                    add("link_dead", "blocks", href[:80], f"answers {r.status_code}")
            except Exception as e:                                # noqa: BLE001
                add("link_dead", "blocks", href[:80], f"does not answer ({type(e).__name__})")
    return out


# ---------------------------------------------------------------------------
# THE RENDER and THE JUDGE
# ---------------------------------------------------------------------------

def page(html: str, title: str, kit_: dict) -> str:
    """The body in a page that carries the store's faces — what the judge
    and the owner look at. The theme owns the real chrome."""
    theme = kit_.get("theme") or {}
    face = (theme.get("font") or {}).get("body") or "Helvetica"
    head_face = (theme.get("font") or {}).get("heading") or face
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family={face.replace(' ', '+')}:wght@400;600;700&display=swap" rel="stylesheet">
<style>body{{margin:0;background:#fff;color:#1a1a1a;font-family:'{face}',Helvetica,Arial,sans-serif;font-size:17px;line-height:1.65}}
.wrap{{max-width:720px;margin:0 auto;padding:40px 24px}} h1{{font-family:'{head_face}',Helvetica,Arial,sans-serif;font-size:38px;line-height:1.15;margin:0 0 8px;font-weight:700}}
.meta{{color:#666;font-size:14px;margin:0 0 28px}} h2{{font-family:'{head_face}',Helvetica,Arial,sans-serif;font-size:26px;margin:40px 0 12px;line-height:1.2}}
h3{{font-size:19px;margin:24px 0 6px}} p{{margin:0 0 16px}} img{{max-width:100%;height:auto}} table{{width:100%}}</style></head>
<body><div class="wrap"><h1>{title}</h1><p class="meta">{kit_.get('name', '')} · {db.utcnow().strftime('%B %Y')}</p>{html}</div></body></html>"""


def shoot(html: str, title: str, kit_: dict) -> dict:
    from . import shots
    return shots.shoot(page(html, title, kit_), width=760)


def _shoot_url(url: str) -> dict:
    """A rival page or a reference, photographed for a read. `{ok, png, why}`."""
    from . import shots
    which, why = shots.door()
    if not which:
        return {"ok": False, "png": b"", "why": why}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(config.SHOTS_WS, timeout=shots.TIMEOUT_MS) if which == "browserless" else p.chromium.launch()
            try:
                pg = browser.new_page(viewport={"width": 1000, "height": 1000})
                pg.set_default_timeout(shots.TIMEOUT_MS)
                pg.goto(url, wait_until="domcontentloaded")
                png = pg.screenshot(full_page=True, type="png")
            finally:
                browser.close()
        return {"ok": bool(png), "png": png, "why": ""}
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "png": b"", "why": f"{type(e).__name__}: {str(e)[:120]}"}


_JUDGE_PROMPT = """Two articles: first THE RIVAL that ranks (whole), then OURS (whole, then its top, legible),
both labelled in their top band. Ours was written for "%(keyword)s" to be the better page, in the
brand's own pattern, from this story:
%(story)s
The brief's line on how ours wins: %(beat)s

Judge OURS as an editor and an SEO judge a page before it goes live, and answer JSON only:
{"ours_first_words": the first eight words you can read in OURS, top to bottom,
 "would_publish": true|false — is this the better page: answers first, covers what the rival
                  covers, adds what the rival lacks, reads like a person wrote it,
 "one_pattern": true|false — laid out in the pattern (the blocks, in order, drawn cleanly),
 "findings": [{"where": "the answer / H2 '…' / the table / the products / the FAQ",
               "what": what is WEAK — thin where the rival is deep, a wall of text, a heading that
                       says nothing, a claim the material cannot hold, a table that is a list, a
                       picture in the wrong place, a block missing,
               "do": the concrete edit the writer can make in the body,
               "severity": "blocks" if you would not publish without it, else "cosmetic"}]}
Never ask for the rival's words or pictures. Never ask for a photograph that does not exist —
name one in the article or say cut. A category fact framed as the category's is not a claim."""


def judge(ours_png: bytes, rival_png: bytes, story_: dict, brief_: dict, keyword: str, *, tenant: str = "") -> dict:
    from . import pictures as ed
    from .recreate import _confused, _stamp
    if not ours_png:
        return {"ok": False, "findings": [], "verdict": {}, "why": "no picture to judge", "calls": 0}
    _, edge = ed._tier_edge()
    blocks = []
    try:
        if rival_png:
            blocks.append({"type": "text", "text": "THE RIVAL — the page that ranks, whole:"})
            blocks.append(ed._image_block(_stamp(ed.contact_sheet(rival_png, edge), "RIVAL — whole")))
        blocks.append({"type": "text", "text": "OURS — whole:"})
        blocks.append(ed._image_block(_stamp(ed.contact_sheet(ours_png, edge), "OURS — whole")))
        blocks.append({"type": "text", "text": "OURS — its top, legible:"})
        blocks.append(ed._image_block(_stamp(ed.strips(ours_png, edge)[0]["png"], "OURS — top")))
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "findings": [], "verdict": {}, "why": f"a picture could not be cut: {e}", "calls": 0}
    blocks.append({"type": "text", "text": _JUDGE_PROMPT % {"keyword": keyword, "story": _story_text(story_)[:2500], "beat": brief_.get("beat") or ""}})
    calls, got, mixed = 0, None, ""
    for _ in range(2):
        reply = _ask("email_judge", blocks, tenant=tenant, max_tokens=2500)
        calls += 1
        got = _json(reply.text) if getattr(reply, "ok", False) else None
        if not isinstance(got, dict):
            mixed = "no JSON"
            continue
        mixed = _confused(got, {"reference_text": [r.get("title", "") for r in brief_.get("rivals") or []]}) if rival_png else ""
        if not mixed:
            break
    if not isinstance(got, dict):
        return {"ok": False, "findings": [], "verdict": {}, "calls": calls, "why": "the judge did not answer — no JSON, twice"}
    if mixed:
        return {"ok": False, "findings": [], "verdict": {}, "calls": calls, "why": f"the judge was confused twice — {mixed}"}
    finds = [{"code": "judge", "severity": "blocks" if str(f.get("severity", "")).lower() == "blocks" else "cosmetic",
              "where": str(f.get("where") or "")[:80], "what": str(f.get("what"))[:300], "do": str(f.get("do") or "")[:300]}
             for f in got.get("findings") or [] if isinstance(f, dict) and f.get("what")]
    verdict = {k: got.get(k) for k in ("would_publish", "one_pattern", "ours_first_words")}
    if verdict.get("would_publish") is False and not any(f["severity"] == "blocks" for f in finds):
        finds.insert(0, {"code": "judge", "severity": "blocks", "where": "the whole", "what": "the judge would not publish it and named no blocking finding", "do": "make it the better page"})
    return {"ok": True, "findings": finds, "verdict": verdict, "why": "", "calls": calls}


# ---------------------------------------------------------------------------
# THE LOOP
# ---------------------------------------------------------------------------

def run(tenant: str, keyword: str, *, role: str = "support", entity_key: str = "", questions: list | None = None,
        rival_urls: list | None = None, approach_url: str = "", products: list | None = None,
        collections: list | None = None, progress=None) -> dict:
    """Brief → story → write → check → shoot → judge → edit, best kept.
    Returns everything the card and the runner need; stores nothing but the
    pattern (a Phase 3 seam wires this into `blog_article` and the ledger)."""
    from .recreate import kit as _kit
    story: list[str] = []
    calls = 0
    say = progress or (lambda t: None)
    kit_ = _kit(tenant)
    if entity_key and not any(e.get("key") == entity_key for e in kit_.get("entities") or []):
        return {"ok": False, "status": FAILED, "note": f"no product with the key {entity_key!r} on file", "rounds": []}
    pat = pattern(tenant)
    say("reading what ranks")
    reads = rivals(tenant, keyword, urls=rival_urls)
    got_b = brief(tenant, keyword, reads)
    calls += got_b.get("calls", 0)
    if not got_b.get("ok"):
        return {"ok": False, "status": FAILED, "note": "The brief could not be read: " + str(got_b.get("why")), "rounds": []}
    brief_ = got_b["brief"]
    story.append(f"Read {len(reads)} rival page(s): " + (str(brief_.get("beat") or "")[:140] if reads else "none on file — writing the best page we can") + ".")
    app_ = None
    if approach_url:
        got_a = approach(approach_url, tenant=tenant)
        calls += got_a.get("calls", 0)
        app_ = got_a.get("approach") if got_a.get("ok") else None
        story.append(("Read the approach: " + str((app_ or {}).get("concept") or "")[:120]) if app_ else "The approach could not be read: " + str(got_a.get("why")))
    say("deciding the story")
    got_s = decide_story(brief_, kit_, keyword, entity_key=entity_key, questions=questions, approach_=app_, tenant=tenant)
    calls += got_s.get("calls", 0)
    if not got_s.get("ok"):
        return {"ok": False, "status": FAILED, "note": " ".join(story) + " " + str(got_s.get("why")), "rounds": [], "brief": brief_}
    story_ = got_s["story"]
    story.append(f"The story: {str(story_.get('hook') or '')[:100]} — {len(story_.get('beats') or [])} beats"
                 + ("; turned: " + "; ".join(map(str, story_["turned"]))[:200] if story_.get("turned") else "") + ".")
    if not products:
        products = [{"name": e.get("name"), "price": e.get("price", ""), "url": e.get("url")} for e in (kit_.get("entities") or [])
                    if e.get("url") and (not entity_key or e.get("key") == entity_key or any(
                        w in (e.get("name") or "").lower() for w in re.findall(r"[a-z]{4,}", keyword.lower())))][:12]
    kit_["_length"] = brief_.get("length_words") or 1400
    rival_png = b""
    if reads:
        shot_r = _shoot_url(reads[0]["url"])
        rival_png = shot_r.get("png") or b""
    rounds: list[dict] = []
    html, title, meta, prev_png, findings_prev = "", "", "", b"", []
    best_i, best_n = -1, 10 ** 6
    material_ = _material(kit_, entity_key)
    for n in range(ROUNDS + 1):
        say(f"round {n}: " + ("writing the article" if n == 0 else "editing to the findings"))
        kit_["_title"], kit_["_meta"] = title, meta
        made = compose(kit_, pat, brief_, story_, keyword, tenant=tenant, products=products, collections=collections,
                       html=html, findings=findings_prev, png=prev_png)
        calls += 1
        if not made.get("ok"):
            story.append(f"Round {n}: {made.get('why')}.")
            break
        html, title, meta = made["html"], made["title"], made["meta"]
        checks = check(html, title, meta, keyword, pat, kit_, products=products, collections=collections, links=True)
        told = truth(_Walk_words(html), material_, tenant=tenant)
        calls += told.get("calls", 0)
        checks += told["findings"]
        shot = shoot(html, title, kit_)
        judged = judge(shot.get("png") or b"", rival_png, story_, brief_, keyword, tenant=tenant) if shot.get("ok") else \
            {"ok": False, "findings": [], "verdict": {}, "why": shot.get("why") or "no picture", "calls": 0}
        calls += judged.get("calls", 0)
        open_ = blocking(checks) + blocking(judged.get("findings"))
        rounds.append({"n": n, "png": shot.get("png") or b"", "html": html, "title": title, "meta": meta, "check": checks,
                       "judge": judged.get("findings") or [], "verdict": judged.get("verdict") or {}, "judged": bool(judged.get("ok")),
                       "why_not_judged": judged.get("why") or "", "blocking": len(open_), "edited": made.get("edited", 0)})
        story.append(f"Round {n}: {len(blocking(checks))} check(s) block, "
                     + (f"the judge names {sum(1 for f in judged.get('findings') or [] if f['severity'] == 'blocks')} blocking"
                        if judged.get("ok") else f"not judged ({judged.get('why')})")
                     + (f", {made.get('edited', 0)} lines edited" if n else "") + ".")
        if len(open_) < best_n:
            best_i, best_n = n, len(open_)
        if not open_ and judged.get("ok"):
            break
        findings_prev = open_ + [f for f in judged.get("findings") or [] if f["severity"] == "cosmetic"][:3]
        prev_png = shot.get("png") or b""
    if best_i < 0:
        return {"ok": False, "status": FAILED, "note": " ".join(story), "rounds": rounds, "brief": brief_, "story": story_, "calls": calls}
    best = rounds[best_i]
    status = PUBLISHABLE if best["blocking"] == 0 and best["judged"] and (best["verdict"] or {}).get("would_publish") else NOT_PUBLISHABLE
    story.append(f"Kept round {best_i} of {len(rounds)}: {status}.")
    return {"ok": True, "status": status, "note": " ".join(story), "title": best["title"], "meta": best["meta"], "html": best["html"],
            "png": best["png"], "findings": blocking(best["check"]) + [f for f in best["judge"]], "rounds": rounds,
            "brief": brief_, "story": story_, "pattern": pat, "verdict": best["verdict"], "calls": calls, "best": best_i,
            "words": len(_Walk_words(best["html"]).split())}
