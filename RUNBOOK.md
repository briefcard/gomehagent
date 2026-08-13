# Runbook — onboarding and running one client

Written 2026-08-12. Every command here was checked against the code, not
remembered. Where something does not work yet, it says so rather than reading
like it does — §7 is the honest list, and it is worth reading first if you are
deciding what to promise a client.

Live service: `https://assistant-web-zm2d.onrender.com`
Bot: `@Gomehadmin_bot`

---

## 0. Start a console session (once per browser, once per shell)

The credential is supplied **once** and exchanged for a session cookie. It no
longer belongs in every URL.

Browser — load this once, then use the console normally for 14 days:

```
https://assistant-web-zm2d.onrender.com/admin/ui?key=<APPROVAL_SECRET>
```

Shell — save the cookie once, then drop the key:

```bash
curl -c ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/ui?key=$APPROVAL_SECRET" -o /dev/null && echo "session saved"
```

Every later call:

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/tenants"
```

`/admin/logout` ends it. A single shared credential, no per-user identity —
see §7.

---

## 1. Create the account

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/tenant_add?tenant=acme&name=Acme%20Co&kind=client&domain=acme.com"
```

`tenant` is the key everything else joins on — lowercase, no spaces, permanent.
`kind` is `client` or `own` (your own P&L).

The original five (agency, baci, eien, coverings, ironside) already exist.

---

## 2. Connect their tools

### The short version — send them a link

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/connect_new?tenant=acme&label=Jane&days=30"
```

Send them the URL. They see one row per provider their systems need, paste each
key, and it is verified against the live API before it is stored — so a wrong
key fails in front of them rather than a week later inside something that reads
it. Keys are encrypted at rest and never rendered again, to them or to you.

Watch the board:

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/connections"
```

Disconnect: `/admin/connect_revoke?tenant=acme&provider=shopify`.

**Self-serve today:** Shopify, Omnisend, Klaviyo, WordPress.
**Still needs you:** Google (Gmail/Drive/Calendar/GSC/GA4) and Meta Ads are
OAuth, which is not built — those stay a ten-minute screen-share where they
click Allow while you run `scripts/google_oauth.py`. The connect page shows them
as "on a call" rather than pretending they are self-serve.

Set **`CREDENTIAL_KEY`** in the env group before using this in production. It is
the encryption key, and it must not live where the database backups live — if it
does, encryption at rest buys nothing. Without it the code derives a key from
`APPROVAL_SECRET`, which still encrypts but ties two secrets together.

### The long version — doing it yourself

Still needed for Google, and for anything a client cannot reach. Two layers,
easy to confuse:

**The secret** lives in the Render env group `assistant-env`, in a JSON blob
keyed by a name you choose. **The tenant row stores that name, never the
secret.**

Env vars must be set on the **group**, not one service — the webhook runs on
`assistant-web` but scheduled work runs on `assistant-worker`, and setting them
web-only makes cron silently fall back.

| Capability | Env blob | What to add |
|---|---|---|
| `inbox` | `GMAIL_ACCOUNTS_JSON` | run `scripts/google_oauth.py` locally as that mailbox, paste the entry |
| `commerce` | `SHOPIFY_STORES_JSON` | Shopify admin → Settings → Apps → Develop apps → create → scopes → install → reveal token |
| `cms` (WordPress) | `WORDPRESS_SITES_JSON` | an application password on an editor account |
| `esp` | any env var | Omnisend: Store settings → Integrations & API. Klaviyo: Settings → API keys |

Grant the **full read set** when creating a Shopify app. `verify` catches a dead
token but not a token with too few scopes — that fails quietly later.

Then point the tenant at those names, either in the console
(`/admin/ui` → Accounts) or directly:

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/tenant_set?tenant=acme&field=gmail_alias&value=acme"
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/tenant_set?tenant=acme&field=shopify_store&value=acme"
```

JSON fields take JSON:

```bash
curl -b ~/.gomeh-console -G "https://assistant-web-zm2d.onrender.com/admin/tenant_set" \
  --data-urlencode "tenant=acme" --data-urlencode "field=esp" \
  --data-urlencode 'value={"provider":"omnisend","credential_ref":"OMNISEND_ACME","from_name":"Acme","reply_to":"hi@acme.com"}'
```

**Then prove it works.** Configured and working are different questions:

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/verify?tenant=acme"
```

Capability names: `inbox`, `commerce`, `esp`, `cms`, `ads`, `analytics`,
`design`, `crm`.

> Note: `esp`, `cms`, `ads`, `analytics` and `crm` currently drive a status chip
> and little else — the SEO subsystem reads `SEO_SITES_JSON`, not the tenant
> row. See §7.

---

## 3. Fill the knowledge base

This is the part that decides whether anything downstream can speak. Nothing
generates from an empty KB — by design, it refuses rather than invents.

**See where it stands:** `/admin/ui?tab=kb` — pick the account. Every field the
KB holds is on that page: claims (and the ones that are expired, retired or
awaiting review), audiences, objections, what they sell, the situation
vocabulary, hard rules, and the gaps that have cost a real answer.

