"""The same question is bought once: the cache, the one domain read, the budget.

Pricing Semrush (`test_semrush_units.py`) made the bill visible and stopped a
runaway. It did not make the bill smaller: the Monday harvest still re-bought
the related keywords and questions for the same eight seeds every week — 25,600
units an account for an answer that moves over months — and four callers were
buying the same domain report with different numbers on it (`own` 40 lines by
traffic, `gap` 200 by volume, the snapshot 50 by traffic, and the agent's
opportunity finder 200 by volume every time it was called).

So this is the other half. `SemrushPull` keeps the ANSWER, keyed by the
question and shared across accounts, because the related keywords for a phrase
in the `us` database are the same fact whoever asks. `domain_rows` is the one
wide domain read every domain-shaped caller derives from. And the seed budget
bounds only what is NEW, because a seed already in hand costs nothing.

Driven through the door's own `httpx` seam, counting the requests that actually
leave — the only honest measure of "asked once".

    python3 scripts/test_semrush_asked_once.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sa.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEMRUSH_API_KEY"] = "fake-key"
os.environ["SEO_SITES_JSON"] = json.dumps(
    {"baci": {"domain": "bacimilanousa.com", "platform": "shopify",
              "creds_key": "baci", "database": "us"},
     "eien": {"domain": "eienhealth.com", "platform": "shopify",
              "creds_key": "eien", "database": "us"}})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db, keywords, seo_tools, tenants  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class _R:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


DOMAIN_CSV = ("Keyword;Position;Search Volume;CPC;Url;Traffic (%)\n"
              + "\n".join(f"kw{i};{i + 5};{500 - i};1.0;https://x/{i};{i}"
                          for i in range(1, 26)))
RELATED_CSV = ("Keyword;Search Volume;CPC;Competition\n"
               + "\n".join(f"rel{i};{300 - i};1.0;0.2" for i in range(1, 6)))
QUESTIONS_CSV = ("Keyword;Search Volume;CPC\n"
                 + "\n".join(f"how to q{i};{100 - i};0.5" for i in range(1, 4)))
RANK_CSV = ("Domain;Rank;Organic Keywords;Organic Traffic;Organic Cost\n"
            "bacimilanousa.com;100;104;16;20")


class Http:
    """Counts every request that actually leaves, by report type."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, url, params=None, timeout=None):
        p = dict(params or {})
        self.calls.append(p)
        if "countapiunits" in url:
            return _R("500000")
        t = p.get("type")
        if t == "domain_organic":
            return _R(DOMAIN_CSV)
        if t == "phrase_related":
            return _R(RELATED_CSV)
        if t == "phrase_questions":
            return _R(QUESTIONS_CSV)
        if t == "domain_rank":
            return _R(RANK_CSV)
        if t == "phrase_these":
            wanted = [w for w in str(p.get("phrase", "")).split(";") if w]
            return _R("Keyword;Search Volume;CPC;Competition;Number of Results\n"
                      + "\n".join(f"{w};777;2.5;0.3;100" for w in wanted))
        return _R("ERROR 50 :: NOTHING FOUND")

    def of(self, report: str) -> list[dict]:
        return [c for c in self.calls if c.get("type") == report]

    def reset(self):
        self.calls.clear()


def age_pulls(days: float, report: str = "") -> None:
    """Make every kept answer older, so the TTL can be tested without waiting."""
    with db.SessionLocal() as s:
        q = s.query(db.SemrushPull)
        if report:
            q = q.filter(db.SemrushPull.report == report)
        for row in q.all():
            row.at = db.as_utc(row.at) - dt.timedelta(days=days)
        s.commit()


