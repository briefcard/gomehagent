"""Money, percentages and durations — the figures a business is HELD to.

Build map §15.6 step 1. The count reader (`statements.find`) knows "<number>
<unit word>" — countries, licences, users — and the accounting stage threw
away every currency-prefixed number as "a price" and never saw a percentage
or a duration as a fact at all. Those are exactly the figures an e-commerce
or service brand is held to: Baci's ads said 10% off while its discount code
gave 15%; a shipping threshold, a return window or a delivery time stated two
ways is a consumer-protection problem, not a wording issue.

Every figure here carries a KIND (money · percent · duration · rating) and,
for money, a CURRENCY. The SUBJECT comes from the words around it — and only
from them: a bare "$95.00" beside a product is a price the catalogue owns, not
a claim, and is left to the accounting stage's non-fact rules. Which words
mean which subject is DATA (`RULES`), the same for every company; step 3 of
the build moves it into the global vocabulary table.

Pure functions, no I/O: the site reader and the draft gate (`truth.check_text`)
call the same code, so a draft is judged by exactly the rule the site was.
"""
from __future__ import annotations

import re

_CUR_SYM = {"$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "C$": "CAD",
            "A$": "AUD", "AED": "AED", "USD": "USD", "EUR": "EUR", "GBP": "GBP",
            "CAD": "CAD", "AUD": "AUD"}
_AMOUNT = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_QUAL = r"(?:(over|more than|at least|from|starting at|up to|under|below|less than|only|just|within|around|about|nearly)\s+)?"
_MONEY = re.compile(
    _QUAL + r"(US\$|C\$|A\$|[$€£¥]|(?:USD|EUR|GBP|CAD|AUD|AED)\s?)\s?" + _AMOUNT + r"(\+)?"
    r"|" + _QUAL + _AMOUNT + r"\s?(USD|EUR|GBP|CAD|AUD|AED|dollars|euros|pounds)\b", re.I)
_PERCENT = re.compile(_QUAL + r"(\d+(?:\.\d+)?)\s?(%|percent\b|per cent\b)", re.I)
_DURATION = re.compile(
    _QUAL + r"(\d+)(?:\s?(?:-|–|to)\s?(\d+))?[\s-]?(business |working |calendar )?"
    r"(minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?)\b", re.I)
_RATING = re.compile(r"(\d(?:\.\d)?)\s?(?:/\s?5|out of 5|stars?\b)|rated\s(\d(?:\.\d)?)", re.I)

#: (kind, context words that must appear within the window, subject). FIRST
#: match wins, so the most specific rule comes first. The window is the
#: sentence the figure sits in.
RULES: list[tuple[str, str, str]] = [
    ("money", r"free (?:standard |express |ground )?(?:shipping|delivery)|ships? free|shipping is free",
     "offer.free_shipping_threshold"),
    ("money", r"minimum order|order minimum|min\.? order|moq", "pricing.minimum_order"),
    ("money", r"\boff\b|discount|save|savings|coupon|promo", "offer.discount_amount"),
    ("money", r"shipping (?:cost|fee|rate)|delivery (?:fee|charge)|flat[- ]rate", "pricing.shipping_fee"),
    ("money", r"\bfees?\b|commission|surcharge|charge", "pricing.fee"),
    ("money", r"credit|gift card|store credit|reward", "offer.credit_amount"),
    ("percent", r"\boff\b|discount|save|savings|coupon|promo|first order", "offer.discount_percent"),
    ("percent", r"\bfees?\b|commission|spread|markup|surcharge", "pricing.fee_percent"),
    ("percent", r"cash ?back|rebate", "offer.cashback_percent"),
    ("percent", r"\bapr\b|\bapy\b|interest|yield|rate of return", "pricing.rate_percent"),
    ("percent", r"uptime|availability|sla", "service.uptime_percent"),
    ("percent", r"satisf|recommend|repeat customers|retention", "reputation.satisfaction_percent"),
    ("duration", r"\breturns?\b|refund|exchange|money[- ]back", "policy.return_window"),
    ("duration", r"warrant|guarantee", "policy.warranty"),
    ("duration", r"settle|payout|withdraw|\btransfers?\b|processing time|funds? (?:arrive|land|clear)",
     "service.settlement_time"),
    ("duration", r"\bships?\b|shipping|deliver|dispatch|arrives?|transit|lead time|turnaround",
     "shipping.delivery_time"),
    ("duration", r"free trial|trial", "offer.trial_length"),
    ("duration", r"in business|of experience|serving|since", "scale.years_in_business"),
    ("rating", r".", "reputation.rating"),
]
_UNIT_DAYS = {"minute": 1 / 1440, "min": 1 / 1440, "hour": 1 / 24, "hr": 1 / 24,
              "day": 1, "week": 7, "month": 30, "year": 365}


