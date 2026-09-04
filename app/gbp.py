"""Google Business Profile — the transport adapter, read side.

THE LISTING IS THE RANKING SURFACE (INITIATIVE-gbp §4b). This module is the
one place the platform talks to Google's Business Profile APIs, the way
`omnisend.py` is for Omnisend: bare HTTP, a NAMED refusal for every way it
fails, instrumented at the `call` seam so a suite drives every path with the
transport stubbed.

WHAT THE OWNER HAS TO DO, IN ORDER (Google's own pages, read 2026-09-04:
developers.google.com/my-business/content/basic-setup and …/prereqs):

1. APPLY FOR ACCESS — it is a queue, not a switch. The GBP API contact form
   (`ACCESS_FORM`), quoting the Cloud PROJECT NUMBER, sent from an email that
   is owner or manager on the profile. Eligibility: a verified profile active
   60+ days with a live website. Until approval the quota is 0 QPM and every
   call below fails; approved is 300 QPM. The Google My Business API is not
   even listed in the console until the account is approved.
2. ENABLE, in that Cloud project, all seven APIs in `APIS_TO_ENABLE`.
3. CONNECT Google for the account on the Connections tab — the flow now asks
   for `SCOPE`; a connection made before it did shows "not granted:
   business.manage" on its card, and re-connecting once is the fix.
4. DECLARE the profile on the account (Accounts → advanced → `gbp`) as
   {"account": "accounts/…", "location": "locations/…"} — `probe` lists both
   so they are copied, never typed from memory.

Base hosts are from the reference pages (verified against the docs, not yet
against a live call — the first approved account proves them):

  Account Management v1    https://mybusinessaccountmanagement.googleapis.com/v1
  Business Information v1  https://mybusinessbusinessinformation.googleapis.com/v1
  Performance v1           https://businessprofileperformance.googleapis.com/v1
  Verifications v1         https://mybusinessverifications.googleapis.com/v1
  Google My Business v4.9  https://mybusiness.googleapis.com/v4  (posts, reviews)

Writes — patching a listing, publishing a post — are NOT here. They arrive
with the skills that hold their approval, so nothing in this module can
change a client's listing.
"""
from __future__ import annotations

import datetime as _dt

from . import credentials as cred, oauth

SCOPE = "https://www.googleapis.com/auth/business.manage"

#: The seven APIs Google's setup page says to enable, by their Cloud Console
#: names. Google My Business (v4.9) carries posts, reviews and media; Account
#: Management lists accounts; Business Information reads and patches the
#: listing; Verifications says whether the listing is live; Performance is
#: the metrics; Notifications and Place Actions are in the family the
#: approval covers, and enabling them later is a second visit for nothing.
APIS_TO_ENABLE = (
    "Google My Business API",
    "My Business Account Management API",
    "My Business Business Information API",
    "My Business Verifications API",
    "Business Profile Performance API",
    "My Business Notifications API",
    "My Business Place Actions API",
)
ACCESS_FORM = "https://support.google.com/business/contact/api_default"

ACCOUNTS = "https://mybusinessaccountmanagement.googleapis.com/v1"
INFO = "https://mybusinessbusinessinformation.googleapis.com/v1"
PERF = "https://businessprofileperformance.googleapis.com/v1"
VERIFY = "https://mybusinessverifications.googleapis.com/v1"
V4 = "https://mybusiness.googleapis.com/v4"
TIMEOUT = 30

#: A readMask is REQUIRED by Business Information and "everything" is refused.
#: This is what a listing sweep reads: the fields that move the map pack.
LOCATION_MASK = ("name,title,storefrontAddress,websiteUri,phoneNumbers,"
                 "regularHours,specialHours,categories,profile,serviceItems,"
                 "openInfo,metadata")
LIST_MASK = "name,title,storefrontAddress,websiteUri,categories,metadata"
METRICS = ("WEBSITE_CLICKS", "CALL_CLICKS", "BUSINESS_DIRECTION_REQUESTS",
           "BUSINESS_CONVERSATIONS")


def _leaf(s: str) -> str:
    return str(s).rsplit("/", 1)[-1]


