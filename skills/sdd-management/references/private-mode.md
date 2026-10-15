# Private mode: SDD outside the team's repository

Use private mode when you work with SDD in a repository shared with a team that has **not** adopted it. The full process stays the same on your side (specs, H1, TDD verified in git, gates with evidence, delivery report), but nothing of SDD reaches the repository. For the team, the result is ordinary code, commits and PRs. In repositories where SDD is part of the repository, nothing changes (full mode).

`status` prints **MODO PRIVADO** on stderr in every command when the mode is on. When you see it, follow this file before any step.

## Activation

```bash
python3 <skill-dir>/scripts/spec_graph.py private init [--spec-root PATH] [--sync none|push]
python3 <skill-dir>/scripts/spec_graph.py private status     # mode, spec_root, sync, pending commits/pushes
python3 <skill-dir>/scripts/spec_graph.py private detect     # re-detect the team's conventions
python3 <skill-dir>/scripts/spec_graph.py private off        # back to full mode; the spec_root is kept
```

- The mode is recorded per repository in the **user registry** `projects.json` (`$SDD_CONFIG_HOME`, else `$XDG_CONFIG_HOME/sdd`, else `~/.config/sdd`), keyed by the normalized `origin` remote (`host/path`) or, without a remote, by the repository path. A new clone of the same remote is found again.
- Default `spec_root`: `<default_root>/<org>/<repo>`; `default_root` comes from the registry, else `$XDG_DATA_HOME/sdd`.
- `init` refuses a repository that already versions `docs/specs` (that one uses full mode) and stops on an unreadable registry instead of falling back to full mode.
- `init` also detects the team's conventions and installs the local leak-check hook when it is safe (see below).

## Where things live

| What | Full mode | Private mode |
|---|---|---|
| Specs, INDEX | `docs/specs/` | `<spec_root>/specs/` |
| ADRs | `docs/adr/` | `<spec_root>/adr/` |
| sdd-config | `docs/specs/sdd-config.yml` | `<spec_root>/sdd-config.yml` |
| History of the records | the repository's git | the `spec_root`'s own git: every command that writes records commits there |
| Sync between machines | the repository's remote | `sync: push` in the registry (default `none`); add a remote to the `spec_root` yourself |

The `spec_root` describes the team's domain. Where it is pushed (if anywhere) is a decision for you and the team: only local is the default.

Commands that only make sense inside the repository refuse to run: `vendor` (no `tools/sdd`, CI job, hooks or AGENTS.md block in the team's repository) and `pr-check`. The board integration stays off.

## Commits and branches

- Write commits in the **team's style** (`team.commits` in the spec_root config: `conventional` or `livre`). No `Refs: SPEC-NNNN`, no spec IDs anywhere in messages.
- Keep red and green apart: a commit touching **only** `test_paths` is red; a commit touching anything else is green. The first green must come after the first red. A commit whose subject contains "scaffold" is contract scaffolding.
- No tags in the code. In the test plan, end each test line with its location: `- **UT-01** — Dado …, quando …, então … → tests/test_soma.py::test_soma`. G1 checks the file at that path contains that name.
- `worktree SPEC-X --create` creates a neutral branch `<type>/<slug>` (e.g. `fix/corrige-soma`) in `<worktree_dir>/<slug>`.
- Code comments, test names, PR text and branch names never mention specs, ADRs, gates or the spec_root.

## Gates in private mode

| Gate | What changes |
|---|---|
| G0, G3 | Same as full mode, reading the spec_root config. |
| G1 | `gate G1 --run` runs the test command **at the last red commit** of the branch (a temporary worktree), so it can be recorded even after green. `--at <sha>` picks the commit explicitly. Traceability uses `→ caminho::nome`. |
| G2 | Same commands as full mode. |
| G1–G5 | Each `gate --run` records the branch's commits in the spec's **Commits** section (role, SHA, `patch-id`, files). |
| G4, G5 | Also run the leak-check over the branch; any finding fails the gate. |
| G5 | Also runs the `ci` command (e.g. the platform CLI that reads the PR checks) — the team's CI is the evidence. |
| G6 | The team's deploy: usually N/A with the `entrega` pillar waived in the spec_root config. |
| G7 | Besides the delivery report, finds where the spec landed on `base_branch`: merge commit, **squash** (branch `patch-id`) or **rebase** (each commit's `patch-id`). |

H1, H2 and production releases still come only from you, in the chat.

## Leak-check

```bash
spec_graph.py leak-check                     # staged diff + current branch + base..HEAD
spec_graph.py leak-check --range A..B        # commits (messages and added lines); A = 000… → commits not on any remote
spec_graph.py leak-check --message FILE      # a commit message or PR body
spec_graph.py leak-check --branch NAME
```

It finds spec IDs (`SPEC-NNNN`), test tags (`SPEC-NNNN:UT-01`), IDs of **your** ADRs (ADRs of the team are not leaks), SDD section titles, `sdd-config` and the spec_root path. Add your own patterns (e.g. internal code names) with `leak_patterns`, and silence legitimate matches with `leak_allow` (tested against the line) in the spec_root config.

- `private init` installs a local, unversioned `pre-push` hook that runs it on every push — only when the team has no hook manager (`core.hooksPath`, husky, lefthook, pre-commit) and no `pre-push` of its own. Otherwise it says so, and the leak-check still runs inside `worktree`, `gate` G4/G5 and `pr`.
- `pr` in private mode builds the title in the team's style and fills the team's PR template by section title (summary, how to test, risks); without a template, a neutral body ("O que muda", "Como testar", "Riscos e rollback"). It refuses to write a title or body with marks.

## Limits

- No SDD control outside the model: there is no required `sdd` job in the team's CI. Private mode is discipline with evidence, protected by the leak-check and the local hook — not a merge block.
- The leak-check knows only the patterns above; anything else is on you (`leak_patterns`).
- A `spec_root` without a remote is lost with the machine; `status` warns about uncommitted and unpushed records.
- Attribution of AI in commits (`Co-Authored-By` and similar) is not touched: follow the agent's configuration and the team's policy.
