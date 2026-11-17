---
id: ADR-0020
title: Nomes técnicos novos com leitura dupla e remoção anunciada
status: accepted
origin: decision
date: 2026-11-16
pillars: []
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by:
---

# ADR-0020 — Nomes técnicos novos com leitura dupla e remoção anunciada

<!-- Formato MADR (Markdown Architectural Decision Records). status: proposed | accepted | rejected | deprecated | superseded — vira accepted quando a spec que o introduz é aprovada (H1); superseded exige superseded_by. origin: decision (recomendada: compare 2–3 opções e cite fontes com data, ou declare "não verificado") | user (escolhida pelo usuário: respeite, sem reabrir a discussão, e registre riscos e custo) | as-is (documenta um padrão que já existe no projeto). enforced_by: teste de arquitetura que garante a decisão (G3), ou "N/A — motivo". -->

## Contexto e Problema
A SPEC-0055 (ADR-0018) renomeou as skills para `gluon-spec`, `photon-brain` e `boson-atlas`, mas manteve de propósito os nomes técnicos antigos — `~/.config/second-brain`, `~/.config/org-atlas`, `.org-atlas/` nos atlas, o contrato `org-atlas/collector@1`, mensagens e nomes de backup — para não quebrar instalações. Como aposentar esses nomes sem quebrar nenhuma máquina, vault, atlas ou coletor? Referências: `skills/photon-brain/scripts/brain.py` (`local_config_path`, `NOT_CONFIGURED`), `skills/boson-atlas/scripts/atlas.py` (`CONTRACT`, `.org-atlas/skill`).

## Direcionadores da Decisão
- Nada configurado pode quebrar numa atualização (ADR-0018).
- O plugin nunca muda arquivos da pessoa sozinho (ADR-0019).
- Coletores de terceiros seguem o contrato publicado (ADR-0011).

## Opções Consideradas
- Troca direta, com migração automática na primeira execução.
- Leitura dupla (novo primeiro, antigo como reserva), gravação só no novo, aviso do `doctor` e remoção anunciada.
- Manter os nomes antigos para sempre.

## Resultado da Decisão
**Opção escolhida:** "Leitura dupla com remoção anunciada", porque é a única que não quebra nada (troca direta move arquivos da pessoa, contra o ADR-0019) e ainda termina com um nome só (manter para sempre deixa a confusão de dois nomes).

### Consequências
- **Boa**, porque nenhuma instalação quebra e o caminho da migração fica visível no `doctor`.
- **Ruim**, porque o código carrega a leitura dupla até a versão de remoção.

### Confirmação (G3)
Testes por filha: nenhuma gravação em caminho antigo; a guarda de nomes antigos (`tests/plugin/test_skill_names.py`) passa a cobrir os nomes técnicos, com exceção só para a leitura de compatibilidade.

## Prós e Contras das Opções
<!-- Decisão de tecnologia: matriz com critérios ponderados pelo contexto (references/greenfield.md). as-is: "N/A". -->
| Critério | Troca direta | Leitura dupla | Manter |
|---|---|---|---|
| Nada quebra | não (move arquivos) | sim | sim |
| Um nome só no fim | sim | sim | não |
| Respeita ADR-0019 | não | sim | sim |

## Mais Informações
<!-- Fontes oficiais consultadas, versão estável/LTS e janela de suporte, com a data da verificação. Se não foi possível verificar, diga explicitamente. Links para specs relacionadas. -->
SPEC-0067 (épico); README, seção dos nomes antigos — 2026-11-16
