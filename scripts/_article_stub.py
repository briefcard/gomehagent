"""THE ARTICLE MAKER, FAKED — for suites that exercise the blog system
without a model.

`blog_article` writes through `articles.run` since 2026-09-22 (the rivals
read, the story decided, the article judged). A suite with no model cannot
run that, and every blog suite written before it stubs the old blind
drafter, `skill_pack._draft_article_live`. This stand-in keeps those
fixtures meaning what they meant: `articles.run` returns whatever that
drafter returns, wrapped in the maker's shape, marked publishable so the
suite reaches the parts it is actually about (the review, the repair, the
refresh, the ship). Nothing here is a path the app can take.
"""
from __future__ import annotations


def install(status: str = "publishable") -> None:
    from app import articles, skill_pack

    def fake_run(tenant, keyword, *, role="support", entity_key="", questions=None, rival_urls=None,
                 approach_url="", products=None, collections=None, links=None, angle="", angle_brief="",
                 notes="", progress=None, **kw):
        # the old drafter's signature, so a suite's stub still sees what it
        # asserted on: the bundle (with the owner's notes folded into its
        # rules block, as the repair path did), the angle, the links
        from app import resolve as _rs
        bundle = _rs.resolve(tenant, system="blog", tier=3, entity_key=entity_key)
        if notes:
            bundle = {**bundle, "revision_notes": notes,
                      "rules": {**bundle.get("rules", {}),
                                "block": str(bundle.get("rules", {}).get("block", "")) + "\n\n" + notes}}
        body, why_not = skill_pack._draft_article_live(
            bundle, keyword, role, angle, list(questions or []), list(links or []), None, [])
        if not body:
            return {"ok": False, "status": articles.FAILED, "note": why_not or "no article", "rounds": []}
        title = skill_pack._h1_of(body) or (keyword[:1].upper() + keyword[1:])
        return {"ok": True, "status": status, "note": "made by the suite's stand-in maker.",
                "title": title, "meta": f"{title[:150]}", "html": body, "png": b"",
                "findings": [], "rounds": [{"n": 0, "blocking": 0, "judged": True}],
                "brief": {"beat": "the stand-in", "length_words": 1400, "rivals": []},
                "story": {"hook": title, "beats": [], "turned": []},
                "pattern": articles.PATTERN_DEFAULT, "verdict": {"would_publish": status == "publishable", "one_pattern": True},
                "calls": 0, "best": 0, "words": len(body.split())}
    articles.run = fake_run
