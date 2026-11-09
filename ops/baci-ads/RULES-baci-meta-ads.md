# Baci Milano USA — Meta ads standing rules

Owner-set rules for ad account 949335500698690. Any session or person
touching this account checks a change against these rules **before** it
goes live. Companion to `HANDOFF-baci-meta-ads-2026-11-02.md`
(branch `claude/sleepy-mendel-lpoz4j`).

Every rule below says where it comes from:
- **[Owner]**: a business decision by the owner. Not up for debate.
- **[M4]**: Sam Piliero's *M4 Method Guide*. Section names are quoted.
- **[Meta]**: a Meta Business Help Center article, linked.
- **[Ours]**: our own judgement, with no outside source. Can be revised.

## Rules

1. **$40 is the maximum cost per sale.** [Owner]
   The enforcement mechanism is an open decision, logged in
   `STRUCTURE-baci-meta-ads.md`. A cost cap is one option. An automated
   rule that pauses anything above $40 is the other; Meta documents it for
   exactly this case ([About cost per result exceeding bid cap or cost per
   result goal](https://www.facebook.com/business/help/867416745088574)).

2. **Graduation is decided by data set in advance.**
   - Graduate only on **high spend AND at or under target** (target =
     $40/sale). Never cherry-pick a low-spend ad with a high return. [M4,
     "Criteria For Graduation"]
   - Low spend + poor performance → pause. High spend + low performance →
     "a catchy ad that doesn't convert." Average → don't touch. [M4,
     "Creative Packs and Signal Density"]
   - Test ads are paused at **$80 spent with no sale (2 × target)**. [Ours.
     M4 gives no dollar threshold.]

3. **Winners are duplicated into Scale, never moved.** [M4, "The Graduation
   System": "Winning creatives are duplicated (not moved/paused)… NEVER pause
   a high performing ad for organization purposes."]
   - *Correction, 2026-11-09:* an earlier version of this file said a winner
     runs in one place only. That contradicts M4 and is withdrawn.
   - The Nov 9 pause of A6 still stands under rule 2. In prospecting, A6 had
     spent $330 at $165/sale: high spend, low performance. It was not a
     prospecting winner.

4. **Swimlanes and exclusions.** [M4, "M1 | Campaign Structure"]
   - Prospecting and Scale exclude Retargeting and Retention.
   - Retargeting excludes Retention.
   - All campaigns use the same audience definitions (see
     `STRUCTURE-baci-meta-ads.md`).

5. **Campaign setup.**
   - Sales objective. [M4, "Traffic Campaigns vs Sales Campaigns"]
   - Campaign budget (CBO) is the default. [M4, "Campaign Setup"]
   - New creative goes in new packs of 4–8 ads. [M4, "Creative Packs"]
   - As few ad set spend limits as possible. Never a minimum and a maximum
     on the same ad set. [Meta, [About ad set spend limits with Advantage+
     campaign budget](https://www.facebook.com/business/help/454681230514942)]

6. **Change discipline.** [Ours]
   - Changes on Mondays only, read back from Meta after publishing.
   - Never publish the Ads Manager draft wholesale; only owner-approved
     objects.
   - Evaluate a change on weekly averages, at least 7 days after it. [Meta,
     [About cost per result goal](https://www.facebook.com/business/help/272336376749096)]
   - Targeting, creative, new ads, optimization event and bid strategy are
     all significant edits that restart learning. [Meta, [Significant edits
     and learning phase](https://www.facebook.com/business/help/316478108955072)]

## Corrections to earlier advice (2026-11-09)

- **"Minimums are part of the method":** wrong. M4 never mentions ad set
  minimums. Meta recommends using as few spend limits as possible.
- **"Testing should be about 20% of spend":** wrong. M4's 80/20 is about
  creative effort (80% iterating on winners, 20% new formats), not budget.
  M4 points to an ad-spend calculator we could not retrieve.
- **"The two campaigns bid against each other":** wrong mechanism. When your
  own ad sets meet in the same auction, Meta enters only the one with the
  highest total value. The others sit that auction out ([Understand auction
  overlap](https://www.facebook.com/business/help/537699989762051)). The
  outcome is the same (the capped Scale set was left out of auctions), but
  the cause is selection, not a bidding war.

## Why (Nov 2026)

- From Nov 3, prospecting ran at $260/day with $210 of forced minimums and
  no cap, alongside a copy of Scale's top ad shown to the same women aged
  30–64.
- Scale's best ad went from $44.50 to $122 per sale, and Scale's spend fell
  from about $175/day to under $15/day.
- Account sales fell from about 6/day to about 2/day.

## Change log

| Date | Change | By |
|---|---|---|
| 2026-11-09 | Prospecting budget $260 → $110/day; ad set minimums A/B/C $60/$60/$90 → $30 each; C maximum $100 → $110 (Meta's floor) | Claude, owner-approved |
| 2026-11-09 | Paused "A6 \| Most Personal Gift" in prospecting ($330, $165/sale: high spend + low performance) | Claude, owner-approved |
| 2026-11-09 | Paused "B1 v4 \| Skip the wine" ($101 spent, 0 sales) | Claude, owner-approved |
