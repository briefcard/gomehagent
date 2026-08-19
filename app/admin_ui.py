"""Single-page console for wiring accounts.

Everything here is also reachable as bare /admin/* URLs, but hand-typing JSON
into a browser bar is how connections get mis-set. This page renders the same
operations as forms, with the how-to-get-this-value instructions sitting next
to the field they belong to rather than in a document you have to cross-read.

Server-rendered, no build step, no external assets — it has to work from a
phone on a hotel wifi.
"""
from __future__ import annotations

import html
import json

from . import config, db, kb, systems, tenants

# The instructions that used to live in a separate manual. Kept beside the
# fields so a value is never entered from memory.
FIELD_HELP = {
    "gmail_alias": (
        "Inbox monitoring + sending drafts",
        "A key from GMAIL_ACCOUNTS_JSON — not an email address. "
        "To add a new one: run scripts/google_oauth.py locally, sign in as that "
        "mailbox, and add the resulting entry to GMAIL_ACCOUNTS_JSON in Render. "
        "For a client, they must grant access to their own Google account."),
    "shopify_store": (
        "Products, inventory, orders",
        "A key from SHOPIFY_STORES_JSON. To create one: in their Shopify admin go to "
        "Settings → Apps and sales channels → Develop apps → Create an app → "
        "Configure Admin API scopes (read_products, read_orders, read_inventory) → "
        "Install → reveal the Admin API access token. Store the token in Render, "
        "put the KEY here."),
    "esp": (
        "Email campaigns, segments, holdouts",
        "Omnisend: Store settings → Integrations & API → API keys → create one. "
        "Klaviyo: Settings → API keys → create a Private Key. "
        "Constant Contact is OAuth, not a key — it needs the auth layer first. "
        "Put the API key in a Render env var and reference its NAME here."),
    "cms": (
        "Blog and page publishing",
        "Shopify: same custom app as commerce, add read_content/write_content. "
        "WordPress: an application password on an editor account. "
        "Squarespace has no usable publishing API — those tenants generate and hand off."),
    "ads": (
        "Spend, ROAS, creative performance",
        "Meta: Business Manager → the ad account → the ID in the URL or account "
        "dropdown (digits only, no 'act_' prefix). "
        "Google Ads: the 10-digit customer ID at the top right, dashes removed."),
    "analytics": (
        "Traffic, rankings, attribution",
        "GA4: Admin → Property settings → Property ID (numeric). "
        "Search Console: the property exactly as verified, including the "
        "sc-domain: prefix if it's a domain property. "
        "semrush_db is the country database, usually 'us'."),
    "crm": (
        "Deal and contact context on inbound",
        "Salesforce: a Connected App with API access; store the credentials in "
        "Render and reference them here. HubSpot: a private app token."),
    "design": (
        "Canva assets for posts and flyers",
        "Connect it on this tab. Canva Connect is OAuth with PKCE — set "
        "CANVA_CLIENT_ID / CANVA_CLIENT_SECRET and register the redirect URI "
        "shown beside the provider. Each account gets its own folder. "
        "built before this field does anything. Leave blank."),
    "systems": (
        "Which pipelines run for this account",
        "A JSON list. Currently meaningful: lead_responder, campaign_email, "
        "blog, reorder_engine, service_desk, reports."),
}

_CSS = """
:root{--bg:#f6f7fa;--panel:#fff;--ink:#15171d;--ink2:#3d434f;--mut:#6e7686;
--rule:#dfe3ea;--rule2:#eef0f4;--acc:#2f4b7c;--accs:#e8edf6;--ok:#2a6357;--oks:#e3efeb;
--gap:#95602a;--gaps:#f6ebdc}
@media(prefers-color-scheme:dark){:root{--bg:#101218;--panel:#171a22;--ink:#e9ebf0;
--ink2:#b9bfcc;--mut:#858d9e;--rule:#2a2f3b;--rule2:#212632;--acc:#87a6d8;--accs:#1c2434;
--ok:#66ad99;--oks:#152621;--gap:#d2a063;--gaps:#2a2115}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,
BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.w{max-width:960px;margin:0 auto;padding:32px 20px 80px;display:flex;flex-direction:column;gap:30px}
h1{font:600 1.7rem/1.2 Georgia,serif;margin:0}
h2{font:600 1.15rem/1.2 Georgia,serif;margin:0}
h3{font:600 .98rem/1.3 Georgia,serif;margin:0}
.mut{color:var(--mut);font-size:.86rem}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:7px;padding:16px 18px;
display:flex;flex-direction:column;gap:12px}
.head{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:baseline;
border-bottom:1px solid var(--rule);padding-bottom:10px}
.head h2{flex:1 1 auto}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{font-size:.68rem;padding:.2em .5em;border-radius:3px;font-weight:700;letter-spacing:.03em}
.chip.on{background:var(--oks);color:var(--ok);border:1px solid var(--ok)}
.chip.off{background:var(--gaps);color:var(--gap);border:1px solid var(--gap)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.f{display:flex;flex-direction:column;gap:5px;border:1px solid var(--rule);border-radius:5px;
padding:11px 13px;background:var(--rule2)}
.f label{font-size:.72rem;text-transform:uppercase;letter-spacing:.07em;font-weight:700;color:var(--acc)}
.f .what{font-size:.8rem;color:var(--ink2)}
.f details{font-size:.79rem;color:var(--mut)}
.f summary{cursor:pointer;color:var(--acc);font-weight:600;font-size:.75rem}
.f details p{margin:6px 0 0}
input,select{font:inherit;font-size:.85rem;padding:6px 8px;border:1px solid var(--rule);
border-radius:4px;background:var(--panel);color:var(--ink);width:100%}
button{font:inherit;font-size:.82rem;font-weight:600;padding:6px 13px;border-radius:5px;
border:1px solid var(--acc);background:var(--acc);color:var(--panel);cursor:pointer}
button.sec{background:transparent;color:var(--acc)}
.row{display:flex;gap:7px;align-items:center;flex-wrap:wrap}
/* `.conn` is a flex ROW (name | state | actions) and this form is a third
   child of it, so without a full-width basis it is squeezed into whatever
   column is left over — the inputs collapse to a few pixels and cannot be
   clicked into, let alone pasted into. `flex-basis:100%` puts it on its own
   line under the row it belongs to. */
.cform{flex:0 0 100%;margin-top:7px;border:1px solid var(--rule);
  border-radius:5px;padding:8px 11px}
.cform summary{cursor:pointer;font-size:.8rem;color:var(--acc);font-weight:600}
.cform .f{margin-top:9px}
.cform input,.cform select{width:100%;box-sizing:border-box}
.cform .f{gap:4px}
.cform label{font-size:.75rem;color:var(--mut)}
.picgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px}
.pic{position:relative;display:block;border:1px solid var(--rule);border-radius:5px;
  overflow:hidden;cursor:pointer;background:var(--panel)}
.pic img{display:block;width:100%;height:112px;object-fit:cover;background:var(--rule2)}
.pic input{position:absolute;top:7px;left:7px;z-index:2;transform:scale(1.25)}
.pic:has(input:checked){outline:2px solid var(--acc);outline-offset:-2px}
.picmeta{display:block;font-size:.68rem;color:var(--mut);padding:5px 7px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.inst{border:1px solid var(--rule);border-radius:5px;padding:11px 13px;
  margin-bottom:8px;display:flex;flex-direction:column;gap:6px}
.inst.ok{border-left:3px solid var(--ok)}
.inst.gap{border-left:3px solid var(--gap)}
.inst.done{border-left:3px solid var(--rule);opacity:.72}
.insthead{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.insthead .grow{flex:1}
.prereqs{display:flex;gap:6px;flex-wrap:wrap}
.pre{font-size:.72rem;border-radius:100px;padding:2px 9px;border:1px solid var(--rule);
  white-space:nowrap}
.pre.yes{color:var(--ok)}
.pre.no{color:var(--gap)}
.btn{display:inline-block;font-size:.78rem;padding:4px 12px;border-radius:4px;
  background:var(--acc);color:var(--panel);text-decoration:none}
.btn.sec{background:transparent;color:var(--ink);border:1px solid var(--rule)}
.bulkbar{position:sticky;top:0;z-index:5;display:flex;gap:8px;align-items:center;
  flex-wrap:wrap;background:var(--panel);border:1px solid var(--rule);
  border-radius:5px;padding:9px 12px;margin-bottom:10px}
.bulkbar .grow{flex:1}
/* The waiting-decisions counter in the tab bar. Defined WITH the markup. */
.tabs a.pend{margin-left:auto;color:var(--acc);border-color:var(--acc);
font-weight:600}
.pick{display:inline-flex;gap:6px;align-items:center;font-size:.75rem;
  color:var(--mut);cursor:pointer;user-select:none}
/* Sticky bar is ~44px tall and would otherwise cover the card just jumped to. */
.anchor{position:relative;top:-56px;display:block;height:0;visibility:hidden}
code{font-family:ui-monospace,Menlo,monospace;font-size:.82em;background:var(--rule2);
padding:.1em .35em;border-radius:3px}
.cur{background:var(--accs);border-left:3px solid var(--acc)}
.note{background:var(--gaps);border-left:3px solid var(--gap);padding:10px 14px;
border-radius:0 4px 4px 0;font-size:.85rem;color:var(--ink2)}
.ok{background:var(--oks);border-left:3px solid var(--ok);padding:10px 14px;
border-radius:0 4px 4px 0;font-size:.85rem;color:var(--ink2)}
.cols{width:100%;border-collapse:collapse;margin-top:10px;font-size:12.5px}.cols th{text-align:left;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#8a8f98;padding:5px 8px;border-bottom:1px solid #e2e5ea}.cols td{padding:5px 8px;border-bottom:1px solid #f0f2f5;vertical-align:middle}.cols .cn{font-family:ui-monospace,Menlo,monospace}.cols .ct{font-family:ui-monospace,Menlo,monospace;color:#8a8f98;font-size:11px}.cols .cf{width:150px;white-space:nowrap}.fillbar{display:inline-block;width:88px;height:6px;border-radius:3px;background:#e6e9ee;vertical-align:middle;overflow:hidden}.fillbar i{display:block;height:100%;background:#2f7d5c}.fillbar i.sec{background:#c9a227}.fillbar i.off{background:#cfd4da}.fillpct{font-family:ui-monospace,Menlo,monospace;font-size:10.5px;color:#8a8f98;margin-left:7px}.tabs{display:flex;gap:4px;border-bottom:1px solid var(--rule);flex-wrap:wrap}
.tabs a{text-decoration:none;font-size:.85rem;font-weight:600;color:var(--mut);
padding:8px 15px;border:1px solid transparent;border-bottom:none;border-radius:5px 5px 0 0;
position:relative;bottom:-1px}
.tabs a.on{color:var(--acc);background:var(--panel);border-color:var(--rule);
border-bottom:1px solid var(--panel)}
textarea{font:inherit;font-size:.85rem;padding:6px 8px;border:1px solid var(--rule);
border-radius:4px;background:var(--panel);color:var(--ink);width:100%;resize:vertical}
.sysgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}
.stat{display:flex;gap:16px;flex-wrap:wrap;font-size:.8rem;color:var(--mut)}
.stat b{color:var(--ink);font-weight:600}
.thread{display:flex;flex-direction:column;gap:7px}
.msg{border-left:2px solid var(--rule);padding:3px 0 3px 11px;font-size:.85rem}
.msg .when{font-size:.72rem;color:var(--mut)}
.rung{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:.8rem}
.rung .step{padding:.15em .5em;border-radius:3px;border:1px solid var(--rule);color:var(--mut);font-size:.72rem}
.rung .step.at{background:var(--accs);border-color:var(--acc);color:var(--acc);font-weight:700}
.rung .step.done{color:var(--ok);border-color:var(--ok)}
ul.bl{margin:0;padding-left:18px;font-size:.85rem;color:var(--ink2)}
ul.bl li{margin:2px 0}
.chip.nb{background:var(--rule2);color:var(--ink2);border:1px solid var(--rule)}
.kv{display:grid;grid-template-columns:130px 1fr;gap:5px 14px;margin:0;font-size:.85rem}
.kv dt{color:var(--mut);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;
font-weight:700;padding-top:2px}
.kv dd{margin:0;color:var(--ink2);min-width:0;overflow-wrap:anywhere}
@media(max-width:560px){.kv{grid-template-columns:1fr;gap:1px 0}.kv dd{margin-bottom:7px}}
details.conns{border:1px solid var(--rule);border-radius:6px;padding:10px 13px;
background:var(--rule2);margin:4px 0}
details.conns>summary{cursor:pointer;font-weight:600;font-size:.85rem;color:var(--acc)}
.conn{display:flex;justify-content:space-between;align-items:center;gap:12px;
flex-wrap:wrap;padding:7px 0;border-top:1px solid var(--rule)}
.conn:first-of-type{border-top:0}
/* Assurance tables. Added WITH the markup that uses them -- `.bulkbar` shipped
   referencing var(--card), which this stylesheet does not define, and the
   sticky bar had no background for weeks. */
.tbl{width:100%;border-collapse:collapse;margin:6px 0;font-size:.85rem}
.tbl th{text-align:left;font-weight:600;color:var(--acc);padding:5px 8px;
border-bottom:1px solid var(--rule)}
.tbl td{padding:5px 8px;border-bottom:1px solid var(--rule)}
.tbl td.num{text-align:right;font-variant-numeric:tabular-nums}
/* One line per connected install. `.conn` is a flex ROW, so these have to be
   full-basis children or each site is squeezed into whatever column is left --
   the same fault the WordPress connect form had, measured in a browser. */
.conn-site{flex:1 0 100%;display:flex;align-items:center;gap:9px;flex-wrap:wrap;
padding:4px 0 4px 12px;border-left:2px solid var(--rule)}
form.inl{display:inline}
.mklink{margin-top:10px;padding-top:10px;border-top:1px solid var(--rule)}
/* `size` is ignored once these are flex children, so both are pinned here or
   the days box stretches to the full row width and wraps the button. */
.mklink input[name=label]{flex:0 1 190px}
.mklink input[name=days]{flex:0 0 56px}
.card.danger{border-color:var(--gap);background:var(--gaps)}
.card.danger .head h2{color:var(--gap)}
input.copy{width:100%;font-family:ui-monospace,Menlo,monospace;font-size:.8rem;
margin-top:6px}
details.sec{border:1px solid var(--rule);border-radius:5px;padding:9px 12px;background:var(--rule2)}
details.sec>summary{cursor:pointer;font-weight:600;font-size:.88rem;color:var(--acc)}
details.sec[open]>summary{margin-bottom:9px;border-bottom:1px solid var(--rule);padding-bottom:7px}
.msg.gone{opacity:.62}
.msg.esc{border-left-color:var(--gap)}\n.tags{display:flex;flex-wrap:wrap;gap:4px 10px}\n.tags .tag{font-size:.78rem;color:var(--ink2);display:flex;align-items:center;gap:4px;white-space:nowrap}\n.tags input{width:auto}
"""

