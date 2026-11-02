---
name: gomeh-data-layer
description: Plan, write and analyse marketing work for Gomeh's accounts (baci, eien, coverings, ironside, agency) from the gomehagent data layer. Use whenever a session is asked what to make next, to draft a campaign email / blog article / ad copy / Google Business post for one of these brands, or to judge what has worked. The data layer is the `gomehagent` MCP server (tools get_plan, get_results, get_package, check, record, inbox_search, inbox_thread, inbox_draft). Also use it to answer customer and partner email for baci or eien.
---

# Working from the gomehagent data layer

Claude is the generator. The data layer holds the facts and the gates, and its
queue is where drafts go. You plan from it, write from it, check against it and
file into it. You never send, publish or push. Approving in the console is the
owner's act.

## 0. Is the server connected?

Look for the `gomehagent` (HTTP) or `gomehagent-local` (stdio) tools. If neither
is there, say so in one line, name the fix, and do not write from memory:

- **HTTP, the default.** `.mcp.json` in the repo points at the deploy. Export
  `MCP_KEY` (from the `assistant-env` group in Render) before starting Claude
  Code. For a cloud session, put `assistant-web-zm2d.onrender.com` on the
  environment's network allowlist and `MCP_KEY` in its environment variables.
- **stdio, on the owner's machine.** This needs no network path to the web
  service and no key:
  `claude mcp add gomehagent-local --env DATABASE_URL=<render external url> -- python3 -m app.mcp_stdio`

## 1. Plan: what is worth making

1. `get_plan(tenant)` returns systems and their health, open plans with dates,
   what is waiting on the owner, the knowledge-base gaps blocking a system, and
   why runs were blocked.
2. `get_results(tenant)` returns ad outcomes by positioning / audience / angle /
   entity / claim, what happened to every draft, the owner's verdicts, and
   which gates caught what.
3. Recommend in priority order and give the reason, which must come from those
   numbers. A gate that keeps catching the same rule is a data-layer fix (a
   missing claim or a vague audience), not a writing fix. Say which.

## 2. Write: one piece

1. `get_package(tenant, system, entity_key, audience_key)` gives you the brief.
   Write ONLY from it. A fact it does not carry is one you do not have, so
   leave it out. "What is missing" names the gaps; write around them.
2. Quote claims as written and keep their ids.
3. Match the exemplar's craft and the owner's notes. They are the standard.

## 3. Check, fix, file

1. `check(tenant, body, kind, subject, preheader, claim_ids, entity_key)`.
   Fix every block, then check again. Advice is yours to weigh; report it.
2. `record(...)` only once check is clean. Put in `notes` what you could not
   verify and what you left out. Hand the owner the `review_url`.
3. A blocked record queues nothing. Do not try to get around a block.

## 4. Email: answering a customer or partner (baci, eien)

1. `inbox_search(tenant, query, days)`, e.g. `from:silvia`, `is:unread`,
   `subject:shipping`. `last_is_ours: false` means nobody has answered yet.
2. `inbox_thread(tenant, thread_id)`: read all of it before writing.
3. For facts, use `get_package(tenant, ...)` (claims, products, the site's own
   pages). Stock, order status, prices and ship dates come from the thread or a
   tool, never from memory. If you don't have one, say so in the reply, or ask
   the owner.
4. `inbox_draft(tenant, thread_id, body)`: it lands in that inbox's Gmail
   Drafts, threaded. **It is never sent.** The owner reads and sends it. A
   banned phrase blocks the draft; fix it and draft again.
5. The tool picks the inbox from the account. Never mix accounts: a baci
   thread is answered through `baci` only.

## Brand guardrails (the package carries them too; these are never negotiable)

- **baci**: Italian-DESIGNED. Never "made in Italy".
- **eien**: no medical, disease or drug claims (no "GLP-1" mechanism claims).

## Do not

- Do not add generators, judges or prompt rules to the app (owner, 2026-10-22).
  Missing context means a new data-layer read, added to `app/mcp_server.py`
  with its reason and its suite check.
- Do not pass one account's facts into another's draft.
