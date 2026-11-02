# Baci Milano — Meta ads rebuild: handoff for the next thread (2026-11-02)

Read this whole file before any tool call. It is the state of record for the
Baci Meta ad account as of the evening of 2026-11-02. Everything here was read
from the live account, Shopify, Gmail or Drive in the session that wrote it,
unless marked **UNVERIFIED**.

---

## 0. Owner's standing rules for this work (verbatim or near-verbatim)

1. **No Meta write calls** ("You are not to call any meta ads tool calls for
   'Write' only read until you have successfully mapped, staged and planned the
   campaigns to hit our goals in ads"). Reads only until the owner approves the
   written plan.
2. **Plan everything in advance**, using the latest tool calls and Sam
   Piliero's structure, then **stage every creative in Canva first** as a
   strong *series*, before anything is uploaded to Meta. Never one ad at a time.
3. **Every creative is built for its placement**: 9:16 for Reels/Stories, 4:5
   for Feed, carousel cards where a carousel is the format. A square product
   photo on Stories renders as a small image on a black screen under a wall of
   text — that is what the last thread shipped to draft, and it "will not sell
   anything".
4. **Keep the $40 cost cap** on the scale campaign ("it's already floating
   above that").
5. **Never touch the winning ads** (list in §3).
6. **Verify before claiming.** Read back every object you build, field by
   field, and tell the owner what YOU checked separately from what Meta's
   validator said. Meta's draft validation passed an ad that failed at publish
   (deprecated `link_title`) — "VALIDATED" in a draft is not proof.
7. **Drafts only; nothing published, sent or launched without the owner's
   explicit OK.** Understand before acting; ask for what the record can't show.
8. Brand guardrail: Baci is **Italian-DESIGNED / designed in Milan** — never
   "made in Italy". The validator ban list also blocks "made to order".
9. Owner directive in code (`app/ad_craft.py:679`, `app/skill_pack.py:1799`):
   copy is generated "with the mind of Hormozi and Piliero and then checked
   against their opinions".

## 1. Environment — do this first

- The owner is adding `docs.google.com`, `app.kit.com`, `miro.com` to the
  environment's allowed domains. Confirm by fetching Sam's guide (§5). If it
  still fails, ask for a PDF export into Drive.
- MCP `gomehagent` returns 401: the session env var is named `MCP_Key`, the
  server expects `MCP_KEY` (owner action, still open).
- Meta account: **`949335500698690`** (Baci Milano USA). Page
  `563209373539609`. Instagram user `17841470148978488` (@bacimilanousa).
  Pixel/dataset `1050425080184653` (Purchase EMQ 9.1; PageView fbc 2.6% →
  heavy bot traffic, which is why site-visitor audiences were removed).
- Catalog `2646887072175123` (Shopify feed): 58 SKUs flagged out of stock,
  19 with a single image. No catalog/DPA campaign exists.
- Canva brand kit id **`kAGIWwLuTfs`**. Existing designs:
  "Baci Milano_2026 + Catalogs" `DAHWsvWkwec` (104 pages) and `DAHX6nwpZHY`.
- Shopify discount endpoint: use `discountNodes` (`codeDiscountNodes` is
  deprecated); product images: use `media` (`images` is deprecated).

## 2. Goal and the numbers that govern it

**Goal: Baci profitable at $1M/yr.** Model: `ops/baci-ads/unit_economics_model.py`;
partner page: `ops/baci-ads/partner-page-profitable-at-1m.html`.

Zodiac cup (Cup, Lid & Saucer), retail **$65**. Owner: 2 cups ≈ **€15 FOB /
€23 landed** (≈ $13.3/cup landed). Shipping: customer pays ~$8 under $110
retail; free at $110+ (so **2 cups ship free**). Chargeback/return 3% at $15 +
goods + shipping.

| Order (with FirstBaci 15%) | Net price | Kept before ads |
|---|---|---|
| 1 cup | $55.25 | **≈ $39** |
| 2 cups | $110.50 | **≈ $69** (assumes ~$10 label on free-ship orders — **UNVERIFIED**, ask) |

→ **At a $40 CPA a 1-cup order breaks even; the profit is in 2+ cups.** Every
concept should push the 2-cup order (host + you; two December birthdays; free
shipping on 2).

Discount codes (Shopify, live): `FirstBaci` 15%, min subtotal, 227 uses;
`FIRST15` 15% (56 uses); `FIRST10` 10% (4); `FirstBaci1`–`FirstBaci8`
("Meta test slot 1–8", 15%, **0 uses** — never put in an ad). Plan: one slot
code per test concept so Shopify attributes sales independently of Meta.
Two old creatives say "10% off with code FirstBaci" — wrong (code gives 15%).

## 3. Account state right now

### Live
| Campaign | ID | Budget | Notes |
|---|---|---|---|
| 04 4X ENGINE (scale) | `120253812101140184` | $150/day (draft: $300) | Ad set `120253812103400184`, cost cap **$40**, women 30–65+, A+ audience OFF, buyers 180d excluded. 7d spend ≈ $712. |
| 03 RETARGETING | `120254102812370184` | $75/day (draft: $50) | Ad set `120254102814370184`; carts 180d + IG engagers 60d + Zodiac video 75% 30d; had **lookalike expansion ON** (targeting_relaxation custom_audience=1) — it was partly prospecting. |
| 01 WINNERS | `120253812100950184` | off since Oct 24 | owner agreed to leave it off. |
| 05 HOLIDAY TABLE | `120254273538850184` | off since Oct 23 | ran 2 days only. Plan said: back on Nov 10. |
| 02 NEW ADS | `120253987535550184` | off | $133 CPA lifetime. |

**Winning ads — do not touch:**
- `120254225341840184` S | "Most Personal" (4X Engine) — $45.40 CPA, 15 purch / 14d
- `120254225348480184` S | "Their sign" trial reel (4X Engine) — $33, 4 purch / 14d
- `120254102816450184` R | "Their sign" reel (Retargeting) — $44.13, 12 purch / 14d
- `120253812185160184` W | "Most Personal" main winner (in Winners, campaign off)

**Paused live by the last thread** (sold-out-sign "comment your sign" ads):
`120253812110210184`, `120254102815370184`, `120254102817110184`.

### Draft (staged in Ads Manager, NOT published)
- 4X Engine: budget $300; ad set W30–64, renamed. **Also still contains two
  square-photo ads** `120254485395230184` (Sagittarius) and
  `120254485396790184` (Capricorn) — owner rejected them; discard previews
  exist but were never confirmed. **Discard them (with owner OK) before any
  publish.**
- Retargeting: budget $50; ad set W/all 30–64, expansion off.
- Both ad-set rewrites dropped location type `frequently_in` (now
  home+recent). Unrequested; owner was asked whether to restore — no answer.
  (The old Piliero ad set used home+recent too.)
- Other campaigns hold stale drafts from Jul–Oct with 5 errors — leave them;
  publish per campaign, never "Publish all".

## 4. Findings (audit, 2026-11-02)

**Economics/attribution**
- Break-even CPA ≈ $71 at blended AOV $101 / 70.4% contribution (DTC). Cup
  economics above are the stricter view.
- Ads only ran "properly" from June; weekly incremental return was ~$1.47–1.53
  per $1 in good periods and $0.82 in late July (seasonality confounds monthly
  regressions — the owner rejected a monthly read).

**Account behaviour**
- ~45 manual edits Oct 19–Nov 1; all three main campaigns off Oct 24–28;
  billing grace period Oct 20–22. Learning never settled. Rule going forward:
  scale campaign is edited on Mondays only, budget ±20% max per 72h, never
  switch campaigns off (pause ads instead).
- Age (Jun 1–Nov 1): F45–54 best ($68 CPA); F35–44 biggest spend ($20K, $94);
  F65+ $308. Placements: IG Reels $80 best; IG feed $91; FB feed $101; FB
  Reels $164.
- Main winner fatigued in uncapped Winners: weekly CPA $50 → $66 → $60 → $91
  → $128 as CPM rose $41 → $54; the capped copy did $44.50.
- Duplicate creatives: "Everyday moment / Comment your sign" exists ~12×,
  "Most Personal Gift" ~7× across campaigns — self-competition.

**Stock (Shopify, 2026-11-02) vs 28-day sales**
| Sign | Stock | Sold 28d |
|---|---|---|
| Capricorn | 175 | 26 |
| Sagittarius | 161 | 27 |
| Aquarius | 50 | 13 |
| Aries | 45 | 13 |
| Cancer | 23 | 10 |
| Gemini | 21 | 16 |
| Leo | 18 | 10 |
| Pisces | 16 | 26 (≈2.5 wks) |
| Virgo | 2 | 17 |
| Scorpio / Libra / Taurus | 0 | 48 / 43 / 11 |

511 cups total, 336 of them Sagittarius + Capricorn — whose birthday seasons
(Nov 22–Dec 21, Dec 22–Jan 19) coincide with holiday gifting. Container 981
(7,288 cups) arrives mid/late December, after the ship-by-Christmas cutoff, and
over-allocates the slowest signs (752 each vs 504 for best sellers) — ask
whether the mix can still change. Rule: pause any ad pointing at a sign < 10
cups. Option pending owner: January pre-order for sold-out signs.

## 5. Sam Piliero — what we know, and whether we followed it

Sources: Gmail from `sampiliero@themoonlighters.com` — "Your Meta guide as
requested" (2026-09-01, thread `1a05ca380782a213`), "as requested" (22-page M4
guide, reply-to-confirm, `1a05ca064d3d2831`), "Your Facebook ads campaign
flowchart" (Miro, `19c7b66d8a667739`), and Emma Cooper's email (thread
`19e28f62f0478d23`) linking his campaign-structure doc:
**https://docs.google.com/document/d/1W5NqZVHhXUx8CxcpGJNMpZyBf4kztNFbaQWPgBm9uh0**
(not in Drive; was blocked by the network policy — read it first now).

