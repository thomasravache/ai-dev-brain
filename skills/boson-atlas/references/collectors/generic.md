# Collector `generic`

Turns a hand-written facts file (JSON) into the `boson-atlas/collector@1` output (`references/collector-contract.md`, ADR-0011). Use it for anything no other collector covers (a datastore, a queue, an external dependency) and as the template for writing a collector of your own: one stdlib-only script that prints one JSON object and exits 0.

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
- **Curated journeys** (SPEC-0103): the `journeys` attr of a `service` lists the ids of the user journeys that the `functional` probe runs in a `tier: test` environment. Only a person declares them, here, and the atlas PR (mode `repo`) or the person's own edit (mode `local`) is the confirmation; no other collector emits them. Only ids: never a command, script or URL (the commands live in the journeys file of the machine, `references/probes/suite.md`).

```json
{"entities": [{"kind": "service", "id": "api", "attrs": {"journeys": ["checkout", "login"]}}]}
```

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

Contract name: since 2026.11.8 the collector prints `boson-atlas/collector@1`; the old name `org-atlas/collector@1` is the same contract and is still accepted by `scan`, `build`, `lint` and `context` until its removal, not before 2027-03 (SPEC-0071, SPEC-0073). Until then `scan` writes `snapshots/<id>.json` with the old name, whatever the collector printed, so machines still on the previous version keep reading them.
