# Curadoria de convenções — `conventions/<id>.md`

Inferir não é normatizar (ADR-0012). O `atlas.py` **propõe** convenções a partir dos sinais dos coletores (títulos de PR, prefixos de branch, métodos de merge, template de PR) com `status: inferred` e a evidência; só uma **pessoa**, pelo `curate confirm` ou `curate reject`, muda o status. Só convenção `confirmed` vale como regra para outras skills (o pacote de contexto, SPEC-0038, e o `lint`, SPEC-0039, leem este formato).

## Comandos

```bash
python3 <skill-dir>/scripts/atlas.py curate propose [--json]       # também roda no fim de todo scan
python3 <skill-dir>/scripts/atlas.py curate list [--status inferred|confirmed|rejected] [--json]
python3 <skill-dir>/scripts/atlas.py curate confirm ID --by NOME --via "PR #n"|local
python3 <skill-dir>/scripts/atlas.py curate reject  ID --by NOME --via "PR #n"|local [--reason TEXTO]
```

- `propose` lê os sinais dos snapshots dos coletores de `collectors`, cria `conventions/<id>.md` para cada proposta nova e atualiza **só a região `evidence`** das que já existem (qualquer status). Imprime `Convenções: N nova(s), M atualizada(s), K esperando decisão` (K = convenções com `status: inferred`); no `scan` a mesma linha sai depois da linha `Grafo: ...`, e no `scan --json` o relatório vem na chave `curation` (`{"ok", "new", "updated", "waiting", "warnings"}`, ou `{"ok": false, "error"}`).
- `propose` e `scan` **nunca** gravam `confirmed` nem `rejected` e nunca mexem no frontmatter de um arquivo que já existe.
- `confirm` e `reject` são os únicos que gravam a decisão. Saem com 2, sem mudar nada:

| Mensagem | Quando |
|---|---|
| `confirm exige --by e --via` (ou `reject exige --by e --via`) | falta `--by` ou `--via`, ou um deles está vazio |
| `--via aceita 'PR #<n>' ou 'local'` | `--via` fora do formato (`PR #3` e `local` exatamente) |
| `convenção não encontrada: ID` | não existe `conventions/ID.md` |
| `convenção já está <status>` | a convenção já foi confirmada ou rejeitada (decidir de novo = editar o arquivo à mão, num PR) |

**Quem confirma:** no modo `repo`, quem aprova o PR do atlas que traz a convenção (`--via "PR #n"`); no modo `local`, quem roda o `curate` (`--via local`).

## Formato do arquivo (contrato v1)

```markdown
---
id: pr-title-conventional
title: Títulos de PR em Conventional Commits
kind: pr-title
scope: organization
status: inferred
proposed_at: 2026-11-02
confirmed_by:
confirmed_at:
confirmed_via:
reason:
---

# Títulos de PR em Conventional Commits

<!-- atlas:begin evidence -->
- Padrão: `conventional`
- Total: 150 PRs da amostra; seguem o padrão: 105 (70%)
...
<!-- atlas:end evidence -->

## Notas
```

| Chave | Valores | Quem grava |
|---|---|---|
| `id` | o nome do arquivo sem `.md`; inclui o padrão (abaixo) | `propose` |
| `title` | frase curta do padrão | `propose` |
| `kind` | `pr-title`, `branch-prefix`, `merge-method` ou `pr-template` | `propose` |
| `scope` | `organization` ou `repository:<org>/<nome>` | `propose` |
| `status` | `inferred` (proposta), `confirmed` (vale como regra) ou `rejected` (descartada) | `propose` grava só `inferred`; `confirm`/`reject` gravam o resto |
| `proposed_at` | `AAAA-MM-DD` (UTC) da criação | `propose` |
| `confirmed_by` | quem decidiu (`--by`); vazio enquanto `inferred` | `confirm`/`reject` |
| `confirmed_at` | `AAAA-MM-DD` (UTC) da decisão; vazio enquanto `inferred` | `confirm`/`reject` |
| `confirmed_via` | `"PR #n"` ou `"local"`, sempre entre aspas (o `#` seria comentário); vazio enquanto `inferred` | `confirm`/`reject` |
| `reason` | só em `reject`, opcional (`--reason`) | `reject` |

