# Baci Milano USA: Google Ads build

Prepared 2026-11-02. No ad account was touched; this is a build sheet plus two
Google Ads Editor import files:

- `baci-google-ads-import.csv`: keywords (Exact + Phrase rows) with Max CPC and keyword-level Final URL, plus campaign-level negatives for all three campaigns (Criterion type `Campaign Negative Phrase`, blank Ad group). If your Editor version rejects that value, paste the negatives into Keywords and targeting > Negative keywords (campaign level) instead.
- `baci-google-ads-rsa.csv`: one responsive search ad per ad group (15 headlines, 4 descriptions, Final URL, Path 1/2).

Every headline and description was length-checked and scanned for banned phrases by a script
(`gen/build.py` in the scratchpad) against the exact strings in the CSVs. Nothing in the copy says
"made in Italy", "Italian-made", "crafted in Italy", "dishwasher safe", "BPA free", "free shipping"
or "official".

---

## 1. Economics (why the caps are where they are)

| Input | Value | Source |
|---|---|---|
| Organic Google orders, last 90 days | 9 | tonight's analysis |
| Organic conversion rate | 2.04% | tonight's analysis |
| Organic AOV | $94 | tonight's analysis |
| Store AOV | $144 | tonight's analysis |
| Gross margin | **50%, ASSUMED** | not verified; replace it with the real landed-cost margin |

Break-even CPC = CVR x AOV x margin = 0.0204 x $94 x 0.50 = **$0.96, about $1.00**. At the store
AOV ($144) it would be $1.47, but paid traffic has not shown that it buys at $144, so the $94 figure sets the cap.
Every keyword bid below sits between $0.60 and $1.00.

**Spend: $30/day if all three campaigns run at their stated budgets ($5 + $15 + $10).** That is
$5 over the "about $25/day" target. Two ways to fix it: (a) start Shopping at $5/day, or (b) launch
Shopping a week after Search. My recommendation is (a): Shopping at $5/day for the first two weeks.

### Semrush check (US, pulled 2026-11-02)

| Keyword | Vol/mo | Semrush CPC | Our bid |
|---|---|---|---|
| baci milano | 90 | $0.00 | $0.80 |
| baci milano usa | 20 | $4.31 | $0.80 |
| bacci milano / baci milan | 0 / 0 | n/a | $0.80 (misspelling safety net) |
| zodiac mugs | 170 | $0.50 | $0.90 |
| zodiac coffee mugs | 90 | $0.39 | $0.90 |
| astrology mugs | 70 | $0.44 | $0.80 |
| zodiac cup and saucer | 20 | $0.00 | $0.90 |
| melamine dinnerware set | 480 | $0.48 | $0.80 |
| outdoor dinnerware set | 260 | $0.66 | $0.80 |
| melamine salad bowl | 210 | $0.52 | $0.75 |
| acrylic champagne bucket | 70 | $0.58 | $0.80 |
| acrylic pitcher | 260 | $0.57 | $0.75 |
| acrylic cake stand with lid | 90 | $0.27 | $0.60 |
| italian espresso cups | 1,300 | $0.37 | $0.70 |
| italian serving platters | 210 | $0.54 | $0.75 |
| italian dinnerware | 720 | $0.77 | $0.90 |
| designer dinnerware | 320 | $0.93 | $1.00 |

Every non-brand bid is at or above Semrush's average CPC, so the ads should serve without anyone
raising bids above the cap. "italian espresso cups" has the most volume (1,300/mo) at the lowest
CPC, so watch whether it uses up the $15/day before anything else does.

---

## 2. Final URL verification (Shopify Admin, live, 2026-11-02)

