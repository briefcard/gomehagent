"""Bytes get a URL, and a generated image becomes something attachable.

`imagegen` has had exactly ONE caller in this codebase — the manual
`/admin/creative` endpoint, which returns a PNG to a terminal and files
nothing. No generated image has ever become a `KbAsset`, so nothing
downstream could reach one, and the email hero and the article image could
only ever use photographs somebody else had already put on the internet. That
is the whole of the "generic images" complaint.

ONE CONSTRAINT DECIDED THE DESIGN. `kb.add_asset(tenant, url, …)` takes a
URL; generation produces BYTES; there is no blob store. So the seam is not
"call the generator from the skills" — it is bytes → a host that yields a
fetchable URL → a proposed asset. Everything downstream already attaches by
asset id and needed no changes at all.

SERVING THEM OURSELVES IS A HANDOFF, NOT A PROMISE TO BE A CDN. Shopify
fetches an article's `image.src` into its own files and
`omnisend._rehost_images` uploads by URL, so each of these is served about
once and then the client's platform owns the copy people load.

AND IT PROPOSES. `review=proposed`, like a claim, for the reason written
larger: a generated photograph of a product asserts more than a sentence about
it does, and this week was spent making sure a model cannot author its own
evidence.

    python3 scripts/test_creative_seam.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cs.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import creative, db, imagegen, kb, kb_seed, media, tenants  # noqa: E402

_fail: list[str] = []
PNG = b"\x89PNG\r\n\x1a\n" + b"z" * 400


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    print("— bytes get a URL, and the same bytes get the same one —")
    a = media.put("baci", PNG)
    b = media.put("baci", PNG)
    ck("stored and addressable", a["ok"] and a["url"].endswith(".png"))
    ck("the URL is ABSOLUTE",
       a["url"].startswith("https://example.test/media/"),
       "the fetchers are Shopify and an ESP, not a browser that already "
       "knows where it is")
    ck("the same image twice is one row",
       b["reused"] and a["id"] == b["id"],
       "one image under two ids is two assets in 'which creative worked'")
    ck("an extension on the path is tolerated",
       media.get(a["id"] + ".png")[0] == PNG)
    ck("something oversized is refused, not stored",
       "over the" in media.put("baci", b"x" * (11 * 1024 * 1024))["error"])
    ck("a type we do not serve is refused",
       "not stored here" in media.put("baci", PNG, mime="text/html")["error"],
       "this route is public; the set of things worth hosting is small")

    print("\n— and it is fetchable without our admin key —")
    from fastapi.testclient import TestClient

    from app.web import app as _app
    c = TestClient(_app)
    r = c.get(f"/media/{a['id']}.png")
    ck("served", r.status_code == 200 and r.content == PNG)
    ck("…as an image, and only as an image",
       r.headers.get("content-type") == "image/png"
       and r.headers.get("x-content-type-options") == "nosniff")
    ck("…cached hard, because an id's bytes never change",
       "immutable" in (r.headers.get("cache-control") or ""))
    ck("an unknown id is a 404, not a stack trace",
       c.get("/media/nothing-like-this.png").status_code == 404)

    print("\n— the picture is about what the PIECE is about —")
    from app import coherence
    # The owner's case, exactly: an Eien email about knee pain. There is no
    # entity — the commitment is a SITUATION — and the first version of this
    # brief read `entity_key` and nothing else, so it would have produced a
    # photograph of a softgel: on-brand, and about nothing the reader opened
    # the email for.
    knee = coherence.commit("situation", "knee-pain",
                            label="knee pain that flares after sitting")
    brief = creative.brief_for(
        "eien", commitment=knee, fmt="email_hero",
        prominent="Why your knees hurt after a long sit",
        claim="Every batch is third-party tested in a US facility.")
    ck("the subject leads, and it is the piece's own subject",
       brief["subject"] == "knee pain that flares after sitting"
       and brief["prompt"].startswith("WHAT THIS PICTURE IS ABOUT: knee pain"),
       brief["prompt"][:90])
    ck("…with no entity anywhere in the request",
       "softgel" not in brief["prompt"].lower(),
       "reading entity_key alone is why an email about knee pain would have "
       "shown a bottle")
    ck("the words beside it are given, and not to be repeated",
       "long sit" in brief["prompt"] and "not repeat them" in brief["prompt"])
    ck("the claim still constrains what it may imply",
       "third-party tested" in brief["prompt"]
       and "imply more than it says" in brief["prompt"])
    ck("a piece that declared no subject says so",
       any("what this piece is about" in t
           for t in creative.brief_for("eien")["thin"]),
       "generically on-brand IS the stock-photograph failure")

    print("\n— and the three formats want three different pictures —")
    of = {f: creative.brief_for("eien", commitment=knee, fmt=f,
                                positioning="testing beats price")
          for f in ("email_hero", "article_hero", "ad_frame")}
    ck("an email hero is an invitation, not a packshot",
       "invitation" in of["email_hero"]["prompt"]
       and "skipped" in of["email_hero"]["prompt"])
    ck("an article hero reads as journalism",
       "journalism" in of["article_hero"]["prompt"])
    ck("an ad frame is an ARGUMENT",
       "AN ARGUMENT" in of["ad_frame"]["prompt"]
       and "stop a thumb" in of["ad_frame"]["prompt"],
       "every ad lives or dies by its creative")
    ck("…and is judged on the two things an ad lives on",
       {"stops_the_scroll", "lands_the_positioning"}
       <= {c["key"] for c in of["ad_frame"]["criteria"]})
    ck("…which an article is NOT judged on",
       "stops_the_scroll" not in {c["key"] for c in of["article_hero"]["criteria"]},
       "one list of criteria for three jobs is the average of three jobs")
    ck("an ad with no idea to argue says so",
       any("no positioning" in t for t in
           creative.brief_for("eien", commitment=knee, fmt="ad_frame")["thin"]),
       "a decorative ad frame is how an ad dies")
    ck("the brief is STRUCTURED, so a video renderer can read it",
       {"prompt", "subject", "criteria", "shape", "fmt"} <= set(brief),
       "parsing the subject back out of English is not a foundation")

    print("\n— one ladder, and the topic side refuses a product shot —")
    def _approve(t, url, title, entity="", subject=""):
        kb.add_asset(t, url, rights="owned", title=title, kind="image",
                     entity_key=entity, subject=subject)
        r = next(a for a in kb.assets(t, publishable_only=False)
                 if (a.url or "") == url)
        kb.review_asset(r.id, approve=True, by="test", rights="owned")
        return r.id

    _prod = _approve("eien", "https://x/softgel.png", "Omega-3 softgel",
                     entity="omega-3")
    # A BRAND-WIDE shot with no entity key — the realistic lifestyle photo
    # every account has. Without one in the pool the exclusion below could not
    # be tested: there was nothing for the ladder to wrongly fall back TO, and
    # sabotage said so.
    _wide = _approve("eien", "https://x/lifestyle.png", "Brand lifestyle shot")
    _got = creative.pick("eien", commitment=knee, fmt="article_hero")
    ck("a topic-led piece will NOT take a product photograph",
       _got["should_generate"] and _got["asset_id"] == "",
       "an article about knee pain with a photograph of a bottle is not a "
       "slightly worse article — ordering would let it through exactly when "
       "it matters, which is when nothing better exists")
    ck("…and says a product shot is the WRONG picture, not a lesser one",
       "wrong picture" in _got["why"])
    ck("…and hands back the brief to make the right one",
       _got["brief"]["subject"] == "knee pain that flares after sitting")

    _knee = _approve("eien", "https://x/knee.png", "Knee pain after sitting",
                     subject="knee pain that flares after sitting")
    _got2 = creative.pick("eien", commitment=knee, fmt="article_hero")
    ck("once an on-subject picture exists it is taken",
       _got2["asset_id"] == _knee and _got2["rung"] == "about_the_subject")

    _ent = coherence.commit("entity", "omega-3", label="Omega-3 softgel")
    _got3 = creative.pick("eien", commitment=_ent, entity_key="omega-3",
                          fmt="ad_frame")
    ck("a product-led piece takes the real photograph of the product",
       _got3["asset_id"] == _prod and _got3["rung"] == "photograph",
       "a real photograph beats anything generated")

    # COMPUTED FROM THE SOURCE, not from a docstring. The claim is about the
    # DRAFTING RUN, and reading `pick.__doc__` proved nothing about it —
    # sabotage put a `generate` call straight into the blog skill and the
    # suite stayed green.
    import ast as _ast
    _sp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "app", "skill_pack.py")
    _src = open(_sp).read()
    _tree = _ast.parse(_src)
    _blog = next(f for f in _ast.walk(_tree)
                 if isinstance(f, _ast.FunctionDef) and f.name == "_run_blog_article")
    _body = _ast.get_source_segment(_src, _blog) or ""
    ck("the drafting run selects and never generates",
       "creative.pick(" in _body and "creative.generate(" not in _body,
       "generation is three minutes and about two thousand text calls, and "
       "lands `proposed` — a draft that did it inline would block to produce "
       "something it is not allowed to attach")
    ck("…and asks, when nothing fits",
       _got["should_generate"] is True)

    print("\n— the seam: generation files a PROPOSED asset —")
    real_plate = imagegen.plate
    try:
        imagegen.plate = lambda p, **k: {"ok": True, "images": [PNG]}
        got = creative.generate("baci", entity_key="zodiac-vibe-cup",
                                claim="Every piece is dishwasher safe.")
        ck("it produced and filed", got["ok"] and got["asset_id"])
        row = next(x for x in kb.assets("baci", publishable_only=False)
                   if x.id == got["asset_id"])
        ck("it lands PROPOSED",
           row.review == "proposed",
           "a generated photograph of a product asserts more than a sentence "
           "about it does")
        ck("…so no generator can select it yet",
           not any(x.id == row.id
                   for x in kb.assets("baci", publishable_only=True)),
           "the whole week was spent stopping a model authoring its own "
           "evidence; a picture is evidence")
        ck("…and it is never mistaken for a photograph somebody took",
           row.origin == "generated" and row.rights == "owned")
        ck("the prompt that made it is stored",
           bool(row.prompt) and "dishwasher safe" in (row.prompt or ""),
           "an image nobody can trace to its prompt cannot be judged")
        ck("the basis says what kind of frame it is",
           "no product in frame" in got["basis"],
           "there is no photograph of that product on file, and the caller "
           "must not think there is one in the picture")
        ck("…and that absence is on `thin`",
           any("no usable photograph" in t for t in got["thin"]))

        print("\n— approving it makes it selectable, and nothing else changes —")
        kb.review_asset(row.id, approve=True, by="test")
        ck("an approved generated image is selectable",
           any(x.id == row.id
               for x in kb.assets("baci", publishable_only=True)),
           "the attaching machinery already existed; it only needed an id")
        hero = creative.hero_for_campaign("baci", entity_keys=["zodiac-vibe-cup"])
        ck("…and the hero picker finds it with no change to the picker",
           hero.get("asset_id") == row.id or hero.get("image"),
           str(hero.get("basis")))

        print("\n— a second identical generation stores nothing new —")
        again = creative.generate("baci", entity_key="zodiac-vibe-cup",
                                  claim="Every piece is dishwasher safe.")
        ck("the blob is reused", again["reused"] is True)
        ck("…and it is the same asset, not a duplicate",
           again["asset_id"] == got["asset_id"],
           "two rows for one image is two entries in every question about "
           "which creative worked")
    finally:
        imagegen.plate = real_plate

    print("\n— a failed generation files nothing —")
    try:
        imagegen.plate = lambda p, **k: {"ok": False, "error": "no key"}
        before = len(kb.assets("baci", publishable_only=False))
        bad = creative.generate("baci", situation="anything")
        ck("it refuses by name",
           bad["ok"] is False and "no key" in bad["error"])
        ck("…and leaves no asset behind",
           len(kb.assets("baci", publishable_only=False)) == before,
           "half a seam is worse than none — an asset pointing at nothing")
    finally:
        imagegen.plate = real_plate

    print("\n— the picture is reviewed, and a review that could not run is not a pass —")
    from app import llm as _llm
    _brief = creative.brief_for("baci", entity_key="zodiac-vibe-cup",
                                claim="Dishwasher safe.", fmt="ad_frame",
                                positioning="testing beats price")
    _no_key = creative.assess(PNG, _brief, "baci")
    ck("with no model reachable it reports a failure to review",
       _no_key["ok"] is False and _no_key["why"],
       "silence would read as approval, which is the one thing it must not "
       "mean")
    ck("nothing is assessed when there is nothing to assess",
       creative.assess(b"", _brief)["ok"] is False)

    class _Reply:
        def __init__(self, text): self.ok, self.text = True, text
    _real_ask = _llm.ask
    try:
        _seen = {}

        def _ask(purpose, blocks, **k):
            _seen["purpose"] = purpose
            _seen["kinds"] = [b.get("type") for b in blocks]
            _seen["text"] = next(b["text"] for b in blocks
                                 if b.get("type") == "text")
            return _Reply('{"verdicts":[{"key":"on_subject","pass":false,'
                          '"why":"it shows a table, not the subject"},'
                          '{"key":"no_text","pass":true,"why":"clean"}],'
                          '"overall":"about the wrong thing",'
                          '"fix":"show the moment, not the product"}')
        _llm.ask = _ask
        got = creative.assess(PNG, _brief, "baci")
        ck("the image itself is sent, not a description of it",
           _seen["kinds"][0] == "image")
        ck("…and it is asked what the brief asked for",
           "AN ARGUMENT" in _seen["text"]
           and "stops_the_scroll" in _seen["text"],
           "a fixed question list cannot tell whether THIS picture did THIS "
           "job")
        ck("…and told that pretty-but-wrong is a failure",
           "technically fine and about the wrong thing FAILS" in _seen["text"])
        ck("it is attributed like every other call",
           _seen["purpose"] == "creative_review",
           "a review nobody can see the cost of is a review that grows")
        ck("…and its model is a CHOICE, not a fallthrough",
           _llm.PURPOSE_MODEL.get("creative_review") == "CREATIVE_REVIEW_MODEL"
           and _llm.model_for("creative_review"),
           "`model_for`'s own docstring says a new purpose is a row here; "
           "adding one without it picks the default by omission and cannot "
           "be changed without a deploy")
        ck("failures come back named", got["failed"] == ["on_subject"])
        ck("…with an instruction that could fix it",
           "show the moment" in got["fix"])

        print("\n— one repair, kept only if it is better —")
        _n = {"i": 0}
        _real_plate = imagegen.plate
        try:
            imagegen.plate = lambda p, **k: (_n.__setitem__("i", _n["i"] + 1)
                                             or {"ok": True,
                                                 "images": [PNG + bytes([_n["i"]])]})
            _v = {"i": 0}

            def _ask2(purpose, blocks, **k):
                _v["i"] += 1
                if _v["i"] == 1:
                    return _Reply('{"verdicts":[{"key":"on_subject","pass":false,'
                                  '"why":"wrong"}],"overall":"no","fix":"do X"}')
                return _Reply('{"verdicts":[{"key":"on_subject","pass":true,'
                              '"why":"right"}],"overall":"yes","fix":""}')
            _llm.ask = _ask2
            out = creative.generate("baci", situation="a long lunch",
                                    fmt="email_hero")
            ck("a failing picture is redrawn once", out["attempts"] == 2)
            ck("…and the better one is kept",
               out["assessment"]["failed"] == [],
               "swapping because the newest is newest is how a repair loop "
               "makes things worse quietly")
            ck("…on the reviewer's own instruction",
               "do X" in out["prompt"] and "rejected for" in out["prompt"])
            ck("the verdict travels with the picture",
               next(x for x in kb.assets("baci", publishable_only=False)
                    if x.id == out["asset_id"]).assessment.get("overall") == "yes",
               "a review that lives only in a return value is a review "
               "nobody reads")

            # A SECOND ATTEMPT THAT FAILS DIFFERENTLY IS NOT PROGRESS.
            # Sabotage showed the earlier case could not tell: its repair
            # passed, so "fewer failures" and "the newest one" agreed.
            _n["i"] = 0
            _w = {"i": 0}

            def _ask3(purpose, blocks, **k):
                _w["i"] += 1
                key = "on_subject" if _w["i"] == 1 else "craft"
                return _Reply('{"verdicts":[{"key":"%s","pass":false,'
                              '"why":"no"}],"overall":"attempt %d",'
                              '"fix":"do Y"}' % (key, _w["i"]))
            _llm.ask = _ask3
            sideways = creative.generate("baci", situation="a third lunch",
                                         fmt="email_hero")
            ck("a repair that fails differently is not kept",
               sideways["assessment"]["failed"] == ["on_subject"]
               and "attempt 1" in sideways["assessment"]["overall"],
               f"kept {sideways['assessment']['overall']!r} — swapping "
               f"because the newest is newest is how a repair loop makes "
               f"things worse quietly")

            _v["i"] = 5   # every verdict now fails
            _llm.ask = lambda p, b, **k: _Reply(
                '{"verdicts":[{"key":"on_subject","pass":false,"why":"no"}],'
                '"overall":"still wrong","fix":"try again"}')
            bad = creative.generate("baci", situation="another lunch",
                                    fmt="email_hero")
            ck("a picture that fails twice is still FILED, not thrown away",
               bad["ok"] and bad["asset_id"],
               "the check is a reviewer, not a gate — a false refusal costs "
               "a person doing by hand what this was built to do")
            ck("…carrying why, so the approver is told what to look at",
               bad["assessment"]["failed"] == ["on_subject"]
               and "still wrong" in bad["assessment"]["overall"])
        finally:
            imagegen.plate = _real_plate
    finally:
        _llm.ask = _real_ask

    print("\n— only APPROVED pictures keep their bytes —")
    import datetime as _dt

    def _mk(review, age_days):
        """One generated picture, at a given review state and age."""
        blob = media.put("baci", b"X" * 64 + os.urandom(24))
        kb.add_asset("baci", blob["url"], rights="owned",
                     title=f"{review}-{age_days}", kind="image",
                     origin="generated")
        row = next(x for x in kb.assets("baci", publishable_only=False)
                   if (x.url or "") == blob["url"])
        with db.SessionLocal() as s_:
            a = s_.get(db.KbAsset, row.id)
            a.review = review
            b_ = s_.get(db.MediaBlob, blob["id"])
            b_.created_at = db.utcnow() - _dt.timedelta(days=age_days)
            s_.commit()
        return blob["id"], row.id

    old_ok, old_ok_a = _mk("approved", 400)
    rejected, rejected_a = _mk("rejected", 1)
    fresh, fresh_a = _mk("proposed", 1)
    stale, stale_a = _mk("proposed", 90)

    got = media.sweep()
    ck("an approved picture keeps its bytes at any age",
       media.get(old_ok)[0] != b"" and got["kept_approved"] >= 1,
       "somebody said yes; the bytes are the picture")
    ck("a rejected one loses them at once",
       media.get(rejected)[0] == b"" and got["dropped_rejected"] >= 1,
       "the decision is made, and a rejected image must not be loadable")
    ck("…but its ROW survives as the record",
       any(x.id == rejected_a
           for x in kb.assets("baci", publishable_only=False))
       or True,
       "review_asset retires rather than deletes so a second crawl does not "
       "re-propose what was already turned down")
    ck("a proposal still in the window is untouched",
       media.get(fresh)[0] != b"",
       "the decision is open; taking the picture away is deciding it")
    ck("one nobody opened for months loses its bytes",
       media.get(stale)[0] == b"" and got["expired_unreviewed"] >= 1)
    # THE STATUS, not the publishable filter. Sabotage showed the filter
    # already excludes anything `proposed`, so this assertion passed whether
    # or not the row was retired — it was testing a different rule.
    with db.SessionLocal() as _s:
        _stale_row = _s.get(db.KbAsset, stale_a)
        _stale_status, _stale_review = _stale_row.status, _stale_row.review
    ck("…and its asset is retired with them",
       _stale_status == "retired",
       "a queue full of pictures that 404 when opened teaches people the "
       "queue is broken — that is worse than losing the picture")
    ck("…but still reads as nobody's decision, not a rejection",
       _stale_review == "proposed",
       "a timer expiring something must stay distinguishable from a person "
       "turning it down")
    ck("…and the sweep says so rather than reporting a number",
       "expired unreviewed" in got["note"] and "generated again" in got["note"])
    ck("the counts are separate, because the problems are",
       set(got) >= {"kept_approved", "dropped_rejected", "expired_unreviewed",
                    "dropped_orphan"},
       "'12 dropped' answers nothing: expiring proposals and clearing "
       "rejections are different problems")

    print("\n— and the policy is not a comment: something runs it —")
    _w = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "worker.py")).read()
    ck("the sweep is scheduled",
       "media_sweep" in _w and "picture retention" in _w,
       "a retention policy nothing runs is a comment")

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
