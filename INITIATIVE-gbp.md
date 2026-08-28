# INITIATIVE — Google Business Profile as a system

Local presence, run the way every other system here is run: derived from what
the brand has already published, gated by the ban list, **held for review**, and
pushed only when a person approves it. Written 2026-08-28 after the owner asked
whether Claude has a GMB skill to automate this. It does not — nothing in the
skill set, no connector on any MCP server, no scaffolding in this repo — so
this is the plan to build it here.

**NOT SCHEDULED YET, DELIBERATELY.** Step 4 of INITIATIVE-ui-overhaul has one
tab left. This file exists so the design is decided while it is fresh and so
the ONE part with a wall-clock dependency — Google's access approval — can be
started immediately, independently of the build.

---

## §0 Where this stands

Nothing is built. The critical path is not engineering:

| | state |
|---|---|
| Google API access | **NOT APPLIED FOR — do this first, it is a queue** |
| `app/gbp.py` provider adapter | not written |
| `gbp_post` skill in `app/skill_pack.py` | not written |
| `gbp_post` system in `systems.SPECS` | not declared |
| `gbp` capability + connection | not wired |

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

## §5 Propagation — the thing actually asked for

*"Automatic updates adhering to brand voice / content / articles we may be
posting elsewhere propagated to GMB."* The design that makes this safe:

- **A GBP post is DERIVED, never authored from nothing.** Its input is an
  artifact that has ALREADY been approved — a published blog article, a sent
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
- **Cadence**: one post per approved article, plus a standing weekly filler
  drawn from the plan when no article shipped that week. Weekly because a GBP
  post's prominence decays fast; a monthly cadence is the same as none.

---

## §6 The compliance edge, per brand — the part most likely to bite

A GBP post is short, public, hosted by Google, and edited by nobody after it
lands. The existing per-brand rules bind harder here than anywhere else.

- **Baci** — Italian-DESIGNED, mass-made. Never made-in-Italy, handmade,
  hand-decorated, artisanal, craftsmanship. There is no room in 1,500
  characters for the qualifying sentence that makes those safe elsewhere, so
  `constitutive=("banned_claims",)` is not optional: no ban list, no post.
- **Eien Health** — the mandatory FDA/DSHEA disclaimer and the † convention
  have **nowhere to live** in a GBP post, and AI-generated imagery must be
  labelled next to the image. This needs an owner decision before Eien is
  enabled: either the system is off for Eien, or Eien posts only
  non-structure/function content. **Do not default it on.**
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

**Step 1 — read-only. Connect and MIRROR.**
`app/gbp.py` with auth + Business Information v1 reads only. Locations, hours,
attributes, review count land in the data layer. Connections gains a `gbp`
provider with a real Test button; the capability appears; Diagnostics sees a
platform that answers. **Nothing writes.** Gate: the credential is proven
against a live listing before a single write path exists.
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
- **Anything that publishes without a person.** The send is the approval,
  here as everywhere. A local listing is the most public surface any of these
  clients has.

---

## §9 Open questions for the owner

1. **Eien** — off entirely, or restricted to non-claim content? (§6)
2. Which listings do we actually control today, and are they verified and
   60+ days old? That decides who can be in step 1.
3. Is the weekly filler post wanted at all, or only article-derived posts?
   (A filler with nothing to say is how a feed becomes noise.)
