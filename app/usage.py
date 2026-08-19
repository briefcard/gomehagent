"""Token-usage logging + cost/cache-hit reporting.

Call log_usage(purpose, model, response) after each Claude call; query
report() to audit cache effectiveness and spend.
"""
import datetime as dt

from . import db

# $ per million tokens (in, out, cache-write +25%, cache-read -90%).
PRICES = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}


def log_usage(purpose: str, model: str, resp, tenant: str = "") -> None:
    """Record one model call, attributed to a client where the caller knows one.

    `Usage.tenant` was declared and indexed from the start, commented
    "per-client cost attribution", and NOTHING ever wrote it — so the one
    question a spend report is actually asked ("what does this client cost me")
    had no answer, and the column looked like a working feature.

    A caller that genuinely does not know passes nothing, and the row stays
    blank. `report()` shows those as `unattributed` rather than folding them
    into an account, because a client's bill inflated by shared overhead is
    worse than one that admits what it cannot split.
    """
    try:
        u = resp.usage
        with db.SessionLocal() as s:
            s.add(db.Usage(
                purpose=purpose, model=model, tenant=tenant or "",
                input_tokens=str(getattr(u, "input_tokens", 0) or 0),
                output_tokens=str(getattr(u, "output_tokens", 0) or 0),
                cache_read=str(getattr(u, "cache_read_input_tokens", 0) or 0),
                cache_write=str(getattr(u, "cache_creation_input_tokens", 0) or 0),
            ))
            s.commit()
    except Exception:  # noqa: BLE001 — never let accounting break a call
        pass


def _cost(model: str, inp: int, out: int, cr: int, cw: int) -> float:
    pin, pout = PRICES.get(model, (3.0, 15.0))
    return (inp * pin + out * pout + cw * pin * 1.25 + cr * pin * 0.10) / 1e6


def report(days: int = 7, tenant: str = "") -> dict:
    """Spend for a window, optionally for ONE client.

    `tenant=""` reports everything and splits it in `by_tenant`, with rows
    nobody attributed under `unattributed` rather than divided across accounts.
    Spreading shared overhead over clients invents a number that looks precise
    and is not, and a client's bill is the last place to do that.
    """
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    with db.SessionLocal() as s:
        q = s.query(db.Usage).filter(db.Usage.at >= since)
        if tenant:
            q = q.filter(db.Usage.tenant == tenant)
        rows = q.all()
    tot = {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
           "cost": 0.0}
    by_purpose: dict = {}
    by_tenant: dict = {}
    for r in rows:
        inp, out = int(r.input_tokens), int(r.output_tokens)
        cr, cw = int(r.cache_read), int(r.cache_write)
        c = _cost(r.model, inp, out, cr, cw)
        tot["calls"] += 1
        tot["input"] += inp; tot["output"] += out
        tot["cache_read"] += cr; tot["cache_write"] += cw
        tot["cost"] += c
        p = by_purpose.setdefault(r.purpose or "other",
                                  {"calls": 0, "cost": 0.0, "cache_read": 0, "input": 0})
        p["calls"] += 1; p["cost"] += c; p["cache_read"] += cr; p["input"] += inp
        # Per client. "" is kept as its own bucket and named, never merged:
        # a spend report that silently attributes shared work to whichever
        # account happens to be first is worse than one that says how much it
        # could not split.
        who = (r.tenant or "").strip() or "unattributed"
        t = by_tenant.setdefault(who, {"calls": 0, "cost": 0.0})
        t["calls"] += 1; t["cost"] += c
    cacheable = tot["cache_read"] + tot["input"]
    hit_rate = round(100 * tot["cache_read"] / cacheable) if cacheable else 0
    # What we'd have paid with zero caching (cache reads billed as full input)
    naive = tot["cost"] + sum(
        int(r.cache_read) * PRICES.get(r.model, (3.0, 15.0))[0] * 0.90 / 1e6
        for r in rows)
    saved = round(naive - tot["cost"], 2)
    return {
        "window_days": days,
        "calls": tot["calls"],
        "cache_hit_rate_pct": hit_rate,
        "est_cost_usd": round(tot["cost"], 2),
        "est_saved_by_cache_usd": saved,
        "projected_monthly_usd": round(tot["cost"] / days * 30, 2) if days else 0,
        "tokens": {k: tot[k] for k in ("input", "output", "cache_read", "cache_write")},
        "by_tenant": {k: {"calls": v["calls"], "cost_usd": round(v["cost"], 2),
                          "share_pct": (round(100 * v["cost"] / tot["cost"])
                                        if tot["cost"] else 0)}
                      for k, v in sorted(by_tenant.items(),
                                         key=lambda kv: -kv[1]["cost"])},
        "attribution_note": (
            "rows logged before per-client attribution was wired appear as "
            "`unattributed` — that is historical, not shared overhead"
            if by_tenant.get("unattributed") else ""),
        "by_purpose": {k: {"calls": v["calls"], "cost_usd": round(v["cost"], 2),
                           "cache_hit_pct": round(100 * v["cache_read"] /
                                                  (v["cache_read"] + v["input"]))
                           if (v["cache_read"] + v["input"]) else 0}
                       for k, v in by_purpose.items()},
    }
