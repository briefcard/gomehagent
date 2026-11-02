"""The data layer is an MCP server: five tools behind one key, nothing leaves.

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
  * the app can start twice (a restart) and /mcp still answers;
  * a request carrying the PRODUCTION Host header is served (2026-11-02: the
    SDK's default host check refused every non-localhost Host with a 421, so
    the deployed door answered nobody);
  * get_plan and get_results read the console's own state, scoped to the
    account asked for, and refuse an unknown account or dimension by name;
  * `python -m app.mcp_stdio` refuses without DATABASE_URL, and with it serves
    the same tools to the official stdio client;
  * the inbox tools reach ONLY the account's own inbox (resolved from
    `Tenant.gmail_alias`, never passed), refuse the personal inbox and an
    account with none, and `inbox_draft` creates a draft — never a send — only
    after the triage guard passes, failing closed when the guard cannot run.

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
PROD_HOST = "assistant-web-zm2d.onrender.com"


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class Rpc:
    """JSON-RPC over the Streamable HTTP route — the wire, not the SDK."""

    def __init__(self, client, key=KEY, host=""):
        self.c, self.key, self.n, self.host = client, key, 0, host

    def post(self, method, params=None, *, notify=False):
        self.n += 1
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            msg["id"] = self.n
        headers = {"Accept": ACCEPT, "Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        if self.host:
            headers["Host"] = self.host
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
        r = Rpc(c, host=PROD_HOST).open()
        ck("the production Host header is served, not refused as misdirected",
           r.status_code == 200, f"{r.status_code} {r.text[:120]}")
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


        print("— get_plan and get_results —")
        plan = rpc.call("get_plan", {"tenant": T})["structuredContent"]
        ck("get_plan reads every section, none unavailable",
           plan.get("ok") and not plan.get("unavailable")
           and {"systems", "plans", "needs_action", "waiting_on", "attention"} <= set(plan),
           str(plan.get("unavailable") or sorted(plan))[:200])
        ck("…and its systems are the account's own",
           any(r["key"] == "campaign_email" and r["tenant"] == T for r in plan["systems"]),
           str(plan["systems"])[:160])
        res = rpc.call("get_results", {"tenant": T})["structuredContent"]
        ck("get_results reads every section, none unavailable",
           res.get("ok") and not res.get("unavailable")
           and {"ads", "headline", "drafts", "verdicts", "caught"} <= set(res),
           str(res.get("unavailable") or sorted(res))[:200])
        ck("…the drafts this suite recorded: one blocked, one draft",
           res["drafts"].get("campaign_email", {}).get("blocked") == 1
           and res["drafts"]["campaign_email"].get("draft") == 1, str(res["drafts"]))
        ck("…the queued one waits as a pending verdict",
           res["verdicts"].get("skill_output", {}).get("pending") == 1, str(res["verdicts"]))
        ck("…and what the gates caught is counted",
           res["caught"].get("banned_claim", 0) >= 1, str(res["caught"]))
        other = rpc.call("get_results", {"tenant": "eien"})["structuredContent"]
        ck("another account sees none of it (tenant-scoped)",
           other.get("ok") and not other["drafts"] and not other["verdicts"]
           and not other["caught"], str(other)[:200])
        bad = rpc.call("get_results", {"tenant": T, "dimension": "vibes"})["structuredContent"]
        ck("an unknown dimension is refused with the known ones",
           not bad["ok"] and "positioning" in bad["known"], str(bad))
        bad = rpc.call("get_plan", {"tenant": "nobody"})["structuredContent"]
        ck("an unknown account is refused by name", not bad["ok"] and "baci" in bad["known"])


        print("— the inbox: the account's own, read and drafted, never sent —")
        from app import gmail_client, validator
        BOXES = {"baci": {"t-baci": [
                    {"id": "m1", "from": "Silvia <silvia@shop.example>", "reply_to": "",
                     "subject": "Zodiac bread plates", "ours": False, "body": "Do you have them?"},
                    {"id": "m2", "from": "Baci <info@bacimilanousa.com>", "reply_to": "",
                     "subject": "Re: Zodiac bread plates", "ours": True, "body": "Checking."}]},
                 "eien": {"t-eien": [
                    {"id": "e1", "from": "Ann <ann@example.com>", "reply_to": "",
                     "subject": "Order", "ours": False, "body": "Where is it?"}]}}
        calls = []

        def fake_search(alias, query, max_results=20):
            calls.append(("search", alias, query))
            return [{"thread_id": t, "subject": m[0]["subject"]} for t, m in BOXES[alias].items()]

        def fake_thread(alias, thread_id, body_limit=6000):
            calls.append(("thread", alias, thread_id))
            if thread_id not in BOXES[alias]:
                raise RuntimeError("HttpError 404: Requested entity was not found.")
            return BOXES[alias][thread_id]

        def fake_draft(alias, to, subject, body, thread_id=None, cc=""):
            calls.append(("draft", alias, to, subject, thread_id))
            return "d-1"

        real = (gmail_client.search_threads, gmail_client.thread_messages,
                gmail_client.create_draft, validator.check)
        gmail_client.search_threads = fake_search
        gmail_client.thread_messages = fake_thread
        gmail_client.create_draft = fake_draft
        try:
            r = rpc.call("inbox_search", {"tenant": T, "query": "from:silvia", "days": 30})["structuredContent"]
            ck("inbox_search reads baci's inbox, with the window applied",
               r["ok"] and calls[-1] == ("search", "baci", "from:silvia newer_than:30d")
               and r["threads"][0]["thread_id"] == "t-baci", str(calls[-1:]))
            r = rpc.call("inbox_search", {"tenant": "eien"})["structuredContent"]
            ck("…and eien's when eien is asked", r["ok"] and calls[-1][1] == "eien", str(calls[-1:]))
            r = rpc.call("inbox_thread", {"tenant": "eien", "thread_id": "t-baci"})["structuredContent"]
            ck("a baci thread asked through eien is a failure, not baci's mail",
               not r["ok"] and calls[-1] == ("thread", "eien", "t-baci") and "404" in r["why"], str(r))
            r = rpc.call("inbox_search", {"tenant": "agency"})["structuredContent"]
            ck("the owner's personal inbox is refused", not r["ok"] and "personal" in r["why"], str(r))
            r = rpc.call("inbox_search", {"tenant": "coverings"})["structuredContent"]
            ck("an account with no inbox is refused, naming the ones that have one",
               not r["ok"] and r.get("accounts_with_an_inbox") == ["baci", "eien"], str(r))
            names = {t["name"]: t for t in rpc.post("tools/list").json()["result"]["tools"]}
            ck("no inbox tool takes an alias or an inbox — the account decides",
               all(not ({"alias", "inbox", "account"} & set(names[n]["inputSchema"].get("properties", {})))
                   for n in ("inbox_search", "inbox_thread", "inbox_attachment", "inbox_draft")))

            # inbox_attachment: the duty on a 7501 is in the inbox's records
            ATTS = {"baci": {"m-7501": [
                {"filename": "7501_NEW_07036093.pdf", "attachment_id": "a1", "mime": "application/pdf"},
                {"filename": "PKLIST.xlsx", "attachment_id": "a2", "mime": "application/vnd.ms-excel"},
                {"filename": "scan.pdf", "attachment_id": "a3", "mime": "application/pdf"}]}, "eien": {}}

            def fake_atts(alias, message_id):
                calls.append(("atts", alias, message_id))
                if message_id not in ATTS[alias]:
                    raise RuntimeError("HttpError 404: Requested entity was not found.")
                return ATTS[alias][message_id]

            def fake_dl(alias, message_id, att_id):
                calls.append(("dl", alias, message_id, att_id))
                return {"a1": b"PDF", "a2": b"XLSX", "a3": b"SCAN"}[att_id]

            def fake_text(name, data):
                return {b"PDF": "Duty 25% $1,234.56", b"XLSX": "Plates\t12", b"SCAN": ""}[data]

            real_att = (gmail_client.message_attachments, gmail_client.download_attachment,
                        mcp_server._attachment_text)
            gmail_client.message_attachments = fake_atts
            gmail_client.download_attachment = fake_dl
            mcp_server._attachment_text = fake_text
            try:
                r = rpc.call("inbox_attachment", {"tenant": T, "message_id": "m-7501"})["structuredContent"]
                ck("inbox_attachment with no filename lists the message's attachments",
                   r["ok"] and r["attachments"][0] == "7501_NEW_07036093.pdf"
                   and calls[-1] == ("atts", "baci", "m-7501"), str(r))
                r = rpc.call("inbox_attachment", {"tenant": T, "message_id": "m-7501",
                                                  "filename": "7501"})["structuredContent"]
                ck("…and reads the TEXT of the one asked for, from baci's inbox",
                   r["ok"] and "$1,234.56" in r["text"]
                   and calls[-1] == ("dl", "baci", "m-7501", "a1"), str(r))
                r = rpc.call("inbox_attachment", {"tenant": "eien", "message_id": "m-7501",
                                                  "filename": "7501"})["structuredContent"]
                ck("a baci message asked through eien is a failure, not baci's document",
                   not r["ok"] and "404" in r["why"]
                   and not any(c[0] == "dl" and c[1] == "eien" for c in calls), str(r))
                r = rpc.call("inbox_attachment", {"tenant": T, "message_id": "m-7501",
                                                  "filename": "scan"})["structuredContent"]
                ck("a scanned PDF with no text says so instead of returning nothing",
                   not r["ok"] and "no text layer" in r["why"], str(r))
                r = rpc.call("inbox_attachment", {"tenant": "agency", "message_id": "m-7501"})["structuredContent"]
                ck("the owner's personal inbox is refused for attachments too",
                   not r["ok"] and "personal" in r["why"], str(r))
            finally:
                (gmail_client.message_attachments, gmail_client.download_attachment,
                 mcp_server._attachment_text) = real_att

            n_before = len([c for c in calls if c[0] == "draft"])
            r = rpc.call("inbox_draft", {"tenant": T, "thread_id": "t-baci",
                                         "body": "Yes, they are hand decorated and back in stock."})["structuredContent"]
            ck("a reply with a banned phrase is NOT drafted, and says which rule",
               not r["ok"] and r["status"] == "blocked"
               and any(b["rule"] == "banned_claim" for b in r["blocks"])
               and len([c for c in calls if c[0] == "draft"]) == n_before, str(r)[:200])
            validator.check = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            r = rpc.call("inbox_draft", {"tenant": T, "thread_id": "t-baci",
                                         "body": "Thank you, Silvia."})["structuredContent"]
            ck("a guard that cannot run is a block (fails closed), and nothing is drafted",
               not r["ok"] and r["blocks"][0]["rule"] == "gate_failed:validator"
               and len([c for c in calls if c[0] == "draft"]) == n_before, str(r)[:200])
            validator.check = real[3]
            r = rpc.call("inbox_draft", {"tenant": T, "thread_id": "t-baci",
                                         "body": "Thank you, Silvia. Here is what we have."})["structuredContent"]
            ck("a clean reply is drafted in baci's inbox, threaded, to the customer and not to us",
               r["ok"] and r["status"] == "drafted"
               and calls[-1] == ("draft", "baci", "Silvia <silvia@shop.example>",
                                 "Re: Zodiac bread plates", "t-baci"), str(calls[-1:]))
        finally:
            (gmail_client.search_threads, gmail_client.thread_messages,
             gmail_client.create_draft, validator.check) = real
        src = inspect.getsource(mcp_server)
        ck("the server never sends mail — no send call exists in the module",
           not re.search(r"\b(send_email|send_draft|send_message)\s*\(", src))

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

    print("— stdio, for a local Claude Code —")
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env.pop("GOMEH_MCP_ALLOW_LOCAL", None)
    p = subprocess.run([sys.executable, "-m", "app.mcp_stdio"], cwd=root, env=env,
                       capture_output=True, text=True, timeout=60)
    ck("without DATABASE_URL it refuses rather than read an empty database",
       p.returncode == 2 and "DATABASE_URL" in p.stderr, f"{p.returncode} {p.stderr[:120]}")
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def _stdio():
        params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_stdio"],
                                       cwd=root, env=dict(os.environ))
        async with stdio_client(params) as (rd, wr):
            async with ClientSession(rd, wr) as sess:
                await sess.initialize()
                tools = sorted(t.name for t in (await sess.list_tools()).tools)
                got = await sess.call_tool("get_results", {"tenant": T})
                return tools, got.structuredContent or {}
    tools, got = anyio.run(_stdio)
    ck("with it, the official stdio client sees the same tools",
       tools == sorted(mcp_server.TOOLS), str(tools))
    ck("…and reads the same data the HTTP door does",
       got.get("drafts", {}).get("campaign_email", {}).get("draft") == 1, str(got)[:160])

    print()
    print("ALL GREEN" if not _fail else f"{len(_fail)} FAILED: {_fail}")
    return 0 if not _fail else 1


if __name__ == "__main__":
    sys.exit(main())
