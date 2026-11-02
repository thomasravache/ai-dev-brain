---
id: SPEC-0045
title: "sdd-management: teste de tempo do leak-check tolerante à carga"
tier: lite
type: fix
user_facing: false
status: proposed
created: 2026-11-02
parent:
depends_on: []
consumes_contract: []
touches: [skills/sdd-management/tests/test_private_mode.py]
adrs: []
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0045 — sdd-management: teste de tempo do leak-check tolerante à carga

## 1. Problema
`SPEC-0004:IT-10` (`test_private_mode.LeakCheckCommandTest.test_fifty_commits_in_under_two_seconds`) exige que `leak-check --range` sobre 50 commits termine em menos de 2 s de relógio. Numa máquina com load average entre 5 e 13 ele levou 2,7 s, 3,0 s e 3,8 s, falhando também na `main`, sem nenhuma mudança na sdd-management. Como os comandos `test` do `sdd-config.yml` encadeiam as suítes com `&&`, essa falha derruba o `gate --run` de G1, G2 e G5 de qualquer spec e interrompe a cadeia antes das outras suítes (SPEC-0034 e SPEC-0035 tiveram o G5 registrado como manual por isso).

## 2. Causa Raiz
O teste mede tempo de relógio do processo inteiro (Python + git em subprocesso), que depende da carga da máquina, contra um limite fixo pensado para máquina ociosa.

## 3. Mudança Proposta
- O teste passa a medir o tempo do `leak-check` em relação a uma linha de base medida na mesma execução (por exemplo, `git log` do mesmo intervalo) e exige que fique abaixo de um múltiplo dela, ou aceita uma variável de ambiente (`SDD_PERF_FACTOR`) que multiplica o limite; a meta de 2 s da SPEC-0004 continua documentada.
- **Não muda:** o `leak-check`, a meta de desempenho da SPEC-0004.

**Padrão seguido:** os demais testes de `test_private_mode.py`.

**Rollback:** reverter o commit.

**Outras ocorrências:** procurar outros `assertLess(elapsed, …)` nas suítes (`second-brain`, `org-atlas`: o teste de 1.000 Applications da SPEC-0035) e aplicar a mesma regra se tiverem o mesmo risco.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — o teste existente é o próprio objeto.
- **UT-01** — Dado uma execução lenta simulada (linha de base também lenta, ou `SDD_PERF_FACTOR=3`), quando o teste de desempenho roda, então não falha por carga; dado um `leak-check` artificialmente 10× mais lento que a linha de base, então falha.
- Integração/E2E: N/A — mudança só no teste.

## 5. Questões em Aberto
- [ ] Linha de base relativa ou fator por variável de ambiente? (thomas)

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
