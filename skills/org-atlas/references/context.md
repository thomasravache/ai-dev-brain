# Pacote de contexto — `atlas.py context`

O `context` é como o atlas chega a quem implementa: para uma tarefa ("feature de cashout no backoffice") ele monta um pacote **só de leitura** com os serviços certos, o que está ligado a eles, as convenções que valem e, no topo, um aviso quando o atlas está velho. Outras skills e o agente chamam este comando em vez de ler o atlas inteiro (SPEC-0038). O `context` nunca grava nada no atlas e nunca roda o `scan`.

## Comando

```bash
python3 <skill-dir>/scripts/atlas.py context QUERY... [--hops 0..2] [--limit N] [--max-chars N] [--json]
```

| Flag | Padrão | Uso |
|---|---|---|
| `QUERY` | — | termos da tarefa (um ou mais); a busca ignora maiúsculas e termos de uma letra |
| `--hops` | `1` | passos no grafo a partir dos serviços encontrados: `0` = só os serviços, `1` = dependências diretas, `2` = dois passos. Fora de `0..2` sai com 2 |
| `--limit` | `8` | máximo de serviços no pacote (os de maior pontuação); menor que 1 sai com 2 |
| `--max-chars` | `30000` | tamanho máximo do pacote em Markdown; o que não cabe vai para "Omitidos". Menor que 1 sai com 2 |
| `--json` | — | o pacote como um objeto JSON (chaves abaixo) |

Exit 0 sempre que o pacote é montado (também quando nada é encontrado e quando o atlas ainda não tem scan); 2 com argumento inválido; 3 sem configuração nesta máquina (rode `init` ou `init --join`).

## O que entra

- **Busca:** cada serviço do `graph.json` ganha pontos por termo encontrado no nome ou no id (10 pelo termo inteiro, 6 por parte dele), nos atributos (3) e nas **notas do time** da página `services/<id>.md` (1; só o texto fora das regiões geradas, sem as linhas fixas do esqueleto). Entram os serviços com pontuação maior que zero, do maior para o menor (empate: pela chave), até `--limit`. Cada um traz a pontuação e o motivo (`nome: backoffice; notas: cashout`).
- **Dependências:** as arestas `depends_on`, `reads`, `writes`, `publishes` e `consumes` (nos dois sentidos: o que o serviço usa e quem usa o serviço) até `--hops` passos, com o tipo, "inferida" quando o `build` inferiu e a evidência (`PAYMENTS_URL=payments`).
- **Convenções** (`conventions/<id>.md`, `references/curation.md`) do escopo `organization` e dos repositórios dos serviços encontrados (os `sourced_from` do serviço no grafo):
  - `confirmed` → **regra** (vale para a tarefa);
  - `inferred` → **dica**, marcada "não confirmada" (não é regra: uma pessoa ainda não decidiu);
  - `rejected` → nunca aparece.
- **Aviso de envelhecimento** a partir de `snapshots/_scan.json` e do `stale_days` do `atlas-config.yml` (padrão 14), só dos coletores declarados em `collectors`:
  - coletor com o último scan `ok` há **mais** de `stale_days` dias (UTC): `Atlas com D dias desde o último scan de: A, B (stale_days: 14)` (uma linha por número de dias, a mais antiga primeiro);
  - coletor cujo último scan falhou: `Último scan falhou: C`.

Quando nada é encontrado, o pacote só tem o aviso (se houver) e a linha fixa `Nada encontrado no atlas para: QUERY`, sem convenções nem dependências. Atlas sem `graph.json` ou sem `snapshots/_scan.json` (nunca rodou `scan`): pacote vazio com o aviso `atlas ainda sem scan — rode scan`.

## Formato em Markdown

Nesta ordem, cada seção só quando tem conteúdo:

```markdown
## Aviso de envelhecimento

- Atlas com 20 dias desde o último scan de: github (stale_days: 14)
- Último scan falhou: argocd

## Serviços

### backoffice (`service:backoffice`)

- Página: services/backoffice.md
- Encontrado por: nome: backoffice; notas: cashout, backoffice (pontuação 12)
- Repositório: acme/backoffice
- Deployments: prod: backoffice-prod
- Donos: pay (acme/pay)
- Visto em: 2026-11-02

## Dependências

- `service:backoffice` → `service:payments` — depends_on, inferida de `PAYMENTS_URL=payments`

## Convenções (regra)

- `pr-title-conventional` — Títulos de PR em Conventional Commits (organization; confirmada por thomas em 2026-11-02 via PR #3; conventions/pr-title-conventional.md)

## Convenções (dica)

- `merge-method-squash` — Merge de PR só por squash (organization; conventions/merge-method-squash.md) — não confirmada

## Omitidos

- dependência `service:payments` → `datastore:payments-db` (depends_on)
```

