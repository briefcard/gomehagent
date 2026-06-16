# Admin Agent — Exhaustive Skills Catalog
*Playbooks for the operations/admin agent, grounded in the tools and processes built*
*Prepared for Gomeh Saias · June 15, 2026*

Each skill is a structured playbook: a defined methodology, the tools it uses, a consistent output, and the small-business value it delivers. **[Built]** = the capability exists today. **[Proposed]** = a high-value playbook to add. Tools available: Gmail (3 inboxes), Google Drive + Sheets, Google Calendar, Shopify (2 stores), the document registry/catalog, shipment & RFQ records, deadline & expense ledgers, contacts, WhatsApp interface, usage logging.

---

## 1. Inbox & Communication

**Triage & Bucketing** *[Built]* — Classifies every inbound email across all inboxes into labeled buckets, applies Gmail labels, marks orders unread for visibility. *Value:* the owner opens an inbox that's already sorted; nothing important hides in noise.

**Draft Reply (voice-matched)** *[Built]* — Drafts grounded replies in the owner's learned per-inbox voice, with correct signatures, looking up real data first. *Value:* replies that read like the owner wrote them, without the owner writing them.

**Routine Auto-Reply** *[Built]* — Auto-sends only tool-verified, low-risk replies once enabled. *Value:* the repetitive 40% of email answers itself.

**Deny-to-Rule Learning** *[Built]* — A denied draft + reason becomes a permanent writing rule. *Value:* the agent stops repeating mistakes; quality compounds.

**Reply-Quote Resolution** *[Built]* — When the owner replies to a specific agent message, the agent knows exactly which one. *Value:* precise back-and-forth without re-explaining context.

**Smart Unsubscribe / Noise Triage** *[Proposed]* — Identifies recurring promo/newsletter senders and proposes bulk unsubscribe or auto-archive rules. *Value:* a permanently quieter inbox, not just sorted noise.

**VIP / Relationship Watch** *[Proposed]* — Flags first contact or re-engagement from high-value senders (big clients, key suppliers) and surfaces relationship history. *Value:* the owner never accidentally lets an important relationship go cold.

---

## 2. Customer Service

**Order-Status Answer** *[Built]* — Looks up the order in Shopify, returns status + tracking, drafts the reply. *Value:* "where's my order?" answered factually in seconds, both stores.

**Refund/Cancellation Ladder** *[Built]* — Pushes back constructively first (replacement, exchange, troubleshooting), escalates only if unresolvable, never claims processed before it is. *Value:* protects revenue while keeping customers happy; no false promises.

**Complaint Handling** *[Built]* — Routes serious issues (defective/wrong/damaged) to drafts for review with order context attached. *Value:* hard conversations handled with full data, never auto-sent blindly.

**Clarifying-Question Auto-Reply** *[Built]* — Requests for missing info get a polite clarifying reply automatically. *Value:* keeps tickets moving without owner involvement.

**Review/Feedback Triage** *[Proposed]* — Detects review-request or feedback emails, drafts responses, logs sentiment themes. *Value:* turns scattered feedback into a usable signal.

**Repeat-Issue Pattern Detection** *[Proposed]* — Spots when multiple customers report the same problem (a defective batch, a shipping delay) and alerts the owner. *Value:* catches a systemic problem before it becomes ten angry customers.

---

## 3. Document & Data Management

**Three-Phase Doc Sweep** *[Built]* — Pulls every attachment, dedups by content hash, reads each, clusters into orders globally, files one-order-one-folder. *Value:* import paperwork organized correctly without manual filing.

**Generalized Organize** *[Built]* — Same engine for any category (receipts, subscriptions, contracts) into any Drive, grouped by order/vendor/month; files attachment-less emails as Docs. *Value:* "organize my X" works for anything in the inbox.

**Content-Based Refile (approval-gated)** *[Built]* — Reads files in the intake area, builds a tether-map move plan, files only on approval. *Value:* fixes messy folders without the owner dragging files.

**Document Registry & Recall** *[Built]* — Every filed doc indexed by counterparty/order/type; instant lookup ("send the BOL for the Primorous order"). *Value:* never hunt through Drive again; the right file in one ask.

**AI Document Catalog (Sheet)** *[Built]* — Master Google Sheet of all files, labeled for use by any agent or human, auto-synced. *Value:* a clean, shareable index the owner (or their accountant, or a future agent) can read at a glance.

**Onboarding-Packet Assembly** *[Built]* — Locates POA, FDA docs, sample invoices across Drive + email into one packet. *Value:* the standing documents a new vendor always asks for, assembled once.

**Duplicate & Version Cleanup** *[Proposed]* — Scans a folder for near-duplicates and stale versions, proposes consolidation. *Value:* a Drive that stays clean as it grows, not just at setup.

**Contract/Document Expiry Watch** *[Proposed]* — Reads filed contracts/agreements for renewal/expiry dates, adds them to the deadline ledger. *Value:* never miss a contract renewal or auto-renew trap.

---

## 4. Logistics & Imports

**RFQ Launch & Tracking** *[Built]* — One message sends all-in quote requests to all forwarders, records quotes, compares, chases non-responders. *Value:* best freight price without the owner managing five email threads.

**Shipment Records & Tethering** *[Built]* — Structured record per shipment, all reference numbers tied to one entity, docs have/missing tracked. *Value:* one source of truth for "where's this shipment and what's missing."

