# INITIATIVE — Organic growth: the keyword plan, the blog skill, and platforms that cannot be written to

> **THIS IS A PLAN, NOT A STATE FILE.** Written 2026-08-25. `BUILD-STATE.md`
> remains the record of what exists.
>
> **NOTHING IN THIS FILE IS BUILT YET.**
>
> §2 is a list of facts with file:line, each checkable in about a minute. If
> they still hold, the plan holds. If one has changed, the phase resting on it
> needs re-reading before it is built. That is the only way a plan avoids the
> `HANDOFF-content-platform.md` failure — describing state that moved
> underneath it.

---

## 1. What this is for

Three goals, from the owner (2026-08-25):

1. **Generate SEO and AEO optimised blogs for clients.**
2. **A keyword plan created PROGRAMMATICALLY, covering long-tail and
   short-tail, tied to the brand's organic growth goal — and verifiable
   against, so progress and ranking changes can be shown from Search Console,
   Semrush and whatever else is connected.**
3. **Squarespace has no content write API.** Build the backend anyway; where
   the API does not exist, generate **drop-in HTML** the owner pastes in.

4. **`blog` runs for EVERY account, not Baci first** (owner, 2026-08-25:
   *"I will be doing blog for all of them from here"*).

Goal 4 sounds like a switch and is not. It is what turned §2.10 from a tidy-up
into a blocker: with one client, a site key that silently fell back to the
primary was invisible; with five, it is the first thing that happens.

Goal 2 is the one that changes the architecture. A blog generator without it
is a copy machine: it produces articles nobody can defend as a strategy and
nobody can prove worked. The map and the measurement are not a later phase —
they are what makes the articles a system.

---

## 2. Verified facts this plan rests on

Each was read in the tree on 2026-08-25 at commit `f0c5e0a`. **Re-check first.**

### 2.1 The publish half is built on both platforms, and unreachable
`shopify_seo.py:238-380` and `wordpress_seo.py:204-285` each carry the same
five functions — `list_blogs`, `list_articles`, `get_article`,
`create_article`, `update_article`. **Nothing calls any of them.**
`seo_tools.TOOLS` holds 33 tools and not one is an article tool;
`approvals.execute` handles `seo_update` (`approvals.py:327`),
`seo_new_collection` (`:334`), `seo_new_page` (`:341`) and
`shopify_theme_asset` (`:347`) — there is no article kind. The blog path is
complete from the platform up to the backend and stops one layer below the
agent.

### 2.2 The ban list already guards the article path
`seo_guard.check` fires at `shopify_seo.py:311` (new article) and `:341`
(revision), and `wordpress_seo.py:260` / `:281`. This is the guarantee that
survives contact with a live client site, and **anything new that writes prose
must call it at the same point** — including the drop-in HTML path, which is
publishable prose that merely travels by clipboard.

### 2.3 AEO primitives exist and are platform-routed
`sites.py:93-134` — `faq_schema` (FAQPage JSON-LD), `faq_html` (visible
answer-first H3/P), `compose_jsonld` (merges Article/Breadcrumb/ItemList),
`jsonld_script`. Routing is by a module flag: `shopify_seo.INLINE_JSONLD =
False` (`:21`, body_html drops `<script>`, so the metafield + theme renderer
path) and `wordpress_seo.INLINE_JSONLD = True` (`:30`). The consumer is
`seo_tools._build_content_fields:271`, via `getattr`, so a new backend joins
by declaring the flag.

### 2.4 Link grounding is real and platform-agnostic
`sites.verify_links:141` HTTP-checks every internal link against the live
domain; `seo_tools._link_grounding:280` blocks the proposal on a broken one.
It needs nothing but HTTP, so it works for a platform we cannot write to.

### 2.5 The blog system is declared, with no skill and no plan fields
`systems.py:180-192`. It declares `unit` ("one article against one keyword"),
`artifact` (`cms_article`), `ship`, `measure` ("draft-vs-published delta") and
`kb_needs`, and carries the comment that the keyword-map planner and the
drafting skill **land together**. `planner.PLANNERS:421` has exactly one
entry, `campaign_email`.

