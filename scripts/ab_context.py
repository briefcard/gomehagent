"""Is this layer better than a brand .md file and some MCP tools?

That is the right question to ask of it, and it deserves a measurement rather
than an argument. Both arms get the same model, the same questions and the
same scaffold. Only the context differs.

    arm A   the GENERATED brand document                 (what you'd ship)
    arm B   resolve() for this question only         (this layer)

**The validator scores both arms.** That is the part that makes this a real
experiment rather than a demo: the judge is deterministic code that neither
arm can charm, and it is the same code in production. A model grading a model
would be the second locked decision violated in the measurement instead of in
the product.

What gets counted, per arm:

    violations    banned phrases in the output. The only score that is
                  unambiguous — a rule was broken or it was not.
    cited         did it lean on an approved claim, or make something up that
                  happened to sound right
    prompt_tokens what the context cost. The .md arm pays for the whole file
                  on every question; this layer pays for what was relevant.
    latency       wall clock, end to end

**Be honest about where the baseline wins.** At one client with a short, stable
knowledge base, a .md file is simpler and probably comparable. The claims this
layer should be judged on are the ones that scale: cost per question as the
knowledge base grows, brand adherence when nobody is reviewing, freshness of
price and stock, and whether "why did it say that" has an answer. Run this at
n=20 on one client and it will tell you little; run it as the knowledge base
grows and the curves separate — or they do not, and that is worth knowing too.

    ANTHROPIC_API_KEY=… DATABASE_URL=… python3 scripts/ab_context.py baci
    …                                  python3 scripts/ab_context.py baci --arm b
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, dossier, kb, resolve as rs, validator  # noqa: E402

SYSTEM = """You are answering a customer for this brand. Use only what the
context supports. If you do not know something, say so plainly rather than
guessing. Answer in 2-4 sentences."""


def brand_md(tenant: str) -> str:
    """Arm A is now `dossier.build()` — the document this layer COMPILES.

    It started as a hand-rolled baseline to beat, and that was the wrong
    frame. The two arms are not layer-versus-document; they are two ways of
    spending the same knowledge base. Arm A sends all of it, cached. Arm B
    sends the part that bears on the question. Testing against a document
    nobody would ship told us nothing about the choice actually in front of us.
    """
    return dossier.build(tenant)["markdown"]


def bundle_text(tenant: str, q: str) -> tuple[str, dict]:
    """Arm B: only what bears on this question."""
    b = rs.resolve(tenant, utterance=q, tier=3)
    parts = [b["rules"]["block"].strip(), ""]
    if b.get("objections"):
        parts.append("## Answers already approved for this kind of question")
        for o in b["objections"]:
            parts.append(f"- Q: {o['objection']}\n  A: {o['response']}")
    if b.get("claims"):
        parts.append("\n## Proof you may lean on")
        for c in b["claims"]:
            parts.append(f"- {c['claim']} ({c['evidence']}) [{c['scope']}]")
    if b.get("entities"):
        parts.append("\n## Products in scope")
        for e in b["entities"]:
            parts.append(f"- {e.get('name')} — fits: {e.get('fits')} "
                         f"({e.get('why', '')})")
    if b.get("needs_lookup"):
        parts.append("\n## This needs a live lookup")
        for n in b["needs_lookup"]:
            parts.append(f"- call {n['tool']} with {n['have']} -> {n['returns']}")
    parts.append(f"\n(grounding: {b['grounding']['level']} — "
                 f"{b['grounding']['means']})")
    return "\n".join(parts), b


def ask(system: str, context: str, q: str) -> tuple[str, dict, float]:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    t0 = time.time()
    msg = client.messages.create(
        model=config.CLAUDE_MODEL, max_tokens=400, system=system,
        messages=[{"role": "user",
                   "content": f"{context}\n\n---\nCustomer asks: {q}"}])
    return (msg.content[0].text.strip(),
            {"prompt_tokens": msg.usage.input_tokens,
             "output_tokens": msg.usage.output_tokens},
            round(time.time() - t0, 2))


def score(tenant: str, answer: str, claim_ids: list[str]) -> dict:
    """The same deterministic judge production uses. Neither arm can charm it."""
    v = validator.check(tenant, answer, claim_ids=claim_ids,
                        require_citation=False)
    return {"violations": [f["detail"] for f in v["failures"]
                           if f["rule"] == "banned_claim"],
            "ok": v["ok"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tenant")
    ap.add_argument("--questions", default="",
                    help="file with one question per line; omit for the "
                         "built-in set derived from this account's situations")
    ap.add_argument("--arm", default="both", choices=["a", "b", "both"])
    args = ap.parse_args()
    t = args.tenant

    if not config.ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY is not set — both arms need the same model.")
        return 2

    if args.questions:
        qs = [q.strip() for q in open(args.questions) if q.strip()]
    else:
        # Derived from the account's own vocabulary, so the probe set is not
        # quietly written to favour either arm.
        qs = [f"{(r.description or r.tag).rstrip('?')}?"
              for r in kb.situation_rows(t)][:12]
    if not qs:
        print(f"no questions — {t} has no situation descriptions to derive from")
        return 2

    md = brand_md(t)
    print(f"# A/B on {t}   {len(qs)} questions")
    meta = dossier.build(t)
    print(f"# arm A document: {meta['approx_tokens']} tokens, "
          f"etag {meta['etag']} — {meta['advice'][:70]}\n")

    totals = {"a": {"tok": 0, "viol": 0, "sec": 0.0},
              "b": {"tok": 0, "viol": 0, "sec": 0.0}}
    rows = []
    for q in qs:
        row = {"q": q}
        if args.arm in ("a", "both"):
            ans, u, secs = ask(SYSTEM, md, q)
            s = score(t, ans, [])
            row["a"] = {"answer": ans, **u, "secs": secs, **s}
            totals["a"]["tok"] += u["prompt_tokens"]
            totals["a"]["viol"] += len(s["violations"])
            totals["a"]["sec"] += secs
        if args.arm in ("b", "both"):
            ctx, b = bundle_text(t, q)
            ans, u, secs = ask(SYSTEM, ctx, q)
            s = score(t, ans, [c["claim_id"] for c in b.get("claims", [])])
            row["b"] = {"answer": ans, **u, "secs": secs, **s,
                        "grounding": b["grounding"]["level"],
                        "ctx_chars": len(ctx)}
            totals["b"]["tok"] += u["prompt_tokens"]
            totals["b"]["viol"] += len(s["violations"])
            totals["b"]["sec"] += secs
        rows.append(row)
        print(json.dumps(row, indent=2, default=str))

    n = len(qs)
    print("\n" + "=" * 66)
    for arm, label in (("a", "A  brand.md"), ("b", "B  resolve()")):
        if args.arm not in (arm, "both"):
            continue
        d = totals[arm]
        print(f"{label:14s} prompt tokens/q {d['tok'] // n:6d}   "
              f"banned-phrase violations {d['viol']:3d}   "
              f"sec/q {d['sec'] / n:5.2f}")
    if args.arm == "both":
        a, b = totals["a"], totals["b"]
        if a["tok"]:
            print(f"\ncontext cost: arm B is {100 * b['tok'] // a['tok']}% of arm A")
        print("Read violations first — it is the only unambiguous number here. "
              "Token cost is the claim that compounds as the KB grows; at this "
              "size it is indicative, not conclusive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