Three ways in, all writing through the same parser so a fact lands identically
whichever you use:

**a) You, one question at a time — Telegram.** Message the bot:

```
/use acme
/next
```

Then just reply. `/skip` moves on. `/gaps` lists what is still missing.

**b) You, in the console.** The Knowledge tab's "Next most useful question"
box, plus per-type add forms underneath.

**c) The client, on a private link.** One question at a time, no schema, no
other account reachable:

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/intake_new?tenant=acme&label=Jane&days=30"
```

Send them the returned URL. Revoke with `/admin/intake_revoke?token=…`.

**Claims submitted by a client are not selectable until you approve them** —
they land as `pending` and show in their own section of the Knowledge tab.

For the four seeded accounts, the established facts are already loaded and
re-runnable:

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/seed_kb?report_only=1"
```

Drop `report_only=1` to apply. Idempotent.

### What "ready" means, and what it doesn't

`ready` on the Knowledge tab means one or more of each required type exists. It
is a floor, not a standard — one objection cannot cover what a real buyer asks.
Treat it as "not obviously empty," not "good."

---

## 3b. Derive the rest from their website

Three tools, all safe to read first. They appear in the console under
**Content** (`/admin/ui?tab=content&tenant=acme`) with a button each, or as
routes.

**Catalogue** — Shopify products into the knowledge base, with live stock:

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/catalog_sync?tenant=baci&report_only=1"
```

The store owns price and availability on every sync; a description you wrote by
hand is never overwritten. Products whose storefront copy uses a banned phrase
are catalogued but their copy is not imported, and they are listed so the page
can be fixed.

> **Draft — reword to taste.** From `feat/context-architecture` on, "never
> overwritten" is enforced rather than intended, and the refusal is now
> reported instead of silent. When the store contradicts something you have
> approved, the sync writes nothing and lists the field under `held_back`; the
> disagreement appears on the Content tab under **Sources disagree**, with both
> values and a button each. Nothing downstream changes until you pick one, so
> the queue is safe to leave — but it is also the only place that work shows
> up, so check it after a sync. A row the store created and you have never
> edited is still refreshed silently; that is not a conflict.

**Compliance** — is the live site already saying what the brand banned:

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/compliance_scan?tenant=baci"
```

Pages come from sitemap → WordPress API → homepage crawl, whichever the site
supports, and the result says which was used. `&since=2026-08-01` checks only
what changed. An account with no `banned_claims` is **refused, not passed** —
scanning against zero rules and reporting "clean" is worse than not scanning.

**Harvest** — propose claims and reviews from their own site:

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/harvest?tenant=baci"
```

Add `&apply=1` to file them. They land **pending** — invisible to every
generator until approved on the Content tab, where each one is editable: fix the
wording, set the situation tags, then Save & approve.

Three rules worth knowing:

- A candidate using a banned phrase is **dropped, not queued** — including a
  customer review. Someone else saying it does not make it sayable.
- A candidate the tagger cannot place is proposed **untagged**. Approval is
  refused until you tag it, so segmentation happens where someone actually knows
  the answer.
- **A testimonial's wording cannot be edited.** A review reworded as brand copy
  is a fabrication however true the sentiment. Tags and attribution stay
  editable; the customer's words do not.

What a crawler can **never** derive is `banned_claims` — a site records what a
brand does say, and the ban list is what it must not. Baci's own site says
"handmade in Italy", which is exactly why.

**Clearing a queue that came from an older crawler.** Proposals filed before
the crawl-quality fixes were chosen by a filter that has since been corrected,
so re-reading them costs more than re-running the harvest. Both purges default
to a dry run and never touch anything approved:

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/purge_proposals?tenant=baci"
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/purge_proposals?tenant=baci&dry_run=0"
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/purge_scans?tenant=baci&dry_run=0"
```

Proposals are **deleted, not rejected** — deliberately. `suggest_tags` learns
what a bad claim looks like from retired rows, so filing a hundred pieces of
parser noise as "rejected" would teach the tagger that noise is what a rejected
claim looks like and degrade every suggestion after it.

**What the harvest report tells you now.** `pages_enumerated` vs `pages_read`
vs `pages_skipped` (with `skipped_examples`), and `dropped_by_reason` — the
count of candidate sentences the quality gate threw away, by reason. A thin
queue is supposed to be readable as either "the site says little that is
checkable" or "the crawl broke", and those two numbers are how you tell.

---

## 4. Attribute their existing data

Only relevant if the account already has history in the operational tables
(mail, deadlines, documents). Dry run first — it predicts per row:

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/tenant_scope?report_only=1"
```

That returns `would_attribute`, `would_remain`, and which tenant each row would
go to. Drop `report_only=1` to apply. Idempotent, never overwrites a tenant that
is already set, and leaves anything it cannot prove unassigned rather than
guessing.

---

## 5. Install systems

```
/admin/ui?tab=systems
```

Installable today: `lead_responder`, `campaign_email`, `blog`, `reorder_engine`,
`service_desk`, `reports`.

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/system_add?tenant=acme&system=lead_responder"
```

