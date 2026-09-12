# INITIATIVE — Recreate a reference email's DESIGN with the brand's own content, assets and colours

> **THIS IS A PLAN, NOT A STATE FILE.** Written 2026-09-11 at commit `b4c0383`.
> `BUILD-STATE.md` remains the record of what exists.
>
> **Phases 0–5 are built and Phase 6 is wired (2026-09-11). The live proof and the acceptance are the owner's; Phase 7 is not started.**
>
> §2 is a list of facts with `file:line`, each checkable in about a minute. If
> they still hold, the plan holds. If one has changed, the phase resting on it
> needs re-reading before it is built.

---

## 0. The rule this plan REVERSES — read this paragraph twice before coding

On 2026-09-11 the structure library shipped under this line, written into
`app/email_render.py:73-80` and `RUNBOOK.md` §6d:

> *"a look changes arrangement only — colours and typefaces stay the theme's."*

**That was the wrong reading of what the owner asked for.** The owner, later
the same day, on seeing the result:

> *"it is currently making the same email with slight layout differences, but
> we want the creatives, the styling and font formats etc — it should be
> similar to recreating [the reference] with our content and dynamic assets,
> potentially in colors that make more sense for each brand."*

So the new line is:

> **A reference contributes its whole DESIGN — layout, type system, colour
> system, image treatment, spacing, button and footer style — read in words
> and recreated. The BRAND contributes the palette that fills the design's
> colour roles, the typefaces when it has them on file, the pictures, the
> logo and every word. The reference's copy, pictures, markup and hex values
> never reach the email — that half of the old rule stands, because that is
> the half that is someone else's property. Design language is not.**

The trap named in memory `creative-references-two-roles` applies: when a rule
is reversed, restate the reversed rule before touching code, or the old one
comes back through habit. It is restated above. `look`, `look_of`, `LOOK`
and every test asserting "no colour but the theme's" are the old rule in
code; §4 says what happens to each.

---

## 1. What this is for, in the owner's words

1. Take a reference email (a Really Good Emails page the owner chose) and
   **recreate its design** — *"the creatives, the styling and font formats"*.
2. Fill it with **our content** (the drafter's copy, the account's approved
   claims) and **our dynamic assets** (the account's own photographs, product
   images, logo — or a picture drawn from them when none fits).
3. In **colours that make sense for each brand** — the reference's colour
   *roles* (which sections are dark, where the accent goes, how much
   contrast) kept; the brand's own palette poured into them.
4. Brand rules still respected at the moment of use (2026-09-11, unchanged).
5. Every approved design joins the collective library for reuse with
   different copy (2026-09-11, unchanged — but the library now keeps the
   DESIGN, not just the block order).

And the complaint underneath all of it: *"the code is so messy and the AI
stopped understanding what I'm trying to do."* §3 answers that with a shape,
not with another knob.

---

## 2. Verified facts this plan rests on (read 2026-09-11 at `b4c0383`)

### 2.1 The reader is told not to see style, and then cannot see it anyway
- `app/email_structures.py:554-576` — `_READ` asks for a block sequence, six
  arrangement axes, and says: *"Describe the arrangement only — never a
  colour, a typeface or a picture's content."*
- `app/email_structures.py:111-127` — `look_of` keeps only the six `LOOK`
  keys; anything volunteered about colour or type is discarded.
- `app/email_structures.py:593-599` — `read_swipe` fetches the swipe's
  screenshot and sends the WHOLE PNG as ONE image block. Nothing resizes or
  tiles it, and nothing pins the vision model's input contract for
  `creative_review` (`imagegen.input_image`, `:618-640`, pins 1536px for the
  OpenAI door only).
- **Measured today:** the RGE `og:image` IS the full-length email —
  `dishpatch-persiana-lamb-chops.png` is **680 × 2857**,
  `flavors-kept-coming-back.png` is **680 × 4543**. RGE also serves a mobile
  render at `/emails/mobile/<slug>.png` (375 wide).
- **The contract, pinned from the docs in Phase 0 (`app/llm.py`,
  `IMAGE_TIERS` … `image_seen_as`; URLs beside the code):** Claude sees
  28-px patches (⌈w/28⌉ × ⌈h/28⌉ visual tokens); each model has a tier with
  a long-edge AND a token limit — **standard 1568 px / 1568 tokens** for
  models before 4.7, **high-resolution 2576 px / 4784 tokens** for Claude 4.7
  and later; a picture over either is scaled down, aspect kept, silently —
  unless the image block sets `transformations: {"oversized_image":
  "error"}`, which refuses the request naming the largest size that fits.
  Hard limits apart from the tier: 8000 px a side, 10 MB base64 per image,
  2000 px a side when a request carries more than 20 image blocks; JPEG/PNG/
  GIF/WebP. The reviewer (`config.CREATIVE_REVIEW_MODEL`, default
  `claude-sonnet-4-6`) is standard tier, so the 680 × 4543 screenshot is
  looked at as **235 × 1568** (on a high-resolution model, 386 × 2576 — still
  57 %). A 14 px line of body type arrives 4.8 px tall. **The reader is
  structurally blind to the very details the owner asked for: weights, case,
  tracking, button borders, rules, kickers.** This is defect one and it is
  independent of the prompt.
- All eight Claude-vision call sites (`creative.py` ×6, `kernel.py`,
  `ops_jobs.py`, plus this one) send raw bytes and none checks the contract;
  only the swipe reader sends a tall picture, so it alone suffers.

### 2.2 The renderer can paint exactly one email
- `app/email_render.py:81-90` — `LOOK`: six axes, 2–4 values each. That is
  the entire range of variation a structure can express.
