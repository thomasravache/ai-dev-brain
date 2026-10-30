---
id: ADR-0012
title: Curadoria de convenções do atlas
status: accepted
origin: decision
date: 2026-10-30
pillars: [arquitetura]
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0037
---

# ADR-0012 — Curadoria de convenções do atlas

## Contexto e Problema
O atlas infere convenções a partir do que a organização faz (padrão de título de PR, de branch, de commits, estrutura de pastas). Se metade dos PRs é bagunçada, a inferência transforma bagunça em padrão, e outras skills (a `sdd-management`, um implementer) passam a seguir isso como regra. Precisamos decidir como uma convenção inferida vira regra.

## Direcionadores da Decisão
- Inferir é dica; regra só com decisão humana.
- A decisão precisa ser auditável (quem, quando, por onde).
- Funcionar no modo repositório e no modo local (SPEC-0040).
- Uma convenção rejeitada não pode voltar a ser proposta a cada scan.

## Opções Consideradas
- **A — Status no arquivo da convenção, confirmado por humano** (`inferred` → `confirmed` ou `rejected`).
- **B — Confirmação automática acima de um limite** (ex.: 80% dos PRs seguem).
- **C — Confirmação num tracker externo** (issue ou ticket aprovado).

## Resultado da Decisão
**Opção escolhida:** A, porque deixa a decisão com o humano, fica versionada no git do atlas e não depende de outra ferramenta. O limite da opção B vira só a evidência mostrada na proposta.

**Regras (verificáveis):**
- Cada convenção é um arquivo `conventions/<slug>.md` com frontmatter: `id`, `title`, `scope` (organização, categoria ou serviço), `status` (`inferred` | `confirmed` | `rejected`), `evidence` (fonte, total, quantos seguem, amostra), `proposed_at`, `confirmed_by`, `confirmed_at`, `confirmed_via`.
- O `atlas.py` só cria convenções `inferred`. Só o comando `curate confirm` (ou `curate reject`) muda o status, e exige `--by` e `--via`.
- **Modo repositório:** a confirmação vale quando o PR do atlas que muda o status é aprovado; `--via "PR #n"`. **Modo local:** quem roda `curate confirm`; `--via local`.
- Só convenção `confirmed` é regra para outras skills. O `context` mostra as `inferred` separadas e marcadas como dica; as `rejected` não aparecem e não são propostas de novo enquanto a evidência não mudar de forma significativa (a proposta guarda a evidência que foi rejeitada).
- O texto escrito por pessoas no arquivo da convenção nunca é reescrito; só a região gerada `<!-- atlas:begin evidence -->` é atualizada.

### Consequências
- **Boa**, porque nenhuma regra nasce sem humano, e a história de cada convenção fica no git.
- **Ruim**, porque a curadoria vira trabalho do time; mitigado pelo `lint`, que lista as convenções esperando decisão (SPEC-0039).

### Confirmação (G3)
Testes da SPEC-0037: nenhum comando além de `curate confirm`/`reject` grava `status: confirmed`/`rejected`; `confirm` sem `--by` ou `--via` falha; o `context` (SPEC-0038) separa `inferred` de `confirmed`.

## Prós e Contras das Opções
| Critério (peso) | A — status + humano | B — automático por limite | C — tracker externo |
|---|---|---|---|
| Regra só com decisão humana (3) | sim | não | sim |
| Auditável no git do atlas (2) | sim | sim | não |
| Sem depender de outra ferramenta (2) | sim | sim | não |
| Pouco trabalho para o time (1) | não | sim | não |

## Mais Informações
ADR-0010 (fronteiras), ADR-0011 (sinais que viram evidência). Fontes: não verificado — decisão de processo, sem ferramenta externa.
