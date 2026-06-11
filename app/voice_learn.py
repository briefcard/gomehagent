"""One-time (per inbox) voice learning: read past sent emails, distill a
style + handling-rules profile, store in DB. Runs automatically at worker
startup if a profile doesn't exist yet. Delete a row from voice_profiles to
force a re-learn."""
import logging

import anthropic

from . import config, db, gmail_client

log = logging.getLogger("voice")
client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

PROMPT = """Below are real emails the owner sent from the "{alias}" inbox.
Distill a concise voice profile (max ~400 words) that a drafting assistant
will follow. Cover:
1. Tone & register (formality, warmth, brevity, typical phrasing).
2. Greeting and opening conventions.
3. How they handle common situations you observe (order issues, quote
   requests, follow-ups, scheduling, chasing).
4. Things they consistently do or avoid.
5. Recurring topics/products/partners worth knowing.
Output the profile only — no preamble.

EMAILS:
{emails}"""


def ensure_profiles() -> None:
    for alias in config.GMAIL_ACCOUNTS:
        with db.SessionLocal() as s:
            if s.get(db.VoiceProfile, alias):
                continue
        try:
            sent = gmail_client.fetch_sent(alias, max_results=50)
            if not sent:
                log.info("[%s] no sent mail found; skipping voice profile", alias)
                continue
            joined = "\n\n=====\n\n".join(sent)[:120000]
            msg = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=1000,
                messages=[{"role": "user",
                           "content": PROMPT.format(alias=alias, emails=joined)}],
            )
            rules = msg.content[0].text.strip()
            with db.SessionLocal() as s:
                s.add(db.VoiceProfile(alias=alias, rules=rules))
                s.commit()
            log.info("[%s] voice profile learned (%d sent emails)", alias, len(sent))
        except Exception:  # noqa: BLE001
            log.exception("voice learning failed for %s", alias)
