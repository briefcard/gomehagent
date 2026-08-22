"""The branded renderer: one canonical email, two clients, two distinct looks.

The owner's bar is a SEND-READY email, branded per client, not a draft. This
checks the "branded per client" and "sendable" halves the renderer owns: the
same canonical blocks handed two different themes produce visibly different,
correctly-branded HTML; the legal footer (address + unsubscribe) is always
present; neutral tokens survive for the ESP layer to make native; and a theme
with no mailing address is flagged as un-sendable rather than shipped.

Run: python3 scripts/test_email_render.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'er.db')}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import email_render as er  # noqa: E402

_fail: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


EIEN = {
    "name": "Eien Health",
    "colors": {"bg": "#eef3f1", "surface": "#ffffff", "text": "#12332b",
               "accent": "#2f7d6b", "accent_text": "#ffffff"},
    "font": {"heading": "Georgia, serif", "body": "Helvetica, Arial, sans-serif"},
    "nav": [{"label": "Shop", "url": "https://eienhealth.com/shop"},
            {"label": "Bestsellers", "url": "https://eienhealth.com/best"},
            {"label": "Learn", "url": "https://eienhealth.com/learn"}],
    "footer": {"brand": "Eien Health", "address": "1213 South 30th Ave, Hollywood FL 33020",
               "tagline": "Science-backed wellness.",
               "socials": [{"name": "Instagram", "url": "https://instagram.com/eien"},
                           {"name": "TikTok", "url": "https://tiktok.com/@eien"}],
               "disclaimer": "These statements have not been evaluated by the FDA. "
                             "This product is not intended to diagnose, treat, cure, "
                             "or prevent any disease."},
}
BACI = {
    "name": "Baci Milano USA",
    "colors": {"bg": "#faf7f2", "surface": "#ffffff", "text": "#2a2018",
               "accent": "#b5122e", "accent_text": "#ffffff"},
    "font": {"heading": "'Playfair Display', Georgia, serif", "body": "Arial, sans-serif"},
    "footer": {"brand": "Baci Milano USA", "address": "4360 NW 135th St, Opa-locka FL 33054",
               "tagline": "Italian design for the table."},
}

BLOCKS = [
    {"type": "hero", "image": "https://cdn.example.com/hero.jpg",
     "headline": "A little something new", "sub": "Picked for you this week."},
    {"type": "text", "html": "<p>Hi {{FIRST_NAME}}, we thought of you.</p>"},
    {"type": "products", "items": [
        {"image": "https://cdn.example.com/p1.jpg", "name": "The one everyone asks about",
         "price": "$48", "url": "https://example.com/p1"},
        {"image": "https://cdn.example.com/p2.jpg", "name": "Back in stock",
         "price": "$32", "url": "https://example.com/p2"}]},
    {"type": "cta", "label": "Shop the edit", "url": "https://example.com/shop"},
    {"type": "mystery", "note": "an unknown block the renderer must survive"},
]


def main() -> int:
    a = er.render(EIEN, BLOCKS, preheader="Just for you")
    b = er.render(BACI, BLOCKS, preheader="Just for you")

    print("— both render as real, email-safe HTML —")
    for name, html in (("eien", a), ("baci", b)):
        ck(f"{name}: has a doctype and table layout",
           html.startswith("<!DOCTYPE html>") and "role=\"presentation\"" in html)

    print("\n— same content, two brands, visibly different —")
    ck("the two emails are not the same bytes", a != b)
    ck("eien carries its own accent and name",
       "#2f7d6b" in a and "Eien Health" in a and "#b5122e" not in a)
    ck("baci carries its own accent and name",
       "#b5122e" in b and "Baci Milano USA" in b and "#2f7d6b" not in b)
    ck("each uses its own heading font",
       "Playfair" in b and "Playfair" not in a)

    print("\n— the legal footer is always present (CAN-SPAM) —")
    for name, html, addr in (("eien", a, "Hollywood"), ("baci", b, "Opa-locka")):
        ck(f"{name}: physical address in the footer", addr in html)
        ck(f"{name}: an unsubscribe link", er.UNSUB in html)

    print("\n— neutral tokens survive for the ESP layer to make native —")
    ck("body personalization token is untouched (not escaped, not rendered)",
       "{{FIRST_NAME}}" in a)
    ck("view-in-browser token present", er.BROWSER in a)
    ck("the copy's link survived (body html not escaped)",
       "href=\"https://example.com/shop\"" in a or "example.com/shop" in a)

    print("\n— nav, socials, and disclaimer render from brand data —")
    ck("eien renders a working nav link",
       'href="https://eienhealth.com/shop"' in a and "Bestsellers" in a)
    ck("eien renders social links",
       "Instagram" in a and 'href="https://instagram.com/eien"' in a)
    ck("eien renders its DSHEA disclaimer",
       "not been evaluated by the FDA" in a)
    ck("baci, with none of those set, skips them cleanly (no empty chrome)",
       "Instagram" not in b and "Bestsellers" not in b)

    print("\n— robustness —")
    ck("an unknown block is skipped, not fatal",
       "skipped unknown block: mystery" in a)
    no_addr = er.render({"name": "New Co", "colors": {"accent": "#333"}}, BLOCKS)
    ck("a theme with no address renders a loud, un-sendable placeholder",
       "NO MAILING ADDRESS" in no_addr)
    ck("missing_to_send names the address gap",
       any("address" in g for g in er.missing_to_send({"name": "New Co"})))
    ck("a complete theme has nothing blocking a send",
       er.missing_to_send(EIEN) == [])

    print("\n— sections and the provider's own limits —")
    structured = er.render(EIEN, [
        {"type": "heading", "text": "The one-line headline", "level": 1},
        {"type": "text", "html": "<p>First idea.</p>"},
        {"type": "divider"},
        {"type": "heading", "text": "Second idea"},
        {"type": "text", "html": "<p>More.</p>"}])
    ck("headings render, at two weights",
       "The one-line headline" in structured and "Second idea" in structured
       and "font-size:24px" in structured and "font-size:17px" in structured)
    no_view = er.render(EIEN, BLOCKS, webview=False)
    ck("webview=False drops the view-in-browser link AND its token — "
       "Omnisend has no variable to fill it",
       "View in browser" not in no_view and "{{VIEW_IN_BROWSER}}" not in no_view)
    ck("…while the default keeps it for providers that have one",
       "View in browser" in er.render(EIEN, BLOCKS))

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
