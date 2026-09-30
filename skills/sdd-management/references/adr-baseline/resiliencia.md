---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [resiliencia]
baseline: resiliencia@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Resiliência e recuperação" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Backup que nunca foi restaurado não é backup, e falhas de dependências externas derrubam o sistema inteiro quando não há limites. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Backup automático dos dados com restauração testada a cada {{periodicidade}}.
- RPO (perda máxima de dados) e RTO (tempo máximo de recuperação) definidos: {{valores}}.
- Chamadas externas com timeout e retry com backoff; nunca espera indefinida.
- Operações repetíveis são idempotentes.
- Falha de dependência não crítica degrada a funcionalidade em vez de derrubar o sistema.

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Teste de restauração registrado; testes de integração para timeout e idempotência.

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: Google SRE; AWS/Azure/GCP Well-Architected (pilar de confiabilidade). {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
