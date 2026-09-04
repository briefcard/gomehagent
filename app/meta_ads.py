"""What happened to the ads, read back — and nothing written.

`systems.ad_creative` has said it out loud since it was written: *"no
ad-platform write is wired"*, and *"fed by hand until the output→ad-id join
exists"*. That join is this module, and it exists now.

**THE JOIN IS THE WHOLE PROBLEM, and pushing is not the answer.** The obvious
way to get an ad id is to create the ad ourselves, which means the system
spends the client's budget on copy nobody has approved in the place it
matters. So the join is made the other way round: the primary text of a Meta
ad is the string this system produced, so the ad can be FOUND by its own
words. Nothing is created, nothing is edited, no budget moves, and it works
whether the owner pasted our copy in themselves or built the ad from it.

**READ-ONLY, and that is a property of the module, not a habit.** Every call
here is a GET. There is no POST helper to reach for, so a future edit that
wanted to write would have to add one, which is a thing a reviewer can see.

**Matched on normalised text, not on equality.** Meta strips and re-wraps
whitespace, and an owner pasting copy adds and removes the odd character. The
comparable form is the same one the knowledge base uses for "is this the same
claim" — one definition of sameness across the codebase, so a match here means
what a match means everywhere else.
"""
from __future__ import annotations

import re

from . import credentials, db

#: Graph API version. Pinned rather than floating: a version bump changes
#: field names, and discovering that through a metric silently reading zero is
#: the worst way to find out.
API = "v21.0"
BASE = f"https://graph.facebook.com/{API}"

#: How long a read may take. Insights over a long window are slow, and a
#: sweep that hangs holds a worker that has other accounts to serve.
TIMEOUT = 45

#: The metrics worth carrying back. Deliberately short — every one of these
#: answers a question somebody actually asks of an ad, and a wide dict makes
#: the ledger row a place to dump the API response rather than a record of
#: what happened.
FIELDS = ("impressions", "clicks", "spend", "ctr", "cpc", "actions",
          # WHAT THE PURCHASES WERE WORTH. `actions` counts them; without
          # values there is no return on spend, only a click rate — and
          # ranking creative on clicks alone promotes the ad that got looked
          # at over the one that sold.
          "action_values")


def _cfg(tenant: str) -> tuple[dict, str]:
    """The stored Meta credential, or a refusal that says what to do.

    Refuses by name for both of its cases — nothing connected, and connected
    without an ad account chosen — because the fixes are different and a
    single "not configured" sends somebody to the wrong screen.
    """
    got = credentials.resolve(tenant, "meta_ads")
    if got.get("error"):
        return {}, str(got["error"])
    if not got.get("secret"):
        return {}, (f"{tenant} has no Meta Ads connection. Connect it on the "
                    f"Accounts tab — read access is enough for this.")
    acct = str(got.get("ad_account_id") or got.get("account_id") or "").strip()
    if not acct:
        return {}, (f"{tenant}'s Meta connection names no ad account, so "
                    f"there is nothing to read. Reconnect and choose one.")
    return {"token": got["secret"],
            "account": acct if acct.startswith("act_") else f"act_{acct}"}, ""


