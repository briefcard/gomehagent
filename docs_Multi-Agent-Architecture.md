# Multi-Agent Platform — Architecture & Build Plan
*How to spin up new role-agents (Ad Manager, SEO, Content, Client-Inbox) on one shared base*
*Prepared for Gomeh Saias · June 12, 2026*

---

## The core idea: Kernel + Role, never a fork

Every agent is the **same kernel** wearing a different **role hat**. You never copy the codebase. The kernel holds everything universal; a role is a small config object that swaps three things — identity, tools, and policy. This is the single most important rule: *behavioral DNA lives in exactly one place.*

```
            ┌──────────────────────────────────────────┐
            │                 KERNEL                     │  (one codebase)
            │  • Agentic tool-use loop + prompt caching  │
            │  • Behavioral DNA (the rules below)        │
            │  • Memory: working memory, voice rules,    │
            │    conversation history, records, registry │
            │  • Learning loop: deny→rule, shared lessons│
            │  • Channels: WhatsApp/email, approvals     │
            │  • Usage/cost logging                       │
            └───────────────┬──────────────────────────┘
                            │ composes
        ┌───────────────────┼───────────────────┬───────────────────┐
        ▼                   ▼                   ▼                   ▼
   ROLE: Admin         ROLE: Ad Mgr        ROLE: SEO          ROLE: Content
   identity            identity            identity            identity
   tools: gmail,       tools: Google/      tools: Semrush,     tools: drafting,
   drive, shopify      Meta Ads, GA4       GSC, Ahrefs         Canva, CMS
   policy: imports     policy: budgets     policy: rankings    policy: brand
```

### Behavioral DNA (lives in the kernel, identical for every agent)
- **Proactivity / data-oriented foresight** — gather data → act → suggest next step → offer it.
- **Action confirmation** — never claim done without a tool confirming it.
- **Approval gating** — money and irreversible actions wait for the human.
- **Grounding** — facts only from tools/thread; no fabrication; no placeholders.
- **Clarify-before-bulk** — ask when a key parameter is ambiguous.
- **Big-task protocol** — acknowledge, be exhaustive, report coverage, close loops.
- **Context discipline** — recency anchoring, reply/quote resolution, memory.

These never change per role. An Ad Manager that doesn't confirm before claiming a campaign is live is as broken as an Admin that lies about sending an email. Same DNA.

---

## How to format a Role

A role is **data, not code** — a config object the kernel loads:

```python
Role(
  name        = "seo",
  identity    = "You are an SEO manager for {org}. You improve organic "
                "visibility through technical audits, keyword strategy, and "
                "content recommendations. You are rigorous and never claim a "
                "ranking change without GSC/Semrush data.",
  tools       = [semrush_keyword, semrush_audit, gsc_query, gsc_inspect,
                 drive_search, find_documents],          # ONLY the tools differ
  buckets     = {...},          # role-specific email categories (optional)
  policies    = {"auto_send": ["routine_status"], ...},
  models      = {"audit": "claude-opus-4-8"},            # heavy work → Opus
  accounts    = ["client_a", "client_b"],                # which inboxes/data
)
```

The kernel builds each agent's system prompt as:

```
[ KERNEL DNA RULES ]   ← cached, identical across all agents
+ [ ROLE IDENTITY ]    ← short, role-specific
+ [ SHARED LESSONS ]   ← cross-agent learning (see below)
+ [ ROLE LESSONS ]     ← this role's learned corrections
+ [ DYNAMIC CONTEXT ]  ← memory, records, date, recent exchange
```

Tools = `role.tools` (cached). That's the whole composition. Adding "Ad Manager" is writing one Role object and registering its tools — not touching the kernel.

---

## Not losing context / vital information

Three guarantees keep knowledge intact as you scale:

