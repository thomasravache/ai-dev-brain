# Adaptador de probe `iam`

Adaptador da capacidade `permissions` do contrato `probe@2` (`references/probes.md`, SPEC-0096, ADR-0025). Vem com a skill em `assets/probes/iam.py` (só biblioteca padrão, Python 3.9 ou mais novo) e responde: **o workload do serviço tem, na fila ou no tópico, a permissão que a relação dele exige?** Usa o `kubectl` (para achar o papel IRSA do workload) e a AWS CLI v2 (para ler a política do recurso e rodar `iam simulate-principal-policy`), **só para leitura**, com o contexto do cluster (`access.clusters`), o profile do ambiente (`access.cloud.<ambiente>.profile`) e a região do recurso (SPEC-0101). Nenhuma mensagem é enviada, lida ou apagada.

| Verbo | Alvo | Pergunta | Itens |
|---|---|---|---|
| `simulate` | `queue`, `topic` | Cada workload pode enviar/receber/apagar na fila, ou publicar no tópico? | um por (workload, ação) |

Os itens seguem a tabela 4a do ADR-0026 (`action`, `api_action`, `decision`), que o `verify@2` (SPEC-0102) lê; os campos a mais são ignorados por ele.

## Configurar

1. Instale o `kubectl` e a AWS CLI v2. Crie, nesta máquina, um profile **só de leitura** por ambiente (SSO ou papel assumido) e um contexto do kubeconfig com leitura de workloads e ServiceAccounts.
2. Ligue o acesso local em `access.clusters` (`<cluster>: {context: <contexto>}`) e `access.cloud` (`<ambiente>: {profile: <profile>}`), `references/config.md`. O atlas guarda só os nomes; as credenciais ficam no kubeconfig e na AWS CLI (ADR-0010).
3. Ligue as probes e declare o adaptador no `config.yml` **desta máquina** (nunca no `atlas-config.yml`):

```yaml
probes:
  enabled: true
  adapters:
    iam:                     # sem command: vale assets/probes/iam.py da skill
      verbs: [simulate]
      timeout: 120
```

4. Rode `atlas.py doctor` e depois uma probe de teste:

```bash
python3 <skill-dir>/scripts/atlas.py probe permissions simulate --service orders-worker --env dev --resource queue:orders
python3 <skill-dir>/scripts/atlas.py probe permissions simulate --service orders-worker --env dev --resource topic:orders-events
```

- **Recurso:** a fila ou o tópico precisa estar ligado ao deployment do serviço no ambiente (`--resource`, `linked_resources`, SPEC-0096). Usa só o nome (o id do nó) e o atributo `region` (obrigatório). Um atributo `arn` ou `url` do atlas é ignorado: a URL e os ARNs saem da própria CLI e ficam só em memória.
- **Login expirado:** a skill nunca faz o login; rode `aws sso login --profile <profile>` você mesmo e repita.
- **Tempo:** cada `kubectl` vai com `--request-timeout=20s`, cada `aws` com `--cli-read-timeout 20 --cli-connect-timeout 10`, e cada processo tem 30 s. Uma execução faz até 5 gets de workload, um get por ServiceAccount, até 3 leituras do recurso e uma simulação por papel: um `timeout` de 120 s no adaptador sobra.

### Permissões mínimas sugeridas

O profile e o papel do cluster só de leitura são a barreira principal (ADR-0023, ADR-0025 regra 7); a lista fechada do adaptador é a segunda.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "iam:SimulatePrincipalPolicy",
        "sqs:GetQueueUrl",
        "sqs:GetQueueAttributes",
        "sns:GetTopicAttributes"
      ],
      "Resource": "*"
    }
  ]
}
```

`sts:GetCallerIdentity` não precisa de permissão. No cluster, um ClusterRole (ou Role por namespace) de leitura:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: atlas-iam-reader
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get"]
  - apiGroups: ["argoproj.io"]
    resources: ["rollouts"]
    verbs: ["get"]
  - apiGroups: [""]
    resources: ["serviceaccounts"]
    verbs: ["get"]
```

## O que é lido

Cada chamada é montada só de `target.resource` (id e `region`), `target.cloud.profile`, `target.context`, `target.namespace` e `target.workloads`, como lista de argumentos e sem shell, e de uma lista fechada:

```text
kubectl get <deployments|statefulsets|daemonsets|rollouts> <nome> -o json --context=<ctx> -n <ns> --request-timeout=20s
kubectl get serviceaccounts <sa> -o json --context=<ctx> -n <ns> --request-timeout=20s
    sa = spec.template.spec.serviceAccountName (ou serviceAccount; ausente = default)
    papel = metadata.annotations["eks.amazonaws.com/role-arn"]
aws sts get-caller-identity                                    (só tópico: conta e partição do ARN)
aws sqs get-queue-url --queue-name <nome>                      (só fila)
aws sqs get-queue-attributes --queue-url <QueueUrl> --attribute-names Policy QueueArn
aws sns get-topic-attributes --topic-arn arn:<partição>:sns:<região>:<conta>:<nome>
aws iam simulate-principal-policy --policy-source-arn <papel> --action-names <ações da API...>
    --resource-arns <QueueArn | ARN do tópico> [--resource-policy <política em JSON compacto>]
```

