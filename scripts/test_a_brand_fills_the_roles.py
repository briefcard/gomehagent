"""A brand fills the roles a design names — its palette derived, never
invented; a role no source gave computed by one rule and labelled; every
ground/ink pair measured; the owner's hand winning and surviving.

INITIATIVE-email-design.md, Phase 2. A design says "the hero sits on the dark
ground"; this is where a brand's actual colour is put under that name.

  1. THE ARITHMETIC IS WCAG'S: known luminances and ratios.
  2. FILL: every role filled; a role from an older theme colour resolves to
     that field's source; a role nobody gave is `computed: <rule>`; the
     renderer's default palette is the same rule on its default colours.
  3. FINDINGS: a pair below the bar is named with its ratio; a good palette
     has none.
  4. THE KIT IS PLACED, BY RULE: the first colour is the accent, the darkest
     the dark ground, the lightest the page; what no role takes is named.
  5. THE PHOTOGRAPHS: a colour read off the packshots proposes secondary and
     tint, and white/black/grey never do.
  6. DERIVE → APPROVE: roles ride the proposal with provenance; precedence
     is kit > Shopify > site > pictures; an edited role wins, is refilled
     around, survives a re-derive, and a non-colour is refused by name.
  7. THE CARD: swatches, where each came from, an input per role inside
     the approve form, the findings, the faces, the pictures by slot kind.
  8. ASSETS BY SLOT KIND: packshots for packshot slots, photographs for
     lifestyle, a reference pin never; an empty kind says its fix.

    python3 scripts/test_a_brand_fills_the_roles.py
"""
from __future__ import annotations

