"""Every console control has a suite that presses it, and every warning a
producer computes reaches a surface.

Owner, 2026-08-28, after a landing page turned out to scrape nothing:
**"The real question is how many UI units we built that you didn't build the
piping for?"** The honest answer is not a survey. It is two computed
populations, each with a shrink-only allowlist, so the number can be asked
again by anybody at any time and cannot drift upward in silence.

  1. **CONTROLS.** Every `<form action=…>` and `_act(…)` target in the
     console, mapped to its route. `test_pointers` already refuses a control
     that points nowhere; this refuses a control that no suite ever presses.
     A route that exists and a route that works are different claims, and
     the second one is only true if something exercises it.

  2. **WARNINGS.** Every key a producer returns whose NAME says something went
     wrong — `missing`, `refused`, `dropped`, `needs_human`, `skipped` — that
     no UI file mentions. This is the shape the landing-page defect actually
     had: `harvest` returned a per-source report naming the source that read
     nothing, `_summarise` kept only the numeric keys, and the fact existed
     where no human could reach it. A warning computed and never rendered is
     the same defect as a KB rule that never reaches a validator.

Both lists MAY SHRINK AND MUST NEVER GROW — the same contract as
`test_sabotage_anchors`'s KNOWN_STALE and the smoke suite's ALLOWED_BARE.
Adding a control without a suite, or computing a new warning nothing shows,
fails the build in the commit that does it, which is when it is cheap.

    python3 scripts/test_control_piping.py
"""
from __future__ import annotations

import ast
import collections
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI = ("app/admin_ui.py", "app/portal_ui.py")

#: Controls no suite presses. Every one of these was pressed BY HAND on
#: 2026-08-28 and verified to move real state (asset_add files a photograph,
#: assets_decide flips it publishable, system_note reaches feedback_block,
#: plan_cadence persists the horizon, merge_situation retags, person_access
#: changes access, brand_theme/approve writes the live theme) or to refuse
#: with a named reason when its third party is absent (connect_test,
#: segments_build, esp_push, campaign_meta_save, brand_theme/derive,
#: email_harvest). Hand-verified is not suite-verified: that is exactly why
#: they are listed here rather than quietly passing.
UNPRESSED = {
    "/admin/asset_add",
    "/admin/assets_decide",
    "/admin/brand_theme/approve",
    "/admin/brand_theme/derive",
    "/admin/campaign_meta_save",
    "/admin/connect_test",
    "/admin/email_harvest",
    "/admin/esp_push",
    "/admin/merge_situation",
    "/admin/person_access",
    "/admin/plan_cadence",
    "/admin/segments_build",
    "/admin/system_note",
}

#: Words that make a key a WARNING rather than a datum.
WARN_WORDS = ("missing", "needs_", "unavailable", "refused", "rejected",
              "dropped", "failed", "blocked", "stale", "problem",
              "skipped", "truncated", "degraded", "still_", "conflict",
              "orphan", "expired", "not_verbatim")

#: Warning-shaped keys computed today and rendered nowhere. Each is a fact
#: about something that went wrong which no person can currently see. This set
#: is the backlog, it is written down rather than discovered again, and it may
#: only shrink.
UNRENDERED_WARNINGS = {
    "approvals.reconcile_drafts": {"still_waiting"},
    "canva.editable_from_image": {"orphan"},
    "catalog_sync.sync_collections": {"refused"},
    "catalog_sync.sync_shopify": {"drafts_skipped", "drafts_skipped_examples"},
    "compliance.scan": {"pages_skipped_unchanged"},
    "creative.harvest_drive": {"skipped_small"},
    "digest.brief": {"stale", "stale_total"},
    "email_harvest.mine": {"rejected_for_banned_claim", "rejected_not_verbatim",
                           "skipped_by_reason", "write_refused",
                           "write_refused_count"},
    "extract.extract": {"rejected_not_verbatim"},
    "extract.extract_qa": {"rejected"},
    "harvest.harvest": {"dropped_by_reason", "not_verbatim_count",
                        "pages_skipped", "rejected_for_banned_claim",
                        "rejected_not_verbatim", "skipped_examples",
                        "truncated_page_count", "truncated_pages",
                        "write_refused", "write_refused_count"},
    "kb.assign_to_group": {"refused"},
    "kb.suggest_tags": {"similar_to_rejected"},
    "keywords.cluster": {"orphan_pillars"},
    "omnisend.draft_from_html": {"orphan"},
    "propose.objection": {"needs_at_approval"},
    "responder.answer": {"draft_blocked_by", "draft_rejected"},
    "shopify_webhooks.handle": {"needs_human"},
    "sources.fill": {"still_needs_a_human"},
    "systems.ready": {"missing_contract"},
    "voice.propose": {"dropped_examples"},
    "web.schema_check": {"tenant_column_missing_from"},
}