def _bearer(tenant: str) -> tuple[str, str]:
    """(access token, refusal). Every refusal names what the owner does next."""
    c = cred.resolve(tenant, "google")
    if c.get("error"):
        return "", c["error"]
    if not c.get("secret"):
        return "", (f"{tenant} has no Google connection — connect Google for "
                    f"this account on the Connections tab; the flow asks for "
                    f"Business Profile access.")
    if c.get("source") == "env":
        # The env-group token was consented long before Business Profile was
        # asked for, and `credentials.ENV_GRANTS` lets an env Google grant
        # `inbox` only — the rule that stops it inventing `analytics`.
        return "", (f"{tenant}'s Google is the env-group token, which never "
                    f"consented to Business Profile — connect Google for "
                    f"this account on the Connections tab.")
    have = cred.granted_scopes(tenant).get("google")
    if have is not None and not any(_leaf(s) == _leaf(SCOPE) for s in have):
        return "", (f"{tenant}'s Google connection was made before Business "
                    f"Profile was asked for — not granted: business.manage. "
                    f"Re-connect Google once on the Connections tab.")
    tok = oauth.access_token("google", c["secret"])
    if not tok.get("ok"):
        return "", f"Google refused to mint a token: {tok.get('error', '')}"
    return tok["token"], ""


def named_refusal(status: int, msg: str) -> str:
    """Google's error, in the words of the thing the owner has to do.

    The family fails three ways before it ever works, and each has a
    different fix: the project is not approved (quota 0 → 429, or a 403 that
    names the quota), an API in the family is not enabled (403 "has not been
    used in project … or it is disabled"), a consent without the scope or a
    user who is not a manager (401/403 permission).
    """
    low = (msg or "").lower()
    if status == 429 or "quota" in low or "resource_exhausted" in low:
        return (f"Google has not approved Business Profile API access for "
                f"this project (the quota is 0 until it does) — apply at "
                f"{ACCESS_FORM} quoting the Cloud project number, from an "
                f"owner/manager email on the profile. If approval has landed, "
                f"this is the 300 requests/minute ceiling; wait a minute. "
                f"Google said: {msg[:160]}")
    if "has not been used" in low or "is disabled" in low or "not enabled" in low:
        return (f"an API in the Business Profile family is not enabled in the "
                f"Cloud project — enable all seven: "
                f"{', '.join(APIS_TO_ENABLE)}. Google said: {msg[:160]}")
    if status in (401, 403):
        return (f"Google refused the connection for Business Profile — "
                f"re-connect Google on the Connections tab so it asks for "
                f"business.manage, and make sure the Google user who connects "
                f"is an owner or manager on the profile. Google said: "
                f"{msg[:160]}")
    if status == 404:
        return (f"Google has no such account or location — check the `gbp` "
                f"declared on the Accounts tab against what the probe lists. "
                f"Google said: {msg[:160]}")
    return f"{status}: {msg[:200]}"


def _call(tenant: str, method: str, url: str, *, params=None,
          payload: dict | None = None) -> dict:
    """One authenticated call: ``{ok, data}`` or ``{ok: False, error}``."""
    token, why = _bearer(tenant)
    if why:
        return {"ok": False, "error": why, "needs_owner": True}
    import httpx
    try:
        r = httpx.request(method, url, params=params, json=payload,
                          headers={"Authorization": f"Bearer {token}"},
                          timeout=TIMEOUT)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False,
                "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
    if r.status_code < 400:
        try:
            return {"ok": True, "data": r.json() if r.content else {}}
        except Exception:                                        # noqa: BLE001
            return {"ok": True, "data": {}}
    try:
        body = r.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    err = (body.get("error") or {}) if isinstance(body, dict) else {}
    msg = str(err.get("message") or r.text[:200])
    return {"ok": False, "status": r.status_code, "needs_owner": True,
            "error": named_refusal(r.status_code, msg)}


# Replaceable so the suite can drive every path with the transport stubbed.
from . import toolcalls as _tc  # noqa: E402
call = _tc.instrument("gbp", _call)


