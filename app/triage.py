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
1. State ONLY facts present in the email thread itself or in this prompt.
   The ship-from address above is the only standing company fact you know.
2. NEVER commit to or confirm: prices, discounts, quantities, stock
   availability, delivery dates, timelines, specs, terms, refunds, or that
   "we will do" anything operational. If asked, the draft must say you'll
   confirm and follow up (e.g., "Let me confirm that on our end and get back
   to you by [no specific date]").
3. NEVER reference conversations, agreements, or context you cannot see in
   this thread. If the sender references a prior agreement you can't verify,
   acknowledge without confirming and flag it.
4. If a reply would require ANY fact you don't have, still write the best
   safe draft but prefix reason with "NEEDS-FACTS:" and list what's missing
   so Gomeh fills it in before approving.

Classify the email and decide ONE action:
- "auto_reply": ONLY if sender_trusted is true AND the reply is routine
  (sending requested shipment docs you reference but don't attach, confirming
  receipt, providing tracking/status, scheduling). The reply must make no
  financial commitment of any kind.
- "draft": write a reply for Gomeh to review (anything financial, novel,
  negotiation, quotes, complaints, unknown senders).
- "escalate": urgent — customs hold, demurrage risk, chargeback, angry VIP,
  payment problem. Include a one-line reason.
- "ignore": newsletters, promos, spam, notifications needing no reply.

Respond with JSON only:
{"category": "forwarder|order|invoice|client|junk|other",
 "action": "auto_reply|draft|escalate|ignore",
 "reason": "<one line>",
 "reply_subject": "<subject or empty>",
 "reply_body": "<full reply text or empty>"}"""


SIGNATURES = {
    "baci": "Best,\n\nBaci Milano Customer Care",
    "eien": "Best,\n\nEien Health Customer Care",
    "personal": "Best,\n\nGomeh",
}

_voice_cache: dict[str, str] = {}


def _voice_rules(alias: str) -> str:
    if alias not in _voice_cache:
        from . import db  # local import to avoid cycle at module load
        with db.SessionLocal() as s:
            vp = s.get(db.VoiceProfile, alias)
            _voice_cache[alias] = vp.rules if vp else ""
    return _voice_cache[alias]


def triage_email(email: dict, account_alias: str, sender_trusted: bool) -> dict:
    system = SYSTEM
    system += (
        f"\n\nSIGNATURE — end every reply for this inbox EXACTLY with:\n"
        f"{SIGNATURES.get(account_alias, SIGNATURES['personal'])}"
    )
    voice = _voice_rules(account_alias)
    if voice:
        system += (
            "\n\nVOICE PROFILE for this inbox (distilled from the owner's past "
            "replies — match this style and follow these handling rules):\n" + voice
        )

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

    msg = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    text = msg.content[0].text.strip()
    # tolerate code fences
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {"category": "other", "action": "escalate", "reason": "triage parse failure",
                  "reply_subject": "", "reply_body": ""}
    # Hard guardrail: never auto-send to untrusted senders, regardless of model output.
    if result.get("action") == "auto_reply" and not sender_trusted:
        result["action"] = "draft"
        result["reason"] = (result.get("reason") or "") + " [downgraded: sender not trusted]"
    return result
