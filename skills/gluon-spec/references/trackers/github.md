# Adapter: GitHub Issues / Projects

Implements the neutral operations of `README.md` for GitHub. Refs use the form `github:<owner>/<repo>#<number>` (e.g. `github:acme/shop#42`).

## Access (never stored in the repo)

The GitHub CLI `gh`, already authenticated (`gh auth status`), or a GitHub MCP server. Without either, record `impede --type externo --reason "sem acesso ao GitHub" --owner usuário`.

## Configuration (`docs/specs/sdd-config.yml`)

```yaml
tracker:
  provider: github
  project: acme/shop
  mode: push+intake
  labels: [sdd]
  blocked_label: sdd-bloqueado
  statuses:                    # labels (default) — or Project v2 "Status" option names
    proposed: "status: proposta"
    approved: "status: aprovada"
    in-progress: "status: em andamento"
    implemented: "status: concluída"
    deprecated: "status: cancelada"
  issue_types:                 # labels (or native issue types, where the organization enables them)
    epic: "tipo: épico"
    feature: "tipo: feature"
    fix: "tipo: bug"
    refactor: "tipo: refactor"
    migration: "tipo: migração"
    foundation: "tipo: fundação"
```

If the team tracks status in a **Project (v2)** board, map `statuses` to the Project's "Status" option names and use `gh project item-edit` for `transition`.

## Operations

| Neutral | GitHub |
|---|---|
| `create_item` | `gh issue create -R <owner/repo> --title "[SPEC-NNNN] title" --body-file <summary.md> --label sdd,SPEC-NNNN,<type label>,<status label>`. Epic children: add as **sub-issues** of the epic issue (GitHub API) or, where unavailable, list them as a task list in the epic body. Then `set SPEC-NNNN external=[github:<owner/repo>#<n>]`. |
| `transition` | Labels: remove the old `status:` label and add the new one (`gh issue edit --remove-label ... --add-label ...`); `implemented` also closes the issue (`gh issue close --reason completed`), `deprecated` closes as not planned. Project v2: `gh project item-edit` on the Status field. |
| `link` | Native issue dependencies ("blocked by") where available; otherwise a line `Blocked by #<n>` in the dependent issue's body. |
| `set_blocked` / `clear_blocked` | Add/remove `blocked_label` + `gh issue comment` with the impediment. |
| `comment` | `gh issue comment <n> --body-file <file>` (GitHub-flavored Markdown). |
| `read_item` | `gh issue view <n> --json title,body,labels,comments`. |
| `snapshot` | `gh issue list -R <owner/repo> --label sdd --state all --json number,labels,state` → neutral: `status` = the `status:` label (or Project field), `blocked` = `blocked_label` present, `blocks` from dependencies/body references. |

## Pull requests

The PR body from `pr` ends with `Refs: SPEC-NNNN, <owner/repo>#<n>`. To auto-close the issue on merge, the Integrator adds `Closes #<n>` **only** in the PR that completes the spec (G7), never in partial PRs.
