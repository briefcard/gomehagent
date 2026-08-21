"""Every model call is attributed, classified, and safe to fail.

Twenty-six `messages.create` calls behind eleven clients agreed on nothing but
the prompt: nine logged usage, two classified their errors, and all twenty-six
read `content[0].text`. This pins the four properties that were inconsistent,
and the fourth is the one that has not gone off yet — a response whose first
block is not text.

    python3 scripts/test_llm.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'llm.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["ANTHROPIC_API_KEY"] = "sk-test-not-real"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db, llm, usage  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class Block:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class Msg:
    def __init__(self, blocks, stop_reason="end_turn"):
        self.content = blocks
        self.stop_reason = stop_reason
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 5,
                                    "cache_read_input_tokens": 0,
                                    "cache_creation_input_tokens": 0})()


class Fake:
    """Records what was sent, returns what it was told to."""

    def __init__(self, blocks=None, raises=None):
        self.blocks, self.raises, self.seen = blocks, raises, []
        self.messages = self

    def create(self, **kw):
        self.seen.append(kw)
        if self.raises:
            raise self.raises
        return Msg(self.blocks or [Block("text", "hello")])


def main() -> int:
    db.init_db()

    # --- reading the answer ----------------------------------------------
    print("— the text of a response, whatever leads it —")
    ck("a plain text block reads",
       llm.extract_text([Block("text", "hi")]) == "hi")
    ck("a THINKING block in front does not break it — the trap in all 26 sites",
       llm.extract_text([Block("thinking"), Block("text", "answer")]) == "answer")
    ck("a tool_use block in front does not either",
       llm.extract_text([Block("tool_use"), Block("text", "answer")]) == "answer")
    ck("several text blocks join rather than the first one winning",
       llm.extract_text([Block("text", "a"), Block("text", "b")]) == "ab")
    ck("nothing at all is empty, not an exception", llm.extract_text([]) == "")
    ck("and so is None", llm.extract_text(None) == "")

    # --- which model ------------------------------------------------------
    print("\n— purpose picks the model —")
    ck("classify runs on the cheap one",
       llm.model_for("classify") == config.CLASSIFY_MODEL, llm.model_for("classify"))
    ck("the nightly sweep has its own",
       llm.model_for("sweep") == config.SWEEP_MODEL, llm.model_for("sweep"))
    ck("anything unlisted gets the default, as every unlisted caller already did",
       llm.model_for("something_new") == config.CLAUDE_MODEL)

    fake = Fake()
    llm._client = lambda: fake
    r = llm.ask("something_new", "hi", model="claude-opus-5")
    ck("an explicit model outranks the purpose",
       fake.seen[-1]["model"] == "claude-opus-5", fake.seen[-1]["model"])

    # --- attribution ------------------------------------------------------
    print("\n— every call is attributed —")
    before = len(db.SessionLocal().query(db.Usage).all())
    fake = Fake()
    llm._client = lambda: fake
    r = llm.ask("filing", "classify this", tenant="baci")
    ck("the call succeeded", r.ok and r.text == "hello", r.error or r.degraded)
    rows = db.SessionLocal().query(db.Usage).all()
    ck("a usage row was written", len(rows) == before + 1, f"{before} -> {len(rows)}")
    ck("carrying the purpose", rows[-1].purpose == "filing", str(rows[-1].purpose))
    ck("and the account — the column that is blank on every historical row",
       rows[-1].tenant == "baci", str(rows[-1].tenant))

    # --- failure ----------------------------------------------------------
    print("\n— a provider condition is reported, never raised —")
    boom = Exception("Error code: 400 - {'type': 'error', 'error': {'type': "
                     "'invalid_request_error', 'message': 'You have reached "
                     "your specified spend limit'}}")
    llm._client = lambda: Fake(raises=boom)
    r = llm.ask("filing", "hi")
    ck("it does not raise", isinstance(r, llm.Reply))
    ck("it is not ok", not r.ok)
    ck("and it says what actually happened, not the exception class",
       "limit" in r.error.lower() and "Exception" not in r.error, r.error)
    ck("a failed Reply is falsy, so `if not reply` is the natural gate", not r)

    # --- absence ----------------------------------------------------------
    print("\n— no key is a named absence, not a crash and not silence —")
    real_key = config.ANTHROPIC_API_KEY
    config.ANTHROPIC_API_KEY = ""
    try:
        r = llm.ask("filing", "hi")
        ck("no key does not raise", isinstance(r, llm.Reply))
        ck("it is not ok", not r.ok)
        ck("it names the missing thing", "ANTHROPIC_API_KEY" in r.degraded, r.degraded)
        ck("and it is degraded, NOT an error — nothing went wrong, "
           "something was absent", not r.error)
        ck("it still reports the model it would have used", bool(r.model), r.model)
    finally:
        config.ANTHROPIC_API_KEY = real_key

    # --- no call site may be unattributed --------------------------------
    # The structural half. Every property above can hold in `llm.py` while a
    # new `messages.create` is written next door that logs nothing — which is
    # exactly how nine-of-twenty-six happened in the first place. Nobody was
    # careless; logging was simply a second thing to remember, and a rule that
    # relies on remembering is not a rule.
    print("\n— every model call in the repo is attributed —")
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "app"
    # `**/*.py`, not `*.py`: the wiring audit globbed the top level, missed
    # `app/roles/`, and reported a function as dead that is injected every turn.
    offenders = []
    scanned = 0
    for f in sorted(root.glob("**/*.py")):
        body = f.read_text()
        if "messages.create" not in body:
            continue
        scanned += 1
        if f.name == "llm.py":
            continue                      # the gateway IS the attributed one
        # COUNT the sites, do not merely ask whether the file mentions logging.
        # The first version of this check asked the second question and passed
        # while `triage.py` held three calls and two log lines — the missing one
        # being the JSON-repair retry, on the path that is 93% of model spend.
        # A file-level check cannot see an unattributed call standing next to an
        # attributed one, which is the only shape this defect actually takes.
        if body.count("usage.log_usage") < body.count("messages.create"):
            offenders.append(f"{f.name} "
                             f"({body.count('messages.create')} calls, "
                             f"{body.count('usage.log_usage')} logged)")
    ck(f"every module calling the API also logs usage ({scanned} scanned)",
       not offenders, "unattributed: " + ", ".join(offenders) if offenders else "")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: " + "; ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