_TABS = (("accounts", "Accounts"), ("systems", "Systems"), ("kb", "Knowledge"),
         ("content", "Content"), ("assurance", "Assurance"),
         ("schema", "Data layer"))


def _shell(key: str, tab: str, title: str, body: str, suffix: str = "") -> str:
    nav = "".join(
        f'<a class="{"on" if t == tab else ""}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab={t}{suffix if t == tab else ""}">{label}</a>'
        for t, label in _TABS)
    # How many decisions are waiting, on every page.
    #
    # `approvals.pending_count` was written and never called, so the one number
    # that says whether this system is waiting on a person was visible nowhere.
    # A queue nobody can see the depth of is a queue that stops being worked --
    # which this codebase has already lived through once, at ~200 drafts.
    try:
        from . import approvals as _ap
        _n = _ap.pending_count()
    except Exception:                                            # noqa: BLE001
        _n = 0                 # never let a counter break the console
    if _n:
        nav += (f'<a class="pend" href="/admin/pending?key={_esc(key)}">'
                f'{_n} waiting</a>')
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} — Saias Ops</title><style>{_CSS}</style></head><body><div class="w">
<div class="tabs">{nav}</div>
{body}
</div></body></html>"""


def _esc(v) -> str:
    return html.escape(str(v or ""), quote=True)


def _chips(caps: dict) -> str:
    return "".join(
        f'<span class="chip {"on" if ok else "off"}">{c}</span>'
        for c, ok in caps.items())


def _connections(tenant: str, key: str) -> str:
    """What this account has actually connected, and the buttons to change it.

    `credentials.status()` has always returned all of this — state, who granted
    it, when it last verified, which scopes came back dark — and nothing on the
    console rendered any of it. Every connection action was a curl the runbook
    told you to paste, which is the §2.13 shape: the credential layer was the
    part of the platform its own operator could not see.

    The secret is not here and cannot be. Nothing on this page has ever held a
    value, only a state.
    """
    from . import credentials as cred
    rows = cred.status(tenant)
    out = []
    for r in rows:
        state = r["state"]
        # The console keeps the alternative visible where the client page drops
        # it, because switching a client from one ESP to another is an owner's
        # job and the form to do it has to be somewhere.
        if r["covered_by"]:
            chip = '<span class="chip nb">not needed</span>'
        else:
            chip = f'<span class="chip {"on" if state == "connected" else "off"}">' \
                   f'{_esc(state)}</span>'
        bits = []
        if r["covered_by"]:
            bits.append(f'this account is on {_esc(r["covered_by"])}')
        if r["detail"]:
            bits.append(_esc(r["detail"]))
        if r["last_verified"]:
            bits.append(f'checked {_esc(r["last_verified"])}')
        detail = f'<div class="mut">{" · ".join(bits)}</div>' if bits else ""

        if r["kind"] == "oauth" and r["self_serve"]:
            label = "Reconnect" if state == "connected" else "Connect"
            action = (f'<a href="/admin/oauth/{_esc(r["provider"])}'
                      f'?key={_esc(key)}&amp;tenant={_esc(tenant)}">'
                      f'<button class="sec" type="button">{label}</button></a>')
        elif r["kind"] == "oauth":
            # Named, not hidden: the thing standing in the way is an env var
            # someone can go and set, and saying which is the whole difference
            # between a blocker and a feature that reads as unbuilt.
            #
            # And the redirect URI is shown, because it is the other half of the
            # job and the half that fails silently: it must match the provider
            # console byte for byte, and a mismatch surfaces as a consent screen
            # rejecting you with no hint of why.
            from . import oauth as _oauth
            action = (f'<div class="mut">{_esc(r["blocked_by"])}</div>'
                      f'<div class="when">Then register this redirect URI, '
                      f'exactly:<br><code>{_esc(_oauth.redirect_uri(r["provider"]))}'
                      f'</code></div>')
        else:
            action = ""      # the form below IS the action for an API key

        # One set of buttons per CONNECTION, not per provider. A client with two
        # WordPress installs had one Disconnect button between them, and it
        # would have severed whichever row the query happened to return first.
        def _buttons(site: str = "") -> str:
            hidden = (f'<input type="hidden" name="key" value="{_esc(key)}">'
                      f'<input type="hidden" name="tenant" value="{_esc(tenant)}">'
                      f'<input type="hidden" name="provider" value="{_esc(r["provider"])}">'
                      f'<input type="hidden" name="site" value="{_esc(site)}">')
            out = ""
            if r["kind"] == "api_key":
                # store() verifies once and nothing checked again, so a rotated
                # or revoked key read "connected" forever off a last_verified
                # date from whenever it was pasted.
                out += (f'<form method="post" action="/admin/connect_test" '
                        f'class="inl">{hidden}<button class="sec">Re-check'
                        f'</button></form>')
            out += (f'<form method="post" action="/admin/connect_revoke" '
                    f'class="inl">{hidden}<button class="sec">Disconnect'
                    f'</button></form>')
            return out

        conns = [c for c in r["connections"] if c["state"] != "revoked"]
        if r["site_scoped"] and conns:
            # Each install named and addressed separately. The site IS the
            # identity here, so showing the provider once with a single state
            # would be describing two things with one word.
            rows_html = "".join(
                f'<div class="conn-site"><span class="mut">'
                f'{_esc(c["site"] or "(no site recorded)")}</span> '
                f'<span class="chip {"on" if c["state"] == "active" else "off"}">'
                f'{_esc("connected" if c["state"] == "active" else c["state"])}'
                f'</span>'
                + (f'<span class="when">checked {_esc(c["last_verified"])}</span>'
                   if c["last_verified"] else "")
                + f'<span class="row">{_buttons(c["site"])}</span></div>'
                for c in conns)
            action += rows_html
        elif state in ("connected", "failed"):
            action += _buttons()

        # The form for an API-key provider, with that provider's own
        # click-by-click instructions above it. Those `howto` strings were
        # written for the client connect page and shown nowhere else, so the
        # owner — the person most likely to be connecting an account — was the
        # one reading a runbook instead.
        form = ""
        spec = cred.PROVIDERS.get(r["provider"]) or {}
        if r["kind"] == "api_key":
            extra = "".join(
                f'<label>{_esc(desc)}</label>'
                f'<input name="{_esc(f)}" placeholder="{_esc(desc)}" required>'
                for f, desc in (spec.get("also") or {}).items())
            starts = spec.get("starts") or ""
            hint = (f'<div class="when">It begins with <code>{_esc(starts)}</code>. '
                    f'Checked against the live API before anything is saved — '
                    f'a key with a trailing space is refused here, not silently '
                    f'a week later.</div>' if starts else
                    '<div class="when">Checked against the live API before '
                    'anything is saved.</div>')
            if r["site_scoped"]:
                # "Replace" is wrong for a provider that can hold several: the
                # client is adding their second landing-page install, not
                # overwriting the first, and a summary saying Replace is how
                # somebody decides not to click it.
                label = (f"Connect another {r['name']} site"
                         if conns else f"Connect {r['name']}")
            else:
                label = (f"Replace {r['name']}" if state == "connected"
                         else f"Connect {r['name']}")
            form = f"""
            <details class="cform">
              <summary>{_esc(label)}</summary>
              <div class="note">{_esc(spec.get('howto', ''))}</div>
              <form method="post" action="/admin/connect_save" class="f">
                <input type="hidden" name="key" value="{_esc(key)}">
                <input type="hidden" name="tenant" value="{_esc(tenant)}">
                <input type="hidden" name="provider" value="{_esc(r['provider'])}">
                <label>{_esc(spec.get('field', 'Key'))}</label>
                <input name="secret" type="password" autocomplete="off"
                       placeholder="{_esc(spec.get('field', 'Key'))}" required>
                {extra}
                {hint}
                <div class="row"><button>Connect</button></div>
              </form>
            </details>"""

        out.append(f"""
        <div class="conn">
          <div><strong>{_esc(r['name'])}</strong> {chip}{detail}</div>
          <div class="row">{action}</div>
          {form}
        </div>""")

    return f"""
    <details class="conns" open>
      <summary>Connections</summary>
      {''.join(out)}
      <form method="post" action="/admin/connect_link" class="row mklink">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="tenant" value="{_esc(tenant)}">
        <input name="label" placeholder="who it is for, e.g. Jane" required>
        <input name="days" value="30" size="3" title="days until it expires">
        <button class="sec">Create a connect link</button>
        <span class="mut">for the client to connect their own accounts</span>
      </form>
    </details>"""


def _field(t, key: str, name: str) -> str:
    title, howto = FIELD_HELP.get(name, (name, ""))
    raw = getattr(t, name, None)
    val = json.dumps(raw) if isinstance(raw, (dict, list)) else (raw or "")
    return f"""
    <form class="f" method="get" action="/admin/tenant_set">
      <input type="hidden" name="key" value="{_esc(key)}">
      <input type="hidden" name="tenant" value="{_esc(t.key)}">
      <input type="hidden" name="field" value="{name}">
      <label>{name}</label>
      <div class="what">{_esc(title)}</div>
      <input name="value" value="{_esc(val)}" placeholder="empty">
      <div class="row"><button>Save</button></div>
      <details><summary>How do I get this?</summary><p>{_esc(howto)}</p></details>
    </form>"""


def render(key: str, msg: str = "", err: str = "", link: str = "") -> str:
    rows = tenants.all_tenants(include_paused=True)
    if not rows:
        body = ('<div class="note">No accounts yet. Run '
                '<code>/admin/register_owner</code> first — it seeds the five.</div>')
    else:
        body = ""
        for t in rows:
            caps = tenants.capabilities(t.key)
            missing = [c for c, ok in caps.items() if not ok]
            fields = "".join(_field(t, key, f) for f in
                             ("gmail_alias", "shopify_store", "esp", "cms",
                              "ads", "analytics", "crm", "design", "systems"))
            body += f"""
            <div class="card">
              <div class="head">
                <h2>{_esc(t.name)}</h2>
                <code>{_esc(t.key)}</code>
                <span class="mut">{_esc(t.kind)} · {_esc(t.domain) or 'no domain'}</span>
              </div>
              <div class="chips">{_chips(caps)}</div>
              <div class="mut">Missing: {', '.join(missing) or 'nothing — fully wired'}</div>
              <div class="row">
                <a href="/admin/verify?key={_esc(key)}&amp;tenant={_esc(t.key)}"><button class="sec" type="button">Test connections</button></a>
                <span class="mut">chips show what is <em>configured</em>; this calls each one to see if it <em>works</em></span>
              </div>
              {_connections(t.key, key)}
              <div class="grid">{fields}</div>
            </div>"""

    note = f'<div class="ok">{_esc(msg)}</div>' if msg else ""
    if err:
        note += f'<div class="note">{_esc(err)}</div>'
    if link:
        note += f"""
        <div class="ok">
          <div>Connect link — send this to the client. It reaches one account
          and connects nothing else.</div>
          <input class="copy" value="{_esc(link)}" readonly onclick="this.select()">
        </div>"""

    return _shell(key, "accounts", "Accounts", f"""
<div>
  <h1>Accounts</h1>
  <p class="mut">The fields on each card are <strong>keys into</strong> credential
  dictionaries or env-var names — never secrets. The secrets themselves are
  either in the Render env group or, for anything a client connected
  themselves, encrypted in the database and shown here only as a state.</p>
</div>
{note}

<div class="card">
  <div class="head"><h2>Add an account</h2></div>
  <form method="get" action="/admin/tenant_add" class="grid">
    <input type="hidden" name="key" value="{_esc(key)}">
    <div class="f"><label>tenant key</label>
      <div class="what">Short and lowercase — you'll type it often</div>
      <input name="tenant" placeholder="acme" required></div>
    <div class="f"><label>name</label>
      <div class="what">Shown in /clients</div>
      <input name="name" placeholder="Acme Co" required></div>
    <div class="f"><label>domain</label>
      <div class="what">Used for enrichment</div>
      <input name="domain" placeholder="acme.com"></div>
    <div class="f"><label>kind</label>
      <div class="what">'own' for your businesses, 'client' otherwise</div>
      <select name="kind"><option value="client">client</option>
        <option value="own">own</option></select>
      <div class="row"><button>Create</button></div></div>
  </form>
</div>

<div class="card">
  <div class="head"><h2>Give someone bot access</h2></div>
  <p class="mut">They message the bot first — it replies with their chat id
  because it doesn't recognise them. Paste that id here.</p>
  <form method="get" action="/admin/user_add" class="grid">
    <input type="hidden" name="key" value="{_esc(key)}">
    <div class="f"><label>chat id</label>
      <div class="what">From their first message to the bot</div>
      <input name="chat_id" placeholder="123456789" required></div>
    <div class="f"><label>name</label><div class="what">For your reference</div>
      <input name="name" placeholder="Ellis"></div>
    <div class="f"><label>role</label>
      <div class="what">client and freelancer are pinned to one account</div>
      <select name="role"><option>client</option><option>freelancer</option>
        <option>owner</option></select></div>
    <div class="f"><label>tenant</label>
      <div class="what">Required unless owner</div>
      <input name="tenant" placeholder="coverings">
      <div class="row"><button>Grant access</button></div></div>
  </form>
  <div class="note"><strong>Not yet.</strong> Ops commands are scoped correctly, but
  free-text questions fall through to an agent that is not tenant-scoped. Hold off
  on client access until reporting and agent scoping land.</div>
</div>

{body}