A system starts `designed` / `shadow` and **will refuse to go live** until:

1. **The 8-part contract is complete** — job replaced, owner, baseline, primary
   metric, counterfactual, kill criteria, failure mode, weekly artifact. If you
   cannot fill one, that is the signal not to build it.
2. **Its capabilities are wired** — `lead_responder` needs `inbox`,
   `campaign_email` needs `esp`, `blog` needs `cms`.
3. **The KB can ground it** — each system names the KB fields it needs.

The Systems tab shows the named blockers for each. Fill the contract there, or:

```bash
curl -b ~/.gomeh-console -G "https://assistant-web-zm2d.onrender.com/admin/system_set" \
  --data-urlencode "id=<system_id>" --data-urlencode "owner=Gomeh" \
  --data-urlencode "baseline=~4h/week answering enquiries by hand"
```

### The autonomy ladder

`shadow` → `approve_all` → `approve_exceptions` → `auto`. Nothing starts
autonomous. Promotion needs run history — 20 decided runs at ≥90% for the third
rung, 50 at ≥95% for the fourth, and one recent denial closes the gate.
Demotion is always available and never gated.

---

## 6. Day to day

Telegram, after `/use <account>`:

| Command | What it does |
|---|---|
| `/clients` | every account, what is wired, what is missing |
| `/use acme` | switch context |
| `/whoami` | who you are and which account you are on |
| `/kb` | knowledge-base status for the current account |
| `/next` | the single most useful missing fact — reply to answer |
| `/gaps` | everything still missing |
| `/unknowns` | the gap that has cost the most real answers |
| `/systems` | installed pipelines and their blockers |

Console: `/admin/ui` — Accounts, Systems, Knowledge.

---

## 7. What does not work yet

Read this before promising anything.

**No system produces output.** The generator, validator and send path are not
built. `systems.start_run` and `finish_run` have no callers outside their test
script. You can install a system, complete its contract and wire every
capability — and nothing will run it. Every run count on the Systems tab is
structurally zero. This is the next slice.

**Do not give a client bot access.** `user_add` exists and ops commands are
correctly scoped (a client pinned to one account is refused another), but
unrecognised free text falls through to an agent that is **not** tenant-scoped.
Intake links are safe — they reach one account and nothing else.

**The console is one shared credential — and it now guards client keys.** A
session cookie replaced the key in URLs, but there is still no per-user identity
and no revocation. That mattered less when the worst case was your data; now the
worst case is your clients' credentials. Real console auth moved from
nice-to-have to required.

**Google and Meta are not self-serve.** OAuth is not built, so those two stay a
screen-share. Everything else on the connect page is.

**Only Shopify is consumed from the new store yet.** `data_tools` reads a
client-connected Shopify token in preference to the env blob. Omnisend, Klaviyo
and WordPress keys are stored and verified but nothing reads them — because
there is no ESP or WordPress feature yet, not because the wiring is missing.

**Console writes are GET requests.** `/admin/kb_add`, `/admin/seed_kb` and
`/admin/tenant_scope` mutate on a GET, so a browser prefetch or link preview can
fire them.

**The SEO subsystem does not read the knowledge base.** `seo_tools`, `sites`,
`google_seo`, `shopify_seo`, `wordpress_seo` — 1,725 lines, zero references to
`banned_claims`. Baci's rules against "made in Italy" and "handmade" are enforced
nowhere in the code that publishes SEO copy to the live store.

**A client is defined in three places.** The `Tenant` table, `SEO_SITES_JSON`,
and `SeoSiteConfig`. The SEO subsystem uses the second; the platform uses the
first.

**No media layer.** No object storage, no CDN. Drive links do not hotlink
reliably into email. This blocks the campaign email builder.

**Rate cards, catering rules, load-in and curfew are missing for Ironside** —
so the quote responder will keep refusing to quote. That is correct behaviour,
not a bug.

---

## 8. Verifying a deploy

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/tenants"
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/seed_kb?report_only=1"
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/tenant_scope?report_only=1"
```

Offline suites, none of which touch the network:

```bash
python3 scripts/test_selection.py && python3 scripts/test_systems.py && \
python3 scripts/test_kb.py && python3 scripts/test_intake.py && \
python3 scripts/test_kb_ui.py && python3 scripts/test_tenant_scope.py && \
python3 scripts/test_migration.py && python3 scripts/test_console_auth.py && \
python3 scripts/test_credentials.py && \
python3 scripts/test_tenant_isolation.py && \
python3 scripts/test_worker_systems.py && python3 scripts/test_catalog_sync.py && \
python3 scripts/test_compliance.py && python3 scripts/test_harvest.py && \
python3 scripts/test_provenance.py && python3 scripts/test_brief.py --demo && \
python3 scripts/test_selection.py && python3 scripts/test_systems.py
```

Still outstanding from the tenant migration — the Postgres constraint regrade
has only ever run against SQLite, which cannot exercise it:

```bash
psql "$DATABASE_URL" -c "select conname from pg_constraint where conrelid='contacts'::regclass;"
```

Expect `uq_contact_tenant_email` present and `contacts_email_key` gone.
