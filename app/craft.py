"""What one account taught us, made available to a similar one — carefully.

Everything else in this system is scoped to a client and `test_tenant_isolation`
is the mandatory suite. This module deliberately steps outside that, so it is
built with the narrowest possible licence:

**Craft shapes HOW something is said. It is never WHAT is asserted as true.**

A claim is a fact about a client's business: it carries a `claim_id`, it is
cited, and a reader can trace an assertion back to it. A craft lesson is
technique — "when someone asks about capacity, lead with the number" — and it
is injected as guidance that can never become a citation. That is the same line
already drawn between prose guidance and the banned-claims list, one layer out.
It is what makes this safe: a leak of technique is embarrassing; a leak of a
client's facts into another client's output is the thing the whole architecture
exists to prevent.

**Three gates, and none of them is trust.**

1. *Reach* is `business_model`, not "everyone". A lesson from a venue does not
   travel to a shop. The vocabulary is `metrics.OUTCOMES`, already on `Tenant`.
2. *A deterministic leak guard.* Before anything can be proposed, the text is
   checked against every account's identifying material — names, keys, domains,
   entity names, email addresses, URLs — and a hit REFUSES by name. It is not a
   scrub: rewriting a lesson to smuggle it past a filter is not something code
   should help with. The owner rewords.
3. *A person approves.* The guard catches what it can recognise, which is not
   everything, and `review` follows the same rule as every other KB table.

**And it ranks last.** In the bundle it sits below the account's own knowledge,
labelled as coming from elsewhere and weaker. The precedence this codebase
already uses for claims — relevance, then specificity, then strength — puts it
there naturally: a cross-client lesson is the least specific thing that can be
said about anything.
"""
from __future__ import annotations

import re

from . import db

#: Anything shorter than this is too common to treat as identifying. "Aqua"
#: would otherwise block a lesson about aquatic anything; the guard is meant to
#: catch a client's material, not every short word that appears in a catalogue.
MIN_TOKEN = 5

#: Structural giveaways. These are refused wherever they appear, at any length,
#: because none of them belongs in a lesson about technique.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"https?://\S+|\b[\w-]+\.(com|co|net|org|io|shop|myshopify\.com)\b",
                  re.I)
_LONGNUM = re.compile(r"\b\d{5,}\b")     # order ids, account ids, phone numbers


def _identifiers() -> dict[str, str]:
    """Every string that would identify an account, mapped to what it is.

    Read from the database rather than listed, for the reason this codebase
    keeps re-learning: a hand-kept list is the one that goes stale the day a
    client is added, and here going stale means a leak rather than a gap.
    """
    out: dict[str, str] = {}

    def add(value, what):
        v = (value or "").strip().lower()
        if len(v) >= MIN_TOKEN:
            out[v] = what

    with db.SessionLocal() as s:
        for t in s.query(db.Tenant).all():
            add(t.key, f"the account key {t.key!r}")
            add(t.name, f"the account name {t.name!r}")
            add(getattr(t, "domain", ""), "an account's domain")
        for e in s.query(db.KbEntity).all():
            add(e.name, "a product or venue name")
            add(e.key, "a catalogue key")
        for b in s.query(db.KbBrand).all():
            add(getattr(b, "positioning", "") or "", "a brand's positioning")
    return out


def leaks(text: str) -> list[str]:
    """What in this text identifies an account. Empty means it is safe to share.

    Refuses rather than scrubs. Rewriting a lesson to get it past a filter is
    not something code should do on somebody's behalf — the person who wrote it
    is the one who knows what they meant.
    """
    body = (text or "")
    low = body.lower()
    found: list[str] = []

    if _EMAIL.search(body):
        found.append("an email address")
    if _URL.search(body):
        found.append("a domain or URL")
    if _LONGNUM.search(body):
        found.append("a long number — an order or account id")

    for needle, what in _identifiers().items():
        # Word-boundary matched, so "aquatic" does not trip on an "aqua" entity
        # and a lesson is not blocked by a coincidence of letters.
        if re.search(rf"\b{re.escape(needle)}\b", low):
            found.append(what)
    # Stable and deduplicated: the same refusal should read the same twice.
    return sorted(set(found))


