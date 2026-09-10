"""Whether an answer engine can fetch the page, and whether one sent anybody.

Owner, 2026-09-10, on what would improve answer-engine ranking. Two of the gaps
change decisions rather than adding signal: nothing verified that the engines
are ALLOWED to read these sites, which gates everything else the blog system
does, and nothing measured whether being cited sends anyone, so the loop could
never close.

THE DISTINCTION THIS SUITE EXISTS TO PROTECT: a search crawler decides whether
an engine can cite the page; a training crawler decides whether the content
trains a model. Blocking `GPTBot` does not remove a site from ChatGPT's answers
— that is `OAI-SearchBot`, and OpenAI says so — and Google states that
`Google-Extended` does not affect inclusion or ranking in Search, while AI
Overviews are served from the Search index by `Googlebot`. A checker that
collapses the two gives confidently wrong advice, which is worse than none.

Driven through a stubbed HTTP seam: robots files and edge responses are the
inputs, and what the verdict says about them is the whole behaviour.

    python3 scripts/test_can_the_engines_read_us.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ae.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = json.dumps(
    {"baci": {"domain": "bacimilanousa.com", "platform": "shopify",
              "creds_key": "baci", "database": "us"}})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import answer_engines as ae, db, google_seo, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class _R:
    def __init__(self, text="", status=200):
        self.text, self.status_code = text, status


def serve(robots: str = "", *, refuse=(), status=200, boom=False):
    """A site: one robots.txt, and a page that may refuse some user agents."""
    def _get(url, timeout=None, follow_redirects=None, headers=None):
        if boom:
            raise ConnectionError("nope")
        ua = (headers or {}).get("User-Agent", "")
        if url.endswith("/robots.txt"):
            return _R(robots, status if robots or status != 200 else 404)
        return _R("<html>ok</html>", 403 if ua in refuse else 200)
    ae.httpx.get = _get


def main() -> int:
    db.init_db()
    tenants.seed()
    real_get = ae.httpx.get
    try:
        print("— the roster is the operators' own, and every entry says its job —")
        ck("each crawler carries a role and the page it was read from",
           all(m.get("role") in ("search", "user", "training") and m.get("doc", "").startswith("https://")
               and m.get("engine") for m in ae.CRAWLERS.values()))
        ck("the search crawlers are the ones a citation depends on",
           set(ae.SEARCH_CRAWLERS) == {"OAI-SearchBot", "PerplexityBot",
                                       "Claude-SearchBot", "Googlebot"},
           str(ae.SEARCH_CRAWLERS))
        ck("Googlebot is the AI Overviews crawler, not Google-Extended",
           ae.CRAWLERS["Googlebot"]["role"] == "search"
           and ae.CRAWLERS["Google-Extended"]["role"] == "training",
           "Google: Google-Extended does not affect inclusion or ranking in Search")
        ck("GPTBot is training and OAI-SearchBot is the one that gets cited",
           ae.CRAWLERS["GPTBot"]["role"] == "training"
           and ae.CRAWLERS["OAI-SearchBot"]["role"] == "search")

        print("\n— what robots.txt says —")
        serve("User-agent: *\nDisallow: /cart\n")
        got = ae.access("baci")
        ck("an ordinary robots file blocks nothing and the verdict says so",
           got["ok"] is True and not got["blocked_search"], got["verdict"][:70])

        serve("User-agent: GPTBot\nDisallow: /\n"
              "\nUser-agent: Google-Extended\nDisallow: /\n")
        got = ae.access("baci")
        ck("blocking ONLY the training crawlers is not a problem",
           got["ok"] is True and not got["blocked_search"]
           and got["blocked_training"] == ["GPTBot", "Google-Extended"],
           got["verdict"][:70])
        ck("and it is reported as the licensing choice it is",
           "does not affect being cited" in got["training_note"],
           got["training_note"][:80])

        serve("User-agent: OAI-SearchBot\nDisallow: /\n"
              "\nUser-agent: PerplexityBot\nDisallow: /\n")
        got = ae.access("baci")
        ck("blocking the SEARCH crawlers is a problem, and it is named",
           got["ok"] is False
           and got["blocked_search"] == ["OAI-SearchBot", "PerplexityBot"]
           and "cannot be cited" in got["verdict"], got["verdict"][:90])

        serve("User-agent: *\nDisallow: /\n")
        got = ae.access("baci")
        # EVERYTHING BUT THE TRAINING CRAWLERS. A `user` crawler is counted
        # with the search ones on purpose: blocking it means the engine cannot
        # fetch the page even when a person asks it to, which costs the same
        # citation a search block costs.
        ck("a blanket disallow blocks every engine that could cite us",
           set(got["blocked_search"]) == {t for t, m in ae.CRAWLERS.items()
                                          if m["role"] != "training"}
           and set(got["blocked_training"]) == {t for t, m in ae.CRAWLERS.items()
                                                if m["role"] == "training"},
           str(got["blocked_search"]))

        serve(status=404)
        got = ae.access("baci")
        ck("NO robots.txt is permission, never 'unknown'",
           got["ok"] is True and "nothing is disallowed" in got["robots"]["source"],
           got["robots"]["source"])

        print("\n— and what the server actually does, which robots cannot say —")
        serve("User-agent: *\nAllow: /\n", refuse=("PerplexityBot",))
        got = ae.access("baci")
        ck("a crawler refused at the edge is caught even though robots allows it",
           got["ok"] is False and got["refused_at_edge"] == ["PerplexityBot"]
           and "whatever robots.txt says" in got["verdict"], got["verdict"][:90])
        ck("the ones the server does serve are marked served",
           got["edge"]["crawlers"]["Googlebot"]["served"] is True)

        serve("User-agent: *\nAllow: /\n",
              refuse=ae.SEARCH_CRAWLERS + (ae._HUMAN_UA,))
        got = ae.access("baci")
        ck("a site that refuses a browser too is down, not blocking",
           got["edge"]["ok"] is False and "nothing here would be about crawlers"
           in got["edge"]["why"], got["edge"].get("why", "")[:70])

        serve("User-agent: *\nAllow: /\n", refuse=("Googlebot",))
        got = ae.access("baci", probe=False)
        ck("without the probe it says it only read robots.txt",
           got["ok"] is True and "not probed" in got["verdict"], got["verdict"][:70])

        serve(boom=True)
        got = ae.access("baci")
        ck("a site that cannot be reached is unknown, not healthy",
           got["ok"] is None and "could not read robots.txt" in got["verdict"],
           got["verdict"][:70])

        print("\n— who an answer engine sent —")
        real_report = google_seo._ga_report
        google_seo._ga_report = lambda p, d, dims, limit=25, organic_only=False: json.dumps([
            {"sessionSource": "google", "sessions": "900"},
            {"sessionSource": "chatgpt.com", "sessions": "31"},
            {"sessionSource": "www.perplexity.ai", "sessions": "7"},
            {"sessionSource": "gemini.google.com", "sessions": "4"},
            {"sessionSource": "(direct)", "sessions": "120"}])
        try:
            r = ae.referrals("baci", days=28)
            ck("only the answer engines are counted, and by engine",
               r["ok"] and r["sessions"] == 42
               and r["by_engine"] == {"ChatGPT": 31, "Perplexity": 7, "Gemini": 4},
               str(r.get("by_engine")))
            ck("and it says what a zero would and would not prove",
               "Zero is not proof" not in r["means"] or r["sessions"] == 0)
            google_seo._ga_report = lambda *a, **k: "No GA4 property is linked."
            r0 = ae.referrals("baci", days=28)
            ck("a sentence back from Analytics is a refusal, never zero sessions",
               r0["ok"] is False and "No GA4 property" in r0["why"], str(r0)[:80])
        finally:
            google_seo._ga_report = real_report

        print("\n— the result is stored, so a page renders without calling out —")
        serve("User-agent: OAI-SearchBot\nDisallow: /\n")
        google_seo._ga_report = lambda *a, **k: "[]"
        try:
            ae.check("baci")
        finally:
            google_seo._ga_report = real_report
        kept = ae.stored("baci")
        ck("the check is kept with what it found and when",
           kept["access"]["blocked_search"] == ["OAI-SearchBot"] and kept.get("at"))

        calls = {"n": 0}

        def _counting(*a, **k):
            calls["n"] += 1
            raise AssertionError("the card must not call anything")
        ae.httpx.get = _counting
        from app import admin_ui
        card = admin_ui._answer_engine_access("s3cret", "baci")
        ck("rendering the card makes no request at all", calls["n"] == 0)
        ck("it shows the verdict and the control together",
           "OAI-SearchBot" in card and "Check again" in card
           and "/admin/answer_engines" in card)
        ck("a blocked TRAINING crawler is not shown as something to fix",
           "a licensing choice, not a citation problem" in
           admin_ui._answer_engine_access("s3cret", "baci")
           or "OAI-SearchBot" in card)

        # THE SERIES, not a marker: "since when" is the question that follows
        # a bad reading, and a key overwritten in place cannot answer it.
        ck("the check is a row in a series, so a change has a date",
           len(ae.history("baci")) >= 1
           and ae.history("baci")[0]["ok"] == "no",
           str(ae.history("baci")[:1]))
        with db.SessionLocal() as s:
            for row in s.query(db.AnswerEngineCheck).all():
                s.delete(row)
            s.commit()
        ck("never checked says so, and still offers the button",
           "Not checked yet" in admin_ui._answer_engine_access("s3cret", "baci"))

        print("\n— and it is a weekly job, not something to remember —")
        import re
        wsrc = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "worker.py")).read()
        ck("the access check runs weekly, sharded, around _safe",
           re.search(r'_safe\(answer_engines_sharded, "[^"]+", sharded=True\)',
                     wsrc) is not None)
    finally:
        ae.httpx.get = real_get

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
