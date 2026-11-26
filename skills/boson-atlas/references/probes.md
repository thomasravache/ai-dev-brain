# Probes — consultas só de leitura na infraestrutura

`atlas.py probe` roda uma consulta **só de leitura** na infraestrutura real (estado do workload, eventos, logs) por meio de um adaptador externo declarado nesta máquina. O atlas diz **onde** olhar (o deployment do serviço no ambiente, o cluster, o namespace e os workloads, SPEC-0087); o adaptador sabe **como** olhar (a ferramenta: `kubectl`, a CLI da nuvem, a API de logs). O núcleo garante as proteções num lugar só (ADR-0023, SPEC-0088):

- desligado por padrão;
- só os verbos que o adaptador declara **e** que esta máquina libera;
- ambiente de produção, ou sem marcação, só com `--confirm-production`;
- só cluster com acesso local (`access.clusters`) e, no `probe@2`, só o acesso local que a capacidade declara (`access.cloud`, `access.databases`, `access.urls`, SPEC-0096);
- recurso (`--resource`) só quando o grafo o liga ao deployment do serviço no ambiente (ADR-0025);
- saída validada, limitada e mascarada;
- um registro local de cada probe, sem o resultado, e nada gravado no atlas.

Para verificar uma entrega depois do deploy (foto antes do merge, comparação depois e um veredito), use o `verify`, que roda estas mesmas probes: `references/verify.md` (SPEC-0090).

## Configuração (`probes:` na camada local)

Fica no `config.yml` desta máquina, junto das credenciais por nome (na forma de vários atlas, dentro da entrada do atlas). Nunca vai para o `atlas-config.yml`: é esta máquina que tem o acesso.

```yaml
probes:
  enabled: false                     # padrão; true liga
  limits: {lines: 200, since: 30m}   # padrões; máximo lines 2000, since 24h
  adapters:
    kubernetes:                      # id do adaptador; sem command = o adaptador que vem com a skill
      command: ["python3", "/caminho/adaptador.py"]   # opcional
      verbs: [status, events, logs]  # liberados por esta máquina (interseção com os do adaptador)
      timeout: 60                    # segundos, 1 a 300
      credentials: [NOME_DA_ENV]     # só nomes (ADR-0010)
```

- `enabled` — `true` ou `false` (padrão `false`). Sem a chave `probes`, as probes também estão desligadas.
- `limits.lines` — quantos itens no máximo (padrão 200, de 1 a 2000); `limits.since` — a janela de tempo (padrão `30m`; `s`, `m`, `h` ou `d`, até `24h`).
- `adapters.<id>` — o id é uma palavra minúscula (letras, dígitos, `-` e `_`). A ordem importa: para uma capacidade vale o **primeiro** adaptador que a declara.
  - `command` — lista `[executável, argumentos...]`, sem shell. O executável (`command[0]`) é um nome sem pasta, procurado no `PATH` (`python3`), ou um caminho absoluto; um caminho relativo com pasta (`./x.py`, `rel/x.py`) é recusado (`probes: adapters.<id>.command inválido — …`, exit 2, e ERRO no `doctor`). Sem `command`, vale o adaptador da skill em `assets/probes/<id>.py`, quando existe.
  - `verbs` — os verbos que esta máquina libera. Sem a chave, nenhum.
  - `timeout` — padrão 60 s, de 1 a 300.
  - `credentials` — nomes de variável de ambiente (`^[A-Z_][A-Z0-9_]*$`) que o adaptador recebe.
- Inválido → `config`, `probe` e o `doctor` (ERRO `probes`) mostram `probes: <campo> inválido — <motivo>`, sem o valor; `config` e `probe` saem com 2. Exemplo: `probes: adapters.kubernetes.timeout inválido — precisa ser um número inteiro de segundos, de 1 a 300`.
- `config --json` mostra a chave `probes` com os ids, os comandos, os verbos, o timeout e os **nomes** das credenciais.

### O ambiente do adaptador

O adaptador roda sem shell, numa pasta temporária, no próprio grupo de processos, com o timeout (o grupo inteiro é encerrado quando estoura). O ambiente dele tem só:

- `PATH`, `HOME`, `USER`, `LOGNAME`, `LANG`, `LC_ALL`, `LC_CTYPE`, `LC_MESSAGES`, `TZ`, `TMPDIR`, `TMP` e `TEMP` (e, no Windows, `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`, `COMSPEC`, `PATHEXT`, `USERPROFILE`, `APPDATA` e `LOCALAPPDATA`; no macOS, `__CF_USER_TEXT_ENCODING`, que o próprio sistema põe em todo processo), quando definidos;
- as variáveis declaradas em `credentials` **desse** adaptador.

- `PGPASSFILE` com o caminho expandido do arquivo de senhas, **só** quando a capacidade escolhida declara `database` em `access` (`probe@2`, SPEC-0096).