def _get(cfg: dict, path: str, params: dict) -> dict:
    """One read. Never raises — a metrics sweep that can take down the worker
    is worse than one that reports nothing this cycle."""
    import httpx
    try:
        r = httpx.get(f"{BASE}/{path}", timeout=TIMEOUT,
                      params={**params, "access_token": cfg["token"]})
    except Exception as exc:                                     # noqa: BLE001
        return {"error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
    if r.status_code >= 400:
        try:
            msg = (r.json().get("error") or {}).get("message", "")
        except Exception:                                        # noqa: BLE001
            msg = r.text[:200]
        return {"error": f"{r.status_code}: {msg}"[:300]}
    try:
        return r.json()
    except Exception:                                            # noqa: BLE001
        return {"error": "Meta returned something that was not JSON"}


def comparable(text: str) -> str:
    """The form two pieces of ad copy are compared in.

    `provenance.normalise` is the knowledge base's answer to "are these the
    same words", and reusing it means a match here means exactly what a match
    means when two claims are deduped. Emoji and the zero-width characters
    that survive a copy-paste are stripped first — they are invisible to the
    person who pasted and fatal to an equality test.
    """
    from . import provenance as prov
    t = re.sub(r"[​-‏⁠﻿]", "", str(text or ""))
    t = re.sub(r"[^\w\s.,!?'\"$%-]", " ", t)
    return prov.normalise(t)


def live_ads(tenant: str, *, limit: int = 200) -> dict:
    """Every ad on the account with the text it is running, plus its numbers.

    One page of ads with `insights` requested inline, because the alternative
    is one insights call per ad and an account with two hundred ads then costs
    two hundred round trips to answer one question.
    """
    cfg, why = _cfg(tenant)
    if why:
        return {"ok": False, "why": why, "ads": []}
    got = _get(cfg, f"{cfg['account']}/ads", {
        "limit": max(1, min(int(limit or 200), 500)),
        # THE PICTURE, not only the words. `image_url` and `thumbnail_url`
        # are what make "which creative worked" answerable at all — without
        # them this module could join copy to outcomes and say nothing about
        # the thing people actually saw.
        "fields": ("id,name,status,effective_status,"
                   "creative{body,object_story_spec,image_url,thumbnail_url},"
                   "insights.date_preset(maximum){" + ",".join(FIELDS) + "}")})
    if got.get("error"):
        return {"ok": False, "why": got["error"], "ads": []}

    out = []
    for a in got.get("data") or []:
        body = str(((a.get("creative") or {}).get("body") or "")).strip()
        if not body:
            # The text can also sit inside the story spec, which is where it
            # lives for a link ad. Absent from both is an image-only ad, and
            # there is nothing here to match on.
            spec = ((a.get("creative") or {}).get("object_story_spec") or {})
            body = str((spec.get("link_data") or {}).get("message") or "").strip()
        if not body:
            continue
        stats = ((a.get("insights") or {}).get("data") or [{}])[0]
        cre = (a.get("creative") or {})
        out.append({"ad_id": str(a.get("id") or ""),
                    "name": str(a.get("name") or ""),
                    "status": str(a.get("effective_status")
                                  or a.get("status") or ""),
                    "body": body, "key": comparable(body),
                    "image_url": str(cre.get("image_url") or ""),
                    "thumbnail_url": str(cre.get("thumbnail_url") or ""),
                    "metrics": {k: stats.get(k) for k in FIELDS
                                if stats.get(k) is not None}})
    return {"ok": True, "ads": out, "why": ""}


def _purchase_value(metrics: dict) -> float:
    """What the purchases attributed to an ad were worth, or 0."""
    for row in (metrics.get("action_values") or []):
        if str((row or {}).get("action_type") or "").endswith("purchase"):
            try:
                return float(row.get("value") or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def winners(tenant: str, *, limit: int = 200, top: int = 3,
            min_impressions: int = 1000) -> dict:
    """The account's best-performing ads THAT HAVE A PICTURE, best first.

    ROAS when the account reports purchase values, click-through rate when it
    does not — ranking on clicks alone promotes the ad that got looked at over
    the one that sold, and most accounts have both numbers. Ads under
    `min_impressions` are excluded whatever their rate: a 12% CTR on 40
    impressions is noise wearing a winner's number, and it is exactly the row
    that would top a naive sort.

    READ-ONLY, like everything else here, and never called on a schedule —
    see `creative.learn_winning_look`, whose only caller is a button.
    """
    got = live_ads(tenant, limit=limit)
    if not got["ok"]:
        return {"ok": False, "why": got["why"], "ads": [], "ranked_by": ""}
    rows = []
    for a in got["ads"]:
        if not a.get("image_url") and not a.get("thumbnail_url"):
            continue
        m = a.get("metrics") or {}
        try:
            impressions = int(float(m.get("impressions") or 0))
        except (TypeError, ValueError):
            impressions = 0
        if impressions < max(0, int(min_impressions or 0)):
            continue
        try:
            spend = float(m.get("spend") or 0)
            ctr = float(m.get("ctr") or 0)
        except (TypeError, ValueError):
            spend, ctr = 0.0, 0.0
        value = _purchase_value(m)
        rows.append({**a, "impressions": impressions, "spend": spend,
                     "ctr": ctr,
                     "roas": round(value / spend, 2) if spend > 0 and value else 0.0})
    if not rows:
        return {"ok": False, "ads": [], "ranked_by": "",
                "why": (f"no ad on this account has both a picture and "
                        f"{min_impressions} impressions yet, so there is "
                        f"nothing to learn a look from")}
    by_roas = any(r["roas"] for r in rows)
    rows.sort(key=lambda r: (r["roas"] if by_roas else r["ctr"]), reverse=True)
    return {"ok": True, "ads": rows[:max(1, int(top or 3))],
            "ranked_by": "roas" if by_roas else "ctr",
            "considered": len(rows), "why": ""}


def match(tenant: str, *, limit: int = 200) -> dict:
    """Join this account's drafted ad copy to the ads actually running.

    Writes `destination` (the ad id, so the row can be opened) and `outcome`
    (what it did) onto the `Output` rows that match. Only rows with no
    destination yet are touched: a join made once is a fact, and re-deriving
    it every sweep would let a later edit to the copy quietly break a link
    that was correct when it was made.

    Returns what it did AND what it could not do. An ad running text nobody
    here wrote is reported rather than dropped — it is usually the owner
    writing their own, which is worth knowing next to a system that claims to
    be drafting them.
    """
    got = live_ads(tenant, limit=limit)
    if not got["ok"]:
        return {"ok": False, "why": got["why"], "matched": 0}

    by_key: dict = {}
    for ad in got["ads"]:
        by_key.setdefault(ad["key"], ad)

    joined, seen_keys = 0, set()
    with db.SessionLocal() as s:
        rows = (s.query(db.Output)
                .filter(db.tenant_filter(db.Output, tenant),
                        db.Output.format == "ad_copy").all())
        for row in rows:
            key = comparable(row.body or "")
            if not key:
                continue
            seen_keys.add(key)
            ad = by_key.get(key)
            if not ad or (row.destination or "").startswith("meta:"):
                continue
            row.destination = f"meta:{ad['ad_id']}"
            row.outcome = {"source": "meta_ads", "status": ad["status"],
                           **ad["metrics"]}
            joined += 1
        if joined:
            s.commit()

    theirs = [a for k, a in by_key.items() if k not in seen_keys]
    return {"ok": True, "matched": joined, "live": len(by_key),
            "unmatched_live": len(theirs),
            "note": (f"{len(theirs)} ad(s) are running copy this system did "
                     f"not write" if theirs else ""),
            "why": ""}


#: Grouping results is `results.by` — one writer, so the Plan tab and the
#: weekly report cannot disagree about the same number. This module is the
#: CLIENT: it fetches and joins, and it does not also decide what the join
#: means.
