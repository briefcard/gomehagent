# Build state — after the wiring audit

The rolling state of the data-layer build. **This file is rewritten by every
thread.** It is always current and never historical — do not add dated sections,
and do not create `HANDOFF-step-N.md` files. History lives in `DEFECTS.md`
(append-only) and in the git log.

That rule was broken. The previous rewrite replaced the top five sections and
left the tail, so this file simultaneously claimed 33 and 41 suites, named a
commit that had been superseded, said "committed, NOT pushed" about work that
was live, and listed a "next thread" of items already built. **If you are
rewriting this file, replace the whole thing or say which sections you did
not.** A stale handoff costs more than no handoff, because it is trusted.

`HANDOFF-content-platform.md` is the **historical** record up to 2026-08-13 and
is no longer maintained. Parts of it are actively wrong. Read it for background,
never for state.

**Live:** everything below is pushed and deployed at `647502d`. `/health`
reports `commit` and `routes` — use it, never infer what is running.
`/health/connections` is unauthenticated and live-tests Shopify and Google.

## Start here if you are new to this thread

Read this file, then `DEFECTS.md` §1 (the recurring patterns) and §3 (what is
still broken). Then run the suites:

    for f in scripts/test_*.py; do
      [ "$(basename $f)" = "test_brief.py" ] && continue
      r=$(python3 "$f" 2>&1 | tail -3)
      echo "$r" | grep -qE "all checks passed|all green" || echo "FAIL $(basename $f)"
    done

**54 suites, 54 pass.** Check the OUTPUT, not the exit code, and skip
`test_brief.py`. That file is not a test — it is an argparse CLI for inspecting
the brief assembler, it exits 0 whatever happens, and every "41 suites pass"
claim in this file's history was counting a help screen as a passing test. The
whole run takes ~4 minutes; a single shell call may time out at 2.

**Deploy is push-to-main.** SSH alias `github-gomehagent`, key
`~/.ssh/gomehagent_deploy`, and git network calls need the sandbox disabled.
Always `git fetch` and confirm a fast-forward first. Render swaps in ~2 minutes.

## The one thing to understand about this codebase

Every layer refuses rather than guesses, and every refusal names the missing
thing. That is not a style — it is the accumulated result of the defects in
`DEFECTS.md`, most of which were an unknown quietly collapsing into a value.
When you add something, the question to ask is "what does this do when it does
not know", and the answer must survive all the way to the output.

**With one correction the owner made on 2026-08-18, and it is load-bearing:**
refusing is for output that would be UNSAFE or FALSE, never for output that
would merely be thinner. *"There should be NO block because of a lack of data.
If it's not there, then don't use it. The idea was never to stop the AI from
responding, it's to guide it on how to answer correctly in an organized way."*
Absent knowledge is now a label on the work, not a gate in front of it. See
**Gating**.

## What is proven and what is not

**Proven against real systems:** Shopify reads (both stores), Google/Gmail/Drive
(three accounts), the site crawler against miamiironside.com — 162 pages, 11
claims, 56 images, 3 new situation tags. The console rendered against a fresh
instance with nothing configured, both connect surfaces.

**Built and NEVER called for real:** Omnisend, Constant Contact, Canva, the
OpenAI image API, and every OAuth leg. Each needs a key and one live call.
Every assumption that has been tested against a real API so far has been wrong
in some detail, so expect the first live run of each to find something.

**Gomeh's live tests have corrected this build four times.** Canva's generator
invents products rather than using a supplied asset; `gpt-image-1`'s mask is
advisory rather than binding; the logo filter was written against imagined
filenames; WordPress could not connect because the probe did not follow
redirects. All four are in `DEFECTS.md` with the measurements.

## Where we are

The data layer is a substrate an agent can be given, it can be connected to
without a runbook, and — new — it can now show what it did. What it still
mostly is not is *wired into the things that run every day*. That gap is the
subject of the audit below and should drive the next several threads.

## The five rules this codebase keeps re-learning

Every one was a real defect, several of them twice. Read before changing
anything.

1. **Absence is a third state and must survive to the output.** Met nine times
   now. Two more this session: an assurance window with no events reports
   "nothing has been checked", never zeros — a clean system and an unmonitored
   one produce identical zeros and mean opposite things — and a claim with no
   timestamp is `undatable`, which is neither current nor expired, because a
   gap in our bookkeeping is not evidence the claim went false.
2. **Enrich, do not gatekeep.** §2.27 was this rule broken at its most
   expensive point. The gating change below is the same rule applied one layer
   up, and it took the owner to see it.
3. **Approved is final, whatever wrote it first.**
4. **Derive lists from the schema, never by hand.** Met twice more this session:
   `oauth.configured` was a per-provider ternary that told Canva to set the
   *Meta* app secret, and `reset.py`'s unclassified report caught a new table
   one commit after it caught the last one.
5. **Run it before claiming it works.** Including claims made in this file.

## Gating — the structural change of 2026-08-18

`systems.ready()` was answering two different questions with one bar: "may this
act unsupervised" (go-live, promotion) and, through `skill.preflight`, "may this
produce anything at all". A blank 8-part contract and a thin knowledge base are
correct blockers for the first and absurd for the second. That is why an
unapproved objection stood between a customer and a reply.

* `ready()` keeps the full bar, for **go-live and promotion only**.
* `can_produce` blocks on **an absent connection and nothing else** — the one
  gap that makes producing impossible rather than thinner. You cannot answer
  mail you cannot fetch.
* Everything else becomes `thin`: noted on the run, returned on the result, and
  filed through `kb.record_unknowns` so it lands in the queue the operator
  already works.

**One deliberate exception.** `Skill.constitutive` names knowledge whose absence
makes an output FALSE rather than thinner. `catalog_compliance` declares
`banned_claims`, because a sweep against an empty ban list reports a catalogue
CLEAN that nothing checked — and Baci's own audit is 110 violations such a sweep
would have blessed. Almost always empty. The test before reaching for it is
"would the output be a LIE without this"; "it would be vaguer" is a no.

**What this changes strategically.** Content is no longer a prerequisite for
producing — it is a quality dial. A client can be onboarded and produce on day
one, thinly and honestly labelled, and the knowledge queue fills from real runs
instead of from an interview. The old order (fill the KB, then switch it on) is
dead; the new order is switch it on, watch what it says it was missing, fill
that.

## Assurance — can you tell it is doing anything?

`app/assurance.py` and the Assurance tab. Every validation is recorded, pass or
fail, at all three places a draft is actually checked: the substrate
(`Context.emit`, including each repair attempt), the skill bridge, and
`triage.py`. A log of only failures cannot show coverage.

The mail path's check is filed as `banned_claims_substring`, deliberately not
`banned_claims` — see the audit below.

**What it reports, ordered by how much each number can be trusted:**

1. **Catches.** A real counterfactual: the model wrote the phrase, deterministic
   code stopped it, without the layer it goes out. Needs no interpretation.
2. **Coverage** by source.
3. **Grounding and repair** — share of drafts carrying a `claim_id`; repairs
   attempted, fixed, still blocked.
4. **"Is it improving the output?"** — and here it says plainly that it cannot
   tell you yet.

