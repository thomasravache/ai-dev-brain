# Adaptador de probe `suite`

Adaptador da capacidade `functional` do contrato `probe@2` (`references/probes.md`, SPEC-0096). Vem com a skill em `assets/probes/suite.py` (só biblioteca padrão, Python 3.9 ou mais novo) e roda as **suítes do time** (Playwright, pytest, k6, Postman…) contra o ambiente de teste, uma jornada por vez, sem shell (SPEC-0103, ADR-0023, ADR-0026 regra 4).

| Verbo | Pergunta | Itens |
|---|---|---|
| `run` | A jornada do usuário funciona neste ambiente de teste, depois do deploy? | um por jornada pedida |

O atlas diz **quais** jornadas valem para o serviço (atributo `journeys`, curado por uma pessoa: `references/collectors/generic.md`). O **arquivo de jornadas** desta máquina diz **como** rodar cada uma. Nenhum comando sai do atlas, e o núcleo não sabe de comandos: ele entrega ao adaptador só os ids (`target.journeys`) e a URL base (`target.urls.base_url`).

O núcleo garante antes de qualquer processo, inclusive o `--describe`, e sem opção que desligue:

- **só `tier: test`:** em qualquer outro ambiente, inclusive sem `tier`, exit 4 `validação funcional só roda em ambiente tier: test (<ambiente> não é)`, mesmo com `--confirm-production`;
- **só com jornadas curadas:** sem `journeys` no serviço, exit 4 `sem jornadas curadas para <serviço> (attrs.journeys)`.

## Configurar

1. Declare as jornadas do serviço no arquivo de fatos do coletor `generic` (`{"kind": "service", "id": "api", "attrs": {"journeys": ["checkout", "login"]}}`), rode `scan` e `build`.
2. Grave a URL base do ambiente de teste em `access.urls.<ambiente>.base_url` (`atlas.py access setup`, `references/access-setup.md`).
3. Escreva o arquivo de jornadas (abaixo) **na pasta da configuração local** desta máquina (ao lado do `config.yml`), nunca no atlas: o adaptador não sabe onde fica o atlas, e o `doctor` não lê o arquivo.
4. Declare o adaptador no `config.yml` **desta máquina**, com o caminho absoluto do arquivo no próprio `command`:

```yaml
probes:
  enabled: true
  adapters:
    suite:
      command: ["python3", "<skill-dir>/assets/probes/suite.py", "--journeys-file", "<pasta da configuração local>/journeys.json"]
      verbs: [run]
      timeout: 300                                         # maior que a soma dos timeouts das jornadas
      credentials: [CHECKOUT_TEST_USER, CHECKOUT_TEST_PASSWORD]   # só nomes; os valores ficam no ambiente
```

5. Rode uma probe de teste:

```bash
python3 <skill-dir>/scripts/atlas.py probe functional run --service api --env dev
python3 <skill-dir>/scripts/atlas.py probe functional run --service api --env dev --journey login --json
```

- **Tempo:** cada jornada tem o próprio `timeout` (padrão 120 s, de 1 a 300) e elas rodam uma depois da outra. O `timeout` do adaptador (1 a 300 s) encerra o grupo de processos inteiro, suítes inclusive: escolha-o maior que a soma das jornadas.
- **Credenciais:** a conta de teste chega à suíte pelo nome da variável, como as outras credenciais (ADR-0010). O adaptador recebe só as `credentials` declaradas nele; cada suíte recebe só as da **própria** jornada.

## Arquivo de jornadas

JSON (o adaptador é só biblioteca padrão). Validado inteiro antes de rodar qualquer jornada.

```json
{"journeys": {
  "checkout": {"command": ["npx", "playwright", "test", "e2e/checkout.spec.ts"],
               "cwd": "/caminho/absoluto/do/repositorio",
               "timeout": 120,
               "credentials": ["CHECKOUT_TEST_USER", "CHECKOUT_TEST_PASSWORD"]},
  "login": {"command": ["pytest", "-q", "e2e/test_login.py"], "cwd": "/caminho/absoluto/do/repositorio"}
}}
```

| Chave | Regra |
|---|---|
| topo | só `journeys`, um mapa `<id>: {...}` |
| `<id>` | regra de nome simples do atlas (letras, dígitos, `.`, `_` e `-`, começando e terminando com letra ou dígito) |
| `command` | obrigatório; lista não vazia de textos; `command[0]` é um nome sem pasta (procurado no `PATH`) ou um caminho absoluto |
| `cwd` | opcional; caminho absoluto. Sem ele, a suíte roda numa pasta temporária |
| `timeout` | opcional; inteiro de 1 a 300 (segundos), padrão 120 |
| `credentials` | opcional; nomes de variável (`^[A-Z_][A-Z0-9_]*$`) |

Qualquer outra chave, em qualquer nível, é recusada. Arquivo ausente, ilegível, acima de 1 MB, que não é JSON ou fora dessas regras → `status: error` com `arquivo de jornadas inválido: <campo> — <motivo>` (nunca o valor), e nenhuma jornada roda. Sem `--journeys-file` no `command` → `status: error` `sem arquivo de jornadas (--journeys-file)`.

## Como cada jornada roda

Para cada id de `target.journeys`, na ordem:

