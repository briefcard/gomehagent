# Baci Milano — the plan to a profitable $1M year, task by task

Companion to `HANDOFF-baci-meta-ads-2026-11-02.md` (read that first — it holds
the IDs, the account state and the owner's rules). Numbers below come from
`unit_economics_model.py`, Shopify and Meta as read on 2026-11-02. Anything
marked **ASSUMPTION** or **UNVERIFIED** must be confirmed before it is relied on.

---

## A. Where we are vs where $1M is

| | Now (Oct 2026, best recent month) | $1M run-rate target |
|---|---|---|
| Revenue / month | DTC ≈ **$19.5K** (Online Store $19.3K + Shop/FB-IG), B2B ≈ $0 | **$83K** (DTC $58K + B2B $25K at a 70/30 mix) |
| Ad spend / month | **$11.0K** | ≈ **$25–27K** |
| MER (DTC revenue ÷ ad spend) | **1.77** (ads = 56.5% of DTC revenue) | **≥ 2.2** (ads ≤ 45% of DTC) |
| Monthly profit (model) | **–$9.4K** (contribution $1.3K – overhead $10.7K) | ≥ **+$8.3K** ($100K/yr) |
| 2026 YTD revenue (Jan–Oct) | **$106K** total, all channels | — |

**What the model says (run it: `python3 -I unit_economics_model.py` via the
`pnl()` function):**
- Contribution before ads: **DTC 63.1¢ per $1** (65.6¢ in a full container);
  **B2B 37.1¢** (41.7¢ full container). Duty 22.4% measured; freight 26% small
  lots / 14% full container.
- At $1M with overhead of **$128K/yr** (employee $48K, warehouse incl. staff
  $30K, tradeshow $50K):

| B2B share | Freight | Max ads ÷ DTC to break even | Max for $100K profit | MER needed for $100K |
|---|---|---|---|---|
| 20% | 26% | 56% | 44% | 2.28 |
| 30% | 26% | 61% | 46% | **2.16** |
| 30% | 14% | 65% | 51% | 1.97 |
| 40% | 26% | 66% | 50% | 2.01 |

**The honest read:**
1. The business loses money today mainly because of **scale, not just ad
   efficiency**: $10.7K/month of fixed cost against ~$20K of revenue. At $1M
   the same overhead is 13% of revenue.
2. Ad efficiency still has to improve: from MER 1.77 to ≥ 2.2 **while spend
   grows ~2.5×** — and history says CPA rises as spend rises (Apr $56 → Jul
   $112 on one ad). That only works with creative volume and diversity (§D).
3. **B2B is the profit stabiliser**: no ad cost. Every $1 of B2B at 30%+ of
   the mix buys ~5 points of ad headroom.
4. **ASSUMPTION — overhead is understated.** The $128K excludes Shopify plan
   + apps, Meta/Canva/other software, accounting, insurance, packaging, card
   fees beyond the model's 3%, and warehouse growth: $1M is ~7,000 DTC orders
   a year (~580/month vs 186 in Oct) — the $2,500/month warehouse incl. staff
   will not pick and pack 3× the volume. **Task 0.4 collects the real list.**
5. **Cup economics are stricter than the blended model:** at FirstBaci 15%, a
   1-cup order keeps ~$39 before ads, a 2-cup order ~$69. With the $40 cost cap
   a 1-cup buyer roughly breaks even. **AOV is the biggest single lever** —
   moving from $101 to $125 lifts MER ~24% at the same CPA.

**The scoreboard every task serves (weekly):** DTC revenue · ad spend · MER ·
blended CPA · AOV · cups per order · % orders 2+ cups · B2B booked · stock by
sign · slot-code sales.

---

## B. Phases and tasks

Each task: **Goal · How · Tools/data · Owner check · Done when.**
Meta stays **read-only** until Phase 7 is approved.

### Phase 0 — Environment, data and the real cost base (Day 1)

**0.1 Unlock network.** Goal: read Sam Piliero's material. How: owner adds
`docs.google.com`, `app.kit.com`, `miro.com` to allowed domains. Done when the
campaign-structure doc (`1W5NqZVHhXUx8CxcpGJNMpZyBf4kztNFbaQWPgBm9uh0`) and
the Miro flowchart open. Fallback: owner exports PDFs to Drive.

**0.2 Fix the data-layer key.** Owner renames env var `MCP_Key` → `MCP_KEY`
so the gomehagent MCP (inbox, plan, results) works in sessions.

**0.3 Verify tracking before spending more.** How (read-only): dataset
`1050425080184653` — Purchase EMQ, dedup, value passed; compare Meta-reported
purchases vs Shopify orders for Oct (Meta 146 purchases vs Shopify DTC ~190
orders). Done when we know the over/under-attribution ratio to apply to every
CPA in this plan.

**0.4 Collect the true overhead.** Ask the owner for monthly: Shopify +
apps, software, accountant, insurance, packaging per order, real label cost on
free-ship orders, warehouse cost at 2× and 3× volume. Re-run the model with
them. Done when §A's table is re-computed with real overhead — **the MER
target in this plan moves with it.**

### Phase 1 — Read Piliero and audit the account against him (Days 1–2)

**1.1 Read the guide, the M4 22-page guide (reply-to-confirm email
`1a05ca064d3d2831` — owner may need to reply) and the flowchart.** Extract
every rule into a checklist: campaigns, CBO/ABO, packs per campaign, ads per
pack, concept vs iteration, launch cadence, kill/graduate thresholds, budget
moves, bidding, audience settings (A+ audience, exclusions), placements,
creative volume per week.

**1.2 Rule-by-rule audit** of the live account and of the Mar–Aug Prospecting
CBO (`120245650447380184`): followed / broken / not applicable, with the data.
Known so far: 99.4% of $30K went to one pack; one ad took 68%; Wave 2 never
ran; that pack used A+ audience ON and produced the most purchases.

**Owner check:** approve the audit before any structure is drawn.

### Phase 2 — Offer and AOV (Days 2–4) — the lever that funds everything

**2.1 Decide the discount.** Options: keep FirstBaci 15% everywhere (simple,
already trusted, 227 uses) or move ads to FIRST10 (+~$6.50 kept per 2-cup
order). Model both against conversion risk; recommend one.

**2.2 Design the 2-cup offer.** "Two signs, free shipping" already exists in
effect (2 × $65 ≥ $110). Make it explicit in every ad and on product pages:
"one for them, one for you", "two December birthdays", "host gift + yours".
Optional bundle SKU (website task, Phase 11). Done when the offer line is fixed
and every concept in Phase 4 carries it.

**2.3 Set the AOV target**: ≥ $120 within 6 weeks of launch; % of orders with
2+ cups tracked weekly from Shopify.

**2.4 Slot codes.** Assign `FirstBaci1`–`FirstBaci8` (all 15%, 0 uses) one per
concept so Shopify attributes sales independently of Meta. Rename nothing
live without OK.

### Phase 3 — Account map to Piliero's structure (Days 3–5)

**3.1 Draw the target structure** from the Phase 1 checklist, constrained by:
- Keep **4X Engine** (`120253812101140184`) as the scale campaign, **$40 cost
  cap**, and its winners (`120254225341840184`, `120254225348480184`).
- Keep **Retargeting** (`120254102812370184`) at $50/day, warm audiences only
  (expansion off) with the "Their sign" reel (`120254102816450184`).
- Winners (`120253812100950184`) stays off.
- Testing = Piliero packs: one concept per pack, the whole pack built before
  launch, packs launched together.

**3.2 Decide audience settings with data**: A+ audience ON (what the best
historical ad set used) vs OFF (current). Age 30–64 vs his guidance; F45–54
best CPA ($68), F65+ worst ($308).

**3.3 Placements**: IG Reels best ($80), FB Reels worst ($164). Decide
Advantage+ placements with placement-customised creative vs a manual list.

**3.4 Operating rules written into the map**: changes on Mondays only;
budget ±20% per 72h max; pause ads, never switch campaigns off; graduation
rule; kill rule; stock rule (pause any ad pointing at a sign < 10 cups);
fatigue rule (two weeks above $60 CPA → rotate).

**3.5 Spend ladder to $1M pace** (each step needs MER ≥ 2.2 for 2
consecutive weeks on Shopify-confirmed revenue, and stock to cover 6 weeks):

| Step | Total daily spend | Monthly | Expected DTC at MER 2.2 |
|---|---|---|---|
| 1 (launch) | ~$400 | $12K | $26K |
| 2 | ~$550 | $16.5K | $36K |
| 3 | ~$700 | $21K | $46K |
| 4 ($1M pace) | ~$850 | $25.7K | $57K |

Drop back one step if MER < 1.9 for a week.

**Owner check:** approve the map.

### Phase 4 — Concept bank (Days 4–7)

**4.1 Inputs:** stock by sign (lead Sagittarius 161, Capricorn 175; then
Aquarius 50, Aries 45), season (Sagittarius Nov 22–Dec 21, Capricorn Dec 22–
Jan 19, holiday gifting), the 2-cup offer, proven winners' hooks ("Most
Personal", "Their sign = your next gift idea", "Dinner Party Argument" V3,
Giselle Bassi "I found the one" partnership — 2.21 ROAS last holiday).

