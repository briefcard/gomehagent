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
        "name": 'a_draft_never_reaches_the_clients_library',
        "file": 'app/hosting.py',
        "find": '    if str(row.review or "") != prov.APPROVED:',
        "replace": '    if False:  # SABOTAGE',
        "suites": ['test_hosting.py'],
        "why": "unapproved frames are uploaded to the client's own media library, where their staff will find them and use them as though they were finished work",
    },
    {
        "name": 'a_refusal_keeps_the_picture',
        "file": 'app/hosting.py',
        "find": '        return {"ok": False, "keeps": True, "error": str(exc)[:300]}',
        "replace": '        kb.set_asset_hosted(asset_id, {"url": "?"}); return {"ok": False}  # SABOTAGE',
        "suites": ['test_hosting.py'],
        "why": 'an account with no CMS gets a row that says it is hosted, pointing at a library that does not have it — which looks like success and 404s a fortnight later when the sweep drops our copy',
    },
    {
        "name": 'a_frame_and_its_crops_move_together',
        "file": 'app/hosting.py',
        "find": '            return {"ok": False, "keeps": True, "error": (\n                f"the frame uploaded but its {fmt} crop did not "',
        "replace": '            return {"ok": True, "keeps": True, "error": (\n                f"the frame uploaded but its {fmt} crop did not "',
        "suites": ['test_hosting.py'],
        "why": 'a frame whose 1:1 is on the client store and whose 9:16 is still ours is half-moved, and the half nobody looked at is the half that breaks',
    },
    {
        "name": 'a_hosted_picture_stops_being_ours',
        "file": 'app/hosting.py',
        "find": '    dropped = _drop(tenant, [str(row.url or "")]',
        "replace": '    dropped = 0; _skip = ([str(row.url or "")]  # SABOTAGE',
        "suites": ['test_hosting.py'],
        "why": 'we keep serving a copy the client already hosts, so the blob store goes on growing for ever — the exact thing its own docstring says it is not for',
    },
    {
        "name": 'an_unhosted_approval_is_not_normal',
        "file": 'app/media.py',
        "find": '                if not (asset.hosted or {}).get("url"):\n                    out["unhosted"] += 1',
        "replace": '                pass  # SABOTAGE',
        "suites": ['test_hosting.py'],
        "why": '"kept because somebody approved it" and "kept because no client site would take it" share one number, so a broken CMS connection reads as normal for ever',
    },
    {
        "name": 'a_scope_added_later_reaches_the_console',
        "file": 'app/credentials.py',
        "find": '            for scope in _dark(row, key):',
        "replace": '            for scope in (row.meta or {}).get("missing_scopes") or []:  # SABOTAGE',
        "suites": ['test_hosting.py'],
        "why": 'a scope added to a flow after a client connected is missing on their connection and reported on none of them, so the first anybody hears of it is a failed upload weeks later',
    },
    {
        "name": 'a_store_without_the_scope_is_told_which',

        "file": 'app/shopify_seo.py',
        "find": '    if granted is not None and FILES_SCOPE not in granted:',
        "replace": '    if False:  # SABOTAGE',
        "suites": ['test_hosting.py'],
        "why": 'a store that never granted write_files gets an opaque Shopify access error instead of "re-connect once" — two sentences with entirely different fixes',
    },
    {
        "name": 'an_unrecorded_grant_is_not_an_empty_one',
        "file": 'app/shopify_seo.py',
        "find": '        return credentials.granted_scopes(_tenant(store)).get("shopify")',
        "replace": '        return credentials.granted_scopes(_tenant(store)).get("shopify") or set()  # SABOTAGE',
        "suites": ['test_hosting.py'],
        "why": 'a credential that arrived by env or a pasted key records no scopes, and reading that as "granted nothing" refuses every store that was never connected by OAuth',
    },
    {
        "name": 'a_canva_design_stays_joined_to_its_frame',
        "file": 'app/hosting.py',
        "find": '            got.canva_design_id = design_id',
        "replace": '            got.canva_design_id = ""  # SABOTAGE',
        "suites": ['test_hosting.py'],
        "why": 'the finished design comes back from Canva as a second, unrelated picture, and the frame somebody edited is not the frame they approve',
    },
    {
        "name": 'the_canva_control_is_not_inside_the_label',
        "file": 'app/admin_ui.py',
        "find": '          </label>\n          <div class="framebar">{edit}</div>',
        "replace": '          {edit}</label>\n          <div class="framebar">',
        "suites": ['test_hosting.py'],
        "why": 'a button inside a <label> activates the label too, so clicking "edit in Canva" silently selects the frame as well and the next Reject takes it',
    },
    {
        "name": 'approving_hands_the_picture_over',
        "file": 'app/web.py',
        "find": '        _run_bg("hosting", _hosting.publish_all, tenant)',
        "replace": '        pass  # SABOTAGE',
        "suites": ['test_creative_batch.py'],
        "why": "approved artwork never reaches the client's own site, so we stay its host for ever and the client owns nothing we made for them",
    },
    {
        "name": 'a_frame_run_reports_itself',
        "file": 'app/admin_ui.py',
        "find": '    batch_html = _frames_run(tenant) + batch_html',
        "replace": '    batch_html = batch_html  # SABOTAGE',
        "suites": ['test_creative_batch.py'],
        "why": 'the minutes-long frame run reports nowhere, so a crashed one is indistinguishable from a slow one: the banner promises pictures under Pictures and none ever arrive',
    },
    {
        "name": 'a_set_does_not_repeat_itself',
        "file": 'app/creative.py',
        "find": '            "lever": lv[(i + i // la) % ll],',
        "replace": '            "lever": lv[i % ll],  # SABOTAGE',
        "suites": ['test_creative_batch.py'],
        "why": 'the axes stop carrying, so the walk has period twelve and a set of twenty-four is twelve approaches generated twice — with one angle locked to one lever for ever',
    },
    {
        "name": 'a_generated_product_is_never_substituted',
        "file": 'app/creative.py',
        "find": '    framings = tuple(FRAMINGS) if product_id else tuple(\n        f for f in FRAMINGS if f not in NEEDS_THE_PRODUCT)',
        "replace": '    framings = tuple(FRAMINGS)  # SABOTAGE',
        "suites": ['test_creative_batch.py'],
        "why": 'an account with no product photograph gets product-framed ads anyway, so the thing in the ad is whatever the generator drew — the exact failure Canva produced against Baci\'s own catalogue, and invisible in the output',
    },
    {
        "name": 'a_product_frame_carries_the_real_photograph',
        "file": 'app/creative.py',
        "find": '            if cell["framing"] in NEEDS_THE_PRODUCT:',
        "replace": '            if False:  # SABOTAGE',
        "suites": ['test_creative_batch.py'],
        "why": 'the composite is skipped and the bare plate is filed as a product frame, so an ad that is supposed to show the product shows an empty table',
    },
    {
        "name": 'a_repeat_is_not_a_variation',
        "file": 'app/creative.py',
        "find": '    if put["reused"]:\n        return {"duplicate": True}',
        "replace": '    if False:  # SABOTAGE\n        return {"duplicate": True}',
        "suites": ['test_creative_batch.py'],
        "why": 'two identical frames fold into one row that answers to two cells of the grid, so the set reports variations it does not have',
    },
    {
        "name": 'a_placement_waits_for_approval',
        "file": 'app/creative.py',
        "find": '    if str(row.review or "") != prov.APPROVED:',
        "replace": '    if False:  # SABOTAGE',
        "suites": ['test_creative_batch.py'],
        "why": 'every proposal is cut into three, so twenty-four frames nobody kept become seventy-two stored pictures — the storage the owner closed on 2026-08-29',
    },
    {
        "name": 'a_placement_is_not_a_new_picture',
        "file": 'app/creative.py',
        "find": '    kbmod.set_asset_placements(row.id, cut)',
        "replace": '    [kbmod.add_asset(tenant, u, rights=GENERATED_RIGHTS, kind="image") for u in cut.values()]  # SABOTAGE',
        "suites": ['test_creative_batch.py'],
        "why": 'a 9:16 story crop becomes an asset in its own right, so `pick` can choose it as an email hero and the review queue asks again for a decision that was just made',
    },
    {
        "name": 'a_set_leaves_the_flat_queue',
        "file": 'app/admin_ui.py',
        "find": '    rest = [a for a in waiting if a.id not in in_sets]',
        "replace": '    rest = list(waiting)  # SABOTAGE',
        "suites": ['test_creative_batch.py'],
        "why": 'every frame is drawn twice — once in its set and once loose in the crawler queue — so one decision has two buttons and neither is trusted',
    },
    {
        "name": 'rejecting_the_set_reads_the_set',
        "file": 'app/web.py',
        "find": '    if action == "reject_batch" and batch:\n        ids = [r.id for r in kbm.batch_assets(tenant, batch)]',
        "replace": '    if False:  # SABOTAGE\n        ids = [r.id for r in kbm.batch_assets(tenant, batch)]',
        "suites": ['test_creative_batch.py'],
        "why": 'Reject the set acts on whatever boxes happened to be ticked rather than on the set, so it silently does nothing when none are',
    },
    {
        "name": 'keeping_a_frame_cuts_its_placements',
        "file": 'app/web.py',
        "find": '                    cuts += 1 if _cr.placements(tenant, aid).get("ok") else 0',
        "replace": '                    pass  # SABOTAGE',
        "suites": ['test_creative_batch.py'],
        "why": 'an approved frame never gets its feed and story crops, so the placement work moves to a second screen nobody visits',
    },
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
        # RE-POINTED 2026-08-30: `guidance_also` threads the additive
        # scopes through, so the call gained an argument.
        "find": "        guidance = _sys.guidance_block(tenant, system, also=guidance_also)",
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
        "name": "a_system_says_what_it_is_waiting_on",
        "file": "app/admin_ui.py",
        "find": "  {_awaiting_strip(key, row)}\n  {_work_strip(key, row, counts)}",
        "replace": "  {_work_strip(key, row, counts)}",
        "suites": ["test_workflow_ui.py"],
        "why": "the page you actually work a system on never says that "
               "knowledge it needs is sitting in a review queue — the fact "
               "lives only on the board card you scanned past, so the "
               "decision that would unblock the next draft is invisible at "
               "the moment you could make it",
    },
    {
        "name": "a_missing_declared_part_is_reported",
        "file": "app/skill.py",
        "find": '    for _absent in (coverage.get("promised_but_absent") or []):',
        "replace": "    for _absent in ():  # SABOTAGE",
        "suites": ["test_bundle_contract.py"],
        "why": "a part the package DECLARED and did not supply is written to "
               "the log and nowhere else — which is how `audiences` was read "
               "by every drafter and supplied by nobody for the life of the "
               "codebase. The one signal that catches that class of defect "
               "never reaches the operator",
    },
    {
        "name": "a_thin_run_can_be_opened",
        "file": "app/assurance.py",
        "find": "    rows = [r for r in _rows(tenant, days) if r.thin]",
        "replace": "    rows = []  # SABOTAGE",
        "suites": ["test_assurance_tab.py"],
        "why": "the per-system gap counts become numbers you cannot open — "
               "`catches()` filters on r.caught, so a run that drafted with no "
               "reader and then passed every rule is unreachable from the page "
               "whose whole job is not to be taken on faith",
    },
    {
        "name": "assurance_says_when_selection_can_only_rotate",
        "file": "app/assurance.py",
        "find": '        "rotating": len(flat) > offered,',
        "replace": '        "rotating": False,  # SABOTAGE',
        "suites": ["test_assurance_tab.py"],
        "why": "an account whose proof is all brand-wide and untagged is never "
               "told that selection can only rotate through it — so the "
               "reasonable response to thin copy is to author MORE claims, "
               "which makes the pile bigger and the output no better",
    },
    {
        "name": "the_angle_fallback_ends",
        "file": "app/ledger.py",
        "find": "                        (db.Output.audience_key == audience_key\n                         if since >= _audience_key_since() else",
        "replace": "                        (or_(db.Output.audience_key == audience_key)\n                         if False else  # SABOTAGE",
        "suites": ["test_strategy_ledger.py"],
        "why": "the compatibility read that exists only for rows written "
               "before `audience_key` was passed never ends — a column keeps "
               "meaning two things for ever, and every strategy read silently "
               "matches segments against a field that is supposed to hold a "
               "persona",
    },
    {
        "name": "the_hero_is_named_to_the_drafter",
        "file": "app/skill_pack.py",
        "find": '                parts.append(("- HERO " if e.get("hero") else "- ")',
        "replace": '                parts.append(("- " if e.get("hero") else "- ")  # SABOTAGE',
        "suites": ["test_campaign_variety.py"],
        "why": "the drafter is shown several entities with nothing marking "
               "which one carries the argument, so which one the email is FOR "
               "is left to be inferred from list order — and it reasonably "
               "makes a case for each, which is the mixed positioning the "
               "owner found by reading the sends",
    },
    {
        "name": "the_workroom_says_why_it_cannot_push",
        "file": "app/admin_ui.py",
        "find": '            elif _rung == "auto":',
        "replace": "            elif False:  # SABOTAGE",
        "suites": ["test_workroom_email.py"],
        "why": "the reason a campaign cannot be sent goes back to being "
               "invisible: `auto` queues no approval and nothing consumes "
               "what it emits, so the page falls through to a grey sentence "
               "naming none of it. Re-pointed 2026-08-31, when `shadow` "
               "stopped being the other half of this branch — it queues like "
               "every rung below `auto` now, so `auto` is the only genuine "
               "stop left and this is the only place that says so",
    },
    {
        "name": "a_withdrawn_approval_prints_its_reason",
        "file": "app/admin_ui.py",
        "find": "            elif _withdrawn:",
        "replace": "            elif False:  # SABOTAGE",
        "suites": ["test_workroom_email.py"],
        "why": "`withdrawn_because` is recorded on the approval and shown "
               "nowhere, so an email held for a missing CAN-SPAM address reads "
               "identically to one nobody has approved yet — and the page "
               "advises a redraft, which cannot clear account data",
    },
    {
        "name": "the_ledger_notices_a_defect_being_fixed",
        "file": "app/skill.py",
        "find": '    if autonomy == "auto":\n        return "cleared"',
        "replace": '    if autonomy == "auto":\n        return "cleared" if disposition != "cleared" else "cleared"  # SABOTAGE (this is the FIX)',
        "suites": ["test_open_defects.py"],
        "why": "the open-defect ledger is the one suite that must fail on GOOD "
               "news. It hands the next thread the code facts this thread "
               "found, and a handoff that stays green after the defect is gone "
               "rots exactly the way SYSTEMS-REFERENCE.md did. This mutant "
               "makes a production module BRANCH on \"cleared\", which is the "
               "condition entry 5 measures; if the ledger stays green after "
               "that, it is a document pretending to be a test and every entry "
               "it carries will outlive its defect. Re-pointed 2026-08-31: it "
               "used to apply the kb.py fix, and that defect is now closed.",
    },
    {
        "name": "retrieval_matches_the_conversation",
        "file": "app/grounding.py",
        "find": "    if thread:\n        out += f\"\\n{thread[:THREAD_UTTERANCE_CHARS]}\"",
        "replace": "    if False:  # SABOTAGE\n        out += f\"\\n{thread[:THREAD_UTTERANCE_CHARS]}\"",
        "suites": ["test_grounding.py"],
        "why": "every lookup the mail path makes — situations, objections, "
               "claims, the archive search, the guidance scope — is keyed on "
               "the newest message alone again, so a five-message negotiation "
               "retrieves against its last short reply and the reply is "
               "grounded in the wrong half of the conversation",
    },
    {
        "name": "the_archive_passage_reaches_the_prompt",
        "file": "app/grounding.py",
        "find": '            if h.get("excerpt"):',
        "replace": "            if False:  # SABOTAGE",
        "suites": ["test_grounding.py"],
        "why": "the mail path shows a subject line where it has the matched "
               "passage in hand — `archive._passage` exists for no other "
               "purpose, and the other drafter in this codebase renders it. "
               "The path that answers real customers gets the least of it",
    },
    {
        "name": "the_newest_message_is_not_its_own_context",
        "file": "app/gmail_client.py",
        "find": "    msgs = [m for m in thread.get(\"messages\", [])\n            if not exclude_id or m.get(\"id\") != exclude_id]",
        "replace": '    msgs = list(thread.get("messages", []))  # SABOTAGE',
        "suites": ["test_grounding.py"],
        "why": "every threaded prompt carries the message being acted on "
               "twice — once under 'NEWEST MESSAGE (the one to act on)' and "
               "again at the end of the thread history — which spends context "
               "and reads as emphasis the sender never gave it",
    },
    {
        "name": "owner_input_has_one_definition",
        "file": "app/skill.py",
        "find": "OWNER_INPUT = _pkg.OWNER_INPUT",
        "replace": 'OWNER_INPUT = ("offer", "deadline")  # SABOTAGE',
        "suites": ["test_skill_conformance.py"],
        "why": "the tuple is restated instead of derived, so the two copies "
               "drift the moment a third owner input is added — one side hops "
               "it onto the bundle and the other does not declare it as a "
               "package part, which is exactly how `revision_notes` ended up "
               "with a declared supplier that never wrote it",
    },
    {
        "name": "the_owner_input_hop_carries_them_all",
        "file": "app/bundle.py",
        "find": 'OWNER_INPUT = ("offer", "deadline", "revision_notes")',
        "replace": 'OWNER_INPUT = ("offer", "deadline")  # SABOTAGE',
        # test_funnel is what actually detects it — it asserts the digest on
        # the bundle the drafter receives. The conformance suite only checks
        # that each member is a declared PART, which stays true when a member
        # is removed. Naming the wrong suite is how an entry reports MISSED
        # while the mutant is genuinely caught elsewhere.
        "suites": ["test_funnel.py"],
        "why": "`revision_notes` falls out of the one route again, so the "
               "redraft digest reaches no drafter unless each one grows its "
               "own private hop back — three of them had, which is the "
               "duplication the single route was built to end",
    },
    {
        "name": "an_article_is_checked_for_coherence",
        "file": "app/skill_pack.py",
        "find": "             commitment=_about,",
        "replace": "             # SABOTAGE",
        "suites": ["test_skill_conformance.py"],
        "why": "articles run ZERO coherence rules — `Context.emit` runs that "
               "axis only when a commitment is passed, so an article whose "
               "hero photograph and prose are about different things reports "
               "clean. Built, wired to five of six emit sites, skipped on the "
               "sixth, and nothing said so",
    },
    {
        "name": "a_new_skill_cannot_ship_half_wired",
        "file": "scripts/test_skill_conformance.py",
        # ANCHORED ON THE SELF-CHECK, not on the per-skill assertion: neutering
        # that assertion is invisible by construction (a disabled check passes
        # exactly like a working one), which the harness reported as MISSED.
        # The walk proving it can SEE a violation is the thing worth guarding.
        "find": '            if any(kw.arg == "commitment" for kw in x.keywords):\n                _w += 1',
        "replace": '            if True:  # SABOTAGE\n                _w += 1',
        "suites": ["test_skill_conformance.py"],
        "why": "the conformance walk stops measuring the one obligation it "
               "exists for, so the next skill can build a commitment, never "
               "hand it to the gate, and ship — which is precisely how "
               "blog_article shipped and stayed shipped",
    },
    {
        "name": "thin_knowledge_does_not_block_promotion",
        "file": "app/systems.py",
        "find": '    if not r["can_produce"]:\n        return {"can": False, "target": target,\n                "why": "cannot produce at all: " + "; ".join(r["impossible"])}',
        "replace": '    if not r["ready"]:  # SABOTAGE\n        return {"can": False, "target": target,\n                "why": "not ready: " + "; ".join(r["blockers"])}',
        "suites": ["test_systems.py"],
        "why": "a system whose connections are wired and which is producing "
               "perfectly well cannot leave the learning phase until every "
               "kb_need is filled — a block on the strength of absent data, "
               "which this platform does not do. It is backwards on safety "
               "too: the next rung up is where a person taps EVERY output, so "
               "holding a system down means the thin drafts are never read",
    },
    {
        "name": "a_typed_note_is_filed_before_it_is_used",
        "file": "app/skill_pack.py",
        "find": "    if (note or \"\").strip():\n        with db.SessionLocal() as s:\n            s.add(db.FeedbackItem(",
        "replace": "    if False:  # SABOTAGE\n        with db.SessionLocal() as s:\n            s.add(db.FeedbackItem(",
        "suites": ["test_campaign_variety.py"],
        "why": "the judgement typed at Request changes is never stored — it "
               "never reaches the thread, cannot be reinforced, and is "
               "DESTROYED on every refused click, which is exactly what "
               "happened to the owner's notes during the redraft outage. It "
               "also makes the flash lie: a note-only redraft reports '0 "
               "feedback item(s) consumed' while having consumed one",
    },
    {
        "name": "a_redraft_carries_the_reader",
        "file": "app/skill_pack.py",
        "find": '            "audience_key": (overrides.get("audience_key")',
        "replace": '            "audience_key": ("" if True else overrides.get("audience_key")',
        "suites": ["test_campaign_variety.py"],
        "why": "Request changes stops redrafting on every account that has a "
               "persona — `campaign_email` requires a reader and this caller "
               "rebuilds the call without one, so the click is refused before "
               "the bundle resolves, the owner's notes never reach the "
               "drafter, and the feedback stays open with the page unchanged",
    },
    {
        "name": "a_refused_redraft_names_its_cause",
        "file": "app/skill_pack.py",
        "find": '                         + (("; ".join(r.get("blocked_on") or [])',
        "replace": '                         + (("" and "".join(r.get("blocked_on") or [])  # SABOTAGE',
        "suites": ["test_campaign_variety.py"],
        "why": "a refused redraft reports the bare word 'blocked' and throws "
               "away `blocked_on`, the one field naming which parameter or "
               "rule stopped it — a dead end for whoever has to fix it, and "
               "the reason this class of bug took a manual test to find",
    },
    {
        "name": "one_to_many_work_names_its_reader",
        "file": "app/skill.py",
        "find": "    if sk.requires:",
        "replace": "    if False:  # SABOTAGE",
        "suites": ["test_funnel.py"],
        "why": "a campaign or an ad runs without naming who it is written "
               "for, from every door except the plan form — the agent tool, "
               "the HTTP route, the worker tick and the workroom redraft all "
               "reach run() and the one gate that knew a reader was required "
               "covered none of them",
    },
    {
        "name": "a_reader_is_only_required_when_one_exists",
        "file": "app/skill_pack.py",
        "find": "        return bool(_k.audiences(tenant))",
        "replace": "        return True  # SABOTAGE",
        "suites": ["test_funnel.py"],
        "why": "an account that has authored no persona yet is REFUSED "
               "instead of running thinly — work stops on the strength of an "
               "absence, which is the one thing this layer does not do, and a "
               "new client can produce nothing until somebody writes a "
               "persona down",
    },
    {
        "name": "a_planner_proposes_complete_work",
        "file": "app/planner.py",
        "find": '                          "audience_key": _reader_for(sysrow, seg["key"])},',
        "replace": '                          "audience_key": ""},  # SABOTAGE',
        "suites": ["test_workflow_ui.py"],
        "why": "every proposed campaign arrives missing its reader, so the "
               "queue fills with work that cannot run until a human opens each "
               "one — a planner that files incomplete work is a nag, which is "
               "the whole thing proposing exists to remove",
    },
    {
        "name": "a_named_persona_is_one_that_exists",
        "file": "app/systems.py",
        "find": '              "audience": _audience_key_check,',
        "replace": "              # SABOTAGE\n              \"_x\": None,",
        "suites": ["test_plans.py", "test_workflow_ui.py"],
        "why": "a plan may name a persona this account has never approved — "
               "free text where every other reference field is checked — and "
               "the run then drafts for nobody while every gate reports clean",
    },
    {
        "name": "one_reader_never_a_blend",
        "file": "app/funnel.py",
        "find": "    _aud = [audience] if audience else []",
        "replace": ("    from . import kb as _kbz  # SABOTAGE\n"
                    "    _aud = _kbz.audiences(tenant)"),
        "suites": ["test_funnel.py"],
        "why": "every drafter is briefed with EVERY persona at once — on Baci "
               "that the reader wants a gift that feels chosen, already owns "
               "plenty, AND wants the look cheaply. Three real buyers merged "
               "into one contradictory instruction, which is not a fuller "
               "brief but an incoherent one",
    },
    {
        "name": "work_says_when_it_has_no_reader",
        "file": "app/skill_pack.py",
        "find": '    if ctx.bundle.get("audience"):\n        return',
        "replace": '    if True:  # SABOTAGE\n        return',
        "suites": ["test_assurance_tab.py", "test_funnel.py"],
        "why": "a campaign or article written for nobody in particular says so "
               "nowhere — not in the run notes and not on Assurance — so the "
               "one decision that would fix it (name the reader on the plan) "
               "is invisible, and generic copy reads as intentional",
    },
    {
        "name": "objections_reach_work_that_asks_no_question",
        "file": "app/resolve.py",
        "find": "    if tier >= 2 and not objections and not utterance:",
        "replace": "    if False:  # SABOTAGE",
        "suites": ["test_funnel.py"],
        "why": "every campaign, article and ad drafts with NO objections — and "
               "worse, says so: an empty list defeats the funnel's fallback, so "
               "the run reports 'no approved objections are on file' on an "
               "account with eight, and the Assurance tab repeats it as "
               "`funnel:objection`, sending the owner to author knowledge they "
               "already have",
    },
    {
        "name": "assurance_says_which_system_ran_blind",
        "file": "app/assurance.py",
        "find": ('        if r.thin:\n'
                 '            e["thin_runs"] += 1'),
        "replace": ('        if False:  # SABOTAGE\n'
                    '            e["thin_runs"] += 1'),
        "suites": ["test_assurance_tab.py"],
        "why": "the page whose whole job is to be believed can say something "
               "was missing and never WHICH SYSTEM was drafting without it — a "
               "campaign writing with no objections and an article writing with "
               "all of them collapse into one account-wide number, which is the "
               "blind spot every silent-supply defect in this codebase has "
               "lived in",
    },
    {
        "name": "claims_rotate_so_every_one_is_reachable",
        "file": "app/kb.py",
        "find": "            out.sort(key=lambda r: last.get(r.id, never))",
        "replace": "            pass  # SABOTAGE",
        "suites": ["test_claim_rotation.py"],
        "why": "a campaign, an article and an ad have no question to rank on, "
               "so every ranking key ties and a stable sort falls back to "
               "insertion order — the SIX OLDEST claims are offered for ever "
               "and the seventh an account authors can never be reached. "
               "Adding good proof stops changing anything and nothing says so",
    },
    {
        "name": "the_receipt_says_what_cannot_be_narrowed",
        "file": "app/resolve.py",
        "find": "    if _claims_flat and _offered_n and _claims_flat > _offered_n:",
        "replace": "    if False:  # SABOTAGE",
        "suites": ["test_claim_rotation.py"],
        "why": "an account whose proof is all brand-wide and untagged is "
               "never told — selection can only rotate, every draft competes "
               "with the same undifferentiated pile, and the owner's "
               "reasonable response is to author MORE claims, which makes it "
               "worse",
    },
    {
        "name": "a_campaign_send_is_measured",
        "file": "app/skill_pack.py",
        "find": "            _edits.record_run(run_id, _was, _now)",
        "replace": "            pass  # SABOTAGE",
        "suites": ["test_campaign_measured.py"],
        "why": "the Measured section for campaigns goes back to being "
               "structurally empty — the system declares that it moves the "
               "share of sends nobody had to touch, and nothing anywhere "
               "records whether a person touched one",
    },
    {
        "name": "the_edit_sample_is_readable",
        "file": "app/skill_pack.py",
        "find": ('            _was, _now = (_ct.plain_text(art.draft_body or ""),\n'
                 '                          _ct.plain_text(art.body or ""))'),
        "replace": '            _was, _now = (art.draft_body or ""), (art.body or "")  # SABOTAGE',
        "suites": ["test_campaign_measured.py"],
        "why": "the Measured list shows a doctype and a wall of table tags "
               "instead of the sentence somebody changed — `edits.delta` is a "
               "line diff and an email body is one long line of HTML, so the "
               "number is right and the evidence beside it is unreadable",
    },
    {
        "name": "mail_is_grounded_as_the_system_that_owns_it",
        "file": "app/grounding.py",
        "find": "        system = _rep.route(bucket)",
        "replace": "        system = SYSTEM_KEY  # SABOTAGE",
        "suites": ["test_grounding.py"],
        "why": "every reply is grounded under `inbox_triage`, which is not a "
               "key in systems.CATALOG at all — so standing guidance typed on "
               "the Lead responder or Service desk page looks up a system "
               "that does not exist and reaches nothing. The owner corrects "
               "the two systems that answer real customer mail every morning "
               "and the correction never arrives",
    },
    {
        "name": "guidance_scopes_are_additive",
        "file": "app/systems.py",
        "find": ('        for extra in also:\n'
                 '            if extra and extra != key:\n'
                 '                out += feedback_block(tenant, extra) + edit_lessons(tenant, extra)'),
        "replace": "        pass  # SABOTAGE",
        "suites": ["test_grounding.py"],
        "why": "scoping a reply to the system that owns it silently DROPS the "
               "general inbox thread — guidance typed on the Inbox triage "
               "page, which has its own board page, stops reaching any routed "
               "mail. One dropped instruction traded for another",
    },
    {
        "name": "an_unapproved_offer_never_ships",
        "file": "app/skill_pack.py",
        "find": ('    if derived_offer and ad_craft.offer_position(\n'
                 '            to_check, derived_offer["offer"]) >= 0:'),
        "replace": ('    if False and ad_craft.offer_position(  # SABOTAGE\n'
                    '            to_check, derived_offer["offer"]) >= 0:'),
        "suites": ["test_offers.py"],
        "why": "a discount NOBODY APPROVED — derived from an old send and "
               "never signed off — is drafted into the client's ESP and is "
               "one click from their whole list, over their own sending "
               "domain. The single most expensive mistake this layer can make",
    },
    {
        "name": "an_offer_is_held_only_when_the_copy_states_it",
        "file": "app/skill_pack.py",
        "find": ('    if derived_offer and ad_craft.offer_position(\n'
                 '            to_check, derived_offer["offer"]) >= 0:'),
        "replace": "    if derived_offer:  # SABOTAGE",
        "suites": ["test_offers.py"],
        "why": "every send is held over an offer it never mentions — the "
               "block is read from the parameter instead of from the words, "
               "so a story email that was handed a proposal it chose not to "
               "use cannot be published either",
    },
    {
        "name": "a_harvested_offer_is_only_proposed",
        "file": "app/offers.py",
        "find": '                origin="harvest", review=prov.PROPOSED)',
        "replace": '                origin="harvest", review=prov.APPROVED)  # SABOTAGE',
        "suites": ["test_offers.py"],
        "why": "the bootstrap APPROVES what it read out of the archive, so a "
               "promotion that ran once two years ago becomes a live offer "
               "every future send may state — a machine authoring its own "
               "permission, which is the whole thing the review queue exists "
               "to prevent",
    },
    {
        "name": "a_proposed_entity_can_be_decided",
        "file": "app/kb.py",
        "find": ('        if approve:\n'
                 '            row.review, row.status = prov.APPROVED, "active"\n'
                 '            row.approved_by, row.approved_at = by, db.utcnow()\n'
                 '            # Approving IS the act of saying this is still what we sell, which'),
        "replace": ('        if False:  # SABOTAGE\n'
                    '            row.review, row.status = prov.APPROVED, "active"\n'
                    '            row.approved_by, row.approved_at = by, db.utcnow()\n'
                    '            # Approving IS the act of saying this is still what we sell, which'),
        "suites": ["test_offers.py"],
        "why": "a proposed entity cannot be approved by anything, so the "
               "queue the systems board points at with a `decide` link can be "
               "filled and never drained — and an email held over an "
               "unapproved offer stays held for ever",
    },
    {
        "name": "the_package_is_checked_against_its_promise",
        "file": "app/bundle.py",
        "find": "    return [k for k in promised(tier) if k not in b]",
        "replace": "    return []  # SABOTAGE",
        "suites": ["test_bundle_contract.py"],
        "why": "the one check that compares a built package against what it "
               "declared goes quiet — a part that stops being supplied is "
               "carried as None into every drafter, exactly as `audiences` "
               "was for the life of the codebase, and nothing notices again",
    },
    {
        "name": "a_consumer_cannot_read_an_undeclared_part",
        "file": "app/bundle.py",
        "find": "    undeclared = {k: sorted(v) for k, v in seen.items() if k not in PARTS}",
        "replace": "    undeclared = {}  # SABOTAGE",
        "suites": ["test_bundle_contract.py"],
        "why": "a generator may read a part of the brand package that nothing "
               "promises to supply, and the contract will report it clean — "
               "which is how a read with no writer reaches production",
    },
    {
        "name": "the_buyers_own_words_reach_the_drafter",
        "file": "app/resolve.py",
        "find": '    bundle["audiences"] = ([',
        "replace": '    bundle["audiences"] = []; _unused = ([  # SABOTAGE',
        "suites": ["test_funnel.py"],
        "why": "no drafter is ever given the audience — the ad, the email and "
               "the article all write in the brand's words because the "
               "buyer's pains, vocabulary and buying triggers never reach "
               "them. It fails SILENTLY: `inputs_for` has no fallback fetch "
               "for audiences, so the value is None and nothing reports a gap",
    },
    {
        "name": "owner_input_reaches_the_bundle",
        "file": "app/skill.py",
        "find": ('        if _k in sk.params and str(params.get(_k) or "").strip():\n'
                 '            bundle[_k] = str(params[_k]).strip()'),
        "replace": ('        if False:  # SABOTAGE\n'
                    '            bundle[_k] = str(params[_k]).strip()'),
        "suites": ["test_funnel.py"],
        "why": "the offer and the deadline a PERSON typed never reach the "
               "drafter, which is the whole reason they are fields rather "
               "than things a model decides — so the copy is written with no "
               "offer in it, or the drafter is left free to invent one",
    },
    {
        "name": "a_lost_draft_files_its_gap",
        "file": "app/skill.py",
        "find": '                        [{"basis": "unknown", "key": entity_key,',
        "replace": '                        [{"key": entity_key,  # SABOTAGE',
        "suites": ["test_skill.py"],
        "why": "a draft blocked by missing knowledge names the gap on screen "
               "and files NOTHING — `record_unknowns` filters on `basis`, so "
               "the call returns cleanly having written no row, for every "
               "skill. The backlog that is supposed to collect what cost an "
               "output stays permanently empty and nobody is ever asked to "
               "close the gap",
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
        # RE-POINTED 2026-08-31: the two-column read gained an end condition
        # (`_AUDIENCE_KEY_MARKER`), so the `or_` moved inside a conditional.
        # What this guard covers is unchanged — a window that SPANS the
        # boundary must still read both columns.
        "find": "                         or_(db.Output.audience_key == audience_key,\n                             db.Output.angle == audience_key)),",
        "replace": "                         db.Output.audience_key == audience_key),  # SABOTAGE",
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
        "suites": ["test_funnel.py"],
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
        "suites": ["test_funnel.py"],
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
        "suites": ["test_seo_head.py"],
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
        "name": 'a_generated_image_is_only_proposed',
        "file": 'app/creative.py',
        "find": 'GENERATED_ORIGIN = "generated"',
        "replace": 'GENERATED_ORIGIN = "human"  # SABOTAGE',
        "suites": ['test_creative_seam.py'],
        "why": 'a picture the model made lands approved and immediately selectable, so the model authors its own evidence — and a generated photograph of a product asserts more than a sentence about it does',
    },
    {
        "name": 'the_capability_report_needs_the_key',
        "file": 'app/web.py',
        "find": '            "skills": _skill_count()}',
        "replace": '            "skills": _skill_count(),\n            "capabilities": _capability_report()}  # SABOTAGE',
        "suites": ['test_console_auth.py'],
        "why": 'the infrastructure report moves to the unauthenticated half, so a landing page that promises each client sees only their own workspace starts naming what the service is wired to',
    },
    {
        "name": 'the_capability_report_leaks_nothing',
        "file": 'app/web.py',
        "find": '        "anthropic": bool(config.ANTHROPIC_API_KEY),\n        "openai": bool(config.OPENAI_API_KEY),',
        "replace": '        "anthropic": config.ANTHROPIC_API_KEY,\n        "openai": config.OPENAI_API_KEY,  # SABOTAGE',
        "suites": ['test_console_auth.py'],
        "why": "the health report returns the API keys themselves rather than whether they are set — a credential leak wearing a diagnostic's clothes, on the endpoint most likely to be pasted into a ticket",
    },
    {
        "name": 'the_reviewers_model_is_chosen',
        "file": 'app/llm.py',
        "find": '    "creative_review": "CREATIVE_REVIEW_MODEL",',
        "replace": '    # SABOTAGE',
        "suites": ['test_creative_seam.py'],
        "why": "the picture reviewer's model goes back to being whatever CLAUDE_MODEL happens to be — a choice nobody made, that nobody can see, and that cannot be changed without a deploy",
    },
    {
        "name": 'a_topic_piece_refuses_a_product_shot',
        "file": 'app/creative.py',
        "find": '        # AND NOTHING ELSE. The brand-wide rung does not exist on this side of\n        # the ladder: brand-wide, for an account that sells things, means a\n        # product shot.',
        "replace": '        for r in heroes:\n            if not (r.entity_key or ""):\n                return _out(r, "brand_wide", "SABOTAGE")',
        "suites": ['test_creative_seam.py'],
        "why": 'an article about knee pain takes a photograph of a bottle the moment nothing better exists — which is exactly when it matters. Ranking a product shot last is not the same as excluding it',
    },
    {
        "name": 'a_real_photograph_beats_a_generated_one',
        "file": 'app/creative.py',
        "find": '        for r in heroes:\n            if (r.entity_key or "") == ent and ent:\n                return _out(r, "photograph",',
        "replace": '        for r in []:\n            if (r.entity_key or "") == ent and ent:\n                return _out(r, "photograph",  # SABOTAGE',
        "suites": ['test_creative_seam.py'],
        "why": 'a product-led piece stops preferring the real photograph of the product, so it falls to a brand-wide shot or to generation — and misrepresenting a product is the most expensive error available here',
    },
    {
        "name": 'the_ladder_does_not_generate',
        "file": 'app/skill_pack.py',
        "find": '    _hero_id = str(_hero.get("asset_id") or "")',
        "replace": '    _hero_id = str((creative.generate(ctx.tenant) or {}).get("asset_id") or "")  # SABOTAGE',
        "suites": ['test_creative_seam.py', 'test_funnel.py'],
        "why": 'the drafting run generates inline — three minutes and about two thousand text calls of latency, to produce an image that lands `proposed` and therefore cannot be attached to the draft that waited for it',
    },
    {
        "name": 'the_picture_is_about_what_the_piece_is_about',
        "file": 'app/creative.py',
        "find": '    subject = _subject_of(commitment, situation,',
        "replace": '    subject = _subject_of(None, situation,  # SABOTAGE',
        "suites": ['test_creative_seam.py'],
        "why": 'the image brief falls back to reading the catalogue, so an email about knee pain gets a photograph of a bottle — on-brand and about nothing the reader opened it for, which is the whole complaint',
    },
    {
        "name": 'the_image_prompt_comes_from_the_account',
        "file": 'app/creative.py',
        "find": '        parts.append(f"It must be consistent with this, which the copy says: "',
        "replace": '        pass; _ = (f"It must be consistent with this, which the copy says: "  # SABOTAGE',
        "suites": ['test_creative_seam.py'],
        "why": 'the frame stops being constrained by what the copy beside it may say, so a photograph can argue something the claim layer would have refused in words',
    },
    {
        "name": 'an_ad_frame_is_judged_as_an_ad',
        "file": 'app/creative.py',
        "find": '        extra=("on_subject", "audience_fit", "stops_the_scroll",\n               "lands_the_positioning")),',
        "replace": '        extra=("on_subject",)),  # SABOTAGE',
        "suites": ['test_creative_seam.py'],
        "why": 'an ad frame is reviewed as though it were an article illustration — nobody asks whether it stops a thumb or argues the positioning, which are the two things an ad lives or dies by',
    },
    {
        "name": 'a_review_that_did_not_run_is_not_a_pass',
        "file": 'app/creative.py',
        "find": '        return {"ok": False, "why": getattr(reply, "degraded", "")',
        "replace": '        return {"ok": True, "why": getattr(reply, "degraded", "")  # SABOTAGE',
        "suites": ['test_creative_seam.py'],
        "why": 'a review that could not run reports success, so an unreviewed picture is indistinguishable from one that passed — silence reading as approval is the one thing this must never mean',
    },
    {
        "name": 'a_repair_is_kept_only_if_better',
        "file": 'app/creative.py',
        "find": '            if v2.get("ok") and len(v2.get("failed") or []) < len(verdict["failed"]):',
        "replace": '            if v2.get("ok"):  # SABOTAGE',
        "suites": ['test_creative_seam.py'],
        "why": 'the second attempt replaces the first for being second, so a repair that fails differently is treated as progress and the loop makes things worse quietly',
    },
    {
        "name": 'a_failing_picture_is_still_filed',
        "file": 'app/creative.py',
        "find": '        return {"ok": False, "error": put["error"], "thin": brief["thin"]}',
        "replace": '        return {"ok": False, "error": put["error"], "thin": brief["thin"]}\n    if verdict.get("failed"):\n        return {"ok": False, "error": "rejected"}  # SABOTAGE',
        "suites": ['test_creative_seam.py'],
        "why": 'the reviewer becomes a GATE, which `imagegen.similarity` already refused to be for the same reason: a false refusal costs a person doing by hand the thing this was built to do',
    },
    {
        "name": 'one_image_is_one_row',
        "file": 'app/media.py',
        "find": '        row = (s.query(db.MediaBlob)\n               .filter(db.MediaBlob.tenant == tenant,\n                       db.MediaBlob.sha == sha).first())',
        "replace": '        row = None  # SABOTAGE',
        "suites": ['test_creative_seam.py'],
        "why": 'the same image stored twice becomes two assets, so every question about which creative worked counts one picture as two and the answer is wrong in a way nobody can see',
    },
    {
        "name": 'media_serves_only_images',
        "file": 'app/media.py',
        "find": '    if mime not in MIME:',
        "replace": '    if False:  # SABOTAGE',
        "suites": ['test_creative_seam.py'],
        "why": 'a public unauthenticated route will serve whatever it was handed under whatever content type came with it',
    },
    {
        "name": 'a_sweep_keeps_what_is_in_use',
        "file": 'app/media.py',
        "find": '            if review == prov.APPROVED:\n                out["kept_approved"] += 1',
        "replace": '            if False:  # SABOTAGE\n                out["kept_approved"] += 1',
        "suites": ['test_creative_seam.py'],
        "why": 'the nightly cleanup deletes the bytes behind APPROVED pictures, so an image somebody signed off becomes a broken link in the next email or article that uses it',
    },
    {
        "name": 'an_unapproved_picture_is_not_kept',
        "file": 'app/media.py',
        "find": '            if made and made < stale:\n                s.delete(row)\n                asset.status = "retired"',
        "replace": '            if False:  # SABOTAGE\n                s.delete(row)\n                asset.status = "retired"',
        "suites": ['test_creative_seam.py'],
        "why": 'pictures nobody ever opened are stored for ever, so a generator left running fills the database with images that were never wanted — the owner asked for exactly the opposite',
    },
    {
        "name": 'expiring_a_picture_retires_its_row',
        "file": 'app/media.py',
        "find": '                s.delete(row)\n                asset.status = "retired"\n                out["expired_unreviewed"] += 1',
        "replace": '                s.delete(row)\n                out["expired_unreviewed"] += 1  # SABOTAGE',
        "suites": ['test_creative_seam.py'],
        "why": 'the bytes go and the asset stays, so the review queue fills with pictures that 404 when opened — which teaches people the queue is broken, and is worse than losing the picture',
    },
    {
        "name": 'a_system_shows_what_it_waits_on',
        "file": 'app/admin_ui.py',
        "find": '      {_awaiting_strip(key, row)}',
        "replace": '      <!-- SABOTAGE -->',
        "suites": ['test_approval_gate.py'],
        "why": 'the count of claims a system is waiting on goes back to living only inside a refusal string, where it is text nobody can act on — so proposals sit in a queue while the system that needs them looks merely thin',
    },
    {
        "name": 'the_ban_list_cannot_be_overridden',
        "file": 'app/skill.py',
        "find": '        hard = [a for a in absent\n                if not (_sysm.NEEDS.get(a.split(" (")[0].strip(), {})\n                        .get("overridable", True))]',
        "replace": '        hard = []  # SABOTAGE',
        "suites": ['test_approval_gate.py'],
        "why": 'a reason typed into a box waives the ban list, so the validator has nothing to refuse against and the draft goes out unchecked — that is not proceeding with less, it is proceeding with no check',
    },
    {
        "name": 'an_override_needs_a_reason',
        "file": 'app/skill.py',
        "find": '    override = str(params.pop("override_needs", "") or "").strip()',
        "replace": '    override = str(params.pop("override_needs", "") or "") or "x"  # SABOTAGE',
        "suites": ['test_approval_gate.py'],
        "why": 'an empty override waives the gate, so a stray parameter turns the check off and nobody can be asked later why it was waived',
    },
    {
        "name": 'an_override_is_on_the_record',
        "file": 'app/skill.py',
        "find": '            thin.append(f"OVERRIDDEN: ran without {\', \'.join(absent)} — "\n                        f"{override}")',
        "replace": '            pass  # SABOTAGE',
        "suites": ['test_approval_gate.py'],
        "why": "a draft produced under a waiver is indistinguishable from one produced under the gate — the assurance ledger reads `thin` as 'what this run was working without', and it would say nothing",
    },
    {
        "name": 'one_writer_counts_the_queue',
        "file": 'app/kb.py',
        "find": '    waiting = pending_counts(tenant)',
        "replace": '    waiting = {}  # SABOTAGE',
        "suites": ['test_approval_gate.py'],
        "why": "`needs_met` stops distinguishing 'nobody has told us yet' from 'somebody has and it is in a queue', so a refusal sends the owner to fill in data that is already written and waiting on them",
    },
    {
        "name": 'an_unmeasured_ad_is_not_a_zero',
        "file": 'app/results.py',
        "find": '                if not has:\n                    continue',
        "replace": '                if False:  # SABOTAGE\n                    continue',
        "suites": ['test_results.py'],
        "why": 'an idea nobody has run yet is averaged in at zero, so every new positioning looks like a failed one and the scoreboard argues against trying anything',
    },
    {
        "name": 'the_result_lands_on_what_produced_it',
        "file": 'app/results.py',
        "find": '    if dim == "funnel_stage":\n        return [row.funnel_stage] if row.funnel_stage else []',
        "replace": '    if dim == "funnel_stage":\n        return []  # SABOTAGE',
        "suites": ['test_results.py'],
        "why": 'results can no longer be grouped by where in the journey the work was aimed, so nobody can ask whether the consideration-stage work pays — the question that decides where next month goes',
    },
    {
        "name": 'the_tab_and_the_report_share_one_writer',
        "file": 'app/admin_ui.py',
        "find": '    from . import results as _res\n    board = _res.scoreboard(tenant)',
        "replace": '    from . import results as _res\n    board = {}  # SABOTAGE',
        "suites": ['test_results.py'],
        "why": 'the Plan tab stops reading the same function the report will, so the console and the weekly number drift into disagreeing about one figure — which this codebase has already paid for twice',
    },
    {
        "name": 'the_ad_client_cannot_spend_money',
        "file": 'app/meta_ads.py',
        "find": '    import httpx\n    try:\n        r = httpx.get(f"{BASE}/{path}", timeout=TIMEOUT,',
        "replace": '    import httpx\n    try:\n        r = httpx.post(f"{BASE}/{path}", timeout=TIMEOUT,  # SABOTAGE',
        "suites": ['test_results.py'],
        "why": "the read-only client gains a write path, so a later edit can create ads — spending the client's budget on copy nobody approved in the one place it matters",
    },
    {
        "name": 'a_batch_records_what_it_tested',
        "file": 'app/skill_pack.py',
        "find": '            positioning=positioning, funnel_stage=stage,\n            commitment=_commit,',
        "replace": '            funnel_stage=stage,\n            commitment=_commit,  # SABOTAGE',
        "suites": ['test_funnel.py'],
        "why": "the hypothesis a batch was testing is stated in the brief and recorded nowhere, so 'which positioning did better' has to be reconstructed from memory — which means it never gets asked",
    },
    {
        "name": 'an_untested_batch_says_so',
        "file": 'app/skill_pack.py',
        "find": '            ctx.note("this batch tests no stated positioning — pass "',
        "replace": '            pass; _ = ("this batch tests no stated positioning — pass "  # SABOTAGE',
        "suites": ['test_funnel.py'],
        "why": 'a batch of five variants that argue five different things looks identical to a test of one idea, and nothing on the run says which it was',
    },
    {
        "name": 'a_positioning_is_derived_never_invented',
        "file": 'app/funnel.py',
        "find": '        for obj, clm in zip(objections[:3], proved[:3]):',
        "replace": '        for obj, clm in zip(objections[:3] or [None], proved[:3] or [None]):  # SABOTAGE',
        "suites": ['test_funnel.py'],
        "why": 'proposals are offered for accounts holding neither the claim nor the objection they claim to pair, so the suggester invents positioning out of nothing — the one thing it exists not to do',
    },
    {
        "name": 'a_thin_proposal_list_says_what_is_missing',
        "file": 'app/funnel.py',
        "find": '    if not objections:\n        gaps.append("no objections on file',
        "replace": '    if False:\n        gaps.append("no objections on file',
        "suites": ['test_funnel.py'],
        "why": "a weak or empty proposal list reads as 'nothing worth testing' rather than as 'this account has no objections on file', so the owner fixes the wrong thing or nothing",
    },
    {
        "name": 'the_ad_brief_is_built_without_a_knob',
        "file": 'app/skill_pack.py',
        "find": '    chose = bool(stage)',
        "replace": '    chose = bool(stage)\n    plan = {}\n    if not stage:\n        return ctx.done()  # SABOTAGE',
        "suites": ['test_funnel.py'],
        "why": 'the default ad run — the one that actually happens — goes back to reading none of the data layer: no situations, no objections as strategy, no audience vocabulary, no search phrases. The draft still passes every gate, because the gates ask whether it is false, not whether it used what we know',
    },
    {
        "name": 'an_inference_does_not_narrow_the_angles',
        "file": 'app/skill_pack.py',
        "find": '    if chose:\n        angles = funnel.angles_for_stage(stage, angles)',
        "replace": '    if True:\n        angles = funnel.angles_for_stage(stage, angles)  # SABOTAGE',
        "suites": ['test_funnel.py'],
        "why": 'a stage nobody chose silently narrows the angle set, so every existing ad batch changes shape on the strength of an inference — a derived stage may brief, it may not bind',
    },
    {
        "name": 'the_buyers_own_words_reach_the_drafter',
        "file": 'app/funnel.py',
        "find": '    if vocab:\n        have["audience_vocabulary"] = vocab',
        "replace": '    if False:  # SABOTAGE\n        have["audience_vocabulary"] = vocab',
        "suites": ['test_funnel.py'],
        "why": "the vocabulary researched for each audience — the words that buyer actually uses — is on the row and reaches nothing, so every generator writes in the brand's words instead of the buyer's",
    },
    {
        "name": 'search_phrases_are_scoped_to_the_reader',
        "file": 'app/funnel.py',
        "find": '        if fitted:\n            have["keyword_stage_fit"] = fitted',
        "replace": '        if False:  # SABOTAGE\n            have["keyword_stage_fit"] = fitted',
        "suites": ['test_funnel.py'],
        "why": "every phrase goes to every stage, so a bottom-of-funnel ad is shown 'what is melamine' beside 'buy melamine plates' and has no way to tell which reader it is for",
    },
    {
        "name": 'an_article_carries_its_picture',
        "file": 'app/shopify_seo.py',
        "find": '    if img := _article_image(fields):\n        art["image"] = img\n    mfs = _seo_metafields(fields)\n    if mfs:\n        art["metafields"] = mfs\n    res = _send(store, "POST", f"blogs/{blog_id}/articles.json",',
        "replace": '    mfs = _seo_metafields(fields)\n    if mfs:\n        art["metafields"] = mfs  # SABOTAGE\n    res = _send(store, "POST", f"blogs/{blog_id}/articles.json",',
        "suites": ['test_article_image.py'],
        "why": 'every article publishes with no featured image, so it looks broken on the blog index and in every share card next to the posts that have one — which is exactly what the owner reported',
    },
    {
        "name": 'a_comp_image_cannot_reach_a_public_page',
        "file": 'app/approvals.py',
        "find": '            ok, _why = kb.may_publish(aid)\n            if not ok:\n                continue',
        "replace": '            ok, _why = True, ""  # SABOTAGE',
        "suites": ['test_article_image.py'],
        "why": 'a reference-only comp is published as the featured image of a public article — the SEO arm does not go through ledger.publish, so this executor is the only door left that can catch it',
    },
    {
        "name": 'an_unambiguous_store_needs_no_picker',
        "file": 'app/shopify_seo.py',
        "find": '    return str(blogs[0].get("id") or "") if len(blogs) == 1 else ""',
        "replace": '    return ""  # SABOTAGE',
        "suites": ['test_article_image.py'],
        "why": 'a store with exactly one blog is refused for having no blog_id, so the commonest account drafts articles that can never be queued until somebody finds a picker on another tab',
    },
    {
        "name": 'where_articles_go_has_one_writer',
        "file": 'app/tenants.py',
        "find": '        cms["blog_id"] = blog_id',
        "replace": '        cms["blogId"] = blog_id  # SABOTAGE',
        "suites": ['test_article_image.py'],
        "why": 'the picker and the auto-resolve write the destination under different keys, so choosing a blog in the console appears to work and every reader still sees none',
    },
    {
        "name": 'a_repeated_lesson_is_reinforced_not_duplicated',
        "file": 'app/systems.py',
        "find": '            if prov.normalise(instruction_of(r.content or "")) == want:',
        "replace": '            if False:  # SABOTAGE',
        "suites": ['test_systems.py'],
        "why": 'pressing Never again on ten sentences that provoke one correction files ten copies of it, so a prompt that should carry one sharp rule carries the same rule ten times and crowds out nine others',
    },
    {
        "name": 'guidance_is_ranked_by_reinforcement',
        "file": 'app/systems.py',
        "find": '    rows.sort(key=lambda r: -_times(r.topic or ""))',
        "replace": '    pass  # SABOTAGE',
        "suites": ['test_systems.py'],
        "why": 'the cap keeps the most RECENT lessons, so a correction given twelve times is pushed out of the prompt by one given once yesterday — and nothing says which rule stopped applying',
    },
    {
        "name": 'the_prompt_gets_the_rule_not_the_example',
        "file": 'app/systems.py',
        "find": '    return _FILED_FROM.sub("", _PROVOCATION.sub("", str(text or ""))).strip()',
        "replace": '    return str(text or "").strip()  # SABOTAGE',
        "suites": ['test_systems.py'],
        "why": 'every prompt in every system carries the quoted sentence that provoked each lesson — the least generalisable part, prose the drafter may echo back, and roughly half the token cost of the whole block',
    },
    {
        "name": 'a_capped_lesson_is_not_dropped_in_silence',
        "file": 'app/systems.py',
        "find": '    tail = (f"\\n({held} older correction(s) are on file and NOT shown here — "',
        "replace": '    tail = ("" or f"\\n({held} hidden — "  # SABOTAGE',
        "suites": ['test_systems.py'],
        "why": 'a rule the owner filed and believes is standing quietly stops reaching the drafter once the cap fills, with nothing on any surface saying so',
    },
    {
        "name": 'an_account_lesson_reaches_every_system',
        "file": 'app/systems.py',
        # RE-POINTED 2026-08-30: `guidance_block` gained additive scopes
        # (`also=`) so a mail reply carries both the inbox thread and the
        # thread of the system that owns it, and the single `return` became an
        # accumulator. The guard is unchanged in what it covers.
        "find": '        out = (account_block(tenant) + feedback_block(tenant, key)',
        "replace": '        out = (feedback_block(tenant, key)  # SABOTAGE',
        "suites": ['test_systems.py'],
        "why": "a lesson filed for the whole account is written down and read by nobody, so 'Never again' silently means 'never again in this one pipeline' and the ad repeats the mistake the blog was corrected for",
    },
    {
        "name": 'an_account_lesson_is_labelled_as_one',
        "file": 'app/systems.py',
        "find": '                   "STANDING GUIDANCE for this ACCOUNT, whatever you are "',
        "replace": '                   "STANDING GUIDANCE for this system, whatever you are "  # SABOTAGE',
        "suites": ['test_systems.py'],
        "why": "account-wide guidance is presented to the drafter as this pipeline's own, so a rule about what the brand sells reads as a rule about how the blog writes — and the drafter applies one as the other",
    },
    {
        "name": 'the_note_teaches_the_account_not_the_blog',
        "file": 'app/admin_ui.py',
        "find": '            + form("account", teach, "Never again",',
        "replace": '            + form("system", teach, "Never again",  # SABOTAGE',
        "suites": ['test_claim_trace.py'],
        "why": 'the claim margin files its lessons against whichever system happened to be open, so a fact about what the account sells teaches one pipeline and leaves the other five to repeat it',
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
        "name": 'a_corrected_claim_keeps_its_scope',
        "file": 'app/web.py',
        "find": "        status=\"active\" if approve else \"pending\",\n        entity_key=entity_key,",
        "replace": '        status="active" if approve else "pending",\n        entity_key="",  # SABOTAGE',
        "suites": ['test_claim_fix.py'],
        "why": "a claim corrected against ONE venue is filed brand-wide, "
               "so \"Glassbox holds 180\" becomes true of everything this "
               "account sells and any draft about any room may cite it. "
               "The entity picker in the panel becomes a decoration, "
               "which is the same defect as filing the uncorrected "
               "sentence one field along.\n\n"
               "(This slot held `a_claim_from_a_draft_is_only_proposed`, "
               "then briefly `a_correction_is_not_re_judged_as_an_"
               "observation` — which reported MISSED, because "
               "`review != APPROVED` already stops the filter on that "
               "path and the `assess` flag it anchored is belt-and-braces "
               "there. The original property is carried by "
               "`an_unread_sentence_is_still_only_proposed`.)",
    },
    {
        "name": 'an_off_catalogue_steer_is_not_a_claim',
        "file": 'app/admin_ui.py',
        "find": '    add = ("" if note["state"] in ("ok", "off") or note.get("proposed")',
        "replace": '    add = ("" if note["state"] in ("ok",) or note.get("proposed")',
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
        "find": '            + form("account", teach, "Never again",',
        "replace": '            + form("account", teach, "SABOTAGED",',
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
    {
        "name": "a_guard_is_judged_by_the_exit_code",
        "file": "scripts/sabotage.py",
        # SPLIT ON PURPOSE, and the only entry that needs to be. This is the
        # one guard whose `file` is this file, so an anchor written whole would
        # appear twice — once in `run_suite`, once here — and both this harness
        # and `test_sabotage_anchors.py` count occurrences to decide whether an
        # anchor is unambiguous. Adjacent literals are one string to Python and
        # two to `str.count`.
        "find": "    return p.return" "code == 0",
        "replace": "    out = p.stdout + p.stderr  # SABOTAGE\n    return \"all checks pas" "sed\" in out or \"all green\" in out",
        "suites": ["test_sabotage_anchors.py"],
        "why": "the harness goes back to reading two strings out of stdout to "
               "decide whether a suite passed, so the eight suites that print "
               "neither can never be seen to pass and the 42 guards naming one "
               "print [ caught ] whether the mutation did anything or not — "
               "including the guard on the open-defect ledger, whose entire "
               "purpose is to fail on good news. A guard that cannot fail is "
               "worse than no guard: it is counted",
    },
    {
        "name": "a_declared_need_reaches_an_answer",
        "file": "app/kb.py",
        "find": '    "asset":         lambda t, b: bool(assets(t)),',
        "replace": '    # SABOTAGE — the asset supplier removed',
        "suites": ["test_catalog_vocabulary.py"],
        "why": "`asset` goes back to being declared in systems.CATALOG and "
               "answered nowhere, so kb.needs_met cannot see it and the "
               "install screen draws a green tick for pictures on an account "
               "with none. This is the exact state the campaign_email walk "
               "shipped: the one token it had just added was the one token "
               "that could not be reported",
    },
    {
        "name": "an_unanswerable_need_is_not_reported_met",
        "file": "app/kb.py",
        "find": "        answer = KB_SUPPLIERS.get(f)\n        if answer is None:",
        "replace": "        answer = KB_SUPPLIERS.get(f) or (lambda t, b: True)  # SABOTAGE\n        if False:",
        "suites": ["test_catalog_vocabulary.py"],
        "why": "an unrecognised kb_needs token is silently SATISFIED again — "
               "`have.get(f, True)` in its original form. A system can then "
               "declare a need no readiness check can ever see, report ready "
               "on it, and go live: absence read as permission, on the surface "
               "whose whole job is to say what is absent",
    },
    {
        "name": "a_scope_is_derived_not_written_beside",
        "file": "app/dossier.py",
        "find": "    out.update({k: _sections_for(k) for k in systems.CATALOG})",
        "replace": '    out.update({"creative": ("identity", "rules", "claims", "catalogue", "gaps")})  # SABOTAGE',
        "suites": ["test_catalog_vocabulary.py"],
        "why": "SCOPES goes back to a hand-written list beside the catalogue "
               "rather than over it, so it can name a scope that is not a "
               "system and miss systems that are. That is how `creative` "
               "outlived `ad_creative` by a fortnight: the narrow scope was "
               "unreachable by the only name a caller has, and the fallback "
               "handed back the whole document stamped with the system it had "
               "not been scoped to",
    },
    {
        "name": "an_unscoped_key_is_refused_not_fallen_back_on",
        "file": "app/dossier.py",
        "find": "    if system and system not in SCOPES:",
        "replace": "    if False:  # SABOTAGE",
        "suites": ["test_dossier.py"],
        "why": "?system=anything silently returns the WHOLE document with "
               "`system` stamped on it, so a caller narrowing to a scope that "
               "does not exist is told it succeeded — the fallback-that-"
               "succeeds shape, which is the hardest kind of wrong to see and "
               "the reason this drift survived",
    },
    {
        "name": "the_reference_is_written_by_the_code",
        "file": "app/systems.py",
        "find": '        kb_needs=("tone", "banned_claims", "entity", "claim",\n                  "objection", "audience", "asset"),',
        "replace": '        kb_needs=("tone", "banned_claims", "entity", "claim",\n                  "objection", "audience"),  # SABOTAGE',
        "suites": ["test_catalog_vocabulary.py"],
        "why": "the declaration moves and SYSTEMS-REFERENCE.md does not, which "
               "is exactly what happened: the document named four of "
               "campaign_email's seven kb_needs tokens for as long as the "
               "extra three existed and nothing said so. A reference that "
               "describes the code has to be written BY the code, and "
               "byte-compared, or it is a summary somebody will trust",
    },
    {
        "name": "the_default_rung_can_be_decided",
        "file": "app/skill.py",
        "find": "    # `shadow` — the one manual rung, and the change of 2026-08-31.",
        "replace": '    if autonomy == "shadow":\n        return "recorded"  # SABOTAGE',
        "suites": ["test_skill.py", "test_workroom_email.py"],
        "why": "shadow goes back to filing `recorded`, and `emit` queues an "
               "approval only on `needs_approval` — so the DEFAULT rung, the "
               "one every system a client installs and never promotes sits "
               "on, drafts things nobody can approve. That was the commonest "
               "state of this platform: a finished draft, and a page whose "
               "only offer was an explanation of which rung to move to in "
               "order to get a button",
    },
    {
        "name": "one_artifact_one_pending_decision",
        "file": "app/approvals.py",
        "find": "        if _oid and kind != \"skill_output\":",
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_article_review.py"],
        "why": "an article carries BOTH the generic `skill_output` approval "
               "emit files and the `seo_new_article` one that actually "
               "publishes, so the workroom offers whichever it reads first — "
               "and half the time 'Approve & publish' is bound to the row "
               "with no executor arm, which approves into nothing. Two "
               "pending rows for one artifact is also exactly the bulk the "
               "owner asked to be rid of",
    },
    {
        "name": "a_draft_with_no_decision_can_get_one",
        "file": "app/admin_ui.py",
        "find": "    if (not published and not superseded_by and (art.body or \"\").strip()\n"
                "            and not _has_decision):",
        "replace": "    if False:  # SABOTAGE — the stranded draft gets no control",
        "suites": ["test_queue_approval.py"],
        "why": "every draft filed before the default rung started queuing is "
               "stranded: real, finished, and with no way to decide it short "
               "of a redraft. The page reports the absence and offers nothing "
               "that ends it, which is design rule 1 broken on the surface "
               "the rule was written for",
    },
    {
        "name": "the_button_that_says_approve_approves",
        "file": "app/web.py",
        "find": "    if decide == \"approved\":\n"
                "        said = _appr.apply_decision(ap_id, \"approved\")",
        "replace": "    if False:  # SABOTAGE\n"
                   "        said = _appr.apply_decision(ap_id, \"approved\")",
        "suites": ["test_queue_approval.py"],
        "why": "the button reads Approve and only queues, so the draft sits "
               "pending while the person who pressed it believes they "
               "decided — the two-step is back, wearing the label of the "
               "one-step",
    },
    {
        "name": "a_decision_is_made_where_it_is_read",
        "file": "app/admin_ui.py",
        "find": '    <form method="post" action="/admin/ship_decide?key={_esc(key)}" class="inl">',
        "replace": '    <form method="get" action="/decide/x" class="inl">  <!-- SABOTAGE -->',
        "suites": ["test_queue_approval.py"],
        "why": "the workroom hands the highest-stakes control back to the "
               "EMAIL mechanism: `/decide/<signed-token>` is unauthenticated "
               "by design, renders a bare <h2> on a blank page, and offers no "
               "way back to the draft you were reading. The ship queue was "
               "rebuilt to end exactly that a fortnight earlier and the "
               "workroom kept it, which is what the owner hit on 2026-08-31 — "
               "'a page that confirms its been sent with no UI'",
    },
    {
        "name": "deciding_never_costs_you_your_place",
        "file": "app/web.py",
        "find": "    back_work = str(form.get(\"back_work\") or \"\")\n    if back_work:",
        "replace": "    back_work = \"\"  # SABOTAGE\n    if back_work:",
        "suites": ["test_queue_approval.py"],
        "why": "approving from the workroom throws the reader out to the "
               "Review tab instead of back to the artifact they were reading, "
               "so the confirmation is a sentence somewhere else rather than "
               "the page itself re-rendering in its pushed state. Design rule "
               "3: a decision never costs the reader their place",
    },
    {
        "name": "a_batch_is_queued_the_way_its_board_reads",
        "file": "app/web.py",
        "find": '    if (art.format or "") == "ad_batch":',
        "replace": "    if False:  # SABOTAGE",
        "suites": ["test_queue_approval.py"],
        "why": "queueing an ad batch files ONE approval against the batch id, "
               "and the board counts only approvals carrying a VARIANT id — "
               "so the row satisfies `_article_bundle`, hides the button that "
               "made it, and is counted and decidable by nothing. An approval "
               "no surface can act on is worse than none: the queue says "
               "there is work waiting and no page will ever clear it",
    },
    {
        "name": "a_new_dead_connection_is_flagged",
        "file": "app/systems.py",
        "find": '            ship_by="approvals._execute:seo_new_article",',
        "replace": '            ship_by="approvals._execute:no_such_kind",  # SABOTAGE',
        "suites": ["test_register.py"],
        "why": "a system declares a ship performed by something that does not "
               "exist and nothing says so. That is the shape every defect "
               "found in this repo in one week actually had — two halves of a "
               "contract written in different places with nothing joining "
               "them — and the register is the join. One that cannot notice a "
               "NEW dead connection is a document, not a check",
    },
    {
        "name": "the_register_cannot_go_stale",
        "file": "REGISTER.md",
        "find": "| **EMPTY** | declared or built, and nothing consumes it |",
        "replace": "| **EMPTY** | edited by hand |  <!-- SABOTAGE -->",
        "suites": ["test_register.py"],
        "why": "the register is edited BY HAND and nothing notices, so it "
               "drifts from the code exactly the way SYSTEMS-REFERENCE.md did "
               "— which is the failure this whole register exists to stop "
               "happening to anything else. Anchored on the document rather "
               "than on `--check`, because the suite compares in-process: a "
               "guard pointed at code the suite does not call is a guard that "
               "cannot fire (it reported MISSED first time, 2026-08-31)",
    },
    {
        "name": "a_table_owner_is_enforced",
        "file": "app/db.py",
        "find": '    "KbBrand": "kb.py", "KbClaim": "kb.py", "KbAudience": "kb.py",',
        "replace": '    "KbBrand": "*", "KbClaim": "*", "KbAudience": "*",  # SABOTAGE',
        "suites": ["test_register.py"],
        "why": "the one-writer-per-table rule SYSTEMS-REFERENCE §3 has stated "
               "in prose since it was written goes back to being unenforced. "
               "It was prose for months, which is this repo's own rule about "
               "rules: one that reaches no validator does not exist",
    },
    {
        "name": "no_two_rungs_behave_alike",
        "file": "app/systems.py",
        "find": 'AUTONOMY = ("shadow", "approve_exceptions", "auto")',
        "replace": 'AUTONOMY = ("shadow", "approve_all", "approve_exceptions", "auto")  # SABOTAGE',
        "suites": ["test_systems.py", "test_register.py"],
        "why": "the ladder carries two rungs that return the same disposition "
               "for the same input again, so every card explains a difference "
               "that is not there and the first promotion moves a system from "
               "'everything waits for you' to 'everything waits for you'. It "
               "also hid a real defect: the thin-knowledge caveat rode ONLY "
               "that no-op promotion, so it was named where it did not matter "
               "and dropped everywhere it did",
    },
    {
        "name": "ready_is_an_ending_not_a_state",
        "file": "app/admin_ui.py",
        "find": '                      f\'href="/admin/ad_export?key={_esc(key)}\'',
        "replace": '                      f\'href="#"  \'  # SABOTAGE',
        "suites": ["test_ad_board.py"],
        "why": "an approved ad batch goes back to being a state with nothing "
               "after it. `ad_creative`'s entire declared ship is this "
               "moment, and the bar reported it while offering no way to take "
               "the copy anywhere — a fact with no control beside it, on the "
               "one system where that IS the whole product",
    },
    {
        "name": "a_dropped_variant_never_rides_the_export",
        "file": "app/web.py",
        "find": '    live = [v for v in (batch.get("variants") or []) if not v.get("dropped")]',
        "replace": '    live = list(batch.get("variants") or [])  # SABOTAGE',
        "suites": ["test_ad_board.py"],
        "why": "copy the owner threw off the board is pasted into Meta with "
               "the rest of it. Approving already DENIES a dropped variant, so "
               "the export would be handing over the exact thing the decision "
               "refused — and once it is running, `meta_ads.match` joins it "
               "back as though it had been approved",
    },
    {
        "name": "launching_reaches_the_join",
        "file": "app/web.py",
        "find": "    got = meta_ads.match(tenant)",
        "replace": '    got = {"ok": True, "matched": 0, "live": 0}  # SABOTAGE',
        "suites": ["test_ad_board.py"],
        "why": "the ads measurement loop goes back to being open at both "
               "ends. `meta_ads.match` writes the ad id and the outcome onto "
               "the drafted rows and had no caller at all until 2026-08-31 — "
               "a fully built join reachable from nowhere, which is the exact "
               "shape the reachability register was written to find",
    },
    {
        "name": "a_retired_rung_never_breaks_a_button",
        "file": "app/systems.py",
        "find": '    return v if v in AUTONOMY else "shadow"',
        "replace": "    return v  # SABOTAGE",
        "suites": ["test_systems.py"],
        "why": "a System row still holding `approve_all` — a skipped "
               "migration, or a row written by an older process between a "
               "deploy and that migration — reaches AUTONOMY.index() and "
               "raises, so Down-a-rung 500s. The failure appears days after "
               "the merge that caused it, on a button, with nothing "
               "connecting the two",
    },
    {
        "name": "a_retired_rung_word_still_posts",
        "file": "app/systems.py",
        "find": '            fields["autonomy"] = AUTONOMY_ALIASES.get(fields["autonomy"],',
        "replace": '            fields["autonomy"] = dict().get(fields["autonomy"],',
        "suites": ["test_systems.py"],
        "why": "a bookmarked rung form, an old digest link, or any client "
               "still posting `approve_all` is refused with 'autonomy must be "
               "one of' — a 400 on a word that was valid yesterday, which "
               "reads to the owner as the console being broken rather than as "
               "a rung having been renamed",
    },
    {
        "name": "background_is_never_counted_as_readiness",
        "file": "app/kb.py",
        "find": '    "asset":         lambda t, b: bool(assets(t)),',
        "replace": '    "asset":         lambda t, b: bool(assets(t)),\n    "context":       lambda t, b: bool(contexts(t)),  # SABOTAGE',
        "suites": ["test_context.py"],
        "why": "background becomes a kb_needs supplier, so filing statements "
               "that prove nothing starts making a system look READY. That is "
               "the exact reason it is a separate table rather than a `kind` "
               "column on KbClaim: one wrong entry and a thin account clears "
               "its gate on notes nobody could cite",
    },
    {
        "name": "background_is_scoped_to_what_it_is_about",
        "file": "app/kb.py",
        "find": '        rows = [r for r in rows\n                if not (r.entity_key or "") or r.entity_key == entity_key]',
        "replace": "        pass  # SABOTAGE",
        "suites": ["test_context.py"],
        "why": "a note filed about one product is handed to the drafter "
               "writing about every other one. Retrieval by scope is the "
               "whole difference between this and guidance — guidance is "
               "capped at eight and rides every draft, and if background does "
               "the same it is guidance with a longer list",
    },
    {
        "name": "background_reaches_the_drafter_saying_what_it_is_not",
        "file": "app/resolve.py",
        "find": '+ "\\n\\n## BACKGROUND — true here, and NOT proof\\n"',
        "replace": '+ "\\n\\n## BACKGROUND\\n"  # SABOTAGE',
        "suites": ["test_context.py"],
        "why": "the drafter is handed interesting sentences with nothing "
               "saying they are not evidence. The validator still refuses a "
               "factual sentence that cites no approved claim, so this does "
               "not ship a false claim — it spends a draft to catch what one "
               "line of the prompt was preventing",
    },
    {
        "name": "a_demoted_claim_keeps_its_row",
        "file": "app/kb.py",
        "find": '        row.review, row.status = prov.REJECTED, "retired"\n        s.commit()\n        text, ctx_id, ctx_text = (row.claim or "")[:60], ctx.id, row.claim',
        "replace": '        s.delete(row)  # SABOTAGE\n        s.commit()\n        text, ctx_id, ctx_text = "", ctx.id, ""',
        "suites": ["test_context.py"],
        "why": "demoting a claim to background DELETES it, so every output "
               "already on the ledger that cited it has a dangling id and the "
               "record of why a published draft said what it said is gone. "
               "Changing your mind about a claim must not rewrite the history "
               "of the work that used it",
    },
    {
        "name": "evidence_does_not_ride_into_background",
        "file": "app/kb.py",
        "find": "        ctx = db.KbContext(tenant=row.tenant, text=row.claim,",
        "replace": '        ctx = db.KbContext(tenant=row.tenant, text=(row.claim + (" — " + row.evidence if row.evidence else "")),  # SABOTAGE',
        "suites": ["test_context.py"],
        "why": "the number rides into the background line, so 'Dishwasher "
               "safe — tested 200 cycles' sits in a section headed 'not "
               "proof' with the proof attached. That is proof wearing another "
               "hat, and it is exactly the thing background exists to stop "
               "being quotable",
    },
    {
        "name": "background_is_an_indexed_kind",
        "file": "app/kb.py",
        "find": '        embed.ensure(tenant, "context", row_id, text)',
        "replace": "        pass  # SABOTAGE",
        "suites": ["test_context.py"],
        "why": "background goes back to being invisible to semantic recall — "
               "`embed` indexes claims and situations and not this — so a "
               "statement re-filed in different words cannot be matched "
               "against what is already there. That is the entire purpose of "
               "having somewhere to put the things that keep coming up",
    },
    {
        "name": "the_same_statement_is_not_filed_twice",
        "file": "app/kb.py",
        "find": "        if dupe is not None:",
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_context.py"],
        "why": "background loses the identity a claim has, so re-typing the "
               "same observation a fortnight later files a second row and the "
               "drafter is handed both. `prov.fingerprint` already decides "
               "two claims are the same claim; background having a weaker "
               "identity than proof is backwards",
    },
    {
        "name": "a_filing_check_spans_both_kinds",
        "file": "app/kb.py",
        "find": '        for kind, live, field in (("claim", live_cl, "claim"),\n                                  ("context", live_ctx, "text")):',
        "replace": '        for kind, live, field in (("claim", live_cl, "claim"),):  # SABOTAGE',
        "suites": ["test_context.py"],
        "why": "the near-duplicate check sees claims only, so filing "
               "background cannot notice the same statement is already filed "
               "as background — each of the two dedup mechanisms this repo "
               "has ends up able to see half the knowledge base, which is the "
               "state that made this work necessary",
    },
    {
        "name": "an_indexed_kind_is_a_kind_the_index_accepts",
        "file": "app/embed.py",
        "find": '"media", "context",',
        "replace": '"media",  # SABOTAGE',
        "suites": ["test_catalog_vocabulary.py", "test_context.py"],
        "why": "`ensure` returns the STRING \"unknown kind\" rather than "
               "raising, so a kind the KB indexes and the index does not "
               "accept fails in silence — background unsearchable while every "
               "surface reports it filed. That is this module's own "
               "docstring's warning ('degrading silently is not allowed') "
               "broken against itself, and it shipped once already",
    },
    {
        "name": "a_proposal_is_indexed_before_it_is_judged",
        "file": "app/kb.py",
        "find": '    # INDEXED WHETHER OR NOT IT IS APPROVED, and that is the change of',
        "replace": '    if review != prov.APPROVED:\n        return "Submitted for review."  # SABOTAGE',
        "suites": ["test_context.py"],
        "why": "a proposal is not embedded, so it cannot be compared with "
               "anything — and 'check what is already on file before "
               "suggesting something new' is impossible for the one row it "
               "matters most for. The queue could still say a proposal "
               "duplicates an approved claim, because that comparison is done "
               "on rows, and could never say it restates background",
    },
    {
        "name": "parallel_rows_are_not_called_duplicates",
        "file": "app/kb.py",
        "find": '        if a["scope"] != b["scope"]:',
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_context.py"],
        "why": "the same sentence about two entities is reported as a "
               "duplicate, so somebody retires one product's answer because "
               "another product has the same one. Both `add_claim` and "
               "`add_context` put the entity in the fingerprint precisely "
               "because those are two statements, and the claim queue already "
               "says so in prose — a report that argues with the queue is "
               "worse than no report",
    },
    {
        "name": "a_proposal_that_restates_background_says_so",
        "file": "app/admin_ui.py",
        "find": "            for _y, _sc in _bg.get(p.id, [])[:2]:",
        "replace": "            for _y, _sc in []:  # SABOTAGE",
        "suites": ["test_context.py"],
        "why": "a proposal restating something deliberately filed as 'true, "
               "and NOT proof' arrives in the queue looking new, and "
               "approving it promotes to citable proof the exact sentence "
               "somebody filed as not being that",
    },
    {
        "name": "a_settled_question_is_not_asked_again",
        "file": "app/kb.py",
        "find": "        _bg = _settled_as_background(tenant, claim, entity_key)",
        "replace": "        _bg = None  # SABOTAGE",
        "suites": ["test_context.py"],
        "why": "a harvester restating something a person already filed as "
               "'true, and NOT proof' goes back into the claim queue as a "
               "proposal — asking the same question a second time and "
               "offering the answer the person already rejected. Every "
               "re-crawl asks it again",
    },
    {
        "name": "a_person_outranks_a_similarity_score",
        "file": "app/kb.py",
        "find": "    if assess and review != prov.APPROVED:\n        _bg = _settled_as_background",
        "replace": "    if True:  # SABOTAGE\n        _bg = _settled_as_background",
        "suites": ["test_context.py"],
        "why": "an APPROVED add — a human in the console, a seed — is "
               "diverted into background by a similarity score, so a person "
               "saying 'this IS a claim' is overruled by a number. The "
               "standing rule runs the other way: generators propose and "
               "never populate, and the converse is that a decision outranks "
               "a measurement",
    },
    {
        "name": "an_observation_is_not_filed_as_proof",
        "file": "app/kb.py",
        "find": '        if _kind["kind"] == "background" and _kind["confident"]:',
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_context.py"],
        "why": "every harvested observation goes back into the claim queue as "
               "a candidate for citable proof, so 'buyers ask about lead time' "
               "is one approval away from being a fact the brand asserts and "
               "a validator will happily let a draft cite",
    },
    {
        "name": "a_routed_statement_waits_for_a_person",
        "file": "app/kb.py",
        "find": '                               status="pending",\n                               source=f"routed from a claim proposal · "',
        "replace": '                               status="active",  # SABOTAGE\n                               source=f"routed from a claim proposal · "',
        "suites": ["test_context.py"],
        "why": "a CLASSIFIER writes an approved row, so a machine's verdict "
               "becomes knowledge on file and reaches every drafter without a "
               "human ever seeing it. Generators propose and never populate — "
               "and a filter is a generator",
    },
    {
        "name": "an_override_is_not_re_litigated",
        "file": "app/kb.py",
        "find": "    if assess and review != prov.APPROVED:",
        "replace": "    if review != prov.APPROVED:  # SABOTAGE",
        "suites": ["test_context.py"],
        "why": "'it is provable' sends a statement to the claim queue, the "
               "classifier reads the same words and routes it straight back "
               "to background, and the reversal control becomes a loop with a "
               "button on it. A person's decision is the one input this layer "
               "may never re-litigate",
    },
    {
        "name": "a_default_is_not_read_as_a_statement",
        "file": "app/kb.py",
        "find": '                            "" if proof_type == DEFAULT_PROOF_TYPE',
        "replace": '                            proof_type if True  # SABOTAGE',
        "suites": ["test_context.py"],
        "why": "`add_claim` defaults `proof_type` to case_study, so a caller "
               "that said NOTHING is indistinguishable from one that chose a "
               "proof type — the filter concludes every candidate carries "
               "proof and never routes anything. It fires on nothing and "
               "looks like it is working",
    },
    {
        "name": "the_register_cannot_go_quietly_out_of_date",
        "file": "scripts/register.py",
        "find": "            \"functions\": function_map()}",
        "replace": '            "functions": []}  # SABOTAGE',
        "suites": ["test_register.py"],
        "why": "the register stops describing what it claims to describe and "
               "nothing says so — the exact failure SYSTEMS-REFERENCE.md had, "
               "rebuilt in the document written to prevent it. A register is "
               "only worth reading if a change that moves it fails the build "
               "in the commit that moves it",
    },
    {
        "name": "the_correction_is_what_gets_filed",
        "file": "app/web.py",
        "find": '        art.tenant or "", sentence, evidence, [], proof_type="",',
        "replace": '        art.tenant or "", str(form.get("sentence") or "")[:0] or art.draft_body or "", evidence, [], proof_type="",  # SABOTAGE',
        "suites": ["test_claim_fix.py"],
        "why": "the box is editable and the DRAFT'S wording is filed anyway, "
               "so correcting 250 to 180 files 250 — the panel becomes a "
               "decoration and the owner has no way to know their correction "
               "was discarded until a draft cites the wrong number",
    },
    {
        "name": "a_corrected_claim_is_the_owners",
        "file": "app/web.py",
        "find": '        origin="human" if approve else "agent",',
        "replace": '        origin="agent",  # SABOTAGE',
        "suites": ["test_claim_fix.py"],
        "why": "a claim a person rewrote is filed as the AGENT'S, and "
               "`origin` is what precedence is computed from — so the next "
               "crawl or store sync may overwrite the correction and put the "
               "wrong capacity back, with nothing having gone wrong in its "
               "own logic",
    },
    {
        "name": "an_unread_sentence_is_still_only_proposed",
        "file": "app/web.py",
        "find": '        status="active" if approve else "pending",',
        "replace": '        status="active",  # SABOTAGE',
        "suites": ["test_claim_fix.py"],
        "why": "Save-as-proposal files an APPROVED claim, so a sentence a "
               "model wrote becomes something every future draft may assert "
               "without anybody reading it. That is the path this endpoint's "
               "docstring exists to keep closed, and the panel's whole "
               "argument for approving is that a person HAS read it",
    },
    {
        "name": "an_approved_correction_reaches_the_draft",
        "file": "app/web.py",
        "find": "        if original and original != sentence:",
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_claim_fix.py"],
        "why": "the corrected claim is filed and the article still says 250 "
               "— so the right fact is on record, the wrong number is what "
               "publishes, and the new claim makes the wrong sentence look "
               "GROUNDED. That is worse than never having filed it",
    },
    {
        "name": "a_correction_that_missed_says_so",
        "file": "app/web.py",
        "find": '        return ("The draft was NOT changed — that sentence is no longer in it, "',
        "replace": '        return ("The draft now says it too."  # SABOTAGE and ("',
        "suites": ["test_claim_fix.py"],
        "why": "a correction that matched nothing reports success, so a "
               "reader is told the draft was updated while it still reads "
               "250. A silent no-op on the one action whose entire purpose "
               "is to change the text is the worst shape this console has",
    },
    {
        "name": "a_correction_keeps_the_markup_balanced",
        "file": "app/claim_trace.py",
        "find": '    tags = "".join(re.findall(r"<[^>]+>", m.group(0)))',
        "replace": '    tags = ""  # SABOTAGE',
        "suites": ["test_claim_fix.py"],
        "why": "a sentence that opens inside <strong> and closes after it "
               "loses its closing tag, so the rest of the article is bold "
               "and the markup is unbalanced from there down. Losing "
               "emphasis is cosmetic; losing a closing tag corrupts the "
               "document",
    },
    {
        "name": "a_correction_meets_the_ban_list",
        "file": "app/web.py",
        "find": "    hit = next((b for b in banned if str(b).strip()\n                and str(b).lower() in corrected.lower()), \"\")",
        "replace": '    hit = ""  # SABOTAGE',
        "suites": ["test_claim_fix.py"],
        "why": "the one edit path that writes into a draft without meeting "
               "the account's ban list is the correction panel — so "
               "'handmade' can be typed straight into an article by the "
               "control that exists to make articles more accurate",
    },
    {
        "name": "review_sees_the_claims_the_draft_was_written_with",
        "file": "app/admin_ui.py",
        "find": "    claims = _claims_for_review(tenant, art)",
        "replace": "    claims = kb.claims(tenant)  # SABOTAGE",
        "suites": ["test_claim_fix.py"],
        "why": "the claim margin goes back to brand-wide claims only, so a "
               "claim scoped to the thing the draft is ABOUT is invisible "
               "and the sentence it backs still reads 'needs a claim' — "
               "which is what the owner hit straight after filing one. The "
               "margin judges a draft against a NARROWER set than `resolve` "
               "gave the drafter, so the review disagrees with the write",
    },
    {
        "name": "a_brand_claim_is_counted_once_per_draft",
        "file": "app/admin_ui.py",
        "find": "    return list(seen.values())",
        "replace": "    return list(seen.values()) + list(seen.values())  # SABOTAGE",
        "suites": ["test_claim_fix.py"],
        "why": "`kb.claims(entity_key=…)` returns brand-wide claims EVERY "
               "time, so a draft naming two entities would carry each brand "
               "claim twice and the coverage percentage would be computed "
               "over a list that double-counts its own contents",
    },
    {
        "name": "a_piece_about_a_place_may_cite_what_is_in_it",
        "file": "app/kb.py",
        "find": "        wanted = [k for k in ([entity_key] if entity_key else [])\n                  + list(entity_keys or []) if k]",
        "replace": "        wanted = [entity_key] if entity_key else []  # SABOTAGE",
        "suites": ["test_entity_scope.py"],
        "why": "an article about a LOCATION goes back to seeing brand-wide "
               "claims only, so the venues that are the evidence for "
               "'several distinct spaces in one place' are invisible and the "
               "account's best claim is the one it cannot prove",
    },
    {
        "name": "specificity_is_scored_against_the_nearest_subject",
        "file": "app/kb.py",
        "find": "            depth = max((scope_depth(k, r.entity_key, chain) for k in wanted),\n                        default=scope_depth(None, r.entity_key, chain))",
        "replace": "            depth = scope_depth(wanted[0] if wanted else None, r.entity_key, chain)  # SABOTAGE",
        "suites": ["test_entity_scope.py"],
        "why": "with several subjects in scope, every claim is scored against "
               "the FIRST of them — so the Atrium's own facts rank as a "
               "distant relative of the Glassbox and sort below brand-wide "
               "ones, in the article whose whole point is the venues",
    },
    {
        "name": "several_subjects_reach_the_drafter",
        "file": "app/skill.py",
        "find": "                        entity_keys=_sysm.entity_list(\n                            params.get(\"entity_keys\") or \"\"),",
        "replace": "                        entity_keys=[],  # SABOTAGE",
        "suites": ["test_blog_skill.py", "test_entity_scope.py"],
        "why": "the plan can say a piece is about several spaces and the run "
               "drops it on the way to `resolve`, so the field is a "
               "decoration and the drafter is handed the same narrow pool it "
               "always had — the shape this repo keeps closing: declared "
               "here, read nowhere",
    },
    {
        "name": "a_several_entity_field_is_a_reference",
        "file": "app/systems.py",
        "find": '              "entity_list": _entity_list_check}',
        "replace": '              }  # SABOTAGE',
        "suites": ["test_entity_scope.py"],
        "why": "a venue nobody approved passes the plan check and reads "
               "downstream as no scope at all, so a typo silently narrows an "
               "article back to brand-wide proof — which is exactly how "
               "`audience_key` accepted a persona this account had never "
               "approved for a fortnight",
    },
    {
        "name": "every_drafting_system_can_name_several_subjects",
        "file": "app/systems.py",
        "find": "                dict(key=\"entity_keys\", label=\"Also about (comma-separated)\",\n                     required=False, kind=\"entity_list\"),\n                # The SOURCE for any urgency in the email.",
        "replace": "                # SABOTAGE\n                # The SOURCE for any urgency in the email.",
        "suites": ["test_entity_scope.py"],
        "why": "campaign_email loses the field and only the blog can say a "
               "piece is about several things — so the same account gets one "
               "answer in an article and another in the email beside it, "
               "which is the vocabulary drift this repo keeps closing",
    },
    {
        "name": "a_plan_subject_outranks_the_pickers",
        "file": "app/skill_pack.py",
        "find": "        for k in _named:\n            if k != _subject and k not in _also:\n                _also.append(k)",
        "replace": "        pass  # SABOTAGE",
        "suites": ["test_campaign_email.py"],
        "why": "an email is only as multi-subject as whatever the drafter "
               "happened to feature, so a plan naming three rooms is "
               "silently narrowed to the ones the picker chose — the plan is "
               "the REVIEWED instruction and it stops outranking a guess",
    },
    {
        "name": "the_register_reports_every_system",
        "file": "scripts/register.py",
        "find": "        if not ship:",
        "replace": "        if not ship:\n            continue  # SABOTAGE",
        "suites": ["test_register.py"],
        "why": "a system with no declared ship drops out of the register "
               "entirely, so it reports eight where the catalogue has ten — "
               "in a document whose own header promises every family is "
               "ENUMERATED and not sampled. A register that quietly omits is "
               "the exact failure it exists to catch, and it shipped that "
               "way for a day",
    },
    {
        "name": "a_plain_text_artifact_is_kept",
        "file": "app/ledger.py",
        "find": "        if body and format and (\n                format in ARTIFACT_FORMATS\n                or (\"<\" in body and len(body) > 2000)):",
        "replace": "        if body and format and \"<\" in body and (\n                format in ARTIFACT_FORMATS or len(body) > 2000):  # SABOTAGE",
        "suites": ["test_compliance_reports.py"],
        "why": "a declared artifact format is kept only if it happens to "
               "contain markup, so every PLAIN-TEXT artifact is discarded — "
               "which is exactly what a compliance report is. Both sweeps go "
               "back to living in Output.body[:2000] with no workroom and no "
               "history, and the paragraph directly above says the opposite "
               "of what the code does",
    },
    {
        "name": "a_clean_check_is_still_on_the_record",
        "file": "app/compliance.py",
        "find": "                      body=report_text(tenant, result), run_id=run_id)",
        "replace": "                      body=(report_text(tenant, result) if result.get(\"violations\") else \"\"), run_id=run_id)  # SABOTAGE",
        "suites": ["test_compliance_reports.py"],
        "why": "only sweeps that FOUND something are filed, so the history "
               "records bad days and nothing else — and 'we checked and it "
               "was clean' becomes indistinguishable from 'nobody checked'. "
               "Those are the two states a compliance record exists to tell "
               "apart, and a clean row is the one that makes it a history "
               "rather than a complaints file",
    },
    {
        "name": "a_report_system_has_somewhere_to_read_its_history",
        "file": "app/admin_ui.py",
        "find": "    if wf[\"artifact\"] == \"report\":\n        subs.insert(1, (\"reports\", \"Reports\"))",
        "replace": "    pass  # SABOTAGE",
        "suites": ["test_compliance_reports.py"],
        "why": "the dated history has no room of its own, so reviewing "
               "compliance means hunting through Drafts — a shelf for things "
               "awaiting a decision, which a filed record of a check is not. "
               "The reports are kept and unreachable, which is the "
               "computed-and-never-rendered shape this console keeps paying "
               "down",
    },
    {
        "name": "a_declined_plan_stops_claiming_the_work",
        "file": "app/systems.py",
        "find": "    _release_plan_subject(sys_id, brief)",
        "replace": "    pass  # SABOTAGE",
        "suites": ["test_plan_lifecycle.py"],
        "why": "filing a plan marks its keyword `planned` and skipping stops "
               "marking it back, so a plan you declined goes on advertising "
               "an article that is never coming — for ever, on the board you "
               "use to decide what to write next. One writer, no reset",
    },
    {
        "name": "a_hand_carried_publish_is_still_delivered",
        "file": "app/admin_ui.py",
        "find": "    live = [r for r in rows if r.published_at or _landed(r.destination or \"\")]",
        "replace": "    live = [r for r in rows if _landed(r.destination or \"\") and r.stage] if False else []  # SABOTAGE",
        "suites": ["test_plan_lifecycle.py"],
        "why": "Delivered lists nothing, so the one view that answers 'what "
               "actually went out' is empty — and on a platform with no "
               "content write API, where paste-and-record IS the workflow, "
               "that is every article the account has ever published",
    },
    {
        "name": "an_intention_is_not_a_delivery",
        "file": "app/admin_ui.py",
        "find": "    return d.startswith(\"http\") or \":campaign/\" in d",
        "replace": "    return bool(d)  # SABOTAGE",
        "suites": ["test_plan_lifecycle.py"],
        "why": "`destination` is written at EMIT with an intention — "
               "`esp:omnisend`, no campaign id — so every drafted campaign "
               "reads as delivered and the view says the work went out when "
               "it is sitting in a queue. A list that cannot be trusted "
               "about that is worse than not having one",
    },
    {
        "name": "a_published_page_that_is_not_working_is_work",
        "file": "app/keywords.py",
        "find": "        \"attention\": attention(tenant, top=top),",
        "replace": "        \"attention\": [],  # SABOTAGE",
        "suites": ["test_keyword_attention.py"],
        "why": "the board goes back to answering only 'what should we "
               "write' — so a page sitting at position 7, which is a far "
               "shorter distance to a win than a page that does not exist "
               "yet, is invisible for ever. `progress` goes on measuring "
               "whether pages rank and nothing acts on the answer",
    },
    {
        "name": "a_slipped_page_is_told_from_one_that_never_ranked",
        "file": "app/keywords.py",
        "find": "                if row.won_at is None:\n                    row.won_at = db.utcnow()",
        "replace": "                pass  # SABOTAGE",
        "suites": ["test_keyword_attention.py"],
        "why": "`settle` walks a page back to `published` the moment it "
               "slips, so with no remembered high-water mark 'it ranked and "
               "stopped' is indistinguishable from 'it never ranked' — and "
               "the first is the most urgent thing on the board while the "
               "second may not be worth writing at all",
    },
    {
        "name": "a_refreshed_page_is_left_to_settle",
        "file": "app/keywords.py",
        "find": "        if since_refresh is not None and since_refresh < cooldown:\n            continue",
        "replace": "        if False:  # SABOTAGE\n            continue",
        "suites": ["test_keyword_attention.py"],
        "why": "a page refreshed last week is offered for refresh again, "
               "before it can have been re-crawled — so the queue asks for a "
               "decision that cannot yet be informed, and the refresh budget "
               "is spent on measuring nothing",
    },
    {
        "name": "the_move_is_chosen_by_where_the_page_sits",
        "file": "app/keywords.py",
        "find": "    (10.0, \"refresh\",",
        "replace": "    (1e9, \"refresh\",",
        "suites": ["test_keyword_attention.py"],
        "why": "every stalled page is told to refresh itself, including the "
               "ones at position 40 where the problem is intent or "
               "indexation and a rewrite changes nothing — the advice stops "
               "being advice and becomes a default with a sentence attached",
    },
    {
        "name": "a_published_page_is_replaced_not_duplicated",
        "file": "app/skill_pack.py",
        "find": "        supersede(ctx.tenant, prior, new_oid,",
        "replace": "        _noop(ctx.tenant, prior, new_oid,  # SABOTAGE",
        "suites": ["test_refresh_lane.py"],
        "why": "the keyword's pointer moves to the new article and the old "
               "one is left LIVE — still queued, still counted, still on the "
               "site. Two pages aimed at one query is the cannibalisation "
               "this whole lane exists to prevent, produced by the lane",
    },
    {
        "name": "the_month_a_plan_falls_in_is_read_not_parsed",
        "file": "app/planner.py",
        "find": "            d = dt.date.fromisoformat(str((brief or {}).get(\"planned_for\") or \"\"))",
        "replace": "            d = dt.date.fromisoformat(\"not-a-date\")  # SABOTAGE",
        "suites": ["test_refresh_lane.py"],
        "why": "every row raises ValueError and is skipped, so the helper "
               "returns {} on every call and the monthly cap binds only "
               "WITHIN one run — and the tick runs the planner daily, so a "
               "cap of one article a month files one a day",
    },
    {
        "name": "only_the_pages_a_refresh_would_help_get_one",
        "file": "app/planner.py",
        "find": "        if item[\"action\"] != \"refresh\":",
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_refresh_lane.py"],
        "why": "a page at position 60 — where the problem is intent or "
               "indexation — is queued for a rewrite that changes neither, "
               "and so is one at 20 whose cluster needs supports. The lane "
               "looks productive and is wrong three times in four",
    },
    {
        "name": "every_candidate_planned_is_not_a_quiet_month",
        "file": "app/planner.py",
        "find": "        ref_out = _blog_refreshes(sysrow, cad,\n"
                "                                  today + dt.timedelta(days=cad[\"horizon_days\"]))",
        "replace": "        ref_out = {\"filed\": 0, \"reasons\": [], \"refusals\": []}  # SABOTAGE",
        "suites": ["test_refresh_lane.py"],
        "why": "with every keyword already planned the planner returns early "
               "and files no refreshes — and that is not a quiet month, it is "
               "the steady state this lane was built for, when fixing pages "
               "that already shipped is the only writing left",
    },
    {
        "name": "an_approved_article_with_no_address_is_flagged",
        "file": "app/keywords.py",
        "find": "            if o is None or (o.status or \"\") not in (\"approved\", \"published\"):",
        "replace": "            if True:  # SABOTAGE",
        "suites": ["test_link_flag.py"],
        "why": "the flag empties, and an approved article nobody can link to "
               "or measure goes back to reading as done — which is the state "
               "it was already in, silently, in all three directions at once",
    },
    {
        "name": "a_linkable_support_is_written_first",
        "file": "app/planner.py",
        "find": "    rows = sorted(rows, key=lambda r: 0 if _links_up(r, by_cluster_pillar) else 1)",
        "replace": "    rows = list(rows)  # SABOTAGE",
        "suites": ["test_link_flag.py"],
        "why": "a support whose pillar has no address is written before one "
               "whose pillar has a real URL, so it ships pointing nowhere and "
               "needs a second pass later — while the article that could have "
               "landed complete waits behind it",
    },
    {
        "name": "an_address_is_a_flag_never_a_gate",
        "file": "app/keywords.py",
        "find": "    rows = [r for r in targets(tenant)\n"
                "            if not (r.target_url or \"\").strip() and (r.output_id or \"\").strip()]",
        "replace": "    rows = [r for r in targets(tenant) if False]  # SABOTAGE",
        "suites": ["test_link_flag.py"],
        "why": "the population is empty, so the strip never renders and the "
               "state stays silent — the flag was the whole mechanism, since "
               "requiring the address would block the hand-publishing "
               "accounts this happens to",
    },
    {
        "name": "the_move_depends_on_whether_there_is_a_cms",
        "file": "app/keywords.py",
        "find": "                         f\"{platform}\" if platform else",
        "replace": "                         f\"{platform}\" if False else  # SABOTAGE",
        "suites": ["test_link_flag.py"],
        "why": "every account is told to paste an address by hand, including "
               "the ones whose CMS holds it — so the instruction is wrong "
               "for exactly the accounts that could have answered it "
               "automatically",
    },
    {
        "name": "a_refresh_revises_the_page_it_is_refreshing",
        "file": "app/skill_pack.py",
        "find": "        _revising = bool(_live_id and (row.target_url or \"\").strip())",
        "replace": "        _revising = False  # SABOTAGE",
        "suites": ["test_refresh_lands.py"],
        "why": "a refresh queues a CREATE, so approving it publishes a second "
               "article beside the one that ranks — two of your own pages on "
               "one query, which is the cannibalisation the whole attention "
               "lane exists to prevent, produced by the lane",
    },
    {
        "name": "the_platform_id_survives_the_reply",
        "file": "app/sites.py",
        "find": "    return f\"{sentence}{_ID_MARK}{aid}\" if aid else sentence",
        "replace": "    return sentence  # SABOTAGE",
        "suites": ["test_refresh_lands.py"],
        "why": "the id is thrown away at creation, so nothing can ever address "
               "a revision and every refresh falls back to publishing a new "
               "page — the exact state this was in before, silently",
    },
    {
        "name": "a_refresh_keeps_the_address_it_is_refreshing",
        "file": "app/skill_pack.py",
        "find": "            **({\"article_id\": _live_id} if _revising\n"
                "               else {\"handle\": kw_mod.slug(keyword)}),",
        "replace": "            **{\"handle\": kw_mod.slug(keyword),\n"
                   "               \"article_id\": _live_id},  # SABOTAGE",
        "suites": ["test_refresh_lands.py"],
        "why": "the revision sends a handle, which moves the page's URL — and "
               "moving the address of something that ranks throws away the "
               "position that was the reason to refresh it",
    },
    {
        "name": "a_re_publish_is_a_refresh_not_a_first_publication",
        "file": "app/keywords.py",
        "find": "            if row.published_at is None:",
        "replace": "            if True:  # SABOTAGE",
        "suites": ["test_refresh_lands.py"],
        "why": "a refreshed page reads as brand new: `too_early` for another "
               "month, 'days live' lying about a page that has been up a "
               "year, and `refreshed_at` never written — so the cooldown "
               "never starts and it is offered for refresh again next week",
    },
    {
        "name": "a_hand_carried_refresh_says_it_replaces",
        "file": "app/admin_ui.py",
        "find": "        _replacing = bool(kw and (kw.target_url or \"\").strip()\n"
                "                          and not published)",
        "replace": "        _replacing = False  # SABOTAGE",
        "suites": ["test_refresh_lands.py"],
        "why": "on an account with no CMS the person carrying the copy is "
               "told nothing about the page it replaces, so the obvious "
               "reading is to paste it as a new post — a second page on one "
               "query, by hand, for exactly the keyword being refreshed",
    },
    {
        "name": "a_refresh_that_shipped_is_recorded_as_shipped",
        "file": "app/seo_tools.py",
        "find": "                 \"output_id\": str(args.get(\"output_id\") or \"\"),",
        "replace": "                 \"output_id\": \"\",  # SABOTAGE",
        "suites": ["test_refresh_lands.py"],
        "why": "the revision approval carries no join, so the executor has "
               "nothing to write the result onto: an approved refresh records "
               "nothing, the cooldown never starts, and the page comes back "
               "into the queue next week as though it had never been touched",
    },
    {
        "name": "the_page_a_publish_returns_to_renders",
        "file": "app/admin_ui.py",
        "find": "            \"measured — \" + (\"sent as-is\" if d.startswith((\"sent unchanged\",",
        "replace": "            \"measured — \" + (\"sent as-is\" if d.get(\"as_is\") or ((\"sent unchanged\",  # SABOTAGE",
        "suites": ["test_refresh_lands.py"],
        "why": "`edit_diff` is a Text column holding a string, so `.get()` on "
               "it raises AttributeError — a 500 on the page the publish loop "
               "redirects to, firing only AFTER a successful publish, which "
               "is the one path nobody re-tests",
    },
    {
        "name": "published_is_a_fact_about_this_artifact",
        "file": "app/admin_ui.py",
        "find": "    published = bool(kw and (kw.status or \"\") in (\"published\", \"won\")\n"
                "                     and _out_row is not None\n"
                "                     and ((_out_row.status or \"\") == \"published\"\n"
                "                          or _out_row.published_at is not None))",
        "replace": "    published = bool(kw and (kw.status or \"\") in (\"published\", \"won\"))  # SABOTAGE",
        "suites": ["test_refresh_lands.py"],
        "why": "every refresh draft claims to be live the moment it is "
               "written — the keyword is still published because the OLD page "
               "is up — so the workroom greets a fresh replacement with "
               "'Published' and offers nothing to do with it",
    },
    {
        "name": "a_queued_refresh_can_be_decided",
        "file": "app/web.py",
        "find": "                                                 \"seo_article_revision\",",
        "replace": "                                                 # SABOTAGE",
        "suites": ["test_refresh_lands.py"],
        "why": "the workroom never looks for a revision approval, so a "
               "refresh is queued and undecidable: the page shows no button "
               "for the one approval that exists",
    },
    {
        "name": "a_connected_store_missing_one_scope_is_told_which",
        "file": "app/sites.py",
        "find": "        if need and have is not None and need not in have:",
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_publish_gap.py"],
        "why": "an account with Shopify connected but approved without "
               "`write_content` reads as having nothing connected, so the "
               "console tells somebody to redo a connection that already "
               "exists instead of re-granting one scope — which is exactly "
               "what the owner hit",
    },
    {
        "name": "a_platform_with_no_write_api_is_not_a_failure",
        "file": "app/sites.py",
        "find": "    if platform not in BACKENDS:",
        "replace": "    if False:  # SABOTAGE",
        "suites": ["test_publish_gap.py"],
        "why": "Squarespace reads as an unconnected account being nagged to "
               "connect something, when paste-and-record IS the workflow "
               "there and no connection could ever change it",
    },
    {
        "name": "the_absence_names_its_own_fix",
        "file": "app/admin_ui.py",
        "find": "            _gap = _sites.publish_gap(tenant)",
        "replace": "            _gap = {\"why\": \"No CMS to push to.\", \"fix\": \"\",\n"
                   "                    \"where\": \"\"}  # SABOTAGE",
        "suites": ["test_publish_gap.py"],
        "why": "four different absences with four different fixes collapse "
               "back into four words, one of which points at the wrong thing "
               "entirely — a page reporting an absence and offering nothing "
               "that ends it is design rule 1 broken",
    },
    {
        "name": "an_audience_says_which_products_it_is_for",
        "file": "app/skill_pack.py",
        "find": "        rec = _kb.audience_entities(ctx.tenant, _aud_key)",
        "replace": "        rec = []  # SABOTAGE",
        "suites": ["test_audience_entities.py"],
        "why": "the recommendation is ignored and the catalogue's first few "
               "are offered alphabetically again — a selection with no "
               "decision behind it, in the one place a decision had been "
               "made",
    },
    {
        "name": "a_recommendation_never_empties_the_offer",
        "file": "app/kb.py",
        "find": "    have = {e.key: e for e in entities(tenant, available_only=available_only)}",
        "replace": "    have = {k: k for k in wanted}  # SABOTAGE",
        "suites": ["test_audience_entities.py"],
        "why": "an out-of-stock recommendation is offered anyway, so the "
               "email features something nobody can buy — and a shortlist "
               "that goes out of stock takes the whole offer with it",
    },
    {
        "name": "a_recommendation_cannot_name_nothing",
        "file": "app/kb.py",
        "find": "        (clean if k in known else unknown).append(k)",
        "replace": "        clean.append(k)  # SABOTAGE",
        "suites": ["test_audience_entities.py"],
        "why": "a mistyped key saves silently and then intersects with "
               "nothing, so the recommendation reads exactly like 'none set' "
               "— the failure is invisible at both ends",
    },
    {
        "name": "a_guessed_offer_says_it_guessed",
        "file": "app/skill_pack.py",
        "find": "                ctx.note(\"products: nobody has said what this audience is \"",
        "replace": "                pass  # SABOTAGE\n                _ = (\"products: nobody has said what this audience is \"",
        "suites": ["test_audience_entities.py"],
        "why": "the branch that picks products with no decision behind it "
               "goes silent, so a run that failed at drafting guessed and "
               "said nothing — the case where somebody most needs to know",
    },
    {
        "name": "a_run_that_cannot_publish_still_says_where_the_work_is",
        "file": "app/skill_pack.py",
        "find": "                + \" The article is written and kept; paste it in from its \"\n"
                "                  \"review page, then record the live URL there.\")",
        "replace": "                )  # SABOTAGE",
        "suites": ["test_blog_skill.py"],
        "why": "the run names what is missing and drops where the article "
               "actually went, so a person is told to go fix a connection "
               "and not told the copy exists and is waiting on a page — the "
               "more urgent of the two the moment a run finishes",
    },
    {
        "name": "the_picture_a_run_asks_for_can_be_made",
        "file": "app/web.py",
        "find": "    got = creative.generate(",
        "replace": "    got = (lambda **k: {\"ok\": False, \"error\": \"x\"})(  # SABOTAGE",
        "suites": ["test_article_picture.py"],
        "why": "the workroom control stops reaching the generator, so the "
               "run's note points at a button that does nothing — which is "
               "the state this fixed: a complete, tested, nine-guard image "
               "generator with no production caller and two surfaces "
               "promising it",
    },
    {
        "name": "a_generated_picture_is_briefed_from_the_article",
        "file": "app/web.py",
        "find": "    about = _sp.article_commitment(keyword, entity_key, also,",
        "replace": "    about = _sp.article_commitment(\"something else\", \"\", [],  # SABOTAGE",
        "suites": ["test_article_picture.py"],
        "why": "the picture is briefed against a different subject than the "
               "article was written against, so it is a picture of the wrong "
               "thing — and it would look right on both surfaces separately",
    },
    {
        "name": "a_generated_picture_is_not_attached_unapproved",
        "file": "app/skill_pack.py",
        "find": "                 f\"article's page; it arrives on Review \u00b7 Pictures for you to \"",
        "replace": "                 f\"article's page. \"  # SABOTAGE",
        "suites": ["test_article_picture.py"],
        "why": "the run stops saying the generated picture is only PROPOSED, "
               "so somebody presses the button and expects an image on the "
               "page — and an unreviewed image reaching a public site is "
               "what the whole rights ladder exists to prevent",
    },
    {
        "name": "an_article_that_has_a_picture_is_not_offered_another",
        "file": "app/admin_ui.py",
        "find": "        _has_pic = bool(_out_row is not None",
        "replace": "        _has_pic = bool(False and _out_row is not None  # SABOTAGE",
        "suites": ["test_article_picture.py"],
        "why": "a Generate button sits over an article that already carries a "
               "chosen image, which is a way to lose it",
    },
    {
        "name": "a_support_that_links_nowhere_is_flagged",
        "file": "app/keywords.py",
        "find": "        if _links.points_at(bodies[r.output_id], pillar.target_url or \"\"):",
        "replace": "        if True:  # SABOTAGE",
        "suites": ["test_support_links.py"],
        "why": "a support published with no link up is never noticed — and "
               "the publish check could never catch it, because it verifies "
               "the links present RESOLVE and never that a required one is "
               "THERE. The mechanism the whole pillar/cluster model rests on "
               "goes back to being advice",
    },
    {
        "name": "a_support_waiting_on_its_pillar_is_not_an_orphan",
        "file": "app/keywords.py",
        "find": "            and pillars.get(r.cluster_key or \"\") is not None]",
        "replace": "            ]  # SABOTAGE",
        "suites": ["test_support_links.py"],
        "why": "a support whose pillar has no address is reported as failing "
               "to link to a page that has nowhere to be linked to — a queue "
               "of work nobody can do, beside the one row that would fix all "
               "of it",
    },
    {
        "name": "the_supports_band_names_which_ones",
        "file": "app/keywords.py",
        "find": "        if act == \"supports\":",
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_support_links.py", "test_keyword_attention.py"],
        "why": "the band recommends supports and says nothing about which, so "
               "the surface renders a sentence and offers no way to take it "
               "— a fix instruction where a control belongs",
    },
    {
        "name": "a_muted_keyword_is_never_offered_as_a_support",
        "file": "app/keywords.py",
        "find": "                and (r.owner_priority or \"\") != \"muted\"]",
        "replace": "                ]  # SABOTAGE",
        "suites": ["test_support_links.py"],
        "why": "a keyword the owner ruled out comes back in the one-click "
               "control, so a decision they already made has to be made "
               "again every time they look at the board",
    },
    {
        "name": "planned_supports_stop_being_offered",
        "file": "app/web.py",
        "find": "            kwm.upsert(tenant, phrase, status=\"planned\")",
        "replace": "            pass  # SABOTAGE",
        "suites": ["test_support_links.py"],
        "why": "filing without marking, so the same support is offered again "
               "next render and the weekly planner proposes it too — one "
               "keyword, two articles, which is the cannibalisation this "
               "whole lane exists to prevent",
    },
    {
        "name": "one_writer_decides_when_an_article_may_be_planned",
        "file": "app/web.py",
        "find": "        nxt = plm.next_article_slot(win, slot)",
        "replace": "        nxt = slot  # SABOTAGE",
        "suites": ["test_support_links.py"],
        "why": "the console control files past the monthly cap and past the "
               "horizon while its docstring claims otherwise — and because "
               "the overrun persists, the next weekly run reads the month as "
               "full and refuses entirely, so one press silently spends the "
               "planner's whole budget",
    },
    {
        "name": "work_already_planned_is_not_reported_as_missing",
        "file": "app/keywords.py",
        "find": "                if sup[\"in_flight\"]:",
        "replace": "                if False:  # SABOTAGE",
        "suites": ["test_support_links.py"],
        "why": "a cluster whose whole support layer was queued last week "
               "reads as '0 support(s) and none left to write — the map needs "
               "more keywords', sending somebody to harvest keywords for work "
               "that is already scheduled",
    },
    {
        "name": "the_supports_control_is_rendered",
        "file": "app/admin_ui.py",
        "find": "        + (_plan_supports_btn(key, tenant, r) if (r.get(\"supports\") or {})",
        "replace": "        + (\"\" if (r.get(\"supports\") or {})  # SABOTAGE",
        "suites": ["test_support_links.py"],
        "why": "the band's recommendation goes back to being a sentence with "
               "nothing behind it — `_plan_supports_btn` has exactly one "
               "caller, so deleting this deletes the whole control and every "
               "route behind it becomes unreachable",
    },
    {
        "name": "the_board_reads_the_keyword_map_once",
        "file": "app/keywords.py",
        "find": "            sup = cluster_support(tenant, r.cluster_key or \"\", every)",
        "replace": "            sup = cluster_support(tenant, r.cluster_key or \"\")  # SABOTAGE",
        "suites": ["test_board_cost.py"],
        "why": "one full keyword_targets scan per stalled row: 602 queries "
               "and ~10 seconds to render the board on a 600-keyword account, "
               "quadratic in the size of the thing the feature exists to "
               "manage",
    },
    {
        "name": "a_refresh_is_judged_from_its_own_date",
        "file": "app/keywords.py",
        "find": "        (after if at >= split else before).setdefault(r.phrase, r)",
        "replace": "        (after if at >= db.utcnow() else before).setdefault(r.phrase, r)  # SABOTAGE",
        "suites": ["test_refresh_effect.py"],
        "why": "a page refreshed partway through the window is compared "
               "against a reading from before it started drifting, so the "
               "refresh is credited with recovering a fall that happened "
               "before anybody touched it",
    },
    {
        "name": "a_refresh_lift_is_never_claimed_without_a_control",
        "file": "app/keywords.py",
        "find": "                 if judged and c_gains else None),",
        "replace": "                 if judged else None),  # SABOTAGE",
        "suites": ["test_refresh_effect.py"],
        "why": "with no control the raw gain is reported as lift, so a "
               "quarter when the whole site rose reads as refreshing working "
               "— the exact claim `progress` was built to refuse for "
               "publishing, made one section down for refreshes",
    },
    {
        "name": "the_refresh_control_is_a_real_cohort",
        "file": "app/keywords.py",
        "find": "        c_before, c_after = _readings_astride(tenant, {k: mid for k in keys})",
        "replace": "        c_before, c_after = _period_readings(tenant, days)  # SABOTAGE",
        "suites": ["test_refresh_effect.py"],
        "why": "the control splits on the window's edge, whose `then` holds "
               "only readings OLDER than the window — so every control page "
               "lands in one bucket, the cohort is silently zero, and `lift` "
               "is withheld forever for a right-looking wrong reason",
    },
    {
        "name": "an_unsettled_refresh_does_not_carry_the_claim",
        "file": "app/keywords.py",
        "find": "    judged = [m for m in moved if not m[\"too_early\"]]",
        "replace": "    judged = list(moved)  # SABOTAGE",
        "suites": ["test_refresh_effect.py"],
        "why": "a page refreshed three days ago, which Google may not have "
               "re-crawled, is averaged into the attributable result — and a "
               "single unsettled reading can carry the whole claim",
    },
    {
        "name": "a_refresh_that_cannot_be_judged_is_named",
        "file": "app/keywords.py",
        "find": "            blind.append({\"phrase\": phrase, \"days_since_refresh\": age,",
        "replace": "            _ = ({\"phrase\": phrase, \"days_since_refresh\": age,  # SABOTAGE",
        "suites": ["test_refresh_effect.py"],
        "why": "pages with no reading on one side of the refresh vanish from "
               "the report, so a result computed from two pages out of twenty "
               "reads exactly like one computed from all twenty",
    },
    {
        "name": "a_rung_describes_what_it_actually_does",
        "file": "app/systems.py",
        # Flipped to False on 2026-09-02. It set True while the value already
        # WAS True — a no-op that reported MISSED — because the blog now ships
        # on `auto`. The direction that can still be wrong is the card denying
        # a push that really happens.
        "find": "CLEARED_IS_WIRED = _cleared_has_a_consumer() or any(AUTO_SHIPS.values())",
        "replace": "CLEARED_IS_WIRED = False  # SABOTAGE",
        "suites": ["test_rung_truth.py"],
        "why": "the card tells an owner nothing pushes on its own while the "
               "blog is publishing to their client's CMS unattended — the "
               "same defect the derived sentence was added to end, pointing "
               "the other way, and the more dangerous direction of the two",
    },
    {
        "name": "the_rung_sentence_is_derived_not_written",
        "file": "app/systems.py",
        "find": "    return bool(_CLEARED_BRANCH.search(str(text or \"\")))",
        "replace": "    return False  # SABOTAGE",
        "suites": ["test_rung_truth.py"],
        "why": "the scan can no longer find a consumer even when one exists, "
               "so the day somebody wires the push the card goes on saying "
               "nothing sends — the same defect pointing the other way, which "
               "is why a hand-corrected string was not the fix",
    },
    {
        "name": "a_body_picture_comes_from_an_approved_asset",
        "file": "app/skill_pack.py",
        "find": "        if not aid or aid in seen or not (got.get(\"url\") or \"\"):",
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_article_images.py"],
        "why": "a marker with nothing behind it renders an <img> with an "
               "empty src, and the hero is repeated halfway down the page — "
               "the two failures a placement system exists to prevent",
    },
    {
        "name": "an_unfilled_marker_is_removed_and_named",
        "file": "app/skill_pack.py",
        "find": "            wanted.append(subject)\n            return \"\"\n        seen.add(aid)",
        "replace": "            return m.group(0)  # SABOTAGE\n        seen.add(aid)",
        "suites": ["test_article_images.py"],
        "why": "the raw marker survives into the published body and the "
               "picture nobody could supply is never recorded — an account "
               "with no approved photographs publishes scaffolding and hears "
               "nothing about it",
    },
    {
        "name": "an_article_is_not_a_gallery",
        "file": "app/skill_pack.py",
        "find": "        if len(placed) >= MAX_BODY_IMAGES:",
        "replace": "        if False:  # SABOTAGE",
        "suites": ["test_article_images.py"],
        "why": "every marker the drafter felt like leaving becomes a picture, "
               "so one article can carry six and the piece reads as a "
               "slideshow with captions",
    },
    {
        "name": "alt_text_describes_the_picture_that_was_chosen",
        "file": "app/skill_pack.py",
        "find": "        alt = str(got.get(\"alt\") or got.get(\"subject\") or subject)",
        "replace": "        alt = subject  # SABOTAGE",
        "suites": ["test_article_images.py"],
        "why": "a screen reader is told what the WRITER wanted to see rather "
               "than what the picture shows — and the two differ whenever the "
               "ladder picked something adjacent, which is most of the time",
    },
    {
        "name": "a_blocked_article_gets_another_attempt",
        "file": "app/skill_pack.py",
        "find": "             fmt=\"cms_article\", redraft=_repair_article,",
        "replace": "             fmt=\"cms_article\",  # SABOTAGE",
        "suites": ["test_article_repair.py"],
        "why": "the longest thing this system writes — and the only one that "
               "lands on a public page under the client's own domain — is the "
               "one piece that never gets a second attempt: a banned phrase "
               "in paragraph nine blocks the whole article and waits for a "
               "person, at every rung including `auto`, where nobody is "
               "watching",
    },
    {
        "name": "a_retry_is_told_what_broke",
        "file": "app/skill_pack.py",
        "find": "        note = \"\\n\".join(f\"- {f['detail']} → {f['fix']}\" for f in failures)\n        fixed, _ = _draft_article_live(",
        "replace": "        note = \"\"  # SABOTAGE\n        fixed, _ = _draft_article_live(",
        "suites": ["test_article_repair.py"],
        "why": "the article is asked again with no idea what was wrong with "
               "it, so the retry is the same question and burns the attempt "
               "budget producing the same rejection three times",
    },
    {
        "name": "only_the_unattended_rung_repairs_itself",
        "file": "app/skill.py",
        "find": "        may_repair = _rung(self.autonomy) == \"auto\"",
        "replace": "        may_repair = True  # SABOTAGE",
        "suites": ["test_article_repair.py"],
        "why": "a draft on a MANUAL rung silently rewrites itself, hiding the "
               "one thing the person reading it is there to see — which rule "
               "keeps biting, and whether the rule or the brief is what needs "
               "changing. Three quiet repairs a week is a ban list nobody "
               "learns from",
    },
    {
        "name": "a_withheld_repair_says_it_was_withheld",
        "file": "app/skill.py",
        "find": "            self.note(\"blocked, and not repaired automatically: this system is \"",
        "replace": "            pass  # SABOTAGE\n            _ = (\"blocked, and not repaired automatically: this system is \"",
        "suites": ["test_article_repair.py"],
        "why": "a blocked draft on a manual rung is silent about WHY nothing "
               "was retried, so a deliberate rung difference reads as a "
               "broken repairer",
    },
    {
        "name": "a_planner_is_offered_its_own_knobs",
        "file": "app/planner.py",
        "find": "            for k, v in defaults.items() if k in KNOBS]",
        "replace": "            for k, v in []]  # SABOTAGE",
        "suites": ["test_cadence_knobs.py"],
        "why": "the cadence card offers no knobs at all, so the numbers that "
               "decide how much work a planner creates go back to being "
               "unreachable from the console",
    },
    {
        "name": "the_refresh_windows_are_the_accounts_own",
        "file": "app/keywords.py",
        "find": "    settle, cooldown = refresh_windows(tenant)",
        "replace": "    settle, cooldown = REFRESH_AFTER_DAYS, REFRESH_COOLDOWN_DAYS  # SABOTAGE",
        "suites": ["test_cadence_knobs.py"],
        "why": "every account gets the platform's settle time however fast "
               "Google actually crawls their site — and the boxes that set it "
               "still render, still save, and change nothing",
    },
    {
        "name": "a_cadence_knob_out_of_range_is_refused",
        "file": "app/systems.py",
        # Anchored on the CADENCE loop's own line: the range check three
        # lines below is byte-identical to the goal validator's, and an anchor
        # matching two blocks covers neither.
        "find": "        val, cap = values.get(name), spec[\"cap\"]",
        "replace": "        val, cap = values.get(name), 10 ** 9  # SABOTAGE",
        "suites": ["test_cadence_knobs.py"],
        "why": "a 9999-day cooldown is written silently and sits behind the "
               "planner for weeks — the refresh lane stops offering anything "
               "and nothing says why",
    },
    {
        "name": "an_undeclared_cadence_knob_is_not_stored",
        "file": "app/systems.py",
        "find": "    unknown = sorted(k for k in values if k not in _pl.KNOBS)",
        "replace": "    unknown = []  # SABOTAGE",
        "suites": ["test_cadence_knobs.py"],
        "why": "a typo saves into `System.config` and reads back as configuration that "
               "works — config nothing reads is indistinguishable from config "
               "that does",
    },
    {
        "name": "the_auto_rung_actually_ships",
        "file": "app/skill_pack.py",
        "find": "        if publish[\"queued\"] and _sysm.rung(ctx.autonomy) == \"auto\" \\",
        "replace": "        if False and _sysm.rung(ctx.autonomy) == \"auto\" \\",
        "suites": ["test_auto_ships.py"],
        "why": "`auto` goes back to removing the approval and putting nothing "
               "in its place — strictly worse than shadow, because the draft "
               "is finished, nobody is asked, and nothing goes out",
    },
    {
        "name": "only_the_named_systems_ship_unattended",
        "file": "app/systems.py",
        "find": "    return bool(AUTO_SHIPS.get(str(system_key or \"\"), False))",
        "replace": "    return True  # SABOTAGE",
        "suites": ["test_auto_ships.py"],
        "why": "every system pushes on its own at the top rung — including "
               "campaign_email, where the owner said leave it human and where "
               "a send cannot be recalled, and ad_creative, where the promise "
               "is of a spend no code performs",
    },
    {
        "name": "an_unattended_ship_is_marked_as_one",
        "file": "app/approvals.py",
        "find": "            run.decision = \"auto\"",
        "replace": "            run.decision = \"approved\"  # SABOTAGE",
        "suites": ["test_auto_ships.py"],
        "why": "a page published with nobody looking records identically to "
               "one somebody read and approved, so 'how much went out "
               "unattended' is a question with no answer",
    },
    {
        "name": "an_unattended_ship_uses_the_normal_executor",
        "file": "app/approvals.py",
        "find": "    said = apply_decision(ids[0], \"approved\")",
        "replace": "    said = \"skipped\"  # SABOTAGE",
        "suites": ["test_auto_ships.py"],
        "why": "the approval is marked without the executor running, so the "
               "console shows a published article and the CMS never received "
               "one — the write-back, the ledger and supersede all skipped",
    },
    {
        "name": "a_cards_promise_is_scoped_to_its_system",
        "file": "app/systems.py",
        "find": "    if may_auto_ship(system_key):\n        return base",
        "replace": "    if True:  # SABOTAGE\n        return base",
        "suites": ["test_auto_ships.py"],
        "why": "campaign_email's card promises 'Sends without asking' on a "
               "system that deliberately never sends by itself — the platform "
               "answer rendered as the account's",
    },
    {
        "name": "a_schedule_link_lands_on_the_card",
        "file": "app/admin_ui.py",
        "find": "    if plan_id:\n        url += f\"&amp;plan={_esc(plan_id)}\"",
        "replace": "    if False:  # SABOTAGE\n        url += f\"&amp;plan={_esc(plan_id)}\"",
        "suites": ["test_schedule_nav.py"],
        "why": "the Schedule's links go back to dropping you on the system "
               "page — the card carries `id=plan-<id>` and nothing points at "
               "it, so finding the item you clicked means scrolling a "
               "paginated queue",
    },
    {
        "name": "a_named_plan_decides_which_page_opens",
        "file": "app/admin_ui.py",
        "find": "    if plan_id:\n        for i, pl in enumerate(open_plans):",
        "replace": "    if False:  # SABOTAGE\n        for i, pl in enumerate(open_plans):",
        "suites": ["test_schedule_nav.py"],
        "why": "the deep link lands on page one while the card it names is "
               "three pages down, which reads as a link that does not work "
               "rather than as pagination",
    },
    {
        "name": "the_schedule_defaults_to_date",
        "file": "app/admin_ui.py",
        "find": "SCHEDULE_SORT_DEFAULT = \"when\"",
        "replace": "SCHEDULE_SORT_DEFAULT = \"state\"  # SABOTAGE",
        "suites": ["test_schedule_nav.py"],
        "why": "the table opens ordered by state again — right for triage, "
               "wrong for reading a calendar, and the owner asked for date",
    },
    {
        "name": "a_sortable_heading_actually_sorts",
        "file": "app/admin_ui.py",
        "find": "    _key = SCHEDULE_SORTS[sort][1]",
        "replace": "    _key = SCHEDULE_SORTS[\"when\"][1]  # SABOTAGE",
        "suites": ["test_schedule_nav.py"],
        "why": "every column heading is clickable and none of them changes "
               "the order — a control that reports a failure by doing "
               "nothing visible",
    },
    {
        "name": "every_attention_state_is_drawn_distinctly",
        "file": "app/admin_ui.py",
        "find": "        \"no_reading\": (\"nb\", \"no reading\"),",
        "replace": "        \"no_reading\": (\"gap\", \"stalled\"),  # SABOTAGE",
        "suites": ["test_keyword_attention.py"],
        "why": "two of the four states render byte-identically, so a page "
               "with no Search Console reading — an INDEXING question — is "
               "drawn as one that stalled, and the reader is sent to rewrite "
               "a page that may not be indexed",
    },
    {
        "name": "the_gap_note_links_somewhere_real",
        "file": "app/admin_ui.py",
        "find": "    sep = \"&amp;\" if \"?\" in str(where or \"\") else \"?\"",
        "replace": "    sep = \"?\"  # SABOTAGE",
        "suites": ["test_publish_gap.py"],
        "why": "the fix link becomes `/admin/ui?tab=accounts?key=…`, which "
               "parses as one parameter whose value is `accounts?key=…` — so "
               "the click lands on no tab and carries no key, and reads as a "
               "sign-in bounce rather than as a broken link",
    },
    {
        "name": "a_stuck_plan_leads_whatever_the_sort",
        "file": "app/admin_ui.py",
        "find": "    rows.sort(key=lambda e: (0 if e[0] == 0 else 1, _key(e)), reverse=desc)",
        "replace": "    rows.sort(key=_key, reverse=desc)  # SABOTAGE",
        "suites": ["test_schedule_nav.py", "test_plan_tab.py"],
        "why": "the one row anybody has to act on — a plan that reads as "
               "queued and is not moving — drops into the middle of the "
               "table the moment somebody sorts by a column, which is what "
               "the sort was added for",
    },
    {
        "name": "a_repaired_article_still_gets_its_pictures",
        "file": "app/skill_pack.py",
        "find": "        fixed, _again, _still_wanted = place_images(",
        "replace": "        _again, _still_wanted = [], []; _skip = place_images(",
        "suites": ["test_article_images.py", "test_article_repair.py"],
        "why": "a repaired article ships the raw `<!--IMAGE: …-->` markers "
               "and no pictures — and repair runs only on `auto`, the rung "
               "that publishes to the client's site with nobody looking, so "
               "the scaffolding goes live unread",
    },
    {
        "name": "the_keyword_learns_its_output_before_the_push",
        "file": "app/skill_pack.py",
        "find": "    if row is not None:\n        kw_mod.upsert(ctx.tenant, keyword, run_id=ctx.run_id,",
        "replace": "    if False:  # SABOTAGE\n        kw_mod.upsert(ctx.tenant, keyword, run_id=ctx.run_id,",
        "suites": ["test_auto_ships.py"],
        "why": "`mark_published` joins on `KeywordTarget.output_id`, so on "
               "`auto` — where the ship happens inside the same run — it "
               "finds no row and writes nothing: the page goes live on the "
               "client's site while the map still reads planned, with no "
               "address and no platform id. Live, unlinkable, unmeasurable, "
               "and silent",
    },
    {
        "name": "a_winning_page_keeps_its_high_water_mark",
        "file": "app/keywords.py",
        "find": "            if pos <= WON_POSITION and row.status in (\"published\", \"planned\",\n                                                      \"won\"):",
        "replace": "            if pos <= WON_POSITION and row.status in (\"published\", \"planned\"):",
        "suites": ["test_keyword_attention.py"],
        "why": "a page already at `won` never records `won_at`, so when it "
               "slips it reads as one that never ranked — and those owe "
               "different work, with the more urgent one invisible",
    },
    {
        "name": "the_settings_card_speaks_for_its_own_system",
        "file": "app/admin_ui.py",
        "find": "f'{_esc(systems.autonomy_meaning(current, system_key))}'",
        "replace": "f'{_esc(systems.AUTONOMY_MEANING.get(current, \"\"))}'",
        "suites": ["test_auto_ships.py"],
        "why": "the settings card promises campaign_email \"Sends without "
               "asking\" on a system `AUTO_SHIPS` deliberately holds back — "
               "the platform's answer rendered as the account's, next to the "
               "button that promotes it",
    },
]


