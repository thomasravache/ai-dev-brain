---
id: SPEC-0060
title: "Servidor MCP: tools sdd de leitura do processo"
tier: full
type: feature
user_facing: false
status: approved
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
- N/A — instalação é a jornada do SPEC-0053:E2E-01; protocolo provado com processo real nos IT; conexão conferida no G4 (`/mcp` lista as `sdd_*`).

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

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — c5417ad (árvore suja) | 2026-11-13 |
| G1 Red | PENDING | | |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
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
- [ ] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [ ] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0060`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
