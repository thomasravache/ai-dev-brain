# Probes — consultas só de leitura na infraestrutura

`atlas.py probe` roda uma consulta **só de leitura** na infraestrutura real (estado do workload, eventos, logs) por meio de um adaptador externo declarado nesta máquina. O atlas diz **onde** olhar (o deployment do serviço no ambiente, o cluster, o namespace e os workloads, SPEC-0087); o adaptador sabe **como** olhar (a ferramenta: `kubectl`, a CLI da nuvem, a API de logs). O núcleo garante as proteções num lugar só (ADR-0023, SPEC-0088):

- desligado por padrão;
- só os verbos que o adaptador declara **e** que esta máquina libera;
- ambiente de produção, ou sem marcação, só com `--confirm-production`;
- só cluster com acesso local (`access.clusters`);
- saída validada, limitada e mascarada;
- um registro local de cada probe, sem o resultado, e nada gravado no atlas.

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

- `PATH`, `HOME`, `USER`, `LOGNAME`, `LANG`, `LC_ALL`, `LC_CTYPE`, `LC_MESSAGES`, `TZ`, `TMPDIR`, `TMP` e `TEMP` (e, no Windows, `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`, `COMSPEC`, `PATHEXT`, `USERPROFILE`, `APPDATA` e `LOCALAPPDATA`), quando definidos;
- as variáveis declaradas em `credentials` **desse** adaptador.

Nenhuma variável declarada só para outro adaptador ou para os coletores chega a ele. Precisa de `KUBECONFIG` ou `AWS_PROFILE`? Declare o nome em `credentials`.

## O comando

```text
atlas.py probe <capacidade> <verbo> --service <id> --env <ambiente>
    [--since 30m] [--lines N] [--summary] [--confirm-production] [--json] [--atlas X]
```

Os passos, nesta ordem:

1. Sem `probes.enabled: true` → exit 4 `probes desligadas nesta máquina (probes.enabled)`. Nada roda, nem o `--describe`, e nada é registrado.
2. `--lines` fora de 1..2000 ou `--since` fora do formato ou acima de 24h → exit 2.
3. **Alvo:** o deployment de `service:<id>` que faz `runs_in` em `environment:<ambiente>` no `graph.json` (o primeiro pelo id, se houver mais de um). Nenhum → exit 2 com o serviço e o ambiente procurados.
   Os campos do alvo que vêm do atlas são conferidos antes de qualquer processo rodar (nem o `--describe`); fora da regra → exit 2 `alvo inválido no atlas: …`, sem citar o valor:
   - `namespace` (quando há) segue o DNS-1123: minúsculas, dígitos e `-`, até 63, sem começar nem terminar com `-`;
   - cada `workload` é `Kind/nome`, com o nome em DNS-1123 subdomínio (até 253) e o Kind sem começar com `-`;
   - `service`, `deployment` e `environment` seguem a regra de nome simples do atlas (`ENVIRONMENT_NAME_RE` de `references/config.md`: letras, dígitos, `.`, `_` e `-`, começando e terminando com letra ou dígito);
   - cada nome em `clusters` segue a regra de nome simples ou é uma URL de servidor (`https://kubernetes.default.svc`) sem espaço, sem caractere de controle e sem `-` no começo (Emenda v5).
   Assim nenhum adaptador recebe um texto que pareça uma opção de linha de comando.
4. **Adaptador:** o primeiro em `adapters` cujo `--describe` declara a capacidade. Nenhum → exit 4 `nenhum adaptador para <capacidade>`.
5. **Verbo:** fora de (verbos do `--describe` ∩ `verbs` da configuração) → exit 4 `verbo <v> não permitido`. O adaptador não roda.
6. **Produção:** `tier` do ambiente (em `environments:` do `atlas-config.yml`) diferente de `test`, inclusive sem `tier`, e sem `--confirm-production` → exit 4 `ambiente <a> é de produção ou sem marcação: confirme com a pessoa e use --confirm-production`.
7. **Acesso:** nenhum cluster do deployment em `access.clusters` → exit 4 `sem acesso local ao cluster <c> (access.clusters)`. Vale o contexto do primeiro cluster (pelo nome) que tem acesso local.
8. Roda o adaptador com a entrada no stdin, as credenciais dele e o timeout; lê no máximo 1 MB do stdout.
9. Valida a saída, mascara, corta em `lines` itens e imprime (Markdown ou `--json`); registra.

