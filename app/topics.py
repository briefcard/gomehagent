"""A topic the plan does not already cover — an event, a holiday, a moment a
client asks for — planned into every channel from one form.

Owner, 2026-09-27: "if a client wants me to write about EV Week or Art Basel
or any event that is happening or holiday that is relevant that we're not
already writing about, I should be able to plug that in and have both
blogs, emails, ads, etc. generated separately or collectively, to reinforce
this piece of content, while leveraging the correct keywords from the SEO
plan, and do so easily."

Nothing new runs. Each channel gets an ordinary PLAN on its own system
(`systems.open_plan`), with the topic in the field that system already
reads — the article's angle, the email's goal, the ad's positioning, the
Business Profile post's event — and the keyword taken from the SEO map, so
the article supports a cluster the site is already building. The plans sit
on each system's Planned list like any other: edited there, due on their
date, or run now.
"""
from __future__ import annotations

import re

#: The channels a topic can go to — each a system whose plan carries it.
CHANNELS = {"blog": "Blog article", "campaign_email": "Email",
            "ad_creative": "Ads", "gbp_post": "Google Business post"}

_STOP = {"a", "an", "and", "at", "for", "from", "in", "of", "on", "the", "to",
         "with", "your", "our", "this", "that", "is", "are", "by", "week"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(w) > 1 and w not in _STOP}


def keyword_for(tenant: str, text: str) -> dict:
    """The SEO map's keyword closest to the topic and its angle — the most
    words in common, then the map's own priority — with its cluster, so the
    article is a SUPPORT for a cluster the site is already building.
    `{}` when no keyword in the map shares a word: the topic is new to it."""
    from . import keywords
    want = _words(text)
    best: dict = {}
    rank = (0, 0.0)
    for c in (keywords.map_for(tenant).get("clusters") or []):
        for k in c.get("keywords") or []:
            common = len(want & _words(k.get("phrase")))
            here = (common, float(k.get("priority") or 0))
            if common and here > rank:
                rank = here
                best = {"phrase": k["phrase"], "cluster": c.get("cluster", ""),
                        "pillar": c.get("pillar", "")}
    return best


def plan(tenant: str, *, topic: str, angle: str = "", starts: str = "", ends: str = "",
         channels=(), entity_key: str = "", audience_key: str = "", segment: str = "",
         keyword: str = "", on: str = "", run_now: bool = False) -> dict:
    """File the topic into each chosen channel. `{ok, keyword, from_map,
    channels: [{key, name, run_id, complete, missing, queued, error}]}`.

    `on` is the day the plans come due (blank: today). `run_now` approves
    each complete plan and puts it on the queue — the same one deliberate
    act as a plan's own Approve & run."""
    from . import jobs, systems
    topic = str(topic or "").strip()
    if not topic:
        return {"ok": False, "why": "name the topic — the event, holiday or moment"}
    picked = [c for c in channels if c in CHANNELS]
    if not picked:
        return {"ok": False, "why": "choose at least one channel"}
    found = {} if keyword.strip() else keyword_for(tenant, f"{topic} {angle}")
    phrase = keyword.strip() or found.get("phrase") or topic.lower()
    about = f"{topic} — {angle.strip()}" if angle.strip() else topic
    fields = {
        "blog": {"keyword": phrase, "cluster": found.get("cluster", ""), "role": "support",
                 "angle": about, "entity_key": entity_key},
        "campaign_email": {"segment": segment, "audience_key": audience_key, "goal": about,
                           "entity_key": entity_key,
                           "deadline": f"{topic} ends {ends}" if ends else ""},
        "ad_creative": {"entity_key": entity_key, "audience_key": audience_key,
                        "positioning": about},
        "gbp_post": ({"kind": "event", "event_title": topic, "event_start": starts,
                      "event_end": ends or starts, "keyword": phrase} if starts else
                     {"kind": "update", "keyword": phrase}),
    }
    ref = "topic:" + re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:60]
    out = []
    for key in picked:
        got = systems.open_plan(tenant, key, ref=f"{ref}:{key}",
                                plan={k: v for k, v in fields[key].items() if str(v or "").strip()},
                                planned_for=on or systems._today(), trigger="topic")
        row = {"key": key, "name": CHANNELS[key], "run_id": got.get("run_id", ""),
               "complete": bool(got.get("complete")), "missing": got.get("missing") or [],
               "queued": False, "error": got.get("error", "")}
        # A Business Profile post is made FROM something already approved — it
        # never invents its own claim — so a topic's post waits for the
        # topic's article: approve that, then pick it as the post's source.
        if key == "gbp_post" and row["missing"] and "blog" in picked:
            row["missing"] = ["the article it is made from — approve the topic's article, "
                              "then pick it as “Made from” on this post's plan"]
        if run_now and row["complete"] and not row["error"]:
            ok = systems.approve_plan(row["run_id"])
            if ok.get("error"):
                row["error"] = ok["error"]
            else:
                wf = systems.workflow(key)
                put = jobs.enqueue(tenant, "system_run", system_key=key,
                                   label=f"{CHANNELS[key]} — {topic}",
                                   payload={"key": wf["skill"] or key, "trigger": "manual",
                                            "run_id": row["run_id"]}, dedupe=False)
                row["queued"] = bool(put.get("ok"))
                row["error"] = "" if put.get("ok") else (put.get("why") or "could not queue it")
        out.append(row)
    return {"ok": any(not r["error"] for r in out), "topic": topic, "keyword": phrase,
            "from_map": bool(found) or bool(keyword.strip()), "cluster": found.get("cluster", ""),
            "channels": out}
