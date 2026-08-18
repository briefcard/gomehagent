"""The creative library: what may be published, and what actually worked.

Two kinds of thing share one table and one shape — assets the client owns, and
a competitor's ad saved because it is worth looking at. Nothing about the row
distinguishes them except `rights`, so every check here is about `rights` being
a gate rather than a label, plus the two feedback signals that make a library
worth keeping at all.

Run: python3 scripts/test_assets.py
"""
import os
import sys
import tempfile

_tmp = os.path.join(tempfile.mkdtemp(), "assets.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ["APPROVAL_SECRET"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, ledger, tenants  # noqa: E402

_fails: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— rights is a gate, not a label —")
    said = kb.add_asset("baci", "https://cdn.example/plate.jpg", rights="owned",
                        title="Aqua plate on white", tags=["on-white"])
    ck("an owned asset is filed", "owned" in said.lower(), said[:70])
    ref = kb.add_asset("baci", "https://competitor.example/their-ad.jpg",
                       rights="reference", title="Competitor autumn ad",
                       source="competitor: Villeroy", tags=["lifestyle"])
    ck("a reference asset is filed, and says what it is",
       "never be published" in ref, ref[:90])

    bad = kb.add_asset("baci", "https://cdn.example/unknown.jpg", rights="")
    ck("REFUSES when rights is not stated — there is no safe guess",
       "no default" in bad, bad[:90])
    ck("  and nothing was written",
       len(kb.assets("baci", publishable_only=False)) == 2,
       str(len(kb.assets("baci", publishable_only=False))))

    pub = kb.assets("baci")
    ck("the default read returns only what may be published",
       len(pub) == 1 and "plate" in (pub[0].title or "").lower(),
       str([a.title for a in pub]))
    ck("  the inspiration shelf has to be asked for by name",
       len(kb.assets("baci", publishable_only=False)) == 2)

    owned_id = pub[0].id
    ref_id = [a for a in kb.assets("baci", publishable_only=False)
              if a.id != owned_id][0].id
    ck("an owned asset may publish", kb.may_publish(owned_id)[0])
    ok, why = kb.may_publish(ref_id)
    ck("A REFERENCE ASSET MAY NOT, and says why", not ok and "reference" in why,
       why[:80])

    # The migration case: a row that predates the column, or a typo.
    with db.SessionLocal() as s:
        row = s.get(db.KbAsset, owned_id)
        row.rights = None
        s.commit()
    ck("a NULL rights reads as NOT publishable — absence lands safe",
       not kb.may_publish(owned_id)[0])
    ck("  and it disappears from the publishable list too",
       len(kb.assets("baci")) == 0, str(len(kb.assets("baci"))))
    with db.SessionLocal() as s:
        row = s.get(db.KbAsset, owned_id)
        row.rights = kb.OWNED
        s.commit()

    print("\n— publishing is the usage signal —")
    out = ledger.record("baci", "ad_creative", body="An ad.", format="ad_copy",
                        media_ids=[owned_id])
    ck("publishing credits the asset behind it",
       "credited" in ledger.publish("baci", out.id, "meta"))
    with db.SessionLocal() as s:
        ck("  the use is counted on the asset",
           s.get(db.KbAsset, owned_id).uses == "1",
           s.get(db.KbAsset, owned_id).uses)
        ck("  with a timestamp, so recency is answerable",
           s.get(db.KbAsset, owned_id).last_used_at is not None)

    blocked = ledger.record("baci", "ad_creative", body="Another ad.",
                            format="ad_copy", media_ids=[ref_id])
    res = ledger.publish("baci", blocked.id, "meta")
    ck("PUBLISHING IS REFUSED when a reference asset is attached",
       res.startswith("Not published"), res[:80])
    with db.SessionLocal() as s:
        ck("  and the output was not marked published",
           s.get(db.Output, blocked.id).status != "published",
           s.get(db.Output, blocked.id).status)
        ck("  nor was the reference asset credited with a use",
           s.get(db.KbAsset, ref_id).uses == "0",
           s.get(db.KbAsset, ref_id).uses)

    print("\n— results are the second signal —")
    kb.record_asset_outcome(owned_id, "meta", {"roas": 2.4, "spend": 300})
    kb.record_asset_outcome(owned_id, "email", {"ctr": 0.9})
    with db.SessionLocal() as s:
        oc = s.get(db.KbAsset, owned_id).outcome or {}
    ck("outcomes are kept per channel, not averaged into one number",
       set(oc) == {"meta", "email"}, str(sorted(oc)))
    ck("  a channel keeps its own metrics", oc["meta"]["roas"] == 2.4)

    kb.add_asset("baci", "https://cdn.example/second.jpg", rights="owned",
                 title="Second")
    second = [a for a in kb.assets("baci") if a.title == "Second"][0]
    ledger.publish("baci", ledger.record("baci", "ad_creative", body="x",
                                         media_ids=[second.id]).id, "meta")
    kb.record_asset_outcome(second.id, "meta", {"roas": 0.4})
    ranked = kb.proven_assets("baci", channel="meta", metric="roas")
    ck("what worked can be ranked ahead of what did not",
       ranked and ranked[0].id == owned_id,
       str([(a.title, (a.outcome or {}).get("meta")) for a in ranked]))
    ck("  and an unused asset is not in that list at all",
       all(int(a.uses or "0") > 0 for a in ranked))

    print("\n— pictures off the client's own website —")
    from app import harvest as hv
    html = ("<html><head>"
            "<meta property=\"og:image\" content=\"/img/hero.jpg\">"
            "</head><body>"
            "<img src=\"https://cdn.x.com/venue/hall.jpg\" alt=\"Main hall\">"
            "<img data-src=\"/gallery/terrace.jpg\" alt=\"Terrace\">"
            "<img src=\"/icons/facebook.svg\" alt=\"fb\">"
            "<img src=\"/payment-badge.png\" alt=\"visa\">"
            "<img src=\"/img/spacer.gif\">"
            "<img src=\"/assets/logo-white.png\" alt=\"logo\">"
            "</body></html>")
    got = hv._images(html, "https://miamiironside.com/spaces")
    urls = [u for u, _, _ in got]
    ck("the page's declared og:image is taken first",
       urls and urls[0].endswith("/img/hero.jpg"), str(urls[:1]))
    ck("  relative paths are made absolute against the page",
       all(u.startswith("http") for u in urls), str(urls))
    ck("  LAZY-LOADED images are found — reading only src collects placeholders",
       any("terrace" in u for u in urls), str(urls))
    # Logos are no longer in this list: they are kept and labelled, not
    # dropped. Only genuine chrome is discarded.
    ck("  icons, payment badges and spacers are left behind",
       not any(bit in " ".join(urls).lower()
               for bit in ("facebook", "payment", "spacer")),
       str(urls))
    # The real Ironside markup, which the first filter let straight through:
    # its files are `Logo.png` and `IRONSIDE+WHITE+LOGO.png`, and the skip list
    # said "logo-" with a hyphen.
    ironside = ('<html><head><meta property="og:image" '
                'content="/t/5fb/Logo.png?format=1500w"></head><body>'
                '<img src="/v1/540/1606/Logo.png?format=1500w" alt="MIAMI IRONSIDE">'
                '<img src="/v1/540/d266/Ironside+Walls.webp" alt="Walls">'
                '<img src="/v1/540/1781/cmd-56.jpg" alt="Community">'
                '<img src="/540/c14a/IRONSIDE+WHITE+LOGO.png" alt="Miami Ironside">'
                '<img src="/v1/540/1781/cmd-56.jpg?format=300w" alt="Community small">'
                "</body></html>")
    ir = hv._images(ironside, "https://www.miamiironside.com/home")
    ir_urls = [u for u, _, _ in ir]
    # Logos are KEPT and labelled rather than dropped: a creative that needs
    # the mark needs THE mark, and mixing them into the photography buries
    # both. The real filenames were Logo.png and IRONSIDE+WHITE+LOGO.png.
    kinds = {u.rsplit("/", 1)[-1][:14]: k for u, _, k in ir}
    ck("  A LOGO IS A DIFFERENT KIND, not junk — it is kept and labelled",
       all(k == "logo" for f, k in kinds.items() if "ogo" in f.lower())
       and any(k == "logo" for k in kinds.values()), str(kinds))
    ck("  and the photographs are not labelled as logos",
       any(k == "photo" for k in kinds.values()), str(kinds))
    ck("  one picture at two sizes is one picture, not two review rows",
       len([u for u in ir_urls if "cmd-56" in u]) == 1, str(ir_urls))
    photos = [u for u, _, k in ir if k == "photo"]
    ck("  and the actual photographs survive", len(photos) == 2, str(photos))

    print("\n— approving pictures —")
    kb.add_asset("ironside", "https://cdn/hall.jpg", rights=kb.OWNED,
                 kind="image", title="Main hall", origin="crawl")
    kb.add_asset("ironside", "https://cdn/LOGO.png", rights=kb.OWNED,
                 kind="image", title="logo", subject=kb.LOGO, origin="crawl")
    ck("crawled pictures land in a queue", len(kb.proposed_assets("ironside")) == 2)
    ck("  and none of them is publishable yet", len(kb.assets("ironside")) == 0)
    ok, why = kb.may_publish(kb.proposed_assets("ironside")[0].id)
    ck("  may_publish says WHY, not just no", not ok and "review" in why, why[:60])
    hall = [a for a in kb.proposed_assets("ironside") if a.title == "Main hall"][0]
    kb.review_asset(hall.id, approve=True)
    ck("approving one makes it usable", len(kb.assets("ironside")) == 1)
    ck("  LOGOS ARE TRACKED APART from the photography — a creative needing "
       "the mark needs the mark, not whichever building sorted first",
       [a.title for a in kb.logos("ironside")] == ["logo"],
       str([a.title for a in kb.logos("ironside")]))
    rej = [a for a in kb.proposed_assets("ironside")][0]
    kb.review_asset(rej.id, approve=False)
    ck("rejecting RETIRES rather than deletes, so the next crawl does not "
       "re-offer it", len(kb.proposed_assets("ironside")) == 0)
    ck("  alt text is kept, because it is the only caption a crawl ever gets",
       any(a == "Main hall" for _, a, _ in got),
       str([a for _, a, _ in got]))

    kb.add_asset("baci", "https://cdn.x.com/venue/hall.jpg", rights=kb.OWNED,
                 kind="image", title="Main hall", source="crawled",
                 origin="crawl")
    crawled = [a for a in kb.assets("baci", publishable_only=False)
               if a.title == "Main hall"]
    ck("a crawled picture is filed", len(crawled) == 1)
    ck("  BUT IT IS NOT PUBLISHABLE UNTIL APPROVED — a photograph on a "
       "client's website is a candidate, not a licence",
       not any(a.title == "Main hall" for a in kb.assets("baci")),
       "plenty of sites carry stock licensed for the web and nothing else")

    print("\n— the brand's visual half —")
    kb.set_brand("baci", visual={"direction": "Styled on a laid table.",
                                 "do_show": ["the piece in use"],
                                 "never_show": ["faces", "props we do not sell"]})
    v = (kb.brand("baci").visual or {})
    ck("art direction is on the brand row, next to voice",
       v.get("never_show") == ["faces", "props we do not sell"], str(v)[:90])

    print()
    if _fails:
        print(f"{len(_fails)} FAILED:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print("all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
