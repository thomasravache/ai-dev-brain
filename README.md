# ai-dev-brain

Skills e materiais de apoio para desenvolvimento com agentes de IA (Claude Code, Gemini CLI, Antigravity e outros que leem `SKILL.md`).

## Skills

| Skill | O que faz |
|---|---|
| [`sdd-management`](skills/sdd-management/SKILL.md) | Spec-Driven Development de ponta a ponta: specs com dependências, aprovação humana antes do código, execução multiagente em ondas, TDD verificado no git, gates de qualidade até o deploy, pilares de entrega e relatório de entrega. Agnóstica de tecnologia e de ferramenta. |
| [`second-brain`](skills/second-brain/SKILL.md) | Segundo cérebro num vault do Obsidian mantido com uma LLM: onboarding de vault novo ou existente, configuração em duas camadas (por máquina e no vault) para usar em várias máquinas e no celular, contextos com MOC e `doctor`. Agnóstica de provedor (Google Drive, OneDrive, iCloud ou pasta local). |

## Instalação

Copie a pasta da skill para o diretório de skills da sua ferramenta, por exemplo:

```bash
cp -R skills/sdd-management ~/.claude/skills/
cp -R skills/second-brain ~/.claude/skills/
```

A ferramenta da `sdd-management` (`scripts/spec_graph.py`) só precisa de Python 3.9+ e git; a da `second-brain` (`scripts/brain.py`), só de Python 3.9+. O CHANGELOG da `second-brain` fica em [`skills/second-brain/CHANGELOG.md`](skills/second-brain/CHANGELOG.md).

Num repositório compartilhado com um time que não usa SDD, ative o **modo privado** (`spec_graph.py private init`): specs e registros ficam numa pasta fora do repositório, e o time só vê código, commits e PRs normais. Detalhes em [`references/private-mode.md`](skills/sdd-management/references/private-mode.md).

Cada projeto ganha dois **documentos vivos** escritos para pessoas — o guia de jornadas e o mapa do sistema (`living_docs` no `sdd-config.yml`, criados com `spec_graph.py living-docs --init` e checados pelo `validate`).

## Novidades e CHANGELOG

O CHANGELOG da skill fica em [`skills/sdd-management/CHANGELOG.md`](skills/sdd-management/CHANGELOG.md), dentro da pasta que se copia para as ferramentas, com uma seção por versão (`SDD_TOOL_VERSION`). Depois de atualizar a skill, rode `spec_graph.py whats-new` no projeto: mostra as novidades desde a versão do projeto, as chaves novas do `sdd-config` e os comandos para se atualizar (`whats-new --ack` registra a versão revisada em projetos sem `tools/sdd`). O `status` avisa quando há novidade.

## Testes

```bash
python3 -m unittest discover -s skills/sdd-management/tests   # suíte completa, inclui os testes de arquitetura
python3 -m unittest discover -s skills/second-brain/tests     # suíte da second-brain, inclui os testes de arquitetura
uvx ruff check                                                 # lint (Ruff 0.17, configurado em ruff.toml)
```

A CI (`.github/workflows/ci.yml`) roda tudo isso em todo PR, em Python 3.9 e 3.15.
