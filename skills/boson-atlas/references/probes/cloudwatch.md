# Adaptador de probe `cloudwatch`

Adaptador da capacidade `signals` do contrato `probe@2` (`references/probes.md`, SPEC-0096, ADR-0025). Vem com a skill em `assets/probes/cloudwatch.py` (só biblioteca padrão, Python 3.9 ou mais novo) e usa a AWS CLI v2 da máquina, **só para leitura**, com o profile do ambiente (`access.cloud.<ambiente>.profile`) e a região do recurso (SPEC-0100). Responde: como estão os sinais (erro, latência, saturação e tráfego) deste banco, cache, fila ou tópico na janela?

| Verbo | Alvos | Itens |
|---|---|---|
| `metrics` | `datastore` (RDS, Aurora, ElastiCache Valkey/Redis), `queue` (SQS), `topic` (SNS) | um por métrica da tabela do tipo, na ordem da tabela |

Os itens seguem a tabela 4a do ADR-0026 (`name`, `stat`, `value`, `kind`), que o `verify@2` lê; os campos a mais (`unit`, `period`, `datapoints`, `nodes`) são ignorados por ele.

## Configurar

1. Instale a AWS CLI v2 e crie, nesta máquina, um profile **só de leitura** por ambiente (SSO ou papel assumido).
2. Ligue o acesso local à nuvem em `access.cloud` (`<ambiente>: {profile: <nome do profile>}`, `references/config.md`). O atlas guarda só o nome do profile; a credencial fica na AWS CLI (ADR-0010).
3. Ligue as probes e declare o adaptador no `config.yml` **desta máquina** (nunca no `atlas-config.yml`):

```yaml
probes:
  enabled: true
  adapters:
    cloudwatch:                        # sem command: vale assets/probes/cloudwatch.py da skill
      verbs: [metrics]
      timeout: 60
```

4. Rode `atlas.py doctor` e depois uma probe de teste:

```bash
python3 <skill-dir>/scripts/atlas.py probe signals metrics --service api --env dev --resource datastore:orders-db --since 30m
```

- **Recurso:** o banco, cache, fila ou tópico precisa estar ligado ao deployment do serviço no ambiente (`--resource`, `linked_resources`, SPEC-0096). Os atributos usados vêm do coletor `aws` (SPEC-0097) ou de um atlas escrito à mão: `type`, `engine`, `serverless` e `region`. O nome do recurso é o id do nó (o identificador no coletor) e vira o valor da dimensão. Nenhuma outra chave escolhe métrica, namespace, estatística ou dimensão: `metric`, `namespace`, `expression`, `arn` ou `url` nos atributos são ignorados.
- **Login expirado:** a skill nunca faz o login; rode `aws sso login --profile <profile>` você mesmo e repita.
- **Tempo:** cada chamada vai com `--cli-read-timeout 20 --cli-connect-timeout 10`, e cada processo da CLI tem 30 s.

### Tipo do recurso

| `kind` | Atributos | Conjunto |
|---|---|---|
| `datastore` | `type: rds`, `engine` que começa com `aurora` (`aurora-postgresql`, `aurora-mysql`, ...) | `rds-aurora` (cluster) |
| `datastore` | `type: rds`, outro `engine` ou sem `engine` | `rds` (instância) |
| `datastore` | `type: elasticache`, `serverless: true` | `elasticache-serverless` |
| `datastore` | `type: elasticache`, `serverless` `false` ou ausente, `engine` `valkey` ou `redis` | `elasticache` (por nós) |
| `queue` | `type: sqs` ou sem `type` | `sqs` |
| `topic` | `type: sns` ou sem `type` | `sns` |

Outro caso (datastore sem `type`, `type` trocado, `memcached`, outro kind) sai "tipo de recurso sem sinais". `serverless` precisa ser booleano JSON.

### Política IAM mínima sugerida

