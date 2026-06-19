# SEO/GEO Agent — Build, Setup & Handoff

*Self-contained context for a fresh Claude Code / Cowork thread. Read this +
`CLAUDE.md` and you have the whole picture. Built Jun 2026 on branch
`seo-agent/kernel-extraction`.*

---

## 0. STATUS & OPEN ISSUES (read this first)

The SEO agent (agent #2) is **built, verified, merged, and pushed to `main`**.
All code is live on `main = 05740d7` (a merge that keeps BOTH the full SEO agent
AND the email-CC feature — see the incident note below). What remains is **Render
operational config**, not code.

- Repo: `briefcard/gomehagent` (main auto-deploys to Render). Local clone:
  `/Users/gomehsaias/Documents/gomehagent`, branch `seo-agent/kernel-extraction`
  (its tip == `main`).
- New tables (`seo_snapshots`, `seo_site_config`) + columns (`chat_messages.thread`,
  `memories.scope`) **auto-create on startup** (db `_auto_migrate`). No migration.

### Push access — a fresh thread CAN push changes live (deploy = push to main)
A dedicated SSH **deploy key** (write-enabled, added to the repo's Deploy keys on
GitHub) lets this environment push non-interactively — the macOS keychain blocks
headless HTTPS auth, so HTTPS pushes fail with "could not read Username". Already
wired:
- `origin` in THIS clone = `git@github-gomehagent:briefcard/gomehagent.git`
  (use this clone, `/Users/gomehsaias/Documents/gomehagent`; a fresh clone would be
  HTTPS — re-point it with `git remote set-url origin git@github-gomehagent:briefcard/gomehagent.git`).
- `~/.ssh/config` has a `Host github-gomehagent` alias → `IdentityFile ~/.ssh/gomehagent_deploy`.
- Local `git config user.email/name` is set (commits need it).
- In Claude Code, run git network commands with **sandbox disabled**
  (`dangerouslyDisableSandbox: true`) so the SSH key is reachable — otherwise SSH
  returns "Permission denied (publickey)".

Deploy: `git fetch origin` (ALWAYS first — `main` gets pushed by other clones), then
`git push origin seo-agent/kernel-extraction:main` (fast-forwards `main` → Render
auto-deploys). If `main` diverged, integrate before pushing. Verify auth anytime:
`ssh -T git@github-gomehagent` → "Hi briefcard! You've successfully authenticated".

### OPEN operational issues to resolve (in order)
1. **Wrong/suspended Render URL.** `assistant-web.onrender.com` serves "This service
   has been suspended by its owner" — it's a **stale/duplicate** service. The ACTIVE
   service is at a DIFFERENT URL (WhatsApp gets replies, so the live one is real).
   FIX: in the Render dashboard open the active `assistant-web`, copy its real
   `.onrender.com` URL, delete the suspended duplicate, and update **`PUBLIC_BASE_URL`**
   to the real URL (approval links use it — they're currently pointing at the dead one).
2. **SEO env values likely pruned.** `render.yaml` now DECLARES the SEO vars in the
   `assistant-env` group, but the secret ones are `sync:false` (values live in the
   dashboard) and were probably wiped when the SEO work got reverted (issue below).
   RE-SET in the dashboard from the unified block in `.env.example`: `SEMRUSH_API_KEY`,
   `SHOPIFY_STORES_JSON` (baci+eien), `SEO_SITES_JSON` (baci/eien/mtw), `WORDPRESS_SITES_JSON`.
   (`SEO_MODEL`/`SEO_GOOGLE_ALIAS`/`SEO_PRIMARY_SITE` are auto-set by render.yaml.)
3. **Verify with the diagnostic:** `https://<REAL-URL>/health/seo?key=APPROVAL_SECRET`
   — shows exactly what the deployed service sees: registered roles (must include
   `seo`), `whatsapp_active_agent`, `semrush_key_set` + live `semrush_probe`, loaded
   `sites`, Shopify/WP store keys. This removes all guesswork — run it FIRST.
4. **Google (GSC/GA4) setup:** delete `accounts.json`, re-run `scripts/google_oauth.py`
   to re-consent `personal` (now requests `webmasters.readonly` + `analytics.readonly`),
   paste new `GMAIL_ACCOUNTS_JSON`; **enable 3 GCP APIs** (Search Console, Analytics
   Data, Analytics Admin); add `gomehsaias@gmail.com` as a user on each site's GSC +
   GA4 property. Then GSC/GA4 tools auto-discover the property by domain.
5. **`SEO_MODEL` is pinned to `claude-sonnet-4-6`** (render.yaml) because
   `claude-opus-4-8` returned a 400 `BadRequestError` on this API key — if Opus is
   wanted, confirm the exact model id available to the key, then override `SEO_MODEL`.

### ⚠ INCIDENT to be aware of (don't repeat)
A CC-support commit (`44302aa`) was pushed to `main` from a **pre-SEO base**, which
**reverted** the entire SEO integration (config, db schema, memory scoping, OAuth
scopes, the router) while adding CC. It was reconciled in `05740d7` (kept both). 
LESSON: any new work MUST branch from current `main` and `git fetch` before pushing,
or it can silently revert the other agent's work. The deployed agent showing "no SEO
tools / send a CSV" was a symptom of this revert, not a code bug.

### How to test once Render config is fixed
On WhatsApp: `/agents` (confirm router live) → `/seo` (or `/baci`) → a Semrush-only
ask like "for baci, show our page-2/3 quick-win keywords from Semrush." GSC/GA4
stay dark until step 4 is done.

---

## 1. What this is

Always-on ops agent platform on Render for Baci Milano USA, Eien Health, and
Saias Consulting. Agent #1 = **admin** (email/orders/docs/logistics). Agent #2 =
**seo** (SEO/GEO + on-site implementation). Both are the **same kernel** wearing
a different **Role** (config + tool pack, never a fork). Built on the Claude API,
state in Postgres, operated by WhatsApp + an HTTP endpoint.

---

## 2. Architecture (what changed in this build)

- **Kernel + Roles.** `app/kernel.py` owns the behavioral DNA + the agentic loop;
  `app/roles/` holds one `Role` per agent (`admin.py`, `seo.py`) + the registry
  (`__init__.py`, exposes `ROLES` + `get(name)`). `Role` carries identity, tool
  pack, model, and per-role `max_tokens`/`max_steps`.
- **One WhatsApp number routes to all agents.** `command_agent.handle()` is a
  router: `/seo`, `/admin`, or `/seo <client>` switches the active agent
  (persisted in `Setting["wa_active"]`); other messages go to the active agent on
  its own thread. `/agents` shows the menu. `force_role=` pins internal admin-only
  calls (draft-edit). HTTP equivalent: `/admin/ask?role=&thread=&q=`.
- **Per-thread conversation isolation.** `chat_messages.thread` scopes history;
  each agent (and optional sub-thread like `seo:eien`) keeps its own context. No
  cross-agent bleed. Window is bounded (16 turns / 3 days), so context never grows
  unbounded.
- **Scoped working memory.** `memories.scope` ('global' | role); each agent sees
  global + its own (`memory_block(role)`). `save_memory` defaults to the agent's
  scope; `shared=true` for cross-cutting facts. Lessons already scoped (global|role).
- **Multi-site / multi-platform.** `app/sites.py` = site profiles + `backend()`
  resolver + shared snippet builders + `verify_links()`. Backends:
  `app/shopify_seo.py` and `app/wordpress_seo.py` (same function surface).
- **Tool packs.** `app/seo_tools.py` (Semrush + GSC/GA4 routing + snapshots +
  Shopify/WP propose tools + dispatch). `app/google_seo.py` (GSC/GA4 via the
  LOCKED Google layer `gmail_client._google_lock`).

### Module map (SEO-relevant)
| File | Role |
|---|---|
| `app/kernel.py` | DNA + agentic loop; `Role` dataclass (now with max_tokens/max_steps) |
| `app/roles/seo.py` | SEO role config (identity, model, caps, context) |
| `app/seo_tools.py` | SEO tool pack (29 tools) + `dispatch` |
| `app/google_seo.py` | GSC + GA4 read layer (locked Google lane) + property auto-discovery |
| `app/sites.py` | site profiles, backend resolver, `verify_links`, snippet builders |
| `app/shopify_seo.py` | Shopify backend (metafield JSON-LD + theme renderer) |
| `app/wordpress_seo.py` | WordPress backend (native title/excerpt + inline JSON-LD; no SEO plugin needed) |
| `app/memory.py` | per-thread chat history + scoped working memory |
| `app/command_agent.py` | admin tool pack + the WhatsApp multi-agent **router** |
| `app/db.py` | + `SeoSnapshot`, `SeoSiteConfig`; `ChatMessage.thread`, `Memory.scope` |
| `app/approvals.py` | executors for `seo_update`/`seo_new_collection`/`seo_new_page`/`shopify_theme_asset` |
| `app/web.py` | `/admin/ask?role=&thread=` + WhatsApp webhook |
| `scripts/google_oauth.py` | + webmasters.readonly + analytics.readonly scopes |

---

## 3. The SEO agent's 29 tools

- **Research (Semrush):** semrush_domain_overview, semrush_top_keywords,
  semrush_competitors, semrush_keyword_metrics, semrush_related_keywords,
  semrush_questions, semrush_opportunity_finder.
- **Ground truth (GSC/GA4):** gsc_top_queries, gsc_top_pages, gsc_page_queries,
  gsc_trend, gsc_inspect_url, ga4_overview, ga4_landing_pages, gsc_list_sites,
  ga4_list_properties, seo_link_google.
- **Measurement loop:** seo_snapshot (weekly cron), seo_progress.
- **Site read / grounding:** list_collections, find_items, get_seo, verify_links.
- **Implementation (approval-gated):** propose_seo_update, propose_new_collection,
  propose_content_page, propose_theme_schema_renderer.
- **Memory:** save_memory, forget_memory.

Writes never publish until Gomeh approves; every link is HTTP-verified against the
real site first; content ships with FAQ HTML + JSON-LD structured snippets.

---

## 4. Environment variables (UNIFIED layout)

Define **every client** (primary included) in `SEO_SITES_JSON`; the flat `SEO_*`
vars are only a fallback for the primary. Full reference + paste-ready values in
**`.env.example`**. Minimal set:

```
SEMRUSH_API_KEY=...                 # required (research)
SEO_GOOGLE_ALIAS=personal           # one Google account granted into each property
SEO_PRIMARY_SITE=baci               # default site key
SEO_MODEL=                          # blank = Opus; set claude-sonnet-4-6 to cut cost
SEO_SITES_JSON={"baci":{...},"eien":{...},"mtw":{...}}   # all clients (see .env.example)
SHOPIFY_STORES_JSON={"baci":{...},"eien":{...}}          # shared with admin agent
WORDPRESS_SITES_JSON={"mtw":{"base_url":"...","user":"...","app_password":"..."}}
# Optional safety-net fallback for the primary: SEO_DOMAIN=bacimilanousa.com SEO_STORE=baci
```
Reused (already on Render): `ANTHROPIC_API_KEY`, `GOOGLE_CLIENT_ID/SECRET`,
`GMAIL_ACCOUNTS_JSON`, `DATABASE_URL`, `APPROVAL_SECRET`, `PUBLIC_BASE_URL`,
`WHATSAPP_*`.

**JSON rule:** inside `SEO_SITES_JSON`, write guardrail/voice WITHOUT double quotes
or it breaks (a broken value drops all sites → validate before pasting).

---

## 5. Setup steps still required on the user's side

1. **Google scopes:** delete `accounts.json`, re-run `python scripts/google_oauth.py`,
   re-consent the **personal** account (now requests `webmasters.readonly` +
   `analytics.readonly`), paste the new `GMAIL_ACCOUNTS_JSON` into Render.
2. **Enable 3 GCP APIs** (same project as `GOOGLE_CLIENT_ID`): Search Console API,
   Google Analytics Data API, Google Analytics Admin API. (Re-auth grants scopes;
   it does NOT enable APIs — a missing one returns 403 `SERVICE_DISABLED`.)
3. **Grant `gomehsaias@gmail.com`** as a user on each client's GSC property + GA4
   property (Baci, Eien, MTW). The agent auto-discovers which property is which.
4. **WordPress:** create a WP Application Password for MTW; fill `WORDPRESS_SITES_JSON`.
5. **Shopify:** confirm `SHOPIFY_STORES_JSON` has both `baci` and `eien`.
6. Set the env vars (Section 4) and deploy (Section 0).

---

## 6. How to operate

- **WhatsApp (one number):** `/agents` shows the menu + current agent. `/admin`
  and `/seo` switch agents; **`/baci` `/eien` `/mtw`** (any SEO site key) switch to
  the SEO agent on that client; `/seo <client>` also works. Then chat normally in
  plain English ("take a look at Eien, where are our quick wins?") — never name
  tools; the agent picks them. Brand guardrails are automatic per site. Admin keeps
  sending its own alerts/approvals regardless of which agent you're chatting with
  (they come from the worker process). The switch persists (Setting `wa_active`).
- **HTTP:** `GET /admin/ask?key=APPROVAL_SECRET&role=seo&thread=<client>&q=<question>`.
- **Diagnostics:** `/health/seo?key=APPROVAL_SECRET` (effective SEO config the live
  service sees) and `/health/connections` (Shopify/Google live tests).
- **Approvals:** every change the agent proposes lands in the approval queue
  (email/WhatsApp). Approve to publish. One-time per Shopify store: approve
  "install the structured-data theme renderer" so JSON-LD renders.

---

## 7. Quality hardening already done (Jun 2026)

1. Working memory **scoped per agent** (no cross-agent contamination).
2. GSC/GA4 auto-binding is **confident-only** — refuses ambiguous matches, surfaces
   candidates to pin via `seo_link_google` (no wrong-property data).
3. **Opus** for SEO + higher caps (4000 tok / 16 steps) + save-state discipline in
   the identity (long-horizon work survives the short window).
4. **Per-site guardrails** enforced (Eien = no medical claims; Baci = no made-in-
   Italy / handmade / artisanal / craftsmanship claims) via `guardrail` field +
   `exclude_terms`.

## 8. Known remaining issues (not blocking)

- **Resource contention:** one Google lock + one WhatsApp consumer thread → a heavy
  SEO turn can delay admin replies; GA4 discovery can be slow. Fine at low volume;
  separate workers later if needed.
- **Misrouting:** after `/seo` you stay on SEO until `/admin` — easy to forget.
  Consider echoing the active agent in replies.
- **Link-verify edge:** a new page linking to another page created in the same
  batch will false-"break" (the target isn't live yet); plus latency if the site
  is slow.
- **GSC/GA4 latency:** ~2-3 day data lag; "last 28 days to today" includes empty
  recent days (don't misread as decline).

---

## 9. Roadmap / next

- Gated **search-ads execution** (Google/Bing/Meta) — deferred per the plan.
- **Insight Bus** (Search ↔ a future social/TikTok agent) — shared table.
- **GSC into the weekly snapshot** (real clicks over time alongside Semrush).
- **Dedicated WhatsApp number** per agent (routing-by-`phone_number_id` already in
  the design) — optional; the one-number router covers it for now.
- Address the Section 8 items if volume grows.
See `docs_Search-Ads-Agent-Plan.md` for the full skill list & rationale.

---

## 10. Hard constraints / decisions (do not regress)

- **Baci is Italian-DESIGNED and mass-manufactured** — never claim/imply made in
  Italy, handmade, artisanal, hand-painted, or craftsmanship (legal/ad risk).
  Encoded in the Baci profile's `exclude_terms` + `guardrail` and `roles/seo.py`.
- **Eien is health/YMYL** — no medical claims; compliant wellness language only.
- **Grounding:** never claim a ranking moved or content published unless a tool
  confirmed it; never publish a link that doesn't resolve.
- **Approval gating:** no publish / no spend without Gomeh's tap.
- **All Google API calls go through `gmail_client._google_lock`** (httplib2 isn't
  thread-safe → segfault otherwise).
- **Agents share working memory (global scope) + lessons, but NOT conversation
  threads.** Keep it that way unless explicitly asked.

---

## 11. Verify a change the way this build did

`python -m py_compile app/*.py app/roles/*.py scripts/*.py`, plus a focused
`python - <<'PY'` AST/logic assertion (e.g. every tool routes, approval kinds
match executors, JSON env values parse, all Google `.execute()` calls sit inside
the lock). The build env is Python 3.9 and CANNOT import the app modules (union
type hints / missing deps), so verification is compile + AST + isolated-logic
tests, not live runs. Live testing happens against the deployed Render service.
```
