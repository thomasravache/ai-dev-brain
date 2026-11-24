---
id: ADR-0025
title: "Probes de dependências: alvo do grafo, acesso local à nuvem e ao banco e contrato probe@2"
status: accepted
origin: decision
date: 2026-11-24
pillars: []
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: testes da SPEC-0096 (alvo, acesso e máscara) e dos adaptadores SPEC-0098 a SPEC-0101, SPEC-0103 (`suite`) e SPEC-0106 (`github-actions`, `argocd`), que só usam verbos de leitura e nunca shell
---

# ADR-0025 — Probes de dependências: alvo do grafo, acesso local à nuvem e ao banco e contrato probe@2

## Contexto e Problema
As probes (ADR-0023) só miram um deployment num cluster, e a verificação (ADR-0024) só olha o workload e os logs dele. A rotina real de verificação da SPEC-0075 também olha as dependências:
- a migration no banco;
- a fila e a DLQ;
- as assinaturas do tópico;
- a permissão do workload no recurso;
- os sinais de cada recurso.

O atlas já mapeia esses recursos (`datastore`, `queue`, `topic`, `bucket`) e as relações com os serviços. Falta definir três coisas, mantendo todas as proteções das probes:
- como uma probe mira um recurso;
- como esta máquina chega à nuvem e ao banco, sem credencial no atlas nem na saída;
- como o contrato do adaptador muda.

## Direcionadores da Decisão
- **Só leitura e menor privilégio** (ADR-0023).
- **Credencial só por nome ou referência** (ADR-0010), e o acesso local nunca impresso (SPEC-0087).
- **Alvo vindo do grafo, nunca texto livre:** nenhum adaptador recebe um recurso que o atlas não liga ao serviço no ambiente.
- **A regra de produção vale também para o recurso:** um recurso de produção não pode ser lido como se fosse de teste.
- **Compatibilidade:** o adaptador Kubernetes (`probe@1`) continua funcionando sem mudança.

## Opções Consideradas
- **Alvo de recurso pelo grafo + `probe@2` + acesso local por ambiente e por banco.**
- **Adaptador recebe só o serviço e o ambiente** e descobre os recursos sozinho.
- **Comandos de verificação por recurso guardados no atlas.**

## Resultado da Decisão
**Opção escolhida:** "alvo de recurso pelo grafo + `probe@2` + acesso local". É a única que mantém o alvo validado pelo núcleo e a regra de produção. Também é a única que mantém o atlas como dado, nunca como comando. Na segunda opção, cada adaptador refaria a descoberta e poderia sair do escopo. A terceira poria instrução no atlas, contra a SPEC-0075.

Regras:
1. **Alvo.** `atlas.py probe <capacidade> <verbo> --service <id> --env <ambiente> --resource <kind:id>` mira um `datastore`, `queue`, `topic` ou `bucket` do `graph.json`. O recurso precisa estar **ligado ao deployment do serviço naquele ambiente** por um destes caminhos:
   - uma aresta do deployment para o recurso (`depends_on`, `reads`, `writes`, `publishes` ou `consumes`);
   - uma referência do `config_refs` do deployment que o `build` resolve para o recurso (as mesmas regras de `references/graph.md`);
   - a DLQ (atributo `dlq`) de uma fila ligada por um dos dois caminhos acima.

   Fora disso → exit 2 `recurso <kind:id> não ligado a <serviço> em <ambiente>`. Uma aresta só do serviço, sem o ambiente, não basta: um recurso de produção não pode passar por recurso de teste.
2. **Ambiente e produção.** O recurso herda o ambiente do deployment que o liga. A regra de produção do ADR-0023 vale igual: `tier` diferente de `test`, ou sem `tier`, exige `--confirm-production`.
3. **Acesso local** (camada local, nunca no `atlas-config.yml`):
   ```yaml
   access:
     clusters:  {...}                                   # SPEC-0087
     cloud:     {<ambiente>: {profile: <nome do profile da CLI da nuvem>}}
     databases: {<id do datastore>: {user: <usuário só leitura>, database: <nome>, passfile: <caminho do arquivo de senhas>}}
   ```
   A região vem do atributo `region` do recurso. A senha nunca está na configuração: só o caminho do arquivo de senhas no formato da ferramenta (`.pgpass`), que o adaptador recebe pela variável da própria ferramenta (`PGPASSFILE`). `config`, `context`, `doctor`, `probe`, `verify` e o `probes.log` mostram só `definido` ou `não definido`.
