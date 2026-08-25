"""The article tools, and the layer that was missing under them.

`shopify_seo` and `wordpress_seo` have carried the same five article functions
— list_blogs, list_articles, get_article, create_article, update_article —
with NOTHING CALLING ANY OF THEM. `seo_tools.TOOLS` held 33 tools and not one
was an article tool; `approvals.execute` had no article kind. The blog path was
complete from the platform up to the backend and stopped one layer below the
agent, which is the same shape as a declared-and-never-written capability:
everything reads present and nothing can run.

These checks assert the layer, not the platform. Every one of them stops before
the network — a refusal, a queued approval row, or a routing decision — because
what was broken was reachability, and reachability is provable offline.

    python3 scripts/test_blog_path.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'bp.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SHOPIFY_STORES_JSON"] = (
    '{"baci": {"domain": "baci.myshopify.com", "token": "shpat_test"}}')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import approvals, db, kb, seo_tools, shopify_seo, tenants, wordpress_seo  # noqa: E402

# `_propose` queues with the production default (notify=True), and notifying
# reaches for a Gmail account no offline suite has. Replacing the module-level
# seam is this repo's own idiom for that — the assertions are about what landed
# in the APPROVAL ROW, and a delivery attempt is a different subject.
approvals.notify_pending = lambda *a, **k: None

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


BACI = {"key": "baci", "domain": "bacimilanousa.com", "platform": "shopify",
        "creds_key": "baci"}
NAMES = {t["name"] for t in seo_tools.TOOLS}
ARTICLE_TOOLS = ("list_blogs", "list_articles", "get_article",
                 "propose_article", "propose_article_revision")


def _pending(kind: str) -> list:
    with db.SessionLocal() as s:
        return [a for a in s.query(db.Approval).all() if a.kind == kind]


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.add_banned("baci", "hand-decorated")

    print("— the five functions exist on BOTH backends, or a publish dies mid-call —")
    # sites.backend() is duck-typed; a missing function is an AttributeError
    # thrown after the approval was already granted.
    for fn in ("list_blogs", "list_articles", "get_article", "create_article",
               "update_article"):
        ck(f"shopify_seo.{fn}", callable(getattr(shopify_seo, fn, None)))
        ck(f"wordpress_seo.{fn}", callable(getattr(wordpress_seo, fn, None)))

    print("\n— the agent can SEE them —")
    for t in ARTICLE_TOOLS:
        ck(f"{t} is offered", t in NAMES)

    print("\n— and every one of them ROUTES (the actual regression) —")
    # A tool in TOOLS but not in dispatch falls through to _HANDLERS[name] and
    # returns "Tool error (KeyError)" — visible only by calling it.
    probe = {"site": "baci", "blog_id": "9", "article_id": "77"}
    for t in ARTICLE_TOOLS:
        out = seo_tools.dispatch(t, dict(probe), {})
        ck(f"{t} does not KeyError", "KeyError" not in out, out[:70])

    print("\n— a new article is refused before it can queue —")
    out = seo_tools.dispatch("propose_article", {"site": "baci", "title": "x"}, {})
    ck("no body is refused", "answer-first" in out, out[:70])
    out = seo_tools.dispatch(
        "propose_article",
        {"site": "baci", "title": "Aqua jug", "body_html": "<p>Acrylic.</p>"}, {})
    ck("a missing blog_id is NAMED, not guessed", "list_blogs" in out, out[:70])

    print("\n— the ban list fires BEFORE the owner is asked to approve —")
    out = seo_tools.dispatch(
        "propose_article",
        {"site": "baci", "blog_id": "9", "title": "Our craft",
         "body_html": "<p>Every piece is hand-decorated.</p>"}, {})
    ck("a banned claim never reaches the queue", out.startswith("Refused"), out[:70])
    ck("it says which field", "body_html" in out, out[:90])
    ck("nothing was queued", not _pending("seo_new_article"),
       "approving prose that cannot publish spends the owner's attention on a "
       "decision with no outcome")

    print("\n— a clean article queues, and carries what the executor needs —")
    out = seo_tools.dispatch(
        "propose_article",
        {"site": "baci", "blog_id": "9", "title": "Choosing an acrylic jug",
         "body_html": "<p>Acrylic holds cold longer.</p>",
         "seo_description": "How to choose an acrylic jug.",
         "faqs": [{"question": "Is it dishwasher safe?", "answer": "Top rack."}]},
        {})
    ck("it queues", "Queued for your approval" in out, out[:70])
    ck("it says it is a draft", "draft" in out.lower(), out[:90])
    rows = _pending("seo_new_article")
    ck("exactly one approval row", len(rows) == 1)
    if rows:
        pl = rows[0].payload
        ck("payload carries the site", pl.get("site") == "baci")
        ck("payload carries blog_id", pl.get("blog_id") == "9",
           "Shopify writes to blogs/<id>/articles.json — without it the call 404s")
        f = pl.get("fields") or {}
        ck("FAQ HTML is in the body", "Frequently asked questions" in f.get("body_html", ""))
        ck("FAQPage JSON-LD rides as structured_data", "FAQPage" in str(f.get("structured_data")),
           "Shopify drops <script> from body_html — INLINE_JSONLD is False, so "
           "it must travel as a metafield or it is silently lost")

    print("\n— a revision is partial, and refuses to work blind —")
    out = seo_tools.dispatch(
        "propose_article_revision",
        {"site": "baci", "blog_id": "9", "seo_title": "Acrylic jugs"}, {})
    ck("no article_id is refused", "article_id" in out, out[:70])
    out = seo_tools.dispatch(
        "propose_article_revision",
        {"site": "baci", "blog_id": "9", "article_id": "77",
         "seo_title": "Acrylic jugs, chosen well"}, {})
    ck("a one-field revision queues", "Queued for your approval" in out, out[:70])
    rows = _pending("seo_article_revision")
    ck("exactly one revision row", len(rows) == 1)
    if rows:
        f = rows[0].payload.get("fields") or {}
        ck("ONLY the field given is carried", set(f) == {"seo_title"},
           f"got {sorted(f)} — sending more would rewrite fields nobody asked "
           "to change, and an absent body arriving as '' blanks a live page")

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
