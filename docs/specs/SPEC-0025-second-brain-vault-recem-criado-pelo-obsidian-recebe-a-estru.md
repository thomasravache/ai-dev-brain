---
id: SPEC-0025
title: "second-brain: vault recém-criado pelo Obsidian recebe a estrutura padrão"
tier: lite
type: fix
user_facing: false
status: in-progress
created: 2026-10-30
parent: SPEC-0016
depends_on: [SPEC-0017]
consumes_contract: []
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/vault-layout.md, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007]
external: []
size: S
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0025 — second-brain: vault recém-criado pelo Obsidian recebe a estrutura padrão

## 1. Problema
Quem cria o vault primeiro no app do Obsidian fica com uma pasta que só tem `.obsidian/`. Pela Emenda v2 da SPEC-0017, o `init` trata essa pasta como "não vazia" e pede `--adopt`. Mas o `--adopt` não cria as pastas de PARA nem `mocs/`, e o vault novo fica sem a estrutura padrão. Quem achou o problema foi a revisão G4 da SPEC-0017 (achado minor 1).

## 2. Causa Raiz
Em `skills/second-brain/scripts/brain.py`, a checagem de pasta vazia ignora só arquivos do sistema (`OS_METADATA`: `.DS_Store`, `Thumbs.db`, `desktop.ini`) e conta `.obsidian/` como conteúdo do usuário.

## 3. Mudança Proposta
Uma pasta cujo único conteúdo, fora de `OS_METADATA`, é `.obsidian/` conta como vazia para o `init`. O `init` cria a estrutura padrão completa e não altera nada dentro de `.obsidian/`. Qualquer outro arquivo ou pasta continua exigindo `--adopt`. O `SKILL.md` e o `references/vault-layout.md` passam a citar esse caso.

NÃO muda: o `--adopt`, a recusa de `log.md` e `index.md` do usuário e as demais regras da Emenda v2.

**Padrão seguido:** a função de pasta vazia e `OS_METADATA` do `brain.py`, e os testes `test_amendment_v2.py::NotEmptyWithoutAdoptTest`.

**Rollback:** `git revert` do commit.

**Outras ocorrências:** Nenhuma.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — o teste de pasta com notas da Emenda v2 da SPEC-0017 fixa a recusa e continua valendo.
- **UT-01** — Dado uma pasta com `.obsidian/app.json` e `.DS_Store`, quando a checagem de pasta vazia roda, então a pasta conta como vazia; com mais um `nota.md`, deixa de contar.
- **IT-01** — Dado uma pasta com só `.obsidian/` (com arquivos dentro), quando roda `init --vault P --files F --provider icloud`, então a estrutura padrão é criada, o conteúdo e a data de modificação de `.obsidian/` não mudam e o exit é 0.

## 5. Questões em Aberto
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01 e IT-01 com a tag `SPEC-0025:<ID>`, falhando pelo motivo certo
- [x] Green: pasta só com `.obsidian/` conta como vazia; `SKILL.md` e `vault-layout.md` citam o caso
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] Seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy (G6) — N/A: pilar entrega dispensado
- [x] Relatório de Entrega e CHANGELOG (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 1304494 | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=2)) — 608f572 | 2026-10-30 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — c9ca851 | 2026-10-30 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — c9ca851 | 2026-10-30 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (c9ca851; 3 minor, sem bloqueio) — c9ca851 | 2026-10-30 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 6b4621b | 2026-10-30 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-10-30 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): skill distribuída por cópia da pasta, sem deploy | 2026-10-30 |
| G7 Pronto & Docs | PENDING | | |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
Quem cria o vault primeiro no app do Obsidian, com uma pasta que só tem `.obsidian/`, roda `init` e recebe a estrutura padrão completa, sem precisar de `--adopt`. Nada dentro de `.obsidian/` é alterado.

### Como foi feito
`brain.py` (versão 2026.10.9) ganhou `is_empty_vault(folder)`, usado só pelo `init`: a pasta é vazia quando só tem arquivos do sistema (`OS_METADATA`) e o diretório `.obsidian`. A regra do `--out` da exportação não mudou. `SKILL.md`, `references/vault-layout.md` e o CHANGELOG citam o caso. A revisão G4 aprovou com 3 minor informativos. O tipo da spec foi corrigido para `fix`.

### Prova de Correção
<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
Red 608f572: com os testes UT-01 e IT-01, a suíte da skill tinha 2 falhas (`is_empty_vault` não existia; o `init` saía com "vault não está vazio — use --adopt"), registrado no G1. Green 631f10a: as duas passam e a suíte completa passa (G2 em c9ca851, G5 e CI do PR #15).

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Pasta só com .obsidian/ e .DS_Store conta como vazia; com uma nota, não | PASS | `test_obsidian_vault.py::EmptyVaultCheckTest.test_only_obsidian_and_os_metadata_counts_as_empty_and_a_note_does_not` — CI do PR #15 em 6b4621b (run 41098462098, Python 3.9 e 3.15) e suíte local (G5) |
| IT-01 | init num vault criado pelo app do Obsidian cria a estrutura sem tocar em .obsidian/ | PASS | `test_obsidian_vault.py::ObsidianVaultInitTest.test_init_in_a_vault_created_by_obsidian_creates_the_structure_and_keeps_obsidian` — CI do PR #15 em 6b4621b (run 41098462098, Python 3.9 e 3.15) e suíte local (G5) |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão existente mantido
- [x] Disponível no ambiente-alvo via pipeline (G6)
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [x] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy
Sem deploy próprio (pilar entrega dispensado). Passa a valer na `main` com o merge do PR #15. Versão da skill: 2026.10.9. Rollback: revert do merge.

### Pendências
Nenhuma.

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
