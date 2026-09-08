"""Google's image models, as a second door for the same request.

Owner, 2026-09-08: *"These days, there must be a way to create this without
hallucinations."* Exact reproduction of a specific object is a PROVIDER
capability — `scripts/bakeoff.py` says so, and it could only compare models
on the one OpenAI-compatible endpoint. This module is the adapter that
script said a different provider would need.

THE CONTRACT, read from Google's docs on 2026-09-08
(https://ai.google.dev/gemini-api/docs/image-generation):
  POST {GEMINI_API_BASE}/interactions        header  x-goog-api-key: <key>
  {"model": "<model>",
   "input": [{"type": "text", "text": "…"},
             {"type": "image", "mime_type": "image/png", "data": "<base64>"}, …],
   "response_format": {"type": "image", "mime_type": "image/png",
                       "aspect_ratio": "1:1", "image_size": "1K"}}
  The reply's last image block is the picture (the SDK's `output_image`);
  REST is read by walking the JSON for {"type": "image", "data": …}.
Models: gemini-3.1-flash-image (Nano Banana 2 — "excelling at multiple
reference image processing and consistency", up to 10 object references),
gemini-3-pro-image (Nano Banana Pro — "accurate brand consistency", up to 6
object references with high fidelity, up to 3 style references),
gemini-3.1-flash-lite-image (up to 14 objects, "not optimized for multiple
reference inputs"), gemini-2.5-flash-image (legacy, best with ≤ 3 inputs).

WHAT THIS DOES NOT DO. It does not pick a winner: the same product, brief
and board go through each model and the owner ranks the sets blind. It
does not change the rules — the prompt that rides here is the one
`imagegen.with_references` builds, word for word.
"""
from __future__ import annotations

import base64

from . import config

DOC = "https://ai.google.dev/gemini-api/docs/image-generation"
PREFIX = "gemini:"
TIMEOUT = 180
DEFAULT_MODEL = "gemini-3-pro-image"

#: How many OBJECT references each model takes "with high fidelity", per the
#: docs' table, and how many style references. The product and its
#: companions are objects; the look pins are style.
LIMITS = {
    "gemini-3-pro-image": {"objects": 6, "style": 3},
    "gemini-3.1-flash-image": {"objects": 10, "style": 3},
    "gemini-3.1-flash-lite-image": {"objects": 14, "style": 0},
    "gemini-2.5-flash-image": {"objects": 3, "style": 0},
}

#: `imagegen.SIZES` shapes as the aspect ratios the API takes.
ASPECT = {"square": "1:1", "landscape": "3:2", "portrait": "2:3"}


def is_gemini(model: str) -> bool:
    return str(model or "").startswith(PREFIX)


def model_name(model: str) -> str:
    return str(model or "")[len(PREFIX):] if is_gemini(model) else str(model or "")


def limits(model: str) -> dict:
    return dict(LIMITS.get(model_name(model)) or {"objects": 6, "style": 3})


def _key() -> tuple[str, str]:
    if not config.GEMINI_API_KEY:
        return "", ("GEMINI_API_KEY is not set — a Google AI Studio key, added to the "
                    "environment; until then `gemini:` models cannot be compared")
    return config.GEMINI_API_KEY, ""


def _post(url: str, *, headers: dict, json_body: dict):
    """One HTTPS call. A seam: the suite hands responses in."""
    import httpx
    return httpx.post(url, timeout=TIMEOUT, headers=headers, json=json_body)


post = _post


def image_blocks(payload) -> list:
    """Every image block in a reply, in order, wherever the API put it —
    `{"type": "image", "data": …}` blocks (the Interactions shape), and the
    older `inline_data`/`inlineData` shape, so a shape change is a missed
    picture and not a crash. The last one is the generated picture."""
    out: list = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "image" and isinstance(node.get("data"), str) and node["data"]:
                out.append(node)
            for k in ("inline_data", "inlineData"):
                v = node.get(k)
                if isinstance(v, dict) and isinstance(v.get("data"), str) and v["data"] \
                        and str(v.get("mime_type") or v.get("mimeType") or "").startswith("image/"):
                    out.append({"type": "image", "mime_type": v.get("mime_type") or v.get("mimeType"),
                                "data": v["data"]})
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(payload)
    return out