### 2.6 The SEO path does not touch the knowledge spine
`seo_tools.py:18` imports `config, db, memory, sites`. Not `kb`, not `brief`,
not `validator`, not `systems`, not `skill`. So blog output today would get no
claim grounding, no citation, no `validator` pass, no run ledger and no
autonomy rung. It is the old agent-with-tools architecture; `campaign_email`
(`skill_pack.py:2577`) is the shape everything else has moved to.

### 2.7 There is no keyword map, and measurement is site-level only
"against the keyword map" (`systems.py:182`) is a phrase with no
implementation anywhere in the repo. What exists is `SeoSnapshot`
(`db.py:860`) — one row per domain per capture: rank, organic keyword count,
organic traffic, and the top 50 keywords by traffic share. `seo_progress`
(`seo_tools.py:200`) diffs the **last two** snapshots' top-50 lists.

That answers "is the site up". It cannot answer *"we published this article
for this keyword — did that keyword move"*, because nothing joins an article
to a keyword, no keyword has a target, and a phrase outside the top 50 by
traffic has no series at all. **Goal 2 is this gap.**

Two smaller notes on the same table: `source` is declared `semrush | gsc` and
**only `semrush` is ever written** (`seo_tools.py:188`); and `tenant` is
documented "derived from `domain`" but the write does not set it —
`tenant_scope.py:165` backfills it later by domain match.

### 2.8 The plan substrate is built, and a keyword plan should ride it
A plan is a `SystemRun` at stage `PLANNED` carrying `brief.plan`,
`brief.edited` and `brief.planned_for`. `systems.open_plan:1175` is the only
entry point: idempotent per `ref`, owner edits carry forward, unknown fields
refused, `plan_complete:1089` names what is missing. Cadence knobs live on the
System row via `set_cadence:1017`. **A keyword plan needs no new plan
machinery — it needs `plan_fields` on `blog` and a planner in the registry.**

### 2.9 Onboarding an organisation nobody wrote code for
**REFRAMED AND FIXED 2026-08-25** after the owner's correction: *"this should
work across any new organization."* The first version of this section was a
per-account table of things to declare — `eien` needs a `cms` block, `agency`
needs an entry — which is a list of developer tasks wearing a product's
clothes. The seeded five are not the subject; the account created tomorrow is.

Three things were DECLARED that are derivable, and each one blocked a new
account on somebody editing Python or an env blob:

* **`cms` did not fall out of connecting a store.** `GRANTS["shopify"]` was
  `("commerce",)`, so a client who connected Shopify was told the blog system
  was not ready — forever — while `shopify_seo.create_article` sat built and
  the OAuth flow already requested and DISCLOSED `write_content`. The
  `CMS_PLATFORM_PROVIDER` fallback in `wired_capabilities` existed only to
  paper over this. Now `GRANTS["shopify"] = ("commerce", "cms")`, gated by
  `CAPABILITY_SCOPES[("shopify","cms")] = "write_content"` against the scopes
  the provider itself reported (`Credential.scopes`, written by `store_oauth`).
  **Known-and-missing refuses; unrecorded grants** — the api_key and env paths
  carry no scope list, and refusing there would disconnect every account that
  works today. Unknown is not absent.
* **The platform was a hand-written column.** It now follows the connection:
  `wired_capabilities(t).get("cms")` is `"client:shopify"` / `"env:wordpress"`
  and the provider IS the platform. A DECLARED platform is the fallback, which
  is how Ironside says `squarespace` — nothing can connect to it, and
  `backend()` refuses it by name.
* **Brand rules lived only in `SEO_SITES_JSON`.** A new account got
  `voice: ""`, `guardrail: ""`, `exclude_terms: []` and the SEO role wrote for
  it with no rules at all — while `KbBrand` held `voice.tone`, `positioning`,
  `never_say` and `banned_claims` for that same account. Baci's env
  `exclude_terms` is literally its banned-claims list, keyed a second time by
  hand: §2.10's defect one field down. `sites._brand_rules` reads the KB now,
  and the KB is the store a CLIENT can fill themselves at `/intake/<token>`.

