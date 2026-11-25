# Collector `aws`

Category `data` (`--services rds,elasticache`) or `messaging` (`--services sqs,sns`). Reads, with the AWS CLI of the machine and **only metadata**, the managed databases (RDS, Aurora, Aurora Serverless), the caches (ElastiCache replication groups, standalone clusters and serverless caches), the SQS queues with their dead-letter queue, the SNS topics and the confirmed SNS → SQS subscriptions, and prints the `boson-atlas/collector@1` output (`references/collector-contract.md`, ADR-0011). The ids are the resource names, so the `build` links the services to them with the existing rules (`config_refs` of the `argocd` collector, `references/graph.md`, rule 2). No ARN, queue URL, account id, subscription owner or filter content reaches the snapshot (ADR-0025) (SPEC-0097).

## Setup

1. Install the AWS CLI v2 and create a **read-only** profile (SSO or role). The collector never runs `aws sso login`, never reads `~/.aws` and never handles a key: the CLI does. Minimum IAM policy:

```text
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "rds:DescribeDBClusters", "rds:DescribeDBInstances",
      "elasticache:DescribeReplicationGroups", "elasticache:DescribeCacheClusters",
      "elasticache:DescribeServerlessCaches",
      "sqs:ListQueues", "sqs:GetQueueAttributes",
      "sns:ListTopics", "sns:ListSubscriptions", "sns:GetSubscriptionAttributes"
    ],
    "Resource": "*"
  }]
}
```

2. Declare two collectors in `atlas-config.yml` (a collector has one category; two collectors also keep the failures apart: without ElastiCache permission the queues are still collected):

```yaml
collectors:
  - id: aws-data
    category: data
    command: ["python3", "{skill}/assets/collectors/aws.py", "--services", "rds,elasticache", "--region", "us-east-1"]
    timeout: 600
  - id: aws-messaging
    category: messaging
    command: ["python3", "{skill}/assets/collectors/aws.py", "--services", "sqs,sns", "--region", "us-east-1,sa-east-1"]
    timeout: 600
```

3. Declare the profile **by name only** in the local configuration of each machine (`references/config.md`), never in the shared `atlas-config.yml`:

```yaml
credentials:
  aws-data:      {profile: <read-only profile name>}
  aws-messaging: {profile: <read-only profile name>}
```

