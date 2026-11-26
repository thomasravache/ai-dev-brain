# Verify — foto antes do merge, comparação depois do deploy e veredito

`atlas.py verify` responde, com evidência, se uma entrega chegou e está saudável num ambiente (ADR-0024, SPEC-0090), inclusive nas dependências que o grafo liga ao serviço (contrato `verify@2`, ADR-0026, SPEC-0102). Tem duas fases, as duas **só de leitura** e feitas pelas probes (`references/probes.md`):

- **`snapshot`**, antes do merge: grava uma foto do serviço no ambiente num **arquivo da tarefa**, fora do atlas;
- **`compare`**, depois do deploy: compara o estado de agora com a foto e com a imagem esperada e dá um veredito: `passou`, `degradou` ou `inconclusivo`.

Por deployment, o `verify` olha a entrega, o runtime e os logs (`delivery`, `runtime`, `logs`). Por recurso ligado (fila, tópico, banco), olha as dependências e os sinais (`dependencies`, `signals`; veja [Dependências e sinais](#dependências-e-sinais-verify2)).

O `verify` não roda adaptador por conta própria: cada consulta passa pelo mesmo caminho do `probe` (ligadas, verbos permitidos, produção confirmada, acesso local, saída validada e mascarada, uma linha em `probes.log`). Nada é gravado no atlas, e nenhuma ação é executada no ambiente, nem rollback.

## Pré-requisitos

- As probes ligadas nesta máquina (`probes.enabled: true`), com um adaptador da capacidade `runtime` que libere `status`, `events` e `logs` (o `kubernetes` da skill serve: `references/probes/kubernetes.md`).
- O serviço com deployment no ambiente no atlas (`scan` e `build`) e o cluster dele em `access.clusters`.
- Para as dependências (opcional): um adaptador `probe@2` com as capacidades de recurso (`messaging`, `database`, `signals`, `permissions`) e o acesso local que elas declaram (`access.cloud`, `access.databases`). Sem nenhum adaptador de recurso, o `verify` fica como no `verify@1`.

## `verify snapshot`

```text
atlas.py verify snapshot --service <id> --env <ambiente> --out <arquivo>
    [--since 30m] [--resource <kind:id>]... [--max-resources 20] [--confirm-production] [--atlas X]
```

Para **cada** deployment do serviço no ambiente roda três probes: `runtime status`, `runtime events` e `runtime logs --summary` (os eventos e os logs na janela `--since`, padrão `30m`, até `24h`). Grava em `--out`:

- `images` — as imagens dos pods, como o adaptador as dá (caminho sem o host do registry, com tag e digest);
- `ready` e `desired` — réplicas prontas e desejadas, somadas pelos workloads;
- `restarts` — restarts por pod;
- `warnings` — os eventos de alerta como `<motivo>|<Kind>/<nome>`, com o nome do pod trocado pelo workload dono (`BackOff` em `api-7f9c-aaaa` ou em `api-7f9c-bbbb` é o mesmo `BackOff|Pod/api`);
- `error_signatures` — só as assinaturas de nível `error` do `--summary`, com a contagem;
- `dependencies` — o estado de cada recurso do escopo (veja [Foto `verify@2`](#foto-verify2)); `{}` sem recurso ligado ou sem adaptador de recurso;
- `not_verified` — cada verificação que a foto não conseguiu sustentar, com o motivo (probe recusada, com erro, que falhou ou que voltou cortada; logs cortados sem nenhuma linha = "nenhum pod respondeu"). Nos recursos, o item traz também `resource`, e o motivo começa pelo aspecto (`queue: probe recusada — …`).

Todas as probes do `verify` pedem o limite máximo de linhas (`limits.lines` = 2000, o máximo do `probe`). Mesmo assim, uma probe que volta com `truncated: true` **nunca dá `ok`**: um pod pode não ter respondido ou linhas antigas da janela podem ter ficado de fora. Veja as regras das probes cortadas no `compare`.

A foto **não guarda nenhuma linha de log**, nem mascarada, nem amostra: só assinaturas e contagens, já com a redaction. Ela é um arquivo da tarefa: quem chama apaga o arquivo no fim (SPEC-0091).

`--out` precisa ficar **fora da pasta do atlas**: o caminho é resolvido (com `..` e links) antes de qualquer probe, e a pasta pai e cada pasta acima dela são comparadas com a pasta do atlas pela **identidade** do arquivo (mesmo `st_dev` e `st_ino`), não pelo texto do caminho; assim nem o nome em outra caixa (macOS) nem um link para dentro do atlas passam. Dentro do atlas sai com 2 sem gravar nada. A pasta de `--out` precisa existir. A foto é gravada num temporário criado de forma exclusiva na pasta de destino e depois renomeado: um arquivo ou link que já exista com nome de temporário nunca é seguido. O arquivo fica legível só pela pessoa (0600).

Exemplo de foto `verify@1`, o contrato anterior, que o `compare` continua aceitando como `--baseline` (a foto `verify@2` está em [Foto `verify@2`](#foto-verify2)):

```json
{
  "contract": "verify@1",
  "service": "api",
  "environment": "dev",
  "taken_at": "2026-11-23T09:00:00Z",
  "deployments": {
    "dev-api": {
      "images": ["acme/api:1.4.1@sha256:0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b0a1b"],
      "ready": 3,
      "desired": 3,
      "restarts": {"api-7f9c-aaaa": 0, "api-7f9c-bbbb": 1, "api-7f9c-cccc": 0},
      "warnings": ["BackOff|Pod/api"],
      "error_signatures": {"ERROR user <n> not found": 2}
    }
  },
  "not_verified": []
}
```

Chaves fechadas: uma chave a mais, `contract` fora de `verify@1` e `verify@2`, uma foto `verify@2` sem `dependencies` ou um tipo errado fazem o `compare` recusar a foto (exit 2).

## `verify compare`

```text
atlas.py verify compare --service <id> --env <ambiente> --expect-image <imagem>
    [--baseline <arquivo>] [--window 10m] [--max-new-errors 0] [--max-new-restarts 0]
    [--resource <kind:id>]... [--max-resources 20]
    [--max-new-dlq 0] [--max-queue-age 10m] [--expect-migration [<datastore>=]<migration>]...
    [--max-signal-increase 0.5]
    [--confirm-production] [--json] [--atlas X]
```

- `--expect-image` — a imagem com `:<tag>`, `@<digest>` ou os dois: `acme/api:1.4.2`, `acme/api@sha256:…`. Passa pela mesma normalização do adaptador: o primeiro segmento sai quando tem `.` ou `:` ou é `localhost` (o host do registry, inclusive com porta: `ghcr.io/acme/api:1.4.2` e `localhost:5000/acme/api:1.4.2` viram `acme/api:1.4.2`), o caminho e o digest ficam em minúsculas. Sem tag nem digest sai com 2. **O digest só casa quando o manifesto fixa o digest** (`image: acme/api:1.4.2@sha256:…`): o adaptador lê a imagem do spec do pod, e um manifesto só com a tag não traz digest, então confira pela tag nesse caso.
- `--baseline` — a foto do `snapshot`, do mesmo serviço e ambiente. Ausente, que não é JSON ou fora do contrato sai com 2. Sem ela, os logs ficam não verificados.
- `--window` — a janela dos eventos e dos logs (padrão `10m`, até `24h`).
- `--max-new-errors` e `--max-new-restarts` — o que se tolera (padrão `0` e `0`, conservadores).
- As opções das dependências e dos sinais (`--resource`, `--max-resources`, `--max-new-dlq`, `--max-queue-age`, `--expect-migration`, `--max-signal-increase`) estão em [Dependências e sinais](#dependências-e-sinais-verify2).

Roda as mesmas três probes por deployment e faz três verificações em cada um:

| Verificação | `ok` quando | `failed` quando | `not_verified` quando |
|---|---|---|---|
| `delivery` | o rollout terminou e **todo** pod pronto roda a imagem esperada (pelo digest, se dado; senão pela tag) | um pod pronto com outra imagem (o pod e as imagens dele na evidência), rollout não concluído, nenhum pod pronto ou workload não encontrado | a probe de `status` foi recusada, falhou, respondeu com erro ou voltou cortada ("probe de status cortada") |
| `runtime` | nenhum pod não pronto, os restarts novos somados ≤ `--max-new-restarts` e nenhum aviso novo | pod não pronto, restarts novos acima do limite, aviso (`<motivo>\|<objeto>`) que não estava na foto ou workload não encontrado (`found: false`) | a probe de `status` foi recusada, falhou, respondeu com erro ou voltou cortada; ou a de `events`, sem outra falha, foi recusada, falhou, respondeu com erro ou voltou cortada ("probe de events cortada") |
| `logs` | as assinaturas de erro da janela que não estavam na foto são ≤ `--max-new-errors` | assinaturas novas acima do limite (as novas na evidência) | sem `--baseline` ("sem foto de antes: erros novos e antigos não se separam"); a foto não tem os logs do deployment; logs cortados sem nenhuma linha ("nenhum pod respondeu"); logs cortados com linhas ("probe de logs cortada"); probe recusada, com erro ou que falhou |

- **Restarts novos** = os de agora menos os da foto, por pod; um pod que não estava na foto (por exemplo depois do rollout) conta desde 0. Sem foto, todos contam.
- **Avisos novos** = as chaves `<motivo>|<objeto>` que não estavam na foto; sem foto, todos contam.
- **Assinaturas** = só as de nível `error` do `--summary` (`warn` e `info` não contam).
- **Probes cortadas** (`truncated: true`, mesmo pedindo o limite máximo de linhas): `status` cortada deixa `delivery` e `runtime` em `not_verified`; `events` cortada deixa `runtime` em `not_verified`, salvo quando ele já deu `failed` por outro motivo (pod não pronto, restarts, workload não encontrado); `logs` cortada, com ou sem itens, deixa `logs` em `not_verified`. Os itens de uma probe cortada nunca sustentam um `ok`.

### Veredito e exits

- `degradou` (exit 1) se alguma verificação deu `failed`;
- senão `inconclusivo` (exit 5) se alguma ficou `not_verified`;
- senão `passou` (exit 0).

Uma verificação que não foi feita nunca vira `passou`. Em `degradou`, sai uma **sugestão**: um texto fixo pedindo que a pessoa decida o rollback, citando o repositório de configuração do delivery (o `sourced_from` do deployment no atlas). Ela nunca traz comando, e nada é executado.

Outros exits: 2 argumento inválido (inclusive `--out` dentro do atlas, `--expect-image` sem tag nem digest, `--baseline` inválida, `--window` ou limite fora do formato, `--resource` fora do formato ou não ligado), 3 sem configuração, 4 probes desligadas ou produção sem `--confirm-production`. Uma probe recusada (verbo, sem acesso, sem adaptador) ou com falha **não** dá 4 nem 1: a verificação dela fica `not_verified`.

### Produção

Segue a regra das probes (ADR-0023): ambiente `tier: production` ou sem `tier` só com `--confirm-production`, depois do "sim" da pessoa na conversa. Sem a opção, `snapshot` e `compare` saem com 4 antes de qualquer consulta, e a foto não é gravada. Em produção o `verify` é só passivo, como sempre.

### Saída

Sem `--json`, Markdown: o veredito, uma tabela com cada verificação (deployment, recurso, verificação, status e motivo; o recurso fica vazio nas verificações de deployment), as evidências e a sugestão. Com `--json`, o objeto `verify@2` com as chaves fechadas `contract`, `verdict`, `checks` e `suggestion` (vazia fora de `degradou`); cada verificação tem `deployment`, `resource` (`null` em `delivery`, `runtime` e `logs`; o `kind:id` em `dependencies` e `signals`), `check`, `status`, `evidence` e `reason` (obrigatório em `not_verified`). Quem conhece só o `verify@1` continua achando `verdict`, `checks` e `suggestion`. O exemplo da saída `verify@2` está em [Saída `verify@2`](#saída-verify2); abaixo, a saída `verify@1` de antes, com as mesmas regras:

```json
{
  "contract": "verify@1",
  "verdict": "degradou",
  "checks": [
    {"deployment": "dev-api", "check": "delivery", "status": "ok",
     "evidence": {"expected": "acme/api:1.4.2", "rollout_complete": true, "ready_pods": 3, "pods_with_other_image": [], "workloads_not_found": []},
     "reason": "3 pod(s) pronto(s) com acme/api:1.4.2"},
    {"deployment": "dev-api", "check": "runtime", "status": "failed",
     "evidence": {"workloads_not_found": [], "not_ready_pods": ["api-7c2d-cccc"], "new_restarts": {"api-7c2d-cccc": 4}, "new_restarts_total": 4, "max_new_restarts": 0, "baseline": "foto", "new_warnings": ["BackOff|Pod/api"]},
     "reason": "1 pod(s) não pronto(s); 4 restart(s) novo(s), acima de 0; 1 aviso(s) novo(s)"},
    {"deployment": "dev-api", "check": "logs", "status": "failed",
     "evidence": {"window_seconds": 600, "max_new_errors": 0, "new_error_signatures": {"ERROR timeout calling <texto>": 1}, "known_error_signatures": 1, "truncated": false},
     "reason": "1 assinatura(s) de erro nova(s), acima de 0"}
  ],
  "suggestion": "Degradou: mostre as evidências à pessoa e deixe que ela decida se volta a versão anterior. O rollback, se ela decidir, é feito no repositório de configuração do delivery (acme/iac), pelo fluxo de mudança do time. O verify não executa nenhuma ação no ambiente."
}
```

## Dependências e sinais (`verify@2`)

O contrato `verify@2` (ADR-0026, SPEC-0102) acrescenta, ao que o `verify@1` já fazia, o estado das dependências do serviço no ambiente e os sinais delas. O veredito, os exits, a regra de produção e o "nada no atlas" não mudam. Tudo continua **só de leitura**, pelas probes de recurso (`probe --resource`, SPEC-0096) e pelos adaptadores que cumprem o contrato dos itens abaixo.

### Escopo

- Por padrão, todos os recursos `queue`, `topic` e `datastore` que `linked_resources` (`references/probes.md`) devolve para algum deployment do serviço no ambiente — aresta do deployment, `config_refs` resolvido ou DLQ —, na ordem de `kind:id`. Um `bucket` ligado não entra nesta versão. Um recurso ligado por mais de um deployment entra uma vez, atribuído ao primeiro deployment pelo id.
- Uma fila ligada **só** pelo atributo `dlq` de outra fila não entra por padrão: o estado dela já vem em `dlq_visible` da fila principal. Pedida em `--resource`, ela entra no papel de DLQ (`dlq_of: <kind:id da fila principal>`).
- `--resource <kind:id>` (repetível; repetido conta uma vez) restringe o escopo à lista dada. `kind` em `queue`, `topic` ou `datastore` e o id pela regra de nome simples do atlas; fora disso, inclusive `bucket:<id>`, sai com 2 (`--resource inválido — use <kind>:<id> com kind queue, topic ou datastore`). Um recurso que não é ligado ao serviço no ambiente sai com 2 (`recurso <kind:id> não ligado a <serviço> em <ambiente>`), antes de qualquer probe.
- `--max-resources N` (o mesmo no `snapshot` e no `compare`; inteiro de 1 a 50, padrão 20): os primeiros N pela ordem entram; os excedentes não têm probe e ficam `not_verified` nas duas verificações, com o motivo `acima de --max-resources (N)`. Mais `--resource` distintos que N sai com 2.
- Sem nenhum recurso ligado, `dependencies` fica `{}` e não há verificações por recurso.
- **Sem adaptador de recurso nesta máquina:** se nenhum adaptador de `probes.adapters` declara, num `--describe` `probe@2`, uma das capacidades `messaging`, `database`, `signals` ou `permissions`, e não há `--resource`, o escopo fica vazio: a foto grava `dependencies: {}`, nenhuma probe de recurso roda e o `compare` não emite `dependencies` nem `signals` (o resultado fica como no `verify@1`, sem virar `inconclusivo`). Basta um adaptador de recurso declarado, ou um `--resource`, para o escopo valer; aí os recursos cujo kind não tem adaptador ficam `not_verified` com o motivo (`nenhum adaptador para <capacidade> …`). Essa decisão usa só o `--describe`.

### Aspectos por kind

Cada recurso tem as probes dos aspectos do kind dele, uma depois da outra, cada uma pelo mesmo caminho do `probe` (com `resource` no `probes.log`). Elas pedem `limits.lines` = 2000 e `limits.since_seconds` = `--since` no `snapshot` e `--window` no `compare` (usado só por `metrics`).

| Kind | `dependencies` | `signals` |
|---|---|---|
| `queue` | `queue` (`messaging queue`); `permissions` (`permissions simulate`, só se a relação exige ação) | `signals metrics` |
| `queue` com `dlq_of` | `queue` (`messaging queue`) | `signals metrics` |
| `topic` | `subscriptions` (`messaging subscriptions`); `permissions` (só se a relação exige ação) | `signals metrics` |
| `datastore` com `engine` `postgres` ou `aurora-postgresql` | `migrations` (`database migrations`); `tables` (`database tables`) | `signals metrics` |
| `datastore` com outro `engine` ou sem `engine` (caches, por exemplo) | nenhum (sem a verificação `dependencies`) | `signals metrics` |

A relação é o tipo da aresta que liga o recurso ao deployment (um `config_refs` resolvido conta como `depends_on`; a ligação só por `dlq` não tem relação). Ela diz as ações exigidas no aspecto `permissions`:

| Relação | Kind | Ações exigidas |
|---|---|---|
| `publishes` | `topic` | `publish` |
| `publishes` | `queue` | `send` |
| `consumes` | `queue` | `receive`, `delete` |
| `depends_on` | `queue` | `send` |
| qualquer outra | qualquer | nenhuma |

O adaptador de permissões não recebe as ações a simular: devolve as ações abstratas do kind, e o `verify` escolhe as que a relação exige.

### Contrato dos itens (regra 4a do ADR-0026)

É o contrato entre os adaptadores (`messaging`, `database`, `signals`, `permissions`) e o `verify`: cada adaptador o cumpre e tem um teste de contrato contra ele. O `verify` lê só estes campos de cada item de uma saída `probe@2` com `status: ok`; outros campos podem vir e são descartados (nunca vão para a foto; `api_action` vai só para a evidência). Um item sem um campo obrigatório ou com o tipo errado deixa o aspecto `not_verified`, com o motivo `item fora do contrato de <capacidade> <verbo>: <campo>`. Inteiro = número inteiro, não booleano.

| Capacidade / verbo (alvo) | Itens | Campos e tipos |
|---|---|---|
| `messaging queue` (fila) | exatamente 1 | `visible` e `in_flight` (inteiros ≥ 0), `oldest_age_seconds` (inteiro ≥ 0 ou `null`), `dlq_visible` (inteiro ≥ 0, ou `null` sem DLQ) |
| `messaging subscriptions` (tópico) | 0 ou mais, um por assinatura | `destination` (texto não vazio: o `kind:id` do grafo ou o destino mascarado), `filter_fingerprint` (texto não vazio, ou `null` sem filtro) |
| `database migrations` (PostgreSQL) | 0 ou mais | `id` (texto não vazio), `success` (booleano ou `null`; só `false` deixa a migration como não aplicada) |
| `database tables` (PostgreSQL) | 0 ou mais | `name` (texto não vazio, `schema.tabela`) |
| `signals metrics` (banco, cache, fila, tópico) | 0 ou mais | `name` (texto não vazio), `stat` (`sum`, `count`, `avg`, `min`, `max` ou `p<n>`, como `p95` ou `p99.9`), `value` (número finito ou `null`), `kind` (`error`, `latency`, `saturation` ou `traffic`) |
| `permissions simulate` (fila, tópico) | 0 ou mais | `action` (`publish`, `send`, `receive`, `delete`, `read` ou `write`), `api_action` (texto, só evidência), `decision` (`allowed` ou `denied`; um *deny* implícito conta como `denied`) |

- `messaging queue` com 0 ou mais de 1 item → `not_verified` (`resposta de messaging queue com <n> item(ns), esperado 1`).
- `signals metrics` com o mesmo `name|stat` repetido → `not_verified` (`métrica repetida: <name>|<stat>`).
- `permissions simulate` com a mesma `action` repetida e decisões diferentes → conta como `denied`.
- A impressão digital do filtro e o `destination` são responsabilidade do adaptador: o mesmo filtro dá sempre o mesmo texto, sem o conteúdo do filtro.
- Os textos chegam já mascarados pelo núcleo (ids de conta em ARNs e URLs como `[REDACTED]`); a comparação é feita sobre o texto mascarado, igual nas duas fases.

Um exemplo válido e um inválido por capacidade e verbo (os blocos `verify-items` são lidos pelo teste de contrato da SPEC-0102: cada bloco é a lista de itens de uma saída `probe@2`):

```json verify-items messaging queue valid
[{"visible": 3, "in_flight": 1, "oldest_age_seconds": 40, "dlq_visible": 0, "delayed": 0}]
```

```json verify-items messaging queue invalid
[{"visible": "3", "in_flight": 1, "oldest_age_seconds": 40, "dlq_visible": 0}]
```

```json verify-items messaging subscriptions valid
[{"destination": "queue:orders-billing", "filter_fingerprint": null},
 {"destination": "arn:aws:sqs:us-east-1:[REDACTED]:orders-audit", "filter_fingerprint": "fp-1a2b", "filter_keys": ["type"]}]
```

```json verify-items messaging subscriptions invalid
[{"endpoint": "queue:orders-billing", "filter_fingerprint": null}]
```

```json verify-items database migrations valid
[{"id": "20261124_add_status", "success": true, "tool": "flyway"},
 {"id": "20261120_create_orders", "success": null},
 {"id": "20261125_half", "success": false}]
```

```json verify-items database migrations invalid
[{"id": "20261124_add_status", "tool": "flyway"}]
```

```json verify-items database tables valid
[{"name": "public.orders", "estimated_rows": 1200}, {"name": "public.items"}]
```

```json verify-items database tables invalid
[{"name": ""}]
```

```json verify-items signals metrics valid
[{"name": "Errors", "stat": "sum", "value": 0, "kind": "error"},
 {"name": "Latency", "stat": "p95", "value": 120.5, "kind": "latency"},
 {"name": "Depth", "stat": "max", "value": null, "kind": "saturation"}]
```

```json verify-items signals metrics invalid
[{"name": "Errors", "stat": "median", "value": 1, "kind": "error"}]
```

```json verify-items permissions simulate valid
[{"action": "receive", "api_action": "sqs:ReceiveMessage", "decision": "allowed"},
 {"action": "delete", "api_action": "sqs:DeleteMessage", "decision": "allowed"}]
```

```json verify-items permissions simulate invalid
[{"action": "receive", "api_action": "sqs:ReceiveMessage", "decision": "implicitDeny"}]
```

### Foto `verify@2`

Chaves fechadas: `contract` (`verify@2`), `service`, `environment`, `taken_at`, `deployments` (como no `verify@1`), `dependencies` e `not_verified`.

- `dependencies`: mapa `"<kind:id>" → objeto` com as chaves fechadas `deployment`, `relations` (lista), `dlq_of` (texto ou `null`) e, só quando a probe sustentou o aspecto, `queue` (os 4 campos), `subscriptions` (lista de `{"destination", "filter_fingerprint"}`, ordenada), `migrations` (os `id` aplicados, com `success` diferente de `false`, ordenados), `tables` (ordenada), `signals` (`{"window_seconds": n, "metrics": {"<name>|<stat>": {"kind", "value"}}}`) e `permissions` (`{"<ação>": "allowed" | "denied"}`). Só contagens, conjuntos de nomes e agregados: nunca dado de linha, corpo de mensagem nem amostra.
- `not_verified`: os itens do `verify@1` (`deployment`, `check`, `reason`) e os de recurso, com `deployment`, `resource`, `check` (`dependencies` ou `signals`) e `reason`, que começa pelo aspecto.

```json
{"contract": "verify@2", "service": "orders", "environment": "dev", "taken_at": "2026-11-24T09:00:00Z",
 "deployments": {"dev-orders": {"images": ["acme/orders:2.0.1"], "ready": 2, "desired": 2,
                                "restarts": {"orders-6b7c-aaaa": 0, "orders-6b7c-bbbb": 0},
                                "warnings": [], "error_signatures": {}}},
 "dependencies": {
   "queue:orders": {"deployment": "dev-orders", "relations": ["consumes"], "dlq_of": null,
                    "queue": {"visible": 3, "in_flight": 1, "oldest_age_seconds": 40, "dlq_visible": 0},
                    "signals": {"window_seconds": 1800,
                                "metrics": {"ApproximateAgeOfOldestMessage|max": {"kind": "latency", "value": 40}}},
                    "permissions": {"receive": "allowed", "delete": "allowed"}},
   "datastore:orders-db": {"deployment": "dev-orders", "relations": ["depends_on"], "dlq_of": null,
                           "migrations": ["20261120_create_orders"], "tables": ["public.orders"]}},
 "not_verified": [{"deployment": "dev-orders", "resource": "datastore:orders-db", "check": "signals",
                   "reason": "signals: probe recusada — nenhum adaptador para signals com alvo datastore (probes.adapters)"}]}
```

Uma foto `verify@2` sem `dependencies` é recusada (no `compare`, exit 2):

```json verify@2 snapshot invalid
{"contract": "verify@2", "service": "orders", "environment": "dev", "taken_at": "2026-11-24T09:00:00Z",
 "deployments": {}, "not_verified": []}
```

### Regras da comparação

Antes das regras, para as duas verificações de um recurso:

- sem `--baseline` → `not_verified` (`sem foto de antes: dependências e sinais não se comparam`), sem probe de recurso;
- `--baseline` `verify@1` → `not_verified` (`foto sem dependências`), sem probe de recurso;
- recurso do escopo ausente de `dependencies` da foto → `not_verified` (`recurso fora da foto`): a comparação é sempre contra a foto; tire a foto depois do `build` com o recurso já mapeado;
- recurso da foto fora do escopo atual → ignorado.

**`dependencies`** avalia cada aspecto do kind: `failed` se algum aspecto falha; senão `not_verified` se algum não pôde ser verificado (sem adaptador, sem acesso local, probe recusada, com erro, com falha, cortada, item fora do contrato, ou o aspecto ausente da foto quando a regra precisa dela); senão `ok`.

| Aspecto | `failed` quando | Precisa da foto? |
|---|---|---|
| `queue` (fila) | `dlq_visible` agora − `dlq_visible` da foto > `--max-new-dlq` (foto `null` e agora número: a foto conta como 0); ou `oldest_age_seconds` agora > `--max-queue-age` **e** na foto era `null` ou ≤ o limite (passou do limite depois do deploy) | sim |
| `queue` (fila com `dlq_of`) | `visible` agora − `visible` da foto > `--max-new-dlq` (a idade não conta) | sim |
| `subscriptions` | um `destination` da foto sumiu, ou o conjunto de `filter_fingerprint` de um `destination` mudou (assinatura nova não falha; vai em `new`) | sim |
| `migrations` | uma migration de `--expect-migration` deste datastore não está entre os `id` aplicados agora (`success` diferente de `false`) | não (a foto só dá `new_since_baseline`) |
| `tables` | um `name` da foto não está entre os de agora (tabela nova não falha) | sim |
| `permissions` | uma ação exigida pela relação estava `allowed` na foto e vem `denied` agora | sim |

- `dlq_visible` `null` agora com número na foto → `not_verified` (`DLQ sem leitura agora`); `null` nas duas → sem DLQ, só evidência.
- Idade já acima do limite na foto → não falha por idade; a evidência traz `age_above_limit_in_baseline: true`.
- Probe cortada (`truncated: true`) → `not_verified` (`probe de <verbo> cortada`), com uma exceção: em `migrations`, se todas as esperadas estão entre os itens recebidos, o aspecto é `ok` (achar é prova; não achar numa lista cortada não é).
- Ação exigida ausente dos itens de `simulate` agora → `not_verified` (`ação <a> não simulada`); ausente da foto → `not_verified` (`ação <a> fora da foto`).
- Ação exigida já `denied` na foto e `denied` agora → `not_verified` (`permissão já negada antes do deploy`), com a ação em `denied_in_baseline`; `denied` na foto e `allowed` agora → `ok`.

**`signals`** compara cada métrica (`name|stat`) presente na foto e agora:

- `sum` e `count` são normalizados por minuto (`value / (janela em segundos / 60)`), porque a janela da foto (`--since`) e a de agora (`--window`) diferem; as outras estatísticas são comparadas como vêm;
- `kind: error` piora quando, com a foto > 0, agora > foto × (1 + `--max-signal-increase`); com a foto 0 ou `null`, qualquer valor > 0 agora;
- `kind: latency` piora quando, com a foto > 0, agora > foto × (1 + `--max-signal-increase`); com a foto 0 ou `null`, não é comparada (`without_baseline`);
- `saturation` e `traffic` nunca falham; vão só em `other`;
- `value` `null` agora → não comparada (`without_data`);
- status: `failed` se alguma métrica de `error` ou `latency` piorou; senão `not_verified` se a probe não sustentou ou se nenhuma métrica de erro ou latência foi comparada (`nenhuma métrica de erro ou latência comparável`); senão `ok`.

### Opções do `compare`

- `--max-new-dlq N` — mensagens novas toleradas na DLQ (inteiro ≥ 0, padrão 0).
- `--max-queue-age D` — a idade máxima da mensagem mais antiga, no formato de `--window` (padrão `10m`, até `24h`).
- `--expect-migration [<datastore>=]<migration>` — repetível; a migration casa `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` (ex.: `orders-db=20261124_add_status`). A forma sem `<datastore>=` só vale com exatamente um `datastore` no escopo; com zero ou mais de um sai com 2 (`--expect-migration <m> ambígua: use <datastore>=<migration>`). Um `<datastore>` fora do escopo sai com 2 (`recurso datastore:<id> fora do escopo do verify`).
- `--max-signal-increase X` — a piora tolerada nas métricas de erro e latência, decimal de 0 a 100 (padrão `0.5`, ou seja 50%); fora disso sai com 2.

Todos são conferidos antes de qualquer probe.

### Evidências

- `dependencies`: `relations`, `dlq_of`, `queue` (`now`, `baseline`, `new_dlq`, `max_new_dlq`, `max_queue_age_seconds`, `age_above_limit_in_baseline`), `subscriptions` (`missing`, `changed`, `new`), `migrations` (`expected`, `missing`, `not_applied`, `new_since_baseline`), `tables` (`missing`, `new`: quantas tabelas novas), `permissions` (`required`: `allowed`, `denied` ou `ausente` por ação exigida; `api_actions`; `denied_in_baseline`) e `not_verified` (`{"<aspecto>": "<motivo>"}`), cada aspecto só quando é do kind e foi avaliado.
- `signals`: `window_seconds`, `baseline_window_seconds`, `max_signal_increase`, `worse` (`[{"metric": "<name>|<stat>", "kind", "baseline", "now"}]`, valores normalizados), `compared`, `without_baseline`, `without_data` e `other`.

A sugestão de `degradou` é a mesma do `verify@1`: nenhuma ação é sugerida na fila, no banco nem na política.

### Saída `verify@2`

```json
{
  "contract": "verify@2",
  "verdict": "degradou",
  "checks": [
    {"deployment": "dev-orders", "resource": null, "check": "delivery", "status": "ok",
     "evidence": {"expected": "acme/orders:2.0.2", "rollout_complete": true, "ready_pods": 2, "pods_with_other_image": [], "workloads_not_found": []},
     "reason": "2 pod(s) pronto(s) com acme/orders:2.0.2"},
    {"deployment": "dev-orders", "resource": null, "check": "runtime", "status": "ok",
     "evidence": {"workloads_not_found": [], "not_ready_pods": [], "new_restarts": {}, "new_restarts_total": 0, "max_new_restarts": 0, "baseline": "foto", "new_warnings": []},
     "reason": "pods prontos, sem restart nem aviso novo"},
    {"deployment": "dev-orders", "resource": null, "check": "logs", "status": "ok",
     "evidence": {"window_seconds": 600, "max_new_errors": 0, "new_error_signatures": {}, "known_error_signatures": 0, "truncated": false},
     "reason": "0 assinatura(s) de erro nova(s)"},
    {"deployment": "dev-orders", "resource": "queue:orders", "check": "dependencies", "status": "failed",
     "evidence": {"relations": ["consumes"], "dlq_of": null,
                  "queue": {"now": {"visible": 2, "in_flight": 0, "oldest_age_seconds": 30, "dlq_visible": 4},
                            "baseline": {"visible": 3, "in_flight": 1, "oldest_age_seconds": 40, "dlq_visible": 0},
                            "new_dlq": 4, "max_new_dlq": 0, "max_queue_age_seconds": 600, "age_above_limit_in_baseline": false},
                  "permissions": {"required": {"receive": "allowed", "delete": "allowed"},
                                  "api_actions": {"receive": "sqs:ReceiveMessage", "delete": "sqs:DeleteMessage"},
                                  "denied_in_baseline": []},
                  "not_verified": {}},
     "reason": "queue: a DLQ ganhou 4 mensagem(ns), acima de 0"},
    {"deployment": "dev-orders", "resource": "queue:orders", "check": "signals", "status": "ok",
     "evidence": {"window_seconds": 600, "baseline_window_seconds": 1800, "max_signal_increase": 0.5, "worse": [], "compared": 1,
                  "without_baseline": [], "without_data": [], "other": []},
     "reason": "1 métrica(s) de erro ou latência dentro do limite"}
  ],
  "suggestion": "Degradou: mostre as evidências à pessoa e deixe que ela decida se volta a versão anterior. O rollback, se ela decidir, é feito no repositório de configuração do delivery (acme/iac), pelo fluxo de mudança do time. O verify não executa nenhuma ação no ambiente."
}
```

Uma verificação `verify@2` sem `resource` é recusada pelo validador:

```json verify@2 result invalid
{"contract": "verify@2", "verdict": "passou", "suggestion": "",
 "checks": [{"deployment": "dev-orders", "check": "delivery", "status": "ok", "evidence": {}, "reason": ""}]}
```

### Compatibilidade com o `verify@1`

- O `compare` aceita a foto `verify@1`: `delivery`, `runtime` e `logs` seguem as regras de sempre, e `dependencies` e `signals` ficam `not_verified` com "foto sem dependências", sem nenhuma probe de recurso.
- A saída passa a `verify@2`, mantendo `verdict`, `checks`, `suggestion`, o exit e as regras de veredito.
- Quem não declarou nenhum adaptador de recurso (e não passa `--resource`) não vê `dependencies` nem `signals`.
- Os adaptadores `probe@1` continuam valendo para o `runtime`; um adaptador `probe@1` nunca recebe um recurso.
- Rollback da skill: uma foto `verify@2` é recusada pelo `compare` antigo (exit 2); basta tirar a foto de novo.

## Validadores

`atlas.py` tem `validate_verify_snapshot(data)` e `validate_verify_result(data)`, que devolvem a lista de problemas (`[]` = válido). Os dois aceitam `verify@1` e `verify@2` e recusam qualquer outro `contract`. O `snapshot` só grava uma foto `verify@2` válida, o `compare` só aceita uma `--baseline` válida (`verify@1` ou `verify@2`) e só imprime um resultado `verify@2` válido. O conjunto fechado de `check` vem do registro `VERIFY_CHECKS` do `atlas.py` (o ponto de extensão: a SPEC-0103 acrescenta `functional`, no nível do deployment, com `resource: null`).

## Uso típico (G6 da gluon-spec)

1. Antes do merge: `verify snapshot --service api --env dev --out <pasta da tarefa>/foto.json`.
2. Depois que o roteiro de verificação (SPEC-0086) mostra a imagem nova no repositório de configuração: `verify compare --service api --env dev --baseline <pasta da tarefa>/foto.json --expect-image acme/api:1.4.2 --json` (com `--expect-migration <datastore>=<migration>` quando o PR traz uma migration, e `--resource` para restringir às dependências que o PR toca).
3. Leve o veredito e as evidências ao Relatório de Entrega; em `degradou`, mostre a sugestão e deixe a pessoa decidir. Se o rollout ainda não terminou, repita depois da janela.
4. Apague a foto no fim da tarefa.