Our own implementation of it: Drive `Baci_Milano___Wave_1_Launch_Plan.docx`
(`17ixAzM2jJ-FRFZorcO3ZIei34Tk4834U`, 2026-03-27, "Piliero M4 Method +
Mathews Funnel Architect"): one Prospecting CBO, several "Broad Packs" (ad
sets = one creative concept each, several ads per pack), all ads built before
activation, packs launched together with $35/day floors, Day-7 decision rules,
Wave-2 packs added one at a time, A+ creative enhancements off.

**Verdict — it was not executed, and what ran lost money:**
- Campaign `120245650447380184` spent **$30,453 → 375 purchases, $81.21 CPA,
  1.05 ROAS**.
- **One pack took 99.4%**: "Broad Pack 2 — Zodiac Test"
  `120245653147820184` ($30,274). BP1 Scale $81 then paused; Packs 3, 6, 7, 8
  and Gift Angle **$0** — never activated. Day-7 rules / Wave 2 never ran.
- Inside it, 10 "Refresh" ads were added at once on May 15; **one ad
  (`120248518984080184`, "Refresh 8 | AD4") took $20,600 (68%)**, the rest
  < $220 each → a single-ad account for five months.
- Monthly: Apr $56 CPA (3 ads — closest to the plan) → May $76 → Jun $68 →
  Jul $112 as spend grew ~4×.
