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

## 6b. Semrush, and what it costs

Semrush bills per LINE returned, at a price that depends on the report: 10 units
a line for a domain report and 40 for the related-keywords and questions
reports. One key serves every account. On 2026-09-07 a single Monday harvest
was 28,000 units an account and nothing in the code knew what a call cost.

Every read now goes through one door that prices it, bounds the lines, checks
three rolling ceilings and refuses in a sentence naming the ceiling. Answers are
kept and reused, so a second harvest in the same week buys nothing.

**When the balance runs out.** The door halts for 24 hours and stops asking; the
first refusal is one row in the ledger rather than seventeen. Buy units at
Semrush → Subscription info → API units, then press **Read the balance now** on
the Diagnostics tab. That read is free and a positive reading reopens the door
immediately. `/health/seo` reports the same number.

**Where to look.** Diagnostics → Platforms and cost → Semrush units: spend by
account for the window, the last balance and when it was read, the weekly cap,
and the door's state. The Plan tab shows what a top-up will cost before you
press it, and says so when the answer is already in hand.

**The knobs**, all environment variables on the `assistant-env` group:

```
SEMRUSH_WEEKLY_CAP=60000            the whole service, rolling 7 days
SEMRUSH_ACCOUNT_WEEKLY_CAP=30000    per account (per-tenant override:
                                    analytics.semrush_weekly_cap)
SEMRUSH_TURN_CAP=3000               one agent message
SEMRUSH_EXPANSION_TTL_DAYS=60       how long a bought expansion is reused
SEMRUSH_NEW_SEEDS_PER_RUN=3         new seeds one harvest may buy
SEMRUSH_MIN_VOLUME=10               the tail an expansion will not pay for
SEMRUSH_LOW_BALANCE=20000           when the daily reading warns you
```

The daily balance reading runs at 05:50 Eastern and messages you below the low
line. The map top-up runs Monday at `SWEEP_HOUR`:25 and no longer expands seeds
unattended. The monthly metrics refresh runs on the 1st at `SWEEP_HOUR`:45,
through the one batch report, a hundred phrases a request.

## 6c. Answer engines: can they read us, and are they sending anyone

Two questions that gate everything the blog system does for answer engines. A
page written to be cited cannot be cited by an engine that is not allowed to
fetch it, and until 2026-09-10 nothing here asked.

**The distinction that matters.** A SEARCH crawler decides whether an engine
can cite the page. A TRAINING crawler decides whether the content trains a
model. Blocking `GPTBot` does not remove a site from ChatGPT's answers — that
is `OAI-SearchBot`, and OpenAI says so on its own bots page. Google states that
`Google-Extended` does not affect inclusion or ranking in Search, and AI
Overviews are served from the Search index, so the crawler that decides whether
a page can appear in one is `Googlebot`. Blocking a training crawler is a
licensing choice a brand is entitled to make and costs no citations. The
console labels it that way rather than as something to fix.

**Where to look.** Plan tab, Progress, "Can the engines read us". It renders
the last stored check and calls nothing; the button runs it. A weekly job
re-checks every account with a blog system on Sunday at `SWEEP_HOUR`:50,
because a robots rule or a CDN setting changes without anybody here being told.

**Two checks, because robots.txt is the declared policy and not the answer.**
The first reads robots.txt. The second asks the site for a page while
identifying as each search crawler, which is the only way to catch a CDN
refusing AI agents at the edge while robots.txt welcomes them. A site that
refuses an ordinary browser too is reported as down rather than as blocking.

```
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/answer_engines?tenant=baci"
```

**And whether it is working.** The same check reads GA4 for sessions whose
source is an answer engine — ChatGPT, Perplexity, Claude, Gemini, Copilot.
Zero is not proof of not being cited, because most answers are read without a
click, but anything above zero is proof that we are. It pairs with
`keywords.aeo`'s answer-taken flag, which is the other direction: ranking well
and not being clicked is consistent with an answer taking the click.

### The files, and who can install each one

