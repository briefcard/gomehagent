"""Can an answer engine read this site, and is it sending anyone back.

Two questions that gate everything else the blog system does for answer
engines, and neither had a surface. A page written to be cited cannot be cited
by an engine that is not allowed to fetch it, and nothing here checked; and
`keywords.aeo` could say a page ranks well and is not being clicked — which is
consistent with an answer taking the click — while having no way to see whether
any answer sent a click BACK.

**THE SEARCH BOTS DECIDE WHETHER YOU CAN BE CITED. THE TRAINING BOTS DO NOT.**
This is the distinction the whole file exists for, because collapsing it is how
a check like this ends up giving confidently wrong advice. Blocking `GPTBot`
stops OpenAI training on the content and does NOT remove the site from
ChatGPT's answers — that is `OAI-SearchBot`, and OpenAI says so in as many
words. Google states plainly that `Google-Extended` "does not impact a site's
inclusion in Google Search nor is it used as a ranking signal", and AI
Overviews are served from the Search index, so the crawler that decides whether
a page can appear in one is `Googlebot`. Blocking a training crawler is a
licensing decision a brand is entitled to make. Blocking a search crawler is
invisibility, usually by accident.

**ROBOTS IS THE DECLARED POLICY, NOT THE ANSWER.** A CDN can refuse a crawler
by user agent at the edge while robots.txt welcomes it, and several now do that
by default. So there are two checks: what the site SAYS, and what the site
DOES when something identifying itself that way asks for a page. The second is
the one that finds the surprise.

Every token below is transcribed from the operator's own published page and
carries its URL, per the standing rule that a provider contract is taken from
its documentation rather than from memory. Bing and Copilot are deliberately
ABSENT: the documentation page did not render when this was written, and a
roster where one entry is a guess puts every other entry in doubt.
"""
from __future__ import annotations

import datetime as dt
import json

import httpx

from . import config, db

#: What each crawler is for, and — the part that matters — whether being
#: blocked costs a citation or only a training corpus.
#:
#:   search    blocked means this engine cannot surface or link the page
#:   user      blocked means the engine cannot fetch it when a person asks
#:   training  blocked means the content is not used to train a model, which
#:             changes nothing about being cited
CRAWLERS: dict[str, dict] = {
    "OAI-SearchBot": {
        "engine": "ChatGPT", "role": "search",
        "why": "Surfaces sites in ChatGPT's search features. OpenAI: sites "
               "opted out of OAI-SearchBot will not be shown in ChatGPT "
               "search answers.",
        "doc": "https://developers.openai.com/api/docs/bots"},
    "PerplexityBot": {
        "engine": "Perplexity", "role": "search",
        "why": "Surfaces and links sites in Perplexity's results. Perplexity: "
               "not used to crawl content for AI foundation models.",
        "doc": "https://docs.perplexity.ai/guides/bots"},
    "Claude-SearchBot": {
        "engine": "Claude", "role": "search",
        "why": "Analyses content to improve the relevance and accuracy of "
               "search responses.",
        "doc": "https://support.claude.com/en/articles/8896518-does-anthropic-"
               "crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler"},
    "Googlebot": {
        "engine": "Google AI Overviews", "role": "search",
        "why": "AI Overviews are served from the Search index, so this is the "
               "crawler that decides whether a page can appear in one — NOT "
               "Google-Extended.",
        "doc": "https://developers.google.com/search/docs/crawling-indexing/"
               "google-common-crawlers"},
    "ChatGPT-User": {
        "engine": "ChatGPT", "role": "user",
        "why": "Fetches a page when a person asks ChatGPT about it.",
        "doc": "https://developers.openai.com/api/docs/bots"},
    "Perplexity-User": {
        "engine": "Perplexity", "role": "user",
        "why": "Visits a page to answer a question a person just asked, and "
               "links it in the response.",
        "doc": "https://docs.perplexity.ai/guides/bots"},
    "Claude-User": {
        "engine": "Claude", "role": "user",
        "why": "Fetches a page when a person asks Claude about it.",
        "doc": "https://support.claude.com/en/articles/8896518-does-anthropic-"
               "crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler"},
    "GPTBot": {
        "engine": "OpenAI", "role": "training",
        "why": "Trains OpenAI's foundation models. Blocking it does NOT "
               "remove the site from ChatGPT's answers — that is "
               "OAI-SearchBot.",
        "doc": "https://developers.openai.com/api/docs/bots"},
    "ClaudeBot": {
        "engine": "Anthropic", "role": "training",
        "why": "Collects web content that may contribute to model training. "
               "Blocking it does not affect being cited.",
        "doc": "https://support.claude.com/en/articles/8896518-does-anthropic-"
               "crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler"},
    "Google-Extended": {
        "engine": "Gemini", "role": "training",
        "why": "Controls whether crawled content trains Gemini and grounds "
               "Vertex AI. Google: does not impact inclusion in Google Search "
               "nor act as a ranking signal.",
        "doc": "https://developers.google.com/search/docs/crawling-indexing/"
               "google-common-crawlers"},
}

