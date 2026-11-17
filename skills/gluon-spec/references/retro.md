# Retrospective across projects (`retro`)

`retro` reads the projects built with SDD and shows what the process is actually following and what it is not: numbers per project, findings with the command that fixes them, and suggestions of specs for the skill itself. It **only reads** — it never changes a project, never runs `vendor` or `upgrade` for them and never creates a spec (ADR-0019). The suggestions are text for a human to turn into specs, or not.

```bash
python3 <skill-dir>/scripts/spec_graph.py retro [PASTA ...] [--registry] [--stale-days N] [--json] [--out ARQUIVO]
```

## Which projects

| Input | What is read |
|---|---|
| `PASTA` with `docs/specs` | the project in full mode |
| `PASTA` registered in private mode | its `spec_root` (found in the registry by the remote or the path, read from the `.git` files) |
| `PASTA` with `sdd-config.yml` and `specs/` | that `spec_root` directly (private) |
| `--registry` | every `spec_root` in the private-mode registry (`SDD_CONFIG_HOME`, default `~/.config/sdd/projects.json`) |
| nothing | the current project |

The same specs folder counts once (a private repository passed as `PASTA` and its registry entry are one project). The project's name is the folder name, or the registry key for private projects.

**Ignored** (exit 0, listed with the reason): a folder without `docs/specs` and without a private-mode entry, a specs folder with no spec, the legacy layout (status folders — run `migrate`), a registry `spec_root` that no longer exists, an unreadable project. A missing `PASTA` is exit 2 (`pasta não encontrada`); nothing to analyse is exit 2 (`nenhum projeto SDD encontrado`, with the ignored list).

## Metrics per project

| Key | Meaning |
|---|---|
| `specs` | total, by status and by tier |
| `tool` | project version (`tools/sdd/spec_graph.py`, else `sdd_version` in the sdd-config; `desconhecida` without either) and the installed one |
| `last_activity` | latest date among `created`, `approved_at` and Gate Register dates |
| `stale` | `approved`/`in-progress` specs whose last activity is **more than** N days old (exactly N does not count) |
| `unclosed` | `approved`/`in-progress` specs with G5 PASS and G7 not PASS |
| `lead_time_days` | median and p90 (nearest rank) of the days from `approved_at` to the G7 PASS date, implemented specs |
| `gates` | current PASS, FAIL and N/A per gate (G0–G7, H2) |
| `fail_history` | FAIL rows of the Gate Register removed in the git history of the specs folder; `null` ("sem git") outside a git repository |
| `evidence` | G0–G5 PASS by evidence origin (below) |
| `na_by_gate` | per gate: N/A and rows with a recorded status (PASS, FAIL or N/A) |
| `amendments` | rows of the Emendas table, total and per spec |
| `impediments` | total, open, and open for more than N days (`SPEC-NNNN/IMP-NN`) |

**Why `fail_history`:** `gate` overwrites the row, so a PASS erases the FAIL before it. The real rigor shows only in git: `git log -p` of the specs folder, counting removed lines (`-`) that are Gate Register rows (first cell starts with a gate) with status FAIL. FAIL rows in other tables (e.g. Verificação) do not count; merge commits show no diff, so nothing is counted twice.

### Evidence origin

Classified by what `gate` itself writes:

| Origin | Rule |
|---|---|
| `gerada` | `gate --run` format: ends with ` — <sha>` (7–40 hex, or `?`), optionally ` (árvore suja)`, **and** starts with `validate: `, `verify G` or `Relatório de Entrega`, or contains `<chave> exit <n> (` |
| `manual` | starts with `MANUAL:` (`gate --manual`) |
| `humana` | starts with `aprovado por` (human gates) |
| `a_mao` | everything else, including free text that ends with a SHA |

## Rules (fixed in this version)

N = `--stale-days` (integer >= 1, default 30). The other limits are fixed; changing them is an amendment to SPEC-0074.

| Rule | Fires when | Action |
|---|---|---|
| R1 ferramenta atrasada | project version < installed, or unknown | `whats-new` and `vendor --force` (private, or no `tools/sdd`: `whats-new --ack`) |
| R2 spec parada | `stale` not empty | resume, close or mark `deprecated` |
| R3 entregue sem fechar | `unclosed` not empty | close G7 (Relatório de Entrega): `gate <ID> G7 --run` |
| R4 evidência à mão | (manual + a_mao) / G0–G5 PASS **> 30%**, with **>= 10** PASS | `gate <ID> <G> --run`; review the sdd-config commands |
| R5 nenhuma reprovação | **>= 20** PASS in G1–G5 and `fail_history` = 0 (`null` never fires) | check that gates run with `--run` and that failures are recorded with `gate --fail` |
| R6 N/A recorrente | per gate: N/A in **>= 50%** of the specs that record it, at least **5** | waiver in `pillars.waived` or the spec of the missing capability |
| R7 impedimento velho | open for more than N days | solve it and close with `resolve` |

## What to adjust in the skill

A rule that fires in **>= 50%** of the analysed projects, and in **at least 2**, becomes one line with a spec suggestion for the skill — text only, from this fixed table (mirrored by `RETRO_SUGGESTIONS` in `spec_graph.py`):

| Rule | Suggested spec |
|---|---|
| R1 | gluon-spec: avisar a ferramenta atrasada no status e no hook, com o comando de atualização |
| R2 | gluon-spec: revisão periódica das specs paradas (retomar, fechar ou deprecated) |
| R3 | gluon-spec: lembrar o fechamento do G7 depois do merge (G5 PASS sem G7) |
| R4 | gluon-spec: reduzir a evidência à mão (comandos do sdd-config prontos e `gate --run` como caminho padrão) |
| R5 | gluon-spec: guardar o histórico de FAIL no Registro de Gates (o PASS hoje apaga o FAIL) |
| R6 | gluon-spec: tratar o N/A recorrente (dispensa de pilar sugerida ou spec da capacidade que falta) |
| R7 | gluon-spec: aviso de impedimento aberto há muito tempo no status |

## Output

- **Markdown** (default): Resumo | Projetos (table) | N/A por gate | Achados | O que ajustar na skill | Ignorados.
- **JSON** (`--json`): `{"retro_version": 1, "generated_at", "installed_tool", "stale_days", "projects": [...], "findings": [{"rule", "project", "value", "action"}], "skill_suggestions": [{"rule", "projects", "suggestion"}], "ignored": [{"path", "reason"}]}`. `retro_version` changes when the format does.
- `--out ARQUIVO` writes the output to that file — the only file the command ever writes.

## Read-only and privacy

- Git runs only as `git log`, with `GIT_OPTIONAL_LOCKS=0`; the private-mode lookup reads `.git/config` instead of running git. Nothing in the projects is created or changed (no index refresh, no lock).
- Paths come only from the arguments and the registry; there is no disk scan.
- Private projects belong to third parties: the report carries folder names or registry keys, spec IDs and numbers only — **never** titles, evidence, N/A reasons or impediment descriptions. Without `--out`, nothing is saved anywhere.
