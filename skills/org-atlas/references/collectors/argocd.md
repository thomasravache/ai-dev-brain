# Collector `argocd`

Category `delivery`. Reads the Argo CD Applications, through the `argocd` CLI or through `kubectl`, and prints the `org-atlas/collector@1` output (`references/collector-contract.md`, ADR-0011): what runs where (deployments, services, environments, clusters), which repository each deployment comes from, and its **configuration references** — the names of keys that point to a host or resource (`DB_URL=db.interno`), the raw material the cross-referencing step (SPEC-0036) uses to find who depends on which database, queue or service.

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
| `--service-label KEY` | `app.kubernetes.io/part-of` | Application label that names the service; without it, the Application name |
| `--env-label KEY` | `env` | Application label that names the environment; without it, the destination namespace |
| `--ref-suffixes a,b` | `_HOST,_URL,_DSN,_ADDR,_QUEUE,_TOPIC,_BUCKET` | key suffixes extracted into `config_refs` (case-insensitive) |
| `--input FILE` | — | read a recorded response instead of calling a CLI (tests, or running without access) |

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
| `service:<service>` (label `--service-label`, else the Application name) | none |
| `environment:<environment>` (label `--env-label`, else the destination namespace) | none |
| `cluster:<destination.server>`, or `cluster:<destination.name>` when there is no server | none |

Relations: `deployment → service` (`deploys`), `deployment → environment` (`runs_in`), `deployment → cluster` (`runs_in`), and `deployment → repository:<owner>/<repo>` (`sourced_from`) when a `repoURL` is a GitHub repository — `https://github.com/o/r(.git)`, with or without a trailing `/` or credentials, `git@github.com:o/r.git` or `ssh://git@github.com/o/r.git`. Helm chart repositories and other Git hosts get no `sourced_from`. Multi-source Applications (`spec.sources`) contribute every source.

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
- Only key names from the suffix list and bare hosts or resource names leave; never a whole configuration value, a key outside the list (`LOG_LEVEL`, `DB_PASSWORD`, `API_TOKEN`), a credential, a port, a path or a query string.
- Secrets are never read: not through the CLI, and Secrets listed in `status.resources` are ignored.
- Annotations are never read, so `last-applied-configuration` (which repeats the whole spec) never leaves.
- The cluster id is the destination server URL as Argo CD stores it (credentials, should one be there, are removed).

## Limits

- Target: 1,000 Applications mapped in under 10 s after the CLI answers (measured on a generated fixture).
- Only Argo CD; Flux and other delivery tools come as separate collectors (SPEC-0029).
- `config_refs` from Helm values are read from the Application only, not from `values.yaml` files in the chart or the GitOps repository.
