# Eien Health: compliant replacement copy for Google Ads

Prepared 2026-11-02. No ad account was touched.

> **FLAG: the live ad copy has NOT been reviewed.** The Eien Google Ads account is not connected to
> this workspace, so I could not read the current ads, keywords, disapprovals or policy status for
> "Funnel | GLP-1 | US" or "Turmeric". The copy below is a full replacement written from the website.
> It is not a diff against what is running. Before pasting it in, export the live ads and keywords (or
> connect the account) and check them against the never-use list in section 4.

Every line below was length-checked and scanned by script (`gen/build.py`) against the never-use list
in section 4. The scan matches whole words, so "Eien Health" does not trip on "heal".

---

## 1. What I could verify (source: eienhealth.com crawl, 2026-11-02)

The Shopify connector here is signed in to Baci, not Eien, and the session cannot fetch
eienhealth.com directly (`products.json` was blocked). I used a brand crawl of 8 pages instead: home,
/collections/shop, /pages/about-us, and the two product pages. The ads use only facts stated on those pages:

| Fact used in copy | Where it appears |
|---|---|
| "GLP-1 Support: Advanced Gut + Mobility Supplement" (product name and subtitle) | product page, shop page |
| 16 naturally-derived actives across 3 matrices | product page |
| 2 capsules a day; 30-day supply | product page |
| Key actives: hops flower extract (xanthohumol) 500 mg, curcumin 250 mg, synbiotics (FOS + probiotic blend) 250 mg, boswellia 125 mg, capsicum, cinnamon bark, licorice root, magnesium malate, bromelain, green tea 50% EGCG, ginger root, CoQ10, black pepper extract, B6, L-methylfolate, chromium picolinate | product page |
| "Supports ... digestive comfort" (structure/function wording) | product page |
| Triple Power Joint Support: turmeric, curcumin, hydrolyzed collagen, BioPerine black pepper extract "to help support absorption" | about-us |
| "support joint comfort and flexibility", "for active adults" | about-us |
| Triple Power price $39.99 | shop page (re-check before launch) |
| Manufactured in the USA; US-based company | about-us |
| Never tested on animals; full supplement facts on every label | about-us |
| "Lab-Tested" | home page trust badge |
| 90-day money-back guarantee; subscribe and save, pause/change/cancel anytime | about-us |

**Left out on purpose:** "20,000+ reviews / 4.9" (the site says some testimonial visuals are
AI-generated, and a review count in ad text has to be independently verifiable, so use Google seller
ratings instead); "Medical-Grade" (the site calls the guarantee "Medical-Grade", which reads as a medical
claim); "Clinically Backed"; everything about appetite, cravings, metabolism, gastric emptying,
inflammation and relief.

---

## 2. Replacement RSAs

### Campaign: Funnel | GLP-1 | US (rename to "Funnel | Gut + Mobility | US", see section 3)
Final URL: `https://eienhealth.com/products/glp-1-advanced-gut-mobility-supplement`  
Path: `/Gut-Mobility/Supplement` (12 / 10 of 15)

| # | Headline | Chars |
|---|---|---|
| H1 | Eien Health Gut + Mobility | 26 |
| H2 | Daily Gut Support Capsules | 26 |
| H3 | 16 Naturally-Derived Actives | 28 |
| H4 | Made in the USA | 15 |
| H5 | With Curcumin & Ginger Root | 27 |
| H6 | Prebiotics + Probiotics | 23 |
| H7 | Hops, Boswellia & Cinnamon | 26 |
| H8 | Just 2 Capsules a Day | 21 |
| H9 | 30-Day Supply per Bottle | 24 |
| H10 | 90-Day Money-Back Guarantee | 27 |
| H11 | Subscribe & Save | 16 |
| H12 | Full Supplement Facts Listed | 28 |
| H13 | Never Tested on Animals | 23 |
| H14 | Supports Digestive Comfort | 26 |
| H15 | Lab-Tested Formulas | 19 |

| # | Description | Chars |
|---|---|---|
| D1 | A daily gut + mobility supplement with 16 naturally-derived actives. Made in the USA. | 85 |
| D2 | Hops flower extract, curcumin, boswellia, ginger, CoQ10 and a synbiotic blend. | 78 |
| D3 | Two capsules a day, 30-day supply. Full supplement facts on every label. Shop Eien. | 83 |
| D4 | Try it with our 90-day money-back guarantee. Subscribe and save, pause anytime. | 79 |