**The measurement gap, stated because hiding it is the whole failure mode.**
`SystemRun.edit_diff` — whose own docstring calls it *"the highest-value column
here… the only honest signal of where the generator is wrong"* — is declared,
is on `finish_run`'s writable list, and **has never been written by anything**.
So `edited_share()` reports coverage first and a NULL rate with a note calling
it an instrumentation gap. Reporting 0% edited would be the lie that flatters
this the most. Closing it needs either an editable body on the approval
(`apply_decision` takes only a decision today) or, better, capturing sent-vs-
draft in Gmail, which is where editing actually happens.

`scripts/ab_context.py` is the real A/B and **has still never been run**:

    ANTHROPIC_API_KEY=… DATABASE_URL=… python3 scripts/ab_context.py baci

## Diagnostics — where it broke, and at which layer

New tab, new `app/diagnostics.py`, 2026-08-19. Assurance answers *is the output
safe*. Nothing answered *is this running, and if not where did it stop* — the
question you actually have when something is wrong, and it was spread across
four tables nobody joined: `SystemRun` (what the pipeline did), `ToolCall` (what
their platforms said), `AssuranceEvent` (what the validator did to the draft),
`Approval` (whether a person ever decided). One of those tells you an outcome;
the four in time order tell you a cause.

**Three layers, and they are constantly mistaken for each other.**

* **functionality** — the call did not come back. Dead token, 500, or a
  `tool_scope` refusal because the account never connected that platform.
* **logic** — everything worked and the result was still refused or caught: a
  run blocked on missing knowledge, a validator catch, a repair that could not.
* **performance** — it worked, and it was slow or expensive.

Every event is classified into one on the record rather than in the reader's
head, because *"the system is broken"* is usually a blocked run, which is the
system working exactly as designed. `blocked` and `failed` are counted apart for
the same reason: one sends you to the knowledge queue and the other to the code
or a connection, and a single pass-rate covering both sends you to neither.

**What it shows, in the order somebody triaging works.** Per-system verdict
(did it run, did it finish, what refused), then the platforms (failure RATE
first — a provider failing most of the time is a broken connection, one failing
occasionally is the internet), then model spend beside latency because slow and
expensive are the two ways a working system is still a problem, then the log.
The log is chronological because a log must be, with a **problems only** filter
that takes failures AND warnings together — "failures" alone hides the blocked
runs, which is where most breakdowns surface first. Filter counts are computed
from the unfiltered window, or every chip would describe itself.

**It stores nothing and calls nothing.** Every figure is computed from rows
other layers already wrote, so it can be wrong about an interpretation and never
about a fact, and switching it off loses no data. Same rule as
`client_report.assemble`: opening a diagnostics page must not be the moment a
dead token is discovered, and a page that half-fails while reporting on failures
is worse than one built from the record.

**Absence, again.** A silent account reports *nothing at all was recorded — no
run, no tool call, no check, no approval; that is a finding about the plumbing,
not a clean report*. A system with no finished run says duration cannot be
computed rather than showing a blank that reads as fast. A run open past
`STALE_RUN_HOURS` with no terminal stage is `unfinished` and points at the
worker — which is a different finding from `failed`, since that at least
recorded why. And runs filed against a system id nothing owns are surfaced as
their own warning rather than dropped: a system deleted under a live pipeline
and a run written with the wrong id are both worth knowing.

**Two things deliberately NOT measured, named in the output.** There is no
per-step timing inside a run — `SystemRun` has `created_at` and `finished_at`
and nothing between — so "which stage was slow" is unanswerable, only "the run
took this long". And a tool call records a round trip, not a queue wait, so a
slow tool and a slow provider are indistinguishable from here.

**Live is opt-in and off by default** — `live=15|60` sets a meta refresh, and
the filters travel with it so a reload does not undo the narrowing you just
did. Safe to poll here in a way this codebase learned the hard way most
endpoints are not: `report()` calls nothing and writes nothing, so a reload
cannot re-trigger work. The suite asserts that reading it twice changes
nothing, because the incident behind that rule — a poller re-firing a slow
side-effectful endpoint until ~200 queued drafts went out at 400 sends/minute —
started as a page that looked exactly this harmless.

Also at `/admin/diagnostics` as JSON, where `tenant` is REQUIRED and `*` is the
explicit all-accounts value: an absent account would have to mean either "all"
or "the first one", and a monitoring feed guessing between those watches the
wrong client. `scripts/test_diagnostics.py`, 46 checks, seeded on two accounts
so a leak fails rather than passing an empty table — verified by removing the
scope clause and watching fourteen assertions fail.

**Unproven:** built and read against seeded data only. No real breakdown has
been diagnosed with it yet, and the first one will find something — every
assumption in this codebase tested against reality so far has been wrong in some
detail.

## Time — claims expire, and so do answers

Two problems that look like one. Owner raised them together and they need
opposite treatments, which is the whole reason this section exists.

### Claims expire by default

`KbClaim.expires_at` had existed since the knowledge layer was built, was
honoured by three readers, and **could not be set by anything** — no parameter,
no route, no form. Every claim in every account lived for ever behind a gate
that looked like it worked. §2.35.

`kb.claim_expiry(row)` is now the single calculation all three readers share, so
no caller can disagree about whether a claim still stands. THREE states:

* **`dated`** — the default. Due `CLAIM_TTL_DAYS` (365) after it was last
  verified, **even with `expires_at` unset**. That derived interval is what
  makes "expires by default" real rather than aspirational.
* **`timeless`** — only via `set_claim_expiry(id, never=True)`. Somebody
  decided. The empty policy value means "expires normally", never "undecided",
  which is why the column has no default: auto-migration writes a default onto
  every existing row and a value nobody chose must not read as one somebody did.
* **`undatable`** — approved, but no `verified_at` and no `approved_at`, so the
  date cannot be worked out. **Not expired.** A missing timestamp is our
  bookkeeping gap, not evidence the claim went false; dropping it would destroy
  real proof to punish that. Stays selectable, listed for somebody to date.

**Expiring means being asked, not vanishing.** `kb.expire_due` returns due
claims to `proposed`, keeping `approved_at` — so the queue asks "you approved
this on 12 August and it came due, still true?" rather than "is this true?"
asked cold. The card renders that instead of showing a came-due claim as a fresh
proposal, with a "This one never expires" button that marks it timeless and
approves in one move.

**The sweep reports before it moves anything, once per account.** A knowledge
base nobody has dated finds every claim older than a year at the same moment,
and forty approved claims quietly reopening overnight is a surprise even when it
is correct. This codebase has had the other kind of incident.

§2.36 is worth reading: approving a due claim stamped `approved_at` but not
`verified_at`, and expiry reads `verified_at` first — so the same claims would
have returned to the queue every week for ever. A state machine that moves a row
between two states needs a test that runs the cycle twice.

### Answers expire too, and that is a different mechanism

The owner's case was a cup answered out-of-stock, and the instinct was to date
the claim. But stock was never a claim: `resolve` declares it in `needs_lookup`
and `responder` refuses to answer it from knowledge, so it is read from the
store at the moment of asking.

The gap was the REPLY. It sits in the ledger, comes back as prior correspondence
for a follow-up, and reads exactly as true in September as it was in August —
nothing in a sentence marks which half was a reading and which half was a brand
fact.

