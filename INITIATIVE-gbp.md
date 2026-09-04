# INITIATIVE — Google Business Profile as a system

**Local SEO for venues and local clients**, run the way every other system here
is run: gated by the ban list, held for review, and pushed only when a person
approves it. Owner, 2026-08-29: *"I want GBP to be native so that we can
optimize SEO and listings for local venues / clients."* That is the frame — the
LISTING is the ranking surface and the primary work; posts are one producer on
top of it, not the point. Written 2026-08-28 after the owner asked
whether Claude has a GMB skill to automate this. It does not — nothing in the
skill set, no connector on any MCP server, no scaffolding in this repo — so
this is the plan to build it here.

**NOT SCHEDULED YET, DELIBERATELY.** Step 4 of INITIATIVE-ui-overhaul has one
tab left. This file exists so the design is decided while it is fresh and so
the ONE part with a wall-clock dependency — Google's access approval — can be
started immediately, independently of the build.

---

## §0 Where this stands

The platform half is built (2026-09-04). The critical path is still not
engineering:

| | state |
|---|---|
| Google API access | **APPLY — it is a queue.** `gbp.ACCESS_FORM`, quoting the Cloud project number, from an owner/manager email on the profile. Quota is 0 until approved. |
| The seven APIs to enable | named once, in `gbp.APIS_TO_ENABLE`; shown on the account card and in the probe |
| `app/gbp.py` provider adapter | **read side built** — accounts, locations, listing, live state, reviews, posts, performance; named refusals; `probe` |
| `gbp` capability + connection | **wired** — `business.manage` in the Google flow; `credentials.CAPABILITY_SCOPES` grants `gbp` only when the consent carried it; declared per account as `Tenant.gbp` |
| `gbp_listing` system (the SEO half — build first) | declared; **skill not written** |
| `gbp_post` system | **built 2026-09-04**: `gbp_post` skill (derived from an approved article/email/ad, or native from an objection or a claim), the planner (`planner.gbp_post_rollout`, one a week, alternating, keyword from the map), `approvals.publish_gbp_post` (the one write, via `gbp.create_post`), the workroom preview, the retry |
| `/admin/gbp_probe`, `/health/connections["gbp"]` | built |

**The owner's order of operations** is the docstring of `app/gbp.py`: apply,
enable the seven, connect Google (again, once, for the scope), declare the
profile from what the probe lists.

---

## §1 Why this is tenant-generic, not a two-client feature

Owner's correction, 2026-08-28: *"any local-focused business will need it."*
That is the whole framing. The first instinct — "Ironside and Coverings are
local, Baci and Eien are not, so it is a two-tenant feature" — is wrong twice:

1. **The agency sells to local businesses.** A working GBP system is a
   capability that opens a client segment, not a convenience for two accounts
   already on the books. It is a reason to win the next five clients.
2. **Hardcoding tenants is the mistake this codebase keeps not making.**
   `campaign_email` is ESP-agnostic; `harvest` reads whatever sources a tenant
   declares. GBP is gated on a CAPABILITY (`gbp`, meaning a connected and
   verified listing), never on a tenant key. An account without one sees the
   system parked with its reason, exactly as Store sync parks without a store.

---

## §2 Facts about the API (verified 2026-08-28, from Google's own docs)

Third-party writing on this is contradictory and much of it is wrong — several
posts claim posting is deprecated. It is not. What follows is from Google's
deprecation schedule and prerequisites pages, not from a blog.

- **Creating posts still works.** `accounts.locations.localPosts` —
  create / delete / get / list / patch — is active in **v4.9**, and **no
  sunset date has been announced** for it.
- **Post-level analytics are gone.** `localPosts.reportInsights` was
  discontinued **20 February 2023 with no replacement.** This is a design
  constraint, not a footnote — see §3.
- The old monolithic My Business API was split; the live surfaces are
  **Business Information v1** (location data, hours, attributes),
  **Business Profile Performance v1** (location metrics),
  **Account Management v1.1**, **Reviews**, Verifications, Place Actions,
  Notifications.
