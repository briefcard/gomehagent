"""Every console page's forms are actually wired to a form.

The bug this exists for (owner, 2026-08-23: "Photo approvals are not
working"): the picture queue rendered an anchor `<div id="pics">` and, twelve
lines later, `<form id="pics">`. Every checkbox, the hidden tenant field and
all three buttons associated themselves with `form="pics"` — and HTML resolves
that to the FIRST element with the id, which was the div. A `form=` attribute
pointing at a non-form element associates with nothing, so the controls were
orphaned: the page looked completely normal, the buttons submitted nothing, and
approving a photograph silently did nothing at all.

Nothing could have caught that by reading the page for words. It is a
STRUCTURAL property of the markup, so it is checked structurally, on every tab
rather than on the one that broke — the same collision is one copy-paste away
anywhere else.

Two invariants, both cheap and both absolute:

  1. NO DUPLICATE ids on a page. Everything downstream of an id — `form=`,
     `<label for=>`, `getElementById`, an `#anchor` — silently takes the first
     match, so a duplicate is never a style problem.
  2. EVERY `form="x"` resolves to a `<form id="x">` on the same page.

Run: python3 scripts/test_admin_forms.py
"""
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'af.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, kb, tenants  # noqa: E402
from app.web import app  # noqa: E402

KEY = "s3cret"
client = TestClient(app)
_fails: list[str] = []

#: The tab KEYS, not the labels shown on them — `_TABS` in `admin_ui` maps
#: ("content", "Review"), ("kb", "Knowledge"), ("schema", "Data layer") and so
#: on. Asserting against the labels renders the DEFAULT tab eight times and
#: every check passes against the same page, which is a false pass of exactly
#: the kind this file exists to prevent.
TABS = ("content", "kb", "brand", "systems", "assurance", "diagnostics",
        "accounts", "schema")


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def _ids(html: str) -> list[str]:
    return re.findall(r'\bid="([^"]+)"', html)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.set_brand("baci", tone="Warm.")
    kb.add_banned("baci", "hand-decorated")
    # A proposed picture, so the queue actually renders. An assertion about
    # markup that was never emitted is the empty-table false pass `sabotage.py`
    # was written after.
    kb.add_asset("baci", "https://cdn.example/candidate.jpg", rights=kb.OWNED,
                 title="A candidate", origin="crawl")

    for tab in TABS:
        r = client.get(f"/admin/ui?tab={tab}&tenant=baci&key={KEY}")
        if r.status_code != 200:
            ck(f"{tab}: renders", False, f"HTTP {r.status_code}")
            continue
        html = r.text

        ids = _ids(html)
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        ck(f"{tab}: no duplicate element ids", not dupes, ", ".join(dupes[:4]))

        forms = set(re.findall(r'<form[^>]*\bid="([^"]+)"', html))
        wanted = set(re.findall(r'\bform="([^"]+)"', html))
        orphans = sorted(wanted - forms)
        ck(f"{tab}: every form= points at a real <form>", not orphans,
           ", ".join(orphans[:4]))

    # THE REVIEW SUB-TABS, each rendered on its own. The strip splits one
    # scroll into six sections (owner, 2026-08-23: "endless scrolls"), and each
    # is markup the others never render — so checking the tab once checks one
    # sixth of it.
    from app.admin_ui import REVIEW_SUBS
    for k, label in REVIEW_SUBS:
        r = client.get(f"/admin/ui?tab=content&sub={k}&tenant=baci&key={KEY}")
        html = r.text
        ids = _ids(html)
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        ck(f"content/{k}: no duplicate element ids", not dupes, ", ".join(dupes[:4]))
        forms = set(re.findall(r'<form[^>]*\bid="([^"]+)"', html))
        wanted = set(re.findall(r'\bform="([^"]+)"', html))
        ck(f"content/{k}: every form= points at a real <form>",
           not (wanted - forms), ", ".join(sorted(wanted - forms)[:4]))
        ck(f"content/{k}: it is the section that rendered",
           f'class="subtab on"' in html and f'sub={k}' in html)

    # THE DIAGNOSTICS VIEWS. Systems check is a second page behind the same
    # tab, so checking `diagnostics` once checks half of it.
    from app.admin_ui import DIAG_VIEWS
    for v, label in DIAG_VIEWS:
        html = client.get(
            f"/admin/ui?tab=diagnostics&view={v}&tenant=baci&key={KEY}").text
        ids = _ids(html)
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        ck(f"diagnostics/{v}: no duplicate element ids", not dupes,
           ", ".join(dupes[:4]))
        forms = set(re.findall(r'<form[^>]*\bid="([^"]+)"', html))
        wanted = set(re.findall(r'\bform="([^"]+)"', html))
        ck(f"diagnostics/{v}: every form= points at a real <form>",
           not (wanted - forms), ", ".join(sorted(wanted - forms)[:4]))
        ck(f"diagnostics/{v}: it is the view that rendered",
           'class="subtab on"' in html and f"view={v}" in html)

    # A report about pages already published is not a decision, so it is not on
    # the decision queue.
    rev = client.get(f"/admin/ui?tab=content&tenant=baci&key={KEY}").text
    asr = client.get(f"/admin/ui?tab=assurance&tenant=baci&key={KEY}").text
    ck("compliance left the Review tab", "Live site compliance" not in rev)
    ck("…and is on Assurance, with its scan control",
       "Live site compliance" in asr and "compliance_scan" in asr)

    # The specific one, named, so a regression reads as itself rather than as
    # "some tab has a duplicate id".
    html = client.get(f"/admin/ui?tab=content&sub=pictures&tenant=baci&key={KEY}").text
    ck("the picture queue rendered at all (else the checks above prove nothing)",
       'name="asset_ids"' in html)
    ck("…and its checkboxes reach the approve/reject form",
       'form="picsform"' in html and 'id="picsform"' in html)

    print("\n" + ("all checks passed" if not _fails
                  else f"{len(_fails)} FAILED: " + "; ".join(_fails)))
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