| Requested URL | Exists? | Used for | Note |
|---|---|---|---|
| `/collections/zodiac-vibe` | Yes, 15 products | Zodiac | **Zodiac Vibe has NO mugs.** It holds porcelain cups with lid and saucer ($65). "zodiac mugs" traffic lands on cups. The copy says "cup" and never calls them mugs. Taurus, Libra and Scorpio show 0 inventory and Virgo shows 2. |
| `/collections/melamine` | Yes, 75 products | Melamine & Outdoor | 18-piece sets are $640. The Mamma Mia set shows 0 inventory; Joke White (4) and Portofino (11) are in stock. A "White Salad Bowl, Medium" ($125) exists for the salad-bowl keyword. |
| `/collections/aqua` | Yes, 12 products | `acrylic pitcher` keyword | Aqua pitchers are $125-145, in stock (4-9 each). The collection does NOT contain the champagne bucket or the cake stand. |
| (product) `/products/clear-champagne-bucket-crystal-touch` | Yes, ACTIVE, 17 in stock, $275 | `acrylic champagne bucket` keyword | Aqua has no bucket, so the keyword goes to the product page. |
| (product) `/products/baroque-rock-clear-cake-stand-with-cover` | Yes, ACTIVE, 50 in stock, $195 | `acrylic cake stand with lid` keyword | Same reason: it is a product page. |
| `/collections/acrylics-polycarbonate` | Yes, 46 products | Acrylic Barware **ad-level** Final URL | Contains all three products (all tagged Acrylic), so the ad-level URL is the umbrella collection. Keyword-level URLs override it. |
| `/collections/italian-coffee-cups` | Yes, 42 products | Italian Coffee & Serving **ad-level** Final URL | as requested |
| `/collections/all` | Yes, 342 products | `designer dinnerware`, `baci milano tableware` | as requested |
| `/collections/italian-espresso-cups` | Yes, 42 products | `italian espresso cups` keyword | **Changed from the plan:** this collection exists and matches the query exactly. |
| `/collections/italian-serving-platters` | Yes, 48 products | `italian serving platters` keyword | **Changed from the plan**, for the same reason |
| `/collections/italian-dinnerware` | Yes, 190 products | `italian dinnerware` keyword | **Changed from the plan**, for the same reason |
| `/` (home) | Yes (shop domain bacimilanousa.com) | Brand | |

All requested URLs exist, so no URL had to be swapped for a substitute. The only changes are three
keyword-level URLs, which now point at collections that match the query exactly, and the two acrylic
product pages, because Aqua does not hold those products.

**Attributes I verified on product pages and used in the copy:** shatterproof acrylic (bucket, clear
pitcher, Aqua Green pitcher, cake stand); crystal look; bucket has built-in handles, is oval and
holds multiple bottles and ice; cake stand has a domed cover and a 32 cm footprint; melamine sets are
18 pieces, service for 6, lightweight and resistant to breakage (Mamma Mia and Portofino set pages);
indoor/outdoor use; Zodiac Vibe cups are porcelain with lid and saucer at $65; espresso cups have
saucer and lid at $40 (Mamma Mia).

**Verified but left out on purpose:** "dishwasher-safe" is true for the bucket, the clear pitcher,
the Portofino set and the Sagittarius cup. The cake stand says hand-wash, and most other pages
don't mention it. Each ad covers a whole collection, so the claim would be false for some products in it.
"BPA-free" is on the bucket, clear pitcher and cake stand, but not on the Aqua pitchers.

**Brand-rule risk on the site itself (not in the ads):** the champagne bucket and clear pitcher pages
say "optical-grade **Italian acrylic**". That reads as a material-origin claim and sits close to
"made in Italy". Recommend changing it to "optical-grade acrylic, designed in Milan".

---

## 3. Campaign settings

### Baci | Brand | Search ($5/day)
- Type: Search. Networks: Google Search only. **Turn off Search Partners and the Display Network.**
- Bidding: Manual CPC; Enhanced CPC off. Max CPC $0.80 on all brand terms.
- Locations: United States, set to "Presence: people in or regularly in". Language: English.
- Ad rotation: Optimize.
- Negatives: the shared list in section 4. Brand searches are where `baci chocolate`, `perugina` and `baci gelato` show up.

| Ad group | Keyword | Match | Max CPC | Final URL |
|---|---|---|---|---|
| Brand | baci milano | Exact + Phrase | $0.80 | `/` |
| Brand | baci milano usa | Exact + Phrase | $0.80 | `/` |
| Brand | bacci milano | Exact + Phrase | $0.80 | `/` |
| Brand | baci milan | Exact + Phrase | $0.80 | `/` |
| Brand | baci milano shop online | Exact + Phrase | $0.80 | `/` |
| Brand | baci milano tableware | Exact + Phrase | $0.80 | `/collections/all` |

