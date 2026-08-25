# INITIATIVE — Moments and orchestration

> **THIS IS A PLAN, NOT A STATE FILE.** Written 2026-08-23. `BUILD-STATE.md`
> remains the record of what exists.
>
> **COMPLETE (2026-08-24), uncommitted and deployed nowhere.** All eight
> phases are built; `BUILD-STATE.md` has three dated sections covering them. 1.4 landed differently from how it is
> written below — moments INFORM `campaign_rollout` rather than running a
> second planner, because there is no per-contact sending surface for a
> per-person plan to use. See BUILD-STATE's correction section. The built phases changed several of the
> facts below, so those are marked CLOSED in place rather than left to read as
> still-true — a plan whose facts have quietly gone false is the exact failure
> this file was written to avoid. `BUILD-STATE.md` has what was actually done.
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

### 2.3 ~~The ledger cannot answer "which product went to which segment"~~
**CLOSED by 2.1 (2026-08-24).** `_run_campaign_email` now passes `entity_key`,
`audience_key`, `situation` and `media_ids`; `Context.emit` gained `media_ids`,
which had no writer anywhere. `lookups` is written only when the catalogue sync
actually runs — entities normally come from the synced table, a stored fact of
unknown age rather than a reading, so `ledger.perishable()` still skips those
rows and is right to. `objection_id` stays empty: nothing in the campaign path
answers an objection, and inventing one would be worse than the gap.

The read that proves it is `ledger.sends_to()`.

### 2.4 Nothing records that an email shipped
**HALF CLOSED by 2.1 (2026-08-24).** `destination` is now an outcome:
`ledger.delivered()` rewrites it after the ESP call to
`esp:{provider}:campaign/<id>`, `:not-drafted` or `:withheld`.

Still true, and deliberately so: no campaign row becomes `published`, so
`used_recently()` / `is_repeat()` remain blind to sent email. This system
creates a DRAFT and the owner launches it in the platform — `apply_decision`
goes out of its way to say approving one is not sending it. The truth about
what shipped has to come back FROM the ESP, which is Phase 2.4, not something
2.1 could honestly assert.

### 2.5 There is no commerce event path
One Shopify webhook route exists: `POST /webhooks/shopify/compliance`, serving
`customers/data_request`, `customers/redact`, `shop/redact`. The HMAC
`verify()` in `app/shopify_webhooks.py` is constant-time, over the raw body,
and **reusable as-is** for a commerce route.

Event-driven paths that do exist: WhatsApp inbound, Telegram, the mail poller.
All human/compliance channels. None commerce.

### 2.6 Other things worth knowing before touching the planner
- ~~`PLANNERS` — one entry. The registry already supports a second; nothing
  needs redesigning to add one.~~ **HALF WRONG, and it cost a debugging pass.**
  True of `PLANNERS`. False of the CONSUMPTION path: `skill.run` resolved the
  system from the SKILL's declaration, so a `moment_email` plan asked whether
  `campaign_email` was installed and was then refused by `take_plan` as
  belonging to a different system. Fixed by `systems.system_for_plan()`, which
  resolves the system from the plan and fails closed. Two entries now.
- `planner` reads the ledger **not at all**. It knows only how many plans are
  open per segment per month (`_existing_by_month`).
- A comment in `systems.py` says the planner rotates intent. **It does not** —
  `skill_pack._campaign_craft` does, at draft time, from those 4 rows.
- `worker.systems_tick` is the only path that turns a planned run into a
  `skill.run`. `LEAD_DAYS = 2`, so nothing proposed in a tick is consumable in
  the same tick.
- ~~Repaired attempt rows dilute the 4-row window.~~ **CLOSED by 2.1** — one
  shared constant, `ledger.NOT_A_SEND`, which includes `repaired`.

---

## 3. Order of work, and why

**Phase 2.1 first, before any moments work.** It is a handful of one-line
fixes and it is the cheapest thing here — and every later phase reads the rows
it corrects. Building moments on a ledger that cannot say which product went to
which segment means rebuilding the analysis afterwards.

| # | Work | Rests on |
|---|------|----------|
| ~~2.1~~ | ~~Complete the per-send writes + indexes~~ **DONE 2026-08-24** | §2.3, §2.4, §2.6 |
| ~~1.1~~ | ~~`db.Moment` table~~ **DONE 2026-08-24** | — |
| ~~1.2~~ | ~~`moments.CATALOG`~~ **DONE 2026-08-24** | §2.1 |
| ~~1.3~~ | ~~Two producers: commerce webhook + inbox-quiet~~ **DONE** | §2.5 |
| ~~1.4~~ | ~~A second planner~~ → **moments INFORM `campaign_rollout`** (2026-08-24; a second planner would have sent one whole-segment campaign per person) | §2.6 |
| ~~2.2~~ | ~~`strategy.py` — the reader~~ **DONE** + `/admin/strategy` | 2.1 |
| ~~2.3~~ | ~~Planner proposes against strategy state~~ **DONE** — ordered by neglect | 2.2 |
| ~~2.4~~ | ~~ESP performance back into the ledger~~ **DONE** — `performance.sync` | 2.1 |

### What proves each phase

- **2.1** — ✅ `ledger.sends_to(tenant, audience_key, days=90)` answers exactly
  that. Pinned by `scripts/test_strategy_ledger.py`; four of its guards fail on
  removal (`python3 scripts/sabotage.py`).
- **1.3** — ✅ both create a `Moment`, and the suite asserts the mutual
  ignorance against the SOURCE: no cart vocabulary in the inbox producer, no
  conversation vocabulary in the commerce one, no function in the spine
  mentioning either. Built with `ecom_inventory` AND `local_venue` from the
  first line, plus `b2b_spec` and `digital_products`.
- **1.4** — ✅ but NOT as written. "A moment produces a draft" was the wrong
  proof, because every draft this system makes is bound to a whole segment.
  What is proven instead, in `test_moment_pressure.py`: enough people in one
  window promotes a common-tier cohort the calendar never proposes for; under
  the floor nothing is proposed and the moments stay open for a person; and a
  cohort that already has a plan gets the evidence ATTACHED rather than a
  second campaign.
- **2.3** — ✅ the planner's choice of segment changes when the ledger
  changes. `test_strategy.py` writes history, reads the order, writes one more
  send and checks the order moved.

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

1. ~~Suppression and expiry.~~ **DECIDED, then REVISED once the sending
   surface was read properly.** The owner set two-per-person-per-seven-days on
   2026-08-24. It is not enforceable: every send goes to a segment whose
   membership Omnisend knows and we do not, so a per-person number is a claim
   rather than a rule. What replaced it, and what the code now does:
   `MIN_PRESSURE` (a cohort needs five people in a window before a campaign is
   an honest response), `segment_rest_days` (how long a cohort rests), and the
   existing monthly cap, which pressure may never exceed. Per-moment dedup is
   still structural — `(tenant, dedup_key)` is unique.
2. ~~Which `local_venue` moment ships first.~~ **"Enquiry gone quiet", as
   suggested** — `Conversation.last_touch_at` was already maintained, and it
   shares no concept whatsoever with a cart, which is what made it the proof.
3. **`published_scope` is read nowhere** (noted in DEFECTS §2.85), so a product
   published to POS only still reads as available. Adjacent, not blocking.

---

## 6. Related records

- `DEFECTS.md` §2.77 (coherence), §2.83 (the angle is not the subject),
  §2.85–2.86 (draft products, KB removal), §2.87 (positioning is scoped).
- `BUILD-STATE.md` — the coherence contract, the console walkthrough, and the
  positioning work all landed 2026-08-22/23 and are what this builds on.
