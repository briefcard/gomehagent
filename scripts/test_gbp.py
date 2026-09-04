"""Google Business Profile: the scope, the capability, the adapter, the probe.

Owner, 2026-09-04: "what are all the APIs I need to enable to make this
functional? … implement it correctly." The platform half is implemented here
and proven OFFLINE — Google's quota is 0 until the project is approved, so
nothing can be proven live yet, and every path below is driven with the
transport stubbed and the shapes taken from Google's reference pages.

What has to hold, and is computed rather than surveyed:

  · the scope is asked for in ONE place and mirrored in the three that must
    agree (the OAuth flow, the CLI, the privacy page Google reads);
  · a Google connection carrying the scope WIRES `gbp`; one without it does
    not; the env-group token never does;
  · the declared profile on the account is what `declared_capabilities`
    reports, and `systems.ready` lets a GBP system produce only when both
    halves hold;
  · every refusal the family produces before it works is NAMED with the
    owner's next move — the access form, the seven APIs, the re-connect;
  · the readers page, mask and sum the way Google documents, and the probe
    stops at the first refusal with that refusal on it.

Run: python3 scripts/test_gbp.py
"""
import os
import pathlib
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'gbp.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEY = "s3cret"

from app import credentials as cred, db, gbp, oauth, systems, tenants, web  # noqa: E402

_fail: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def connect_google(tenant: str, scopes: str) -> None:
    """One Google connection per account (tenant+provider+site is UNIQUE), so
    a re-connect UPDATES the row — the same thing `store_oauth` does."""
    with db.SessionLocal() as s:
        row = s.query(db.Credential).filter(
            db.Credential.tenant == tenant,
            db.Credential.provider == "google").first()
        if row is None:
            row = db.Credential(tenant=tenant, provider="google", site="")
            s.add(row)
        row.secret = cred._encrypt("refresh-1")
        row.scopes = scopes
        row.status = "active"
        row.granted_at = db.utcnow()
        s.commit()


