---
id: ADR-0016
title: O repositório é o plugin fermion
status: proposed
origin: decision
date: 2026-11-12
pillars: []
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: tests/plugin/test_plugin.py (SPEC-0053:UT-01, UT-02, UT-05, IT-01)
---

# ADR-0016 — O repositório é o plugin fermion

<!-- Formato MADR (Markdown Architectural Decision Records). status: proposed | accepted | rejected | deprecated | superseded — vira accepted quando a spec que o introduz é aprovada (H1); superseded exige superseded_by. origin: decision (recomendada: compare 2–3 opções e cite fontes com data, ou declare "não verificado") | user (escolhida pelo usuário: respeite, sem reabrir a discussão, e registre riscos e custo) | as-is (documenta um padrão que já existe no projeto). enforced_by: tests/plugin/test_plugin.py (SPEC-0053:UT-01, UT-02, UT-05, IT-01) teste de arquitetura que garante a decisão (G3), ou "N/A — motivo". -->

## Contexto e Problema
As três skills vivem em `skills/<nome>/` e são instaladas por cópia. Queremos distribuí-las como um plugin do Claude Code (SPEC-0031) sem duplicar arquivos nem criar passo de build. Onde fica o plugin e como ele alcança as skills?

## Direcionadores da Decisão
- A pasta de cada skill continua sendo a fonte da verdade e instalável por cópia (ADR-0001).
- O Claude Code rejeita caminho de componente fora da raiz do plugin e copia a raiz para um cache na instalação a partir do GitHub.
- Nenhum passo de release ou build novo.

## Opções Consideradas
- A: o repositório inteiro é o plugin (`.claude-plugin/` na raiz, `"source": "./"`, scan padrão de `skills/`).
- B: plugin em `plugins/fermion/` com link simbólico ou caminho para `../../skills`.
- C: cópia das skills para dentro do plugin gerada na release.

## Resultado da Decisão
**Opção escolhida:** A, porque é a única que traz as skills sem duplicar e sem build, dentro das regras documentadas do Claude Code.

### Consequências
- **Boa**, porque instalar e atualizar o conjunto vira um comando, e o plugin não tem cópia que possa divergir das skills.
- **Ruim**, porque o repositório inteiro (incluindo `docs/` e `tools/`) vai para o cache do plugin, e toda skill precisa ser autocontida: nada de referência a arquivo fora da própria pasta.

### Confirmação (G3)
`tests/plugin/test_plugin.py`: manifestos com `source: "./"` e nomes coerentes, scan das três skills, autocontenção de cada skill e as CLIs rodando a partir de uma cópia do repositório (SPEC-0053). `claude plugin validate .` no G4.

## Prós e Contras das Opções
| Critério (peso) | A | B | C |
|---|---|---|---|
| Sem duplicação (3) | sim | sim | não |
| Dentro das regras do Claude Code (3) | sim | não (caminho fora da raiz) | sim |
| Sem build/release (2) | sim | sim | não |
| Cache enxuto (1) | não | sim | sim |

## Mais Informações
- code.claude.com/docs/en/plugins/manifest-reference, marketplace-reference, loading e cli-reference — `source` relativo começa com `./`; caminhos de componente fora da raiz são rejeitados; plugin de marketplace Git é copiado para `cache/<marketplace>/<plugin>/<versão>/`; `claude plugin validate` — lidos em 2026-11-12.
- SPEC-0031, SPEC-0053.
