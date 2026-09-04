"""Are the connectors actually set up — publish, measure, and know what to write.

The question that prompted this (owner, 2026-08-25): *"make sure that our
connectors for these are set up correctly."* Asking it properly found the hole:
**nothing in this codebase had ever verified Search Console.**

`/health/connections` probes gmail and drive. `/health/seo` probes Semrush.
Neither asks Google whether the token can read Search Console — and there are
THREE Google scope lists here: `scripts/google_oauth.py` and
`oauth.FLOWS["google"]` both request `webmasters.readonly`,
`gmail_client.SCOPES` does not, and `ENV_GRANTS["google"]` grants `inbox`
ALONE. So an account reads "gmail ok · drive ok" forever while every GSC call
fails — and the entire Phase 3 measurement loop runs on GSC.

`systems.ready()` is not this. It checks the `requires` the catalogue declares,
which for `blog` is `cms`, and that is the right gate for PUBLISHING. Measuring
fails independently and for different reasons, fixed by different people —
so it is reported independently rather than folded into one green light.

    python3 scripts/test_blog_readiness.py
"""
import os
import pathlib
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'br.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import credentials, db, google_seo, kb, keywords, systems  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def org(key, domain, cms=None, model="ecom_inventory"):
    with db.SessionLocal() as s:
        s.add(db.Tenant(key=key, name=key.title(), kind="client", domain=domain,
                        business_model=model, cms=cms or {}, systems=[]))
        s.commit()


def connect(tenant, provider="shopify", scopes="write_content"):
    with db.SessionLocal() as s:
        s.add(db.Credential(tenant=tenant, provider=provider, site="", kind="oauth",
                            secret=credentials._encrypt("t"),
                            meta={"domain": f"{tenant}.myshopify.com"},
                            scopes=scopes, status="active", granted_at=db.utcnow()))
        s.commit()


