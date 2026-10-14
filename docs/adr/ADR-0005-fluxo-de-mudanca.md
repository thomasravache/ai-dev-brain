---
id: ADR-0005
title: Fluxo de mudança e versionamento da skill
status: proposed
origin: decision
date: 2026-10-14
pillars: [fluxo-mudanca]
baseline: fluxo-mudanca@2026.09
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: N/A — repositório privado no plano gratuito do GitHub não tem proteção de branch; `validate` aponta commits diretos e merges fora de PR
---

# ADR-0005 — Fluxo de mudança e versionamento da skill

## Contexto e Problema
Push direto e merges locais tiram a revisão e os checks do caminho, e a rastreabilidade entre spec, código e entrega se perde. Até 2026-10-14 todos os 23 commits entraram direto na `main`. A skill é usada por link simbólico (`~/.claude/skills/sdd-management` aponta para o checkout principal), então o que entra na `main` passa a valer na hora em todas as sessões — inclusive para julgar os gates das próximas mudanças.

## Direcionadores da Decisão
- Um único mantenedor humano, com agentes de IA escrevendo o código.
- Repositório privado no GitHub gratuito: CI disponível, proteção de branch não.
- Dogfooding: a skill deve exercitar `pr` e `pr-check` no próprio repositório.

## Opções Consideradas
- **A — PR com merge commit, revisão do mantenedor** (`change_flow: pr`).
- **B — Commit direto na `main`** (`change_flow: direct`, com motivo).

## Resultado da Decisão
**Opção escolhida:** A, porque separa quem escreve (agente) de quem aprova (humano) e testa `pr`/`pr-check` no uso real.

**Regras (verificáveis):**
- Toda mudança entra na `main` por PR — código, specs, ADRs e registros do SDD incluídos.
- Checks `sdd` e `ci` verdes e revisão do mantenedor antes do merge. Sem proteção de branch disponível, a regra vale por disciplina; `validate` aponta desvios.
- Sem push direto nem force-push na `main`.
- Merge com merge commit (sem squash), para as evidências dos gates continuarem válidas.
- Correção urgente segue o mesmo caminho, com spec lite criada na hora e revisão acelerada.
- **Versão da ferramenta:** toda mudança de comportamento do `spec_graph.py` atualiza `SDD_TOOL_VERSION` e o `CHANGELOG.md` no mesmo PR.
- **Cópia julgadora:** `tools/sdd/spec_graph.py` (usada pela CI) só é atualizada por `vendor` num PR próprio (`chore: atualiza tools/sdd para <versão>`), depois do merge da mudança. Um PR que muda o script nunca é julgado pela própria versão alterada.
- **Rollback:** `git revert` do merge na `main`; o link simbólico passa a usar a versão anterior imediatamente.

### Consequências
- **Boa**, porque o agente não aprova o próprio trabalho e o fluxo de PR do SDD é testado de verdade.
- **Ruim**, porque cada mudança custa um PR e uma revisão; sem proteção de branch, nada impede tecnicamente um push direto. Removidas do modelo: a regra de dono obrigatório para arquivos de controle (CODEOWNERS), sem efeito com um único mantenedor e sem proteção de branch.

### Confirmação (G3)
`change_flow: pr` no sdd-config; `validate` aponta commits diretos e merges sem PR; job `sdd` (`.github/workflows/sdd.yml`) roda `pr-check` em todo PR.

## Prós e Contras das Opções
| Critério (peso) | A — PR | B — direto |
|---|---|---|
| Separação de quem faz e quem aprova (3) | sim | não |
| Exercita `pr`/`pr-check` (2) | sim | não |
| Velocidade (1) | menor | maior |

## Mais Informações
Referências neutras: práticas de trunk-based development. Fontes: não verificado na documentação — a falta de proteção de branch foi constatada pela resposta 403 da API do GitHub em 2026-10-14 ("Upgrade to GitHub Pro or make this repository public").
