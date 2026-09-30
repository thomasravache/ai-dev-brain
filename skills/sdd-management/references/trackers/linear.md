# Adapter: Linear

**Status: not validated against a real workspace.** Refs use `linear:<TEAM-123>`.

## Access (never stored in the repo)
A Linear MCP server connected to the session or the GraphQL API with the user's key from the environment. Without either: `impede --type externo`.

## Configuration
`tracker.provider: linear`, `tracker.project: <team key>`. `statuses` map to the team's **workflow states** (names as shown in the team settings); `issue_types` map to labels (Linear has no issue types), e.g. `feature: "tipo: feature"`.

## Operations
| Neutral | Linear |
|---|---|
| `create_item` | create issue in the team with title `[SPEC-NNNN] title`, labels, state; epic children as **sub-issues** of the epic issue (or grouped in a Linear project) |
| `transition` | set the issue's workflow state to the mapped name |
| `link` | issue relation "blocks" from the dependency to the dependent |
| `set_blocked` / `clear_blocked` | add/remove the blocked label + comment |
| `comment` / `read_item` / `snapshot` | comment; read issue; list issues with the SDD label → neutral format |

## Bootstrap
Workflow states and labels are team settings: create the labels, map states to existing ones (or ask an admin to add them), confirm with the user.