#### RSA: Brand
Final URL: `https://bacimilanousa.com/`  
Path: `/Baci-Milano/Shop` (11 / 4 of 15)

| # | Headline | Chars |
|---|---|---|
| H1 | Baci Milano USA | 15 |
| H2 | Baci Milano USA Online Store | 28 |
| H3 | Shop Baci Milano Online | 23 |
| H4 | Designed in Milan | 17 |
| H5 | Italian-Designed Tableware | 26 |
| H6 | Zodiac, Joke & Mamma Mia | 24 |
| H7 | Porcelain, Melamine & Acrylic | 29 |
| H8 | Designer Dinnerware & Decor | 27 |
| H9 | Statement Pieces for the Table | 30 |
| H10 | Coffee Cups, Plates & Trays | 27 |
| H11 | Shop the Full Collection | 24 |
| H12 | Gifts for the Table | 19 |
| H13 | Bold Milanese Design | 20 |
| H14 | Tableware Designed in Milan | 27 |
| H15 | Shop the US Collection | 22 |

| # | Description | Chars |
|---|---|---|
| D1 | Tableware designed in Milan: porcelain, melamine and acrylic for every table. | 77 |
| D2 | Shop Baci Milano in the US: coffee cups, dinnerware, serving trays and home decor. | 82 |
| D3 | From Zodiac Vibe cups to Mamma Mia plates, find bold Italian-designed pieces. | 77 |
| D4 | Statement tableware for hosts and gift-givers. Browse the full Baci Milano range. | 81 |

### Baci | Non-brand | Search ($15/day)
- Type: Search. Google Search only (Search Partners off, Display off). Manual CPC, Enhanced CPC off.
- Locations: US, presence only. Language: English.
- Each ad group's keywords are entered twice, once as Exact and once as Phrase (the CSV has both rows).

| Ad group | Keyword | Match | Max CPC | Final URL |
|---|---|---|---|---|
| Zodiac | zodiac mugs | Exact + Phrase | $0.90 | `/collections/zodiac-vibe` |
| Zodiac | zodiac coffee mugs | Exact + Phrase | $0.90 | `/collections/zodiac-vibe` |
| Zodiac | astrology mugs | Exact + Phrase | $0.80 | `/collections/zodiac-vibe` |
| Zodiac | zodiac cup and saucer | Exact + Phrase | $0.90 | `/collections/zodiac-vibe` |
| Melamine & Outdoor | melamine dinnerware set | Exact + Phrase | $0.80 | `/collections/melamine` |
| Melamine & Outdoor | outdoor dinnerware set | Exact + Phrase | $0.80 | `/collections/melamine` |
| Melamine & Outdoor | melamine salad bowl | Exact + Phrase | $0.75 | `/collections/melamine` |
| Acrylic Barware | acrylic champagne bucket | Exact + Phrase | $0.80 | `/products/clear-champagne-bucket-crystal-touch` |
| Acrylic Barware | acrylic pitcher | Exact + Phrase | $0.75 | `/collections/aqua` |
| Acrylic Barware | acrylic cake stand with lid | Exact + Phrase | $0.60 | `/products/baroque-rock-clear-cake-stand-with-cover` |
| Italian Coffee & Serving | italian espresso cups | Exact + Phrase | $0.70 | `/collections/italian-espresso-cups` |
| Italian Coffee & Serving | italian serving platters | Exact + Phrase | $0.75 | `/collections/italian-serving-platters` |
| Italian Coffee & Serving | italian dinnerware | Exact + Phrase | $0.90 | `/collections/italian-dinnerware` |
| Italian Coffee & Serving | designer dinnerware | Exact + Phrase | $1.00 | `/collections/all` |

#### RSA: Zodiac
Final URL: `https://bacimilanousa.com/collections/zodiac-vibe`  
Path: `/Zodiac/Coffee-Cups` (6 / 11 of 15)

