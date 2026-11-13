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
touches: [skills/gluon-spec/tests/test_private_mode.py, .claude-plugin/plugin.json]
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
- O teste mede, na mesma execução e logo antes, uma linha de base: o tempo de `python3 -c pass` mais `git log --oneline` do mesmo intervalo de 50 commits (custo de abrir processos, que cresce com a carga como o do `leak-check`). O limite passa a ser `max(2 s, 10 × linha de base)`: em máquina ociosa continua 2 s (meta da SPEC-0004); sob carga cresce junto com a linha de base. A decisão fica numa função pequena do teste (`limite(linha_de_base)`), testada à parte.
- Sem variável de ambiente: o teste se ajusta sozinho, sem configuração na CI.
- **Não muda:** o `leak-check`, a meta de desempenho da SPEC-0004.

**Padrão seguido:** os demais testes de `test_private_mode.py`.

**Rollback:** reverter o commit.

**Outras ocorrências:** procurar outros `assertLess(elapsed, …)` nas suítes (`second-brain`, `org-atlas`: o teste de 1.000 Applications da SPEC-0035) e aplicar a mesma regra se tiverem o mesmo risco.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — o teste existente é o próprio objeto.
- **UT-01** — Dados linha de base de 0,05 s e `leak-check` de 1,5 s, linha de base de 0,4 s (carga) e `leak-check` de 3,8 s, e linha de base de 0,05 s e `leak-check` de 2,5 s, quando a regra `limite(linha_de_base)` é aplicada, então os dois primeiros passam (limites 2 s e 4 s) e o terceiro falha; e o teste real de 50 commits usa essa regra com a linha de base medida na mesma execução.
- Integração/E2E: N/A — mudança só no teste.

## 5. Questões em Aberto
- [x] Linha de base relativa ou fator por variável de ambiente? — Linha de base relativa medida na mesma execução, com piso de 2 s: não exige configuração e continua pegando regressão real (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-13: "pode seguir no piloto automático com o recomendado"; revisável no H1)

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
