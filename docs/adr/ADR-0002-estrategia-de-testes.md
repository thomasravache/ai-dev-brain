---
id: ADR-0002
title: Estratégia de testes
status: proposed
origin: decision
date: 2026-10-14
pillars: [testes]
baseline: testes@2026.09
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0001
---

# ADR-0002 — Estratégia de testes

## Contexto e Problema
Sem uma estratégia explícita, a suíte cresce desequilibrada e regressões chegam a quem usa a skill. Aqui, quem usa a skill depende do `spec_graph.py` para aprovar ou reprovar gates, então um defeito nele aprova trabalho errado em outros projetos. Hoje há 61 testes em `skills/sdd-management/tests/test_spec_graph.py`, com `unittest` e repositórios git temporários, que só rodam na máquina de quem desenvolve.

## Direcionadores da Decisão
- Mesma restrição do ADR-0001: nada de dependência instalada para rodar os testes.
- O que importa é o comportamento da CLI sobre um repositório git real (commits, branches, merges).

## Opções Consideradas
- **A — `unittest` da biblioteca padrão + git real em diretório temporário** (como está hoje).
- **B — `pytest`** com fixtures.

## Resultado da Decisão
**Opção escolhida:** A, porque já cobre a ferramenta, roda sem instalar nada e mantém o padrão dos 61 testes existentes.

**Regras (verificáveis):**
- Todo comando novo ou alterado do `spec_graph.py` tem teste que o executa pela CLI num repositório git temporário (`Project` em `test_spec_graph.py` é a referência).
- A suíte completa roda na CI em todo PR.
- Testes nunca leem nem escrevem fora do diretório temporário: `HOME` e configurações do usuário são isolados quando o comando os usa.
- Teste instável é defeito: vai para quarentena por no máximo 7 dias com spec aberta para corrigir; nunca retry-até-passar.
- Cobertura das linhas alteradas: não medida por enquanto (sem ferramenta na biblioteca padrão); o revisor (G4) confere que cada regra nova tem teste.

**Ferramenta por nível:**
| Nível | Ferramenta / abordagem | Por quê | Onde roda |
|---|---|---|---|
| Unitário | `unittest`, chamando funções de `spec_graph` importado | regras puras (globs, YAML, parsing) sem processo | local + CI |
| Integração | `unittest` + `subprocess` da CLI + `git` real num `tempfile.mkdtemp()` | a ferramenta é a CLI sobre um repositório real | local + CI |
| Contrato | N/A — não há contrato entre serviços; o formato das specs é coberto pelos testes de `validate` e `upgrade` | — | — |
| E2E | N/A — a skill não tem interface própria; a jornada do usuário é a CLI, coberta pelos testes de integração (fluxo `new` → `gate` → `pr-check`) | — | — |
| Carga | N/A — sem meta de desempenho nos RNFs | — | — |
| Acessibilidade | N/A — sem interface | — | — |

### Consequências
- **Boa**, porque os testes exercitam o mesmo caminho que os usuários: CLI sobre git real.
- **Ruim**, porque testes de integração com git são lentos (~14 s hoje) e não há medição de cobertura.

### Confirmação (G3)
Comando `test` do sdd-config (`python3 -m unittest discover -s skills/sdd-management/tests`), executado pelo `gate --run` e pela CI criada na SPEC-0001.

## Prós e Contras das Opções
| Critério (peso) | A — unittest | B — pytest |
|---|---|---|
| Sem instalação (3) | sim | não |
| Continuidade com a suíte atual (2) | total | migração |
| Ergonomia (1) | média | alta |

## Mais Informações
Referências neutras: Pirâmide de testes; `references/testing.md` da skill. Fontes: não verificado — `unittest` faz parte da biblioteca padrão do Python, sem versão separada a conferir.
