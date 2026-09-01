"""The knowledge base, compiled into the brand document a skill can just use.

A hand-written brand `.md` is a good tool and this layer should not compete
with it. At a corpus this size a static document beats retrieval outright: it
is prompt-cached to nearly free, it cannot surface the wrong thing because
everything is present, and picking the relevant paragraphs from it is
something the model is already reliably good at.

What a hand-written `.md` cannot do is hold an approval state, record that two
sources disagree, be enforced rather than merely read, or say why it once said
something. Those are curation problems, and no amount of context length fixes
them.

So: **the knowledge base is source and the document is a build artifact.** You
would not hand-maintain a compiled binary. Generated here it is always current,
provably derived from approved rows only, and the same rows the validator
enforces on the way out — so what the drafter was told and what it will be held
to cannot drift apart.

## Ordering is the whole cost argument

Prompt caching works on **prefixes**. Put live stock at the top and every
inventory change invalidates the cache for the entire document, which is
exactly the saving this is supposed to deliver. So sections run

    most stable ......................................... most volatile
    identity, voice, hard rules -> situations -> objections -> claims -> stock

and everything inside each section is sorted deterministically. A document
that reorders itself between two generations is a document that never gets
cached twice.
"""
from __future__ import annotations

import hashlib

from . import kb, tenants

#: Every section there is, in the order they must appear. Stable first, so the
#: prompt cache hits on a prefix; `lookups` before `catalogue` because the
#: DECLARATION is stable — which tool, which parameters — even though what it
#: returns is not. The volatile thing is the answer, and the answer is
#: deliberately not here.
#:
#: A scope FILTERS this tuple rather than listing its own order, so no scope
#: can reorder the document and cost every account its cache.
ORDER = ("identity", "rules", "situations", "objections", "claims", "context",
         "lookups", "catalogue", "gaps")


def _sections_for(key: str) -> tuple[str, ...]:
    """Which sections a system gets — DERIVED from what it declared it needs.

    This was five hand-written lists, and it drifted exactly the way a second
    copy of a fact always does. `creative` was written on 2026-08-16 for a
    generator that entered `systems.CATALOG` the next day as `ad_creative`, and
    the two were never reconciled: the narrow scope became unreachable by the
    system's real name, `SCOPES.get(system, SCOPES[""])` quietly handed back
    the whole document, and `build` went on stamping `"system": "ad_creative"`
    on it. Seven of the ten systems had no scope at all and none of them said
    so — a fallback that succeeds is the hardest kind of wrong to see.

    So it is computed, from declarations that already exist and are already
    enforced elsewhere:

      · `claim` in `kb_needs`     -> the claims it may lean on
      · `objection` in `kb_needs` -> the answers already approved
      · `entity` in `kb_needs`    -> the catalogue
      · a `gmail_draft` artifact  -> situations, and the live lookups hanging
        off them. Those are facts about INBOUND CONVERSATION: what people
        actually ask, and which of those questions this document must refuse
        to answer from memory.

    identity, rules and gaps are unconditional — who this is, what may never
    be said, and what is not established. No system opts out of those.

    The derivation reproduces the author's own `creative` scope for
    `ad_creative` exactly, which is the evidence it is the rule that was in
    their head. Where it DISAGREES with the old lists it agrees with the
    system's own declaration instead: `service_desk` declares it needs
    `entity` and now gets the catalogue; `campaign_email` declares `objection`
    and now gets the objections its drafter was already being fed through
    `funnel.inputs_for`. A disagreement between two hand-written lists is not
    a preference to preserve — it is the drift, and the declaration wins.
    """
    from . import systems
    sp = systems.CATALOG.get(key) or {}
    needs = set(sp.get("kb_needs") or ())
    mail = (sp.get("workflow") or {}).get("artifact") == "gmail_draft"
    want = {
        "identity": True, "rules": True, "gaps": True,
        "situations": mail, "lookups": mail,
        "objections": "objection" in needs,
        "claims": "claim" in needs,
        # EVERY SYSTEM THAT WRITES ANYTHING. Context is not a `kb_needs`
        # token — deliberately, so no amount of it can make an account look
        # ready — so there is nothing to key it on, and there should not be:
        # background bears on any draft. It costs nothing where none is filed.
        "context": True,
        "catalogue": "entity" in needs,
    }
    return tuple(s for s in ORDER if want[s])


