"""The real handshake: the official MCP client against a live local server.

The suite speaks JSON-RPC by hand so it can assert on the wire. This proves
the thing the suite cannot — that an actual MCP client (the SDK's own, the
same protocol Claude speaks) completes initialize, lists the three tools and
calls one — against uvicorn, not a test client. `app/mcp_client.py` carries
the warning this script answers: "no call here has ever met a live MCP
server", and every adapter in this codebase was wrong in some detail on first
contact.

    python3 scripts/mcp_smoke.py            # local: seeds a temp DB, starts uvicorn
    MCP_URL=https://…/mcp MCP_KEY=… python3 scripts/mcp_smoke.py   # against a deploy
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _local() -> tuple[str, str, subprocess.Popen]:
    key = "smoke-" + str(int(time.time()))
    env = {**os.environ,
           "DATABASE_URL": f"sqlite:///{os.path.join(tempfile.mkdtemp(), 's.db')}",
           "APPROVAL_SECRET": "smoke", "SEO_SITES_JSON": "{}", "MCP_KEY": key,
           "ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "", "GEMINI_API_KEY": ""}
    # seed in-process against the same file, then hand it to uvicorn
    os.environ.update({k: env[k] for k in ("DATABASE_URL", "APPROVAL_SECRET", "SEO_SITES_JSON", "MCP_KEY")})
    from app import db, kb, tenants
    db.init_db(); tenants.seed()
    kb.add_claim("baci", "Designed in Milan by the Italian design house Baci Milano.",
                 "brand file", [], origin="human", status="active")
    kb.add_banned("baci", "hand-decorated")
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.web:app",
                             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
                            cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(url + "/health", timeout=2).status_code == 200:
                break
        except Exception:                                      # noqa: BLE001
            time.sleep(0.5)
    return url + "/mcp", key, proc


async def _probe(url: str, key: str) -> int:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    fails = 0

    def ck(label, cond, detail=""):
        nonlocal fails
        print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
        fails += 0 if cond else 1

    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {key}"}) as (r, w, _sid):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            ck("initialize", init.serverInfo.name == "gomehagent", init.serverInfo.name)
            tools = await s.list_tools()
            names = sorted(t.name for t in tools.tools)
            ck("three tools", names == ["check", "get_package", "record"], str(names))
            got = await s.call_tool("get_package", {"tenant": "baci", "system": "campaign_email"})
            text = "\n".join(c.text for c in got.content if getattr(c, "type", "") == "text")
            ck("get_package returns the package", "hand-decorated" in text and "### The rules" in text,
               f"{len(text)} chars")
            got = await s.call_tool("check", {"tenant": "baci", "body": "Hand decorated for you",
                                              "kind": "email"})
            ck("check blocks a banned claim", got.structuredContent and not got.structuredContent["ok"],
               str(got.structuredContent and [b["rule"] for b in got.structuredContent["blocks"]]))
    # the door, with the real client's own transport
    try:
        async with streamablehttp_client(url, headers={"Authorization": "Bearer wrong"}) as (r, w, _sid):
            async with ClientSession(r, w) as s:
                await asyncio.wait_for(s.initialize(), timeout=10)
        ck("a wrong key is refused", False, "initialize succeeded")
    except Exception as exc:                                   # noqa: BLE001
        ck("a wrong key is refused", True, exc.__class__.__name__)
    return fails


def main() -> int:
    url, key, proc = os.environ.get("MCP_URL", ""), os.environ.get("MCP_KEY", ""), None
    if not url:
        url, key, proc = _local()
    print(f"— {url} —")
    try:
        fails = asyncio.run(_probe(url, key))
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    print("ALL GREEN" if not fails else f"{fails} FAILED")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
