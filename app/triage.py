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

from . import config, tools as _tools

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
5b. CC IS SUPPORTED. You CAN cc people. On a reply, PRESERVE the thread's
   existing recipients by default (reply-all): carry the original To and Cc
   (minus our own address and duplicates) into the "cc" field so no one is
   dropped from the conversation. Add or remove CCs when the context clearly
   calls for it. Never silently drop people who were on the thread.
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

WATCH SIGNALS (add to "suggestion" when present):
- VIP / relationship: first contact or re-engagement from a high-value sender
  (big client, key supplier, press) -> note it and the relationship history.
- Review/feedback request -> flag for a response and note sentiment.
- Repeat issue: if this mirrors recent order_issue emails (same product,
  same defect, same delay), say so — it may be systemic, not a one-off.

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
 "reply_cc": "<comma-separated CC addresses to preserve/add, or empty>",
 "claim_ids": ["<id of each APPROVED CLAIM you actually used, or empty list>"],
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


def classify_only(email: dict, account_alias: str, tenant: str = "") -> str:
    """Cheap bucket classification (no drafting) — used for backfill labeling.

    `tenant` is optional because the backfill path genuinely does not have one;
    the main path does and passes it. Half of all logged calls come through
    here, so leaving it unattributed would leave half the spend report blank.
    """
    msg = client.messages.create(
        model=config.CLASSIFY_MODEL,
        max_tokens=20,
        system=CLASSIFY_SYSTEM,
        messages=[{"role": "user", "content":
                   f"Inbox: {account_alias}\nFrom: {email['from']}\n"
                   f"Subject: {email['subject']}\n\n{email['body'][:1200]}"}],
    )
    from . import usage
    usage.log_usage("classify", config.CLASSIFY_MODEL, msg, tenant=tenant)
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


def _apply_guards(result: dict, tenant: str, sender_trusted: bool,
                  offered_claim_ids: list | None = None,
                  thin: list | None = None) -> dict:
    """The deterministic checks a model verdict must survive before it can send.

    Extracted from the triage loop so they are testable on their own and
    reusable by the generator when it lands. Every one of these is code rather
    than a prompt instruction, for the reason locked decision #2 gives: a prompt
    mostly obeys, a check always blocks, and a model may never validate a model.
    """
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
    # Brand guard: a phrase the client has banned must never leave the building.
    # The KB has held these rules since the knowledge layer was built and the
    # unattended half of the system could not see them — Baci's "made in Italy"
    # ban was enforced nowhere in the code that actually sends mail.
    #
    # This is code, not a prompt instruction, and it fails closed: the rule is
    # in the prompt too (via agent_block), but a prompt mostly obeys and a check
    # always blocks. Locked decision #2 — a model may never validate a model.
    if tenant:
        from . import assurance, grounding, validator
        draft = f"{result.get('reply_subject', '')} {result.get('reply_body', '')}"

        # The SAME matcher the substrate uses, at last.
        #
        # This was a plain `in` test while `validator._banned` next door matched
        # on word boundaries with flexible separators — so on the one path that
        # answers customers, "hand-decorated" was caught and "hand decorated"
        # walked straight through, and "artisan" false-fired inside
        # "artisanal". Two strengths of the same rule, and the weaker one was
        # guarding the live path.
        #
        # `require_citation=False` deliberately: an email answering "where is
        # my order" has no claim to cite, and a guard that fires on every reply
        # is a guard somebody switches off. Only the rules that make an output
        # FALSE are enforced here.
        cited = grounding.verify(offered_claim_ids or [], result.get("claim_ids"))
        result["claim_ids"] = cited
        try:
            report = validator.check(
                tenant, draft, claim_ids=cited,
                entity_key=result.get("entity_key", ""),
                require_citation=False)
        except Exception as exc:                                 # noqa: BLE001
            # A validator that cannot run must not pass the draft. It escalates
            # instead: a human reads it, which is what "we could not check
            # this" actually warrants.
            result["action"] = "escalate"
            result["reason"] = (f"UNCHECKED: the validator raised "
                                f"({exc.__class__.__name__}) — read this one "
                                f"yourself. " + (result.get("reason") or ""))
            return result

        hard = [f for f in report["failures"]
                if f["rule"] in ("banned_claim", "entity_unavailable")]
        # Logged whether it hit or not. A check that only records its failures
        # cannot tell you it is running, and this is the path that actually
        # answers customers — the one where "is the layer switched on" most
        # needs an answer that is not a code reading.
        assurance.record(
            tenant, source="mail", system_key=grounding.SYSTEM_KEY,
            checked=report["checked"],
            caught=[f["rule"] for f in hard],
            verdict="blocked" if hard else "passed",
            grounded=bool(cited),
            thin=list(thin or []))
        if hard:
            result["action"] = "escalate" if result.get("action") == "auto_reply" \
                else result.get("action", "draft")
            # The marker NAMES THE RULE that fired, and `BANNED CLAIM` is kept
            # verbatim from before the validator swap.
            #
            # These prefixes are an interface, not prose: `emailfmt` and
            # `worker` both branch on `NEEDS-FACTS` in exactly this field, so a
            # reason string is read by code as well as by a person. Replacing
            # them with a generic "BLOCKED" quietly widened one marker into two
            # rules and broke the one assertion that had been holding the
            # banned-claim guard since it was written. A rule that fires should
            # say which rule it was, at the front, where a grep finds it.
            marker = {"banned_claim": "BANNED CLAIM",
                      "entity_unavailable": "UNAVAILABLE"}
            head = ", ".join(dict.fromkeys(
                marker.get(f["rule"], f["rule"].upper()) for f in hard))
            result["reason"] = (f"{head}: "
                                + "; ".join(f["detail"] for f in hard)
                                + f" — barred for {tenant}. "
                                + (result.get("reason") or ""))

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


