# Quality Gates

A gate is a checkpoint with objective pass criteria. Every executable spec (`lite`/`full`) records its gates in **Registro de Gates** with `PENDING | PASS | FAIL | N/A` and **evidence**: the command run and its result, commit SHA, CI run, deployed version, or reviewer verdict. `N/A` always needs a justification — usually a pointer to the spec that will create what's missing. A spec can only become `implemented` when every row is `PASS` or `N/A` **and** its Relatório de Entrega proves the Definition of Done (`validate` enforces both).

Gate commands come from `docs/specs/sdd-config.yml`. Every agent runs the same commands — never improvise a different command per agent.

| Gate | Owner | When | Deterministic part |
|---|---|---|---|
| G0 Spec | Architect | before H1 | `spec_graph.py validate SPEC-X` |
| H1 Spec approval | **Human** | before PLAN | frontmatter `approved_by/at` |
| G1 Red | Test-writer | before any implementation | `spec_graph.py verify SPEC-X` (G1 lines) |
| G2 Green | Implementer | after implementation | `build`, `test`, `lint`, `coverage` |
| G3 Architecture | Implementer, confirmed by Reviewer | after implementation | `arch_test` |
| G4 Review | Reviewer (independent) | before integration | `spec_graph.py verify SPEC-X` (G4 lines) |
| G5 Integration & CI | Integrator | after merging the wave | `build`, `test`, `test_integration`, `test_e2e`, `arch_test`, `security_scan` on the merged result + `ci` |
| H2 Integration approval | **Human** | after G5 | H2 row |
| G6 Deploy | Release | after H2 | pipeline run, `smoke_test`, `test_e2e` against the environment |
| G7 Done & Docs | Architect | closing | `validate` (Relatório de Entrega + DoD) and `index` |

A FAIL is recorded with its reason and sent back to the owner. **Three consecutive FAILs on the same gate for the same spec → stop, record `impede --type falha` and escalate to the human** with a diagnosis: what fails, what was tried, and the hypothesis (spec defect, environment, or approach).

A spec with an open impediment (Registro de Impedimentos) cannot pass G7 or become `implemented`; every impediment closes with a resolution that points to its evidence (Emenda, answer/ADR, SPEC-NNNN, action).

---

## G0 — Spec

**Deterministic** — `validate` returns zero errors: valid frontmatter (`type` allowed for the tier, `user_facing` declared); references exist (`parent`, `depends_on`, `consumes_contract` pinned to an existing version, `adrs`); no `depends_on` cycles; required sections present and filled; no `{{...}}` markers; `size` S/M; `touches` declared; test IDs present; `full` has UT + IT, CT when it provides/consumes a contract, E2E when `user_facing: true`; `type: migration` has an ADR; every row of the Mapa de Comportamentos references existing test IDs; epic acceptance criteria cite existing tests; **no open item in Questões em Aberto**; impediment rows well-formed.

**Judgment** — Architect self-check before presenting for H1:
- Scope in/out is explicit; nothing in scope lacks a behavior and a test.
- Every observable behavior — success and **each** error — is a row of the Mapa de Comportamentos.
- NFRs are concrete and say how they'll be measured, or are an explicit N/A.
- **Brownfield:** the Decisão Arquitetural cites the reference implementation it follows; any deviation is declared and covered by `type: migration` or a new ADR. **Greenfield:** decisions trace to the foundation ADRs.
- New cross-cutting decisions have an ADR (with options matrix and sources for technology choices).
- `depends_on` only when the other spec's **implementation** is truly required; otherwise `consumes_contract`.
- `touches` is as narrow as possible.
- The Plano de Rollout makes the change deployable and reversible.
- No gap was filled by assumption: every doubt was asked and its answer recorded in Questões em Aberto.
- A child spec is implementable by one agent in one session.

## H1 — Spec approval (human)

Exact question in SKILL.md. Only an explicit "Aprovado" from the user in chat counts. Record with `set <ids> status=approved approved_by=<user> approved_at=today`; set the introduced ADRs to `accepted`.

## G1 — Red

- Every test ID in the plan exists in code with the tag `SPEC-XXXX:<ID>` (`verify`).
- `CH` tests and tests marked `(guarda)` in the plan **pass** on the current code; every other new test compiles/loads and **fails for the expected reason** (assertion failure or NotImplemented from scaffolding) — never compile errors, missing fixtures or broken setup.
- Red commits are `test(...)` commits that reference the spec and touch only `test_paths`. Contract scaffolding (types, interfaces, signatures that throw NotImplemented — no logic) goes in a separate `chore(...): scaffold ...` commit.
- No `feat|fix|refactor|perf` commit for the spec before the first red commit.
- A new test that passes on red but isn't marked `CH` or `(guarda)` is a spec defect: either it doesn't test the new behavior, or the plan must mark it as a guard (amendment).
- Evidence: `verify` G1 lines + failing summary, e.g. `CH-01 pass; UT-01..03 fail (assertion), IT-01 fail (NotImplemented), E2E-01 fail (element not found) — abc1234`.

Test levels, mandatory coverage and tag conventions: `references/testing.md`.

## G2 — Green

- Build OK; the **full** test suite green (not only the new tests); lint clean when configured.
- Coverage of changed lines ≥ `coverage_min_changed_lines` when `coverage` is configured.
- The Implementer doesn't change red tests. If a test is genuinely wrong, it stops and reports `TEST_DEFECT` (the Test-writer fixes it in a new `test(...)` commit); `verify` flags any test changed outside red commits for the Reviewer.
- Evidence: commands + counts, e.g. `dotnet test: 412 passed, 0 failed — def5678`.