- **Access is not self-serve.** A Cloud project must be approved: application
  via the GBP API contact form quoting the project number, submitted from an
  owner/manager email on the profile. Eligibility requires a **verified GBP
  active 60+ days with a live website**. Unapproved quota is **0 QPM**;
  approved default is **300 QPM**. Approval duration is not published.

Sources: developers.google.com/my-business/content/sunset-dates ·
/content/prereqs · /reference/rest/v4/accounts.locations.localPosts

---

## §3 The contract problem, decided now rather than discovered later

Every system here must answer `systems.CONTRACT` — what makes us switch this
off, how does it break, who notices, how would we know it worked. With
per-post analytics dead, **there is no per-post metric and there never will
be.** Deciding this in advance, in the open:

- **The measurement is LOCATION-LEVEL and coarse**: Business Profile
  Performance v1 gives calls, direction requests, website clicks, searches —
  per location, per period. Not per post.
- **Attribution to a single post is impossible.** The honest contract is
  week-over-week movement at the location while a posting cadence is running,
  read as a trend and never as "this post produced these calls".
- **So the kill criterion is not a conversion number.** It is: the cadence
  lapsed, or the ban-list gate started firing, or location metrics fell while
  cadence held. Written into the contract fields at declaration time, so
  `can_promote` refuses `auto` until they are answered — which is exactly what
  that gate is for.

A system whose success metric is vague is the case the eight contract
questions exist for. This one is vague by Google's decision, so it is named.

---

## §4 Where it sits in the substrate

Nothing here is a new architecture. Every piece has a precedent to copy, and
the precedent is named so the build does not invent a parallel one.

| piece | new thing | copy the shape of |
|---|---|---|
| provider adapter | `app/gbp.py` | **`app/esp.py`** — duck-typed adapter + profile row, never a branch in a generator |
| the push | `push_post_to_gbp()` | **`skill_pack.push_campaign_to_esp`** — the ONLY external write, called by the APPROVAL executor, idempotent by destination, refuses withdrawn verdicts |
| the skill | `register(Skill(key="gbp_post", …))` | **`campaign_email`** for lifecycle, **`ad_copy`** for short-copy shape |
| the system | `SPECS["gbp_post"]` | `campaign_email`, with `requires=("gbp",)` |
| capability | `gbp` in `declared_capabilities` | `commerce`, `email_platform` |
| the artifact | `ArtifactBody(format="gbp_post")` | the campaign path — held in our store, `push` = machine recipe |
| the workroom | a `gbp_post` branch on `/admin/work/{id}` | the email branch's sandboxed preview |
| the queue | it lands in Review's ship queue | every other held artifact |
| cadence | GBP rows in the Plan schedule | `campaign_rollout` |

### The skill file, specifically

**`app/skill_pack.py`** is the file to append to — 3,599 lines, six registered
skills, one `register(Skill(...))` block each. The new block declares:

```python
register(Skill(
    key="gbp_post",
    name="Google Business Profile post",
    does="Turn one already-approved article, campaign or moment into a short "
         "local post with a call to action. Asserts nothing the source did "
         "not. Held for review; approving is what publishes it.",
    system_key="gbp_post",
    tier=1,                       # a shortener with a CTA, not an author
    needs=("rules.banned_claims", "brand.voice", "brand.positioning"),
    # CONSTITUTIVE, like catalog_compliance's. A 1,500-character post has
    # nowhere to hedge: generating one against an empty ban list is how a
    # banned claim reaches a Google-hosted surface the brand does not control.
    constitutive=("banned_claims",),
    params=("source_output_id", "cta", "location"),
    writes=True,
    produces="draft",
    run=_run_gbp_post))
```

`campaign_email` is the closest existing model and should be read before this
is written — it is the skill that already holds its output, writes its own
`ArtifactBody`, and lets the approval executor do the external write.

---

## §4b THE LISTING IS THE RANKING SURFACE (owner, 2026-08-29)

