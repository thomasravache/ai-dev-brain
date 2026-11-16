---
id: SPEC-0059
title: "Servidor MCP: tools brain de leitura do segundo cérebro"
tier: full
type: feature
user_facing: false
status: implemented
created: 2026-11-13
parent: SPEC-0031
depends_on: [SPEC-0054, SPEC-0058]
consumes_contract: []
contract_version: 2
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [mcp/**, .claude-plugin/plugin.json]
adrs: [ADR-0017, ADR-0014]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-13
---

# SPEC-0059 — Servidor MCP: tools brain de leitura do segundo cérebro

## 1. Visão Geral
O servidor MCP `fermion` (SPEC-0054) ganha oito tools de leitura do segundo cérebro (`photon-brain`): `brain_config`, `brain_doctor`, `brain_search`, `brain_related`, `brain_links`, `brain_context`, `brain_inbox_list` e `brain_lint`. Cada tool só chama a CLI `skills/photon-brain/scripts/brain.py` e devolve o mesmo resultado dela. Notas confidenciais nunca saem por MCP.

## 2. Motivação & Escopo
**Motivação:** frente 3 do épico SPEC-0031, segunda na ordem (atlas, depois brain). Com tools tipadas, qualquer cliente MCP consulta o vault do usuário sem shell e sem montar a linha de comando, e a política fica fora do alcance do agente: o servidor só expõe leitura e nunca pede notas confidenciais.

**Objetivos (dentro do escopo):**
- Oito tools `brain_*` sobre os comandos de leitura do `brain.py`, com `inputSchema` fechado e `annotations.readOnlyHint: true`.
- Mapeamento de saída igual ao do atlas: exit 0 (e exit 1 no `brain_doctor` e no `brain_lint`, que significa "há ERRO no relatório") é resultado normal; exit 3 = cérebro não configurado.
- A regra de arquitetura "processo só para a CLI do atlas" (SPEC-0054:UT-07) passa a aceitar também `brain.py` (a SPEC-0060 acrescenta `spec_graph.py` e a SPEC-0061 o `fermion_doctor.py`), como o ADR-0017 já permite.

**Não-objetivos (fora do escopo):**
- Tools que gravam: `capture`, `ingest`, `new-note`, `relate`, `index`, `inbox done`, `backup`, `restore`, `export-notebooklm`, `init`, `context add`, `process` (executa processadores externos).
- `--include-confidential`: nenhuma tool aceita; nota confidencial só sai pela CLI, quando a pessoa pede (ADR-0014).
- Tools `sdd_*` (SPEC-0060), resources e prompts.

## 3. Dependências
- **Implementações necessárias:** SPEC-0054 (servidor, protocolo das duas eras, validação de argumentos, `run_cli`), e os comandos `config`, `doctor`, `search`, `related`, `links`, `context`, `inbox list` e `lint` com `--json` do `photon-brain` (já na `main`, `BRAIN_VERSION` 2026.11.6).
- **Contratos consumidos:** N/A — o servidor repassa o JSON da CLI sem interpretar o conteúdo.
- **Pré-requisitos externos:** os mesmos da SPEC-0054 (especificação MCP `2026-07-28` e legadas até `2025-11-25`; `python3` 3.9+).

## 4. Decisão Arquitetural
**Contexto:** brownfield. Referência: as tools `atlas_*` em `mcp/fermion_mcp.py` (`TOOLS`, `command_args`, `map_output`) e as suítes `mcp/tests/test_server.py` e `mcp/tests/test_architecture.py`.

**Decisão:** as tools `brain_*` entram na mesma tabela `TOOLS` e no mesmo `command_args`, apontando para `skills/photon-brain/scripts/brain.py`. Texto livre vai sempre depois de `--` (busca, contexto e links) e toda opção com valor vai colada (`--note=<valor>`, `--context=<valor>`; o argparse recusa `--note -x`, e assim nenhum valor vira argumento próprio), sem shell. O ambiente é herdado (`BRAIN_CONFIG_HOME`).

**Justificativa:** um servidor só, com prefixo por skill (épico, frente 3); a CLI continua a fonte da verdade (ADR-0001, ADR-0017).

**Desvio do padrão existente:** Nenhum. A SPEC-0054 fixava "as cinco tools" no `tools/list`; esta spec acrescenta as `brain_*` (Emenda v3 da SPEC-0054, aprovada junto com esta spec: UT-01 passa a conferir as tools por prefixo).

**Alternativas descartadas:** um servidor MCP por skill (três processos e três entradas no `/mcp` para a mesma instalação); expor `capture` agora (grava no vault; fica para quando houver política de escrita por MCP decidida num ADR); aceitar `include_confidential` (o agente poderia pedir sem a pessoa saber, contra o ADR-0014).

**ADRs:** ADR-0017 (camada fina), ADR-0014 (confidenciais).

## 5. Requisitos Não-Funcionais
- **Ordem:** depois da SPEC-0058, que estende a regra de versão do plugin a `mcp/`.
- **Desempenho e escala:** mesma sobrecarga da SPEC-0054 (um processo por chamada); medido no IT-01 (cada resposta em menos de 5 s num vault de fixture).
- **Segurança:** só leitura; argumentos validados contra o `inputSchema` antes de abrir processo; `--include-confidential` nunca é passado; texto livre depois de `--` ou como valor de opção; sem shell; nada do ambiente no resultado.
- **Privacidade e dados pessoais:** notas confidenciais ficam de fora (a CLI as omite sem a opção); `brain_lint` repassa os achados `secret-in-note` e `personal-data` como a CLI, que nunca mostra o valor.
- **Disponibilidade e resiliência:** timeout de 120 s por chamada; erros viram `isError: true` sem derrubar o servidor (como na SPEC-0054).
- **Acessibilidade (UI):** N/A — sem interface.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** tools `brain_*` do servidor MCP `fermion`

```text
tools/list → as tools atlas_* da SPEC-0054 e mais estas, todas com inputSchema object, additionalProperties: false, annotations {readOnlyHint: true}
  brain_config       {}                                                    → brain.py config --json
  brain_doctor       {}                                                    → brain.py doctor --json
  brain_search       {query: string 1..500 (obrigatório), context: string 1..100, type: string 1..50, tag: string 1..100, limit: int 1..100}
                                                                           → brain.py search [--context=C] [--type=T] [--tag=G] [--limit=L] --json -- <query dividida em palavras>
  brain_related      {note: string 1..500, text: string 1..2000, limit: int 1..100}; inputSchema com as duas opcionais e a descrição "exatamente um de note ou text"; o servidor confere depois do schema (nenhum ou os dois → -32602)
                                                                           → brain.py related (--note=N | --text=X) [--limit=L] --json
  brain_links        {note: string 1..500 (obrigatório)}                   → brain.py links --json -- <note>
  brain_context      {query: string 1..500 (obrigatório), context: string 1..100, hops: int 0..2, limit: int 1..50, max_chars: int 500..200000}
                                                                           → brain.py context [--context=C] [--hops=H] [--limit=L] [--max-chars=M] --json -- <query dividida em palavras>
  brain_inbox_list   {}                                                    → brain.py inbox list --json
  brain_lint         {only: array de strings [a-z-]+ (opcional)}           → brain.py lint --json [--only=a,b]
  strings: o mesmo padrão de query da SPEC-0054 (sem caracteres de controle, exceto tab, LF e CR); query só de espaços → -32602 (sem palavra depois de dividir)

tools/call
  argumento fora do schema (inclusive note e text juntos, ou nenhum dos dois em brain_related) → erro -32602, sem abrir processo
  exit 0 → isError: false, content texto = stdout, structuredContent = stdout como JSON se for objeto
  exit 1 em brain_doctor e brain_lint com stdout JSON objeto (há ERRO no relatório) → isError: false, como o exit 0
  exit 1 sem stdout JSON objeto (erro de leitura, vault ausente: OSError ou BrainError da CLI) → isError: true com o stderr
  exit 2 em brain_links e brain_related (nota não encontrada, nota confidencial recusada) → isError: true com o stderr
  exit 3 → isError: true, "segundo cérebro não configurado nesta máquina — rode a skill photon-brain (onboarding)" + stderr
  exit 2 em brain_lint (regra desconhecida em only) → isError: true com o stderr
  outro exit → isError: true com o exit code e o stderr; timeout → "brain.py não respondeu em 120 s"; CLI ausente → caminho procurado
nenhuma linha de comando contém --include-confidential como argumento próprio: toda opção com valor vai colada (--opção=valor), e texto livre só depois de --
```

**Design:** N/A — sem interface.

**Arquivos/módulos afetados:** ver `touches`. Alterar `mcp/fermion_mcp.py` (tools, linhas de comando, mapeamento), `mcp/tests/` (UT, IT, regra de arquitetura das três CLIs, fixture de vault), `mcp/README.md` (tools novas) e `.claude-plugin/plugin.json` (versão).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Lista de tools | `tools/list` | as `atlas_*` e as oito `brain_*` com schema fechado e `readOnlyHint` | UT-01 |
| Argumento inválido | tipo, faixa, chave extra; `note` e `text` juntos ou nenhum; query só de espaços | -32602 sem abrir processo | UT-02 |
| Texto livre seguro | `query` ou `note` começando com `-`, com `;` e aspas | depois de `--` ou como valor de opção; sem shell; nunca `--include-confidential` | UT-03 |
| Mapeamento de saída | exit 0, 1 com e sem relatório JSON, 2 (lint, links, related), 3, outro, timeout, CLI ausente | resultado e `isError` do contrato | UT-04 |
| Nota inexistente ou confidencial | `brain_links` ou `brain_related` por `note` | `isError: true` com o stderr da CLI, sem o conteúdo da nota | IT-03 |
| Mesmo resultado da CLI | servidor real num vault de fixture | `brain_search`, `brain_context`, `brain_links` e `brain_lint` iguais ao stdout da CLI | IT-01 |
| Cérebro não configurado | `BRAIN_CONFIG_HOME` vazio | `brain_doctor` com `isError: true` e a orientação de onboarding | IT-02 |
| Confidencial fora | vault de fixture com nota `confidential: true` que casa com a busca | nenhum resultado `brain_*` traz o corpo dela nem a tem como resultado (`path`); o título no `log.md` é da CLI (SPEC-0064) | IT-03 |
| Fronteira com as CLIs | código do servidor | processo só para as três CLIs das skills; sem import de `skills/` | UT-05 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — as tools `atlas_*` já têm suíte (SPEC-0054) e continuam passando sem mudança.

### 7.2 Testes Unitários
- **UT-01** — Dado o servidor, quando recebe `tools/list` (era legada e moderna), então a lista traz as cinco `atlas_*` da SPEC-0054 e as oito `brain_*` do contrato, cada uma com `description`, `inputSchema` fechado com as faixas do contrato e `annotations.readOnlyHint: true`.
- **UT-02** — Dados `brain_search` sem `query`, `brain_context` com `hops: 3`, `brain_related` com `note` e `text` juntos, `brain_related` sem nenhum dos dois, `brain_lint` com `only: ["Bad"]`, `brain_search` com `query: "   "` e uma chave extra, quando chegam, então cada um recebe -32602 e nenhum processo é aberto.
- **UT-03** — Dados `brain_search` com `query: "-rf --include-confidential; x"`, `brain_links` com `note: "--json"`, `brain_related` com `note: "-x"` e `brain_context` com `query: "add x"`, quando as linhas de comando são montadas, então a busca termina em `--json`, `--`, `-rf`, `--include-confidential;`, `x`; a de links em `--json`, `--`, `--json`; a de related tem `--note=-x`; a de context começa com `context` seguido de opção (nunca `context add`, que cria contexto) e termina em `--`, `add`, `x`; todas sem shell; e nenhuma linha de comando de nenhuma tool `brain_*` contém `--include-confidential` antes do `--`.
- **UT-04** — Dado um executor falso, quando a CLI sai com 0 (JSON), 1 no `brain_doctor` e no `brain_lint` com relatório JSON, 1 sem stdout, 2 no `brain_lint` e no `brain_links`, 3, 4, por timeout, com `FileNotFoundError` e com `OSError`, então os resultados seguem o contrato (`structuredContent` só com JSON objeto; `isError` e textos de cada caso).
- **UT-05** — Dados o código de `mcp/fermion_mcp.py` e exemplos que violam as regras, quando as regras do ADR-0017 rodam, então acusam processo para um script que não seja `atlas.py` ou `brain.py` das skills, import de `skills/` e `shell=True`; o código real não tem achado.

### 7.3 Testes de Integração
- **IT-01** — Dado um vault de fixture criado pela própria CLI (`init` num `BRAIN_CONFIG_HOME` temporário e notas com `new-note`), quando o servidor real é aberto por stdio e recebe `tools/call` de `brain_search`, `brain_context`, `brain_links` e `brain_lint`, então o texto de cada resultado é igual ao stdout da CLI com os mesmos argumentos, e cada resposta chega em menos de 5 s.
- **IT-02** — Dado `BRAIN_CONFIG_HOME` numa pasta vazia, quando `brain_doctor` é chamado pelo servidor real, então o resultado tem `isError: true` e a orientação de onboarding.
- **IT-03** — Dado o vault de fixture com uma nota `confidential: true` cujo título e corpo casam com a consulta, quando `brain_search`, `brain_context`, `brain_related` (por texto e por `note` com o nome dela) e `brain_links` (com o nome dela) são chamados pelo servidor real, então nenhum resultado contém o corpo dessa nota, nenhum resultado de busca, contexto, related ou backlink tem a nota como `path`, `confidential_omitted` é pelo menos 1, e `brain_related`/`brain_links` por nome devolvem `isError: true` com a recusa da CLI; `brain_links` com uma nota inexistente também devolve `isError: true`.

### 7.4 Testes de Contrato
- N/A — o servidor repassa o JSON da CLI sem interpretar; a igualdade com a CLI é provada no IT-01.

### 7.5 Testes E2E
- N/A — a instalação é a jornada E2E da SPEC-0053 e o protocolo é provado com o processo real nos IT; a conexão no Claude Code é conferida no G4 (`/mcp` lista as tools `brain_*`).

### 7.6 Outros
- Tempo de resposta no IT-01 (menos de 5 s por chamada no vault de fixture).

**Dublês e dados de teste:** executor substituível nos UT; vault de fixture criado pela CLI em pasta temporária (referência: `skills/photon-brain/tests/` para montar vault, sem importar dela); nunca a configuração real do cérebro.

**Ambiente de execução:** local e CI, sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto com `claude plugin update` (versão do plugin sobe).
- **Dados/schema:** N/A.
- **Compatibilidade:** clientes das duas eras; `tools/list` só cresce; as `atlas_*` não mudam.
- **Observabilidade:** stderr do servidor, como na SPEC-0054.
- **Rollback:** reverter o merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Entram tools que gravam (por exemplo `brain_capture`)? — Não nesta spec: só leitura, como o atlas; gravação por MCP fica para um ADR de política de escrita (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-13: "pode seguir no piloto automático com o recomendado"; revisável no H1)
- [x] As tools aceitam incluir notas confidenciais? — Não: nota confidencial só sai pela CLI quando a pessoa pede (ADR-0014) (recomendação do arquiteto, aceita no piloto automático, thomas, 2026-11-13; revisável no H1)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Tools, schemas e linhas de comando**
- [x] Red: UT-01 a UT-04 em `mcp/tests/test_server.py` (UT-01 da SPEC-0054 passa a conferir as `atlas_*` por prefixo, Emenda v3 da SPEC-0054) com a tag `SPEC-0059:<ID>`, falhando pelo motivo certo
- [x] Green: as oito `brain_*` em `TOOLS`, `command_args` e `map_output` de `mcp/fermion_mcp.py`

**Fase 2: Fronteira com as CLIs**
- [x] Red: UT-05 em `mcp/tests/test_architecture.py` (processo só para `atlas.py` e `brain.py`)
- [x] Green: regra aceita as duas CLIs; código real sem achado

**Fase 3: Servidor real num vault de fixture**
- [x] Red: IT-01 a IT-03 (vault criado pela CLI do `photon-brain` num `BRAIN_CONFIG_HOME` temporário, com nota confidencial)
- [x] Green: resultados iguais aos da CLI, confidencial fora, onboarding quando não configurado

**Fase final: Integração, entrega e documentação**
- [x] Validar: suíte completa + arquitetura (G2/G3); `mcp/README.md` e `version` do `plugin.json`
- [x] Review independente (G4), com `/mcp` listando as `brain_*` numa sessão real do Claude Code
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega e README (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — c5417ad (árvore suja) | 2026-11-13 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=108)) — e5bc324 | 2026-11-16 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 666744d | 2026-11-16 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 6e42069 | 2026-11-16 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer independente: APPROVED (rodada 1 com 3 minors e 3 nits; minors corrigidos com teste antes em 459a194/666744d e reconferidos: APPROVED). Verificação manual em 2026-11-16 com Claude Code 2.1.322 e --plugin-dir: servidor plugin:fermion:fermion connected, tools 5 atlas_* e 8 brain_* no init. — 58bd047 | 2026-11-16 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 82ed945 | 2026-11-16 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-16 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-16 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 5e9faa6 | 2026-11-16 |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-11-16 | G1 | spec | SPEC_DEFECT do Test-writer: IT-03 exige que busca e contexto não tragam o título da nota confidencial, mas brain.py new-note grava o título em log.md e search/context devolvem log.md (CLI fora do touches); e opções com valor em dois argumentos deixariam um valor '--include-confidential' antes do '--' (recusado pelo argparse, mas contra a letra do contrato) | Test-writer conferiu na CLI real em 2026-11-16: search -- zebracorn secret devolve log.md com o título; corpo não vaza | thomas | Emenda v2 — opções com valor coladas; IT-03 sem o título do log.md, que vai para a SPEC-0064 (photon-brain) | 2026-11-16 |

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
- O servidor MCP `fermion` ganhou oito tools de leitura do segundo cérebro: `brain_config`, `brain_doctor`, `brain_search`, `brain_related`, `brain_links`, `brain_context`, `brain_inbox_list` e `brain_lint`. Cada uma chama a CLI `brain.py` da `photon-brain` e devolve o resultado dela; nenhuma grava no vault nem traz nota confidencial.
- Argumento inválido (inclusive Unicode com surrogate solto, também nas `atlas_*`) é recusado com -32602 antes de abrir processo.
- `mcp/README.md` com as tools, o mapeamento de saída e a segurança; `version` do plugin 2026.11.8.

### Como foi feito
- Mesma tabela `TOOLS`, `command_args` e `map_output` das `atlas_*` (SPEC-0054, ADR-0017); `brain_command_args` cola toda opção com valor (`--opção=valor`) e põe texto livre depois de `--`; `check_brain_arguments` cobre "exatamente um de note ou text" e query só de espaços; `_check` recusa surrogate solto.
- Testes em 7d7cf12, 4f016c4 e e5bc324; implementação em 90a7da8; revisão: testes 459a194 e correção 666744d.
- **Emenda v2** (contrato 2, IMP-01): opções coladas; o título da nota confidencial no `log.md` é da CLI e foi para a SPEC-0064.
- **Revisão G4:** APPROVED na rodada 1 com três minors (exit 1 fora de doctor/lint sem teste, `confidential_omitted` não conferido pelo MCP, surrogate solto virando -32603), corrigidos com teste antes e reconferidos (APPROVED). Verificação manual: numa sessão real do Claude Code 2.1.322 o servidor conecta e lista as 5 `atlas_*` e as 8 `brain_*`.

### Prova de Correção
N/A — feature.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | `tools/list` com as cinco `atlas_*` e as oito `brain_*`, schemas fechados e `readOnlyHint`, nas duas eras | PASS | `test_brain_server.py::BrainToolsListTest` — CI do PR #33 (run 43888780543, Python 3.9 e 3.15) e suíte local no G5 |
| UT-02 | Argumento inválido (tipo, faixa, chave extra, `note`+`text`, query só de espaços, surrogate solto) → -32602 sem processo | PASS | `test_brain_server.py::BrainInvalidArgumentsTest, BrainSurrogateTest` — CI do PR #33 (run 43888780543, Python 3.9 e 3.15) e suíte local no G5 |
| UT-03 | Opções coladas, texto livre depois de `--`, `context` nunca vira `context add`, nunca `--include-confidential` | PASS | `test_brain_server.py::BrainCommandLineTest` — CI do PR #33 (run 43888780543, Python 3.9 e 3.15) e suíte local no G5 |
| UT-04 | Mapeamento de exit 0, 1 (só doctor/lint como relatório), 2, 3, outro, timeout, CLI ausente e `OSError` | PASS | `test_brain_server.py::BrainOutputMappingTest` — CI do PR #33 (run 43888780543, Python 3.9 e 3.15) e suíte local no G5 |
| UT-05 | Processo só para `atlas.py` e `brain.py`, sem import de `skills/` e sem shell | PASS | `test_architecture.py::BrainBoundaryTest (também no `arch_test` do G3)` — CI do PR #33 (run 43888780543, Python 3.9 e 3.15) e suíte local no G5 |
| IT-01 | Servidor real num vault da CLI: search, context, links e lint iguais ao stdout da CLI, cada um em menos de 5 s | PASS | `test_brain_server.py::BrainSameResultAsCliTest` — CI do PR #33 (run 43888780543, Python 3.9 e 3.15) e suíte local no G5 |
| IT-02 | `BRAIN_CONFIG_HOME` vazio: `brain_doctor` com `isError` e a orientação de onboarding | PASS | `test_brain_server.py::BrainNotConfiguredTest` — CI do PR #33 (run 43888780543, Python 3.9 e 3.15) e suíte local no G5 |
| IT-03 | Nota confidencial: corpo nunca sai, nunca é `path` de resultado, `confidential_omitted` ≥ 1, recusa por nome | PASS | `test_brain_server.py::BrainConfidentialTest` — CI do PR #33 (run 43888780543, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado — padrão das `atlas_*` (SPEC-0054, ADR-0017)
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — IT-01 abaixo de 5 s por chamada; timeout de 120 s e `isError` sem derrubar o servidor (UT-04)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: distribuído pelo plugin; conferido numa sessão real no G4
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout — stderr do servidor; rollback = reverter o merge
- [x] Documentação raiz e CHANGELOG atualizados (G7) — `mcp/README.md`; sem CHANGELOG raiz
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: o projeto não declara `living_docs`
- [x] Pendências registradas como novas specs (ou nenhuma) — SPEC-0064

### Deploy
N/A — plugin `fermion` 2026.11.8, PR #33.

### Pendências
- SPEC-0064 (proposta): o `log.md` traz o título da nota confidencial em `search` e `context` da própria CLI.
- Nits da revisão, sem spec: `note` só de espaços abre processo (a CLI responde "nota não encontrada"); docstring de `atlas_names` em `mcp/tests/test_server.py` cita tools das SPEC-0060/0061; sem teste próprio de surrogate nas `atlas_*` (mesmo caminho de validação).

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0059`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-16 | Opções com valor sempre coladas (`--opção=valor`) em todas as `brain_*`; IT-03 e Mapa: a nota confidencial nunca aparece como resultado (`path`) nem tem o corpo exposto, e o título que a CLI grava no `log.md` sai do escopo (vai para a SPEC-0064, da `photon-brain`) | IMP-01: SPEC_DEFECT do Test-writer — `new-note` grava o título no `log.md`, que `search`/`context` devolvem (CLI fora do `touches`); valor `--include-confidential` em opção de dois argumentos ficaria antes do `--` | nenhuma (sem consumidores) | thomas, 2026-11-16 (piloto automático com o recomendado) |
