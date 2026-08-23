"""Approved photographs are visible somewhere.

Owner, 2026-08-23: "add a place to see all approved photos in the knowledge".
There was nowhere. The picture grid on Review renders ONLY the proposed queue,
and the number of approved ones appeared in a sentence nested inside
`if waiting:` — so an account that had worked its queue down to empty could not
see the library it had just built, or even how big it was. Approving a
photograph was a decision with no visible consequence anywhere in the console.

What is pinned here:

  1. IT EXISTS, on Knowledge, and it lists the actual photographs.
  2. IT SHOWS ONLY WHAT MAY BE PUBLISHED. A reference-rights picture — one the
     client does not own — must never appear in a library that reads as
     "these are yours to use". That is the same line `creative.hero_for_campaign`
     holds, and a library that disagreed with it would be worse than none.
  3. LOGOS ARE HELD APART. A brand mark is never a hero; showing it in the same
     grid invites exactly that.
  4. IT SAYS WHAT EACH ONE IS OF. `entity_key` is what `coherence.review`
     checks a hero against, so a library that omits it cannot answer "why did
     that email pick this picture".
  5. THE EMPTY STATE SAYS WHERE PHOTOGRAPHS COME FROM, rather than looking
     like a broken card.

Run: python3 scripts/test_photo_library.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, kb, tenants  # noqa: E402
from app.web import app  # noqa: E402

KEY = "s3cret"
client = TestClient(app)
_fails = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def page():
    return client.get(f"/admin/ui?tab=kb&tenant=baci&key={KEY}").text


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— before anything is approved —")
    empty = page()
    ck("the card is there rather than absent",
       "Photographs the creative may use" in empty)
    ck("…and it says where photographs come from",
       "Nothing approved yet" in empty and "Review" in empty)

    kb.add_entity("baci", "product", "aqua", "Aqua pitcher")
    kb.add_asset("baci", "https://cdn.example/aqua.jpg", rights=kb.OWNED,
                 title="Aqua on linen", entity_key="aqua", origin="human")
    kb.add_asset("baci", "https://cdn.example/shelf.jpg", rights=kb.OWNED,
                 title="Tablescape, evening", origin="human")
    kb.add_asset("baci", "https://cdn.example/mark.png", rights=kb.OWNED,
                 title="Brand mark", subject=kb.LOGO, origin="human")
    # NOT the client's to publish. The whole reason `rights` is required and
    # has no safe default.
    kb.add_asset("baci", "https://cdn.example/competitor.jpg",
                 rights=kb.REFERENCE, title="Competitor ad", origin="human")

    print("\n— the library —")
    h = page()
    ck("every approved, owned photograph is shown",
       "aqua.jpg" in h and "shelf.jpg" in h)
    ck("…in the thumbnail grid, not as a list of URLs", "picgrid" in h)
    ck("…and it counts them", "2 approved" in h, "count chip missing")

    print("\n— what may NOT be shown —")
    ck("a REFERENCE-rights picture never appears — it is not theirs to publish",
       "competitor.jpg" not in h)
    ck("the logo is held apart from the photographs",
       "mark.png" in h and "Logos" in h)
    ck("…and says why, so nobody files the next one as a photograph",
       "letterhead" in h)

    print("\n— what each one is of —")
    ck("a scoped photograph names the product it depicts", "Aqua pitcher" in h)
    ck("…and an unscoped one says brand-wide rather than nothing",
       "brand-wide" in h)

    print("\n— use is visible, because approving grants it —")
    row = [a for a in kb.assets("baci", publishable_only=True, kind="image")
           if a.url.endswith("aqua.jpg")][0]
    kb.mark_asset_used(row.id, destination="campaign_email draft")
    ck("a photograph that has been published says so",
       "used 1" in page())

    print("\n— it is a view, not a second queue —")
    # Deciding belongs on Review, where the decision is. If this page grew
    # approve/reject controls there would be two queues disagreeing about the
    # same rows.
    ck("no approve or reject control on the Knowledge tab",
       "assets_decide" not in h and 'name="asset_ids"' not in h)

    print("\n" + ("all checks passed" if not _fails
                  else f"{len(_fails)} FAILED: " + "; ".join(_fails)))
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