def main() -> int:
    db.init_db()
    tenants.seed()
    T = "ironside"

    print("— 1. the scope, asked for once and mirrored where it must be —")
    flow = oauth.FLOWS["google"]["scopes"]
    ck("the Google flow asks for business.manage", gbp.SCOPE in flow)
    cli = (ROOT / "scripts" / "google_oauth.py").read_text()
    ck("…and the CLI that mirrors the flow asks for the same list",
       gbp.SCOPE in cli and all(s in cli for s in flow))
    priv = (ROOT / "app" / "web.py").read_text()
    ck("…and the privacy page Google reads names it, as it names the others",
       "<code>business.manage</code>" in priv
       and all(f"<code>{s.rsplit('/', 1)[-1]}</code>" in priv for s in flow))
    ck("the seven APIs Google's setup page lists are named, in code, once",
       len(gbp.APIS_TO_ENABLE) == 7 and "Google My Business API" in gbp.APIS_TO_ENABLE
       and "Business Profile Performance API" in gbp.APIS_TO_ENABLE)

    print("\n— 2. the capability: declared on the row, wired by the consent —")
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, T)
        t.gbp = {}
        s.commit()
    ck("no profile declared → not declared",
       tenants.declared_capabilities(T)["gbp"] is False)
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, T)
        t.gbp = {"account": "accounts/1", "location": "locations/9"}
        s.commit()
    ck("a declared location → declared",
       tenants.declared_capabilities(T)["gbp"] is True)
    connect_google(T, "https://www.googleapis.com/auth/gmail.modify "
                      "https://www.googleapis.com/auth/analytics.readonly")
    ck("a Google connection WITHOUT the scope does not wire gbp — a consent "
       "for the inbox must not read as reaching a listing",
       tenants.capabilities(T)["gbp"] is False
       and tenants.capabilities(T)["inbox"] is True)
    connect_google(T, "https://www.googleapis.com/auth/gmail.modify "
                      + gbp.SCOPE)
    ck("…and one WITH it does", tenants.capabilities(T)["gbp"] is True,
       str(cred.wired_capabilities(T)))
    ck("the wiring names how", cred.wired_capabilities(T).get("gbp") == "client:google")
    row = systems.find(T, "gbp_listing") or systems.create(T, "gbp_listing")
    gate = systems.ready(row)
    ck("with both halves, a GBP system can produce (its refusals are now "
       "knowledge, not a missing connection)", gate["can_produce"] is True,
       str(gate.get("impossible"))[:120])
    connect_google(T, "https://www.googleapis.com/auth/gmail.modify")
    gate = systems.ready(row)
    ck("…and without the scope it cannot, by name",
       gate["can_produce"] is False
       and any("gbp" in str(b) for b in gate["impossible"]),
       str(gate.get("impossible"))[:120])

    print("\n— 3. the field control accepts the declaration through the route —")
    from fastapi.testclient import TestClient
    c = TestClient(web.app, raise_server_exceptions=False)
    r = c.get(f"/admin/tenant_set?key={KEY}&tenant={T}&field=gbp"
              f"&value=%7B%22account%22%3A%22accounts%2F1%22%2C%22location%22%3A%22locations%2F9%22%7D")
    ck("tenant_set takes gbp as a JSON field",
       r.status_code == 200 and not r.json().get("error"), r.text[:120])
    page = c.get(f"/admin/ui?key={KEY}&tab=accounts&tenant={T}&sub=advanced").text
    ck("the account card carries the field, the probe link and the seven APIs",
       'name="field" value="gbp"' in page and "/admin/gbp_probe" in page
       and all(a in page for a in gbp.APIS_TO_ENABLE)
       and gbp.ACCESS_FORM in page)

    print("\n— 4. refusals are named with the owner's next move —")
    connect_google(T, "https://www.googleapis.com/auth/gmail.modify")
    got = gbp.accounts(T)
    ck("a connection without the scope refuses before any call, naming the "
       "re-connect", not got["ok"] and "business.manage" in got["error"]
       and "Connections tab" in got["error"], got["error"][:100])
    with db.SessionLocal() as s:
        for r_ in s.query(db.Credential).filter(db.Credential.tenant == T).all():
            r_.status = "revoked"
            r_.secret = ""
        s.commit()
    got = gbp.accounts(T)
    ck("no connection at all refuses by name",
       not got["ok"] and "no Google connection" in got["error"], got["error"][:100])
    ck("a 429 / quota error says the project is not approved and where to apply",
       gbp.ACCESS_FORM in gbp.named_refusal(429, "Quota exceeded for quota metric")
       and "0 until" in gbp.named_refusal(403, "RESOURCE_EXHAUSTED: quota"))
    ck("a disabled-API error names all seven APIs to enable",
       all(a in gbp.named_refusal(403, "Google My Business API has not been used in "
                                  "project 123 before or it is disabled")
           for a in gbp.APIS_TO_ENABLE))
    ck("a permission error names the scope and the manager requirement",
       "business.manage" in gbp.named_refusal(403, "The caller does not have permission")
       and "manager" in gbp.named_refusal(403, "The caller does not have permission"))

    print("\n— 5. the readers, against the documented shapes —")
    connect_google(T, gbp.SCOPE)
    real_tok, real_call = oauth.access_token, gbp.call
    oauth.access_token = lambda p, rt: {"ok": True, "token": "tok"}
    calls: list = []

    def _fake(tenant, method, url, *, params=None, payload=None):
        calls.append((method, url, params))
        if url.endswith("/v1/accounts"):
            return {"ok": True, "data": {"accounts": [
                {"name": "accounts/1", "accountName": "Ironside", "type": "LOCATION_GROUP"}]}}
        if url.endswith("/accounts/1/locations"):
            tok = (params or {}).get("pageToken", "")
            if not tok:
                return {"ok": True, "data": {"locations": [
                    {"name": "locations/9", "title": "Ironside Miami",
                     "websiteUri": "https://ironside.example",
                     "categories": {"primaryCategory": {"displayName": "Event venue"},
                                    "additionalCategories": [{"displayName": "Wedding venue"}]},
                     "metadata": {"mapsUri": "https://maps.google.com/?cid=1"}}],
                    "nextPageToken": "p2"}}
            return {"ok": True, "data": {"locations": [
                {"name": "locations/10", "title": "Ironside Annex"}]}}
        if url.endswith("/v1/locations/9"):
            return {"ok": True, "data": {"name": "locations/9", "title": "Ironside Miami",
                                         "profile": {"description": "A venue."},
                                         "regularHours": {"periods": []},
                                         "categories": {"primaryCategory": {"displayName": "Event venue"}}}}
        if url.endswith("/VoiceOfMerchantState"):
            return {"ok": True, "data": {"hasVoiceOfMerchant": True, "hasBusinessAuthority": True}}
        if ":fetchMultiDailyMetricsTimeSeries" in url:
            return {"ok": True, "data": {"multiDailyMetricTimeSeries": [{"dailyMetricTimeSeries": [
                {"dailyMetric": "CALL_CLICKS", "timeSeries": {"datedValues": [
                    {"date": {"year": 2026, "month": 9, "day": 1}, "value": "3"},
                    {"date": {"year": 2026, "month": 9, "day": 2}, "value": "4"}]}},
                {"dailyMetric": "WEBSITE_CLICKS", "timeSeries": {"datedValues": [
                    {"date": {"year": 2026, "month": 9, "day": 1}, "value": "10"}]}}]}]}}
        if url.endswith("/reviews"):
            return {"ok": True, "data": {"totalReviewCount": 2, "averageRating": 4.5, "reviews": [
                {"name": "accounts/1/locations/9/reviews/a", "starRating": "FIVE",
                 "reviewer": {"displayName": "A"}, "comment": "Great", "createTime": "2026-08-01T00:00:00Z",
                 "reviewReply": {"comment": "Thanks"}},
                {"name": "accounts/1/locations/9/reviews/b", "starRating": "FOUR",
                 "reviewer": {"displayName": "B"}, "comment": "Good", "createTime": "2026-08-02T00:00:00Z"}]}}
        if url.endswith("/localPosts"):
            return {"ok": True, "data": {"localPosts": [
                {"name": "accounts/1/locations/9/localPosts/p1", "summary": "Open Labor Day",
                 "topicType": "STANDARD", "state": "LIVE", "createTime": "2026-08-30T00:00:00Z"}]}}
        return {"ok": False, "error": f"unexpected {url}"}
    gbp.call = _fake
    try:
        acc = gbp.accounts(T)
        ck("accounts are read from Account Management v1",
           acc["ok"] and acc["accounts"][0]["name"] == "accounts/1"
           and calls[-1][1].startswith(gbp.ACCOUNTS), str(acc)[:100])
        locs = gbp.locations(T, "accounts/1")
        ck("locations are read from Business Information v1 with a readMask, "
           "EVERY page, nextPageToken on the same URL",
           locs["ok"] and [x["name"] for x in locs["locations"]] == ["locations/9", "locations/10"]
           and all("readMask" in (p or {}) for m, u, p in calls if u.endswith("/locations"))
           and [p.get("pageToken", "") for m, u, p in calls if u.endswith("/locations")] == ["", "p2"],
           str([p for m, u, p in calls if u.endswith("/locations")]))
        ck("…and the slim row carries the ranking fields — primary category, "
           "additional categories, website, maps link",
           locs["locations"][0]["primary_category"] == "Event venue"
           and locs["locations"][0]["additional_categories"] == ["Wedding venue"]
           and locs["locations"][0]["maps_uri"].startswith("https://maps"))
        one = gbp.location(T, "locations/9")
        ck("one listing is read with the sweep's mask",
           one["ok"] and one["location"]["title"] == "Ironside Miami"
           and calls[-1][2]["readMask"] == gbp.LOCATION_MASK)
        perf = gbp.performance(T, "locations/9", days=28)
        ck("performance sums each daily metric over the window, per location",
           perf["ok"] and perf["totals"]["CALL_CLICKS"] == 7
           and perf["totals"]["WEBSITE_CLICKS"] == 10
           and perf["totals"]["BUSINESS_DIRECTION_REQUESTS"] == 0
           and perf["days"] == 28, str(perf)[:120])
        ck("…asking for every metric by name, with the dated range as query fields",
           sorted(v for k, v in calls[-1][2] if k == "dailyMetrics") == sorted(gbp.METRICS)
           and any(k == "dailyRange.startDate.year" for k, v in calls[-1][2]))
        rev = gbp.reviews(T, "accounts/1", "locations/9")
        ck("reviews come from v4 under the account, with the answered share",
           rev["ok"] and rev["total"] == 2 and rev["answered"] == 1
           and rev["unanswered"] == 1 and calls[-1][1].startswith(gbp.V4)
           and "/accounts/1/locations/9/reviews" in calls[-1][1], str(rev)[:100])
        po = gbp.posts(T, "accounts/1", "locations/9")
        ck("posts come from v4 with the last post's date",
           po["ok"] and po["last"] == "2026-08-30T00:00:00Z"
           and po["posts"][0]["state"] == "LIVE")

        print("\n— 6. the probe: end to end, read only, stops at the first refusal —")
        with db.SessionLocal() as s:
            s.get(db.Tenant, T).gbp = {}
            s.commit()
        pr = gbp.probe(T)
        ck("with nothing declared, the probe lists accounts and locations and "
           "says what to declare — not blocked, because the listing exists",
           "blocked_on" not in pr and pr["accounts"] and len(pr["locations"]) == 2
           and "declare" in pr.get("next", ""), str(pr)[:160])
        with db.SessionLocal() as s:
            s.get(db.Tenant, T).gbp = {"account": "accounts/1", "location": "locations/9"}
            s.commit()
        pr = gbp.probe(T)
        ck("with the profile declared, the probe reads state, listing, reviews, "
           "posts and performance, and drops the raw payloads",
           pr.get("state", {}).get("live") is True
           and pr.get("listing", {}).get("location", {}).get("title") == "Ironside Miami"
           and "raw" not in pr["listing"]["location"]
           and pr["reviews"]["answered"] == 1 and pr["posts"]["last"]
           and pr["performance"]["totals"]["CALL_CLICKS"] == 7, str(pr)[:200])
        ck("…and always carries the setup checklist on the same JSON",
           pr["apis_to_enable"] == list(gbp.APIS_TO_ENABLE)
           and pr["access_form"] == gbp.ACCESS_FORM and pr["scope"] == gbp.SCOPE)
        r = c.get(f"/admin/gbp_probe?key={KEY}&tenant={T}")
        # A FRESH client for the wrong key: `c` visited the console in step 3
        # and holds its session cookie, which `admin_key` honours — so the
        # wrong key on that client is still an authenticated request.
        ck("the probe route answers with the same, admin-gated",
           r.status_code == 200 and r.json().get("reviews", {}).get("answered") == 1
           and TestClient(web.app).get(
               f"/admin/gbp_probe?key=wrong&tenant={T}").json().get("error"),
           f"{r.status_code} {r.text[:120]}")

        def _quota(tenant, method, url, **kw):
            return {"ok": False, "status": 429, "needs_owner": True,
                    "error": gbp.named_refusal(429, "Quota exceeded")}
        gbp.call = _quota
        pr = gbp.probe(T)
        ck("an unapproved project stops the probe at the first call, with the "
           "access form on the refusal",
           pr.get("blocked_on", "").startswith("Google has not approved")
           and gbp.ACCESS_FORM in pr["blocked_on"] and "accounts" not in pr,
           str(pr.get("blocked_on"))[:100])
    finally:
        gbp.call, oauth.access_token = real_call, real_tok

    print("\n— 7. the health line: declared vs wired, per account, no live call —")
    r = c.get(f"/health/connections?key={KEY}")
    line = (r.json().get("gbp") or {}).get(T, "")
    ck("/health/connections carries a gbp row per account naming the state "
       "and the probe", "declared locations/9" in line and "wired" in line
       and "/admin/gbp_probe" in line, line[:120])

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed — the platform half of Business Profile is built; "
          "Google's approval is what remains")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
