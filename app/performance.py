"""What the sending platform says happened, joined back to what we drafted.

The last open half of the loop. `Output` has carried an `outcome` column since
the table was written, commented "metrics, filled in later", and nothing ever
filled it — so the ledger could say which product went to which list and never
whether anybody opened it. Every "did this work" question was unanswerable
about the one channel this system actually operates.

**The join is `destination`.** Phase 2.1 made that column an outcome rather
than an intention: a drafted campaign records `esp:omnisend:campaign/<id>`,
which is exactly the id the analytics endpoint reports against. Without that
fix there would be nothing to join on — every row said `esp:omnisend` and
which campaign it became was lost.

**One call per account.** Omnisend's analytics endpoint allows ten requests a
minute and fifty-five a day per brand, so this asks for a breakdown by
campaign in a single request and matches locally. Asking per row would spend a
client's daily budget on a fortnight of sends.

**Status decides `published`, numbers do not.** A campaign mid-send already
has opens; recording those as its result files a number that is wrong and
never revisits it. Only a finished campaign is confirmed.
"""
from __future__ import annotations

import datetime as dt
import logging

from . import db, esp, ledger

log = logging.getLogger(__name__)

#: How the campaign id is encoded in `Output.destination` — written by
#: `_run_campaign_email` after the ESP call returns.
_MARK = ":campaign/"


def _sent_at(value: str):
    """The platform's own send time, or None.

    None is not a failure: `confirm_sent` then stamps now, and "we learned
    about it at this moment" is honest. A parsed-wrong date would be worse
    than an admitted approximation.
    """
    raw = str(value or "").strip().replace("Z", "+00:00")
    if not raw:
        return None
    try:
        got = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=dt.timezone.utc)


def _campaign_id(destination: str) -> str:
    d = str(destination or "")
    return d.rsplit(_MARK, 1)[1].strip() if _MARK in d else ""


def sync(tenant: str, *, days: int = 30) -> dict:
    """Bring one account's campaign results back into the ledger.

    Rows are matched by campaign id, and only rows we are still waiting on are
    touched — a confirmed send does not get re-confirmed on every sweep, which
    keeps this cheap and keeps `published_at` meaning the first time the
    platform said so rather than the last time we asked.
    """
    mod, refusal = esp.backend(tenant)
    if refusal:
        return {"ok": False, "why": refusal}
    if not hasattr(mod, "campaign_metrics"):
        # Named, not silent: a provider without a reports API is a real state,
        # and it is the difference between "nothing worked" and "nothing was
        # measurable".
        return {"ok": False, "why": (
            f"{esp.provider_for(tenant)} has no campaign reporting in this "
            f"integration — sends will stay unconfirmed until it does")}

    with db.SessionLocal() as s:
        rows = [(r.id, r.destination) for r in s.query(db.Output)
                .filter(db.tenant_filter(db.Output, tenant),
                        db.Output.format == "campaign_email",
                        db.Output.status != "published",
                        db.Output.destination.like(f"%{_MARK}%")).all()]
    waiting = {cid: oid for oid, dest in rows if (cid := _campaign_id(dest))}
    if not waiting:
        return {"ok": True, "confirmed": 0, "waiting": 0,
                "why": "no drafted campaign is waiting on a result"}

    got = mod.campaign_metrics(tenant, days=days)
    if not got.get("ok"):
        return {"ok": False, "why": got.get("error", "the ESP would not report"),
                "waiting": len(waiting)}
    metrics = got.get("campaigns") or {}

    confirmed, still, warnings = 0, 0, []
    for cid, output_id in waiting.items():
        state = mod.campaign(tenant, cid)
        if not state.get("ok"):
            still += 1
            continue
        status = state.get("status", "")
        if status in getattr(mod, "DEAD", ()):
            # It will never send. Recorded on the row so the sweep stops
            # asking and a person can see that the draft died in the platform.
            ledger.delivered(tenant, output_id,
                             f"esp:{esp.provider_for(tenant)}:{status}")
            continue
        if status not in getattr(mod, "FINISHED", ("sent",)):
            still += 1
            continue
        out = ledger.confirm_sent(
            tenant, output_id,
            at=_sent_at(state.get("sent_at")),
            outcome={**(metrics.get(cid) or {}), "campaign_id": cid,
                     "provider": esp.provider_for(tenant)})
        if out.get("ok"):
            confirmed += 1
            warnings += out.get("warnings") or []
    for w in warnings:
        log.warning("performance sync (%s): %s", tenant, w)
    return {"ok": True, "confirmed": confirmed, "waiting": still,
            "warnings": warnings, "measured": len(metrics)}


def sync_all(*, days: int = 30) -> dict:
    """Every account whose campaign system is on. Returns a per-account map."""
    from . import systems, tenants
    out: dict[str, dict] = {}
    for t in tenants.all_tenants():
        row = systems.find(t.key, "campaign_email")
        if not (row and systems.is_on(row)):
            continue
        try:
            out[t.key] = sync(t.key, days=days)
        except Exception as exc:                                 # noqa: BLE001
            log.exception("performance sync failed for %s", t.key)
            out[t.key] = {"ok": False, "why": f"{exc.__class__.__name__}"}
    return out
