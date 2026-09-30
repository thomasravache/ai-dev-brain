---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [testes]
baseline: testes@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Estratégia de testes" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Sem estratégia explícita, os testes ficam desbalanceados (muitos E2E instáveis ou nenhum teste de integração real) e o CI deixa de ser confiável. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Níveis e obrigatoriedade conforme a skill: unitário, integração com dependências reais, contrato entre specs e E2E das jornadas de usuário.
- A suíte completa roda no CI em toda solicitação de mudança.
- As jornadas críticas estão em `critical_journeys` no sdd-config e cada uma tem ao menos um E2E.
- Teste instável é defeito: vai para quarentena por no máximo {{N}} dias com spec aberta para corrigir; nunca retry-até-passar.
- Cobertura das linhas alteradas ≥ {{meta, ex: 80%}} quando a medição estiver configurada.

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Comandos `test`, `test_integration`, `test_e2e` e `coverage` do sdd-config, executados pelo `gate --run` e pelo CI.

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: Pirâmide de testes; references/testing.md da skill. {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
