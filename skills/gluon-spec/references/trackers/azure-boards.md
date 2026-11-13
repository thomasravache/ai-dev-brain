# Adapter: Azure Boards

**Status: not validated against a real organization.** Refs use `azure:<project>#<id>`.

## Access (never stored in the repo)
`az boards` (Azure DevOps CLI extension) authenticated, or the REST API with a token from the environment.

## Configuration
`statuses` map to the **process** states (e.g. Agile: New, Active, Resolved, Closed; Scrum: New, Approved, Committed, Done). `issue_types` map to work item types of the process (e.g. Epic, Feature, User Story or Product Backlog Item, Bug, Task).

## Operations
| Neutral | Azure Boards |
|---|---|
| `create_item` | `az boards work-item create --type <type> --title "[SPEC-NNNN] title"`, tags `sdd; SPEC-NNNN`; child of the epic via a parent link |
| `transition` | update `System.State` to the mapped state |
| `link` | predecessor/successor link (dependency → dependent) |
| `set_blocked` / `clear_blocked` | tag + discussion comment (or the "Blocked" field when the process has it) |
| `snapshot` | WIQL query on tag `sdd` → neutral format |

## Bootstrap
States and types come from the process (inherited process edits need an admin): map to existing ones and confirm with the user; create tags freely.
