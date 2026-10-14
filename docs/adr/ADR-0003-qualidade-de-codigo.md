---
id: ADR-0003
title: Qualidade de código
status: proposed
origin: decision
date: 2026-10-14
pillars: [qualidade-codigo]
baseline: qualidade-codigo@2026.09
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0001
---

# ADR-0003 — Qualidade de código

## Contexto e Problema
Sem formatação e lint automáticos, cada revisão gasta tempo com estilo e erros simples (variável não usada, import esquecido) passam. O `spec_graph.py` tem ~3.300 linhas e nenhuma checagem automática hoje.

## Direcionadores da Decisão
- A ferramenta de qualidade roda só na CI e na máquina de quem desenvolve; o script continua sem dependências (ADR-0001).
- Um projeto pessoal pequeno: uma ferramenta só, rápida e com pouca configuração.

## Opções Consideradas
- **A — Ruff** (lint + formatação numa ferramenta).
- **B — flake8 + black**.
- **C — nenhuma** (dispensar o pilar).

## Resultado da Decisão
**Opção escolhida:** A, porque faz lint e formatação numa ferramenta só, sem dependências no script e com configuração mínima.

**Regras (verificáveis):**
- `ruff check` sem erros nas regras configuradas, rodando na CI.
- Configuração do Ruff versionada na raiz do repositório, com `target-version` = Python 3.9.
- Suprimir uma regra exige comentário com o motivo na própria linha; supressão sem motivo é achado do revisor.
- Formatação automática (`ruff format --check`): adiada — reformatar 3.300 linhas agora geraria um diff enorme sem mudança de comportamento. Fica como dívida a decidir em spec própria.
- Checagem de tipos e SAST: fora do perfil mínimo; reavaliar se o script passar a lidar com credenciais ou entrada não confiável.

### Consequências
- **Boa**, porque erros simples são pegos antes da revisão.
- **Ruim**, porque a primeira adoção pode exigir ajustes no código existente para zerar os achados, e a formatação fica para depois.

### Confirmação (G3)
Comando `lint` do sdd-config (`ruff check`) na CI e no G2; configuração em `ruff.toml` — criados pela SPEC-0001.

## Prós e Contras das Opções
| Critério (peso) | A — Ruff | B — flake8 + black | C — nenhuma |
|---|---|---|---|
| Ferramentas a manter (2) | 1 | 2 | 0 |
| Velocidade (1) | alta | média | — |
| Erros pegos antes da revisão (3) | sim | sim | não |

## Mais Informações
Referências neutras: documentação oficial do Ruff (docs.astral.sh/ruff). Fontes: https://docs.astral.sh/ruff/ e https://pypi.org/project/ruff/ (consultado em 2026-10-14). Versão: Ruff 0.17.0, conferida no mesmo dia com `uvx ruff --version`. Uso local: `uvx ruff check`.
