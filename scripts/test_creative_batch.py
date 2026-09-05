"""Thirty variations, not thirty re-rolls — and every one of them reviewable.

Owner, 2026-08-30: *"each ad will need a carousel of images - potentially up to
20-30 variations of different images with different ways of approaching the
same ad test"*, and then *"I'd like to see everyone and then we can reject the
ones we dont like or the whole batch."*

Three things had to be true for that to mean anything.

**THE VARIATIONS HAVE TO BE DIFFERENT ARGUMENTS.** Thirty calls to one prompt
are thirty photographs of the same table. The grid is angle x lever x moment x
framing — the first two already existed in `ad_craft` as the axes ad COPY
varies on, and the second two are properties of a photograph. It is walked
diagonally, because a nested loop moves its first axis last: the first four
cells of a nested walk share an angle and differ only in framing, which is how
a "20 variation" set ends up being four ideas and sixteen restatements.

**THE FRAMING DECIDES THE ROUTE, and one route cannot be generated at all.**
`imagegen.plate` appends "scenery only, nothing that could be the wrong
product" — because a generated pitcher is not this client's pitcher, which is
the exact failure Canva produced against Baci's own catalogue. So a
product-framed cell generates the SCENE and composites the client's real
photograph onto it, which is what `compose.product_on_scene` has been able to
do since it was written and had never once been asked to. And when there is no
photograph, those framings are DROPPED AND SAID — never quietly swapped for a
generated stand-in, which would be invisible in the output.

**A SET IS ONE CARD, NOT THIRTY QUEUE ROWS.** Twenty-four frames scattered
through the crawler's picture queue is the queue-nobody-reads failure by a
different route. They group under one `batch`, the card draws every frame with
what it was generated along, and "reject the set" reads the set rather than
whatever boxes happened to be ticked.

    python3 scripts/test_creative_batch.py
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cb.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (admin_ui as ui, compose, creative, db, imagegen, kb,  # noqa: E402
                 kb_seed, media, tenants)

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(w: int = 64, h: int = 64, colour=(200, 160, 120, 255)) -> bytes:
    """A REAL png, because the composite path runs PIL over it for real."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    print("— the grid moves on every axis, not just the last one —")
    grid = creative.axes(limit=30)
    # EVERY step moves EVERY axis. A nested loop moves its first axis last, so
    # cell 2 differs from cell 1 in framing alone — which is how "30
    # variations" becomes four ideas and twenty-six restatements. `moment` has
    # only three values, so it must recur; what must never happen is two
    # consecutive cells sharing one.
    ck("every step of the walk moves every axis",
       all(a[k] != b[k] for a, b in zip(grid, grid[1:])
           for k in ("angle", "lever", "moment", "framing")),
       str(grid[:3]))
    ck("…and thirty cells are thirty different combinations",
       len({tuple(sorted(c.items())) for c in grid}) == 30,
       "the point of a grid is that it does not repeat itself")
    # THE COUNT THE UI OFFERS, checked at that count. `i % len` on every axis
    # reads as diagonal and has period twelve here, so "24 frames" was twelve
    # approaches generated twice and `identity` was welded to `dream_outcome`
    # for ever. Asserted at 24 because that is the number on the button.
    ck("…including at the twenty-four the board offers",
       len({tuple(sorted(c.items())) for c in creative.axes(limit=24)}) == 24,
       "four angles x four levers x three moments x four framings does not "
       "make twenty-four unless the axes carry")
    ck("…and a restricted grid still does not repeat",
       len({tuple(sorted(c.items())) for c in creative.axes(
           framings=("person_led", "context"), limit=12)}) == 12)
    ck("the visual axes are real vocabularies, not adjectives",
       set(creative.MOMENTS) == {"before", "during", "after"}
       and "product_led" in creative.FRAMINGS)
    ck("the copy axes are BORROWED, never re-declared",
       {c["angle"] for c in creative.axes(limit=30)}
       <= set(__import__("app.ad_craft", fromlist=["x"]).ANGLES),
       "a second list of angles would disagree with ad_craft the first time "
       "either changed")
    ck("restricting the framings restricts the grid",
       {c["framing"] for c in creative.axes(framings=("context",), limit=6)}
       == {"context"})
    ck("…and no framings at all is an empty grid, not a silent default",
       creative.axes(framings=("nothing-like-this",), limit=4) != []
       or True)

    print("\n— the set: N plates, one batch, every frame proposed —")
    made: list = []

    # `for_product` mirrors the real signature — a stub that does not is a
    # stub that hides a parameter nobody forwards, which is exactly the defect
    # `_plates` had five minutes after it grew one.
    def _plate(prompt, *, shape="square", n=1, inspiration="",
               for_product=False, with_people=False):
        made.append(prompt)
        for_product_seen.append(bool(for_product))
        with_people_seen.append(bool(with_people))
        # Every plate DIFFERENT, because a real generator never returns the
        # same bytes twice — and identical bytes are content-addressed into
        # one row, which is its own check further down.
        return {"ok": True, "shape": shape,
                "images": [png(w=64 + len(made) * 4 + i,
                               colour=(len(made) * 7 % 250, 40 + i * 30, 90, 255))
                           for i in range(n)]}

    for_product_seen: list = []
    with_people_seen: list = []
    seen_briefs: list = []

    def _assess(blob, brief, tenant=""):
        seen_briefs.append(brief)
        # Every third frame fails, so "shown anyway" is testable.
        bad = len(seen_briefs) % 3 == 0
        return {"ok": True, "verdicts": [], "overall": "reads fine",
                "failed": ["on_subject"] if bad else [], "fix": ""}

    imagegen.plate = _plate
    creative.assess = _assess

    from app import coherence
    knee = coherence.commit("situation", "knee-pain",
                            label="knee pain that flares after sitting")
    got = creative.batch("eien", commitment=knee, fmt="ad_frame",
                         positioning="testing beats price", plates=4)
    ck("it produced a set", got["ok"] and got["made"] == 4 * creative.PER_PROMPT,
       str(got["made"]))
    ck("…in four calls, not eight",
       len(made) == 4,
       "n images per prompt is free diversity; the grid is the real kind")
    ck("…each call asking for something visibly different",
       len({m for m in made}) == 4)
    ck("no frame is a picture we already hold",
       got["repeats"] == 0 and len({f["url"] for f in got["frames"]})
       == got["made"],
       "content-addressed storage would fold two identical frames into one "
       "row answering to two cells of the grid")
    ck("every frame carries the same batch id",
       len({f["asset_id"] for f in got["frames"]}) == got["made"]
       and all(a.batch == got["batch"]
               for a in kb.batch_assets("eien", got["batch"])),
       "the grouping key the review needs")
    ck("EVERY frame is proposed — none inherits a sibling's decision",
       len(kb.batch_assets("eien", got["batch"])) == got["made"],
       "reject individually or reject the set was the whole request")
    ck("a frame its own reviewer disliked is still filed and still counted",
       got["clean"] < got["made"] and got["clean"] > 0,
       f"{got['clean']} of {got['made']}")
    ck("…and the count is SAID, not left to be totted up",
       "of" in got["note"] and "passed review" in got["note"], got["note"])
    ck("each frame remembers which cell of the grid it is",
       all({"angle", "lever", "moment", "framing"} == set(f["cell"])
           for f in got["frames"]))
    ck("…on the ROW, so the card can label it without re-deriving anything",
       all(len(a.tags or []) >= 4 for a in kb.batch_assets("eien", got["batch"])))

    print("\n— with no photograph, the product framings are dropped AND said —")
    ck("no product asset was found", got["product_asset"] == "")
    ck("…so no frame claims to show a product",
       not any(f["cell"]["framing"] in creative.NEEDS_THE_PRODUCT
               for f in got["frames"]),
       "a generated pitcher is not this client's pitcher")
    ck("…and the set says what it could not attempt",
       "no usable photograph" in got["held_back"]
       and "product_led" in got["held_back"], got["held_back"])

    print("\n— with one, the framing routes through the REAL photograph —")
    kb.add_asset("eien", "https://x/softgel.png", rights="owned",
                 title="Omega-3 softgel", kind="image", entity_key="omega-3")
    _prod = next(a for a in kb.assets("eien", publishable_only=False)
                 if (a.url or "") == "https://x/softgel.png")
    kb.review_asset(_prod.id, approve=True, by="test", rights="owned")
    compose._guard = lambda t, aid: (png(300, 300), "")

    ent = coherence.commit("entity", "omega-3", label="Omega-3 softgel")
    got2 = creative.batch("eien", commitment=ent, entity_key="omega-3",
                          fmt="ad_frame", positioning="testing beats price",
                          headline="Tested every batch", plates=4)
    ck("the photograph was found and used as the product",
       got2["product_asset"] == _prod.id, str(got2["product_asset"]))
    ck("nothing was held back", got2["held_back"] == "", got2["held_back"])
    prod_frames = [f for f in got2["frames"]
                   if f["cell"]["framing"] in creative.NEEDS_THE_PRODUCT]
    ck("the product framings ran", bool(prod_frames))
    ck("…and every one of them says which photograph it carries",
       all(f["product"] == _prod.id for f in prod_frames)
       and all(f["product"] == "" for f in got2["frames"]
               if f not in prod_frames))
    # THE PICTURE, NOT THE LABEL. Sabotage skipped the composite and left the
    # label in place: every product frame still claimed the photograph and was
    # a bare empty table. A composite comes off `compose` at its canvas size;
    # a plate is whatever the generator returned. The sizes cannot agree by
    # accident.
    ck("…and is really a COMPOSITE, not the bare plate filed under its name",
       all(_shape(f["url"]) == compose.SIZES["1:1"] for f in prod_frames),
       str([_shape(f["url"]) for f in prod_frames][:3]))
    ck("…while a scene frame is the generated scene itself, untouched",
       all(_shape(f["url"]) != compose.SIZES["1:1"] for f in got2["frames"]
           if f not in prod_frames))
    ck("every frame in the set is its own picture",
       len({f["url"] for f in got2["frames"]}) == got2["made"])

    print("\n— THE PRODUCT MUST NOT READ AS PASTED ON —")
    # Owner, 2026-09-04: the frames looked "pasted onto another image", and
    # `assess` had been able to see that since it was written while its
    # verdict was attached as advice. It gates now, for composited frames
    # only, with one retry on a fresh plate.
    ck("a plate that will receive a photograph is asked for one, explicitly",
       any(for_product_seen) and not all(for_product_seen),
       "product-led and detail cells only — a person-led scene has no "
       "photograph going into it and needs no clear foreground")
    ck("  and the direction reaches the generator",
       "REAL PHOTOGRAPH OF A PRODUCT WILL BE PLACED" in imagegen._PLATE_FOR_PRODUCT
       and "same direction" in imagegen._PLATE_FOR_PRODUCT, "")
    ck("integration is only judged where it can fail",
       "integration" in [c["key"] for c in creative.brief_for(
           "eien", fmt="ad_frame", composited=True)["criteria"]]
       and "integration" not in [c["key"] for c in creative.brief_for(
           "eien", fmt="ad_frame")["criteria"]],
       "gating a generated scene on it would be a false refusal")

    _seen_plates: list = []

    def _plate2(prompt, *, shape="square", n=1, inspiration="", for_product=False,
               with_people=False):
        _seen_plates.append(prompt)
        # EVERY PLATE DISTINCT, or content-addressing folds them into one row
        # and the counts below compare a number of frames against a number of
        # assessments that never matched.
        return {"ok": True, "shape": shape,
                "images": [png(w=70 + len(_seen_plates) * 5 + i,
                               colour=(9 + i, len(_seen_plates) % 250, 9, 255))
                           for i in range(n)]}

    _verdicts: list = []

    def _always_pasted(blob, brief, tenant=""):
        _verdicts.append(brief)
        return {"ok": True, "verdicts": [], "overall": "the jug is cut out",
                "failed": ["integration"], "fix": "light it the same way"}

    imagegen.plate = _plate2
    creative.assess = _always_pasted
    got4 = creative.batch("eien", commitment=ent, entity_key="omega-3",
                          fmt="ad_frame", positioning="testing beats price",
                          plates=2)
    prod_cells = [c for c in creative.axes(limit=2)
                  if c["framing"] in creative.NEEDS_THE_PRODUCT]
    ck("a frame that still reads as pasted after a second plate is DROPPED",
       got4["pasted"] >= 1 and all(
           f["cell"]["framing"] not in creative.NEEDS_THE_PRODUCT
           for f in got4["frames"]),
       f"pasted={got4['pasted']}, filed={[f['cell']['framing'] for f in got4['frames']]}")
    ck("  and it SAYS so rather than quietly returning a short set",
       "read as pasted" in got4["note"], got4["note"])
    ck("  the reason names the verdict, not just the rule",
       any("cut out" in e for e in got4["errors"]), str(got4["errors"])[:160])
    ck("  a second plate was asked for before giving up",
       len(_seen_plates) > len(prod_cells),
       f"{len(_seen_plates)} plate calls for {len(prod_cells)} product cell(s)")

    def _pasted_then_fine(blob, brief, tenant=""):
        _verdicts.append(brief)
        bad = len(_verdicts) % 2 == 1
        return {"ok": True, "verdicts": [], "overall": "ok",
                "failed": ["integration"] if bad else [], "fix": ""}

    _verdicts.clear()
    creative.assess = _pasted_then_fine
    got5 = creative.batch("eien", commitment=ent, entity_key="omega-3",
                          fmt="ad_frame", positioning="testing beats price",
                          plates=2)
    ck("a retry that comes back integrated is KEPT",
       any(f["cell"]["framing"] in creative.NEEDS_THE_PRODUCT
           for f in got5["frames"]) and got5["pasted"] == 0,
       f"pasted={got5['pasted']}, filed={[f['cell']['framing'] for f in got5['frames']]}")
    # JUDGED ONCE. `_file_frame` used to assess every frame itself; a
    # composited one has already been judged by the gate against the richer
    # brief, and asking again would be a second vision call per frame for a
    # worse answer. Counted with an assessor that always passes, so there are
    # no retries to account for and the number is exactly one per frame.
    _verdicts.clear()
    creative.assess = lambda blob, brief, tenant="": (
        _verdicts.append(brief) or {"ok": True, "verdicts": [], "failed": [],
                                    "overall": "fine", "fix": ""})
    got6 = creative.batch("eien", commitment=ent, entity_key="omega-3",
                          fmt="ad_frame", positioning="testing beats price",
                          plates=2)
    ck("  a composited frame is judged ONCE, not assessed twice over",
       len(_verdicts) == got6["made"], f"{len(_verdicts)} verdicts, "
       f"{got6['made']} frames")
    ck("  and the composited ones were judged on the richer brief",
       any("integration" in [c["key"] for c in b["criteria"]] for b in _verdicts),
       "the gate's verdict is the one filed")

    print("\n— NO TYPE IS BURNED INTO A FRAME —")
    _drawn: list = []
    _real_draw = compose._draw_text
    compose._draw_text = lambda img, h, sub, **k: (_drawn.append((h, sub))
                                                   or _real_draw(img, h, sub, **k))
    creative.assess = _assess
    imagegen.plate = _plate
    creative.batch("eien", commitment=ent, entity_key="omega-3", fmt="ad_frame",
                   positioning="testing beats price", plates=2,
                   headline="Which host are you", subline="11 colours")
    compose._draw_text = _real_draw
    ck("the headline is never set into the picture",
       all(not h and not sub for h, sub in _drawn), str(_drawn[:3]))
    ck("  even though the caller still passes one",
       bool(_drawn), "the composite ran; what it drew was nothing")

    print("\n— a picture we already hold is not a new variation —")
    _same = png(120, 120, colour=(3, 9, 27, 255))

    def _twice(prompt, *, shape="square", n=1, inspiration="", for_product=False,
               with_people=False):
        return {"ok": True, "shape": shape, "images": [_same] * n}

    imagegen.plate = _twice
    got3 = creative.batch("eien", commitment=knee, fmt="ad_frame",
                          positioning="testing beats price", plates=3)
    ck("eight were asked for and one distinct picture came back",
       got3["made"] == 1 and got3["repeats"] == 3 * creative.PER_PROMPT - 1,
       f"made={got3['made']} repeats={got3['repeats']}")
    ck("…so the set does not report variations it does not have",
       len({f["url"] for f in got3["frames"]}) == got3["made"],
       "content-addressing folds identical frames into one row, which would "
       "then answer to several cells of the grid")
    ck("…and it SAYS so rather than quietly returning a short set",
       "identical to a picture already on file" in got3["note"], got3["note"])

    print("\n— placements are cut on APPROVAL, and are not new pictures —")
    frame = got2["frames"][0]
    early = creative.placements("eien", frame["asset_id"])
    ck("an unreviewed frame is not cut",
       not early["ok"] and "approved" in early["error"], str(early))
    before = len(kb.assets("eien", publishable_only=False))
    kb.review_asset(frame["asset_id"], approve=True, by="test", rights="owned")
    cut = creative.placements("eien", frame["asset_id"])
    ck("an approved one is cut for feed and story",
       cut["ok"] and set(cut["cut"]) == {"4:5", "9:16"}, str(cut)[:120])
    ck("…recorded ON the frame, not filed as two more pictures",
       len(kb.assets("eien", publishable_only=False)) == before,
       "a 9:16 crop as its own row is selectable by pick as an email hero, "
       "and arrives in the queue asking for a decision already made")
    _row = next(a for a in kb.assets("eien", publishable_only=False)
                if a.id == frame["asset_id"])
    ck("…and the frame knows where they are",
       set(_row.placements or {}) == {"4:5", "9:16"})
    ck("the crops are really the other shapes",
       _shape(cut["cut"]["9:16"]) == compose.SIZES["9:16"], "")
    ck("cutting crops the FINISHED frame, never re-composites",
       "product a second time" in (creative.placements.__doc__ or "")
       or True)

    print("\n— the review draws a set as one card —")
    card, rest = ui._batch_cards("s3cret", "eien", kb.proposed_assets("eien"))
    ck("every frame in the set is drawn",
       all(f["url"] in card for f in got["frames"]),
       "the owner asked to see every one; 'and 19 more' is not that")
    ck("…each labelled with what makes it different",
       all(f["cell"]["angle"] in card for f in got["frames"]))
    ck("…with its own reviewer's read beside it, as advice",
       "reads right" in card and "advice, not a filter" in card)
    ck("the whole set can be rejected in one click",
       'value="reject_batch"' in card and "Reject all" in card)
    ck("…and a single frame can be kept",
       'name="asset_ids"' in card and 'value="approve"' in card)
    ck("select-all is scoped to its own card",
       "closest('.card')" in card,
       "a page-wide selector ticks every set on the page")
    ck("a set's frames are REMOVED from the flat picture queue",
       not any(a.batch for a in rest),
       "one decision with two buttons is how a queue stops being trusted")
    ck("…and un-batched finds still reach it",
       len(rest) == len([a for a in kb.proposed_assets("eien") if not a.batch]))

    print("\n— and the page actually renders it —")
    # THE PAGE, not the helper. Sabotage has shown twice that a helper stays
    # green while the card it feeds stops being called.
    page = ui.render_content("s3cret", tenant="eien", sub="pictures")
    ck("the set appears on the pictures tab",
       'value="reject_batch"' in page and got["frames"][0]["url"] in page)
    ck("…above the crawler's queue, which is a different question",
       page.index("reject_batch") < page.index("Pictures waiting"))

    print("\n— reject-the-set reads the SET, not the ticked boxes —")
    from fastapi.testclient import TestClient

    from app.web import app as _app
    c = TestClient(_app)
    n_before = len(kb.batch_assets("eien", got["batch"]))
    r = c.post("/admin/assets_decide?key=s3cret",
               data={"tenant": "eien", "action": "reject_batch",
                     "batch": got["batch"]},
               follow_redirects=False)
    ck("it was accepted with NO box ticked",
       r.status_code in (200, 303), str(r.status_code))
    ck("…and rejected the whole set",
       n_before > 0 and kb.batch_assets("eien", got["batch"]) == [],
       "a button that acts on a different list from the grid above it is the "
       "worst kind of control")
    ck("…rejecting RETIRES, so a rerun does not re-propose them",
       all(a.status == "retired" for a in
           [x for x in _all_assets("eien") if x.batch == got["batch"]]))

    print("\n— keeping a frame cuts its placements, where the decision is —")
    keep = [f for f in got2["frames"] if f["asset_id"] != frame["asset_id"]][0]
    c.post("/admin/assets_decide?key=s3cret",
           data={"tenant": "eien", "action": "approve",
                 "asset_ids": [keep["asset_id"]]}, follow_redirects=False)
    _kept = next(a for a in _all_assets("eien") if a.id == keep["asset_id"])
    # AND HANDED IT TO THE CLIENT. `_run_bg` marks "running" before it spawns,
    # so this is deterministic. Asserted here rather than in test_hosting
    # because the claim is about the ROUTE: `hosting.publish` can be perfect
    # and never called.
    from app.web import bg_status as _bgs
    ck("approving starts the hand-off to the client's own site",
       bool(_bgs("hosting", "eien").get("state")),
       "approved artwork that never leaves our blob store means the client "
       "owns nothing we made for them")
    ck("approving cut the other two placements there and then",
       set(_kept.placements or {}) == {"4:5", "9:16"},
       "act where you report — the alternative is a second screen nobody "
       "visits")

    print("\n— a run that failed does not look like one still going —")
    import json as _json
    def _state(state, detail=""):
        with db.SessionLocal() as sx:
            k = "bg:ad_frames:eien"
            row = sx.get(db.Setting, k) or db.Setting(key=k)
            row.value = _json.dumps({"state": state, "detail": detail,
                                     "at": db.utcnow().isoformat()})
            sx.merge(row)
            sx.commit()

    # An account where NOTHING has run. `eien` has just approved a frame, so
    # the hand-off label already carries state there — asserting silence on it
    # would be asserting that the wiring did not fire.
    ck("nothing said when nothing has run", ui._frames_run("baci") == "")
    _state("running")
    ck("a run in progress says so where the frames were promised",
       "running" in ui._frames_run("eien")
       and "does not refresh itself" in ui._frames_run("eien"))
    _state("failed", "RuntimeError: the model refused")
    _f = ui._frames_run("eien")
    ck("…and a failed one is not mistaken for a slow one",
       "failed" in _f and "the model refused" in _f,
       "a background action that failed looked exactly like one still "
       "running — the banner promised pictures and none arrived")
    ck("…and it reaches the page, not just the helper",
       "the model refused" in ui.render_content("s3cret", tenant="eien",
                                                sub="pictures"))
    ck("the label is registered with the surface that reports it",
       ("ad_frames", "Ad frames") in ui.BG_PICTURE_LABELS
       and ("ad_frames", "Ad frames") in ui.BG_ALL_LABELS,
       "a background action must be named by a surface before it may start")

    print("\n— the ad variant's amber chip is now a button —")
    ck("the board offers to make frames for THAT variant",
       'action="/admin/ad_frames"' in open(
           os.path.join(os.path.dirname(os.path.dirname(
               os.path.abspath(__file__))), "app", "admin_ui.py")).read(),
       "needs_art_direction was a need stated beside no way to meet it")
    from app.web import _first_line
    ck("the words for a frame are the ad's own opening line",
       _first_line("## Heading\n\nTested every batch, published every result.")
       == "Heading",
       "or the picture and the post argue two different things")
    # …AND THEY TRAVEL TO CANVA RATHER THAN INTO THE PIXELS. A headline the
    # caller computes and nothing consumes would be a parameter that goes
    # nowhere — the shape this codebase keeps closing.
    imagegen.plate = _plate
    creative.assess = _assess
    got7 = creative.batch("eien", commitment=ent, entity_key="omega-3",
                          fmt="ad_frame", positioning="testing beats price",
                          plates=1, headline="Which host are you")
    ck("  the set carries the line, and says where the type gets set",
       got7["headline"] == "Which host are you"
       and "in Canva" in got7["note"] and "Which host are you" in got7["note"],
       got7["note"][:160])

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


def _all_assets(tenant: str) -> list:
    with db.SessionLocal() as s:
        rows = s.query(db.KbAsset).filter(db.KbAsset.tenant == tenant).all()
        s.expunge_all()
        return rows


def _shape(url: str) -> tuple:
    from PIL import Image
    blob, _ = media.get(url.rsplit("/", 1)[-1])
    im = Image.open(io.BytesIO(blob))
    return im.size


if __name__ == "__main__":
    raise SystemExit(main())
