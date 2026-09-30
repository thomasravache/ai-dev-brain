# Adapter: Trello

**Status: not validated against a real board.** Refs use `trello:<cardShortLink>`. Trello has no item types or native dependencies — this adapter degrades explicitly.

## Access (never stored in the repo)
REST API key and token from the user's environment, or a Trello MCP server.

## Configuration
`statuses` map to **list names** (one list per SDD status). `issue_types` map to labels. `tracker.project` is the board id.

## Operations
| Neutral | Trello |
|---|---|
| `create_item` | card `[SPEC-NNNN] title` in the list of its status, with labels; the epic card gets a checklist with one item per child (link to the child card) |
| `transition` | move the card to the mapped list |
| `link` | **degraded:** line "Bloqueado por: <card>" in the description + a checklist "Dependências" |
| `set_blocked` / `clear_blocked` | blocked label + comment |
| `snapshot` | cards with the SDD label → neutral format (`blocks` read from the description lines) |

## Bootstrap
Create the lists and labels (allowed through the API), after showing the plan to the user.