Plan tab, Progress, under "Can the engines read us". Two files, generated from
what the site serves today rather than from a template.

**robots.txt is only offered when it changes something.** A site that already
lets the search crawlers in gets told so and nothing is written. When it does
need a change, the generated groups repeat the wildcard group's own Disallow
lines: a crawler obeys the most specific user-agent group that matches it and
ignores `*`, so a bare `Allow: /` under a crawler's name would detach it from
the wildcard rules and hand it `/cart`, `/checkout` and `/admin`.

On Shopify it installs. robots.txt there is a theme template, and the generated
`templates/robots.txt.liquid` replays Shopify's own default groups through
their loop (so the store keeps tracking their updates) and appends ours. It
goes through the approval queue like every other write. On WordPress and
Squarespace there is no write path, so the file is shown and somebody uploads
it.

**llms.txt** is an index in the format llmstxt.org describes: an H1, a
blockquote summary, then H2 sections of markdown links. It lists only pages
that are published with a live URL, because an index pointing at pages an
engine cannot fetch is worse than none. No platform here can write it.

**Training is a separate decision from being cited, and it is yours.** Search
crawlers decide whether an engine can cite a page; the training setting decides
only whether the content trains a model. Undecided is a real third state and
leaves robots.txt alone — a brand nobody has asked is not a brand that said no.
The buttons are on the same card. For these accounts the recommendation is to
allow both: being in training data is roughly how a brand becomes part of what
a model knows without needing a citation, and blocking it is the publisher's
posture, which protects licensing revenue none of these brands sell.

**What no file can fix.** A CDN can refuse a crawler before the origin sees the
request. When the check finds Cloudflare in front of a site, the card says so
and points at Cloudflare's AI Crawl Control, which is on all plans and shows
which AI services actually reached the site.

## 6d. The email structure library, and the swipe board

Brand tab, "Email structures", beside the visual boards. Owner, 2026-09-11:
mimic many styles from Really Good Emails, respect brand rules, and save every
approved structure to a collective library for reuse with different copy.

**A structure is how an email is built, never what it says.** Block order and
the reasons for it: where the picture sits, how many asks and where, how
dense. Never the words, never the pictures, never the markup. Every email in
that gallery is some brand's copyrighted creative; the pattern is what is
legitimate, applied with our own material. It is the visual-board rule one
channel over: a reference contributes words, never pixels.

**Two ways in.**
- *Swipe.* Paste one email's page from reallygoodemails.com into the form.
  The screenshot is filed as a REFERENCE picture on the agency's swipe board
  (so it can never be selected as a hero), read once in words into a
  structure, and the structure waits for your approval. A category or search
  page is refused; you curate, the system reads what you chose.
- *Run.* When you approve a campaign email and it pushes to the ESP, its
  block sequence is filed as an approved structure automatically, once per
  distinct sequence, named by what it does (`hero-led medium offer, 2 asks`)
  and never by the account.

**Brand rules bind at the moment of use, in two places.** Before the drafter
sees a structure, `usable_for` refuses it for a brand when its notes use a
word that brand bars (a structure described around "hand-crafted" never
reaches Baci), when it needs something the brand cannot supply (a products
block with no products on file, a proof block with no approved claim, a hero
where nothing can illustrate), or when its notes identify another account.
Then the drafted email goes through every gate it went through before — ban
list, citation, coherence — because a structure cannot put a word on the page.

**The library is shared and says so.** It carries no account, on
`CraftLesson`'s terms: technique, never a client fact. Each structure on the
card shows whether THIS brand may use it and why not when it may not.

**How it is chosen: random unless designated.** On the campaign plan, the
field "Email structure (optional)" lists the approved structures this brand
may use, with anything it may not use shown disabled and the reason beside
it. Left blank, the run draws at random from those that fit the send's
intent and form and are not one of the last shapes that list received. A
draw rather than a rotation, because a rotation is a schedule a list can
learn to see. Name one and the run builds on it — or, if this brand may not
use it, refuses with the reason and designs fresh rather than silently
swapping. The run's notes say which happened. With nothing that fits the
drafter designs fresh, as it always did.

