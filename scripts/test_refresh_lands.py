"""Addressing a Needs-attention row updates the page — it never adds one.

Owner, 2026-09-01: *"So when a 'Needs Attention' is addressed, do we have the
mechanism to patch with link in a way that makes sense, or providing updated
copy if no CMS / Website publishing exists? Make sure that the workflow still
makes sense and is very clear."*

WE DID NOT. Reproduced before anything was fixed: two runs on one keyword
queued TWO `seo_new_article` approvals. `_run_blog_article` called the CREATE
tool unconditionally, so approving a refresh on a connected store would have
published a second article beside the one that ranks — the exact
cannibalisation the attention lane exists to prevent, produced by the lane.

`propose_article_revision` had existed and worked the whole time. It needed one
thing nothing supplied: the platform's own `article_id`. `create_article`'s
reply was read for its URL and the id thrown away, so there was nothing to
address a revision to. That is the join, and it is the same shape as every
other defect here — two halves written apart, each correct alone.

BOTH HALVES OF THE WORKFLOW, because the account without a CMS is not a lesser
case:

  · WITH a CMS — the run proposes a revision against the article id, sending
    NO handle, because changing the handle moves the URL and moving the URL of
    a page that ranks throws away the reason to refresh it. The button says
    "update the live page", not "publish".
  · WITHOUT one — a person carries it, and the one thing they could get wrong
    is the one thing the page never said: paste it OVER the existing page. The
    address is stated, pre-filled, and unchanged.

And a re-publish is recorded as a REFRESH, not as a first publication:
`published_at` is when the page first went live and must stay that, or a
refreshed page reads as brand new and "days live" lies about a page that has
been up a year.

Run: python3 scripts/test_refresh_lands.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rl2.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SHOPIFY_STORES_JSON"] = (
    '{"baci": {"domain": "baci.myshopify.com", "token": "shpat_test"}}')
os.environ["SEO_SITES_JSON"] = (
    '{"baci": {"key": "baci", "domain": "bacimilanousa.com",'
    ' "platform": "shopify", "creds_key": "baci"}}')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (admin_ui, approvals, db, kb, keywords, seo_tools,  # noqa: E402
                 sites, skill, skill_pack, systems, tenants)

KEY = "s3cret"
_fail = []
approvals.notify_pending = lambda *a, **k: None
# The link check reaches the real store; the subject here is which TOOL the
# run proposes, and a network call is a different subject.
seo_tools._link_grounding = lambda *a, **k: None


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _setup(tenant, *, cms=True):
    kb.ensure_brand(tenant, tenant.title())
    row = systems.find(tenant, "blog") or systems.create(tenant, "blog")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        b = s.get(db.KbBrand, tenant)
        b.positioning = "Mid-century tableware."
        b.voice = {"tone": ["plain"]}
        b.banned_claims = ["handmade"]
        t = s.get(db.Tenant, tenant)
        t.cms = {"platform": "shopify", "blog_id": "99"} if cms else {}
        s.commit()
    kb.add_claim(tenant, f"{tenant.title()} jugs are dishwasher safe.",
                 "lab report", [])


def _workroom(output_id):
    """The workroom as a person sees it, through the same bundle the route
    builds — asserting on a hand-made call would test a page nobody visits."""
    from app.web import _article_bundle
    art, kw, ap = _article_bundle(output_id)
    return admin_ui.render_workroom(KEY, output_id, art, kw, ap)


def _seo_approvals(tenant):
    with db.SessionLocal() as s:
        return [a for a in s.query(db.Approval)
                .filter(db.Approval.tenant == tenant).all()
                if str(a.kind or "").startswith("seo")]


def main() -> int:
    db.init_db()
    tenants.seed()
    skill_pack._draft_article_live = lambda *a, **k: (
        "<h1>Acrylic jugs</h1><p>An acrylic jug is a jug made of acrylic, and "
        "this sentence is here so the body is long enough to be an article "
        "rather than a stub.</p>", "")

    print("— the id the platform gave us survives the trip —")
    reply = sites.with_article_id(
        "https://baci.example/blogs/news/acrylic-jug — published", 553221)
    ck("a create reply still leads with its URL",
       reply.startswith("https://"),
       "`approvals._published` decides a write succeeded by exactly that, so "
       "the id had to ride at the END or every publish would read as failed")
    ck("  and carries the id", sites.article_id_in(reply) == "553221", reply)
    ck("no id is an empty answer, never a guess",
       sites.article_id_in("Refused — banned_claim: handmade") == "",
       "a wrong id would revise SOMEBODY ELSE'S page")

    print()
    print("— with a CMS: the second run REVISES, it does not publish again —")
    _setup("baci")
    r1 = skill.run("blog_article", "baci", keyword="acrylic jug", role="pillar")
    oid1 = ((r1.get("items") or [{}])[-1] or {}).get("output_id", "")
    ck("the first run proposes a create", bool(oid1)
       and [a.kind for a in _seo_approvals("baci")] == ["seo_new_article"],
       str([a.kind for a in _seo_approvals("baci")]))

    keywords.mark_published("baci", oid1, url=reply.split()[0],
                            article_id=sites.article_id_in(reply))
    skill.run("blog_article", "baci", keyword="acrylic jug", role="pillar",
              revision_notes="published and not working: stalled at 8")
    kinds = [a.kind for a in _seo_approvals("baci")]
    ck("the refresh proposes a REVISION",
       kinds == ["seo_new_article", "seo_article_revision"],
       f"{kinds} — two creates was the reproduced defect: approving the "
       f"second would put a duplicate on the blog")
    rev = [a for a in _seo_approvals("baci")
           if a.kind == "seo_article_revision"][0]
    ck("  addressed to the page that ranks",
       str((rev.payload or {}).get("article_id")) == "553221",
       str((rev.payload or {}).get("article_id")))
    ck("  and it does NOT send a handle",
       "handle" not in ((rev.payload or {}).get("fields") or {}),
       "the handle is the URL; moving the address of a page that ranks "
       "throws away the reason to refresh it")
    ck("  while still sending the new copy",
       "body_html" in ((rev.payload or {}).get("fields") or {}))

    print()
    print("— a re-publish is a refresh, not a first publication —")
    with db.SessionLocal() as s:
        row = (s.query(db.KeywordTarget)
               .filter(db.KeywordTarget.tenant == "baci",
                       db.KeywordTarget.phrase == "acrylic jug").first())
        first_live = row.published_at
    with db.SessionLocal() as s:
        live_oid = (s.query(db.KeywordTarget)
                    .filter(db.KeywordTarget.tenant == "baci",
                            db.KeywordTarget.phrase == "acrylic jug")
                    .first().output_id)
    # The write-back lands on the output the REFRESH made — which is what the
    # executor passes, since the approval payload carries the new draft's id.
    got = keywords.mark_published("baci", live_oid, url=reply.split()[0])
    with db.SessionLocal() as s:
        row = (s.query(db.KeywordTarget)
               .filter(db.KeywordTarget.tenant == "baci",
                       db.KeywordTarget.phrase == "acrylic jug").first())
    ck("the first publication date is not overwritten",
       row.published_at == first_live,
       "a refreshed page would read as brand new — `too_early` for another "
       "month, and 'days live' lying about a page that has been up a year")
    ck("  the refresh is recorded as one",
       row.refreshed_at is not None and got.get("refresh") is True,
       "it drives the cooldown, and it is the only way 'did refreshing work?' "
       "can ever be answered")
    ck("  so the page leaves the attention queue",
       not any(x["phrase"] == "acrylic jug"
               for x in keywords.attention("baci")),
       "it has been rewritten and not re-crawled; asking again now asks for "
       "a decision that cannot be informed")

    print()
    print("— without a CMS: the copy says it REPLACES, and where —")
    _setup("eien", cms=False)
    r = skill.run("blog_article", "eien", keyword="acrylic jug", role="pillar")
    oid = ((r.get("items") or [{}])[-1] or {}).get("output_id", "")
    ck("nothing is queued to a CMS there",
       not _seo_approvals("eien"),
       "no platform to write to — the draft is kept and a person carries it")
    keywords.mark_published("eien", oid, url="https://eien.example/jugs")
    r2 = skill.run("blog_article", "eien", keyword="acrylic jug", role="pillar",
                   revision_notes="published and not working: stalled at 8")
    oid2 = ((r2.get("items") or [{}])[-1] or {}).get("output_id", "")
    page = " ".join(_workroom(oid2).split())
    ck("the page says it replaces a live page",
       "replaces a page that is already live" in page,
       "the one thing a person could get wrong here is pasting it as a NEW "
       "post, and the page never said not to")
    ck("  and names the address it goes over",
       "https://eien.example/jugs" in page)
    ck("  and pre-fills it, because a refresh keeps its URL",
       'value="https://eien.example/jugs"' in page,
       "retyping it is a chance to typo the join between the page and every "
       "measurement of it")
    ck("  and still offers the record-it control",
       "It&rsquo;s live here" in page or "live here" in page)

    print()
    print("— the button names the write it performs —")
    cms_page = " ".join(
        _workroom(str((rev.payload or {}).get("output_id") or "")).split())
    ck("a revision says it updates the live page",
       "update the live page" in cms_page,
       "'Approve &amp; publish' over a revision reads as a new post, which is "
       "the one thing a refresh must not be mistaken for")
    ck("  and does not also offer paste-and-record",
       "Paste it over that page" not in cms_page,
       "the arm writes the page itself; offering both is an invitation to do "
       "both")

    print()
    print("— and the page a published article sends you back to renders —")
    # A 500 ON THE RETURN PAGE, and only after a SUCCESSFUL publish, which is
    # the one path nobody re-tests. `edit_diff` is a Text column and both
    # writers store a string; the workroom called `.get("as_is")` on it, so
    # every measured artifact raised AttributeError. Found here because this
    # suite publishes and then reads the page — which is the actual loop.
    with db.SessionLocal() as s:
        live_row = (s.query(db.KeywordTarget)
                    .filter(db.KeywordTarget.tenant == "baci",
                            db.KeywordTarget.phrase == "acrylic jug").first())
        run = s.get(db.SystemRun, live_row.run_id) if live_row.run_id else None
        has_diff = bool(run is not None and run.edit_diff)
    ck("the measured artifact has a diff to render",
       has_diff,
       "without one this check passes on an artifact that never had the "
       "field — asserting on the absence of the crash rather than on the "
       "path that caused it")
    after = " ".join(_workroom(live_row.output_id).split())
    ck("  and its workroom renders", "measured" in after,
       "an AttributeError here is a 500 on the page the publish loop "
       "redirects to")

    print()
    print("— a replacement is not its predecessor —")
    with db.SessionLocal() as s:
        e_kw = (s.query(db.KeywordTarget)
                .filter(db.KeywordTarget.tenant == "eien",
                        db.KeywordTarget.phrase == "acrylic jug").first())
    ck("the keyword is published", (e_kw.status or "") == "published")
    # ONE CLAIM, NOT A DISJUNCTION. The second half — that the page says it
    # replaces a live one — is TRUE for every refresh draft, so the `or` made
    # the whole thing unfalsifiable and the first half was never tested.
    _w2 = " ".join(_workroom(oid2).split())
    ck("  but the refresh draft is NOT shown as published",
       "Published<" not in _w2 and "live page</a>." not in _w2,
       "read off the keyword alone, every refresh draft claimed to be live "
       "the moment it was written — and the workroom greeted a fresh "
       "replacement with 'Published — live page' and no way to act on it")
    ck("    while still saying it replaces one",
       "replaces a page that is already live" in _w2,
       "the two are separate claims and were asserted as one")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
