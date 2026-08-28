"""The triage tab stops contradicting itself.

`test_diagnostics.py` covers classification and scoping and PASSES today —
because its fixture holds far fewer than 200 events, so the cap it would have
to reach never bites. That is design rule 11 in the one place it costs most: a
check run against a fixture too small to trigger the defect proves nothing
about the defect.

The headline, found 2026-08-28 and reproduced here: a window holding 253
events with 3 FAILURES older than the newest 200 rendered, on `level=fail`,
the sentence *"nothing at all was recorded for this account in the window — no
run, no tool call, no check and no approval. That is a finding about the
plumbing, not a clean report"* — on the same page whose Platforms table showed
`shopify 3 3 100% 401 invalid token`. The tab whose whole job is to say
whether anything is broken called a broken account silent, in the direction of
reassurance.

Everything seeded here is sized to reach the thing it tests.

    python3 scripts/test_diagnostics_surface.py
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ds.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (admin_ui, db, diagnostics, kb_seed,  # noqa: E402
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
    now = db.utcnow()

    # ── the seed that makes the cap bite ──────────────────────────────────
    # 3 failures FIVE DAYS BACK (older than the newest 200) + 250 clean calls
    # in the last few hours. Anything under 200 total proves nothing here.
    with db.SessionLocal() as s:
        for i in range(3):
            s.add(db.ToolCall(tenant="baci", tool="shopify.products",
                              source="skill", provider="shopify", ok="no",
                              error="401 invalid token", ms="300",
                              at=now - dt.timedelta(days=5, minutes=i)))
        for i in range(250):
            s.add(db.ToolCall(tenant="baci", tool="shopify.products",
                              source="skill", provider="shopify", ok="yes",
                              ms="120", at=now - dt.timedelta(minutes=i)))
        s.commit()

    print("— the counts describe the WINDOW, not the newest slice —")
    rep = diagnostics.report("baci", 7, level="fail")
    ck("the fixture reaches past the 200 cap",
       rep["window_total"] > 200, str(rep["window_total"]))
    ck("the failures chip counts the window", rep["counts"]["fail"] == 3,
       str(rep["counts"]["fail"]))
    ck("the clean chip counts the window", rep["counts"]["ok"] == 250,
       str(rep["counts"]["ok"]))
    ck("total / shown / limit are three different, stated numbers",
       (rep["total"], rep["shown"], rep["limit"]) == (3, 3, 200),
       str((rep["total"], rep["shown"], rep["limit"])))

    print("\n— silent means NOTHING WAS RECORDED, never 'your filter is empty' —")
    page_fail = admin_ui.render_diagnostics("s3cret", "baci", level="fail")
    ck("a filtered page does not call a busy account silent",
       "nothing at all was recorded" not in page_fail)
    ck("…and it shows the failures it filtered to",
       "401 invalid token" in page_fail)
    row = re.search(r"<tr><td>shopify</td>.*?</tr>", page_fail, re.S)
    ck("the same page's Platforms row still names them — the contradiction "
       "that started this is gone from BOTH halves",
       row is not None and "401 invalid token" in row.group(0)
       and ">3<" in row.group(0),
       (row.group(0)[:120] if row else "no shopify row"))
    ck("`silent` is about the window, not the filter", rep["silent"] is False)

    # A filter that genuinely matches nothing says THAT, not "broken plumbing".
    empty = diagnostics.report("baci", 7, level="warn")
    ck("an empty filter over a busy window is flagged as an empty FILTER",
       empty["empty_filter"] is True and empty["silent"] is False,
       f"empty_filter={empty['empty_filter']} silent={empty['silent']}")

    # And a genuinely empty account still reports broken plumbing.
    quiet = diagnostics.report("coverings", 1)
    ck("an account with nothing recorded is still called out",
       quiet["silent"] is True and "plumbing" in quiet["note"])

    print("\n— no silent caps: the page says how many, and offers the rest —")
    with db.SessionLocal() as s:
        for i in range(400):
            s.add(db.ToolCall(tenant="eien", tool="omnisend.send", source="skill",
                              provider="omnisend", ok="yes", ms="80",
                              at=now - dt.timedelta(minutes=i)))
        s.commit()
    page = admin_ui.render_diagnostics("s3cret", "eien")
    ck("the cap states BOTH numbers", "Showing 200 of 400" in page, "")
    ck("…and carries the control that raises it",
       "limit=500" in page and "limit=1000" in page,
       "a cap with no way past it is the defect, not the number")
    wide = admin_ui.render_diagnostics("s3cret", "eien", limit=1000)
    ck("raising it actually shows more",
       wide.count('class="row') > page.count('class="row')
       or "All 400" in wide, "")
    ck("a raised limit SURVIVES the next click — every link carries it",
       "limit=1000" in wide,
       "a hand-typed limit that the next chip reverts is not a control")

    print("\n— the reader never loses their room —")
    sysv = admin_ui.render_diagnostics("s3cret", "baci", view="systems")
    hrefs = re.findall(r'href="(/admin/ui\?[^"]+)"', sysv)
    # This tab's OWN controls, which all carry the window. The sidebar's
    # account switcher is built by `_shell` and carries no `days` — keeping a
    # room across an account switch is a frame question, not this tab's, and
    # widening the assertion to cover it would be testing another surface.
    diag_links = [h for h in hrefs
                  if "tab=diagnostics" in h and "days=" in h]
    ck("the sweep found a real population of links", len(diag_links) > 5,
       str(len(diag_links)))
    # Every link states a room. The rail's own "Overview" link correctly
    # names the OTHER room — that is the one link on the page whose job is to
    # change it — so the assertion is "carries a room", and separately that
    # the FILTER controls keep this one.
    ck("every control on the page states which room it lands in",
       all("sub=" in h for h in diag_links),
       "; ".join(h for h in diag_links if "sub=" not in h)[:160])
    filters = [h for h in diag_links if "sub=overview" not in h]
    ck("…and every filter keeps the reader in Systems check",
       len(filters) > 3 and all("sub=systems" in h for h in filters),
       f"{len(filters)} filter links")
    ck("the theme toggle keeps it too — a display preference must not cost "
       "the reader their place",
       "&amp;sub=systems" in sysv)

    print("\n— every named gap reaches a tab that can CLEAR it —")
    emitted = {w for _k, _l, w, _n in systems.ATTENTION_KINDS}
    known = set(admin_ui._FIX_WHERE)
    ck("every `where` a reason can classify to has a destination",
       emitted <= known, f"unrouted: {sorted(emitted - known)}")
    ck("…and no destination is declared that nothing emits",
       known <= emitted, f"dead keys: {sorted(known - emitted)}")
    ck("the ban-list class routes to Brand, which is where the rule is added",
       admin_ui._FIX_WHERE.get("brand", ("", ""))[0] == "Brand")
    ck("the compliance class routes to Assurance, which can scan and clear it",
       admin_ui._FIX_WHERE.get("assurance", ("", ""))[0] == "Assurance")

    print("\n— one list, one number —")
    with db.SessionLocal() as s:
        for i, reason in enumerate(("no_ban_list", "no_ban_list",
                                    "coherence: two subjects")):
            s.add(db.SystemRun(tenant="baci", system_id="", stage="draft",
                               blocked_on=[reason],
                               created_at=now - dt.timedelta(hours=i + 1)))
        s.commit()
    need = systems.attention("baci", 7)
    room = admin_ui.render_diagnostics("s3cret", "baci", view="systems")
    m = re.search(r'<span class="cnt">(\d+)</span>', room)
    ck("the rail chip counts the same things the room renders",
       m is not None and int(m.group(1)) == len(need),
       f"rail={m.group(1) if m else '-'} distinct={len(need)}")

    print("\n— money is money —")
    # `Usage` stores TOKENS and `usage.report` computes the cost, so an exact
    # figure cannot be seeded. What is asserted is the property that was
    # broken: a bare float reached the page, printing "$12.5" for a $12.50
    # bill and "$0.0" next to "model calls 1" for real sub-cent spend.
    with db.SessionLocal() as s:
        s.add(db.Usage(tenant="ironside", purpose="draft",
                       model="claude-opus-5",
                       input_tokens="900000", output_tokens="200000",
                       at=now - dt.timedelta(hours=1)))
        s.add(db.Usage(tenant="coverings", purpose="classify",
                       model="claude-haiku-4-5-20251001",
                       input_tokens="1", output_tokens="1",
                       at=now - dt.timedelta(hours=1)))
        s.commit()
    big = admin_ui.render_diagnostics("s3cret", "ironside", days=7)
    ck("a real bill renders with exactly two decimals",
       re.search(r"\$\d[\d,]*\.\d\d", big) is not None
       and not re.search(r"\$\d+\.\d</", big),
       (re.search(r"\$[\d,.]+", big) or ["none"])[0])
    tiny = admin_ui.render_diagnostics("s3cret", "coverings", days=7)
    ck("sub-cent spend says so instead of printing $0.00 beside a real call",
       ("&lt; $0.01" in tiny) or ("no model call" in tiny),
       "a number that reads as free beside evidence it was not is the defect")
    ck("the projection is suppressed at 30d, where it is the same number",
       "projected / month" not in
       admin_ui.render_diagnostics("s3cret", "ironside", days=30))
    ck("…and present at 7d, where it is a different one",
       "projected / month" in big)

    print("\n— wide tables scroll inside themselves —")
    for label, html in (("overview", admin_ui.render_diagnostics("s3cret", "baci")),
                        ("systems check", room)):
        seg = html
        bare = [m.start() for m in re.finditer(r'<table class="tbl"', seg)
                if "tblwrap" not in seg[max(0, m.start() - 140):m.start()]]
        ck(f"no unwrapped table on {label}", not bare, f"{len(bare)} bare")

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
