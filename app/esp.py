"""One ESP, whichever one the client actually uses.

Some clients send through Omnisend, some Klaviyo, some Constant Contact. The
campaign generator must not know or care which. It produces ONE canonical email
— grounded, validated, ESP-agnostic HTML carrying *neutral* personalization
tokens like ``{{FIRST_NAME}}`` — and this layer renders that email native for
whichever ESP the client connected: Omnisend's merge syntax, Klaviyo's tags,
Constant Contact's contact fields, and (later) each provider's own dynamic
blocks.

That is the whole design the owner asked for: **clean generation once, native
adaptation per ESP.** Generation stays client-agnostic; "make it native" is a
transform applied at the very end, chosen by which ESP the client is on.

Same shape as ``sites.backend()`` one subsystem over, and for the same reason:
a per-tenant resolver returning a duck-typed adapter, so adding an ESP is a
profile row plus an adapter module — never a branch inside the generator.

**Two kinds of "native" and where each lives.**

* *Transport*-native — how a draft is created and sent — lives in the adapter
  modules (`omnisend.py`, `constant_contact.py`, a Klaviyo one to come). Those
  already exist and already refuse by name when a client has no connection.
* *Presentation*-native — the merge-tag syntax and the capability flags a
  generator needs to decide what it can even ask for — lives in ``PROFILES``
  here, one place, so the two ESPs cannot drift on what ``{{FIRST_NAME}}``
  becomes.

**Honesty, inherited.** None of the adapters has ever made a real call against a
live ESP (see each module's own note), so the native merge strings below are
best-effort from each provider's public docs and are marked to VERIFY on the
first real send. Getting one wrong shows up as a literal ``{{FIRST_NAME}}`` in a
customer's inbox, so `personalize` refuses an unknown token rather than shipping
it as text — a typo must not become a send.
"""
from __future__ import annotations

import re

from . import credentials as cred

# ---------------------------------------------------------------------------
# The neutral vocabulary a canonical email may use. The generator writes these;
# `personalize` translates them. Keeping the set closed is what lets a typo be
# caught: `{{FIRSTNAME}}` (no underscore) is not in here, so it is refused
# rather than sent as four literal words.
# ---------------------------------------------------------------------------
TOKENS = ("FIRST_NAME", "LAST_NAME", "EMAIL", "UNSUBSCRIBE", "VIEW_IN_BROWSER")

# Matches ANY `{{ ... }}` in a canonical email, not just well-formed tokens.
# A canonical email carries only the neutral TOKENS above, so anything else
# inside `{{ }}` is a typo — `{{FisrtName}}`, `{{ first name }}` — and must be
# caught rather than substituted-past and shipped. (Native provider syntax like
# Omnisend's `{{ contact.firstName }}` appears only AFTER this runs, never in
# its input.)
_TOKEN_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}", re.S)


