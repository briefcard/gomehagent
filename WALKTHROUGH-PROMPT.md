# The system walkthrough — the prompt to open each thread with

The owner walks the platform one system at a time, finds issues by USING it,
and fixes them one at a time. This file is the prompt that opens each of those
threads, and the protocol they follow. Paste §1 verbatim; it names the system.

The order is in §3. Ask for "the next system" and the thread reads §3, marks
the one it just finished, and tells you which is next.

---

## 1. Paste this (replace `<SYSTEM>` with the one being walked)

> You are continuing the gomehagent build at `/Users/gomehsaias/Documents/gomehagent-build`
> (deployed at https://assistant-web-zm2d.onrender.com).
>
> **We are walking ONE system at a time. This thread is about `<SYSTEM>` and
> nothing else.** I will use it, find issues, and give them to you one at a
> time. Do not go looking for work in other systems; if you notice something
> elsewhere, write it down and tell me at the end.
>
> **Before I give you the first issue, get deeply familiar with this system —
> from the CODE, not from documentation and not from memory.** Read
> `WALKTHROUGH-PROMPT.md` §2 for exactly what "familiar" means here, do it, and
> then give me the briefing it asks for. Documentation is a hint about where to
> look; every fact you tell me must come from a file you actually opened, with
> the `path:line` to prove it.
>
> Then stop and wait for me.

---

## 2. What "familiar" means before the first issue

Do all of it, then produce the briefing at the end. Keep it under ~500 words:
the point is to prove you looked, not to write an essay.

1. **The declaration.** `systems.CATALOG[<system>]` — its `requires`, its
   `workflow.skill`, its `kb_needs`, its cadence. And `skill.REGISTRY` for the
   skill it names: parameters, `constitutive` needs, what it emits.
2. **The path a run takes**, named as functions, end to end: planner (if any)
   → `systems.take_plan` → `skill.run` → the bundle it resolves → the drafter
   → `Context.emit` → the three gates (`validator.check`, `coherence.review`,
   `artifact_check.check`) → `ledger.record` + `ArtifactBody` → approval →
   executor → write-back. Say which steps this system actually HAS; several
   systems are missing several, and that is often where the issue is.
3. **The data layer it reads.** Which of claims / objections / audiences /
   situations / entities / keywords / assets reach this system, WHICH
   generator receives each one, and WHICH gate enforces it. **A rule that
   reaches no validator is a rule that does not exist** — if you find one, say
   so before I ask.
4. **Its surfaces.** Every place in `admin_ui.py` this system is rendered or
   controlled, and every route in `web.py` that acts on it. For each surface:
   what it SAYS and what it lets you DO there. A fact reported with no control
   beside it is a defect in this codebase (see SYSTEMS-REFERENCE §6).
5. **What it is waiting on.** `systems.awaiting(tenant, key)` for a real
   account, and `kb.needs_met` — the distinction between "nobody has told us
   yet" and "it is written and waiting on you" matters and they have different
   fixes.
6. **Its guards.** `grep` the system's modules in `scripts/sabotage.py` and
   name which suites cover it. If a load-bearing behaviour has no guard, say
   which.
7. **Run it once** if it can be run offline, and show me what came out.

**The briefing:** the run path with the missing steps called out · what the
data layer contributes and where it is enforced · the surfaces and what each
lets me do · what it is waiting on · anything that is declared and read by
nobody. End with the two or three things you EXPECT me to hit, and why.

---

## 3. The order, and where we are

Ten systems (`systems.CATALOG`), then the machinery that is not a system but
that every system rides. Mark each as it is finished — this file is the
running record, so update it in the thread that finishes one.

| # | system | skill | status |
|---|---|---|---|
| 1 | `blog` | `blog_article` | not walked |
| 2 | `campaign_email` | `campaign_email` | **walked** 2026-08-31 — see §5 |
| 3 | `ad_creative` | `ad_copy` | not walked |
| 4 | `content_compliance` | — | not walked |
| 5 | `catalog_compliance` | — | not walked |
| 6 | `service_desk` | — (mail-owned) | not walked |
| 7 | `lead_responder` | — (mail-owned) | not walked |
| 8 | `moment_email` | — (a watcher) | not walked |
| 9 | `reorder_engine` | — (declared, no generator) | not walked |
| 10 | `reports` | — (declared, no generator) | not walked |

Then the cross-cutting machinery, same protocol, same briefing shape:

| # | area | where it lives |
|---|---|---|
| 11 | the creative seam | `creative.py`, `compose.py`, `media.py`, `hosting.py` |
| 12 | the knowledge base | `kb.py`, the Knowledge tab, intake |
| 13 | the gates | `validator.py`, `coherence.py`, `artifact_check.py`, `assurance.py` |
| 14 | approvals & the ladder | `approvals.py`, `systems.py` GATES, the digest |
| 15 | connections & credentials | `credentials.py`, `oauth.py`, Connections |
| 16 | the plan | `keywords.py`, `planner.py`, the Plan tab, `results.py` |

**Suggested start: `blog`.** It is the most complete pipeline — planner,
skill, gates, approval, executor, write-back, and a closed measurement loop —
so it is where "what a finished system looks like" is defined, and every later
walk can be measured against it. `ad_creative` is worth doing third rather
than first: it changed most recently and the newest code is the least worn in.

---

## 4. How a fix lands (unchanged, and not negotiable)

- **Reproduce it first.** A fix for a defect nobody reproduced is a guess.
- **Ship through the ritual:** `./scripts/ship.sh "<subject>" <body-file>` —
  it gates on byte-compile → web import → the full suite, then commits and
  pushes (which deploys). **Never edit the working tree while it runs.** Put
  the subject on the FIRST LINE of the body file: with a body file, ship.sh
  uses the file as the whole message and ignores the subject argument.
- **Every fix ships with its sabotage guard**, and the guard must report
  `[ caught ]` — `python3 scripts/sabotage.py <name>`. `MISSED` means the test
  around it is decoration; the usual cause is that the test called a helper
  directly instead of the surface, or asserted on a label instead of the
  thing.
- **Every console fact ships with its control.** If you tell the owner
  something is missing, the button that fixes it belongs on the same surface.
- **Turn the claim into a check.** A claim about EVERY instance is computed
  from the source (an AST walk, a schema walk), never surveyed by eye.
- **Verify the deploy on `/health`**, which reports the commit. Never infer
  what is running.

---

## 5. What each walked system established

One section per walked system. **Standing rules and traps go here; code facts
go in `scripts/test_open_defects.py`,** which fails the moment a fact stops
being true. Do not restate a code fact in prose — that is how
`SYSTEMS-REFERENCE.md` went stale.

### `campaign_email` — walked 2026-08-31 (commits `bef67d7`..`987b6d4`)

**The one root cause behind every defect found.** An input read by one place
and supplied by another, with nothing declaring the obligation. Every issue in
this walk was an instance: `audiences` (read by every drafter, written by
nobody), `offer` (read, undeclared), `audience_key` (declared, unread),
`revision_notes` (declared supplier was fiction, three private hops),
objections (returned `[]` for generative systems, so the run *denied* what was
on file), `blog_article`'s commitment never reaching `emit` (zero coherence
rules ever ran on an article), claim selection falling back to insertion order
(the six oldest claims won forever).

