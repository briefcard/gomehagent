"""Pre-send edits, synthesised into standing guidance — the learning axis.

`edits.record` writes what the owner changed before every send, and for weeks
nothing read one. Showing the drafter the raw diffs would not converge: a
growing pile of "here is what you changed" that no model can generalise. What
converges is what this codebase already does for mute lessons and voice
rules — DELTAS ARE EVIDENCE, RULES ARE WHAT THE DRAFTER READS, AND THE OWNER
IS THE GATE BETWEEN THEM.

  · `moves(sample)` classifies one edit deterministically (shortened,
    sign-off changed, exclamation removed, …). Code, not a model, so an edit
    about one customer cannot be mistaken for a habit.
  · `propose_for(tenant)` finds a move that recurs across at least
    MIN_RECURRENCE distinct sends of one system, asks the model for ONE
    imperative sentence from that evidence, and files it as a `guidance_rule`
    approval. Approving calls `systems.note` — the store the drafter already
    reads through `guidance_block`. The model proposes; the owner populates.
  · `effect(tenant, key)` says, per accepted rule, whether the median change
    fell afterwards. A rule that changed nothing is the next thing to retire.
"""
from __future__ import annotations

import re

from . import db

#: A rule needs recurrence. One bad Tuesday is not a habit, and proposing a
#: rule from a single edit would teach the drafter the wrong thing — the
#: same floor `kb.classify` uses before it asserts a tag.
MIN_RECURRENCE = 3

#: Sends read per system per proposal pass.
LOOKBACK_DAYS = 30

_GREETING = re.compile(r"^\s*[-+]\s*(hi|hello|dear|hey)\b", re.I)
_SIGNOFF = re.compile(r"^\s*[-+]\s*(best|regards|kind regards|thanks|thank you|cheers|warmly)\b", re.I)
_MARK = "[learned from"


def moves(sample: str) -> set[str]:
    """What kind of change one unified-diff sample shows. Deterministic."""
    minus = [l[1:] for l in (sample or "").splitlines()
             if l.startswith("-") and not l.startswith("---")]
    plus = [l[1:] for l in (sample or "").splitlines()
            if l.startswith("+") and not l.startswith("+++")]
    out: set[str] = set()
    if not minus and not plus:
        return out
    if len(minus) - len(plus) >= 2:
        out.add("shortened")
    if len(plus) - len(minus) >= 2:
        out.add("lengthened")
    if "".join(minus).count("!") > "".join(plus).count("!"):
        out.add("exclamation_removed")
    # A greeting is the FIRST line and a sign-off the LAST — not any line that
    # happens to start with "Thanks". The first cut matched anywhere, and a
    # body line "Thanks for reaching out" read as a changed sign-off.
    if (minus and plus and _GREETING.match("-" + minus[0])
            and _GREETING.match("+" + plus[0]) and minus[0].strip() != plus[0].strip()):
        out.add("greeting_changed")
    if (minus and plus and _SIGNOFF.match("-" + minus[-1])
            and _SIGNOFF.match("+" + plus[-1]) and minus[-1].strip() != plus[-1].strip()):
        out.add("signoff_changed")
    nums_in = set(re.findall(r"\d+", " ".join(plus))) - set(re.findall(r"\d+", " ".join(minus)))
    if nums_in:
        out.add("specifics_added")
    if minus and not plus:
        out.add("sentence_removed")
    return out


def _recurring(runs: list) -> dict[str, list]:
    """move -> the runs that show it, for moves seen on MIN_RECURRENCE+ runs."""
    by: dict[str, list] = {}
    for r in runs:
        for m in moves(r.edit_diff or ""):
            by.setdefault(m, []).append(r)
    return {m: rs for m, rs in by.items() if len({r.id for r in rs}) >= MIN_RECURRENCE}


def _already(tenant: str, key: str, move: str) -> bool:
    """A pending proposal or an accepted rule for this move already exists."""
    from . import systems
    if any(_MARK in (n.content or "") and f": {move}]" in (n.content or "")
           for n in systems.notes(tenant, key)):
        return True
    with db.SessionLocal() as s:
        for ap in (s.query(db.Approval)
                   .filter(db.Approval.tenant == tenant,
                           db.Approval.kind == "guidance_rule",
                           db.Approval.status == "pending").all()):
            pl = ap.payload or {}
            if pl.get("system_key") == key and pl.get("move") == move:
                return True
    return False


