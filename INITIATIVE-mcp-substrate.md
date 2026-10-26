# INITIATIVE — The substrate as an MCP server; Claude is the generator

> **THIS IS THE PLAN AND ITS RECORD.** Written 2026-10-26. `BUILD-STATE.md`
> remains the record of what exists; `/health` is the authority on what is
> deployed. §1 is a list of facts with `file:line`, each checkable in a minute.

## 0. The decision — read it before touching a generator

Owner, 2026-10-22, after a month of the email agent "constantly writing bad
drafts that I have to re-write" at a cost: **stop building generators inside
the app.** The data layer becomes an MCP server that scheduled automation
calls; Claude itself is the generator, handed context and data; drafts land in
the app's approval queue.

The evidence behind it: on 2026-10-02 one direct Claude session produced 16
Omnisend emails and a brand theme in 30 minutes and beat the whole layered
pipeline. What the pipeline lacked was never "Claude" — it already called
Claude. It was Sonnet 4.6 in ONE call, on a brief that cut each product at 600
characters, two audiences at 300, one objection, with nothing reading the
result back. What changed on Oct 2 was a capable model, the WHOLE package, a
loop with tools, and a check before anything was filed. The MCP is how a run
outside the app gets those four.

**Standing rule from here:** in any gomehagent thread, do not add a generator,
a judge, or a prompt rule inside the app. Build toward the MCP and the skill
files that call it. ARCHITECTURE.md's trust boundary holds unchanged — nothing
the server exposes acts outward.

## 1. What exists — v1, this commit

- `app/mcp_server.py` — the server. Three tools (`TOOLS`), the bearer wrapper
  (`_Bearer`), the mount (`mount`), the composed gates (`run_checks`).
- `app/handoff.py` `package_sections` — ONE builder of the brand package as
  markdown, shared by the job file (`for_job`) and `get_package`.
- `app/config.py` `MCP_KEY` — the credential; no default; unset refuses all.
  `render.yaml` declares it with `generateValue: true`.
- `app/web.py` — `/mcp` added as a Route (not a Mount: a Mount redirects the
  bare path and a POSTing client does not follow); `/health` says `mcp:
  keyed|unkeyed` keyless.
- `requirements.txt` — `mcp>=1.12,<2`.
- `scripts/test_the_substrate_is_an_mcp_server.py` — the suite (door, wire,
  package, gates, queue, trust boundary computed from `apply_decision`,
  restart). Mutation run: the bearer made to accept any token → two checks red.
- `scripts/mcp_smoke.py` — the official MCP client against a live uvicorn (or
  `MCP_URL`/`MCP_KEY` against a deploy): initialize, three tools, a call, a
  refused key.

## 2. The tools — the contract

| tool | reads | writes | refuses |
|---|---|---|---|
| `get_package(tenant, system, entity_key, audience_key)` | `resolve.resolve` via `handoff.package_sections`; `exemplars.standard` + `notes_text`; `handoff.DELIVER`/`RULES` | nothing | unknown account (names the known ones); unknown system |
| `check(tenant, body, kind, subject, preheader, headline, claim_ids, entity_key)` | `validator.check`, `artifact_check.check`, `email_craft`/`ad_craft.review`, `fitness.named_unfit`, `coherence.review` | nothing | — (a gate that raises is a BLOCK naming the gate) |
| `record(tenant, system, body, …, claim_ids, notes)` | runs `check` | `ledger.record` (+ `ArtifactBody` for artifact formats), `assurance.record(source="mcp")`, ONE `skill_output` approval when clean | unknown account/system; a blocked draft is filed blocked and queues NOTHING |

The package is the same document a failed job hands a chat, plus: "What is
missing" (the resolver's `blocked_on` and `gaps`, named), the exemplar the owner
last approved (the standard), and the owner's notes (taste, in their words).
Claims carry their ids; `check` and `record` take them back.

Nothing is sent, pushed or published by the server. Approving in the console
is the owner's act. `record` never writes an approval payload carrying a key
`approvals.apply_decision` executes (`esp_push`, `gbp_post`, `send_mail`); the
suite derives that set from the function's source and asserts equality.

## 3. Deliberately not here

- **ESP push on approve.** A skill-run email carries an `esp_push` binding the
  emit stashes on its approval; an MCP-recorded email does not, so approving it
  today means "reviewed" and the owner moves it. Phase 2 decides whether the
  binding is reconstructed or the skill pushes through the Omnisend connector
  Claude already has.
- **Products/photos, performance, exemplar-by-id tools.** The rule: a tool is
  added only after a skill needed it in a real session.
- **`run_skill`.** ARCHITECTURE.md queued it; the 2026-10-22 decision makes
  Claude the generator, so the server hands over the package and takes back
  the draft. Nothing here runs a generator.
- **OAuth.** A static bearer. Claude Code takes a header (`claude mcp add
  --transport http gomehagent <url>/mcp --header "Authorization: Bearer <key>"`).
  Whether claude.ai custom connectors accept a bearer header is UNVERIFIED —
  verify on first connect in Phase 2; if not, the OAuth resource-server path
  the SDK provides is the next step, not a key in the URL.

## 4. Phases

0. **Stop the bleed.** The campaign_email system's status → off on the Systems
   tab (`off` proposes nothing). The owner's press.
1. **This.** The server, the suite, the smoke, the deploy. Verify: keyless
   `/health` says `mcp: keyed`. If `unkeyed`, the blueprint sync did not add
   `MCP_KEY` to the existing env group — add it in the Render dashboard.
2. **One skill, three runs.** `baci-campaign-email` as a Claude skill file:
   get_package → draft → check → fix → record. Run three times in a thread with
   the owner watching; approvals file as exemplars. THIS IS ALSO THE TEST: the
   Oct 2 session had no data layer. If these three are not clearly better on
   corrections made, banned claims caught, buyer-language vs brand-language,
   the data layer needs content before it needs a schedule.
3. **Schedule it.** A Claude routine on the skill, drafts to the queue. Measure
   approval rate two weeks. Then blog, ads, GBP in the same shape; then
   `admin_ui` shrinks to the data-layer editor, the queue and connections.

## 5. How to connect

```
claude mcp add --transport http gomehagent https://assistant-web-zm2d.onrender.com/mcp \
  --header "Authorization: Bearer $MCP_KEY"
```

The key is `MCP_KEY` on the `assistant-env` group in Render. A connector that
gets 401 with "MCP_KEY is not set" is a deploy without the key; one that gets
401 with "present the deployment's MCP_KEY" has the wrong key.