**Shipment & Quote Audit** *[Built]* — Opus reviews 90 days of logistics threads, surfaces open shipments, pending quotes, prepared follow-up drafts. *Value:* nothing stalls for months because data was scattered.

**Inbound Inventory Logging** *[Proposed]* — On booking, creates a Shopify inbound transfer; on arrival, confirms counts against the packing list. *Value:* inventory and landed cost captured at the source, not reconstructed later.

**Landed-Cost Tracking** *[Proposed]* — Logs freight, duties, fees per shipment for true per-unit cost. *Value:* the owner finally knows what a product actually costs to land.

**Customs/Demurrage Watch** *[Built]* — Escalates customs holds and storage-charge risk immediately. *Value:* avoids expensive demurrage and clearance delays.

---

## 5. Calendar & Scheduling

**Event Creation w/ Guests** *[Built]* — Creates events and emails invitations to attendees. *Value:* meetings scheduled and invited from a single instruction.

**Meeting-from-Email Detection** *[Built]* — Spots meeting proposals in email, offers to calendar them with suggested invitees from contacts. *Value:* proposed calls actually make it onto the calendar.

**Deadline-to-Calendar** *[Built]* — Extracted deadlines (trade shows, customs, payments) get added with context on request. *Value:* commitments leave the inbox and become scheduled, visible time.

**Daily/Weekly Schedule Brief** *[Proposed]* — Summarizes the day/week ahead, flags conflicts and prep needed. *Value:* the owner starts each day knowing exactly what's on it.

**Smart Rescheduling** *[Proposed]* — Proposes new times around existing commitments and drafts the reschedule notes. *Value:* the friction of moving meetings handled.

---

## 6. Money & Deadlines

**Deadline Ledger & Alerts** *[Built]* — Captures money-dated items from email, alerts at 3 days, shows 7-day view in digest. *Value:* no late fees, no missed renewals, no dropped payment dates.

**Expense Receipt Capture** *[Built]* — Logs receipts (vendor/amount/date) to a ledger as they arrive. *Value:* tax-deductible expenses captured year-round, not scrambled in April.

**Subscription Watch** *[Built]* — Escalates renewals/price increases/trial-ends that will charge soon. *Value:* catches creeping software costs and auto-renews before they hit.

**Tax-Receipt Export** *[Proposed]* — Compiles the expense ledger into an accountant-ready spreadsheet with linked receipts. *Value:* hands the CPA a finished file instead of a shoebox.

**Invoice Chasing (AR)** *[Proposed]* — Tracks money owed to the owner, drafts tone-matched reminders by aging. *Value:* faster payment without awkward manual follow-ups.

**Spend Pattern Flags** *[Proposed]* — Notices unusual or duplicate charges in receipts/notifications. *Value:* catches billing errors and surprise charges early.

---

## 7. Oversight & Proactivity

**Daily Review ("expert second look")** *[Built]* — Reasons across all inboxes, shipments, RFQs, deadlines; flags stalls, untracked deadlines, things that don't add up; names the top priority. *Value:* a conscientious manager who checks whether everything still makes sense — every morning.

**Auto Follow-Up Chasing** *[Built]* — Outbound mail that expects a reply is chased after 3 days, escalated after 6. *Value:* loops close themselves; the owner stops being the bottleneck.

**Morning/Evening Digest** *[Built]* — Twice-daily summary of what was handled, what's pending, what's due. *Value:* full situational awareness in two glances a day.

**Weekly Cost Report** *[Built]* — API spend, cache savings, projected monthly. *Value:* the owner sees the agent's own running cost and that it's controlled.

**Cross-Agent Lessons** *[Built]* — Generalizable corrections shared across all current and future agents. *Value:* one correction improves the whole operation, permanently.

**Weekly Business Pulse** *[Proposed]* — One-page roll-up: orders, cash-dated items, open shipments, customer issues, top 3 to-dos. *Value:* the Monday-morning "state of the business" without pulling it together by hand.

**Anomaly Watch** *[Proposed]* — Flags unusual patterns (order spike/drop, a supplier going quiet, a cost jump). *Value:* early warning the owner would otherwise notice too late.

---

## 8. Interface & Control

**WhatsApp Command Agent** *[Built]* — Natural-language operation by text, voice note, or forwarded file; clarify-before-bulk. *Value:* run the back office from your pocket, conversationally.

**Voice-Note Handling** *[Built]* — Transcribes and executes spoken instructions. *Value:* dictate a task walking through the warehouse; it's done by your desk.

**Document-in-Conversation** *[Built]* — Forwarded files are read in context and filed/answered/recorded as the conversation implies. *Value:* drop a doc, it knows what to do with it.

**Approval Inline (Approve/Deny/Edit)** *[Built]* — Full draft shown on WhatsApp with one-tap actions. *Value:* approve work from anywhere without opening email.

---

## Summary: where the value lands for a small business owner

The through-line is **the owner stops being the single point of failure.** Email is sorted and largely answered; customers get fast, factual service; documents file and find themselves; freight and deadlines don't slip; receipts are captured for taxes as they arrive; and every morning something conscientious checks whether the whole picture still makes sense. The owner trades hours of low-leverage admin for a few taps of approval — and the agent gets more reliable every week it's corrected.

**Highest-impact gaps to build next (in order):** Tax-Receipt Export, Invoice Chasing (AR), Landed-Cost Tracking, Weekly Business Pulse, Contract Expiry Watch. These convert captured data into the financial clarity and dropped-ball prevention that owners feel most.
