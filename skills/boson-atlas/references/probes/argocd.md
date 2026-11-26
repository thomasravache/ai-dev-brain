# Adaptador de probe `argocd`

Adaptador da capacidade `gitops` do contrato `probe@2` (`references/probes.md`, SPEC-0096, ADR-0025). Vem com a skill em `assets/probes/argocd.py` (só biblioteca padrão, Python 3.9 ou mais novo) e responde: **a Application do Argo CD do deployment sincronizou, está saudável e com qual imagem?** Lê a Application com `kubectl get`, **só para leitura**, sem a CLI do `argocd` (que pede login próprio e tem verbos de escrita na mesma ferramenta) (SPEC-0106). Nunca sincroniza, faz refresh nem rollback.

| Verbo | Alvo | Pergunta | Itens |
|---|---|---|---|
| `application` | `deployment` | sync, health, revisão, fase da operação e imagens da Application | um |

É a fonte das etapas `image` e `gitops` do `verify track` (`references/verify.md`).

## Configurar

1. Um contexto do kubeconfig com leitura de `applications.argoproj.io` no cluster onde o Argo CD roda. Ligue o acesso local em `access.clusters` (`<cluster>: {context: <contexto>}`, `references/config.md`).
2. Ligue as probes e declare o adaptador no `config.yml` **desta máquina** (nunca no `atlas-config.yml`):

```yaml
probes:
  enabled: true
  adapters:
    argocd:                  # sem command: vale assets/probes/argocd.py da skill
      verbs: [application]
      timeout: 60
```

3. Rode `atlas.py doctor` e depois uma probe de teste:

```bash
python3 <skill-dir>/scripts/atlas.py probe gitops application --service api --env dev
```

- **Nome da Application:** o do deployment no atlas (o id que o coletor `argocd` grava, SPEC-0082).
- **Namespace das Applications:** `argocd` por padrão. Noutro namespace, passe `--app-namespace <ns>` no `command` local (um rótulo DNS-1123; nunca vem do atlas):

```yaml
    argocd:
      command: ["python3", "/caminho/da/skill/assets/probes/argocd.py", "--app-namespace", "gitops"]
      verbs: [application]
```

- **Argo CD num cluster de gestão:** declare `ATLAS_GITOPS_CONTEXT` em `credentials` e defina a variável com o contexto desse cluster; ela vale no lugar do contexto do cluster do deployment, e o valor é mascarado como credencial:

```yaml
    argocd:
      verbs: [application]
      credentials: [ATLAS_GITOPS_CONTEXT]
```

- **Tempo:** `kubectl --request-timeout=20s` e 30 s por processo.

### Permissão mínima sugerida

Um ClusterRole (ou Role no namespace das Applications) só com `get`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: atlas-argocd-reader
rules:
  - apiGroups: ["argoproj.io"]
    resources: ["applications"]
    verbs: ["get"]
```

## O que é lido

Uma chamada, como lista de argumentos e sem shell:

```text
kubectl get applications.argoproj.io <deployment> -n <app-namespace> -o json --context=<contexto> --request-timeout=20s
```

- Recusado **antes** de chamar o `kubectl`: verbo fora de `application` (`chamada não permitida`); stdin que não é `probe@2` da capacidade `gitops`, sem `target.context`, nome fora do subdomínio DNS-1123 (até 253, minúsculas, dígitos, `-` e `.`), contexto começando com `-` ou com caractere de controle, `--app-namespace` fora do rótulo DNS-1123 (`entrada inválida`).
- **Nunca:** `-A`, `-l`, `--raw`, `--kubeconfig`, `patch`, `annotate`, `apply`, `delete`, nem a CLI `argocd`.
- Campos lidos: `metadata.name`, `status.sync.status`, `status.sync.revision` (ou o primeiro de `status.sync.revisions`), `status.health.status`, `status.operationState.phase`, `status.operationState.finishedAt`, `status.reconciledAt` e `status.summary.images`. **Nunca saem** `spec.source`, `spec.sources` (valores de Helm, `repoURL` com credencial), anotações (`last-applied-configuration`) nem `status.resources`.

## Saída

```json probe@2 describe valid
{"contract": "probe@2", "adapter": "argocd", "capabilities": {"gitops": {"verbs": ["application"], "targets": ["deployment"], "access": ["cluster"]}}}
```

```json probe@2 input valid
{"contract": "probe@2", "capability": "gitops", "verb": "application", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "clusters": ["cluster-dev"], "context": "ctx-dev", "namespace": "api-dev", "workloads": ["Deployment/api"]}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "argocd", "capability": "gitops", "verb": "application", "status": "ok", "items": [{"application": "dev-api", "found": true, "sync_status": "Synced", "health_status": "Healthy", "revision": "4f1c2d", "operation_phase": "Succeeded", "operation_finished_at": "2026-11-24T10:09:00Z", "reconciled_at": "2026-11-24T10:10:00Z", "images": ["acme/api:sha-0a1b2c3"]}], "truncated": false}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "argocd", "capability": "gitops", "verb": "application", "status": "ok", "items": [{"application": "dev-api", "found": false}], "truncated": false}
```

Inválida (um item com objeto aninhado, como a `source` da Application, nunca sai):

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "argocd", "capability": "gitops", "verb": "application", "status": "ok", "items": [{"application": "dev-api", "source": {"repoURL": "https://github.com/acme/iac"}}], "truncated": false}
```

- Texto ausente → `""`; `images` ausente → `[]`.
- `images`: a regra da SPEC-0082 e do adaptador `kubernetes` (caminho normalizado + `:tag` + `@digest`, sem o host do registro, também o host ECR com a conta); uma referência fora da regra (com credencial, espaço ou digest estranho) não sai.
- Application inexistente (`NotFound`): `{"application": "dev-api", "found": false}`.

## Erros

Saem com exit 0, `status: "error"`, `items: []` e uma destas mensagens fixas, nunca o stderr do `kubectl` (que pode citar o contexto):

| Mensagem | Quando |
|---|---|
| `kubectl não encontrado` | o `kubectl` não está no `PATH` |
| `sem permissão (Forbidden)` | o RBAC não deixa ler a Application |
| `contexto inexistente` | o contexto não existe no kubeconfig |
| `timeout` | o processo passou de 30 s ou o servidor não respondeu |
| `Argo CD ausente no cluster` | o tipo `applications.argoproj.io` não existe no cluster |
| `falha do kubectl` | outra falha do `kubectl` |
| `resposta inválida do kubectl` | a resposta não é o JSON esperado (por exemplo, `status` que não é objeto) |
| `chamada não permitida` | verbo fora de `application` |
| `entrada inválida` | entrada ou `--app-namespace` fora das regras acima |

O núcleo (`atlas.py probe`) valida a saída, aplica a máscara (o contexto e as credenciais declaradas mascarados literalmente, a conta de 12 dígitos do host ECR e de ARN) e grava uma linha em `probes.log` (SPEC-0096).