def accounts(tenant: str) -> dict:
    """The Business Profile accounts the connected Google user manages."""
    res = call(tenant, "GET", f"{ACCOUNTS}/accounts", params={"pageSize": 20})
    if not res["ok"]:
        return res
    rows = (res["data"] or {}).get("accounts") or []
    return {"ok": True, "accounts": [
        {"name": a.get("name", ""), "title": a.get("accountName", ""),
         "type": a.get("type", "")} for a in rows]}


def _slim(loc: dict) -> dict:
    cats = loc.get("categories") or {}
    return {"name": loc.get("name", ""), "title": loc.get("title", ""),
            "website": loc.get("websiteUri", ""),
            "primary_category": (cats.get("primaryCategory") or {}).get(
                "displayName", ""),
            "additional_categories": [
                c.get("displayName", "")
                for c in (cats.get("additionalCategories") or [])],
            "maps_uri": (loc.get("metadata") or {}).get("mapsUri", "")}


def locations(tenant: str, account: str) -> dict:
    """Every location under one account, ALL pages — `nextPageToken` is
    followed on the same URL, the way Google documents it."""
    rows: list = []
    token, pages = "", 0
    while pages < 10:
        params: dict = {"readMask": LIST_MASK, "pageSize": 100}
        if token:
            params["pageToken"] = token
        res = call(tenant, "GET", f"{INFO}/{account}/locations", params=params)
        if not res["ok"]:
            return res
        data = res["data"] or {}
        rows += data.get("locations") or []
        pages += 1
        token = str(data.get("nextPageToken") or "")
        if not token:
            break
    return {"ok": True, "locations": [_slim(loc) for loc in rows]}


def location(tenant: str, name: str) -> dict:
    """One listing, the fields a sweep reads (`LOCATION_MASK`). `name` is
    ``locations/<id>``. `raw` rides along for the sweep; the probe drops it."""
    res = call(tenant, "GET", f"{INFO}/{name}", params={"readMask": LOCATION_MASK})
    if not res["ok"]:
        return res
    loc = res["data"] or {}
    return {"ok": True, "location": {**_slim(loc), "raw": loc}}


def voice_of_merchant(tenant: str, name: str) -> dict:
    """Is the listing LIVE — verified, and not suspended or disabled."""
    res = call(tenant, "GET", f"{VERIFY}/{name}/VoiceOfMerchantState")
    if not res["ok"]:
        return res
    d = res["data"] or {}
    return {"ok": True, "live": bool(d.get("hasVoiceOfMerchant")),
            "authority": bool(d.get("hasBusinessAuthority")),
            "wait_for_voice": bool(d.get("waitForVoiceOfMerchant")),
            "raw": d}


def performance(tenant: str, name: str, days: int = 28) -> dict:
    """Location-level totals over the window — calls, direction requests,
    website clicks, conversations. Coarse and per location on purpose:
    INITIATIVE-gbp §3, there is no per-post metric and never will be."""
    end = _dt.date.today() - _dt.timedelta(days=1)
    start = end - _dt.timedelta(days=max(1, days) - 1)
    params = [("dailyMetrics", m) for m in METRICS] + [
        ("dailyRange.startDate.year", start.year),
        ("dailyRange.startDate.month", start.month),
        ("dailyRange.startDate.day", start.day),
        ("dailyRange.endDate.year", end.year),
        ("dailyRange.endDate.month", end.month),
        ("dailyRange.endDate.day", end.day)]
    res = call(tenant, "GET", f"{PERF}/{name}:fetchMultiDailyMetricsTimeSeries",
               params=params)
    if not res["ok"]:
        return res
    totals = {m: 0 for m in METRICS}
    for block in (res["data"] or {}).get("multiDailyMetricTimeSeries") or []:
        for series in block.get("dailyMetricTimeSeries") or []:
            m = str(series.get("dailyMetric") or "")
            for dv in ((series.get("timeSeries") or {}).get("datedValues")
                       or []):
                try:
                    totals[m] = totals.get(m, 0) + int(dv.get("value") or 0)
                except (TypeError, ValueError):
                    continue
    return {"ok": True, "days": days, "from": start.isoformat(),
            "to": end.isoformat(), "totals": totals}


