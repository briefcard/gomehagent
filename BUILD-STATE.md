# Build state — 2026-08-14, after step 02

The rolling state of the data-layer build. **This file is rewritten by every
thread.** It is always current and never historical — do not add dated sections
to it, and do not create `HANDOFF-step-N.md` files. History lives in
`DEFECTS.md` (append-only) and in the git log.

`HANDOFF-content-platform.md` is the **historical** record of the platform
build up to 2026-08-13. It is no longer updated and parts of it are already
stale — it describes the execution half as tenant-blind, which is no longer
true. Read it for background, not for state.

Plan of record: the Data Layer Build Map (11 steps). Steps 01 and 02 are done.

---

## Where we are

The layer now has both halves. The knowledge half already answered *what is
true about this brand*; `app/conversation.py` answers *what is true about this
conversation*, and the two meet at `Conversation.situations` — the field the
resolver will hand to `kb.objections()` in step 03.

**Step 01** — the situation classifier stopped asserting tags on weak evidence.
`kb.suggest_tags` returns `confident`, `score` and `candidates`; a guess that
clears neither of two floors comes back with no tag and a legible reason.

**Step 02** — three new models and a read/write layer over them:

- `Conversation` — the state machine and the retrieval key. Two email chains
  with the same person for the same system fold onto **one row** via
  `open_or_get`, with every provider thread id kept in `external_refs`. That is
  the overlapping-threads problem closed. Reuse is a lookup on
  `status == "open"`, not a unique constraint, so a lead who goes quiet and
  returns next quarter correctly starts a second conversation.
- `Touch` — bounded history plus the idempotency guard. An **outbound touch
  without an idempotency key is refused**; inbound defaults its key to the
  provider's own message id. A repeat writes nothing and returns the original.
- `Commitment` — what we told them, as a row a validator can check. This is
  what makes "effective without misleading" enforceable rather than a line in
  a prompt.

`state_for()` is the read step 03 will call. It reports absence explicitly
(`exists: False` plus a reason) rather than returning a blank that reads
downstream as "nothing happened".

## Verified vs assumed

**Ran and confirmed — 23 offline suites, all exit 0, none touching the
network:**

```
python3 scripts/test_classify.py          25 checks   3s
python3 scripts/test_conversation.py      40 checks   2s
python3 scripts/test_tenant_isolation.py  passed      3s   ← unmodified
python3 scripts/test_migration.py         passed      1s
```

plus `test_kb`, `test_harvest`, `test_provenance`, `test_claim_tagging`,
`test_selection`, `test_systems`, `test_intake`, `test_kb_ui`,
`test_tenant_scope`, `test_console_auth`, `test_credentials`,
`test_worker_systems`, `test_catalog_sync`, `test_compliance`, `test_extract`,
`test_email_harvest`, `test_sources`, `test_oauth`, `test_brief --demo`.

**`test_tenant_isolation.py` passes unmodified** — verified with
`git diff --stat` showing no change to that file. Three new models entered the
schema and none needed an entry in `PLATFORM_MODELS`. That test is also what
forced `Touch.idempotency_key` to be a composite `UniqueConstraint` with
`tenant` rather than a globally unique column: a global unique on a per-client
table means two clients cannot both use the same key, and
`test_conversation.py` now asserts that they can.

**Timing note for the next thread:** the full suite takes ~2m10s wall clock, so
running all of it in one shell call hits a 2-minute default timeout. Split it,
or raise the timeout. `test_sources` is 52s, `test_harvest` 16s,
`test_selection` 15s; everything else is 1–4s.

**Built but unproven:**

- **The classifier floors are reasoned, not tuned.** `MIN_SHARED_WORDS = 2` and
  `MIN_LEARNED_SCORE = 0.5` come from the scoring arithmetic and two
  constructed cases that isolate each floor, not from production rows — no
  database access in either session. Re-check against real Baci and agency
  claims before live traffic routes through the classifier.
- **No live call has been made against either step.** Everything above is the
  offline harness.
- **No conversation has been created by a real system**, because nothing calls
  `conversation.py` yet. Step 03 is its first consumer.

**Deliberately not done — no backfill, and that is a decision:**

