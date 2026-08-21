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

    # ONE LAYER PER PROVIDER, and this is not tidiness.
    #
    # A model tool call that reaches Shopify now files TWO rows: the tool the
    # model named, and the HTTP round trip under it. Counting both doubles every
    # provider total — and worse, it halves the failure rate, because
    # `data_tools.dispatch` catches the exception and returns a "Tool error"
    # STRING, so the platform row records a failure while the tool row records a
    # success for the very same call.
    #
    # Measured: a completely dead Shopify token read as `failure_rate 0.5`. This
    # report's own comment below says most-of-the-time means a broken connection
    # and occasionally means the internet, so a dead credential landed exactly on
    # the line between them.
    #
    # The platform layer is the truthful one where it exists, so it wins. Where
    # no seam is instrumented — Google, today — the tool layer is all there is
    # and is used, with `layer` saying so, because a provider counted from the
    # tool layer has durations that include our own work rather than the round
    # trip, and reading those as network time is the next version of this bug.
    platform_layer = {r.provider for r in rows
                      if r.source == "adapter" and r.provider}
    by_provider: dict[str, dict] = {}
    for r in rows:
        if not r.provider:
            continue          # our own tables say nothing about their stack
        if r.provider in platform_layer and r.source != "adapter":
            continue          # counted from the round trip instead
        b = by_provider.setdefault(r.provider, {"calls": 0, "failed": 0,
                                                "last_error": ""})
        b["calls"] += 1
        if r.ok != "yes":
            b["failed"] += 1
            b["last_error"] = b["last_error"] or (r.error or "")[:160]
    for prov, b in by_provider.items():
        b["layer"] = "platform" if prov in platform_layer else "tool"

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


def clean_path(path: str) -> str:
    """A path safe to store as telemetry, and coarse enough to group by.

    One id per segment makes every call unique and useless to group by, and it
    would also put a client's order numbers in our own telemetry — which is the
    payload rule one level down. Numeric-looking segments are dropped.
    """
    head = str(path or "").split("?")[0].rstrip("/")
    return "/".join(seg for seg in head.split("/")
                    if not any(ch.isdigit() for ch in seg)) or "/"


def http_seam(provider: str, tenant_of, method: str = ""):
    """Record every round trip through a seam keyed by something that is not a tenant.

    `instrument` fits the three adapters whose `call` already begins with a
    tenant — and those three are Omnisend, Constant Contact and Canva, every
    one of which has never been called for real. The modules that run EVERY
    DAY were not instrumented at all: `shopify_seo` is keyed by a store key and
    `wordpress_seo` by a site profile, so neither fits that signature.

    The result was telemetry that covered the code which never runs and missed
    the code which runs constantly, which is why Diagnostics reports most of
    this system as untimed. `tenant_of` is how the seam's own key becomes an
    account — the join `app/connections.py` exists to provide.

    `method=""` means the seam takes the HTTP verb as its SECOND argument
    (`_send(who, method, path, ...)`); a given verb means it is fixed for that
    seam (`_get(who, path, ...)`).

    **A raising seam is recorded and re-raised.** These wrap `raise_for_status`,
    so a dead token arrives as an exception — and an exception is exactly the
    call worth having in the ledger. Swallowing it here would turn a broken
    connection into a silent empty answer, which is the failure mode this whole
    ledger exists to make visible.
    """
    import functools
    import time as _clock

    def deco(fn):
        @functools.wraps(fn)
        def wrapped(who, *a, **kw):
            if method:
                verb, path = method, (a[0] if a else "")
            else:
                verb, path = ((a[0] if a else ""), (a[1] if len(a) > 1 else ""))
            started = _clock.perf_counter()
            err = ""
            res = None
            try:
                res = fn(who, *a, **kw)
                return res
            except Exception as exc:                             # noqa: BLE001
                err = f"{exc.__class__.__name__}: {str(exc)[:160]}"
                raise
            finally:
                try:
                    tenant = tenant_of(who) or ""
                except Exception:                                # noqa: BLE001
                    # Never let the ATTRIBUTION of a call break the call.
                    tenant = ""
                record(tenant, f"{provider}:{verb} {clean_path(path)}",
                       source="adapter", provider=provider, ok=not err,
                       error=err,
                       ms=int((_clock.perf_counter() - started) * 1000),
                       bytes_back=len(str(res)) if res is not None else 0)
        return wrapped
    return deco


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
            clean = clean_path(path)
            record(tenant, f"{provider}:{method} {clean}",
                   source="adapter", provider=provider, ok=ok, error=err,
                   ms=int((_clock.perf_counter() - started) * 1000),
                   bytes_back=len(str((res or {}).get("data", ""))))
        except Exception:                                        # noqa: BLE001
            pass
        return res

    return wrapped