def triage_email(email: dict, account_alias: str, sender_trusted: bool,
                 tenant: str = "") -> dict:
    """Categorise one email and draft a reply.

    ``tenant`` is which client this inbox belongs to. It scopes the tools the
    loop may call, filters working memory to that client, and supplies the brand
    rules the draft must not violate. Without it this function drafts and can
    auto-send with no idea whose voice it is writing in — which is the same hole
    the agent had, in the half that runs unattended.
    """
    from . import grounding, tenants
    tenant = tenant or tenants.for_alias(account_alias)
    # Static prefix (identical every call) is cached; dynamic suffix is not.
    dynamic = (
        f"\n\nSIGNATURE — end every reply for this inbox EXACTLY with:\n"
        f"{SIGNATURES.get(account_alias, SIGNATURES['personal'])}"
    )
    if tenant:
        dynamic += tenants.agent_block(tenant)
    voice = _voice_rules(account_alias)
    if voice:
        dynamic += (
            "\n\nVOICE PROFILE for this inbox (distilled from the owner's past "
            "replies — match this style and follow these handling rules):\n" + voice
        )
    from . import memory
    dynamic += (memory.lessons_block("admin", tenant)
                + memory.memory_block("", tenant)
                # What a person has already looked at and accounted for. This
                # is why the same concern was escalated five times: nothing
                # could tell the model somebody had checked.
                + memory.cleared_block(tenant))

    # THE KNOWLEDGE BASE, on the path that answers customers.
    #
    # `resolve.resolve` had exactly one caller — the skill substrate — so every
    # claim, objection and piece of brand guidance the owner had approved
    # reached registered skills and nothing else. This path, which drafts the
    # replies he actually reads each morning, drafted from a hardcoded prompt.
    # The bundle also carries this system's standing guidance and the edits a
    # human made to its recent drafts (see `resolve._rules`), so the loop that
    # measured itself now feeds itself.
    #
    # The cheap classifier runs FIRST here, not because drafting needs it but
    # because a bucket that never replies must not pay for a bundle: a tier-3
    # resolve runs a semantic search over the archive, and roughly half of
    # inbound is a newsletter. It was already being computed a few lines below
    # to route the model; it is simply computed once, earlier.
    try:
        bucket_hint = classify_only(email, account_alias, tenant)
    except Exception:                                            # noqa: BLE001
        bucket_hint = ""
    ground = grounding.for_mail(tenant, email, bucket=bucket_hint)
    dynamic += ground["text"]
    if ground["thin"]:
        # The gap survives to the prompt rather than being silently absent. A
        # model that does not know it is working without the objections file
        # writes with the same confidence either way.
        dynamic += ("\n\nWHAT THIS ACCOUNT COULD NOT GIVE YOU for this mail: "
                    + "; ".join(ground["thin"][:6])
                    + "\nWrite the reply anyway — thinner and more careful, "
                      "never blocked. Say you will confirm rather than "
                      "asserting anything this did not cover.")
    system = [
        {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic},
    ]

    thread_context = email.get("thread_context", "")
    user_content = (
        f"Inbox: {account_alias} (our address: "
        f"{config.GMAIL_ACCOUNTS.get(account_alias, {}).get('email', '')})\n"
        f"Sender trusted: {sender_trusted}\n"
        f"From: {email['from']}\nTo: {email.get('to', '')}\n"
        f"Cc: {email.get('cc', '')}\n"
        f"Subject: {email['subject']}\n"
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

    # Model routing: the bucket picked above also picks the brain (logistics ->
    # Opus; everything else -> Sonnet). It used to be classified again here —
    # two calls to the same cheap classifier for one email, and two chances for
    # them to disagree about what the mail was.
    model = config.BUCKET_MODELS.get(bucket_hint, config.CLAUDE_MODEL)

    messages: list[dict] = [{"role": "user", "content": content_blocks}]
    text = ""
    for _ in range(8):
        msg = client.messages.create(
            model=model,
            max_tokens=3000,  # headroom so long replies don't truncate the JSON
            system=system,
            tools=_cached_tools(data_tools.tools_for(tenant)),
            messages=messages,
        )
        from . import usage
        usage.log_usage("triage", model, msg, tenant=tenant)
        if msg.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": msg.content})
            results = []
            for block in msg.content:
                if block.type == "tool_use":
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        # Through the same door the kernel uses. This called
                        # `data_tools.dispatch` directly, which applies the
                        # account boundary and files NOTHING — so the busiest
                        # model loop in the system, the one answering mail every
                        # few minutes, contributed no rows to the ledger that
                        # Diagnostics reads. Its platform calls were invisible in
                        # exactly the report you open when mail stops working.
                        "content": _tools.call(
                            block.name, dict(block.input), tenant,
                            source="triage"),
                    })
            messages.append({"role": "user", "content": results})
            continue
        text = next((b.text for b in msg.content if b.type == "text"), "").strip()
        break
    result = _parse_verdict(text)
    if result is None:
        # One repair attempt: ask the model to re-emit clean JSON only.
        # Through the gateway, for two reasons that both bit here. It was the
        # one model call on this path that recorded NO usage — on the path that
        # is 93% of spend — so every repair attempt was free as far as any
        # report could tell. And it read `content[0].text` while the loop eight
        # lines above already knows better and scans for the text block.
        from . import llm
        fix = llm.ask("triage_repair",
                      "Convert this triage verdict into the required JSON "
                      "object ONLY (keys: category, action, reason, "
                      "reply_subject, reply_body, claim_ids, deadline). "
                      "No prose, no "
                      "code fences. If truncated, complete it sensibly:\n\n"
                      + text[:4000],
                      tenant=tenant, max_tokens=2500)
        result = _parse_verdict(fix.text) if fix.ok else None
    if result is None:
        result = {"category": "other", "action": "escalate",
                  "reason": "triage parse failure (after retry)",
                  "reply_subject": "", "reply_body": ""}
    return _apply_guards(result, tenant, sender_trusted,
                         offered_claim_ids=ground["claim_ids"],
                         thin=ground["thin"])
