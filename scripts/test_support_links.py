"""The band that says "supports, linking up" can now do both halves.

Phase 3. `_owed_for` tells a page at 11-30 that it needs "supports in its
cluster, linking up" — and that sentence was the end of the line in BOTH
directions:

  · Nothing said WHICH supports, or whether any were left to write. A surface
    could render the recommendation and offer nothing, which is a fix
    instruction where a control belongs.
  · Nothing checked the linking ever happened. The drafter is TOLD a support
    "links back to the pillar", and `_link_grounding` verifies that the links
    present RESOLVE — it never verifies a required link is THERE. So a support
    could ship with zero links up and pass every gate, and the mechanism the
    whole pillar/cluster model rests on was advice.

A FLAG, NEVER A GATE, on the second one. Owner, 2026-09-01, on requiring a
link: *"I can see issues with it being required — for example clients who dont
have a cms."* The reason generalises past the CMS: at drafting time the pillar
may not be published yet, so the link CANNOT exist, and refusing the article
would punish it for the order the work was done in.

Run: python3 scripts/test_support_links.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui, db, kb, keywords, links, systems, tenants, web  # noqa: E402

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


def _page(tenant, phrase, *, role, cluster, status, url="", body=None,
          pos=None):
    keywords.upsert(tenant, phrase, role=role, cluster_key=cluster,
                    status=status)
    oid = ""
    if body is not None:
        with db.SessionLocal() as s:
            out = db.Output(tenant=tenant, system_key="blog",
                            format="cms_article", status="published")
            s.add(out)
            s.commit()
            oid = out.id
            s.add(db.ArtifactBody(tenant=tenant, system_key="blog",
                                  format="cms_article", output_id=oid,
                                  body=body))
            s.commit()
    with db.SessionLocal() as s:
        r = (s.query(db.KeywordTarget)
             .filter(db.KeywordTarget.tenant == tenant,
                     db.KeywordTarget.phrase == phrase).first())
        r.target_url = url
        r.output_id = oid
        r.published_at = db.utcnow() - dt.timedelta(days=90)
        s.commit()
        if pos is not None:
            s.add(db.KeywordReading(tenant=tenant, phrase=phrase,
                                    position=pos, source="gsc"))
            s.commit()
    return oid


PILLAR_URL = "https://baci.example/blogs/news/corporate-venues"


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    blog = _live("baci", "blog")

    print("— the link check is offline, and forgiving of how a URL is written —")
    body = f'<p>See <a href="{PILLAR_URL}/">the venues</a>.</p>'
    ck("a trailing slash is the same page",
       links.points_at(body, PILLAR_URL))
    ck("  so is a different scheme",
       links.points_at(body, PILLAR_URL.replace("https", "http")))
    ck("  and a query string",
       links.points_at(body, PILLAR_URL + "?utm=x"))
    ck("a different page is not",
       not links.points_at(body, "https://baci.example/blogs/news/other"))
    ck("and nothing links to nothing",
       not links.points_at(body, ""),
       "an empty target matching everything would report every support as "
       "linked and the flag would never fire")

    print()
    print("— a support that links up is not flagged; one that does not, is —")
    _page("baci", "corporate venues", role="pillar", cluster="ce",
          status="published", url=PILLAR_URL, body="<p>The hub.</p>")
    _page("baci", "venue with parking", role="support", cluster="ce",
          status="published", url="https://baci.example/p",
          body=f'<p>More at <a href="{PILLAR_URL}">corporate venues</a>.</p>')
    _page("baci", "venue with catering", role="support", cluster="ce",
          status="published", url="https://baci.example/c",
          body="<p>Nothing points anywhere.</p>")
    orph = {r["phrase"]: r for r in keywords.orphan_supports("baci")}
    ck("the one that links up is clean",
       "venue with parking" not in orph)
    ck("the one that does not is flagged",
       "venue with catering" in orph,
       "`_link_grounding` verifies the links present RESOLVE — it never "
       "verifies a required one is THERE, so this passed every gate")
    ck("  and it names the pillar it should reach",
       orph["venue with catering"]["pillar"] == "corporate venues",
       str(orph["venue with catering"])[:110])

    print()
    print("— a support whose pillar has no address is WAITING, not orphaned —")
    _page("baci", "no hub yet", role="pillar", cluster="zz",
          status="published", url="", body="<p>Hub with no address.</p>")
    _page("baci", "waiting support", role="support", cluster="zz",
          status="published", url="https://baci.example/w",
          body="<p>Links nowhere.</p>")
    ck("it is not called an orphan",
       "waiting support" not in
       {r["phrase"] for r in keywords.orphan_supports("baci")},
       "there is nothing it COULD have linked to — and `unlinked()` already "
       "reports the pillar as the thing to fix, which is the one action that "
       "helps both")

    print()
    print("— the band names which supports are left to write —")
    _page("baci", "stalled hub", role="pillar", cluster="mid",
          status="published", url="https://baci.example/m",
          body="<p>Mid.</p>", pos=20)
    keywords.upsert("baci", "one narrow question", cluster_key="mid",
                    role="support", status="candidate")
    keywords.upsert("baci", "another narrow question", cluster_key="mid",
                    role="support", status="candidate")
    keywords.upsert("baci", "already done", cluster_key="mid",
                    role="support", status="published")
    sup = keywords.cluster_support("baci", "mid")
    ck("it counts what is writable",
       sorted(sup["writable"]) == ["another narrow question",
                                   "one narrow question"],
       str(sup))
    ck("  and does not offer what is already published",
       "already done" not in sup["writable"] and sup["published"] == 1,
       str(sup))
    keywords.upsert("baci", "one narrow question", owner_priority="muted")
    ck("  and never offers a keyword the owner ruled out",
       "one narrow question" not in
       keywords.cluster_support("baci", "mid")["writable"],
       "a muted keyword reappearing in a control is a decision the owner has "
       "to make again every time they look")

    print()
    print("— and the control files exactly those —")
    row = {x["phrase"]: x for x in keywords.attention("baci")}.get("stalled hub")
    ck("the attention row carries the answer",
       bool(row) and (row.get("supports") or {}).get("writable")
       == ["another narrow question"],
       str((row or {}).get("supports")))
    c = TestClient(web.app)
    r = c.post(f"/admin/plan_supports?key={KEY}",
               data={"tenant": "baci", "cluster": "mid"},
               follow_redirects=False)
    ck("it lands back on the Plan tab", r.status_code == 303
       and "tab=plan" in r.headers.get("location", ""),
       r.headers.get("location", "")[:70])
    plans = [p for p in systems.plans("baci", "blog")]
    refs = {(p.ref or "") for p in plans}
    ck("  the support is planned",
       "article:baci:another-narrow-question" in refs, str(sorted(refs)))
    ck("  the muted one is NOT",
       "article:baci:one-narrow-question" not in refs, str(sorted(refs)))
    ck("  and the keyword is marked planned, so it stops being offered",
       {k.phrase: k.status for k in keywords.targets("baci")}
       ["another narrow question"] == "planned",
       "filing without marking is how the same work gets proposed twice")
    ck("  filed under the SAME ref space the planner uses",
       all(not ref.startswith("supports:") for ref in refs),
       "a second ref space would be a second way to create work, outside the "
       "monthly cap that governs the first")

    print()
    print("— already planned is not none —")
    # THE SENTENCE PRINTED THE PUBLISHED COUNT AND DROPPED `in_flight`. A
    # cluster whose whole support layer had just been queued read as "0
    # support(s) and none left to write — the map needs more keywords",
    # sending the owner to harvest keywords for work already scheduled. Not
    # button-only either: the weekly run marks each candidate `planned` as it
    # files it, so any 11-30 page whose supports were queued last week said
    # the same wrong thing.
    after = {x["phrase"]: x for x in keywords.attention("baci")}["stalled hub"]
    ck("the cluster now has one in flight and none writable",
       after["supports"]["in_flight"] == 1
       and not after["supports"]["writable"],
       str(after["supports"]))
    ck("  and the row says THAT, not 'go find more keywords'",
       "already planned" in after["owed"]
       and "needs more keywords" not in after["owed"],
       after["owed"])
    # THE THIRD EMPTY, with a fixture that makes it real. This read
    # `… if any(row exists) else True` — and the row did not exist in this
    # suite, so the assertion was the literal `True`. An unfalsifiable check
    # naming a distinction nobody had built the case for.
    _page("baci", "done hub", role="pillar", cluster="done",
          status="published", url="https://baci.example/d",
          body="<p>Done.</p>", pos=22)
    _page("baci", "done support", role="support", cluster="done",
          status="published", url="https://baci.example/ds",
          body=f'<p><a href="https://baci.example/d">up</a></p>')
    done = {x["phrase"]: x for x in keywords.attention("baci")}["done hub"]
    ck("  a cluster with published supports and none left is an authoring gap",
       done["supports"]["published"] >= 1
       and not done["supports"]["writable"]
       and not done["supports"]["in_flight"],
       str(done["supports"]))
    ck("    and it says to build the map, not to wait",
       "needs more keywords" in done["owed"], done["owed"])

    print()
    print("— pressing it with nothing to write says so —")
    r2 = c.post(f"/admin/plan_supports?key={KEY}",
                data={"tenant": "baci", "cluster": "mid"},
                follow_redirects=False)
    from urllib.parse import unquote
    said = unquote(r2.headers.get("location", ""))
    ck("it refuses by name",
       "already planned for that cluster" in said,
       said[-100:] + " — asserting only that SOME error came back passes "
       "when the branch is deleted and the generic tail answers instead, "
       "with a different and wrong sentence")

    print()
    print("— both are on the board —")
    page = " ".join(admin_ui._board_section(KEY, "baci", 7).split())
    ck("the orphan strip is there", "Links nowhere" in page)
    # INSIDE THE STRIP, not anywhere on the page. 'venue with catering'
    # appears four times in this HTML — in the attention band and twice in
    # the keyword tables — so a whole-page grep passed with the strip
    # rendering nameless rows.
    strip = page.split("Links nowhere", 1)[1].split("<h3", 1)[0]
    ck("  the strip itself names the support", "venue with catering" in strip,
       strip[:120])
    ck("  and names the pillar it should reach",
       "corporate venues" in strip)
    ck("  and does not list the one that links up",
       "venue with parking" not in strip,
       "an absence assertion over the whole page would have been vacuous "
       "twice over")
    ck("  and saying why the publish check could not catch it",
       "never that a required one is" in page,
       "state the mechanism, not just the symptom")
    ck("  and why it is a flag rather than a rule",
       "pillar simply was not live yet" in page)

    print()
    print("— the headline control is rendered, and posts to the route —")
    # NO ASSERTION COVERED THIS AT ALL. The reviewer's mutation — replace the
    # button with "" — left both suites green, and `_plan_supports_btn` has
    # exactly one caller, so the change's headline control could have been
    # deleted silently.
    _page("baci", "band hub", role="pillar", cluster="band",
          status="published", url="https://baci.example/b",
          body="<p>Band.</p>", pos=19)
    keywords.upsert("baci", "band question", cluster_key="band",
                    role="support", status="candidate")
    board = " ".join(admin_ui._board_section(KEY, "baci", 7).split())
    ck("the button is on the row that recommends supports",
       "Plan 1 support</button>" in board,
       "the count comes from the cluster, so a button reading the wrong "
       "number is a different defect this also catches")
    ck("  and it posts to the route that files them",
       "/admin/plan_supports" in board)
    ck("  and it carries the cluster it is for",
       'name="cluster" value="band"' in board,
       "without it the press would file some other cluster's supports")
    ck("  a row with nothing writable gets no button",
       board.count("Plan 0 support") == 0,
       "a control that files nothing is a button that reports a failure")

    print()
    print("— the control obeys the SAME cap the weekly run obeys —")
    # THE DOCSTRING CLAIMED THIS AND THE CODE DID NOT DO IT. It read
    # `articles_monthly` only to SPACE the plans, never to stop: twelve
    # supports in one press put 8 into a month capped at 4 and three past the
    # horizon — and because the overrun persists, the next weekly run read
    # the month as full and refused entirely.
    cap = _live("wm", "blog")
    kb.ensure_brand("wm", "WM")
    with db.SessionLocal() as sx:
        r = sx.get(db.System, cap.id)
        cfg = dict(r.config or {})
        cfg["cadence"] = {"articles_monthly": 2, "horizon_days": 40}
        r.config = cfg
        sx.commit()
    cap = systems.find("wm", "blog")
    _page("wm", "capped hub", role="pillar", cluster="cc", status="published",
          url="https://wm.example/h", body="<p>Hub.</p>", pos=20)
    for i in range(8):
        keywords.upsert("wm", f"cap question {i}", cluster_key="cc",
                        role="support", status="candidate")
    c.post(f"/admin/plan_supports?key={KEY}",
           data={"tenant": "wm", "cluster": "cc"}, follow_redirects=False)
    months = {}
    for pl in systems.plans("wm", "blog"):
        m = str((pl.brief or {}).get("planned_for", ""))[:7]
        months[m] = months.get(m, 0) + 1
    ck("no month exceeds the cap",
       months and max(months.values()) <= 2,
       f"{months} against articles_monthly=2")
    ck("  and nothing lands past the horizon",
       all(str(k) <= (dt.date.today()
                      + dt.timedelta(days=40)).strftime("%Y-%m")
           for k in months),
       f"{months} — the weekly run stops at the horizon and said so; the "
       f"console press has to mean the same thing")
    ck("  and the ones that did not fit are still candidates",
       sum(1 for k in keywords.targets("wm")
           if k.status == "candidate" and (k.cluster_key or "") == "cc") > 0,
       "filed-or-forgotten would lose the rest of the cluster")

    print()
    print("— and it is behind the admin key —")
    # A CLUSTER WITH SOMETHING TO LOSE. The first version pointed at `mid`,
    # which by this line had nothing writable left — so deleting the entire
    # auth check left the suite green and the check named "a wrong key plans
    # nothing" passed because there was nothing to plan either way.
    keywords.upsert("baci", "guarded question", cluster_key="locked",
                    role="support", status="candidate")
    before = len(systems.plans("baci", "blog"))
    r4 = TestClient(web.app).post("/admin/plan_supports?key=wrong",
                                  data={"tenant": "baci", "cluster": "locked"},
                                  follow_redirects=False)
    ck("the cluster HAS something to plan",
       keywords.cluster_support("baci", "locked")["writable"]
       == ["guarded question"],
       "otherwise this passes whether or not the key is checked")
    ck("a wrong key plans nothing",
       len(systems.plans("baci", "blog")) == before
       and "unauthorized" in r4.text,
       f"{r4.status_code} {r4.text[:40]}")
    ck("  and the right key plans it",
       c.post(f"/admin/plan_supports?key={KEY}",
              data={"tenant": "baci", "cluster": "locked"},
              follow_redirects=False).status_code == 303
       and len(systems.plans("baci", "blog")) == before + 1,
       "the negative case means nothing without the positive beside it")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