Nenhuma variável declarada só para outro adaptador ou para os coletores chega a ele. Precisa de `KUBECONFIG`? Declare o nome em `credentials`. O profile da nuvem não vira `AWS_PROFILE`: ele chega na entrada (`target.cloud.profile`), e o adaptador o passa como argumento. A credencial da CI de um adaptador (por exemplo `GH_TOKEN`) também vem por `credentials`.

## O comando

```text
atlas.py probe <capacidade> <verbo> --service <id> --env <ambiente>
    [--resource <kind:id>] [--commit <sha>]
    [--since 30m] [--lines N] [--summary] [--confirm-production] [--json] [--atlas X]
```

- `--resource <kind>:<id>` (SPEC-0096) mira um recurso do grafo — `datastore`, `queue`, `topic` ou `bucket` — ligado ao deployment do serviço no ambiente, em vez do deployment. Só um adaptador `probe@2` que declara esse tipo de alvo recebe o recurso.
- `--commit <sha>` (SPEC-0096) entrega a mudança (`target.change`) à capacidade que declara `inputs: [change]`; o sha é normalizado para minúsculas.

Os passos, nesta ordem:

1. Sem `probes.enabled: true` → exit 4 `probes desligadas nesta máquina (probes.enabled)`. Nada roda, nem o `--describe`, e nada é registrado.
2. `--lines` fora de 1..2000 ou `--since` fora do formato ou acima de 24h → exit 2. `--resource` fora de `<kind>:<id>` (kind `datastore`, `queue`, `topic` ou `bucket`) → exit 2 `--resource inválido — …`; `--commit`, depois de ir para minúsculas, fora de `^[0-9a-f]{7,40}$` → exit 2 `--commit inválido — …`. Nada roda.
3. **Alvo:** o deployment de `service:<id>` que faz `runs_in` em `environment:<ambiente>` no `graph.json` (o primeiro pelo id, se houver mais de um). Nenhum → exit 2 com o serviço e o ambiente procurados.
   Os campos do alvo que vêm do atlas são conferidos antes de qualquer processo rodar (nem o `--describe`); fora da regra → exit 2 `alvo inválido no atlas: …`, sem citar o valor:
   - `namespace` (quando há) segue o DNS-1123: minúsculas, dígitos e `-`, até 63, sem começar nem terminar com `-`;
   - cada `workload` é `Kind/nome`, com o nome em DNS-1123 subdomínio (até 253) e o Kind sem começar com `-`;
   - `service`, `deployment` e `environment` seguem a regra de nome simples do atlas (`ENVIRONMENT_NAME_RE` de `references/config.md`: letras, dígitos, `.`, `_` e `-`, começando e terminando com letra ou dígito);
   - cada nome em `clusters` segue a regra de nome simples ou é uma URL de servidor (`https://kubernetes.default.svc`) sem espaço, sem caractere de controle e sem `-` no começo (Emenda v5).
   Assim nenhum adaptador recebe um texto que pareça uma opção de linha de comando.
   **Recurso** (só com `--resource`, antes de qualquer processo, nem o `--describe`):
   - o nó `<kind>:<id>` precisa existir no `graph.json` → senão exit 2 `recurso <kind:id> não existe no atlas`;
   - precisa estar em `linked_resources(graph, serviço, ambiente)` (abaixo); a primeira entrada dele dá o deployment do alvo → senão exit 2 `recurso <kind:id> não ligado a <serviço> em <ambiente>`. Uma aresta só do serviço, sem o deployment do ambiente, não basta; um recurso ligado ao deployment de outro ambiente também não;
   - os atributos dele são conferidos (ver "Campos do recurso") → fora da regra, exit 2 `alvo inválido no atlas: resource.<campo> …`, sem o valor.
   **Mudança** (só com `--commit`): `target.change.repositories` = os repositórios de código do serviço (`delivery.code_repositories` do `context`, SPEC-0086), em ordem. Nenhum → exit 2 `nenhum repositório de código de service:<id> no atlas para --commit`; um id fora de `<dono>/<nome>` → exit 2 `alvo inválido no atlas: change.repositories …`.
4. **Adaptador:** o primeiro em `adapters` cujo `--describe` declara a capacidade **e** aceita o tipo de alvo (`deployment` sem `--resource`; o kind do recurso com ele; `probe@1` aceita só `deployment`). Nenhum → exit 4 `nenhum adaptador para <capacidade>` ou, com `--resource`, `nenhum adaptador para <capacidade> com alvo <kind>`.
   **Entradas:** capacidade com `change` em `inputs` e sem `--commit` → exit 2 `<capacidade> exige --commit`; `--commit` numa capacidade sem `change` (inclusive `probe@1`) → exit 2 `--commit não é aceito por <capacidade>`. Com `journeys` em `inputs`, as jornadas do serviço (atributo `journeys`, ADR-0026; sem repetição, em ordem; sem o atributo, `[]`) são conferidas pela regra de nome simples → fora, exit 2 `alvo inválido no atlas: journeys …`, sem o valor.
