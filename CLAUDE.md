# CLAUDE.md — Project memory & build handoff

This file orients any new Claude Code / Cowork session on this repo so it can
continue the build without re-deriving context. Read it first.

## What this is
An always-on, self-hosted operations agent on Render for three businesses —
Baci Milano USA (imports/wholesale/e-com), Eien Distributions / Eien Health
(e-com), Saias Consulting (marketing). Operated by WhatsApp (text, voice,
forwarded files). Built on the Claude API. State in Postgres.

## Repo / deploy
- GitHub: briefcard/gomehagent (main branch auto-deploys to Render).
- Services: `assistant-web` (FastAPI webhook/approvals) + `assistant-worker`
  (scheduler/poller), one Postgres. See `render.yaml`.
- `app/config.py` reads ALL settings from env vars (see `.env.example`).
- Verify after changes: `python -m py_compile app/*.py`. Health:
  `/health` and `/health/connections`. Cost: `/admin/usage?key=APPROVAL_SECRET`.

## Module map (`app/`)
- `config.py` — env config, buckets, model routing, per-agent settings.
- `db.py` — SQLAlchemy models + **auto-migration on startup** (adds missing
  columns to existing tables — never breaks on a new field).
- `gmail_client.py` — multi-account Gmail; **all Google calls serialized behind
  one lock** (httplib2 isn't thread-safe → segfaults otherwise).
- `drive_io.py` — Drive read/write/move/sheets (shares the Google lock).
- `triage.py` — email triage agent (buckets, drafts, grounding, foresight).
- `kernel.py` — **the agent kernel**: behavioral DNA (shared, identical for
  every agent), the `Role` schema, and the agentic tool-use loop + prompt
  caching. New agents = a Role config + a tool pack, never a fork.
- `roles/` — one Role object per agent. `roles/admin.py` (agent #1) and
  `roles/seo.py` (agent #2); `roles/__init__.py` is the registry (`get(name)`).
- `command_agent.py` — the **admin tool pack**: ACTION_TOOLS + `admin_dispatch`.
  `handle()` is now a thin shim that runs the admin role through the kernel.
- `seo_tools.py` — the **SEO tool pack** (role: seo): native Semrush Analytics
  client (overview, top keywords, competitors, keyword/related/questions metrics,
  opportunity finder) + the snapshot/progress self-analysis loop + the Shopify
  propose_* implementation tools + dispatch.
- `sites.py` — **multi-client/multi-platform layer for the SEO role**: site
  profiles (primary from SEO_* + `SEO_SITES_JSON`), `backend()` resolver
  (shopify_seo | wordpress_seo), shared structured-snippet builders (faq_html /
  compose_jsonld / jsonld_script), and `verify_links()` — the grounding check
  that HTTP-validates every link resolves on the real site before publishing.
- `shopify_seo.py` / `wordpress_seo.py` — the two **platform backends** (same
  function surface: list_collections, find_items, get_seo, update_seo,
  create_collection, create_page, install_schema_renderer). Shopify: JSON-LD via
  the `seo.structured_data` metafield + a one-time theme snippet (INLINE_JSONLD
  False). WordPress: WP REST API + native Application Passwords, JSON-LD inlined
  in content (INLINE_JSONLD True), SEO handled with NATIVE fields (title tag from
  the post title, meta description from the excerpt) — NO SEO plugin required;
  Yoast/RankMath meta set only as a best-effort bonus if REST-exposed. Writes run
  only from the approval executor (`seo_update` / `seo_new_collection` /
  `seo_new_page` / `shopify_theme_asset` kinds).
- `ops_jobs.py` — on-demand/scheduled jobs (doc_sweep, organize, refile,
  audit, daily_review, sync_catalog…).
- `skills.py` — playbook skills (tax export, invoice chase, business pulse,
  meeting_scan, contract expiry, duplicate cleanup, spend flags).
- `memory.py` — conversation history (PER-THREAD: each agent has its own chat
  thread via `ChatMessage.thread`, so admin and seo never share context; pass a
  sub-thread like `seo:eien` for independent parallel convos), working memory,
  shared LESSONS, doc recall, shipments block. Working memory + lessons stay
  shared across agents by design; only the raw conversation is isolated.
- `approvals.py` — approval queue + execution + autonomy stats.
- `whatsapp.py` — Cloud API send/receive, template fallback, reply-quote map.
- `data_tools.py` — Shopify, Drive search, TIERED email search (Jul 2026:
  count→metadata→relevance-filter→bounded deep read, coverage receipts, honors
  window_days scope), read_email / read_email_attachment (on-demand PDF text
  via pypdf), contacts, RFQ, registry.
- `systems_map.py` — the SYSTEMS MAP (Jul 2026): durable docs on how Gomeh's
  world is organized (SystemDoc: 'drive:<account>' taxonomies from the
  map_drive job, 'conventions:filing', 'project:<name>'). Injected compactly
  every turn by the kernel (pinned docs full, rest as index); agents READ
  BEFORE WRITE for any organizing and systems_update after. Also the
  FeatureRequest queue (request_feature tool, /admin/features endpoint, weekly
  systems_review cron) — agents file their own limitations; implement the top
  ones in a dev session. Adoption of new structure = approval kind
  'systems_update'.
- `emailfmt.py` — HTML email formatting. `usage.py` — token/cost logging.

## Behavioral DNA (the "trainings" — NEVER drop these; they belong in the kernel)
1. **Approval gating** — money & irreversible actions wait for Gomeh's tap.
2. **Action confirmation** — never claim done unless a tool confirmed it.
3. **Grounding** — facts only from tools/thread; no fabrication; no placeholders.
4. **Proactivity / data-foresight** — gather data → act → suggest next → offer.
5. **Clarify-before-bulk** — ask when a key parameter is ambiguous.
6. **Big-task protocol** — acknowledge, be exhaustive, report coverage, close loops.
7. **Context discipline** — recency anchoring; resolve WhatsApp reply-quotes.
8. **Filing** — read file contents (primary evidence); one order = one folder;
   8–15 folders not per-file; OLD VERSIONS; never delete; dedup by content hash.
9. **Three accounts never mixed** (baci/eien/personal).
10. **Refund ladder** — push back first; never say "processed" before it is.
11. **Learning** — deny→voice rule (per inbox); generalizable→shared Lesson
    (all agents). Memory + records over free recall.
12. **Per-inbox/brand voice**, signatures, no false "attached" claims.
Infra inheritances: prompt caching (static system + tools cached), model
routing (Haiku classify / Sonnet draft / Opus high-stakes), ordered single
command queue, webhook dedup, auto-migration, usage logging.

## Conventions
- Add a DB field → just add the column to the model; auto-migration applies it.
- New capability → add a tool in command_agent + handler; or a job in ops_jobs;
  or a playbook in skills.py. Keep outputs concrete (numbers/links), proactive.
- All Google API access must go through gmail_client/drive_io (the locked layer).
- Every Claude call: log usage; cache static prefixes + tools.
- Test: `python -m py_compile app/*.py` + a focused `python -c` assertion.

## Roadmap (see /outputs design docs)
- **Multi-Agent-Architecture.md** — kernel+role split; cross-agent lessons.
- **Admin-Agent-Skills-Catalog.md** — built vs proposed admin skills (all built).
- **Search-Ads-Agent-Plan.md** — next agent (SEO/GEO/search ads), skills, kernel
  inheritance, Insight Bus for cross-agent collaboration.
- **Kernel extraction — DONE (Jun 2026).** DNA + the agentic loop live in
  `kernel.py`; admin is the first Role (`roles/admin.py`); `command_agent.py` is
  now just the admin tool pack + a `handle()` shim. Admin behavior unchanged
  (composed prompt = kernel DNA + admin identity, a superset of the old one).
- **SEO agent v1 — DONE (Jun 2026).** Agent #2 stood up as pure config + tool
  pack (no fork): `roles/seo.py` + `seo_tools.py` (native Semrush) + `SeoSnapshot`
  + a weekly snapshot job in `worker.py`. Reachable now via
  `/admin/ask?key=…&role=seo&q=…`; target = Baci Milano USA. Needs `SEMRUSH_API_KEY`.
  Validated against live Semrush: Baci ~104 organic kw, ~16 traffic/mo — near
  greenfield, with page-2/3 quick-win keywords the opportunity finder surfaces.
  The agent also IMPLEMENTS (approval-gated): reads the live site and proposes
  SEO edits, new collections/landing pages, and content pages with structured
  snippets (FAQ HTML + JSON-LD) — nothing publishes until Gomeh approves, and
  every link is HTTP-verified against the real site first (no hallucinated URLs).
- **SEO agent is multi-client / multi-platform.** One role serves many sites via
  site profiles (sites.py): Baci + Eien on Shopify, MarketingThatWorks on
  WordPress, more via SEO_SITES_JSON. Research (Semrush) is shared; implementation
  routes to a per-platform backend. Per-site brand guardrails (e.g. Baci =
  Italian-DESIGNED, never "made in Italy") live in each profile, never mixed.
- **SEO agent — GSC + GA4 ground truth — DONE (Jun 2026).** `google_seo.py` adds
  Search Console (gsc_top_queries/top_pages/page_queries/trend/inspect_url) and
  GA4 (ga4_overview/landing_pages) read tools through the **locked Google layer**
  (gmail_client._google_lock). Per-site config: google_alias / gsc_site /
  ga4_property. Needs the `webmasters.readonly` + `analytics.readonly` scopes —
  re-run `scripts/google_oauth.py` (delete accounts.json first to re-consent) and
  update GMAIL_ACCOUNTS_JSON. The role now leads with GSC/GA4 truth and uses
  Semrush for the wider opportunity.
- **Quality hardening (Jun 2026).** (1) Working memory is now SCOPED per agent —
  `Memory.scope` ('global' | role); `memory_block(role)` = global + own, so agents
  don't contaminate each other (conversation already isolated per thread; lessons
  already scoped). save_memory takes `shared` for cross-cutting facts. (2) GSC/GA4
  auto-binding is CONFIDENT-ONLY — exact/unique match required (GA4 by web-stream
  URL), ambiguity refuses to bind and surfaces candidates to pin (no silent
  wrong-property data). (3) Role gains per-role `max_tokens`/`max_steps`; SEO runs
  on Opus (4000 tok / 16 steps) and is told to save project state to survive the
  short window. (4) Site profiles gain a `guardrail` field (e.g. Eien = no medical
  claims) injected prominently and obeyed strictly.
- **SEO agent — next:** gated search-ads execution; the Insight Bus
  (Search↔Social); a dedicated WhatsApp number. See docs_Search-Ads-Agent-Plan.md.
- Financial spine (QuickBooks/Wave/Stripe/PayPal) deferred per Gomeh — unlocks
  tax export, invoice chasing, landed cost, business pulse depth.

## WhatsApp multi-agent — ONE number, every agent (Jun 2026)
No per-agent phone numbers. `command_agent.handle()` is a ROUTER: a slash command
`/<agent>` (`/seo`, `/admin`, or `/seo <client>` for a sub-thread) switches the
active agent, persisted in `Setting["wa_active"]`; all other messages route to the
active agent on its own conversation thread. `/agents` shows the menu + current.
`force_role=` bypasses the router for internal admin-only calls (draft-edit).
Per-thread isolation (`ChatMessage.thread`) means agents never share context.
HTTP `/admin/ask?role=&thread=` is the equivalent explicit selector. (The
phone_number_id-per-agent path from the plan is still available later if a number
is ever provisioned, but isn't needed.)