**SUPERSEDED 2026-09-11 (owner) — read `INITIATIVE-email-design.md` §0 before building on the paragraph below.** It describes how the LIVE renderer behaves until Phase 4 of that plan lands; the rule it states ("never a colour") was the wrong reading of the owner's ask and is reversed there: the reference's whole design is recreated, the brand fills its colour roles, faces, pictures and words.

<!-- BEGIN GENERATED: the design vocabulary — scripts/gen_email_design_doc.py -->

**The design vocabulary (INITIATIVE-email-design.md, Phase 1 — filed on every structure; drawn from Phase 4).** A design is the whole of how an email is built, in these words and no others: a ground is a ROLE the brand's palette fills, a face is a CLASS the brand's own face overrides, a slot is a KIND of content the drafter writes. Generated from `email_design.SCHEMA`; do not edit by hand.

| field | values | default | what it means |
|---|---|---|---|
| `frame.page` | page · dark · tint | page | the ground behind the email |
| `frame.container` | flat · card · cards | card | the email sits flat on the page, in one card on it, or as a stack of cards — every section its own rounded card with the page showing between them |
| `frame.width` | 600 · 640 · 680 | 600 | the email's width in pixels |
| `frame.radius` | none · soft · round | soft | how corners are cut, everywhere |
| `frame.border` | off · on | on | a keyline around the card |
| `header.logo` | left · center | left | where the brand mark sits |
| `header.nav` | none · inline · below | inline | the store's sections as links: none, beside the mark, on their own line |
| `header.case` | upper · title | upper | how the links are set |
| `header.bg` | page · surface · dark · tint · accent | surface | the header's ground — a role |
| `header.rule` | off · on | on | a rule under the header |
| `type.display_family` | serif-display · serif-editorial · sans-geometric · sans-grotesque · condensed · script | serif-editorial | the CLASS of the headline face — the brand's own face wins when it has one on file; this chooses a stack only when it has none |
| `type.body_family` | serif · sans | sans | the class of the reading face |
| `type.scale` | modest · large · display · poster | modest | how big the headline is against the body |
| `type.heading_weight` | light · regular · bold · black | bold | the headline's weight |
| `type.heading_case` | upper · title · sentence | sentence | the headline's case |
| `type.tracking` | tight · normal · wide | normal | letter-spacing on headings |
| `type.align` | left · center | left | where headings sit |
| `type.body_size` | 14 · 15 · 16 · 17 | 16 | the reading size in pixels |
| `type.leading` | tight · regular · airy | regular | line height everywhere |
| `type.kicker` | none · caps · accent · rule · pill | accent | the small line over a section: none; small capitals; small capitals in the accent; with a short rule; on a filled pill |
| `type.italic_sub` | off · on | off | the sub-headline is set in italics |
| `palette.mood` | light · dark · high-contrast · tonal · mono | light | the email's overall key — read off the reference, filled by the brand's roles |
| `palette.accent_use` | buttons · rules · type · blocks | buttons, rules | where the accent is allowed to appear |
| `cta.style` | filled · outline · underline · arrow · full | filled | the ask's shape: a filled button; outlined; an underlined line; a line with an arrow; a full-width bar |
| `cta.radius` | square · soft · pill | soft | the button's corners |
| `cta.size` | small · regular · large | regular | the button's size |
| `cta.case` | upper · title · sentence | sentence | the label's case |
| `cta.align` | left · center | left | where the ask sits |
| `dividers.style` | none · thin · thick · dotted · ornament | thin | what separates sections when a divider is asked for |
| `footer.bg` | page · surface · dark · tint · accent | surface | the footer's ground — a role |
| `footer.align` | left · center | center | where the footer's lines sit |
| `footer.socials` | none · words · icons | words | how the social links are shown |
| `footer.rule` | off · on | off | a rule over the footer |
| `imagery.hero` | packshot-on-plain · packshot-on-colour · lifestyle · flat-lay · portrait · texture | lifestyle | the kind of picture the opening wants |
| `imagery.product` | packshot-on-plain · packshot-on-colour · lifestyle · flat-lay · portrait · texture | packshot-on-plain | the kind of picture a product card wants |
| `imagery.feature` | packshot-on-plain · packshot-on-colour · lifestyle · flat-lay · portrait · texture | lifestyle | the kind of picture a feature section wants |
| `section.layout` | stack · split-left · split-right · grid2 · grid3 · collage · overlay · columns · band · letter | stack | how the section's parts sit: stacked; picture beside the words (left or right); a grid of two or three; a collage of pictures; words ON the picture; two columns of words; one line on a band; a letter's paragraphs |
| `section.align` | left · center | left | where the words sit |
| `section.bg` | page · surface · dark · tint · accent | surface | the ground the section sits on — a ROLE the brand's palette fills, never a colour |
| `section.pad` | none · tight · regular · airy | regular | the room around the section |
| `section.image` | none · contained · bleed · rounded · circle · framed · duotone | contained | the picture's treatment: inside the margins; edge to edge; rounded corners; a circle; a keyline; a tint |
| `section.aspect` | square · portrait · landscape · wide | landscape | the picture's shape — the slot the brand's own picture is cut to |
| `section.text_on_image` | off · on | off | the words sit over the picture |
| `section.rule_above` | none · thin · thick · dotted | none | a rule between this section and the one before |
| `section.list` | check · pill · arrow · plain | check | how a list is set: ticks; pill buttons two across (a quiz, a poll); rows with an arrow and a rule between (further reading); plain lines |
| `section.image_kind` | inherit · packshot-on-plain · packshot-on-colour · lifestyle · flat-lay · portrait · texture · mark | inherit | what KIND of picture this section's picture slots want — a product alone on a plain or a coloured ground, a lifestyle scene, a flat-lay, a person, a texture — or a brand mark (a logo band, not a photograph); inherit = the design's imagery default for this section's family |

