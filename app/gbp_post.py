"""A Google Business Profile post — what makes one rank and convert, as rules.

The sibling of `ad_craft` and `email_craft`, for the same reason they exist:
the validator says whether a draft is FALSE; this says whether it is a POST —
the thing Google shows under the listing in the local pack, 1,500 characters
at most, of which the first sentence is the snippet.

Two producers, both held to the same rules (INITIATIVE-gbp §5; owner,
2026-09-04: "either take existing blogs, emails or ads and convert them to
be SEO optimized GMB posts or generate a new one from scratch to address
company objections or reinforce company claims"):

  DERIVED  from an artifact already approved — an article, a campaign, an ad
           batch. Shortens and adds a call to action; asserts nothing the
           source did not.
  NATIVE   from scratch: answers one of the account's objections with its
           approved response, or reinforces one approved claim. An offer's
           terms and an event's dates are OWNER INPUT — a generator inventing
           a discount is the one failure here that costs real money.

WHAT MAKES IT SEO-OPTIMISED, from Google's post guidelines and what moves the
map pack (INITIATIVE-gbp §4b), each a MEASUREMENT rather than a taste:

  · the LOCAL KEYWORD — the category the listing is in and the place it is
    in — sits in the first sentence, because that sentence is the snippet
    and the listing is matched on it (`SNIPPET` characters);
  · ONE idea, `WORDS_MIN`–`WORDS_MAX` words, under `SUMMARY_MAX` characters;
  · the call to action is the BUTTON Google renders (`CTAS`), never a bare
    "click here" in the text;
  · no phone number and no URL in the body — Google rejects them, and the
    button carries the link; no hashtags — not indexed on Business Profile
    and read as spam; sentence case, not shouting;
  · an offer without terms and an event without dates are refused, not
    softened; urgency needs a real deadline, the rule email is held to.
"""
from __future__ import annotations

import datetime as _dt
import re

from .ad_craft import PLATITUDES, VAGUE, _find
from .email_craft import URGENCY

SUMMARY_MAX = 1500
WORDS_MIN, WORDS_MAX = 40, 300
#: What the local pack shows of a post before "…" — the first sentence, near
#: enough. The local keyword must land inside it.
SNIPPET = 160
TITLE_MAX = 58

#: Post type → Google's topicType. `offer` and `event` both need a title and
#: dates on Google's side; `update` is the plain post.
KINDS = {"update": "STANDARD", "offer": "OFFER", "event": "EVENT"}
#: The buttons Google renders. `CALL` uses the listing's own number and takes
#: no URL; every other one carries the link the owner chose.
CTAS = ("LEARN_MORE", "BOOK", "ORDER", "SHOP", "SIGN_UP", "CALL")
CTA_WORDS = {"LEARN_MORE": "Learn more", "BOOK": "Book", "ORDER": "Order online",
             "SHOP": "Shop", "SIGN_UP": "Sign up", "CALL": "Call now"}

_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+\.(?:com|net|org|co|io|us|shop)\b",
                  re.I)
_HASHTAG = re.compile(r"(?:^|\s)#\w+")


def _keyword_in(text: str, keyword: str) -> bool:
    """Every real word of the keyword, in the text — order-free, so "event
    venue in Miami" is found in "Miami's event venue for…"."""
    words = [w for w in re.findall(r"[a-z0-9']+", keyword.lower()) if len(w) > 2
             and w not in ("the", "and", "for", "with", "near")]
    low = text.lower()
    return bool(words) and all(w in low for w in words)


