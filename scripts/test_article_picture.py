"""The picture the article was promised can actually be made.

Owner, 2026-09-01: *"I also dont see any images both for featured image nor for
throughout the article. Where is all the work we did for generating images?"*

ALL OF IT WAS THERE AND NOTHING CALLED IT. `creative.generate` renders,
assesses, repairs once on the reviewer's own instruction, files the asset and
attaches the verdict; `creative.batch` does the grid. Both are covered by
`test_creative_batch.py` with nine sabotage guards. NEITHER HAD A SINGLE
PRODUCTION CALLER — grep finds no reference outside `creative.py` but comments.

The only image path that ran was `creative.pick`, which SELECTS among approved
assets and never makes one. So an account with no approved photographs got no
hero, ever — and the run's note said:

    "A brief is ready for one about … — generate it from the workroom, or the
     nightly sweep will."

BOTH HALVES WERE FALSE. There was no workroom control and there is no sweep.
That is the product asserting a capability it does not have, in its own voice,
on the one surface where somebody would go looking for it.

THE BRIEF COMES FROM ONE WRITER. `article_commitment` is what the run used to
choose a picture; the control uses the same call. A picture briefed against a
different subject than the article was written against is a picture of the
wrong thing — and it would look right in both places separately.

AND IT ATTACHES NOTHING. `generate` files the asset as PROPOSED; attaching it
here would put an unreviewed image on a page bound for a public site, which is
the one thing the rights ladder exists to prevent.

Run: python3 scripts/test_article_picture.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ap.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (admin_ui, creative, db, kb, keywords, skill_pack,  # noqa: E402
                 tenants, web)

KEY = "s3cret"
_fail = []
_calls = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _article(tenant, keyword, *, media=None):
    with db.SessionLocal() as s:
        out = db.Output(tenant=tenant, system_key="blog", format="cms_article",
                        status="draft", media_ids=list(media or []))
        s.add(out)
        s.commit()
        oid = out.id
        s.add(db.ArtifactBody(tenant=tenant, system_key="blog",
                              format="cms_article", output_id=oid,
                              body="<h1>Jugs</h1><p>A jug.</p>",
                              meta={"keyword": keyword, "title": "Jugs"}))
        s.commit()
    keywords.upsert(tenant, keyword)
    with db.SessionLocal() as s:
        r = (s.query(db.KeywordTarget)
             .filter(db.KeywordTarget.tenant == tenant,
                     db.KeywordTarget.phrase == keyword).first())
        r.output_id = oid
        s.commit()
    return oid


def _page(oid):
    from app.web import _article_bundle
    art, kw, ap = _article_bundle(oid)
    return " ".join(admin_ui.render_workroom(KEY, oid, art, kw, ap).split())


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")

    print("— the run no longer promises what does not exist —")
    src = __import__("pathlib").Path(skill_pack.__file__).read_text()
    # THE NOTE, NOT THE FILE. A whole-file grep for the old wording also
    # trips on the COMMENT that explains why it was wrong — which would make
    # documenting the defect forbidden, and the comment is the most valuable
    # part of the fix. So this reads the sentence the run actually emits.
    _i = src.find('ctx.note(f"no picture:')
    note = src[_i:_i + 420] if _i > 0 else ""
    ck("the note exists to be read at all", bool(note),
       "asserting on an empty slice would pass forever")
    ck("the nightly-sweep promise is gone",
       "nightly sweep" not in note,
       "there is no sweep — grep finds no caller of creative.generate or "
       "creative.batch anywhere outside creative.py, so the run was "
       "promising a thing that would never happen")
    ck("  and the workroom promise is no longer empty either",
       "press Generate the picture" in note,
       "the other half of the same sentence named a control that did not "
       "exist; it does now, and this is what points at it")
    ck("  and it says the result needs approving",
       "Review \u00b7 Pictures" in note,
       "a generated picture is proposed, not approved — saying so is the "
       "difference between a control and a surprise")

    print()
    print("— the brief has ONE writer —")
    a1 = skill_pack.article_commitment("acrylic jug", "", [], "Jugs")
    a2 = skill_pack.article_commitment("acrylic jug", "", [], "Jugs")
    ck("it is deterministic", a1 == a2, str(a1)[:80])
    ck("  a topic piece commits to its topic",
       a1.get("kind") == "topic", str(a1.get("kind")))
    ent = skill_pack.article_commitment("acrylic jug", "glassbox",
                                        ["atrium"], "Jugs")
    ck("  an entity piece commits to the entity",
       ent.get("kind") == "entity" and ent.get("key") == "glassbox",
       str(ent)[:90])
    ck("  and the companions are proof scope, not the subject",
       "atrium" in (ent.get("also") or [])
       and "atrium" in (ent.get("proof_scopes") or [])
       and ent.get("key") != "atrium",
       str(ent)[:120])

    print()
    print("— the control is on the article that has no picture —")
    oid = _article("baci", "acrylic jug")
    page = _page(oid)
    ck("the button is there", "Generate the picture" in page)
    ck("  it says why nothing was attached",
       "no approved photograph fitted this piece" in page)
    ck("  and where the result goes",
       "Review &middot; Pictures" in page or "Review · Pictures" in page)
    ck("  and that it cannot be used until approved",
       "cannot be used until you approve it" in page,
       "an unreviewed image on a page bound for a public site is what the "
       "rights ladder exists to prevent")

    with_pic = _article("baci", "melamine bowl", media=["asset_1"])
    ck("an article that HAS one is not offered another",
       "Generate the picture" not in _page(with_pic),
       "a button that regenerates over a chosen image is a way to lose it")

    print()
    print("— pressing it calls the generator, with the article's own brief —")
    real = creative.generate

    def _spy(tenant, **kw):
        _calls.append({"tenant": tenant, **kw})
        return {"ok": True, "url": "https://cdn/x.png", "asset_id": "a1",
                "assessment": {"ok": True, "failed": []},
                "review": "proposed"}
    creative.generate = _spy
    try:
        c = TestClient(web.app)
        r = c.post(f"/admin/article_picture?key={KEY}",
                   data={"output_id": oid}, follow_redirects=False)
    finally:
        creative.generate = real
    ck("it lands back on the article", r.status_code == 303
       and f"/admin/work/{oid}" in r.headers.get("location", ""),
       r.headers.get("location", "")[:80])
    ck("  the generator was actually called", len(_calls) == 1,
       f"{len(_calls)} call(s) — this is the whole defect: the function was "
       f"complete, tested, guarded, and reached by nothing")
    got = _calls[0] if _calls else {}
    ck("  briefed as an article hero",
       got.get("fmt") == "article_hero", str(got.get("fmt")))
    ck("  against the SAME commitment the run would have used",
       got.get("commitment") == skill_pack.article_commitment(
           "acrylic jug", "", [], "Jugs"),
       "a picture briefed against a different subject than the article was "
       "written against is a picture of the wrong thing — and it would look "
       "right in both places separately")
    ck("  and the reply says it is proposed, not attached",
       "PROPOSED" in r.headers.get("location", "").upper()
       or "proposed" in r.headers.get("location", ""),
       r.headers.get("location", "")[-90:])

    print()
    print("— nothing is attached to the article —")
    with db.SessionLocal() as s:
        row = s.get(db.Output, oid)
        media = list(row.media_ids or [])
    ck("the draft still carries no picture", media == [],
       "approving on Review · Pictures is what grants use; attaching here "
       "would put an unreviewed image on a page bound for a public site")

    print()
    print("— a refusal is named, not swallowed —")
    creative.generate = lambda tenant, **kw: {"ok": False,
                                              "error": "ANTHROPIC_API_KEY is not set"}
    try:
        r2 = TestClient(web.app).post(f"/admin/article_picture?key={KEY}",
                                      data={"output_id": oid},
                                      follow_redirects=False)
    finally:
        creative.generate = real
    ck("it says what stopped it",
       "ANTHROPIC_API_KEY" in r2.headers.get("location", ""),
       "a generator that fails silently is the state this replaced, one "
       "layer down")

    print()
    print("— and it is behind the admin key —")
    r3 = TestClient(web.app).post("/admin/article_picture?key=wrong",
                                  data={"output_id": oid},
                                  follow_redirects=False)
    ck("a wrong key generates nothing", "unauthorized" in r3.text,
       f"{r3.status_code} {r3.text[:50]}")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
