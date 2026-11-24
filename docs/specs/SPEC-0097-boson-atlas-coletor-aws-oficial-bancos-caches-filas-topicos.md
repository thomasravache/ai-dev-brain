---
id: SPEC-0097
title: "boson-atlas: coletor aws oficial — bancos, caches, filas, tópicos e assinaturas"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-11-24
parent: SPEC-0095
depends_on: []
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/assets/collectors/aws.py, skills/boson-atlas/references/collectors/aws.md, skills/boson-atlas/references/collector-contract.md, skills/boson-atlas/references/config.md, skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, skills/boson-atlas/tests/test_collector_aws.py, skills/boson-atlas/tests/fixtures/aws/**, skills/boson-atlas/tests/fixtures/contract/valid/*-aws.json, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0011, ADR-0025]
external: []
size: M
approved_by:
approved_at:
---

# SPEC-0097 — boson-atlas: coletor aws oficial — bancos, caches, filas, tópicos e assinaturas

> Origem: épico SPEC-0095, onda 1. O atlas de referência já mapeia bancos PostgreSQL gerenciados, caches compatíveis com Redis (Valkey), filas, tópicos e assinaturas tópico → fila, hoje por fatos escritos à mão (coletor `generic`). Este coletor traz esses recursos da conta, só lendo metadados, para que as probes de recurso (SPEC-0096) e o `verify@2` (SPEC-0102) tenham alvo.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Coletor `aws` da skill (`assets/collectors/aws.py`), no molde dos coletores `github` e `argocd`. Ele chama a AWS CLI da máquina só com uma lista fechada de operações `describe`/`list`/`get`, sem shell, e imprime a saída `boson-atlas/collector@1` (ADR-0011) com:
- **`datastore`:** instâncias e clusters RDS/Aurora (inclusive Aurora Serverless) e caches ElastiCache (grupos de replicação, clusters avulsos e caches serverless);
- **`queue`:** filas SQS, com a DLQ da redrive policy;
- **`topic`:** tópicos SNS;
- **relação `topic → queue` (`publishes`):** uma por assinatura SNS → SQS confirmada.

Os ids são os nomes dos recursos. Nenhum ARN, URL de fila, id de conta, dono de assinatura ou conteúdo de filtro chega ao snapshot. O `build` liga os serviços a esses recursos pelas regras que já existem (`config_refs` do `argocd`), sem mudança no grafo.

## 2. Motivação & Escopo
**Motivação:** sem os recursos da nuvem no grafo, a probe de recurso (ADR-0025) não tem alvo e a verificação das dependências fica "não verificado". Escrever bancos, filas e assinaturas à mão envelhece rápido e não traz o `host` nem a DLQ, que são justamente o que liga o serviço ao recurso e o que a verificação olha.

**Objetivos (dentro do escopo):**
- Coletor `aws` com `--services`, `--region` (uma ou mais) e `--max-items`, só leitura, sem shell, com o profile vindo da configuração local só pelo nome.
- Entidades `datastore`, `queue` e `topic` com os atributos escalares do contrato desta spec e a relação `topic → queue` `publishes`, sem kind nem tipo de relação novos (ADR-0011).
- `scan` passa o profile declarado em `credentials.<id>.profile` ao coletor daquele id, pela variável `ATLAS_COLLECTOR_PROFILE` (só o nome; qualquer coletor pode usar).
- Erros da AWS CLI (sem credencial, login expirado, profile ausente, sem permissão, tempo esgotado, limite atingido) viram falha do coletor com mensagem fixa, sem valores.
- Documentação: `references/collectors/aws.md` (setup, política IAM mínima, chamadas, saída e como os ids casam no `build`), `collector-contract.md` (uso de `publishes` entre tópico e fila e a variável do profile), `config.md` e `SKILL.md`.

**Não-objetivos (fora do escopo):**
- Métricas, profundidade de fila, idade de mensagem e conteúdo de filtros (SPEC-0098 e SPEC-0100).
- Buckets S3, DynamoDB, Kinesis, MSK, EventBridge, Lambda e demais serviços: entram depois como `--services` novos.
- Mudança nas regras de inferência do `build` (`references/graph.md`), inclusive ligar pelo endpoint de leitura ou por DNS próprio (CNAME).
- Contas e fornecedores como entidades (SPEC-0084) e infraestrutura como código (SPEC-0083).
- Fazer login na nuvem: a skill nunca roda `aws sso login` nem lê arquivos de credencial.

## 3. Dependências
- **Implementações necessárias:** N/A — usa o `scan`, o validador `@1` e o `build` que já existem.
- **Contratos consumidos:** N/A — o contrato `boson-atlas/collector@1` já está implementado (SPEC-0033) e não muda de versão.
- **Pré-requisitos externos:** AWS CLI v2 no PATH da máquina que roda o `scan`, com um profile só de leitura (política mínima em `references/collectors/aws.md`). Nos testes ela é substituída por um dublê.

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **coletor `argocd`** (`assets/collectors/argocd.py`, SPEC-0035): CLI externa com argv em lista, stdin fechado, timeout por chamada, só os campos necessários lidos da resposta, dublês `tests/fixtures/argocd/fake_kubectl.py` e `fake_argocd.py`;
- **`config_refs`** (SPEC-0076): o `argocd` já reduz uma URL de fila SQS ao nome da fila e um ARN SQS/SNS ao nome do recurso, e reduz um endpoint de banco ao host;
- **inferência do `build`** (`references/graph.md`, regra 2): o host de um `config_refs` liga o serviço ao `datastore`, `queue` ou `topic` cujo `attrs.host` ou `name` é igual;
- **credenciais só por nome** (`references/config.md`, ADR-0010).

**Decisão:**
- Script `assets/collectors/aws.py`, só biblioteca padrão. Cada chamada é montada de uma tabela fechada `(serviço, operação) → argumentos permitidos`, com `--region <r> --output json --no-cli-pager` e `--max-items <n>` nas operações de lista. Uma chamada fora da tabela é recusada antes de executar.
- Um coletor declarado tem uma categoria só (ADR-0011), então o coletor aceita só serviços de uma categoria por execução: `rds` e `elasticache` → `data`; `sqs` e `sns` → `messaging`. O setup recomendado declara dois coletores (`aws-data` e `aws-messaging`), o que também separa as falhas: sem permissão no ElastiCache, as filas continuam sendo coletadas.
- Ids = nome do recurso (identificador do RDS, id do grupo ou do cluster do ElastiCache, nome do cache serverless, nome da fila, nome do tópico). É o mesmo texto que o `argocd` tira de uma URL de fila ou de um ARN, então o `build` liga pelo `name` sem regra nova.
- A assinatura SNS → SQS vira a relação `topic:<t> publishes queue:<q>`, como o atlas de referência já modela. A presença de filtro fica no nó da fila (`filtered_topics`), porque relação não tem atributos no contrato `@1`.
- O `scan` passa a exportar `ATLAS_COLLECTOR_PROFILE` (o nome em `credentials.<id>.profile`) só para o coletor daquele id. O coletor `aws` o repassa à AWS CLI como `AWS_PROFILE`, no ambiente do processo filho, e nunca o imprime.

**Justificativa:** repete o padrão do `argocd` (CLI de leitura, dublê no PATH, stdlib), não muda o contrato nem o `build`, e o profile por coletor permite mapear contas diferentes (dev e prod) no mesmo `scan` sem que um coletor use o profile do outro.

**Desvio do padrão existente:** nenhum. A relação `publishes` com origem `topic` usa um tipo já existente; o validador do `@1` não restringe os kinds das pontas, e a referência passa a documentar esse uso (mudança só de documentação, aditiva).

**Alternativas descartadas:**
- **boto3:** dependência nova fora da biblioteca padrão e credencial manipulada pelo próprio processo.
- **`--profile` no `command` do `atlas-config.yml`:** o `atlas-config.yml` é compartilhado e o nome do profile é desta máquina.
- **`AWS_PROFILE` declarado em `credentials.<id>.env`:** o valor vem do shell e é o mesmo para todos os coletores, então não dá para mapear duas contas no mesmo `scan`.
- **Id com região ou conta (`us-east-1/orders`):** quebraria a ligação pelo nome que o `argocd` já produz, e a conta não pode ir para o atlas.
- **Uma relação por fila de DLQ (`queue → queue`):** não há tipo de relação que diga "redrive"; o atributo `dlq` basta para a probe (ADR-0025, regra 1).
- **Paginação automática sem limite:** uma conta grande deixaria o `scan` sem fim e um snapshot parcial geraria remoções falsas no diff.

**ADRs:** ADR-0010 (credencial só por nome), ADR-0011 (contrato `@1`, sem kind nem tipo novo), ADR-0025 (id de conta nunca sai; `region` e `dlq` são os atributos que a probe de recurso usa).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:**
  - por região: uma chamada de lista por operação, mais um `get-queue-attributes` por fila e um `get-subscription-attributes` por assinatura SQS confirmada;
  - cada lista com `--max-items` (padrão 1000, de 1 a 10000); passou do limite → falha, nunca snapshot parcial;
  - cada chamada com `--cli-connect-timeout 10 --cli-read-timeout 30` e o processo com timeout de 60 s; o `timeout` do coletor no `atlas-config.yml` continua valendo para o todo (sugestão de 600 s na referência).
- **Segurança:**
  - lista fechada de operações (seção 6), argv em lista, `shell=False`, stdin fechado;
  - nenhum argumento vem do atlas: a URL da fila e o ARN da assinatura usados nos `get-*` vêm só da resposta da lista anterior;
  - `get-queue-attributes` pede só `RedrivePolicy` (nunca `All`, que traz a `Policy` com ids de conta);
  - o stderr da AWS CLI nunca é repetido: só a mensagem fixa da seção 6.
- **Privacidade e dados pessoais:**
  - nada de ARN, URL de fila, id de conta, `Owner`, ARN de assinatura nem conteúdo de `FilterPolicy` na saída;
  - rede de segurança: um recurso cujo id, nome ou atributo tenha 12 dígitos seguidos é descartado inteiro (só a contagem vai para o stderr);
  - o nome do profile não aparece em stdout, stderr, snapshot, `graph.json` nem nas páginas.
- **Disponibilidade e resiliência:**
  - a porta do endpoint vai para `port` (não é sensível e o adaptador de banco da SPEC-0099 precisa dela);
  - qualquer erro da AWS CLI → exit 1 com mensagem fixa; o `scan` mantém o snapshot anterior e o `seen_at` (comportamento existente);
  - coletores `aws-data` e `aws-messaging` falham de forma independente.
- **Acessibilidade (UI):** N/A — CLI sem interface gráfica.
- **Custo:** N/A — as operações de leitura usadas não são cobradas por chamada no volume de um `scan`; o limite de itens impede rajadas.

## 6. Artefato A — Contrato
**Interface:** `python3 {skill}/assets/collectors/aws.py --services <lista> --region <lista> [--max-items N]`, rodado pelo `atlas.py scan`.

```text
DECLARAÇÃO (atlas-config.yml, compartilhado):
  collectors:
    - id: aws-data
      category: data
      command: ["python3", "{skill}/assets/collectors/aws.py", "--services", "rds,elasticache", "--region", "us-east-1"]
      timeout: 600
    - id: aws-messaging
      category: messaging
      command: ["python3", "{skill}/assets/collectors/aws.py", "--services", "sqs,sns", "--region", "us-east-1,sa-east-1"]
      timeout: 600

CREDENCIAL (configuração local, só o nome):
  credentials:
    aws-data:      {profile: <nome do profile só leitura>}
    aws-messaging: {profile: <nome do profile só leitura>}

OPÇÕES:
  --services  obrigatório; lista de rds, elasticache, sqs, sns; só de uma categoria
              (rds, elasticache → category "data"; sqs, sns → category "messaging")
  --region    obrigatório; lista separada por vírgula, cada uma em ^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$, até 10, sem repetição
  --max-items inteiro de 1 a 10000, padrão 1000; vale para cada chamada de lista em cada região

PERFIL (scan → coletor):
  scan: para o coletor <id>, o ambiente do processo ganha ATLAS_COLLECTOR_PROFILE=<credentials.<id>.profile>
        quando definido; uma ATLAS_COLLECTOR_PROFILE herdada do shell é sempre removida antes
  aws.py: com ATLAS_COLLECTOR_PROFILE, o ambiente da AWS CLI ganha AWS_PROFILE=<valor> e perde
          AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN e AWS_DEFAULT_PROFILE;
          sem ela, a AWS CLI usa a cadeia padrão da máquina

CHAMADAS PERMITIDAS (sempre: --region <r> --output json --no-cli-pager --cli-connect-timeout 10
                     --cli-read-timeout 30; argv em lista, sem shell, stdin fechado, timeout 60 s):
  rds         describe-db-clusters        --max-items N
  rds         describe-db-instances       --max-items N
  elasticache describe-replication-groups --max-items N
  elasticache describe-cache-clusters     --show-cache-node-info --max-items N
  elasticache describe-serverless-caches  --max-items N
  sqs         list-queues                 --max-items N
  sqs         get-queue-attributes        --queue-url <URL vinda do list-queues> --attribute-names RedrivePolicy
  sns         list-topics                 --max-items N
  sns         list-subscriptions          --max-items N
  sns         get-subscription-attributes --subscription-arn <ARN vindo do list-subscriptions, protocolo sqs>
  qualquer outra operação, argumento ou valor de --attribute-names → recusada antes de executar (exit 1,
  "aws: chamada não permitida")

SAÍDA (stdout, um objeto boson-atlas/collector@1; collector "aws"; source "aws" em tudo):
  datastore:<id>  name = id
    rds — describe-db-clusters (Aurora, Multi-AZ DB cluster):
      id = DBClusterIdentifier; attrs: type "rds", engine = Engine em minúsculas, host = Endpoint,
      port = Port, reader_host = ReaderEndpoint (quando existe), region, serverless = EngineMode == "serverless"
      ou ServerlessV2ScalingConfiguration presente
    rds — describe-db-instances, só as que não têm DBClusterIdentifier:
      id = DBInstanceIdentifier; attrs: type "rds", engine, host = Endpoint.Address,
      port = Endpoint.Port, region, serverless false
    elasticache — describe-replication-groups:
      id = ReplicationGroupId; attrs: type "elasticache", engine = Engine do grupo ou, na falta, o Engine dos
      clusters membros (describe-cache-clusters), host = ConfigurationEndpoint.Address (cluster mode) ou
      NodeGroups[0].PrimaryEndpoint.Address, port = Port do mesmo endpoint, reader_host = NodeGroups[0].ReaderEndpoint.Address (quando
      existe), region, serverless false
    elasticache — describe-cache-clusters, só os sem ReplicationGroupId:
      id = CacheClusterId; attrs: type "elasticache", engine, host = ConfigurationEndpoint.Address ou
      CacheNodes[0].Endpoint.Address, port = Port do mesmo endpoint, region, serverless false
    elasticache — describe-serverless-caches:
      id = ServerlessCacheName; attrs: type "elasticache", engine, host = Endpoint.Address,
      port = Endpoint.Port, reader_host = ReaderEndpoint.Address (quando existe), region, serverless true
    port: inteiro de 1 a 65535; texto de dígitos vira inteiro; outro valor → atributo omitido
    sem endpoint (recurso criando ou parado): a entidade sai sem host e sem port
    migrations_table: NÃO vem da AWS e o coletor aws nunca o emite; quem o usa (adaptador postgres,
      SPEC-0099) o recebe por curadoria ou por um fato do coletor generic com a mesma chave
      datastore:<id>, que o build junta ao nó deste coletor
  queue:<nome>   nome = último segmento da URL de list-queues
    attrs: type "sqs", fifo = nome termina em ".fifo", region,
           dlq = texto com o id (nome) de OUTRA fila do mesmo snapshot: último segmento de
                 RedrivePolicy.deadLetterTargetArn, emitido só quando a redrive policy é legível e essa fila
                 é uma entidade queue desta mesma saída e diferente da própria; DLQ de região não listada
                 ou de outra conta → atributo omitido (stderr só com a contagem),
           filtered_topics = lista ordenada dos tópicos cuja assinatura para esta fila tem FilterPolicy não vazia
           (só quando há alguma)
  topic:<nome>   nome = último segmento do TopicArn
    attrs: type "sns", fifo = nome termina em ".fifo", region
  relação {from: "topic:<t>", to: "queue:<q>", type: "publishes", source: "aws"}
    por assinatura com Protocol "sqs" e SubscriptionArn confirmado (≠ "PendingConfirmation");
    <q> = último segmento do Endpoint (ARN da fila), mesmo que a fila seja de outra região ou conta
    (referência a fila ausente é aviso broken-ref do lint, não erro); outros protocolos são ignorados
  nunca saem: ARN, URL, id de conta, Owner, SubscriptionArn, FilterPolicy, RedrivePolicy inteira,
    nome do profile, nome de usuário mestre, tags
  ordem: entidades por kind:id, relações por from/type/to
  recurso com 12 dígitos seguidos no id, nome ou atributo → descartado; stderr
    "aws: <n> recurso(s) ignorado(s): 12 dígitos seguidos"
  mesmo kind:id em duas regiões → fica o da primeira região de --region; stderr
    "aws: <n> recurso(s) repetido(s) em outra região ignorado(s)"
  assinatura pendente, RedrivePolicy ilegível ou DLQ fora do snapshot → ignorada; stderr só com a contagem

EXITS E MENSAGENS (stderr, prefixo "aws: "; nunca o stderr da AWS CLI, o profile, a URL, o ARN ou a conta):
  0  saída impressa
  2  "--services precisa de rds, elasticache, sqs ou sns"
     "misture serviços de dados (rds, elasticache) e de mensageria (sqs, sns) em coletores separados"
     "--region precisa de 1 a 10 regiões válidas, sem repetição"
     "--max-items precisa ser um inteiro de 1 a 10000"
  1  "AWS CLI não encontrada no PATH"
     "profile da AWS não encontrado — confira credentials.<id>.profile"      (ProfileNotFound / "could not be found")
     "login da nuvem expirado — renove o login da nuvem"                    (Token has expired, SSO session,
                                                                              UnauthorizedSSOTokenError, ExpiredToken)
     "sem credencial da AWS — declare o profile em credentials do coletor"  (Unable to locate credentials)
     "sem permissão para <serviço> <operação> em <região>"                  (AccessDenied, AccessDeniedException,
                                                                              UnauthorizedOperation, AuthorizationError,
                                                                              "not authorized")
     "tempo esgotado em <serviço> <operação> (<região>)"                    (timeout do processo, Read/Connect timeout)
     "limite de <N> itens atingido em <serviço> <operação> (<região>) — aumente --max-items"  (NextToken na resposta)
     "resposta inválida da AWS CLI em <serviço> <operação>"                 (JSON inválido ou campo de tipo errado)
     "falha da AWS CLI em <serviço> <operação> (<região>)"                  (qualquer outro código ≠ 0)
     "chamada não permitida"
  A primeira falha encerra o coletor; o scan mostra "FALHA <id> — saiu com 1" com essas linhas, mantém o
  snapshot anterior e não avança o seen_at (comportamento existente do scan).
```

**Como os ids e atributos casam no `build`** (regra 2 de `references/graph.md`, sem mudança):

| `config_refs` do deployment (coletor `argocd`) | Casa com | Por quê |
|---|---|---|
| `ORDERS_QUEUE_URL=orders` (de `https://sqs.<região>.amazonaws.com/<conta>/orders`) | `queue:orders` | o `argocd` reduz a URL ao nome; o `name` da fila é o nome |
| `ORDER_EVENTS_TOPIC=order-events` (de `arn:aws:sns:<região>:<conta>:order-events`) | `topic:order-events` | o `argocd` reduz o ARN ao nome; o `name` do tópico é o nome |
| `DB_HOST=orders-db.cluster-abc123.us-east-1.rds.amazonaws.com` (ou o host de uma URL `postgres://…`) | `datastore:orders-db` | igual a `attrs.host` (endpoint de escrita) |
| `REDIS_HOST=orders-cache.abc123.ng.0001.use1.cache.amazonaws.com` | `datastore:orders-cache` | igual a `attrs.host` |
| `DB_HOST=orders-db` | `datastore:orders-db` | igual ao `name` |
| `DB_READER_HOST=orders-db.cluster-ro-abc123…` ou um CNAME próprio (`db.interno`) | nada | a regra 2 só olha `host` e `name`; `reader_host` é informativo (fora do escopo, seção 2) |

A DLQ de uma fila ligada ao deployment também é alvo de probe pelo atributo `dlq` (ADR-0025, regra 1), sem aresta própria.

**Exemplo de saída** (o mesmo de `tests/fixtures/contract/valid/messaging-aws.json` e de `references/collectors/aws.md`):

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

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `assets/collectors/aws.py` (novo).
- `references/collectors/aws.md` (nova): setup, política IAM mínima só de leitura (`rds:DescribeDBClusters`, `rds:DescribeDBInstances`, `elasticache:DescribeReplicationGroups`, `elasticache:DescribeCacheClusters`, `elasticache:DescribeServerlessCaches`, `sqs:ListQueues`, `sqs:GetQueueAttributes`, `sns:ListTopics`, `sns:ListSubscriptions`, `sns:GetSubscriptionAttributes`), opções, chamadas, saída, a tabela de casamento acima e os limites.
- `references/collector-contract.md`: `publishes` também de `topic` para `queue` (assinatura); `ATLAS_COLLECTOR_PROFILE`; exemplos `data-aws` e `messaging-aws`.
- `references/config.md`: `credentials.<id>.profile` agora chega ao coletor como `ATLAS_COLLECTOR_PROFILE`.
- `scripts/atlas.py`: `scan_one`/`collector_environment` passam o profile; `ATLAS_VERSION`.
- `SKILL.md` (link para `references/collectors/aws.md`), `CHANGELOG.md`, `.claude-plugin/plugin.json`.
- `tests/test_collector_aws.py`, `tests/fixtures/aws/` (dublê `fake_aws.py`, respostas gravadas, Applications do `argocd` para o IT) e `tests/fixtures/contract/valid/data-aws.json` e `messaging-aws.json`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Bancos e caches | `--services rds,elasticache` com Aurora serverless e membros, RDS avulso, grupo Valkey, grupo em cluster mode, Memcached avulso, cache serverless | um `datastore` por recurso com `type`, `engine`, `host`, `port` (inteiro), `region`, `serverless`, nunca `migrations_table`; membros de cluster não viram entidade; category `data` | UT-01, CT-01 |
| Filas, tópicos e assinaturas | `--services sqs,sns` com redrive (DLQ no snapshot e fora dele), FIFO, assinatura com e sem filtro, pendente, HTTP e de fila de outra região | `queue` com `dlq` (só nome de outra fila da mesma saída), `fifo`, `filtered_topics`; `topic` com `fifo`; `topic → queue` `publishes` só para SQS confirmada; category `messaging` | UT-02, CT-01 |
| Lista fechada | todas as execuções; pedidos de `receive-message`, `purge-queue`, `publish`, `delete-*`, `--attribute-names All` | toda chamada registrada está na tabela; o resto é recusado sem executar, com "chamada não permitida" | UT-03 |
| Sem credencial | AWS CLI responde "Unable to locate credentials" | exit 1, "sem credencial da AWS — …", sem o stderr da CLI | UT-04 |
| Login expirado | SSO expirado ou token expirado | exit 1, "login da nuvem expirado — renove o login da nuvem" | UT-04, IT-02 |
| Profile ausente | "The config profile (…) could not be found" | exit 1, "profile da AWS não encontrado — …", sem o nome | UT-04 |
| Sem permissão | AccessDenied numa operação | exit 1, "sem permissão para <serviço> <operação> em <região>" | UT-04 |
| CLI ausente, tempo esgotado, JSON inválido, outro erro | sem `aws` no PATH, processo lento, resposta quebrada, código ≠ 0 | exit 1 com a mensagem fixa de cada caso | UT-04 |
| Limite | resposta com `NextToken` | exit 1, "limite de <N> itens atingido em …"; `--max-items` passado em toda lista | UT-05 |
| Argumentos inválidos | serviço desconhecido, categorias misturadas, região inválida ou repetida, `--max-items` fora da faixa | exit 2 com a mensagem fixa, sem chamar a AWS CLI | UT-05 |
| Conta e dados sensíveis | respostas com ARNs, URLs, `Owner`, `FilterPolicy`, `Policy` | nada disso em stdout, stderr nem snapshot; recurso com 12 dígitos seguidos descartado | UT-06, IT-01 |
| Mesmo nome em duas regiões | `orders` em `us-east-1` e `sa-east-1` | fica o da primeira região; stderr só com a contagem | UT-06 |
| Profile por coletor | `credentials.aws-messaging.profile` definido, outro coletor sem profile, variável herdada do shell | só aquele coletor recebe `ATLAS_COLLECTOR_PROFILE`; a AWS CLI recebe `AWS_PROFILE` sem as chaves estáticas; o nome não aparece em nenhuma saída | UT-07, IT-01 |
| Ambiente dos coletores sem profile | `scan` sem `credentials.<id>.profile` | o ambiente do coletor é o de antes | CH-01 |
| Ponta a ponta com o `build` | `scan` com `aws-data`, `aws-messaging` e `argocd` (`--input`) | snapshots válidos; `service:api` `depends_on` `queue:orders`, `topic:order-events` e `datastore:orders-db` (inferidas); `topic:order-events` `publishes` `queue:orders`; nenhuma conta no atlas | IT-01 |
| Falha isolada | `aws-messaging` com login expirado e `aws-data` ok | `FALHA aws-messaging — saiu com 1` com a mensagem fixa, snapshot anterior e `seen_at` mantidos; `aws-data` gravado; exit 1 | IT-02 |

## 7. Artefato B — Plano de Testes (TDD)
<!-- Todo teste tem um ID e é escrito ANTES da implementação (Red). No código, cada teste carrega a tag `SPEC-0097:<ID>` — o G1 (`spec_graph.py verify`) verifica. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem testes: "N/A — motivo" SEM ID. Teste que protege comportamento existente e passa antes da mudança: marque `(guarda: passa antes da mudança)`. Estratégia completa: references/testing.md da skill. -->

### 7.1 Testes de Caracterização
- **CH-01** — Dado um atlas temporário com um coletor falso que imprime os nomes das variáveis de ambiente que recebeu (como `fixtures/fake-collectors/env_names.py`) e sem `credentials.<id>.profile`, quando o `scan` roda, então o conjunto de nomes recebido é o mesmo de antes da mudança (o isolamento entre atlas continua) e não há `ATLAS_COLLECTOR_PROFILE` (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado o dublê da AWS CLI com respostas gravadas de `us-east-1`: um cluster `aurora-postgresql` `orders-db` com `ServerlessV2ScalingConfiguration`, endpoint de escrita e de leitura e duas instâncias membro; uma instância `postgres` avulsa `billing-db`; um grupo de replicação `orders-cache` sem `Engine` cujos membros são `valkey`; um grupo `sessions` em cluster mode com `ConfigurationEndpoint`; um Memcached avulso `catalog-mc`; e um cache serverless `rates-cache`, quando `aws.py --services rds,elasticache --region us-east-1` roda, então a saída tem category `data` e exatamente os `datastore` `orders-db`, `billing-db`, `orders-cache`, `sessions`, `catalog-mc` e `rates-cache`, com `type`, `engine` (`aurora-postgresql`, `postgres`, `valkey`, …), `host` igual ao endpoint de escrita ou de configuração, `port` inteiro (`5432`, `6379`, `11211`, inclusive quando a resposta traz `"5432"` como texto), `reader_host` só onde existe, `region: us-east-1` e `serverless` verdadeiro só em `orders-db` e `rates-cache`; as instâncias membro não viram entidade; uma instância sem endpoint sai sem `host` e sem `port`; nenhuma entidade tem `migrations_table`.
- **UT-02** — Dado o dublê com as filas `orders` (redrive para `orders-dlq`), `orders-dlq`, `refunds` (redrive para `refunds-dlq` de outra conta, fora da lista) e `payments.fifo`, os tópicos `order-events` e `payments.fifo`, e as assinaturas `order-events → orders` com `FilterPolicy`, `payments.fifo → payments.fifo` sem filtro, uma pendente, uma HTTP e `order-events → audit` (fila de outra região), quando `aws.py --services sqs,sns --region us-east-1` roda, então a saída tem category `messaging`; `queue:orders` tem `dlq: orders-dlq` (texto igual ao id de `queue:orders-dlq` da mesma saída) e `filtered_topics: ["order-events"]`; `queue:refunds` sai sem `dlq` e o stderr traz só a contagem; as duas `.fifo` têm `fifo: true`; as relações são exatamente `topic:order-events publishes queue:orders`, `topic:order-events publishes queue:audit` e `topic:payments.fifo publishes queue:payments.fifo`.
- **UT-03** — Dado que o dublê registra cada argv recebido, quando os cenários de UT-01 e UT-02 rodam, então todo argv bate com uma linha da tabela de chamadas permitidas (com `--region`, `--output json`, `--no-cli-pager` e os timeouts), o `get-queue-attributes` pede só `RedrivePolicy` e cada URL e ARN de `get-*` veio da lista anterior; e, chamada direto, a função que monta a chamada recusa `sqs receive-message`, `sqs purge-queue`, `sns publish`, `rds delete-db-instance` e `get-queue-attributes --attribute-names All` com "chamada não permitida", sem executar nada; o código do coletor não usa `shell=True`.
- **UT-04** — Dado o dublê em cada modo de erro (sem credencial, SSO expirado, token expirado, profile `acme-prod-readonly` inexistente, AccessDenied em `elasticache describe-serverless-caches`, processo acima do timeout, JSON inválido, código 255 com texto livre) e, à parte, um PATH sem `aws`, quando o coletor roda, então sai com 1 e o stderr tem só a mensagem fixa do contrato para o caso; o stderr não contém o texto do dublê, o nome do profile, `123456789012`, URL nem ARN, e o stdout fica vazio.
- **UT-05** — Dado o dublê devolvendo `NextToken` em `sqs list-queues`, quando o coletor roda com `--max-items 2`, então sai com 1 e "limite de 2 itens atingido em sqs list-queues (us-east-1) — aumente --max-items", e toda chamada de lista levou `--max-items 2`; e, dado `--services s3`, `--services rds,sqs`, `--region us-east-1,us-east-1`, `--region Brasil`, `--max-items 0` e `--max-items 10001`, então sai com 2 e a mensagem fixa de cada caso, sem nenhuma chamada registrada.
- **UT-06** — Dado o dublê com ARNs, URLs, `Owner`, `FilterPolicy` com o texto `"customer_tier"` e `Policy` com `123456789012` nas respostas, uma fila `report-202411241200` (12 dígitos seguidos) e a fila `orders` também em `sa-east-1`, quando o coletor roda com `--region us-east-1,sa-east-1`, então o stdout não contém `123456789012`, `arn:`, `https://`, `customer_tier` nem `Owner`; `queue:report-202411241200` não aparece; `queue:orders` tem `region: us-east-1`; e o stderr tem só as contagens de ignorados e repetidos.
- **UT-07** — Dado um atlas temporário com `credentials.aws-messaging.profile: acme-prod-readonly`, um segundo coletor sem profile e `ATLAS_COLLECTOR_PROFILE` e `AWS_ACCESS_KEY_ID` definidos no shell, quando o `scan` roda, então só `aws-messaging` recebe `ATLAS_COLLECTOR_PROFILE` (com o nome declarado) e o outro não recebe a variável herdada; o dublê registra que a AWS CLI recebeu `AWS_PROFILE` igual ao nome e não recebeu `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` nem `AWS_DEFAULT_PROFILE`; e o nome do profile não aparece no stdout do `scan`, nos snapshots nem no `graph.json`.

### 7.3 Testes de Integração
- **IT-01** — Dado um atlas temporário criado pelo `atlas.py init` real, com `HOME`, `XDG_CONFIG_HOME` e `ATLAS_CONFIG_HOME` temporários, `credentials` com profile para `aws-data` e `aws-messaging`, os coletores `aws-data`, `aws-messaging` e `argocd --from kubectl --input <fixtures/aws/argocd-apps.json>` (deployment `dev/api` com `ORDERS_QUEUE_URL` como URL SQS com conta, `ORDER_EVENTS_TOPIC` como ARN SNS e `DB_HOST` com o endpoint do Aurora) declarados e o dublê `fake_aws.py` como `aws` no PATH, quando `atlas.py scan --json` roda como processo, então sai com 0; `snapshots/aws-data.json` e `snapshots/aws-messaging.json` passam no validador `@1`; o `graph.json` tem `service:api depends_on queue:orders`, `topic:order-events` e `datastore:orders-db` (inferidas, com a evidência do `config_refs`) e `topic:order-events publishes queue:orders`; e nenhum arquivo da pasta do atlas contém `123456789012`, `arn:` nem o nome do profile.
- **IT-02** — Dado o mesmo atlas depois do IT-01 e o dublê em modo SSO expirado só para `sqs`, quando `atlas.py scan` roda de novo, então sai com 1, mostra `FALHA aws-messaging — saiu com 1` com "login da nuvem expirado — renove o login da nuvem", `snapshots/aws-messaging.json` fica byte a byte igual, `_scan.json` traz `status: failed` com o `seen_at` anterior para `aws-messaging` e `aws-data` segue `ok`.

### 7.4 Testes de Contrato
- **CT-01** — Os exemplos `tests/fixtures/contract/valid/data-aws.json` e `messaging-aws.json`, iguais aos blocos de `references/collectors/aws.md` e de `references/collector-contract.md`, e as saídas do coletor nos cenários de UT-01 e UT-02, quando passam por `validate_collector_output` do `atlas.py`, então não têm violação nem campo ou chave descartada, todo `port` é inteiro, todo `dlq` é o id de outra `queue` da mesma saída (nenhuma chave de `attrs` cai na regra de chave proibida e todo valor é escalar ou lista de escalares), e só usam kinds e tipos de relação que já existem.

### 7.5 Testes E2E
- N/A — CLI sem jornada de usuário; o IT-01 roda `scan` e `build` de ponta a ponta com o dublê.

### 7.6 Outros
- N/A — segurança e privacidade estão cobertas pelos unitários de lista fechada, erros, dados sensíveis e profile; não há requisito de desempenho medido além do limite de itens.

**Dublês e dados de teste:**
- `tests/fixtures/aws/fake_aws.py`, copiado como `aws` numa pasta temporária que é o PATH dos testes unitários: responde por `(serviço, operação, região)` a partir de `tests/fixtures/aws/responses/`, registra cada argv e os nomes das variáveis de ambiente recebidas (e o valor de `AWS_PROFILE`, só no registro do teste) num arquivo indicado por `FAKE_AWS_LOG`, e simula os erros por `FAKE_AWS_MODE` (`no-credentials`, `sso-expired`, `token-expired`, `profile-not-found`, `denied:<serviço>:<operação>`, `slow`, `invalid-json`, `fail`, `next-token:<serviço>:<operação>`), escrevendo no stderr textos parecidos com os reais, com o profile e a conta, para provar que não vazam.
- Respostas JSON só com nomes `acme`, `orders`, `order-events`, regiões `us-east-1` e `sa-east-1` e a conta de exemplo `123456789012`.
- Nenhuma AWS CLI real, rede ou `~/.aws` real; `HOME`, `XDG_CONFIG_HOME` e `ATLAS_CONFIG_HOME` temporários.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15), sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto, pela versão do plugin (SPEC-0056) e um novo `ATLAS_VERSION`. O coletor só roda depois de declarado em `collectors` no `atlas-config.yml`.
- **Dados/schema:** nenhum. Snapshots novos (`snapshots/aws-data.json`, `snapshots/aws-messaging.json`) no contrato `@1`.
- **Compatibilidade:**
  - contrato `@1` inalterado: uma máquina com a versão anterior da skill lê os snapshots e gera o mesmo grafo;
  - `ATLAS_COLLECTOR_PROFILE` é aditivo; um coletor que não a lê não muda;
  - quem já mantém filas e bancos no coletor `generic` passa a ter o mesmo nó em duas fontes (mesma chave `kind:id`): o `build` junta, e diferenças de atributo aparecem em `conflicts`; a referência sugere apagar os fatos à mão depois do primeiro `scan` bom;
  - o mesmo nome de recurso em duas contas (dois coletores) vira um nó só, com `region` ou `host` em `conflicts`; a referência recomenda nomes únicos por ambiente e mostra o caso.
- **Observabilidade:** o relatório do `scan` (`OK/FALHA <id>`, contagens, diff) e `snapshots/_scan.json`; o `lint` acusa coletor que falhou ou envelheceu (comportamento existente) e `broken-ref` para fila assinada de outra conta.
- **Rollback:** tirar ou desabilitar (`enabled: false`) os coletores no `atlas-config.yml` e, se preciso, voltar a versão do plugin. Os snapshots ficam no histórico do atlas.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Como passar o profile por coletor sem pôr o nome no `atlas-config.yml` compartilhado? — O `scan` exporta `credentials.<id>.profile` como `ATLAS_COLLECTOR_PROFILE` só para aquele coletor, e o `aws.py` o converte em `AWS_PROFILE` no processo filho, tirando as chaves estáticas do ambiente para que o profile valha (Architect, 2026-11-24, recomendado)
- [x] Um coletor para dados e mensageria, ou dois? — Dois por execução, porque o contrato pede uma `category` por coletor (ADR-0011): `--services` só de uma categoria; misturar sai com 2. Também isola falhas de permissão (Architect, 2026-11-24, recomendado)
- [x] Onde fica a presença de filtro da assinatura, já que relação não tem atributos no `@1`? — No nó da fila, `filtered_topics` (lista de nomes de tópico), nunca o conteúdo do filtro; o adaptador da SPEC-0098 lê o filtro ao vivo (Architect, 2026-11-24, recomendado)
- [x] Chegou ao limite de itens: snapshot parcial ou falha? — Falha com mensagem fixa: um snapshot parcial geraria remoções falsas no diff e no grafo; o anterior fica (Architect, 2026-11-24, recomendado)
- [x] Mesmo nome em duas regiões do mesmo coletor ou em duas contas? — Na mesma execução fica a primeira região de `--region` (contagem no stderr). Entre contas o `build` junta pelo id e mostra o conflito; ids continuam sendo o nome para casar com o `config_refs` do `argocd`. A referência recomenda nomes únicos por ambiente (Architect, 2026-11-24, recomendado; revisável no H1)
- [x] `port` e `migrations_table` no `datastore`? — `port` sim, inteiro, do mesmo endpoint de `host` (alinhamento com as specs consumidoras). `migrations_table` não vem da AWS: entra só por curadoria ou fato do coletor `generic` com a mesma chave, e o coletor `aws` nunca o emite (Architect, 2026-11-24, recomendado)
- [x] `dlq` de uma fila fora do snapshot (outra conta ou região não listada)? — Omitido, para que `dlq` seja sempre o id de outra fila da mesma saída; o stderr mostra só a contagem (Architect, 2026-11-24, recomendado)
- [x] Ligar o serviço também pelo endpoint de leitura ou por CNAME próprio? — Não nesta spec: exige mudar a regra 2 do `build`. O `reader_host` sai como atributo informativo (Architect, 2026-11-24, recomendado)

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0097`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
