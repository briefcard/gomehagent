# Baci Milano USA: Meta account structure (M4 swimlanes)

Status: **proposal, not applied.** Ad account 949335500698690. Live state
read from Meta on 2026-11-09.

Every control is tagged with its source:
- **[M4]**: Sam Piliero, *M4 Method Guide*, by section.
- **[Meta]**: the linked Meta Business Help Center article.
- **[Owner]**: a business rule set by the owner.
- **[Ours]**: no outside source; our judgement.

## Before anything: eligibility

- M4 says it is for e-commerce brands spending **$1,000/day or more**
  [M4, intro]. Baci spends about $330/day, so it is below that threshold.
- Its cost-cap phase additionally requires **$30K+/month and 90 days of
  stability** [M4, "Cost Caps"]. Baci is at about $10K/month.
- Meta's own guidance points the same way: cost per result goal "works best
  when your ad set gets at least **50–100 weekly conversions**." Scale got
  10–24 a week, and its learning status is FAIL. [Meta, [About cost per
  result goal](https://www.facebook.com/business/help/272336376749096)]

## The four swimlanes

| Swimlane | Who it reaches [M4] | Job | Excludes [M4] |
|---|---|---|---|
| Prospecting | 100% net new. Broad packs, plus single-interest "winners" ad sets | Test new creative in packs; find winners | Retargeting, Retention |
| Scale (optional) | 100% broad net new | Put more money behind graduated winners only | Retargeting, Retention |
| Retargeting (optional) | Site visitors, add-to-carts, IG/FB engagers | Convert warm non-buyers | Retention |
| Retention | Existing customers | Repeat purchases | — |

M4 separates these lanes "to ensure Meta doesn't dip into our warm
audiences and create a blended ROAS," and so each lane's return is known on
its own [M4, "M1"].

## Shared audience definitions (one definition, used everywhere) [Ours]

- **RETENTION** = FA26 · Purchasers · 365d ∪ FA26 · Customer List · Shopify
  Buyers ∪ Long-Time Buyers
- **RETARGETING** = RTG · Cart + Checkout Abandoners · 180d ∪ FA26 · IG
  Engagers · 60d ∪ FA26 · FB Page Engagers · 60d ∪ FA26 · Zodiac Video
  Viewers 75% · 30d
- **Site visitors**: left out until site traffic is confirmed clean. Shopify
  sessions fell from about 8k/day to about 150/day on Nov 5 while
  add-to-carts held steady, consistent with bot traffic being filtered out.

## Live state vs target

| Control | Prospecting | Scale | Retargeting | Retention |
|---|---|---|---|---|
| **Exists today** | Yes ($110/day) | Yes ($150/day) | Yes ($75/day) | **No** |
| **Exclusions, live** | RETENTION + RETARGETING ✅ | Purchasers 180d only ❌ (engager and visitor exclusions removed Oct 23) | Purchasers 180d ⚠️ (narrower than RETENTION) | — |
| **Exclusions, target** [M4] | RETENTION + RETARGETING | RETENTION + RETARGETING | RETENTION | — |
| **Objective** [M4] | Sales | Sales | Sales | Sales |
| **Budget type** [M4] | CBO | CBO | CBO | CBO |
| **Bid strategy** | Highest volume [M4, "Cost Caps"; Meta 50–100/week] | **Owner decision, below** | Highest volume | Highest volume |
| **Ad set spend limits** [Meta] | Remove all; least possible | None | None | None |
| **Creative** | Packs of 4–8; new creative = new pack [M4] | Graduated winners only, duplicated [M4] | Mixed proof/offer [Ours] | Cross-sell / next sign [Ours] |

## Owner decision: how to enforce $40 in Scale

**Option A: keep the $40 cost cap.**
- Pro: the hard ceiling stays inside the auction.
- Con: with 10–24 conversions a week, Meta's own threshold of 50–100 isn't
  met, so expect thin and erratic delivery (as seen Nov 2–9).
- Con: M4 says cost caps used before $30K/month "will not behave how you
  expect."

**Option B: highest volume, plus an automated rule.**
- The rule pauses any Scale ad whose 7-day cost per purchase is above $40
  once it has spent at least $80.
- Meta documents this exact use: "if it is absolutely imperative that the
  campaign cost per result is below a specific value… set up an automatic
  rule" ([About cost per result exceeding bid cap or cost per result
  goal](https://www.facebook.com/business/help/867416745088574)).
- Con: individual days can run above $40 before the rule acts. The $40 is
  enforced over a 7-day window, not per auction.

Either option honours the $40 rule. We recommend B.

**DECIDED 2026-11-09: Option B, 7-day window** (owner). The cap stays on
until the rule is confirmed live in Ads Manager; then the cap is removed
and Scale's exclusions are fixed in one edit, so learning restarts once.

## Build order (Mondays only; each step read back from Meta)

1. **Scale:** add RETARGETING + RETENTION exclusions.
   - This is a targeting change, so it restarts learning
     ([Significant edits](https://www.facebook.com/business/help/316478108955072)).
   - Make the bid decision (A or B) in the same edit, so learning restarts
     only once.
2. **Retargeting:** widen its exclusion from Purchasers 180d to RETENTION.
   Also a significant edit.
3. **Prospecting:** remove ad set spend limits once Meta allows it. Today it
   refuses a maximum below $102 on C. Meta advises against a minimum and a
   maximum on the same ad set
   ([Spend limits](https://www.facebook.com/business/help/454681230514942)).
4. **Retention:** create it.
   - Sales objective, CBO, audience = RETENTION.
   - Small budget, e.g. $15–20/day [Ours; M4's spend calculator wasn't
     retrievable].
   - Creative: second-sign and cross-collection.
5. **Graduation:** every Monday, duplicate (not move) any prospecting ad
   with high spend at ≤ $40/sale into Scale, and into a single-interest
   "winners" ad set in prospecting [M4].
6. **Wait 7 days** after each step and judge it on weekly averages [Meta].

## Open items

- Retrieve the M4 flowchart and the ad-spend calculator. The Miro link and
  the calculator were not reachable from this environment; the budget split
  above is ours until they are.
- The unpublished Ads Manager draft (Nov 2 restructure, about 66 edits) must
  be resolved first. Every edit made through the API lands in that draft
  until it's cleared.