- That ad set ran with **Advantage+ audience ON** (women, 25–54 suggestion) —
  more purchases than anything since; the current structure has A+ audience off.
- Current structure (since Sep) is not Piliero's either. Best performer now:
  4X Engine (cost cap) $44–58 CPA.

**Next thread must:** read the guide + flowchart, then audit rule-by-rule
(campaign count, CBO/ABO, pack size, concept diversity, testing cadence, kill
and graduation rules, budgets/bidding, audience settings, creative volume and
formats) against the account, and say which rules we break today.

## 6. The game plan (in this order; each step ends with an owner check)

**The full task-by-task version, with the $1M targets and the model's
break-even MER, is `ops/baci-ads/PLAN-profitable-1m.md`. Work from that.**

1. **Read** Sam's guide/flowchart. Write the rule-by-rule audit (§5).
2. **Map** the account to his structure, keeping the $40 cost-cap scale
   campaign and the four winners. Output: campaigns → ad sets/packs → ads,
   budgets, bid strategy, audiences (decide A+ audience on/off with the data
   above), placements, exclusions, and the weekly operating rules (Monday-only
   changes, graduation/kill thresholds, stock rule).
3. **Concepts** (Hormozi value levers + Piliero diversity): ≥ 4–5 genuinely
   different entries — identity, gifting, occasion, objection, offer
   (`app/ad_craft.py` ANGLES / VALUE_LEVERS / HEADLINE_TYPES). Lead with the
   in-stock signs (Sagittarius, Capricorn; also Aquarius, Aries), push the
   2-cup order, holiday timing, Giselle Bassi partnership. Each concept gets a
   FirstBaci1–8 slot code. Copy rules: hook in first 5 words, offer inside
   first 125 characters, headline ≤ 40 characters, ≥ 2 value levers.
