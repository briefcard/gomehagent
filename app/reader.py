"""THE READER — who a piece is written to, carried to every mind that writes
or judges its words.

Owner, 2026-10-02, on a Baci email that finally looked right: *"It makes sense
grammatically, but it doesn't land anything that the reader would connect with.
One of the reasons we share the audiences, their pain points, etc is so that
you could always gear the content regardless of topic / context / goal towards
the correct audience."* The email opened "White, decided once and for good" and
told a reader who eats off white plates every day that white "is never the
easy choice".

WHY IT HAPPENED. The persona reached the DRAFTER (`funnel.brief`: pains,
vocabulary, triggers) and the drafter no longer writes the words that ship. The
email maker decides a story and writes the email (`recreate`), and neither it
nor its judge was ever told who the reader is. The story prompt asked for "the
reader's real objection" with nothing to read it from, so it invented one in
the reference's shape. With no reader on the plan, nobody was chosen at all.

What this module holds, so the email and the article read the reader the same way:

* `from_plan` / `text` — the reader as a prompt receives it: who, where they
  are, what they find hard, what is going on, what holds them back (with the
  honest answer), what makes them act, their own words.
* `story_problems` — a story names the ONE need it answers (`for`), quoted from
  the reader, and a problem beat about the reader rests on one. Verified in
  code against the account's own rows; the writer is asked again on a miss.
* `check` — the reader pass: the email's words read as the reader reads them,
  apart from the design judge. This is the truth pass's lesson: asked beside the
  design questions, a copy question gets a fraction of the attention. A premise
  the reader would not agree with, an email that speaks to nothing they have, or a motto
  where the argument belongs each blocks.
"""
from __future__ import annotations

import json
import re

#: The words a match is not made of.
_STOP = frozenset(
    "a an and are as at be been but by can do does for from had has have her hers him his how i if in "
    "into is it its just me more most my no not of on one or our out she so than that the their them "
    "then there they this those to too us was we what when which who why will with would you your".split())

#: A beat that tells the reader something is wrong with their life. One the
#: account never wrote down is invented, whatever its shape.
_FAILING = re.compile(r"problem|objection|pain|failing|doubt|scepticism|skepticism|settled|tension|"
                      r"contrast|worry|struggle|hesitat|fear|frustrat", re.I)


def from_plan(audience: dict | None, plan: dict | None = None, segment: dict | None = None, *,
              chosen_by: str = "") -> dict:
    """The reader, from the run's chosen persona and its funnel plan
    (`funnel.inputs_for`). Persona rows are owner-approved; the situations and
    hesitations are the ones this stage leads with, quoted from the account.
    Nothing here is invented, and an empty field stays empty."""
    a = audience or {}
    p = plan or {}
    have = p.get("have") or {}
    seg = segment or {}
    situations: list[str] = []
    for kind in p.get("leads") or []:
        if str(kind).startswith("situation:"):
            for s in have.get(kind) or []:
                said = str((s or {}).get("description") or (s or {}).get("tag") or "").strip()
                if said and said not in situations:
                    situations.append(said)
    holds = [{"objection": str((o or {}).get("objection") or "").strip(),
              "answer": str((o or {}).get("response") or "").strip()}
             for o in have.get("objection") or [] if str((o or {}).get("objection") or "").strip()]
    trig = str(a.get("buying_trigger") or "").strip()
    return {"key": str(a.get("key") or ""), "who": str(a.get("name") or ""), "chosen_by": chosen_by,
            "list": (f"{seg.get('name', '')} — {seg.get('definition', '')}".strip(" —")
                     if seg.get("key") and seg.get("key") != "general" else ""),
            "stage": (f"{p.get('label')} — they {p.get('reader')}" if p.get("label") and p.get("reader")
                      else str(p.get("label") or "")),
            "pains": [str(x).strip() for x in a.get("pains") or [] if str(x).strip()],
            "situations": situations[:5], "holds_back": holds[:4],
            "acts_when": [trig] if trig else [],
            "words": [str(x).strip() for x in a.get("vocabulary") or [] if str(x).strip()][:12]}


