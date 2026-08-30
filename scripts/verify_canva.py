"""Does Canva actually work — asked of the live API, not of the docs.

Every Canva path in `app/canva.py` carries the same warning in its own
docstring: *"this has never met the live API."* The client was written from
public documentation, and documentation is where the last two integration
surprises came from. This makes the calls for real and says what happened.

NOT A TEST SUITE, and named so `test_all.sh` does not glob it: it needs live
credentials and it makes real calls against a real Canva workspace. The suites
must run offline on every commit; this runs when somebody asks it to.

    python3 scripts/verify_canva.py <tenant>            # read-only
    python3 scripts/verify_canva.py <tenant> --design   # also creates one

The owner's two questions, 2026-08-30:

  1. Does it create organised folders BY CLIENT as intended?
  2. Does a client connecting their OWN Canva take precedence over ours?

Both are yes in the code. `SHARED_PROVIDERS = ("canva",)` means
`credentials.resolve` reads the client's own rows first and only falls through
to the agency's, tagging the result `source: "agency"` so a shared credential
is never reported as the client's own. Folders are two levels — one root for
the installation, remembered as a Setting, and one per account on the tenant
row. Neither has been observed happening.

NOTHING IS PRINTED THAT COULD BE PASTED SOMEWHERE HARMFUL. Not the token, not
a prefix, not a length. The questions are "whose credential" and "what did the
API do", and neither needs the secret.
"""
from __future__ import annotations

import sys

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from app import canva, credentials, db, tenants  # noqa: E402


def _line(label: str, value: str = "", ok: bool | None = None) -> None:
    mark = {True: "  ok  ", False: " FAIL ", None: "  --  "}[ok]
    print(f"[{mark}] {label}" + (f"  — {value}" if value else ""))


def _accounts() -> list | None:
    """The tenant list, or None when there is no database to read.

    A tool whose failure mode is a SQLAlchemy traceback is a tool nobody runs
    twice — and the commonest way to run this wrong is against a local shell
    with no DATABASE_URL, which is precisely the mistake it should name.
    """
    try:
        return list(tenants.all_tenants())
    except Exception:                                            # noqa: BLE001
        return None


def main(argv: list[str]) -> int:
    rows = _accounts()
    if rows is None:
        print("\nNo database reachable. This runs against the LIVE service, "
              "so give it the live DATABASE_URL:\n\n"
              "  DATABASE_URL='...' python3 scripts/verify_canva.py <tenant>\n")
        return 2
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[0])
        print("\nusage: python3 scripts/verify_canva.py <tenant> [--design]")
        print("       tenants: " + (", ".join(t.key for t in rows) or "(none)"))
        return 2
    tenant, want_design = argv[1], "--design" in argv

    print(f"\n=== Canva, live, for {tenant!r} ===\n")
    t = next((x for x in rows if x.key == tenant), None)
    if not t:
        _line("the account exists", f"no tenant {tenant!r}", False)
        return 1

    # ---- 1. whose credential -------------------------------------------
    got = credentials.resolve(tenant, "canva")
    if got.get("error"):
        _line("one Canva connection resolves", str(got["error"]), False)
        return 1
    if not got.get("secret"):
        _line("Canva is connected", "nothing resolved — connect it on the "
                                    "Accounts tab, or connect the agency's", False)
        return 1
    source = got.get("source") or "?"
    _line("Canva resolves", f"source={source}", True)
    _line("…and the CLIENT's own takes precedence" if source == "client"
          else "…falling back to the AGENCY's shared connection",
          "this is the client's own account" if source == "client" else
          "the client has not connected their own; designs will be made in "
          "OUR workspace, which is the documented fallback and worth knowing",
          True if source == "client" else None)

    # ---- 2. can it talk at all -----------------------------------------
    me = canva.call(tenant, "GET", "/users/me")
    _line("the token is accepted", "" if me["ok"] else str(me.get("error"))[:160],
          bool(me["ok"]))
    if not me["ok"]:
        print("\nNothing below can be trusted until that call works.")
        return 1

    # ---- 3. the folder, which is the actual question --------------------
    before = (t.design or {}).get("canva_folder_id") or ""
    _line("a folder was already remembered" if before else
          "no folder remembered yet — this run should create one",
          before or "", None)

    res = canva.folder(tenant)
    if not res.get("ok"):
        _line("a per-client folder exists", str(res.get("error"))[:200], False)
        return 1
    _line("a per-client folder exists",
          f"id={res['folder_id']} created={res.get('created')}", True)

    again = canva.folder(tenant)
    _line("…and a second call REUSES it, never duplicates",
          f"same={again.get('folder_id') == res['folder_id']} "
          f"created={again.get('created')}",
          again.get("folder_id") == res["folder_id"]
          and not again.get("created"))

    with db.SessionLocal() as s:
        row = s.get(db.Tenant, tenant)
        stored = (row.design or {}).get("canva_folder_id") or ""
    _line("…and it is written back to the tenant, so the next process agrees",
          stored or "(nothing stored)", stored == res["folder_id"])

    # ---- 4. optional: does a design land in it --------------------------
    if not want_design:
        print("\nRead-only run. Add --design to create one real design and "
              "check it lands in that folder.")
        return 0

    made = canva.create_design(
        tenant, title="gomehagent verification — safe to delete",
        width=1080, height=1080)
    if not made.get("ok"):
        _line("a design can be created", str(made.get("error"))[:200], False)
        return 1
    _line("a design can be created", str(made.get("design_id", ""))[:40], True)
    _line("…and it was FILED into this client's folder",
          str(made.get("filed_error") or "")[:160] or "filed",
          bool(made.get("filed")))
    _line("…and the library knows about it",
          str(made.get("recorded") or "")[:120]
          or "a design Canva holds that our library does not name is "
             "invisible to every skill",
          bool(made.get("recorded")))
    if made.get("edit_url"):
        print(f"\nOpen it and see where it landed:\n  {made['edit_url']}")
    print("\nThen delete 'gomehagent verification — safe to delete'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
