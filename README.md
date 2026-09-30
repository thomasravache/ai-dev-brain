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

A ferramenta da skill (`scripts/spec_graph.py`) só precisa de Python 3.8+ e git.

## Testes

```bash
cd skills/sdd-management && python3 -m unittest discover -s tests
```
