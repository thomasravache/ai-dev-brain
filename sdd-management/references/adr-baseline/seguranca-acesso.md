---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [seguranca-acesso]
baseline: seguranca-acesso@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Identidade e acesso" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Autenticação e autorização improvisadas em cada tela ou endpoint geram brechas difíceis de achar depois. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Autenticação centralizada em {{provedor/abordagem}}; sem senha armazenada em texto nem hash fraco.
- Autorização negada por padrão; cada permissão é explícita.
- Menor privilégio para usuários, serviços e credenciais de CI.
- Sessões e tokens com expiração e revogação.
- O plano de testes de cada spec com regra de acesso inclui o caso de acesso negado.
- Os riscos do OWASP Top 10 aplicáveis são checados na revisão (G4).

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Testes de autorização (acesso negado) nas specs; checklist de segurança no G4.

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: OWASP ASVS, OWASP Top 10. {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
