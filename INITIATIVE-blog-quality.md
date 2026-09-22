# INITIATIVE — The model writes the article; the code inspects it; an editor looks

> **THIS IS A PLAN, NOT A STATE FILE.** Written 2026-09-18 at commit `87b57ce`,
> the day the email maker produced a recreation the owner called "great".
> `BUILD-STATE.md` remains the record of what exists.
>
> It is the email pattern (`INITIATIVE-email-recreation.md` §0, §7) applied to
> the blog, on top of what the blog system already has — the keyword map, the
> plan, the claims, the pictures, the Shopify publish arm. §1 is the facts with
> `file:line`; if they hold, the plan holds. §3 is the phases. §5 is the one
> decision that is the owner's: when an article goes live with nobody looking.
>
> **BUILT 2026-09-18..22. Phases 0–5 are done** (`5568a7e`, `a0e3612`,
> `9aa94d3`, `525973d`, `061d4f5`): the hand-made standard, `app/articles.py`
> (pattern + SERP brief + story + writer + checks + render + judge + loop),
> `scripts/article_once.py`, the skill seam, §5's go-live condition,
> `app/exemplars.py` (approvals raise the standard, the owner's notes are
> remembered), and both cards. **Open, and the owner's:** turning the
> unattended live push on for a tenant (the condition and the wiring exist;
> nothing is enabled), and a deploy run against a plan keyword where the SERP
> comes from Semrush rather than a URL typed by hand.

---

## 0. The rule, carried over

The email work of 2026-09-12..18 settled how creative output is made here:

> **The model makes the thing, whole, with everything in view. The code
> inspects invariants only. A judge with eyes says whether it would ship. The
> owner's approvals and notes are the standard, not rules of ours.**

For the email the "reference" was another brand's email. For an article the
reference is **what already ranks for the keyword** — the pages a searcher
sees before ours — plus the brand's own exemplar article once one exists. The
system prompt has told the drafter for months to "answer a search query better
than anything already ranking for it" (`skill_pack.py:4818`), and the drafter
has never once been shown what ranks. That is the blog's version of the token
chain: a model asked to beat a thing it cannot see.

The owner's ask, 2026-09-18: *"similar quality results in blogs that can be
pushed automatically to Shopify while keeping the plan keywords etc. in mind,
based on the system we have today."* Three clauses, three sections below: the
quality loop (§3), the automatic push (§5), the plan (§4).

**Amended 2026-09-18, on the owner's note:** *"we don't necessarily want to
always have a reference but it would be nice to have one; but with blogs there
is usually a certain layout that stays consistent between blogs."* So the
reference splits in three, and only one of them is per article — see §0a.

---

## 0a. The reference, for a blog, is three things — and the layout is not one of them per piece

An email is a one-off; its reference gives it its whole design. A blog is a
series; its layout is the brand's and stays put while the content changes.
So what the email called "the reference" becomes:

| | What it is | How often | Where it comes from | What it decides |
|---|---|---|---|---|
| **The pattern** | The brand's standing article layout, in words: the blocks an article of this brand carries and in what order — a key-takeaways box after the answer, H2 sections with one picture each, a comparison table where two things are compared, a product callout card, the FAQ, a closing CTA band; the devices (a pull quote, a "what you'll need" list, a note box) and how each is drawn inside the store's theme | **once per brand**, standing | a reference article URL the owner likes, read once into the pattern (optional); else the pattern the maker declares for the first article, filed when the owner approves it; the hand-made article of Phase 0 is Baci's | the layout of every article; the judge's "one pattern" check across articles |
| **The SERP brief** | What ranks for this keyword: the rivals' structure, depth, the questions they answer and miss, the media they carry, the length that wins | **per article** | the rivals already on file (`keywords.latest_serp`), fetched and read | the story, the length, the sections that must exist |
| **An approach reference** | An article the owner likes for its *way in* — "X vs Y, compared", "the buyer's mistakes", "a season's guide" — read into a brief of concept and argument, like the email's brief | **optional, per article** | a URL pasted on the plan item or the card | the story's shape; never the layout |

Three consequences:

1. **A brand with no reference of any kind still gets a well-laid-out
   article** — the pattern has a default the maker declares (the email's
   DESIGNLESS path), and it becomes the brand's after the first approval.
2. **Consistency is a check, not a hope.** The maker emits its blocks marked
   (`<!-- block: takeaways -->` … `<!-- /block -->`), so `articles.check` can
   see that the pattern's blocks are present in the pattern's order, and the
   judge is asked whether this article is laid out like the last approved one.
   That is the article's version of the email's "one system", held across
   pieces rather than within one.
