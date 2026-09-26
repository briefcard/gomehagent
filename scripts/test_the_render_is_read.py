"""The email is checked as the reader SEES it — readability and coherence
measured on the render, not read off the inline styles.

Owner, 2026-09-25: "The output still isn't as great when I switch templates
around to new, untested ones. We need a readability check for color contrasts
and of text to background and also making sure that the designs are
coherent." A new design puts its colour where the inline-style reading
cannot look — a class in a <style> block, a photograph behind the words,
rgb(), a link left in the browser's blue — so each passed unmeasured.

`shots.shoot(read=True)` reads every line as drawn and shoots the page again
with the letters transparent; `recreate.render_check` measures each line
against the pixels under it and every painted colour against the brand's and
its photographs'; `recreate.system_check(seen=shot)` holds the faces and
sizes the RENDER shows to the composer's declared system. No browser here:
the ground is drawn, the lines are placed on it.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'r.db')}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import recreate as rc  # noqa: E402

_fail: list = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def line(text, color, x, y, size=16, weight=400, family="Helvetica, Arial, sans-serif", opacity=1):
    return {"text": text, "chars": len(text), "color": color, "opacity": opacity, "size": size,
            "weight": weight, "family": family, "rects": [[x, y, 300, 20]]}


def main() -> int:
    # The page with its letters made transparent: a white band, a dark band,
    # and a pale photograph (a warm ground with a lighter grain).
    g = Image.new("RGB", (640, 300), (255, 255, 255))
    g.paste((27, 27, 27), (0, 100, 640, 200))
    for x in range(640):                      # a photograph: light falling across it, and grain
        for y in range(200, 300):
            lift = int(40 * x / 640) + (18 if (x * 7 + y * 3) % 5 == 0 else 0)
            g.putpixel((x, y), (min(255, 200 + lift), min(255, 186 + lift), min(255, 168 + lift)))
    buf = io.BytesIO()
    g.save(buf, "PNG")
    kit_ = {"theme": {"colors": {"accent": "#c8102e"}}}
    cast_ = {"picks": {"1": {"colours": {"light": "#f5ede0", "accent": "#b5651d"}}}}

    def measured(texts, grounds=()):
        return rc.render_check({"texts": texts, "grounds": list(grounds), "ground": buf.getvalue()},
                               kit_, cast_)

    print("— readability: each line against the pixels under it —")
    ck("dark text on white reads", not measured([line("Body copy that reads", "rgb(51, 51, 51)", 20, 40)]))
    got = measured([line("Pale words nobody reads", "rgb(200, 200, 200)", 20, 40)])
    ck("pale rgb() text on white is blocked, measured", [f["code"] for f in got] == ["contrast"]
       and "#c8c8c8 on #ffffff reads at 1.7:1" in got[0]["what"], str(got))
    ck("a large grey headline at 3:1 is NOT blocked — large type's floor is 3:1",
       not measured([line("A large grey headline", "rgb(148, 148, 148)", 20, 40, size=32)]))
    ck("  but the same grey as body text is",
       "floor for body text" in (measured([line("Small grey words", "rgb(148, 148, 148)", 20, 40)]) or [{}])[0].get("what", ""))
    ck("muted text on the dark band is blocked",
       "on #1b1b1b" in (measured([line("Muted on dark", "rgb(85, 85, 85)", 20, 140)]) or [{}])[0].get("what", ""))
    ck("see-through text is measured as it lands, not as declared",
       measured([line("Faded words", "rgba(0, 0, 0, 0.3)", 20, 40)])
       and not measured([line("Solid words", "rgba(0, 0, 0, 1)", 20, 40)]))
    got = measured([line("White words on the photograph", "rgb(255, 255, 255)", 20, 240)])
    ck("white words over a pale photograph are blocked, and it says a photograph",
       got and "a photograph (around" in got[0]["what"], str(got))

    print("\n— coherence: every painted colour is the brand's or its photographs' —")
    got = measured([], grounds=[{"color": "rgb(123, 47, 247)", "area": 7200}])
    ck("a purple button is off the palette", [f["code"] for f in got] == ["off_palette"]
       and "#7b2ff7" in got[0]["what"] and "#c8102e" in got[0]["what"], str(got))
    ck("a tint of the brand's own red is the brand's",
       not measured([], grounds=[{"color": "rgb(243, 198, 204)", "area": 50000}]))
    ck("a photograph's own tone is the email's",
       not measured([], grounds=[{"color": "rgb(181, 101, 29)", "area": 50000}]))
    ck("near-black, near-white and grey are nobody's colour",
       not measured([], grounds=[{"color": c, "area": 50000} for c in
                                 ("rgb(28, 26, 36)", "rgb(250, 250, 248)", "rgb(128, 128, 128)")]))
    ck("a badge-sized chip is not a colour of the design",
       not measured([], grounds=[{"color": "rgb(0, 255, 0)", "area": 800}]))

    print("\n— the declared system, held to what the render shows —")
    html = ("<html><body><!-- system: faces Playfair / Helvetica · scale 32/24/16/12 · inset 32 -->"
            "<p>words</p></body></html>")
    faces = [line("x" * 30, "rgb(0,0,0)", 0, 0, family=f) for f in
             ("'Playfair Display', Georgia, serif", "Helvetica, Arial", "'Caveat', cursive", "'Courier New', monospace")]
    ck("a fourth face set by a class is caught — the inline styles never saw it",
       [f["code"] for f in rc.system_check(html)] == []
       and "system_faces" in [f["code"] for f in rc.system_check(html, seen={"texts": faces})])
    sizes = [line("x" * 30, "rgb(0,0,0)", 0, 0, size=s) for s in (32, 16, 19, 21, 14.5)]
    ck("sizes off the declared scale are caught from the render",
       "system_scale" in [f["code"] for f in rc.system_check(html, seen={"texts": sizes})])

    print("\n— a section edge drawn by code is one closed shape —")
    # The owner's diagonal (2026-09-26): an edge left unclosed fills back to
    # its start in a straight line, so down some columns the colours flip
    # back — above, below, above. A closed shape turns once, top to bottom.
    from app import dividers, palette

    def turns(png, above, below) -> int:
        im = Image.open(io.BytesIO(png)).convert("RGB")
        a, b = palette.parse(above), palette.parse(below)
        gap = sum(abs(x - y) for x, y in zip(a, b))
        worst = 0
        for x in range(0, im.width, 7):
            seq = []
            for y in range(im.height):
                p = im.getpixel((x, y))
                da, db = sum(abs(i - j) for i, j in zip(p, a)), sum(abs(i - j) for i, j in zip(p, b))
                if min(da, db) < gap / 3:
                    seq.append("a" if da < db else "b")
            flips = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
            worst = max(worst, flips if seq and seq[0] == "a" and seq[-1] == "b" else 99)
        return worst

    ck("every shape turns from the ground above to the ground below exactly once, in every column",
       all(turns(dividers.draw(sh, "#29325a", "#f4f1ec"), "#29325a", "#f4f1ec") == 1 for sh in dividers.SHAPES),
       str({sh: turns(dividers.draw(sh, "#29325a", "#f4f1ec"), "#29325a", "#f4f1ec") for sh in dividers.SHAPES}))
    from PIL import ImageDraw
    broken = Image.new("RGB", (1200, 96), (244, 241, 236))
    ImageDraw.Draw(broken).polygon([(x, 20 + 18 * ((x // 150) % 2)) for x in range(0, 1201, 50)] + [(1200, 0)],
                                   fill=(41, 50, 90))
    b_ = io.BytesIO()
    broken.save(b_, "PNG")
    ck("  and an edge left open — the diagonal the owner saw — fails the same measure",
       turns(b_.getvalue(), "#29325a", "#f4f1ec") > 1)
    from app import media
    real_put = media.put
    media.put = lambda tenant, blob, **k: {"ok": True, "id": "d1", "url": "http://x/media/d1.png"}
    try:
        html, notes = dividers.place('<td><!--divider: wave #29325a #F4F1EC--></td><td><!--divider: blob #fff #000--></td>', "t")
    finally:
        media.put = real_put
    ck("a named edge becomes its picture, with the grounds it joins",
       'data-divider="#29325a #f4f1ec"' in html and "divider: wave" not in html, html[:160])
    ck("  and a shape there is not is refused by name, left as it was",
       any(n.startswith("divider:") and "wave, curve, slant" in n for n in notes) and "divider: blob" in html)

    print("\n— a divider meets its grounds; words are never under a shape —")
    seam = Image.new("RGB", (640, 300), (244, 241, 236))
    seam.paste((41, 50, 90), (0, 0, 640, 100))                 # a navy section, cream below
    s_ = io.BytesIO()
    seam.save(s_, "PNG")

    def edge(colours):
        return rc.render_check({"texts": [], "grounds": [], "ground": s_.getvalue(),
                                "dividers": [{"colors": colours, "rect": [20, 100, 600, 48]}]}, kit_, cast_)
    ck("a divider named by the grounds it joins leaves no seam", not edge("#29325a #f4ede0"), str(edge("#29325a #f4ede0")))
    got = edge("#c8102e #f4f1ec")
    ck("  one named by another colour is a seam, and says which side",
       [f["code"] for f in got] == ["divider_seam"] and "above it is #29325a" in got[0]["what"], str(got))
    ck("words a drawn shape sits on are found",
       [f["code"] for f in measured([{**line("Body copy that reads", "rgb(51, 51, 51)", 20, 40), "covered": 0.4}])]
       == ["covered"])
    ck("  and words clear of every shape are not",
       not measured([{**line("Body copy that reads", "rgb(51, 51, 51)", 20, 40), "covered": 0}]))

    print()
    print("ALL GREEN" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
