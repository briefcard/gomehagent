"""A reference email's DESIGN is recreated with the brand's own material —
Phase 0 of INITIATIVE-email-design.md: the diagnosis, turned into checks.

Owner, 2026-09-11, on the first send built from a swiped structure: *"it is
currently making the same email with slight layout differences, but we want
the creatives, the styling and font formats etc — it should be similar to
recreating [the reference] with our content and dynamic assets, potentially
in colors that make more sense for each brand."*

Three causes, each verified in the tree, each asserted here in the
`test_open_defects` style — an entry PASSES while the defect stands and goes
red, naming the phase of the initiative that removes it, the moment it is
fixed. So the fix cannot land without this ledger moving in the same commit.

  1. THE READER CANNOT SEE THE TYPE. `read_swipe` sends the gallery
     screenshot whole; the screenshots are 680 wide and 2800–4600 tall, and
     Claude scales a picture down to its model's tier (28-px patches; a
     long-edge AND a visual-token limit). The number is computed from the
     pinned contract in `llm.py`, never eyeballed.        → Phase 3
  2. THE RENDERER CAN PAINT ONE EMAIL. Every combination of every look axis
     (all of them, walked from `email_render.LOOK`) shares one header, one
     footer, one frame, one palette of seven roles, and never sets a text
     section on a dark ground.                            → Phase 4
  3. THE BRAND KIT'S COLOURS ARE DISCARDED. `_from_canva` keeps the first
     kit colour as the accent and drops the rest.          → Phase 2

Plus the contract itself, asserted against the docs' own worked examples,
so a port that drifted from the published rule fails here first.

    python3 scripts/test_a_reference_is_recreated.py
"""
from __future__ import annotations

import base64
import io
import itertools
import json
import os
import pathlib
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (brand_theme, config, db, email_render as er,  # noqa: E402
                 email_structures as es, kb, llm, skill_pack, tenants)

PLAN = "INITIATIVE-email-design.md"
_fail: list[str] = []
_open: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def still_broken(what, cond, phase, fixed_msg):
    """PASSES while the defect stands. Fails — loudly — once it is fixed,
    naming the phase of the plan whose checks now replace this entry."""
    if cond:
        _open.append(what)
        print(f"  [ open  ] {what}")
    else:
        _fail.append(f"{what}\n      FIXED — {PLAN} {phase} has landed: {fixed_msg}; "
                     f"replace this entry with that phase's own checks")
        print(f"  [ FIXED ] {what}")


