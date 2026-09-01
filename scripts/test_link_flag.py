"""An approved article with no address is flagged, and linkable supports go first.

Owner, 2026-09-01: *"I can see issues with it being required — for example
clients who dont have a cms we would need to derive the link unless otherwise
stated and associated. Lets prioritize linked support articles and raise a flag
when an approved article has no link associated yet."*

REQUIRING THE LINK WOULD HAVE BEEN WRONG TWICE. It would block exactly the
accounts that publish by hand — where paste-and-record IS the workflow — and it
would refuse an article for a fact that does not exist yet at drafting time. A
URL is not something the writer withheld; it is something that has no value
until the page does. So: a flag, and a reorder, and no gate anywhere.

THE FLAG EXISTS BECAUSE THE STATE IS SILENT IN THREE DIRECTIONS AT ONCE.
An approved article with no `target_url`:

  · cannot be LINKED to — `_run_blog_article` builds its link pool from
    siblings whose `target_url` resolves, so an unlinked pillar is a cluster
    with no hub and every support written into it ships pointing nowhere;
  · cannot be MEASURED — `attention` and `progress` both read
    published/won, and this row is neither;
  · does not SAY so — it was approved, which reads as done.

Run: python3 scripts/test_link_flag.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'lf.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import admin_ui, db, keywords, planner, systems, tenants  # noqa: E402

KEY = "s3cret"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _article(tenant, phrase, *, role, cluster, status, url="", priority=50,
             kw_status=""):
    """A keyword with a real Output behind it, the way a run leaves them.

    `kw_status` is the KEYWORD row's state and it is not the Output's. An
    article that was approved and never marked live leaves the keyword at
    `planned` — `mark_published` is the only writer of `published` and it is
    the same call that writes `target_url`. Leaving the keyword a `candidate`
    here would have described a state the pipeline cannot produce, and it did:
    the first cut of this fixture passed the reorder assertion by way of the
    pillar-before-support rule instead of the rule under test.
    """
    keywords.upsert(tenant, phrase, role=role, cluster_key=cluster,
                    priority=priority,
                    status=kw_status or ("published" if url else "planned"))
    with db.SessionLocal() as s:
        o = db.Output(tenant=tenant, system_key="blog", format="cms_article",
                      status=status, destination=url or "")
        s.add(o)
        s.commit()
        oid = o.id
        r = (s.query(db.KeywordTarget)
             .filter(db.KeywordTarget.tenant == tenant,
                     db.KeywordTarget.phrase == phrase).first())
        r.output_id = oid
        r.target_url = url
        r.role = role
        r.cluster_key = cluster
        r.priority = priority
        s.commit()
    return oid


def _live(tenant, key):
    row = systems.find(tenant, key) or systems.create(tenant, key)
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    return systems.find(tenant, key)


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— the flag: approved, and nothing knows where it is —")
    _article("baci", "corporate venues", role="pillar", cluster="ce",
             status="approved")
    _article("baci", "venue with parking", role="support", cluster="ce",
             status="approved", url="https://baci.example/parking")
    _article("baci", "still drafting", role="support", cluster="ce",
             status="draft")

    with db.SessionLocal() as s:
        s.get(db.Tenant, "baci").cms = {}
        s.commit()
    got = {r["phrase"]: r for r in keywords.unlinked("baci")}
    ck("an approved article with no address is flagged",
       "corporate venues" in got,
       "it was approved, which reads as done — and it is outside every "
       "measurement lane and cannot be linked to")
    ck("one that HAS an address is not",
       "venue with parking" not in got,
       "the address is the whole condition")
    ck("a draft is not flagged",
       "still drafting" not in got,
       "nothing was decided about it yet — this is a flag about approved "
       "work, not a backlog of unfinished work")
    ck("it counts who is waiting on it",
       got["corporate venues"]["waiting"] == 2,
       f"waiting={got['corporate venues']['waiting']} — a pillar with six "
       f"supports behind it is a different-sized problem from a lone support")

    print()
    print("— the move depends on whether there is a CMS —")
    ck("with no CMS it asks for the address",
       "paste" in got["corporate venues"]["owed"],
       got["corporate venues"]["owed"])
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, "baci")
        t.cms = {"platform": "shopify"}
        s.commit()
    got2 = {r["phrase"]: r for r in keywords.unlinked("baci")}
    ck("with a CMS it says the page was published outside the flow",
       "shopify" in got2["corporate venues"]["owed"],
       got2["corporate venues"]["owed"]
       + " — the create path already captures the address from the backend's "
         "own reply, so a row here means it did not go through that path")
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, "baci")
        t.cms = {}
        s.commit()

    print()
    print("— a pillar leads, because its cluster inherits the problem —")
    _article("baci", "lone question", role="support", cluster="zz",
             status="approved")
    order = [r["phrase"] for r in keywords.unlinked("baci")]
    ck("the unlinked pillar is first",
       order[0] == "corporate venues",
       f"{order} — every support written into that cluster ships pointing "
       f"nowhere until the hub has an address")

    print()
    print("— NOT a gate: the article was still approved —")
    with db.SessionLocal() as s:
        o = s.get(db.Output,
                  [r for r in keywords.targets("baci")
                   if r.phrase == "corporate venues"][0].output_id)
        ck("the flagged article's own status is untouched",
           (o.status or "") == "approved",
           "requiring the address would block the accounts that publish by "
           "hand — exactly the ones this happens to")

    print()
    print("— linkable supports are written first —")
    wm = _live("wm", "blog")
    # Two clusters. One pillar is published WITH an address; the other is
    # approved with none — which reads to the drafter exactly like not
    # existing, because the link pool is built from `target_url` alone.
    _article("wm", "hub with address", role="pillar", cluster="a",
             status="published", url="https://wm.example/a", priority=10)
    _article("wm", "hub with none", role="pillar", cluster="b",
             status="approved", priority=10)
    keywords.upsert("wm", "orphan support", role="support", cluster_key="b",
                    status="candidate", priority=99)
    keywords.upsert("wm", "linkable support", role="support", cluster_key="a",
                    status="candidate", priority=98)

    out = planner.blog_rollout(wm)
    with db.SessionLocal() as s:
        filed = [(r.ref, (r.brief or {}).get("planned_for"))
                 for r in s.query(db.SystemRun)
                 .filter(db.SystemRun.system_id == wm.id).all()
                 if (r.ref or "").startswith("article:")]
    filed.sort(key=lambda x: str(x[1]))
    seq = [f for f, _ in filed]
    ck("the support whose pillar has an address is written first",
       seq.index("article:wm:linkable-support")
       < seq.index("article:wm:orphan-support"),
       f"{seq} — 'orphan support' outranks it on priority (99 vs 98) and "
       f"still goes second, because its pillar is approved with no address "
       f"and that reads to the drafter exactly like not existing")
    print()
    print("— and it does not swallow the rule it sits next to —")
    # THE TWO RULES OVERLAP AND THE OLDER ONE WINS. A support whose pillar is
    # still a CANDIDATE is already handled better: the pillar is promoted ahead
    # of it and the run says so. Demoting here as well reaches the same order
    # by a silent route and costs the sentence — which is the whole point of
    # that sentence. The first cut did exactly that and `test_blog_skill`
    # caught it, so the case is asserted here too, where the rule lives.
    eien = _live("eien", "blog")
    keywords.upsert("eien", "unwritten hub", role="pillar", cluster_key="q",
                    status="candidate", priority=10)
    keywords.upsert("eien", "eager support", role="support", cluster_key="q",
                    status="candidate", priority=99)
    res = planner.blog_rollout(eien)
    ck("a support whose pillar is unwritten still promotes the pillar",
       any("unwritten hub" in m for m in res.get("pillar_first") or []),
       str(res.get("pillar_first"))[:120])
    ck("  and the run SAYS it reordered",
       bool(res.get("pillar_first")),
       "planning something other than the thing that ranked first, without "
       "saying so, is the kind of helpfulness nobody can audit")
    ck("  and the orphan is still planned, not refused",
       any(f.endswith("orphan-support") for f, _ in filed),
       "it is real work; it just does not go first when something else can "
       "land complete — refusing it would punish the account for its CMS")
    ck("the run still reports normally", out.get("ok") is True, str(out)[:90])

    print()
    print("— the flag renders where the board is read —")
    card = admin_ui._board_section(KEY, "baci", 7)
    flat = " ".join(card.split())
    ck("the strip is on the Plan tab", "Not linked yet" in flat)
    ck("it names the article", "corporate venues" in flat)
    ck("and offers the action inline",
       "Add the address" in flat,
       "act where you report — the fix is a click from the flag, not a "
       "different screen")
    clean = admin_ui._board_section(KEY, "eien", 7)
    ck("an account with nothing to flag shows no strip",
       "Not linked yet" not in " ".join(clean.split()),
       "an empty table teaching a lesson nobody needs is noise on every "
       "other account's board")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