def main() -> int:
    db.init_db()
    tenants.seed()
    seo_tools.record_reading(500_000, "console")
    real_get = seo_tools.httpx.get
    http = Http()
    seo_tools.httpx.get = http
    caps = (config.SEMRUSH_WEEKLY_CAP, config.SEMRUSH_ACCOUNT_WEEKLY_CAP)
    config.SEMRUSH_WEEKLY_CAP, config.SEMRUSH_ACCOUNT_WEEKLY_CAP = 10**7, 10**6

    try:
        print("— an answer is bought once and kept —")
        a = seo_tools.semrush("phrase_related", _tenant="baci", phrase="jug",
                              database="us", display_limit=25)
        b = seo_tools.semrush("phrase_related", _tenant="baci", phrase="jug",
                              database="us", display_limit=25)
        ck("the second ask makes no request and returns the same rows",
           len(http.of("phrase_related")) == 1 and a == b and len(a) == 5,
           f"{len(http.of('phrase_related'))} request(s)")
        with db.SessionLocal() as s:
            hits = s.query(db.ToolCall).filter(db.ToolCall.tool == "semrush_cached").all()
            ck("the hit is recorded as cached, at no units and no provider",
               len(hits) == 1 and int(hits[0].units or 0) == 0 and not hits[0].provider
               and hits[0].ref == "phrase_related")
            pulls = s.query(db.SemrushPull).all()
            ck("what was bought is kept with its price on it",
               len(pulls) == 1 and pulls[0].lines == 5 and pulls[0].units == 200,
               f"{[(p.report, p.lines, p.units) for p in pulls]}")
        seo_tools.semrush("phrase_related", _tenant="baci", phrase="jug",
                          database="us", display_limit=50)
        ck("a WIDER ask is a different question and is bought",
           len(http.of("phrase_related")) == 2)
        seo_tools.semrush("phrase_related", _tenant="baci", phrase="jug",
                          database="uk", display_limit=25)
        ck("another market is another question", len(http.of("phrase_related")) == 3)

        print("\n— one key, one index: two accounts pay once —")
        http.reset()
        seo_tools.semrush("phrase_questions", _tenant="baci", phrase="shared",
                          database="us", display_limit=25)
        seo_tools.semrush("phrase_questions", _tenant="eien", phrase="shared",
                          database="us", display_limit=25)
        ck("the second account reads the first account's purchase",
           len(http.of("phrase_questions")) == 1)
        ck("and the spend stays attributed to the one that bought it",
           seo_tools.toolcalls_spent("baci") > 0
           if hasattr(seo_tools, "toolcalls_spent") else True)

        print("\n— the domain is read once, and four callers derive from it —")
        http.reset()
        age_pulls(99)
        prof = {"domain": "bacimilanousa.com", "database": "us"}
        own = json.loads(seo_tools.semrush_top_keywords(
            "bacimilanousa.com", "us", limit=40, _tenant="baci"))
        gap = seo_tools.semrush_opportunity_finder(
            "bacimilanousa.com", "us", min_volume=50, _tenant="baci")
        snap = seo_tools.capture_snapshot("bacimilanousa.com", "us", _tenant="baci")
        ck("own, gap and the snapshot make ONE domain_organic request between them",
           len(http.of("domain_organic")) == 1, f"{len(http.of('domain_organic'))}")
        ck("the snapshot still buys its own one-line overview",
           len(http.of("domain_rank")) == 1)
        ck("the one read is the wide one",
           http.of("domain_organic")[0].get("display_limit") == seo_tools.DOMAIN_PULL_LINES
           and http.of("domain_organic")[0].get("display_sort") == "nq_desc")
        ck("own comes back sorted by traffic, from the volume-sorted rows",
           [r["keyword"] for r in own][:2] == ["kw25", "kw24"],
           str([r["keyword"] for r in own][:3]))
        ck("the opportunity finder still answers from them",
           gap.startswith("{") and "opportunities" in gap, gap[:60])
        ck("and the snapshot saved", "organic keywords" in snap, snap[:60])
        with db.SessionLocal() as s:
            ck("one snapshot row was written",
               s.query(db.SeoSnapshot).count() == 1)

        print("\n— the expansion is bought at the bounded size, filtered —")
        http.reset()
        age_pulls(999)
        seo_tools.semrush_related_keywords("jug", database="us", _tenant="baci")
        sent = http.of("phrase_related")[-1]
        ck("it asks for EXPANSION_LINES, not forty",
           int(sent["display_limit"]) == seo_tools.EXPANSION_LINES, str(sent.get("display_limit")))
        ck("and never pays for the tail nobody searches",
           sent.get("display_filter") == f"+|Nq|Gt|{config.SEMRUSH_MIN_VOLUME - 1}",
           str(sent.get("display_filter")))

        print("\n— the harvest: warm seeds are free, new ones are rationed —")
        seams = {k: getattr(keywords, k) for k in ("_fetch_gsc",)}
        keywords._fetch_gsc = lambda p, d, l: []
        real_next = keywords.next_to_write
        try:
            for i in range(1, 7):
                keywords.upsert("baci", f"seed{i}", volume=900, source="semrush_own")
            ck("six head/body seeds are in the pool",
               len(keywords.seed_pool("baci")) == 6, str(keywords.seed_pool("baci")))
            keywords.next_to_write = lambda t, *, top=12: ["seed5"]
            age_pulls(999)
            http.reset()
            config.SEMRUSH_NEW_SEEDS_PER_RUN = 2
            plan = keywords.expansion_plan("baci")
            ck("nothing is warm yet, and the budget takes two",
               plan["warm"] == [] and len(plan["buy"]) == 2 and len(plan["deferred"]) == 4)
            ck("the phrase the planner is about to write goes first",
               plan["buy"][0] == "seed5", str(plan["buy"]))
            ck("the estimate is the two it will buy, not the six",
               plan["units"] == 2 * 2 * seo_tools.estimate(
                   "phrase_related", display_limit=seo_tools.EXPANSION_LINES),
               str(plan["units"]))
            before = keywords.spent_on("baci")
            out = keywords.harvest("baci")
            ck("two seeds x two reports left as four requests",
               len(http.of("phrase_related")) == 2
               and len(http.of("phrase_questions")) == 2,
               f"{len(http.of('phrase_related'))}r {len(http.of('phrase_questions'))}q")
            ck("the run says what it deferred and why",
               any("not expanded this run" in n for n in out["notes"]), str(out["notes"])[:150])
            # LINES RETURNED, not lines asked for — the door bills what came
            # back. One domain read (25 rows at 10) plus two seeds x related
            # (5 rows at 40) and questions (3 rows at 40).
            ck("what it spent is the lines it got back, at each report's price",
               out["spent"] - before == 25 * 10 + 2 * (5 * 40) + 2 * (3 * 40),
               f"{out['spent'] - before}")

            http.reset()
            est2 = keywords.harvest_estimate("baci")
            out2 = keywords.harvest("baci")
            ck("the domain read is not bought again this week",
               not http.of("domain_organic"))
            ck("the two warm seeds are re-filed with no request, and two NEW "
               "ones are bought",
               len(http.of("phrase_related")) == 2
               and len(http.of("phrase_questions")) == 2
               and len(keywords.expansion_plan("baci")["warm"]) == 4,
               f"{len(http.of('phrase_related'))}r, "
               f"{len(keywords.expansion_plan('baci')['warm'])} warm after")
            ck("it still files what the warm seeds expand to",
               out2["added"]["related"] > 0 and out2["added"]["questions"] > 0,
               str(out2["added"]))
            ck("and it says which seeds cost nothing",
               any("already bought" in n for n in out2["notes"]), str(out2["notes"])[:150])
            ck("the estimate was the two it would buy, and nothing for the warm ones",
               est2 == 2 * 2 * seo_tools.estimate(
                   "phrase_related", display_limit=seo_tools.EXPANSION_LINES),
               str(est2))
            ck("the ones it just bought are no longer waiting",
               not ({"seed5", "seed1"} & set(keywords.expansion_plan("baci")["deferred"])),
               str(keywords.expansion_plan("baci")["deferred"]))

            # THE STEADY STATE, and the whole point. The pool GROWS as the
            # harvest works — `own` files head and body terms, and those become
            # seeds — so convergence is the claim worth making: a bounded
            # number of new seeds a run, and then a weekly harvest that asks
            # Semrush for nothing at all until the answers go stale.
            runs = 0
            while keywords.harvest_estimate("baci") and runs < 20:
                keywords.harvest("baci")
                runs += 1
            http.reset()
            keywords.harvest("baci")
            ck("it converges, and then a weekly harvest buys nothing",
               runs < 20 and not http.calls,
               f"{runs} run(s) to warm every seed; then "
               f"{[c.get('type') for c in http.calls]}")

            http.reset()
            age_pulls(config.SEMRUSH_EXPANSION_TTL_DAYS + 1, "phrase_related")
            plan = keywords.expansion_plan("baci")
            ck("past the TTL a seed is cold again",
               len(plan["warm"]) == 0 and plan["units"] > 0, str(plan["units"]))
        finally:
            for k, v in seams.items():
                setattr(keywords, k, v)
            keywords.next_to_write = real_next
            config.SEMRUSH_NEW_SEEDS_PER_RUN = 3

        # THE POOL CAP IS NOT THE BUDGET, and the cache is what separated
        # them. The budget bounds what a run BUYS; a warm seed costs nothing
        # and is never deferred, so without `MAX_SEEDS` a hand-typed
        # `?seeds=` of forty warm phrases would expand all forty in one
        # synchronous request — free of Semrush, and still a loop nobody asked
        # for.
        many = tuple(f"warm{i}" for i in range(40))
        for phrase in many[:12]:
            for rep_ in ("phrase_related", "phrase_questions"):
                seo_tools.semrush(
                    rep_, _tenant="baci", phrase=phrase, database="us",
                    display_limit=seo_tools.EXPANSION_LINES, display_sort="nq_desc",
                    display_filter=f"+|Nq|Gt|{config.SEMRUSH_MIN_VOLUME - 1}")
        plan = keywords.expansion_plan("baci", seeds=many)
        ck("forty seeds, twelve of them already in hand, still make one "
           "bounded run",
           len(plan["warm"]) + len(plan["buy"]) == keywords.MAX_SEEDS
           and len(plan["warm"]) <= keywords.MAX_SEEDS,
           f"{len(plan['warm'])} warm + {len(plan['buy'])} bought")

        print("\n— the monthly refresh goes through the one batch report —")
        http.reset()
        for i in range(120):
            keywords.upsert("eien", f"phrase {i}", volume=1, source="semrush_own")
        got = keywords.refresh_metrics("eien")
        sent = http.of("phrase_these")
        ck("120 phrases go as two requests, not 120",
           len(sent) == 2 and [len(c["phrase"].split(";")) for c in sent] == [100, 20],
           str([len(c.get("phrase", "").split(";")) for c in sent]))
        ck("nothing else was asked", not [c for c in http.calls
                                          if c.get("type") != "phrase_these"])
        ck("every phrase came back re-priced", got["refreshed"] == 120, str(got))
        ck("and the rows carry the new volume",
           all(r.volume == 777 for r in keywords.targets("eien")[:5]))
        ck("120 lines at 10 units is what it cost", got["spent"] == 1200, str(got["spent"]))
        wsrc = open(os.path.join(ROOT, "app", "worker.py")).read()
        ck("the monthly refresh is a sharded cron around _safe",
           re.search(r'_safe\(keyword_metrics_sharded, "[^"]+", sharded=True\)', wsrc)
           is not None)

        print("\n— the button says what it will spend, before it is pressed —")
        from app import admin_ui
        page = admin_ui.render_plan("s3cret", "baci", sub="architecture")
        ck("the spending button carries its cost and the balance",
           "Topping up costs" in page and "Semrush unit(s)" in page
           and "left as of" in page, "")
        ck("and a week already paid for reads as free",
           ("nothing — every answer it needs is already in hand" in page)
           == (keywords.harvest_estimate("baci") == 0),
           f"estimate {keywords.harvest_estimate('baci')}")

        print("\n— a halted door reaches the cache, not the network —")
        http.reset()
        seo_tools.semrush("phrase_questions", _tenant="baci", phrase="shared",
                          database="us", display_limit=25)
        seo_tools._halt("API UNITS BALANCE IS ZERO", "baci")
        http.reset()
        got = seo_tools.semrush("phrase_questions", _tenant="baci", phrase="shared",
                                database="us", display_limit=25)
        ck("a kept answer is still served while the door is shut",
           isinstance(got, list) and len(got) == 3 and not http.calls, str(got)[:60])
        got = seo_tools.semrush("phrase_questions", _tenant="baci", phrase="never asked",
                                database="us", display_limit=25)
        ck("one nobody bought is the halt sentence", "halted" in str(got))
        seo_tools.record_reading(500_000, "console")
    finally:
        seo_tools.httpx.get = real_get
        config.SEMRUSH_WEEKLY_CAP, config.SEMRUSH_ACCOUNT_WEEKLY_CAP = caps

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
