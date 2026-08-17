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

## Rejection repairs itself — the QA layer

A validator that only says no teaches nothing. It files a blocked item and
leaves a hole for a human to patch, one output at a time, forever — and a queue
of human rewrites is not quality assurance, it is the same mistake repeated with
a person absorbing it.

`Context.emit(redraft=...)` closes that. A failing draft is handed its own
failures — each already carrying a `fix`, which was never decoration — and asked
again, up to `MAX_REPAIRS` (3). **The rule is never relaxed to achieve this:**
every repaired attempt goes through the same deterministic check, and a draft
that cannot be fixed is still blocked. What changes is that the system explains
and adjusts before giving up, and the attempt history is on the record.

Three states now, not two. `repaired` marks a rejected attempt a later one
fixed; `superseded` marks attempts on a run that failed anyway; `blocked` still
means an output was lost. Keeping them apart matters because
`blocked_reasons()` ranks the KB backlog by what actually cost output —
counting self-corrections there would inflate it with problems already solved.

**A terminal failure names missing knowledge, not a review task.** `_NEEDS` maps
each validator rule to the KB row that would have prevented it, and the gap is
filed through `kb.record_unknowns` so it surfaces in the queue the operator
already works. Rules a rewrite genuinely can solve (`banned_claim`, `repeat`)
are deliberately absent from that map and produce no knowledge task. The fix
then holds for every future draft rather than being applied to one by hand.

`/admin/agent_emit` returns the same thing as `retry` for an outside skill:
what to change, how many attempts are advised, an explicit "do not relax the
rule or send anyway", and — when no wording can work — the instruction to stop
rewriting and report the missing knowledge.

## The learning loop turns

`SystemRun.decision` is written at last. `Approval` carried `system_id` and
`run_id` from the start and **nothing ever populated either side**:
`request_approval` did not accept them and `apply_decision` did not write back.
So `systems.stats()` reported zero decided runs for every system forever,
`can_promote` could never clear its 20-run gate, and the autonomy ladder was
capped at `approve_all` in production. Both halves are now wired, and `emit`
queues an approval against the run whenever the rung asks for one.

That queueing is `notify=False` deliberately. A skill emitting thirty items
would otherwise fire thirty notifications, and this codebase has had that
incident: a poller re-triggered a slow endpoint, ~200 queued drafts went out at
400 sends/minute, Meta rate-limited the pair, ~200 fallback emails landed in a
minute. The existing digest poller batches and caps; nothing in the substrate
sends directly.

## Omnisend: the send path exists

Connecting Omnisend used to switch on `esp` and nothing else — `campaign_email`
could install, pass readiness, go live in shadow and have no way to put an email
anywhere. `app/omnisend.py` closes that, built against the shapes read from the
live Omnisend MCP rather than guessed.

The API's shape happens to match the architecture: **a campaign is created as a
draft and sending it is a different endpoint.** `draft_from_html` imports
finished HTML as a template (required even for a draft — Omnisend rejects a
create without one and saves nothing), then creates the campaign. Nothing sends
as a side effect of producing something. `send_campaign` takes `confirm=True`
and **the substrate never calls it**: an email campaign is irreversible and
lands in thousands of inboxes at once, which is not what `auto` was ever
supposed to mean.

Two rules taken from Omnisend's own docs because getting them wrong is
expensive: `senderEmail`/`replyToEmail` are always omitted so the brand's
verified sender applies — an invented or copied address is rejected, and 422
`sender-email-not-available` is surfaced as a question for the owner rather than
retried; and `language` is left unset rather than guessed.

`test_omnisend.py` (20 checks) drives a stubbed transport and asserts the
REQUEST: template before campaign, fields nested under `content.email`, no
sender address invented, no schedule, no locale, sending refused without
confirmation, and a half-finished run naming the template it orphaned.

**Unproven:** no call has been made against a real Omnisend account.

## Claim scope: individual, group, brand-wide