def _scopes() -> dict[str, tuple[str, ...]]:
    """One entry per system, plus `""` for the whole document.

    Built over `systems.CATALOG` rather than beside it, so a system added next
    month has a scope the moment it is declared and an entry for something
    that is not a system cannot be written at all.
    """
    from . import systems
    out = {"": ORDER}
    out.update({k: _sections_for(k) for k in systems.CATALOG})
    return out


#: What each system actually needs. A section nobody reads is a section that
#: pushed something useful out of the context window.
SCOPES: dict[str, tuple[str, ...]] = _scopes()

#: Rough, and honest about being rough. Enough to tell a caller whether this
#: still belongs in a prompt or whether it is time to call `resolve()` instead.
CHARS_PER_TOKEN = 3.7

#: Past this the document has outgrown what most callers want to pay for on
#: every turn, and per-question retrieval starts winning. This is the crossover
#: the A/B harness exists to locate — stated so it can be argued with.
CONTEXT_BUDGET_TOKENS = 25000


def _identity(t, b) -> list[str]:
    out = [f"# {b.display_name if b else t.name}", ""]
    if b and b.positioning:
        out += [b.positioning, ""]
    tone = (b.voice or {}).get("tone") if b else None
    if tone:
        out += [f"**Voice:** {', '.join(tone)}", ""]
    return out


def _rules(t, b) -> list[str]:
    """First, and never anywhere else. These are the lines that get enforced."""
    banned = sorted(b.banned_claims or []) if b else []
    if not banned:
        return ["## Hard rules", "",
                "> **No ban list on file for this account.** Nothing said here "
                "can be checked, so treat every factual claim as unverified "
                "and say less rather than more.", ""]
    return [
        "## Hard rules — never say these, in any draft, for any reason", "",
        *[f"- {p}" for p in banned], "",
        "These are enforced in code after you write, not merely requested. "
        "A draft containing one is blocked, not softened.", "",
    ]


def _situations(t) -> list[str]:
    rows = sorted(kb.situation_rows(t.key), key=lambda r: r.tag)
    if not rows:
        return []
    out = ["## What customers are actually asking about", ""]
    for r in rows:
        out.append(f"- **{r.tag}** — {r.description or 'no description on file'}")
    return out + [""]


def _objections(t) -> list[str]:
    rows = sorted(kb.objections(t.key, any_entity=True),
                  key=lambda o: (o.entity_key or "", o.objection))
    if not rows:
        return ["## Answers already approved", "",
                "_None on file yet._ Draft from the claims below and stay "
                "inside the hard rules.", ""]
    out = ["## Answers already approved", "",
           "Wording a human wrote and signed off. Prefer it over inventing a "
           "new phrasing for the same question.", ""]
    for o in rows:
        scope = f" _(about {o.entity_key})_" if o.entity_key else ""
        out += [f"**{o.objection}**{scope}", f"> {o.response}", ""]
    return out


def _claims(t) -> list[str]:
    rows = sorted(kb.claim_inventory(t.key)["selectable"],
                  key=lambda c: (c.entity_key or "", c.claim))
    if not rows:
        return []
    out = ["## Proof you may lean on", "",
           "Approved and current. Anything not here is not established — say "
           "less rather than filling the gap.", ""]
    for c in rows:
        scope = c.entity_key or "brand-wide"
        ev = f" — _{c.evidence}_" if c.evidence else ""
        out.append(f"- [{scope}] {c.claim}{ev}")
    return out + [""]


def _context(t) -> list[str]:
    """True here, and not proof. Its own heading, on purpose.

    Put under "Proof you may lean on" it would be quoted; left out entirely
    the document would be missing what a person reading this account actually
    knows about it. So: present, named, and told what it is not.
    """
    rows = sorted(kb.contexts(t.key), key=lambda c: (c.entity_key or "", c.text))
    if not rows:
        return []
    out = ["## Background — true here, and NOT proof", "",
           "Context somebody filed about this account. It carries no id and "
           "nothing here may be stated as a fact, quoted, or built into a "
           "claim. Let it shape what you write and what you leave out.", ""]
    for c in rows:
        scope = f" _(about {c.entity_key})_" if c.entity_key else ""
        out.append(f"- {c.text}{scope}")
    return out + [""]


