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
        return {"ok": True, "status": r.status_code, "text": r.text,
                "server": r.headers.get("server", "")}
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
    return {"ok": True, "control_status": control["status"],
            "server": control.get("server", ""), "crawlers": out}


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


# ---------------------------------------------------------------------------
# The files. What a site SHOULD serve, generated from what it serves today.
# ---------------------------------------------------------------------------
#
# THE SPECIFICITY TRAP, and the reason a generator is worth having here at all.
# A crawler obeys the MOST SPECIFIC user-agent group that matches it and
# ignores every other, `*` included. So "declaring" a bot with
#
#     User-agent: OAI-SearchBot
#     Allow: /
#
# does not add a permission — it detaches that crawler from the wildcard group
# and hands it /cart, /checkout and /admin, which the wildcard was disallowing.
# Every named group this file writes therefore MIRRORS the wildcard's own
# disallows, and no group is written at all unless it changes something.

def _wildcard_disallows(robots_text: str) -> list[str]:
    """The `Disallow:` lines of the `*` group, to mirror into a named one."""
    out, in_star = [], False
    for raw in (robots_text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("user-agent:"):
            in_star = line.split(":", 1)[1].strip() == "*"
            continue
        if in_star and low.startswith("disallow:"):
            value = line.split(":", 1)[1].strip()
            if value:
                out.append(value)
    return out


def _stance(tenant: str) -> str:
    """allow | block | "" — and "" means nobody has been asked."""
    with db.SessionLocal() as s:
        row = s.get(db.KbBrand, tenant)
        return (getattr(row, "ai_training", "") or "") if row else ""


def robots_plan(tenant: str) -> dict:
    """What this site's robots.txt should say, and whether it already says it.

    CHANGES ONLY WHAT NEEDS CHANGING. The common and correct outcome is
    "nothing": a site whose robots.txt already lets the search crawlers in and
    matches the brand's training stance needs no file, and generating one
    anyway would be churn that carries the specificity trap for no gain.
    """
    from . import sites
    try:
        profile = sites.get(tenant)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "why": str(exc)[:200]}
    domain = profile.get("domain", "")
    got = _fetch(_url(domain) + "/robots.txt", _HUMAN_UA)
    if not got["ok"]:
        return {"ok": False, "why": f"robots.txt is not readable — "
                                    f"{got.get('why', '')}"}
    text = got["text"] if got["status"] == 200 else ""
    pol = robots_policy(domain)
    if not pol.get("ok"):
        return {"ok": False, "why": pol.get("why", "")}
    current = pol["crawlers"]
    stance = _stance(tenant)

    allow, block = [], []
    for token, meta in current.items():
        if meta["role"] == "training":
            # THE OWNER'S CALL, and an unmade one is not a refusal. Undecided
            # leaves the file alone and says so, rather than opting a brand out
            # of being part of what a model knows on nobody's authority.
            if stance == "block" and meta["allowed"]:
                block.append(token)
            elif stance == "allow" and not meta["allowed"]:
                allow.append(token)
        elif not meta["allowed"]:
            allow.append(token)

    mirror = _wildcard_disallows(text)
    plan = {"ok": True, "domain": domain,
            "platform": profile.get("platform", ""),
            "stance": stance or "undecided",
            "allow": sorted(allow), "block": sorted(block),
            "mirrored_disallows": mirror,
            "changes": bool(allow or block)}
    if not plan["changes"]:
        plan["why_not"] = (
            "robots.txt already lets every search crawler in"
            + (f", and matches this brand's choice to {stance} training"
               if stance else
               ". Nobody has said whether this brand wants to be trained on, "
               "and an unmade decision changes nothing here"))
        return plan
    plan["groups"] = _groups(allow, block, mirror)
    plan.update(_rendered(plan))
    return plan


def _groups(allow: list, block: list, mirror: list) -> str:
    """The user-agent groups, each carrying the wildcard's own disallows."""
    out = []
    for token in allow:
        lines = [f"User-agent: {token}"]
        # MIRRORED, NOT "Allow: /". Naming a crawler detaches it from the
        # wildcard group, so without these it would be handed every path the
        # site disallows to everybody else.
        lines += [f"Disallow: {d}" for d in mirror] or ["Allow: /"]
        out.append("\n".join(lines))
    for token in block:
        out.append(f"User-agent: {token}\nDisallow: /")
    return "\n\n".join(out)