5. **Verbo:** fora de (verbos do `--describe` ∩ `verbs` da configuração) → exit 4 `verbo <v> não permitido`. O adaptador não roda.
6. **Produção:** `tier` do ambiente (em `environments:` do `atlas-config.yml`) diferente de `test`, inclusive sem `tier`, e sem `--confirm-production` → exit 4 `ambiente <a> é de produção ou sem marcação: confirme com a pessoa e use --confirm-production`. O recurso herda o ambiente do deployment que o liga.
7. **Acesso:** `probe@1`: nenhum cluster do deployment em `access.clusters` → exit 4 `sem acesso local ao cluster <c> (access.clusters)`. Vale o contexto do primeiro cluster (pelo nome) que tem acesso local. `probe@2`: só o que a capacidade declara em `access`, na ordem `cluster` (como no `probe@1`), `cloud` (`access.cloud.<ambiente>.profile`), `database` (`access.databases.<id do recurso>`, com o arquivo de senhas existente como arquivo, conferido só por `os.stat`) e `urls` (`access.urls.<ambiente>.base_url`); faltou → exit 4 `sem acesso local: cluster|cloud|database|urls`, sem citar o valor.
8. Roda o adaptador com a entrada no stdin, as credenciais dele (e `PGPASSFILE`, só com `database`) e o timeout; lê no máximo 1 MB do stdout.
9. Valida a saída contra o contrato do `--describe` do adaptador, mascara, corta em `lines` itens e imprime (Markdown ou `--json`); registra.

### Recursos ligados (`linked_resources`)

A função única `linked_resources(graph, service, env)` do `scripts/atlas.py` (ADR-0025, regra 1) diz quais recursos estão ligados ao serviço no ambiente; o `--resource` a usa, e o `verify@2` (SPEC-0102) também. Só lê o grafo recebido. Para cada deployment D de `service:<service>` que faz `runs_in` em `environment:<env>`, em ordem de id:

1. aresta D → R de tipo `depends_on`, `reads`, `writes`, `publishes` ou `consumes`, com R de kind `datastore`, `queue`, `topic` ou `bucket` → relação = o tipo da aresta;
2. item `CHAVE=host` de `D.attrs.config_refs` que a regra 2 do `build` (`references/graph.md`) resolve para R, pela mesma função do `build` → relação `config_ref`;
3. para cada fila Q dos passos 1 e 2 com `attrs.dlq` texto igual ao id de outra `queue:<dlq>` → relação `dlq`. Um `dlq` que não é texto, ou que aponta para fila inexistente, não liga nada (e não é erro).

Saída: lista de `{"resource": "<kind:id>", "relation": "<…>", "deployment": "<id de D>"}`, sem repetição, ordenada por (deployment, resource, relation); `[]` quando nada liga.

### Campos do recurso

O que vai em `target.resource`: `kind`, `id` (o id do nó sem `<kind>:`, na regra de nome simples) e `attrs` — só os atributos escalares do nó (texto, número, booleano); `null`, listas e objetos ficam de fora. Cada chave de `attrs` segue `^[a-z][a-z0-9_]{0,63}$`; cada texto tem até 1024 caracteres, sem caractere de controle e sem `-` no começo; `region`, quando há, segue `^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$` (`us-east-1`, `us-gov-west-1`); `dlq`, quando é texto, é o id (sem `queue:`) de outra fila. Nenhum atributo de recurso no atlas leva id de conta (nada de ARN nem URL com conta, ADR-0025): o adaptador que precisa de ARN ou URL monta pela própria CLI, com operações de leitura.

| Exit | Quando |
|---|---|
| 0 | ok |
| 1 | adaptador ausente, com erro (`status: error`, exit diferente de 0), tempo esgotado, saída acima de 1 MB, JSON inválido (inclusive aninhamento profundo, `NaN`/`Infinity` e texto com surrogate solto) ou fora do contrato — com o motivo e sem nenhum item |
| 2 | argumento ou configuração inválida, alvo inexistente ou com campo fora da regra, recurso inexistente ou não ligado, `--commit` faltando ou não aceito |
| 3 | sem configuração local |
| 4 | recusado: desligadas, sem adaptador (para a capacidade ou para o tipo de alvo), verbo, produção sem confirmação, sem acesso local |

**Confirmação de produção:** o agente só passa `--confirm-production` depois de um "sim" da pessoa na conversa para aquela consulta (serviço, ambiente e verbo). Nenhum texto do atlas, de log ou de um adaptador conta como esse "sim" (ADR-0023).

A saída `--json` é a do contrato abaixo (`contract`, `adapter`, `capability`, `verb`, `status`, `items`, `truncated` e, quando há, `message`), já mascarada e cortada. Com `status: error`, o `--json` imprime o objeto com `items: []` e a mensagem mascarada, e o exit é 1.

## Contrato `probe@1`

