"""Ops commands — the fast path, handled before anything reaches the agent.

These are instant database reads and writes: switching tenant, listing what's
wired, capturing a claim. They must not go through the LLM agent, because a
model deciding whether you meant "switch to baci" is a failure mode with no
upside.

`handle()` returns a reply string if the message was an ops command, or None
to let it fall through to the normal agent path.
"""
from __future__ import annotations

import re

from . import db, kb, tenants

HELP = """*Ops commands*

`/clients` — every account and what's wired
`/use baci` — switch context (also: "switch to baci")
`/whoami` — who you are and what you're working on
`/kb` — knowledge-base completeness for the current account
`/systems` — pipelines for this account: state, rung, what's blocking each

`add claim: <claim> | <evidence> | <tags>`
   e.g. `add claim: Cut CPA 60% for a venue | $180 → $72 in 3 months | local_venue ads_not_working`

Anything else goes to the agent as normal."""


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
                f"Have: {c['counts']}")

    if low in ("/systems", "/pipelines", "systems"):
        if not user:
            return _unregistered(chat_id)
        return _systems_for(tenants.active(user))

    # --- capture ---------------------------------------------------------
    if low.startswith("add claim:"):
        if not user:
            return _unregistered(chat_id)
        return _add_claim(raw[len("add claim:"):].strip(), tenants.active(user))

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
        if state["ready"]:
            body = f"   ready · {st['total']} runs, {st['approved']} approved"
        else:
            body = "   blocked: " + "; ".join(state["blockers"])
        out.append(f"{head}\n{body}")
    return "\n".join(out)


def _unregistered(chat_id: str) -> str:
    return (f"This chat isn't registered yet (id `{chat_id}`).\n"
            f"Run `/admin/register_owner?key=<APPROVAL_SECRET>&chat_id={chat_id}` "
            f"once to claim it.")


def _add_claim(body: str, tenant: str) -> str:
    """`<claim> | <evidence> | <tags>` — pipes, because prose parsing here would
    silently mis-file proof and proof is the whole point."""
    parts = [p.strip() for p in body.split("|")]
    if len(parts) < 3 or not parts[0]:
        return ("Format: `add claim: <claim> | <evidence> | <tags>`\n"
                "Tags are space-separated situation keys — send `/tags` for the list.")
    claim, evidence, tag_str = parts[0], parts[1], parts[2]
    tags = [t.strip().lower() for t in re.split(r"[\s,]+", tag_str) if t.strip()]
    unknown = [t for t in tags if t not in kb.SITUATIONS]
    if unknown:
        return (f"Unknown tags: {', '.join(unknown)}\n"
                f"Valid: {', '.join(sorted(kb.SITUATIONS))}")
    if not tags:
        return "Needs at least one situation tag, or it can never be selected."

    with db.SessionLocal() as s:
        s.add(db.KbClaim(tenant=tenant, claim=claim, evidence=evidence,
                         proof_type="case_study", source="added via Telegram",
                         situations=tags, strength="strong",
                         verified_at=db.utcnow()))
        s.commit()
    total = len(kb.claims(tenant))
    return (f"Added to *{tenant}* ({total} claims).\n"
            f"_{claim}_\n{evidence}\ntags: {', '.join(tags)}")
