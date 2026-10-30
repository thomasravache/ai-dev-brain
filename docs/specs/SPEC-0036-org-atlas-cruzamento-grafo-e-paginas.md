---
id: SPEC-0036
title: "org-atlas: cruzamento de fontes, grafo e páginas geradas"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0033]
consumes_contract: []
contract_version: 1
touches: [skills/org-atlas/SKILL.md, skills/org-atlas/scripts/atlas.py, skills/org-atlas/references/atlas-layout.md, skills/org-atlas/references/graph.md, skills/org-atlas/assets/pages/**, skills/org-atlas/tests/test_build.py, skills/org-atlas/tests/fixtures/build/**, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0011]
external: []
size: M
approved_by:
approved_at:
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

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 81b467c (árvore suja) | 2026-10-30 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0036`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
