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
    # THE MODEL MAKES THE EMAIL (`app/recreate.py`). The three that look —
    # the reference read into a brief, the brand's pictures cast by looking,
    # ours judged beside the reference — are vision jobs and sit with the
    # reviewer. The two that write — the copy to the brief's jobs, the HTML
    # itself — are the strongest text model, the default.
    "email_brief": "CREATIVE_REVIEW_MODEL",
    "email_cast": "CREATIVE_REVIEW_MODEL",
    "email_judge": "CREATIVE_REVIEW_MODEL",
    "email_copy": "CLAUDE_MODEL",
    "email_compose": "CLAUDE_MODEL",
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


# ---------------------------------------------------------------------------
# THE IMAGE CONTRACT — what Claude does to a picture before it looks at it.
#
# Pinned from the docs (owner's standing rule: learn what inputs the models
# take, from the published contract, before sending a byte):
#   https://platform.claude.com/docs/en/build-with-claude/vision
#   https://platform.claude.com/docs/en/build-with-claude/vision-coordinates
#     #how-claude-resizes-and-pads-images
#
# Read 2026-09-11. What it says, and why it matters here:
#
# * Claude sees an image in 28×28-pixel PATCHES — one visual token each, so a
#   picture costs ⌈w/28⌉ × ⌈h/28⌉ tokens.
# * Each model has a resolution TIER, a long-edge limit AND a visual-token
#   limit. A picture over either is scaled down, aspect kept, to the largest
#   size that fits both — "Claude 4.7 and later" get the high-resolution
#   tier (2576 px / 4784 tokens); everything else is standard (1568 / 1568).
# * The scaling is silent by default. Set `transformations` on the image
#   block to `{"oversized_image": "error"}` and the request is REFUSED with a
#   400 naming the dimensions and the largest that fit — the house style: a
#   thing that would be degraded is refused and says so.
# * Hard limits, separate from the tier: 8000 px on either side; 10 MB per
#   image base64-encoded on the API directly (5 MB on Bedrock/Vertex); more
#   than 20 image blocks in one request drops the per-image limit to 2000 px
#   on each side; JPEG, PNG, GIF (first frame) and WebP only.
#
# Why this exists: the swipe reader (`email_structures.read_swipe`) sends a
# gallery screenshot whole. Those are 680 wide and 2800–4600 tall (measured
# 2026-09-11), so on the standard tier the model sees a 680×4543 email at
# 235×1568 — body type under five pixels — and reports it cannot see the
# typography it was asked about. `image_seen_as` makes that a number a test
# can assert, and the reader that replaces it (INITIATIVE-email-design.md,
# Phase 3) cuts strips that fit the tier of the model it is about to call.
# ---------------------------------------------------------------------------
IMAGE_DOCS = "https://platform.claude.com/docs/en/build-with-claude/vision"
IMAGE_MIMES = ("image/jpeg", "image/png", "image/gif", "image/webp")
IMAGE_MAX_BYTES = 10 * 1024 * 1024      # base64-encoded, on the API directly
IMAGE_HARD_EDGE = 8000                  # either side, any tier
IMAGE_MANY = 20                         # over this many blocks in one request…
IMAGE_MANY_EDGE = 2000                  # …every image is held to this per side
IMAGE_PATCH = 28
#: The resolution tiers, verbatim from the table in the vision docs.
IMAGE_TIERS = {
    "standard": {"max_edge": 1568, "max_tokens": 1568},
    "high": {"max_edge": 2576, "max_tokens": 4784},
}
#: The image-block field that turns a silent downscale into a refusal.
OVERSIZED_IMAGE_ERROR = {"oversized_image": "error"}


def _model_version(model: str) -> tuple[int, int] | None:
    """`(major, minor)` read off a model id, or None when it carries none.

    Ids come in every shape this platform has used — `claude-sonnet-4-6`,
    `claude-opus-5`, `claude-fable-5-1`, `claude-haiku-4-5-20251001`,
    `claude-3-5-sonnet-20241022` — so the version is the first run of one or
    two digit groups, and an eight-digit date is never read as a minor.
    """
    import re as _re
    m = _re.search(r"(?<![\d])(\d{1,2})(?:-(\d{1,2}))?(?![\d])", str(model or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def image_tier(model: str) -> tuple[str, str]:
    """`(tier, why)` for a model id. "Claude 4.7 and later models" are the
    high-resolution tier (the docs' words); an id whose version cannot be
    read is treated as STANDARD — the smaller limits — and says so, because
    assuming the larger tier of an unknown model would send it pictures it
    then shrinks in silence."""
    v = _model_version(model)
    if v is None:
        return "standard", f"{model!r} carries no version I can read — held to the standard tier"
    if v >= (4, 7):
        return "high", f"{model!r} is {v[0]}.{v[1]}, Claude 4.7 or later — high-resolution tier"
    return "standard", f"{model!r} is {v[0]}.{v[1]}, before 4.7 — standard tier"


def image_tokens(width: int, height: int) -> int:
    """Visual tokens consumed by an image: one token per 28×28 pixel patch."""
    import math
    return math.ceil(width / IMAGE_PATCH) * math.ceil(height / IMAGE_PATCH)


def resized_size(width: int, height: int, max_edge: int = 1568,
                 max_tokens: int = 1568) -> tuple[int, int]:
    """The size Claude resizes an image to before padding — the docs'
    reference implementation, ported line for line (Python's `round` is the
    half-to-even the live API uses at exact ties). Returns (width, height);
    an image that already fits is returned unchanged."""
    import math

    def fits(w: int, h: int) -> bool:
        return (math.ceil(w / IMAGE_PATCH) * IMAGE_PATCH <= max_edge
                and math.ceil(h / IMAGE_PATCH) * IMAGE_PATCH <= max_edge
                and image_tokens(w, h) <= max_tokens)

    if fits(width, height):
        return (width, height)
    if height > width:
        resized_h, resized_w = resized_size(height, width, max_edge, max_tokens)
        return (resized_w, resized_h)
    aspect_ratio = width / height
    lo, hi = 1, width  # lo always fits; hi never fits
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if fits(mid, max(round(mid / aspect_ratio), 1)):
            lo = mid
        else:
            hi = mid
    return (lo, max(round(lo / aspect_ratio), 1))


def image_seen_as(model: str, width: int, height: int) -> tuple[int, int]:
    """The size THIS model actually looks at a `width`×`height` picture — the
    picture itself when it fits the model's tier, the downscaled one when it
    does not. The number the swipe-reader check asserts on."""
    tier, _ = image_tier(model)
    lim = IMAGE_TIERS[tier]
    return resized_size(width, height, lim["max_edge"], lim["max_tokens"])


def image_fits(model: str, width: int, height: int) -> bool:
    """True when the model sees the picture at the size it was sent."""
    return image_seen_as(model, width, height) == (width, height)
