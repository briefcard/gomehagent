"""Single-page console for wiring accounts.

Everything here is also reachable as bare /admin/* URLs, but hand-typing JSON
into a browser bar is how connections get mis-set. This page renders the same
operations as forms, with the how-to-get-this-value instructions sitting next
to the field they belong to rather than in a document you have to cross-read.

Server-rendered, no build step, no external assets — it has to work from a
phone on a hotel wifi.
"""
from __future__ import annotations

import contextvars
import html
import json
import re as _re

from . import config, db, kb, systems, tenants

#: The viewer's theme for THIS request. Set by `web.admin_ui` from the
#: `gomeh_theme` cookie before any rendering; dark is the default and renders
#: with NO attribute, so every other caller of `_shell` (and every test that
#: never set a cookie) gets the default look without knowing themes exist.
#: A contextvar rather than a parameter because threading a display
#: preference through nine render functions would put presentation in every
#: signature; and rather than a module global because two concurrent requests
#: must not see each other's choice.
_THEME = contextvars.ContextVar("console_theme", default="dark")


def set_theme(value: str) -> None:
    _THEME.set("light" if value == "light" else "dark")

# The instructions that used to live in a separate manual. Kept beside the
# fields so a value is never entered from memory.
FIELD_HELP = {
    "domain": (
        "The brand's website — scraping, compliance, and SEO",
        "NO CONNECTION NEEDED. The site is public, so this is the one field "
        "that works for a client on any platform, or on none: Squarespace, "
        "Wix, a hand-built site, anything. It is what the claim crawler reads "
        "to propose brand claims, what the compliance sweep checks against "
        "the ban list, and what a Search Console property is matched to. "
        "Bare host, no scheme and no path — acme.com, not "
        "https://acme.com/. An account with no domain has no site profile at "
        "all, so nothing here can run for it."),
    "gmail_alias": (
        "Inbox monitoring + sending drafts",
        "The account's Google connection. To add one, use Connect beside "
        "Google on this tab and sign in as that mailbox — nothing to run "
        "locally and no env var to paste. Connecting here also records which "
        "scopes Google actually granted, which the env-var route cannot, so "
        "Search Console and Analytics report as wired only when they truly "
        "are. A key from GMAIL_ACCOUNTS_JSON still works for accounts "
        "connected before this existed."),
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
/* The Saias Ops token sheet — UI overhaul step 1 (INITIATIVE-ui-overhaul.md,
   design source: the "Saias Ops Overhaul" spec §1). The console COMMITS to
   dark: one look, no media query — the old light default with a dark override
   meant every hard-coded hex was wrong in one of the two themes, and three
   were. Color semantics are fixed across every page: lavender (--acc) =
   navigation/selection/primary action; mint (--ok) = healthy/live/confirmed;
   amber (--gap) = WAITING ON A PERSON (every badge and count); red (--err) =
   failure and destruction only; the per-account --tint hue = whose data this
   is. Same class names as before on purpose — the suite string-matches
   markup, so the reskin swaps values, never contracts. */
:root{--bg:#0b1326;--panel:#131b2e;--ink:#dae2fd;--ink2:#b9c2de;--mut:#8f97b3;
--rule:#2c3450;--rule2:#1b2338;--field:#1d2740;
--acc:#d2bbff;--accs:#241f45;--acc-ink:#2a1155;--ok:#4edea3;--oks:#0f2c22;
--gap:#ffb95f;--gaps:#2b2113;--gap-ink:#2a1700;--err:#ffb4ab;--errs:#3a1512;
--scrollh:#3a4160;
--sans:"Hanken Grotesk",-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
--mono:"JetBrains Mono",ui-monospace,Menlo,monospace}
/* The LIGHT equivalent (owner, 2026-08-27) — same custom properties, second
   values, chosen per pair for the same contrast the dark set holds. Dark is
   the DEFAULT and renders with no attribute; data-theme=light on the body
   tag comes from the gomeh_theme cookie via the pagehead toggle. The smoke
   asserts the two blocks define the SAME token set, so neither palette can
   silently fall behind the other. */
body[data-theme=light]{--bg:#f4f6fb;--panel:#fff;--ink:#171a26;--ink2:#3d4353;
--mut:#6b7386;--rule:#dfe3ec;--rule2:#eef1f6;--field:#fff;
--acc:#6d28d9;--accs:#efe9fd;--acc-ink:#f6efff;--ok:#0e7a55;--oks:#e4f4ec;
--gap:#9a5b00;--gaps:#faf0de;--gap-ink:#fff7ea;--err:#b3251e;--errs:#fbe9e7;
--scrollh:#c3c9d6;
--tone:hsl(var(--tint,214) 42% 38%);--tones:hsl(var(--tint,214) 46% 94%)}
body[data-theme=light] .side .switch a .dot{background:hsl(var(--tint,214) 44% 48%)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--sans);
-webkit-font-smoothing:antialiased}
/* Every bare link, on-palette. Links were styled per component (.side a,
   .filters a, …) and nothing defined the element itself, so any plain <a> in
   prose fell back to the browser's default blue — unreadable on this ground
   (owner, 2026-08-27, step-1 review). Underlined so an inline control is
   visibly a control; the nav/chrome contexts all declare their own
   text-decoration:none and keep it. */
