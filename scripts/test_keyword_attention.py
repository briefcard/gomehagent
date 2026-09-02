"""A published page that is not working is work, and the board says so.

Owner, 2026-09-01: *"Im not sure if we should be so simplistic as marking a
keyword as planned and then preventing future articles… keywords often need a
few articles to start ranking for them right?"*

Half right, and the half that matters is the distinction. A KEYWORD needs one
page — two aimed at the same query cannibalise and the engine picks one. A
TOPIC needs several, which is what a pillar and its supports already are. So
the answer is never a second article on the same phrase.

The real gap was one step later: `writing_next` is `status == "candidate"`, so
once a page was published its keyword was never proposed again WHATEVER IT
DID — while `progress()` had been measuring position against a control the
whole time. The system measured whether a page ranked and did nothing with the
answer.

FOUR STATES, because they owe different work, and lumping them together is
what would make this lane noise rather than a queue:

  too_early   inside the window — Google has not settled; nothing is owed
  no_reading  no Search Console data — an INDEXING question, not a writing one
  slipping    it ranked and stopped — the most urgent thing on the board
  stalled     past the window, outside the top 3, not refreshed lately

Run: python3 scripts/test_keyword_attention.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ka.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import admin_ui, db, keywords, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _target(phrase, status, live_days, pos=None, won_days=None,
            refreshed_days=None, role="support"):
    keywords.upsert("baci", phrase, status=status, role=role)
    with db.SessionLocal() as s:
        r = (s.query(db.KeywordTarget)
             .filter(db.KeywordTarget.tenant == "baci",
                     db.KeywordTarget.phrase == phrase).first())
        r.published_at = db.utcnow() - dt.timedelta(days=live_days)
        r.won_at = (db.utcnow() - dt.timedelta(days=won_days)
                    if won_days else None)
        r.refreshed_at = (db.utcnow() - dt.timedelta(days=refreshed_days)
                          if refreshed_days else None)
        s.commit()
        if pos is not None:
            s.add(db.KeywordReading(tenant="baci", phrase=phrase,
                                    position=pos, source="gsc"))
            s.commit()


def main() -> int:
    db.init_db()
    tenants.seed()

    _target("a fresh page", "published", 5, pos=18)
    _target("no data page", "published", 60)
    _target("stalled close", "published", 60, pos=7)
    _target("stalled far", "published", 60, pos=22)
    # A CLUSTER WITH SOMETHING LEFT TO WRITE. The band's advice is "supports
    # in its cluster" and it is only that advice when the cluster HAS one
    # available — with none, telling somebody to write supports is advice
    # that cannot be taken. Both cases are asserted below; without this
    # fixture the first assertion silently tested the second case.
    keywords.upsert("baci", "stalled far", cluster_key="mid")
    keywords.upsert("baci", "a narrow question", cluster_key="mid",
                    role="support", status="candidate")
    _target("stalled miles", "published", 60, pos=55)
    _target("slipped one", "published", 90, pos=9, won_days=40)
    _target("winning", "won", 90, pos=2)
    _target("just refreshed", "published", 120, pos=15, refreshed_days=10)

    got = {x["phrase"]: x for x in keywords.attention("baci")}

    print("— four states, each owing something different —")
    ck("a page inside the window is too early",
       got["a fresh page"]["state"] == "too_early",
       "`progress` already refuses to attribute here; acting is the more "
       "expensive mistake")
    ck("no Search Console reading is an INDEXING question",
       got["no data page"]["state"] == "no_reading"
       and "indexed" in got["no data page"]["owed"],
       "a refresh does not answer whether the page is in the index")
    ck("a page that ranked and stopped is SLIPPING",
       got["slipped one"]["state"] == "slipping",
       "`settle` walks it back to `published` the moment it slips, so without "
       "`won_at` this is indistinguishable from never having ranked")
    ck("  and it leads the list",
       keywords.attention("baci")[0]["phrase"] == "slipped one",
       "something that worked and stopped is the most urgent thing here")
    ck("a stalled page is stalled", got["stalled close"]["state"] == "stalled")

    print("\n— and `won_at` is written by SETTLE, not by the fixture —")
    # The fixture above sets `won_at` directly, which tests the reader and
    # nothing else: deleting the writer left every assertion green (sabotage
    # reported MISSED, 2026-09-01). This drives the real path — a page ranks,
    # `settle` marks it won, it slips, `settle` walks it back — so the
    # high-water mark has to survive on its own.
    keywords.upsert("baci", "round trip", status="published")
    with db.SessionLocal() as s:
        r = (s.query(db.KeywordTarget)
             .filter(db.KeywordTarget.phrase == "round trip").first())
        r.published_at = db.utcnow() - dt.timedelta(days=90)
        s.add(db.KeywordReading(tenant="baci", phrase="round trip",
                                position=2.0, source="gsc"))
        s.commit()
    keywords.settle("baci")
    with db.SessionLocal() as s:
        r = (s.query(db.KeywordTarget)
             .filter(db.KeywordTarget.phrase == "round trip").first())
        ck("winning writes the high-water mark",
           r.status == "won" and r.won_at is not None, str(r.status))
        s.add(db.KeywordReading(tenant="baci", phrase="round trip",
                                position=9.0, source="gsc"))
        s.commit()
    keywords.settle("baci")
    with db.SessionLocal() as s:
        r = (s.query(db.KeywordTarget)
             .filter(db.KeywordTarget.phrase == "round trip").first())
        ck("  slipping walks the status back", r.status == "published")
        ck("  but the mark survives", r.won_at is not None,
           "without it, slipped and never-ranked are the same row")
    ck("  so the lane calls it slipping",
       {x["phrase"]: x for x in keywords.attention("baci")}
       .get("round trip", {}).get("state") == "slipping",
       str({x["phrase"]: x["state"] for x in keywords.attention("baci")}))

    print("\n— and the move is chosen by where it actually sits —")
    ck("close: refresh THIS page",
       "refresh this page" in got["stalled close"]["owed"],
       got["stalled close"]["owed"])
    ck("mid: supports in the cluster, not a rewrite",
       "supports in its cluster" in got["stalled far"]["owed"],
       got["stalled far"]["owed"])
    ck("  and it names which ones are left to write",
       got["stalled far"].get("supports", {}).get("writable")
       == ["a narrow question"],
       str(got["stalled far"].get("supports")) + " — the sentence was the end "
       "of the line: nothing said WHICH supports, so no surface could offer "
       "to file them")
    # THE OTHER HALF OF THE SAME BAND. A cluster with nothing left to write
    # gets a different sentence, because "write supports" there is advice
    # somebody follows, finds nothing, and stops trusting the column for.
    _target("stalled empty", "published", 60, pos=25)
    keywords.upsert("baci", "stalled empty", cluster_key="bare")
    empty = {x["phrase"]: x for x in keywords.attention("baci")}["stalled empty"]
    ck("  and a cluster with none left says THAT instead",
       "none left to write" in empty["owed"]
       or "no cluster around it" in empty["owed"],
       empty["owed"])
    ck("far: re-read the intent before spending anything",
       "intent" in got["stalled miles"]["owed"],
       got["stalled miles"]["owed"])

    print("\n— and nothing that is fine is listed —")
    ck("a winning page owes nothing", "winning" not in got)
    ck("  nor does one refreshed inside the cooldown",
       "just refreshed" not in got,
       "offering it again asks for a decision that cannot yet be informed — "
       "it has not been re-crawled")

    print("\n— never a second article on the same phrase —")
    ck("the lane proposes no new page for a published keyword",
       all(x["state"] in ("too_early", "no_reading", "slipping", "stalled")
           for x in got.values())
       and not any("write a new" in x["owed"].lower() for x in got.values()),
       "two pages aimed at one query cannibalise; the engine picks one")
    ck("  and published keywords stay out of Writing next",
       not any(r["phrase"] in got
               for r in keywords.board("baci")["writing_next"]),
       "Writing next is candidates; this lane is the other question")

    print("\n— the board carries it, with the reasoning on the page —")
    b = keywords.board("baci")
    ck("`attention` is on the board", bool(b.get("attention")))
    # ASSERTED ON THE RENDER, not on a name that might not exist. The first
    # version of this called `admin_ui._plan_board`, guarded with `hasattr`,
    # and there is no such function — so it assigned "" and checked nothing.
    # A hollow assertion is worse than none: it reads as coverage.
    card = admin_ui._board_section("s3cret", "baci", 7)
    ck("the lane renders on the Plan board", "Needs attention" in card)
    # THE CHIPS THEMSELVES, not the page. Grepping the card for "no reading"
    # passed with the chip collapsed onto "stalled", because the phrase also
    # occurs in that row's own owed sentence AND in the static paragraph under
    # the table — three times in all. The mutation
    # `_STATE["no_reading"] = ("gap", "stalled")` rendered two states
    # byte-identically and the suite stayed green: exactly the failure the
    # assertion names.
    import re as _re
    chips = _re.findall(r'<span class="chip [a-z]+">([^<]+)</span>', card)
    ck("  every state is drawn distinctly",
       len(set(chips)) == len({r["state"] for r in keywords.attention("baci")}),
       f"{sorted(set(chips))} — four states in one list is a queue; four "
       f"states drawn alike is noise")
    ck("  and each is the state's own word",
       set(chips) >= {"slipping", "stalled"},
       str(sorted(set(chips))))
    ck("  the page it is about is reachable",
       "slipped one" in card and "stalled close" in card)
    # WHITESPACE-NORMALISED. The markup wraps prose across lines, so a raw
    # substring test fails on text that is plainly present — which reads as a
    # missing explanation rather than as a badly written assertion.
    flat = " ".join(card.split())
    ck("  and the reasoning is on the page, not only in my head",
       "two aimed at the same query compete" in flat
       and "A <em>topic</em> needs several" in flat,
       "the rule that says why there is no second article belongs where the "
       "decision is made")
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
