# ai-dev-brain

Skills e materiais de apoio para desenvolvimento com agentes de IA (Claude Code, Gemini CLI, Antigravity e outros que leem `SKILL.md`).

## Skills

| Skill | O que faz |
|---|---|
| [`sdd-management`](skills/sdd-management/SKILL.md) | Spec-Driven Development de ponta a ponta: specs com dependências, aprovação humana antes do código, execução multiagente em ondas, TDD verificado no git, gates de qualidade até o deploy, pilares de entrega e relatório de entrega. Agnóstica de tecnologia e de ferramenta. |

## Instalação

Copie a pasta da skill para o diretório de skills da sua ferramenta, por exemplo:

```bash
cp -R skills/sdd-management ~/.claude/skills/
```

A ferramenta da skill (`scripts/spec_graph.py`) só precisa de Python 3.9+ e git.

Num repositório compartilhado com um time que não usa SDD, ative o **modo privado** (`spec_graph.py private init`): specs e registros ficam numa pasta fora do repositório, e o time só vê código, commits e PRs normais. Detalhes em [`references/private-mode.md`](skills/sdd-management/references/private-mode.md).

Cada projeto ganha dois **documentos vivos** escritos para pessoas — o guia de jornadas e o mapa do sistema (`living_docs` no `sdd-config.yml`, criados com `spec_graph.py living-docs --init` e checados pelo `validate`).

## Testes

```bash
python3 -m unittest discover -s skills/sdd-management/tests   # suíte completa, inclui os testes de arquitetura
uvx ruff check                                                 # lint (Ruff 0.17, configurado em ruff.toml)
```

A CI (`.github/workflows/ci.yml`) roda os dois em todo PR, em Python 3.9 e 3.15.
