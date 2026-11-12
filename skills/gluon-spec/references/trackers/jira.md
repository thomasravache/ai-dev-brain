# Adapter: Jira (Cloud or Data Center)

Implements the neutral operations of `README.md` for Jira. Refs use the form `jira:<ISSUE-KEY>` (e.g. `jira:PAY-123`).

## Access (never stored in the repo)

Use whatever the agent has, in this order:
1. An **Atlassian MCP server** connected to the session (tool names vary by server: create/edit issue, get transitions, transition issue, create issue link, add comment, search with JQL, get issue).
2. The **Jira CLI** of the team (e.g. `jira` / `acli`), already authenticated.
3. The **REST API** (`/rest/api/3` on Cloud, `/rest/api/2` on Data Center) with a token from the user's environment.

If none is available, stop and record `impede --type externo --reason "sem acesso ao Jira" --owner usuário`.

## Configuration (`docs/specs/sdd-config.yml`)

```yaml
tracker:
  provider: jira
  project: PAY
  mode: push+intake
  labels: [sdd]
  blocked_label: sdd-bloqueado
  statuses:
    proposed: "To Do"
    approved: "Selected for Development"
    in-progress: "In Progress"
    implemented: "Done"
    deprecated: "Won't Do"
  issue_types:
    epic: Epic
    feature: Story
    fix: Bug
    refactor: Task
    migration: Story
    foundation: Task
```

Use the **exact status names of the project's workflow** (check an existing issue's transitions once and write them here).

## Operations

| Neutral | Jira |
|---|---|
| `create_item` | Create issue: `project.key`, `issuetype.name` = mapped type, `summary` = `[SPEC-NNNN] title`, `labels` = `tracker.labels` + the spec ID, `parent` = the epic's key (team-managed and newer company-managed projects; older ones use the Epic Link field), description = spec summary + repository path of the spec. Then `set SPEC-NNNN external=[jira:<KEY>]`. |
| `transition` | Jira changes status only through workflow **transitions**: list the issue's available transitions and execute the one whose **target status** equals the mapped name. None available → the workflow requires an intermediate step; walk it or record `impede --type externo`. |
| `link` | Create issue link of type **Blocks**: outward = `from` (the dependency), inward = `to`. |
| `set_blocked` / `clear_blocked` | Add/remove `blocked_label` and comment `🚧 SPEC-NNNN/IMP-NN (tipo → responsável): descrição`. If the team uses the "Flagged" impediment field, set it as well. |
| `comment` | Add comment. REST v3 requires Atlassian Document Format (ADF) for rich text; MCP servers and CLIs usually accept Markdown/wiki markup and convert. Keep comments short and link the spec file. |
| `read_item` | Get issue with summary, description, acceptance criteria (custom field, if any), labels, links and comments. |
| `snapshot` | JQL `project = PAY AND labels = sdd`, fields `status`, `labels`, `issuelinks`. Map to the neutral format: `status` = status name, `blocked` = `blocked_label` in labels, `blocks` = outward "Blocks" links as `jira:<KEY>`. |

## Intake (`mode: push+intake`)

"Implementa o PAY-123":
1. `read_item jira:PAY-123`.
2. `new --tier lite|full` (Bug → lite unless it changes a contract; Story → full), then `set SPEC-NNNN external=[jira:PAY-123]`.
3. Ticket description and acceptance criteria → Motivação, Escopo and Mapa de Comportamentos; everything ambiguous → Questões em Aberto.
4. Comment on the ticket with the spec path and "em especificação (SDD)". Continue the normal flow.

## Quirks

- Required fields on create (components, fix version, custom fields) vary by project: read the create metadata once and add them to the create call; note them in the root docs.
- Rate limits: batch the operations of a `sync` and wait between bursts.
- Mentioning `PAY-123` in the PR title/body (the `pr` command already adds `Refs: PAY-123`) links the PR to the issue when the Jira ↔ Git integration is enabled.