def _lookups(t) -> list[str]:
    from . import lookups as lk
    rows = [r for r in kb.situation_rows(t.key) if getattr(r, "needs", None)]
    if not rows:
        return []
    caps = tenants.capabilities(t.key)
    out = ["## Questions that need a live lookup, not this document", "",
           "These change by the hour and are never written down here. Call the "
           "tool.", ""]
    for r in sorted(rows, key=lambda x: x.tag):
        for want in r.needs or []:
            spec = lk.TOOLS.get(want.get("tool", ""))
            if not spec:
                continue
            ok = "" if caps.get(spec["capability"]) else \
                 f" _(not connected — {spec['capability']})_"
            out.append(f"- **{r.tag}** → `{want['tool']}"
                       f"({', '.join(want.get('params') or spec['params'])})`"
                       f" → {spec['returns']}{ok}")
    return out + [""]


def _catalogue(t) -> list[str]:
    """Last, deliberately. Price and stock move hourly; everything above does
    not. A volatile section at the top would invalidate the cached prefix for
    the whole document every time a unit sold."""
    rows = sorted(kb.entities(t.key, available_only=False),
                  key=lambda e: e.key)
    if not rows:
        return []
    out = ["## Catalogue", "",
           "_Live at the time this was generated — the volatile section, and "
           "last on purpose._", ""]
    for e in rows:
        stock = "" if e.availability == "available" else f" **{e.availability}**"
        price = f" {e.price}" if e.price else ""
        out.append(f"- `{e.key}` {e.name}{price}{stock}")
    return out + [""]


def _gaps(t) -> list[str]:
    from . import resolve as rs
    r = rs.readiness(t.key)
    out = ["## What this account does NOT know", "",
           f"{r['verdict']}.", ""]
    thin = [p["situation"] for p in r["per_situation"]
            if p["state"] in ("unanswerable", "waiting on review")]
    if thin:
        out += [f"No approved answer for: {', '.join(sorted(thin))}.", "",
                "Those are not forbidden topics — they are unproven ones. "
                "Answer from the rules and say plainly what you do not know.",
                ""]
    return out


SECTIONS = {
    "identity": _identity, "rules": _rules, "situations": _situations,
    "objections": _objections, "claims": _claims, "context": _context,
    "lookups": _lookups, "catalogue": _catalogue, "gaps": _gaps,
}


def build(tenant: str, system: str = "") -> dict:
    """Compile the document. Returns text plus what a caller needs to cache it."""
    t = tenants.get(tenant)
    if not t:
        return {"error": f"unknown account {tenant!r}"}
    b = kb.brand(tenant)
    if system and system not in SCOPES:
        # NOT a silent fallback. `?system=creative` returned the whole document
        # stamped `"system": "creative"` and nothing anywhere said the scope
        # had not been applied — which is how the orphan survived a fortnight.
        return {"error": f"{system!r} is not a system. Try one of: "
                         + ", ".join(sorted(k for k in SCOPES if k))}
    wanted = SCOPES[system]

    parts: list[str] = []
    for name in wanted:
        fn = SECTIONS[name]
        parts += (fn(t, b) if name in ("identity", "rules") else fn(t))

    text = "\n".join(parts).rstrip() + "\n"
    tokens = int(len(text) / CHARS_PER_TOKEN)
    return {
        "tenant": tenant, "system": system or "all",
        "markdown": text,
        "chars": len(text),
        "approx_tokens": tokens,
        # The content hash IS the cache key. A caller re-fetches, compares, and
        # skips the model call entirely when nothing has changed.
        "etag": hashlib.sha256(text.encode()).hexdigest()[:16],
        "sections": list(wanted),
        "within_context_budget": tokens <= CONTEXT_BUDGET_TOKENS,
        "budget": CONTEXT_BUDGET_TOKENS,
        "advice": (
            "small enough to send whole — a cached document beats per-question "
            "retrieval at this size, and cannot surface the wrong thing"
            if tokens <= CONTEXT_BUDGET_TOKENS else
            f"{tokens} tokens is past the budget: switch this surface to "
            f"/resolve, or narrow it with ?system="),
    }
