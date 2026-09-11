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
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (brand_theme, config, db, email_render as er,  # noqa: E402
                 email_structures as es, kb, llm, tenants)

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
    print("\n— 1. the reader cannot see the type (open until Phase 3) —")
    W, H = 680, 4543                      # flavors-kept-coming-back.png, measured 2026-09-11
    shot = _png(W, H)

    class _R:
        def __init__(self, text="", content=b"", status=200):
            self.text, self.content, self.status_code = text, content, status
            self.headers = {}
    page = ('<html><head><title>Tall gallery email</title>'
            '<meta property="og:image" content="https://cdn.rge/tall.png">'
            '<meta property="og:title" content="A tall gallery email"></head></html>')
    sent: list = []

    class _Reply:
        ok = True
        text = json.dumps({"sequence": ["hero", "heading", "text", "cta"],
                           "fits_intents": ["offer"], "fits_formats": ["designed"],
                           "notes": "One ask, late.", "look": {"hero": "bleed"}})
    real_get, real_ask = es.httpx.get, llm.ask
    es.httpx.get = lambda url, **k: (_R(page) if "reallygoodemails" in url
                                     else _R(content=shot))
    llm.ask = lambda purpose, blocks, **k: (sent.append((purpose, blocks)) or _Reply())
    try:
        sw = es.add_swipe("https://reallygoodemails.com/emails/a-tall-gallery-email")
        ck("a swipe of a tall gallery email is filed", sw.get("ok") is True, str(sw)[:80])
        rd = es.read_swipe(sw["asset_id"])
        ck("and read", rd.get("ok") is True, str(rd)[:80])
    finally:
        es.httpx.get, llm.ask = real_get, real_ask
    images = [b for _, blocks in sent for b in blocks if b.get("type") == "image"]
    ck("the reading sends the model exactly one image block", len(images) == 1, str(len(images)))
    from PIL import Image
    sent_w, sent_h = Image.open(io.BytesIO(base64.b64decode(images[0]["source"]["data"]))).size
    model = config.CREATIVE_REVIEW_MODEL
    seen_w, seen_h = llm.image_seen_as(model, sent_w, sent_h)
    tier, why = llm.image_tier(model)
    print(f"  the reviewer is {model!r} ({why});\n  it is sent {sent_w}×{sent_h} and "
          f"looks at {seen_w}×{seen_h} — {seen_h / sent_h:.0%} of the height; a 14 px "
          f"line of body type arrives {14 * seen_h / sent_h:.1f} px tall")
    still_broken(
        f"the swipe reader sends the screenshot whole ({sent_w}×{sent_h}) and the "
        f"reviewer sees it at {seen_w}×{seen_h}",
        (sent_w, sent_h) == (W, H) and not llm.image_fits(model, sent_w, sent_h),
        "Phase 3",
        "the reader now cuts strips that fit the reviewer's tier before sending")
    still_broken(
        "the reading is told to describe the arrangement only — never a colour, a typeface",
        "never a colour, a typeface" in es._READ, "Phase 3",
        "the reading now asks for the whole design")
    ck("no image block sets the refusal switch, so a downscale is silent",
       all("transformations" not in b for b in images))

    # ------------------------------------------------------------------
    print("\n— 2. the renderer can paint one email (open until Phase 4) —")
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
    hexes = lambda h: set(m.lower() for m in re.findall(r"#[0-9a-fA-F]{3,6}\b", h))
    theme_hex = hexes(er.render(theme, blocks))
    all_hex = set().union(*(hexes(h) for h in renders))
    header_of = lambda h: h.split("</head>", 1)[1].split("<tr><td style=\"padding:0\">", 1)[0] \
        if "<tr><td style=\"padding:0\">" in h else ""
    footer_of = lambda h: h[h.rfind("<tr><td style=\"padding:24px 32px 32px"):]
    frame_of = lambda h: h[:h.find("<title>")] + h[h.find("</title>"):h.find("<tr><td style=\"padding:18px 32px 0\">")]
    n_frames = len({frame_of(h) for h in renders})
    n_footers = len({footer_of(h) for h in renders})
    sizes = set().union(*(set(re.findall(r"font-size:(\d+)px", h)) for h in renders))
    # A TEXT section on a dark ground. The bulletproof button is a filled
    # cell (the accent) and the overlay hero paints the ink behind its
    # photograph — those are the only grounds today's renderer ever sets
    # besides the page colour under a band. Under every look whose hero is
    # NOT the overlay, the ink never appears as a ground at all.
    keys = [k for k, _ in axes]
    grounds = lambda h: set(re.findall(
        r'<tr><td[^>]*style="[^"]*background:(#[0-9a-fA-F]{3,6})', h))
    all_grounds = set().union(*(grounds(h) for h in renders))
    off_overlay = set().union(*(grounds(h) for c, h in zip(combos, renders)
                                if dict(zip(keys, c))["hero"] != "overlay"))
    print(f"  {len(combos)} look combinations rendered: {n_frames} distinct frame(s), "
          f"{n_footers} distinct footer(s), {len(all_hex)} colour(s) in play, "
          f"font sizes {sorted(int(s) for s in sizes)}, cell grounds {sorted(all_grounds)}")
    still_broken(
        f"every one of the {len(combos)} look combinations shares one frame and one footer",
        n_frames == 1 and n_footers == 1, "Phase 4",
        "a design now chooses the frame and the footer")
    still_broken(
        "no combination reaches a colour the seven theme roles do not name",
        all_hex <= theme_hex | {"#ffffff"}, "Phase 4",
        "the renderer now paints from a palette of roles")
    still_broken(
        "the only grounds any look can set are the page colour, the button's accent, "
        "and the ink behind the overlay hero's photograph — no text section on a dark ground",
        all_grounds <= {theme["colors"]["bg"], theme["colors"]["text"], theme["colors"]["accent"]}
        and theme["colors"]["text"] not in off_overlay, "Phase 4",
        "a section's ground is now a palette role the design chooses")
    # Phase 1 filed the DESIGN vocabulary on every structure; nothing draws
    # it yet. The painter registry the schema walk will run against is
    # Phase 4's; until it exists this entry holds the claim open.
    from app import email_design as _ed
    still_broken(
        f"the renderer has no painter registry for the design vocabulary "
        f"({len(_ed.fields())} fields filed, none drawn) — a structure's design "
        f"is stored and never executed",
        not hasattr(er, "PAINTERS") and not hasattr(er, "render_design"), "Phase 4",
        "email_render.render_design executes a design; replace this with the "
        "schema-walk-against-PAINTERS check")
    ck("the look vocabulary is the six axes the plan describes — a seventh would be news",
       sorted(er.LOOK) == ["bands", "cta", "density", "hero", "products", "scale"],
       str(sorted(er.LOOK)))

    # ------------------------------------------------------------------
    print("\n— 3. the brand kit's colours are discarded (open until Phase 2) —")
    kit = {"logo_url": "", "colors": ["#112233", "#445566", "#778899", "#aabbcc"],
           "fonts": {}}
    real_kit = brand_theme.canva_kit
    brand_theme.canva_kit = lambda tenant: {"ok": True, "kit": kit}
    try:
        got = brand_theme._from_canva("baci")
    finally:
        brand_theme.canva_kit = real_kit
    fields = got.get("fields") or {}
    colour_fields = {k: v[0] for k, v in fields.items() if k.startswith("colors.")}
    kept = {c for c in kit["colors"] if any(c == v for v in colour_fields.values())}
    print(f"  a kit of {len(kit['colors'])} colours proposes {colour_fields}")
    still_broken(
        "a four-colour brand kit proposes one role — the accent, from the first colour",
        got.get("ok") and kept == {"#112233"} and set(colour_fields) == {"colors.accent",
                                                                          "colors.accent_text"},
        "Phase 2", "the deriver now proposes a palette of roles from the whole kit")
    ck("the seven roles the theme knows are the ones the plan names",
       sorted(er._DEFAULT["colors"]) == ["accent", "accent_text", "bg", "border",
                                         "muted", "surface", "text"],
       str(sorted(er._DEFAULT["colors"])))

    print("\n" + (f"ALL PASSED — {len(_open)} defect(s) still open, as the plan says"
                  if not _fail else f"{len(_fail)} FAILED:\n  - " + "\n  - ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
