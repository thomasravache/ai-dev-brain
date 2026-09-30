---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [acessibilidade-conformidade]
baseline: acessibilidade-conformidade@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Acessibilidade e conformidade" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Acessibilidade e exigências legais tratadas no fim do projeto custam retrabalho e expõem a risco jurídico. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Interfaces atendem WCAG 2.2 nível AA nas jornadas do produto.
- Verificação automática de acessibilidade no CI mais revisão manual das jornadas críticas.
- Normas legais e do setor que se aplicam estão listadas, com como cada uma é atendida.
- Termos, consentimento e direitos do titular dos dados implementados quando exigidos.
- Auditoria ou evidência de conformidade registrada quando o setor exigir.

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Verificação automática de acessibilidade {{ferramenta}} no CI; checklist de conformidade na revisão.

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: WCAG 2.2; LGPD/GDPR; normas do setor. {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