4. **Contrato `probe@2`.**
   - O `--describe` declara, por capacidade, os verbos, os tipos de alvo e o acesso de que precisa:
     ```json
     {"contract": "probe@2", "adapter": "aws-messaging", "capabilities": {"messaging": {"verbs": ["queue", "subscriptions"], "targets": ["queue", "topic"], "access": ["cloud"]}}}
     ```
     `targets` aceita `deployment` e os kinds de recurso; `access` aceita `cluster`, `cloud`, `database` e `urls`. Sem o acesso local pedido → exit 4 `sem acesso local: <tipo>`, sem citar o valor.
   - A entrada leva o `target.resource` (`kind`, `id` e os `attrs` escalares do nó) e só os blocos de acesso declarados:
     - `target.cloud.profile`;
     - `target.database` (`user`, `name`, `passfile`);
     - o contexto do cluster, como no `probe@1`.
   - A saída é a do `probe@1`, com `contract: probe@2`.
   - **Mudança como alvo.** Uma capacidade pode declarar `inputs: ["change"]`. Nesse caso:
     - `atlas.py probe … --commit <sha>` chega ao adaptador como `target.change` (`commit` e os repositórios do serviço no atlas);
     - sem `--commit`, sai com 2;
     - o acompanhamento da entrega de um commit usa isso (SPEC-0106).
   - **Jornadas como entrada.** Uma capacidade pode declarar `inputs: ["journeys"]`. Ela recebe `target.journeys`, as jornadas curadas do serviço no atlas (ADR-0026).
   - **URL base do ambiente.** Um tipo de acesso `urls` permite configurar `access.urls.<ambiente>: {base_url: <url>}` na camada local. Ele chega ao adaptador como `target.urls.base_url`, só quando o adaptador declara `urls` em `access`.
   - **Repositórios da mudança.** Em `target.change.repositories` vão só os repositórios de código do serviço (`delivery.code_repositories`, SPEC-0086). O commit é normalizado para minúsculas antes da validação.
   - **Campos do cluster.** Os campos de cluster do alvo (`clusters`, `context`, `namespace`, `workloads`) só vão para o adaptador que declara `cluster` em `access`.
   - **Recursos ligados.** A lista dos recursos ligados a um deployment, com a relação de cada um, sai de uma função única do núcleo, a mesma do `--resource` e do `verify@2`.
   - **Atributos no atlas.**
     - `dlq` é um texto com o id de outra fila.
     - Nenhum atributo de recurso no atlas leva id de conta: nada de ARN nem URL com conta. O adaptador que precisa de ARN ou URL monta pela própria CLI, com operações de leitura (`get-queue-url`, `get-caller-identity`).
     - A região segue `^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$`.
   - `access` pode ser uma lista vazia, quando o adaptador só usa credenciais por nome (por exemplo, o token da CI em `probes.adapters.<id>.credentials`).
   - O núcleo continua aceitando um adaptador `probe@1`. Ele só recebe alvo de deployment e a entrada `probe@1` de sempre.
5. **Máscara.** A máscara literal do ADR-0023 ganha o profile, o usuário, o nome do banco e o caminho do arquivo de senhas. Os ids de conta de nuvem (12 dígitos dentro de ARNs e URLs de fila) saem como `[REDACTED]`.
6. **Registro.** O `probes.log` ganha quatro chaves: `resource` (`kind:id`, que vem do atlas), `commit`, `reason` (código fechado da recusa) e `access` (o tipo de acesso que faltou, nunca o valor). Continua sem o resultado da probe e sem nenhum valor de acesso.
7. **Adaptadores.** Cada um monta a chamada só dos campos do alvo, como lista de argumentos e sem shell. Só usa as operações de leitura listadas na própria spec, e qualquer outra é recusada por teste.

### Consequências
- **Boa:** banco, fila, tópico, sinais e permissão entram como adaptadores, com as mesmas proteções e sem mudar o núcleo de novo.
- **Boa:** o recurso de produção fica protegido pela ligação com o deployment do ambiente.
- **Ruim:** um recurso usado por um serviço sem deployment mapeado naquele ambiente não pode ser consultado. É preciso completar o mapa, e o onboarding da SPEC-0104 ajuda.
- **Ruim:** a skill não sabe se o profile e o usuário são mesmo só de leitura. O adaptador de banco força a sessão só de leitura; os de nuvem dependem do papel, que o onboarding e o `doctor` recomendam.

### Confirmação (G3)
Os testes da SPEC-0096 falham:
- se um recurso não ligado ao deployment do ambiente chegar ao adaptador;
- se o profile, o usuário ou o caminho do arquivo de senhas aparecer em qualquer saída ou no `probes.log`;
- se um adaptador `probe@1` receber alvo de recurso.

Os testes dos adaptadores (SPEC-0098 a SPEC-0101, SPEC-0103 e SPEC-0106) falham se houver chamada fora da lista de leitura ou uso de shell.

## Prós e Contras das Opções
| Critério (peso) | Alvo pelo grafo + probe@2 | Adaptador descobre | Comandos no atlas |
|---|---|---|---|
| Alvo validado pelo núcleo (alto) | sim | não | sim |
| Produção protegida por ambiente (alto) | sim | depende do adaptador | depende do texto |
| Atlas como dado, não instrução (alto) | sim | sim | não |
| Compatível com `probe@1` (médio) | sim | sim | sim |
| Esforço (baixo) | médio | baixo | baixo |

## Mais Informações
- SPEC-0075 (rotina real e garantias transversais), SPEC-0087 (acesso local por cluster), SPEC-0088 (núcleo do probe), ADR-0023.
- PostgreSQL `default_transaction_read_only` e o arquivo `.pgpass`: documentação oficial do PostgreSQL ("Client Connection Defaults" e "The Password File"), consultada de memória, sem verificação nesta data; o adaptador (SPEC-0099) confirma com a versão instalada.
