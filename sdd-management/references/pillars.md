# Delivery pillars

A product is delivered end to end with quality only when a few cross-cutting questions have explicit answers. The skill keeps a **neutral catalog** of those questions (the pillars). Each pillar is answered by an ADR that declares `pillars: [<id>]`, or explicitly waived with a reason. The answer — which tool, which platform — is always the project's; the catalog never names a technology.

## Catalog (version 2026.09)

| id | Pillar | Question | From profile |
|---|---|---|---|
| `arquitetura` | Arquitetura e fronteiras | How is the system split and which dependencies are forbidden? | mínimo |
| `testes` | Estratégia de testes | Which test levels, where they run, what is mandatory? | mínimo |
| `qualidade-codigo` | Qualidade de código | Do formatting, lint, types and static analysis run automatically? | mínimo |
| `entrega` | Entrega contínua e ambientes | How does code reach production, and how does it roll back? | mínimo |
| `fluxo-mudanca` | Fluxo de mudança | How do changes enter the main branch and who reviews? | mínimo |
| `segredos-dados` | Segredos e dados sensíveis | Where do credentials live and how is personal data protected? | mínimo |
| `seguranca-acesso` | Identidade e acesso | How do users and services authenticate, and what may each do? | padrão |
| `dependencias` | Dependências e ciclo de vida da stack | How are vulnerabilities, updates and end-of-life handled? | padrão |
| `observabilidade` | Observabilidade | How do we know the system is healthy or broken? | padrão |
| `resiliencia` | Resiliência e recuperação | Backups, recovery time, fault tolerance? | padrão |
| `dados-migracoes` | Dados e migrações | How does the schema evolve without breaking running versions? | padrão |
| `custo` | Custo | What does it cost to run, under which assumptions, how is it tracked? | padrão |
| `desempenho-escala` | Desempenho e escala | Which load and latency targets, and how are they verified? | rigoroso |
| `acessibilidade-conformidade` | Acessibilidade e conformidade | Which accessibility, legal and sector rules apply? | rigoroso |

**Profiles** (`pillars.profile` in `sdd-config.yml`): `minimo` for prototypes and personal tools, `padrao` for regular products, `rigoroso` for sensitive data, finance, health, or products with a UI that must meet accessibility law. A project may add its own pillars in `pillars.extra` (an organization can keep its standard there).

## How it is used

- **Coverage:** `spec_graph.py pillars` lists each required pillar as covered (accepted ADR), proposed (ADR awaiting approval), waived (`pillars.waived.<id>: "reason"`) or **without decision**, with why it matters and how to fix it. `status` and `INDEX.md` show the gaps; `validate` warns.
- **Baseline ADRs:** `new-adr --baseline <id>` creates the pillar's ADR from `references/adr-baseline/<id>.md`: **verifiable rules** already written (e.g. "logs estruturados com ID de correlação", "segredos nunca no repositório, varredura no CI"), with blanks for the project's tool choices. It is always `proposed`; it becomes `accepted` only with the human's approval, like any ADR. Edit the rules to fit the product — removing one requires recording why.
- **Greenfield:** in DISCOVER, set the profile from the product framing; the foundation epic ships with one ADR per required pillar (baseline or own). A foundation epic **cannot pass G0** while a required pillar has no decision.
- **Brownfield:** opt-in. With a profile set, first write as-is ADRs for what already exists (declaring their `pillars`), then baseline ADRs as targets for the gaps, each gap closed by a spec (a `migration` spec when it changes existing architecture). Nothing changes without an approved spec.
- **Recurring N/A:** when G3 (architecture) or G6 (deploy) is N/A in 3 or more specs and the pillar isn't waived, the gap is permanent, not temporary: `validate` and `pillars` say so. Either create the spec that closes it or record the waiver with its reason.

The check proves a decision **exists**, not that it is good or implemented — that remains the job of each ADR's `enforced_by`, the gates and the review.
