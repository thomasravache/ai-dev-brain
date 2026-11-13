---
id: SPEC-0054
title: Servidor MCP local do plugin com as tools atlas
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-12
parent: SPEC-0031
depends_on: [SPEC-0053, SPEC-0055]
consumes_contract: []
contract_version: 2
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [mcp/**, .claude-plugin/plugin.json, .github/workflows/ci.yml]
adrs: [ADR-0017]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-12
---

# SPEC-0054 — Servidor MCP local do plugin com as tools atlas

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
O plugin `fermion` ganha um servidor MCP local (`mcp/fermion_mcp.py`, stdio, só biblioteca padrão) com cinco tools de leitura do atlas da organização: `atlas_config`, `atlas_doctor`, `atlas_context`, `atlas_lint` e `atlas_curate_list`. Cada tool só chama a CLI da `boson-atlas` (antes `org-atlas`) e devolve o mesmo resultado dela. Qualquer agente com MCP passa a consultar o atlas sem shell e com entradas tipadas.

## 2. Motivação & Escopo
**Motivação:** hoje um agente só usa o atlas montando a linha de comando da CLI. Tools tipadas funcionam em qualquer cliente MCP (inclusive sem shell) e deixam a política fora do alcance do agente: o servidor só expõe leitura, e confirmar convenção continua sendo de pessoas (ADR-0012).

**Objetivos (dentro do escopo):**
- `mcp/fermion_mcp.py`: JSON-RPC 2.0 sobre stdio, das duas eras do protocolo (legada com `initialize`, versão `2025-11-25`; moderna sem handshake, versão `2026-07-28`, com `server/discover` e versão em `_meta`), com `tools/list` e `tools/call`.
- As cinco tools sobre `skills/boson-atlas/scripts/atlas.py`, declaradas no `plugin.json` (`mcpServers.fermion`, com `${CLAUDE_PLUGIN_ROOT}`).
- Testes de arquitetura do ADR-0017 e guia `mcp/README.md`.

**Não-objetivos (fora do escopo):**
- Tools que gravam: `scan`, `build`, `init`, `vendor`; e `curate confirm`/`curate reject`, que são só de pessoas (ADR-0012).
- Tools `brain_*` e `sdd_*` (filhas seguintes), resources, prompts, transporte HTTP e MCP remoto.

## 3. Dependências
- **Implementações necessárias:** SPEC-0053 — o `plugin.json` onde o servidor é declarado; SPEC-0038, SPEC-0039, SPEC-0037 e SPEC-0032 (via SPEC-0029) — os comandos `context`, `lint`, `curate list`, `config` e `doctor` com `--json`.
- **Contratos consumidos:** N/A — o servidor repassa a saída da CLI sem interpretar o conteúdo.
- **Pré-requisitos externos:** especificação do MCP (modelcontextprotocol.io/specification/versioning, 2026-07-28/basic/versioning, 2026-07-28/schema e 2026-07-28/server/discover, lidas em 2026-11-12 e 2026-11-13: revisão atual `2026-07-28`; legadas com `initialize` até `2025-11-25`; servidor das duas eras é permitido); `python3` 3.9+ no PATH de quem usa o plugin.

## 4. Decisão Arquitetural
**Contexto:** brownfield. Referência: `skills/boson-atlas/assets/collectors/github.py`, que chama uma CLI por `subprocess` com lista de argumentos, sem shell, com timeout, e devolve o exit code; `skills/*/tests/test_architecture.py` para as regras de arquitetura (regra testada contra exemplo e contra o código real).

**Decisão:** servidor de arquivo único, stdlib, em `mcp/` na raiz do plugin. Cada tool vira uma linha de comando da CLI (`python3 <raiz>/skills/boson-atlas/scripts/atlas.py <comando> ... --json`) por `subprocess.run` com lista de argumentos, `--` antes de texto livre, timeout de 120 s e o ambiente herdado (`ATLAS_CONFIG_HOME` e afins). Nenhum `import` de código das skills (ADR-0017).

**Justificativa:** a CLI continua a fonte da verdade (ADR-0001: sem lógica duplicada); o servidor é trocável e testável com processo real; stdlib mantém a regra de instalação zero.

**Desvio do padrão existente:** Nenhum nas skills. Pasta nova `mcp/` na raiz, coberta pelo ADR-0017.

**Alternativas descartadas:** SDK oficial de MCP em Python (dependência externa, quebra a regra stdlib do ADR-0001); importar `atlas.py` como módulo (acopla o servidor ao código interno da skill e duplica a fronteira); só a era moderna (clientes legados não conectariam); só a legada (clientes só modernos não conectariam).

**ADRs:** ADR-0017.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** a sobrecarga do servidor sobre a CLI é a de abrir um processo; medido no IT-01 (resposta de `atlas_context` em menos de 5 s num atlas de fixture).
- **Segurança:** só tools de leitura; argumentos validados contra o `inputSchema` (tipo, faixa, enum, sem chave extra) antes de chamar a CLI; texto livre sempre depois de `--`, sem shell; nenhum valor de credencial em resposta ou log (a CLI já não mostra; o servidor não acrescenta nada do ambiente); stdout reservado ao protocolo, diagnóstico só no stderr.
- **Privacidade e dados pessoais:** N/A — mesmos dados que a CLI já devolve.
- **Disponibilidade e resiliência:** timeout de 120 s por chamada (vira resultado com `isError: true`); JSON inválido, método desconhecido ou erro numa chamada não derrubam o servidor; o servidor termina quando o stdin fecha.
- **Acessibilidade (UI):** N/A — sem interface.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** servidor MCP `fermion` (stdio) declarado no `.claude-plugin/plugin.json`; tools `atlas_config`, `atlas_doctor`, `atlas_context`, `atlas_lint`, `atlas_curate_list`

```text
declaração (plugin.json)
  "mcpServers": {"fermion": {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/mcp/fermion_mcp.py"]}}
  raiz do plugin para achar a CLI: a pasta acima de mcp/ (Path(__file__)), nunca o cwd

transporte
  JSON-RPC 2.0, uma mensagem por linha no stdin/stdout; stderr só para diagnóstico; termina com exit 0 quando o stdin fecha
  JSON inválido → erro -32700 (id null); objeto que não é request → -32600; método desconhecido → -32601; parâmetros inválidos → -32602
  notificações (sem id) nunca recebem resposta

era legada (versões suportadas: "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
  initialize {protocolVersion: V, ...} → {protocolVersion: V se suportada, senão "2025-11-25"; capabilities: {tools: {}}; serverInfo: {name: "fermion", version: <versão do plugin.json>}}
  notifications/initialized → nada; ping → {}
  tools/list e tools/call antes do initialize → também atendidos (cliente legado tolerante)

era moderna (versão suportada: "2026-07-28"; schema oficial conferido em 2026-11-13)   (v2)
  request moderno = traz _meta["io.modelcontextprotocol/protocolVersion"]; sem _meta de versão e sem initialize → atendido como legado (tolerante)
  _meta["io.modelcontextprotocol/clientCapabilities"] ausente → tolerado (não é erro)
  versão não suportada → erro -32022, message "Unsupported protocol version", data {supported: ["2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"], requested: V}
  todo resultado moderno leva resultType: "complete"
  server/discover → {resultType: "complete", supportedVersions: [...as mesmas...], capabilities: {tools: {}}, ttlMs: 3600000, cacheScope: "private",
                     _meta: {"io.modelcontextprotocol/serverInfo": {name: "fermion", version: <versão do plugin.json>}}}
  tools/list moderno → também ttlMs: 3600000 e cacheScope: "private" (o atlas é dado da organização)
  respostas legadas seguem o schema legado: sem resultType, ttlMs nem cacheScope

tools/list → as cinco tools, cada uma com name, description, inputSchema (JSON Schema com type "object" na raiz, additionalProperties: false) e annotations {readOnlyHint: true}   (v2: readOnlyHint)
  atlas_config        {}                                                         → atlas.py config --json
  atlas_doctor        {}                                                         → atlas.py doctor --json
  atlas_context       {query: string 1..500 (obrigatório), hops: int 0..2, limit: int 1..200, max_chars: int 500..200000}
                                                                                 → atlas.py context [--hops H] [--limit L] [--max-chars M] --json -- <query dividida em palavras>
  atlas_lint          {only: array de strings [a-z-]+ (opcional)}                → atlas.py lint --json [--only a,b]
  atlas_curate_list   {status: "inferred"|"confirmed"|"rejected" (opcional)}     → atlas.py curate list --json [--status S]

tools/call {name, arguments}
  tool desconhecida ou argumento fora do schema → erro -32602, sem chamar a CLI
  CLI com exit 0 (e exit 1 no atlas_lint, que significa "há ERRO no relatório") →
      {content: [{type: "text", text: <stdout>}], structuredContent: <stdout como JSON, se for objeto>, isError: false}
  CLI com exit 3 → isError: true, texto "atlas não configurado nesta máquina — rode a skill boson-atlas (onboarding)" + stderr da CLI
  outro exit diferente de 0 (e de 1 no lint) → isError: true, texto com o exit code e o stderr da CLI
  timeout (120 s) → isError: true, texto "atlas.py não respondeu em 120 s"
  python3/CLI ausente → isError: true, texto com o caminho procurado
```

**Design:** N/A — sem interface.

**Arquivos/módulos afetados:** ver `touches`. Criar `mcp/fermion_mcp.py`, `mcp/README.md`, `mcp/tests/` (suíte, regras de arquitetura do ADR-0017 e helpers); alterar `.claude-plugin/plugin.json` (`mcpServers`) e `.github/workflows/ci.yml` (passo da suíte `mcp/tests`).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Lista de tools | `tools/list` | as cinco tools com `inputSchema` fechado | UT-01 |
| Argumento inválido | tool desconhecida, tipo/faixa/enum errado, chave extra | erro -32602 sem abrir processo | UT-02 |
| Texto livre seguro | `query` começando com `-` ou com aspas e `;` | vai depois de `--`, como argumento único por palavra, sem shell | UT-03 |
| Mapeamento de saída | exit 0, exit 1 no lint, exit 3, outro exit, timeout | resultado e `isError` do contrato | UT-04 |
| Era legada | `initialize` com versão suportada, não suportada; `notifications/initialized`; `ping` | versão ecoada ou `2025-11-25`; sem resposta a notificação | UT-05 |
| Era moderna | `server/discover`; `tools/list` e `tools/call` modernos; request com versão em `_meta` não suportada; sem `clientCapabilities` | `DiscoverResult` do schema 2026-07-28; `resultType`, `ttlMs` e `cacheScope` nos resultados modernos; erro -32022 com `supported` e `requested`; tolerado | UT-06 |
| Mesmo resultado da CLI | servidor real por stdio num atlas de fixture | `atlas_context`, `atlas_lint` e `atlas_curate_list` devolvem o stdout igual ao da CLI | IT-01 |
| Atlas não configurado | `ATLAS_CONFIG_HOME` vazio | `atlas_doctor` com `isError: true` e a orientação de onboarding | IT-02 |
| Robustez do transporte | JSON inválido, método desconhecido, notificação, stdin fechado | -32700, -32601, nada, exit 0; o servidor segue respondendo depois dos erros | IT-03 |
| Fronteira com a CLI | código do servidor | só stdlib; nenhum import de `skills/`; processo só para a CLI do atlas | UT-07 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — código novo; a CLI do atlas já tem suíte própria.

### 7.2 Testes Unitários
- **UT-01** — Dado o servidor, quando recebe `tools/list`, então devolve exatamente as cinco tools do contrato, cada uma com `description`, `inputSchema` (JSON Schema `object`, `additionalProperties: false`, faixas e enums do contrato) e `annotations.readOnlyHint: true` (v2).
- **UT-02** — Dados `tools/call` com tool desconhecida, `query` vazia ou com mais de 500 caracteres, `hops: 3`, `status: "pending"`, `only: ["Bad Rule"]` e chave extra, quando chegam, então cada um recebe erro -32602 e nenhum processo é aberto (executor substituído no teste).
- **UT-03** — Dado `atlas_context` com `query: "-rf --hops 9; rm"`, quando a linha de comando é montada, então é uma lista que termina em `--json`, `--`, `-rf`, `--hops`, `9;`, `rm` e é executada sem shell.
- **UT-04** — Dado um executor falso, quando a CLI sai com 0 (stdout JSON), 1 no `atlas_lint`, 3, 2 e por timeout, então os resultados seguem o contrato (`structuredContent` só com JSON objeto; `isError` e textos de cada caso).
- **UT-05** — Dado `initialize` com `2025-06-18`, com `1999-01-01`, e depois `notifications/initialized` e `ping`, quando chegam, então a resposta traz `2025-06-18`, depois `2025-11-25`, nada para a notificação e `{}` para o ping, com `serverInfo.version` igual à do `plugin.json`.
- **UT-06** — Dados `server/discover`, `tools/list` e `tools/call` com `_meta` de versão `2026-07-28` (um deles sem `clientCapabilities`) e um `tools/list` com versão `1900-01-01`, quando chegam, então o discover devolve `resultType: "complete"`, as versões suportadas, `capabilities.tools`, `ttlMs: 3600000`, `cacheScope: "private"` e `_meta["io.modelcontextprotocol/serverInfo"]`; o `tools/list` moderno traz `resultType`, `ttlMs` e `cacheScope`; o `tools/call` moderno traz `resultType`; a falta de `clientCapabilities` é tolerada; a versão `1900-01-01` recebe -32022 com `data.supported` e `data.requested`; as respostas legadas do UT-05 não têm esses campos (v2).
- **UT-07** — Dado o código de `mcp/fermion_mcp.py` e exemplos que violam as regras, quando as regras do ADR-0017 rodam, então acusam import fora da stdlib ou de `skills/`, `shell=True` e processo que não seja a CLI do atlas; o código real não tem achado.

### 7.3 Testes de Integração
- **IT-01** — Dado um atlas de fixture criado pela própria CLI (`init` e `scan` com coletor falso, `ATLAS_CONFIG_HOME` temporário), quando o servidor real é aberto por stdio e recebe `initialize` e `tools/call` de `atlas_context`, `atlas_lint` e `atlas_curate_list`, então o texto de cada resultado é igual ao stdout da CLI com os mesmos argumentos, e cada resposta chega em menos de 5 s.
- **IT-02** — Dado `ATLAS_CONFIG_HOME` numa pasta vazia, quando `atlas_doctor` é chamado pelo servidor real, então o resultado tem `isError: true` e a orientação de onboarding.
- **IT-03** — Dado o servidor real, quando recebe uma linha de JSON inválido, um método desconhecido, uma notificação e depois um `ping`, então responde -32700, -32601, nada e `{}`, nessa ordem, e sai com 0 quando o stdin fecha.

### 7.4 Testes de Contrato
- N/A — o servidor repassa o JSON da CLI sem interpretar o conteúdo; a igualdade com a CLI é provada no IT-01.

### 7.5 Testes E2E
- N/A — a jornada de instalação é a do teste E2E da SPEC-0053; o protocolo é provado com o processo real nos IT-01 a IT-03, e a conexão no Claude Code é conferida no G4 (`/mcp` mostra `plugin:fermion:fermion` conectado).

### 7.6 Outros
- Tempo de resposta no IT-01 (menos de 5 s por chamada no atlas de fixture).

**Dublês e dados de teste:** executor de processo substituível nos UT; atlas de fixture e coletor falso como nos testes da `org-atlas` (`skills/boson-atlas/tests/helpers.py` como referência, sem importar dela).

**Ambiente de execução:** local e CI, sem rede; IT abrem o servidor e a CLI como processos reais.

## 8. Plano de Rollout
- **Estratégia:** deploy direto: o servidor sobe quando o plugin `fermion` é instalado ou atualizado.
- **Dados/schema:** N/A.
- **Compatibilidade:** clientes MCP das duas eras; quem usa a skill por cópia não é afetado.
- **Observabilidade:** stderr do servidor (visível nos logs de MCP do cliente) com uma linha por erro de transporte, sem argumentos nem saída da CLI.
- **Rollback:** reverter o merge; quem não quiser o servidor desabilita em `/mcp`.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Quais tools entram primeiro? — As cinco de leitura; nada que grave, e confirmar ou rejeitar convenção nunca por MCP (ADR-0012) (thomas, 2026-11-12)
- [x] Qual era do protocolo? — As duas: legada até `2025-11-25` e moderna `2026-07-28`, para qualquer cliente conectar (thomas, 2026-11-12)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Protocolo e tools**
- [ ] Red: UT-01 a UT-07 em `mcp/tests/` com a tag `SPEC-0054:<ID>`, falhando pelo motivo certo
- [ ] Green: `mcp/fermion_mcp.py` (duas eras, cinco tools, executor por subprocess) e regras do ADR-0017
- [ ] Refactor mantendo tudo verde

**Fase 2: Processo real**
- [ ] Red: IT-01 a IT-03 falhando pelo motivo certo
- [ ] Green: servidor real por stdio contra um atlas de fixture; `mcpServers` no `plugin.json`; `mcp/README.md`; passo `mcp/tests` na CI
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4), com `/mcp` mostrando `plugin:fermion:fermion` conectado
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy via pipeline (G6) — N/A: o servidor sobe com o plugin
- [ ] Relatório de Entrega, README (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 997634e (árvore suja) | 2026-11-12 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=86)); nota: vermelho em 1df8578: mcp/tests 57 testes, 86 falhas (subtests), 0 erros — só 'mcp/fermion_mcp.py não existe'; exemplos das regras do UT-07 e fixture passam; 1ª execução falhou por mcp/tests/** ausente de test_paths (config corrigida) — 1df8578 | 2026-11-13 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — d1c6633 | 2026-11-13 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — d1c6633 | 2026-11-13 |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-11-13 | G1 | spec | SPEC_DEFECT do Test-writer: o schema oficial 2026-07-28 diverge do contrato na era moderna — DiscoverResult exige resultType, ttlMs e cacheScope e põe a identidade em _meta['io.modelcontextprotocol/serverInfo'] (sem serverInfo no topo); todo resultado moderno exige resultType; ListToolsResult exige ttlMs e cacheScope; requests modernos trazem clientCapabilities em _meta | Test-writer conferiu /specification/2026-07-28/schema, /server/discover e /basic/versioning.md em 2026-11-13; nenhum teste escrito | thomas | Emenda v2 — era moderna conforme o schema oficial 2026-07-28 (DiscoverResult, resultType, ttlMs/cacheScope, serverInfo em _meta, clientCapabilities tolerado, readOnlyHint) (H1 thomas, 2026-11-13) | 2026-11-13 |
| IMP-02 | 2026-11-13 | G2 | spec | Contratos em conflito: a SPEC-0054 declara mcpServers.fermion no plugin.json, mas o contrato da SPEC-0053 (e o UT-02 dela) proíbe qualquer chave de componente no plugin.json; com a declaração, test_plugin.py falha em 2 testes | Implementer mediu com mcpServers (validate exit 0, 2 testes da SPEC-0053 vermelhos) e reverteu; servidor pronto e verde em 064060d | thomas | Emenda v3 da SPEC-0053 — plugin.json pode declarar mcpServers com o servidor fermion (H1 thomas, 2026-11-13) | 2026-11-13 |

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0054`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-13 | Era moderna conforme o schema oficial 2026-07-28: `DiscoverResult` com `resultType`, `ttlMs: 3600000`, `cacheScope: "private"` e identidade em `_meta["io.modelcontextprotocol/serverInfo"]`; `resultType: "complete"` em todo resultado moderno; `ttlMs`/`cacheScope` no `tools/list` moderno; `clientCapabilities` ausente tolerado; request sem `_meta` e sem `initialize` atendido como legado; respostas legadas sem os campos modernos; `annotations.readOnlyHint: true` nas cinco tools | IMP-01: o contrato v1 tinha `serverInfo` no topo do discover e não tinha os campos obrigatórios do schema | nenhuma (sem consumidores) | thomas, 2026-11-13 |