**The path for any organisation, with no code edit anywhere:**
`/admin/tenant_add` -> `/connect/<token>` -> `/intake/<token>` -> install
`blog`. `scripts/test_new_organization.py` drives exactly that for an account
called `acme` that appears in no seed and no env, and asserts each stage
including the two that must NOT resolve: no platform before a connection, and
no `cms` for a token granted without `write_content`.

**What that leaves for the five.** Only connections, which are client-facing:
`baci` is ready; `eien` connects (its store is in the env group but its row
never named it — `tenants.py:383`); `coverings` and `agency` connect theirs;
`ironside` waits on Phase 5. **Do not write that list down again** —
`systems.ready()` returns named blockers and the console answers it per
account, which a document cannot do without going stale.

### 2.10 The site registry was a second list of clients, and it leaked
**FOUND AND FIXED 2026-08-25, in this branch.** `SEO_SITES_JSON` held `baci`,
`eien` and `mtw`; the tenant registry held `agency`, `baci`, `eien`,
`coverings` and `ironside`. Two hand-maintained lists of the same clients.

`sites.get()` fell back to the primary site for any key it did not hold, so
**`site="coverings"` returned Baci** — and three of five tenants had no profile
at all. On the path Phase 1 just opened that means
`propose_article(site="coverings")` queues a write to Baci's store under a
summary reading `[SEO/coverings]`, checked against **Baci's** ban list, because
`seo_guard.tenant_for` resolves from the profile's domain and not from the key
that was asked for. Coverings' own rules would never have run.

The same family, one layer along: `sites.backend()` was
`wordpress if platform == "wordpress" else shopify`, so Ironside's
`squarespace` inherited the Shopify client — §2.31's bare-`else` shape again.

Now: `sites._from_tenants()` derives profiles from the tenant rows (the rows
decide WHICH clients exist; `SEO_SITES_JSON` decides voice/guardrail/
exclude_terms and merges on by key or by domain, keeping `mtw` as an alias for
`agency`); `get()` raises `sites.UnknownSite` for a key it does not hold while
blank still means the default; and `BACKENDS` is a name per arm.
`scripts/test_site_resolution.py` pins all of it — **and `BACKENDS` is the seam
Phase 5 plugs `squarespace_seo` into.** §2.9 is the same defect's other half:
this one was a second list of WHICH clients exist, that one a second list of
what each client IS.

---

## 3. The decisions this plan makes

### 3.1 You do not rank a head term with an article. You rank it with a cluster.
This is the load-bearing decision and everything in the schema follows from it.
A short-tail term is won by a **pillar page** plus N long-tail articles that
genuinely answer sub-questions and link into it. So the map is two levels:
`cluster_key` groups rows, and `role` is `pillar | support`.

It also settles which existing tool publishes what. A pillar is a page —
`propose_content_page` already exists and already carries FAQ + JSON-LD. A
support piece is an article — that is §2.1's unreachable half. And the
internal links from support to pillar are exactly what `verify_links` (§2.4)
already refuses to let us hallucinate.

Without this, "rank for short-tail keywords" is a wish. With it, it is a
countable build: a cluster is done when its pillar exists and its supports are
published, and a cluster half-built is the most common way this work produces
nothing.

### 3.2 Tier is computed, and the thresholds are per-tenant
`head | body | long_tail` is derived from word count, volume and difficulty —
deterministic code, stored on the row, never typed by a person. Per-tenant
thresholds, because a local venue's head term and a national e-com brand's are
different volumes, and one global constant would file Ironside's whole map as
long-tail. Same lesson as `kb.SITUATIONS` being a shared module constant that
did not fit product tenants.

### 3.3 Four sources, each answering a different question
- **`gsc_striking`** — queries with impressions at average position 5–20. You
  already have relevance and are one article from the fold. Fastest
  measurable win, and it is *your* data rather than a model of it.
- **`semrush_gap`** — competitors rank, you do not.
- **`semrush_related`** / **`semrush_questions`** — long-tail and question
  expansion. `semrush_questions` is the AEO seam: it mines the interrogative
  phrasing that the FAQ + FAQPage path (§2.3) was built to consume.
- **`owner`** — manual, and never overwritten by a refresh, the same
  carry-forward rule `open_plan` already enforces.