def edit(prompt: str, *, images: list, model: str = "", shape: str = "square",
         n: int = 1, tenant: str = "") -> dict:
    """The same request `imagegen.with_references` makes, to Google.

    `images` is the ordered list of `(name, bytes, mime)` the OpenAI door
    takes — product first, then companions, then the look — capped to the
    model's documented reference limits here. One picture per call; `n`
    calls. `{ok, images: [bytes], error, model}`."""
    import time as _clock
    from . import toolcalls as _tc
    name = model_name(model) or DEFAULT_MODEL
    lim = limits(name)
    key, why = _key()
    if why:
        _tc.record(tenant, "images:interactions", source="creative", provider="gemini_images",
                   ok=False, error=why)
        return {"ok": False, "error": why, "model": name}
    objects = [i for i in images if not str(i[0]).startswith("look-")][:lim["objects"]]
    style = [i for i in images if str(i[0]).startswith("look-")][:lim["style"]]
    blocks = [{"type": "text", "text": prompt}]
    for _name, blob, mime in objects + style:
        blocks.append({"type": "image", "mime_type": mime or "image/png",
                       "data": base64.b64encode(blob).decode()})
    body = {"model": name, "input": blocks,
            "response_format": {"type": "image", "mime_type": "image/png",
                                "aspect_ratio": ASPECT.get(shape, "1:1"),
                                "image_size": "1K"}}
    url = f"{config.GEMINI_API_BASE.rstrip('/')}/interactions"
    out: list = []
    for _ in range(max(1, min(4, int(n or 1)))):
        started = _clock.monotonic()
        try:
            r = post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                     json_body=body)
        except Exception as exc:                                 # noqa: BLE001
            err = f"{exc.__class__.__name__}: {str(exc)[:160]}"
            _tc.record(tenant, "images:interactions", source="creative", provider="gemini_images",
                       ok=False, error=err, ms=int((_clock.monotonic() - started) * 1000))
            return {"ok": False, "error": err, "model": name, "images": out}
        status = int(getattr(r, "status_code", 0) or 0)
        try:
            payload = r.json()
        except Exception:                                        # noqa: BLE001
            payload = {}
        if status >= 400:
            msg = ""
            if isinstance(payload, dict):
                e = payload.get("error")
                msg = (e.get("message") if isinstance(e, dict) else str(e or "")) or ""
            err = f"{status}: {msg or str(getattr(r, 'text', ''))[:200]}"[:300]
            _tc.record(tenant, "images:interactions", source="creative", provider="gemini_images",
                       ok=False, error=err, ms=int((_clock.monotonic() - started) * 1000))
            return {"ok": False, "error": err, "model": name, "images": out}
        found = image_blocks(payload)
        if not found:
            keys = ", ".join(sorted(payload.keys())[:8]) if isinstance(payload, dict) else type(payload).__name__
            err = f"the reply carried no image block (top-level keys: {keys})"
            _tc.record(tenant, "images:interactions", source="creative", provider="gemini_images",
                       ok=False, error=err, ms=int((_clock.monotonic() - started) * 1000))
            return {"ok": False, "error": err, "model": name, "images": out}
        try:
            out.append(base64.b64decode(found[-1]["data"]))
        except Exception:                                        # noqa: BLE001
            return {"ok": False, "error": "the image block did not decode", "model": name,
                    "images": out}
        # THE SHAPE, RECORDED ONCE PER CALL: the docs describe the SDK's view
        # of the reply; the raw keys ride the ledger so the first live call
        # says what the API actually returned.
        _tc.record(tenant, "images:interactions", source="creative", provider="gemini_images",
                   ok=True, ms=int((_clock.monotonic() - started) * 1000),
                   bytes_back=len(out[-1]),
                   ref=("keys: " + ", ".join(sorted(payload.keys())[:8])) if isinstance(payload, dict) else "")
    try:
        from . import usage
        usage.log_image("image_edit" if images else "image_generate", name, len(out))
    except Exception:                                            # noqa: BLE001
        pass
    return {"ok": True, "images": out, "model": name}