- `:110` `_PAD` three densities; `:183` headline 38/26 px; `:246` body 16 px;
  `:270` button padding; `:384` kicker 13 px uppercase; `:534-566` ONE header
  (logo left, view-in-browser right, centred uppercase nav); `:568-598` ONE
  footer (centred, muted, on the surface); `:632-657` ONE frame — a white
  card with a 1 px border and a radius on a grey page.
- Every painter reads colour by the seven role names in `_DEFAULT["colors"]`
  (`:49-52`: bg, surface, text, muted, accent, accent_text, border). There is
  no dark surface, no tint, no secondary — a "dark hero, cream body" reference
  has nowhere to go.
- `scripts/test_a_structure_is_how_not_what.py:371-379` asserts no hex outside
  the theme appears under any look, and that only the overlay hero may set
  white. **This guard encodes the reversed rule.** Its principle survives
  (colours come from the brand, never from the reference); its object moves
  from *theme* to *palette* (§4, Phase 4).

### 2.3 The brand's design inputs are too thin to recreate anything
- `app/brand_theme.py:149-152` — `_from_canva` keeps **`cols[0]` only** as
  the accent; every other colour in the brand kit is thrown away.
- The theme is one accent, two font stacks, a logo, a nav, a footer. No type
  classification (is the heading a high-contrast serif or a grotesque?), no
  tonal range, nothing derived from the brand's own photography.
- Assets carry `subject` OBJECT/SURFACE/SCENE/LOGO (`app/kb.py:2860`) and
  `kind`; `creative.focused` (`app/creative.py:2255`) cuts a product out of a
  lifestyle shot; `creative.generate` (`:960`) draws and judges;
  `hero_for_campaign(draw_first=)` (`:65`) already draws the hero first when
  the brand can draw. The assets exist; nothing maps them to *what a design
  slot needs* (a square packshot, a wide lifestyle, a cut-out on colour).

### 2.4 Where the campaign run touches all of this — one place
- `app/skill_pack.py:3609-3615` — inside `_build()` in the campaign skill:
  `_look = ((craft.get("structure") or {}).get("profile") or {}).get("look")`
  then `email_render.render(theme, blocks, ..., look=_look)`. **This is the
  one seam.** Guard `the_campaign_run_passes_the_look` (test `:395-415`) is
  an AST check that `look=` is fed from the structure.
- `:2833` `_assemble_blocks` is the rules gate on the drafter's blocks
  (images only from governed sources, products only from offered keys,
  stat/quote must cite, one CTA, unknown types dropped). It stays. `:2119`
  `CAMPAIGN_FORMATS` restricts blocks by letter/designed. `:433-453`
  `email_structures.brief` says the look in words to the drafter.
- `app/approvals.py:468` — an approved ESP push files `Output.shape` (block
  types, `db.py:470`) as an approved structure. The library grows by
  sequence; it does not yet keep how the email LOOKED.

### 2.5 What the console can and cannot show
- `app/admin_ui.py:4036` — emails preview in a sandboxed `srcdoc` iframe;
  `:6585` `_structures_card` shows swipes beside their structures with
  approve/reject and "Read its look". **There is no HTML→image capability in
  the deployment** (no headless browser in `requirements.txt`), so a
  rendered preview cannot be sent to a vision judge as a picture. A
  side-by-side on the Brand tab — reference screenshot beside a live preview
  of the recreation — is the review surface that exists.

### 2.6 The rules that do not move
- Copy never comes from a reference: `craft.leaks` at filing
  (`email_structures.py:170`) and at use (`:311`); the ban list on the
  structure's notes (`:321`); the drafted email through every gate
  (`_assemble_blocks`, validator, coherence).
- A swipe is `rights=REFERENCE`, `kind="email_swipe"`, never on a visual
  board (`:64-77`, guard `a_swipe_never_enters_the_picture_reads`).
- A structure carries no tenant (`db.py:1058-1080`), named by what it does.
- Random unless designated (`:383-425`).

---

## 3. The shape — `reference × brand × content → email`

Today the run computes `theme + blocks + six switches → HTML`. Every
reference collapses to the six switches, which is why every email is the
house template. The replacement separates three things that today are
tangled inside the renderer:

```
DESIGN   (from the reference, in words — technique, shared library)
  frame · header · type system · colour ROLES · sections[] (layout, alignment,
  background role, image treatment, slots) · cta style · dividers · footer ·
  imagery direction
BRAND    (from the account, owner-approved on the Brand tab)
  palette of ROLES (page, surface, ink, muted, accent, accent_ink, dark,
  dark_ink, tint, tint_ink, border, secondary) · type roles (display,
  heading, body, kicker — the brand's faces when on file) · logo · assets by
  kind (logo, packshot, cutout, lifestyle, scene, pattern) · footer facts
CONTENT  (from the drafter and the KB — unchanged gates)
  copy per slot · products · claims · the hero
                        ↓
render_design(design, brand, content) → email-safe HTML
```

**Why roles, not hex.** The reference says *"hero on the dark surface with
light type; product grid on the surface; the ask is a filled accent button;
footer on dark."* Baci's dark is the navy from its kit; Eien's is a forest
green derived from its accent. Same design, two brands, each in its own
colours — which is what *"colors that make more sense for each brand"*
means, made mechanical. A hex value in a design is a defect the normaliser
drops and names.

**Why the family may be the brand's but the FORMAT is the reference's.** Type
*format* — the scale, weights, case, tracking, alignment, line-height,
italics, the serif/sans pairing — always comes from the design. The type
*family* comes from the brand when it has one on file (Canva kit, Shopify
typography), otherwise the design's classification ("high-contrast serif
display over a grotesque body") picks an email-safe stack. Decision 1 in §5
is whether a reference may ever override a brand face (default: no).

