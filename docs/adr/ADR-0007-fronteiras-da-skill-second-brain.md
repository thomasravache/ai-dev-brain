---
id: ADR-0007
title: Fronteiras da skill second-brain
status: accepted
origin: decision
date: 2026-10-30
pillars: [arquitetura]
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0017
---

# ADR-0007 — Fronteiras da skill second-brain

## Contexto e Problema
O `ai-dev-brain` passa a ter uma segunda skill, `second-brain`, que mantém um vault do Obsidian com uma LLM (SPEC-0016). O ADR-0001 define as fronteiras da `sdd-management`. Precisamos decidir se a skill nova segue as mesmas fronteiras e o que é próprio dela: o vault é conteúdo pessoal do usuário, e a LLM vai criar e alterar notas nele.

## Direcionadores da Decisão
- Funcionar em qualquer máquina e com qualquer agente que leia `SKILL.md`, só com Python 3.9+, sem `pip install` (como o ADR-0001).
- O vault é do usuário: nada pode ser apagado ou sobrescrito sem ele pedir.
- O conteúdo do vault e os caminhos pessoais nunca entram no repositório.
- As duas skills são instaladas separadamente; uma não pode quebrar a outra.

## Opções Consideradas
- **A — Mesmo padrão do ADR-0001, com script próprio** (`skills/second-brain/scripts/brain.py`, arquivo único, só biblioteca padrão).
- **B — Biblioteca compartilhada entre as skills** (ex.: o parser de YAML da `sdd-management` importado pelo `brain.py`).
- **C — Pacote Python com dependências** (PyYAML, python-frontmatter, um motor de busca).

## Resultado da Decisão
**Opção escolhida:** A, porque mantém a instalação por cópia de uma pasta e deixa as skills independentes.

**Regras (verificáveis):**
- `skills/second-brain/SKILL.md` contém os fluxos (guardar, consultar, manter) e as regras do agente. Detalhe vai para `skills/second-brain/references/`.
- `skills/second-brain/scripts/brain.py` é um arquivo único que importa só a biblioteca padrão e roda em Python 3.9.
- Nenhum código de `skills/second-brain/` importa de `skills/sdd-management/` nem de `tools/`, e vice-versa. Um parser mínimo de YAML/frontmatter próprio fica no `brain.py`.
- O `brain.py` só executa processos externos declarados em `processors` na configuração compartilhada (ADR-0009). Nunca faz chamada de rede.
- **Só cria e acrescenta:** o `brain.py` nunca apaga arquivo do vault e nunca reescreve texto fora das regiões geradas, que ficam delimitadas por `<!-- brain:begin <nome> -->` e `<!-- brain:end <nome> -->`. A única exceção é tirar um item processado da inbox (SPEC-0021): texto vai para `raw/processed/` e arquivo vai para a pasta `files` (`ingest --move`). Nada é apagado.
- Toda escrita do `brain.py` no vault acrescenta uma linha ao `log.md`.
- Nenhum caminho absoluto de usuário (`/Users/<nome>`, `C:\Users\<nome>`, `/home/<nome>`) em arquivos de `skills/second-brain/` fora dos testes.
- **Versão:** o `brain.py` tem `BRAIN_VERSION` (AAAA.MM.N). Toda mudança de comportamento atualiza a versão e o `skills/second-brain/CHANGELOG.md` no mesmo PR, com a mesma regra do ADR-0005.
- Testes seguem o ADR-0002: `unittest`, unitários importando `brain` e integração pela CLI em diretórios temporários, com `HOME` e `BRAIN_CONFIG_HOME` isolados.

### Consequências
- **Boa**, porque a skill é copiada com uma pasta e roda em qualquer máquina, e o vault fica protegido por regras testadas.
- **Ruim**, porque o parser de YAML e os checadores de arquitetura ficam duplicados em relação à `sdd-management`, e a busca é feita sem um motor de busca pronto.

### Confirmação (G3)
`skills/second-brain/tests/test_architecture.py`, criado pela SPEC-0017: imports só da biblioteca padrão, arquivo único, nenhum import entre skills, processos externos só pela função que executa processadores, nenhum caminho pessoal em `skills/second-brain/`. Roda na CI junto com a suíte.

## Prós e Contras das Opções
| Critério (peso) | A — script próprio stdlib | B — biblioteca compartilhada | C — pacote com dependências |
|---|---|---|---|
| Instalação por cópia de uma pasta (3) | sim | não (exige as duas skills) | não (pip) |
| Independência entre as skills (3) | sim | não | sim |
| Menos código duplicado (1) | não | sim | sim |

## Mais Informações
ADR-0001 (fronteiras da `sdd-management`), ADR-0002 (testes), ADR-0003 (Ruff), ADR-0005 (fluxo de mudança e versão). Fontes: não verificado — decisão sobre a estrutura do próprio código, sem ferramenta externa nem versão a conferir.
