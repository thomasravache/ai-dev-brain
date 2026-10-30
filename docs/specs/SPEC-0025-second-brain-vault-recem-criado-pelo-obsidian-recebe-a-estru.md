---
id: SPEC-0025
title: "second-brain: vault recém-criado pelo Obsidian recebe a estrutura padrão"
tier: lite
type: feature
user_facing: false
status: approved
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
- Caracterização: N/A — o IT-09 da SPEC-0017 fixa a recusa para pastas com notas e continua valendo.
- **UT-01** — Dado uma pasta com `.obsidian/app.json` e `.DS_Store`, quando a checagem de pasta vazia roda, então a pasta conta como vazia; com mais um `nota.md`, deixa de contar.
- **IT-01** — Dado uma pasta com só `.obsidian/` (com arquivos dentro), quando roda `init --vault P --files F --provider icloud`, então a estrutura padrão é criada, o conteúdo e a data de modificação de `.obsidian/` não mudam e o exit é 0.

## 5. Questões em Aberto
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [ ] Red: UT-01 e IT-01 com a tag `SPEC-0025:<ID>`, falhando pelo motivo certo
- [ ] Green: pasta só com `.obsidian/` conta como vazia; `SKILL.md` e `vault-layout.md` citam o caso
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] Seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy (G6) — N/A: pilar entrega dispensado
- [ ] Relatório de Entrega e CHANGELOG (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PENDING | | |
| G1 Red | PENDING | | |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue

### Como foi feito

### Prova de Correção
<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Teste de regressão falhou antes e passa depois da correção
- [ ] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão existente mantido
- [ ] Disponível no ambiente-alvo via pipeline (G6)
- [ ] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [ ] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy

### Pendências

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
