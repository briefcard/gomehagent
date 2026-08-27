"""Every route and tab the code POINTS AT exists. Mechanically, forever.

The owner found four of one defect family in a single day, all from the user
side: a message directing them to a place that did not hold the thing — a tab
with no such section, a board whose filters excluded the row, a redirect
landing elsewhere than its own message pointed, a link inside a card whose
display condition excluded the case that generated it.

The judgement half of that family (does the surface show the referent in the
generating state) needs eyes. THIS half does not: a string that names
`/admin/keywords_harvest` or `tab=plan` either matches a registered route and
a real tab or it does not. Extracted from the AST — every string constant,
f-string fragments included, comments excluded — so a renamed route whose
pointers were forgotten fails here by name before anyone clicks it.

    python3 scripts/test_pointers.py
"""
import ast
import os
import pathlib
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pt.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import admin_ui  # noqa: E402
from app.web import app  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if cond is False else ""))
    if not cond:
        _fail.append(label)


def _strings(path: pathlib.Path):
    """Every string in a module — f-strings reconstructed WHOLE.

    An f-string arrives from the AST as fragments: the Shopify base
    f"https://{domain}/admin/api/..." is the constants "https://" and
    "/admin/api/", and checked fragment-by-fragment the second reads as a
    console pointer with its external context amputated. Joined strings are
    reassembled with a placeholder where each expression sat, so URL context
    survives, and their fragments are not yielded a second time.
    """
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return
    inside_joined = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    inside_joined.add(id(v))
                    parts.append(v.value)
                else:
                    parts.append("\x00")
            yield node.lineno, "".join(parts)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in inside_joined):
            yield node.lineno, node.value


def _external_spans(s: str):
    """Character ranges inside absolute URLs to hosts that are not ours.

    Shopify's Admin API lives at https://<store>/admin/api/... and every
    provider's OAuth endpoints end in /oauth/authorize|token — their PATHS
    collide with our route namespace, and the first run of this suite flagged
    all of them. A pointer inside a full external URL is that provider's
    business; our own absolute links are built as f"{PUBLIC_BASE_URL}/..."
    whose CONSTANT fragment starts at the slash, so they stay checked.
    """
    for m in re.finditer(r"https?://[^\s\"'<>]*", s):
        yield m.start(), m.end()


def main() -> int:
    routes = {r.path for r in app.routes}

    def resolves(p: str) -> bool:
        if p in routes:
            return True
        return any(r == p or r.startswith(p + "/") or r.startswith(p + "{")
                   or (r.split("{")[0].rstrip("/") == p) for r in routes)

    from app import portal_ui
    tabs = {t for t, _l, _i in admin_ui._TABS}
    # The portal has its OWN tab vocabulary — the first run of this suite
    # flagged /portal?tab=requests against the console's tabs, a category
    # error: two surfaces, two vocabularies, each checked against its own.
    portal_tabs = {t for t, _l, _i in portal_ui._NAV}
    subs = dict(admin_ui.REVIEW_SUBS)

    pointed, bad_paths, bad_tabs, bad_subs = set(), [], [], []
    for f in sorted((ROOT / "app").glob("*.py")):
        for lineno, s in _strings(f):
            ext = list(_external_spans(s))

            def _ours(m) -> bool:
                return not any(a <= m.start() < b for a, b in ext)

            for m in re.finditer(r"/(?:admin|connect|intake|decide|portal|oauth|health)/[a-z_]+", s):
                if not _ours(m):
                    continue
                path = m.group(0)
                pointed.add(path)
                if not resolves(path):
                    bad_paths.append(f"{f.name}:{lineno} → {path}")
            for m in re.finditer(r"tab=(?:&amp;)?([a-z_]+)", s):
                vocab = portal_tabs if "/portal" in s else tabs
                if m.group(1) not in vocab:
                    bad_tabs.append(f"{f.name}:{lineno} → tab={m.group(1)}")
            if "tab=content" in s:
                for m in re.finditer(r"sub=([a-z_]+)", s):
                    if m.group(1) not in subs:
                        bad_subs.append(f"{f.name}:{lineno} → sub={m.group(1)}")

    print(f"— {len(pointed)} distinct paths pointed at across app/ —")
    ck("every pointed-at path resolves to a registered route",
       not bad_paths, "; ".join(bad_paths[:6]))
    ck("every tab= names a real tab", not bad_tabs, "; ".join(bad_tabs[:6]))
    ck("every Review sub= names a real section", not bad_subs,
       "; ".join(bad_subs[:6]))
    ck("the sweep found a real population, not an empty regex",
       len(pointed) > 25, str(len(pointed)))

    # ── background-status labels: one writer vocabulary, one reader ─────
    #
    # The sweep found THREE of four background actions writing status under
    # labels nothing read ("email_harvest", "catalog sync", "compliance
    # scan" vs the banner's email/sync/scan) — so a crashed run looked
    # identical to one still running, which is the exact broken-button
    # experience _run_bg exists to remove. Writer labels and reader labels
    # are string literals; parity is mechanical.
    writers = set()
    text = (ROOT / "app" / "web.py").read_text()
    for m in re.finditer(r'_run_bg\(\s*"([a-z_ ]+)"', text):
        writers.add(m.group(1))
    readers = {label for label, _name in admin_ui.BG_LABELS}
    print(f"— bg labels: writers {sorted(writers)} · readers {sorted(readers)} —")
    ck("every background writer's label has a reader",
       writers <= readers, str(sorted(writers - readers)))

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f_ in _fail:
            print(f"  - {f_}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