| # | Headline | Chars |
|---|---|---|
| H1 | Zodiac Coffee Cups | 18 |
| H2 | Zodiac Cup & Saucer Sets | 24 |
| H3 | Find Your Zodiac Sign Cup | 25 |
| H4 | Astrology Coffee Cups | 21 |
| H5 | Porcelain Zodiac Cups | 21 |
| H6 | Cup, Lid & Saucer in One | 24 |
| H7 | Zodiac Vibe by Baci Milano | 26 |
| H8 | Designed in Milan | 17 |
| H9 | Gifts for Every Star Sign | 25 |
| H10 | A Birthday Gift by Star Sign | 28 |
| H11 | Zodiac Cups from $65 | 20 |
| H12 | Bold Celestial Designs | 22 |
| H13 | More Than a Zodiac Mug | 22 |
| H14 | Cups for Astrology Lovers | 25 |
| H15 | Shop the Zodiac Vibe Line | 25 |

| # | Description | Chars |
|---|---|---|
| D1 | Porcelain cup with lid and saucer for each sign, from the Zodiac Vibe collection. | 81 |
| D2 | Designed in Milan by Baci Milano. A personal birthday gift for every star sign. | 79 |
| D3 | Colorful celestial designs for coffee, tea or hot chocolate. Find your sign today. | 82 |
| D4 | Pick a sign for yourself or a friend and shop the Zodiac Vibe collection online. | 80 |

#### RSA: Melamine & Outdoor
Final URL: `https://bacimilanousa.com/collections/melamine`  
Path: `/Melamine/Dinnerware` (8 / 10 of 15)

| # | Headline | Chars |
|---|---|---|
| H1 | Melamine Dinnerware Sets | 24 |
| H2 | Outdoor Dinnerware Sets | 23 |
| H3 | Designer Melamine Plates | 24 |
| H4 | Melamine Salad Bowls | 20 |
| H5 | Indoor & Outdoor Dining | 23 |
| H6 | Designed in Milan | 17 |
| H7 | Breakage-Resistant Melamine | 27 |
| H8 | 18-Piece Sets, Service for 6 | 28 |
| H9 | Patio & Poolside Dinnerware | 27 |
| H10 | Portofino, Joke & Mamma Mia | 27 |
| H11 | Not Your Basic Melamine | 23 |
| H12 | Lightweight Melamine Plates | 27 |
| H13 | Stylish Outdoor Tableware | 25 |
| H14 | Melamine by Baci Milano | 23 |
| H15 | Shop Melamine Dinnerware | 24 |

| # | Description | Chars |
|---|---|---|
| D1 | Melamine dinnerware designed in Milan, made for patio, poolside and everyday meals. | 83 |
| D2 | 18-piece sets with dinner plates, dessert plates and soup bowls. Service for six. | 81 |
| D3 | Lightweight and resistant to breakage, with bold patterns from Portofino to Joke. | 81 |
| D4 | Plates, salad bowls and serving pieces for outdoor entertaining. Shop melamine now. | 83 |

#### RSA: Acrylic Barware
Final URL: `https://bacimilanousa.com/collections/acrylics-polycarbonate`  
Path: `/Acrylic/Barware` (7 / 7 of 15)

| # | Headline | Chars |
|---|---|---|
| H1 | Acrylic Champagne Bucket | 24 |
| H2 | Acrylic Pitchers | 16 |
| H3 | Acrylic Cake Stand with Lid | 27 |
| H4 | Shatterproof Acrylic | 20 |
| H5 | The Crystal Look, Shatterproof | 30 |
| H6 | Clear Cake Stand with Dome | 26 |
| H7 | Indoor & Outdoor Barware | 24 |
| H8 | Made for Poolside Parties | 25 |
| H9 | Designed in Milan | 17 |
| H10 | Champagne Bucket for Parties | 28 |
| H11 | Acrylic Serveware | 17 |
| H12 | Crystal Touch Collection | 24 |
| H13 | Baroque & Rock Acrylic | 22 |
| H14 | No Broken Glass by the Pool | 27 |
| H15 | Shop Acrylic Barware | 20 |

