# Claim attribution — evaluation (INITIATIVE-review-surface §3.H)

Who said a harvested statement (the account, a partner or customer, another
company, the industry, or nobody — not a claim), which product an account's
claim is true of, and the source / date / topic of an industry fact. Claude
proposes; people confirm. Claude's accuracy is measured ONLY against labels
made without its answer in view — the client's claim sample sheet.

* `prompt_A_brief.md`, `prompt_B_detailed.md` — the two prompt variants
  compared (prompt detail is domain-dependent; Majer & Šnajder 2024).
* `score.py` — compares label runs with the returned sheet: accuracy with a
  95% Wilson lower bound, Cohen's kappa, confusion, product precision/recall,
  and agreement between variants.

Client content (the sampled statements, the labels, the returned sheet) is
NOT kept in the repo; it lives with the account's working files.

## Transak, round 1 (2026-11-09)
100 statements sampled across every page type (`Transak-claim-sample-sheet.xlsx`,
sent to the client blind). Both variants labelled the same 100 independently,
with page title, section and the sentences either side; results held until
the sheet returns. Nothing was written to production.
