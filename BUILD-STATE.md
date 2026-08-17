# Build state — 2026-08-17, after the skill substrate

The rolling state of the data-layer build. **This file is rewritten by every
thread.** It is always current and never historical — do not add dated sections,
and do not create `HANDOFF-step-N.md` files. History lives in `DEFECTS.md`
(append-only) and in the git log.

`HANDOFF-content-platform.md` is the **historical** record up to 2026-08-13 and
is no longer maintained. Parts of it are actively wrong. Read it for background,
never for state.

**Live:** `45ba6cf` on `origin/main` — pushed and confirmed serving (`/health`
reported the swap after ~60s, and `/health/connections` still passes on both
Shopify stores and all three Google accounts). The skill-bridge work below is a
later commit, **not yet pushed**. `/health` reports `commit` and `routes` — use
it, do not infer what is running.

**Connections, verified live 2026-08-17 via `/health/connections`:** Shopify
`baci` and `eien` both ok; Gmail + Drive ok for `personal`, `baci`, `eien`. So
Baci has `inbox` and `commerce` genuinely wired, which is everything the three
ready skills need.

`capabilities()` now tells the truth about the rest — see §2.29. It reported
`esp`, `cms`, `ads` and `crm` as wired off a declaration in the Tenant JSON,
with no credential behind them. Every capability resolves through
`credentials.wired_capabilities` now, and `tenants.capability_detail` reports
`wired` / `via` / `declared` / `needs_connecting`. Against the live env group
that reads: **baci** inbox + commerce + cms (all `env:shopify`/`env:google`),
declared-but-unconnected esp/ads · **eien** inbox · **agency** inbox ·
**coverings** and **ironside** nothing wired.

**Connected what was connectable.** `cms` is now granted by the provider the
tenant's CMS platform names, when that provider's credential resolves — Baci's
CMS *is* its Shopify store, published with the token it already has, so the blog
system was blocked on a connection that already existed. Baci now sees 37/37
agent tools, up from 34.

**Two things need you, and cannot be done from code:** Omnisend (`esp`, both
Baci and Eien — there is no Omnisend credential anywhere in the codebase and
`credential_ref` was never a real one) and Meta (`ads` — `META_APP_ID/SECRET`
are OAuth app credentials, not a per-tenant token). Both go through
`/connect/{token}`. **Eien's store row:** `_SEED` now names `shopify_store="eien"`
but `seed()` skips existing rows, so the live database needs
`/admin/tenant_set?tenant=eien&field=shopify_store&value=eien` — the credential
has been live in `SHOPIFY_STORES` all along and the row simply never claimed it,
which is why `reorder_engine` could never go live.

---

## Where we are

The data layer stopped being a retrieval library and became something an agent
can be *given*. Before this thread, `resolve`, `validator`, `ledger` and
`responder` all worked and none of them opened a run — `systems.start_run` had
two callers, neither in the data layer. Anything built on top would have
produced ungoverned output. `app/skill.py` closes that: a skill declares the
context it needs, and the substrate resolves it once, gates on coverage, opens
and closes a run, runs the validator on everything emitted, files it to the
ledger, and applies the autonomy rung. Four skills are registered on it, three
of which serve Baci with no new content.

**The contract is frozen.** Build-map steps 05, 06, 08, 10 and 11 are
deliberately not built — they are the *visual and creative* chain, and nothing
Baci needs first touches them.

## The five rules this codebase keeps re-learning

Every one was a real defect, several of them twice. Read before changing
anything.

1. **Absence is a third state and must survive to the output.** Met seven times
   now. This thread added two: `empty` versus `blocked` for a sweep that found
   nothing, and a metafield that could not be read versus one that was clean.
2. **Enrich, do not gatekeep.** `blocked_on` is reserved for output that would
   be unsafe. §2.27 is this rule broken at its most expensive point — a gate
   written against an *assumption* about `claims()` rather than against
   `claims()`, which refused real proof from any account without a vocabulary.
3. **Approved is final, whatever wrote it first.**
4. **Derive lists from the schema, never by hand.**
5. **Run it before claiming it works.** Every finding below came from running
   against real code. Four defects in this thread were found by the new suite,
   two of them in code written the same hour.

## Built this session