4. **Production spec per concept**: 9:16 (Reels/Stories, safe zones, text in
   frame, short caption) + 4:5 (Feed) for every ad; carousel only where it
   fits. Prefer video (winners are vertical video). Source assets: Drive
   (Zodiac reels, Morning Ritual, partner shoots), Shopify product media,
   existing IG posts ("use existing post" keeps social proof). Ask the owner
   for footage where none exists.
5. **Stage the whole series in Canva** (brand kit `kAGIWwLuTfs`), one folder,
   every size per concept, for owner review. Comment/iterate in Canva.
6. Only after owner approval: lift the Meta write freeze → upload as one batch
   per pack, placement-customised creatives, read back every field, launch the
   pack together.
7. Then the website work (sold-out signs, pre-order option) — owner said ads
   first, website after.

## 7. Open owner questions
- Restore `frequently_in` location type? (§3)
- OK to discard the two square-photo draft ads? (§3)
- Real label cost on free-shipping orders (for the 2-cup margin).
- Switch 10%-copy ads to `FIRST10`, or keep FirstBaci 15% everywhere?
- January pre-order for Scorpio/Libra/Taurus/Virgo?
- Can container 981's sign mix still change?
- Holiday Table back on Nov 10?
- Footage/photos available for Sagittarius & Capricorn?

## 8. Mistakes the last thread made (don't repeat)
- Called the Holiday campaign "idle" without reading the change log (it ran 2
  days and was switched off).
- Built image ads with `image_url` → "picture and image_hash both specified";
  then `ads_create_creative` put the headline into
  `call_to_action.value.link_title` (deprecated, rejected at publish). If
  creating inline creatives, put the headline in `link_data.name` and only
  `link` inside `call_to_action.value`.
- Used a square product photo for Stories/Reels placements.
- Rewrote ad-set targeting and silently dropped a field.
- Reported "validated, no errors" as if it were verification.

## 9. Prompt to start the next thread

> Read `ops/baci-ads/HANDOFF-baci-meta-ads-2026-11-02.md` in full. Meta is
> read-only until I approve the plan. Step 1: confirm you can open Sam
> Piliero's campaign-structure guide (§5 link) and the Miro flowchart, then
> give me the rule-by-rule audit of our account against it. Do not build
> anything yet.
