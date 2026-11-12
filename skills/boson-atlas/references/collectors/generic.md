# Collector `generic`

Turns a hand-written facts file (JSON) into the `org-atlas/collector@1` output (`references/collector-contract.md`, ADR-0011). Use it for anything no other collector covers (a datastore, a queue, an external dependency) and as the template for writing a collector of your own: one stdlib-only script that prints one JSON object and exits 0.

## Declare it

```yaml
collectors:
  - id: runtime-facts
    category: runtime
    command: ["python3", "{skill}/assets/collectors/generic.py", "--facts", "{atlas}/facts/runtime.json", "--category", "runtime"]
```

## Options

| Option | Required | Meaning |
|---|---|---|
| `--facts FILE` | yes | the facts file (JSON) |
| `--category C` | yes | the contract category of the output (`code`, `runtime`, `docs`, ...) |
| `--source NAME` | no | the `source` of every entity and relation (default `generic`); `collector` stays `generic` |

## Facts file

```json
{
  "entities": [{"kind": "datastore", "id": "payments-db", "name": "payments-db", "attrs": {"engine": "postgres"}}],
  "relations": [{"from": "service:payments-api", "to": "datastore:payments-db", "type": "writes"}]
}
```

- `kind` and `id` are required in every entity; `name` defaults to the id and `attrs` to `{}`.
- `from`, `to` and `type` are required in every relation.
- Kinds, relation types and `attrs` rules are the contract's: the `scan` validates the output, drops forbidden keys and masks secrets. Never put a secret value in the file; a `secret-ref` holds only the name and where the secret lives.

## Output

`{contract, collector: "generic", category, collected_at, entities, relations}`, with `source` added to every fact. The facts are copied as they are; the collector makes no call and reads nothing else.

## Failure modes (exit 1, message on stderr, nothing on stdout)

| Message | When |
|---|---|
| `<file>: arquivo não encontrado` | the file does not exist |
| `<file>: JSON inválido (...)` | the file is not valid JSON |
| `<file>: entities[<i>]: falta o campo id` (or `kind`) | an entity without `kind` or `id` |
| `<file>: relations[<i>]: falta o campo from` (or `to`, `type`) | a relation without a required field |
| `<file>: entities precisa ser uma lista` | `entities` or `relations` is not a list |
