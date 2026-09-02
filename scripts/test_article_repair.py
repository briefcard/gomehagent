"""A blocked article repairs itself on `auto`, and nowhere else.

Owner, 2026-09-02: *"Does the auto have a redraft capability with instruction
on why it failed validation?"*

The loop exists and it is NOT a property of `auto`. `Context.emit` repairs
before `_disposition` is ever consulted, so every rung gets the same attempts —
`auto` no more than `shadow`. What varies by rung is only what happens to a
draft that PASSES.

But the loop only runs when the skill hands `emit` a repairer, and
`blog_article` handed it none. Three of the six emits in this pack passed one;
the article did not — so the longest thing this system writes, and the only one
landing on a public page under the client's own domain, was the one that never
got a second attempt. A banned phrase in paragraph nine blocked the whole piece
and waited for a person, at every rung including `auto`, where nobody is
watching and a blocked draft costs the most.

WHAT THE RETRY IS TOLD: the checker's own `detail` and `fix`, verbatim.
Paraphrasing them here would be a second vocabulary for the gate the draft has
to pass, and the drafter would be reasoning about the paraphrase.

AND IT ONLY HAPPENS ON `auto`. Owner, 2026-09-02: *"Lets make sure this only
happens for auto rung because manually I\'d like to catch if things need to be
updated and how."* On a manual rung a person READS the output, and a draft that
silently rewrote itself hides the thing they are there to see: which rule keeps
biting, and whether the rule or the brief is what needs changing. On `auto`
nobody reads it, so a blocked draft is a silent gap and self-correction is all
that stands between a rejection and nothing happening. The failures are kept
either way — the manual rungs lose a repair they did not ask for, never the
named rule, the phrase, or the fix.

Run: python3 scripts/test_article_repair.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ar.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, skill, skill_pack, systems, tenants  # noqa: E402

_fail = []
MANUAL = ""


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  → {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


GOOD = ("<h1>Acrylic jugs</h1><p>An acrylic jug is a jug made of acrylic, and "
        "this sentence exists so the body is long enough to be an article "
        "rather than a stub.</p>")
BANNED = GOOD.replace("made of acrylic", "handmade in Italy")


def _setup(tenant):
    kb.ensure_brand(tenant, tenant.title())
    row = systems.find(tenant, "blog") or systems.create(tenant, "blog")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        b = s.get(db.KbBrand, tenant)
        b.positioning = "Mid-century tableware."
        b.voice = {"tone": ["plain"]}
        b.banned_claims = ["handmade"]
        s.commit()
    kb.add_claim(tenant, f"{tenant.title()} jugs are dishwasher safe.",
                 "lab report", [])


def main() -> int:
    db.init_db()
    tenants.seed()
    # A second SEEDED account, so the manual half differs from the auto half
    # in exactly one thing: the rung.
    global MANUAL
    MANUAL = next(t.key for t in tenants.all_tenants() if t.key != "baci")

    print("— the repair loop is emit's, and it runs BEFORE the rung —")
    ck("a failed check blocks at every rung, auto included",
       skill._disposition("auto", False, True) == "blocked"
       and skill._disposition("shadow", False, True) == "blocked",
       "`auto` never means send the thing that failed")
    ck("the attempt budget is one number for the whole platform",
       skill.MAX_REPAIRS == 3,
       f"MAX_REPAIRS={skill.MAX_REPAIRS} — a rung-specific budget would mean "
       f"'try harder because nobody is watching', which is backwards")

    print()
    print("— the article now hands emit a repairer —")
    _setup("baci")
    with db.SessionLocal() as sx:
        sx.get(db.System, systems.find("baci", "blog").id).autonomy = "auto"
        sx.commit()
    seen = []
    calls = {"n": 0}

    def _drafter(bundle, keyword, role, angle, questions, links, entity,
                 avoid=None):
        calls["n"] += 1
        seen.append(bundle.get("rules", {}).get("block", ""))
        # First attempt breaks the ban list; the repair fixes it.
        return (BANNED if calls["n"] == 1 else GOOD), ""
    skill_pack._draft_article_live = _drafter

    r = skill.run("blog_article", "baci", keyword="acrylic jug", role="pillar")
    ck("it was asked more than once", calls["n"] >= 2,
       f'{calls["n"]} call(s) — one means the article still has no repairer, '
       f'which is the state this fixes')
    ck("  and the result is not blocked",
       r.get("status") != "blocked", str(r.get("status")))
    item = (r.get("items") or [{}])[-1]
    ck("  the banned phrase is gone from what shipped",
       "handmade" not in (item.get("body") or ""),
       (item.get("body") or "")[:80])
    ck("  and the rejected attempt is on the record",
       item.get("repairs", 0) >= 1 and bool(item.get("repair_history")),
       f'repairs={item.get("repairs")} — a repair nobody can count is a '
       f'repair rate nobody can measure')

    print()
    print("— and the repaired body still gets its pictures placed —")
    # A REPAIR IS A FRESH DRAFT, WITH FRESH MARKERS. `place_images` ran once,
    # on the FIRST body; the repaired one came back carrying
    # `<!--IMAGE: …-->` that nothing filled, and `emit` took it as final. So a
    # repaired article published raw scaffolding and no pictures — and repair
    # runs only on `auto`, the rung that publishes with nobody looking.
    calls["n"] = 0
    MARKED_BAD = BANNED.replace("</p>", "</p>\n<!--IMAGE: a jug on a table-->")
    MARKED_OK = GOOD.replace("</p>", "</p>\n<!--IMAGE: a jug on a table-->")

    def _marked(bundle, keyword, role, angle, questions, links, entity,
                avoid=None):
        calls["n"] += 1
        return (MARKED_BAD if calls["n"] == 1 else MARKED_OK), ""
    skill_pack._draft_article_live = _marked
    rm = skill.run("blog_article", "baci", keyword="acrylic jug",
                   role="pillar")
    itm = (rm.get("items") or [{}])[-1]
    ck("the drafter marked a place in BOTH attempts",
       calls["n"] >= 2,
       f'{calls["n"]} — without a repair this proves nothing')
    ck("  and no raw marker survives into the filed body",
       "<!--IMAGE" not in (itm.get("body") or ""),
       (itm.get("body") or "")[-90:] + " — an HTML comment renders as "
       "nothing, so this ships silently and the page has no pictures")

    print()
    print("— the retry is told WHAT broke, in the checker's own words —")
    second = seen[1] if len(seen) > 1 else ""
    ck("it is shown its own previous article",
       "previous article was rejected" in second and "handmade" in second,
       "asking again without the rejected text is asking the same question")
    # THE CHECKER'S OWN WORDS, and asserted on the FIX rather than on the
    # banned phrase: the phrase also appears in the quoted previous article,
    # so blanking the failure note left the old assertion green. `fix` can
    # only have come from the note.
    ck("  and the named failure, not a paraphrase",
       "Why, and what to change" in second
       and "reword it" in second and "retire the rule" in second,
       "the gate's own `detail` and `fix` — a nicer sentence here would be a "
       "second vocabulary for the rule it has to pass")
    ck("  and the detail, saying which phrase",
       "the draft says 'handmade'" in second,
       "'a banned claim' is a category; the phrase is what gets reworded")
    ck("  and is told to keep what was already right",
       "keep every internal link" in second and "do not drop the claims" in second,
       "a repair that drops the links or the citations trades one block for "
       "another")

    print()
    print("— a drafter with nothing more to give stops the loop —")
    calls["n"] = 0

    def _stuck(bundle, keyword, role, angle, questions, links, entity,
               avoid=None):
        calls["n"] += 1
        return BANNED, ""
    skill_pack._draft_article_live = _stuck
    r2 = skill.run("blog_article", "baci", keyword="melamine bowl",
                   role="support")
    ck("it stops at the cap rather than looping",
       calls["n"] <= skill.MAX_REPAIRS + 1,
       f'{calls["n"]} call(s) against MAX_REPAIRS={skill.MAX_REPAIRS}')
    # THE ITEM, NOT THE RUN. The run's status says it PRODUCED something,
    # which is a fact about the run and true whether or not the thing passed.
    # Reading it here would have asserted a different component's behaviour —
    # and did, on the first cut.
    it2 = (r2.get("items") or [{}])[-1]
    ck("  the still-failing draft is blocked, not shipped",
       it2.get("status") == "blocked" and it2.get("ok") is False,
       f'item status={it2.get("status")}, run status={r2.get("status")} — the '
       f'run produced an item; the item did not pass')
    ck("  and it names what is still wrong",
       any(f.get("rule") == "banned_claim" for f in (it2.get("failures") or [])),
       str(it2.get("failures"))[:120])
    ck("  and it is KEPT, with its text, not lost",
       "handmade" in (it2.get("body") or ""),
       "the copy is worth more than the run — a person can fix a blocked "
       "draft, not a discarded one")

    print()
    print("— and on a manual rung it does NOT repair —")
    # A SEEDED ACCOUNT. The only difference between this half and the one
    # above must be the RUNG — an unknown tenant refuses before drafting
    # and every assertion below would pass on an empty result.
    _setup(MANUAL)
    calls["n"] = 0
    seen.clear()
    skill_pack._draft_article_live = _drafter
    with db.SessionLocal() as sx:
        row = systems.find(MANUAL, "blog")
        ck("the system is on the default rung",
           systems.rung(row) == "shadow",
           f"{systems.rung(row)} — the default, and the one an owner reads")
    r3 = skill.run("blog_article", MANUAL, keyword="acrylic jug", role="pillar")
    ck("the drafter is asked exactly once",
       calls["n"] == 1,
       f'{calls["n"]} call(s) — a silent second attempt is the thing the '
       f'owner asked to stop: it hides which rule is biting')
    it3 = (r3.get("items") or [{}])[-1]
    ck("  the draft is blocked and kept",
       it3.get("status") == "blocked" and "handmade" in (it3.get("body") or ""),
       str(it3.get("status")))
    ck("  with the rule, the phrase and the fix on it",
       any(f.get("rule") == "banned_claim"
           and "handmade" in f.get("detail", "")
           and "reword" in f.get("fix", "")
           for f in (it3.get("failures") or [])),
       str(it3.get("failures"))[:130] + " — this is the 'how' the owner asked "
       "to be able to see")
    ck("  and the run SAYS why it did not repair",
       any("manual rung" in str(n) for n in (r3.get("notes") or [])),
       "silence would read as 'the repairer is broken' rather than as a "
       "deliberate rung difference")
    ck("  and no repair is recorded, because none happened",
       not it3.get("repair_history"),
       str(it3.get("repair_history"))[:60])

    print()
    print("— one reader decides what rung a value means —")
    ck("the gate goes through systems.rung",
       skill._rung("approve_all") == "shadow",
       "a retired word normalised in two places is how it starts behaving "
       "differently depending on which file asked")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
