# INITIATIVE — Moments and orchestration

> **THIS IS A PLAN, NOT A STATE FILE.** Written 2026-08-23. Nothing in it has
> been built. `BUILD-STATE.md` remains the record of what exists.
>
> `HANDOFF-content-platform.md` is in this repo and is WRONG — it described
> state that moved underneath it. This file avoids that failure the only way a
> plan can: **§2 is a list of facts with file:line, and every one of them is
> checkable in about a minute.** If they still hold, the plan holds. If one has
> changed, the phase that rests on it needs re-reading before it is built.

Full build map, with the diagram and the phase detail:
<https://claude.ai/code/artifact/489c224e-a381-43b3-892f-3287e4f5bb81>

---

## 1. What this is for

Two goals, from the owner (2026-08-23):

1. **Moments.** Every email today is *scheduled* — `planner.campaign_rollout`
   picks a segment and a date. Competitors trigger on shopper events, which
   reads as better copy and mostly is better *timing*. We want triggered sends.
2. **Orchestration.** The drafter avoids repeating its own last four sends to
   one segment. It does not know what the other segments were told, whether the
   brand is telling one story, or whether anything worked.

**The constraint that shapes everything:** this serves e-commerce, a venue, a
B2B specifier and a digital-products account. A property rental has no carts;
it has enquiries that go quiet and dates that expire. So the abstraction is a
**moment** — a signal that a known person is in a window where a message is
welcome — and never "abandoned cart".

---

## 2. Verified facts this plan rests on

Each was read in the tree on 2026-08-23. **Re-check these first.**

### 2.1 The moment catalogue is already half-written
`app/segments.py` — `CATALOG` is keyed by `Tenant.business_model` and every
entry carries `source: 'esp' | 'commerce' | 'lifecycle'` (the capability axis)
and `tier: 'high_value' | 'common'`. `planner.campaign_rollout` iterates
**`got["high_value"]` only** — the `common` tier (`cart_abandoners`,
`hot_enquiries`, `win_back`…) is never proposed for. Those entries are the
moments, waiting for a trigger.

`segments.for_tenant()` is also the refusal pattern to copy verbatim: it
refuses by name when `business_model` is unset and names the control that sets
it.

### 2.2 The strategy substrate is written on every send and has one reader
`ledger.record()` writes `theme` (`"{intent}|{format}"`), `angle` (the segment
key) and `shape` (the block sequence) for every campaign email. A grep across
`app/` finds **exactly one reader**: `skill_pack._recent_sends()`, which takes
4 rows for one segment and renders them into the drafter's prompt. Nothing
aggregates them; nothing shows them to the owner.

`theme`, `angle`, `format` and `shape` are all **unindexed** on `db.Output`.

### 2.3 The ledger cannot answer "which product went to which segment"
`skill_pack._run_campaign_email` calls `ctx.emit(...)` **without**
`entity_key=` or `audience_key=`, so both columns are empty on every
campaign_email row. `_run_ad_copy` **does** pass them. One-line fix, and it
gates the whole of Phase 2.

Also empty for email, with consequences: `situation` (metrics count nothing),
`objection_id` (same), `lookups` (so `ledger.perishable()` skips every email),
`media_ids` (no writer anywhere).

### 2.4 Nothing records that an email shipped
`ledger.publish()` — the only writer of `status="published"` / `published_at` —
is called from exactly one place, `responder.py` (the reply path). No campaign
row ever becomes `published`, so `ledger.used_recently()` / `is_repeat()` are
**blind to every email ever sent**. `destination` is written at `emit` time
(`esp:omnisend`) roughly ninety lines before the ESP call that may fail, so it
records intent, not outcome.

### 2.5 There is no commerce event path
One Shopify webhook route exists: `POST /webhooks/shopify/compliance`, serving
`customers/data_request`, `customers/redact`, `shop/redact`. The HMAC
`verify()` in `app/shopify_webhooks.py` is constant-time, over the raw body,
and **reusable as-is** for a commerce route.

Event-driven paths that do exist: WhatsApp inbound, Telegram, the mail poller.
All human/compliance channels. None commerce.

### 2.6 Other things worth knowing before touching the planner
- `PLANNERS = {"campaign_email": campaign_rollout}` — one entry. The registry
  already supports a second; nothing needs redesigning to add one.
- `planner` reads the ledger **not at all**. It knows only how many plans are
  open per segment per month (`_existing_by_month`).
- A comment in `systems.py` says the planner rotates intent. **It does not** —
  `skill_pack._campaign_craft` does, at draft time, from those 4 rows.