*"I want GBP to be native so that we can optimize SEO and listings for local
venues / clients."* This section did not exist in the first draft, which
treated GBP as a posting pipe. That was the wrong centre of gravity: **posts
are a freshness signal; the LISTING is what ranks.** In local search the
fields that move the map pack are the primary category, the secondary
categories, the services/products list, the business description, the
attributes, the hours (including special hours), the photos, and NAP
consistency — none of which is a post.

So the system has **two producers of work, and the listing one comes first**:

**(a) LISTING OPTIMISATION — the SEO half.** A recurring audit that reads the
live listing through Business Information v1 and proposes concrete field
changes, each held for review like any other artifact:
- **Primary category** — the single highest-leverage field on a listing, and
  the one clients most often have wrong. Proposed against what the business
  actually is, evidenced from the website and the knowledge base.
- **Secondary categories, services, products** — the long tail. A venue that
  lists "event venue" and nothing else is invisible for "wedding venue",
  "corporate event space", "photo studio rental".
- **The business description** — 750 characters, written in the brand voice,
  through the same ban list and validator as every other draft.
- **Attributes and hours**, including special hours, because a wrong holiday
  hour is a lost booking and a bad review in the same afternoon.
- **Photos** — coverage by type (exterior, interior, team, product), drawn
  from the approved asset library that already exists (`kb.assets`, rights-
  gated), never from anywhere else.
- **Gaps stated as gaps** — a missing field is reported as missing, with the
  control to fill it, not silently skipped.

**(b) POSTS — the freshness half.** §5 below.

**WHY THIS ORDERING MATTERS FOR THE BUILD:** step 1 already mirrors the
listing read-only, so listing optimisation is *the natural first thing that
produces value* and needs no write access to Google at all until the owner
approves a change. A client can be audited and given a prioritised list of
listing fixes before the posting path exists. That is a sellable deliverable
on its own, and it is the half that actually moves local rank.

**A SECOND SKILL, THEREFORE.** `app/skill_pack.py` gains two blocks, not one:
`gbp_listing_audit` (`produces="report"`, `writes=False`, tier 1 — modelled on
**`catalog_compliance`**, which is exactly this shape: read a live surface,
check it against what this brand may say, report violations grouped by cause)
and `gbp_post` (§4). The audit skill is the one to build first.

---

## §4c Two systems, not one (owner, 2026-09-03)

"So far I only see a system for posting on GMB, what about making sure that
all the listings are optimized?" — the post is one act; the listing is the
surface it lands on, and §4b already says the listing is the ranking surface.
So GBP is two systems in `systems.CATALOG`, both gated on the `gbp` capability:

| system | unit | shape |
|---|---|---|
| `gbp_post` | one post to one profile | campaign_email: draft → approval → publish |
| `gbp_listing` | one sweep of one profile | catalog_compliance: sweep → completeness report → fixes via approval |

`gbp_listing`'s rubric, when built: primary + secondary categories set;
description present, within limits, and clean against the ban list; hours
including special hours; attributes filled where the category allows; services
listed from the KB's entities; photo count and recency; Q&A seeded from the
KB's objections; reviews answered inside the window, in the brand voice. Its
measure is the completeness score rising sweep over sweep and the answered
share of reviews — computed, so the effectiveness map can hold it.

Both are declared empty in the register's known list until Google API access
exists (§0). Declaring them now is what lets readiness, the register and the
effectiveness map show the gap by name instead of the initiative doc being the
only place GBP exists.

## §5 What a post can be — derived AND native

**CORRECTED 2026-08-29 after the owner pushed back.** The first version of this
section said a GBP post is *"DERIVED, never authored from nothing"* — built
entirely around the propagation half of the question and too narrow to be the
system a local business actually needs. Google's post types include **offers,
events and standalone updates**, and a local business's best-performing posts
are usually exactly those: *"open Labor Day weekend"*, *"20% off installs this
month"*. Those will never come from a blog article, and a system that cannot
write them is not a local-presence system.

So there are **two producers**, both running the same gates:

**(a) DERIVED — the propagation the owner asked for.**

