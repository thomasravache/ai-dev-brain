# O grafo do atlas — `graph.json` (versão 1)

O `atlas.py build` (que também roda sozinho no fim de todo `scan`) junta os snapshots de todos os coletores declarados em `collectors` num grafo único, infere as ligações que nenhum coletor declara e grava `<atlas>/graph.json`. O `graph.json` é o contrato que o pacote de contexto (SPEC-0038) e o `lint` (SPEC-0039) leem; as páginas `ATLAS.md`, `services/<id>.md` e `platform/<categoria>.md` são geradas a partir dele (SPEC-0036).

Não edite o `graph.json` à mão: ele é refeito a cada `build`, a partir de `snapshots/`.

## Formato

```json
{
  "version": 1,
  "organization": "Acme",
  "built_at": "2026-11-02",
  "nodes": [
    {"key": "datastore:payments-db", "kind": "datastore", "name": "payments-db",
     "attrs": {"engine": "postgres", "host": "db-prod.interno"},
     "sources": ["db-facts"], "seen_at": "2026-11-02", "conflicts": []}
  ],
  "edges": [
    {"from": "service:api", "to": "datastore:payments-db", "type": "depends_on",
     "sources": ["argocd", "db-facts"], "inferred": true, "evidence": "DB_URL=db-prod.interno"}
  ]
}
```

### Topo

| Chave | Tipo | Conteúdo |
|---|---|---|
| `version` | inteiro | versão do formato: `1`. Uma mudança incompatível incrementa a versão |
| `organization` | texto | `organization` do `atlas-config.yml` |
| `built_at` | texto `AAAA-MM-DD` | data (UTC) do último `build` que mudou o grafo. Com os mesmos snapshots o arquivo não é regravado (fica idêntico, byte a byte) |
| `nodes` | lista | as entidades, ordenadas por `key` |
| `edges` | lista | as relações, ordenadas por (`from`, `type`, `to`); cada trinca aparece uma vez só |

### Nó (`nodes[]`)

| Chave | Tipo | Conteúdo |
|---|---|---|
| `key` | texto | `kind:id`, a chave da entidade (única no grafo) |
| `kind` | texto | um dos kinds do contrato dos coletores (`references/collector-contract.md`) |
| `name` | texto | nome da entidade, do primeiro coletor (na ordem de `collectors`) que a declarou |
| `attrs` | objeto | atributos combinados de todos os coletores (chaves ordenadas); escalares ou listas de escalares, já mascarados pelo `scan` |
| `sources` | lista de textos | ids dos coletores que declararam a entidade, na ordem de `collectors` |
| `seen_at` | texto `AAAA-MM-DD` | o `seen_at` mais recente (em `snapshots/_scan.json`) entre os coletores de `sources`; sem `_scan.json`, a data de `collected_at` do snapshot |
| `conflicts` | lista | um item `{"attr": <nome>, "values": {<id do coletor>: <valor>}}` por atributo com valores diferentes entre coletores, ordenados por `attr`; `values` traz o valor de cada coletor que tem o atributo, na ordem de `collectors`. Vazia quando não há conflito |

### Aresta (`edges[]`)

| Chave | Tipo | Conteúdo |
|---|---|---|
| `from` | texto | `kind:id` de origem |
| `to` | texto | `kind:id` de destino (pode não existir em `nodes`: referência pendente é aviso do `lint`, SPEC-0039) |
| `type` | texto | um dos tipos de relação do contrato (`builds`, `sourced_from`, `deploys`, `runs_in`, `reads`, `writes`, `publishes`, `consumes`, `depends_on`, `owns`) |
| `sources` | lista de textos | coletores que declararam a relação; numa aresta inferida, os coletores dos fatos usados na inferência |
| `inferred` | booleano | `false` para relação declarada por um coletor; `true` para relação inferida pelo `build` |
| `evidence` | texto | só nas arestas inferidas: o fato que gerou a aresta (abaixo) |

## Junção

- **Entidades:** a mesma chave `kind:id` em vários coletores vira **um** nó, com os `attrs` de todos e todas as fontes.
- **Conflito:** o mesmo atributo com valores diferentes — vale o valor do **primeiro coletor na ordem de `collectors`** do `atlas-config.yml` (não a ordem alfabética), e o conflito vai para `conflicts`. Valores iguais (inclusive listas iguais) não são conflito.
- **Relações:** a mesma trinca (`from`, `type`, `to`) em vários coletores vira **uma** aresta com todas as fontes.
- Entram os snapshots dos coletores declarados em `collectors` (habilitados ou não). Um coletor que nunca rodou (sem `snapshots/<id>.json`) é ignorado; um snapshot ilegível ou fora do contrato gera `aviso: snapshots/<id>.json ilegível ou fora do contrato — ignorado no build` e o `build` segue com os outros.

## Inferência