**`app/skill.py` — the substrate.** `Skill` declares `system_key`, `tier`,
`needs`, `params`, `writes`, `produces`. `preflight()` answers "can this run for
this account" cheaply and by name. `run()` is the only entry point.
`Context.emit()` is the only exit, and it validates before the caller sees
anything — the gate is structural, not remembered. `catalogue(tenant)` is what
an agent should be shown instead of a tool list: every skill, and whether it can
run here, with the missing field named.

**Autonomy is applied, and the validator outranks it.** `auto` means "do not ask
about the things that passed", never "send the thing that failed". A skill that
writes still needs approval at `approve_exceptions`.

**`app/skill_pack.py` — four skills.** None is Baci-specific; each reads its
client out of the KB.

| skill | system | writes | state |
|---|---|---|---|
| `catalog_compliance` | catalog_compliance | no | ready |
| `catalog_seo_rewrite` | catalog_compliance | proposes | ready |
| `inbound_reply` | service_desk | no | ready, thin until objections exist |
| `ad_copy` | ad_creative | no | model-drafted; copy only, no imagery |

**Where the model actually writes.** `inbound_reply` and `ad_copy` are model
calls — grounded on the bundle, with the validator as deterministic code behind
them. `catalog_seo_rewrite` composes by code on purpose: a 155-character
formulaic field where composing from an approved claim means the `claim_id` is
carried by construction.

`ad_copy` makes **one call per claim**, not one call for N variants. Parsing
which line came from which claim risks filing the wrong `claim_id`, and
attribution that is wrong is worse than attribution that is missing — the
anti-repeat and hygiene queries both trust it. Per-claim calls make attribution
structural. With no key it degrades to a composer and every variant carries
`basis="composed (…)"`, because a silent fallback is the extractor defect again.

**Why the sweep is not `compliance.scan` again.** The site crawler strips
`<head>` before matching, so an SEO meta description is invisible to it — and
that is the field a violation hides in, because it gets templated across a whole
catalogue. Baci's own audit is that shape: 110 flagged strings, **96 of them one
repeated SEO-meta template**, none of which the crawler could see.

**Two new `systems.CATALOG` entries:** `catalog_compliance` and `ad_creative`.

**Five defects fixed** — §2.25 through §2.29 in `DEFECTS.md`. The one worth
reading is **§2.27**: `add_claim` and `review_claim` both refused an untagged
approved claim on the stated grounds that it "can never be selected". False —
`claims()` filters on situation only when a caller asks for one. Both paths now
infer a situation where the classifier is confident and file brand-wide proof
where it is not, saying which happened. Owner's call, and it unblocked the
rewrite skill. §2.28 fixed the two `add_claim` silent losses carried as live
since 14 Aug.

## The skill bridge

Four routes so an outside Claude skill — the Coverings trio, the marketing pack
— can run on this data layer instead of on its own workbook copy.

`/admin/agent_context` hands over the resolved brief. `/admin/agent_emit` is the
gate: it validates a skill-written draft, files it to the ledger passing or
blocked, and returns `may_send` rather than the draft, so a skill that skips it
has nothing to quote as permission. `/admin/skill_catalogue` and
`/admin/skill_run` finally give the four registered skills an entry point —
before this they were reachable only from Python.

**The design constraint.** Letting a skill draft in its own session puts the
draft outside `Context.emit`, and `emit` is the only reason any of this is safe
— validator, ledger and rung all bypassed silently. So the bridge is not "read
the KB", it is read → draft → come back through the gate. `test_bridge.py`
(21 checks) holds that line: a skill writing a banned claim is blocked, on
`auto` as well as on `shadow`; both drafts reach the ledger; and material in
review never enters a bundle.

## Verified vs assumed

**Ran and confirmed.** All **33 offline suites pass**, none touching the
network, including `test_tenant_isolation.py` **unmodified**.
`scripts/test_skill.py` is new — 54 checks covering the gate, the rung, named
refusals, `empty` vs `blocked`, unread vs clean, and every run reaching the
ledger. It drives the model seam from both sides with a stub: the degraded path
reports `basis="composed"`, and **a model that returns a banned phrase is
blocked, not softened** — the check worth keeping. Full run is ~2m30s; split it
or a single shell call hits a 2-minute timeout.