Scope was binary — one entity or the whole brand — so "every Aqua pitcher is
acrylic" could only be filed once per pitcher. That is not a review backlog,
it is the schema having no way to say what is true: brand-wide would be false,
because the porcelain lines are not acrylic. A dozen rows saying one thing was
the only expressible answer.

`KbEntity.parent_keys` adds the middle. A collection is an entity in its own
right (`type="collection"`), members point at it, and `claims()` widens to the
ancestor chain — so one row against `aqua` serves every member and never
reaches Mamma Mia porcelain.

**A LIST, not one parent**, and the live catalogue is why. Baci's 40 Shopify
collections group along three independent axes at once: range (`aqua`,
`mamma-mia`, `joke`…), material (`porcelain` 111, `melamine` 89,
`acrylics-polycarbonate` 43) and type (`italian-pitchers-carafes`,
`charcuterie-boards`…). A white Aqua pitcher is in all three, and the material
claim belongs to the material group while a palette claim belongs to the range.
A single parent would have forced choosing which kind of fact can be said once.
Membership is additive: joining one group never evicts another.

**Collection import is opt-in, and that is a safety property.** `sync_collections`
files every Shopify collection as an entity — always safe — but only the ones
named in `adopt` get members. Baci's list is half merchandising: `all` (341),
`featured-items`, `baci-summer-collections` (210), and one literally titled
"New! Shopify performance sharing is now turned on" (343). A group claim is
asserted about every member and inherited silently, so auto-assigning parentage
would have scoped material claims to a tracking collection with nothing to catch
it. `/admin/collections_sync` with no `adopt` lists what is available;
`/admin/entity_group` is the manual path for what the import cannot decide.

**Precedence is relevance, then specificity, then strength.** Relevance leads
because a claim answering the question asked beats a narrower one about
something else. Specificity decides everything after that, and it is a
correctness rule rather than a preference: the narrower the scope, the more
precisely the fact was checked against the thing being written about. It also
replaces a tie that used to be broken by row insertion order.

**Conflicts are flagged, never resolved.** Two claims covering one situation at
different scopes is either a refinement — specificity winning, as designed — or
a contradiction, and code cannot tell those apart. `scope_conflicts()` reports
the pair, names which would be selected, and says to check. Keyed on the pair of
claims rather than on the entity that revealed it: one collection-versus-brand
overlap is true of every member, and reporting it per member turns a single
decision into forty rows. Widest blast radius first. Computed, never stored, for
the same reason the duplicate sweep is.

Two bugs found by running it. The loop guard was checked *after* the write and
against the row's own ancestry — but `ancestors` stops when it revisits a key,
so a walk ending in a cycle looks identical to one reaching the top, and the
guard silently passed. It now asks, before writing, whether the proposed parent
already sits inside this row. And `scope_conflicts` first used `claims()`, which
returns brand-wide rows only when called without an entity — right for
selection, useless here, and it reported no conflicts at all.

## The creative library — foundation only

Generative-with-references, as agreed. What landed is the substrate the
generator will stand on, not the generator.

**`KbAsset`, and `rights` is a gate rather than a label.** A competitor's ad
saved for inspiration and a photograph the client owns are the same shape — a
URL with tags on it — so if convention is the only thing keeping the first out
of a published campaign, it eventually goes out in one. `rights` has **no
column default**, exactly like `review`: anything that is not literally
`owned` reads as reference. `add_asset` refuses rather than guessing, the
default read returns publishable assets only, and `ledger.publish` re-checks at
the last moment it still can — the media on an output may have been chosen by a
generator several steps upstream, so trusting whoever attached it is not enough.

**Both feedback signals are wired.** Publishing an output credits the assets
behind it (`uses`, `last_used_at`) — collected as a side effect rather than as
its own step, because a signal that must be remembered is missing exactly when
somebody asks which creative worked. Results land per channel via
`record_asset_outcome`, never flattened to one score: a creative that earns its
keep on Meta and dies in email has said something specific, and averaging
destroys it. `proven_assets()` ranks by either.

