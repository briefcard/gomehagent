"""Reading the competition is capped, scoped to prioritised words, and cheap.

Rivals are the ONE Semrush read charged per phrase rather than per account, so
the only thing standing between this feature and an open-ended bill is a cap
that actually binds. The owner set the scope and the constraint in the same
breath (2026-09-02): "just based on the words we're prioritizing. We dont want
an expensive solution that we dont actually need or use regularly."

Counted, not timed, and counted at the SEAM — `_fetch_serp` is the single door
every Semrush rival read goes through, so a count there is the bill.

Every cap check is written `== CAP`, never `<= CAP`. A `<=` passes when the
fetcher is broken and makes zero calls, which is the failure this file exists
to catch, and it is why each cap check is preceded by a precondition proving
there was MORE work available than the cap allows.

Run: python3 scripts/test_rivals.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rv.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, keywords, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _serp(n=5, ours=None):
    """A fake SERP: n rivals, optionally with our own domain planted in it."""
    rows = [{"domain": f"rival{i}.com", "position": float(i + 1),
             "url": f"https://rival{i}.com/p"} for i in range(n)]
    if ours is not None:
        rows.append({"domain": "bacimilanousa.com", "position": float(ours),
                     "url": "https://bacimilanousa.com/x"})
    return rows


def _count_fetches(fn, rows_for=None):
    """Run fn with `_fetch_serp` counted and stubbed. Returns (calls, phrases)."""
    seen = []
    real = keywords._fetch_serp

    def _stub(profile, phrase, limit):
        seen.append(phrase)
        return (rows_for(phrase) if rows_for else _serp(5, ours=9))

    keywords._fetch_serp = _stub
    try:
        fn()
    finally:
        keywords._fetch_serp = real
    return len(seen), seen


def main() -> int:
    db.init_db()
    tenants.seed()

    CAP = keywords.RIVALS_MAX_PHRASES
    OVER = CAP + 8
    with db.SessionLocal() as s:
        for i in range(OVER):
            s.add(db.KeywordTarget(tenant="baci", phrase=f"word {i}",
                                   status="candidate", priority=100 - i))
        # Muted is a decision already made. If it reaches the scope we are both
        # spending money on a ruled-out word and re-presenting it.
        s.add(db.KeywordTarget(tenant="baci", phrase="muted word",
                               status="candidate", priority=999,
                               owner_priority="muted"))
        # IN THE MAP, IN NEITHER LANE, AND TOP OF THE MAP BY PRIORITY. This is
        # the row that separates "the words we are prioritising" from "the
        # first dozen rows of the map": `targets()` sorts it first, and both
        # lanes exclude it — `next_to_write` takes candidates only and
        # `attention` takes published/won only.
        s.add(db.KeywordTarget(tenant="baci", phrase="already filed",
                               status="planned", priority=10_000))
        # Published pages owed a move, so `attention` fills its own twelve.
        # Without these the scope has only one lane to draw on and a missing
        # clamp cannot be told from a working one.
        for i in range(14):
            s.add(db.KeywordTarget(
                tenant="baci", phrase=f"live page {i}", status="published",
                role="support", cluster_key=f"k{i % 5}", priority=500 - i,
                published_at=db.utcnow() - dt.timedelta(days=90)))
        s.commit()
        for i in range(14):
            s.add(db.KeywordReading(tenant="baci", phrase=f"live page {i}",
                                    position=18.0, source="gsc"))
        s.commit()

    # ---- precondition: there is MORE work than the cap allows -------------
    offered = keywords.next_to_write("baci")
    ck("more prioritised words exist than the cap allows",
       len(offered) >= CAP and OVER > CAP,
       f"{OVER} candidates, cap {CAP} — without this the '== cap' below would "
       f"pass on a fetcher that never fired")

    lanes = len(keywords.attention("baci")) + len(offered)
    ck("both lanes are full, so the cap has something to cut",
       lanes > CAP,
       f"{lanes} prioritised word(s) across attention + next-to-write — if the "
       f"lanes summed to the cap on their own, a missing clamp would look "
       f"identical to a working one")

    scope = keywords.rivals_scope("baci")
    ck("the scope is exactly the cap, not both lanes",
       len(scope) == CAP, f"{len(scope)} word(s) of {lanes} available")
    ck("a muted word is never bought",
       "muted word" not in scope,
       "it outranks every other candidate on priority, so only the mute keeps "
       "it out")
    ck("a word in the map but in neither lane is never bought",
       "already filed" not in scope,
       "it is the highest-priority row this account has, so it heads the map — "
       "only being already filed keeps it out, which is what makes this scope "
       "'the words we are working' and not 'the top of the map'")

    # ---- the cap binds against a caller who asks for more -----------------
    n, _ = _count_fetches(lambda: keywords.rivals_refresh("baci", top=999))
    ck("a caller asking for 999 still spends only the cap",
       n == CAP,
       f"{n} fetch(es) — `attention(top=)` and `next_to_write(top=)` both pass "
       f"a caller's number straight through, so the clamp has to be here")

    # ---- the same call again spends nothing (the TTL) ---------------------
    n2, _ = _count_fetches(lambda: keywords.rivals_refresh("baci"))
    ck("a second read inside the window spends nothing",
       n2 == 0,
       f"{n2} fetch(es) — without this the weekly sweep pays in full every "
       f"Monday forever")

    got = keywords.rivals_refresh("baci")
    ck("and it says so rather than looking like it did the work",
       got["skipped"] == CAP and got["fetched"] == 0,
       f"skipped={got['skipped']} fetched={got['fetched']}")

    # ---- forcing past the window costs the cap again, never more ---------
    n3, _ = _count_fetches(lambda: keywords.rivals_refresh("baci", force=True))
    ck("forcing re-reads the cap, not the map",
       n3 == CAP, f"{n3} fetch(es)")

    # ---- what got stored -------------------------------------------------
    row = keywords.latest_serp("baci", scope[0])
    ck("our own position is lifted out of the SERP, not counted as a rival",
       row is not None and row.our_position == 9.0
       and all(v["domain"] != "bacimilanousa.com" for v in (row.rivals or [])),
       f"our_position={getattr(row, 'our_position', None)}, "
       f"{len(getattr(row, 'rivals', []) or [])} rival(s)")

    # ---- a failed fetch must NOT be stored as an empty SERP --------------
    def _rows():
        with db.SessionLocal() as s:
            return s.query(db.KeywordSerp).count()

    before = _rows()
    got_f = {}
    _count_fetches(
        lambda: got_f.update(keywords.rivals_refresh("baci", force=True)),
        rows_for=lambda p: [])
    ck("a fetch that fails writes nothing",
       _rows() == before and got_f.get("failed") == CAP,
       f"{_rows() - before} row(s) written on {got_f.get('failed')} failed "
       f"fetch(es) — Semrush answers every failure with a SENTENCE and the "
       f"parser turns it into [], so storing it would file 'nobody ranks for "
       f"this' — a won SERP — for a key that cannot call the report")

    # ---- the measure of success -----------------------------------------
    with db.SessionLocal() as s:
        s.add(db.KeywordSerp(
            tenant="baci", phrase="tracked", our_position=8.0,
            at=db.utcnow() - dt.timedelta(days=60), depth=6,
            rivals=[{"domain": "a.com", "position": 2.0},
                    {"domain": "b.com", "position": 3.0},
                    {"domain": "c.com", "position": 4.0}]))
        s.add(db.KeywordSerp(
            tenant="baci", phrase="tracked", our_position=3.0,
            at=db.utcnow(), depth=6,
            rivals=[{"domain": "a.com", "position": 2.0},
                    {"domain": "b.com", "position": 5.0},
                    {"domain": "c.com", "position": 6.0}]))
        s.commit()
        # One capture only — the "no baseline yet" case, which every phrase
        # above has already grown out of by being read twice.
        s.add(db.KeywordSerp(tenant="baci", phrase="solo", our_position=5.0,
                             at=db.utcnow(), depth=6,
                             rivals=[{"domain": "z.com", "position": 1.0}]))
        s.commit()
    tracked = [r for r in keywords.overtaking("baci") if r["phrase"] == "tracked"]
    t = tracked[0] if tracked else {}
    ck("passing a rival is counted from the baseline, not asserted",
       t.get("passed") == ["b.com", "c.com"] and t.get("ahead_count") == 1,
       f"passed={t.get('passed')} ahead={t.get('ahead_count')} — we went 8 -> 3 "
       f"while b and c stayed put, so two were passed and a.com was not")
    ck("a single capture reports no baseline rather than zero passed",
       [r for r in keywords.overtaking("baci")
        if r["phrase"] == "solo"][0]["has_baseline"] is False
       and t.get("has_baseline") is True,
       "'0 passed' from one reading is a claim about movement made from one "
       "point — the same false precision as the static numbers this replaces")

    # ---- reading it can never spend -------------------------------------
    n4, _ = _count_fetches(lambda: keywords.overtaking("baci"))
    ck("rendering the answer spends nothing",
       n4 == 0,
       "the Architecture room is built on every Plan request, so a read that "
       "could fetch would be a Semrush call on five unrelated sub-tabs")

    # ---- the seeds overrun this work also closed -------------------------
    hit = {"n": 0}
    real_rel = keywords._fetch_related

    def _rel(profile, phrase, limit):
        hit["n"] += 1
        return []

    keywords._fetch_related = _rel
    try:
        keywords.harvest("baci", seeds=tuple(f"seed {i}" for i in range(40)),
                         sources=("related",))
    finally:
        keywords._fetch_related = real_rel
    ck("a caller's own seed list is capped too",
       hit["n"] == keywords.MAX_SEEDS,
       f"{hit['n']} expansion(s) of 40 seeds — the [:8] used to sit on the "
       f"fallback branch only, so `?seeds=` on the harvest route was an "
       f"unbounded per-seed loop in one synchronous request")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