### 3.4 Two verification sources, deliberately, because they disagree
`KeywordReading` records both. GSC is the truth about **your traffic**
(impressions, clicks, CTR, average position across the devices and places your
buyers actually are). Semrush is the truth about **the market** (where
competitors sit, what the term is worth). Semrush saying #7 while GSC says
11.3 is not an error to reconcile — it is the difference between a rank check
from one location and an average over everyone who saw you. Recording both and
showing the gap is more honest than picking a favourite, and picking one would
mean re-deriving the other every time somebody asked.

### 3.5 Progress is measured against a control, or it is not measured
Tracked pages get compared to **the rest of the site over the same window**.
Without a control, a good quarter for the category reads as our work — and
this codebase refuses false assurance everywhere else (`validator` fails
closed; `seo_guard` names the field; `correlate` says out loud when the
summariser did not run). A progress report that cannot be wrong is the same
defect wearing a chart.

### 3.6 Correlation is reported as correlation
Every delta carries `days_since_publish`, and a move inside ~14 days of
publish is reported **without** an attribution line, because Google has not
settled. The report says what changed and when it was published; it does not
say one caused the other. Same discipline as `performance.py`: status decides
`published`, numbers do not.

### 3.7 The goal is declared, so progress has something to be against
The `blog` System row carries goal fields in the `set_cadence` shape — e.g.
target organic clicks, target wins per tier, horizon. Progress is then a
computed number versus a number somebody chose. A dashboard with no declared
target is a dashboard nobody can fail, which is why nobody reads it.

### 3.8 A platform with no write API produces a drop-in artifact, not a refusal
Squarespace has commerce/inventory/orders APIs and **no public content write
API**. The undocumented internal endpoints its own editor uses are not an
option: unstable, outside their terms, and the failure mode is a client's
live site breaking silently.

So `squarespace_seo.py` joins with the same five-function surface and
`MANUAL_PUBLISH = True`, `INLINE_JSONLD = True` (no metafield, no theme
snippet — the JSON-LD rides inline in a code block). `create_article` returns a
**paste-ready artifact**: the article body, the FAQ block, the inline
`<script type="application/ld+json">`, plus the fields that must be set by hand
in the editor (title, URL slug, meta description, category, publish date).

Four rules that make it a real ship rather than a lighter one:

* **It goes through `seo_guard` at the same call site.** Prose that travels by
  clipboard is still prose on a client's site.
* **`verify_links` still runs.** It only needs HTTP.
* **It records a real `Output`** with `destination="manual:squarespace:<slug>"`.
  Withholding the row until someone confirms would leave the entire
  measurement loop blind on this client — and Ironside is the account most
  likely to need proof.
* **It stays `drafted` until the live URL comes back**, and the confirmation is
  verified with `gsc_inspect_url` rather than a checkbox. A person ticking
  "done" is not evidence the page exists.

`MANUAL_PUBLISH` generalises past Squarespace — Wix, Webflow on some plans, a
client's bespoke CMS. Building it as a Squarespace special case would mean
building it again for the next one.

---

## 4. Phases

Ordered so each one is demonstrable on its own, and so the earliest one makes a
live client publishable.

**Phase 1 — BUILT (2026-08-25, branch `feat/blog-path`, uncommitted). Reach the article backends.** `propose_article` +
`propose_article_revision` in `seo_tools.TOOLS`; `seo_new_article` /
`seo_article_revision` in `approvals.execute`, routed through
`sites.backend()`. Nothing new is written — this connects §2.1 to the agent.
*Demo: an approval-gated, ban-list-guarded article published to Baci.*

**Phase 2 — BUILT (2026-08-25). The map.** `KeywordTarget` + `KeywordReading`
in `db.py`, both classified in `reset.OPERATIONS` in the same change.
`app/keywords.py` (603 lines): tier (3.2) and intent classifiers, pillar/support
clustering (3.1), the priority score, four harvest seams, `harvest()` and
`map_for()`. Reachable at `/admin/keywords` (read), `/admin/keywords_harvest`
(spends API calls — a separate URL on purpose) and `/admin/keywords_rescore`.
`scripts/test_keywords.py` drives the whole pipeline offline through the seams.

