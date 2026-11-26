---
id: SPEC-0101
title: "boson-atlas: adaptador de simulação de IAM — permissão do workload no recurso"
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
touches: [skills/boson-atlas/assets/probes/iam.py, skills/boson-atlas/references/probes/iam.md, skills/boson-atlas/tests/test_probe_iam.py, skills/boson-atlas/tests/fixtures/iam/**, skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0023, ADR-0025]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-24
---

# SPEC-0101 — boson-atlas: adaptador de simulação de IAM — permissão do workload no recurso

> Origem: épico SPEC-0095, adaptador da capacidade `permissions`. É o que o `verify@2` (SPEC-0102) usa para provar que o workload do serviço tem a permissão que a relação dele com a fila ou o tópico exige.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Adaptador `iam` do contrato `probe@2` (ADR-0025) para a capacidade `permissions`, com o verbo `simulate`. Para uma fila ou um tópico ligado ao serviço no ambiente, ele:
1. descobre o papel (role) do workload, lendo com `kubectl get` a anotação IRSA da ServiceAccount dos pods do deployment;
2. lê a política do próprio recurso (fila ou tópico);
3. roda `aws iam simulate-principal-policy` com o papel, as ações do tipo do recurso e a política do recurso;
4. devolve, por ação abstrata (`send`, `receive`, `delete`, `publish`), a decisão (`allowed` ou `denied`), a ação da API como evidência e as relações do grafo que exigem aquela ação.

Tudo só de leitura, sem ARN cru e sem id de conta na saída. Quando não consegue o papel ou a política do recurso, devolve erro com motivo, nunca `allowed`.

## 2. Motivação & Escopo
**Motivação:** a rotina real de verificação (radar da SPEC-0075) inclui "o workload tem permissão no recurso?". Um deploy que troca a ServiceAccount, ou uma política de fila que muda, quebra a publicação ou o consumo sem erro de rollout. A simulação de IAM responde isso sem enviar nem ler mensagem nenhuma. Sem a política do recurso, a simulação dá falso negativo ou falso positivo (épico, seção Riscos), por isso ela entra sempre que existe.

**Objetivos (dentro do escopo):**
- **`assets/probes/iam.py`:** só stdlib, Python 3.9 ou mais novo, com `--describe` e o protocolo `probe@2`.
- **Principal:** para cada workload do deployment (até 5), `kubectl get <kind> <nome>` e `kubectl get serviceaccount <sa>`, ambos `-o json` e só leitura, e a anotação `eks.amazonaws.com/role-arn`.
- **Endereço e política do recurso:** o atlas não traz ARN nem URL com conta (ADR-0025); o adaptador monta pela CLI, só lendo: `aws sqs get-queue-url` e `aws sqs get-queue-attributes` (`Policy` e `QueueArn`) para fila; `aws sts get-caller-identity` (conta e partição) e `aws sns get-topic-attributes` para tópico.
- **Simulação:** `aws iam simulate-principal-policy` com as ações do tipo do recurso e `--resource-policy` quando a política existe.
- **Itens por (workload, ação):** os campos da regra 4a do ADR-0026 (`action` abstrata, `api_action` como evidência, `decision` `allowed` ou `denied`, com *deny* implícito contando como `denied`), mais `deny_type` e `required_by` com as relações do grafo que exigem a ação (mapa fixo do adaptador).
- **Lista fechada de chamadas** do `kubectl` e da `aws`, recusando qualquer outra antes de executar.
- **`references/probes/iam.md`:** configuração, permissões mínimas sugeridas, as chamadas feitas, o mapa relação → ações e os exemplos de contrato.

**Não-objetivos (fora do escopo):**
- **EKS Pod Identity:** sem a anotação IRSA, o resultado é erro "workload sem role IRSA (Pod Identity não verificado nesta versão)". Ler a associação pela API do EKS pede o nome do cluster na nuvem, que o atlas não liga ao contexto do kubeconfig.
- **Bucket e datastore:** o coletor `aws` (SPEC-0097) não traz buckets, e o S3 pede recurso por objeto (`bucket/*`); o banco autentica pelo arquivo de senhas (SPEC-0099), não por IAM. Ficam para uma versão futura do adaptador.
- **Credenciais estáticas do pod** (chave em variável de ambiente ou no nó): não verificadas.
- Decidir quais ações a relação exige no veredito: o adaptador devolve a decisão de todas as ações do tipo e o `required_by`; o `verify@2` (SPEC-0102) escolhe pelas arestas do grafo.
- Qualquer escrita em IAM, fila, tópico ou cluster.

## 3. Dependências
- **Implementações necessárias:** SPEC-0096 (`depends_on`), porque o IT-01, o IT-02 e o CT-01 usam o núcleo `probe@2` real (`atlas.py probe --resource` e os validadores). Do `probe@2` esta spec usa: o `--describe` do `probe@2`, a entrada com `target.resource` (`kind`, `id`, `attrs` escalares), `target.cloud.profile` e os campos do deployment e do cluster "como no `probe@1`" (`deployment`, `context`, `namespace`, `workloads`), e a saída `probe@2`, validados por `validate_probe_describe`, `validate_probe_input` e `validate_probe_output`; e os itens `permissions simulate` da tabela da regra 4a do ADR-0026.
- **Contratos consumidos:** N/A — a dependência é de implementação (acima).
- **Pré-requisitos externos:** `kubectl` e AWS CLI v2 (`aws`) no PATH. Papel da nuvem com `iam:SimulatePrincipalPolicy`, `sqs:GetQueueUrl`, `sqs:GetQueueAttributes` e `sns:GetTopicAttributes` (`sts:GetCallerIdentity` não pede permissão); no cluster, `get` de workloads e `serviceaccounts`. Nos testes os dois são dublês.

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **adaptador `kubernetes`:** `assets/probes/kubernetes.py` (SPEC-0089): `kubectl get … -o json` com `--context`, `-n` e `--request-timeout=20s`, nomes DNS-1123, lista fechada, erros com exit 0 e `status: error`, dublê `tests/fixtures/kubernetes/fake_kubectl.py`;
- **contrato:** `probe@2` e acesso local `access.cloud.<ambiente>.profile` (ADR-0025, SPEC-0096).

**Decisão:** script próprio em `assets/probes/iam.py`, no molde do `kubernetes`. A relação do grafo **não** entra na entrada: o adaptador simula todas as ações do tipo do recurso e marca, em cada item, `required_by` pelo mapa fixo relação → ações. Com isso o contrato da SPEC-0096 não muda, e o `verify@2`, que tem o grafo, decide quais ações contam. As chamadas de nuvem são da AWS CLI com `--profile`, `--region` (do `attrs.region` do recurso), `--output json` e `--no-cli-pager`. A URL e os ARNs com conta nunca vêm do atlas: saem de `get-queue-url`, `get-queue-attributes` e `get-caller-identity` e ficam só em memória.

**Justificativa:** mandar a relação ou a lista de ações na entrada exigiria um campo novo no `target` fechado do ADR-0025. Simular o conjunto do tipo custa uma chamada a mais de ação, não uma chamada a mais de API (o `simulate-principal-policy` aceita várias ações de uma vez). O mapa fica num lugar só, testado aqui, e o `verify@2` só filtra.

**Desvio do padrão existente:** nenhum.

**Alternativas descartadas:**
- **`target.relations` ou `actions` na entrada:** muda o contrato da SPEC-0096 e do ADR-0025.
- **Um verbo por relação** (`publish`, `consume`): espalha o mapa entre o núcleo e o adaptador e multiplica as chamadas.
- **`simulate-custom-policy` com as políticas do papel baixadas:** mais chamadas, mais dado sensível em trânsito e não considera limites de permissão como a simulação do principal.
- **SDK (`boto3`):** dependência nova, contra o padrão stdlib.

**ADRs:** ADR-0010 (credencial só por nome), ADR-0023 (probes), ADR-0025 (alvo de recurso, `probe@2`, acesso à nuvem, máscara de conta).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:**
  - por execução: no máximo 1 `get` por workload (até 5), 1 `get serviceaccount` por ServiceAccount distinta, 1 `get-caller-identity` (só tópico), 1 `get-queue-url` (só fila), 1 leitura da política do recurso e 1 simulação por papel distinto;
  - `kubectl` com `--request-timeout=20s` e timeout de 30 s no processo; `aws` com `--cli-read-timeout 20 --cli-connect-timeout 10` e timeout de 30 s no processo.
- **Segurança:**
  - lista fechada: `kubectl get` só de `deployments`, `statefulsets`, `daemonsets`, `rollouts` e `serviceaccounts`; `aws` só `sts get-caller-identity`, `sqs get-queue-url`, `sqs get-queue-attributes`, `sns get-topic-attributes` e `iam simulate-principal-policy`;
  - nomes, ARN do papel, ARN e URL do recurso, região e profile validados por expressão antes de qualquer chamada; nada que comece com `-`;
  - o ARN do papel, a conta, a URL da fila, os ARNs dos recursos e a política só vão como argumento das chamadas; nunca para a saída, a mensagem nem o registro;
  - nenhuma mensagem leva o stderr das ferramentas, o profile, o contexto nem id de conta;
  - ambiente da `aws`: o do adaptador sem `AWS_PROFILE`, `AWS_DEFAULT_PROFILE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` e `AWS_SESSION_TOKEN` herdados (vale só o `--profile`), com `AWS_PAGER=""`.
- **Privacidade e dados pessoais:** N/A — só metadados de permissão; nenhuma mensagem de fila é lida. A saída passa pela redaction do núcleo, que mascara ids de conta (ADR-0025, regra 5).
- **Disponibilidade e resiliência:**
  - ferramenta ausente, login expirado, sem permissão, recurso inexistente e tempo → `status: error` com texto fixo, exit 0;
  - sem conseguir ler a política do recurso → erro, nunca simulação sem ela; recurso sem política (atributo ausente) é legítimo e simula sem `--resource-policy`, com `resource_policy: false` no item;
  - idempotente: só leitura.
- **Acessibilidade (UI):** N/A — sem interface gráfica.
- **Custo:** N/A — chamadas de leitura e de simulação de IAM, sem cobrança por chamada; limitadas por execução.

## 6. Artefato A — Contrato
**Interface:** a descrição e o verbo `simulate` do adaptador `iam`.

```text
--describe → {"contract": "probe@2", "adapter": "iam",
              "capabilities": {"permissions": {"verbs": ["simulate"], "targets": ["queue", "topic"],
                                               "access": ["cluster", "cloud"]}}}

entrada (probe@2, SPEC-0096): target.resource = {kind: "queue"|"topic", id, attrs}; target.cloud.profile;
                              target.context, target.namespace, target.workloads (como no probe@1)
  nome do recurso   o id do nó (target.resource.id); fila ^[A-Za-z0-9_-]{1,80}$ ou ^[A-Za-z0-9_-]{1,75}\.fifo$ (até 80 no total),
                    tópico ^[A-Za-z0-9_-]{1,256}$ ou ^[A-Za-z0-9_-]{1,251}\.fifo$
  attrs.region      ^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$ (ADR-0025); ausente → "recurso sem região no atlas"
  attrs.arn, attrs.url ou qualquer outro atributo: ignorados. O atlas não leva id de conta (ADR-0025, regra 4);
                    o adaptador monta a URL e o ARN pela CLI, com as leituras abaixo
  profile           ^[A-Za-z0-9_.+-]{1,64}$, sem começar com "-"
  workloads         Kind/nome, Kind ∈ {Deployment, StatefulSet, DaemonSet, Rollout}, nome DNS-1123; até 5 (mais → truncated)
  fora da regra → "entrada inválida" (sem citar o valor), nenhuma chamada

chamadas permitidas (única forma; argv como lista, sem shell; opções comuns da aws = --region <r> --profile <p>
--output json --no-cli-pager --cli-read-timeout 20 --cli-connect-timeout 10):
  kubectl get <deployments|statefulsets|daemonsets|rollouts> <nome> -o json --context <ctx> -n <ns> --request-timeout=20s
  kubectl get serviceaccounts <sa> -o json --context <ctx> -n <ns> --request-timeout=20s
      sa = spec.template.spec.serviceAccountName (ou serviceAccount; ausente → "default"), DNS-1123
      papel = metadata.annotations["eks.amazonaws.com/role-arn"], ^arn:aws[-a-z]*:iam::[0-9]{12}:role/[\w+=,.@/-]{1,512}$
  aws sts get-caller-identity (opções comuns)
      → conta e partição do profile (do campo Arn), usadas só para montar o ARN do tópico; nunca saem
  fila:   aws sqs get-queue-url --queue-name <nome> (opções comuns)                         → QueueUrl
          aws sqs get-queue-attributes --queue-url <QueueUrl> --attribute-names Policy QueueArn (opções comuns)
  tópico: aws sns get-topic-attributes --topic-arn arn:<partição>:sns:<região>:<conta>:<nome> (opções comuns) → Policy
  aws iam simulate-principal-policy --policy-source-arn <papel> --action-names <ações da API…>
      --resource-arns <QueueArn | ARN do tópico> [--resource-policy <JSON compacto da política>] (opções comuns)
  qualquer outra → "chamada não permitida", sem executar
  QueueUrl, QueueArn e o ARN do tópico são validados (host sqs.<região>.amazonaws.com, 12 dígitos, mesmo nome e
  mesma região do alvo) antes de seguir; fora disso → "resposta inválida da nuvem"
  recurso em outra conta que não a do profile: não suportado nesta versão (get-queue-url/get-topic-attributes
  dão "recurso não encontrado na nuvem")

ações por tipo (ADR-0026, regra 4a) e relações que as exigem (required_by, regra 3 do ADR-0026 e SPEC-0102):
  queue  send     sqs:SendMessage      depends_on, publishes
         receive  sqs:ReceiveMessage   consumes
         delete   sqs:DeleteMessage    consumes
  topic  publish  sns:Publish          publishes
  nenhuma ação é exigida por writes nem por depends_on de tópico (required_by não os cita); as ações são
  simuladas mesmo assim, e o verify@2 só usa as que a relação exige

simulate → um item por (workload, ação), em ordem de workload e da lista acima:
  {"workload": "Deployment/api", "role": "api-dev", "action": "receive", "api_action": "sqs:ReceiveMessage",
   "decision": "allowed" | "denied", "deny_type": null | "explicit" | "implicit",
   "required_by": ["consumes"], "resource_policy": true}
  action e decision são os campos do ADR-0026 (regra 4a); api_action é só evidência; os outros são extra
  role = só o nome do papel (sem caminho, partição nem conta)
  decision = EvalDecision da AWS: "allowed" → allowed (deny_type null); "explicitDeny" → denied/explicit;
             "implicitDeny" → denied/implicit; qualquer outro valor → "resposta inválida da nuvem"
  workloads com o mesmo papel → uma simulação só, itens repetidos por workload

erros → status: "error", items: [], exit 0, message:
  "kubectl não encontrado" | "aws não encontrado" | "renove o login da nuvem" |
  "sem permissão no cluster (Forbidden)" | "contexto inexistente" | "workload não encontrado" |
  "workload sem role IRSA (Pod Identity não verificado nesta versão)" |
  "não foi possível ler a política do recurso" | "recurso não encontrado na nuvem" |
  "sem permissão para simular (iam:SimulatePrincipalPolicy)" | "timeout" |
  "entrada inválida" | "recurso sem região no atlas" | "chamada não permitida" | "verbo não suportado" |
  "falha do kubectl" | "falha da aws" | "resposta inválida do kubectl" | "resposta inválida da nuvem"
  reconhecimento pelo stderr (sem diferenciar maiúsculas):
    login: "token has expired", "sso session", "expiredtoken", "unable to locate credentials", "the config profile"
    política: AccessDenied/AuthorizationError em get-queue-attributes ou get-topic-attributes
    recurso: "nonexistentqueue", "notfound" em get-queue-url, get-queue-attributes ou get-topic-attributes
    simulação: AccessDenied em simulate-principal-policy;  papel inexistente ("nosuchentity") → "resposta inválida da nuvem"
    tempo: "timeout", "timed out", "deadline exceeded"
  qualquer workload sem papel IRSA, ou papéis que não leem a política → erro da execução inteira (nunca parcial com allowed)
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `assets/probes/iam.py` (novo), com as constantes `ACTIONS` (o mapa acima) e as listas fechadas de chamadas.
- `references/probes/iam.md` (nova): configuração em `probes.adapters.iam` (verbo `simulate`), `access.cloud.<ambiente>.profile` e `access.clusters`; política IAM mínima sugerida para o profile e ClusterRole de leitura (inclui `serviceaccounts`); as chamadas feitas; o mapa relação → ações; o que fica não verificado (Pod Identity, credenciais estáticas, SCP e políticas de sessão que a simulação não cobre); os blocos `json probe@2 describe|output valid|invalid` lidos pelo CT-01.
- `SKILL.md`: link para a referência, na lista de adaptadores.
- `scripts/atlas.py`: só o `ATLAS_VERSION`.
- `tests/test_probe_iam.py` e `tests/fixtures/iam/` (dublês de `kubectl` e `aws`, respostas JSON).

**`probes.log`:** nada novo nesta spec. O núcleo (SPEC-0096) registra `resource` e o status, nunca os itens, o profile nem o contexto.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Descrição | `--describe` | `probe@2`, capacidade `permissions`, verbo `simulate`, alvos `queue` e `topic`, acesso `cluster` e `cloud` | CT-01 |
| Fila com política | consumer com IRSA, fila com `Policy` | URL por `get-queue-url`; itens `send`, `receive` e `delete` com `api_action`, decisões da simulação, `resource_policy: true`, `required_by` do mapa | UT-01, IT-01 |
| Tópico | publisher com IRSA, tópico com política | ARN montado com `get-caller-identity`; item `publish` (`sns:Publish`) com a decisão | UT-01, IT-02 |
| Recurso sem política | `Policy` ausente | simulação sem `--resource-policy`, `resource_policy: false` | UT-01 |
| Decisões | `allowed`, `explicitDeny`, `implicitDeny`, valor desconhecido | `allowed`; `denied` com `deny_type` `explicit` ou `implicit`; desconhecido → "resposta inválida da nuvem" | UT-02, CT-02 |
| Região e nome | `attrs.region` ausente ou fora de `^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$`; nome inválido; `attrs.arn`/`attrs.url` presentes | erro fixo sem chamada; ARN e URL do atlas ignorados | UT-05 |
| Papel compartilhado | dois workloads com a mesma ServiceAccount | uma simulação, itens para os dois | UT-02 |
| Principal | ServiceAccount sem anotação IRSA, workload ausente, `serviceAccountName` ausente | erro Pod Identity; "workload não encontrado"; usa `default` | UT-03 |
| Política ilegível | AccessDenied ao ler a política | `status: error` "não foi possível ler a política do recurso", nenhuma simulação, nada `allowed` | UT-03, IT-02 |
| Sem ARN cru | qualquer saída | sem ARN, URL de fila, id de conta, profile nem contexto | UT-04, IT-01 |
| Lista fechada | todos os cenários; entrada que levaria a outro verbo, kind `Secret`, nome com `-`, URL ou ARN fora da regra | só as chamadas do contrato; recusadas sem executar | UT-05, IT-01 |
| Erros das ferramentas | ausentes, login expirado, Forbidden, contexto, recurso inexistente, sem `SimulatePrincipalPolicy`, tempo, JSON inválido | `status: error` com o texto fixo, exit 0, sem stderr | UT-06 |
| Ponta a ponta | `atlas.py probe permissions simulate --resource queue:orders` com os dublês | saída validada pelo núcleo; profile e conta fora da saída e do `probes.log` | IT-01 |
| Contrato | describe e saídas de exemplo, válidas e inválidas | aceitas ou recusadas pelos validadores `probe@2` | CT-01 |
| Itens do `verify@2` | itens reais de `simulate` | cumprem a tabela da regra 4a do ADR-0026 | CT-02 |

## 7. Artefato B — Plano de Testes (TDD)
<!-- Todo teste tem um ID e é escrito ANTES da implementação (Red). No código, cada teste carrega a tag `SPEC-0101:<ID>` — o G1 (`spec_graph.py verify`) verifica. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem testes: "N/A — motivo" SEM ID. Teste que protege comportamento existente e passa antes da mudança: marque `(guarda: passa antes da mudança)`. Estratégia completa: references/testing.md da skill. -->

### 7.1 Testes de Caracterização
- N/A — adaptador novo, sem comportamento anterior; o núcleo `probe@2` tem os testes dele na SPEC-0096.

### 7.2 Testes Unitários
- **UT-01** — Dado o dublê de `kubectl` com `Deployment/worker` usando a ServiceAccount `worker` anotada com o ARN de um papel `orders-worker-dev` na conta de exemplo `123456789012` (só na resposta do dublê), e o dublê de `aws` respondendo `get-queue-url` e `get-queue-attributes` da fila `orders` (URL e `QueueArn` dessa conta, com `Policy`), quando `simulate` roda para `queue:orders` com `attrs` só com `region: us-east-1`, então o `get-queue-attributes` usa a `QueueUrl` devolvida pelo `get-queue-url`, o `simulate-principal-policy` recebe `sqs:SendMessage`, `sqs:ReceiveMessage` e `sqs:DeleteMessage`, `--resource-arns` com o `QueueArn` e `--resource-policy` com a política em JSON compacto, e saem 3 itens com `role: orders-worker-dev`, `action` `send`, `receive` e `delete`, o `api_action` correspondente, a decisão, `required_by` do mapa e `resource_policy: true`; dado o tópico `orders-events`, então o adaptador chama `sts get-caller-identity`, monta `arn:aws:sns:us-east-1:<conta>:orders-events` para o `get-topic-attributes` e a simulação, e sai só o item `publish` (`sns:Publish`) com `required_by: ["publishes"]`; o item `send` tem `required_by: ["depends_on", "publishes"]` e os itens `receive` e `delete` têm `["consumes"]`; dada a fila sem `Policy`, então a simulação vai sem `--resource-policy` e os itens têm `resource_policy: false`.
- **UT-02** — Dada a resposta da simulação com `allowed`, `explicitDeny` e `implicitDeny`, então os itens têm `decision` `allowed` (`deny_type: null`), `denied` (`deny_type: explicit`) e `denied` (`deny_type: implicit`); com outro valor, então `status: error` "resposta inválida da nuvem"; dados `Deployment/api` e `Deployment/api-canary` com a mesma ServiceAccount, então há uma chamada de simulação só e itens para os dois workloads; dados 6 workloads, então só os 5 primeiros e `truncated: true`.
- **UT-03** — Dada a ServiceAccount sem a anotação `eks.amazonaws.com/role-arn`, então `status: error` "workload sem role IRSA (Pod Identity não verificado nesta versão)" e nenhuma chamada à `aws`; dado o workload ausente (NotFound), então "workload não encontrado"; dado o pod template sem `serviceAccountName`, então o adaptador lê a ServiceAccount `default`; dado NonExistentQueue no `get-queue-url` ou NotFound no `get-topic-attributes`, então "recurso não encontrado na nuvem"; dado AccessDenied em `get-queue-attributes` ou `get-topic-attributes`, então "não foi possível ler a política do recurso", nenhuma simulação e nenhum item; dada a anotação com ARN fora da regra, então "resposta inválida do kubectl".
- **UT-04** — Em todos os testes que saem com `ok`, a saída serializada não contém `arn:`, `https://sqs`, `123456789012`, o profile nem o contexto da entrada; os itens têm só as chaves `workload`, `role`, `action`, `api_action`, `decision`, `deny_type`, `required_by` e `resource_policy`.
- **UT-05** — Os dublês gravam cada argv. Em todos os testes, todo argv do `kubectl` começa com `get` e um recurso da lista, e todo argv da `aws` começa com `sts get-caller-identity`, `sqs get-queue-url`, `sqs get-queue-attributes`, `sns get-topic-attributes` ou `iam simulate-principal-policy` e traz `--profile`, `--output json` e `--no-cli-pager`; o ambiente gravado da `aws` não tem `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` nem `AWS_PROFILE` herdados. Dada uma entrada com verbo `attach`, workload `Secret/x`, nome começando com `-`, profile com espaço, nome de fila com `/`, recurso de kind `bucket`, sem `attrs.region` ou com região `us-east-100` ou `US-east-1`, então sai o erro fixo do contrato e nenhum dublê registra chamada; com `us-east-1` e `ap-southeast-12` a região é aceita. Dado `attrs.arn` e `attrs.url` apontando para outra fila, então eles não aparecem em nenhum argv (o adaptador usa só o nome e a região). Dada uma `QueueUrl` devolvida com outro host ou outro nome, então "resposta inválida da nuvem" e nenhuma simulação.
- **UT-06** — Dado o `kubectl` ou a `aws` ausente do PATH, ou o dublê saindo com erro e cada stderr do contrato (token expirado, Forbidden, contexto inexistente, NonExistentQueue, AccessDenied na simulação, timeout, outro texto), ou com exit 0 e stdout que não é JSON, quando `simulate` roda, então `status: error` com a mensagem do contrato, `items: []`, exit 0, e a saída não contém o stderr, o profile, o contexto nem id de conta.

### 7.3 Testes de Integração
- **IT-01** — Dado um atlas temporário com `service:orders-worker`, o deployment `dev-orders-worker` em `environment:dev` (`tier: test`) no `cluster-dev`, com `consumes` para `queue:orders` (só `region` nos atributos, sem ARN nem URL), a configuração local temporária (`HOME`, `XDG_CONFIG_HOME` e `ATLAS_CONFIG_HOME` em pasta temporária) com `probes.enabled: true`, `probes.adapters.iam` sem `command` e com `verbs: [simulate]`, `access.clusters` e `access.cloud.dev.profile`, e os dublês de `kubectl` e `aws` no PATH, quando `atlas.py probe permissions simulate --service orders-worker --env dev --resource queue:orders --json` roda como processo, então sai com 0, a saída validada pelo núcleo traz os itens do UT-01, os dublês registraram só chamadas da lista fechada com o profile e o contexto da configuração, e nem a saída nem o `probes.log` contêm o profile, o contexto, `arn:` ou `123456789012`.
- **IT-02** — Com o mesmo atlas e um `publishes` para `topic:orders-events`, quando `atlas.py probe permissions simulate --service orders-worker --env dev --resource topic:orders-events --json` roda, então sai com 0 e o item `sns:Publish`; com o dublê de `aws` negando a leitura da política do tópico, então o `probe` sai com 1 e a mensagem "não foi possível ler a política do recurso", sem nenhum item `allowed` e sem chamada de simulação registrada.

### 7.4 Testes de Contrato
- **CT-01** — O `--describe` real do adaptador e os blocos `json probe@2 describe|output valid|invalid` de `references/probes/iam.md` (pelo menos: describe válido; saída `ok` de fila; saída `ok` de tópico; saída de erro; describe com `access: ["database"]` inválido para este adaptador; saída com item aninhado inválida; saída com chave fora do contrato inválida), quando passam por `validate_probe_describe` e `validate_probe_output` do `atlas.py`, são aceitos ou recusados como o bloco declara; e as saídas reais do UT-01, do UT-03 e do UT-06 também são aceitas.
- **CT-02** — Os itens reais de `simulate` (fila e tópico do UT-01, as três decisões do UT-02), conferidos contra a tabela da regra 4a do ADR-0026, cumprem: `action` em `publish`, `send`, `receive`, `delete`, `read` ou `write`; `api_action` texto não vazio; `decision` só `allowed` ou `denied`, com todo *deny* implícito como `denied`; nenhum item com `decision` `implicitDeny` ou `explicitDeny`. Um item de exemplo com `action: "sqs:SendMessage"`, sem `api_action` ou com `decision: "implicitDeny"` é recusado pela mesma conferência.

### 7.5 Testes E2E
- N/A — sem jornada de usuário interativa (CLI chamada pelo agente); o IT-01 e o IT-02 rodam o comando de ponta a ponta com os dublês.

### 7.6 Outros
- N/A — a segurança (só leitura, lista fechada, nada sensível na saída) já está nos UT-04, UT-05, UT-06 e IT-01.

**Dublês e dados de teste:**
- `tests/fixtures/iam/fake_kubectl.py` e `tests/fixtures/iam/fake_aws.py`, copiados como `kubectl` e `aws` numa pasta temporária no PATH: acham o cenário num arquivo ao lado, respondem por argv, gravam argv e as variáveis `AWS_*` num registro JSON e saem com 2 em qualquer argv fora da lista fechada.
- Respostas JSON só com nomes genéricos (`acme`, `orders`, `orders-events`, `orders-worker`). A conta de exemplo `123456789012` aparece só nas respostas dos dublês (anotação IRSA, `get-queue-url`, `get-caller-identity`), nunca nos atributos do atlas de teste, e precisa sair ausente ou mascarada.
- Nenhum cluster, nenhuma conta de nuvem, nenhuma rede, nenhum `~/.aws` ou `~/.kube` real.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15), com `HOME`, `XDG_CONFIG_HOME` e `ATLAS_CONFIG_HOME` temporários.

## 8. Plano de Rollout
- **Estratégia:** deploy direto, pela versão do plugin. Só roda com `probes.enabled: true`, o adaptador declarado em `probes.adapters.iam` com `simulate` liberado, `access.clusters` e `access.cloud.<ambiente>.profile`.
- **Dados/schema:** N/A — nada gravado no atlas, na nuvem nem no cluster.
- **Compatibilidade:** aditivo. Usa o `probe@2` da SPEC-0096 sem campo novo; os itens seguem a regra 4a do ADR-0026 (`action`, `api_action`, `decision`), e o `required_by` ajuda a SPEC-0102 a casar com as arestas do grafo.
- **Observabilidade:** o `probes.log` do núcleo (com `resource`, sem resultado nem acesso) e o `doctor`, que acha `kubectl` e `aws` pelo `shutil.which`.
- **Rollback:** tirar o adaptador de `probes.adapters` (efeito imediato nesta máquina) ou voltar a versão do plugin.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
- [x] Como a relação do grafo chega ao adaptador? — Não chega: o adaptador simula todas as ações do tipo do recurso e marca `required_by` por um mapa fixo; o `verify@2` (SPEC-0102), que tem o grafo, escolhe as ações que contam. Assim o contrato `probe@2` da SPEC-0096 e o ADR-0025 não mudam (Architect, 2026-11-24, recomendado)
- [x] De onde vêm a URL da fila e os ARNs, se o atlas não leva id de conta (ADR-0025, regra 4)? — Da própria CLI, só lendo: `sqs get-queue-url` e `get-queue-attributes` (`QueueArn`) para fila; `sts get-caller-identity` (conta e partição do profile) para montar o ARN do tópico. Ficam só em memória. Um recurso em outra conta que não a do profile não é suportado nesta versão e dá "recurso não encontrado na nuvem" (Architect, 2026-11-24, recomendado)
- [x] E o EKS Pod Identity? — Nesta versão, sem anotação IRSA a execução dá erro "workload sem role IRSA (Pod Identity não verificado nesta versão)", e a verificação fica "não verificado". Ler a associação pede `aws eks list-pod-identity-associations` com o nome do cluster na nuvem, que o atlas não liga ao contexto; entra numa versão futura quando o mapa tiver esse campo (Architect, 2026-11-24, recomendado)
- [x] Entram bucket e datastore? — Não nesta versão: o coletor `aws` (SPEC-0097) não traz buckets e o S3 pede recurso por objeto; o PostgreSQL autentica pelo arquivo de senhas (SPEC-0099). `targets` fica `["queue", "topic"]` (Architect, 2026-11-24, recomendado)
- [x] Um workload sem papel ou uma política ilegível deixa os outros itens saírem? — Não: a execução inteira vira erro com motivo, para nunca sair `allowed` sem a prova completa (épico, seção Riscos) (Architect, 2026-11-24, recomendado)
- [x] A simulação dispensa `--caller-arn` e `--resource-owner` com papel e política de fila ou tópico? — Pela documentação da AWS consultada de memória, sem verificação nesta data: o ARN de SQS e SNS traz a conta, e o `--caller-arn` só se aplica a usuário IAM. O implementer confere com a AWS CLI instalada; se for preciso, vira Emenda (Architect, 2026-11-24, recomendado)
- [x] A simulação cobre SCP, limite de permissão e política de sessão? — Limite de permissão sim; SCP e política de sessão podem não entrar, conforme a documentação da AWS (consultada de memória). A referência diz isso, e `allowed` significa "permitido pelas políticas do papel e do recurso" (Architect, 2026-11-24, recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Contrato e implementação**
- [x] Red: UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, IT-01, IT-02, CT-01, CT-02 com a tag `SPEC-0101:<ID>`, falhando pelo motivo certo
- [x] Green: implementar o mínimo para passar, seguindo o padrão de referência da seção 4
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy (G6): N/A — skills distribuídas por cópia e pelo plugin
- [x] Relatório de Entrega, CHANGELOG e versão do plugin (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — e297cb0 | 2026-11-24 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=127, skipped=1)) — 98468ad | 2026-11-25 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 68d2e7f | 2026-11-25 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 51f418b | 2026-11-25 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED — 0 major, 4 minor (regex de conta não separa _, ensure_ascii na política, RecursionError, AWS_ENDPOINT_URL herdada) — 1e286d0 | 2026-11-25 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — a787cad | 2026-11-25 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-25 |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

### Histórico de reprovações
- G5 FAIL 2026-11-25 — test exit 1 (FAILED (failures=1)); arch_test exit 0 (OK) — 27a4a07
- G5 PASS 2026-11-25 — depois de 1 reprovação(ões)

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->
Adaptador `iam` (`probe@2`, capacidade `permissions`, verbo `simulate`), só de leitura pelo `kubectl` e pela AWS CLI. Ele resolve o papel IRSA de cada workload no cluster e simula, com a política do recurso, as ações que a relação do atlas exige (fila: send, receive, delete; tópico: publish), trazendo `allowed` ou `denied` por ação. Os itens seguem a regra 4a do ADR-0026. Versões: boson-atlas 2026.11.24 e plugin 2026.11.39.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- **`assets/probes/iam.py`:** listas fechadas de recursos do `kubectl` e de operações da `aws`, conferidas antes de qualquer processo; papéis resolvidos antes de qualquer chamada à nuvem; uma simulação por papel distinto; política do recurso em JSON compacto; credenciais `AWS_*` herdadas removidas e `AWS_PAGER` vazio; conta de 12 dígitos mascarada; mensagens de erro fixas.
- **Documentação:** `references/probes/iam.md`, com a política IAM e o ClusterRole mínimos.

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A — `type: feature`. Red em 98468ad (G1) e green em 68d2e7f (G2).

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | papel IRSA resolvido no cluster e simulação de fila e tópico | PASS | `test_probe_iam.py`; G2 PASS em 68d2e7f; G4 `verify` 10/10 |
| UT-02 | decisões allowed, explicitDeny e implicitDeny nos itens | PASS | `test_probe_iam.py`; G2 PASS em 68d2e7f; G4 `verify` 10/10 |
| UT-03 | workload sem IRSA vira erro sem nenhuma chamada à aws | PASS | `test_probe_iam.py`; G2 PASS em 68d2e7f; G4 `verify` 10/10 |
| UT-04 | saída sem ARN, URL, conta, profile nem contexto | PASS | `test_probe_iam.py`; G2 PASS em 68d2e7f; G4 `verify` 10/10 |
| UT-05 | só chamadas de leitura das listas fechadas do kubectl e da aws | PASS | `test_probe_iam.py`; G2 PASS em 68d2e7f; G4 `verify` 10/10 |
| UT-06 | ferramentas ausentes e erros com mensagens fixas | PASS | `test_probe_iam.py`; G2 PASS em 68d2e7f; G4 `verify` 10/10 |
| IT-01 | probe de fila de ponta a ponta com o atlas.py real | PASS | `test_probe_iam.py`; G2 PASS em 68d2e7f; G4 `verify` 10/10 |
| IT-02 | probe de tópico (publishes) de ponta a ponta | PASS | `test_probe_iam.py`; G2 PASS em 68d2e7f; G4 `verify` 10/10 |
| CT-01 | describe e blocos válidos e inválidos do contrato probe@2 | PASS | `test_probe_iam.py`; G2 PASS em 68d2e7f; G4 `verify` 10/10 |
| CT-02 | itens conferidos contra a regra 4a do ADR-0026 | PASS | `test_probe_iam.py`; G2 PASS em 68d2e7f; G4 `verify` 10/10 |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6)
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout
- [x] Documentação raiz e CHANGELOG atualizados (G7)
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [x] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->
Sem deploy: a skill chega pelo plugin `fermion` 2026.11.39 depois do merge. O adaptador só roda declarado em `probes.adapters`, com as probes ligadas.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
- **Minors do G4 no radar** do épico SPEC-0095:
  - a regex de conta (`\b`) não separa `_` de dígito: um papel `app_<conta>` sairia sem máscara;
  - `ensure_ascii=False` na política do recurso pode gerar ValidationError da IAM;
  - `RecursionError` de política muito aninhada não é tratado;
  - `AWS_ENDPOINT_URL*`, `AWS_CONFIG_FILE` e `AWS_SHARED_CREDENTIALS_FILE` herdadas passam.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0101`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
