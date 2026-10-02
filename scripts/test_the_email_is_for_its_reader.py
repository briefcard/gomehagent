"""The email is written to one reader, about what they have, and the products
it offers turn over.

Owner, 2026-10-02, of a Baci email that finally looked right: *"It makes sense
grammatically, but it doesn't land anything that the reader would connect with.
One of the reasons we share the audiences, their pain points, etc is so that
you could always gear the content regardless of topic / context / goal towards
the correct audience."* The email said "White, decided once and for good" and
told a reader who eats off white plates every day that white "is never the easy
choice". And: *"can you please check to make sure that we are cycling through
the entities correctly? This is yet another example of us choosing the 18-piece
joke when the entity was not set."*

WHAT WAS WRONG, each asserted against what fixes it:

  1. THE PRODUCTS. With no entity on the plan, the email took the first item of
     a fixed order: the audience's list as entered, or the catalogue by
     photograph then NAME, where "18-Piece …" sorts before every letter.
     Nothing read what had already been sent, so the same set led every time.
  2. THE READER. The persona reached the drafter, which no longer writes the
     words that ship. The story, the maker and the judge were never told who
     reads, and a plan naming only a segment chose nobody at all.
  3. Nothing read the words as the reader would, so a premise nobody holds
     and a motto in place of the argument passed every check.

Run: python3 scripts/test_the_email_is_for_its_reader.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rd.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ.pop("SHOTS_WS", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # the suite's stand-in maker
from _maker_stub import install as _install_maker  # noqa: E402

from app import (articles as ar, brand_theme, config, db, esp, funnel, kb, llm,  # noqa: E402
                 reader as rd, recreate as rc, skill, skill_pack, systems, tenants)

T = "baci"
_fail: list = []

THE_OWNERS_EMAIL = ("White, decided once and for good. White at the table is never the easy choice — until "
                    "it is the only one that makes sense. The Joke set arrives in a clean, minimal line that "
                    "sits alongside anything. Not a trend. A decision. Trends set the table for a season. "
                    "The Joke set stays.")
HOSTESS_PAINS = ["generic tableware that says nothing about her",
                 "wants a gift that feels chosen, not bought",
                 "hosting for people whose opinion she cares about"]


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class _R:
    ok, error, degraded, stop_reason, model = True, "", "", "end_turn", "stub"

    def __init__(self, text):
        self.text = text if isinstance(text, str) else json.dumps(text)


_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else {c: False for c in tenants.CAPABILITIES}


def _fake_esp():
    esp.provider_for = lambda t: "omnisend"
    esp.personalize = lambda t, html: {"ok": True, "html": html}

    class _Mod:
        @staticmethod
        def draft_from_html(tenant, *, name, subject, sender_name, html, preheader="", include_segments=None):
            return {"ok": True, "campaign_id": "c1", "stage": "done"}
    esp.backend = lambda t: (_Mod, "")


def _drafter(picks=()):
    """A drafter that names `picks` as its products — or nothing, the case in
    which the email is still made about the hero it was handed."""
    def _d(bundle, seg, goal, craft=None):
        blocks = [{"type": "heading", "text": "A table for the people you cook for", "level": 1},
                  {"type": "text", "html": "<p>Eighteen pieces, one box.</p>"}]
        if picks:
            blocks.append({"type": "products", "keys": list(picks)})
        return ({"subject": "A table for the people you cook for", "preheader": "Inside",
                 "blocks": blocks, "claim_ids": [], "cta_label": "Shop", "cta_url": "https://x/s"}, "model", "")
    return _d


def _note(res, prefix):
    return next((str(n) for n in res.get("notes") or [] if str(n).startswith(prefix)), "")


def _meta(res):
    return ((res.get("items") or [{}])[0].get("meta") or {})


def main() -> int:
    _install_maker()
    db.init_db()
    tenants.seed()
    kb.ensure_brand(T, "Baci Milano")
    kb.set_brand(T, positioning="Italian-designed tableware.", tone="warm")
    kb.add_banned(T, "made in Italy")
    kb.add_claim(T, "Designed in Milan by the Italian design house Baci Milano.", "brand file", [],
                 origin="human", status="active")
    row = systems.find(T, "campaign_email") or systems.create(T, "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    brand_theme.approve(T, {"footer.address": "2875 NE 191st St, Aventura FL"})
    _fake_esp()
    # Three lines, five items. "18-Piece …" starts with a digit, so by name it
    # sorts first — the order that led every email the owner saw — and its two
    # colours sort side by side: offered one after the other, the same set
    # twice is exactly the repetition reported.
    for k, n in (("18-piece-joke-black", "18-Piece Joke Melamine in Black"),
                 ("18-piece-joke-white", "18-Piece Joke Melamine in White"),
                 ("aqua-pitcher", "Aqua Pitcher"),
                 ("aqua-tumbler", "Aqua Tumbler"),
                 ("baroque-plate", "Baroque & Rock Plate")):
        kb.add_entity(T, "product", k, n, description=f"{n}.", price="40",
                      attributes={"image": f"https://cdn.example.com/{k}.jpg"})

    print("— 1. a product's line is what its name says first —")
    ck("the set's two colours are one line",
       skill_pack._line("18-Piece Joke Melamine in White") == skill_pack._line("18-Piece Joke Melamine in Black")
       == "joke")
    ck("  and the others are their own",
       skill_pack._line("Aqua Tumbler") == "aqua" and skill_pack._line("Baroque & Rock Plate") == "baroque")

    print("\n— 2. the rotation: never featured, then featured longest ago, never the last one again —")
    rows = sorted(kb.entities(T), key=lambda r: r.name)
    names = {r.key: r.name for r in rows}
    order = lambda lately: [r.key for r in skill_pack._rotation(rows, lately, names)]  # noqa: E731
    ck("with nothing sent, the given order stands — the rotation only reorders by what was sent",
       order([])[0] == "18-piece-joke-black", str(order([])))
    after_joke = order(["18-piece-joke-black"])
    ck("after the set leads, another LINE leads — not the set's other colour, next by name",
       after_joke[0] == "aqua-pitcher" and after_joke.index("18-piece-joke-white") == 3, str(after_joke))
    ck("  and the one featured last comes last", after_joke[-1] == "18-piece-joke-black", str(after_joke))
    every = order(["baroque-plate", "aqua-pitcher", "18-piece-joke-black"])
    ck("when every line has had a turn, the one featured longest ago comes back — with its item not yet shown",
       every[0] == "18-piece-joke-white", str(every))
    ck("ties keep the order given, so a recommendation still decides between equals",
       [r.key for r in skill_pack._rotation(list(reversed(rows)), [], names)][0] == "baroque-plate")

    print("\n— 3. through the run: the hero turns over, email after email —")
    kb.add_audience(T, "core_hostess", "Women 35–44 — the core buyer", HOSTESS_PAINS,
                    ["set", "gift", "hosting", "table"],
                    buying_trigger="A birthday, a housewarming, or her own table feeling tired")
    skill_pack.draft_campaign = _drafter()          # names no product: the hero still turns over
    heroes = []
    for _ in range(4):
        r = skill.run("campaign_email", T, audience_key="core_hostess")
        heroes.append(_note(r, "hero: ").split(" — ")[0].replace("hero: ", ""))
    ck("the first three emails lead with three different lines — the 18-piece set once",
       [skill_pack._line(h) for h in heroes[:3]] == ["joke", "aqua", "baroque"], str(heroes))
    ck("  the fourth is the line featured longest ago, with the colour it has not shown",
       heroes[3] == "18-Piece Joke Melamine in White", str(heroes))
    ck("each email records the hero it was made about, though the drafter named none",
       _meta(r).get("hero") == "18-piece-joke-white", str(_meta(r).get("hero")))
    lately = skill_pack._sent_lately(T)
    ck("  and the rotation reads it back, newest first",
       [h["hero"] for h in lately[:2]] == ["18-piece-joke-white", "baroque-plate"], str(lately[:2]))
    ck("the run says the products were chosen in rotation, not as the catalogue's top",
       "rotation" in _note(r, "products: ") and "top available" not in _note(r, "products: "),
       _note(r, "products: "))
    oid = ((r.get("items") or [{}])[0]).get("output_id", "")
    again = skill_pack.redraft_artifact(T, oid, part="body", note="Shorter, please.")
    with db.SessionLocal() as s_:
        a_ = (s_.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == again.get("output_id", "")).first())
        hero_again = ((a_.meta or {}).get("hero") if a_ else "") or ""
    ck("a Revise makes the same email again — about the same product, not the next in the rotation",
       again.get("ok") and hero_again == "18-piece-joke-white", f"{str(again)[:120]} hero={hero_again!r}")

    print("\n— 4. a recommendation turns over too —")
    kb.set_audience_entities(T, "core_hostess", ["baroque-plate", "aqua-tumbler"])
    r_a = skill.run("campaign_email", T, audience_key="core_hostess")
    r_b = skill.run("campaign_email", T, audience_key="core_hostess")
    h_a, h_b = (_note(x, "hero: ").split(" — ")[0] for x in (r_a, r_b))
    ck("the reader's recommendation is what is offered", "recommended for" in _note(r_a, "products: "),
       _note(r_a, "products: "))
    ck("  the line featured longest ago leads, though the recommendation names the other first",
       h_a == "hero: Aqua Tumbler", h_a)
    ck("  and the one just featured does not lead the next email", h_b == "hero: Baroque & Rock Plate", h_b)
    kb.set_audience_entities(T, "core_hostess", [])

    print("\n— 5. a named hero's companions are its own line, not the catalogue's first by name —")
    seen_ents: dict = {}
    real_d = skill_pack.draft_campaign

    def _cap(bundle, seg, goal, craft=None):
        seen_ents["keys"] = [e.get("key") for e in bundle.get("entities") or []]
        return real_d(bundle, seg, goal, craft)
    skill_pack.draft_campaign = _cap
    skill.run("campaign_email", T, audience_key="core_hostess", entity_key="aqua-tumbler")
    skill_pack.draft_campaign = real_d
    keys = seen_ents.get("keys") or []
    ck("the named hero leads", keys[:1] == ["aqua-tumbler"], str(keys))
    ck("  its own line comes next — not the 18-piece set, first by name", keys[1:2] == ["aqua-pitcher"], str(keys))
    ck("  and the rest are still offered — an email may show several", len(keys) == 5, str(keys))

    print("\n— 6. the reader: named on the plan it stands; otherwise one is chosen and said —")
    kb.add_audience(T, "established_host", "Women 45–54 — owns plenty",
                    ["already owns plenty; needs a reason for another set"], ["quality", "everyday"],
                    buying_trigger="Replacing a broken piece, or a milestone gift")
    kb.add_audience(T, "price_led", "Women 25–34 — first homes", ["wants the look at a reachable price"],
                    ["bundle", "starter"], buying_trigger="A sale, or a first apartment")
    r_p = skill.run("campaign_email", T, audience_key="established_host")
    ck("the plan's reader stands and nothing is chosen over it",
       _meta(r_p).get("audience_key") == "established_host" and _meta(r_p).get("reader_chosen_by") == "plan"
       and not _note(r_p, "written for: "), str(_meta(r_p).get("reader_chosen_by")))
    picked = []
    for _ in range(3):
        r_s = skill.run("campaign_email", T, segment="new_subscribers")
        picked.append(_meta(r_s).get("audience_key"))
    ck("a plan naming only a list is still written to one reader, and the run says which",
       "no reader was named on the plan" in _note(r_s, "written for: ") and _note(r_s, "written for: "),
       _note(r_s, "written for: "))
    ck("  the one written for least recently, so the readers take turns",
       len(set(picked)) == 3 and picked[0] == "price_led", str(picked))
    ck("  recorded on the email, so a redraft keeps its reader",
       _meta(r_s).get("reader_chosen_by") == "rotation" and _meta(r_s).get("audience_key") == picked[-1])
    kb.set_audience_entities(T, "price_led", ["aqua-tumbler"])
    r_e = skill.run("campaign_email", T, segment="new_subscribers", entity_key="aqua-tumbler")
    ck("a plan's product chooses the reader it is recommended for",
       _meta(r_e).get("audience_key") == "price_led" and "recommended for" in _note(r_e, "written for: "),
       _note(r_e, "written for: "))

    print("\n— 7. the reader reaches the minds that write and judge the words —")
    msgs: list = []
    real_run = rc.run
    rc.run = lambda *a, message=None, **k: (msgs.append(dict(message or {})) or real_run(*a, message=message, **k))
    skill.run("campaign_email", T, audience_key="core_hostess")
    rc.run = real_run
    reader_ = (msgs[-1] if msgs else {}).get("reader") or {}
    ck("the maker's message carries the reader: who, and what they have",
       reader_.get("who") == "Women 35–44 — the core buyer" and HOSTESS_PAINS[2] in reader_.get("pains", []),
       str(reader_)[:200])
    ck("  what makes them act, and their own words",
       reader_.get("acts_when") and "hosting" in reader_.get("words", []))
    plan_ = funnel.inputs_for(T, "interest", audience={"key": "core_hostess", "name": "Women 35–44 — the core buyer",
                                                       "pains": HOSTESS_PAINS, "vocabulary": ["hosting"]})
    ck("the drafter's brief says who it is written to, by name",
       "WHO THIS IS WRITTEN TO: Women 35–44 — the core buyer" in funnel.brief(plan_))

    asked: list = []
    real_ask = rc._ask
    story_bad = {"for": "white is a decision", "hook": "White, decided once and for good",
                 "beats": [{"beat": "tension", "says": "White at the table is never the easy choice.",
                            "rests_on": "the reference's contrast", "about": "the reader"}], "close": "Shop"}
    story_good = {"for": HOSTESS_PAINS[2], "hook": "A table for the people whose opinion you care about",
                  "beats": [{"beat": "problem", "says": "Hosting the people whose opinion you care about.",
                             "rests_on": HOSTESS_PAINS[2], "about": "the reader"}], "close": "Shop the set"}
    answers = iter([story_bad, story_good])
    rc._ask = lambda purpose, prompt, **k: (asked.append(prompt) or _R(next(answers)))
    kit_ = {"tenant": T, "name": "Baci Milano", "entities": [], "claims": []}
    told = rc.decide_story({"argument": [{"beat": "hook", "says": "Not a trend. A decision."}]}, kit_,
                           {"subject": "x", "reader": reader_}, tenant=T)
    rc._ask = real_ask
    ck("the story is told the reader before the reference's shape",
       bool(asked) and "THE READER — who this email is written to" in asked[0] and HOSTESS_PAINS[2] in asked[0]
       and asked[0].index("THE READER") < asked[0].index("THE REFERENCE'S ARGUMENT"))
    ck("  and that the reader decides what it is about — the owner's own line is the example",
       "THE READER DECIDES WHAT THE EMAIL IS ABOUT" in asked[0] and "never the easy choice" in asked[0])
    ck("a story that answers nothing of the reader's is asked for again, told what missed",
       len(asked) == 2 and "YOUR LAST STORY MISSED THE READER" in asked[1] and '"for"' in asked[1],
       str(len(asked)))
    ck("  and the one that answers a thing they have is kept",
       told.get("story", {}).get("for") == HOSTESS_PAINS[2] and told.get("reader_problems") == [])
    probs = rd.story_problems(story_bad, reader_)
    ck("an invented difficulty told to the reader is named, beat by beat",
       any("never the easy choice" in p for p in probs) and any('"for"' in p for p in probs), str(probs))
    settled = {"for": HOSTESS_PAINS[2], "hook": "h", "beats": [
        {"beat": "contrast", "says": "You settled for white because it was safe.",
         "rests_on": "the reference's contrast", "about": "the reader"}]}
    ck("  a contrast that tells the reader what they settled for is held to them too",
       any("settled for white" in p for p in rd.story_problems(settled, reader_)),
       str(rd.story_problems(settled, reader_)))
    ck("a story with nothing on file to hold it to is not refused for that",
       rd.story_problems(story_bad, rd.from_plan({}, {})) == [])
    no_ref = rc.decide_story({}, kit_, {"subject": "x"}, tenant=T)
    ck("a design for the shelf, with no message and no reference, still decides no story",
       no_ref.get("calls") == 0 and not no_ref.get("story"))
    rc._ask = lambda purpose, prompt, **k: (asked.append(prompt) or _R(story_good))
    with_reader = rc.decide_story({}, kit_, {"subject": "x", "reader": reader_}, tenant=T)
    rc._ask = real_ask
    ck("  but a campaign with a reader decides one even with no reference to take a shape from",
       with_reader.get("ok") and with_reader.get("calls") == 1 and "no reference this time" in asked[-1])
    sec = rc._reader_section({"reader": reader_})
    ck("the maker is told the reader, and a shelf design is not",
       "THE READER — who this email is written to" in sec and HOSTESS_PAINS[0] in sec
       and rc._reader_section({"subject": "x"}) == "" and rc._reader_section(None) == "")
    ck("  in the prompt it writes from", "%(reader)s%(story)s" in rc._COMPOSE_PROMPT)
    ck("the judge writes its copy edits to them", "%(reader)s" in rc._JUDGE_PROMPT)

    print("\n— 8. the reader pass: the owner's email, read as its reader —")
    said: list = []
    real_llm = llm.ask
    llm.ask = lambda purpose, prompt, **k: (said.append((purpose, prompt)) or _R({
        "speaks_to": "",
        "premises": [{"words": "White at the table is never the easy choice",
                      "why": "I serve on white plates every day; nothing about it is hard"}],
        "empty": [{"words": "White, decided once and for good.", "why": "a motto; it tells me nothing"}]}))
    heard = rd.check(THE_OWNERS_EMAIL, reader_, brand="Baci Milano", tenant=T)
    llm.ask = real_llm
    codes = {f["code"]: f for f in heard["findings"]}
    ck("one short text call, on its own purpose", [p for p, _ in said] == ["email_reader"]
       and llm.PURPOSE_MODEL.get("email_reader") == "CLAUDE_MODEL")
    ck("  holding the reader and the email's words", HOSTESS_PAINS[2] in said[0][1] and "never the easy choice" in said[0][1])
    ck("a premise the reader would not nod at blocks",
       codes.get("false_premise", {}).get("severity") == "blocks", str(list(codes)))
    ck("  a motto in the place of the argument blocks", codes.get("says_nothing", {}).get("severity") == "blocks")
    ck("  an email that speaks to nothing the reader has blocks",
       codes.get("no_reader", {}).get("severity") == "blocks")
    ck("  and each says what to write instead, from what the reader has",
       HOSTESS_PAINS[0] in codes["false_premise"].get("do", ""), codes["false_premise"].get("do"))
    llm.ask = lambda purpose, prompt, **k: _R({"speaks_to": HOSTESS_PAINS[2], "premises": [], "empty": []})
    ok_ = rd.check("Eighteen pieces for the dinner you host for the people whose opinion you care about.",
                   reader_, brand="Baci Milano", tenant=T)
    llm.ask = lambda purpose, prompt, **k: _R("no json here")
    dumb = rd.check(THE_OWNERS_EMAIL, reader_, tenant=T)
    llm.ask = real_llm
    ck("copy that speaks to a thing the reader has passes", ok_["findings"] == [], str(ok_["findings"]))
    ck("a pass that does not answer is said, and does not block — unread is unproven, not unsafe",
       [(f["code"], f["severity"]) for f in dumb["findings"]] == [("reader_unread", "cosmetic")] and dumb["calls"] == 2)
    ck("with nobody on file the reader is told plainly that nothing may be said about them",
       "nobody is on file" in rd.text(rd.from_plan({}, {})) and "Write no line about the reader's difficulties"
       in rd.text(rd.from_plan({}, {})))

    print("\n— 9. the article: the writer that replaced the drafter is told the reader too —")
    kit_a = {"tenant": T, "name": "Baci Milano", "_reader": reader_}
    ck("a plan's reader reaches the article's story and its writer",
       "WHO IS SEARCHING" in ar._reader_block(kit_a) and HOSTESS_PAINS[1] in ar._reader_block(kit_a)
       and "%(reader)s" in ar._COMPOSE_PROMPT)
    ck("  and with none named the searcher is the reader — nothing is added", ar._reader_block({"tenant": T}) == "")
    got: dict = {}
    real_ar = ar.run
    ar.run = lambda tenant, keyword, **k: (got.update(k) or {"ok": False, "status": "failed", "rounds": [],
                                                            "note": "stopped by the suite", "why": "stopped"})
    blog = systems.find(T, "blog") or systems.create(T, "blog")
    with db.SessionLocal() as s:
        s.get(db.System, blog.id).status = "live"
        s.commit()
    skill.run("blog_article", T, keyword="melamine dinnerware set", audience_key="core_hostess",
              generate_visual="no")
    ar.run = real_ar
    ck("the blog skill hands the maker the reader it was planned for",
       ((got.get("reader") or {}).get("who") == "Women 35–44 — the core buyer"), str(got.get("reader"))[:160])

    print()
    print("ALL GREEN" if not _fail else f"{len(_fail)} FAILED: " + "; ".join(_fail))
    return 0 if not _fail else 1


if __name__ == "__main__":
    config.ANTHROPIC_API_KEY = ""
    sys.exit(main())
