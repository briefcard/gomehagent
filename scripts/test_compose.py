"""Composing a creative that actually contains the product.

Canva's generator treats a supplied asset as inspiration — tested against
Baci's own catalogue it produced four ads with four invented pitchers. This
places the product by drawing it, so there is nothing to verify afterwards.

Run: python3 scripts/test_compose.py
"""
import io
import os
import sys
import tempfile

_tmp = os.path.join(tempfile.mkdtemp(), "compose.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ["APPROVAL_SECRET"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import compose, db, kb, tenants  # noqa: E402

_fails: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def _cutout(colour=(240, 240, 245, 255)):
    """A transparent-background product stand-in, like Baci's real ones."""
    im = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    from PIL import ImageDraw
    ImageDraw.Draw(im).ellipse([150, 120, 450, 520], fill=colour)
    b = io.BytesIO()
    im.save(b, format="PNG")
    return b.getvalue()


def main() -> int:
    db.init_db()
    tenants.seed()

    # The fetch is the only network step; everything else is local pixels.
    png = _cutout()
    compose_fetch = {"data": png}

    import httpx

    class _R:
        content = png

        def raise_for_status(self):
            return None

    httpx.get = lambda *a, **k: _R()          # noqa: E731

    kb.add_asset("baci", "https://cdn/p.png", rights=kb.OWNED,
                 title="Pitcher", kind="image", origin="human")
    kb.add_asset("baci", "https://rival/ad.png", rights=kb.REFERENCE,
                 title="Rival ad", kind="image", origin="human")
    owned = [a for a in kb.assets("baci") if a.title == "Pitcher"][0].id
    ref = [a for a in kb.assets("baci", publishable_only=False)
           if a.title == "Rival ad"][0].id

    print("— rights are the gate here too —")
    r = compose.product_on_colour("baci", ref, headline="X")
    ck("A REFERENCE ASSET IS REFUSED — compositing a competitor's photograph "
       "into an ad is exactly what that axis exists to prevent",
       not r["ok"] and "reference" in r["error"], r.get("error", "")[:80])
    r = compose.product_on_colour("eien", owned, headline="X")
    ck("another account cannot composite this account's product",
       not r["ok"], r.get("error", "")[:60])
    ck("a missing asset is named, not guessed",
       not compose.product_on_colour("baci", "", headline="X")["ok"])

    print("\n— product on colour —")
    r = compose.product_on_colour(
        "baci", owned, headline="Shatterproof. Not fragile.",
        subline="Italian-designed acrylic.", background="#E8DFD2")
    ck("it renders", r["ok"], str(r)[:80])
    ck("  all three ad shapes, so nothing is re-cropped by hand",
       set(r["images"]) == {"1:1", "4:5", "9:16"}, str(sorted(r["images"])))
    for k, (w, h) in compose.SIZES.items():
        im = Image.open(io.BytesIO(r["images"][k]))
        ck(f"  {k} is exactly {w}×{h}", im.size == (w, h), str(im.size))
    ck("  the font used is REPORTED, so a silent substitution cannot pass as "
       "brand-correct", bool(r["font"]), r["font"])

    print("\n— product on a scene —")
    plate = Image.new("RGB", (1400, 900), (210, 196, 176))
    pb = io.BytesIO()
    plate.save(pb, format="PNG")
    r2 = compose.product_on_scene("baci", owned, pb.getvalue(),
                                  headline="Set the table.", formats=["1:1"])
    ck("it renders onto the plate", r2["ok"], str(r2)[:70])
    ck("  and refuses without one",
       not compose.product_on_scene("baci", owned, b"",
                                    headline="X")["ok"])

    flat = Image.open(io.BytesIO(
        compose.product_on_colour("baci", owned, headline="X",
                                  background="#D2C4B0",
                                  formats=["1:1"])["images"]["1:1"])).convert("RGB")
    scened = Image.open(io.BytesIO(r2["images"]["1:1"])).convert("RGB")
    # Under the product, a grounded composite is darker than an ungrounded one.
    W, H = scened.size
    box = (int(W * 0.42), int(H * 0.88), int(W * 0.58), int(H * 0.93))
    dark_scene = sum(sum(p) for p in scened.crop(box).getdata())
    dark_flat = sum(sum(p) for p in flat.crop(box).getdata())
    ck("THE PRODUCT IS GROUNDED — there is a contact shadow beneath it, which "
       "is most of the difference between composited and pasted",
       dark_scene < dark_flat, f"scene {dark_scene} vs flat {dark_flat}")

    print("\n— the plate is scaled, never squashed —")
    wide = Image.new("RGB", (2000, 600), (200, 190, 170))
    wb = io.BytesIO()
    wide.save(wb, format="PNG")
    r3 = compose.product_on_scene("baci", owned, wb.getvalue(),
                                  headline="X", formats=["9:16"])
    im = Image.open(io.BytesIO(r3["images"]["9:16"]))
    ck("a wide plate still fills a tall format at the right size",
       im.size == compose.SIZES["9:16"], str(im.size))

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
