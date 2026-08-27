"""The judgement half of pointer integrity — every root-cause fix, pinned.

The 2026-08-26 sweep found 75 not-ok instances of one family: a message
pointing at a place that does not hold the thing. Most collapsed into a few
root causes; each fix below is asserted at its root so a regression fails by
name rather than waiting for the owner's click.

    python3 scripts/test_pointer_fixes.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pf.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (admin_ui, credentials, db, emailfmt, kb, keywords,  # noqa: E402
                 systems, tenants, web)

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    c = TestClient(web.app)

    print("— a Review redirect opens the section its anchor lives in —")
    for anchor, want in (("proposals", "sub=claims"), ("c-abc123", "sub=claims"),
                         ("pics", "sub=pictures"), ("others", "sub=other"),
                         ("plan-xyz", "sub=plans")):
        loc = web._back_to_content("baci", anchor=anchor).headers["location"]
        ck(f"#{anchor} → {want}", want in loc, loc)
    loc = web._back_to_content("baci", started="harvest").headers["location"]
    ck("a harvest-started banner lands on the claims section",
       "sub=claims" in loc, loc)
    loc = web._back_to_content("baci", sub="conflicts").headers["location"]
    ck("an explicit sub overrides", "sub=conflicts" in loc)
    loc = web._back_to_content("baci").headers["location"]
    ck("a bare return keeps the tab default", "sub=" not in loc,
       "no anchor, no promise — the counts fallback is correct there")

    print("\n— system_set keeps its place and refuses out loud —")
    row = systems.create("ironside", "blog")
    r = c.get(f"/admin/system_set?key=s3cret&id={row.id}&status=live"
              f"&back=plan&tenant=ironside", follow_redirects=False)
    loc = r.headers["location"]
    ck("a refused switch-on is a FLASH on the Plan tab, not raw JSON",
       "tab=plan" in loc and "err=" in loc and "tenant=ironside" in loc, loc[:120])
    r2 = c.get(f"/admin/system_set?key=s3cret&id={row.id}&notes=x",
               follow_redirects=False)
    loc2 = r2.headers["location"]
    ck("a systems-tab save keeps tenant and system",
       "tenant=ironside" in loc2 and "system=blog" in loc2, loc2[:120])
    ck("and its flash uses the key the dispatcher reads",
       "ok=" in loc2, "the helper wrote msg= for as long as it existed — "
       "every flash it carried rendered nowhere")

    print("\n— an accepted exclude term binds EVERY harvest source —")
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, "ironside")
        t.analytics = {"exclude_terms": ["wedding"]}
        s.commit()
    keywords._fetch_gsc = lambda p_, d, l: [
        {"query": "wedding venue miami", "position": 14.0, "impressions": 100},
        {"query": "corporate venue miami", "position": 14.0, "impressions": 100}]
    keywords._fetch_own = lambda p_, l: [{"keyword": "wedding packages", "volume": 500}]
    keywords._fetch_gap = lambda p_, l: []
    keywords._fetch_related = lambda p_, s_, l: [{"keyword": "wedding caterers", "volume": 300}]
    keywords._fetch_questions = lambda p_, s_, l: [{"question": "what does a wedding cost", "volume": 100}]
    keywords.harvest("ironside", seeds=("venue",))
    phrases = {r.phrase for r in keywords.targets("ironside")}
    ck("gsc, own, related and questions all filtered",
       not any("wedding" in p_ for p_ in phrases), str(phrases),)
    ck("the non-excluded phrase still arrived", "corporate venue miami" in phrases,
       "only the gap fetch filtered before — accepting a term stopped one "
       "entrance of five and the owner's decision looked ignored")

    print("\n— the connect page offers a CMS to a blog account —")
    ck("needed_for includes a cms provider once blog is installed",
       any(p_ in ("shopify", "wordpress")
           for p_ in credentials.needed_for("ironside")),
       "blog requires nothing to RUN — and the moment any system was "
       "installed, the page that sites.backend()'s own refusal points at "
       "stopped offering a store")

    print("\n— the digest says what approving each card DOES —")
    html = emailfmt.approval_email([
        {"_kind": "send_email", "subject": "Re: hi", "body": "Dear X",
         "inbound_from": "a@b.c", "account": "baci", "inbound_snippet": "hi",
         "reason": "fine", "approve_url": "u", "deny_url": "d"},
        {"_kind": "seo_new_article", "summary": "[SEO] New article: Jugs",
         "fields": {"body_html": "<h1>Jugs</h1>"},
         "approve_url": "u2", "deny_url": "d2"}])
    ck("the article card never promises a send",
       "publishes the article" in html and html.count("Approve &amp; send") == 1,
       "'Approve & send' over an article publish, and a Drafts-folder tip "
       "for a Gmail draft that does not exist")
    ck("the mixed intro stops describing every card as a reply",
       "1 repl" in html and "1 other" in html)
    html2 = emailfmt.approval_email([
        {"_kind": "sweep", "summary": "nightly sweep",
         "approve_url": "u", "deny_url": "d"}])
    ck("a no-reply digest drops the Drafts tip", "Drafts folder" not in html2)

    print("\n— the theme can finally name a sender —")
    ck("sender.name is an editable theme field",
       any(p_ == "sender.name" for p_, _l, _h in admin_ui._THEME_EDIT_FIELDS),
       "the sign-off note said 'set it on the Brand tab' while no control "
       "existed — it fired on every signature block, forever")

    print("\n— who said it is settable, so a quote can survive —")
    kb.ensure_brand("ironside", "Miami Ironside")
    cid = kb.add_claim("ironside", "Best venue we have used.", "email", [],
                       proof_type="testimonial")
    with db.SessionLocal() as s:
        row_c = (s.query(db.KbClaim)
                 .filter(db.KbClaim.tenant == "ironside").first())
    got = kb.update_claim(row_c.id, attributed_to="Dana R.")
    with db.SessionLocal() as s:
        ck("update_claim writes attributed_to",
           s.get(db.KbClaim, row_c.id).attributed_to == "Dana R.", str(got))

    print("\n— a deep link to a plan carries its page —")
    ck("plan_page mirrors the board's slice",
       systems.plan_page("ironside", "blog", "nonexistent") == 1,
       "an unknown id lands on page 1 rather than 500ing")

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
