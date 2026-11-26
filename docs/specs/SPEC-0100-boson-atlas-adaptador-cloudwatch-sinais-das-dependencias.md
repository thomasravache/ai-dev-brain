---
id: SPEC-0100
title: "boson-atlas: adaptador cloudwatch — sinais das dependências"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-24
parent: SPEC-0095
depends_on: [SPEC-0096]
consumes_contract: []
contract_version: 2
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/assets/probes/cloudwatch.py, skills/boson-atlas/references/probes/cloudwatch.md, skills/boson-atlas/tests/test_probe_cloudwatch.py, skills/boson-atlas/tests/fixtures/cloudwatch/**, skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0023, ADR-0025, ADR-0026]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-24
---

# SPEC-0100 — boson-atlas: adaptador cloudwatch — sinais das dependências

> Origem: épico SPEC-0095, onda 2. É o adaptador que dá à verificação depois do deploy os sinais (erro, latência, saturação e tráfego) dos bancos, caches, filas e tópicos que o serviço usa.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Adaptador `cloudwatch` do contrato `probe@2` (SPEC-0096, ADR-0025) para a capacidade `signals`, com o verbo `metrics`. Ele usa a AWS CLI da máquina, **só para leitura**, com o profile do ambiente e a região do recurso, e responde: como estão os sinais deste recurso na janela?

Para cada tipo de recurso há um **conjunto fixo** de métricas oficiais do CloudWatch, separadas em erro, latência, saturação e tráfego. Todas vão numa consulta em lote (`get-metric-data`), e cada métrica vira um item agregado na janela `limits.since_seconds`. Nenhum nome de métrica vem do atlas nem da chamada.

## 2. Motivação & Escopo
**Motivação:** o `verify@2` (SPEC-0102, ADR-0026 regra 3) dá `failed` em `signals` quando uma métrica de erro ou de latência de uma dependência piora contra a foto de antes do merge. A rotina real (SPEC-0075) já olha esses painéis à mão. Sem o adaptador, a verificação fica "não verificado".

**Objetivos (dentro do escopo):**
- **`assets/probes/cloudwatch.py`:** só stdlib, Python 3.9 ou mais novo. Usa `--describe` e o protocolo `probe@2`.
- **`metrics`** para os alvos:
  - `datastore` com `type: rds` (instância avulsa, ou cluster Aurora quando o `engine` começa com `aurora`, inclusive Aurora Serverless) ou `type: elasticache` (Valkey ou Redis OSS, por nós ou serverless, pelo atributo `serverless`);
  - `queue` (SQS);
  - `topic` (SNS).
- **Métricas fixas por tipo** (tabela da seção 6), com o `kind` (erro, latência, saturação ou tráfego), a estatística e a unidade de cada uma.
- **Um item por métrica**, com os campos da tabela 4a do ADR-0026 (`name`, `stat` em minúsculas, `value` agregado na janela, `kind`) e, a mais, `unit`, `period` e `datapoints`.
- **Consulta em lote** e **limite de custo:** uma chamada `get-metric-data` por execução, no máximo 60 consultas e 5 páginas.
- **Lista fechada** de operações e opções da AWS CLI; o resto é recusado antes de executar.
- **Login expirado:** `status: error` com o texto fixo "renove o login da nuvem".
- `references/probes/cloudwatch.md`: configuração, política IAM mínima, a tabela das métricas, saída, erros e os blocos de contrato de exemplo.

**Não-objetivos (fora do escopo):**
- Métrica livre, pedida pela pessoa ou escrita no atlas; expressões `SEARCH` ou Metrics Insights.
- Alarmes do CloudWatch (`describe-alarms`), logs do CloudWatch e painéis.
- Memcached (`type: elasticache`, `engine: memcached`): as métricas dele são por nó e diferentes das do Valkey; sai "tipo de recurso sem sinais" e entra numa emenda.
- RDS Proxy, DynamoDB, S3, Lambda e `bucket`: entram como tipos novos numa emenda, quando o atlas os mapear.
- Linha de base e veredito: quem compara contra a foto é o `verify@2` (SPEC-0102).
- Estado da fila e da DLQ: é do adaptador de mensageria (SPEC-0098).

## 3. Dependências
- **Implementações necessárias:** SPEC-0096 — o IT-01, o IT-02 e o CT-01 rodam o núcleo real (`probe --resource`, entrada `probe@2` com `target.resource` e `target.cloud.profile`, validador `probe@2`).
- **Contratos consumidos:** N/A — a implementação da SPEC-0096 já é dependência.
- **Pré-requisitos externos:** AWS CLI v2 no PATH (usa `--no-cli-pager`), com um profile só de leitura por ambiente em `access.cloud`. Nos testes ela é substituída por um dublê.

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **adaptador `kubernetes`:** `assets/probes/kubernetes.py` (SPEC-0089), com lista fechada, erros com mensagem fixa e exit 0 e o dublê que registra o argv;
- **adaptador `aws-messaging`:** a mesma família de chamadas da AWS CLI, opções globais e mensagens de erro (SPEC-0098);
- **contrato:** `probe@2` (SPEC-0096, ADR-0025).

**Decisão:** script próprio em `assets/probes/cloudwatch.py`. O tipo do recurso sai do `kind` e dos `attrs`; o conjunto de métricas sai de uma tabela fixa no próprio adaptador; as consultas são montadas como JSON pelo adaptador e enviadas numa só chamada `cloudwatch get-metric-data`. Para um cache por nós, o adaptador lê os nós do grupo de replicação com `elasticache describe-replication-groups` (só leitura) e agrega as métricas deles.

**Agregação na janela:**
- `period` = o maior entre 60 e `ceil(since_seconds / 60 / 60) * 60` segundos, para ter no máximo 60 pontos por métrica;
- `start-time` = agora − `since_seconds`, `end-time` = agora (UTC, ISO 8601, segundos);
- `value` sobre os pontos da janela: `sum` → soma; `avg` → média dos pontos; `max` → máximo; `min` → mínimo; sem ponto → `null`, com `datapoints: 0`;
- cache por nós com vários nós: a mesma regra sobre os pontos de todos os nós juntos (`sum` soma os nós, `max` pega o pior nó), com `nodes` no item.

**Justificativa:**
- o `get-metric-data` aceita até 500 consultas por chamada (documentação oficial, conferida em 2026-11-24), então um recurso cabe numa chamada só;
- a tabela fixa no adaptador mantém o atlas como dado, nunca como instrução (ADR-0025), e deixa o custo previsível;
- quatro categorias dão ao `verify@2` o que ele compara (erro e latência) e à pessoa o contexto (saturação e tráfego).

**Desvio do padrão existente:** nenhum.

**Alternativas descartadas:**
- **`get-metric-statistics`:** uma chamada por métrica, mais lenta e com mais chamadas para o mesmo custo de leitura.
- **Expressão `SEARCH` pelo prefixo do grupo de replicação:** pode casar caches de outros serviços com nome parecido.
- **Métricas configuráveis por projeto:** abririam a porta para métrica livre; um tipo ou métrica nova entra por emenda desta spec.
- **Percentis (`p99`) de latência:** o suporte a percentil não foi conferido métrica a métrica; ficam as estatísticas padrão, revisável numa emenda.

**ADRs:** ADR-0010 (credencial só por nome), ADR-0023 (probes), ADR-0025 (alvo de recurso, acesso local, `probe@2`), ADR-0026 (agregados por métrica na foto; `signals` compara erro e latência).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:**
  - uma chamada `get-metric-data` por execução, até 5 páginas (`NextToken`); acima disso, `truncated: true`;
  - no máximo 60 consultas por execução (cache por nós: até 6 nós; acima disso, os 6 primeiros em ordem de nome e `truncated: true`);
  - no máximo uma `describe-replication-groups`;
  - cada chamada com `--cli-read-timeout 20 --cli-connect-timeout 10`, e o processo com timeout de 30 s.
- **Segurança:**
  - lista fechada de operações e opções; recusa antes de executar;
  - nenhum nome de métrica, namespace, dimensão ou expressão vem da entrada: só o nome do recurso, conferido por regex, entra no valor da dimensão;
  - o profile vem só de `target.cloud.profile` e nunca é impresso;
  - mensagens de erro fixas, sem o stderr da AWS CLI; ids de conta (12 dígitos) mascarados no adaptador.
  - Verificado pelos UT-04, UT-05 e IT-01.
- **Privacidade e dados pessoais:** N/A — só agregados numéricos de métricas de infraestrutura, sem dado de linha nem de cliente.
- **Disponibilidade e resiliência:**
  - `aws` ausente → "aws não encontrado"; login expirado → "renove o login da nuvem";
  - recurso sem dados na janela (inexistente, ocioso ou inativo) → itens com `value: null`, `datapoints: 0`, `status: ok` e a mensagem "sem dados na janela";
  - consulta com `StatusCode` `PartialData` → `truncated: true`; `Forbidden` ou `InternalError` numa consulta → `value: null` naquela métrica e a mensagem "dados parciais".
- **Acessibilidade (UI):** N/A — sem interface gráfica.
- **Custo:** o `GetMetricData` é cobrado por métrica pedida (página de preços da AWS não conferida nesta data). O teto por execução é de 60 métricas: 9 no `rds`, até 8 no `rds-aurora`, 10 por nó no `elasticache`, 9 no `elasticache-serverless`, 6 no `sqs` e 5 no `sns`. O `verify@2` limita o número de recursos (`--max-resources`, ADR-0026). Medido pelo argv registrado no UT-05 (contagem de consultas).

## 6. Artefato A — Contrato
**Interface:** a descrição e o verbo `metrics` do adaptador `cloudwatch`.

```text
--describe → {"contract": "probe@2", "adapter": "cloudwatch",
              "capabilities": {"signals": {"verbs": ["metrics"], "targets": ["datastore", "queue", "topic"],
                                           "access": ["cloud"]}}}

entrada (probe@2, SPEC-0096):
  target.resource = {"kind": "datastore"|"queue"|"topic", "id": "<id do nó>", "attrs": {escalares do nó}}
  target.cloud.profile; limits.since_seconds (1..86400) = a janela; limits.lines (1..2000) corta os itens
  nenhuma outra chave da entrada escolhe métrica, namespace, estatística ou dimensão

tipo do recurso (atributos do coletor aws, SPEC-0097: type, engine, serverless, region; id = identificador):
  attrs.type precisa casar com o kind: rds ou elasticache → datastore; sqs → queue; sns → topic
    (queue e topic sem attrs.type valem sqs e sns); outro, ausente no datastore ou trocado → "tipo de recurso sem sinais"
  rds:   engine começa com "aurora" (aurora-postgresql, aurora-mysql, ...) → conjunto "rds-aurora" (cluster);
         outro engine ou ausente → conjunto "rds" (instância)
  elasticache: serverless true → conjunto "elasticache-serverless"; serverless false ou ausente, engine
         valkey ou redis → conjunto "elasticache" (por nós); engine memcached ou outro → "tipo de recurso sem sinais"
  serverless: booleano JSON; outro tipo → "entrada inválida"
  attrs.region      ^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$ (ADR-0025); ausente → "recurso sem região no atlas"; fora da regra → "entrada inválida"
  nome do recurso   o id do nó (`target.resource.id`, o identificador do recurso no coletor); vira o valor da dimensão;
                    ARN ou URL em atributo: ignorado
    rds e rds-aurora ^[A-Za-z][A-Za-z0-9-]{0,62}$; elasticache e elasticache-serverless ^[A-Za-z][A-Za-z0-9-]{0,39}$;
    fila ^[A-Za-z0-9_-]{1,80}(\.fifo)?$, tópico ^[A-Za-z0-9_-]{1,256}(\.fifo)?$; fora → "entrada inválida"
  profile           ^[A-Za-z0-9_.+-]{1,64}$, sem começar com "-"; fora → "entrada inválida"

chamadas permitidas (argv começa com <serviço> <operação>; sempre com --region <attrs.region>,
--profile <target.cloud.profile>, --output json, --no-cli-pager, --cli-read-timeout 20, --cli-connect-timeout 10):
  cloudwatch get-metric-data --metric-data-queries <JSON montado pelo adaptador, só MetricStat da tabela>
      --start-time <ISO> --end-time <ISO> --scan-by TimestampAscending [--next-token <token devolvido>]
  elasticache describe-replication-groups --replication-group-id <valor da dimensão>   (só conjunto elasticache)
    ReplicationGroupNotFoundFault → o valor vale como CacheClusterId de um cluster sem grupo
  qualquer outra (list-metrics, get-metric-statistics, describe-alarms, put-*, set-*, delete-*,
  get-metric-widget-image, Expression nas consultas, --endpoint-url, --debug, --query, ...) → recusada
  antes de executar (status: error, "chamada não permitida")

metrics → itens, um por métrica da tabela (por nó agregado no elasticache), na ordem da tabela
(tabela 4a do ADR-0026: name, stat, value, kind; o resto é a mais e o verify@2 ignora):
  {"name": "ReadLatency", "stat": "avg", "value": 0.0021 | null, "kind": "latency",
   "unit": "Seconds", "period": 60, "datapoints": 30}
  elasticache por nós: mais "nodes": <número de nós lidos>
  stat ∈ sum | avg | max | min (o adaptador manda Sum, Average, Maximum, Minimum ao CloudWatch);
    count e p<n> são aceitos pela tabela 4a, mas nenhuma métrica desta versão os usa
  kind ∈ error | latency | saturation | traffic
  nunca dois itens com o mesmo par (name, stat)
  value: número JSON finito ou null; datapoints: inteiro ≥ 0; period: inteiro múltiplo de 60
  sem nenhum ponto em nenhuma métrica → status ok, message "sem dados na janela"
  StatusCode PartialData ou mais de 5 páginas ou mais de 6 nós → truncated: true
  consulta com Forbidden/InternalError → value null nessa métrica, message "dados parciais"

erros → exit 0, status: "error", items: [], message fixa (sem stderr, profile, ARN ou conta):
  "aws não encontrado" | "renove o login da nuvem" | "profile inexistente" | "sem credenciais da nuvem" |
  "sem permissão (AccessDenied)" | "limite de chamadas da nuvem" | "sem conexão com a nuvem" | "timeout" |
  "recurso sem região no atlas" | "tipo de recurso sem sinais" | "chamada não permitida" | "entrada inválida" |
  "falha da aws" | "resposta inválida da aws"
  (os gatilhos de cada mensagem no stderr são os mesmos do adaptador aws-messaging, SPEC-0098)
```

**Métricas fixas por conjunto.** Nomes, namespaces, dimensões e unidades conferidos na documentação oficial da AWS em 2026-11-24 (páginas de métricas do RDS, do ElastiCache por nós e Serverless, do SQS e do SNS), menos o que está marcado "não verificado".

| Conjunto | Namespace / dimensão | kind | Métrica | stat | Unidade |
|---|---|---|---|---|---|
| `rds` | `AWS/RDS` / `DBInstanceIdentifier` (dimensão não verificado) | latency | `ReadLatency`, `WriteLatency` | avg | Seconds |
| | | saturation | `CPUUtilization` | max | Percent |
| | | saturation | `DatabaseConnections`, `DiskQueueDepth` | max | Count |
| | | saturation | `FreeableMemory`, `FreeStorageSpace` | min | Bytes |
| | | traffic | `ReadIOPS`, `WriteIOPS` | avg | Count/Second |
| `rds-aurora` | `AWS/RDS` / `DBClusterIdentifier` (dimensão e métricas por cluster não verificado) | latency | `ReadLatency`, `WriteLatency` | avg | Seconds |
| | | saturation | `CPUUtilization` | max | Percent |
| | | saturation | `DatabaseConnections` | max | Count |
| | | saturation | `FreeableMemory` | min | Bytes |
| | | saturation | `ACUUtilization` (só com `serverless: true`; não verificado) | max | Percent |
| | | traffic | `ReadIOPS`, `WriteIOPS` | avg | Count/Second |
| `elasticache` | `AWS/ElastiCache` / `CacheClusterId` (por nó do grupo) | error | `ErrorCount`, `AuthenticationFailures` | sum | Count |
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

- O `rds` e o `rds-aurora` não têm métrica de erro no CloudWatch; o `sqs` e o `sns` não têm de saturação ou de latência equivalentes. A categoria ausente simplesmente não tem item, e o `verify@2` não inventa comparação.
- A unidade da tabela é a que o adaptador imprime; a da resposta não é usada.
- No Aurora, o CloudWatch agrega as métricas das instâncias pela dimensão `DBClusterIdentifier`; isso não foi conferido na página lida, e o adaptador confere com a primeira resposta real (sem pontos = `value: null`, sem erro).
- `ReadIOPS` e `WriteIOPS` aparecem na documentação como "Count per second"; o adaptador imprime `Count/Second`, o nome da unidade na API do CloudWatch.
- `ErrorCount` e `AuthenticationFailures` existem só em versões recentes do motor; num cache mais antigo, a métrica vem sem pontos (`value: null`).

**Máscara no adaptador:** todo texto da saída passa por `\b[0-9]{12}\b` → `[REDACTED]`; o núcleo ainda aplica a redaction e a máscara literal do profile (ADR-0025 regra 5).

**Registro:** o adaptador não grava nada; o `probes.log` é do núcleo, com `resource` e sem resultado.

**Esclarecimentos (Emenda v2):**
- `PartialData` só conta na última página lida (a resposta sem `NextToken`, ou a 5ª página): nas páginas intermediárias a AWS usa esse status para dizer que há mais páginas, e isso não marca `truncated`.
- O UT-03 cobre isso com 3 páginas: `PartialData` só nas intermediárias → `truncated: false`; `PartialData` na última → `truncated: true`. O UT-04 cobre valores `NaN`, `Infinity` e estouro na agregação (sum/avg não finitos) → "resposta inválida da aws".

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `assets/probes/cloudwatch.py` (novo).
- `references/probes/cloudwatch.md` (nova): configuração, política IAM mínima sugerida (`cloudwatch:GetMetricData` e `elasticache:DescribeReplicationGroups`), a tabela das métricas, a regra de agregação, saída, erros e os blocos `json probe@2 ...` válidos e inválidos lidos pelo CT-01.
- `SKILL.md`: o link para a referência, ao lado do `kubernetes`.
- `scripts/atlas.py`: só o `ATLAS_VERSION`.
- `tests/test_probe_cloudwatch.py` e `tests/fixtures/cloudwatch/` (AWS CLI falsa e respostas JSON).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Descrição | `--describe` | `probe@2`, `signals` com `metrics`, alvos `datastore`, `queue` e `topic`, acesso `cloud` | CT-01 |
| Banco RDS | `datastore` com `type: rds`, `engine: postgres` e pontos na janela | as 9 métricas do conjunto `rds`, com `name`, `stat` em minúsculas, `value` agregado e `kind` | UT-01, IT-01, CT-02 |
| Aurora e serverless | `type: rds` com `engine: aurora-postgresql` (com e sem `serverless`); `type: elasticache` com `serverless: true` | dimensão `DBClusterIdentifier` (`ACUUtilization` só com `serverless`); dimensão `clusterId` | UT-01, UT-03 |
| Cache por nós | grupo com 2 nós | uma `describe-replication-groups`; `Sum` soma os nós, `Maximum` pega o pior; `nodes: 2` | UT-02 |
| Cache sem grupo | `ReplicationGroupNotFoundFault` | o id vale como `CacheClusterId` | UT-02 |
| Cache serverless, fila e tópico | `type: elasticache` com `serverless: true`, `queue`, `topic` | as métricas da tabela com a dimensão certa (`clusterId`, `QueueName`, `TopicName`) | UT-03 |
| Janela e período | `since_seconds` 1800 e 86400 | `period` 60 e 1440; `start-time` e `end-time` da janela | UT-03 |
| Sem dados | nenhuma métrica com ponto | `value: null`, `datapoints: 0`, `status: ok`, "sem dados na janela" | UT-03 |
| Dados parciais | `PartialData`, mais de 5 páginas, mais de 6 nós, consulta `Forbidden` | `truncated: true` ou `value: null` com "dados parciais" | UT-03 |
| Login expirado | stderr de SSO expirado | `status: error`, "renove o login da nuvem", sem o profile | UT-04, IT-02 |
| Outros erros | aws ausente, profile inexistente, sem credenciais, AccessDenied, Throttling, sem conexão, timeout, JSON inválido | `status: error` com a mensagem fixa | UT-04 |
| Lista fechada e custo | qualquer execução | só `get-metric-data` (uma, até 5 páginas) e no máximo uma `describe-replication-groups`; até 60 consultas, só `MetricStat` da tabela | UT-05, IT-01 |
| Sem métrica livre | `attrs` com chaves como `metric`, `namespace` ou `expression` | ignoradas; as consultas são as da tabela | UT-05 |
| Entrada fora da regra | `type` ausente, trocado ou memcached, `serverless` não booleano, região inválida, nome com `-` no começo, profile com caractere de controle, stdin não `probe@2` | mensagem fixa, sem nenhuma chamada | UT-06 |
| Ponta a ponta | `atlas.py probe signals metrics --resource datastore:orders-db` com a AWS CLI falsa | saída validada pelo núcleo; profile e conta fora da saída e do `probes.log` | IT-01 |

## 7. Artefato B — Plano de Testes (TDD)
<!-- Todo teste tem um ID e é escrito ANTES da implementação (Red). No código, cada teste carrega a tag `SPEC-0100:<ID>` — o G1 (`spec_graph.py verify`) verifica. -->

### 7.1 Testes de Caracterização
- N/A — adaptador novo, sem comportamento anterior; o núcleo do probe tem os testes dele (SPEC-0096).

### 7.2 Testes Unitários
- **UT-01** — Dado a AWS CLI falsa com pontos para `orders-db` (por exemplo `ReadLatency` 0.002 e 0.004, `CPUUtilization` 40 e 70, `FreeStorageSpace` 9e9 e 8e9) e `since_seconds: 1800`, quando `metrics` roda para `datastore:orders-db` com `attrs: {type: rds, engine: postgres, serverless: false, region: us-east-1}`, então saem os 9 itens do conjunto `rds` na ordem da tabela, com a dimensão `DBInstanceIdentifier=orders-db`, `kind` e `unit` da tabela, `period: 60`, `datapoints` igual ao número de pontos e `value` 0.003 (`stat: avg`), 70 (`max`) e 8e9 (`min`); com `engine: aurora-postgresql`, as consultas usam `DBClusterIdentifier` e o conjunto `rds-aurora`, e `ACUUtilization` só entra com `serverless: true`.
- **UT-02** — Dado o grupo de replicação `orders-cache` com os nós `orders-cache-001` e `orders-cache-002`, quando `metrics` roda com `attrs: {type: elasticache, engine: valkey, serverless: false}`, então há uma só `describe-replication-groups`, as consultas usam `CacheClusterId` de cada nó, `CacheHits` (`sum`) soma os dois nós, `EngineCPUUtilization` (`max`) é o maior dos dois e cada item tem `nodes: 2`; com `ReplicationGroupNotFoundFault`, as consultas usam `CacheClusterId` igual ao id e `nodes: 1`.
- **UT-03** — Dado um `datastore` com `type: elasticache` e `serverless: true`, uma `queue` e um `topic`, quando `metrics` roda, então as consultas usam `clusterId`, `QueueName` e `TopicName` e as métricas da tabela; com `since_seconds` 1800 e 86400, `period` é 60 e 1440, e `end-time` − `start-time` é igual à janela; sem nenhum ponto, todo `value` é `null`, `datapoints: 0`, `status: ok` e a mensagem "sem dados na janela"; com `StatusCode: PartialData`, mais de 5 páginas ou 7 nós, `truncated: true`; com uma consulta `Forbidden`, aquela métrica sai `null` e a mensagem é "dados parciais".
- **UT-04** — Dado a AWS CLI falsa respondendo, em cada caso, SSO expirado, profile inexistente, sem credenciais, AccessDenied, Throttling, sem conexão, timeout, JSON inválido e outro erro (e, num caso, sem `aws` no PATH), quando `metrics` roda, então o adaptador sai com 0, `status: error`, `items: []` e a mensagem fixa ("renove o login da nuvem" no SSO); o profile e o id de conta do stderr falso não aparecem na saída.
- **UT-05** — O dublê registra cada argv. Em todos os testes, todo argv é `cloudwatch get-metric-data` ou `elasticache describe-replication-groups`, com `--region`, `--profile`, `--output json`, `--no-cli-pager` e os timeouts e nenhuma opção fora da lista; cada `--metric-data-queries` tem no máximo 60 consultas, todas `MetricStat` com namespace, métrica, dimensão e estatística da tabela, sem `Expression`; há no máximo uma `get-metric-data` por página (até 5) por execução. Com `attrs` trazendo `metric`, `namespace` e `expression`, as consultas são as mesmas da tabela.
- **UT-06** — Dado um `datastore` sem `type`, com `type: sqs`, com `engine: memcached` ou com `serverless: "sim"`, `attrs.region` ausente ou `us-east-1; rm`, um id (o identificador) que começa com `-`, uma fila com nome de 81 caracteres, um profile com quebra de linha e um stdin que não é `probe@2`, quando o adaptador roda, então sai "tipo de recurso sem sinais", "recurso sem região no atlas" (sem `attrs.region`) ou "entrada inválida", sem nenhuma chamada registrada.

### 7.3 Testes de Integração
- **IT-01** — Com o `atlas.py` real (núcleo `probe@2`), um atlas temporário com `service:api`, o deployment `dev-api` em `environment:dev` (`tier: test`) e as arestas para `datastore:orders-db` (`type: rds`, `engine: postgres`, `serverless: false`, `region: us-east-1`), `queue:orders` e `topic:orders-events`, o acesso local `access.cloud.dev.profile`, o adaptador declarado sem `command` em `probes.adapters.cloudwatch` e a AWS CLI falsa no PATH, quando `atlas.py probe signals metrics --service api --env dev --resource datastore:orders-db --since 30m --json` roda como processo, então a saída passa no validador do núcleo com os itens do UT-01; o argv registrado só tem as operações da lista; o profile e `123456789012` não aparecem na saída nem no `probes.log`, que tem a linha com `resource`.
- **IT-02** — No mesmo cenário, com a AWS CLI falsa respondendo SSO expirado, quando a mesma probe roda, então o exit é 1, a saída tem `status: error` e "renove o login da nuvem", e o `probes.log` registra `status: error` sem o profile.

### 7.4 Testes de Contrato
- **CT-02** — As saídas reais de `metrics` dos UT-01 a UT-03, quando conferidas contra a tabela 4a do ADR-0026 (a mesma tabela que o `verify@2` lê), cumprem: todo item tem `name` texto não vazio, `stat` em `sum`, `count`, `avg`, `min`, `max` ou `p<n>`, `value` número finito ou `null` e `kind` em `error`, `latency`, `saturation` ou `traffic`, sem dois itens com o mesmo (`name`, `stat`); um item com `category` no lugar de `kind`, `stat` `Average` ou `value` em texto é recusado pela mesma conferência.
- **CT-01** — O `--describe` real do adaptador, as saídas reais de `metrics` (com valores, sem dados e de erro, geradas com o dublê) e os blocos `json probe@2 ...` válidos de `references/probes/cloudwatch.md` passam no validador `probe@2` do núcleo (SPEC-0096); os blocos marcados `invalid` (`targets` com kind desconhecido, `access` desconhecido, item com objeto aninhado, `value` `NaN`, chave a mais na saída) são recusados.

### 7.5 Testes E2E
- N/A — CLI sem jornada de usuário; o IT-01 roda o comando de ponta a ponta com o dublê.

### 7.6 Outros
- N/A — custo e segurança (lista fechada, teto de consultas, sem métrica livre) estão nos UT-05 e UT-06 e no IT-01.

**Dublês e dados de teste:**
- `tests/fixtures/cloudwatch/fake_aws.py`, copiado como `aws` numa pasta do PATH: responde a `get-metric-data` pelos `Id` das consultas e a `describe-replication-groups` a partir de cenários JSON ao lado dele, registra cada argv num arquivo da pasta temporária e falha o teste com qualquer operação fora da lista.
- Respostas só com nomes `acme`, `orders-db`, `orders-cache`, `orders`, `orders-events`, região `us-east-1` e a conta de exemplo `123456789012` (que precisa sair mascarada).
- Relógio: os testes não fixam o "agora"; conferem que `end-time` − `start-time` é igual a `since_seconds` e que `end-time` está a poucos segundos do relógio do teste.
- Sem AWS de verdade e sem rede; HOME, `XDG_CONFIG_HOME` e `ATLAS_CONFIG_HOME` temporários, nenhum `~/.aws` real.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, pela versão do plugin. Só roda com `probes.enabled: true`, o adaptador declarado em `probes.adapters.cloudwatch` com `metrics` liberado e `access.cloud.<ambiente>.profile` definido.
- **Dados/schema:** N/A — nada persistido.
- **Compatibilidade:** aditivo; o `probe@1` e os outros adaptadores não mudam. Depende dos atributos `type`, `engine`, `serverless` e `region` do coletor `aws` (SPEC-0097), com o id igual ao identificador do recurso; um atlas escrito à mão com esses atributos também serve. Os itens seguem a tabela 4a do ADR-0026; métrica ou conjunto novo entra por emenda, e mudar a forma dos itens sobe o `contract_version`.
- **Observabilidade:** o `probes.log` do núcleo, com `resource` e `status`; o `doctor` mostra o adaptador e se a `aws` foi encontrada.
- **Rollback:** tirar o adaptador de `probes.adapters` (a verificação de sinais volta a "não verificado") ou voltar a versão do plugin.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Quais métricas por tipo? — As da tabela da seção 6 (com Aurora por `DBClusterIdentifier` e o cache serverless pelo atributo `serverless`), separadas em erro, latência, saturação e tráfego, com os nomes oficiais conferidos na documentação da AWS em 2026-11-24 (a dimensão `DBInstanceIdentifier` do RDS e as métricas do Aurora por cluster, inclusive `ACUUtilization`, não foram conferidas na página lida) (Architect, 2026-11-24, recomendado)
- [x] Como agregar a janela? — `period` de 60 s ou maior, para no máximo 60 pontos, e o valor pela estatística da métrica (soma, média, máximo ou mínimo dos pontos); sem ponto, `null` com `datapoints: 0` (Architect, 2026-11-24, recomendado)
- [x] Cache por nós: um nó ou o grupo? — O grupo: lê os nós com `describe-replication-groups` e agrega, para não esconder um nó quente (Architect, 2026-11-24, recomendado)
- [x] Percentis de latência? — Não nesta versão; `Sum`, `Average`, `Maximum` e `Minimum` são estatísticas padrão de toda métrica, e o suporte a percentil não foi conferido métrica a métrica; percentil entra por emenda (Architect, 2026-11-24, recomendado)
- [x] Pode haver métrica configurável pelo projeto? — Não: abriria métrica livre; mudança na tabela é emenda desta spec (Architect, 2026-11-24, recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Contrato e implementação**
- [ ] Red: UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, IT-01, IT-02, CT-02, CT-01 com a tag `SPEC-0100:<ID>`, falhando pelo motivo certo
- [ ] Green: implementar o mínimo para passar, seguindo o padrão de referência da seção 4
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy (G6): N/A — skills distribuídas por cópia e pelo plugin
- [ ] Relatório de Entrega, CHANGELOG e versão do plugin (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — e297cb0 | 2026-11-24 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=100, skipped=1)) — 01461f1 | 2026-11-25 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (Installed 1 package in 4ms) — 8284c0c | 2026-11-25 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — d2fd17b | 2026-11-25 |
| G4 Review | FAIL | reviewer independente: CHANGES_REQUESTED — major: a regra da Emenda v2 (PartialData só na última página) não tem teste que a prove (mutante passa); minors: overflow vira Infinity, OverflowError sem tratamento, NaN/Infinity sem teste | 2026-11-25 |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

### Histórico de reprovações
- G4 FAIL 2026-11-25 — reviewer independente: CHANGES_REQUESTED — major: a regra da Emenda v2 (PartialData só na última página) não tem teste que a prove (mutante passa); minors: overflow vira Infinity, OverflowError sem tratamento, NaN/Infinity sem teste — 599f0ca

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). -->

### O que foi entregue

### Como foi feito

### Prova de Correção

### Verificação
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

### Pendências

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0100`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-25 | `PartialData` só marca `truncated` na última página lida | Achado do Test-writer: nas páginas intermediárias o status só indica que há mais páginas | nenhuma | thomas, 2026-11-25 (piloto automático com o recomendado) |