Three decisions worth keeping, each of which the suite caught rather than the
author:

* **Clustering singularises.** Exact-token containment meant "acrylic jug" did
  not contain "are acrylic jugs dishwasher safe" — the most common variation in
  any keyword set. `_stem` is deliberately crude (an `ss` guard, `ies -> y`) and
  not a real stemmer, which would fold "designs" and "designer" together and
  silently merge two intents.
* **An unclustered row gets a cluster whatever its status.** The first rule
  skipped on status alone, which left every keyword published before the map
  existed permanently unclustered — and an unclustered pillar is invisible to
  `cluster_state`, so the bonus for finishing its cluster could never fire.
  Protecting a settled plan is not the same as refusing to make one.
* **`difficulty` is nullable and unknown scores nothing either way.** Semrush's
  `phrase_related` projection carries `competition` (paid, 0-1) and no KD;
  filling difficulty from it would be DEFECTS §1's "ranking across incomparable
  scales" on purpose, and treating unknown as 0 would sort every unmeasured
  keyword to the top.

**Phase 2 has no automatic caller yet, deliberately** — `planner.blog_rollout`
is the consumer and lands in Phase 4, per `CATALOG["blog"]`'s own instruction
that the planner and the skill land together. The admin routes are what make it
runnable meanwhile, so the map can be built and read before anything writes
against it.

**Phase 3 — BUILT (2026-08-25). The measurement loop.** `keywords.sync` /
`sync_all` on the nightly schedule at `SWEEP_HOUR:05` — five minutes BEFORE
`correlate`, because a sweep that runs first reports yesterday's positions as
today's. `keywords.progress` is the report; `systems.set_goal` / `goal_for` is
the declared target, on `System.config["goal"]` beside `cadence`. Reachable at
`/admin/keywords_progress`, `/admin/keywords_sync`, `/admin/keywords_goal`.
`scripts/test_keyword_progress.py` pins the three refusals.

* **`GOAL_FIELDS` has no default and will not get one** (3.7). A target nobody
  chose is a bar nobody can fail. With none declared, `progress` returns
  `goal.declared = None`, names the field, and still delivers every number that
  does not depend on it — the same shape as `resolve`'s `needs_lookup`: refuse
  the invention, not the work.
* **`won` is derived from readings, in BOTH directions.** A status that only
  ratchets upward is a status that lies, so a win that drops out of the top
  three returns to `published` on the next sync.
* **A phrase GSC did not return gets NO reading.** Absent from a truncated
  top-N is not the same fact as "not ranking", and writing the second when we
  only know the first is how a report acquires a number nobody can defend.
  `sync` reports `tracked_without_data` instead.
* **`position_gain` is inverted at the seam.** A smaller position is an
  improvement, and a delta reading -9 for a nine-place gain is one somebody
  misreports the first time they quote it.
* **`clicks_pct` is None on a zero base.** No base is not zero growth.

**A portability bug this surfaced.** `_period_readings` compared stored
datetimes against `utcnow()` directly, which works on Postgres and raises
"can't compare offset-naive and offset-aware" on SQLite. `db.as_utc` exists for
exactly this — and three modules (`approvals.py:99`, `systems_map.py:178`,
`performance.py:52`) each hand-roll their own copy of it anyway. Tracked
separately; this branch uses the canonical one.

*Demo, once there are two weeks of readings: "9 of 14 moved up, 4 into top-10,
tracked +23% vs control -2%, 3 too early to attribute."*

**Phase 4 — BUILT (2026-08-25).** `CATALOG["blog"]` declares
`skill="blog_article"` and five plan fields; `planner.blog_rollout` is
registered; `skill_pack.blog_article` drafts. `scripts/test_blog_skill.py`
pins both halves.

* **A support is never planned before its pillar** — the one rule a priority
  score cannot express, and the most common way this work produces motion and
  no result. The first cut promoted the pillar *instead of* the support and
  moved on, silently dropping the highest-priority keyword in the whole map;
  the pillar goes AHEAD of it now, and `pillar_first` says so on the run.