1. **One source of behavioral truth.** The DNA rules exist once in the kernel. Fixing a rule (or adding one, like today's reply-quote support) instantly applies to every agent. No drift, no "we fixed it in the admin agent but not the SEO agent."

2. **Shared data substrate, scoped access.** One Postgres. Tables carry an `agent`/`scope` column. Each agent sees its own memory, voice rules, and records — but the **document registry/catalog, contacts, and lessons are shared**, so a file the Admin agent filed is findable by the Content agent, and a contact one agent learned is known to all. The catalog Google Sheet is the human-and-AI-readable index across all of them.

3. **Role configs are versioned and reviewed.** Because a role is a config object, its full definition (identity, tools, policies) is in one readable place you can diff and audit — not scattered through prompt strings.

---

## Cross-agent learning (built today)

This is the part that makes the fleet smarter than any one agent. Two tiers:

- **Role-specific corrections** → stay as that agent's voice/handling rules (a deny on an Eien customer draft only affects Eien drafting).
- **Generalizable lessons** → promoted to a **shared Lessons store** that *every* agent reads. When you deny a draft and your reason contains a universal principle ("always verify before claiming done," "never fabricate a link," "confirm the destination before bulk moves"), it's saved globally. The next day the SEO agent, the Ad agent, and the Content agent all carry that lesson — they never have to make the same mistake to learn it.

**How it works now:** the deny-feedback loop auto-detects generalizable wording ("always/never/verify/confirm/every…") and writes it to the global Lessons table; all agents inject lessons into their prompt. You can also tell any agent "make this a lesson for all agents" explicitly.

**The compounding effect:** every correction you give *any* agent makes the *whole fleet* better at the universal behaviors. Role-specific taste stays local; hard-won judgment goes global. That's exactly the "learn from each other's mistakes" you asked for — and it's the moat: a fleet that's been corrected for months is far more reliable than a fresh one.

---

## Build sequence (recommended)

1. **Extract the kernel (refactor, ~1 focused pass).** Pull the DNA rules, memory, channels, and loop out of the current admin-specific code into a `kernel` module; turn the admin agent into the first Role config. This is the prerequisite for everything else — do it once, carefully, with the admin agent as the proof it still works identically.
2. **Define the Role schema** and a role registry. Admin becomes `roles/admin.py`.
3. **Add the second role (pick the simplest — likely Client-Inbox, since it reuses the email/triage tools).** This validates the split with minimal new tooling.
4. **Add tool packs per new role** (Ad Manager: Google/Meta Ads + GA4; SEO: Semrush + GSC; Content: drafting + Canva). The connectors for several of these already exist in your stack.
5. **Per-agent deployment** (matches your self-hosted-per-client plan): each client/role can run its own Render instance with its own data, or share one instance with scoped data — your choice per engagement.

Do **not** build role #2 by copying the repo. If you ever feel tempted to copy-paste a prompt rule into a new agent, that's the signal the kernel extraction isn't done yet.

---

## What's already in place vs. to build

| Capability | Status |
|---|---|
| Behavioral DNA (all rules) | ✅ Built — needs extraction into a kernel module |
| Memory, records, registry, catalog | ✅ Built, shared-ready |
| Cross-agent shared lessons | ✅ Built today |
| Usage/cost logging per call | ✅ Built (can tag per-agent) |
| Channels (WhatsApp/email/approvals) | ✅ Built |
| Role config schema + registry | ⏳ To build (the kernel extraction) |
| Tool packs for Ad/SEO/Content roles | ⏳ To build (connectors largely exist) |
| Per-agent data scoping column | ⏳ To add when role #2 lands |

---

## Bottom line

You already have the hard part — a battle-tested kernel of behaviors and memory. Turning it into a platform is **one disciplined refactor** (kernel ↔ role split) plus **one config object + one tool pack per new role**. The cross-agent learning that makes the whole fleet improve from any single correction is live as of today. Keep the discipline — DNA in the kernel, only tools/identity in the role — and you can stand up an Ad Manager or SEO agent in a day without re-deriving a single rule.
