# Build state — 2026-08-14, after step 03

The rolling state of the data-layer build. **This file is rewritten by every
thread.** It is always current and never historical — do not add dated sections
to it, and do not create `HANDOFF-step-N.md` files. History lives in
`DEFECTS.md` (append-only) and in the git log.

`HANDOFF-content-platform.md` is the **historical** record of the platform
build up to 2026-08-13. It is no longer updated and parts of it are already
stale — it describes the execution half as tenant-blind, which is no longer
true. Read it for background, not for state.

Plan of record: the Data Layer Build Map (11 steps). **Steps 01–03 are done.**

---

## Where we are

The layer has both halves and a single door into them.

**Step 01** — the classifier stopped asserting tags on weak evidence.
`kb.suggest_tags` returns `confident`, `score` and `candidates`; below either
of two floors it returns no tag and a legible reason.

**Step 02** — `Conversation`, `Touch`, `Commitment` on top of `Contact`. Two
email chains with one person fold onto one row; an outbound touch without an
idempotency key is refused; a commitment is a row a validator can check.

**Step 03** — `app/resolve.py`. One call returns a tiered bundle plus a
coverage receipt, and `GET /resolve` serves it behind a read-only credential.

The three pieces now compose: a conversation carries `situations`, the
classifier decides whether an utterance can be placed against them, and the KB
serves the objections and support claims for what was placed. Where any link
fails, the bundle blocks and names the field rather than answering anyway.

**What `resolve()` refuses to do, which is the point:**

- An **unplaceable utterance retrieves nothing.** Ranking objections against a
  tag nobody stands behind returns a plausible answer aimed at the wrong
  problem, and nothing downstream could tell it from a good one. The skip is
  recorded with its reason and the near-miss candidates ride along.
- An account with **no ban list is blocked, not warned** — nothing can validate
  output against rules that do not exist.
- `coverage.complete` is **never optimistic**. A bundle that skipped retrieval
  is not complete, whatever it managed to return.

## Verified vs assumed

**Ran and confirmed — 24 offline suites, all exit 0, none touching the
network:**

```
python3 scripts/test_resolve.py           30 checks   ← new
python3 scripts/test_classify.py          25 checks
python3 scripts/test_conversation.py      40 checks
python3 scripts/test_tenant_isolation.py  passed      ← still unmodified
```

plus `test_kb`, `test_kb_ui`, `test_harvest`, `test_provenance`,
`test_claim_tagging`, `test_console_auth`, `test_credentials`,
`test_selection`, `test_systems`, `test_intake`, `test_tenant_scope`,
`test_migration`, `test_worker_systems`, `test_catalog_sync`,
`test_compliance`, `test_extract`, `test_email_harvest`, `test_oauth`,
`test_sources`, `test_brief --demo`.

**Timing:** the full suite is ~2m10s wall clock, so running all of it in one
shell call hits a 2-minute default timeout. Split it. `test_sources` is 52s,
`test_harvest` 16s, `test_selection` 15s; the rest are 1–4s.

**Live:** steps 01–02 and the calibration route are deployed (`a788f30`).
`/health` returns `ok:true`; `/admin/calibrate_classify` returns 200. Step 03
is committed but **not pushed**.

**Built but unproven:**

- **`/resolve` has never run against the live database.** Every check above is
  the offline harness on SQLite.
- **The classifier floors are still reasoned, not tuned.** The instrument
  exists and is deployed:

  ```bash
  curl -b ~/.gomeh-console -s \
    "https://assistant-web-zm2d.onrender.com/admin/calibrate_classify" | jq
  ```

  Read-only. **It has not been run yet.** Expect `enough_to_calibrate: false` —
  Baci has 3 tagged claims and agency 12 against a `CALIBRATION_MIN_N` of 25.
  On a seeded smoke test the correct placements clustered at 1.51–1.77 and a
  single mistag sat at 0.67, which hints 0.5 may be too permissive — but that
  was n=5 synthetic and proves nothing.

## Commit

