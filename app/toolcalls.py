"""What the tools did, so a client report is read rather than remembered.

`Usage` records what the model cost. `assurance` records what the validator
checked. Neither says whether the client's OWN systems were reached — so "is
Baci's Shopify actually being read", "when did their Search Console start
failing", and "what did we do for this account in October" had no answer except
somebody's memory, which is exactly the kind of thing a monthly report should
never be built from.

Three decisions worth knowing before you extend this.

**The result is a size and a verdict, never a payload.** A tool result is the
client's own data — their orders, their mail, their customers. A ledger that
copies it becomes a second place that data lives, with none of the scoping the
first one has and none of the deletion guarantees. `bytes_back` and `ok` are
what a report needs; the body is not, and storing it would be a privacy
liability dressed as observability.

**A failure records the provider's own words.** "Shopify rejected that token"
is actionable and "tool failed" is not, and the difference decides whether the
next person re-connects an account or opens a debugger.

**Recording never breaks the call.** Every write here is wrapped and swallowed.
Telemetry that can take down the thing it observes is worse than none.
"""
from __future__ import annotations

import datetime as dt

from . import db

#: Which client platform each tool actually reaches. A tool that only touches
#: our own tables has no provider and is not a sign of anything about the
#: client's connections — counting it as one would make a healthy report out of
#: an account with nothing wired.
#:
#: Derived where it can be: `tool_scope.SCOPED` already knows which tools name
#: an account and which capability each needs.
_CAPABILITY_PROVIDER = {
    "commerce": "shopify",
    "inbox": "google",
    "analytics": "google",
    "esp": "esp",
    "cms": "cms",
    "ads": "meta_ads",
    "design": "canva",
}


def provider_for(tool: str) -> str:
    """Which of the client's platforms this tool reaches, or ""."""
    from . import tool_scope
    scoped = tool_scope.SCOPED.get(tool)
    if not scoped:
        return ""
    _param, capability = scoped
    return _CAPABILITY_PROVIDER.get(capability, "")


def record(tenant: str, tool: str, *, source: str = "kernel", ok: bool = True,
           error: str = "", ms: int = 0, bytes_back: int = 0,
           provider: str = "", ref: str = "") -> None:
    """File one tool call. Never raises."""
    try:
        with db.SessionLocal() as s:
            s.add(db.ToolCall(
                tenant=tenant or "", tool=tool or "", source=source,
                provider=provider or provider_for(tool),
                ok="yes" if ok else "no", error=(error or "")[:400],
                ms=str(int(ms or 0)), bytes_back=str(int(bytes_back or 0)),
                ref=ref or ""))
            s.commit()
    except Exception:                                            # noqa: BLE001
        pass


def _rows(tenant: str = "", days: int = 30) -> list[db.ToolCall]:
    since = db.utcnow() - dt.timedelta(days=days)
    with db.SessionLocal() as s:
        q = s.query(db.ToolCall).filter(db.ToolCall.at >= since)
        if tenant:
            q = q.filter(db.ToolCall.tenant == tenant)
        return q.order_by(db.ToolCall.at.desc()).all()


def report(tenant: str = "", days: int = 30) -> dict:
    """Per-tool counts, failures and the slow ones. The input to a report."""
    rows = _rows(tenant, days)
    if not rows:
        return {"tenant": tenant, "days": days, "calls": 0,
                "verdict": "no tool call was recorded in this window",
                "by_tool": {}, "by_provider": {}, "failing": []}

    by_tool: dict[str, dict] = {}
    for r in rows:
        b = by_tool.setdefault(r.tool, {"calls": 0, "failed": 0, "ms": []})
        b["calls"] += 1
        if r.ok != "yes":
            b["failed"] += 1
        if (r.ms or "").isdigit() and int(r.ms):
            b["ms"].append(int(r.ms))
    for b in by_tool.values():
        b["slowest_ms"] = max(b["ms"]) if b["ms"] else 0
        b["median_ms"] = (sorted(b["ms"])[len(b["ms"]) // 2] if b["ms"] else 0)
        del b["ms"]

    by_provider: dict[str, dict] = {}
    for r in rows:
        if not r.provider:
            continue          # our own tables say nothing about their stack
        b = by_provider.setdefault(r.provider, {"calls": 0, "failed": 0,
                                                "last_error": ""})
        b["calls"] += 1
        if r.ok != "yes":
            b["failed"] += 1
            b["last_error"] = b["last_error"] or (r.error or "")[:160]

    # A provider that fails MOST of the time is a broken connection; one that
    # fails occasionally is the internet. Ranked so the first is not buried
    # under the second.
    failing = sorted(
        ({"provider": p, **d,
          "failure_rate": round(d["failed"] / d["calls"], 3)}
         for p, d in by_provider.items() if d["failed"]),
        key=lambda x: -x["failure_rate"])

    return {"tenant": tenant, "days": days, "calls": len(rows),
            "by_tool": dict(sorted(by_tool.items(),
                                   key=lambda kv: -kv[1]["calls"])),
            "by_provider": by_provider, "failing": failing}


def reached(tenant: str, days: int = 30) -> dict[str, int]:
    """Which of the client's platforms were successfully read, and how often.

    The line a client report actually needs: "we read your store 42 times this
    month" is a fact about the work; "Shopify is connected" is a fact about a
    settings page and says nothing about whether anything used it.
    """
    out: dict[str, int] = {}
    for r in _rows(tenant, days):
        if r.provider and r.ok == "yes":
            out[r.provider] = out.get(r.provider, 0) + 1
    return out


def instrument(provider: str, fn):
    """Wrap an adapter's `call` seam so every platform round trip is recorded.

    Applied at the module-level seam rather than inside each `_call`, for two
    reasons. The three adapters have three different bodies and patching each
    is three chances to get it wrong; and the suites replace that same seam
    with a stub, so an instrumented build under test records nothing and the
    tests stay honest about what they are driving.

    The tool name is `provider:METHOD /path` — coarse on purpose. Recording the
    full path with ids in it would put a client's order numbers in our
    telemetry, which is the payload rule one level down.
    """
    import time as _clock

    def wrapped(tenant, method, path, **kw):
        started = _clock.perf_counter()
        res = fn(tenant, method, path, **kw)
        try:
            ok = bool((res or {}).get("ok"))
            err = "" if ok else str((res or {}).get("error", ""))
            head = str(path).split("?")[0].rstrip("/")
            # One id per path segment is enough to make every call unique and
            # useless to group by, so numeric-looking segments are dropped.
            clean = "/".join(seg for seg in head.split("/")
                             if not any(ch.isdigit() for ch in seg))
            record(tenant, f"{provider}:{method} {clean or '/'}",
                   source="adapter", provider=provider, ok=ok, error=err,
                   ms=int((_clock.perf_counter() - started) * 1000),
                   bytes_back=len(str((res or {}).get("data", ""))))
        except Exception:                                        # noqa: BLE001
            pass
        return res

    return wrapped
