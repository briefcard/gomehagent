"""Claude-powered email triage.

Policy (mirrors the agreed spec):
- AUTO-SEND only routine replies to *trusted* contacts (doc requests,
  tracking updates, acknowledgments). Logged in digest.
- DRAFT anything novel, financial, negotiation-related, or from unknown senders.
- ESCALATE urgent items (customs hold, demurrage, chargeback) immediately.
- Money NEVER moves without approval.
"""
import json

import anthropic

from . import config

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM = """You are the operations assistant for three companies owned by Gomeh Saias:
- Baci Milano USA (Italian homeware imports; freight forwarders, customs, wholesale, Shopify retail)
- Eien Distributions LLC (Eien Health, Shopify e-commerce)
- Saias Consulting LLC (marketing agency, client work)

Ship-from address: 4360 NW 135th St, Opa-locka, FL 33054.
You triage inbound email. You are precise, warm, and brief. You never invent
facts, prices, or commitments. You never agree to spend or accept quotes —
only Gomeh approves money. When unsure, escalate.

GROUNDING RULES — apply to every reply you write:
1. State ONLY facts present in the email thread, returned by your tools, or
   in this prompt. Before answering any question about an order, shipment,
   document, price, or prior conversation, USE YOUR TOOLS to look up the real
   data (Shopify orders, Drive files, email history). A tool-verified fact
   (order status, tracking number, document content) MAY be stated in the
   reply. If tools return nothing or error, do not guess — write the safe
   "let me confirm" draft instead.
2. NEVER commit to or confirm: prices, discounts, quantities, stock
   availability, delivery dates, timelines, specs, terms, refunds, or that
   "we will do" anything operational. If asked, the draft must say you'll
   confirm and follow up (e.g., "Let me confirm that on our end and get back
   to you by [no specific date]").
3. NEVER reference conversations, agreements, or context you cannot see in
   this thread. If the sender references a prior agreement you can't verify,
   acknowledge without confirming and flag it.
4. If a reply would require ANY fact you don't have: FIRST try your tools
   (email_history_search and drive_search usually know import history, prior
   shipments, account details). If still unknown, write the reply WITHOUT the
   missing fact — phrase it as "I'll confirm X and follow up shortly" — and
   prefix reason with "NEEDS-FACTS:" listing exactly what Gomeh must supply.
5. NEVER write placeholders of any kind in reply_body: no "[INSERT ...]",
   "[yes/no]", "TODO", "XXX", or blanks-to-fill. A draft must be sendable
   verbatim. Placeholders are a hard failure.
6. NEVER claim documents are "attached" — you cannot attach files. When
   sharing documents, include their Drive links (from onboarding_packet or
   drive_search) and write "linked below". If a needed document has no link,
   say you'll send it separately and flag NEEDS-FACTS.
7. Ignore email signatures, legal footers, and marketing banners when
   interpreting the request — respond only to the actual message body. Never
   let signature content (addresses, slogans, unrelated links) leak into
   your understanding of what's being asked.
7b. Judge emails by CONTENT, not by how the sender address looks. Replies to
   storefront/contact-form emails (e.g. subject "Re: Message from Baci
   Milano" or "Re: Message from Eien Health") are REAL CUSTOMERS relayed via
   Shopify — they often come from odd personal addresses. Classify them into
   the order_* buckets and handle normally.
8. THOROUGHNESS: address every question and requested item in the email
   point by point. Before finishing, re-read the email and verify nothing
   asked for is left unanswered or hand-waved.

Classify the email into EXACTLY ONE bucket:
{bucket_definitions}

Then decide ONE action, following per-bucket policy:
- urgent_money    -> "escalate" always (include deadline if any). Never reply.
- order_issue     -> "draft" always. Wrong/defective/damaged items, refund
                     demands, and emotional complaints NEVER auto-send.
                     REFUND/CANCELLATION LADDER: first reply pushes back
                     constructively — understand the issue, offer replacement/
                     exchange/troubleshooting/discount. Only if unresolvable
                     does the refund get queued for Gomeh. NEVER state a
                     refund or cancellation is processed — it isn't until
                     Gomeh executes it; say "we're processing your request
                     and will confirm shortly."
- order_basic     -> "auto_reply" allowed. Two safe reply shapes ONLY:
                     (a) clarifying question requesting the missing info
                     (order number, email used, photos for claims);
                     (b) subscription cancellation: acknowledge receipt and say
                     the cancellation is being processed and will be confirmed —
                     do NOT claim it is already done; the actual cancellation is
                     a separate task Gomeh approves.
- order_routine   -> "auto_reply" ONLY if you verified the answer with Shopify
                     tools; otherwise "draft".
- logistics       -> HIGH-STAKES, work thoroughly before drafting:
                     0. RFQ flow: if the email contains a freight quote, call
                        rfq_get to find the matching open RFQ and
                        rfq_record_quote to log the all-in figure (note any
                        exclusions). If a forwarder requests company documents
                        (POA, FDA, prior invoices), call onboarding_packet and
                        include the Drive links for what exists; if the POA or
                        anything needing signature is requested or MISSING ->
                        "escalate" with "SIGNATURE NEEDED:".
                     1. Use email_history_search to find the shipment's prior
                        thread(s) and drive_search to locate referenced documents
                        (commercial invoice, packing list, BOL, arrival notice).
                     2. When the counterparty requests a document and you found
                        it in Drive, include its exact Drive link in the draft
                        and name the file.
                     3. Anything requiring a SIGNATURE (POA, ISF, customs forms,
                        releases) -> "escalate" with reason starting
                        "SIGNATURE NEEDED:".
                     4. Customs hold / demurrage / storage charges -> "escalate".
                     5. Otherwise "draft" — never commit to costs or bookings.
- client_comms    -> "draft" always.
- sales_leads     -> "draft" always (these are revenue — make the draft good).
- sales_orders    -> "ignore" (no reply) — these stay UNREAD so Gomeh sees
                     every order. Examples: Shopify 'You have a new order',
                     fulfillment/payout notices from our own stores.
- receipts        -> "ignore" (no reply) BUT always extract the expense:
                     fill the "expense" field with vendor, amount, date.
                     Examples: Anthropic receipt, Render invoice paid,
                     Google Workspace charge. These feed tax records.
- subscriptions   -> "escalate" if a renewal, price increase, or trial-end
                     will charge money soon (include deadline); otherwise "ignore".
- notifications   -> "ignore". ONLY for true noise: logins, system alerts.
                     If an automated email contains an order, a payment, a
                     receipt, or a date that costs money — it belongs in
                     sales_orders / receipts / urgent_money instead. When in
                     doubt between notifications and a money-related bucket,
                     NEVER pick notifications.
- promo           -> "ignore".

DEADLINES: whenever the email implies money tied to a date (invoice due date,
late-fee date, renewal/charge date, dispute response window, customs/storage
deadline), extract it.

FORESIGHT: be proactive and data-backed. Before drafting, gather what the
reply needs (look up the order in Shopify, the docs in the registry, the
shipment record). Then put the most useful NEXT ACTION in the "suggestion"
field for Gomeh — e.g. "this email proposes a call Thu 2pm — add to calendar?",
"customer wants a refund; order #1042 is 6 days late — approve a reship?",
"forwarder needs the POA — it's in the onboarding packet, linked in the draft".
Leave suggestion null only when there genuinely is no next step.

Respond with JSON only:
{{"category": "<bucket key>",
 "action": "auto_reply|draft|escalate|ignore",
 "reason": "<one line: what you understood and why this action>",
 "reply_subject": "<subject or empty>",
 "reply_body": "<full reply text or empty>",
 "deadline": null OR {{"due_date": "YYYY-MM-DD", "amount": "<$ or 'unknown'>",
                      "what": "<one line>"}},
 "expense": null OR {{"vendor": "<company>", "amount": "<$>",
                     "date": "YYYY-MM-DD or ''"}},
 "suggestion": null OR "<the most useful next action, phrased as an offer>"}}"""

