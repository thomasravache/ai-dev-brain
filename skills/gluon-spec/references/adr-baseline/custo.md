---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [custo]
baseline: custo@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Custo" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Custo descoberto só na fatura inviabiliza produtos que funcionam, e escolhas de stack parecem baratas até a escala mudar. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Estimativa mensal antes de escolher hospedagem e serviços, com premissas de uso explícitas e cenários (atual, 2x, 10x).
- Preços verificados na fonte oficial com a data da verificação; se não verificados, isso é declarado.
- A estimativa é comparada com o orçamento informado; estourar exige decisão humana.
- Alerta de gasto configurado em {{valor}} e revisão de custo real a cada {{periodicidade}}.
- Recursos identificados por ambiente e serviço para rastrear o gasto.

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Estimativa neste ADR; alerta de gasto na plataforma {{nome}}; revisão registrada.

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: FinOps Foundation. {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
