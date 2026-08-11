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

from . import config, db, tenants

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
        "NOT CONNECTED YET. Canva Connect is OAuth, so it needs the auth layer "
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
code{font-family:ui-monospace,Menlo,monospace;font-size:.82em;background:var(--rule2);
padding:.1em .35em;border-radius:3px}
.cur{background:var(--accs);border-left:3px solid var(--acc)}
.note{background:var(--gaps);border-left:3px solid var(--gap);padding:10px 14px;
border-radius:0 4px 4px 0;font-size:.85rem;color:var(--ink2)}
"""


def _esc(v) -> str:
    return html.escape(str(v or ""), quote=True)


def _chips(caps: dict) -> str:
    return "".join(
        f'<span class="chip {"on" if ok else "off"}">{c}</span>'
        for c, ok in caps.items())


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


def render(key: str) -> str:
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
              <div class="grid">{fields}</div>
            </div>"""

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Accounts — Saias Ops</title><style>{_CSS}</style></head><body><div class="w">

<div>
  <h1>Accounts</h1>
  <p class="mut">Values here are <strong>keys into</strong> credential dictionaries or
  env-var names — never the secrets themselves. API keys and tokens live in
  Render env vars.</p>
</div>

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
</div></body></html>"""
