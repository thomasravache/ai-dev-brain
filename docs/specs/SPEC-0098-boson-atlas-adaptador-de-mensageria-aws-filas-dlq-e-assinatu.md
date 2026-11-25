---
id: SPEC-0098
title: "boson-atlas: adaptador de mensageria aws — filas, DLQ e assinaturas"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-24
parent: SPEC-0095
depends_on: [SPEC-0096]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/assets/probes/aws-messaging.py, skills/boson-atlas/references/probes/aws-messaging.md, skills/boson-atlas/tests/test_probe_aws_messaging.py, skills/boson-atlas/tests/fixtures/aws-messaging/**, skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0023, ADR-0025, ADR-0026]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-24
---

# SPEC-0098 — boson-atlas: adaptador de mensageria aws — filas, DLQ e assinaturas

> Origem: épico SPEC-0095, onda 2. É o adaptador que dá à verificação depois do deploy o estado das filas, da DLQ e das assinaturas dos tópicos que o serviço usa.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Adaptador `aws-messaging` do contrato `probe@2` (SPEC-0096, ADR-0025) para a capacidade `messaging`. Ele usa a AWS CLI da máquina, **só para leitura**, com o profile do ambiente (`target.cloud.profile`) e a região do recurso, e responde duas perguntas:
- **`queue`** (alvo `queue`): a fila está acumulando? A DLQ dela ganhou mensagens?
- **`subscriptions`** (alvo `topic`): quem assina o tópico, e com que filtro?

Nunca lê, recebe, apaga nem reenvia mensagens.

## 2. Motivação & Escopo
**Motivação:** a rotina real de verificação (SPEC-0075, passos 4 e 5) olha a fila sem acúmulo, a DLQ sem mensagens novas e as assinaturas do tópico com os filtros. O `verify@2` (SPEC-0102, ADR-0026) compara esse estado contra a foto de antes do merge. Sem o adaptador, essas verificações ficam "não verificado".

**Objetivos (dentro do escopo):**
- **`assets/probes/aws-messaging.py`:** só stdlib, Python 3.9 ou mais novo. Usa `--describe` e o protocolo `probe@2`.
- **`queue`:** para a fila do alvo, informa:
  - mensagens visíveis, em voo e atrasadas (atributos `ApproximateNumberOfMessages*` da fila);
  - a idade da mais antiga, em segundos, pela métrica `ApproximateAgeOfOldestMessage` do CloudWatch (decisão na seção 4);
  - se a fila é FIFO (pelo sufixo `.fifo` do nome, regra da própria AWS);
  - a DLQ do atributo `dlq` do recurso (o id de outra fila, ADR-0025 regra 4): visíveis e em voo; e se a `RedrivePolicy` da fila aponta para essa mesma DLQ.
  - Sai **exatamente um item**, com os campos da tabela 4a do ADR-0026 (`visible`, `in_flight`, `oldest_age_seconds`, `dlq_visible`) e alguns campos a mais, que o `verify@2` ignora.
- **`subscriptions`:** para o tópico do alvo, **um item por assinatura** (tabela 4a do ADR-0026), sem item-resumo do tópico; o resumo vai em `message`. Cada item traz:
  - protocolo;
  - destino como `queue:<nome>` quando é fila, senão o destino mascarado (`<protocolo>:[REDACTED]`);
  - a impressão digital do destino (`destination_fingerprint`, para dois destinos mascarados iguais não colidirem) e a do filtro (hash estável);
  - presença do filtro, escopo e as **chaves** do filtro, nunca os valores;
  - confirmação pendente, entrega crua e DLQ da assinatura (só se existe).
- **Lista fechada** de operações de leitura da AWS CLI (seção 6), recusando qualquer outra antes de executar.
- **Sem ARN nem URL no atlas** (ADR-0025 regra 4): a URL da fila sai de `sqs get-queue-url` e o ARN do tópico é montado com a conta e a partição de `sts get-caller-identity`, ambos na lista fechada.
- **Ids de conta mascarados** em toda saída do adaptador, além da máscara do núcleo.
- **Login expirado:** `status: error` com o texto fixo "renove o login da nuvem". A skill nunca faz o login.
- `references/probes/aws-messaging.md`: configuração, política IAM mínima sugerida, o que é lido, saída, erros e os blocos de contrato de exemplo.

**Não-objetivos (fora do escopo):**
- `sqs receive-message`, `purge-queue`, `delete-message`, `start-message-move-task` (redrive) e qualquer escrita: seguem no radar da SPEC-0075.
- Ler a política da fila ou do tópico (`Policy`) e os atributos de criptografia: quem lê política é a simulação de IAM (SPEC-0101).
- Métricas de tráfego e erro da fila e do tópico na janela: são do adaptador CloudWatch (SPEC-0100). Aqui entra só a idade da mais antiga, que faz parte do estado da fila no ADR-0026.
- Descobrir filas ou tópicos que o atlas não mapeou: o alvo vem só do núcleo (ADR-0025).
- Outras nuvens e outros brokers (Kafka, RabbitMQ): seriam outros adaptadores da mesma capacidade.

## 3. Dependências
- **Implementações necessárias:** SPEC-0096 — o IT-01, o IT-02 e o CT-01 rodam o núcleo real (`probe --resource`, entrada `probe@2` com `target.resource` e `target.cloud.profile`, validador `probe@2`).
- **Contratos consumidos:** N/A — a implementação da SPEC-0096 já é dependência.
- **Pré-requisitos externos:** AWS CLI v2 no PATH da máquina que roda a probe (usa `--no-cli-pager`), com um profile só de leitura por ambiente em `access.cloud`. Nos testes ela é substituída por um dublê.

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **adaptador `kubernetes`:** `assets/probes/kubernetes.py` (SPEC-0089), com a ferramenta chamada como lista de argumentos, lista fechada, erros com mensagem fixa e exit 0, e o dublê `tests/fixtures/kubernetes/fake_kubectl.py` que registra o argv;
- **contrato:** `probe@2` (SPEC-0096, ADR-0025).

**Decisão:** script próprio em `assets/probes/aws-messaging.py`, no molde do adaptador `kubernetes`. Cada chamada é montada só a partir de `target.resource` (id e `attrs`), `target.cloud.profile` e `limits`, de uma lista fechada de operações, sempre com `--output json`.

**Idade da mensagem mais antiga — decisão:** vem da métrica `ApproximateAgeOfOldestMessage` (namespace `AWS/SQS`, dimensão `QueueName`, estatística `Maximum`, período 60 s, últimos 10 minutos, o ponto mais recente), por **uma** chamada `cloudwatch get-metric-data`. Justificativa:
- o `GetQueueAttributes` não tem atributo de idade (conferido na documentação oficial da API em 2026-11-24);
- a única outra forma seria olhar a mensagem (`receive-message`), que muda a visibilidade dela e é escrita na prática: proibida;
- o ADR-0026 põe a idade no estado da fila; tirá-la do adaptador CloudWatch faria uma fila depender de dois adaptadores para um estado só.

Sem ponto na janela (fila inativa: a AWS só emite as métricas com a fila ativa), a idade sai `null` com `oldest_age_source: "sem dados"`; sem permissão no CloudWatch, `null` com `"sem permissão"`. O resto do item segue valendo.

**Justificativa:** repetir o padrão do `kubernetes` deixa o adaptador testável sem nuvem e sem rede. A lista fechada é a segunda barreira, depois do papel só de leitura (ADR-0023, ADR-0025 regra 7).

**Desvio do padrão existente:** nenhum.

**Alternativas descartadas:**
- **boto3:** dependência nova fora da stdlib, e a skill já usa ferramentas da máquina.
- **Atributo `All` no `get-queue-attributes`:** traz a `Policy` da fila (contas e principais), que não é desta probe.
- **Filtro em texto, mascarado, sob pedido:** o filtro pode carregar ids de cliente nos valores; a impressão digital e as chaves bastam para o `verify` dizer que o filtro mudou (ADR-0026 regra 3), e a pessoa vê o texto no console da nuvem se precisar.
- **Resolver se a fila destino está no grafo dentro do adaptador:** o adaptador não recebe o grafo. Ele emite `queue:<nome>` com a regra de id de fila do coletor `aws` (SPEC-0097), e quem cruza com o grafo é o `verify` (SPEC-0102).

**ADRs:** ADR-0010 (credencial só por nome), ADR-0023 (probes), ADR-0025 (alvo de recurso, acesso local, `probe@2`), ADR-0026 (estado da fila e do tópico na foto).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:**
  - `queue`: no máximo 2 `get-queue-url`, 2 `get-queue-attributes` (fila e DLQ) e 1 `get-metric-data`;
  - `subscriptions`: 1 `sts get-caller-identity`, 1 `list-subscriptions-by-topic` (paginado pela CLI) e um `get-subscription-attributes` por assinatura, até 100; acima disso, `truncated: true`;
  - cada chamada com `--cli-read-timeout 20 --cli-connect-timeout 10`, e o processo com timeout de 30 s.
- **Segurança:**
  - lista fechada de serviços, operações e opções; recusa antes de executar;
  - o profile vem só de `target.cloud.profile` e nunca é impresso;
  - nomes de fila, tópico e região conferidos por regex antes de qualquer chamada, sem começar com `-`;
  - nenhuma operação que lê ou move mensagens; nenhuma leitura de `Policy`;
  - as mensagens de erro são fixas, sem o stderr da AWS CLI (que pode citar o profile, o ARN e a conta);
  - ids de conta (12 dígitos) mascarados no próprio adaptador.
  - Verificado pelos UT-05, UT-06 e IT-01 (argv registrado pelo dublê).
- **Privacidade e dados pessoais:** nenhum conteúdo de mensagem é lido. Os valores do filtro (que podem ter ids de cliente) nunca saem: só as chaves e o hash. O destino de protocolos que apontam para pessoa ou host (`email`, `email-json`, `sms`, `http`, `https`) sai como `<protocolo>:[REDACTED]`.
- **Disponibilidade e resiliência:**
  - `aws` ausente → `status: error`, "aws não encontrado";
  - login expirado → `status: error`, "renove o login da nuvem";
  - fila, DLQ ou tópico inexistente → `status: error` com a mensagem fixa ("fila não encontrada", "DLQ não encontrada", "tópico não encontrado"); o `verify@2` mostra "não verificado" em vez de um item sem as contagens;
  - sem dados de idade → `null` com o motivo, sem derrubar o item.
- **Acessibilidade (UI):** N/A — sem interface gráfica.
- **Custo:** as operações de SQS, SNS e STS de leitura são baratas; o `get-metric-data` pede uma métrica por execução de `queue`. Medido pelo argv registrado no UT-05 (contagem de chamadas).

## 6. Artefato A — Contrato
**Interface:** a descrição e os dois verbos do adaptador `aws-messaging`.

```text
--describe → {"contract": "probe@2", "adapter": "aws-messaging",
              "capabilities": {"messaging": {"verbs": ["queue", "subscriptions"], "targets": ["queue", "topic"],
                                             "access": ["cloud"]}}}

entrada (probe@2, SPEC-0096):
  target.resource = {"kind": "queue"|"topic", "id": "<id do nó>", "attrs": {escalares do nó}}
  target.cloud.profile = nome do profile da AWS CLI desta máquina para o ambiente
  limits.lines (1..2000), limits.since_seconds (1..86400; não usado: o estado é instantâneo)
  verbo queue só com kind queue; subscriptions só com kind topic; o contrário → "chamada não permitida"

atributos do recurso usados (coletor aws, SPEC-0097; ADR-0025 regra 4 — nenhum leva id de conta):
  attrs.region      ^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$ (ADR-0025); ausente → "recurso sem região no atlas"; fora da regra → "entrada inválida"
  dlq         opcional     texto com o id de outra fila (o nome dela); mesma regra de nome de fila
  type        opcional     "sqs" na fila, "sns" no tópico; outro valor → "chamada não permitida"
  ARN ou URL em qualquer atributo: ignorado (nunca usado para montar chamada)
  nome do recurso   o id do nó (`target.resource.id`; o coletor usa o nome do recurso como id)
  fila ^[A-Za-z0-9_-]{1,80}(\.fifo)?$, tópico ^[A-Za-z0-9_-]{1,256}(\.fifo)?$; dlq com a regra de fila; fora → "entrada inválida"
  profile           ^[A-Za-z0-9_.+-]{1,64}$, sem começar com "-"; fora → "entrada inválida", sem chamada

chamadas permitidas (argv começa com <serviço> <operação>; sempre com --region <attrs.region>,
--profile <target.cloud.profile>, --output json, --no-cli-pager, --cli-read-timeout 20, --cli-connect-timeout 10):
  sqs get-queue-url --queue-name <nome>
  sqs get-queue-attributes --queue-url <url devolvida acima> --attribute-names ApproximateNumberOfMessages
      ApproximateNumberOfMessagesNotVisible ApproximateNumberOfMessagesDelayed RedrivePolicy
  cloudwatch get-metric-data --metric-data-queries <JSON montado pelo adaptador: 1 consulta,
      AWS/SQS ApproximateAgeOfOldestMessage, QueueName=<nome>, Maximum, 60 s> --start-time <agora-600s>
      --end-time <agora> --scan-by TimestampDescending
  sts get-caller-identity                (subscriptions: conta e partição do ARN do chamador)
  sns list-subscriptions-by-topic --topic-arn arn:<partição>:sns:<region>:<conta>:<nome>   (montado pelo adaptador)
  sns get-subscription-attributes --subscription-arn <arn devolvido pela listagem, conferido por regex>
  qualquer outra (receive-message, purge-queue, delete-*, send-*, set-*, publish, start-message-move-task,
  get-queue-attributes com All ou Policy, --endpoint-url, --debug, --query, ...) → recusada antes de executar
  (status: error, "chamada não permitida")

queue → exatamente 1 item (tabela 4a do ADR-0026: visible, in_flight, oldest_age_seconds, dlq_visible):
  {"visible": 12, "in_flight": 3, "oldest_age_seconds": 42 | null, "dlq_visible": 2 | null,
   "delayed": 0, "fifo": false, "oldest_age_source": "cloudwatch" | "sem dados" | "sem permissão",
   "dlq": "queue:<id da dlq>" | null, "dlq_in_flight": 0 | null, "redrive": true,
   "redrive_matches_dlq": true | false | null}
  visible e in_flight: inteiros ≥ 0, nunca null; dlq_visible null só sem attrs.dlq
  campos depois de dlq_visible: a mais, ignorados pelo verify@2
  dlq: só pelo attrs.dlq; redrive = a fila tem RedrivePolicy; redrive_matches_dlq = o nome do deadLetterTargetArn
  é o da dlq (null sem attrs.dlq ou sem RedrivePolicy)
  fila inexistente → status error "fila não encontrada"; DLQ inexistente → status error "DLQ não encontrada"

subscriptions → um item por assinatura (tabela 4a: destination, filter_fingerprint), sem item do tópico;
  message = "<n> assinaturas, <m> pendentes" (n = total listado, antes do corte)
  {"destination": "queue:orders", "filter_fingerprint": "sha256:<16 hex>" | null,
   "destination_fingerprint": "sha256:<16 hex>", "protocol": "sqs",
   "pending_confirmation": false, "raw_delivery": true | null,
   "has_filter": true | false | null, "filter_scope": "MessageAttributes" | "MessageBody" | null,
   "filter_keys": ["event_type", "payload.status"],
   "has_dlq": false | null}
  destination: sqs → "queue:<nome da fila do ARN>"; lambda → "function:<nome>"; firehose → "stream:<nome>";
    email, email-json, sms, http, https, application e outros → "<protocolo>:[REDACTED]"
  destination_fingerprint: sha256 do protocolo + endpoint com a conta trocada por "[REDACTED]", primeiros 16 hex;
    distingue destinos mascarados iguais (dois https:[REDACTED]); filter_fingerprint null = sem filtro
  filter_fingerprint: sha256 do JSON canônico do FilterPolicy (json.dumps sort_keys, separadores "," ":",
    ensure_ascii=False), primeiros 16 hex; muda quando muda qualquer chave ou valor do filtro
  filter_keys: caminhos das chaves, ordenados, com "." entre níveis no escopo MessageBody; nunca valores
  assinatura pendente (SubscriptionArn "PendingConfirmation"): sem get-subscription-attributes;
    pending_confirmation: true e os campos de atributo null
  ordem: por destination e destination_fingerprint; acima de limits.lines ou de 100 assinaturas → truncated: true
  tópico sem assinaturas: items [] e message "0 assinaturas, 0 pendentes"
  tópico inexistente → status error "tópico não encontrado"
  nenhum ARN, URL de fila, id de assinatura ou id de conta sai em item ou mensagem

erros → exit 0, status: "error", items: [], message fixa (sem stderr, profile, ARN ou conta):
  "aws não encontrado"            sem aws no PATH do adaptador
  "renove o login da nuvem"       SSO ou token expirado (stderr com "Token has expired", "SSO session",
                                  "UnauthorizedSSOTokenError", "Error loading SSO Token", "ExpiredToken",
                                  "RequestExpired" ou "security token included in the request is expired")
  "profile inexistente"           "could not be found" para o profile
  "sem credenciais da nuvem"      "Unable to locate credentials"
  "sem permissão (AccessDenied)"  AccessDenied, AuthorizationError ou "not authorized" em sqs/sns/sts
  "limite de chamadas da nuvem"   Throttling, "Rate exceeded"
  "sem conexão com a nuvem"       "Could not connect to the endpoint URL", erro de DNS
  "timeout"                       "Read timeout", "Connect timeout" ou o processo passou de 30 s
  "recurso sem região no atlas"   attrs.region ausente (fora da regra → "entrada inválida")
  "fila não encontrada" / "DLQ não encontrada" / "tópico não encontrado"   QueueDoesNotExist / NotFound
  "chamada não permitida"         verbo, kind, operação ou opção fora da lista; recusado sem chamar a aws
  "entrada inválida"              stdin que não é probe@2 bem formado, profile ou nome fora da regra,
                                  caractere de controle
  "falha da aws" / "resposta inválida da aws"  outro erro, ou JSON que não tem a forma esperada
  AccessDenied só no get-metric-data não é erro: oldest_age_source "sem permissão"
```

**Máscara no adaptador:** antes de imprimir, todo texto da saída passa por `\b[0-9]{12}\b` → `[REDACTED]`. O núcleo ainda aplica a redaction e a máscara literal do profile (ADR-0025 regra 5).

**Registro:** o adaptador não grava nada. O `probes.log` é do núcleo, com `resource` (`kind:id`) e sem resultado nem acesso (ADR-0025 regra 6).

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `assets/probes/aws-messaging.py` (novo).
- `references/probes/aws-messaging.md` (nova): verbos, chamadas, política IAM mínima sugerida (`sqs:GetQueueUrl`, `sqs:GetQueueAttributes`, `sns:ListSubscriptionsByTopic`, `sns:GetSubscriptionAttributes`, `cloudwatch:GetMetricData`; `sts:GetCallerIdentity` não precisa de permissão), saída, erros e os blocos `json probe@2 ...` válidos e inválidos lidos pelo CT-01.
- `SKILL.md`: o link para a referência, ao lado do `kubernetes`.
- `scripts/atlas.py`: só o `ATLAS_VERSION`.
- `tests/test_probe_aws_messaging.py` e `tests/fixtures/aws-messaging/` (AWS CLI falsa e respostas JSON).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Descrição | `--describe` | `probe@2`, `messaging` com `queue` e `subscriptions`, alvos `queue` e `topic`, acesso `cloud` | CT-01 |
| Fila com DLQ | fila com 12 visíveis, 3 em voo, idade 42 s, DLQ com 2 e RedrivePolicy para ela | exatamente 1 item com `visible: 12`, `in_flight: 3`, `oldest_age_seconds: 42`, `dlq_visible: 2` e `redrive_matches_dlq: true` | UT-01, IT-01, CT-02 |
| Fila FIFO sem DLQ | nome `.fifo`, sem `attrs.dlq`, sem RedrivePolicy | `fifo: true`, `dlq_visible: null`, `redrive: false` | UT-01, CT-02 |
| RedrivePolicy divergente | RedrivePolicy aponta para outra fila | `redrive_matches_dlq: false` | UT-01 |
| Idade sem dados ou sem permissão | `get-metric-data` vazio ou AccessDenied | `oldest_age_seconds: null` com o motivo; resto do item preenchido | UT-02 |
| Fila, DLQ ou tópico inexistente | `QueueDoesNotExist` ou `NotFound` | `status: error`, "fila não encontrada", "DLQ não encontrada" ou "tópico não encontrado" | UT-02, UT-03 |
| Assinaturas | tópico com assinatura sqs filtrada, lambda, duas https e uma pendente | um item por assinatura, sem item do tópico; `destination` `queue:<nome>`, `function:<nome>`, `https:[REDACTED]`; as duas https com `destination_fingerprint` diferentes; chaves e hash do filtro; resumo em `message` | UT-03, IT-01, CT-02 |
| Filtro estável | mesmo filtro com chaves em outra ordem; filtro com um valor trocado | mesma impressão digital; impressão digital diferente; valores nunca na saída | UT-03 |
| ARN e URL montados | atlas sem ARN nem URL; atributo com ARN ignorado | URL por `sqs get-queue-url`, ARN do tópico com a conta de `sts get-caller-identity` | UT-01, UT-03 |
| Muitas assinaturas | mais que `limits.lines` ou que 100 | corta e `truncated: true` | UT-03 |
| Tópico sem assinaturas | listagem vazia | `items: []`, `message` "0 assinaturas, 0 pendentes" | UT-03 |
| Login expirado | stderr de SSO expirado | `status: error`, "renove o login da nuvem", sem o profile | UT-04, IT-02 |
| Outros erros | aws ausente, profile inexistente, sem credenciais, AccessDenied, Throttling, sem conexão, timeout, JSON inválido | `status: error` com a mensagem fixa, sem profile, ARN nem conta | UT-04 |
| Lista fechada | verbo com kind trocado, operação ou opção fora da lista | recusado sem nenhuma chamada | UT-05 |
| Entrada fora da regra | nome com `-` no começo, região inválida, profile com caractere de controle, stdin não `probe@2` | "entrada inválida" ou "recurso sem região no atlas", sem chamada | UT-06 |
| Conta mascarada | ARN e URL com `123456789012` nas respostas | nenhum `123456789012` na saída do adaptador | UT-06, IT-01 |
| Ponta a ponta | `atlas.py probe messaging queue` e `subscriptions` com `--resource` com a AWS CLI falsa | saída validada pelo núcleo; só operações da lista no argv; profile fora da saída e do `probes.log` | IT-01 |

## 7. Artefato B — Plano de Testes (TDD)
<!-- Todo teste tem um ID e é escrito ANTES da implementação (Red). No código, cada teste carrega a tag `SPEC-0098:<ID>` — o G1 (`spec_graph.py verify`) verifica. -->

### 7.1 Testes de Caracterização
- N/A — adaptador novo, sem comportamento anterior; o núcleo do probe tem os testes dele (SPEC-0096).

### 7.2 Testes Unitários
- **UT-01** — Dado a AWS CLI falsa com a fila `orders` (12 visíveis, 3 em voo, 0 atrasadas, RedrivePolicy para `orders-dlq`), a DLQ `orders-dlq` com 2 visíveis e a métrica de idade com o último ponto 42, quando `queue` roda com `attrs: {region: us-east-1, type: sqs, dlq: orders-dlq}`, então sai exatamente um item com `visible: 12`, `in_flight: 3`, `oldest_age_seconds: 42`, `dlq_visible: 2`, `delayed: 0`, `oldest_age_source: "cloudwatch"`, `dlq: "queue:orders-dlq"`, `redrive: true` e `redrive_matches_dlq: true`, e as URLs vieram de `sqs get-queue-url` (um atributo `url` com conta posto no `attrs` é ignorado); com a fila `jobs.fifo` sem `dlq` e sem RedrivePolicy, `fifo: true`, `redrive: false` e `dlq_visible: null`; com a RedrivePolicy apontando para outra fila, `redrive_matches_dlq: false`.
- **UT-02** — Dado o `get-metric-data` sem pontos, e depois com AccessDenied, quando `queue` roda, então `oldest_age_seconds` é `null` com `oldest_age_source` `"sem dados"` e `"sem permissão"`, e `visible` e `in_flight` seguem preenchidos com `status: ok`; dado `QueueDoesNotExist` para a fila, então `status: error` e "fila não encontrada"; para a DLQ, "DLQ não encontrada".
- **UT-03** — Dado o tópico `orders-events` com cinco assinaturas (sqs para `orders` com filtro `{"event_type": ["created"], "region": ["br"]}` no escopo `MessageAttributes`, lambda `notify`, duas https para endpoints diferentes e uma `PendingConfirmation`), quando `subscriptions` roda, então saem cinco itens, nenhum do tópico, com `destination` `queue:orders`, `function:notify` e `https:[REDACTED]` (duas vezes, com `destination_fingerprint` diferentes), `filter_keys: ["event_type", "region"]`, `filter_fingerprint` no formato `sha256:<16 hex>` (e `null` onde não há filtro), a pendente com `pending_confirmation: true`, `message` "5 assinaturas, 1 pendentes", e nenhum valor do filtro (`created`, `br`) na saída; o mesmo filtro com as chaves em outra ordem dá a mesma impressão digital, e com `["deleted"]` dá outra; o ARN do tópico é montado com a conta e a partição de `sts get-caller-identity` (um atributo `arn` no `attrs` é ignorado); com 150 assinaturas e `lines: 200`, saem 100 e `truncated: true`; sem assinaturas, `items: []` e "0 assinaturas, 0 pendentes"; com `NotFound`, `status: error` e "tópico não encontrado".
- **UT-04** — Dado a AWS CLI falsa respondendo, em cada caso, SSO expirado, profile inexistente, sem credenciais, AccessDenied, Throttling, sem conexão, timeout, JSON inválido e outro erro (e, num caso, sem `aws` no PATH), quando qualquer verbo roda, então o adaptador sai com 0, `status: error`, `items: []` e a mensagem fixa do contrato ("renove o login da nuvem" no SSO); o profile, o ARN, a URL da fila e o id de conta do stderr falso não aparecem na saída.
- **UT-05** — O dublê registra cada argv. Em todos os testes, todo argv começa com um par (serviço, operação) da lista, traz `--region`, `--profile`, `--output json`, `--no-cli-pager` e os timeouts, e nenhuma opção fora da lista; `get-queue-attributes` pede só os quatro atributos; o número de chamadas por execução respeita os máximos da seção 5. `queue` com alvo `topic`, `subscriptions` com alvo `queue`, um verbo desconhecido ou uma tentativa de operação fora da lista (via nome de verbo `receive`) são recusados com "chamada não permitida" e nenhuma chamada registrada.
- **UT-06** — Dado entradas com nome de fila começando com `-`, nome com espaço, nome de fila com 81 caracteres, região `us-east-1; rm`, `attrs.region` ausente, profile com quebra de linha e um stdin que não é `probe@2`, quando o adaptador roda, então sai "entrada inválida" ou "recurso sem região no atlas" sem nenhuma chamada; dado respostas da AWS com `123456789012` em ARNs e URLs, nenhum `123456789012` aparece na saída do adaptador.

### 7.3 Testes de Integração
- **IT-01** — Com o `atlas.py` real (núcleo `probe@2`), um atlas temporário com `service:api`, o deployment `dev-api` em `environment:dev` (`tier: test`), as arestas para `queue:orders` (com `dlq: orders-dlq`) e `topic:orders-events`, o acesso local `access.cloud.dev.profile`, o adaptador declarado sem `command` em `probes.adapters.aws-messaging` e a AWS CLI falsa no PATH, quando `atlas.py probe messaging queue --service api --env dev --resource queue:orders --json` e `... subscriptions --resource topic:orders-events --json` rodam como processos, então as saídas passam no validador do núcleo com os itens do UT-01 e do UT-03; o argv registrado pelo dublê só tem operações da lista de leitura; o nome do profile e `123456789012` não aparecem na saída nem no `probes.log`, que tem a linha com `resource`.
- **IT-02** — No mesmo cenário, com a AWS CLI falsa respondendo SSO expirado, quando `atlas.py probe messaging queue ... --json` roda, então o exit é 1, a saída tem `status: error` e "renove o login da nuvem", e o `probes.log` registra `status: error` sem o profile.

### 7.4 Testes de Contrato
- **CT-02** — As saídas reais de `queue` e `subscriptions` dos UT-01 e UT-03, quando conferidas contra a tabela 4a do ADR-0026 (a mesma tabela que o `verify@2` lê), cumprem: `queue` tem exatamente um item, com `visible` e `in_flight` inteiros ≥ 0, `oldest_age_seconds` inteiro ou `null` e `dlq_visible` inteiro ou `null`; `subscriptions` tem um item por assinatura, todos com `destination` texto não vazio no formato `kind:id` ou `<protocolo>:[REDACTED]` e `filter_fingerprint` `sha256:<16 hex>` ou `null`, sem dois itens com o mesmo par (`destination`, `destination_fingerprint`). Uma saída com um item a mais em `queue`, sem `in_flight` ou com um item-resumo de tópico é recusada pela mesma conferência.
- **CT-01** — O `--describe` real do adaptador, as saídas reais de `queue`, `subscriptions` e de erro (geradas com o dublê) e os blocos `json probe@2 ...` válidos de `references/probes/aws-messaging.md` passam no validador `probe@2` do núcleo (SPEC-0096); os blocos marcados `invalid` (verbo com espaço, `targets` com kind desconhecido, item com objeto aninhado, chave a mais na saída) são recusados.

### 7.5 Testes E2E
- N/A — CLI sem jornada de usuário; o IT-01 roda o comando de ponta a ponta com o dublê.

### 7.6 Outros
- N/A — a segurança (lista fechada, máscara, sem shell) está nos UT-04 a UT-06 e no IT-01.

**Dublês e dados de teste:**
- `tests/fixtures/aws-messaging/fake_aws.py`, copiado como `aws` numa pasta do PATH: responde por (serviço, operação, nome) a partir de cenários JSON ao lado dele, registra cada argv num arquivo da pasta temporária e falha o teste com qualquer operação fora da lista.
- Respostas só com nomes `acme`, `orders`, `orders-dlq`, `orders-events`, `notify`, região `us-east-1` e a conta de exemplo `123456789012` (que precisa sair mascarada).
- Sem AWS de verdade e sem rede; HOME, `XDG_CONFIG_HOME` e `ATLAS_CONFIG_HOME` temporários, nenhum `~/.aws` real.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, pela versão do plugin. Só roda com `probes.enabled: true`, o adaptador declarado em `probes.adapters.aws-messaging` com os verbos liberados e `access.cloud.<ambiente>.profile` definido.
- **Dados/schema:** N/A — nada persistido.
- **Compatibilidade:** aditivo; o adaptador `kubernetes` e o `probe@1` não mudam. Depende dos atributos `region`, `type` e `dlq` do coletor `aws` (SPEC-0097), que não levam id de conta (ADR-0025 regra 4); um atlas escrito à mão com esses atributos também serve. Os itens seguem a tabela 4a do ADR-0026; mudar um campo dela é emenda com `contract_version` novo.
- **Observabilidade:** o `probes.log` do núcleo, com `resource` e `status`; o `doctor` mostra o adaptador e se a `aws` foi encontrada.
- **Rollback:** tirar o adaptador de `probes.adapters` (a verificação volta a "não verificado") ou voltar a versão do plugin.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] De onde vem a idade da mensagem mais antiga? — Da métrica `ApproximateAgeOfOldestMessage` do CloudWatch, numa chamada `get-metric-data`, porque o `GetQueueAttributes` não tem esse atributo e espiar a mensagem é proibido; sem ponto ou sem permissão, `null` com o motivo (Architect, 2026-11-24, recomendado)
- [x] O filtro da assinatura sai em texto, mascarado, quando pedido? — Não. Saem só a presença, o escopo, as chaves e a impressão digital; os valores podem ter dado de cliente e a impressão digital basta para o `verify` ver a mudança (Architect, 2026-11-24, recomendado)
- [x] Como o destino vira `kind:id` do grafo? — O adaptador não tem o grafo: emite `queue:<nome>`, que é o id de fila do coletor `aws` (SPEC-0097), e o `verify` (SPEC-0102) cruza com o grafo; protocolos que apontam para pessoa ou host saem `<protocolo>:[REDACTED]`, com `destination_fingerprint` para não colidirem (Architect, 2026-11-24, recomendado)
- [x] Como achar a URL da fila e o ARN do tópico sem guardar a conta? — Pela própria CLI, com operações de leitura da lista: `sqs get-queue-url` e `sts get-caller-identity` (que não precisa de permissão); o atlas não guarda ARN nem URL (ADR-0025 regra 4) (Architect, 2026-11-24, recomendado)
- [x] FIFO pelo atributo `FifoQueue`? — Não: pelo sufixo `.fifo`, que a AWS exige no nome de toda fila FIFO, sem uma chamada a mais (Architect, 2026-11-24, recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Contrato e implementação**
- [ ] Red: UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, IT-01, IT-02, CT-02, CT-01 com a tag `SPEC-0098:<ID>`, falhando pelo motivo certo
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
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=76, skipped=1)) — 44735ab | 2026-11-25 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 77595ce | 2026-11-25 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 05b06ef | 2026-11-25 |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0098`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
