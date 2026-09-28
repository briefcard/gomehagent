"""A topic the plan does not already cover is planned into every channel from
one form, on the keyword the SEO map is already building.

Owner, 2026-09-27: "if a client wants me to write about EV Week or Art Basel
or any event that is happening or holiday that is relevant that we're not
already writing about, I should be able to plug that in and have both
blogs, emails, ads, etc. generated separately or collectively, to reinforce
this piece of content, while leveraging the correct keywords from the SEO
plan, and do so easily."

`topics.plan` files an ordinary plan on each chosen system — the topic in the
field that system already reads — and the Plan tab's card is the form.
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 't.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui as ui, db, kb, systems, tenants, topics, web  # noqa: E402

_fail: list = []
T = "baci"


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def plans(key: str) -> list:
    return [r for r in systems.plans(T, key) if str(r.ref or "").startswith("topic:")]


def fields(key: str) -> dict:
    rows = plans(key)
    return ((rows[-1].brief or {}).get("plan") or {}) if rows else {}


def main() -> int:
    db.init_db()
    tenants.seed()
    ids = [(systems.find(T, k) or systems.create(T, k)).id for k in topics.CHANNELS]
    with db.SessionLocal() as s:
        for i in ids:
            s.get(db.System, i).status = "live"
        s.add(db.KeywordTarget(tenant=T, phrase="italian dinnerware", tier="head",
                               status="candidate", priority=50, cluster_key="dinnerware"))
        s.add(db.KeywordTarget(tenant=T, phrase="holiday table setting", tier="body",
                               status="candidate", priority=90, cluster_key="entertaining"))
        s.commit()
    kb.add_audience(T, "hosts", "Hosts who entertain", ["dull tables"], ["a table worth a photo"])
    kb.add_entity(T, "product", "portofino", "Portofino dinner set")

    print("— the keyword comes from the map the site is already building —")
    got = topics.keyword_for(T, "Holiday entertaining — a table set for guests")
    ck("the map's closest keyword, with its cluster",
       got.get("phrase") == "holiday table setting" and got.get("cluster") == "entertaining", str(got))
    ck("a topic the map has never met says so — nothing is borrowed",
       topics.keyword_for(T, "EV Week") == {})

    print("\n— one form, every channel, the topic in the field each system reads —")
    out = topics.plan(T, topic="Holiday entertaining", angle="a table set for guests",
                      starts="2026-12-18", ends="2026-12-24", channels=list(topics.CHANNELS),
                      entity_key="portofino", audience_key="hosts", segment="new_subscribers",
                      on="2026-12-01")
    by = {c["key"]: c for c in out["channels"]}
    ck("the article, the email and the ads are planned, complete", out["ok"]
       and all(by[k]["complete"] and not by[k]["error"] for k in ("blog", "campaign_email", "ad_creative")),
       str(out["channels"]))
    ck("  and the Business Profile post waits for the article it is made from — named, never invented",
       not by["gbp_post"]["complete"] and "approve the topic's article" in " ".join(by["gbp_post"]["missing"]),
       str(by["gbp_post"]))
    b = fields("blog")
    ck("the article supports the cluster, on the map's keyword, at the topic's angle",
       b.get("keyword") == "holiday table setting" and b.get("cluster") == "entertaining"
       and b.get("role") == "support" and "Holiday entertaining" in b.get("angle", ""), str(b))
    ck("  written for the reader the card named — not for everybody", b.get("audience_key") == "hosts", str(b))
    e = fields("campaign_email")
    ck("the email carries the topic as its goal, and its real end as its deadline",
       "Holiday entertaining" in e.get("goal", "") and "2026-12-24" in e.get("deadline", "")
       and e.get("segment") == "new_subscribers" and e.get("audience_key") == "hosts", str(e))
    a = fields("ad_creative")
    ck("the ads carry it as their angle", "Holiday entertaining" in a.get("positioning", ""), str(a))
    ck("  and the topic's dates travel with it", "2026-12-18 to 2026-12-24" in a.get("positioning", "")
       and "2026-12-18 to 2026-12-24" in b.get("angle", ""), a.get("positioning", ""))
    g = fields("gbp_post")
    ck("the Business Profile post is an event, on its dates",
       g.get("kind") == "event" and g.get("event_title") == "Holiday entertaining"
       and g.get("event_start") == "2026-12-18" and g.get("event_end") == "2026-12-24", str(g))
    ck("each is due on the day asked", all(str((r.brief or {}).get("planned_for") or "")[:10] == "2026-12-01"
                                          for k in topics.CHANNELS for r in plans(k)))

    before = {k: len(plans(k)) for k in topics.CHANNELS}
    topics.plan(T, topic="Holiday entertaining", angle="a table set for guests",
                channels=list(topics.CHANNELS), entity_key="portofino", audience_key="hosts",
                segment="new_subscribers", on="2026-12-01")
    ck("planning the same topic again updates it — nothing twice",
       {k: len(plans(k)) for k in topics.CHANNELS} == before)

    print("\n— what a channel still needs is named, not invented —")
    out = topics.plan(T, topic="EV Week", channels=["blog", "campaign_email"], on="2026-11-02")
    by = {c["key"]: c for c in out["channels"]}
    ck("a topic new to the map is written for its own name", out["keyword"] == "ev week"
       and out["from_map"] is False)
    ck("the email waits for who it is for and which list, and says so",
       not by["campaign_email"]["complete"] and by["campaign_email"]["missing"], str(by["campaign_email"]))
    ck("  while the article is complete", by["blog"]["complete"])

    print("\n— run now: approved and on the queue in one act —")
    out = topics.plan(T, topic="Art Basel Miami Beach", angle="hosting guests during the fair",
                      starts="2026-12-04", ends="2026-12-07", channels=["blog", "ad_creative"],
                      entity_key="portofino", audience_key="hosts", run_now=True)
    ck("each complete plan is queued", all(c["queued"] for c in out["channels"]), str(out["channels"]))
    with db.SessionLocal() as s:
        queued = {(j.payload or {}).get("run_id") for j in s.query(db.JobQueue).all()}
        approved = [bool(((s.get(db.SystemRun, c["run_id"]).brief or {}).get("plan_approved_at")))
                    for c in out["channels"]]
    ck("  with its plan approved — the rung's question answered by the press",
       all(approved) and {c["run_id"] for c in out["channels"]} <= queued)

    print("\n— with no date given, each channel is staggered before the start —")
    topics.plan(T, topic="Wine Week", starts="2027-03-22", channels=list(topics.CHANNELS),
                entity_key="portofino", audience_key="hosts", segment="new_subscribers")
    due = {k: str(((r := [x for x in plans(k) if x.ref.startswith("topic:wine-week")][0]).brief or {})
                  .get("planned_for")) for k in topics.CHANNELS}
    ck("the article three weeks out, the ads ten days, the email and the post a week",
       due == {"blog": "2027-03-01", "ad_creative": "2027-03-12",
               "campaign_email": "2027-03-15", "gbp_post": "2027-03-15"}, str(due))
    ck("  and never before today", topics._due("blog", "2020-01-01") == systems._today())

    print("\n— the pieces reinforce the article: made from it, pointing at it —")
    blog_run = [x for x in plans("blog") if x.ref == "topic:wine-week:blog"][0].id
    with db.SessionLocal() as s:
        art = db.Output(tenant=T, system_key="blog", run_id=blog_run, format="cms_article")
        s.add(art)
        s.get(db.SystemRun, blog_run).decision = "approved"   # as approving records it first
        s.commit()
        art_id = art.id
    topics.article_approved(art_id)
    g = [x for x in plans("gbp_post") if x.ref == "topic:wine-week:gbp_post"][0]
    ck("the article approved, the post is made from it — and complete",
       (g.brief or {}).get("plan", {}).get("source") == art_id
       and systems.plan_complete(g, "gbp_post")["complete"], str((g.brief or {}).get("plan")))
    url = "https://www.bacimilanousa.com/blogs/news/wine-week-table"
    from app import keywords
    keywords.mark_published(T, art_id, url=url)
    e = [x for x in plans("campaign_email") if x.ref == "topic:wine-week:campaign_email"][0]
    g = [x for x in plans("gbp_post") if x.ref == "topic:wine-week:gbp_post"][0]
    ck("the article live, the email's button and the post's point at it",
       (e.brief or {}).get("plan", {}).get("link") == url
       and (g.brief or {}).get("plan", {}).get("url") == url,
       str(((e.brief or {}).get("plan", {}).get("link"), (g.brief or {}).get("plan", {}).get("url"))))
    from app import recreate, skill
    ck("  and the email's maker is told the button's address, verbatim",
       "link" in skill.get("campaign_email").params
       and f"the main button goes to (use verbatim): {url}" in recreate._message_text({"link": url}))

    print("\n— the Plan tab carries the form, and the form comes back with a line per channel —")
    page = ui.render_plan("s3cret", T)
    ck("the card is on the Plan tab with a box per channel",
       'action="/admin/topic_plan"' in page and all(f'value="{k}"' in page for k in topics.CHANNELS))
    c = TestClient(web.app)
    c.cookies.set("console", web._console_token())
    r = c.post("/admin/topic_plan", data={"tenant": T, "topic": "Miami Spice", "channels": ["blog"],
                                           "on": "2026-08-01"}, follow_redirects=False)
    ck("the press comes back to the Plan tab, saying what it filed",
       r.status_code == 303 and "/plan" in r.headers.get("location", "")
       and "Blog" in r.headers.get("location", ""), r.headers.get("location", "")[:160])

    print()
    print("ALL GREEN" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
