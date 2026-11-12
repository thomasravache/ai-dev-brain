---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [observabilidade]
baseline: observabilidade@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Observabilidade" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Sem sinais e metas definidos, problemas em produção são descobertos pelo usuário e o rollback vira decisão no escuro. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Logs estruturados com ID de correlação que atravessa as chamadas.
- Métricas de requisição (taxa, erro, duração) e de recurso para cada serviço.
- Traces distribuídos quando houver mais de um processo envolvido numa requisição.
- Health check em cada serviço implantável.
- SLI e SLO para as jornadas críticas, com orçamento de erro.
- Alertas disparam por SLO; cada alerta tem responsável e procedimento curto (runbook).
- Cada Plano de Rollout define o limite numérico que dispara rollback durante a observação do deploy.
- Nenhum dado pessoal ou segredo em logs, métricas ou traces.

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Instrumentação com {{biblioteca/padrão}}; teste de integração do health check; limite de rollback verificado no G6.

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: OpenTelemetry (padrão aberto de instrumentação); Google SRE (SLI, SLO, orçamento de erro). {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
