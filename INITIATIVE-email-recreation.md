# INITIATIVE — The model makes the email; the code inspects it

> **THIS IS A PLAN, NOT A STATE FILE.** Written 2026-09-12 at commit `7e73b0b`.
> `BUILD-STATE.md` remains the record of what exists.
>
> It supersedes the *centre* of `INITIATIVE-email-design.md` (the closed
> vocabulary, the token-writing reader, the token-drawing renderer) and keeps
> its plumbing (pictures read and filed, the photo-led palette maths, the
> campaign seam, the Brand tab). §5 says what is kept and what is retired.
>
> §2 is a list of facts with `file:line`, each checkable in a minute. If they
> still hold, the plan holds.
>
> **Phases 1 and 3 are built, Phase 2 in part (2026-09-12, same day; hashes
> in the memory note) — the chain in `app/recreate.py`, the door in
> `app/shots.py`, the campaign seam in `skill_pack._build`, the whole flow in
> one room (Systems → Campaign email → Designs: add a link → look → choose).
> Not proven live: the model calls are stubbed on this machine. Phase 2's
> owner-note-as-a-finding, Phases 4–6 are not started.**

---

## 0. The rule — read it before touching code

On 2026-09-12 the owner put the Ayoh reference beside the app's preview and
asked what they were supposed to do with it. Then, by hand, in about an hour,
with the reference in view and Baci's own catalogue open, the model recreated
the Ayoh email for Baci — and it was better than anything the app has made.
The owner asked why. The answer, and the rule:

