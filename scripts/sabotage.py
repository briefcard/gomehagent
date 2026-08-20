"""Turn each guard off, and check the suite notices.

A test that passes is not evidence. A test that FAILS when the thing it
describes is broken is. This codebase has caught six tests passing for the
wrong reason — the portal cookie over http, `test_oauth` against a page that
stacked every account, a fixture with literal backslash-n, an authorisation
check on a client that had already signed in, an assertion about absence run
against an empty table, and a go-live gate that passed by never being asked.
Every one was found by accident.

So this does it on purpose. Each entry below disables ONE guard, runs the
suites that claim to cover it, and expects them to fail. Three outcomes:

    caught      the suite failed. The guard is genuinely tested.
    UNDETECTED  the guard was removed and every suite still passed. The
                tests around it are decoration.
    STALE       the code no longer contains what this entry patches. Says so
                loudly rather than reporting a pass, because a sabotage whose
                target has moved silently stops testing anything — which is
                the same failure this file exists to find, one level up.

The repo is restored after every entry, verified byte-for-byte, and a failure
to restore is fatal and shouted about. Nothing here is left applied.

    python3 scripts/sabotage.py            # all of them
    python3 scripts/sabotage.py shop_host  # one, by name
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: One entry per guard whose absence should be loud. `find` must appear exactly
#: once; `why` is the consequence in the world, not the mechanism — a person
#: reading a STALE report needs to know what stopped being covered.
SABOTAGES = [
    {
        "name": "tenant_scope",
        "file": "app/diagnostics.py",
        "find": "    return q.filter(model.tenant == tenant) if tenant else q",
        "replace": "    return q  # SABOTAGE",
        "suites": ["test_diagnostics.py"],
        "why": "one client's runs, tool calls and failures appear on another "
               "client's Diagnostics page",
    },
    {
        "name": "banned_claims_mail",
        "file": "app/triage.py",
        "find": ('        hard = [f for f in report["failures"]\n'
                 '                if f["rule"] in ("banned_claim", "entity_unavailable")]'),
        "replace": "        hard = []  # SABOTAGE",
        "suites": ["test_grounding.py", "test_tenant_isolation.py"],
        "why": "a phrase the client has banned goes out to a customer",
    },
    {
        "name": "guidance_reaches_prompt",
        "file": "app/resolve.py",
        "find": "        guidance = _sys.guidance_block(tenant, system)",
        "replace": '        guidance = ""  # SABOTAGE',
        "suites": ["test_grounding.py"],
        "why": "corrections written on the Systems card never reach a draft — "
               "the loop measures itself and learns nothing",
    },
    {
        "name": "craft_leak_guard",
        "file": "app/craft.py",
        "find": "    return sorted(set(found))",
        "replace": "    return []  # SABOTAGE",
        "suites": ["test_craft.py"],
        "why": "one client's names, products and domains travel into another "
               "client's prompt",
    },
    {
        "name": "shop_host",
        "file": "app/oauth.py",
        "find": '    return host if _SHOP_RE.match(host) else ""',
        "replace": "    return host  # SABOTAGE",
        "suites": ["test_shopify_oauth.py"],
        "why": "our Shopify client_id and client_secret are POSTed to whatever "
               "host an attacker puts in a link",
    },
    {
        "name": "webhook_signature",
        "file": "app/shopify_webhooks.py",
        "find": "    return hmac.compare_digest(want, header)",
        "replace": "    return True  # SABOTAGE",
        "suites": ["test_shopify_compliance.py"],
        "why": "anyone who finds the URL can forge a privacy request and make "
               "us delete a store's credentials",
    },
    {
        "name": "one_reply_per_thread",
        "file": "app/replies.py",
        "find": '    if not held or held["system"] == system_key:',
        "replace": "    if True:  # SABOTAGE",
        "suites": ["test_replies.py"],
        "why": "two systems answer the same customer on the same thread",
    },
    {
        "name": "the_switch",
        "file": "app/systems.py",
        "find": '    return (getattr(system, "status", "") or "") == "live"',
        "replace": "    return True  # SABOTAGE",
        "suites": ["test_replies.py", "test_worker_systems.py"],
        "why": "a paused system keeps running — the off switch does nothing",
    },
    {
        "name": "compliance_double_run",
        "file": "app/worker.py",
        "find": "                compliance.record_scan(\n                    t.key, compliance.scan(t.key, limit=60, since=since))",
        "replace": ("                compliance.record_scan(\n"
                    "                    t.key, compliance.scan(t.key, limit=60, since=since))\n"
                    "                systems.start_run(site.id, t.key, trigger='schedule')  # SABOTAGE"),
        "suites": ["test_correlate.py"],
        "why": "every compliance scan is recorded twice, halving every rate "
               "computed from the ledger",
    },
    {
        "name": "sweep_survives_no_model",
        "file": "app/correlate.py",
        "find": '    if not config.ANTHROPIC_API_KEY:\n        return ""',
        "replace": '    if not config.ANTHROPIC_API_KEY:\n        raise RuntimeError("SABOTAGE")',
        "suites": ["test_correlate.py"],
        "why": "the nightly sweep goes silent when the API key expires, and "
               "silence from a monitor is indistinguishable from all-clear",
    },
]


def run_suite(name: str) -> bool:
    """True if the suite PASSED."""
    p = subprocess.run([sys.executable, f"scripts/{name}"], cwd=ROOT,
                       capture_output=True, text=True, timeout=600)
    out = p.stdout + p.stderr
    return "all checks passed" in out or "all green" in out


def main(only: str = "") -> int:
    entries = [s for s in SABOTAGES if not only or s["name"] == only]
    if only and not entries:
        print(f"no sabotage named {only!r}. Known: "
              + ", ".join(s["name"] for s in SABOTAGES))
        return 2

    undetected, stale = [], []
    for s in entries:
        path = ROOT / s["file"]
        original = path.read_text()

        if original.count(s["find"]) != 1:
            # Not a pass and not a failure: the thing this claims to test has
            # moved or gone, so it has been testing nothing since it did.
            n = original.count(s["find"])
            print(f"[ STALE  ] {s['name']:24} — the target appears {n} times in "
                  f"{s['file']}; this has been covering nothing")
            print(f"            was guarding: {s['why']}")
            stale.append(s["name"])
            continue

        path.write_text(original.replace(s["find"], s["replace"], 1))
        try:
            passed = {n: run_suite(n) for n in s["suites"]}
        finally:
            # Restored whatever happened, and VERIFIED rather than assumed — a
            # harness that leaves a guard disabled is worse than no harness,
            # and this one edits the live tree.
            #
            # No `return` in here: returning from a `finally` swallows the
            # exception that sent us here, which would turn a crashed suite
            # into a silent success. The check below runs after.
            path.write_text(original)
            restored = path.read_text() == original
        if not restored:
            print(f"\n!!! FAILED TO RESTORE {s['file']} — fix it by hand "
                  f"before doing anything else !!!")
            return 3

        noticed = [n for n, ok in passed.items() if not ok]
        if noticed:
            print(f"[ caught ] {s['name']:24} — {', '.join(noticed)}")
        else:
            print(f"[ MISSED ] {s['name']:24} — every suite still passed")
            print(f"            unguarded: {s['why']}")
            print(f"            claimed by: {', '.join(s['suites'])}")
            undetected.append(s["name"])

    print()
    if undetected or stale:
        if undetected:
            print(f"{len(undetected)} guard(s) NOT covered by their suites: "
                  + ", ".join(undetected))
            print("Each one can be removed today and nothing will say so.")
        if stale:
            print(f"{len(stale)} sabotage(s) STALE: " + ", ".join(stale))
            print("The code moved. Re-point them or the coverage is imaginary.")
        return 1
    print(f"all {len(entries)} guards are genuinely tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