#: Answered once per suite, not once per guard: 324 guards name 83 suites.
_BASELINE: dict[str, bool] = {}


def run_suite(name: str) -> bool:
    """True if the suite PASSED, judged by its EXIT CODE.

    This read two strings out of stdout — "all checks passed" or "all green" —
    which is `SYSTEMS-REFERENCE` §6's string-matching-instead-of-state-checking
    rule, broken by the file whose whole job is to prove the rules are kept.

    Eight suites print neither. `test_open_defects.py` ends "all 6 defects
    still open"; `test_render_smoke.py`, `test_moments.py`, `test_strategy.py`
    and three more end on lines of their own; two named suites do not exist at
    all any more. So `run_suite` could never see any of them pass, `noticed`
    was non-empty no matter what the mutation did, and **42 of 324 guards
    printed `[ caught ]` unconditionally** — including the one guarding the
    open-defect ledger, the suite whose entire purpose is to fail on good news.

    `test_all.sh` has judged these same 135 suites by exit code since it was
    written, and it is green, so the exit codes are the contract already.
    """
    p = subprocess.run([sys.executable, f"scripts/{name}"], cwd=ROOT,
                       capture_output=True, text=True, timeout=600)
    return p.returncode == 0


def baseline(name: str) -> bool:
    """Does this suite pass on the UNMUTATED tree?

    Without this, "the suite failed after the mutation" is not evidence: a
    suite that was already failing — or that cannot be run at all — fails
    afterwards too. `[ caught ]` has to be earned against a green baseline or
    it is the same decoration as `MISSED`, pointing the other way.
    """
    if name not in _BASELINE:
        _BASELINE[name] = run_suite(name)
    return _BASELINE[name]