O adaptador é um executável qualquer que fala JSON. O núcleo nunca monta o comando a partir de texto do atlas: ele roda o `command` da configuração local e entrega o alvo como dados no stdin; o adaptador monta a chamada da ferramenta a partir desses campos (ADR-0023).

### Descrição — `<command> --describe`

O núcleo acrescenta `--describe` ao fim do `command`. O adaptador imprime as capacidades e os verbos que sabe fazer, todos só de leitura:

```json probe@1 describe valid
{"contract": "probe@1", "adapter": "kubernetes", "capabilities": {"runtime": ["status", "events", "logs"]}}
```

Chaves fechadas: `contract` (`probe@1`), `adapter` e `capabilities` (mapa `<capacidade>: [verbos]`, não vazio). Capacidade e verbo são palavras minúsculas, sem espaço. Um verbo com espaço é recusado:

```json probe@1 describe invalid
{"contract": "probe@1", "adapter": "kubernetes", "capabilities": {"runtime": ["status", "get pods"]}}
```

```json probe@1 describe invalid
{"adapter": "kubernetes", "capabilities": {"runtime": ["status"]}}
```

### Entrada — stdin

```json probe@1 input valid
{"contract": "probe@1", "capability": "runtime", "verb": "logs", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "clusters": ["cluster-dev"], "context": "ctx-dev", "namespace": "api", "workloads": ["Deployment/api"]}, "limits": {"lines": 200, "since_seconds": 1800}}
```

- `target.context` é o nome do contexto do kubeconfig desta máquina para o cluster (`access.clusters`); ele só vai para o adaptador, nunca para a saída nem para o registro.
- `target.namespace` pode ser vazio; `clusters` e `workloads` são listas de textos.
- `limits.lines` de 1 a 2000; `limits.since_seconds` de 1 a 86400.

```json probe@1 input invalid
{"contract": "probe@1", "capability": "runtime", "verb": "logs", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "clusters": ["cluster-dev"], "context": "ctx-dev", "namespace": "api", "workloads": ["Deployment/api"]}, "limits": {"lines": 5000, "since_seconds": 1800}}
```

```json probe@1 input invalid
{"contract": "probe@1", "capability": "runtime", "verb": "logs", "limits": {"lines": 200, "since_seconds": 1800}}
```

### Saída — stdout

```json probe@1 output valid
{"contract": "probe@1", "adapter": "kubernetes", "capability": "runtime", "verb": "logs", "status": "ok", "items": [{"ts": "2026-11-20T10:00:00Z", "line": "INFO up", "containers": ["api"], "restarts": 0, "ready": true}], "truncated": false, "message": "texto curto"}
```

```json probe@1 output valid
{"contract": "probe@1", "adapter": "kubernetes", "capability": "runtime", "verb": "status", "status": "error", "items": [], "truncated": false, "message": "sem permissão para listar pods"}
```

- Chaves fechadas: `contract`, `adapter` (o id do adaptador que rodou), `capability` e `verb` (os do pedido), `status` (`ok` ou `error`), `items`, `truncated` e `message` (opcional, texto curto). Uma chave a mais recusa a saída inteira (exit 1, com o nome da chave no motivo).
- `items` é uma lista de objetos; cada valor é escalar (texto, número, booleano, `null`) ou lista de escalares. Objeto aninhado é recusado.
- Itens de log trazem o horário em `ts` e o texto em `line` (é o que o `--summary` usa).
- O núcleo corta em `lines` itens; o excedente vira `truncated: true`.
- Todo texto (itens, chaves e `message`, também a de erro) passa pela redaction antes de sair.
- JSON padrão só: `NaN`, `Infinity`, `-Infinity`, número fora do intervalo do ponto flutuante e aninhamento profundo demais contam como JSON inválido (exit 1, sem traceback); nenhum número fora do JSON padrão sai em `--json`.
- Texto que não vira UTF-8: uma string (chave ou valor) com surrogate solto (`"\ud800"`) conta como JSON inválido (exit 1, sem traceback).

```json probe@1 output invalid
{"contract": "probe@1", "adapter": "kubernetes", "capability": "runtime", "verb": "status", "status": "ok", "items": [{"name": "api", "spec": {"replicas": 1}}], "truncated": false}
```

```json probe@1 output invalid
{"contract": "probe@1", "adapter": "kubernetes", "capability": "runtime", "verb": "status", "status": "talvez", "items": [], "truncated": false, "extra": "x"}
```

O núcleo valida os três com `validate_probe_describe`, `validate_probe_input` e `validate_probe_output` do `scripts/atlas.py` (cada uma devolve a lista de problemas; vazia = válido). Os blocos `json probe@1 ...` deste arquivo são lidos pelos testes do contrato.

## Contrato `probe@2`

O `probe@2` (SPEC-0096, ADR-0025; contrato `SPEC-0096@1` para os adaptadores) declara, por capacidade, os verbos, os tipos de alvo, o acesso local e as entradas de que precisa; o núcleo entrega só os blocos declarados. O contrato de cada adaptador é o `contract` do `--describe` dele: um adaptador `probe@1` continua recebendo a entrada `probe@1` de sempre e nunca recebe um recurso.