Section kinds: hero · intro · feature · products · proof · editorial · offer · closing · ps. Slots: kicker · headline · sub · body · list · cta · products · quote · stat · image · caption · signature · ps (products and image take a count, 1–6). Grounds a design may name: page · surface · dark · tint · accent; the roles a brand supplies: page · surface · ink · muted · accent · accent_ink · dark · dark_ink · tint · tint_ink · border · secondary.

<!-- END GENERATED: the design vocabulary -->

**The look: a structure carries the arrangement, never a colour.** Block
order alone was not what the owner meant by "mimic the style" — the first
send built on a swipe came out as the house template with the swipe's
sequence, "not anywhere near the structure / styling / layout of the email
reference" (2026-09-11). So the reading also records HOW the blocks are
arranged, in a closed vocabulary the renderer draws (`email_render.LOOK`):

| axis | values | what moves |
|---|---|---|
| `hero` | contained · bleed · overlay · split | the opening picture's treatment |
| `scale` | modest · display | the headline size and the section heads |
| `density` | tight · regular · airy | padding and line height everywhere |
| `bands` | on · off | every second section on the page colour |
| `cta` | block · full · pill · link | the ask's shape |
| `products` | rows · grid2 · grid3 | the catalogue layout |

Colours and typefaces are NOT axes — a look the model volunteers with an
accent or a font has those dropped at filing (`look_of`), because the
brand's theme is the only source of identity and the look is only the shape
it is poured into. The one place a look touches colour is the overlay hero,
which forces white type over a dark scrim so the headline stays readable on
a photograph. The card says how each structure is arranged; a structure
filed before this existed says "no look read" with **Read its look**, which
re-reads the same screenshot into the same structure (its approval stands).
The drafter's brief says the arrangement in words so the copy fits it (a
display headline is short; a grid needs each product name to stand alone).
The run's notes say `arranged as the structure's look: …`.

**Klaviyo targeting reads segments ten a page.** Klaviyo's Get Segments caps
`page[size]` at 10; the first cut asked for 100 and every campaign came back
"the ESP could not be read (400: Page size must be an integer between 1 and
10)" and untargeted. It pages by the `links.next` cursor now, to 500.

## 6e. Designs — a reference from a link, reviewed, chosen, used by the campaigns

**One room, three moves** — *Systems → Campaign email → Designs*:

1. **Add this reference** — paste one email's page on Really Good Emails.
   In one press, off the request: the page's picture is filed on the shared
   swipe board (once — the same link finds it), read into a *brief* in words
   (concept, each section's job / asset / copy jobs, the visual system, the
   devices), filed as ONE design keyed by that picture, and **recreated for
   this brand**: its pictures cast by looking at a numbered sheet, its copy
   written to the brief's jobs, the email HTML written whole by the model,
   checked (the invariants), photographed, judged beside the reference,
   edited up to twice, the best round kept. The room shows *running — ‹step›*
   until it lands.
2. **Look** — the design lands under *New — look, then choose*: the reference
   beside ours, the status (*shippable / not shippable / cannot be made*),
   the judge's line (*same concept · devices in order · all the brand's own ·
   weight and rhythm*), every open finding (*where — what → do*), the rounds,
   the run's story. *open the HTML* serves the kept email.
3. **Choose** — **Use it — into the rotation** or **Not this one**. In the
   rotation, **Use this for every campaign** makes it the standing choice
   (*Back to random* undoes it). The line under the paste form says what the
   campaigns will do: draw at random from the rotation this brand may use,
   or build every one on the standing choice. A plan's own `structure` field
   still outranks both for that send.

**The campaigns are built in the design.** When a campaign's design has a
brief, the drafter writes the MESSAGE as before (subject, angle, offer, the
blocks, the claims it cites — through every gate it went through before) and
the email is then made in the design: the message poured into its copy jobs,
the brand's pictures cast, the HTML written, checked, photographed and judged
beside the reference. The words checked at the emit door are the words that
ship. The run's notes say *built in the design ‹name›: ‹status› — ‹story›*
and list any blocking finding; the Designs room shows that recreation as the
latest, marked *from a campaign*. A recreation that fails builds the send the
old way **and says so**. A design with no brief (the house, a hand-filed order)
is built the old way. An unattended ship is held while a recreation has a
blocking finding.

**Recreate again / Read the reference again** — a fresh recreation (about an
entity, if chosen), or a fresh brief and recreation when the reading itself
was wrong.

**Statuses.** `shippable` — no check blocks and the judge names nothing
blocking. `not shippable` — something blocks (listed) or the email was never
judged (no picture; the note says why). `cannot be made` — the brand has no
publishable picture for a slot the design needs; the finding names what it
needs. `failed` — a step did not answer; the story says which.

**What it costs.** Five to seven model calls (three of them vision) and one
browser unit per round; the brief is read once per reference and reused. A
campaign draft rebuilt with the same words reuses its recreation.

**The screenshot door.** `SHOTS_WS` in the env group — a Browserless
endpoint `wss://production-sfo.browserless.io?token=…` (free plan: 1,000
shots a month, 2 at a time). Without it the email is still made and checked
but *not judged* and never called shippable, and the room says so.