The `scan` passes the name to that collector only, as `ATLAS_COLLECTOR_PROFILE`; the collector gives it to the AWS CLI as `AWS_PROFILE` and removes `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` and `AWS_DEFAULT_PROFILE` from the CLI environment, so the profile is what counts. Without a declared profile the CLI uses the default chain of the machine. The profile name is never printed. Two accounts (dev and prod) = two collectors with two profiles in the same `scan`.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--services` | required | `rds`, `elasticache`, `sqs`, `sns`, comma separated, of one category only (`rds`, `elasticache` → `data`; `sqs`, `sns` → `messaging`) |
| `--region` | required | 1 to 10 regions, comma separated, each in `^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$`, no repetition |
| `--max-items` | `1000` | 1 to 10000; passed to every list call in every region |

Invalid arguments exit with 2 and a fixed message, without calling the CLI: `aws: --services precisa de rds, elasticache, sqs ou sns`, `aws: misture serviços de dados (rds, elasticache) e de mensageria (sqs, sns) em coletores separados`, `aws: --region precisa de 1 a 10 regiões válidas, sem repetição`, `aws: --max-items precisa ser um inteiro de 1 a 10000`.

## CLI calls

Only this closed table is ever run (`build_call`): argv as a list, never a shell, stdin closed, a 60 s timeout per process, and always `--region <r> --output json --no-cli-pager --cli-connect-timeout 10 --cli-read-timeout 30`. Anything else is refused before running (`aws: chamada não permitida`).

| Service | Operation | Arguments |
|---|---|---|
| `rds` | `describe-db-clusters` | `--max-items N` |
| `rds` | `describe-db-instances` | `--max-items N` |
| `elasticache` | `describe-replication-groups` | `--max-items N` |
| `elasticache` | `describe-cache-clusters` | `--show-cache-node-info --max-items N` |
| `elasticache` | `describe-serverless-caches` | `--max-items N` |
| `sqs` | `list-queues` | `--max-items N` |
| `sqs` | `get-queue-attributes` | `--queue-url <URL from list-queues> --attribute-names RedrivePolicy` (never `All`: the `Policy` holds account ids) |
| `sns` | `list-topics` | `--max-items N` |
| `sns` | `list-subscriptions` | `--max-items N` |
| `sns` | `get-subscription-attributes` | `--subscription-arn <ARN from list-subscriptions, protocol sqs, confirmed>` |

Per region: one call per list operation, one `get-queue-attributes` per queue and one `get-subscription-attributes` per confirmed SQS subscription. No argument comes from the atlas: URLs and ARNs come only from the previous list. Suggested collector `timeout`: 600 s.

## Output

`collector` `aws`, `source` `aws` everywhere; entities ordered by `kind:id`, relations by `from`/`type`/`to`.

- **`datastore:<name>`** — `type` (`rds` or `elasticache`), `engine` (lower case: `aurora-postgresql`, `postgres`, `valkey`, `redis`, `memcached`, …), `host` (writer or configuration endpoint), `port` (integer, from the same endpoint), `reader_host` (only when there is one; informative), `region`, `serverless`.
  - RDS clusters (Aurora, Multi-AZ DB cluster): id `DBClusterIdentifier`; `serverless` when `EngineMode` is `serverless` or `ServerlessV2ScalingConfiguration` is present. Instances that belong to a cluster are not entities; standalone instances are, by `DBInstanceIdentifier`.
  - ElastiCache replication groups by `ReplicationGroupId` (engine of the group or, missing, of its member clusters; host = `ConfigurationEndpoint` in cluster mode, else the primary endpoint of the first node group), standalone clusters by `CacheClusterId` and serverless caches by `ServerlessCacheName` (`serverless: true`).
  - A resource without endpoint (creating, stopped) comes without `host` and `port`.
  - `migrations_table` never comes from AWS: it enters by curation or by a fact of the `generic` collector with the same `datastore:<id>` key, which the `build` merges.
- **`queue:<name>`** — `type: sqs`, `fifo`, `region`; `dlq` = the name of **another queue of the same output**, from `RedrivePolicy.deadLetterTargetArn` (a DLQ of another account or of a region not listed is omitted, stderr has only the count); `filtered_topics` = sorted topic names whose subscription to this queue has a non-empty `FilterPolicy` (never the filter itself).
- **`topic:<name>`** — `type: sns`, `fifo`, `region`.
- **`topic:<t> publishes queue:<q>`** — one per confirmed SQS subscription; `<q>` is the queue name of the endpoint, even in another region or account (a missing queue is a `broken-ref` warning of `lint`, not an error). Pending subscriptions and other protocols are ignored.
- **Never leaves:** ARN, URL, account id, `Owner`, `SubscriptionArn`, `FilterPolicy`, the whole `RedrivePolicy`, the profile name, the master user name, tags.
- **Safety net:** a resource with 12 digits in a row in its id, name or any attribute is dropped whole (`aws: <n> recurso(s) ignorado(s): 12 dígitos seguidos`).
- **Same name in two regions** of the same run: the first region of `--region` wins (`aws: <n> recurso(s) repetido(s) em outra região ignorado(s)`). Across accounts (two collectors) the `build` merges by id and shows the difference in `conflicts`: prefer unique names per environment.

Example `data` (the same as `tests/fixtures/contract/valid/data-aws.json`):

```json
{
  "contract": "boson-atlas/collector@1",
  "collector": "aws",
  "category": "data",
  "collected_at": "2026-11-24T12:00:00Z",
  "entities": [
    {"kind": "datastore", "id": "orders-cache", "name": "orders-cache", "attrs": {"engine": "valkey", "host": "orders-cache.abc123.ng.0001.use1.cache.amazonaws.com", "port": 6379, "reader_host": "orders-cache-ro.abc123.ng.0001.use1.cache.amazonaws.com", "region": "us-east-1", "serverless": false, "type": "elasticache"}, "source": "aws"},
    {"kind": "datastore", "id": "orders-db", "name": "orders-db", "attrs": {"engine": "aurora-postgresql", "host": "orders-db.cluster-abc123.us-east-1.rds.amazonaws.com", "port": 5432, "reader_host": "orders-db.cluster-ro-abc123.us-east-1.rds.amazonaws.com", "region": "us-east-1", "serverless": true, "type": "rds"}, "source": "aws"}
  ],
  "relations": []
}
```

Example `messaging` (the same as `tests/fixtures/contract/valid/messaging-aws.json`):

```json
{
  "contract": "boson-atlas/collector@1",
  "collector": "aws",
  "category": "messaging",
  "collected_at": "2026-11-24T12:00:00Z",
  "entities": [
    {"kind": "queue", "id": "orders", "name": "orders", "attrs": {"dlq": "orders-dlq", "fifo": false, "filtered_topics": ["order-events"], "region": "us-east-1", "type": "sqs"}, "source": "aws"},
    {"kind": "queue", "id": "orders-dlq", "name": "orders-dlq", "attrs": {"fifo": false, "region": "us-east-1", "type": "sqs"}, "source": "aws"},
    {"kind": "topic", "id": "order-events", "name": "order-events", "attrs": {"fifo": false, "region": "us-east-1", "type": "sns"}, "source": "aws"}
  ],
  "relations": [
    {"from": "topic:order-events", "to": "queue:orders", "type": "publishes", "source": "aws"}
  ]
}
```

## How the ids match in the `build`

Rule 2 of `references/graph.md`, unchanged: the host of a `config_refs` links the service to the `datastore`, `queue` or `topic` whose `attrs.host` or `name` is equal.

| `config_refs` of the deployment (`argocd` collector) | Matches | Why |
|---|---|---|
| `ORDERS_QUEUE_URL=orders` (from `https://sqs.<region>.amazonaws.com/<account>/orders`) | `queue:orders` | `argocd` reduces the URL to the name; the queue `name` is the name |
| `ORDER_EVENTS_TOPIC=order-events` (from `arn:aws:sns:<region>:<account>:order-events`) | `topic:order-events` | `argocd` reduces the ARN to the name |
| `DB_HOST=orders-db.cluster-abc123.us-east-1.rds.amazonaws.com` | `datastore:orders-db` | equal to `attrs.host` (writer endpoint) |
| `REDIS_HOST=orders-cache.abc123.ng.0001.use1.cache.amazonaws.com` | `datastore:orders-cache` | equal to `attrs.host` |
| `DB_HOST=orders-db` | `datastore:orders-db` | equal to `name` |
| `DB_READER_HOST=orders-db.cluster-ro-…` or an own CNAME | nothing | rule 2 looks only at `host` and `name`; `reader_host` is informative |