#: Shopify renders robots.txt from a Liquid template, and the default rules are
#: maintained by Shopify and updated as their SEO guidance changes. So the
#: generated template REPLAYS the defaults through their own loop and appends
#: ours, rather than freezing today's defaults into a static file that stops
#: tracking theirs. Property names from shopify.dev/themes/seo/robots-txt:
#: `robots.default_groups`, `group.user_agent`, `group.rules`, `group.sitemap`.
_SHOPIFY_TEMPLATE = """{%- comment -%}
  Generated for the answer engines. The loop below is Shopify's own default
  rule set, replayed unchanged so it keeps tracking their updates; the groups
  after it are ours.

  Each named group repeats the wildcard group's Disallow lines on purpose: a
  crawler obeys the most specific group that matches it and ignores '*', so a
  bare 'Allow: /' here would hand that crawler /cart, /checkout and /admin.
{%- endcomment -%}
{% for group in robots.default_groups %}
  {{- group.user_agent }}
  {%- for rule in group.rules -%}
    {{ rule }}
  {%- endfor -%}
  {%- if group.sitemap != blank -%}
    {{ group.sitemap }}
  {%- endif -%}
{% endfor %}

{GROUPS}
"""


def _rendered(plan: dict) -> dict:
    """The file itself, in the form the platform actually serves."""
    if plan["platform"] == "shopify":
        return {"filename": "templates/robots.txt.liquid",
                "content": _SHOPIFY_TEMPLATE.replace("{GROUPS}", plan["groups"]),
                "installable": True,
                "how": ("installs into the published theme as "
                        "templates/robots.txt.liquid, on your approval")}
    return {"filename": "robots.txt",
            "content": plan["groups"] + "\n",
            "installable": False,
            "how": ("this platform has no write path for robots.txt from here "
                    "— add these groups to the file the site already serves, "
                    "keeping everything that is in it")}


def llms_txt(tenant: str) -> dict:
    """An index of what this site is for, in the format llmstxt.org describes.

    H1, then a blockquote summary, then H2 sections of markdown links — the
    order the specification gives. Built only from pages that are actually
    PUBLISHED with a real URL, because an index that lists a page an engine
    cannot fetch is worse than no index.
    """
    from . import kb, keywords as kw, sites
    try:
        profile = sites.get(tenant)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "why": str(exc)[:200]}
    brand = kb.get_brand(tenant) if hasattr(kb, "get_brand") else None
    with db.SessionLocal() as s:
        row = s.get(db.KbBrand, tenant)
        name = (getattr(row, "name", "") if row else "") or tenant.title()
        summary = (getattr(row, "positioning", "") if row else "") or ""
    live = [r for r in kw.targets(tenant)
            if r.status in ("published", "won") and (r.target_url or "").strip()]
    if not live:
        return {"ok": False, "filename": "llms.txt",
                "why": ("nothing is published with a live URL yet, so an "
                        "llms.txt would be an index of nothing")}
    pillars = [r for r in live if r.role == "pillar"]
    supports = [r for r in live if r.role != "pillar"]

    def _list(rows):
        return "\n".join(f"- [{(r.phrase or '').strip()}]({r.target_url.strip()})"
                          for r in rows)
    parts = [f"# {name}", ""]
    if summary:
        parts += [f"> {summary.strip()}", ""]
    if pillars:
        parts += ["## Main topics", "", _list(pillars), ""]
    if supports:
        parts += ["## Optional", "", _list(supports), ""]
    return {"ok": True, "filename": "llms.txt", "content": "\n".join(parts),
            "pages": len(live), "installable": False,
            "how": ("serve this at /llms.txt. No platform here has a write "
                    "path for it, so it is a file to upload")}


def files_for(tenant: str, *, fresh: bool = False) -> dict:
    """Everything this account should serve, and who can install each one.

    READS THE STORED CHECK unless asked for `fresh`. The plan is computed from
    the site's LIVE robots.txt, so computing it on every page render would put
    the console back to crawling the client on each look — the thing the stored
    reading exists to stop. The weekly job and the Check button recompute it;
    installing recomputes too, because a file is written against what is true
    now rather than what was true on Sunday.
    """
    got = stored(tenant)
    cdn = ((got.get("access") or {}).get("edge") or {}).get("server", "")
    if fresh:
        out = {"tenant": tenant, "robots": robots_plan(tenant),
               "llms_txt": llms_txt(tenant)}
    else:
        kept = got.get("files") or {}
        out = {"tenant": tenant,
               "robots": kept.get("robots") or {
                   "ok": False, "why": "not checked yet — press Check above"},
               "llms_txt": kept.get("llms_txt") or {
                   "ok": False, "why": "not checked yet"}}
    if "cloudflare" in str(cdn).lower():
        # THE ONE WE CANNOT DO FOR THEM, named only when it is actually in the
        # path. A CDN can refuse a crawler that robots.txt welcomes, and no
        # file served from the origin changes that.
        out["cdn_note"] = (
            "This site is behind Cloudflare, which can refuse a crawler before "
            "the origin sees it and cannot be changed by any file here. Check "
            "Cloudflare → AI Crawl Control (all plans) for which AI services "
            "reached the site, and the bot rules for anything blocking them.")
    return out


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
    # THE PLAN RIDES WITH THE READING. Both come from the same live robots.txt,
    # and computing them together is what lets the card render from a stored
    # row without calling anything.
    got = {"access": acc, "referrals": ref,
           "files": {"robots": robots_plan(tenant), "llms_txt": llms_txt(tenant)},
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