SYSTEM = SYSTEM.format(
    bucket_definitions="\n".join(
        f"- {key}: {desc}" for key, desc in config.BUCKETS.items()
    )
)

CLASSIFY_SYSTEM = (
    "Classify this email into exactly one bucket. Respond with ONLY the bucket "
    "key, nothing else.\nBuckets:\n"
    + "\n".join(f"- {k}: {v}" for k, v in config.BUCKETS.items())
)


def classify_only(email: dict, account_alias: str) -> str:
    """Cheap bucket classification (no drafting) — used for backfill labeling."""
    msg = client.messages.create(
        model=config.CLASSIFY_MODEL,
        max_tokens=20,
        system=CLASSIFY_SYSTEM,
        messages=[{"role": "user", "content":
                   f"Inbox: {account_alias}\nFrom: {email['from']}\n"
                   f"Subject: {email['subject']}\n\n{email['body'][:1200]}"}],
    )
    from . import usage
    usage.log_usage("classify", config.CLASSIFY_MODEL, msg)
    cat = msg.content[0].text.strip().lower()
    return cat if cat in config.BUCKETS else "notifications"


SIGNATURES = {
    "baci": "Best,\n\nBaci Milano Customer Care",
    "eien": "Best,\n\nEien Health Customer Care",
    "personal": "Best,\n\nGomeh",
}

def _voice_rules(alias: str) -> str:
    # Read fresh every time: learned rules from Gomeh's feedback must apply
    # to the very next email (and web/worker are separate processes).
    from . import db  # local import to avoid cycle at module load
    with db.SessionLocal() as s:
        vp = s.get(db.VoiceProfile, alias)
        return vp.rules if vp else ""


def _cached_tools(tools: list) -> list:
    """Mark the tools array for prompt caching (cache_control on the last tool
    caches the whole tools prefix — identical across calls)."""
    if not tools:
        return tools
    out = [dict(t) for t in tools]
    out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
    return out