**Why this is not another knob.** `LOOK` was a knob on a fixed renderer; a
seventh knob would be a seventh way to produce the house template. A design
is a document the renderer *executes*, and the vocabulary is closed only so
that every value has a painter — the test in Phase 1 walks the schema and
refuses a value nothing draws. Adding a layout is one painter + one schema
entry, and the prompt, the validator, the RUNBOOK table and that test all
derive from the schema (the owner's rule: generate it or delete it).

**What stays legally clean.** Words in, words out. A design is a description
of decisions, the same thing a designer writes down when briefed "make it
feel like this one". Never the reference's copy (the read has no free-text
copy field; notes go through `craft.leaks` and a quoted-copy check), never
its pictures (a swipe is REFERENCE by construction), never its markup (we
read a screenshot, never fetch the email's HTML), never its hex (dropped at
normalise, guarded at render).

---

## 4. The ships, in order

Each ship follows §4 of `WALKTHROUGH-PROMPT.md`: reproduce first, a sabotage
guard that prints `[ caught ]`, `./scripts/ship.sh`, verify on `/health`.

### Phase 0 — Turn the diagnosis into checks — DONE 2026-09-11
Reproduced, and each cause made a ledger entry before anything is fixed.
The ship gate refuses a red suite, so the checks take the
`test_open_defects` shape: an entry PASSES while the defect stands and goes
red — naming the phase — the moment it is fixed. Proven by mutation (a
reader that tiles flipped two entries to FIXED).

- `scripts/test_a_reference_is_recreated.py` — six open entries:
  1. **the reader cannot see the type** — a 680×4543 swipe read through the
     real `read_swipe` sends one whole image block; `llm.image_seen_as`
     computes what the reviewer looks at (235×1568). Plus: the prompt says
     "never a colour, a typeface"; no block sets the refusal switch. → Phase 3
  2. **the renderer paints one email** — every combination of every `LOOK`
     axis (576, walked from the vocabulary, never listed) shares one frame
     and one footer; reaches no colour beyond the seven roles; the ink is
     only ever a ground behind the overlay hero's photograph. → Phase 4
  3. **the brand kit's colours are discarded** — a four-colour kit proposes
     `colors.accent` from the first colour and nothing else. → Phase 2
  Plus the contract itself asserted against the docs' worked examples (A4
  → 924×1307; 1920×1080 → 1456×819; the 2000×1500 row where the docs' table
  and their own reference implementation differ by one pixel at a .5 tie —
  both recorded).
- The contract lives in **`app/llm.py`**, not `email_design.py` as first
  written: the Claude seam owns it, as `imagegen.py` owns OpenAI's and
  `gemini_images.py` Google's; Phase 3 imports it.
- The live reproduction (the Ayoh structure on Baci, HTML beside the
  reference) needs the production database and stays the owner's; the
  offline pair — identical content through the house default and through
  every toggle flipped — was rendered and sent to the owner 2026-09-11.

### Phase 1 — The design vocabulary and its schema — DONE 2026-09-11 (`app/email_design.py`)
- `SCHEMA`: one declarative structure, 44 fields across `frame`, `header`,
  `type`, `palette`, `cta`, `dividers`, `footer`, `imagery` and the `SECTION`
  fields (used twice: `defaults` per kind, and `sections[]`). Every field:
  values, a default among them, one line of meaning. `KINDS` (9), `SLOTS`
  (13; `products`/`image` take a count 1–6), `GROUNDS` (the five roles a
  design may name) ⊂ `ROLES` (the twelve a brand supplies). No free-text
  field exists — a design cannot carry a word.
- `normalize(raw) → (design, dropped)`: complete (every field filled),
  idempotent, and every raw thing that did not make it is a sentence with
  its reason — a hex is "a design never names a colour", a link "never
  carries a link", a face or an unknown layout "not a value the renderer
  draws (…) — default used", a bad slot or count said by index.
- `house(look=None)`: today's renderer as a design (card, mark left, links
  inline, editorial serif over grotesque, kicker in the accent, filled soft
  button, thin rule, centred footer), the six look axes folded in — proven
  over all 576 combinations, each axis shown to move the design. Tenant-free.
- `sequence_of(design)`: the library's identity derived from sections' slots,
  only blocks `email_render._BLOCKS` builds (a hero section = one hero block
  + its ask). `summary(design)`: one line for a card. `fields()`: the one
  walk the generator, the prompt (Phase 3) and the painter test (Phase 4)
  share.
- `db.EmailStructure.design` (JSON); `email_structures.backfill_designs()`
  at boot fills empty designs with `house(profile["look"])`, idempotent;
  `file_structure(design=)` normalises, stores, returns `dropped`; a re-read
  carries a design forward with approval untouched; `_row` exposes it.
- RUNBOOK §6d: the vocabulary table is GENERATED between markers by
  `scripts/gen_email_design_doc.py` (`--check` byte-compares; the suite runs
  it). The old look table stays until Phase 4 retires `LOOK`.
- Ledger: the seventh entry — "no painter registry (44 fields filed, none
  drawn)" — holds Phase 4 open. Suite
  `scripts/test_a_design_is_words_the_renderer_can_draw.py`; six guards, all
  `[ caught ]`: `a_hex_never_enters_a_design`,
  `a_design_is_complete_after_normalise`, `the_house_is_todays_renderer`,
  `an_old_look_moves_the_design`, `the_vocabulary_table_is_generated`,
  `a_structure_without_a_design_takes_the_house_at_boot`.
