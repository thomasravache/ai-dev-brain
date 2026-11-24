---
id: SPEC-0106
title: "boson-atlas: acompanhar a entrega de um commit — pipeline, imagem, GitOps e rollout"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-11-24
parent: SPEC-0095
depends_on: [SPEC-0096]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/assets/probes/github-actions.py, skills/boson-atlas/assets/probes/argocd.py, skills/boson-atlas/references/probes/github-actions.md, skills/boson-atlas/references/probes/argocd.md, skills/boson-atlas/references/verify.md, skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, skills/boson-atlas/tests/test_probe_github_actions.py, skills/boson-atlas/tests/test_probe_argocd.py, skills/boson-atlas/tests/test_verify_track.py, skills/boson-atlas/tests/fixtures/github-actions/**, skills/boson-atlas/tests/fixtures/delivery-track/**, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0022, ADR-0023, ADR-0024, ADR-0025]
external: []
size: M
approved_by:
approved_at:
---

# SPEC-0106 — boson-atlas: acompanhar a entrega de um commit — pipeline, imagem, GitOps e rollout

> **Origem (thomas, 2026-11-24):** "o atlas tem que saber tudo da infra e, se tiver acesso, saber avaliar como uma funcionalidade ou correção está subindo, e auxiliar a gluon-spec quando um PR disparar uma pipe". Hoje o G6 da gluon-spec acompanha a pipeline do merge e a imagem no repositório de configuração por instrução solta (passos 1 e 2 do roteiro da SPEC-0086). Esta spec transforma esses passos num comando só de leitura, com estágio e evidência.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Dado um commit, o `atlas.py verify track` diz **onde a entrega está** no caminho que o atlas conhece (o `delivery` do `context`, SPEC-0086), num ambiente:

1. **`pipeline`** — as execuções da CI para o commit nos repositórios de código do serviço;
2. **`image`** — a imagem do commit aparece na Application do GitOps do deployment;
3. **`gitops`** — a Application sincronizou e está saudável com essa imagem;
4. **`rollout`** — os pods do workload rodam a imagem e o rollout terminou (o `runtime status` que já existe).

Cada etapa sai como `pending`, `running`, `ok`, `failed` ou `not_verified`, com evidência. O exit diz se a entrega chegou (0), falhou (1), ficou sem prova (5) ou **ainda não chegou** (6, repita depois da janela). Tudo é só leitura, pelas probes, com as mesmas proteções: o comando nunca aprova, faz merge, re-roda pipeline nem sincroniza, e nada é gravado no atlas.

Dois adaptadores novos `probe@2` vêm com a skill:
- **`github-actions`** (capacidade `pipeline`, verbo `runs`): lê as execuções do commit pela API do GitHub com `gh api` só em GET;
- **`argocd`** (capacidade `gitops`, verbo `application`): lê a Application do Argo CD do deployment com `kubectl get`, sem a CLI do `argocd`.

A SPEC-0105 (G6 da gluon-spec) passa a chamar o `track` depois do merge, no lugar dos passos soltos.

## 2. Motivação & Escopo
**Motivação:** depois do merge, o agente precisa saber se a pipeline do commit passou, se a imagem nova chegou ao GitOps e se o rollout terminou, antes de rodar o `verify compare`. Hoje ele faz isso improvisando chamadas à CI e ao cluster, sem as proteções das probes (verbos permitidos, produção confirmada, máscara, registro). Também não há um jeito determinístico de responder "ainda não chegou, espere" contra "falhou". O atlas já sabe o caminho (repositórios de código e de configuração, pipelines, imagens, deployments, SPEC-0086); falta lê-lo ao vivo, só lendo.

**Objetivos (dentro do escopo):**
- **Adaptador `github-actions`** (`assets/probes/github-actions.py`, só stdlib, Python 3.9+): capacidade `pipeline`, verbo `runs`. Lê as execuções do commit em cada repositório de `target.change.repositories`, com `gh api -X GET`. Devolve status, conclusão, nome e arquivo do workflow, evento, início, duração e a URL da execução sem token.
- **Adaptador `argocd`** (`assets/probes/argocd.py`, só stdlib): capacidade `gitops`, verbo `application`. Lê a Application do deployment com `kubectl get applications.argoproj.io <nome>`. Devolve sync, health, revisão, fase da operação e as imagens em uso (sem o host do registry).
- **`atlas.py verify track`**: encadeia `pipeline runs` → `gitops application` → `runtime status` e devolve o estado de cada etapa, o estado geral, a etapa atual e a imagem esperada, que serve de `--expect-image` para o `verify compare`. Saída `track@1` em `--json`, com um validador `validate_track_result`.
- **Documentação:** `references/probes/github-actions.md`, `references/probes/argocd.md` e a seção `verify track` em `references/verify.md`, com os blocos de contrato lidos pelos testes; `SKILL.md` e CHANGELOG.

**Não-objetivos (fora do escopo):**
- **Qualquer ação:** aprovar PR, fazer merge, re-rodar ou cancelar pipeline, disparar workflow, sincronizar, fazer refresh ou rollback de Application. Nenhum verbo de escrita existe nos adaptadores.
- **Esperar sozinho:** o `track` não tem laço nem `--wait`. Quem chama (a gluon-spec) repete depois da janela; o limite de repetições é da SPEC-0105.
- **Ler o conteúdo do repositório de configuração** (arquivos de values, manifests): pode ter segredo e o caminho do arquivo não está no atlas. A imagem no GitOps é lida da Application.
- **Consultar o registry** de imagens ou os artefatos da CI para descobrir a tag produzida: a imagem vem do `--expect-image` ou da tag que carrega o commit (seção 6).
- **Outras CIs e outros GitOps** (GitLab CI, Jenkins, Flux): entram como adaptadores das capacidades `pipeline` e `gitops`, pelo mesmo contrato.
- **Mudar o `verify compare` ou o `verify snapshot`:** o `compare` já recebe `--expect-image`; o `track` só o entrega pronto.
- **O G6 da gluon-spec:** é da SPEC-0105.

## 3. Dependências
- **Implementações necessárias:** SPEC-0096 — o núcleo `probe@2` (describe com `targets`, `access` e `inputs`, a entrada `target.change` vinda de `--commit`, as credenciais só por nome e o acesso ao cluster por `access.clusters`) precisa estar implementado: o IT-01 e o CT-01 rodam o núcleo e os validadores reais.
- **Contratos consumidos:** N/A — o `probe@2` vem com a implementação da SPEC-0096 (`depends_on`). Do contrato dela esta spec usa: `inputs: ["change"]` no `--describe`; `target.change.commit` (sha completo) e `target.change.repositories` (só os `code_repositories` do `delivery` do serviço, SPEC-0086) na entrada; `access: []` (permitido pelo ADR-0025, regra 4) no `github-actions` e `access: ["cluster"]` com o contexto em `target.context`.
- **Pré-requisitos externos:** `gh` autenticado (ou `GH_TOKEN` declarado por nome) e `kubectl` com acesso de leitura a `applications.argoproj.io`, na máquina que roda o `track`. Nos testes, os dois são dublês no `PATH`.

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **adaptador:** `assets/probes/kubernetes.py` e `references/probes/kubernetes.md` (SPEC-0089): stdlib, lista fechada de chamadas, argv como lista sem shell, erros com mensagem fixa e exit 0;
- **leitura das Applications:** o coletor `assets/collectors/argocd.py` (`--from kubectl`), que já lê só campos escolhidos e normaliza imagens com a regra da SPEC-0082;
- **leitura da API do GitHub:** o coletor `assets/collectors/github.py`, que usa o `gh` já autenticado;
- **verificação:** `verify compare` (SPEC-0090, ADR-0024): probes pelo mesmo caminho do `probe`, `not_verified` com motivo, exits fixos, nada no atlas;
- **núcleo:** `probe@2` (SPEC-0096, ADR-0025).

**Decisão:**
- **Dois adaptadores, duas capacidades** (`pipeline` e `gitops`), no lugar de um adaptador `delivery` com dois verbos. Para cada capacidade vale o primeiro adaptador que a declara (`references/probes.md`); com capacidades separadas, uma máquina pode combinar GitHub Actions com Flux, ou GitLab CI com Argo CD, sem um adaptador que saiba os dois.
- **`verify track`** é uma terceira fase do `verify`, ao lado de `snapshot` e `compare`, e reaproveita o caminho das probes, a normalização de `--expect-image`, a regra de produção e a forma de `checks`. O `runtime status` é o do adaptador da capacidade `runtime` (o `kubernetes` da skill).
- **A imagem do commit** é o `--expect-image` quando dado; senão, a imagem da Application cuja tag carrega o commit (seção 6). Nenhuma consulta ao registry.

**Justificativa:** as proteções ficam num lugar só (núcleo), como manda o ADR-0023; as capacidades separadas mantêm o desenho agnóstico de ferramenta (épico SPEC-0095); e o `track` entrega à gluon-spec um estado determinístico com exit próprio para "ainda não chegou", o que hoje é julgamento do agente.

**Desvio do padrão existente:** nenhum. Os adaptadores seguem o contrato `probe@2` do ADR-0025; o `track` segue as regras do `verify` do ADR-0024 (só leitura, nada no atlas, `not_verified` nunca vira `ok`).

**Alternativas descartadas:**
- **Um adaptador `delivery` com os verbos `pipeline` e `gitops`:** amarra a CI ao GitOps no mesmo executável.
- **CLI do `argocd`:** exige login e servidor próprios e tem verbos de escrita na mesma ferramenta; o `kubectl get` só lê o objeto, com o RBAC de leitura que o coletor já recomenda.
- **Ler a tag produzida nos artefatos ou logs da CI, ou no registry:** não há forma padronizada, os logs podem ter segredo e o registry pede outra credencial.
- **`track` com espera interna (`--wait`):** prende o processo e esconde do agente o que está acontecendo; a repetição fica com quem chama.

**ADRs:** ADR-0010 (credencial só por nome), ADR-0022 (separação código/configuração do `delivery`), ADR-0023 (probes), ADR-0024 (verify), ADR-0025 (`probe@2`).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:**
  - `github-actions`: uma chamada por repositório (`per_page=100`), no máximo 10 repositórios; acima disso, os excedentes ficam fora e a saída vem com `truncated: true`.
  - `argocd`: um `get` por Application.
  - `track`: uma probe `pipeline runs` por serviço, e uma `gitops application` e uma `runtime status` por deployment do ambiente. Medido pelo registro de argv dos dublês no UT-12 e no IT-01.
- **Segurança:**
  - só leitura: `gh api` sempre com `-X GET` e um caminho fixo `repos/<owner>/<repo>/actions/runs`; `kubectl` só `get applications.argoproj.io <nome>`; qualquer outra chamada é recusada antes de executar (UT-04, UT-07, IT-01);
  - argumentos como lista, sem shell; o repositório, o commit, o nome da Application e o namespace são conferidos por regra fechada antes de virarem argumento (nada que comece com `-`, nada de `?`, `&`, `#`, `..`);
  - `GH_TOKEN` e o contexto do cluster só por nome; os valores são mascarados literalmente pelo núcleo em tudo o que sai (UT-14);
  - do Application, só os campos listados na seção 6: nunca `spec.source`, `spec.sources` (valores de Helm, `repoURL` com credencial), anotações nem `status.resources`;
  - da execução da CI, nunca o título (mensagem do commit), o autor nem o branch; a URL sai sem query, sem fragmento e sem usuário;
  - produção só com `--confirm-production`, depois do "sim" da pessoa na conversa (ADR-0023).
- **Privacidade e dados pessoais:** nenhum dado pessoal é pedido; autor e mensagem do commit ficam de fora, e todo texto passa pela redaction das probes.
- **Disponibilidade e resiliência:**
  - cada adaptador com timeout por chamada (`gh` 30 s; `kubectl --request-timeout=20s`, processo 30 s);
  - erro de um adaptador, recusa ou falta de acesso vira `not_verified` na etapa, com o motivo; nunca derruba o `track` nem vira `ok`;
  - repetível: o `track` não guarda estado entre chamadas.
- **Acessibilidade (UI):** N/A — saída de CLI (Markdown ou JSON).
- **Custo:** chamadas à API do GitHub contam no limite da conta (uma por repositório por `track`); o erro de limite vira `not_verified` com a mensagem "limite de requisições do GitHub".

## 6. Artefato A — Contrato
**Interface:** os adaptadores `github-actions` e `argocd` (`probe@2`) e o comando `atlas.py verify track` (`track@1`).

```text
=== Adaptador github-actions (assets/probes/github-actions.py) ===
--describe →
  {"contract": "probe@2", "adapter": "github-actions",
   "capabilities": {"pipeline": {"verbs": ["runs"], "targets": ["deployment"], "access": [], "inputs": ["change"]}}}

entrada: a do probe@2 (SPEC-0096) com target.change = {"commit": "<sha de 40 hexadecimais>", "repositories": ["acme/api"]}
  repositories = só os delivery.code_repositories do serviço (SPEC-0086), montados pelo núcleo
  commit: ^[0-9a-f]{40}$ (já em minúsculas pelo núcleo); repositório: ^[a-z0-9_.-]+/[a-z0-9_.-]+$, cada parte sem começar com "-" ou "."
  e sem ".."; até 10 repositórios (os demais ficam fora, truncated: true); fora da regra → status error "entrada inválida"

chamada permitida (uma por repositório, argv como lista, sem shell, stdin fechado, timeout 30 s):
  gh api -X GET repos/<owner>/<repo>/actions/runs -f head_sha=<commit> -f per_page=100
  qualquer outra (outro caminho, outro método, --paginate, --input, workflow, run, rerun) → recusada antes de executar
  o gh recebe só o ambiente que o núcleo dá ao adaptador: GH_TOKEN só quando declarado em credentials

runs → um item por execução, ordenados por repositório e started_at:
  {"repository": "acme/api", "found": true, "workflow": "Build", "path": ".github/workflows/build.yml",
   "event": "push", "status": "completed", "conclusion": "success", "attempt": 1,
   "started_at": "2026-11-24T10:00:00Z", "duration_seconds": 312,
   "url": "https://github.com/acme/api/actions/runs/1001"}
  status: o da API (queued, in_progress, completed, waiting, requested, pending); conclusion: o da API ou "" enquanto
  não terminou; duration_seconds: updated_at - run_started_at só quando completed, senão null
  repositório sem acesso ou inexistente (404) → {"repository": "acme/x", "found": false}; os outros seguem
  total_count acima dos itens devolvidos ou mais itens que limits.lines → truncated: true
  nunca saem: display_title, head_commit, actor, triggering_actor, head_branch, pull_requests

erros (exit 0, status: "error", items: [], mensagem fixa, sem o stderr do gh):
  "gh não encontrado" | "sem autenticação no GitHub" (401 ou gh sem login) | "sem permissão (403)" |
  "limite de requisições do GitHub" | "timeout" | "resposta inválida do gh" | "chamada não permitida" |
  "entrada inválida"

=== Adaptador argocd (assets/probes/argocd.py) ===
opções do command local (nunca do atlas): --app-namespace <ns> (padrão argocd; DNS-1123 rótulo)
--describe →
  {"contract": "probe@2", "adapter": "argocd",
   "capabilities": {"gitops": {"verbs": ["application"], "targets": ["deployment"], "access": ["cluster"]}}}

alvo: a Application tem o nome do deployment (o id que o coletor argocd grava, SPEC-0082); o contexto é
  target.context; se a variável ATLAS_GITOPS_CONTEXT estiver declarada em credentials e definida, ela vale no lugar
  (Argo CD num cluster de gestão); o valor é mascarado como credencial
chamada permitida (uma, argv como lista, sem shell):
  kubectl get applications.argoproj.io <deployment> -n <app-namespace> -o json --context=<contexto> --request-timeout=20s
  nada de -A, -l, --raw, --kubeconfig, patch, annotate, apply, delete, nem a CLI argocd → recusado antes de executar

application → um item:
  {"application": "dev-api", "found": true, "sync_status": "Synced", "health_status": "Healthy",
   "revision": "4f1c2d…(sha do repositório de configuração)", "operation_phase": "Succeeded",
   "operation_finished_at": "2026-11-24T10:09:00Z", "reconciled_at": "2026-11-24T10:10:00Z",
   "images": ["acme/api:sha-0a1b2c3"]}
  campos lidos: metadata.name, status.sync.status, status.sync.revision (ou o primeiro de status.sync.revisions),
  status.health.status, status.operationState.phase, status.operationState.finishedAt, status.reconciledAt,
  status.summary.images; texto ausente → ""
  images: a regra da SPEC-0082/kubernetes (caminho normalizado + :tag + @digest, sem host do registry; referência fora
  da regra não sai)
  Application inexistente (NotFound) → {"application": "dev-api", "found": false}

erros (exit 0, status: "error", items: [], sem o stderr do kubectl):
  "kubectl não encontrado" | "sem permissão (Forbidden)" | "contexto inexistente" | "timeout" |
  "Argo CD ausente no cluster" (o tipo applications.argoproj.io não existe) | "falha do kubectl" |
  "resposta inválida do kubectl" | "chamada não permitida" | "entrada inválida"

=== atlas.py verify track ===
atlas.py verify track --service <id> --env <ambiente> --commit <sha>
    [--expect-image <imagem>] [--confirm-production] [--json] [--atlas X]

passos, nesta ordem (os mesmos do verify, ADR-0024):
  1. probes desligadas → exit 4, nada roda, nada registrado
  2. --commit: o núcleo normaliza para minúsculas e depois valida ^[0-9a-f]{40}$ (ADR-0025, regra 4); aceita
     maiúsculas na chamada, mas o adaptador e a saída recebem só minúsculas; fora da regra → exit 2
     "commit precisa ser o sha completo (40 hexadecimais)"
     --expect-image sem tag nem digest ou fora da regra → exit 2 (mesma normalização do compare)
  3. serviço sem deployment no ambiente → exit 2 (mesma mensagem do probe)
  4. ambiente sem tier: test e sem --confirm-production → exit 4 antes de qualquer probe
  5. probes, cada uma pelo caminho do probe (verbos, acesso, saída validada e mascarada, uma linha no probes.log):
       pipeline runs  --commit <sha>  (uma vez; alvo = o primeiro deployment do serviço no ambiente)
       gitops application             (por deployment do serviço no ambiente)
       runtime status                 (por deployment; limits.lines = 2000, como no verify)
     probe recusada (sem adaptador, verbo, sem acesso), com erro, que falhou ou cortada → a etapa fica not_verified
     com o motivo; não muda o exit para 4 nem 1

imagem esperada (expected_image):
  --expect-image dado → ele, normalizado (source: "expect-image")
  senão, entre as imagens da Application cujo caminho está em delivery.images do serviço (ou todas, se a lista é
  vazia), a que tem na tag um pedaço (separado por "-", "_" ou ".") que é prefixo do commit com 7 ou mais caracteres,
  ou a tag igual ao commit (source: "commit-tag"); duas imagens diferentes casando → nenhuma ("mais de uma imagem
  com o commit: passe --expect-image")
  casamento com os pods: pelo digest, se a imagem esperada tem; senão pela tag (regra do compare)

etapas (stage) e status:
  pipeline (uma, deployment ""):
    failed      alguma execução completed com conclusion failure, timed_out, cancelled, startup_failure ou action_required
    running     senão, alguma execução com status diferente de completed
    pending     senão, nenhuma execução para o commit ("nenhuma execução da CI para o commit ainda")
    ok          todas completed com success, neutral ou skipped
    not_verified serviço sem repositório de código no atlas; repositório found: false; probe recusada, com erro ou
                cortada (um failed visto nos itens de uma probe cortada continua failed)
  image (por deployment):
    ok          a imagem esperada está nas images da Application
    pending     não está ainda (ou não há imagem esperada e a entrega ainda se move: pipeline não ok, ou Application
                não Synced/Healthy)
    not_verified sem Application (found: false), probe recusada ou com erro; ou sem imagem esperada com pipeline ok e
                Application Synced e Healthy ("imagem do commit não identificada: passe --expect-image"); ou ambígua
  gitops (por deployment):
    failed      health Degraded ou Missing, ou operation_phase Failed ou Error, com a etapa image ok
    running     image ok e (operation_phase Running, health Progressing ou sync OutOfSync)
    ok          image ok, sync Synced e health Healthy
    pending     image pending ("aguardando a imagem no GitOps")
    not_verified image not_verified; health Suspended ou Unknown; Application ausente; probe recusada ou com erro
  rollout (por deployment, do runtime status):
    failed      workload found: false; ou um pod com a imagem esperada não pronto e com restarts > 0
    ok          todos os workloads com rollout_complete e todo pod pronto com a imagem esperada
    running     algum pod com a imagem esperada, rollout não concluído
    pending     nenhum pod com a imagem esperada
    not_verified sem imagem esperada; probe de status recusada, com erro ou cortada ("probe de status cortada")

estado geral (state) e exit:
  failed (exit 1) se alguma etapa failed
  senão running (exit 6) se alguma running; senão pending (exit 6) se alguma pending
  senão not_verified (exit 5) se alguma not_verified
  senão ok (exit 0)
  current_stage: a primeira etapa, na ordem pipeline → image → gitops → rollout (e deployments por id), cujo status
  não é ok; "" quando state é ok
  outros exits: 2 argumento inválido, 3 sem configuração, 4 probes desligadas ou produção sem confirmação

saída --json (track@1), chaves fechadas:
  {"contract": "track@1", "service": "api", "environment": "dev", "commit": "<sha>",
   "state": "running", "current_stage": "gitops",
   "expected_image": "acme/api:sha-0a1b2c3", "expected_image_source": "commit-tag",
   "stages": [{"stage": "pipeline", "deployment": "", "status": "ok", "evidence": {...}, "reason": "..."}, ...]}
  stage ∈ pipeline, image, gitops, rollout; status ∈ pending, running, ok, failed, not_verified; reason obrigatório
  fora de ok; expected_image "" e expected_image_source "" quando não há; evidence só com escalares, listas de
  escalares e, no pipeline, a lista runs de objetos planos (os itens do adaptador)
Markdown (sem --json): o estado, a etapa atual, a imagem esperada e uma tabela etapa | deployment | status | motivo

garantias: nada gravado no atlas nem em arquivo (só as linhas do probes.log); nenhuma ação na CI, no GitOps ou no
  cluster; a saída nunca traz comando; nenhum valor de GH_TOKEN, ATLAS_GITOPS_CONTEXT ou contexto de cluster
uso com o compare: em state ok, o expected_image é o --expect-image do verify compare (sem mudança no compare)
```

Exemplos de contrato que vão para as referências (os testes leem os blocos):

```json probe@2 describe valid
{"contract": "probe@2", "adapter": "github-actions", "capabilities": {"pipeline": {"verbs": ["runs"], "targets": ["deployment"], "access": [], "inputs": ["change"]}}}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "argocd", "capability": "gitops", "verb": "application", "status": "ok", "items": [{"application": "dev-api", "found": true, "sync_status": "Synced", "health_status": "Healthy", "revision": "4f1c2d", "operation_phase": "Succeeded", "operation_finished_at": "2026-11-24T10:09:00Z", "reconciled_at": "2026-11-24T10:10:00Z", "images": ["acme/api:sha-0a1b2c3"]}], "truncated": false}
```

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "argocd", "capability": "gitops", "verb": "application", "status": "ok", "items": [{"application": "dev-api", "source": {"repoURL": "https://github.com/acme/iac"}}], "truncated": false}
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `assets/probes/github-actions.py` e `assets/probes/argocd.py` (novos).
- `references/probes/github-actions.md` e `references/probes/argocd.md` (novas): configuração, permissão mínima (token só com leitura de Actions; ClusterRole só `get` em `applications.argoproj.io`), o que é lido, saída, erros e os blocos `json probe@2 …`.
- `references/verify.md`: a seção `verify track`, os blocos `json track@1 valid|invalid` e o passo do track no "Uso típico".
- `scripts/atlas.py`: a fase `track` do `verify`, `validate_track_result` e o `ATLAS_VERSION`.
- `SKILL.md` (linha do `verify` na tabela de comandos e o passo "Depois do deploy"), CHANGELOG da boson-atlas e `plugin.json`.
- Testes: `test_probe_github_actions.py`, `test_probe_argocd.py`, `test_verify_track.py`, `fixtures/github-actions/` (dublê `fake_gh.py` e respostas) e `fixtures/delivery-track/` (dublê de `kubectl` que responde Applications, workloads e pods por estado, e cenários).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Descrição dos adaptadores | `--describe` | `probe@2` com `pipeline`/`runs` (`inputs: change`) e `gitops`/`application` (`access: cluster`) | CT-01 |
| Execuções da CI | commit com execuções em dois repositórios | um item por execução, sem título, autor nem branch, URL sem query | UT-01 |
| Mais execuções que o limite | `total_count` acima do devolvido ou acima de `lines` | `truncated: true` | UT-02 |
| Repositório sem acesso | 404 num repositório | item `found: false`, os outros seguem | UT-03 |
| Erros do gh | ausente, 401, 403, limite, timeout, resposta inválida | `status: error` com a mensagem fixa, sem stderr nem token | UT-03 |
| Lista fechada do gh | commit curto, repositório com `-`, `..`, `?`; verbo fora | recusado sem chamar o gh; todo argv é `api -X GET repos/…/actions/runs` | UT-04, IT-01 |
| Application lida | Application com sync, health, revisão e imagens | item com os campos do contrato, imagens sem host | UT-05 |
| Cluster de gestão | `ATLAS_GITOPS_CONTEXT` declarado e definido; `--app-namespace` | o contexto e o namespace usados no argv; o valor mascarado | UT-05, UT-14 |
| Application ausente | NotFound | item `found: false` | UT-06 |
| Erros do kubectl | ausente, Forbidden, contexto inexistente, timeout, CRD ausente, resposta inválida | `status: error` com a mensagem fixa | UT-06 |
| Lista fechada do kubectl | nome ou namespace fora do DNS-1123; verbo fora | recusado sem chamar; todo argv começa com `get applications.argoproj.io`; `spec.source` nunca sai | UT-07, IT-01 |
| Etapa pipeline | sem execução, em fila, em andamento, falha, sucesso, repositório sem acesso, sem adaptador | `pending`, `running`, `running`, `failed`, `ok`, `not_verified`, `not_verified` | UT-08 |
| Imagem esperada | `--expect-image`; tag com o commit; duas casando; nenhuma com a entrega parada | `expect-image`; `commit-tag`; `not_verified` ambígua; `not_verified` "passe --expect-image" | UT-09 |
| Etapa image | imagem na Application ou ainda não | `ok` ou `pending` | UT-09 |
| Etapa gitops | Synced/Healthy; OutOfSync, Progressing ou Running; Degraded, Missing ou Failed; imagem pendente; Suspended; ausente | `ok`; `running`; `failed`; `pending`; `not_verified`; `not_verified` | UT-10 |
| Etapa rollout | completo com a imagem; parte dos pods; nenhum; workload ausente; pod novo reiniciando; probe cortada | `ok`; `running`; `pending`; `failed`; `failed`; `not_verified` | UT-11 |
| Estado e exit | combinações das etapas | `failed` 1 > `running`/`pending` 6 > `not_verified` 5 > `ok` 0; `current_stage` = primeira não ok | UT-12, IT-01 |
| Commit inválido | sha curto ou com letra fora de hex | exit 2 com a mensagem fixa, nenhuma probe | UT-13 |
| `--expect-image` inválido | sem tag nem digest | exit 2, nenhuma probe | UT-13 |
| Sem deployment no ambiente | serviço ou ambiente sem deployment | exit 2 | UT-13 |
| Probes desligadas | `probes.enabled: false` | exit 4, nada roda nem é registrado | UT-13 |
| Produção sem confirmação | ambiente sem `tier: test` | exit 4 antes de qualquer chamada | UT-13, IT-02 |
| Sem configuração | sem `config.yml` local | exit 3 | UT-13 |
| Nada gravado, nada vazado | qualquer `track` | árvore do atlas igual; só linhas no `probes.log`; nenhum valor de token ou contexto na saída e no log | UT-14 |
| Saída Markdown | sem `--json` | estado, etapa atual, imagem e tabela; nenhum comando | UT-14 |
| Ponta a ponta até o compare | CI em andamento → imagem no GitOps → rollout pronto | exits 6, 6 e 0; o `expected_image` vira `--expect-image` do `compare` com `passou` | IT-01 |
| Falha da CI | execução com `failure` | `state: failed`, exit 1, sem nenhuma chamada de escrita | IT-02 |
| Contrato do resultado | blocos `track@1` da referência e saídas do `track` | válidos aceitos, inválidos recusados | CT-02 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — `verify snapshot` e `verify compare` não mudam (a foto, as três verificações, o veredito e os exits seguem como hoje e já têm testes próprios); os adaptadores e a fase `track` são novos.

### 7.2 Testes Unitários
- **UT-01** — Dado o `fake_gh.py` com execuções do commit em `acme/api` (Build `completed/success`, Publish `in_progress`) e em `acme/web` (Build `completed/failure`), com `display_title`, `actor` e `head_branch` preenchidos e `html_url` com `?check_suite_focus=true`, quando o adaptador `github-actions` roda `runs`, então sai um item por execução, ordenado por repositório e início, com os campos do contrato, `duration_seconds` só nas terminadas, `conclusion: ""` na em andamento, a URL sem a query e nenhum título, autor ou branch.
- **UT-02** — Dado `total_count: 150` com 100 execuções devolvidas, ou mais execuções que `limits.lines`, quando `runs` roda, então `truncated: true`; com 12 repositórios na entrada, só os 10 primeiros são chamados e `truncated: true`.
- **UT-03** — Dado o `gh` ausente do `PATH`, ou respondendo 401, 403, 403 de limite de requisições, demorando além do timeout ou com JSON inválido, quando `runs` roda, então `status: error` com a mensagem fixa do contrato e sem o stderr do `gh`; com 404 em um dos dois repositórios, sai `{"repository": …, "found": false}` para ele e os itens do outro.
- **UT-04** — O `fake_gh.py` registra cada argv. Em todos os testes do adaptador, todo argv é exatamente `api -X GET repos/<owner>/<repo>/actions/runs -f head_sha=<sha> -f per_page=100`. Uma entrada com commit de 7 caracteres, repositório `-x/api`, `acme/../x`, `acme/api?x=1` ou `acme/api/extra`, ou com verbo diferente de `runs`, é recusada com "entrada inválida" ou "chamada não permitida" sem nenhuma chamada.
- **UT-05** — Dado o dublê de `kubectl` com a Application `dev-api` (Synced, Healthy, `revision`, `operationState.phase: Succeeded`, `summary.images` com `ghcr.io/acme/api:sha-0a1b2c3`), quando o adaptador `argocd` roda `application`, então o item tem os campos do contrato e `images: ["acme/api:sha-0a1b2c3"]`, e o argv é `get applications.argoproj.io dev-api -n argocd -o json --context=<ctx> --request-timeout=20s`. Com `--app-namespace gitops` no command, o argv usa `-n gitops`; com `ATLAS_GITOPS_CONTEXT` declarado em `credentials` e definido, o argv usa esse contexto.
- **UT-06** — Dada a Application inexistente, então sai `{"application": "dev-api", "found": false}`. Dado o `kubectl` ausente, Forbidden, contexto inexistente, timeout, "the server doesn't have a resource type" ou uma resposta em que `status` não é objeto, então `status: error` com a mensagem fixa do contrato, sem traceback e sem o contexto.
- **UT-07** — O dublê registra cada argv. Em todos os testes do adaptador, todo argv começa com `get applications.argoproj.io` e não tem `-A`, `-l`, `--raw` nem `--kubeconfig`. Nome de Application ou `--app-namespace` fora do DNS-1123, ou começando com `-`, e verbo diferente de `application` são recusados sem chamada. A Application da fixture tem `spec.source.helm.values` com `password: s3cr3t` e uma anotação `last-applied-configuration`; nenhum dos dois aparece na saída.
- **UT-08** — Dadas saídas de `pipeline runs` (via adaptador falso de `fixtures/fake-probes/scripted.py`), quando o `track` monta a etapa `pipeline`, então: sem itens → `pending`; um `queued` ou `in_progress` → `running`; um `completed/failure` com outro em andamento → `failed`; todos `success`, `neutral` ou `skipped` → `ok`; um repositório `found: false` sem outra falha → `not_verified`; serviço sem `code_repositories` → `not_verified` "serviço sem repositório de código no atlas"; sem adaptador de `pipeline` → `not_verified` com o motivo da recusa.
- **UT-09** — Dado `--expect-image ghcr.io/acme/api:1.4.2`, então `expected_image` é `acme/api:1.4.2` com `source: expect-image`. Sem ele, dadas imagens da Application `acme/api:sha-0a1b2c3` (commit começando com `0a1b2c3`) e `acme/sidecar:2.0`, então `expected_image: acme/api:sha-0a1b2c3`, `source: commit-tag`; um pedaço de 6 caracteres não casa; `acme/api:sha-0a1b2c3` e `acme/worker:0a1b2c3d` (ambos em `delivery.images`) dão `not_verified` "mais de uma imagem com o commit: passe --expect-image". Sem imagem casando, com a pipeline `ok` e a Application Synced/Healthy → `image` `not_verified` "imagem do commit não identificada: passe --expect-image"; com a pipeline `running` → `pending`. Com a imagem esperada nas imagens da Application → `image` `ok`; sem ela → `pending`.
- **UT-10** — Com a etapa `image` `ok`: Synced/Healthy → `gitops` `ok`; OutOfSync, Progressing ou `operation_phase: Running` → `running`; Degraded, Missing, `Failed` ou `Error` → `failed`; Suspended ou Unknown → `not_verified`. Com `image` `pending` e a Application Synced/Healthy (versão anterior) → `gitops` `pending` "aguardando a imagem no GitOps". Application `found: false`, probe recusada ou com erro → `not_verified` com o motivo.
- **UT-11** — Dadas saídas de `runtime status` com a imagem esperada `acme/api:sha-0a1b2c3`: rollout completo com todos os pods prontos nela → `rollout` `ok`; um pod novo e dois antigos com `rollout_complete: false` → `running`; nenhum pod nela → `pending`; workload `found: false` → `failed`; um pod com a imagem nova não pronto e com `restarts: 3` → `failed` (o pod na evidência); `truncated: true` → `not_verified` "probe de status cortada"; sem imagem esperada → `not_verified`. Com `--expect-image acme/api@sha256:<digest>`, o casamento é pelo digest.
- **UT-12** — Para as combinações de status das quatro etapas em dois deployments, `state` segue `failed` > `running` > `pending` > `not_verified` > `ok`, os exits são 1, 6, 6, 5 e 0, e `current_stage` é a primeira etapa não ok na ordem pipeline → image → gitops → rollout. O registro de chamadas mostra uma probe `pipeline runs` por `track` e uma `gitops application` e uma `runtime status` por deployment.
- **UT-13** — Então: `--commit` de 40 hexadecimais em maiúsculas é aceito e chega ao adaptador e à saída em minúsculas; `--commit 0a1b2c3` ou com `g` → exit 2 "commit precisa ser o sha completo (40 hexadecimais)", sem probe; `--expect-image acme/api` → exit 2; serviço sem deployment no ambiente → exit 2; `probes.enabled: false` → exit 4 sem nenhuma linha no `probes.log`; ambiente `tier: production` ou sem `tier`, sem `--confirm-production` → exit 4 antes de qualquer chamada dos dublês; sem configuração local → exit 3.
- **UT-14** — Em todos os testes do `track`, a árvore da pasta do atlas tem o mesmo hash antes e depois, nenhum arquivo é criado além das linhas do `probes.log`, e o valor de `GH_TOKEN`, de `ATLAS_GITOPS_CONTEXT` e do contexto do cluster não aparece na saída (Markdown e `--json`) nem no `probes.log`, mesmo quando o dublê os ecoa num item. Sem `--json`, a saída tem o estado, a etapa atual, a imagem esperada e a tabela, e nenhum texto de comando (`gh `, `kubectl `, `argocd `).

### 7.3 Testes de Integração
- **IT-01** — Num atlas temporário (serviço `api` com `code_repositories: [acme/api]`, `config_repositories: [acme/iac]`, deployment `dev-api` em `dev` com `tier: test` e cluster com `access.clusters`), configuração local temporária com as probes ligadas e os adaptadores `github-actions`, `argocd` e `kubernetes` da skill, e o `fake_gh.py` e o dublê de `kubectl` de `fixtures/delivery-track/` no `PATH` (os dois registram cada argv num arquivo), o `atlas.py verify track --service api --env dev --commit <sha> --json` real roda três vezes, com o dublê passando de estado entre elas:
  1. CI `in_progress` → exit 6, `state: running`, `current_stage: pipeline`;
  2. CI `success` e Application OutOfSync com `acme/api:sha-0a1b2c3` → exit 6, `current_stage: gitops`;
  3. Application Synced/Healthy e pods prontos com a imagem → exit 0, `state: ok`, `expected_image: acme/api:sha-0a1b2c3`.

  Em seguida, `verify compare --expect-image <expected_image>` com o mesmo dublê dá `passou`. Nos registros, todo argv do `gh` é `api -X GET repos/acme/api/actions/runs …` e todo argv do `kubectl` começa com `get`; nenhum tem `POST`, `PATCH`, `PUT`, `DELETE`, `rerun`, `dispatch`, `sync`, `patch`, `apply`, `annotate`, `rollout` ou `delete`. O `probes.log` tem uma linha por probe, com `status: ok`.
- **IT-02** — Com o mesmo atlas e a CI `completed/failure`, o `track` real sai com 1, `state: failed`, `current_stage: pipeline` e a execução com a URL na evidência. Com o ambiente trocado para `tier: production` e sem `--confirm-production`, sai com 4 e os registros dos dois dublês ficam vazios.

### 7.4 Testes de Contrato
- **CT-01** — As saídas de `--describe`, de `runs`, de `application` e de cada erro dos dois adaptadores passam pelos validadores `probe@2` do núcleo (SPEC-0096) sem problemas, e os blocos `json probe@2 describe|input|output valid|invalid` de `references/probes/github-actions.md` e `references/probes/argocd.md` são aceitos ou recusados como o rótulo diz (um item com objeto aninhado, como `source`, é recusado).
- **CT-02** — Os blocos `json track@1 valid|invalid` de `references/verify.md` passam por `validate_track_result` como o rótulo diz (chave a mais, `stage` ou `status` fora da lista e `reason` vazio fora de `ok` são recusados), e toda saída `--json` do `track` nos testes é válida.

### 7.5 Testes E2E
- N/A — CLI sem jornada interativa de usuário; o IT-01 roda o `track` e o `compare` como processos, de ponta a ponta, com os dublês.

### 7.6 Outros
- N/A — a segurança (só leitura, lista fechada, máscara) está nos UT-04, UT-07, UT-14 e IT-01.

**Dublês e dados de teste:**
- `fixtures/github-actions/fake_gh.py`: responde `api -X GET repos/<o>/<r>/actions/runs` a partir de JSON gravado por repositório e por estado, simula 401, 403, limite, 404, timeout e JSON inválido, registra cada argv e falha (exit 97) em qualquer argv fora da lista.
- `fixtures/delivery-track/`: dublê de `kubectl` que responde `get applications.argoproj.io`, `deployments`, `replicasets`, `pods` e `events` por estado (`antes`, `ci`, `gitops`, `pronto`), no molde de `fixtures/kubernetes/fake_kubectl.py`, registrando cada argv; o `fake_gh.py` é reaproveitado.
- Os adaptadores falsos de `fixtures/fake-probes/` para as regras de etapa do `track`.
- Atlas, `HOME`, `ATLAS_CONFIG_HOME` e `XDG_CONFIG_HOME` temporários; nunca `~/.claude` nem `~/.config` reais. Só nomes `acme`; nenhum `gh`, `kubectl` ou rede reais.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15), só com dublês.

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin (SPEC-0056). O `track` só roda com `probes.enabled: true`, e cada etapa só com o adaptador declarado em `probes.adapters` e o verbo liberado; sem eles, a etapa fica `not_verified` com o motivo. A SPEC-0105 (G6 da gluon-spec) consome o `track` depois do merge: repete a chamada enquanto o exit for 6, depois da janela, e leva o `expected_image` ao `verify compare`. Até ela entrar, o `track` funciona sozinho pela CLI.
- **Dados/schema:** nenhum; o `track` não grava arquivo nem atlas.
- **Compatibilidade:** aditivo. `verify snapshot` e `verify compare` não mudam; o exit 6 é novo e só existe no `track`. Os adaptadores falam `probe@2` e só funcionam com o núcleo da SPEC-0096.
- **Observabilidade:** o estado e as evidências do `track`, que a SPEC-0105 leva ao Relatório de Entrega, e uma linha por probe no `probes.log` (sem resultado nem acesso).
- **Rollback:** voltar a versão do plugin ou tirar `github-actions` e `argocd` de `probes.adapters`; o G6 volta ao roteiro da SPEC-0086.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Um adaptador `delivery` com dois verbos ou dois adaptadores? — Dois, com as capacidades `pipeline` e `gitops`: como vale o primeiro adaptador por capacidade, separar deixa combinar qualquer CI com qualquer GitOps (Architect, 2026-11-24, recomendado)
- [x] De onde vem a imagem do commit, se a CI não a expõe de forma padronizada? — Do `--expect-image` quando dado; senão, da imagem da Application cuja tag tem um pedaço que é prefixo do commit (7+ caracteres). Sem registry nem logs da CI. Time com tag semver passa `--expect-image` (Architect, 2026-11-24, recomendado)
- [x] Como achar a Application quando o Argo CD roda noutro cluster ou namespace? — `--app-namespace` (padrão `argocd`) no `command` local e a variável opcional `ATLAS_GITOPS_CONTEXT`, declarada em `credentials` e mascarada; sem ela, o contexto do cluster do deployment (Architect, 2026-11-24, recomendado)
- [x] Qual exit para "ainda não chegou"? — 6 (`running` ou `pending`), distinto do 5 (`inconclusivo`), para a gluon-spec repetir depois da janela sem confundir com falta de prova (Architect, 2026-11-24, recomendado)
- [x] O `track` espera sozinho (`--wait`)? — Não: uma leitura por chamada; quem repete é a SPEC-0105 (Architect, 2026-11-24, recomendado)
- [x] O `github-actions` declara `access: []`? — Sim: não usa acesso local do atlas, só o `gh` autenticado ou o `GH_TOKEN` por nome. O ADR-0025 (regra 4) permite `access: []` (Architect, 2026-11-24, recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — e297cb0 | 2026-11-24 |
| G1 Red | PENDING | | |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Todos os testes do plano passando e listados na Verificação
- [ ] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [ ] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [ ] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [ ] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6)
- [ ] Observabilidade e rollback prontos conforme o Plano de Rollout
- [ ] Documentação raiz e CHANGELOG atualizados (G7)
- [ ] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [ ] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0106`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