**Three existing assertions in `test_harvest.py` were changed**, not worked
around. They pinned the old approve-time tag refusal that §2.27 removes.

**Built but unproven — read this before trusting anything above.** No skill has
run against real Baci data. There was no `DATABASE_URL`, `APPROVAL_SECRET` or
`ANTHROPIC_API_KEY` available in the session that wrote them, so:

- `_fetch_products_live` has **never made a Shopify call.** Everything above it
  is proven against fixtures. The REST shapes (`products.json`,
  `products/{id}/metafields.json?namespace=global`) are the ones `shopify_seo`
  already uses, but "the code is right" is not "it ran".
- The 96-violation figure is from the prior audit, not from this sweep.
- **No real model call was made.** `inbound_reply` and `ad_copy` were exercised
  against a stub. The prompts, the grounding block and the shape of what comes
  back are all unproven against the live API.
- The N+1 metafield read is untimed against a real catalogue.

## Open, and honest about it

**Never measured:** `scripts/ab_context.py` — the central claim that this layer
beats a compiled `.md` is still unproven. One command:
`ANTHROPIC_API_KEY=… DATABASE_URL=… python3 scripts/ab_context.py baci`

**Blocked on content, not code:**
- Objections: 7 in review, 1 approved. Binding constraint on `inbound_reply`.
- `brand.voice.tone` unset. `/admin/propose_voice` will hand you the words.
- 13 claim fingerprints unrepaired (`/admin/repair_fingerprints?apply=1`).

**Known gaps:**
- `ad_copy` has no imagery and does not pretend to. Every variant carries
  `needs_art_direction`. Steps 05/06 are what fix this.
- `ANTHROPIC_API_KEY` unset in the authoring session, so both model skills
  degrade to composers today. Setting it is what turns `ad_copy` from a
  grounded placeholder into ad copy.
- `feedback_block` still has no caller.
- 2 scanned PDFs need OCR. Not built.
- `READ_KEY` unset, so `/resolve` and `/brand.md` answer only the admin secret.
- `ops_jobs.py` is the last file in the execution half with zero tenant refs.
- No route or agent tool exposes the skills yet — `skill.run` is importable and
  nothing calls it. That is the next thread.

## Commit

`67625b7` on `feat/context-architecture`, one commit ahead of `origin/main`
(`21fdb89`, which is what `/health` reports as live). **Committed, NOT pushed.**
Verified a clean fast-forward with `git merge-base --is-ancestor` before
committing.

New: `app/skill.py`, `app/skill_pack.py`, `scripts/test_skill.py`.
Modified: `app/kb.py`, `app/harvest.py`, `app/email_harvest.py`,
`app/systems.py`, `app/responder.py`, `scripts/test_harvest.py`,
`DEFECTS.md`, this file.

Pushing deploys it. `_fetch_products_live` has never made a real call and no
model call has been made either, so push when somebody can watch the first
sweep rather than overnight.

## Next thread starts here

**Read, and only these:** this file, then `DEFECTS.md` §1 and §2.25–2.28, then
`app/skill.py`. Do not search the repo broadly.

Highest value first:

1. **Run `catalog_compliance` against real Baci.** It is the only thing standing
   between this and a client-facing artifact in week one, and it is the first
   real exercise of the Shopify read. Expect to fix something in
   `_fetch_products_live`.
2. **Expose the skills.** A `/admin/skill/<key>` route and one agent tool
   (`run_skill`) whose description is generated from `skill.catalogue(tenant)`,
   so the agent picks a skill by name and never picks context.
3. **Approve the 7 objections and set a voice tone.** Console work, no code, and
   it changes more about what the system can do than the last ten commits.
4. **Steps 05/06** — visual identity, then media. Only when Baci needs imagery.

**Verify:** run the suites in two batches. `test_tenant_isolation.py` must pass
**unmodified**.

**Standing preamble for a new thread:** worktree
`/Users/gomehsaias/Documents/gomehagent-build`, branch
`feat/context-architecture`. The other clone (`~/Documents/gomehagent`) is on
`feat/warehouse-picklist`, a pre-kernel base — **never push from there.** Render
auto-deploys `main`; git needs the sandbox off; always fetch and verify a
fast-forward before pushing. Deploys usually land in 60–90s but have taken 6+
minutes — check `/health` for the commit rather than theorising.