def review(body: str, *, keyword: str = "", kind: str = "update",
           offer_terms: str = "", event_start: str = "",
           urgency_backed_by: str = "") -> list[dict]:
    """Craft findings for one post. `[]` means nothing to say.

    Same vocabulary as `ad_craft.review`: "block" is a defect the owner should
    not have to catch, "nudge" is a note. Nothing edits the copy; every
    finding names what is wrong and the fix, and the redraft applies it.
    """
    out: list[dict] = []

    def add(sev, rule, detail, fix):
        out.append({"severity": sev, "rule": rule, "detail": detail, "fix": fix})

    text = (body or "").strip()
    if not text:
        return out
    if len(text) > SUMMARY_MAX:
        add("block", "too_long", f"{len(text)} characters",
            f"Google takes {SUMMARY_MAX} at most — cut to one idea")
    words = len(text.split())
    if words < WORDS_MIN:
        add("nudge", "too_short", f"{words} words",
            f"under {WORDS_MIN} words there is nothing for the local pack to "
            f"match on — say the one idea, the place, and what to do next")
    elif words > WORDS_MAX:
        add("nudge", "too_long_to_read", f"{words} words",
            f"past {WORDS_MAX} words it is a page, not a post; keep the one "
            f"idea and move the rest to the link")
    if keyword and not _keyword_in(text[:SNIPPET], keyword):
        add("block", "local_keyword_not_in_the_snippet",
            f"{keyword!r} is not in the first {SNIPPET} characters",
            "the first sentence is the snippet and what the listing is "
            "matched on — name the category and the place there, in "
            "plain words, not as a tag")
    if _PHONE.search(text):
        add("block", "phone_number_in_the_body", _PHONE.search(text).group(0),
            "Google rejects phone numbers in a post; the Call button uses "
            "the listing's own number")
    if _URL.search(text):
        add("block", "url_in_the_body", _URL.search(text).group(0),
            "Google rejects links in the text; the button carries the link")
    if _HASHTAG.search(text):
        add("block", "hashtags", _HASHTAG.search(text).group(0).strip(),
            "hashtags are not indexed on Business Profile and read as spam "
            "there — say the words in a sentence instead")
    shouting = [w for w in re.findall(r"\b[A-Z]{4,}\b", text)
                if w not in ("GBP", "USA", "FAQ")]
    if len(shouting) >= 3:
        add("nudge", "shouting", ", ".join(shouting[:3]),
            "sentence case — capitals read as an advert shouting, and the "
            "local pack renders them as such")
    if kind == "offer" and not (offer_terms or "").strip():
        add("block", "offer_without_terms", "no terms on the plan",
            "an offer post needs its terms (dates, conditions) — from the "
            "owner, never invented; put them on the plan")
    if kind == "event" and not (event_start or "").strip():
        add("block", "event_without_dates", "no start date on the plan",
            "an event post needs its dates from the owner — put them on "
            "the plan")
    urg = _find(text, URGENCY)
    if urg and not (urgency_backed_by or "").strip():
        add("block", "urgency_without_a_deadline", ", ".join(sorted(set(urg))[:3]),
            "there is no deadline behind this — state the real one on the "
            "plan or drop the pressure")
    vague = _find(text, VAGUE) + _find(text, PLATITUDES)
    if vague:
        add("nudge", "vague_adjectives", ", ".join(sorted(set(vague))[:4]),
            "replace each with the concrete thing — a material, a number, a "
            "moment; these are true of every competitor in the pack too")
    return out


def block_reasons(findings: list[dict]) -> list[dict]:
    return [f for f in findings or [] if f.get("severity") == "block"]


def as_prompt(findings: list[dict]) -> str:
    if not findings:
        return ""
    return ("\n\n## Problems with your draft — fix every one\n"
            + "\n".join(f"- {f['detail']} → {f['fix']}" for f in findings))


SYSTEM = """You are writing one Google Business Profile post for a local business.

## What a post is
It is shown under the business's listing in local search and on Maps. The
FIRST SENTENCE is the snippet people see and the text the listing is matched
on — it must name, in plain words, what the business is (its category) and
where it is (its place). One idea per post. Between 60 and 250 words. No
hashtags, no phone number, no link in the text: the button carries the link.
Sentence case. Plain sentences a neighbour would say.

## What must be true
Assert nothing that is not in the material you are given. If the post is made
FROM an approved article, email or ad, shorten it and add nothing — no new
number, price, origin or guarantee. If it is written from scratch, build only
on the claim or the approved answer you are given. The hard rules are enforced
in code after you write, so a draft breaking one is thrown away rather than
softened.

## An offer or an event
Their terms and dates come from the owner and are given to you verbatim.
Never invent a discount, a date or a condition.
"""

REPLY_FORMAT = """Answer in exactly this shape and nothing else:

TITLE: <for an offer or event only — under 58 characters; leave blank for an update>
---
<the post itself: 60–250 words, plain sentences>"""