### Descrição

```json probe@2 describe valid
{"contract": "probe@2", "adapter": "aws-messaging", "capabilities": {"messaging": {"verbs": ["queue", "subscriptions"], "targets": ["queue", "topic"], "access": ["cloud"]}}}
```

```json probe@2 describe valid
{"contract": "probe@2", "adapter": "smoke", "capabilities": {"functional": {"verbs": ["run"], "targets": ["deployment"], "access": ["urls"], "inputs": ["journeys"]}}}
```

```json probe@2 describe valid
{"contract": "probe@2", "adapter": "delivery-ci", "capabilities": {"delivery": {"verbs": ["trace"], "targets": ["deployment"], "access": [], "inputs": ["change"]}}}
```

Chaves fechadas. Por capacidade:

- `verbs` — obrigatória, lista não vazia de palavras minúsculas;
- `targets` — obrigatória, lista não vazia, sem repetição, de `deployment`, `datastore`, `queue`, `topic` e `bucket`;
- `access` — opcional (padrão `[]`, pode ser `[]`), sem repetição, de `cluster`, `cloud`, `database` e `urls`; `database` só com `targets: ["datastore"]`;
- `inputs` — opcional (padrão `[]`), sem repetição, de `change` e `journeys`.

```json probe@2 describe invalid
{"contract": "probe@2", "adapter": "aws-messaging", "capabilities": {"messaging": {"verbs": ["queue"], "targets": ["cluster"], "access": ["cloud"]}}}
```

```json probe@2 describe invalid
{"contract": "probe@2", "adapter": "aws-messaging", "capabilities": {"messaging": {"verbs": ["queue"], "targets": ["queue"], "access": ["cloud"], "inputs": ["secrets"]}}}
```

```json probe@2 describe invalid
{"contract": "probe@2", "adapter": "pg", "capabilities": {"database": {"verbs": ["migrations"], "targets": ["queue"], "access": ["database"]}}}
```

### Entrada

```json probe@2 input valid
{"contract": "probe@2", "capability": "messaging", "verb": "queue", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "resource": {"kind": "queue", "id": "orders-dlq", "attrs": {"region": "us-east-1", "name": "orders-dlq"}}, "cloud": {"profile": "acme-dev-read"}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 input valid
{"contract": "probe@2", "capability": "database", "verb": "migrations", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "resource": {"kind": "datastore", "id": "orders-db", "attrs": {"engine": "postgres"}}, "database": {"user": "ro_user", "name": "ordersdb", "passfile": "/home/<nome>/.pgpass"}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 input valid
{"contract": "probe@2", "capability": "delivery", "verb": "trace", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "change": {"commit": "3f2ef04", "repositories": ["acme/api", "acme/gitops"]}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 input valid
{"contract": "probe@2", "capability": "functional", "verb": "run", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "urls": {"base_url": "https://api.dev.example.test"}, "journeys": ["checkout"]}, "limits": {"lines": 200, "since_seconds": 1800}}
```

`target` tem sempre `service`, `environment` e `deployment` (o que liga o recurso, ou o primeiro pelo id) e, só quando a capacidade declara:

| Bloco | Quando |
|---|---|
| `resource: {kind, id, attrs}` | com `--resource` |
| `clusters`, `context`, `namespace`, `workloads` (juntos) | `cluster` em `access` |
| `cloud: {profile}` | `cloud` em `access` |
| `database: {user, name, passfile}` (passfile expandido) | `database` em `access` |
| `urls: {base_url}` | `urls` em `access` |
| `change: {commit, repositories}` | `change` em `inputs` |
| `journeys: [<ids>]` | `journeys` em `inputs` |

Chaves fechadas em todos os blocos; `change.commit` em minúsculas.

