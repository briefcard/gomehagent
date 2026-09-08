"""A blind bake-off of image models on ONE product, for the owner's eyes.

Owner, 2026-09-07: *"the photos are better but they are still not recreating
the product photos exactly."* Exact reproduction of a specific object is a
PROVIDER capability: if the model cannot, no prompt will. So the same product,
the same brief and the same board go through each model named here, the sets
land under Pictures with only a number on them, the owner keeps and rejects
without knowing which is which, and `--reveal` says afterwards.

Two doors: a plain model name goes to the configured image API
(IMAGE_API_BASE — OpenAI-compatible); a `gemini:<model>` name goes to Google's
image models through `app/gemini_images.py` (GEMINI_API_KEY required — the
docs read 2026-09-08 say Nano Banana Pro takes up to six object references
"with high fidelity"). Both get the same words and the same pictures.
  python3 scripts/bakeoff.py --tenant baci --entity zodiac-cup \\
      --models gpt-image-1,gemini:gemini-3-pro-image,gemini:gemini-3.1-flash-image --plates 2
  python3 scripts/bakeoff.py --tenant baci --reveal
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import coherence, creative, db, kb  # noqa: E402

KEY = "bakeoff"


def run(tenant: str, entity: str, models: list[str], plates: int,
        positioning: str, boards: list[str]) -> int:
    row = next((e for e in kb.entities(tenant, available_only=False) if e.key == entity), None)
    if row is None:
        print(f"no entity {entity!r} for {tenant}")
        return 1
    order = list(models)
    random.shuffle(order)                       # the number says nothing about the model
    mapping = {}
    commitment = coherence.commit("entity", entity, label=row.name or entity)
    for n, model in enumerate(order, 1):
        got = creative.batch(tenant, commitment=commitment, entity_key=entity,
                             fmt="ad_frame", positioning=positioning, plates=plates,
                             review=True, boards=tuple(boards), image_model=model)
        mapping[str(n)] = {"model": model, "batch": got.get("batch", ""),
                           "made": got.get("made", 0), "fidelity": got.get("fidelity", {}),
                           "errors": got.get("errors", [])}
        print(f"set {n}: {got.get('made', 0)} frame(s) — {got.get('note', '')[:160]}")
        if got.get("errors"):
            print("   errors:", "; ".join(str(e)[:120] for e in got["errors"][:3]))
    with db.SessionLocal() as s:
        s.merge(db.Setting(key=f"{KEY}:{tenant}", value=json.dumps(mapping)))
        s.commit()
    print(f"\n{len(order)} set(s) are under Pictures for {tenant}, numbered only. "
          f"Keep the frames that are the product; then:\n"
          f"  python3 scripts/bakeoff.py --tenant {tenant} --reveal")
    return 0


def reveal(tenant: str) -> int:
    with db.SessionLocal() as s:
        row = s.get(db.Setting, f"{KEY}:{tenant}")
    if row is None or not row.value:
        print(f"no bake-off on file for {tenant}")
        return 1
    mapping = json.loads(row.value)
    rows = kb.assets(tenant, publishable_only=False)
    for n, m in sorted(mapping.items()):
        frames = [a for a in rows if (a.batch or "") == m.get("batch")]
        kept = [a for a in frames if (a.review or "") == "approved"]
        rejected = [a for a in frames if a.status != "active"]
        fid = m.get("fidelity") or {}
        print(f"set {n}: {m['model']} — {len(frames)} filed, {len(kept)} kept, "
              f"{len(rejected)} rejected; judge: {fid.get('judged', 0)} judged, "
              f"{fid.get('kept', 0)} kept, {fid.get('redrafted', 0)} redrawn")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--entity", default="")
    ap.add_argument("--models", default="gpt-image-1,gpt-image-1-mini")
    ap.add_argument("--plates", type=int, default=2)
    ap.add_argument("--positioning", default="")
    ap.add_argument("--boards", default="")
    ap.add_argument("--reveal", action="store_true")
    a = ap.parse_args()
    if a.reveal:
        return reveal(a.tenant)
    if not a.entity:
        print("--entity is required to run a bake-off")
        return 1
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    boards = [b.strip() for b in a.boards.split(",") if b.strip()]
    return run(a.tenant, a.entity, models, a.plates, a.positioning, boards)


if __name__ == "__main__":
    raise SystemExit(main())