- `## Aviso de envelhecimento` é sempre a primeira seção quando existe e **nunca** é omitida, nem com `--max-chars` mínimo.
- `## Omitidos`: os itens que não couberam em `--max-chars`, uma linha `- ` por item, até 50; passando disso, uma última linha `… e mais N item(ns) — use termos mais específicos, --hops menor ou --max-chars maior`. O corte mantém o maior prefixo possível na ordem serviços → dependências → regras → dicas, contando a própria seção Omitidos no tamanho.

## Formato em JSON (`--json`)

```json
{"version": "...", "query": "cashout backoffice",
 "warnings": ["Atlas com 20 dias desde o último scan de: github (stale_days: 14)"],
 "services": [{"key": "service:backoffice", "name": "backoffice", "score": 12, "reason": "nome: backoffice; notas: cashout, backoffice",
               "page": "services/backoffice.md", "repositories": ["acme/backoffice"],
               "deployments": [{"id": "backoffice-prod", "environments": ["prod"]}],
               "owners": [{"id": "acme/pay", "name": "pay"}], "attrs": {}, "seen_at": "2026-11-02"}],
 "dependencies": [{"from": "service:backoffice", "to": "service:payments", "type": "depends_on", "inferred": true,
                   "evidence": "PAYMENTS_URL=payments"}],
 "rules": [{"id": "pr-title-conventional", "title": "...", "kind": "pr-title", "scope": "organization", "status": "confirmed",
            "proposed_at": "...", "confirmed_by": "thomas", "confirmed_at": "...", "confirmed_via": "PR #3",
            "path": "conventions/pr-title-conventional.md"}],
 "hints": [{"id": "merge-method-squash", "status": "inferred", "...": "..."}],
 "omitted": ["dependência `service:payments` → `datastore:payments-db` (depends_on)"]}
```

| Chave | Conteúdo |
|---|---|
| `query` | os termos como recebidos |
| `warnings` | linhas do aviso de envelhecimento (lista vazia quando o atlas está em dia) |
| `services` | serviços encontrados, por pontuação: `key`, `name`, `score`, `reason`, `page`, `repositories`, `deployments` (`id`, `environments`), `owners` (`id`, `name`), `attrs`, `seen_at` |
| `dependencies` | arestas até `--hops`: `from`, `to`, `type`, `inferred` e, quando há, `evidence`; ordenadas por (`from`, `type`, `to`) |
| `rules` | convenções `confirmed` do escopo: as chaves do frontmatter (menos `reason`) e `path` |
| `hints` | convenções `inferred` do escopo, no mesmo formato |
| `omitted` | textos dos itens que não couberam em `--max-chars` |
| `message` | só quando nada foi encontrado: `Nada encontrado no atlas para: QUERY` |

## Como outras skills devem chamar

1. Antes de propor, planejar ou implementar algo sobre a organização, rode `atlas.py context "<termos da tarefa>"` (ou `--json` para ler as chaves). Use os nomes de serviço, repositório e domínio da tarefa como termos; `--hops 2` quando a mudança pode afetar quem depende de um banco ou fila.
2. Se o pacote tem `## Aviso de envelhecimento` (`warnings` não vazio), **repasse o aviso ao usuário** antes de decidir e ofereça rodar `scan`; nunca rode o `scan` sozinho.
3. Trate `## Convenções (regra)` (`rules`) como regras do time e cite o arquivo da convenção. Trate `## Convenções (dica)` (`hints`) como sugestão **não confirmada**: pode seguir, mas diga que não é regra e não bloqueie nada por ela.
4. Cite as páginas (`services/<id>.md`, `conventions/<id>.md`) de onde veio cada afirmação.
5. Com `Nada encontrado no atlas para: ...`, diga que o atlas não conhece aquilo; não invente serviços nem dependências.
