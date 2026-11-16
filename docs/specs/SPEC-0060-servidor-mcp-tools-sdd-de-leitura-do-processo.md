---
id: SPEC-0060
title: "Servidor MCP: tools sdd de leitura do processo"
tier: full
type: feature
user_facing: false
status: implemented
created: 2026-11-13
parent: SPEC-0031
depends_on: [SPEC-0054, SPEC-0059]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [mcp/**, .claude-plugin/plugin.json]
adrs: [ADR-0017]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-13
---

# SPEC-0060 — Servidor MCP: tools sdd de leitura do processo

## 1. Visão Geral
O servidor MCP `fermion` ganha seis tools de leitura do processo SDD (`gluon-spec`): `sdd_status`, `sdd_validate`, `sdd_next`, `sdd_waves`, `sdd_report` e `sdd_whats_new`. Cada uma só chama `skills/gluon-spec/scripts/spec_graph.py` com `--root` igual à pasta do projeto aberto e devolve a saída dela. Nada que grave (gates, `set`, `new`, `vendor`, `index`) sai por MCP.

## 2. Motivação & Escopo
**Motivação:** última parte da frente 3 do épico SPEC-0031 (ganho marginal, por isso por último). Um cliente MCP sem shell (ou um agente que não carregou a skill) consulta onde a spec está e qual o próximo passo com uma chamada tipada. Os registros do SDD continuam só do Architect pela CLI (regra "single writer").

**Objetivos (dentro do escopo):**
- Seis tools `sdd_*` de leitura, com `inputSchema` fechado e `annotations.readOnlyHint: true`.
- A regra de arquitetura do servidor passa a aceitar também `spec_graph.py` (depois da SPEC-0059, que aceitou `brain.py`).
- Pasta do projeto: `CLAUDE_PROJECT_DIR` do ambiente do servidor (o Claude Code exporta para servidores stdio de plugin), senão o cwd do servidor; passada como `--root`.

**Não-objetivos (fora do escopo):**
- Comandos que gravam: `gate`, `set`, `new`, `new-adr`, `impede`, `resolve`, `index`, `vendor`, `upgrade --apply`, `migrate --apply`, `whats-new --ack`, `worktree --create`, `private`.
- `export` (JSON grande, para adaptadores de board, que rodam pela CLI), `verify`, `pr-check` e `sync` (dependem de git e de variáveis de CI).
- Escolher outro projeto por argumento da tool.

## 3. Dependências
- **Implementações necessárias:** SPEC-0054 (servidor, validação, `run_cli`, mapeamento de saída) e os comandos `status`, `validate`, `next`, `waves`, `report` e `whats-new` da `gluon-spec` (na `main`, `SDD_TOOL_VERSION` 2026.11.3), com a opção global `--root`.
- **Contratos consumidos:** N/A — saída de texto repassada sem interpretar.
- **Pré-requisitos externos:** code.claude.com/docs/en/plugins-reference, lida em 2026-11-13: servidores MCP stdio de plugin recebem `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA` e `CLAUDE_PROJECT_DIR` no ambiente.

## 4. Decisão Arquitetural
**Contexto:** brownfield. Referência: as tools `atlas_*` em `mcp/fermion_mcp.py` e as suítes de `mcp/tests/`.

**Decisão:** as tools `sdd_*` entram na mesma tabela `TOOLS` e no mesmo `command_args`, sempre com `spec_graph.py --root <projeto> <comando>`. A pasta do projeto vem do ambiente (`CLAUDE_PROJECT_DIR`) ou do cwd, nunca de argumento do agente. Saída de texto (a CLI não tem `--json` nesses comandos): `content` texto, sem `structuredContent`.

**Justificativa:** a CLI continua a fonte da verdade (ADR-0017); a pasta do projeto fora do alcance do agente evita que uma tool leia specs de outro repositório por engano.

**Desvio do padrão existente:** Nenhum. Acrescenta tools ao `tools/list` (Emenda v3 da SPEC-0054, a mesma da SPEC-0059: UT-01 confere por prefixo).

**Alternativas descartadas:** argumento `project_dir` na tool (o agente poderia apontar qualquer pasta da máquina); `--json` novo no `status` (muda a `gluon-spec` sem necessidade; o texto já é o que o agente lê hoje); incluir `export` (saída grande sem uso por agente).

**ADRs:** ADR-0017.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** um processo por chamada; medido no IT-01 (resposta em menos de 5 s num projeto de fixture).
- **Segurança:** só leitura; ids validados por padrão (o mesmo `\d{4,}` da `gluon-spec`) antes de abrir processo; sem shell; `--root` vem do ambiente.
- **Privacidade e dados pessoais:** N/A — specs do projeto aberto.
- **Disponibilidade e resiliência:** timeout de 120 s; erros viram `isError: true` sem derrubar o servidor.
- **Acessibilidade (UI):** N/A — sem interface.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** tools `sdd_*` do servidor MCP `fermion`

```text
projeto = env CLAUDE_PROJECT_DIR (se não vazio) senão os.getcwd() do servidor; toda linha de comando começa com spec_graph.py --root <projeto>
spec_id = string ^SPEC-[0-9]{4,}$        any_id = string ^(SPEC|ADR)-[0-9]{4,}$   (o status só aceita specs; o validate aceita os dois)
arrays com minItems/maxItems: o validador de argumentos do servidor (_check) passa a conferir os dois

tools/list → atlas_*, brain_* (SPEC-0059, se já integrada) e estas, com inputSchema object, additionalProperties: false, annotations {readOnlyHint: true}
  sdd_status       {ids: array de spec_id, 0..20 itens}   → status [ids...]
  sdd_validate     {ids: array de any_id, 0..20 itens}    → validate [ids...]
  sdd_next         {}                                → next
  sdd_waves        {}                                → waves
  sdd_report       {id: spec_id (obrigatório)}       → report <id>
  sdd_whats_new    {}                                → whats-new            (nunca --ack)

tools/call
  argumento fora do schema → -32602 sem abrir processo
  exit 0; e exit 1 em sdd_validate (há ERRO na validação) → isError: false, content texto = stdout (sem structuredContent)
  outro exit diferente de 0 → isError: true com o exit code e o stderr; timeout → "spec_graph.py não respondeu em 120 s"; CLI ausente → caminho procurado
```

**Design:** N/A — sem interface.

**Arquivos/módulos afetados:** ver `touches`. Alterar `mcp/fermion_mcp.py`, `mcp/tests/` (UT, IT, fixture de projeto SDD), `mcp/README.md` e `.claude-plugin/plugin.json` (versão).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Lista de tools | `tools/list` | as `sdd_*` do contrato com schema fechado e `readOnlyHint` | UT-01 |
| Argumento inválido | id fora do padrão, ADR no `sdd_status`, mais de 20 ids, `sdd_report` sem `id`, chave extra | -32602 sem abrir processo | UT-02 |
| Fronteira com as CLIs | código do servidor | processo só para `atlas.py`, `brain.py` e `spec_graph.py` das skills | UT-05 |
| Pasta do projeto | `CLAUDE_PROJECT_DIR` definido, vazio ou ausente | `--root` com o valor do ambiente, ou com o cwd do servidor | UT-03 |
| Mapeamento de saída | exit 0, 1 (validate), 2, timeout | resultado e `isError` do contrato | UT-04 |
| Mesmo resultado da CLI | servidor real num projeto de fixture | `sdd_status`, `sdd_validate` e `sdd_next` iguais ao stdout da CLI | IT-01 |
| Nada grava | servidor real chamando as seis tools | nenhum arquivo do projeto de fixture muda | IT-02 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — as tools existentes têm suíte própria e continuam passando.

### 7.2 Testes Unitários
- **UT-01** — Dado o servidor, quando recebe `tools/list` (era legada e moderna), então a lista contém as seis `sdd_*` do contrato, cada uma com `description`, `inputSchema` fechado (padrão de id, limites de itens) e `annotations.readOnlyHint: true`, e as tools das specs anteriores continuam iguais.
- **UT-02** — Dados `sdd_status` com `ids: ["SPEC-1"]`, com `ids: ["ADR-0001"]`, com 21 ids, `sdd_validate` com `ids: ["ADR-0001", "SPEC-12345"]` (válido: abre processo), `sdd_report` sem `id`, `sdd_report` com `id: "--ack"` e `sdd_next` com chave extra, quando chegam, então cada inválido recebe -32602 sem abrir processo, o válido chega ao executor, e o validador confere `minItems`/`maxItems` de qualquer array do schema.
- **UT-03** — Dado um executor falso, quando `sdd_status` é chamado com `CLAUDE_PROJECT_DIR=/p`, com `CLAUDE_PROJECT_DIR` vazio e sem a variável, então a linha de comando é `spec_graph.py --root /p status`, e nos outros dois casos `--root` é o cwd do servidor; nenhuma linha de comando de nenhuma `sdd_*` contém `--ack`, `--apply`, `--create` ou `--out`.
- **UT-04** — Dado um executor falso, quando a CLI sai com 0, com 1 no `sdd_validate`, com 1 no `sdd_status`, com 2, por timeout e com `FileNotFoundError`, então os resultados seguem o contrato (sem `structuredContent`; `isError` e textos de cada caso).
- **UT-05** — Dados o código de `mcp/fermion_mcp.py` e exemplos que violam as regras, quando as regras do ADR-0017 rodam, então acusam processo para um script que não seja `atlas.py`, `brain.py` ou `spec_graph.py` das skills; o código real não tem achado.

### 7.3 Testes de Integração
- **IT-01** — Dado um projeto de fixture criado pela própria CLI (`git init` e `new --tier lite --title "Fixture A"` e `new --tier lite --title "Fixture B"`), quando o servidor real é aberto por stdio com `CLAUDE_PROJECT_DIR` apontando para ele e recebe `sdd_status`, `sdd_validate` e `sdd_next`, então o texto de cada resultado é igual ao stdout de `spec_graph.py --root <projeto>` com o mesmo comando, e cada resposta chega em menos de 5 s.
- **IT-02** — Dado o mesmo projeto de fixture, quando as seis tools são chamadas pelo servidor real, então o conteúdo e a data de modificação de todos os arquivos do projeto são iguais antes e depois.

### 7.4 Testes de Contrato
- N/A — texto repassado sem interpretar; igualdade com a CLI provada no IT-01.

### 7.5 Testes E2E
- N/A — instalação é a jornada E2E da SPEC-0053; protocolo provado com processo real nos IT; conexão conferida no G4 (`/mcp` lista as `sdd_*`).

### 7.6 Outros
- Tempo de resposta no IT-01.

**Dublês e dados de teste:** executor substituível nos UT; projeto de fixture em pasta temporária criado pela CLI real.

**Ambiente de execução:** local e CI, sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto com `claude plugin update`.
- **Dados/schema:** N/A.
- **Compatibilidade:** `tools/list` só cresce.
- **Observabilidade:** stderr do servidor, como na SPEC-0054.
- **Rollback:** reverter o merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] De onde vem a pasta do projeto? — Do ambiente (`CLAUDE_PROJECT_DIR`) ou do cwd do servidor, nunca de argumento do agente (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-13: "pode seguir no piloto automático com o recomendado"; revisável no H1)
- [x] Entram comandos que gravam registros (por exemplo `gate --run`)? — Não: só o Architect grava, pela CLI (recomendação do arquiteto, aceita no piloto automático, thomas, 2026-11-13; revisável no H1)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Tools, schemas, pasta do projeto e saída**
- [x] Red: UT-01 a UT-04 em `mcp/tests/` com a tag `SPEC-0060:<ID>`, falhando pelo motivo certo
- [x] Green: as seis `sdd_*` em `TOOLS`, `command_args` (`--root` do ambiente) e `map_output`; `_check` confere `minItems`/`maxItems`

**Fase 2: Fronteira com as CLIs**
- [x] Red: UT-05 (processo só para `atlas.py`, `brain.py` e `spec_graph.py`)
- [x] Green: regra aceita as três CLIs; código real sem achado

**Fase 3: Servidor real num projeto de fixture**
- [x] Red: IT-01 e IT-02 (projeto criado pela CLI da `gluon-spec` em pasta temporária)
- [x] Green: resultados iguais aos da CLI; nenhum arquivo muda

**Fase final: Integração, entrega e documentação**
- [x] Validar: suíte completa + arquitetura (G2/G3); `mcp/README.md` e `version` do `plugin.json`
- [x] Review independente (G4), com as `sdd_*` listadas numa sessão real do Claude Code
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — c5417ad (árvore suja) | 2026-11-13 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=101)) — 5e2e7a4 | 2026-11-16 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — f264956 | 2026-11-16 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 760d20c | 2026-11-16 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer independente: APPROVED (sem blocker/major; 17 de 18 mutações pegas; 2 minors e 3 nits como pendências). Verificação manual em 2026-11-16 com Claude Code 2.1.322 e --plugin-dir: servidor plugin:fermion:fermion connected com 19 tools, entre elas as seis sdd_*. — a866f2c | 2026-11-16 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — ab54ad2 | 2026-11-16 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-16 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-16 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 79651f6 | 2026-11-16 |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
- O servidor MCP `fermion` ganhou seis tools de leitura do processo SDD: `sdd_status`, `sdd_validate`, `sdd_next`, `sdd_waves`, `sdd_report` e `sdd_whats_new`. Cada uma chama `spec_graph.py --root <projeto>` com a pasta do projeto aberto (`CLAUDE_PROJECT_DIR` ou o cwd do servidor) e devolve o texto da CLI; nada que grave sai por MCP.
- O validador de argumentos passou a conferir `minItems`/`maxItems` de qualquer array.
- `mcp/README.md`; `version` do plugin 2026.11.9.

### Como foi feito
- Mesmo padrão das `atlas_*` e `brain_*` (tabela `TOOLS`, `run_cli`, argv em lista, ADR-0017); `project_dir()` lido a cada chamada; `Server._call` escolhe CLI, rótulo e timeout por família, com as mensagens anteriores iguais.
- Testes em 5e2e7a4; implementação em f264956.
- **Revisão G4:** APPROVED na rodada 1; 17 de 18 mutações pegas pela suíte. Verificação manual: numa sessão real do Claude Code 2.1.322 o servidor conecta com 19 tools, entre elas as seis `sdd_*`.

### Prova de Correção
N/A — feature.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | `tools/list` com as seis `sdd_*`, schemas fechados (padrão de id, 0..20 itens) e `readOnlyHint`; tools anteriores iguais | PASS | `test_sdd_server.py::SddToolsListTest` — CI do PR #34 (run 43898353874, Python 3.9 e 3.15) e suíte local no G5 |
| UT-02 | Id fora do padrão, ADR no status, 21 ids, report sem id, `--ack`, chave extra → -32602 sem processo; `minItems`/`maxItems` em qualquer array | PASS | `test_sdd_server.py::SddInvalidArgumentsTest, ArrayLimitsTest` — CI do PR #34 (run 43898353874, Python 3.9 e 3.15) e suíte local no G5 |
| UT-03 | `--root` de `CLAUDE_PROJECT_DIR` ou do cwd (vazio/ausente), lido na chamada; nunca `--ack`/`--apply`/`--create`/`--out` | PASS | `test_sdd_server.py::SddProjectDirTest, SddCommandLineTest` — CI do PR #34 (run 43898353874, Python 3.9 e 3.15) e suíte local no G5 |
| UT-04 | Exit 0, 1 (normal só no validate), 2, timeout e CLI ausente; sem `structuredContent` | PASS | `test_sdd_server.py::SddOutputMappingTest` — CI do PR #34 (run 43898353874, Python 3.9 e 3.15) e suíte local no G5 |
| UT-05 | Processo só para `atlas.py`, `brain.py` e `spec_graph.py`; cada tool abre só a sua CLI | PASS | `test_architecture.py::SddBoundaryTest (também no `arch_test` do G3)` — CI do PR #34 (run 43898353874, Python 3.9 e 3.15) e suíte local no G5 |
| IT-01 | Servidor real: `sdd_status`, `sdd_validate` e `sdd_next` iguais à CLI, cada um em menos de 5 s | PASS | `test_sdd_server.py::SddSameResultAsCliTest` — CI do PR #34 (run 43898353874, Python 3.9 e 3.15) e suíte local no G5 |
| IT-02 | As seis tools pelo servidor real não mudam conteúdo nem mtime de nenhum arquivo do projeto (inclusive `.git`) nem do HOME | PASS | `test_sdd_server.py::SddNothingWritesTest` — CI do PR #34 (run 43898353874, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado — padrão das `atlas_*` (SPEC-0054, ADR-0017)
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — IT-01 abaixo de 5 s; timeout de 120 s (UT-04)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: distribuído pelo plugin; conferido numa sessão real no G4
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout — stderr do servidor; rollback = reverter o merge
- [x] Documentação raiz e CHANGELOG atualizados (G7) — `mcp/README.md`; sem CHANGELOG raiz
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: o projeto não declara `living_docs`
- [x] Pendências registradas como novas specs (ou nenhuma) — nenhuma spec nova; minors e nits abaixo

### Deploy
N/A — plugin `fermion` 2026.11.9, PR #34.

### Pendências
- Minors da revisão, sem spec: o texto "CLI do atlas/do segundo cérebro não encontrada" não tem assert do texto completo (lacuna anterior à spec); em modo privado da `gluon-spec`, o `git status` do `status` pode atualizar o `.git/index` do `spec_root` (não é arquivo do projeto nem gravação da CLI).
- Nits: `--root` em dois argumentos (o valor vem do ambiente, não do cliente); espaçamento em `mcp/tests/helpers.py`; caso explícito de id com dígito unicode.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0060`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