* **A failed draft files NOTHING** — no composed fallback, unlike `ad_copy`.
  A three-line placeholder ad is usable; a templated ARTICLE is a thin page,
  and thin pages harm the thing this system exists to improve.
* **No claims, no article, and no model call.** `emit` defaults
  `require_citation` True for a draft, so an uncited article is blocked every
  time. Drafting one first meant paying for something the validator would
  always refuse, and reporting the KB backlog as a validation failure.
* **A published sibling is a LINK, never also an FAQ answer** — answering
  inline what you also link to competes with your own page for the query.
* **The publish goes through `seo_tools._propose`**, which already owns
  `_build_content_fields`, `_link_grounding` and the approval, rather than a
  second copy of the FAQ/JSON-LD composition — the defect this initiative has
  now fixed three times.

**A shared-path defect it surfaced.** `approvals.request_approval` let a
notification failure raise AFTER the approval was committed, so every caller
was told the REQUEST had failed when only the telling had, and the queue filled
silently behind the error. Found because an exception there marks a skill run
`failed` and discards a drafted article whose approval was in the database the
whole time. Logged now, not raised.

*Superseded plan text below* (§2.5's own
instruction). `plan_fields` on `blog`; `blog_rollout` in `planner.PLANNERS`
reading the map; a `blog_article` skill in `skill_pack` with
`needs=("rules.voice_tone","rules.positioning")`,
`constitutive=("banned_claims",)`, `writes=True`, `produces="draft"`. This is
what moves blog output onto the rails `campaign_email` already runs on —
grounding, citation, `validator`, ledger, autonomy rung (§2.6).

### 2.12 Whose Google account reads a client's Search Console
**REVERSED 2026-08-26 by the owner: *"every account has their own google
connect."* PER-ACCOUNT, not shared identity.** The section below recorded the
opposite as a locked decision earlier the same day and was wrong; it is kept
because the REASONING about `_match_gsc_site` still stands and because a plan
file that quietly rewrites its own history is one nobody can check.

**What changed in the code.** `sites._from_tenants` fell back to
`config.SEO_GOOGLE_ALIAS` and `google_seo._alias` did the same. Correct under
shared identity; the `sites.get()` defect one field along under per-account
connections — and it was already costing. Ironside's own Google IS connected;
the console files a credential under the TENANT and sets no `gmail_alias`; so
`gmail_alias` was empty and every Search Console read for Ironside went
through `personal`, an account whose token is revoked. Its own working
connection was never asked. The fallback is now `t.key`, which is not another
account's identity — `credentials.google_config` treats an unmatched key AS
the tenant, so the key resolves that account's own credential. `_alias`
returns "" rather than substituting anybody.

**What this makes cheaper, and what it costs.** Cheaper: `_match_gsc_site`
stops being the boundary between clients, because one token no longer sees
several clients' properties — the label-boundary fix below stands anyway and
is still right. More expensive: every client now runs a Google consent, which
is the scope conversation in §2.11 multiplied by five, and the client-facing
flow can no longer be kept clear of Google entirely.

---

*Superseded, kept for the reasoning:*

### 2.12a Whose Google account reads a client's Search Console
**DECIDED 2026-08-25 by the owner: the SHARED-IDENTITY model stands.** One
Google account (`SEO_GOOGLE_ALIAS`, default `personal`) is granted viewer
access on each client's Search Console property, rather than each client
running an OAuth consent of their own. `config.py:257` has always said so; the
decision is that it stays.

**What it buys.** Client onboarding never asks for a Google scope, so the
client-facing flow stays clear of `gmail.modify` and `drive` — Google's
RESTRICTED tier, the one that can pull a production External app into a CASA
security assessment. A client adds an email address as a viewer in Search
Console and is done. The six-scope grant is the owner's own account, of which
he is the only user.

**What it costs, and where the cost lands.** One token can now see several
clients' properties, so `google_seo._match_gsc_site` stops being a convenience
and becomes THE boundary between one client's rankings and another's. It was
already built for this — "CONFIDENT match only — never guess", three tiers
strongest-first, ambiguity returning None so a person must pin it, and a
docstring that names "another client's property" as the risk.

