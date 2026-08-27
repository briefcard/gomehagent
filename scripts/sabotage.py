"""Turn each guard off, and check the suite notices.

A test that passes is not evidence. A test that FAILS when the thing it
describes is broken is. This codebase has caught six tests passing for the
wrong reason — the portal cookie over http, `test_oauth` against a page that
stacked every account, a fixture with literal backslash-n, an authorisation
check on a client that had already signed in, an assertion about absence run
against an empty table, and a go-live gate that passed by never being asked.
Every one was found by accident.

So this does it on purpose. Each entry below disables ONE guard, runs the
suites that claim to cover it, and expects them to fail. Three outcomes:

    caught      the suite failed. The guard is genuinely tested.
    UNDETECTED  the guard was removed and every suite still passed. The
                tests around it are decoration.
    STALE       the code no longer contains what this entry patches. Says so
                loudly rather than reporting a pass, because a sabotage whose
                target has moved silently stops testing anything — which is
                the same failure this file exists to find, one level up.

The repo is restored after every entry, verified byte-for-byte, and a failure
to restore is fatal and shouted about. Nothing here is left applied.

    python3 scripts/sabotage.py            # all of them
    python3 scripts/sabotage.py shop_host  # one, by name
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: One entry per guard whose absence should be loud. `find` must appear exactly
#: once; `why` is the consequence in the world, not the mechanism — a person
#: reading a STALE report needs to know what stopped being covered.
SABOTAGES = [
    {
        "name": "ship_queue_is_scoped",
        "file": "app/admin_ui.py",
        "find": "            _q = _q.filter(db.Approval.tenant == tenant)",
        "replace": "            pass  # SABOTAGE",
        "suites": ["test_ship_section.py"],
        "why": "the Review tab's ship queue pools every client's approvals "
               "under whichever account is being looked at — the leak the "
               "whole console frame was rebuilt to prevent, on the page "
               "where a wrong decision executes",
    },
    {
        "name": "approving_writes_back",
        "file": "app/approvals.py",
        "find": "            if p.get(\"output_id\"):\n                keywords.mark_published(",
        "replace": "            if False:  # SABOTAGE\n                keywords.mark_published(",
        "suites": ["test_article_review.py"],
        "why": "the publish loop reopens: the live URL is discarded again, "
               "target_url/published_at never written, progress's tracked "
               "cohort starves, and the Plan board's live-page link can "
               "never render — the exact state the 2026-08-26 audit found",
    },
    {
        "name": "owner_edits_meet_the_ban_list",
        "file": "app/web.py",
        "find": "    if (refusal := seo_guard.check(profile, edited, what=\"article edit\")):",
        "replace": "    if False and (refusal := seo_guard.check(profile, edited, what=\"article edit\")):  # SABOTAGE",
        "suites": ["test_article_review.py"],
        "why": "an owner's edit can reintroduce a banned phrase and the save "
               "stops refusing it — the publish-time guard then fires on a "
               "text the owner already approved, which reads as the system "
               "overriding them",
    },
    # ---- 2026-08-26: ONE DEFECT, SEVEN PLACES ---------------------------
    #
    # Every entry below is the same shape, and it recurred all day: A VALUE
    # THAT WAS ASSUMED, DEFAULTED OR DECLARED, PRESENTED AS IF IT HAD BEEN
    # OBSERVED. DEFECTS §1 already names it — "unknown collapsed into a
    # value" — which is the point: naming a pattern does not stop it, and
    # every one of these was written by somebody who knew the rule.
    #
    # Each fix now has a test. None of them had been proven to FAIL when the
    # fix is removed, which by this file's own standard makes them decoration.
    {
        "name": "site_named_unknown_refuses",
        "file": "app/sites.py",
        "find": "        raise UnknownSite(\n            f\"No site profile for {site_key!r}",
        "replace": "        return sites.get(config.SEO_PRIMARY_SITE) or {}  # SABOTAGE\n        raise UnknownSite(\n            f\"No site profile for {site_key!r}",
        "suites": ["test_site_resolution.py"],
        "why": "site=coverings silently resolves to Baci again — an article "
               "queues against the wrong client's store, under a summary "
               "naming the right one, checked against the wrong ban list",
    },
    {
        "name": "backend_is_a_name_per_arm",
        "file": "app/sites.py",
        "find": "    mod = BACKENDS.get(platform)\n    if not mod:",
        "replace": "    mod = BACKENDS.get(platform) or \"shopify_seo\"  # SABOTAGE\n    if False:",
        "suites": ["test_site_resolution.py"],
        "why": "Squarespace borrows the Shopify client again and Ironside "
               "writes articles to a store that does not exist",
    },
    {
        "name": "env_group_is_a_registry",
        "file": "app/credentials.py",
        "find": "        elif _env_registry_hit(tenants.get(tenant), key):",
        "replace": "        elif env.get(\"secret\"):  # SABOTAGE",
        "suites": ["test_credentials.py"],
        "why": "a Shopify store configured with client_id/client_secret and no "
               "inline token reads MISSING in the console while working "
               "perfectly — the owner is asked to supply a credential twice",
    },
    {
        "name": "gsc_property_matches_on_boundaries",
        "file": "app/google_seo.py",
        "find": "        if ph and (ph == host or host.endswith(\".\" + ph)):",
        "replace": "        if ph and host in e[\"siteUrl\"]:  # SABOTAGE",
        "suites": ["test_blog_readiness.py"],
        "why": "under the shared-identity model one token sees several "
               "clients' properties, and 'acme.com' matches 'shopacme.com' "
               "again — pinned permanently, in a client's report",
    },
    {
        "name": "unprobed_measure_is_not_ok",
        "file": "app/keywords.py",
        "find": "        meas = {\"ok\": None,",
        "replace": "        meas = {\"ok\": \"analytics\" in caps,  # SABOTAGE",
        "suites": ["test_blog_readiness.py"],
        "why": "the Plan tab shows a green tick beside Measure for an account "
               "whose Search Console returns 403 — the capability answering a "
               "question only the API can",
    },
    {
        "name": "drafted_is_not_published",
        "file": "app/skill_pack.py",
        "find": "    head = (\"drafted and queued for approval\" if publish[\"queued\"]\n            else \"DRAFTED ONLY, nothing queued\")",
        "replace": "    head = \"drafted and queued for approval\"  # SABOTAGE",
        "suites": ["test_blog_skill.py"],
        "why": "a run that queued nothing reports the same sentence as one "
               "that queued an article — the owner goes looking in Shopify "
               "for something that was never sent",
    },
    {
        "name": "sync_rescores_what_it_read",
        "file": "app/keywords.py",
        "find": "    ranked = score(tenant)\n    return {\"tenant\": tenant, \"readings\": seen,",
        "replace": "    ranked = {\"scored\": 0, \"top\": []}  # SABOTAGE\n    return {\"tenant\": tenant, \"readings\": seen,",
        "suites": ["test_keyword_progress.py"],
        "why": "the nightly sync updates every position and leaves yesterday's "
               "ranking in place, so the best thing to write next keeps its "
               "old score until somebody presses Re-score",
    },
    {
        "name": "data_layer_lists_every_table",
        "file": "app/admin_ui.py",
        "find": "        if not name.startswith(\"Kb\"):",
        "replace": '        if name not in described:  # SABOTAGE',
        "suites": ["test_data_layer.py"],
        "why": "the Data layer tab goes back to a hand-maintained list and "
               "silently stops showing any table nobody remembered to add — "
               "which is how the photograph library became invisible",
    },
    {
        "name": "data_layer_says_what_to_fix",
        "file": "app/admin_ui.py",
        "find": "{_fix_list(key, tenant)}",
        "replace": "",
        "suites": ["test_data_layer.py"],
        "why": "the page goes back to a wall of row counts with nothing "
               "clickable, and the ranked work list readiness() already "
               "computes is rendered nowhere again",
    },
    {
        "name": "positioning_is_scoped",
        "file": "app/kb.py",
        "find": '                        db.KbClaim.entity_key != "",',
        "replace": "                        db.KbClaim.entity_key == db.KbClaim.entity_key,  # SABOTAGE",
        "suites": ["test_positioning.py"],
        "why": "a brand-wide position is reported as a contested one, so the "
               "drafter is warned about a disagreement that does not exist",
    },
    {
        "name": "drafts_are_not_catalogued",
        "file": "app/catalog_sync.py",
        "find": '            if state in ("draft", "archived"):',
        "replace": "            if False:  # SABOTAGE",
        "suites": ["test_kb_removal.py"],
        "why": "every Shopify draft becomes an approved catalogue entity again "
               "— the pollution the owner reported, in every account",
    },
    {
        "name": "removing_an_entity_takes_its_claims",
        "file": "app/kb.py",
        "find": "        if kind == \"entity\":",
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_kb_removal.py"],
        "why": "a claim scoped to a removed entity is left behind unreachable "
               "— it cannot be offered and cannot even be edited, because the "
               "editor validates its key against active entities",
    },
    {
        "name": "a_removed_tag_is_not_vocabulary",
        "file": "app/kb.py",
        "find": ('                if (r.review or "") != prov.REJECTED\n'
                 '                and (include_proposed or (r.review or "") != prov.PROPOSED)}'),
        "replace": "                if True}  # SABOTAGE",
        "suites": ["test_kb_removal.py"],
        "why": "a situation tag somebody removed goes on validating new claims "
               "for ever",
    },
    {
        "name": "angle_is_not_the_subject",
        "file": "app/skill_pack.py",
        "find": '    line = _named or (proof.split(".")[0] if proof else "") or seg["name"]',
        "replace": '    line = (goal or seg.get("angle") or "A quick note").split(".")[0]  # SABOTAGE',
        "suites": ["test_campaign_variety.py"],
        "why": "the internal brief written for the drafter goes back into the "
               "customer-facing subject line, on every model-less send",
    },
    {
        "name": "library_shows_only_owned",
        "file": "app/admin_ui.py",
        "find": '    shots = [a for a in kbm.assets(tenant, publishable_only=True, kind="image")',
        "replace": '    shots = [a for a in kbm.assets(tenant, publishable_only=False, kind="image")  # SABOTAGE',
        "suites": ["test_photo_library.py"],
        "why": "a picture the client does not own is listed as theirs to "
               "publish, in the one place that reads as 'these are yours'",
    },
    {
        "name": "propose_leads_an_empty_queue",
        "file": "app/admin_ui.py",
        "find": "        lead = propose if not total else \"\"",
        "replace": '        lead = ""  # SABOTAGE',
        "suites": ["test_workflow_ui.py"],
        "why": "the one press that fills every required field goes back under "
               "a fold labelled 'Cadence', and an empty queue leads with the "
               "eight-field hand form again",
    },
    {
        "name": "toggle_says_why_it_cannot_move",
        "file": "app/admin_ui.py",
        "find": '    elif r["ready"]:',
        "replace": "    elif True:  # SABOTAGE",
        "suites": ["test_systems_check.py"],
        "why": "a system that cannot go live offers a switch that will be "
               "refused by the server, instead of a disabled one naming the "
               "connection it is missing",
    },
    {
        "name": "attention_carries_the_runs",
        "file": "app/systems.py",
        "find": '            if len(b["examples"]) < max(1, int(examples)):',
        "replace": "            if False:  # SABOTAGE",
        "suites": ["test_systems_check.py"],
        "why": "Systems check goes back to ranking problems it cannot show you "
               "one example of — the exact uselessness of the flat refused "
               "list it replaced",
    },
    {
        "name": "picture_queue_form_wiring",
        "file": "app/admin_ui.py",
        "find": '<form id="picsform" method="post" action="/admin/assets_decide"></form>',
        "replace": '<form id="pics" method="post" action="/admin/assets_decide"></form>',
        "suites": ["test_admin_forms.py"],
        "why": "the id collides with the anchor div above it, every control "
               "associates with a non-form element, and approving a photograph "
               "silently does nothing on a page that looks perfectly normal",
    },
    {
        "name": "proof_belongs_to_subject",
        "file": "app/coherence.py",
        "find": "        elif kind == \"entity\" and proof_ok and scope not in proof_ok:",
        "replace": "        elif False:  # SABOTAGE",
        "suites": ["test_coherence.py"],
        "why": "one product is substantiated with another product's facts — an "
               "ad for the pitcher proved by a claim about the platter",
    },
    {
        "name": "withhold_false_or_forbidden",
        "file": "app/skill_pack.py",
        "find": "    if final_html and not _forbidden:",
        "replace": "    if final_html:  # SABOTAGE",
        "suites": ["test_campaign_variety.py", "test_campaign_email.py"],
        "why": "an email carrying a banned claim, a fabricated deadline or a "
               "product nobody can buy is placed in the client's sending "
               "platform, one click from a list",
    },
    {
        "name": "coherence_gate",
        "file": "app/skill.py",
        "find": "            found = _coherence(text)",
        "replace": "            found = []  # SABOTAGE",
        "suites": ["test_coherence.py"],
        "why": "an email ships whose hero photograph is of a different product "
               "than the one it is selling, and whose proof is asserted twice — "
               "every part grounded, none of them agreeing",
    },
    {
        "name": "commitment_narrowing",
        "file": "app/skill_pack.py",
        "find": "    picked = list(dict.fromkeys(picked))",
        "replace": "    picked = []  # SABOTAGE",
        "suites": ["test_coherence.py"],
        "why": "the offered candidate list is never collapsed to what the "
               "drafter chose, so the hero, the cards and the copy are each "
               "selected from a different set and drift apart",
    },
    {
        "name": "coherence_not_a_kb_gap",
        "file": "app/systems.py",
        "find": '            if str(reason).startswith("coherence:"):',
        "replace": "            if False:  # SABOTAGE",
        "suites": ["test_coherence.py"],
        "why": "quality failures pile into the knowledge-base backlog, sending "
               "somebody to author claims that could never have prevented them",
    },
    {
        "name": "tenant_scope",
        "file": "app/diagnostics.py",
        "find": "    return q.filter(model.tenant == tenant) if tenant else q",
        "replace": "    return q  # SABOTAGE",
        "suites": ["test_diagnostics.py"],
        "why": "one client's runs, tool calls and failures appear on another "
               "client's Diagnostics page",
    },
    {
        "name": "shipments_scope",
        "file": "app/memory.py",
        "find": ('        if tenant != "*":\n'
                 '            q = q.filter(db.tenant_filter(db.Shipment, tenant,\n'
                 '                                          include_unassigned=True))'),
        "replace": "        pass  # SABOTAGE",
        "suites": ["test_tenant_isolation.py"],
        "why": "one client's open shipments are injected into another client's "
               "drafting prompt on the live mail path",
    },
    {
        "name": "whatsapp_webhook_sig",
        "file": "app/web.py",
        "find": '    if not _verify_meta_sig(raw, request.headers.get("x-hub-signature-256", "")):',
        "replace": "    if False:  # SABOTAGE",
        "suites": ["test_console_auth.py"],
        "why": "a forged POST to the WhatsApp webhook approves, executes and "
               "commands the agent with no signature check",
    },
    {
        "name": "telegram_webhook_sig",
        "file": "app/web.py",
        "find": "    if not (expected and hmac.compare_digest(sent, expected)):",
        "replace": "    if False:  # SABOTAGE",
        "suites": ["test_console_auth.py"],
        "why": "a forged POST to the Telegram webhook — the live ops channel — "
               "reaches approve/execute when the secret is unset (fail open)",
    },
    {
        "name": "esp_unknown_token",
        "file": "app/esp.py",
        "find": ("    unknown = sorted({m.group(1).strip() for m in _TOKEN_RE.finditer(html or \"\")}\n"
                 "                     - set(TOKENS))"),
        "replace": "    unknown = []  # SABOTAGE",
        "suites": ["test_esp.py"],
        "why": "a typo'd personalization token ships to the customer as literal "
               "text instead of being caught before the draft",
    },
    {
        "name": "asset_rights_gate",
        "file": "app/kb.py",
        "find": "            q = q.filter(db.KbAsset.rights == OWNED)",
        "replace": "            pass  # SABOTAGE",
        "suites": ["test_campaign_visual.py", "test_assets.py"],
        "why": "a competitor's photograph saved as inspiration becomes "
               "selectable imagery and ships as the hero of a customer's "
               "campaign email",
    },
    {
        "name": "segments_dry_run_gate",
        "file": "app/segments.py",
        "find": ('        if not apply:\n'
                 '            would.append({"key": s["key"], "name": s["name"]})\n'
                 '            continue'),
        "replace": "        pass  # SABOTAGE — dry-run creates for real",
        "suites": ["test_segments.py"],
        "why": "the read-only preview of segment building CREATES segments in "
               "a client's live ESP on every page load — the poller/prefetch "
               "class of incident this codebase already paid for at ~200 "
               "queued drafts",
    },
    {
        "name": "claim_edit_reattests",
        "file": "app/web.py",
        "find": ("    if not timeless:\n"
                 "        kbm.set_claim_expiry(claim_id)"),
        "replace": "    pass  # SABOTAGE — edits stop re-dating the claim",
        "suites": ["test_kb_ui.py"],
        "why": "editing an approved claim stops resetting its expiry, so a "
               "fact the owner just re-attested still comes due on the OLD "
               "clock — or, edited a year in, never gets asked about again "
               "the way the owner's resave rule promises",
    },
    {
        "name": "email_legal_footer",
        "file": "app/email_render.py",
        "find": "    rows.append(_footer(t))",
        "replace": "    pass  # SABOTAGE",
        "suites": ["test_email_render.py"],
        "why": "a marketing email renders with no unsubscribe link and no "
               "physical address — illegal to send under CAN-SPAM",
    },
    {
        "name": "theme_review_gate",
        "file": "app/brand_theme.py",
        "find": "    return dict(row.theme or {})",
        "replace": "    return dict(row.theme or ((row.theme_proposed or {})"
                   ".get(\"theme\") or {}))  # SABOTAGE",
        "suites": ["test_brand_theme.py"],
        "why": "a machine-derived, never-reviewed brand theme — logo, palette, "
               "mailing address — ships in customer emails without the owner "
               "ever approving the look",
    },
    {
        "name": "campaign_draft_gate",
        "file": "app/skill_pack.py",
        # RE-POINTED 2026-08-24. The old target — a single `if` that withheld
        # the draft when anything at all was wrong — was removed on 2026-08-22,
        # because withholding it also took away the only view the owner had of
        # the work ("how else will I see it and send it?"). The gate did not
        # disappear, it narrowed: a defective draft is still made and marked
        # [NEEDS FIX], and only a FORBIDDEN one is kept out of the platform.
        # This entry had been covering nothing since that change.
        "find": ("    _forbidden = [f for f in (hard + list(item.get(\"failures\") or []))\n"
                 "                  if str(f.get(\"rule\", \"\")) in WITHHOLD_FROM_ESP]"),
        "replace": "    _forbidden = []  # SABOTAGE",
        "suites": ["test_campaign_email.py", "test_campaign_variety.py"],
        "why": "a campaign email that states something false or forbidden in "
               "the client's name is drafted into their live ESP anyway — one "
               "click from a list, over their sending domain",
    },
    {
        "name": "banned_claims_mail",
        "file": "app/triage.py",
        "find": ('        hard = [f for f in report["failures"]\n'
                 '                if f["rule"] in ("banned_claim", "entity_unavailable")]'),
        "replace": "        hard = []  # SABOTAGE",
        "suites": ["test_grounding.py", "test_tenant_isolation.py"],
        "why": "a phrase the client has banned goes out to a customer",
    },
    {
        "name": "guidance_reaches_prompt",
        "file": "app/resolve.py",
        "find": "        guidance = _sys.guidance_block(tenant, system)",
        "replace": '        guidance = ""  # SABOTAGE',
        "suites": ["test_grounding.py"],
        "why": "corrections written on the Systems card never reach a draft — "
               "the loop measures itself and learns nothing",
    },
    {
        "name": "craft_leak_guard",
        "file": "app/craft.py",
        "find": "    return sorted(set(found))",
        "replace": "    return []  # SABOTAGE",
        "suites": ["test_craft.py"],
        "why": "one client's names, products and domains travel into another "
               "client's prompt",
    },
    {
        "name": "shop_host",
        "file": "app/oauth.py",
        "find": '    return host if _SHOP_RE.match(host) else ""',
        "replace": "    return host  # SABOTAGE",
        "suites": ["test_shopify_oauth.py"],
        "why": "our Shopify client_id and client_secret are POSTed to whatever "
               "host an attacker puts in a link",
    },
    {
        "name": "webhook_signature",
        "file": "app/shopify_webhooks.py",
        "find": "    return hmac.compare_digest(want, header)",
        "replace": "    return True  # SABOTAGE",
        "suites": ["test_shopify_compliance.py"],
        "why": "anyone who finds the URL can forge a privacy request and make "
               "us delete a store's credentials",
    },
    {
        "name": "one_reply_per_thread",
        "file": "app/replies.py",
        "find": '    if not held or held["system"] == system_key:',
        "replace": "    if True:  # SABOTAGE",
        "suites": ["test_replies.py"],
        "why": "two systems answer the same customer on the same thread",
    },
    {
        "name": "the_switch",
        "file": "app/systems.py",
        "find": '    return (getattr(system, "status", "") or "") == "live"',
        "replace": "    return True  # SABOTAGE",
        "suites": ["test_replies.py", "test_worker_systems.py"],
        "why": "a paused system keeps running — the off switch does nothing",
    },
    {
        "name": "compliance_double_run",
        "file": "app/worker.py",
        "find": "                compliance.record_scan(\n                    t.key, compliance.scan(t.key, limit=60, since=since))",
        "replace": ("                compliance.record_scan(\n"
                    "                    t.key, compliance.scan(t.key, limit=60, since=since))\n"
                    "                systems.start_run(site.id, t.key, trigger='schedule')  # SABOTAGE"),
        "suites": ["test_correlate.py"],
        "why": "every compliance scan is recorded twice, halving every rate "
               "computed from the ledger",
    },
    {
        "name": "sweep_survives_no_model",
        "file": "app/correlate.py",
        "find": '    if not config.ANTHROPIC_API_KEY:\n        return ""',
        "replace": '    if not config.ANTHROPIC_API_KEY:\n        raise RuntimeError("SABOTAGE")',
        "suites": ["test_correlate.py"],
        "why": "the nightly sweep goes silent when the API key expires, and "
               "silence from a monitor is indistinguishable from all-clear",
    },
    {
        "name": "client_credential_reaches_publish",
        "file": "app/connections.py",
        "find": "    tenant = tenant_for_site(site_key)\n    if tenant:",
        "replace": "    tenant = tenant_for_site(site_key)\n    if False:  # SABOTAGE",
        "suites": ["test_connections.py"],
        "why": "a client who connected their own Shopify or WordPress through "
               "the console is told to edit an env var, and cannot publish at "
               "all if they were never in one \u2014 the connection is real, "
               "verified, shown as connected, and unreadable by the only two "
               "modules that write to their live site",
    },
    {
        "name": "handles_resolved_once",
        "file": "app/tool_scope.py",
        "find": "        if not resolved.get(param):",
        "replace": "        if not account_for(tenant, param):  # SABOTAGE",
        "suites": ["test_connections.py"],
        "why": "building one tool list costs a database read per scoped tool "
               "and an SEO_SITES_JSON parse per site-scoped one \u2014 48 and 27 "
               "of them, on every turn of every agent",
    },
    {
        "name": "gateway_logs_usage",
        "file": "app/llm.py",
        "find": "    usage.log_usage(purpose, chosen, msg, tenant=tenant)",
        "replace": "    pass  # SABOTAGE",
        "suites": ["test_llm.py"],
        "why": "the model spend of every migrated caller stops being recorded, "
               "and a spend report that omits most of the spend is worse than "
               "none because it gets believed",
    },
    {
        "name": "no_unattributed_call_site",
        "file": "app/triage.py",
        "find": "    usage.log_usage(\"classify\", config.CLASSIFY_MODEL, msg, tenant=tenant)",
        "replace": "    pass  # SABOTAGE",
        "suites": ["test_llm.py"],
        "why": "a module can call the API without recording it and no test "
               "notices \u2014 which is how nine of twenty-six call sites came "
               "to be the only attributed ones",
    },
    {
        "name": "oauth_route_named_for_api_key_providers",
        "file": "app/credentials.py",
        "find": "        oauth_why = oauth.configured(key) if has_oauth else \"\"",
        "replace": "        oauth_why = \"\"  # SABOTAGE",
        "suites": ["test_connect_ui.py"],
        "why": "Shopify's one-click route disappears from every screen with no "
               "reason attached, so connecting a store means walking a merchant "
               "through developer settings, nine API scopes and a token shown "
               "once \u2014 while the easy route sits one env var away and "
               "nothing says so",
    },
    {
        "name": "adapter_round_trips_recorded",
        "file": "app/toolcalls.py",
        "find": "                record(tenant, f\"{provider}:{verb} {clean_path(path)}\",",
        "replace": "                return  # SABOTAGE\n                record(tenant, f\"{provider}:{verb} {clean_path(path)}\",",
        "suites": ["test_toolcalls.py"],
        "why": "every Shopify and WordPress round trip vanishes from the "
               "ledger again, so Diagnostics reports the two platforms that "
               "run every day as untimed \u2014 and an untimed call reads as "
               "fast rather than as unmeasured",
    },
    {
        "name": "model_tool_calls_gated",
        "file": "app/tools.py",
        "find": "    args, refusal = tool_scope.guard(name, args, tenant)",
        "replace": "    refusal = \"\"  # SABOTAGE",
        "suites": ["test_tenant_isolation.py", "test_scope.py"],
        "why": "a model can address another client's store or inbox from "
               "either loop \u2014 the kernel's and the mail path's now share "
               "this one door, so removing it opens both",
    },
    {
        "name": "one_layer_per_provider",
        "file": "app/toolcalls.py",
        "find": "        if r.provider in platform_layer and r.source != \"adapter\":\n            continue          # counted from the round trip instead",
        "replace": "        pass  # SABOTAGE",
        "suites": ["test_toolcalls.py"],
        "why": "instrumenting the adapters doubles every provider total and "
               "HALVES its failure rate, so a completely dead token reads 0.5 "
               "\u2014 exactly the line this report draws between a broken "
               "connection and the internet",
    },
    {
        "name": "wordpress_blog_reads_callable",
        "file": "app/wordpress_seo.py",
        "find": "    post = _get(profile, f\"posts/{article_id}\", {\"context\": \"edit\"})",
        "replace": "    post = _send(profile, \"GET\", f\"posts/{article_id}\", params={\"context\": \"edit\"})  # SABOTAGE",
        "suites": ["test_toolcalls.py"],
        "why": "the 'review and revise existing articles' half of the blog "
               "path raises TypeError before reaching WordPress \u2014 "
               "`_send` takes `body` positionally and has no `params`",
    },
    {
        "name": "plan_edit_carry_forward",
        "file": "app/systems.py",
        "find": "                if fk in edited:",
        "replace": "                if False:  # SABOTAGE",
        "suites": ["test_plans.py"],
        "why": "a planner re-proposing an item writes straight over the "
               "owner's hand-set plan fields \u2014 the segment or date he "
               "corrected silently reverts on the next planning pass, the "
               "exact failure the theme deriver's rule 3 exists to prevent",
    },
    {
        "name": "planner_double_file",
        "file": "app/systems.py",
        "find": "        existing = _open_plan_row(s, row.id, ref)",
        "replace": "        existing = None  # SABOTAGE",
        "suites": ["test_plans.py"],
        "why": "every planning pass files the same item again \u2014 the "
               "queue fills with duplicates and a campaign is drafted once "
               "per copy, the record_scan double-file defect one layer up",
    },
    {
        "name": "plan_complete_gate",
        "file": "app/systems.py",
        "find": "    comp = plan_complete(row, sysrow.key)\n    if not comp[\"complete\"]:",
        "replace": "    comp = plan_complete(row, sysrow.key)\n    if False:  # SABOTAGE",
        "suites": ["test_plans.py"],
        "why": "an under-specified plan executes \u2014 a campaign with no "
               "segment or no date runs anyway, which is the owner's "
               "'complete brief in advance of execution' requirement removed "
               "at its only enforcement point",
    },
    {
        "name": "plan_switch_gate",
        "file": "app/systems.py",
        "find": "    if not is_on(sysrow):",
        "replace": "    if False:  # SABOTAGE",
        "suites": ["test_plans.py"],
        "why": "a paused system's queued plans keep executing \u2014 pausing "
               "is the one action whose entire meaning is stop, and the "
               "switch would no longer dictate at the queue",
    },
    {
        "name": "planner_month_cap",
        "file": "app/planner.py",
        "find": "            if have.get(_month(d), 0) < cad[\"per_segment_monthly\"]:",
        "replace": "            if True:  # SABOTAGE",
        "suites": ["test_planner.py"],
        "why": "the planner ignores the owner's cadence \u2014 a month the owner "
               "skipped is re-proposed, and every planning pass can pile "
               "more campaigns onto a month that was already full",
    },
    {
        "name": "skill_pack_self_load",
        "file": "app/skill.py",
        "find": "    global _PACK_LOADED\n    if _PACK_LOADED:\n        return",
        "replace": "    return  # SABOTAGE",
        "suites": ["test_workflow_ui.py"],
        "why": "skill registration falls back to whoever-imports-first — "
               "the web process answers Run now with 'no skill keyed "
               "campaign_email' and the Monday catalog sweep refuses "
               "silently, exactly the production incident of 2026-08-21",
    },
    {
        "name": "plan_segment_reference",
        "file": "app/systems.py",
        "find": "        why = fn(tenant, v)",
        "replace": "        why = \"\"  # SABOTAGE",
        "suites": ["test_plans.py"],
        "why": "a plan's segment and entity become free text again — a "
               "typo'd or invented key slides through to a stand-in cohort "
               "or product, and the campaign composes for something that "
               "does not exist",
    },
    {
        "name": "segment_id_remembered",
        "file": "app/segments.py",
        "find": "    stored = links(tenant).get(key) or {}",
        "replace": "    stored = {}  # SABOTAGE",
        "suites": ["test_segments.py"],
        "why": "every campaign draft falls back to a name search of the "
               "live ESP \u2014 a renamed segment silently unlinks, the draft "
               "goes untargeted or to the wrong cohort, and the Canva-"
               "folder lesson (the id is remembered, never searched for "
               "by name) is unlearned",
    },
    {
        "name": "campaign_honest_urgency",
        "file": "app/email_craft.py",
        "find": "    if urgent and not urgency_backed_by:",
        "replace": "    if False:  # SABOTAGE",
        "suites": ["test_campaign_variety.py"],
        "why": "the engine invents deadlines — \"last chance, ends "
               "tonight\" goes out over the client's sending domain with "
               "nothing behind it, at scale, which is a false statement "
               "made in their name and the exact scarcity both Kennedy "
               "and Hormozi call the dishonest kind",
    },
    {
        "name": "campaign_claim_backed_figures",
        "file": "app/skill_pack.py",
        "find": "            if cid not in offered_claims:",
        "replace": "            if False:  # SABOTAGE",
        "suites": ["test_campaign_variety.py"],
        "why": "a quote or a STATISTIC the model made up renders as proof "
               "in a customer email — an uncited number looks more "
               "traceable than no number, so this is worse than silence",
    },
    {
        "name": "health_probe_creates_nothing",
        "file": "app/web.py",
        "find": '    tok, why = _cv._token("agency")',
        "replace": '    tok, why = (_cv.folder("agency").get("folder_id", ""), "")  # SABOTAGE',
        "suites": ["test_canva.py"],
        "why": "an UNAUTHENTICATED health page creates a root folder and one "
               "folder per client inside the owner's Canva on its first hit "
               "\u2014 the segments dry-run incident again: a read-only "
               "surface writing to a live account",
    },
    {
        "name": "approval_grants_rights",
        "file": "app/kb.py",
        "find": "        if approve and rights in (OWNED, REFERENCE):",
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_assets.py"],
        "why": "approving a picture flips its review and leaves its rights at "
               "`reference`, so `may_publish` still refuses it \u2014 the "
               "owner approves photographs, nothing can use them, and no "
               "surface says why",
    },
    {
        "name": "links_point_at_real_pages",
        "file": "app/skill_pack.py",
        "find": "                if _want.split(\"?\")[0].rstrip(\"/\") not in known_urls:",
        "replace": "                if False:  # SABOTAGE",
        "suites": ["test_campaign_variety.py"],
        "why": "the call to action goes to a URL the drafter invented from a "
               "platform convention \u2014 /collections/all on a store whose "
               "catalogue is /collections/shop \u2014 so the one click the "
               "whole email exists to earn lands on a 404",
    },
    {
        "name": "no_approval_without_an_artifact",
        "file": "app/skill_pack.py",
        "find": "        if _appr.withdraw(ctx.run_id, why):",
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_campaign_variety.py"],
        "why": "the owner is asked to approve an email that exists nowhere \u2014 "
               "approving it reports success, clears it from the queue and "
               "produces nothing, so an approved campaign simply cannot be "
               "found afterwards",
    },
    {
        "name": "letter_may_show_the_product",
        "file": "app/skill_pack.py",
        "find": '            items = _product_items(picked)[:1 if fmt == "letter" else 3]',
        "replace": '            items = []  # SABOTAGE',
        "suites": ["test_campaign_variety.py"],
        "why": "a product launch to people who have bought before goes out "
               "with no picture of the product in it — the reader is asked "
               "to buy something they cannot see, which is what shipped on "
               "2026-08-22 when the letter format carried no imagery at all",
    },
    {
        "name": "attribution_is_copied_not_written",
        "file": "app/skill_pack.py",
        "find": '                            "attribution": str(claim.get("attributed_to") or "")})',
        "replace": '                            "attribution": b.get("attribution", "")})  # SABOTAGE',
        "suites": ["test_campaign_variety.py"],
        "why": "the drafter credits a statement to whoever sounds right — a "
               "live email cited \"Eien Health Research\", an organisation "
               "that does not exist, under a real claim; a credit line is a "
               "fact about the world and is copied from the record or not "
               "shown at all",
    },
    {
        "name": "product_status_is_read",
        "file": "app/catalog_sync.py",
        "find": "    status = str(product.get(\"status\") or \"\").strip().lower()",
        "replace": "    status = \"\"  # SABOTAGE",
        "suites": ["test_campaign_variety.py"],
        "why": "a DRAFT or ARCHIVED product is recorded as available — the "
               "knowledge base says a thing nobody can buy is in stock, and "
               "every layer downstream believes it (this is how Eien's "
               "letter came to recommend CitroBurn)",
    },
    {
        "name": "unfit_entity_named_in_copy",
        "file": "app/skill_pack.py",
        "find": "    _named = fitness.named_unfit(_model, to_check, _all_ents)",
        "replace": "    _named = []  # SABOTAGE",
        "suites": ["test_campaign_variety.py"],
        "why": "an email that RECOMMENDS a product in a sentence — no card, "
               "no key, nothing a parameter check could see — ships even "
               "when the product is a draft, and the whole list is sent to "
               "a dead page",
    },
    {
        "name": "signature_names_a_real_person",
        "file": "app/skill_pack.py",
        "find": "            who = str((signatory or {}).get(\"name\") or \"\").strip()",
        "replace": "            who = str(b.get(\"name\") or \"\").strip()  # SABOTAGE",
        "suites": ["test_campaign_variety.py"],
        "why": "the drafter signs the client's email as a person it invented "
               "— a name, a job title, and a statement attributed to a human "
               "being who does not exist",
    },
    {
        "name": "proof_used_as_its_kind_allows",
        "file": "app/skill_pack.py",
        "find": "            why = _proof_misuse(kind, b, claim)",
        "replace": "            why = \"\"  # SABOTAGE",
        "suites": ["test_campaign_variety.py"],
        "why": "a customer testimonial goes out REWORDED under a real "
               "attribution — words invented for a named person — and a "
               "statistic the cited claim never contained ships looking "
               "traceable; citing a real claim id was treated as permission "
               "to say anything near it",
    },
    {
        "name": "campaign_repair_rerenders",
        "file": "app/skill.py",
        "find": "\"meta\": (meta() if callable(meta) else meta) or {}}",
        "replace": "\"meta\": ({} if callable(meta) else meta) or {}}  # SABOTAGE",
        "suites": ["test_campaign_variety.py"],
        "why": "a repaired email files the CLEAN copy and ships the "
               "REJECTED render — the banned phrase the validator "
               "caught reaches the ESP anyway, and the ledger says it did "
               "not",
    },
    {
        "name": "campaign_format_by_audience",
        "file": "app/skill_pack.py",
        "find": "        if allowed and kind and kind not in allowed:",
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_campaign_variety.py"],
        "why": "the letter-format send to warm buyers grows a banner and a "
               "product grid — every email collapses back to one house "
               "layout, which is the sameness the composed-layout work "
               "exists to end",
    },
    {
        "name": "moments_route_checks_the_key",
        "file": "app/web.py",
        "find": ("    # Same omission, and worse here: `due_now` carries `person_key`, which is\n"
                 "    # a customer's email address. An unauthenticated read of this was a\n"
                 "    # personal-data leak, not just an internal one.\n"
                 "    if key != config.APPROVAL_SECRET:\n"
                 "        return {\"error\": \"unauthorized\"}"),
        "replace": "    pass  # SABOTAGE",
        "suites": ["test_strategy.py"],
        "why": "anyone who finds the URL reads a client's open moments — and "
               "`due_now` carries `person_key`, which is a customer's email "
               "address. `admin_key` RESOLVES the credential and returns '' "
               "rather than rejecting, so a route that forgets to check is "
               "wide open and looks identical to one that does",
    },
    {
        "name": "planner_follows_the_ledger",
        "file": "app/planner.py",
        "find": "    for seg in _by_neglect(sysrow.tenant, got[\"high_value\"]):",
        "replace": "    for seg in got[\"high_value\"]:  # SABOTAGE",
        "suites": ["test_strategy.py"],
        "why": "the planner goes back to walking the catalogue in the order "
               "somebody typed it, so the cohort listed first is written to "
               "first every month whether or not it has just been written to "
               "— a programme shaped by a list order rather than by what has "
               "actually been sent",
    },
    {
        "name": "only_a_finished_send_is_published",
        "file": "app/performance.py",
        "find": '        if status not in getattr(mod, "FINISHED", ("sent",)):',
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_strategy.py"],
        "why": "a campaign still going out is recorded as finished, so its "
               "partial-subset open rate — Omnisend verifies a brand's first "
               "send against a small sample — is filed as the campaign's "
               "result and never looked at again",
    },
    {
        "name": "a_send_confirmed_once_stays_confirmed",
        "file": "app/ledger.py",
        "find": '        if row.status != "published":\n            row.status = "published"\n            row.published_at = at or db.utcnow()',
        "replace": '        row.status = "published"  # SABOTAGE\n        row.published_at = db.utcnow()\n        if False:\n            pass',
        "suites": ["test_strategy.py"],
        "why": "`published_at` is rewritten on every sweep, so it means the "
               "last time we asked rather than when the email went out — and "
               "every anti-repeat window measured from it silently slides "
               "forward for ever",
    },
    {
        "name": "campaign_results_cost_one_call",
        "file": "app/performance.py",
        "find": "    got = mod.campaign_metrics(tenant, days=days)",
        "replace": "    got = mod.campaign_metrics(tenant, days=days)  # SABOTAGE\n    [mod.campaign_metrics(tenant, days=days) for _ in waiting]",
        "suites": ["test_strategy.py"],
        "why": "one analytics request per campaign instead of one per account "
               "— Omnisend allows 55 a day per brand, so a fortnight of sends "
               "exhausts the budget and then reporting fails for everything",
    },
    {
        "name": "pressure_never_becomes_a_second_send",
        "file": "app/planner.py",
        "find": "        queued = _open_plan_ref(sysrow.tenant, seg)\n        if queued:",
        "replace": "        queued = _open_plan_ref(sysrow.tenant, seg)\n        if False:  # SABOTAGE",
        "suites": ["test_moment_pressure.py"],
        "why": "a cohort that already has a campaign queued gets a SECOND one "
               "from the moment path — and for a venue every moment segment "
               "is also a calendar segment, so that is the normal case, not a "
               "corner one. Two sends to the same list about the same week",
    },
    {
        "name": "pressure_needs_enough_people",
        "file": "app/moments.py",
        "find": '            "ready": n >= MIN_PRESSURE,',
        "replace": '            "ready": True,  # SABOTAGE',
        "suites": ["test_moment_pressure.py"],
        "why": "one person abandoning a cart proposes a campaign to the whole "
               "list — a message to a thousand people about something true of "
               "one, which is the exact failure the per-person design would "
               "have shipped",
    },
    {
        "name": "pressure_buys_timing_not_volume",
        "file": "app/planner.py",
        "find": '        if have_by_segment.get(seg, {}).get(_month(today), 0) >= cad["per_segment_monthly"]:',
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_moment_pressure.py"],
        "why": "a cohort earns extra campaigns by having a bad week — the "
               "monthly cap stops binding on the pressure path, so the busier "
               "a segment gets the more it is written to",
    },
    {
        "name": "an_order_closes_the_cart",
        "file": "app/commerce_events.py",
        "find": '        return {"ok": True, "filed": [], "closed": _order_supersedes(tenant, who)}',
        "replace": '        return {"ok": True, "filed": [], "closed": 0}  # SABOTAGE',
        "suites": ["test_moments.py"],
        "why": "the cart moment survives the purchase, comes due five hours "
               "later, and asks somebody to finish buying a thing they have "
               "already paid for — not a wasted send but the send that tells "
               "a customer nobody is watching",
    },
    {
        "name": "a_moment_belongs_to_its_business_model",
        "file": "app/moments.py",
        "find": "    sp = spec(model, kind)\n    if not sp:",
        "replace": "    sp = spec(model, kind) or by_model(model)[0]  # SABOTAGE\n    if False:",
        "suites": ["test_moments.py"],
        "why": "a producer can file a cart moment against a venue — the row "
               "looks like work in the queue, and dies at consumption with a "
               "key nothing recognises. Wiring mistakes stop being catchable "
               "at the only cheap moment there is",
    },
    {
        "name": "quiet_clock_starts_at_the_last_touch",
        "file": "app/inbox_events.py",
        "find": "            conversation_id=conv_id, source=\"inbox\", occurred_at=last,",
        "replace": "            conversation_id=conv_id, source=\"inbox\",  # SABOTAGE",
        "suites": ["test_moments.py"],
        "why": "the window is measured from when a cron happened to run "
               "instead of from when the person last heard from us — so "
               "'three days quiet' becomes three days after we noticed, and "
               "the moment is served days late or not at all",
    },
    {
        "name": "a_stale_enquiry_is_not_a_moment",
        "file": "app/inbox_events.py",
        "find": "                        db.Conversation.last_touch_at > too_old)",
        "replace": "                        )  # SABOTAGE",
        "suites": ["test_moments.py"],
        "why": "every enquiry that ever went quiet files a moment that is "
               "already past its own expiry — rows that can never be served, "
               "filling the table and slowing every `due()` behind them",
    },
    {
        "name": "commerce_webhook_is_verified",
        "file": "app/web.py",
        "find": ("    raw = await request.body()\n"
                 "    if not swh.verify(raw, request.headers.get(\"X-Shopify-Hmac-Sha256\", \"\")):\n"
                 "        return JSONResponse({\"error\": \"unverified\"}, status_code=401)\n"
                 "\n"
                 "    topic = request.headers.get(\"X-Shopify-Topic\", \"\")\n"
                 "    shop = request.headers.get(\"X-Shopify-Shop-Domain\", \"\")\n"
                 "    try:\n"
                 "        payload = json.loads(raw or b\"{}\")\n"
                 "        if not isinstance(payload, dict):\n"
                 "            payload = {}"),
        "replace": ("    raw = await request.body()  # SABOTAGE\n"
                    "    topic = request.headers.get(\"X-Shopify-Topic\", \"\")\n"
                    "    shop = request.headers.get(\"X-Shopify-Shop-Domain\", \"\")\n"
                    "    try:\n"
                    "        payload = json.loads(raw or b\"{}\")\n"
                    "        if not isinstance(payload, dict):\n"
                    "            payload = {}"),
        "suites": ["test_moments.py"],
        "why": "anyone who finds the URL can file moments into a client's "
               "account — inventing the people, the products and the timing "
               "of emails sent over that client's own sending domain",
    },
    {
        "name": "declared_index_reaches_the_database",
        "file": "app/db.py",
        "find": ("                    conn.execute(text(\n"
                 "                        f'CREATE INDEX IF NOT EXISTS \"{ix.name}\" '\n"
                 "                        f'ON \"{table.name}\" ({target})'))"),
        "replace": "                    pass  # SABOTAGE",
        "suites": ["test_strategy_ledger.py"],
        "why": "marking a column `index=True` goes back to changing nothing on "
               "a table that already exists — the declaration reads as done, "
               "the query stays a sequential scan over every output the "
               "account has ever produced, and the only symptom is a latency "
               "nobody is measuring",
    },
    {
        "name": "index_migration_is_reached_at_startup",
        "file": "app/db.py",
        "find": "    _auto_index()\n\n\ndef _auto_index() -> None:",
        "replace": "    pass  # SABOTAGE\n\n\ndef _auto_index() -> None:",
        "suites": ["test_strategy_ledger.py"],
        "why": "the index migration still works perfectly and is never called "
               "— the same failure as a rule that reaches no validator, and "
               "invisible for exactly as long",
    },
    {
        "name": "campaign_row_names_subject_and_list",
        "file": "app/skill_pack.py",
        "find": '        entity_key=_subject, audience_key=seg["key"],',
        "replace": '        entity_key="", audience_key="",  # SABOTAGE',
        "suites": ["test_strategy_ledger.py"],
        "why": "the ledger goes back to holding every campaign ever sent with "
               "no record of which product went to which list — and the "
               "answer comes back EMPTY, which reads as 'nothing was sent' "
               "rather than 'nobody wrote it down'. Every strategy question "
               "downstream is then answered from a blank",
    },
    {
        "name": "repaired_draft_is_not_a_send",
        "file": "app/skill_pack.py",
        "find": "                            db.Output.status.notin_(ledger.NOT_A_SEND))",
        "replace": '                            db.Output.status.notin_(("blocked", "superseded")))  # SABOTAGE',
        "suites": ["test_strategy_ledger.py"],
        "why": "a draft the validator THREW AWAY re-enters the four rows the "
               "drafter varies against — filed with an empty theme and shape, "
               "so it reads as a real send with no intent, displaces one that "
               "actually went out, and teaches the next email to differ from "
               "something nobody ever received",
    },
    {
        "name": "campaign_destination_is_an_outcome",
        "file": "app/skill_pack.py",
        "find": '    ledger.delivered(ctx.tenant, item["output_id"], _landed)',
        "replace": "    pass  # SABOTAGE",
        "suites": ["test_strategy_ledger.py"],
        "why": "`destination` goes back to what was written ninety lines "
               "before the ESP call — every campaign row says `esp:omnisend` "
               "whether or not anything reached Omnisend, so a refusal and a "
               "landing are indistinguishable in the one table anybody later "
               "queries",
    },
    {
        "name": "strategy_read_spans_the_column_change",
        "file": "app/ledger.py",
        "find": "                        or_(db.Output.audience_key == audience_key,\n                            db.Output.angle == audience_key),",
        "replace": "                        db.Output.audience_key == audience_key,  # SABOTAGE",
        "suites": ["test_strategy_ledger.py"],
        "why": "every campaign written before `audience_key` was passed drops "
               "out of the window — the brand reads as having no history at "
               "all, which is the most misleading possible answer to 'what "
               "have we been telling these people'",
    },
    # ------------------------------------------------------------------
    # UI overhaul step 0 (INITIATIVE-ui-overhaul.md) — the safety rails.
    # ------------------------------------------------------------------
    {
        "name": "portal_signin_submits",
        "file": "app/portal_ui.py",
        "find": "    return _page(\"Sign in\", f\"<div class='in'>{inner}</div>\")",
        "replace": "    return _page(\"Sign in\", f\"<form class='in' "
                   "onsubmit='return false'>{inner}</form>\")  # SABOTAGE",
        "suites": ["test_render_smoke.py"],
        "why": "the client product's front door goes dead again: a nested "
               "<form> start tag is dropped by the HTML parser, so the "
               "request-a-link button submits a wrapper that cancels itself "
               "and no client can ever ask to sign in",
    },
    {
        "name": "health_is_liveness_only",
        "file": "app/web.py",
        "find": "    if key != config.APPROVAL_SECRET:\n"
                "        return base                     # liveness + build identity, no roster",
        "replace": "    if False:\n"
                   "        return base                     # SABOTAGE",
        "suites": ["test_render_smoke.py"],
        "why": "/health goes back to printing every Gmail alias, channel "
               "state and OAuth redirect URI to anyone on the internet — a "
               "roster where a heartbeat belongs, contradicting the landing "
               "page's isolation promise with one curl",
    },
    {
        "name": "connections_probe_needs_key",
        "file": "app/web.py",
        "find": "    if key != config.APPROVAL_SECRET:\n"
                "        from fastapi.responses import JSONResponse",
        "replace": "    if False:\n"
                   "        from fastapi.responses import JSONResponse",
        "suites": ["test_render_smoke.py"],
        "why": "/health/connections live-probes and prints Shopify shop "
               "names and every tenant's Google state, unauthenticated — "
               "the client roster with a health verdict per row, again",
    },
    {
        "name": "client_view_carries_no_key",
        "file": "app/admin_ui.py",
        "find": "    client_view = (\"\" if tenant == ALL else\n"
                "                   f'<a href=\"/portal?tenant={_esc(tenant)}\">'",
        "replace": "    client_view = (\"\" if tenant == ALL else\n"
                   "                   f'<a href=\"/portal?tenant={_esc(tenant)}&amp;key={_esc(key)}\">'",
        "suites": ["test_render_smoke.py"],
        "why": "the console secret rides back into the portal's access logs "
               "and browser history on every Client-view click — the exact "
               "propagation the session cookie was built to end",
    },
    {
        "name": "portal_sessions_fail_closed",
        "file": "app/portal.py",
        "find": "    if not (config.APPROVAL_SECRET or \"\").strip():\n"
                "        return None",
        "replace": "    if False:\n"
                   "        return None",
        "suites": ["test_render_smoke.py"],
        "why": "with APPROVAL_SECRET unset, the portal HMAC keys on \"\" and "
               "verifies anything — a forged role=owner cookie reads every "
               "account and passes can_write; sessions must fail closed the "
               "way web._matches does",
    },
    {
        "name": "intake_links_have_a_surface",
        "file": "app/admin_ui.py",
        "find": "              {_intake_links(t.key, key)}",
        "replace": "              ",
        "suites": ["test_render_smoke.py"],
        "why": "minting an intake link goes back to hand-typing "
               "/admin/intake_new and copying a URL out of raw JSON — the "
               "highest-leverage client surface loses its only console "
               "control",
    },
    {
        "name": "draft_survives_edit",
        "file": "app/web.py",
        "find": "        row.body = body\n        row.bytes = len(body)",
        "replace": "        row.body = body\n        row.draft_body = body  # SABOTAGE\n        row.bytes = len(body)",
        "suites": ["test_render_smoke.py", "test_article_review.py"],
        "why": "the frozen draft gets overwritten by every save — v1 stops "
               "existing, the draft-vs-published delta (the blog system's "
               "declared measure) can never compute again, and the version "
               "history's first step is a lie",
    },
    {
        "name": "version_appends_never_overwrites",
        "file": "app/web.py",
        "find": "        s.add(db.ArtifactVersion(tenant=art.tenant or \"\", output_id=output_id,\n"
                "                                 n=n, author=\"owner\",\n"
                "                                 note=\"save for later\" if later else \"\",\n"
                "                                 body=body))",
        "replace": "        pass  # SABOTAGE",
        "suites": ["test_render_smoke.py"],
        "why": "saves stop leaving history — the workroom's versions fold "
               "shows only the frozen draft forever, and 'doesn't get stored "
               "anywhere, to edit later' comes back as a fact instead of a "
               "complaint",
    },
    {
        "name": "workroom_indexed",
        "file": "app/admin_ui.py",
        "find": "                    .filter(db.ArtifactBody.tenant == tenant,\n"
                "                            db.ArtifactBody.state == \"in_review\")",
        "replace": "                    .filter(db.ArtifactBody.tenant == tenant,\n"
                   "                            db.ArtifactBody.state == \"never\")  # SABOTAGE",
        "suites": ["test_render_smoke.py"],
        "why": "Save-for-later holds work that no surface can find again — "
               "persistence with no index, which is the exact experience "
               "('stored nowhere') the workroom was built to end",
    },
    {
        "name": "feedback_reaches_prompt",
        "file": "app/web.py",
        "find": "        _sys.note(tenant, syskey, f\"[workroom · {part}] {note}\")",
        "replace": "        pass  # SABOTAGE",
        "suites": ["test_render_smoke.py"],
        "why": "teach-this-system feedback files a row and teaches nothing — "
               "the rail becomes a complaint box, and the owner's judgement "
               "stops reaching the prompt that drafts tomorrow's work",
    },
    {
        "name": "rule_reaches_validator",
        "file": "app/web.py",
        "find": "        got = _sys.promote_rule(tenant, note)",
        "replace": "        got = \"\"  # SABOTAGE",
        "suites": ["test_render_smoke.py"],
        "why": "make-it-a-rule stops writing the ban list — the strongest "
               "promise on the rail ('the validator blocks it forever') "
               "silently becomes the weakest, a note nobody enforces",
    },
    {
        "name": "draft_products_never_offered",
        "file": "app/admin_ui.py",
        "find": "        rows = sorted((r for r in kb.entities(tenant, available_only=False)\n"
                "                       if (r.availability or \"available\")\n"
                "                       not in (\"draft\", \"archived\", \"unpublished\")),",
        "replace": "        rows = sorted(kb.entities(tenant, available_only=False),  # SABOTAGE",
        "suites": ["test_render_smoke.py"],
        "why": "the plan's entity picker offers draft and archived products "
               "again — inviting the owner to plan a campaign around a "
               "product no customer can buy, which is the CitroBurn failure "
               "wearing a select element",
    },
    {
        "name": "approving_pushes_the_draft",
        "file": "app/approvals.py",
        "find": "                got = _sp.push_campaign_to_esp(\n"
                "                    ap.tenant or p.get(\"tenant\", \"\"), p.get(\"output_id\", \"\"))",
        "replace": "                got = {\"ok\": True, \"provider\": \"omnisend\",\n"
                   "                       \"campaign_id\": \"x\"}  # SABOTAGE",
        "suites": ["test_campaign_variety.py"],
        "why": "approving a campaign claims a push that never happened — the "
               "owner approves, the message says launch-ready, and the ESP "
               "holds nothing; review-before-push becomes review-before-"
               "nothing",
    },
    {
        "name": "push_refuses_withdrawn",
        "file": "app/skill_pack.py",
        "find": "    if latest_status == \"withdrawn\" or (\n"
                "            held_defects and run_decision != \"approved\"):",
        "replace": "    if False and (\n"
                   "            held_defects and run_decision != \"approved\"):  # SABOTAGE",
        "suites": ["test_campaign_variety.py"],
        "why": "the push becomes a side door around the review's verdict — a "
               "campaign the gates withdrew (dead links, defects) can be "
               "written into a client's live ESP anyway, one click from a "
               "list",
    },
    {
        "name": "redraft_supersedes",
        "file": "app/skill_pack.py",
        "find": "            old.status = \"superseded\"",
        "replace": "            pass  # SABOTAGE",
        "suites": ["test_campaign_variety.py", "test_article_review.py"],
        "why": "a redraft leaves TWO live rows for one intent — both held, "
               "both counted, both on the board — and the anti-repeat window "
               "reads the rejected attempt as something the brand said",
    },
    {
        "name": "redraft_carries_the_notes",
        "file": "app/skill_pack.py",
        "find": "    digest = \"\\n\".join(f\"- {ln}\" for ln in lines)",
        "replace": "    digest = \"\"  # SABOTAGE",
        "suites": ["test_campaign_variety.py", "test_article_review.py"],
        "why": "Request-changes reruns the drafter with the owner's feedback "
               "silently dropped — a reroll wearing a redraft's name, and the "
               "workroom's rail teaching the owner that filing feedback does "
               "nothing",
    },
    {
        "name": "seo_head_carries_the_keyword",
        "file": "app/skill_pack.py",
        "find": "    keyword = (keyword or \"\").strip().lower()\n"
                "    if keyword:\n"
                "        sentences = _re.split(r\"(?<=[.!?])\\s+\", text)",
        "replace": "    keyword = (keyword or \"\").strip().lower()\n"
                   "    if False:\n"
                   "        sentences = _re.split(r\"(?<=[.!?])\\s+\", text)",
        "suites": ["test_blog_skill.py"],
        "why": "the meta description goes back to being whatever the article "
               "opened with — the target keyword the page exists to win "
               "vanishes from the one line a searcher reads before deciding "
               "to click",
    },
    {
        "name": "badge_counts_match_lists",
        "file": "app/admin_ui.py",
        "find": "        out[\"content\"] += len(prov.conflicts(tenant))",
        "replace": "        out[\"content\"] += len(prov.conflicts(tenant)) + 1  # SABOTAGE",
        "suites": ["test_render_smoke.py"],
        "why": "the sidebar badge drifts from the queue it points at — a "
               "number that does not match the list it opens is learned as "
               "noise within a week, and the console goes back to answering "
               "'is there work' with a click per tab",
    },
    {
        "name": "light_defines_every_token",
        "file": "app/admin_ui.py",
        "find": "body[data-theme=light]{--bg:#f4f6fb;--panel:#fff;--ink:#171a26;--ink2:#3d4353;",
        "replace": "body[data-theme=light]{--bg:#f4f6fb;--panel:#fff;--ink:#171a26;--inkX:#3d4353;",
        "suites": ["test_render_smoke.py"],
        "why": "the light palette drops a token the dark set defines — every "
               "rule reading it falls back to the dark value on a light "
               "ground, which is exactly the mistuned-hex era the token "
               "sheet retired, reintroduced one theme at a time",
    },
    {
        "name": "theme_survives_the_session",
        "file": "app/web.py",
        "find": "    resp.set_cookie(THEME_COOKIE, \"light\" if to == \"light\" else \"dark\",\n"
                "                    max_age=60 * 60 * 24 * 180, httponly=True, samesite=\"lax\",\n"
                "                    secure=request.url.scheme == \"https\")",
        "replace": "    pass  # SABOTAGE",
        "suites": ["test_render_smoke.py"],
        "why": "the toggle redirects but remembers nothing — every click "
               "flashes the other theme for one page load and reverts, the "
               "kind of half-working control that teaches a person the "
               "console cannot be trusted with preferences",
    },
    {
        "name": "plan_classes_defined",
        "file": "app/admin_ui.py",
        "find": ".cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));",
        "replace": ".cards-SABOTAGED{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));",
        "suites": ["test_render_smoke.py"],
        "why": "the Plan tab's readiness strip renders as unstyled stacked "
               "divs again — markup using classes the stylesheet does not "
               "define, which shipped unnoticed for weeks because nothing "
               "compared the page to its own CSS",
    },
    {
        "name": "ad_batch_is_kept",
        "file": "app/skill_pack.py",
        "find": "    if board_rows and not str(ctx.params.get(\"into_batch\") or \"\").strip():",
        "replace": "    if False and board_rows:  # SABOTAGE",
        "suites": ["test_ad_board.py"],
        "why": "ad variants go back to living only in run-detail JSON — the "
               "spec's exact defect ('no surface shows them, so nothing can "
               "be judged, edited, or regenerated') returns, while every "
               "variant still queues an approval about copy nobody can see",
    },
    {
        "name": "ad_regenerate_keeps_kept",
        "file": "app/skill_pack.py",
        "find": "        merged = kept + rows",
        "replace": "        merged = list(rows)  # SABOTAGE",
        "suites": ["test_ad_board.py"],
        "why": "Regenerate silently throws away every KEPT variant — the "
               "owner's edits and approvals with them — and replaces the "
               "whole board with fresh drafts; 'kept variants survive' is "
               "the promise printed next to the button",
    },
    {
        "name": "ad_variant_edit_is_ban_gated",
        "file": "app/web.py",
        "find": "    low = text.lower()\n"
                "    hit = next((b for b in banned if str(b).strip()\n"
                "                and str(b).lower() in low), \"\")\n"
                "    if hit:",
        "replace": "    low = text.lower()\n"
                   "    hit = \"\"  # SABOTAGE\n"
                   "    if hit:",
        "suites": ["test_ad_board.py"],
        "why": "the owner can type a banned claim straight into a variant "
               "and mark the batch ready — the ban list stops binding the "
               "owner's hands exactly where copy leaves for a paid channel",
    },
    {
        "name": "batch_approve_denies_dropped",
        "file": "app/web.py",
        "find": "        for ap_id, oid in pend:\n"
                "            if oid in drop_ids:\n"
                "                _appr.apply_decision(ap_id, \"denied\")\n"
                "                n_no += 1",
        "replace": "        for ap_id, oid in pend:\n"
                   "            if False:  # SABOTAGE\n"
                   "                _appr.apply_decision(ap_id, \"denied\")\n"
                   "                n_no += 1",
        "suites": ["test_ad_board.py"],
        "why": "approving the batch leaves the dropped variants' approvals "
               "pending — the thing the owner threw off the board stays "
               "decidable in the ship queue, one stray click from 'ready'",
    },
    {
        "name": "queue_answers_land_approved",
        "file": "app/web.py",
        "find": "        situations=sits, origin=\"human\")",
        "replace": "        situations=sits, origin=\"crawl\")  # SABOTAGE",
        "suites": ["test_schema_tab.py"],
        "why": "the Queue's answer box files the owner's own answer as a "
               "machine PROPOSAL — invisible to every generator until "
               "somebody re-approves their own words on Review, and the "
               "lane's promise ('saving files it as an objection, approved') "
               "becomes a lie",
    },
    {
        "name": "lesson_guidance_reaches_prompt",
        "file": "app/web.py",
        "find": "        said = _sys.note(tenant, syskey,\n"
                "                         \"[observed, kept as guidance] \" + rows[0][\"text\"][:400])",
        "replace": "        said = \"kept\"  # SABOTAGE",
        "suites": ["test_schema_tab.py"],
        "why": "Keep-as-guidance flashes success and teaches nothing — the "
               "promoted observation never reaches the system's standing "
               "notes, so the Active Learning lane becomes a complaint box "
               "with three buttons",
    },
    {
        "name": "lesson_dismiss_is_real",
        "file": "app/systems.py",
        "find": "    return [r for r in out\n"
                "            if r[\"text\"] and r[\"text\"] != \"sent unchanged\"\n"
                "            and r[\"run_id\"] not in gone]",
        "replace": "    return [r for r in out\n"
                   "            if r[\"text\"] and r[\"text\"] != \"sent unchanged\"]  # SABOTAGE",
        "suites": ["test_schema_tab.py"],
        "why": "dismissing a lesson hides nothing — the one-off the owner "
               "rejected keeps riding the drafter's brief and keeps "
               "re-appearing on the lane, a control that lies about its "
               "consequence in both channels at once",
    },
    {
        "name": "claim_restore_has_a_surface",
        "file": "app/admin_ui.py",
        "find": "<button class=\"sec\">Restore</button>",
        "replace": "<!-- SABOTAGE -->",
        "suites": ["test_schema_tab.py"],
        "why": "putting back a removed claim goes back to being an API call "
               "with a row id — the exact hole the Removed filter was built "
               "to close, reopened while the filter still lists what cannot "
               "be acted on",
    },
    {
        "name": "schema_badge_matches_queue",
        "file": "app/admin_ui.py",
        "find": "        out[\"schema\"] = _schema_needs_you(tenant)[\"n\"]",
        "replace": "        out[\"schema\"] = _schema_needs_you(tenant)[\"n\"] + 1  # SABOTAGE",
        "suites": ["test_schema_tab.py"],
        "why": "the Data layer badge drifts from the queue it opens — a "
               "number that does not match its list is learned as noise "
               "within a week, which is the defect the needs-you badges "
               "were built to end",
    },
    {
        "name": "variant_reaches_its_board",
        "file": "app/web.py",
        "find": "        if hit is not None and hit.output_id != output_id:\n"
                "            return RedirectResponse(\n"
                "                f\"/admin/work/{quote(hit.output_id)}?key={quote(key)}\", 303)",
        "replace": "        if False and hit is not None:  # SABOTAGE\n"
                   "            return RedirectResponse(\n"
                   "                f\"/admin/work/{quote(hit.output_id)}?key={quote(key)}\", 303)",
        "suites": ["test_ad_board.py", "test_render_smoke.py"],
        "why": "every ship-queue link for a non-anchor variant dead-ends on "
               "a 404 — the review control points at a place that does not "
               "hold the thing, the defect family the pointers suite exists "
               "to end",
    },
]


def run_suite(name: str) -> bool:
    """True if the suite PASSED."""
    p = subprocess.run([sys.executable, f"scripts/{name}"], cwd=ROOT,
                       capture_output=True, text=True, timeout=600)
    out = p.stdout + p.stderr
    return "all checks passed" in out or "all green" in out


def main(only: str = "") -> int:
    entries = [s for s in SABOTAGES if not only or s["name"] == only]
    if only and not entries:
        print(f"no sabotage named {only!r}. Known: "
              + ", ".join(s["name"] for s in SABOTAGES))
        return 2

    undetected, stale = [], []
    for s in entries:
        path = ROOT / s["file"]
        original = path.read_text()

        if original.count(s["find"]) != 1:
            # Not a pass and not a failure: the thing this claims to test has
            # moved or gone, so it has been testing nothing since it did.
            n = original.count(s["find"])
            print(f"[ STALE  ] {s['name']:24} — the target appears {n} times in "
                  f"{s['file']}; this has been covering nothing")
            print(f"            was guarding: {s['why']}")
            stale.append(s["name"])
            continue

        path.write_text(original.replace(s["find"], s["replace"], 1))
        try:
            passed = {n: run_suite(n) for n in s["suites"]}
        finally:
            # Restored whatever happened, and VERIFIED rather than assumed — a
            # harness that leaves a guard disabled is worse than no harness,
            # and this one edits the live tree.
            #
            # No `return` in here: returning from a `finally` swallows the
            # exception that sent us here, which would turn a crashed suite
            # into a silent success. The check below runs after.
            path.write_text(original)
            restored = path.read_text() == original
        if not restored:
            print(f"\n!!! FAILED TO RESTORE {s['file']} — fix it by hand "
                  f"before doing anything else !!!")
            return 3

        noticed = [n for n, ok in passed.items() if not ok]
        if noticed:
            print(f"[ caught ] {s['name']:24} — {', '.join(noticed)}")
        else:
            print(f"[ MISSED ] {s['name']:24} — every suite still passed")
            print(f"            unguarded: {s['why']}")
            print(f"            claimed by: {', '.join(s['suites'])}")
            undetected.append(s["name"])

    print()
    if undetected or stale:
        if undetected:
            print(f"{len(undetected)} guard(s) NOT covered by their suites: "
                  + ", ".join(undetected))
            print("Each one can be removed today and nothing will say so.")
        if stale:
            print(f"{len(stale)} sabotage(s) STALE: " + ", ".join(stale))
            print("The code moved. Re-point them or the coverage is imaginary.")
        return 1
    print(f"all {len(entries)} guards are genuinely tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
