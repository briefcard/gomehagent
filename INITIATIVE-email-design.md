# INITIATIVE — Recreate a reference email's DESIGN with the brand's own content, assets and colours

> **THIS IS A PLAN, NOT A STATE FILE.** Written 2026-09-11 at commit `b4c0383`.
> `BUILD-STATE.md` remains the record of what exists.
>
> **Phases 0, 1 and 2 are built (2026-09-11). Phases 3–7 are not.**
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

### Phase 3 — The reader, with eyes (`email_design.read`, replaces `_READ`)
- **Tile the screenshot** with Pillow: 680-wide strips cut to the REVIEWER'S
  tier — `llm.image_tier(config.CREATIVE_REVIEW_MODEL)` decides 1568 or 2576
  — with ~120 px overlap; the mobile render (375 wide) as one more strip when
  RGE serves it. Every strip checked with `llm.image_fits` before send and
  marked `transformations: llm.OVERSIZED_IMAGE_ERROR`, so a strip that would
  be downscaled is refused by the API and said, never degraded in silence.
  Under 20 image blocks per request, or the 2000 px rule bites.
- **Pass A — global** (top strip + a contact sheet of all strips scaled to
  fit one 1568 image): frame, header, type system, palette mood and roles,
  cta, dividers, footer, imagery direction.
- **Pass B — per strip**: the sections in that strip with layout, align, bg
  role, pad, image treatment, aspect, slots. Stitched top-down; the
  overlap de-duplicated by the section the model names as "continued".
- **Pass C — the critique**: the strips again, plus the assembled design in
  words: *"list every visible design property this description gets wrong
  or misses"* → one corrective merge. (The ad judge's one-corrective-redraft
  pattern, `creative._judged`, applied to reading.) Without an HTML→image
  capability this is the fidelity loop that exists; §5 Decision 4 names the
  screenshot-service option for a picture-to-picture judge later.
- Output through `normalize`; dropped items listed on the card; filed
  `review="proposed"` with `design`, `sequence` (derived from
  `sections[].kind` so the old library reads still work) and `notes`
  (through `craft.leaks` + a no-quoted-copy check).
- **The card shows the reference BESIDE a live preview of the recreation**,
  rendered through THIS brand's palette/type/logo with its three real
  products, an owned hero photograph and a fixed sample copy — so "would
  this recreate it?" is answered before approval. Approve / Read again /
  Reject. "Read its look" becomes "Read its design".
- Model calls filed in toolcalls like every other call; the read's cost
  said on the card (three passes per swipe).
- Guards: `a_strip_never_exceeds_the_pinned_edge`;
  `a_reference_hex_never_survives_the_read`;
  `a_references_copy_never_reaches_the_structure`.

### Phase 4 — The renderer executes a design (`email_render.render_design`)
The biggest ship. Section painters keyed by `layout`, every visual property
read from the design with the schema default, colours resolved ONLY through
`brand.palette[role]`, faces through `brand.type` or the classification's
stack.
- `render_design(design, brand, content, *, preheader, webview) -> html`.
- `render(theme, blocks, *, look=)` becomes `render_design(house(theme, look),
  brand_from_theme(theme), content_from_blocks(blocks))` — a thin wrapper, so
  **every existing suite passes unchanged**. That is the proof the seam is
  clean; if a legacy test moves, the wrapper is wrong, not the test.
- Email-safe by construction, as today: tables, inline styles, bulletproof
  buttons, `role="presentation"`, alt text, live text under every image,
  plus what the new range needs — MSO conditionals and VML for section
  backgrounds and background images in Outlook, `color-scheme` meta and
  dark-mode-safe backgrounds, widths from the design (600/640/680), a
  Google Fonts `<link>` + `@import` with the stack fallback when the brand's
  face or the classification names one (Decision 5).