def brief(*, keyword: str, kind: str, cta: str, url: str,
          source_kind: str = "", source_text: str = "", source_label: str = "",
          objection: str = "", response: str = "", claim: str = "",
          evidence: str = "", offer_terms: str = "", event_title: str = "",
          event_start: str = "", event_end: str = "", place: str = "",
          voice: str = "", positioning: str = "",
          revision_notes: str = "") -> list[str]:
    """Everything the drafter is told, as inspectable parts — assertable
    without an API key, the lesson `ad_prompt` carries."""
    parts: list[str] = []
    if revision_notes:
        parts.append("## The owner reviewed the previous draft — address this "
                     "before anything else\n" + revision_notes.strip())
    parts.append(f"## The local keyword — it belongs in the FIRST sentence\n"
                 f"{keyword or '(none given — name the category and the place '
                 f'as best the material says)'}")
    if place:
        parts.append(f"## Where this business is\n{place}")
    if positioning:
        parts.append(f"## What the brand stands for\n{positioning[:300]}")
    if voice:
        parts.append(f"## The house voice\n{voice[:300]}")
    if source_text:
        parts.append(f"## MADE FROM this approved {source_kind or 'artifact'}"
                     + (f" — {source_label}" if source_label else "")
                     + "\nShorten it into one post. Add nothing it does not "
                       "say.\n\n" + source_text[:5000])
    elif objection:
        parts.append(f"## The hesitation this post answers\n{objection}\n\n"
                     f"## The approved answer — the ONLY thing you may build on"
                     f"\n{response}")
    elif claim:
        parts.append(f"## The one claim this post reinforces — the ONLY thing "
                     f"you may build on\n{claim}"
                     + (f"\n(evidence: {evidence})" if evidence else ""))
    parts.append(f"## Post type\n{kind}"
                 + (f"\n## The offer's terms, verbatim from the owner\n{offer_terms}"
                    if kind == "offer" else "")
                 + (f"\n## The event, verbatim from the owner\n{event_title} — "
                    f"{event_start}" + (f" to {event_end}" if event_end else "")
                    if kind == "event" else ""))
    parts.append(f"## The button under the post\n{CTA_WORDS.get(cta, cta)}"
                 + (f" → {url}" if url and cta != "CALL" else "")
                 + "\nThe last sentence should make pressing it the natural "
                   "next step, without saying 'click'.")
    parts.append("## How to answer\n" + REPLY_FORMAT)
    return parts


def parse(raw: str) -> dict:
    """Split a reply into {title, body}. Forgiving: no markers means all body."""
    text = str(raw or "").strip()
    title, body = "", text
    if "---" in text:
        head, _, body = text.partition("---")
        body = body.strip()
        for ln in head.split("\n"):
            m = re.match(r"^\s*TITLE\s*:\s*(.*)$", ln, re.I)
            if m:
                title = m.group(1).strip()[:TITLE_MAX]
    else:
        lines = text.split("\n")
        keep = []
        for ln in lines:
            m = re.match(r"^\s*TITLE\s*:\s*(.*)$", ln, re.I)
            if m:
                title = m.group(1).strip()[:TITLE_MAX]
            else:
                keep.append(ln)
        body = "\n".join(keep).strip()
    return {"title": title, "body": body}


def compose(*, keyword: str, cta: str, source_text: str = "",
            response: str = "", claim: str = "", place: str = "") -> str:
    """The offline fallback — a deterministic restatement, and it says so in
    `basis` upstream. Never craft-reviewed as if it were writing."""
    lead = keyword or place or "this business"
    first = f"{lead[0].upper() + lead[1:]}: here is one thing worth knowing this week."
    material = (source_text or response or claim or "").strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", material) if s.strip()]
    middle = " ".join(sentences[:2])
    close = f"{CTA_WORDS.get(cta, 'Learn more')} below to see for yourself."
    return " ".join(x for x in (first, middle, close) if x).strip()


def _ymd(s: str) -> dict:
    try:
        d = _dt.date.fromisoformat(str(s or "").strip()[:10])
    except ValueError:
        return {}
    return {"year": d.year, "month": d.month, "day": d.day}


def payload(body: str, *, kind: str, cta: str, url: str, title: str = "",
            offer_terms: str = "", coupon: str = "", event_start: str = "",
            event_end: str = "", media_url: str = "",
            language: str = "en-US") -> dict:
    """The body Google's `localPosts.create` takes — built here, once, so the
    workroom preview and the publish arm cannot disagree about what ships.

    OFFER and EVENT both require `event` (a title and a schedule) on Google's
    side; `offer` adds the terms. `CALL` takes no URL — the listing's number
    is the button. Shapes are from the v4 reference (VERIFY on the first live
    post, like every Google call here)."""
    p: dict = {"languageCode": language, "summary": (body or "")[:SUMMARY_MAX],
               "topicType": KINDS.get(kind, "STANDARD")}
    if cta == "CALL":
        p["callToAction"] = {"actionType": "CALL"}
    elif cta in CTAS and url:
        p["callToAction"] = {"actionType": cta, "url": url}
    if kind in ("offer", "event"):
        first_line = (body or "").strip().split("\n")[0]
        p["event"] = {"title": (title or first_line)[:TITLE_MAX],
                      "schedule": {"startDate": _ymd(event_start),
                                   "endDate": _ymd(event_end or event_start)}}
    if kind == "offer":
        p["offer"] = {k: v for k, v in (("couponCode", coupon),
                                        ("redeemOnlineUrl", url),
                                        ("termsConditions", offer_terms)) if v}
    if media_url:
        p["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": media_url}]
    return p
