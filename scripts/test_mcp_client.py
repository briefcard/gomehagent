"""The MCP client: framing, session mechanics, and refusals by name.

No live server is touched — `mcp_client._post` is the one network seam and
the suite replaces it with a scripted server. What is checked is the CONTRACT
the adapters rely on: the handshake captures a server-issued session id and
sends it back; responses arrive as plain JSON or as an SSE stream and both
parse; a JSON-RPC error, an auth rejection, a tool-level `isError` and a
dead socket all come back as named refusals, never exceptions; and the tool
inventory read returns names — the thing the first live probe exists to
learn (ARCHITECTURE.md: exact names, never guessed ones).

Run: python3 scripts/test_mcp_client.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import mcp_client  # noqa: E402

_fail: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class _Resp:
    def __init__(self, status=200, body=None, headers=None, text=""):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = text if text else (json.dumps(body) if body is not None else "")

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _server(script):
    """A fake server: pops one canned response per request, records requests."""
    seen = []

    def post(url, headers, payload):
        seen.append({"url": url, "headers": headers, "payload": payload})
        step = script.pop(0)
        return step(payload) if callable(step) else step
    return post, seen


def main() -> int:
    print("— handshake and session id —")
    post, seen = _server([
        _Resp(200, {"jsonrpc": "2.0", "id": 1,
                    "result": {"protocolVersion": "2025-06-18",
                               "serverInfo": {"name": "fake"}}},
              headers={"mcp-session-id": "sess-42"}),
        _Resp(202),                                    # notifications/initialized
        _Resp(200, {"jsonrpc": "2.0", "id": 2,
                    "result": {"tools": [
                        {"name": "create_design", "description": "makes one"},
                        {"name": "get_brand_kit", "description": "reads kit"}]}}),
    ])
    mcp_client._post = post
    sess, why = mcp_client.open_session("https://mcp.example/mcp", "tok-1")
    ck("handshake succeeds", sess is not None and why == "", why)
    ck("the server-issued session id was captured", sess.sid == "sess-42")
    ck("the bearer rides every request",
       seen[0]["headers"].get("Authorization") == "Bearer tok-1")
    ck("the client accepts both response shapes",
       "text/event-stream" in seen[0]["headers"].get("Accept", ""))
    got = mcp_client.tools(sess)
    ck("tools/list returns the REAL names",
       got["ok"] and [t["name"] for t in got["tools"]]
       == ["create_design", "get_brand_kit"])
    ck("…and the session id went back on the follow-up",
       seen[-1]["headers"].get("Mcp-Session-Id") == "sess-42")
    ck("the ack after initialize was a notification (no id)",
       "id" not in seen[1]["payload"]
       and seen[1]["payload"]["method"] == "notifications/initialized")

    print("\n— SSE responses parse, chatter is skipped —")
    sse = ("event: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":"
           "\"notifications/progress\",\"params\":{}}\n\n"
           "data: {\"jsonrpc\":\"2.0\",\"id\":3,\"result\":"
           "{\"content\":[{\"type\":\"text\",\"text\":\"made design DAF1\"}],"
           "\"structuredContent\":{\"id\":\"DAF1\"}}}\n\n")
    post, seen = _server([_Resp(200, text=sse,
                                headers={"content-type": "text/event-stream"})])
    mcp_client._post = post
    sess = mcp_client.Session("https://mcp.example/mcp", "tok-1")
    sess._id = 2                    # the next request gets id 3
    got = mcp_client.tool_call(sess, "create_design", {"title": "x"})
    ck("the response with OUR id is found among the chatter",
       got["ok"] and got["structured"] == {"id": "DAF1"}, str(got)[:80])
    ck("text content is joined", got.get("text") == "made design DAF1")

    print("\n— every failure is a named refusal, never an exception —")
    post, _ = _server([_Resp(401, text="nope")])
    mcp_client._post = post
    sess2, why = mcp_client.open_session("https://mcp.example/mcp", "bad")
    ck("auth rejection names the credential problem",
       sess2 is None and "rejected the credential" in why, why[:70])

    post, _ = _server([_Resp(200, {"jsonrpc": "2.0", "id": 1,
                                   "error": {"code": -32601,
                                             "message": "no such method"}})])
    mcp_client._post = post
    sess3, why = mcp_client.open_session("https://mcp.example/mcp")
    ck("a JSON-RPC error carries code and message",
       sess3 is None and "-32601" in why and "no such method" in why, why[:70])

    def _boom(url, headers, payload):
        raise ConnectionError("refused")
    mcp_client._post = _boom
    sess4, why = mcp_client.open_session("https://mcp.example/mcp")
    ck("a dead socket is a named refusal", sess4 is None
       and "ConnectionError" in why, why[:60])

    ck("no URL refuses before the network",
       mcp_client.open_session("")[1] == "no MCP server URL configured.")

    print("\n— a tool that refuses is a refusal, not a transport failure —")
    post, _ = _server([_Resp(200, {"jsonrpc": "2.0", "id": 1, "result": {
        "isError": True,
        "content": [{"type": "text", "text": "brand kit not found"}]}})])
    mcp_client._post = post
    sess5 = mcp_client.Session("https://mcp.example/mcp")
    got = mcp_client.tool_call(sess5, "get_brand_kit", {})
    ck("isError becomes ok:False with the tool's own reason",
       not got["ok"] and "brand kit not found" in got["error"], got.get("error", "")[:60])

    print("\n— an SSE stream that never answers is named, not hung —")
    post, _ = _server([_Resp(200, text="data: {\"jsonrpc\":\"2.0\",\"method\":\"x\"}\n\n",
                             headers={"content-type": "text/event-stream"})])
    mcp_client._post = post
    sess6 = mcp_client.Session("https://mcp.example/mcp")
    got = mcp_client.tool_call(sess6, "anything", {})
    ck("the missing response is reported by request id",
       not got["ok"] and "without a response" in got["error"], got.get("error", "")[:70])

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