def _rule_from(tenant: str, key: str, move: str, samples: list[str]) -> str:
    from . import llm
    prompt = (f"An operator edits drafts from the '{key}' system before sending. "
              f"Across {len(samples)} different replies the same kind of change "
              f"recurred: {move.replace('_', ' ')}. Here are the diffs "
              f"(- is what the draft said, + is what was sent):\n\n"
              + "\n\n---\n\n".join(samples)
              + "\n\nWrite ONE imperative sentence of standing guidance for the "
                "drafter that would have made these edits unnecessary. Under 25 "
                "words. No preamble, no quotes.")
    got = llm.ask("guidance_rule", prompt, tenant=tenant, system=key, max_tokens=120)
    text = (getattr(got, "text", "") or "").strip().strip('"').splitlines()
    return text[0].strip() if text else ""


def propose_for(tenant: str) -> dict:
    """One pass over a tenant's mail systems. Files at most one proposal per
    recurring move; returns what it found and why it did not propose."""
    import datetime as _dt
    from . import approvals, replies, systems
    since = db.utcnow() - _dt.timedelta(days=LOOKBACK_DAYS)
    out: dict = {"tenant": tenant, "proposed": 0, "systems": {}}
    for key in sorted(set(replies.ROUTES.values()) & set(systems.CATALOG)):
        row = systems.find(tenant, key)
        if not row:
            out["systems"][key] = "not installed"
            continue
        with db.SessionLocal() as s:
            runs = (s.query(db.SystemRun)
                    .filter(db.SystemRun.system_id == row.id,
                            db.SystemRun.decision.isnot(None),
                            db.SystemRun.created_at >= since).all())
            runs = [r for r in runs if (r.edit_diff or "").strip()
                    and r.edit_diff.strip() != "sent unchanged"]
            s.expunge_all()
        rec = _recurring(runs)
        if not rec:
            out["systems"][key] = (f"{len(runs)} edited send(s), no move recurs "
                                   f"{MIN_RECURRENCE}+ times")
            continue
        filed = []
        for move, rs in rec.items():
            if _already(tenant, key, move):
                continue
            samples = [(r.edit_diff or "")[:600] for r in rs[:4]]
            rule = _rule_from(tenant, key, move, samples)
            if not rule:
                continue
            approvals.request_approval(
                kind="guidance_rule",
                summary=f"Standing guidance for {key}: {rule}",
                payload={"tenant": tenant, "system_key": key, "move": move,
                         "rule": rule, "n": len(rs), "evidence": samples[:3]},
                notify=False, system_id=row.id)
            filed.append(move)
            out["proposed"] += 1
        out["systems"][key] = (f"proposed {len(filed)}: {', '.join(filed)}"
                               if filed else "every recurring move already proposed or standing")
    return out


def accept(ap) -> str:
    """Write an approved rule into the system's standing guidance. The
    `guidance_rule` executor — named so the map and the register can join it."""
    from . import systems
    pl = ap.payload or {}
    rule, key, move = pl.get("rule", ""), pl.get("system_key", ""), pl.get("move", "")
    if not (rule and key):
        return "Approved — but the proposal carried no rule or no system, so nothing was noted."
    said = systems.note(ap.tenant or pl.get("tenant", ""), key,
                        f"{rule} {_MARK} {pl.get('n', '?')} edits: {move}]")
    return f"Approved — now standing guidance for {key}: {rule[:90]} ({said})"


def effect(tenant: str, key: str, days: int = 14) -> list[dict]:
    """Per accepted rule: the median change before it vs after it."""
    import datetime as _dt
    import statistics
    from . import systems
    row = systems.find(tenant, key)
    if not row:
        return []
    out = []
    with db.SessionLocal() as s:
        aps = (s.query(db.Approval)
               .filter(db.Approval.system_id == row.id,
                       db.Approval.decided_at.isnot(None)).all())
        pts = [(db.as_utc(a.decided_at), float((a.payload or {}).get("similarity")))
               for a in aps if (a.payload or {}).get("similarity") is not None]
    for n in systems.notes(tenant, key):
        if _MARK not in (n.content or ""):
            continue
        at = db.as_utc(getattr(n, "created_at", None) or db.utcnow())
        before = [1 - v for t, v in pts if at - _dt.timedelta(days=days) <= t < at]
        after = [1 - v for t, v in pts if at <= t < at + _dt.timedelta(days=days)]
        b = round(statistics.median(before), 3) if before else None
        a = round(statistics.median(after), 3) if after else None
        out.append({"rule": (n.content or "").split(_MARK)[0].strip(),
                    "since": at.date().isoformat(),
                    "before": b, "after": a, "n_before": len(before), "n_after": len(after),
                    "improved": (a < b) if (a is not None and b is not None) else None})
    return out
