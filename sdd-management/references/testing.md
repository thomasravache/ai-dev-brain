# Testing Strategy

Tests are the executable form of the spec. Every behavior of the contract is proven by a test at the right level, written **before** the implementation, tagged for traceability, and reported in the spec's *Verificação* table when the work is done.

## Levels

| ID | Level | Proves | Rules |
|---|---|---|---|
| guard (any ID, marked `(guarda)` in the plan) | Guard | behavior that already exists and the change must preserve (e.g. "below the threshold the old rule still applies") | written with the red tests but expected to **pass** before and after the change; marked `(guarda: passa antes da mudança)` in the plan so G1 doesn't treat them as broken red |
| `CH` | Characterization | current behavior of existing code, before changing it | must **pass** on the current code; written first in brownfield areas without coverage |
| `UT` | Unit | domain logic, rules, calculations, edge cases | fast, no I/O; doubles only at boundaries; the bulk of the suite |
| `IT` | Integration | the code works with its **real** infrastructure: database, queue, cache, HTTP clients, framework wiring, migrations | real dependencies via containers (e.g. Testcontainers) or official emulators — mocking the thing an integration test exists to exercise hides exactly the bugs it should find |
| `CT` | Contract | provider and consumer agree on a contract between specs/services | consumer-driven (e.g. Pact) or schema-based (OpenAPI/AsyncAPI/JSON Schema validation) |
| `E2E` | End-to-end | a user journey works through the real UI or public API on a deployed-like environment | few and meaningful — critical journeys only; stable selectors (roles, labels, test ids); no fixed sleeps; each test owns its data |

When the NFRs demand it, also: performance/load (k6, Gatling, JMeter, Locust, NBomber), security (SAST, dependency audit, secret scan in CI, DAST against staging), accessibility for UI (axe, Lighthouse). They are listed in section 7.6 of the spec and their results go in the Verificação/Relatório.

## Mandatory coverage

| Spec | Required (enforced by `validate`) |
|---|---|
| `full` | ≥ 1 `UT` and ≥ 1 `IT`; `CT` when it provides or consumes a contract between specs; ≥ 1 `E2E` when `user_facing: true` — a new E2E or an update of the E2E that already covers the journey |
| `lite` | ≥ 1 regression test that fails before the fix, at the level where the defect shows up (`IT` across I/O boundaries, `E2E` for user-journey bugs — warned when `user_facing: true`) |
| `epic` | every acceptance criterion cites the test that proves it (`SPEC-NNNN:E2E-01`, or `IT` for non-journey criteria) |
| brownfield area without coverage | `CH` tests for the code being changed, committed before the change |

## Writing good tests

- One behavior per test, Given/When/Then, names that state the behavior.
- Assert observable behavior (outputs, persisted state, emitted events, HTTP responses, what the user sees) — never private implementation details.
- Every row of the Mapa de Comportamentos, including **each** error, has at least one test.
- Deterministic: control time, randomness and generated IDs; no dependence on test order or shared mutable data.
- Test data comes from builders/factories; each test creates and owns its data.
- A flaky test is a defect: fix it or remove it through a spec. Never retry-until-green, never skip silently.
- Follow the project's existing test structure, naming and libraries (brownfield); in greenfield they are defined by the foundation ADRs.
- Optional quality signal: mutation testing on critical domain code (`mutation` in `sdd-config.yml`).

## Traceability tags

Every test carries `SPEC-NNNN:<ID>` so `verify` can prove that each planned test exists in code.

| Stack | Tag |
|---|---|
| .NET (xUnit) | `[Trait("Spec", "SPEC-0042:UT-01")]` |
| .NET (NUnit / MSTest) | `[Category("SPEC-0042:UT-01")]` / `[TestCategory("SPEC-0042:UT-01")]` |
| JS/TS (Jest, Vitest, Playwright, Cypress) | `it("SPEC-0042:UT-01 rejeita cartão expirado", …)` / `test("SPEC-0042:E2E-01 …", …)` |
| Python (pytest) | docstring or comment `SPEC-0042:UT-01` in the test |
| Java/Kotlin (JUnit 5) | `@Tag("SPEC-0042:UT-01")` |
| Go | comment `// SPEC-0042:UT-01` above the test |
| Mobile flows (Maestro, Detox, Appium) | spec ID in the flow/test name |

A test that serves several specs carries several tags.

## E2E environment

- Runs **locally** against the app started by one command (docker compose or equivalent) and **in CI** against an ephemeral environment or staging.
- `test_e2e` in `sdd-config.yml` runs the suite; `smoke_test` is the small subset run after every deploy (G6), in staging and in production.
- Common choices: web — Playwright or Cypress; mobile — Maestro, Detox or Appium; API-only products — E2E through the public API with the project's HTTP test client. In brownfield, use what the project already has; in greenfield, decide in the foundation ADRs.
- Journey tests use accounts/data created for the test and clean up after themselves; they never depend on production data.
