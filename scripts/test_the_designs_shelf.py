"""The references sit on a shelf: one action a row, everything else in a menu.

Owner, 2026-09-23, looking at the Designs room: *"extremely messy, with so
many competing buttons and no clear menu workflow. Instead we should have a
sub menu to edit / delete / reread reference. What else should we do to make
it a very clear workflow? Rename feature? pagination? meta description?"*

Measured before the rewrite, with seven references on the page: 29 buttons,
13 forms, 7 dropdowns, 28 links and every recreation's findings and rounds
unfolded underneath. Each row repeated the same four buttons.

What this suite holds shut:

  · a row carries the FACTS, ONE action — the one belonging to the state it
    is in — and a menu; the counts are computed off the rendered page, so a
    fifth button added to a row fails here rather than on the owner's screen;
  · what needs room (the reference beside ours, the judge, the rounds) is on
    the reference's own page and NOT in the list;
  · the shelf searches, sorts, filters and pages, and the filter chips count
    the population rather than the filtered remainder;
  · a rename and a note are real: the name is the owner's, and the note
    reaches the maker rather than decorating a card;
  · IN OR OUT IS PER BRAND. The library is shared; until this change "Not
    this one" set the shared row to rejected and took the design away from
    every account at once.

    python3 scripts/test_the_designs_shelf.py
"""
import io
import os
import re
import sys
import tempfile
from urllib.parse import unquote

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'shelf.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient                        # noqa: E402

from app import admin_ui as ui, db, email_structures as es, media, tenants, web  # noqa: E402

KEY = "s3cret"
_fail: list = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _png(w=240, h=560):
    from PIL import Image
    im = Image.new("RGB", (w, h), (235, 226, 214))
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


def _visible(html: str) -> str:
    """The page as it LOOKS: the menus are folds, and a fold is shut — a
    row's menu, and the one fold that starts the library over."""
    return re.sub(r'<details class="(?:fix|startover)">.*?</details>', "", html, flags=re.S)


