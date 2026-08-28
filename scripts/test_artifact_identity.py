"""Every artifact carries what it IS — with no writer left out.

Owner, 2026-08-28, looking at a Drafts index reading "campaign email ·
2026-08-28" three times: *"Why am I still seeing that these drafts are not
named correctly? This is in the campaign email system but I asked you to take
care of this in all systems."*

They were right. There are THREE places an `ArtifactBody` is constructed —
`ledger.record` (the general path), the ad-batch writer, and the campaign
writer, which keeps its own row because the HTML is only final after render.
Two were given `meta` and the third was not, and "all systems" was a claim
rather than a check.

So this is the check. It reads the SOURCE for every construction site rather
than exercising each skill, because the failure mode is a writer nobody
thought about — and a test that walks the writers it knows about would have
missed this one exactly the way I did.

    python3 scripts/test_artifact_identity.py
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ai.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = pathlib.Path(__file__).resolve().parent.parent

from app import admin_ui  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def writers() -> list[tuple[str, int, bool]]:
    """Every `ArtifactBody(...)` construction, and whether it passes `meta`."""
    out = []
    for path in sorted((ROOT / "app").glob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else getattr(fn, "id", ""))
            if name != "ArtifactBody":
                continue
            has = any(k.arg == "meta" for k in node.keywords)
            out.append((path.name, node.lineno, has))
    return out


def main() -> int:
    sites = writers()
    ck("the artifact writers are found by reading the source",
       len(sites) >= 3, str(sites))

    missing = [f"{f}:{n}" for f, n, has in sites if not has]
    ck("EVERY writer gives the artifact its identity", not missing,
       ", ".join(missing) or "a writer without `meta` is a draft that can "
       "only be named 'format · date' — which is what the owner found")

    # And the label itself, per kind, including the pre-`meta` campaign rows
    # that are named from the `push` recipe they already carry.
    class _A:
        def __init__(self, **kw):
            self.meta, self.push, self.format, self.created_at = {}, {}, "", ""
            for k, v in kw.items():
                setattr(self, k, v)

    lab = admin_ui.artifact_label(_A(
        format="campaign_email", created_at="2026-08-28",
        meta={"subject": "Your table, ready for August",
              "segment": "lapsed_buyers", "intent": "offer"}))
    ck("a campaign is named by its subject, list and intent",
       lab.startswith("Your table, ready for August")
       and "to lapsed_buyers" in lab and "offer" in lab, lab)

    old = admin_ui.artifact_label(_A(
        format="campaign_email", created_at="2026-08-28",
        push={"subject": "An older send", "segment_key": "vip"}))
    ck("a campaign written BEFORE meta existed is still named",
       old.startswith("An older send") and "to vip" in old,
       "the push recipe is already on the row — no backfill needed")

    bare = admin_ui.artifact_label(_A(format="campaign_email",
                                      created_at="2026-08-28"))
    ck("and one with neither falls back rather than rendering blank",
       bare.startswith("campaign email"), bare)

    ck("an article is named by its title",
       admin_ui.artifact_label(_A(
           format="cms_article", created_at="2026-08-28",
           meta={"title": "Acrylic jugs, properly",
                 "keyword": "acrylic jug", "role": "pillar"}))
       .startswith("Acrylic jugs, properly"))
    ck("an ad board by what it sells and to whom",
       "Aqua set" in admin_ui.artifact_label(_A(
           format="ad_batch", created_at="2026-08-28",
           meta={"entity_label": "Aqua set", "audience_key": "hosts",
                 "variants": 3})))

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print(f"all checks passed — {len(sites)} artifact writers, all carrying "
          f"identity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
