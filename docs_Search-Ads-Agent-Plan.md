# Search & Search-Ads Agent — Skill List & Implementation Plan
*SEO / GEO / Google / Bing / Pinterest / YouTube / Meta AI ads*
*Prepared for Gomeh Saias · June 16, 2026*

---

## Mandate

Create top-tier, value-centric content and search ads that are discoverable by
both modern AI answer-engines (GEO) and classic search (SEO), targeting the
**high-intent keywords the correct audience is actually searching** for a given
product or service — while genuinely educating. It plans, executes, measures
its own progress on a schedule, detects growth vs. decline, adjusts the plan
from the data, and implements (with approval on spend and publishing).

Data spine: Semrush (keywords, traffic, competitors), Google Search Console
(real rankings/impressions/clicks), GA4 / Shopify analytics (traffic +
conversions), Ahrefs (backlinks + AI-search/brand-radar), and the ad platforms
(Google, Bing, Pinterest, YouTube, Meta). Works for products (Shopify stores)
and services (e.g., marketingthatworks.co).

---

## Part 1 — Connectors & data sources

| Need | Connector | Status |
|---|---|---|
| Keywords, intent, competitors, site audit | **Semrush** | ✅ connected |
| AI-search / answer-engine visibility, backlinks | **Ahrefs** | 1-click |
| Real ranking/impression/click data | **Google Search Console** | in stack (gsc_*) |
| Traffic + conversions | **GA4** (ga_*) / **Shopify analytics** | in stack |
| Search ads | **Google Ads** (gads_*) | in stack |
| Bing/Pinterest search ads | **Microsoft Ads** (msads_*) / Pinterest | msads in stack; Pinterest via API |
| Video | **YouTube** (Google) | Google scope |
| Meta AI/Advantage+ | **Meta Ads** | in stack |
| Cross-platform normalized feed | **Supermetrics / Windsor.ai** | 1-click (optional) |

---

## Part 2 — The comprehensive skill list

### A. Research & Intelligence
1. **Keyword Research & Intent Clustering** — pull Semrush keywords for a product/service, classify by intent (informational / commercial / transactional), cluster into topics, score by volume × difficulty × commercial intent.
2. **High-Intent Opportunity Finder** — surface keywords with strong buying intent AND winnable difficulty; the money keywords.
3. **Audience-Question Mining** — what the *correct* audience actually asks: People-Also-Ask, Semrush questions, forum/Reddit/AI-prompt patterns. The basis for value-centric content.
4. **GEO / Answer-Engine Audit** — how the brand shows up in AI Overviews / LLM answers (Ahrefs brand radar); gaps to close so AI recommends it.
5. **SERP & Competitor Analysis** — who ranks, what format wins, content gaps competitors own.
6. **Site / Technical Audit** — Semrush site audit + GSC coverage; fix-list for crawlability, speed, schema.
7. **Baseline Snapshot** — capture starting rankings, traffic, conversions per target topic (the yardstick for progress).
8. **Seasonality & Trend Watch** — when demand spikes for each topic; time content/ads to it.

### B. Strategy & Planning
9. **Topic-Cluster / Pillar Strategy** — pillar pages + supporting cluster content mapped to the keyword clusters.
10. **Keyword→Funnel Mapping** — assign each cluster to a funnel stage (educate → consider → buy) so content and ads match intent.
11. **Content Calendar** — prioritized, scheduled, dependency-aware.
12. **Search-Ads Campaign Strategy** — structure (campaigns/ad groups), match types, budget framing, bid strategy, per platform.
13. **Audience & Negative-Keyword Definition** — who to reach, who to exclude (protects spend).
14. **Channel Mix Recommendation** — where a given product/service should compete (Google vs. Pinterest vs. YouTube vs. Meta AI) and why.