### Campaign: Turmeric (rename to "Funnel | Turmeric Joint | US")
Final URL: `https://eienhealth.com/products/triple-power-joint-support`  
Path: `/Turmeric/Triple-Power` (8 / 12 of 15)

| # | Headline | Chars |
|---|---|---|
| H1 | Triple Power Joint Support | 26 |
| H2 | Turmeric + Curcumin Formula | 27 |
| H3 | With Hydrolyzed Collagen | 24 |
| H4 | Plus Black Pepper Extract | 25 |
| H5 | Supports Joint Comfort | 22 |
| H6 | Supports Flexibility | 20 |
| H7 | Made in the USA | 15 |
| H8 | Made for Active Adults | 22 |
| H9 | Turmeric Supplement $39.99 | 26 |
| H10 | 90-Day Money-Back Guarantee | 27 |
| H11 | Subscribe & Save | 16 |
| H12 | Never Tested on Animals | 23 |
| H13 | Naturally-Derived Ingredients | 29 |
| H14 | Full Supplement Facts Listed | 28 |
| H15 | Eien Health Turmeric | 20 |

| # | Description | Chars |
|---|---|---|
| D1 | Turmeric, curcumin and hydrolyzed collagen in one daily formula for active adults. | 82 |
| D2 | Supports joint comfort and flexibility as part of a daily routine. Made in the USA. | 83 |
| D3 | Includes black pepper extract to help support absorption. Naturally-derived actives. | 84 |
| D4 | Backed by a 90-day money-back guarantee. Subscribe and save, and pause any time. | 80 |

Copy notes:
- "Supports Digestive Comfort", "Supports Joint Comfort" and "Supports Flexibility" are classic
  structure/function wording, and each is stated on the site. They are the only benefit lines. Everything else is
  a factual attribute: ingredients, dose, origin, guarantee or offer. If a reviewer pushes back, drop
  those three lines first; the remaining 12-13 headlines still meet the RSA minimum of 3.
- "BioPerine" is a third-party trademark (Sabinsa), so it is written as "black pepper extract" to avoid
  a trademark limitation.
- No exclamation marks, superlatives, timelines ("within days") or before/after framing.
- **Path text** avoids "glp-1", but the **Final URL slug** is `/products/glp-1-advanced-gut-mobility-supplement`. See section 5.

---

## 3. Campaign renames

| Current | Proposed | Why |
|---|---|---|
| Funnel \| GLP-1 \| US | **Funnel \| Gut + Mobility \| US** | It mirrors the product's own subtitle ("Advanced Gut + Mobility Supplement") and points at the only benefit area we claim (digestive comfort plus ingredients). |
| Turmeric | **Funnel \| Turmeric Joint \| US** | It follows the same naming pattern, names the product (turmeric) and its structure/function area (joint), and contains no disease word. |

**Is "Funnel | Metabolic Support | US" safe?** Campaign names are not shown to searchers, and Google's
ad review does not review them, so as a *name* it carries no direct policy risk. I still recommend
against it, for two reasons:
1. A campaign name tells whoever builds the next ads what the campaign is about. "Metabolic Support"
   points them toward metabolism, appetite and weight copy. On a product sold as "GLP-1 Support", that
   is exactly the copy that gets disapproved under Google's weight-loss and unapproved-substance rules.
