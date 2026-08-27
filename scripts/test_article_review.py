"""The article review loop: see it whole, edit it, and the publish writes back.

Built against the 2026-08-26 audit, which found the owner deciding on
articles from a ONE-LINE SUMMARY — /admin/pending reads payload["body"],
which a seo_new_article payload does not have — with no edit path anywhere,
and the publish write-back fully open: no production code had ever written
KeywordTarget.target_url/published_at/status="published", the live URL was
discarded into a WhatsApp message, and `progress`'s tracked cohort was
structurally starved.

The properties pinned here, in the owner's terms:

  * the whole article is readable and editable before it ships;
  * what was reviewed is what publishes — one save updates every copy;
  * the ban list binds the owner's edits exactly as it binds the model's;
  * approving actually closes the loop: URL, published_at, status, Output,
    and the draft-vs-published delta the blog system declared as its measure
    on day one and nothing ever computed.

    python3 scripts/test_article_review.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ar.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (approvals, credentials, db, kb, keywords, shopify_seo,  # noqa: E402
                 skill, skill_pack, systems, tenants, web)

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


DRAFT = ("<h1>Acrylic jugs</h1><p>Acme jugs are made from BPA-free acrylic. "
         "A jug for every table.</p>")


def _setup(key, domain, cms, with_cred):
    with db.SessionLocal() as s:
        s.add(db.Tenant(key=key, name=key.title(), kind="client", domain=domain,
                        business_model="ecom_inventory", cms=cms, systems=[]))
        if with_cred:
            s.add(db.Credential(tenant=key, provider="shopify", site="",
                                kind="oauth", secret=credentials._encrypt("t"),
                                meta={"domain": f"{key}.myshopify.com"},
                                scopes="write_content", status="active",
                                granted_at=db.utcnow()))
        s.commit()
    kb.ensure_brand(key, key.title())
    with db.SessionLocal() as s:
        b = s.get(db.KbBrand, key)
        b.banned_claims, b.voice = ["handmade"], {"tone": ["warm"]}
        s.commit()
    kb.add_claim(key, "Acme jugs are made from BPA-free acrylic.", "spec", [])
    row = systems.create(key, "blog")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    keywords.upsert(key, "acrylic jug", volume=5000)
    keywords.cluster(key)


def main() -> int:
    db.init_db()
    skill_pack._draft_article_live = lambda *a, **k: (DRAFT, "")
    _setup("acme", "acme.example",
           {"platform": "shopify", "creds_key": "acme", "blog_id": "77"}, True)
    _setup("sqonly", "sqonly.example", {"platform": "squarespace"}, False)
    c = TestClient(web.app)

    # ================= the CMS path =====================================
    print("— drafting queues an approval that can be JOINED —")
    r = skill.run("blog_article", "acme", keyword="acrylic jug", role="pillar")
    oid = r["items"][0]["output_id"]
    _art, _kw, ap = web._article_bundle(oid)
    ck("the approval carries the output_id", ap is not None
       and (ap.payload or {}).get("output_id") == oid,
       "without it the executor has nothing to write the publish back onto")
    ck("and the run_id, on the approval row itself",
       ap is not None and bool(ap.run_id),
       "the decision and the edit delta land on the SystemRun through it")

    print("\n— the review page shows the WHOLE article —")
    page = c.get(f"/admin/article/{oid}?key=s3cret").text
    ck("the full body renders", "BPA-free acrylic" in page,
       "the owner was deciding from a one-line summary")
    ck("with an approve control", "Approve" in page)
    ck("and an edit form", "article_save" in page)
    ck("but no mark-as-published form — this account publishes by approval",
       "article_published" not in page)
    pend = c.get("/admin/pending?key=s3cret").text
    ck("/admin/pending now shows the article text too",
       "BPA-free acrylic" in pend,
       "its body lookup missed fields.body_html — every channel had the "
       "same blind spot")
    ck("and links the review page", "review &amp; edit" in pend)

    print("\n— what was reviewed is what publishes —")
    edited = DRAFT.replace("every table", "every table, indoors or out")
    r2 = c.post("/admin/article_save",
                data={"key": "s3cret", "output_id": oid, "body": edited,
                      "title": "Acrylic jugs, properly",
                      "seo_title": "", "seo_description": ""},
                follow_redirects=False)
    ck("the save lands", r2.status_code == 303 and "ok=" in r2.headers["location"])
    art, _kw, ap = web._article_bundle(oid)
    ck("ArtifactBody.body is the edit", "indoors or out" in (art.body or ""))
    ck("draft_body is STILL the draft", "indoors or out" not in (art.draft_body or ""),
       "the declared measure is draft-vs-published; a delta needs the draft "
       "to survive the edit that makes it interesting")
    ck("the approval payload publishes the edit",
       "indoors or out" in ((ap.payload or {}).get("fields") or {}).get("body_html", ""))
    ck("and the new title travels with it",
       ((ap.payload or {}).get("fields") or {}).get("title") == "Acrylic jugs, properly")

    print("\n— the ban list binds the owner too —")
    r3 = c.post("/admin/article_save",
                data={"key": "s3cret", "output_id": oid,
                      "body": edited + "<p>Each one handmade with love.</p>",
                      "title": "", "seo_title": "", "seo_description": ""},
                follow_redirects=False)
    ck("a banned phrase refuses the save", "err=" in r3.headers.get("location", ""),
       "an edit reintroduces 'handmade' as easily as a model does, and the "
       "guard firing later — on a text the owner approved — reads as the "
       "system overriding them")
    art2, _kw, _ap = web._article_bundle(oid)
    ck("and nothing changed", "handmade" not in (art2.body or ""))

    print("\n— approving closes the loop —")
    calls = {}

    def _fake_create(profile, blog_id, fields):
        calls["fields"] = fields
        return "https://acme.example/blogs/news/acrylic-jug — saved as a draft"
    _real = shopify_seo.create_article
    shopify_seo.create_article = _fake_create
    try:
        token = approvals._signer.dumps([ap.id, "approved"])
        approvals.decide(token)
    finally:
        shopify_seo.create_article = _real
    ck("what shipped is the REVIEWED text",
       "indoors or out" in calls["fields"].get("body_html", ""))
    with db.SessionLocal() as s:
        kw = (s.query(db.KeywordTarget)
              .filter_by(tenant="acme", phrase="acrylic jug").first())
        out = s.get(db.Output, oid)
        run = s.get(db.SystemRun, ap.run_id) if ap.run_id else None
    ck("the keyword row learned its URL",
       kw.target_url == "https://acme.example/blogs/news/acrylic-jug",
       "the audit found the URL was discarded into a WhatsApp message — no "
       "production writer for target_url existed at all")
    ck("and its status", kw.status == "published")
    ck("and when", kw.published_at is not None)
    ck("the Output row is published, not draft-forever",
       out.status == "published",
       "cms_article outputs previously stayed 'draft' forever — "
       "ledger.publish had zero production callers")
    # `decision` records what the human did with the approval — "approved" —
    # and `edit_diff` records whether the text changed under them. The mail
    # path has meant exactly this since edits.record was written (`run.decision
    # or ...` never overwrites the verdict), so the article path matches it
    # rather than inventing a second meaning for the same column.
    ck("the declared measure finally computes",
       run is not None and bool(run.edit_diff)
       and "published unchanged" not in (run.edit_diff or "")
       and run.decision == "approved",
       f"edit_diff={(run.edit_diff or '')[:40]!r} decision={run.decision!r}")

    print("\n— and the measurement loop can finally see it —")
    keywords.record_reading("acme", "acrylic jug", position=14.0, clicks=9)
    keywords.record_reading("acme", "a control page", position=6.0, clicks=20)
    p = keywords.progress("acme", days=28)
    ck("the tracked cohort is no longer starved",
       p["tracked"]["now"]["phrases"] == 1,
       "progress attributes only published/won rows, and nothing in "
       "production ever produced one")
    b = keywords.board("acme")
    live = [x for x in b["in_flight"] if x["phrase"] == "acrylic jug"]
    ck("the board's live-page link can now render",
       live and live[0]["target_url"].startswith("https://"),
       "it could never render before — target_url had no writer")

    # ================= the no-CMS path ==================================
    print("\n— the manual path records where it went live —")
    r4 = skill.run("blog_article", "sqonly", keyword="acrylic jug", role="pillar")
    oid2 = r4["items"][0]["output_id"]
    page2 = c.get(f"/admin/article/{oid2}?key=s3cret").text
    ck("no approval to decide, so the page offers mark-as-published",
       "article_published" in page2 and "Approve &amp; publish" not in page2)
    r5 = c.get(f"/admin/article_published?key=s3cret&output_id={oid2}"
               f"&url=notaurl", follow_redirects=False)
    ck("a non-URL is refused", "err=" in r5.headers["location"])
    r6 = c.get(f"/admin/article_published?key=s3cret&output_id={oid2}"
               f"&url=https://sqonly.example/blog/acrylic-jug",
               follow_redirects=False)
    ck("a real one is recorded", "ok=" in r6.headers["location"])
    with db.SessionLocal() as s:
        kw2 = (s.query(db.KeywordTarget)
               .filter_by(tenant="sqonly", phrase="acrylic jug").first())
        out2 = s.get(db.Output, oid2)
    ck("keyword row updated", kw2.status == "published"
       and kw2.target_url.endswith("/blog/acrylic-jug"))
    ck("output published", out2.status == "published")
    r7 = c.get(f"/admin/article_published?key=s3cret&output_id={oid2}"
               f"&url=https://elsewhere.example/x", follow_redirects=False)
    ck("an off-domain URL warns and does not refuse",
       "ok=" in r7.headers["location"] and "not+on+sqonly.example"
       in r7.headers["location"].replace("%20", "+"),
       "staging hosts and CDNs are real; a caution, not a block")

    print("\n— Request changes: the article redraft (UI overhaul 3.3b) —")
    ck("a PUBLISHED article refuses the redraft — a live page gets a "
       "revision, not a redraft of its draft",
       skill_pack.redraft_artifact("sqonly", oid2, note="x")
       .get("ok") is not True)
    r8 = skill.run("blog_article", "sqonly", keyword="acrylic carafe",
                   role="support")
    oid3 = r8["items"][0]["output_id"]
    with db.SessionLocal() as s:
        s.add(db.FeedbackItem(tenant="sqonly", output_id=oid3, part="body",
                              category="tone",
                              note="ARTICLE-REDRAFT-NOTE warmer opening",
                              level="draft", status="open"))
        s.commit()
    _seen_rd: dict = {}
    _orig_live = skill_pack._draft_article_live

    def _capture_live(bundle, *a, **k):
        _seen_rd["bundle"] = dict(bundle or {})
        return _orig_live(bundle, *a, **k)
    skill_pack._draft_article_live = _capture_live
    got_rd = skill_pack.redraft_artifact("sqonly", oid3,
                                         note="typed blog note")
    skill_pack._draft_article_live = _orig_live
    ck("the redraft runs fresh and supersedes",
       got_rd.get("ok") is True
       and got_rd.get("output_id") not in ("", oid3), str(got_rd)[:90])
    ck("…the drafter's bundle carried the owner's notes",
       "ARTICLE-REDRAFT-NOTE" in (_seen_rd.get("bundle", {})
                                  .get("revision_notes") or "")
       and "typed blog note" in (_seen_rd.get("bundle", {})
                                 .get("revision_notes") or ""))
    with db.SessionLocal() as s:
        old3 = s.get(db.Output, oid3)
        kw3 = (s.query(db.KeywordTarget)
               .filter_by(tenant="sqonly", phrase="acrylic carafe").first())
    ck("the old row is SUPERSEDED and names its successor",
       old3.status == "superseded"
       and old3.destination == f"superseded:{got_rd.get('output_id')}",
       f"{old3.status} · {old3.destination}")
    ck("…and the keyword row points at the LIVING draft",
       kw3.output_id == got_rd.get("output_id"), str(kw3.output_id)[:14])

    print("\n— the run LANDS on the article it made —")
    # Owner, live: *"I published an article and I dont see it. Where is it?"*
    # The flash was a paragraph directing them to the Plan tab's board — from
    # a redirect that landed them on the SYSTEMS tab — and a directly-run
    # keyword stayed "candidate", so the board's targeting table did not list
    # it: the notification pointed at a row that was not there.
    keywords.upsert("sqonly", "event spaces miami", volume=900)
    keywords.cluster("sqonly")
    plan = systems.open_plan("sqonly", "blog",
                             ref="article:sqonly:event-spaces-miami",
                             plan={"keyword": "event spaces miami",
                                   "role": "pillar"},
                             trigger="planner")
    rid = plan.get("run_id") or plan.get("id") or ""
    if not rid:
        with db.SessionLocal() as s:
            rid = (s.query(db.SystemRun)
                   .filter(db.SystemRun.tenant == "sqonly")
                   .order_by(db.SystemRun.started_at.desc()).first().id)
    r9 = c.get(f"/admin/plan_run?key=s3cret&id={rid}&tenant=sqonly"
               f"&system=blog&approve=1", follow_redirects=False)
    loc = r9.headers.get("location", "")
    ck("Run now redirects to the review page itself",
       r9.status_code == 303 and "/admin/article/" in loc, loc[:110])
    ck("saying plainly that this is it", "this+is+it" in loc.replace("%20", "+"),
       "a run that produces one reviewable thing puts it in front of the "
       "person who asked")
    oid3 = loc.split("/admin/article/")[1].split("?")[0]
    with db.SessionLocal() as s:
        kw3 = (s.query(db.KeywordTarget)
               .filter_by(tenant="sqonly", phrase="event spaces miami").first())
    bd = keywords.board("sqonly")
    ck("and the board's targeting table lists it",
       any(x["phrase"] == "event spaces miami" and x["output_id"] == oid3
           for x in bd["in_flight"]),
       f"status={kw3.status!r} — a row with an article behind it is past "
       f"candidate whatever filed it")

    print("\n— a DIRECT run is findable too —")
    keywords.upsert("sqonly", "loft venue miami", volume=400)
    keywords.cluster("sqonly")
    r10 = skill.run("blog_article", "sqonly", keyword="loft venue miami",
                    role="support")
    with db.SessionLocal() as s:
        kw4 = (s.query(db.KeywordTarget)
               .filter_by(tenant="sqonly", phrase="loft venue miami").first())
    ck("no plan, same visibility", kw4.status == "planned",
       "the direct path left it candidate — invisible to the exact table "
       "the summary named")

    print("\n— the corrected Shopify URL —")
    sent = {}
    _send_real, _get_real = shopify_seo._send, shopify_seo._get
    shopify_seo._send = lambda store, m, path, body: (
        {"article": {"handle": "jug-care", "published_at": None}})
    shopify_seo._get = lambda store, path, params=None: (
        {"blog": {"handle": "news"}} if path.startswith("blogs/") else {})
    try:
        res = shopify_seo.create_article(
            {"key": "acme", "domain": "acme.example", "creds_key": "acme",
             "platform": "shopify"}, "77",
            {"title": "T", "body_html": "<p>x</p>"})
    finally:
        shopify_seo._send, shopify_seo._get = _send_real, _get_real
    ck("the URL carries the blog handle",
       "/blogs/news/jug-care" in res,
       "it returned /blogs/<article-handle> — one path segment short of "
       "existing, harmless while only a person read it, wrong the moment "
       "it became target_url")

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