- Toda chamada da `aws` leva `--region <região> --profile <profile> --output json --no-cli-pager --cli-read-timeout 20 --cli-connect-timeout 10`, num ambiente sem `AWS_PROFILE`, `AWS_DEFAULT_PROFILE` e chaves estáticas herdados (vale só o `--profile`) e com `AWS_PAGER=""`.
- **Ordem:** todos os papéis são resolvidos no cluster antes de qualquer chamada à `aws`; depois o endereço e a política do recurso; por fim uma simulação por papel distinto (workloads com o mesmo papel dividem a simulação).
- **Conferências:** a `QueueUrl` precisa ser `https://sqs.<região>.amazonaws.com/<12 dígitos>/<nome>` e o `QueueArn` ter o mesmo nome, a mesma região e a mesma conta; o ARN do papel segue `^arn:aws[-a-z]*:iam::[0-9]{12}:role/[\w+=,.@/-]{1,512}$`. Fora disso, nada é simulado.
- **Política do recurso:** sempre entra na simulação quando existe. Fila ou tópico sem `Policy` é legítimo: simula sem `--resource-policy` e marca `resource_policy: false`. Política que não pode ser lida (`AccessDenied`, `AuthorizationError`) é erro, nunca simulação sem ela.
- **Nunca:** escrita em IAM, fila, tópico ou cluster; `Secret`, `ConfigMap`, `exec`, `describe`; `--endpoint-url`, `--debug`, `--query`; `receive-message`, `send-message`, `publish`.
- Recusado **antes** de chamar qualquer ferramenta: verbo fora de `simulate` (`verbo não suportado`); stdin que não é `probe@2`, kind fora de `queue` e `topic`, fila fora de `^[A-Za-z0-9_-]{1,80}$` ou `^[A-Za-z0-9_-]{1,75}\.fifo$`, tópico fora de `^[A-Za-z0-9_-]{1,256}$` ou `^[A-Za-z0-9_-]{1,251}\.fifo$`, nome começando com `-`, região fora de `^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$`, profile fora de `^[A-Za-z0-9_.+-]{1,64}$` ou começando com `-`, workload fora de `Deployment|StatefulSet|DaemonSet|Rollout/<nome DNS-1123>`, caractere de controle (`entrada inválida`); sem `region` (`recurso sem região no atlas`).
- Até 5 workloads, na ordem da entrada; acima disso, os 5 primeiros e `truncated: true`, sem ler o sexto.

## Relação → ações

O adaptador simula todas as ações do tipo do recurso e marca em `required_by` as relações do grafo que exigem cada uma (regra 3 do ADR-0026). Quem escolhe as que contam é o `verify@2`, que tem as arestas.

| Tipo | `action` | `api_action` | `required_by` |
|---|---|---|---|
| `queue` | `send` | `sqs:SendMessage` | `depends_on`, `publishes` |
| `queue` | `receive` | `sqs:ReceiveMessage` | `consumes` |
| `queue` | `delete` | `sqs:DeleteMessage` | `consumes` |
| `topic` | `publish` | `sns:Publish` | `publishes` |

Nenhuma ação é exigida por `writes` nem por `depends_on` de tópico.

## Saída

Um item por (workload, ação), na ordem dos workloads da entrada e da tabela acima:

```json
{"workload": "Deployment/worker", "role": "orders-worker-dev", "action": "receive", "api_action": "sqs:ReceiveMessage", "decision": "allowed", "deny_type": null, "required_by": ["consumes"], "resource_policy": true}
```

- `role`: só o nome do papel (sem caminho, partição nem conta).
- `decision` e `deny_type`: do `EvalDecision` da AWS: `allowed` → `allowed` e `null`; `explicitDeny` → `denied` e `explicit`; `implicitDeny` → `denied` e `implicit`. Qualquer outro valor é `resposta inválida da nuvem`.
- `resource_policy`: a simulação levou a política do recurso.
- Nenhum ARN, URL de fila, política ou id de conta sai em item ou mensagem; todo texto passa por `\b[0-9]{12}\b` → `[REDACTED]` no próprio adaptador, e o núcleo ainda aplica a redaction e a máscara do profile (ADR-0025 regra 5).

### O que fica não verificado

- **EKS Pod Identity:** sem a anotação IRSA, a execução dá erro (`workload sem role IRSA (Pod Identity não verificado nesta versão)`).
- **Credenciais estáticas do pod** (chave em variável de ambiente, perfil do nó).
- **SCP e políticas de sessão:** a simulação do principal considera as políticas do papel, o limite de permissão e a política do recurso; SCP e política de sessão podem não entrar. `allowed` quer dizer "permitido pelas políticas do papel e do recurso".
- **Recurso em outra conta** que não a do profile: dá `recurso não encontrado na nuvem`.
- **Bucket e datastore:** fora desta versão (`targets` é `queue` e `topic`).

