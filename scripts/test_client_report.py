"""A client report is read off the record, not remembered.

Gomeh will send these. That is a higher bar than an internal dashboard: every
number needs a source, and anything that cannot be measured has to SAY SO
rather than be quietly left out. A report with a visible hole is recoverable; a
report that implies completeness it does not have is not.

What this locks:

  · Tool calls are recorded — the first thing in this system that says whether
    a client's own platforms were actually reached, as opposed to connected.
  · A failure keeps the provider's own words.
  · The ledger stores a SIZE and a verdict, never a payload. A tool result is
    the client's data, and a second copy of it here would have none of the
    scoping the first has.
  · Figures we cannot produce are named in the output with what would fix them.

    python3 scripts/test_client_report.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import assurance, client_report, db, tenants, toolcalls  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— an unmeasured window says so —")
    ck("no calls reports nothing recorded, not zero calls",
       "no tool call was recorded" in toolcalls.report("baci")["verdict"])

    print("— what a tool reached, and what it did not —")
    toolcalls.record("baci", "shopify_find_orders", ok=True, ms=120, bytes_back=900)
    toolcalls.record("baci", "shopify_find_orders", ok=False,
                     error="Shopify rejected that token.")
    toolcalls.record("baci", "read_email", ok=True, ms=80, bytes_back=400)
    rep = toolcalls.report("baci")
    ck("calls are counted per tool", rep["by_tool"]["shopify_find_orders"]["calls"] == 2)
    ck("  failures separately", rep["by_tool"]["shopify_find_orders"]["failed"] == 1)
    ck("  and latency is kept", rep["by_tool"]["shopify_find_orders"]["slowest_ms"] == 120)
    ck("a failing provider keeps ITS OWN words",
       "Shopify rejected that token." in rep["failing"][0]["last_error"],
       "'tool failed' sends somebody to a debugger; this sends them to reconnect")
    ck("  ranked by failure rate, so a broken connection is not buried",
       rep["failing"][0]["provider"] == "shopify")

    print("\n— the tool is mapped to the client's platform, not guessed —")
    ck("a scoped tool resolves to its provider",
       toolcalls.provider_for("shopify_find_orders") == "shopify")
    ck("  an inbox tool to google", toolcalls.provider_for("read_email") == "google")
    ck("a tool that touches only OUR tables has no provider",
       toolcalls.provider_for("run_skill") == "",
       "counting it would make a healthy report out of an account with "
       "nothing wired")
    ck("reached() counts only successes",
       toolcalls.reached("baci") == {"shopify": 1, "google": 1},
       str(toolcalls.reached("baci")))

    print("\n— the ledger holds no payload —")
    with db.SessionLocal() as s:
        row = s.query(db.ToolCall).filter(db.ToolCall.ok == "yes").first()
        cols = {c.name for c in db.ToolCall.__table__.columns}
    ck("there is no column a result body could go in",
       not ({"result", "body", "payload", "data", "response"} & cols),
       "a tool result is the client's own data; a second copy here would have "
       "none of the scoping the first one has")
    ck("  only its size is kept", row.bytes_back == "900")

    print("\n— the report joins our work to their systems —")
    assurance.record("baci", source="skill", checked=["banned_claims"],
                     caught=["banned_claim"], verdict="blocked", grounded=True)
    rep = client_report.assemble("baci", 30)
    ck("it names the account", rep["account"]["name"] == "Baci Milano USA")
    ck("the period is explicit", rep["period"]["days"] == 30 and rep["period"]["from"])
    ck("a catch appears — the one number that needs no interpretation",
       rep["assurance"]["caught_total"] == 1)
    ck("which platforms were READ, not which are connected",
       rep["reach"]["platforms_read"].get("shopify") == 1,
       "'connected' is a fact about a settings page")
    ck("and the failing one is surfaced", rep["reach"]["failing"])

    print("\n— what it cannot say, it says —")
    un = {u["figure"] for u in rep["not_yet_measured"]}
    ck("quality change is named as unmeasured",
       any("quality change" in f for f in un))
    ck("  revenue too, with the reason", any("revenue" in f for f in un))
    ck("every gap carries a fix",
       all(u.get("fix") for u in rep["not_yet_measured"]),
       "a to-do the next person can delete, not a paragraph nobody updates")
    ck("an unknown account is refused by name",
       "no account keyed" in client_report.assemble("nobody")["error"])

    print("\n— accounts do not see each other —")
    toolcalls.record("eien", "read_email", ok=True)
    ck("baci's report excludes eien's calls",
       client_report.assemble("baci", 30)["reach"]["calls"] == 3,
       str(client_report.assemble("baci", 30)["reach"]["calls"]))

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
