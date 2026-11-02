# Collector `github`

Category `code`. Reads, through the `gh` CLI already authenticated on the machine, the repositories of a GitHub organization, their Actions workflows, the teams in CODEOWNERS and a sample of pull requests, and prints the `org-atlas/collector@1` output (`references/collector-contract.md`, ADR-0011). The PR sample becomes signals for curation (title and branch patterns); the repository settings give the allowed merge methods and whether a PR template exists.

## Setup

1. Install `gh` (<https://cli.github.com>) and run `gh auth login`, or export `GH_TOKEN` (declare its name in `credentials` of the local config, never the value).
2. Use a **read-only** token: a fine-grained token with read access to *Metadata*, *Contents*, *Pull requests* and *Actions* on the organization's repositories (or a classic token with `repo` + `read:org`). The collector never reads or prints the token; `gh` handles it.
3. Declare it in `atlas-config.yml`:

```yaml
collectors:
  - id: github
    category: code
    command: ["python3", "{skill}/assets/collectors/github.py", "--org", "acme"]
    timeout: 600
```

## Options

| Option | Default | Meaning |
|---|---|---|
| `--org ORG` | required | the GitHub organization |
| `--repos a,b` | all | only these repositories (and their pipelines, owner teams and signals); an unknown name is a warning |
| `--pr-sample N` | 100 | the N most recent PRs (all states) read per repository |
| `--input FOLDER` | — | read recorded responses instead of calling `gh` (tests, or running without access) |

## `gh` calls

All are `gh api` (GET), read with the standard library (no `--jq`), argv lists without a shell, 120 s timeout each.

| Call | Used for |
|---|---|
| `orgs/<org>/repos?per_page=100` (`--paginate`) | repositories |
| `repos/<org>/<repo>` | `allow_merge_commit`, `allow_squash_merge`, `allow_rebase_merge` |
| `repos/<org>/<repo>/actions/workflows?per_page=100` (`--paginate`) | pipelines |
| `repos/<org>/<repo>/contents/<path>` for `.github/CODEOWNERS`, `CODEOWNERS`, `docs/CODEOWNERS` (first found) | owner teams |
| `repos/<org>/<repo>/pulls?state=all&per_page=..&page=..` | PR sample; only the pages needed for N are fetched |
| `repos/<org>/<repo>/contents[/.github\|/docs]` (folder listings) | PR template presence |

A 404 on a per-repository resource means "absent" (no workflows, no CODEOWNERS, no template). Cost per repository: about 6 to 9 calls plus one per 100 PRs.

## Output

| Entity | Attributes |
|---|---|
| `repository:<org>/<name>` | `language`, `default_branch`, `topics`, `archived`, `visibility` |
| `pipeline:<org>/<repo>/<workflow file without .yml/.yaml>` (name = workflow name) | `file` |
| `team:<org>/<team>` (once, from `@org/team` in CODEOWNERS; users and e-mails are ignored) | none |

Relations: `pipeline → repository` (`builds`), `team → repository` (`owns`). Workflows without a file (`dynamic/...`, such as Pages) are skipped.

Signals, one of each per repository:

- `{type: "pr-titles", repository, total, pattern_counts: {conventional, ticket_key, other}, sample}` — each title counts once: Conventional Commits (`type(scope)!: ...`) first, then a ticket key (`ABC-123` anywhere), else `other`; `sample` has at most 10 titles (the most recent).
- `{type: "branch-prefixes", repository, total, counts: {"feat/": n, ...}}` — prefix = first segment of the head branch plus `/`; a branch without `/` counts in `total` only.
- `{type: "merge-methods", repository, present: {merge, squash, rebase}}` — the repository's allowed merge methods. When the response lacks the `allow_*` fields (GitHub shows them only to tokens with enough access to the repository) the signal is left out and a warning naming `<org>/<repo>` goes to stderr; the exit stays 0.
- `{type: "pr-template", repository, present: {pr_template}}` — `pull_request_template.md` (any case) or a `PULL_REQUEST_TEMPLATE/` folder in `.github/`, the root or `docs/`.

Never collected: author logins, PR bodies, code contents, issues. PR titles may name people or customers, so only the 10-title sample leaves the collector, and the `scan` redacts it.

## `--input` layout

```text
FOLDER/
  repos.json              # response of orgs/<org>/repos (one list)
  repo/<repo>.json        # response of repos/<org>/<repo>
  workflows/<repo>.json   # response of actions/workflows ({"workflows": [...]})
  codeowners/<repo>       # CODEOWNERS text
  pulls/<repo>.json       # response of pulls (a list, newest first)
  pr-template/<repo>      # exists = the repository has a PR template
```

Only `repos.json` is required; a missing file means "absent" (a missing `repo/<repo>.json` omits `merge-methods` with the warning). With `--input` the collector never calls `gh`.

## Failure modes (exit 1, message on stderr, nothing on stdout)

| Message | When |
|---|---|
| `gh não encontrado — instale e autentique (references/collectors/github.md)` | `gh` is not on the `PATH` |
| `gh sem acesso à organização ORG` | `gh` has no login, the token is invalid, or the organization denies access (401/403) |
| `organização não encontrada: ORG` | `orgs/<org>/repos` answers 404 |
| `gh api <path> falhou (HTTP <status>)` | any other failed call (rate limit, server error) |
| `gh api <path>: tempo esgotado (120 s)` | one call took longer than the timeout |
| `--input: repos.json não encontrado em FOLDER` | `--input` without `repos.json` |

## Limits

- Large organizations: the target is about 300 repositories with `--pr-sample 200` within 5 minutes of `gh` calls (not yet measured on a real organization); raise the collector `timeout` accordingly and use `--repos` to narrow it.
- Calls count against the token's rate limit (5,000 requests/hour for a user token).
- Only GitHub; GitLab and other providers come as separate collectors.