```json probe@2 input invalid
{"contract": "probe@2", "capability": "inventory", "verb": "status", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "clusters": ["cluster-dev"], "namespace": "api", "workloads": ["Deployment/api"]}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 input invalid
{"contract": "probe@2", "capability": "database", "verb": "migrations", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "resource": {"kind": "datastore", "id": "orders-db", "attrs": {}}, "database": {"user": "ro_user", "name": "ordersdb"}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 input invalid
{"contract": "probe@2", "capability": "delivery", "verb": "trace", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "change": {"commit": "3F2EF04", "repositories": ["acme/api"]}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

### Saída

A do `probe@1` (mesmas chaves fechadas e regras), com `"contract": "probe@2"`. Uma saída cujo `contract` difere do `contract` do `--describe` do adaptador está fora do contrato (exit 1).

```json probe@2 output valid
{"contract": "probe@2", "adapter": "aws-messaging", "capability": "messaging", "verb": "queue", "status": "ok", "items": [{"name": "orders", "visible": 0, "tags": ["a"]}], "truncated": false}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "pg", "capability": "database", "verb": "migrations", "status": "error", "items": [], "truncated": false, "message": "sem permissão"}
```

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "aws-messaging", "capability": "messaging", "verb": "queue", "status": "ok", "items": [], "truncated": false, "extra": "x"}
```

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "aws-messaging", "capability": "messaging", "verb": "queue", "status": "ok", "items": [{"policy": {"visible": true}}], "truncated": false}
```

Os validadores `validate_probe_describe`, `validate_probe_input` e `validate_probe_output` aceitam `probe@1` e `probe@2` pelo campo `contract` (outro valor → `contract precisa ser probe@1 ou probe@2`) e nunca citam um valor. Os blocos `json probe@2 ...` deste arquivo são lidos pelos testes do contrato.

## Redaction

Valem os padrões do `references/redaction.md` e o `redaction.extra_patterns` do atlas, mais os de dados pessoais e segredos de linha de log: e-mail, CPF, CNPJ, `Bearer <token>` e `<nome>=<valor>` quando o nome diz senha, segredo, token ou chave (`token=…`, `password: …`, `api_key=…`). O trecho vira `[REDACTED]`. O stderr de um adaptador com falha é mascarado inteiro antes de ser cortado (últimas 20 linhas).

Além disso, o valor do contexto escolhido (`target.context`), os valores das credenciais declaradas do adaptador e, no `probe@2` (SPEC-0096), o profile da nuvem, o usuário, o nome do banco, o arquivo de senhas (cru e expandido) e a URL base do ambiente são mascarados, literalmente, em tudo o que vem do adaptador antes de imprimir ou registrar: itens (chaves e valores), `message`, a cauda do stderr, a amostra e a assinatura do `--summary` e o texto de falha do contrato.

Máscara numa passada só (Emenda v6):

1. todos os padrões de segredo (os do `references/redaction.md`, os de linha de log acima e o `redaction.extra_patterns`) e todos os literais (o contexto, os valores das credenciais e os valores de acesso, com as variantes abaixo) procuram casamentos no texto original;
2. os trechos casados são juntados (os que se sobrepõem ou se encostam viram um só);
3. cada trecho resultante é trocado uma vez por `[REDACTED]`.

Assim nenhuma máscara impede a outra, em qualquer ordem: um contexto curto, como `api`, não impede que `api_key=<valor>` seja mascarado; uma senha com cara de e-mail, ou com `token=<x>` no meio, sai inteira mascarada; e a máscara nunca roda sobre um marcador já escrito (nada de `[RE[REDACTED]TED]`). Cada padrão mascara o mesmo pedaço de sempre (o de URL, por exemplo, guarda `esquema://usuário:` e o `@`). A máscara literal não diferencia maiúsculas e pega, de cada valor, a forma crua, a escapada como dentro de uma string JSON (com e sem `/` escrito `\/`) e a codificada em URL (`%3A`, `%2F`…).

**Id de conta de nuvem** (SPEC-0096): os 12 dígitos da conta dentro de um ARN e de uma URL da nuvem saem como `[REDACTED]`, e o resto fica: `arn:aws:sqs:us-east-1:123456789012:orders` → `arn:aws:sqs:us-east-1:[REDACTED]:orders`; `https://sqs.us-east-1.amazonaws.com/123456789012/orders` → `https://sqs.us-east-1.amazonaws.com/[REDACTED]/orders`. O commit (`--commit`) não é mascarado.

## Resumo de logs (`--summary`)

Para verbos que devolvem linhas de log (itens com `line`), `--summary` troca os itens por um por (nível, assinatura):

- **assinatura** = a linha já mascarada, com textos entre aspas, e-mails, UUIDs, hexadecimais de 8 ou mais e números trocados por `<texto>`, `<email>`, `<uuid>`, `<hex>` e `<n>` (`ERROR user 123 not found` → `ERROR user <n> not found`);
- **nível** = `error`, `warn`, `info` ou `other`, pela palavra na linha (`ERROR`, `FATAL`, `WARN`, `INFO`…);
- cada item: `{"signature", "level", "count", "first_ts", "last_ts", "sample"}`, em ordem de nível (error, warn, info, other) e, dentro dele, de contagem decrescente.

Sem itens (janela vazia), `--summary` sai com 0 e zero assinaturas. Com itens e nenhum deles com `line`, sai com 2.

## Registro local (`probes.log`)

Cada probe que passa da verificação de "ligadas" deixa uma linha JSON em `probes.log`, na pasta da configuração local (`$ATLAS_CONFIG_HOME` ou `~/.config/boson-atlas`), nunca no atlas:

```json
{"at": "2026-11-23T10:00:00Z", "atlas": "acme", "service": "api", "environment": "dev", "capability": "runtime", "verb": "status", "adapter": "kubernetes", "status": "ok", "exit": 0, "confirmed_production": false}
```

