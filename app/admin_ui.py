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
/* --- the frame: sidebar, client switcher, page ---------------------------
   Same shape as the client portal on purpose. Switching between the two
   should not mean learning a second layout, and the account is chosen once
   in the frame rather than re-picked inside four separate tabs. */
.shell{display:flex;min-height:100vh;align-items:stretch}
.side{width:224px;flex:0 0 224px;background:var(--panel);
border-right:1px solid var(--rule);padding:18px 12px;display:flex;
flex-direction:column;gap:1px;position:sticky;top:0;height:100vh;overflow-y:auto}
.side .brand{font-weight:700;font-size:.98rem;padding:0 10px 14px}
.side .swlabel,.side .navlabel{font-size:.68rem;text-transform:uppercase;
letter-spacing:.08em;color:var(--mut);padding:12px 10px 6px;font-weight:600}
.side .switch{display:flex;flex-direction:column;gap:1px;margin-bottom:4px}
.side a{display:flex;align-items:center;gap:9px;padding:8px 10px;border-radius:6px;
color:var(--ink2);font-size:.88rem;text-decoration:none}
.side a:hover{background:var(--rule2)}
.side a.on{background:var(--accs);color:var(--acc);font-weight:600}
.side .ico{width:16px;text-align:center;opacity:.8;font-size:.9em}
.side .dot{width:7px;height:7px;border-radius:99px;background:var(--rule);
flex:0 0 7px}
.side a.on .dot{background:var(--acc)}
/* --- one account, told apart at a glance --------------------------------
   The pill said which account you were on and nothing else did, so two tabs
   of two clients looked identical until you read the name. `--tint` is a hue
   derived from the account key (see `_accent`), applied to the one selected
   row, the page pill and a rule under the heading. Hue only: saturation and
   lightness are fixed here so no account can render illegibly or alarmingly,
   and an account added tomorrow gets its colour without an edit. */
body{--tone:hsl(var(--tint,214) 42% 38%);--tones:hsl(var(--tint,214) 46% 94%)}
@media(prefers-color-scheme:dark){body{--tone:hsl(var(--tint,214) 52% 72%);
--tones:hsl(var(--tint,214) 34% 17%)}}
body.every{--tone:var(--acc);--tones:var(--accs)}
/* Every account's dot in ITS OWN colour, not just the selected one -- each
   row carries a `--tint` of its own, so the mapping is learnable from the
   list rather than only visible once you have already switched. */
.side .switch a .dot{background:hsl(var(--tint,214) 44% 52%);opacity:.5}
.side .switch a.on{background:var(--tones);color:var(--tone)}
.side .switch a.on .dot{opacity:1}
.side .switch a.every .dot{background:var(--rule);opacity:1}
.side .switch a.every{border-top:1px solid var(--rule);margin-top:5px;
padding-top:10px;color:var(--mut);font-size:.82rem}
.side .switch a.every.on{color:var(--acc);background:var(--accs)}
.pagehead{border-bottom:2px solid var(--tone);padding-bottom:10px}
.pagehead .who{color:var(--tone);background:var(--tones)}
/* Cross-account is a deliberate view and says so on the page it produces --
   never a state you can arrive in without having asked for it. */
.everynote{background:var(--accs);border-left:3px solid var(--acc);
padding:9px 13px;border-radius:0 4px 4px 0;font-size:.83rem;color:var(--ink2);
margin-bottom:14px}
.everynote b{color:var(--acc)}
/* --- the diagnostics log -------------------------------------------------
   A dense, scannable timeline: level in the gutter so failures are found by
   colour before they are read, and the layer named on every row because
   "broken" and "refused on purpose" look identical until something says so. */