SEARCH_CRAWLERS = tuple(t for t, m in CRAWLERS.items() if m["role"] == "search")

#: A browser-shaped agent, for the control fetch. Without one there is no way
#: to tell "the CDN refuses this crawler" from "the site is down".
_HUMAN_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

#: How a refusal looks at the edge. 401/403 is a rule, 429 is a rate limit
#: applied to the agent, 451 is a legal block; all three mean this crawler does
#: not get the page whatever robots.txt says.
_REFUSED = (401, 403, 429, 451)


def _url(domain: str) -> str:
    d = (domain or "").strip()
    return d if d.startswith(("http://", "https://")) else "https://" + d


def _fetch(url: str, ua: str, timeout: int = 20) -> dict:
    """One GET, with the reason a failure happened rather than a bare ''."""
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": ua})
        return {"ok": True, "status": r.status_code, "text": r.text}
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)[:120]
        if "CERTIFICATE_VERIFY_FAILED" in detail:
            detail = ("TLS certificate chain is incomplete — the server is not "
                      "sending its intermediate certificate")
        return {"ok": False, "status": 0, "text": "",
                "why": f"{exc.__class__.__name__}: {detail}"}


def robots_policy(domain: str, path: str = "/") -> dict:
    """What the site's own robots.txt says about each crawler.

    NO robots.txt IS NOT UNKNOWN — it is permission. A 404 means nothing is
    disallowed, and reporting that as "could not determine" would send somebody
    hunting for a file whose absence is the answer.
    """
    from urllib.robotparser import RobotFileParser

    base = _url(domain)
    got = _fetch(f"{base}/robots.txt", _HUMAN_UA)
    if not got["ok"]:
        return {"ok": False, "why": got.get("why", "robots.txt not reachable"),
                "crawlers": {}}
    parser = RobotFileParser()
    if got["status"] == 200:
        parser.parse(got["text"].splitlines())
        source = "robots.txt"
    else:
        parser.parse([])
        source = f"no robots.txt ({got['status']}), so nothing is disallowed"
    target = base.rstrip("/") + (path if path.startswith("/") else "/" + path)
    return {"ok": True, "source": source,
            "crawlers": {token: {**meta,
                                 "allowed": bool(parser.can_fetch(token, target))}
                         for token, meta in CRAWLERS.items()}}


def edge_check(domain: str, tokens=SEARCH_CRAWLERS, path: str = "/") -> dict:
    """What the site DOES when a crawler asks, which robots.txt cannot say.

    A CDN that refuses AI agents by user agent is invisible to a robots read
    and is, today, the likeliest way a site is unreachable to an answer engine
    without anybody deciding it should be. The control fetch is what makes the
    result mean anything: a site that refuses a browser too is down, not
    blocking.
    """
    base = _url(domain)
    target = base.rstrip("/") + (path if path.startswith("/") else "/" + path)
    control = _fetch(target, _HUMAN_UA)
    # THE CONTROL HAS TO SUCCEED, not merely answer. A site that returns 403 to
    # a browser refuses everyone, so "this crawler got a 403" says nothing
    # about the crawler — and reporting it as a crawler block would send
    # somebody editing robots.txt to fix a site that is simply not serving.
    if not control["ok"] or control["status"] >= 400:
        return {"ok": False, "crawlers": {},
                "why": (f"the site did not serve a normal browser either "
                        f"({control.get('why') or control['status']}), so "
                        f"nothing here would be about crawlers")}
    out = {}
    for token in tokens:
        got = _fetch(target, token)
        out[token] = {
            "status": got["status"],
            "served": bool(got["ok"] and got["status"] < 400),
            "refused": bool(got["ok"] and got["status"] in _REFUSED),
            "why": got.get("why", "")}
    return {"ok": True, "control_status": control["status"], "crawlers": out}


