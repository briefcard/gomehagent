"""What a human changed before it went out — the only honest quality signal.

`SystemRun.edit_diff` has been in the schema since the systems spine landed,
with its own docstring calling it *"the highest-value column here — what a
human changed before approving is the only honest signal of where the generator
is wrong"*. Nothing ever wrote it. So "is this better than the model alone" had
no answer beyond catches, and `% drafts sent as-is` sat in `metrics.CATALOG`
marked unmeasurable.

It could not be written because the two halves were never joined: a draft was
created in Gmail, an approval was queued from a COPY of what it said at that
moment, and approving composed a third message from that copy. Editing the
draft changed nothing anybody read. Now the draft is what sends, so the draft is
what can be compared.

**The diff is stored as a summary, not as the text.** A customer reply is the
client's correspondence; keeping a second copy of every one in an approvals
payload is a data store nobody asked for. What a quality signal needs is how
much changed and where — `changed`, the ratio, and a short unified sample —
which is enough to see a pattern and not enough to reconstruct the letter.
"""
from __future__ import annotations

import difflib
import re


def _norm(text: str) -> list[str]:
    """Comparable lines. Signature blocks and quoted history are stripped.

    Without this every diff is 100% changed: Gmail appends the quoted original
    to a reply, and a signature the drafter never wrote arrives on every send.
    Counting those as human edits would make the number useless in the
    direction that flatters nobody.
    """
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            break                    # quoted history — everything after is theirs
        if re.match(r"^On .+ wrote:$", line):
            break
        out.append(re.sub(r"\s+", " ", line))
    return out


def delta(generated: str, sent: str) -> dict:
    """How far the sent version drifted from the drafted one."""
    a, b = _norm(generated), _norm(sent)
    if not a and not b:
        return {"measured": False, "why": "nothing to compare"}
    sm = difflib.SequenceMatcher(None, a, b)
    ratio = sm.ratio()
    changed = [l for l in difflib.unified_diff(a, b, lineterm="", n=0)
               if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    return {
        "measured": True,
        # `as_is` is the metric the owner asked for. A tiny threshold rather
        # than exact equality: a trailing space or a smart quote is not an
        # edit, and calling it one would report a generator as worse than it is.
        "as_is": ratio >= 0.995,
        "similarity": round(ratio, 3),
        "lines_changed": len(changed),
        # Capped. Enough to see a pattern across many replies, not enough to
        # reconstruct the client's correspondence from our own tables.
        "sample": "\\n".join(changed[:12])[:1200],
    }


def record(approval, generated: str, sent: str) -> dict:
    """File the delta against the approval, and the run if there is one.

    Both, because they answer different questions. The approval carries it for
    "what happened to this reply"; `SystemRun.edit_diff` carries it for "is this
    system getting better", which is the question the column was added for.
    """
    from . import db

    d = delta(generated, sent)
    if not d.get("measured"):
        return d
    try:
        with db.SessionLocal() as s:
            ap = s.get(db.Approval, approval.id if hasattr(approval, "id")
                       else approval)
            if ap:
                ap.payload = {**(ap.payload or {}),
                              "edit": {k: d[k] for k in
                                       ("as_is", "similarity", "lines_changed")},
                              "edit_sample": d["sample"]}
                run_id = ap.run_id
            else:
                run_id = ""
            if run_id:
                run = s.get(db.SystemRun, run_id)
                if run and not run.edit_diff:
                    run.edit_diff = d["sample"] or ("sent unchanged"
                                                    if d["as_is"] else "")
                    run.decision = run.decision or ("approved" if d["as_is"]
                                                    else "edited")
            s.commit()
    except Exception:                                            # noqa: BLE001
        pass          # measuring quality must never block a send
    return d


def record_run(run_id: str, generated: str, sent: str) -> dict:
    """File the delta against a RUN that may have no approval behind it.

    `record` reaches the run THROUGH an approval, which is right for mail —
    every reply there is queued for a person. A campaign on the `shadow` or
    `auto` rung has no approval at all, and on those rungs the delta is still
    the number the Measured section is built from: what we first produced
    against what actually went. Requiring an approval to measure would mean
    the systems being trusted MOST are the ones nobody can check.
    """
    from . import db

    d = delta(generated, sent)
    if not d.get("measured") or not run_id:
        return d
    try:
        with db.SessionLocal() as s:
            run = s.get(db.SystemRun, run_id)
            if run is not None and not run.edit_diff:
                run.edit_diff = d["sample"] or ("sent unchanged"
                                                if d["as_is"] else "")
                run.decision = run.decision or ("approved" if d["as_is"]
                                                else "edited")
                s.commit()
    except Exception:                                            # noqa: BLE001
        pass          # measuring quality must never block a send
    return d
