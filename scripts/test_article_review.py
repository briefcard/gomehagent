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

    # ================= the artifact is self-describing ==================
    # Owner, 2026-08-28, looking at a blog draft: "the title, SEO title, and
    # meta description in the edit area are not available in the review
    # process". They were computed at draft time and then lived ONLY in the
    # approval payload — which the review page finds by scanning PENDING
    # approvals — so the moment one stopped being pending the boxes went
    # blank above a perfect body preview. Worse, saving in that state wrote
    # the body and dropped all three without a word.
    # A SECOND article, kept entirely separate: `oid` above is still needed by
    # the publish section below, and the first version of this reassigned it.
    print("\n— identity lives on the artifact, not on a pending approval —")
    r_b = skill.run("blog_article", "acme", keyword="acrylic tumbler",
                    role="pillar")
    oid_b = r_b["items"][0]["output_id"]
    art_b, _k2, ap2 = web._article_bundle(oid_b)
    ck("the draft carried its identity from birth — BEFORE any edit",
       (art_b.meta or {}).get("seo_title")
       and (art_b.meta or {}).get("seo_description")
       and (art_b.meta or {}).get("title"),
       str(art_b.meta)[:150])
    page_i = c.get(f"/admin/article/{oid_b}?key=s3cret").text
    ck("  and the edit form is PREFILLED with it",
       f'value="{(art_b.meta or {}).get("seo_title")}"' in page_i,
       "state before instructions")

    # ONE ARTIFACT, ONE PENDING DECISION. `emit` files a generic
    # `skill_output` approval and `blog_article` then files the
    # `seo_new_article` one that actually publishes — both carrying this
    # output_id. Two rows for one thing means the workroom offers whichever
    # it read first, and half of those approve into nothing.
    with db.SessionLocal() as _s:
        _same = [a for a in _s.query(db.Approval)
                 .filter(db.Approval.status == "pending").all()
                 if (a.payload or {}).get("output_id") == oid_b]
    ck("one artifact carries exactly one pending decision", len(_same) == 1,
       ", ".join(sorted(a.kind for a in _same)) or "none")
    ck("  and it is the kind with an executor arm",
       bool(_same) and _same[0].kind == "seo_new_article",
       _same[0].kind if _same else "none")

    # Decide it, so the "no pending approval" state is real. EVERY pending
    # one, not just the one this test made: since 2026-08-31 the run queues
    # its own at the default rung, so approving `ap2` alone leaves a second
    # pending row and the state under test never arrives.
    with db.SessionLocal() as s_:
        for _a in (s_.query(db.Approval)
                   .filter(db.Approval.status == "pending").all()):
            if _a.id == ap2.id or (_a.payload or {}).get("output_id") == oid_b:
                _a.status = "approved"
        s_.commit()
    art_d, _kw, ap_d = web._article_bundle(oid_b)
    ck("with no pending approval there is nothing to fall back on",
       ap_d is None)
    page_d = c.get(f"/admin/article/{oid_b}?key=s3cret").text
    ck("  the fields are STILL there",
       f'value="{(art_d.meta or {}).get("seo_title")}"' in page_d
       and bool((art_d.meta or {}).get("seo_title")),
       "this is the state the owner found empty")
    r_d = c.post("/admin/article_save",
                 data={"key": "s3cret", "output_id": oid_b, "body": edited,
                       "title": "Renamed with no approval open",
                       "seo_title": "SEO title typed later",
                       "seo_description": "Meta typed later"},
                 follow_redirects=False)
    ck("  and an edit made now is not thrown away",
       "ok=" in r_d.headers.get("location", ""))
    art_e, _kw, _ = web._article_bundle(oid_b)
    ck("    the title saved", (art_e.meta or {}).get("title")
       == "Renamed with no approval open",
       "it used to be written only under `if ap is not None`")
    ck("    the SEO title saved",
       (art_e.meta or {}).get("seo_title") == "SEO title typed later")
    ck("    the meta description saved",
       (art_e.meta or {}).get("seo_description") == "Meta typed later")

    print("\n— and THAT is what a push would send —")
    pushed = approvals._fields_from_artifact(oid_b, {"handle": "acrylic-jug",
                                                    "title": "stale",
                                                    "body_html": "<p>stale</p>"})
    ck("the artifact's text overlays the payload",
       pushed["title"] == "Renamed with no approval open"
       and "indoors or out" in pushed["body_html"])
    ck("  while the machine-set fields survive",
       pushed["handle"] == "acrylic-jug",
       "the proposer owns the handle and the structured data; a person owns "
       "the words")
    ck("  and an unknown artifact publishes exactly as before",
       approvals._fields_from_artifact("", {"title": "untouched"})["title"]
       == "untouched",
       "every approval queued before this column existed")

    print("\n— a draft has a real name, not a format and a timestamp —")
    from app import admin_ui as _aui
    art_n, _k, _a = web._article_bundle(oid_b)
    label = _aui.artifact_label(art_n)
    ck("an article is named by its title",
       "Renamed with no approval open" in label, label)
    ck("  with the keyword it was written for",
       "acrylic tumbler" in label, label)
    ck("  and the date", "-" in label.split("—")[-1], label)
    ck("a nameless artifact still gets SOMETHING, not a blank",
       _aui.artifact_label(type("A", (), {"meta": {}, "format": "cms_article",
                                          "created_at": "2026-08-28"})())
       .startswith("cms article"),
       "a generic name is worse than a specific one and better than a blank")

    class _Camp:
        format = "campaign_email"
        created_at = "2026-08-28"
        meta = {"subject": "Your table, ready for August",
                "segment": "lapsed_buyers", "intent": "offer"}
    lab_c = _aui.artifact_label(_Camp())
    ck("an email is named by its SUBJECT",
       lab_c.startswith("Your table, ready for August"), lab_c)
    ck("  with who it is for", "to lapsed_buyers" in lab_c, lab_c)
    ck("  and what it is trying to do", "offer" in lab_c, lab_c)

    class _Ads:
        format = "ad_batch"
        created_at = "2026-08-28"
        meta = {"entity_label": "Aqua set", "audience_key": "hosts",
                "variants": 3}
    lab_a = _aui.artifact_label(_Ads())
    ck("an ad board is named by what it sells and to whom",
       "Aqua set" in lab_a and "to hosts" in lab_a and "3 variants" in lab_a,
       lab_a)

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
    # Make the artifact and the approval payload DIVERGE on purpose, so the
    # assertion below can tell which one the push actually read. In the wild
    # they diverge whenever an edit is made with no approval pending.
    with db.SessionLocal() as s_:
        _row = (s_.query(db.ArtifactBody)
                .filter(db.ArtifactBody.output_id == oid).first())
        _row.body = (_row.body or "") + "<p>DIVERGED-ON-THE-ARTIFACT</p>"
        _row.meta = {**(_row.meta or {}),
                     "title": "Title only the artifact has"}
        s_.commit()
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
    ck("  and it came from the ARTIFACT, not the payload's copy",
       "DIVERGED-ON-THE-ARTIFACT" in calls["fields"].get("body_html", "")
       and calls["fields"].get("title") == "Title only the artifact has",
       "the two used to be kept in step by hand, and an edit made with no "
       "approval pending never reached the payload at all")
    ck("  while the proposer's own fields survived the overlay",
       bool(calls["fields"].get("handle")),
       "a person owns the words; the proposer owns the handle and the "
       "structured data")
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
