"""A Pinterest board, by its link, onto one of the brand's visual boards —
through Pinterest's public feed, with no API and no sign-in.

Owner, 2026-09-08: *"I dont want to use an API for pinterest but I also
dont have a way to upload those photos directly. Ideally if we can go off
a board link that'd work best."*

THE FEED. Every public board has an RSS feed at
`https://www.pinterest.com/<user>/<board>.rss` (verified 2026-09-08: XML,
about twenty-four items; each carries the pin's title, its link, and a
236-pixel thumbnail at `i.pinimg.com/236x/…`; swapping `/236x/` for
`/originals/` resolves the full-size file, `/736x/` the large thumbnail).
That is the whole contract — a public page format, not an API — so it can
change without notice, and `pins` says plainly when the feed is not there.

WHAT A PIN IS. Somebody else's photograph, saved. It lands with REFERENCE
rights: never sent to the model as pixels (`kb.may_publish` keeps it out of
every request, and the guard on that gate says so), never published. It
guides IN WORDS: `creative.read_board_direction` looks at a board's
reference pins once and writes down the light, framing, palette and styling
they share, and that direction rides every cell drawn for that board. A pin
that is the brand's own photograph can be marked owned on the board — a
decision, not a default.
"""
from __future__ import annotations

import html as _html
import re
from urllib.parse import urlsplit

from . import creative, kb

FEED_DOC = "https://www.pinterest.com/<user>/<board>.rss"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 30
#: How many pins one fill takes — the feed carries about twenty-four, and a
#: direction read looks at the first READ_PINS of them.
PIN_LIMIT, READ_PINS = 40, 8
ORIGINAL, LARGE, THUMB = "/originals/", "/736x/", "/236x/"


def board_url(raw: str) -> tuple[str, str]:
    """`(clean_board_url, why_not)`. A Pinterest board link is
    `https://www.pinterest.com/<user>/<board>/` — two path segments on a
    pinterest host. Anything else is refused by name rather than fetched."""
    text = (raw or "").strip()
    if not text:
        return "", "no link was given"
    if "://" not in text:
        text = "https://" + text
    try:
        u = urlsplit(text)
    except ValueError:
        return "", "that is not a link"
    host = (u.netloc or "").lower()
    if not (host == "pinterest.com" or host.endswith(".pinterest.com")
            or host.endswith(".pinterest.co.uk") or host.endswith(".pinterest.ca")
            or host.endswith(".pinterest.com.au")):
        return "", f"{host or text!r} is not a Pinterest board link"
    parts = [p for p in (u.path or "").split("/") if p]
    if len(parts) != 2 or parts[0].lower() in ("pin", "search", "ideas", "today"):
        return "", ("a board link looks like pinterest.com/<user>/<board>/ — "
                    "this is not one")
    user, board = parts
    if board.endswith(".rss"):
        board = board[:-4]
    return f"https://www.pinterest.com/{user}/{board}/", ""


def feed_url(board: str) -> str:
    return board.rstrip("/") + ".rss"


def _get(url: str) -> tuple[int, bytes]:
    """`(status, body)` for one public URL. A seam: the suite hands feeds in."""
    try:
        import httpx
        r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True,
                      headers={"User-Agent": UA, "Accept": "application/rss+xml, "
                                                            "text/xml, */*"})
        return r.status_code, r.content
    except Exception:                                            # noqa: BLE001
        return 0, b""


get = _get


def full_size(thumb: str) -> str:
    """The full-size file behind a 236px thumbnail — the same path under
    `/originals/`."""
    return thumb.replace(THUMB, ORIGINAL, 1) if THUMB in thumb else thumb


def large(thumb: str) -> str:
    return thumb.replace(THUMB, LARGE, 1) if THUMB in thumb else thumb


def pins(board: str) -> dict:
    """The board's pins off its public feed: `{ok, board, title, pins:
    [{title, link, image, thumb}], error}`."""
    clean, why = board_url(board)
    if why:
        return {"ok": False, "error": why, "pins": []}
    status, body = get(feed_url(clean))
    if status != 200 or not body:
        return {"ok": False, "board": clean, "pins": [],
                "error": (f"Pinterest answered {status or 'nothing'} for the board's "
                          f"feed ({feed_url(clean)}) — the board may be private, "
                          f"secret, or the link is not a board")}
    text = body.decode("utf-8", "ignore")
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {"ok": False, "board": clean, "pins": [],
                "error": "the board's feed was not XML — Pinterest may have changed it"}
    title = (root.findtext("channel/title") or "").strip()
    out = []
    for item in root.iter("item"):
        desc = _html.unescape(item.findtext("description") or "")
        m = re.search(r'<img[^>]+src="([^"]+)"', desc)
        if not m:
            continue
        thumb = m.group(1)
        out.append({"title": (item.findtext("title") or "").strip()[:120],
                    "link": (item.findtext("link") or "").strip(),
                    "image": full_size(thumb), "thumb": thumb})
    if not out:
        return {"ok": False, "board": clean, "title": title, "pins": [],
                "error": "the feed carried no pictures — an empty board, or the "
                         "feed's shape changed"}
    return {"ok": True, "board": clean, "title": title, "pins": out[:PIN_LIMIT]}


def fill_board(tenant: str, slug: str, board: str) -> dict:
    """Every pin of a Pinterest board onto one of the brand's boards, as
    REFERENCE look pins, then the board read into direction words.

    `{ok, added, already, failed, read, note, error}`. Idempotent by URL:
    `kb.add_asset` dedupes on it, so filling twice adds nothing twice.
    """
    have = kb.boards(tenant)
    if slug not in have:
        return {"ok": False, "error": f"no board named {slug!r} on {tenant}"}
    got = pins(board)
    if not got["ok"]:
        return {"ok": False, "error": got["error"]}
    added, already, failed = 0, 0, 0
    for pin in got["pins"]:
        url = pin["image"]
        # A picture that cannot be fetched at full size is kept at the large
        # thumbnail; one that cannot be fetched at all is not filed at all —
        # a pin nobody can look at guides nothing.
        blob = creative._fetch(url)
        if not blob:
            url = large(pin["thumb"])
            blob = creative._fetch(url)
        if not blob:
            failed += 1
            continue
        before = {a.id for a in kb.assets(tenant, publishable_only=False)}
        said = kb.add_asset(tenant, url, rights=kb.REFERENCE,
                            title=(pin["title"] or "Pinterest pin")[:80],
                            kind="image", subject=kb.SCENE,
                            source=f"pinterest: {got['board']}",
                            tags=[], origin="human")
        row = next((a for a in kb.assets(tenant, publishable_only=False)
                    if a.url == url), None)
        if row is None:
            failed += 1
            continue
        if row.id in before or not str(said).startswith("Filed"):
            already += 1
        else:
            added += 1
        kb.set_board_role(row.id, slug, "look", True)
    read = creative.read_board_direction(tenant, slug) if (added or already) else {
        "ok": False, "why": "no pin could be fetched"}
    name = have[slug].get("name") or slug
    note = (f"{added} pin(s) added to “{name}” from {got.get('title') or 'the Pinterest board'}"
            + (f", {already} already there" if already else "")
            + (f", {failed} could not be fetched" if failed else "")
            + " — all as REFERENCE: read for direction, never sent as pixels"
            + (f"; direction read from {read.get('from', 0)} pin(s)" if read.get("ok")
               else f"; direction not read: {read.get('why', '')}"))
    return {"ok": bool(added or already), "added": added, "already": already,
            "failed": failed, "read": read, "board": got["board"], "note": note}
