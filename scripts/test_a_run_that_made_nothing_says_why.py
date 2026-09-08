"""A frames run that made nothing says why — on the strip where the pictures
were promised, in the run's own words, before anything else.

Owner, 2026-09-08: *"My latest run didnt generate any photos — I used the
Lifestyle board and see this message: made 0 · clean 0 — nothing was
generated — drawn from 0 photograph(s) of the product and 4 board pin(s); 1
pin(s) kept out of the request: reference only — saved for inspiration, not
licensed for use. Generate something of our ow. Is there an issue with the
way we generate?"*

WHAT WAS TRUE. `batch` collected every cell's failure in `errors` and its
note said "nothing was generated" plus what the board contributed; the
errors never reached the note, `_summarise` never read them, so the strip
showed a run that did nothing for no reason. The excluded pin's reason was
cut at 90 characters, mid-word ("of our ow"), which read as a broken
sentence rather than a licence rule. Every image call IS recorded in
`toolcalls` with its error — a fact stored where no surface showed it.

Run: python3 scripts/test_a_run_that_made_nothing_says_why.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'why.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import (admin_ui as ui, coherence, creative, db, imagegen, kb,  # noqa: E402
                 kb_seed, tenants, web)

KEY = "s3cret"
_fail: list[str] = []
REFUSED = ("400: Your request was rejected as a result of our safety system. Your "
           "request may contain content that is not allowed by our safety system.")


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(colour, w: int = 96, h: int = 96) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


PICS = {f"https://cdn.example/look-{i}.png": png((20 * i, 90, 140, 255)) for i in range(1, 6)}


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    # THE OWNER'S SETUP: a product with NO photograph on file, a Lifestyle
    # board of four owned pictures and one reference pin.
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Cup",
                  description="a porcelain cup with a hand-painted zodiac sign", origin="human")
    kb.add_board("baci", "Lifestyle", note="tables, daylight, linen")
    for i in range(1, 6):
        kb.add_asset("baci", f"https://cdn.example/look-{i}.png",
                     rights=(kb.OWNED if i < 5 else kb.REFERENCE), title=f"look {i}",
                     subject=kb.SCENE, origin="human")
        aid = next(a.id for a in kb.assets("baci", publishable_only=False)
                   if a.url == f"https://cdn.example/look-{i}.png")
        kb.set_board_role(aid, "lifestyle", "look", True)
    creative._fetch = lambda url: PICS.get(url, b"")
    creative.assess = lambda blob, brief, tenant="": {
        "ok": True, "verdicts": [], "overall": "reads right", "failed": [], "fix": ""}
    cup = coherence.commit("entity", "zodiac-cup", label="Zodiac Cup")
    sent: list = []

    print("— EVERY CELL REFUSED BY THE IMAGE API: THE RUN SAYS SO, FIRST —")

    def _refuse(path, *, json_body=None, files=None, data=None):
        sent.append({"path": path, "files": files, "data": data})
        return {"ok": False, "error": REFUSED}
    imagegen.post = _refuse
    got = creative.batch("baci", commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                         positioning="the sign you were born under", plates=8,
                         review=False, boards=("lifestyle",))
    note = str(got.get("note") or "")
    ck("nothing is made and every cell's failure is kept",
       got.get("made") == 0 and len(got.get("errors") or []) == len(sent) >= 1,
       f"made={got.get('made')} errors={len(got.get('errors') or [])} calls={len(sent)}")
    ck("  the note LEADS with the reason — how many cells failed and the API's own words",
       note.startswith("nothing was generated") and "safety system" in note
       and f"{len(sent)} of {len(sent)} cell(s) failed" in note
       and note.index("failed") < note.index("drawn from"), note[:260])
    ck("  the excluded pin's reason is a whole sentence, not cut mid-word",
       "not licensed for use" in note and "of our ow" not in note, note[-200:])
    ck("  the board's contribution is still said after it",
       "drawn from 0 photograph(s) of the product and 4 board pin(s)" in note
       and "1 pin(s) kept out" in note)
    said = web._summarise(got)
    ck("the run summary carries the reason once, not twice",
       "safety system" in said and said.count("rejected as a result") == 1, said[:300])
    bare = web._summarise({"made": 0, "clean": 0, "note": "nothing was generated",
                           "errors": ["identity/person_led: 502: upstream connect error"]})
    ck("  and a result whose note forgot its errors still gets them said, with the count",
       "1 error(s)" in bare and "upstream connect error" in bare, bare)
    # THE STRIP, through the real background runner.
    web._run_bg("ad_frames", creative.batch, "baci", commitment=cup, entity_key="zodiac-cup",
                fmt="ad_frame", positioning="the sign you were born under", plates=8,
                review=False, boards=("lifestyle",))
    for _ in range(100):
        with db.SessionLocal() as s:
            row = s.get(db.Setting, "bg:ad_frames:baci")
            state = json.loads(row.value).get("state") if row else ""
        if state == "done":
            break
        time.sleep(0.1)
    strip = ui._frames_run("baci")
    ck("the Pictures strip shows the API's refusal where the pictures were promised",
       "safety system" in strip and "nothing was generated" in strip, strip[:400])

    print("\n— THE SAME BOARD WITH A WORKING API: THE LOOK-ONLY ROUTE MAKES FRAMES —")
    sent.clear()
    n = [0]

    def _draw(path, *, json_body=None, files=None, data=None):
        sent.append({"path": path, "files": files, "data": data})
        n[0] += 1
        return {"ok": True, "images": [png((n[0] * 7 % 250, i * 60 + 10, 30, 255))
                                       for i in range(int((data or {}).get("n") or 1))]}
    imagegen.post = _draw
    got2 = creative.batch("baci", commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                          positioning="the sign you were born under", plates=8,
                          review=False, boards=("lifestyle",))
    looks = [len([f for f in (c["files"] or []) if f[1][0].startswith("look-")]) for c in sent]
    prods = [len([f for f in (c["files"] or []) if f[1][0].startswith("product-")]) for c in sent]
    ck("with no product photograph the board's four owned pins go in as the look, and nothing as the product",
       got2.get("made", 0) >= 1 and sent and all(l == 4 for l in looks) and all(p == 0 for p in prods),
       f"made={got2.get('made')} looks={looks[:3]} prods={prods[:3]}")
    ck("  the reference pin never reaches the request",
       all(len(c["files"] or []) == 4 for c in sent))
    ck("  and a run that made something does not lead with a failure",
       str(got2.get("note", "")).startswith(f"{got2.get('clean')} of {got2.get('made')} passed review")
       or "passed review" in str(got2.get("note", ""))[:60], str(got2.get("note", ""))[:120])

    print("\n— SOME CELLS FAILED, SOME DREW: BOTH FACTS ARE SAID —")
    sent.clear()
    k = [0]

    def _half(path, *, json_body=None, files=None, data=None):
        k[0] += 1
        if k[0] % 2:
            return {"ok": False, "error": "429: Rate limit reached for images"}
        return {"ok": True, "images": [png((k[0] * 11 % 250, 40, 200, 255))]}
    imagegen.post = _half
    got3 = creative.batch("baci", commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                          positioning="the sign you were born under", plates=8,
                          review=False, boards=("lifestyle",))
    note3 = str(got3.get("note") or "")
    ck("a partial run says how many cells failed and the first reason, after what it made",
       got3.get("made", 0) >= 1 and "cell(s) failed" in note3 and "Rate limit" in note3
       and note3.index("passed review") < note3.index("cell(s) failed"), note3[:300])
    ck("  and the summary does not repeat it",
       web._summarise(got3).count("Rate limit") == 1)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