| Situação | Resultado | `failed_steps` |
|---|---|---|
| id sem entrada no arquivo | `skipped` | `jornada sem comando neste arquivo de jornadas` |
| credencial da jornada fora do ambiente do adaptador | `skipped` | `credencial não recebida: <NOME>` |
| executável não encontrado | `skipped` | `comando da suíte não encontrado` |
| a suíte sai com 0 | `passed` | `[]` |
| a suíte sai com 77 | `skipped` | `a suíte pulou a jornada` |
| a suíte sai com outro código | `failed` | as linhas do protocolo, ou `a suíte saiu com <n>` |
| tempo esgotado | `failed` | `tempo esgotado (<n>s)`; o grupo da suíte é encerrado |

- Roda sem shell (lista de argumentos), no `cwd` (ou numa pasta temporária), num grupo de processos próprio, sem stdin.
- Ambiente da suíte: o mínimo das probes (`PATH`, `HOME`, `LANG`…), as `credentials` **daquela** jornada e `ATLAS_SERVICE`, `ATLAS_ENVIRONMENT`, `ATLAS_JOURNEY` e `ATLAS_BASE_URL` (de `target.urls.base_url`). Nenhuma outra variável.
- Jornadas do arquivo que não estão em `target.journeys` nunca rodam.

### Protocolo da suíte

A suíte diz o resultado pelo exit (0 passou, 77 pulou, outro falhou) e os passos que falharam por linhas da saída padrão que começam com `ATLAS-FAILED-STEP: `:

```text
ATLAS-FAILED-STEP: campo senha não apareceu
```

O adaptador lê no máximo 1 MB da saída de cada suíte, guarda até 5 dessas linhas, sem o prefixo e cortadas em 200 caracteres, e descarta o resto. **Nenhuma outra linha da suíte** (nem o stderr) sai do adaptador: a saída de uma suíte pode ter dado de teste. O núcleo mascara a URL base, os valores das credenciais e os padrões de segredo nos passos.

## Contrato

### Descrição

```json probe@2 functional describe valid
{"contract": "probe@2", "adapter": "suite", "capabilities": {"functional": {"verbs": ["run"], "targets": ["deployment"], "access": ["urls"], "inputs": ["journeys"]}}}
```

```json probe@2 functional describe invalid
{"contract": "probe@2", "adapter": "suite", "capabilities": {"functional": {"verbs": ["run"], "targets": ["deployment"], "access": ["urls"], "inputs": ["commands"]}}}
```

### Entrada

Sem campos de cluster e sem nenhum comando:

```json probe@2 functional input valid
{"contract": "probe@2", "capability": "functional", "verb": "run", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "urls": {"base_url": "https://dev.acme.example"}, "journeys": ["checkout", "login"]}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 functional input invalid
{"contract": "probe@2", "capability": "functional", "verb": "run", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "urls": {"base_url": "https://dev.acme.example"}, "journeys": ["checkout"], "command": ["npx", "playwright", "test"]}, "limits": {"lines": 200, "since_seconds": 1800}}
```

### Saída

Além da validação genérica, o núcleo confere a saída de `functional` (`validate_functional_output`): um item por id de `target.journeys`, na mesma ordem, com exatamente `journey`, `result` (`passed`, `failed` ou `skipped`), `duration_seconds` (número ≥ 0) e `failed_steps` (até 5 textos de até 200 caracteres). Id a mais, faltando ou repetido, chave a mais ou `result` fora da lista → exit 1 `saída fora do contrato`, sem itens. Uma jornada `failed` **não** muda o exit do probe (0): o probe informa e o `verify` julga.

```json probe@2 functional output valid
{"contract": "probe@2", "adapter": "suite", "capability": "functional", "verb": "run", "status": "ok", "truncated": false, "items": [{"journey": "checkout", "result": "passed", "duration_seconds": 12.4, "failed_steps": []}, {"journey": "login", "result": "failed", "duration_seconds": 3.1, "failed_steps": ["campo senha não apareceu"]}]}
```

```json probe@2 functional output valid
{"contract": "probe@2", "adapter": "suite", "capability": "functional", "verb": "run", "status": "error", "truncated": false, "items": [], "message": "sem arquivo de jornadas (--journeys-file)"}
```

Um id repetido (e `login` faltando):

```json probe@2 functional output invalid
{"contract": "probe@2", "adapter": "suite", "capability": "functional", "verb": "run", "status": "ok", "truncated": false, "items": [{"journey": "checkout", "result": "passed", "duration_seconds": 1, "failed_steps": []}, {"journey": "checkout", "result": "passed", "duration_seconds": 1, "failed_steps": []}]}
```

Um `result` fora da lista e uma chave a mais:

```json probe@2 functional output invalid
{"contract": "probe@2", "adapter": "suite", "capability": "functional", "verb": "run", "status": "ok", "truncated": false, "items": [{"journey": "checkout", "result": "ok", "duration_seconds": 1, "failed_steps": []}, {"journey": "login", "result": "passed", "duration_seconds": 1, "failed_steps": [], "stdout": "linha da suíte"}]}
```

## Erros

`status: error` (exit 0 do adaptador; exit 1 do probe), com a mensagem curta:

| Mensagem | Quando |
|---|---|
| `sem arquivo de jornadas (--journeys-file)` | o `command` não traz `--journeys-file` |
| `arquivo de jornadas inválido: <campo> — <motivo>` | arquivo ausente, ilegível, acima de 1 MB, que não é JSON ou fora das regras |
| `entrada inválida` | a entrada no stdin não é a de `probe@2 functional run` |

No `verify compare --functional` (`references/verify.md`), qualquer `skipped`, recusa ou erro deixa a verificação `functional` em `not_verified`, nunca `ok`.