.filters{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:0 0 12px}
.filters a{font-size:.78rem;padding:4px 11px;border-radius:99px;
border:1px solid var(--rule);color:var(--ink2);text-decoration:none}
.filters a.on{background:var(--tones);border-color:var(--tone);color:var(--tone);
font-weight:600}
.filters .sep{width:1px;height:18px;background:var(--rule);margin:0 4px}
.log{border:1px solid var(--rule);border-radius:5px;overflow:hidden}
.log .ev{display:flex;gap:10px;padding:8px 12px;border-top:1px solid var(--rule2);
font-size:.83rem;align-items:baseline}
.log .ev:first-child{border-top:0}
.log .ev .lv{flex:0 0 6px;align-self:stretch;border-radius:99px;margin-top:2px}
.log .ev.fail .lv{background:#b4443a}
.log .ev.warn .lv{background:var(--gap)}
.log .ev.ok .lv{background:var(--ok)}
.log .ev.info .lv{background:var(--rule)}
.log .ev .when{flex:0 0 118px;color:var(--mut);font-size:.76rem;
font-family:ui-monospace,Menlo,monospace}
.log .ev .kind{flex:0 0 74px;color:var(--mut);font-size:.74rem;
text-transform:uppercase;letter-spacing:.05em}
.log .ev .what{flex:1;min-width:0}
.log .ev .what b{font-weight:600}
.log .ev .det{color:var(--ink2);display:block;font-size:.8rem;
word-break:break-word}
.log .ev .layer{flex:0 0 auto;font-size:.7rem;color:var(--mut);
border:1px solid var(--rule);border-radius:99px;padding:1px 8px}
.log .ev .acct{flex:0 0 auto;font-size:.7rem;color:var(--mut)}
.sysrow{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;
padding:9px 0;border-top:1px solid var(--rule2)}
.sysrow:first-child{border-top:0}
.sysrow .nm{flex:0 0 190px;font-weight:600}
.sysrow .vd{flex:1;min-width:200px;color:var(--ink2);font-size:.85rem}
.sysrow .n{font-family:ui-monospace,Menlo,monospace;font-size:.8rem;
color:var(--mut)}
.sysrow.bad .vd{color:#b4443a}
.sysrow.warn .vd{color:var(--gap)}
.side .foot{margin-top:auto;padding-top:12px;border-top:1px solid var(--rule);
display:flex;flex-direction:column;gap:1px}
.side .foot a{font-size:.82rem;color:var(--mut)}
.side a.pend{color:var(--acc);font-weight:600}
.main{flex:1;min-width:0;padding:22px 28px 60px;max-width:1180px}
.pagehead{display:flex;align-items:baseline;gap:12px;margin-bottom:18px;
flex-wrap:wrap}
.pagehead h1{font-size:1.3rem;margin:0;letter-spacing:-.02em}
/* Whose data this is, on every page. Below the fold it was possible to read a
   whole screen without ever seeing the account name. */
.pagehead .who{font-size:.82rem;color:var(--acc);background:var(--accs);
padding:3px 10px;border-radius:99px;font-weight:600}
@media(max-width:820px){.shell{flex-direction:column}
.side{width:auto;flex:none;height:auto;position:static;flex-direction:row;
flex-wrap:wrap;padding:10px;gap:4px}
.side .brand,.side .swlabel,.side .navlabel{display:none}
.side .switch{flex-direction:row;flex-wrap:wrap}
.side .foot{margin:0;border:0;flex-direction:row;padding:0}
.main{padding:16px}}
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
/* The result of what you just did stays readable even when a redirect lands
   the reader mid-page at an anchor — without this, every anchored decision
   scrolled its own confirmation out of view. */
.flash{position:sticky;top:0;z-index:60}
.pager{display:flex;gap:12px;align-items:center;margin:8px 0;font-size:.85rem}
.navbadge{margin-left:auto;background:var(--gap);color:#fff;border-radius:9px;
font-size:.72rem;font-weight:700;padding:1px 7px;line-height:1.5}
/* The workflow surface: the strip is STATE (counts that link into the
   system's own view), a plan card is one item of queued work. */
.workstrip{display:flex;gap:4px 16px;flex-wrap:wrap;font-size:.8rem;align-items:center;color:var(--mut)}
.workstrip a{color:var(--ink);text-decoration:none;border-bottom:1px dotted var(--mut)}
.workstrip b{font-weight:600}
.crumb{font-size:.8rem}
.crumb a{color:var(--acc);text-decoration:none}
.plan{border:1px solid var(--rule);border-radius:5px;padding:11px 13px;
  display:flex;flex-direction:column;gap:8px;background:var(--panel)}
.plan.ok{border-left:3px solid var(--ok)}
.plan.gap{border-left:3px solid var(--gap)}
.planhead{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.planhead .grow{flex:1}
.planfields{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px}
"""

#: (key, label, icon). Ordered the way a day runs rather than the way the code
#: is arranged: what needs deciding, then what it knows, then what it is
#: connected to, then the plumbing.
_TABS = (("content", "Review", "✓"), ("kb", "Knowledge", "◈"),
         ("brand", "Brand", "❖"),
         ("systems", "Systems", "◧"), ("assurance", "Assurance", "◉"),
         ("diagnostics", "Diagnostics", "⚕"),
         ("accounts", "Connections", "⚯"), ("schema", "Data layer", "⛁"))


def _model_options(selected: str = "") -> str:
    """The business models a report knows how to speak, from the one list.

    Read off `metrics.OUTCOMES` rather than typed here: a model in this dropdown
    that the report has no vocabulary for creates an account whose first report
    says "no outcomes for 'x'", and a hand-kept second list is how that happens.
    `selected` pre-picks the account's current value, so the edit control on an
    existing account shows what IS before offering what could be.
    """
    from . import metrics
    label = {"ecom_inventory": "shop — sells stock it holds",
             "ecom_dtc": "shop — direct to consumer",
             "local_venue": "venue, events or a local service",
             "b2b_spec": "sells into trade or specification",
             "digital_products": "courses, software, info products",
             "coaching": "coaching or consulting",
             "real_estate": "property",
             "food_bev": "food and drink"}
    opts = [f'<option value=""{"" if selected else " selected"}>'
            f'— not set (their report carries no outcomes) —</option>']
    opts += [f'<option value="{m}"{" selected" if m == selected else ""}>'
             f'{label.get(m, m)}</option>'
             for m in sorted(metrics.OUTCOMES)]
    return "".join(opts)


#: The account a page is about when the URL names none. Every render_* and the
#: frame itself go through `_account`, so the pill above the fold and the
#: numbers below it cannot disagree -- which they did: the Assurance tab with
#: no `tenant=` reported every account's checks under the first account's name.
ALL = "*"          # the deliberate cross-account view, never the default


def _account(tenant: str = "") -> tuple[str, object, list]:
    """Resolve the selected account ONCE, for the frame and the body alike.

    Returns `(key, row, all_rows)`. `key` is `ALL` only when the caller asked
    for it by name -- an empty `tenant=` falls back to the first account rather
    than to everything, because a page showing five accounts' data under one
    account's heading is worse than either view on its own.

    `row` is None for `ALL` and for an account key that does not exist; callers
    render the key rather than 500ing, because a stale bookmark should show an
    empty page and not an error.
    """
    from . import tenants as _t
    try:
        rows = _t.all_tenants(include_paused=True)
    except Exception:                                            # noqa: BLE001
        rows = []
    if tenant == ALL:
        return ALL, None, rows
    key = tenant or (rows[0].key if rows else "")
    return key, next((r for r in rows if r.key == key), None), rows


def _account_name(tenant: str, row=None) -> str:
    """What to call the selected account in a heading."""
    if tenant == ALL:
        return "All accounts"
    return (row.name if row is not None else "") or tenant or "no account"


def _hues(rows: list) -> dict[str, str]:
    """A hue per account, spread as far apart as the number of accounts allows.

    Derived rather than configured, for the same reason `metrics.OUTCOMES`
    drives its own dropdown: a hand-kept colour table is a second list to
    forget. Hue only -- saturation and lightness are fixed in the stylesheet,
    so every account stays legible in both themes and none can be handed an
    alarming red by accident.

    **Spaced by position, not hashed from the key**, and the first version was
    hashed. With five accounts, five samples out of 360 collide by chance:
    `ironside` landed on 231 and `coverings` on 256, twenty-five degrees apart
    and the same blue to anybody not comparing them side by side. A cue nobody
    can tell apart is not a cue.

    The cost, stated because it is real: adding an account re-colours the set.
    That is a one-off on a list that gains a client every few months, against
    two indistinguishable blues every day -- and the name is on the screen
    either way, so the colour is the second signal and never the identifier.
    """
    keys = sorted(r.key for r in rows)
    n = len(keys) or 1
    # Offset so the first account is not the same blue as the house accent,
    # which would make "selected" and "chrome" read as one thing.
    return {k: str(round((i * 360 / n + 25) % 360)) for i, k in enumerate(keys)}


def _review_waiting(tenant: str) -> int:
    """This account's review-queue depth — every KB table's proposed rows.

    Rides the Review item in the sidebar on every page, because "is there
    work" must not cost a click per tab to find out (owner, 2026-08-21: the
    fewer clicks and the less thinking, the better the app is planned). The
    sibling number — pending APPROVALS — already has its own pill below the
    switcher linking /admin/pending; this one is the proposals half and links
    where proposals are decided. Scalar COUNTs only, and any failure counts as
    zero: a sidebar must never be the thing that breaks a page.
    """
    if not tenant or tenant == ALL:
        return 0
    from . import provenance as prov
    try:
        with db.SessionLocal() as s:
            proposed = sum(
                s.query(model)
                .filter(model.tenant == tenant,
                        model.review == prov.PROPOSED).count()
                for model in (db.KbClaim, db.KbAudience, db.KbObjection,
                              db.KbEntity, db.KbSituation, db.KbAsset))
        # Plans held for a person are review work too — a plan missing a
        # field, or complete and awaiting the explicit tap its rung requires.
        # In the same badge, because "is there work" is one question.
        return proposed + len(systems.plans_needing_action(tenant))
    except Exception:                                            # noqa: BLE001
        return 0


def _every_note(every: bool, what: str) -> str:
    """Say, on the page itself, that this one is about every account.

    A cross-account screen that looks like a single-account screen is the whole
    defect this session fixed; the banner is what stops the fixed version from
    quietly becoming it again.
    """
    return (f'<div class="everynote"><b>All accounts.</b> {_esc(what)}</div>'
            if every else "")


def _shell(key: str, tab: str, title: str, body: str, suffix: str = "",
           tenant: str = "", head: str = "") -> str:
    """Sidebar, client switcher, then the page.

    The console used a horizontal tab bar and a SEPARATE client picker inside
    four of the five tabs. Two consequences, both daily: the nav links carried
    no tenant, so moving between tabs silently dropped you back to the first
    account; and with the picker below the fold you could read a whole screen
    without ever seeing whose data it was.

    So the account moves into the frame. It is chosen once, it travels on every
    link, and it is named at the top of every page — the same shape the client
    portal uses, because switching between the two should not mean learning a
    second layout.
    """
    tenant, here, rows = _account(tenant)

    hues = _hues(rows)
    switch = "".join(
        f'<a class="{"on" if r.key == tenant else ""}" '
        f'style="--tint:{hues.get(r.key, "")}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab={tab}&amp;tenant={_esc(r.key)}">'
        f'<span class="dot"></span>{_esc(r.name)}</a>' for r in rows)
    # Cross-account is a place you go on purpose, listed apart from the clients
    # so it can never be the account you are on without having chosen it.
    switch += (f'<a class="every {"on" if tenant == ALL else ""}" '
               f'href="/admin/ui?key={_esc(key)}&amp;tab={tab}&amp;tenant={ALL}">'
               f'<span class="dot"></span>All accounts</a>')

    nav = "".join(
        f'<a class="{"on" if t == tab else ""}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab={t}&amp;tenant={_esc(tenant)}'
        f'{suffix if t == tab else ""}"><span class="ico">{i}</span>{label}'
        + (f'<span class="navbadge" title="proposals waiting for review">'
           f'{_rw}</span>'
           if t == "content" and (_rw := _review_waiting(tenant)) else "")
        + '</a>'
        for t, label, i in _TABS)

    # How many decisions are waiting, FOR THIS ACCOUNT, on every page.
    #
    # `approvals.pending_count` was written and never called, so the one number
    # that says whether this system is waiting on a person was visible nowhere.
    # A queue nobody can see the depth of is a queue that stops being worked --
    # which this codebase has already lived through once, at ~200 drafts.
    #
    # It counted every account, so the number beside one client's name was
    # another client's backlog. Scoped now, and the link carries the account
    # through, so clicking it does not silently widen what you are looking at.
    try:
        from . import approvals as _ap
        _n = _ap.pending_count("" if tenant == ALL else tenant)
    except Exception:                                            # noqa: BLE001
        _n = 0                 # never let a counter break the console
    waiting = (f'<a class="pend" href="/admin/pending?key={_esc(key)}'
               f'&amp;tenant={_esc(tenant)}">'
               f'<span class="ico">!</span>{_n} waiting</a>' if _n else "")

    who = _account_name(tenant, here)
    # The client view is one account's page; there is no portal for "all".
    client_view = ("" if tenant == ALL else
                   f'<a href="/portal?tenant={_esc(tenant)}&amp;key={_esc(key)}">'
                   f'Client view &rarr;</a>')

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} — {_esc(who)}</title>
<style>{_CSS}</style>{head}</head><body class="{"every" if tenant == ALL else ""}"
 style="--tint:{hues.get(tenant, "")}">
<div class="shell">
  <div class="side">
    <div class="brand">Saias Ops</div>
    <div class="swlabel">Account</div>
    <div class="switch">{switch}</div>
    <div class="navlabel">Manage</div>
    {nav}
    <div class="foot">{waiting}{client_view}</div>
  </div>
  <div class="main">
    <div class="pagehead"><h1>{_esc(title)}</h1>
      <span class="who">{_esc(who)}</span></div>
    {body}
  </div>
</div></body></html>"""


def _esc(v) -> str:
    return html.escape(str(v or ""), quote=True)


def _chips(caps: dict) -> str:
    return "".join(
        f'<span class="chip {"on" if ok else "off"}">{c}</span>'
        for c, ok in caps.items())


def _routes_panel(expanded: bool | None = None) -> str:
    """Which ways of connecting work at all — the plumbing, not one account.

    Every other thing on this tab answers "is this ACCOUNT connected", which is
    the wrong question when the answer is "nobody can connect, because an app
    credential is unset". Those are different problems with different owners,
    and only one of them is fixable by the person reading a client's card.

    Shopify is the case that earned this panel: its one-click route is built and
    deployed, and with the app credentials unset the button did not render
    anywhere — so connecting a store meant walking a merchant through developer
    settings, ticking nine API scopes and copying a token shown exactly once,
    with nothing on any screen saying the easy route existed.

    **Collapsed by default since 2026-08-21** (owner: the tab led with two
    blocks of instructions and buried the account's actual state). It OPENS
    ITSELF when it has something urgent — a prerequisite warning, or a provider
    where no route works at all — because that is the one moment the plumbing
    is the headline. A parked route on a provider that still connects fine is
    background, and reads here as one summary line until opened.
    """
    from . import credentials as cred
    r = cred.routes()

    warn = ""
    for w in r["warnings"]:
        warn += (f'<div class="note"><strong>{_esc(w["what"])}</strong>'
                 f'<div class="mut">{_esc(w["detail"])}</div>'
                 f'<div class="when">{_esc(w["fix"])}</div></div>')

    rows = ""
    for p in r["providers"]:
        chip = ('<span class="chip off">no route works</span>' if p["dead"]
                else ('<span class="chip nb">one route only</span>' if p["degraded"]
                      else '<span class="chip on">ready</span>'))
        ways = ""
        for w in p["ways"]:
            if w["ok"]:
                ways += (f'<div class="mut">✓ <strong>{_esc(w["label"])}</strong>'
                         f' — {_esc(w["effort"])}</div>')
                if w["action"]:
                    ways += f'<div class="when">{_esc(w["action"])}</div>'
            else:
                # The blocked route is the useful row: it is the one somebody
                # can go and unblock, and the one whose absence is otherwise
                # indistinguishable from the feature not existing.
                ways += (f'<div class="mut">✗ <strong>{_esc(w["label"])}</strong>'
                         f' — would be: {_esc(w["effort"])}</div>'
                         f'<div class="when">Blocked by: {_esc(w["why"])}</div>'
                         + (f'<div class="when">{_esc(w["action"])}</div>'
                            if w["action"] else ""))
            if w.get("caveat"):
                # True whether the route is on or off, and it fails QUIETLY:
                # switching the button on does not make the data complete, and
                # a redacted field reads as an empty account rather than as an
                # error. Cheaper on the screen than discovered in a report.
                ways += (f'<div class="note">Even once it is on — '
                         f'{_esc(w["caveat"])}</div>')
        rows += (f'<div class="card"><div class="head">'
                 f'<h2>{_esc(p["name"])}</h2><code>{_esc(p["capability"])}</code>'
                 f'{chip}</div>{ways}</div>')

    def _short(names: list[str]) -> str:
        names = [n.split(" (")[0] for n in names]
        return (", ".join(names[:3])
                + (f" +{len(names) - 3} more" if len(names) > 3 else ""))

    dead = [p["name"] for p in r["providers"] if p["dead"]]
    degraded = [p["name"] for p in r["providers"] if p["degraded"] and not p["dead"]]
    if r["warnings"]:
        verdict = "a prerequisite needs attention"
    elif dead:
        verdict = "no route works for " + _short(dead)
    elif degraded:
        verdict = "all connectable · one-click parked for " + _short(degraded)
    else:
        verdict = "every route works"
    # Self-opens ONLY on a prerequisite warning — something that breaks every
    # connection and is fixable right now. A dead OAuth-only provider is a
    # standing state (Canva until its app creds exist), and a panel that opens
    # on a standing state is open forever, which is the wall this fold
    # replaced. The verdict line above names the dead ones without opening.
    is_open = bool(r["warnings"]) if expanded is None else expanded
    return f"""
    <details class="sec"{" open" if is_open else ""}>
      <summary>Connection routes — {_esc(verdict)}</summary>
      <div class="mut">The plumbing itself, not any one account. A route that
      is switched off does not appear as a button anywhere, on this console or
      on a client's connect page — an absent button and an unbuilt feature look
      identical, which is why the off ones are listed here.</div>
      {warn}
      {rows}
      <div class="when">{_esc(r["redirect_uri_note"])}</div>
    </details>"""


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
            # Named, not hidden — but QUIETLY: the blocker is an env var
            # someone can go and set, and it belongs on the page (saying which
            # is the difference between a blocker and a feature that reads as
            # unbuilt) without being the loudest thing on the row. The redirect
            # URI rides along because it is the other half of the job and the
            # half that fails silently on a byte mismatch.
            from . import oauth as _oauth
            action = (f'<details><summary class="mut">Not connectable yet — '
                      f'how to switch it on</summary>'
                      f'<div class="mut">{_esc(r["blocked_by"])}</div>'
                      f'<div class="when">Then register this redirect URI, '
                      f'exactly:<br><code>{_esc(_oauth.redirect_uri(r["provider"]))}'
                      f'</code></div></details>')
        elif r["has_oauth"]:
            # An API-key provider that ALSO has a one-click route — Shopify.
            # Both are correct and which one is right depends on whose store it
            # is: a custom-app token is five minutes for a store you own, while
            # OAuth is what lets a CLIENT connect theirs without being walked
            # through Shopify's developer settings, ticking nine API scopes and
            # copying a token that is revealed exactly once.
            #
            # Neither of those was on this page. The branch above asks
            # `kind == "oauth"`, Shopify's kind is `api_key`, so it fell to the
            # empty `else` — and the paste form was presented as the only way to
            # connect a store, on the owner's own console.
            from . import oauth as _oauth
            if not r["oauth_blocked_by"]:
                shop_field = ('<input name="shop" placeholder="handle.myshopify.com" '
                              'required>' if r["shop_scoped"] else "")
                action = (
                    f'<form method="get" action="/admin/oauth/{_esc(r["provider"])}" '
                    f'class="inl"><input type="hidden" name="key" value="{_esc(key)}">'
                    f'<input type="hidden" name="tenant" value="{_esc(tenant)}">'
                    f'{shop_field}<button class="sec">Sign in with '
                    f'{_esc(r["name"].split(" (")[0])}</button></form>'
                    f'<div class="mut">One click for the merchant — no token to '
                    f'copy. The form below still works for a store you already '
                    f'hold a token for.</div>')
            else:
                # PARKED BY CHOICE, and the page says so (owner, 2026-08-21:
                # this rendered as a shouty "Blocked by:" wall on every visit,
                # nagging about a flow he had deliberately decided not to use).
                # One-click OAuth is the client self-serve path; the working
                # paths today are the token form below and a per-store
                # client_id/secret entry in SHOPIFY_STORES_JSON. The env var
                # and redirect URI stay ON the page — inside the fold — for
                # whenever a client actually wants self-serve.
                action = (
                    f'<details><summary class="mut">One-click sign-in — '
                    f'parked until a client wants self-serve</summary>'
                    f'<div class="mut">Connecting works today via the token '
                    f'form below, or a per-store client_id/secret entry in '
                    f'SHOPIFY_STORES_JSON. To switch the one-click route on '
                    f'instead: {_esc(r["oauth_blocked_by"])}</div>'
                    f'<div class="when">Then register this redirect URI, '
                    f'exactly:<br><code>'
                    f'{_esc(_oauth.redirect_uri(r["provider"]))}</code></div>'
                    f'</details>')
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

        # The same two-ways choice the client page offers, for the owner
        # connecting an account himself.
        if r.get("oauth_too"):
            shop_field = ('<input name="shop" placeholder="your-handle.myshopify.com"'
                          ' required>' if r.get("shop_scoped") else "")
            form = f"""
            <details class="cform">
              <summary>Sign in with {_esc(r['name'])}</summary>
              <div class="note">One click, and the merchant approves the
              permissions on {_esc(r['name'])}'s own screen. Use this for a
              client's store; the token form below is for one you already
              hold a key for.</div>
              <form method="get" action="/admin/oauth/{_esc(r['provider'])}" class="f">
                <input type="hidden" name="key" value="{_esc(key)}">
                <input type="hidden" name="tenant" value="{_esc(tenant)}">
                {shop_field}
                <div class="row"><button>Sign in</button></div>
              </form>
            </details>{form}"""

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
    </details>
    """ + _people(tenant, key)


def _people(tenant: str, key: str) -> str:
    """Who from this client can sign in, and with what.

    Read-only is the DEFAULT and is shown as the plain state rather than as a
    restriction, because that is what it is: the portal shows a client their
    own commercial data and lets them hand us figures we will print in a
    report, and full access is the thing that should need a decision.
    """
    from . import portal as _p
    rows = ""
    for u in _p.people(tenant):
        full = u["access"] == "full"
        revoked = u["status"] != "active"
        chip = ('<span class="chip off">revoked</span>' if revoked
                else f'<span class="chip {"on" if full else "nb"}">'
                     f'{"full access" if full else "read only"}</span>')
        hidden = (f'<input type="hidden" name="key" value="{_esc(key)}">'
                  f'<input type="hidden" name="tenant" value="{_esc(tenant)}">'
                  f'<input type="hidden" name="user_id" value="{_esc(u["id"])}">')
        buttons = ""
        if not revoked:
            nxt = "read_only" if full else "full"
            buttons = (
                f'<form method="post" action="/admin/person_access" class="inl">'
                f'{hidden}<button class="sec" name="action" value="{nxt}">'
                f'{"Make read only" if full else "Give full access"}</button></form>'
                f'<form method="post" action="/admin/person_access" class="inl">'
                f'{hidden}<button class="sec" name="action" value="revoke">'
                f'Revoke</button></form>')
            if u["can_sign_in"]:
                buttons += (f'<a href="/admin/portal_link?key={_esc(key)}'
                            f'&amp;email={_esc(u["email"])}">'
                            f'<button class="sec" type="button">Sign-in link'
                            f'</button></a>')
        note = ""
        if u["unused_links"]:
            note = (f'<div class="when">{u["unused_links"]} unused sign-in '
                    f'link(s) outstanding &mdash; revoking kills them</div>')
        elif not u["email"]:
            note = ('<div class="when">No email, so they cannot sign in to the '
                    'portal &mdash; this is a chat-only user</div>')
        rows += (f'<div class="conn"><div><strong>{_esc(u["name"])}</strong> '
                 f'{chip}<div class="mut">{_esc(u["email"]) or "no email"}</div>'
                 f'{note}</div><div class="row">{buttons}</div></div>')

    return f"""
    <div class="anchor" id="people"></div>
    <details class="conns" open>
      <summary>People who can sign in</summary>
      <p class="mut">The portal shows this client their own numbers and lets
      them send us figures we will print in a report. <b>Read only</b> is the
      default; full access is a decision. Revoking also kills any sign-in link
      they have not used yet &mdash; without that, one already sitting in a
      mailbox still works.</p>
      {rows or '<div class="mut" style="padding:8px 0">Nobody yet.</div>'}
      <form method="post" action="/admin/person_save" class="f"
            style="margin-top:12px">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="tenant" value="{_esc(tenant)}">
        <label>Their email</label>
        <input name="email" type="email" placeholder="name@client.com" required>
        <label>Their name</label>
        <input name="name" placeholder="Ellis">
        <label>Access</label>
        <select name="access">
          <option value="read_only">read only &mdash; can look, cannot change</option>
          <option value="full">full &mdash; can send us figures and connect tools</option>
        </select>
        <div class="row"><button>Add them</button></div>
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


def render(key: str, tenant: str = "", msg: str = "", err: str = "",
           link: str = "") -> str:
    """Connections for ONE account.

    This used to render every account stacked on one page, which is how it
    stayed while the console had no client switcher — but it is the screen
    where getting the wrong account is most expensive, because the buttons on
    it revoke credentials and mint links. One account at a time, named in the
    frame, is the point of the whole rearrangement.
    """
    tenant, _here, rows = _account(tenant)
    if tenant == ALL:
        return _shell(key, "accounts", "Connections", tenant=tenant,
                      body=_every_note(True, "These buttons revoke credentials "
                                       "and mint client links, so they are only "
                                       "ever offered for one named account."))
    rows = [r for r in rows if r.key == tenant]
    if not rows:
        # The routes panel EXPANDED here: with no accounts yet, "can anyone
        # connect at all" is the only question on this page that HAS an answer,
        # and it is the one a fresh install needs.
        panel = _routes_panel(expanded=True)
        body = ('<div class="note">No accounts yet. Run '
                '<code>/admin/register_owner</code> first — it seeds the five.</div>')
    else:
        panel = _routes_panel()
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
              <form class="row" method="get" action="/admin/tenant_set"
                    style="align-items:center;gap:8px">
                <input type="hidden" name="key" value="{_esc(key)}">
                <input type="hidden" name="tenant" value="{_esc(t.key)}">
                <input type="hidden" name="field" value="business_model">
                <input type="hidden" name="ui" value="1">
                <label style="white-space:nowrap"><b>Business model</b></label>
                <select name="value">{_model_options(t.business_model or "")}</select>
                <button class="sec">Save</button>
                <span class="mut">decides which segments get built and which
                numbers their report speaks{' — <b>unset: segments and reports refuse until this is chosen</b>' if not (t.business_model or '') else ''}</span>
              </form>
              {_connections(t.key, key)}
              <details class="sec">
                <summary>Raw wiring — this account's connection keys (advanced)</summary>
                <div class="mut">These fields are <strong>keys into</strong>
                credential dictionaries or env-var names — never secrets. The
                secrets themselves are either in the Render env group or, for
                anything a client connected themselves, encrypted in the
                database and shown above only as a state. Saving reloads to a
                JSON response — hit back to return here; changes take effect
                immediately, no redeploy.</div>
                <div class="grid">{fields}</div>
              </details>
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
    if note:
        note = f'<div class="flash">{note}</div>'

    # Order (owner, 2026-08-21): the result of what you just did, then the
    # selected account's actual state — the question the tab exists to answer —
    # and only then the rarely-used admin forms and the plumbing, folded. The
    # old page led with two blocks of instructions and two create-forms, and
    # the account's connections sat below all of it.
    return _shell(key, "accounts", "Connections", tenant=tenant, body=f"""
{note}
<div>
  <h1>Connections</h1>
</div>

{body}

<details class="sec">
  <summary>Add an account</summary>
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
        <option value="own">own</option></select></div>
    <div class="f"><label>what kind of business</label>
      <div class="what">Decides which numbers their report carries &mdash; a
        venue is measured in events booked, a store in average order value</div>
      <select name="business_model">{_model_options()}</select>
      <div class="row"><button>Create</button></div></div>
  </form>
  <div class="when">Saving reloads to a JSON response — hit back to return
  here. Changes take effect immediately; no redeploy.</div>
</details>

<details class="sec">
  <summary>Give someone bot access</summary>
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
</details>

{panel}
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

    # Proof that the promise above is kept.
    #
    # That sentence was written when `feedback_block` had no caller anywhere in
    # the codebase: guidance was saved, displayed, and read by nothing. It is
    # wired now, and the card says so with the actual size of what reaches the
    # prompt — because "it is injected" is exactly the kind of claim this
    # console exists to stop taking on trust.
    live = ""
    try:
        note_txt = systems.feedback_block(row.tenant, row.key)
        edit_txt = systems.edit_lessons(row.tenant, row.key)
        bits = []
        if note_txt:
            bits.append(f"{len(msgs)} correction(s) you wrote")
        if edit_txt:
            bits.append("plus the edits you made to recent drafts")
        if bits:
            live = (f'<div class="ok" style="margin:10px 0">In the prompt now: '
                    f'{_esc(" — ".join(bits))}. Injected on every draft this '
                    f'system writes, and on no other system.</div>')
        else:
            live = ('<div class="note" style="margin:10px 0">Nothing is being '
                    'injected yet. Guidance appears here once written; edits '
                    'appear once you approve a draft you changed.</div>')
    except Exception:                                            # noqa: BLE001
        pass

    return f"""
    <details><summary>Thread — guidance and corrections ({len(msgs)})</summary>
      {live}
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
    # Queue is not activity here either: a planned row is a card in the
    # Planned section, and listing it again as a "run" would count work that
    # has not happened (and disagree with the stats beside it, which already
    # exclude it).
    rows = [r for r in systems.runs(row.id, limit=0)
            if r.stage != systems.PLANNED][:8]
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


def _measured(row) -> dict:
    """Sent-as-is, from the deltas that were actually captured.

    `edit_diff` is written by `edits.record` as JSON when a draft is sent;
    a run without one is UNMEASURED, which is a different fact from "sent
    as-is" and is reported beside it rather than folded in — 0% edited would
    be the lie that flatters the generator most.
    """
    rows = [r for r in systems.runs(row.id, limit=0)
            if r.stage != systems.PLANNED]
    measured = as_is = 0
    for r in rows:
        if not (r.edit_diff or "").strip():
            continue
        measured += 1
        try:
            if json.loads(r.edit_diff).get("as_is"):
                as_is += 1
        except (ValueError, AttributeError):
            pass
    unmeasured = sum(1 for r in rows if r.stage in ("sent", "approved")
                     and not (r.edit_diff or "").strip())
    return {"measured": measured, "as_is": as_is, "unmeasured": unmeasured}


def _pending_for_system(row, limit: int = 300) -> list:
    """This system's approvals still waiting on a person.

    Matched by `system_id` OR by `run_id`, because the two pipelines wire
    the join from different ends (the substrate sets both; the mail path
    sets the run) — and a check that consults one ledger fails exactly when
    it matters, which is the `replies.owner()` lesson one table over.
    """
    run_ids = {r.id for r in systems.runs(row.id, limit=limit)}
    with db.SessionLocal() as s:
        rows = (s.query(db.Approval)
                .filter(db.Approval.tenant == row.tenant,
                        db.Approval.status == "pending")
                .order_by(db.Approval.created_at.desc()).limit(limit).all())
        s.expunge_all()
    return [a for a in rows
            if a.system_id == row.id or (a.run_id and a.run_id in run_ids)]


def _shipped_runs(row, days: int = 0, limit: int = 0) -> list:
    """Terminal, produced runs — what actually went out or was approved."""
    import datetime as _dt
    rows = [r for r in systems.runs(row.id, limit=0)
            if r.stage in ("sent", "approved") and r.decision != "denied"]
    if days:
        since = db.utcnow() - _dt.timedelta(days=days)
        rows = [r for r in rows
                if db.as_utc(r.finished_at or r.created_at) >= since]
    return rows[:limit] if limit else rows


def _sysview_url(key: str, row, anchor: str = "", ppage: int = 0) -> str:
    url = (f"/admin/ui?key={_esc(key)}&amp;tab=systems"
           f"&amp;tenant={_esc(row.tenant)}&amp;system={_esc(row.key)}")
    if ppage and ppage > 1:
        url += f"&amp;ppage={ppage}"
    return url + (f"#{anchor}" if anchor else "")


def _work_strip(key: str, row) -> str:
    """One line of state per system: what is queued, waiting, shipped, kept.

    Counts, each linking into the section of the system's own view that
    holds the rows behind it — state first, and the click lands on the work
    rather than on an explanation of it.
    """
    bits: list[str] = []
    if systems.plan_capable(row.key):
        n = len(systems.plans(row.tenant, row.key))
        bits.append(f'<a href="{_sysview_url(key, row, "planned")}">'
                    f'<b>{n}</b> planned</a>')
    waiting = len(_pending_for_system(row))
    bits.append(f'<a href="{_sysview_url(key, row, "waiting")}">'
                f'<b>{waiting}</b> waiting on you</a>')
    week = len(_shipped_runs(row, days=7))
    bits.append(f'<a href="{_sysview_url(key, row, "shipped")}">'
                f'<b>{week}</b> shipped this week</a>')
    m = _measured(row)
    if m["measured"]:
        bits.append(f'<a href="{_sysview_url(key, row, "measured")}">'
                    f'<b>{m["as_is"]} of {m["measured"]}</b> sent as-is</a>')
    return '<div class="workstrip">' + " · ".join(bits) + "</div>"


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
        <a class="btn sec" href="{_sysview_url(key, row)}">Workflow &rarr;</a>
      </div>
      <div class="mut">{_esc(systems.spec(row.key)["does"])}</div>
      {_work_strip(key, row)}
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


PLANS_PAGE = 15


def _plan_field_input(f: dict, value, tenant: str = "") -> str:
    """One declared plan field as a prefilled control — rule 13: nothing the
    owner can see is display-only, and the control shows what IS before
    offering what could be."""
    label = _esc(f.get("label") or f["key"])
    req = ('<div class="what">required — the plan cannot run without it</div>'
           if f.get("required") else "")
    if f.get("kind") == "segment":
        # A REFERENCE, not free text (owner, 2026-08-21): the options are
        # the account's own segment catalog, and the data layer refuses any
        # key outside it — so the select is a convenience over a rule, not
        # the rule itself. Linked-in-the-ESP status rides each option from
        # the last sync's record.
        from . import segments as segmod
        got = segmod.for_tenant(tenant)
        cur = str(value or "").strip()
        if not got.get("ok"):
            note = f'<div class="what">{_esc(got.get("error", ""))}</div>'
            opts = (f'<option value="" selected>— unavailable —</option>'
                    + (f'<option value="{_esc(cur)}" selected>{_esc(cur)}'
                       f'</option>' if cur else ""))
            return (f'<div class="f"><label>{label}</label>{req}{note}'
                    f'<select name="{_esc(f["key"])}">{opts}</select></div>')
        linked = {s.get("key") for s in
                  ((segmod.stored_state(tenant) or {}).get("linked") or [])}
        opts = [f'<option value=""{"" if cur else " selected"}>— choose a '
                f'segment —</option>']
        seen = False
        for s in got["segments"]:
            seen = seen or s["key"] == cur
            tag = ("high value" if s["tier"] == "high_value" else "common")
            in_esp = " · in the ESP" if s["key"] in linked else ""
            opts.append(
                f'<option value="{_esc(s["key"])}"'
                f'{" selected" if s["key"] == cur else ""}>'
                f'{_esc(s["name"])} — {tag}{in_esp}</option>')
        if cur and not seen:
            # An old plan holding a key the catalog no longer has renders
            # the truth rather than silently snapping to something else.
            opts.append(f'<option value="{_esc(cur)}" selected>{_esc(cur)} '
                        f'(unknown key)</option>')
        return (f'<div class="f"><label>{label}</label>{req}'
                f'<select name="{_esc(f["key"])}">{"".join(opts)}</select>'
                f'</div>')
    if f.get("kind") == "entity":
        # Same rule as segments: a reference into the catalogue, never free
        # text. Options are this account's real entities, in-stock first;
        # the data layer refuses any key outside them.
        cur = str(value or "").strip()
        rows = sorted(kb.entities(tenant, available_only=False),
                      key=lambda r: ((r.availability or "available") != "available",
                                     (r.name or "").lower()))
        opts = [f'<option value=""{"" if cur else " selected"}>— none — the '
                f'top catalogue items are featured —</option>']
        seen = False
        for r in rows:
            seen = seen or r.key == cur
            oos = " · out of stock" if (r.availability or "") == "oos" else ""
            opts.append(f'<option value="{_esc(r.key)}"'
                        f'{" selected" if r.key == cur else ""}>'
                        f'{_esc(r.name or r.key)}{oos}</option>')
        if cur and not seen:
            opts.append(f'<option value="{_esc(cur)}" selected>{_esc(cur)} '
                        f'(unknown key)</option>')
        note = ("" if rows else
                '<div class="what">the catalogue is empty — run the '
                'catalogue sync on the Review tab first</div>')
        return (f'<div class="f"><label>{label}</label>{req}{note}'
                f'<select name="{_esc(f["key"])}">{"".join(opts)}</select>'
                f'</div>')
    if f.get("kind") == "choice":
        # A fixed vocabulary the skill understands. Rendered as a select for
        # the same reason segment is: a typo in a free-text field would read
        # downstream as "unset" and silently change what the send is.
        cur = str(value or "").strip().lower()
        opts = "".join(
            f'<option value="{_esc(v)}"{" selected" if v == cur else ""}>'
            f'{_esc(v)}</option>'
            for v in ("",) + tuple(f.get("choices") or ()))
        return (f'<div class="f"><label>{label}</label>{req}'
                f'<div class="what">blank = the planner decides, rotating so '
                f'this list is given to more often than it is asked</div>'
                f'<select name="{_esc(f["key"])}">{opts}</select></div>')
    if f.get("kind") == "flag":
        cur = str(value or "").strip().lower()
        state = ("yes" if cur in ("1", "true", "yes", "y", "on")
                 else "no" if cur else "")
        opts = "".join(
            f'<option value="{v}"{" selected" if v == state else ""}>{t}</option>'
            for v, t in (("", "— unset —"), ("yes", "yes"), ("no", "no")))
        return (f'<div class="f"><label>{label}</label>{req}'
                f'<select name="{_esc(f["key"])}">{opts}</select></div>')
    return (f'<div class="f"><label>{label}</label>{req}'
            f'<input name="{_esc(f["key"])}" value="{_esc(str(value or ""))}">'
            f'</div>')


def _plan_card(key: str, row, p, rung: str, live: bool, ppage: int) -> str:
    """One queued item: its state, then its prefilled edit form."""
    brief = p.brief or {}
    plan = brief.get("plan") or {}
    comp = systems.plan_complete(p, row.key)
    approved = bool(brief.get("plan_approved_at"))
    when = str(brief.get("planned_for") or "")
    low_rung = rung in ("shadow", "approve_all")

    if not comp["complete"]:
        state = ('<span class="pre no">✗ needs completing: '
                 + _esc(", ".join(comp["missing"])) + "</span>")
        ok = False
    elif low_rung and not approved:
        state = ('<span class="pre no">complete — awaiting your approval'
                 '</span>')
        ok = False
    elif low_rung:
        state = f'<span class="pre yes">✓ approved — runs {_esc(when)}</span>'
        ok = True
    else:
        state = (f'<span class="pre yes">runs {_esc(when)} — no tap needed '
                 f'on {_esc(rung.replace("_", " "))}</span>')
        ok = True

    # The date makes a plan eligible for the MORNING TICK; a person is the
    # other trigger. "Run now" consumes THIS plan through skill.run — the
    # same take_plan gates as the tick, so nothing about safety changes,
    # only who pulled the trigger (owner, 2026-08-21: "putting today's date
    # didn't work" — filing after 07:00 meant waiting for tomorrow's tick).
    _actions = (f'key={_esc(key)}&amp;id={_esc(p.id)}&amp;tenant='
                f'{_esc(row.tenant)}&amp;system={_esc(row.key)}'
                f'&amp;ppage={ppage}')
    approve = ""
    if live and comp["complete"] and low_rung and not approved:
        approve = (f'<a href="/admin/plan_approve?{_actions}">'
                   f'<button type="button">Approve plan</button></a>'
                   f'<a href="/admin/plan_run?{_actions}&amp;approve=1">'
                   f'<button class="sec" type="button">Approve &amp; run '
                   f'now</button></a>')
    elif live and comp["complete"]:
        approve = (f'<a href="/admin/plan_run?{_actions}">'
                   f'<button type="button">Run now</button></a>')

    fields = "".join(_plan_field_input(f, plan.get(f["key"], ""), row.tenant)
                     for f in systems.workflow(row.key)["plan_fields"])
    return f"""
    <div class="plan {'ok' if ok else 'gap'}" id="plan-{_esc(p.id)}">
      <div class="planhead">
        <b>{_esc(p.ref or "(no key)")}</b>
        {state}
        <span class="grow"></span>
        {approve}
      </div>
      <form method="get" action="/admin/plan_save">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="id" value="{_esc(p.id)}">
        <input type="hidden" name="tenant" value="{_esc(row.tenant)}">
        <input type="hidden" name="system" value="{_esc(row.key)}">
        <input type="hidden" name="ppage" value="{ppage}">
        <div class="planfields">
          {fields}
          <div class="f"><label>planned for</label>
            <div class="what">the date it may run — a dateless plan is never due</div>
            <input type="date" name="planned_for" value="{_esc(when)}"></div>
        </div>
        <div class="row" style="margin-top:8px"><button>Save changes</button>
          <span class="mut">a blank box leaves its field as it is — saving is
          a re-attestation, and your edits survive the planner's next pass</span>
        </div>
      </form>
      <div class="when">filed {p.created_at:%b %d, %H:%M} · {_esc(p.trigger or "")}</div>
      <details><summary class="mut">skip this plan</summary>
        <form method="get" action="/admin/plan_skip" class="row" style="margin-top:7px">
          <input type="hidden" name="key" value="{_esc(key)}">
          <input type="hidden" name="id" value="{_esc(p.id)}">
          <input type="hidden" name="tenant" value="{_esc(row.tenant)}">
          <input type="hidden" name="system" value="{_esc(row.key)}">
          <input name="reason" placeholder="why (optional — kept on the record)">
          <button class="sec">Skip</button>
        </form>
      </details>
    </div>"""


def _planned_section(key: str, row, ppage: int) -> str:
    """The queue: what this system intends to do, editable before it does."""
    wf = systems.workflow(row.key)
    if not systems.plan_capable(row.key):
        if row.key in systems.externally_driven():
            why = ("This system takes no plans — its work arrives on its own "
                   "trigger (inbound mail, or its weekly schedule), and shows "
                   "up below the moment it happens.")
        else:
            why = ("This system declares no plan fields yet — plans arrive "
                   "when its planner and consuming skill land together.")
        return (f'<div class="card"><div class="head"><h2>Planned</h2></div>'
                f'<p class="mut">{_esc(why)}</p></div>')

    live = systems.is_on(row)
    open_plans = systems.plans(row.tenant, row.key)
    total = len(open_plans)
    pages = max(1, -(-total // PLANS_PAGE))
    ppage = max(1, min(ppage, pages))
    shown = open_plans[(ppage - 1) * PLANS_PAGE: ppage * PLANS_PAGE]
    rung = row.autonomy or "shadow"

    cards = "".join(_plan_card(key, row, p, rung, live, ppage) for p in shown)

    pager = ""
    if pages > 1:
        def _pg(n: int) -> str:
            return _sysview_url(key, row, "planned", ppage=n)
        pager = ('<div class="pager"><span class="mut">plans '
                 f'{(ppage - 1) * PLANS_PAGE + 1}&ndash;'
                 f'{(ppage - 1) * PLANS_PAGE + len(shown)} of {total}</span>'
                 + (f'<a href="{_pg(ppage - 1)}">&larr; sooner</a>'
                    if ppage > 1 else "")
                 + (f'<a href="{_pg(ppage + 1)}">later &rarr;</a>'
                    if ppage < pages else "")
                 + "</div>")

    new_fields = "".join(_plan_field_input(f, "", row.tenant)
                         for f in wf["plan_fields"])
    if live:
        create = f"""
        <details class="sec"{"" if total else " open"}>
          <summary>{"Plan another" if total else "Plan one by hand"}</summary>
          <form method="get" action="/admin/plan_new">
            <input type="hidden" name="key" value="{_esc(key)}">
            <input type="hidden" name="tenant" value="{_esc(row.tenant)}">
            <input type="hidden" name="system" value="{_esc(row.key)}">
            <div class="planfields">
              {new_fields}
              <div class="f"><label>planned for</label>
                <div class="what">the date it may run</div>
                <input type="date" name="planned_for"></div>
            </div>
            <div class="row" style="margin-top:8px"><button>File the plan</button></div>
          </form>
        </details>"""
    else:
        create = ('<p class="mut">Filing plans needs the system on — the '
                  'switch is above. Existing plans stay editable meanwhile.</p>')

    from . import planner as _pl
    has_planner = row.key in _pl.PLANNERS

    if total:
        empty = ""
    elif has_planner:
        empty = ('<p class="mut">Nothing is planned. The planner proposes '
                 'daily on the tick, or right now with the button below — '
                 'and plans can always be filed by hand.</p>')
    else:
        empty = ('<p class="mut">Nothing is planned. No planner exists for '
                 'this system yet, so plans are filed by hand — each one '
                 'says what it still needs before it can run.</p>')

    # The planner's knobs, ON the surface they govern (a knob that exists
    # only in code is a knob that does not exist). Folded: cadence is set
    # rarely; the current numbers ride the summary line so the fold never
    # has to be opened just to know them.
    planner_ctl = ""
    if has_planner:
        cad = _pl.cadence_for(row)
        if live:
            propose = f"""
          <form method="get" action="/admin/plan_propose" class="row" style="margin-top:9px">
            <input type="hidden" name="key" value="{_esc(key)}">
            <input type="hidden" name="tenant" value="{_esc(row.tenant)}">
            <input type="hidden" name="system" value="{_esc(row.key)}">
            <button>Propose now</button>
            <span class="mut">runs the planner once — proposes only, consumes nothing</span>
          </form>"""
        else:
            propose = ('<p class="mut" style="margin-top:9px">Proposing needs '
                       'the system on.</p>')
        planner_ctl = f"""
        <details class="sec">
          <summary>Cadence — {cad["per_segment_monthly"]}/segment/month,
            {cad["horizon_days"]}-day horizon</summary>
          <p class="mut">High-value segments only, first proposal two days
          out. The planner proposes from the segment catalog and never
          overwrites your edits; a skipped month stays skipped.</p>
          <form method="get" action="/admin/plan_cadence" class="row">
            <input type="hidden" name="key" value="{_esc(key)}">
            <input type="hidden" name="tenant" value="{_esc(row.tenant)}">
            <input type="hidden" name="system" value="{_esc(row.key)}">
            <div class="f" style="max-width:180px"><label>per segment / month</label>
              <input name="per_segment_monthly" inputmode="numeric"
                     value="{cad["per_segment_monthly"]}"></div>
            <div class="f" style="max-width:180px"><label>horizon, days</label>
              <input name="horizon_days" inputmode="numeric"
                     value="{cad["horizon_days"]}"></div>
            <button class="sec">Set cadence</button>
          </form>
          {propose}
        </details>"""

    return f"""
    <div class="card"><div class="anchor" id="planned"></div>
      <div class="head"><h2>Planned — the queue</h2>
        <span class="mut">{total} open · runs on its date via the morning
        tick, or the moment you press Run now — through every gate either
        way</span></div>
      {empty}{planner_ctl}{pager}{cards}{pager}{create}
    </div>"""


def _waiting_section(key: str, row) -> str:
    pend = _pending_for_system(row)
    if not pend:
        body = '<p class="mut">Nothing is waiting on you.</p>'
    else:
        body = "".join(f"""
        <div class="msg"><div>{_esc(a.summary or a.kind)}</div>
          <div class="when">{a.created_at:%b %d, %H:%M} ·
            <a href="/admin/pending?key={_esc(key)}&amp;tenant={_esc(row.tenant)}">decide &rarr;</a>
          </div></div>""" for a in pend[:15])
    return f"""
    <div class="card"><div class="anchor" id="waiting"></div>
      <div class="head"><h2>Waiting on you</h2>
        <span class="mut">{len(pend)} pending — decisions happen on the approvals queue</span></div>
      <div class="thread">{body}</div>
    </div>"""


def _shipped_section(row) -> str:
    done = _shipped_runs(row)
    week = len(_shipped_runs(row, days=7))
    if not done:
        body = ('<p class="mut">Nothing has shipped yet. When it does, each '
                'one lands here with its decision and its date.</p>')
    else:
        body = "".join(f"""
        <div class="msg"><div><code>{_esc(r.stage)}</code>
          {_esc(r.decision or "")} — {_esc(r.output or "")}</div>
          <div class="when">{(r.finished_at or r.created_at):%b %d, %H:%M} · {_esc(r.ref or r.trigger or "")}</div>
        </div>""" for r in done[:8])
    return f"""
    <div class="card"><div class="anchor" id="shipped"></div>
      <div class="head"><h2>Shipped</h2>
        <span class="mut">{len(done)} all-time · {week} this week</span></div>
      <div class="thread">{body}</div>
    </div>"""


def _measured_section(row) -> str:
    st = systems.stats(row.id)
    m = _measured(row)
    if m["measured"]:
        headline = (f'<span><b>{m["as_is"]} of {m["measured"]}</b> measured '
                    f'sends went as-is</span>')
    else:
        headline = ('<span class="mut">no delta has been measured yet — '
                    'the number arrives with the first sends</span>')
    gap = ""
    if m["unmeasured"]:
        gap = (f'<p class="mut">{m["unmeasured"]} send(s) carry no delta — '
               f'unmeasured, which is a different fact from "sent as-is". '
               f'Mail captures its delta at send; other artifact kinds get '
               f'theirs as their ship paths land.</p>')
    return f"""
    <div class="card"><div class="anchor" id="measured"></div>
      <div class="head"><h2>Measured</h2></div>
      <div class="stat">
        {headline}
        <span><b>{st['decided']}</b> decided</span>
        <span><b>{st['approved']}</b> approved</span>
        <span><b>{st['edited']}</b> edited</span>
        <span><b>{st['denied']}</b> denied</span>
        <span><b>{st['blocked']}</b> blocked</span>
      </div>
      {gap}
    </div>"""


def _segments_card(key: str, row) -> str:
    """The cohorts this system's campaigns target — rendered from the RECORD.

    A page load must never be the moment a live ESP call happens (the
    client_report rule), so everything here comes from the last sync's
    stored state; the buttons do the live work. Building segments is the
    explicit act — dry-run first, and the apply button says it writes to
    the live account.
    """
    from . import segments as segmod
    st = segmod.stored_state(row.tenant)
    base = (f"/admin/segments_sync?key={_esc(key)}&amp;tenant={_esc(row.tenant)}"
            f"&amp;system={_esc(row.key)}")
    sync_btn = f'<a href="{base}"><button type="button">Sync now</button></a>'

    if st is None:
        body = ('<p class="mut">Never synced. Sync reads the live ESP, '
                'remembers the id of every segment that matches the catalog '
                '(a remembered id survives a rename — a name search does '
                'not), and reports what is missing or drifting. It writes '
                'nothing to the ESP.</p>'
                f'<div class="row">{sync_btn}</div>')
        return (f'<div class="card"><div class="anchor" id="segments"></div>'
                f'<div class="head"><h2>Segments</h2>'
                f'<span class="mut">the cohorts campaigns target</span></div>'
                f'{body}</div>')

    when = _esc((st.get("at") or "")[:16].replace("T", " "))
    drift = ""
    if st.get("drift"):
        items = "".join(f"<li>{_esc(d['what'])}</li>" for d in st["drift"])
        drift = (f'<div class="note"><strong>Drift.</strong>'
                 f'<ul class="bl">{items}</ul></div>')

    linked_rows = "".join(f"""
      <div class="msg"><div><b>{_esc(s["name"])}</b>
        {('<span class="mut"> — in the ESP as “' + _esc(s["esp_name"]) + '”</span>')
         if s.get("esp_name") and _esc(s["esp_name"]) != _esc(s["name"]) else ''}
        {('<span class="mut"> · ' + _esc(str(s["esp_count"])) + ' members</span>')
         if str(s.get("esp_count", "")) != "" else ''}</div>
        <div class="when"><code>{_esc(s.get("esp_segment_id", ""))}</code>
          · linked by {_esc(s.get("linked_by") or "sync")}</div>
      </div>""" for s in st.get("linked", []))
    linked = (f'<div class="thread">{linked_rows}</div>' if linked_rows else
              '<p class="mut">Nothing is linked yet.</p>')

    build = ""
    to_build = st.get("to_build", [])
    unmapped = st.get("unmapped", [])
    if to_build:
        chips = "".join(f'<span class="chip off">{_esc(w["name"])}</span>'
                        for w in to_build)
        burl = (f"/admin/segments_build?key={_esc(key)}&amp;tenant="
                f"{_esc(row.tenant)}&amp;ui=1&amp;system={_esc(row.key)}")
        build = (f'<div class="chips">{chips}</div>'
                 f'<div class="row">'
                 f'<a href="{burl}"><button class="sec" type="button">'
                 f'Preview build</button></a>'
                 f'<a href="{burl}&amp;apply=1"><button type="button">'
                 f'Create {len(to_build)} in the ESP</button></a>'
                 f'<span class="mut">preview is a dry run; create WRITES to '
                 f'the live account — segments send nothing and can be '
                 f'deleted in the ESP if wrong</span></div>')
    elif not st.get("build_note"):
        build = '<p class="mut">Every catalog segment the adapter can express exists.</p>'
    if unmapped:
        u = "".join(f"<li><b>{_esc(x['name'])}</b> — {_esc(x['why'])}</li>"
                    for x in unmapped)
        build += (f'<div class="mut">Cannot be built yet:'
                  f'<ul class="bl">{u}</ul></div>')
    if st.get("build_note"):
        build += f'<p class="mut">{_esc(st["build_note"])}</p>'

    return f"""
    <div class="card"><div class="anchor" id="segments"></div>
      <div class="head"><h2>Segments</h2>
        <span class="mut">{len(st.get("linked", []))} linked ·
          {len(to_build)} to build · synced {when} (weekly, and on this
          button)</span></div>
      {drift}
      {linked}
      {build}
      <div class="row">{sync_btn}</div>
    </div>"""


def _system_view(key: str, row, flash: str, ppage: int = 1) -> str:
    """One system's workflow: planned, waiting, shipped, measured — in the
    order the work moves, with the queue's controls leading each section."""
    wf = systems.workflow(row.key)
    live_ctl = ""
    if row.status != "live" and systems.ready(row)["ready"]:
        live_ctl = (f'<a href="/admin/system_set?key={_esc(key)}&amp;id={_esc(row.id)}'
                    f'&amp;status=live"><button type="button">Switch on</button></a>')
    elif row.status == "live":
        live_ctl = (f'<a href="/admin/system_set?key={_esc(key)}&amp;id={_esc(row.id)}'
                    f'&amp;status=paused"><button class="sec" type="button">Pause</button></a>')

    ship_note = (f'<p class="mut">One item is {_esc(wf["unit"])}. '
                 f'Approving {_esc(wf["ship"] or "ships it")}.</p>'
                 if wf["unit"] else "")

    # The gate, on the page whose queue it holds shut. A Planned list on a
    # system that cannot produce reads as "will run on its date" — when the
    # truth is that every attempt is refused until a connection is wired,
    # and a queue that can never drain must say so where the queue is.
    gate = systems.ready(row)
    gate_note = ""
    if not gate["can_produce"]:
        items = "".join(f"<li>{_esc(b)}</li>" for b in gate["impossible"])
        gate_note = ('<div class="note"><strong>Cannot produce.</strong>'
                     f'<ul class="bl">{items}</ul>'
                     '<div class="mut">Plans keep and stay editable; they '
                     'run once this is wired.</div></div>')

    body = f"""
{flash}
<div>
  <div class="crumb"><a href="/admin/ui?key={_esc(key)}&amp;tab=systems&amp;tenant={_esc(row.tenant)}">&larr; Systems</a></div>
  <div class="head" style="border-bottom:0;padding-bottom:0">
    <h1>{_esc(row.name)}</h1>
    <code>{_esc(row.key)}</code>
    <span class="chips">
      <span class="chip {'on' if row.status == 'live' else 'off'}">{_esc(row.status)}</span>
      <span class="chip {'on' if row.autonomy == 'auto' else 'off'}">{_esc(row.autonomy)}</span>
    </span>
    {live_ctl}
  </div>
  {ship_note}
  {_work_strip(key, row)}
  {gate_note}
</div>
{_planned_section(key, row, ppage)}
{_segments_card(key, row) if systems.workflow(row.key)["artifact"] == "esp_campaign" else ""}
{_waiting_section(key, row)}
{_shipped_section(row)}
{_measured_section(row)}
{_runs(row, systems.stats(row.id)['total'])}
<details class="sec"><summary>How to read this page</summary>
  <p class="mut">Planned is work declared in advance — each plan is editable
  until the moment it runs, an incomplete plan waits and names its gaps, and
  on the shadow / approve-all rungs a complete plan still waits for your
  explicit approval because running it has real side effects. Waiting on you
  is this system's approval queue. Shipped is what actually went out.
  Measured is the edit delta — the share of sends a human did not have to
  touch, which is the number this system is trying to move.</p>
</details>"""
    return _shell(key, "systems", f"{row.name} — workflow",
                  tenant=row.tenant, body=body,
                  suffix=f"&amp;system={_esc(row.key)}")


def render_systems(key: str, tenant: str = "", msg: str = "", err: str = "",
                   system: str = "", ppage: int = 1) -> str:
    """One account's pipelines.

    This tab used to render `systems.all_systems()` grouped by client, so the
    account chosen in the sidebar picked which INSTALLER you saw while the
    cards below it were every account's -- five clients' autonomy rungs, kill
    criteria and Guidance boxes stacked on one page, each with a form that
    writes to a different account. The frame said "Miami Ironside" and the
    third card down was Baci's.
    """
    tenant, here, all_t = _account(tenant)
    every = tenant == ALL

    flash = ""
    if err:
        flash = f'<div class="flash"><div class="note">{_esc(err)}</div></div>'
    elif msg:
        flash = f'<div class="flash"><div class="ok">{_esc(msg)}</div></div>'

    # One system's own workflow view — a real place inside the frame, not a
    # hyperlink to somewhere unframed. `system=` on the all-accounts view is
    # ignored: a workflow belongs to one account.
    if system and not every:
        target = systems.find(tenant, system)
        if target is not None:
            return _system_view(key, target, flash, ppage=ppage)
        flash += (f'<div class="note">No <code>{_esc(system)}</code> system '
                  f'is installed for this account — the list below is what '
                  f'is.</div>')

    rows = systems.all_systems() if every else systems.for_tenant(tenant)

    if not rows:
        body = ('<div class="note">No systems on this account yet. '
                '<a href="/admin/systems_seed?key=' + _esc(key) + '">Adopt the ones already '
                'named on each account</a> — it reads <code>Tenant.systems</code> and '
                'creates a row for each, with an empty contract.</div>')
    elif every:
        # Grouped by client, and ONLY here -- the one screen you reach by
        # asking for it. Each group names its account above its own cards.
        by_tenant: dict[str, list] = {}
        for r in rows:
            by_tenant.setdefault(r.tenant, []).append(r)
        body = ""
        for tkey, group in sorted(by_tenant.items()):
            t = tenants.get(tkey)
            cards = "".join(_system_card(key, r) for r in group)
            live = sum(1 for r in group if r.status == "live")
            body += f"""
            <div>
              <div class="head" style="margin-bottom:12px">
                <h2>{_esc(t.name if t else tkey)}</h2>
                <code>{_esc(tkey)}</code>
                <span class="mut">{live} of {len(group)} live</span>
                <a class="btn sec" href="/admin/ui?key={_esc(key)}&amp;tab=systems&amp;tenant={_esc(tkey)}">Open this account</a>
              </div>
              {cards}
            </div>"""
    else:
        live = sum(1 for r in rows if r.status == "live")
        body = f"""
        <div>
          <div class="head" style="margin-bottom:12px">
            <h2>Installed</h2>
            <span class="mut">{live} of {len(rows)} live</span>
          </div>
          {"".join(_system_card(key, r) for r in rows)}
        </div>"""

    # Scoped to the account too. An unscoped backlog ranks another client's
    # missing knowledge above this one's, and the fix it points at is filed
    # against a knowledge base this page cannot reach.
    backlog = systems.blocked_reasons("" if every else tenant)
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
    def _pre_chip(i: dict) -> str:
        mark = "✓" if i["met"] else "✗"
        note = f' <span class="mut">{_esc(i["note"])}</span>' if i["note"] else ""
        return (f'<span class="pre {"yes" if i["met"] else "no"}">{mark} '
                f'{_esc(i["name"])}{note}</span>')

    cards = ""
    for p in ([] if every else (systems.installable(tenant) if tenant else [])):
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
        # What installing this one actually gets you, when the mail path is
        # already doing the work. Without this the card reads as "switch on a
        # pipeline", when the honest description is "start governing a kind of
        # mail triage is answering anyway" — which is a different and much
        # easier decision.
        from . import replies as _rep
        mail_owned = ""
        if p["key"] in set(_rep.ROUTES.values()):
            kinds = ", ".join(sorted(b for b, k in _rep.ROUTES.items()
                                     if k == p["key"]))
            mail_owned = (f'<div class="when">Triage already answers this mail. '
                          f'Installing it does not change who writes the reply — '
                          f'it gives <b>{_esc(kinds)}</b> its own ledger, '
                          f'guidance and autonomy rung, so a correction here '
                          f'teaches only this kind of mail.</div>')
        cards += f"""
        <div class="inst {"done" if p["installed"] else ("ok" if p["ready"] else "gap")}">
          <div class="insthead">
            <b>{_esc(p["name"])}</b>
            <code>{_esc(p["key"])}</code>
            <span class="grow"></span>
            {action}
          </div>
          <div class="when">{_esc(p["does"])}</div>
          {mail_owned}
          <div class="prereqs">{chips}</div>
        </div>"""

    # Installing writes to ONE account, so the form is not offered on a screen
    # that is about all of them -- there would be no account for it to mean.
    installer = "" if every else f"""
<div class="card">
  <div class="head"><h2>Install a system</h2></div>
  <p class="mut">Everything in the catalogue for this account, with what each one
  needs and whether it has it. <b>✓</b> is wired or written, <b>✗</b> is not.
  A system starts in <em>designed / shadow</em> — it records and sends nothing —
  and the 8-part contract is optional — worth answering, never a blocker.</p>
  {cards}
</div>"""

    return _shell(key, "systems", "Systems", tenant=tenant, body=f"""
{flash}
{_every_note(every, "Every account's pipelines, grouped by client. "
             "Installing and the contract forms are on an account's own page.")}
<div>
  <h1>Systems</h1>
  <p class="mut">One row per installed pipeline. A system is not on because it has a
  name — it is on when its contract is answered, its connections work, and the
  knowledge base can ground it. Everything below refuses in public rather than
  guessing in private.</p>
</div>

{backlog_html}

{installer}

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


# ---------------------------------------------------------------------------
# Brand tab — the email LOOK, with the same standing as Knowledge.
# ---------------------------------------------------------------------------

#: (dotted path, label, hint) — the hand-editable subset on the approve form.
#: Deliberately the high-consequence fields; the long tail (background/border
#: colours, radius, nav) arrives via the deriver or `brand_theme.approve`
#: called directly. footer.address is the CAN-SPAM line.
_THEME_EDIT_FIELDS = (
    ("footer.address", "Mailing address", "required before anything can send"),
    ("logo_url", "Logo URL", "absolute https URL"),
    ("colors.accent", "Accent colour", "#hex — buttons and links"),
    ("footer.tagline", "Tagline", "one line above the legal footer"),
    ("footer.disclaimer", "Disclaimer", "rendered small in the footer"),
    ("name", "Brand name", "defaults to the brand KB display name"),
)

_BRAND_CSS = """<style>
.bt-frame{width:100%;height:480px;border:1px solid var(--rule);border-radius:6px;background:#fff}
.bt-table{border-collapse:collapse;width:100%;font-size:.82rem;margin:8px 0}
.bt-table td,.bt-table th{border:1px solid var(--rule);padding:4px 8px;text-align:left}
.bt-form input[type=text]{width:100%;box-sizing:border-box;padding:5px}
.bt-form td{vertical-align:top}
</style>"""


def _theme_preview(theme: dict) -> str:
    """The sample email through one theme, sandboxed. A swatch table asks the
    owner to imagine the email; this shows it."""
    from . import brand_theme, email_render
    doc = email_render.render(theme, brand_theme.PREVIEW_BLOCKS,
                              preheader="Theme preview")
    return f'<iframe sandbox="" srcdoc="{_esc(doc)}" class="bt-frame"></iframe>'


def render_brand(key: str, tenant: str = "", msg: str = "", err: str = "",
                 derive_voice: bool = False) -> str:
    """One account's brand, whole: WHO they are and how they SOUND (identity —
    positioning, elevator, voice, hard rules) and how their email LOOKS (the
    derived, owner-approved theme).

    Split out of the Knowledge tab at the owner's instruction (2026-08-21) —
    a one-line link is not a place — then widened the same day: identity
    fields lived on Knowledge as read-only display whose only write paths
    were the intake kernel and two blank set-forms in a fold ("how does that
    make sense?" — it didn't; the fossil of the interview-first era). Brand
    now owns identity, edit-in-place and prefilled; Knowledge keeps what is
    TRUE and sayable. `derive_voice` runs the voice proposer against the
    client's own site — banned-claims-filtered, verbatim exemplars, and it
    WRITES NOTHING: `set_brand` via the form remains the only way a voice
    lands. Like Connections, the forms write to a single account, so the
    cross-account view refuses to offer them.
    """
    from . import brand_theme
    tenant, t, _rows = _account(tenant)
    if tenant == ALL:
        return _shell(key, "brand", "Brand", tenant=tenant,
                      body=_every_note(True, "A brand theme is derived and "
                                       "approved one account at a time — these "
                                       "forms write to a single client, so "
                                       "pick one in the sidebar."))
    st = brand_theme.status(tenant)
    if not st.get("ok"):
        return _shell(key, "brand", "Brand", tenant=tenant, head=_BRAND_CSS,
                      body=f'<div class="note">{_esc(st.get("error", ""))}</div>')
    prop = brand_theme.proposed(tenant)
    live = brand_theme.live_theme(tenant)
    note = (f'<div class="ok">{_esc(msg)}</div>' if msg else "") + \
           (f'<div class="note">{_esc(err)}</div>' if err else "")
    if note:
        note = f'<div class="flash">{note}</div>'

    # --- identity: positioning, elevator, voice, hard rules -----------------
    b = kb.brand(tenant)
    voice_d = (b.voice or {}) if b else {}
    banned = (b.banned_claims or []) if b else []
    banned_chips = "".join(f'<span class="chip off">{_esc(p)}</span>'
                           for p in banned) or \
        '<span class="mut">none — the validator has nothing to enforce, and ' \
        'campaign emails will not validate until at least one exists</span>'

    voice_prop = ""
    if derive_voice:
        from . import voice as vc
        # Six pages, not fifteen: this runs INSIDE the page request, and a
        # sequential crawl plus a model call has to come back while the
        # person is still watching the tab. Six pages of a brand's own copy
        # is plenty to hear a voice in.
        texts, how = vc.gather(tenant, limit=6)
        if not texts:
            voice_prop = (f'<div class="note">Could not read the site to '
                          f'derive a voice: {_esc(how)}</div>')
        else:
            got = vc.propose(tenant, texts)
            tone_s = ", ".join(str(x) for x in (got.get("tone") or []))
            pos = str(got.get("positioning") or "")
            elev = str(got.get("elevator") or "")
            # `propose` returns the verified quotes as "evidence" — the first
            # panel read a key that did not exist and rendered tone with no
            # quotes under it, which the suite missed because its stub used
            # the same wrong key. The stub uses the real one now.
            quotes = "".join(
                f'<div class="msg"><div>&ldquo;{_esc(e)}&rdquo;</div></div>'
                for e in (got.get("evidence") or got.get("exemplars") or [])[:4])
            identity_rows = ""
            if pos:
                identity_rows += (f'<p><b>Proposed positioning:</b> '
                                  f'{_esc(pos)}</p>')
            if elev:
                identity_rows += (f'<p><b>Proposed elevator:</b> '
                                  f'{_esc(elev)}</p>')
            if not (pos or elev):
                identity_rows = (
                    '<p class="mut">No positioning or elevator proposed — '
                    + _esc(got.get("degraded")
                           or "the copy read never says what the business "
                              "does, and an invented one beats nothing by "
                              "being worse") + "</p>")
            adopt_fields = "".join(
                f'<input type="hidden" name="{n}" value="{_esc(v)}">'
                for n, v in (("tone", tone_s), ("positioning", pos),
                             ("elevator_sentence", elev)) if v)
            adopts = " + ".join(x for x, v in (("tone", tone_s),
                                               ("positioning", pos),
                                               ("elevator", elev)) if v)
            voice_prop = f"""
      <div class="card">
        <div class="head"><h2>Read off their own site</h2>
          <span class="mut">{_esc(str(got.get("source") or how))}</span></div>
        <p class="mut"><b>Nothing was written.</b> A proposal from what the
        brand has already published — banned phrases filtered out, quotes
        verbatim, and the positioning may assert only what the copy asserts.
        Adopt it below, or copy what fits into the editor above.</p>
        <p><b>Proposed tone:</b> {_esc(tone_s) or '<span class="mut">nothing inferred</span>'}</p>
        {identity_rows}
        {quotes}
        {f'''<form method="post" action="/admin/brand_update" class="row">
          <input type="hidden" name="tenant" value="{_esc(tenant)}">
          {adopt_fields}
          <button class="sec">Adopt proposal ({adopts})</button>
          <span class="mut">saves only the fields shown; everything else
          stays as set</span>
        </form>''' if adopts else ''}
      </div>"""

    identity = f"""
<div class="anchor" id="identity"></div>
<div class="card">
  <div class="head"><h2>Identity — who they are, how they sound</h2></div>
  <form class="f" method="post" action="/admin/brand_update">
    <input type="hidden" name="tenant" value="{_esc(tenant)}">
    <label>Positioning — one sentence: what they do, and for whom</label>
    <input name="positioning" value="{_esc(b.positioning if b else '')}"
           placeholder="not set — every draft leans on this">
    <label>Elevator sentence</label>
    <input name="elevator_sentence"
           value="{_esc((b.elevator or {}).get('sentence', '') if b else '')}"
           placeholder="the one-liner a stranger repeats correctly">
    <label>Tone — three or four words, comma separated</label>
    <input name="tone" value="{_esc(', '.join(voice_d.get('tone') or []))}"
           placeholder="e.g. direct, warm, unhurried">
    <label>Do say — one per line</label>
    <textarea name="do_say" rows="3">{_esc(chr(10).join(voice_d.get('do_say') or []))}</textarea>
    <label>Never say — one per line (style guidance; hard rules are below)</label>
    <textarea name="never_say" rows="3">{_esc(chr(10).join(voice_d.get('never_say') or []))}</textarea>
    <div class="row"><button>Save identity</button></div>
  </form>
  <!-- Its own form, OUTSIDE the editor. The first version nested a button
       inside an anchor inside the identity form — invalid HTML whose click
       does nothing in most browsers, which is exactly how the owner found
       it: "I pressed it and it's not populating." A control that cannot
       fire is worse than a missing one, because it reads as broken. -->
  <form method="get" action="/admin/ui" class="row" style="margin-top:8px">
    <input type="hidden" name="key" value="{_esc(key)}">
    <input type="hidden" name="tab" value="brand">
    <input type="hidden" name="tenant" value="{_esc(tenant)}">
    <input type="hidden" name="derive_voice" value="1">
    <button class="sec">Derive voice from the site</button>
    <span class="mut">reads a few of their published pages and proposes below —
    takes ~20 seconds, writes nothing</span>
  </form>
  <div style="margin-top:10px"><span class="mut">Hard rules the validator
  enforces — a draft containing one is BLOCKED, never softened:</span></div>
  <div class="chips">{banned_chips}</div>
  <form class="row" method="post" action="/admin/brand_update"
        style="align-items:center;gap:8px">
    <input type="hidden" name="tenant" value="{_esc(tenant)}">
    <input name="add_banned" placeholder="add a phrase the validator must reject">
    <button class="sec">Add hard rule</button>
  </form>
</div>
{voice_prop}"""

    # The live half: what customers' emails render with today.
    if live:
        gaps = st.get("live_gaps") or []
        meta = live.get("_meta") or {}
        state = (('<span class="mut">still not sendable: '
                  + _esc("; ".join(gaps)) + "</span>") if gaps
                 else "<b>sendable</b> — address and name are on file")
        edited = ", ".join(meta.get("edited") or []) or "none"
        live_body = (f'<p class="mut">Approved {_esc(meta.get("approved_at") or "?")}'
                     f' · {state} · hand-set fields (these survive re-derives): '
                     f'{_esc(edited)}</p>' + _theme_preview(live))
    else:
        live_body = ('<div class="note">No approved theme — campaign emails '
                     'render on the default look with no mailing address, and '
                     'every campaign stays marked not-yet-sendable until one '
                     'is approved here.</div>')

    # The proposed half: what the deriver found, and where every field came
    # from. Provenance is the review — the owner is signing off SOURCES, not
    # just colours.
    if prop.get("theme"):
        src_rows = "".join(
            f"<tr><td><code>{_esc(p)}</code></td><td>{_esc(s)}</td></tr>"
            for p, s in sorted((prop.get("sources") or {}).items()))
        unavailable = "".join(
            f"<li><b>{_esc(k)}</b>: {_esc(v)}</li>"
            for k, v in (prop.get("unavailable") or {}).items())
        partial = "".join(
            f"<li><b>{_esc(k)}</b> answered partly: {_esc('; '.join(v))}</li>"
            for k, v in (prop.get("partial") or {}).items())
        prop_body = (
            f'<p class="mut">Derived {_esc(prop.get("derived_at") or "?")}'
            + (' · <span class="mut">gaps: '
               + _esc("; ".join(prop.get("gaps") or [])) + "</span>"
               if prop.get("gaps") else "")
            + "</p>"
            + f'<table class="bt-table"><tr><th>field</th><th>came from</th>'
              f"</tr>{src_rows}</table>"
            + (f'<p><b>Sources not consulted</b> — each names its fix:</p>'
               f"<ul>{unavailable}</ul>" if unavailable else "")
            + (f"<ul>{partial}</ul>" if partial else "")
            + _theme_preview(prop["theme"]))
    else:
        prop_body = ('<p class="mut">Nothing derived yet — the button below '
                     'reads the Canva brand kit, then Shopify (brand settings, '
                     'the shop\'s registered address, theme socials), then the '
                     'site, and shows the result here for review.</p>')

    # The approve form, prefilled from the proposal (else the live theme) so
    # approving unchanged is one click and correcting is typing over a value.
    inputs = ""
    for path, label, hint in _THEME_EDIT_FIELDS:
        node: object = prop.get("theme") or live or {}
        for part in path.split("."):
            node = node.get(part, "") if isinstance(node, dict) else ""
        inputs += (f"<tr><td style='white-space:nowrap'>{_esc(label)}<br>"
                   f"<small class='mut'>{_esc(hint)}</small></td>"
                   f"<td><input type='text' name='{path}' "
                   f"value='{_esc(node)}'></td></tr>")
    keyfield = f'<input type="hidden" name="key" value="{_esc(key)}">'
    actions = f"""
<form method="post" action="/admin/brand_theme/derive" style="margin:10px 0">
  {keyfield}<input type="hidden" name="tenant" value="{_esc(tenant)}">
  <button>Derive from Canva / Shopify / site</button>
  <span class="mut">writes a proposal only — nothing ships from this button</span>
</form>
<h3>Approve{" / correct" if prop.get("theme") else " by hand"}</h3>
<p class="mut">Blank fields keep the derived value; anything typed here wins,
and hand-set fields survive future re-derives.</p>
<form method="post" action="/admin/brand_theme/approve" class="bt-form">
  {keyfield}<input type="hidden" name="tenant" value="{_esc(tenant)}">
  <table class="bt-table">{inputs}</table>
  <p><button>Approve — this look ships</button></p>
</form>"""

    return _shell(key, "brand", "Brand", tenant=tenant, head=_BRAND_CSS, body=f"""
{note}
<div>
  <h1>Brand</h1>
  <p class="mut">Who this account is, how it sounds, and how its email looks —
  positioning and voice feed every draft; the theme is rendered into every
  campaign email once approved. What may be ASSERTED (claims, objections, the
  catalogue) lives on Knowledge.</p>
  {identity}
  <div class="card"><div class="head"><h2>Live theme</h2></div>{live_body}</div>
  <div class="card"><div class="head"><h2>Proposed</h2></div>{prop_body}{actions}</div>
</div>""")


def render_kb(key: str, tenant: str = "", err: str = "", msg: str = "") -> str:
    # One resolver for the frame and the body, so the pill cannot name an
    # account the numbers below it are not about.
    tenant, t, rows = _account(tenant)

    if t is None:
        return _shell(key, "kb", "Knowledge", tenant=tenant, body=
                      _every_note(tenant == ALL,
                                  "Knowledge is authored per client — there is "
                                  "no pooled knowledge base. Pick an account.")
                      or '<div class="note">No accounts yet. Run '
                      '<code>/admin/register_owner</code> first.</div>')

    c = kb.completeness(tenant)
    gaps = kb.gaps(tenant)
    b = kb.brand(tenant)

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

    # --- claims, split by whether they can actually be used ------------------
    inv = kb.claim_inventory(tenant)

    vocab = sorted(kb.situations(tenant))

    def _expiry_line(r) -> str:
        """When this claim stops standing — visible on EVERY card (owner,
        2026-08-21). Three states, same vocabulary as `kb.claim_expiry`."""
        e = kb.claim_expiry(r)
        if e["state"] == "timeless":
            return ('<span class="chip nb">never expires</span>')
        if e["state"] == "undatable":
            return ('<span class="chip off">undatable</span> '
                    '<span class="mut">no verification date on file — '
                    'saving it dates it from today</span>')
        due = e.get("due")
        return (f'<span class="mut">expires {_esc(_date(due)) if due else "?"}'
                f' — a resave re-verifies and resets it to a year out</span>')

    def _claim_editor(r) -> str:
        """Edit-in-place for an approved claim, folded so the list stays
        scannable. Same guards as review: a testimonial's wording is its
        evidence (read-only), tags come only from the account's vocabulary."""
        verbatim = (r.proof_type or "") in kb.VERBATIM_ONLY
        tagbox = "".join(
            f'<label class="tag"><input type="checkbox" name="tags" '
            f'value="{_esc(tg)}"{" checked" if tg in (r.situations or []) else ""}> '
            f'{_esc(tg)}</label>' for tg in vocab)
        exp_btn = ('<button class="sec" name="action" value="expire" '
                   'title="Put it back on the clock, dated from today">'
                   'Expires again</button>'
                   if (r.expiry_policy or "") == "never" else
                   '<button class="sec" name="action" value="never" '
                   'title="Brand origin, a material, a permanent placement — '
                   'facts that do not go stale">Never expires</button>')
        return f"""
        <details><summary class="mut">Edit</summary>
          <form class="f" method="post" action="/admin/claim_update">
            <input type="hidden" name="claim_id" value="{_esc(r.id)}">
            <input type="hidden" name="tenant" value="{_esc(tenant)}">
            <label>{"Quoted — a customer's own words (cannot be reworded)"
                    if verbatim else "Claim"}</label>
            <textarea name="claim" rows="2"{" readonly" if verbatim else ""
                      }>{_esc(r.claim)}</textarea>
            <label>Evidence</label>
            <input name="evidence" value="{_esc(r.evidence or '')}"
                   placeholder="what makes this checkable">
            <label>True of — blank means the whole brand</label>
            <input name="entity_key" list="objents"
                   value="{_esc(r.entity_key or '')}"
                   placeholder="brand-level (used in any content)">
            <label>Situations</label>
            <div class="tags">{tagbox}</div>
            <div class="row">
              <button title="Saving re-attests it: verified today, any expiry
date reset to a year from now (a timeless claim stays timeless)">Save</button>
              {exp_btn}
            </div>
          </form>
        </details>"""

    def _claim_msg(r, note: str = "", cls: str = "", editable: bool = False) -> str:
        meta = " · ".join(x for x in [
            _esc(r.strength or ""), _esc(r.proof_type or ""),
            f"verified {_date(r.verified_at)}" if r.verified_at else "",
        ] if x)
        tags = " ".join(r.situations or []) or "untagged — can never be selected"
        return (f'<div class="anchor" id="cl-{_esc(r.id)}"></div>'
                f'<div class="msg {cls}">'
                f"<div>{_esc(r.claim)}</div>"
                + (f'<div class="when"><strong>{_esc(r.evidence)}</strong></div>'
                   if r.evidence else
                   '<div class="when"><span class="mut">no evidence recorded</span></div>')
                + f'<div class="when"><code>{_esc(tags)}</code></div>'
                + f'<div class="when">{meta}{" · " if meta else ""}'
                f'{_esc(r.source or "source not recorded")}</div>'
                + f'<div class="when">{_expiry_line(r)}</div>'
                + (f'<div class="when"><b>{_esc(kb.usage_rule(r.proof_type))}</b></div>'
                   if kb.usage_rule(r.proof_type or "") else "")
                + (f'<div class="when"><b>{_esc(note)}</b></div>' if note else "")
                + (_claim_editor(r) if editable else "")
                + "</div>")

    def _claim_block(title: str, rows_, empty: str, note: str = "",
                     cls: str = "", open_: bool = False,
                     editable: bool = False) -> str:
        if not rows_:
            return (f'<details class="sec"><summary>{_esc(title)} (0)</summary>'
                    f'<p class="mut" style="margin-top:10px">{_esc(empty)}</p></details>')
        body = "".join(_claim_msg(r, note, cls, editable=editable) for r in rows_)
        return (f'<details class="sec"{" open" if open_ else ""}>'
                f'<summary>{_esc(title)} ({len(rows_)})</summary>'
                f'<div class="thread">{body}</div></details>')

    claims_html = (
        _claim_block("Claims — selectable", inv["selectable"],
                     "No usable proof. Any draft that needs a number is blocked.",
                     editable=True)
        + _claim_block("Claims — awaiting review", inv["pending"],
                       "Nothing submitted for review.",
                       "not selectable until approved", "gone")
        + _claim_block("Claims — expired", inv["expired"],
                       "Nothing has gone stale.",
                       "past its expiry date, so selection skips it", "gone")
        + _claim_block("Claims — retired", inv["retired"],
                       "Nothing retired.", "withdrawn from selection", "gone"))

    aud_html = _kb_list("All audiences", [
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
            f'<div class="anchor" id="o-{_esc(r.id)}"></div>'
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
            <details><summary class="mut">Edit</summary>
            <form class="f" method="post" action="/admin/objection_edit">
              <input type="hidden" name="row_id" value="{_esc(r.id)}">
              <input type="hidden" name="tenant" value="{_esc(tenant)}">
              <label>Objection — the hesitation in the buyer's words</label>
              <textarea name="objection" rows="2">{_esc(r.objection or '')}</textarea>
              <label>The approved answer</label>
              <textarea name="response" rows="3">{_esc(r.response or '')}</textarea>
              <label>True of &mdash; blank claims it of everything they sell</label>
              <input name="entity_key" list="objents"
                     value="{_esc(r.entity_key or '')}"
                     placeholder="leave blank only if it really is brand-wide">
              <div class="row"><button class="sec">Save</button></div>
            </form>
            </details>""")

    # Objections stand alone — they used to share a block with the situation-
    # merge warnings, which is how "claims vs objections" stopped reading as
    # two different things (owner, 2026-08-21). The merge card now lives with
    # the situations it is about.
    obj_html = _kb_list("All objections", [_obj(r) for r in obj_rows],
                        "None. This is human-authored and it is half of the "
                        "intake.", open=len(obj_rows) <= 12)
    obj_html += ('<datalist id="objents">'
                 + "".join(f'<option value="{_esc(k)}">{_esc(v)}</option>'
                           for k, v in obj_cat.items()) + "</datalist>")

    ents = kb.entities(tenant, available_only=False)
    ent_html = _kb_list("All items", [
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

    # Positioning, tone and the hard-rule adder moved to the Brand tab's
    # identity editor (2026-08-21) — two controls for one decision is how
    # they disagree, and the editor there is prefilled where these were blank.
    forms = (
        _kb_add_form(key, tenant, "claim", "Add a claim",
                     "claim | evidence | situation tags (spaces)")
        + _kb_add_form(key, tenant, "objection", "Add an objection",
                       "objection | your approved answer")
        + _kb_add_form(key, tenant, "audience", "Add an audience",
                       "key | name | pains (semicolons) | their words (semicolons)")
        + _kb_add_form(key, tenant, "entity", "Add something they sell",
                       "type | key | name | price | description"))

    warn = ((f'<div class="note">{_esc(err)}</div>' if err else "")
            + (f'<div class="ok">{_esc(msg)}</div>' if msg else ""))
    if warn:
        warn = f'<div class="flash">{warn}</div>'
    # A pointer, not a section: the email LOOK lives on its own Brand tab now
    # (owner, 2026-08-21 — a one-line link was not a place). This line stays so
    # somebody reading "what may be said" is told where "how it looks" went.
    theme_line = (
        f'<p class="mut">What may be ASSERTED lives here. Who the brand is — '
        f'positioning, voice, hard rules — and how its email looks are the '
        f'<a href="/admin/ui?key={_esc(key)}&amp;tab=brand&amp;'
        f'tenant={_esc(tenant)}">Brand tab →</a></p>')

    # Anything waiting for a decision is the first thing on the page — the
    # queue lives on Review, but discovering it exists must not require
    # visiting Review on spec.
    n_pending = len(inv["pending"])
    review_banner = ""
    if n_pending:
        review_banner = (
            f'<div class="card"><div class="head"><h2>Waiting for review</h2>'
            f'<span class="chip off">{n_pending} claims</span></div>'
            f'<p class="mut">Proposed claims are invisible to every generator '
            f'until approved. '
            f'<a href="/admin/ui?key={_esc(key)}&amp;tab=content&amp;'
            f'tenant={_esc(tenant)}#proposals">Open the review queue →</a></p>'
            f'</div>')

    # The substance, one clearly-named card per kind (owner, 2026-08-21: one
    # "What is in there" card mixing claims, audiences, objections and the
    # catalogue read as a single undifferentiated pile). Identity detail rides
    # folded under the stat strip — state first, prose on request.
    return _shell(key, "kb", "Knowledge", tenant=tenant, body=f"""
{warn}
<div>
  <h1>Knowledge</h1>
  <p class="mut">Everything the generators are allowed to say, for this account. A
  draft may assert nothing that is not on this page.</p>
  {theme_line}
</div>

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
  <details class="sec">
    <summary>Selection &amp; next steps — how picking works (advanced)</summary>
    {_kv([
      ("selection", _selection_line(kb.selection_config(tenant))),
      ("next steps", _next_steps_line((b.next_steps or {}) if b else {})),
    ])}
    {_approval_policy_html((b.approval_policy or {}) if b else {})}
    <p class="mut">Positioning, voice and the hard-rule list moved to the
    <a href="/admin/ui?key={_esc(key)}&amp;tab=brand&amp;tenant={_esc(tenant)}">Brand
    tab</a> (owner, 2026-08-21) — identity is the brand's, facts are the
    knowledge base's.</p>
  </details>
</div>

{review_banner}
{ask}

<div class="card">
  <div class="head"><h2>Claims — the proof drafts may cite</h2>
    <span class="chip {'on' if inv['selectable'] else 'off'}">{len(inv['selectable'])} usable</span></div>
  {claims_html}
</div>

<div class="card">
  <div class="head"><h2>Objections — the approved answers</h2>
    <span class="chip {'on' if obj_rows else 'off'}">{len(obj_rows)}</span></div>
  {obj_html}
</div>

<div class="card">
  <div class="head"><h2>Catalogue — what they sell</h2>
    <span class="chip {'on' if ents else 'off'}">{len(ents)}</span></div>
  {ent_html}
</div>

<div class="card">
  <div class="head"><h2>Audiences — who they sell to</h2>
    <span class="chip {'on' if c['counts'].get('audiences', 0) else 'off'}">{c['counts'].get('audiences', 0)}</span></div>
  {aud_html}
</div>

<div class="card">
  <div class="head"><h2>Situations — this account's vocabulary</h2>
    <span class="chip {'on' if sits else 'off'}">{len(sits)} tags</span></div>
  {sit_note}
  <div class="thread">{sit_body}</div>
</div>
{over_html}

{unk_card}

<details class="sec">
  <summary>Add to {_esc(t.name)} — claims, objections, audiences, catalogue, rules</summary>
  <div class="grid">{forms}</div>
  <p class="mut">The same captures work from Telegram — <code>/next</code> asks
  these one at a time and reads your reply as the answer.</p>
</details>
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
                   err: str = "", msg: str = "", cpage: int = 1) -> str:
    from . import compliance, credentials as cred, kb as kbm

    tenant, t, rows = _account(tenant)
    if t is None:
        return _shell(key, "content", "Review", tenant=tenant, body=
                      _every_note(tenant == ALL,
                                  "Every decision on this queue writes to one "
                                  "client's knowledge base. Pick an account.")
                      or '<div class="note">No accounts yet.</div>')

    # --- proposals ---------------------------------------------------------
    # Two-step, and the order is the performance fix (owner, 2026-08-21: "why
    # does it take so long to load tabs" — measured at 2.5–4.5s/render at real
    # harvest volume): first the ROWS with no analysis, to know the queue and
    # slice the page; then the O(pending × approved) similarity pass for the
    # 15 cards actually being shown, not the 135 that are not.
    base = kbm.proposals(tenant, kind="claim",
                         analyze_ids=frozenset()).get("claim", [])
    pending = [e["row"] for e in base]

    # A harvest files claims by the dozen, and a hundred full edit-forms on
    # one page is a queue nobody works (owner, 2026-08-21). One page of cards
    # at a time; every decide path carries `cpage` back so a decision returns
    # to THIS page at the next card, never to the top of page one.
    CLAIMS_PAGE = 15
    total_claims = len(pending)
    pages = max(1, -(-total_claims // CLAIMS_PAGE))
    try:
        cpage = max(1, min(int(cpage or 1), pages))
    except (TypeError, ValueError):
        cpage = 1
    shown = pending[(cpage - 1) * CLAIMS_PAGE: cpage * CLAIMS_PAGE]
    analyzed = kbm.proposals(tenant, kind="claim",
                             analyze_ids=frozenset(r.id for r in shown)
                             ).get("claim", [])
    _dupes = {e["row"].id: e for e in analyzed}
    # The page renders the ANALYZED copies of the shown rows — same ids, same
    # order (both queries order by id), with the duplicate context attached.
    shown = [e["row"] for e in analyzed
             if e["row"].id in {r.id for r in shown}]
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
    # queue rather than returning to the top of it every time. Computed over
    # the PAGE being shown — the next card must be one that is on screen.
    _order = [p.id for p in shown]
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
              <input type="hidden" name="cpage" value="{cpage}">
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
        def _pg(p: int) -> str:
            return (f"/admin/ui?tab=content&amp;tenant={_esc(tenant)}"
                    f"&amp;cpage={p}#proposals")
        pager = ""
        if pages > 1:
            pager = ('<div class="pager"><span class="mut">claims '
                     f'{(cpage - 1) * CLAIMS_PAGE + 1}&ndash;'
                     f'{(cpage - 1) * CLAIMS_PAGE + len(shown)} of {total_claims}'
                     '</span>'
                     + (f'<a href="{_pg(cpage - 1)}">&larr; newer</a>'
                        if cpage > 1 else "")
                     + (f'<a href="{_pg(cpage + 1)}">older &rarr;</a>'
                        if cpage < pages else "")
                     + '</div>')
        bulk = f"""
        <form id="bulk" method="post" action="/admin/claims_decide"></form>
        <input type="hidden" name="tenant" value="{_esc(tenant)}" form="bulk">
        <input type="hidden" name="cpage" value="{cpage}" form="bulk">
        {pager}
        <div class="bulkbar">
          <label class="pick"><input type="checkbox" id="allbox"> select all
            {len(shown)} on this page</label>
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
                     + "".join(_card(p) for p in shown) + "</div>" + pager)
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
    # Per kind, EXCLUDING claims — the old call asked for everything and then
    # threw the claims away, which recomputed their full duplicate scan a
    # third time per page load purely to discard it.
    other = {}
    for k in kbm.REVIEWABLE:
        if k == "claim":
            continue
        got = kbm.proposals(tenant, kind=k).get(k, [])
        if got:
            other[k] = got
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

    # --- plans waiting on a person, across systems -------------------------
    # One kind of thing per card: a PLAN is queued work that cannot run until
    # the owner completes or approves it — different from a proposal (which
    # asks "is this true") and from an approval (which asks "may this ship").
    # Each row links into the system's own workflow view, at the card itself.
    plans_wait = systems.plans_needing_action(tenant)
    plans_card = ""
    if plans_wait:
        prows = "".join(f"""
        <div class="msg"><div><b>{_esc(w["system_name"])}</b> ·
          {_esc(w["ref"])}{" · " + _esc(w["planned_for"]) if w["planned_for"] else ""}
          — {'needs completing: ' if w["need"] == "complete" else ''}{_esc(w["detail"])}</div>
          <div class="when"><a href="/admin/ui?key={_esc(key)}&amp;tab=systems&amp;tenant={_esc(tenant)}&amp;system={_esc(w["system_key"])}#plan-{_esc(w["run_id"])}">
            {'complete it' if w["need"] == "complete" else 'approve it'} &rarr;</a></div>
        </div>""" for w in plans_wait[:15])
        plans_card = f"""
<div class="anchor" id="plans"></div>
<div class="card">
  <div class="head"><h2>Plans awaiting you</h2>
    <span class="chip off">{len(plans_wait)} held</span></div>
  <p class="mut">Queued work that cannot run yet — a plan missing a field, or
  one that is complete and needs your go-ahead on this rung. Nothing here
  fails while it waits; it just waits.</p>
  <div class="thread">{prows}</div>
</div>"""
    # Order (owner, 2026-08-21): the queues this tab exists for come first —
    # the destructive start-over card used to be the FIRST thing on the page,
    # a rare, dangerous action sitting above the daily work. It now lives
    # folded at the bottom. The heading matches the nav ("Review"): two names
    # for one tab made it read like two places.
    return _shell(key, "content", "Review", tenant=tenant, body=f"""
<div class="flash">{banner}</div>
<div>
  <h1>Review</h1>
  <p class="mut">What has been proposed for this account and not yet approved.
  Nothing here is published — it is the difference between what the brand
  allows and what is live.</p>
</div>

<div class="anchor" id="proposals"></div>
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
{plans_card}
<div class="anchor" id="others"></div>
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

<details class="sec">
  <summary>Start this account's machine-read half over (destructive)</summary>
  <div class="card danger" style="margin-top:10px">
  <p class="mut">Deletes every claim and objection that came from a crawl or a
  mailbox for <strong>{_esc(t.name if t else tenant)}</strong> — <strong>including approved
  ones</strong>, which is what the proposal clear above cannot reach. Keeps the
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
    <span class="mut">then run Find proposals / Mine sent mail, above</span>
  </div>
  </div>
</details>
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

        # The one-click path, offered FIRST where it exists.
        #
        # Shopify can be connected two ways and only one of them is reasonable
        # to ask a client for: signing in is a button, while a custom app means
        # walking a merchant through developer settings, ticking API scopes and
        # copying a token that is shown exactly once. So the button leads and
        # the paste form stays underneath for anyone who prefers it — removing
        # it would break connecting a store you already hold a token for.
        oauth_block = ""
        if r.get("oauth_too"):
            shop_field = ('<label>Your store domain</label>'
                          '<input name="shop" placeholder="your-handle.myshopify.com"'
                          ' required>' if r.get("shop_scoped") else "")
            # What they are agreeing to, before they click — rendered from the
            # flow's own scope list so it cannot drift from what is requested.
            # A consent screen nobody can read is consent in name only, and the
            # merchant sees Shopify's version of this a moment later anyway;
            # the one that costs trust is the one they meet only there.
            from . import oauth as _oa
            words = _oa.scope_words(r["provider"])
            grants = ("<div class=\"mut\">You will be asked to allow:</div>"
                      "<ul class=\"mut\">"
                      + "".join(f"<li>{_esc(w)}</li>" for w in words)
                      + "</ul>") if words else ""
            oauth_block = f"""
            <form class="f" method="get"
                  action="/connect/{_esc(link.token)}/oauth/{_esc(r['provider'])}">
              {shop_field}
              {grants}
              <div class="row"><button>Sign in with {_esc(spec['name'])}</button></div>
              <div class="mut">Recommended — you approve these on
              {_esc(spec['name'])}'s own screen and nothing is copied by hand.
              You can revoke it there at any time.</div>
            </form>
            <details class="how" style="margin-top:10px">
              <summary>Or paste a token instead</summary>"""

        blocks.append(f"""
        <div class="prov{' done' if done else ''}">
          <h3>{_esc(r['name'])} {chip}</h3>
          {detail}
          {oauth_block}
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
          {"</details>" if r.get("oauth_too") else ""}
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

    tenant, _here, rows_t = _account(tenant)
    if tenant == ALL:
        return _shell(key, "schema", "Data layer", tenant=tenant,
                      body=_every_note(True, "Row counts are per client. "
                                       "Pick an account to read its tables."))
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

    return _shell(key, "schema", "Data layer", tenant=tenant, body=f"""
<div>
  <h1>Data layer</h1>
  <p class="mut">What the knowledge base holds for this account, table by table.
  The Knowledge tab shows the content; this shows the shape — which columns are
  actually being filled, and how the rows break down by where they came from and
  whether a human has approved them. Read from the models, so a new column shows
  up here on its own.</p>
</div>
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
    # `tenant=""` used to reach `assurance.report()` unchanged, which reports
    # EVERY account -- while the frame beside it named the first account,
    # because `_shell` fell back to it. So the one page whose whole job is to
    # be believed showed five clients' catches under one client's name. The
    # resolver runs first now, and "all accounts" is only ever what was asked
    # for by name.
    tenant, here, _rows = _account(tenant)
    every = tenant == ALL
    rep = assurance.report("" if every else tenant, days)
    who = f" · {_esc(_account_name(tenant, here))}"

    # The window is a CONTROL, not a caption (owner, 2026-08-21) — and it
    # renders on the empty state too, because "nothing in the last day" with
    # no way to widen the window from the page is a dead end.
    windows = ('<div class="filters">' + "".join(
        f'<a class="{"on" if days == d else ""}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab=assurance&amp;'
        f'tenant={_esc(tenant)}&amp;days={d}">{lbl}</a>'
        for d, lbl in ((1, "24h"), (7, "7d"), (30, "30d"), (90, "90d")))
        + "</div>")

    if not rep["events"]:
        body = (_every_note(every, "Checks recorded across every account.")
                + windows
                + f'<div class="note"><strong>Nothing has been checked for '
                f'{_esc(_account_name(tenant, here))} in the last {days} '
                f'days.</strong><br>That is not the same as '
                f'nothing being wrong — it means no draft passed through a '
                f'validator, so this page has no evidence either way.</div>')
        return _shell(key, "assurance", "Assurance", body=body, tenant=tenant)

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
    {_every_note(every, "Checks recorded across every account, pooled. "
                 "Pick a client to see only theirs.")}
    <h2>Assurance{who}</h2>
    {windows}
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
    return _shell(key, "assurance", "Assurance", body=body, tenant=tenant)


# ---------------------------------------------------------------------------
# Diagnostics tab
#
# Assurance says whether the output was safe. This says whether the thing RAN,
# and where it stopped if it did not. They are different questions and were
# answerable only by reading four tables by hand, which meant "something is
# wrong with Baci's mail" was diagnosed by opening the code.
# ---------------------------------------------------------------------------

_LEVEL_WORD = {"fail": "failures", "warn": "warnings", "ok": "clean",
               "info": "notes"}


def _dur(ms) -> str:
    """A duration a reader believes. `0s` for everything sub-second reads as a
    broken clock, so the unit follows the magnitude."""
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms} ms"
    if ms < 60000:
        return f"{ms / 1000:.1f}s"
    return f"{ms // 60000}m {ms % 60000 // 1000}s"


#: Auto-refresh intervals offered, in seconds. 0 is off and is the default:
#: a page that reloads itself while somebody is reading a stack trace is worse
#: than one they refresh themselves.
LIVE_EVERY = (0, 15, 60)


def render_diagnostics(key: str, tenant: str = "", days: int = 7,
                       level: str = "", system: str = "",
                       limit: int = 200, live: int = 0) -> str:
    """Live reports and logs for one account's systems.

    Ordered by what a person triaging actually does: the per-system verdict
    first (is anything broken at all), then the platforms (did their stack
    answer), then the log (what happened, in order). Spend sits with latency
    because slow and expensive are the two ways a working system is still a
    problem.
    """
    from . import diagnostics as diag

    tenant, here, _rows = _account(tenant)
    every = tenant == ALL
    scope = "" if every else tenant
    rep = diag.report(scope, days, level=level, system=system, limit=limit)

    def _link(**over) -> str:
        q = {"key": key, "tab": "diagnostics", "tenant": tenant,
             "days": days, "level": level, "system": system, "live": live}
        q.update(over)
        return "/admin/ui?" + "&amp;".join(
            f"{k}={_esc(v)}" for k, v in q.items() if v not in ("", None))

    windows = "".join(
        f'<a class="{"on" if days == d else ""}" href="{_link(days=d)}">{lbl}</a>'
        for d, lbl in ((1, "24h"), (7, "7d"), (30, "30d"), (90, "90d")))

    # Counts have to come from the UNFILTERED window, or every filter reports
    # its own size and the chips agree with nothing: pick "failures" and the
    # warnings chip would read 0 because there are no warnings among failures.
    counts = rep["counts"]           # of the whole window, never of the filter
    problems = counts.get("fail", 0) + counts.get("warn", 0)
    levels = (f'<a class="{"on" if level == "problems" else ""}" '
              f'href="{_link(level="problems")}">problems only '
              f'<span class="mut">{problems}</span></a>'
              f'<a class="{"on" if not level else ""}" '
              f'href="{_link(level="")}">everything</a>')
    levels += "".join(
        f'<a class="{"on" if level == lv else ""}" href="{_link(level=lv)}">'
        f'{_LEVEL_WORD[lv]} <span class="mut">{counts.get(lv, 0)}</span></a>'
        for lv in diag.LEVELS)

    # --- per-system health -------------------------------------------------
    h = rep["health"]
    if h["note"]:
        sysrows = f'<p class="mut">{_esc(h["note"])}</p>'
    else:
        sysrows = ""
        for row in h["systems"]:
            bad = row["failed"] or row["unfinished"]
            # "Problem" means a response was required and did not happen. An
            # escalation is a response — to the owner, on purpose — and mail
            # that needed no reply got the right treatment. Colouring those red
            # trains somebody to stop reading the page.
            cls = "bad" if bad else ("warn" if row["blocked"] else "")
            timing = (f'{_dur(row["median_ms"])} median · '
                      f'{_dur(row["slowest_ms"])} slowest'
                      if row["median_ms"] is not None
                      else f'<span class="mut">{_esc(row["timing_note"])}</span>')
            acct = (f'<span class="acct">{_esc(row["tenant"])}</span>'
                    if every else "")
            sysrows += f"""
            <div class="sysrow {cls}">
              <span class="nm">{_esc(row["name"])}</span>{acct}
              <span class="n">{row["runs"]} runs · <b>{row["problems"]}</b> problem(s){
                f' · {row["worked"]} worked' if row.get("worked") else ""}{
                f' · {row["escalated"]} raised for you' if row.get("escalated") else ""}{
                f' · {row["waiting"]} waiting' if row.get("waiting") else ""}{
                f' · {row["skipped"]} needed no reply' if row.get("skipped") else ""}{
                f' · {row["not_built"]} no generator yet' if row.get("not_built") else ""}</span>
              <span class="vd">{_esc(row["verdict"])}</span>
              <span class="n">{timing}</span>
            </div>"""
            if row["last_error"]:
                sysrows += (f'<div class="sysrow" style="border:0;padding-top:0">'
                            f'<span class="nm"></span><span class="vd">'
                            f'<code>{_esc(row["last_error"])}</code></span></div>')

    orphans = ""
    if h["orphan_runs"]:
        items = "".join(
            f'<li><code>{_esc(o["system_id"])}</code> — {o["runs"]} run(s), '
            f'last {_esc(o["last"][:16])}</li>' for o in h["orphan_runs"])
        orphans = f"""
        <div class="note"><strong>Runs filed against a system that no longer
        exists.</strong> Either a system row was deleted under a live pipeline,
        or something is writing runs with the wrong id. Neither is harmless.
        <ul>{items}</ul></div>"""

    # --- platforms and spend ------------------------------------------------
    pf = rep["platforms"]
    if pf["note"]:
        pf_html = f'<p class="mut">{_esc(pf["note"])}</p>'
    else:
        prow = "".join(
            f'<tr><td>{_esc(p["provider"])}</td>'
            f'<td class="num">{p["calls"]}</td>'
            f'<td class="num">{p["failed"]}</td>'
            f'<td class="num">{p["failure_rate"]:.0%}</td>'
            f'<td class="num">{p["median_ms"] if p["median_ms"] is not None else "—"}</td>'
            f'<td class="num">{p["slowest_ms"] if p["slowest_ms"] is not None else "—"}</td>'
            f'<td>{_esc(p["last_error"])}</td></tr>'
            for p in pf["providers"]) or (
            '<tr><td colspan="7" class="mut">every call this window was to our '
            'own tables — nothing reached a client platform</td></tr>')
        slow = "".join(
            f'<tr><td><code>{_esc(t["tool"])}</code></td>'
            f'<td class="num">{t["calls"]}</td>'
            f'<td class="num">{t["median_ms"]}</td>'
            f'<td class="num">{t["slowest_ms"]}</td></tr>'
            for t in pf["slow"]) or (
            f'<tr><td colspan="4" class="mut">nothing had a median over '
            f'{pf["slow_after_ms"]} ms</td></tr>')
        pf_html = f"""
        <table class="tbl">
          <tr><th>platform</th><th>calls</th><th>failed</th><th>rate</th>
              <th>median ms</th><th>slowest</th><th>last error</th></tr>
          {prow}
        </table>
        <p class="when">Failure <em>rate</em> leads, not count: a platform
        failing most of the time is a broken connection, one failing
        occasionally is the internet.</p>
        <h3 style="font-size:.9rem;margin:16px 0 6px">Slow tools</h3>
        <table class="tbl">
          <tr><th>tool</th><th>calls</th><th>median ms</th><th>slowest</th></tr>
          {slow}
        </table>
        <p class="when">A round trip, not a queue wait — a slow tool and a slow
        provider are indistinguishable from here.</p>"""

    sp = rep["spend"]
    spend_html = (f'<p class="mut">{_esc(sp["note"])}</p>' if sp["note"] else f"""
        <table class="tbl">
          <tr><td>model calls</td><td class="num">{sp["calls"]}</td></tr>
          <tr><td>cost in window</td><td class="num">${sp["cost_usd"]}</td></tr>
          <tr><td>projected / month</td><td class="num">${sp["projected_monthly_usd"]}</td></tr>
          <tr><td>cache hit rate</td><td class="num">{sp["cache_hit_rate_pct"]}%</td></tr>
        </table>""")

    # --- the log ------------------------------------------------------------
    if rep["silent"]:
        log = f'<div class="note">{_esc(rep["note"])}</div>'
    else:
        rowsh = ""
        for e in rep["events"]:
            when = e["at"][:16].replace("T", " ")
            acct = (f'<span class="acct">{_esc(e["tenant"] or "—")}</span>'
                    if every else "")
            rowsh += f"""
            <div class="ev {e["level"]}">
              <span class="lv"></span>
              <span class="when">{_esc(when)}</span>
              <span class="kind">{_esc(e["kind"])}</span>
              <span class="what"><b>{_esc(e["summary"])}</b>
                <span class="det">{_esc(e["detail"])}</span></span>
              {acct}
              <span class="layer">{_esc(e["layer"])}</span>
            </div>"""
        more = ('<p class="when">Showing the most recent '
                f'{len(rep["events"])} — the window holds more.</p>'
                if rep["truncated"] else "")
        log = f'<div class="log">{rowsh}</div>{more}'

    sysfilter = ""
    if h["systems"]:
        sysfilter = ('<span class="sep"></span>'
                     f'<a class="{"on" if not system else ""}" '
                     f'href="{_link(system="")}">all systems</a>')
        seen = []
        for row in h["systems"]:
            if row["key"] in seen:
                continue
            seen.append(row["key"])
            sysfilter += (f'<a class="{"on" if system == row["key"] else ""}" '
                          f'href="{_link(system=row["key"])}">'
                          f'{_esc(row["key"])}</a>')

    # Watching it happen, and OFF unless asked for.
    #
    # Safe to poll here in a way this codebase learned the hard way that most
    # endpoints are not: `report()` is a pure read that calls nothing and
    # writes nothing, so a reload cannot re-trigger work. The incident that
    # taught that -- a poller re-firing a slow side-effectful endpoint until
    # ~200 queued drafts went out at 400 sends/minute -- is why this note is
    # here rather than in a commit message.
    livebar = "".join(
        f'<a class="{"on" if live == v else ""}" href="{_link(live=v)}">'
        f'{"live off" if not v else f"every {v}s"}</a>' for v in LIVE_EVERY)
    refresh = (f'<meta http-equiv="refresh" content="{live}">' if live else "")

    lay = rep["layers"]
    # The controls lead the page (owner, 2026-08-21: a window nobody can
    # change from the page is a URL-editing exercise). The whole report is
    # computed from `days`, so the bar governs everything below it, not just
    # the log it used to sit on.
    body = f"""
{_every_note(every, "Every account's runs, calls and checks in one timeline. "
             "Each row names the client it belongs to.")}
<div class="filters">{windows}<span class="sep"></span>{levels}{sysfilter}
  <span class="sep"></span>{livebar}</div>
<details class="sec">
  <summary>How to read this page</summary>
  <p class="mut">Where a system is breaking, and at which layer.
  <b>functionality</b> is the call not coming back, <b>logic</b> is it working
  and refusing or being caught, <b>performance</b> is it working and being slow.
  They need different fixes and are constantly mistaken for each other — a
  blocked run is the system doing its job. Everything here is computed from
  rows other layers already wrote — this page calls nothing, so opening it
  cannot be the moment a dead token is discovered.</p>
</details>

<div class="card">
  <div class="head"><h2>Systems</h2>
    <span class="mut">last {days} days</span></div>
  {sysrows}
</div>
{orphans}

<div class="card">
  <div class="head"><h2>Platforms and cost</h2></div>
  {pf_html}
  <h3 style="font-size:.9rem;margin:16px 0 6px">Model spend</h3>
  {spend_html}
</div>

<div class="card">
  <div class="head"><h2>Log</h2>
    <span class="mut">{lay["functionality"]} functionality ·
      {lay["logic"]} logic · {lay["performance"]} performance ·
      last {days} days</span></div>
  {log}
</div>
"""
    return _shell(key, "diagnostics", "Diagnostics", body=body, tenant=tenant,
                  head=refresh, suffix=f"&amp;days={days}")
