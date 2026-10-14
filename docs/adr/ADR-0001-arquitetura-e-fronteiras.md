---
id: ADR-0001
title: Arquitetura e fronteiras
status: proposed
origin: decision
date: 2026-10-14
pillars: [arquitetura]
baseline: arquitetura@2026.09
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0001
---

# ADR-0001 — Arquitetura e fronteiras

## Contexto e Problema
Sem fronteiras explícitas e verificadas, módulos se acoplam aos poucos e cada mudança passa a exigir mexer em tudo. O `ai-dev-brain` distribui skills para agentes de IA. A skill `sdd-management` tem quatro partes com papéis diferentes: as instruções que o agente lê, as referências carregadas sob demanda, os arquivos instalados nos projetos e a ferramenta determinística. A ferramenta é copiada para cada projeto (`tools/sdd/spec_graph.py`) e roda na CI de terceiros, sem instalar nada.

## Direcionadores da Decisão
- A ferramenta precisa rodar em qualquer máquina e CI com só Python 3.9+ e git, sem `pip install`.
- `vendor` copia um único arquivo para o projeto; mais de um arquivo quebra essa cópia.
- O `SKILL.md` entra inteiro no contexto do agente a cada uso; detalhe demais ali custa tokens em toda sessão.

## Opções Consideradas
- **A — Script único, só biblioteca padrão** (como está hoje).
- **B — Pacote Python com dependências** (ex.: PyYAML, click), instalado via pip.

## Resultado da Decisão
**Opção escolhida:** A, porque é a única que mantém a cópia de um arquivo e a CI de terceiros sem instalação.

**Regras (verificáveis):**
- `skills/<skill>/SKILL.md` contém o fluxo e os mandatos; detalhe vai para `references/` e é citado pelo caminho.
- `assets/` contém só arquivos que `vendor` instala nos projetos (CI, hooks, templates de PR, bloco de agentes, CHANGELOG).
- `scripts/spec_graph.py` é um arquivo único que importa apenas a biblioteca padrão do Python.
- `scripts/spec_graph.py` roda em Python 3.9 (versão mínima; README e SKILL.md declaram 3.9+).
- Nenhum código de `skills/` importa de `tools/sdd/` (a cópia é saída do `vendor`, não fonte).
- **A skill é agnóstica de stack e de plataforma.** O `spec_graph.py` só executa `git` e os comandos que o projeto declara no `sdd-config.yml`; nunca chama diretamente a CLI de uma plataforma (`gh`, `glab`, `az`…) nem de uma stack (`dotnet`, `npm`, `pytest`…). O que é específico de uma plataforma entra só como opção escolhida pelo usuário, com um valor por provedor (`--ci github|gitlab|generic`, `references/trackers/<provider>.md`), sempre com uma saída genérica.
- As escolhas de ferramenta **deste repositório** (Python, `unittest`, Ruff, GitHub — ADR-0002, ADR-0003, ADR-0005) valem só para o código do `ai-dev-brain` e nunca viram padrão imposto pela skill aos projetos.
- Mudar uma fronteira exige um ADR novo (que substitui este).

### Consequências
- **Boa**, porque a ferramenta continua portátil: copiar um arquivo basta para qualquer projeto e CI.
- **Ruim**, porque o script cresce num arquivo só (~3.300 linhas) e um parser YAML próprio substitui o PyYAML.

### Confirmação (G3)
Teste de arquitetura em `skills/sdd-management/tests/test_architecture.py` (imports só da biblioteca padrão, arquivo único, sem import de `tools/sdd`, processos externos só `git` ou comando lido do sdd-config) e a suíte rodando em Python 3.9 na CI — criados pela SPEC-0001.

## Prós e Contras das Opções
| Critério (peso) | A — script único stdlib | B — pacote com dependências |
|---|---|---|
| Portabilidade sem instalação (3) | sim | não |
| Cópia por `vendor` (3) | um arquivo | exige instalar o pacote |
| Ergonomia de código (1) | arquivo grande, YAML próprio | módulos e bibliotecas prontas |

## Mais Informações
Referências neutras: C4 model (diagramas de contexto e contêiner). Fontes: não verificado — decisão sobre a estrutura do próprio código, sem ferramenta externa nem versão a conferir.
