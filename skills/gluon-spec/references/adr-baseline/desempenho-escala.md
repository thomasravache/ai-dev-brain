---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [desempenho-escala]
baseline: desempenho-escala@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Desempenho e escala" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Sem metas numéricas, desempenho só é discutido quando já virou incidente. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Metas de latência e throughput por jornada crítica nos requisitos não-funcionais das specs.
- Teste de carga antes de releases que mudam caminhos críticos, com o resultado registrado.
- Limites e quotas para proteger o sistema de picos e abuso.
- Cache, filas e escala horizontal só quando uma meta exigir, registrados em ADR.

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Teste de carga {{ferramenta}} com critério de aprovação; RNFs com metas nas specs.

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: Métodos RED/USE. {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