**Where it now lives.** `app/bundle.py` is the declared package: `PARTS` with
tier, supplier, and absent-semantics; `verify()` at runtime; `audit()` static.
`scripts/test_skill_conformance.py` computes the obligations from the registry
by AST walk — declared↔read in both directions — so a new skill inherits the
contract or fails the suite. That file is the answer to "how do I not miss an
input again"; read it before adding a system.

**The owner's standing rules** (stated in this walk; they bind every system):

- **Claims are human-approved knowledge about entities, brands, policies, or
  positioning.** Generators propose; they never populate. Do not turn model
  output into claims — it defeats the approval process.
- **Overwhelming is not conflicting.** Prefer a data layer full of quality,
  well-associated context over a sparse one. World knowledge that does not
  contradict an approved claim is not a problem to be gated.
- **Audience is singular, and required for anything generated.** One audience
  at a time, always — no piece of content is written without knowing who it
  speaks to. *Audiences* plural applies only to segments in one-to-many
  marketing (email campaigns, ads), never to individual correspondence.
- **Segment ≠ audience.** Segment is who RECEIVES (the ESP cohort). Audience is
  who it is WRITTEN FOR (the persona with pains, vocabulary, buying trigger).
- **Entities, not products.** A product is one kind of entity; venues and
  digital offerings are others. Never write product-shaped code or copy.
- **Thin knowledge caveats a promotion, it never vetoes one.** Shadow is the
  **Learning phase**, and manual approval is available inside it.
- **A hero, not a monogamy rule.** One artifact may mention several entities;
  it may not mix their positioning. Ads are exempt — that is what the
  positioning input is for.
- **Don't just do to do — assess the sense.**

**Traps this walk fell into.** Each cost a cycle; do not repeat them:

1. **Shipping a claim about "every instance" that was surveyed by eye.** Two
   AST audits were wrong (a loop-variable subscript `ctx.bundle[_k] = ...` read
   as absent; documented back-compat read as noise). Resolve loop variables,
   and check `git log -S` before calling something accidental.
2. **A guard that reports `MISSED` is decoration.** Two tests asserted on the
   bundle when only the prompt had changed, and one passed against `None`
   because preflight blocked the run. `python3 scripts/sabotage.py <name>` must
   print `[ caught ]` or the fix is unproven.
3. **Believing a commit message over the code.** `c4f72cc` claimed the workroom
   redraft was covered; it was not, and every Request-changes click refused on
   any account with a persona. Fixed in `c49477f`.
4. **Nearly shipping a no-op.** Measure the current behaviour before writing
   the fix — `resolve` already scoped claims by entity, so the "fix" changed
   nothing. Reverted with the measurement written into the commit.

**Open, in the order to take them** (all proven; see `test_open_defects.py`):

1. **Index our replies.** `EmailLog.body_excerpt` stores inbound mail only; our
   reply lives in an Approval payload and is never indexed. So the archive
   answers "what did they ask before" and never "how did we answer". The
   agentic `email_history_search` tool can reach sent mail, but that is a tool
   the model may call — not context the prompt is assembled from.
2. **One surface that reports success wrongly** — `SYSTEMS-REFERENCE.md` is
   stale. (The other two are closed, both into
   `scripts/test_catalog_vocabulary.py`, which joins every list derived from
   `systems.CATALOG` back to the declaration: the `kb_needs` vocabulary must
   reach an answer in `kb.KB_SUPPLIERS`, and `dossier.SCOPES` is now computed
   over CATALOG rather than written beside it.)
3. **The input register** — as the JOIN computed from the declaration surfaces,
   **not a fourteenth place to state things.** Do 2 before 3: the register
   would faithfully report a vocabulary that currently cannot be trusted.

**Left deliberately unchanged, flagged not fixed:** the `auto` rung produces
`"cleared"`, which nothing consumes — so it cannot actually push. Five CATALOG
systems have no skill at all (`content_compliance`, `lead_responder`,
`moment_email`, `reorder_engine`, `reports`), so no contract reaches them.

**Open question the owner has not answered:** should `blog_article` require a
reader? It is one-to-many, but its reader is defined by search intent.
