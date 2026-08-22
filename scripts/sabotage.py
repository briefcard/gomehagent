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
        "find": "    if (item.get(\"ok\") and not missing and native_ok and not hard",
        "replace": "    if (not missing and native_ok  # SABOTAGE",
        "suites": ["test_campaign_email.py"],
        "why": "a campaign email that FAILED the banned-claims check still gets "
               "drafted into the client's live ESP",
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