def access(tenant: str, *, probe: bool = True, path: str = "/") -> dict:
    """Whether the answer engines can read this account's site, and the verdict.

    The verdict leads with the SEARCH crawlers, because those are the ones
    whose absence costs a citation. A blocked training crawler is reported and
    explicitly not counted as a problem: it is a decision a brand is allowed to
    make and has no bearing on whether an answer can cite the page.
    """
    from . import sites
    try:
        profile = sites.get(tenant)
    except Exception as exc:  # noqa: BLE001
        return {"tenant": tenant, "ok": False, "why": str(exc)[:200]}
    domain = profile.get("domain", "")
    if not domain:
        return {"tenant": tenant, "ok": False,
                "why": "no domain on this account, so there is nothing to check"}

    pol = robots_policy(domain, path)
    edge = edge_check(domain, path=path) if probe else {"ok": None, "crawlers": {}}

    blocked_search, blocked_training, refused_at_edge = [], [], []
    for token, meta in (pol.get("crawlers") or {}).items():
        if not meta["allowed"]:
            (blocked_search if meta["role"] == "search"
             else blocked_training if meta["role"] == "training"
             else blocked_search).append(token)
    for token, meta in (edge.get("crawlers") or {}).items():
        if meta.get("refused"):
            refused_at_edge.append(token)

    if not pol.get("ok"):
        verdict = f"could not read robots.txt — {pol.get('why', '')}"
        ok = None
    elif blocked_search or refused_at_edge:
        parts = []
        if blocked_search:
            parts.append("robots.txt disallows " + ", ".join(sorted(blocked_search)))
        if refused_at_edge:
            parts.append("the server refuses " + ", ".join(sorted(refused_at_edge))
                         + " at the edge, whatever robots.txt says")
        verdict = ("this site cannot be cited by every engine: " + "; ".join(parts))
        ok = False
    else:
        verdict = ("every search crawler may read this site"
                   + ("" if probe else " — robots.txt only, not probed"))
        ok = True
    return {"tenant": tenant, "domain": domain, "ok": ok, "verdict": verdict,
            "robots": pol, "edge": edge,
            "blocked_search": sorted(blocked_search),
            "refused_at_edge": sorted(refused_at_edge),
            "blocked_training": sorted(blocked_training),
            "training_note": (
                "blocking a training crawler is a licensing choice and does "
                "not affect being cited: " + ", ".join(sorted(blocked_training))
                if blocked_training else ""),
            "at": db.utcnow().isoformat(timespec="minutes")}


#: WHERE AN ANSWER SENDS SOMEBODY. GA4 records the assistant's own host as the
#: session source when a person follows a link out of an answer, so this needs
#: no new integration — the property is already wired for every account that
#: has Google connected.
AI_REFERRERS: dict[str, str] = {
    "chatgpt.com": "ChatGPT",
    "chat.openai.com": "ChatGPT",
    "perplexity.ai": "Perplexity",
    "www.perplexity.ai": "Perplexity",
    "claude.ai": "Claude",
    "gemini.google.com": "Gemini",
    "copilot.microsoft.com": "Copilot",
    "bing.com/chat": "Copilot",
    "you.com": "You.com",
}


def _engine_of(source: str) -> str:
    s = (source or "").strip().lower()
    for host, name in AI_REFERRERS.items():
        if s == host or s.startswith(host) or host.split("/")[0] in s:
            return name
    return ""


