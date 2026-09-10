"""The FAQ markup describes the page, and the angle's shape reaches the schema.

Owner, 2026-09-10, asking what would improve answer-engine ranking: the first
finding was not a missing strategy. `_run_blog_article` built its FAQ list as
`[{"question": q, "answer": ""} for q in questions]`, nothing ever filled an
answer, and the propose call filtered to `[f for f in faqs if f["answer"]]` —
so the list was empty on every article this system has ever written. No visible
FAQ block, no FAQPage schema. The comment two hundred lines above it calls that
"the AEO half, and it is not an extra".

The answers were never missing from the PAGE: the questions reach the drafter
as sections to answer, and it answers them. What was missing is the extractable
form. So they are read back off the body rather than written a second time —
structured data has to describe content a visitor can see, and a composed
second FAQ block would print every question twice.

The same joint was open one level up. `ARTICLE_ANGLES` already decides the
shape of each article — a walkthrough is numbered steps, a checklist is a list
— and that decision reached the prose and stopped.

    python3 scripts/test_the_page_says_what_it_answers.py
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pa.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
# A CMS THAT RESOLVES, so the run reaches the propose call. Without it
# `sites.backend()` refuses by name, the article is kept rather than queued,
# and the payload this suite exists to inspect is never built.
os.environ["SHOPIFY_STORES_JSON"] = (
    '{"baci": {"domain": "baci.myshopify.com", "token": "shpat_test"}}')
os.environ["SEO_SITES_JSON"] = (
    '{"baci": {"domain": "bacimilanousa.com", "platform": "shopify",'
    ' "creds_key": "baci", "database": "us"}}')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, seo_tools, sites, skill, skill_pack, systems, tenants  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


ANSWER = ("An acrylic jug is a shatter-resistant pitcher moulded from cast "
          "acrylic, used outdoors where glass is a hazard.")
CLEAN = ("Wash it by hand in warm water with a soft cloth. Skip the "
         "dishwasher, because the heat crazes the surface and the clouding "
         "that follows is permanent.")
BODY = f"""<h1>Acrylic jugs, and how to look after one</h1>
<p>The short answer is that they last for years if you keep them out of the dishwasher.</p>
<h2>What is an acrylic jug?</h2><p>{ANSWER}</p>
<h2>Our range</h2><p>This heading is not a question and must not be marked up as one.</p>
<h3>How do you clean an acrylic jug?</h3><p>{CLEAN}</p>
<h3>Why?</h3><p>Too short.</p>
<h2>Washing one, step by step</h2>
<ol><li>Rinse under warm water</li><li>Wipe with a soft cloth</li><li>Air dry upside down</li></ol>"""


def _setup(tenant: str) -> None:
    kb.ensure_brand(tenant, tenant.title())
    row = systems.find(tenant, "blog") or systems.create(tenant, "blog")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        b = s.get(db.KbBrand, tenant)
        b.positioning = "Mid-century tableware."
        b.voice = {"tone": ["plain"]}
        b.banned_claims = ["handmade"]
        s.commit()
    kb.add_claim(tenant, f"{tenant.title()} jugs are dishwasher safe.",
                 "lab report", [])


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— what the page answers is read off the page —")
    faqs = sites.faqs_from_body(BODY, ["what is an acrylic jug"])
    got = {f["question"]: f["answer"] for f in faqs}
    ck("a question-shaped heading and the text under it become one pair",
       got.get("What is an acrylic jug?") == ANSWER, str(list(got))[:90])
    ck("a heading that is not a question is left alone",
       "Our range" not in got)
    ck("a reworded question still counts — the page is what matters, not our list",
       "How do you clean an acrylic jug?" in got)
    ck("a heading with nothing under it is not an answer",
       "Why?" not in got, "a question with two words under it marks up nothing")

    long_body = ("<h2>Is it dishwasher safe?</h2><p>"
                 + ("No, and here is the reason it matters. " * 60) + "</p>")
    one = sites.faqs_from_body(long_body)[0]["answer"]
    ck("a long answer is cut at a sentence, never mid-clause",
       len(one) <= sites.FAQ_ANSWER_MAX and one.endswith("."), f"{len(one)} chars")

    many = "".join(f"<h3>Question {i}?</h3><p>{ANSWER}</p>" for i in range(30))
    ck("and the page is not turned into nothing but markup",
       len(sites.faqs_from_body(many)) == sites.FAQ_MAX,
       f"{len(sites.faqs_from_body(many))} of 30")

    print("\n— the shape the angle chose reaches the schema —")
    walk = sites.schema_for_angle("walkthrough", "Washing a jug", BODY)
    ck("a walkthrough's numbered steps become HowTo steps",
       [s["@type"] for s in walk] == ["HowTo"]
       and [s["text"] for s in walk[0]["step"]][0] == "Rinse under warm water"
       and len(walk[0]["step"]) == 3, str(walk)[:80])
    checklist_body = "<ul><li>Check the rim</li><li>Check the handle</li></ul>"
    ck("a checklist's items become an ItemList",
       [s["@type"] for s in sites.schema_for_angle(
           "checklist", "Before you buy", checklist_body)] == ["ItemList"])
    ck("an angle with no shape of its own marks up nothing",
       sites.schema_for_angle("definitive", "X", BODY) == [])
    ck("an angle that was asked for and NOT delivered marks up nothing",
       sites.schema_for_angle("walkthrough", "X", "<p>No list here.</p>") == [],
       "a HowTo whose steps are not on the page is a claim about a page "
       "that does not exist")

    print("\n— and both reach the article that ships —")
    _setup("baci")
    payload: dict = {}
    real_propose = seo_tools._propose

    def _capture(name, args, profile):
        payload.update(args)
        return real_propose(name, args, profile)
    seo_tools._propose = _capture
    # THE DESTINATION, stubbed. `sites.ensure_blog` asks the live store which
    # blog to publish into, and a suite has no store — without this the run
    # stops one line before the payload this suite exists to inspect.
    real_blog, real_note = sites.ensure_blog, sites.blog_note
    sites.ensure_blog = lambda t: {"ok": True, "blog_id": "b1"}
    sites.blog_note = lambda got: ""
    skill_pack._draft_article_live = lambda *a, **k: (BODY, "")
    try:
        skill.run("blog_article", "baci", keyword="acrylic jug",
                  role="pillar", angle="walkthrough")
    finally:
        seo_tools._propose = real_propose
        sites.ensure_blog, sites.blog_note = real_blog, real_note

    ck("the propose payload carries real question-and-answer pairs",
       len(payload.get("faqs") or []) >= 2
       and all(f["answer"] for f in payload["faqs"]),
       f"{len(payload.get('faqs') or [])} pair(s) — this was 0 on every "
       f"article ever written")
    ck("and the angle's own schema rides with it",
       [s["@type"] for s in (payload.get("jsonld") or [])] == ["HowTo"],
       str(payload.get("jsonld"))[:60])

    fields = seo_tools._build_content_fields(
        sites.get("baci"), dict(payload))
    structured = fields.get("structured_data") or []
    if not structured and "<script" in (fields.get("body_html") or ""):
        import json as _json
        import re as _re
        structured = _json.loads(_re.search(
            r'<script type="application/ld\+json">(.*?)</script>',
            fields["body_html"], _re.S).group(1))
    ck("what publishes carries the FAQPage and the HowTo together",
       {s["@type"] for s in structured} == {"FAQPage", "HowTo"},
       str([s["@type"] for s in structured]))
    ck("every marked-up answer is visible in the body a reader gets",
       all(f["answer"][:40] in fields["body_html"] for f in payload["faqs"]),
       "markup that describes content nobody can see is a page claiming "
       "something it does not have")
    ck("and nothing is printed twice",
       fields["body_html"].count("What is an acrylic jug?") == 1,
       "a composed FAQ block on top of the article's own sections would "
       "duplicate every question and answer")

    # THE OTHER CALLER, and it needs the opposite. The agent authors pairs
    # beside a body that does not contain them; without a block they would be
    # marked up and invisible, which is the same offence as marking up an FAQ
    # that does not exist, pointed the other way.
    authored = seo_tools._build_content_fields(sites.get("baci"), {
        "title": "Jugs", "body_html": "<h1>Jugs</h1><p>No questions here.</p>",
        "faqs": [{"question": "Is it dishwasher safe?", "answer": "No."}]})
    ck("a pair the body does NOT contain is printed, so the markup stays true",
       "Is it dishwasher safe?" in authored["body_html"]
       and "Frequently asked questions" in authored["body_html"])

    print("\n— an article briefed to answer questions and answering none says so —")
    notes: list[str] = []
    real_note = skill_pack.Context.note
    skill_pack.Context.note = lambda self, msg: notes.append(str(msg))
    skill_pack._draft_article_live = lambda *a, **k: (
        "<h1>Jugs</h1><p>" + ("A statement, not a question. " * 12) + "</p>", "")
    try:
        skill.run("blog_article", "baci", keyword="acrylic jug", role="pillar")
    finally:
        skill_pack.Context.note = real_note
    ck("it names what is missing and what it costs",
       any("no FAQ markup" in n for n in notes)
       or not any("answered as sections" in n for n in notes),
       str([n[:70] for n in notes])[:200])

    print("\n— computed: nothing builds an answer it never fills —")
    bad = []
    for path in sorted((ROOT / "app").glob("*.py")):
        for n in ast.walk(ast.parse(path.read_text())):
            if not isinstance(n, ast.Dict):
                continue
            keys = [k.value for k in n.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if "question" not in keys or "answer" not in keys:
                continue
            val = n.values[keys.index("answer")]
            if isinstance(val, ast.Constant) and val.value == "":
                bad.append(f"{path.name}:{n.lineno}")
    ck("no FAQ pair is constructed with an empty answer",
       not bad, "; ".join(bad) + " — the exact shape of the defect this "
       "suite exists for: a list built empty, never filled, and filtered "
       "away at the end")

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