import io
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pal.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (admin_ui, brand_theme as bt, db, email_design as ed,  # noqa: E402
                 email_render as er, kb, palette as P, tenants)

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _jpg(colour: str, w: int = 120, h: int = 120) -> bytes:
    from PIL import Image
    im = Image.new("RGB", (w, h), colour)
    b = io.BytesIO(); im.save(b, format="JPEG", quality=92)
    return b.getvalue()


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")

    print("— 1. the arithmetic is WCAG's —")
    ck("white is 1.0, black is 0.0, #808080 is about 0.216",
       P.luminance("#fff") == 1.0 and P.luminance("#000") == 0.0
       and abs(P.luminance("#808080") - 0.216) < 0.005, str(P.luminance("#808080")))
    ck("white on black is 21:1; #777 on white is 4.48:1 (just under the text bar)",
       P.contrast("#ffffff", "#000000") == 21.0 and abs(P.contrast("#777777", "#ffffff") - 4.48) < 0.02,
       str(P.contrast("#777777", "#ffffff")))
    ck("a non-colour is nothing", P.norm("blue") == "" and P.parse("#12") is None and P.norm("#ABC") == "#aabbcc")
    ck("the readable ink is light on a dark ground and dark on a light one",
       P.on("#1e2a44") == "#ffffff" and P.on("#f1ede6") == "#1c1e22")

    print("\n— 2. fill —")
    pal, how = P.fill({}, er._DEFAULT["colors"])
    ck("every role is filled", sorted(pal) == sorted(ed.ROLES) and all(P.norm(v) for v in pal.values()))
    ck("a role the older theme colours already are resolves to that field",
       how["page"] == "from colors.bg" and how["ink"] == "from colors.text"
       and how["accent_ink"] == "from colors.accent_text")
    ck("a role nobody gave is computed by one stated rule and says so",
       how["dark"].startswith("computed:") and how["tint"].startswith("computed:")
       and how["secondary"].startswith("computed:") and "eight per cent" in how["tint"])
    ck("a given role wins over the older colour and over the rule",
       P.fill({"page": "#f1ede6", "dark": "#0b1a0f"}, er._DEFAULT["colors"])[1]["page"] == "given"
       and P.fill({"dark": "#0b1a0f"}, er._DEFAULT["colors"])[0]["dark"] == "#0b1a0f")
    ck("a light ink is deepened before it is used as a ground",
       "sixty per cent towards black" in P.fill({}, {"text": "#9aa3ad"})[1]["dark"])
    ck("the renderer's default palette is this rule on its default colours — one rule, one place",
       er._DEFAULT["palette"] == pal and er._theme({})["palette"] == pal)
    ck("a theme with no palette renders with the default one; a theme with roles keeps them",
       er._theme({"palette": {"dark": "#0b1a0f"}})["palette"]["dark"] == "#0b1a0f")

    print("\n— 3. findings —")
    ck("a good palette has no findings", P.findings(pal) == [])
    bad = P.findings({"surface": "#ffffff", "ink": "#bbbbbb", "muted": "#dddddd",
                      "accent": "#ffff00", "accent_ink": "#ffffff", "dark": "#333333",
                      "dark_ink": "#444444", "page": "#ffffff", "tint": "#fafafa", "tint_ink": "#eeeeee"})
    ck("every pair below the bar is named with its ratio",
       any(b.startswith("ink on surface is 1.92:1") for b in bad)
       and any(b.startswith("dark_ink on dark") for b in bad)
       and any("muted on surface" in b and "3.0:1" in b for b in bad)
       and any("text link in the accent would not read" in b for b in bad), str(bad)[:200])

    print("\n— 4. the kit is placed, by rule —")
    placed = P.rank_kit(["#B8302F", "#1E2A44", "#F1EDE6", "#C9B8A3", "#F6E9E3"])
    ck("the first colour is the accent, the darkest the dark ground and (near black) the ink, "
       "the lightest the page, the second-lightest the tint, the most saturated remainder the secondary",
       placed["accent"][0] == "#b8302f" and placed["dark"][0] == "#1e2a44" and placed["ink"][0] == "#1e2a44"
       and placed["page"][0] == "#f1ede6" and placed["tint"][0] == "#f6e9e3"
       and placed["secondary"][0] == "#c9b8a3", str(placed))
    ck("every placement names its rule",
       all(rule for _, rule in placed.values()) and "first colour" in placed["accent"][1])
    ck("an empty kit places nothing; one colour is the accent alone",
       P.rank_kit([]) == {} and list(P.rank_kit(["#123456"])) == ["accent"])

    print("\n— 5. the photographs —")
    got = P.from_pictures([_jpg("#2f6b4f"), _jpg("#2f6b4f"), _jpg("#ffffff"), _jpg("#808080"), _jpg("#dfe9e2")])
    ck("the most frequent real colour proposes the secondary; the most frequent light one the tint; "
       "white and grey never do",
       got.get("secondary", ("",))[0] and P.contrast(got["secondary"][0], "#2f6b4f") < 1.15
       and got.get("tint", ("",))[0] and P.luminance(got["tint"][0]) > 0.7, str(got))
    ck("the rule names the photographs and their count",
       "product photographs (5 pictures)" in got["secondary"][1])
    ck("only white, black and grey is nothing to say",
       P.from_pictures([_jpg("#ffffff"), _jpg("#000000"), _jpg("#777777")]) == {})

    print("\n— 6. derive → approve —")
    real_kit, real_shop, real_site, real_pics = bt.canva_kit, bt.shop_brand, bt.fetch_page, bt.packshot_blobs
    bt.canva_kit = lambda t: {"ok": True, "kit": {"colors": ["#B8302F", "#1E2A44", "#F1EDE6", "#C9B8A3"],
                                                  "fonts": {"heading": "Playfair Display"}, "logo_url": ""}}
    bt.packshot_blobs = lambda t, limit=6: [_jpg("#2f6b4f"), _jpg("#dfe9e2")]
    try:
        got = bt.derive("baci")
        th, src = got["theme"], got["sources"]
        ck("the proposal carries every role, each with where it came from",
           sorted(th["palette"]) == sorted(ed.ROLES)
           and all(src.get(f"palette.{r}") for r in ed.ROLES), str({r: src.get(f"palette.{r}") for r in ed.ROLES})[:200])
        ck("the kit's roles are the kit's, by rule",
           th["palette"]["accent"] == "#b8302f" and "canva brand kit (the first colour" in src["palette.accent"]
           and th["palette"]["page"] == "#f1ede6" and "lightest" in src["palette.page"])
        ck("a role only the photographs gave is the photographs' — the lowest source",
           th["palette"]["tint"] and "product photographs" in src["palette.tint"], src["palette.tint"])
        ck("the kit outranks the photographs where both speak (secondary)",
           th["palette"]["secondary"] == "#c9b8a3" and "kit" in src["palette.secondary"])
        ck("a role no source gave is labelled computed, with its rule",
           src["palette.dark_ink"].startswith("computed:") and src["palette.tint_ink"].startswith("computed:"))
        ck("a role that is an older theme colour names that colour's source",
           "as surface" in src["palette.surface"] and "as accent_ink" in src["palette.accent_ink"])
        ck("the findings ride the proposal and the status", got["findings"] == [] and bt.status("baci")["findings"] == [])
        ck("the older colour fields are untouched — the live renderer changes nothing until Phase 4",
           th["colors"]["accent"] == "#B8302F" and "bg" not in th["colors"])
        # The "dark" ground set to a LIGHT colour on purpose: the ink computed
        # for the navy was white, and white on this would not read — so the
        # test can tell a refilled ink from a stale one (the first cut edited
        # navy to near-black, both took white, and the guard went UNDETECTED).
        ap = bt.approve("baci", {"palette.dark": "#e8f0e8", "palette.secondary": "#7a5c2e"})
        live = bt.live_theme("baci")
        ck("an edited role wins, and the roles computed around it are computed again",
           live["palette"]["dark"] == "#e8f0e8" and live["palette"]["secondary"] == "#7a5c2e"
           and live["palette"]["dark_ink"] == live["palette"]["ink"]
           and not any("dark_ink on dark" in f for f in ap["findings"])
           and set(live["_meta"]["edited"]) >= {"palette.dark", "palette.secondary"},
           str(live["palette"]["dark_ink"]) + " " + str(ap["findings"]))
        bt.derive("baci")
        ap2 = bt.approve("baci")
        ck("a hand-set role survives a re-derive and a plain approve",
           ap2["theme"]["palette"]["dark"] == "#e8f0e8" and "palette.dark" in ap2["carried"])
        no = bt.approve("baci", {"palette.tint": "eggshell"})
        ck("a role that is not a colour is refused by name",
           not no.get("ok") and "palette.tint takes a colour as #hex" in no.get("error", ""), no.get("error", ""))
        ck("a mis-set role is a finding on the approval, said, never a silent fallback",
           "contrast:" in bt.approve("baci", {"palette.ink": "#cccccc"})["note"])
        bt.approve("baci", {"palette.ink": "#1e2a44"})
        bt.packshot_blobs = lambda t, limit=6: []
        got2 = bt.derive("baci")
        ck("no photographs on file is a source not consulted, with its fix",
           "pictures" in got2["unavailable"] and "catalogue sync" in got2["unavailable"]["pictures"])
        bt.canva_kit = lambda t: {"ok": True, "kit": {"colors": ["#112233", "#445566", "#778899", "#aabbcc"],
                                                      "fonts": {}, "logo_url": ""}}
        got3 = bt.derive("baci")
        ck("a kit colour no role took is shown under the source, never written to the theme",
           any("no role took" in x for x in got3["partial"].get("canva", []))
           and "_unplaced" not in got3["theme"])

        print("\n— 7. the card —")
        bt.canva_kit = lambda t: {"ok": True, "kit": {"colors": ["#B8302F", "#1E2A44", "#F1EDE6", "#C9B8A3"],
                                                      "fonts": {"heading": "Playfair Display"}, "logo_url": ""}}
        bt.derive("baci")
        html = admin_ui.render_brand("s3cret", "baci")
        ck("the palette of roles is a section with a swatch, its source and an input per role, inside the approve form",
           "Palette of roles" in html and len(re.findall(r"name='palette\.", html)) == len(ed.ROLES)
           and "class=sw style=background:#b8302f" in html and "the first colour in the kit" in html
           and html.index('action="/admin/brand_theme/approve"') < html.index("Palette of roles")
           < html.index("Approve — this look ships"))
        ck("the faces on file are named, and a missing one says the classification chooses",
           "Playfair Display" in html and "the design's classification chooses" in html)
        ck("the pictures by slot kind are counted, and an empty kind says its fix",
           "Pictures by the kind of slot" in html and "none for packshot-on-plain" in html
           and "catalogue sync" in html)
        bt.approve("baci", {"palette.ink": "#cccccc"})
        html2 = admin_ui.render_brand("s3cret", "baci")
        ck("a contrast finding on the live palette is on the card",
           "Contrast, live" in html2 and "ink on surface is" in html2)
        from app import web
        import asyncio
        class _Form(dict):
            pass
        class _Req:
            async def form(self):
                return _Form({"tenant": "baci", "palette.dark": "#101820", "footer.address": ""})
        resp = asyncio.run(web.brand_theme_approve(_Req(), key="s3cret"))
        ck("the approve route carries a role typed on the card into the live theme",
           bt.live_theme("baci")["palette"]["dark"] == "#101820" and resp.status_code == 303)
    finally:
        bt.canva_kit, bt.shop_brand, bt.fetch_page, bt.packshot_blobs = real_kit, real_shop, real_site, real_pics

    print("\n— 8. assets by slot kind —")
    kb.add_asset("baci", "https://cdn/x1.jpg", rights=kb.OWNED, subject="object",
                 tags=["store-image:1", "packshot"], origin="store_sync")
    kb.add_asset("baci", "https://cdn/x2.jpg", rights=kb.OWNED, subject="object",
                 tags=["store-image:2"], origin="store_sync")
    kb.add_asset("baci", "https://cdn/p1.jpg", rights=kb.OWNED, subject="photo", origin="human")
    kb.add_asset("baci", "https://cdn/ref.jpg", rights=kb.REFERENCE, subject="scene", origin="pinterest")
    urls = {k: [a.url.rsplit("/", 1)[1] for a in ed.assets_for("baci", k)["assets"]] for k in ed._KIND_FIT}
    ck("a packshot slot takes the packshot first, then the other store images",
       urls["packshot-on-plain"] == ["x1.jpg", "x2.jpg"] and urls["packshot-on-colour"] == ["x1.jpg", "x2.jpg"])
    ck("a lifestyle slot takes the photographs, then the later store images — never the packshot",
       urls["lifestyle"] == ["p1.jpg", "x2.jpg"] and "x1.jpg" not in urls["lifestyle"])
    ck("a reference pin fills nothing, whatever its kind", all("ref.jpg" not in v for v in urls.values()))
    ck("an empty kind says why, with its fix; an unknown kind is refused by name",
       "file a surface photograph" in ed.assets_for("baci", "texture")["why"]
       and "not an imagery kind" in ed.assets_for("baci", "hologram")["why"])
    ck("the count per kind is the line the card shows",
       ed.assets_by_kind("baci")["packshot-on-plain"] == 2 and ed.assets_by_kind("baci")["texture"] == 0)

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