3. **The theme owns the chrome.** Title, date, author, featured image and the
   page around the body are Shopify's; the pattern lives inside the body as
   HTML that the theme's CSS will style — so every device the pattern names
   is drawn in the store's faces and colours, read from the theme, and
   rendered for the judge in a template that carries them.

The Brand tab gets one card, **Article layout**: the pattern in words, the
reference it was read from (if any), the exemplar article, and *Use this
layout for every article* — the same room the email's designs have.

---

## 1. What exists today (`file:line`, checked 2026-09-18)

The blog is further along than the email was when its rebuild started. Most of
the plumbing is real; the centre is thin.

| # | What | Where | State |
|---|---|---|---|
| 1 | The skill: one article against one keyword; needs voice + positioning; a ban list is constitutive; refuses with no claim in scope | `skill_pack.py:5227` `_run_blog_article`, registration at `:5834` | built, runs on the plan |
| 2 | The draft: ONE model call, `max_tokens=3000`, a system prompt (answer-first, H1 = title, H2/H3, ground in claims, `<!--IMAGE-->` markers) and a prompt of rules block + claims + entity + real questions + internal links + angle + objections | `:5043` `_draft_article_live`, `:4818` `_ARTICLE_SYSTEM`, `:4859` `_article_prompt` | built; **3,000 tokens caps the article at ~1,800 words**; no exemplar; no view of what ranks |
| 3 | The keyword map: phrases with volume, tier, intent, cluster, role (pillar/support), priority; scored; a recommended mix | `keywords.py:279` `targets`, `:302` `cluster`, `:466` `score`, `:2404` `mix_recommendation` | built |
| 4 | The plan: the planner fills the horizon from the score and the mix, with cadence and rest days per system | `planner.py:75` `_cadence`, `:193` THE MIX | built |
| 5 | The questions people search, harvested into the map, answered as H3s and marked up as FAQPage | `_run_blog_article` ~`:5266`, `sites.py:629` `faqs_from_body`, `:749` `compose_jsonld` | built |
| 6 | Internal links only to pages that resolve | `sites.py:790` `verify_links` | built |
| 7 | What ranks: the top 10 URLs per keyword from Semrush, stored and refreshed | `keywords.py:2586` `latest_serp`, `:2601` `rivals_refresh` | built, **never handed to the drafter** (no reader in `skill_pack.py`) |
| 8 | Pictures: the shared ladder — a proven photograph of the subject first, else drawn; body markers filled; the hero approved with the article | `creative.py:829` `pick`, `:960` `generate`, `skill_pack.py:4956` `place_images` | built |
| 9 | Truth: claims cited or the draft is blocked; the ban list word-bounded; coherence (one artifact, one subject) | `validator.py:93` `check`, `:71` `_banned`, `coherence.py:252` `review` | built |
| 10 | Publish: Shopify `create_article` (draft unless `published` is true), the blog ensured, the URL written back, staged vs published distinguished | `shopify_seo.py:546`, `:565`; `approvals.py:940`, `:967`, `:972`; `keywords.py:2966`, `:3017` | built; **every article lands as a Shopify DRAFT** |
| 11 | Unattended: on the `auto` rung a cleared article's pending ship is approved by the system through the same executor, marked `auto` | `approvals.py:346` `ship_unattended` | built — but see 10: it stages a draft, it does not make a page public |
| 12 | Measurement: GSC/Semrush readings per phrase, progress against a control, the monthly report | `keywords.py:375`, `:466` | built |

What is **missing**, against the email loop:

- **No eyes.** Nothing renders the article and looks at it. The email has
  `shots` + `judge`; the article has a validator and a title check.
- **No standard.** No exemplar article; the drafter's only model of "good" is
  the system prompt.
