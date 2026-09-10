"""Whether an account can put a picture on anything, as a number.

Owner, 2026-09-10: *"So what are we going to do about emails and blogs
continuing to not have images as intended?"*

The plumbing turned out to be sound at both ends — the blog run attaches its
hero to the output, the approval executor joins it at publish time behind a
rights check, and the email renderer emits the image tag from the hero block.
What was missing was the ability to SEE why nothing arrives: a run that finds
nothing to illustrate with writes a note inside that one run, among a dozen
others, and moves on. So "our articles keep going out without pictures" was
something to notice across weeks rather than a number to look at.

And the two causes it can have are different jobs. An empty library is a
catalogue sync. A library of reference-only pictures is a rights problem no
sync touches — inspiration saved from elsewhere is not licensed for a page. An
undrawable brand is a board with nothing pinned. A single "no picture" note
cannot tell those apart; this counts them.

    python3 scripts/test_can_this_account_illustrate.py
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ci.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = (
    '{"baci": {"domain": "bacimilanousa.com", "platform": "shopify",'
    ' "creds_key": "baci", "database": "us"}}')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import admin_ui, creative, db, kb, keywords, systems, tenants  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    systems.create("baci", "blog")

    print("— an empty library is not a healthy account —")
    got = creative.can_illustrate("baci")
    ck("nothing on file reads as not ok, and names the job that fixes it",
       got["ok"] is False and got["publishable"] == 0
       and "catalogue sync" in got["why"], got["why"][:70])

    print("\n— and neither is a library of things we may not use —")
    kb.add_asset("baci", "https://cdn.example/pin.png", rights="reference",
                 title="somebody else's photograph")
    got = creative.can_illustrate("baci")
    ck("reference pictures are on file and still not publishable",
       got["ok"] is False and got["on_file"] == 1 and got["publishable"] == 0)
    ck("and the reason says rights, not absence",
       "reference material" in got["why"] and "catalogue sync" not in got["why"],
       got["why"][:80])

    print("\n— what a picker can reach is what this counts —")
    kb.add_asset("baci", "https://cdn.example/ours.png", rights="owned",
                 title="our jug on a table")
    got = creative.can_illustrate("baci")
    ck("one owned, reviewed picture makes the account able to illustrate",
       got["ok"] is True and got["publishable"] == 1, str(got["publishable"]))
    # THE SAME READ, not a second one. A count that could disagree with what a
    # run can actually reach would be worse than no count.
    ck("the number is the picker's own read, so the two cannot drift",
       got["publishable"] == len(kb.assets("baci", publishable_only=True,
                                           kind="image")))

    print("\n— a brand that can draw its own is able even with an empty shelf —")
    real = creative.drawable
    creative.drawable = lambda t, entity_key="", boards=(): True
    try:
        with db.SessionLocal() as s:
            for a in s.query(db.KbAsset).all():
                a.status = "retired"
            s.commit()
        got = creative.can_illustrate("baci")
        ck("drawing counts as being able to illustrate",
           got["ok"] is True and got["publishable"] == 0 and got["drawable"] is True)
    finally:
        creative.drawable = real
        with db.SessionLocal() as s:
            for a in s.query(db.KbAsset).all():
                a.status = "active"
            s.commit()

    print("\n— and the outcome, which is what was actually being complained about —")
    with db.SessionLocal() as s:
        s.add(db.Output(id="out-bare", tenant="baci", system_key="blog",
                        media_ids=[]))
        s.add(db.Output(id="out-shot", tenant="baci", system_key="blog",
                        media_ids=[a.id for a in s.query(db.KbAsset).all()
                                   if a.rights == "owned"]))
        s.commit()
    keywords.upsert("baci", "a bare article", source="t", status="published",
                    output_id="out-bare")
    keywords.upsert("baci", "an illustrated article", source="t",
                    status="published", output_id="out-shot")
    got = creative.can_illustrate("baci")
    ck("an article that went out with no usable picture is counted",
       got["published"] == 2 and got["published_without"] == 1
       and got["without"] == ["a bare article"], str(got.get("without")))

    with db.SessionLocal() as s:
        for a in s.query(db.KbAsset).filter(db.KbAsset.rights == "owned").all():
            a.rights = "reference"
        s.commit()
    got = creative.can_illustrate("baci")
    ck("a picture we may no longer use stops counting as one that shipped",
       got["published_without"] == 2,
       "the join is may_publish, not 'an id was attached'")
    with db.SessionLocal() as s:
        for a in s.query(db.KbAsset).filter(db.KbAsset.title.like("our%")).all():
            a.rights = "owned"
        s.commit()

    print("\n— it reaches the page, next to publishing and measuring —")
    ready = keywords.readiness("baci", probe=False)
    ck("readiness carries it", (ready.get("illustrate") or {}).get("ok") is True)
    # NOT A BLOCKER. An article without a picture is a worse article, not a
    # refused one, and gating planning on it would stop work over something a
    # catalogue sync fixes.
    #
    # COMPUTED FROM THE SOURCE, not compared between two runs. The obvious
    # version — take `ok` before and after removing every picture — passes
    # whether or not the verdict considers pictures, because on a test account
    # `ok` is already False for a reason of its own. An assertion that holds
    # either way is decoration; this reads the verdict's own expression.
    import ast
    tree = ast.parse(pathlib.Path(ROOT, "app", "keywords.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "readiness")
    verdict = [n for n in ast.walk(fn)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Subscript)
                       and getattr(t.slice, "value", None) == "ok"
                       and getattr(getattr(t, "value", None), "id", "") == "out"
                       for t in n.targets)]
    ck("readiness computes one verdict, and it is the one being read",
       len(verdict) == 1, f"{len(verdict)} assignments to out['ok']")
    expr = ast.unparse(verdict[0].value) if verdict else ""
    ck("the verdict does not consider whether there are pictures",
       "illustrate" not in expr, expr[:120])

    with db.SessionLocal() as s:
        for a in s.query(db.KbAsset).all():
            a.rights = "reference"
        s.commit()
    after = keywords.readiness("baci", probe=False)
    ck("and the fact is still reported, as its own answer",
       (after.get("illustrate") or {}).get("ok") is False
       and "reference material" in (after["illustrate"].get("why") or ""),
       str(after.get("illustrate", {}).get("why", ""))[:70])

    page = admin_ui.render_plan("s3cret", "baci", sub="architecture")
    line = re.search(r"<li>[^<]*<strong>Illustrating.{0,400}", page)
    ck("the Plan tab shows it as its own line", line is not None)
    ck("and the fact travels with the job that fixes it",
       line is not None and "reference material" in re.sub("<[^>]+>", "", line.group(0)),
       re.sub("<[^>]+>", " ", line.group(0))[:110] if line else "")

    with db.SessionLocal() as s:
        for a in s.query(db.KbAsset).all():
            a.status = "retired"
        s.commit()
    page = admin_ui.render_plan("s3cret", "baci", sub="architecture")
    ck("an account with nothing on file is offered the catalogue sync",
       "/admin/catalog_sync" in page and "store&#x27;s photographs" in page
       or "store's photographs" in page)

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