def main(only: str = "") -> int:
    entries = [s for s in SABOTAGES if not only or s["name"] == only]
    if only and not entries:
        print(f"no sabotage named {only!r}. Known: "
              + ", ".join(s["name"] for s in SABOTAGES))
        return 2

    undetected, stale, unproven = [], [], []
    for s in entries:
        path = ROOT / s["file"]
        if not path.exists():
            print(f"[UNPROVEN] {s['name']:24} — {s['file']} does not exist")
            unproven.append(s["name"])
            continue
        original = path.read_text()

        # The baseline FIRST: a suite that is red (or absent) before the
        # mutation cannot testify about it afterwards.
        red = [n for n in s["suites"] if not baseline(n)]
        if red:
            print(f"[UNPROVEN] {s['name']:24} — {', '.join(red)} does not pass "
                  f"before the mutation, so failing after it proves nothing")
            print(f"            claimed to guard: {s['why']}")
            unproven.append(s["name"])
            continue

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
    if undetected or stale or unproven:
        if unproven:
            print(f"{len(unproven)} guard(s) UNPROVEN: " + ", ".join(unproven))
            print("Their suite does not pass before the mutation, so the "
                  "[ caught ] they used to print was unconditional.")
        if undetected:
            print(f"{len(undetected)} guard(s) NOT covered by their suites: "
                  + ", ".join(undetected))
            print("Each one can be removed today and nothing will say so.")
        if stale:
            print(f"{len(stale)} sabotage(s) STALE: " + ", ".join(stale))
            print("The code moved. Re-point them or the coverage is imaginary.")
        return 1
    print(f"all {len(entries)} guards are genuinely tested "
          f"(each against a green baseline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