`feat/context-architecture`. `origin/main` is at `a788f30` (steps 01–02 plus
calibration, deployed). Step 03 is one commit on top, **not pushed**.

Pushing needs one thing first, or the new credential is dead on arrival — see
the owner track: **`READ_KEY` must exist in the `assistant-env` group.** Unset
means read-only access is disabled (it fails closed, not open), so `/resolve`
will only answer the admin secret until it is set.

## Step 03b — semantic recall — BUILT, needs one env var to switch on

`app/embed.py` plus `KbEmbedding`, a semantic tier inside `suggest_tags`, an
approve-time index hook, and `/admin/embed_backfill`. 25 offline suites green.

**The authority order is now three deep:** pattern is a decision, semantic is
the second authority, word overlap is the floor and the offline path. `path`
names which one decided; `degraded` carries the reason when semantic could not
run. That pairing is the `extractor: "deterministic filter"` lesson — a
fallback that looks like the real path is how something ran at 0% recall for
weeks.

**Storage is a seam, not a decision.** `embed.Backend` is the interface and
`JsonRows` is what ships: vectors as JSON in Postgres, cosine in process.
Brute force over a few thousand 512-dim vectors is single-digit milliseconds
with numpy and under a second without, and it beats a network round trip to
anything at this corpus size. **pgvector or a search cluster is a `Backend`
subclass when a measured number says so** — no extension, no cluster, and no
second copy of a truth whose approval state lives in Postgres regardless.

`numpy` is now in `requirements.txt` and is genuinely optional — `cosine`
falls back to pure Python, roughly 100× slower, which is fine at hundreds of
vectors and not inside a voice turn.

**To switch it on:** set `OPENAI_API_KEY` in the env group (the same variable
voice notes already need), then

```bash
curl -b ~/.gomeh-console -s ".../admin/embed_backfill?tenant=baci"            # rehearsal
curl -b ~/.gomeh-console -s ".../admin/embed_backfill?tenant=baci&report_only=0"
```

Approving a claim indexes it from then on, so the backfill is for the backlog
and for re-indexing after a model change — which invalidates every stored
vector, since cosine between two models is a number with no meaning.

**Adopt on evidence, not on novelty.** `kb.calibration()` now splits results
three ways and reports `semantic.agreed` beside `pattern.agreed`. Keep the
semantic path because that number moved, not because it is newer. Two defects
were already caught this way while building: `search` reported "nothing
embedded" when the real cause was a missing key (sending someone to run a
backfill that could not succeed), and `calibration` was about to sweep
semantic placements against word-overlap floors they never passed through.

**pgvector is no longer a blocker** — it was only ever needed for the storage
decision, and that decision is deferred behind the seam. Still worth knowing
for later: `CREATE EXTENSION IF NOT EXISTS vector;`

## Original step 03b prerequisites (now resolved)

pgvector behind the contracts steps 01–03 already fixed. `suggest_tags` keeps
returning `confident` / `score` / `basis`; this changes what computes them.
`resolve()` does not change, the receipt does not change, the refusal does not
change — which is the whole reason it is safe to adopt now and would not have
been safe to start with.

**Shape:** one polymorphic `kb_embeddings` table (tenant, kind, row_id, model,
text_hash, vector), so making a new type embeddable is zero schema change. A
semantic tier lands **between** pattern and word overlap: pattern stays the
decision, embeddings become the second authority, overlap stays as the floor.
`basis` names which path ran, and with no key or no extension it degrades to
overlap **and says so** — the `extractor: "deterministic filter"` lesson, where
a silent fallback at 0% recall looked exactly like a working one. Re-embedding
is gated on `text_hash` or every harvest re-pays for the corpus.

Also picks up semantic dedup at ingest (`near_duplicates` cannot currently see
that "ships in 2–3 days" and "usually dispatched within three business days"
are one claim) and retires the hand-rolled similarity in `similar_situation`
and `situation_neighbours`.

**Adopt only on evidence.** `kb.calibration()` already runs leave-one-out; run
it against both scorers on the same claims and keep the new one only if the
numbers move. That is what building the instrument first bought.

