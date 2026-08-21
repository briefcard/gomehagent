# Architecture decision record

Decided 2026-08-21 by the owner, after an external (ChatGPT) proposal was
reviewed against this codebase. This file records what was adopted, what was
rejected, and the one rule that must survive every future integration. Update
it when a decision here is reversed — never let it drift into aspiration.

## What this system is

An AI execution layer that turns one agency's institutional knowledge into
governed, tenant-scoped output. Three layers, and the middle one is the
product:

1. **The substrate** — per-tenant knowledge (claims, objections, audiences,
   entities, situations, assets, brand themes) with provenance on every row.
2. **The governance spine** — the defensible layer, and the box most
   architecture diagrams don't have: `Context.emit` is the ONLY exit for
   generated content; a deterministic banned-claims validator; human approval
   before anything customer-facing moves; every validation ledgered
   (assurance), every tool call attributed (toolcalls), every run recorded
   (SystemRun); tenant isolation enforced structurally (`tool_scope` strips
   the account parameter — the model is never asked which client it is on);
   `sabotage.py` proves the guards are genuinely tested.
3. **Adapters** — Shopify, Gmail/Drive, ESPs (via the `esp.py` capability
   resolver), Canva, WordPress, Semrush. Deliberately thin. Commodity.

## The trust-boundary rule (the one that must survive)

> **MCP is a transport, not an authority.** Remote MCP servers are called by
> OUR adapters — inside the same seam as REST, instrumented by `toolcalls`,
> authenticated per tenant from the credential store — never wired directly
> into a model's tool loop for ACTION tools.

`Your App → Claude API → MCP → Canva` (the model holding the pen on external
actions) was considered and REJECTED: it would bypass the approval queue, the
banned-claims gate, the toolcalls ledger and structural tenant scoping in one
move — rebuilding the perimeter-by-memory problem the 2026-08 remediation
ladder exists to remove. The adopted shape is
`Your App → (model writes copy) → governed pipeline → MCP client in the
adapter → provider`.

## Adopted

- **MCP as adapter transport, provider by provider,** only where the
  provider's own MCP server beats our hand-built surface. Canva first: our
  REST adapter has never met the live API and the brand-kit read is
  best-effort, while Canva maintains an MCP server advertising design,
  asset and brand management (`https://mcp.canva.com/mcp`). Shopify and
  Google stay REST — proven, instrumented, working.
- **Capability resolvers on the `esp.py` pattern** — `provider_for(tenant)`
  from what is CONNECTED, `backend()` or a refusal by name, one PROFILES
  table so providers cannot drift, `caps()` read before composing,
  normalized readers. A generic `{"capability": "x"}` string-router was
  rejected as the shallow version: the value is the per-domain
  normalization, which cannot be generic. `tenants.CAPABILITIES` +
  `tool_scope` remain the index.
- **The substrate as an MCP server (queued):** a facade over `/resolve`, KB
  reads, brand-theme status and `run_skill` — per-tenant scoping in the
  token, writes limited to already-governed paths (run_skill still lands in
  approvals; memory proposals still land in review), never raw table writes.

## Rejected (with the reason, so it stays rejected for the right one)

- **A multi-model agent runtime** (Claude/GPT/Gemini router). The model
  already sits behind single seams (`llm.py`, per-skill `draft_*` with
  deterministic composers as fallback — the offline suites run the whole
  system with no model at all). Swapping providers is editing one module;
  a routing layer serves a platform vendor, not five clients. Revisit only
  if a client contract demands non-Anthropic execution.
- **Third-party ACTION tools in the model loop** (see the trust-boundary
  rule). Read-only MCP tools behind `tool_scope` may be considered later;
  outward actions never.

## Sequence (by customer value)

1. Eien campaign round-trip (the gate on everything).
2. `tool_scope` fail-closed — the keystone; precondition for ANY new outward
   tools, MCP included.
3. Canva via MCP inside the adapter (brand-kit read for the theme deriver;
   bespoke campaign visuals through the pictures approval queue).
4. Substrate-as-MCP v1 (read + run_skill).
5. Capability resolvers as providers accrue (Klaviyo next).