<p class="mut">Saving reloads to a JSON response — hit back to return here.
Changes take effect immediately; no redeploy.</p>
""")


# ---------------------------------------------------------------------------
# Systems tab
# ---------------------------------------------------------------------------

def _rung(current: str) -> str:
    at = systems.AUTONOMY.index(current if current in systems.AUTONOMY else "shadow")
    steps = "".join(
        f'<span class="step {"at" if i == at else ("done" if i < at else "")}">'
        f'{r.replace("_", " ")}</span>'
        for i, r in enumerate(systems.AUTONOMY))
    return (f'<div class="rung">{steps}</div>'
            f'<div class="mut">{_esc(systems.AUTONOMY_MEANING.get(current, ""))}</div>')


def _contract_form(key: str, row) -> str:
    fields = "".join(f"""
      <div class="f"><label>{label}</label>
        <div class="what">{_esc(hint)}</div>
        <textarea name="{f}" rows="2" placeholder="empty">{_esc(getattr(row, f, "") or "")}</textarea>
      </div>""" for f, label, hint in systems.CONTRACT)
    return f"""
    <details><summary>The contract — 8 questions a system answers before it runs</summary>
      <form method="get" action="/admin/system_set" style="margin-top:10px">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="id" value="{_esc(row.id)}">
        <div class="sysgrid">{fields}</div>
        <div class="row" style="margin-top:10px"><button>Save contract</button>
        <span class="mut">A system can't go live until every one is filled.</span></div>
      </form>
    </details>"""


def _thread(key: str, row) -> str:
    msgs = systems.notes(row.tenant, row.key)
    if msgs:
        body = "".join(f"""
        <div class="msg"><div>{_esc(m.content)}</div>
          <div class="when">{m.created_at:%b %d, %H:%M} ·
            <a href="/admin/system_note?key={_esc(key)}&amp;drop={_esc(m.id)}">archive</a></div>
        </div>""" for m in msgs)
    else:
        body = ('<p class="mut">Nothing yet. Corrections you write here are injected '
                'into this system\'s drafting prompt — and only this one.</p>')
    return f"""
    <details><summary>Thread — guidance and corrections ({len(msgs)})</summary>
      <div class="thread" style="margin-top:10px">{body}</div>
      <form method="get" action="/admin/system_note" style="margin-top:12px">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="id" value="{_esc(row.id)}">
        <div class="f"><label>guidance</label>
          <div class="what">Prose. Shapes how this system drafts — it does not enforce.</div>
          <textarea name="text" rows="2" placeholder="Lead with the number, not the greeting."></textarea>
          <div class="row"><button>Add to thread</button></div>
        </div>
      </form>
      <form method="get" action="/admin/system_rule" style="margin-top:8px">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="id" value="{_esc(row.id)}">
        <div class="f"><label>hard rule</label>
          <div class="what">A phrase that must never appear. Enforced by the validator,
          which is code and fails closed — use this for anything that must ALWAYS hold.</div>
          <input name="phrase" placeholder="handcrafted">
          <div class="row"><button>Make it a rule</button></div>
        </div>
      </form>
    </details>"""


def _runs(row, total: int) -> str:
    rows = systems.runs(row.id, limit=8)
    if not rows:
        return ('<details><summary>Runs (0)</summary>'
                '<p class="mut" style="margin-top:10px">Nothing has run yet.</p></details>')
    lines = "".join(f"""
      <div class="msg"><div><code>{_esc(r.stage)}</code>
        {_esc(r.decision or "")} {_esc((r.blocked_on or [""])[0] if r.stage == "blocked" else "")}</div>
        <div class="when">{r.created_at:%b %d, %H:%M} · {_esc(r.trigger or "")}</div></div>"""
        for r in rows)
    more = f" — showing the last {len(rows)}" if total > len(rows) else ""
    return (f'<details><summary>Runs ({total}){more}</summary>'
            f'<div class="thread" style="margin-top:10px">{lines}</div></details>')


def _system_card(key: str, row) -> str:
    r = systems.ready(row)
    st = systems.stats(row.id)
    nxt = systems.can_promote(row)

    # THREE states, not two. A system that cannot reach its connection is
    # blocked; a system missing knowledge or a contract now PRODUCES, thinly,
    # and calling that "blocked" would have the console contradicting the
    # worker -- which is running it every tick.
    if r["ready"]:
        gate = ('<div class="ok">Ready. Everything it needs is connected and '
                'the contract is complete.</div>')
    elif not r["can_produce"]:
        items = "".join(f"<li>{_esc(b)}</li>" for b in r["impossible"])
        gate = ('<div class="note"><strong>Blocked &mdash; it cannot run at '
                'all.</strong><ul class="bl">' + items + '</ul>'
                '<div class="mut">A connection is missing. Nothing else stops '
                'a system producing.</div></div>')
    else:
        items = "".join(f"<li>{_esc(b)}</li>" for b in r["thin"])
        gate = ('<div class="note"><strong>Running thin.</strong> It produces, '
                'and says on every output what it was working without:'
                '<ul class="bl">' + items + '</ul>'
                '<div class="mut">These gate GOING LIVE, not producing. Each '
                'one is filed as a knowledge task when a run hits it.</div>'
                '</div>')

    if nxt["can"]:
        promo = (f'<a href="/admin/system_promote?key={_esc(key)}&amp;id={_esc(row.id)}">'
                 f'<button type="button">Promote to {_esc(nxt["target"].replace("_", " "))}</button></a>')
    elif nxt["target"]:
        promo = f'<span class="mut">Next rung ({_esc(nxt["target"].replace("_", " "))}): {_esc(nxt["why"])}</span>'
    else:
        promo = '<span class="mut">Top of the ladder.</span>'

    live = ""
    if row.status != "live" and r["ready"]:
        live = (f'<a href="/admin/system_set?key={_esc(key)}&amp;id={_esc(row.id)}&amp;status=live">'
                f'<button type="button">Switch on</button></a>')
    elif row.status == "live":
        live = (f'<a href="/admin/system_set?key={_esc(key)}&amp;id={_esc(row.id)}&amp;status=paused">'
                f'<button class="sec" type="button">Pause</button></a>')

    return f"""
    <div class="card">
      <div class="head">
        <h3>{_esc(row.name)}</h3>
        <code>{_esc(row.key)}</code>
        <span class="chips">
          <span class="chip {'on' if row.status == 'live' else 'off'}">{_esc(row.status)}</span>
          <span class="chip {'on' if row.autonomy == 'auto' else 'off'}">{_esc(row.autonomy)}</span>
        </span>
      </div>
      <div class="mut">{_esc(systems.spec(row.key)["does"])}</div>
      {gate}
      {_rung(row.autonomy or "shadow")}
      <div class="stat">
        <span><b>{st['total']}</b> runs</span>
        <span><b>{st['approved']}</b> approved</span>
        <span><b>{st['edited']}</b> edited</span>
        <span><b>{st['denied']}</b> denied</span>
        <span><b>{st['blocked']}</b> blocked</span>
      </div>
      <div class="row">{live}{promo}</div>
      {_contract_form(key, row)}
      {_thread(key, row)}
      {_runs(row, st['total'])}
    </div>"""


def render_systems(key: str, tenant: str = "") -> str:
    rows = systems.all_systems()

    if not rows:
        body = ('<div class="note">No systems yet. '
                '<a href="/admin/systems_seed?key=' + _esc(key) + '">Adopt the ones already '
                'named on each account</a> — it reads <code>Tenant.systems</code> and '
                'creates a row for each, with an empty contract.</div>')
    else:
        by_tenant: dict[str, list] = {}
        for r in rows:
            by_tenant.setdefault(r.tenant, []).append(r)
        body = ""
        for tkey, group in by_tenant.items():
            t = tenants.get(tkey)
            cards = "".join(_system_card(key, r) for r in group)
            live = sum(1 for r in group if r.status == "live")
            body += f"""
            <div>
              <div class="head" style="margin-bottom:12px">
                <h2>{_esc(t.name if t else tkey)}</h2>
                <code>{_esc(tkey)}</code>
                <span class="mut">{live} of {len(group)} live</span>
              </div>
              {cards}
            </div>"""

    backlog = systems.blocked_reasons()
    backlog_html = ""
    if backlog:
        items = "".join(f"<li><b>{n}×</b> {_esc(reason)}</li>" for reason, n in backlog[:10])
        backlog_html = f"""
        <div class="card">
          <div class="head"><h2>What the systems refused on</h2></div>
          <p class="mut">Last 30 days, most frequent first. This is the knowledge-base
          backlog ranked by how often each gap actually cost an output — fix from the top.</p>
          <ul class="bl">{items}</ul>
        </div>"""

    # The installer, per account. The old version was two dropdowns and a
    # button: it listed every system whether or not it was already installed,
    # and said nothing about what any of them needed — so installing was a
    # guess, and the refusal only arrived afterwards on the system's own card.
    all_t = tenants.all_tenants(include_paused=True)
    tenant = tenant or (all_t[0].key if all_t else "")
    picker = "".join(
        f'<a class="{"on" if t.key == tenant else ""}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab=systems&amp;tenant={_esc(t.key)}">'
        f'{_esc(t.name)}</a>' for t in all_t)

    def _pre_chip(i: dict) -> str:
        mark = "✓" if i["met"] else "✗"
        note = f' <span class="mut">{_esc(i["note"])}</span>' if i["note"] else ""
        return (f'<span class="pre {"yes" if i["met"] else "no"}">{mark} '
                f'{_esc(i["name"])}{note}</span>')

    cards = ""
    for p in (systems.installable(tenant) if tenant else []):
        chips = "".join(_pre_chip(i) for i in p["items"]) or (
            '<span class="pre yes">✓ nothing required</span>')
        if p["installed"]:
            action = (f'<span class="mut">installed &middot; '
                      f'{_esc(p["status"] or "designed")} &middot; '
                      f'{_esc(p["autonomy"] or "shadow")}</span>')
        elif p["ready"]:
            action = (f'<a class="btn" href="/admin/system_add?key={_esc(key)}'
                      f'&amp;tenant={_esc(tenant)}&amp;system={_esc(p["key"])}">'
                      f'Install</a>')
        else:
            # Installable anyway, and deliberately so: a system in shadow with
            # a gap is a useful thing to look at, and blocking the button would
            # hide the very list that says what to go and fix.
            what = ", ".join(i["name"] for i in p["missing"])
            action = (f'<a class="btn sec" href="/admin/system_add?key={_esc(key)}'
                      f'&amp;tenant={_esc(tenant)}&amp;system={_esc(p["key"])}">'
                      f'Install anyway</a>'
                      f'<div class="when">will not run until: {_esc(what)}</div>')
        cards += f"""
        <div class="inst {"done" if p["installed"] else ("ok" if p["ready"] else "gap")}">
          <div class="insthead">
            <b>{_esc(p["name"])}</b>
            <code>{_esc(p["key"])}</code>
            <span class="grow"></span>
            {action}
          </div>
          <div class="when">{_esc(p["does"])}</div>
          <div class="prereqs">{chips}</div>
        </div>"""

    return _shell(key, "systems", "Systems", f"""
<div>
  <h1>Systems</h1>
  <p class="mut">One row per installed pipeline. A system is not on because it has a
  name — it is on when its contract is answered, its connections work, and the
  knowledge base can ground it. Everything below refuses in public rather than
  guessing in private.</p>
</div>

{backlog_html}

<div class="card">
  <div class="head"><h2>Install a system</h2></div>
  <div class="picker">{picker}</div>
  <p class="mut">Everything in the catalogue for this account, with what each one
  needs and whether it has it. <b>✓</b> is wired or written, <b>✗</b> is not.
  A system starts in <em>designed / shadow</em> — it records and sends nothing —
  so the 8-part contract comes after installing, while you are looking at it.</p>
  {cards}
</div>

{body}

