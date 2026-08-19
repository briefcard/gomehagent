"""The ban list, on the path that publishes to a live customer site.

The audit that opened this session found the inversion that made this file
necessary: `grep -c "banned|validator|compliance"` across `shopify_seo`,
`wordpress_seo` and `seo_tools` returned **0, 0, 0** — and those three are the
only modules in the repo that write to customer-facing properties. Everything
that merely REPORTED had every guarantee; the thing that PUBLISHED had none.

It is worse than "SEO metadata", which is how it was described for most of this
session and was wrong. `update_seo` writes `body_html` — the real description
copy — and on WordPress with `resource="post"` it replaces the entire `content`
of an article. Baci's own audit is 110 flagged strings, 96 of them one templated
SEO meta description, in exactly the field this path writes.

**Scope, deliberately narrow.** This checks the ban list and nothing else.
`require_citation` is False: an SEO title has no claim to cite, and demanding
one would block every legitimate write and get the guard switched off inside a
week. A guard that fires on everything is a guard somebody removes.

**It fails closed, and it says which field.** "Blocked" sends someone hunting;
"the body says 'hand-decorated'" is one edit away from fixed.
"""
from __future__ import annotations

#: The fields that become words on the page. A field not listed here is not
#: unchecked by oversight — ids, handles and slugs are not prose and flagging a
#: banned word inside a URL slug is the false positive that gets a guard
#: disabled.
PROSE_FIELDS = ("title", "body_html", "content", "summary_html",
                "seo_title", "seo_description", "excerpt")


def tenant_for(profile: dict) -> str:
    """Which account this site belongs to, by domain.

    Reuses `tenant_scope`'s existing domain map rather than adding a second
    one — a site profile and a tenant are already joined there, and a second
    join is a second thing to drift.
    """
    from . import tenant_scope
    _alias, by_domain, _keys = tenant_scope._lookups()
    return by_domain.get(tenant_scope._norm_domain(profile.get("domain", "")), "")


def check(profile: dict, fields: dict, *, what: str = "") -> str:
    """"" if this may be published, else why not.

    Returns a REASON rather than raising, because every caller here returns a
    string to an agent and an exception would arrive as a stack trace in a
    chat window.
    """
    from . import assurance, validator

    tenant = tenant_for(profile)
    if not tenant:
        # Not silently allowed. A site nobody has matched to an account has no
        # ban list, and publishing to it unchecked is the same hole this file
        # exists to close — it just fails at a different layer.
        return (f"No account matches {profile.get('domain') or profile.get('key')!r}, "
                f"so there is no ban list to check this against. Link the site "
                f"to a tenant before publishing to it.")

    parts = [str(fields.get(f) or "") for f in PROSE_FIELDS]
    body = "\n".join(p for p in parts if p.strip())
    if not body.strip():
        return ""            # nothing to say means nothing to check

    verdict = validator.check(tenant, body, require_citation=False)
    caught = [f["rule"] for f in verdict["failures"]]
    assurance.record(
        tenant, source="seo", system_key="seo",
        checked=verdict.get("checked") or [], caught=caught,
        verdict="passed" if verdict["ok"] else "blocked", grounded=False)
    if verdict["ok"]:
        return ""

    # Name the FIELD, not just the rule. The caller is about to edit one of
    # seven strings and needs to know which.
    bad = [f for f in PROSE_FIELDS
           if any(hit["phrase"].lower() in str(fields.get(f) or "").lower()
                  for hit in validator._banned(tenant, body))]
    why = "; ".join(f"{f['rule']}: {f['detail']}" for f in verdict["failures"])
    return (f"Refused{' — ' + what if what else ''}: {why}."
            + (f" Look at: {', '.join(bad)}." if bad else "")
            + " Nothing was published. Reword it, or retire the rule if it is "
              "no longer true.")
