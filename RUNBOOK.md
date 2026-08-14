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

> **Read this before sending anyone a link.** The connect page 500'd on every
> submission from the day form parsing landed until `6a04e65` deployed on
> 2026-08-12 — `python-multipart` was missing from `requirements.txt`. Any
> client who was ever sent a link pasted a key and got an Internal Server Error.
> It is fixed and **has never been used successfully by a client**, so prove the
> path on yourself first:
>
> ```bash
> curl -b ~/.gomeh-console -s ".../admin/connect_new?tenant=baci&label=self-test&days=1"
> ```
>
> Open the URL, paste a real key, submit. A wrong key must fail in front of you;
> a right one must verify against the live API before it is stored.

**Set `CREDENTIAL_KEY` in the env group before any of this.** It is the Fernet
key, and it must not live where the database backups live — if it does,
encryption at rest buys nothing. Without it the code derives one from
`APPROVAL_SECRET`, which still encrypts but ties two secrets together. Setting
it later orphans every credential stored before it.

### The short version — do it on the console

`/admin/ui?tab=accounts`. Every account card now has a **Connections** block:
one row per provider, its state, who granted it, when it last verified, and
which permissions came back dark. From there —

- **Connect / Reconnect** on Google or Meta runs the OAuth flow as you, for
  accounts you connect yourself on a screen-share.
- **Re-check** re-probes a stored API key against the live provider. Worth
  doing before you rely on one: `store()` verified it the day it was pasted and
  nothing has checked since. A failed re-check reads **not verifying** and does
  **not** change which credential is in use — a probe can fail for reasons the
  real call will not, and demoting on that would silently fall back to the env
  blob.
- **Disconnect** revokes. It is a POST, so a link preview cannot fire it.
- **Create a connect link** mints the client's own private link and shows it to
  copy.

Everything below still works and is what the console calls. Until 2026-08-13
the console rendered none of it and all of this was curl-only — which is why
the runbook used to open with a shell command for the most common action in
onboarding.

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

**Self-serve today:** Shopify, Omnisend, Klaviyo, WordPress — paste a key.
Google (Gmail/Drive/Calendar/GSC/GA4) and Meta Ads — click Connect and sign in.

### What the client sees on the Google button

Our Google app is **not verified by Google**, deliberately: verification takes
weeks and caps nothing that matters at five clients. So the consent screen shows
"Google hasn't verified this app". They click **Advanced → Continue**. The
connect page says this in advance, in those words, because a client who meets
that screen unwarned closes the tab.

Unverified apps allow 100 users. If that ever becomes the limit, start
verification then.

**Leave every permission ticked.** One Google sign-in grants the mailbox,
Search Console and GA4 together. If they untick one, the connection still
stores and works — and the console names the missing scope beside it rather
than failing quietly a month later inside something that needed it. That is the
one thing OAuth does that an API key never could.

Before either OAuth provider works, four env vars must be in `assistant-env`:
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `META_APP_ID`, `META_APP_SECRET`.
Until they are, the connect page shows that provider as "on a call" **and names
the missing variable** — a blocker someone can clear, rather than a feature that
reads as unbuilt. The registered redirect URI must be exactly:

```
https://assistant-web-zm2d.onrender.com/oauth/google/callback
```

and the Meta equivalent. It is derived from `PUBLIC_BASE_URL` in one place
(`oauth.redirect_uri`), so it cannot drift between the two providers.

**Meta connections expire.** Meta long-lived tokens die at ~60 days and cannot
refresh — they are exchanged for a new one while still valid. A worker job at
06:30 daily renews anything inside 14 days of expiry; a renewal that fails marks
the credential `failed` and pings Telegram, because the alternative is an ads
connection that lapses silently. Google refresh tokens have no clock and are
never touched by it.

**You can also run either flow yourself**, for an account you connect on a
screen-share — same flow, console session instead of a client link:

```
/admin/oauth/google?tenant=acme
```

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

Grant the **full read set** when creating a Shopify app. The probe now catches a
403 (a valid token whose app has no read access) and says so, but a token with
*some* scopes and not others still passes and fails quietly later.

**The domain field wants the `.myshopify.com` one, not their storefront.** It is
in Shopify admin under Settings → Domains, and it is often a number rather than
a brand name — Baci's is `769684-2.myshopify.com`. Pasting the storefront domain
is refused with that instruction rather than a network error.

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

## 3b. Fill it from every source they have wired

**The one call that does all of it:**

```bash
curl -b ~/.gomeh-console -s ".../admin/fill?tenant=acme"          # rehearsal
curl -b ~/.gomeh-console -s ".../admin/fill?tenant=acme&apply=1"  # file proposals
```

It runs every source this account can use, skips the rest with a reason, and
ends with the questions only a human can answer. Sources declare themselves in
`sources.SOURCES`, so this list grows without the route changing:

| Source | Needs | Produces |
|---|---|---|
| `catalogue` | a commerce connection | entities with live price and stock |
| `compliance` | `banned_claims` on file | pages that break the brand's own rules |
| `website` | a domain | claim and review proposals |
| `sent_mail` | a connected mailbox | claims already made, **and objections** |