<p class="mut">Guidance shapes drafting. Rules are enforced by code. When a correction
matters every single time, make it a rule — a prompt that usually obeys is not a control.</p>
""")


# ---------------------------------------------------------------------------
# Knowledge tab
#
# The KB had no read surface at all — `/kb` returned four counts, which tells
# you a claim exists but never which one, or whether it is any good. Everything
# the generators will be grounded in is shown here in full, because proof you
# cannot read is proof you cannot trust.
# ---------------------------------------------------------------------------

def _kb_add_form(key: str, tenant: str, step_id: str, label: str,
                 hint: str, rows: int = 2) -> str:
    return f"""
    <form class="f" method="get" action="/admin/kb_add">
      <input type="hidden" name="key" value="{_esc(key)}">
      <input type="hidden" name="tenant" value="{_esc(tenant)}">
      <input type="hidden" name="step" value="{step_id}">
      <label>{_esc(label)}</label>
      <div class="what">{_esc(hint)}</div>
      <textarea name="text" rows="{rows}" placeholder="{_esc(hint)}"></textarea>
      <div class="row"><button>Add</button></div>
    </form>"""


def _kb_list(title: str, items: list[str], empty: str, open: bool = False) -> str:
    if not items:
        return (f'<details class="sec"><summary>{_esc(title)} (0)</summary>'
                f'<p class="mut" style="margin-top:10px">{_esc(empty)}</p></details>')
    body = "".join(f'<div class="msg">{i}</div>' for i in items)
    return (f'<details class="sec"{" open" if open else ""}>'
            f'<summary>{_esc(title)} ({len(items)})</summary>'
            f'<div class="thread">{body}</div></details>')


# --- value formatters -------------------------------------------------------
#
# Every one of these renders "not set" differently from "set to nothing useful",
# because the whole premise of the KB is that a missing field blocks a pipeline.
# A blank space where a value should be tells the reader nothing at all.

def _mut(msg: str) -> str:
    return f'<span class="mut">{_esc(msg)}</span>'


def _kv(pairs: list[tuple[str, str]]) -> str:
    """Label/value rows. Pairs whose value is empty are dropped by the caller,
    never silently — an absent field gets an explicit 'not set' value instead."""
    body = "".join(f"<dt>{_esc(k)}</dt><dd>{v}</dd>" for k, v in pairs)
    return f'<dl class="kv">{body}</dl>'


def _words(items, empty: str = "not set") -> str:
    """A list of short values. A bare string is treated as one value, not as a
    list of characters — `voice.do_say` has no writer that normalises it, and
    rendering "d, i, r, e, c, t" would look like corrupted data rather than a
    shape mismatch."""
    if isinstance(items, str):
        items = [items] if items.strip() else []
    items = [str(i) for i in (items or []) if str(i).strip()]
    return _esc(", ".join(items)) if items else _mut(empty)


def _attr_chips(d: dict) -> str:
    if not d:
        return ""
    return '<div class="chips">' + "".join(
        f'<span class="chip nb">{_esc(str(k).replace("_", " "))} '
        f'<b>{_esc(v)}</b></span>' for k, v in d.items()) + "</div>"


def _date(v) -> str:
    if not v:
        return ""
    try:
        return db.as_utc(v).date().isoformat()
    except Exception:
        return str(v)[:10]


def _selection_line(cfg: dict) -> str:
    """How this tenant's catalogue gets ranked — the thing that decided a
    200-seat room was offered for 220 guests. It belongs on screen."""
    if not cfg:
        return _mut("not set — falls back to keyword relevance over every type")
    bits = []
    if cfg.get("primary_type"):
        bits.append(f'ranks <code>{_esc(cfg["primary_type"])}</code>')
    for m in cfg.get("modes") or []:
        mode = m.get("mode", "")
        if not mode:
            continue
        detail = ""
        if m.get("requirement"):
            detail = f' on <code>{_esc(m["requirement"])}</code>'
            attrs = m.get("attributes") or {}
            if attrs:
                detail += " → " + ", ".join(
                    f'{_esc(k)}: <code>{_esc(v)}</code>' for k, v in attrs.items())
        bits.append(f"<b>{_esc(mode)}</b>{detail}")
    return " · ".join(bits) if bits else _mut("not set")


def _approval_policy_html(policy: dict) -> str:
    """Which assets go out unattended and which need a signature. An empty policy
    is not 'no policy' — it decides behaviour, so it is shown either way."""
    if not policy:
        return ('<div class="mut">Approval policy not set — nothing is marked '
                'auto-publishable, so everything waits for a human.</div>')
    auto = policy.get("auto_publish") or []
    signoff = policy.get("requires_signoff") or []
    return _kv([
        ("auto publish", _words(auto, "nothing — all output waits for approval")),
        ("needs signoff", _words(signoff, "nothing listed")),
    ])


def _next_steps_line(steps: dict) -> str:
    """What the tenant asks for at the end of a draft. Silently emptied once by
    a migration, which produced blank asks on every agency brief and was visible
    nowhere but the rendered output."""
    if not steps:
        return _mut("not set — every draft ends with a blank ask")
    return "<br>".join(
        f'<code>{_esc(stage)}</code> {_esc((v or {}).get("ask", ""))}'
        for stage, v in steps.items())


def render_kb(key: str, tenant: str = "", err: str = "") -> str:
    rows = tenants.all_tenants(include_paused=True)
    tenant = tenant or (rows[0].key if rows else "")
    t = tenants.get(tenant)

    picker = "".join(
        f'<a class="{"on" if r.key == tenant else ""}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab=kb&amp;tenant={_esc(r.key)}">'
        f'{_esc(r.name)}</a>' for r in rows)

    if not t:
        return _shell(key, "kb", "Knowledge",
                      '<div class="note">No accounts yet. Run '
                      '<code>/admin/register_owner</code> first.</div>')

    c = kb.completeness(tenant)
    gaps = kb.gaps(tenant)
    b = kb.brand(tenant)
    voice = (b.voice or {}) if b else {}

    if gaps:
        nxt = gaps[0]
        ask = f"""
        <div class="card">
          <div class="head"><h2>Next most useful question</h2>
            <span class="chip off">{len(gaps)} missing</span></div>
          <p><strong>{_esc(nxt['q'])}</strong></p>
          <p class="mut">{_esc(nxt['hint'])}</p>
          <form class="f" method="get" action="/admin/kb_add">
            <input type="hidden" name="key" value="{_esc(key)}">
            <input type="hidden" name="tenant" value="{_esc(tenant)}">
            <input type="hidden" name="step" value="{nxt['id']}">
            <textarea name="text" rows="2" placeholder="{_esc(nxt['hint'])}"></textarea>
            <div class="row"><button>Answer</button>
            <span class="mut">or send <code>/next</code> to the bot and reply there</span></div>
          </form>
        </div>"""
    else:
        ask = ('<div class="card"><div class="head"><h2>Complete</h2>'
               '<span class="chip on">ready</span></div>'
               '<p class="mut">Everything the pipeline requires is present. More proof '
               'is still better than less — keep adding claims as they are earned.</p></div>')

    banned = (b.banned_claims or []) if b else []
    banned_html = "".join(f'<span class="chip off">{_esc(p)}</span>' for p in banned) \
        or '<span class="mut">None — the validator has nothing to enforce.</span>'

    # --- claims, split by whether they can actually be used ------------------
    inv = kb.claim_inventory(tenant)

    def _claim_msg(r, note: str = "", cls: str = "") -> str:
        meta = " · ".join(x for x in [
            _esc(r.strength or ""), _esc(r.proof_type or ""),
            f"verified {_date(r.verified_at)}" if r.verified_at else "",
            f"expires {_date(r.expires_at)}" if r.expires_at else "",
        ] if x)
        tags = " ".join(r.situations or []) or "untagged — can never be selected"
        return (f'<div class="msg {cls}">'
                f"<div>{_esc(r.claim)}</div>"
                + (f'<div class="when"><strong>{_esc(r.evidence)}</strong></div>'
                   if r.evidence else
                   '<div class="when"><span class="mut">no evidence recorded</span></div>')
                + f'<div class="when"><code>{_esc(tags)}</code></div>'
                + f'<div class="when">{meta}{" · " if meta else ""}'
                f'{_esc(r.source or "source not recorded")}</div>'
                + (f'<div class="when"><b>{_esc(kb.usage_rule(r.proof_type))}</b></div>'
                   if kb.usage_rule(r.proof_type or "") else "")
                + (f'<div class="when"><b>{_esc(note)}</b></div>' if note else "")
                + "</div>")

    def _claim_block(title: str, rows_, empty: str, note: str = "",
                     cls: str = "", open_: bool = False) -> str:
        if not rows_:
            return (f'<details class="sec"><summary>{_esc(title)} (0)</summary>'
                    f'<p class="mut" style="margin-top:10px">{_esc(empty)}</p></details>')
        body = "".join(_claim_msg(r, note, cls) for r in rows_)
        return (f'<details class="sec"{" open" if open_ else ""}>'
                f'<summary>{_esc(title)} ({len(rows_)})</summary>'
                f'<div class="thread">{body}</div></details>')

    claims_html = (
        _claim_block("Claims — selectable", inv["selectable"],
                     "No usable proof. Any draft that needs a number is blocked.")
        + _claim_block("Claims — awaiting review", inv["pending"],
                       "Nothing submitted for review.",
                       "not selectable until approved", "gone")
        + _claim_block("Claims — expired", inv["expired"],
                       "Nothing has gone stale.",
                       "past its expiry date, so selection skips it", "gone")
        + _claim_block("Claims — retired", inv["retired"],
                       "Nothing retired.", "withdrawn from selection", "gone"))

    aud_html = _kb_list("Audiences", [
        f"<div><strong>{_esc(r.name)}</strong> <code>{_esc(r.key)}</code></div>"
        + _kv([("pains", _words(r.pains, "none recorded")),
               ("their words", _words(r.vocabulary,
                                      "none — selection cannot recognise this buyer")),
               ("buying trigger", _esc(r.buying_trigger) or _mut("not set")),
               ("decides in", _esc(r.decision_timeline) or _mut("not set"))]
              + ([("notes", _esc(r.notes))] if r.notes else []))
        for r in kb.audiences(tenant)],
        "No segments. Selection cannot narrow to a buyer.")

    # `any_entity` because this page's job is to show what the account knows,
    # not what selection would pick. Without it the list was the brand-wide
    # subset presented as the whole, and every product-scoped answer was
    # invisible here.
    # Situations doing one job. Reported here rather than merged anywhere,
    # because a merge rewrites what every claim under both tags can answer.
    overlaps = kb.situation_overlaps(tenant)
    over_html = ""
    if overlaps:
        rowsh = "".join(f"""
        <div class="conn">
          <div><code>{_esc(o['keep'])}</code> and <code>{_esc(o['drop'])}</code>
            <span class="chip off">{_esc(o['basis'].replace('_', ' '))}</span>
            <div class="mut">{_esc(o['why'])} &middot;
              {o['rows'].get(o['keep'], 0)} and {o['rows'].get(o['drop'], 0)} rows</div>
          </div>
          <form method="post" action="/admin/merge_situation" class="inl"
                onsubmit="return confirm('Fold {_esc(o['drop'])} into {_esc(o['keep'])}? Every row tagged the first will be retagged.')">
            <input type="hidden" name="tenant" value="{_esc(tenant)}">
            <input type="hidden" name="keep" value="{_esc(o['keep'])}">
            <input type="hidden" name="drop" value="{_esc(o['drop'])}">
            <button class="sec">Fold into {_esc(o['keep'])}</button>
          </form>
        </div>""" for o in overlaps[:8])
        over_html = f"""
        <div class="card danger">
          <div class="head"><h2>These situations may be one situation</h2></div>
          <p class="mut">Two tags a person would answer with the same proof are
          one tag. Split across both, neither accumulates the approved examples
          that make tagging work, and selection reaches half the evidence it
          should. Nothing is merged automatically.</p>
          {rowsh}
          <p class="mut">A pair that means the same thing in different words
          will not appear here &mdash; measured on the real case, the two tags
          shared no trigger words and scored 0.25 on their descriptions. Run
          <code>/admin/vocabulary?tenant={_esc(tenant)}&amp;model=1</code> for the
          pass that can see those.</p>
        </div>"""

    obj_rows = kb.objections(tenant, any_entity=True)
    obj_cat = {e.key: e.name for e in kb.entities(tenant, available_only=False)}

    def _obj(r) -> str:
        # The scope is the first thing that has to be readable. An answer true
        # of one product and shown as true of the catalogue is not a display
        # bug — it is the system asserting something false about every other
        # thing the account sells.
        if r.entity_key:
            scope = (f'true of <code>{_esc(obj_cat.get(r.entity_key, r.entity_key))}'
                     f'</code> only')
            flag = ""
        else:
            scope = "<strong>true of everything they sell</strong>"
            # A machine-origin row that nobody scoped never had that decided.
            flag = ('<div class="note">Nothing has said what this is true of, '
                    'so it is being claimed of the whole catalogue. If it came '
                    'off one product page, scope it — approving a product '
                    'answer brand-wide is how a customer is told the wrong '
                    'thing about a different item.</div>'
                    if kb.scope_unconfirmed(r) or (r.origin or "") == "crawl"
                    else "")
        return (
            f'<div><strong>{_esc(r.objection)}</strong>'
            + (' <span class="chip off">escalate</span>'
               if (r.escalate or "").lower() == "yes" else "")
            + "</div>"
            + f"<div>{_esc(r.response)}</div>"
            + f'<div class="when">{scope}'
            + (f" · segment <code>{_esc(r.audience_key)}</code>"
               if r.audience_key else " · any segment")
            + (f" · from {_esc(r.origin)}" if r.origin else "")
            + (f" · paired proof <code>{_esc(r.claim_id)}</code>"
               if r.claim_id else "")
            + "</div>" + flag
            + f"""
            <form class="f" method="post" action="/admin/objection_edit">
              <input type="hidden" name="row_id" value="{_esc(r.id)}">
              <input type="hidden" name="tenant" value="{_esc(tenant)}">
              <label>True of &mdash; blank claims it of everything they sell</label>
              <input name="entity_key" list="objents"
                     value="{_esc(r.entity_key or '')}"
                     placeholder="leave blank only if it really is brand-wide">
              <div class="row"><button class="sec">Save scope</button></div>
            </form>""")

    obj_html = over_html + _kb_list("Objections", [_obj(r) for r in obj_rows],
                        "None. This is human-authored and it is half of the "
                        "intake.")
    obj_html += ('<datalist id="objents">'
                 + "".join(f'<option value="{_esc(k)}">{_esc(v)}</option>'
                           for k, v in obj_cat.items()) + "</datalist>")

    ents = kb.entities(tenant, available_only=False)
    ent_html = _kb_list("Things they sell", [
        f'<div><strong>{_esc(r.name)}</strong> <code>{_esc(r.type)}</code> '
        f"{_esc(r.price) or _mut('no price')}"
        + ("" if (r.availability or "available") == "available"
           else f' <span class="chip off">{_esc(r.availability)}</span>')
        + "</div>"
        + f'<div class="when">{_esc(r.description) or _mut("no description")}</div>'
        + _attr_chips(r.attributes or {})
        + f'<div class="when"><code>{_esc(r.key)}</code> · '
        + _esc(r.source or "source not recorded")
        + (f" · verified {_date(r.verified_at)}" if r.verified_at else "")
        + (f" · goes stale after {_esc(r.freshness_days)} days"
           if r.freshness_days else "")
        + "</div>"
        for r in ents],
        "Nothing catalogued. Selection has nothing to offer.")

    # --- grouping, in the console rather than one URL per product ------------
    #
    # `kb.assign_to_group` has existed since the scope work with no caller. The
    # only manual path was one `/admin/entity_group?...` GET per entity, which
    # for a forty-item range is forty URLs pasted by hand — so the path the
    # collection import deliberately leaves to a person was one nobody could
    # actually walk.
    groups = [r for r in ents if (r.type or "") == "collection"]
    if groups and len(ents) > len(groups):
        opts = "".join(f'<option value="{_esc(g.key)}">{_esc(g.name)}</option>'
                       for g in groups)
        picks = "".join(
            f'<label class="pick"><input type="checkbox" name="entity_keys" '
            f'value="{_esc(r.key)}" form="grp"> {_esc(r.name)}</label>'
            for r in ents if (r.type or "") != "collection")
        ent_html += f"""
    <div class="anchor" id="groups"></div>
    <div class="card">
      <div class="head"><h2>Put things in a group</h2></div>
      <p class="mut">A claim filed against a group is true of every member and
      is inherited silently, so this is deliberately a decision rather than an
      import. Membership is <b>additive</b> — a white Aqua pitcher can be in its
      range, its material and its type at once, and adding one never removes
      another.</p>
      <form id="grp" method="post" action="/admin/entity_group"></form>
      <input type="hidden" name="tenant" value="{_esc(tenant)}" form="grp">
      <div class="bulkbar">
        <select name="group" form="grp">{opts}</select>
        <span class="grow"></span>
        <button form="grp">Add selected to this group</button>
      </div>
      <div class="tags">{picks}</div>
    </div>"""

    # --- the tenant's own diagnostic vocabulary ------------------------------
    sits = kb.situation_rows(tenant)
    if sits:
        sit_body = "".join(
            f'<div class="msg"><div><code>{_esc(r.tag)}</code> '
            f'<span class="chip nb">{_esc(r.kind or "problem")}</span></div>'
            f'<div class="when">{_esc(r.description) or _mut("no description")}</div>'
            f'<div class="when">triggers on: '
            + (_esc(", ".join(" ".join(p) for p in (r.patterns or []) if p))
               or _mut("no patterns — diagnosis can never assign this tag"))
            + "</div></div>" for r in sits)
        sit_note = (f'<p class="mut">These {len(sits)} tags are the only ones a claim '
                    f'for {_esc(t.name)} may carry. A claim tagged with anything else '
                    f'is refused on the way in.</p>')
    else:
        sit_body = ""
        sit_note = ('<div class="note">No vocabulary authored, so this account '
                    'silently inherits the agency\'s B2B language — which no venue '
                    'or product enquiry will ever match. Claims tagged in this '
                    'account\'s own words will be refused until tags exist here.</div>')

    # --- gaps the selection loop actually hit --------------------------------
    unk = kb.unknowns(tenant)
    closed = len(kb.unknowns(tenant, status="answered")) + \
        len(kb.unknowns(tenant, status="not_applicable"))
    if unk:
        unk_body = "".join(
            f'<div class="msg"><div><strong>{_esc(r.entity_name or r.entity_key)}</strong> '
            f'— {_esc((r.attribute or "").replace("_", " "))} unknown</div>'
            f'<div class="when">blocked an answer {_esc(r.hits)}× · last asked: '
            f'{_esc(r.asked_for or "—")}</div>'
            f'<form class="f" method="get" action="/admin/kb_unknown" '
            f'style="margin-top:6px">'
            f'<input type="hidden" name="key" value="{_esc(key)}">'
            f'<input type="hidden" name="tenant" value="{_esc(tenant)}">'
            f'<input type="hidden" name="id" value="{_esc(r.id)}">'
            f'<div class="row"><input name="value" placeholder="the value, or n/a">'
            f'<button>Save</button></div></form></div>' for r in unk)
        unk_card = f"""
    <div class="card">
      <div class="head"><h2>Gaps that cost an answer</h2>
        <span class="chip off">{len(unk)} open</span></div>
      <p class="mut">Ranked by how often each one blocked a real enquiry — not every
      empty field, only the ones that lost something. Answering writes the value
      straight onto the item and it becomes matchable immediately.</p>
      <div class="thread">{unk_body}</div>
    </div>"""
    else:
        unk_card = f"""
    <div class="card">
      <div class="head"><h2>Gaps that cost an answer</h2>
        <span class="chip on">none open</span></div>
      <p class="mut">Nothing has been asked for that this account could not answer.
      {closed} gap(s) closed so far.</p>
    </div>"""

    forms = (
        _kb_add_form(key, tenant, "claim", "Add a claim",
                     "claim | evidence | situation tags (spaces)")
        + _kb_add_form(key, tenant, "objection", "Add an objection",
                       "objection | your approved answer")
        + _kb_add_form(key, tenant, "audience", "Add an audience",
                       "key | name | pains (semicolons) | their words (semicolons)")
        + _kb_add_form(key, tenant, "entity", "Add something they sell",
                       "type | key | name | price | description")
        + _kb_add_form(key, tenant, "banned_claims", "Add a hard rule",
                       "phrases the validator must reject, separated by semicolons", 1)
        + _kb_add_form(key, tenant, "positioning", "Set positioning",
                       "one sentence: what they do, and for whom")
        + _kb_add_form(key, tenant, "tone", "Set voice",
                       "three or four words, comma separated", 1))

    warn = f'<div class="note">{_esc(err)}</div>' if err else ""
    return _shell(key, "kb", "Knowledge", f"""
{warn}
<div>
  <h1>Knowledge</h1>
  <p class="mut">Everything the generators are allowed to say, per account. A draft
  may assert nothing that is not on this page — which is why an empty section here
  is a blocked pipeline there, not a cosmetic gap.</p>