| # | Description | Chars |
|---|---|---|
| D1 | Crystal-look acrylic that won't shatter: champagne buckets, pitchers, cake stands. | 82 |
| D2 | Clear cake stand with domed cover, sized for a layer cake, a tart or a cheese board. | 84 |
| D3 | Oval champagne bucket with built-in handles holds multiple bottles and lots of ice. | 83 |
| D4 | Acrylic serveware designed for patios, pools and parties. Shop the collection now. | 82 |

#### RSA: Italian Coffee & Serving
Final URL: `https://bacimilanousa.com/collections/italian-coffee-cups`  
Path: `/Italian-Design/Coffee-Cups` (14 / 11 of 15)

| # | Headline | Chars |
|---|---|---|
| H1 | Italian Espresso Cups | 21 |
| H2 | Espresso Cups from $40 | 22 |
| H3 | Italian Serving Platters | 24 |
| H4 | Italian-Designed Dinnerware | 27 |
| H5 | Designer Dinnerware | 19 |
| H6 | Designed in Milan | 17 |
| H7 | Porcelain Espresso Cup Sets | 27 |
| H8 | Cup, Saucer & Lid Sets | 22 |
| H9 | Serving Trays & Platters | 24 |
| H10 | Mamma Mia Espresso Cups | 23 |
| H11 | Statement Coffee Cups | 21 |
| H12 | Bold Italian Design | 19 |
| H13 | Elevate Your Coffee Ritual | 26 |
| H14 | Hostess & Wedding Gifts | 23 |
| H15 | Shop Baci Milano | 16 |

| # | Description | Chars |
|---|---|---|
| D1 | Porcelain espresso cups with saucer and lid, designed in Milan. Make coffee a ritual. | 85 |
| D2 | Serving platters, trays and dinnerware with bold Milanese design for every table. | 81 |
| D3 | Mamma Mia espresso cups with symbolic designs. A thoughtful gift for coffee lovers. | 83 |
| D4 | Shop Italian-designed porcelain, melamine and serveware from Baci Milano online. | 80 |

**Notes on the copy:**
- Prices in copy ("from $65", "from $40") were read from Shopify on 2026-11-02. Remove those lines if prices change.
- "Breakage-Resistant", "Shatterproof" and "Lightweight" are each worded the way the product page states them.
- Nothing claims "every sign in stock", because three signs are out of stock.
- Pin nothing at launch. If you want "Designed in Milan" shown on every impression, pin it to Headline position 2. Pinning lowers Ad Strength, so only do it if the brand rule needs it.

### Baci | Shopping ($10/day as planned; recommend $5/day for the first two weeks, see section 1)
Setup notes:
1. **Merchant Center:** link it to the Google Ads account (Merchant Center > Settings > Linked accounts). The feed comes from the Shopify **Google & YouTube** app. In the app, confirm the products are approved and fix any "Missing GTIN / brand" items: set brand = `Baci Milano`, and if there is no GTIN, set `identifier_exists = no`.
2. **Feed hygiene:** titles must not say "made in Italy". Several product descriptions say "Italian acrylic"; the Shopify app copies descriptions into the feed, so fix those first (see section 2). Do not let the app add a "free shipping" annotation unless the shipping settings really are free.
3. Campaign: **Standard Shopping** (not Performance Max). Country of sale US. Bidding Manual CPC, Enhanced CPC off. Campaign priority Low. Networks: Google Search only, so untick Search Partners and YouTube/Discover/Gmail.
4. Product groups. Subdivide "All products" by **Custom label 0**, or by **Product type** if you'd rather not touch labels:
   - `zodiac` (tag Zodiac Vibe): **$0.90**
   - `acrylic` (tag Acrylic / Crystal Touch): **$0.90**
   - `melamine` (tag Melamine): **$0.90**
   - Everything else: **Excluded** at launch. This keeps the $10 on the three tested themes.
   Easiest route: in the Google & YouTube app (or a feed rule in Merchant Center), map Shopify tag to `custom_label_0`. Without labels, use Product type: Zodiac = "Cups" + brand, acrylic = "Pitchers" / "Cake stands & jars" / "Jugs and Bottles", melamine via the Melamine tag. Labels are cleaner.
