"""Score Claude's claim attribution against an account's BLIND sample sheet.

INITIATIVE-review-surface §3.H: the AI is measured only on labels made
without its answer in view. The client's claim sample sheet is that set —
built with no suggestion shown. This script compares one or more label runs
(prompt variants) with the returned sheet.

    python3 evals/claim_attribution/score.py RETURNED_SHEET.xlsx ENTITIES.json OUT_A.json [OUT_B.json ...]

`ENTITIES.json` is MCP `get_entities` for the account (product names → keys).
Each OUT file is the labeller's JSON array (see prompt_*.md); items are
matched to sheet rows by `n` (the sheet's "#" column) and checked against the
hidden id column.

Reports per run: accuracy of "whose statement" with its 95% Wilson lower
bound, Cohen's kappa, the confusion matrix, product precision / recall on the
rows both call Transak's, and agreement between runs. A sheet row the client
left blank is not scored.
"""
from __future__ import annotations

import collections
import json
import sys

CLIENT_WHOSE = {
    "transak's claim": "transak",
    "a partner's or customer's words": "partner_or_customer",
    "about another company": "other_company",
    "a market or industry fact": "industry_fact",
    "not a claim (navigation, instructions)": "not_a_claim",
}


def wilson_lower(k: int, n: int) -> float | None:
    if not n:
        return None
    from scipy.stats import binomtest
    return float(binomtest(k, n).proportion_ci(confidence_level=0.95, method="wilson").low)


def read_sheet(path: str, ents: dict) -> dict:
    from openpyxl import load_workbook
    ws = load_workbook(path, data_only=True)["Claims"]
    name_to_key = {e["name"].strip().lower(): e["key"] for e in ents}
    out = {}
    for r in range(2, ws.max_row + 1):
        n = ws.cell(r, 1).value
        whose = str(ws.cell(r, 5).value or "").strip().lower()
        if not n or not whose:
            continue
        prods = set()
        for c in (6, 7, 8):
            v = str(ws.cell(r, c).value or "").strip().lower()
            if v and v != "all of transak":
                prods.add(name_to_key.get(v, v))
        out[int(n)] = {"id": ws.cell(r, 15).value, "whose": CLIENT_WHOSE.get(whose, whose),
                       "products": prods, "accurate": ws.cell(r, 9).value,
                       "add": ws.cell(r, 10).value}
    return out


def score(gold: dict, labels: list) -> dict:
    by_n = {int(x["n"]): x for x in labels}
    pairs = [(g["whose"], by_n[n].get("whose", "")) for n, g in gold.items() if n in by_n]
    k = sum(1 for a, b in pairs if a == b)
    from sklearn.metrics import cohen_kappa_score
    kappa = cohen_kappa_score([a for a, _ in pairs], [b for _, b in pairs]) if pairs else None
    conf = collections.Counter(pairs)
    tp = fp = fn = 0
    for n, g in gold.items():
        x = by_n.get(n)
        if not x or g["whose"] != "transak" or x.get("whose") != "transak":
            continue
        p = set(x.get("products") or [])
        tp += len(p & g["products"]); fp += len(p - g["products"]); fn += len(g["products"] - p)
    return {"scored": len(pairs), "whose_correct": k,
            "whose_accuracy": (k / len(pairs)) if pairs else None,
            "whose_lower_bound_95": wilson_lower(k, len(pairs)),
            "cohen_kappa": kappa,
            "confusion": {f"{a} → {b}": v for (a, b), v in sorted(conf.items()) if a != b},
            "products_precision": (tp / (tp + fp)) if tp + fp else None,
            "products_recall": (tp / (tp + fn)) if tp + fn else None}


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    ents = json.load(open(argv[2]))
    ents = ents.get("entities", ents)
    gold = read_sheet(argv[1], ents)
    runs = {p: json.load(open(p)) for p in argv[3:]}
    report = {"gold_rows": len(gold), "runs": {p: score(gold, r) for p, r in runs.items()}}
    if len(runs) >= 2:
        (pa, ra), (pb, rb) = list(runs.items())[:2]
        a = {int(x["n"]): x.get("whose") for x in ra}
        b = {int(x["n"]): x.get("whose") for x in rb}
        both = [n for n in a if n in b]
        report["agreement_between_runs"] = sum(a[n] == b[n] for n in both) / len(both) if both else None
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
