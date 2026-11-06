"""Money, percentages, durations and ratings, given a subject by their words.

The figures a business is held to — a free-shipping threshold, a discount, a
return window, a delivery time, a fee — read by `app.quantities` (one rule set,
shared with the draft gate). A bare price beside a product has no subject and
is not recorded here; the catalogue owns it.
"""
from __future__ import annotations

from ... import quantities

NAME = "quantities"
VERSION = 1
USES_MODEL = False


def run(doc: dict, terms: tuple = ()) -> list[dict]:
    body = " ".join(" ".join(b.split()) for b in doc.get("body_blocks", [])).lower()
    out, seen = [], set()
    for field, lines in (("visible", doc.get("lines", [])), ("page_data", doc.get("page_data", []))):
        for ln in lines:
            for f in quantities.find(ln):
                key = (f["subject"], f["value"], f["text"])
                if key in seen:
                    continue
                seen.add(key)
                f["field"] = ("page_data" if field == "page_data"
                              else "body" if f["match"].lower() in body else "furniture")
                out.append(f)
    return out
