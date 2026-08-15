# Build state — 2026-08-14, after step 01

The rolling state of the data-layer build. **This file is rewritten by every
thread.** It is always current and never historical — do not add dated sections
to it, and do not create `HANDOFF-step-N.md` files. History lives in
`DEFECTS.md` (append-only) and in the git log.

`HANDOFF-content-platform.md` is the **historical** record of the platform
build up to 2026-08-13. It is no longer updated and parts of it are already
stale — it describes the execution half as tenant-blind, which is no longer
true. Read it for background, not for state.

Plan of record: the Data Layer Build Map (11 steps).

---

## Where we are

Step 01 is done. The situation classifier no longer asserts a tag on weak
evidence: `kb.suggest_tags` returns `confident`, `score` and `candidates`
alongside `tags`, and a guess that clears neither of two floors comes back with
no tag and a legible reason. Everything that routes on situations — the
resolver in step 03, and every system after it — now has a signal it can refuse
on. Nothing else changed; no schema, no routes, no behaviour outside this
function.

## Verified vs assumed

**Ran and confirmed:**

```
python3 scripts/test_classify.py          25 checks, all passed
python3 scripts/test_harvest.py           all checks passed
python3 scripts/test_provenance.py        all checks passed
python3 scripts/test_claim_tagging.py     all checks passed
python3 scripts/test_kb.py                all checks passed
```

Plus the remaining 17 offline suites from `RUNBOOK.md` §8 — `test_selection`,
`test_systems`, `test_intake`, `test_kb_ui`, `test_tenant_scope`,
`test_migration`, `test_console_auth`, `test_credentials`,
`test_tenant_isolation`, `test_worker_systems`, `test_catalog_sync`,
`test_compliance`, `test_extract`, `test_email_harvest`, `test_sources`,
`test_oauth`, `test_brief --demo` — all exit 0. **21 suites green, none
touching the network.**

**Built but unproven:**

- **The floors are reasoned, not tuned.** `MIN_SHARED_WORDS = 2` and
  `MIN_LEARNED_SCORE = 0.5` come from the scoring function's own arithmetic
  and from two constructed cases that isolate each floor. They have **not**
  been run against production rows — this session had no access to the live
  database. Before anything routes live traffic through the classifier,
  re-check them against real Baci and agency claims. The step 01 exit contract
  asked for tuning against real rows; this is the part of it that is not met.
- **No live call was made.** Everything above is the offline harness.

## Commit

`feat/context-architecture`, one commit on top of `5566ebb`. Base was clean and
level with `origin/main` (`git rev-list --count origin/main..HEAD` was 0 before
this work).

**Not pushed.** Pushing `main` auto-deploys to Render, and that is the owner's
call, not a build thread's. Nothing here is risky to deploy — one function, no
schema, no routes — but it also gains nothing until step 03 consumes it.
Reasonable to batch with steps 02–03.

## Next thread starts here

**Step:** 02 — Conversation, Touch, Commitment
**Size:** large, budget a full thread; see the split point below

**Read, and only these:**

- `app/db.py` — `Contact`, `Approval`, `EmailLog`, `_Provenance`
- `app/tenant_scope.py` — `resolve()` is what writers call to attribute a row
- `scripts/test_tenant_isolation.py` — the mandatory rule as a test
- `scripts/test_migration.py` — migration over a database that already has rows

Do **not** search the repo broadly. The four files above are sufficient.

**Touches:** `app/db.py`, new `app/conversation.py`, new
`scripts/test_conversation.py`

**Done when:**

- `Conversation` carries tenant, contact_id, system_key, stage, status,
  next_action_at, situations, entity_key. `Touch` carries channel, direction,
  sent_at, run_id, idempotency_key. `Commitment` records what was told to whom,
  with a value and a date, so a validator can check it later.
- Tenant-scoped from birth — `test_tenant_isolation.py` passes **unmodified**.
- Stages are declared per `system_key` as data, not hardcoded per system.
- The migration includes a backfill. A new column with meaningful defaults and
  no backfill regresses behaviour silently — DEFECTS §1, *migration adds
  columns, not values*.

**Verify:**

```bash
python3 scripts/test_conversation.py && \
python3 scripts/test_tenant_isolation.py && \
python3 scripts/test_migration.py
```

**Split point if the thread runs long:** land the models plus CRUD first and
stop. The stage machine and `next_action_at` scheduling become step 02b.

**Watch for:**

- `Approval` already has `tenant`, `system_id` and `run_id` columns, and
  **nothing writes the last two**. Step 02 is the natural moment to wire
  `run_id`, since `Touch` needs the same link.
- `ops_jobs.py` is the one file in the execution half with zero tenant
  references. Out of scope for step 02, but it is where a cross-client bug
  will surface first once client rows land in the operational tables.

## Defects filed

- **DEFECTS §2.24** — *One shared word asserted a situation tag* (fixed). The
  fourth instance of §1 *unknown collapsed into a value*, and the first entry
  in the log caught by reading rather than by a failing run.
- Noted inside §2.24, **not fixed**: `email_harvest.py:314` and the equivalent
  in `harvest.py` ignore `add_claim`'s returned status string, so a dedupe
  refusal or an unknown-tag rejection disappears without a count. §1 *silent
  loss*, in live code.

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
   has no mailbox at all — that one is an authoring job.