def items(reader: dict | None) -> list[str]:
    """What a story may answer: each thing the account knows this reader HAS.
    Their words are how to say it, not something to answer."""
    r = reader or {}
    return (list(r.get("pains") or []) + list(r.get("situations") or [])
            + [h["objection"] for h in r.get("holds_back") or [] if h.get("objection")]
            + list(r.get("acts_when") or []))


def known(reader: dict | None) -> bool:
    return bool((reader or {}).get("who") or items(reader))


def text(reader: dict | None) -> str:
    """THE READER as every prompt receives it. With nobody on file the
    instruction is the opposite one: no line about the reader's difficulties
    at all, because any would be invented."""
    r = reader or {}
    if not known(r):
        return ("- nobody is on file for this account: no persona says who buys or what they find hard. "
                "Write no line about the reader's difficulties, habits or feelings, because any would be "
                "invented. Say plainly what the product is and what it does, for the use the message names.")
    lines = []
    if r.get("who"):
        lines.append(f"who: {r['who']}")
    if r.get("list"):
        lines.append(f"the list it goes to: {r['list']}")
    if r.get("stage"):
        lines.append(f"where they are: {r['stage']}")
    if r.get("pains"):
        lines.append("what they want or find hard: " + "; ".join(r["pains"]))
    if r.get("situations"):
        lines.append("what is going on for them: " + "; ".join(r["situations"]))
    if r.get("holds_back"):
        lines.append("what holds them back: " + "; ".join(
            h["objection"] + (f" (the honest answer: {h['answer']})" if h.get("answer") else "")
            for h in r["holds_back"]))
    if r.get("acts_when"):
        lines.append("what makes them act: " + "; ".join(r["acts_when"]))
    if r.get("words"):
        lines.append("their own words, to write in: " + ", ".join(r["words"]))
    if not items(r):
        lines.append("nothing is on file about what they find hard: write no line about their difficulties")
    return "\n".join("- " + ln for ln in lines)


def _content(t: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", str(t or "").lower().replace("’", "'"))
            if w not in _STOP and len(w) > 2]


def quotes(said: str, among: list[str], *, share: float = 0.6) -> str:
    """The item `said` quotes, or "". A quote is the item's own words, whole or
    most of them (`share` of its content words), so a paraphrase that keeps the
    substance passes and a sentence that merely shares a word does not."""
    got = _content(said)
    if not got:
        return ""
    flat, bag = " ".join(got), set(got)
    for it in among or []:
        want = _content(it)
        if not want:
            continue
        if " ".join(want) in flat or len(set(want) & bag) / len(set(want)) >= share:
            return it
    return ""


def story_problems(story: dict | None, reader: dict | None) -> list[str]:
    """What a story got wrong about its reader. An empty list when it is right,
    or when the account knows nothing about the reader to hold it to."""
    its = items(reader)
    if not story or not its:
        return []
    out = []
    if not quotes(str(story.get("for") or ""), its):
        out.append('"for" quotes none of THE READER\'s lines. Name the one thing this email answers, '
                   "in the words it is listed in")
    for b in story.get("beats") or []:
        if str(b.get("about") or "").strip().lower() != "the reader" or not _FAILING.search(str(b.get("beat") or "")):
            continue
        if quotes(str(b.get("rests_on") or ""), its) or quotes(str(b.get("says") or ""), its):
            continue
        out.append(f'the beat "{b.get("beat")}" tells the reader a difficulty nobody has written down for them '
                   f'("{str(b.get("says") or "")[:90]}"). Rest it on one of THE READER\'s lines, or drop it')
    return out


# ---------------------------------------------------------------------------
# THE READER PASS — the words, read as the reader reads them
# ---------------------------------------------------------------------------

