# Adaptador de probe `kubernetes`

Adaptador de referência da capacidade `runtime` do contrato `probe@1` (`references/probes.md`, SPEC-0088). Vem com a skill em `assets/probes/kubernetes.py` (só biblioteca padrão, Python 3.9 ou mais novo) e usa o `kubectl` da máquina, **só para leitura**, com o contexto e o namespace que o atlas entrega (SPEC-0089, ADR-0023).

| Verbo | Pergunta | Itens |
|---|---|---|
| `status` | O workload está de pé, com a imagem certa? | um por workload e um por pod |
| `events` | Que alertas apareceram? | um por evento `Warning` |
| `logs` | O que os pods escreveram na janela? | um por linha |

## Configurar

1. Instale o `kubectl` e garanta um contexto do kubeconfig para cada cluster que você quer consultar.
2. Ligue o acesso local ao cluster em `access.clusters` (`<cluster>: {context: <nome do contexto>}`, `references/config.md`).
3. Ligue as probes e declare o adaptador no `config.yml` **desta máquina** (nunca no `atlas-config.yml`):

```yaml
probes:
  enabled: true
  adapters:
    kubernetes:                       # sem command: vale assets/probes/kubernetes.py da skill
      verbs: [status, events, logs]   # tire o que esta máquina não deve rodar
      timeout: 60
      credentials: [KUBECONFIG]       # opcional: só quando o kubeconfig não é o ~/.kube/config do HOME
```

4. Rode `atlas.py doctor` (linha `adaptador kubernetes`) e depois uma probe de teste:

```bash
python3 <skill-dir>/scripts/atlas.py probe runtime status --service api --env dev
```

- **Kubeconfig:** o adaptador recebe só a base fixa do ambiente (`PATH`, `HOME`…) mais as credenciais declaradas nele. Sem `KUBECONFIG` em `credentials`, o `kubectl` usa o `~/.kube/config` do `HOME`. Declare só o **nome** da variável; o valor fica no ambiente da máquina.
- **Tempo:** cada chamada vai com `--request-timeout=20s` fixo, abaixo do timeout padrão do núcleo (60 s). A entrada `probe@1` não traz o timeout do núcleo; com um `timeout` menor que uns 25 s na configuração, o núcleo pode encerrar o adaptador antes do `kubectl` desistir.

### Permissão mínima sugerida

A credencial é a barreira principal (ADR-0023): use uma conta só de leitura, **sem** `secrets` nem `configmaps`.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: atlas-probe-reader
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]
    verbs: ["get", "list"]
  - apiGroups: ["argoproj.io"]
    resources: ["rollouts"]
    verbs: ["get", "list"]
  - apiGroups: [""]
    resources: ["pods", "pods/log", "events"]
    verbs: ["get", "list"]
```

Ligue o ClusterRole com um `RoleBinding` em cada namespace que o atlas aponta.

## O que é lido

O adaptador monta cada chamada só a partir de `target` e `limits`, como lista de argumentos e sem shell, e de uma lista fechada:

```text
kubectl get <recurso> -o json --context=<target.context> -n <target.namespace> --request-timeout=20s
    recurso ∈ deployments, statefulsets, daemonsets, rollouts, replicasets, pods, events
kubectl logs pod/<nome> --all-containers --timestamps --prefix --since=<since_seconds>s --tail=<lines>
    --context=<target.context> -n <target.namespace> --request-timeout=20s
