# Saias Operations Assistant — Phase 1

Always-on assistant for Baci Milano USA, Eien Distributions, and Saias Consulting.
Email triage across three inboxes · approval-gated replies · daily digests ·
WhatsApp-ready.

**Hard rule baked in: no money moves, no quote is accepted, and no email to an
untrusted contact is sent without Gomeh's approval.**

## Setup (~30 min)

### 1. Anthropic API key (2 min)
console.anthropic.com → API Keys → create key. Add billing (Phase 1 usage is
roughly $5–20/month at normal email volume).

### 2. Google OAuth app (10 min, once)
1. console.cloud.google.com → new project "saias-assistant".
2. APIs & Services → enable **Gmail API**.
3. OAuth consent screen → External → add the three addresses as **test users**:
   gomehsaias@gmail.com, gs@bacimilanousa.com, store@eienhealth.com.
4. Credentials → Create credentials → OAuth client ID → **Desktop app**.
   Copy client ID + secret into a local `.env` (see `.env.example`).

### 3. Authorize each inbox (3 × 1 min — no sign-outs)
```bash
pip install -r requirements.txt
python scripts/google_oauth.py   # browser opens -> pick account -> Allow
```
Run it three times, picking a different account each time. Collect the three
refresh tokens into `GMAIL_ACCOUNTS_JSON` (format in `.env.example`).

### 4. Deploy to Render (5 min)
1. Push this folder to a private GitHub repo.
2. Render dashboard → New → **Blueprint** → select the repo. `render.yaml`
   creates: web service + worker + Postgres.
3. Fill the `assistant-env` group: `ANTHROPIC_API_KEY`, `GOOGLE_CLIENT_ID`,
   `GOOGLE_CLIENT_SECRET`, `GMAIL_ACCOUNTS_JSON`, and `PUBLIC_BASE_URL`
   (the web service URL Render assigns, e.g. `https://assistant-web-xxxx.onrender.com`).
4. Deploy. Check `https://<web-url>/health` shows all three inboxes.

### 5. Seed trusted contacts
Auto-send only ever happens for contacts marked trusted. Insert them via the
Render Postgres shell (or ask Claude to prep the SQL):
```sql
INSERT INTO contacts (id, email, name, company, role, entity, trusted)
VALUES ('1', 'warehouse@example.com', 'Warehouse Mgr', 'Opa-locka WH', 'warehouse', 'shared', 'yes');
```
Everyone else gets drafts, never auto-sends.

## What it does, day one
- Polls all three inboxes every 5 min.
- Routine replies to trusted contacts → sent automatically, logged.
- Everything else → Gmail draft + approval email with one-click Approve/Deny links.
- Urgent items (customs hold, demurrage, chargeback) → immediate alert.
- 8am & 8pm EST digests.

## Flipping on WhatsApp (when Meta verification completes)
1. Meta for Developers → app → WhatsApp → register the Baci number (Cloud API,
   voice verification works for the Google Voice number; Twilio is the fallback).
2. Set webhook URL `https://<web-url>/webhooks/whatsapp` with your
   `WHATSAPP_VERIFY_TOKEN`; subscribe to `messages`.
3. Fill `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_APPROVER_NUMBER` env
   vars → redeploy. Approvals and escalations move to WhatsApp buttons
   automatically; email stays as backup.

## Roadmap
Phase 2: QuickBooks/Stripe/PayPal/Shopify → Jeff investment & true-margin P&L.
Phase 3: Import docs sweep, landed-cost ledger, Shopify inbound inventory.
Phase 4: Label approval queue (Eien auto-prep; Baci packing-list → box-table flow).
Phase 5: Forwarder RFQ engine with all-in quote comparison.