- `worker.systems_tick` is the only path that turns a planned run into a
  `skill.run`. `LEAD_DAYS = 2`, so nothing proposed in a tick is consumable in
  the same tick.
- Repaired attempt rows are written with `theme=""` and `shape=[]` but keep
  `angle` and `format`, and `_recent_sends` excludes only
  `("blocked", "superseded")` — so they enter the 4-row window and dilute it.

---

## 3. Order of work, and why

**Phase 2.1 first, before any moments work.** It is a handful of one-line
fixes and it is the cheapest thing here — and every later phase reads the rows
it corrects. Building moments on a ledger that cannot say which product went to
which segment means rebuilding the analysis afterwards.

| # | Work | Rests on |
|---|------|----------|
| 2.1 | Complete the per-send writes + indexes | §2.3, §2.4, §2.6 |
| 1.1 | `db.Moment` table | — |
| 1.2 | `moments.CATALOG` per business_model, per capability | §2.1 |
| 1.3 | Two producers: Shopify commerce webhook + inbox-quiet | §2.5 |
| 1.4 | A second planner that consumes due moments | §2.6 |
| 2.2 | `strategy.py` — the reader | 2.1 |
| 2.3 | Planner proposes against strategy state | 2.2 |
| 2.4 | ESP performance back into the ledger | 2.1 |

### What proves each phase

- **2.1** — a query answers, for one segment over 90 days: which intents, which
  products, which claims, which angles, at what spacing.
- **1.3** — a venue enquiry going quiet and a cart going cold both create a
  `Moment`, and **neither producer knows what the other is for**. Build with
  `ecom_inventory` AND `local_venue` from day one; with one vertical the
  vertical bakes into the generic layer and nobody finds out for a year.
- **1.4** — a moment produces a draft through the unchanged `campaign_email`
  path: same coherence contract, same claims, same validator.
- **2.3** — the planner's choice of segment changes when the ledger changes.

---

## 4. Conventions this repo enforces

Non-obvious, and each one cost time to learn.

- **`./scripts/test_all.sh`** runs all suites in parallel, ~90s (serial is 5m+).
  Takes a substring filter: `./scripts/test_all.sh campaign`.
- **Every guard gets a `sabotage.py` entry.** A test that passes proves
  nothing; a test that FAILS when the guard is removed proves something. Run
  `python3 scripts/sabotage.py <name>` after adding one. **`MISSED` means the
  test is decoration. `STALE` means the find-string is not unique** — both
  happened this week and both were real gaps.
- **`Context.emit()` is the one exit.** Banned-claims validation, the coherence
  contract, the repair loop and the ledger write all hang off it. A new
  generator gets all of it by calling `emit`, and none of it by not.
- **Refuse by name.** A refusal states what is missing and where the control
  is. `segments.for_tenant()` is the model.
- **Soft removal.** `review="rejected"` is removal — every read accessor
  filters on it. `kb.remove()` / `kb.restore()` are the door. Hard delete is
  reserved for bulk machine-origin purges.

### False passes to avoid — all three hit this week
- Console tabs are addressed by **key, not label**: `content`=Review,
  `kb`=Knowledge, `schema`=Data layer. `?tab=review` silently renders the
  default tab and every assertion passes against the wrong page.
- The admin key is **`APPROVAL_SECRET`**, not `ADMIN_KEY`. With the wrong one
  the console returns the public landing page — HTTP 200, and every
  "no duplicate ids" assertion trivially true.
- **Assert against a fixture that has the thing in it.** A check for absence
  run against an empty table passes for the wrong reason.

---

## 5. Open decisions

1. **Suppression and expiry are load-bearing, not polish.** A moment is a
   message to a named person about a specific thing — a different consent and
   frequency question from a segment campaign. Decide the per-person cap and
   the per-moment dedup before 1.4, not after.
2. **Which `local_venue` moment ships first.** "Enquiry gone quiet" needs only
   `Conversation.last_touch_at`, which is already maintained — it is the
   cheapest second producer and it is the one that proves the abstraction.
3. **`published_scope` is read nowhere** (noted in DEFECTS §2.85), so a product
   published to POS only still reads as available. Adjacent, not blocking.

---

## 6. Related records

- `DEFECTS.md` §2.77 (coherence), §2.83 (the angle is not the subject),
  §2.85–2.86 (draft products, KB removal), §2.87 (positioning is scoped).
- `BUILD-STATE.md` — the coherence contract, the console walkthrough, and the
  positioning work all landed 2026-08-22/23 and are what this builds on.
