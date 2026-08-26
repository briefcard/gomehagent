# INITIATIVE — Solidify

**Written 2026-08-26, after the owner's correction:** *"across all the systems
you have been very careless in your execution."* Correct, and this plan's §1
is the accounting. Every §2 fact below comes from a five-agent audit run the
same day (workflow `wf_2358cc8c`), each with file:line evidence — not from
memory, which is where the carelessness lived.

**Read §2 before touching approvals, the console, or the skill registry.**

---

## §1 Why this initiative exists

One day's error ledger, all mine: a red suite pushed to main (`edf6803` —
commit chained off `tail`'s exit code); a duplicated decorator that took
`app/web.py` down at import and 44 suites with it; a green tick rendered for
an account whose Search Console returns 403, on the page built to catch
exactly that; an advisory that gated readiness; two suite-variable shadowings;
retention built while the gate contradicting it stayed; an exclude-term
engine that proposed blacklisting "miami" for Miami Ironside.

The shape is one shape: **a value assumed, defaulted, or declared, presented
as observed** — DEFECTS §1's "unknown collapsed into a value", written
repeatedly by someone who could quote the rule. Rules do not stop it.
Structure does. Hence Phase 0.

## §2 The audited facts (2026-08-26)

Numbered so later phases can cite them.

1. **The owner decided on articles from a one-line summary.** The Review tab
   rendered no Approval rows at all (`admin_ui.py:4071-4127` — six sections,
   none approvals); `/admin/pending` read `payload["body"]`, empty for
   articles (`web.py:1113` vs `seo_tools.py` fields nesting); the WhatsApp
   card and fallback email shared the blind spot (`whatsapp.py:197`,
   `emailfmt.py:84`); the WhatsApp Edit button seeded a revision from an
   empty string (`web.py:1230`). **CLOSED 2026-08-26 (`be79f35`)** — see
   Phase 1, done.
2. **The publish loop was fully open.** Zero production writers for
   `KeywordTarget.target_url` / `published_at` / `status="published"`;
   `create_article`'s returned URL discarded into a WhatsApp string;
   `ledger.publish`'s only caller was `responder.send`, itself with zero
   production callers; cms_article Outputs stayed `draft` forever; the blog
   measure "draft-vs-published delta" computed nowhere; `progress`'s tracked
   cohort structurally starved. **CLOSED 2026-08-26 (`be79f35`)** via
   `keywords.mark_published`, called from both publish paths.
3. **Skill reachability is uneven and partly deliberate.** Four production
   entry points to `skill.run`: the weekly compliance sweep
   (catalog_compliance only), the daily tick (only systems declaring a
   workflow skill: campaign_email, blog, ad_creative), console
   `GET /admin/plan_run` (same three) and `POST /admin/skill_run` (any
   skill), and the admin agent's `run_skill` tool. The mail path bypasses the
   skill layer entirely — `triage.triage_email` drafts in its own loop, so
   `inbound_reply` is never used by real mail. `catalog_seo_rewrite` and
   `inbound_reply` have no named surface beyond generic `skill_run`.
4. **Nine console facts have no control.** Worst two: mute-lesson
   exclude-term proposals are prose with no accept route existing anywhere;
   the market/semrush_db advisory's only write path is the raw-JSON
   `analytics` field. Plus: Knowledge-tab pending claims (banner only), no
   add-situation control despite the KB warning that claims will be refused
   without tags, bare-code strings for `/admin/vocabulary` and
   `/admin/register_owner`, "run the catalogue sync on the Review tab" with
   no link, and system gate blockers naming a connection with no link to
   Connections.
5. **Process had no gate.** No hooks, no CI, no ship script; `test_all.sh`
   exits 1 on failure but nothing forced consulting it. **PARTIALLY CLOSED**
   — `scripts/ship.sh` (compile → import → suite, gated on exit codes) is now
   the only sanctioned push path; a pre-push hook does not yet exist (the
   build dir is a linked worktree; hooks live in the parent repo's
   `.git/hooks`).
