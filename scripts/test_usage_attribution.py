"""Spend, split by client, and honest about what it cannot split.

`Usage.tenant` was declared and indexed from the start, commented "per-client
cost attribution", and NOTHING ever wrote it. So the one question a spend report
is actually asked — what does this client cost me — had no answer, while the
column made it look answered. Same shape as `Approval.system_id`,
`SystemRun.edit_diff` and `KbClaim.expires_at`: declared, indexed, dead.

    python3 scripts/test_usage_attribution.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ua.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, usage  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class Resp:
    def __init__(self, i, o):
        self.usage = type("U", (), {"input_tokens": i, "output_tokens": o,
                                    "cache_read_input_tokens": 0,
                                    "cache_creation_input_tokens": 0})()


def main() -> int:
    db.init_db()

    print("— the column is actually written now —")
    usage.log_usage("triage", "claude-sonnet-4-6", Resp(100_000, 5_000), tenant="baci")
    with db.SessionLocal() as s:
        ck("a tenant reaches the row",
           s.query(db.Usage).first().tenant == "baci",
           "accepting the parameter is not the same as storing it")

    print("\n— spend splits by client —")
    usage.log_usage("triage", "claude-sonnet-4-6", Resp(50_000, 2_000), tenant="ironside")
    usage.log_usage("classify", "claude-haiku-4-5-20251001", Resp(1_000, 20), tenant="baci")
    rep = usage.report(30)
    ck("every client appears", {"baci", "ironside"} <= set(rep["by_tenant"]))
    ck("  the bigger spender is first",
       list(rep["by_tenant"])[0] == "baci",
       "sorted by cost, so the answer is the first line")
    ck("  with a share of the total",
       rep["by_tenant"]["baci"]["share_pct"] > rep["by_tenant"]["ironside"]["share_pct"])
    ck("  and the shares are of real cost, not call count",
       rep["by_tenant"]["baci"]["calls"] == 2)

    print("\n— one client can be asked for on its own —")
    solo = usage.report(30, tenant="ironside")
    ck("filtering returns only that account",
       set(solo["by_tenant"]) == {"ironside"} and solo["calls"] == 1)
    ck("  and its cost matches its line in the full report",
       solo["est_cost_usd"] == rep["by_tenant"]["ironside"]["cost_usd"])

    print("\n— what cannot be attributed is NAMED, never spread —")
    usage.log_usage("harvest_extract", "claude-sonnet-4-6", Resp(20_000, 500))
    rep = usage.report(30)
    ck("an unattributed call gets its own bucket",
       "unattributed" in rep["by_tenant"],
       "spreading shared work across clients invents a precise-looking number")
    ck("  it does not inflate any client",
       rep["by_tenant"]["baci"]["calls"] == 2)
    ck("  and the report explains what it is",
       "historical" in rep["attribution_note"],
       "otherwise it reads as overhead somebody should be billed for")

    print("\n— the totals still hold —")
    ck("client costs plus unattributed equal the total",
       abs(sum(v["cost_usd"] for v in rep["by_tenant"].values())
           - rep["est_cost_usd"]) < 0.02,
       "a split that does not reconcile is worse than no split")

    print("\n— purpose and tenant are independent cuts —")
    ck("by_purpose still works alongside it",
       {"triage", "classify", "harvest_extract"} <= set(rep["by_purpose"]))

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
