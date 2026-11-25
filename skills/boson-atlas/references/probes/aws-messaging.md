# Adaptador de probe `aws-messaging`

Adaptador da capacidade `messaging` do contrato `probe@2` (`references/probes.md`, SPEC-0096, ADR-0025). Vem com a skill em `assets/probes/aws-messaging.py` (só biblioteca padrão, Python 3.9 ou mais novo) e usa a AWS CLI v2 da máquina, **só para leitura**, com o profile do ambiente (`access.cloud.<ambiente>.profile`) e a região do recurso (SPEC-0098). Nunca lê, recebe, apaga nem reenvia mensagens.

| Verbo | Alvo | Pergunta | Itens |
|---|---|---|---|
| `queue` | `queue` | A fila está acumulando? A DLQ dela ganhou mensagens? | exatamente um |
| `subscriptions` | `topic` | Quem assina o tópico, e com que filtro? | um por assinatura |

Os itens seguem a tabela 4a do ADR-0026, que o `verify@2` lê; os campos a mais são ignorados por ele.

## Configurar

1. Instale a AWS CLI v2 e crie, nesta máquina, um profile **só de leitura** por ambiente (SSO ou papel assumido).
2. Ligue o acesso local à nuvem em `access.cloud` (`<ambiente>: {profile: <nome do profile>}`, `references/config.md`). O atlas guarda só o nome do profile; a credencial fica na AWS CLI (ADR-0010).
3. Ligue as probes e declare o adaptador no `config.yml` **desta máquina** (nunca no `atlas-config.yml`):

```yaml
probes:
  enabled: true
  adapters:
    aws-messaging:                     # sem command: vale assets/probes/aws-messaging.py da skill
      verbs: [queue, subscriptions]    # tire o que esta máquina não deve rodar
      timeout: 60
```

4. Rode `atlas.py doctor` e depois uma probe de teste:

```bash
python3 <skill-dir>/scripts/atlas.py probe messaging queue --service api --env dev --resource queue:orders
python3 <skill-dir>/scripts/atlas.py probe messaging subscriptions --service api --env dev --resource topic:orders-events
```

- **Recurso:** a fila ou o tópico precisa estar ligado ao deployment do serviço no ambiente (`--resource`, `linked_resources`, SPEC-0096). Os atributos usados vêm do coletor `aws` (SPEC-0097) ou de um atlas escrito à mão: `region` (obrigatório), `type` (`sqs` na fila, `sns` no tópico, opcional) e `dlq` (o nome de outra fila, opcional). O nome é o id do nó. Nenhum ARN nem URL é lido do atlas: um atributo `arn` ou `url` é ignorado.
- **Login expirado:** a skill nunca faz o login; rode `aws sso login --profile <profile>` você mesmo e repita.
- **Tempo:** cada chamada vai com `--cli-read-timeout 20 --cli-connect-timeout 10`, e cada processo da CLI tem 30 s. O `subscriptions` faz uma chamada por assinatura (até 100): num tópico grande, suba o `timeout` do adaptador.

### Política IAM mínima sugerida

O profile só de leitura é a barreira principal (ADR-0023, ADR-0025 regra 7); a lista fechada do adaptador é a segunda.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sqs:GetQueueUrl",
        "sqs:GetQueueAttributes",
        "sns:ListSubscriptionsByTopic",
        "sns:GetSubscriptionAttributes",
        "cloudwatch:GetMetricData"
      ],
      "Resource": "*"
    }
  ]
}
```

`sts:GetCallerIdentity` não precisa de permissão. Sem `cloudwatch:GetMetricData`, o `queue` segue funcionando, com a idade `null` e `oldest_age_source: "sem permissão"`.

## O que é lido

O adaptador monta cada chamada só a partir de `target.resource` (id, `region`, `dlq`), `target.cloud.profile` e `limits`, como lista de argumentos e sem shell, e de uma lista fechada. Toda chamada leva `--region <region> --profile <profile> --output json --no-cli-pager --cli-read-timeout 20 --cli-connect-timeout 10`:

```text
sqs get-queue-url --queue-name <nome>
sqs get-queue-attributes --queue-url <url devolvida acima> --attribute-names ApproximateNumberOfMessages
    ApproximateNumberOfMessagesNotVisible ApproximateNumberOfMessagesDelayed RedrivePolicy
cloudwatch get-metric-data --metric-data-queries <1 consulta: AWS/SQS ApproximateAgeOfOldestMessage,
    QueueName=<nome>, Maximum, 60 s> --start-time <agora-600s> --end-time <agora> --scan-by TimestampDescending
