"""One door to the model.

There were twenty-six `messages.create` calls in this codebase behind eleven
separate `anthropic.Anthropic()` clients, and they disagreed about everything
that is not the prompt:

  * **Attribution.** Nine of the twenty-six called `usage.log_usage`. So
    two thirds of the model spend was invisible, and `Usage.tenant` — already
    on the known-gaps list — could not be filled by callers that were not
    logging at all. A spend figure that omits most of the spend is worse than
    no figure, because it gets believed.
  * **Failure.** `model_error.explain` exists because a spend limit once
    reached the console as a truncated `BadRequestError` and sent somebody
    through the ban list and the validator looking for a billing problem. Two
    of the twenty-six call it.
  * **Absence.** Some sites degrade and say so; some return `""`; some raise.
    A key that expires should read the same way everywhere, and this codebase's
    own first rule is that absence must survive to the output.
  * **Reading the answer.** Every one of them does `msg.content[0].text`.
    That is only true while the first block happens to be text — it is a list
    of blocks, and a thinking or tool_use block in front of the text turns the
    whole call into an AttributeError or a silently wrong string. Nothing has
    enabled thinking yet, so this is a trap rather than a bug, and it is
    exactly the kind that goes off during an unrelated change.

None of that belongs in the caller. A caller knows its prompt and its purpose;
everything else is the same question answered twenty-six times.

**This does not raise.** A provider condition is an operational fact, not an
exception in the caller's control flow, and every consumer here already has a
degraded path it is supposed to take. `Reply.ok` is the gate, `Reply.error`
says what the provider actually refused in words somebody can act on, and
`Reply.degraded` says what was missing before we ever called.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config, model_error, usage

#: Which model each purpose runs on. A map rather than a `config.X` reference
#: at each call site, because that is how `SEO_MODEL` came to be read in one
#: place and `CLAUDE_MODEL` in the nine next to it. A purpose that is not here
#: gets `CLAUDE_MODEL`, which is what every unlisted caller already used.
#:
#: Deliberately NOT a config lookup per purpose: adding a purpose should not
#: require adding an environment variable, and the three that genuinely differ
#: are the three that already had their own setting.
#: Values are the NAME of the config setting, not the value, so the map is read
#: when the call is made rather than frozen at import. A module-level dict of
#: values would go stale the moment anything reassigned a setting, which is the
#: shape of half the tests in this repo.
PURPOSE_MODEL: dict[str, str] = {
    "classify": "CLASSIFY_MODEL",
    "search_filter": "CLASSIFY_MODEL",
    "sweep": "SWEEP_MODEL",
    "seo": "SEO_MODEL",
    # The picture reviewer. It was added without a row here and therefore fell
    # through to CLAUDE_MODEL — which is the right model and was not a
    # decision, exactly what the docstring below warns against. Named so the
    # choice is visible and so it can be moved without editing code: judging
    # whether an image is about the right thing is a vision job and the cheap
    # classifier cannot do it, but a future model might do it better or for
    # less.
    "creative_review": "CREATIVE_REVIEW_MODEL",
}


def model_for(purpose: str) -> str:
    """The model a purpose runs on.

    Data, not a branch. `oauth.configured` was a per-provider ternary that
    ended up telling Canva to set the Meta app secret, and rule 4 of this
    codebase — derive lists from the schema, never by hand — was written from
    it. A new purpose is a row here.
    """
    return (getattr(config, PURPOSE_MODEL.get(purpose, ""), "")
            or config.CLAUDE_MODEL)


@dataclass
class Reply:
    """What came back, including when nothing did."""

    text: str = ""
    blocks: list = field(default_factory=list)
    stop_reason: str = ""
    model: str = ""
    purpose: str = ""
    ok: bool = False
    #: The provider's condition, classified — "the model account has hit the
    #: usage limit set on it", not "BadRequestError: Error code: 400 - {'typ".
    error: str = ""
    #: Why this is thinner than it should be, decided BEFORE the call. Empty
    #: when nothing was missing. Carried so a caller can label its output
    #: rather than quietly producing a worse one.
    degraded: str = ""

    def __bool__(self) -> bool:
        return self.ok


class ModelUnavailable(RuntimeError):
    """The call could not be made or came back refused.

    This module does not raise on its own — `Reply.ok` is the gate. But most of
    the batch jobs already sit inside a `try/except` with a correct fallback for
    exactly this case, and the ONLY thing they lost when the provider failed was
    the reason: an `except Exception: log.exception(...)` printed a truncated
    `BadRequestError` where "the account is out of budget" belonged.

    `text_or_raise` converts a refusal back into an exception carrying the
    CLASSIFIED message, so those handlers keep working unchanged and start
    logging something a person can act on. Use it only where such a handler
    already exists; anywhere else, check `Reply.ok`.
    """


def text_or_raise(reply: "Reply") -> str:
    """The text, or raise `ModelUnavailable` saying what the provider refused."""
    if not reply.ok:
        raise ModelUnavailable(reply.error or reply.degraded or "no model output")
    return reply.text


def _client():
    """Built on use, never at import.

    Eleven modules constructed a client at import time, so importing any of
    them without a key in the environment was already a decision about whether
    the process could start. Tests import all of them.
    """
    import anthropic
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def extract_text(blocks) -> str:
    """The text of a response, whatever else is in front of it.

    `content[0].text` is the idiom this replaces and it is a latent break: the
    content is a LIST of blocks and a thinking or tool_use block may lead it.
    Joining every text block is correct under all of them.
    """
    out = []
    for b in blocks or []:
        if getattr(b, "type", "") == "text":
            out.append(getattr(b, "text", "") or "")
    return "".join(out)


def call(purpose: str, messages: list, *, tenant: str = "", system: str = "",
         model: str = "", max_tokens: int = 1000, tools: list | None = None,
         **extra) -> Reply:
    """One model call, attributed, classified, and safe to fail.

    `purpose` is required and is BOTH the usage tag and the model selector, so
    a call that is not attributed is not expressible. That is the point: the
    nine-of-twenty-six problem was not carelessness, it was that logging was a
    second thing to remember.
    """
    chosen = model or model_for(purpose)
    if not config.ANTHROPIC_API_KEY:
        # Not an error — a known, nameable absence. The caller decides whether
        # it can still deliver something honest, and several of them can.
        return Reply(model=chosen, purpose=purpose, ok=False,
                     degraded="ANTHROPIC_API_KEY is not set")

    kwargs = {"model": chosen, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    kwargs.update(extra)

    try:
        msg = _client().messages.create(**kwargs)
    except Exception as exc:                                    # noqa: BLE001
        return Reply(model=chosen, purpose=purpose, ok=False,
                     error=model_error.explain(exc))

    # Logged before the body is read: the tokens were spent whether or not we
    # like the shape of what came back, and a call that cost money and recorded
    # nothing is the exact hole this module closes. `log_usage` swallows its own
    # failures by design — "never let accounting break a call" — so there is no
    # second guard here; adding one would only hide that it already has one.
    usage.log_usage(purpose, chosen, msg, tenant=tenant)

    return Reply(text=extract_text(msg.content), blocks=list(msg.content),
                 stop_reason=getattr(msg, "stop_reason", "") or "",
                 model=chosen, purpose=purpose, ok=True)


def ask(purpose: str, prompt, *, tenant: str = "", system: str = "",
        model: str = "", max_tokens: int = 1000, **extra) -> Reply:
    """One user turn in, text out — the shape fifteen of the callers wanted.

    `prompt` may be a string or a list of content blocks (a PDF document block
    plus a question, which is how the filing and receipt jobs call it).
    """
    return call(purpose, [{"role": "user", "content": prompt}], tenant=tenant,
                system=system, model=model, max_tokens=max_tokens, **extra)
