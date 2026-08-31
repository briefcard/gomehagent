"""The knowledge base compiled into a document, ordered so caching works.

This layer should not compete with a brand `.md`. At this corpus size a cached
document beats per-question retrieval outright — nearly free after the first
call, and it cannot surface the wrong thing because everything is present. So
the KB becomes source and the document becomes a build artifact.

The check that matters most here is ORDER. Prompt caching works on prefixes,
so a volatile section near the top invalidates the cache for everything below
it every time a unit sells. Rules and voice barely change; stock changes
hourly. If that ordering is ever "tidied", the entire cost argument for this
approach quietly dies and nothing else in the suite would notice.

    python3 scripts/test_dossier.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ds.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["READ_KEY"] = "r3adonly"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, dossier, kb, tenants  # noqa: E402
from app.web import app  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _seed():
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.set_brand("baci", positioning="Italian-designed tableware for hosts.",
                 tone="formal, brisk")
    for p in ("made in Italy", "handmade", "hand-painted"):
        kb.add_banned("baci", p)
    kb.add_situation("baci", "quality_doubt", patterns=[["dishwasher"]],
                     description="Will it survive real use?", origin="seed")
    kb.add_situation("baci", "order_status", patterns=[["order"]],
                     description="Where is my order?", origin="seed",
                     needs=[{"tool": "shopify_order",
                             "params": ["order_number"]}])
    kb.add_claim("baci", "Every piece is tested on a normal dishwasher cycle.",
                 "tested across the range", ["quality_doubt"],
                 proof_type="data", source="seed", origin="human")
    kb.add_objection("baci", "Will it break in the dishwasher?",
                     "It is dishwasher safe — every piece is tested.",
                     situations=["quality_doubt"], origin="human")
    for r in kb.pending_claims("baci"):
        kb.review_claim(r.id, approve=True)
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Vibe Cup",
                  price="$45", origin="human")


def main() -> int:
    with TestClient(app) as cl:
        tenants.seed()
        _seed()
        doc = dossier.build("baci")
        md = doc["markdown"]

        print("— the hard rules come first, and say they are enforced —")
        ck("the ban list is in it", "handmade" in md)
        ck("it says the rules are code, not a request",
           "enforced in code" in md, "a drafter should know which lines bite")
        ck("rules appear before the catalogue",
           md.index("Hard rules") < md.index("Catalogue"))

        print("\n— ORDER: stable first, volatile last —")
        # If this is ever "tidied" the caching argument dies silently.
        order = [md.index(h) for h in
                 ("Hard rules", "What customers are actually asking",
                  "Answers already approved", "Proof you may lean on",
                  "Catalogue")]
        ck("sections run most-stable to most-volatile",
           order == sorted(order),
           "prompt caching works on prefixes — volatile content at the top "
           "invalidates everything below it on every stock change")
        ck("and the catalogue says why it is last",
           "volatile section, and last on purpose" in md)

        print("\n— the same bytes twice, or nothing is ever cached —")
        again = dossier.build("baci")
        ck("regeneration is byte-identical", again["markdown"] == md)
        ck("so the etag is stable", again["etag"] == doc["etag"], doc["etag"])
        kb.add_entity("baci", "product", "aqua-set", "Aqua Set", price="$90",
                      origin="human")
        after = dossier.build("baci")
        ck("but a real change moves it", after["etag"] != doc["etag"])

        print("\n— only approved rows reach it —")
        kb.add_claim("baci", "An unreviewed crawl sentence 4471.", "",
                     ["quality_doubt"], proof_type="data", source="crawl",
                     status="pending", origin="crawl")
        ck("a pending claim is not in the document",
           "4471" not in dossier.build("baci")["markdown"],
           "the document is compiled from what a human signed off")

        print("\n— it tells you what it does NOT know —")
        ck("gaps are stated, not hidden",
           "does NOT know" in md and "unproven" in md,
           "a reader that knows the edges says less rather than inventing")

        print("\n— live data is named as out of scope —")
        ck("the order lookup is declared, not answered",
           "shopify_order" in md and "need a live lookup" in md,
           "hourly facts do not belong in a cached document")

        print("\n— a system gets only what it needs —")
        desk = dossier.build("baci", "service_desk")
        # `creative` until 2026-08-31. It was never a system: the scope was
        # written the day before `ad_creative` was declared and the two were
        # never reconciled, so the narrow scope was unreachable by the only
        # name a caller has and the whole document came back stamped with the
        # system it had not been scoped to.
        art = dossier.build("baci", "ad_creative")
        ck("the desk gets objections", "Answers already approved" in desk["markdown"])
        ck("the ad scope drops them",
           "Answers already approved" not in art["markdown"],
           "a section nobody reads pushed something useful out of the window")
        ck("but both keep the hard rules",
           "handmade" in desk["markdown"] and "handmade" in art["markdown"],
           "the rules are the one section no scope may drop")
        ck("a key that is not a system is refused, not fallen back on",
           "not a system" in (dossier.build("baci", "creative").get("error") or ""),
           "a fallback that succeeds is the hardest kind of wrong to see")

        print("\n— it says whether it still belongs in a prompt —")
        ck("size is reported", doc["approx_tokens"] > 0, str(doc["approx_tokens"]))
        ck("and judged against a stated budget",
           doc["within_context_budget"] is True
           and doc["budget"] == dossier.CONTEXT_BUDGET_TOKENS,
           doc["advice"][:60])

        print("\n— served as markdown, behind the read key —")
        r = cl.get("/brand.md", params={"tenant": "baci"})
        ck("no credential is refused", "unauthorized" in r.text)
        r = cl.get("/brand.md", params={"tenant": "baci", "key": "r3adonly"})
        ck("the read key gets the document", "Hard rules" in r.text)
        ck("as plain markdown a skill can paste",
           r.headers["content-type"].startswith("text/plain"),
           r.headers["content-type"])
        m = cl.get("/brand_meta", params={"tenant": "baci", "key": "r3adonly"})
        ck("and the meta route carries the cache key, not the payload",
           m.json()["etag"] and "markdown" not in m.json())

        print("\n— an unknown account is named, not guessed —")
        ck("it says so", "unknown account" in dossier.build("nope")["error"])

    print()
    if _fail:
        print(f"FAILED {len(_fail)}:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
