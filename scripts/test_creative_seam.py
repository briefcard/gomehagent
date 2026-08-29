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

    print("\n— the prompt is built from the account, not typed —")
    brief = creative.brief_for(
        "baci", entity_key="zodiac-vibe-cup",
        claim="Every piece is dishwasher safe.",
        situation="a long lunch that ran into the evening",
        audience_key="hosts")
    ck("it names the subject from the catalogue",
       "Zodiac Vibe cup" in brief["prompt"])
    ck("…and its own description, not ours",
       "zodiac sign" in brief["prompt"].lower())
    ck("…and constrains the picture with the claim",
       "dishwasher safe" in brief["prompt"]
       and "contradict" in brief["prompt"],
       "a photograph arguing something the copy cannot say is worse than no "
       "photograph")
    ck("…and the moment", "long lunch" in brief["prompt"])
    ck("no text or logos, ever",
       "no text of any kind" in brief["prompt"])
    ck("what is missing is NAMED, not silently dropped",
       any("brand theme colours" in t for t in brief["thin"]),
       "a brief built from three of five inputs is a weaker brief and the "
       "run is the only place that can say so")
    ck("a subject with no catalogue entry says so",
       any("nothing to be OF" in t for t in
           creative.brief_for("baci", entity_key="no-such-thing")["thin"]))

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

    print("\n— and spares are droppable without losing what is in use —")
    kept = media.put("baci", b"KEEP" + PNG)
    kb.add_asset("baci", kept["url"], rights="owned", title="in use",
                 kind="image")
    spare = media.put("baci", b"SPARE" + PNG)
    # `sweep` floors the window at one day on purpose — a caller passing 0
    # must not be able to empty the table — so the age is made real rather
    # than the floor lowered to suit the test.
    import datetime as _dt
    with db.SessionLocal() as _s:
        for _bid in (kept["id"], spare["id"]):
            _row = _s.get(db.MediaBlob, _bid)
            _row.created_at = db.utcnow() - _dt.timedelta(days=400)
        _s.commit()
    swept = media.sweep(days=30)
    ck("an unreferenced blob can be dropped",
       swept["dropped"] >= 1 and media.get(spare["id"])[0] == b"",
       str(swept))
    ck("…and one an asset points at is kept",
       media.get(kept["id"])[0] != b"",
       "once the platform has copied it our bytes are a spare, but a spare "
       "for something nobody published yet is not spare at all")

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