2. "Metabolic support" is a structure/function phrase, so it is legal under DSHEA, but in Google's
   classifiers it sits next to weight-loss intent. Keywords grouped under that theme ("metabolism
   supplement", "metabolic booster") pull in weight-loss queries and land in restricted territory.

"Gut + Mobility" describes the same product with no weight-loss signal.

**Keywords to check once the account is connected:** if the campaign bids on `glp-1`, `glp 1
supplement`, `natural ozempic` or `ozempic alternative`, pause them. Add as campaign negatives:
`ozempic`, `wegovy`, `semaglutide`, `tirzepatide`, `mounjaro`, `zepbound`, `compounded`,
`prescription`, `injection`, `weight loss`, `lose weight`, `diet pill`, `fat burner` (not bare `diet`, which close-variant matching can stretch to "dietary supplement").
Bidding on prescription-drug names without Google healthcare certification triggers the
unapproved-pharmaceutical policy no matter what the ad text says.

---

## 4. Never use (in ad text, sitelinks, callouts, image assets, or keyword-inserted text)

**Drug and mechanism terms:** GLP-1, GLP 1, glucagon-like peptide, Ozempic, Wegovy, semaglutide,
tirzepatide, Mounjaro, Zepbound, "natural Ozempic", "Ozempic alternative", "nature's Ozempic",
"GLP-1 booster", "GLP-1 activator", "boost GLP-1", "GLP-1 production", "GLP-1 pathway", gastric emptying,
insulin, blood sugar, glucose, hormone.

**Weight-loss terms:** weight loss, lose weight, lose pounds or inches, fat loss, fat burning, burn fat,
"afterburner", belly fat, stubborn weight, slim, skinny, diet pill, appetite suppressant, curb
appetite, appetite control, cravings, "feel lighter", "in control of your body", metabolism boost,
metabolic booster, BMI, before/after.

**Disease and medical terms:** arthritis, inflammation, anti-inflammatory, "joint inflammation",
pain, pain relief, "pain control", relief, heal, cure, treat, prevent, diagnose, disease, condition,
diabetes, prediabetes, PCOS, IBS, bloating cure, mitochondrial, detox, anti-aging (in ads).

**Authority and proof claims:** clinically proven, clinically backed, clinical precision,
doctor-recommended, doctor-formulated, medical-grade, pharmaceutical-grade, FDA-approved, FDA-registered,
"science-backed results", "20,000+ reviews", "4.9 stars" (use seller ratings instead), "real
results", testimonials framed as outcomes.

**Timelines and guarantees of effect:** "within 7 days", "in as little as 5-14 days", "feel the difference
within days", "results guaranteed". The money-back guarantee is fine; any guarantee of a result is not.

---

## 5. The landing pages will fail review even with clean ads (owner decision needed)

Google reviews the destination as well as the ad. On 2026-11-02 the site carries claims that will
get these ads disapproved or limited however clean the ad text is:

| Page | Claim on the page | Problem |
|---|---|---|
| Home | "Supports fat loss (Burn) within 7 days", "Helps balance afterburner & fat burning", "Supports metabolism, energy & pain control", "Natural ingredients promote healthy GLP-1 production" | weight-loss timeline, mechanism and pain claims |
| Home | "Struggling with cravings, stubborn weight..."; "Feel in control of your body again" | weight-loss framing |
| Product (GLP-1) | product name "GLP-1 Support"; URL slug `glp-1-...`; "Supports normal gastric emptying" | GLP-1 mechanism; drug-adjacent naming |
| Product (GLP-1) | links to "Natural Weight Loss Supplements for Women" | weight-loss collection one click from the landing page |
| Triple Power | "Support your body's natural recovery and joint inflammation, notice relief and flexibility in as little as 5-14 days"; "Clinically Backed" | disease-adjacent claim, timeline, unsupported clinical claim |
| About | "90-Day Medical-Grade Money-Back Guarantee" | "medical-grade" |
| Blog | article opening on arthritis treatment | disease content one click away |

This is also a conflict with the Eien guardrail in the gomehagent site profile ("no medical claims").

Recommended order:
1. Remove the home-page "Inside the Formula" bullets and replace them with the product page's
   structure/function bullets (without the GLP-1 and gastric-emptying lines).
2. Create a clean landing variant for ads, for example `/pages/gut-mobility`, or a product duplicate whose handle and
   title have no "GLP-1". Point the Gut + Mobility campaign there.
3. On Triple Power, replace "joint inflammation ... relief ... 5-14 days" with "supports joint
   comfort and flexibility", and drop "Clinically Backed".
4. Change "Medical-Grade Money-Back Guarantee" to "90-Day Money-Back Guarantee".
5. Make sure the FDA disclaimer appears on the product pages themselves (it appears on about-us).

Until 1-3 are done, expect "Healthcare and medicines: unapproved substances / misleading health claims"
or "Weight loss" disapprovals or limited serving on the GLP-1 campaign, even with this copy.
