---
id: SPEC-0036
title: "org-atlas: cruzamento de fontes, grafo e páginas geradas"
tier: full
type: feature
user_facing: false
status: implemented
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0033]
consumes_contract: []
contract_version: 1
touches: [skills/org-atlas/SKILL.md, skills/org-atlas/scripts/atlas.py, skills/org-atlas/references/atlas-layout.md, skills/org-atlas/references/graph.md, skills/org-atlas/assets/pages/**, skills/org-atlas/tests/test_build.py, skills/org-atlas/tests/fixtures/build/**, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0011]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0036 — org-atlas: cruzamento de fontes, grafo e páginas geradas

## 1. Visão Geral
Implementa o `atlas.py build`, que roda sozinho no fim de cada `scan` e pode ser chamado à parte. Ele junta os snapshots de todos os coletores num **grafo único** (`graph.json`), **infere as ligações** que nenhum coletor declara (o serviço que usa o banco, a fila ou outro serviço, descobertos pelas referências de configuração) e gera as páginas para pessoas: `ATLAS.md`, `services/<id>.md` e `platform/<categoria>.md`. O texto escrito por pessoas nunca é reescrito.

## 2. Motivação & Escopo
**Motivação:** o valor do atlas está em cruzar fontes. Um coletor de entrega sabe que o deployment aponta para `db.interno`; um coletor de dados (ou um fato do `generic`) sabe que `db.interno` é o banco `payments`; só o cruzamento diz que o serviço depende do banco.

**Objetivos (dentro do escopo):**
- Junção das entidades pela chave `kind:id`; atributos de coletores diferentes combinados; conflito de valor registrado em `conflicts` (vale o primeiro coletor na ordem do `atlas-config.yml`).
- Regras de inferência: (1) `deployment` com `sourced_from` e `deploys` liga o serviço ao repositório; (2) `config_refs` cujo host bate com o `host` ou o nome de um `datastore`, `queue`, `topic` ou `bucket` conhecido gera `depends_on` inferido; (3) `config_refs` cujo host bate com o nome de outro `service` gera `depends_on` inferido entre serviços.
- `graph.json` determinístico (nós, arestas, coletores de origem, `seen_at` herdado do `_scan.json`, `inferred`).
- Páginas geradas a partir de `assets/pages/`, com regiões `<!-- atlas:begin ... -->`; entidade que sumiu mantém a página, com a região trocada por "não visto desde AAAA-MM-DD".

**Não-objetivos (fora do escopo):**
- Inferir a direção (leitura ou escrita) de uma dependência.
- Convenções (SPEC-0037), pacote de contexto (SPEC-0038) e lint (SPEC-0039).

## 3. Dependências
- **Implementações necessárias:** SPEC-0033 — snapshots e `_scan.json`.
- **Contratos consumidos:** N/A (lê os snapshots já normalizados pela SPEC-0033, implementada).
- **Pré-requisitos externos:** N/A.

## 4. Decisão Arquitetural
**Contexto:** a referência para regiões geradas é o `index` da `second-brain` (SPEC-0019, ADR-0007): só o conteúdo entre `<!-- brain:begin <nome> -->` e `<!-- brain:end <nome> -->` é reescrito.

**Decisão:** funções `merge_snapshots` → `infer_relations` → `render_graph` → `render_pages`, todas puras exceto a gravação final, com as mesmas regras de região (marcadores `atlas:`).

**Justificativa:** funções puras deixam as regras de inferência testáveis uma a uma, e as regiões geradas preservam o que o time escreveu.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** apagar a página de uma entidade que sumiu (perderia as notas do time); inferência por similaridade de nomes (falsos positivos demais; só igualdade de host ou de nome).

**ADRs:** ADR-0010, ADR-0011.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** 500 serviços e 5.000 relações em menos de 5 s (fixture gerada).
- **Segurança:** só lê snapshots já mascarados; nenhuma escrita fora das regiões geradas e de `graph.json`.
- **Privacidade e dados pessoais:** N/A — só metadados já filtrados pela SPEC-0033.
- **Disponibilidade e resiliência:** snapshot ilegível → aviso e o `build` segue com os outros.
- **Acessibilidade (UI):** páginas em Markdown simples, legíveis no GitHub e em qualquer editor.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** comando `build`, formato do `graph.json` (consumido pela SPEC-0038 e pela SPEC-0039) e páginas geradas.

```text
atlas.py build [--json]
  roda no fim de todo scan; imprime "Grafo: N nós, M arestas (I inferidas), C conflitos; P páginas atualizadas"

graph.json (contrato v1, documentado em references/graph.md):
  {"version": 1, "organization": "...", "built_at": "AAAA-MM-DD",
   "nodes": [{"key": "service:payments", "kind": "service", "name": "...", "attrs": {...},
              "sources": ["argocd"], "seen_at": "AAAA-MM-DD", "conflicts": [{"attr", "values": {"<coletor>": v}}]}],
   "edges": [{"from": "...", "to": "...", "type": "depends_on", "sources": ["argocd"], "inferred": true,
              "evidence": "DB_URL=db.interno"}]}
  nós e arestas ordenados pela chave; mesmo conjunto de snapshots → arquivo idêntico

Páginas:
  ATLAS.md                → regiões: summary (contagens por tipo), services (lista com links), scans (seen_at por coletor)
  services/<id>.md        → regiões: summary, repository, deployments (por ambiente), depends-on, used-by, owners, pipelines, sources
  platform/<categoria>.md → região: entities
  arquivo novo criado a partir de assets/pages/<tipo>.md (título, regiões e "## Notas" para o time)
  entidade ausente no grafo: região summary → "_Não visto desde AAAA-MM-DD._", demais regiões vazias; arquivo mantido
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Junção | mesma entidade em dois coletores | um nó com os atributos combinados e as duas fontes | UT-01 |
| Conflito | mesmo atributo com valores diferentes | vale o primeiro coletor; conflito registrado | UT-02 |
| Repositório do serviço | `sourced_from` + `deploys` | serviço ligado ao repositório | UT-03 |
| Dependência por configuração | `config_refs` com host de datastore ou de serviço | `depends_on` inferido com a evidência | UT-04 |
| Sem casamento | host desconhecido | nenhuma aresta inventada | UT-04 |
| Determinismo | mesmos snapshots | `graph.json` idêntico | UT-05, CT-01 |
| Atlas completo | snapshots de GitHub, Argo CD e um fato `generic` de banco | grafo com repositório → deployment → serviço → banco e as páginas | IT-01 |
| Texto do time | nota fora das regiões | preservada depois de um novo build | UT-06, IT-02 |
| Entidade removida | serviço some do scan | página mantida com "Não visto desde" | IT-03 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — comando novo.

### 7.2 Testes Unitários
- **UT-01** — Dado a mesma entidade em dois snapshots, quando `merge_snapshots` roda, então há um nó só com os atributos dos dois e as duas fontes.
- **UT-02** — Dado o mesmo atributo com valores diferentes, quando os snapshots são juntados, então vale o do primeiro coletor e o conflito é registrado.
- **UT-03** — Dado um deployment com `sourced_from` e `deploys`, quando `infer_relations` roda, então o serviço ganha a ligação com o repositório.
- **UT-04** — Dado `config_refs` com o host de um datastore, o nome de outro serviço e um host desconhecido, quando as relações são inferidas, então surgem dois `depends_on` inferidos com a evidência e nada para o host desconhecido.
- **UT-05** — Dado os mesmos snapshots em ordens diferentes, quando o grafo é gerado, então o `graph.json` é idêntico.
- **UT-06** — Dado uma página com texto do time fora das regiões, quando é regenerada, então só as regiões mudam.

### 7.3 Testes de Integração
- **IT-01** — `scan` pela CLI com coletores falsos que imprimem as fixtures de GitHub (SPEC-0034), Argo CD (SPEC-0035) e um fato `generic` de banco gera o grafo com a cadeia repositório → deployment → serviço → banco e as páginas `ATLAS.md`, `services/<id>.md` e `platform/<categoria>.md`.
- **IT-02** — Uma nota escrita em `services/<id>.md` continua igual depois de um novo `scan`.
- **IT-03** — Quando um serviço some dos snapshots, a página dele fica, com "Não visto desde" e as notas do time.

### 7.4 Testes de Contrato
- **CT-01** — O `graph.json` gerado das fixtures segue o formato de `references/graph.md` (chaves, tipos, ordenação), contrato consumido pela SPEC-0038 e pela SPEC-0039.

### 7.5 Testes E2E
- N/A — comando usado pelo agente; a jornada é provada pela SPEC-0038.

### 7.6 Outros
- Medição de desempenho da seção 5 na revisão.

**Dublês e dados de teste:** fixtures de snapshots e coletores falsos que imprimem as saídas das SPEC-0034 e SPEC-0035.

**Ambiente de execução:** local e CI, sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto.
- **Dados/schema:** `graph.json` versão 1.
- **Compatibilidade:** campo `version` permite evoluir o formato.
- **Observabilidade:** resumo do `build`.
- **Rollback:** reverter o PR; páginas e grafo são versionados no git do atlas.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Junção e inferência**
- [x] Red: UT-01, UT-02, UT-03, UT-04, UT-05, CT-01 com a tag `SPEC-0036:<ID>`, falhando pelo motivo certo
- [x] Green: `merge_snapshots`, `infer_relations`, `render_graph` e `references/graph.md`
- [x] Refactor mantendo tudo verde

**Fase 2: Páginas**
- [x] Red: UT-06, IT-02, IT-03 com a tag `SPEC-0036:<ID>`, falhando pelo motivo certo
- [x] Green: `render_pages` com regiões `atlas:` e esqueletos em `assets/pages/`
- [x] Refactor mantendo tudo verde

**Fase 3: Comando build**
- [x] Red: IT-01 com a tag `SPEC-0036:<ID>`, falhando pelo motivo certo
- [x] Green: `build` e chamada no fim do `scan`; `SKILL.md` e `references/atlas-layout.md`
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] `ATLAS_VERSION` e seção no `skills/org-atlas/CHANGELOG.md` (ADR-0010)

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy via pipeline (G6) — N/A: skill distribuída por cópia (como a second-brain)
- [x] Relatório de Entrega, README e `skills/org-atlas/CHANGELOG.md` (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 81b467c (árvore suja) | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests && python3 -m unittest discover -s skills/org-atlas/tests` exit 1 (red: FAILED (failures=11, errors=17)); nota: red da org-atlas conferido em worktree limpa em ef6af55: FAILED (failures=11, errors=17), só testes da SPEC-0036; se a cadeia parar antes, é o SPEC-0004:IT-10 (tempo, sob carga) — ef6af55 | 2026-11-02 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 4f98aa9 | 2026-11-02 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 4f98aa9 | 2026-11-02 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer (rodada 2, 4f98aa9): APPROVED — M1 corrigido (casos do Mac reproduzidos, nenhuma nota perdida em ataques à regra de dono); menores: reivindicação fraca ou duplicada pode tomar a página de um serviço ativo quando uma pessoa edita o marcador — 4f98aa9 | 2026-11-02 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK); nota: CI do PR #20 em c370bfa verde (run 41434381652 Python 3.9/3.15; run 41435015546 sdd/pr-check) — c370bfa | 2026-11-02 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-02 |
| G6 Deploy | N/A | skill distribuída por cópia, sem deploy — mesmo critério da SPEC-0017 | 2026-11-02 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 34e7fd6 | 2026-11-02 |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->
`atlas.py build`, que roda no fim de cada `scan` e pode ser chamado sozinho (`build [--json]`): junta os snapshots de todos os coletores num grafo único e determinístico (`graph.json` v1, documentado em `references/graph.md`), infere as ligações que nenhum coletor declara — serviço → repositório pelo deployment, e `depends_on` pelo host das `config_refs` contra datastores, filas, tópicos, buckets e outros serviços — e gera as páginas `ATLAS.md`, `services/<id>.md` e `platform/<categoria>.md`, reescrevendo só as regiões `atlas:` e preservando o texto do time.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- Funções puras `merge_snapshots` → `infer_relations` → `render_graph` → `render_pages` no `atlas.py`, com a gravação no fim; `scan --json` continua um objeto só, com o relatório do build em `build`.
- **Decisões do Architect na execução:** snapshots por id de coletor com a ordem da configuração (o primeiro vence conflitos); fontes = ids de coletor; aresta inferida serviço → repositório do tipo `sourced_from`; casamento de host por igualdade exata do texto depois do primeiro `=`; `graph.json` na raiz do atlas e não regravado quando só `built_at` mudaria.
- **Revisão G4 (2 rodadas):** a 1ª achou que os nomes dos arquivos das páginas de serviço não eram estáveis nem seguros contra colisão — no Mac (sem diferença de caixa) `service:payments` sobrescrevia a página de `service:Payments` e apagava a nota do time, e o arquivo de um serviço que sumia passava para outro. Correção (testes 67506b2, código 4f98aa9): cada página pertence ao serviço da sua linha `- Chave:`, colisão comparada com `casefold()`, ids longos truncados com hash, nomes reservados do Windows com sufixo e erro do build dentro do `scan --json`.
- `ATLAS_VERSION` 2026.11.1 com a seção do CHANGELOG (inclui as entradas das SPEC-0034/0035); `SKILL.md` com `build` e os links para `graph.md` e os guias dos coletores; `references/graph.md` e `atlas-layout.md`.
- **Menores aceitos:** uma página escrita à mão com a linha de introdução de outro serviço, ou um `- Chave:` editado por uma pessoa, pode tomar a página de um serviço ativo (nenhum texto se perde; reversível à mão); `reads` declarado e `depends_on` inferido para o mesmo alvo aparecem os dois; regiões desconhecidas de um serviço que sumiu são esvaziadas (a spec permite).

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A — `type: feature`.

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Mesma entidade em dois coletores vira um nó com os atributos e as duas fontes; seen_at do `_scan.json` | PASS | `test_build.py::MergeSnapshotsTest` — CI do PR #20 em c370bfa (run 41434381652, Python 3.9 e 3.15) e suíte local no G5 (c370bfa) |
| UT-02 | Conflito: vale o primeiro coletor da configuração e o conflito é registrado | PASS | `ConflictTest` — CI do PR #20 em c370bfa (run 41434381652, Python 3.9 e 3.15) e suíte local no G5 (c370bfa) |
| UT-03 | Deployment com `sourced_from` e `deploys` liga o serviço ao repositório (`sourced_from` inferido) | PASS | `RepositoryOfServiceTest` — CI do PR #20 em c370bfa (run 41434381652, Python 3.9 e 3.15) e suíte local no G5 (c370bfa) |
| UT-04 | `config_refs` com host de datastore e nome de serviço geram `depends_on` com evidência; host desconhecido não gera nada | PASS | `ConfigRefsTest` — CI do PR #20 em c370bfa (run 41434381652, Python 3.9 e 3.15) e suíte local no G5 (c370bfa) |
| UT-05 | Mesmos snapshots em ordens diferentes dão `graph.json` idêntico | PASS | `DeterminismTest` — CI do PR #20 em c370bfa (run 41434381652, Python 3.9 e 3.15) e suíte local no G5 (c370bfa) |
| UT-06 | Regenerar muda só as regiões; páginas novas com título, regiões e notas | PASS | `RenderPagesTest` — CI do PR #20 em c370bfa (run 41434381652, Python 3.9 e 3.15) e suíte local no G5 (c370bfa) |
| IT-01 | `scan` monta repositório → deployment → serviço → banco e as páginas; `build` sozinho, `--json`, snapshot ilegível, ids longos, nomes reservados, erro do build no `scan --json` | PASS | `AtlasBuildTest`, `PageNamesTest` — CI do PR #20 em c370bfa (run 41434381652, Python 3.9 e 3.15) e suíte local no G5 (c370bfa) |
| IT-02 | Nota do time sobrevive a um novo `scan`; nada é escrito fora das páginas e do `graph.json`; gêmeo só de caixa não apaga a nota | PASS | `TeamTextTest`, `PageNamesTest` — CI do PR #20 em c370bfa (run 41434381652, Python 3.9 e 3.15) e suíte local no G5 (c370bfa) |
| IT-03 | Serviço que some mantém a página com "Não visto desde" e as notas; o arquivo nunca passa a outro serviço | PASS | `RemovedEntityTest`, `PageNamesTest` — CI do PR #20 em c370bfa (run 41434381652, Python 3.9 e 3.15) e suíte local no G5 (c370bfa) |
| CT-01 | `graph.json` segue `references/graph.md` e é idêntico depois de `build` e de novo `scan` | PASS | `GraphContractTest` — CI do PR #20 em c370bfa (run 41434381652, Python 3.9 e 3.15) e suíte local no G5 (c370bfa) |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5) — CI do PR #20 em c370bfa
- [x] Review independente sem achados blocker/major (G4) — 2ª rodada
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — 500 serviços e 5.000 relações em 0,37 s (frio) e 0,32 s (quente) pela CLI, meta 5 s; snapshot ilegível vira aviso (IT-01); escrita só nas regiões e no `graph.json` (IT-02)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: skill distribuída por cópia
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout — linha `Grafo: …` e relatório `build` no `scan --json`; rollback por revert
- [x] Documentação raiz e CHANGELOG atualizados (G7) — README, `SKILL.md`, `references/graph.md`, `atlas-layout.md` e `skills/org-atlas/CHANGELOG.md` 2026.11.1
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: `living_docs` não habilitado neste repositório
- [x] Pendências registradas como novas specs (ou nenhuma) — SPEC-0047

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->
N/A — skill distribuída por cópia; versão 2026.11.1 na branch `sdd/SPEC-0029`, PR #20.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
- SPEC-0047 — ids de repositório sem diferença de caixa entre coletores, que afeta o cruzamento `sourced_from` deste `build`.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0036`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
