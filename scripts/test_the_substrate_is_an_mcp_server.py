"""The data layer is an MCP server: three tools behind one key, nothing leaves.

Owner, 2026-10-22: stop building generators inside the app; expose the data
layer as an MCP layer that scheduled automation calls, with Claude as the
generator. `app/mcp_server.py` is that layer, v1 — get_package, check, record.

What this suite holds:
  * the door is shut without the key, with the wrong key, and when MCP_KEY is
    unset (fails closed, like READ_KEY);
  * the live tool list IS `mcp_server.TOOLS`, read over the wire;
  * get_package carries the ban list, the claim WITH ITS ID, the audience, the
    product, the deliverable spec and the rules, and NAMES what is missing;
  * check catches a banned claim written with a space instead of the hyphen,
    reports an uncited draft, and passes a clean cited one;
  * record of a blocked draft files a blocked ledger row and NO approval;
    record of a clean draft files one row, one artifact, ONE pending
    `skill_output` approval, and the workroom opens it;
  * no approval `record` writes carries a key `approvals.apply_decision`
    executes — computed from that function's source, not from a list here;
  * the app can start twice (a restart) and /mcp still answers.

Mutation run before this was committed (the assertion-discipline rule): the
bearer compare was changed to accept any non-empty token, and the first and
third checks went red. Reverted.
"""
from __future__ import annotations

import inspect
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'm.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
os.environ["MCP_KEY"] = "mcp-test-key"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import approvals, config, db, kb, mcp_server, systems, tenants, web  # noqa: E402