def reviews(tenant: str, account: str, name: str) -> dict:
    """Every review on the listing, and how many have an owner reply — the
    answered share is one of `gbp_listing`'s declared measures."""
    loc_id = name.rsplit("/", 1)[-1]
    rows: list = []
    token, pages, meta = "", 0, {}
    while pages < 10:
        params: dict = {"pageSize": 50}
        if token:
            params["pageToken"] = token
        res = call(tenant, "GET",
                   f"{V4}/{account}/locations/{loc_id}/reviews", params=params)
        if not res["ok"]:
            return res
        meta = res["data"] or {}
        rows += meta.get("reviews") or []
        pages += 1
        token = str(meta.get("nextPageToken") or "")
        if not token:
            break
    answered = sum(1 for r in rows if r.get("reviewReply"))
    return {"ok": True,
            "total": int(meta.get("totalReviewCount") or len(rows)),
            "average": meta.get("averageRating"),
            "answered": answered, "unanswered": len(rows) - answered,
            "reviews": [{"name": r.get("name", ""),
                         "rating": r.get("starRating", ""),
                         "reviewer": (r.get("reviewer") or {}).get(
                             "displayName", ""),
                         "comment": str(r.get("comment") or "")[:400],
                         "created": r.get("createTime", ""),
                         "replied": bool(r.get("reviewReply"))}
                        for r in rows]}


def posts(tenant: str, account: str, name: str) -> dict:
    """The posts on the listing, newest first as Google returns them."""
    loc_id = name.rsplit("/", 1)[-1]
    res = call(tenant, "GET",
               f"{V4}/{account}/locations/{loc_id}/localPosts",
               params={"pageSize": 20})
    if not res["ok"]:
        return res
    rows = (res["data"] or {}).get("localPosts") or []
    out = [{"name": p.get("name", ""), "summary": str(p.get("summary") or "")[:300],
            "type": p.get("topicType", ""), "state": p.get("state", ""),
            "created": p.get("createTime", "")} for p in rows]
    return {"ok": True, "posts": out,
            "last": max((p["created"] for p in out), default="")}


def probe(tenant: str) -> dict:
    """Prove the connection END TO END, read only: the connection, the
    accounts it manages, the locations under the declared (or only) account,
    and — once a location is declared — its live state, reviews, posts and
    28-day performance. Every refusal is named and the probe stops there, so
    the answer is always "what to do next", never a stack trace. Lists what
    the owner has to enable and where to apply, on the same JSON."""
    from . import tenants
    t = tenants.get(tenant)
    declared = dict((t.gbp or {}) if t else {})
    out: dict = {"tenant": tenant, "declared": declared, "scope": SCOPE,
                 "apis_to_enable": list(APIS_TO_ENABLE),
                 "access_form": ACCESS_FORM}
    if not t:
        out["blocked_on"] = f"unknown account {tenant!r}"
        return out
    acc = accounts(tenant)
    if not acc["ok"]:
        out["blocked_on"] = acc["error"]
        return out
    out["accounts"] = acc["accounts"]
    account = str(declared.get("account") or
                  (acc["accounts"][0]["name"] if acc["accounts"] else ""))
    if not account:
        out["blocked_on"] = ("the connected Google user manages no Business "
                             "Profile account — the user who connects must "
                             "be an owner or manager on the profile")
        return out
    locs = locations(tenant, account)
    if not locs["ok"]:
        out["blocked_on"] = locs["error"]
        return out
    out["account"] = account
    out["locations"] = locs["locations"]
    name = str(declared.get("location") or "")
    if not name:
        out["next"] = ("declare the profile on the Accounts tab (advanced → "
                       "gbp) as {\"account\": \"…\", \"location\": \"…\"}, "
                       "copied from the list above")
        return out
    for label, fn in (("state", lambda: voice_of_merchant(tenant, name)),
                      ("listing", lambda: location(tenant, name)),
                      ("reviews", lambda: reviews(tenant, account, name)),
                      ("posts", lambda: posts(tenant, account, name)),
                      ("performance", lambda: performance(tenant, name))):
        got = fn()
        if not got.get("ok"):
            out[label] = {"error": got.get("error", "")}
            continue
        got.pop("raw", None)
        if isinstance(got.get("location"), dict):
            got["location"].pop("raw", None)
        out[label] = got
    return out