def main() -> int:
    db.init_db()
    tenants.seed()
    c = TestClient(web.app)
    names = ["Sauce the meat", "Decaf risk free", "Pistol shrimp quiz", "One promise",
             "The seasonal edit", "Welcome in three", "The founder's letter",
             "A ninth design", "A tenth design"]
    ids = []
    with db.SessionLocal() as s:
        for i, name in enumerate(names):
            url = media.put("baci", _png())["url"]
            a = db.KbAsset(tenant="baci", kind="image", subject="reference",
                           rights="reference", title=name, url=url, review="approved")
            s.add(a); s.flush()
            st = db.EmailStructure(name=name, source="reallygoodemails.com",
                                   source_url=f"https://reallygoodemails.com/emails/{i}",
                                   source_asset_id=a.id,
                                   review="approved" if i < 7 else "proposed",
                                   sequence=["hero", "ask"], brief={"concept": name},
                                   used_count=i)
            s.add(st); s.flush(); ids.append(st.id)
        s.commit()

    print("— the page the owner complained about, counted —")
    page = ui._structures_card(KEY, "baci", view={})
    vis = _visible(page)
    rows = len(re.findall(r'class="msg"', page))
    buttons = len(re.findall(r"<button", vis))
    ck("the shelf pages rather than laying every reference out",
       rows == ui.SHELF_PAGE, f"{rows} rows for {len(ids)} references")
    ck("  and one row offers ONE action, with the rest in its menu",
       buttons <= rows + 2, f"{buttons} buttons visible for {rows} rows "
                            f"(it was 29 for 7 rows)")
    ck("  every row has a menu", len(re.findall(r'<details class="fix">', page)) == rows)
    ck("  the judge's findings and the rounds are NOT in the list",
       "open finding" not in page and "round(s)" not in page,
       "they are what made the old room unreadable")
    ck("  and each row links to the page that does carry them",
       page.count("/systems/campaign_email/designs/") >= rows)

    print("\n— the states, and the one action each of them wants —")
    es.designate("baci", ids[1])
    es.set_out("baci", ids[2], True)
    page = ui._structures_card(KEY, "baci", view={})
    ck("the standing design offers the way back to random",
       "Back to random" in page and "every campaign uses this" in page)
    ck("one in the rotation offers the standing choice",
       "Use for every campaign" in page)
    ck("one taken out offers its way back",
       "Put back in the rotation" in page and "out of this brand" in page)
    ck("one nobody has chosen offers the choice",
       "Use it" in page and "not chosen yet" in page)

    print("\n— search, sort, filter, page —")
    ck("search narrows to what it matches",
       len(re.findall(r'class="msg"', ui._structures_card(KEY, "baci", view={"q": "shrimp"}))) == 1)
    by_name = ui._structures_card(KEY, "baci", view={"sort": "name"})
    first = re.search(r'<b><a [^>]*>([^<]+)</a></b>', by_name).group(1)
    ck("by name sorts by name", first.startswith("A ninth"), first)
    by_used = ui._structures_card(KEY, "baci", view={"sort": "used"})
    ck("most used sorts by use",
       re.search(r'<b><a [^>]*>([^<]+)</a></b>', by_used).group(1) == names[-1])
    filtered = ui._structures_card(KEY, "baci", view={"state": "out"})
    ck("a filter shows only that state",
       len(re.findall(r'class="msg"', filtered)) == 1)
    ck("  and the chips still count the whole shelf, not the remainder",
       re.search(r'>In rotation (\d+)<', filtered).group(1) != "0",
       "a chip that reads 0 because its own filter is on says the shelf is empty")
    p2 = ui._structures_card(KEY, "baci", view={"page": "2"})
    ck("page two is the rest of them",
       len(re.findall(r'class="msg"', p2)) == len(ids) - ui.SHELF_PAGE)
    ck("  and the pager keeps the filter it was paging",
       "dstate=out" in ui._structures_card(KEY, "baci", view={"state": "out", "page": "1"})
       or len(re.findall(r'class="msg"', filtered)) <= ui.SHELF_PAGE)

    print("\n— rename —")
    r = c.post("/admin/reference_rename", params={"key": KEY},
               data={"tenant": "baci",
                                                "id": ids[0], "name": "The four-step story"},
               follow_redirects=False)
    ck("renaming posts and comes back to the shelf",
       r.status_code == 303 and "/designs" in r.headers.get("location", ""))
    ck("  and the owner's name is what the shelf shows, and what search finds",
       "The four-step story" in ui._structures_card(KEY, "baci", view={"q": "four-step"}))
    ck("  an empty name is refused rather than silently blanking it",
       "err=" in c.post("/admin/reference_rename", params={"key": KEY},
               data={"tenant": "baci", "id": ids[0], "name": "  "},
                        follow_redirects=False).headers.get("location", ""))

    print("\n— the note is not decoration —")
    r = c.post("/admin/reference_note", params={"key": KEY},
               data={"tenant": "baci", "id": ids[0],
                     "note": "the four-step story, never the mascot"},
               follow_redirects=False)
    ck("a note posts and is kept", r.status_code == 303
       and es.note_of(ids[0]) == "the four-step story, never the mascot")
    ck("  it is shown where the reference is", "never the mascot"
       in ui._structures_card(KEY, "baci", view={}))
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "app", "recreate.py"), encoding="utf-8").read()
    ck("  and it REACHES THE MAKER — every email built on this design hears it",
       "_es_note(structure_id)" in src and 'kit_["_notes"]' in src,
       "a field that only sat on a card would be the same defect as a KB rule "
       "that never reaches a validator")
    ck("  emptying it clears it", not c.post(
        "/admin/reference_note", data={"key": KEY, "tenant": "baci", "id": ids[0], "note": ""},
        follow_redirects=False) is None and es.note_of(ids[0]) == "")

    print("\n— in or out is THIS brand's decision —")
    r = c.post("/admin/reference_rotation", params={"key": KEY},
               data={"tenant": "baci", "id": ids[3]}, follow_redirects=False)
    ck("taking one out posts and says so", r.status_code == 303
       and "rotation" in r.headers.get("location", ""))
    ck("  it leaves this brand's rotation",
       ids[3] not in {x["id"] for x in es.eligible("baci")})
    ck("  and another account still draws on it — the library is shared, the "
       "decision is not",
       ids[3] in {x["id"] for x in es.eligible("eien")},
       "'Not this one' used to set the shared row to rejected")
    ck("  the design itself is untouched in the library",
       next(x for x in es.library() if x["id"] == ids[3])["review"] == "approved")
    c.post("/admin/reference_rotation", params={"key": KEY},
               data={"tenant": "baci", "id": ids[3], "back_in": "1"},
           follow_redirects=False)
    ck("  and it comes back", ids[3] in {x["id"] for x in es.eligible("baci")})
    es.designate("baci", ids[4])
    c.post("/admin/reference_rotation", params={"key": KEY},
               data={"tenant": "baci", "id": ids[4]},
           follow_redirects=False)
    ck("taking out the STANDING design frees the standing choice rather than "
       "leaving every campaign pointed at a design this brand no longer draws",
       es.standing_designation("baci") == "")

    print("\n— delete —")
    es.designate("baci", ids[5])
    r = c.post("/admin/reference_delete", params={"key": KEY},
               data={"tenant": "baci", "id": ids[5]},
               follow_redirects=False)
    ck("deleting posts and says what went", r.status_code == 303
       and "deleted" in r.headers.get("location", ""))
    ck("  it is gone from the library", ids[5] not in {x["id"] for x in es.library()})
    ck("  and the brand that stood on it draws at random again, told so",
       es.standing_designation("baci") == "")
    ck("deleting something that is not there says so, rather than pretending",
       "err=" in c.post("/admin/reference_delete", params={"key": KEY},
               data={"tenant": "baci", "id": "nope"},
                        follow_redirects=False).headers.get("location", ""))

    print("\n— ONE answer to 'which designs may this brand use' —")
    # Owner, 2026-09-23: "Do we have consistency in the designs in rotation in
    # the design tab and the options available in the dropdown for the brand
    # when proposing an email plan?" We did not: four readers asked the
    # question four ways, and the plan's dropdown and a plan that NAMED a
    # design both missed the per-brand rotation. The population here is
    # every design in the library, and each surface is read, not assumed.
    from app import systems as _sy
    es.designate("baci", "")
    es.set_out("baci", ids[6], True)             # taken out by this brand
    lib = es.library()
    shelf_html = "".join(ui._structures_card(KEY, "baci", view={"page": str(p_)})
                         for p_ in range(1, 4))
    shelf_rotation = set()
    for st in lib:
        row = shelf_html.split(f"/designs/{st['id']}", 1)
        if len(row) > 1 and "in the rotation" in row[1][:900].split('class="msg"')[0] \
                or (len(row) > 1 and "every campaign uses this" in row[1][:900].split('class="msg"')[0]):
            shelf_rotation.add(st["id"])
    # the REAL field, read off the workflow the plan form is built from
    field = next(f for f in _sy.workflow("campaign_email")["plan_fields"]
                 if f["key"] == "structure")
    dropdown = ui._plan_field_input(field, "", "baci")
    offered = {m.group(1) for m in re.finditer(r'<option value="([^"]+)"(?![^>]*disabled)', dropdown)}
    drawn = {st["id"] for st in es.eligible("baci")}
    standable = {st["id"] for st in lib if "until you say" in es.designate("baci", st["id"])}
    es.designate("baci", "")
    built = {st["id"] for st in lib
             if (es.pick("baci", designated=st["id"])["structure"] or {}).get("id") == st["id"]}
    ck("the shelf's rotation IS the random draw",
       shelf_rotation == drawn, f"shelf {len(shelf_rotation)} · draw {len(drawn)}")
    ck("  IS what the plan's dropdown offers",
       offered == drawn, f"offered {len(offered)} · draw {len(drawn)} · "
       f"extra {sorted(offered - drawn)[:2]}")
    ck("  IS what can be made the standing choice",
       standable == drawn, f"standable {len(standable)}")
    ck("  IS what a plan naming one actually builds on",
       built == drawn, f"built {len(built)}")
    ck("a design this brand took out is offered NOWHERE, and says why where it is listed",
       ids[6] not in offered and "taken out of this brand" in dropdown)
    ck("  and a plan that names it is refused by name rather than quietly built",
       "taken out of this brand" in es.pick("baci", designated=ids[6])["why"])
    es.designate("baci", sorted(drawn)[0])
    stand = next(st["name"] for st in lib if st["id"] == sorted(drawn)[0])
    ck("the blank option says what blank DOES — the standing choice when there is one",
       f"the standing choice — {stand}" in ui._plan_field_input(field, "", "baci"),
       "it said 'random from the library' while every campaign used one design")
    es.designate("baci", "")
    ck("  and a random draw when there is not",
       "a random draw from this brand" in ui._plan_field_input(field, "", "baci"))

    print("\n— the reference's own page —")
    r = c.get(f"/admin/reference?key={KEY}&tenant=baci&id={ids[0]}")
    ck("it opens", r.status_code == 200 and "The four-step story" in r.text)
    ck("  inside the console frame, not as a bare fragment",
       "<html" in r.text.lower() and "sidebar" in r.text.lower())
    ck("  it carries what the list does not: the reference, and the way back",
       "every design" in r.text and "the reference" in r.text)
    gone = c.get(f"/admin/reference?key={KEY}&tenant=baci&id=nope")
    ck("a design that is gone says so instead of rendering an empty page",
       gone.status_code == 200 and "No such design" in gone.text)

    print("\n— start over: every design, with the links kept to add again —")
    # Owner, 2026-09-30: "I'm going to delete all email references from the
    # DB … so we can process them the way we have them set up in the later
    # iterations."
    from app import jobs, kb
    left = [st["id"] for st in es.library()]
    with db.SessionLocal() as s:
        owned = db.KbAsset(tenant="baci", kind="image", subject="photo", rights=kb.OWNED,
                           title="the brand's own table", url="https://cdn.example.test/own.jpg",
                           review="approved")
        swipe = db.KbAsset(tenant=es.SWIPE_TENANT, kind=es.SWIPE_KIND, subject="scene",
                           rights=kb.REFERENCE, title="a swipe that never became a design",
                           url="https://images.example.test/never.png", review="approved")
        s.add_all([owned, swipe]); s.flush()
        own_id, swipe_id = owned.id, swipe.id
        s.get(db.EmailStructure, left[0]).source_asset_id = own_id
        ref_ids = [s.get(db.EmailStructure, i).source_asset_id for i in left[1:]]
        made = db.Recreation(tenant="baci", structure_id=left[1], status="kept")
        s.add(made); s.flush(); made_id = made.id
        s.commit()
    es.designate("baci", left[2])
    es.set_out("baci", left[3], True)
    page = ui._structures_card(KEY, "baci", view={})
    fold = re.search(r'<details class="startover">(.*?)</details>', page, re.S)
    ck("the shelf offers to start over, folded shut",
       fold is not None and f"Delete all {len(left)} designs" in fold.group(1))
    ck("  and shows the links the designs were read from BEFORE they go",
       fold is not None and "https://reallygoodemails.com/emails/0" in fold.group(1)
       and "<textarea readonly" in fold.group(1))

    busy = jobs.enqueue("eien", "email_recreate", payload={"mode": "run"})
    r = c.post("/admin/references_delete_all", params={"key": KEY}, data={"tenant": "baci"},
               follow_redirects=False)
    ck("while a design job is queued for ANY account, nothing is deleted, and it says why",
       r.status_code == 303 and "err=" in r.headers.get("location", "")
       and "eien" in unquote(r.headers.get("location", ""))
       and len(es.library()) == len(left))
    jobs.cancel(busy["id"])
    run_ = jobs.enqueue("baci", "system_run", system_key="campaign_email", payload={})
    ck("  nor while a campaign email is being made", "campaign email" in es.design_work_in_flight())
    jobs.cancel(run_["id"])

    r = c.post("/admin/references_delete_all", params={"key": KEY}, data={"tenant": "baci"},
               follow_redirects=False)
    said = unquote(r.headers.get("location", ""))
    ck("deleting all posts and says what went", r.status_code == 303
       and f"deleted {len(left)} design(s)" in said, said[:160])
    ck("  every design is gone from the library", es.library() == [])
    with db.SessionLocal() as s:
        ck("  with the reference pictures they were read from",
           all(s.get(db.KbAsset, a) is None for a in ref_ids if a))
        ck("  and the swipe that never became a design", s.get(db.KbAsset, swipe_id) is None)
        ck("  but NEVER a brand's own picture a design pointed at",
           s.get(db.KbAsset, own_id) is not None)
        ck("  and the emails already made are kept", s.get(db.Recreation, made_id) is not None)
    ck("  the standing choice and the taken-out list are cleared — they named designs that are gone",
       es.standing_designation("baci") == "" and not es.out_for("baci"))
    ck("  and the links come back in the answer, ready to paste",
       "https://reallygoodemails.com/emails/1" in said)
    ck("  a campaign now says the maker designs it, rather than failing on a design that is gone",
       es.pick("baci")["structure"] is None and "designs this one itself" in es.pick("baci")["why"])
    ck("  and the empty shelf offers no start-over",
       'class="startover"' not in ui._structures_card(KEY, "baci", view={}))

    print("\n— adding them again, several links in one press —")
    r = c.post("/admin/email_reference", params={"key": KEY}, follow_redirects=False, data={
        "tenant": "baci", "urls": "https://reallygoodemails.com/emails/a\n"
                                  "reallygoodemails.com/emails/b\n"
                                  "https://example.com/not-a-swipe\n"
                                  "https://reallygoodemails.com/emails/a"})
    said = unquote(r.headers.get("location", ""))
    with db.SessionLocal() as s:
        queued = sorted(str((j.payload or {}).get("url")) for j in s.query(db.JobQueue).filter(
            db.JobQueue.tenant == "baci", db.JobQueue.kind == "email_recreate",
            db.JobQueue.state == "queued").all())
    ck("each good link is its own job, once",
       queued == ["https://reallygoodemails.com/emails/a", "https://reallygoodemails.com/emails/b"],
       str(queued))
    ck("  and the one that is not a swipe is named, not dropped",
       "queued 2 reference(s)" in said and "example.com/not-a-swipe" in said, said[:200])
    r = c.post("/admin/email_reference", params={"key": KEY}, follow_redirects=False, data={
        "tenant": "baci", "urls": "https://reallygoodemails.com/emails/a\nhttps://reallygoodemails.com/emails/b"})
    ck("  pressing again queues nothing twice",
       "nothing new queued; 2 already queued" in unquote(r.headers.get("location", "")))

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}\n  " + "\n  ".join(_fail))
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
