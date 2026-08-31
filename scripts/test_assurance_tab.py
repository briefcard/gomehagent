"""The Assurance tab, step 4 (spec §9) — the page whose whole job is believing.

Four things it did not do, each measured before it was changed:

  · **Every section opened at once**, so the page was a wall rather than
    something you choose to read. Folded now — and the catch COUNT rides on
    the summary, because a closed fold that hides its own number is worse
    than an open one on the page that exists to show the layer caught
    something.
  · **The catch list was capped at 40 with no page two and no statement that
    there was more.** On an account busy enough to be worth checking, catch
    41 did not exist. A silent cap on the believability page is the "no
    silent caps" rule broken where it matters most.
  · **A catch showed 400 characters of the draft and no way to reach it.**
    The workroom is where it is read whole, corrected or redrafted.
  · **The all-accounts view offered no scan at all** — it said "pick an
    account to see and run it", which is a fix instruction where a control
    belongs (design rule 1). The pooled REPORT genuinely cannot exist; the
    RUN is per account and now sits here with its last-run state.

    python3 scripts/test_assurance_tab.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'at.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (admin_ui, assurance, db, kb_seed,  # noqa: E402
                 systems, tenants)

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    systems.seed_from_tenants()

    # 30 catches: more than one page, so paging is a real question and not a
    # check that passes against emptiness (design rule 11).
    for i in range(60):
        assurance.record("baci", source="skill", checked=["banned_claims"],
                         caught=["banned_claims"] if i % 2 else [],
                         verdict="blocked" if i % 2 else "passed",
                         system_key="blog" if i % 3 else "campaign_email",
                         output_id=f"o{i}")
    total = len(assurance.catches("baci", 30, limit=9999))
    ck("the fixture actually has more than one page of catches", total > 20,
       str(total))

    page1 = admin_ui.render_assurance("s3cret", "baci")
    page2 = admin_ui.render_assurance("s3cret", "baci", page=2)

    # ── 1. folds fold, and the number survives the fold ────────────────────
    print("\n— folds fold (spec §9) —")
    ck("no section on this tab opens itself",
       'class="conns" open' not in page1,
       "every one open at once is a wall, not a page")
    ck("the catch count rides on the summary, so folding hides no number",
       re.search(r"What was caught &mdash; \d+", page1) is not None)

    # ── 2. the drill filter says it is on, and offers the way out ──────────
    print("\n— a filtered view says so —")
    drilled = admin_ui.render_assurance("s3cret", "baci", rule="banned_claims")
    ck("a narrowed page says what it is narrowed to",
       "Showing only" in drilled and "banned_claims" in drilled)
    ck("…and carries the way back to everything",
       "show everything" in drilled)

    # ── 3. catches paginate, and each opens the draft it caught ────────────
    print("\n— no silent cap on the page that has to be believed —")
    ck("the catch list pages", "page=2" in page1)
    ck("the pager states the depth in the one pager vocabulary",
       re.search(r"catches \d+&ndash;\d+ of \d+", page1) is not None,
       "X–Y of N, newer/older — the same words as every other queue")
    ck("page two is a different page, not the same one re-rendered",
       page1 != page2)
    first_ids = set(re.findall(r"/admin/work/(o\d+)", page1))
    second_ids = set(re.findall(r"/admin/work/(o\d+)", page2))
    ck("…and holds catches the first page did not",
       bool(second_ids) and not (second_ids & first_ids),
       f"p1={len(first_ids)} p2={len(second_ids)} overlap="
       f"{len(second_ids & first_ids)}")
    ck("every catch opens the draft it caught",
       "open the draft it caught" in page1,
       "400 characters and no way through is half a control")

    # ── 4. the all-accounts view can RUN a scan ────────────────────────────
    print("\n— a control, not an instruction to go elsewhere —")
    every = admin_ui.render_assurance("s3cret", "*")
    n_scan = every.count("/admin/compliance_scan")
    ck("the * view carries one scan per account",
       n_scan >= len(tenants.all_tenants()), f"{n_scan} controls")
    ck("…and says when each last ran, so the button is not a guess",
       "never scanned" in every or "ran " in every)
    ck("it still refuses to POOL what cannot be pooled",
       "nothing to pool here" in every,
       "one client's ban list against another client's site is not a number")

    # The single-account view is unchanged in what it offers.
    ck("a single account still has its own Scan now",
       "Scan now" in page1)

    print()
    print("\n— every gap number OPENS the runs behind it —")
    # `catches()` filters on `r.caught`, so the existing drill-down could only
    # ever reach runs that failed a RULE. A run that drafted with no reader and
    # no objections and then passed every gate cleanly was unreachable — and
    # those are the runs most worth opening: nothing is wrong with the words,
    # the brief was thinner than the account could have supplied.
    from app import ledger as _led
    _o = _led.record("baci", "campaign_email", format="campaign_email",
                     status="draft", body="Written for nobody in particular.")
    assurance.record("baci", source="skill", checked=["banned_claims"],
                     caught=[], verdict="passed", system_key="campaign_email",
                     output_id=_o.id, thin=["reader:not-chosen"])
    _runs = assurance.thin_runs("baci", 30, gap="reader:not-chosen")
    ck("thin_runs reaches a run that caught nothing", len(_runs) >= 1,
       "catches() cannot: it filters on r.caught")
    _page = admin_ui.render_assurance("s3cret", "baci")
    ck("the per-system gap is a link, not a dead number",
       "gap=reader:not-chosen" in _page, "a number you cannot open is faith")
    _d = admin_ui.render_assurance("s3cret", "baci", gap="reader:not-chosen")
    ck("  and it opens the runs behind it",
       "Runs that drafted without" in _d and "nobody in particular" in _d,
       "the draft itself, not just a count")
    ck("  saying plainly that nothing was caught",
       "passed every rule" in _d,
       "a thin run reading as a caught one would be the same conflation "
       "this module keeps apart everywhere else")
    ck("  with a way through to the artifact",
       "open what it produced" in _d,
       "400 characters you cannot act on is half a control")

    print("\n— can the knowledge be navigated, or only rotated through —")
    # Volume is not usefulness. An untagged brand-wide claim is selectable
    # whenever nobody asks for a situation — which for a campaign or an
    # article is always — so once there are more of those than fit the window,
    # selection can only ROTATE. The owner must not be left to infer that;
    # authoring MORE proof is the natural response to thin copy and the one
    # that makes it worse.
    from app import kb as _kbn
    _kbn.ensure_brand("navtest", "Nav")
    _kbn.set_brand("navtest", positioning="p", tone="warm")
    _kbn.add_banned("navtest", "nope")
    for i in range(20):
        _kbn.add_claim("navtest", f"Untagged claim {i:02d}.", f"ev {i}", [],
                       origin="human", status="active")
    n = assurance.navigability("navtest")
    ck("navigability counts what can never be narrowed",
       n["claims_unnarrowable"] == 20 and n["claims_offered"] == 6, str(n))
    ck("  and says selection is rotating", n["rotating"] is True, str(n))
    page = admin_ui.render_assurance("s3cret", "navtest")
    ck("it renders on an account with NO checks recorded",
       "Can it be navigated" in page,
       "the accounts most likely to need this are the ones that have "
       "authored plenty and produced little")
    ck("  and names the fix as tagging, not authoring",
       "authoring more will not help" in page and "Tag them" in page,
       "a number with no control is a number you cannot act on")

    _kbn.add_situation("navtest", "gifting", patterns=[["gift"]],
                       description="a gift", origin="seed")
    for c in _kbn.claims("navtest"):
        _kbn.update_claim(c.id, tags=["gifting"])
    ck("tagging what is on file flips it",
       assurance.navigability("navtest")["rotating"] is False,
       "the number has to be able to move, or it is decoration")
    ck("  and the card says so rather than going quiet",
       "chooses rather than rotates" in
       admin_ui.render_assurance("s3cret", "navtest"),
       "silence reads as unmeasured")

    print("\n— WHICH system ran blind, not just that something did —")
    # `thin` has been on every assurance row since the column was added, and
    # `report()` counts it ACCOUNT-WIDE, top ten. That answers "is anything
    # missing" and never "which system is drafting without it" — a campaign
    # writing with no objections and an article writing with all of them were
    # one number and nothing separated them. `system_key` was on the row.
    assurance.record("baci", source="skill", checked=["banned_claims"],
                     caught=[], verdict="passed", system_key="campaign_email",
                     thin=["funnel:situation:doubt"])
    rows = {e["system"]: e for e in assurance.by_system("baci", 30)}
    ce = rows.get("campaign_email", {})
    ck("by_system carries what a system was drafting without",
       ce.get("thin_runs", 0) >= 1 and ce.get("top_thin"),
       str(ce.get("top_thin")))
    ck("  and separates it from the systems that were not thin",
       rows.get("blog", {}).get("thin_runs", 0) == 0,
       "an account-wide count cannot tell these two apart")
    page = admin_ui.render_assurance("s3cret", "baci")
    ck("the tab renders the column", "drafting without" in page)
    ck("  with the gap named against its system",
       "funnel:situation:doubt" in page, "the number is useless without it")
    ck("  and says a clean system is clean, not blank",
       "nothing missing" in page,
       "blank reads as unmeasured; those are different facts")


    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