Step 02's exit contract asked for a migration backfill. Three *new* tables need
none: `create_all` builds them and `_auto_migrate` only ever adds columns to
tables that already exist. The backfill that could have been written —
deriving historical `Conversation` rows from `EmailLog` — was not, on the same
grounds as `tenant_scope.UNDERIVABLE`: a wrongly attributed row is worse than
an absent one, because nothing downstream will ever question it. History stays
blank; conversations start when a system starts one.

## Commit

`feat/context-architecture`, two commits on top of `5566ebb` (`193196a`, then
step 02). Base was clean and level with `origin/main`.

**Not pushed.** Pushing `main` auto-deploys to Render, and that is the owner's
call. Neither step changes a route or an existing behaviour — step 02 is
additive schema plus a module with no callers — so it is safe to deploy and
gains nothing until step 03 lands. Reasonable to batch all three.

## Next thread starts here

**Step:** 03 — the resolver, the coverage receipt, and a read-only key
**Size:** large, budget a full thread

**Read, and only these:**

- `app/tenants.py::agent_block` — the compact identity + rules block, already
  written and already the right shape for tier 1
- `app/kb.py` — `objections`, `support_for`, `match_entities`, `completeness`,
  `suggest_tags` (note its new `confident` / `score` / `candidates` keys)
- `app/conversation.py::state_for` — the state half of the bundle
- `app/systems_map.py::block` — how an every-turn injection is kept small
- `app/web.py` — the auth section only, for where the read-only key goes

Do **not** search the repo broadly. Those five are sufficient.

**Touches:** new `app/resolve.py`, `app/web.py`, `app/config.py`, new
`scripts/test_resolve.py`

**Done when:**

- `resolve(tenant, system, contact?, utterance?, entity?)` returns a tiered
  bundle: tier 1 rules always, tier 2 situated objections plus their support
  claims, tier 3 entity match and conversation state.
- The **coverage receipt** states what was searched and what could not be
  grounded. An account missing a required field returns `blocked_on` naming
  the field rather than a thin bundle that looks complete.
- An unconfident classification does **not** silently retrieve tier 2. It says
  it could not place the utterance and returns the candidates.
- The read-only key reaches the read routes and nothing else. Today's
  `APPROVAL_SECRET` also fires GET routes that mutate (`/admin/seed_kb`,
  `/admin/kb_add`, `/admin/tenant_scope`, `/admin/harvest`), so handing it to
  a consumer hands over write access.

**Verify:**

```bash
python3 scripts/test_resolve.py
python3 scripts/test_classify.py && python3 scripts/test_conversation.py
```

Then a live call per tenant with the read-only key, and one with that key
against a write route proving refusal.

**Watch for:**

- **Baci and Ironside will return `blocked_on` for most requests, and that is
  correct.** Objections are zero on all five accounts. Do not weaken the
  bundle to make a demo look better — a thin bundle that reads as complete is
  the failure this receipt exists to prevent.
- `Approval.system_id` and `run_id` are still written by nothing. `Touch` now
  carries `run_id`, so step 03 or the first generator is the moment to wire
  both together.
- `ops_jobs.py` remains the one file in the execution half with zero tenant
  references.

## Defects filed

- **DEFECTS §2.24** — *One shared word asserted a situation tag* (fixed in
  step 01). Fourth instance of §1 *unknown collapsed into a value*, and the
  first entry in that log caught by reading rather than by a failing run.
- Noted inside §2.24, **not fixed**: `email_harvest.py:314` and the equivalent
  in `harvest.py` ignore `add_claim`'s returned status string, so a dedupe
  refusal or unknown-tag rejection disappears without a count. §1 *silent
  loss*, in live code.
- **Step 02 found no new defect.** Nothing is filed for it, rather than
  something being manufactured to fill the section.

## Owner track — runs alongside, blocks content not code

1. `CREDENTIAL_KEY` in the `assistant-env` group. Setting it later orphans
   every credential stored before it.
2. `ANTHROPIC_API_KEY` in the same group, or harvest silently runs a path
   measured at 0% recall. Check the `extractor` field, not the proposal count.
3. `GOOGLE_CLIENT_ID` / `_SECRET`, `META_APP_ID` / `_SECRET`, plus both
   redirect URIs registered byte for byte. Then prove the Google flow on Baci —
   it has never run against a real provider.
4. Author objections on at least one account. They are zero on all five, and
   sent-mail harvest (which needs #3) is the only derivable source. Ironside
   has no mailbox at all — that one is an authoring job. **This is now the
   binding constraint on step 03 showing anything useful.**
