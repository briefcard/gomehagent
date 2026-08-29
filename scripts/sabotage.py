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
        # Retargeted 2026-08-27 (step 4): the card moved to the People &
        # links view with the rest of the client-access surface.
        "find": "    {_intake_links(t.key, key)}",
        "replace": "    ",
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
        "name": "card_meta_folds",
        "file": "app/admin_ui.py",
        "find": "              <label>{\"Attribution\" if verbatim",
        "replace": "              <div class=\"when\">{_esc(p.proof_type or '')} · {_esc(p.source or '')}</div>\n              <label>{\"Attribution\" if verbatim",
        "suites": ["test_review_tab.py"],
        "why": "the provenance line climbs back above the fold and the card "
               "is busy again — the exact walkthrough complaint (owner, "
               "2026-08-27: metadata at the bottom, on toggle only) undone "
               "one line at a time",
    },
    {
        "name": "claims_filter_filters",
        "file": "app/admin_ui.py",
        "find": "    if _cf == \"due\":",
        "replace": "    if False and _cf == \"due\":  # SABOTAGE",
        "suites": ["test_review_tab.py"],
        "why": "the came-due chip highlights and filters nothing — a control "
               "that changes the address and not the list teaches the owner "
               "that filtering is decoration, which kills the whole "
               "prioritisation gesture",
    },
    {
        "name": "filters_survive_the_decision",
        "file": "app/web.py",
        "find": "                                  \"flt\": str(form.get(\"flt\") or \"\")})",
        "replace": "                                  \"flt\": \"\"})  # SABOTAGE",
        "suites": ["test_review_tab.py"],
        "why": "deciding one row silently resets the narrowed queue to "
               "unfiltered — every decision costs the reader the view they "
               "built, the same bounce the cpage threading was built to end",
    },
    {
        "name": "ship_decides_in_console",
        "file": "app/web.py",
        "find": "    said = _appr.apply_decision(str(form.get(\"approval_id\") or \"\"), verdict)",
        "replace": "    said = \"Approved\"  # SABOTAGE",
        "suites": ["test_review_tab.py"],
        "why": "the console's primary control flashes success and decides "
               "nothing — the approval stays pending, the campaign never "
               "pushes, and the owner reads 'Approved' over a queue that "
               "silently kept everything",
    },
    {
        "name": "every_queue_pages",
        "file": "app/admin_ui.py",
        "find": "    _ship_shown = ship_rows[(_page - 1) * SHIP_PAGE:_page * SHIP_PAGE]",
        "replace": "    _ship_shown = ship_rows[:25]  # SABOTAGE",
        "suites": ["test_review_tab.py"],
        "why": "the ship queue goes back to a 25-row cap wearing a pager's "
               "clothes — decision #26 is unreachable again, and a queue "
               "whose depth nobody can see stops being worked (it lived at "
               "~200 drafts once)",
    },
    {
        "name": "sources_lead_the_page",
        "file": "app/admin_ui.py",
        "find": "{_sources_block(key, tenant)}\n{strip}",
        "replace": "{strip}",
        "suites": ["test_review_tab.py"],
        "why": "the feeders and their last-ran state disappear from the "
               "day's tab — a failed harvest goes back to being invisible "
               "until somebody wonders why the queues are empty",
    },
    {
        "name": "store_sync_parks_without_a_store",
        "file": "app/admin_ui.py",
        "find": "   if has_store else\n   '<p class=\"mut\">The sync button appears once a store is connected",
        "replace": "   if True else\n   '<p class=\"mut\">The sync button appears once a store is connected",
        "suites": ["test_review_tab.py"],
        "why": "the sync button renders for an account with no store and "
               "fails on every click — a control that can only fail, on the "
               "tab the day starts on, teaching distrust of every button "
               "beside it",
    },
    {
        "name": "bulk_reports_are_flashes",
        "file": "app/admin_ui.py",
        "find": "        banner = f'<div class=\"ok\">{_esc(msg)}</div>' + banner",
        "replace": "        banner = f'<div class=\"when\">{_esc(msg)}</div>' + banner",
        "suites": ["test_review_tab.py"],
        "why": "a bulk decision's report — including what it REFUSED — goes "
               "back to muted grey, the least important text on the page; a "
               "refusal nobody notices is a claim that quietly never "
               "became usable",
    },
    {
        "name": "verify_lands_on_the_card",
        "file": "app/web.py",
        "find": "    if ui and tenant:\n"
                "        import json as _json",
        "replace": "    if False:  # SABOTAGE\n"
                   "        import json as _json",
        "suites": ["test_connections_tab.py"],
        "why": "Test connections goes back to dumping raw JSON in a new tab "
               "— the console's own button becomes the dead-end the page's "
               "copy used to document, and the stored per-provider summary "
               "on the Status card stops updating",
    },
    {
        "name": "signin_link_flashes_back",
        "file": "app/web.py",
        "find": "    got = portal.issue_link(email, issued_by=\"owner\")\n"
                "    if ui:",
        "replace": "    got = portal.issue_link(email, issued_by=\"owner\")\n"
                   "    if False:  # SABOTAGE",
        "suites": ["test_connections_tab.py"],
        "why": "minting a sign-in link dumps the credential as raw JSON "
               "again instead of flashing it copyable on People & links — "
               "the exact dead-end §11 counted, on the most "
               "credential-shaped link this page mints",
    },
    {
        "name": "destructive_asks_first",
        "file": "app/admin_ui.py",
        "find": "                f'<form method=\"post\" action=\"/admin/person_access\" class=\"inl\" '\n"
                "                f'onsubmit=\"return confirm(",
        "replace": "                f'<form method=\"post\" action=\"/admin/person_access\" class=\"inl\" '\n"
                   "                f'data-x=\"return confirm(",
        "suites": ["test_connections_tab.py"],
        "why": "Revoke goes back to firing on a bare click — an irreversible "
               "action (their unused sign-in links die with it) one stray "
               "tap from happening, inside a fold that self-opens",
    },
    {
        "name": "parked_reads_as_parked",
        "file": "app/admin_ui.py",
        "find": "  <summary>Give someone bot access\n"
                "    <span class=\"chip nb\">parked by choice</span></summary>",
        "replace": "  <summary>Give someone bot access</summary>",
        "suites": ["test_connections_tab.py"],
        "why": "the bot-access fold loses its parked-by-choice label — a "
               "deliberately parked decision rendering as an ordinary "
               "feature is rule 3's defect inverted, and the next reader "
               "switches it on without meeting the switch-on conditions",
    },
    {
        "name": "domains_live_on_knowledge",
        "file": "app/admin_ui.py",
        "find": "    sub = (sub or \"\").strip().lower() or \"queue\"\n"
                "    if sub in DOMAIN_SUBS:",
        "replace": "    sub = (sub or \"\").strip().lower() or \"queue\"\n"
                   "    if False and sub in DOMAIN_SUBS:  # SABOTAGE",
        "suites": ["test_schema_tab.py"],
        "why": "the Data layer's old domain addresses stop forwarding to "
               "Knowledge and silently land on the queue — every bookmark "
               "and every ship-queue pointer from the hosted week shows the "
               "wrong page at a 200, the exact typo'd-bookmark trap the "
               "unknown-tab redirect was built to end",
    },
    {
        "name": "map_counts_from_the_kb",
        "file": "app/admin_ui.py",
        "find": "        n = counts.get(sub_, 0)\n"
                "        readers = reads_by_kind.get(label, 0)",
        "replace": "        n = counts.get(sub_, 0) + 1  # SABOTAGE\n"
                   "        readers = reads_by_kind.get(label, 0)",
        "suites": ["test_schema_tab.py"],
        "why": "the map's kind nodes drift from Knowledge's own counts — the "
               "one page whose whole job is to explain the data starts "
               "describing data that does not exist, and rule 8 (a number "
               "matches the list it opens) breaks on the explaining surface",
    },
    {
        "name": "leverage_counts_are_real",
        "file": "app/admin_ui.py",
        "find": "    <span class=\"chip off\">{caught_total} caught (90d)</span>",
        "replace": "    <span class=\"chip off\">{caught_total + 1} caught (90d)</span>",
        "suites": ["test_schema_tab.py"],
        "why": "the layer's headline value claim inflates past the assurance "
               "ledger it cites — the page built to prove the layer's worth "
               "honestly becomes the one place the console exaggerates",
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
    {
        "name": "voice_reads_the_website_only",
        "file": "app/voice.py",
        "find": "    pages, how = compliance.discover_pages(t.domain, limit=limit * 4)",
        "replace": "    pages, how = compliance.discover_pages(  # SABOTAGE\n"
                   "        (tenants.content_sources(tenant) or [{}])[-1].get('url', t.domain),\n"
                   "        limit=limit * 4)",
        "suites": ["test_brand_sources.py"],
        "why": "a brand's voice starts being derived from a campaign landing "
               "page — the loudest month of the year read as how the company "
               "speaks all year. The owner's constraint on multi-domain "
               "sources was that identity comes from the WEBSITE and nothing "
               "else, and this is the seam where that would quietly stop "
               "being true",
    },
    {
        "name": "harvest_reads_every_source",
        "file": "app/harvest.py",
        "find": "    srcs = tenants.content_sources(tenant)\n"
                "    pages, src_report = [], []",
        "replace": "    srcs = tenants.content_sources(tenant)[:1]  # SABOTAGE\n"
                   "    pages, src_report = [], []",
        "suites": ["test_brand_sources.py"],
        "why": "every landing page goes unread again: the claims, objections "
               "and pictures published there are invisible to the knowledge "
               "base, and the queue looks thin rather than incomplete — you "
               "cannot review what was never enumerated",
    },
    {
        "name": "scan_covers_landing_pages",
        "file": "app/compliance.py",
        "find": "    srcs = tenants.content_sources(tenant)\n"
                "    pages, src_report = [], []",
        "replace": "    srcs = tenants.content_sources(tenant)[:1]  # SABOTAGE\n"
                   "    pages, src_report = [], []",
        "suites": ["test_brand_sources.py"],
        "why": "the ban-list scan reports a clean brand while a banned phrase "
               "sits live on a landing page it never enumerated — the worst "
               "shape a compliance check can take, because a clean report is "
               "acted on",
    },
    {
        "name": "the_send_is_the_approval",
        "file": "app/approvals.py",
        # Pinned on the shared predicate rather than on the queue's filter:
        # the pill, the queue and the email fallback all read it, so one
        # sabotage here proves all three are covered at once.
        "find": "    return not (getattr(ap, \"kind\", \"\") == \"send_email\"\n"
                "                and (getattr(ap, \"payload\", None) or {}).get(\"draft_id\"))",
        "replace": "    return True  # SABOTAGE",
        "suites": ["test_draft_sync.py"],
        "why": "every drafted reply is back in the ship queue asking to be "
               "approved — a decision whose subject is sitting in the "
               "client's own mailbox, already answerable there. Approving it "
               "from the console after it was sent by hand is the duplicate "
               "delivery this whole path exists to prevent",
    },
    {
        "name": "a_sent_draft_teaches",
        "file": "app/approvals.py",
        # Anchored with the line ABOVE it: the draftless branch added in the
        # same file files an identical `learn.append`, and an anchor matching
        # twice patches whichever comes first — which may not be the one under
        # test. Caught by `test_sabotage_anchors` the day it was written.
        "find": "                ap.status = \"sent_outside\"\n"
                "                closed += 1\n"
                "                learn.append((ap.id, p.get(\"body\", \"\"), sent.get(\"body\", \"\")))",
        "replace": "                ap.status = \"sent_outside\"\n"
                   "                closed += 1  # SABOTAGE",
        "suites": ["test_draft_sync.py"],
        "why": "the delta between the draft and the letter is thrown away "
               "again on the ONLY path a reply now takes. `SystemRun."
               "edit_diff` goes back to never being written, `% sent as-is` "
               "goes back to unmeasurable, and the generator stops learning "
               "from the one honest signal it has — exactly the state this "
               "function's docstring described while quietly having it",
    },
    {
        "name": "a_deleted_draft_is_not_a_send",
        "file": "app/approvals.py",
        "find": "                sent = gc.sent_in_thread(alias, p.get(\"thread_id\") or \"\")",
        "replace": "                sent = {\"body\": p.get(\"body\", \"\")}  # SABOTAGE",
        "suites": ["test_draft_sync.py"],
        "why": "a draft the owner DELETED is filed as a reply the customer "
               "received: the thread stays owned so no other system may ever "
               "answer a question that got no answer, and a 'sent as-is' is "
               "recorded for a letter nobody wrote — flattering the "
               "generator with a measurement of nothing",
    },
    {
        "name": "a_cleared_item_stays_cleared",
        "file": "app/digest.py",
        "find": "    kept = [i for i in items\n"
                "            if (i[\"kind\"], i[\"ref\"]) not in dead\n"
                "            and (i[\"kind\"], i[\"ref\"], i[\"fingerprint\"]) not in seen]",
        "replace": "    kept = list(items)  # SABOTAGE",
        "suites": ["test_digest.py"],
        "why": "the briefing goes back to repeating everything the owner has "
               "already dealt with, every twelve hours, for ever — which is "
               "the exact state that made it 'practically useless'. Marking "
               "something handled would do nothing at all",
    },
    {
        "name": "a_changed_item_comes_back",
        "file": "app/digest.py",
        "find": "    seen = {(a.kind, a.ref, a.fingerprint) for a in acks\n"
                "            if a.state in (\"handled\", \"updated\")}",
        "replace": "    seen = {(a.kind, a.ref, i) for a in acks  # SABOTAGE\n"
                   "            for i in [a.fingerprint]\n"
                   "            if a.state in (\"handled\", \"updated\")} \\\n"
                   "        | {(a.kind, a.ref, x[\"fingerprint\"]) for a in acks\n"
                   "           for x in items if x[\"ref\"] == a.ref}",
        "suites": ["test_digest.py"],
        "why": "clearing something silences it FOR EVER, whatever happens to "
               "it afterwards: a blocked draft that breaks again for a new "
               "reason, or a bill whose amount changed, never reaches the "
               "owner again. Permanently silencing a live problem is how a "
               "real one gets missed",
    },
    {
        "name": "the_briefing_leads_with_the_client",
        "file": "app/digest.py",
        "find": "    order = sorted(by_client,\n"
                "                   key=lambda k: (by_client[k][0][\"rank\"], -len(by_client[k])))",
        "replace": "    order = sorted(by_client)  # SABOTAGE",
        "suites": ["test_digest.py"],
        "why": "the briefing goes back to alphabetical, so the account with "
               "an overdue bill can sit below one with nothing but filtered "
               "newsletters — the owner has to re-sort five clients in their "
               "head, which is the reading cost that made it unread",
    },
    {
        "name": "the_board_asks_once",
        "file": "app/admin_ui.py",
        "find": "        runs = (s.query(db.SystemRun)\n"
                "                .filter(db.SystemRun.system_id.in_(ids)).all())",
        "replace": "        runs = [r for i in ids for r in  # SABOTAGE\n"
                   "                s.query(db.SystemRun).filter(\n"
                   "                    db.SystemRun.system_id == i).all()]",
        "suites": ["test_systems_board.py"],
        "why": "the board goes back to asking the database once per system "
               "instead of once per page — and it was three FULL run-history "
               "loads per card, multiplied by every installed system across "
               "five accounts, which is what made the all-accounts view the "
               "slowest page in the console",
    },
    {
        "name": "the_board_row_stays_scannable",
        "file": "app/admin_ui.py",
        "find": "      {_work_strip(key, row, c)}\n"
                "      <div class=\"row\">\n"
                "        <a class=\"btn\" href=\"{_sysview_url(key, row)}\">Workflow &rarr;</a>",
        "replace": "      {_work_strip(key, row, c)}\n"
                   "      {_settings_section(key, row)}  <!-- SABOTAGE -->\n"
                   "      <div class=\"row\">\n"
                   "        <a class=\"btn\" href=\"{_sysview_url(key, row)}\">Workflow &rarr;</a>",
        "suites": ["test_systems_board.py"],
        "why": "the board row becomes fifteen kinds of thing again — ladder, "
               "promote, an 8-field contract form and the guidance thread on "
               "every card — which is what made a five-account board "
               "impossible to scan and buried the one control (the toggle) "
               "people come here to use",
    },
    {
        "name": "waiting_decides_where_you_are",
        "file": "app/web.py",
        "find": "    sys_key = str(form.get(\"back_system\") or \"\")\n"
                "    if sys_key:",
        "replace": "    sys_key = \"\"  # SABOTAGE\n"
                   "    if sys_key:",
        "suites": ["test_systems_board.py"],
        "why": "deciding an approval from a system's own Waiting tab dumps "
               "you on the Review tab instead of bringing you back — a "
               "decision costing you your place, which is the defect design "
               "rule 3 exists to name",
    },
    {
        "name": "data_only_classes_are_covered",
        "file": "app/admin_ui.py",
        "find": ".grp td{background:var(--rule2);font-size:.82rem;padding-top:9px}",
        "replace": ".grp-SABOTAGED td{background:var(--rule2)}",
        "suites": ["test_render_smoke.py"],
        "why": "the Plan tab's table group headings render unstyled again — "
               "and, worse, the coverage check goes back to not being able "
               "to SEE it. `.grp` only appears on a row that exists when the "
               "account has keywords, so the smoke suite walked an empty "
               "Plan tab and reported full coverage of markup it never "
               "rendered. This entry fails only while the suite seeds a real "
               "map, which is what makes the blind spot stay closed",
    },
    {
        "name": "one_window_governs_the_page",
        "file": "app/admin_ui.py",
        "find": "        \"board\": lambda: (_board_section(key, tenant, days)",
        "replace": "        \"board\": lambda: (_board_section(key, tenant, 7)  # SABOTAGE",
        "suites": ["test_plan_tab.py"],
        "why": "the board goes back to a hard-coded 7 days while the "
               "7/28/90 control governs only the section below it — so "
               "'Moved in the last 7 days' sits directly above a control "
               "that silently does not affect it, and the page says two "
               "different things with the same word",
    },
    {
        "name": "strategy_reaches_the_owner",
        "file": "app/admin_ui.py",
        "find": "        \"strategy\": lambda: _strategy_section(key, tenant, days),",
        "replace": "        \"strategy\": lambda: \"\",  # SABOTAGE",
        "suites": ["test_plan_tab.py"],
        "why": "`strategy.read` goes back to being computed for the planner "
               "and shown to nobody — which is the state it was in since it "
               "was written: neglected cohorts, an unbalanced give:ask and a "
               "programme carried by one product, all answerable and none of "
               "it ever put in front of the owner",
    },
    {
        "name": "every_writer_names_its_artifact",
        "file": "app/skill_pack.py",
        "find": "                    body=final_html, draft_body=final_html, meta=_meta,",
        "replace": "                    body=final_html, draft_body=final_html,",
        "suites": ["test_artifact_identity.py"],
        "why": "the campaign writer — which keeps its own ArtifactBody row "
               "because the HTML is only final after render — stops giving "
               "the email an identity, and the Drafts index shows three "
               "'campaign email · <date>' rows again. This is the writer "
               "that was missed when the other two were fixed and the job "
               "was called done",
    },
    {
        "name": "the_queue_names_the_thing",
        "file": "app/admin_ui.py",
        "find": "    art = (arts or {}).get(oid)\n"
                "    if art is not None and (getattr(art, \"meta\", None) or {}):\n"
                "        return artifact_label(art)",
        "replace": "    art = (arts or {}).get(oid)  # SABOTAGE\n"
                   "    if False:\n"
                   "        return artifact_label(art)",
        "suites": ["test_review_tab.py"],
        "why": "every queued decision goes back to being titled by its "
               "approval summary — for a skill_output that is the skill's "
               "name and eighty characters of raw body, so a queue of "
               "campaigns reads as several near-identical rows of HTML head, "
               "on the page whose entire job is choosing between them",
    },
    {
        "name": "a_draft_has_a_real_name",
        "file": "app/admin_ui.py",
        # Repointed 2026-08-28: the campaign branch gained a `push` fallback
        # so pre-`meta` rows are named too, which moved the old anchor.
        "find": "    if fmt == \"campaign_email\":\n"
                "        # `push` is the machine recipe this artifact already carries",
        "replace": "    if False:  # SABOTAGE\n"
                   "        # `push` is the machine recipe this artifact already carries",
        "suites": ["test_article_review.py"],
        "why": "every draft goes back to being named 'format · timestamp', so "
               "four campaigns to four different segments are four identical "
               "rows and the only way to tell them apart is to open each one "
               "— on the page whose whole job is deciding between them",
    },
    {
        "name": "a_live_draft_is_not_an_unanswered_one",
        "file": "app/approvals.py",
        "find": "                if answered and float(answered.get(\"at\") or 0) > raised:",
        "replace": "                if False:  # SABOTAGE",
        "suites": ["test_draft_sync.py"],
        "why": "a reply answered from a phone — or composed fresh instead of "
               "sending the draft — leaves the draft sitting in the mailbox, "
               "and the approval asks to be decided for ever. The console "
               "shows a queue of mail already handled, the drafts pile up in "
               "Gmail, and what the owner actually wrote is never learned "
               "from. This is the exact state the owner found",
    },
    {
        "name": "answered_mail_stops_asking",
        "file": "app/approvals.py",
        "find": "                        sent = gc.sent_to_since(alias, p.get(\"to\") or \"\",\n"
                "                                                db.as_utc(ap.created_at))",
        "replace": "                        sent = {}  # SABOTAGE",
        "suites": ["test_draft_sync.py"],
        "why": "outbound mail with no Gmail draft behind it — an RFQ, an "
               "invoice reminder, a shipment follow-up — is never reconciled "
               "again, so answering the person yourself leaves the approval "
               "pending for ever and the queue fills with work already done. "
               "The delta between what was drafted and what you actually "
               "wrote is lost with it",
    },
    {
        "name": "attention_clears_when_read",
        "file": "app/admin_ui.py",
        "find": "    backlog = systems.attention_unseen(\"\" if every else tenant, 30)",
        "replace": "    backlog = systems.attention(\"\" if every else tenant, 30)",
        "suites": ["test_systems_check.py"],
        "why": "the Systems tab's attention card stands for ever again, "
               "whether or not the owner has read the check it points at — "
               "and a card that never clears is a card that stops being "
               "read, which is the whole reason it was worth raising",
    },
    {
        "name": "attention_returns_for_a_new_reason",
        "file": "app/systems.py",
        "find": "    return [] if seen_fp and seen_fp == attention_fingerprint(rows) else rows",
        "replace": "    return [] if seen_fp else rows  # SABOTAGE",
        "suites": ["test_systems_check.py"],
        "why": "acknowledged stops meaning 'I have seen THESE' and starts "
               "meaning 'stop telling me'. A brand-new kind of refusal — a "
               "connection that just died, a gate nobody has hit before — "
               "never raises the card again, because one glance months ago "
               "silenced every future issue",
    },
    {
        "name": "the_artifact_is_self_describing",
        "file": "app/web.py",
        "find": "        row.meta = {**(row.meta or {}),\n"
                "                    \"title\": edited[\"title\"],",
        "replace": "        row.meta = {**(row.meta or {}),  # SABOTAGE\n"
                   "                    \"title\": (row.meta or {}).get(\"title\", \"\"),",
        "suites": ["test_article_review.py"],
        "why": "a title typed on an artifact with no pending approval is "
               "silently discarded again — the body saves, the identity does "
               "not, and the button doing it says 'the push uses exactly "
               "this'. Silent loss under a promise is the worst shape a save "
               "can have",
    },
    {
        "name": "the_push_uses_what_was_reviewed",
        "file": "app/approvals.py",
        "find": "            _fields_from_artifact(p.get(\"output_id\") or \"\", p[\"fields\"]))",
        "replace": "            p[\"fields\"])  # SABOTAGE",
        "suites": ["test_article_review.py"],
        "why": "the CMS write goes back to publishing the approval payload's "
               "copy of the text rather than the artifact the owner actually "
               "read and edited — so any edit made while no approval was "
               "pending reaches the store as the older words, with nothing "
               "anywhere saying the two had diverged",
    },
    {
        "name": "the_plan_shows_what_happened",
        "file": "app/admin_ui.py",
        "find": "    items = [r for r in runs\n"
                "             if (getattr(r, \"brief\", None) or {}).get(\"plan\") is not None]",
        "replace": "    items = [r for r in runs  # SABOTAGE\n"
                   "             if (getattr(r, \"brief\", None) or {}).get(\"plan\") is not None\n"
                   "             and r.stage == systems.PLANNED]",
        "suites": ["test_plan_tab.py"],
        "why": "the Plan tab goes back to showing only what is COMING: a "
               "plan vanishes the moment the tick consumes it, so nothing "
               "on the planning side can answer what was planned last week "
               "and what became of it — no shipped item, no skip and its "
               "reason, and no overdue plan sitting held while the worker "
               "counts it and says nothing",
    },
    {
        "name": "a_stuck_plan_says_why",
        "file": "app/admin_ui.py",
        "find": "                verdict = systems.consumable(run, sysrow)\n"
                "                why = \"\" if verdict[\"ok\"] else verdict[\"why\"]",
        "replace": "                why = \"\"  # SABOTAGE",
        "suites": ["test_plan_tab.py"],
        "why": "an overdue plan is listed as merely late when it is actually "
               "STUCK — the system is off, or its instruction is incomplete, "
               "or the rung wants a human. The worker already refuses it "
               "every tick and increments a counter nobody sees; without "
               "this the console repeats that silence",
    },
    {
        "name": "a_dateless_plan_is_not_scheduled",
        "file": "app/admin_ui.py",
        # Repointed 2026-08-28: the bidirectional Schedule rewrote this
        # section, so the old anchor stopped existing and the guard went
        # quiet. The rule it protects moved into `_plan_outcome`.
        "find": "        if not systems._valid_date(when):\n"
                "            return ('<span class=\"chip off\">no date</span>',",
        "replace": "        if False:  # SABOTAGE\n"
                   "            return ('<span class=\"chip off\">no date</span>',",
        "suites": ["test_plan_tab.py"],
        "why": "a plan whose date is missing or unparseable is listed under "
               "a heading that says it will come due. `plan_complete` will "
               "never pass it and the tick will never consume it, so it "
               "reads as queued and means lost — which is the one thing the "
               "Schedule view exists to make visible",
    },
    {
        "name": "a_lifted_rule_stays_lifted",
        "file": "app/kb.py",
        "find": "        lifted = [x for x in (row.lifted_claims or [])\n"
                "                  if str(x.get(\"phrase\", \"\")).lower() != phrase.lower()]",
        "replace": "        lifted = list(row.lifted_claims or [])  # SABOTAGE",
        "suites": ["test_ban_list.py"],
        "why": "a rule the owner lifted and then restored is enforced again "
               "AND still listed as lifted — the tab states the same fact in "
               "two opposite directions at once, and the Restore button on a "
               "rule that is already live is a control whose press means "
               "nothing. Rule 8, on the one list that blocks every draft",
    },
    {
        "name": "one_writer_owns_the_ban_list",
        "file": "app/systems.py",
        "find": "    _kb.add_banned(tenant, phrase)",
        "replace": "    with db.SessionLocal() as s:  # SABOTAGE\n"
                   "        brand = s.get(db.KbBrand, tenant)\n"
                   "        brand.banned_claims = list(brand.banned_claims or []) + [phrase]\n"
                   "        s.commit()",
        "suites": ["test_ban_list.py"],
        "why": "promotion becomes a SECOND writer of `banned_claims` again, "
               "so a phrase the owner deliberately lifted can be re-added by "
               "a path that knows nothing about the lifted record — enforced "
               "and listed-as-lifted simultaneously. This is the exact shape "
               "of the writer-I-missed defect (§6b): the instance nobody "
               "audited is the one that is broken",
    },
    {
        "name": "the_theme_cannot_take_the_tab",
        "file": "app/admin_ui.py",
        "find": "    except Exception as exc:                                     # noqa: BLE001\n"
                "        log.exception(\"brand theme unreadable for %s\", tenant)\n"
                "        theme_err = f\"{exc.__class__.__name__}: {exc}\"",
        "replace": "    except Exception as exc:  # SABOTAGE\n"
                   "        raise",
        "suites": ["test_brand_theme.py"],
        "why": "a stale Shopify credential or a corrupt theme blob takes the "
               "WHOLE Brand tab down again — including the identity editor, "
               "the hard rules and the source list, which are the controls a "
               "person would reach for to fix the account. A failure in one "
               "half removing the other half's controls is how a fixable "
               "problem becomes an unfixable one",
    },
    {
        "name": "a_landing_page_is_a_page",
        "file": "app/compliance.py",
        "find": "    if not tenants._is_bare_host(base):",
        "replace": "    if False:  # SABOTAGE",
        "suites": ["test_brand_sources.py"],
        "why": "every source is treated as a SITE again, so a landing page "
               "on a path asks for `<path>/sitemap.xml`, then wp-json under "
               "the path, then crawls the links OUT of the page — and never "
               "reads the page itself. A campaign landing page is "
               "deliberately link-free, so the commonest landing page in the "
               "world discovers nothing and its facts reach no queue, while "
               "the run reports a healthy total from the website beside it",
    },
    {
        "name": "a_page_is_not_its_host",
        "file": "app/tenants.py",
        "find": "            page = _norm_url(url)\n"
                "            if page == site:",
        "replace": "            page = _norm(url)  # SABOTAGE\n"
                   "            if page == _norm(t.domain or ''):",
        "suites": ["test_brand_sources.py"],
        "why": "source identity collapses back to the HOST, so "
               "`theirdomain.com/pages/spring` is refused as \"the website "
               "itself\" — which is the only kind of landing page a Shopify "
               "client has — and two campaigns sharing one host silently "
               "become one source with the wrong campaign's name on every "
               "claim read off either",
    },
    {
        "name": "an_empty_source_says_so",
        "file": "app/web.py",
        "find": "    if empty:\n"
                "        bits.append(\"READ NOTHING: \" + \", \".join(str(e) for e in empty[:4]))",
        "replace": "    if False:  # SABOTAGE\n"
                   "        pass",
        "suites": ["test_brand_sources.py"],
        "why": "a source that enumerated nothing goes silent again, hidden "
               "behind a website that enumerated plenty: the line reads "
               "\"proposed_count 12 · pages_read 40\" and the owner cannot "
               "learn that the landing page they just added contributed "
               "zero. Absence read as success — the exact defect design rule "
               "12 was written for",
    },
    {
        "name": "a_run_says_what_it_lost",
        "file": "app/web.py",
        "find": "    lost = _losses(result)\n"
                "    if lost:\n"
                "        bits.append(\"LOST: \" + \" · \".join(lost))",
        "replace": "    lost = []  # SABOTAGE",
        "suites": ["test_brand_sources.py"],
        "why": "a run reports only its GAINS again — a harvest that proposed "
               "twelve claims and refused to write five says \"12\" and "
               "nothing else. `harvest`'s own source says these are different "
               "numbers and that conflating them hid a whole class of loss; "
               "this is the line where they get conflated, and the owner "
               "reads a healthy total over a run that threw work away",
    },
    {
        "name": "catches_are_not_silently_capped",
        "file": "app/admin_ui.py",
        "find": "    all_catches = assurance.catches(scope, days, limit=2000,\n"
                "                                    system_key=system, rule=rule)",
        "replace": "    all_catches = assurance.catches(scope, days, limit=20,  # SABOTAGE\n"
                   "                                    system_key=system, rule=rule)",
        "suites": ["test_assurance_tab.py"],
        "why": "the catch list is silently capped again, so on any account "
               "busy enough to be worth checking the twenty-first catch does "
               "not exist and the page says nothing about it. A silent cap on "
               "the one page whose whole job is to be believed teaches "
               "exactly the wrong lesson about every other number on it",
    },
    {
        "name": "every_account_can_be_scanned",
        "file": "app/admin_ui.py",
        # Repointed 2026-08-28 the same day it was written: `_scan_rows`
        # grew a `rows` argument so it stops enumerating the accounts a
        # second time (the frame contract allows exactly one), and the anchor
        # named the old one-argument call.
        "find": "       'is here, with when it last ran.</p>' + _scan_rows(key, _rows)}",
        "replace": "       'is here, with when it last ran.</p>'}  # SABOTAGE",
        "suites": ["test_assurance_tab.py"],
        "why": "the all-accounts view goes back to telling you to go and pick "
               "an account — a named gap whose fix is an instruction to "
               "navigate elsewhere, which is the defect design rule 1 exists "
               "to stop, on the page that reports whether anyone has ever "
               "checked a client's live site",
    },
    {
        "name": "the_counts_describe_the_window",
        "file": "app/diagnostics.py",
        "find": "    everything = events(tenant, days, system=system, limit=WINDOW_CEILING)",
        "replace": "    everything = events(tenant, days, system=system, limit=limit)  # SABOTAGE",
        "suites": ["test_diagnostics_surface.py"],
        "why": "the triage tab contradicts itself again: the cap is applied "
               "before the counting, so on a busy account the level chips "
               "describe the newest 200 rows rather than the window, and "
               "choosing \"problems only\" renders \"nothing at all was "
               "recorded ... a finding about the plumbing\" on the same page "
               "whose Platforms table shows the failures. It errs toward "
               "calling a broken account healthy, on the one page whose job "
               "is to say whether anything is broken",
    },
    {
        "name": "silent_means_nothing_was_recorded",
        "file": "app/diagnostics.py",
        "find": '            "silent": not everything,',
        "replace": '            "silent": not ev,  # SABOTAGE',
        "suites": ["test_diagnostics_surface.py"],
        "why": "a filter that simply matched nothing is reported as broken "
               "plumbing — \"no run, no tool call, no check and no approval\" "
               "— so a healthy account viewed through a narrow filter reads "
               "as dead. Design rule 12: absence is not an answer, and the "
               "absence of MATCHES is a different fact from the absence of "
               "RECORDS",
    },
    {
        "name": "a_named_gap_reaches_a_tab_that_can_clear_it",
        "file": "app/admin_ui.py",
        "find": '    "brand": ("Brand", "add the hard rule"),',
        "replace": "    # SABOTAGE",
        "suites": ["test_diagnostics_surface.py"],
        "why": "the missing-ban-list card renders an EMPTY control row again "
               "— the reader is told the ban list is missing and given "
               "nothing to press, on the class that `systems.py` deliberately "
               "split out of `knowledge` so that the fix would land on the "
               "tab that can actually author the rule",
    },
    {
        "name": "the_drafter_gets_a_craft_brief",
        "file": "app/skill_pack.py",
        # Repointed the same day it was written: the prompt assembly moved
        # out of `_draft_ad_live` into `ad_prompt` so it could be asserted
        # without an API key, which de-indented this line by four spaces.
        "find": '    parts.append("\\n## How to answer\\n" + ad_craft.REPLY_FORMAT)',
        "replace": "    pass  # SABOTAGE",
        "suites": ["test_ad_craft.py"],
        "why": "the drafter stops being told how to answer, so it declares no "
               "value levers and writes no headline, and every variant then "
               "fails the value-equation gate on a brief that was never "
               "delivered. The wider defect this guards is the one the owner "
               "named: an ad generator given only prohibitions writes "
               "prohibitionally-correct slop",
    },
    {
        "name": "an_offer_must_beat_the_truncation",
        "file": "app/ad_craft.py",
        "find": "        elif at > TRUNCATION:",
        "replace": "        elif False:  # SABOTAGE",
        "suites": ["test_ad_craft.py"],
        "why": "the offer can be buried past the ~125 characters Meta shows "
               "before the fold again — the exact defect the live copy audit "
               "found on four of five texts. An offer nobody reads was not "
               "made, and the ad pays full price for the impression",
    },
    {
        "name": "gifting_does_not_generalise",
        "file": "app/ad_craft.py",
        "find": "    if any(w in low for w in _GIFT_EVIDENCE):",
        "replace": "    if True:  # SABOTAGE",
        "suites": ["test_ad_craft.py"],
        "why": "every account gets a gifting angle again, so one ad in five "
               "for an events venue or a showroom is written to a gift-buyer "
               "who does not exist. Nothing downstream catches it: the "
               "validator asks whether a draft is TRUE, and 'the most "
               "personal gift' is not false, it is about somebody else's "
               "business",
    },
    {
        "name": "the_stage_decides_who_is_listening",
        "file": "app/skill_pack.py",
        "find": "        angles = funnel.angles_for_stage(stage, angles)",
        "replace": "        pass  # SABOTAGE",
        "suites": ["test_funnel.py"],
        "why": "the funnel stage stops narrowing the angles, so an awareness "
               "batch is written with the offer-led and objection-killer "
               "angles — asking a stranger to buy, and answering a hesitation "
               "the reader has not formed yet. Both are well-formed ads aimed "
               "at the wrong reader, and NOTHING else in the pipeline can see "
               "it: the validator asks whether a draft is true and the craft "
               "ruleset asks whether it is well written. Neither asks who is "
               "listening",
    },
    {
        "name": "a_missing_input_is_named",
        "file": "app/funnel.py",
        "find": "    note = [_COST.get(k, f\"no {k} on file\") for k in missing]",
        "replace": "    note = []  # SABOTAGE",
        "suites": ["test_funnel.py"],
        "why": "a stage whose leading knowledge is absent goes quiet about "
               "it, so an account with no objections gets a consideration ad "
               "built out of whatever else was lying around — plausible, "
               "wrong, and undetectable downstream. The owner's 'if they are "
               "available, of course' is a licence to run thin, not a licence "
               "to run thin in silence",
    },
    {
        "name": "email_reads_the_same_funnel",
        "file": "app/skill_pack.py",
        "find": "    if craft.get(\"funnel\"):\n        out.append(funnel.brief(craft[\"funnel\"]))",
        "replace": "    if False:  # SABOTAGE\n        pass",
        "suites": ["test_campaign.py", "test_funnel.py"],
        "why": "the campaign drafter stops being shown the account's own "
               "objections and situations, so 'answer their doubt' goes back "
               "to being a category rather than an instruction — and the "
               "shared strategy layer becomes a thing only the ad skill "
               "reads, which is the unwired-claim shape this codebase keeps "
               "having to fix",
    },
    {
        "name": "the_blog_reads_the_same_funnel",
        "file": "app/skill_pack.py",
        # The ad prompt now carries the identical two lines, so the anchor
        # takes the line AFTER them to stay unique — `test_sabotage_anchors`
        # caught the collision the moment the blog was wired.
        "find": "    if bundle.get(\"funnel\"):\n"
                "        parts.append(funnel.brief(bundle[\"funnel\"]))\n"
                "    if angle:",
        "replace": "    if False:  # SABOTAGE\n        pass\n    if angle:",
        "suites": ["test_blog.py", "test_funnel.py"],
        "why": "an article for 'best X vs Y' stops being briefed as writing "
               "for somebody comparing alternatives, so a comparison search "
               "gets an explainer — the right words about the wrong reader. "
               "The keyword layer knew the intent all along and the drafter "
               "was never told",
    },
    {
        "name": "the_title_is_a_title_not_the_query",
        "file": "app/skill_pack.py",
        "find": "    title = _h1_of(body)",
        "replace": "    title = keyword[:1].upper() + keyword[1:]  # SABOTAGE",
        "suites": ["test_blog.py", "test_seo_head.py"],
        "why": "the article's Title and <title> tag go back to being the "
               "capitalised SEARCH QUERY — 'Buy acrylic dinnerware' — while "
               "the H1 the drafter was asked for is written into the body and "
               "thrown away. It reads like a deliberate optimisation, which "
               "is why it survived: nobody looks twice at a title that "
               "contains the keyword",
    },
    {
        "name": "a_targeting_title_is_left_alone",
        "file": "app/skill_pack.py",
        "find": "    if _targets_keyword(keyword, title) or keyword.lower() in title.lower():",
        "replace": "    if keyword.lower() in title.lower():  # SABOTAGE",
        "suites": ["test_seo_head.py"],
        "why": "matching the query by exact substring again, so a title that "
               "plainly targets it — 'Melamine and Acrylic Dinnerware, "
               "Compared' for 'acrylic dinnerware sets' — is judged a miss, "
               "gets the query stapled to the front, and then loses its "
               "readable half to the 60-character trim. The reader sees the "
               "search phrase followed by a fragment",
    },
    {
        "name": "a_dose_does_not_back_an_effect",
        "file": "app/claim_trace.py",
        "find": "            if r[\"figures\"] and not (r[\"figures\"] & set(_FIGURE.findall(sent))):",
        "replace": "            if False:  # SABOTAGE",
        "suites": ["test_claim_trace.py"],
        "why": "a claim about a DOSE starts backing a sentence about an "
               "EFFECT — 'each serving contains 1000mg of omega-3' credited "
               "as the support for 'omega-3 is widely researched for "
               "moderating inflammation'. They share the ingredient and "
               "nothing else, and the review page then shows a green mark on "
               "an unapproved health claim. Of every mistake available here "
               "that is the worst: it does not fail to flag a problem, it "
               "actively vouches for one",
    },
    {
        "name": "the_review_shows_what_is_unbacked",
        "file": "app/admin_ui.py",
        "find": "    return f\"\"\"\n<div class=\"anchor\" id=\"grounding\"></div>",
        "replace": "    return \"\"  # SABOTAGE\n    return f\"\"\"\n<div class=\"anchor\" id=\"grounding\"></div>",
        "suites": ["test_claim_trace.py"],
        "why": "the workroom stops showing which sentences stand on a claim, "
               "so an article that is 0% grounded looks exactly like one that "
               "is fully grounded — which is the state the Eien article "
               "shipped in, past every gate, because nothing rendered the "
               "difference",
    },
    {
        "name": "a_mention_is_not_a_recommendation",
        "file": "app/claim_trace.py",
        "find": "    if not vocab or not any(m in low for m in _RECOMMENDS):\n        return []",
        "replace": "    if not vocab:  # SABOTAGE\n        return []",
        "suites": ["test_claim_trace.py"],
        "why": "every sentence NAMING something outside the catalogue is "
               "flagged, not only the ones recommending it — so a "
               "competitor-comparison article, which the owner explicitly "
               "wants and which must be able to name the shelf, lights up as "
               "a defect end to end. The reviewer then learns to ignore the "
               "marker, and it stops catching the case it exists for",
    },
    {
        "name": "an_output_records_what_backed_it",
        "file": "app/ledger.py",
        "find": "        pct = claim_trace.coverage_of(tenant, body, claim_ids)",
        "replace": "        pct = -1  # SABOTAGE",
        "suites": ["test_claim_trace.py"],
        "why": "nothing records how much of each output stood on a claim, so "
               "the trend has no history to draw and the question 'is filling "
               "in the knowledge base making the output better' becomes "
               "unanswerable — not wrong, unanswerable, and only in six "
               "months when somebody asks",
    },
    {
        "name": 'an_embedding_is_recorded',
        "file": 'app/embed.py',
        "find": '                input_tokens=(payload.get("usage") or {}).get("prompt_tokens", 0))',
        "replace": '                input_tokens=0)  # SABOTAGE',
        "suites": ['test_spend_complete.py'],
        "why": 'every semantic search records a free call, so the per-email cost of the path that answers customers reads as zero and the spend report is confidently wrong rather than visibly incomplete',
    },
    {
        "name": 'an_image_is_recorded',
        "file": 'app/imagegen.py',
        "find": '        usage.log_image("image_edit" if "edits" in path else "image_generate",',
        "replace": '        pass; usage.log_image("x" if 0 else "image_generate",  # SABOTAGE',
        "suites": ['test_spend_complete.py'],
        "why": 'image generation stops being attributed at the one seam every generator returns through — the most expensive single thing the system does, invisible again',
    },
    {
        "name": 'an_unknown_model_is_not_priced_as_sonnet',
        "file": 'app/usage.py',
        "find": '    pin, pout = PRICES.get(model, UNPRICED)',
        "replace": '    pin, pout = PRICES.get(model, (3.0, 15.0))  # SABOTAGE',
        "suites": ['test_spend_complete.py'],
        "why": "any model nobody has priced is billed at Sonnet's rate — $18 per million tokens of invented spend — so an embedding reads 150x its true cost and the report looks precise while being wrong",
    },
    {
        "name": 'a_proposal_is_acknowledged_on_the_card',
        "file": 'app/admin_ui.py',
        "find": '    waiting = bool(note.get("proposed"))',
        "replace": '    waiting = False  # SABOTAGE',
        "suites": ['test_claim_trace.py'],
        "why": 'pressing Add claim reloads a page that looks exactly the same — the note still says the sentence needs a claim, the button is still there, and the only way to learn it worked is to go hunting on Review, so it gets pressed twice or not believed',
    },
    {
        "name": 'a_preview_link_opens_a_tab',
        "file": 'app/admin_ui.py',
        "find": 'PREVIEW_SANDBOX = "allow-popups allow-popups-to-escape-sandbox"',
        "replace": 'PREVIEW_SANDBOX = "allow-popups"  # SABOTAGE',
        "suites": ['test_preview_links.py'],
        "why": 'the tab opens still carrying every sandbox flag, so the linked page loads scriptless in an opaque origin and looks broken — the reviewer concludes the link is wrong when the link is fine',
    },
    {
        "name": 'a_preview_does_not_eat_itself',
        "file": 'app/admin_ui.py',
        "find": '    m = _HEAD_OPEN.search(html_)\n    if m:\n        return html_[:m.end()] + _BASE_TAG + html_[m.end():]',
        "replace": '    m = _HEAD_OPEN.search(html_)\n    if m:\n        return html_  # SABOTAGE',
        "suites": ['test_preview_links.py'],
        "why": 'links in a full email document get no target, so clicking one navigates the iframe in place: the email is replaced by whatever it pointed at and the only way back is reloading the workroom',
    },
    {
        "name": 'a_preview_never_repoints_a_link',
        "file": 'app/admin_ui.py',
        "find": '_BASE_TAG = \'<base target="_blank">\'',
        "replace": '_BASE_TAG = \'<base target="_blank" href="/">\'  # SABOTAGE',
        "suites": ['test_preview_links.py'],
        "why": 'a base href re-resolves every relative URL in the email, so the preview shows links going somewhere other than where they will actually go once the ESP sends it',
    },
    {
        "name": 'the_card_is_the_preview',
        "file": 'app/admin_ui.py',
        "find": '        reading = (f\'<div class="live" data-notes="{_esc(_payload)}">\'',
        "replace": '        reading = (f\'<div class="live" data-notes="">\'  # SABOTAGE',
        "suites": ['test_claim_trace.py'],
        "why": 'the article renders but no sentence can be located in it, so every marker stacks at the top of the gutter pointing at nothing — and the separate Preview card was DELETED on the strength of this lane working, so a silent failure here leaves the workroom with no preview at all',
    },
    {
        "name": 'a_claim_from_a_draft_is_only_proposed',
        "file": 'app/web.py',
        "find": '        art.tenant or "", sentence, "", [], proof_type="", status="pending",',
        "replace": '        art.tenant or "", sentence, "", [], proof_type="", status="active",  # SABOTAGE',
        "suites": ['test_claim_trace.py'],
        "why": 'a sentence a model wrote becomes an APPROVED claim in one click, so the model authors its own evidence: the next draft cites it, the citation check passes, and an unreviewed guess is now the thing that makes other drafts look grounded',
    },
    {
        "name": 'an_off_catalogue_steer_is_not_a_claim',
        "file": 'app/admin_ui.py',
        "find": '    add = ("" if note["state"] in ("ok", "off") or note.get("proposed") else',
        "replace": '    add = ("" if note["state"] in ("ok",) or note.get("proposed") else  # SABOTAGE',
        "suites": ['test_claim_trace.py'],
        "why": 'the panel offers to file \\u201cglucosamine remains the benchmark\\u201d as a claim about an account that has never sold it \\u2014 one mis-click away from approving the exact sentence the off-catalogue check exists to catch',
    },
    {
        "name": 'a_fact_about_the_world_is_not_a_brand_claim',
        "file": 'app/admin_ui.py',
        "find": '        elif claim_trace.about_us(sent["text"], marks):',
        "replace": '        elif True:  # SABOTAGE',
        "suites": ['test_claim_trace.py'],
        "why": 'every cited fact about a condition, a material or a market is reported as an unfounded claim about the company, so a research-led article shows a wall of amber and the owner learns to ignore the one mark that matters — which is how the Eien knee-pain article read',
    },
    {
        "name": 'a_country_code_is_not_a_pronoun',
        "file": 'app/claim_trace.py',
        "find": '    if _PRONOUN.search(raw) or _PRONOUN_START.match(raw):',
        "replace": '    if any(w in raw.lower() for w in _FIRST_PERSON):  # SABOTAGE',
        "suites": ['test_claim_trace.py'],
        "why": "'tested in a US facility' matches the pronoun 'us' and the country code is read as the brand, so third-party and regulatory statements are silently reclassified as claims about the company",
    },
    {
        "name": 'a_judgement_can_be_filed_where_it_was_formed',
        "file": 'app/admin_ui.py',
        "find": '            + form("system", teach, "Never again",',
        "replace": '            + form("system", teach, "SABOTAGED",',
        "suites": ['test_claim_trace.py'],
        "why": 'the note loses its teach-the-system action, so the only way to stop a mistake recurring is the free-text form at the bottom of the page — which means scrolling away from the sentence you are judging and retyping it, and in practice means nobody does it',
    },
    {
        "name": 'nothing_is_inserted_into_the_artifact',
        "file": 'app/admin_ui.py',
        "find": '    <div class="gut">{"".join(_marker_html(n) for n in notes)}</div>\n    <div class="gread"><div class="body">',
        "replace": '    <div class="gut"></div>\n    <div class="gread"><div class="body">{"".join(_marker_html(n) for n in notes)}',
        "suites": ['test_claim_trace.py'],
        "why": "the numbers move back into the text flow, so the reading is no longer the artifact: lines re-wrap, and on an ad Meta's 125-character fold moves — which makes every offer-position check on this page a check of a fold that will not happen",
    },
    {
        "name": 'one_index_joins_marker_and_note',
        "file": 'app/claim_trace.py',
        "find": '            s["note"] = n',
        "replace": '            s["note"] = 0  # SABOTAGE',
        "suites": ['test_claim_trace.py'],
        "why": 'the marker in the gutter and the entry in the panel stop sharing a number, so clicking note 3 highlights the wrong sentence — silently, and only on bodies where prose interleaves with assertions, which is every real one',
    },
    {
        "name": 'a_heading_is_its_own_sentence',
        "file": 'app/claim_trace.py',
        "find": '    t = _BLOCK.sub("\\n", t)',
        "replace": '    t = _BLOCK.sub(" ", t)  # SABOTAGE',
        "suites": ['test_claim_trace.py'],
        "why": "a heading carrying no full stop is glued to the first sentence of the paragraph under it and the pair is scored as one, so a heading like 'Glucosamine and chondroitin work' can ride a claim that only covers the sentence after it — and the review surface loses the author's paragraphs on the way",
    },
    {
        "name": "a_direction_needs_enough_outputs",
        "file": "app/claim_trace.py",
        "find": "        enough = min(len(earlier), len(later)) >= MIN_FOR_DIRECTION",
        "replace": "        enough = True  # SABOTAGE",
        "suites": ["test_claim_trace.py"],
        "why": "the assurance page draws an arrow and a points figure off one "
               "output against two, on the one page whose entire job is to be "
               "believed — and a direction is the number here most likely to "
               "be repeated to a client",
    },
    {
        "name": "the_trend_is_rendered_where_it_is_asked",
        "file": "app/admin_ui.py",
        "find": "      {_grounding_trend(scope, days)}",
        "replace": "      <!-- SABOTAGE -->",
        "suites": ["test_claim_trace.py"],
        "why": "grounding coverage is recorded on every output and shown "
               "nowhere, so the owner's own question — is the output "
               "improving as the knowledge base fills — has an answer in the "
               "database that no surface renders. A unit with no piping, "
               "which is the backlog this console keeps paying down",
    },
    {
        "name": "prose_is_not_scored_zero",
        "file": "app/claim_trace.py",
        "find": "    return -1 if pct is None else int(pct)",
        "replace": "    return int(pct or 0)  # SABOTAGE",
        "suites": ["test_claim_trace.py"],
        "why": "an output that asserts nothing checkable is recorded as 0% "
               "grounded rather than as not-applicable, so every short, "
               "honest, claim-free asset drags the average down and the trend "
               "measures how much prose was written rather than how well it "
               "was grounded",
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
