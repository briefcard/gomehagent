"""A structure is how an email is built, never what it says — and the library
is shared, gated per brand at the moment of use.

Owner, 2026-09-11: mimic many styles from the gallery, *"and you will need to
make sure that brand rules are respected given the structure / layout /
references you generate based on the emails. Anytime we build out new email
structures, we should save any approved structure to our collective library
of email structures so we can reuse them in the future for different copy /
campaigns."*

Three claims, each with the check that makes it more than a sentence:

  1. A structure carries no material. Its notes are refused if they identify
     an account; its brief is built from block types and shape facts only.
  2. Brand rules bind at use. A structure whose notes trip THIS brand's ban
     list, or that needs something THIS brand lacks, never reaches its
     drafter — and the drafted email still meets every gate it met before.
  3. Approval is the way in. A swipe arrives proposed; an approved send files
     its shape, once per sequence, named by what it does and not whose it was.

    python3 scripts/test_a_structure_is_how_not_what.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'es.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, email_structures as es, kb, skill_pack, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


SEQ = ["hero", "heading", "text", "products", "cta", "ps"]


def _card_for(tenant: str, strip: str = "") -> str:
    """The Brand-tab structures card; with `strip`, that structure's look is
    removed first so the card's 'not read' state can be seen."""
    from app import admin_ui
    if strip:
        with db.SessionLocal() as s:
            row = s.get(db.EmailStructure, strip)
            prof = dict(row.profile or {}); had = prof.pop("look", None)
            row.profile = prof; s.commit()
        try:
            return admin_ui._structures_card("s3cret", tenant)
        finally:
            with db.SessionLocal() as s:
                row = s.get(db.EmailStructure, strip)
                prof = dict(row.profile or {})
                if had:
                    prof["look"] = had
                row.profile = prof; s.commit()
    return admin_ui._structures_card("s3cret", tenant)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    with db.SessionLocal() as s:
        b = s.get(db.KbBrand, "baci")
        b.banned_claims = ["handmade", "hand-crafted"]
        s.commit()

    print("— a structure is filed once, in the renderer's own vocabulary —")
    a = es.file_structure(name="hero-led offer", sequence=SEQ, source="hand",
                          review="approved")
    b = es.file_structure(name="the same thing again", sequence=SEQ, source="hand",
                          review="approved")
    ck("the same sequence is one structure, however many times it is filed",
       a["ok"] and b["ok"] and b["existing"] and a["id"] == b["id"])
    ck("a block the renderer cannot build is refused by name",
       not es.file_structure(name="x", sequence=["hero", "carousel"], source="hand",
                             review="approved")["ok"])
    ck("what it requires is read off its blocks",
       set(es.requires_of(SEQ)) == {"hero", "products"}, str(es.requires_of(SEQ)))

    print("\n— it carries no material —")
    leak = es.file_structure(name="x", sequence=["heading", "text", "cta"], source="swipe",
                             review="proposed",
                             notes="Opens like bacimilanousa.com does, then asks")
    ck("notes that identify an account are refused at filing",
       not leak["ok"] and "identify an account" in leak["why"], leak.get("why", "")[:60])
    st = next(r for r in es.library() if r["id"] == a["id"])
    text = es.brief(st)
    ck("the brief is the order and the shape, never copy",
       " → ".join(SEQ) in text and "borrowed" in text
       and not any(w in text.lower() for w in ("buy now", "free shipping", "$")),
       text[:100])

    print("\n— brand rules bind at the moment of use —")
    # EACH REFUSAL ISOLATED: a sequence that requires nothing but the thing
    # under test, so the reason named is the reason meant.
    bad = es.file_structure(name="artisan showcase", sequence=["heading", "text", "cta"],
                            source="swipe", review="approved",
                            notes="A hand-crafted feel: the words do the talking")
    ok, why = es.usable_for("baci", next(r for r in es.library() if r["id"] == bad["id"]))
    ck("a structure whose notes trip THIS brand's ban list is refused for it",
       not ok and "words this brand bars" in why and "hand-crafted" in why, why[:80])
    kb.ensure_brand("eien", "Eien")
    ok2, why2 = es.usable_for("eien", next(r for r in es.library() if r["id"] == bad["id"]))
    ck("and the same structure is fine for a brand with no such rule",
       ok2, why2 or "the rule is the brand's, not the structure's")
    prods = es.file_structure(name="grid", sequence=["heading", "products", "cta"],
                              source="hand", review="approved")
    ok, why = es.usable_for("eien", next(r for r in es.library() if r["id"] == prods["id"]))
    ck("a structure that needs products is refused where there are none",
       not ok and "no products" in why, why[:70])
    ok, why = es.usable_for("eien", st)
    ck("one that leads with a picture is refused where nothing can lead with one",
       not ok and "none to lead with" in why, why[:70])
    # THE EMAIL RUN'S OWN FALLBACK COUNTS. A product with a store image leads
    # an email as its hero even with an empty picture library, and the check
    # that only read the library refused the Ayoh structure for a brand whose
    # emails were going out with a hero on them (2026-09-11).
    with db.SessionLocal() as s:
        # An entity the run would actually offer: active, approved, available —
        # the same read `kb.entities` makes for the email itself.
        from app import provenance as _prov
        s.add(db.KbEntity(tenant="eien", type="product", key="capsules",
                          name="Capsules", status="active", review=_prov.APPROVED,
                          availability="available",
                          attributes={"image": "https://cdn/x.png"}))
        s.commit()
    ok, why = es.usable_for("eien", st)
    ck("a product with a store image makes a hero-led structure usable",
       ok, why)
    with db.SessionLocal() as s:
        for e in s.query(db.KbEntity).filter(db.KbEntity.tenant == "eien").all():
            s.delete(e)
        s.commit()
    proof = es.file_structure(name="proof first", sequence=["heading", "quote", "text", "cta"],
                              source="hand", review="approved")
    ok, why = es.usable_for("eien", next(r for r in es.library() if r["id"] == proof["id"]))
    ck("one that needs proof is refused where there is no approved claim",
       not ok and "no approved claim" in why, why[:70])

    print("\n— the library chooses for a send: random unless designated —")
    kb.add_claim("eien", "Eien capsules are third-party tested.", "lab", [])
    a1 = es.file_structure(name="story letter", sequence=["heading", "text", "text", "signature"],
                           source="hand", review="approved", fits_intents=["story"],
                           fits_formats=["letter"])
    a2 = es.file_structure(name="another story", sequence=["heading", "text", "list", "signature"],
                           source="hand", review="approved", fits_intents=["story"],
                           fits_formats=["letter"])
    # THE PROPOSAL FITS EXACTLY LIKE THE APPROVED ONES, so review status is
    # the only thing keeping it out. The first version left its format at the
    # default, and the format filter excluded it before the review filter got
    # a chance — the guard on the review filter went MISSED because the test
    # passed for a reason that was not the one it claimed.
    es.file_structure(name="not yet", sequence=["heading", "list", "cta"],
                      source="swipe", review="proposed", fits_intents=["story"],
                      fits_formats=["letter"])
    pool = es.eligible("eien", intent="story", fmt="letter")
    ck("the pool is approved, usable, and fitting — the proposed one is not in it",
       {st["name"] for st in pool} == {"story letter", "another story"},
       str([st["name"] for st in pool]))
    # RANDOM, not a rotation. Owner, 2026-09-11: "random unless designated".
    # A draw over two eligible structures, repeated, must land on both — a
    # least-recently-used rule would alternate on a schedule a list could
    # learn to see; a draw is not a schedule.
    seen = {es.pick("eien", intent="story", fmt="letter")["structure"]["name"]
            for _ in range(40)}
    ck("blank draws at random from everything that fits", seen == {"story letter", "another story"},
       str(seen))
    got = es.pick("eien", intent="story", fmt="letter")
    ck("and it says it was a draw, and from how many",
       not got["designated"] and "drawn from 2" in got["why"], got["why"])
    ck("what this list just received is still never drawn again",
       es.pick("eien", intent="story", fmt="letter",
               recent_shapes=[["heading", "text", "text", "signature"]])
       ["structure"]["name"] == "another story")
    got = es.pick("eien", intent="story", fmt="letter", designated=a1["id"])
    ck("a designated structure is used by name",
       got["designated"] and got["structure"]["name"] == "story letter"
       and got["why"].startswith("designated"), got["why"])
    prods = next(r for r in es.library() if r["name"] == "grid")
    got = es.pick("eien", intent="story", fmt="letter", designated=prods["id"])
    ck("a designated one this brand may not use is REFUSED with the reason, never swapped",
       got["designated"] and got["structure"] is None
       and "not for this brand" in got["why"] and "no products" in got["why"], got["why"])
    pending = next(r for r in es.library() if r["review"] == "proposed")
    got = es.pick("eien", designated=pending["id"])
    ck("a designated one that is still a proposal is refused too",
       got["structure"] is None and "not approved" in got["why"], got["why"])
    ck("designating nothing that exists says so and designs fresh",
       es.pick("eien", designated="nope")["structure"] is None)
    got = es.pick("eien", intent="story", fmt="letter")
    es.mark_used(got["structure"]["id"])

    print("\n— the drafter receives it, and only it —")
    craft = {"intent": "story", "format": "letter", "structure": got["structure"],
             "funnel": {}, "deadline": ""}
    brief = skill_pack._craft_brief(craft)
    ck("the structure rides the craft brief the drafter reads",
       "THE STRUCTURE THIS SEND IS BUILT ON" in brief
       and got["structure"]["name"] in brief)
    ck("and nothing in it names an account", "eien" not in brief.lower()
       and "baci" not in brief.lower())

    print("\n— an approved send files its shape, named by what it does —")
    with db.SessionLocal() as s:
        s.add(db.Output(id="out-1", tenant="baci", system_key="campaign_email",
                        shape=["hero", "heading", "text", "cta", "products", "cta"],
                        angle="offer", theme="designed"))
        s.commit()
    filed = es.file_from_output("out-1")
    ck("it lands approved — the approval was the decision",
       filed["ok"] and filed["review"] == "approved", str(filed))
    row = next(r for r in es.library() if r["id"] == filed["id"])
    ck("named by shape and asks, never by the account",
       "2 asks" in row["name"] and "baci" not in row["name"].lower()
       and row["source"] == "run", row["name"])
    ck("it fits the intent and form the send had",
       row["fits_intents"] == ["offer"] and row["fits_formats"] == ["designed"])
    again = es.file_from_output("out-1")
    ck("filing the same send twice adds nothing", again["existing"] is True)

    print("\n— a swipe is read, never copied, and arrives as a proposal —")
    ok_url, why = es.swipe_url("https://reallygoodemails.com/emails/welcome-to-acme")
    ck("only one email's own page is a swipe",
       ok_url.endswith("/emails/welcome-to-acme")
       and not es.swipe_url("https://reallygoodemails.com/categories/welcome")[0]
       and not es.swipe_url("https://example.com/emails/x")[0])

    class _R:
        def __init__(self, text="", content=b"", status=200):
            self.text, self.content, self.status_code = text, content, status
            self.headers = {}
    page = ('<html><head><title>Acme welcome</title>'
            '<meta property="og:image" content="https://cdn.rge/acme.png">'
            '<meta property="og:title" content="Welcome to Acme"></head></html>')
    real_get = es.httpx.get
    es.httpx.get = lambda url, **k: (_R(page) if "reallygoodemails" in url
                                     else _R(content=b"\x89PNG\r\n\x1a\n" + b"0" * 64))
    from app import llm

    class _Reply:
        ok = True
        text = json.dumps({"sequence": ["hero", "heading", "text", "cta"],
                           "fits_intents": ["offer"], "fits_formats": ["designed"],
                           "notes": "The picture carries the opening; one ask, late.",
                           "look": {"hero": "overlay", "scale": "display",
                                    "density": "airy", "bands": True, "cta": "pill",
                                    "products": "grid3",
                                    # volunteered, and must not survive
                                    "accent": "#ff0000", "font": "Futura",
                                    "hero_style": "cinematic"}})
    real_ask = llm.ask
    llm.ask = lambda *a, **k: _Reply()
    try:
        # THROUGH THE ROUTE, not only the helper: the control the card offers
        # is the one being pressed.
        from app import web
        pressed = web.admin_email_swipe(
            key="s3cret", tenant="baci",
            url="https://reallygoodemails.com/emails/welcome-to-acme", ui=0)
        ck("the swipe control on the card swipes and reads in one press",
           pressed.get("ok") is True, str(pressed)[:100])
        with db.SessionLocal() as s:
            for r in s.query(db.EmailStructure).filter(
                    db.EmailStructure.source == "swipe").all():
                s.delete(r)
            for a in s.query(db.KbAsset).filter(db.KbAsset.kind == "email_swipe").all():
                s.delete(a)
            s.commit()
        sw = es.add_swipe("https://reallygoodemails.com/emails/welcome-to-acme")
        ck("the swipe is filed as a reference picture on the swipe board",
           sw["ok"] and sw["asset_id"], str(sw)[:80])
        with db.SessionLocal() as s:
            asset = s.get(db.KbAsset, sw["asset_id"])
            ck("reference rights, so it can never be a hero or a product",
               asset.rights == kb.REFERENCE and not kb.may_publish(asset.id)[0])
        # A PLACE TO LOOK, and NOT on a visual board: the boards feed the
        # picture ladder, and a screenshot of somebody's email is not a look
        # the brand's pictures are drawn in. It is seen beside the structure
        # it produced instead.
        ck("the swipe is its own kind, invisible to every picture read",
           kb.board(es.SWIPE_TENANT)["look"] == [] and
           not any(a.id == sw["asset_id"] for a in
                   kb.assets(es.SWIPE_TENANT, publishable_only=False, kind="image")))
        listed = [x for x in es.swipes() if x["asset_id"] == sw["asset_id"]]
        ck("and it is listed as a swipe, with its screenshot",
           listed and listed[0]["image"] == "https://cdn.rge/acme.png"
           and listed[0]["review"] == "unread", str(listed)[:80])
        rd = es.read_swipe(sw["asset_id"])
        ck("the reading lands as a PROPOSED structure",
           rd["ok"] and rd["review"] == "proposed", str(rd)[:80])
        srow = next(r for r in es.library() if r["id"] == rd["id"])
        ck("carrying the shape and the reason, and no words from the source",
           srow["sequence"] == ["hero", "heading", "text", "cta"]
           and "carries the opening" in srow["profile"]["notes"]
           and "acme" not in json.dumps(srow["profile"]).lower())
        drawn = es.pick("eien", intent="offer", fmt="designed")["structure"]
        ck("and a proposed swipe is not drawn for anyone",
           drawn is None or drawn["review"] == "approved")

        print("\n— the LOOK: a structure carries the arrangement, never a colour —")
        # Owner, 2026-09-11: the produced email *"was not anywhere near the
        # structure / styling / layout of the email reference"* — because a
        # structure carried block ORDER only. The reading now carries how the
        # blocks are arranged, in the renderer's own vocabulary.
        from app import email_render as er
        lk = srow["profile"].get("look") or {}
        ck("the reading's look is kept on the structure, every axis the renderer draws",
           lk == {"hero": "overlay", "scale": "display", "density": "airy",
                  "bands": True, "cta": "pill", "products": "grid3"}, str(lk))
        ck("a colour, a typeface or a value the renderer does not know is dropped",
           "accent" not in lk and "font" not in lk and "hero_style" not in lk
           and es.look_of({"hero": "cinematic", "cta": "PILL"}) == {"cta": "pill"})
        ck("the reader asks for exactly the renderer's axes, by name",
           all(f'"{k}"' in es._READ for k in er.LOOK)
           and all(v in es._READ for vals in er.LOOK.values()
                   for v in vals if isinstance(v, str)))
        ck("and the drafter's brief says how it will be arranged",
           "arrange it as" in es.brief(srow) and "hero overlay" in es.brief(srow))
        # A structure filed BEFORE the look existed takes it on a re-read,
        # without a second structure and without touching its review.
        with db.SessionLocal() as s:
            row = s.get(db.EmailStructure, srow["id"])
            prof = dict(row.profile or {}); prof.pop("look", None)
            row.profile = prof; row.review = "approved"; s.commit()
        again = web.admin_email_swipe(key="s3cret", tenant="baci",
                                      asset=sw["asset_id"], ui=0)
        after = next(r for r in es.library() if r["id"] == srow["id"])
        ck("'Read its look' on the card re-reads the same screenshot into the same structure",
           again.get("ok") is True and after["profile"].get("look", {}).get("hero") == "overlay"
           and after["review"] == "approved"
           and len([r for r in es.library() if r["sequence"] == srow["sequence"]]) == 1,
           str(again)[:80])
        card_look = _card_for("baci")
        ck("the card says how each structure is arranged, or that it was not read",
           "arranged: hero overlay" in card_look and "Read its look" in _card_for("baci", strip=srow["id"]))
        with db.SessionLocal() as s:  # back to proposed for the sections below
            row = s.get(db.EmailStructure, srow["id"]); row.review = "proposed"; s.commit()

        # THE RENDERER HONOURS IT — and only the arrangement moves.
        theme = {"name": "T", "colors": {"accent": "#123456"}}
        blocks = [{"type": "hero", "image": "https://x/h.jpg", "headline": "H", "sub": "S"},
                  {"type": "heading", "text": "Why", "level": 2},
                  {"type": "text", "html": "<p>B</p>"},
                  {"type": "products", "items": [{"name": "A", "url": "https://x/a",
                                                  "image": "https://x/a.jpg", "price": "$1"},
                                                 {"name": "B", "url": "https://x/b"}]},
                  {"type": "heading", "text": "More", "level": 2},
                  {"type": "cta", "label": "Go", "url": "https://x/go"}]
        base = er.render(theme, blocks)
        for axis, vals in er.LOOK.items():
            for v in vals:
                out = er.render(theme, blocks, look={axis: v})
                is_default = (v == er._LOOK_DEFAULT[axis])
                ck(f"look {axis}={v!r} {'is the house default' if is_default else 'changes the arrangement'}",
                   (out == base) if is_default else (out != base and "H" in out and "Go" in out))
        with_look = er.render(theme, blocks, look=lk)
        import re as _re
        _hexes = lambda h: set(m.lower() for m in _re.findall(r"#[0-9a-fA-F]{3,6}\b", h))
        ck("no colour the theme does not own appears under any look",
           _hexes(with_look) <= _hexes(base) and "#123456" in with_look
           and all(_hexes(er.render(theme, blocks, look={a: v})) <= _hexes(base)
                   for a, vals in er.LOOK.items() for v in vals),
           str(_hexes(with_look) - _hexes(base)))
        ck("only the overlay hero sets white type, over its scrim — no other look touches a colour",
           _re.search(r"<h1[^>]*color:#ffffff", with_look)
           and not _re.search(r"<h1[^>]*color:#ffffff", base)
           and not _re.search(r"<h1[^>]*color:#ffffff", er.render(theme, blocks, look={"cta": "pill", "bands": True})))
        banded = er.render(theme, blocks, look={"bands": True})
        bg = er._DEFAULT["colors"]["bg"]
        # section 1 = "Why" + text + products (three cells); section 2 =
        # "More" + cta, unbanded; the hero is never banded.
        ck("bands sit on every second section, painted with the theme's own page colour",
           banded.count(f'style="background:{bg};') == 3
           and base.count(f'style="background:{bg};') == 0,
           str(banded.count(f'style="background:{bg};')))
        ck("an unknown look value falls to the house default, never to a block nothing draws",
           er.render(theme, blocks, look={"hero": "cinematic", "x": 1}) == base)
        ck("the grid keeps the whole card one link and every product named",
           er.render(theme, blocks, look={"products": "grid2"}).count('href="https://x/a"') == 1
           and ">A<" in er.render(theme, blocks, look={"products": "grid2"}))

        # THE SKILL PASSES IT — the claim turned into a check: the one render
        # call in the campaign run reads the look off the picked structure.
        import ast as _ast
        src = pathlib.Path(skill_pack.__file__).read_text()
        calls = [n for n in _ast.walk(_ast.parse(src)) if isinstance(n, _ast.Call)
                 and isinstance(n.func, _ast.Attribute) and n.func.attr == "render"
                 and isinstance(n.func.value, _ast.Name) and n.func.value.id == "email_render"]
        # Not "a keyword named look is present" — `look=None` would pass
        # that. The value must be a NAME, and that name must be assigned from
        # the picked structure's profile in the same source.
        tree = _ast.parse(src)
        def _fed_from_structure(name: str) -> bool:
            for n in _ast.walk(tree):
                if (isinstance(n, _ast.Assign) and len(n.targets) == 1
                        and isinstance(n.targets[0], _ast.Name) and n.targets[0].id == name):
                    seg = _ast.get_source_segment(src, n.value) or ""
                    if 'get("structure")' in seg and '.get("look")' in seg:
                        return True
            return False
        looks = [next((k.value for k in c.keywords if k.arg == "look"), None) for c in calls]
        ck("the campaign run's render call passes the structure's look",
           calls and all(isinstance(v, _ast.Name) and _fed_from_structure(v.id) for v in looks),
           f"{len(calls)} call(s)")
    finally:
        es.httpx.get = real_get
        llm.ask = real_ask

    print("\n— the plan form offers the library, and disables what this brand may not use —")
    from app import admin_ui as _ui
    field = _ui._plan_field_input({"key": "structure", "kind": "structure",
                                   "label": "Email structure (optional)"}, "", "eien")
    ck("blank is the random draw, said plainly",
       'value="">random from the library' in field)
    ck("a structure this brand may not use is shown, disabled, with the reason",
       "not for this brand" in field and " disabled>" in field)
    ck("and one it may use is selectable by id",
       f'value="{a1["id"]}"' in field and "story letter" in field)
    from app import systems as _sy
    decl = next(f for f in _sy.CATALOG["campaign_email"]["workflow"]["plan_fields"]
                if f["key"] == "structure")
    ck("the plan field is declared, optional, its own kind",
       decl["required"] is False and decl["kind"] == "structure")

    print("\n— the card shows the library, the verdict per brand, and the controls —")
    from app import admin_ui
    card = admin_ui._structures_card("s3cret", "baci")
    ck("proposed structures wait with approve and reject beside them",
       "Waiting for you" in card and "verdict=approved" in card and "verdict=rejected" in card)
    from app import web as _web
    pending = [r for r in es.library() if r["review"] == "proposed"][0]
    said = _web.admin_email_structure(key="s3cret", tenant="baci",
                                      id=pending["id"], verdict="approved", ui=0)
    ck("and pressing Approve moves it into the library",
       "approved" in str(said.get("said", ""))
       and next(r for r in es.library() if r["id"] == pending["id"])["review"] == "approved")
    ck("each structure says whether THIS brand may use it",
       "usable here" in card and "not for this brand" in card)
    ck("the reference screenshot is shown beside the structure it produced",
       'src="https://cdn.rge/acme.png"' in card)
    ck("the swipe form on the card is the control that was pressed above",
       'action="/admin/email_swipe"' in card and "/admin/email_structure?" in card)
    ck("and the card says the library is shared, shape only",
       "shared across every account" in card and "never words" in card)

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
