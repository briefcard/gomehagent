"""Ops commands — the fast path, handled before anything reaches the agent.

These are instant database reads and writes: switching tenant, listing what's
wired, capturing knowledge. They must not go through the LLM agent, because a
model deciding whether you meant "switch to baci" is a failure mode with no
upside — and a model deciding which KB field a sentence belongs in is worse,
because the corruption is silent and the KB is the one place nothing may be
quietly wrong.

`handle()` returns a reply string if the message was an ops command, or None
to let it fall through to the normal agent path.
"""
from __future__ import annotations

import json
import re

from . import db, kb, tenants

HELP = """*Ops commands*

`/clients` — every account and what's wired
`/use baci` — switch context (also: "switch to baci")
`/whoami` — who you are and what you're working on
`/systems` — pipelines for this account: state, rung, what's blocking each

*Filling the knowledge base*
`/next` — the single most useful question right now. Just reply to answer.
`/gaps` — everything still missing for this account
`/unknowns` — facts the catalogue couldn't answer, worst first. Reply to fill one.
`/kb` — completeness summary
`/skip` — skip the current question

*Direct capture* (when you already know the format)
`add claim: <claim> | <evidence> | <tags>`
`add objection: <objection> | <answer>`
`add audience: <key> | <name> | <pains;…> | <their words;…>`
`add entity: <type> | <key> | <name> | <price> | <description>`
`ban: <phrase>` — a hard rule the validator enforces

Anything else goes to the agent as normal."""


# ---------------------------------------------------------------------------
# Pending-question state. Stored per chat so a plain reply can be read as an
# answer without a model inferring intent.
# ---------------------------------------------------------------------------

def _pending_key(chat_id: str) -> str:
    return f"intake:{chat_id}"


def _pending_get(chat_id: str) -> dict:
    if not chat_id:
        return {}
    with db.SessionLocal() as s:
        row = s.get(db.Setting, _pending_key(chat_id))
        if not row or not row.value:
            return {}
        try:
            return json.loads(row.value)
        except Exception:  # noqa: BLE001
            return {}


def _pending_set(chat_id: str, tenant: str, step_id: str,
                 unknown_id: str = "") -> None:
    with db.SessionLocal() as s:
        row = s.get(db.Setting, _pending_key(chat_id))
        payload = json.dumps({"tenant": tenant, "step": step_id,
                              "unknown": unknown_id})
        if row:
            row.value = payload
        else:
            s.add(db.Setting(key=_pending_key(chat_id), value=payload))
        s.commit()


def _pending_clear(chat_id: str) -> None:
    with db.SessionLocal() as s:
        row = s.get(db.Setting, _pending_key(chat_id))
        if row:
            row.value = ""
            s.commit()


def _ask_next(tenant: str, chat_id: str, skip: str = "") -> str:
    """Pose the next unmet intake question and remember that it's open."""
    remaining = [g for g in kb.gaps(tenant) if g["id"] != skip]
    if not remaining:
        _pending_clear(chat_id)
        c = kb.completeness(tenant)
        return (f"*{tenant}* has everything the pipeline requires.\n"
                f"{c['counts']}\n\nKeep going with `add claim:` / `add objection:` "
                f"— more proof is always better than less.")
    step = remaining[0]
    _pending_set(chat_id, tenant, step["id"])
    left = len(remaining)
    return (f"*{tenant}* — {left} thing{'s' if left != 1 else ''} still missing.\n\n"
            f"*{step['q']}*\n_{step['hint']}_\n\n"
            f"Reply with the answer, or `/skip`.")


# ---------------------------------------------------------------------------

