---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [entrega]
baseline: entrega@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Entrega contínua e ambientes" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Sem caminho automatizado até produção, o produto fica 'pronto' sem nunca chegar ao usuário, e cada deploy vira evento de risco. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Um único pipeline leva do commit à produção; nada é publicado fora dele.
- A branch principal está sempre em estado publicável.
- Staging é atualizado automaticamente a cada merge, com smoke e E2E contra ele.
- Produção exige confirmação humana por release; estratégia (direta, flag, canário, blue-green) definida por spec.
- Rollback em um passo, ensaiado; mudanças de dados compatíveis com a versão anterior.
- Métricas DORA acompanhadas: frequência de deploy, tempo de entrega, taxa de falha, tempo de recuperação.

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Pipeline {{plataforma de CI/CD}}; `deploy_staging`, `deploy_production` e `smoke_test` no sdd-config (G6).

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: DORA (Accelerate), Twelve-Factor App. {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