**What it will not do.** Use a picture that is not the brand's own; carry
five words in a row, a colour or a picture from the reference; change the
drafter's words; ship without the address and `{{UNSUBSCRIBE}}`; draw a
verified tick or a count nobody has; call an email shippable that nobody
looked at; make a design the standing choice before it is in the rotation.
Each is a named finding with a sabotage guard.

**The older token reading (§6d) no longer shows anywhere on the console**;
its code and its route survive only until Phase 5 deletes them. Nothing is
read on a press: a reference is read the moment it is added.

## 7. What does not work yet

Read this before promising anything.

**~~No system produces output.~~ STALE — corrected 2026-08-30.** This
paragraph described the state before the generator existed and was left
standing for a week after it stopped being true, which is exactly the failure
this file warns about elsewhere. Systems do produce output: `Context.emit` is
the only exit, three gates run on every artifact, `campaign_email` has done
live Omnisend round-trips for Eien, and run counts on the Systems tab are
real. `BUILD-STATE.md` and `/health` are the authority on what is live.
`reorder_engine` and `reports` are still declared with no generator, and they
say `not_built` honestly when run — that is the remaining truth in this
paragraph.

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

## 7b. Making and approving ad creative

The whole loop, in the order you would actually do it.

1. **Write the copy.** Run `ad_copy` for the account (skill_run, or the admin
   agent). Every variant lands on the variant board at `/admin/work/<anchor>`
   with an amber "needs art direction" chip.
