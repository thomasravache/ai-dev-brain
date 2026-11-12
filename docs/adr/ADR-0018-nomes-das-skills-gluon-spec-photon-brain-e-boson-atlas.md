---
id: ADR-0018
title: "Nomes das skills: gluon-spec, photon-brain e boson-atlas"
status: proposed
origin: user
date: 2026-11-12
pillars: []
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: tests/plugin/test_skill_names.py (SPEC-0055:UT-01 a UT-04)
---

# ADR-0018 — Nomes das skills: gluon-spec, photon-brain e boson-atlas

<!-- Formato MADR (Markdown Architectural Decision Records). status: proposed | accepted | rejected | deprecated | superseded — vira accepted quando a spec que o introduz é aprovada (H1); superseded exige superseded_by. origin: user (recomendada: compare 2–3 opções e cite fontes com data, ou declare "não verificado") | user (escolhida pelo usuário: respeite, sem reabrir a discussão, e registre riscos e custo) | as-is (documenta um padrão que já existe no projeto). enforced_by: tests/plugin/test_skill_names.py (SPEC-0055:UT-01 a UT-04) teste de arquitetura que garante a decisão (G3), ou "N/A — motivo". -->

## Contexto e Problema
O plugin `fermion` (SPEC-0053) mostra cada skill como `/fermion:<pasta>`. Os nomes da marca foram escolhidos em 2026-10-30 (SPEC-0031) e a troca estava prevista para bem depois. Publicar o plugin com os nomes antigos e trocar depois quebraria os comandos de quem instalou.

## Direcionadores da Decisão
- O plugin deve sair com os nomes finais.
- Máquinas, vaults, atlas e projetos já configurados não podem precisar de nenhuma ação.
- Agentes e blocos `AGENTS.md` que pedem o nome antigo continuam achando a skill.

## Opções Consideradas
- A: renomear pasta, `name` e textos de apresentação agora; manter scripts, pastas de configuração, contratos e arquivos gerados; nome antigo como apelido na `description`.
- B: renomear tudo, inclusive configuração e contratos.
- C: publicar com os nomes antigos e renomear depois, com apelidos.

## Resultado da Decisão
**Opção escolhida:** A (escolhida pelo thomas em 2026-11-12), porque o plugin sai com os nomes finais sem migrar dados.

### Consequências
- **Boa**, porque `/fermion:gluon-spec`, `/fermion:photon-brain` e `/fermion:boson-atlas` nascem estáveis, e nada fora do repositório muda.
- **Ruim**, porque convivem nomes novos (skills) e antigos (scripts, `~/.config/org-atlas`, `org-atlas/collector@1`, `.org-atlas/`), o que precisa estar explicado no README e nas skills.

### Confirmação (G3)
`tests/plugin/test_skill_names.py` (SPEC-0055): pastas e `name` novos, apelido na `description`, nenhuma referência ao caminho antigo fora das exceções e identificadores mantidos.

## Prós e Contras das Opções
| Critério (peso) | A | B | C |
|---|---|---|---|
| Plugin com nomes finais (3) | sim | sim | não |
| Nenhuma ação em máquinas e atlas (3) | sim | não | sim |
| Nomes coerentes em todo lugar (1) | não | sim | não |

## Mais Informações
- SPEC-0031 (nomes e por quê), SPEC-0053 (comando vem da pasta: code.claude.com/docs/en/plugins, lido em 2026-11-12), SPEC-0055.