- Image slots: Shopify CDN filename convention extended from `_{w}x` to
  `_{w}x{h}_crop_center` for aspect (`_sized`, `:129`) — the same reasons
  it uses filenames, not `?width=` (Omnisend's entity-mangling).
- `scripts/test_email_design_render.py`: every schema value renders and
  differs from its default (the moved guard from
  `test_a_structure_is_how_not_what.py:361-368`); **no hex in the output
  outside `brand.palette` ∪ {#ffffff, #000000 for scrims}** (the moved
  guard from `:371-379` — the principle kept, the object moved from theme
  to palette); every layout keeps live text under images; the footer's
  CAN-SPAM line survives every design.
- Retire `LOOK`, `_look`, `look_of`, `profile["look"]`, the `look=` kwarg
  (after the wrapper proves nothing reads them — `python3 scripts/register.py
  --write`, then the AST guard confirms no reader).

### Phase 5 — Content fits the design (`email_design.brief` + `fill`)
- `brief(design)` replaces `email_structures.brief` for the drafter: the
  slots in words WITH LIMITS — a poster headline is ≤ 5 words, a kicker ≤ 3,
  a split section wants a 2-line sub, a grid3 needs names that stand alone,
  a quote slot needs an approved claim or the section drops. The drafter's
  `blocks` contract stays; the prompt lists the design's sections as the
  order and the slots as the shape (today's `_es.brief` at `:433` is the
  hook, `_craft_brief` at `:2394` the caller).
- `_assemble_blocks` (`:2833`) unchanged as the RULES gate. After it,
  `fill(design, blocks, brand, ents, assets, note)` maps validated blocks
  into sections/slots and fills the IMAGE slots by kind+aspect from the
  brand's own library: packshot for product cards, lifestyle/scene for a
  hero, a `focused` cut-out for "product on colour"; when nothing fits and
  `creative.drawable`, draws one through `creative.generate` judged like a
  set and approved WITH the email (`d3bf631` path, `hero_for_campaign
  (draw_first=)` already does this for the hero). A slot it cannot fill
  degrades that section to its text form AND is named on the run — never a
  silent text-only email (DEFECTS §2.66).
- `Output.design` (JSON) filed with every send; `file_from_output` files the
  DESIGN into the library, once per distinct design signature, named by
  what it does — the library keeps how approved emails looked, not only
  their order.
- Guards: `an_unfillable_slot_is_said`; `a_drawn_slot_is_approved_with_the_email`.

### Phase 6 — Wire, prove live, accept
- The one seam: `skill_pack.py:3609-3615` reads
  `craft["structure"]["design"]` and calls `render_design`. The AST guard
  `the_campaign_run_passes_the_look` becomes
  `the_campaign_run_executes_the_structures_design`, same shape (a NAME fed
  from the structure; `None` fails it). Zero other changes to the campaign
  function — if a second change is needed in `skill_pack.py`, stop and ask
  why.
- The run note says what happened, whole: *"recreated from <name>: dark
  editorial, 7 sections; palette page #… surface #… dark #… accent #… (dark
  computed); faces: brand heading, classified body; slots filled 9/10, drawn
  1; not filled: proof quote — no approved claim fits."*
- **First live read** on a real RGE screenshot — this has NEVER run (all
  suites stub `llm.ask`). Expect one wrong assumption about the model's
  JSON; fix it from its own words.
- **Acceptance, owner's eyes:** three references of different character —
  a dark editorial, a bright product grid, a letter/plain-text — × two brands
  (Baci, Eien) = six emails on the Brand tab beside their references. The
  bar: a stranger shown the reference and the email says *"same designer,
  different brand."* Not before that is the campaign skill switched for the
  run that ships.
- Memory note + RUNBOOK §6d regenerated + `WALKTHROUGH-PROMPT.md` §5 entry
  with the reversed rule verbatim.

### Phase 7 — Learn (later, not this initiative)
Structures carry outcomes per brand (`results.py` joining `Output.design` to
performance); a "hand" authoring surface for a design written from scratch;
a picture-to-picture fidelity judge once a screenshot capability exists.

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
> **First move:** `python3 scripts/test_a_reference_is_recreated.py` — six
> entries report `[ open ]`; that is the diagnosis, on record. Then re-check
> `INITIATIVE-email-design.md` §2 against the tree (`git log -1`, then each
> `file:line`). Phases 0–2 shipped 2026-09-11; start at Phase 3 (the reader
> with eyes — strips cut to the reviewer's tier, three passes, the reference
> beside a live preview), and when a phase lands, its ledger entries go red —
> replace them with that phase's own checks in the same commit. Check first
> that the entry MEASURES THE NEWS: Phase 2's entry counted the wrong fields
> and did not flip until it was rewritten.
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