PASS_PROMPT = """You are the reader below. An email from %(brand)s has just arrived in your inbox.
Read it as yourself, line by line, and answer for yourself.

YOU
%(reader)s

THE EMAIL'S WORDS
%(words)s

Answer JSON only:
{"speaks_to": the one thing under YOU that this email speaks to, quoted as it is written there,
              or "" if it would read the same to anybody on any list,
 "premises": [{"words": the exact words in the email, "why": why you would not nod}] — every line
              that tells you something about your own life, your home, your table, what you find
              hard or easy, or how people live, that you would NOT agree with on reading it: an
              ordinary choice made to sound difficult, a problem you do not have, a habit you do not
              keep, a feeling nobody has. A line you would agree with is not listed,
 "empty": [{"words": the exact words, "why": what it fails to tell you}] — a line in the place of
              the argument (the headline, the hook, a section's first line) that sounds good and
              tells you nothing you can use: a motto, a mood, a slogan. One mood line as the very
              last line is allowed.}"""


def _json(raw: str):
    t = str(raw or "")
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1)
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        got = json.loads(m.group(0), strict=False)
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


def check(words: str, reader: dict | None, *, brand: str = "", tenant: str = "") -> dict:
    """`{ok, findings, calls, speaks_to}` — the reader pass, one short text call.
    A pass that does not answer is SAID and does not block: an unread email
    is unproven, not unsafe, which is the line between this and the truth pass."""
    from . import llm
    if not str(words or "").strip():
        return {"ok": True, "findings": [], "calls": 0, "speaks_to": ""}
    prompt = PASS_PROMPT % {"brand": brand or "a brand", "reader": text(reader), "words": str(words)[:9000]}
    got, calls, reply = None, 0, None
    for _ in range(2):
        reply = llm.ask("email_reader", prompt, tenant=tenant, max_tokens=1500)
        calls += 1
        got = _json(reply.text) if getattr(reply, "ok", False) else None
        if got is not None and any(k in got for k in ("speaks_to", "premises", "empty")):
            break
        got = None
    if got is None:
        return {"ok": False, "calls": calls, "speaks_to": "", "findings": [{
            "code": "reader_unread", "severity": "cosmetic", "where": "the words",
            "what": "the reader pass did not answer ("
                    + (str(getattr(reply, "error", "") or "no JSON, twice")[:120]) + "), so whether this lands is unread"}]}
    its = items(reader)
    near = "; ".join(its[:3])
    out = []
    for f in got.get("premises") or []:
        if isinstance(f, dict) and str(f.get("words") or "").strip():
            out.append({"code": "false_premise", "severity": "blocks", "where": str(f["words"])[:120],
                        "what": "the reader would not agree: " + str(f.get("why") or "")[:220],
                        "do": ("say what is true for them instead, from what they have: " + near) if near
                              else "cut it, or say plainly what the product does"})
    for f in got.get("empty") or []:
        if isinstance(f, dict) and str(f.get("words") or "").strip():
            out.append({"code": "says_nothing", "severity": "blocks", "where": str(f["words"])[:120],
                        "what": "it sounds good and tells the reader nothing: " + str(f.get("why") or "")[:220],
                        "do": ("say the thing it stands in for, to them: " + near) if near
                              else "say the plain thing it stands in for"})
    said = str(got.get("speaks_to") or "").strip()
    if its and not said:
        out.append({"code": "no_reader", "severity": "blocks", "where": "the copy",
                    "what": "it would read the same to anybody. It speaks to nothing this reader has",
                    "do": "open on one of theirs: " + near})
    elif its and not quotes(said, its, share=0.5):
        out.append({"code": "reader_unlisted", "severity": "cosmetic", "where": "the copy",
                    "what": f"it speaks to “{said[:120]}”, which is not on file about this reader",
                    "do": "speak to one of theirs: " + near})
    return {"ok": True, "calls": calls, "speaks_to": said, "findings": out}
