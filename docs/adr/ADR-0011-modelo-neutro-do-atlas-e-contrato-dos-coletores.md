---
id: ADR-0011
title: Modelo neutro do atlas e contrato dos coletores
status: accepted
origin: decision
date: 2026-10-30
pillars: [arquitetura]
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0033
---

# ADR-0011 — Modelo neutro do atlas e contrato dos coletores

## Contexto e Problema
A `org-atlas` (SPEC-0029) precisa juntar informação de provedores diferentes (GitHub, GitLab, Argo CD, Flux, nuvens, bancos) num atlas só, sem conhecer nenhum deles no código (ADR-0010). Precisamos de um formato único que qualquer coletor, em qualquer linguagem, consiga produzir, e que o `atlas.py` consiga validar, comparar entre scans e cruzar.

## Direcionadores da Decisão
- Um coletor novo não pode exigir mudança no `atlas.py`.
- O `atlas.py` lê o formato só com a biblioteca padrão.
- O diff entre scans precisa ser estável: o mesmo estado gera o mesmo arquivo.
- O formato não pode ter lugar para valor de segredo nem dado de negócio.

## Opções Consideradas
- **A — JSON próprio na saída padrão do coletor**, com tipos de entidade e de relação fechados e versionados.
- **B — Coletores como módulos Python importados pelo `atlas.py`.**
- **C — Formato do catálogo do Backstage** (`catalog-info.yaml`: Component, API, Resource, System).

## Resultado da Decisão
**Opção escolhida:** A, porque qualquer linguagem gera JSON, o `atlas.py` lê com `json` da biblioteca padrão e o contrato fica independente de ferramenta. Os tipos foram escolhidos para mapear depois para o Backstage (`service` ≈ Component, `datastore`/`queue` ≈ Resource), sem depender dele.

**Regras (verificáveis):**
- O coletor imprime na saída padrão **um** objeto JSON com `contract: "org-atlas/collector@1"`, `collector`, `category`, `collected_at` (ISO 8601 UTC), `entities`, `relations` e, opcional, `signals`.
- **Categorias:** `code`, `ci`, `delivery`, `runtime`, `data`, `messaging`, `observability`, `tracker`, `docs`, `secrets`.
- **Entidade:** `{kind, id, name, attrs, source}`. `kind` ∈ `repository`, `service`, `environment`, `deployment`, `cluster`, `datastore`, `queue`, `topic`, `bucket`, `secret-ref`, `pipeline`, `team`. A chave da entidade é `kind:id`, estável entre scans. `attrs` só tem valores escalares ou listas de escalares.
- **Relação:** `{from, to, type, source}`, com `from`/`to` no formato `kind:id` e `type` ∈ `builds` (pipeline → repository), `sourced_from` (deployment → repository), `deploys` (deployment → service), `runs_in` (deployment → environment ou cluster), `reads`/`writes` (service → datastore ou bucket), `publishes`/`consumes` (service → queue ou topic), `depends_on` (service → qualquer entidade, quando a direção não é conhecida) e `owns` (team → repository ou service). Relação inferida pelo cruzamento (SPEC-0036), e não declarada por um coletor, leva `inferred: true`.
- **Sinal (`signals`):** evidência para a curadoria (ADR-0012), por exemplo `{type: "pr-titles", repository, sample, total, pattern_counts}`. Nunca o texto inteiro de PRs ou commits, só contagens e uma amostra limitada.
- **Proibido no contrato:** chaves de `attrs` com nome que indique segredo (`password`, `secret`, `token`, `key`, `credential`, `private`) e qualquer valor que pareça segredo; o `scan` rejeita ou mascara (SPEC-0033). Um `secret-ref` guarda só o nome e onde o segredo vive, nunca o valor.
- **Snapshots:** o `scan` grava `snapshots/<collector>.json` normalizado (entidades e relações ordenadas pela chave, JSON com indentação fixa), e o diff compara por chave.
- **Versão:** mudança só aditiva mantém `@1`; mudança que quebra cria `org-atlas/collector@2`, e o `atlas.py` aceita a versão atual e a anterior.

### Consequências
- **Boa**, porque coletores novos entram sem tocar no `atlas.py`, o diff fica legível no PR do atlas e o formato não tem campo para guardar segredo.
- **Ruim**, porque tipos fechados podem não cobrir um caso novo; ampliar a lista exige mudança do contrato (aditiva).

### Confirmação (G3)
Testes de contrato da SPEC-0033 (CT): o validador do `scan` aceita a saída de cada coletor entregue (SPEC-0034, SPEC-0035) e rejeita entidade com tipo fora da lista, `attrs` com chave proibida e relação apontando para chave inexistente.

## Prós e Contras das Opções
| Critério (peso) | A — JSON próprio | B — módulos Python | C — catálogo do Backstage |
|---|---|---|---|
| Coletor em qualquer linguagem (3) | sim | não | sim |
| Leitura só com a biblioteca padrão (3) | sim | sim | não (YAML com vários documentos) |
| Sem acoplar a uma ferramenta (2) | sim | sim | não |
| Diff estável entre scans (2) | sim | depende | depende |

## Mais Informações
ADR-0010 (fronteiras da `org-atlas`), ADR-0012 (curadoria). Fontes: formato do catálogo do Backstage, conhecido mas não verificado nesta data; a decisão não depende dele.
