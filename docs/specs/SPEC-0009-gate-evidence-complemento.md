---
id: SPEC-0009
title: gate --run grava o complemento de --evidence
tier: lite
type: fix
user_facing: false
status: proposed
created: 2026-10-14
parent:
depends_on: []
consumes_contract: []
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, CHANGELOG.md]
adrs: []
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0009 — gate --run grava o complemento de --evidence

## 1. Problema
A ajuda de `gate` diz que `--evidence` é "texto de evidência (com --manual) ou complemento", mas com `--run` o texto é descartado. Em 2026-10-14 a nota de bypass do G5 sumiu dos registros e foi preciso regravar com `--manual`.

## 2. Causa Raiz
O caminho `--run` de `cmd_gate` monta a evidência só com as partes geradas pela execução; o argumento `evidence` não é passado para esse caminho.

## 3. Mudança Proposta
Com `--run`, `--evidence "<texto>"` entra no fim da evidência gerada como `nota: <texto>`, antes do SHA. Não muda: `--manual`, `--na`, `--fail`, `--by`, nem o PASS/FAIL (a nota nunca altera o resultado).

**Padrão seguido:** montagem de `parts` em `gate_run` (cada parte separada por "; ").

**Rollback:** revert do commit.

**Outras ocorrências:** Nenhuma — os outros caminhos de `gate` já usam o texto.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — `test_run_generates_evidence_and_manual_is_flagged` fixa o caminho `--run` e continua passando.
- **UT-01** — Dado uma spec com G0 pendente, quando roda `gate SPEC-0001 G0 --run --evidence "bypass até amanhã"`, então a linha do G0 tem a evidência gerada, `nota: bypass até amanhã` e o SHA, e o status é o mesmo que sem a nota.
- Integração/E2E: N/A — UT-01 roda o comando pela CLI num repositório temporário.

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

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