O profile só de leitura é a barreira principal (ADR-0023, ADR-0025 regra 7); a lista fechada do adaptador é a segunda.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricData",
        "elasticache:DescribeReplicationGroups"
      ],
      "Resource": "*"
    }
  ]
}
```

`elasticache:DescribeReplicationGroups` só é usada no cache por nós.

## O que é lido

Toda chamada leva `--region <region> --profile <profile> --output json --no-cli-pager --cli-read-timeout 20 --cli-connect-timeout 10`, como lista de argumentos e sem shell:

```text
elasticache describe-replication-groups --replication-group-id <id>       (só no conjunto elasticache, no máximo 1)
cloudwatch get-metric-data --metric-data-queries <JSON montado pelo adaptador, só MetricStat da tabela>
    --start-time <agora - janela> --end-time <agora> --scan-by TimestampAscending [--next-token <token devolvido>]
```

- **Uma consulta em lote:** um `get-metric-data` por execução, com até 5 páginas (`NextToken`); todas as páginas mandam as mesmas consultas e a mesma janela. Até 60 consultas: 9 no `rds`, até 8 no `rds-aurora`, 10 por nó no `elasticache` (até 6 nós), 9 no `elasticache-serverless`, 6 no `sqs` e 5 no `sns`.
- **Cache por nós:** os nós vêm de `MemberClusters` e `NodeGroupMembers` do grupo de replicação; acima de 6, os 6 primeiros em ordem de nome e `truncated: true`. Com `ReplicationGroupNotFoundFault`, o id vale como `CacheClusterId` de um cluster sem grupo (`nodes: 1`).
- **Nunca:** `list-metrics`, `get-metric-statistics`, `describe-alarms`, `get-metric-widget-image`, `put-*`, `set-*`, `delete-*`, `Expression` (`SEARCH`, Metrics Insights) nas consultas, `--endpoint-url`, `--debug`, `--query`. Alarmes, logs e painéis do CloudWatch não são lidos.
- Recusado **antes** de chamar a CLI: capacidade ou verbo fora de `signals`/`metrics` (`chamada não permitida`); tipo sem conjunto (`tipo de recurso sem sinais`); sem `region` (`recurso sem região no atlas`); região fora de `^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$`, `serverless` não booleano, nome fora da regra (RDS `^[A-Za-z][A-Za-z0-9-]{0,62}$`, ElastiCache `^[A-Za-z][A-Za-z0-9-]{0,39}$`, fila `^[A-Za-z0-9_-]{1,80}(\.fifo)?$`, tópico `^[A-Za-z0-9_-]{1,256}(\.fifo)?$`, nunca começando com `-`), profile fora de `^[A-Za-z0-9_.+-]{1,64}$` ou começando com `-`, caractere de controle, janela acima de 86400 s (`entrada inválida`).

### Métricas por conjunto

| Conjunto | Namespace / dimensão | kind | Métrica | stat | Unidade |
|---|---|---|---|---|---|
| `rds` | `AWS/RDS` / `DBInstanceIdentifier` | latency | `ReadLatency`, `WriteLatency` | avg | Seconds |
| | | saturation | `CPUUtilization` | max | Percent |
| | | saturation | `DatabaseConnections`, `DiskQueueDepth` | max | Count |
| | | saturation | `FreeableMemory`, `FreeStorageSpace` | min | Bytes |
| | | traffic | `ReadIOPS`, `WriteIOPS` | avg | Count/Second |
| `rds-aurora` | `AWS/RDS` / `DBClusterIdentifier` | latency | `ReadLatency`, `WriteLatency` | avg | Seconds |
| | | saturation | `CPUUtilization` | max | Percent |
| | | saturation | `DatabaseConnections` | max | Count |
| | | saturation | `FreeableMemory` | min | Bytes |
| | | saturation | `ACUUtilization` (só com `serverless: true`) | max | Percent |
| | | traffic | `ReadIOPS`, `WriteIOPS` | avg | Count/Second |
| `elasticache` | `AWS/ElastiCache` / `CacheClusterId` (por nó) | error | `ErrorCount`, `AuthenticationFailures` | sum | Count |
| | | latency | `SuccessfulReadRequestLatency`, `SuccessfulWriteRequestLatency` | avg | Microseconds |
| | | saturation | `EngineCPUUtilization`, `DatabaseMemoryUsagePercentage` | max | Percent |
| | | saturation | `CurrConnections` | max | Count |
| | | saturation | `Evictions` | sum | Count |
| | | traffic | `CacheHits`, `CacheMisses` | sum | Count |
| `elasticache-serverless` | `AWS/ElastiCache` / `clusterId` | error | `ThrottledCmds`, `AuthenticationFailures` | sum | Count |
| | | latency | `SuccessfulReadRequestLatency`, `SuccessfulWriteRequestLatency` | avg | Microseconds |
| | | saturation | `ElastiCacheProcessingUnits` | sum | Count |
| | | saturation | `BytesUsedForCache` | max | Bytes |
| | | saturation | `CurrConnections` | max | Count |
| | | traffic | `TotalCmdsCount` | sum | Count |
| | | traffic | `CacheHitRate` | avg | None |
| `sqs` | `AWS/SQS` / `QueueName` | latency | `ApproximateAgeOfOldestMessage` | max | Seconds |
| | | saturation | `ApproximateNumberOfMessagesVisible`, `ApproximateNumberOfMessagesNotVisible` | max | Count |
| | | traffic | `NumberOfMessagesSent`, `NumberOfMessagesReceived`, `NumberOfMessagesDeleted` | sum | Count |
| `sns` | `AWS/SNS` / `TopicName` | error | `NumberOfNotificationsFailed` | sum | Count |
| | | traffic | `NumberOfMessagesPublished`, `NumberOfNotificationsDelivered`, `NumberOfNotificationsFilteredOut` | sum | Count |
| | | traffic | `PublishSize` | avg | Bytes |

A dimensão `DBInstanceIdentifier` e as métricas do Aurora por cluster (inclusive `ACUUtilization`) não foram conferidas na documentação; sem pontos, o item sai `value: null`, sem erro. `ErrorCount` e `AuthenticationFailures` só existem em versões recentes do motor. A unidade impressa é a da tabela, não a da resposta. Uma categoria sem métrica (o RDS não tem erro; a fila e o tópico não têm saturação ou latência equivalentes) simplesmente não tem item.

### Agregação na janela

- `period` = o maior entre 60 e `ceil(since_seconds / 3600) * 60` segundos (no máximo 60 pontos por métrica): 60 em 30 min, 1440 em 24 h.
- `start-time` = agora − `since_seconds`, `end-time` = agora (UTC, ISO 8601, segundos).
- `value` sobre os pontos da janela: `sum` → soma; `avg` → média dos pontos; `max` → máximo; `min` → mínimo; sem ponto → `null` com `datapoints: 0`.
- Cache por nós: a mesma regra sobre os pontos de todos os nós juntos (`sum` soma os nós, `max` pega o pior nó, `avg` é a média de todos os pontos), `datapoints` é o total e `nodes` o número de nós lidos.

## Saída

Um item por métrica, na ordem da tabela:

```json
{"name": "ReadLatency", "stat": "avg", "value": 0.003, "kind": "latency", "unit": "Seconds", "period": 60, "datapoints": 2}
{"name": "CacheHits", "stat": "sum", "value": 35, "kind": "traffic", "unit": "Count", "period": 60, "datapoints": 3, "nodes": 2}
```

- `stat` em minúsculas (`sum`, `avg`, `max`, `min`; o adaptador manda `Sum`, `Average`, `Maximum`, `Minimum` ao CloudWatch); `kind` em `error`, `latency`, `saturation` ou `traffic`; `value` número finito ou `null`; `datapoints` inteiro ≥ 0; `period` múltiplo de 60.
- Nenhuma métrica com ponto: `status: ok`, todo `value: null` e `message: "sem dados na janela"` (recurso inexistente, ocioso ou inativo).
- `truncated: true`: `StatusCode` `PartialData` na última página lida (a resposta sem `NextToken`, ou a 5ª página; nas intermediárias o status só diz que há mais páginas), mais de 5 páginas, mais de 6 nós, ou mais itens que `limits.lines` (corta na ordem da tabela).
- Consulta com `Forbidden` ou `InternalError`: aquela métrica sai `value: null` e a mensagem é `"dados parciais"`.
- Todo texto passa por `\b[0-9]{12}\b` → `[REDACTED]` no próprio adaptador, e o núcleo ainda aplica a redaction e a máscara do profile (ADR-0025 regra 5).

## Erros

Saem com exit 0, `status: error`, `items: []` e uma mensagem fixa, **sem** o stderr da CLI (que pode citar o profile, o ARN e a conta). Os gatilhos são os mesmos do adaptador `aws-messaging` (`references/probes/aws-messaging.md`):

| Mensagem | Quando |
|---|---|
| `aws não encontrado` | sem `aws` no `PATH` do adaptador |
| `renove o login da nuvem` | SSO ou token expirado |
| `profile inexistente` | o profile do `access.cloud` não existe nesta máquina |
| `sem credenciais da nuvem` | "Unable to locate credentials" |
| `sem permissão (AccessDenied)` | `AccessDenied`, `AuthorizationError` ou "not authorized" na chamada |
| `limite de chamadas da nuvem` | `Throttling`, "Rate exceeded" |
| `sem conexão com a nuvem` | "Could not connect to the endpoint URL", erro de DNS |
| `timeout` | "Read timeout", "Connect timeout", ou o processo passou de 30 s |
| `recurso sem região no atlas` | o recurso não tem `region` |
| `tipo de recurso sem sinais` | tipo sem conjunto (datastore sem `type`, `type` trocado, `memcached`, outro kind) |
| `chamada não permitida` | capacidade, verbo, operação ou opção fora da lista, recusado sem chamar a CLI |
| `entrada inválida` | stdin que não é `probe@2` bem formado, profile, região ou nome fora da regra, `serverless` não booleano, caractere de controle |
| `falha da aws` / `resposta inválida da aws` | outro erro, ou JSON sem a forma esperada |

O adaptador não grava nada; o `probes.log` é do núcleo, com `resource` e sem resultado nem acesso (ADR-0025 regra 6).

## Exemplos do contrato

Blocos lidos pelo teste de contrato (CT-01) contra os validadores `probe@2` do núcleo.

```json probe@2 describe valid
{"contract": "probe@2", "adapter": "cloudwatch", "capabilities": {"signals": {"verbs": ["metrics"], "targets": ["datastore", "queue", "topic"], "access": ["cloud"]}}}
```

```json probe@2 describe invalid
{"contract": "probe@2", "adapter": "cloudwatch", "capabilities": {"signals": {"verbs": ["metrics"], "targets": ["database"], "access": ["cloud"]}}}
```

```json probe@2 describe invalid
{"contract": "probe@2", "adapter": "cloudwatch", "capabilities": {"signals": {"verbs": ["metrics"], "targets": ["datastore"], "access": ["aws"]}}}
```

```json probe@2 input valid
{"contract": "probe@2", "capability": "signals", "verb": "metrics", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "resource": {"kind": "datastore", "id": "orders-db", "attrs": {"type": "rds", "engine": "postgres", "serverless": false, "region": "us-east-1"}}, "cloud": {"profile": "acme-dev-read"}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "cloudwatch", "capability": "signals", "verb": "metrics", "status": "ok", "items": [{"name": "ReadLatency", "stat": "avg", "value": 0.003, "kind": "latency", "unit": "Seconds", "period": 60, "datapoints": 2}, {"name": "WriteLatency", "stat": "avg", "value": null, "kind": "latency", "unit": "Seconds", "period": 60, "datapoints": 0}, {"name": "CPUUtilization", "stat": "max", "value": 70, "kind": "saturation", "unit": "Percent", "period": 60, "datapoints": 2}], "truncated": true}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "cloudwatch", "capability": "signals", "verb": "metrics", "status": "ok", "items": [{"name": "CacheHits", "stat": "sum", "value": 35, "kind": "traffic", "unit": "Count", "period": 60, "datapoints": 3, "nodes": 2}], "truncated": true, "message": "dados parciais"}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "cloudwatch", "capability": "signals", "verb": "metrics", "status": "error", "items": [], "truncated": false, "message": "renove o login da nuvem"}
```

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "cloudwatch", "capability": "signals", "verb": "metrics", "status": "ok", "items": [{"name": "ReadLatency", "stat": "avg", "value": {"avg": 0.003, "max": 0.004}, "kind": "latency"}], "truncated": false}
```

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "cloudwatch", "capability": "signals", "verb": "metrics", "status": "ok", "items": [{"name": "ReadLatency", "stat": "avg", "value": NaN, "kind": "latency", "unit": "Seconds", "period": 60, "datapoints": 2}], "truncated": false}
```

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "cloudwatch", "capability": "signals", "verb": "metrics", "status": "ok", "items": [], "truncated": false, "namespace": "AWS/RDS"}
```