So the OUTPUT is asked instead of the sentence. `lookups.STALE_AFTER_HOURS`
makes the registry's own prose ("stock is true at the moment of asking and stale
by lunchtime") into a value with an import-time guard; `Output.lookups` records
which lookups fed a body; `ledger.perishable` flags a reply whose live facts
have aged; `resolve` files it beside the correspondence.

**Flagged, never hidden or corrected.** What was said is a fact about the
conversation and stays true whatever the stock does now.

Written by **four** call sites, because a column written by one of two writers
is a column written by none: both of `responder`'s ledger writes (the approved
path AND draft-from-context, which leans hardest on live data), `Context.emit`,
and `skill_pack.inbound_reply`. The tools recorded are the ones the bundle
DECLARED rather than the keys of `facts` — sound rather than convenient, because
the responder refuses to proceed while a declared lookup is unanswered, so
arriving there with facts means those lookups were called.

## Reporting — what the tools did, and what a client is told

Built for the client report Gomeh will send, which is a higher bar than an
internal dashboard: every number needs a source, and anything unmeasurable has
to SAY SO rather than be quietly left out. A report with a visible hole is
recoverable; one that implies completeness it does not have is not.

**`ToolCall` is the ledger that was missing.** `Usage` recorded what the model
cost; nothing recorded what the tools DID — so "is this client's Shopify
actually being read", "when did their Search Console start failing" and "what
did we do for them in October" were answerable only from memory.

Instrumented at TWO chokepoints, not sprinkled:

* `kernel._dispatch` — every agent tool, tenant already resolved. A
  `tool_scope` REFUSAL is recorded as a failed call: "this account asked for a
  capability it has not connected" is exactly what a report should surface, and
  dropping it makes a blocked account look idle.
* The three adapters' `call` seams, via `toolcalls.instrument()`. One wrapper
  rather than three patched bodies — and because the suites replace that same
  seam, an instrumented build under test records nothing, so the tests stay
  honest about what they drive.

**Two privacy decisions, both asserted by the suite.** The ledger stores a SIZE
and a verdict, never a payload — a tool result is the client's own orders and
mail, and a second copy here would have none of the scoping the first one has;
the test checks there is no column a body could go into. And paths are stripped
of id-bearing segments, so `/orders/1234` records as `GET /orders` — otherwise
every call is unique, ungroupable, and carries the client's order numbers.

**`client_report.assemble()`** at `/admin/client_report`. Work (runs, produced,
blocked, self-corrected), reach (which platforms were READ — a fact about the
work, where "connected" is a fact about a settings page), and blocked, ranked by
what it cost.

It **calls nothing**. Assembling a report must not be the moment a dead Shopify
token is discovered, and a report that takes forty seconds and half-fails is
worse than one built from the record.

The section to read is `not_yet_measured`: every figure we cannot produce,
named IN THE OUTPUT with its reason and its fix. A report that silently omits
revenue reads as "we did not move revenue"; one that says the figure is not
wired reads as what it is. Kept as data so the console can render it as a to-do
somebody deletes, rather than a paragraph nobody updates.

**The honest gap:** live platform figures — revenue, sessions, ad spend, sends
— need the `reports` system, which is declared in `systems.CATALOG` and still
unbuilt. That is the next real piece if these reports are to carry a number the
client already believes.

### Two audiences, declared per system

Owner's framing: *"for each of these systems there are technical reports and
business reports"*. Technical answers "is this working" and belongs to us;
business answers "what did it do for me" and is what the client pays for. A
report leading with validator counts is a report about ourselves.

`metrics.CATALOG` is a row per metric with a `kind` and a `source`, so adding
one is data and the assembler never grows a clause. Four sources, and the last
two are the honest ones:

* `ledger` / `kb` / `assurance` — we compute it from our own record.
* `provider` — their platform holds it; needs the unbuilt `reports` system.
* `blocked` — computable if something upstream existed. **`% drafts sent as-is`
  needs `edit_diff`**, which nothing writes: the metric the owner named is
  exactly what the missing column was for.
* `asked` — no connection could answer it, so it is genuinely theirs.

The first version of `asked` was WRONG and the correction is worth keeping.
It asked "what does one support reply cost you in staff time" — owner:
*"they won't have that answer"*. Right, and the mistake has a name: that is an
ops-accounting question we wanted answered so we could derive a number
OURSELVES. Asking a client to do our arithmetic gets no reply and deserves
none. What a client can recite from memory is their top line: revenue, AOV,
booked calls, closed leads.

Nothing unmeasurable is dropped from the output. Skipping it makes a short
report look complete.

### Outcomes belong to the business, not the system

`Tenant.business_model` decides which headline numbers a report carries —
vocabulary reused from `kb.SITUATIONS`' "who they are" set rather than a second
taxonomy. The five accounts are classified.

    baci       ecom_inventory    revenue · orders · AOV · returning share
    ironside   local_venue       enquiries · calls · events · avg event value
    coverings  b2b_spec          samples · quotes · projects won · avg value
    agency     digital_products  leads · calls · closed · avg contract value

The suite asserts the venue and shop vocabularies DO NOT OVERLAP. Reporting a
venue's "average order value" is not a small error — it is the client
concluding we do not know what their business is. An unclassified account
reports that, rather than being handed a shop's vocabulary by default.

Outcomes are account-level and do NOT depend on which systems are installed: a
client's headline numbers are facts about their business. Coverings has nothing
installed and is still a b2b_spec business with projects won.

**The create form asks for it**, with options read off `metrics.OUTCOMES`
rather than typed into the template — a hand-kept second list is how a model
reaches the dropdown that the report has no vocabulary for. Validated on BOTH
write paths (`tenant_add` and `tenant_set`), because a field settable two ways
and checked on one gets set wrong through the other. A typo is refused and the
account is NOT created: a bad value here is silent, and the account looks fine
on every screen until a report fails in a document already sent. Omitting it
warns rather than blocks — refusing would stop onboarding over a question that
can wait an hour, and saying nothing is how it waits for ever.

**We never ask for what we could read.** Three states, and the middle one is
the point: `asked` (no connection could answer it), `not wired` (the capability
IS connected, so this is OURS and the missing `reports` system is our gap —
never asked), and supplied. With Shopify connected, Baci's revenue moves to
"ours to read" and drops off the ask list entirely. Asking a client for a
number we already have access to is asking them to do our work.

### The privacy path is the same mechanism

A client who declines to connect is not a client with a hole in their report —
their figures move to `asked`, and `metrics.request_email` composes ONE message
rather than one per figure. Somebody already choosing friction will not answer
five emails. Every ask carries WHY, because "what does a support reply cost you
in staff time" reads as odd until it is followed by "we multiply it by the
replies we answered", and it closes by offering to connect instead so the ask is
not permanent. **Composed, never sent** — `queue=True` puts it in the approval
queue.

Two rules the suite pins. A supplied figure is stored **as given, never
coerced**: "about £18, maybe £20 at peak" tells us something a float destroys,
and a report can say "£18 (their estimate)" but cannot say that from `18.0`.
And **the period is part of a figure's identity** — a supplied number whose
period has lapsed returns to unanswered rather than being carried forward,
because carrying it is how a report becomes fiction the client signed off on.

