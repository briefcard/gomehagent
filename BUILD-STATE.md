# Build state — 2026-08-14

The rolling state of the data-layer build. **This file is rewritten by every
thread.** It is always current and never historical — do not add dated sections,
and do not create `HANDOFF-step-N.md` files. History lives in `DEFECTS.md`
(append-only) and in the git log.

`HANDOFF-content-platform.md` is the **historical** record up to 2026-08-13 and
is no longer maintained. Parts of it are actively wrong now — it describes the
execution half as tenant-blind, which stopped being true before this session
started. Read it for background, never for state.

**Live:** `93faab8` on `origin/main`, deployed, 92 routes.
`/health` reports `commit` and `routes` — use it, do not infer what is running.

---

## What this layer is now

Three stores with different lifecycles, and everything else is a consumer.

| | holds | key modules |
|---|---|---|
| **Knowledge** | brand, rules, claims, objections, entities, situations | `kb`, `provenance`, `embed` |
| **State** | conversations, touches, commitments | `conversation` |
| **Archive** | email bodies, attachment text, all searchable by meaning | `archive` |
| **Ledger** | what was produced, from which brief | `ledger` |

`resolve()` is the one call every consumer makes. `validator` is the one gate
every output passes. `dossier` compiles the whole knowledge base into a
cacheable brand document.

## The five rules this codebase keeps re-learning

Every one of these was a real defect, several of them twice. Read them before
changing anything.

1. **Absence is a third state and must survive to the output.** Met five times
   now: `fits: True` from a keyword match, one-word overlap asserting a tag,
   coverage collapsed across kinds, `unreadable` holding three meanings,
   `wrote:0 skipped:N` hiding whether rows were done or empty. If you are about
   to return a bare `False` or an empty list, name the reason instead.
2. **Enrich, do not gatekeep.** Refusing to *invent* belongs in `validator`, on
   output, in code that fails closed. Refusing to hand over *context* just lets
   a missing row veto a reader that had plenty to work with. `blocked_on` is
   reserved for one case: no ban list, so nothing can check the output.
3. **Approved is final, whatever wrote it first.** `approve()` does not change
   `origin`, so origin cannot be the guard — an agent-authored row a human
   approved was overwritable by that agent for ever until this session.
4. **Derive lists from the schema, never by hand.** `reset.py` caught its own
   `kb_brands` / `kb_brand` typo this way; a hand-kept list misses the model
   somebody adds next month, silently.
5. **Run it before claiming it works.** Every finding below came from running
   against real Baci data, not from reading. Several were in code with passing
   tests around it.

## Built and deployed this session

Steps 01–04, 07, 09 of the Build Map, plus a lot that was not on it.

**Retrieval** — `resolve()` with tiered bundles, a coverage receipt, and
`grounding.level` (answered / unranked / supported / rules_only). Semantic
recall via `embed` (OpenAI `text-embedding-3-small`, 512 dims), stored as JSON
in Postgres and scanned in process. `embed.Backend` is the seam; pgvector or a
cluster is a subclass when `/embed_status` says `swap_backend_yet: true`
(ceiling 20,000 vectors; Baci is at ~115 and scans in 3.6ms).

**Conversation state** — `Conversation` / `Touch` / `Commitment` on top of
`Contact`. Two email chains with one person fold onto one row. An outbound
touch without an idempotency key is refused.

**The archive** — this is the big one, and it fixed the thing that made inbox
drafts untrustworthy. `EmailLog.body_excerpt` and `DocIndex.text_excerpt` now
hold what was *said*, not just that something arrived; `DocIndex.thread_id`
joins a document to the conversation it came on; attachments ride along when a
thread is retrieved.

**Output** — `ledger` (anti-repeat, attribution, hygiene in one table),
`validator` (pure code, fails closed, no model call in the file),
`responder` (resolve → assemble → validate → ledger, and now `_draft` with the
model behind the same gate).

**Knowledge growth** — `propose` lets an agent file a claim/objection/situation
instead of asking; nothing lands usable (`origin="agent"` is not
`AUTO_APPROVED`). `voice` proposes a tone from the site with verbatim evidence.
`kb.calibration()` measures the classifier by leave-one-out.
`kb.label_conflicts()` finds near-identical claims tagged differently.

**Operations** — `dossier` (`/brand.md`), `reset` (scoped, dry-run),
`/readiness`, `/admin/threads`, `/admin/draft_test`.

