---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [dados-migracoes]
baseline: dados-migracoes@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Dados e migrações" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Migração de schema acoplada ao deploy quebra rollback e derruba versões antigas ainda em execução. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Migrações versionadas no repositório e executadas pelo pipeline.
- Toda migração é compatível com a versão anterior da aplicação (expand, migrar, contract).
- Migrações são testadas em testes de integração contra o banco real.
- Cada migração destrutiva tem plano de rollback de dados documentado na spec.

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Teste de integração de migração; Plano de Rollout das specs com mudança de schema.

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: Padrão expand/contract (parallel change). {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
