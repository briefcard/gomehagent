---
name: baci-campaign-email
description: Write one Baci Milano USA campaign email from the gomehagent data layer and file it in the owner's approval queue. Use when asked for a Baci newsletter, promo or campaign email. Phase 2 of INITIATIVE-mcp-substrate.md. Run it with the owner watching; approved drafts become the exemplar the next run is held to.
---

# Baci Milano USA: one campaign email

Follow `gomeh-data-layer` (connection, the loop, and what not to do). This file
adds what is specific to Baci campaign email. Tenant `baci`, system
`campaign_email`.

## 1. Decide what this email is for (before the package)

1. `get_plan("baci")`: is a campaign_email planned or due? If one is, write
   THAT one: its entity, audience and date come from the plan.
2. `get_results("baci")`: which positioning, audience and entity worked, what
   the owner denied, and which gates keep catching drafts. Pick the subject and
   reader from these. Name your reason in one line to the owner.
3. ONE reader per email. The Omnisend lists are "Has ordered" (~1,040,
   opens 29–34%) and "Hasn't ordered" (~3,060, opens 12–16%). They are
   different emails, not one email with a softer line. Never write to the trade
   segments here; trade is a separate monthly email.

## 2. The package

`get_package("baci", "campaign_email", entity_key=<product>, audience_key=<reader>)`.
Write only from it. If the product's facts or a price are missing, the email
does not state them. Put that in `notes`.

## 3. Write

- Subject 3–8 words in the reader's words, not the brand's. Preheader adds to
  it; it does not repeat it.
- One product or one idea. Every product named is linked to its own page from
  the package's site pages. Have a CTA button above the fold. Tonight's audit
  found the recovery emails at 30% opens and **0% clicks** because the click
  path was broken. An email whose button goes nowhere is the most expensive
  defect there is.
- Italian-DESIGNED, designed in Milan. NEVER "made in Italy", "Italian-made" or
  "crafted in Italy". Check catches the ban list; do not rely on it alone.
- No discount unless the package or the owner's news carries one.
- Keep `{{UNSUBSCRIBE}}` and the deliverable spec the package gives.

## 4. Check, fix, record

`check("baci", body, "email", subject, preheader, claim_ids, entity_key)` →
fix every block → check again → `record(...)` with `notes` saying what you
left out and why. Give the owner the `review_url`. Approving there means
"reviewed". The owner moves it into Omnisend; this skill never pushes.

## 5. After the owner decides

If the owner rewrites or denies it, ask for the reason in one line. That reason
belongs in the owner's notes for Baci emails, which `get_package` hands the next
run. A correction nobody records is a correction made twice.
