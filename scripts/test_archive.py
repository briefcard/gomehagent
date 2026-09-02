""""What did we agree in March" — the question that broke every inbox draft.

The agent was not stupid. `EmailLog` stored sender, subject and what was done,
and not one word of what was said; `DocIndex` stored that a bill of lading
exists and nothing about what was on it. So an agent asked to reference a prior
thread had two moves: ask, or guess. Both read as a bad model and both are a
storage problem.

The case that proves it is the one keyword search cannot do:

    stored   "the crates arrived broken on the March shipment"
    asked    "what happened with the pallet damage?"

Not one informative word in common. Gmail search returns nothing, so the agent
asks — and asking is the CORRECT behaviour of a system whose retrieval failed.
Suppress the asking and you get invention instead.

    python3 scripts/test_archive.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ar.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["READ_KEY"] = "r3adonly"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import archive, db, embed, resolve as rs, tenants  # noqa: E402
from app.web import app  # noqa: E402

_fail = []

BROKEN = ("Confirming the crates arrived broken on the March shipment. "
          "We agreed to credit the damaged units on the next invoice.")
ASKED = "what happened with the pallet damage?"

CONCEPTS = [
    {"crates", "broken", "damage", "damaged", "pallet", "shipment", "credit"},
    {"invoice", "payment", "terms", "net", "wire", "remittance"},
    {"artwork", "packaging", "label", "print", "proof"},
]


def stub(texts):
    out = []
    for t in texts:
        w = set(re.findall(r"[a-z]+", (t or "").lower()))
        out.append([float(len(w & c)) for c in CONCEPTS] + [0.15])
    return out, ""


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    with TestClient(app) as cl:
        tenants.seed()
        embed.set_provider(stub)

        with db.SessionLocal() as s:
            s.add(db.EmailLog(tenant="baci", account="baci",
                              gmail_message_id="m-1", thread_id="t-1",
                              sender="forwarder@ship.com",
                              subject="March shipment", category="forwarder"))
            s.add(db.EmailLog(tenant="baci", account="baci",
                              gmail_message_id="m-2", thread_id="t-2",
                              sender="bank@x.com", subject="Remittance advice",
                              category="invoice"))
            s.add(db.DocIndex(tenant="baci", filename="BOL-Primorous.pdf",
                              path="B2B/Inbound", doc_type="BOL",
                              anchor="Primorous PO-2241"))
            s.commit()

        print("— catalogued but silent, which is where this started —")
        r = archive.index("baci", kind="thread")
        ck("nothing can be indexed yet", r["chunks_written"] == 0,
           str(r["chunks_written"]))
        ck("and it says the rows hold no text", r["no_text_stored"] == 2,
           str(r["no_text_stored"]))
        ck("naming that as the actual gap", "unanswerable in content" in r["note"])

        print("\n— store what was SAID —")
        n = archive.store_email("baci", "m-1", BROKEN)
        archive.store_email("baci", "m-2", "Remittance advice attached, net 30.")
        ck("the body is kept", n > 0, f"{n} chars")

        print("\n— quoted history is stripped before it lands —")
        threaded = ("Yes, agreed.\n\nOn Mon, Gomeh wrote:\n> the crates arrived "
                    "broken\n> please credit us")
        ck("only the new words survive",
           "agreed" in archive.clean(threaded)
           and "please credit" not in archive.clean(threaded),
           archive.clean(threaded)[:40] + "…")
        # THE CLAIM, ACTUALLY MADE. This was the literal `True` — a rhetorical
        # continuation of the assertion above, printing [ ok ] for a case
        # nobody built. Fifteen deep is where quoting compounds: if `clean`
        # kept even one layer, the row would grow with every reply and the
        # index would hold fifteen near-identical copies of one thread.
        deep = "The latest word."
        for i in range(15):
            deep = f"{deep}\n\nOn Mon, Someone wrote:\n> layer {i}"
        cleaned = archive.clean(deep)
        ck("or a fifteen-message chain is fifteen identical rows",
           "latest word" in cleaned and "layer 0" not in cleaned
           and "layer 14" not in cleaned,
           cleaned[:60] + "…")
        ck("  and it does not grow with the chain",
           len(cleaned) < len(deep) / 3,
           f"{len(cleaned)} chars from {len(deep)} — quoting compounds, so a "
           f"clean that keeps one layer keeps all of them")

        print("\n— THE CASE: found by meaning, not by keyword —")
        archive.index("baci", kind="thread")
        overlap = set(re.findall(r"[a-z]{4,}", BROKEN.lower())) & \
            set(re.findall(r"[a-z]{4,}", ASKED.lower()))
        ck("the question shares no informative word with the thread",
           not overlap, str(overlap))
        found = archive.search("baci", ASKED)
        ck("and it is found anyway", found["hits"], str(len(found["hits"])))
        ck("it is the right thread",
           found["hits"][0]["subject"] == "March shipment",
           found["hits"][0]["subject"])
        ck("with the words that answer the question",
           "credit the damaged units" in found["hits"][0]["excerpt"],
           "this is what the agent used to ask a human for")

        print("\n— coverage is stated, because silence was the original bug —")
        ck("it says how much was searched",
           found["chunks_scanned"] > 0 and "thread" in found["searched_kinds"],
           found["coverage"])
        ck("and an unindexed kind does NOT poison the whole report",
           "document" in found["unsearched_kinds"] and found["hits"],
           "one empty store made a good search read as 'nothing searched'")


        print("\n— noise never reaches the index —")
        with db.SessionLocal() as s:
            s.add(db.EmailLog(tenant="baci", account="baci",
                              gmail_message_id="m-promo", thread_id="t-p",
                              sender="deals@brand.com", subject="50% OFF TODAY",
                              category="promo",
                              body_excerpt="Shop the pallet sale now! " * 20))
            s.add(db.EmailLog(tenant="baci", account="baci",
                              gmail_message_id="m-bot", thread_id="t-b",
                              sender="no-reply@shopify.com",
                              subject="Order confirmation",
                              category="order_routine",
                              body_excerpt="Your order shipped. " * 20))
            s.add(db.EmailLog(tenant="baci", account="baci",
                              gmail_message_id="m-thanks", thread_id="t-t",
                              sender="real@customer.com", subject="Re: crates",
                              category="client_comms",
                              body_excerpt="Thanks!"))
            s.commit()
        r = archive.index("baci", kind="thread")
        ck("a promo blast is declined", r["declined_total"] >= 3, str(r["declined"]))
        ck("and the reason is legible, not a silent drop",
           any("promo" in k for k in r["declined"]), str(list(r["declined"])))
        ck("so is an automated sender",
           any("automated" in k for k in r["declined"]), str(list(r["declined"])))
        ck("and a two-word reply",
           any("chars" in k for k in r["declined"]), str(list(r["declined"])))

        promo = archive.search("baci", "pallet sale")
        ck("the promo cannot be retrieved at all",
           not any(h.get("subject") == "50% OFF TODAY" for h in promo["hits"]),
           "it has content; it is content nobody will ever look for")
        ck("but the real thread still is",
           archive.search("baci", ASKED)["hits"], "the filter is not a mute")

        print("\n— an order thread is KEPT, unlike mining —")
        # email_harvest excludes sales_orders so a customer's words are not
        # mined as brand claims. That says nothing about whether anyone will
        # later ask what shipped on which order.
        ck("sales_orders is not skipped by the archive",
           "sales_orders" not in archive.SKIP_BUCKETS,
           "mining and archiving exclude for different reasons")
        ck("nor is urgent_money", "urgent_money" not in archive.SKIP_BUCKETS)

        print("\n— a long document is chunked, or only page one is findable —")
        # Genuinely past CHUNK_CHARS — the first version of this test was 300
        # characters and "proved" chunking by not needing it.
        filler = ("Routine packing detail describing carton dimensions, pallet "
                  "stacking limits and the labelling convention used on every "
                  "inbound consignment for this account. ")
        long_doc = "\n\n".join(
            [f"Section {i}: {filler * 3}" for i in range(6)]
            + ["Clause 9: artwork proof must be approved before the print run."])
        with db.SessionLocal() as s:
            d = s.query(db.DocIndex).first()
            did = d.id
        archive.store_document("baci", did, long_doc)
        archive.index("baci", kind="document")
        parts = [r for r in embed.BACKEND.rows("baci", "document")]
        ck("it became several chunks", len(parts) > 1, f"{len(parts)} chunks")
        hit = archive.search("baci", "when does the artwork proof get approved?",
                             kinds=("document",))
        ck("and a clause deep inside is findable",
           hit["hits"] and "Clause 9" in hit["hits"][0]["excerpt"],
           "the EXCERPT must be the passage that matched, not the title page")

        print("\n— one row, one hit — a long thread cannot crowd the results —")
        ck("chunks collapse back to their source",
           len({h["id"] for h in hit["hits"]}) == len(hit["hits"]))

        print("\n— it reaches the bundle every system already reads —")
        b = rs.resolve("baci", utterance=ASKED, tier=3)
        ck("correspondence rides along with brand context",
           any(h["kind"] == "thread" for h in b["correspondence"]),
           str([h["kind"] for h in b.get("correspondence", [])]))
        ck("and its coverage is on the receipt",
           "correspondence" in b["coverage"]["searched"])


        print("\n— an attachment belongs to the thread it arrived on —")
        # The join that did not exist: you could find the bill of lading and
        # find the thread where the credit was agreed, and nothing connected
        # them. `anchor` is a business key and answers a different question.
        with db.SessionLocal() as s:
            s.add(db.DocIndex(
                tenant="baci", filename="commercial-invoice-2241.pdf",
                path="(email attachment)", doc_type="invoice", source="email",
                content_hash="h1", thread_id="t-1", gmail_message_id="m-1",
                text_excerpt=("Commercial invoice for the March consignment. "
                              "Six pallets, two recorded as crushed on arrival "
                              "at the DHL hub. Credit note to follow.")))
            s.commit()
        docs = archive.for_thread("baci", "t-1")
        ck("the document is reachable FROM the conversation",
           docs and docs[0]["filename"].startswith("commercial-invoice"),
           str([d["filename"] for d in docs]))
        ck("and it carries what it says, not just its name",
           docs[0]["has_text"] and "crushed" in docs[0]["excerpt"])
        ck("another thread does not inherit it",
           archive.for_thread("baci", "t-2") == [])

        print("\n— and it rides along when the thread is retrieved —")
        archive.index("baci", kind="document")
        b2 = rs.resolve("baci", utterance=ASKED, tier=3)
        thread_hits = [h for h in b2["correspondence"] if h["kind"] == "thread"]
        ck("the retrieved thread carries its attachments",
           any(h.get("attachments") for h in thread_hits),
           "'please see attached' is the least useful sentence in an inbox")


        print("\n— a logo is not an unreadable document —")
        ck("images are ignored, not reported as failures",
           ".png" in archive.IGNORED_TYPES and ".jpg" in archive.IGNORED_TYPES,
           "96 attachments on a logistics inbox, 79 of them signature furniture")
        ck("and a spreadsheet IS a document",
           ".xlsx" in archive.READABLE,
           "openpyxl was already a dependency; skipping it was a gap")

        import io
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Invoice", "1256"])
        ws.append(["Pallets", 6, "two crushed on arrival"])
        buf = io.BytesIO()
        wb.save(buf)
        text = archive._xlsx_text(buf.getvalue())
        ck("its cells come out as text", "1256" in text and "crushed" in text,
           text.replace(chr(10), " | ")[:70])

        print("\n— one account's mail is invisible to another —")
        ck("eien sees none of it",
           archive.search("eien", ASKED)["hits"] == [])

        print("\n— served behind the read key —")
        r = cl.get("/archive_search", params={"tenant": "baci", "q": ASKED})
        ck("no credential is refused", r.json().get("error") == "unauthorized")
        r = cl.get("/archive_search", params={"tenant": "baci", "q": ASKED,
                                              "key": "r3adonly"})
        ck("the read key searches it", r.json()["hits"], str(r.json())[:60])

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