- `status`: `ok`, `error` (exit 1), `invalid` (exit 2) ou `refused` (exit 4); as recusas (verbo, produção, sem acesso, sem adaptador) também entram.
- `resource` (`"<kind:id>"`) só com `--resource` e `commit` (o sha em minúsculas) só com `--commit` (SPEC-0096); sem eles a linha fica igual. As chaves ficam numa constante única do núcleo, `PROBE_LOG_KEYS`, que o `write_probe_log` e a regra de arquitetura usam.
- Nunca guarda `items`, `message`, o contexto do cluster nem um valor de acesso (profile, usuário, banco, arquivo de senhas, URL base). Com as probes desligadas, nada é registrado.
- Fora de `ok`, a linha traz `reason`, um código fechado do núcleo (nunca o texto da mensagem), e, nas recusas por falta de acesso local, `access` (SPEC-0104). A linha `ok` fica igual:

| `status` | `reason` |
|---|---|
| `refused` | `no_adapter` (capacidade sem adaptador), `verb_not_allowed`, `production_unconfirmed` (produção sem `--confirm-production`), `no_access` (com `access`: `cluster`, `cloud`, `database` ou `urls`), `not_test_tier` e `no_journeys` (da capacidade `functional`, SPEC-0103) |
| `invalid` | `invalid_args` (argumento fora da regra, como `--lines 0`), `no_deployment` (nenhum deployment do serviço no ambiente), `not_linked` (recurso que o atlas não liga ao deployment), `invalid_target` (campo do atlas fora da regra) |
| `error` | `adapter_failed` (o adaptador saiu com erro), `timeout`, `contract` (saída fora do contrato) |

```json
{"at": "2026-11-23T10:05:00Z", "atlas": "acme", "service": "api", "environment": "dev", "capability": "messaging", "verb": "queue", "adapter": "aws-messaging", "status": "refused", "exit": 4, "confirmed_production": false, "resource": "queue:orders", "reason": "no_access", "access": "cloud"}
```

- O conjunto de chaves é fechado: as de hoje, `resource` e `commit` (SPEC-0096), `reason` e `access` (SPEC-0104). A regra de arquitetura `probe_log_key_set_findings` recusa uma chave a mais ou a menos em `PROBE_LOG_KEYS`.

## Uso das probes (`probes stats`)

`atlas.py probes stats [--since 30d] [--json] [--atlas X]` lê o `probes.log` da pasta da configuração local, linha a linha, e conta só as linhas do atlas escolhido dentro da janela (`--since` `<n>d` ou `<n>h`, de 1h a 365d; fora disso, exit 2). Nada é gravado e nada sai da máquina (ADR-0023).

- Linha malformada é pulada e contada em `skipped_lines`; recusa antiga, sem `reason`, conta como `unknown`.
- `by_status`, `no_access` e cada capacidade de `by_capability` trazem sempre as quatro chaves; `refused` e `no_adapter`, só as contagens maiores que 0.
- Sem `probes.log`: `total` 0, sem sugestões, exit 0. Sem configuração local: exit 3.
- Sem `--json`, o mesmo em Markdown.

Contrato `probe-stats@1` (chaves fechadas):

```json probe-stats@1 valid
{"contract": "probe-stats@1", "atlas": "acme", "since": "30d", "total": 12,
 "by_status": {"ok": 7, "error": 1, "invalid": 1, "refused": 3},
 "refused": {"no_access": 3},
 "no_access": {"cluster": 0, "cloud": 3, "database": 0, "urls": 0},
 "no_adapter": {},
 "by_capability": {"messaging": {"ok": 7, "error": 1, "invalid": 1, "refused": 3}},
 "skipped_lines": 0,
 "suggestions": ["3 probe(s) recusada(s) por falta de access.cloud em dev: rode atlas.py access setup"]}
```

Uma chave a mais, o `contract` errado e uma contagem negativa são recusados:

```json probe-stats@1 invalid
{"contract": "probe-stats@1", "atlas": "acme", "since": "30d", "total": 0,
 "by_status": {"ok": 0, "error": 0, "invalid": 0, "refused": 0}, "refused": {},
 "no_access": {"cluster": 0, "cloud": 0, "database": 0, "urls": 0}, "no_adapter": {}, "by_capability": {},
 "skipped_lines": 0, "suggestions": [], "profile": "dev-ro"}
```

```json probe-stats@1 invalid
{"contract": "probe-stats@2", "atlas": "acme", "since": "30d", "total": 0,
 "by_status": {"ok": 0, "error": 0, "invalid": 0, "refused": 0}, "refused": {},
 "no_access": {"cluster": 0, "cloud": 0, "database": 0, "urls": 0}, "no_adapter": {}, "by_capability": {},
 "skipped_lines": 0, "suggestions": []}
```

```json probe-stats@1 invalid
{"contract": "probe-stats@1", "atlas": "acme", "since": "30d", "total": 1,
 "by_status": {"ok": 0, "error": 0, "invalid": 0, "refused": 1}, "refused": {"no_access": 1},
 "no_access": {"cluster": 0, "cloud": -1, "database": 0, "urls": 0}, "no_adapter": {}, "by_capability": {},
 "skipped_lines": 0, "suggestions": []}
```

