"""The Data layer tab: current with the models, and act-where-you-report.

Owner, 2026-08-23: "The Data Layer tab I believe is outdated and it doesnt allow
us to fix data layer issues from there, we have to navigate to the places where
the data layer tells us needs attention."

Both halves were true, and I measured them before changing anything: the page
rendered ZERO forms, ZERO buttons and ZERO body links — every number on it was a
dead end — and its table list was a literal that had drifted off the schema.

  1. THE TABLE LIST IS DERIVED. `KbAsset` — the photograph library, a whole
     table of the knowledge base — was not on the page, so the surface whose
     job is to show the shape of the data did not know the pictures existed.
     The lede already promised "read from the models, so a new column shows up
     here on its own": true of columns, false of tables. Membership now comes
     from the models and the PROSE stays hand-written, because "what this table
     is for" is the one thing introspection cannot produce.
  2. THE RANKED FIX LIST IS RENDERED. `resolve.readiness()` has always returned
     `next_actions`, already ordered by how many situations each fix releases
     and already naming where it lives — and its only two callers were a
     dossier and a JSON route. The console had an account-specific work list
     and showed a wall of row counts instead.

Run: python3 scripts/test_data_layer.py
"""
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'dl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui, db, kb, resolve, tenants  # noqa: E402
from app.web import app  # noqa: E402

KEY = "s3cret"
client = TestClient(app)
_fails = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def page(tenant="baci"):
    return client.get(f"/admin/ui?tab=schema&tenant={tenant}&key={KEY}").text


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— the table list follows the models —")
    derived = {n for n, _t, _h, _w in admin_ui._kb_tables()}
    models = {m.__name__ for m in db.Base.__subclasses__()
              if m.__name__.startswith("Kb") and hasattr(m, "tenant")}
    ck("every knowledge table is listed", derived == models,
       f"listed but not a model: {sorted(derived - models)}; "
       f"a model but not listed: {sorted(models - derived)}")
    ck("…including the photograph library, which the hand-written list missed",
       "KbAsset" in derived)
    ck("…and the vector index, which is derived data but still a table",
       "KbEmbedding" in derived)
    ck("every listed table carries a written description, not a placeholder",
       not [n for n, _t, h, _w in admin_ui._kb_tables() if h == n],
       str([n for n, _t, h, _w in admin_ui._kb_tables() if h == n]))

    h = page()
    ck("the tables render on the page", "kb_assets" in h and "kb_claims" in h)

    print("\n— a new knowledge table would appear on its own —")
    # The point of deriving it: nobody has to remember. Asserted by asking the
    # deriver about the models rather than by trusting the literal underneath.
    described = {n for n, _t, _h, _w in admin_ui._KB_DESCRIBED}
    ck("the authored prose covers what exists today",
       described >= models, str(sorted(models - described)))
    # Asserted by REMOVING a description, not by reading the docstring. The
    # first version of this check ended in `or True`, which is not a check.
    _kept = admin_ui._KB_DESCRIBED
    try:
        admin_ui._KB_DESCRIBED = [r for r in _kept if r[0] != "KbClaim"]
        undescribed = {n: h for n, _t, h, _w in admin_ui._kb_tables()}
        ck("…and a table nobody has described still appears, named",
           undescribed.get("KbClaim") == "KbClaim", str(undescribed.get("KbClaim")))
        ck("…saying plainly that the sentence is missing, rather than "
           "inventing one", any("somebody has to write" in w
                                for n, _t, _h, w in admin_ui._kb_tables()
                                if n == "KbClaim"))
    finally:
        admin_ui._KB_DESCRIBED = _kept
    ck("…and the real list is restored afterwards",
       len(admin_ui._kb_tables()) == len(models))

    print("\n— the page acts now —")
    ck("the ranked fix list is on it", "What to fix, in order" in h)
    r = resolve.readiness("baci")
    top = (r.get("next_actions") or [{}])[0].get("fix", "")
    ck("…showing the highest-leverage fix first, from readiness()",
       bool(top) and top in h, top)
    ck("…with the number of situations it releases, so the order is arguable",
       "unblocks" in h)
    ck("…and a real link to where it is fixed", 'href="/admin/ui?tab=kb' in h)

    print("\n— it was a dead end before, and the counts still work —")
    ck("the row counts survived", "This account at a glance" in h)
    ck("the identifiers and relationships survived",
       "Identifiers" in h and "How the tables relate" in h)

    print("\n— an account with nothing blocking it says so —")
    kb.set_brand("baci", tone="Warm, precise.", positioning="Italian-designed.")
    kb.add_banned("baci", "made in Italy")
    for tag in list(kb.situations("baci"))[:2]:
        kb.add_objection("baci", f"About {tag}?", "Yes.", situations=[tag],
                         origin="human")
    h2 = page()
    acts = resolve.readiness("baci").get("next_actions") or []
    if acts:
        ck("still blocked, and it still names the top one",
           acts[0]["fix"] in h2, acts[0]["fix"][:50])
    else:
        ck("nothing blocking, and the page says that rather than showing an "
           "empty list", "Nothing is blocking" in h2)

    print("\n— all accounts is not an account —")
    every = page("*")
    ck("the pooled view refuses rather than mixing clients' schemas",
       "Pick an account" in every and "What to fix" not in every)

    print("\n" + ("all checks passed" if not _fails
                  else f"{len(_fails)} FAILED: " + "; ".join(_fails)))
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