```

- No máximo um `get` por recurso em cada execução e um `logs` por pod. Nada de `-l`, `-A`, `--kubeconfig`, `--raw`, `exec`, `describe`, `port-forward`, `Secret` ou `ConfigMap`.
- Os pods de um workload são os que casam com o seletor dele (`spec.selector`), conferido no próprio adaptador depois do `get pods`.
- Recusado **antes** de chamar o `kubectl` (`status: error`, "chamada não permitida"): verbo fora de `status`, `events` e `logs`; workload de kind fora de `Deployment`, `StatefulSet`, `DaemonSet` e `Rollout`; nome de workload fora do DNS-1123 (subdomínio) ou namespace fora do DNS-1123 (rótulo), inclusive começando com `-`.
- O cluster sem o tipo `rollouts` (CRD do Argo Rollouts ausente) conta como lista vazia.

## Saída

**`status`** — lê o recurso de cada kind pedido e `pods`.

```json
{"kind": "workload", "workload": "Deployment/api", "found": true, "desired": 3, "updated": 3, "ready": 3, "available": 3, "rollout_complete": true}
{"kind": "pod", "workload": "Deployment/api", "pod": "api-7f9c-abcd", "phase": "Running", "ready": true, "restarts": 0, "images": ["acme/api:1.4.2@sha256:…"], "last_termination": ""}
```

- `rollout_complete`: atualizadas = desejadas = prontas = disponíveis e `observedGeneration` ≥ `generation`. No `Rollout`, um `observedGeneration` em texto de dígitos (como o Argo Rollouts grava) vale como número. No `DaemonSet`, os números vêm de `desiredNumberScheduled`, `updatedNumberScheduled`, `numberReady` e `numberAvailable`.
- Workload que não existe no cluster: `{"kind": "workload", "workload": "Deployment/x", "found": false, "rollout_complete": false}`, sem pods.
- `images`: o caminho normalizado (regra da SPEC-0082), mais `:<tag>` e `@<digest>` quando existem, **sem o host do registry** (`ghcr.io/acme/api:1.4.2` → `acme/api:1.4.2`). Uma referência fora da regra (credencial, espaço, digest estranho) não sai.
- `restarts` soma os containers; `last_termination` é o motivo do último término (`OOMKilled`, `Error`) ou `""`.

**`events`** — lê `events`, `pods`, o recurso de cada kind pedido e, para `Deployment` e `Rollout`, `replicasets`.

```json
{"reason": "Unhealthy", "object": "Pod/api-7f9c-abcd", "count": 3, "last_ts": "2026-11-23T10:00:00Z", "message": "Readiness probe failed: …"}
```

- Só `type: Warning`, só dos workloads, dos pods deles e dos ReplicaSets de um `Deployment` ou de um `Rollout` (os que têm em `ownerReferences` o mesmo kind e nome; a ReplicaSet de um `Deployment` com o mesmo nome de um `Rollout` não entra nos eventos do `Rollout`), com o último horário dentro de `since_seconds`; `message` até 300 caracteres. Ordem: do mais antigo ao mais novo; acima de `lines`, ficam os mais recentes e `truncated: true`.

**`logs`** — lê `pods` e o recurso de cada kind pedido, e roda um `logs pod/<nome>` por pod do workload, até 10, em ordem de nome.

```json
{"workload": "Deployment/api", "pod": "api-7f9c-abcd", "container": "api", "ts": "2026-11-23T10:00:00.000000000Z", "line": "INFO request ok"}
```

- Todos os containers, com horário; a linha sai sem o prefixo `[pod/…/…]` e sem o horário do `kubectl`.
- As linhas dos pods são juntadas, ordenadas pelo tempo real do `ts` (com a fração de segundo, até nanossegundos, também quando o `kubectl` omite os zeros do fim ou a fração inteira), e ficam as `lines` mais recentes; o `ts` sai como o `kubectl` imprimiu. `truncated: true` quando sobrou linha, quando um container chegou ao `--tail`, quando o workload tem mais de 10 pods ou quando um pod foi pulado.
- **Pod que não responde:** um pod em `Pending`, ou com todos os containers esperando sem nunca ter rodado, é pulado sem chamar o `logs`; um pod cujo `logs` falha com erro que não é Forbidden, contexto inexistente nem timeout (o pod sumiu, o container ainda não começou) também é pulado. Os outros pods seguem e `truncated` fica `true`. Forbidden, contexto inexistente ou timeout no `logs` de qualquer pod continuam dando `status: error`.
- A redaction (e-mail, token, documento) é do núcleo, como em toda probe.

## Erros

Saem com exit 0, `status: error`, `items: []` e uma mensagem fixa, **sem** o texto do `kubectl` (que pode citar o contexto):

| Mensagem | Quando |
|---|---|
| `kubectl não encontrado` | sem `kubectl` no `PATH` do adaptador |
| `sem permissão (Forbidden)` | o RBAC negou uma leitura |
| `contexto inexistente` | o contexto do `access.clusters` não existe no kubeconfig |
| `timeout` | "deadline exceeded", "timeout" ou "i/o timeout" no stderr, ou o `kubectl` passou de 30 s |
| `chamada não permitida` | verbo, kind ou nome fora da lista, recusado sem chamar o `kubectl` |
| `falha do kubectl` / `resposta inválida do kubectl` | outro erro, ou uma resposta que não é a lista JSON esperada, inclusive um item com campo de forma errada (`metadata`, `spec`, `status`, `labels`, seletor, `state`/`lastState` de container ou referência de evento que não é objeto, como `spec: []`) |
| `entrada inválida` | a entrada no stdin não é um `probe@1` bem formado, ou o contexto tem caractere de controle (nulo, quebra de linha), recusado sem chamar o `kubectl` |

O nome do contexto nunca sai do adaptador; o núcleo ainda mascara o valor em tudo o que vem dele (SPEC-0088).
