# Board adapters

The repository is the **single source of truth**; a board (Jira, GitHub Issues/Projects, Linear, Azure Boards, Trello…) is a **view** of it. The SDD core never talks to a board: `spec_graph.py` only reads and writes files. An adapter is a guide that tells the agent how to turn neutral operations into calls of the tool it has (MCP server, CLI, REST API). Changing boards means changing the adapter, never the flow.

The project's choice lives in `docs/specs/sdd-config.yml` → `tracker` (`provider: none` = repository only). Every session, tool and model reads it from there — nothing depends on conversation memory.

## Direction

- **repo → board (always):** the board mirrors specs, statuses, blocks, dependencies and delivery evidence.
- **board → repo (only with `mode: push+intake`, and only as input):** a ticket can be the **origin** of a spec, and board comments become Questões em Aberto or impediments recorded by the Architect. A status change made on the board never changes a spec: `sync --check` reports it as drift, and the Architect treats it as a request.

## Neutral operations

The adapter implements these operations. The JSON produced by `sync --json` lists exactly which ones to execute.

| Operation | Input | Effect on the board |
|---|---|---|
| `create_item` | title `[SPEC-NNNN] title`, issue_type, parent, labels, status, spec_path | create the item, link the spec file, then record it: `set SPEC-NNNN external=[<provider>:<key>]` |
| `transition` | ref, to | move the item to the mapped status/column |
| `link` | from, to, type `blocks` | dependency: `from` blocks `to` |
| `set_blocked` / `clear_blocked` | ref, label, comment | add/remove the blocked label (plus a comment with the impediment) |
| `comment` | ref, markdown | event comments (below) |
| `read_item` | ref | intake: summary, description, acceptance criteria, comments |
| `snapshot` | project, labels | dump the board in the neutral format below (for `sync --board`) |
| `missing_on_board` / `orphan` | ref | report to the human: item deleted on the board, or SDD-labeled item without a spec |

## Sync points (Architect, right after the event)

| Event | Operations |
|---|---|
| `new` (spec or epic created) | `create_item` (epic first, so children get the parent) |
| `depends_on` declared | `link` |
| H1 approved, dispatched, implemented, deprecated (`set status=...`) | `transition` |
| `impede` / `resolve` | `set_blocked` + comment / `clear_blocked` + comment with the resolution |
| G5 + H2, G6 | `comment` with the evidence (CI run, deployed version) |
| G7 / `implemented` | `transition` + `comment` with the output of `report SPEC-NNNN` |

At the end of every wave, and in CI if desired: produce a snapshot and run `sync --board snapshot.json --check` — it exits 1 on any drift.

Creating, editing or commenting on board items is visible to other people: do it only with the user's confirmation or a standing authorization written in the project's root docs.

## Capabilities by tool

Fidelity is not the same everywhere: the adapter declares what the tool supports and degrades explicitly — never pretends.

| Tool | Hierarchy (epic → spec) | Dependency link | Custom statuses | Item types | Labels | Access | Validated against a real board |
|---|---|---|---|---|---|---|---|
| Repository only (`none`) | `parent` in frontmatter | `depends_on` | 5 SDD statuses | tier/type | — | files | yes (default) |
| Jira (`jira.md`) | Epic / parent | "Blocks" link | workflow (admin) | issue types (admin) | yes | MCP, CLI, REST | **no** |
| GitHub (`github.md`) | sub-issues / task list | dependencies / "Blocked by" text | labels or Project field | labels / issue types | yes | `gh`, MCP | **no** |
| Linear (`linear.md`) | parent / sub-issues | "blocks" relation | team workflow states | labels | yes | API, MCP | **no** |
| Azure Boards (`azure-boards.md`) | parent/child links | predecessor/successor links | process states | work item types | tags | `az boards`, REST | **no** |
| Trello (`trello.md`) | checklist on the epic card | text in card + checklist (degraded) | lists | labels | yes | REST, Power-Ups | **no** |

Before the first real use of an adapter, run it with the user watching and record what differed in the adapter's guide.

## Preparing a new board (bootstrap)

1. `spec_graph.py sync --structure` prints what the board must have, in neutral terms: the statuses and item types mapped in `tracker`, the labels (SDD + blocked) and the relations (parent, blocks).
2. The adapter checks access and permissions, then **proposes** the plan to the user: create what the tool lets it create (labels, lists, fields) and, where it needs an administrator (e.g. Jira workflows and issue types), map the existing ones instead and ask the user to confirm the mapping in `sdd-config.yml`.
3. After the user's confirmation it creates the structure, creates one test item and removes it, and records the result.
4. From then on, snapshots include a `structure` block and `sync --board snapshot.json --check` reports missing statuses, item types or labels as well as item drift.

## Neutral snapshot format

```json
{
  "structure": { "statuses": ["To Do", "In Progress", "Done"], "issue_types": ["Epic", "Story", "Bug"], "labels": ["sdd"] },
  "items": [
    { "ref": "jira:PAY-123", "status": "In Progress", "blocked": false, "blocks": ["jira:PAY-124"] }
  ]
}
```

`ref` uses the same `provider:key` form as the spec's `external`; `blocks` lists the refs this item blocks. Only items carrying the SDD labels (`tracker.labels`) belong in the snapshot.

## Writing a new adapter

Copy `jira.md` or `github.md` and fill, for the target tool: authentication (never in the repo), how each neutral operation maps to the tool's calls, how to produce the snapshot, and the tool's quirks (workflow transitions, rich-text formats, rate limits). Nothing else in the skill changes.