def main() -> int:
    db.init_db()
    # Stubbed at the `google_seo` seam, never by replacing `_gsc_probe` — the
    # probe's own contract (a SENTENCE means failure, JSON means data) is one
    # of the things worth pinning, and a stubbed probe would assert nothing
    # about it.
    google_seo.gsc_list_sites = lambda profile: '[{"siteUrl": "sc-domain:x"}]'
    google_seo._resolve_gsc_site = lambda profile: "sc-domain:x"

    print("— an unknown account is refused, not reported as unready —")
    ck("named", keywords.readiness("nobody").get("error") == "unknown account")

    print("\n— publish: what is missing, and whose job it is —")
    org("nocms", "nocms.example")
    r = keywords.readiness("nocms")
    ck("no CMS is reported", r["publish"]["ok"] is False)
    ck("with the fix, not just the fault", "/connect/" in r["publish"]["fix"],
       r["publish"]["fix"][:80])

    org("noblog", "noblog.example", cms={"platform": "shopify"})
    connect("noblog")
    r = keywords.readiness("noblog")
    # NO BLOG CHOSEN IS NOT A FAULT ANY MORE (owner, 2026-09-04). It was, and
    # the consequence was a connected store sitting "not ready" while every
    # article it wrote was filed and never queued. `sites.ensure_blog` answers
    # the question now — the store's own blog when it holds one, ours
    # otherwise — so readiness states the destination and keeps the choice.
    from app import sites as _sites
    ck("a connected store with no blog chosen is READY, and says where it goes",
       r["publish"]["ok"] is True
       and _sites.FALLBACK_BLOG_TITLE in r["publish"]["detail"],
       str(r["publish"])[:150])
    ck("and it still asks for the choice, so the control is not lost",
       r["publish"].get("choose") is True, str(r["publish"])[:110])

    org("sq", "sq.example", cms={"platform": "squarespace"}, model="local_venue")
    r = keywords.readiness("sq")
    ck("squarespace fails at the CONNECTION, before the backend",
       r["publish"]["ok"] is False and "no CMS connected" in r["publish"]["detail"],
       "there is no squarespace provider to connect, so it never reaches "
       "sites.backend — and the fix it names is the true one")
    ck("and it names the platform in the fix",
       "squarespace" in r["publish"]["fix"], r["publish"]["fix"][:70])

    org("good", "good.example", cms={"platform": "shopify", "blog_id": "77"})
    connect("good")
    r = keywords.readiness("good")
    ck("a fully connected store publishes", r["publish"]["ok"] is True,
       str(r["publish"])[:100])
    ck("and says how it is wired", r["publish"]["via"] == "client:shopify")

    print("\n— measure: the capability is not the answer, the API is —")
    ck("the capability is reported alongside",
       keywords.readiness("good")["measure"]["capability"] == "not wired",
       "env-group Google grants `inbox` ALONE, so a working mailbox says "
       "nothing about Search Console")

    google_seo.gsc_list_sites = lambda profile: (
        "Search Console is not connected. Re-run scripts/google_oauth.py.")
    r = keywords.readiness("good")
    ck("a SENTENCE from the tool means failure, not data",
       r["measure"]["ok"] is False, str(r["measure"])[:120])
    ck("and the fix names the scope", "webmasters.readonly" in r["measure"]["fix"],
       r["measure"]["fix"][:90])

    google_seo.gsc_list_sites = lambda profile: '[{"siteUrl": "sc-domain:good.example"}]'
    google_seo._resolve_gsc_site = lambda profile: ""
    r = keywords.readiness("good")
    ck("a readable token with NO matching property is still not ready",
       r["measure"]["ok"] is False and "no property matches" in r["measure"]["detail"],
       str(r["measure"])[:130])

    google_seo._resolve_gsc_site = lambda profile: "sc-domain:good.example"
    r = keywords.readiness("good")
    ck("a token that reads the right property is ready",
       r["measure"]["ok"] is True, str(r["measure"])[:100])

    print("\n— knows what to write —")
    ck("an empty map is named", any("keyword map" in f for f in
                                    keywords.readiness("good")["knows_what_to_write"]["fix"]))
    keywords.upsert("good", "acrylic jug", volume=5000)
    kb.ensure_brand("good", "Good Co")
    r = keywords.readiness("good")
    ck("no claims is named", any("approved claims" in f
                                 for f in r["knows_what_to_write"]["fix"]),
       str(r["knows_what_to_write"]["fix"]))
    ck("no ban list is named", any("banned_claims" in f
                                   for f in r["knows_what_to_write"]["fix"]))
    kb.add_claim("good", "Made from BPA-free acrylic.", "spec sheet", [])
    with db.SessionLocal() as s:
        s.get(db.KbBrand, "good").banned_claims = ["handmade"]
        s.commit()
    r = keywords.readiness("good")
    ck("with a map, a claim and a ban list it knows what to write",
       r["knows_what_to_write"]["ok"] is True, str(r["knows_what_to_write"])[:130])

    print("\n— the switch counts too —")
    ck("every connector green but NOT INSTALLED is not ready",
       r["ok"] is False and r["switch"]["ok"] is False,
       "a green light on a pipeline that cannot run is the false assurance "
       "this whole check exists to refuse")
    ck("and it says to install it", "install" in r["switch"]["fix"],
       r["switch"]["fix"][:60])
    row = systems.create("good", "blog")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    r = keywords.readiness("good")
    ck("installed and live, with all three green, is ready", r["ok"] is True,
       str({k: v.get("ok") for k, v in r.items() if isinstance(v, dict)}))
    google_seo._resolve_gsc_site = lambda profile: ""
    ck("one red is not ready", keywords.readiness("good")["ok"] is False,
       "publishing and measuring fail independently; a single green light "
       "would hide whichever one is broken")

    print("\n— 'not checked' is not 'working' —")
    # The owner's live Plan tab for Miami Ironside showed a GREEN TICK beside
    # Measure — `client:google` — for an account whose Search Console returns
    # 403 insufficientPermissions. `readiness(probe=False)` read
    # `ok = "analytics" in caps`, which is the CAPABILITY, and the capability
    # is precisely what cannot answer this: Google being connected is not
    # Search Console answering. §2.29's defect, on the page built to detect
    # it, introduced by the person who spent the day removing it.
    org("hasgoogle", "hasgoogle.example")
    connect("hasgoogle", provider="google",
            scopes="https://www.googleapis.com/auth/gmail.modify")
    caps = credentials.wired_capabilities("hasgoogle")
    ck("the capability reports analytics as wired", "analytics" in caps, str(caps))
    m = keywords.readiness("hasgoogle", probe=False)["measure"]
    ck("but unprobed Measure is UNKNOWN, not ok", m["ok"] is None, str(m["ok"]))
    ck("and it says it did not check", "not checked" in m["detail"], m["detail"])
    ck("an account is never READY on an unchecked Measure",
       keywords.readiness("hasgoogle", probe=False)["ok"] is False)
    from app import admin_ui as _aui
    page = _aui.render_plan("s3cret", "hasgoogle")
    ck("Measuring reads '?' rather than a tick",
       "? <strong>Measuring</strong>" in page,
       "measuring is DOWNSTREAM of planning — stated, never a gate")
    ck("and offers the one control that answers it",
       "Check Search Console now" in page,
       "the thing that says it has no answer is where you ask for one")

    print("\n— a website alone is enough to scrape and check a brand —")
    # Owner, 2026-08-26: *"if I dont have a shopify, wordpress etc — can I just
    # have a source website in the connections tab to default to?"* The field
    # already existed and `tenant_set` already accepted it; nothing ever
    # RENDERED the box, so it was settable only at account creation and a
    # client whose site moved could not be corrected from the console at all.
    from app import admin_ui as _ui, compliance as _comp, harvest as _hv
    org("scrapeonly", "scrapeonly.example")          # no cms, no credential
    prof = keywords.sites.get("scrapeonly") if hasattr(keywords, "sites") else None
    from app import sites as _sites
    ck("an account with only a domain still has a site profile",
       _sites.get("scrapeonly")["domain"] == "scrapeonly.example")
    ck("and no platform, honestly", _sites.get("scrapeonly")["platform"] == "",
       "nothing is connected, so nothing is claimed")
    ck("publishing is correctly blocked",
       keywords.readiness("scrapeonly", probe=False)["publish"]["ok"] is False)
    ck("but the crawler takes a DOMAIN, not a backend",
       "base" in _comp.discover_pages.__code__.co_varnames,
       "the site is public — content_compliance declares requires=() for "
       "exactly this reason")
    ck("and both scrapers refuse only on a missing domain",
       "if not t.domain" in pathlib.Path("app/harvest.py").read_text()
       and "if not t.domain" in pathlib.Path("app/compliance.py").read_text())

    print("\n— and the box to set it is on the Connections tab —")
    ck("domain is an editable field", "domain" in _ui.FIELD_HELP)
    ck("its help says no connection is needed",
       "NO CONNECTION NEEDED" in _ui.FIELD_HELP["domain"][1])
    ck("it asks for a bare host",
       "no scheme" in _ui.FIELD_HELP["domain"][1],
       "https://acme.com/ in this field breaks the GSC property match and "
       "the crawler's URL joins alike")

    print("\n— which MARKET the research came from —")
    r = keywords.readiness("good", probe=False)["knows_what_to_write"]
    ck("the market is reported, not assumed silently", r.get("market") == "us",
       str(r.get("market")))
    ck("and an account that never chose one is told",
       any("market not set" in f for f in r["notes"]),
       "the default stays — it is right for most of these accounts — but a "
       "US default on a UK client pulls US volumes, competitors and questions "
       "into their map: wrong data, correctly filed, invisible")
    with db.SessionLocal() as s:
        s.get(db.Tenant, "good").analytics = {"semrush_db": "uk"}
        s.commit()
    r2 = keywords.readiness("good", probe=False)["knows_what_to_write"]
    ck("declaring one silences the warning",
       not any("market not set" in f for f in r2["notes"]), str(r2["notes"]))
    ck("and it never made a working account read NOT READY",
       keywords.readiness("good", probe=False)["knows_what_to_write"]["ok"] is True,
       "a warning that turns a working account red is one somebody learns to "
       "scroll past")
    ck("and the declared market is what gets used", r2["market"] == "uk", r2["market"])

    print("\n— which client's Search Console property, exactly —")
    # LOAD-BEARING under the shared-identity model the owner chose (2026-08-25):
    # one Google account granted viewer access on several clients' properties,
    # rather than each client running OAuth. With one token seeing many
    # properties, this match is the only thing keeping one client's rankings
    # out of another's report.
    from app.google_seo import _match_gsc_site

    def E(*urls):
        return [{"siteUrl": u, "permissionLevel": "siteOwner"} for u in urls]

    ck("a lookalike domain does NOT match",
       _match_gsc_site(E("https://shopacme.com/"), "acme.com") is None,
       "'acme.com' in 'https://shopacme.com/' is True as a substring — with "
       "that the only candidate it matched confidently and _save_link PINNED "
       "another client's property")
    ck("the apex domain property matches",
       _match_gsc_site(E("sc-domain:acme.com"), "acme.com") == "sc-domain:acme.com")
    ck("a www prefix property matches",
       _match_gsc_site(E("https://www.acme.com/"), "acme.com") == "https://www.acme.com/")
    ck("a host beneath a domain property matches",
       _match_gsc_site(E("sc-domain:acme.com"), "blog.acme.com") == "sc-domain:acme.com",
       "sc-domain:acme.com genuinely covers blog.acme.com")
    ck("an unverified permission is never a candidate",
       _match_gsc_site([{"siteUrl": "sc-domain:acme.com",
                         "permissionLevel": "siteUnverifiedUser"}], "acme.com") is None)
    ck("two plausible properties refuse to guess",
       _match_gsc_site(E("https://acme.com/uk/", "https://acme.com/us/"),
                       "acme.com") is None,
       "staging vs prod, or two clients — pinning is a person's job")

    print("\n— the blog id is a picker, not a URL-encoded JSON blob —")
    # This is a defect I introduced: the fix text told the owner to hand-build
    # a percent-encoded `cms` blob for /admin/tenant_set. That is not
    # configuration, it is a developer typing a database value into a URL bar.
    from app import admin_ui, web
    page = admin_ui.render_plan("s3cret", "noblog")
    ck("the gap offers a control, not an instruction",
       "Find the blogs on this store" in page,
       "act where you report — naming a missing value and sending somebody "
       "elsewhere to set it is two pages for one decision")
    ck("the account that HAS one is not nagged",
       "Find the blogs on this store" not in admin_ui.render_plan("s3cret", "good"))

    # The setter MERGES. /admin/tenant_set takes the whole JSON column, so
    # setting one key by hand meant rewriting platform and creds_key too —
    # and getting one wrong silently unwires the account.
    with db.SessionLocal() as s:
        s.get(db.Tenant, "noblog").cms = {"platform": "shopify",
                                          "creds_key": "noblog"}
        s.commit()
    web.admin_blog_set(key="s3cret", tenant="noblog", blog_id="77")
    with db.SessionLocal() as s:
        cms = s.get(db.Tenant, "noblog").cms
    ck("the blog id is set", cms.get("blog_id") == "77", str(cms))
    ck("and platform survived", cms.get("platform") == "shopify", str(cms))
    ck("and creds_key survived", cms.get("creds_key") == "noblog", str(cms))
    bad = web.admin_blog_set(key="s3cret", tenant="noblog", blog_id="News")
    with db.SessionLocal() as s:
        ck("a non-numeric id is refused",
           s.get(db.Tenant, "noblog").cms.get("blog_id") == "77",
           "Shopify addresses blogs by id; a title would 404 mid-publish")

    print("\n— and it is a SURFACE, not a JSON endpoint —")
    # The design flaw this closes (owner, 2026-08-25): *"where do I see the
    # high level SEO plan from which the blogs are built out?"* Nowhere. The
    # map lived in `/admin/keywords` as JSON, the console had no idea it
    # existed, and planning an article therefore meant typing a keyword in by
    # hand — the one thing the map exists to stop.
    from app import admin_ui
    page = admin_ui.render_plan("s3cret", "good", sub="architecture")
    for probe, why in (
            ("Switch", "the two that GATE planning lead the page"),
            ("Knows what to write", ""),
            ("Once it is written", "publishing and measuring are stated "
                                   "downstream, not rendered as blockers"),
            ("acrylic jug", "the map itself, not a link to it"),
            ("Propose the next articles", "the action is on the page that "
                                          "shows the state")):
        ck(f"the page shows {probe!r}", probe in page, why)
    ck("an empty map SAYS it is the system's half that is missing",
       "has not done its half" in admin_ui.render_plan(
           "s3cret", "nocms", sub="architecture"),
       "asking the owner to invent a keyword is the failure, not the prompt")
    ck("cross-account refuses rather than blending domains",
       "one site" in admin_ui.render_plan("s3cret", admin_ui.ALL),
       "head terms, clusters and positions are all per-domain")

    print("\n— progress is a section, not a JSON endpoint —")
    import re as _re
    from app import systems as _sys, web as _web
    _r = _sys.create("good", "blog") if not _sys.find("good", "blog") else _sys.find("good", "blog")
    with db.SessionLocal() as s:
        s.get(db.System, _r.id).status = "live"
        s.commit()
    keywords.upsert("good", "acrylic jug", status="published")
    keywords.record_reading("good", "acrylic jug", position=14.0, clicks=9)
    keywords.record_reading("good", "a page we did not write", position=6.0, clicks=30)
    flat = _re.sub(r"\s+", " ",
                   admin_ui.render_plan("s3cret", "good", sub="progress"))

    ck("the tracked row is there", "Articles we wrote" in flat)
    ck("and the CONTROL row beside it", "The rest of the site" in flat,
       "a rise on its own is a claim; a rise against the rest of the site "
       "over the same window is a finding")
    ck("a smaller position is explained as a positive gain",
       "a POSITIVE gain is an improvement" in flat,
       "the sign convention is the thing somebody misreports first")
    ck("it separates attributable from too-recent",
       "too recent to claim" in flat)
    goal_v = _re.sub(r"\s+", " ",
                     admin_ui.render_plan("s3cret", "good", sub="goal"))
    ck("with no goal it says so and does not invent one",
       "No goal set" in goal_v
       and "nobody chose is a target nobody can fail" in goal_v)
    ck("and the form to set it is RIGHT THERE",
       "Set the goal" in goal_v
       and 'action="/admin/keywords_goal"' in goal_v,
       "act where you report — set_goal was reachable only as a URL with four "
       "query parameters")

    _web.admin_keywords_goal(key="s3cret", tenant="good", organic_clicks="2000",
                             top3="8", top10="25", horizon_days="90")
    flat2 = _re.sub(r"\s+", " ",
                    admin_ui.render_plan("s3cret", "good", sub="goal"))
    ck("once set, attainment is shown against it",
       "2000" in flat2 and "No goal set" not in flat2)
    ck("and the form is pre-filled with what IS, not blank",
       'value="2000"' in flat2, "state before instructions")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
