# Collector `argocd`

Category `delivery`. Reads the Argo CD Applications, through the `argocd` CLI or through `kubectl`, and prints the `boson-atlas/collector@1` output (`references/collector-contract.md`, ADR-0011): what runs where (deployments, services, environments, clusters), which repository each deployment comes from, and its **configuration references** — the names of keys that point to a host or resource (`DB_URL=db.interno`), the raw material the cross-referencing step (SPEC-0036) uses to find who depends on which database, queue or service.

## Setup

Pick one of the two access paths; both are **read-only** and only list Applications.

1. **`--from argocd`**: install the `argocd` CLI and run `argocd login <server>` (or export `ARGOCD_AUTH_TOKEN`, declared by name in `credentials` of the local config, never the value). Use an account or project role whose RBAC policy allows only `applications, get` on the projects to map, for example `p, role:atlas-reader, applications, get, */*, allow`. No `sync`, `override`, `exec` or `logs` permission is needed.
2. **`--from kubectl`**: a kubeconfig context with a ClusterRole that allows only `get` and `list` on `applications.argoproj.io` (no Secrets, no other resources), for example:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: atlas-argocd-reader
rules:
  - apiGroups: ["argoproj.io"]
    resources: ["applications"]
    verbs: ["get", "list"]
```

3. Declare it in `atlas-config.yml`:

```yaml
collectors:
  - id: argocd
    category: delivery
    command: ["python3", "{skill}/assets/collectors/argocd.py", "--from", "argocd"]
    timeout: 300