# ---------------------------------------------------------------------------
# Presentation-native mapping, one entry per ESP. `merge` is keyed by the
# neutral TOKENS above; `caps` is what a generator asks before it composes.
#
# `adapter` names the transport module; `audience_fn`/`audience_key` normalise
# the one reader whose name and result shape differ per provider (Omnisend
# `segments`→`segments`, Constant Contact `contact_lists`→`lists`).
# ---------------------------------------------------------------------------
PROFILES: dict[str, dict] = {
    "omnisend": dict(
        name="Omnisend",
        adapter="omnisend",
        audience_fn="segments", audience_key="segments",
        # The segment LIST carries no count (proven live 2026-09-03); the
        # number is a second call per segment. `audience_count` asks this.
        count_fn="segment_count",
        # VERIFIED against Omnisend's own docs on 2026-08-21 (support
        # articles 1061845 "Use Personalization" + 11197418 "Liquid
        # Templating"), after the first live draft rendered the previous
        # guess as LITERAL TEXT in the owner's preview — camelCase curly
        # braces were wrong twice over. Omnisend is modified Liquid:
        # SQUARE brackets, snake_case, quoted defaults. There is NO
        # view-in-browser variable in their tag set, so the token is absent
        # here ON PURPOSE — `caps.webview=False` keeps the renderer from
        # emitting a link no variable can fill, and `personalize` refusing
        # an unmapped token is the backstop if one slips through. Their
        # logic tags ([% if %]) work only in Automations, never campaigns.
        merge={
            "FIRST_NAME": "[[contact.first_name | default: 'there']]",
            "LAST_NAME": "[[contact.last_name | default: '']]",
            "EMAIL": "[[contact.email]]",
            "UNSUBSCRIBE": "[[unsubscribe_link]]",
        },
        caps=dict(hosts_images=True, dynamic_products=True, segments=True,
                  webview=False),
    ),
    "klaviyo": dict(
        name="Klaviyo",
        adapter="klaviyo",              # adapter not built yet — backend() says so
        audience_fn="segments", audience_key="segments",
        # VERIFY on first real send. Klaviyo renders Django-style tags.
        merge={
            "FIRST_NAME": "{{ first_name|default:'there' }}",
            "LAST_NAME": "{{ last_name|default:'' }}",
            "EMAIL": "{{ email }}",
            "UNSUBSCRIBE": "{% unsubscribe %}",
            "VIEW_IN_BROWSER": "{% web_view %}",
        },
        caps=dict(hosts_images=True, dynamic_products=True, segments=True),
    ),
    "constant_contact": dict(
        name="Constant Contact",
        adapter="constant_contact",
        audience_fn="contact_lists", audience_key="lists",
        # VERIFY on first real send. Constant Contact uses bracketed contact
        # detail tags, and has no segment engine — it targets contact LISTS.
        merge={
            "FIRST_NAME": "[[FirstName]]",
            "LAST_NAME": "[[LastName]]",
            "EMAIL": "[[EmailAddress]]",
            "UNSUBSCRIBE": "[[UnsubscribeLink]]",
            "VIEW_IN_BROWSER": "[[BrowserLink]]",
        },
        # No image hosting API and no segments — a generator reads this and
        # falls back to store-hosted image URLs and list targeting instead.
        caps=dict(hosts_images=False, dynamic_products=False, segments=False),
    ),
}

#: The order to prefer when a client somehow has more than one ESP connected —
#: which should not happen (they grant one `esp` capability), but resolving it
#: deterministically beats resolving it by dict order.
PROVIDERS = ("omnisend", "klaviyo", "constant_contact")


def provider_for(tenant: str) -> str:
    """Which ESP this client actually has connected, or "".

    Reads the credential store (client connection first, env second — the same
    resolution every other consumer uses), never the *declared* `esp.provider`
    on the Tenant row: declared is intent, and a campaign cannot be drafted into
    an intention. First connected provider wins; there should only ever be one.
    """
    if not tenant:
        return ""
    for p in PROVIDERS:
        got = cred.resolve(tenant, p)
        if (got or {}).get("secret"):
            return p
    return ""


def profile(tenant: str) -> dict:
    """The presentation-native profile for this client's ESP, or {}."""
    return PROFILES.get(provider_for(tenant), {})


def backend(tenant: str):
    """The transport adapter for this client's ESP: ``(module, "")`` or
    ``(None, refusal)``.

    Refuses BY NAME, the two ways it can: no ESP connected at all, or connected
    to a provider whose send adapter has not been written yet (Klaviyo, today).
    Both are things somebody can act on — connect one, or build the adapter —
    and neither is a silent None the generator would trip over three calls later.
    """
    if not tenant:
        return None, "no account — say which client this campaign is for."
    p = provider_for(tenant)
    if not p:
        return None, (f"{tenant} has no email platform connected. Connect "
                      f"Omnisend, Klaviyo or Constant Contact on the Accounts "
                      f"tab before a campaign can be drafted into one.")
    prof = PROFILES.get(p, {})
    mod_name = prof.get("adapter", "")
    try:
        from importlib import import_module
        mod = import_module(f".{mod_name}", __package__)
    except Exception:                                            # noqa: BLE001
        return None, (f"{tenant} is connected to {prof.get('name', p)}, but its "
                      f"send adapter is not built yet — nothing can be drafted "
                      f"into it here. This is our gap, not the account's.")
    # A provider that is a known ESP but has no real send surface yet (a profile
    # exists, the module imports, but it is a stub) still refuses honestly.
    if not hasattr(mod, "draft_from_html"):
        return None, (f"{prof.get('name', p)}'s adapter has no draft path yet.")
    return mod, ""


def caps(tenant: str) -> dict:
    """What this client's ESP can do — read BEFORE composing.

    A generator asks this so it composes for what the platform actually
    supports: whether it can host images (else use store-hosted URLs), whether
    it has dynamic product blocks (else render static product cards from
    commerce data), whether it segments (else target lists). Absent ESP returns
    everything False, which reads as "assume nothing" — the safe default.
    """
    return dict(PROFILES.get(provider_for(tenant), {}).get("caps", {}))