a{color:var(--acc);text-decoration:underline;text-underline-offset:2px}
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--rule);border-radius:5px}
::-webkit-scrollbar-thumb:hover{background:var(--scrollh)}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,
textarea:focus-visible,summary:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.w{max-width:960px;margin:0 auto;padding:32px 20px 80px;display:flex;flex-direction:column;gap:30px}
h1{font:700 1.7rem/1.2 var(--sans);letter-spacing:-.02em;margin:0}
h2{font:700 1.15rem/1.25 var(--sans);letter-spacing:-.015em;margin:0}
h3{font:700 .98rem/1.3 var(--sans);margin:0}
.tblwrap{overflow-x:auto}
.mut{color:var(--mut);font-size:.86rem}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:6px;padding:16px 18px;
display:flex;flex-direction:column;gap:12px}
.head{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:baseline;
border-bottom:1px solid var(--rule);padding-bottom:10px}
.head h2{flex:1 1 auto}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{font-family:var(--mono);font-size:.66rem;padding:.25em .55em;border-radius:3px;
font-weight:700;letter-spacing:.04em;background:var(--rule2);color:var(--ink2);
border:1px solid var(--rule)}
.chip.on{background:var(--oks);color:var(--ok);border:1px solid var(--ok)}
.chip.off{background:var(--gaps);color:var(--gap);border:1px solid var(--gap)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.f{display:flex;flex-direction:column;gap:5px;border:1px solid var(--rule);border-radius:4px;
padding:11px 13px;background:var(--rule2)}
.f label{font-family:var(--mono);font-size:.68rem;text-transform:uppercase;
letter-spacing:.08em;font-weight:700;color:var(--acc)}
.f .what{font-size:.8rem;color:var(--ink2)}
.f details{font-size:.79rem;color:var(--mut)}
.f summary{cursor:pointer;color:var(--acc);font-weight:600;font-size:.75rem}
.f details p{margin:6px 0 0}
input,select{font:inherit;font-size:.85rem;padding:6px 8px;border:1px solid var(--rule);
border-radius:3px;background:var(--field);color:var(--ink);width:100%}
input:focus,select:focus,textarea:focus{border-color:var(--acc)}
button{font:inherit;font-size:.82rem;font-weight:700;padding:6px 13px;border-radius:4px;
border:1px solid var(--acc);background:var(--acc);color:var(--acc-ink);cursor:pointer}
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
.pictile{display:flex;flex-direction:column;gap:4px}
.pictile .sec summary{font-size:.7rem}
.picmeta{display:block;font-size:.68rem;color:var(--mut);padding:5px 7px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.inst{border:1px solid var(--rule);border-radius:5px;padding:11px 13px;
  margin-bottom:8px;display:flex;flex-direction:column;gap:6px}
.inst.ok{border-left:3px solid var(--ok)}
.inst.gap{border-left:3px solid var(--gap)}
.inst.done{border-left:3px solid var(--rule);opacity:.72}
.insthead{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.grow{flex:1}
.when{color:var(--mut);font-size:.8rem}
.prereqs{display:flex;gap:6px;flex-wrap:wrap}
.pre{font-size:.72rem;border-radius:100px;padding:2px 9px;border:1px solid var(--rule);
  white-space:nowrap}
.pre.yes{color:var(--ok)}
.pre.no{color:var(--gap)}
.btn{display:inline-block;font-size:.78rem;font-weight:700;padding:4px 12px;border-radius:4px;
  border:1px solid var(--acc);background:var(--acc);color:var(--acc-ink);text-decoration:none}
.btn.sec{background:transparent;color:var(--ink);border-color:var(--rule)}
.btn.danger{background:transparent;color:var(--err);border-color:var(--err)}
/* --- the frame: sidebar, client switcher, page ---------------------------
   Same shape as the client portal on purpose. Switching between the two
   should not mean learning a second layout, and the account is chosen once
   in the frame rather than re-picked inside four separate tabs. */
.shell{display:flex;min-height:100vh;align-items:stretch}
.side{width:224px;flex:0 0 224px;background:var(--panel);
border-right:1px solid var(--rule);padding:18px 12px;display:flex;
flex-direction:column;gap:1px;position:sticky;top:0;height:100vh;overflow-y:auto}
.side .brand{font-weight:700;font-size:.98rem;padding:0 10px 14px}
.side .swlabel,.side .navlabel{font-family:var(--mono);font-size:.64rem;
text-transform:uppercase;letter-spacing:.1em;color:var(--mut);
padding:12px 10px 6px;font-weight:700}
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
body{--tone:hsl(var(--tint,214) 58% 74%);--tones:hsl(var(--tint,214) 42% 17%)}
body.every{--tone:var(--acc);--tones:var(--accs)}
/* Every account's dot in ITS OWN colour, not just the selected one -- each
   row carries a `--tint` of its own, so the mapping is learnable from the
   list rather than only visible once you have already switched. */
.side .switch a .dot{background:hsl(var(--tint,214) 58% 64%);opacity:.55}
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
.log .ev.fail .lv{background:var(--err)}
.log .ev.warn .lv{background:var(--gap)}
.log .ev.ok .lv{background:var(--ok)}
.log .ev.info .lv{background:var(--rule)}
.log .ev .when{flex:0 0 118px;color:var(--mut);font-size:.76rem;
font-family:var(--mono)}
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
.sysrow .n{font-family:var(--mono);font-size:.8rem;
color:var(--mut)}
.sysrow.bad .vd{color:var(--err)}
.sysrow.warn .vd{color:var(--gap)}
.side .foot{margin-top:auto;padding-top:12px;border-top:1px solid var(--rule);
display:flex;flex-direction:column;gap:1px}
.side .foot a{font-size:.82rem;color:var(--mut)}
.side a.pend{color:var(--gap);font-weight:700}
.main{flex:1;min-width:0;padding:22px 28px 60px;max-width:1180px}
.pagehead{display:flex;align-items:baseline;gap:12px;margin-bottom:18px;
flex-wrap:wrap}
.pagehead h1{font-size:1.3rem;margin:0;letter-spacing:-.02em}
.pagehead .theme{margin-left:auto;text-decoration:none;color:var(--mut);
font-size:.95rem;line-height:1;padding:4px 9px;border:1px solid var(--rule);
border-radius:4px;background:var(--panel)}
.pagehead .theme:hover{color:var(--acc);border-color:var(--acc)}
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
/* The waiting-decisions pill (styled with the sidebar foot above) is AMBER on
   purpose: amber is the waiting-on-a-person color everywhere in this console,
   and a count that can read as mere activity stops being checked. The old
   `.tabs a.pend` rule retired with the tab bar it belonged to. */
.pick{display:inline-flex;gap:6px;align-items:center;font-size:.75rem;
  color:var(--mut);cursor:pointer;user-select:none}
/* Sticky bar is ~44px tall and would otherwise cover the card just jumped to. */
.anchor{position:relative;top:-56px;display:block;height:0;visibility:hidden}
code{font-family:var(--mono);font-size:.8em;background:var(--rule2);
border:1px solid var(--rule);padding:.08em .35em;border-radius:3px}
.cur{background:var(--accs);border-left:3px solid var(--acc)}
.note{background:var(--gaps);border-left:3px solid var(--gap);padding:10px 14px;
border-radius:0 4px 4px 0;font-size:.85rem;color:var(--ink2)}
.ok{background:var(--oks);border-left:3px solid var(--ok);padding:10px 14px;
border-radius:0 4px 4px 0;font-size:.85rem;color:var(--ink2)}
.cols{width:100%;border-collapse:collapse;margin-top:10px;font-size:12.5px}.cols th{text-align:left;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut);padding:5px 8px;border-bottom:1px solid var(--rule)}.cols td{padding:5px 8px;border-bottom:1px solid var(--rule2);vertical-align:middle}.cols .cn{font-family:var(--mono)}.cols .ct{font-family:var(--mono);color:var(--mut);font-size:11px}.cols .cf{width:150px;white-space:nowrap}.fillbar{display:inline-block;width:88px;height:6px;border-radius:3px;background:var(--rule2);vertical-align:middle;overflow:hidden}.fillbar i{display:block;height:100%;background:var(--ok)}.fillbar i.sec{background:var(--gap)}.fillbar i.off{background:var(--rule)}.fillpct{font-family:var(--mono);font-size:10.5px;color:var(--mut);margin-left:7px}
/* The old horizontal `.tabs` bar rendered by nothing since the frame rebuild —
   its rules (and the light-theme hexes they carried) retire with the reskin. */
textarea{font:inherit;font-size:.85rem;padding:6px 8px;border:1px solid var(--rule);
border-radius:3px;background:var(--field);color:var(--ink);width:100%;resize:vertical}
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
.tog{display:inline-flex;align-items:center;gap:8px;text-decoration:none;color:var(--mut);font-size:.75rem;font-weight:700;letter-spacing:.03em}
.tog .tr{width:34px;height:19px;border-radius:10px;background:var(--rule2);border:1px solid var(--rule);position:relative;transition:background .12s}
.tog .kn{position:absolute;top:2px;left:2px;width:13px;height:13px;border-radius:50%;background:var(--mut);transition:left .12s,background .12s}
.tog.on{color:var(--ok)}
.tog.on .tr{background:var(--oks);border-color:var(--ok)}
.tog.on .kn{left:17px;background:var(--ok)}
.tog.dis{opacity:.45;cursor:not-allowed}
.kv{display:grid;grid-template-columns:130px 1fr;gap:5px 14px;margin:0;font-size:.85rem}
.kv dt{color:var(--mut);font-family:var(--mono);font-size:.68rem;text-transform:uppercase;
letter-spacing:.07em;font-weight:700;padding-top:2px}
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
input.copy{width:100%;font-family:var(--mono);font-size:.8rem;
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
.flow{display:flex;gap:6px;align-items:stretch;flex-wrap:wrap;margin-top:12px}
.flowcol{flex:1;min-width:200px;display:flex;flex-direction:column;gap:8px}
.flowlab{font-family:var(--mono);font-size:.68rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--mut);padding-bottom:2px;border-bottom:1px solid var(--rule)}
.flowarr{align-self:center;color:var(--mut);font-size:1.3rem;padding:0 2px}
.fnode{border:1px solid var(--rule);border-left:3px solid var(--acc);border-radius:4px;padding:7px 10px;font-size:.84rem;background:var(--rule2)}
.fnode b{display:block;margin-bottom:2px}
.fnode .when{display:block}
.fnode.dim{border-left-color:var(--rule2);opacity:.72}
@media(max-width:900px){.flow{flex-direction:column}.flowarr{transform:rotate(90deg);align-self:flex-start;padding-left:14px}}
.subtabs{display:flex;gap:4px;flex-wrap:wrap;margin:18px 0 16px;border-bottom:1px solid var(--rule);padding-bottom:0}
.subtab{display:flex;align-items:center;gap:7px;padding:9px 14px;text-decoration:none;color:var(--mut);font-size:.9rem;font-weight:600;border-bottom:2px solid transparent;margin-bottom:-1px}
.subtab:hover{color:var(--ink)}
.subtab.on{color:var(--ink);border-bottom-color:var(--acc)}
.subtab .cnt{font-family:var(--mono);font-size:.72rem;font-weight:700;padding:1px 7px;border-radius:9px;background:var(--rule2);border:1px solid var(--rule);color:var(--mut)}
.subtab.on .cnt{background:var(--gap);border-color:var(--gap);color:var(--gap-ink)}
.navbadge{margin-left:auto;background:var(--gap);color:var(--gap-ink);border-radius:9px;
font-family:var(--mono);font-size:.7rem;font-weight:700;padding:1px 7px;line-height:1.5}
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
/* Plan tab. These six shipped used-but-undefined, so the readiness strip
   rendered as unstyled stacked divs and an ERROR on that tab rendered as
   plain body text. scripts/test_render_smoke.py now fails on any class the
   markup uses that this sheet does not define. */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
  gap:10px;margin:10px 0 16px}
.cards .card{margin:0;padding:12px 14px}
.card.warn{border-left:3px solid var(--gap);background:var(--gaps)}
.lbl{font-weight:600;font-size:.85rem;color:var(--ink2)}
.big{font-size:1.02rem;font-weight:600;margin:2px 0 4px}
.tbl tr.grp td{background:var(--rule2);font-size:.85rem;padding-top:8px}
/* A table's group heading row — the tier or pillar a run of rows belongs to.
   It was the last of the Plan tab's undefined classes (spec §7's P0 named
   six; step 1's token sheet styled five). It renders ONLY when the account
   has clusters or opportunities, which is why the smoke suite's class
   coverage never saw it: a class used only when there is data is invisible
   to a check run against an account with none. The demo now seeds enough
   keyword rows for it to render, so it is actually walked. */
.grp td{background:var(--rule2);font-size:.82rem;padding-top:9px}
.bad{color:var(--err);background:var(--errs);border-left:3px solid var(--err);
  padding:8px 12px;border-radius:4px}
"""

#: (key, label, icon). Ordered the way a day runs rather than the way the code
#: is arranged: what needs deciding, then what it knows, then what it is
#: connected to, then the plumbing.
#: The background actions whose status the Review banner reports. ONE
#: vocabulary: `_run_bg` writers must use exactly these labels — three of the
#: four once wrote under names nothing read ("email_harvest", "catalog sync",
#: "compliance scan"), so a crashed run looked identical to one still
#: running. `test_pointers` holds writer labels to this tuple.
BG_LABELS = (("harvest", "Harvest"), ("scan", "Compliance scan"),
             ("sync", "Catalogue sync"), ("email", "Sent mail"))

_TABS = (("content", "Review", "✓"), ("kb", "Knowledge", "◈"),
         ("brand", "Brand", "❖"),
         # The SEO plan the blog is built from. It sits beside Systems rather
         # than inside Review because it is not a queue of things to decide —
         # it is the standing answer to "what are we writing, and why that
         # next", which had no surface at all and lived in a JSON endpoint.
         ("plan", "Plan", "◎"),
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


def _blocker_li(key: str, tenant: str, b: str) -> str:
    """One gate blocker as a list item — with the way to it, when there is one.

    "not connected: cms" told the reader exactly what was missing and nothing
    about where to fix it; the Connections tab is one link away and the audit
    found no page made the trip. A blocker that is not a connection renders
    plain — inventing a destination for "knowledge base: kb_brand row" would
    point somewhere that cannot clear it.
    """
    li = f"<li>{_esc(b)}</li>"
    if b.startswith("not connected:"):
        li = (f'<li>{_esc(b)} — <a href="/admin/ui?key={_esc(key)}'
              f'&amp;tab=accounts&amp;tenant={_esc(tenant)}">connect it</a></li>')
    return li


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


def _badges(tenant: str, full: bool = True) -> dict:
    """Needs-you counts per tab, computed once per page render.

    THE RULE: a badge counts things WAITING ON A PERSON — never runs, never
    activity — which is why every badge renders amber. "Is there work" must
    not cost a click per tab to find out (owner, 2026-08-21), and for months
    only Review could answer it: pictures, conflicts, a failing connection,
    a system refusing every run for a week — all invisible until you opened
    the right tab, and for Systems check, the right sub-view too.

    Review's number is everything decidable: proposed KB rows, held plans,
    open conflicts, AND pending approvals — one question, one number. The
    approvals pill in the foot keeps its own markup (test-pinned, and the
    ship queue deserves its dedicated door) but it is a subset of this.

    `full=False` computes Review's number only — the all-accounts switcher
    calls this once per account for its rollups, and five accounts times the
    readiness probe would make the deliberate view the slow one.

    Every part is wrapped separately and a failure counts as zero: a sidebar
    must never be the thing that breaks a page.
    """
    out = {"content": 0, "systems": 0, "accounts": 0, "schema": 0}
    if not tenant or tenant == ALL:
        return out
    from . import approvals, credentials as cred, provenance as prov
    try:
        with db.SessionLocal() as s:
            out["content"] += sum(
                s.query(model)
                .filter(model.tenant == tenant,
                        model.review == prov.PROPOSED).count()
                for model in (db.KbClaim, db.KbAudience, db.KbObjection,
                              db.KbEntity, db.KbSituation, db.KbAsset))
    except Exception:                                            # noqa: BLE001
        pass
    try:
        out["content"] += len(systems.plans_needing_action(tenant))
    except Exception:                                            # noqa: BLE001
        pass
    try:
        out["content"] += len(prov.conflicts(tenant))
    except Exception:                                            # noqa: BLE001
        pass
    try:
        out["content"] += approvals.pending_count(tenant)
    except Exception:                                            # noqa: BLE001
        pass
    if not full:
        return out
    try:
        out["systems"] = len(systems.attention(tenant, 30))
    except Exception:                                            # noqa: BLE001
        pass
    try:
        out["accounts"] = sum(1 for r in cred.status(tenant)
                              if r.get("state") == "failed")
    except Exception:                                            # noqa: BLE001
        pass
    try:
        # The SAME computation Queue & Insights renders (rule 8) — this used
        # to read a "proposals" key mute_lessons never returned, so the
        # lessons half of the badge was permanently zero while the title
        # promised it counted.
        out["schema"] = _schema_needs_you(tenant)["n"]
    except Exception:                                            # noqa: BLE001
        pass
    return out


#: What each badge counts, said on hover — the number must be explainable
#: or it becomes noise somebody learns to scroll past.
_BADGE_TITLES = {
    "content": "decisions waiting on you",
    "systems": "systems needing attention",
    "accounts": "connections failing",
    "schema": "gaps and lessons waiting on you",
}


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
    # On the deliberate cross-account view, each switcher row carries its own
    # needs-you rollup — the one place a per-account roll-up makes sense is
    # the page whose whole point is looking across accounts. Elsewhere the
    # rows stay plain: five extra badge passes per render would tax every
    # page for a number the sidebar already shows for the account you are on.
    rollups = ({r.key: _badges(r.key, full=False)["content"] for r in rows}
               if tenant == ALL else {})
    switch = "".join(
        f'<a class="{"on" if r.key == tenant else ""}" '
        f'style="--tint:{hues.get(r.key, "")}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab={tab}&amp;tenant={_esc(r.key)}">'
        f'<span class="dot"></span>{_esc(r.name)}'
        + (f'<span class="navbadge" title="{_BADGE_TITLES["content"]}">'
           f'{_n}</span>' if (_n := rollups.get(r.key, 0)) else "")
        + '</a>' for r in rows)
    # Cross-account is a place you go on purpose, listed apart from the clients
    # so it can never be the account you are on without having chosen it.
    switch += (f'<a class="every {"on" if tenant == ALL else ""}" '
               f'href="/admin/ui?key={_esc(key)}&amp;tab={tab}&amp;tenant={ALL}">'
               f'<span class="dot"></span>All accounts</a>')

    badges = _badges(tenant)
    nav = "".join(
        f'<a class="{"on" if t == tab else ""}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab={t}&amp;tenant={_esc(tenant)}'
        f'{suffix if t == tab else ""}"><span class="ico">{i}</span>{label}'
        + (f'<span class="navbadge" title="{_BADGE_TITLES[t]}">'
           f'{_n}</span>'
           if (_n := badges.get(t, 0)) else "")
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
    # To the Review tab's own section — /admin/pending survives only as the
    # unauthenticated-email fallback it always was.
    # On All accounts the count spans every client but Review refuses the
    # pooled view — so the pill goes to /admin/pending, the one queue that
    # renders all-accounts rows, each labelled with its owner.
    _pend_href = ("/admin/pending?key=" + _esc(key) if tenant == ALL else
                  f"/admin/ui?key={_esc(key)}&amp;tab=content&amp;sub=ship"
                  f"&amp;tenant={_esc(tenant)}")
    waiting = (f'<a class="pend" href="{_pend_href}">'
               f'<span class="ico">!</span>{_n} waiting</a>' if _n else "")

    who = _account_name(tenant, here)
    # The client view is one account's page; there is no portal for "all".
    # NO key in this URL: the console session cookie already authenticates the
    # owner on /portal (portal.principal checks it), and the cookie system
    # exists precisely because the credential used to ride in browser history,
    # Referer headers and access logs. This link reintroduced it — into the
    # PORTAL's logs, the client-facing surface.
    client_view = ("" if tenant == ALL else
                   f'<a href="/portal?tenant={_esc(tenant)}">'
                   f'Client view &rarr;</a>')
    # /admin/logout existed with no link anywhere — a door with no handle.
    sign_out = '<a href="/admin/logout">Sign out</a>'

    # Dark renders with no attribute; the cookie-chosen light look rides
    # `data-theme` so the token block can address it without JS. The toggle
    # carries tab + tenant + the current tab's suffix, so switching themes
    # keeps the reader exactly where they were — a display preference must
    # never cost the place (the redirect rule, applied to chrome).
    theme = _THEME.get()
    other = "dark" if theme == "light" else "light"
    theme_ctl = (f'<a class="theme" href="/admin/theme?key={_esc(key)}'
                 f'&amp;to={other}&amp;tab={tab}&amp;tenant={_esc(tenant)}{suffix}"'
                 f' title="Switch to {other} mode">'
                 f'{"☾" if other == "dark" else "☀"}</a>')
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} — {_esc(who)}</title>
<style>{_CSS}</style>{head}</head><body class="{"every" if tenant == ALL else ""}"{
    ' data-theme="light"' if theme == "light" else ""}
 style="--tint:{hues.get(tenant, "")}">
<div class="shell">
  <div class="side">
    <div class="brand">Saias Ops</div>
    <div class="swlabel">Account</div>
    <div class="switch">{switch}</div>
    <div class="navlabel">Manage</div>
    {nav}
    <div class="foot">{waiting}{client_view}{sign_out}</div>
  </div>
  <div class="main">
    <div class="pagehead"><h1>{_esc(title)}</h1>
      <span class="who">{_esc(who)}</span>{theme_ctl}</div>
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
    # FAILED FIRST (spec §11): a broken connection is the row this page
    # exists to surface, and it was sorted wherever the provider list put
    # it. Stable within each state, so the provider order stays learnable.
    _rank = {"failed": 0, "connected": 1}
    rows = sorted(rows, key=lambda r: _rank.get(r.get("state"), 2))
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
            # Asks first (spec §11): severing a connection is irreversible
            # in effect — the client re-connects, we do not un-revoke.
            out += (f'<form method="post" action="/admin/connect_revoke" '
                    f'class="inl" onsubmit="return confirm(\'Disconnect '
                    f'{_esc(r["name"])}'
                    + (f' ({_esc(site)})' if site else "")
                    + f' for {_esc(tenant)}? The client will have to '
                    f'connect it again.\')">'
                    f'{hidden}<button class="sec">Disconnect'
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
      <div class="when">Connect links, sign-in links and the people who may
      use them live on
      <a href="/admin/ui?tab=accounts&amp;sub=people&amp;tenant={_esc(tenant)}{f'&amp;key={_esc(key)}' if key else ''}">People &amp; links</a>.</div>
    </details>
    """


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
                # Irreversible-in-effect (their unused sign-in links die with
                # it) so it asks first — the bare inline button was one of
                # the spec's named defects on this page.
                f'<form method="post" action="/admin/person_access" class="inl" '
                f'onsubmit="return confirm(\'Revoke {_esc(u["name"] or u["email"])}\\u0027s portal access? Any unused sign-in link they hold dies with it.\')">'
                f'{hidden}<button class="sec" name="action" value="revoke">'
                f'Revoke</button></form>')
            if u["can_sign_in"]:
                buttons += (f'<a href="/admin/portal_link?key={_esc(key)}'
                            f'&amp;email={_esc(u["email"])}&amp;ui=1'
                            f'&amp;tenant={_esc(tenant)}">'
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


def _intake_links(tenant: str, key: str) -> str:
    """Intake links — mint, list, revoke, on the page that owns client access.

    /admin/intake_new, _links and _revoke existed for months with no console
    surface: minting a link meant hand-typing a URL and copying it out of raw
    JSON. Connect links got a form; intake links — the higher-leverage
    surface, because answers fill the KB every generator grounds on — got
    nothing. Folded closed: minting is rare, and the summary line carries the
    standing state.
    """
    with db.SessionLocal() as s:
        rows = (s.query(db.IntakeLink)
                .filter(db.IntakeLink.tenant == tenant)
                .order_by(db.IntakeLink.created_at.desc()).all())
        for r in rows:
            s.expunge(r)
    now = db.utcnow()

    def _live(r) -> bool:
        exp = db.as_utc(r.expires_at) if r.expires_at else None
        return (r.status or "") == "active" and (exp is None or exp > now)

    live = [r for r in rows if _live(r)]
    dead = len(rows) - len(live)
    items = ""
    for r in live:
        url = f"{config.PUBLIC_BASE_URL}/intake/{r.token}"
        items += f"""
        <div class="conn">
          <div>
            <strong>{_esc(r.label or 'unlabelled')}</strong>
            <span class="chip on">active</span>
            <div class="mut">{_esc(str(r.answered or 0))} answered ·
              expires {_esc(str(r.expires_at)[:10])}</div>
            <input class="copy" value="{_esc(url)}" readonly onclick="this.select()">
          </div>
          <div class="row">
            <a href="/admin/intake_revoke?key={_esc(key)}&amp;token={_esc(r.token)}&amp;tenant={_esc(tenant)}&amp;ui=1" onclick="return confirm('Revoke this intake link? Anyone holding it loses access; a new one can always be minted.')"><button class="sec" type="button">Revoke</button></a>
          </div>
        </div>"""
    if not items:
        items = ('<div class="mut">No live links. A link asks the client this '
                 'account\'s open questions one at a time — answers land as '
                 'proposals, and claims stay pending until reviewed.</div>')
    summary = (f"Intake links — {len(live)} live"
               + (f" · {dead} expired or revoked" if dead else ""))
    return f"""
    <details class="conns">
      <summary>{summary}</summary>
      {items}
      <form class="row mklink" method="get" action="/admin/intake_new">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="tenant" value="{_esc(tenant)}">
        <input type="hidden" name="ui" value="1">
        <input name="label" placeholder="who it is for, e.g. Jane" required>
        <input name="days" value="30" size="4" title="days until it expires">
        <button class="sec">Create an intake link</button>
        <span class="mut">the client answers this account's open KB questions;
        anything they skip is asked again later rather than guessed</span>
      </form>
    </details>"""


#: Connections' sub-views (step 4, spec §11): Status is the question the
#: tab exists to answer — is this account wired; People & links is
#: everything about letting its humans in; Advanced is the plumbing and
#: the rare admin forms.
ACCOUNTS_SUBS = (("", "Status"), ("people", "People & links"),
                 ("advanced", "Advanced"))


def _verify_summary(tenant: str, key: str) -> str:
    """The last Test-connections result, on the card that owns the button.

    The test runs in the background (a hotel-wifi page must not hang on five
    live probes); the result is stored and rendered HERE — so the button's
    consequence is visible where the button is, not in a JSON tab."""
    import json as _json
    with db.SessionLocal() as s:
        row = s.get(db.Setting, f"verify_result:{tenant}")
    if row is None:
        return ('<div class="mut">Never live-tested. The chips above show '
                'what is <em>configured</em>; Test connections calls each '
                'one to see if it <em>works</em>.</div>')
    try:
        got = _json.loads(row.value or "{}")
    except Exception:                                            # noqa: BLE001
        return ""
    bits = "".join(
        f'<span class="chip {"on" if r.get("status") == "ok" else ("off" if r.get("status") == "FAIL" else "nb")}" '
        f'title="{_esc(str(r.get("detail") or ""))}">'
        f'{_esc(cap)}: {_esc(str(r.get("status") or ""))}</span>'
        for cap, r in (got.get("results") or {}).items())
    return (f'<div class="mut">Last live test {_esc(str(got.get("when") or "")[:16])} '
            f'— hover a chip for the detail:</div>'
            f'<div class="chips">{bits}</div>')


def _copy_flash(title: str, url: str) -> str:
    """A minted link, flashed with its copy affordance labeled."""
    return f"""
        <div class="ok">
          <div>{title}</div>
          <input class="copy" value="{_esc(url)}" readonly onclick="this.select()">
          <div class="when">click the field to select it, then copy — the
          link is shown once here and is not sent anywhere by itself</div>
        </div>"""


def render(key: str, tenant: str = "", msg: str = "", err: str = "",
           link: str = "", ilink: str = "", plink: str = "",
           sub: str = "") -> str:
    """Connections for ONE account (restructured in step 4, spec §11).

    One account at a time, named in the frame — this is the screen where
    getting the wrong account is most expensive, because the buttons on it
    revoke credentials and mint links. Three views: Status (is it wired),
    People & links (letting its humans in), Advanced (raw wiring, admin
    forms, the plumbing panel). Every action lands back here as a flash —
    the six raw-JSON dead-ends the spec counted are gone.
    """
    tenant, _here, rows = _account(tenant)
    if tenant == ALL:
        return _shell(key, "accounts", "Connections", tenant=tenant,
                      body=_every_note(True, "These buttons revoke credentials "
                                       "and mint client links, so they are only "
                                       "ever offered for one named account."))
    sub = (sub or "").strip().lower()
    if sub not in dict(ACCOUNTS_SUBS):
        sub = ""
    rows = [r for r in rows if r.key == tenant]

    # The flashes render on EVERY view — the result of what you just did
    # comes first, whichever view the action returns to.
    note = f'<div class="ok">{_esc(msg)}</div>' if msg else ""
    if err:
        note += f'<div class="note">{_esc(err)}</div>'
    if link:
        note += _copy_flash("Connect link — send this to the client. It "
                           "reaches one account and connects nothing else.",
                           link)
    if ilink:
        note += _copy_flash("Intake link — send this to the client. It asks "
                           "this account's open questions and reaches "
                           "nothing else.", ilink)
    if plink:
        note += _copy_flash("Sign-in link — send it to them yourself. A "
                           "login link is a credential: nothing here sends "
                           "it as a side effect of minting it.", plink)
    if note:
        note = f'<div class="flash">{note}</div>'

    if not rows:
        # The routes panel EXPANDED here: with no accounts yet, "can anyone
        # connect at all" is the only question on this page that HAS an
        # answer, and it is the one a fresh install needs.
        return _shell(key, "accounts", "Connections", tenant=tenant, body=(
            note + '<div class="note">No accounts yet. Run '
            '<code>/admin/register_owner</code> first — it seeds the five.'
            '</div>' + _routes_panel(expanded=True)))

    t = rows[0]

    from . import credentials as _cred
    try:
        n_failed = sum(1 for r in _cred.status(tenant)
                       if r.get("state") == "failed")
    except Exception:                                            # noqa: BLE001
        n_failed = 0

    def _sub_href(k: str) -> str:
        return (f"/admin/ui?tab=accounts"
                + (f"&amp;sub={k}" if k else "")
                + f"&amp;tenant={_esc(tenant)}"
                + (f"&amp;key={_esc(key)}" if key else ""))

    strip = '<div class="subtabs">' + "".join(
        f'<a class="subtab{" on" if k == sub else ""}" href="{_sub_href(k)}">'
        f'{_esc(label)}'
        + (f'<span class="cnt">{n_failed}</span>'
           if k == "" and n_failed else "")
        + '</a>'
        for k, label in ACCOUNTS_SUBS) + "</div>"

    if sub == "people":
        body = f"""
<div class="card">
  <div class="head"><h2>{_esc(t.name)} — people &amp; links</h2>
    <code>{_esc(t.key)}</code></div>
  {_people(tenant, key)}
  <details class="conns" open>
    <summary>Links to send</summary>
    <p class="mut">A <b>connect link</b> lets the client wire their own
    tools; an <b>intake link</b> asks them this account's open questions.
    Each reaches one account and nothing else; minted links flash at the
    top of this page, copyable.</p>
    <form method="post" action="/admin/connect_link" class="row mklink">
      <input type="hidden" name="key" value="{_esc(key)}">
      <input type="hidden" name="tenant" value="{_esc(tenant)}">
      <input name="label" placeholder="who it is for, e.g. Jane" required>
      <input name="days" value="30" size="3" title="days until it expires">
      <button class="sec">Create a connect link</button>
    </form>
    {_intake_links(t.key, key)}
  </details>
</div>"""
    elif sub == "advanced":
        fields = "".join(_field(t, key, f) for f in
                         # `domain` FIRST — the most load-bearing field on
                         # the row: `harvest` and `compliance` refuse
                         # without it, `sites` builds no profile, and
                         # `seo_guard` joins on it.
                         ("domain", "gmail_alias", "shopify_store", "esp",
                          "cms", "ads", "analytics", "crm", "design",
                          "systems"))
        body = f"""
<div class="card">
  <div class="head"><h2>{_esc(t.name)} — advanced</h2>
    <code>{_esc(t.key)}</code></div>
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
  <details class="sec">
    <summary>Raw wiring — this account's connection keys</summary>
    <div class="mut">These fields are <strong>keys into</strong>
    credential dictionaries or env-var names — never secrets. The
    secrets themselves are either in the Render env group or, for
    anything a client connected themselves, encrypted in the
    database and shown only as a state. Saving lands back here with a
    flash; changes take effect immediately, no redeploy.</div>
    <div class="grid">{fields}</div>
  </details>
</div>

<details class="sec">
  <summary>Add an account</summary>
  <form method="get" action="/admin/tenant_add" class="grid">
    <input type="hidden" name="key" value="{_esc(key)}">
    <input type="hidden" name="ui" value="1">
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
  <div class="when">Creating lands back here with a flash; changes take
  effect immediately, no redeploy.</div>
</details>

<details class="sec">
  <summary>Give someone bot access
    <span class="chip nb">parked by choice</span></summary>
  <p class="mut">Parked, deliberately — not broken: ops commands are scoped
  correctly, but free-text questions fall through to an agent that is not
  tenant-scoped. Switch-on condition: reporting and agent scoping land.
  The form works today for OWNER-side users; hold off on clients.</p>
  <p class="mut">They message the bot first — it replies with their chat id
  because it doesn't recognise them. Paste that id here.</p>
  <form method="get" action="/admin/user_add" class="grid">
    <input type="hidden" name="key" value="{_esc(key)}">
    <input type="hidden" name="ui" value="1">
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
</details>

{_routes_panel()}"""
    else:
        caps = tenants.capabilities(t.key)
        missing = [c for c, ok in caps.items() if not ok]
        body = f"""
<div class="card">
  <div class="head">
    <h2>{_esc(t.name)}</h2>
    <code>{_esc(t.key)}</code>
    <span class="mut">{_esc(t.kind)} · {_esc(t.domain) or 'no domain'}</span>
  </div>
  <div class="chips">{_chips(caps)}</div>
  <div class="mut">Missing: {', '.join(missing) or 'nothing — fully wired'}</div>
  {_verify_summary(tenant, key)}
  <div class="row">
    <form method="get" action="/admin/verify" style="display:inline">
      <input type="hidden" name="key" value="{_esc(key)}">
      <input type="hidden" name="tenant" value="{_esc(t.key)}">
      <input type="hidden" name="ui" value="1">
      <button class="sec">Test connections</button>
    </form>
    <span class="mut">runs in the background — the per-provider result
    lands on this card</span>
  </div>
  {_connections(t.key, key)}
</div>"""

    return _shell(key, "accounts", "Connections", tenant=tenant,
                  body=note + strip + body)


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
    from . import approvals as _apm
    return [a for a in rows
            if (a.system_id == row.id or (a.run_id and a.run_id in run_ids))
            # Same predicate as the console queue, the waiting pill and the
            # briefing (2026-08-27). A drafted reply is answered in the
            # mailbox, so counting it here made this system's "waiting on
            # you" disagree with every other surface that says the phrase.
            and _apm.decided_in_console(a)]


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


def _board_counts(rows: list) -> dict:
    """Every board row's work strip, in TWO queries for the whole page.

    The per-card version asked the database five times per system — and two
    of those (`stats`, `_shipped_runs`) loaded that system's ENTIRE run
    history, with `_measured` loading it a third time. On the all-accounts
    view that multiplied by five clients (spec §8 names it: "its per-card
    queries multiply by every installed system").

    So the page asks once: one pass over the runs belonging to the systems
    actually being rendered, one over this page's pending approvals. Each
    number is still computed from the same rows the workflow view lists, so
    a count and its list cannot disagree (design rule 8).
    """
    import datetime as _dt
    from . import approvals as _apm

    ids = [r.id for r in rows]
    out = {i: {"planned": 0, "waiting": 0, "week": 0,
               "measured": 0, "as_is": 0} for i in ids}
    if not ids:
        return out
    week_ago = db.utcnow() - _dt.timedelta(days=7)
    tenants_on_page = {r.tenant for r in rows}

    with db.SessionLocal() as s:
        runs = (s.query(db.SystemRun)
                .filter(db.SystemRun.system_id.in_(ids)).all())
        pend = (s.query(db.Approval)
                .filter(db.Approval.tenant.in_(list(tenants_on_page)),
                        db.Approval.status == "pending").all())
        s.expunge_all()

    run_owner = {r.id: r.system_id for r in runs}
    for r in runs:
        c = out.get(r.system_id)
        if c is None:
            continue
        if r.stage == systems.PLANNED:
            c["planned"] += 1
            continue
        if (r.edit_diff or "").strip():
            c["measured"] += 1
            try:
                if json.loads(r.edit_diff).get("as_is"):
                    c["as_is"] += 1
            except (ValueError, AttributeError):
                pass
        if r.stage in ("sent", "approved") and r.decision != "denied":
            if db.as_utc(r.finished_at or r.created_at) >= week_ago:
                c["week"] += 1

    for a in pend:
        if not _apm.decided_in_console(a):
            continue           # answered in the mailbox, not here
        owner = a.system_id if a.system_id in out else run_owner.get(a.run_id)
        if owner in out:
            out[owner]["waiting"] += 1
    return out


def _sysview_url(key: str, row, anchor: str = "", ppage: int = 0) -> str:
    """A link into one system's workflow view.

    `anchor` names both the sub-view and the in-page anchor, because the four
    it is ever called with — planned, waiting, shipped, measured — were the
    old stacked page's anchor ids and are now the rail's keys. Emitting both
    means every existing link keeps working and lands on the right tab
    (fluidity rule 3: URLs and params never break).
    """
    url = (f"/admin/ui?key={_esc(key)}&amp;tab=systems"
           f"&amp;tenant={_esc(row.tenant)}&amp;system={_esc(row.key)}")
    if anchor:
        url += f"&amp;wf={anchor}"
    if ppage and ppage > 1:
        url += f"&amp;ppage={ppage}"
    return url + (f"#{anchor}" if anchor else "")


def _work_strip(key: str, row, c: dict | None = None) -> str:
    """One line of state per system: what is queued, waiting, shipped, kept.

    Counts, each linking into the section of the system's own view that
    holds the rows behind it — state first, and the click lands on the work
    rather than on an explanation of it.

    `c` is this system's row from `_board_counts`, so a board of N systems
    costs two queries rather than five per card. Without it the strip still
    asks for itself, which is what the single-system workflow view wants.
    """
    if c is None:
        c = _board_counts([row])[row.id]
    bits: list[str] = []
    if systems.plan_capable(row.key):
        bits.append(f'<a href="{_sysview_url(key, row, "planned")}">'
                    f'<b>{c["planned"]}</b> planned</a>')
    bits.append(f'<a href="{_sysview_url(key, row, "waiting")}">'
                f'<b>{c["waiting"]}</b> waiting on you</a>')
    bits.append(f'<a href="{_sysview_url(key, row, "shipped")}">'
                f'<b>{c["week"]}</b> shipped this week</a>')
    if c["measured"]:
        bits.append(f'<a href="{_sysview_url(key, row, "measured")}">'
                    f'<b>{c["as_is"]} of {c["measured"]}</b> sent as-is</a>')
    return '<div class="workstrip">' + " · ".join(bits) + "</div>"


def _system_toggle(key: str, row, r: dict) -> str:
    """ONE CONTROL THAT SHOWS THE STATE AND CHANGES IT (owner, 2026-08-23).

    This was two different buttons that swapped places — "Switch on" when
    off, "Pause" when on — so the same pixel meant opposite things and the
    only way to know the state was to read the label of the thing that would
    change it. And when a system could not go live, NEITHER rendered, so the
    page fell silent exactly where it needed to explain itself.

    The route and its semantics are unchanged: a system that is not ready
    still cannot be switched on. What changes is that the refusal is now
    visible and says why, instead of being an absence.

    Extracted in step 4 (spec §8: "one toggle convention everywhere") because
    the workflow view still rendered the OLD pair of buttons — two opposite
    labelling conventions for one operation, one click apart. Both surfaces
    call this now, so there is one component and one vocabulary.
    """
    on = row.status == "live"
    if on:
        live = (f'<a class="tog on" title="Live — click to pause" '
                f'href="/admin/system_set?key={_esc(key)}&amp;id={_esc(row.id)}'
                f'&amp;status=paused"><span class="tr"><span class="kn"></span>'
                f'</span>ON</a>')
    elif r["ready"]:
        live = (f'<a class="tog" title="Off — click to switch on" '
                f'href="/admin/system_set?key={_esc(key)}&amp;id={_esc(row.id)}'
                f'&amp;status=live"><span class="tr"><span class="kn"></span>'
                f'</span>OFF</a>')
    else:
        why = "; ".join(r["impossible"] or r["thin"])[:120] or "it is not ready"
        live = (f'<span class="tog dis" title="{_esc(why)}">'
                f'<span class="tr"><span class="kn"></span></span>OFF</span>')
    return live


def _gate_chip(key: str, row, r: dict) -> str:
    """The gate as ONE chip on the board — Ready, Blocked (first reason), or
    Running thin.

    THREE states, not two (design rule 2). A system that cannot reach its
    connection is blocked; a system missing knowledge or a contract now
    PRODUCES, thinly, and calling that "blocked" would have the console
    contradicting the worker, which is running it every tick.

    The board carries the verdict and the FIRST reason — enough to know
    whether to go in. The full list, each blocker with its own fix link,
    lives in the workflow view where the work is (spec §8: everything but
    identity, toggle, description, gate, strip and the link moves there).
    """
    if r["ready"]:
        return '<span class="chip on" title="Everything it needs is connected and the contract is complete.">Ready</span>'
    if not r["can_produce"]:
        first = (r["impossible"] or ["a connection is missing"])[0]
        return (f'<span class="chip off" title="{_esc(first)}">Blocked &mdash; '
                f'{_esc(str(first)[:48])}</span>')
    first = (r["thin"] or [""])[0]
    return (f'<span class="chip nb" title="{_esc(first)} — this gates GOING '
            f'LIVE, not producing.">Running thin</span>')


def _system_card(key: str, row, c: dict | None = None) -> str:
    """One COMPACT board row (spec §8).

    This card used to be fifteen kinds of thing — identity, toggle, workflow
    link, description, work strip, the full gate, the autonomy ladder, run
    stats, promote/demote, an 8-field contract form, the guidance thread, a
    hard-rule form and a run log — which made a five-account board
    unscannable and loaded every system's entire run history three times to
    draw it.

    What is left is what you scan: who it is, whether it is on, what it does,
    whether it can run, and the work. Everything else moved to the workflow
    view, which is one click away and is where you would act on any of it.
    """
    r = systems.ready(row)
    return f"""
    <div class="card">
      <div class="head">
        <h3>{_esc(row.name)}</h3>
        <code>{_esc(row.key)}</code>
        <span class="chip {'on' if row.autonomy == 'auto' else 'off'}">{_esc(row.autonomy)}</span>
        {_gate_chip(key, row, r)}
        <span class="grow"></span>
        {_system_toggle(key, row, r)}
      </div>
      <div class="mut">{_esc(systems.spec(row.key)["does"])}</div>
      {_work_strip(key, row, c)}
      <div class="row">
        <a class="btn" href="{_sysview_url(key, row)}">Workflow &rarr;</a>
        <span class="mut">plan the work, see what ran, correct it</span>
      </div>
    </div>"""


PLANS_PAGE = 15


def _plan_fields_split(key_: str, get, tenant: str) -> str:
    """Required fields in the open; everything else folded, and named.

    Every declared field rendered flat with equal weight is what "it's a lot of
    different fields" described (owner, 2026-08-23). For campaign_email it is
    eight boxes of which TWO decide whether the plan can run — the rest change
    what the send is LIKE, and none of them stop it. Showing all eight the same
    way makes a two-field job look like an eight-field one, and the person
    filling it in cannot tell which boxes they are allowed to leave alone.

    Nothing is hidden that was not already optional, and the fold names what is
    inside it, so it is never a mystery drawer.
    """
    fields = systems.workflow(key_)["plan_fields"]
    req = [f for f in fields if f.get("required")]
    rest = [f for f in fields if not f.get("required")]
    out = "".join(_plan_field_input(f, get(f["key"]), tenant) for f in req)
    if rest:
        names = ", ".join(str(f.get("label") or f["key"]).lower() for f in rest)
        out += ('<details class="sec" style="grid-column:1/-1">'
                '<summary>Optional &mdash; ' + _esc(names[:110]) + '</summary>'
                + "".join(_plan_field_input(f, get(f["key"]), tenant)
                          for f in rest)
                + '<p class="mut">None of these stop the plan running. They '
                  'change what the send is like.</p></details>')
    return out


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
        #
        # DRAFT PRODUCTS ARE NOT OFFERED — at all (owner, 2026-08-27: "draft
        # products shouldn't even be accessible to the system"). fitness.py
        # already screens the DRAFTER's pool and catches one named anyway;
        # this closes the last door, the one facing the owner: a select that
        # lists a draft/archived product invites a plan the run must then
        # refuse. Out-of-stock stays listed WITH its label — stock is a
        # temporary state a plan may legitimately wait out; draft is a
        # decision the store owner has not made yet.
        cur = str(value or "").strip()
        rows = sorted((r for r in kb.entities(tenant, available_only=False)
                       if (r.availability or "available")
                       not in ("draft", "archived", "unpublished")),
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
                # No key= on purpose: this renders inside a helper the key
                # never reaches, and the console session cookie authenticates
                # the click — the same reason _sub_href drops it when empty.
                f'<a href="/admin/ui?tab=content&amp;sub=catalogue'
                f'&amp;tenant={_esc(tenant)}">catalogue '
                'sync on the Review tab</a> first</div>')
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

    fields = _plan_fields_split(row.key,
                                lambda k: plan.get(k, ""), row.tenant)
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

    new_fields = _plan_fields_split(row.key, lambda _k: "", row.tenant)
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
        create = ('<p class="mut">Filing plans needs the system on — '
                  'switch on above once the gate is clear (when it is '
                  'blocked, the gate note names what to connect first). '
                  'Existing plans stay editable meanwhile.</p>')

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
        # PROPOSE IS THE FAST PATH AND IT WAS THE HIDDEN ONE. Pressing it
        # produces COMPLETE plans — every required field filled from the
        # segment catalog, nothing missing — and it was folded inside a
        # <details> whose summary says "Cadence", a word that does not read as
        # "make some work now". Meanwhile the empty queue opened the 8-field
        # hand form. So the page led with the slow path and hid the fast one
        # (owner, 2026-08-23: "it should be easier to get things moving").
        #
        # Out of the fold, above the queue, and only when the queue is empty —
        # once there ARE plans, proposing again is a cadence decision and
        # belongs back with cadence.
        lead = propose if not total else ""
        planner_ctl = (f'<div class="row" style="margin-top:4px">{lead}</div>'
                       if lead else "") + f"""
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
          {"" if lead else propose}
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
    """This system's approval queue, DECIDED IN PLACE (spec §8b).

    It used to render ✅ / ❌ as bare links into the unstyled `/decide` page
    with no way back — the same defect Review's ship queue was rebuilt to end
    a fortnight ago, still living here. Same executor (`apply_decision`), the
    same consequence-stating button, and the redirect returns to this tab.
    """
    pend = _pending_for_system(row)
    if not pend:
        body = '<p class="mut">Nothing is waiting on you.</p>'
    else:
        def _row(a) -> str:
            pl = a.payload or {}
            prov = (pl.get("esp_push") or {}).get("provider", "")
            if prov:
                says = f"Approve — pushes the draft to {_esc(prov)}"
            elif a.kind == "seo_new_article":
                says = "Approve &amp; publish"
            elif a.kind == "send_email":
                says = "Approve — sends it"
            elif a.kind == "skill_output":
                says = "Approve — marks it reviewed, ready"
            else:
                says = "Approve"
            review = ""
            if a.kind == "seo_new_article" and pl.get("output_id"):
                review = (f' <a href="/admin/article/{_esc(pl["output_id"])}'
                          f'?key={_esc(key)}">review &amp; edit &rarr;</a>')
            elif pl.get("output_id"):
                review = (f' <a href="/admin/work/{_esc(pl["output_id"])}'
                          f'?key={_esc(key)}">open workroom &rarr;</a>')

            def _btn(verdict: str, label: str, cls: str = "") -> str:
                return f"""
                <form method="post" action="/admin/ship_decide" class="inl">
                  <input type="hidden" name="key" value="{_esc(key)}">
                  <input type="hidden" name="tenant" value="{_esc(row.tenant)}">
                  <input type="hidden" name="approval_id" value="{_esc(a.id)}">
                  <input type="hidden" name="back_system" value="{_esc(row.key)}">
                  <input type="hidden" name="verdict" value="{verdict}">
                  <button class="{cls}">{label}</button>
                </form>"""
            return f"""
            <div class="msg"><div><b>{_esc(a.summary or a.kind)}</b></div>
              {_ship_preview(pl)}
              <div class="row">
                {_btn("approved", says)}
                {_btn("denied", "Deny", "sec")}
                <span class="when">{a.created_at:%b %d, %H:%M}{review}</span>
              </div>
            </div>"""
        body = "".join(_row(a) for a in pend[:15])
    return f"""
    <div class="card"><div class="anchor" id="waiting"></div>
      <div class="head"><h2>Waiting on you</h2>
        <span class="chip {'off' if pend else 'on'}">{len(pend)} pending</span>
        <span class="mut">deciding here does the same thing as deciding on
        Review — and brings you back here</span></div>
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
    # It LEADS WITH ITS OWN FACT (spec §8b). This repeated the board's
    # five-number run stat under a headline that was the only thing on the
    # card anyone came for — so the number this system is trying to move sat
    # in a row of five that say nothing about it. The stat lives once now,
    # on Runs, beside the runs it counts.
    deltas = ""
    rows = [r for r in systems.runs(row.id, limit=0)
            if (r.edit_diff or "").strip()]
    if rows:
        items = ""
        for r in rows[:8]:
            try:
                d = json.loads(r.edit_diff)
                what = ("sent as-is" if d.get("as_is") else
                        f"{d.get('lines_changed', '?')} line(s) changed")
                sample = str(d.get("sample") or "")[:160]
            except (ValueError, AttributeError):
                what, sample = str(r.edit_diff)[:60], ""
            items += (f'<div class="msg"><div>{_esc(what)}'
                      f'<span class="when"> · '
                      f'{(r.finished_at or r.created_at):%b %d}</span></div>'
                      + (f'<div class="when">{_esc(sample)}</div>'
                         if sample else "") + "</div>")
        deltas = ('<p class="mut">What a person changed, most recent first — '
                  'this is the list the rate is computed from:</p>'
                  f'<div class="thread">{items}</div>')
    return f"""
    <div class="card"><div class="anchor" id="measured"></div>
      <div class="head"><h2>Measured</h2>
        <span class="mut">the share of sends nobody had to touch</span></div>
      <div class="stat">{headline}</div>
      {gap}
      {deltas}
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
                 # A live write into the CLIENT'S ESP account asks first,
                 # naming the account and the count (spec §8b). Preview
                 # beside it is a dry run and does not.
                 f'<form method="get" action="/admin/segments_build" '
                 f'class="inl" onsubmit="return confirm('
                 f'&quot;Create {len(to_build)} segment(s) in '
                 f'{_esc(row.tenant)}&#39;s live ESP account?&quot;)">'
                 f'<input type="hidden" name="key" value="{_esc(key)}">'
                 f'<input type="hidden" name="tenant" value="{_esc(row.tenant)}">'
                 f'<input type="hidden" name="ui" value="1">'
                 f'<input type="hidden" name="system" value="{_esc(row.key)}">'
                 f'<input type="hidden" name="apply" value="1">'
                 f'<button>Create {len(to_build)} in the ESP</button></form>'
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


def _settings_section(key: str, row) -> str:
    """What the board stopped carrying: the ladder, promote/demote, the
    contract, the guidance thread — and the FULL gate with a fix link per
    blocker (spec §8).

    None of it was scannable on a board of N systems across five accounts,
    and all of it is something you act on having already decided to work on
    THIS system — which is the click that got you here.
    """
    r = systems.ready(row)
    if r["ready"]:
        gate = ('<div class="ok">Ready. Everything it needs is connected and '
                'the contract is complete.</div>')
    elif not r["can_produce"]:
        items = "".join(_blocker_li(key, row.tenant, b) for b in r["impossible"])
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

    nxt = systems.can_promote(row)
    if nxt["can"]:
        promo = (f'<a href="/admin/system_promote?key={_esc(key)}&amp;id={_esc(row.id)}">'
                 f'<button type="button">Promote to {_esc(nxt["target"].replace("_", " "))}</button></a>')
    elif nxt["target"]:
        promo = f'<span class="mut">Next rung ({_esc(nxt["target"].replace("_", " "))}): {_esc(nxt["why"])}</span>'
    else:
        promo = '<span class="mut">Top of the ladder.</span>'
    # THE LADDER GOES DOWN TOO. The nightly sweep has always advised "work
    # them or turn the system down a rung" for a swollen queue — and only
    # Promote existed, so the advice named a control the console did not
    # have. LESS autonomy needs no earning, so the promote gate does not apply.
    _l = list(systems.AUTONOMY)
    _cur = (row.autonomy or "shadow")
    if _cur in _l and _l.index(_cur) > 0:
        _down = _l[_l.index(_cur) - 1]
        promo += (f' <a href="/admin/system_set?key={_esc(key)}'
                  f'&amp;id={_esc(row.id)}&amp;autonomy={_esc(_down)}'
                  f'&amp;tenant={_esc(row.tenant)}">'
                  f'<button class="sec" type="button">Down a rung '
                  f'({_esc(_down.replace("_", " "))})</button></a>')
    return f"""
    <div class="card"><div class="anchor" id="settings"></div>
      <div class="head"><h2>Settings</h2>
        <span class="mut">what it needs, how far it may go, and what it has
        been told</span></div>
      {gate}
      {_rung(row.autonomy or "shadow")}
      <div class="row">{promo}</div>
      {_contract_form(key, row)}
      {_thread(key, row)}
    </div>"""


def _runs_section(key: str, row) -> str:
    """The run log, and the five numbers a promotion decision needs.

    The stat row used to sit on every board card AND be repeated by Measured.
    It lives here once now — beside the runs it counts, which is the only
    place it can be checked.
    """
    st = systems.stats(row.id)
    return f"""
    <div class="card"><div class="anchor" id="runs"></div>
      <div class="head"><h2>Runs</h2></div>
      <div class="stat">
        <span><b>{st['total']}</b> runs</span>
        <span><b>{st['approved']}</b> approved</span>
        <span><b>{st['edited']}</b> edited</span>
        <span><b>{st['denied']}</b> denied</span>
        <span><b>{st['blocked']}</b> blocked</span>
      </div>
      {_runs(row, st['total'])}
    </div>"""


#: The workflow view's inner rail (spec §8b), in the order the work moves.
#: Segments is ESP-only and is added by `_workflow_subs`; the four names that
#: were anchors on the old stacked page (`planned`, `waiting`, `shipped`,
#: `measured`) are the sub keys too, so every link that pointed at an anchor
#: still lands on the right place (fluidity rule 3).
WORKFLOW_SUBS = (("planned", "Plan queue"), ("drafts", "Drafts"),
                 ("waiting", "Waiting on you"), ("shipped", "Shipped"),
                 ("measured", "Measured"), ("settings", "Settings"),
                 ("runs", "Runs"))


def _workflow_subs(row) -> tuple:
    """The rail for THIS system. Segments only exists for the ones that push
    to an ESP — offering an empty room on a blog system would be a tab that
    teaches you it does nothing."""
    subs = list(WORKFLOW_SUBS)
    if systems.workflow(row.key)["artifact"] == "esp_campaign":
        subs.insert(5, ("segments", "Segments"))
    return tuple(subs)


def _system_view(key: str, row, flash: str, ppage: int = 1,
                 wf: str = "") -> str:
    """One system's workflow: planned, waiting, shipped, measured — in the
    order the work moves, with the queue's controls leading each section.

    Step 4 (spec §8b) gave it the inner rail every other restructured tab
    has. The page was every section stacked, so reaching Measured on a system
    with fifteen plans meant scrolling past all of them, and the sections you
    rarely touch (Settings, Runs) cost the same scroll as the one you came
    for. Each section still renders whole; only one at a time is asked for.
    """
    wfd = systems.workflow(row.key)
    subs = _workflow_subs(row)
    sub = (wf or "").strip().lower()
    if sub not in dict(subs):
        sub = subs[0][0]

    ship_note = (f'<p class="mut">One item is {_esc(wfd["unit"])}. '
                 f'Approving {_esc(wfd["ship"] or "ships it")}.</p>'
                 if wfd["unit"] else "")

    # The gate, on the page whose queue it holds shut. A Planned list on a
    # system that cannot produce reads as "will run on its date" — when the
    # truth is that every attempt is refused until a connection is wired,
    # and a queue that can never drain must say so where the queue is.
    gate = systems.ready(row)
    gate_note = ""
    if not gate["can_produce"]:
        items = "".join(_blocker_li(key, row.tenant, b) for b in gate["impossible"])
        gate_note = ('<div class="note"><strong>Cannot produce.</strong>'
                     f'<ul class="bl">{items}</ul>'
                     '<div class="mut">Plans keep and stay editable; they '
                     'run once this is wired.</div></div>')

    counts = _board_counts([row])[row.id]

    def _href(v: str) -> str:
        return (f"/admin/ui?tab=systems&amp;tenant={_esc(row.tenant)}"
                f"&amp;system={_esc(row.key)}&amp;wf={v}"
                + (f"&amp;key={_esc(key)}" if key else ""))

    #: Counts on the rail come from the SAME batch the strip renders, so a
    #: tab label and the list behind it cannot disagree (design rule 8).
    tab_counts = {"planned": counts["planned"], "waiting": counts["waiting"],
                  "shipped": counts["week"]}
    strip = '<div class="subtabs">' + "".join(
        f'<a class="subtab{" on" if v == sub else ""}" href="{_href(v)}">'
        f'{label}'
        + (f'<span class="cnt">{tab_counts[v]}</span>' if v in tab_counts else "")
        + '</a>' for v, label in subs) + "</div>"

    sections = {
        "planned": lambda: _planned_section(key, row, ppage),
        "drafts": lambda: _drafts_section(key, row),
        "waiting": lambda: _waiting_section(key, row),
        "shipped": lambda: _shipped_section(row),
        "measured": lambda: _measured_section(row),
        "segments": lambda: _segments_card(key, row),
        "settings": lambda: _settings_section(key, row),
        "runs": lambda: _runs_section(key, row),
    }

    body = f"""
{flash}
<div>
  <div class="crumb"><a href="/admin/ui?key={_esc(key)}&amp;tab=systems&amp;tenant={_esc(row.tenant)}">&larr; Systems</a></div>
  <div class="head" style="border-bottom:0;padding-bottom:0">
    <h2>{_esc(row.name)}</h2>
    <code>{_esc(row.key)}</code>
    <span class="chips">
      <span class="chip {'on' if row.status == 'live' else 'off'}">{_esc(row.status)}</span>
      <span class="chip {'on' if row.autonomy == 'auto' else 'off'}">{_esc(row.autonomy)}</span>
    </span>
    <span class="grow"></span>
    {_system_toggle(key, row, gate)}
  </div>
  {ship_note}
  {_work_strip(key, row, counts)}
  {gate_note}
</div>
{strip}
{sections[sub]()}
<details class="sec"><summary>How to read this page</summary>
  <p class="mut">Planned is work declared in advance — each plan is editable
  until the moment it runs, an incomplete plan waits and names its gaps, and
  on the shadow / approve-all rungs a complete plan still waits for your
  explicit approval because running it has real side effects. Waiting on you
  is this system's approval queue. Shipped is what actually went out.
  Measured is the edit delta — the share of sends a human did not have to
  touch, which is the number this system is trying to move. Settings holds
  the gate, the autonomy ladder, the contract and what this system has been
  told.</p>
</details>"""
    return _shell(key, "systems", f"{row.name} — workflow",
                  tenant=row.tenant, body=body,
                  suffix=f"&amp;system={_esc(row.key)}")


#: A board of systems is a list like any other, and this one was the last
#: unpaginated queue in the console.
SYSTEMS_PAGE = 15


#: The Systems tab's two jobs. They are not two halves of one page: one is a
#: place you WORK (the systems that exist, every day) and the other is a place
#: you SHOP (the catalogue, rarely, once per system ever). Stacking them put
#: the shop first and made the daily work scroll (owner, 2026-08-23).
SYSTEM_SUBS = (("active", "Active"), ("available", "Available"))


def render_systems(key: str, tenant: str = "", msg: str = "", err: str = "",
                   system: str = "", ppage: int = 1, sub: str = "",
                   wf: str = "") -> str:
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
            return _system_view(key, target, flash, ppage=ppage, wf=wf)
        flash += (f'<div class="note">No <code>{_esc(system)}</code> system '
                  f'is installed for this account — the list below is what '
                  f'is.</div>')

    all_rows = systems.all_systems() if every else systems.for_tenant(tenant)
    # THE BOARD PAGES (spec §8: it was unpaginated, and on the all-accounts
    # view that is five clients' systems in one unbounded list). Paged before
    # grouping, so the group headings describe what is actually on the page.
    total_rows = len(all_rows)
    _pages = max(1, -(-total_rows // SYSTEMS_PAGE))
    _pg = max(1, min(ppage if sub != "available" else 1, _pages))
    rows = all_rows[(_pg - 1) * SYSTEMS_PAGE:_pg * SYSTEMS_PAGE]
    board_pager = _pager(
        f"/admin/ui?tab=systems&amp;sub=active&amp;tenant={_esc(tenant)}"
        + (f"&amp;key={_esc(key)}" if key else ""),
        _pg, total_rows, SYSTEMS_PAGE, "systems")
    # Two queries for the whole board, not five per card (spec §8).
    counts = _board_counts(rows)

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
        body = board_pager
        for tkey, group in sorted(by_tenant.items()):
            t = tenants.get(tkey)
            cards = "".join(_system_card(key, r, counts.get(r.id))
                            for r in group)
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
        live = sum(1 for r in all_rows if r.status == "live")
        body = f"""
        <div>
          <div class="head" style="margin-bottom:12px">
            <h2>Installed</h2>
            <span class="mut">{live} of {total_rows} live</span>
          </div>
          {board_pager}
          {"".join(_system_card(key, r, counts.get(r.id)) for r in rows)}
          {board_pager}
        </div>"""

    # Scoped to the account too. An unscoped backlog ranks another client's
    # missing knowledge above this one's, and the fix it points at is filed
    # against a knowledge base this page cannot reach.
    # THE REFUSED LIST MOVED TO DIAGNOSTICS (owner, 2026-08-23: "I dont even
    # think that belongs here but rather on the diagnostics page"). It was a
    # flat `<ul>` of "12× no_ban_list" — no dates, nothing clickable, no way to
    # see a single example — sitting ABOVE the systems it was about, so the
    # first thing this tab showed was a diagnosis you could not act on and the
    # installed systems needed a scroll to reach.
    #
    # What replaces it is a SIGNPOST, not the list: one line with the count and
    # the way through. A tab that silently drops a number people relied on
    # teaches them the number was never real.
    backlog = systems.attention("" if every else tenant, 30)
    backlog_html = ""
    if backlog:
        _n = sum(a["count"] for a in backlog)
        _href = ("/admin/ui?tab=diagnostics&amp;view=systems&amp;tenant="
                 + _esc(tenant) + (f"&amp;key={_esc(key)}" if key else ""))
        backlog_html = f"""
        <div class="card">
          <div class="head"><h2>Something needs attention</h2>
            <span class="chip off">{_n} in 30 days</span></div>
          <p class="mut">{len(backlog)} distinct thing(s) refused a run or
          shipped with it. The diagnosis lives on Diagnostics now, with the runs
          themselves — dates, which system, and what each one actually said.</p>
          <div class="row"><a class="btn sec" href="{_href}">Systems check
            &rarr;</a></div>
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
            # It named a system and pointed nowhere (spec §8). The catalogue
            # is the one place you meet a system before you own it, so the
            # already-installed entry is exactly where "take me to it"
            # belongs.
            _wf = (f"/admin/ui?tab=systems&amp;tenant={_esc(tenant)}"
                   f"&amp;system={_esc(p['key'])}"
                   + (f"&amp;key={_esc(key)}" if key else ""))
            action = (f'<span class="mut">installed &middot; '
                      f'{_esc(p["status"] or "designed")} &middot; '
                      f'{_esc(p["autonomy"] or "shadow")}</span> '
                      f'<a class="btn sec" href="{_wf}">Workflow &rarr;</a>')
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

    sub = (sub or "").strip().lower()
    if sub not in dict(SYSTEM_SUBS):
        sub = SYSTEM_SUBS[0][0]

    # The catalogue is per-account, so on the all-accounts view there is
    # nothing to install and the strip would offer an empty room.
    n_avail = 0 if every else len(
        [p for p in (systems.installable(tenant) if tenant else [])
         if not p["installed"]])

    def _sub_href(v: str) -> str:
        return ("/admin/ui?tab=systems&amp;sub=" + v
                + f"&amp;tenant={_esc(tenant)}"
                + (f"&amp;key={_esc(key)}" if key else ""))

    strip = "" if every else '<div class="subtabs">' + "".join(
        f'<a class="subtab{" on" if v == sub else ""}" href="{_sub_href(v)}">'
        f'{label}<span class="cnt">'
        f'{total_rows if v == "active" else n_avail}</span></a>'
        for v, label in SYSTEM_SUBS) + "</div>"

    return _shell(key, "systems", "Systems", tenant=tenant, body=f"""
{flash}
{_every_note(every, "Every account's pipelines, grouped by client. "
             "Installing and the contract forms are on an account's own page.")}
<div>
  <p class="mut">One row per installed pipeline. A system is not on because it has a
  name — it is on when its contract is answered, its connections work, and the
  knowledge base can ground it. Everything below refuses in public rather than
  guessing in private.</p>
</div>

{backlog_html}
{strip}
{installer if sub == "available" and not every else ""}
{body if sub == "active" or every else ""}

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
    # The letter-format sign-off reads theme["sender"]["name"] and dropped
    # the signature with "set it on the Brand tab" when empty — a direction
    # at a control that did not exist. The dotted path writes the nested
    # shape the reader expects, exactly as footer.address already does.
    ("sender.name", "Sender name", "signs letter-format emails — with no "
                                   "name the sign-off is dropped"),
)

_BRAND_CSS = """<style>
.bt-frame{width:100%;height:480px;border:1px solid var(--rule);border-radius:6px;background:#fff}
.bt-table{border-collapse:collapse;width:100%;font-size:.82rem;margin:8px 0}
.bt-table td,.bt-table th{border:1px solid var(--rule);padding:4px 8px;text-align:left}
.bt-form input[type=text]{width:100%;box-sizing:border-box;padding:5px}
.bt-form td{vertical-align:top}
/* A source row is a label and a URL side by side, each wide enough to READ
   at a glance — an unreadable URL in a list of sites is a list you cannot
   check. They grow to share the row and wrap on a phone. */
.src-cell{flex:1 1 15rem;min-width:0}
.src-cell input{width:100%;box-sizing:border-box;padding:5px}
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

    # --- where the facts are read from: one website, N landing pages -------
    # The owner's constraint (2026-08-27) is the whole design: "some brands
    # have several domains including landing pages" — but ONE of them is the
    # website, and branding, positioning and tone come from that one only. So
    # the page says that in words, not just in code: the website is labelled
    # the identity source, and the landing pages are labelled facts-only.
    srcs = tenants.content_sources(tenant)
    lps = [x for x in srcs if x["role"] == "landing_page"]
    src_rows = "".join(f"""
    <div class="conn-site">
      <span class="src-cell"><input name="lp_label" value="{_esc(x['label'])}"
             placeholder="what this page is"></span>
      <span class="src-cell"><input name="lp_url" value="{_esc(x['url'])}"></span>
      <label class="pick"><input type="checkbox" name="lp_drop"
             value="{_esc(x['url'])}"> remove</label>
    </div>""" for x in lps) or (
        '<p class="mut">None recorded — only the website is read. If this '
        'brand runs campaign landing pages, the claims and the banned '
        'phrases on them are invisible to every system until they are '
        'listed here.</p>')
    sources_card = f"""
<div class="anchor" id="sources"></div>
<div class="card">
  <div class="head"><h2>Where their words are read from</h2>
    <span class="mut">{len(srcs)} site{"" if len(srcs) == 1 else "s"}</span></div>
  <p class="mut">The <b>website</b> is the identity source: positioning, tone
  and the email theme are derived from it and from nothing else. Landing
  pages are read for <b>facts only</b> — harvest proposes claims, objections
  and pictures off them, and the ban-list scan checks them, because a banned
  phrase on a landing page is exactly as live as one on the homepage.
  <b>Voice is never derived from a landing page</b>: a page written for one
  campaign is the loudest month of the year, not how the brand speaks.</p>
  <form class="f" method="post" action="/admin/brand_sources">
    <input type="hidden" name="tenant" value="{_esc(tenant)}">
    <label>Website &mdash; the identity source</label>
    <input name="website" value="{_esc(t.domain if t else '')}"
           placeholder="not set — nothing can be derived, harvested or scanned">
    <label>Landing pages &mdash; read for facts only</label>
    {src_rows}
    <label>Add a landing page</label>
    <div class="conn-site">
      <span class="src-cell"><input name="add_label"
             placeholder="what this page is"></span>
      <span class="src-cell"><input name="add_url"
             placeholder="offer.example.com"></span>
      <span class="when">a URL already listed, or the website itself, is
      refused rather than read twice</span>
    </div>
    <div class="row"><button>Save sources</button></div>
  </form>
</div>"""

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
  <p class="mut">Who this account is, how it sounds, and how its email looks —
  positioning and voice feed every draft; the theme is rendered into every
  campaign email once approved. What may be ASSERTED (claims, objections, the
  catalogue) lives on Knowledge.</p>
  {identity}
  {sources_card}
  <div class="card"><div class="head"><h2>Live theme</h2></div>{live_body}</div>
  <div class="card"><div class="head"><h2>Proposed</h2></div>{prop_body}{actions}</div>
</div>""")


def _pager(base: str, page: int, total: int, per: int, what: str) -> str:
    """One pager, one vocabulary — "X–Y of N", newer/older — extracted in
    step 4 (the 2b deferral; the Data layer's domain views are its consumer)
    from the Review claims queue's inline version, which stays the wording's
    origin. `base` already carries every other param; this appends `page=`.
    Rendered above AND below a long list by callers, per the 2b contract."""
    pages = max(1, -(-total // per))
    if pages <= 1:
        return ""
    page = max(1, min(page, pages))
    lo = (page - 1) * per + 1
    hi = min(total, page * per)
    return ('<div class="pager"><span class="mut">'
            f'{_esc(what)} {lo}&ndash;{hi} of {total}</span>'
            + (f'<a href="{base}&amp;page={page - 1}">&larr; newer</a>'
               if page > 1 else "")
            + (f'<a href="{base}&amp;page={page + 1}">older &rarr;</a>'
               if page < pages else "")
            + "</div>")


def _remove_control(key: str, tenant: str, kind: str, row_id: str,
                    name: str = "", note: str = "",
                    back_fields: str = "") -> str:
    """The one way to take a row out, wherever it is listed.

    Folded, because removing is rare next to reading, and a delete control
    sitting open beside every row is an invitation. Named, because "Remove"
    alone does not say what happens — nothing here is deleted, and a person who
    believes it was will not trust the undo.
    """
    return f"""
    <details class="sec" style="margin-top:6px">
      <summary class="mut">Remove{(" " + _esc(name)) if name else ""}</summary>
      <p class="mut" style="margin-top:6px">It stops being offered to every
      generator immediately. Nothing is deleted, though putting one back is
      still an API call (/admin/kb_restore with the row id) — no console
      surface lists removed rows yet.
      {_esc(note)}</p>
      <form method="post" action="/admin/kb_remove" class="row">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="tenant" value="{_esc(tenant)}">
        <input type="hidden" name="kind" value="{_esc(kind)}">
        <input type="hidden" name="id" value="{_esc(row_id)}">
        {back_fields}
        <button class="sec">Remove</button>
      </form>
    </details>"""


def _photo_library(tenant: str, key_: str = "", page: int = 0,
                   base: str = "", back_fields: str = "") -> str:
    """Every photograph the creative pipeline is allowed to publish.

    There was nowhere in the console to see this (owner, 2026-08-23). The
    picture grid rendered ONLY the proposed queue, and the number of approved
    ones appeared in a sentence inside `if waiting:` — so an account that had
    worked its queue to empty could not see the library it had just built, or
    even its size. Approving was a decision with no visible consequence.

    Read-only on purpose. Approving and rejecting belong to the queue on
    Review, where the decision is; this is the answer to "what do we have",
    which is a knowledge question and belongs with the rest of what the
    account knows.

    `page` > 0 turns on the Data layer's paged mode (step 4): photograph #61
    stops being unreachable, and the card says how many candidates are still
    WAITING with the decision's address — the rail row the spec asked for.
    Knowledge's call stays parameterless and renders exactly as before until
    step 6 retires it.
    """
    from . import kb as kbm
    shots = [a for a in kbm.assets(tenant, publishable_only=True, kind="image")
             if (a.subject or "") != kbm.LOGO]
    marks = kbm.logos(tenant)
    names = {e.key: e.name for e in kbm.entities(tenant, available_only=False)}

    def _tile(a) -> str:
        # WHAT IT IS OF, and WHETHER IT HAS EARNED ANYTHING. Both are on the
        # row and neither was rendered anywhere: `entity_key` is what
        # `coherence.review` checks a hero against, so a library that does not
        # show it cannot be used to answer "why did that email pick this one".
        scope = (names.get(a.entity_key or "", a.entity_key or "")
                 or "brand-wide")
        used = int(a.uses or "0")
        when = (db.as_utc(a.last_used_at).strftime("%b %d")
                if a.last_used_at else "")
        # The one CONTROL in an otherwise read-only library. Approving a
        # photograph grants publication, so un-approving it has to live
        # wherever the approved ones are listed — the pending queue on Review
        # cannot reach a row that already left it.
        return (f'<div class="pictile">'
                f'<a class="pic" href="{_esc(a.url)}" target="_blank" '
                f'rel="noopener" title="{_esc(a.title or "")}">'
                f'<img src="{_esc(a.url)}" loading="lazy" alt="">'
                f'<span class="picmeta">{_esc((a.title or "untitled")[:34])}'
                f'</span>'
                f'<span class="picmeta">{_esc(scope[:22])}'
                + (f' &middot; used {used}&times;'
                   + (f" {_esc(when)}" if when else "") if used else "")
                + '</span></a>'
                + _remove_control(key_, tenant, "asset", a.id,
                                  a.title or "this photograph",
                                  back_fields=back_fields)
                + '</div>')

    waiting_chip = ""
    if page:
        with db.SessionLocal() as s:
            from . import provenance as _pv
            n_wait = (s.query(db.KbAsset)
                      .filter(db.KbAsset.tenant == tenant,
                              db.KbAsset.review == _pv.PROPOSED).count())
        if n_wait:
            waiting_chip = (
                f'<span class="chip off">{n_wait} waiting &middot; '
                f'<a href="/admin/ui?tab=content&amp;sub=pictures&amp;'
                f'tenant={_esc(tenant)}'
                + (f'&amp;key={_esc(key_)}' if key_ else "")
                + '">decide on Review</a></span>')

    if not shots and not marks:
        return ('<div class="card"><div class="head">'
                '<h2>Photographs the creative may use</h2>'
                + waiting_chip + '</div>'
                '<p class="mut">Nothing approved yet. Pictures found on the '
                'account&#39;s own site queue up on <b>Review &rarr; '
                'Pictures</b>; approving one there grants use and it appears '
                'here. A picture on a client&#39;s site is a candidate, not a '
                'licence — approve what is genuinely theirs.</p></div>')

    if page:
        pg = max(1, min(page, max(1, -(-len(shots) // 60))))
        shown = shots[(pg - 1) * 60:pg * 60]
        tail = _pager(base, pg, len(shots), 60, "photographs")
    else:
        shown = shots[:60]
        tail = (f'<p class="mut">Showing 60 of {len(shots)}.</p>'
                if len(shots) > 60 else '')

    return f"""
<div class="card">
  <div class="head"><h2>Photographs the creative may use</h2>
    <span class="chip on">{len(shots)} approved</span>
    {f'<span class="chip">{len(marks)} logo(s)</span>' if marks else ''}
    {waiting_chip}</div>
  <p class="mut">Owned and approved, so a generator may publish them — an
  email hero comes from this shelf or the email goes without one. What each is
  OF is shown beneath it, because that is what a hero is checked against;
  brand-wide means it is not tied to one product. Decisions live on
  <b>Review &rarr; Pictures</b>.</p>
  <div class="picgrid">{"".join(_tile(a) for a in shown)}</div>
  {tail}
  {('<h3 style="font-size:.9rem;margin:14px 0 6px">Logos</h3>'
    '<div class="picgrid">' + "".join(_tile(a) for a in marks[:12]) + "</div>"
    + '<p class="mut">Held apart on purpose: the header already carries the '
      'logo, so a brand mark is never chosen as a hero — it would read as a '
      'letterhead.</p>') if marks else ''}
</div>"""


# --- KB row builders, shared by Knowledge and the Data layer's domain views —
# extracted from render_kb's closures in step 4 (the deferred 2b extraction;
# the domain views are the consumer that makes them not-dead-code). Markup is
# byte-identical to what the closures produced: test_kb_ui pins it.

def _claim_expiry_line(r) -> str:
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


def _claim_editor_form(key: str, tenant: str, r, vocab,
                       back_fields: str = "") -> str:
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
            {back_fields}
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
            <label>Who said it — required before a testimonial or
review can be QUOTED</label>
            <input name="attributed_to" value="{_esc(r.attributed_to or '')}"
                   placeholder="the customer's name, as it may appear in print">
            <label>Situations</label>
            <div class="tags">{tagbox}</div>
            <div class="row">
              <button title="Saving re-attests it: verified today, any expiry
date reset to a year from now (a timeless claim stays timeless)">Save</button>
              {exp_btn}
            </div>
          </form>
        </details>"""


def _claim_row(key: str, tenant: str, r, vocab, note: str = "",
               cls: str = "", editable: bool = False,
               back_fields: str = "") -> str:
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
            + f'<div class="when">{_claim_expiry_line(r)}</div>'
            + (f'<div class="when"><b>{_esc(kb.usage_rule(r.proof_type))}</b></div>'
               if kb.usage_rule(r.proof_type or "") else "")
            + (f'<div class="when"><b>{_esc(note)}</b></div>' if note else "")
            + (_claim_editor_form(key, tenant, r, vocab, back_fields)
               if editable else "")
            # A claim has always been rejectable from the REVIEW queue,
            # which an approved claim has already left. Removing one it
            # turns out the brand should not be making meant re-finding it
            # there, where it no longer is.
            + (_remove_control(key, tenant, "claim", r.id, "this claim",
                               back_fields=back_fields)
               if editable else "")
            + "</div>")


def _claim_decide_row(key: str, tenant: str, r, backq: str = "back=kb") -> str:
    """Approve/reject a pending claim from HERE, landing back here.

    The audit's gap 3b: the Knowledge tab listed pending claims with a
    banner pointing at Review — the fact on one page, the control on
    another. Same route the Review tab uses, so a decision lands
    identically whichever surface makes it; `backq` names where the reader
    is, so the decision never costs them their place.
    """
    base = (f'/admin/claim_review?key={_esc(key)}&amp;tenant={_esc(tenant)}'
            f'&amp;ui=1&amp;{backq}&amp;claim_id={_esc(r.id)}&amp;approve=')
    # Labeled buttons, not emoji links: a control says what it does, and
    # ✅/❌ were the only "buttons" in the console whose meaning lived in
    # a glyph (step 2b; the ship queue's pair retired the same day).
    return (f'<div class="row"><a class="btn" href="{base}yes">Approve</a> '
            f'<a class="btn danger" href="{base}no">Reject</a></div>')


def _objection_row(key: str, tenant: str, r, cat: dict,
                   back_fields: str = "") -> str:
    # The scope is the first thing that has to be readable. An answer true
    # of one product and shown as true of the catalogue is not a display
    # bug — it is the system asserting something false about every other
    # thing the account sells.
    if r.entity_key:
        scope = (f'true of <code>{_esc(cat.get(r.entity_key, r.entity_key))}'
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
              {back_fields}
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


def _situation_overlap_card(key: str, tenant: str, overlaps,
                            back_fields: str = "") -> str:
    """The merge-danger card, one builder for both tabs that show it —
    Knowledge (until step 6 retires it) and the Data layer's Situations
    view, where the spec moves it."""
    if not overlaps:
        return ""
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
            {back_fields}
            <button class="sec">Fold into {_esc(o['keep'])}</button>
          </form>
        </div>""" for o in overlaps[:8])
    return f"""
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
          <a href="/admin/vocabulary?key={_esc(key)}&amp;tenant={_esc(tenant)}&amp;model=1">
          <code>/admin/vocabulary?tenant={_esc(tenant)}&amp;model=1</code></a> for the
          pass that can see those.</p>
        </div>"""


def render_kb(key: str, tenant: str = "", err: str = "", msg: str = "",
              sub: str = "", q: str = "", state: str = "",
              page: int = 1) -> str:
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

    # THE FOUR-TAB CONTRACT (owner, 2026-08-27): Knowledge is where the
    # approved knowledge is MANAGED — add, edit, remove, restore — so the
    # paged domain views live here, one per kind, beside the Overview this
    # page has always been. The Data layer explains the same data; Review
    # decides what enters it.
    sub = (sub or "").strip().lower()
    if sub not in DOMAIN_SUBS:
        sub = ""
    counts = _kind_counts(tenant)

    def _sub_href(k: str) -> str:
        return (f"/admin/ui?tab=kb"
                + (f"&amp;sub={k}" if k else "")
                + f"&amp;tenant={_esc(tenant)}"
                + (f"&amp;key={_esc(key)}" if key else ""))

    strip = '<div class="subtabs">' + "".join(
        f'<a class="subtab{" on" if k == sub else ""}" href="{_sub_href(k)}">'
        f'{_esc(label)}'
        + (f'<span class="cnt">{counts[k]}</span>' if k in counts else "")
        + '</a>'
        for k, label in KB_SUBS) + "</div>"

    if sub:
        flash = ((f'<div class="note">{_esc(err)}</div>' if err else "")
                 + (f'<div class="ok">{_esc(msg)}</div>' if msg else ""))
        if flash:
            flash = f'<div class="flash">{flash}</div>'
        return _shell(key, "kb", "Knowledge", tenant=tenant,
                      body=flash + strip
                      + _schema_domain(key, tenant, sub, q, state, page,
                                       tab="kb"),
                      suffix=f"&amp;tenant={tenant}")

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

    def _claim_block(title: str, rows_, empty: str, note: str = "",
                     cls: str = "", open_: bool = False,
                     editable: bool = False, decidable: bool = False) -> str:
        if not rows_:
            return (f'<details class="sec"><summary>{_esc(title)} (0)</summary>'
                    f'<p class="mut" style="margin-top:10px">{_esc(empty)}</p></details>')
        body = "".join(_claim_row(key, tenant, r, vocab, note, cls,
                                  editable=editable)
                       + (_claim_decide_row(key, tenant, r) if decidable
                          else "") for r in rows_)
        return (f'<details class="sec"{" open" if open_ else ""}>'
                f'<summary>{_esc(title)} ({len(rows_)})</summary>'
                f'<div class="thread">{body}</div></details>')

    claims_html = (
        _claim_block("Claims — selectable", inv["selectable"],
                     "No usable proof. Any draft that needs a number is blocked.",
                     editable=True)
        + _claim_block("Claims — awaiting review", inv["pending"],
                       "Nothing submitted for review.",
                       "not selectable until approved", "gone",
                       decidable=True)
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
        + _remove_control(key, tenant, "audience", r.id, r.name or r.key)
        for r in kb.audiences(tenant)],
        "No segments. Selection cannot narrow to a buyer.")

    # `any_entity` because this page's job is to show what the account knows,
    # not what selection would pick. Without it the list was the brand-wide
    # subset presented as the whole, and every product-scoped answer was
    # invisible here.
    # Situations doing one job. Reported here rather than merged anywhere,
    # because a merge rewrites what every claim under both tags can answer.
    over_html = _situation_overlap_card(key, tenant,
                                        kb.situation_overlaps(tenant))

    obj_rows = kb.objections(tenant, any_entity=True)
    obj_cat = {e.key: e.name for e in kb.entities(tenant, available_only=False)}

    # Objections stand alone — they used to share a block with the situation-
    # merge warnings, which is how "claims vs objections" stopped reading as
    # two different things (owner, 2026-08-21). The merge card now lives with
    # the situations it is about.
    obj_html = _kb_list("All objections",
                        [_objection_row(key, tenant, r, obj_cat)
                         + _remove_control(key, tenant, "objection",
                                           r.id, "this answer")
                         for r in obj_rows],
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
        + _remove_control(key, tenant, "entity", r.id, r.name,
                          "Anything scoped only to it — its claims, its "
                          "objections, its photographs — comes out with it, "
                          "because a claim about a catalogue row that no "
                          "longer exists cannot even be edited.")
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
            + "</div>"
            + _remove_control(key, tenant, "situation", r.id, r.tag,
                              "Claims already tagged with it keep the tag, but "
                              "no new claim may carry it.")
            + "</div>" for r in sits)
        sit_note = (f'<p class="mut">These {len(sits)} tags are the only ones a claim '
                    f'for {_esc(t.name)} may carry. A claim tagged with anything else '
                    f'is refused on the way in.</p>')
    else:
        sit_body = ""
        sit_note = ('<div class="note">No vocabulary authored, so this account '
                    'silently inherits the agency\'s B2B language — which no venue '
                    'or product enquiry will ever match. Claims tagged in this '
                    'account\'s own words will be refused until tags exist '
                    'here — add the first one below.</div>')

    # The warning above dead-ended for as long as it has existed: no console
    # control could author a tag (seed_kb.py and the model pass were the only
    # writers). The form is on the card that states the fact.
    sit_note += f"""
    <form method="get" action="/admin/situation_add" class="row">
      <input type="hidden" name="key" value="{_esc(key)}">
      <input type="hidden" name="tenant" value="{_esc(tenant)}">
      <input name="tag" size="22" placeholder="planning_a_wedding">
      <input name="description" size="34" placeholder="what a buyer in it is trying to do">
      <button type="submit" class="sec">Add situation</button>
    </form>"""

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
            f'sub=claims&amp;tenant={_esc(tenant)}#proposals">'
            f'Open the review queue →</a></p>'
            f'</div>')

    # The substance, one clearly-named card per kind (owner, 2026-08-21: one
    # "What is in there" card mixing claims, audiences, objections and the
    # catalogue read as a single undifferentiated pile). Identity detail rides
    # folded under the stat strip — state first, prose on request.
    return _shell(key, "kb", "Knowledge", tenant=tenant, body=f"""
{warn}
{strip}
<div>
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

{_photo_library(tenant, key)}
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


def _compliance_body(tenant: str) -> str:
    """The live-site compliance readout, as HTML.

    Extracted 2026-08-23 so it can live on Assurance instead of Review.
    Compliance is a FINDING ABOUT WHAT ALREADY SHIPPED, which is what the
    Assurance tab is for; Review is a queue of decisions waiting on a
    person. Mixing the two made Review a place you scrolled past your own
    work to read a report (owner, 2026-08-23).
    """
    from . import compliance
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
    return comp


#: The Review tab's own sections, as sub-tabs. Seven cards stacked in one
#: scroll is what the owner met (2026-08-23: "endless scrolls") — and the
#: picture queue was buried INSIDE the claims card, which is part of why
#: nobody noticed its buttons were dead. Each of these is a different DECISION,
#: made by a different person on a different day; they are not chapters of one
#: document.
#:
#: Every entry carries its own count, so the tab strip says where the work is
#: without opening anything — the point of splitting is lost if you have to
#: visit six tabs to find the one with something in it.
# "ship" FIRST: the strip's order is the day's order, and "may this go out"
# outranks "is this true" — a wrong claim waits safely in the KB, a wrong
# send does not. Until 2026-08-26 approvals had NO section here at all: the
# tab named Review reviewed everything except the thing most people mean by
# the word, and the real queue lived on the unstyled /admin/pending fallback.
REVIEW_SUBS = (("ship", "May it ship?"), ("claims", "Claims"),
               ("pictures", "Pictures"),
               ("other", "Everything else"), ("plans", "Plans"),
               ("conflicts", "Conflicts"),
               # Renamed from "Catalogue" (step 4, spec §4): this is a
               # sync-and-flags panel, not the catalogue — the catalogue
               # itself is managed on Knowledge — and the old name collided
               # with that card. The KEY stays `catalogue`: URLs never break.
               ("catalogue", "Store sync"))


def _read_off(srcs: list[dict], source_text: str) -> str:
    """Which of this account's sites a finding was read off, by its own name.

    Derived from the URL already recorded in the finding's `source` rather
    than stored beside it — the URL IS the record of where it came from (rule
    8: every fact stated once), and a second copy would go stale the moment a
    landing page is relabelled. An unrecognised host answers with the host,
    which is the honest answer for a claim harvested before that source was
    named.

    Takes the ALREADY-LOADED source list rather than a tenant key: called per
    card, the key form reloaded the tenant row for every claim on the page
    (twice each, once to ask and once to answer), so a full queue cost thirty
    lookups to render one line. Amended the day it shipped.
    """
    m = _re.search(r"https?://[^\s\"'<>]+", source_text or "")
    if not m:
        return ""
    from .connections import norm_domain
    host = norm_domain(m.group(0))
    for src in srcs:
        if norm_domain(src["url"]) == host:
            return src["label"]
    return host


def _sources_block(key: str, tenant: str) -> str:
    """The three feeders and what they last did — at the TOP (spec §4).

    The queue-filling actions used to sit below the fifteen cards they
    feed, and the BG status lines rendered as loose banner rows. One
    compact card now: each source with its last-ran state (failed loud,
    running plain, finished with its own summary) and its button beside
    it — controls lead.
    """
    from .web import bg_status
    has_store = bool(tenants.capabilities(tenant).get("commerce"))
    acts = {"harvest": ("/admin/harvest", "Run harvest", {"apply": "1"},
                        "reads the site, files proposals"),
            "email": ("/admin/email_harvest", "Mine sent mail", {"ui": "1"},
                      "reads what this account already SAID"),
            # No store, no button — same rule as the Store sync section: a
            # control that can only fail teaches distrust of every control.
            "sync": (("/admin/catalog_sync", "Sync store", {},
                      "names, prices, live stock") if has_store else
                     ("", "", {}, "parked — no store connected")),
            "scan": ("/admin/compliance_scan", "Scan site", {"ui": "1"},
                     "checks live pages against the ban list")}
    rows = ""
    for label, name in BG_LABELS:
        st = bg_status(label, tenant)
        when = _esc((st.get("at") or "")[:16].replace("T", " "))
        if not st:
            state = '<span class="mut">never ran</span>'
        elif st.get("state") == "failed":
            state = (f'<span class="chip off" title="{_esc(st.get("detail", ""))}">'
                     f'failed {when}</span>')
        elif st.get("state") == "running":
            state = f'<span class="chip nb">running · {when}</span>'
        else:
            state = (f'<span class="mut" title="{_esc(st.get("detail", ""))}">'
                     f'ran {when}</span>')
        action, btn, extra, what = acts.get(label, ("", "", {}, ""))
        rows += (f'<div class="conn-site"><span><b>{_esc(name)}</b> '
                 f'<span class="when">{_esc(what)}</span></span> {state} '
                 f'<span class="row">'
                 + (_act(key, action, btn, tenant, extra, small=True)
                    if action else "")
                 + '</span></div>')
    # A failure is the one state that must not hide in a fold.
    fails = "".join(
        f'<div class="note"><strong>{name} failed</strong> — '
        f'{_esc(bg_status(label, tenant).get("detail", ""))}</div>'
        for label, name in BG_LABELS
        if bg_status(label, tenant).get("state") == "failed")
    return f"""
<details class="sec"><summary>Sources — what fills these queues, and when
each last ran</summary>{rows}</details>{fails}"""


def _ship_preview(pl: dict) -> str:
    """The thing being approved, rendered inside the row's fold (spec §4:
    "read the thing you are approving without leaving").

    Artifact-backed kinds render their kept body — a sandboxed iframe for
    HTML, the variant texts for an ad batch; everything else falls back to
    the payload's text, which is what the fold always showed.
    """
    oid = str(pl.get("output_id") or "")
    body = (pl.get("body") or pl.get("content")
            or (pl.get("fields") or {}).get("body_html", ""))
    art = None
    if oid:
        with db.SessionLocal() as s:
            art = (s.query(db.ArtifactBody)
                   .filter(db.ArtifactBody.output_id == oid).first())
            if art is None:
                art = (s.query(db.ArtifactBody)
                       .filter(db.ArtifactBody.format == "ad_batch",
                               db.ArtifactBody.body.like(f'%"{oid}"%'))
                       .first())
            s.expunge_all()
    if art is not None and (art.format or "") == "ad_batch":
        import json as _json
        try:
            vs = _json.loads(art.body or "").get("variants") or []
            inner = "".join(
                f'<div class="msg{" gone" if v.get("dropped") else ""}">'
                f'{_esc(str(v.get("text") or ""))}</div>' for v in vs)
            return (f'<details><summary>preview — {len(vs)} variant(s)'
                    f'</summary><div class="thread">{inner}</div></details>')
        except Exception:                                        # noqa: BLE001
            pass
    if art is not None and (art.body or "").strip():
        return (f'<details><summary>preview — rendered'
                f'</summary><iframe sandbox="" srcdoc="{_esc(art.body)}" '
                f'style="width:100%;height:380px;border:1px solid '
                f'var(--rule);border-radius:6px;background:#fff"></iframe>'
                f'</details>')
    if body:
        return (f'<details><summary>read it ({len(body)} chars)</summary>'
                f'<pre style="white-space:pre-wrap">{_esc(body[:1500])}'
                + ("…" if len(body) > 1500 else "") + "</pre></details>")
    return ('<div class="mut">this kind carries no text body — the '
            'summary above is the whole decision</div>')


def render_content(key: str, tenant: str = "", started: str = "",
                   err: str = "", msg: str = "", cpage: int = 1,
                   sub: str = "", q: str = "", flt: str = "",
                   corigin: str = "") -> str:
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
    # FILTER, then page (owner, 2026-08-27: "the ability to filter /
    # prioritize the claims"). Chips are the prioritisation — came-due
    # reconfirmations are the quick wins, brand vs scoped is how you batch
    # the judgement — and search narrows by any word on the card. Honest
    # counts: the pager reports the filtered depth, the bar names the
    # unfiltered total. (No date sort is offered: KbClaim carries no
    # created_at, and ordering by a column that does not exist would be a
    # sort by accident.)
    total_unfiltered = len(pending)
    _cf = (flt or "").strip().lower() if sub in ("", "claims") else ""
    if _cf == "due":
        pending = [p for p in pending if p.approved_at]
    elif _cf == "brand":
        pending = [p for p in pending if not (p.entity_key or "")]
    elif _cf == "scoped":
        pending = [p for p in pending if (p.entity_key or "")]
    if corigin:
        pending = [p for p in pending if (p.origin or "") == corigin]
    if q and sub in ("", "claims"):
        pending = [p for p in pending
                   if _match(q, p.claim, p.evidence, p.source, p.entity_key,
                             " ".join(p.situations or []))]

    # A harvest files claims by the dozen, and a hundred full edit-forms on
    # one page is a queue nobody works (owner, 2026-08-21). One page of cards
    # at a time; every decide path carries `cpage` back so a decision returns
    # to THIS page at the next card, never to the top of page one.
    CLAIMS_PAGE = 15
    total_claims = len(pending)
    pages = max(1, -(-total_claims // CLAIMS_PAGE))
    # The REQUESTED page, before the claims clamp narrows it — every other
    # queue pages off this (step 4), and the clamp below rebinds `cpage` to
    # the claims queue's own depth, which silently pinned page 2 of any
    # other queue back to page 1.
    try:
        page_req = max(1, int(cpage or 1))
    except (TypeError, ValueError):
        page_req = 1
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
    # Pager past 60 (spec §4): photograph #61 was unreachable — a 60-cap
    # with no way to turn the page.
    PICS_PAGE = 60
    _pages_p = max(1, -(-len(waiting) // PICS_PAGE))
    _ppage = max(1, min(page_req, _pages_p))
    _pics_shown = waiting[(_ppage - 1) * PICS_PAGE:_ppage * PICS_PAGE]
    _pics_pager = _pager(
        f"/admin/ui?tab=content&amp;sub=pictures&amp;tenant={_esc(tenant)}"
        + (f"&amp;key={_esc(key)}" if key else ""),
        _ppage, len(waiting), PICS_PAGE, "pictures")
    pic_cards = ""
    for a in _pics_shown:
        is_logo = (a.subject or "") == kbm.LOGO
        pic_cards += f"""
        <label class="pic">
          <input type="checkbox" name="asset_ids" value="{_esc(a.id)}" form="picsform">
          <img src="{_esc(a.url)}" loading="lazy" alt="">
          <span class="picmeta">{'&#9679; logo' if is_logo else ''}
            {_esc((a.title or '')[:38])}</span>
        </label>"""
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
      <form id="picsform" method="post" action="/admin/assets_decide"></form>
      <input type="hidden" name="tenant" value="{_esc(tenant)}" form="picsform">
      {_pics_pager}
      <div class="bulkbar">
        <label class="pick"><input type="checkbox" id="allpics"> select all
          {len(_pics_shown)} on this page</label>
        <span class="grow"></span>
        <button form="picsform" name="action" value="reject" class="sec">Reject
          selected</button>
        <button form="picsform" name="action" value="approve_reference" class="sec"
          title="Keep it on file but never publish it — for a picture the
                 client does not own">Reference only</button>
        <button form="picsform" name="action" value="approve"
          title="Approving grants use: the picture becomes selectable as an
                 email hero">Approve selected</button>
      </div>
      <div class="picgrid">{pic_cards}</div>
      {_pics_pager}
      <script>
      document.getElementById('allpics').addEventListener('change', function(e) {{
        document.querySelectorAll('input[name="asset_ids"]')
                .forEach(function(b) {{ b.checked = e.target.checked; }});
      }});
      </script>
    </div>"""
    else:
        # The card renders EMPTY too (spec §4): a crawler-fed queue that
        # vanishes when empty hides that the queue exists at all — and the
        # empty state is where the filling action belongs.
        from .web import bg_status as _bgs
        _hv = _bgs("harvest", tenant)
        _hv_when = _esc((_hv.get("at") or "never")[:16].replace("T", " "))
        pics_html = f"""
    <div class="anchor" id="pics"></div>
    <div class="card">
      <div class="head"><h2>Pictures waiting</h2>
        <span class="chip on">none waiting</span>
        <span class="mut">{len(approved_pics)} approved · {len(marks)} logo(s)</span></div>
      <p class="mut">Nothing waiting — the crawler files what it finds here.
      Last harvest: {_hv_when}.</p>
      <div class="row">{_act(key, "/admin/harvest", "Run harvest", tenant, {"apply": "1"})}
        <span class="mut">reads the site; candidates land here for your
        decision</span></div>
    </div>"""

    assets_form = pics_html + f"""
    <div class="card">
      <div class="head"><h2>Creative library</h2></div>
      <p class="mut">Photographs the creative pipeline may use.
      <b>Owned</b> is the client&#39;s to publish; <b>reference</b> is
      inspiration only and can never leave the building. What it depicts is
      guessed from the file — a cutout is an object, anything else is treated
      as a scene.</p>
      <details class="sec"><summary>Add a photograph by URL</summary>
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
        <input name="entity_key" list="ents" placeholder="leave blank for brand-wide">
        <div class="row"><button>Add to library</button></div>
      </form>
      </details>
      {catlist}
    </div>"""

    # Named only when there is more than one site to tell apart: on a
    # single-domain account "read off Website" on every card is a fact stated
    # once too often (rule 8), and the whole point of the declutter was that
    # the card leads with the decision.
    _srcs = tenants.content_sources(tenant)
    _many_sites = len(_srcs) > 1

    if pending:
        def _card(p) -> str:
            chosen = set(p.situations or [])
            _site_of = _read_off(_srcs, p.source or "") if _many_sites else ""
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
            # THE ESSENTIALS LEAD (owner, 2026-08-27: "the claim cards
            # are too busy — the metadata should be at the bottom on toggle
            # only"): claim, evidence, scope, situations, duplicates and
            # the buttons. Everything about WHERE it came from and HOW to
            # read it — source, found-next-to context, the proves field —
            # folds under one Details toggle at the bottom of the card.
            return f"""
            <div class="anchor" id="c-{_esc(p.id)}"></div>
            <label class="pick"><input type="checkbox" name="claim_ids"
                   value="{_esc(p.id)}" form="bulk"> select</label>
            <form class="f" method="post" action="/admin/claim_edit">
              <input type="hidden" name="claim_id" value="{_esc(p.id)}">
              <input type="hidden" name="tenant" value="{_esc(tenant)}">
              <input type="hidden" name="next_id" value="{_esc(_next_of(p.id))}">
              <input type="hidden" name="cpage" value="{cpage}">
              {_keep_fields}
              <label>{"Quoted — a customer's own words"
                      if verbatim else "Claim"}</label>
              <textarea name="claim" rows="2"{" readonly" if verbatim else ""
                        }>{_esc(p.claim)}</textarea>
              {rule if verbatim else ""}
              <label>{"Attribution" if verbatim
                      else "Evidence — the number or the proof"}</label>
              <input name="evidence" value="{_esc(p.evidence or '')}"
                     placeholder="what makes this checkable">
              <label>True of &mdash; blank means the whole brand</label>
              <input name="entity_key" list="ents" value="{_esc(p.entity_key or '')}"
                     placeholder="brand-level (used in any content)">
              <div class="when">{
                  "Scoped to " + _esc(dict(cat).get(p.entity_key, p.entity_key))
                  if p.entity_key else "Brand-level"
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
              <details class="sec"><summary class="mut">Details — where it
              was found, what it proves</summary>
                <div class="when">{_esc(p.proof_type or '')} · {_esc(p.source or 'source not recorded')}
                · from {_esc(p.origin or 'unknown')}{
                  (" · read off " + _esc(_site_of))
                  if (_many_sites and _site_of) else ""}</div>
                {(f'<label>Found next to &mdash; copied from the page</label>'
                  f'<div class="when">&ldquo;{_esc(getattr(p, "context", ""))}&rdquo;</div>')
                 if getattr(p, "context", "") else ""}
                <label>What it proves &mdash; written by the model, not the site</label>
                <textarea name="proves" rows="2"
                  placeholder="what a reader should conclude from this">{_esc(getattr(p, 'proves', '') or '')}</textarea>
                {rule if (not verbatim and rule) else ""}
              </details>
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
        from urllib.parse import quote as _q_

        def _fq(extra_flt: str = "", extra_origin: str = "") -> str:
            s = ""
            if q:
                s += f"&amp;q={_esc(_q_(q, safe=''))}"
            fv = extra_flt if extra_flt != "\x00" else _cf
            ov = extra_origin if extra_origin != "\x00" else corigin
            if fv:
                s += f"&amp;flt={_esc(fv)}"
            if ov:
                s += f"&amp;corigin={_esc(ov)}"
            return s

        def _pg(p: int) -> str:
            return (f"/admin/ui?tab=content&amp;sub=claims"
                    f"&amp;tenant={_esc(tenant)}&amp;cpage={p}"
                    + _fq("\x00", "\x00") + "#proposals")
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
        _chip_defs = (("", "all"), ("due", "came due"), ("brand", "brand-level"),
                      ("scoped", "product-scoped"))
        _origins = sorted({(p.origin or "") for p in
                           (e["row"] for e in base) if (p.origin or "")})
        _chips_html = '<div class="filters">' + "".join(
            f'<a class="{"on" if _cf == v else ""}" '
            f'href="/admin/ui?tab=content&amp;sub=claims&amp;tenant={_esc(tenant)}'
            + _fq(v, "\x00") + f'#proposals">{label}</a>'
            for v, label in _chip_defs) + "</div>"
        _osel = "".join(
            f'<option value="{_esc(o)}"{" selected" if o == corigin else ""}>'
            f'{_esc(o)}</option>' for o in _origins)
        filter_bar = f"""
        <div class="row">
          {_chips_html}
          <form method="get" action="/admin/ui" class="row" style="flex:1">
            <input type="hidden" name="tab" value="content">
            <input type="hidden" name="sub" value="claims">
            <input type="hidden" name="tenant" value="{_esc(tenant)}">
            {f'<input type="hidden" name="key" value="{_esc(key)}">' if key else ''}
            {f'<input type="hidden" name="flt" value="{_esc(_cf)}">' if _cf else ''}
            <input name="q" value="{_esc(q)}" placeholder="search claims, evidence, source"
                   style="flex:1;min-width:180px">
            <select name="corigin" style="width:auto">
              <option value="">any origin</option>{_osel}</select>
            <button class="sec">Filter</button>
            {f'<a class="mut" href="/admin/ui?tab=content&amp;sub=claims&amp;tenant={_esc(tenant)}#proposals">clear</a>' if (q or _cf or corigin) else ''}
          </form>
        </div>
        {f'<div class="when">showing {total_claims} of {total_unfiltered} pending (filtered)</div>' if (q or _cf or corigin) else ''}"""
        _keep_fields = (
            (f'<input type="hidden" name="q" value="{_esc(q)}">' if q else "")
            + (f'<input type="hidden" name="flt" value="{_esc(_cf)}">' if _cf else "")
            + (f'<input type="hidden" name="corigin" value="{_esc(corigin)}">'
               if corigin else ""))
        bulk = f"""
        <form id="bulk" method="post" action="/admin/claims_decide"></form>
        <input type="hidden" name="tenant" value="{_esc(tenant)}" form="bulk">
        <input type="hidden" name="cpage" value="{cpage}" form="bulk">
        {"".join(f.replace('">', '" form="bulk">', 1) for f in ([
            f'<input type="hidden" name="q" value="{_esc(q)}">'] if q else []))}
        {"".join(f.replace('">', '" form="bulk">', 1) for f in ([
            f'<input type="hidden" name="flt" value="{_esc(_cf)}">'] if _cf else []))}
        {"".join(f.replace('">', '" form="bulk">', 1) for f in ([
            f'<input type="hidden" name="corigin" value="{_esc(corigin)}">'] if corigin else []))}
        {filter_bar}
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
        # `assets_form` USED to be concatenated here, so the picture queue
        # rendered inside the claims card — which is how a queue with dead
        # buttons went unnoticed for weeks: nobody scrolled past 15 claim
        # cards to reach it. It is its own section now.
        # The prose that repeated on every card reads ONCE here (spec §4:
        # "collapse into one legend fold above the queue" — it rendered
        # fifteen times per page).
        legend = """
        <details class="sec"><summary>How to read these cards</summary>
          <p class="mut"><b>What it proves</b> is the one field the model
          WROTE rather than copied — read it: a wrong reading of a true
          number is invisible once approved, and it is what a drafter
          reaches for when deciding how to use the claim. Empty means no
          model read the page. <b>True of</b> scopes the claim: blank is
          brand-level, usable in any content; a named item means it only
          ever appears in content about that. <b>Quoted</b> rows are a
          customer's own words — the wording is the evidence and cannot be
          reworded. An untagged claim can never be selected.</p>
        </details>"""
        proposals = (catlist + legend + bulk
                     + '<div class="grid" style="grid-template-columns:1fr">'
                     + "".join(_card(p) for p in shown) + "</div>" + pager)
    else:
        proposals = ('<p class="mut">Nothing waiting. Harvest reads the account\'s '
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
        _pages_c = max(1, -(-len(open_conflicts) // 15))
        _kpage = max(1, min(page_req, _pages_c))
        _conf_pager = _pager(
            f"/admin/ui?tab=content&amp;sub=conflicts&amp;tenant={_esc(tenant)}"
            + (f"&amp;key={_esc(key)}" if key else ""),
            _kpage, len(open_conflicts), 15, "conflicts")
        conflicts_html = (_conf_pager
                          + '<div class="grid" style="grid-template-columns:1fr">'
                          + "".join(_conflict(c) for c in
                                    open_conflicts[(_kpage - 1) * 15:_kpage * 15])
                          + "</div>" + _conf_pager)
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
                # The datalist renders ONCE for the section (spec §4) — it
                # was rebuilt inside every objection card.
                scope = f"""
              <label>True of &mdash; which item is this answer about?</label>
              <input name="entity_key" list="pents"
                     value="{_esc(getattr(r, 'entity_key', '') or '')}"
                     placeholder="start typing a product name">
              <label class="row" style="gap:6px">
                <input type="checkbox" name="brand_wide" value="1">
                <span>No item &mdash; this is true of everything they sell</span>
              </label>"""
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
        _flat = [(k, i) for k, items in other.items() for i in items]
        _okinds = sorted(other)
        _of = (flt or "").strip().lower() if sub == "other" else ""
        if _of in _okinds:
            _flat = [(k, i) for k, i in _flat if k == _of]
        if q and sub == "other":
            _flat = [(k, i) for k, i in _flat
                     if _match(q, getattr(i["row"], "name", ""),
                               getattr(i["row"], "objection", ""),
                               getattr(i["row"], "response", ""),
                               getattr(i["row"], "tag", ""),
                               getattr(i["row"], "description", ""))]
        _pages_o = max(1, -(-len(_flat) // 15))
        _opage = max(1, min(page_req, _pages_o))
        _oth_pager = _pager(
            f"/admin/ui?tab=content&amp;sub=other&amp;tenant={_esc(tenant)}"
            + (f"&amp;key={_esc(key)}" if key else ""),
            _opage, len(_flat), 15, "proposals")
        _pents_opts = "".join(
            f'<option value="{_esc(e.key)}">{_esc(e.name)}</option>'
            for e in kbm.entities(tenant, available_only=False))
        from urllib.parse import quote as _oq
        _oth_chips = '<div class="filters">' + "".join(
            f'<a class="{"on" if _of == v else ""}" '
            f'href="/admin/ui?tab=content&amp;sub=other&amp;tenant={_esc(tenant)}'
            + (f"&amp;q={_esc(_oq(q, safe=''))}" if q else "")
            + (f"&amp;flt={_esc(v)}" if v else "") + f'">{_esc(label)}</a>'
            for v, label in ([("", "all")]
                             + [(k, k + "s") for k in _okinds])) + "</div>"
        _oth_search = f"""
    <form method="get" action="/admin/ui" class="row" style="flex:1">
      <input type="hidden" name="tab" value="content">
      <input type="hidden" name="sub" value="other">
      <input type="hidden" name="tenant" value="{_esc(tenant)}">
      {f'<input type="hidden" name="key" value="{_esc(key)}">' if key else ''}
      {f'<input type="hidden" name="flt" value="{_esc(_of)}">' if _of else ''}
      <input name="q" value="{_esc(q)}" placeholder="search proposals"
             style="flex:1;min-width:160px">
      <button class="sec">Search</button>
    </form>"""
        others_html = (
            f'<datalist id="pents">{_pents_opts}</datalist>'
            + f'<div class="row">{_oth_chips}{_oth_search}</div>'
            + (f'<div class="when">showing {len(_flat)} of {n_other} '
               f'(filtered)</div>' if (q and sub == "other") or _of else '')
            + '<details class="sec"><summary>How scope works</summary>'
              '<p class="mut">An objection needs one of the two: a named '
              'item, or the brand-wide box. An answer approved with neither '
              'is claimed of the whole catalogue &mdash; &ldquo;dishwasher '
              'safe&rdquo; read off one product page becomes a promise '
              'about the porcelain too.</p></details>'
            + _oth_pager
            + '<div class="grid" style="grid-template-columns:1fr">'
            + "".join(_prop(k, i) for k, i in
                      _flat[(_opage - 1) * 15:_opage * 15])
            + "</div>" + _oth_pager)
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

    # The per-source status lines live in the Sources block now (spec §4)
    # — one place, with each source's action beside its state. A RUNNING
    # source still announces itself here so "refresh in a moment" is
    # visible without opening the fold.
    from .web import bg_status
    for label, name in BG_LABELS:
        st = bg_status(label, tenant)
        if st.get("state") == "running":
            banner += (f'<div class="ok">{name} is running. '
                       f'Refresh in a moment.</div>')

    if err:
        banner = f'<div class="note">{_esc(err)}</div>' + banner
    if msg:
        # A bulk decision reports what it did, including what it refused —
        # AS THE FLASH (spec §4): it rendered in muted .when grey, the least
        # important text on the page, above the styled flash it belonged in.
        banner = f'<div class="ok">{_esc(msg)}</div>' + banner

    # --- plans waiting on a person, across systems -------------------------
    # One kind of thing per card: a PLAN is queued work that cannot run until
    # the owner completes or approves it — different from a proposal (which
    # asks "is this true") and from an approval (which asks "may this ship").
    # Each row links into the system's own workflow view, at the card itself.
    plans_wait = systems.plans_needing_action(tenant)
    plans_card = ""
    if plans_wait:
        _pages_pl = max(1, -(-len(plans_wait) // 15))
        _plpage = max(1, min(page_req, _pages_pl))
        _pl_pager = _pager(
            f"/admin/ui?tab=content&amp;sub=plans&amp;tenant={_esc(tenant)}"
            + (f"&amp;key={_esc(key)}" if key else ""),
            _plpage, len(plans_wait), 15, "plans")

        def _plan_row(w) -> str:
            jump = (f'<a href="/admin/ui?key={_esc(key)}&amp;tab=systems&amp;'
                    f'tenant={_esc(tenant)}&amp;system={_esc(w["system_key"])}'
                    f'&amp;ppage={systems.plan_page(tenant, w["system_key"], w["run_id"])}'
                    f'#plan-{_esc(w["run_id"])}">')
            if w["need"] == "complete":
                # A missing field is filled on the workflow card, where the
                # plan's own form is — the jump stays.
                ctl = f'{jump}complete it &rarr;</a>'
            else:
                # DECIDED IN PLACE (spec §4): the routes have carried
                # back-to-place since the pointer sweep; the Review queue
                # now uses them instead of sending the reader to another
                # tab to click the same two buttons.
                base = (f'<input type="hidden" name="key" value="{_esc(key)}">'
                        f'<input type="hidden" name="tenant" value="{_esc(tenant)}">'
                        f'<input type="hidden" name="system" value="{_esc(w["system_key"])}">'
                        f'<input type="hidden" name="id" value="{_esc(w["run_id"])}">'
                        f'<input type="hidden" name="back" value="content">')
                ctl = (f'<form method="get" action="/admin/plan_approve" '
                       f'class="inl">{base}<button class="sec">Approve — '
                       f'runs on its date</button></form> '
                       f'<form method="get" action="/admin/plan_skip" '
                       f'class="inl">{base}'
                       f'<input name="reason" placeholder="why not (kept on the record)" size="22">'
                       f'<button class="sec">Skip</button></form> '
                       f'{jump}open its plan &rarr;</a>')
            return (f'<div class="msg"><div><b>{_esc(w["system_name"])}</b> ·'
                    f' {_esc(w["ref"])}'
                    + (" · " + _esc(w["planned_for"]) if w["planned_for"] else "")
                    + f' — {"needs completing: " if w["need"] == "complete" else ""}'
                    f'{_esc(w["detail"])}</div>'
                    f'<div class="row">{ctl}</div></div>')

        prows = "".join(_plan_row(w) for w in
                        plans_wait[(_plpage - 1) * 15:_plpage * 15])
        plans_card = f"""
<div class="anchor" id="plans"></div>
<div class="card">
  <div class="head"><h2>Plans awaiting you</h2>
    <span class="chip off">{len(plans_wait)} held</span></div>
  <p class="mut">Queued work that cannot run yet — a plan missing a field, or
  one that is complete and needs your go-ahead on this rung. Nothing here
  fails while it waits; it just waits. Approving and skipping happen here;
  completing a field happens on the plan itself.</p>
  {_pl_pager}
  <div class="thread">{prows}</div>
  {_pl_pager}
</div>"""
    # --- approvals: may this ship? -----------------------------------------
    #
    # Scoped to THIS account, like everything on the frame — an approval from
    # another client rendered here is the pooled-page leak all over again.
    from . import approvals as _apm
    with db.SessionLocal() as _s:
        _q = (_s.query(db.Approval)
              .filter(db.Approval.status == "pending"))
        if tenant != ALL:
            _q = _q.filter(db.Approval.tenant == tenant)
        ship_rows = _q.order_by(db.Approval.created_at.desc()).all()
        _s.expunge_all()
    # THE SEND IS THE APPROVAL (owner, 2026-08-27): a drafted reply is not a
    # decision this page collects. The draft is sitting in the client's own
    # mailbox; the person answers the customer from there, and pressing send
    # IS the approval. `approvals.reconcile_drafts` notices it went, closes
    # the row, and records what changed between the draft and the letter —
    # which is the lesson, and the reason the row is not simply deleted.
    #
    # Only replies with a draft BEHIND them leave. A `send_email` approval
    # with no `draft_id` (an RFQ, an invoice reminder, a shipment follow-up)
    # exists nowhere but here, so approving here is the only way it can ever
    # go out — dropping those would silently strand them.
    ship_rows = [a for a in ship_rows if _apm.decided_in_console(a)]

    def _ship_row(a) -> str:
        pl = a.payload or {}
        review = ""
        if a.kind == "seo_new_article" and pl.get("output_id"):
            review = (f' <a href="/admin/article/{_esc(pl["output_id"])}'
                      f'?key={_esc(key)}">review &amp; edit &rarr;</a>')
        elif (a.kind == "skill_output" and pl.get("output_id")
              and pl.get("skill") in ("campaign_email", "ad_copy")):
            # The artifact-backed kinds get their workroom behind the row —
            # a campaign to its preview, an ad variant to the batch board it
            # belongs to (the workroom route resolves a variant id to its
            # board). Replies stay bare: their artifact IS the Gmail draft.
            _what = ("review on its board" if pl.get("skill") == "ad_copy"
                     else "open workroom")
            review = (f' <a href="/admin/work/{_esc(pl["output_id"])}'
                      f'?key={_esc(key)}">{_what} &rarr;</a>')
        # APPROVE STATES ITS CONSEQUENCE (spec §4) — the sweep already made
        # each summary's wording honest; the button now says what approving
        # DOES, per kind, instead of one word meaning five things.
        prov = (pl.get("esp_push") or {}).get("provider", "")
        if prov:
            says = f"Approve — pushes the draft to {_esc(prov)}"
        elif a.kind == "seo_new_article":
            says = "Approve &amp; publish"
        elif a.kind == "send_email":
            says = "Approve — sends it"
        elif a.kind == "skill_output":
            says = "Approve — marks it reviewed, ready"
        else:
            says = "Approve"

        def _btn(verdict: str, label: str, cls: str = "") -> str:
            # POSTs back INTO the console with the executor's own sentence
            # as the flash — the signed /decide links stay the EMAIL
            # mechanism only; the console's primary control no longer exits
            # to an unstyled page with no way back.
            return (f'<form method="post" action="/admin/ship_decide" '
                    f'class="inl"><input type="hidden" name="key" '
                    f'value="{_esc(key)}">'
                    f'<input type="hidden" name="tenant" value="{_esc(tenant)}">'
                    f'<input type="hidden" name="approval_id" value="{_esc(a.id)}">'
                    f'<input type="hidden" name="page" value="{_page}">'
                    + (f'<input type="hidden" name="q" value="{_esc(q)}">'
                       if q else "")
                    + (f'<input type="hidden" name="flt" value="{_esc(_sf)}">'
                       if _sf else "")
                    + f'<input type="hidden" name="verdict" value="{verdict}">'
                    f'<button{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>'
                    f'{label}</button></form>')
        return f"""
        <div class="msg"><div><b>{_esc(a.summary or a.kind)}</b></div>
          {_ship_preview(pl)}
          <div class="row">
            {_btn("approved", says)}
            {_btn("denied", "Deny", "sec")}
            <span class="when">{a.created_at:%b %d, %H:%M}{review}</span>
          </div>
        </div>"""

    # FILTERABLE (owner, 2026-08-27, extended from the claims queue): a
    # kind chip narrows to campaigns / articles / replies / ads, and the
    # search box matches the summary — spec §4 named "no filter" among the
    # primary queue's defects.
    def _ship_kind(a) -> str:
        pl = a.payload or {}
        if (pl.get("esp_push") or {}).get("provider"):
            return "campaign"
        if a.kind == "seo_new_article":
            return "article"
        if a.kind == "send_email":
            # What is left of this kind after drafted replies leave: mail
            # that exists nowhere but this queue. "replies" was the old name
            # and stays an accepted `flt=` value so a bookmark still works.
            return "email"
        if a.kind == "skill_output" and pl.get("skill") == "ad_copy":
            return "ad"
        return "other"

    total_ship = len(ship_rows)
    _sf = (flt or "").strip().lower() if sub == "ship" or not sub else ""
    if _sf == "reply":
        _sf = "email"      # 2026-08-27: renamed when drafted replies left
    if _sf in ("campaign", "article", "email", "ad"):
        ship_rows = [a for a in ship_rows if _ship_kind(a) == _sf]
    if q and (sub == "ship" or not sub):
        ship_rows = [a for a in ship_rows
                     if _match(q, a.summary, a.kind,
                               (a.payload or {}).get("skill"))]

    from urllib.parse import quote as _sq
    _ship_keep = ((f"&amp;q={_esc(_sq(q, safe=''))}" if q else "")
                  + (f"&amp;flt={_esc(_sf)}" if _sf else ""))
    _ship_chips = '<div class="filters">' + "".join(
        f'<a class="{"on" if _sf == v else ""}" '
        f'href="/admin/ui?tab=content&amp;sub=ship&amp;tenant={_esc(tenant)}'
        + (f"&amp;q={_esc(_sq(q, safe=''))}" if q else "")
        + (f"&amp;flt={v}" if v else "") + f'">{label}</a>'
        for v, label in (("", "all"), ("campaign", "campaigns"),
                         ("article", "articles"), ("email", "emails"),
                         ("ad", "ads"))) + "</div>"
    _ship_search = f"""
    <form method="get" action="/admin/ui" class="row" style="flex:1">
      <input type="hidden" name="tab" value="content">
      <input type="hidden" name="sub" value="ship">
      <input type="hidden" name="tenant" value="{_esc(tenant)}">
      {f'<input type="hidden" name="key" value="{_esc(key)}">' if key else ''}
      {f'<input type="hidden" name="flt" value="{_esc(_sf)}">' if _sf else ''}
      <input name="q" value="{_esc(q)}" placeholder="search the queue"
             style="flex:1;min-width:160px">
      <button class="sec">Search</button>
    </form>"""

    # Paginated at 15 (spec §4): the primary queue rendered "25 rows max
    # with no pager" — a queue whose depth nobody can see stops being
    # worked; it lived at ~200 drafts once.
    SHIP_PAGE = 15
    _pages_s = max(1, -(-len(ship_rows) // SHIP_PAGE))
    _page = max(1, min(page_req, _pages_s))
    _ship_shown = ship_rows[(_page - 1) * SHIP_PAGE:_page * SHIP_PAGE]
    _ship_pager = _pager(
        f"/admin/ui?tab=content&amp;sub=ship&amp;tenant={_esc(tenant)}"
        + (f"&amp;key={_esc(key)}" if key else "") + _ship_keep,
        _page, len(ship_rows), SHIP_PAGE, "decisions")
    ship_card = f"""
<div class="anchor" id="ship"></div>
<div class="card">
  <div class="head"><h2>May it ship?</h2>
    <span class="chip {'off' if ship_rows else 'on'}">{len(ship_rows)} pending</span></div>
  <p class="mut">Everything queued to go OUT — an article to the store, a
  change to live pages, an email that exists nowhere else. Approving executes
  it; nothing leaves without you. The preview in each row is the thing itself.
  <b>Drafted replies are not here</b>: they are waiting in the mailbox, and
  sending one from there is what approves it — what changed between the draft
  and the letter is then recorded as the lesson.</p>
  <div class="row">{_ship_chips}{_ship_search}</div>
  {f'<div class="when">showing {len(ship_rows)} of {total_ship} pending (filtered)</div>' if (q or _sf) else ''}
  {_ship_pager}
  <div class="thread">{"".join(_ship_row(a) for a in _ship_shown)
                       or '<p class="mut">Nothing is waiting to ship.</p>'}</div>
  {_ship_pager}
</div>"""

    # --- the sub-tab strip -------------------------------------------------
    #
    # Counts come from the lists already built above, so the strip costs
    # nothing extra and can be trusted: a tab reading 0 is a tab with nothing
    # in it, not a tab whose count was estimated.
    counts = {"ship": total_ship,
              "claims": total_unfiltered, "pictures": len(waiting),
              "other": n_other, "plans": len(plans_wait),
              "conflicts": len(open_conflicts), "catalogue": len(flagged)}
    sub = (sub or "").strip().lower()
    if sub not in dict(REVIEW_SUBS):
        # LAND ON THE WORK. With no section asked for, open the first one that
        # has something waiting rather than always the first in the list — the
        # tab exists to be worked through, and opening an empty Claims queue
        # when twelve pictures are waiting is the scroll problem again, one
        # click deeper.
        sub = next((k for k, _ in REVIEW_SUBS if counts.get(k)),
                   REVIEW_SUBS[0][0])

    def _sub_href(k: str) -> str:
        return (f"/admin/ui?tab=content&amp;sub={k}&amp;tenant={_esc(tenant)}"
                + (f"&amp;key={_esc(key)}" if key else ""))

    strip = '<div class="subtabs">' + "".join(
        f'<a class="subtab{" on" if k == sub else ""}" href="{_sub_href(k)}">'
        f'{label}<span class="cnt">{counts.get(k, 0)}</span></a>'
        for k, label in REVIEW_SUBS) + "</div>"

    # Order (owner, 2026-08-21): the queues this tab exists for come first —
    # the destructive start-over card used to be the FIRST thing on the page,
    # a rare, dangerous action sitting above the daily work. It now lives
    # folded at the bottom. The heading matches the nav ("Review"): two names
    # for one tab made it read like two places.
    # Each section renders only when it is the one being looked at. That is
    # not only tidiness: the claim similarity pass, the conflict query and the
    # catalogue read all cost real time, and this page was measured at 2.5-4.5s
    # (owner, 2026-08-21: "why does it take so long to load tabs"). Six
    # sections behind one strip means one section's work per render.
    sections = {
        "ship": ship_card,
        "claims": f"""
<div class="anchor" id="proposals"></div>
<div class="card">
  <div class="head"><h2>Claims proposed, awaiting you</h2>
    <span class="chip {'off' if pending else 'on'}">{len(pending)} pending</span></div>
  <p class="mut">Found on {_esc(t.name)}'s own site. Invisible to every generator
  until approved. Anything using a banned phrase was dropped, not queued.</p>
  {proposals}
  {'' if pending else f'<div class="row">{_act(key, "/admin/harvest", "Find proposals", tenant, {"apply": "1"})}{_act(key, "/admin/email_harvest", "Mine sent mail", tenant, {"ui": "1"})}<span class="mut">the feeders — their last-ran state is in Sources above</span></div>'}
  {clear_all}
</div>""",
        "pictures": assets_form,
        "other": f"""
<div class="anchor" id="others"></div>
<div class="card">
  <div class="head"><h2>Everything else awaiting you</h2>
    <span class="chip {'off' if n_other else 'on'}">{n_other} pending</span></div>
  <p class="mut">Buyer segments, objections, catalogue rows and situation tags
  proposed by a client, a spreadsheet or a crawl. Approving one makes it final —
  no machine source can change it afterwards.</p>
  {others_html}
</div>""",
        "plans": plans_card or """
<div class="card">
  <div class="head"><h2>Plans awaiting you</h2></div>
  <p class="mut">Nothing held. Work a system has planned appears here when it
  cannot run yet — a missing field, or a rung that needs your go-ahead.</p>
</div>""",
        "conflicts": f"""
<div class="card">
  <div class="head"><h2>Sources disagree</h2>
    <span class="chip {'off' if open_conflicts else 'on'}">{len(open_conflicts)} open</span></div>
  <p class="mut">Something approved was contradicted by a later crawl, upload or
  store sync. The approved value is still what gets used — nothing was
  overwritten. Pick one and the disagreement closes.</p>
  {conflicts_html}
</div>""",
        "catalogue": f"""
<div class="card">
  <div class="head"><h2>Store sync</h2>
    {'' if has_store else '<span class="chip nb">parked — no store connected</span>'}</div>
  {cat}
  {f'<div class="row">{_act(key, "/admin/catalog_sync", "Sync from store", tenant)}<span class="mut">names, prices and live stock — the store owns those</span></div>'
   if has_store else
   '<p class="mut">The sync button appears once a store is connected on the Connections tab — offering one that can only fail teaches the reader to distrust every button.</p>'}
</div>""",
    }

    # The In-progress strip — the index that makes Save-for-later a real
    # state. Held artifacts were the owner's exact complaint about the old
    # article screen: edits persisted, but persistence with no index is
    # experienced as loss. Guarded like every sidebar fact: a broken strip
    # must never be the thing that breaks the day's tab.
    inprog = ""
    try:
        with db.SessionLocal() as s:
            held = (s.query(db.ArtifactBody)
                    .filter(db.ArtifactBody.tenant == tenant,
                            db.ArtifactBody.state == "in_review")
                    .order_by(db.ArtifactBody.created_at.desc())
                    .limit(8).all())
            s.expunge_all()
        if held:
            links = " · ".join(
                f'<a href="/admin/work/{_esc(a.output_id)}?key={_esc(key)}">'
                f'{_esc(a.system_key or "artifact")} · '
                f'{_esc(str(a.created_at)[:10])}</a>' for a in held)
            inprog = (f'<div class="everynote"><b>In progress</b> — '
                      f'{len(held)} kept to finish: {links}</div>')
    except Exception:                                            # noqa: BLE001
        inprog = ""

    return _shell(key, "content", "Review", tenant=tenant, body=f"""
<div class="flash">{banner}</div>
{inprog}
<div>
  <p class="mut">Decisions waiting on you for this account. Nothing here is
  published — it is the difference between what the brand allows and what is
  live. (Compliance moved to Assurance: a report about pages already published
  is not a decision.)</p>
</div>
{_sources_block(key, tenant)}
{strip}
{sections[sub]}

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
      <input type="hidden" name="ui" value="1">
      <button class="sec">Show me what it would delete</button>
    </form>
    <form method="post" action="/admin/purge_harvested" class="inl"
          onsubmit="return confirm('Delete every crawled and mailed claim and objection for {_esc(tenant)}, approved ones included? The ban list, vocabulary and catalogue are kept.')">
      <input type="hidden" name="tenant" value="{_esc(tenant)}">
      <input type="hidden" name="ui" value="1">
      <button>Clear and re-harvest</button>
    </form>
    <span class="mut">then run Find proposals / Mine sent mail on the
    Claims section</span>
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
                  <div class="how">One-click sign-in is not configured on this
                  install, so there is no Connect button here — this one gets
                  wired together on a call.</div>
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
              <div class="how">This one gets wired together on a call — the
              form for it is not offered here.</div>
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

def _kb_tables() -> list:
    """Every knowledge table, derived — with the written-down prose kept.

    The list below was a literal, and it had drifted: `KbAsset` — the
    photograph library, a whole table of the knowledge base — was not on it, so
    the page whose job is to show the shape of the data did not know the
    pictures existed (owner, 2026-08-23: "the Data Layer tab I believe is
    outdated"). The page's own lede already promised "read from the models, so
    a new column shows up here on its own", which was true of COLUMNS and false
    of TABLES.

    So the models decide membership and the prose stays hand-written, because
    "what this table is FOR" is the one thing introspection cannot produce. A
    table nobody has described yet appears with its name and its columns rather
    than not at all — visible and obviously undocumented, which is the honest
    state and the one that prompts somebody to write the sentence.
    """
    from . import db as _dbm
    described = {name: (headline, why) for name, _t, headline, why in _KB_DESCRIBED}
    out = []
    for model in sorted(_dbm.Base.__subclasses__(), key=lambda m: m.__name__):
        name = model.__name__
        if not name.startswith("Kb"):
            continue
        if not hasattr(model, "tenant"):
            continue
        headline, why = described.get(
            name, (name, "No description written yet. It is listed because it "
                         "is part of the knowledge base — what it is FOR is a "
                         "sentence somebody has to write."))
        out.append((name, model.__tablename__, headline, why))
    # Described tables first, in their authored order: the curated ones are the
    # narrative and the derived ones are the appendix.
    order = {n: i for i, (n, _t, _h, _w) in enumerate(_KB_DESCRIBED)}
    out.sort(key=lambda r: (order.get(r[0], len(order)), r[0]))
    return out


_KB_DESCRIBED = [
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
    ("KbAsset", "kb_assets", "Pictures the creative may publish",
     "`rights` is the gate and has no default: anything that is not exactly "
     "`owned` is inspiration, never inventory. `entity_key` is what a hero "
     "gets checked against, and `uses`/`outcome` are what publishing writes "
     "back. Approved ones are listed on the Knowledge tab."),
    ("KbEmbedding", "kb_embeddings", "The vector index over the rows above",
     "Derived, never authored — it is how near-duplicate proposals and "
     "same-fact-different-tag pairs are found. Removing a row must forget its "
     "vector or the index drifts away from the knowledge base."),
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


#: Where each `readiness` blocker is actually fixed. `resolve.readiness` already
#: names a destination in prose — "Knowledge tab", "Content tab" — and prose is
#: not a link. This is the same "act where you report" line the Systems check
#: draws, one page over.
_READINESS_WHERE = {
    "knowledge tab": ("kb", "Knowledge"),
    # `sub=claims`: the fix these buttons carry is "claims waiting review",
    # and Review's default section is May-it-ship whenever approvals are
    # pending — the click landed beside the queue it named.
    "content tab": ("content&amp;sub=claims", "Review"),
    "brand tab": ("brand", "Brand"),
    "connections": ("accounts", "Connections"),
}


def _fix_list(key: str, tenant: str) -> str:
    """What to fix, in the order that unblocks the most.

    `resolve.readiness()` has always returned this list, already ranked by how
    many situations each fix releases and already naming where it lives — and
    it was rendered NOWHERE. Two callers existed: a dossier and a JSON route.
    So the console had a ranked, account-specific work list and showed the
    operator a wall of row counts instead (owner, 2026-08-23: the Data layer
    tab "doesnt allow us to fix data layer issues from there, we have to
    navigate to the places where the data layer tells us needs attention").

    The counts stay — the shape of the data is what this page is for. They just
    stop being the first thing, and the thing above them is clickable.
    """
    from . import resolve as _rs
    r = _rs.readiness(tenant)
    acts = r.get("next_actions") or []

    def _link(where: str) -> str:
        tab, label = _READINESS_WHERE.get(str(where or "").strip().lower(),
                                          ("", ""))
        if not tab:
            # Telegram and intake links are real destinations that are not
            # tabs. Naming them plainly beats inventing a link that goes
            # somewhere else.
            return f'<span class="mut">{_esc(where)}</span>'
        return (f'<a class="btn sec" href="/admin/ui?tab={tab}'
                f'&amp;tenant={_esc(tenant)}'
                + (f'&amp;key={_esc(key)}' if key else "")
                + f'">{label} &rarr;</a>')

    if not acts:
        body = (f'<p class="mut">Nothing is blocking this account. It can '
                f'answer {r.get("answerable", 0)} of {r.get("situations", 0)} '
                f'situations, {r.get("proven", 0)} of them with proof '
                f'attached.</p>')
    else:
        body = "".join(
            '<div class="msg">'
            f'<div><strong>{_esc(a.get("fix", ""))}</strong></div>'
            f'<div class="when">unblocks {_esc(str(a.get("unblocks", "")))}'
            + (f' · {a.get("situations", 0)} situation(s)'
               if a.get("situations") else "")
            + '</div>'
            f'<div class="row">{_link(a.get("where", ""))}</div>'
            "</div>" for a in acts[:6])

    return f"""
<div class="card">
  <div class="head"><h2>What to fix, in order</h2>
    <span class="chip {'off' if acts else 'on'}">{_esc(r.get("score", ""))}
      situations answerable</span></div>
  <p class="mut">Ranked by how many situations each one releases, not by how
  quick it is. {_esc(r.get("verdict", ""))}</p>
  <div class="thread">{body}</div>
</div>"""


def _schema_advanced(key: str, tenant: str) -> str:
    """The schema reference — today's Data layer page, as the Advanced view.

    Honest about being reference: the shape of the data, not a queue. The
    fill bars used to be computed by loading EVERY ROW of EVERY KB table per
    page view (spec §5 named it); they are aggregate queries now — one per
    table for the bars, two GROUP BYs for the breakdown — and the page reads
    identically.
    """
    from sqlalchemy import Text as _Text, case, cast, func

    from . import db as _db, kb as kbm, provenance as prov

    blocks = []
    for cls_name, table, headline, why in _kb_tables():
        model = getattr(_db, cls_name)
        cols = [c for c in model.__table__.columns]
        names = [c.name for c in cols]
        data_cols = [c for c in cols if c.name not in ("id", "tenant")]

        # One aggregate query per table: COUNT(*) plus a filled-count per
        # column. Emptiness matches the old in-python test (None, "", [],
        # {}) via a text cast — CAST(col AS TEXT) is valid for JSON on both
        # sqlite and Postgres, where VARCHAR would not be.
        aggs = [func.count()]
        for c in data_cols:
            aggs.append(func.sum(case(
                (c.is_(None), 0),
                (cast(c, _Text).in_(("", "[]", "{}", "null")), 0),
                else_=1)))
        with _db.SessionLocal() as s:
            q = s.query(*aggs)
            if "tenant" in names:
                q = q.filter(model.tenant == tenant)
            got = q.one()
            rev, org = {}, {}
            if "review" in names and "tenant" in names:
                rev = {(k or "—"): v for k, v in
                       s.query(model.review, func.count())
                       .filter(model.tenant == tenant)
                       .group_by(model.review).all()}
                org = {(k or "—"): v for k, v in
                       s.query(model.origin, func.count())
                       .filter(model.tenant == tenant)
                       .group_by(model.origin).all()}
        n = int(got[0] or 0)

        # Per-column fill rate. A column nobody fills is either dead weight or
        # a gap in the intake, and both are worth seeing.
        colrows = ""
        for c, filled in zip(data_cols, got[1:]):
            pct = int(100 * int(filled or 0) / n) if n else 0
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
        breakdown = ""
        if n and rev:
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

    return f"""
<div>
  <p class="mut">The shape of the data, as reference — which columns are
  actually being filled, and how the rows break down by where they came from
  and whether a human has approved them. Read from the models, so a new column
  shows up here on its own. The content lives on the domain views; the work
  lives on Queue &amp; Insights.</p>
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
"""


#: The four-tab contract (owner, 2026-08-27): KNOWLEDGE manages the
#: knowledge, the DATA LAYER explains it — how it connects, how complete it
#: is, how systems leverage it, and what the layer has been worth — REVIEW
#: decides, PLAN is the strategy. So this tab's sub-views are the
#: understanding set; the domain management views live on Knowledge.
SCHEMA_SUBS = (("queue", "Queue & Insights"), ("map", "The map"),
               ("leverage", "Leverage"), ("advanced", "Advanced"))

#: The domain views the Data layer briefly hosted (same push, same day)
#: before the owner drew the line above — their URLs 303 to Knowledge so
#: nothing anyone bookmarked breaks.
DOMAIN_SUBS = ("claims", "objections", "audiences", "catalogue",
               "situations", "photos")

#: Knowledge's sub-views: the Overview (the by-type page it has always
#: been) plus one management view per kind — paged, searchable, editable
#: in place.
KB_SUBS = (("", "Overview"), ("claims", "Claims"),
           ("objections", "Objections"), ("audiences", "Audiences"),
           ("catalogue", "Catalogue"), ("situations", "Situations"),
           ("photos", "Photos"))


def _kind_counts(tenant: str) -> dict:
    """Approved rows per kind — the strip numbers, from the same filters
    the domain views list (rule 8)."""
    from . import provenance as prov
    with db.SessionLocal() as s:
        return {
            "claims": s.query(db.KbClaim).filter(
                db.KbClaim.tenant == tenant,
                db.KbClaim.review == prov.APPROVED).count(),
            "objections": s.query(db.KbObjection).filter(
                db.KbObjection.tenant == tenant,
                db.KbObjection.review == prov.APPROVED).count(),
            "audiences": s.query(db.KbAudience).filter(
                db.KbAudience.tenant == tenant,
                db.KbAudience.review == prov.APPROVED).count(),
            "catalogue": s.query(db.KbEntity).filter(
                db.KbEntity.tenant == tenant,
                db.KbEntity.review == prov.APPROVED).count(),
            "situations": s.query(db.KbSituation).filter(
                db.KbSituation.tenant == tenant).count(),
            "photos": s.query(db.KbAsset).filter(
                db.KbAsset.tenant == tenant,
                db.KbAsset.review == prov.APPROVED).count(),
        }


def _schema_needs_you(tenant: str) -> dict:
    """The Data layer's needs-you rows, computed ONCE and shared by the
    badge, the strip and the queue itself — rule 8: a count and the list it
    points at come from the same query, or the number is learned as noise.

    Four parts, each wrapped so a failing feed counts zero instead of taking
    the sidebar down: readiness blockers, entity-attribute gaps that cost an
    answer, observed edit lessons, and mute-pattern proposals with a
    one-click accept. (The spec's fifth feed — craft proposals — has no
    carrier in the code yet and is not counted or rendered.)
    """
    out: dict = {"readiness": {}, "actions": [], "unknowns": [],
                 "lessons": [], "mutes": [], "mute_info": []}
    try:
        from . import resolve as _rs
        out["readiness"] = _rs.readiness(tenant)
        out["actions"] = list(out["readiness"].get("next_actions") or [])
    except Exception:                                            # noqa: BLE001
        pass
    try:
        out["unknowns"] = list(kb.unknowns(tenant))
    except Exception:                                            # noqa: BLE001
        pass
    try:
        out["lessons"] = systems.edit_lesson_rows(tenant)
    except Exception:                                            # noqa: BLE001
        pass
    try:
        from . import keywords as _kw
        ml = _kw.mute_lessons(tenant) or {}
        out["mutes"] = list(ml.get("terms") or [])
        out["mute_info"] = (list(ml.get("sources") or [])
                            + list(ml.get("clusters") or []))
    except Exception:                                            # noqa: BLE001
        pass
    out["n"] = (len(out["actions"]) + len(out["unknowns"])
                + len(out["lessons"]) + len(out["mutes"]))
    return out


def _dl_base(key: str, tenant: str, sub: str, q: str = "",
             state: str = "", tab: str = "schema") -> str:
    """One URL base for a domain view — search, state and pager all append
    to the same address, so a filter never loses the search and a page turn
    never loses either. `tab` names the host: the domain views moved to
    Knowledge under the four-tab contract (owner, 2026-08-27), and the
    machinery serves whichever tab hosts it."""
    from urllib.parse import quote as _q
    b = f"/admin/ui?tab={_esc(tab)}&amp;sub={_esc(sub)}&amp;tenant={_esc(tenant)}"
    if key:
        b += f"&amp;key={_esc(key)}"
    if state:
        b += f"&amp;state={_esc(state)}"
    if q:
        b += f"&amp;q={_esc(_q(q, safe=''))}"
    return b


def _dl_search(key: str, tenant: str, sub: str, q: str, state: str = "",
               what: str = "filter", tab: str = "schema") -> str:
    hidden = "".join(
        f'<input type="hidden" name="{n}" value="{_esc(v)}">'
        for n, v in (("tab", tab), ("sub", sub), ("tenant", tenant),
                     ("key", key), ("state", state)) if v)
    return (f'<form method="get" action="/admin/ui" class="row">{hidden}'
            f'<input name="q" value="{_esc(q)}" placeholder="{_esc(what)}" '
            f'style="flex:1;min-width:200px">'
            f'<button class="sec">Search</button>'
            + (f'<a class="mut" href="{_dl_base(key, tenant, sub, "", state, tab)}">'
               f'clear</a>' if q else "")
            + '</form>')


def _dl_back_fields(sub: str, state: str = "", page: int = 1,
                    q: str = "", tab: str = "schema") -> str:
    """Hidden fields every domain form carries so its route lands the
    reader back on THIS view, page and filter — rule 3, by name, never by
    echoing a URL. `back` names the hosting tab (kb for the re-homed
    domain views; schema for the queue's own forms)."""
    return (f'<input type="hidden" name="back" value="{_esc(tab)}">'
            f'<input type="hidden" name="bsub" value="{_esc(sub)}">'
            + (f'<input type="hidden" name="bstate" value="{_esc(state)}">'
               if state else "")
            + (f'<input type="hidden" name="bpage" value="{page}">'
               if page > 1 else "")
            + (f'<input type="hidden" name="bq" value="{_esc(q)}">'
               if q else ""))


def _dl_backq(sub: str, state: str = "", page: int = 1,
              tab: str = "schema") -> str:
    """The same back parts as a query fragment, for GET links."""
    s = f"back={_esc(tab)}&amp;bsub={_esc(sub)}"
    if state:
        s += f"&amp;bstate={_esc(state)}"
    if page > 1:
        s += f"&amp;bpage={page}"
    return s


def _match(q: str, *fields) -> bool:
    ql = (q or "").strip().lower()
    if not ql:
        return True
    hay = " ".join(str(f or "") for f in fields).lower()
    return all(w in hay for w in ql.split())


def _schema_queue(key: str, tenant: str, need: dict) -> str:
    """Queue & Insights — the landing. Three lanes (spec §5): what the brain
    is missing (answerable HERE), what it is learning from human edits
    (promote or dismiss HERE), and a fact shown WORKING inside real output —
    the honest answer to "nothing in the KB is display-only"."""
    from urllib.parse import quote as _q
    r = need["readiness"]

    # --- lane 1 · missing knowledge, each row with its typed control ------
    missing_sits = [p["situation"] for p in (r.get("per_situation") or [])
                    if p.get("state") == "unanswerable"]

    def _act_row(a: dict) -> str:
        fix = str(a.get("fix") or "")
        meta = (f'<div class="when">unblocks {_esc(str(a.get("unblocks", "")))}'
                + (f' · {a.get("situations", 0)} situation(s)'
                   if a.get("situations") else "") + "</div>")
        if fix.startswith("author an objection"):
            forms = "".join(f"""
      <form class="f" method="post" action="/admin/objection_add">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="tenant" value="{_esc(tenant)}">
        <input type="hidden" name="situations" value="{_esc(tag)}">
        {_dl_back_fields("queue")}
        <label>No approved answer for <code>{_esc(tag)}</code></label>
        <input name="objection" placeholder="the hesitation, in the buyer's words">
        <textarea name="response" rows="2" placeholder="the approved answer — saving files it as an objection, approved"></textarea>
        <div class="row"><button>Save answer</button>
          <span class="when">lands approved — the next draft can use it</span></div>
      </form>""" for tag in missing_sits[:3])
            more = (f'<div class="when">and {len(missing_sits) - 3} more '
                    f'situation(s) after these</div>'
                    if len(missing_sits) > 3 else "")
            return (f'<div class="msg"><div><strong>{_esc(fix)}</strong></div>'
                    f'{meta}{forms}{more}</div>')
        # The two brand blockers and the approve-backlog keep their labeled
        # link-button — their control-bearing surface is one place (one
        # writer), and the button says which.
        tab, label = _READINESS_WHERE.get(
            str(a.get("where") or "").strip().lower(), ("", ""))
        ctl = (f'<a class="btn sec" href="/admin/ui?tab={tab}'
               f'&amp;tenant={_esc(tenant)}'
               + (f'&amp;key={_esc(key)}' if key else "")
               + f'">{label} &rarr;</a>' if tab
               else f'<span class="mut">{_esc(str(a.get("where") or ""))}</span>')
        return (f'<div class="msg"><div><strong>{_esc(fix)}</strong></div>'
                f'{meta}<div class="row">{ctl}</div></div>')

    acts_html = ("".join(_act_row(a) for a in need["actions"])
                 or f'<p class="mut">Nothing is blocking this account. It can '
                    f'answer {r.get("answerable", 0)} of '
                    f'{r.get("situations", 0)} situations, '
                    f'{r.get("proven", 0)} of them with proof attached.</p>')

    unk_html = "".join(
        f'<div class="msg"><div><strong>{_esc(u.entity_name or u.entity_key)}'
        f'</strong> — {_esc((u.attribute or "").replace("_", " "))} unknown</div>'
        f'<div class="when">blocked an answer {_esc(u.hits)}× · last asked: '
        f'{_esc(u.asked_for or "—")}</div>'
        f'<form class="f" method="get" action="/admin/kb_unknown" '
        f'style="margin-top:6px">'
        f'<input type="hidden" name="key" value="{_esc(key)}">'
        f'<input type="hidden" name="tenant" value="{_esc(tenant)}">'
        f'<input type="hidden" name="id" value="{_esc(u.id)}">'
        f'{_dl_back_fields("queue")}'
        f'<div class="row"><input name="value" placeholder="the value, or n/a">'
        f'<button>Save</button></div></form></div>'
        for u in need["unknowns"]) or (
        '<p class="mut">Nothing has been asked for that this account could '
        'not answer.</p>')

    gaps = []
    try:
        gaps = kb.gaps(tenant)
    except Exception:                                            # noqa: BLE001
        pass
    if gaps:
        nxt = gaps[0]
        gap_html = f"""
    <details class="sec"><summary>The intake question ({len(gaps)} unanswered)</summary>
      <p style="margin-top:8px"><strong>{_esc(nxt['q'])}</strong></p>
      <form class="f" method="get" action="/admin/kb_add">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="tenant" value="{_esc(tenant)}">
        <input type="hidden" name="step" value="{nxt['id']}">
        {_dl_back_fields("queue")}
        <textarea name="text" rows="2" placeholder="{_esc(nxt['hint'])}"></textarea>
        <div class="row"><button>Answer</button></div>
      </form>
    </details>"""
    else:
        gap_html = ('<p class="mut">The intake is complete — every question '
                    'the pipeline requires has an answer.</p>')

    blocked = []
    try:
        blocked = systems.blocked_reasons(tenant, 30)
    except Exception:                                            # noqa: BLE001
        pass
    blocked_html = ""
    if blocked:
        blocked_html = (
            '<details class="sec"><summary>What cost an output (30 days, '
            f'{len(blocked)} reason(s))</summary>'
            '<p class="mut" style="margin-top:8px">Runs that blocked or '
            'shipped with a recorded defect, by reason, most frequent first '
            '— the authoring backlog ranked by what it actually cost.</p>'
            + "".join(f'<div class="msg"><code>{_esc(rule)}</code> '
                      f'<span class="chip off">×{n}</span></div>'
                      for rule, n in blocked[:10])
            + '</details>')

    lane1 = f"""
<div class="card">
  <div class="head"><h2>What to fix, in order</h2>
    <span class="chip {'off' if need['actions'] else 'on'}">{_esc(r.get("score", "0/0"))}
      situations answerable</span></div>
  <p class="mut">Ranked by how many situations each one releases, not by how
  quick it is. This account {_esc(r.get("verdict", "has no vocabulary yet"))}.
  Each row carries its control — answering files it approved, here.</p>
  <div class="thread">{acts_html}</div>
  <h3 style="font-size:.9rem;margin:14px 0 6px">Gaps that cost an answer
    <span class="chip {'off' if need['unknowns'] else 'on'}">{len(need['unknowns'])} open</span></h3>
  <div class="thread">{unk_html}</div>
  {gap_html}
  {blocked_html}
</div>"""

    # --- lane 2 · active learning — observed, never instruction ------------
    lessons_html = ""
    for les in need["lessons"]:
        rid = _esc(les["run_id"])
        base_fields = (
            f'<input type="hidden" name="key" value="{_esc(key)}">'
            f'<input type="hidden" name="tenant" value="{_esc(tenant)}">'
            f'<input type="hidden" name="run_id" value="{rid}">'
            f'<input type="hidden" name="system_key" '
            f'value="{_esc(les["system_key"])}">'
            + _dl_back_fields("queue"))
        lessons_html += f"""
  <div class="msg">
    <div><span class="chip nb">{_esc(les["system_key"])}</span>
      <span class="when">{_esc(f"{les['when']:%b %d}" if les.get("when") else "")}
      · observed from your edits · 60d window</span></div>
    <pre class="msg" style="white-space:pre-wrap;margin:6px 0">{_esc(les["text"][:600])}</pre>
    <div class="row">
      <form method="post" action="/admin/lesson_act" style="display:inline">
        {base_fields}
        <input type="hidden" name="act" value="guidance">
        <button class="sec" title="Standing guidance — injected into every future draft for this system">Keep as guidance</button>
      </form>
      <form method="post" action="/admin/lesson_act" style="display:inline">
        {base_fields}
        <input type="hidden" name="act" value="dismiss">
        <button class="sec" title="A one-off, not a pattern — it leaves this lane AND the drafter's brief">Dismiss</button>
      </form>
    </div>
    <details class="sec"><summary>Make it a rule</summary>
      <form method="post" action="/admin/lesson_act" class="row">
        {base_fields}
        <input type="hidden" name="act" value="rule">
        <input name="phrase" placeholder="the exact phrase to ban — the validator blocks it forever" style="flex:1;min-width:240px">
        <button class="sec">Ban it</button>
      </form>
    </details>
  </div>"""
    if not lessons_html:
        lessons_html = ('<p class="mut">No edited runs in the last 60 days. '
                        'When you edit a draft before it ships, the pattern '
                        'appears here to promote or dismiss.</p>')

    mutes_html = ""
    for m in need["mutes"]:
        mutes_html += f"""
  <div class="msg">
    <div><strong>{_esc(m.get("term", ""))}</strong>
      <span class="when">muted with it: {_esc(", ".join(m.get("muted_with_it") or [])[:120])}</span></div>
    <div class="when">{_esc(m.get("proposal", ""))}</div>
    <form method="get" action="/admin/exclude_term" class="row">
      <input type="hidden" name="key" value="{_esc(key)}">
      <input type="hidden" name="tenant" value="{_esc(tenant)}">
      <input type="hidden" name="term" value="{_esc(m.get("term", ""))}">
      {_dl_back_fields("queue")}
      <button class="sec">Exclude it — the harvest stops surfacing it</button>
    </form>
  </div>"""
    for m in need["mute_info"]:
        mutes_html += (
            f'<div class="msg"><div class="when">{_esc(m.get("proposal", ""))}'
            f' · <a href="/admin/ui?tab=plan&amp;tenant={_esc(tenant)}'
            + (f'&amp;key={_esc(key)}' if key else "")
            + '">retire it on Plan &rarr;</a></div></div>')
    if not (need["mutes"] or need["mute_info"]):
        mutes_html = ('<p class="mut">No mute patterns yet — under a handful '
                      'of muted keywords, a shared word is a coincidence, not '
                      'a pattern.</p>')

    lane2 = f"""
<div class="card">
  <div class="head"><h2>Active learning</h2>
    <span class="chip {'off' if (need['lessons'] or need['mutes']) else 'on'}">{len(need['lessons']) + len(need['mutes'])} waiting</span></div>
  <p class="mut"><b>Observed, never instruction</b> — the code's own
  distinction. These are patterns read from what you actually changed and
  muted; promoting one makes it standing guidance or a hard rule, dismissing
  one removes it from the drafter's brief too.</p>
  {lessons_html}
  <h3 style="font-size:.9rem;margin:14px 0 6px">From your muted keywords</h3>
  {mutes_html}
</div>"""

    return lane1 + lane2 + _grounded_lane(key, tenant)


def _grounded_lane(key: str, tenant: str) -> str:
    """Grounded output v1 (spec §5, the one new build): a claim shown WORKING
    inside a kept artifact — used N times in 90 days, last in a named piece,
    with the sentence that carries it. The display shows the fact doing its
    job, which is the honest answer to a KB that reads as display-only."""
    import datetime as _dt

    since = db.utcnow() - _dt.timedelta(days=90)
    uses: dict[str, list] = {}
    with db.SessionLocal() as s:
        outs = (s.query(db.Output)
                .filter(db.Output.tenant == tenant,
                        db.Output.created_at >= since,
                        db.Output.claim_ids.isnot(None))
                .order_by(db.Output.created_at.desc())
                .limit(400).all())
        s.expunge_all()
    for o in outs:
        for cid in (o.claim_ids or []):
            uses.setdefault(str(cid), []).append(o)
    top = sorted(uses.items(), key=lambda kv: -len(kv[1]))[:3]
    if not top:
        return ("""
<div class="card">
  <div class="head"><h2>Grounded output</h2><span class="chip nb">preview</span></div>
  <p class="mut">No output has cited a claim in the last 90 days. Once drafts
  cite proof, this shows each fact working inside the real thing — the
  sentence it became, in the artifact it shipped in.</p>
</div>""")

    with db.SessionLocal() as s:
        by_id = {c.id: c for c in
                 s.query(db.KbClaim)
                 .filter(db.KbClaim.id.in_([cid for cid, _ in top])).all()}
        s.expunge_all()

    rows_html = ""
    for cid, used in top:
        claim = by_id.get(cid)
        if claim is None:
            continue
        latest = used[0]
        used_ids = [o.id for o in used[:12]]
        with db.SessionLocal() as s:
            art = (s.query(db.ArtifactBody)
                   .filter(db.ArtifactBody.output_id.in_(used_ids)).first())
            if art is None:
                # An ad VARIANT is kept inside its batch, not under its own
                # id — the same membership resolution the workroom route
                # runs, or every ad claim would read as "not kept".
                from sqlalchemy import or_
                art = (s.query(db.ArtifactBody)
                       .filter(db.ArtifactBody.format == "ad_batch",
                               or_(*[db.ArtifactBody.body.like(f'%"{i}"%')
                                     for i in used_ids])).first())
            s.expunge_all()
        quote_html = ""
        where = ""
        if art is not None:
            if (art.format or "") == "ad_batch":
                # Quote the VARIANT'S copy — the JSON around it is the
                # record, not the artifact a reader would recognise.
                import json as _json
                sent = ""
                try:
                    for v in _json.loads(art.body or "").get("variants") or []:
                        if (cid in (v.get("claim_ids") or [])
                                or v.get("output_id") in used_ids):
                            sent = _cited_sentence(str(v.get("text") or ""),
                                                   claim.claim or "")
                            break
                except Exception:                                # noqa: BLE001
                    pass
            else:
                sent = _cited_sentence(art.body or art.draft_body or "",
                                       claim.claim or "")
            if sent:
                quote_html = (f'<div class="msg esc" style="margin-top:6px">'
                              f'&hellip;{sent}&hellip;</div>')
            where = (f' · last in <a href="/admin/work/{_esc(art.output_id)}'
                     + (f'?key={_esc(key)}' if key else "")
                     + f'">{_esc((art.format or "artifact").replace("_", " "))}'
                     f' &middot; {_esc(str(latest.created_at)[:10])}</a>')
        else:
            where = (' · the artifacts were not kept whole (pre-workroom '
                     'outputs), so the sentence cannot be shown')
        uses_fold = (
            '<details class="sec"><summary>'
            f'See all {len(used)} use(s)</summary>'
            + "".join(f'<div class="msg"><span class="when">'
                      f'{_esc(str(o.created_at)[:16])} · '
                      f'{_esc(o.system_key or "")} · '
                      f'{_esc((o.format or ""))}</span></div>'
                      for o in used[:15])
            + '</details>')
        rows_html += (
            f'<div class="msg"><div>claim: <b>{_esc(claim.claim)}</b></div>'
            f'<div class="when">used {len(used)}&times; / 90d{where}</div>'
            f'{quote_html}'
            f'<div class="row"><a class="btn sec" '
            f'href="{_dl_base(key, tenant, "claims")}#cl-{_esc(cid)}">'
            f'Edit claim &rarr;</a></div>'
            f'{uses_fold}</div>')

    return f"""
<div class="card">
  <div class="head"><h2>Grounded output</h2><span class="chip nb">preview</span></div>
  <p class="mut">The most-used proof, shown working — the sentence a claim
  became, inside the artifact that shipped it. Nothing here is display-only:
  each row carries its editor.</p>
  <div class="thread">{rows_html}</div>
</div>"""


def _cited_sentence(html: str, claim: str) -> str:
    """The sentence of the artifact that most carries the claim's words —
    a token-overlap best match, with the shared words bolded. Deterministic
    and honest: when nothing overlaps, empty, and the caller says so."""
    text = _re.sub(r"<[^>]+>", " ", html or "")
    text = _re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    toks = {w for w in _re.findall(r"[a-z0-9']+", (claim or "").lower())
            if len(w) > 3}
    if not toks:
        return ""
    best, best_n = "", 0
    for sent in _re.split(r"(?<=[.!?])\s+", text):
        n = sum(1 for w in _re.findall(r"[a-z0-9']+", sent.lower())
                if w in toks)
        if n > best_n:
            best, best_n = sent, n
    if best_n < 2:
        return ""
    out = _esc(best[:300])
    for w in sorted(toks, key=len, reverse=True):
        out = _re.sub(f"(?i)\\b({_re.escape(w)})\\b", r"<b>\1</b>", out)
    return out


def _schema_domain(key: str, tenant: str, sub: str, q: str, state: str,
                   page: int, tab: str = "schema") -> str:
    """One domain view: a paged list of the rows with edit-in-place, a
    search filter, the pending count linking at the Review queue, and a
    structured add form — the pipe-format textareas retire here.

    Hosted by KNOWLEDGE under the four-tab contract (owner, 2026-08-27:
    Knowledge manages, the Data layer explains); `tab` binds every URL and
    back-field to the hosting tab, so the machinery serves either."""
    from . import provenance as prov
    per = 15
    base = _dl_base(key, tenant, sub, q, state, tab)

    def _bf(s_, st="", pg_=1, q_=""):
        return _dl_back_fields(s_, st, pg_, q_, tab)

    def _bq(s_, st="", pg_=1):
        return _dl_backq(s_, st, pg_, tab)

    def _srch(q_, st="", what="filter"):
        return _dl_search(key, tenant, sub, q_, st, what, tab)
    ents = kb.entities(tenant, available_only=False)
    cat = {e.key: e.name for e in ents}
    datalist = ('<datalist id="objents">'
                + "".join(f'<option value="{_esc(k)}">{_esc(v)}</option>'
                          for k, v in cat.items()) + "</datalist>")

    def _page_slice(rows_):
        total = len(rows_)
        pg = max(1, min(page, max(1, -(-total // per))))
        return rows_[(pg - 1) * per:pg * per], _pager(base, pg, total, per,
                                                      sub), pg

    def _pending_chip(model, review_sub: str) -> str:
        with db.SessionLocal() as s:
            n = (s.query(model)
                 .filter(model.tenant == tenant,
                         model.review == prov.PROPOSED).count())
        if not n:
            return ""
        return (f'<span class="chip off">{n} awaiting review &middot; '
                f'<a href="/admin/ui?tab=content&amp;sub={review_sub}&amp;'
                f'tenant={_esc(tenant)}'
                + (f'&amp;key={_esc(key)}' if key else "")
                + '">decide on Review</a></span>')

    def _add_fold(title: str, kind: str, fields: str) -> str:
        return f"""
<details class="sec"><summary>{_esc(title)}</summary>
  <form class="f" method="post" action="/admin/kb_row_add">
    <input type="hidden" name="key" value="{_esc(key)}">
    <input type="hidden" name="tenant" value="{_esc(tenant)}">
    <input type="hidden" name="kind" value="{_esc(kind)}">
    {_bf(sub, state, page, q)}
    {fields}
    <div class="row"><button>Add — it lands approved, yours to edit here</button></div>
  </form>
</details>"""

    if sub == "claims":
        inv = kb.claim_inventory(tenant)
        with db.SessionLocal() as s:
            # KbClaim carries no created_at; verified_at is the row's most
            # recent attestation and orders removed rows newest-first.
            removed = (s.query(db.KbClaim)
                       .filter(db.KbClaim.tenant == tenant,
                               db.KbClaim.review == prov.REJECTED)
                       .order_by(db.KbClaim.verified_at.desc()).all())
            s.expunge_all()
        states = (("selectable", inv["selectable"]),
                  ("awaiting", inv["pending"]),
                  ("expired", inv["expired"]),
                  ("retired", inv["retired"]),
                  ("removed", removed))
        cur = state if state in dict(states) else "selectable"
        chips = '<div class="filters">' + "".join(
            f'<a class="{"on" if k == cur else ""}" '
            f'href="{_dl_base(key, tenant, sub, q, k)}">{k} ({len(v)})</a>'
            for k, v in states) + "</div>"
        vocab = sorted(kb.situations(tenant))
        rows_ = [r for r in dict(states)[cur]
                 if _match(q, r.claim, r.evidence,
                           " ".join(r.situations or []), r.entity_key)]
        shown, pager, pg = _page_slice(rows_)
        bf = _bf(sub, cur, pg, q)
        body = ""
        for r in shown:
            if cur == "removed":
                body += (
                    _claim_row(key, tenant, r, vocab, "removed — no "
                               "generator may cite it", "gone")
                    + f"""
      <form method="post" action="/admin/kb_restore" class="row">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="tenant" value="{_esc(tenant)}">
        <input type="hidden" name="kind" value="claim">
        <input type="hidden" name="id" value="{_esc(r.id)}">
        {_bf(sub, cur, pg, q)}
        <button class="sec">Restore</button>
        <span class="when">back to approved — every generator may cite it
        again</span>
      </form>""")
            elif cur == "awaiting":
                body += (_claim_row(key, tenant, r, vocab,
                                    "not selectable until approved", "gone")
                         + _claim_decide_row(key, tenant, r,
                                             backq=_bq(sub, cur, pg)))
            else:
                body += _claim_row(key, tenant, r, vocab,
                                   editable=(cur == "selectable"),
                                   cls=("" if cur == "selectable" else "gone"),
                                   back_fields=bf)
        empty = {"selectable": "No usable proof. Any draft that needs a "
                               "number is blocked.",
                 "awaiting": "Nothing submitted for review.",
                 "expired": "Nothing has gone stale.",
                 "retired": "Nothing retired.",
                 "removed": "Nothing removed by hand."}[cur]
        add = _add_fold("Add a claim", "claim", f"""
    <label>Claim — one checkable statement</label>
    <textarea name="claim" rows="2"></textarea>
    <label>Evidence — what makes it checkable</label>
    <input name="evidence">
    <label>Situations</label>
    <div class="tags">{"".join(
        f'<label class="tag"><input type="checkbox" name="situations" '
        f'value="{_esc(t)}"> {_esc(t)}</label>' for t in vocab)
        or '<span class="mut">no vocabulary yet — untagged is brand-wide proof</span>'}</div>""")
        return f"""
<div class="card">
  <div class="head"><h2>Claims — the proof drafts may cite</h2>
    <span class="chip {'on' if inv['selectable'] else 'off'}">{len(inv['selectable'])} usable</span>
    {_pending_chip(db.KbClaim, "claims")}</div>
  {chips}
  {_srch(q, cur, "search claims, evidence, tags")}
  {pager}
  <div class="thread">{body or f'<p class="mut">{_esc(empty)}{" Nothing matches the filter." if q else ""}</p>'}</div>
  {pager}
  {add}
  {datalist}
</div>"""

    if sub == "objections":
        rows_ = [r for r in kb.objections(tenant, any_entity=True)
                 if _match(q, r.objection, r.response, r.entity_key,
                           " ".join(r.situations or []))]
        shown, pager, pg = _page_slice(rows_)
        vocab = sorted(kb.situations(tenant))
        bf = _bf(sub, "", pg, q)
        body = "".join(
            f'<div class="msg">{_objection_row(key, tenant, r, cat, bf)}'
            + _remove_control(key, tenant, "objection", r.id, "this answer",
                              back_fields=bf)
            + '</div>' for r in shown)
        add = _add_fold("Add an objection", "objection", f"""
    <label>Objection — the hesitation in the buyer's words</label>
    <textarea name="objection" rows="2"></textarea>
    <label>The approved answer</label>
    <textarea name="response" rows="3"></textarea>
    <label>True of — blank claims it of everything they sell</label>
    <input name="entity_key" list="objents">
    <label>Situations</label>
    <div class="tags">{"".join(
        f'<label class="tag"><input type="checkbox" name="situations" '
        f'value="{_esc(t)}"> {_esc(t)}</label>' for t in vocab)
        or '<span class="mut">no vocabulary yet</span>'}</div>""")
        return f"""
<div class="card">
  <div class="head"><h2>Objections — the approved answers</h2>
    <span class="chip {'on' if rows_ else 'off'}">{len(rows_)}</span>
    {_pending_chip(db.KbObjection, "other")}</div>
  {_srch(q, "", "search objections and answers")}
  {pager}
  <div class="thread">{body or '<p class="mut">None. This is human-authored and it is half of the intake.</p>'}</div>
  {pager}
  {add}
  {datalist}
</div>"""

    if sub == "audiences":
        rows_ = [r for r in kb.audiences(tenant)
                 if _match(q, r.name, r.key, " ".join(r.pains or []),
                           " ".join(r.vocabulary or []))]
        shown, pager, pg = _page_slice(rows_)
        body = ""
        for r in shown:
            body += (f'<div class="msg">'
                     f"<div><strong>{_esc(r.name)}</strong> <code>{_esc(r.key)}</code></div>"
                     + _kv([("pains", _words(r.pains, "none recorded")),
                            ("their words", _words(r.vocabulary,
                                                   "none — selection cannot recognise this buyer")),
                            ("buying trigger", _esc(r.buying_trigger) or _mut("not set")),
                            ("decides in", _esc(r.decision_timeline) or _mut("not set"))]
                           + ([("notes", _esc(r.notes))] if r.notes else []))
                     + f"""
      <details><summary class="mut">Edit</summary>
        <form class="f" method="post" action="/admin/audience_update">
          <input type="hidden" name="key" value="{_esc(key)}">
          <input type="hidden" name="tenant" value="{_esc(tenant)}">
          <input type="hidden" name="row_id" value="{_esc(r.id)}">
          {_bf(sub, "", pg, q)}
          <label>Name</label>
          <input name="name" value="{_esc(r.name or '')}">
          <label>Pains — one per line</label>
          <textarea name="pains" rows="3">{_esc(chr(10).join(r.pains or []))}</textarea>
          <label>Their words — one per line; selection matches on these</label>
          <textarea name="vocabulary" rows="3">{_esc(chr(10).join(r.vocabulary or []))}</textarea>
          <label>Buying trigger</label>
          <input name="buying_trigger" value="{_esc(r.buying_trigger or '')}">
          <label>Decides in</label>
          <input name="decision_timeline" value="{_esc(r.decision_timeline or '')}">
          <div class="row"><button class="sec">Save</button></div>
        </form>
      </details>"""
                     + _remove_control(key, tenant, "audience", r.id,
                                       r.name or r.key,
                                       back_fields=_bf(sub, "", pg, q))
                     + '</div>')
        add = _add_fold("Add an audience", "audience", """
    <label>Key — short, lowercase</label>
    <input name="akey" placeholder="hosts">
    <label>Name</label>
    <input name="name" placeholder="Hosts who entertain">
    <label>Pains — one per line</label>
    <textarea name="pains" rows="2"></textarea>
    <label>Their words — one per line</label>
    <textarea name="vocabulary" rows="2"></textarea>""")
        return f"""
<div class="card">
  <div class="head"><h2>Audiences — who they sell to</h2>
    <span class="chip {'on' if rows_ else 'off'}">{len(rows_)}</span>
    {_pending_chip(db.KbAudience, "other")}</div>
  <p class="mut">The one KB kind that had no editor (spec §5) — it does now:
  every field a segment is selected on, editable in place.</p>
  {_srch(q, "", "search audiences")}
  {pager}
  <div class="thread">{body or '<p class="mut">No segments. Selection cannot narrow to a buyer.</p>'}</div>
  {pager}
  {add}
</div>"""

    if sub == "catalogue":
        rows_ = [r for r in ents
                 if _match(q, r.name, r.key, r.type, r.description)]
        shown, pager, pg = _page_slice(rows_)
        groups = [r for r in ents if (r.type or "") == "collection"]
        opts = "".join(f'<option value="{_esc(g.key)}">{_esc(g.name)}</option>'
                       for g in groups)
        body = ""
        for r in shown:
            grp = ""
            if groups and (r.type or "") != "collection":
                grp = f"""
      <form method="post" action="/admin/entity_group" class="row">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="tenant" value="{_esc(tenant)}">
        <input type="hidden" name="entity_keys" value="{_esc(r.key)}">
        {_bf(sub, "", pg, q)}
        <select name="group">{opts}</select>
        <button class="sec">Add to group</button>
        <span class="when">membership is additive — adding one never removes
        another</span>
      </form>"""
            body += (f'<div class="msg">'
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
                     + "</div>" + grp
                     + _remove_control(key, tenant, "entity", r.id, r.name,
                                       "Anything scoped only to it — its claims, its "
                                       "objections, its photographs — comes out with it.",
                                       back_fields=_bf(sub, "", pg, q))
                     + '</div>')
        bulk = ""
        if groups and len(shown) > 1:
            picks = "".join(
                f'<label class="pick"><input type="checkbox" name="entity_keys" '
                f'value="{_esc(r.key)}" form="grp"> {_esc(r.name)}</label>'
                for r in shown if (r.type or "") != "collection")
            bulk = f"""
<details class="sec"><summary>Group several at once (this page's items)</summary>
  <form id="grp" method="post" action="/admin/entity_group"></form>
  <input type="hidden" name="key" value="{_esc(key)}" form="grp">
  <input type="hidden" name="tenant" value="{_esc(tenant)}" form="grp">
  <input type="hidden" name="back" value="{tab}" form="grp">
  <input type="hidden" name="bsub" value="catalogue" form="grp">
  <div class="bulkbar">
    <select name="group" form="grp">{opts}</select>
    <span class="grow"></span>
    <button form="grp">Add selected to this group</button>
  </div>
  <div class="tags">{picks}</div>
  <p class="mut">Search first to narrow the page — the old 200-checkbox wall
  is what this replaces.</p>
</details>"""
        add = _add_fold("Add something they sell", "entity", """
    <label>Type</label>
    <select name="etype"><option>product</option><option>collection</option>
      <option>service</option></select>
    <label>Key — short, lowercase</label>
    <input name="ekey" placeholder="aqua-plate">
    <label>Name</label>
    <input name="name">
    <label>Price</label>
    <input name="price" placeholder="$95">
    <label>Description</label>
    <textarea name="description" rows="2"></textarea>""")
        return f"""
<div class="card">
  <div class="head"><h2>Catalogue — what they sell</h2>
    <span class="chip {'on' if rows_ else 'off'}">{len(rows_)}</span>
    {_pending_chip(db.KbEntity, "other")}</div>
  <div class="row">{_act(key, "/admin/catalog_sync", "Sync from store", tenant)}
    <span class="when">the store owns price and availability; editorial
    fields conflict rather than overwrite</span></div>
  {_srch(q, "", "search the catalogue")}
  {pager}
  <div class="thread">{body or '<p class="mut">Nothing catalogued. Selection has nothing to offer.</p>'}</div>
  {pager}
  {bulk}
  {add}
</div>"""

    if sub == "situations":
        sits = [r for r in kb.situation_rows(tenant)
                if _match(q, r.tag, r.description)]
        shown, pager, pg = _page_slice(sits)
        body = "".join(
            f'<div class="msg"><div><code>{_esc(r.tag)}</code> '
            f'<span class="chip nb">{_esc(r.kind or "problem")}</span></div>'
            f'<div class="when">{_esc(r.description) or _mut("no description")}</div>'
            f'<div class="when">triggers on: '
            + (_esc(", ".join(" ".join(p) for p in (r.patterns or []) if p))
               or _mut("no patterns — diagnosis can never assign this tag"))
            + "</div>"
            + _remove_control(key, tenant, "situation", r.id, r.tag,
                              "Claims already tagged with it keep the tag, but "
                              "no new claim may carry it.",
                              back_fields=_bf(sub, "", pg, q))
            + "</div>" for r in shown)
        add = f"""
<details class="sec"><summary>Add a situation</summary>
  <form method="get" action="/admin/situation_add" class="f">
    <input type="hidden" name="key" value="{_esc(key)}">
    <input type="hidden" name="tenant" value="{_esc(tenant)}">
    {_bf(sub, "", pg, q)}
    <label>Tag — short, lowercase</label>
    <input name="tag" placeholder="planning_a_wedding">
    <label>What a buyer in it is trying to do</label>
    <input name="description">
    <div class="row"><button class="sec">Add situation</button></div>
  </form>
</details>"""
        return f"""
<div class="card">
  <div class="head"><h2>Situations — this account's vocabulary</h2>
    <span class="chip {'on' if sits else 'off'}">{len(sits)} tags</span></div>
  <p class="mut">The only tags a claim for this account may carry — a claim
  tagged with anything else is refused on the way in.</p>
  {_srch(q, "", "search tags")}
  {pager}
  <div class="thread">{body or '<p class="mut">No vocabulary authored yet — add the first tag below.</p>'}</div>
  {pager}
  {add}
</div>""" + _situation_overlap_card(key, tenant,
                                    kb.situation_overlaps(tenant),
                                    back_fields=_bf(sub))

    # photos
    return _photo_library(tenant, key, page=max(1, page),
                          base=_dl_base(key, tenant, "photos", q, tab=tab),
                          back_fields=_bf("photos", "", max(1, page), q))


#: Which knowledge KIND each `kb_needs` token names — the map's edges and
#: the leverage table's "reads" column both derive from this, so a system
#: declaring a need and the visual disagreeing is impossible by
#: construction.
_NEED_KIND = {
    "claim": ("claims", "Claims"),
    "entity": ("catalogue", "Catalogue"),
    "audience": ("audiences", "Audiences"),
    "objection": ("objections", "Objections"),
    "situation": ("situations", "Situations"),
    "situations": ("situations", "Situations"),
    "tone": ("", "Brand voice"),
    "positioning": ("", "Brand voice"),
    "banned_claims": ("", "Hard rules"),
}


def _installed_systems(tenant: str) -> list:
    with db.SessionLocal() as s:
        rows = (s.query(db.System)
                .filter(db.System.tenant == tenant,
                        db.System.status != "retired")
                .order_by(db.System.key).all())
        s.expunge_all()
    return rows


def _schema_map(key: str, tenant: str) -> str:
    """The map — how the data connects (owner, 2026-08-27: "a visual of how
    everything connects, to completion of the data, the structure of the
    data and the way systems leverage the data").

    Derived, never drawn by hand: kind counts come from the same queries
    Knowledge's strip shows, each system's reads come from its declared
    `kb_needs`, and every node links to the tab that owns it — Knowledge to
    manage, Review to decide, Systems to run. Four columns, left to right:
    where a fact enters, what it becomes, the gates every draft passes,
    and who reads it.
    """
    from . import resolve as _rs
    counts = _kind_counts(tenant)
    b = kb.brand(tenant)
    banned = list((b.banned_claims or []) if b else [])
    voice = bool(b and (b.voice or {}).get("tone"))
    r = {}
    try:
        r = _rs.readiness(tenant)
    except Exception:                                            # noqa: BLE001
        pass
    rows_sys = _installed_systems(tenant)

    def _kb_link(sub: str) -> str:
        return (f"/admin/ui?tab=kb"
                + (f"&amp;sub={sub}" if sub else "")
                + f"&amp;tenant={_esc(tenant)}"
                + (f"&amp;key={_esc(key)}" if key else ""))

    reads_by_kind: dict[str, int] = {}
    for row in rows_sys:
        for need in systems.spec(row.key).get("kb_needs") or ():
            k = _NEED_KIND.get(need, ("", ""))[1]
            if k:
                reads_by_kind[k] = reads_by_kind.get(k, 0) + 1

    def _node(label: str, meta: str, href: str = "", on: bool = True) -> str:
        head = (f'<a href="{href}">{_esc(label)}</a>' if href
                else _esc(label))
        return (f'<div class="fnode{"" if on else " dim"}"><b>{head}</b>'
                f'<span class="when">{meta}</span></div>')

    kinds_col = ""
    for sub_, label in (("claims", "Claims"), ("objections", "Objections"),
                        ("audiences", "Audiences"),
                        ("catalogue", "Catalogue"),
                        ("situations", "Situations"), ("photos", "Photos")):
        n = counts.get(sub_, 0)
        readers = reads_by_kind.get(label, 0)
        kinds_col += _node(
            f"{label} · {n}",
            (f"read by {readers} system(s)" if readers else
             "no installed system declares it — reference until one does"),
            _kb_link(sub_), on=n > 0)
    kinds_col += _node(
        f"Hard rules · {len(banned)}",
        f"read by every gate, against every draft — including yours",
        f"/admin/ui?tab=brand&amp;tenant={_esc(tenant)}"
        + (f"&amp;key={_esc(key)}" if key else ""), on=bool(banned))
    kinds_col += _node(
        "Brand voice" + (" · set" if voice else " · not set"),
        "tone and positioning ride every drafter brief",
        f"/admin/ui?tab=brand&amp;tenant={_esc(tenant)}"
        + (f"&amp;key={_esc(key)}" if key else ""), on=voice)

    sys_col = ""
    for row in rows_sys:
        needs = [
            _NEED_KIND.get(nd, ("", nd))[1]
            for nd in systems.spec(row.key).get("kb_needs") or ()]
        sys_col += _node(
            row.name or row.key,
            ("reads: " + ", ".join(dict.fromkeys(needs))
             if needs else "reads no knowledge — runs on connections alone")
            + f" · {row.status}",
            f"/admin/ui?tab=systems&amp;tenant={_esc(tenant)}"
            f"&amp;system={_esc(row.key)}"
            + (f"&amp;key={_esc(key)}" if key else ""),
            on=(row.status == "live"))
    if not sys_col:
        sys_col = _node("No systems installed",
                        "install one on the Systems tab and its reads "
                        "appear here", on=False)

    score = _esc(str(r.get("score", "0/0")))
    return f"""
<div class="card">
  <div class="head"><h2>How it all connects</h2>
    <span class="chip {'on' if r.get('answerable') else 'off'}">{score}
      situations answerable</span></div>
  <p class="mut">Facts enter on the left, become governed knowledge in the
  middle, pass the gates, and come out as drafts a system produced — held on
  Review until you approve. Everything below is read live: the counts are
  Knowledge's own, each system's reads are its declared needs, and every
  node opens the tab that owns it — <b>Knowledge to manage, Review to
  decide, this tab to understand</b>.</p>
  <div class="flow">
    <div class="flowcol">
      <div class="flowlab">Where a fact enters</div>
      {_node("You — console & Telegram", "adds land approved; edits are re-attestations", _kb_link(""))}
      {_node("Client intake links", "answers land as proposals", f"/admin/ui?tab=accounts&amp;tenant={_esc(tenant)}" + (f"&amp;key={_esc(key)}" if key else ""))}
      {_node("Site crawl & store sync", "candidate facts and catalogue rows — proposals, never silent overwrites")}
      {_node("Sent-mail harvest", "voice and objection candidates from real correspondence")}
    </div>
    <div class="flowarr">&rarr;</div>
    <div class="flowcol">
      <div class="flowlab">The knowledge, by kind</div>
      {kinds_col}
      <div class="when">proposals wait on
        <a href="/admin/ui?tab=content&amp;tenant={_esc(tenant)}{f'&amp;key={_esc(key)}' if key else ''}">Review</a>
        — nothing here is citable until approved</div>
    </div>
    <div class="flowarr">&rarr;</div>
    <div class="flowcol">
      <div class="flowlab">The gates every draft passes</div>
      {_node("Validator", f"{len(banned)} hard rule(s) — a banned phrase is refused, whoever wrote it", on=bool(banned))}
      {_node("Coherence", "one artifact, one subject — parts checked against the commitment")}
      {_node("Structure", "rendered artifacts must hold together — links, variables, cut words")}
      {_node("Fitness", "draft and archived products are never offered, anywhere")}
    </div>
    <div class="flowarr">&rarr;</div>
    <div class="flowcol">
      <div class="flowlab">Who reads it</div>
      {sys_col}
      <div class="when">what they produce holds on
        <a href="/admin/ui?tab=content&amp;tenant={_esc(tenant)}{f'&amp;key={_esc(key)}' if key else ''}">Review</a>
        until you approve it</div>
    </div>
  </div>
</div>"""


def _schema_leverage(key: str, tenant: str) -> str:
    """Leverage — what the layer has been worth, measured (owner,
    2026-08-27: "how effective that data has been in outputs compared to
    just using a skill without this context / coherence / compliance
    layer").

    There is no ungrounded control arm and this page does not invent one.
    The honest form of the comparison is the counterfactual the assurance
    ledger already keeps: every catch listed here is something a drafter
    actually produced and the layer stopped or repaired — running the same
    skill without the layer is precisely the world where each one shipped.
    """
    import datetime as _dt

    from . import assurance
    rep = assurance.report(tenant, 90)
    since = db.utcnow() - _dt.timedelta(days=90)
    with db.SessionLocal() as s:
        outs = (s.query(db.Output)
                .filter(db.Output.tenant == tenant,
                        db.Output.created_at >= since).count())
        cited = (s.query(db.Output)
                 .filter(db.Output.tenant == tenant,
                         db.Output.created_at >= since,
                         db.Output.claim_ids.isnot(None)).count())
        ev = (s.query(db.AssuranceEvent)
              .filter(db.AssuranceEvent.tenant == tenant,
                      db.AssuranceEvent.created_at >= since).all())
        s.expunge_all()

    by_sys: dict[str, dict] = {}
    for e in ev:
        d = by_sys.setdefault(e.system_key or "—",
                              {"checks": 0, "caught": 0})
        d["checks"] += 1
        if e.caught:
            d["caught"] += 1

    caught = rep.get("caught") or {}
    caught_total = rep.get("caught_total", sum(caught.values()))
    repairs = rep.get("repairs") or {}
    grounding = rep.get("grounding") or {}
    edited = rep.get("edited") or {}

    meters = f"""
  <div class="stat">
    <span><b>{outs}</b> outputs (90d)</span>
    <span><b>{cited}</b> grounded in cited claims</span>
    <span><b>{caught_total}</b> catches</span>
    <span><b>{repairs.get('succeeded', 0)}</b> repaired, then shipped clean</span>
    <span><b>{repairs.get('still_blocked', 0)}</b> refused outright</span>
  </div>"""

    if caught:
        rules = "".join(
            f'<div class="msg"><code>{_esc(rule)}</code> '
            f'<span class="chip off">×{n}</span></div>'
            for rule, n in list(caught.items())[:12])
        counterfactual = f"""
<div class="card">
  <div class="head"><h2>What would have shipped without the layer</h2>
    <span class="chip off">{caught_total} caught (90d)</span></div>
  <p class="mut">Each of these is something a drafter actually produced and
  a gate stopped — a banned phrase, an uncited assertion, an off-subject
  artifact, a broken render. Running the same skill without this layer is
  the world where every one of them reached a customer in the client's
  name. Repaired ones were fixed and re-checked; refused ones never left.</p>
  <div class="thread">{rules}</div>
</div>"""
    else:
        counterfactual = """
<div class="card">
  <div class="head"><h2>What would have shipped without the layer</h2></div>
  <p class="mut">No catches in this window. On a quiet account that means
  nothing was checked or nothing was produced — the meters above say which;
  a live account with output and zero catches is worth reading twice.</p>
</div>"""

    rows_html = ""
    counts = _kind_counts(tenant)
    b = kb.brand(tenant)
    for row in _installed_systems(tenant):
        spec = systems.spec(row.key)
        needs = [nd for nd in spec.get("kb_needs") or ()]
        chips = ""
        for nd in needs:
            sub_, label = _NEED_KIND.get(nd, ("", nd))
            if nd == "banned_claims":
                have = bool(b and b.banned_claims)
            elif nd in ("tone", "positioning"):
                have = bool(b and (b.voice or {}).get("tone"))
            else:
                have = counts.get(sub_, 0) > 0
            chips += (f'<span class="chip {"on" if have else "off"}">'
                      f'{_esc(label)}</span> ')
        with db.SessionLocal() as s:
            n_out = (s.query(db.Output)
                     .filter(db.Output.tenant == tenant,
                             db.Output.system_key == row.key,
                             db.Output.created_at >= since).count())
        st = by_sys.get(row.key, {"checks": 0, "caught": 0})
        rows_html += (
            f'<div class="msg"><div><b>{_esc(row.name or row.key)}</b> '
            f'<span class="chip nb">{_esc(row.status)}</span></div>'
            f'<div class="when">reads: {chips or "—"}</div>'
            f'<div class="when">{n_out} output(s) · {st["checks"]} check(s) '
            f'· {st["caught"]} with a catch</div></div>')

    grounded_line = (
        f'{grounding.get("with_a_claim_id", 0)} of '
        f'{grounding.get("measured", 0)} measured drafts cited an approved '
        f'claim' if grounding.get("measured") else
        "grounding is not yet measured in this window")
    edited_note = _esc(str(edited.get("note") or ""))

    return f"""
<div class="card">
  <div class="head"><h2>Leverage — what the layer is worth</h2>
    <span class="chip nb">90 days</span></div>
  <p class="mut">The comparison is honest by construction: there is no
  ungrounded control arm, so what is counted is the counterfactual the
  assurance ledger keeps — everything a drafter produced that the gates
  caught, repaired or refused before it left. {_esc(grounded_line)}.</p>
  {meters}
  {f'<p class="when">{edited_note}</p>' if edited_note else ""}
</div>
{counterfactual}
<div class="card">
  <div class="head"><h2>How each system leverages it</h2></div>
  <p class="mut">What each installed system declares it reads (green = on
  file, amber = missing — the gap is on Queue &amp; Insights), and what the
  gates did for its output.</p>
  <div class="thread">{rows_html or '<p class="mut">No systems installed yet.</p>'}</div>
</div>"""


def render_schema(key: str, tenant: str = "", sub: str = "", q: str = "",
                  state: str = "", page: int = 1, msg: str = "",
                  err: str = "") -> str:
    """The Data layer — the actionable brain (step 4, spec §5).

    Queue & Insights lands first: the brain asks, you answer inline; what it
    learned from your edits waits to be promoted or dismissed; and the most-
    used proof is shown working inside a kept artifact. The domain views are
    the content, paged with edit-in-place; Advanced keeps the schema
    reference this tab used to be, computed with COUNT queries instead of
    full-table loads.
    """
    tenant, _here, _rows = _account(tenant)
    if tenant == ALL:
        return _shell(key, "schema", "Data layer", tenant=tenant,
                      body=_every_note(True, "The knowledge base is per "
                                       "client. Pick an account to work its "
                                       "queue."))
    sub = (sub or "").strip().lower() or "queue"
    if sub in DOMAIN_SUBS:
        # The management views live on Knowledge now (the four-tab
        # contract); a bookmark from the days this tab hosted them keeps
        # working — with its filter, search and page intact.
        from urllib.parse import quote as _uq

        from fastapi.responses import RedirectResponse
        u = f"/admin/ui?tab=kb&sub={_uq(sub)}&tenant={_uq(tenant)}"
        if state:
            u += f"&state={_uq(state)}"
        if q:
            u += f"&q={_uq(q)}"
        if page > 1:
            u += f"&page={page}"
        return RedirectResponse(u, 303)
    if sub not in dict(SCHEMA_SUBS):
        sub = "queue"

    need = _schema_needs_you(tenant)

    def _sub_href(k: str) -> str:
        return (f"/admin/ui?tab=schema&amp;sub={k}&amp;tenant={_esc(tenant)}"
                + (f"&amp;key={_esc(key)}" if key else ""))

    strip = '<div class="subtabs">' + "".join(
        f'<a class="subtab{" on" if k == sub else ""}" href="{_sub_href(k)}">'
        f'{_esc(label)}'
        + (f'<span class="cnt">{need["n"]}</span>' if k == "queue" else "")
        + '</a>'
        for k, label in SCHEMA_SUBS) + "</div>"

    if sub == "map":
        body = _schema_map(key, tenant)
    elif sub == "leverage":
        body = _schema_leverage(key, tenant)
    elif sub == "advanced":
        body = _schema_advanced(key, tenant)
    else:
        body = _schema_queue(key, tenant, need)

    flash = ((f'<div class="ok">{_esc(msg)}</div>' if msg else "")
             + (f'<div class="bad">{_esc(err)}</div>' if err else ""))
    if flash:
        flash = f'<div class="flash">{flash}</div>'

    return _shell(key, "schema", "Data layer", tenant=tenant,
                  body=flash + strip + body,
                  suffix=f"&amp;tenant={_esc(tenant)}")


def render_assurance(key: str, tenant: str = "", days: int = 30,
                     system: str = "", rule: str = "", started: str = "") -> str:
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
    # Named once, used by every query below. `"" if every else tenant` was
    # written out at each call site, and the moment a new one was added it was
    # the thing most likely to be got wrong — an all-accounts page is the exact
    # case where a missed scope shows one client's numbers under another's name.
    scope = "" if every else tenant
    rep = assurance.report(scope, days)
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

    # COMPLIANCE IS INDEPENDENT OF WHETHER ANYTHING WAS DRAFTED. Built here,
    # above the empty-state return, because an account with no validated drafts
    # yet is exactly the one whose live site nobody has checked — and letting
    # the early return swallow it would have moved the report off Review and
    # into a page that does not always render it.
    comp_card = f"""
    <div class="card">
      <div class="head"><h2>Live site compliance</h2></div>
      <p class="mut">The other half of assurance: everything else on this page
      is what the layer caught BEFORE anything shipped, and this is what is
      already live on the client&#39;s own site. Moved here from Review (owner,
      2026-08-23) — Review is a queue of decisions waiting on you, and a report
      about published pages is not a decision.</p>
      {_compliance_body(tenant) if not every else
       '<p class="mut">A scan reads one client&#39;s own site against one '
       'client&#39;s ban list, so there is nothing to pool here. Pick an '
       'account to see and run it.</p>'}
      {'' if every else
       f'<div class="row">{_act(key, "/admin/compliance_scan", "Scan now", tenant)}'
       '<span class="mut">checks every public page against this account&#39;s '
       'rules</span></div>'}
    </div>"""

    if not rep["events"]:
        body = (_every_note(every, "Checks recorded across every account.")
                + windows
                + f'<div class="note"><strong>Nothing has been checked for '
                f'{_esc(_account_name(tenant, here))} in the last {days} '
                f'days.</strong><br>That is not the same as '
                f'nothing being wrong — it means no draft passed through a '
                f'validator, so this page has no evidence either way.</div>'
                + comp_card)
        return _shell(key, "assurance", "Assurance", body=body, tenant=tenant,
                      suffix=f"&amp;days={days}")

    # A NUMBER YOU CANNOT OPEN IS A NUMBER YOU TAKE ON FAITH. `catches()`
    # accepts `system_key` and `rule` filters; the first version of this page
    # passed neither, so the drill-down existed in the model layer and was
    # reachable from nowhere.
    def _drill(system_: str = "", rule_: str = "") -> str:
        bits = ["tab=assurance", f"tenant={_esc(tenant)}", f"days={days}"]
        if system_:
            bits.append(f"system={_esc(system_)}")
        if rule_:
            bits.append(f"rule={_esc(rule_)}")
        if key:
            bits.append(f"key={_esc(key)}")
        return "/admin/ui?" + "&amp;".join(bits)

    catch_rows = "".join(
        f'<tr><td><a href="{_drill(rule_=r)}"><code>{_esc(r)}</code></a></td>'
        f'<td class="num">{n}</td></tr>'
        for r, n in rep["caught"].items()) or \
        '<tr><td colspan="2" class="mut">nothing caught in this window</td></tr>'

    src_rows = "".join(
        f'<tr><td>{_esc(src)}</td><td class="num">{d["checks"]}</td>'
        f'<td class="num">{d["caught"]}</td><td class="num">{d["blocked"]}</td></tr>'
        for src, d in sorted(rep["by_source"].items()))

    # PER SYSTEM. `report()` groups by SOURCE — which layer did the checking —
    # and that answers a question nobody asks. "Which system keeps getting
    # caught" is the one people actually have, `system_key` is on every row and
    # indexed, and nothing grouped by it.
    sysrows = "".join(
        f'<tr><td><a href="{_drill(system_=e["system"])}">{_esc(e["system"])}</a></td>'
        f'<td class="num">{e["checks"]}</td>'
        f'<td class="num">{e["catches"]}</td>'
        f'<td class="num">{e["blocked"] or ""}</td>'
        f'<td class="num">{e["repaired"] or ""}</td>'
        f'<td>{"".join(f"<code>{_esc(k)}</code> {n} " for k, n in e["top_rules"])}</td>'
        f'</tr>' for e in assurance.by_system(scope, days)) or \
        '<tr><td colspan="6" class="mut">nothing checked in this window</td></tr>'

    # THE CATCHES THEMSELVES. The page could say "14 caught" and never show one
    # of them — the draft was on the Output row the event already points at and
    # was never joined. A page whose whole job is to be believed has to be able
    # to show its work.
    got = assurance.catches(scope, days, limit=40,
                            system_key=system, rule=rule)
    narrowed = ""
    if system or rule:
        what = " · ".join(x for x in (system, rule) if x)
        narrowed = (f'<p class="mut">Showing only <b>{_esc(what)}</b>. '
                    f'<a href="{_drill()}">show everything &rarr;</a></p>')
    catch_cards = "".join(
        '<div class="msg">'
        f'<div class="when">{_esc(c["when"])} · {_esc(c["system"] or "—")} · '
        f'{_esc(c["where"])}'
        + (f' · {_esc(c["tenant"])}' if every else "")
        + (f' · attempt {_esc(str(c["attempt"]))}' if str(c["attempt"]) not in ("0", "") else "")
        + '</div>'
        + '<div>' + "".join(f'<code>{_esc(r)}</code> ' for r in c["rules"])
        + f'<span class="chip {"off" if c["verdict"] == "blocked" else "on"}">'
          f'{_esc(c["verdict"])}</span></div>'
        + (f'<div class="msg esc">{_esc(c["body"])}</div>' if c["body"] else
           '<div class="when">no draft was filed — the gate refused before '
           'anything reached the ledger</div>')
        + '</div>' for c in got)
    if not got and (system or rule):
        catch_cards = ('<p class="mut">Nothing matches that filter in this '
                       'window.</p>')
    elif not got:
        catch_cards = ('<p class="mut">Nothing was caught in this window. On a '
                       'live account that is worth reading twice: it means '
                       'either the drafts were clean or nothing was drafted, '
                       'and the count above says which.</p>')

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
    {windows}
    <p class="mut">Last {days} days · {rep['events']} checks recorded.</p>

    <details class="conns" open><summary>What was caught</summary>
      <p class="mut">Each of these is a phrase the model wrote and
      deterministic code stopped. Without the layer it would have gone out —
      this is the one number here that needs no interpretation.</p>
      <table class="tbl"><tr><th>rule</th><th>times</th></tr>
      {catch_rows}</table>
      <p class="when"><strong>{rep['caught_total']}</strong> total.</p>

      <h3 style="font-size:.9rem;margin:16px 0 6px">Which system</h3>
      <table class="tbl"><tr><th>system</th><th class="num">checks</th>
        <th class="num">caught</th><th class="num">blocked</th>
        <th class="num">repaired</th><th>most often</th></tr>
      {sysrows}</table>

      <h3 style="font-size:.9rem;margin:16px 0 6px">The drafts themselves</h3>
      <p class="mut">What the model actually wrote, and what stopped it. A
      number you cannot open is a number you have to take on faith — and this
      is the page whose whole job is to be believed.</p>
      {narrowed}
      <div class="thread">{catch_cards}</div>
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

    {comp_card}
    """
    # `suffix` rides the CURRENT tab's own nav link, so the window survives a
    # trip to another tab and back. Diagnostics has always done this; Assurance
    # did not, so every visit silently reset to 30 days.
    # The scan's own feedback, on the page whose button starts it. The banner
    # machinery lived on Review; the scan moved here (2026-08-23) and its
    # feedback did not move with it — the started flash was dropped by the
    # dispatcher and the bg status was keyed under a label and tenant nothing
    # read, so a crashed scan looked identical to one still running.
    scan_note = ""
    if started == "scan":
        scan_note = ('<div class="ok">Scan started — it reads the live site, '
                     'so give it a minute and refresh.</div>')
    try:
        from .web import bg_status as _bgs
        _st = _bgs("scan", tenant) or {}
    except Exception:                                            # noqa: BLE001
        _st = {}
    if _st.get("state") == "failed":
        scan_note += (f'<div class="note"><strong>The last scan failed</strong>'
                      f' — {_esc(_st.get("detail", ""))}</div>')
    elif _st.get("state") == "done" and _st.get("detail"):
        scan_note += f'<div class="ok">{_esc(_st.get("detail", ""))}</div>'
    body = scan_note + body
    return _shell(key, "assurance", "Assurance", body=body, tenant=tenant,
                  suffix=f"&amp;days={days}")


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


#: Where each kind of problem is actually fixed. The label is what the button
#: says; the tab is where it goes. A list of things that went wrong is only
#: useful if every line knows where its fix lives.
_FIX_WHERE = {
    "accounts": ("Connections", "connect the account"),
    "systems": ("Systems", "install or switch it on"),
    "kb": ("Knowledge", "author what is missing"),
    "content": ("Review", "decide what is queued"),
    "diagnostics": ("", ""),
}


def _systems_check(key: str, tenant: str, days: int, need: list,
                   scope: str, system: str) -> str:
    """Per-system health, and every item needing attention WITH its content.

    Three things, in the order somebody actually works: which system is unwell,
    what keeps going wrong, and — the part that did not exist before — the runs
    themselves, so a line reading "12x no_ban_list" can be opened and read.
    """
    rows = systems.per_system(scope, days)
    if system:
        rows = [r for r in rows if r["key"] == system]

    def _when(dt_):
        return _esc(db.as_utc(dt_).strftime("%b %d, %H:%M")) if dt_ else "never"

    if rows:
        table = ('<table class="tbl"><tr><th>system</th><th>state</th>'
                 '<th class="num">runs</th><th class="num">shipped</th>'
                 '<th class="num">blocked</th><th class="num">defective</th>'
                 '<th>last run</th></tr>' + "".join(
            f'<tr><td><a href="/admin/ui?tab=systems&amp;tenant={_esc(r["tenant"])}'
            f'&amp;system={_esc(r["key"])}'
            + (f'&amp;key={_esc(key)}' if key else "")
            + f'">{_esc(r["name"] or r["key"])}</a>'
            + (f'<div class="when">{_esc(r["tenant"])}</div>' if not tenant or tenant == ALL else "")
            + f'</td>'
            f'<td><span class="chip {"on" if r["status"] == "live" else "off"}">'
            f'{_esc(r["status"] or "designed")}</span> '
            f'<span class="mut">{_esc(r["autonomy"] or "")}</span></td>'
            f'<td class="num">{r["runs"]}</td>'
            f'<td class="num">{r["shipped"]}</td>'
            f'<td class="num">{r["blocked"] or ""}</td>'
            f'<td class="num">{r["defective"] or ""}</td>'
            f'<td class="when">{_when(r["last_at"])}</td></tr>'
            for r in rows) + "</table>")
    else:
        table = ('<p class="mut">No systems installed for this account yet — '
                 'install one on the Systems tab and its runs appear here.</p>')

    # --- the items, with their content ------------------------------------
    cards = ""
    for a in need:
        where_tab, verb = _FIX_WHERE.get(a["where"], ("", ""))
        fix = ""
        if where_tab:
            fix = (f'<a class="btn sec" href="/admin/ui?tab={_esc(a["where"])}'
                   f'&amp;tenant={_esc(tenant)}'
                   + (f'&amp;key={_esc(key)}' if key else "")
                   + f'">{_esc(where_tab)} &rarr;</a>'
                   f'<span class="mut">{_esc(verb)}</span>')
        # THE RUNS THEMSELVES. Folded, because twelve examples open at once is
        # the wall of text this page is replacing — but present, because
        # "12x no_ban_list" with no way to see one is what made the old list
        # useless.
        egs = "".join(
            f'<div class="msg"><div class="when">{_when(e["at"])} · '
            f'{_esc(e["system"])} · {_esc(e["stage"] or "?")}'
            + (f' · {_esc(e["tenant"])}' if not tenant or tenant == ALL else "")
            + (f' · ref {_esc(e["ref"])}' if e["ref"] else "")
            + '</div>'
            + (f'<div class="det">{_esc(e["error"])}</div>' if e["error"] else "")
            + (f'<div class="msg esc">{_esc(e["output"])}</div>'
               if e["output"] else "")
            + (f'<div class="when">also: '
               + _esc(", ".join(x for x in e["blocked_on"]
                                if x != a["reason"])) + "</div>"
               if len(e["blocked_on"]) > 1 else "")
            + "</div>"
            for e in a["examples"])
        seen = (f'first {_when(a["first_at"])} · last {_when(a["last_at"])}'
                if a["count"] > 1 else f'{_when(a["last_at"])}')
        cards += f"""
    <div class="card">
      <div class="head">
        <h2 style="font-size:.95rem">{_esc(a["reason"])[:140]}</h2>
        <span class="chip off">{a["count"]}&times;</span></div>
      <p class="mut"><span class="chip">{_esc(a["label"])}</span>
        {_esc(" · ".join(f"{k} ({n})" for k, n in
                         sorted(a["systems"].items(), key=lambda kv: -kv[1])))}
        &nbsp;·&nbsp; {seen}</p>
      <div class="row">{fix}</div>
      <details class="sec"><summary>The {len(a["examples"])} most recent
        {"run" if len(a["examples"]) == 1 else "runs"}</summary>
        <div class="thread">{egs}</div></details>
    </div>"""

    if not need:
        cards = ('<div class="card"><p class="mut">Nothing was refused and '
                 f'nothing shipped with a defect in the last {days} days. '
                 'That is either a quiet period or a healthy one — the table '
                 'above says which.</p></div>')

    return f"""
<div>
  <h2>Systems check</h2>
  <p class="mut">Which system is unwell, since when, and what exactly went
  wrong — with the runs that prove it. Ranked by how often each thing bit,
  most recent first between equals.</p>
</div>

<div class="card">
  <div class="head"><h2>Every system, last {days} days</h2>
    <span class="mut">worst first</span></div>
  {table}
  <p class="mut"><b>blocked</b> is a run that produced nothing.
  <b>defective</b> is a run that shipped anyway and needs fixing — those are
  the ones nobody notices without this column.</p>
</div>

<div class="card">
  <div class="head"><h2>Needs attention</h2>
    <span class="chip {'off' if need else 'on'}">{len(need)} distinct</span></div>
  <p class="mut">Every reason a run was refused or shipped defective in the
  window, with the runs themselves. <b>Quality</b> items are deliberately here
  and deliberately absent from the Systems backlog: no amount of authoring
  fixes an incoherent email, so counting it as an authoring gap would send
  somebody to write rows that could not have helped.</p>
</div>
{cards}
"""


#: Diagnostics has two jobs and they want different pages. The timeline
#: answers "what is happening right now, across everything"; Systems check
#: answers "which system is unwell, since when, and what exactly went wrong".
#: One scroll served the first and buried the second (owner, 2026-08-23).
DIAG_VIEWS = (("overview", "Overview"), ("systems", "Systems check"))


def render_diagnostics(key: str, tenant: str = "", days: int = 7,
                       level: str = "", system: str = "",
                       limit: int = 200, live: int = 0, view: str = "") -> str:
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
    # --- Systems check ------------------------------------------------------
    #
    # The Systems tab used to open on a flat `<ul>` of "12x no_ban_list" with
    # nothing clickable, no dates, and no way to see a single example — the
    # content was on the run row the whole time and was never joined (owner,
    # 2026-08-23). It lives here instead, because it is a diagnosis and not a
    # thing you install.
    view = (view or "").strip().lower()
    if view not in dict(DIAG_VIEWS):
        view = DIAG_VIEWS[0][0]

    def _dv(v: str) -> str:
        bits = [f"tab=diagnostics", f"view={v}", f"days={days}",
                f"tenant={_esc(tenant)}"]
        if system:
            bits.append(f"system={_esc(system)}")
        if key:
            bits.append(f"key={_esc(key)}")
        return "/admin/ui?" + "&amp;".join(bits)

    need = systems.attention("" if every else tenant, days,
                             system_key=system or "")
    strip = '<div class="subtabs">' + "".join(
        f'<a class="subtab{" on" if v == view else ""}" href="{_dv(v)}">{label}'
        + (f'<span class="cnt">{sum(a["count"] for a in need)}</span>'
           if v == "systems" else "") + "</a>"
        for v, label in DIAG_VIEWS) + "</div>"

    if view == "systems":
        return _shell(key, "diagnostics", "Diagnostics", tenant=tenant,
                      head=refresh, suffix=f"&amp;days={days}",
                      body=_every_note(
                          every, "Every account's systems in one table. Each "
                                 "row names the client it belongs to.")
                      + f'<div class="filters">{windows}<span class="sep">'
                        f'</span>{sysfilter}</div>'
                      + strip
                      + _systems_check(key, tenant, days, need,
                                       "" if every else tenant, system))

    body = f"""
{_every_note(every, "Every account's runs, calls and checks in one timeline. "
             "Each row names the client it belongs to.")}
<div class="filters">{windows}<span class="sep"></span>{levels}{sysfilter}
  <span class="sep"></span>{livebar}</div>
{strip}
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


def _blog_picker(key: str, tenant: str, pick: bool) -> str:
    """Choose which blog on the store articles publish into.

    The alternative, until now, was hand-building a percent-encoded JSON blob
    for `/admin/tenant_set?field=cms` — which is not configuration, it is a
    developer typing a database value into a URL bar. The id is the only thing
    standing between a drafted article and a published one, so it belongs on
    the page that reports it missing.

    The store is only called when asked (`pick`), because this page renders on
    every visit and a Shopify round trip per load would make the console feel
    broken on a slow morning.
    """
    from . import sites
    ask = (f'<a href="/admin/ui?key={_esc(key)}&amp;tab=plan&amp;tenant='
           f'{_esc(tenant)}&amp;pick=1"><button class="sec" type="button">'
           f'Find the blogs on this store</button></a>')
    if not pick:
        return f'<p>{ask}</p>'
    try:
        raw = sites.backend(sites.get(tenant)).list_blogs(sites.get(tenant))
    except Exception as exc:                                     # noqa: BLE001
        return (f'<p class="bad">Could not read the store: '
                f'{_esc(exc.__class__.__name__)}: {_esc(str(exc)[:160])}</p>{ask}')
    rows = []
    for line in (raw or "").splitlines():
        parts = line.split("  ")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            bid, title = parts[0].strip(), parts[1].strip()
            rows.append(
                f'<li>{_esc(title)} <code>{_esc(bid)}</code> '
                f'<a href="/admin/blog_set?key={_esc(key)}&amp;tenant='
                f'{_esc(tenant)}&amp;blog_id={_esc(bid)}">'
                f'<button type="button">Use this one</button></a></li>')
    if not rows:
        # `list_blogs` returns a SENTENCE on failure and on an empty store —
        # showing it beats rendering an empty list that looks like a bug.
        return f'<p class="mut">{_esc((raw or "")[:300])}</p>{ask}'
    return ("<ul>" + "".join(rows) + "</ul>"
            '<p class="when">Articles publish into the blog you pick. A store '
            'can hold several, and guessing writes into the wrong one.</p>')


def _plan_window(key: str, tenant: str, days: int) -> str:
    """ONE window control for the whole Plan tab (spec §7).

    The board was hard-coded to 7 days while this control governed only the
    Progress section below it — so "Moved in the last 7 days" sat directly
    above a control that silently did not affect it, which is a page telling
    you two different things about the same word. Both tables read `days`
    now, and the control sits in the header where it can be seen to govern
    them.
    """
    return '<div class="filters">' + "".join(
        f'<a class="{"on" if days == d else ""}" '
        f'href="/admin/ui?tab=plan&amp;tenant={_esc(tenant)}&amp;days={d}'
        + (f"&amp;key={_esc(key)}" if key else "")
        + f'">{lbl}</a>' for d, lbl in ((7, "7 days"), (28, "28 days"),
                                        (90, "90 days"))) + \
        '<span class="mut" style="margin-left:8px">every dated table on this ' \
        'page reads this window</span></div>'


def _board_section(key: str, tenant: str, days: int) -> str:
    """The map as the four questions somebody asks of it, not one sorted list.

    A single table ordered by score says what to do and nothing about why,
    what changed, what is unclaimed, or which article was written for which
    keyword — which was the one join between the plan and the content and had
    no surface at all.
    """
    from . import keywords as kw
    b = kw.board(tenant, days=days)
    if not b["keywords"]:
        return ""

    def _why(parts: dict) -> str:
        """The arithmetic, in the order it is weighted."""
        bits = []
        s = parts.get("striking")
        if s:
            bits.append(f'striking +{s:g}')
        c = parts.get("cluster")
        if c:
            bits.append(f'cluster +{c:g}')
        d = parts.get("demand")
        if d:
            bits.append(f'demand +{d:g}')
        diff = parts.get("difficulty")
        if isinstance(diff, (int, float)) and diff:
            bits.append(f'difficulty {diff:g}')
        elif isinstance(diff, str):
            bits.append("difficulty unknown")
        return " · ".join(bits)

    def _tier(t):
        return _esc((t or "").replace("_", "-"))

    def _say(phrase: str, current: str) -> str:
        """Pin, mute, or clear — on the row, where the judgement is formed.

        Both controls are always offered and the current state is a word, not
        a highlighted button: an override you cannot see is one you forget you
        set, and a keyword mysteriously first for weeks is worse than one
        openly pinned.
        """
        from urllib.parse import quote
        base = (f'/admin/keyword_priority?key={_esc(key)}&amp;tenant='
                f'{_esc(tenant)}&amp;ui=1&amp;phrase={quote(phrase)}&amp;mode=')
        if current:
            return (f'<span class="chip">{_esc(current)}</span> '
                    f'<a href="{base}" title="clear">clear</a>')
        return (f'<a href="{base}pinned" title="always write this next">pin</a> '
                f'<a href="{base}muted" title="never propose this">mute</a>')

    next_rows = "".join(
        f'<tr><td>{_esc(r["phrase"])}</td><td>{_tier(r["tier"])}</td>'
        f'<td>{_esc(r["intent"])}</td><td>{_esc(r["role"])}</td>'
        f'<td class="num">{r["volume"] or "—"}</td>'
        f'<td class="num">{r["position"] if r["position"] is not None else "—"}</td>'
        f'<td class="num">{(r["priority"] or 0):.0f}</td>'
        f'<td class="when">{_esc(_why(r["parts"]))}</td>'
        f'<td>{_say(r["phrase"], r.get("owner_priority") or "")}</td></tr>'
        for r in b["writing_next"]) or (
        '<tr><td colspan="9" class="mut">every keyword in the map is already '
        'planned or published</td></tr>')

    def _move_rows(items, label):
        return "".join(
            f'<tr><td>{_esc(r["phrase"])}</td><td>{_tier(r["tier"])}</td>'
            f'<td class="num">{r.get("from", "—")}</td>'
            f'<td class="num">{r.get("to", "—")}</td>'
            f'<td class="num">{r.get("gain", "")}</td>'
            f'<td>{_esc(label)}</td></tr>' for r in items)

    moved = (_move_rows(b["moved"]["up"], "up")
             + _move_rows(b["moved"]["down"], "down")
             + _move_rows(b["moved"]["entered"], "first reading")) or (
        f'<tr><td colspan="6" class="mut">no position changed in '
        f'{b["window_days"]} days — the nightly sync needs two readings to '
        f'compare</td></tr>')

    opp = ""
    for tier in ("head", "body", "long_tail"):
        items = b["opportunities"].get(tier) or []
        if not items:
            continue
        opp += (f'<tr class="grp"><td colspan="6"><strong>{_tier(tier)}</strong> '
                f'<span class="when">{len(items)} unclaimed</span></td></tr>')
        opp += "".join(
            f'<tr><td>{_esc(r["phrase"])}</td><td>{_esc(r["intent"])}</td>'
            f'<td class="num">{r["volume"] or "—"}</td>'
            f'<td class="num">{r["difficulty"] if r["difficulty"] is not None else "?"}</td>'
            f'<td class="num">{(r["priority"] or 0):.0f}</td>'
            f'<td>{_say(r["phrase"], r.get("owner_priority") or "")}</td></tr>'
            for r in items[:8])
    opp = opp or ('<tr><td colspan="6" class="mut">nothing unclaimed</td></tr>')

    flight = "".join(
        f'<tr><td>{_esc(r["phrase"])}</td><td>{_esc(r["status"])}</td>'
        f'<td>{_esc(r["role"])}</td><td>{_esc(r["cluster"])}</td>'
        f'<td class="num">{r["position"] if r["position"] is not None else "—"}</td>'
        f'<td>' + (f'<a href="{_esc(r["target_url"])}">live page</a>'
                   if r["target_url"] else
                   (f'<a href="/admin/article/{_esc(r["output_id"])}'
                    f'?key={_esc(key)}">review the draft</a>' if r["output_id"]
                    else '<span class="mut">not written yet</span>'))
        + '</td></tr>'
        for r in b["in_flight"]) or (
        '<tr><td colspan="6" class="mut">no keyword has been planned yet — '
        'press "Propose the next articles"</td></tr>')

    fresh = "".join(
        f'<tr><td>{_esc(r["phrase"])}</td><td>{_tier(r["tier"])}</td>'
        f'<td class="num">{r["volume"] or "—"}</td>'
        f'<td class="num">{(r["priority"] or 0):.0f}</td></tr>'
        for r in b["new_this_week"])
    fresh_html = (f'<h3>New to the map this week</h3><table class="tbl">'
                  f'<tr><th>keyword</th><th>tier</th><th>volume</th>'
                  f'<th>priority</th></tr>{fresh}</table>' if fresh else "")

    # --- the ruled-out, folded away, with what they add up to -------------
    les = b.get("lessons") or {}
    proposals = ""
    # TERM proposals carry the one action that has a backing store — accept
    # into `Tenant.analytics["exclude_terms"]`, which the site profile merges
    # and the harvest already honours. Source and cluster findings stay prose:
    # "this harvester is mostly noise" is a judgement for a person, and a
    # button that half-implements it would act on less than it claims.
    for item in les.get("terms") or []:
        proposals += (
            f'<li>→ {_esc(item["proposal"])} '
            f'<a href="/admin/exclude_term?key={_esc(key)}&amp;tenant='
            f'{_esc(tenant)}&amp;ui=1&amp;term={_esc(item["term"])}">'
            f'<button class="sec" type="button">Exclude it</button></a></li>')
    for group in ("sources", "clusters"):
        for item in les.get(group) or []:
            proposals += f'<li>→ {_esc(item["proposal"])}</li>'
    muted_rows = "".join(
        f'<tr><td>{_esc(r["phrase"])}</td><td>{_tier(r["tier"])}</td>'
        f'<td class="num">{r["volume"] or "—"}</td>'
        f'<td>{_esc(r["cluster"])}</td>'
        f'<td>{_say(r["phrase"], "muted")}</td></tr>'
        for r in b.get("muted") or [])
    muted_html = ""
    if muted_rows:
        muted_html = f"""
        <details><summary>Muted — {len(b["muted"])} keyword(s) you ruled out
        </summary>
          <table class="tbl">
            <tr><th>keyword</th><th>tier</th><th>volume</th><th>cluster</th>
                <th></th></tr>
            {muted_rows}
          </table>
          <p class="when">Out of Writing next and Opportunities entirely —
          a decision already made should not be re-presented every week — and
          the planner never proposes one. Clear it here to bring it back.</p>
          """ + (f"""<h4>What these have in common</h4>
          <ul>{proposals}</ul>
          <p class="when">Proposals, not actions. An exclude term added
          silently would shrink every future harvest with no way to find out
          why a keyword stopped appearing.</p>"""
                 if proposals else
                 f'<p class="when">{_esc(les.get("note") or "nothing they share yet")}</p>') + """
        </details>"""

    counts = " · ".join(f"{n} {s}" for s, n in sorted(b["counts"].items()))
    return f"""
    <h3>Writing next <span class="when">{_esc(counts)}</span></h3>
    <table class="tbl">
      <tr><th>keyword</th><th>tier</th><th>intent</th><th>role</th>
          <th>volume</th><th>position</th><th>priority</th><th>why</th>
          <th>your call</th></tr>
      {next_rows}
    </table>
    <p class="when">The <em>why</em> column is the score's own arithmetic.
    Striking distance leads because a page already ranking 11&ndash;20 is the
    biggest single lever; finishing a cluster beats starting one; demand is
    weighted by intent; difficulty subtracts only where it is known.</p>

    <h3>Moved in the last {b["window_days"]} days</h3>
    <table class="tbl">
      <tr><th>keyword</th><th>tier</th><th>was</th><th>now</th><th>gain</th>
          <th></th></tr>
      {moved}
    </table>
    <p class="when">{_esc(b["moved"]["note"])}</p>

    {fresh_html}

    <h3>Opportunities</h3>
    <table class="tbl">
      <tr><th>keyword</th><th>intent</th><th>volume</th><th>difficulty</th>
          <th>priority</th><th>your call</th></tr>
      {opp}
    </table>
    <p class="when">A head term and a long-tail are different decisions, so
    they are ranked apart. A head term is won with a pillar page plus the
    supports that link into it &mdash; never with one article.</p>

    <h3>What each article is targeting</h3>
    <table class="tbl">
      <tr><th>keyword</th><th>status</th><th>role</th><th>cluster</th>
          <th>position</th><th>the content</th></tr>
      {flight}
    </table>
    <p class="when">The join between the plan and what was actually written.
    A draft with no live page is one waiting on approval or on a CMS.</p>

    {muted_html}"""


def _progress_section(key: str, tenant: str, days: int) -> str:
    """Did the work move anything, and may we say it was the work.

    On the same page as the plan, deliberately. A plan and its result are one
    subject; putting the numbers on a separate tab is how a plan stops being
    checked against them. `keywords.progress` reads only our own tables, so
    this costs no API call and can render on every visit.

    THE GOAL FORM IS HERE because this is the section that reports its
    absence. `set_goal` was reachable only as a URL with four query
    parameters, which is the same defect as the blog id: naming a missing
    value and then sending somebody elsewhere to supply it.
    """
    from . import keywords as kw
    p = kw.progress(tenant, days=days)
    t, c = p["tracked"], p["control"]

    def _num(v, suffix=""):
        return "—" if v in (None, "") else f"{v}{suffix}"


    # TRACKED BESIDE CONTROL, always. A rise on its own is a claim; a rise
    # against the rest of the site over the same window is a finding. The
    # control column is why this table has four columns instead of two.
    compare = f"""
    <table class="tbl">
      <tr><th></th><th>clicks</th><th>vs before</th><th>avg position</th>
          <th>position gain</th></tr>
      <tr><td><strong>Articles we wrote</strong></td>
          <td class="num">{t["now"]["clicks"]}</td>
          <td class="num">{_num(t["change"]["clicks_pct"], "%")}</td>
          <td class="num">{_num(t["now"]["avg_position"])}</td>
          <td class="num">{_num(t["change"]["position_gain"])}</td></tr>
      <tr><td>The rest of the site <span class="mut">(control)</span></td>
          <td class="num">{c["now"]["clicks"]}</td>
          <td class="num">{_num(c["change"]["clicks_pct"], "%")}</td>
          <td class="num">{_num(c["now"]["avg_position"])}</td>
          <td class="num">{_num(c["change"]["position_gain"])}</td></tr>
    </table>
    <p class="when">A smaller position is better, so a POSITIVE gain is an
    improvement. The control row is what separates our work from a good
    quarter for the whole category.</p>"""

    moves = "".join(
        f'<tr><td>{_esc(m["phrase"])}</td>'
        f'<td>{_esc((m["tier"] or "").replace("_", "-"))}</td>'
        f'<td class="num">{_num(m["from"])}</td>'
        f'<td class="num">{m["to"]}</td>'
        f'<td class="num">{_num(m["gain"])}</td>'
        f'<td class="num">{m["clicks"]}</td>'
        f'<td>{_esc(str(m["days_since_publish"]))}'
        + ('<span class="mut"> · too early to attribute</span>'
           if m["too_early"] else "") + '</td></tr>'
        for m in p["movements"]) or (
        '<tr><td colspan="7" class="mut">nothing tracked has a reading yet — '
        'the nightly sync files them once articles are published</td></tr>')

    goal = p["goal"]
    if goal["declared"]:
        rows = "".join(
            f'<tr><td>{_esc(f.replace("_", " "))}</td>'
            f'<td class="num">{a["actual"]}</td><td class="num">{a["target"]}</td>'
            f'<td class="num">{a["pct"]}%</td></tr>'
            for f, a in goal["attainment"].items()) or (
            '<tr><td colspan="4" class="mut">a goal is set but nothing it '
            'names is measurable yet</td></tr>')
        goal_html = (f'<table class="tbl"><tr><th>goal</th><th>now</th>'
                     f'<th>target</th><th></th></tr>{rows}</table>'
                     f'<p class="when">Set {_esc(goal["declared"].get("set_at", ""))}'
                     f'. Change it below.</p>')
    else:
        goal_html = ('<p class="mut">No goal set, so nothing above has a bar to '
                     'clear. There is deliberately no default — a target nobody '
                     'chose is a target nobody can fail.</p>')

    form = (f'<form method="get" action="/admin/keywords_goal">'
            f'<input type="hidden" name="key" value="{_esc(key)}">'
            f'<input type="hidden" name="tenant" value="{_esc(tenant)}">'
            f'<input type="hidden" name="ui" value="1">'
            + "".join(
                f'<label>{lbl} <input name="{n}" size="7" value="'
                + _esc(str((goal["declared"] or {}).get(n, "")))
                + '"></label> '
                for n, lbl in (("organic_clicks", "monthly clicks"),
                               ("top3", "keywords in top 3"),
                               ("top10", "keywords in top 10"),
                               ("horizon_days", "over (days)")))
            + '<button type="submit">Set the goal</button></form>')

    notes = "".join(f'<p class="mut">{_esc(n)}</p>' for n in p["notes"])

    a = kw.aeo(tenant, days=days)
    cov, surf = a["coverage"], a["question_surface"]
    flags = "".join(
        f'<tr><td>{_esc(f["phrase"])}</td>'
        f'<td class="num">{f["position"]}</td>'
        f'<td class="num">{f["ctr"]}%</td>'
        f'<td class="num">{f["band_median_ctr"]}%</td>'
        f'<td class="num">{f["impressions"]}</td></tr>'
        for f in a["answer_taken"]["flagged"]) or (
        '<tr><td colspan="5" class="mut">nothing flagged — '
        + _esc(" · ".join(a["answer_taken"]["bands"].values()) or "no readings yet")
        + '</td></tr>')

    aeo_html = f"""
    <h3>Answer engines</h3>
    <p><strong>{cov["answered"]}</strong> of <strong>{cov["questions_in_map"]}</strong>
       question(s) in the map are answered · {cov["planned"]} planned ·
       {cov["unanswered"]} not yet written</p>
    <p>Question-shaped queries: <strong>{surf["now"]["clicks"]}</strong> click(s)
       from {surf["now"]["impressions"]} impression(s)
       {("(" + str(surf["change"]["clicks_pct"]) + "% vs before)")
        if surf["change"]["clicks_pct"] is not None else ""}</p>
    <table class="tbl">
      <tr><th>ranking well, not being clicked</th><th>position</th><th>CTR</th>
          <th>median at this rank</th><th>impressions</th></tr>
      {flags}
    </table>
    <p class="when">{_esc(a["answer_taken"]["means"])} The comparison is against
    <em>this account's own</em> keywords at similar positions — not a published
    CTR curve, which would be somebody else's sample standing in for a
    measurement.</p>
    <p class="mut">{_esc(a["not_measured"])}</p>"""

    return f"""
    <h3>Progress</h3>
    {notes}
    {compare}
    <p><strong>{p["wins"]["top3"]}</strong> keyword(s) ranking 1–3 ·
       <strong>{p["wins"]["top10"]}</strong> in the top 10 ·
       {p["attributable"]} attributable, {p["too_early_to_attribute"]} too
       recent to claim</p>
    <table class="tbl">
      <tr><th>keyword</th><th>tier</th><th>was</th><th>now</th><th>gain</th>
          <th>clicks</th><th>published</th></tr>
      {moves}
    </table>
    {aeo_html}
    <h3>The goal</h3>
    {goal_html}
    {form}"""


def _drafts_section(key: str, row) -> str:
    """This system's workroom index — every kept artifact, newest first.

    The third index that ends redirect-only artifacts (with Review's
    In-progress strip and the Plan board's links): the system that produced a
    thing is where you go looking for it a week later.
    """
    try:
        with db.SessionLocal() as s:
            arts = (s.query(db.ArtifactBody)
                    .filter(db.ArtifactBody.tenant == row.tenant,
                            db.ArtifactBody.system_key == row.key)
                    .order_by(db.ArtifactBody.created_at.desc())
                    .limit(8).all())
            total = (s.query(db.ArtifactBody)
                     .filter(db.ArtifactBody.tenant == row.tenant,
                             db.ArtifactBody.system_key == row.key).count())
            s.expunge_all()
    except Exception:                                            # noqa: BLE001
        arts, total = [], 0
    rows_html = ""
    for a in arts:
        held = (a.state or "") == "in_review"
        rows_html += (
            f'<div class="msg{"" if held else " gone"}">'
            f'<a href="/admin/work/{_esc(a.output_id)}?key={_esc(key)}">'
            f'{_esc((a.format or "artifact").replace("_", " "))} · '
            f'{_esc(str(a.created_at)[:16])}</a>'
            + (' <span class="chip off">in review</span>' if held else "")
            + f' <span class="when">{a.bytes or 0} bytes</span></div>')
    if not rows_html:
        rows_html = ('<p class="mut">Nothing produced yet. When a run makes '
                     'an artifact, it lands here with its workroom one click '
                     'away — never reachable only through a redirect.</p>')
    return f"""
<div class="anchor" id="drafts"></div>
<div class="card">
  <div class="head"><h2>Drafts — the workroom index</h2>
    <span class="chip nb">{total} kept</span></div>
  <div class="thread">{rows_html}</div>
</div>"""


def render_workroom(key: str, output_id: str, art, kw, ap,
                    ok: str = "", err: str = "") -> str:
    """One artifact's home: preview, edit, feedback, history — the work loop.

    Absorbs /admin/article's page (owner, on that page: "some weird edit
    screen that can only be accessed as a redirect but doesn't get stored
    anywhere, to edit later and doesn't give an option for feedback loops")
    and keeps its three earned properties verbatim: what was reviewed is what
    publishes; the ban list binds the owner too; the draft survives the edit.
    What it adds is the loop those properties deserved: Save-for-later with
    an index that can find it again, a version history whose v1 is the frozen
    draft, and a feedback rail whose three levels each land in a real channel
    — this draft, this system's prompt, or the validator — at filing time.
    """
    from . import artifact_check, edits

    tenant = art.tenant or ""
    syskey = art.system_key or ""
    fields = (ap.payload or {}).get("fields", {}) if ap else {}
    published = bool(kw and (kw.status or "") in ("published", "won"))
    title = fields.get("title") or (kw.phrase if kw else "") or "Artifact"

    with db.SessionLocal() as s:
        versions = (s.query(db.ArtifactVersion)
                    .filter(db.ArtifactVersion.output_id == output_id)
                    .order_by(db.ArtifactVersion.n).all())
        fb = (s.query(db.FeedbackItem)
              .filter(db.FeedbackItem.output_id == output_id)
              .order_by(db.FeedbackItem.created_at.desc()).all())
        run = s.get(db.SystemRun, art.run_id) if art.run_id else None
        out = s.get(db.Output, output_id)
        s.expunge_all()

    # A campaign email reviews differently from an article: iframe previews
    # instead of inline HTML, subject/preheader adjustable pre-push instead
    # of a body editor (email HTML is fragile; blocks get redrafted, not
    # hand-edited), and the decide bar's consequence is the ESP push itself
    # — under review-before-push, NOTHING sits in a client's platform until
    # the approval here says so.
    is_email = (art.format or "") == "campaign_email"
    esp_push = ((ap.payload or {}).get("esp_push") or {}) if ap else {}
    dest = getattr(out, "destination", "") or ""
    pushed = ":campaign/" in dest
    superseded_by = (dest.split("superseded:", 1)[1]
                     if dest.startswith("superseded:") else "")

    # An ad BATCH reviews differently again (3.4): the artifact is a set —
    # JSON of 1–5 variants — so the preview is a board of cards, each with
    # its own edit / feedback / drop, the decide bar resolves every
    # variant's approval in one gesture, and Request-changes regenerates in
    # place (kept variants survive; the board never supersedes as a page,
    # which is why variant-level supersession uses its own destination
    # vocabulary that the `superseded:` parse above deliberately misses).
    is_ads = (art.format or "") == "ad_batch"
    batch = None
    ad_apr = {"pending": 0, "ready": 0, "denied": 0}
    if is_ads:
        import json as _json
        title, kw_line = "Ad batch", "the batch record is unreadable"
        try:
            batch = _json.loads(art.body or "")
            if not isinstance(batch.get("variants"), list) \
                    or not batch["variants"]:
                batch = None
        except Exception:                                        # noqa: BLE001
            batch = None
        if batch is not None:
            _ids = {str(v.get("output_id") or "") for v in batch["variants"]}
            with db.SessionLocal() as s:
                for a in (s.query(db.Approval)
                          .filter(db.Approval.tenant == tenant).all()):
                    if str((a.payload or {}).get("output_id") or "") in _ids:
                        if a.status == "pending":
                            ad_apr["pending"] += 1
                        elif a.status in ("approved", "executed"):
                            ad_apr["ready"] += 1
                        elif a.status == "denied":
                            ad_apr["denied"] += 1
            title = ("Ad batch — "
                     + (batch.get("entity_label")
                        or batch.get("entity_key") or "the brand")
                     + " × " + (batch.get("audience_key") or "everyone"))
            _n_live = sum(1 for v in batch["variants"]
                          if not v.get("dropped"))
            kw_line = (f'{_n_live} of {len(batch["variants"])} variant(s) '
                       f'riding · '
                       f'<a href="/admin/ui?key={_esc(key)}&amp;tab=systems&amp;'
                       f'tenant={_esc(tenant)}&amp;system=ad_creative">its '
                       f'system</a>')

    # --- the lifecycle, as chips: where this artifact IS ------------------
    def _chip(label: str, on: bool) -> str:
        return f'<span class="chip {"on" if on else "nb"}">{label}</span>'
    if is_ads:
        # A batch's last chip is READY, not published — its declared ship
        # marks it ready and a person carries it to the platform; claiming
        # "published" would claim a write that does not exist.
        steps = (_chip("drafted", True)
                 + _chip("in review", bool(versions))
                 + _chip("awaiting approval", ad_apr["pending"] > 0)
                 + _chip("ready", ad_apr["pending"] == 0
                         and ad_apr["ready"] > 0))
    else:
        steps = (_chip("drafted", True)
                 + _chip("in review", (art.state or "") == "in_review"
                         or bool(versions))
                 + _chip("awaiting approval", bool(ap))
                 + _chip("published", published))
    measured = ""
    if run is not None and getattr(run, "edit_diff", None):
        d = run.edit_diff or {}
        measured = _chip(
            "measured — " + ("sent as-is" if d.get("as_is") else "edited"),
            True)

    # --- decide bar (moved from web.py, restyled; same consequences) ------
    if is_ads:
        # HONEST BY CONTRACT (spec §3c): approve marks the batch ready — its
        # declared ship — and nothing else. No ad-platform write is wired,
        # and this bar says so in every state rather than implying a launch.
        ship_note = ('<span class="when">Approving marks the batch ready — '
                     'that is its whole ship: <b>no ad-platform write is '
                     'wired</b>, the copy leaves by hand, and launching '
                     'stays yours in the platform.</span>')
        if batch is None:
            decide = ('<div class="bad">The batch record is unreadable — '
                      'nothing here can be decided. The raw source link '
                      'below still shows what is stored.</div>')
        elif ad_apr["pending"]:
            _n_drop = sum(1 for v in batch["variants"] if v.get("dropped"))
            decide = (f'<form class="row" method="post" '
                      f'action="/admin/ad_batch_decide">'
                      f'<input type="hidden" name="key" value="{_esc(key)}">'
                      f'<input type="hidden" name="output_id" '
                      f'value="{_esc(output_id)}">'
                      f'<button type="submit" name="verdict" value="approve">'
                      f'Approve batch — {_n_live} kept variant(s) ready'
                      f'</button> '
                      f'<button type="submit" name="verdict" value="deny" '
                      f'class="sec">Deny batch</button> '
                      + (f'<span class="chip nb">{_n_drop} dropped — denied '
                         f'on approve</span> ' if _n_drop else "")
                      + ship_note + "</form>")
        elif ad_apr["ready"]:
            decide = (f'<div class="ok">Batch ready — {ad_apr["ready"]} '
                      f'variant(s) approved. No ad-platform write is wired: '
                      f'the copy ships by hand, and launching stays yours '
                      f'in the platform.</div>')
        elif ad_apr["denied"]:
            decide = ('<div class="note">Denied — nothing on this board '
                      'rides. A regenerate with feedback starts it over.'
                      '</div>')
        else:
            decide = ('<div class="note">No approval was asked — this run '
                      'filed as <code>'
                      + _esc(getattr(out, "status", "") or "recorded")
                      + '</code> at its autonomy rung. ' + ship_note
                      + '</div>')
    elif is_email:
        prov = esp_push.get("provider") or "the ESP"
        if ap:
            from . import approvals
            approve = "/decide/" + approvals._signer.dumps([ap.id, "approved"])
            deny = "/decide/" + approvals._signer.dumps([ap.id, "denied"])
            decide = (f'<div class="row"><a class="btn" href="{approve}">'
                      f'Approve — pushes the draft to {_esc(prov)}, '
                      f'launch-ready</a> <a class="btn danger" href="{deny}">'
                      f'Deny</a> <span class="when">Nothing reaches '
                      f'{_esc(prov)} until you approve. Review and adjust '
                      f'here; launch there.</span></div>')
        elif pushed:
            decide = (f'<div class="ok">In {_esc(dest.split(":")[1])} as a '
                      f'draft — campaign '
                      f'{_esc(dest.split(":campaign/")[-1])}. Launching stays '
                      f'yours, in the platform; the launch-time edit delta is '
                      f'measured.</div>')
        else:
            why = ""
            if run is not None and (run.decision or "") == "denied":
                why = "denied — it will not be pushed"
            decide = (f'<div class="note">Held in our store — no pending '
                      f'approval{" (" + why + ")" if why else ""}. A clean '
                      f'redraft re-queues one.</div>'
                      + (f'<form class="row" method="get" '
                         f'action="/admin/esp_push">'
                         f'<input type="hidden" name="key" value="{_esc(key)}">'
                         f'<input type="hidden" name="output_id" '
                         f'value="{_esc(output_id)}">'
                         f'<button class="sec">Push to {_esc(prov)} now'
                         f'</button><span class="when">the retry for an '
                         f'approved push that failed — never the first '
                         f'path</span></form>'
                         if (art.body or "").strip()
                         and run is not None
                         and (run.decision or "") == "approved" else ""))
    elif ap:
        from . import approvals
        approve = "/decide/" + approvals._signer.dumps([ap.id, "approved"])
        deny = "/decide/" + approvals._signer.dumps([ap.id, "denied"])
        decide = (f'<div class="row"><a class="btn" href="{approve}">Approve '
                  f'&amp; publish</a> <a class="btn danger" href="{deny}">'
                  f'Deny</a> <span class="when">Approving publishes THIS text '
                  f'— saving below updates what ships.</span></div>')
    elif published:
        live = (f' — <a href="{_esc(kw.target_url)}">live page</a>'
                if kw and kw.target_url else "")
        decide = f'<div class="ok">Published{live}.</div>'
    else:
        decide = f"""
        <form class="row" method="get" action="/admin/article_published">
          <input type="hidden" name="key" value="{_esc(key)}">
          <input type="hidden" name="output_id" value="{_esc(output_id)}">
          <b>No CMS to push to.</b>
          <span class="when">Copy the source, paste it into the platform by
          hand, then record where it went live so the measurement loop can
          see it:</span>
          <input name="url" size="42" placeholder="https://…/blogs/…">
          <button type="submit" class="sec">It&rsquo;s live here</button>
        </form>"""

    if superseded_by:
        # A replaced draft is a record, not a workspace — every decision and
        # adjustment belongs to its successor.
        decide = (f'<div class="note"><b>Superseded by a redraft.</b> This '
                  f'version was sent back and replaced; it stays readable, '
                  f'and everything decidable lives on '
                  f'<a href="/admin/work/{_esc(superseded_by)}?key={_esc(key)}">'
                  f'the current draft &rarr;</a></div>')

    # The structural check reads rendered artifacts; a batch is a JSON
    # record, and flags computed over it would be findings about brackets.
    flags = [] if is_ads else artifact_check.check(art.body or "")
    flag_html = "".join(
        f'<li><code>{_esc(f["rule"])}</code> {_esc(f["detail"])} — '
        f'<em>{_esc(f["fix"])}</em></li>' for f in flags)
    if not is_ads:
        # The board sets its own byline above — a batch has no keyword and
        # "no keyword joined" would read as a gap instead of a fact.
        kw_line = (f'for <b>{_esc(kw.phrase)}</b> ({_esc(kw.role or "")}, '
                   f'{_esc(kw.status or "")}) · '
                   f'<a href="/admin/ui?key={_esc(key)}&amp;tab=plan&amp;'
                   f'tenant={_esc(tenant)}">its Plan row</a>'
                   if kw else "no keyword joined")

    def _inp(name, label, value, size=60):
        return (f'<label style="display:block;margin:6px 0">{label}<br>'
                f'<input name="{name}" size="{size}" '
                f'value="{_esc(value or "")}"></label>')

    # --- versions: v1 is the frozen draft, rows are what changed it -------
    vs_rows = (f'<div class="msg"><b>v1</b> — the draft, as the machine wrote '
               f'it <span class="when">{len(art.draft_body or "")} chars · '
               f'frozen at emit</span></div>')
    for v in versions:
        vs_rows += (f'<div class="msg"><b>v{v.n}</b> — {_esc(v.author)}'
                    + (f' · {_esc(v.note)}' if v.note else "")
                    + f' <span class="when">{_esc(str(v.created_at)[:16])} · '
                      f'{len(v.body or "")} chars</span></div>')
    dsum = ""
    # Not for batches: a text diff of two JSON documents is noise — the
    # version notes ("variant 2 copy edited", "regenerated 1 of 1 …") tell
    # the same story in the board's own vocabulary.
    if not is_ads and (art.draft_body or "") \
            and (art.body or "") != (art.draft_body or ""):
        d = edits.delta(art.draft_body or "", art.body or "")
        dsum = (f'<p class="when">Draft vs current: '
                f'{"unchanged" if d.get("as_is") else "edited"}'
                + (f' — sample:</p><pre class="msg esc" style="white-space:'
                   f'pre-wrap">{_esc(str(d.get("sample") or "")[:1200])}</pre>'
                   if d.get("sample") else "</p>"))

    # --- preview + edit, by kind ------------------------------------------
    src_link = (f'<p class="when"><a href="/admin/artifact/{_esc(output_id)}'
                f'?key={_esc(key)}&amp;raw=1">source</a></p>')
    if is_ads:
        if batch is None:
            preview_card = (f'<div class="card"><h3>The variant board</h3>'
                            f'<div class="bad">The batch record is '
                            f'unreadable — the raw source below is all '
                            f'there is.</div>{src_link}</div>')
        else:
            regen = batch.get("last_regenerate") or {}
            head_bits = (
                f'<span class="chip nb">entity</span> '
                f'{_esc(batch.get("entity_label") or batch.get("entity_key") or "the brand")} '
                f'<span class="chip nb">audience</span> '
                f'{_esc(batch.get("audience_key") or "everyone")}'
                + (f' <span class="chip off">{batch["blocked_at_emit"]} '
                   f'blocked at the gates</span>'
                   if batch.get("blocked_at_emit") else "")
                + (f' <span class="chip nb">last regenerate: '
                   f'{regen.get("cleared", 0)} of {regen.get("asked", 0)} '
                   f'cleared</span>' if regen else ""))
            vcards = ""
            for v in batch["variants"]:
                n = v.get("n")
                dropped = bool(v.get("dropped"))
                basis = str(v.get("basis") or "")
                chips = f'<span class="chip nb">{_esc(str(v.get("angle") or ""))}</span> '
                if v.get("needs_art_direction"):
                    # The flag nobody could see (spec §3c) — an amber chip
                    # per variant instead of JSON in a run detail.
                    chips += '<span class="chip off">needs art direction</span> '
                if basis and basis != "model":
                    chips += (f'<span class="chip off" title="{_esc(basis)}">'
                              f'composed fallback — not ad copy</span> ')
                if dropped:
                    chips += '<span class="chip nb">dropped</span> '
                claim_line = (f'<div class="when">built on: '
                              f'&ldquo;{_esc(str(v.get("claim") or "")[:180])}'
                              f'&rdquo;</div>'
                              if v.get("claim") else "")
                if dropped:
                    act_forms = f"""
      <form method="post" action="/admin/ad_variant_drop" class="row">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="output_id" value="{_esc(output_id)}">
        <input type="hidden" name="n" value="{n}">
        <input type="hidden" name="act" value="restore">
        <button type="submit" class="sec">Restore</button>
        <span class="when">dropped — Regenerate replaces it; approving the
        batch denies it</span>
      </form>"""
                else:
                    act_forms = f"""
      <form method="post" action="/admin/ad_variant_save">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="output_id" value="{_esc(output_id)}">
        <input type="hidden" name="n" value="{n}">
        <textarea name="text" rows="3" style="width:100%;font-family:var(--mono)">{_esc(str(v.get("text") or ""))}</textarea>
        <div class="row">
          <button type="submit" class="sec">Save copy</button>
          <span class="when">ban-gated — a banned phrase refuses, whoever
          typed it</span>
        </div>
      </form>
      <form method="post" action="/admin/feedback_add" class="row">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="output_id" value="{_esc(output_id)}">
        <input type="hidden" name="system_key" value="{_esc(syskey)}">
        <input type="hidden" name="part" value="variant {n}">
        <input type="hidden" name="level" value="draft">
        <input name="note" placeholder="what&rsquo;s wrong with this one — rides the next regenerate" style="flex:1;min-width:220px">
        <button type="submit" class="sec">File feedback</button>
      </form>
      <form method="post" action="/admin/ad_variant_drop" class="row">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="output_id" value="{_esc(output_id)}">
        <input type="hidden" name="n" value="{n}">
        <button type="submit" class="sec">Drop</button>
        <span class="when">a judgement, not a delete — it stays here, greyed,
        until a regenerate replaces it</span>
      </form>"""
                vcards += (f'<div class="msg{" gone" if dropped else ""}">'
                           f'<div class="row"><b>Variant {n}</b> {chips}'
                           f'</div>{claim_line}{act_forms}</div>')
            preview_card = (f'<div class="card"><h3>The variant board</h3>'
                            f'<div class="row">{head_bits}</div>'
                            f'<div class="thread">{vcards}</div>'
                            f'{src_link}</div>')
        # Per-variant editors live on the cards; a whole-body editor over
        # the batch JSON would invite hand-breaking the record.
        edit_card = ""
    elif is_email:
        srcdoc = _esc(art.body or "")
        plain = _re.sub(r"<[^>]+>", " ", art.body or "")
        plain = _re.sub(r"\s+", " ", plain).strip()
        seg_note = (f'{_esc(esp_push.get("segment_key") or "—")}'
                    + (" · bound in the ESP" if esp_push.get("segment_id")
                       else " · NOT bound in the ESP yet — it would go to "
                            "the platform default"))
        preview_card = f"""
<div class="card">
  <h3>Preview — as the ESP will receive it</h3>
  <div class="row">
    <span class="chip nb">subject</span> {_esc(esp_push.get("subject") or "—")}
    <span class="chip nb">preheader</span> {_esc(esp_push.get("preheader") or "—")}
    <span class="chip nb">segment</span> {seg_note}
  </div>
  <iframe sandbox="" srcdoc="{srcdoc}" style="width:100%;height:520px;
    border:1px solid var(--rule);border-radius:6px;background:#fff"></iframe>
  <details class="sec"><summary>Phone width (360px)</summary>
    <iframe sandbox="" srcdoc="{srcdoc}" style="width:360px;max-width:100%;
      height:560px;border:1px solid var(--rule);border-radius:6px;
      background:#fff"></iframe></details>
  <details class="sec"><summary>Plain text</summary>
    <pre class="msg" style="white-space:pre-wrap">{_esc(plain[:4000])}</pre>
  </details>
  {src_link}
</div>"""
        # No body editor for email: the HTML is a rendered artifact of the
        # blocks contract, hand-editing it is how emails break in clients —
        # blocks get redrafted, not retyped. Subject and preheader ARE
        # editable, because the push reads them from the approval this form
        # writes: adjustment happens in our data layer, not in the ESP.
        edit_card = (f"""
<div class="card">
  <h3>Adjust before the push</h3>
  <form method="post" action="/admin/campaign_meta_save">
    <input type="hidden" name="key" value="{_esc(key)}">
    <input type="hidden" name="output_id" value="{_esc(output_id)}">
    {_inp("subject", "Subject", esp_push.get("subject", ""), 70)}
    {_inp("preheader", "Preheader", esp_push.get("preheader", ""), 90)}
    <div class="row">
      <button type="submit" class="sec">Save — the push uses exactly this</button>
      <span class="when">checked against {_esc(tenant)}&rsquo;s ban list —
      a banned phrase refuses, whoever typed it</span>
    </div>
  </form>
</div>""" if ap else "")
    else:
        preview_card = f"""
<div class="card">
  <h3>Preview</h3>
  <div style="border:1px solid var(--rule);padding:18px 22px;border-radius:6px;background:#fff;color:#15171d">
  {art.body or ""}</div>
  {src_link}
</div>"""
        edit_card = f"""
<div class="card">
  <h3>Edit</h3>
  <form method="post" action="/admin/article_save">
    <input type="hidden" name="key" value="{_esc(key)}">
    <input type="hidden" name="output_id" value="{_esc(output_id)}">
    {_inp("title", "Title", fields.get("title", ""))}
    {_inp("seo_title", "SEO title (60)", fields.get("seo_title", ""))}
    {_inp("seo_description", "Meta description (155)",
          fields.get("seo_description", ""), 90)}
    <label style="display:block;margin:6px 0">Body (HTML)<br>
    <textarea name="body" rows="22" style="font-family:var(--mono)"
    >{_esc(art.body or "")}</textarea></label>
    <div class="row">
      <button type="submit" name="action" value="save">Save changes</button>
      <button type="submit" name="action" value="later" class="sec"
        title="Keeps your edits and holds this In review — it appears on the Review tab's In-progress strip until you finish">Save for later</button>
      <span class="when">Saves are checked against {_esc(tenant)}&rsquo;s ban
      list — a banned phrase refuses, whoever typed it.</span>
    </div>
  </form>
</div>"""

    # Feedback parts follow the artifact's anatomy: an email's judgement
    # lands on a block, not a paragraph number — and a batch's on a variant.
    if is_ads:
        parts = (["overall"]
                 + [f"variant {v.get('n')}"
                    for v in (batch or {}).get("variants") or []])
    elif is_email:
        shape = list(getattr(out, "shape", None) or [])[:10]
        parts = (["overall", "subject", "preheader", "hero"]
                 + [f"block {i + 1} · {str(k)[:16]}"
                    for i, k in enumerate(shape)]
                 + ["footer"])
    else:
        parts = ["overall", "title", "seo", "meta", "body"]
    part_opts = "".join(f"<option>{_esc(p)}</option>" for p in parts)

    plan_fold = ""
    if is_email and run is not None and isinstance(
            getattr(run, "brief", None), dict):
        rows_ = "".join(
            f"<dt>{_esc(k)}</dt><dd>{_esc(str(v))}</dd>"
            for k, v in list(run.brief.items())[:12] if k != "edited")
        plan_fold = (
            '<details class="sec"><summary>The plan behind this send'
            f'</summary><dl class="kv">{rows_}</dl>'
            '<p class="when">Subject and preheader adjust above and flow '
            'into the push. A different segment, entity, intent or angle: '
            'adjust it in Request changes below — the redraft runs against '
            'the adjusted plan, through every gate.</p></details>')

    # --- Request changes: the redraft, fed by the filed feedback ----------
    open_draft_fb = [f for f in fb
                     if f.level == "draft" and f.status == "open"]
    redraft_card = ""
    if ((art.body or "").strip() and not pushed and not published
            and not superseded_by):
        if is_ads:
            ov_fields = (
                _plan_field_input({"key": "entity_key", "kind": "entity",
                                   "label": "Entity"},
                                  (batch or {}).get("entity_key") or "",
                                  tenant=tenant)
                + _plan_field_input({"key": "audience_key",
                                     "label": "Audience key"},
                                    (batch or {}).get("audience_key") or "",
                                    tenant=tenant))
        elif is_email:
            ov_fields = (
                _plan_field_input({"key": "segment", "kind": "segment",
                                   "label": "Segment"},
                                  esp_push.get("segment_key")
                                  or getattr(out, "audience_key", "") or "",
                                  tenant=tenant)
                + _plan_field_input({"key": "entity_key", "kind": "entity",
                                     "label": "Featured entity"},
                                    getattr(out, "entity_key", "") or "",
                                    tenant=tenant)
                + _plan_field_input({"key": "intent", "kind": "choice",
                                     "label": "Intent",
                                     "choices": ["story", "education",
                                                 "proof", "offer"]},
                                    getattr(out, "situation", "") or "",
                                    tenant=tenant)
                + _plan_field_input({"key": "deadline",
                                     "label": "Deadline — the only licit "
                                              "urgency"}, "", tenant=tenant)
                + _plan_field_input({"key": "goal",
                                     "label": "Angle / concept"}, "",
                                    tenant=tenant))
        else:
            ov_fields = (
                _plan_field_input({"key": "angle", "label": "Angle"},
                                  getattr(out, "angle", "") or "",
                                  tenant=tenant)
                + _plan_field_input({"key": "entity_key", "kind": "entity",
                                     "label": "Featured entity"},
                                    getattr(out, "entity_key", "") or "",
                                    tenant=tenant))
        fb_line = (f"{len(open_draft_fb)} open feedback item(s) will be "
                   f"consumed" if open_draft_fb else
                   "no open feedback filed — the note below is the whole "
                   "instruction")
        if is_ads:
            _n_dropped = sum(1 for v in (batch or {}).get("variants") or []
                             if v.get("dropped"))
            _rc_title = "Request changes — regenerate on this board"
            _rc_btn = "Regenerate with feedback"
            _rc_how = ((f"replaces the {_n_dropped} dropped variant(s), "
                        f"kept ones survive verbatim" if _n_dropped else
                        "nothing is dropped, so the WHOLE batch is "
                        "redrafted — drop a variant first to keep the rest")
                       + " · runs fresh through every gate")
            _rc_ph = ("e.g. shorter lines, and stop opening every variant "
                      "with the brand name")
        else:
            _rc_title = "Request changes — redraft in our data layer"
            _rc_btn = "Redraft with this feedback"
            _rc_how = ("runs fresh through every gate · supersedes this "
                       "draft and re-queues the approval")
            _rc_ph = ("e.g. two products max, and lead with the "
                      "free-shipping line")
        redraft_card = f"""
<div class="card">
  <h3>{_rc_title}</h3>
  <form method="post" action="/admin/work_redraft">
    <input type="hidden" name="key" value="{_esc(key)}">
    <input type="hidden" name="output_id" value="{_esc(output_id)}">
    <label style="display:block;margin:6px 0">What must change<br>
    <textarea name="note" rows="3" placeholder="{_esc(_rc_ph)}"></textarea></label>
    <details class="sec"><summary>Adjust the plan for this redraft</summary>
      <div class="planfields">{ov_fields}</div>
    </details>
    <div class="row" style="margin-top:8px">
      <button type="submit">{_rc_btn}</button>
      <span class="when">{fb_line} · {_rc_how}</span>
    </div>
  </form>
</div>"""

    # --- the feedback rail ------------------------------------------------
    open_fb = "".join(
        f'<div class="msg"><b>{_esc(f.part)}</b> · {_esc(f.category or "—")} '
        f'· {_esc(f.note)} <span class="when">{_esc(f.level)} · '
        f'{_esc(f.status)}</span>'
        + (f' · <a href="/admin/feedback_drop?key={_esc(key)}&amp;id='
           f'{_esc(f.id)}&amp;output_id={_esc(output_id)}">dismiss</a>'
           if f.status == "open" else "")
        + '</div>' for f in fb) or (
        '<p class="mut">Nothing filed yet. Feedback filed here lands in a '
        'real channel the moment you save it — nothing goes into a box '
        'nobody reads.</p>')
    learned = systems.guidance_block(tenant, syskey) if syskey else ""

    body_html = f"""
{f'<div class="flash"><div class="ok">{_esc(ok)}</div></div>' if ok else ""}
{f'<div class="flash"><div class="bad">{_esc(err)}</div></div>' if err else ""}
<div class="crumb"><a href="/admin/ui?key={_esc(key)}&amp;tab=content&amp;tenant={_esc(tenant)}&amp;sub=ship">&larr; Review</a> ·
  <a href="/admin/ui?key={_esc(key)}&amp;tab=plan&amp;tenant={_esc(tenant)}">&larr; Plan</a></div>
<div class="card">
  <div class="head"><h2>{_esc(title)}</h2><code>{_esc(syskey or "artifact")}</code>
    <span class="mut">{kw_line}</span></div>
  <div class="row">{steps}{measured}</div>
  {decide}
</div>
{f'<div class="card"><h3>Structural flags</h3><ul class="bl">{flag_html}</ul></div>' if flag_html else ""}
{preview_card}
{edit_card}
<div class="anchor" id="feedback"></div>
<div class="card">
  <h3>Feedback — where should this lesson land?</h3>
  <form method="post" action="/admin/feedback_add">
    <input type="hidden" name="key" value="{_esc(key)}">
    <input type="hidden" name="output_id" value="{_esc(output_id)}">
    <input type="hidden" name="system_key" value="{_esc(syskey)}">
    <div class="row">
      <select name="part" style="width:auto">{part_opts}</select>
      <select name="category" style="width:auto"><option value="">category…</option>
        <option>tone</option><option>length</option><option>format</option>
        <option>factual</option><option>brand</option><option>layout</option></select>
      <input name="note" placeholder="the judgement, in one line — for rule level, the exact phrase to ban" style="flex:1;min-width:260px">
    </div>
    <div class="row" style="margin-top:6px">
      <label class="pick"><input type="radio" name="level" value="draft" checked>
        fix this draft <span class="when">— stays open, rides the next redraft</span></label>
      <label class="pick"><input type="radio" name="level" value="system">
        teach this system <span class="when">— standing guidance, injected into every future draft</span></label>
      <label class="pick"><input type="radio" name="level" value="rule">
        make it a rule <span class="when">— the validator blocks it forever</span></label>
      <button type="submit" class="sec">File it</button>
    </div>
  </form>
  <div class="thread">{open_fb}</div>
</div>
{redraft_card}
{plan_fold}
{f'<details class="sec"><summary>What this system has learned from you</summary><pre class="msg" style="white-space:pre-wrap">{_esc(learned)}</pre></details>' if learned else ""}
<details class="sec"><summary>Versions — v1 is the frozen draft ({1 + len(versions)})</summary>
  <div class="thread">{vs_rows}</div>{dsum}
</details>"""
    return _shell(key, "content", title, body=body_html, tenant=tenant)


def render_plan(key: str, tenant: str = "", msg: str = "", err: str = "",
                pick: bool = False, days: int = 28, probe: bool = False) -> str:
    """The keyword plan the blog is built from.

    STATE BEFORE INSTRUCTIONS, which is the rule this page was missing
    entirely: the map lived in `/admin/keywords` as JSON and the console had
    no idea it existed, so planning an article meant typing a keyword in by
    hand — the one thing the map is for.

    Read top to bottom it answers, in order: can this account do this at all,
    what is the plan, and what would you like to do about it. The readiness
    strip is first because every other section is meaningless if publishing or
    measuring is broken, and each red verdict carries ITS OWN fix rather than
    sending you to a page that explains all four.
    """
    from . import keywords as kw

    tenant, here, _rows = _account(tenant)
    if tenant == ALL:
        return _shell(key, "plan", "Plan", tenant=tenant,
                      body=_every_note(True, "A keyword plan belongs to one "
                                       "site — head terms, clusters and "
                                       "positions are all per-domain."))

    def _link(route: str, **over) -> str:
        # `ui=1` is what makes these buttons and not API calls: the route
        # comes back to this page with a sentence, instead of leaving the
        # owner looking at raw JSON with no way back.
        q = {"key": key, "tenant": tenant, "ui": 1}
        q.update(over)
        return f"/admin/{route}?" + "&amp;".join(f"{k}={_esc(v)}" for k, v in q.items())

    # `probe=False` — this page renders on every visit and a live Search
    # Console round trip per load would make the console feel broken on a slow
    # morning. The real probe is /health/blog, and the strip says which it did.
    # Not probed on every visit — a live Search Console round trip per page
    # load makes the console feel broken on a slow morning — but one click
    # away, and honest about not having asked.
    ready = kw.readiness(tenant, probe=probe)
    chips = ""
    # THE TWO THAT GATE PLANNING, first and alone. Publishing and measuring
    # are downstream of this page, not preconditions for it — see
    # `keywords.readiness`'s `can_plan`.
    for label, part, hint in (
            ("Switch", "switch", "installed and on"),
            ("Knows what to write", "knows_what_to_write", "map, claims, ban list")):
        got = ready.get(part) or {}
        # THREE STATES, not two. `ok is None` means nobody has asked — and a
        # tick for "we did not check" is the failure this whole strip exists
        # to prevent.
        raw_ok = got.get("ok")
        ok = raw_ok is True
        unknown = raw_ok is None
        # `fix` is a SENTENCE for the connection verdicts and a LIST for the
        # knowledge one, and `notes` is always a list. Normalise both rather
        # than assuming either shape — concatenating them blind was a
        # TypeError that took down every page in the console, not just this
        # section.
        def _lines(v) -> list:
            if not v:
                return []
            return list(v) if isinstance(v, (list, tuple)) else [str(v)]
        fix = "; ".join(_lines(got.get("fix")) + _lines(got.get("notes")))
        detail = got.get("detail") or ("ready" if ok else "")
        extra = ""   # publish/measure controls now live with their lines
        if part == "knows_what_to_write" and any(
                "market not set" in n for n in (got.get("notes") or [])):
            # The advisory said "Set analytics.semrush_db to change it" — an
            # instruction whose only write path was the raw-JSON field on
            # Connections. The control now lives where the fact is stated.
            extra += (
                f'<form method="get" action="/admin/market_set" '
                f'style="margin-top:6px">'
                f'<input type="hidden" name="key" value="{_esc(key)}">'
                f'<input type="hidden" name="tenant" value="{_esc(tenant)}">'
                f'<input type="hidden" name="ui" value="1">'
                f'<input name="market" size="6" placeholder="us">'
                f'<button type="submit" class="sec">Set market</button></form>')
        if part == "switch" and not ok and got.get("system_id"):
            # ACT WHERE YOU REPORT, again. "turn it on to run" with no way to
            # turn it on is an instruction, not a control.
            # `back=plan`: the redirect returns to THIS page — system_set
            # used to land on the all-accounts Systems list with the tenant
            # dropped, and refuse with raw JSON.
            extra = (f'<p><a href="/admin/system_set?key={_esc(key)}'
                     f'&amp;id={_esc(got["system_id"])}&amp;status=live'
                     f'&amp;back=plan&amp;tenant={_esc(tenant)}">'
                     f'<button type="button">Turn it on</button></a></p>')
        chips += (
            f'<div class="card {"" if ok else "warn"}">'
            f'<div class="lbl">{"✓" if ok else ("?" if unknown else "!")} '
            f'{_esc(label)}</div>'
            f'<div class="big">{_esc(str(detail) or ("ready" if ok else "not ready"))}</div>'
            f'<p class="when">{_esc(fix or hint)}</p>{extra}</div>')

    # Stated, not gated. What happens to an article after it is written, on
    # one line, where it informs rather than blocks.
    down = ready.get("downstream") or {}
    _pub, _meas = down.get("publish") or {}, down.get("measure") or {}

    def _line(name, got, control=""):
        """One downstream verdict, WITH the control that resolves it.

        The control travels with the verdict rather than staying behind on a
        chip. Moving publish and measure out of the strip took the blog-id
        picker and the Search Console check down with them — the two buttons
        that answer the two lines — which the suite caught immediately. A fact
        and the thing that fixes it belong in the same place, which is the
        rule this page was built on.
        """
        mark = {True: "✓", None: "?"}.get(got.get("ok"), "!")
        why = got.get("fix") or ""
        why = "; ".join(why) if isinstance(why, list) else why
        return (f'<li>{mark} <strong>{name}</strong> — '
                f'{_esc(str(got.get("detail") or ""))}'
                + (f' <span class="when">{_esc(why)}</span>'
                   if got.get("ok") is not True else "")
                + control + '</li>')

    _check_gsc = ""
    if _meas.get("ok") is None:
        _check_gsc = (f' <a href="/admin/ui?key={_esc(key)}&amp;tab=plan'
                      f'&amp;tenant={_esc(tenant)}&amp;probe=1">'
                      f'<button class="sec" type="button">Check Search Console '
                      f'now</button></a>')
    _fix_blog = ""
    if _pub.get("ok") is not True and "blog_id" in str(_pub.get("detail", "")):
        _fix_blog = " " + _blog_picker(key, tenant, pick)

    downstream_html = (
        '<h3>Once it is written</h3><ul style="margin:0;padding-left:18px">'
        + _line("Publishing", _pub, _fix_blog)
        + _line("Measuring", _meas, _check_gsc)
        + '</ul><p class="when">Neither stops you planning. An account with no '
        'CMS can still build a map, rank it and decide what to write — the '
        'articles just need somewhere to go before they go there.</p>')

    m = kw.map_for(tenant)
    by_tier = m["by_tier"]
    tiers = " · ".join(f"{n} {t.replace('_', '-')}" for t, n in sorted(by_tier.items())) or "none"

    if not m["clusters"]:
        body_map = (
            '<p class="mut">No keyword map for this account yet — so there is '
            'nothing to plan an article against, and asking you to type a '
            'keyword is the system admitting it has not done its half.</p>'
            f'<p><a href="{_link("keywords_harvest")}"><button>Build the map'
            '</button></a> <span class="when">Reads Search Console for terms '
            'you already rank near, Semrush for the gap against competitors, '
            'and the questions people actually ask. Spends API calls.</span></p>')
    else:
        rows_html = ""
        for c in m["clusters"]:
            done = c["supports_published"]
            total = c["supports"]
            head = (f'{_esc(c["pillar"] or c["cluster"])}'
                    + ('' if c["pillar"] else ' <span class="mut">(no pillar)</span>'))
            state = ("pillar live" if c["pillar_published"] else "pillar not written")
            rows_html += (
                f'<tr class="grp"><td colspan="5"><strong>{head}</strong> '
                f'<span class="when">{_esc(state)} · {done}/{total} supports '
                f'published</span></td></tr>')
            for k in c["keywords"]:
                rows_html += (
                    f'<tr><td>{_esc(k["phrase"])}</td>'
                    f'<td>{_esc((k["tier"] or "").replace("_", "-"))}</td>'
                    f'<td>{_esc(k["role"])}</td>'
                    f'<td>{_esc(k["status"])}</td>'
                    f'<td class="num">{k["priority"] or 0:.0f}</td></tr>')
        body_map = f"""
        <table class="tbl">
          <tr><th>keyword</th><th>tier</th><th>role</th><th>status</th>
              <th>priority</th></tr>
          {rows_html}
        </table>"""

    actions = (
        f'<a href="{_link("keywords_propose")}"><button>Propose the next articles'
        '</button></a> '
        f'<a href="{_link("keywords_harvest")}"><button class="sec">Top up the map'
        '</button></a> '
        f'<a href="{_link("keywords_rescore")}"><button class="sec">Re-score'
        '</button></a>')

    # The one flash pattern every tab uses: sticky, so a redirect that lands
    # mid-page at an anchor cannot scroll the result out of view. Plan used
    # bare <p> tags for weeks — the confirmation scrolled away with the page.
    note = (f'<div class="ok">{_esc(msg)}</div>' if msg else "") + (
        f'<div class="bad">{_esc(err)}</div>' if err else "")
    if note:
        note = f'<div class="flash">{note}</div>'

    return _shell(key, "plan", "Plan", tenant=tenant, body=f"""
      {note}
      <div class="cards">{chips}</div>
      {_plan_window(key, tenant, days)}
      {_board_section(key, tenant, days)}
      <h3>The architecture — {m["keywords"]} keyword(s): {_esc(tiers)}</h3>
      {body_map}
      <p>{actions}</p>
      {downstream_html}
      {_progress_section(key, tenant, days)}
      <details><summary>How this decides what to write next</summary>
        <p class="when">A head term is never targeted with an article. It is
        targeted with a <strong>pillar</strong> page plus the long-tail
        <strong>supports</strong> that link into it, which is what makes
        ranking for a short phrase a build you can count rather than a hope.
        Priority is striking distance first — a page already sitting 11-20 is
        the biggest single lever, because Google already considers it relevant
        — then finishing a cluster over starting one, then demand weighted by
        intent, minus difficulty where it is known. A keyword already ranking
        1-3 scores nothing: rewriting a page that ranks is how a site loses the
        position it had.</p>
        <p class="when">"Propose the next articles" never plans a support
        before its pillar. Proposals land in Review as plans, and an article is
        drafted, checked against the ban list, and queued for your approval —
        nothing reaches the store until you approve it.</p>
      </details>""")