**32 offline suites, all green, none touching the network.** Full run is
~2m30s — split it or a single shell call hits a 2-minute timeout.
`test_sources` 52s, `test_harvest` 16s, `test_selection` 15s.

## Verified against real Baci data

Not claims — these were run and the output read.

- **Archive:** 104 threads, 56 declined as noise (promo 27, notifications 23,
  automated 5, subscriptions 1 — **54%**), 43 bodies stored, 47 vectors.
- **Attachments:** 96 found across 43 threads, of which **79 were sender logos
  and tracking pixels**. 12 real documents stored, 42 chunks indexed.
- **Retrieval works:** `"problem with a damaged shipment"` returns a customs
  clearance thread sharing no words with the query. `"customs clearance invoice"`
  returns `rev Final_INVOICE_1256_BACI_MILANO_USA_LLC.pdf` — a PDF found by
  what it says.
- **Calibration:** patterns 8/8, semantic 8/11. All three misses are the same
  defect — near-identical claims tagged differently, worst at **0.9672**, which
  is higher than most correct placements. **No threshold fixes that**; the fix
  is upstream, in the labels.
- **Voice:** 876 sentences measured. Measured descriptors say formal / brisk /
  understated / plain; the model says playful / stylish / whimsical. Both are
  right — restrained construction, exuberant vocabulary. **23 sentences on the
  live site break Baci's own ban list.**

## Open, and honest about it

**Never measured:** `scripts/ab_context.py` compares this layer against the
compiled brand document, scored by the validator. It has never been run. The
central claim — that this beats a `.md` file — is therefore unproven, and my
prediction is that **at Baci's corpus size the document arm ties or wins**.
That would validate the architecture rather than undermine it, which is why
`dossier` compiles the document rather than competing with it.

**Blocked on content, not code:**
- Objections: 7 in review, 1 approved. This is the binding constraint on
  everything — `/resolve` correctly blocks on "nothing on file to answer with".
- `brand.voice.tone` still unset. `/admin/propose_voice` will hand you the words.
- 13 claim fingerprints unrepaired (`/admin/repair_fingerprints?apply=1`).
- One duplicate claim pair unresolved — retiring one drops its vector and
  should move `semantic.agreed` from 8/11 to 9/11 with no code change.

**Known gaps:**
- **2 scanned PDFs need OCR.** Not built. Counted under `scanned, needs OCR`.
- **`archive_fetch` has reached everything `EmailLog` knows.** Going further
  back means logging mail Gmail has and `EmailLog` does not — the cheap route
  is reading the Gmail label `bucket_backfill` already applied, rather than
  re-classifying at a model call each.
- `READ_KEY` unset, so `/resolve` and `/brand.md` answer only the admin secret.
- `MIN_SEMANTIC_SCORE = 0.45` is unturned against real mail. Live hits score
  0.48–0.56 — barely above the floor on a thin corpus.
- `ops_jobs.py` is the last file in the execution half with zero tenant refs.
- `email_harvest.py:314` and `harvest.py` ignore `add_claim`'s return (§1
  silent loss, live).

## Next thread starts here

**Read, and only these:** this file, then `DEFECTS.md` §1 (the patterns), then
the files named by whichever task you pick. Do not search the repo broadly — a
cold thread that greps its way around this codebase burns a third of its budget
before writing a line.

Highest value first:

1. **Run the A/B.** It is the only unmeasured claim in the whole system, and it
   is one command. `ANTHROPIC_API_KEY=… DATABASE_URL=… python3 scripts/ab_context.py baci`
2. **Approve the 7 objections and set a voice tone.** Console work, no code, and
   it changes more about what the system can do than the last ten commits.
3. **Step 05/06 of the Build Map** — visual identity + themes, then the media
   layer. Both blocked on nothing.
4. **OCR** for the scanned PDFs, if the logistics inbox turns out to need it.

**Verify:** run the suites in two batches. `test_tenant_isolation.py` must pass
**unmodified** — it is the mandatory rule as a test.

**Standing preamble for a new thread:** worktree
`/Users/gomehsaias/Documents/gomehagent-build`, branch
`feat/context-architecture`. The other clone
(`~/Documents/gomehagent`) is on `feat/warehouse-picklist`, a pre-kernel base —
**never push from there.** Render auto-deploys `main`; git needs the sandbox
off; always fetch and verify a fast-forward before pushing. Deploys usually
land in 60–90s but have taken 6+ minutes — check `/health` for the commit
rather than theorising about failed builds.
