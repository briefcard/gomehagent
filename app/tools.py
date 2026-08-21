"""One path for a tool the MODEL chose: guard it, run it, record it.

Three things have to happen every time a model names a tool, and they were
written out longhand in `kernel._dispatch` and nowhere else:

  1. the account boundary is applied — the tool is refused if it names a
     different client, and the resolved account is injected;
  2. the handler runs;
  3. the round trip is filed in `ToolCall`, pass or fail.

`triage.py` runs its own tool loop for inbound mail and did (1) only, by calling
`data_tools.dispatch(..., tenant=…)` directly. So the busiest model loop in the
system — the one answering the owner's mail every few minutes — contributed
nothing to the ledger that Diagnostics reads, and its platform calls were
invisible in exactly the report you open when mail stops being answered.

That is not a bug in `triage`; it is what happens when the three steps live
inside one caller instead of behind one door. This is the door. `kernel` keeps
its role plumbing and delegates the three steps here, so a second loop cannot
be written that quietly does two of them.

**A refusal IS a tool call** and is recorded as a failed one. It is the signal
that something asked for a capability this account has not connected, which is
precisely what a report should surface — dropping it makes a blocked account
look idle instead.
"""
from __future__ import annotations

from typing import Callable

from . import data_tools


def call(name: str, args: dict, tenant: str = "", *,
         fallback: Callable[[str, dict], str] | None = None,
         source: str = "kernel") -> str:
    """Route one model-chosen tool call. Returns the tool result as a string.

    `fallback` handles names outside the shared `data_tools` pack — a role's own
    tools. Without one, an unknown name is a `KeyError` from `data_tools`, the
    same as before.

    Exceptions are RECORDED and RE-RAISED. Swallowing here would turn a broken
    connection into a silent empty answer, which is the failure mode the ledger
    exists to make visible.
    """
    import time as _clock

    from . import tool_scope, toolcalls

    args, refusal = tool_scope.guard(name, args, tenant)
    if refusal:
        toolcalls.record(tenant, name, source=source, ok=False,
                         error=refusal[:200])
        return refusal

    started = _clock.perf_counter()
    err = ""
    out = ""
    try:
        if name in data_tools._HANDLERS:
            out = data_tools.dispatch(name, args)
        elif fallback is not None:
            out = fallback(name, args)
        else:
            out = data_tools.dispatch(name, args)
        return out
    except Exception as exc:                                     # noqa: BLE001
        err = f"{exc.__class__.__name__}: {str(exc)[:160]}"
        raise
    finally:
        toolcalls.record(
            tenant, name, source=source, ok=not err, error=err,
            ms=int((_clock.perf_counter() - started) * 1000),
            bytes_back=len(out or "") if isinstance(out, str) else 0)