## G3 — Architecture

Architecture stays scalable because structural rules are executable. Every accepted ADR that constrains structure — as-is or new — names the test that enforces it (`enforced_by`).

- `arch_test` passes.
- Rules introduced by the spec's ADRs get their architecture test **in the same delivery**.
- No architecture suite yet → G3 = N/A with evidence pointing to the spec that creates it (brownfield baseline or greenfield foundation). Allowed only until that spec is implemented.

Rules worth enforcing: dependency direction between layers (Domain ↛ Infrastructure/UI); modules talk only through public contracts; no cycles between modules/packages; no framework, ORM or HTTP types in the domain; naming and placement conventions (handlers, controllers, repositories).

| Stack | Tools |
|---|---|
| .NET | NetArchTest.Rules, ArchUnitNET |
| Java / Kotlin | ArchUnit, Konsist |
| JS / TS | dependency-cruiser, eslint-plugin-boundaries |
| Python | import-linter |
| Go | go-arch-lint, depguard |

## G4 — Review (independent)

The Reviewer wrote neither the tests nor the code of this spec. It reports; it doesn't fix.

- `verify SPEC-X` has no FAIL: red → green order, tags, files inside `touches`.
- **Architectural conformance:** the diff follows the reference implementation and accepted ADRs; any new library, layer, pattern or convention is covered by an approved ADR or `type: migration` — otherwise **blocker**. Dependency-manifest warnings from `verify` are resolved explicitly.
- The diff conforms to the contract: signatures, payloads, status/error codes, events, screens.
- Every row of the Mapa de Comportamentos is implemented **and** covered; tests assert behavior, not implementation details.
- No scope creep: nothing outside `touches`, no features outside "in scope".
- Test changes after red (flagged by `verify`) are justified.
- NFRs addressed; Plano de Rollout implemented (flag, migration, observability, rollback).
- Code quality: project naming and patterns; no dead code; no logic duplicated from existing abstractions; errors handled at boundaries; no secrets or sensitive data in code or logs.

Verdict `APPROVED` or `CHANGES_REQUESTED`, findings with severity `blocker | major | minor`. Only blocker/major prevent PASS. Evidence: verdict + reviewed commit SHA.

## G5 — Integration & CI

After every spec branch of the wave is merged into the integration branch, in dependency order:

- On the **merged result**: build, full suite, integration, E2E (local environment), architecture and security scan pass.
- Contract tests run against the real provider when provider and consumer both exist in the merged code.
- **CI pipeline green** for the integration branch/PR (`ci`), including the SDD job (`validate --exclude-drafts` + `pr-check`). The PR title/body come from `spec_graph.py pr`. Pushing the branch or opening the PR to trigger CI happens only with the user's confirmation — a standing authorization written in the project's root docs counts.
- Merge conflicts are resolved preserving both behaviors; a conflict that needs a design choice goes to the Architect.
- No CI yet → the CI part is N/A pointing to the spec that creates the pipeline.
- Evidence: integration commit SHA, command results, CI run ID/URL.

## H2 — Integration approval (human)

Exact question in SKILL.md, once per wave. Record it in the H2 row of every spec of the wave.

## G6 — Deploy

The change reaches its users through the pipeline — never through manual steps outside it.

- **Staging** (or the project's pre-production environment): deployed by the pipeline; `smoke_test` and `test_e2e` pass against it.
- **Production:** only after the user's **explicit confirmation in chat** for that release. Deploy with the strategy of the Plano de Rollout (direct, feature flag, canary, blue-green); `smoke_test` passes in production; key metrics and alerts stay healthy during the observation window; the rollback path is confirmed.
- Libraries/CLIs/mobile: "deploy" means the release channel (package registry, store track) — same rules.
- Evidence: pipeline run, deployed version/tag, environment(s), smoke/E2E results, flag state, who authorized production.
- N/A only with a pointer: no environment exists yet (→ foundation or pipeline spec), or the spec ships with a later wave behind a flag (→ that wave). An epic can't close while user-facing children have G6 = N/A.

## G7 — Done & Docs (Definition of Done)

The Definition of Done is the checklist in each spec's Relatório de Entrega, plus the project's `dod_extra` items appended at PLAN. G7 passes when:

- **Relatório de Entrega** is complete and consistent with the evidence:
  - *O que foi entregue* — the behavior delivered, in user/system terms.
  - *Como foi feito* — implementation decisions, main modules/files, deviations and amendments (with version), technical debt accepted.
  - *Prova de Correção* (`type: fix`) — the regression test failing before (red commit + output) and passing after (green commit + run).
  - *Verificação* — **one row per test ID of the plan** with `PASS` and evidence (CI run, commit or report). This is the proof that what the spec promised was actually delivered.
  - *Definição de Pronto* — every item checked.
  - *Deploy* — environments, version, date, strategy, flag state.
  - *Pendências* — new specs for anything left out, or "Nenhuma".
- Root docs (`root_docs`) reflect the delivered behavior, architecture and any new conventions; backlog items moved; `changelog` entry added (use `spec_graph.py report SPEC-X` as the base).
- ADR statuses correct; `validate` clean for the spec; `index` regenerated.
- Evidence: docs commit SHA + `validate` result.
