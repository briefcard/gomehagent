"""An audience says which products it is for, and that beats alphabetical.

Owner, 2026-09-01: *"some audiences are more associated with different entities
so maybe help to have a 'recommended entities' selector in the audiences."*

It answers the one selection in this pipeline that had NO DECISION BEHIND IT.
With no entity on the plan, `_run_campaign_email` offered the catalogue's first
six sorted by "has a photograph, then alphabetically" — and its own note said
so: *"the catalogue's top available items are featured"*. Alphabetical order is
not a judgement about who is reading; a recommendation somebody entered is.

THREE THINGS IT DELIBERATELY IS NOT, and each is asserted:

  · Not a restriction — a plan's Featured entity still outranks it, the way a
    plan outranks every picker here. This only changes what is OFFERED when
    nobody named anything.
  · Not a filter that can empty the offer — a recommendation whose products
    are all out of stock falls back to the catalogue. An email with no
    products because the shortlist went out of stock is a worse answer than
    the one this replaced.
  · Not free text — a mistyped key would intersect with nothing and read
    exactly like "none set", so the console is a checklist over the real
    catalogue and the writer refuses an unknown key by name.

ORDER IS THE RECOMMENDATION. The rows come back in the order they were
entered, and the offer is not re-sorted: the first entity named is the one this
buyer is most for, and re-sorting by photograph would put the decision back
where it started.

Run: python3 scripts/test_audience_entities.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ae.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui, db, kb, tenants, web  # noqa: E402

KEY = "s3cret"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.add_audience("baci", "wedding_planner", "Wedding planners",
                    ["timelines"], ["tablescape"], origin="human")
    kb.add_audience("baci", "office_manager", "Office managers",
                    ["budget"], ["breakroom"], origin="human")
    # `available` is the word `kb.entities(available_only=True)` filters on;
    # anything else is unavailable. Writing "in_stock" here made every
    # assertion below fail against a correct implementation — a fixture in the
    # wrong vocabulary tests nothing but itself.
    for k, n, avail in (("zebra_platter", "Zebra platter", "available"),
                        ("amber_flute", "Amber flute", "available"),
                        ("cake_stand", "Cake stand", "available"),
                        ("gone_bowl", "Gone bowl", "out_of_stock")):
        kb.add_entity("baci", "product", k, n, origin="human")
        with db.SessionLocal() as s:
            r = (s.query(db.KbEntity)
                 .filter(db.KbEntity.tenant == "baci",
                         db.KbEntity.key == k).first())
            r.availability = avail
            s.commit()

    print("— the recommendation is recorded, in the order it was given —")
    said = kb.set_audience_entities("baci", "wedding_planner",
                                    ["cake_stand", "amber_flute"])
    ck("it saves", "2 recommended" in said, said)
    got = [e.key for e in kb.audience_entities("baci", "wedding_planner")]
    ck("and comes back in THAT order, not alphabetical",
       got == ["cake_stand", "amber_flute"],
       f"{got} — the first named is the one this buyer is most for; "
       f"re-sorting would put the decision back where it started")
    ck("an audience with none set recommends nothing",
       kb.audience_entities("baci", "office_manager") == [],
       "empty is a real answer — the caller falls back to the catalogue")

    print()
    print("— a key naming nothing is refused, not saved —")
    bad = kb.set_audience_entities("baci", "wedding_planner",
                                   ["cake_stand", "typo_key"])
    ck("it says which key", "typo_key" in bad, bad)
    ck("  and changes nothing",
       [e.key for e in kb.audience_entities("baci", "wedding_planner")]
       == ["cake_stand", "amber_flute"],
       "a saved typo intersects with nothing and reads exactly like "
       "'none set' — the failure would be invisible")

    print()
    print("— out of stock drops out; it never empties the offer —")
    kb.set_audience_entities("baci", "office_manager", ["gone_bowl"])
    ck("the recommendation is stored as given",
       [str(k) for k in (kb.audiences("baci") and
        [a for a in kb.audiences("baci")
         if a.key == "office_manager"][0].entity_keys or [])] == ["gone_bowl"],
       "the buyer is still for it; it is simply not sellable today")
    ck("  but an unavailable one is not offered",
       kb.audience_entities("baci", "office_manager") == [],
       "so the caller falls back to the catalogue — an email with no products "
       "because the shortlist went out of stock is worse than the guess this "
       "replaced")
    ck("  and it comes back when it is back",
       len(kb.audience_entities("baci", "office_manager",
                                available_only=False)) == 1,
       "the record is the association, not the stock level")

    print()
    print("— clearing is a decision the form can express —")
    kb.set_audience_entities("baci", "wedding_planner", [])
    ck("an empty save clears rather than refusing",
       kb.audience_entities("baci", "wedding_planner") == [],
       "a form that cannot say 'none of these any more' makes the first save "
       "permanent")
    kb.set_audience_entities("baci", "wedding_planner",
                             ["cake_stand", "amber_flute"])

    print()
    print("— the selector is on the audience, in the console —")
    page = " ".join(admin_ui.render_kb(KEY, "baci").split())
    ck("the control is there", "Recommended entities" in page)
    ck("  it says how many are set", "2 set" in page, "folded when none")
    ck("  it is a checklist over the real catalogue, not free text",
       'name="entity_keys" value="cake_stand"' in page
       and 'name="entity_keys" value="zebra_platter"' in page,
       "a mistyped key would read exactly like none set")
    ck("  the ones chosen are checked",
       'value="cake_stand" checked' in page)
    ck("  and it says it is a recommendation, not a rule",
       "not a rule" in page and "Featured entity still" in page,
       "state what it does NOT do, on the control — a person reading this "
       "needs to know a plan still wins")

    print()
    print("— and the route saves what the form posts —")
    c = TestClient(web.app)
    r = c.post(f"/admin/kb_audience_entities?key={KEY}",
               data={"tenant": "baci", "audience_key": "office_manager",
                     "entity_keys": ["zebra_platter", "cake_stand"]},
               follow_redirects=False)
    ck("it redirects back to the tab", r.status_code == 303,
       r.headers.get("location", ""))
    ck("  and the recommendation stuck",
       [e.key for e in kb.audience_entities("baci", "office_manager")]
       == ["zebra_platter", "cake_stand"])
    # A FRESH CLIENT. `TestClient` keeps a cookie jar, and `admin_key` accepts
    # the console cookie as well as the query key — so reusing `c` here would
    # have authenticated on the cookie the signed-in session already held and
    # passed while proving nothing about the key.
    r2 = TestClient(web.app).post(
        "/admin/kb_audience_entities?key=wrong",
        data={"tenant": "baci", "audience_key": "office_manager",
              "entity_keys": []}, follow_redirects=False)
    ck("  and it is behind the admin key",
       "unauthorized" in r2.text
       and [e.key for e in kb.audience_entities("baci", "office_manager")]
       == ["zebra_platter", "cake_stand"],
       f"{r2.status_code} {r2.text[:60]}")

    print()
    print("— and it reaches the drafter, where the guess used to be —")
    # THE ASSERTION THAT MATTERS. Everything above is storage; this is the one
    # place the recommendation changes an output. Driven through the skill's
    # own picker seam (`_last_ents`) rather than by reading source, because a
    # source assertion would pass on a wiring that never ran.
    from app import esp, skill, skill_pack, systems

    # The ESP seam, the way `test_campaign_email` drives it: the subject here
    # is which PRODUCTS get offered, and a real connection is a different one.
    esp.provider_for = lambda t: "omnisend"
    esp.personalize = lambda t, html: {"ok": True, "html": html}

    class _Mod:
        @staticmethod
        def draft_from_html(tenant, *, name, subject, sender_name, html,
                            preheader="", include_segments=None):
            return {"ok": True, "campaign_id": "camp_1", "stage": "done"}
    esp.backend = lambda t: (_Mod, "")
    # `campaign_email` declares `requires: esp`, and that is checked against
    # the CREDENTIAL store — a module-level stub does not connect anything.
    # Without this the run refuses before ever choosing products, and the two
    # assertions below would have passed on an empty list.
    from app import credentials as _cr
    with db.SessionLocal() as sx:
        sx.add(db.Credential(tenant="baci", provider="omnisend", site="",
                             kind="api_key", secret=_cr._encrypt("k"),
                             meta={}, scopes="", status="active",
                             granted_at=db.utcnow()))
        sx.commit()
    row = systems.find("baci", "campaign_email") or \
        systems.create("baci", "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        b = s.get(db.KbBrand, "baci")
        b.positioning = "Mid-century tableware."
        b.voice = {"tone": ["plain"]}
        b.banned_claims = ["handmade"]
        s.commit()
    kb.add_claim("baci", "Baci pieces are dishwasher safe.", "lab report", [])
    skill_pack.draft_campaign = lambda *a, **k: {
        "subject": "A note about your table",
        "preheader": "Inside",
        "body": "<p>Baci pieces are dishwasher safe.</p>"}

    # The audience recommends the LAST item alphabetically, so a picker that
    # ignored the recommendation would offer something else first.
    def _products_note(**kw):
        """What the run said about choosing products. Read from the RUN, not
        from a module global: `_last_ents` is set further down the same
        function and a failure after the choice — a stubbed drafter returning
        a shape the renderer does not take, say — would leave it empty and
        every assertion here passing on nothing."""
        r = skill.run("campaign_email", "baci", segment="office_manager",
                      audience_key="office_manager", **kw)
        return next((str(n) for n in (r.get("notes") or [])
                     if str(n).startswith("products: ")), "")

    kb.set_audience_entities("baci", "office_manager", ["zebra_platter"])
    said = _products_note()
    ck("the audience's recommendation is what gets offered",
       "recommended for" in said and "Zebra" in said
       and "Amber" not in said and "Cake" not in said,
       f"{said!r} — alphabetically 'Amber flute' and 'Cake stand' both come "
       f"first, so this cannot be passing on the old sort order")

    kb.set_audience_entities("baci", "office_manager", [])
    said2 = _products_note()
    ck("  with none set it falls back to the catalogue, not to nothing",
       "catalogue" in said2, f"{said2!r} — the guess it replaced is still the "
       f"right answer when nobody has made the decision")
    ck("  and it says a guess was made",
       "nobody has said" in said2,
       "the branch that guesses must say so where the choice happens, not in "
       "a note further down that a failed run never reaches")
    ck("  and the fallback names both ways to make the decision",
       "Featured entity" in said2 and "recommended entities" in said2,
       "the note is where somebody reads that this was a guess, so it is "
       "where the two fixes belong")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
