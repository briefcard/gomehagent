"""The agent kernel — one codebase, every agent is the same kernel wearing a
different Role hat.

The kernel owns everything universal: the behavioral DNA (the rules below), the
agentic tool-use loop with prompt caching, memory/lessons wiring, usage logging,
and the WhatsApp/file channel plumbing. A Role (see ``Role`` and the ``roles``
package) swaps only three things — identity, tools, and policy. Behavioral DNA
lives in exactly one place: here.

Adding a new agent (SEO, Ad Manager, Content…) is writing one Role object and a
tool pack — never a fork. If you ever feel tempted to copy a DNA rule into a new
agent, that's the signal this kernel isn't doing its job.
"""
import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

import anthropic

from . import config, data_tools, memory, triage, usage

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


# ---------------------------------------------------------------------------
# Behavioral DNA — identical for every agent. An Ad Manager that doesn't confirm
# before claiming a campaign is live is as broken as an Admin that lies about
# sending an email. Same DNA. This block is cached (static prefix).
# ---------------------------------------------------------------------------
KERNEL_DNA = """You are an always-on operations agent for Gomeh Saias. He
messages you on the go; answer like a sharp chief of staff: concise, concrete,
mobile-friendly (no markdown tables, short lines).

CONTEXT & FORESIGHT — a DATA-ORIENTED posture on EVERY task. The loop is:
GATHER the relevant data with tools → ACT/REPORT with it → SUGGEST the obvious
next step → OFFER to do it. Never report a bare outcome; never make Gomeh "go
check." Always be concrete: numbers, names, dates, amounts, links — and end with
the single most useful next action as an offer, not a question left hanging.

CLARIFY BEFORE BULK ACTIONS — for anything that files, moves, publishes, spends,
or otherwise acts on many items: if a KEY parameter is missing or ambiguous, ASK
before running. Don't silently default. Confirm scope in one short line and wait
for yes. Only skip the question when every key parameter is unambiguous from the
request or our recent conversation. A wrong guess on a bulk job is expensive;
one question is cheap.

BIG-TASK PROTOCOL — for any multi-step or exhaustive request (audits, "find all
X", reorganizations, anything touching many items):
1. ACKNOWLEDGE first: restate what you understood and lay out your plan in 2-4
   short lines BEFORE diving in. If the request is ambiguous, ask one sharp
   question.
2. BE EXHAUSTIVE: one query is never enough. Enumerate variants and paginate
   across ALL relevant sources. Deduplicate before presenting.
3. REPORT COVERAGE: state what you actually searched and what you might have
   missed. NEVER present partial results as complete — say "found 14; areas I
   couldn't cover: X" rather than implying totality.
4. CLOSE LOOPS: end with what happens next — drafts queued, memory saved,
   follow-ups armed, or what you need from Gomeh.

HARD RULES (set by Gomeh — non-negotiable, identical for every agent):
- ACTION CONFIRMATION: never state an action is completed unless a tool result
  explicitly confirmed it. Otherwise say "queued" or "pending". Applies to
  everything — filing, refunds, cancellations, emails, payments, publishing
  content, and ad spend / bid changes.
- APPROVAL GATING: money and irreversible actions wait for Gomeh's tap. Money
  never moves on your say-so. Gather the facts, list what HE must do, or queue
  drafts/changes for his approval.
- GROUNDING: facts only from tools or the conversation. No fabrication, no
  placeholders. If you can't verify, say so. (For an SEO/ads agent this is
  critical: never claim a ranking improved or content published unless the tool
  confirmed it.)
- MEMORY: you carry the recent conversation and have durable memory tools.
  Whenever a task spans time (something being chased, a decision, a standing
  instruction like "always cc Jeff on X"), SAVE it; update the same topic as it
  progresses; archive it when done. Working memory is shared across all agents.
- LEARNING: when Gomeh critiques your output or sets a preference, persist it so
  every future action obeys it; generalizable corrections become shared lessons
  that reach all agents.

Today's date and your current working context are appended below."""


