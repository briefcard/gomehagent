"""A Drive harvest reads the folder, and says so when it stops early.

`harvest_drive` called `files().list(pageSize=min(limit, 100))` ONCE and never
passed a `pageToken`. Drive returns at most 100 files per call, so a brand with
400 photographs in the folder was harvested down to the newest 40 and the reply
said `seen: 40` — a number a reader takes for an answer.

This platform's recorded conclusion about its own creative is that asset
scarcity was never the blocker and asset SPECIFICITY is. A harvest that stops
early and does not say so manufactures the scarcity it was built to remove.

The same class as the existing guard `catches_are_not_silently_capped`: a run
that read a page and reported it as if it were the set. A ceiling is fine; a
ceiling nobody can see is not.

    python3 scripts/test_the_harvest_reads_the_folder.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'hv.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import creative, db, tenants  # noqa: E402

_fail: list[str] = []
CALLS: list[dict] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _drive(total: int):
    """A folder with `total` images, served 100 at a time like the real API."""
    CALLS.clear()
    shelf = [{"id": f"f{i}", "name": f"portofino pitcher {i}.jpg",
              "mimeType": "image/jpeg", "webViewLink": f"https://d/{i}",
              "imageMediaMetadata": {"width": 1600, "height": 900}}
             for i in range(total)]

    class _Files:
        def list(self, **kw):
            CALLS.append(kw)
            start = int(kw.get("pageToken") or 0)
            size = min(int(kw.get("pageSize") or 100), 100)
            page = shelf[start:start + size]
            nxt = start + len(page)
            class _Ex:
                def execute(self_inner):
                    return {"files": page,
                            **({"nextPageToken": str(nxt)} if nxt < total else {})}
            return _Ex()

    class _Svc:
        def files(self):
            return _Files()

    creative._drive_service = lambda alias: _Svc()
    return _Svc()


def main() -> int:
    db.init_db()
    tenants.seed()
    with db.SessionLocal() as s:
        row = s.get(db.Tenant, "baci")
        row.gmail_alias = "baci-alias"
        s.commit()
    _drive(250)

    print("— it reads past the first page —")
    got = creative.harvest_drive("baci", limit=250)
    ck("the harvest ran", got["ok"], "")
    ck("it read all 250, not the first 100", got["seen"] == 250, str(got["seen"]))
    ck("  which took more than one call", len(CALLS) >= 3, f"{len(CALLS)} calls")
    ck("  each asking for at most 100, as Drive allows",
       all(int(c.get("pageSize") or 0) <= 100 for c in CALLS),
       str([c.get("pageSize") for c in CALLS]))
    ck("  and every call after the first carried a page token",
       all(c.get("pageToken") for c in CALLS[1:]),
       str([c.get("pageToken") for c in CALLS]))
    ck("nothing more is claimed when the folder is exhausted",
       got.get("more_in_drive") is False, str(got.get("more_in_drive")))

    print("\n— and a ceiling is SAID, not silent —")
    _drive(400)
    small = creative.harvest_drive("baci", limit=40)
    ck("a limit still bounds the run", small["seen"] == 40, str(small["seen"]))
    ck("  and the reply says there are more", small.get("more_in_drive") is True,
       str(small.get("more_in_drive")))
    ck("  in words, on the note a person actually reads",
       "MORE than" in small["note"] and "raise the limit" in small["note"],
       small["note"][-90:])
    # The invariant that matters: a run never files more than it says it read.
    # A harvest whose `seen` and `filed` can diverge is one whose report is a
    # different number from its behaviour — which is the whole defect here.
    ck("  and it never files more than it reports seeing",
       small["filed"] + small["skipped_small"] <= small["seen"],
       f"filed={small['filed']} skipped={small['skipped_small']} "
       f"seen={small['seen']}")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