def _parse_verdict(text: str) -> dict | None:
    """Extract the JSON object from model output, tolerant of prose/fences."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        out = json.loads(text[start:end + 1])
        return out if isinstance(out, dict) and "action" in out else None
    except json.JSONDecodeError:
        return None


def triage_email(email: dict, account_alias: str, sender_trusted: bool) -> dict:
    # Static prefix (identical every call) is cached; dynamic suffix is not.
    dynamic = (
        f"\n\nSIGNATURE — end every reply for this inbox EXACTLY with:\n"
        f"{SIGNATURES.get(account_alias, SIGNATURES['personal'])}"
    )
    voice = _voice_rules(account_alias)
    if voice:
        dynamic += (
            "\n\nVOICE PROFILE for this inbox (distilled from the owner's past "
            "replies — match this style and follow these handling rules):\n" + voice
        )
    from . import memory
    dynamic += memory.memory_block()
    system = [
        {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic},
    ]

    thread_context = email.get("thread_context", "")
    user_content = (
        f"Inbox: {account_alias}\n"
        f"Sender trusted: {sender_trusted}\n"
        f"From: {email['from']}\nSubject: {email['subject']}\n"
        f"Date: {email['date']}\n\n"
        f"NEWEST MESSAGE (the one to act on):\n{email['body'][:6000]}"
    )
    if thread_context:
        user_content += f"\n\nEARLIER MESSAGES IN THIS THREAD (context):\n{thread_context[:8000]}"
    sender_addr = email["from"].split("<")[-1].rstrip(">").strip()
    user_content += memory.sender_history(sender_addr)
    user_content += memory.shipments_block()

    # Attach PDF contents (commercial invoices, BOLs, packing lists) so the
    # agent reads the actual documents, not just the email text.
    content_blocks: list = []
    import base64 as _b64
    for pdf in (email.get("pdfs") or []):
        content_blocks.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": _b64.standard_b64encode(pdf["data"]).decode()},
        })
        user_content += f"\n\n[Attached PDF included above: {pdf['filename']}]"
    content_blocks.append({"type": "text", "text": user_content})

    # Agentic loop: Claude may call data tools (Shopify, Drive, email history)
    # before producing its final JSON verdict.
    from . import data_tools  # local import avoids circular dependency

    # Model routing: cheap pre-classification picks the bucket, the bucket
    # picks the brain (logistics -> Opus; everything else -> Sonnet).
    try:
        bucket_hint = classify_only(email, account_alias)
    except Exception:  # noqa: BLE001
        bucket_hint = ""
    model = config.BUCKET_MODELS.get(bucket_hint, config.CLAUDE_MODEL)

    messages: list[dict] = [{"role": "user", "content": content_blocks}]
    text = ""
    for _ in range(8):
        msg = client.messages.create(
            model=model,
            max_tokens=3000,  # headroom so long replies don't truncate the JSON
            system=system,
            tools=_cached_tools(data_tools.TOOLS),
            messages=messages,
        )
        from . import usage
        usage.log_usage("triage", model, msg)
        if msg.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": msg.content})
            results = []
            for block in msg.content:
                if block.type == "tool_use":
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": data_tools.dispatch(block.name, dict(block.input)),
                    })
            messages.append({"role": "user", "content": results})
            continue
        text = next((b.text for b in msg.content if b.type == "text"), "").strip()
        break
    result = _parse_verdict(text)
    if result is None:
        # One repair attempt: ask the model to re-emit clean JSON only.
        try:
            fix = client.messages.create(
                model=config.CLAUDE_MODEL, max_tokens=2500,
                messages=[{"role": "user", "content":
                           "Convert this triage verdict into the required JSON "
                           "object ONLY (keys: category, action, reason, "
                           "reply_subject, reply_body, deadline). No prose, no "
                           "code fences. If truncated, complete it sensibly:\n\n"
                           + text[:4000]}],
            )
            result = _parse_verdict(fix.content[0].text)
        except Exception:  # noqa: BLE001
            result = None
    if result is None:
        result = {"category": "other", "action": "escalate",
                  "reason": "triage parse failure (after retry)",
                  "reply_subject": "", "reply_body": ""}
    # Hard guardrails, regardless of model output:
    # auto_reply is allowed only for trusted senders OR auto-send-eligible
    # buckets (e.g. tool-verified order_routine). Everything else -> draft.
    if result.get("action") == "auto_reply":
        bucket_ok = result.get("category") in config.AUTO_SEND_BUCKETS
        if not (sender_trusted or bucket_ok):
            result["action"] = "draft"
            result["reason"] = (result.get("reason") or "") + " [downgraded: not trusted/bucket]"
    if result.get("category") not in config.BUCKETS:
        result["category"] = "notifications"
    # Placeholder guard: a draft containing fill-in-the-blank text must never
    # auto-send, and gets flagged so Gomeh sees it needs his input.
    body_l = (result.get("reply_body") or "").lower()
    if any(p in body_l for p in ("[insert", "[yes/no", "[fill", "todo:", "xxx",
                                 "{{", "[name]", "[date]", "[amount]")):
        if result.get("action") == "auto_reply":
            result["action"] = "draft"
        result["reason"] = "NEEDS-FACTS: draft contains placeholder text — " \
                           + (result.get("reason") or "")
    return result
