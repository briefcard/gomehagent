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

**44 suites, 44 pass.** Check the OUTPUT, not the exit code, and skip
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

**The inversion is the finding.** `grep -c "banned|validator|compliance"` across
`shopify_seo.py`, `wordpress_seo.py` and `seo_tools.py` returns **0, 0, 0** —
and those three are the only modules that write to live customer-facing
properties. The subsystem that merely REPORTS has every guarantee; the one that
PUBLISHES has none. Baci's 110 violations are SEO metadata, which is exactly
what `shopify_seo.update_seo` writes.

**Two mail paths, and only one is guarded.** `worker.py:108 → triage.triage_email`
checks banned claims and escalates. `command_agent → queue_email_draft` — the
model composing a draft in the tool loop — checks nothing. And the guarded one
uses a plain substring test while `validator._banned` next door matches on word
boundaries with flexible separators: today "hand-decorated" is caught, "hand
decorated" walks through, and "artisan" false-fires inside "artisanal".

**Smaller findings.** 10 functions nothing can reach (`approvals.pending_count`,
`canva.export_result`, `credentials.granted_capabilities`, `kb.retire_claim`,
`kb.assign_to_group`, `omnisend.upload_image`, `ops_jobs.file_whatsapp_document`,
`propose.from_gap`, `seo_tools.seo_context_block`,
`baci_backoffice.list_company_documents`) — `kb.assign_to_group` is the manual
collection-grouping path `/admin/entity_group` was meant to expose.
`_fetch_products_live` raises `KeyError` instead of refusing by name. Two orphan
columns (`KbUnknown.first_seen`, `KbConflict.first_seen`). Otherwise the column
layer is clean, all 37 kernel tools have handlers, and `_GOOGLE_TOOLS` has not
drifted.

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

**Ran and confirmed.** All **44 suites pass**, none touching the network,
including `test_tenant_isolation.py` **unmodified**. New this session:
`test_assurance.py`, `test_constant_contact.py` (30 checks against a stubbed
transport, asserting the REQUEST), `test_claim_expiry.py` and
`test_perishable.py` — the last of which drives `responder.answer` for real and
then asks the DATABASE what landed, because a column accepting a value proves
nothing. Deploy verified live: `/health` reports
`647502d`, 106 routes, and `/health/connections` still resolves both Shopify
stores and three Google accounts — which is the code path the credential
constraint migration touches.

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

**1 — Guard the SEO write path.** The highest-value fix in the codebase and the
one with a live blast radius. `shopify_seo.update_seo`, `shopify_seo.create_page`,
`wordpress_seo.update_seo` and `wordpress_seo.create_page` publish to customer-
facing properties with zero compliance checks. Route them through
`validator.check` (with `require_citation=False` — an SEO title has no claim to
cite) and record through `assurance.record(source="seo")`. Baci's 110 known
violations are exactly the field this writes.

**2 — Close the second mail path and strengthen the first.** Give
`queue_email_draft` the same check, and replace `triage.py`'s substring test
with `validator._banned`. One is a hole; the other is a matcher that misses the
spellings that matter. Both are small, and both are on the path that answers
customers.

**3 — Write `edit_diff`.** Until something does, "is this better than the AI
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

**5 — Expose the skills to the agent.** `/admin/skill_catalogue` and
`/admin/skill_run` exist; no agent TOOL does, so the four skills are reachable
only from Python and two admin routes. One `run_skill` tool whose description is
generated from `skill.catalogue(tenant)`, so the agent picks a skill and never
picks context. **This is the next thread's first job** — it is the largest
gap between "built" and "usable" left in the repo.

**5b — The rest of the built-but-unreachable list.** `kb.assign_to_group` is the
manual collection-grouping path `/admin/entity_group` was meant to expose;
`kb.retire_claim`, `credentials.granted_capabilities`, `canva.export_result`,
`omnisend.upload_image`, `approvals.pending_count`, `propose.from_gap`,
`seo_tools.seo_context_block`, `ops_jobs.file_whatsapp_document` and
`baci_backoffice.list_company_documents` have no caller at all. Each is either a
missing route or dead weight, and deciding which is a morning's work.

**6 — Squarespace, or decide Ironside's blog is not a system.** It is installed
and permanently blocked on a provider that does not exist.

**Deliberately NOT next:** more knowledge authoring. It is no longer a
prerequisite for producing, the queue now fills from real runs, and the
unguarded write paths above are where the actual risk is.

## Next thread starts here

**Read, and only these:** this file, then `DEFECTS.md` §1 and §3, then
`app/skill.py` and `app/assurance.py`. Do not search the repo broadly.

Start at plan item 1. Verify by running the suites in two batches; check the
OUTPUT, not the exit code; skip `test_brief.py`;
`test_tenant_isolation.py` must pass **unmodified**.

**Standing preamble.** Worktree `/Users/gomehsaias/Documents/gomehagent-build`,
branch `feat/context-architecture`, tracking `origin/main`. The other clone
(`~/Documents/gomehagent`) is on `feat/warehouse-picklist`, a pre-kernel base —
**never push from there.** Render auto-deploys `main`; git needs the sandbox
off; always fetch and verify a fast-forward before pushing. Deploys land in
about two minutes — check `/health` for the commit rather than theorising.