**Check `extractor` in the response.** If it reads `deterministic filter`,
`ANTHROPIC_API_KEY` is not set and you are getting a path measured at 0% recall
on qualitative claims — it found none of the six real claims on Ironside's
homepage. The proposal count will look plausible either way; the field is the
only tell.

The individual tools below still exist and are what `/admin/fill` calls. They
appear in the console under **Content**
(`/admin/ui?tab=content&tenant=acme`) with a button each.

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

**Sent mail** — what this account has already told customers:

```bash
curl -b ~/.gomeh-console -s ".../admin/email_harvest?tenant=baci"
```

This is the only source **objections** can be derived from, and it is why a
Google connection matters more than the others. It reads SENT mail, not the
inbox: a sentence someone sent a real customer is a claim they were already
willing to make, and paired with the message it answers it is an objection with
its approved answer.

Noise is not re-litigated here — threads are filtered by the bucket `triage`
already assigned, months ago, one message at a time. `promo`, `notifications`,
`receipts`, `subscriptions`, `sales_orders` and `urgent_money` are never opened.
Quoted history and signatures are cut before anything is read, so a customer's
words can never be attributed to the brand. A banned phrase found in your own
sent mail is refused **and reported** — someone has already said it to a
customer.

**Sent mail is walked, not sampled.** Gmail answers newest-first, so the old
call — `newer_than:365d` capped at a few dozen threads — read the same newest
few dozen on every run for ever. There is now a cursor per account with two
hands: `newest` is how far forward it has caught up, `oldest` is how far back
the backfill has walked. `/admin/fill` moves the forward hand only, so it is a
fast top-up of new mail; a nightly worker job at 03:15 moves the backward one,
`MAIL_BACKFILL_THREADS` (250) at a time, and stops on its own when it reaches
the start of the mailbox.

```bash
curl -b ~/.gomeh-console -s ".../admin/mail_cursor"                      # all accounts
curl -b ~/.gomeh-console -s ".../admin/mail_cursor?tenant=baci&reset=1"  # start over
```

A thread with no triage bucket used to be classified and the answer thrown
away, so the next pass paid for it again. It is now written back to
`EmailLog`, which is what makes a multi-night backfill get cheaper rather than
costing the same every night.

An account with no mailbox has no source for objections. Ironside is one.

What a crawler can **never** derive is `banned_claims` — a site records what a
brand does say, and the ban list is what it must not. Baci's own site says
"handmade in Italy", which is exactly why.

**Starting the machine-read half over.** `purge_proposals` below clears only
un-reviewed rows, which is the wrong tool when the bad rows were approved.
`purge_harvested` clears crawl- and email-origin claims and objections whatever
their review state, for one account or `*` for all:

```bash
curl -b ~/.gomeh-console -s ".../admin/purge_harvested?tenant=baci"            # report
curl -b ~/.gomeh-console -s ".../admin/purge_harvested?tenant=*&entities=1"    # report, wider
curl -b ~/.gomeh-console -s -X POST -d "tenant=baci" ".../admin/purge_harvested"
```

It never deletes `banned_claims`, the situation vocabulary, or anything of
human or seed origin — a crawler cannot derive the ban list, an empty tag
vocabulary refuses every harvested claim, and Ironside's eight venues were
authored rather than synced.

`entities=1` additionally clears the **store-synced** catalogue. **Order
matters if you use it:** `harvest` scopes a product page by looking its handle
up in the entity set, so until the catalogue is rebuilt every harvested answer
comes back unscoped. Re-run `catalog_sync` FIRST, then `fill`.

**Clearing a queue that came from an older crawler.** Proposals filed before
the crawl-quality fixes were chosen by a filter that has since been corrected,
so re-reading them costs more than re-running the harvest. Both purges default
to a dry run and never touch anything approved:

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/purge_proposals?tenant=baci"
curl -b ~/.gomeh-console -s -X POST -d "tenant=baci" "https://assistant-web-zm2d.onrender.com/admin/purge_proposals"
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/purge_scans?tenant=baci&dry_run=0"
```

Easier: the Content tab has a **Clear all N proposals** button that does the
same thing for the account you are looking at, with the count in the label and
a confirmation. The GET above only ever *reports* — deleting requires the POST
or the button, because a GET that deletes is fired by a browser prefetch.

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

**Nothing has connected through OAuth in production yet.** The flow is built and
covered offline end to end — signing, consent URL, the exchange, storage,
renewal, and the routes — but no real Google or Meta account has completed it.
Prove it on Baci before a client sees it, the same way §2 says to prove the
API-key path. The `GOOGLE_CLIENT_ID` pair also has to exist first, and the
redirect URI has to be registered byte for byte.

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
python3 scripts/test_provenance.py && python3 scripts/test_extract.py && \
python3 scripts/test_email_harvest.py && python3 scripts/test_sources.py && \
python3 scripts/test_oauth.py && python3 scripts/test_brief.py --demo
```

Still outstanding from the tenant migration — the Postgres constraint regrade
has only ever run against SQLite, which cannot exercise it:

```bash
psql "$DATABASE_URL" -c "select conname from pg_constraint where conrelid='contacts'::regclass;"
```

Expect `uq_contact_tenant_email` present and `contacts_email_key` gone.
