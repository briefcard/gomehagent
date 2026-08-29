"""A link in a preview opens a tab. It does not eat the preview.

Owner, 2026-08-29: *"For the email preview — can you make sure all links in
the email open a new tab instead of opening inside the iframe / preview
screen?"*

They did not, and could not. Every preview iframe carried `sandbox=""`, which
denies everything including opening a window, so a click navigated the frame
in place: the email was replaced by whatever it pointed at, and the only way
back was reloading the workroom.

TWO THINGS ARE NEEDED AND ONE ALONE IS USELESS.

  `<base target="_blank">`  makes every link in the document default to a new
                            browsing context, without rewriting a single <a>.
  the sandbox tokens        `allow-popups` lets the window open at all, and
                            `allow-popups-to-escape-sandbox` makes it an
                            ordinary tab instead of one that inherits every
                            restriction and renders scriptless in an opaque
                            origin.

With the base tag and no tokens the click is simply blocked. With the tokens
and no base tag the frame still navigates in place. So both are asserted, at
every call site, computed from the source rather than surveyed by eye — the
standing rule after a claim about "every instance" turned out to be about the
three instances somebody remembered.

    python3 scripts/test_preview_links.py
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'p.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import admin_ui as ui  # noqa: E402

_fail: list[str] = []
SRC = pathlib.Path(__file__).resolve().parent.parent / "app" / "admin_ui.py"


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    src = SRC.read_text()

    print("— every preview iframe, not the ones I remembered —")
    # The placeholder resolves to the constant, so this checks BOTH that
    # every site uses it and that its value is right. Reading the literal
    # would only prove the sites are consistent with each other.
    frames = [f.replace("{PREVIEW_SANDBOX}", ui.PREVIEW_SANDBOX)
              for f in re.findall(r'<iframe sandbox="([^"]*)"', src)]
    ck("there are preview iframes to check", len(frames) >= 4, str(len(frames)))
    ck("…and every one of them uses the shared constant",
       all(f == ui.PREVIEW_SANDBOX for f in frames), str(set(frames)),)
    ck("none is left unable to open a window",
       all(f != "" for f in frames),
       "sandbox=\"\" denies opening a window, so the click navigates the "
       "frame in place and eats the preview")
    ck("each allows the popup AND lets it escape the sandbox",
       all("allow-popups" in f and "allow-popups-to-escape-sandbox" in f
           for f in frames),
       "allow-popups alone opens a tab that inherits every restriction — "
       "scriptless, opaque origin, and it looks broken")

    print("\n— and every srcdoc carries the base tag —")
    docs = re.findall(r'srcdoc="([^"]*)"', src)
    ck("every srcdoc is built through the helper",
       docs and all("_preview_html" in d or d == "{srcdoc}" for d in docs),
       str(docs))
    ck("…including the one built into a variable first",
       "srcdoc = _esc(_preview_html(" in src,
       "the email preview assigns srcdoc once and uses it twice")

    print("\n— where the tag goes, which is the whole care —")
    full = ('<!DOCTYPE html><html><head><title>t</title></head>'
            '<body><a href="https://x/">go</a></body></html>')
    out = ui._preview_html(full)
    ck("a full document gets it inside <head>",
       '<head><base target="_blank">' in out)
    ck("…after the doctype, never before it",
       out.lower().index("<!doctype") < out.lower().index("<base"),
       "content before the doctype drops the document into quirks mode, "
       "which changes the box model and how tables lay out — on the surface "
       "whose whole job is showing what lands in the inbox")
    ck("…and the email's own markup is otherwise untouched",
       out.replace('<base target="_blank">', "") == full,
       "a preview that edits the artifact is not a preview")

    nohead = '<!DOCTYPE html><html><body><a href="https://x/">go</a></body></html>'
    ck("a document with no head gets one",
       '<head><base target="_blank"></head>' in ui._preview_html(nohead)
       and ui._preview_html(nohead).lower().index("<!doctype") <
       ui._preview_html(nohead).lower().index("<base"))
    ck("a bare fragment is simply prefixed",
       ui._preview_html("<p>hi</p>") == '<base target="_blank"><p>hi</p>')
    ck("a document that already declares a base is left alone",
       ui._preview_html('<html><head><base href="https://y/"></head></html>')
       == '<html><head><base href="https://y/"></head></html>',
       "it has chosen, and a second base tag is ignored anyway")
    ck("an empty body stays empty", ui._preview_html("") == "")

    print("\n— and it never touches where the links POINT —")
    ck("only target is set, never href",
       "target=" in ui._BASE_TAG and "href=" not in ui._BASE_TAG,
       "a <base href> re-resolves every relative URL in the email, which "
       "silently changes what the links go to")

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
