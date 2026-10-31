# Contrato dos coletores — `org-atlas/collector@1`

Todo coletor do atlas (os da skill, SPEC-0034 e SPEC-0035, ou um escrito pela organização, em qualquer linguagem) segue este contrato (ADR-0011). O `atlas.py scan` roda o coletor, valida a saída contra ele, mascara o que parecer segredo (`references/redaction.md`), grava um snapshot normalizado e mostra o que mudou desde o scan anterior. Um coletor novo nunca exige mudança no `atlas.py`.

## Declarar um coletor — `collectors` no `atlas-config.yml`

```yaml
collectors:
  - id: github                     # ^[a-z0-9-]+$, único; nome do snapshot: snapshots/github.json
    category: code                 # uma das categorias abaixo
    command: ["python3", "{skill}/assets/collectors/github.py", "--org", "acme"]
    timeout: 300                   # segundos (inteiro ≥ 1), padrão 300
    enabled: true                  # padrão true; false = o scan não roda
redaction: {extra_patterns: []}    # regex extras de mascaramento (references/redaction.md)
```

- `command` é uma **lista**: o executável e os argumentos. Roda **sem shell** (nada de `|`, `>`, `$VAR`, `~`), numa pasta temporária, com as variáveis de ambiente da máquina (as credenciais ficam na configuração local, só pelo nome).
- Nenhum argumento pode ter caminho absoluto (`/x`, `~`, `C:\`, `C:/`, `\\servidor`, nem `--opcao=/x` ou `-o/x` colado): o `atlas-config.yml` vai junto com o atlas e é usado em várias máquinas. Use os marcadores, trocados em cada argumento antes de rodar:
  - `{skill}` — a pasta da skill `org-atlas` nesta máquina;
  - `{atlas}` — a pasta do atlas nesta máquina.
- Configuração inválida faz o `scan` sair com 2 sem rodar nada: `id` fora do formato ou repetido, `category` desconhecida, `command` que não é lista não vazia, `timeout` que não é inteiro ≥ 1, `enabled` que não é `true`/`false`, `redaction.extra_patterns` com regex inválida, ou caminho absoluto em `command`, com a mensagem:

  ```text
  command não pode ter caminho absoluto — use {skill} ou {atlas}
  ```

## A saída do coletor

O coletor imprime na **saída padrão um único objeto JSON** e sai com 0. O que ele escreve no stderr é diagnóstico: o `scan` mostra só as últimas 20 linhas, já mascaradas, e só quando o coletor falha.

| Campo | Obrigatório | Conteúdo |
|---|---|---|
| `contract` | sim | `"org-atlas/collector@1"` |
| `collector` | sim | id do coletor (texto não vazio) |
| `category` | sim | `code`, `ci`, `delivery`, `runtime`, `data`, `messaging`, `observability`, `tracker`, `docs` ou `secrets` |
| `collected_at` | sim | ISO 8601 UTC, por exemplo `2026-10-30T12:00:00Z` |
| `entities` | sim | lista de entidades (pode ser vazia) |
| `relations` | sim | lista de relações (pode ser vazia) |
| `signals` | não | lista de sinais para a curadoria (ADR-0012) |

**Entidade** — `{kind, id, name, attrs, source}`:

- `kind`: `repository`, `service`, `environment`, `deployment`, `cluster`, `datastore`, `queue`, `topic`, `bucket`, `secret-ref`, `pipeline` ou `team`.
- A **chave** da entidade é `kind:id` (por exemplo `repository:acme/api`): única na saída e estável entre scans — é por ela que o diff compara.
- `attrs`: objeto só com valores escalares (texto, número, booleano, `null`) ou listas de escalares. Nada de objeto aninhado.
- Um `secret-ref` guarda só o nome e onde o segredo vive (`store`, `path`), **nunca o valor**.

**Relação** — `{from, to, type, source}` e, opcional, `inferred` (`true` só nas relações inferidas pelo cruzamento, SPEC-0036):

- `from` e `to` no formato `kind:id`, com um `kind` da lista acima. A relação pode apontar para uma entidade de **outro** coletor (por exemplo um deployment do Argo CD → `repository:acme/api` do GitHub): isso é válido; referência que não existe em nenhum snapshot é aviso do `lint` (SPEC-0039), não erro do `scan`.
- `type`: `builds` (pipeline → repository), `sourced_from` (deployment → repository), `deploys` (deployment → service), `runs_in` (deployment → environment ou cluster), `reads`/`writes` (service → datastore ou bucket), `publishes`/`consumes` (service → queue ou topic), `depends_on` (service → qualquer entidade, quando a direção não é conhecida) e `owns` (team → repository ou service).

**Sinal** — objeto com `type` e só os campos `repository`, `total`, `pattern_counts`, `sample`, `counts` e `present` (por exemplo `{type: "pr-titles", repository, total, pattern_counts, sample}`): só contagens e uma amostra limitada, **nunca** o texto inteiro de PRs ou commits.

## O que o contrato proíbe

- **Campo fora do contrato:** só os campos listados acima chegam ao snapshot — na saída (`contract`, `collector`, `category`, `collected_at`, `entities`, `relations`, `signals`), na entidade (`kind`, `id`, `name`, `attrs`, `source`), na relação (`from`, `to`, `type`, `source`, `inferred`) e no sinal (`type`, `repository`, `total`, `pattern_counts`, `sample`, `counts`, `present`). Qualquer outro campo é **descartado** e reportado pelo lugar e pelo nome (`saída: campo debug descartado (fora do contrato)`, `repository:acme/api: campo password descartado (fora do contrato)`, `relations[0]: campo note descartado (fora do contrato)`), sem mostrar o valor e **sem falhar** o coletor.
- **Chave que indica segredo**, em `attrs` e nos campos de um sinal: nome que contém `password`, `passwd`, `secret`, `token` ou `credential`, que tem `key`/`keys`, `private` ou `pwd` como parte (`api_key`, `privateKey`, `private`, `db_pwd`) ou que termina em `key` (`apikey`). A chave é **descartada** e reportada (`repository:acme/api: attrs.password descartada (chave proibida)`), sem mostrar o valor e **sem falhar** o coletor.
- **Valor que parece segredo** (token, chave privada PEM ou PGP, JWT, URL com senha e os `extra_patterns`), também quando aparece como **chave** de um objeto (`attrs`, `pattern_counts`): vira `[REDACTED]` antes de gravar; o relatório mostra só a contagem (`references/redaction.md`). Os nomes reportados como descartados passam pela mesma máscara antes de aparecer na tela.

## Violações

**Tipos:** um campo do contrato com o tipo errado é violação (o coletor falha e nada é gravado), porque um objeto aninhado nele poderia carregar um segredo. Na saída, `contract`, `category` e `collected_at` são texto. Na entidade, `kind`, `id`, `name` e `source` são texto. Na relação, `from`, `to`, `type` e `source` são texto e `inferred`, booleano. No sinal, `type` e `repository` são texto, `sample` é lista de textos, `total` é número, `pattern_counts` e `counts` são objetos planos de números (booleano não conta como número) e `present` é objeto plano de booleanos. Um texto nesses objetos é violação: só contagens e presença chegam ao snapshot. A mensagem de tipo nunca repete o valor recebido.

Uma saída com violação não é gravada: o `scan` mostra `FALHA <id> — saída fora do contrato org-atlas/collector@1 (N violação(ões))` e uma linha por violação, mantém o snapshot anterior e não avança o `seen_at`. As mensagens:

| Mensagem | Quando |
|---|---|
| `a saída não é um objeto JSON` | o JSON é uma lista, texto ou número |
| `faltam campos: <campo>[, <campo>...]` | falta campo obrigatório (também `entities[<i>]: faltam campos: ...` e `relations[<i>]: faltam campos: ...`) |
| `contract não suportado: <valor>` | `contract` diferente de `org-atlas/collector@1` |
| `collector precisa ser um texto não vazio` | `collector` vazio ou que não é texto |
| `category desconhecida: <valor>` | `category` fora da lista |
| `collected_at fora do formato ISO 8601 UTC (AAAA-MM-DDTHH:MM:SSZ): <valor>` | data sem formato ou fora de UTC |
| `entities precisa ser uma lista`, `relations precisa ser uma lista`, `signals precisa ser uma lista` | campo com outro tipo |
| `entities[<i>]: kind desconhecido: <valor>` | `kind` fora da lista |
| `entities[<i>]: chave repetida: <kind:id>` | duas entidades com a mesma chave |
| `entities[<i>]: attrs precisa ser um objeto` | `attrs` que não é objeto |
| `entities[<i>]: attrs.<chave> não é escalar` | valor de `attrs` que é objeto ou lista com objeto |
| `relations[<i>]: type desconhecido: <valor>` | `type` fora da lista |
| `relations[<i>]: from fora do formato kind:id: <valor>` | `from` sem `kind:` ou com `kind` fora da lista |
| `relations[<i>]: to fora do formato kind:id: <valor>` | `to` sem `kind:` ou com `kind` fora da lista |
| `signals[<i>]: precisa ser um objeto com type` | sinal sem `type` (ou com `type` que não é texto) |
| `<lugar>: <campo> precisa ser texto` | `contract`, `category` ou `collected_at` da saída (lugar `saída`), `kind`, `id`, `name` ou `source` de `entities[<i>]`, `from`, `to`, `type` ou `source` de `relations[<i>]`, ou `repository` de `signals[<i>]`, com outro tipo (objeto, lista, número) |
| `relations[<i>]: inferred precisa ser true ou false` | `inferred` que não é booleano |
| `signals[<i>]: sample precisa ser uma lista de textos` | `sample` que não é lista ou tem item que não é texto |
| `signals[<i>]: total precisa ser um número` | `total` que não é número |
| `signals[<i>]: pattern_counts precisa ser um objeto de números` | `pattern_counts` aninhado ou com valor que não é número |
| `signals[<i>]: counts precisa ser um objeto de números` | `counts` aninhado ou com valor que não é número |
| `signals[<i>]: present precisa ser um objeto de booleanos` | `present` aninhado ou com valor que não é `true`/`false` |

Falhas que não são do contrato também aparecem como `FALHA <id> — <motivo>`: `saiu com <código>` (com as últimas 20 linhas do stderr, mascaradas), `tempo esgotado (<timeout> s); processo encerrado`, `JSON inválido na saída: ...`, `executável não encontrado: <executável>`.

## O `scan`

```text
atlas.py scan [--only id,...] [--json]
```

Para cada coletor habilitado (ou só os de `--only`): executa, valida, mascara, normaliza e grava `snapshots/<id>.json`, e atualiza `snapshots/_scan.json`:

```json
{"github": {"entities": 3, "relations": 2, "seen_at": "2026-10-30", "status": "ok"}}
```

- `seen_at` é a data (UTC) do último scan **bem-sucedido** do coletor: é o `seen_at` de todos os fatos dele. Coletor com falha fica com `status: "failed"`, o `seen_at` e as contagens anteriores e o snapshot anterior intacto; os outros coletores seguem.
- O snapshot é normalizado: entidades ordenadas por `kind:id`, relações por `from`/`type`/`to`, chaves ordenadas, indentação de 2 espaços. O mesmo estado gera o mesmo arquivo; se só `collected_at` mudou, o arquivo não é regravado (o histórico do atlas não ganha ruído).
- Saída por coletor: `OK <id> — +A entidades, -R, ~C; +a relações, -r` (adicionadas, removidas e alteradas desde o scan anterior), `OK <id> — sem mudanças`, `N valor(es) mascarado(s)` e as chaves descartadas, ou `FALHA <id> — <motivo>`. `--json` imprime `{"version", "ok", "collectors": [...]}` com o diff completo de cada coletor.
- Exit 0 sem falha, 1 com alguma falha, 2 com configuração inválida, `--only` com id não declarado ou com coletor `enabled: false` (nada roda).
- Sem nenhum coletor habilitado, o `scan` só avisa e sai com 0, sem gravar nada (nem cria `snapshots/`).

## Versões

Mudança só aditiva mantém `org-atlas/collector@1`. Mudança que quebra cria `org-atlas/collector@2`, e o `atlas.py` passa a aceitar a versão atual e a anterior (ADR-0011).

## Exemplos

Os exemplos abaixo são os mesmos de `tests/fixtures/contract/` e passam (ou falham, com a mensagem indicada) no validador (CT-01 da SPEC-0033).

### Válidos

**Coletor de código (GitHub), com sinais** (`valid/code-github.json`):

```json
{
  "contract": "org-atlas/collector@1",
  "collector": "github",
  "category": "code",
  "collected_at": "2026-10-30T12:00:00Z",
  "entities": [
    {
      "kind": "repository",
      "id": "acme/api",
      "name": "api",
      "attrs": {
        "default_branch": "main",
        "visibility": "private",
        "archived": false,
        "topics": [
          "payments",
          "go"
        ]
      },
      "source": "github"
    },
    {
      "kind": "pipeline",
      "id": "acme/api/ci",
      "name": "ci",
      "attrs": {
        "file": ".github/workflows/ci.yml",
        "runs_last_30d": 42
      },
      "source": "github"
    },
    {
      "kind": "team",
      "id": "acme/payments",
      "name": "payments",
      "attrs": {
        "members": 6
      },
      "source": "github"
    }
  ],
  "relations": [
    {
      "from": "pipeline:acme/api/ci",
      "to": "repository:acme/api",
      "type": "builds",
      "source": "github"
    },
    {
      "from": "team:acme/payments",
      "to": "repository:acme/api",
      "type": "owns",
      "source": "github"
    }
  ],
  "signals": [
    {
      "type": "pr-titles",
      "repository": "acme/api",
      "total": 200,
      "pattern_counts": {
        "conventional": 180,
        "ticket-prefix": 12,
        "other": 8
      },
      "sample": [
        "feat(api): add refunds endpoint",
        "fix: retry on 503"
      ]
    }
  ]
}
```

**Coletor de entrega (Argo CD), com `secret-ref` só pelo nome e relação para outra entidade** (`valid/delivery-argocd.json`):

```json
{
  "contract": "org-atlas/collector@1",
  "collector": "argocd",
  "category": "delivery",
  "collected_at": "2026-10-30T12:05:00Z",
  "entities": [
    {
      "kind": "deployment",
      "id": "prod/api",
      "name": "api",
      "attrs": {
        "sync_status": "Synced",
        "revision": "a1b2c3d"
      },
      "source": "argocd"
    },
    {
      "kind": "service",
      "id": "api",
      "name": "api",
      "attrs": {
        "replicas": 3
      },
      "source": "argocd"
    },
    {
      "kind": "environment",
      "id": "prod",
      "name": "prod",
      "attrs": {},
      "source": "argocd"
    },
    {
      "kind": "cluster",
      "id": "eks-prod-1",
      "name": "eks-prod-1",
      "attrs": {
        "region": "us-east-1"
      },
      "source": "argocd"
    },
    {
      "kind": "secret-ref",
      "id": "prod/api/db-url",
      "name": "db-url",
      "attrs": {
        "store": "aws-secrets-manager",
        "path": "prod/api/db-url"
      },
      "source": "argocd"
    }
  ],
  "relations": [
    {
      "from": "deployment:prod/api",
      "to": "service:api",
      "type": "deploys",
      "source": "argocd"
    },
    {
      "from": "deployment:prod/api",
      "to": "environment:prod",
      "type": "runs_in",
      "source": "argocd"
    },
    {
      "from": "deployment:prod/api",
      "to": "cluster:eks-prod-1",
      "type": "runs_in",
      "source": "argocd"
    },
    {
      "from": "service:api",
      "to": "secret-ref:prod/api/db-url",
      "type": "depends_on",
      "source": "argocd"
    }
  ]
}
```

### Inválidos

**`attrs` com objeto aninhado** (`invalid/attrs-not-scalar.json`) — violação: `entities[0]: attrs.owner não é escalar`

```json
{
  "contract": "org-atlas/collector@1",
  "collector": "github",
  "category": "code",
  "collected_at": "2026-10-30T12:00:00Z",
  "entities": [
    {
      "kind": "repository",
      "id": "acme/api",
      "name": "api",
      "attrs": {
        "default_branch": "main",
        "owner": {
          "login": "ana"
        }
      },
      "source": "github"
    },
    {
      "kind": "pipeline",
      "id": "acme/api/ci",
      "name": "ci",
      "attrs": {},
      "source": "github"
    }
  ],
  "relations": [
    {
      "from": "pipeline:acme/api/ci",
      "to": "repository:acme/api",
      "type": "builds",
      "source": "github"
    }
  ]
}
```

**Categoria fora da lista** (`invalid/category-unknown.json`) — violação: `category desconhecida: billing`

```json
{
  "contract": "org-atlas/collector@1",
  "collector": "github",
  "category": "billing",
  "collected_at": "2026-10-30T12:00:00Z",
  "entities": [
    {
      "kind": "repository",
      "id": "acme/api",
      "name": "api",
      "attrs": {
        "default_branch": "main"
      },
      "source": "github"
    },
    {
      "kind": "pipeline",
      "id": "acme/api/ci",
      "name": "ci",
      "attrs": {},
      "source": "github"
    }
  ],
  "relations": [
    {
      "from": "pipeline:acme/api/ci",
      "to": "repository:acme/api",
      "type": "builds",
      "source": "github"
    }
  ]
}
```

**Versão do contrato que não existe** (`invalid/contract-version.json`) — violação: `contract não suportado: org-atlas/collector@9`

```json
{
  "contract": "org-atlas/collector@9",
  "collector": "github",
  "category": "code",
  "collected_at": "2026-10-30T12:00:00Z",
  "entities": [
    {
      "kind": "repository",
      "id": "acme/api",
      "name": "api",
      "attrs": {
        "default_branch": "main"
      },
      "source": "github"
    },
    {
      "kind": "pipeline",
      "id": "acme/api/ci",
      "name": "ci",
      "attrs": {},
      "source": "github"
    }
  ],
  "relations": [
    {
      "from": "pipeline:acme/api/ci",
      "to": "repository:acme/api",
      "type": "builds",
      "source": "github"
    }
  ]
}
```

**Duas entidades com a mesma chave `kind:id`** (`invalid/duplicate-key.json`) — violação: `entities[2]: chave repetida: repository:acme/api`

```json
{
  "contract": "org-atlas/collector@1",
  "collector": "github",
  "category": "code",
  "collected_at": "2026-10-30T12:00:00Z",
  "entities": [
    {
      "kind": "repository",
      "id": "acme/api",
      "name": "api",
      "attrs": {
        "default_branch": "main"
      },
      "source": "github"
    },
    {
      "kind": "pipeline",
      "id": "acme/api/ci",
      "name": "ci",
      "attrs": {},
      "source": "github"
    },
    {
      "kind": "repository",
      "id": "acme/api",
      "name": "api-copy",
      "attrs": {},
      "source": "github"
    }
  ],
  "relations": [
    {
      "from": "pipeline:acme/api/ci",
      "to": "repository:acme/api",
      "type": "builds",
      "source": "github"
    }
  ]
}
```

**`from` sem `kind:`** (`invalid/from-format.json`) — violação: `relations[0]: from fora do formato kind:id: acme/api/ci`

```json
{
  "contract": "org-atlas/collector@1",
  "collector": "github",
  "category": "code",
  "collected_at": "2026-10-30T12:00:00Z",
  "entities": [
    {
      "kind": "repository",
      "id": "acme/api",
      "name": "api",
      "attrs": {
        "default_branch": "main"
      },
      "source": "github"
    },
    {
      "kind": "pipeline",
      "id": "acme/api/ci",
      "name": "ci",
      "attrs": {},
      "source": "github"
    }
  ],
  "relations": [
    {
      "from": "acme/api/ci",
      "to": "repository:acme/api",
      "type": "builds",
      "source": "github"
    }
  ]
}
```

**`kind` fora da lista** (`invalid/kind-unknown.json`) — violação: `entities[2]: kind desconhecido: widget`

```json
{
  "contract": "org-atlas/collector@1",
  "collector": "github",
  "category": "code",
  "collected_at": "2026-10-30T12:00:00Z",
  "entities": [
    {
      "kind": "repository",
      "id": "acme/api",
      "name": "api",
      "attrs": {
        "default_branch": "main"
      },
      "source": "github"
    },
    {
      "kind": "pipeline",
      "id": "acme/api/ci",
      "name": "ci",
      "attrs": {},
      "source": "github"
    },
    {
      "kind": "widget",
      "id": "acme/w",
      "name": "w",
      "attrs": {},
      "source": "github"
    }
  ],
  "relations": [
    {
      "from": "pipeline:acme/api/ci",
      "to": "repository:acme/api",
      "type": "builds",
      "source": "github"
    }
  ]
}
```

**Sem `collected_at`** (`invalid/missing-field.json`) — violação: `faltam campos: collected_at`

```json
{
  "contract": "org-atlas/collector@1",
  "collector": "github",
  "category": "code",
  "entities": [
    {
      "kind": "repository",
      "id": "acme/api",
      "name": "api",
      "attrs": {
        "default_branch": "main"
      },
      "source": "github"
    },
    {
      "kind": "pipeline",
      "id": "acme/api/ci",
      "name": "ci",
      "attrs": {},
      "source": "github"
    }
  ],
  "relations": [
    {
      "from": "pipeline:acme/api/ci",
      "to": "repository:acme/api",
      "type": "builds",
      "source": "github"
    }
  ]
}
```

**`to` sem `kind:`** (`invalid/to-format.json`) — violação: `relations[0]: to fora do formato kind:id: acme/api`

```json
{
  "contract": "org-atlas/collector@1",
  "collector": "github",
  "category": "code",
  "collected_at": "2026-10-30T12:00:00Z",
  "entities": [
    {
      "kind": "repository",
      "id": "acme/api",
      "name": "api",
      "attrs": {
        "default_branch": "main"
      },
      "source": "github"
    },
    {
      "kind": "pipeline",
      "id": "acme/api/ci",
      "name": "ci",
      "attrs": {},
      "source": "github"
    }
  ],
  "relations": [
    {
      "from": "pipeline:acme/api/ci",
      "to": "acme/api",
      "type": "builds",
      "source": "github"
    }
  ]
}
```

**`type` de relação fora da lista** (`invalid/type-unknown.json`) — violação: `relations[0]: type desconhecido: calls`

```json
{
  "contract": "org-atlas/collector@1",
  "collector": "github",
  "category": "code",
  "collected_at": "2026-10-30T12:00:00Z",
  "entities": [
    {
      "kind": "repository",
      "id": "acme/api",
      "name": "api",
      "attrs": {
        "default_branch": "main"
      },
      "source": "github"
    },
    {
      "kind": "pipeline",
      "id": "acme/api/ci",
      "name": "ci",
      "attrs": {},
      "source": "github"
    }
  ],
  "relations": [
    {
      "from": "pipeline:acme/api/ci",
      "to": "repository:acme/api",
      "type": "calls",
      "source": "github"
    }
  ]
}
```