### C. Content Creation (value-centric, AI-searchable)
15. **SEO Content Brief** — target keyword + cluster, the audience questions to answer, structure, word count, internal links, schema.
16. **Long-Form Content Draft** — answer-first, E-E-A-T, genuinely educational AND conversion-aware; written to be cited by AI and rank in Google.
17. **GEO-Formatted Content** — concise extractable answers, structured data, FAQ blocks, citations — built for AI answer engines.
18. **Landing / Product / Service Page Copy** — high-intent keyword aligned, conversion-structured.
19. **Metadata & Schema** — titles, descriptions, FAQ/Product/Article schema.
20. **Multi-Channel Repurposing** — YouTube titles/descriptions/tags, Pinterest pin copy + keywords, from the same source content.
21. **Brand-Voice Adherence** — every asset matches the brand's learned voice (per-brand, like the admin agent's per-inbox voice).

### D. Ads Execution
22. **Search Ad Copy Generation** — RSAs/headlines/descriptions from high-intent keywords, intent-matched.
23. **Google Ads Campaign Build** — campaigns, ad groups, keywords, RSAs (gads_*), gated for approval.
24. **Bing / Pinterest / YouTube / Meta Campaign Build** — same pattern per platform.
25. **Negative-Keyword Management** — ongoing, to stop wasted spend.
26. **Landing-Page ↔ Ad Alignment** — message match between ad and destination (Quality Score + conversion).
27. **Budget Pacing & Bid Adjustment** — propose changes from performance (gated).

### E. Measurement & Self-Adjusting Feedback Loop *(the core differentiator)*
28. **Scheduled Performance Analysis** — recurring pull of GSC rankings/clicks, GA4/Shopify conversions, Semrush position tracking, ad performance.
29. **Progress Tracking** — store snapshots over time; compute growth/decline per topic, page, keyword, campaign.
30. **Decay & Cannibalization Detection** — pages losing ground, or competing with each other.
31. **Plan Adjustment** — translate the data into concrete changes: refresh declining content, double down on winners, kill losing ad spend, re-target.
32. **ROAS / ROI per Keyword & Campaign** — what's actually making money.
33. **A/B Test Tracking** — title/copy/landing tests, called by data.
34. **Implementation** — execute the adjustments (publish updates, change bids, add negatives) — spend/publish gated for approval.
35. **Performance Report** — periodic, plain-English, with wins/declines and next-period plan.

### F. Cross-Agent Collaboration *(for the coming Meta/TikTok agent)*
36. **Insight Publishing** — write high-intent keywords, winning audience questions, and proven angles to a shared brief the Discovery/Social-ads agent reads (so TikTok/Meta hooks are informed by real search intent).
37. **Creative-Performance Consumption** — read back which hooks/creatives the social agent found winning, to inform content and search ad copy.

### G. Governance (inherited — see Part 3)
38. Approval gating on spend & publishing · proactivity · clarify-before-bulk · action-confirmation · grounding · memory · lessons · cataloging.

---

## Part 3 — Every admin-agent training carries over (the kernel)

This agent is the **same kernel, new role + tools**. Nothing built for admin is
lost — explicitly:

| Admin training | How it applies to Search & Ads |
|---|---|
| **Approval gating (money)** | No ad spend, bid change, or publish without your tap. |
| **Action confirmation** | Never claim a ranking improved or content published unless GSC/the platform confirms it. *Critical for SEO honesty.* |
| **Grounding / no fabrication** | Only report metrics a tool returned; never invent traffic or rankings. |
| **Proactivity / data-foresight** | gather data → act → suggest next step → offer it. |
| **Clarify-before-bulk** | Confirm scope before launching campaigns or publishing batches. |
| **Voice rules** | Per-brand brand voice, learned from approved content (like per-inbox voice). |
| **Deny-to-rule + cross-agent lessons** | Corrections persist and generalizable ones reach all agents. |
| **Working memory + records** | Campaigns, content pieces, snapshots as structured records. |
| **Document registry + catalog** | Every content asset/brief cataloged for reuse by any agent. |
| **Scheduled scans (3x meeting-scan pattern)** | Reused as the scheduled performance-analysis cadence. |
| **Deadlines & calendar** | Content calendar + publish/campaign dates. |
| **WhatsApp interface (text/voice/files/approvals inline, reply-quote)** | Same control surface. |
| **Usage/cost logging + prompt caching + model routing** | Same; heavy analysis → Opus, drafting → Sonnet, classify → Haiku. |
| **Auto-migration, thread-safety, ordered queue, retries** | Inherited infrastructure. |