def _ask_unknown(tenant: str, chat_id: str) -> str:
    """Pose the costliest thing the catalogue could not answer.

    These are ranked by how often the gap actually blocked an answer, so the
    first question is the one that has cost the most enquiries — not the one
    that happens to be alphabetically first.
    """
    rows = kb.unknowns(tenant)
    if not rows:
        return (f"Nothing outstanding for *{tenant}*.\n"
                f"Gaps appear here when a real enquiry asks for something the "
                f"catalogue has no data for.")
    u = rows[0]
    _pending_set(chat_id, tenant, "unknown", u.id)
    hits = int(u.hits or "1")
    asked = f"\nLast asked: _{u.asked_for}_" if u.asked_for else ""
    more = (f"\n\n{len(rows) - 1} more after this." if len(rows) > 1 else "")
    return (f"*{u.entity_name or u.entity_key}* has no "
            f"*{u.attribute.replace('_', ' ')}* recorded.\n"
            f"It has blocked {hits} enquir{'ies' if hits != 1 else 'y'}.{asked}\n\n"
            f"What is it? Reply with the value, or `n/a` if it genuinely "
            f"doesn't apply.{more}")


def handle(text: str, chat_id: str = "") -> str | None:
    raw = (text or "").strip()
    low = raw.lower()

    if low in ("/start", "/help", "help", "commands"):
        return HELP

    user = tenants.user_for_chat(chat_id) if chat_id else None

    # --- switching -------------------------------------------------------
    m = re.match(r"^(?:/use|/switch|switch to|work on|use)\s+([a-z0-9_-]+)$", low)
    if m:
        if not user:
            return _unregistered(chat_id)
        _pending_clear(chat_id)  # a new account means a new question
        return tenants.switch(user, m.group(1))

    if low in ("/clients", "/tenants", "/accounts"):
        if not user:
            return _unregistered(chat_id)
        keys = tenants.visible_tenants(user)
        cur = tenants.active(user)
        lines = []
        for k in keys:
            caps = tenants.capabilities(k)
            wired = [c for c, ok in caps.items() if ok]
            missing = [c for c, ok in caps.items() if not ok]
            mark = "▸" if k == cur else " "
            t = tenants.get(k)
            lines.append(f"{mark} *{t.name}* (`{k}`)\n"
                         f"   on: {', '.join(wired) or 'nothing yet'}\n"
                         f"   missing: {', '.join(missing) or '—'}")
        return "\n".join(lines) or "No accounts visible to you."

    if low in ("/whoami", "/where", "whoami"):
        if not user:
            return _unregistered(chat_id)
        cur = tenants.active(user)
        t = tenants.get(cur)
        return (f"{user.name or 'you'} — role *{user.role}*\n"
                f"Working on: *{t.name if t else cur or '(none)'}*\n"
                f"Access to: {', '.join(tenants.visible_tenants(user))}")

    if low in ("/kb", "kb status"):
        if not user:
            return _unregistered(chat_id)
        cur = tenants.active(user)
        c = kb.completeness(cur)
        if c["ready"]:
            return f"*{cur}* KB ready — {c['counts']}"
        return (f"*{cur}* KB not ready.\nMissing: {', '.join(c['missing'])}\n"
                f"Have: {c['counts']}\n\nSend `/next` to start filling it.")

    if low in ("/systems", "/pipelines", "systems"):
        if not user:
            return _unregistered(chat_id)
        return _systems_for(tenants.active(user))

    # --- guided intake ---------------------------------------------------
    if low in ("/next", "next question"):
        if not user:
            return _unregistered(chat_id)
        return _ask_next(tenants.active(user), chat_id)

    if low == "/skip":
        if not user:
            return _unregistered(chat_id)
        cur_pending = _pending_get(chat_id)
        return _ask_next(tenants.active(user), chat_id,
                         skip=cur_pending.get("step", ""))

    if low in ("/gaps", "gaps"):
        if not user:
            return _unregistered(chat_id)
        cur = tenants.active(user)
        g = kb.gaps(cur)
        if not g:
            return f"*{cur}* — nothing missing. {kb.completeness(cur)['counts']}"
        lines = [f"{i}. *{s['q']}*\n   _{s['hint']}_"
                 for i, s in enumerate(g, 1)]
        return (f"*{cur}* — {len(g)} missing, most useful first:\n\n"
                + "\n".join(lines) + "\n\nSend `/next` to answer them one at a time.")

    if low in ("/unknowns", "/gaps2", "unknowns"):
        if not user:
            return _unregistered(chat_id)
        return _ask_unknown(tenants.active(user), chat_id)

    # --- direct capture --------------------------------------------------
    if low.startswith("ban:"):
        if not user:
            return _unregistered(chat_id)
        return kb.add_banned(tenants.active(user), raw[4:].strip())

    for prefix, step_id in (("add claim:", "claim"),
                            ("add objection:", "objection"),
                            ("add audience:", "audience"),
                            ("add entity:", "entity")):
        if low.startswith(prefix):
            if not user:
                return _unregistered(chat_id)
            body = raw[len(prefix):].strip()
            return kb.apply_answer(tenants.active(user), step_id, body)

    # --- an open question turns a plain message into an answer ------------
    # Last, so no command is ever swallowed as an answer. A leading slash is
    # never an answer either — that is a mistyped command, not knowledge.
    pending = _pending_get(chat_id)

    # Answering an unknown writes onto the entity, so the next enquiry that
    # asks the same question gets a real answer instead of the same shrug.
    if pending.get("unknown") and user and not raw.startswith("/"):
        tenant = pending.get("tenant", "")
        _pending_clear(chat_id)
        result = kb.resolve_unknown(pending["unknown"], raw)
        if result.startswith("Needs a value"):
            _pending_set(chat_id, tenant, "unknown", pending["unknown"])
            return result
        return result + "\n\n" + _ask_unknown(tenant, chat_id)

    if pending.get("step") and user and not raw.startswith("/"):
        tenant, step = pending.get("tenant", ""), pending["step"]
        _pending_clear(chat_id)
        result = kb.apply_answer(tenant, step, raw)
        # Whether the answer took is decided by the data, not by reading the
        # reply text. If the gap is still open the answer was rejected, so the
        # question re-opens rather than being silently dropped.
        if any(g["id"] == step for g in kb.gaps(tenant)):
            _pending_set(chat_id, tenant, step)
            return result + "\n\nStill open — try again, or `/skip`."
        return result + "\n\n" + _ask_next(tenant, chat_id)

    return None  # not an ops command — fall through to the agent