sts get-caller-identity
sns list-subscriptions-by-topic --topic-arn arn:<partição>:sns:<region>:<conta>:<nome>
sns get-subscription-attributes --subscription-arn <arn devolvido pela listagem, conferido por regex>
```

- **`queue`:** até 2 `get-queue-url` e 2 `get-queue-attributes` (fila e DLQ) e 1 `get-metric-data`.
- **`subscriptions`:** 1 `sts get-caller-identity` (a conta e a partição do ARN do tópico), 1 `list-subscriptions-by-topic` (a CLI pagina) e um `get-subscription-attributes` por assinatura confirmada, até 100.
- **Nunca:** `receive-message`, `purge-queue`, `delete-*`, `send-*`, `set-*`, `publish`, `start-message-move-task`, `get-queue-attributes` com `All` ou `Policy`, `--endpoint-url`, `--debug`, `--query`. A política da fila e do tópico e os atributos de criptografia não são lidos.
- Recusado **antes** de chamar a CLI: verbo fora de `queue` e `subscriptions`, `queue` com alvo que não é fila, `subscriptions` com alvo que não é tópico, `type` diferente de `sqs`/`sns` (`chamada não permitida`); nome de fila fora de `^[A-Za-z0-9_-]{1,80}(\.fifo)?$`, de tópico fora de `^[A-Za-z0-9_-]{1,256}(\.fifo)?$`, `dlq` fora da regra de fila, nome começando com `-`, região fora de `^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$`, profile fora de `^[A-Za-z0-9_.+-]{1,64}$` ou começando com `-`, caractere de controle (`entrada inválida`); sem `region` (`recurso sem região no atlas`).

## Saída

**`queue`** — exatamente um item:

```json
{"visible": 12, "in_flight": 3, "oldest_age_seconds": 42, "dlq_visible": 2, "delayed": 0, "fifo": false, "oldest_age_source": "cloudwatch", "dlq": "queue:orders-dlq", "dlq_in_flight": 0, "redrive": true, "redrive_matches_dlq": true}
```

- `visible`, `in_flight` e `delayed`: `ApproximateNumberOfMessages`, `...NotVisible` e `...Delayed`, inteiros ≥ 0.
- `oldest_age_seconds`: o ponto mais recente de `ApproximateAgeOfOldestMessage` (máximo, 60 s) nos últimos 10 minutos, em segundos inteiros. Sem ponto na janela (a AWS só emite a métrica com a fila ativa): `null` e `oldest_age_source: "sem dados"`; sem permissão no CloudWatch: `null` e `"sem permissão"`. O resto do item segue valendo.
- `fifo`: pelo sufixo `.fifo` do nome (regra da AWS).
- `dlq`, `dlq_visible`, `dlq_in_flight`: da fila do atributo `dlq` do recurso; `null` sem ele.
- `redrive`: a fila tem `RedrivePolicy`; `redrive_matches_dlq`: o nome do `deadLetterTargetArn` é o da `dlq` (`null` sem `dlq` ou sem `RedrivePolicy`).

**`subscriptions`** — um item por assinatura, sem item do tópico; o resumo vai em `message` (`"<n> assinaturas, <m> pendentes"`, com `n` contado antes do corte):

```json
{"destination": "queue:orders", "filter_fingerprint": "sha256:0f3c2a9b5d7e1f46", "destination_fingerprint": "sha256:9a1b2c3d4e5f6071", "protocol": "sqs", "pending_confirmation": false, "raw_delivery": true, "has_filter": true, "filter_scope": "MessageAttributes", "filter_keys": ["event_type", "region"], "has_dlq": false}
{"destination": "https:[REDACTED]", "filter_fingerprint": null, "destination_fingerprint": "sha256:5e6f708192a3b4c5", "protocol": "https", "pending_confirmation": false, "raw_delivery": false, "has_filter": false, "filter_scope": null, "filter_keys": [], "has_dlq": false}
```

- `destination`: `sqs` → `queue:<nome da fila>` (o id de fila do coletor `aws`; quem cruza com o grafo é o `verify`); `lambda` → `function:<nome>`; `firehose` → `stream:<nome>`; `email`, `email-json`, `sms`, `http`, `https`, `application` e outros → `<protocolo>:[REDACTED]`.
- `destination_fingerprint`: `sha256` do protocolo e do endpoint com a conta trocada por `[REDACTED]`, 16 primeiros hex; distingue dois destinos mascarados iguais.
- `filter_fingerprint`: `sha256` do JSON canônico do `FilterPolicy` (`sort_keys`, separadores `,` e `:`, sem escapar não-ASCII), 16 primeiros hex; muda quando muda qualquer chave ou valor; `null` sem filtro.
- `filter_keys`: os caminhos das chaves, ordenados, com `.` entre níveis no escopo `MessageBody`; **nunca os valores** (podem ter ids de cliente). Para ver o texto do filtro, use o console da nuvem.
- `has_dlq`: a assinatura tem `RedrivePolicy`. `raw_delivery`: `RawMessageDelivery`.
- Assinatura pendente (`PendingConfirmation`): sem `get-subscription-attributes`; `pending_confirmation: true` e os campos de atributo `null`.
- Ordem: por `destination` e `destination_fingerprint`; acima de `limits.lines` ou de 100 assinaturas, corta e `truncated: true`. Tópico sem assinaturas: `items: []` e `"0 assinaturas, 0 pendentes"`.
- Nenhum ARN, URL de fila, id de assinatura ou id de conta sai em item ou mensagem; todo texto passa por `\b[0-9]{12}\b` → `[REDACTED]` no próprio adaptador, e o núcleo ainda aplica a redaction e a máscara do profile (ADR-0025 regra 5).

## Erros

Saem com exit 0, `status: error`, `items: []` e uma mensagem fixa, **sem** o stderr da CLI (que pode citar o profile, o ARN e a conta):

| Mensagem | Quando |
|---|---|
| `aws não encontrado` | sem `aws` no `PATH` do adaptador |
| `renove o login da nuvem` | SSO ou token expirado ("Token has expired", "SSO session", `UnauthorizedSSOTokenError`, "Error loading SSO Token", `ExpiredToken`, `RequestExpired`, "security token included in the request is expired") |
| `profile inexistente` | o profile do `access.cloud` não existe nesta máquina |
| `sem credenciais da nuvem` | "Unable to locate credentials" |
| `sem permissão (AccessDenied)` | `AccessDenied`, `AuthorizationError` ou "not authorized" em sqs, sns ou sts (no `get-metric-data` não é erro: `oldest_age_source: "sem permissão"`) |
| `limite de chamadas da nuvem` | `Throttling`, "Rate exceeded" |
| `sem conexão com a nuvem` | "Could not connect to the endpoint URL", erro de DNS |
| `timeout` | "Read timeout", "Connect timeout", ou o processo passou de 30 s |
| `recurso sem região no atlas` | o recurso não tem `region` |
| `fila não encontrada` / `DLQ não encontrada` / `tópico não encontrado` | `QueueDoesNotExist` ou `NotFound` |
| `chamada não permitida` | verbo, kind, `type`, operação ou opção fora da lista, recusado sem chamar a CLI |
| `entrada inválida` | stdin que não é `probe@2` bem formado, profile ou nome fora da regra, caractere de controle |
| `falha da aws` / `resposta inválida da aws` | outro erro, ou JSON sem a forma esperada |

O adaptador não grava nada; o `probes.log` é do núcleo, com `resource` e sem resultado nem acesso (ADR-0025 regra 6).

## Exemplos do contrato

Blocos lidos pelo teste de contrato (CT-01) contra os validadores `probe@2` do núcleo.

```json probe@2 describe valid
{"contract": "probe@2", "adapter": "aws-messaging", "capabilities": {"messaging": {"verbs": ["queue", "subscriptions"], "targets": ["queue", "topic"], "access": ["cloud"]}}}
```

```json probe@2 describe invalid
{"contract": "probe@2", "adapter": "aws-messaging", "capabilities": {"messaging": {"verbs": ["queue depth"], "targets": ["queue"], "access": ["cloud"]}}}
```

```json probe@2 describe invalid
{"contract": "probe@2", "adapter": "aws-messaging", "capabilities": {"messaging": {"verbs": ["queue"], "targets": ["stream"], "access": ["cloud"]}}}
```

```json probe@2 input valid
{"contract": "probe@2", "capability": "messaging", "verb": "queue", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "resource": {"kind": "queue", "id": "orders", "attrs": {"region": "us-east-1", "type": "sqs", "dlq": "orders-dlq"}}, "cloud": {"profile": "acme-dev-read"}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 input valid
{"contract": "probe@2", "capability": "messaging", "verb": "subscriptions", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "resource": {"kind": "topic", "id": "orders-events", "attrs": {"region": "us-east-1", "type": "sns"}}, "cloud": {"profile": "acme-dev-read"}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "aws-messaging", "capability": "messaging", "verb": "queue", "status": "ok", "items": [{"visible": 12, "in_flight": 3, "oldest_age_seconds": 42, "dlq_visible": 2, "delayed": 0, "fifo": false, "oldest_age_source": "cloudwatch", "dlq": "queue:orders-dlq", "dlq_in_flight": 0, "redrive": true, "redrive_matches_dlq": true}], "truncated": false}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "aws-messaging", "capability": "messaging", "verb": "subscriptions", "status": "ok", "items": [{"destination": "queue:orders", "filter_fingerprint": "sha256:0f3c2a9b5d7e1f46", "destination_fingerprint": "sha256:9a1b2c3d4e5f6071", "protocol": "sqs", "pending_confirmation": false, "raw_delivery": true, "has_filter": true, "filter_scope": "MessageAttributes", "filter_keys": ["event_type", "region"], "has_dlq": false}, {"destination": "email:[REDACTED]", "filter_fingerprint": null, "destination_fingerprint": "sha256:1a2b3c4d5e6f7081", "protocol": "email", "pending_confirmation": true, "raw_delivery": null, "has_filter": null, "filter_scope": null, "filter_keys": null, "has_dlq": null}], "truncated": false, "message": "2 assinaturas, 1 pendentes"}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "aws-messaging", "capability": "messaging", "verb": "queue", "status": "error", "items": [], "truncated": false, "message": "renove o login da nuvem"}
```

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "aws-messaging", "capability": "messaging", "verb": "queue", "status": "ok", "items": [{"visible": 12, "in_flight": 3, "dlq": {"name": "orders-dlq", "visible": 2}}], "truncated": false}
```

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "aws-messaging", "capability": "messaging", "verb": "queue", "status": "ok", "items": [], "truncated": false, "queue_url": "[REDACTED]"}
```