- Deviations from the plan as first written: the migration is a boot-time
  backfill (`db.init_db` → `backfill_designs`), not a one-off script; the
  house has per-KIND `defaults` and an empty `sections` list — a reference
  read yields a concrete order, the house leaves the order to the drafter,
  and a renderer reads `defaults[kind]` when a block has no section.

### Phase 2 — The brand's design inputs — DONE 2026-09-11 (`app/palette.py`, `brand_theme.py`, Brand tab)
- **`app/palette.py`** — the arithmetic (WCAG luminance and contrast, the
  readable ink on a ground, mix, saturation), `fill(given, colors) →
  (palette, how)`: every one of the twelve roles filled — a role a source
  gave, else the older theme colour that already IS that role (`from
  colors.<field>`, resolved to that field's source), else `computed: <one
  stated rule>` (the dark ground is the ink, deepened when the ink is
  light; the tint is the accent at eight per cent over the surface; every
  `_ink` is the readable one on its ground; the secondary is the muted
  colour standing in). `findings(palette)`: every ground/ink pair below
  4.5:1 (3:1 for the muted line and for the accent as a text link) named
  with its ratio. `rank_kit(hexes)`: the first colour is the accent, the
  darkest the dark ground (and the ink when near black), the lightest the
  page, a second light the tint, the most saturated remainder the
  secondary — one stated rule each; what no role takes is returned to be
  NAMED, never lost. `from_pictures(blobs)`: the most frequent real colour
  across the packshots → secondary, the most frequent light one → tint;
  white/black/grey never; a light colour is held to a gentler saturation bar
  than a mid-tone (a bone is not a grey).
- **`email_render._DEFAULT["palette"]`** = `palette.fill({}, _DEFAULT
  ["colors"])` — the default palette and a brand's computed roles are ONE
  rule in one place; `_theme()` merges `palette` like `colors`. No painter
  reads it until Phase 4 (the ledger's seventh entry holds that open).
- **`brand_theme`**: `_from_canva` places EVERY kit colour under a role by
  `rank_kit` and names the unplaced under `partial`; `_from_shopify`
  proposes `palette.accent`/`accent_ink` (primary) and `palette.secondary`
  (secondary); `_from_site` proposes `palette.accent`; a FOURTH source,
  `_from_pictures` (seam `packshot_blobs`), lowest precedence, names its fix
  when there are no photographs. `_fill_palette` in `derive` fills and
  checks; provenance per role is the source's own name, `<field's source> —
  as <role>`, `hand-set`, or `computed: <rule>`; `findings` ride the
  proposal and `status()`. **Absence survives:** with nothing derived, no
  palette is written — the renderer's default applies at render. `approve`
  refuses a role that is not a `#hex` by name, keeps every given/edited
  role and recomputes the computed ones around them (an edited dark ground
  takes a fresh readable ink), reports findings in its note; edited roles
  carry forward across re-derives like every hand-set field.
- **Brand tab** (`admin_ui._palette_rows`, inside the approve form — act
  where you report): the twelve roles as swatches, proposed beside live,
  where each came from, an input per role; contrast findings for the
  proposal and the live palette; the faces on file (or "none on file — the
  design's classification chooses", Decision 1); pictures counted by the
  kind of slot they fit, an empty kind with its fix. The approve route reads
  `palette.<role>` for every role in `email_design.ROLES`.
- **`email_design.assets_for(tenant, kind, aspect)` / `assets_by_kind`**:
  publishable pictures by imagery kind — packshots for packshot slots (a
  cut-out is made at fill time, never stored), photographs then later store
  images for lifestyle/flat-lay, surfaces for texture; a reference pin
  fills nothing; an empty kind says its fix.
- Ledger: entry 3 CLOSED — and the first cut of that entry counted
  `colors.*` only, so it did not flip when the fix landed; it now measures
  the claim (every kit colour reaches a role or is named unplaced). Six
  entries open. Suite `scripts/test_a_brand_fills_the_roles.py`; seven
  guards, all `[ caught ]`: `a_brand_kit_colour_is_not_discarded`,
  `a_computed_role_is_labelled`, `a_contrast_failure_is_a_finding`,
  `an_edited_role_is_refilled_around` (went UNDETECTED on the first cut —
  the test edited navy to near-black and both took white ink; sharpened),
  `a_role_that_is_not_a_colour_is_refused`,
  `the_default_palette_is_the_one_rule`, `a_reference_pin_fills_no_slot`.
- Not done, by decision: type roles as new theme fields — the brand's
  `font.heading`/`font.body` already are the faces; Phase 4 maps
  display/heading → heading and body/kicker → body, the classification
  choosing only when a face is absent (Decision 1 default).

### Phase 3 — The reader, with eyes — DONE 2026-09-11 (`email_design.read`; `_READ` and the first reader deleted)
- **Strips** (`strips`): the screenshot cut to the reviewer's tier —
  `llm.image_tier(config.CREATIVE_REVIEW_MODEL)` decides 1568 or 2576 —
  with 120 px overlap, a wide picture narrowed to the edge first, lossless
  PNG; every image block carries `transformations: {"oversized_image":
  "error"}` so a strip that would be downscaled is refused by the API and
  said. A contact sheet (`contact_sheet`) of the whole at the tier's size.
  The phone render (`mobile_url`: `…/emails/<slug>.png` → `…/emails/mobile/
  <slug>.png`) fetched when the gallery serves it, skipped and said when
  not. Never more than 20 image blocks in a request (`MAX_IMAGE_BLOCKS`).
- **Three passes, prompts derived from `SCHEMA`** (`prompt_global`,
  `prompt_strip`, `prompt_critique` — every field, its values and meaning,
  from `fields()`; the suite proves nothing outside the schema is asked
  for): A, the whole design off the contact sheet + the top strip (+ the
  phone render); B, the sections in each strip with `continued` for one
  cut by the edge; C, the strips again with the assembled design — "list
  every visible property this gets wrong or misses" — answered as a JSON
  patch, applied ONCE (`apply_patch`, global groups field by field,
  sections by index, out-of-range ignored, off-vocabulary dropped and said).
- `stitch`: a strip's first section marked `continued` is the previous
  strip's last, kept once, slots the union. `normalize` on the whole; every
  drop — the reading's and the critique's — filed on the structure as
  `profile["read"]["dropped"]` with `tier, edge, strips, calls, mobile,
  critiqued`.
- **Refusals by name**: no sections found ("the picture may not be an
  email"); a pass that did not run (the model's own error); over the image
  limit (before sending); a reading of a non-reference picture.
  **The reference's copy never lands**: `quoted_copy` — three or more words
  inside quotation marks in the notes — drops the notes and says so;
  `craft.leaks` still runs at filing.
- **The live renderer keeps working**: `look_of_design` derives the old
  six-axis look from the design (overlay/split/bleed/contained; poster or
  display → display; leading → density; any section on `page` → bands;
  arrow/underline → link, full, pill, else block; grid2/grid3) and it is
  filed as `profile["look"]` until Phase 4 executes the design itself.
  `sequence_for_library` derives the library's identity from the slots,
  falling back to the kinds. A re-read of an existing sequence carries the
  design AND clean notes forward, approval untouched.
- **The card** (`_structures_card`): "design: <summary> · read in N calls
  from M strip(s) on the <tier> tier · with the phone render · critiqued
  once", the drops and the sections under `<details>`, **Read its design**
  on any structure with a screenshot; a structure never read says "design
  not read — the house design". The reference-beside-a-live-preview lands
  with Phase 4 (`render_design` is what would draw it) and the card says so.
- Ledger: entries 1 and 2 CLOSED by measurement (every image the reader
  sends fits the reviewer's tier; every block carries the refusal switch;
  no request over 20 images; the prompt names every schema field, "never a
  colour, a typeface" gone; a tall screenshot read in ≥3 strips, calls =
  strips + 2). Four entries open, all Phase 4's. Suite
  `scripts/test_the_reader_has_eyes.py`; seven guards, all `[ caught ]`:
  `a_strip_is_cut_to_the_reviewers_tier`, `a_strip_refuses_to_be_downscaled`,
  `the_prompt_is_the_schema`, `a_continued_section_is_one_section`,
  `the_critique_is_applied`, `quoted_copy_never_reaches_the_notes`,
  `a_reading_with_no_sections_is_refused`. Phase 0's
  `a_fixed_defect_moves_the_ledger` went STALE when the old prompt was
  deleted (the anchors ratchet caught it) and is retargeted at a fake
  `render_design`.
- **NOT proven live.** Every suite stubs `llm.ask`. The `transformations`
  field on an image block rides through the SDK as a plain dict; if the
  live API refuses it the read fails loudly with the API's words — that is
  the designed failure, and the first real press tells. Owner's move: swipe
  one real RGE email, read it, and read the card.

### Phase 4 — The renderer executes a design — DONE 2026-09-11 (`email_render.render_design`)
- **`render_design(design, theme, blocks, *, preheader, webview)`.** The
  drafter's blocks are grouped into SECTIONS (`group_sections`: hero,
  products, proof, offer, closing, ps are their own; a heading starts a
  run — intro, then feature/editorial by turns; text/list/divider/ask join
  the run; an ask alone is the closing). Each section takes its kind's
  `defaults`, overlaid by the next unconsumed entry of that kind in the
  design's concrete order (`_spec_for`), so a reference's hero treatment
  reaches the hero and its grid the products, in the order it had them.
- **One style context per section** (`_context`): the theme with its
  colours replaced by the section's GROUND — the ground as surface/page,
  the ink that reads on it (`palette.INK_OF`), a muted line and a border
  mixed from the two, the accent kept — plus the design's type and ask,
  the section's treatment, and the old look derived for the painters that
  still read it. **The thirteen block painters are the same ones**, handed
  that context: a quote on the dark ground is painted by the quote painter
  in the dark ground's ink. Nothing is written twice.
- **What the painters learned**, every addition inert at the house values
  so `render` is byte-identical: the type system (`_type`: four scales,
  weights, upper/title case, tracking, alignment, body size, leading,
  four kicker styles, italic sub); the ask (`_cta` with a spec: filled,
  outline, underline, arrow, full; square/soft/pill; three sizes; case;
  alignment; **inverted on the accent ground** — the first cut painted
  accent on accent, caught by the suite); dividers (thin/thick/dotted/
  ornament/none); the header (`_header_design`: mark left or centred, nav
  none/inline/below, case, rule); the footer (`_footer_design`: ground,
  alignment, socials as words/chips/none, rule — CAN-SPAM in every one);
  hero treatments (contained inside the margins, bleed, rounded, circle,
  framed, duotone on the tint) and split-right; product pictures rounded/
  circle and cut to the slot's aspect through the CDN's own convention
  (`_sized(url, w, aspect)` → `_600x480_crop_center`; the 88 px thumbnail
  is a square crop now, not a squash). Layouts as a registry (`LAYOUTS`:
  stack, split-*, grid2/3, collage, overlay, columns — words dealt left and
  right — band, letter). Frame: page ground, card or flat, 600/640/680,
  radius, keyline. Faces (`_faces`): the brand's own wins; the class
  chooses a stack only when none is on file, and links its Google face
  (Decision 5) with the stack as fallback.
- **`render(theme, blocks, look=)` is NOT a wrapper — a deviation from the
  plan as written.** Its positional bands (every second run between
  headings, three cells counted by the suite) and its six toggles are the
  OLD behaviour, pinned honestly by the suites that pin them; imitating
  them through a section renderer would have been a second fixed template.
  It stays untouched until Phase 6 switches the campaign run, then it,
  `LOOK`, `look_of` and `profile["look"]` are retired together.
- **The card** (`_design_preview` + `email_design.preview_html/
  preview_blocks`): a read design is executed with THIS brand's live theme
  (or its proposal, said) on its own hero photograph, its own three
  products and plainly-sample copy, in a sandboxed frame beside the
  reference screenshot — "would this recreate it?" answered before approval.
  A brand with no theme is told what to do first.
- `NOT_DRAWN_YET` names the five fields the renderer does not draw (imagery
  ×3 and the palette's mood/accent_use), each with its phase — and the
  suite proves the list hides nothing that draws.
- Ledger: the "no painter registry" entry CLOSED; the three legacy-renderer
  entries fold into ONE open entry, measured by AST on the campaign run's
  call: it renders through `email_render.render`, not `render_design` →
  Phase 6. Suite `scripts/test_a_design_is_executed.py`: 96 non-default
  values walked from the schema, every one changes the email and keeps the
  copy and the footer; every hex ∈ palette ∪ the renderer's own mixes; the
  same design through two palettes = same words, same structure, different
  colours. Six guards, all `[ caught ]`: `a_ground_takes_its_own_ink`,
  `a_designs_ground_is_the_brands_colour`, `the_brands_face_wins`,
  `a_concrete_order_reaches_its_kind`, `canspam_survives_every_design`,
  `not_drawn_yet_hides_nothing_drawn`.

### Phase 5 — Content fits the design — DONE 2026-09-11 (`email_design.brief` + `fill`)
- **`brief(design)`**: the drafter's words for a design with a concrete
  order — each section in order with where it sits, every slot with its
  LIMIT: the headline's word budget by scale (poster 4 / display 6 / large
  8 / modest 10) and its case, kicker ≤ 3 words, sub one line, body 40–90
  words, list 3–5, cta 2–4 words, a quote "an APPROVED claim, verbatim, or
  leave the slot and the section drops", a picture "from the brand's own
  library; you write its alt line only". `''` for a design with no order —
  the drafter composes as before. `email_structures.brief` delegates to it
  when the structure's design has sections, the notes beneath; the old
  order-and-shape brief otherwise.
- **`fill(tenant, design, blocks, note)`**: after `_assemble_blocks` (the
  rules gate, unchanged), the design's picture slots filled from the
  brand's own publishable library by the imagery kind the design names
  for that section (`imagery.hero` / `.product` / `.feature`) and the
  aspect the slot wants (cut through the CDN at render). A hero without a
  picture takes one; a section with an `image:n` slot gets `n` picture
  blocks before its words; a picture is used once; a reference pin never;
  **a slot nothing fills is named on the run with its fix and the section
  keeps its words** — never a silent text-only email. A picture is added,
  never a word. **Drawing when nothing fits is NOT wired** (the plan's
  `creative.generate` path) — the miss says so; a follow-up.
- **The renderer**: an `image` block (`_image`: treatment, aspect, live
  alt; the filler is its only writer — the drafter cannot produce one,
  `_assemble_blocks` drops it), `split-left/right` for a section with a
  picture (`_lay_split`), `collage` two across (`_lay_collage`). A picture
  never starts a run — it joins the words it was filled for. **A run of
  words is one FAMILY** (`WORDS` = intro/feature/editorial): the grouping
  names runs by position, the reader by judgment, and they meet on the
  family in order — without this the reader's "feature" never met the
  drafter's first run.
- **The library keeps designs**: `Output.meta["design"]` and
  `["structure_id"]` ride every send (the same meta bag as `shape`; no new
  column; read off `ArtifactBody.meta`); `file_from_output` files the
  design with the shape — approved sends teach the library how they
  looked. Same sequence = same structure still (the design carried forward
  is the latest); a design signature of its own is Phase 7's.
- Suite `scripts/test_content_fits_the_design.py`; six guards, all
  `[ caught ]`: `a_headline_is_briefed_with_its_budget`,
  `a_picture_slot_is_filled_by_its_kind`, `a_slot_nothing_fills_is_said`,
  `a_picture_joins_the_words_it_was_filled_for`,
  `an_approved_send_files_its_design`, `a_run_of_words_is_one_family`.

### Phase 6 — Wire, prove live, accept — WIRED 2026-09-11; the live proof and the acceptance are the owner's
- **The one seam** (`skill_pack.py`, `_build()`): `_design =
  _structure.get("design") or _ed.house()`; `blocks, _filled = _ed.fill(
  ctx.tenant, _design, blocks, note=ctx.note)`; `email_render.render_design
  (_design, theme, blocks, …)`. Nothing else in the campaign function
  moved. The old `look=` read is gone from the run.
- **The run note says what happened, whole**: `recreated from <name>:
  <summary>; grounds → page #… surface #… dark #… tint #… accent #…;
  faces: heading the brand's own / chosen by the design's class, body …;
  pictures filled n, not filled m` — and every unfilled slot as its own
  note with the fix.
- **The claim, computed**: the AST check in the structure suite and the
  ledger — the campaign run's ONE render call is `render_design`, its
  design a NAME assigned from the picked structure, and the fixed template
  called nowhere in the run. Guard
  `the_campaign_run_executes_the_structures_design` (retargeted from the
  look it once guarded) `[ caught ]`. **The ledger reads 0 open.**
- **Not done here, and not claimable from this machine**: the first live
  read of a real RGE screenshot (every suite stubs the model); the six-
  email acceptance (three references × Baci and Eien on the Brand tab,
  beside their references — "same designer, different brand"). Both are
  the owner's press. The legacy `render`, `LOOK`, `look_of`,
  `look_of_design` and `profile["look"]` still exist: `render` serves the
  Brand tab's theme sample and the suites that pin the old behaviour;
  retiring them is a cleanup ship of its own, listed under Phase 7.

### The first top-down review — 2026-09-11, `animal-facts-pistol-shrimp-quiz`
The owner asked for the whole chain reviewed on one real gallery email.
Run locally with the real code at every step; the three vision passes
answered by hand from the strips (no key on this machine), in the reader's
own prompts, fed through the real `read()`. What it found, each fixed and
guarded in the same ship:

- **The reader's sections and the drafter's runs did not share a grouping
  rule.** The reference's opening card is ONE section — kicker, headline,
  byline, then the picture, body, ask — while the drafter's hero block is
  placement only and its words a run of their own, so the design's next
  section landed on the hero's copy and everything after was one place
  off. Now: a hero section that carries word slots absorbs the run after
  it (`_HERO_WORDS`); the slot ORDER is honoured inside a section
  (`ordered` — headline over the picture when the reference had it so); a
  kicker and its headline are one section (a heading starts a run only
  when the run already holds words); a `divider` is the section boundary
  the drafter never had, and the brief says to write one; the last
  headingless run of words is the closing; a group takes the next section
  of its family that can HOLD what it carries (`_holds` — a closing of
  words steps past the reference's logo band); a section stepped past is
  reported as unreached.
- **The rules gate trimmed the drafter's blocks at 12, in silence** — the
  closing and its ask fell off the end. `BLOCKS_CAP` = 24, and a trim is
  said with the count and the cap.
- **Two asks.** A design that asks twice was briefed for a second cta the
  one-ask rule then dropped. Now the brief says "the same ask again — the
  one link, repeated" and `fill` repeats the one ask into a later ask slot
  (the craft doctrine: one destination, repeated).
- **The structure was named by the gallery page's title** — the reference
  email's own headline and brand, in a library that carries no words. Named
  by `summary(design)` now, as a run-filed structure is.
- **The vocabulary was too narrow for three common newsletter devices** the
  reader saw and could not say: sections as a stack of rounded CARDS on the
  page (`frame.container: cards`), a kicker on a filled PILL (`type.kicker:
  pill`), and LIST styles — pill buttons two across for a quiz, arrow rows
  with rules for further reading, plain (`section.list`). Added; the painter
  walk covered them the moment they existed (45 fields).
- Small: the brief said "a underline button"; a centred closing centres its
  ask; in a stack of cards a boundary divider paints no rule under nothing.
- **Seen and left, named:** the header's patterned strip and the arrow disc
  beside the underlined link are not in the vocabulary; the hero took the
  product packshot from the hero ladder rather than the design's
  `imagery.hero` (lifestyle) — the ladder is the governed choice and the
  design's kind is a preference, to be reconciled in Phase 7.
- Before the vocabulary grew, the recreation held the structure and about
  half the style; after, it is recognisably the reference in Baci's colours
  with the brand's own photograph and copy. Ten guards, all `[ caught ]`.

### The pictures lead, the brand supports — 2026-09-12
The owner, on the card's preview: *"it shows that we are not really doing it
well … One of the things that decide an email's aesthetic is not the brand
per se but the colors of the images we choose so that it all looks
intentional. But our emails will always default to the same thing and our
preview will never provide images that actually show us what the email
should look like."* Then the order: *"the main media assets should be chosen
based on the email we are trying to recreate and then the colors lean first
on the themes in the photos … then apply our branding to support that."*
And: *"once you validate photos that meta information should stick with
them in the knowledgebase"*; *"we will want different emails about the same
entities to use different order / choice of photos which will affect the
color palette of the email."*

**What was true.** `preview_blocks` took the first lifestyle asset and the
first three products every time and rendered a fixed house-shaped sample,
not the design's sections; `fill` chose pictures by recency; `render_design`
resolved every role through the one approved palette, so every email had the
same grounds whatever picture it carried; the reader named one picture kind
per family; the campaign recorded only the ladder's hero on the ledger.

**What changed (all with guards):**
- **The reading stays on the picture** — `KbAsset.reading`: colours (dominant,
  light, mid, dark, key, warmth) and size/aspect by arithmetic; the KIND by
  the filing when it says (packshot tag, surface, logo), else by ONE vision
  look, kept on the row and never re-read; the owner's hand
  (`/admin/picture_kind`) outranks both. `read_pictures` — the Brand tab's
  control — reads the unread; the tab shows every picture with its reading.
  A reference pin is never read.
- **The reader counts every photograph** — `section.image_kind` (inherit |
  the six kinds | `mark`), pass B told to count each photograph and to read
  a logo band as a mark. A mark slot takes the brand's logo, never a photo.
- **One chooser** (`choose_media`) for every slot: the campaign's entities
  first (brand-wide when it names none), the design's kind per section,
  not seen lately by this list (the Output's `media_ids`, now every picture
  the email carried), fit to the design's key and coherence with the hero,
  ties by the run's seed. Every step said on the run.
- **The palette from the photos** (`palette.from_photos`): the hero's light
  tone is the page, white warmed to it the surface, its soft tone the tint,
  its deepest the dark, its saturated mid the secondary; on a dark key the
  deepest tone is the page. The accent is the brand's by construction (the
  suite reads the source to hold it); the ink the brand's while it reads at
  4.5:1, else computed; every ground measured; a tone that will not carry
  its ink replaced and said. `theme["keyed_grounds"]` (Brand tab checkbox)
  turns the lead off. A drawn hero stands; a library hero gives way to the
  chooser's pick and says so.
- **The preview is the run** — `preview_html(entity_key)` runs the same
  chooser and palette on an entity you pick on the card, on the design's
  own blocks; the card shows the pictures, the steps and the derivation.
- **Two sends, same layout, same entity, different pictures, different
  palette** — a check in the suite, not a sentence.
- Defaults chosen (the owner's three questions): accent, mark and faces
  always the brand's, the ink while it reads; complementary slots entity
  first then brand-wide, said; packshots on white surface cards over the
  photo-led page. Fields now say who reads them (`_F.by`): the painter walk
  covers painter fields with the renderer and filler fields with the chooser.

### Phase 7 — Learn, and tidy (later, not this initiative)
Structures carry outcomes per brand (`results.py` joining `Output.meta
["design"]` to performance); a design signature of its own in the library
(today same sequence = same structure); a "hand" authoring surface; a
picture-to-picture fidelity judge once a screenshot capability exists;
drawing a picture through `creative.generate` when no owned one fits a
slot; retiring the legacy `render`/`LOOK`/`look_of`/`profile["look"]` and
rewriting the two suites that pin the old renderer in design terms.

---

## 5. Decisions the owner makes (defaults stated; the build proceeds on them)

1. **Brand face vs reference classification.** Default: the brand's typeface
   wins when one is on file; the reference's classification chooses only
   when none is. Alternative: a per-brand switch "let the reference choose
   the faces" for brands whose kit has no real type identity.
2. **Product photography as a palette source.** Default: yes — proposed
   roles from the brand's own packshots, owner approves like every other
   derived field. Alternative: kit + Shopify + site only.
3. **The mobile render.** Default: read it (it is free, it says how sections
   stack). Alternative: desktop only.
4. **A screenshot service** (hosted HTML→PNG) for a picture-to-picture
   fidelity judge. Default: not now — the side-by-side on the Brand tab and
   the words-critique pass are the loop; revisit after the six-email
   acceptance.
5. **Web fonts in email.** Default: on — a Google Fonts link with the stack
   fallback (renders in Apple Mail/iOS, falls back in Gmail/Outlook).
   Alternative: stacks only.
6. **The legal line restated** (§0/§3): design language yes; copy, pictures,
   markup, hex no. Confirm, or narrow.

---

## 6. What stays true whatever is chosen

- A reference contributes WORDS. The words now describe the whole design.
- The brand's rules bind at use (`usable_for`) and the drafted email goes
  through every gate it went through before. A design cannot put a word on
  the page.
- Random unless designated; the library is shared and carries no account.
- Nothing invented: a role no source fills is computed and labelled, or
  absent and said; a slot nothing fills is named on the run.
- One seam in the campaign skill. One vocabulary. One schema that generates
  the prompt, the validator, the docs table and the painter test.
- Every model contract pinned from its docs and checked before the call.

---

## 7. Next thread — paste this

> You are continuing the gomehagent build at
> `/Users/gomehsaias/Documents/gomehagent-build` (deployed at
> https://assistant-web-zm2d.onrender.com). Read the memory notes
> `gomehagent-email-structures` (its LAST section first — the owner's
> correction) and `gomehagent-walkthrough-handoff`, then
> `WALKTHROUGH-PROMPT.md` §4 (the protocol) and §5, then
> **`INITIATIVE-email-design.md` in full, §0 twice.**
>
> **The rule was reversed on 2026-09-11.** Restate it in your first message,
> in your own words, before opening a file: the reference's whole design is
> recreated; the brand supplies palette, faces, pictures, logo and words;
> the reference's copy, pictures, markup and hex never reach the email.
>
> **First move:** `python3 scripts/test_a_reference_is_recreated.py` — it
> reads `0 defect(s) still open`: every entry the initiative opened, closed by
> measurement. Then re-check `INITIATIVE-email-design.md` §2 against the tree
> (`git log -1`, then each `file:line`). Phases 0–5 shipped and Phase 6 is
> wired (2026-09-11). What is left is the OWNER's: swipe one real RGE email,
> read the card, open the preview beside the reference, run one campaign on
> the structure and read the run note; then the six-email acceptance. After
> that, Phase 7's list — drawing when no picture fits, a design signature in
> the library, retiring the legacy renderer. When a phase lands, its ledger
> entries go red — replace them with that phase's own checks in the same
> commit, and check first that the entry MEASURES THE NEWS: Phase 2's entry
> counted the wrong fields and did not flip until it was rewritten.
>
> Then the phases in order. Under §4 unchanged: reproduce first; every fix
> ships a sabotage guard that prints `[ caught ]`; ship via
> `./scripts/ship.sh "<subject>" <body-file>` with the subject on the body's
> first line; never edit the tree while it runs; `python3 scripts/register.py
> --write` before shipping whenever a guard or a caller moved; verify on
> `/health`; regenerate RUNBOOK §6d from the schema, never by hand; write the
> memory note before the thread ends.
>
> The campaign skill changes at ONE call site (`skill_pack.py` `_build()`,
> the `email_render.render(...)` call). If you find yourself editing it
> anywhere else, stop and say why.
