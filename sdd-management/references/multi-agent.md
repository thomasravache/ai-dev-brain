# Multi-Agent Execution

## Roles

| Role | Does | Must not |
|---|---|---|
| **Architect** (orchestrator — this skill) | DISCOVER, specs, ADRs, waves, dispatch, gate bookkeeping, amendments, G7 | write domain code; approve its own specs |
| **Test-writer** | G1: characterization tests (brownfield) + failing unit/integration/contract/E2E tests from the contract and test plan | write production logic |
| **Implementer** | G2/G3: minimal code to turn tests green following the existing pattern, then refactor | silently change red tests; touch files outside `touches`; change the contract; introduce libraries/patterns not covered by an ADR |
| **Reviewer** | G4: independent review of the diff against the spec and the ADRs | fix code (it reports findings) |
| **Integrator** | G5: merge the wave, run every suite on the merged result, check CI | merge anything with a FAIL gate; push, open PRs or merge into `base_branch` without user confirmation |
| **Release** | G6: deploy through the pipeline, smoke/E2E against the environment, watch metrics | deploy to production without the user's explicit confirmation for that release; deploy outside the pipeline |

Test-writer and Implementer are **different agents with fresh context**: tests written by the same mind that writes the code tend to confirm the implementation instead of the specification. The Reviewer is a third agent. Integrator and Release may be the same agent.

## Environment mapping

- **Claude Code:** one Agent call per role per spec. Use `isolation: "worktree"` (or a manual worktree, below) for Test-writer and Implementer. Dispatch the specs of a wave in a **single message** with several Agent calls so they run in parallel (≤ `max_parallel`). Prefer a stack-specialist agent type for the Implementer when one is available (e.g. a .NET expert agent).
- **Gemini CLI / other tools with subagents:** same mapping with their subagent mechanism.
- **No subagents:** Solo mode (end of this file).

## Branches and worktrees

- Integration branch: `sdd/<epic-id>` (or `sdd/<spec-id>` for a standalone spec), created from `base_branch`.
- Spec branch: `sdd/<spec-id>-<slug>`, created from the integration branch at the start of the wave (so it contains previous waves).
- Test-writer then Implementer work sequentially on the same spec branch; Reviewer reads it; Integrator merges it into the integration branch.
- Manual worktree when the tool doesn't manage one: `git worktree add ../<repo>-<spec-id> -b sdd/<spec-id>-<slug> sdd/<epic-id>`; remove it after the merge (`git worktree remove`).

## Commit conventions (checked by `verify`, the `commit-msg` hook and `pr-check`)

