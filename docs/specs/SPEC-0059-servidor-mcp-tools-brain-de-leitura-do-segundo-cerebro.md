---
id: SPEC-0059
title: "Servidor MCP: tools brain de leitura do segundo cérebro"
tier: full
type: feature
user_facing: false
status: approved
created: 2026-11-13
parent: SPEC-0031
depends_on: [SPEC-0054, SPEC-0058]
consumes_contract: []
contract_version: 1
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

**Decisão:** as tools `brain_*` entram na mesma tabela `TOOLS` e no mesmo `command_args`, apontando para `skills/photon-brain/scripts/brain.py`. Texto livre vai sempre depois de `--` (busca, contexto e links) ou colado na opção (`--note=<valor>`, `--text=<valor>`, porque o argparse recusa `--note -x`), sem shell. O ambiente é herdado (`BRAIN_CONFIG_HOME`).

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
                                                                           → brain.py search [--context C] [--type T] [--tag G] [--limit L] --json -- <query dividida em palavras>
  brain_related      {note: string 1..500, text: string 1..2000, limit: int 1..100}; inputSchema com as duas opcionais e a descrição "exatamente um de note ou text"; o servidor confere depois do schema (nenhum ou os dois → -32602)
                                                                           → brain.py related (--note=N | --text=X) [--limit L] --json
  brain_links        {note: string 1..500 (obrigatório)}                   → brain.py links --json -- <note>
  brain_context      {query: string 1..500 (obrigatório), context: string 1..100, hops: int 0..2, limit: int 1..50, max_chars: int 500..200000}
                                                                           → brain.py context [--context C] [--hops H] [--limit L] [--max-chars M] --json -- <query dividida em palavras>
  brain_inbox_list   {}                                                    → brain.py inbox list --json
  brain_lint         {only: array de strings [a-z-]+ (opcional)}           → brain.py lint --json [--only a,b]
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
nenhuma linha de comando contém --include-confidential
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
| Confidencial fora | vault de fixture com nota `confidential: true` que casa com a busca | nenhum resultado `brain_*` traz o título ou o corpo dela | IT-03 |
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
- **IT-03** — Dado o vault de fixture com uma nota `confidential: true` cujo título e corpo casam com a consulta, quando `brain_search`, `brain_context`, `brain_related` (por texto e por `note` com o nome dela) e `brain_links` (com o nome dela) são chamados pelo servidor real, então nenhum resultado contém o corpo dessa nota, busca e contexto não trazem o título, e `brain_related`/`brain_links` por nome devolvem `isError: true` com a recusa da CLI; `brain_links` com uma nota inexistente também devolve `isError: true`.

### 7.4 Testes de Contrato
- N/A — o servidor repassa o JSON da CLI sem interpretar; a igualdade com a CLI é provada no IT-01.

### 7.5 Testes E2E
- N/A — a instalação é a jornada do SPEC-0053:E2E-01 e o protocolo é provado com o processo real nos IT; a conexão no Claude Code é conferida no G4 (`/mcp` lista as tools `brain_*`).

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0059`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
