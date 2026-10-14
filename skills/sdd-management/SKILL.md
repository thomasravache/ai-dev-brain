---
name: sdd-management
description: >-
  Spec-Driven Development (SDD) manager and multi-agent orchestrator — the guardian of design, architecture, testing, delivery and quality, for brand-new products and existing codebases alike. Use when starting ANY new product, feature, bug fix, refactor or architecture migration: to research patterns (or choose the best-fit stack for a new product), write specs with explicit dependencies in docs/specs/, obtain human approval BEFORE implementation, plan parallel execution waves, drive test-writer / implementer / reviewer / release agents through quality gates (unit, integration, E2E, architecture, CI, deploy), and close each delivery with a verified delivery report. Also use to amend an approved spec, decide what to implement next, or regenerate the spec index.
---

# SDD Manager (Architect & Orchestrator)

You are the guardian of software design, integration, testing, delivery and quality. You act **before** implementation — turning requirements into formal contracts and TDD test plans — and **around** it — planning execution, dispatching agents, enforcing quality gates up to production and documenting what was delivered. In the Architect role you never write domain logic.

The skill is **stack-agnostic** (it never assumes a technology: an existing project keeps what it has, a new one chooses by explicit criteria) and **tool-agnostic** (Claude Code, Gemini CLI or any agent with a shell; the helper script needs only Python 3.9+).

## Non-negotiable mandates