_fail: list = []
T = "baci"
CLAIM = "Designed in Milan by the Italian design house Baci Milano."
KEY = "mcp-test-key"
ACCEPT = "application/json, text/event-stream"


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class Rpc:
    """JSON-RPC over the Streamable HTTP route — the wire, not the SDK."""

    def __init__(self, client, key=KEY):
        self.c, self.key, self.n = client, key, 0

    def post(self, method, params=None, *, notify=False):
        self.n += 1
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            msg["id"] = self.n
        headers = {"Accept": ACCEPT, "Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        return self.c.post("/mcp", json=msg, headers=headers)

    def open(self):
        r = self.post("initialize", {"protocolVersion": "2025-06-18",
                                     "capabilities": {},
                                     "clientInfo": {"name": "suite", "version": "0"}})
        self.post("notifications/initialized", notify=True)
        return r

    def call(self, name, args):
        r = self.post("tools/call", {"name": name, "arguments": args})
        return r.json()["result"]


def _text(result) -> str:
    return "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.add_claim(T, CLAIM, "brand file", [], origin="human", status="active")
    kb.add_banned(T, "hand-decorated")
    kb.add_audience(T, "hosts", "Hosts who entertain", ["dull tables"], ["a table worth a photo"])
    kb.add_entity(T, "product", "portofino", "Portofino dinner set")
    claim_id = next(c.id for c in kb.claims(T) if c.claim == CLAIM)
    sysrow = systems.find(T, "campaign_email") or systems.create(T, "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, sysrow.id).status = "live"
        s.commit()

    with TestClient(web.app) as c:
        print("— the door —")
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Accept": ACCEPT})
        ck("no key → 401", r.status_code == 401, str(r.status_code))
        r = Rpc(c, key="wrong").post("tools/list")
        ck("wrong key → 401, and the body says how to present it",
           r.status_code == 401 and "Authorization: Bearer" in r.text, r.text[:120])
        saved, config.MCP_KEY = config.MCP_KEY, ""
        r = Rpc(c).post("tools/list")
        ck("MCP_KEY unset → even the right key is refused (fails closed)",
           r.status_code == 401 and "not set" in r.text, r.text[:120])
        config.MCP_KEY = saved
        h = c.get("/health").json()
        ck("keyless /health says the door is keyed", h.get("mcp") == "keyed", str(h.get("mcp")))

        print("— the handshake and the tool list —")
        rpc = Rpc(c)
        r = rpc.open()
        ck("initialize answers with the server's name",
           r.status_code == 200 and r.json()["result"]["serverInfo"]["name"] == mcp_server.NAME,
           r.text[:200])
        names = sorted(t["name"] for t in rpc.post("tools/list").json()["result"]["tools"])
        ck("the live tool list IS mcp_server.TOOLS", names == sorted(mcp_server.TOOLS), str(names))

        print("— get_package —")
        pkg = _text(rpc.call("get_package", {"tenant": T, "system": "campaign_email",
                                             "entity_key": "portofino", "audience_key": "hosts"}))
        ck("carries the ban list", "hand-decorated" in pkg)
        ck("carries the claim WITH its id", CLAIM in pkg and claim_id in pkg)
        ck("carries the audience in the buyer's words", "dull tables" in pkg)
        ck("carries the product", "Portofino dinner set" in pkg)
        ck("carries the deliverable spec and the rules",
           "### What to hand back" in pkg and "{{UNSUBSCRIBE}}" in pkg and "### The rules" in pkg)
        ck("names what is missing instead of inventing it",
           "## What is missing" in pkg and "voice" in pkg.lower())
        bad = _text(rpc.call("get_package", {"tenant": "nobody"}))
        ck("an unknown account is refused by name", "unknown account" in bad and "baci" in bad)
        bad = _text(rpc.call("get_package", {"tenant": T, "system": "nope"}))
        ck("an unknown system is refused with the known ones", "unknown system" in bad and "campaign_email" in bad)

        print("— check —")
        body_banned = "<p>Hand decorated in Italy, for your table.</p>"
        v = rpc.call("check", {"tenant": T, "body": body_banned, "kind": "email",
                               "subject": "A table worth a photo"})["structuredContent"]
        rules = {b["rule"] for b in v["blocks"]}
        ck("a banned claim is caught ACROSS the hyphen", not v["ok"] and "banned_claim" in rules, str(rules))
        ck("an uncited draft is a block, with a fix", "uncited" in rules
           and all(b.get("fix") for b in v["blocks"]))
        ck("every gate ran", {"rules", "structure", "craft", "fitness", "coherence"} <= set(v["checked"]),
           str(v["checked"]))
        clean = f"<p>{CLAIM} <a href='https://bacimilanousa.com/products/portofino'>Portofino</a>.</p>"
        v = rpc.call("check", {"tenant": T, "body": clean, "kind": "email",
                               "subject": "Portofino, for the table", "claim_ids": [claim_id],
                               "entity_key": "portofino"})["structuredContent"]
        ck("a clean, cited draft passes", v["ok"], str(v["blocks"]))
        long_subject = "one two three four five six seven eight nine ten eleven twelve thirteen"
        v = rpc.call("check", {"tenant": T, "body": clean, "kind": "email",
                               "subject": long_subject, "claim_ids": [claim_id]})["structuredContent"]
        ck("craft nudges ride as advice, not blocks",
           v["ok"] and any("subject_length" in a["rule"] for a in v["advice"]), str(v["advice"])[:160])

        print("— record —")
        with db.SessionLocal() as s:
            before_out = s.query(db.Output).count()
            before_ap = s.query(db.Approval).count()
        got = rpc.call("record", {"tenant": T, "system": "campaign_email", "body": body_banned,
                                  "subject": "x"})["structuredContent"]
        with db.SessionLocal() as s:
            row = s.get(db.Output, got["output_id"])
            aps = s.query(db.Approval).count()
        ck("a blocked draft is recorded as blocked and queues NOTHING",
           not got["ok"] and got["status"] == "blocked" and row is not None
           and row.status == "blocked" and aps == before_ap and got["approval_id"] == "",
           f"status={got['status']} approvals={aps - before_ap}")
        got = rpc.call("record", {"tenant": T, "system": "campaign_email", "body": clean,
                                  "subject": "Portofino, for the table", "preheader": "Set the table",
                                  "claim_ids": [claim_id], "entity_key": "portofino",
                                  "audience_key": "hosts", "notes": "no price on file"})["structuredContent"]
        with db.SessionLocal() as s:
            row = s.get(db.Output, got["output_id"])
            art = s.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == got["output_id"]).first()
            new_aps = [a for a in s.query(db.Approval).all() if (a.payload or {}).get("output_id") == got["output_id"]]
            outs = s.query(db.Output).count()
        ck("a clean draft files ONE ledger row (draft, esp_campaign) with the whole artifact beside it",
           got["ok"] and row is not None and row.status == "draft" and row.format == "esp_campaign"
           and art is not None and art.body == clean and outs == before_out + 2)
        ck("…and ONE pending skill_output approval, scoped to the account",
           len(new_aps) == 1 and new_aps[0].kind == "skill_output" and new_aps[0].status == "pending"
           and new_aps[0].tenant == T and new_aps[0].id == got["approval_id"],
           f"{len(new_aps)} approval(s)")
        ck("the review_url is the workroom on the public base",
           got["review_url"] == f"https://example.test/admin/work/{got['output_id']}", got["review_url"])
        r = c.get(f"/admin/work/{got['output_id']}?key=s3cret")
        ck("the workroom opens it", r.status_code == 200 and "Portofino" in r.text, str(r.status_code))

        print("— the trust boundary, computed —")
        src = inspect.getsource(approvals.apply_decision)
        executes = set(re.findall(r'\.get\("([a-z_]+)"\)', src)) & {"esp_push", "gbp_post", "send_mail"}
        ck("mcp_server.EXECUTOR_KEYS is exactly what apply_decision executes",
           executes and executes == set(mcp_server.EXECUTOR_KEYS), f"{executes}")
        ck("no approval this server wrote carries an executor key",
           all(not (set(a.payload or {}) & executes) for a in new_aps))
        src = inspect.getsource(mcp_server)
        ck("nothing in the module reaches an outward door",
           not re.search(r"\b(esp|gbp|omnisend|constant_contact|shopify|canva|smtp)\.", src)
           and "push_campaign_to_esp" not in src)

    print("— a restart —")
    with TestClient(web.app) as c:
        r = Rpc(c).post("tools/list")
        ck("the app can start again and /mcp answers (a fresh session manager)",
           r.status_code == 200 and "get_package" in r.text, str(r.status_code))

    print()
    print("ALL GREEN" if not _fail else f"{len(_fail)} FAILED: {_fail}")
    return 0 if not _fail else 1


if __name__ == "__main__":
    sys.exit(main())
