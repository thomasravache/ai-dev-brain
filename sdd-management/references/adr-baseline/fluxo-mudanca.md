---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [fluxo-mudanca]
baseline: fluxo-mudanca@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Fluxo de mudança" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Push direto e merges locais tiram a revisão e os checks do caminho, e a rastreabilidade entre spec, código e deploy se perde. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Toda mudança entra na branch principal por solicitação de mudança (PR, MR ou equivalente).
- Checks obrigatórios (build, testes, `sdd`) e pelo menos {{N}} revisão humana antes do merge.
- Sem push direto nem force-push na branch principal, inclusive para administradores.
- Merge com merge commit (sem squash), para as evidências dos gates continuarem válidas.
- Arquivos de controle (tools/sdd, sdd-config, ADRs, hooks, workflows) têm dono obrigatório na revisão.
- Correção urgente segue o mesmo caminho, com spec lite criada na hora e revisão acelerada.

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Proteção de branch em {{plataforma}}; `change_flow: pr` no sdd-config; `vendor --codeowners`; `validate` aponta desvios.

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: Práticas de trunk-based development. {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