_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _controls() -> dict[str, set[str]]:
    """Every control the console renders, from the markup, by route."""
    out: dict[str, set[str]] = collections.defaultdict(set)
    for f in UI:
        text = (ROOT / f).read_text()
        for m in re.finditer(r"<form([^>]*)>", text):
            attrs = m.group(1)
            act = re.search(r"action=['\"]([^'\"{]+)", attrs)
            if not act:
                continue
            meth = "POST" if re.search(r"method=['\"]?post", attrs, re.I) else "GET"
            out[act.group(1).strip()].add(meth)
        for m in re.finditer(r"_act\(\s*[a-z_0-9]+\s*,\s*['\"]([^'\"]+)['\"]", text):
            out[m.group(1)].add("GET")
    return dict(out)


def _produced_keys() -> dict[str, set[str]]:
    """Keys each public producer puts into a returned dict."""
    out: dict[str, set[str]] = collections.defaultdict(set)
    for path in sorted((ROOT / "app").glob("*.py")):
        if path.name in ("admin_ui.py", "portal_ui.py", "db.py"):
            continue
        for fn in ast.walk(ast.parse(path.read_text())):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name.startswith("_"):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                    for k in node.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            out[f"{path.stem}.{fn.name}"].add(k.value)
    return dict(out)


def main() -> int:
    # ── 1. every control is pressed by some suite ─────────────────────────
    controls = _controls()
    ck("the control sweep found a real population, not an empty regex",
       len(controls) > 40, str(len(controls)))
    # EXCLUDING THIS FILE. The first version grepped every suite including
    # itself, and `UNPRESSED` below names all thirteen paths — so the
    # allowlist was read as proof that the controls were pressed and the
    # check reported zero unpressed controls. A check that counts its own
    # bookkeeping as evidence proves nothing, which is the trap this whole
    # file exists to close.
    me = pathlib.Path(__file__).name
    suites = "\n".join(f.read_text() for f in (ROOT / "scripts").glob("test_*.py")
                       if f.name != me)
    unpressed = {c for c in controls if c not in suites}
    print(f"— {len(controls)} controls · {len(unpressed)} pressed by no suite —")

    new = sorted(unpressed - UNPRESSED)
    ck("no NEW control ships without a suite that presses it", not new,
       ", ".join(new) or "a control nothing presses is a control nobody has "
       "proved does anything — which is how a scraper that read no landing "
       "pages passed 113 suites")
    fixed = sorted(UNPRESSED - unpressed)
    ck("the unpressed list has not grown", unpressed <= UNPRESSED | set(new),
       "it may shrink; it must never grow")
    if fixed:
        print(f"       {len(fixed)} now pressed — delete from UNPRESSED: "
              + ", ".join(fixed))

    # ── 2. every warning a producer computes reaches a surface ────────────
    ui_blob = "\n".join((ROOT / f).read_text() for f in UI)
    produced = _produced_keys()
    ck("the producer sweep found a real population", len(produced) > 50,
       str(len(produced)))

    found: dict[str, set[str]] = {}
    for owner, keys in produced.items():
        hidden = {k for k in keys
                  if any(w in k for w in WARN_WORDS)
                  and f'"{k}"' not in ui_blob and f"'{k}'" not in ui_blob}
        if hidden:
            found[owner] = hidden
    total = sum(len(v) for v in found.values())
    print(f"— {len(produced)} producers · {total} warning-shaped keys no UI "
          f"file mentions —")

    grew = sorted(f"{o}.{k}" for o, ks in found.items()
                  for k in ks - UNRENDERED_WARNINGS.get(o, set()))
    ck("no NEW warning is computed and hidden", not grew,
       ", ".join(grew[:6]) or "a fact about something going wrong that no "
       "surface renders is a fact nobody can act on — the shape the "
       "landing-page defect actually had")
    healed = sorted(f"{o}.{k}" for o, ks in UNRENDERED_WARNINGS.items()
                    for k in ks - found.get(o, set()))
    ck("the hidden-warning backlog has not grown",
       all(found.get(o, set()) <= UNRENDERED_WARNINGS.get(o, set()) | set()
           for o in found) or bool(grew),
       "it may shrink; it must never grow")
    if healed:
        print(f"       {len(healed)} now rendered — delete from "
              f"UNRENDERED_WARNINGS: {', '.join(healed[:8])}")

    # ── 3. the one this audit was born from ───────────────────────────────
    # `tone_from` says whether a model inferred the tone with evidence or the
    # arithmetic guessed it. The panel offered Adopt without it for a day.
    ck("the voice panel says WHERE the tone came from",
       "tone_from" in ui_blob,
       "a tone from pure measurement and a tone inferred with quotes behind "
       "it must not look identical above an Adopt button")
    ck("…and warns when the sample was too thin to lean on",
       "sample_warnings" in ui_blob)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