**`KbBrand.visual` — the half that was missing.** The brand row was entirely
verbal: positioning, elevator, voice, banned claims. Colours, type and logos
live in the Canva brand kit and are deliberately NOT duplicated here. What no
brand kit holds is art direction — "styled on a laid table", "never a face",
"no props we do not sell" — which is the visual equivalent of
`voice.never_say`. Without it a generative path has nothing to be wrong
against.

**Canva, checked live:** connector authenticated, 1 brand kit, 1 brand template
(*CM Post-Call Follow Up*, a presentation, unrelated), **0 autofill-capable
templates**. So the template-driven path has connectivity and no substrate,
which is why generative-first is the right call — templates become references
as they get made.

`set_brand` now derives its writable set from the model. The hand-written one
had already gone stale on `visual`, and since its refusal is a return value
most callers ignore, the field was silently unwritable and the brand row was
never created. Rule 4, met again.

**Not built:** the generator itself, the Canva/Ryze calls, the join from an
output to a channel's ad id (so `record_asset_outcome` is fed by hand today),
and any UI for the library.

## Installing a system is no longer a guess

The Systems tab had an install form: two dropdowns and a button. It listed every
catalogue system whether or not it was already installed, and said nothing about
what any of them needed — so you picked one, installed it, and only then read
the refusal on its own card.

It is now a per-account list. Every catalogue system, sorted so what can be
switched on now comes first, each showing its prerequisites as ✓/✗ chips before
you commit. `systems.prerequisites()` answers the same question `ready()` does
but for a system that is NOT yet installed, and returns the items separately
rather than as prose — because a missing connection is a credential to go and
wire and a missing knowledge field is something to go and write, and one
sentence lumping them together is exactly what made the dropdown a guess.

The 8-part contract is deliberately not a prerequisite. It gates going LIVE, not
installing: a system starts in shadow with an empty contract on purpose, so the
contract gets filled while looking at the thing rather than as a toll gate
before seeing it. A blocked system can still be installed — "Install anyway",
with what it is waiting on named underneath — because a system in shadow with a
gap is a useful thing to look at, and greying the button out would hide the
list that says what to fix.

Found while building it: `.bulkbar` used `var(--card)`, which this stylesheet
does not define. The sticky batch-approval bar had no background, so the review
queue scrolled visibly behind it. All three tabs now sweep clean for undefined
CSS variables.

## Working the review queue

Three workflow defects, all of them reasons a queue of forty proposals stops
being read rather than reasons it is wrong.

**Deciding is now batched.** Every proposal card carries a checkbox bound to a
single bulk form through the HTML5 `form` attribute — forms cannot nest, and
duplicating the queue into a compact list would mean deciding against a summary
instead of against the claim. Approve or reject any selection in one request.
Individual decisions return to `#c-<next-id>`, so approving walks DOWN the queue
instead of bouncing to the top of the page each time, which is what made forty
decisions cost forty scrolls.

**Brand-level duplicates collapse in one action.** The mass harvest filed the
same fact once per product page, so approving the brand-level copy left a dozen
narrower ones behind that add nothing — a brand-level claim is already usable in
content about every entity. `kb.brand_level_duplicates` finds them and one
button retires the lot. It recomputes server-side rather than trusting the list
the browser assembled, because the page may have rendered before the last
approval landed.

**Entities are findable.** A datalist filters on the option VALUE, so a list of
bare slugs could only ever be searched by slug — and a reviewer looking at a
claim about the Aqua dinner plate knows "aqua", not `bm-aq-din-25`.
`kb.resolve_entity_ref` accepts the key, the display name, the combined label
the picker emits, or a unique partial of either, in any word order. Ambiguity is
reported with the candidates named rather than guessed at: scoping a claim to
the wrong product is worse than leaving it brand-level, because it will then be
used confidently in content about something else. An unmatched entity is
refused instead of written through, where it would have surfaced much later as
"not selectable" far from its cause.

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
