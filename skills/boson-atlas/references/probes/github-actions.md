# Adaptador de probe `github-actions`

Adaptador da capacidade `pipeline` do contrato `probe@2` (`references/probes.md`, SPEC-0096, ADR-0025). Vem com a skill em `assets/probes/github-actions.py` (só biblioteca padrão, Python 3.9 ou mais novo) e responde: **quais execuções da CI rodaram para este commit nos repositórios de código do serviço, e como terminaram?** Usa o `gh` já autenticado da máquina, **só em GET** (SPEC-0106). Nunca aprova, re-roda, cancela nem dispara workflow.

| Verbo | Alvo | Entrada | Pergunta | Itens |
|---|---|---|---|---|
| `runs` | `deployment` | `change` | As execuções do commit em cada repositório de código | um por execução |

É a primeira etapa do `verify track` (`references/verify.md`), que lê o `pipeline runs` uma vez por chamada.

## Configurar

1. Instale o `gh` e faça o login (`gh auth login`) com uma conta que leia as Actions dos repositórios de código, ou declare um token **só de leitura** por nome em `GH_TOKEN` (a skill nunca guarda o valor, ADR-0010).
2. Ligue as probes e declare o adaptador no `config.yml` **desta máquina** (nunca no `atlas-config.yml`):

```yaml
probes:
  enabled: true
  adapters:
    github-actions:          # sem command: vale assets/probes/github-actions.py da skill
      verbs: [runs]
      timeout: 120
      credentials: [GH_TOKEN]   # opcional: só o nome; sem ele vale o login do gh
```

3. Rode `atlas.py doctor` e depois uma probe de teste (o sha completo do commit):

```bash
python3 <skill-dir>/scripts/atlas.py probe pipeline runs --service api --env dev --commit 0a1b2c3d4e5f60718293a4b5c6d7e8f901234567
```

- **Repositórios:** o núcleo monta `target.change.repositories` só com os `delivery.code_repositories` do serviço (SPEC-0086); um serviço sem repositório de código no atlas não tem o que ler (`--commit` dá exit 2 no `probe`; no `verify track` a etapa fica `not_verified`).
- **Acesso:** `access: []` (ADR-0025, regra 4): o adaptador não usa acesso local do atlas, só o `gh` autenticado ou o `GH_TOKEN` declarado.
- **Tempo:** cada `gh` tem 30 s; com até 10 repositórios, um `timeout` de 120 s no adaptador sobra.

### Permissão mínima sugerida

Um token fine-grained só com **Actions: Read** (e **Metadata: Read**, obrigatório) nos repositórios de código; nada de escrita. Com o `gh auth login`, a conta precisa só ler as Actions desses repositórios.

## O que é lido

Uma chamada por repositório (até 10, na ordem da entrada), como lista de argumentos, sem shell e com o stdin fechado:

```text
gh api -X GET repos/<dono>/<repo>/actions/runs -f head_sha=<commit> -f per_page=100
```

- Recusado **antes** de chamar o `gh`: verbo fora de `runs` (`chamada não permitida`); stdin que não é `probe@2` da capacidade `pipeline`, sem `target.change`, commit fora de `^[0-9a-f]{40}$`, lista de repositórios vazia, repositório fora de `^[a-z0-9_.-]+/[a-z0-9_.-]+$`, com uma parte começando com `-` ou `.`, ou com `..` (`entrada inválida`).
- **Nunca:** outro caminho ou método, `--paginate`, `--input`, `workflow`, `run`, `rerun`, `cancel`, `dispatch`.
- O `gh` recebe só o ambiente que o núcleo dá ao adaptador (`GH_TOKEN` só quando declarado em `credentials`), mais `GH_PROMPT_DISABLED=1`.
- De cada execução saem só os campos da tabela abaixo: **nunca** `display_title` (a mensagem do commit), `head_commit`, `actor`, `triggering_actor`, `head_branch` nem `pull_requests`.

## Saída

Um item por execução, ordenados por repositório e início:

| Campo | De onde vem |
|---|---|
| `repository` | o repositório da entrada |
| `found` | `true` (o repositório respondeu) |
| `workflow`, `path`, `event` | `name`, `path` e `event` da execução |
| `status` | o da API (`queued`, `in_progress`, `completed`, `waiting`, `requested`, `pending`) |
| `conclusion` | o da API quando `completed`; `""` enquanto não terminou |
| `attempt` | `run_attempt` |
| `started_at` | `run_started_at` |
| `duration_seconds` | `updated_at - run_started_at`, só quando `completed`; senão `null` |
| `url` | `html_url` só com esquema, host e caminho (sem usuário, query nem fragmento) |

- Repositório sem acesso ou inexistente (HTTP 404): `{"repository": "acme/x", "found": false}`; os outros seguem.
- `truncated: true` quando o `total_count` passa das execuções devolvidas (mais de 100), quando há mais itens que `limits.lines` ou quando a entrada tem mais de 10 repositórios.

```json probe@2 describe valid
{"contract": "probe@2", "adapter": "github-actions", "capabilities": {"pipeline": {"verbs": ["runs"], "targets": ["deployment"], "access": [], "inputs": ["change"]}}}
```

```json probe@2 input valid
{"contract": "probe@2", "capability": "pipeline", "verb": "runs", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "change": {"commit": "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567", "repositories": ["acme/api"]}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "github-actions", "capability": "pipeline", "verb": "runs", "status": "ok", "items": [{"repository": "acme/api", "found": true, "workflow": "Build", "path": ".github/workflows/build.yml", "event": "push", "status": "completed", "conclusion": "success", "attempt": 1, "started_at": "2026-11-24T10:00:00Z", "duration_seconds": 312, "url": "https://github.com/acme/api/actions/runs/1001"}, {"repository": "acme/x", "found": false}], "truncated": false}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "github-actions", "capability": "pipeline", "verb": "runs", "status": "error", "items": [], "truncated": false, "message": "limite de requisições do GitHub"}
```

Inválida (o autor da execução é um objeto aninhado e nunca sai):

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "github-actions", "capability": "pipeline", "verb": "runs", "status": "ok", "items": [{"repository": "acme/api", "found": true, "author": {"login": "pessoa"}}], "truncated": false}
```

Inválida (`change` sem a lista de repositórios):

```json probe@2 input invalid
{"contract": "probe@2", "capability": "pipeline", "verb": "runs", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "change": {"commit": "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567"}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

## Erros

Saem com exit 0, `status: "error"`, `items: []` e uma destas mensagens fixas, nunca o stderr do `gh` (que pode citar o token). Um erro em qualquer repositório derruba a execução inteira; só o 404 vira item `found: false`.

| Mensagem | Quando |
|---|---|
| `gh não encontrado` | o `gh` não está no `PATH` |
| `sem autenticação no GitHub` | HTTP 401 ou `gh` sem login |
| `sem permissão (403)` | HTTP 403 que não é de limite |
| `limite de requisições do GitHub` | HTTP 403 ou 429 de limite de requisições |
| `timeout` | o processo passou de 30 s ou a rede esgotou o tempo |
| `resposta inválida do gh` | a resposta não é o JSON esperado, ou outra falha do `gh` |
| `chamada não permitida` | verbo fora de `runs` |
| `entrada inválida` | entrada fora das regras acima |

O núcleo (`atlas.py probe`) valida a saída, aplica a máscara (valores declarados em `credentials` mascarados literalmente) e grava uma linha em `probes.log` com o `commit` (SPEC-0096).
