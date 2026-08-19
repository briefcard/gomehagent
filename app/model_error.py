"""Say what the model provider actually refused, and what to do about it.

Written after a real incident. Every model-drafted reply stopped, and the
reason reached the console as:

    BadRequestError: Error code: 400 - {'type': 'error', 'error':
    {'type': 'invalid_request_error', 'message': 'You have reached your specifi

Truncated at 120 characters, one word before the cause. The account had hit its
Anthropic spend limit — a thirty-second fix in a billing console — and instead
it read as an unexplained 400, was assumed to be a code regression, and sent
somebody through the ban list, the validator and a freshly installed system
looking for it.

Two failures in that, and both are the same failure:

  · A cap that cuts the message exactly where the informative half begins.
  · An operational condition reported as an exception class. "BadRequestError"
    is what the library called it; "the account is out of budget" is what
    happened, and only one of those tells anybody what to do next.

So this classifies, rather than truncating. The classes are the ones with
genuinely different responses: pay, wait, fix a key, or read the error.
"""
from __future__ import annotations

import json
import re

#: (needle in the provider's message, what it is, what to do) — matched in
#: order. Kept as data so a new provider condition is a row, not a branch.
_KNOWN = (
    ("reached your specified", "spend limit",
     "the model account has hit the usage limit set on it — raise or reset it "
     "in the Anthropic console. Nothing is wrong with the draft or the rules."),
    ("credit balance is too low", "out of credit",
     "the model account is out of credit — top it up in the Anthropic console."),
    ("rate_limit", "rate limited",
     "too many calls at once. This clears by itself; if it persists the "
     "account's per-minute limit is too low for the poll cadence."),
    ("overloaded", "provider overloaded",
     "the provider is busy. This clears by itself and the next cycle will "
     "retry."),
    ("authentication", "bad key",
     "ANTHROPIC_API_KEY is set but rejected — check it has not been rotated "
     "or revoked."),
    ("invalid x-api-key", "bad key",
     "ANTHROPIC_API_KEY is set but rejected — check it has not been rotated "
     "or revoked."),
    ("max_tokens", "request too large",
     "the request exceeded the model's limit — the bundle is too big for the "
     "window, not a fault in the account."),
)


def provider_message(exc: Exception) -> str:
    """The provider's own sentence, dug out of whatever the SDK wrapped it in.

    SDK exceptions stringify as `Error code: 400 - {dict}`, so the useful text
    is inside a repr of a dict inside a string. Parsed rather than sliced,
    because slicing is what lost it the first time.
    """
    raw = str(exc)
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        msg = (body.get("error") or {}).get("message") or body.get("message")
        if msg:
            return str(msg)
    # `{'message': '...'}` — single quotes, so not JSON. Regex before json.
    m = re.search(r"['\"]message['\"]\s*:\s*['\"](.+?)['\"]\s*[,}]", raw, re.S)
    if m:
        return m.group(1)
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            d = json.loads(m.group(0).replace("'", '"'))
            return str((d.get("error") or {}).get("message") or raw)
        except Exception:                                        # noqa: BLE001
            pass
    return raw


def explain(exc: Exception) -> str:
    """One line an operator can act on, never a truncated stack string."""
    msg = provider_message(exc)
    low = msg.lower()
    for needle, what, advice in _KNOWN:
        if needle in low:
            return f"{what}: {advice}"
    # Unrecognised: give the WHOLE provider message. A cap here is what caused
    # the incident this file is named after.
    return f"{exc.__class__.__name__}: {msg}"


def is_operational(exc: Exception) -> bool:
    """True when the account or the provider is the problem, not the draft.

    Callers use this to keep an operational stop out of the knowledge backlog:
    a spend limit is not a missing objection, and filing it as one puts a
    billing problem on the authoring queue where no amount of writing fixes it.
    """
    low = provider_message(exc).lower()
    return any(n in low for n, _w, _a in _KNOWN)
