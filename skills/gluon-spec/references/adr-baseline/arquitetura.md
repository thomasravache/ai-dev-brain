---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [arquitetura]
baseline: arquitetura@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Arquitetura e fronteiras" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Sem fronteiras explícitas e verificadas, módulos se acoplam aos poucos e cada mudança passa a exigir mexer em tudo. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Cada módulo expõe um contrato público; os demais só dependem desse contrato.
- As dependências proibidas entre camadas e módulos estão listadas abaixo e são verificadas por teste de arquitetura no CI.
- Não há ciclos de dependência entre módulos.
- Mudar uma fronteira exige um ADR novo (que substitui este).

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Teste de arquitetura {{ferramenta de testes de arquitetura da stack}} em {{caminho}}, rodando no CI (G3).

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: C4 model (diagramas de contexto e contêiner). {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