- Input is an artifact ALREADY approved — a published blog article, a sent
  campaign, a moment. Nothing reaches Google that a person has not already
  signed off in a longer form.
- **The deriver shortens and adds a CTA. It does not assert.** Every factual
  sentence still has to trace to a claim, and `validator.check` +
  `coherence.review` + `artifact_check.check` run at emit exactly as they do
  for every other artifact. A post that would introduce a new assertion is
  refused, not softened.
- **Lineage is rendered, not just stored.** The post carries `run_id`,
  `system_key` and a `derived_from` pointer to its source artifact, and the
  Review row says *"derived from <that article>"* with a link both ways. This
  is **move 2 of the lineage work already on the UI backlog** — build them
  together, because this system is its first real consumer.
**(b) NATIVE — offers, events, updates, with no article behind them.**

- Authored against the knowledge base the same way every other draft is: it
  may assert only what an approved claim already says, and the offer's own
  terms (dates, discount, conditions) are OWNER INPUT, not model output — a
  generator inventing a discount is the one failure mode here that costs real
  money.
- Held to the LISTING'S OWN FACTS. This is why step 1 mirrors hours, address
  and attributes before anything writes: a post announcing Sunday opening on a
  listing that says closed Sunday is worse than no post, and only the mirror
  can catch it.
- Google's post types carry structure — an offer has a window and a redeem
  link, an event has a start and end — so these are typed at emit rather than
  being free text with a date in it.

**Cadence**: one derived post per approved article, plus native posts on the
plan's own schedule. Weekly, because a GBP post's prominence decays fast and a
monthly cadence is the same as none.

**AND THE APPROVAL POLICY IS THE OWNER'S CALL, not this design's.** "Held for
review, approving is what publishes" is carried over from the ESP flow the
owner inverted deliberately — it is a POLICY, not a technical limit. If routine
native posts should go out on a cadence unattended, that is the autonomy ladder
doing its job (`shadow` → `approve_all` → `auto`), and the contract gate in §3
is what has to be answered before `auto` is earned. Nothing here needs
rebuilding to allow it.

---

## §6 The compliance edge, per brand — the part most likely to bite

A GBP post is short, public, hosted by Google, and edited by nobody after it
lands. The existing per-brand rules bind harder here than anywhere else.

- **Baci** — Italian-DESIGNED, mass-made. Never made-in-Italy, handmade,
  hand-decorated, artisanal, craftsmanship. There is no room in 1,500
  characters for the qualifying sentence that makes those safe elsewhere, so
  `constitutive=("banned_claims",)` is not optional: no ban list, no post.
- **Eien Health — ANSWERED by the owner 2026-08-29, and it is simpler than the
  question.** *"We dont have to have a disclaimer on every post, should on the
  website and we can just ensure no claims are made on posts too much."* So:
  **Eien is IN.** The FDA/DSHEA disclaimer belongs on the WEBSITE, where the
  claims are made; a post that makes no structure/function claim needs no
  disclaimer, because there is nothing to disclaim. The rule the generator is
  held to is therefore *no health claim in a post*, enforced the way every
  other content rule here is — the ban list plus the validator — rather than a
  block of legal text stapled to 1,500 characters. AI-generated imagery still
  carries its label; that is about the image, not the copy.
- **Any local client** — a post that contradicts the listing's own hours,
  address or attributes is worse than no post. The read-only mirror in step 1
  exists partly so the drafter can be held to the listing's own facts.

---

## §7 The build, in shippable steps

Same working agreement as the UI overhaul: one step per push, every step
leaves the app usable, every step ships with its guard, owner reviews before
the next begins.

**Step 0 — the access application. Do this now; it gates everything.**
Cloud project + application from an owner/manager email, per §2. Costs an
hour; buys weeks. No code.