**Two answers needed before a thread starts:**

1. **Does Render's Postgres have pgvector?** `CREATE EXTENSION IF NOT EXISTS
   vector;`. If not, store vectors as JSON and cosine in Python — fine at
   hundreds of rows, wrong at a hundred thousand.
2. **Which embeddings provider?** Anthropic does not serve one. `OPENAI_API_KEY`
   is already on the owner track for voice notes, so one key could cover both;
   Voyage is the alternative.

**Not on the critical path.** Steps 04–11 all run without it. Step 06 is where
it stops being an improvement and becomes the mechanism — semantic search over
thousands of photo descriptions is not a SQL problem.

## Next thread starts here

**Step:** 04 — the ledger (or 03b, if the two answers above land first)
**Size:** medium

**Read, and only these:**

- `app/systems.py` — `SystemRun`, `start_run`, `finish_run`, `blocked_reasons`
- `app/db.py` — `_Provenance`, and `Touch` for how `run_id` is carried
- `app/resolve.py` — the bundle whose fields become the brief record

Do **not** search the repo broadly.

**Touches:** `app/db.py`, new `app/ledger.py`, new `scripts/test_ledger.py`

**Done when** three queries work against seeded rows:

1. "Has this claim been used for this entity in the last N outputs?" — the
   anti-repeat check.
2. "Which claims have never been selected?" — the hygiene signal. A claim
   unused across 200 outputs is wrong or redundant, and nothing can currently
   tell you which claims those are.
3. "What varied between these two outputs?" — the attribution query the
   e-commerce hypothesis loop needs.

One table serves all three. Record the brief that produced each output —
`claim_ids, audience_key, situation, entity_key, media_ids, theme, angle,
format` — plus destination, published_at and outcome.

**Verify:** `python3 scripts/test_ledger.py`

**Watch for:**

- `Approval.system_id` and `run_id` are still written by nothing. `Touch` now
  carries `run_id`; the ledger is the third place that needs the same link, so
  wire all three together here rather than a fourth time later.
- The ledger is also what makes step 07's validator able to check "topic not
  already covered", which is listed in the handoff as a validator requirement
  and has never had anything behind it.
- `ops_jobs.py` remains the one file in the execution half with zero tenant
  references.

## Defects filed

- **DEFECTS §2.24** — *One shared word asserted a situation tag* (fixed,
  step 01). Fourth instance of §1 *unknown collapsed into a value*.
- Noted in §2.24, **not fixed**: `email_harvest.py:314` and the equivalent in
  `harvest.py` ignore `add_claim`'s returned status, so a dedupe refusal
  disappears without a count. §1 *silent loss*, in live code.
- Steps 02 and 03 found no new defect. Nothing is filed for them rather than
  something being manufactured to fill the section.

## Owner track — runs alongside

1. **`READ_KEY` in the `assistant-env` group** — new, and it gates step 03.
   Any long random string. Until it is set, `/resolve` answers only the admin
   secret and the whole point of the split is unrealised. Set it on the
   **group**, not one service.
2. `CREDENTIAL_KEY` in the same group. Setting it later orphans every
   credential stored before it.
3. `ANTHROPIC_API_KEY`, or harvest silently runs a path measured at 0% recall.
   Check the `extractor` field, not the proposal count.
4. `GOOGLE_CLIENT_ID` / `_SECRET`, `META_APP_ID` / `_SECRET`, plus both
   redirect URIs registered byte for byte, then prove the Google flow on Baci.
   **Note:** a local `.env` in the *other* clone
   (`~/Documents/gomehagent/.env`) already defines `GOOGLE_CLIENT_ID` and
   `GOOGLE_CLIENT_SECRET` — worth checking whether those are the values the
   env group needs before minting new ones.
5. **Author objections on at least one account.** They are zero on all five.
   This is now the binding constraint on everything: `/resolve` will correctly
   block on "nothing on file to answer with" for every real request until it
   changes, and the classifier cannot be calibrated without tagged claims
   either.