def _systems_for(tenant: str) -> str:
    """The board for one account, told honestly: what's on, and what's stopping
    the rest. A blocked system names its gap here rather than looking idle."""
    from . import systems
    rows = systems.for_tenant(tenant)
    if not rows:
        return (f"No systems installed for *{tenant}* yet.\n"
                f"Install them from the console: /admin/ui?tab=systems")
    out = []
    for r in rows:
        state = systems.ready(r)
        st = systems.stats(r.id)
        head = f"{'▸' if r.status == 'live' else '·'} *{r.name}* — {r.status} / {r.autonomy}"
        # Same three states as the console card. `/systems` on Telegram saying
        # "blocked" about a system the worker is running every tick is the
        # console lying about its own behaviour, in the surface Gomeh actually
        # reads.
        if state["ready"]:
            body = f"   ready · {st['total']} runs, {st['approved']} approved"
        elif not state["can_produce"]:
            body = "   blocked, cannot run: " + "; ".join(state["impossible"])
        else:
            body = ("   running thin · " + f"{st['total']} runs" +
                    " · without: " + "; ".join(state["thin"]))
        out.append(f"{head}\n{body}")
    return "\n".join(out)


def _unregistered(chat_id: str) -> str:
    return (f"This chat isn't registered yet (id `{chat_id}`).\n"
            f"Run `/admin/register_owner?key=<APPROVAL_SECRET>&chat_id={chat_id}` "
            f"once to claim it.")