def _qualifier(q: str, plus: bool = False) -> str:
    q = (q or "").lower()
    if plus or q in ("over", "more than", "at least", "from", "starting at"):
        return "at least"
    if q in ("up to", "under", "below", "less than", "within"):
        return "up to"
    if q in ("around", "about", "nearly"):
        return "about"
    return ""


def _sentence(text: str, start: int, end: int) -> str:
    """The sentence holding the figure — the window its subject is read from."""
    left = max(text.rfind(". ", 0, start), text.rfind("! ", 0, start), text.rfind("? ", 0, start))
    right = min([i for i in (text.find(". ", end), text.find("! ", end), text.find("? ", end)) if i >= 0]
                or [len(text)])
    return text[left + 1 if left >= 0 else 0:right + 1].strip()


def _subject(kind: str, window: str) -> str:
    for k, words, subj in RULES:
        if k == kind and re.search(words, window, re.I):
            return subj
    return ""


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def find(text: str) -> list[dict]:
    """Every money / percent / duration / rating figure in one line that the
    words around it give a subject. Same record shape as `statements.find`,
    plus `kind` and (money) `currency`."""
    text = text or ""
    out, taken = [], []

    def add(m, kind, value, number, qualifier, subject, currency="", unit=""):
        if any(a < m.end() and m.start() < b for a, b in taken):
            return
        taken.append((m.start(), m.end()))
        out.append({"subject": subject, "value": value, "number": number,
                    "qualifier": qualifier, "unit": unit or kind, "kind": kind,
                    "currency": currency, "match": " ".join(m.group(0).split()),
                    "text": text.strip()[:400]})

    for m in _MONEY.finditer(text):
        q1, sym, amt1, plus, q2, amt2, word = m.groups()
        amt = amt1 or amt2
        cur = (_CUR_SYM.get((sym or "").strip().upper()) or _CUR_SYM.get((sym or "").strip())
               or {"dollars": "USD", "euros": "EUR", "pounds": "GBP"}.get((word or "").lower())
               or _CUR_SYM.get((word or "").upper(), ""))
        subj = _subject("money", _sentence(text, m.start(), m.end()))
        if not subj:
            continue
        q = q1 or q2 or ""
        shown = (sym or "").strip()
        value = ((q + " ") if q else "") + (shown + amt if shown else f"{amt} {word}") + ("+" if plus else "")
        add(m, "money", value, _num(amt), _qualifier(q, bool(plus)), subj, cur)
    styled = [(c.start(), c.end()) for c in re.finditer(r"(?:hsla?|rgba?|calc)\([^)]*\)", text, re.I)]
    for m in _PERCENT.finditer(text):
        q, amt, _unit = m.groups()
        if any(a <= m.start() < b for a, b in styled):
            continue
        subj = _subject("percent", _sentence(text, m.start(), m.end()))
        if subj:
            add(m, "percent", ((q + " ") if q else "") + amt + "%", _num(amt), _qualifier(q), subj)
    for m in _DURATION.finditer(text):
        q, lo, hi, basis, unit = m.groups()
        # Interface text, not a commitment: "Last 30 days", "5 min read".
        if re.search(r"\b(?:last|past|previous|next)\s*$", text[:m.start()], re.I) \
                or re.match(r"\s*read\b", text[m.end():], re.I):
            continue
        subj = _subject("duration", _sentence(text, m.start(), m.end()))
        if not subj:
            continue
        u = unit.lower().rstrip("s")
        u = {"min": "minute", "hr": "hour"}.get(u, u)
        top = _num(hi or lo)
        value = (((q + " ") if q else "") + (f"{lo}–{hi}" if hi else lo) + " "
                 + (basis or "") + u + ("s" if top != 1 else ""))
        add(m, "duration", " ".join(value.split()), top * _UNIT_DAYS.get(u, 1),
            "up to" if hi else _qualifier(q), subj, unit=f"{(basis or '').strip()} days".strip())
    for m in _RATING.finditer(text):
        val = m.group(1) or m.group(2)
        if val and float(val) <= 5:
            add(m, "rating", f"{val}/5", float(val), "", "reputation.rating")
    return out


def currency_of(value: str) -> str:
    """The currency a stored value is written in ("$95" -> USD), or ""."""
    v = (value or "").strip()
    for sym in sorted(_CUR_SYM, key=len, reverse=True):
        if sym in v.upper() or sym in v:
            return _CUR_SYM[sym]
    for w, c in (("dollar", "USD"), ("euro", "EUR"), ("pound", "GBP")):
        if w in v.lower():
            return c
    return ""