</div>

<div class="tabs">{picker}</div>


<div class="card">
  <div class="head">
    <h2>{_esc(t.name)}</h2><code>{_esc(tenant)}</code>
    <span class="chips">
      <span class="chip {'on' if c['ready'] else 'off'}">{'ready' if c['ready'] else 'not ready'}</span>
    </span>
  </div>
  <div class="stat">
    <span><b>{c['counts'].get('claims', 0)}</b> claims</span>
    <span><b>{c['counts'].get('audiences', 0)}</b> audiences</span>
    <span><b>{c['counts'].get('objections', 0)}</b> objections</span>
    <span><b>{c['counts'].get('entities', 0)}</b> entities</span>
    <span><b>{len(sits)}</b> situations</span>
    <span><b>{len(banned)}</b> hard rules</span>
    <span><b>{len(unk)}</b> open gaps</span>
  </div>
  {_kv([
    ("positioning", _esc(b.positioning if b else "") or _mut("not set")),
    ("elevator", _esc((b.elevator or {}).get("sentence", "") if b else "")
                 or _mut("not set")),
    ("tone", _words(voice.get("tone"))),
    ("do say", _words(voice.get("do_say"), "nothing specified")),
    ("never say", _words(voice.get("never_say"), "nothing specified")),
    ("selection", _selection_line(kb.selection_config(tenant))),
    ("next steps", _next_steps_line((b.next_steps or {}) if b else {})),
  ])}
  <div><span class="mut">Hard rules the validator enforces:</span></div>
  <div class="chips">{banned_html}</div>
  {_approval_policy_html((b.approval_policy or {}) if b else {})}
</div>

{ask}

<div class="card">
  <div class="head"><h2>Situations — this account's vocabulary</h2>
    <span class="chip {'on' if sits else 'off'}">{len(sits)} tags</span></div>
  {sit_note}
  <div class="thread">{sit_body}</div>
</div>

<div class="card">
  <div class="head"><h2>What is in there</h2></div>
  {claims_html}
  {aud_html}
  {obj_html}
  {ent_html}
</div>

{unk_card}

<div class="card">
  <div class="head"><h2>Add to {_esc(t.name)}</h2></div>
  <div class="grid">{forms}</div>
</div>

<p class="mut">The same captures work from Telegram — <code>/next</code> asks these
one at a time and reads your reply as the answer.</p>
""", suffix=f"&amp;tenant={tenant}")


# ---------------------------------------------------------------------------
# Client intake — the one surface a client ever sees.
#
# Scoped to a single tenant by an unguessable token. No secret key, no other
# account reachable, no schema on display: one question at a time in the words
# the client already uses. Answers go through the SAME parser as the console and
# the bot, so a fact entered here and one entered by Gomeh land identically —
# which is the property that makes onboarding client #6 cost days, not weeks.
# ---------------------------------------------------------------------------

_INTAKE_CSS = _CSS + """
.w{max-width:680px}
.prog{display:flex;gap:4px;margin-bottom:4px}
.prog i{flex:1;height:4px;border-radius:2px;background:var(--rule)}
.prog i.on{background:var(--ok)}
.q{font:600 1.35rem/1.3 Georgia,serif;margin:0}
.why{font-size:.83rem;color:var(--acc);font-weight:600}
.done{text-align:center;padding:30px 0}
"""


def render_intake(link, tenant, step, done: int, total: int,
                  waiting: list[str], saved: str = "") -> str:
    """One question. No navigation, no schema, no way to reach anything else."""
    t = tenants.get(tenant)
    name = _esc(t.name if t else tenant)

    if step is None:
        body = f"""
        <div class="card done">
          <h1>That's everything — thank you.</h1>
          <p class="mut">We have what we need to start writing for {name}.
          Nothing you sent goes out without being reviewed first.</p>
        </div>"""
    else:
        bars = "".join(f'<i class="{"on" if i < done else ""}"></i>'
                       for i in range(max(total, 1)))
        why = ""
        if waiting:
            why = (f'<div class="why">Needed by: {_esc(", ".join(waiting))}</div>')
        body = f"""
        <div class="card">
          <div class="prog">{bars}</div>
          <div class="mut">Question {done + 1} of {total}</div>
          <h2 class="q">{_esc(step['q'])}</h2>
          <p class="mut">{_esc(step['hint'])}</p>
          {why}
          <form method="get" action="/intake/{_esc(link.token)}">
            <textarea name="answer" rows="3" autofocus
              placeholder="{_esc(step['hint'])}"></textarea>
            <div class="row" style="margin-top:10px">
              <button>Save and continue</button>
              <a href="/intake/{_esc(link.token)}?skip={_esc(step['id'])}"
                 class="mut">skip this one</a>
            </div>
          </form>
        </div>"""

    note = f'<div class="ok">{_esc(saved)}</div>' if saved else ""

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — setup</title><style>{_INTAKE_CSS}</style></head><body><div class="w">
<div>
  <h1>{name}</h1>
  <p class="mut">A few questions so we can write in your voice and never say
  anything you wouldn't. Answer what you can — anything you skip, we'll ask
  again later rather than guess.</p>
</div>
{note}
{body}
<p class="mut">This link is private to {name}. Nothing here is published.</p>
</div></body></html>"""


# ---------------------------------------------------------------------------
# Content tab — what the site says, what the catalogue holds, what is proposed.
#
# The three things behind this tab were built as JSON routes and nothing else,
# which is §2.13 committed again: a compliance report that lives only in the
# response that triggered it has to be re-run to be read twice. The queue of
# proposals matters most — approving one meant finding its id in JSON and
# hand-writing a URL, which nobody does thirty times, and an unreviewed queue
# is worse than no queue because `pending` rows look like progress while being
# invisible to selection.
# ---------------------------------------------------------------------------

_STARTED = {
    "scan": "Scan started. It reads the live site, so give it a minute — "
            "refresh this page and the result will be below.",
    "harvest": "Harvest started. Proposals will appear above when it finishes.",
    "sync": "Catalogue sync started. Refresh in a moment.",
    "email": "Reading sent mail. Only threads triage already bucketed as worth "
             "mining are opened, so this is quick — refresh in a moment.",
}


def _act(key: str, action: str, label: str, tenant: str = "",
         extra: dict | None = None, small: bool = False) -> str:
    """A one-click button that runs something and comes back to this tab."""
    hidden = "".join(
        f'<input type="hidden" name="{_esc(k)}" value="{_esc(v)}">'
        for k, v in {"key": key, "tenant": tenant, "ui": "1",
                     **(extra or {})}.items() if v != "")
    cls = ' class="sec"' if small else ""
    return (f'<form method="get" action="{_esc(action)}" style="display:inline">'
            f'{hidden}<button{cls}>{_esc(label)}</button></form>')


