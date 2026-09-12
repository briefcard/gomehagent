"""The screenshot door — the pixels of an email, for the judge and the card.

A judge without pixels is blind. The thing that made the hand-made
recreation of 2026-09-12 good was round two: the headline sat at 45 % of the
column against the reference's 75 %, and that was SEEN, not computed. So the
email is rendered by a real browser and looked at, in production too.

ONE code path, two browsers. Playwright drives both: on this machine a local
Chromium (`playwright install chromium`), in production Browserless over CDP
— the deploy has no browser (`render.yaml` runtime `python`, no Chromium in
`requirements.txt`), and a Chromium in the image needs more memory than the
starter plan gives. The door is chosen by one setting: `SHOTS_WS` set →
Browserless; unset → local; neither reachable → `{"ok": False, "why": …}` and
the caller says the judge was skipped. Nothing raises.

THE PROVIDER'S CONTRACT, pinned from its docs before a byte was sent (owner's
standing rule, memory `learn-what-inputs-the-models-take`), read 2026-09-12:

    https://docs.browserless.io/baas/start      connect_over_cdp, endpoint form
    https://www.browserless.io/pricing          plans, units, concurrency

    endpoint     wss://production-sfo.browserless.io?token=<token>
                 (the region is the host's prefix; the token a query param)
    connect      Playwright `connect_over_cdp` — never `connect`
    a unit       up to 30 seconds of one browser connection; a longer
                 session bills another unit every 30 s
    free plan    1,000 units / month, 2 concurrent browsers, 2-minute sessions
    prototyping  $25 / month, 20,000 units, 10 concurrent, 15-minute sessions

One shot is one unit. The semaphore below holds the free plan's concurrency,
so a burst of previews queues instead of being refused by the provider.
"""
from __future__ import annotations

import threading
import time

from . import config

#: Where the numbers below were read. A STALE contract is a wrong contract.
DOCS = ("https://docs.browserless.io/baas/start",
        "https://www.browserless.io/pricing")

#: The provider's published limits, as read 2026-09-12. `test_the_model_makes
#: _the_email` checks the semaphore and the endpoint form against these.
BROWSERLESS = {
    "endpoint": "wss://production-sfo.browserless.io?token=<token>",
    "connect": "connect_over_cdp",
    "unit_seconds": 30,
    "free_units_per_month": 1000,
    "free_concurrent": 2,
    "free_session_seconds": 120,
}

#: An email is judged at the width the hand-made proof was rendered at, at
#: 2× so the judge sees type as a phone would show it.
WIDTH = 640
SCALE = 2
#: Under the free plan's session cap, with room for fonts to arrive.
TIMEOUT_MS = 45_000

_SEM = threading.BoundedSemaphore(BROWSERLESS["free_concurrent"])


def door() -> tuple[str, str]:
    """Which browser a shot would use, or why none: `("browserless"|"local"|"", why)`."""
    ws = (getattr(config, "SHOTS_WS", "") or "").strip()
    if ws and (not ws.startswith("wss://") or "token=" not in ws):
        return "", "SHOTS_WS is not a Browserless endpoint (wss://…?token=…)"
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:                                            # noqa: BLE001
        return "", "playwright is not installed (pip install playwright)"
    if ws:
        return "browserless", ""
    return "local", "no SHOTS_WS — a local Chromium is used when installed"


def shoot(html: str, *, width: int = WIDTH, scale: int = SCALE,
          full: bool = True) -> dict:
    """`{ok, png, door, ms, why}` — the email as a browser shows it, whole.

    `set_content` rather than a URL: the HTML is unpublished at judge time and
    nothing of it should sit on a public address to be photographed. Fonts
    are waited for (`document.fonts.ready`) so the judge sees the faces the
    email asks for, not the fallback of a browser that had not finished.
    """
    which, why = door()
    if not which:
        return {"ok": False, "png": b"", "door": "", "ms": 0, "why": why}
    t0 = time.monotonic()
    got = _SEM.acquire(timeout=TIMEOUT_MS / 1000)
    if not got:
        return {"ok": False, "png": b"", "door": which, "ms": 0,
                "why": "every browser slot is busy — try again"}
    try:
        return _shoot(html, which, width=width, scale=scale, full=full, t0=t0)
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "png": b"", "door": which,
                "ms": int((time.monotonic() - t0) * 1000),
                "why": f"the browser did not answer: {type(e).__name__}: {str(e)[:160]}"}
    finally:
        _SEM.release()


def _shoot(html: str, which: str, *, width: int, scale: int, full: bool, t0: float) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if which == "browserless":
            browser = p.chromium.connect_over_cdp(config.SHOTS_WS, timeout=TIMEOUT_MS)
        else:
            browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 1000},
                                    device_scale_factor=scale)
            page.set_default_timeout(TIMEOUT_MS)
            page.set_content(html, wait_until="networkidle")
            try:
                page.evaluate("document.fonts && document.fonts.ready")
            except Exception:                                    # noqa: BLE001
                pass
            png = page.screenshot(full_page=full, type="png")
        finally:
            browser.close()
    return {"ok": bool(png), "png": png, "door": which,
            "ms": int((time.monotonic() - t0) * 1000), "why": "" if png else "an empty picture"}