## Erros

Saem com exit 0, `status: error`, `items: []` e uma mensagem fixa, **sem** o stderr das ferramentas (que pode citar o profile, o contexto, o ARN e a conta). Um workload sem papel ou uma política ilegível derruba a execução inteira: nunca sai `allowed` parcial.

| Mensagem | Quando |
|---|---|
| `kubectl não encontrado` / `aws não encontrado` | a ferramenta não está no `PATH` do adaptador |
| `renove o login da nuvem` | "token has expired", "sso session", `ExpiredToken`, "unable to locate credentials", "the config profile" |
| `sem permissão no cluster (Forbidden)` | o `kubectl` respondeu Forbidden |
| `contexto inexistente` | o contexto do `access.clusters` não existe no kubeconfig |
| `workload não encontrado` | NotFound no get do workload ou da ServiceAccount |
| `workload sem role IRSA (Pod Identity não verificado nesta versão)` | a ServiceAccount não tem `eks.amazonaws.com/role-arn` |
| `não foi possível ler a política do recurso` | `AccessDenied` ou `AuthorizationError` em `get-queue-attributes` ou `get-topic-attributes` |
| `recurso não encontrado na nuvem` | `NonExistentQueue` ou `NotFound` na leitura do recurso |
| `sem permissão para simular (iam:SimulatePrincipalPolicy)` | `AccessDenied` na simulação |
| `timeout` | "timeout", "timed out", "deadline exceeded", ou o processo passou de 30 s |
| `entrada inválida` / `recurso sem região no atlas` / `verbo não suportado` | entrada fora da regra, recusada sem chamar nada |
| `chamada não permitida` | operação ou opção fora da lista fechada |
| `falha do kubectl` / `falha da aws` | outro erro |
| `resposta inválida do kubectl` / `resposta inválida da nuvem` | JSON sem a forma esperada, anotação fora da regra, URL ou ARN do recurso que não confere, papel inexistente (`NoSuchEntity`), decisão desconhecida |

O adaptador não grava nada; o `probes.log` é do núcleo, com `resource` e sem resultado nem acesso (ADR-0025 regra 6).

## Exemplos do contrato

Blocos lidos pelo teste de contrato (CT-01) contra os validadores `probe@2` do núcleo.

```json probe@2 describe valid
{"contract": "probe@2", "adapter": "iam", "capabilities": {"permissions": {"verbs": ["simulate"], "targets": ["queue", "topic"], "access": ["cluster", "cloud"]}}}
```

```json probe@2 describe invalid
{"contract": "probe@2", "adapter": "iam", "capabilities": {"permissions": {"verbs": ["simulate"], "targets": ["queue", "topic"], "access": ["database"]}}}
```

```json probe@2 input valid
{"contract": "probe@2", "capability": "permissions", "verb": "simulate", "target": {"service": "orders-worker", "environment": "dev", "deployment": "dev-orders-worker", "resource": {"kind": "queue", "id": "orders", "attrs": {"region": "us-east-1"}}, "clusters": ["cluster-dev"], "context": "acme-dev", "namespace": "orders-dev", "workloads": ["Deployment/worker"], "cloud": {"profile": "acme-dev-read"}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "iam", "capability": "permissions", "verb": "simulate", "status": "ok", "items": [{"workload": "Deployment/worker", "role": "orders-worker-dev", "action": "send", "api_action": "sqs:SendMessage", "decision": "denied", "deny_type": "implicit", "required_by": ["depends_on", "publishes"], "resource_policy": true}, {"workload": "Deployment/worker", "role": "orders-worker-dev", "action": "receive", "api_action": "sqs:ReceiveMessage", "decision": "allowed", "deny_type": null, "required_by": ["consumes"], "resource_policy": true}, {"workload": "Deployment/worker", "role": "orders-worker-dev", "action": "delete", "api_action": "sqs:DeleteMessage", "decision": "allowed", "deny_type": null, "required_by": ["consumes"], "resource_policy": true}], "truncated": false}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "iam", "capability": "permissions", "verb": "simulate", "status": "ok", "items": [{"workload": "Deployment/worker", "role": "orders-worker-dev", "action": "publish", "api_action": "sns:Publish", "decision": "denied", "deny_type": "explicit", "required_by": ["publishes"], "resource_policy": false}], "truncated": false}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "iam", "capability": "permissions", "verb": "simulate", "status": "error", "items": [], "truncated": false, "message": "não foi possível ler a política do recurso"}
```

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "iam", "capability": "permissions", "verb": "simulate", "status": "ok", "items": [{"workload": "Deployment/worker", "action": "publish", "api_action": "sns:Publish", "decision": {"value": "allowed", "matched": 1}}], "truncated": false}
```

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "iam", "capability": "permissions", "verb": "simulate", "status": "ok", "items": [], "truncated": false, "role_arn": "[REDACTED]"}
```
