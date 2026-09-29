---
id: {{id}}
title: {{title}}
tier: lite
type: fix
user_facing: false
status: proposed
created: {{created}}
parent:
depends_on: []
consumes_contract: []
touches: []
adrs: []
size: S
approved_by:
approved_at:
---

# {{id}} — {{title}}

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
{{Comportamento atual vs. esperado. Para bug: passos de reprodução, ambiente e impacto.}}

## 2. Causa Raiz
{{Causa identificada no código (arquivo/trecho e por que falha). Corrija a causa, não o sintoma. Para melhoria pequena: contexto técnico.}}

## 3. Mudança Proposta
{{O que muda e o que explicitamente NÃO muda.}}

**Padrão seguido:** {{arquivos de referência do padrão existente que a correção respeita}}

**Rollback:** {{revert do commit | outro procedimento}}

**Outras ocorrências:** {{o mesmo defeito existe em outro lugar? liste como novas specs | Nenhuma}}

## 4. Plano de Testes (TDD)
<!-- Mínimo: um teste de regressão que reproduz o problema e FALHA antes da correção, no nível em que o defeito aparece (IT para fronteiras de I/O, E2E para jornadas de usuário). Código sem cobertura: primeiro CH-xx fixando o comportamento atual. Tag no código: `{{id}}:<ID>`. Categoria sem teste: "N/A — motivo" SEM ID. -->
- {{CH-01 — comportamento atual preservado | Caracterização: N/A — área já coberta}}
- **UT-01** — {{teste de regressão: Dado..., quando..., então...}}
- {{IT-01 ou E2E-01 — regressão no nível do defeito | Integração/E2E: N/A — motivo}}

## 5. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 6. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->

## 7. Registro de Gates
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

## 8. Relatório de Entrega
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
