"""An ad is allowed to look like an ad, and a person-led frame gets a person.

Owner, 2026-09-05: *"everything is trying to pretend to be a real photo instead
of an ad."* That was not a description of a model's failure. `brief_for`
appended "Photographic and real." to EVERY brief including `ad_frame`, and the
`craft` criterion asked "does it look like a photograph somebody was paid to
take, or like generic stock?" — both answers are photographs, so a frame that
looked like an AD was marked down by our own reviewer. The prompt and the gate
agreed with each other and both disagreed with the owner.

The line is CORRECT for an article hero, which must read as journalism. So the
treatment moved onto the format, and the craft question followed it.

And the second half, which is the one that bites if done carelessly.
`_PLATE_RULE` was one string carrying two prohibitions with opposite scopes —
"invent no product", which must hold for every frame, and "no people, the
foreground is empty", which is only true of a plate about to receive a
photograph. Concatenated unconditionally, `'no people' in prompt` was true for
every cell including `person_led`, whose own brief says a person is the
subject; Miami Ironside, which gets only the person-led and context cells, had
every frame commissioned as an empty room with nobody in it.

MOVING THE WHOLE STRING BEHIND `for_product` IS THE REGRESSION, not the fix:
it would free the model to invent a product in every non-composited frame,
which is the failure this architecture was built after. These assertions exist
to catch that specific mistake.

    python3 scripts/test_an_ad_may_look_like_an_ad.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ad.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import creative, db, imagegen, systems, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _plate_prompt(**kw) -> str:
    sent: dict = {}
    imagegen.post = lambda path, **k: (sent.update(k.get("json_body") or {})
                                       or {"ok": True, "images": [b"x"]})
    imagegen.plate("a warm room with a long table", **kw)
    return sent.get("prompt", "")


def main() -> int:
    db.init_db()
    tenants.seed()
    systems.create("baci", "ad_creative")

    print("— an ad is no longer told to be a photograph —")
    ad = creative.brief_for("baci", fmt="ad_frame", positioning="p")
    art = creative.brief_for("baci", fmt="article_hero", positioning="p")
    body = creative.brief_for("baci", fmt="article_body", positioning="p")
    ck("the ad brief does NOT say 'Photographic and real'",
       "Photographic and real" not in ad["prompt"], ad["prompt"][-90:])
    ck("  and says it is an advertisement and may look like one",
       "ADVERTISEMENT AND MAY LOOK LIKE ONE" in ad["prompt"], "")
    ck("  and asks for a clear band where the headline will go",
       "headline will be set" in ad["prompt"], "")
    ck("an ARTICLE hero still is — journalism is the right answer there",
       "Photographic and real" in art["prompt"]
       and "Photographic and real" in body["prompt"], "")
    ck("no format may render its own lettering",
       all("NO text, lettering" in b["prompt"] for b in (ad, art, body)),
       "the type layer is a person's job, not the image model's")

    print("\n— and the gate stops grading toward a photograph —")
    asks = {c["key"]: c["ask"] for c in ad["criteria"]}
    ck("the ad's craft question judges it as an AD",
       "as an ad" in asks["craft"] and "graphic" in asks["craft"],
       asks["craft"][:70])
    ck("  and does not ask whether it looks like a photograph",
       "look like a photograph" not in asks["craft"], "")
    ck("the article's craft question is untouched",
       "photograph somebody was paid to take"
       in {c["key"]: c["ask"] for c in art["criteria"]}["craft"], "")
    ck("  so the two formats really are asked different things",
       asks["craft"] != {c["key"]: c["ask"] for c in art["criteria"]}["craft"])

    print("\n— THE REGRESSION GUARD: no frame may invent a product —")
    person = _plate_prompt(with_people=True)
    context = _plate_prompt()
    forprod = _plate_prompt(for_product=True)
    ck("EVERY framing is told to invent no product",
       all("Do not invent" in p for p in (person, context, forprod)),
       "moving the whole rule behind for_product is the regression")
    ck("  including the two Ironside and Coverings actually get",
       "Do not invent" in person and "Do not invent" in context,
       "they have no cut-outable product, so they get ONLY these two cells")

    print("\n— and only a plate receiving a photograph is emptied —")
    ck("a person-led frame is NOT told there are no people",
       "no people in the frame" not in person, person[-100:])
    ck("  it is told a person IS the subject",
       "A PERSON IS THE SUBJECT" in person, "")
    ck("  because deleting a prohibition is not asking for the thing",
       "not an empty room" in person, "")
    ck("a plate that will RECEIVE a photograph is emptied, and of people",
       "no people in the frame" in forprod
       and "COMPLETELY EMPTY" in forprod, "")
    ck("  and is lit and framed for the photograph coming into it",
       "REAL PHOTOGRAPH OF A PRODUCT WILL BE PLACED" in forprod, "")
    ck("a context frame is told neither — it is simply a place",
       "no people in the frame" not in context
       and "A PERSON IS THE SUBJECT" not in context, "")

    print("\n— the batch asks for the right one per cell —")
    import inspect
    src = inspect.getsource(creative.batch)
    ck("the framing decides whether people are asked for",
       'with_people=cell["framing"] in PEOPLE_ARE_THE_SUBJECT' in src, "")
    ck("  and person_led is the framing that means it",
       creative.PEOPLE_ARE_THE_SUBJECT == ("person_led",),
       str(creative.PEOPLE_ARE_THE_SUBJECT))
    ck("  and the seam forwards it, not merely accepts it",
       "with_people=with_people" in inspect.getsource(creative._plates),
       "a parameter accepted and not forwarded is this codebase's own defect")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
