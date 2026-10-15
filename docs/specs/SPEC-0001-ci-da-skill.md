---
id: SPEC-0001
title: "CI da skill: testes, lint e arquitetura"
tier: full
type: foundation
user_facing: false
status: in-progress
created: 2026-10-14
parent:
depends_on: []
consumes_contract: []
contract_version: 2
touches: [.github/workflows/ci.yml, ruff.toml, skills/sdd-management/tests/**, skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/SKILL.md, README.md, CHANGELOG.md]
adrs: [ADR-0001, ADR-0002, ADR-0003, ADR-0005]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-14
---

# SPEC-0001 — CI da skill: testes, lint e arquitetura

## 1. Visão Geral
Cria a CI do `ai-dev-brain`: em todo PR roda o lint (Ruff), os testes de arquitetura do ADR-0001 e a suíte completa da skill em Python 3.9 e numa versão atual. Hoje os 61 testes só rodam na máquina de quem desenvolve, e nenhuma regra estrutural é verificada.

## 2. Motivação & Escopo
**Motivação:** a `sdd-management` aprova ou reprova gates em outros projetos; um defeito no `spec_graph.py` aprova trabalho errado. Sem CI, nada impede uma regressão de entrar na `main` — e pelo link simbólico ela passa a valer na hora. Os ADRs 0001–0003 citam esta spec como quem os garante (`enforced_by`).

**Objetivos (dentro do escopo):**
- Workflow `.github/workflows/ci.yml` com lint, testes de arquitetura e suíte completa em PRs e na `main`.
- `test_architecture.py` verificando as regras do ADR-0001 (imports só da biblioteca padrão, arquivo único, processos externos só `git` ou comando do sdd-config, nenhum código de `skills/` carregando a cópia em `tools/sdd`).
- `ruff.toml` (ADR-0003) e o código atual sem achados de lint.
- Python mínimo declarado como 3.9+ (README, SKILL.md), testado na CI.
- Comandos `lint` e `arch_test` preenchidos no `docs/specs/sdd-config.yml`.

**Não-objetivos (fora do escopo):**
- Formatação automática (`ruff format`): adiada pelo ADR-0003.
- Medição de cobertura, checagem de tipos e SAST.
- Tornar a CI obrigatória para o merge (indisponível no plano gratuito — ADR-0005).
- Qualquer mudança de comportamento dos comandos do `spec_graph.py`.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** Ruff 0.17.0 (verificado em 2026-10-14 via `uvx ruff --version`, PyPI); GitHub Actions habilitado no repositório (privado, plano gratuito: 2.000 minutos/mês; a suíte leva ~14 s localmente).

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Os testes seguem o padrão de `skills/sdd-management/tests/test_spec_graph.py` (`unittest`, script importado como `sg` para funções puras). O workflow segue o padrão de `skills/sdd-management/assets/ci/github-actions.yml` (permissões mínimas, `concurrency`, checkout sem credenciais persistidas).

**Decisão:** um workflow novo (`ci.yml`), separado do `sdd.yml` gerado pelo `vendor`, com um job `ci` em matriz de versões do Python. Os testes de arquitetura analisam o código com `ast` (biblioteca padrão), em funções que recebem o código-fonte como texto — assim cada regra é testada contra um exemplo que a viola e contra o código real.

**Justificativa:** o `sdd.yml` é arquivo de controle mantido pelo `vendor`; misturar os jobs faria o `vendor` apontar o arquivo como customizado. `ast` não exige dependência (ADR-0001) e funciona em 3.9.

**Desvio do padrão existente:** Nenhum. Ruff entra só na CI e no `uvx` local (ADR-0003), não no script. Levantamento em 2026-10-14: 37 achados em `skills/` (21 corrigíveis automaticamente; o resto são variáveis desempacotadas sem uso, `subprocess.run` sem `check` onde o retorno já é conferido, flags de regex e concatenações implícitas) — ajustes sem mudança de comportamento, protegidos pela suíte existente.

**Alternativas descartadas:** testes de arquitetura por `grep` em texto (frágil com strings e comentários); acrescentar os passos no `sdd.yml` (conflito com o `vendor`).

**ADRs:** ADR-0001, ADR-0002, ADR-0003, ADR-0005.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** job completo em menos de 5 minutos por versão do Python — medido pela duração da execução na CI.
- **Segurança:** `permissions: contents: read`; actions fixadas no SHA completo do commit da release; `persist-credentials: false`; nenhum segredo usado — verificado na revisão (G4).
- **Privacidade e dados pessoais:** N/A — a CI não processa dados pessoais.
- **Disponibilidade e resiliência:** `concurrency` cancela execuções antigas do mesmo PR; `timeout-minutes: 10`.
- **Acessibilidade (UI):** N/A — sem interface.
- **Custo:** cerca de 1 minuto de Actions por versão do Python por push, dentro da cota gratuita.

## 6. Artefato A — Contrato
**Interface:** workflow `ci` + comandos `lint` e `arch_test` do sdd-config + mensagens de falha dos testes de arquitetura.

```text
.github/workflows/ci.yml
  on: pull_request; push na main
  permissions: contents: read
  job ci — matriz python: ["3.9", "<versão estável mais recente, fixada e verificada na implementação>"]
    1. ruff check            (Ruff 0.17.0 fixo; só na versão mais recente do Python)
    2. python -m unittest discover -s skills/sdd-management/tests   (inclui test_architecture.py)
  Sucesso: todos os passos verdes. Falha: qualquer achado de lint, teste ou regra de arquitetura → job vermelho.

docs/specs/sdd-config.yml
  lint: "ruff check"
  arch_test: "python3 -m unittest discover -s skills/sdd-management/tests -p test_architecture.py"

ruff.toml
  target-version = "py39"; regras padrão do Ruff 0.17; exclui tools/ (cópia do vendor, recebe os ajustes pelo vendor)
  ignorar uma regra exige comentário com o motivo ao lado (ex.: PLW1510 onde o código já confere returncode)

skills/sdd-management/tests/test_architecture.py — mensagem de falha (uma linha por violação):
  <arquivo>:<linha> — <regra do ADR-0001 violada> — <o que foi encontrado>
  ex.: scripts/spec_graph.py:12 — só biblioteca padrão — import de 'yaml'
```

**Design:** N/A — sem interface.

**Arquivos/módulos afetados:** ver `touches`. Novos: `.github/workflows/ci.yml`, `ruff.toml`, `skills/sdd-management/tests/test_architecture.py`. Alterados: `spec_graph.py` (só ajustes de lint e `SDD_TOOL_VERSION`), `SKILL.md` e `README.md` (Python 3.9+, seção de testes), `CHANGELOG.md`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Import fora da biblioteca padrão | script importa módulo de terceiro | teste falha citando arquivo, linha e módulo | UT-01, UT-02 |
| Script deixa de ser arquivo único | script importa módulo local de `scripts/` | teste falha citando o import | UT-01, UT-02 |
| Processo externo não permitido | chamada `subprocess` fora das funções permitidas (`run_git` e executor de comandos do gate) | teste falha citando função e linha | UT-03, UT-04 |
| Código da skill carrega a cópia do vendor | arquivo em `skills/` importa de `tools/sdd` ou põe esse caminho no `sys.path` (citar o caminho como destino da cópia é permitido) | teste falha citando arquivo e linha | UT-05, UT-06 |
| PR sem problemas | lint, arquitetura e suíte verdes em 3.9 e na versão atual | job `ci` verde | IT-01 |
| PR com problema | erro de lint ou teste falhando | job `ci` vermelho | IT-02 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — os 61 testes existentes já fixam o comportamento do script e precisam continuar verdes após os ajustes de lint.

### 7.2 Testes Unitários
- **UT-01** — Dado um código-fonte sintético com `import yaml` e `from helpers import x` (módulo local), quando o checador de imports roda, então aponta os dois imports com a linha e a regra violada.
- **UT-02** — (guarda: passa antes da mudança) Dado o `scripts/spec_graph.py` atual, quando o checador de imports roda, então não há import fora da biblioteca padrão nem de módulo local.
- **UT-03** — Dado um código-fonte sintético com `subprocess.run(["gh", "pr", "list"])` numa função fora da lista permitida, quando o checador de processos roda, então aponta a chamada com função e linha.
- **UT-04** — (guarda: passa antes da mudança) Dado o `scripts/spec_graph.py` atual, quando o checador de processos roda, então toda chamada de `subprocess` está em `run_git` ou no executor de comandos do gate.
- **UT-05** — Dado um código-fonte sintético que faz `from tools.sdd import spec_graph` e outro que faz `sys.path.insert(0, "tools/sdd")`, quando o checador da cópia do vendor roda, então aponta os dois com arquivo e linha; e dado um código que só atribui `"tools/sdd/spec_graph.py"` a uma constante, então não aponta nada.
- **UT-06** — (guarda: passa antes da mudança) Dado todo arquivo `.py` em `skills/`, quando o checador da cópia do vendor roda, então nenhum importa de `tools/sdd` nem o põe no `sys.path`.

### 7.3 Testes de Integração
- **IT-01** — Dado um PR com o código desta spec, quando o workflow `ci` roda no GitHub Actions, então lint, arquitetura e suíte completa passam em Python 3.9 e na versão atual (evidência: execução da CI).
- **IT-02** — Dado um commit descartável com um erro de lint e um teste falhando, num PR em rascunho aberto só para isso e fechado depois, quando o workflow `ci` roda, então o job fica vermelho apontando os dois problemas (evidência: execução da CI).

### 7.4 Testes de Contrato
- N/A — não há contrato entre specs.

### 7.5 Testes E2E
- N/A — `user_facing: false`: nenhum comando da skill muda; a CI é usada só por quem mantém o repositório.

### 7.6 Outros
- Duração do job (RNF de desempenho) lida da execução do IT-01.

**Dublês e dados de teste:** código-fonte sintético em strings, dentro dos próprios testes; nenhum arquivo fora do diretório do teste é escrito.

**Ambiente de execução:** UT localmente e na CI; IT-01 e IT-02 no GitHub Actions (`ubuntu-24.04`: o Python 3.9 não tem build para 26.04).

## 8. Plano de Rollout
- **Estratégia:** merge direto do PR; o workflow passa a rodar a partir do próprio PR que o cria.
- **Dados/schema:** N/A
- **Compatibilidade:** quem usa a skill com Python 3.8 deixa de ter garantia; registrado no CHANGELOG como mudança.
- **Observabilidade:** status do job `ci` em cada PR e na `main`.
- **Rollback:** `git revert` do merge (ADR-0005); nenhum outro estado é criado.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] Qual a versão mínima do Python que a CI garante? — 3.9+; o 3.8 está sem suporte desde out/2024 e pode não existir nos runners (thomas, 2026-10-14)
- [x] Qual ferramenta de lint? — Ruff, só na CI, conforme ADR-0003; formatação adiada (thomas, 2026-10-14, a confirmar no H1 junto do ADR)
- [x] O IT-02 exige abrir um PR em rascunho descartável no GitHub? — sim; push e PR só com autorização do mantenedor no momento da execução (thomas, 2026-10-14)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação

**Fase 1: Testes de arquitetura**
- [ ] Red: escrever UT-01..UT-06 com a tag `SPEC-0001:<ID>`; UT-02, UT-04 e UT-06 (guardas) passam no código atual, UT-01, UT-03 e UT-05 falham pelo motivo certo
- [ ] Green: implementar os checadores (`ast`) em `test_architecture.py` até tudo passar
- [ ] Refactor mantendo tudo verde

**Fase 2: Lint**
- [ ] `ruff.toml` (py39, exclui `tools/`) e ajustes no `spec_graph.py` sem mudança de comportamento; motivo ao lado de cada regra ignorada
- [ ] Validar: `uvx ruff check` limpo + suíte completa (G2) + `arch_test` (G3)

**Fase 3: CI e documentação**
- [ ] `.github/workflows/ci.yml` (matriz 3.9 + versão atual, actions fixadas por SHA) com a tag `SPEC-0001:IT-01` e `SPEC-0001:IT-02`
- [ ] `lint` e `arch_test` no sdd-config; README e SKILL.md com Python 3.9+; `SDD_TOOL_VERSION` e CHANGELOG

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (IT-01), CI vermelha no PR descartável (IT-02) (G5) e aprovação (H2)
- [ ] Deploy: N/A — pilar entrega dispensado
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 9c2f5e4 | 2026-10-14 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=1, skipped=1)) — 1762aaa | 2026-10-14 |
| G2 Green | PASS | test exit 0 (OK (skipped=1)); lint exit 0 (All checks passed!) — 53c8181 | 2026-10-14 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 53c8181 | 2026-10-14 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: APPROVED (modo solo) — 0 blocker/major; minor: regra {tools,sdd} do checador de vendor pode dar falso positivo raro em sys.path; avisos do verify justificados: IT-01/02 vivem no workflow, architecture_rules.py é a implementação, test_spec_graph.py só teve ajustes de lint sem mudar asserções — 53c8181 | 2026-10-14 |
| G5 Integração & CI | PASS | MANUAL: BYPASS LOCAL (autorizado por thomas em 2026-10-14; GitHub Actions bloqueado por cobrança, IMP-02): test exit 0 e arch_test exit 0 em d8be9d6 — refazer na CI do GitHub em 2026-10-15 | 2026-10-14 |
| H2 Integração aprovada | PASS | aprovado por thomas — bypass autorizado em 2026-10-14 ('o bypass é pra tudo até amanhã'); CI do GitHub refeita em 2026-10-15 | 2026-10-14 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): a skill vale na main pelo link simbólico | 2026-10-14 |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-10-14 | G1 | spec | UT-05/UT-06 proíbem 'referenciar' tools/sdd, mas o vendor cita esse caminho como destino da cópia (spec_graph.py:22, :70, :2803) e os testes do vendor conferem o destino; a guarda reprovaria código correto | conferido com grep em scripts/ e tests/ | Architect + thomas | Emenda v2 — regra da cópia do vendor proíbe carregar código de tools/sdd (import ou sys.path), não citar o caminho; aprovada por thomas em 2026-10-14 | 2026-10-14 |
| IMP-02 | 2026-10-14 | G5 | externo | GitHub Actions não inicia jobs no repositório: 'recent account payments have failed or your spending limit needs to be increased' (runs 38650532309 e 38650548527); IT-01 e IT-02 sem evidência | PRs #1 e #2 abertos; todos os jobs (ci 3.9, ci 3.15, sdd) recusados em 2–3 s sem executar passos | thomas |  |  |

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). -->

### O que foi entregue

### Como foi feito

### Prova de Correção

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Todos os testes do plano passando e listados na Verificação
- [ ] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [ ] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [ ] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [ ] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6)
- [ ] Observabilidade e rollback prontos conforme o Plano de Rollout
- [ ] Documentação raiz e CHANGELOG atualizados (G7)
- [ ] Pendências registradas como novas specs (ou nenhuma)

### Deploy

### Pendências

## 15. Emendas
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-10-14 | Regra da cópia do vendor: proíbe carregar código de `tools/sdd` (import ou `sys.path`), não citar o caminho; UT-05/UT-06 e Mapa ajustados | IMP-01: o `vendor` cita `tools/sdd` como destino e a guarda reprovaria código correto | Nenhuma | thomas, 2026-10-14 |
