"""WHAT THE OWNER APPROVED IS THE STANDARD, AND WHAT THEY SAID IS REMEMBERED.

Phase 4 of INITIATIVE-blog-quality, and the same seam for the email
(INITIATIVE-email-recreation §7). Two things, one home, both brand-scoped:

  - THE EXEMPLAR: the last artifact of a kind the owner approved. The maker
    is shown it beside the hand-made standard, so the bar rises with the
    brand's own best work instead of staying at whatever was written into a
    prompt in September.
  - THE NOTES: what the owner has said about this brand's emails or articles,
    in their own words, kept as a short list and shown to the maker and the
    judge. Taste enters here, never as a rule of ours (owner, 2026-09-17:
    *"I don't want to hard-code any constraints"*).

Both live on `KbBrand.visual`, the column the boards, the standing email
design and the article pattern already use — one place a brand's own
decisions accumulate, not four.
"""
from __future__ import annotations

from . import db

#: How many of the owner's notes ride with a make. Enough to carry a standing
#: instruction and a recent correction; not enough to become a rulebook.
NOTES_SHOWN = 6
#: The kinds. An email and an article learn apart: a good email is not a
#: model for an article.
EMAIL, ARTICLE = "email", "article"
_FIELD = "exemplars"


def _visual(tenant: str) -> dict:
    from . import kb
    b = kb.ensure_brand(tenant, tenant)
    return dict(getattr(b, "visual", None) or {})


def _write(tenant: str, got: dict) -> None:
    from . import kb
    visual = _visual(tenant)
    visual[_FIELD] = got
    kb.set_brand(tenant, visual=visual)


def _all(tenant: str) -> dict:
    got = _visual(tenant).get(_FIELD) or {}
    return got if isinstance(got, dict) else {}


# ---------------------------------------------------------------------------
# THE EXEMPLAR
# ---------------------------------------------------------------------------

def approved(tenant: str, kind: str) -> dict:
    """The last thing of this kind the owner approved for this brand:
    `{html, title, at, output_id, why}` or `{}`."""
    got = (_all(tenant).get(kind) or {}).get("exemplar") or {}
    return got if isinstance(got, dict) else {}


def file_approved(tenant: str, kind: str, *, html: str, title: str = "", output_id: str = "", why: str = "") -> str:
    """Remember this approved artifact as the brand's exemplar of its kind.
    The one writer. Called where an approval is executed, not where it is
    proposed: a thing the owner did not approve is not a standard."""
    if not (html or "").strip():
        return "nothing to file"
    got = _all(tenant)
    kind_ = dict(got.get(kind) or {})
    kind_["exemplar"] = {"html": html[:60000], "title": title[:200], "output_id": output_id,
                         "at": db.utcnow().isoformat(), "why": why[:300]}
    got[kind] = kind_
    _write(tenant, got)
    return ""


def standard(tenant: str, kind: str, *, fallback: str = "") -> tuple[str, str]:
    """What the maker is shown as the standard of craft: the brand's last
    approved piece when there is one, else the hand-made exemplar shipped
    with the code. Returns `(html, said)` — `said` names which it is, so a
    run's story can say whose standard it was held to."""
    got = approved(tenant, kind)
    if got.get("html"):
        when = str(got.get("at") or "")[:10]
        return got["html"], f"the last {kind} you approved" + (f" ({got['title']}, {when})" if got.get("title") else "")
    return fallback, "the hand-made standard"


# ---------------------------------------------------------------------------
# THE NOTES
# ---------------------------------------------------------------------------

def notes(tenant: str, kind: str, *, limit: int = NOTES_SHOWN) -> list[dict]:
    """What the owner has said about this brand's work of this kind, newest
    first: `[{said, at, output_id}]`."""
    rows = (_all(tenant).get(kind) or {}).get("notes") or []
    return [r for r in rows if isinstance(r, dict)][:limit]


def remember(tenant: str, kind: str, said: str, *, output_id: str = "", by: str = "owner") -> str:
    """Keep what the owner said. The note reaches every later make of this
    kind for this brand — which is what "the AI learns" means here: their
    words, not a rule we inferred from them."""
    said = " ".join(str(said or "").split())[:600]
    if not said:
        return "nothing said"
    got = _all(tenant)
    kind_ = dict(got.get(kind) or {})
    rows = [r for r in (kind_.get("notes") or []) if isinstance(r, dict) and r.get("said") != said]
    rows.insert(0, {"said": said, "at": db.utcnow().isoformat(), "output_id": output_id, "by": by})
    kind_["notes"] = rows[:30]
    got[kind] = kind_
    _write(tenant, got)
    return ""


def forget(tenant: str, kind: str, said: str) -> str:
    """Drop a note the owner no longer means. Kept honest: a standing
    instruction that cannot be withdrawn is a rule, which is the thing this
    module exists not to be."""
    got = _all(tenant)
    kind_ = dict(got.get(kind) or {})
    before = len(kind_.get("notes") or [])
    kind_["notes"] = [r for r in (kind_.get("notes") or []) if isinstance(r, dict) and r.get("said") != said]
    got[kind] = kind_
    _write(tenant, got)
    return "" if len(kind_["notes"]) < before else "no note said that"


def notes_text(tenant: str, kind: str) -> str:
    """The notes as the makers and the judge see them — the owner's words,
    marked as theirs and as outranking the brief."""
    rows = notes(tenant, kind)
    if not rows:
        return ""
    return ("WHAT THE OWNER HAS SAID about this brand's " + kind + "s — their words, and they outrank "
            "the brief, the reference and the angle:\n"
            + "\n".join(f"- {r.get('said', '')}" for r in rows) + "\n")