- O frontmatter não tem outras chaves nem comentários.
- A única região gerada é `<!-- atlas:begin evidence -->` … `<!-- atlas:end evidence -->`: total de itens, quantos seguem o padrão, a porcentagem, os repositórios (com a conta de cada um) e, para títulos de PR, uma amostra de até 10 títulos já mascarados pelo `scan`. Nunca guarda autor de PR. A evidência não tem data: com os mesmos sinais o arquivo fica idêntico.
- Todo o resto (o título, o parágrafo de abertura, `## Notas` e o que o time escrever) nunca é reescrito.

## Padrão dominante por kind (contrato v2)

Limiares em `curation` no `atlas-config.yml` (padrões abaixo); os limites são inclusivos (`≥`):

```yaml
curation: {min_share: 0.6, min_total: 20, min_repos: 3}
```

| Chave | Padrão | Uso |
|---|---|---|
| `min_share` | `0.6` | fração mínima (0 a 1) de itens com o padrão |
| `min_total` | `20` | mínimo de itens (PRs ou branches) num repositório para `pr-title` e `branch-prefix` |
| `min_repos` | `3` | mínimo de repositórios com o sinal para `merge-method` e `pr-template` |

**Por itens — `pr-title` e `branch-prefix`:**

| kind | Sinal | Itens | Padrões | id |
|---|---|---|---|---|
| `pr-title` | `pr-titles` | PRs da amostra (`total`) | `conventional`, `ticket_key` ou `other` (`pattern_counts`) | `pr-title-<padrão>` (`ticket_key` → `pr-title-ticket-key`) |
| `branch-prefix` | `branch-prefixes` | branches da amostra (`total`) | cada chave de `counts` (`feat/`, `fix/`…) | `branch-prefix-<prefixo sem />` (`branch-prefix-feat`) |

- Um padrão **domina num repositório** quando `contagem / total ≥ min_share` e `total ≥ min_total`.
- **Escopo:** `organization` quando **mais da metade** dos repositórios com o sinal (todos, inclusive os sem padrão dominante ou com poucos itens) tem o mesmo padrão dominante; a evidência soma os itens de todos eles. Senão, uma convenção por repositório em que o padrão domina, com `scope: repository:<org>/<nome>` e id `<kind>-<padrão>-<org>-<nome>` (`pr-title-conventional-acme-api`).

**Por repositório — `merge-method` e `pr-template`:**

| kind | Sinal | Padrão do repositório | id |
|---|---|---|---|
| `merge-method` | `merge-methods` | o **único** método permitido (`merge`, `squash` ou `rebase`); repositório com mais de um método não conta para nenhum padrão | `merge-method-<método>` |
| `pr-template` | `pr-template` | `pr_template` verdadeiro | `pr-template-present` |

- O padrão domina quando `repositórios com o padrão / repositórios com o sinal ≥ min_share` e `repositórios com o sinal ≥ min_repos`.
- **Escopo sempre `organization`:** um sinal sim/não de um repositório só não vira convenção.

**Sem sinal** para um kind (o coletor não trouxe, ou trouxe menos do que os limiares): nenhuma proposta, sem erro.

## Ciclo de vida

- O id inclui o padrão dominante. Se o padrão muda (por exemplo de `squash` para `merge`), é **outra** convenção, com outro arquivo; a anterior fica como está.
- Uma convenção `rejected` nunca é proposta de novo com o mesmo id (o arquivo já existe), mas a evidência dela continua sendo atualizada a cada `scan`.
- Uma convenção que deixa de ser proposta (o padrão deixou de dominar) não é apagada nem alterada.
- `curate list` mostra `<status> <id> — <título> (<escopo>)` e, para as decididas, quem, quando e por onde; `--json` imprime `{"version", "conventions": [{id, title, kind, scope, status, proposed_at, confirmed_by, confirmed_at, confirmed_via, reason}]}`.