- **No reference.** The SERP is on file (#7) and unread.
- **No story first.** The drafter gets questions and claims and writes in one
  breath; the argument (what the reader wants, what we know, what we say
  first) is never decided before the prose.
- **No length to be thorough.** 3,000 output tokens.
- **No craft invariants on the body.** Word count against what ranks, the
  keyword in the H1 and the first paragraph, a meta description that fits,
  every image with alt, headings that are questions where people asked
  questions — none checked.
- **Draft, not live.** "Pushed automatically" is not true today even on `auto`.

---

## 2. The trace — what a good article writer does by hand, and what does it here

| # | By hand | In the system |
|---|---|---|
| 0 | Opens the keyword on the plan: the phrase, its role (pillar/support), its cluster, its intent, the questions people ask. | Exists: `keywords.targets`, the plan item's `keyword`/`role`/`cluster`, `semrush_questions`. |
| 1 | **Reads what ranks.** Opens the top 3–5 pages: their structure (H2s), their depth (words), what they answer, what they miss, what media they carry. Writes a brief: *to beat these, the article must answer X first, cover A/B/C, be about N words, carry a table for D.* | **NEW** `articles.brief(tenant, keyword)` — fetch the top 3–5 rival URLs already on file (`latest_serp`), extract headings/word count/questions/media per page, one model call → a brief in words (what to answer first, sections that must exist, the gap nobody fills, target length, the media that would help). Stored on the keyword row. |
| 2 | Pulls the brand's material: the claims that bear on this keyword, the entities, the pictures, the voice, the ban list, the objections. | Exists: `ctx.bundle` (claims in scope, rules block, entity, objections). |
| 3 | **Decides the story**: the reader's question, the answer in one sentence, the sections in order, which claim supports which section, what will NOT be claimed. | **NEW** `articles.story(brief, bundle)` — the email's `decide_story`, for an article: beats = answer-first / sections / proof per section / the objection handled / the ask; each rests on a claim or on the SERP brief; nothing rests on air. |
| 4 | Chooses the pictures: the subject's own photograph for the hero, a picture where the text needs one. | Exists: `creative.pick`, `place_images`, the drawn fallback. |
| 5 | **Writes the article** from the story, to the length the SERP demands, with the H1 as the title, the meta description, the FAQ. | Exists as one call; **rewritten** to take the brief + story + the brand's exemplar + a length budget; `max_tokens` raised (streamed). Output contract: `Title:` / `Meta:` / HTML. |
| 6 | **Checks the invariants**: claims cited, ban list, links resolve, keyword in H1 + first paragraph, meta ≤ 155 chars, alt on every image, no invented facts (truth pass with implication), no cannibalising an article already targeting this phrase. | Exists in part (`validator`, `verify_links`, `_targets_keyword`); **NEW** `articles.check` for the rest — the only closed list. |
| 7 | **Renders it and looks**: the article in the brand's theme, on a phone and a desktop — wall of text? headings that earn their place? the picture where it helps? | **NEW** `articles.shoot` — the body wrapped in a template that carries the store's own faces and colours (`brand_theme`), shot by `shots.shoot` at 640 and 1280. |
| 8 | **Judges as an editor and an SEO**: *would you publish this?* Does the first paragraph answer the query; does each H2 earn its place; is it more useful than the pages that rank (the brief is in view); is a claim stated that the material does not hold. | **NEW** `articles.judge` — the email's judge prompt shape: the brief, the story, the shot, the words; `would_publish`, findings with `do` that the writer can make; the truth pass separate. |
| 9 | **Edits** to the findings, looking at the render; ≤ 2 rounds; best kept. | Same loop as `recreate.run`. |
| 10 | **Publishes** — or stages for a look — and records the URL so the rank readings have a page to read. | Exists (`create_article`, `mark_published`); **the `published` flag becomes a decision** (§5). |
| 11 | **Learns**: an approved article becomes the brand's exemplar; the owner's notes are remembered. | **NEW**, shared with the email (the approved-as-exemplar seam is one function for both). |

---

## 3. Phases

**Phase 0 — the standard, by hand (½ day, first).** As with the email: one
article for Baci, written by hand in this chat with the SERP open and the
material open, for one keyword on the plan (a support term with a real
question behind it). Owner judges it. If it is not better than what ranks,
nothing below is worth building. It becomes `docs/recreations/<tenant>-<slug>.html`,
the first exemplar, **and Baci's pattern** — its blocks, in its order, are
what every Baci article is laid out in until the owner files another.

**Phase 1 — the pattern, the reference and the story (1½ days).**
- `articles.pattern(tenant)`: the brand's standing layout — read once from a
  reference URL when the owner pastes one (`articles.read_pattern(url)`,
  one call, text + a screenshot), else the default declared by the maker;
  filed on the brand (`KbBrand.visual["article_pattern"]`, the way the
  email's standing design is) when the owner approves an article in it.
- `articles.brief`: read the rivals on file into a brief (headings, depth,
  gaps, media, length). No vision needed — pages are text; one call.
- `articles.approach(url)` (optional): a pasted article read into a brief of
  its concept and argument, for the story only.
- `articles.story`: the argument before the prose, resting on claims and the
  brief; contrast beats framed; nothing implied that is untrue.
- The drafter receives the pattern + brief + story + exemplar + length;
  streamed; the output contract `Title:` / `Meta:` / HTML with the pattern's
  blocks marked (`<!-- block: … -->`), drawn in the store's faces and colours.
- The runner: `scripts/article_once.py --tenant --store --keyword` — the
  looking loop on a laptop, like `recreate_once.py`, writing `brief.json`,
  `story.json`, `article.html`, `article.png`, `findings.json`.

**Phase 2 — the invariants and the eyes (1 day).**
- `articles.check`: keyword in H1 and first paragraph; meta present and ≤ 155;
  alt on every image; length within the brief's band; no second article on
  the plan already targeting this phrase (cannibalisation); **the pattern's
  blocks present, in its order**; links resolve (exists); claims cited
  (exists); ban list (exists); truth by implication (the email's pass, reused).
- `articles.shoot` + `articles.judge` + the edit loop; best round kept; an
  unjudged article is never called publishable. The judge sees the last
  approved article beside this one and answers `one_pattern` as well as
  `would_publish`.
- The judge's `do` must be makeable in the body; a `do` that needs a new
  photograph names a picture already in the piece or says cut.

**Phase 3 — the plan and the push (½ day).**
- The plan item carries `keyword`, `role`, `cluster`, `angle` today; it also
  carries the **story's hook** back, so the plan reads as a list of articles
  and not phrases.
- `published` on `create_article` follows §5.
- `mark_published` is written only when the page is live (exists); the URL
  the rank readings read is the live one.

**Phase 4 — learning (½ day).** `exemplars.approved(tenant, kind)` — one seam
for email and article: an approved output becomes the brand's exemplar of
that kind; the writer and the judge see the last approved one beside the
reference. The owner's note on the card is a finding and is remembered per
brand ("what the owner has said about this brand's articles").

**Phase 5 — the cards (1 day).** The article's page shows the brief (what
ranks, in a line each), the story (the beats), the render beside the top
rival's screenshot, the findings, the cost line from `Usage`, and the two
buttons: *Publish* / *Not this one*. The Brand tab's **Article layout** card
shows the pattern in words, its reference (if any), the exemplar, and *Use
this layout for every article*; pasting a URL there reads a new pattern.

Total: about five days, of which the first half-day is the one that decides
whether the rest happens.

---

## 4. Keeping the plan's keywords in mind

Nothing changes in what the plan decides; everything changes in what the
article does with it.

- The keyword stays the aim: it is in the H1 and the first paragraph, and
  `_targets_keyword` (`skill_pack.py` — token coverage, not stuffing) stays
  the test.
- The **role** decides the article's shape: a pillar covers the cluster and
  links down; a support answers one question and links up to the pillar
  (exists: `links` in the prompt). The brief and the story are told the role.
- The **cluster's other phrases** become the H2s the SERP brief says are
  missing, so one article can rank for its siblings without a second article
  cannibalising it — and `articles.check` refuses a second article on a
  phrase the plan already covers.
- The **questions** harvested for the phrase are the FAQ, as today.
- The **measurement** closes the loop as today (GSC readings against the
  live URL); the new fact recorded per article is the brief's target length
  and the rival it was written to beat, so a later refresh knows what it was
  competing with.

---

## 5. The push: when an article goes live with nobody looking

Today: every article lands as a Shopify draft (`shopify_seo.py:565`), even
on `auto` (`ship_unattended` approves the *stage*). "Pushed automatically" is
therefore a decision, not a bug fix, and it is the owner's. The proposal:

- On the **`auto`** rung, an article is created with `published: true` **only
  when** every invariant passes, the judge answered `would_publish: true`, the
  truth pass found nothing, and a picture is in the piece. Anything short of
  that lands as a draft with a pending approval, as now.
- On **`approve_exceptions`** and **`shadow`**, nothing changes: a write needs
  a person.
- A page that went live unattended is marked `auto` (exists) and appears on
  the Review tab under *went live without a look* for seven days, with
  *Unpublish* one press away — the undo the email cannot have.

The owner said on 2026-09-02 that cleared pushes are blog only; this keeps
that scope and adds the one condition that was missing: *cleared* means the
judge looked.

---

## 6. What this is not

- Not a new renderer: the article is HTML in the store's own blog theme; the
  theme's faces and colours are the design. No baking, no bespoke layout —
  structure, typography inside the body, pictures where they help.
- Not a second publishing path: `approvals._execute` stays the only writer to
  Shopify; §5 changes one flag it passes.
- Not a rule set about "good writing": the standard is the exemplar and the
  SERP brief; the invariants are truth, coverage, links, alt, length band,
  cannibalisation.

---

## 7. Open, for the owner

1. §5 — go live unattended on `auto` when the judge says publish? (Recommended: yes, with the seven-day *went live without a look* list.)
2. Phase 0 — which Baci keyword for the hand-made article? (Recommended: a support term on the plan with a real question behind it and a rival page that is beatable.)
3. Length — do we let the SERP set it (recommended) or cap it per brand?
