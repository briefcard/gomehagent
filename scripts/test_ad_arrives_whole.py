"""The ad arrives whole: its own words reach the picture, its pictures come back.

Owner, 2026-09-05, asking the question this build had not answered: *"we still
have not defined how we will improve the output of the actual generated
content."* Three of the answers were one line each, and all three were the same
shape — a value the row already carried that nothing ever sent.

  · `Output.body`'s first line IS the ad. `prominent` is the parameter written
    to carry it, whose clause tells the generator the picture "sits beside
    these words". `web.ad_frames` passed `headline`, which `batch` puts in a
    return note and nowhere else. So the frame never knew what the ad said.

  · `Output.situation` is the FIRST thing `_subject_of` reads. It was never
    passed, so an ad about a circumstance had no subject and fell through to
    the entity name.

  · Frames were filed `tags=[angle, lever, moment, framing]` — the grid cell,
    not the argument. The binding between a variant and its pictures lived in
    `batch()`'s stack frame and died when it returned, so `/admin/ad_export`
    shipped copy with no pictures and the owner paired them by eye.

    python3 scripts/test_ad_arrives_whole.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'aw.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import creative, db, kb, llm, systems, tenants, web  # noqa: E402

KEY = "s3cret"
_fail: list[str] = []

HEADLINE = "Your table, set in ninety seconds"
SITUATION = "a long lunch that runs into the evening"


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _variant_output(tenant: str) -> str:
    with db.SessionLocal() as s:
        row = db.Output(tenant=tenant, system_key="ad_creative",
                        format="ad_variant", status="approved",
                        situation=SITUATION, positioning="p",
                        body=f"{HEADLINE}\nand the rest of the copy.")
        s.add(row)
        s.commit()
        return row.id


def main() -> int:
    db.init_db()
    tenants.seed()
    systems.create("baci", "ad_creative")
    c = TestClient(web.app)

    print("— the ad's own words reach the picture —")
    # THE FIRST VERSION OF THIS SPIED ON THE SENDER AND NEVER RAN THE
    # RECEIVER. `_run_bg` was replaced with a stub that recorded kwargs and
    # returned, so the suite proved `ad_frames` SENDS `situation` while
    # `creative.batch` rejected it with TypeError in production for two days
    # (2026-09-05 17:03 →). A seam is only tested when both sides execute.
    sent: dict = {}
    briefs: list = []                    # EVERY call, not a merged dict
    _real_brief = creative.brief_for

    def _brief_spy(tenant, **kw):
        briefs.append(dict(kw))
        return _real_brief(tenant, **kw)
    creative.brief_for = _brief_spy
    creative._plates = lambda text, shape, n, **kw: {"ok": True, "images": [b"PNGx" * 8]}

    class _Ok:
        ok, degraded, error = True, "", ""
        text = '{"verdicts": [], "overall": "fine", "fix": ""}'
    llm.ask = lambda *a, **k: _Ok()

    def _run_now(label, fn, *a, **k):
        sent.update(k)
        return fn(*a, **k)            # the REAL batch, synchronously
    web._run_bg = _run_now
    vid = _variant_output("baci")
    r = c.post(f"/admin/ad_frames?key={KEY}",
               data={"tenant": "baci", "output_id": vid, "plates": "1"},
               follow_redirects=False)
    ck("the run is accepted", r.status_code in (200, 303), str(r.status_code))
    ck("the ad's first line is sent as `prominent`, not only as `headline`",
       sent.get("prominent") == HEADLINE, repr(sent.get("prominent")))
    ck("  and the row's situation is sent, which _subject_of reads FIRST",
       sent.get("situation") == SITUATION, repr(sent.get("situation")))
    ck("  and the variant is named, so its frames can be found again",
       sent.get("output_id") == vid, repr(sent.get("output_id")))
    ck("and creative.batch ACCEPTED every kwarg the route sent — no TypeError",
       bool(briefs), "the receiver ran; a spy on the sender cannot say this")
    # A MERGED DICT WAS HOLLOW HERE: the composited brief still forwarded
    # `situation` when the base brief had it stripped, so the sabotage run
    # reported MISSED. Every brief `batch` triggers must carry it — the frame
    # brief AND the one inside `pick` that chooses the photograph.
    base = [b for b in briefs if not b.get("composited")]
    ck("  and EVERY base brief batch triggered carries the situation "
       f"({len(base)} calls: frame + photo selection)",
       bool(base) and all(b.get("situation") == SITUATION for b in base),
       str([b.get("situation") for b in base]))

    print("\n— structurally: everything ad_frames sends, batch accepts —")
    import ast as _ast
    import inspect as _inspect
    # Walk the PARSED MODULE for the function, rather than slicing source and
    # re-indenting it — the first version did that and fell over on its own
    # string surgery, which is a fine way to make a structural check hollow.
    wsrc = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "web.py")).read()
    fn = next(n_ for n_ in _ast.walk(_ast.parse(wsrc))
              if isinstance(n_, (_ast.AsyncFunctionDef, _ast.FunctionDef))
              and n_.name == "ad_frames")
    sent_keys = set()
    for node in _ast.walk(fn):
        if isinstance(node, _ast.Call):
            fname = _ast.unparse(node.func)
            if fname == "dict" or fname.endswith("_run_bg"):
                sent_keys |= {kw.arg for kw in node.keywords if kw.arg}
    accepted = set(_inspect.signature(creative.batch).parameters)
    ck("every kwarg the route builds for batch is in batch's signature",
       sent_keys <= accepted, f"not accepted: {sorted(sent_keys - accepted)}")
    ck("  and the check is computed from the AST, not asserted from memory",
       "situation" in sent_keys and "situation" in accepted, "")

    print("\n— and the brief actually carries them —")
    b = creative.brief_for("baci", fmt="ad_frame", positioning="p",
                           prominent=HEADLINE, situation=SITUATION)
    ck("the words the ad says are in the picture prompt",
       HEADLINE in b["prompt"], b["prompt"][-160:])
    ck("  told not to repeat them literally",
       "repeat" in b["prompt"].lower(), "")
    ck("  and the situation is what the picture is ABOUT",
       b.get("subject") == SITUATION, repr(b.get("subject")))
    bare = creative.brief_for("baci", fmt="ad_frame", positioning="p")
    ck("  an ad with neither still says the picture has no subject",
       HEADLINE not in bare["prompt"]
       and any("about" in t for t in bare["thin"]), str(bare["thin"])[:90])

    print("\n— a frame is filed under the variant that asked for it —")
    # A SECOND VARIANT, because the real `batch` above now files frames under
    # `vid` — the count here must not depend on how many cells it walked.
    vid2 = _variant_output("baci")
    creative._file_frame("baci", b"PNG", {"subject": SITUATION}, {
        "angle": "identity", "lever": "proof", "moment": "before",
        "framing": "product_led"}, "batch-1", entity_key="", prompt="p",
        review=False, output_id=vid2)
    rows = [a for a in kb.assets("baci", publishable_only=False)
            if f"output:{vid2}" in list(a.tags or [])]
    ck("the asset carries `output:<id>` beside the cell", len(rows) == 1,
       str([list(a.tags or []) for a in kb.assets("baci", publishable_only=False)])[:150])
    ck("  and the cell tags are NOT replaced by it",
       bool(rows) and "identity" in list(rows[0].tags or [])
       and "product_led" in list(rows[0].tags or []), "")

    print("\n— the export puts each variant's pictures under its words —")
    with db.SessionLocal() as s:
        head = db.Output(tenant="baci", system_key="ad_creative",
                         format="ad_batch", status="approved", body="")
        s.add(head)
        s.commit()
        bid = head.id
        s.add(db.ArtifactBody(
            tenant="baci", output_id=bid, system_key="ad_creative",
            format="ad_batch",
            body=json.dumps({"variants": [
                {"n": 1, "output_id": vid2, "text": "the copy"},
                {"n": 2, "output_id": "nope", "text": "more copy"}]})))
        s.commit()
    txt = c.get(f"/admin/ad_export?key={KEY}&output_id={bid}").text
    ck("the copy is still there", "the copy" in txt and "more copy" in txt)
    ck("the frame's URL is exported beside its variant",
       bool(rows) and (rows[0].url or "") in txt, txt[:200])
    ck("  labelled with the cell it came from", "product_led" in txt, "")
    ck("a variant whose frames were never made SAYS so",
       "none made yet" in txt, "")
    ck("  and the frames land under the RIGHT variant",
       txt.index("Frames (1)") < txt.index("--- variant 2 ---"),
       "a frames block after the wrong header is worse than none")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
