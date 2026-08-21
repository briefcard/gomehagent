"""A minimal MCP client over Streamable HTTP — a transport, not an authority.

ARCHITECTURE.md's rule made mechanical: remote MCP servers (Canva's first) are
called from OUR adapter seams, with the tenant's own credential, inside the
same instrumentation every other adapter gets. Nothing here is handed to a
model as a tool; an adapter calls `tool_call` the way it would call REST, and
everything downstream — validation, approval, ledger — is unchanged.

Speaks just enough of the protocol to be useful: `initialize` (capturing the
`Mcp-Session-Id` the server may issue), the `notifications/initialized` ack,
`tools/list`, and `tools/call`. Responses may arrive as plain JSON or as an
SSE stream (Streamable HTTP allows either); both are parsed, and the SSE path
reads events until the response with OUR request id appears.

**Honesty, inherited:** no call here has ever met a live MCP server — the
same state every adapter in this codebase started in, and every one of them
was wrong in some detail on first contact (DEFECTS §2). So every failure
returns a named refusal rather than raising, timeouts are bounded, and the
first live probe (`/admin/canva_probe`) is designed to TEACH — it lists the
server's real tool names so the adapter wires exact names, not guessed ones.
"""
from __future__ import annotations

import json

PROTOCOL = "2025-06-18"      # the Streamable HTTP revision; VERIFY on first
                             # live handshake — servers negotiate downward.
TIMEOUT = 45


def _post(url: str, headers: dict, payload: dict):
    """The one network seam, replaceable by the suite. Returns the httpx
    response object; callers read status_code / headers / text."""
    import httpx
    return httpx.post(url, headers=headers, json=payload, timeout=TIMEOUT)


class Session:
    """One conversation with one MCP server, for one tenant's credential."""

    def __init__(self, url: str, bearer: str = ""):
        self.url = url
        self.bearer = bearer
        self.sid = ""            # Mcp-Session-Id, if the server issues one
        self._id = 0

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json",
             # Streamable HTTP requires the client to accept both shapes.
             "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": PROTOCOL}
        if self.bearer:
            h["Authorization"] = f"Bearer {self.bearer}"
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        return h

    def _next(self) -> int:
        self._id += 1
        return self._id


def _parse_sse(text: str, want_id: int) -> dict | None:
    """The JSON-RPC response with our id, out of an SSE stream.

    An event's payload is the concatenation of its `data:` lines; events are
    blank-line separated. Anything unparseable or addressed to another id
    (server-initiated requests, progress notifications) is skipped rather
    than fatal — a chatty server must not read as a broken one.
    """
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line[5:].lstrip() for line in block.split("\n")
                         if line.startswith("data:"))
        if not data:
            continue
        try:
            msg = json.loads(data)
        except Exception:                                        # noqa: BLE001
            continue
        if isinstance(msg, dict) and msg.get("id") == want_id:
            return msg
    return None


def _rpc(sess: Session, method: str, params: dict | None = None,
         *, notification: bool = False) -> dict:
    """One JSON-RPC exchange. Returns {ok, result} or {ok: False, error}."""
    payload: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        payload["params"] = params
    want = None
    if not notification:
        want = sess._next()
        payload["id"] = want
    try:
        r = _post(sess.url, sess._headers(), payload)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"{method}: {exc.__class__.__name__}: "
                                      f"{str(exc)[:160]}"}
    sid = r.headers.get("mcp-session-id", "")
    if sid:
        sess.sid = sid
    if r.status_code in (401, 403):
        return {"ok": False, "error": (
            f"{method}: the MCP server rejected the credential "
            f"({r.status_code}) — the token that works for the REST API may "
            f"not be accepted here; reconnect or re-scope it.")}
    if r.status_code >= 400:
        return {"ok": False,
                "error": f"{method}: HTTP {r.status_code}: {r.text[:200]}"}
    if notification:
        return {"ok": True, "result": None}

    ctype = (r.headers.get("content-type") or "").lower()
    msg: dict | None
    if "text/event-stream" in ctype:
        msg = _parse_sse(r.text, want)
        if msg is None:
            return {"ok": False, "error": (
                f"{method}: the SSE stream ended without a response to "
                f"request {want} — nothing to act on.")}
    else:
        try:
            msg = r.json()
        except Exception:                                        # noqa: BLE001
            return {"ok": False,
                    "error": f"{method}: unparseable response: {r.text[:160]}"}
    if not isinstance(msg, dict):
        return {"ok": False, "error": f"{method}: non-object response"}
    if msg.get("error"):
        e = msg["error"]
        return {"ok": False, "error": (
            f"{method}: {e.get('code', '?')}: {str(e.get('message', ''))[:200]}")}
    return {"ok": True, "result": msg.get("result")}


def open_session(url: str, bearer: str = "",
                 client_name: str = "gomehagent") -> tuple[Session | None, str]:
    """Handshake with a server: `(session, "")` or `(None, why)`."""
    if not url:
        return None, "no MCP server URL configured."
    sess = Session(url, bearer)
    got = _rpc(sess, "initialize", {
        "protocolVersion": PROTOCOL,
        "capabilities": {},
        "clientInfo": {"name": client_name, "version": "1"},
    })
    if not got["ok"]:
        return None, got["error"]
    # The ack is a notification; a server that errors on it has still
    # initialized, so a failure here is reported by the next real call.
    _rpc(sess, "notifications/initialized", {}, notification=True)
    return sess, ""


def tools(sess: Session) -> dict:
    """The server's tool inventory: {ok, tools: [{name, description}]}.

    This is the call the first live probe exists for — the REAL tool names,
    so the adapter maps exact names instead of guessed ones.
    """
    got = _rpc(sess, "tools/list", {})
    if not got["ok"]:
        return got
    rows = (got["result"] or {}).get("tools") or []
    return {"ok": True, "tools": [
        {"name": t.get("name", ""),
         "description": (t.get("description") or "")[:200]}
        for t in rows if isinstance(t, dict)]}


def tool_call(sess: Session, name: str, arguments: dict | None = None) -> dict:
    """Call one tool: {ok, text, structured} or a named refusal.

    A result with `isError` is a REFUSAL, not a transport failure — the
    server ran the tool and the tool said no; the text is the reason.
    """
    got = _rpc(sess, "tools/call", {"name": name,
                                    "arguments": arguments or {}})
    if not got["ok"]:
        return got
    res = got["result"] or {}
    text = " ".join(c.get("text", "") for c in (res.get("content") or [])
                    if isinstance(c, dict) and c.get("type") == "text").strip()
    if res.get("isError"):
        return {"ok": False, "error": f"{name}: {text[:300] or 'the tool refused'}"}
    return {"ok": True, "text": text,
            "structured": res.get("structuredContent")}