def referrals(tenant: str, *, days: int = 28) -> dict:
    """Sessions an answer engine sent, by engine.

    THE OTHER HALF OF `keywords.aeo`. That report can already say a page ranks
    well and is not being clicked, which is consistent with an answer taking
    the click above the result — and had no way to see the clicks an answer
    SENT. Both halves come from data already flowing.
    """
    from . import google_seo, sites
    try:
        profile = sites.get(tenant)
    except Exception as exc:  # noqa: BLE001
        return {"tenant": tenant, "ok": False, "why": str(exc)[:200]}
    raw = google_seo._ga_report(profile, days, ["sessionSource"], limit=200)
    try:
        rows = json.loads(raw)
    except (ValueError, TypeError):
        # A SENTENCE, not rows: no property linked, or Analytics refused.
        return {"tenant": tenant, "ok": False, "why": str(raw)[:220],
                "days": days}
    by_engine: dict[str, int] = {}
    for r in rows if isinstance(rows, list) else []:
        engine = _engine_of(r.get("sessionSource", ""))
        if not engine:
            continue
        try:
            by_engine[engine] = by_engine.get(engine, 0) + int(r.get("sessions") or 0)
        except (TypeError, ValueError):
            continue
    total = sum(by_engine.values())
    return {"tenant": tenant, "ok": True, "days": days, "sessions": total,
            "by_engine": dict(sorted(by_engine.items(), key=lambda kv: -kv[1])),
            "means": ("sessions where somebody followed a link out of an "
                      "answer. Zero is not proof of not being cited — most "
                      "answers are read without a click — but any number "
                      "above zero is proof that we are."
                      if not total else
                      "sessions where somebody followed a link out of an "
                      "answer engine into the site")}


def stored(tenant: str) -> dict:
    """The last check, for a page to render without calling anything."""
    with db.SessionLocal() as s:
        row = (s.query(db.AnswerEngineCheck)
               .filter(db.AnswerEngineCheck.tenant == tenant)
               .order_by(db.AnswerEngineCheck.at.desc()).first())
        if row is None:
            return {}
        got = dict(row.detail or {})
        got["at"] = db.as_utc(row.at).isoformat(timespec="minutes")
        return got


def history(tenant: str, limit: int = 12) -> list[dict]:
    """What the answer was, week by week. "Since when" needs a series."""
    with db.SessionLocal() as s:
        rows = (s.query(db.AnswerEngineCheck)
                .filter(db.AnswerEngineCheck.tenant == tenant)
                .order_by(db.AnswerEngineCheck.at.desc())
                .limit(max(1, limit)).all())
        return [{"at": db.as_utc(r.at).isoformat(timespec="minutes"),
                 "ok": r.ok, "verdict": r.verdict, "sessions": int(r.sessions or 0)}
                for r in rows]


def check(tenant: str, *, probe: bool = True, days: int = 28) -> dict:
    """Run both halves and keep the result. The button behind the card.

    STORED, because the console's rule is that opening a page calls nothing:
    a live crawl per render would make the tab feel broken and would hammer
    the client's own site every time somebody looked at it.
    """
    acc = access(tenant, probe=probe)
    ref = referrals(tenant, days=days)
    got = {"access": acc, "referrals": ref,
           "at": db.utcnow().isoformat(timespec="minutes")}
    with db.SessionLocal() as s:
        s.add(db.AnswerEngineCheck(
            tenant=tenant,
            ok=("yes" if acc.get("ok") else
                "no" if acc.get("ok") is False else "unknown"),
            verdict=str(acc.get("verdict", ""))[:2000],
            detail=got,
            sessions=int((ref or {}).get("sessions") or 0)))
        s.commit()
    return got


def check_one(tenant: str) -> dict:
    """One account's weekly check, with its gates. The unit the worker shards."""
    from . import systems
    if not systems.find(tenant, "blog"):
        return {"skipped": "no blog system installed"}
    try:
        got = check(tenant)
        return {"verdict": got["access"].get("verdict", ""),
                "sessions": (got["referrals"] or {}).get("sessions", 0)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{exc.__class__.__name__}: {str(exc)[:140]}"}
