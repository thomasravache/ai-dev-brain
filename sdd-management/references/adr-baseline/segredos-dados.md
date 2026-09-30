---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [segredos-dados]
baseline: segredos-dados@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Segredos e dados sensíveis" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Credencial em código ou log e dado pessoal sem controle são as falhas de segurança e de conformidade mais comuns. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Nenhum segredo no repositório; varredura de segredos no CI bloqueia o merge.
- Segredos ficam em {{gerenciador de segredos}}, separados por ambiente, com acesso mínimo.
- Rotação de credenciais a cada {{periodicidade}} e imediata em caso de vazamento.
- Dados pessoais classificados, com base legal, finalidade e prazo de retenção registrados.
- Dados pessoais e segredos nunca aparecem em logs (mascaramento verificado por teste).
- Criptografia em trânsito e em repouso.

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Varredura de segredos em `security_scan`; teste de mascaramento de logs no plano de testes.

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: OWASP ASVS; LGPD/GDPR. {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