`service_desk` is worked through against the owner's own list.
`catalog_compliance`, `campaign_email` and `ad_creative` have starter
declarations and want the same pass — their business metrics are the owner's to
name.

## The client portal, and the boundary under it

Owner is putting clients into a UI. The console had exactly two credentials —
`APPROVAL_SECRET` and `READ_KEY` — and NEITHER is scoped to a client: `tenant=`
is a filter, not a permission, so anyone holding either could switch it and read
every account. `DEFECTS` has carried that as debt since the credential layer
landed. It stopped being theoretical the moment a client would log in, so the
boundary was built BEFORE any visual work; no amount of design makes an
unscoped console safe.

**The rule everything rests on:** a client's account comes from their SESSION,
never from the URL. `portal.resolve_tenant` is the one function every portal
view goes through, and a mismatched `tenant=` is REFUSED BY NAME rather than
silently corrected — a substitution makes reading somebody else's data look
exactly like a stale bookmark, and only one of those is worth seeing. The tenant
sits inside the signature, so a hand-written cookie cannot move it.

**Sign-in is a single-use expiring link**, the same shape as `ConnectLink` and
`IntakeLink` — there were already two scoped, key-free links, and a third
mechanism for the same job is how they drift. No password store: the mailbox is
already the recovery channel for any such system.