**Its last tier was a raw substring test, and that is fixed.**
`_gsc_candidates` matched `host in siteUrl`, so `"acme.com" in
"https://shopacme.com/"` was True. With that as the only candidate the tier
returned confidently and `_save_link` PINNED another client's property —
silently, permanently, in front of a client. It matches on LABEL BOUNDARIES
now (`_property_host`): a property covers a host if it is that host, or if the
host sits beneath it. Narrow window, since it needs no exact domain property
and no exact prefix match to reach tier three at all — but the failure was
invisible and durable, which is the combination this repo keeps paying for.

**The fallbacks stay, and are now intended rather than tolerated.**
`sites.py:128` and `google_seo.py:68` both fall back to `SEO_GOOGLE_ALIAS`.
Under per-client OAuth those would be the `sites.get()` defect one field along
— an unconnected account silently borrowing the owner's identity. Under shared
identity they ARE the design. What keeps them honest is that `/health/blog`'s
Measure verdict asks the API for a property matching THIS site's domain, so
"connected" cannot mean "we hold a Google token" the way it briefly did.

### 2.11 Nothing had ever verified Search Console
**FOUND 2026-08-25**, answering the owner's *"make sure that our connectors for
these are set up correctly."* Asking it properly found the hole rather than
confirming the setup.

`/health/connections` probes gmail and drive. `/health/seo` probes Semrush.
**Neither asks Google whether the token can read Search Console** — and the
whole Phase 3 measurement loop runs on GSC.

There are THREE Google scope lists in this repo and they do not agree:

| where | Search Console? |
|---|---|
| `scripts/google_oauth.py:21` | yes — `webmasters.readonly` + `analytics.readonly` |
| `oauth.FLOWS["google"].scopes` (`oauth.py:231`) | yes, both |
| `gmail_client.SCOPES:16` | **no** — gmail.modify, gmail.send, drive.readonly |
| `credentials.ENV_GRANTS["google"]` | **`("inbox",)` alone** |

So an account reads `gmail ok · drive ok` forever and may have no Search
Console at all. `ENV_GRANTS` granting `inbox` alone is CORRECT and deliberate
(§2.29's note: a pasted env refresh token may never have had the GSC
re-consent) — the defect is that nothing ever asks the API which it is.

`keywords.readiness` asks. `_gsc_probe` makes a real `gsc_list_sites` call and
reads its result against the pack's documented contract — JSON is data, a
SENTENCE is failure — then checks a property actually matches the site's
domain. Reachable at `/health/blog?key=…`, per account or across all.

**Three axes, reported separately, because they fail separately and the fixes
are different people:** connecting a store is the client, granting Search
Console is whoever owns the Google account, approving a claim is the owner. A
single green light would hide whichever one is broken. `systems.ready()` is not
this — it checks the catalogue's `requires`, which for `blog` is `cms`, and
that is the right gate for PUBLISHING; making `analytics` a hard requirement
would refuse to publish an article because nobody had connected the thing that
reports on it afterwards.

**The switch is part of the answer.** The first cut returned `ok=True` for an
account with every connector wired and no `blog` system installed — a green
light on a pipeline that cannot run.

**Also live right now, unrelated but broken:** the agency Canva connection
reports `Refresh token used twice. All access tokens granted from this flow are
now revoked`. It blocks `draft_visual` on campaigns, not blogs.

---

**Phase 5 — Squarespace, and the four accounts that cannot publish yet.**
`squarespace_seo.py` per 3.8, registered in `sites.BACKENDS`; `MANUAL_PUBLISH`
handling in `_propose` and in the approval executor. Then §2.9's column four,
per account: declare `eien`'s `cms`, connect Coverings' Shopify, connect the
agency WordPress, and install `blog` on all five.

Per §2.9 this is now connections only — no tenant row needs a `cms` block and
no account needs an `SEO_SITES_JSON` entry. Worth starting in parallel rather
than after, since three of them need somebody else's cooperation.

**Open, owner's call:** the goal numbers for 3.7 — organic-clicks target, wins
per tier, horizon. Progress needs a number somebody chose to be measured
against, and it is the one input no amount of connected data supplies.
