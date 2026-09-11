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
    ck("one that leads with a picture is refused where nothing can illustrate",
       not ok and "cannot illustrate" in why, why[:70])
    proof = es.file_structure(name="proof first", sequence=["heading", "quote", "text", "cta"],
                              source="hand", review="approved")
    ok, why = es.usable_for("eien", next(r for r in es.library() if r["id"] == proof["id"]))
    ck("one that needs proof is refused where there is no approved claim",
       not ok and "no approved claim" in why, why[:70])

    print("\n— the library chooses for a send: approved, usable, fitting, rotating —")
    kb.add_claim("eien", "Eien capsules are third-party tested.", "lab", [])
    es.file_structure(name="story letter", sequence=["heading", "text", "text", "signature"],
                      source="hand", review="approved", fits_intents=["story"],
                      fits_formats=["letter"])
    es.file_structure(name="not yet", sequence=["heading", "list", "cta"],
                      source="swipe", review="proposed")
    got = es.pick("eien", intent="story", fmt="letter")
    ck("it picks an approved structure that fits and that the brand can use",
       got is not None and got["name"] == "story letter", str(got and got["name"]))
    ck("a proposed one is never picked",
       all(r["review"] == "approved" for r in [got]) and
       es.pick("eien", intent="proof", fmt="designed") is not None)
    ck("what this list just received is not picked again",
       es.pick("eien", intent="story", fmt="letter",
               recent_shapes=[["heading", "text", "text", "signature"]]) is None
       or es.pick("eien", intent="story", fmt="letter",
                  recent_shapes=[["heading", "text", "text", "signature"]])["name"] != "story letter")
    es.mark_used(got["id"])
    es.file_structure(name="another story", sequence=["heading", "text", "list", "signature"],
                      source="hand", review="approved", fits_intents=["story"],
                      fits_formats=["letter"])
    ck("the least recently used goes first, so one favourite never wins forever",
       es.pick("eien", intent="story", fmt="letter")["name"] == "another story")

    print("\n— the drafter receives it, and only it —")
    craft = {"intent": "story", "format": "letter", "structure": got,
             "funnel": {}, "deadline": ""}
    brief = skill_pack._craft_brief(craft)
    ck("the structure rides the craft brief the drafter reads",
       "THE STRUCTURE THIS SEND IS BUILT ON" in brief and "story letter" in brief)
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
                           "notes": "The picture carries the opening; one ask, late."})
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
        rd = es.read_swipe(sw["asset_id"])
        ck("the reading lands as a PROPOSED structure",
           rd["ok"] and rd["review"] == "proposed", str(rd)[:80])
        srow = next(r for r in es.library() if r["id"] == rd["id"])
        ck("carrying the shape and the reason, and no words from the source",
           srow["sequence"] == ["hero", "heading", "text", "cta"]
           and "carries the opening" in srow["profile"]["notes"]
           and "acme" not in json.dumps(srow["profile"]).lower())
        ck("and a proposed swipe is not picked for anyone",
           all(r["review"] == "approved"
               for r in [es.pick("eien", intent="offer", fmt="designed") or {"review": "approved"}]))
    finally:
        es.httpx.get = real_get
        llm.ask = real_ask

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
    ck("the swipe form on the card is the control that was pressed above",
       'action="/admin/email_swipe"' in card and "/admin/email_structure?" in card)
    ck("and the card says the library is shared, shape only",
       "shared across every account" in card and "never words" in card)

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