| Exit | Quando |
|---|---|
| 0 | ok |
| 1 | adaptador ausente, com erro (`status: error`, exit diferente de 0), tempo esgotado, saída acima de 1 MB, JSON inválido (inclusive aninhamento profundo, `NaN`/`Infinity` e texto com surrogate solto) ou fora do contrato — com o motivo e sem nenhum item |
| 2 | argumento ou configuração inválida, alvo inexistente ou com campo fora da regra |
| 3 | sem configuração local |
| 4 | recusado: desligadas, sem adaptador, verbo, produção sem confirmação, sem acesso local |

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

## Redaction

Valem os padrões do `references/redaction.md` e o `redaction.extra_patterns` do atlas, mais os de dados pessoais e segredos de linha de log: e-mail, CPF, CNPJ, `Bearer <token>` e `<nome>=<valor>` quando o nome diz senha, segredo, token ou chave (`token=…`, `password: …`, `api_key=…`). O trecho vira `[REDACTED]`. O stderr de um adaptador com falha é mascarado inteiro antes de ser cortado (últimas 20 linhas).

Além disso, o valor do contexto escolhido (`target.context`) e os valores das credenciais declaradas do adaptador são mascarados, literalmente, em tudo o que vem do adaptador antes de imprimir ou registrar: itens (chaves e valores), `message`, a cauda do stderr, a amostra e a assinatura do `--summary` e o texto de falha do contrato.

Ordem da máscara (Emenda v5):

1. primeiro os padrões de segredo (os do `references/redaction.md`, os de linha de log acima e o `redaction.extra_patterns`), no texto original;
2. depois os literais (o contexto e os valores das credenciais).

Assim um contexto curto, como `api`, não impede que `api_key=<valor>` seja mascarado. A máscara literal não diferencia maiúsculas e pega, de cada valor, a forma crua, a escapada como dentro de uma string JSON (com e sem `/` escrito `\/`) e a codificada em URL (`%3A`, `%2F`…).

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
- Nunca guarda `items`, `message` nem o contexto do cluster. Com as probes desligadas, nada é registrado.

## O `doctor`

- Sem a chave `probes`, nenhuma linha (o `doctor` fica como antes). Com ela: `OK probes — ligadas, N adaptador(es)` ou `OK probes — desligadas (probes.enabled: false)`; `ERRO probes — probes: <campo> inválido — …`.
- Uma linha por adaptador: `OK adaptador <id> — executável … encontrado`, ou não encontrado (ERRO com as probes ligadas, AVISO com elas desligadas). O `doctor` só usa `shutil.which`: não roda o `--describe`.

## Escrever um adaptador

1. Um executável (Python, Go, shell script com `#!`…) que aceita `--describe` e, sem ele, lê a entrada JSON do stdin.
2. Declare só verbos de leitura. `probe@1` não tem verbo de escrita, e a credencial do adaptador deve ser só de leitura (por exemplo o ClusterRole `view` do Kubernetes): é a barreira principal.
3. Monte a chamada da ferramenta **só** a partir dos campos de `target` e `limits`, como lista de argumentos e sem shell; nunca a partir de texto livre.
4. Respeite `limits.lines` e `limits.since_seconds`; se cortar, devolva `truncated: true`.
5. Imprima uma única saída JSON no stdout. Erro da ferramenta → `status: error` com uma `message` curta e exit 0; exit diferente de 0 também vira erro (exit 1 do `probe`, com o fim do stderr mascarado).
6. Declare em `probes.adapters.<id>` com o `command`, os `verbs` liberados nesta máquina e as `credentials` por nome, e rode `atlas.py doctor`.
