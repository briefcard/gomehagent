"""The Business Profile post: made FROM something, planned, held, published.

Owner, 2026-09-04: "a post generator which can either take existing blogs,
emails or ads and convert them to be SEO optimized GMB posts or generate a
new one from scratch to address company objections or reinforce company
claims" — and "if posts are now part of the Plan then it needs to be clear
that they need to set up a plan."

Everything below runs OFFLINE: the drafter is a fake that remembers what it
was briefed with (the claim is "the source reached the drafter", not "the
function was called"), and Google's one write is stubbed at the adapter.

Run: python3 scripts/test_gbp_post.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'gp.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KEY = "s3cret"
T = "ironside"

from app import (approvals, db, gbp, gbp_post as gp, kb, kb_seed,  # noqa: E402
                 planner, skill, skill_pack, systems, tenants)

_fail: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class FakeDrafter:
    """Stands in for `draft_gbp_post` and REMEMBERS the brief."""

    def __init__(self):
        self.briefs: list[list[str]] = []
        self.reply = ""
        self.fail = False

    def __call__(self, bundle, parts):
        self.briefs.append(list(parts))
        if self.fail:
            return "", "ANTHROPIC_API_KEY is not set"
        return self.reply, ""


def contract(row, autonomy="approve_all"):
    first = systems.update(row.id, **{f: "declared for the test"
                                      for f, _l, _h in systems.CONTRACT})
    assert first.get("ok"), f"contract fill refused: {first}"
    second = systems.update(row.id, status="live", autonomy=autonomy)
    assert second.get("ok"), f"go-live refused: {second}"
    return systems.get(row.id)


def pending(run_id: str):
    with db.SessionLocal() as s:
        aps = (s.query(db.Approval)
               .filter(db.Approval.run_id == run_id,
                       db.Approval.status == "pending").all())
        out = [(a.id, dict(a.payload or {})) for a in aps]
    return out


def artifact(output_id: str):
    with db.SessionLocal() as s:
        a = (s.query(db.ArtifactBody)
             .filter(db.ArtifactBody.output_id == output_id).first())
        o = s.get(db.Output, output_id)
        s.expunge_all()
    return a, o


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    _real_caps = tenants.capabilities
    tenants.capabilities = lambda k: {**_real_caps(k), "gbp": True}
    kb.ensure_brand(T, "Ironside")
    kb.set_brand(T, positioning="A campus of event venues in Little River, Miami.",
                 tone="direct, warm")
    kb.add_banned(T, "best in town")
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, T)
        t.gbp = {"account": "accounts/1", "location": "locations/9",
                 "category": "event venue", "locality": "Miami"}
        t.domain = "ironsidemiami.com"
        s.commit()
    for c, ev in (("Six venues on one campus, from 60 to 400 guests.", "site plan"),
                  ("On-site parking for 200 cars.", "lease")):
        kb.add_claim(T, c, ev, [], origin="human", status="active")
    claims = kb.claims(T)
    c1 = next(c for c in claims if "Six venues" in c.claim)
    c2 = next(c for c in claims if "parking for 200" in c.claim)
    kb.add_objection(T, "Is there parking?",
                     "Yes — on-site parking for 200 cars, free for guests.",
                     origin="human")
    objection = next(o for o in kb.objections(T, any_entity=True)
                     if "parking" in o.objection.lower())
    row = systems.find(T, "gbp_post") or systems.create(T, "gbp_post")
    contract(row)

    # An APPROVED article to convert — published, with its claims.
    with db.SessionLocal() as s:
        out = db.Output(tenant=T, system_key="blog", format="cms_article",
                        body="<p>Corporate events at Ironside: six venues on "
                             "one campus, from 60 to 400 guests, with on-site "
                             "parking for 200 cars.</p>",
                        claim_ids=[c1.id], status="published")
        s.add(out)
        s.flush()
        s.add(db.ArtifactBody(tenant=T, output_id=out.id, run_id="",
                              system_key="blog", format="cms_article",
                              body=out.body, draft_body=out.body,
                              meta={"title": "Corporate events at Ironside"}))
        s.commit()
        article_id = out.id
    ck("an approved article is an eligible source, named by its title",
       any(x["id"] == article_id and "Corporate events" in x["label"]
           for x in systems.approved_sources(T)),
       str(systems.approved_sources(T))[:120])

    fake = FakeDrafter()
    skill_pack.draft_gbp_post = fake
    fake.reply = ("TITLE: \n---\n"
                  "Looking for an event venue in Miami with room for your "
                  "whole team? Ironside is six venues on one campus in Little "
                  "River, from a 60-seat lounge to a 400-guest hall, with "
                  "on-site parking for 200 cars so nobody circles the block. "
                  "Bring the offsite, the launch or the holiday party here and "
                  "let the campus do the work. Learn more below.")

    print("— 1. nothing to make it from is a named refusal, pointing at the plan —")
    r = skill.run("gbp_post", T)
    ck("a run with no source refuses by name and says where a plan is made",
       "made FROM" in str(r.get("summary", ""))
       and any("Plan one by hand" in n for n in r.get("notes", [])),
       f"{r.get('summary')} | {[n[:60] for n in r.get('notes', [])][:2]}")

    print("\n— 2. DERIVED: an approved article becomes a post —")
    r = skill.run("gbp_post", T, source=article_id)
    ck("the run produces", r["status"] == "produced" and len(r["items"]) == 1,
       f"{r['status']} {r.get('summary')}")
    brief = "\n".join(fake.briefs[-1])
    ck("the article's text reached the drafter as the thing to shorten, "
       "with the rule to add nothing",
       "MADE FROM this approved cms_article" in brief
       and "six venues" in brief.lower() and "Add nothing" in brief)
    ck("the local keyword — category in locality — opens the brief",
       "event venue in Miami" in brief)
    post_id = r["items"][0]["output_id"]
    art, out = artifact(post_id)
    meta = dict(art.meta or {})
    ck("the post is filed as its own format, joined to its source",
       art.format == "gbp_post" and meta.get("derived_from") == article_id
       and meta.get("source_kind") == "cms_article", str(meta)[:120])
    ck("it inherits the source's claims — grounding is not re-invented",
       list(out.claim_ids or []) == [c1.id])
    body = meta.get("google_body") or {}
    ck("Google's body is built once: STANDARD, Learn more → the website",
       body.get("topicType") == "STANDARD"
       and body.get("callToAction", {}).get("actionType") == "LEARN_MORE"
       and body.get("callToAction", {}).get("url") == "https://ironsidemiami.com"
       and body.get("summary", "").startswith("Looking for an event venue"),
       str(body)[:140])
    aps = pending(r.get("run_id") or "")
    ck("one approval waits, carrying account, location and the exact body",
       len(aps) == 1 and aps[0][1].get("gbp_post", {}).get("account") == "accounts/1"
       and aps[0][1]["gbp_post"].get("location") == "locations/9"
       and aps[0][1]["gbp_post"].get("body") == body,
       str(aps)[:120])

    print("\n— 3. approving PUBLISHES — the one write to Google —")
    from fastapi.testclient import TestClient
    from app import web
    c = TestClient(web.app, raise_server_exceptions=False)
    calls: list = []
    real_create = gbp.create_post
    # Google refuses the first time (the project is not approved yet, say):
    # the decision stands, nothing is on the profile, and the fix is named.
    gbp.create_post = lambda t, a, n, b: (
        calls.append((t, a, n, b)) or {"ok": False,
                                       "error": gp and gbp.named_refusal(429, "Quota exceeded")})
    said = approvals.apply_decision(aps[0][0], "approved")
    ck("a refusal from Google leaves nothing on the profile and names the fix",
       len(calls) == 1 and said.startswith("Approved — but Google refused")
       and "Nothing is on the profile" in said and gbp.ACCESS_FORM in said,
       said[:120])
    _, out = artifact(post_id)
    ck("…and the post records no destination yet", not (out.destination or ""))
    # The retry, from the workroom's button — the one control for this state.
    gbp.create_post = lambda t, a, n, b: (
        calls.append((t, a, n, b)) or {"ok": True, "state": "LIVE",
                                       "name": "accounts/1/locations/9/localPosts/p1"})
    r3 = c.get(f"/admin/gbp_publish?key={KEY}&output_id={post_id}",
               follow_redirects=False)
    ck("pressing 'Publish to the profile now' publishes exactly once, to the "
       "declared profile, with the body the preview showed",
       len(calls) == 2 and calls[1][1:3] == ("accounts/1", "locations/9")
       and calls[1][3] == body and r3.status_code == 303
       and "ok=Approved" in (r3.headers.get("location") or ""),
       f"{len(calls)} call(s); {r3.headers.get('location', '')[:100]}")
    _, out = artifact(post_id)
    ck("the post records where it went",
       (out.destination or "").startswith("gbp:") and out.status == "published",
       f"{out.destination} {out.status}")

    print("\n— 4. NATIVE: from an objection, and from a claim —")
    fake.reply = ("TITLE: \n---\n"
                  "Parking at an event venue in Miami should never be the "
                  "hard part. At Ironside there is on-site parking for 200 "
                  "cars, free for your guests, so the evening starts at the "
                  "door and not three blocks away. Six venues on one campus, "
                  "from 60 to 400 guests. Learn more below.")
    r = skill.run("gbp_post", T, objection_id=objection.id)
    brief = "\n".join(fake.briefs[-1])
    ck("an objection post is briefed with the hesitation AND the approved "
       "answer as the only material",
       r["status"] == "produced" and "Is there parking?" in brief
       and "free for guests" in brief and "ONLY thing you may build on" in brief,
       f"{r['status']} {r.get('summary')}")
    objection_post_id = r["items"][0]["output_id"]
    art, out = artifact(objection_post_id)
    ck("…filed as made from that objection",
       (art.meta or {}).get("objection_id") == objection.id)
    # A claim post CITES its claim, so the validator holds it to that claim
    # — the reply asserts only what the claim says.
    # The claim nothing has cited yet — the ledger refuses the same proof
    # to the same entity inside its window, and the article post already
    # inherited the first claim. The planner counts that as used, below.
    fake.reply = ("TITLE: \n---\n"
                  "Parking at an event venue in Miami is usually the first "
                  "thing a planner asks about. Ironside has on-site parking "
                  "for 200 cars, so your guests park where the evening "
                  "happens and nobody walks three blocks in the heat. Bring "
                  "the whole team and leave the logistics to the campus. "
                  "Book below.")
    r = skill.run("gbp_post", T, claim_id=c2.id, cta="book")
    brief = "\n".join(fake.briefs[-1])
    ck("a claim post is briefed with that one claim and its evidence",
       r["status"] == "produced" and "parking for 200 cars" in brief
       and "lease" in brief,
       f"{r['status']} {[n[:80] for n in r.get('notes', [])][-3:]}")
    art, out = artifact(r["items"][0]["output_id"])
    ck("…cites exactly that claim, and carries the chosen button",
       art is not None and list(out.claim_ids or []) == [c2.id]
       and (art.meta or {}).get("google_body", {}).get("callToAction", {})
       .get("actionType") == "BOOK",
       f"{[n[:80] for n in r.get('notes', [])][-2:]}")
    ck("an objection post cites no claim — its grounding is the approved "
       "answer, and it spends nothing against the repetition window",
       list(artifact(objection_post_id)[1].claim_ids or []) == [])

    print("\n— 5. the rules a post is held to —")
    rules = lambda body, **kw: {f["rule"] for f in gp.review(body, **kw)}  # noqa: E731
    long = "word " * 400
    ck("over 1,500 characters is refused",
       "too_long" in rules(long, keyword="event venue in Miami"))
    ck("the local keyword missing from the first sentence is refused",
       "local_keyword_not_in_the_snippet" in rules(
           "Come and see us. " * 8 + "We are an event venue in Miami.",
           keyword="event venue in Miami"))
    ck("…and present in it passes",
       "local_keyword_not_in_the_snippet" not in rules(
           "Miami's event venue for teams of sixty to four hundred. " * 3,
           keyword="event venue in Miami"))
    ck("a phone number, a link and a hashtag are each refused",
       {"phone_number_in_the_body", "url_in_the_body", "hashtags"} <= rules(
           "Event venue in Miami. Call 305-555-0100 or see ironside.com now "
           "#miamievents " + "and more words here. " * 8,
           keyword="event venue in Miami"))
    ck("an offer without terms and an event without dates are refused",
       "offer_without_terms" in rules("Event venue in Miami. " * 10, keyword="event venue in Miami", kind="offer")
       and "event_without_dates" in rules("Event venue in Miami. " * 10, keyword="event venue in Miami", kind="event"))
    ck("urgency needs a real deadline — the rule email is held to",
       "urgency_without_a_deadline" in rules(
           "Event venue in Miami — only a few dates left, hurry. " * 4,
           keyword="event venue in Miami")
       and "urgency_without_a_deadline" not in rules(
           "Event venue in Miami — only a few dates left, hurry. " * 4,
           keyword="event venue in Miami", urgency_backed_by="2026-10-01"))
    off = gp.payload("Half off the lounge this month.", kind="offer", cta="SHOP",
                     url="https://x.com", title="Half off", offer_terms="Weekdays only",
                     event_start="2026-09-10", event_end="2026-09-30")
    ck("an offer's body carries Google's event (title, schedule) AND the terms",
       off["topicType"] == "OFFER" and off["event"]["title"] == "Half off"
       and off["event"]["schedule"]["startDate"] == {"year": 2026, "month": 9, "day": 10}
       and off["offer"]["termsConditions"] == "Weekdays only")
    ck("CALL takes no URL — the listing's number is the button",
       gp.payload("x", kind="update", cta="CALL", url="https://x.com")["callToAction"]
       == {"actionType": "CALL"})

    print("\n— 6. the plan: one of three sources, each a reference —")
    ck("a plan naming none of source / objection / claim is not complete, "
       "and says so", not systems.plan_complete(
           {"plan": {}, "planned_for": "2026-09-10"}, "gbp_post")["complete"]
       and "one of:" in systems.plan_complete(
           {"plan": {}, "planned_for": "2026-09-10"}, "gbp_post")["missing"][0])
    ck("…and one naming a source is",
       systems.plan_complete({"plan": {"source": article_id},
                              "planned_for": "2026-09-10"}, "gbp_post")["complete"])
    o = systems.open_plan(T, "gbp_post", ref="test:1")
    ck("a ghost source is refused by name",
       "unknown source" in (systems.save_plan(o["run_id"], {"source": "ghost"}).get("error") or ""))
    ck("a ghost objection is refused by name",
       "unknown objection" in (systems.save_plan(o["run_id"], {"objection_id": "ghost"}).get("error") or ""))
    ck("a ghost claim is refused by name",
       "unknown claim" in (systems.save_plan(o["run_id"], {"claim_id": "ghost"}).get("error") or ""))
    ck("a real source saves",
       systems.save_plan(o["run_id"], {"source": article_id}).get("ok") is True)

    print("\n— 7. the planner: one a week, derived and native alternating —")
    with db.SessionLocal() as s:
        for p in s.query(db.SystemRun).filter(db.SystemRun.ref == "test:1").all():
            s.delete(p)
        s.commit()
    # A second approved artifact, so a derived week has something left after
    # the article above was already posted in step 2.
    # TWO unposted derived sources, so alternation is OBSERVABLE: with one,
    # the second week would fall to native anyway and a planner that only
    # ever converts would pass this check.
    with db.SessionLocal() as s:
        o2 = db.Output(tenant=T, system_key="campaign_email", format="campaign_email",
                       body="Six venues, one campus, your holiday party sorted.",
                       claim_ids=[c1.id], status="approved")
        o3 = db.Output(tenant=T, system_key="ad_creative", format="ad_copy",
                       body="Parking for 200 cars. The rest is the party.",
                       claim_ids=[c2.id], status="approved")
        s.add(o2)
        s.add(o3)
        s.commit()
        email_id, ad_id = o2.id, o3.id
    sysrow = systems.get(row.id)
    got = planner.gbp_post_rollout(sysrow)
    plans = systems.plans(T, "gbp_post")
    kinds = [("source" if (p.brief or {}).get("plan", {}).get("source")
              else "objection" if (p.brief or {}).get("plan", {}).get("objection_id")
              else "claim" if (p.brief or {}).get("plan", {}).get("claim_id")
              else "none") for p in plans]
    ck("three weeks of horizon file up to three plans, none blank",
       got["proposed"] >= 2 and "none" not in kinds and len(plans) == got["proposed"],
       f"{got} kinds={kinds}")
    ck("the first is made from the NEWEST unposted artifact — the ad, filed "
       "last; the article was already posted",
       (plans[0].brief or {}).get("plan", {}).get("source") == ad_id,
       str((plans[0].brief or {}).get("plan")))
    ck("…and the third takes the next one — the email",
       len(plans) > 2 and (plans[2].brief or {}).get("plan", {}).get("source") == email_id,
       str([(p.brief or {}).get("plan", {}).get("source", "")[:8] for p in plans]))
    ck("the second is native — an objection or a claim not yet posted — and "
       "the third converts again: derived and native ALTERNATE",
       kinds[1] in ("objection", "claim") and (len(kinds) < 3 or kinds[2] == "source"),
       str(kinds))
    again = planner.gbp_post_rollout(systems.get(row.id))
    ck("a second pass refreshes and doubles nothing",
       again["proposed"] == 0 and len(systems.plans(T, "gbp_post")) == len(plans),
       str(again))
    ck("the cadence knob the planner reads is the one the form offers",
       any(k["key"] == "posts_weekly" for k in planner.knobs_for(systems.get(row.id))))

    print("\n— 8. the page says how it is used, and the pickers are selects —")
    page = c.get(f"/admin/ui?key={KEY}&tab=systems&tenant={T}&system=gbp_post&wf=planned").text
    ck("the system page says posts are planned work and how a plan is made",
       "Posts are PLANNED work" in page and "Plan one by hand" in page)
    ck("the plan form picks the source, the objection and the claim from "
       "selects — never a typed id",
       '<select name="source">' in page and '<select name="objection_id">' in page
       and '<select name="claim_id">' in page
       and "Corporate events at Ironside" in page and "Is there parking?" in page)
    wr = c.get(f"/admin/work/{post_id}?key={KEY}").text
    ck("the workroom shows the post as Google will, with its length, button "
       "and what it was made from",
       "As Google shows it" in wr and "/ 1500 characters" in wr
       and "made from" in wr and "Corporate events at Ironside" in wr
       and "Published to the profile" in wr)

    print("\n— 9. degraded honestly —")
    fake.fail = True
    r = skill.run("gbp_post", T, objection_id=objection.id)
    art, _ = artifact(r["items"][0]["output_id"]) if r.get("items") else (None, None)
    ck("with no model the post is a composed restatement that says so",
       r["status"] == "produced" and art is not None
       and str((art.meta or {}).get("basis", "")).startswith("composed")
       and "event venue in miami" in (art.body or "").lower(),
       f"{r['status']} {(art.meta or {}).get('basis') if art else ''} "
       f"{[n[:70] for n in r.get('notes', [])][-2:]}")
    fake.fail = False
    gbp.create_post = real_create
    said = approvals.publish_gbp_post(type("A", (), {"payload": {"gbp_post": {
        "tenant": T, "account": "", "location": "", "output_id": "x", "body": {}}},
        "tenant": T})())
    ck("publishing with no declared profile refuses by name, pointing at the "
       "Accounts tab", "declares no Business Profile" in said and "Accounts" in said)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed — a post is made from something, planned, held, "
          "and published on approval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