The build is **kernel extraction → Search role config → Search tool pack →
Search skills**. The behavioral DNA is not rewritten.

---

## Part 4 — The self-analysis loop (how it tracks its own progress)

On a schedule (recommend weekly for SEO, daily for active ad campaigns):
1. **Snapshot** current rankings (GSC), traffic/conversions (GA4/Shopify), ad performance — store with a timestamp.
2. **Compare** to the prior snapshot and the baseline → per-topic/page/keyword/campaign growth or decline.
3. **Diagnose** — what improved, what decayed, what's wasting spend, what's cannibalizing.
4. **Adjust the plan** — concrete changes (refresh this post, scale this ad group, add these negatives, re-target this audience).
5. **Surface + implement** — report the plan with the data behind it; execute on approval; log the change so the next snapshot measures its effect.

This closes the loop: the agent measures the consequence of its own last set of changes, so it compounds rather than guessing.

---

## Part 5 — Cross-agent collaboration (Search ↔ Meta/TikTok)

A shared **Insight Bus** — a table both agents read and write, scoped by
project/brand:
- The **Search agent posts**: high-intent keywords, the audience's real
  questions, proven messaging angles, seasonal timing.
- The **Discovery/Social agent reads** those to build hooks grounded in real
  search intent (not guesses), and **posts back** which creatives/hooks won.
- The Search agent consumes that to sharpen content and search-ad copy.

Plus the existing shared layers already make collaboration safe: one document
catalog (shared assets), shared lessons (shared judgment), and per-brand voice
(consistent messaging across agents). When you build the Meta/TikTok agent, it
plugs into the same bus — no rework.

---

## Part 6 — WhatsApp: one agent per number

- The incoming webhook payload contains `value.metadata.phone_number_id`, so a
  **single shared webhook can route each message to the correct agent by the
  number it arrived on.** One number → one agent is clean and supported.
- **Today's test number** is a single, limited number (pre-approved recipients
  only) — it cleanly runs **one** agent. Run the admin agent on it while testing.
- **To give each agent its own number**, register additional real phone numbers
  to your WhatsApp Business Account (each verified, each with its own
  `phone_number_id`). With per-agent self-hosting, each deployment simply holds
  its own number's credentials.
- **Interim option** if you don't want multiple numbers yet: one number, and you
  prefix a message ("seo: …", "ads: …") to address an agent — workable but
  clunkier than separate numbers. Recommended end state is one number per agent.

Routing is the easy part; provisioning real numbers is the only gating step.

---

## Part 7 — Recommended build order

1. **Kernel extraction** (prerequisite — do once, admin agent proves it).
2. **Connect** Ahrefs + confirm GSC/GA4/Google Ads scopes; pick Pinterest path.
3. **Search role config** + tool pack (Semrush, GSC, GA4, Ahrefs, Google/Bing/Meta Ads).
4. **Adopt + customize the existing marketing skills** (`seo-audit`,
   `competitive-brief`, `content-creation`, `performance-report`,
   `campaign-plan`) as the starting playbooks — don't write from scratch.
5. **Add the measurement loop** (snapshots + adjust + implement) — the part that
   makes it self-improving.
6. **Add the Insight Bus** so it's ready for the Meta/TikTok agent.
7. **Provision its WhatsApp number** when ready to operate it live.

The data layer is bought (Semrush/Ahrefs/GSC/Google Ads), the behavioral layer
is inherited (the admin kernel), and several role playbooks already exist as
marketing skills. The net new work is the Search tool pack, the self-analysis
loop, and the cross-agent bus.
