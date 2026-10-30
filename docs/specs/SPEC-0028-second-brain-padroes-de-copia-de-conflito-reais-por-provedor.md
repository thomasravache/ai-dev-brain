---
id: SPEC-0028
title: "second-brain: padrões de cópia de conflito reais por provedor"
tier: lite
type: feature
user_facing: false
status: proposed
created: 2026-10-30
parent:
depends_on: [SPEC-0023]
consumes_contract: []
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/references/providers.md, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0008]
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0028 — second-brain: padrões de cópia de conflito reais por provedor

## 1. Problema
O `lint` (SPEC-0023, Emenda v2) detecta cópias de conflito só com padrões genéricos, como `Nota (1).md` e `Nota conflict ….md`, iguais para os quatro provedores e marcados em `references/providers.md` como não conferidos. Cópias no formato real de cada provedor podem não ser detectadas. Exemplos prováveis, ainda não conferidos: sufixo com o nome da máquina no OneDrive e `Nota 2.md` no iCloud.

## 2. Causa Raiz
Para conferir os padrões, é preciso ter cópias de conflito reais criadas por cada provedor. Elas só podem ser geradas nos aparelhos do usuário: editar a mesma nota em dois aparelhos sem sincronizar. Isso não dá para fazer na máquina de desenvolvimento. Essa parte foi separada da SPEC-0027 a pedido do usuário (2026-10-30).

## 3. Mudança Proposta
Com os nomes reais em mãos:
- registrar um padrão por provedor conferido em `CONFLICT_PATTERNS`, mantendo os genéricos como reforço;
- registrar em `references/providers.md` o nome de exemplo, a data e o aparelho usado na conferência.

Provedor que não for conferido continua só com os padrões genéricos, marcados como tal.

NÃO muda: as regras, as severidades e os formatos do `lint`.

**Padrão seguido:** `CONFLICT_PATTERNS` e `check_conflict_copy` da SPEC-0023, e os testes `test_lint.py`.

**Rollback:** `git revert` do commit.

**Outras ocorrências:** Nenhuma.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — os testes da SPEC-0023 fixam o comportamento genérico.
- **UT-01** — Dado o nome real de cópia de conflito informado para cada provedor conferido, ao lado do original, quando `check_conflict_copy` roda com os padrões padrão daquele provedor, então a cópia é detectada; e uma nota legítima com nome parecido (sem original ao lado) não é.

## 5. Questões em Aberto
- [ ] Em quais provedores você consegue gerar uma cópia de conflito real (editar a mesma nota em dois aparelhos sem sincronizar) e me passar o nome exato do arquivo que o provedor criou? (thomas)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->

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
