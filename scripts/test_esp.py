"""The ESP abstraction: one interface over Omnisend / Klaviyo / Constant Contact.

The campaign generator produces ONE canonical email and this layer renders it
native for whichever ESP a client connected. Driven offline — the credential
resolver and each adapter's transport are the module seams the suite replaces,
so no live ESP is touched. What is checked is the ABSTRACTION: which provider a
client resolves to, that personalization becomes each provider's native syntax
(and refuses an unknown token), that a client with no ESP — or one whose adapter
is unbuilt — refuses by name, and that one client's ESP never bleeds into
another's.

Run: python3 scripts/test_esp.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'esp.db')}"
os.environ["APPROVAL_SECRET"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (constant_contact, credentials as cred, db, esp,  # noqa: E402
                 omnisend, tenants)

_fail: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


# Which ESP each client is "connected" to, controlled by a fake resolver so the
# credential store and its encryption stay out of this suite.
_CONNECTED = {"baci": "omnisend", "coverings": "constant_contact",
              "ironside": "klaviyo"}  # eien: nothing connected


def _fake_resolve(tenant, provider, site=""):
    if _CONNECTED.get(tenant) == provider:
        return {"secret": "test-key", "source": "test"}
    return {}


def main() -> int:
    db.init_db()
    tenants.seed()
    cred.resolve = _fake_resolve

    print("— which ESP is this client on —")
    ck("baci resolves to omnisend", esp.provider_for("baci") == "omnisend",
       esp.provider_for("baci"))
    ck("coverings resolves to constant_contact",
       esp.provider_for("coverings") == "constant_contact")
    ck("ironside resolves to klaviyo", esp.provider_for("ironside") == "klaviyo")
    ck("a client with no ESP resolves to nothing",
       esp.provider_for("eien") == "")

    print("\n— the transport adapter, or a refusal that names the fix —")
    mod, refusal = esp.backend("baci")
    ck("a connected client gets its adapter", mod is omnisend and not refusal)
    mod, refusal = esp.backend("eien")
    ck("no ESP connected refuses by name",
       mod is None and "no email platform connected" in refusal, refusal[:70])
    mod, refusal = esp.backend("ironside")
    ck("connected to Klaviyo (no adapter yet) refuses honestly",
       mod is None and "not built yet" in refusal, refusal[:70])

    print("\n— personalization becomes each provider's native syntax —")
    body = "<p>Hi {{FIRST_NAME}}, <a href='{{UNSUBSCRIBE}}'>unsubscribe</a></p>"
    om = esp.personalize("baci", body)
    # CHANGED 2026-08-21, deliberately: the old pin held the camelCase
    # curly-brace GUESS, and the first live draft rendered it as literal
    # text in the owner's preview. Verified against Omnisend's own docs
    # (support articles 1061845 + 11197418): modified Liquid, SQUARE
    # brackets, snake_case, quoted default.
    ck("omnisend gets [[contact.first_name | default: 'there']]",
       om["ok"] and "[[contact.first_name | default: 'there']]" in om["html"]
       and "[[unsubscribe_link]]" in om["html"]
       and "{{FIRST_NAME}}" not in om["html"], om.get("html", "")[:60])
    cc = esp.personalize("coverings", body)
    ck("constant contact gets [[FirstName]]",
       cc["ok"] and "[[FirstName]]" in cc["html"], cc.get("html", "")[:60])
    ck("the two providers render the SAME token differently",
       om["html"] != cc["html"])

    print("\n— an unknown token is refused, not shipped as text —")
    bad = esp.personalize("baci", "<p>Hi {{FIRSTNAME}} and {{FisrtName}}</p>")
    ck("a typo'd token refuses and names it — mixed case caught too",
       not bad["ok"] and "FIRSTNAME" in bad["error"]
       and "FisrtName" in bad["error"], bad.get("error", "")[:80])
    none = esp.personalize("eien", body)
    ck("no ESP means no native syntax to render into",
       not none["ok"] and "no ESP" in none["error"])

    print("\n— capabilities a generator reads before composing —")
    ck("omnisend hosts images and segments", esp.caps("baci")["hosts_images"]
       and esp.caps("baci")["segments"])
    ck("constant contact hosts no images and has no segments",
       not esp.caps("coverings")["hosts_images"]
       and not esp.caps("coverings")["segments"])
    ck("no ESP assumes nothing", esp.caps("eien") == {}
       or not any(esp.caps("eien").values()))

    print("\n— audiences, normalised across segments and lists —")
    omnisend.call = lambda t, m, p, **k: {
        "ok": True, "data": {"segments": [{"segmentID": "s1",
                                           "name": "Lapsed buyers"}]}}
    a = esp.audiences("baci")
    ck("omnisend segments come back normalised as audiences",
       a["ok"] and a["kind"] == "segment"
       and a["audiences"][0]["name"] == "Lapsed buyers", str(a)[:80])
    constant_contact.call = lambda t, m, p, **k: {
        "ok": True, "data": {"lists": [{"list_id": "l1", "name": "Newsletter",
                                        "membership_count": 500}]}}
    b = esp.audiences("coverings")
    ck("constant contact lists come back in the same shape",
       b["ok"] and b["kind"] == "list"
       and b["audiences"][0]["count"] == 500, str(b)[:80])

    print("\n— isolation: one client's ESP never decides another's —")
    ck("baci and coverings resolve to different providers",
       esp.provider_for("baci") != esp.provider_for("coverings"))
    # CHANGED 2026-08-21: bracket style no longer separates the providers —
    # verified Omnisend is square-bracket Liquid too. What still must never
    # cross is the VOCABULARY: Constant Contact's tags on an Omnisend
    # account (or vice versa) ship as literal text.
    ck("baci's personalization carries no constant-contact tag names",
       "[[FirstName]]" not in esp.personalize("baci", body)["html"]
       and "[[UnsubscribeLink]]" not in esp.personalize("baci", body)["html"])

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