Só **igualdade** de texto, nunca semelhança: um host desconhecido ou só parecido não gera aresta nem nó. Toda aresta inferida tem `inferred: true` e `evidence`.

1. **Repositório do serviço** — um `deployment` com `sourced_from` → `repository:R` e `deploys` → `service:S` gera a aresta `service:S` **`sourced_from`** `repository:R`. `evidence` = a chave do deployment (`deployment:api-prod`).
2. **Dependência por configuração** — cada item `CHAVE=host` de `attrs.config_refs` de um deployment: o host é o texto depois do primeiro `=`. Se ele é igual ao `attrs.host` ou ao `name` de um `datastore`, `queue`, `topic` ou `bucket`, o serviço do deployment (`deploys`) ganha `depends_on` para essa entidade. `evidence` = o item (`DB_URL=db-prod.interno`).
3. **Dependência entre serviços** — o mesmo host igual ao `name` de **outro** `service` gera `depends_on` entre os serviços. O próprio serviço não conta.

Uma aresta inferida igual a uma declarada (mesma trinca) não é adicionada: a declarada fica como está. A mesma aresta inferida por vários fatos (dois deployments do mesmo serviço, por exemplo) aparece uma vez, com a menor `evidence` em ordem alfabética e as fontes somadas. A direção (leitura ou escrita) de uma dependência nunca é inferida.

## Páginas geradas

| Página | Regiões |
|---|---|
| `ATLAS.md` | `summary` (contagens por kind, links para `platform/`), `services` (lista com links), `scans` (`seen_at` e estado por coletor, de `snapshots/_scan.json`) |
| `services/<id>.md` | `summary`, `repository`, `deployments` (por ambiente), `depends-on`, `used-by`, `owners`, `pipelines`, `sources` |
| `platform/<categoria>.md` | `entities` |

- Os donos e os pipelines de um serviço chegam pelo repositório dele: `team` → `owns` → repositório (ou o próprio serviço) e `pipeline` → `builds` → repositório (ou o serviço).
- `depends-on` e `used-by` mostram `depends_on`, `reads`, `writes`, `publishes` e `consumes`, com a evidência das inferidas.
- Cada kind (menos `service`) tem a sua categoria em `platform/`: `repository` e `team` → `code`; `pipeline` → `ci`; `deployment` e `environment` → `delivery`; `cluster` → `runtime`; `datastore` e `bucket` → `data`; `queue` e `topic` → `messaging`; `secret-ref` → `secrets`.
- **Nome do arquivo de um serviço** (estável e sem colisão):
  - Uma página que já existe continua do serviço dela: o da linha `- Chave: \`service:<id>\`` da região `summary` ou, na falta dela (página de serviço que sumiu), o da linha `Serviço \`service:<id>\`` do esqueleto. O nome do arquivo nunca muda depois de criado.
  - Serviço novo: o id com tudo o que não é letra, dígito, `.`, `_` ou `-` trocado por `-`. Mais de 80 caracteres = cortado em 80 e com `-<10 primeiros caracteres do SHA-1 do id>` no fim. Nome reservado do Windows (`con`, `prn`, `aux`, `nul`, `com1`–`com9`, `lpt1`–`lpt9`, sem diferença de caixa, com ou sem extensão) ganha `_` depois da primeira parte (`con_.md`, `con_.txt.md`).
  - Se o nome colide, sem diferenciar maiúsculas, com outro serviço ou com qualquer arquivo de `services/` (inclusive o de um serviço que sumiu), ganha `-2`, `-3`…, nessa ordem pelos ids em ordem alfabética. O arquivo de um serviço que sumiu nunca é dado a outro.
- Página nova vem de `assets/pages/` (`service.md`, `platform.md`, `ATLAS.md`), com título, regiões e `## Notas` para o time. Página existente: só o conteúdo entre `<!-- atlas:begin <nome> -->` e `<!-- atlas:end <nome> -->` muda; regiões que o `build` não conhece (como `about`) e todo o texto fora delas ficam como estão.
- **Serviço que sumiu** do grafo: a página fica, a região `summary` vira `_Não visto desde AAAA-MM-DD._` (o `seen_at` do serviço no `graph.json` anterior; a data se mantém nos builds seguintes) e as outras regiões ficam vazias. Uma página `platform/` sem entidades fica, com `_(nenhum)_`.

## Saída do comando

```text
Grafo: N nós, M arestas (I inferidas), C conflitos; P páginas atualizadas
```

`P` conta as páginas gravadas (novas ou com alguma região diferente). `build --json` imprime um objeto `{"version", "ok", "nodes", "edges", "inferred", "conflicts", "pages", "warnings"}`; no `scan --json` o mesmo relatório vem na chave `build`. Se o `build` falhar dentro do `scan` (página ilegível, disco sem permissão), o `scan --json` continua imprimindo um objeto só, com `build: {"ok": false, "error": "..."}`, e sai com 1; no modo texto a mensagem vai para o stderr como `erro no build: ...`.