def _png(w: int, h: int) -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), "#f4f1ea")
    d = ImageDraw.Draw(im)
    # A "hero" band and some "type" lines, so the picture is not one flat
    # colour — nothing about the check depends on the content.
    d.rectangle([0, 0, w, h // 6], fill="#1e2a44")
    for y in range(h // 6 + 40, h - 40, 34):
        d.rectangle([40, y, w - 40, y + 14], fill="#7a746b")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")

    # ------------------------------------------------------------------
    print("— the image contract, pinned from the docs and checked against them —")
    # The worked examples on the vision pages, verbatim. A port of the
    # reference implementation that drifts fails HERE, before any strip is cut.
    ck("A4 at 130 DPI (1075×1520) resizes to 924×1307 — the docs' printed example",
       llm.resized_size(1075, 1520) == (924, 1307), str(llm.resized_size(1075, 1520)))
    ck("1920×1080 → 1456×819 on the standard tier, untouched on high-resolution",
       llm.resized_size(1920, 1080) == (1456, 819)
       and llm.resized_size(1920, 1080, 2576, 4784) == (1920, 1080))
    ck("3840×2160 → 1456×819 standard / 2576×1449 high-resolution",
       llm.resized_size(3840, 2160) == (1456, 819)
       and llm.resized_size(3840, 2160, 2576, 4784) == (2576, 1449))
    # The docs' TABLE says 1269×952 for 2000×1500; the docs' own reference
    # implementation — with the ties-to-even the docs say the live API uses —
    # says 1270×952. One pixel, at an exact .5 tie. Both are recorded rather
    # than one asserted as the truth.
    ck("2000×1500 lands within a pixel of the docs' table (ties-to-even)",
       llm.resized_size(2000, 1500) in ((1269, 952), (1270, 952)),
       str(llm.resized_size(2000, 1500)))
    ck("visual tokens are 28-px patches: 1000×1000 = 1296, 1092×1092 = 1521",
       llm.image_tokens(1000, 1000) == 1296 and llm.image_tokens(1092, 1092) == 1521)
    ck("a picture that fits is seen as sent",
       llm.image_fits("claude-sonnet-4-6", 1000, 1000) and llm.image_seen_as(
           "claude-sonnet-4-6", 200, 200) == (200, 200))
    tiers = {m: llm.image_tier(m)[0] for m in (
        "claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-3-5-sonnet-20241022",
        "claude-opus-4-7", "claude-opus-5", "claude-fable-5-1")}
    ck("the tier is read off the version — 4.7 and later high-resolution, earlier standard",
       tiers == {"claude-sonnet-4-6": "standard", "claude-haiku-4-5-20251001": "standard",
                 "claude-3-5-sonnet-20241022": "standard", "claude-opus-4-7": "high",
                 "claude-opus-5": "high", "claude-fable-5-1": "high"}, str(tiers))
    unk = llm.image_tier("")
    ck("a model whose version cannot be read is held to the standard tier, and says so",
       unk[0] == "standard" and "carries no version" in unk[1], unk[1])
    ck("the refusal switch is the documented field",
       llm.OVERSIZED_IMAGE_ERROR == {"oversized_image": "error"})

    # ------------------------------------------------------------------
    print("\n— 1. the reader cannot see the type — CLOSED by Phase 3 (2026-09-11) —")
    W, H = 680, 4543                      # flavors-kept-coming-back.png, measured 2026-09-11
    shot = _png(W, H)

    class _R:
        def __init__(self, text="", content=b"", status=200):
            self.text, self.content, self.status_code = text, content, status
            self.headers = {}
    page = ('<html><head><title>Tall gallery email</title>'
            '<meta property="og:image" content="https://cdn.rge/emails/tall.png">'
            '<meta property="og:title" content="A tall gallery email"></head></html>')
    sent: list = []
    from app import email_design as _ed

    class _Reply:
        ok = True
        def __init__(self, text): self.text = text

    def _ask(purpose, blocks, **k):
        sent.append((purpose, blocks))
        text = next((b["text"] for b in reversed(blocks) if b.get("type") == "text"), "")
        if "JSON patch" in text:
            return _Reply("{}")
        if "strip " in text and "SECTIONS" in text:
            return _Reply(json.dumps({"sections": [{"kind": "editorial", "slots": ["headline", "body"]}]}))
        return _Reply(json.dumps({"palette": {"mood": "dark"}, "notes": "One ask, late."}))
    real_get, real_ask = es.httpx.get, llm.ask
    es.httpx.get = lambda url, **k: (_R(page) if "reallygoodemails" in url
                                     else _R(content=shot) if "mobile" not in url
                                     else _R(status=404))
    llm.ask = _ask
    try:
        sw = es.add_swipe("https://reallygoodemails.com/emails/a-tall-gallery-email")
        ck("a swipe of a tall gallery email is filed", sw.get("ok") is True, str(sw)[:80])
        rd = es.read_swipe(sw["asset_id"])
        ck("and read", rd.get("ok") is True, str(rd)[:120])
    finally:
        es.httpx.get, llm.ask = real_get, real_ask
    model = config.CREATIVE_REVIEW_MODEL
    tier, why = llm.image_tier(model)
    from PIL import Image
    sizes = []
    for _, blocks in sent:
        for b in blocks:
            if b.get("type") == "image":
                sizes.append((Image.open(io.BytesIO(base64.b64decode(b["source"]["data"]))).size,
                              b.get("transformations")))
    per_request = [sum(1 for b in blocks if b.get("type") == "image") for _, blocks in sent]
    print(f"  the reviewer is {model!r} ({why}); the reader sent {len(sent)} request(s), "
          f"{len(sizes)} image(s), the largest {max(s for s, _ in sizes)} — every one seen as sent")
    # The claim the old entry held open, measured on the news: what the
    # reader sends is what the reviewer sees. Closed by Phase 3; kept as
    # plain checks so a regression shows here.
    ck("every image the reader sends fits the reviewer's tier — the model looks at it as sent "
       "(closed by Phase 3)",
       sizes and all(llm.image_fits(model, *sz) for sz, _ in sizes),
       str([sz for sz, _ in sizes if not llm.image_fits(model, *sz)]))
    ck("every image block carries the refusal switch, so a strip that would be downscaled is "
       "refused by the API and said, never degraded in silence",
       all(t == llm.OVERSIZED_IMAGE_ERROR for _, t in sizes))
    ck("no request carries more than 20 image blocks — over that the API holds every image to 2000 px",
       all(n <= 20 for n in per_request), str(per_request))
    ck("the reading asks for the whole design, every schema field by name — never 'arrangement only'",
       all(f'"{name}"' in _ed.prompt_global(False) for g in _ed.SCHEMA for name in _ed.SCHEMA[g])
       and "never a colour, a typeface" not in _ed.prompt_global(False)
       and "Describe its DESIGN" in _ed.prompt_global(False))
    ck("the tall screenshot is read in strips, each cut to the tier's edge, overlapping",
       (rd.get("read") or {}).get("strips", 0) >= 3 and (rd.get("read") or {}).get("calls", 0)
       == (rd.get("read") or {}).get("strips", 0) + 2, str(rd.get("read")))

    print("\n— 2. the renderer can paint one email — CLOSED by Phases 4 and 6 (2026-09-11) —")
    theme = {"name": "T", "colors": {"accent": "#123456", "text": "#1c1e22",
                                     "bg": "#f2f3f5", "surface": "#ffffff"},
             "footer": {"address": "1 Main St"}}
    blocks = [{"type": "hero", "image": "https://x/h.jpg", "headline": "Head", "sub": "Sub"},
              {"type": "heading", "text": "Kicker"},
              {"type": "text", "html": "<p>Body copy.</p>"},
              {"type": "products", "items": [{"name": "A", "url": "https://x/a",
                                              "image": "https://x/a.jpg", "price": "$1"}]},
              {"type": "quote", "text": "Q", "attribution": "R"},
              {"type": "cta", "label": "Go", "url": "https://x/go"},
              {"type": "ps", "text": "P.S. line"}]
    axes = list(er.LOOK.items())
    combos = list(itertools.product(*[list(v) for _, v in axes]))
    renders = [er.render(theme, blocks, look=dict(zip([k for k, _ in axes], c)))
               for c in combos]
    frame_of = lambda h: h[:h.find("<title>")] + h[h.find("</title>"):h.find("<tr><td style=\"padding:18px 32px 0\">")]
    footer_of = lambda h: h[h.rfind("<tr><td style=\"padding:24px 32px 32px"):]
    n_frames, n_footers = len({frame_of(h) for h in renders}), len({footer_of(h) for h in renders})
    print(f"  `email_render.render` (the fixed template): {len(combos)} look combinations, "
          f"{n_frames} frame(s), {n_footers} footer(s) — no longer what a send is built with")
    # CLOSED by Phase 4: `render_design` executes a design — every schema
    # value drawn (walked in test_a_design_is_executed.py), colours only
    # through the palette, one design two brands. The layouts registry is
    # the painter registry the Phase 1 entry held open.
    from app import email_design as _ed2
    ck("the renderer executes a design: render_design exists and every layout the schema names has a painter "
       "(closed by Phase 4)",
       callable(getattr(er, "render_design", None)) and set(_ed2.SECTION["layout"].values) == set(er.LAYOUTS))
    # CLOSED by Phase 6: the campaign run executes the structure's design.
    # Measured on the call, by AST — the design handed to render_design is
    # a NAME assigned from the picked structure, and the fixed template is
    # called nowhere in the run.
    if True:
        import ast as _ast
        src = pathlib.Path(skill_pack.__file__).read_text()
        tree = _ast.parse(src)
        calls = [n for n in _ast.walk(tree) if isinstance(n, _ast.Call)
                 and isinstance(n.func, _ast.Attribute) and n.func.attr == "render_design"
                 and isinstance(n.func.value, _ast.Name) and n.func.value.id == "email_render"]
        def _fed_from_structure(name: str) -> bool:
            for n in _ast.walk(tree):
                if (isinstance(n, _ast.Assign) and len(n.targets) == 1
                        and isinstance(n.targets[0], _ast.Name) and n.targets[0].id == name):
                    seg = _ast.get_source_segment(src, n.value) or ""
                    if '.get("design")' in seg and "_structure" in seg:
                        return True
            return False
        firsts = [c.args[0] if c.args else None for c in calls]
        legacy = [n for n in _ast.walk(tree) if isinstance(n, _ast.Call)
                  and isinstance(n.func, _ast.Attribute) and n.func.attr == "render"
                  and isinstance(n.func.value, _ast.Name) and n.func.value.id == "email_render"]
        ck("the campaign run's one render call executes the structure's design — the fixed "
           "template is called nowhere (closed by Phase 6)",
           len(calls) == 1 and all(isinstance(v, _ast.Name) and _fed_from_structure(v.id) for v in firsts)
           and not legacy, f"{len(calls)} design call(s), {len(legacy)} legacy call(s)")
    ck("the look vocabulary is the six axes the plan describes — a seventh would be news",
       sorted(er.LOOK) == ["bands", "cta", "density", "hero", "products", "scale"],
       str(sorted(er.LOOK)))

    print("\n— 3. the brand kit's colours are discarded — CLOSED by Phase 2 (2026-09-11) —")
    # The entry that held this open measured `colors.*` alone — a PROXY —
    # and stayed green after Phase 2 put the kit's colours under `palette.*`
    # roles. A ledger that fails on good news has to be measuring the news:
    # the claim is that a kit colour reaches SOME proposed field, so that is
    # what is counted now, and the closed claim stays as a plain check so a
    # regression shows here.
    kit = {"logo_url": "", "colors": ["#112233", "#445566", "#778899", "#aabbcc"],
           "fonts": {}}
    real_kit = brand_theme.canva_kit
    brand_theme.canva_kit = lambda tenant: {"ok": True, "kit": kit}
    try:
        got = brand_theme._from_canva("baci")
    finally:
        brand_theme.canva_kit = real_kit
    fields = got.get("fields") or {}
    reached = {c for c in kit["colors"]
               if any(c.lower() == str(v[0]).lower() for k, v in fields.items()
                      if not k.startswith("_"))}
    roles = sorted(k for k in fields if k.startswith("palette."))
    unplaced = {c.lower() for c in (fields.get("_unplaced", ([], ""))[0] or [])}
    print(f"  a kit of {len(kit['colors'])} colours proposes {roles}; unplaced, and said: {sorted(unplaced)}")
    ck("every colour in a four-colour kit reaches a proposed role OR is named as one no role took "
       "— nothing is discarded in silence (closed by Phase 2; the old entry counted colors.* "
       "only and would never have flipped)",
       got.get("ok") and {c.lower() for c in reached} | unplaced == {c.lower() for c in kit["colors"]}
       and len(roles) >= 3 and (not unplaced or "no role took" in fields["_unplaced"][1]),
       f"reached {sorted(reached)}, unplaced {sorted(unplaced)}")
    ck("the seven roles the theme knows are the ones the plan names",
       sorted(er._DEFAULT["colors"]) == ["accent", "accent_text", "bg", "border",
                                         "muted", "surface", "text"],
       str(sorted(er._DEFAULT["colors"])))

    print("\n" + (f"ALL PASSED — {len(_open)} defect(s) still open, as the plan says"
                  if not _fail else f"{len(_fail)} FAILED:\n  - " + "\n  - ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
