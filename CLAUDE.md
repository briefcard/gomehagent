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
- `command_agent.py` — conversational WhatsApp agent + tool dispatch.
- `ops_jobs.py` — on-demand/scheduled jobs (doc_sweep, organize, refile,
  audit, daily_review, sync_catalog…).
- `skills.py` — playbook skills (tax export, invoice chase, business pulse,
  meeting_scan, contract expiry, duplicate cleanup, spend flags).
- `memory.py` — conversation history, working memory, shared LESSONS, doc
  recall, shipments block.
- `approvals.py` — approval queue + execution + autonomy stats.
- `whatsapp.py` — Cloud API send/receive, template fallback, reply-quote map.
- `data_tools.py` — Shopify, Drive search, email/contact search, RFQ, registry.
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
- **NEXT MAJOR STEP: kernel extraction** — pull DNA + memory + channels into a
  `kernel` module; make the admin agent the first Role config; then new agents
  are config + tool pack, never a fork. Do this before building agent #2.
- Financial spine (QuickBooks/Wave/Stripe/PayPal) deferred per Gomeh — unlocks
  tax export, invoice chasing, landed cost, business pulse depth.

## WhatsApp multi-agent
Webhook payload has `value.metadata.phone_number_id` → route to the right agent
by number. One number per agent (test number runs one). Self-hosted per agent.