def render_content(key: str, tenant: str = "", started: str = "",
                   err: str = "", msg: str = "") -> str:
    from . import compliance, credentials as cred, kb as kbm

    rows = tenants.all_tenants(include_paused=True)
    tenant = tenant or (rows[0].key if rows else "")
    t = tenants.get(tenant)
    if not t:
        return _shell(key, "content", "Content",
                      '<div class="note">No accounts yet.</div>')

    picker = "".join(
        f'<a class="{"on" if r.key == tenant else ""}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab=content&amp;tenant={_esc(r.key)}">'
        f'{_esc(r.name)}</a>' for r in rows)

    # --- proposals ---------------------------------------------------------
    entries = kbm.proposals(tenant, kind="claim").get("claim", [])
    pending = [e["row"] for e in entries]
    _dupes = {e["row"].id: e for e in entries}
    vocab = sorted(kbm.situations(tenant))
    cat = sorted(((e.key, e.name) for e in
                  kbm.entities(tenant, available_only=False)), key=lambda p: p[1])
    # The option VALUE is what a datalist filters on, so a list of bare slugs
    # could only ever be searched by slug — and a reviewer looking at a claim
    # about the Aqua dinner plate knows "aqua", not `bm-aq-din-25`. Putting
    # both in the value makes either searchable; `kb.resolve_entity_ref` splits
    # it back apart and also accepts a plain key, a plain name, or a unique
    # partial of either.
    catlist = ('<datalist id="ents">'
               + "".join(f'<option value="{_esc(k + kbm.LABEL_SEP + n)}">'
                         f'</option>' for k, n in cat) + "</datalist>")
    # Where the reader lands after deciding one, so approving walks down the
    # queue rather than returning to the top of it every time.
    _order = [e["row"].id for e in entries]
    _after = {cid: (_order[i + 1] if i + 1 < len(_order) else "")
              for i, cid in enumerate(_order)}

    def _next_of(cid: str) -> str:
        return _after.get(cid, "")

    _covered = kbm.brand_level_duplicates(tenant) if pending else []

    # The creative library needs a way in that is not a Shopify sync: a venue
    # photograph and a tile installation shot have no store behind them, so the
    # whole photograph-based treatment was unreachable for precisely the
    # accounts it was built for. Rendered outside the `if pending` branch,
    # because an account with an empty review queue is the one most likely to
    # be starting from nothing.
    # The picture queue. A crawl files dozens at a time and they are useless
    # until somebody says which are the client's to publish — so the review has
    # to be as quick as the claim queue, thumbnails and all. Seeing them is the
    # whole job: nobody can judge a photograph from a CDN URL.
    waiting = kbm.proposed_assets(tenant)
    approved_pics = [a for a in kbm.assets(tenant) if a.kind == "image"]
    marks = kbm.logos(tenant)
    pic_cards = ""
    for a in waiting[:60]:
        is_logo = (a.subject or "") == kbm.LOGO
        pic_cards += f"""
        <label class="pic">
          <input type="checkbox" name="asset_ids" value="{_esc(a.id)}" form="pics">
          <img src="{_esc(a.url)}" loading="lazy" alt="">
          <span class="picmeta">{'&#9679; logo' if is_logo else ''}
            {_esc((a.title or '')[:38])}</span>
        </label>"""
    pics_html = ""
    if waiting:
        pics_html = f"""
    <div class="anchor" id="pics"></div>
    <div class="card">
      <div class="head"><h2>Pictures waiting</h2>
        <span class="mut">{len(waiting)} found by the crawler ·
        {len(approved_pics)} approved · {len(marks)} logo(s)</span></div>
      <p class="mut">A picture on a client&#39;s site is a <b>candidate, not a
      licence</b> — plenty of sites carry stock licensed for the web and
      nothing else. Approve what is genuinely theirs. Rejecting retires it, so
      the next crawl will not offer it again.</p>
      <form id="pics" method="post" action="/admin/assets_decide"></form>
      <input type="hidden" name="tenant" value="{_esc(tenant)}" form="pics">
      <div class="bulkbar">
        <label class="pick"><input type="checkbox" id="allpics"> select all
          {len(waiting)}</label>
        <span class="grow"></span>
        <button form="pics" name="action" value="reject" class="sec">Reject
          selected</button>
        <button form="pics" name="action" value="approve">Approve selected</button>
      </div>
      <div class="picgrid">{pic_cards}</div>
      <script>
      document.getElementById('allpics').addEventListener('change', function(e) {{
        document.querySelectorAll('input[name="asset_ids"]')
                .forEach(function(b) {{ b.checked = e.target.checked; }});
      }});
      </script>
    </div>"""

    assets_form = pics_html + f"""
    <div class="card">
      <div class="head"><h2>Creative library</h2></div>
      <p class="mut">Photographs the creative pipeline may use.
      <b>Owned</b> is the client&#39;s to publish; <b>reference</b> is
      inspiration only and can never leave the building. What it depicts is
      guessed from the file — a cutout is an object, anything else is treated
      as a scene.</p>
      <form class="f" method="post" action="/admin/asset_add">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="tenant" value="{_esc(tenant)}">
        <label>Image URL</label>
        <input name="url" placeholder="https://…" required>
        <label>What it is</label>
        <input name="title" placeholder="e.g. Main hall, evening">
        <label>Rights</label>
        <select name="rights">
          <option value="owned">owned — ours to publish</option>
          <option value="reference">reference — inspiration only</option>
        </select>
        <label>Product or space it shows (optional)</label>
        <input name="entity_key" placeholder="leave blank for brand-wide">
        <div class="row"><button>Add to library</button></div>
      </form>
    </div>"""

    if pending:
        def _card(p) -> str:
            chosen = set(p.situations or [])
            # A testimonial's wording IS its evidence. The field is read-only
            # rather than merely discouraged, because rewording a review turns a
            # record of what a customer said into something the brand asserts.
            verbatim = (p.proof_type or "") in kbm.VERBATIM_ONLY
            usage = kbm.usage_rule(p.proof_type or "")
            rule = (f'<div class="note">{_esc(usage)}</div>'
                    if verbatim and usage else
                    (f'<div class="when">{_esc(usage)}</div>' if usage else ""))
            # The vocabulary as checkboxes: a tag can only ever be one the
            # account actually has, so a correction cannot invent a tag that
            # selection will never match.
            tagbox = "".join(
                f'<label class="tag"><input type="checkbox" name="tags" '
                f'value="{_esc(t)}"{" checked" if t in chosen else ""}> '
                f'{_esc(t)}</label>' for t in vocab)
            # Similarity is only a duplicate where both rows could be
            # selected together. The same sentence on a different product is a
            # parallel fact — showing it as a duplicate would invite a reviewer
            # to reject a real product's answer.
            ent = _dupes.get(p.id, {})
            dup = ""
            for d in ent.get("covered_by_brand_level", [])[:2]:
                dup += ('<div class="note">Already covered brand-level: '
                        f'&ldquo;{_esc((d.claim or "")[:110])}&rdquo; — that one '
                        'applies everywhere, so this narrower copy adds nothing.'
                        '</div>')
            others = [d for d in ent.get("near_duplicates", [])
                      if d not in ent.get("covered_by_brand_level", [])]
            for d in others[:2]:
                dup += ('<div class="note">Close to an approved claim in the same '
                        f'scope: &ldquo;{_esc((d.claim or "")[:110])}&rdquo;</div>')
            for d in ent.get("parallel_on_other_entities", [])[:2]:
                dup += ('<div class="when">Same wording on a different item '
                        f'({_esc(d.entity_key or "")}): '
                        f'&ldquo;{_esc((d.claim or "")[:90])}&rdquo; — not a '
                        'duplicate; both can be true.</div>')

            # An expired claim is back in this queue because it CAME DUE, not
            # because somebody proposed it. Rendering it identically to a new
            # proposal throws away the whole advantage of returning it here —
            # "you approved this a year ago, is it still true" is a far easier
            # question than "is this true", asked cold.
            reconfirm = ""
            if p.approved_at:
                _e = kbm.claim_expiry(p)
                reconfirm = (
                    '<div class="note"><strong>Came due &mdash; you approved '
                    f'this on {_esc(_date(p.approved_at))}.</strong> '
                    f'{_esc(_e["why"])}. Nothing is wrong with it; claims '
                    'expire so somebody confirms they are still true. '
                    'Approving re-dates it for another year.'
                    '<div class="row">'
                    f'<button class="sec" name="action" value="never" '
                    f'title="Some facts do not go stale — brand origin, a '
                    f'material, a permanent placement. Marked timeless, this '
                    f'claim will never come back here.">This one never '
                    f'expires</button></div></div>')

            warn = ""
            if not chosen:
                warn = ('<div class="note">No tag matched. Pick at least one — '
                        'approval is refused without it, because an untagged '
                        'claim can never be selected.</div>')
            return f"""
            <div class="anchor" id="c-{_esc(p.id)}"></div>
            <label class="pick"><input type="checkbox" name="claim_ids"
                   value="{_esc(p.id)}" form="bulk"> select</label>
            <form class="f" method="post" action="/admin/claim_edit">
              <input type="hidden" name="claim_id" value="{_esc(p.id)}">
              <input type="hidden" name="tenant" value="{_esc(tenant)}">
              <input type="hidden" name="next_id" value="{_esc(_next_of(p.id))}">
              <label>{"Quoted — a customer's own words"
                      if verbatim else "Claim"}</label>
              <textarea name="claim" rows="2"{" readonly" if verbatim else ""
                        }>{_esc(p.claim)}</textarea>
              {rule}
              <label>{"Attribution" if verbatim
                      else "Evidence — the number or the proof"}</label>
              <input name="evidence" value="{_esc(p.evidence or '')}"
                     placeholder="what makes this checkable">
              <div class="when">{_esc(p.proof_type or '')} · {_esc(p.source or '')}</div>
              {(f'<label>Found next to &mdash; copied from the page</label>'
                f'<div class="when">&ldquo;{_esc(getattr(p, "context", ""))}&rdquo;</div>')
               if getattr(p, "context", "") else ""}
              <label>What it proves &mdash; written by the model, not the site</label>
              <textarea name="proves" rows="2"
                placeholder="what a reader should conclude from this">{_esc(getattr(p, 'proves', '') or '')}</textarea>
              <div class="when">{
                "The one field here the model WROTE rather than copied. Read it: "
                "a wrong reading of a true number is invisible once approved, and "
                "this is what a drafter reaches for when deciding how to use the "
                "claim."
                if getattr(p, "proves", "") else
                "Empty because no model read this page &mdash; the deterministic "
                "filter produces no interpretation at all. Write one, or re-run "
                "the harvest once the extractor is working and check "
                "<code>extractor</code> in the response."
              }</div>
              <label>True of &mdash; blank means the whole brand</label>
              <input name="entity_key" list="ents" value="{_esc(p.entity_key or '')}"
                     placeholder="brand-level (used in any content)">
              <div class="when">{
                  "Scoped to " + _esc(dict(cat).get(p.entity_key, p.entity_key))
                  + " &mdash; it will only ever appear in content about that."
                  if p.entity_key else
                  "Brand-level &mdash; usable in any content for this account."
              }</div>
              {dup}
              {reconfirm}
              {warn}
              <label>Situations</label>
              <div class="tags">{tagbox}</div>
              <div class="row">
                <button name="action" value="approve">Save &amp; approve</button>
                <button class="sec" name="action" value="save">Save only</button>
                <button class="sec" name="action" value="reject">Reject</button>
              </div>
            </form>"""
        # The checkboxes live inside each card but belong to THIS form via the
        # HTML5 `form` attribute — forms cannot nest, and duplicating the queue
        # into a separate compact list would mean deciding against a summary
        # rather than against the claim.
        covered_btn = ""
        if _covered:
            n = len(_covered)
            covered_btn = (
                f'<button form="bulk" name="action" value="reject_covered" '
                f'class="sec" title="A brand-level claim is already usable in '
                f'content about every product, so these narrower copies add '
                f'nothing">Retire {n} already covered brand-level</button>')
        bulk = f"""
        <form id="bulk" method="post" action="/admin/claims_decide"></form>
        <input type="hidden" name="tenant" value="{_esc(tenant)}" form="bulk">
        <div class="bulkbar">
          <label class="pick"><input type="checkbox" id="allbox"> select all
            {len(pending)}</label>
          <span class="grow"></span>
          {covered_btn}
          <button form="bulk" name="action" value="reject" class="sec">Reject
            selected</button>
          <button form="bulk" name="action" value="approve">Approve
            selected</button>
        </div>
        <script>
        document.getElementById('allbox').addEventListener('change', function(e) {{
          document.querySelectorAll('input[name="claim_ids"]')
                  .forEach(function(b) {{ b.checked = e.target.checked; }});
        }});
        </script>"""
        proposals = (catlist + assets_form + bulk
                     + '<div class="grid" style="grid-template-columns:1fr">'
                     + "".join(_card(p) for p in pending) + "</div>")
    else:
        proposals = (assets_form + '<p class="mut">Nothing waiting. Harvest reads the account\'s '
                     'own site and files what it finds here — as proposals, never '
                     'as facts.</p>')

    # --- disagreements between sources -------------------------------------
    # A conflict nobody can see is worse than the silent overwrite it replaced:
    # the data is right and the work is invisible. This is that surface.
    from . import provenance as prov
    open_conflicts = prov.conflicts(tenant)
    if open_conflicts:
        def _conflict(c) -> str:
            where = f"{c.table_name.replace('kb_', '').rstrip('s')} · {_esc(c.field)}"
            times = (f' <span class="chip off">seen {c.hits}×</span>'
                     if int(c.hits or "1") > 1 else "")
            return f"""
            <form class="f" method="post" action="/admin/conflict_resolve">
              <input type="hidden" name="conflict_id" value="{_esc(c.id)}">
              <input type="hidden" name="tenant" value="{_esc(tenant)}">
              <div class="when">{where}{times}</div>
              <label>Approved — what is in use now</label>
              <div class="msg">{_esc((c.approved_value or '')[:400])}</div>
              <label>{_esc(c.origin or 'another source')} says</label>
              <div class="msg esc">{_esc((c.incoming_value or '')[:400])}</div>
              <div class="when">{_esc(c.source_ref or '')}</div>
              <div class="row">
                <button class="sec" name="keep" value="approved">Keep ours</button>
                <button name="keep" value="incoming">Take theirs</button>
              </div>
            </form>"""
        conflicts_html = ('<div class="grid" style="grid-template-columns:1fr">'
                          + "".join(_conflict(c) for c in open_conflicts[:20])
                          + "</div>")
    else:
        conflicts_html = ('<p class="mut">Nothing in dispute. When a crawl, an '
                          'upload or the store disagrees with something already '
                          'approved, the approved value stays and the '
                          'disagreement appears here.</p>')

    # --- proposals from the other four tables ------------------------------
    # Claims had a review queue; audiences, objections, entities and situations
    # went live on write, so a client could redefine a buyer segment through an
    # intake link and nobody would ever see it happen.
    other = {k: v for k, v in kbm.proposals(tenant).items() if k != "claim"}
    if other:
        def _prop(kind: str, item: dict) -> str:
            r = item["row"]
            label = (getattr(r, "name", "") or getattr(r, "objection", "")
                     or getattr(r, "tag", "") or r.id)
            detail = (getattr(r, "response", "") or getattr(r, "description", "")
                      or getattr(r, "price", "") or "")
            dupes = "".join(
                f'<div class="when">looks like: '
                f'{_esc((getattr(d, "name", "") or getattr(d, "objection", "") or "")[:90])}'
                f'</div>' for d in item["near_duplicates"][:3])
            # An objection needs its scope decided before it can be approved,
            # and until now this form offered Approve and Reject and nothing
            # else — so a reviewer who could SEE that "sold as a set of 6" was
            # true of one product had no way to say so. The only moves were to
            # approve it wrong or throw away a real answer, which is why the
            # wrong ones are approved.
            scope = ""
            if kind == "objection":
                cat = {e.key: e.name for e in
                       kbm.entities(tenant, available_only=False)}
                opts = "".join(f'<option value="{_esc(k)}">{_esc(v)}</option>'
                               for k, v in cat.items())
                scope = f"""
              <label>True of &mdash; which item is this answer about?</label>
              <input name="entity_key" list="pents"
                     value="{_esc(getattr(r, 'entity_key', '') or '')}"
                     placeholder="start typing a product name">
              <datalist id="pents">{opts}</datalist>
              <label class="row" style="gap:6px">
                <input type="checkbox" name="brand_wide" value="1">
                <span>No item &mdash; this is true of everything they sell</span>
              </label>
              <div class="when">One of the two is required. An answer approved
                with neither is claimed of the whole catalogue &mdash;
                &ldquo;dishwasher safe&rdquo; read off one product page becomes
                a promise about the porcelain too.</div>"""
            return f"""
            <form class="f" method="post" action="/admin/proposal_review">
              <input type="hidden" name="kind" value="{_esc(kind)}">
              <input type="hidden" name="row_id" value="{_esc(r.id)}">
              <input type="hidden" name="tenant" value="{_esc(tenant)}">
              <div class="when">{_esc(kind)} · from {_esc(r.origin or 'unknown')}
                {_esc(r.source or '')}</div>
              <div class="msg">{_esc(str(label)[:200])}</div>
              {f'<div class="when">{_esc(str(detail)[:240])}</div>' if detail else ''}
              {dupes}
              {scope}
              <div class="row">
                <button name="action" value="approve">Approve</button>
                <button class="sec" name="action" value="reject">Reject</button>
              </div>
            </form>"""
        n_other = sum(len(v) for v in other.values())
        others_html = ('<div class="grid" style="grid-template-columns:1fr">'
                       + "".join(_prop(k, i) for k, items in other.items()
                                 for i in items) + "</div>")
    else:
        n_other, others_html = 0, (
            '<p class="mut">Nothing waiting. Audiences, objections, entities and '
            'situations submitted by a client or read from a spreadsheet land '
            'here first — they are not usable until approved.</p>')

    # --- clearing a queue in one action ------------------------------------
    # A queue filled by an earlier version of the crawler is not worth reading
    # one card at a time — the filter that selected it has since been fixed, so
    # re-running the harvest costs less than reviewing its output. The count is
    # in the button because "clear everything" should say how much everything is.
    n_props = len(pending) + sum(len(v) for v in other.values())
    if n_props:
        clear_all = f"""
        <form method="post" action="/admin/purge_proposals" class="row"
              onsubmit="return confirm('Delete all {n_props} un-reviewed \
proposals for {_esc(t.name)}? Approved rows are not touched.')">
          <input type="hidden" name="tenant" value="{_esc(tenant)}">
          <button class="sec">Clear all {n_props} proposals</button>
          <span class="mut">deletes un-reviewed rows only — nothing approved is
          touched, and nothing is kept as a rejection</span>
        </form>"""
    else:
        clear_all = ""

    # --- compliance --------------------------------------------------------
    scan = compliance.last_scan(tenant)
    if not scan:
        comp = ('<p class="mut">Never scanned. This checks every public page '
                'against this account\'s banned claims and lists the ones that '
                'break them.</p>')
    elif scan.get("stage") == "blocked":
        comp = ('<div class="note">Could not scan: '
                + _esc("; ".join(scan.get("blocked_on") or [])) + "</div>")
    else:
        n = scan.get("violations", 0)
        head = (f'<div class="stat"><span><b>{scan.get("pages_checked", 0)}</b> '
                f'pages checked</span><span><b>{n}</b> with a violation</span>'
                f'<span>{_esc(scan["at"].strftime("%b %d, %H:%M")) if scan.get("at") else ""}</span></div>')
        if not n:
            comp = head + '<p class="mut">Nothing on the live site breaks the rules.</p>'
        else:
            ranked = "".join(
                f'<span class="chip off">{_esc(p)} ×{c}</span>'
                for p, c in sorted((scan.get("by_phrase") or {}).items(),
                                   key=lambda kv: -kv[1]))
            items = "".join(
                f'<div class="msg esc">'
                f'<div><a href="{_esc(d["url"])}" target="_blank" rel="noopener">'
                f'{_esc(d["url"])}</a></div>'
                f'<div class="when">{_esc(", ".join(d["phrases"]))}</div>'
                f'<div class="when">“{_esc(d.get("context", ""))}”</div></div>'
                for d in (scan.get("detail") or []))
            more = (f'<p class="mut">+{scan["truncated"]} more not shown.</p>'
                    if scan.get("truncated") else "")
            comp = (head + f'<div class="chips">{ranked}</div>'
                    + f'<div class="thread">{items}</div>' + more)

    # --- catalogue ---------------------------------------------------------
    ents = kbm.entities(tenant, available_only=False)
    oos = [e for e in ents if (e.availability or "available") != "available"]
    flagged = [e for e in ents if (e.attributes or {}).get("_compliance")]
    synced = [e for e in ents if e.source == "shopify"]
    last = max((e.verified_at for e in synced if e.verified_at), default=None)
    has_store = cred.status(tenant) and tenants.capabilities(tenant).get("commerce")
    cat = (f'<div class="stat"><span><b>{len(ents)}</b> catalogued</span>'
           f'<span><b>{len(synced)}</b> from the store</span>'
           f'<span><b>{len(oos)}</b> out of stock</span>'
           f'<span><b>{len(flagged)}</b> with flagged copy</span>'
           + (f'<span>synced {_esc(db.as_utc(last).strftime("%b %d, %H:%M"))}</span>'
              if last else "") + "</div>")
    if flagged:
        cat += ('<div class="chips">' + "".join(
            f'<span class="chip off">{_esc(e.name)}</span>' for e in flagged[:10])
            + "</div><p class=\"mut\">Their storefront copy uses a banned phrase, "
              "so it was not imported. Fix the product page to clear the flag.</p>")
    if not has_store:
        cat += ('<p class="mut">No store connected, so there is nothing to sync. '
                'Products can still be added by hand on the Knowledge tab.</p>')

    banner = (f'<div class="ok">{_esc(_STARTED.get(started, ""))}</div>'
              if started in _STARTED else "")

    # What the last background action actually did. Without this a run that
    # failed and a run still going look identical — the banner says "proposals
    # will appear above" either way, and the traceback is in a service log the
    # person reading this page cannot see.
    from .web import bg_status
    for label, name in (("harvest", "Harvest"), ("scan", "Compliance scan"),
                        ("sync", "Catalogue sync"), ("email", "Sent mail")):
        st = bg_status(label, tenant)
        if not st:
            continue
        when = _esc((st.get("at") or "")[:16].replace("T", " "))
        if st.get("state") == "failed":
            banner += (f'<div class="note"><strong>{name} failed</strong> '
                       f'({when})<br>{_esc(st.get("detail", ""))}</div>')
        elif st.get("state") == "running":
            banner += (f'<div class="ok">{name} is running ({when}). '
                       f'Refresh in a moment.</div>')
        elif st.get("detail"):
            banner += (f'<div class="ok"><strong>{name}</strong> finished '
                       f'{when} — {_esc(st["detail"])}</div>')

    if err:
        banner = f'<div class="note">{_esc(err)}</div>' + banner
    if msg:
        # A bulk decision reports what it did, including what it refused. A
        # count with no reasons reads as a partial success nobody can act on.
        banner = f'<div class="when">{_esc(msg)}</div>' + banner
    return _shell(key, "content", "Content", f"""
{banner}
<div>
  <h1>Content</h1>
  <p class="mut">What this account's site actually says, what its catalogue holds,
  and what has been proposed but not yet approved. Nothing here is published —
  it is the difference between what the brand allows and what is live.</p>
</div>

<div class="tabs">{picker}</div>
<div class="card danger">
  <div class="head"><h2>Start this account's machine-read half over</h2></div>
  <p class="mut">Deletes every claim and objection that came from a crawl or a
  mailbox for <strong>{_esc(t.name if t else tenant)}</strong> — <strong>including approved
  ones</strong>, which is what the proposal clear below cannot reach. Keeps the
  ban list, the situation vocabulary, the catalogue, and anything a person
  wrote: a re-harvest needs all four, and without the catalogue every answer
  comes back unscoped.</p>
  <div class="row">
    <form method="get" action="/admin/purge_harvested" class="inl">
      <input type="hidden" name="tenant" value="{_esc(tenant)}">
      <button class="sec">Show me what it would delete</button>
    </form>
    <form method="post" action="/admin/purge_harvested" class="inl"
          onsubmit="return confirm('Delete every crawled and mailed claim and objection for {_esc(tenant)}, approved ones included? The ban list, vocabulary and catalogue are kept.')">
      <input type="hidden" name="tenant" value="{_esc(tenant)}">
      <input type="hidden" name="ui" value="1">
      <button>Clear and re-harvest</button>
    </form>
    <span class="mut">then run Fill from every source, below</span>
  </div>
</div>


<div class="card">
  <div class="head"><h2>Proposed, awaiting you</h2>
    <span class="chip {'off' if pending else 'on'}">{len(pending)} pending</span></div>
  <p class="mut">Found on {_esc(t.name)}'s own site. Invisible to every generator
  until approved. Anything using a banned phrase was dropped, not queued.</p>
  {proposals}
  <div class="row">{_act(key, "/admin/harvest", "Find proposals", tenant, {"apply": "1"})}
    <span class="mut">reads the site and files what it finds</span></div>
  <div class="row">{_act(key, "/admin/email_harvest", "Mine sent mail", tenant, {"ui": "1"})}
    <span class="mut">reads what this account has already SAID — the one place
    objections exist, because the brand has been answering the same questions
    for years. Only the buckets triage flagged as worth mining are opened.</span></div>
  {clear_all}
</div>

<div class="card">
  <div class="head"><h2>Everything else awaiting you</h2>
    <span class="chip {'off' if n_other else 'on'}">{n_other} pending</span></div>
  <p class="mut">Buyer segments, objections, catalogue rows and situation tags
  proposed by a client, a spreadsheet or a crawl. Approving one makes it final —
  no machine source can change it afterwards.</p>
  {others_html}
</div>

<div class="card">
  <div class="head"><h2>Sources disagree</h2>
    <span class="chip {'off' if open_conflicts else 'on'}">{len(open_conflicts)} open</span></div>
  <p class="mut">Something approved was contradicted by a later crawl, upload or
  store sync. The approved value is still what gets used — nothing was
  overwritten. Pick one and the disagreement closes.</p>
  {conflicts_html}
</div>

<div class="card">
  <div class="head"><h2>Live site compliance</h2></div>
  {comp}
  <div class="row">{_act(key, "/admin/compliance_scan", "Scan now", tenant)}
    <span class="mut">checks every public page against this account's rules</span></div>
</div>

<div class="card">
  <div class="head"><h2>Catalogue</h2></div>
  {cat}
  <div class="row">{_act(key, "/admin/catalog_sync", "Sync from store", tenant)}
    <span class="mut">names, prices and live stock — the store owns those</span></div>
</div>
""", suffix=f"&amp;tenant={tenant}")


