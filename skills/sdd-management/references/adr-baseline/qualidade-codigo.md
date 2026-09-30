---
id: {{id}}
title: {{title}}
status: proposed
origin: decision
date: {{created}}
pillars: [qualidade-codigo]
baseline: qualidade-codigo@2026.09
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# {{id}} — {{title}}

<!-- ADR de base do pilar "Qualidade de código" (catálogo SDD 2026.09). Fixa REGRAS verificáveis; a tecnologia é escolha do projeto (campos com chaves duplas). Ajuste as regras ao produto — remover uma regra exige registrar o motivo em Consequências — ou dispense o pilar em sdd-config.yml (pillars.waived). Só vira accepted com aprovação humana (H1). -->

## Contexto e Problema
Estilo e problemas triviais revisados à mão custam caro e geram inconsistência, principalmente quando parte do código é escrita por agentes. {{Contexto do produto que torna este pilar relevante: porte, usuários, dados, restrições}}

## Direcionadores da Decisão
- {{direcionadores do projeto (enquadramento do produto, orçamento, equipe)}}

## Opções Consideradas
- {{Opção A — ferramenta ou abordagem}}
- {{Opção B}}

## Resultado da Decisão
**Opção escolhida:** {{opção}}, porque {{motivo ligado aos direcionadores}}.

**Regras (verificáveis):**
- Formatador com verificação automática no CI (falha se o código não estiver formatado).
- Linter com regras versionadas no repositório; zero avisos novos nas linhas alteradas.
- Checagem de tipos habilitada no modo mais estrito viável para a linguagem.
- Suprimir uma regra exige comentário com o motivo na própria linha; supressão sem motivo é achado do revisor.
- Análise estática de segurança (SAST) no CI.

### Consequências
- **Boa**, porque {{o que melhora}}
- **Ruim**, porque {{o que custa ou limita}}

### Confirmação (G3)
Comando `lint` (e formatação/tipos) do sdd-config no CI e no G2; configuração em {{arquivos de configuração}}.

## Prós e Contras das Opções
{{| Critério (peso) | Opção A | Opção B |}}

## Mais Informações
Referências neutras: Regras publicadas das próprias ferramentas escolhidas. {{Fontes oficiais das ferramentas escolhidas, com versão e data da verificação | "não verificado" + motivo}}