5. Exclude products with 0 inventory (Merchant Center does this when availability = out of stock, but check that the Shopify sync sends inventory). Also exclude the DRAFT / B2B-only items, for example "Cake Jar & Mini Cake Jar Set (B2B Only)".
6. Negatives: the same campaign-level list as Search (in the CSV).
7. Expected first-week behaviour: Shopping impressions build slowly for the first 3-5 days while products are reviewed.

---

## 4. Negatives (campaign level, phrase match, applied to all three campaigns)

`made in italy`, `outlet`, `uk`, `geschirr`, `site officiel`, `wholesale`, `free`, `diy`, `cheap`, `used`, `baci chocolate`, `perugina`, `baci gelato`, `baci appliances`, `baci kitchen`, `recipe`

Watch-outs:
- `free` blocks "free shipping" queries too. That is intended, since we make no free-shipping claim.
- `wholesale` blocks B2B queries. Baci does sell wholesale, but those buyers should not arrive through retail ads.
- `made in italy` blocks searchers who want Italian manufacture. That is correct, because we cannot honestly serve them.
- Week 1: read the Search Terms report daily. Add as negatives anything about chocolate or candy, "baci" restaurants, or jobs/careers.

---

## 5. Pre-launch checklist (all must be YES before enabling)

- [ ] **Purchase conversion with value.** Google Ads > Goals > Conversions: one primary "Purchase" action from the Shopify Google & YouTube app (or GA4 import, but not both). Set value = order value (dynamic), count = One, click-through window 30 days. Place a test order and confirm the conversion records a value. Any "Add to cart" or "Begin checkout" actions are set to **Secondary** so they do not inflate results.
- [ ] **Enhanced conversions** on for the purchase action (Shopify app setting). Recommended, not blocking.
- [ ] **Merchant Center linked** to the Ads account, with the feed showing approved products for zodiac, acrylic and melamine.
- [ ] **Bot-traffic exclusion.** GA4: Admin > Data streams > Configure tag settings > Define internal traffic (add office/home IPs) and turn on the internal-traffic data filter. Google Ads: Settings > IP exclusions for the same IPs. Review the Invalid Clicks column after week 1. Also confirm the Shopify bot protection setting is on, and that no "Search Partners" or Display placements are enabled (they carry most of the junk traffic).
- [ ] **Search Partners and Display off** on both Search campaigns.
- [ ] **Location = presence only** ("People in or regularly in"), not "interest in".
- [ ] **Budgets entered as daily**: Brand $5, Non-brand $15, Shopping $10 (or $5, see section 1).
- [ ] **Every Final URL opens** (all checked in section 2 on 2026-11-02; check again on launch day).
- [ ] **Out-of-stock check:** Taurus, Libra, Scorpio (Zodiac) and the Mamma Mia melamine set are at 0.
- [ ] **Stop rule written into an automated rule.** Google Ads > Tools > Rules: "Pause ad group when Cost > $40 AND Conversions = 0, date range: all time, run daily". The rule is: **pause any ad group above $40 spend with 0 purchases.** At an $0.80 average CPC, $40 buys about 50 clicks, and at a 2.04% CVR, 50 clicks should yield about one purchase. With none, the ad group is not covering itself.
- [ ] **Margin confirmed.** The $1.00 break-even depends on a 50% margin that is ASSUMED. If the real margin is lower, cut every bid by the same ratio.

---

## 6. What to read after 7 and 14 days
- Per ad group: cost, clicks, purchases, conversion value, and ROAS against a break-even ROAS of 2.0 (1 / 50% margin).
- Search terms: add negatives, and promote converting search terms to Exact.
- Zodiac: if the "mug" keywords get clicks but no sales, the problem is the mismatch with the product (a cup and saucer, not a mug). Pause the "mug" keywords before the cup-and-saucer ones.
- Do not raise any bid above $1.00 until purchases show a real AOV and margin.
