"""The ban list reaches the fields the violations are actually in.

Baci's 2026-08 audit found ~110 banned-claim violations store-wide, and 96 of
them were a single "Hand-decorated" SEO-meta template. Two separate reasons
neither the scan nor the write guard could have caught them:

  · THE PHRASE WAS NOT ON THE LIST. `kb_seed` seeded 25 phrases covering
    handmade, hand-crafted and hand-painted — and not hand-decorated, the one
    actually on the store. Twenty-one test scripts used "hand-decorated" as
    their canonical example, so the machinery was proven end to end on a
    phrase production never enforced. That is this codebase's own standing
    audit — name the generator AND the validator — failing on its own rule.

  · THE SCAN COULD NOT SEE THE FIELD. `_clean` narrows to <main> and then
    strips every tag with `_HTML`, which deletes attributes. So the page
    title, the meta description and every `alt` were gone before a phrase was
    matched, and `content_compliance` could report "No banned claim found"
    about a store with 110 known findings. Reproduced before the fix: the
    identical phrase scores clean in a meta description and scores a hit in a
    paragraph.

And the write side had the same hole from the other end: `seo_guard` gated
seven prose fields and not the alt text it publishes beside them.

    python3 scripts/test_the_ban_list_reaches_the_fields.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'bl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import compliance, db, kb, kb_seed, seo_guard, tenants  # noqa: E402

_fail: list[str] = []

PAGE = """<html><head>
<title>Hand-decorated Aqua Dinner Plate</title>
<meta name="description" content="Hand-decorated melamine, Italian design.">
<meta property="og:description" content="A hand-painted finish.">
</head><body><main>
<img src="a.jpg" alt="A hand-decorated plate on linen">
<p>Dishwasher safe melamine in six colours.</p>
</main></body></html>"""


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— the phrase that was actually on the store is on the list —")
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "kb_seed.py")).read()
    ck("`hand-decorated` is seeded", '"hand-decorated"' in src,
       "96 of ~110 real violations were this one phrase")
    ck("  and so are the variants it travels with",
       all(f'"{p}"' in src for p in ("hand decorated", "hand-finished")), "")
    ck("  the ones that were already there are untouched",
       all(f'"{p}"' in src for p in ("handmade", "hand-painted", "artisanal")))

    print("\n— and the scan can see where it lives —")
    for p in ("hand-decorated", "hand-painted"):
        kb.add_banned("baci", p)
    res = compliance.check_page("baci", "https://x/p", html=PAGE)
    where = {h.get("where") for h in res["phrases"]}
    ck("the scan runs clean-status but NOT clean", res["status"] == "ok"
       and len(res["phrases"]) >= 3, str(len(res["phrases"])))
    ck("  the meta description is read", "meta description" in where, str(where))
    ck("  the page title is read", "page title" in where, str(where))
    ck("  the image alt text is read", "image alt text" in where, str(where))
    ck("every finding says WHICH FIELD to go and fix",
       all(h.get("where") or h.get("context") for h in res["phrases"]),
       "'on this page' is not actionable when the words are not on the page")

    print("\n— the body path is unchanged, not replaced —")
    body_only = ("<html><head><title>Plate</title></head><body><main>"
                 "<p>Hand-decorated. Melamine.</p></main></body></html>")
    r2 = compliance.check_page("baci", "https://x/q", html=body_only)
    ck("a phrase in the prose is still found", len(r2["phrases"]) == 1,
       str(r2["phrases"]))
    ck("  and carries no field label, because it is on the page",
       not r2["phrases"][0].get("where"), str(r2["phrases"][0]))
    clean = ("<html><head><title>Plate</title>"
             '<meta name="description" content="Melamine, six colours."></head>'
             "<body><main><p>Dishwasher safe.</p></main></body></html>")
    ck("a page with nothing banned in any field is still clean",
       compliance.check_page("baci", "https://x/r", html=clean)["phrases"] == [],
       "a checker that flags everything stops being read")

    print("\n— and the write side gates the alt it publishes —")
    profile = {"platform": "shopify", "site": "https://bacimilanousa.com"}
    seo_guard.tenant_for = lambda p: "baci"
    ok_fields = {"title": "Aqua Plate", "body_html": "<p>Melamine.</p>",
                 "image": {"src": "https://x/a.png", "alt": "A plate on linen"}}
    bad_fields = dict(ok_fields, image={"src": "https://x/a.png",
                                        "alt": "A hand-decorated plate"})
    ck("a clean payload still publishes",
       not seo_guard.check(profile, ok_fields, what="new post"), "")
    refusal = seo_guard.check(profile, bad_fields, what="new post")
    ck("a banned claim in the ALT is refused",
       bool(refusal) and "hand-decorated" in refusal.lower(), str(refusal)[:100])
    ck("  which is the field that shipped unchecked beside six that did not",
       ("image", "alt") in seo_guard.NESTED_PROSE, str(seo_guard.NESTED_PROSE))

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