[Conventional Commits 1.0](https://www.conventionalcommits.org/): `<type>(<scope>)?!?: <description>` — imperative, lowercase, no trailing period; the body explains **why**; the spec goes in a git trailer footer `Refs: SPEC-0042` (several specs: `Refs: SPEC-0042, SPEC-0043`). Types: `build chore ci docs feat fix perf refactor revert style test`. A contract-breaking change uses `!` and a `BREAKING CHANGE:` footer. Follow the project's own scope rules.

| Commit | Purpose |
|---|---|
| `chore(<scope>): scaffold <contract>` + `Refs: SPEC-0042` | optional; types/interfaces/signatures only, throwing NotImplemented |
| `test(<scope>): characterize <area>` + `Refs: SPEC-0042` | brownfield: CH tests pinning current behavior (they pass); before any other change |
| `test(<scope>): <tests>` + `Refs: SPEC-0042` | red; only files under `test_paths` |
| `feat\|fix\|refactor\|perf(<scope>): ...` + `Refs: SPEC-0042` | green / refactor |

Example:

```text
test(wallet): add failing tests for card limit

Covers UT-01..UT-03 and IT-01 from the approved contract.

Refs: SPEC-0042
```

## Wave loop

1. `spec_graph.py next` → the batch to dispatch now (already excludes file conflicts and respects `max_parallel`).
2. For each spec in the batch: create branch/worktree, `set SPEC-X status=in-progress`, dispatch the **Test-writer**.
3. Test-writer returns → Architect runs `verify SPEC-X` and checks the failing summary → record G1. FAIL → back to the Test-writer with the reason.
4. Dispatch the **Implementer** → record G2/G3 from its evidence (re-run the commands if the evidence is thin).
   Any report other than DONE/APPROVED → record it at once with `impede` (see *Stops* below) and route it: `SPEC_DEFECT` → Amendment flow; `TEST_DEFECT` → back to the Test-writer; `BLOCKED` → ask the human or create the missing spec.
5. Dispatch the **Reviewer** → record G4. `CHANGES_REQUESTED` → Implementer receives the findings verbatim → Reviewer again.
6. When every spec of the wave has G4 = PASS → dispatch the **Integrator** → G5 → ask H2 (human).
7. Dispatch **Release** for staging → G6 (staging). Production only after the user confirms that release in chat → G6 (production).
8. G7 for the specs being closed (Relatório de Entrega, docs, changelog) → `index`.
9. Back to step 1 until `next` is empty and nothing is running.

Specs of the same batch are independent by construction: no `depends_on` between them and no overlapping `touches`. A spec that finishes early does not start the next wave — waves integrate together, then `next` is recomputed.

## Consuming a contract that isn't implemented yet

The consumer's Test-writer builds test doubles strictly from the provider spec's contract section at the pinned version (`SPEC-0041@1`). The consumer's CT tests encode what it expects from the provider; the provider's CT tests prove it delivers that. At G5 the Integrator runs the consumer's integration/contract tests against the real provider. A mismatch is a `SPEC_DEFECT` in one of the two specs → Amendment flow.

## Single writer

Only the Architect writes SDD records (`docs/specs/`, `docs/adr/`): status, checklist ticks, gate rows, impediments, amendments, delivery report — in the main checkout, right after each report arrives. Subagents never edit spec files in their worktrees: they report, and the Architect records. This keeps `INDEX.md` current in real time and keeps spec branches free of conflicts on spec files.

## Stops

A subagent that cannot proceed stops — it never guesses, works around the spec or silently narrows scope — and ends its report with a STOP block:

```text
STOP
Status: SPEC_DEFECT | TEST_DEFECT | BLOCKED
Phase/Gate: <e.g. G2>
Missing: <exactly what prevents progress>
Tried: <what was attempted and the result>
Needs: <who must act — Architect, human, third party — and the decision or action needed>
Suggested type: spec | decisão | trabalho | externo | falha
```

The Architect turns it into a tracked impediment immediately:

```text
spec_graph.py impede <SPEC-ID> --type <type> --phase <gate> --reason "<Missing>" --tried "<Tried>" --owner "<Needs>"
```

…routes it (SKILL.md → *Gaps and impediments*), and closes it with `resolve <SPEC-ID> IMP-NN --resolution "..."` citing the amendment, answer/ADR, new spec or action. The Architect also records `falha` itself after 3 consecutive FAILs of a gate.

## Dispatch packets

Subagents start with no context: give them everything they need and ask for a structured report. Fill the `<...>` fields, and end **every** packet with: "Do not edit files under docs/specs or docs/adr. If you cannot proceed, stop and end your report with the STOP block (Status, Phase/Gate, Missing, Tried, Needs, Suggested type)."

### Test-writer

```text
Role: Test-writer (SDD) for <SPEC-ID> — <title>.
Repository: <repo path>. Work on branch <spec branch> (worktree: <path>).
Read first: <spec path> (Contrato + Plano de Testes), docs/specs/sdd-config.yml, ADRs <adrs>, <skill dir>/references/testing.md, the existing tests of the reference implementation <paths> (follow their structure, naming and libraries), and for each consumed contract only the Contrato section of <provider spec paths> at the pinned version.
Task: write EVERY test listed in the test plan (<IDs>), at its level: CH (characterization — must PASS on the current code, commit them first), UT, IT with real dependencies (containers/emulators, not mocks), CT, E2E through the real UI/public API. Tag each one with "<SPEC-ID>:<ID>" using <stack tag convention>. Except CH, tests must compile and FAIL for the expected reason (assertion or NotImplemented), never because of setup or compile errors.
You may add contract scaffolding (types/interfaces/signatures throwing NotImplemented, no logic) in a separate commit "chore(<scope>): scaffold ..." with footer "Refs: <SPEC-ID>".
Commit tests as "test(<scope>): ..." (Conventional Commits) with footer "Refs: <SPEC-ID>". Only touch: <touches>.
Run: <test command>. Do not write production logic.
If the spec is ambiguous, contradictory or untestable: stop and report SPEC_DEFECT — do not guess.
Report only: STATUS (DONE | SPEC_DEFECT | BLOCKED); commits (SHA + subject); tests per ID with file; failing summary (count + reason per ID); notes.
```

### Implementer

```text
Role: Implementer (SDD) for <SPEC-ID> — <title>.
Repository: <repo path>. Branch <spec branch> (worktree: <path>), which already contains the failing tests (red commits <SHAs>).
Read first: <spec path> (whole spec), docs/specs/sdd-config.yml, ADRs <adrs>, and the reference implementation the spec's Decisão Arquitetural cites (<paths>) — your code must look like it belongs there.
Task: implement the minimum needed to make the tests pass, then refactor keeping everything green, following the checklist phases in section "Checklist de Implementação" (report which items you completed; do not edit the spec file). Implement the Plano de Rollout items that live in code (feature flag, backward-compatible migration, logs/metrics).
Rules: do not change the red tests (if a test is wrong, stop and report TEST_DEFECT with the reason); only touch <touches>; do not change the contract; keep the existing architecture, patterns, libraries and conventions — no new library, layer or pattern unless an approved ADR in the spec covers it.
Commit as "feat|fix|refactor(<scope>): ..." (Conventional Commits) with footer "Refs: <SPEC-ID>".
Gates to run before reporting: build "<build>", full tests "<test>", architecture "<arch_test>", lint "<lint>", coverage "<coverage>" (min <coverage_min_changed_lines>% of changed lines).
If the spec is wrong or incomplete: stop and report SPEC_DEFECT with the exact gap — never diverge silently.
Report only: STATUS (DONE | SPEC_DEFECT | TEST_DEFECT | BLOCKED); commits; G2 evidence (command → result counts); G3 evidence; checklist items completed; deviations or risks; STOP block if not DONE.
```

### Reviewer

```text
Role: independent Reviewer (SDD) for <SPEC-ID> — <title>. You did not write this code or these tests.
Repository: <repo path>. Review branch <spec branch> against <integration branch>: git diff <integration branch>...<spec branch>.
Read first: <spec path> (whole spec), ADRs <adrs>, references/gates.md section G4 of the sdd-management skill (<skill dir>).
Run: python3 <skill dir>/scripts/spec_graph.py verify <SPEC-ID> --base <integration branch>, and "<arch_test>".
Check every G4 item: architectural conformance with the reference implementation <paths> and the ADRs (unapproved new library/layer/pattern = blocker), contract conformance, every behavior of the Mapa de Comportamentos implemented and tested, scope, test changes after red, NFRs, Plano de Rollout, code quality.
Do not modify code.
Report only: VERDICT (APPROVED | CHANGES_REQUESTED); verify result; findings as "severity (blocker|major|minor) — file:line — problem — expected"; reviewed commit SHA.
```

### Integrator

```text
Role: Integrator (SDD) for wave <N> of <epic or spec>.
Repository: <repo path>. Integration branch <integration branch>. Spec branches with G4 = PASS, in dependency order: <branches>.
Task: merge each branch (no fast-forward, preserve history), resolving conflicts without dropping behavior — escalate any conflict that needs a design decision. Then run on the merged result: build "<build>", tests "<test>", integration "<test_integration>", E2E "<test_e2e>", architecture "<arch_test>", security "<security_scan>", including contract tests of consumers against real providers. <If the user authorized it: push the integration branch / open the PR and check CI with "<ci>".>
Do not push, open PRs or merge into <base_branch> unless the packet says the user authorized it.
Report only: STATUS (DONE | CONFLICT_NEEDS_DECISION | FAIL); merge commit SHAs; G5 evidence (command → result, CI run); failures with diagnosis.
```

### Release

```text
Role: Release (SDD) for wave <N> of <epic or spec>. Target environment: <staging | production>.
Repository: <repo path>. Version/commit to deploy: <SHA or tag> (G5 PASS, H2 approved).
<Production only: the user explicitly confirmed this production release in chat at <time>.>
Read first: the Plano de Rollout of <spec paths>, docs/specs/sdd-config.yml.
Task: deploy through the pipeline with "<deploy_staging | deploy_production>" using the strategy of the Plano de Rollout (flag, canary, blue-green). Then run smoke "<smoke_test>" and E2E "<test_e2e>" against <staging_url | production_url>, and check the key metrics/alerts listed in the Plano de Rollout for the observation window.
Never deploy outside the pipeline. If smoke/E2E fail or metrics degrade: execute the rollback from the Plano de Rollout and report.
Report only: STATUS (DEPLOYED | ROLLED_BACK | FAIL); pipeline run; version deployed; smoke/E2E results; metrics observed; flag state.
```

After G6, the Architect does G7: fills the Relatório de Entrega from the gate evidence (Verificação with one row per test ID), checks the Definition of Done, updates `root_docs` and `changelog` (`spec_graph.py report SPEC-X` as the base), `set <ids> status=implemented`, `validate`, `index`.

## Solo mode (no subagents)

Same sequence and gates, one agent switching roles and announcing it (`[ROLE: Test-writer]`, `[ROLE: Implementer]`, …). Mitigate the loss of independence:

- Commit the red tests before designing the implementation; derive tests only from the contract and test plan.
- As Reviewer, re-read the spec from the file and review `git diff <integration>...HEAD` as if someone else wrote it; run `verify`.
- Suggest the user run the Reviewer role in a fresh session when the change is risky.
- No parallelism: process the batch sequentially, one spec branch at a time.
