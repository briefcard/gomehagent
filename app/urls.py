"""WHERE A CONSOLE ADDRESS IS BUILT — the only place, and a small one.

It lived inside `admin_ui` for a day and that was already wrong: the five
modules that tell a person where to go next (a WhatsApp reply, a proposal's
"review at", a refusal's "fix it here") would each have had to import the
console's largest module to name a page. A URL builder is string work; it
should cost an import of nothing.
"""
from __future__ import annotations

#: The cross-account view. Mirrors `admin_ui.ALL`, which imports from here.
ALL = "*"


def url(tenant: str, tab: str = "content", *parts, **view) -> str:
    """THE ONE PLACE A CONSOLE LINK IS BUILT.

    Owner, 2026-09-23, on `/admin/ui?tab=systems&tenant=baci&system=campaign_
    email&wf=designs&key=…`: *"We need to fix the way we do routing — look at
    how messy this is … Isn't this ridiculous?"* It was: the path said
    nothing, four query parameters carried the identity of the page, and the
    credential rode along beside them.

    The identity of a page goes in the PATH, in the order you would say it —
    the account, then the tab, then whatever that tab nests:

        /admin/baci/systems/campaign_email/designs
        /admin/baci/brand
        /admin/baci/content?page=2

    and the query keeps only what is genuinely a VIEW of that page: a page
    number, a search, a sort, a flash message. A link built anywhere else is
    a link that drifts, which is why every caller comes through here.
    """
    from urllib.parse import quote, urlencode
    # "all" rather than the internal `*`: a path segment a person can type,
    # and the route maps it back. The cross-account view is a place you go on
    # purpose, so it is named in the URL like everywhere else.
    who = "all" if (not tenant or tenant == ALL) else tenant
    path = "/admin/" + "/".join(quote(str(p_), safe="") for p_ in
                                ([who, tab] + [x for x in parts if x]))
    q = {k: v for k, v in view.items() if v not in ("", None)}
    # %20, NOT `+`. `urlencode` defaults to quote_plus, which is correct for a
    # form body and wrong here: these values are read back by people (a flash
    # sentence lands in the address bar) and by every suite that asserts on
    # one. Same encoding as the hand-written links this replaced.
    return path + (f"?{urlencode(q, quote_via=quote)}" if q else "")
