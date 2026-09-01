"""A declined plan leaves the system, and a delivered thing is findable.

Owner, 2026-09-01, on the plan queue: *"When I skip an item in the plan, it
should no longer appear in that system… set it as skipped and file it outside
of the plan view. Same for rejected."* And: *"I should have a view for all
blogs that were approved and sent to CMS or emails approved and sent to EMS —
even if they were copied over."*

SKIPPING ALREADY LEFT THE QUEUE — `plans()` filters on stage. What it did not
leave was the BOARD: filing a plan marks its keyword `status="planned"`
(`planner.py`) and nothing ever marked it back, so the in-flight list went on
advertising an article that was never coming. One writer, no reset — the
signature defect of this repo, once more.

DELIVERED IS READ FROM THE DESTINATION, not from the run. `Shipped` lists runs
that reached a terminal stage, which is a fact about the pipeline and says
nothing about where the work went. `Output.destination` and `published_at` are
written by the write-back itself — and because "It's live here" calls the same
`keywords.mark_published` the executor calls, the hand-carried ones appear in
the same list. A view showing only what the executor pushed would miss exactly
the accounts that need it most.

Run: python3 scripts/test_plan_lifecycle.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import admin_ui, db, kb, keywords, systems, tenants  # noqa: E402

KEY = "s3cret"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _live(tenant, key):
    row = systems.find(tenant, key) or systems.create(tenant, key)
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    return systems.find(tenant, key)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    blog = _live("baci", "blog")

    print("— a skipped plan leaves the queue AND the board —")
    systems.open_plan("baci", "blog", ref="blog:baci:kw1",
                      plan={"keyword": "corporate events"},
                      planned_for="2026-09-10")
    keywords.upsert("baci", "corporate events", status="planned")
    ck("the plan is queued", len(systems.plans("baci", "blog")) == 1)
    ck("  and the board says an article is coming",
       "corporate events" in
       [x["phrase"] for x in keywords.board("baci")["in_flight"]])

    plan_id = systems.plans("baci", "blog")[0].id
    systems.skip_plan(plan_id, "not this month")

    ck("skipping empties the queue", not systems.plans("baci", "blog"))
    board = keywords.board("baci")
    ck("  and takes it off the board",
       "corporate events" not in [x["phrase"] for x in board["in_flight"]],
       "filing marked the keyword `planned` and nothing marked it back, so a "
       "declined plan advertised an article that was never coming")
    ck("  released as a CANDIDATE, not retired",
       "corporate events" in [x["phrase"] for x in board["writing_next"]],
       "declining THIS plan is not a judgement about the keyword — 'never "
       "propose it again' is `owner_priority=muted`, a different sentence")
    ck("  and it is gone from the Plan queue surface",
       "corporate events" not in
       admin_ui._planned_section(KEY, blog, 1))

    print("\n— but it is kept, with the reason —")
    card = admin_ui._declined_section(KEY, blog)
    ck("Declined lists it", "corporate events" in card)
    ck("  with the reason recorded", "not this month" in card,
       "a decision recorded nowhere is one that gets made again")
    ck("  and Declined is a rail on the system",
       "declined" in [v for v, _l in admin_ui._workflow_subs(blog)],
       str([v for v, _l in admin_ui._workflow_subs(blog)]))

    print("\n— delivered: what reached a destination, however it got there —")
    from app import ledger
    pushed = ledger.record("baci", "campaign_email", format="campaign_email",
                           status="sent", body="Your table, ready for August",
                           destination="esp:omnisend:campaign/c-991")
    by_hand = ledger.record("baci", "blog", format="cms_article", status="sent",
                            body="<p>Corporate events in Miami</p>")
    with db.SessionLocal() as s:
        r = s.get(db.Output, by_hand.id)
        r.destination = "https://mi.example/blog/corporate-events"
        r.published_at = db.utcnow()
        s.commit()
    drafted = ledger.record("baci", "blog", format="cms_article",
                            status="draft", body="<p>Not published yet</p>")

    blog_card = admin_ui._delivered_section(KEY, blog)
    ck("a HAND-CARRIED article is listed",
       "corporate-events" in blog_card,
       "'It's live here' calls the same `mark_published` the executor calls, "
       "so one writer means one list")
    ck("  shown as a live page you can open", "live page" in blog_card)
    ck("  and a draft that never went is NOT listed",
       "Not published yet" not in blog_card,
       str(drafted.id)[:8])

    camp = admin_ui._delivered_section(KEY, _live("baci", "campaign_email"))
    ck("a campaign in the ESP is listed", "c-991" in camp)
    ck("  naming the platform it is in", "omnisend" in camp)

    print("\n— an INTENTION is not a delivery —")
    ck("`esp:omnisend` with no campaign id does not count",
       not admin_ui._landed("esp:omnisend"),
       "`destination` is also written at emit with an intention; a non-empty "
       "value is not delivery")
    ck("  a campaign id does", admin_ui._landed("esp:omnisend:campaign/x"))
    ck("  and so does a URL", admin_ui._landed("https://x/y"))

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
