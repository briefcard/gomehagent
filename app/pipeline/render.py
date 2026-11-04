"""RENDER — draw a JavaScript page in a browser so what a visitor sees is read.

BUILD-MAP M9. Some pages ship almost nothing in their HTML and fetch their
copy when they run (a country picker filled from an API, a slider loaded on
scroll). The parser reads embedded page data, which covers most of them; the
rest need the page drawn. Rendering is OFF unless `config.RENDER_JS` is set
and Playwright is installed — the owner decides whether the deploy carries a
browser (BUILD-MAP §11.3). While off, every page that needed it is recorded
(`page_snapshots.rendered = 2`) and counts against trust: unread is reported,
never assumed empty.
"""
from __future__ import annotations

from .. import config


def needed(doc: dict) -> bool:
    """The page probably holds content its HTML does not: drawn by script, or
    built from interactive pieces (sliders, tabs, pickers) with little text."""
    if doc.get("from_page_data"):
        return True
    thin = len(" ".join(doc.get("body_blocks", []))) < 400
    return bool(doc.get("interactive")) and thin


def available() -> bool:
    if not config.RENDER_JS:
        return False
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def render(url: str, timeout_ms: int = 25_000) -> str:
    """The page's HTML after scripts ran, tabs and accordions opened. "" on failure."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                # Open what a visitor would click to see.
                page.evaluate("""() => {
                  document.querySelectorAll('details').forEach(d => d.open = true);
                  document.querySelectorAll('[aria-expanded="false"]').forEach(b => {
                    try { b.click(); } catch (e) {} });
                }""")
                page.wait_for_timeout(600)
                return page.content()
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 — a failed render reads the HTML we have
        return ""
