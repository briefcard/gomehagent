"""The ad variant board: judge, edit, drop, regenerate, approve — honestly.

Before UI-overhaul 3.4, `ad_copy` produced 1–5 variants flagged
`needs_art_direction` into run-detail JSON and NO SURFACE SHOWED THEM — the
spec's words: "nothing can be judged, edited, or regenerated". This suite
pins the loop that ended that, end to end and offline:

  1. THE BATCH IS AN ARTIFACT — one ArtifactBody (format `ad_batch`),
     anchored on the first variant's ledger row, JSON of the reviewable set;
     `draft_body` freezes the machine's original batch as the virtual v1.
  2. EVERY VARIANT REACHES THE BOARD — a variant's own output id redirects
     to the board it belongs to (the ship queue links land somewhere real).
  3. OWNER EDITS ARE BAN-GATED AND VERSIONED — the list binds the owner's
     hands too, and every change to the board appends a version.
  4. REGENERATE KEEPS THE KEPT — dropped variants are replaced through the
     full gate stack with the owner's notes FIRST in the brief; kept
     variants survive verbatim (owner edits included); replaced rows close
     with a pointer and their approvals are withdrawn; the board keeps its
     page (no wholesale supersede).
  5. APPROVE IS HONEST — one gesture approves the kept variants and DENIES
     the dropped ones, and the surface says in every state that no
     ad-platform write is wired.

Run: python3 scripts/test_ad_board.py
"""
import json
import os
import re as _re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'adb.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, kb, skill, skill_pack, systems, tenants, web  # noqa: E402

KEY = "s3cret"
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


# Offline: capabilities are credential-backed; stub at the boundary the way
# test_skill.py does, so ad_creative's requires_any=("ads","commerce") holds.
_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else \
    {c: False for c in tenants.CAPABILITIES}


class FakeModel:
    """Stands in for `draft_ad` and REMEMBERS what it was briefed with —
    the regenerate assertions read the captured bundles, because "the notes
    rode the brief" is the claim, not "the function was called"."""

    def __init__(self):
        self.bundles = []
        self.n = 0

    def __call__(self, bundle, claim, angle, objections):
        self.bundles.append(bundle)
        self.n += 1
        return (f"Ad line {self.n}: {str(claim.get('claim') or '')[:40]}", "")


def contract(row, autonomy):
    first = systems.update(row.id, **{f: "declared for the test"
                                      for f, _l, _h in systems.CONTRACT})
    assert first.get("ok"), f"contract fill refused: {first}"
    second = systems.update(row.id, status="live", autonomy=autonomy)
    assert second.get("ok"), f"go-live refused: {second}"
    return systems.get(row.id)


def board(anchor):
    with db.SessionLocal() as s:
        art = (s.query(db.ArtifactBody)
               .filter(db.ArtifactBody.output_id == anchor).first())
        s.expunge_all()
    return art, (json.loads(art.body) if art else None)


def approvals_by_output(tenant):
    with db.SessionLocal() as s:
        rows = s.query(db.Approval).filter(db.Approval.tenant == tenant).all()
        got = {str((a.payload or {}).get("output_id") or ""): a.status
               for a in rows if (a.payload or {}).get("output_id")}
        s.expunge_all()
    return got