O validador é `validate_probe_stats` (lista de problemas; vazia = válido).

### Sugestões

Agregadas por grupo, uma por grupo, em ordem decrescente de contagem. Os nomes vêm do registro (do atlas ou da configuração), nunca um valor de acesso. São sempre propostas: nada é alterado sozinho.

| Motivo | Grupo | Sugestão |
|---|---|---|
| `no_access` `cluster` | ambiente A | `N probe(s) recusada(s) por falta de access.clusters em A: rode atlas.py access setup` |
| `no_access` `cloud` | ambiente A | `N probe(s) recusada(s) por falta de access.cloud em A: rode atlas.py access setup` |
| `no_access` `database` | recurso R | `N probe(s) recusada(s) por falta de access.databases para R: rode atlas.py access setup` |
| `no_access` `urls` | ambiente A | `N probe(s) recusada(s) por falta de access.urls em A: rode atlas.py access setup` |
| `no_journeys` | serviço S | `N probe(s) funcional(is) sem jornadas curadas para S: declare journeys no arquivo de fatos do coletor generic (references/collectors/generic.md)` |
| `no_adapter` | capacidade C | `N probe(s) sem adaptador para C: declare um em probes.adapters (references/probes.md)` |
| `verb_not_allowed` | adaptador D | `N probe(s) com verbo não liberado em D: libere em probes.adapters.D.verbs se for de leitura` |
| `not_linked` | serviço S, ambiente A | `N probe(s) em recurso não ligado a S em A: complete o mapa do atlas (coletor aws ou fatos do generic)` |
| `no_deployment` | serviço S, ambiente A | `N probe(s) sem deployment de S em A: mapeie o deployment no atlas` |

`production_unconfirmed`, `not_test_tier`, `invalid_args`, `invalid_target` e os de `error` não viram sugestão: são escolhas ou falhas, não falta de mapa ou acesso. Para configurar o acesso, `references/access-setup.md`.

## O `doctor`

- Sem a chave `probes`, nenhuma linha (o `doctor` fica como antes). Com ela: `OK probes — ligadas, N adaptador(es)` ou `OK probes — desligadas (probes.enabled: false)`; `ERRO probes — probes: <campo> inválido — …`.
- Uma linha por adaptador: `OK adaptador <id> — executável … encontrado`, ou não encontrado (ERRO com as probes ligadas, AVISO com elas desligadas). O `doctor` só usa `shutil.which`: não roda o `--describe`.
- O acesso local à nuvem, ao banco e à URL base (`acesso nuvem <ambiente>`, `acesso banco <id>`, `acesso url <ambiente>`) tem as linhas descritas em `references/config.md`.
- Com o `probes.log` e alguma sugestão nos últimos 30 dias (as mesmas do `probes stats --since 30d` do atlas escolhido): uma linha `AVISO uso das probes — <sugestão>` por sugestão, até 5, e depois `AVISO uso das probes — … e mais N: rode atlas.py probes stats`. No `doctor --json`, cada uma é um check `{"item": "uso das probes", "status": "AVISO", "detail": "<sugestão>"}`. Nunca muda o exit; sem log ou sem sugestão, nenhuma linha (SPEC-0104).

## Escrever um adaptador

1. Um executável (Python, Go, shell script com `#!`…) que aceita `--describe` e, sem ele, lê a entrada JSON do stdin.
2. Declare só verbos de leitura. `probe@1` e `probe@2` não têm verbo de escrita, e a credencial do adaptador deve ser só de leitura (por exemplo o ClusterRole `view` do Kubernetes, um profile da nuvem só de leitura, um usuário de banco só de leitura): é a barreira principal.
   Num adaptador novo, prefira `probe@2`: declare em cada capacidade os `targets` (o deployment ou os kinds de recurso), o `access` de que precisa (pode ser `[]`) e as `inputs` (`change`, `journeys`). Ele recebe só esses blocos.
3. Monte a chamada da ferramenta **só** a partir dos campos de `target` e `limits`, como lista de argumentos e sem shell; nunca a partir de texto livre. Use o profile de `target.cloud.profile` como argumento (`--profile`), o banco por `PGPASSFILE` e `target.database`; monte ARN ou URL com conta pela própria CLI, com operações de leitura.
4. Respeite `limits.lines` e `limits.since_seconds`; se cortar, devolva `truncated: true`.
5. Imprima uma única saída JSON no stdout. Erro da ferramenta → `status: error` com uma `message` curta e exit 0; exit diferente de 0 também vira erro (exit 1 do `probe`, com o fim do stderr mascarado).
6. Declare em `probes.adapters.<id>` com o `command`, os `verbs` liberados nesta máquina e as `credentials` por nome, e rode `atlas.py doctor`.
