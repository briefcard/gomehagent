"""Pictures inside the article — the drafter names the place, never the picture.

Owner, 2026-09-02: *"Yes we want in-article images."*

The featured image was already selected and pushed; the BODY had nothing —
`campaign_email` has a block model (`hero`, `products`) and `blog_article`
emitted one flat HTML body whose prompt said "no image tags".

THE MODEL NAMES THE PLACE AND THE SUBJECT; IT NEVER NAMES THE PICTURE. The same
rule the internal links already follow, for the same reason: a URL from a model
is one nobody can vouch for, and `_link_grounding` exists because that failure
shipped once. Here it cannot happen by construction — the marker carries prose,
and every `src` comes from `creative.pick`, which selects only approved assets.

FOUR THINGS THAT MAKE IT SAFE TO SHIP, each asserted:

  · A marker with nothing behind it is REMOVED, and recorded as a brief — the
    same queue the hero's absence feeds. An article whose markers were all
    dropped still reads correctly, which is why the prompt forbids referring
    to a picture in the prose.
  · An HTML COMMENT, so a missed marker renders as nothing. `[IMAGE: …]` would
    render as literal text on a live page — the failure mode of a placement
    system has to be an absent picture, never visible scaffolding.
  · The hero is never repeated. The same photograph under the headline and
    again halfway down reads as a rendering fault.
  · Alt text comes from the ASSET, not the marker. The marker is what the
    writer wanted; the alt has to describe what is actually there.

Run: python3 scripts/test_article_images.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ai.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import creative, db, kb, skill_pack, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


BODY = """<h1>Outdoor dining</h1>
<p>Answer first.</p>
<!--IMAGE: a folding table set for eight in a garden-->
<h2>Setting the table</h2>
<p>More prose.</p>
<!--IMAGE: stacked melamine plates on a tray-->
<p>Closing.</p>
"""


def _stub(results):
    """`creative.pick` returns one dict per call, in order."""
    calls = list(results)
    seen = []

    def _pick(tenant, **kw):
        seen.append(kw)
        return calls.pop(0) if calls else {"asset_id": "", "url": "",
                                           "why": "nothing approved fits"}
    creative.pick = _pick
    return seen


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    real = creative.pick

    print("— the marker becomes a real picture, from a governed source —")
    seen = _stub([
        {"asset_id": "a1", "url": "https://cdn.example/one.png",
         "alt": "A garden table laid for eight", "rung": "photograph",
         "why": "approved photo"},
        {"asset_id": "a2", "url": "https://cdn.example/two.png",
         "alt": "Melamine plates stacked", "rung": "photograph", "why": "ok"},
    ])
    html, placed, wanted = skill_pack.place_images(BODY, "baci")
    ck("both markers are filled", len(placed) == 2, str(placed))
    ck("  no marker survives into the body",
       "<!--IMAGE" not in html and "IMAGE:" not in html, html[:120])
    ck("  and the src is the asset's, not the model's",
       'src="https://cdn.example/one.png"' in html,
       "the model never supplies a URL — it cannot, the marker is prose")
    ck("  each is a figure, not a bare img",
       html.count("<figure>") == 2)
    ck("  and lazy, because a body image is below the fold by definition",
       html.count('loading="lazy"') == 2)

    print()
    print("— the subject reaches the picker as what the passage is about —")
    ck("the marker's words are what it searched on",
       seen[0].get("prominent") == "a folding table set for eight in a garden",
       str(seen[0]))
    ck("  and it asked for the BODY format, not the hero's",
       seen[0].get("fmt") == "article_body",
       f'{seen[0].get("fmt")} — the hero summarises the article, a body image '
       f'makes one passage concrete; one rule for both puts the same picture '
       f'in twice')
    ck("  which is a format the ladder actually knows",
       "article_body" in creative.FORMATS,
       "an unknown fmt falls back to email_hero, which judges a picture as an "
       "invitation to a reader who has just opened something")

    print()
    print("— alt text describes what is THERE, not what was wanted —")
    ck("it comes from the asset",
       'alt="A garden table laid for eight"' in html,
       "the marker said 'a folding table set for eight in a garden'; a screen "
       "reader must be told about the picture that was chosen")

    print()
    print("— a marker with nothing behind it is removed, and recorded —")
    _stub([])
    html2, placed2, wanted2 = skill_pack.place_images(BODY, "baci")
    ck("nothing is placed", placed2 == [])
    ck("  the markers are gone", "IMAGE" not in html2, html2[:100])
    ck("  the prose is intact",
       "<h2>Setting the table</h2>" in html2 and "<p>Closing.</p>" in html2,
       "an article whose markers were all dropped must still read correctly")
    ck("  and each subject is reported as a brief",
       wanted2 == ["a folding table set for eight in a garden",
                   "stacked melamine plates on a tray"],
       f"{wanted2} — a picture somebody wanted, named, reaching the same "
       f"queue the hero's absence feeds")

    print()
    print("— the hero is never repeated —")
    _stub([
        {"asset_id": "hero", "url": "https://cdn.example/hero.png",
         "alt": "The hero", "rung": "photograph", "why": "x"},
        {"asset_id": "a9", "url": "https://cdn.example/nine.png",
         "alt": "Something else", "rung": "photograph", "why": "x"},
    ])
    html3, placed3, wanted3 = skill_pack.place_images(
        BODY, "baci", used={"hero"})
    ck("the hero's asset is refused in the body",
       all(p["asset_id"] != "hero" for p in placed3), str(placed3))
    ck("  and that place is reported as still wanting one",
       len(wanted3) == 1, str(wanted3))
    ck("  while the other place is filled",
       len(placed3) == 1 and placed3[0]["asset_id"] == "a9",
       "the same photograph under the headline and again halfway down reads "
       "as a rendering fault, not as illustration")

    print()
    print("— an article is not a gallery —")
    many = "<p>a</p>\n" + "\n".join(
        f"<!--IMAGE: subject {i}-->" for i in range(6))
    _stub([{"asset_id": f"m{i}", "url": f"https://cdn.example/{i}.png",
            "alt": f"alt {i}", "rung": "photograph", "why": "x"}
           for i in range(6)])
    html4, placed4, wanted4 = skill_pack.place_images(many, "baci")
    ck(f"at most {skill_pack.MAX_BODY_IMAGES} are placed",
       len(placed4) == skill_pack.MAX_BODY_IMAGES, str(len(placed4)))
    ck("  and the rest are still named rather than dropped silently",
       len(wanted4) == 4, str(wanted4))

    print()
    print("— an attribute cannot be broken out of —")
    _stub([{"asset_id": "q", "url": 'https://cdn.example/a"b.png',
            "alt": 'He said "hello" <b>', "rung": "photograph", "why": "x"}])
    html5, _p, _w = skill_pack.place_images(
        "<p>x</p>\n<!--IMAGE: a thing-->\n", "baci")
    ck("quotes in the alt are escaped",
       '&quot;hello&quot;' in html5 and 'alt="He said "' not in html5,
       html5.strip())
    ck("  and so are angle brackets",
       "&lt;b&gt;" in html5 and "<b>" not in html5,
       "an unescaped alt puts prose into the markup and a tag into the page")

    print()
    print("— the drafter is told the contract —")
    sysprompt = skill_pack._ARTICLE_SYSTEM
    ck("it is told to mark the place, not write the tag",
       "<!--IMAGE:" in sysprompt and "no image tags" in sysprompt.lower(),
       "the one rule that makes a hallucinated src impossible")
    ck("  and never to refer to a picture in the prose",
       "never refer to a picture" in " ".join(sysprompt.lower().split()),
       # The rule wraps across a line in the prompt, so the assertion has to
       # normalise whitespace — the trap this repo has hit before on rendered
       # prose, hit again on a prompt.
       "every marker can be dropped, so prose that points at one would be "
       "left pointing at nothing")

    creative.pick = real
    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