Three refusals worth keeping: an unknown address gets nothing (self-registration
on a portal showing commercial data is not a feature), a user with no
`tenant_key` is refused (they would inherit the owner's unscoped view), and the
form ANSWERS IDENTICALLY for known and unknown addresses — a login page on the
open internet that confirms which addresses exist is a customer list.

**People management** is on the Accounts tab per client: add by email, toggle
read-only/full, revoke, mint a link. `User.access` defaults to `read_only`,
deliberately — the portal shows a client their own commercial data and lets them
send figures we print in a report, so access is something ADDED rather than
something forgotten to remove. Revoking also expires every unused link that
person holds; without that, one already in a mailbox outlives the revocation,
which is precisely the window somebody would use.

Read-only is enforced on BOTH sides: the field is hidden and `/portal/figure`
refuses server-side, because a form nobody is shown is still a form somebody can
post to.

**Sending is MANUAL, by the owner's choice**, and the copy says so. The page
reads "Request received — we have passed this to your account manager" rather
than "check your email", which would be a promise nothing keeps. The request
pings the ops channel WITH THE LINK READY, because otherwise it dies in a log
line and the client waits for mail that was never coming. An unknown address
pings too, differently — either a client using another address or somebody
probing, and both want a human to look.

### The owner console, same shape

Done too. The console used a horizontal tab bar and a SEPARATE client picker
inside four of the five tabs, which cost two things every day: the nav links
carried NO tenant, so moving between tabs silently dropped you back to the first
account and nothing said so; and with the picker below the fold you could read a
whole screen without seeing whose data it was — including the Connections
screen, whose buttons revoke credentials and mint client links.

The account is now chosen once in the sidebar, travels on every link, and is
named in a pill at the top of every page. Connections renders ONE account where
it used to stack all five. The four duplicate pickers are gone — two controls
for one decision is how they disagree. Nav is ordered the way a day runs:
Review, Knowledge, Systems, Assurance, Diagnostics, Connections, Data layer,
with a "Client view →" link to the portal for the selected account.

Same visual language as the portal, deliberately: switching between them should
not mean learning a second layout.

**The frame was moved and the bodies were not — finished 2026-08-19.** Three
tabs were still answering the "which account" question their own way, and the
Systems tab was answering it with "all of them": it rendered
`systems.all_systems()` grouped by client, so the sidebar picked which INSTALLER
you saw while the cards under it were five clients' autonomy rungs, kill
criteria and Guidance boxes, each with a form writing to a different account.
Assurance did the reverse — handed `tenant=""` whenever the URL carried none, it
reported every account's catches under the first account's name, on the one page
whose entire job is to be believed. And the "N waiting" counter counted every
account, so the number beside one client was another client's backlog and the
link opened everybody's queue. §2.40.

`admin_ui._account()` is now the single resolver, used by the frame AND by every
render — the pill and the numbers below it are computed from one value, so they
cannot disagree. The three leftover `picker = …` builds (constructed every
render, rendered nowhere since the duplicate pickers were deleted) are gone;
dead code that still reads plausible is how one comes back.

**Cross-account is a place you go on purpose.** `admin_ui.ALL` ("*") is an
explicit entry in the switcher, kept below a rule and apart from the clients.
An empty `tenant=` falls back to the FIRST ACCOUNT, never to everything — "all
accounts" and "the account I did not name" are different requests, and
answering the second with the first is the whole defect. Every all-accounts page
says so in a banner and in the pill, every row on one names the client it
belongs to, and the two screens whose forms write to a single account
(Connections, and the Systems installer) refuse to render on it at all.

**And an account is told apart by more than its name.** Each gets a hue —
spaced evenly across the accounts that exist rather than hashed from the key,
because five hashed samples out of 360 collided (`ironside` 231 and `coverings`
256 is the same blue to anybody not comparing them). It tints the selected row,
the pill and the rule under the page heading, and every account's dot carries
its own colour so the mapping is learnable from the list. The cost is stated
rather than hidden: adding a client re-colours the set. That is a one-off on a
list that gains a client every few months, against two indistinguishable blues
every day — and the name is on screen either way, so the colour is the second
signal and never the identifier.

**The test that said all of this was already true.** `test_console_frame.py`
asserted "the body is single-account" for every tab against a database holding a
brand row and nothing else — no system, no run, no approval, no assurance event.
The assertion was true of empty tables and passed for months while the Systems
tab leaked. Every account is now seeded with a row in each table a tab reads,
each carrying a marker only that account can produce; putting the old
`all_systems()` call back fails the suite by name. §2.41, and the fourth test
this codebase has caught passing for the wrong reason.

**A test that could not fail for its stated reason.** `test_oauth` fetched the
Accounts tab with no tenant and asserted a connected provider showed a green
chip — which passed only because the page stacked every account, so a credential
on ANY of them satisfied it. It was checking "some account somewhere is
connected". Retargeted at the account it actually stores one on. That is the
second such test this session; the other was the portal cookie over http.

**A trap worth knowing:** the session cookie is `secure=True`, so a `TestClient`
over http silently sends nothing and a test reads the signed-out page while
appearing to pass. `test_portal.py` pins `base_url="https://testserver"` and
says why.

## Drafts and approvals are one thing now

Owner: *"they should be in sync so that it's not a constant build up, whatever
gets sent in the end is approved, and we track the delta."*

A drafted reply used to produce TWO artefacts that never spoke: a Gmail draft,
and an approval built from a COPY of what that draft said when it was written.
Approving composed a THIRD message from that copy. So editing the draft in Gmail
changed nothing anybody sent; approving left the draft behind to accumulate; and
sending it yourself left the approval pending, where approving it later would
deliver the original text A SECOND TIME to the same customer on the same thread.

Now the draft id is kept on the approval and **approving sends the draft
itself**. Whatever goes out is what was approved, an edit made in Gmail travels
with it, and nothing is left behind.

The reverse is handled by `approvals.reconcile_drafts`, on a 20-minute tick: an
approval whose draft has vanished was dealt with in Gmail, so it closes as
`sent_outside` — not `approved`, which would claim we did something the owner
did. It only ever CLOSES approvals and never sends, so the worst case of a
misread is a closed approval rather than a mailed customer.

**`app/edits.py` records the delta**: `as_is`, `similarity`, `lines_changed`,
and a CAPPED sample — not the full text, because a second copy of every customer
reply is a data store nobody asked for. It writes `SystemRun.edit_diff`, the
last of the three declared-and-dead columns.

Two things the diff deliberately ignores. **Quoted history** — Gmail appends the
original to every reply, and counting it would make every send look wholly
rewritten. And **whitespace** — a stray space is not a correction, and treating
it as one reports the generator as worse than it is.

`% drafts sent as-is` is therefore no longer blocked, and reports as "7 of 9"
rather than a percentage: a percentage of three replies is not a rate, and
rounding it to one looks like a measurement.

**Unproven:** `read_draft` and `send_draft` are written against Gmail's
`drafts().get/send` and are STUBBED in the suite. No real Gmail call has been
made. Given this codebase's record with untested API assumptions, watch the
first real approval after drafts resume.

**Measured, NOT yet learned from.** This closes the measurement gap and nothing
more. No drafting path reads a delta, and `systems.feedback_block` — which
renders per-system Guidance for injection at drafting — STILL HAS NO CALLER, so
the Guidance box on the Systems card saves text that never reaches a prompt.
See plan item 1.

## The wiring audit — which entry points reach the data layer

Traced mechanically on 2026-08-18. This is the most important table in the file.

    entry point         reaches                    what it is
    command_agent.py    — NOTHING —                the kernel tool loop
    kernel.py           — NOTHING —                the model loop
    ops_jobs.py         — NOTHING —                scheduled jobs
    seo_tools.py        — NOTHING —                the SEO agent's tools
    shopify_seo.py      — NOTHING —                WRITES to the live store
    wordpress_seo.py    — NOTHING —                WRITES to the live site
    digest.py           — NOTHING —                what reaches the owner
    triage.py           kb                         inbound mail (weak check)
    worker.py           systems                    the cron tick
    skill.py            kb resolve validator ledger  the substrate
    web.py              everything                 console + bridge

**The inversion — FIXED 2026-08-19, and it was worse than described.**
`grep -c "banned|validator|compliance"` across `shopify_seo`, `wordpress_seo`
and `seo_tools` returned **0, 0, 0**, and those three are the only modules that
write to live customer-facing properties.

"SEO metadata" was the wrong description and it understated it. `update_seo`
writes `body_html` — real description copy — and on WordPress with
`resource="post"` it replaces an article's ENTIRE `content`. See **The blog
path** below; `app/seo_guard.py` now stands in front of all of it, and the same
grep returns 10 and 8.

**Two mail paths, and only one is guarded.** `worker.py:108 → triage.triage_email`
checks banned claims and escalates. `command_agent → queue_email_draft` — the
model composing a draft in the tool loop — checks nothing. And the guarded one
uses a plain substring test while `validator._banned` next door matches on word
boundaries with flexible separators: today "hand-decorated" is caught, "hand
decorated" walks through, and "artisan" false-fires inside "artisanal".

**Smaller findings.** `_fetch_products_live` raises `KeyError` instead of
refusing by name. Two orphan columns (`KbUnknown.first_seen`,
`KbConflict.first_seen`). Otherwise the column layer is clean, all kernel tools
have handlers, and `_GOOGLE_TOOLS` has not drifted.

**The unreachable-function count was WRONG the first time, and how it was wrong
is the useful part.** The first pass globbed `app/*.py` and never recursed into
`app/roles/` — which is exactly where the roles wire their tools and context
blocks. So `seo_tools.seo_context_block` was reported as dead when
`roles/seo.py` passes it as `extra_context=` and it is injected every turn. Redo
any repo-wide sweep with `app/**/*.py` and diff it against the last one; a
survey that under-reads its own corpus produces confident findings about code it
never looked at.

Corrected list, five remaining after this session wired one and deleted two:
`canva.export_result`, `omnisend.upload_image`,
`baci_backoffice.list_company_documents`, `ops_jobs.file_whatsapp_document`,
`propose.from_gap`. These are unfinished features rather than dead weight —
deleting them throws away real work. Note both halves of the Canva export path
(`export` and `export_result`) are unwired, so it is incomplete rather than
broken.

## The blog path

Owner: *"we need to go through the blog path for shopify and we should have a
path to both review and revise existing articles and to extend our articles by
writing new ones"*.

Nothing in `shopify_seo` had ever touched `blogs/{id}/articles.json`, so the
entire content half of an SEO plan had no publish path on Shopify at all.
`list_blogs`, `list_articles`, `get_article`, `create_article`,
`update_article`.

**WordPress could revise but never create.** `update_seo(resource="post")`
revises an existing post; `create_page` writes to the `pages` endpoint. So the
`blog` system — declared in `CATALOG`, installed on Ironside — had no way to
publish a new article. It has the same five functions now, in the same shape,
because `sites.backend()` is duck-typed and a missing one is an AttributeError
mid-publish. The suite checks all five exist on both.

Three decisions worth keeping:

* **`get_article` returns the full body.** A revision that has not read the
  current text is a rewrite, and rewriting a page that already ranks is how a
  site loses the position it had.
* **`update_article` is partial.** A revision that sends every field rewrites
  the ones it was not asked to change, and an untouched `body_html` arriving as
  `""` would blank a live page.
* **A new article is a DRAFT unless `published` is explicitly true.** This is
  the one call that can put prose nobody has read on a public site. Note
  `create_page` beside it still publishes immediately — a separate pre-existing
  decision, left alone rather than changed quietly.

## Connecting a client — now possible entirely from the console

Seven providers, all rendered on both the Accounts tab and the client
`/connect/<token>` page. Audited by booting a fresh instance with nothing
configured and reading the rendered HTML.

**Three OAuth providers are one env var each**, and nothing else blocks them.
Register the redirect URI byte-for-byte in the provider console:

| provider | env | redirect URI |
|---|---|---|
| Google | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | `…/oauth/google/callback` |
| Meta Ads | `META_APP_ID` / `META_APP_SECRET` | `…/oauth/meta_ads/callback` |
| Canva | `CANVA_CLIENT_ID` / `CANVA_CLIENT_SECRET` | `…/oauth/canva/callback` |
| Constant Contact | `CONSTANT_CONTACT_CLIENT_ID` / `_SECRET` | `…/oauth/constant_contact/callback` |

`CREDENTIAL_KEY` and `PUBLIC_BASE_URL` are set and live. `CREDENTIAL_KEY` must
never be rotated casually — every credential stored under the old one orphans.

**ESP is pick-one.** Omnisend, Klaviyo and Constant Contact all grant `esp`;
`covered_by` is derived by grouping `PROVIDERS` on capability, so a fourth ESP
joins the group without an edit. The client page drops the alternatives; the
console keeps them so an owner can switch a client.

**Canva falls back to the agency's connection**, and is the only provider
allowed to — it holds our own finished work, and `canva.folder()` already files
each account separately. A client's own connection still wins. A test asserts
Coverings can never reach Shopify through the agency's token.

**WordPress can be connected more than once per client** — `Credential` is keyed
`(tenant, provider, site)`. Resolving or revoking without naming the site
REFUSES and lists them: picking the first would publish a landing page to
whichever install was connected first, and the client would find out by reading
their own website.

**Still unconnectable:** Squarespace, which is Ironside's main site. No
provider, no adapter, and the connect page offers it WordPress instead. Its
`blog` system is blocked on something the UI cannot express.

## Two bugs that would have failed on the first real call

Both found while building the connect work, both the shape already in §1.

* **`oauth.exchange` was an if/elif on provider name ending in a bare `else`**
  that put `client_id` and `client_secret` in a URL QUERY STRING. Whatever was
  added next inherited it — a new provider's client secret into access logs and
  proxy caches. `token_style` is declared per flow now.
* **Canva would have 401'd on every real call.** `exchange` stores the refresh
  token for that provider, deliberately, and `canva._token` handed it to the API
  as a Bearer. Green chip, dead connection. New `oauth.access_token()` mints a
  real one and carries back a rotated refresh token — dropping that would make a
  connection work once and then die, which looks exactly like a revocation.

## Onboarding a client from zero, through the UI

No seed script is needed and this was checked by doing it. `/admin/tenant_add`
creates the account; the brand row appears on first write; `add_situation`
authors a vocabulary, and a crawl proposes its own tags on top;
`/admin/asset_add` and the picture queue fill the creative library;
the Accounts tab connects providers; the Systems installer shows each system's
prerequisites as met/unmet before you commit to it.

**One caveat worth knowing.** A tenant with no authored vocabulary falls back to
a shared default set, so a new account appears to have 29 situations that are
not its own. That fallback is deliberate and load-bearing for the existing
accounts, but borrowed vocabulary currently looks identical to authored
vocabulary — the §1 pattern again, unfixed.

## The creative chain, and which route can be trusted

Three treatments. They differ in what can be wrong, not in how they look.

| route | product fidelity | scene |
|---|---|---|
| `compose.photo_with_headline` | the client's own photograph, untouched | n/a |
| `compose.product_on_colour` / `product_on_scene` | drawn by us, cannot be wrong | flat or a supplied plate |
| `imagegen.scene_with_real_product` | photograph composited on, cannot be wrong | generated |
| `imagegen.place_product` | **the model may redraw it** | generated, best integrated |

`photo_with_headline` is the only one that fits every client — Baci sells
objects, Coverings sells surfaces (a tile IS the surface), Ironside sells places
(a room cannot be cut out). `KbAsset.subject` records which of `object` /
`surface` / `scene` / `logo` an asset is, because it does not generalise.

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

## One creative pipeline, three shapes of business

The cutout pipeline only ever fitted one kind of client. Baci sells **objects**
with a silhouette; Coverings sells **surfaces**, where the tile IS the surface
and standing it on a table is meaningless; Ironside sells **places**, and a room
cannot be cut out at all. A pipeline that assumes a product cutout is a Baci
pipeline wearing a platform's clothes.

`KbAsset.subject` records which — `object` / `surface` / `scene` — because it
does not generalise and guessing it per render is how a venue photograph gets
treated like a pitcher. `kb.detect_subject` offers a default from the one
reliable signal, transparency: a cutout is a discrete thing somebody already
isolated. With no alpha it returns `scene`, the treatment that is safe for a
tiled wall and a restaurant alike, and says the caller should override it.

`compose.photo_with_headline` is the treatment that fits all three, because it
assumes nothing about what is in the picture: the client's own photograph, plus
something to say. No cutout, no generation, nothing that can be the wrong
product, tile or room.

Two things make it survive that range without a human tuning each client.
`_quiet_band` measures the variance of each horizontal band and puts the type in
the calmest one — where the quiet region sits is a fact about each photograph,
not a house style, and a packed interior is quiet at the ceiling while a product
sweep is quiet everywhere but the middle. Text colour is picked
from that band's brightness, so one call produces white type on a dark
restaurant and dark type on a white sweep.

**No panel behind the type.** An earlier version laid a gradient scrim there so
the text would be readable on anything. It worked and it looked like a
template — a band across every image regardless of what was underneath. Gomeh
called it, and he was right. Contrast does the same job, and where it will not
quite carry — a mid-toned band with real clutter in it — a soft offset shadow at
low opacity lifts the type without putting a shape on the picture. It fires on
measurement (`stddev > 34`, or a mean in the muddy middle), not on every render:
a clean sweep and a flat dark wall get none.

Verified across a dark venue, a mosaic, a bright product sweep — all readable
with no shadow at all — and a deliberately hopeless mid-toned clutter field,
where the shadow appears and carries it.

## Generated scenes, with the product protected rather than checked

`app/imagegen.py`, on OpenAI — the same `OPENAI_API_KEY` `embed.py` already
uses, so no new credential.

Two jobs. `plate()` generates scenery with **no product in it**; the empty-
surface rule is appended to every prompt, because a plate with a jug already
standing in it is the failure the whole approach exists to avoid. Inspiration
is carried as **words**, never an uploaded reference: a scene generated from
someone else's photograph is a derivative of it and would arrive with nothing
saying so.

`place_product()` is Gomeh's own technique — hand the model the cutout,
describe the setting, let it build around the object — and it uses a **mask**,
which is a decision that came from measuring the alternative. The first version
generated freely then scored the result against the source to catch drift. That
score was far too weak to gate on: the real product scored **0.433** and a
different-coloured, handleless impostor scored **0.356** — a 0.077 gap ordinary
lighting variation would swamp. Tuning the threshold until the test passed
would have shipped a safety gate that does not gate.

So the product is not verified afterwards, it is protected during. The mask is
the product's own alpha silhouette, grown a few pixels so no rim of old
background survives to read as cut out; the API repaints only outside it and
the product's pixels return exactly as sent. Fidelity by construction, the same
reasoning as `catalog_seo_rewrite` carrying its `claim_id` by construction.

`similarity()` survives as a **reported** diagnostic and never a gate, and says
so in its own output: a coarse screen that catches a wholly different object
and misses a faithfully redrawn one.

Generation happens at the model's native sizes; `compose` cuts the ad shapes,
which is already its job for a photographic plate.

**Unproven:** no call against the live image API.

## Creative that actually contains the product

Canva's generator treats a supplied asset as **inspiration**. Tested against
Baci's own catalogue with `asset_id` set, it produced four ads with four
invented pitchers — Gomeh confirmed none showed the product. No amount of
prompt tightening makes that deterministic, so a compliance-gated skill cannot
stand on it.

`app/compose.py` places the product by drawing it, so there is nothing to
verify afterwards. Two treatments, both wanted:

* `product_on_colour` — cutout on a brand ground. Ships today, depends on
  nothing generated.
* `product_on_scene` — cutout composited onto a styled plate, **grounded with a
  contact shadow**. That shadow is most of the difference between composited
  and pasted, and the first version of it was invisible: a pitcher's footprint
  is its narrow foot, so a shadow at the object's own width vanishes once
  blurred — a real one spreads wider than what casts it — and the blur radius
  was a constant rather than a fraction of the shadow's height.

Baci's photography is already right for this: verified 1200×1200 PNGs with a
real alpha channel and fully transparent corners.

**Rights gate the imagery too.** `_guard` refuses to composite an asset that is
not `owned`, and refuses one belonging to another account. A competitor's
photograph composited into an ad is precisely what that axis exists to prevent,
and it would be invisible in the output.

**The font used is reported.** Rendering a brand's headline in whatever font
happened to be installed is a brand violation that looks like a success — same
reasoning as `ad_copy` reporting `basis`.

Three ad shapes every time (1:1, 4:5, 9:16), so nothing is re-cropped by hand
and the story version does not lose its headline off the top. `Pillow` added to
requirements — it was installed locally and **not on the service**.

**Still needed for scenes:** a plate. A generated background must contain NO
product — asking a generator for a table with a pitcher on it and then pasting
a second pitcher beside it is the failure this approach exists to avoid.

## The handoff: correct image in, editable design out

`canva.editable_from_image` is the join between the two halves. Everything
upstream exists to make the picture **correct** — the real product, the client's
own photograph, a claim that passed the validator. None of that survives being
retyped by hand, and none of it makes a layout a designer would sign off. So the
rendered base goes into Canva as an asset inside a design, filed in that
account's folder and recorded in the library, and the typography and composition
are done there by a person who can see it.

**Render the base without text for this.** Baked type is a picture of words: it
cannot be corrected, re-weighted, translated or re-flowed for a story crop — and
those are precisely the things the handoff exists to allow.
`compose.photo_with_headline` with an empty headline gives exactly that.

`upload_bytes` uploads **binary**, not a URL. The URL variant is no use here: a
rendered ad exists as bytes in memory, and putting it somewhere public purely so
Canva can fetch it back would mean publishing an unapproved draft in order to
get it reviewed. The upload is a job rather than an answer, so it is polled — a
bounded number of times, because a caller holding "in_progress" has nothing to
do with it and an unbounded poll turns a Canva outage into a hung request.

## Canva, and where each account's work lives

Canva is a real provider now — OAuth **with PKCE**, which Canva Connect requires
even of a confidential client. `oauth.py` gained generic PKCE rather than a
Canva branch: `_pkce_pair()`, a `pkce` flag on the flow, and the verifier
carried **encrypted** inside the signed state. Signing alone would not do — a
readable state hands the verifier to anyone who can see the URL, which is the
interception PKCE exists to prevent. Encrypting it keeps the codebase's rule
that sign-in state is never a database row without making the secret public to
buy it.

**Every call is scoped to one account, structurally.** Nothing in `app/canva.py`
takes a folder id from a caller; it is looked up from the tenant row and created
on first use. A design cannot be filed into another client's folder because
there is no argument for saying which folder to use — the same reasoning as
`tool_scope` stripping the account parameter out of a tool's schema. Two levels:
one root (`Client work — gomehagent`) so a team that also uses Canva by hand
keeps its own work separate, and one folder per account inside it. The id is
remembered on `Tenant.design`, not searched for by name — a name search
eventually matches a renamed folder or creates a second one, and two folders
called "Baci Milano USA" is exactly the state where work goes into the wrong one.

**Both sides are written together.** `create_design` files the design in Canva
AND records a `KbAsset` carrying `canva_design_id`, the entity it is about, and
`rights="owned"`. A design nothing names is invisible to every skill — it cannot
be selected, credited when used, or carry a result. `reconcile()` reports drift
in both directions and says which one is dangerous: a row naming a design that
no longer opens is worse than an unrecorded design, because a skill will select
it and produce output pointing at nothing.

`test_canva.py` (24 checks) holds all of it, including that a competitor
reference uploaded through the same call stays unpublishable.

**Unproven:** no call has been made against a real Canva account, and the OAuth
leg has never run — same standing as Omnisend.

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

**Not built:** the generator itself, the Canva/Ryze calls, and the join from an
output to a channel's ad id (so `record_asset_outcome` is fed by hand today).
The library DOES have a UI now — `/admin/asset_add` plus the picture-approval
queue on the Content tab — added after Gomeh approved claims and found nowhere
to approve the 56 images the Ironside crawl had filed.

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

**Ran and confirmed.** All **54 suites pass**, none touching the network,
including `test_tenant_isolation.py` **unmodified**. New: `test_diagnostics.py`
(42 checks). `test_console_frame.py` was rewritten rather than extended — see
§2.41; its old form asserted scoping against empty tables. `test_assurance.py`,
`test_constant_contact.py` (30 checks against a stubbed transport, asserting the
REQUEST), `test_claim_expiry.py` and `test_perishable.py` — the last of which
drives `responder.answer` for real and then asks the DATABASE what landed,
because a column accepting a value proves nothing.

**Two sabotage runs, because a suite that has never failed has never been
tested.** Removing `diagnostics._scope`'s filter fails fourteen assertions by
name; putting the old `systems.all_systems()` call back fails
`test_console_frame` with `systems body is single-account — Baci Milano USA,
BACIMARK`. Both were restored immediately.

Deploy verified live at `647502d` BEFORE this session's console work: `/health`
reported 106 routes and `/health/connections` still resolved both Shopify stores
and three Google accounts. **The console-scoping and diagnostics work is in the
worktree, NOT committed and NOT pushed** — it has never run on the service, and
`/health` will not report it. Committing and deploying it is the owner's call.

**Assertions deliberately CHANGED, not worked around:** two in `test_skill.py`
pinned the rule that an incomplete contract stops a run. Three in
`test_harvest.py` (earlier) pinned the old tag gate.

**Built but unproven — read before trusting anything above.**

- **No skill has run against real Baci data.** `_fetch_products_live` has never
  made a Shopify call. The REST shapes are the ones `shopify_seo` already uses,
  but "the code is right" is not "it ran".
- **No real model call has been made.** `inbound_reply` and `ad_copy` were
  exercised against a stub, so the prompts and grounding blocks are unproven.
- **No OAuth leg has ever run** against a real provider. The working Google is
  the env-group path.
- Omnisend, Constant Contact, Canva and the OpenAI image API: never called.
- The 110-violation figure is from the prior audit, not from a sweep.
- The credential constraint regrade is verified on SQLite and by the service
  coming up healthy; the Postgres `DROP CONSTRAINT` path itself was not
  observed. If a client's second WordPress site ever fails with an
  IntegrityError, that is where to look.

## The build plan, revised

The old plan assumed content had to be filled before anything could produce, and
that the substrate was the risky part. Both premises changed this session. The
substrate is governed, instrumented and connectable; the daily runtime is not
governed at all. **Order by where an unguarded write reaches a customer.**

**1 — ~~Guard the SEO write path.~~ DONE.** `app/seo_guard.py` stands in front
of all five existing writers and the four new article ones. Ban list only,
`require_citation=False` — an SEO title has no claim to cite, and a guard that
fires on everything is a guard somebody removes. It names the FIELD rather than
just the rule, refuses when no tenant matches the domain (a site with no ban
list is the same hole one layer down), and records every check — pass or catch —
to `assurance` under source `seo`.

**2 — Close the second mail path and strengthen the first.** Give
`queue_email_draft` the same check, and replace `triage.py`'s substring test
with `validator._banned`. One is a hole; the other is a matcher that misses the
spellings that matter. Both are small, and both are on the path that answers
customers.

**1 — Close the learning loop.** Everything now MEASURES and nothing LEARNS.
`systems.feedback_block()` renders a system's standing guidance for injection at
drafting time and has no caller — the Guidance field on the Systems card is
saved, displayed, and read by nothing. And the new edit deltas are recorded and
consumed by nothing. Two small wirings, and together they are the difference
between a system that reports on itself and one that improves: `ctx` already
carries the tenant and system key, so folding `feedback_block` into the bundle
is a few lines plus a test that a note actually reaches a draft.

**~~3 — Write `edit_diff`.~~ DONE for capture, see above.** Was: Until something does, "is this better than the AI
alone" has no answer beyond catches. Capture sent-vs-draft in Gmail rather than
adding a field to the approval — it measures what actually happens. This is now
the LAST unwritten column of the three that were declared and dead; `expires_at`
and `Output.lookups` both got writers this session.

**3b — Watch the first claim-expiry sweep.** It runs Mondays and reports
without moving anything on its first pass per account, so the first Monday after
deploy is the one to read. Every claim older than a year comes due at once on a
knowledge base nobody has dated.

**4 — Run `catalog_compliance` against real Baci.** Still the first real
exercise of the Shopify read, and now it can be watched on the Assurance tab
while it runs. Expect to fix something in `_fetch_products_live`, which raises
`KeyError` instead of refusing by name.

**5 — ~~Expose the skills to the agent.~~ DONE.** `run_skill` is a kernel tool.
`tool_scope` strips `tenant` from the schema and injects it at dispatch, and
`skill.catalogue(tenant)` IS the description, regenerated per account — so the
model picks a name and never picks a client or a brief. Blocked skills are
listed with what they are waiting on rather than hidden, because a model that
cannot see `catalog_compliance` concludes the system cannot check a catalogue.
The refusal path tells the agent explicitly not to draft the thing by hand
instead, and a thin run reports what it worked without. `tenant` joined
`ACCOUNT_PARAMS`, so any future tool naming one must register in `SCOPED` or
`test_tenant_isolation` fails by name.

**5b — The rest of the built-but-unreachable list.** `kb.assign_to_group` is
DONE — a bulk POST plus a form on the Knowledge tab. It mattered more than its
size suggests: collection import is opt-in on purpose, because a group claim is
asserted about every member and inherited silently, and the manual alternative
was one GET per entity — forty URLs by hand for a forty-item range. The safe
default had no usable alternative.

`approvals.pending_count` is DONE too — the console shows "N waiting" in the tab
bar on every page. The one number that says whether this system is waiting on a
person was visible nowhere, and a queue whose depth nobody can see is one that
stops being worked; this codebase has lived that at ~200 drafts.

Two were DELETED rather than wired, because leaving them was worse than the work
they represented. `credentials.granted_capabilities` sees only client
connections and not the env group, so anyone reaching for it reintroduces §2.29
— env-connected accounts reading as unwired. `kb.retire_claim` was a one-line
alias for `review_claim(approve=False)`, and two names for one decision is the
`add_claim`/`add_audience` trap in miniature.

Five left, all unfinished features rather than dead weight (see the audit
section for the list). Deleting the dead ones is as valuable as wiring the live
ones — an unreachable function reads as a feature to the next person who greps
for one.

**6 — Squarespace, or decide Ironside's blog is not a system.** It is installed
and permanently blocked on a provider that does not exist.

**Deliberately NOT next:** more knowledge authoring. It is no longer a
prerequisite for producing, the queue now fills from real runs, and the
unguarded write paths above are where the actual risk is.

## Next thread starts here

**Read, and only these:** this file, then `DEFECTS.md` §1 and §3, then
`app/skill.py`. Do not search the repo broadly.

**Run the suites first, before changing anything.** 54 of them, all offline:

    for f in scripts/test_*.py; do
      [ "$(basename $f)" = "test_brief.py" ] && continue
      r=$(python3 "$f" 2>&1 | tail -3)
      echo "$r" | grep -qE "all checks passed|all green" || echo "FAIL $(basename $f)"
    done

Check the OUTPUT, not the exit code, and skip `test_brief.py` — it is an
argparse CLI that exits 0 whatever happens, and counting it as a passing test is
a mistake this file made for weeks.

**Start at plan item 1** — close the learning loop. It is the smallest change
with the largest gap behind it: everything in this system now measures itself
and nothing learns from what it measured. The Diagnostics tab makes that gap
visible rather than closing it: it can now show you that a system blocked on the
same missing field forty times, and nothing still feeds that back into drafting.

**Then watch the Diagnostics tab against a real breakdown.** It has only ever
been read against seeded rows. The first real one will find something — every
assumption in this codebase tested against reality so far has been wrong in some
detail. Two known blind spots to check first: `ToolCall.ms` is only written at
the kernel dispatch and the three adapter seams, so anything reaching a platform
another way records no duration and reads as untimed rather than as fast; and
`Usage.tenant` is blank on every row written before attribution was wired, so an
account's spend in a long window is understated and the note says so.

### Three habits this session earned the hard way

**A test that cannot fail for its stated reason is worse than no test.** Three
were found this session, each passing for the wrong reason and only admitting it
under an unrelated change: the portal cookie is `secure=True`, so `TestClient`
over http silently sends nothing and every assertion read the signed-out page;
`test_oauth` checked "a connected provider says so" against a page that stacked
every account, so a credential on ANY of them satisfied it; and a hand-built
fixture used literal `\n` characters, so every diff scored 0.0 similarity and
looked correct. When an assertion passes first time, ask what would make it
fail.

**A survey that under-reads its corpus produces confident nonsense.** The wiring
audit globbed `app/*.py`, never recursed into `app/roles/`, and reported a
function as unreachable that its own docstring said was injected every turn.
67 files of 123. Use `**/*.py`, say how many files were read, diff against the
last one.

**Declared and never written is this codebase's signature defect.** Met five
times: `Approval.system_id`, `SystemRun.edit_diff`, `KbClaim.expires_at`,
`Usage.tenant`, `Output.lookups`. Every one made a question look answered while
having no answer in it. When adding a column, write the reader and the writer in
the same change, and assert the value LANDS rather than that the parameter was
accepted.

### Standing preamble

Worktree `/Users/gomehsaias/Documents/gomehagent-build`, branch
`feat/context-architecture`, tracking `origin/main`. The other clone
(`~/Documents/gomehagent`) is on `feat/warehouse-picklist`, a pre-kernel base —
**never push from there.** Render auto-deploys `main`; git needs the sandbox
off; always fetch and verify a fast-forward before pushing. Deploys land in
about two minutes — check `/health` for the commit rather than theorising.

### What to watch rather than build

* **The first Monday after this deploy**, the claim-expiry sweep reports without
  moving anything, once per account. A knowledge base nobody has dated finds
  every claim older than a year at that moment.
* **The first real approval** once drafts resume — `send_draft` has never made a
  real Gmail call.
* **The Anthropic spend limit.** It is what stopped drafts on 18 Aug, and
  `triage` is 93% of spend at $0.035 per email against `classify` at $0.0009.
  The cheap classifier routes but does not filter: every email gets the
  expensive agentic pass, including the ~50% that are promo and notifications
  and never draft. Gating triage on the bucket is roughly half of $55/month.