# ---------------------------------------------------------------------------
# A Role is DATA, not code — the only thing that differs between agents.
# ---------------------------------------------------------------------------
@dataclass
class Role:
    """One agent's configuration. The kernel composes its system prompt as:
    [ KERNEL DNA ] + [ ROLE IDENTITY ] + [ SHARED + ROLE LESSONS ] +
    [ DYNAMIC CONTEXT ]. Only ``identity``, ``action_tools``/``dispatch`` and
    the policy fields below change per role."""

    name: str                       # 'admin', 'seo', … — also the lessons scope
    identity: str                   # short, role-specific system text
    action_tools: list              # this role's tool schemas
    dispatch: Callable[[str, dict, dict], str]  # (name, args, session_files) -> str
    model: str                      # default model for this role's loop
    usage_purpose: str = "command"  # tag for cost logging
    use_data_tools: bool = True     # include the shared data_tools pack
    # Per-role depth caps: analysis/content-heavy roles (SEO) need more tool
    # rounds and longer output than the admin email loop.
    max_tokens: int = 2000
    max_steps: int = 10
    # Optional callable returning extra dynamic context (e.g. open shipments for
    # admin). Kept OUT of the cached prefix so the static block caches cleanly.
    extra_context: Callable[[], str] | None = None


# ---------------------------------------------------------------------------
# The agentic loop — generalized from the original command agent. Parameterized
# by Role; the body is identical for every agent.
# ---------------------------------------------------------------------------
def run(role: Role, text: str, attachments: list[dict] | None = None,
        thread: str | None = None) -> str:
    """Process one message (optionally with documents/images) for ``role`` with
    full conversational continuity. attachments: [{filename, data, mime}].

    ``thread`` is the conversation thread — each agent gets its OWN thread
    (defaults to the role name) so admin and seo never share context; pass a
    distinct thread (e.g. 'seo:eien') to run independent parallel conversations."""
    import base64 as _b64

    thread = thread or role.name
    tools = (data_tools.TOOLS if role.use_data_tools else []) + role.action_tools
    history = memory.load_chat_history(thread)
    # Dynamic context (date, lessons, memory, role extras, recent recap) kept
    # OUT of the cached static block so the big rules prefix caches cleanly.
    dynamic = (f"\n\nToday: {dt.datetime.now().strftime('%A %Y-%m-%d')} "
               "(America/New_York)." + memory.lessons_block(role.name)
               + memory.memory_block(role.name))
    if role.extra_context:
        dynamic += role.extra_context()
    if history:
        recent = history[-4:]
        recap = "\n".join(f"  {m['role']}: "
                          + (m['content'] if isinstance(m['content'], str)
                             else '[attachment/tool]')[:300]
                          for m in recent)
        dynamic += ("\n\nMOST RECENT EXCHANGE (this is the live thread — the new "
                    "message below continues THIS, not older topics):\n" + recap)
    system = [
        {"type": "text", "text": KERNEL_DNA + "\n\n" + role.identity,
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic},
    ]
    messages = history

    # Attachments from the current exchange, readable by this role's tools.
    session_files: dict[str, dict] = {}
    if attachments:
        blocks: list = []
        for att in attachments:
            session_files[att["filename"]] = att
            mime = (att.get("mime") or "").lower()
            if len(att["data"]) < 5_000_000:
                if "pdf" in mime or att["filename"].lower().endswith(".pdf"):
                    blocks.append({"type": "document", "source": {
                        "type": "base64", "media_type": "application/pdf",
                        "data": _b64.standard_b64encode(att["data"]).decode()}})
                elif mime.startswith("image/"):
                    blocks.append({"type": "image", "source": {
                        "type": "base64", "media_type": mime,
                        "data": _b64.standard_b64encode(att["data"]).decode()}})
        blocks.append({"type": "text", "text": text})
        messages.append({"role": "user", "content": blocks})
    else:
        messages.append({"role": "user", "content": text})
    memory.save_turn(thread, "user", text)

    reply = "I hit my step limit on that one — try breaking it into smaller asks."
    for _ in range(role.max_steps):
        msg = client.messages.create(
            model=role.model, max_tokens=role.max_tokens,
            system=system, tools=triage._cached_tools(tools), messages=messages,
        )
        usage.log_usage(role.usage_purpose, role.model, msg)
        if msg.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": msg.content})
            results = []
            for block in msg.content:
                if block.type == "tool_use":
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": role.dispatch(
                                        block.name, dict(block.input),
                                        session_files)[:8000]})
            messages.append({"role": "user", "content": results})
            continue
        reply = next((b.text for b in msg.content if b.type == "text"),
                     "Done (no further output).").strip()
        break
    memory.save_turn(thread, "assistant", reply)
    return reply
