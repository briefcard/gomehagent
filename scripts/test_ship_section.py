"""The Review tab finally reviews the thing the word means: what may ship.

The 2026-08-26 audit found the tab named Review had six sections and none of
them were approvals — the owner decided whether an article ships from a
one-line summary on the unstyled /admin/pending fallback, with the same blind
spot on the WhatsApp card, and the WhatsApp Edit button seeding a revision
from an empty string.

    python3 scripts/test_ship_section.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sh.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import admin_ui, approvals, db, tenants, web  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    ap_id = approvals.request_approval(
        "seo_new_article", "[SEO/baci] New article: Jugs",
        {"site": "baci", "bucket": "seo", "output_id": "out-123",
         "fields": {"title": "Jugs", "body_html": "<h1>Jugs</h1><p>All about jugs.</p>"}},
        notify=False)
    approvals.request_approval(
        "send_email", "[eien] Reply to customer",
        {"account": "eien", "body": "Dear customer, thanks."}, notify=False)

    print("— the section exists, first, and lands by default —")
    page = admin_ui.render_content("s3cret", "baci")
    ck("with no sub asked for, the tab lands on the ship queue",
       "May it ship?" in page and "All about jugs" in page,
       "the strip's order is the day's order, and 'may this go out' outranks "
       "'is this true'")
    ck("the article's TEXT is on the page",
       "All about jugs" in page,
       "the owner was deciding from a one-line summary")
    # Retargeted twice, deliberately: 2b made ✅/❌ labeled link-buttons;
    # step 4 (2026-08-27) made them POST forms that decide IN CONSOLE and
    # flash the executor's own sentence back — the signed /decide links are
    # the email mechanism only now. The approve button states its
    # consequence per kind ("Approve & publish" for an article).
    ck("with approve and deny in place, deciding in-console",
       'action="/admin/ship_decide"' in page
       and 'value="approved"' in page and 'value="denied"' in page
       and "Approve &amp; publish" in page and ">Deny</button>" in page)
    ck("and the review page one click away", "review &amp; edit" in page)

    print("\n— scoped to the account being looked at —")
    ck("another client's approval does not render",
       "Reply to customer" not in page,
       "an approval from another tenant on this page is the pooled-page leak "
       "all over again")
    eien = admin_ui.render_content("s3cret", "eien", sub="ship")
    ck("it renders on ITS account's page", "Reply to customer" in eien)
    ck("where the email body previews too", "Dear customer" in eien,
       "kinds that carry payload.body use it; articles fall back to "
       "fields.body_html — one preview chain for every kind")

    print("\n— the entry points lead here, not to the fallback —")
    frame = admin_ui.render_plan("s3cret", "baci")
    ck("the frame's waiting pill targets the section",
       "tab=content&amp;sub=ship" in frame and "/admin/pending" not in
       frame.split("waiting</a>")[0].rsplit("<a", 1)[-1],
       "/admin/pending survives only as the unauthenticated-email fallback")

    print("\n— WhatsApp Edit stops offering to retype an article —")
    said = []
    from app import channel
    real = channel.send_text
    channel.send_text = lambda t, **k: said.append(t)
    try:
        web._handle_button("edit", ap_id)
    finally:
        channel.send_text = real
    ck("an article edit is pointed at the review page",
       said and "/admin/article/out-123" in said[0],
       "the capture flow seeds the revision from payload['body'], which an "
       "article does not carry — the agent would revise an EMPTY draft")
    ck("and not into the chat-capture flow",
       said and "Send me your edited version" not in said[0])

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