def propose(lesson: str, *, business_model: str = "", situations=None,
            basis: str = "", learned_from: str = "") -> dict:
    """Offer a lesson for cross-client use. Refused if it identifies anyone."""
    lesson = (lesson or "").strip()
    if not lesson:
        return {"ok": False, "error": "a lesson needs some text"}
    bad = leaks(lesson) + leaks(basis)
    if bad:
        return {"ok": False, "error": (
            "That would carry one account's material to another. It names: "
            + "; ".join(sorted(set(bad)))
            + ". Reword it as technique — what to DO, not who it was for.")}
    if business_model:
        from . import metrics
        if business_model not in metrics.OUTCOMES:
            return {"ok": False,
                    "error": f"unknown business model {business_model!r} — "
                             f"one of: {', '.join(sorted(metrics.OUTCOMES))}"}
    with db.SessionLocal() as s:
        row = db.CraftLesson(lesson=lesson, basis=basis,
                             business_model=business_model,
                             situations=list(situations or []),
                             learned_from=learned_from, review="proposed")
        s.add(row)
        s.commit()
        return {"ok": True, "id": row.id, "review": "proposed"}


def approve(lesson_id: str, by: str = "owner", approve_it: bool = True) -> dict:
    """A person decides. The guard is the first check, not the only one."""
    with db.SessionLocal() as s:
        row = s.get(db.CraftLesson, lesson_id)
        if not row:
            return {"ok": False, "error": f"no lesson {lesson_id!r}"}
        # Re-checked at approval: the accounts on file may have changed since
        # it was proposed, and a name that was harmless last month may identify
        # a client onboarded since.
        if approve_it:
            bad = leaks(row.lesson) + leaks(row.basis or "")
            if bad:
                row.review = "retired"
                s.commit()
                return {"ok": False, "error": (
                    "Refused and retired — since it was proposed it now names: "
                    + "; ".join(sorted(set(bad))))}
        row.review = "approved" if approve_it else "retired"
        row.approved_by = by
        row.approved_at = db.utcnow()
        s.commit()
        return {"ok": True, "id": lesson_id, "review": row.review}


def for_account(tenant: str, situations=None, limit: int = 3) -> list[dict]:
    """Approved lessons that could apply here, most specific first.

    Matched on the account's `business_model` — a lesson learned at a venue
    does not reach a shop — and then on situation where the caller knows one.
    A lesson with no model set applies anywhere and ranks BELOW one that named
    this kind of business, because the more specific match is the better bet.
    """
    from . import tenants
    t = tenants.get(tenant)
    model = (getattr(t, "business_model", "") or "") if t else ""
    want = set(situations or [])
    with db.SessionLocal() as s:
        rows = (s.query(db.CraftLesson)
                .filter(db.CraftLesson.review == "approved").all())
        s.expunge_all()

    out = []
    for r in rows:
        if r.business_model and r.business_model != model:
            continue
        sits = set(r.situations or [])
        if sits and want and not (sits & want):
            continue
        out.append({"id": r.id, "lesson": r.lesson, "basis": r.basis or "",
                    "situations": sorted(sits),
                    "specificity": (1 if r.business_model else 0)
                    + (1 if sits & want else 0)})
    out.sort(key=lambda x: -x["specificity"])
    return out[:max(0, limit)]


def block(tenant: str, situations=None, limit: int = 3) -> str:
    """The lessons, rendered for injection — and labelled as what they are.

    The label is load-bearing. Without it a model reads borrowed technique with
    the same authority as the account's own approved knowledge, and the whole
    point is that it carries less. It also says plainly that none of it may be
    stated as fact, because the one failure mode that matters here is a lesson
    being repeated to a customer as though it were true of THEIR business.
    """
    rows = for_account(tenant, situations, limit)
    if not rows:
        return ""
    lines = [f"- {r['lesson']}" + (f" ({r['basis']})" if r["basis"] else "")
             for r in rows]
    return ("\n\nWHAT HAS WORKED ELSEWHERE — from other accounts in a similar "
            "line of business, and the WEAKEST thing in this brief. It is "
            "technique, not fact: use it to shape how you write, never as "
            "something to assert. Anything above overrides it.\n"
            + "\n".join(lines))


def pending(limit: int = 50) -> list[dict]:
    """Lessons waiting on a person."""
    with db.SessionLocal() as s:
        rows = (s.query(db.CraftLesson)
                .filter(db.CraftLesson.review == "proposed")
                .order_by(db.CraftLesson.created_at.desc()).limit(limit).all())
        return [{"id": r.id, "lesson": r.lesson, "basis": r.basis or "",
                 "business_model": r.business_model or "any",
                 "situations": list(r.situations or []),
                 # Shown to the OWNER for audit. Never rendered into a prompt
                 # and never shown to a client.
                 "learned_from": r.learned_from or ""} for r in rows]