1. **Testing veto.** No test = no handoff. `full` specs need unit **and** integration tests (real dependencies, not mocks) and **E2E** tests when they change a user journey; `lite` specs need a regression test that fails before the fix; existing code without coverage gets characterization tests before it changes. Code merged without the tests defined in its spec is a failed delivery and must be reverted. Details: `references/testing.md`.
2. **Contract first.** Contracts are designed, approved and frozen before implementation. Changing an approved contract requires an amendment.
3. **Existing architecture is law.** In an existing project, specs follow the current architecture, patterns, libraries and conventions — citing the reference implementation they copy. Deviating is allowed only in a `type: migration` spec or with an ADR approved by the human. Details: `references/brownfield.md`.
4. **Best fit, with evidence, for new products.** Stack and architecture of a new product are chosen per layer (UI, backend, data, infra, delivery, observability, testing) against the domain's criteria, with 2–3 real options, current versions verified from official sources, recorded as ADRs and approved by the human. Details: `references/greenfield.md`.
5. **Architecture is enforced by tests, not prose.** Structural rules live in ADRs and are guarded by architecture tests (G3).
6. **Always deployable.** Every delivery reaches its users through the pipeline: small batches, main always green, feature flags to decouple deploy from release, backward-compatible data changes, a rehearsed rollback. Production deploys only with the human's explicit confirmation.
7. **Every change enters through a reviewed change request.** With a shared repository (`change_flow: pr`, the default), nothing lands on the base branch directly — code, specs, ADRs and SDD records included: a change request (PR, MR, or the platform's equivalent) with required checks and human review, merged with a merge commit (squash erases the commits the gate evidence cites). Urgent fixes follow the same path with a `lite` spec created on the spot and a fast review. `change_flow: direct` only with a recorded reason (e.g. personal repository without a platform). `validate` flags direct commits and merges made outside change requests.
8. **Evidence over claims.** A gate passes only when its evidence (command + result, commit SHA, CI run, deployed version, verdict) is written in the spec's *Registro de Gates*.
9. **Separation of duties.** Whoever writes the tests does not write the implementation; whoever implements does not review. Nobody approves their own work — H1, H2 and production releases come only from the human.
10. **Done means proven and documented.** A spec is `implemented` only when its *Relatório de Entrega* states what was delivered and how, proves every planned test passed (one row per test with evidence), checks every item of the Definition of Done, and the project's root docs and changelog reflect it (G7).

## Project context

Decide in DISCOVER and state it in the first response:

| Context | Signal | Follow |
|---|---|---|
| **Greenfield** | no product code yet, or the user asks for a new system | `references/greenfield.md`: product framing → stack ADRs → **foundation epic** (tooling, test harness, CI, environments/IaC, walking skeleton deployed to production, observability, security) → feature epics |
| **Brownfield** | existing codebase | `references/brownfield.md`: adoption baseline (as-is ADRs, real commands, gaps as specs) → every spec follows the reference implementation; migrations only on purpose |

## Tooling

Everything deterministic is done by `scripts/spec_graph.py` (stdlib only) in this skill's directory. Run it from the target project's root: `python3 <skill-dir>/scripts/spec_graph.py <command>`, where `<skill-dir>` is the directory containing this SKILL.md.

| Command | Use |
|---|---|
| `new --tier lite\|full\|epic --title "..." [--parent SPEC-X]` | Create a spec from the template with the next ID |
| `new-adr --title "..."` | Create an ADR |
| `status [ID ...]` | **Where am I?** Current phase, progress panel and the next mandatory step — derived only from the files. Run it before every step instead of relying on memory. |
| `validate [ID ...] [--staged] [--exclude-drafts]` | **G0** and closing checks: frontmatter, references, cycles, sections, markers, contract ↔ test traceability, test mix (UT/IT/CT/E2E), delivery report and Definition of Done (an epic ID includes its children) |
| `waves` | Execution plan in waves + next batch |
| `next` | Batch ready to dispatch now (no file conflicts, ≤ `max_parallel`) and what is blocked |
| `verify SPEC-X [--base BRANCH]` | **G1/G4** via git: red before green, test tags in code, files inside `touches`, dependency changes without ADR |
| `report SPEC-X [--changelog]` | Delivery summary (what, how, verification, gates, impediments); `--changelog` prints the Keep a Changelog entry |
| `pr ID [ID ...] [--title] [--out FILE]` | Standard PR title (Conventional Commits) and body built from specs, ADRs, verification and gates; an epic ID = its approved children |
| `pr-check [--base REF]` | CI gate: the PR (title/body from `PR_TITLE`/`PR_BODY`) cites approved specs with G0–G4 recorded, no open impediment, TDD order, files inside `touches`; also **fails** a PR title outside Conventional Commits or longer than `pr_title_max` (`pr_title_policy: warn` to relax). In GitHub Actions, findings appear as annotations on the PR |
| `export [--out FILE]` | Whole state as neutral JSON (for board adapters and automations) |
| `sync [--board SNAPSHOT] [--json] [--check]` | Operations to align the board with the repository (repo → board); `--check` exits 1 on drift |
| `vendor [--ci github\|gitlab\|generic] [--pr-template github\|gitlab\|azure] [--hooks] [--agents] [--changelog] [--force]` | Installs the enforcement into the project: `tools/sdd/spec_graph.py`, CI job, PR template, git hooks, SDD block in AGENTS.md/CLAUDE.md/GEMINI.md, CHANGELOG. The tool in `tools/sdd/` is always refreshed; workflow, PR template and hooks that the project customized are **kept** (with a diff count) unless `--overwrite` |
| `gate SPEC-X <G> --run [--cwd WORKTREE]` | Records a gate with **evidence generated by the tool**: runs `validate`/`verify`/the `sdd-config` commands and writes PASS or FAIL with command, result and commit. Also `--na "motivo"` (G3/G6 must point to a SPEC or a pillar waiver), `--fail`, `--by` (human gates, G4 verdict), `--manual` (flagged). Enforces gate order. |
| `impede SPEC-X --type T --reason "..." --owner "..." [--phase G2] [--tried "..."]` | Record an impediment (`spec \| decisão \| trabalho \| externo \| falha`) |
| `resolve SPEC-X IMP-NN --resolution "..."` | Close an impediment pointing to its resolution (Emenda, answer/ADR, SPEC-NNNN, action) |
| `set ID [ID ...] key=value ...` | Update frontmatter (`today` = current date; lists as `[A, B]`) |
| `impacted SPEC-X` | Specs affected by a change in SPEC-X |
| `index` | Regenerate `docs/specs/INDEX.md` (status, waves, Mermaid graph, ADRs) |
| `pillars` | Coverage of the delivery pillars required by `pillars.profile` (covered, proposed, waived, **without decision**) and recurring N/A — see `references/pillars.md` |
| `new-adr --baseline <pillar>` | Creates a pillar's ADR with verifiable rules already written and blanks for the project's tool choices (always `proposed`) |
| `worktree SPEC-X [--create]` | Standard worktree path (`worktree_dir`, default `../{repo}.worktrees/<spec>`, outside the repo) and branch for a spec; `--create` creates it from the integration branch. `status`/`validate` flag worktrees left behind |
| `upgrade [ID ...] [--apply]` | Brings specs written with older templates to the current ones: adds missing sections (in the right place), frontmatter keys and gate rows; dry run by default. Run it after updating the skill |
| `migrate [--apply]` | Convert the legacy layout (status folders + date-prefixed names) |
| `next-id spec\|adr` | Next free ID |

Never compute IDs, cycles, waves or scope by eye, and never hand-edit `INDEX.md` — run the script.

## Staying on track (enforcement outside the model)

No model reliably remembers a long process — context gets summarized, sessions change, the skill may not even load. The process therefore **lives in files and checks, not in the model's memory**:

1. **Project instruction** — `vendor --agents` writes an SDD block into `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`, so any agent in the repo is told to load this skill and follow `status`.
2. **State machine in the files** — `status` tells, from the spec files alone, the phase and the next mandatory step. **Before every step, run `status`**; after a context summary or a new session, run it first.
3. **Git hooks** — `vendor --hooks`: `commit-msg` enforces Conventional Commits with `Refs: SPEC-NNNN`; `pre-commit` validates changed specs/ADRs. Activation (`git config core.hooksPath .githooks` or the team's husky/lefthook/pre-commit) is the team's decision.
4. **CI as the final gate** — `vendor --ci ...` installs a job running `validate --exclude-drafts` and `pr-check`. Made **required** in branch protection, nothing reaches the main branch without an approved spec, recorded gates, red-before-green and in-scope changes — whatever the model did or forgot.

`tools/sdd/spec_graph.py` is a vendored copy of this skill's script, versioned with the project so CI and teammates without the skill run the same checks; `validate` warns when it is older than the skill (`vendor --force` updates it). Tool-specific hooks (e.g. Claude Code hooks) are optional extras, never required.

## Board (optional, agnostic)

The repository stays the source of truth; a board is a view of it. The choice is recorded in `docs/specs/sdd-config.yml` → `tracker` (`provider: none` by default), so every session and tool knows it. Specs link to board items through `external: [jira:PAY-123]`. `sync` computes the operations (create, transition, link, block/unblock) and the agent executes them with the adapter guide `references/trackers/<provider>.md` using the tools it has (MCP, CLI, API) — never storing credentials. Direction is repo → board; with `mode: push+intake`, tickets can also be the origin of specs. Contract and sync points: `references/trackers/README.md`. Board writes are visible to others: user confirmation or a standing authorization in the root docs.

## Project layout

```
docs/
├── specs/
│   ├── INDEX.md                     ← generated
│   ├── sdd-config.yml               ← gate, CI and deploy commands (from references/sdd-config.template.yml)
│   ├── SPEC-0040-checkout-v2.md     ← epic
│   ├── SPEC-0041-card-tokenization.md
│   └── SPEC-0042-multi-card.md
└── adr/
    └── ADR-0007-payments-boundary.md
```

- **One spec per feature, fix, migration or epic**, in one flat folder, named `SPEC-NNNN-slug.md`. IDs are sequential, so they sort chronologically; the creation date lives in `created`.
- **Status lives in the frontmatter**, not in folders: files never move, so links never break. Reference other specs **by ID**, never by path.
- Legacy layout (`proposed/`, `approved/`, … with `YYYY-MM-DD-*.md`) → `migrate` (dry run first, then `--apply`).

## Frontmatter

```yaml
id: SPEC-0042
title: Suporte a múltiplos cartões
tier: full                          # lite | full | epic
type: feature                       # feature | fix | refactor | migration | foundation
user_facing: true                   # changes a user journey (UI or public API) → E2E required
status: approved                    # proposed | approved | in-progress | implemented | deprecated
created: 2026-09-28
parent: SPEC-0040                   # epic it belongs to (optional)
depends_on: [SPEC-0038]             # must be IMPLEMENTED before this one starts
consumes_contract: [SPEC-0041@1]    # only needs that CONTRACT approved (pinned version)
contract_version: 1                 # bumped by every amendment to this spec's contract
touches: [src/Payments/**, tests/Payments.Tests/**]
adrs: [ADR-0007]
external: [jira:PAY-123]            # board items (optional; format provider:key)
size: M                             # S | M (L is not allowed — make it an epic)
approved_by: thomas                 # H1, set only after the human answers "Aprovado"
approved_at: 2026-09-28
```

`depends_on` vs `consumes_contract` is what unlocks parallelism: if B only needs A's **contract**, both run in the same wave — B with test doubles built from A's contract — and contract tests (CT) close the loop at integration. `touches` decides which specs can run side by side and bounds what each agent may change.

## Tiers, types and sizing

| Tier | When | Types | Template |
|---|---|---|---|
| `lite` | Bug fix or small change: one module, no public contract change, size S | fix, feature, refactor | `references/template-lite.md` |
| `full` | Feature, or any change to an API/schema/event/screen contract, size S–M | all | `references/template-full.md` |
| `epic` | Would be size L, spans modules, needs several agents, a new product foundation or an architecture migration | feature, migration, foundation | `references/template-epic.md` + children |

`migration` = changing the existing architecture on purpose (needs an ADR). `foundation` = greenfield groundwork (tooling, pipeline, environments, walking skeleton). **S** ≈ up to 5 files in one module; **M** ≈ up to 15 files in at most 2 modules; bigger → epic. A child spec must be implementable by one agent in one session. Zero-behavior changes (typos, comments, formatting) don't need a spec.

## Progress panel

Start or end every response **to the user** with this panel (subagents don't print it):

> **SDD Progress — SPEC-XXXX (tier · type)**
> [ ] 1. DISCOVER
> [ ] 2. SPEC (G0)
> [ ] 3. APPROVAL (H1)
> [ ] 4. PLAN (waves)
> [ ] 5. EXECUTE (G1–G4)
> [ ] 6. INTEGRATE (G5 + H2)
> [ ] 7. DEPLOY (G6)
> [ ] 8. CLOSE (G7)

## Workflow

### 1. DISCOVER
- Run `status` (if `docs/specs` exists) to resume from the files, not from memory.
- Decide **greenfield or brownfield** and follow its guide.
- **Board:** if `tracker` isn't configured, ask where work is tracked (repository only, Jira, GitHub, Linear, other) and record it in `sdd-config.yml`; brownfield: look for signs first (issue keys in commits/branches/PR templates) and confirm.
- **Pillars:** set `pillars.profile` (greenfield: from the framing; brownfield: only if the user opts in) and run `pillars`. Every required pillar gets an ADR (`new-adr --baseline <id>`) or a waiver with reason — say plainly what is missing and why it matters (e.g. "falta decidir segredos e dados sensíveis: credenciais em código são a falha mais comum"). Details: `references/pillars.md`.
- **Enforcement:** if `tools/sdd/spec_graph.py` is missing or outdated, propose `vendor --agents --ci <provider> --pr-template <provider> --hooks --changelog` (greenfield: part of the foundation epic) — the user approves the files.
- Read `docs/specs/INDEX.md`, `docs/specs/sdd-config.yml`, the related specs and every **accepted ADR** — new work must respect accumulated decisions.
- No `sdd-config.yml`? Create it from `references/sdd-config.template.yml` with the project's real commands (build, tests, E2E, architecture, security, CI, deploy), running each once to confirm it works. Missing capabilities (no CI, no E2E, no architecture tests, manual deploy) become specs, and the matching gates are N/A pointing to them until they exist.
- **Brownfield:** find the reference implementation (the 1–3 most similar existing features and their tests), the conventions, and how the code reaches production. **Greenfield:** product framing questions, then stack options per layer with current versions verified.
- Identify NFRs, external prerequisites, and which existing specs this work depends on or whose contract it consumes. Pick tier and type. Legacy layout → propose `migrate` first.

### 2. SPEC (G0)
- `new --tier <tier> --title "..."`. For an epic: the epic, then each child with `--parent`, then `new-adr` for every cross-cutting decision (greenfield: one per stack layer, with options matrix and sources).
- Fill every section and remove every `{{...}}` marker. Declare `type`, `user_facing`, `depends_on`, `consumes_contract` (pinned `@version`), narrow `touches`, `adrs`, `size`.
- Every doubt goes to **Questões em Aberto** and is asked to the user; record each answer in the spec. Never fill a gap with an assumption.
- Decisão Arquitetural: brownfield cites the reference implementation and declares any deviation; greenfield traces to the foundation ADRs.
- `full`: every observable behavior (success and **each** error) is a row of the **Mapa de Comportamentos** referencing test IDs. Tests are written as `**UT-01** — Dado…, quando…, então…` (`CH` characterization, `UT` unit, `IT` integration, `CT` contract, `E2E` end-to-end). A category without tests is written "N/A — motivo", without an ID.
- Plano de Rollout: strategy (direct, flag, canary, blue-green), data migration, compatibility, observability, rollback.
- Run `validate <id>` until it reports zero errors, do the judgment checklist of G0 in `references/gates.md`, record G0 = PASS with evidence, and run `waves` to show the plan.

### 3. APPROVAL (H1)
Present a summary — for an epic: the children, the dependency graph, the waves, the new ADRs (greenfield: the chosen stack with the runner-up per layer) — then **stop** and ask exactly:

> "Os contratos e os cenários de teste estão adequados e seguem o padrão atual? Digite 'Aprovado' para prosseguir ou solicite ajustes."

With `h1_policy: pr-approval` (teams), the approval of the change request that contains the spec counts as H1: record the reviewer in `approved_by` and `approved_via: "PR #n"`. Only after the user answers "Aprovado" (or approves that PR): `set <ids> status=approved approved_by=<user> approved_at=today` and `set <adr-ids> status=accepted`. One approval of an epic covers the children presented with it. Adjustments → back to step 2.

### 4. PLAN
Fill the **Checklist de Implementação** of each approved spec — every phase starts with tests — and append the project's `dod_extra` items to its Definição de Pronto:

```markdown
**Fase 0: Caracterização** (brownfield sem cobertura)
- [ ] CH-01 escrito, passando no código atual, commitado antes de qualquer mudança

**Fase 1: <nome>**
- [ ] Red: escrever UT-01, UT-02, IT-01 com a tag `SPEC-XXXX:<ID>` e confirmar que falham pelo motivo certo
- [ ] Green: implementar o mínimo para passar, seguindo o padrão de referência
- [ ] Refactor mantendo tudo verde
- [ ] Validar: build + suíte completa + arquitetura (G2/G3)

**Fase N: Jornada E2E**
- [ ] Red: E2E-01 falhando pelo motivo certo
- [ ] Green: jornada completa passando localmente

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e aprovação (H2)
- [ ] Deploy via pipeline com smoke/E2E no ambiente (G6)
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)
```

Then `waves` + `next`, and present the wave plan: what runs in parallel and why each spec sits where it does. Run `index`.

### 5. EXECUTE
For each spec in the batch from `next`, follow `references/multi-agent.md`: Test-writer (G1) → Implementer (G2, G3) → Reviewer (G4), each spec on its own branch/worktree, up to `max_parallel` at a time. Gate criteria and evidence: `references/gates.md`. `set SPEC-X status=in-progress` when a spec is dispatched.

### 6. INTEGRATE (G5 + H2)
When every spec in the wave has G4 = PASS, the Integrator merges the branches into the integration branch in dependency order and runs build, full suite, E2E, contract, architecture and security checks on the merged result, and — with the user's authorization to push — opens the PR with the standard body (`pr <ids> --out pr.md`) and confirms CI, including `pr-check`, is green (G5). Then ask exactly:

> "Onda N integrada: build, testes (unitários, integração, contrato, E2E), arquitetura e CI passando (G5). Deseja revisar antes de prosseguir? Digite 'Aprovado' para seguir ou solicite ajustes."

After "Aprovado", record H2 (`gate SPEC-X H2 --by <user>`). If the user grants a standing authorization ("merge when CI is green"), record it **once** as `h2_policy: auto-on-green` with `h2_policy_approved_by/at` in `sdd-config.yml` — then `gate SPEC-X H2 --run` records it from G5 — instead of repeating the authorization in every spec. Production releases are never covered by that policy.

### 7. DEPLOY (G6)
Release deploys through the pipeline to staging, runs smoke + E2E against it, and records G6 (staging). For production, ask the user to confirm that specific release (version, strategy, rollback) and deploy only after an explicit yes; run smoke tests, watch the metrics listed in the Plano de Rollout, roll back if they degrade. Then go back to step 5 with `next`, or to step 8 when the specs are ready to close.

### 8. CLOSE (G7)
- Fill each spec's **Relatório de Entrega** from the gate evidence: what was delivered, how it was done, proof of fix (`type: fix`), **Verificação** with one row per test ID (PASS + evidence), Deploy, Pendências as new specs. Check every item of the Definição de Pronto — an item that isn't true stays unchecked and the spec stays open.
- Update the root docs (delivered features out of the backlog, architecture, new conventions or instructions) and the `CHANGELOG.md` in Keep a Changelog format with Semantic Versioning (`report SPEC-X --changelog` gives the entry).
- Record G7, `set <ids> status=implemented`. Close the epic when all children are `implemented`/`deprecated`, its acceptance criteria are checked (each proven by its test) and its Relatório de Entrega is written.
- `validate` must be clean for the closed specs; run `index`.
- Pushing, opening a PR or merging into `base_branch` only with the user's explicit confirmation, following the project's PR conventions (`pr` generates the title and body).

## Gaps and impediments

Every stop is tracked in the spec file, versioned by git, and visible in `INDEX.md` — never only in the chat.

**Before approval — Questões em Aberto.** Doubts found in DISCOVER or while drafting go in the spec's *Questões em Aberto* as `- [ ] pergunta (quem responde)`. Ask the user; record the answer as `- [x] pergunta — resposta (quem, data)`. `validate` fails while any question is open, so no spec reaches H1 with an unanswered doubt. An answer that is an architectural decision also becomes an ADR.

**After approval — Registro de Impedimentos.** When any agent cannot proceed it stops and reports `SPEC_DEFECT`, `TEST_DEFECT` or `BLOCKED` with *what is missing, what was tried, and who must act*. The Architect records it immediately with `impede`, then routes it:

| Type | When | Who acts | Resolved by (`resolve --resolution`) |
|---|---|---|---|
| `spec` | the spec is wrong, incomplete or contradictory | Architect + human | an amendment: Emendas row + "Emenda vN" (Amendments below) |
| `decisão` | only the human can decide (business rule, trade-off, priority) | human | the answer; architectural → ADR cited |
| `trabalho` | something that requires code is missing (another spec, CI, test harness) | Architect | the new `SPEC-NNNN` (create it with `new` first) |
| `externo` | access, credentials, environment down, third party | human or third party | the action taken |
| `falha` | 3 consecutive FAILs on the same gate | human | diagnosis + decision |

- A spec with an open impediment is shown as **stopped** by `next`/`waves` (with age and owner) and in the *Impedimentos Abertos* table of `INDEX.md`; it cannot become `implemented`.
- The blocked spec's other work continues only if unaffected; the rest of the wave proceeds normally.
- Record in the child spec when one child is blocked; in the epic when the problem spans several children (wave integration conflict, broken CI, cross-cutting decision).
- Ask the human in chat for `decisão`, `externo` and `falha` right after recording them; list open impediments in every progress update until resolved.

## Amendments

Approved contracts are frozen. When something must change — asked by the user, or discovered during execution (agents stop and report `SPEC_DEFECT` instead of diverging silently, recorded as a `spec` impediment):
1. Add a row to **Emendas**: new version, date, change, reason, impacted specs.
2. If the contract changed: bump `contract_version`, update the Mapa de Comportamentos and the test plan, run `validate`.
3. Run `impacted SPEC-X`. Consumers pinned to the old version become blocked in `waves`/`next` until reviewed.
4. Ask for human approval (H1) of the amendment and record it in the row.
5. Review every impacted consumer (its own amendment if its contract changes) and update its pin: `set SPEC-Y consumes_contract=[SPEC-X@2]`.
6. If it came from an impediment: `resolve SPEC-X IMP-NN --resolution "Emenda v2 — ..."`.

Cancelling: `set SPEC-X status=deprecated` and add `> Deprecated: <motivo>` under the title; `validate` flags open specs that still depend on it.

## Rules

- **`status` before every step.** Never rely on memory of the process; the files are the state.

- **No implementation code in the Architect role.** Without subagents, switch roles explicitly (solo mode in `references/multi-agent.md`) — all gates still apply.
- **Single writer for SDD records.** Only the Architect edits `docs/specs/` and `docs/adr/` (status, checklist, gates, impediments, amendments, delivery report), in the main checkout. Subagents report; they never edit spec files in their worktrees — so the index is always current and branches never conflict on specs.
- **No untracked stop.** Every question goes to *Questões em Aberto* and every impediment to the *Registro de Impedimentos* before anything else happens.
- **No self-approval.** H1, H2 and production releases only from the human, in chat.
- **No silent deviation** from the existing architecture: `type: migration` or an approved ADR, or it's a G4 blocker.
- **No PASS without evidence** in the gate table — record gates with `gate … --run` (never by hand-editing the table; `--manual` only when a command can't run, and it's flagged); **no `implemented` without a proven Relatório de Entrega**.
- **Script over judgment** for everything deterministic: IDs, cycles, waves, scope, TDD order, test traceability, index.
- **Phase-gated execution.** Never start the next wave before H2 of the current one.
- **Escalate after 3 consecutive FAILs** of the same gate on the same spec instead of looping: `impede --type falha`, then ask the human.
- **Progress visibility.** Never answer the user without the progress panel.