def main():
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.set_brand("baci", positioning="Italian-designed tableware.",
                 tone="direct, warm")
    kb.add_banned("baci", "hand-decorated")
    for c, ev in (("Dishwasher safe at 65 degrees.", "lab report"),
                  ("Made of shatter-resistant acrylic.", "spec sheet"),
                  ("Designed in Milan.", "brand file")):
        kb.add_claim("baci", c, ev, [], origin="human", status="active")
    kb.add_audience("baci", "hosts", "Hosts who entertain",
                    ["dull tables"], ["colour", "set"], origin="human")
    kb.add_entity("baci", "product", "aqua-plate", "Aqua Plate",
                  description="A generous 32 cm plate.", origin="human")
    row = systems.find("baci", "ad_creative") or systems.create(
        "baci", "ad_creative")
    contract(row, autonomy="approve_all")

    fake = FakeModel()
    skill_pack.draft_ad = fake

    print("\n--- 1 · the batch lands as an artifact ---")
    r = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                  audience_key="hosts", variants=3)
    ck("three variants produced", r["status"] == "produced"
       and len(r["items"]) == 3, f"{r['status']}, {len(r['items'])} items")
    anchor = r["items"][0]["output_id"]
    art, batch = board(anchor)
    ck("one ArtifactBody, format ad_batch, anchored on variant 1",
       art is not None and art.format == "ad_batch", str(art))
    # 2026-08-29: retargeted. The angles were three hardcoded strings and
    # "proof" was not an angle at all — proof is a VALUE LEVER that belongs in
    # every ad, not the theme of one. They come from `ad_craft.angles_for`
    # now, chosen per account from its own knowledge base, so this asserts
    # against the ruleset rather than restating a list that can drift from it.
    from app import ad_craft
    # Read the angle set the RUN said it was using, rather than guessing the
    # evidence string that produced it — the angles are chosen per account
    # from its own knowledge base, so a fixture that reconstructs the input is
    # testing my reconstruction rather than the code.
    said = next((n for n in r["notes"] if n.startswith("angles in play")), "")
    in_play = [a.strip(" .") for a in
               said.split(":", 1)[-1].split("(")[0].split(",") if a.strip()]
    got = [v["angle"] for v in (batch or {}).get("variants", [])]
    ck("  the JSON names all three variants with their angles",
       batch is not None and len(batch["variants"]) == 3
       and got == in_play[:3], f"{got} vs {in_play[:3]}")
    ck("  every angle it used is one the ruleset defines",
       bool(got) and all(v in ad_craft.ANGLES for v in got), str(got))
    ck("  and they are three DIFFERENT angles — five texts on one angle is "
       "the collapse the matrix exists to prevent",
       len(set(got)) == 3, str(got))
    ck("  gifting is withheld from an account with no evidence of it",
       "gifting" not in in_play or "gift" in str(r["notes"]).lower(),
       said[:120])
    ck("  every variant is flagged needs_art_direction",
       all(v["needs_art_direction"] for v in batch["variants"]))
    ck("  draft_body froze the machine's batch (virtual v1)",
       art.draft_body == art.body)
    ck("  the run says the board exists",
       any("variant board" in n for n in r["notes"]), str(r["notes"]))
    apr = approvals_by_output("baci")
    ck("three approvals pending (approve_all rung)",
       [apr.get(v["output_id"]) for v in batch["variants"]]
       == ["pending"] * 3, str(apr))

    c = TestClient(web.app, base_url="https://testserver")
    v2, v3 = batch["variants"][1], batch["variants"][2]

    print("\n--- 2 · every variant reaches the board ---")
    r2 = c.get(f"/admin/work/{v2['output_id']}?key={KEY}",
               follow_redirects=False)
    ck("a variant's own id 303s to the board", r2.status_code == 303
       and f"/admin/work/{anchor}" in r2.headers.get("location", ""),
       f"{r2.status_code} -> {r2.headers.get('location', '')}")
    page = c.get(f"/admin/work/{anchor}?key={KEY}").text
    ck("the board renders, framed", 'class="side"' in page
       and "The variant board" in page)
    ck("  variant cards with the amber chip",
       "Variant 1" in page and "needs art direction" in page)
    ck("  honest in every state: no ad-platform write is wired",
       "no ad-platform write is wired" in page.lower())
    ck("  Regenerate is offered with batch semantics",
       "Regenerate with feedback" in page and "WHOLE batch" in page)
    ck("  the grounding is on the card", "built on:" in page)

    # ONE CLAIM READING PER VARIANT (owner, 2026-09-04). The card used to
    # CONCATENATE every variant's text and annotate that — five ads read as
    # one document, so "is THIS ad grounded" had no answer and a note against
    # variant four sat in variant one's gutter.
    ck("the claim review is tabbed, one pane per variant",
       'class="vtabs"' in page
       and all(f'id="gv-{i}"' in page and f'id="gp-{i}"' in page
               for i in (1, 2, 3)), "")
    ck("  the first variant is open with no script — radios are the state",
       'id="gv-1" checked' in page or 'id="gv-1"checked' in page
       or 'id="gv-1" checked>' in page, "")
    ck("  each tab is labelled with its variant",
       all(f">Variant {i} " in page for i in (1, 2, 3)), "")
    ck("  and there is one gutter per pane, not one for the batch",
       page.count('class="gwrap"') == 3, str(page.count('class="gwrap"')))
    # THE NUMBERS MUST NOT COLLIDE. `_MARGIN_JS` joins marker to sentence to
    # panel entry on `data-note` across the WHOLE document, so three panes
    # each numbering from 1 would make one click select three things.
    notes = _re.findall(r'class="mk" data-note="(\d+)"', page)
    ck("  note numbers are unique across the panes, not restarted per tab",
       len(notes) == len(set(notes)) and len(notes) >= 2, str(notes))
    ck("  and the script re-lays out when a pane is revealed",
       ".vtabs>input" in page and "addEventListener('change',layout)" in page,
       "a hidden pane has no rectangles, so its markers would stack at the top")

    ship = c.get(f"/admin/ui?key={KEY}&tab=content&sub=ship&tenant=baci").text
    ck("the ship queue links each variant to its board",
       "review on its board" in ship)

    print("\n--- 3 · owner edits: ban-gated, versioned, draft survives ---")
    r3 = c.post("/admin/ad_variant_save",
                data={"key": KEY, "output_id": anchor, "n": "2",
                      "text": "Every piece is hand-decorated with love."},
                follow_redirects=False)
    ck("a banned phrase refuses, whoever typed it",
       "refused" in r3.headers.get("location", "")
       and "ban" in r3.headers.get("location", "").lower(),
       r3.headers.get("location", ""))
    _, b3 = board(anchor)
    ck("  and nothing changed on the board",
       b3["variants"][1]["text"] == v2["text"])
    r3 = c.post("/admin/ad_variant_save",
                data={"key": KEY, "output_id": anchor, "n": "2",
                      "text": "Acrylic that survives the party."},
                follow_redirects=False)
    ck("a clean edit saves", "saved" in r3.headers.get("location", ""))
    art, b3 = board(anchor)
    ck("  the board carries the edit",
       b3["variants"][1]["text"] == "Acrylic that survives the party.")
    ck("  the draft survived the edit (v1 frozen)",
       json.loads(art.draft_body)["variants"][1]["text"] == v2["text"])
    with db.SessionLocal() as s:
        vs = (s.query(db.ArtifactVersion)
              .filter(db.ArtifactVersion.output_id == anchor)
              .order_by(db.ArtifactVersion.n).all())
        s.expunge_all()
    ck("  the edit appended a version", len(vs) == 1
       and "variant 2" in vs[0].note, str([v.note for v in vs]))

    print("\n--- 4 · feedback + drop + regenerate keeps the kept ---")
    c.post("/admin/feedback_add",
           data={"key": KEY, "output_id": anchor, "system_key": "ad_creative",
                 "part": "variant 3", "level": "draft", "category": "tone",
                 "note": "too flat — give it a pulse"},
           follow_redirects=False)
    with db.SessionLocal() as s:
        fbs = (s.query(db.FeedbackItem)
               .filter(db.FeedbackItem.output_id == anchor).all())
        s.expunge_all()
    ck("per-variant feedback files at the variant", len(fbs) == 1
       and fbs[0].part == "variant 3" and fbs[0].status == "open")
    r4 = c.post("/admin/ad_variant_drop",
                data={"key": KEY, "output_id": anchor, "n": "3"},
                follow_redirects=False)
    ck("variant 3 drops", "dropped" in r4.headers.get("location", ""))
    _, b4 = board(anchor)
    ck("  the board shows it dropped, not deleted",
       b4["variants"][2]["dropped"] is True and len(b4["variants"]) == 3)

    n_bundles = len(fake.bundles)
    r4 = c.post("/admin/work_redraft",
                data={"key": KEY, "output_id": anchor,
                      "note": "punchier, and no exclamation marks"},
                follow_redirects=False)
    loc = r4.headers.get("location", "")
    ck("regenerate lands back on the SAME board (in place, no supersede)",
       f"/admin/work/{anchor}" in loc and "regenerated" in loc, loc)
    briefed = " ".join(str(b.get("revision_notes") or "")
                       for b in fake.bundles[n_bundles:])
    ck("  the owner's note rode the brief", "punchier" in briefed,
       briefed[:200])
    ck("  the filed feedback rode it too", "give it a pulse" in briefed)
    ck("  the kept variants rode as do-not-repeat context",
       "KEPT" in briefed and "Acrylic that survives the party." in briefed)
    art, b5 = board(anchor)
    ck("  kept variants survive verbatim (owner edit included)",
       b5["variants"][0]["text"] == batch["variants"][0]["text"]
       and b5["variants"][1]["text"] == "Acrylic that survives the party.")
    new_v3 = b5["variants"][2]
    ck("  the dropped one was replaced by a fresh output",
       new_v3["output_id"] != v3["output_id"]
       and not new_v3.get("dropped"), str(new_v3.get("output_id")))
    ck("  still ONE board — the refill wrote no second artifact",
       db.SessionLocal().query(db.ArtifactBody)
       .filter(db.ArtifactBody.format == "ad_batch").count() == 1)
    with db.SessionLocal() as s:
        old3 = s.get(db.Output, v3["output_id"])
        s.expunge_all()
    ck("  the replaced row closed with a pointer",
       old3.status == "superseded"
       and old3.destination == f"replaced-in-batch:{new_v3['output_id']}",
       f"{old3.status} / {old3.destination}")
    apr = approvals_by_output("baci")
    ck("  its approval was withdrawn; the replacement's is pending",
       apr.get(v3["output_id"]) == "withdrawn"
       and apr.get(new_v3["output_id"]) == "pending", str(apr))
    with db.SessionLocal() as s:
        fbs = (s.query(db.FeedbackItem)
               .filter(db.FeedbackItem.output_id == anchor).all())
        vs = (s.query(db.ArtifactVersion)
              .filter(db.ArtifactVersion.output_id == anchor)
              .order_by(db.ArtifactVersion.n).all())
        s.expunge_all()
    ck("  the feedback is consumed", fbs[0].status == "applied")
    ck("  the regenerate appended a machine version",
       vs[-1].author == "machine" and "regenerated" in vs[-1].note,
       str([(v.author, v.note) for v in vs]))

    print("\n--- 5 · approve is one honest gesture ---")
    c.post("/admin/ad_variant_drop",
           data={"key": KEY, "output_id": anchor, "n": "1"},
           follow_redirects=False)
    r5 = c.post("/admin/ad_batch_decide",
                data={"key": KEY, "output_id": anchor, "verdict": "approve"},
                follow_redirects=False)
    loc = r5.headers.get("location", "")
    ck("approve marks the batch ready and says what it is NOT",
       "batch+marked+ready" in loc.replace("%20", "+")
       and "No+ad-platform+write" in loc.replace("%20", "+"), loc)
    apr = approvals_by_output("baci")
    _, b6 = board(anchor)
    ck("  kept variants approved (executed), dropped one DENIED",
       apr.get(b6["variants"][1]["output_id"]) == "executed"
       and apr.get(new_v3["output_id"]) == "executed"
       and apr.get(b6["variants"][0]["output_id"]) == "denied", str(apr))
    page = c.get(f"/admin/work/{anchor}?key={KEY}").text
    ck("  the board reads ready, still honest",
       "Batch ready" in page and "by hand" in page)
    # READY IS AN ENDING, not a state with nothing after it. `ad_creative`'s
    # whole declared ship is this moment, and until 2026-08-31 the bar
    # reported it and offered nothing to do about it — a fact with no control,
    # which is design rule 1 broken on the system the rule matters most to.
    ck("  and ready offers the two things that end it",
       "/admin/ad_export" in page and "/admin/ad_launched" in page,
       "carry the copy out, then tell it to look — `meta_ads.match` closes "
       "the loop by comparing the copy it wrote")

    print("\n--- 5b · the copy comes out paste-ready, dropped ones excluded ---")
    txt = c.get(f"/admin/ad_export?key={KEY}&output_id={anchor}").text
    ck("the export names its variants", "variant 1" in txt, txt[:70])
    # THE COPY, NOT THE HEADER. This suite asserted "variant 1" appears and
    # counted "--- variant " markers, and passed for months while the export
    # emitted headers and NOTHING ELSE: it read headline/primary_text/
    # description/cta and a variant row carried none of them. `primary_text`
    # matched exactly one line in the whole codebase — this reader. Asserting
    # on the label instead of the thing is how a declared ship shipped empty.
    _kept = [v for v in b6["variants"] if not v.get("dropped")]
    ck("  AND THE ACTUAL COPY, which is the whole point of an export",
       all(str(v.get("text") or "")[:40] in txt for v in _kept),
       txt[:200])
    ck("  with the headline the drafter wrote",
       all(str(v.get("headline") or "") in txt for v in _kept if v.get("headline")),
       str([v.get("headline") for v in _kept]))
    ck("  and a variant that carries no copy is NAMED, never a silent blank",
       "no copy at all" not in txt and "(this variant carries no copy" not in txt,
       "these variants have copy; the warning path is for when they do not")
    # THE EMPTY PATH, exercised. Without this the warning is unreachable code
    # and its guard reports MISSED — which is how the original defect lived:
    # nothing ever asked what an export with no copy in it looks like.
    with db.SessionLocal() as _s:
        _row = (_s.query(db.ArtifactBody)
                .filter(db.ArtifactBody.output_id == anchor).first())
        _doc = json.loads(_row.body)
        for _v in _doc["variants"]:
            _v["text"] = ""
        _row.body = json.dumps(_doc)
        _s.commit()
    blank = c.get(f"/admin/ad_export?key={KEY}&output_id={anchor}").text
    ck("an export with no copy REFUSES to look normal",
       "carries no copy" in blank and "WARNING" in blank
       and "exported no copy at all" in blank, blank[:180])
    with db.SessionLocal() as _s:
        _row = (_s.query(db.ArtifactBody)
                .filter(db.ArtifactBody.output_id == anchor).first())
        _row.body = json.dumps(b6)
        _s.commit()
    _live_n = len([v for v in b6["variants"] if not v.get("dropped")])
    ck("  and carries the KEPT variants only",
       txt.count("--- variant ") == _live_n and _live_n < len(b6["variants"]),
       f'{txt.count("--- variant ")} exported, {_live_n} kept of '
       f'{len(b6["variants"])} — approving DENIES a dropped variant, so '
       f'exporting it hands over the exact thing the decision refused')
    ck("  and says why the copy must not be edited",
       "comparing the text" in txt,
       "meta_ads.match joins by the copy; an edit breaks the join silently")
    # A FRESH client, because `c` is signed in: `admin_key` accepts the
    # console session cookie as well as the query key, so `?key=no` on an
    # already-authenticated browser is still authenticated — correctly. The
    # property is that a stranger gets nothing.
    _out = TestClient(web.app, base_url="https://testserver")
    ck("  and a signed-out stranger gets no copy",
       "variant 1" not in _out.get(
           f"/admin/ad_export?key=no&output_id={anchor}").text)

    print("\n--- 5c · telling it the ads are live closes the loop ---")
    # THE JOIN EXISTED AND NOTHING CALLED IT. `meta_ads.match` has been able to
    # write `destination` (the ad id) and `outcome` onto the drafted rows since
    # it was written, reachable from nowhere — so the ads measurement loop was
    # open at BOTH ends: the copy could not get out, and what came back could
    # not be recognised.
    from app import meta_ads as _ma
    _calls = {}

    def _fake_match(tenant, *, limit=200):
        _calls["tenant"] = tenant
        return {"ok": True, "matched": 2, "live": 3, "unmatched_live": 1,
                "note": "1 ad(s) are running copy this system did not write",
                "why": ""}
    _real_match = _ma.match
    _ma.match = _fake_match
    try:
        r5c = c.post(f"/admin/ad_launched?key={KEY}",
                     data={"output_id": anchor, "tenant": "baci"},
                     follow_redirects=False)
    finally:
        _ma.match = _real_match
    ck("the button reaches the join", _calls.get("tenant") == "baci",
       str(_calls))
    _loc = r5c.headers.get("location", "")
    ck("  and lands back on the board with what it found",
       f"/admin/work/{anchor}" in _loc and "joined+2" in _loc.replace("%20", "+"),
       _loc[:120])
    ck("  including the ads it did NOT write",
       "did+not+write" in _loc.replace("%20", "+"),
       "an ad running copy nobody here wrote is worth knowing beside a system "
       "that claims to be drafting them")

    def _fake_dead(tenant, *, limit=200):
        return {"ok": False, "why": "no ad account connected", "matched": 0}
    _ma.match = _fake_dead
    try:
        r5d = c.post(f"/admin/ad_launched?key={KEY}",
                     data={"output_id": anchor, "tenant": "baci"},
                     follow_redirects=False)
    finally:
        _ma.match = _real_match
    ck("  a refusal is reported as one, not as zero matches",
       "err=" in r5d.headers.get("location", ""),
       r5d.headers.get("location", "")[:110])

    print("\n--- 6 · refusals hold ---")
    r6 = c.post("/admin/work_redraft",
                data={"key": KEY, "output_id": anchor, "note": ""},
                follow_redirects=False)
    ck("a regenerate with no direction is refused as a reroll",
       "reroll" in r6.headers.get("location", ""),
       r6.headers.get("location", ""))

    print("\n--- 7 · the default rung gets a board AND a decision ---")
    contract(systems.find("baci", "ad_creative"), autonomy="shadow")
    r7 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=1)
    a2 = r7["items"][0]["output_id"]
    page = c.get(f"/admin/work/{a2}?key={KEY}").text
    # Shadow used to file `recorded`, which queued nothing — so the board on
    # the DEFAULT rung explained that no approval had been asked instead of
    # offering one. Owner, 2026-08-31: a drafted thing offers Approve or
    # Redraft, and this system is not exempt.
    ck("the shadow-rung board offers a decision, not an explanation",
       "No approval was asked" not in page,
       "shadow is the default; a draft nobody can decide is the commonest "
       "state this platform had")
    ck("  and it is still honest about what approving does",
       "no ad-platform write is wired" in page.lower(),
       "approving marks the batch ready — that is its whole declared ship")

    print()
    if _fail:
        print(f"FAILED: {len(_fail)} — " + "; ".join(_fail[:8]))
        sys.exit(1)
    print("all green: the board judges, teaches, regenerates and stays honest")


if __name__ == "__main__":
    main()