def personalize(tenant: str, html: str) -> dict:
    """Render a canonical email's neutral tokens native for this client's ESP.

    `{{FIRST_NAME}}` becomes Omnisend's `{{ contact.firstName }}`, Klaviyo's
    `{{ first_name }}`, or Constant Contact's `[[FirstName]]`. Returns
    ``{ok, html}`` or ``{ok: False, error}``.

    **Refuses on an unknown token rather than leaving it in the body.** A stray
    `{{FIRST NAME}}` or `{{FISRT_NAME}}` that slipped past the generator would
    otherwise reach a customer as literal text — the cheap, visible kind of
    brand damage. The closed `TOKENS` set is what makes that catchable.
    """
    prof = profile(tenant)
    if not prof:
        return {"ok": False, "error": (
            f"{tenant} has no ESP connected, so there is no native syntax to "
            f"render personalization into.")}
    merge = prof.get("merge", {})

    unknown = sorted({m.group(1).strip() for m in _TOKEN_RE.finditer(html or "")}
                     - set(TOKENS))
    if unknown:
        return {"ok": False, "error": (
            "unknown personalization token(s): " + ", ".join(unknown)
            + f". Use only {', '.join(TOKENS)} — a token this layer does not "
            f"know would ship to the customer as literal text.")}

    out = _TOKEN_RE.sub(lambda m: merge.get(m.group(1).strip(), m.group(0)),
                        html or "")
    return {"ok": True, "html": out, "provider": provider_for(tenant)}


def audiences(tenant: str) -> dict:
    """The client's targetable audiences — segments or lists — normalised.

    Omnisend and Klaviyo call them segments; Constant Contact calls them lists
    and has no segment engine. A generator targeting "lapsed buyers" needs the
    same shape back whichever it is, so this returns
    ``{ok, audiences: [{id, name, count}], kind}`` and the caller reads `kind`
    only when it matters (a segment can be behavioural; a list is static).
    """
    mod, refusal = backend(tenant)
    if refusal:
        return {"ok": False, "error": refusal}
    prof = profile(tenant)
    fn = getattr(mod, prof.get("audience_fn", ""), None)
    if not fn:
        return {"ok": False, "error": (
            f"{prof.get('name', '')} has no audience reader wired.")}
    got = fn(tenant)
    if not got.get("ok"):
        return got
    rows = got.get(prof.get("audience_key", ""), []) or []
    kind = "list" if prof.get("audience_fn") == "contact_lists" else "segment"
    return {"ok": True, "kind": kind,
            "audiences": [{"id": r.get("id", ""), "name": r.get("name", ""),
                           # None when the provider sent none — Omnisend's
                           # segment list carries no counts (proven live
                           # 2026-09-03: a row is segmentID, name, status,
                           # conditionGroups and dates), and collapsing that
                           # absence to 0 made every one of its segments
                           # read as empty (the zero-members drift check
                           # would have fired on ALL of them). Absence is a
                           # third state and survives to the output; a
                           # caller that needs the number for a LINKED
                           # audience asks `audience_count`.
                           "count": r.get("count", r.get("membership_count"))}
                          for r in rows]}


def audience_count(tenant: str, audience_id: str):
    """Members in ONE audience, from wherever the provider keeps it — or None.

    Omnisend's segment list carries no count and the number is a per-segment
    call on ``/statistics`` (``contactsCount``, proven live 2026-09-03), so
    `audiences` cannot fill it without one call per segment on the whole
    list. This asks for one audience, and the caller asks only for the ones
    it is linked to. Constant Contact's list rows carry `membership_count`
    already, so `audiences` fills those and this is never needed.

    None means the provider has no reader for it, the segment id is empty, or
    the read refused — a third state, not zero. The zero-members drift check
    reads None as "not sent" and stays quiet.
    """
    if not audience_id:
        return None
    mod, refusal = backend(tenant)
    if refusal:
        return None
    fn = getattr(mod, profile(tenant).get("count_fn", ""), None)
    if not fn:
        return None
    got = fn(tenant, audience_id) or {}
    n = got.get("count") if got.get("ok") else None
    return n if isinstance(n, (int, float)) else None