> **The model makes the email. The code inspects it. A judge compares it to
> the reference. The owner approves it.**
>
> The model is never again asked a narrow question with a closed answer set
> about a design ("which of these tokens?", "which kind tag?", "blocks for
> this format"). It is given the whole job with everything in view — the
> reference as a picture, the brand's kit, the campaign's content — and it
> writes the email. **The only closed lists in the system are invariants**
> (brand assets only, no string from the reference, contrast, footer,
> unsubscribe, ban lists, compliance lines, email-safe HTML). The design is
> open. A reference with something we have never seen needs nothing added.

Why the old centre had to go, in one sentence: *if the reader has to round,
the representation is wrong* — a vocabulary smaller than the input space
guarantees every reference comes out as a variant of the same email.

The half of the old rule that stands: **the reference's copy, pictures,
markup and hex never reach the email.** That is now a validator, not a
vocabulary.

The owner's wider decision (2026-09-12): *"this is how everything should run
when it comes to creative output. Let's start with email, then the other
creative systems."* §7 names the pattern the other systems will inherit.

---

## 1. The trace — what was done by hand, step by step, and what does it in the system

Each step below is what the model did on 2026-09-12 (Ayoh "Sauce the meat" →
Baci Milano, Portofino). The right-hand side is the component that does it
unattended. **This is the spec.** If a phase's component does not do what the
hand did, the phase is not done.

| # | By hand, 2026-09-12 | In the system |
|---|---|---|
| 0 | Looked at the reference **whole**, as a picture. | The structure's REFERENCE picture (already filed by `add_swipe`). Nothing else about the reference is stored — no tokens. |
| 1 | Wrote the **brief** in words: the concept in one sentence (*a recipe delivered as a screenshot of our own Instagram post; pun hook above; shop the product used; the product at the table below*); each section as *what it is, what it does for the reader, the asset it carries and what that asset must show, the copy job, its look*; the visual system (type roles, colour logic, rhythm); the devices (post card with handle + icon row, display + script closer, cream-on-ground bordered button). | `recreate.brief(asset_id) → brief` — one vision call, free words under a light schema (`concept`, `sections[]`, `visual_system`, `devices[]`, `copy_jobs[]`, `reference_text[]`). Stored on the structure. `reference_text` is every visible word of the reference, kept ONLY for the leak validator. |
| 2 | Pulled the **brand's material**: catalogue with every image, names, prices, URLs; logo; Instagram handle; postal address; site faces; the brand's rules (Baci's ban list). | `recreate.kit(tenant) → kit`: entities + their pictures with readings, approved claims, reviews, brand theme (palette, faces, logo, sender, nav, address), channel copy rules, compliance lines, ban list, social handles. All of it exists in the KB today; this is one function that gathers it. |
| 3 | **Looked at 71 photographs** on a contact sheet and cast two by the job each slot needs: *the product in use, food on it, hands, sunlight* → the spaghetti on the Portofino plate; *the pieces at the table* → the place setting. | `recreate.cast(tenant, brief, kit) → cast` — a vision call that sees the candidates (thumbnails + their readings) and the brief's asset specs, returns a pick per slot **with the reason**, or *none fits* → the substitution ladder (§3) → cut and said. Never by colour histogram alone. |
| 4 | **Measured the palette** from the cast photos (page = the placemat's terracotta, card = the linen) and checked contrast; the logo the brand's white one. | `palette.from_photos` (exists) offered to the composer as *measured candidates*; the composer decides, the validator checks contrast ≥ 4.5 on every text-over-ground pair it can compute from the HTML. |
| 5 | **Chose faces**: the brand's own for kicker/body/button; a display and a script face for the roles the reference has, with client fallbacks. | The kit carries `faces.body`; the composer may add `display`/`script` from Google Fonts with fallbacks and records the choice on the recreation; the card offers *keep these faces for the brand* → `brand_theme` (Phase 4). |
| 6 | **Wrote the copy to the jobs**: a hook that turns on the verb; four steps naming real pieces, ending on one word; a closer with a script tail; a CTA naming the collection — inside the brand's rules. | The drafter gets `brief.copy_jobs` + kit + the campaign's content and rules, writes per job; the existing craft and claim gates (`email_craft`, `coherence`, `compliance`) run unchanged on the text. |
| 7 | **Wrote the email HTML directly** — tables, inline CSS, 600 wide, alt text, real links, address, unsubscribe — drawing the devices as needed. | `recreate.compose(brief, kit, cast, copy) → html` — the model writes the HTML. Copy strings must appear verbatim (validator). |
| 8 | **Rendered it** to a picture and looked. | `shots.shoot(html) → png` — the screenshot door (§4). Also shoots fragments to bake (Phase 4). |
| 9 | **Judged it against the reference** — headline sat at 45 % of the column against the reference's ~75 %, face too narrow — fixed, rendered again. Two rounds. | `recreate.judge(reference_png, ours_png, brief) → findings[]` — *where, what differs, what to do, severity*; then `compose(..., revise=findings)` **edits** the HTML (never rewrites); prior findings re-checked first; ≤ 2 rounds; best round kept by blocking-count. |
| 10 | **Listed what is not shippable**: SVG icons drop in Gmail; web-font fallbacks unverified; the post is composed, not a real Instagram post; no verified tick because unknown; merge-tag placeholders. | `recreate.check(html, kit, brief, copy) → findings[]` — the invariants (§3). A failing invariant is *not shippable*, whatever the judge said. |
| 11 | **Delivered** the render, the HTML and the findings; asked for the reference beside it. | The structure card shows *reference | ours | open findings | rounds*; the owner's note is a finding and runs step 9 again; approval ships through the ESP door that exists. |

---

## 2. Facts this plan rests on (`file:line`, checked 2026-09-12)

- The reference is a REFERENCE picture on the swipe board — `app/email_structures.py:565` `add_swipe` → `kb.add_asset(..., rights=kb.REFERENCE)`; `read_swipe` at `:619`. The picture is there; only its *reading* changes.
- One attributed model call, model chosen by purpose — `app/llm.py:151` `call(purpose, messages, ...)`, `:193` `ask`, `:69` `model_for(purpose)`; image tiers and size checks `:269–327`. New purposes register here.
- The judge pattern already exists for pictures — `app/creative.py:1257` `_judged(tenant, images, text, refs, checklist, redraw, *, fidelity)`: candidates, closest kept, faults named, one corrective redraw, near miss dropped and said. The email judge is the same shape on screenshots.
- The campaign seam is nineteen lines — `app/skill_pack.py:3634–3651`: `_design = structure.design or house()` → `email_design.fill` → `palette_for` → `email_render.render_design`. Phase 3 replaces exactly these lines.
- Pictures are already read and filed with readings — `app/email_design.py:686` `read_pictures`, `KbAsset.reading`; kinds set from the Brand tab (`/admin/picture_kind`). Casting uses them as text beside the thumbnails.
- The photo-led palette maths exist — `app/palette.py` `from_photos`, `contrast`, `fit`. Kept as measurement.
- Media is hosted — `app/web.py:409` `/media/{blob_id}`; `kb.add_asset` at `app/kb.py:3230`; generated pictures are approved at the push (`kb.approve_generated`, `:3018`).
- The ESP door — `app/omnisend.py:391` `send_campaign(tenant, campaign_id, confirm)`; Klaviyo/Constant Contact beside it in `esp.py`. Unchanged.
- **There is no browser in the deploy** — `render.yaml` runtime `python`, `requirements.txt` has no Playwright/Chromium. Screenshots need a door (§4).
- Model contracts are pinned per model before use (owner's rule, memory `learn-what-inputs-the-models-take`) — the brief/cast/judge calls send pictures at the reviewer tier (`llm.image_tier`), the compose call is text-only.
- The house protocol stands (`WALKTHROUGH-PROMPT.md` §4): reproduce first; every fix ships a sabotage guard; `./scripts/ship.sh`. **Guards apply to invariants and loop mechanics — never to a design.** A suite that asserts what an email must look like is the old mistake.

---

## 3. The invariants (the only closed lists) and the substitution ladder

`recreate.check` — each a named finding, each with a sabotage guard:

1. **Brand assets only**: every `<img src>` resolves to the kit (the brand's KB assets, its CDN, the brand's logo files). Anything else blocks.
2. **No reference leak**: no 5-gram of ours appears in `brief.reference_text`; no hex from the reference (the brief reader lists the reference's dominant hexes for this check only); no `<img>` from the reference's host.
3. **Copy verbatim**: every string the drafter wrote appears in the HTML unchanged; nothing the drafter did not write appears as body copy (the composer adds no words).
4. **Email-safe HTML**: table layout, inline styles, width 600, `alt` on every image, no `<svg>`/`<video>`/forms/scripts, total size < 100 KB (Gmail clips), web fonts with a named fallback stack.
5. **Contrast** ≥ 4.5 : 1 for every text colour over the ground it sits on that the checker can resolve from inline styles; unresolved pairs are listed, not assumed.
6. **CAN-SPAM and the ESP's variables**: the postal address from the theme, the unsubscribe merge tag the ESP uses, no view-in-browser link where the ESP has no variable for it.
7. **Brand rules at use**: ban list (word-bounded), compliance lines (Eien's FDA footer), the channel copy rules, entity fitness — the gates that exist, run on the text as today.
8. **Links live**: every `href` answers 2xx/3xx (HEAD) or is a merge tag.
9. **Fabrication**: no engagement counts, no verified tick, no review, no quote, no figure that is not on file. A social post shown is either a real post on file or composed from the brand's own picture and handle **and said so** in the findings.

**The substitution ladder** (what makes it consistent across brands): when the cast finds nothing for a device, it walks: *social post card → review-with-photo card → quote card*; *recipe/steps → steps from the brand's own material (a how-to, a table, a routine)*; *product in use → packshot on the photo's ground*; *nothing* → the section is cut and the finding says *needs: a photograph of X*. A brand with no usable pictures gets *cannot be made yet* on the card, never a wireframe.

---

## 4. The screenshot door

The judge needs pixels. Two doors, one interface — `shots.shoot(html: str, *, width=640, full=True) -> bytes`:

- **A. Browserless over CDP** (chosen by the owner 2026-09-12; built): `SHOTS_WS=wss://production-sfo.browserless.io?token=…` in the env group; Playwright `connect_over_cdp`; the contract pinned in `app/shots.py` from the provider's docs (a unit = 30 s of browser time, free plan 1,000 units/month, 2 concurrent, 2-minute sessions). Zero infrastructure, free at our volume, works on the starter plan. The same Playwright code drives a local Chromium on a laptop.
- **B. Playwright + Chromium** (later, if volume warrants): the web service moves to a Docker runtime with Chromium in the image; same function, no per-shot cost; needs more memory than the starter plan gives.

Local development and the suites use B when Playwright is present and a **stub** otherwise; the suites never call A. The door is also how fragments are baked (Phase 4): a block the composer marks `data-bake` is shot alone, filed as a generated picture, and replaces itself with an `<img>` — the reference's own trick (its post card is one image).

---

## 5. Phases — each shippable, each gated by eye, none started

The gate for every phase is the same two pictures the owner judges, side by
side with their references: **Ayoh → Baci** (against the hand-made one of
2026-09-12, filed at `docs/recreations/ayoh-baci-portofino.html`) and **pistol-shrimp →
Eien**. From Phase 2 on, a third: **a reference the owner picks fresh, with a
device the system has never seen** — the whole point is that this needs
nothing added.

**Phase 1 — Recreate, on the structure card (the proof and the preview). BUILT 2026-09-12.**
`recreate.brief`, `recreate.kit`, `recreate.cast`, `recreate.compose`,
`recreate.check`, `shots.shoot`, `recreate.judge`, up to two revise rounds; a
`Recreation` row (structure, tenant, brief, cast, html, png asset, findings,
rounds, status); a **Recreate for ‹brand›** button on the structure card, run
in the background like a creative set (`_run_bg`), the card showing
*reference | ours | findings*. Copy for a preview comes from the drafter with
the brand's material as content (no campaign yet) — never `sample_copy`.
**Gate:** the two pictures, by eye. No campaign touched.

**Phase 2 — The loop is the owner's too.** A note on the card is a finding
and runs the revise step; ≤ 2 automatic rounds, best kept; the card shows the
round history; *approve as the preview* marks the recreation good. The third
reference joins the gate. **Gate:** the owner's note changes the email the way
they said, and nothing else moves.

**Phase 3 — The campaign is a recreation.** `skill_pack.py:3634–3651` becomes
`recreate.for_campaign(structure, tenant, content, entities, recent_media,
seed)`: same chain, the campaign's copy jobs filled with the campaign's
content, variety from the cast (what this list saw lately ranks below what it
has not — the rule of 2026-09-12 stands), `media_ids` carrying every picture,
the judge's findings in the run notes, `ship_unattended` holding a blocking
finding. Approval → the ESP door. **Gate:** one real send per brand, judged
before and after in the inbox (Gmail, Apple Mail, Outlook) — the fallbacks
looked at, not assumed.

**Phase 4 — Sources and devices.** Instagram (the brand's feed and tagged
posts) as a KB source so a post card can be a real post; baked fragments
through the screenshot door; display/script faces kept on the brand from the
card; the substitution ladder shown on the card when it was walked. **Gate:**
the Ayoh recreation for Baci carries a real post, and the findings no longer
say *composed*.

**Phase 5 — Retire the old centre.** For designated structures:
`email_design.SCHEMA/normalize/house/read/fill/choose_media/preview_blocks/sample_copy`,
`email_render.render_design` and `LAYOUTS`, `email_structures.look_of/LOOK`,
the generated vocabulary table in `RUNBOOK.md` §6d, and every suite that
asserts a token. Kept: `read_pictures`/readings and kinds, `palette.py` as
measurement, the letter format's renderer for sends with no structure, the
swipe board, the library and its rules at use. `scripts/register.py` and
`gen_systems_reference.py` re-run. **Gate:** the full suite green with the
token suites deleted, not skipped; `/health` on the commit.

**Phase 6 — Learn.** A finding that recurs across brands or references is
promoted: into `recreate.check` if checkable, into the composer's standing
instructions if craft. Nothing else accumulates.

---

## 6. What is NOT in this plan

- A device library, a vocabulary, a schema of sections, a layout enum. If one
  appears in a diff, it is the old mistake.
- A suite that asserts what an email looks like. Suites cover invariants,
  the loop's mechanics (rounds, best-kept, edits-not-rewrites), model
  contracts, budgets and leaks.
- Ads, creative, blog. They inherit the pattern (§7) in their own initiatives
  after Phase 3 has shipped a real email.

---

## 7. The pattern the other creative systems inherit

*brief (the reference, in words) → kit (the brand's material, gathered) →
cast (chosen by looking, with reasons, or substituted and said) → make (the
model writes the artifact) → check (invariants) → shoot (pixels) → judge
(against the reference, findings not scores) → revise (edit, ≤ 2 rounds, best
kept) → approve (the owner, whose note is a finding) → ship (the door that
exists).*

Ads already have the judge (`creative._judged`); they lack the brief and the
cast-by-looking. Creative sets lack the brief. Blog heroes lack the judge
against a reference. Each is one initiative of the same shape as this one.

---

## 8. Paste this to open the next thread

> Read `INITIATIVE-email-recreation.md` §0 and §1 first — the rule and the
> trace. The hand-made recreation it was traced from is
> `docs/recreations/ayoh-baci-portofino.html` (Ayoh → Baci, 2026-09-12). Build Phase 1
> only: the chain behind **Recreate for ‹brand›** on the structure card, ending
> in *reference | ours | findings*. Before the first line of code, write the
> brief the reader should produce for the Ayoh reference, in words, and check
> it against §1 row 1; if it reads as a bad email in words, stop. Guards go on
> invariants (§3) and loop mechanics, never on a design. Gate by eye: Ayoh →
> Baci beside the hand-made one, pistol-shrimp → Eien beside its reference.
