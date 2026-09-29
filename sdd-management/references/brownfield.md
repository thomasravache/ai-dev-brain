# Brownfield: evolving an existing product

**The existing architecture, patterns and conventions are the law of the project.** Every spec follows them. A deviation is allowed only when the spec is explicitly a migration (`type: migration`) or carries an ADR approved by the human at H1. "I would have done it differently" is never a reason to deviate.

## 1. Adoption baseline

The first time SDD runs in an existing repository, as part of DISCOVER:

1. **Map the architecture:** modules and layers, dependency directions, entry points, data access, error model, logging, dependency injection, configuration, API style, folder and naming conventions, test stack and structure, CI/CD and the path to production.
2. **Record each structural rule as an as-is ADR** (`origin: as-is`, `status: accepted`), citing 2–3 files that exemplify it. These ADRs are what later specs must respect and what the Reviewer checks against.
3. **Create `sdd-config.yml`** with the real commands and run each one. Record the true state — failing tests, flaky tests, missing CI, manual deploys — as specs, never as silent assumptions.
4. **No architecture test suite?** Create a spec (`type: refactor`, no behavior change) that encodes the as-is ADRs as architecture tests. Until it is implemented, G3 is N/A pointing to it.
5. **No CI or no deploy pipeline?** Same: a spec to create it. Until then G5's CI part and G6 are N/A pointing to that spec.
6. If the project used the old SDD layout, run `migrate`.
7. **Board:** look for signs of a tracker (issue keys like `PAY-123` in commits, branch names or PR templates; links in the docs), confirm with the human, and record `tracker` in `sdd-config.yml`. The existing backlog is **not** imported: a ticket becomes a spec only when someone starts working on it (intake in `references/trackers/<provider>.md`).
8. **Enforcement:** propose `vendor --agents --ci <provider> --pr-template <provider> --hooks --changelog`, respecting what already exists (existing PR template, CI, hook manager, changelog format — adapt instead of replacing).

The baseline doesn't block the first feature: it runs in parallel or right before it, and the gaps are explicit N/As with pointers.

## 2. Following the existing pattern

- DISCOVER finds the **reference implementation**: the 1–3 existing features most similar to the new one. The spec's Decisão Arquitetural cites them ("segue o padrão de `src/Orders/CreateOrder/*`").
- Same folder layout, naming, layering, libraries, error model, logging, DI registration and test structure/style as the reference.
- **Deviation** = a new library or framework, a new layer, a new pattern, a new folder or naming convention, a different error model. It needs `type: migration` or an approved ADR, and it is written in "Desvio do padrão existente".
- `verify` warns when dependency manifests change in a spec without an ADR, so the Reviewer confirms whether it's an approved deviation or a justified version bump.
- **Two patterns coexisting?** Follow the one used by the module being changed. If that's unclear, follow the most recent accepted ADR. If there is none, ask the human and record the answer as an ADR.
- The Reviewer (G4) treats an unapproved deviation as a **blocker**.
- **Commit convention:** `verify` and `pr-check` read the Conventional Commits type (`test`, `feat`, `fix`…) to prove red-before-green. If the team uses another convention (e.g. `LOJA-12 descrição`), don't impose silently: ask the human and record an ADR reconciling both — for example `fix(LOJA-12): descrição` + `Refs: SPEC-NNNN` — and set `pr_title` in `sdd-config.yml` to match (e.g. `"{conv}({scope}): {title} [{id}]"` with `scope: LOJA-12` in the spec). Also adapt existing hooks, PR templates and changelog formats instead of replacing them.

## 3. Changing code without tests

Before modifying code without coverage:

1. The Test-writer writes **characterization tests** (`CH-xx`) that pin the current behavior. They must **pass** on the current code, and they're committed first (`test(<scope>): characterize ...` with footer `Refs: SPEC-NNNN`).
2. Then the red tests for the new or fixed behavior.
3. When a characterization test encodes the bug being fixed, the plan says so and the test changes in the same spec.
4. Prefer introducing seams (dependency injection, adapters) over broad rewrites. Refactor only what the spec needs; list further improvements as new specs.

## 4. Bug fixes

1. **Reproduce first.** The regression test (`UT`/`IT`, or `E2E` when the bug is in a user journey) fails on the current code — that failure, recorded in G1, is the proof the bug was captured.
2. Fix the **root cause**, documented in the spec's Causa Raiz — not the symptom.
3. The same test passes after the fix. Relatório de Entrega → **Prova de Correção** cites both runs (red and green commits/CI).
4. Look for the same defect pattern elsewhere and register other occurrences as new specs instead of widening scope silently.

## 5. Migrations: changing the architecture on purpose

A migration is a `type: migration` spec (tier `full`) or epic, with an ADR that supersedes the as-is ADR.

- **Incremental, never big-bang:** strangler fig (the new path grows while the old one shrinks), branch by abstraction, or parallel run/shadow traffic when correctness is critical.
- Old and new coexist behind a stable contract, and both are tested during the coexistence period.
- Data moves with expand → migrate/backfill → switch reads → contract; every step is reversible.
- Architecture tests change in steps: the new rule applies to migrated modules; the old rule is removed only when the migration completes.
- The Plano de Rollout lists the steps, the criteria to switch each one, and the rollback of each step.
- Done means: old path removed, superseded ADR marked `superseded` (with `superseded_by`), architecture tests and root docs updated.