```

The collector never reads or prints a token; the CLI handles it. It uses only the CLI you choose with `--from` and never falls back to the other one.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--from argocd\|kubectl` | required | which CLI lists the Applications |
| `--service-label KEY` | `app.kubernetes.io/part-of` | Application label that names the service; without it, the Helm `nameOverride`, then the Application name (see [Service name](#service-name)) |
| `--env-label KEY` | `env` | Application label that names the environment; without it, the destination namespace |
| `--ref-suffixes a,b` | `HOST,URL,URI,ENDPOINT,DSN,ADDR,_QUEUE,_TOPIC,_BUCKET` | key suffixes extracted into `config_refs` (case-insensitive, matched only at the end of the key); replaces the whole list |
| `--input FILE` | — | read a recorded response instead of calling a CLI (tests, or running without access) |

The default suffixes cover both `SNAKE_CASE` keys (`DB_HOST`, `API_URL`) and .NET-style keys without `_` (`Acme.Account__RouterEndpoint`, `ServiceUrl`, `CallbackUri`): `HOST` and `URL` also match `_HOST` and `_URL`, so the default is a superset of the one before 2026.11.9 (SPEC-0076). A suffix matches the end of the key only, in any case: `serviceurl` and `DB_HOST` match, `HostName` and `UrlPrefix` do not.

`--ref-suffixes` replaces the whole list, so repeat the defaults you want to keep. For example, to also extract keys ending in `redis` (`SessionRedis`, `CACHE_REDIS`), in `atlas-config.yml`:

```yaml
collectors:
  - id: argocd
    category: delivery
    command: ["python3", "{skill}/assets/collectors/argocd.py", "--from", "argocd",
              "--ref-suffixes", "HOST,URL,URI,ENDPOINT,DSN,ADDR,_QUEUE,_TOPIC,_BUCKET,REDIS"]
    timeout: 300
```

## CLI calls

One call per run, argv as a list without a shell, stdin closed (no prompt), 120 s timeout:

| `--from` | Command |
|---|---|
| `argocd` | `argocd app list -o json` |
| `kubectl` | `kubectl get applications.argoproj.io -A -o json` |

Nothing else is called: no `app get`, `app manifests` or `app resources`, no Secrets, no rendered manifests, no cluster state beyond the Application objects. From each Application only `metadata.name`, `metadata.labels`, `spec.project`, `spec.destination`, `spec.source` / `spec.sources` and `status.sync.status` / `status.health.status` are read; annotations (such as `last-applied-configuration`), `status.resources`, `status.history` and `status.sync.comparedTo` are ignored.

## Output

| Entity | Attributes |
|---|---|
| `deployment:<Application name>` | `project`, `namespace` (destination), `sync_status`, `health_status`, `config_refs` |
| `service:<service>` (label `--service-label`, else the Helm `nameOverride`, else the Application name) | none |
| `environment:<environment>` (label `--env-label`, else the destination namespace) | none |
| `cluster:<destination.server>`, or `cluster:<destination.name>` when there is no server | none |

Relations: `deployment → service` (`deploys`), `deployment → environment` (`runs_in`), `deployment → cluster` (`runs_in`), and `deployment → repository:<owner>/<repo>` (`sourced_from`) when a `repoURL` is a GitHub repository — `https://github.com/o/r(.git)`, with or without a trailing `/` or credentials, `git@github.com:o/r.git` or `ssh://git@github.com/o/r.git`. The target id is lower case (`https://github.com/Acme/API.git` → `repository:acme/api`), the same id the GitHub collector emits, since GitHub names are case-insensitive (SPEC-0047). Helm chart repositories and other Git hosts get no `sourced_from`. Multi-source Applications (`spec.sources`) contribute every source.

### Service name

The service of each Application is, in this order (SPEC-0076):

1. the `--service-label` label of the Application;
2. the Helm `nameOverride`, read only at the root of the values of the first source that declares a valid one (`spec.source`, then each of `spec.sources`). Inside one source the Argo CD and Helm precedence applies: the `nameOverride` parameter of `helm.parameters` (that exact name, not `chart.nameOverride`), then the root key of `helm.valuesObject`, then a line without indentation of `helm.values` (`nameOverride: account`, quoted or not);
3. the Application name.

The `nameOverride` counts only when it is a simple name (the same rule as a host or resource name). An empty value, a YAML null or boolean literal (`null`, `~`, `true`, `false`, in any case, quoted or not), a template (`{{ .Values.app }}`, `${NAME}`), a value with a space or a non-text value is ignored, and the search goes on to the next place, then to the next source; the Application name is used only when no source has a valid one. So Applications per environment (`dev-account`, `qa-account`) whose chart declares `nameOverride: account` all deploy `service:account`, and a value such as `http://account` in another Application matches that service in `build`.

Shared entities (a service, environment or cluster used by several Applications) appear once. When two Applications have the same name (Applications in several namespaces), the whole first one is kept: the later one adds no deployment and no relation, a warning naming it (`aviso: Application repetida ignorada: NAME (namespace NS) — fica a primeira`) goes to stderr, and the exit stays 0.

### `config_refs`

A sorted list, without repetition, of `KEY=host` taken from:

- `spec.source.helm.parameters` (`{name, value}`; a dotted name counts by its last segment: `env.DB_URL` → `DB_URL`);
- `helm.values` (YAML text, read line by line: `KEY: value` at any indentation, single or double quotes, comment lines and trailing comments ignored, and the `- name: KEY` / `value: ...` list form);
- `helm.valuesObject` (nested object at any depth, also `{name, value}` items);
- `plugin.env` (`{name, value}`).

Only keys ending in one of `--ref-suffixes` count, and only the host or resource name of the value leaves:

| Value | Reference |
|---|---|
| `postgres://user:senha@db.interno:5432/app?ssl=true` | `db.interno` |
| `admin:pass@mq.interno:5672` | `mq.interno` |
| `cache.interno:6379` | `cache.interno` |
| `s3://acme-uploads/web/` | `acme-uploads` |
| `orders-events`, `payments.events` | as is |
| `https://sqs.us-east-1.amazonaws.com/123456789012/orders` (SQS queue URL) | `orders` |
| `https://us-east-1.queue.amazonaws.com/123456789012/billing.fifo` (legacy SQS queue URL) | `billing.fifo` |
| `https://sqs-fips.us-east-1.amazonaws.com/123456789012/orders` (SQS FIPS endpoint) | `orders` |
| `https://vpce-1.sqs.us-east-1.vpce.amazonaws.com/123456789012/orders` (SQS VPC endpoint) | `orders` |
| `arn:aws:sns:us-east-1:123456789012:orders-events` (SNS topic ARN) | `orders-events` |
| `arn:aws:sqs:sa-east-1:123456789012:orders-dlq` (SQS queue ARN) | `orders-dlq` |
| `https://sqs.us-east-1.amazonaws.com/orders` (SQS URL without the account), `arn:aws:s3:::bucket`, `arn:aws:iam::123456789012:role/x` | none |
| `true`, `false`, `null`, `~` (any case) | none |
| `Server=db;Password=abc@xyz`, `Host=db;Password=p@ss` (connection string without a scheme) | none |

The SQS host (`sqs.<region>.amazonaws.com`) is the same for every queue of a region, so the queue name is taken from the path and the reference becomes `ORDERS_QUEUE_URL=orders`; the `build` matches it with a `queue` or `topic` of the same name emitted by another collector (SPEC-0076).

User, password, port, path and query are stripped by the collector, before the `scan`'s redaction (two layers). A value with nothing safe left (empty, a template such as `${DB_HOST}` or `{{ .Values.x }}`, a list `a:9092,b:9092`, `user:pass` without a host) gives no reference. The cross-referencing step decides what the reference means (`depends_on`, inferred); the collector does not guess whether it is a read or a write.

## `--input` formats

`FILE` is one JSON file in either CLI format, whatever `--from` says:

- the list printed by `argocd app list -o json` (`[...]`, `null` = none);
- the `List` object printed by `kubectl get applications.argoproj.io -A -o json` (`{"kind": "List", "items": [...]}`).

With `--input` the collector never calls a CLI.

## Failure modes (exit 1, message on stderr, nothing on stdout)

| Message | When |
|---|---|
| `<argocd\|kubectl> não encontrado — veja references/collectors/argocd.md` | the chosen CLI is not on the `PATH` |
| `sem acesso às Applications (...) — veja references/collectors/argocd.md` | the CLI fails for a login, server or permission reason (argocd `Unauthenticated` / `PermissionDenied`, expired session, `server address unspecified` when no `argocd login` was done; kubectl `Unauthorized` / `Forbidden`) |
| `resposta inválida da CLI (...)` | the CLI exits 0 but stdout is not JSON, or is not a list of Applications |
| `<cli> falhou (saiu com N): <last stderr line>` | any other CLI failure (server unreachable, Argo CD CRD not installed) |
| `<cli>: tempo esgotado (120 s)` | the call took longer than the timeout |
| `--input: arquivo não encontrado: FILE` / `--input: FILE: ...` | `--input` missing, not JSON, or not a list of Applications |

## Privacy

- Host rule: the scheme is dropped and the authority is the text up to the first `/`, `?` or `#`. When an `@` appears after that point (in the path, query or fragment — a password may contain `@`, `/`, `#` or `?`), the value is ambiguous and gives **no reference** (`postgres://db/app?password=Pa55@word`, `postgres://u:p#ss@db/x`): losing a reference is acceptable, leaking never is. Otherwise the host is what follows the last `@` of the authority (`redis://:p@ss@cache:6379` → `cache`), without the port, and it must be a strict host name, IP or resource name, otherwise there is no reference.
- YAML null and boolean literals (`null`, `~`, `true`, `false`, in any case) never give a reference nor a service name: with the broader default suffixes, flags such as `ENABLE_CURL=true` or `VerifyHost=false` would otherwise become references (SPEC-0076).
- A value without a scheme whose authority contains `=` or `;` is treated as a connection string (`Server=db;Password=p@ss`) and gives **no reference**: the text after its last `@` may be part of a password (SPEC-0076).
- AWS queues and topics (SPEC-0076): an SQS queue URL — standard (`sqs.<region>.amazonaws.com`), FIPS (`sqs-fips.<region>.amazonaws.com`), VPC endpoint (`<vpce-id>.sqs.<region>.vpce.amazonaws.com`) or legacy (`<region>.queue.amazonaws.com`) — gives the queue name only when its path is exactly `/<account>/<queue>`; an SQS URL without the account segment, with an extra path or with a query gives **no reference**, so the regional host never leaves alone. An ARN gives a reference only for `sqs` and `sns` (`arn:<partition>:sqs|sns:<region>:<account>:<name>`); any other ARN gives none. The account id, the region, the VPC endpoint id and the rest of the URL or ARN never leave, an `@` anywhere in an SQS or ARN value gives no reference, and the name must be a strict resource name (`orders:dlq`, `orders_` or `orders%2Fx` give none).
- Only key names from the suffix list and bare hosts or resource names leave; never a whole configuration value, a key outside the list (`LOG_LEVEL`, `DB_PASSWORD`, `API_TOKEN`), a credential, a port, a path or a query string.
- Secrets are never read: not through the CLI, and Secrets listed in `status.resources` are ignored.
- Annotations are never read, so `last-applied-configuration` (which repeats the whole spec) never leaves.
- The cluster id is the destination server URL as Argo CD stores it (credentials, should one be there, are removed).

## Limits

- Target: 1,000 Applications mapped in under 10 s after the CLI answers (measured on a generated fixture).
- Only Argo CD; Flux and other delivery tools come as separate collectors (SPEC-0029).
- `config_refs` from Helm values are read from the Application only, not from `values.yaml` files in the chart or the GitOps repository.

Contract name: since 2026.11.8 the collector prints `boson-atlas/collector@1`; the old name `org-atlas/collector@1` is the same contract and is still accepted by `scan`, `build`, `lint` and `context` until its removal, not before 2027-03 (SPEC-0071, SPEC-0073). Until then `scan` writes `snapshots/<id>.json` with the old name, whatever the collector printed, so machines still on the previous version keep reading them.