The DLQ of a linked queue is also a probe target through the `dlq` attribute (ADR-0025, rule 1), without an edge of its own. Who already keeps queues and databases in the `generic` collector gets the same node from two sources (same `kind:id`): the `build` merges them; delete the hand-written facts after the first good `scan`.

## Failure modes (exit 1, one fixed line on stderr, nothing on stdout)

The stderr of the AWS CLI is never repeated, nor the profile, URL, ARN or account. The first failure ends the collector; the `scan` shows `FALHA <id> — saiu com 1` with the line, keeps the previous snapshot and does not move `seen_at`.

| Message | When |
|---|---|
| `aws: AWS CLI não encontrada no PATH` | no `aws` executable |
| `aws: profile da AWS não encontrado — confira credentials.<id>.profile` | `ProfileNotFound`, "could not be found" |
| `aws: login da nuvem expirado — renove o login da nuvem` | expired SSO session or token (`Token has expired`, `UnauthorizedSSOTokenError`, `ExpiredToken`) |
| `aws: sem credencial da AWS — declare o profile em credentials do coletor` | `Unable to locate credentials` |
| `aws: sem permissão para <service> <operation> em <region>` | `AccessDenied`, `AccessDeniedException`, `UnauthorizedOperation`, `AuthorizationError`, "not authorized" |
| `aws: tempo esgotado em <service> <operation> (<region>)` | process timeout, read or connect timeout |
| `aws: limite de <N> itens atingido em <service> <operation> (<region>) — aumente --max-items` | `NextToken` in a list response: never a partial snapshot (it would create false removals) |
| `aws: resposta inválida da AWS CLI em <service> <operation>` | invalid JSON or a field of the wrong type |
| `aws: falha da AWS CLI em <service> <operation> (<region>)` | any other non-zero exit |
| `aws: chamada não permitida` | a call outside the closed table |

## Limits

- Out of scope: metrics, queue depth, message age and filter content (SPEC-0098, SPEC-0100); S3, DynamoDB, Kinesis, MSK, EventBridge, Lambda (future `--services`); linking by reader endpoint or own DNS.
- The collector does not check that the profile is read-only: that is the role's job.
