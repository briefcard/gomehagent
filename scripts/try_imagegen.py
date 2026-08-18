"""Run the real thing: a Baci product, a described scene, a generated frame.

    OPENAI_API_KEY=sk-... python3 scripts/try_imagegen.py

Optional:
    --product URL     any product image with a transparent background
    --prompt  "..."   the scene to build around it
    --inspo   "..."   the look you are after, in words
    --shape   square|portrait|landscape
    --n       how many candidates
    --out     where to write them (default: ./imagegen_out)

Writes every candidate plus the base frame and the mask that was sent, so a
disappointing result can be diagnosed rather than guessed at — nine times in
ten the mask is the answer.
"""
import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_PRODUCT = ("https://cdn.shopify.com/s/files/1/0769/1993/1192/files/"
                   "APIT1_AQ02.png?v=1751564537")
DEFAULT_PROMPT = (
    "A sunlit Mediterranean table: pale linen cloth, a folded napkin, a bowl "
    "of lemons further back, dappled daylight through leaves, soft shadows "
    "falling to the right. Editorial food-photography styling, warm natural "
    "light, shallow depth of field.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default=DEFAULT_PRODUCT)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--inspo", default="linen, lemons, unfussy, lots of light")
    ap.add_argument("--shape", default="square")
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--out", default="imagegen_out")
    a = ap.parse_args()

    from app import config, imagegen
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY first — the same key embed.py uses.")
        return 2
    config.OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

    import httpx
    print(f"fetching {a.product[:70]}…")
    r = httpx.get(a.product, timeout=60, follow_redirects=True)
    r.raise_for_status()
    product = r.content

    from PIL import Image
    # Convert BEFORE testing. Shopify serves these as mode "P" with a
    # transparency palette, and checking `mode != "RGBA"` called a perfectly
    # good cutout unusable — a false warning about a correct input is worse
    # than none, because it sends you off fixing something that is not wrong.
    alpha = Image.open(io.BytesIO(product)).convert("RGBA").getchannel("A")
    lo, hi = alpha.getextrema()
    if lo == hi:
        print("WARNING: that image has no transparency — every pixel is "
              f"alpha {lo}. The mask will protect a rectangle and the result "
              "will look pasted. Use a cutout.")
    else:
        print("product has a real alpha channel — good, the mask will follow "
              "its silhouette")

    os.makedirs(a.out, exist_ok=True)
    w, h = (int(v) for v in imagegen.SIZES[a.shape].split("x"))
    base, mask = imagegen._protect_mask(product, (w, h))
    open(f"{a.out}/_base.png", "wb").write(base)
    open(f"{a.out}/_mask.png", "wb").write(mask)
    print(f"wrote {a.out}/_base.png and _mask.png — check these first if the "
          f"result disappoints")

    print(f"generating {a.n} candidate(s) at {imagegen.SIZES[a.shape]}…")
    res = imagegen.place_product(product, a.prompt, shape=a.shape, n=a.n,
                                 inspiration=a.inspo)
    if not res["ok"]:
        print("FAILED:", res.get("error", ""))
        return 1

    for i, c in enumerate(res["candidates"], 1):
        p = f"{a.out}/candidate_{i}.png"
        open(p, "wb").write(c["image"])
        print(f"  {p}   similarity {c['similarity']}")
    print("\n" + res["note"])
    print(res["caveat"])
    print("\nThe similarity number is a diagnostic, not a verdict — the mask is "
          "what keeps the product. Judge the pictures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
