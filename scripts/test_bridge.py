"""The skill bridge: can an outside skill run on this data layer safely?

The bridge exists so a Claude skill can draft from the KB instead of from its
own workbook copy. The danger it is designed against is that drafting in the
skill's own session happens OUTSIDE `Context.emit`, which is the only reason
any of this is safe. So the checks that matter here are not "does it return
data" — they are:

  · does anything in review leak into a bundle a customer-facing skill reads
  · does a banned claim written by a skill still get blocked
  · does a skill-written draft reach the ledger, passing or blocked
  · does the rung still decide how far a passing draft travels

Run: python3 scripts/test_bridge.py
"""
import os
import sys
import tempfile

_tmp = os.path.join(tempfile.mkdtemp(), "bridge.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ["APPROVAL_SECRET"] = "test-secret"
os.environ.setdefault("SHOPIFY_STORES_JSON",
                      '{"baci":{"domain":"b.myshopify.com","token":"shpat_x"}}')
os.environ.setdefault("GMAIL_ACCOUNTS_JSON",
                      '{"baci":{"refresh_token":"r","email":"b@x.com"}}')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, kb, ledger, systems, tenants  # noqa: E402
from app.web import app  # noqa: E402

KEY = "test-secret"
client = TestClient(app)
_fails: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()

    kb.set_brand("baci", tone="Warm, precise, never florid.")
    kb.add_banned("baci", "hand-decorated")
    kb.add_banned("baci", "made in Italy")
    # A tag must exist in the account's vocabulary first — `add_claim` refuses
    # unknown ones rather than inventing a situation nothing can select on.
    kb.add_situation("baci", "care", patterns=[["dishwasher"], ["clean"]],
                     origin="human")
    kb.add_claim("baci", "Every piece is dishwasher and microwave safe.",
                 "Tested to EN 12875-1.", ["care"], origin="human")
    # `status="pending"` is how a caller asks for a proposal — see `add_claim`.
    # `origin` alone does NOT hold something back, which is a trap: `add_audience`
    # decides review from `origin` via `prov.lands_approved`, `add_claim` decides
    # it from `status`. Writing this test with only `origin="harvest"` produced a
    # row that landed approved and looked exactly like a leak. Both real harvest
    # callers pass `status="pending"`; see DEFECTS §3.
    kb.add_claim("baci", "Our porcelain is fired at 1400C.",
                 "supplier deck, unverified", ["care"],
                 status="pending", origin="harvest")
    live = kb.claims("baci")
    assert live, "setup failed: no approved claim on file"
    claim_id = live[0].id

    print("— the brief a skill is handed —")
    r = client.get("/admin/agent_context",
                   params={"key": KEY, "tenant": "baci",
                           "utterance": "is this dishwasher safe?"}).json()
    ck("a skill can fetch a brief for one client", not r.get("error"),
       str(r.get("error", ""))[:80])
    ck("  it names which client it is acting for",
       r.get("acting_for", {}).get("name") == "Baci Milano USA",
       str(r.get("acting_for")))

    blob = str(r)
    ck("  approved proof is in the brief", "dishwasher and microwave" in blob)
    ck("  MATERIAL IN REVIEW IS NOT — a skill cannot quote what you have "
       "not approved", "1400C" not in blob,
       "unapproved claim leaked into a customer-facing bundle")
    ck("  the ban list travels with the brief", "hand-decorated" in blob)
    ck("  and the obligation to come back is stated in the payload",
       "agent_emit" in str(r.get("obligation", {})))
    ck("unknown clients are refused, not silently empty",
       bool(client.get("/admin/agent_context",
                       params={"key": KEY, "tenant": "nope"}).json().get("error")))
    # A fresh client on purpose: a successful call sets a 14-day `console`
    # session cookie, and `admin_key` accepts it on later requests. That is the
    # admin UI working as designed — but it means an authenticated client is
    # the wrong instrument for asking whether the door is locked.
    ck("the bridge is not open to the world",
       TestClient(app).get("/admin/agent_context",
                           params={"key": "wrong", "tenant": "baci"}
                           ).json().get("error") == "unauthorized")

    print("\n— the gate —")
    sysrow = systems.find("baci", "service_desk") or systems.create(
        "baci", "service_desk")
    systems.update(sysrow.id, autonomy="shadow")

    good = client.post("/admin/agent_emit", json={
        "tenant": "baci", "system_key": "service_desk",
        "body": "Yes — it is dishwasher and microwave safe.",
        "claim_ids": [claim_id], "require_citation": False}).json()
    ck("a clean draft passes", good.get("ok"), str(good.get("failures"))[:110])
    ck("  but shadow still refuses to send it", good.get("may_send") is False,
       good.get("disposition", ""))

    bad = client.post("/admin/agent_emit", json={
        "tenant": "baci", "system_key": "service_desk",
        "body": "Each piece is hand-decorated and made in Italy.",
        "require_citation": False}).json()
    ck("A SKILL THAT WRITES A BANNED CLAIM IS BLOCKED", bad.get("ok") is False,
       "the validator did not travel with the data")
    ck("  and told which rules, so the skill can fix it",
       len(bad.get("failures") or []) == 2, str(bad.get("failures"))[:110])
    ck("  may_send is false, so there is nothing to quote as permission",
       bad.get("may_send") is False)

    rows = ledger.recent("baci", "service_desk", 10)
    ck("both drafts reached the ledger", len(rows) >= 2, f"{len(rows)} rows")
    ck("  including the blocked one, with its reason",
       any(x.status == "blocked" and x.blocked_on for x in rows))

    print("\n— the rung decides how far a PASSING draft goes —")
    systems.update(sysrow.id, autonomy="auto")
    auto = client.post("/admin/agent_emit", json={
        "tenant": "baci", "system_key": "service_desk",
        "body": "Yes — it is dishwasher and microwave safe.",
        "require_citation": False}).json()
    ck("on auto, a passing draft may send", auto.get("may_send") is True,
       auto.get("disposition", ""))
    still_bad = client.post("/admin/agent_emit", json={
        "tenant": "baci", "system_key": "service_desk",
        "body": "Beautiful hand-decorated pieces.",
        "require_citation": False}).json()
    ck("ON AUTO, A FAILING DRAFT STILL MAY NOT — the validator outranks "
       "the rung", still_bad.get("may_send") is False,
       still_bad.get("disposition", ""))

    print("\n— reaching the registered skills —")
    cat = client.get("/admin/skill_catalogue",
                     params={"key": KEY, "tenant": "baci"}).json()
    keys = [s["key"] for s in cat.get("skills", [])]
    ck("the four skills are reachable over HTTP at last",
       {"catalog_compliance", "inbound_reply", "ad_copy"} <= set(keys),
       str(keys))
    ck("  each says whether it can run for this client",
       all("status" in s for s in cat.get("skills", [])))
    unknown = client.post("/admin/skill_run", json={
        "skill": "nope", "tenant": "baci"}).json()
    ck("an unknown skill is refused with the list of real ones",
       "available" in unknown, str(unknown)[:80])

    print()
    if _fails:
        print(f"{len(_fails)} FAILED:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print("all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