**Step 1 — read-only. Connect, MIRROR, and AUDIT.**
`app/gbp.py` with auth + Business Information v1 reads only. Locations, hours,
attributes, review count land in the data layer. Connections gains a `gbp`
provider with a real Test button; the capability appears; Diagnostics sees a
platform that answers. **Nothing writes.** **And `gbp_listing_audit` lands here** — it needs
nothing but reads, and it is the half that moves local rank, so the first
deliverable is a prioritised list of listing fixes for a real client rather
than a connection nobody can use yet. Gate: the credential is proven against a
live listing before a single write path exists, and the audit produces a
reviewable report for one real venue.
Guards: `gbp_reads_do_not_write`, `gbp_capability_gates_the_system`.

**Step 2 — the deriver and the skill. Drafts only, no push.**
`_run_gbp_post` derives from an approved source artifact, emits a held
`ArtifactBody(format="gbp_post")`, runs every existing gate. Review shows it;
the workroom previews it as it will render, with its CTA and image; feedback
and redraft ride the paths that already exist. Gate: a real derived post for
a real account, reviewed, with the source link working both ways.
Guards: `a_post_asserts_nothing_new`, `no_post_without_a_ban_list`,
`post_names_its_source`.

**Step 3 — the push. Approval-executed.**
`push_post_to_gbp` in the `push_campaign_to_esp` shape: the ONLY external
write, called by the approval executor, idempotent by destination, refuses
withdrawn verdicts and recorded defects, honest failure with a retry control
in the workroom. **Approving is what publishes.** Gate: the owner watches the
first live post through hold → approve → push, per the standing rule that
every live first has found a defect.
Guards: `approving_publishes_the_post`, `push_refuses_withdrawn`.

**Step 4 — the measurement, per §3.**
Performance v1 location metrics into the reports layer; the contract fields
answered; the system becomes promotable past shadow.

**Step 5 — cadence in Plan.**
GBP rows in the Schedule so planned-vs-happened works for local the way it
does for campaigns.

---

## §8 Named non-goals, so they are parked rather than forgotten

- **Review replies** — genuinely valuable and a DIFFERENT system: it is
  mail-shaped (inbound, per-customer, tone-sensitive), belongs with
  `service_desk`/`lead_responder`, and must not be bolted onto a posting
  system because both touch GBP.
- **Q&A seeding** — same reasoning, plus it is close to review-gaming and
  needs a policy decision first.
- **Photo management** beyond the post's own image.
- **Bulk multi-location** — until a client has more than about five, the
  per-location path is enough and the bulk path is speculative.
Note what is NOT on this list any more: **unattended publishing.** It was
listed as a non-goal in the first draft and that was wrong — it is a rung on
the autonomy ladder every other system already has, gated on the contract
being answered (§3), not a thing this system refuses to do.

---

## §9 Open questions for the owner

1. ~~**Eien** — off entirely, or restricted to non-claim content?~~
   **ANSWERED 2026-08-29: Eien is IN.** The disclaimer belongs on the website;
   posts simply make no claims. See §6.
2. **STILL OPEN, and it is the only thing blocking step 1:** which listings do
   we actually control today, and are they verified and 60+ days old? That
   decides who can be audited first — and the audit is the half that moves
   local rank, so it decides where the first value lands.
3. ~~Is the weekly filler post wanted at all?~~ **ANSWERED by §5's correction:**
   native posts are a first-class producer, not filler. What is still open is
   whether offers and events should reach `auto` on the ladder once the
   contract is answered, or stay owner-approved for good — a business decision
   about a public surface, not a technical one.

---

## §10 A note on how this file read the first time

The owner's response to the first draft was *"I don't understand the issues …
are we just trying to create a GBP system with only the existing pathways for
some reason? What seems to be the issue you found?"* — and that was the right
question. There were **no blocking issues**; ordinary design decisions were
written up as if they were problems, which made a straightforward build sound
fraught. Two external facts are real (the access application, the dead
post-analytics endpoint) and neither stops anything.

Reusing the existing paths for auth, drafting, the ban-list gate, review and
push IS the right call — days instead of weeks, and GBP posts inherit the
compliance gates that already exist. But reuse is leverage, not a boundary on
what the system may do: where it started shaping the FEATURE SET rather than
the implementation — derived posts only, no unattended publishing — it was
wrong, and §5 and §8 are corrected above.
