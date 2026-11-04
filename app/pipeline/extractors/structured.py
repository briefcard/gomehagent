"""Structured data a page declares (JSON-LD): served areas, ratings, counts."""
from __future__ import annotations

NAME = "structured"
VERSION = 1
USES_MODEL = False

#: JSON-LD keys whose LIST value is a count of a subject.
LIST_KEYS = {"areaServed": "coverage.markets", "eligibleRegion": "coverage.markets",
             "availableLanguage": "coverage.languages",
             "currenciesAccepted": "coverage.currencies",
             "paymentAccepted": "coverage.payment_methods"}


def _walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v, path
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, path)


def run(doc: dict, terms: tuple = ()) -> list[dict]:
    out = []
    for i, block in enumerate(doc.get("jsonld", []), 1):
        for key, val, path in _walk(block):
            subj = LIST_KEYS.get(key)
            if not subj:
                continue
            if isinstance(val, str) and "," in val:
                val = [x.strip() for x in val.split(",") if x.strip()]
            if not isinstance(val, list) or len(val) < 2:
                continue
            names = [x.get("name", "") if isinstance(x, dict) else str(x) for x in val]
            out.append({
                "subject": subj, "value": str(len(val)), "number": float(len(val)),
                "qualifier": "counted", "unit": key, "match": f"{key} [{len(val)}]",
                "text": f"structured data {key}: {', '.join(names)[:200]}",
                "field": "structured", "section": path,
                "locator": f"jsonld {i}"})
    return out
