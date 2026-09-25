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
          full: bool = True, read: bool = False) -> dict:
    """`{ok, png, door, ms, why}` — the email as a browser shows it, whole.

    `read=True` also READS the render, in the same session: `texts` — every
    visible line of text as the browser drew it (colour, size, weight, face,
    where) — `grounds`, the background colours painted, and `ground`, the
    page shot again with every letter transparent, so the pixels under each
    line are its real ground, photograph or gradient included
    (`recreate.seen` measures contrast and coherence from them).

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
        return _shoot(html, which, width=width, scale=scale, full=full, t0=t0, read=read)
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "png": b"", "door": which,
                "ms": int((time.monotonic() - t0) * 1000),
                "why": f"the browser did not answer: {type(e).__name__}: {str(e)[:160]}"}
    finally:
        _SEM.release()


def _shoot(html: str, which: str, *, width: int, scale: int, full: bool, t0: float,
           read: bool = False) -> dict:
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
            seen = _read(page, width) if read and png else {}
        finally:
            browser.close()
    return {"ok": bool(png), "png": png, "door": which,
            "ms": int((time.monotonic() - t0) * 1000), "why": "" if png else "an empty picture",
            **seen}


#: Every visible run of text, as drawn. A run the reader cannot see is left
#: out: no box, hidden, faded to nothing, under 6 px (the preheader tricks),
#: or covered where it sits (a clipped `max-height:0` block paints nothing).
_READ_JS = r"""() => {
  const texts = [], grounds = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walk.nextNode())) {
    const t = n.nodeValue.replace(/\s+/g, " ").trim();
    if (!/[\p{L}\p{N}]/u.test(t)) continue;
    const el = n.parentElement, cs = getComputedStyle(el);
    if (cs.visibility !== "visible" || parseFloat(cs.fontSize) < 6) continue;
    let op = 1;
    for (let e = el; e; e = e.parentElement) op *= parseFloat(getComputedStyle(e).opacity);
    if (op < 0.1) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    const rects = [...r.getClientRects()].filter(q => q.width >= 2 && q.height >= 2)
      .map(q => [q.left, q.top, q.width, q.height]);
    if (!rects.length) continue;
    const q = rects[0], hit = document.elementFromPoint(q[0] + q[2] / 2, q[1] + q[3] / 2);
    if (!hit || !(el.contains(hit) || hit.contains(el))) continue;
    texts.push({text: t.slice(0, 60), chars: t.length, color: cs.color, opacity: op,
                size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight) || 400,
                family: cs.fontFamily, rects: rects.slice(0, 3)});
  }
  for (const el of document.body.querySelectorAll("*")) {
    const bg = getComputedStyle(el).backgroundColor, b = el.getBoundingClientRect();
    if (bg && bg !== "transparent" && !/, 0\)$/.test(bg) && b.width * b.height >= 400)
      grounds.push({color: bg, area: Math.round(b.width * b.height)});
  }
  return {texts, grounds};
}"""

_NO_TEXT = ("*, *::before, *::after, *::marker { color: transparent !important; "
            "-webkit-text-fill-color: transparent !important; text-shadow: none !important; "
            "text-decoration-color: transparent !important; }")


def _read(page, width: int) -> dict:
    """The render READ, beside the picture. The viewport is opened to the
    page's height first, so every line is on screen for `elementFromPoint`
    and the coordinates are the page's. The ground shot is at CSS scale —
    a quarter of the pixels, the same coordinates.

    ADDITIVE: a read that fails says why and the picture still stands — the
    judge must not lose its look because the measuring did."""
    try:
        h = int(page.evaluate("document.documentElement.scrollHeight") or 1000)
        page.set_viewport_size({"width": width, "height": max(1000, min(h, 16000))})
        got = page.evaluate(_READ_JS)
        page.add_style_tag(content=_NO_TEXT)
        ground = page.screenshot(full_page=True, type="png", scale="css")
        return {"texts": got.get("texts") or [], "grounds": got.get("grounds") or [],
                "ground": ground}
    except Exception as e:                                        # noqa: BLE001
        return {"read_why": f"the render could not be read: {type(e).__name__}: {str(e)[:160]}"}


def shoot_fragment(head: str, fragment: str, *, width: int = 600, scale: int = SCALE) -> dict:
    """One baked block — a complete <table> — photographed alone, with the
    email's own <head> (its fonts), at 2×. `{ok, png, door, why}`."""
    which, why = door()
    if not which:
        return {"ok": False, "png": b"", "door": "", "why": why}
    # a transparent page: the picture carries only what the block paints, so
    # a device sits on the email's own ground — the owner saw white rectangles
    # behind every baked word (2026-09-17)
    doc = (f"<!DOCTYPE html><html><head><meta charset='utf-8'>{head}</head>"
           f"<body style='margin:0;padding:0;width:{width}px;background:transparent'>{fragment}</body></html>")
    t0 = time.monotonic()
    got = _SEM.acquire(timeout=TIMEOUT_MS / 1000)
    if not got:
        return {"ok": False, "png": b"", "door": which, "why": "every browser slot is busy — try again"}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = (p.chromium.connect_over_cdp(config.SHOTS_WS, timeout=TIMEOUT_MS)
                       if which == "browserless" else p.chromium.launch())
            try:
                page = browser.new_page(viewport={"width": width, "height": 400}, device_scale_factor=scale)
                page.set_default_timeout(TIMEOUT_MS)
                page.set_content(doc, wait_until="networkidle")
                try:
                    page.evaluate("document.fonts && document.fonts.ready")
                except Exception:                                # noqa: BLE001
                    pass
                el = page.locator("body > table").first
                png = (el.screenshot(type="png", omit_background=True) if el.count()
                       else page.screenshot(full_page=True, type="png", omit_background=True))
                # THE MEASUREMENTS the composer cannot make itself: a word wider
                # than its box is clipped in the picture ("MELAMINE" lost its
                # last letter on the owner's run, 2026-09-17, through three
                # edit rounds), and type set at 8 px is unreadable on a phone.
                try:
                    measured = page.evaluate("""() => {
                        const t = document.querySelector('body > table');
                        if (!t) return {};
                        let smallest = null;
                        const walker = document.createTreeWalker(t, NodeFilter.SHOW_TEXT);
                        let n;
                        while ((n = walker.nextNode())) {
                            if (!n.textContent.trim()) continue;
                            const px = parseFloat(getComputedStyle(n.parentElement).fontSize);
                            if (px && (smallest === null || px < smallest)) smallest = px;
                        }
                        // the rightmost edge any text reaches, against the box: a
                        // table never scrolls, so scrollWidth hides the clipping
                        const box = t.getBoundingClientRect();
                        let right = box.right;
                        const w2 = document.createTreeWalker(t, NodeFilter.SHOW_TEXT);
                        let m;
                        while ((m = w2.nextNode())) {
                            if (!m.textContent.trim()) continue;
                            const r = document.createRange(); r.selectNodeContents(m);
                            for (const rect of r.getClientRects()) if (rect.right > right) right = rect.right;
                        }
                        return {overflow: Math.round(Math.max(0, right - box.right)),
                                box: Math.round(box.width), smallest_px: smallest};
                    }""") or {}
                except Exception:                                # noqa: BLE001
                    measured = {}
            finally:
                browser.close()
        return {"ok": bool(png), "png": png, "door": which, "why": "" if png else "an empty picture",
                "ms": int((time.monotonic() - t0) * 1000), **{k: v for k, v in measured.items() if v is not None}}
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "png": b"", "door": which,
                "why": f"the browser did not answer: {type(e).__name__}: {str(e)[:160]}"}
    finally:
        _SEM.release()
