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


def log_usage(purpose: str, model: str, resp) -> None:
    try:
        u = resp.usage
        with db.SessionLocal() as s:
            s.add(db.Usage(
                purpose=purpose, model=model,
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


def report(days: int = 7) -> dict:
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    with db.SessionLocal() as s:
        rows = s.query(db.Usage).filter(db.Usage.at >= since).all()
    tot = {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
           "cost": 0.0}
    by_purpose: dict = {}
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
        "by_purpose": {k: {"calls": v["calls"], "cost_usd": round(v["cost"], 2),
                           "cache_hit_pct": round(100 * v["cache_read"] /
                                                  (v["cache_read"] + v["input"]))
                           if (v["cache_read"] + v["input"]) else 0}
                       for k, v in by_purpose.items()},
    }
