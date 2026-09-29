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

## Neutral snapshot format

```json
{
  "items": [
    { "ref": "jira:PAY-123", "status": "In Progress", "blocked": false, "blocks": ["jira:PAY-124"] }
  ]
}
```

`ref` uses the same `provider:key` form as the spec's `external`; `blocks` lists the refs this item blocks. Only items carrying the SDD labels (`tracker.labels`) belong in the snapshot.

## Writing a new adapter

Copy `jira.md` or `github.md` and fill, for the target tool: authentication (never in the repo), how each neutral operation maps to the tool's calls, how to produce the snapshot, and the tool's quirks (workflow transitions, rich-text formats, rate limits). Nothing else in the skill changes.