2. **Make the frames.** On the variant you want, choose 8 / 16 / 24 and press
   **Make frames**. It runs off the request (an image call and a review per
   cell — two to three minutes for eight). The page does not refresh itself;
   the state appears under Review · Pictures as "Ad frames — running", and as
   "failed" with the reason if it fails. It will not silently look like it is
   still going.
3. **Review the set.** Review · Pictures draws the set as ONE card above the
   crawler's queue: every frame, labelled with the angle and framing it was
   generated along, with the model's own read beside it. That read is advice —
   a frame it disliked is still yours to keep. Per-frame **Keep**, or **Reject
   the set** if the brief was wrong.
4. **Optionally edit one in Canva.** "edit in Canva" per frame hands the
   picture over with the type and layout editable; the picture itself is
   fixed. Nothing is published. Bring the finished design back with
   `canva.harvest`.
5. **Keep what works.** Approving cuts the 4:5 and 9:16 placements there and
   then, and starts the hand-off to the client's own CMS in the background.

**When the hand-off does not happen**, the reason is one of three and each has
its own fix:

| what you see | why | fix |
|---|---|---|
| "no CMS connected" | `Tenant.domain` has no connected platform | connect a store or site at `/connect/<token>` |
| "not granted: write_files" on Connections | the store was connected before 2026-08-30, when we started asking | re-connect that store once |
| `media.sweep` reports `unhosted` | approved pictures nobody would take | one of the two above |

Nothing is lost while any of that is true — a refusal KEEPS the picture with
us and the row is never rewritten. `media.sweep` counts them separately from
ordinary approvals precisely so a broken connection stops reading as normal.

**Canva has never met the live API.** Every path in `app/canva.py` says so in
its own docstring. Before relying on step 4, run the live check — it needs the
live database and makes real calls, and prints no secrets:

```bash
DATABASE_URL='...' python3 scripts/verify_canva.py <tenant>
DATABASE_URL='...' python3 scripts/verify_canva.py <tenant> --design
```

It answers the two questions that matter: whether a per-client folder is
created and REUSED (never duplicated) and written back to the tenant, and
whether a client's own Canva takes precedence over the agency's
(`source=client` vs `source=agency`).

---

## 8. Verifying a deploy

```bash
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/tenants"
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/seed_kb?report_only=1"
curl -b ~/.gomeh-console -s "https://assistant-web-zm2d.onrender.com/admin/tenant_scope?report_only=1"
```

Offline suites, none of which touch the network. The hand-kept list that used
to live here named twenty of them and went stale the moment the twenty-first
was written — use the runner, which globs:

```bash
./scripts/test_all.sh
```

128 suites, about two minutes, run in parallel. One suite by name:

```bash
./scripts/test_all.sh hosting
```

And the guards themselves — every entry disables one guard, runs the suites
that claim to cover it, and expects them to FAIL. `caught` is the only good
outcome; `MISSED` means the test around it is decoration and `STALE` means the
code it patched has moved:

```bash
python3 scripts/sabotage.py
```

Still outstanding from the tenant migration — the Postgres constraint regrade
has only ever run against SQLite, which cannot exercise it:

```bash
psql "$DATABASE_URL" -c "select conname from pg_constraint where conrelid='contacts'::regclass;"
```

Expect `uq_contact_tenant_email` present and `contacts_email_key` gone.