# ---------------------------------------------------------------------------
# Client connect page — the other half of onboarding.
#
# Same guarantees as the intake link: one tenant, no admin key, nothing else
# reachable. One difference that matters — this form POSTs. Every other form in
# this console is a GET, which is fine for a step id and a sentence and very much
# not fine for an API key: a query string lands in browser history, the Referer
# header and every access log on the way.
# ---------------------------------------------------------------------------

_CONNECT_CSS = _CSS + """
.w{max-width:720px}
.prov{display:flex;flex-direction:column;gap:9px;border:1px solid var(--rule);
border-radius:6px;padding:14px 16px;background:var(--panel)}
.prov.done{background:var(--oks);border-color:var(--ok)}
.prov h3{display:flex;align-items:baseline;gap:9px}
.prov .how{font-size:.82rem;color:var(--ink2);border-left:2px solid var(--rule);
padding-left:10px}
.lock{font-size:.78rem;color:var(--mut)}
a.btn{font-size:.82rem;font-weight:600;padding:7px 14px;border-radius:5px;
border:1px solid var(--acc);background:var(--acc);color:var(--panel);
text-decoration:none;display:inline-block}
"""


def render_connect(link, tenant, rows: list[dict], msg: str = "",
                   err: str = "") -> str:
    """One row per provider this account needs. Secrets are never rendered back."""
    from . import credentials as cred
    t = tenants.get(tenant)
    name = _esc(t.name if t else tenant)

    blocks = []
    for r in rows:
        spec = cred.PROVIDERS[r["provider"]]
        done = r["state"] == "connected"
        chip = (f'<span class="chip on">connected</span>' if done else
                f'<span class="chip off">{_esc(r["state"])}</span>')
        if r["kind"] == "oauth":
            # An OAuth provider with its app credentials set is a button. Without
            # them it is still "on a call" — but the reason is now named, so the
            # thing blocking it is an env var someone can go and set rather than
            # a feature that reads as unbuilt.
            if not r["self_serve"]:
                blocks.append(f"""
                <div class="prov">
                  <h3>{_esc(r['name'])} <span class="chip nb">on a call</span></h3>
                  <div class="how">{_esc(spec['howto'])}</div>
                  <div class="mut">{_esc(r.get('blocked_by', ''))}</div>
                </div>""")
                continue
            detail = (f'<div class="mut">{_esc(r["detail"])}'
                      + (f' · last checked {_esc(r["last_verified"])}'
                         if r["last_verified"] else "") + "</div>") if done else ""
            blocks.append(f"""
            <div class="prov{' done' if done else ''}">
              <h3>{_esc(r['name'])} {chip}</h3>
              {detail}
              <details class="how"><summary>What happens when I click this?</summary>
                <p>{_esc(spec['howto'])}</p></details>
              <div class="row"><a class="btn"
                 href="/connect/{_esc(link.token)}/oauth/{_esc(r['provider'])}"
                 >{'Reconnect' if done else 'Connect'} {_esc(spec['name'].split(' (')[0])}</a></div>
            </div>""")
            continue
        if not r["self_serve"]:
            blocks.append(f"""
            <div class="prov">
              <h3>{_esc(r['name'])} <span class="chip nb">on a call</span></h3>
              <div class="how">{_esc(spec['howto'])}</div>
            </div>""")
            continue
        extra = "".join(
            f'<label>{_esc(hint)}</label>'
            f'<input name="{_esc(f)}" placeholder="{_esc(hint)}" required>'
            for f, hint in spec["also"].items())
        detail = (f'<div class="mut">{_esc(r["detail"])}'
                  + (f' · last checked {_esc(r["last_verified"])}'
                     if r["last_verified"] else "") + "</div>") if done else ""
        # A client with more than one WordPress install needs to see the ones
        # already connected, or they cannot tell whether the form below is for
        # adding the next one or replacing the last one.
        conns = [c for c in r.get("connections", []) if c["state"] != "revoked"]
        if r.get("site_scoped") and conns:
            detail = ('<div class="mut">connected: '
                      + ", ".join(_esc(c["site"] or "(no site recorded)")
                                  for c in conns) + "</div>")
        verb = ("Add another" if (r.get("site_scoped") and conns)
                else ("Replace" if done else "Connect"))
        blocks.append(f"""
        <div class="prov{' done' if done else ''}">
          <h3>{_esc(r['name'])} {chip}</h3>
          {detail}
          <details class="how"><summary>Where do I find this?</summary>
            <p>{_esc(spec['howto'])}</p></details>
          <form class="f" method="post" action="/connect/{_esc(link.token)}">
            <input type="hidden" name="provider" value="{_esc(r['provider'])}">
            {extra}
            <label>{_esc(spec['field'])}</label>
            <input name="secret" type="password" autocomplete="off"
                   placeholder="{_esc(spec['field'])}" required>
            <div class="row"><button>{_esc(verb)}</button></div>
          </form>
        </div>""")

    note = f'<div class="ok">{_esc(msg)}</div>' if msg else ""
    if err:
        note += f'<div class="note">{_esc(err)}</div>'

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — connect your accounts</title><style>{_CONNECT_CSS}</style></head>
<body><div class="w">
<div>
  <h1>Connect {name}</h1>
  <p class="mut">So we can work on your behalf without asking you for exports.
  Each one is checked the moment you paste it, so you will know immediately if
  it is right. You can disconnect any of them at any time.</p>