**4.2 Five genuinely different entries** (`app/ad_craft.py` ANGLES): identity
("which sign are they"), gifting (buyer's fear of a generic gift), occasion
(the specific dinner/morning scene), objection (fragile? will it arrive in
time? price), offer (two signs, free shipping). 2–3 ads per concept = one
pack.

**4.3 Run the Hormozi/Piliero panel on the concepts** (the repo's
`PANEL_SYSTEM`): ≥ 2 value levers each, lead lever named, hook in the first 5
words (concrete noun / number / the reader), offer inside the first 125
characters, headline ≤ 40 characters, no vague adjectives (`VAGUE` list), no
two concepts Meta would fold into one entity.

**4.4 Guardrails check:** "designed in Milan / Italian-designed", never "made
in Italy"; nothing on the ban list; no claim without evidence; no sign that is
out of stock.

**Owner check:** approve concepts and copy.

### Phase 5 — Production spec and assets (Days 6–9)

**5.1 Spec per ad:** 9:16 (1080×1920, Reels/Stories — keep text inside the
safe zone, no text in the top ~14% / bottom ~20%), 4:5 (1080×1350, Feed);
carousel 1:1 or 4:5 cards only where a carousel is the format. Video first
(every winner is vertical video); first 2 seconds = the hook; captions
burned-in or on-screen text; product fills the frame.

**5.2 Asset inventory:** Drive (Zodiac reels, Morning Ritual, partner
shoots), Shopify product media (square, 1080 — feed/carousel only), existing
IG posts (use as "existing post" to keep social proof), Canva catalog designs
(`DAHWsvWkwec`). List what is missing per concept and ask the owner for
footage/shoot.

**5.3 Shot list / script** for anything missing (reel scripts in the style of
"Their sign").

### Phase 6 — Stage the whole series in Canva (Days 8–12)

**6.1** One Canva folder per launch, brand kit `kAGIWwLuTfs`, every concept in
every size. Naming: `PACK-<concept>-<sign>-<9x16|4x5>-v<n>`.

**6.2** Read-back checklist per design: size, safe zones, hook legible on a
phone, offer line exact, code exact, sign in stock, brand guardrail.

**6.3** Owner reviews in Canva (comments), iterate.

**Owner check:** approve the series. **This is the gate that lifts the Meta
write freeze.**

### Phase 7 — Upload and launch (after explicit OK)

**7.1** Before anything: discard the two rejected square-photo draft ads
(`120254485395230184`, `120254485396790184`); resolve the `frequently_in`
question; never "Publish all" (stale Jul–Oct drafts with 5 errors exist).

**7.2** Upload media; build each ad with placement-customised creative (9:16
+ 4:5); headline in `link_data.name`, only `link` in the CTA value (no
`link_title`); A+ creative enhancements per the map.

**7.3** Read back every object field by field; report what was checked vs
what Meta validated.

**7.4** Launch each pack complete, all ads at once; publish the 4X Engine and
Retargeting drafts per campaign.

### Phase 8 — Operating rhythm (weekly, from launch)

**8.1 Monday review** (read-only report first, then the approved changes):
scoreboard (§A), per-pack and per-ad CPA (Meta) vs slot-code sales (Shopify),
fatigue (CPM and CPA trend per winner), stock by sign.

**8.2 Graduate / kill / rotate** per the Phase 3 rules; graduates enter 4X
Engine on Mondays only.

**8.3 New pack every week** (or per Piliero's cadence from Phase 1) so the
account never runs on one ad again.

**8.4 Spend ladder** step decisions (§3.5).

### Phase 9 — Revenue that costs no ads

**9.1 Email (Omnisend)** — holiday sends (Nov 28 send is an open item; the
90-day engaged filter too), post-purchase "add the second sign", winback.
Target: email ≥ 15% of DTC revenue (ASSUMPTION — set from Omnisend history).

**9.2 B2B to ~$25K/month** — order windows with 40% deposits sold from Baci
Milano's stock lists, core stock for repeat stockists, no air special orders
(air freight = 149%); active threads (Silvia, Chanel exclusivity), tradeshow
leads. B2B at keystone keeps 37¢ per $1 with no ad cost.

**9.3 Organic / partnership** — Giselle Bassi and similar partner posts fed
into ads as partnership ads.

### Phase 10 — Inventory to support $1M

**10.1** $1M ≈ 7,000 DTC orders/yr; at 1.3+ cups/order ≈ 9,000+ cups plus
B2B. Container 981 (7,288 cups, mid/late Dec) — ask whether its sign mix can
still change (752 of each slowest sign vs 504 of each best seller).

**10.2** Reorder triggers by sign from weekly velocity (stockout < 8 weeks out
= reorder in the next full container; full containers only — freight 14% vs
26%).

**10.3** Holiday decision: January pre-order for Scorpio/Libra/Taurus/Virgo
(owner's call).

### Phase 11 — Website (after ads, owner's order)

Sold-out sign handling (no dead ends from ads), pre-order if approved,
2-cup offer visible on product pages, landing pages that match each concept's
hook, free-shipping threshold message at $110.

### Phase 12 — Monthly P&L check

Re-run the model on actuals (revenue by channel, ad spend, real overhead);
compare to the §A targets; adjust the ladder and the B2B target.

---

## C. Open owner questions (blocking where marked)

1. **Blocking:** allow docs.google.com / app.kit.com / miro.com (Phase 0/1).
2. **Blocking for the target:** the real overhead list (Task 0.4).
3. Real label cost on free-shipping orders.
4. FirstBaci 15% vs FIRST10 in ads (Task 2.1).
5. Discard the two square-photo draft ads? Restore `frequently_in`?
6. Footage for Sagittarius / Capricorn / Aquarius / Aries.
7. January pre-order for sold-out signs; container 981 mix.
8. Holiday Table back on Nov 10, and the Nov 28 email send.
9. MCP_KEY rename.

## D. Why this order

Offer and AOV come before creative because a 1-cup order at a $40 CPA earns
nothing; structure comes before concepts because Piliero's pack rules decide
how many concepts we need; Canva staging comes before Meta because the last
two builds failed on format and fields; the weekly rhythm comes before the
spend ladder because the last time spend went up 4× on one ad, CPA doubled.