6. **test_harvest's flake is its live-network half.** It restores the real
   `httpx.get` at line 299 and then crawls bacimilanousa.com under `-P 8`
   load asserting `pages_read>0`, `pages_discovered>200`. Secondary:
   `test_brief.py` uses a fixed repo-root sqlite path.
7. **Render auto-deploys every push to main** (no autoDeploy/branch keys in
   render.yaml → platform default), so a push IS a deploy.
8. **Semrush `_tenant` threading is consistent** and schemas do not leak it —
   audited clean; no action.

## §3 The phases

**Phase 0 — the working agreement. PARTIALLY DONE.**
`ship.sh` exists and shipped `be79f35`. Remaining: a `pre-push` hook in the
parent repo's `.git/hooks` that refuses a push to main outside `ship.sh`
(§2.5, §2.7 — a push is a deploy, so the hook is the deploy gate); codify in
CLAUDE.md: every fix ships with its sabotage guard, every new console fact
ships with its control.

**Phase 1 — the article review loop. DONE (`be79f35`).**
`/admin/article/<output_id>`: whole article, edit form, ban-list-gated saves
(the list binds the owner too), approve/deny, manual mark-as-published with
URL for no-API platforms. What was reviewed is what publishes; the draft
survives in `draft_body`; the declared measure computes at publish onto
`SystemRun.edit_diff`. Publish write-back closed on both paths (§2.1, §2.2).
Follow-through left: point the WhatsApp Edit button for article kinds at the
review page instead of the empty-seeded requeue (`web.py:1341`).

**Phase 2 — approvals become a Review-tab section (§2.1 residue, §2.4).**
`render_content` gains a "may this ship" section: every pending approval with
a real body preview, approve/deny, and the review link for artifacts.
`/admin/pending` stays as the unstyled fallback it is. The Systems "Waiting
on you" rows link the same controls instead of a bare "decide →".

**Phase 3 — reach or retire (§2.3).** Decisions, not code, first:
`inbound_reply` — the mail path is governed without it by design; either
retire the skill or mark it agent-only in its `does` string so the map stops
reading it as a gap. `catalog_seo_rewrite` — give it its real consumer: the
**article recheck pass** (Phase 5) files through the same proposal shape.
`ad_copy` — reachable via tick already; needs plans, which needs the
ad_creative planner that doesn't exist; park explicitly or build the planner.

**Phase 4 — controls for the nine named facts (§2.4).** In order of harm:
accept-exclude-term (needs its home first: `Tenant.analytics["exclude_terms"]`,
merged into the site profile by `sites._from_tenants`, so the button has
somewhere to write); market/semrush_db field with the other Connections
fields; pending-claims controls on the Knowledge tab; add-situation control;
the four bare-string→link fixes.

**Phase 5 — the map as input everywhere (the owner's stated direction).**
1. `article_recheck` skill: published article (live URL or ArtifactBody) vs
   its keyword — answer still first, FAQ questions vs the cluster's question
   siblings, internal links vs cluster obligations, title/meta vs phrase —
   filing proposals, never writes. Joins already exist (`output_id`,
   `target_url`, `cluster_key`).
2. Intent + volume + priority into `ad_copy`'s brief.
3. Cluster link-obligations table on the Plan tab.

**Phase 6 — suite hygiene (§2.6).** Gate test_harvest's live-crawl half
behind `LIVE=1`; give test_brief a temp path. The flake has fired in full
runs and a suite people learn to re-run is a suite people learn to ignore.

**Phase 7 — owner actions, unchanged and still owed:** Google re-consent per
account (the live 403), Canva reconnect, eien blog_id, Coverings' Shopify,
agency Google connect, the goal numbers.

Order: 0-remainder immediately; 2 next (it is the owner's daily surface);
then 4, 5, 3, 6. Phase 7 runs parallel and is not mine to do.