</div>
{note}
<div class="grid" style="grid-template-columns:1fr">{''.join(blocks)}</div>
<p class="lock">Keys are encrypted before they are stored and are never shown
again — not on this page, and not to us. This link is private to {name}.</p>
</div></body></html>"""


# ---------------------------------------------------------------------------
# The Data layer tab — what the knowledge base actually holds, per account.
#
# The Knowledge tab shows the CONTENT: this shows the SHAPE. Which tables exist,
# how full each column is, and how the rows break down by where they came from
# and whether anyone has approved them. Built by reading the models rather than
# by hand, so a column added tomorrow appears here without anyone remembering
# to add it — the same reason `test_kb_ui` asserts against rendered HTML.
# ---------------------------------------------------------------------------

_KB_TABLES = [
    ("KbBrand", "kb_brand", "Who they are, how they sound, what they may never say",
     "One row per account. Voice, positioning, banned claims, and the config "
     "that tells selection what this account sells."),
    ("KbClaim", "kb_claims", "Assertions the brand is allowed to make",
     "The heart of it. Each carries its proof, its proof TYPE (which governs "
     "what a generator may do with it), the situations it answers, and what it "
     "is true of."),
    ("KbEntity", "kb_entities", "The thing being sold",
     "One table absorbs offers, products, venue spaces and slabs. `attributes` "
     "is the typed bag selection matches numeric requirements against."),
    ("KbObjection", "kb_objections", "Why a deal stalls, and the approved answer",
     "Scoped to an audience, an entity, or neither. A product FAQ is exactly "
     "this shape, which is why it is the one place objections can be derived."),
    ("KbAudience", "kb_audiences", "A buyer segment, in their words not yours",
     "`vocabulary` is what THEY say — the words a draft should echo back."),
    ("KbSituation", "kb_situations", "The account's own diagnostic vocabulary",
     "The controlled tag list claims are filed under. Per account, as data — a "
     "shared constant was agency language no product enquiry could ever match."),
    ("KbUnknown", "kb_unknowns", "Questions the catalogue could not answer",
     "Counted by how often each gap actually cost an answer, so the backlog is "
     "ranked by real cost rather than by guesswork."),
    ("KbConflict", "kb_conflicts", "Two sources disagree about an approved value",
     "Both values kept, neither applied. The row keeps what a human approved "
     "until someone settles it."),
]


# How the KB tables find each other. Written down here rather than derived,
# because there are no foreign keys to derive it FROM — every one of these is a
# join the write layer performs and validates by hand. Anyone reading the schema
# needs that stated, not implied.
_IDENTIFIERS = [
    ("kb_brand", "tenant", "—",
     "The account key IS the primary key. One brand row per client."),
    ("kb_claims", "id (uuid)", "fingerprint(claim, entity_key)",
     "Dedupe is on the normalised claim text plus its scope, so the same "
     "sentence about two products stays two rows."),
    ("kb_entities", "id (uuid)", "tenant + key",
     "`key` is the stable slug or SKU — the join target every entity_key points at."),
    ("kb_audiences", "id (uuid)", "tenant + key", "Upserted on key."),
    ("kb_objections", "id (uuid)", "fingerprint(objection, entity_key)",
     "Same rule as claims: one question, two products, two answers."),
    ("kb_situations", "id (uuid)", "tenant + tag", "The controlled vocabulary."),
    ("kb_unknowns", "id (uuid)", "tenant + entity_key + attribute",
     "One row per real gap, counted — not one per enquiry."),
    ("kb_conflicts", "id (uuid)", "tenant + table_name + row_id + field",
     "Aggregated while open, so a nightly sync raises the count not the rows."),
]

_RELATIONSHIPS = [
    ("tenants.key", "every KB table .tenant", "1 : N", "required",
     "The account boundary. Reads are filtered by it server-side, never from a "
     "caller-supplied parameter."),
    ("kb_entities (tenant, key)", "kb_claims.entity_key", "1 : N", "nullable",
     "Blank means the claim is true of the brand and usable anywhere. Set means "
     "it only ever appears in content about that entity."),
    ("kb_entities (tenant, key)", "kb_objections.entity_key", "1 : N", "nullable",
     "Same rule. A product FAQ answer is correct about one product and wrong "
     "about the next."),
    ("kb_entities (tenant, key)", "kb_unknowns.entity_key", "1 : N", "required",
     "A gap is always a gap in one thing's data."),
    ("kb_audiences (tenant, key)", "kb_objections.audience_key", "1 : N", "nullable",
     "Blank means it applies to every segment."),
    ("kb_situations (tenant, tag)", "kb_claims.situations[]", "N : M", "validated",
     "A JSON array, checked against the account's own tags on every write. An "
     "unknown tag is refused rather than stored."),
    ("kb_claims.id", "kb_objections.claim_id", "1 : N", "nullable, unused",
     "Designed to pair an objection with the proof that answers it. Nothing "
     "writes it yet."),
    ("any KB row .id", "kb_conflicts.row_id + table_name", "1 : N", "polymorphic",
     "The conflict names its table, so one queue covers every kind of row."),
]

def _fill_bar(pct: int) -> str:
    """A column's fill rate. Empty columns are the point of this screen."""
    cls = "on" if pct >= 80 else ("sec" if pct >= 30 else "off")
    return (f'<span class="fillbar"><i class="{cls}" style="width:{pct}%"></i>'
            f'</span><span class="fillpct">{pct}%</span>')


def render_schema(key: str, tenant: str = "") -> str:
    from . import db as _db, kb as kbm, provenance as prov

    rows_t = tenants.all_tenants(include_paused=True)
    tenant = tenant or (rows_t[0].key if rows_t else "")
    picker = "".join(
        f'<a class="{"on" if r.key == tenant else ""}" '
        f'href="/admin/ui?tab=schema&amp;tenant={_esc(r.key)}">{_esc(r.name)}</a>'
        for r in rows_t)

    blocks = []
    for cls_name, table, headline, why in _KB_TABLES:
        model = getattr(_db, cls_name)
        cols = [c for c in model.__table__.columns]
        with _db.SessionLocal() as s:
            q = s.query(model)
            if "tenant" in [c.name for c in cols]:
                q = q.filter(model.tenant == tenant)
            rows = q.all()
            s.expunge_all()
        n = len(rows)

        # Per-column fill rate. A column nobody fills is either dead weight or
        # a gap in the intake, and both are worth seeing.
        colrows = ""
        for c in cols:
            if c.name in ("id", "tenant"):
                continue
            filled = 0
            for r in rows:
                v = getattr(r, c.name, None)
                if v not in (None, "", [], {}):
                    filled += 1
            pct = int(100 * filled / n) if n else 0
            axis = ""
            if c.name in ("origin", "review", "approved_by", "approved_at",
                          "fingerprint", "also_seen"):
                axis = '<span class="chip sec">provenance</span>'
            elif c.name in ("entity_key", "audience_key"):
                axis = '<span class="chip sec">scope</span>'
            colrows += (f'<tr><td class="cn">{_esc(c.name)}</td>'
                        f'<td class="ct">{_esc(str(c.type)[:14])}</td>'
                        f'<td class="cf">{_fill_bar(pct) if n else "&mdash;"}</td>'
                        f'<td>{axis}</td></tr>')

        # How the rows break down on the two axes that decide usability.
        def _tally(attr):
            out = {}
            for r in rows:
                out[getattr(r, attr, None) or "—"] = out.get(
                    getattr(r, attr, None) or "—", 0) + 1
            return out
        breakdown = ""
        if n and hasattr(model, "review"):
            rev = _tally("review")
            org = _tally("origin")
            breakdown = ('<div class="chips">'
                         + "".join(f'<span class="chip {"on" if k == prov.APPROVED else "off"}">'
                                   f'{_esc(k)} {v}</span>' for k, v in sorted(rev.items()))
                         + "".join(f'<span class="chip sec">{_esc(k)} {v}</span>'
                                   for k, v in sorted(org.items())) + "</div>")

        blocks.append(f"""
        <div class="card">
          <div class="head">
            <h2>{_esc(headline)}</h2>
            <span class="chip {"on" if n else "off"}">{n} row{"" if n == 1 else "s"}</span>
          </div>
          <div class="when">{_esc(cls_name)} &middot; <code>{_esc(table)}</code></div>
          <p class="mut">{why}</p>
          {breakdown}
          <table class="cols">
            <tr><th>Column</th><th>Type</th><th>Filled</th><th></th></tr>
            {colrows}
          </table>
        </div>""")

    ident = "".join(
        f'<tr><td class="cn">{_esc(t)}</td><td class="cn">{_esc(pk)}</td>'
        f'<td class="cn">{_esc(bk)}</td><td class="mut">{_esc(why)}</td></tr>'
        for t, pk, bk, why in _IDENTIFIERS)
    rels = "".join(
        f'<tr><td class="cn">{_esc(a)}</td><td class="ct">&rarr;</td>'
        f'<td class="cn">{_esc(b)}</td><td class="ct">{_esc(card)}</td>'
        f'<td><span class="chip sec">{_esc(req)}</span></td>'
        f'<td class="mut">{_esc(why)}</td></tr>'
        for a, b, card, req, why in _RELATIONSHIPS)
    relational = f"""
<div class="card">
  <div class="head"><h2>Identifiers</h2></div>
  <p class="mut">Every table has a surrogate primary key. The business key is
  what the write layer actually dedupes and upserts on — and none of these are
  database constraints, so concurrent writers could still both insert.</p>
  <table class="cols">
    <tr><th>Table</th><th>Primary key</th><th>Business key</th><th></th></tr>
    {ident}
  </table>
</div>

<div class="card">
  <div class="head"><h2>How the tables relate</h2></div>
  <p class="mut"><b>There are no foreign keys anywhere in this schema.</b> Every
  relationship below is a join the write layer performs and validates by hand —
  which is why an unknown situation tag or an entity key that is not in the
  catalogue is refused at the door rather than caught by the database.</p>
  <table class="cols">
    <tr><th>From</th><th></th><th>To</th><th>Card.</th><th></th><th></th></tr>
    {rels}
  </table>
</div>"""

    comp = kbm.completeness(tenant)
    waiting = comp.get("awaiting_review", {})
    top = (f'<div class="stat">'
           f'<span><b>{comp["counts"].get("claims", 0)}</b> claims</span>'
           f'<span><b>{comp["counts"].get("entities", 0)}</b> entities</span>'
           f'<span><b>{comp["counts"].get("objections", 0)}</b> objections</span>'
           f'<span><b>{sum(waiting.values())}</b> awaiting review</span>'
           f'<span>{"ready" if comp["ready"] else "not ready"}</span></div>')
    missing = ("".join(f'<span class="chip off">{_esc(m)}</span>'
                       for m in comp.get("missing", []))) or ""

    return _shell(key, "schema", "Data layer", f"""
<div>
  <h1>Data layer</h1>
  <p class="mut">What the knowledge base holds for this account, table by table.
  The Knowledge tab shows the content; this shows the shape — which columns are
  actually being filled, and how the rows break down by where they came from and
  whether a human has approved them. Read from the models, so a new column shows
  up here on its own.</p>
</div>
<div class="tabs">{picker}</div>
<div class="card">
  <div class="head"><h2>This account at a glance</h2></div>
  {top}
  <div class="chips">{missing}</div>
  <p class="mut">Counts are APPROVED rows only — the same filter every generator
  reads through. Anything proposed is in "awaiting review" and cannot be used
  until someone approves it.</p>
</div>
{"".join(blocks)}
{relational}
""", suffix=f"&amp;tenant={_esc(tenant)}")


def render_assurance(key: str, tenant: str = "", days: int = 30) -> str:
    """What the layer checked, what it caught, and what cannot be measured yet.

    Ordered by how much each number can be trusted: catches first because they
    need no interpretation, then coverage, then the quality signal that is
    still missing. A dashboard that leads with a rate computed from four events
    teaches people to believe rates computed from four events.
    """
    from . import assurance
    rep = assurance.report(tenant, days)
    who = f" · {_esc(tenant)}" if tenant else " · all accounts"

    if not rep["events"]:
        body = (f'<div class="note"><strong>Nothing has been checked in the '
                f'last {days} days.</strong><br>That is not the same as '
                f'nothing being wrong — it means no draft passed through a '
                f'validator, so this page has no evidence either way.</div>')
        return _shell(key, "assurance", "Assurance", body)

    catch_rows = "".join(
        f'<tr><td><code>{_esc(r)}</code></td><td class="num">{n}</td></tr>'
        for r, n in rep["caught"].items()) or \
        '<tr><td colspan="2" class="mut">nothing caught in this window</td></tr>'

    src_rows = "".join(
        f'<tr><td>{_esc(src)}</td><td class="num">{d["checks"]}</td>'
        f'<td class="num">{d["caught"]}</td><td class="num">{d["blocked"]}</td></tr>'
        for src, d in sorted(rep["by_source"].items()))

    g = rep["grounding"]
    grate = ("not measured" if g["rate"] is None
             else f'{g["rate"]:.0%} <span class="mut">of {g["measured"]}</span>')
    rp = rep["repairs"]
    ed = rep["edited"]
    ed_line = (f'<strong>{ed["edited_rate"]:.0%}</strong> of {ed["decided_runs"]} '
               f'decided runs were edited before sending'
               if ed["edited_rate"] is not None else
               f'<span class="mut">{_esc(ed["note"])}</span>')

    thin_rows = "".join(
        f'<tr><td>{_esc(t)}</td><td class="num">{n}</td></tr>'
        for t, n in rep["thin"].items()) or \
        '<tr><td colspan="2" class="mut">every run had what it needed</td></tr>'

    body = f"""
    <h2>Assurance{who}</h2>
    <p class="mut">Last {days} days · {rep['events']} checks recorded.</p>

    <details class="conns" open><summary>What was caught</summary>
      <p class="mut">Each of these is a phrase the model wrote and
      deterministic code stopped. Without the layer it would have gone out —
      this is the one number here that needs no interpretation.</p>
      <table class="tbl"><tr><th>rule</th><th>times</th></tr>
      {catch_rows}</table>
      <p class="when"><strong>{rep['caught_total']}</strong> total.</p>
    </details>

    <details class="conns" open><summary>Where the checking happens</summary>
      <p class="mut">The mail path uses a plain substring test; the substrate
      uses word-boundary matching. Same column, different strength.</p>
      <table class="tbl">
      <tr><th>source</th><th>checks</th><th>caught</th><th>blocked</th></tr>
      {src_rows}</table>
    </details>

    <details class="conns" open><summary>Grounding and repair</summary>
      <table class="tbl">
        <tr><td>drafts carrying a claim_id</td><td class="num">{grate}</td></tr>
        <tr><td>repair attempts</td><td class="num">{rp['attempted']}</td></tr>
        <tr><td>&nbsp;&nbsp;fixed by a redraft</td><td class="num">{rp['succeeded']}</td></tr>
        <tr><td>&nbsp;&nbsp;still blocked after repair</td><td class="num">{rp['still_blocked']}</td></tr>
      </table>
    </details>

    <details class="conns" open><summary>Is it improving the output?</summary>
      <p>{ed_line}</p>
      <p class="mut">Catches and repairs prove the layer is doing something a
      model alone would not. They do not prove the drafts are better — that is
      a comparison, and it needs either the edit history above or a run of
      <code>scripts/ab_context.py</code>, which has never been run.</p>
    </details>

    <details class="conns"><summary>What runs were missing</summary>
      <table class="tbl"><tr><th>gap</th><th>runs affected</th></tr>
      {thin_rows}</table>
    </details>
    """
    return _shell(key, "assurance", "Assurance", body)
