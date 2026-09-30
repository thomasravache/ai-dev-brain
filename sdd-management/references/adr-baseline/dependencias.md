---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [dependencias]
baseline: dependencias@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Dependências e ciclo de vida da stack" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Dependências vulneráveis ou fora de suporte viram risco silencioso, e atualizar tudo de uma vez depois fica caro. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Varredura de vulnerabilidades no CI; severidade crítica bloqueia o merge.
- Atualização de dependências automatizada ({{ferramenta}}) com revisão, pelo menos {{periodicidade}}.
- Nenhuma dependência ou runtime fora de suporte (EOL); o calendário de fim de suporte é revisado a cada {{periodicidade}} e cada item vira spec.
- Arquivos de trava de versão (lockfiles) versionados.
- Licenças compatíveis com o uso do produto.

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
`security_scan` no sdd-config e no CI; `verify` avisa manifesto alterado sem ADR.

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: SLSA, OpenSSF Scorecard. {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
