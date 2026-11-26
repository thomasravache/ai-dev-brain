---
id: SPEC-0103
title: "boson-atlas: validação funcional em teste — jornadas e suítes curadas"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-24
parent: SPEC-0095
depends_on: [SPEC-0102, SPEC-0104]
consumes_contract: []
contract_version: 2
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/assets/probes/suite.py, skills/boson-atlas/references/probes.md, skills/boson-atlas/references/probes/suite.md, skills/boson-atlas/references/verify.md, skills/boson-atlas/references/collector-contract.md, skills/boson-atlas/references/collectors/generic.md, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, skills/boson-atlas/tests/test_probe_functional.py, skills/boson-atlas/tests/test_probe_suite.py, skills/boson-atlas/tests/test_verify_functional.py, skills/boson-atlas/tests/test_probe_resource.py, skills/boson-atlas/tests/fixtures/functional/**, skills/boson-atlas/tests/architecture_rules.py, skills/boson-atlas/tests/test_architecture.py, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0011, ADR-0012, ADR-0023, ADR-0025, ADR-0026]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-24
---

# SPEC-0103 — boson-atlas: validação funcional em teste — jornadas e suítes curadas

> Origem: épico SPEC-0095 (regra 4 do ADR-0026). Fecha o passo "smoke e E2E em teste" da rotina real de verificação da SPEC-0075: depois do deploy, a jornada principal do serviço roda no ambiente de teste e vira evidência do G6. Produção continua só passiva.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
A boson-atlas ganha a validação funcional, que só roda em ambiente `tier: test`:
- **no atlas:** o atributo `journeys` do `service`, uma lista de ids de jornadas curadas por uma pessoa (ADR-0012), que entra pelo arquivo de fatos do coletor `generic`;
- **no núcleo do probe:** a capacidade `functional`, com o verbo `run`, recusada (exit 4) em qualquer ambiente que não seja `tier: test`, mesmo com `--confirm-production`, e sem jornadas curadas. O núcleo continua genérico: entrega ao adaptador só os ids (`target.journeys`, SPEC-0096) e a URL base (`target.urls.base_url`, SPEC-0096);
- **na máquina:** o adaptador `suite`, que vem com a skill. Ele lê de um **arquivo de jornadas local**, passado no próprio `command` (`--journeys-file`), o mapa jornada → comando. Roda só as jornadas pedidas que existem no arquivo, sem shell, e marca as que faltam como `skipped`;
- **no `verify compare`:** a verificação `functional`, ligada por `--functional`, que entra no veredito do `verify@2` (SPEC-0102) sem quebrá-lo.

O atlas diz **quais** jornadas valem para o serviço; o arquivo desta máquina diz **como** rodar cada uma. Nenhum comando sai do atlas.

## 2. Motivação & Escopo
**Motivação:** o `verify` prova que a versão chegou, que o workload está de pé e que as dependências seguem a foto, mas não que a jornada do usuário funciona. Hoje a gluon-spec só tem o `smoke_test` e o `test_e2e` do projeto, sem ligação com o ambiente nem com o veredito. Rodar a jornada à mão em teste é lento e não deixa evidência repetível. Rodar em produção está fora de questão (SPEC-0075: produção só passiva).

**Objetivos (dentro do escopo):**
- **Atributo `journeys`** no nó `service`: lista de ids na regra de nome simples do atlas (a mesma que a SPEC-0096 confere), sem repetição. Entra pelo arquivo de fatos do coletor `generic`, escrito por uma pessoa e aprovado no PR do atlas (modo `repo`) ou editado por ela (modo `local`). É uma lista de escalares, então o contrato dos coletores continua `@1` (ADR-0011), sem kind novo.
- **Capacidade `functional`** no `atlas.py probe`, com o verbo `run`:
  - só em `tier: test`; em qualquer outro ambiente, inclusive sem `tier`, exit 4, mesmo com `--confirm-production`;
  - sem jornadas curadas, exit 4;
  - `--journey <id>` (repetível) restringe às curadas escolhidas;
  - a saída tem uma validação própria: um item por jornada pedida.
- **Adaptador `suite`** (`assets/probes/suite.py`, só biblioteca padrão), declarado com `access: ["urls"]` e `inputs: ["journeys"]`:
  - lê o arquivo de jornadas local (JSON) indicado por `--journeys-file` no `command`;
  - para cada id de `target.journeys`, roda o comando do arquivo, ou marca `skipped` quando o id não está no arquivo;
  - devolve um item por jornada: `journey`, `result` (`passed`, `failed` ou `skipped`), `duration_seconds` e `failed_steps` (textos curtos, mascarados).
- **Verificação `functional`** no `verify compare --functional [--journey <id>]...`: `ok`, `failed` ou `not_verified`, com o motivo. Fora de `tier: test`, fica `not_verified` sem rodar nada.

**Não-objetivos (fora do escopo):**
- **Rodar qualquer coisa funcional em produção**, por qualquer caminho.
- **Comando, script ou URL vindos do atlas:** o atlas guarda só ids de jornada.
- **Configuração de jornada no núcleo:** o `config.yml` não ganha chave nova. O arquivo de jornadas é do adaptador, e o caminho dele vai no `command` local, como qualquer argumento de adaptador.
- **Inferir jornadas** dos testes do repositório ou de outro coletor: só a pessoa declara (ADR-0012).
- **Um runner de testes próprio:** a suíte é a do time (Playwright, pytest, k6, Postman…); o adaptador só a chama e lê o resultado.
- **Criar a conta de teste ou fazer login:** a conta chega à suíte pelo nome da variável, como as outras credenciais.
- **Guardar a jornada no `snapshot`:** a jornada é absoluta (passa ou não depois do deploy), não comparada com antes.
- **O G6 da gluon-spec:** SPEC-0105.

## 3. Dependências
- **Implementações necessárias:**
  - SPEC-0102: o `verify@2` (as chaves de cada verificação, `resource: null` nas de deployment, e o validador do resultado), onde a verificação `functional` entra. Por ela chega a SPEC-0096, que já entrega o `probe@2` com `inputs: ["journeys"]` (os ids do atributo do serviço em `target.journeys`, conferidos pela regra de nome simples) e `access: ["urls"]` (`access.urls.<ambiente>.base_url` em `target.urls.base_url`, exit 4 `sem acesso local: urls`, máscara da URL), e só manda os campos de cluster a quem declara `cluster`;
  - SPEC-0104: os códigos `reason` do `probes.log` (`not_test_tier`, `no_journeys`, `no_access` com `access: urls`) e o `access setup`, que grava a URL base.
- **Contratos consumidos:** N/A (o `probe@2` e o `verify@2` chegam com as implementações).
- **Pré-requisitos externos:** N/A. Os testes usam uma suíte falsa em Python; nenhuma ferramenta de teste de verdade é exigida.

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **núcleo do probe:** `run_probe` e `_probe_query` do `scripts/atlas.py` (SPEC-0088) e os passos do `probe@2` (SPEC-0096), com a ordem das recusas, a máscara numa passada e o registro em `probes.log`;
- **adaptador que vem com a skill:** `assets/probes/kubernetes.py` e `references/probes/kubernetes.md` (SPEC-0089); o `command` local de um adaptador aceita argumentos (lista, sem shell), por onde o `suite` recebe o `--journeys-file`;
- **verificação no `verify`:** as de `cmd_verify_compare` (SPEC-0090) e as de `dependencies` e `signals` (SPEC-0102);
- **atributo de lista de escalares no contrato `@1`:** `images` e `workloads` (`references/collector-contract.md`);
- **testes:** `tests/test_probe.py`, `tests/test_verify.py` e os adaptadores falsos de `tests/fixtures/fake-probes`.

**Decisão:**
- `functional` é mais uma capacidade do núcleo, com duas regras que o núcleo garante antes de escolher o adaptador: **só `tier: test`** e **ao menos uma jornada curada**. Assim nem o `--describe` roda num ambiente recusado.
- O núcleo continua genérico: entrega os ids (`target.journeys`) e a URL base (`target.urls`) pelo `probe@2` da SPEC-0096, sem saber de comandos.
- O adaptador `suite` resolve id → comando por um arquivo local próprio, cujo caminho a pessoa põe no `command` do adaptador. Um time pode trocar o `suite` por outro adaptador que fale o mesmo contrato.
- A verificação `functional` do `verify compare` só existe com `--functional` e chama o probe pelo mesmo `run_probe`.

**Justificativa:**
- A regra "nada funcional fora de teste" fica num lugar só, o núcleo, e vale para qualquer adaptador (ADR-0026, regra 4).
- O núcleo não ganha configuração específica de uma capacidade.
- Os comandos ficam na máquina que tem o acesso, num arquivo que só o adaptador lê (ADR-0023).
- O atlas continua só dado: um id de jornada não executa nada.

**Desvio do padrão existente:** nenhum. O contrato dos coletores continua `@1`, e a configuração local não muda de forma.

**Alternativas descartadas:**
- **Mapa jornada → comando em `probes.adapters.<id>.journeys`, validado pelo núcleo** (primeira versão desta spec): punha no núcleo configuração de uma capacidade só. A decisão do Architect foi manter o núcleo genérico.
- **URL base no atlas** (atributo `urls` do `environment`): o mapa `environments:` aceita só `tier`, e a URL interna não precisa ir ao repositório do atlas. Fica em `access.urls` (ADR-0025, SPEC-0096).
- **Comando da suíte no atlas** (por exemplo, nas notas do serviço): poria instrução no atlas, contra a SPEC-0075 e o ADR-0026.
- **Curadoria das jornadas pelo `curate confirm`:** o `curate` decide propostas inferidas. Uma jornada nunca é inferida: quem escreve o arquivo de fatos já é a pessoa, e o PR do atlas é a confirmação (o mesmo "quem confirma" do `references/curation.md`).

**ADRs:** ADR-0010 (credencial só por nome), ADR-0011 (contrato `@1`, lista de escalares), ADR-0012 (curadoria humana), ADR-0023 (probes), ADR-0025 (`probe@2`, `inputs: ["journeys"]`, acesso `urls`), ADR-0026 (regra 4: funcional só em `tier: test`).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:**
  - cada jornada tem `timeout` próprio no arquivo (padrão 120 s, de 1 a 300), e as jornadas rodam uma depois da outra;
  - o `timeout` do adaptador (`probes.adapters.suite.timeout`, de 1 a 300 s) encerra o grupo de processos inteiro, suítes inclusive. O `references/probes/suite.md` orienta a escolher esse `timeout` maior que a soma das jornadas;
  - o adaptador lê no máximo 1 MB da saída de cada suíte e descarta o resto.
- **Segurança:**
  - as regras de `tier: test` e de jornadas curadas vêm antes de qualquer processo, inclusive o `--describe`, e não há opção que as desligue;
  - o comando de cada jornada é uma lista no arquivo local; o executável segue a regra do `command` dos adaptadores (nome no `PATH` ou caminho absoluto); nada vem do atlas;
  - nada roda com shell: núcleo e adaptador usam lista de argumentos;
  - o arquivo de jornadas é da máquina, nunca do atlas. O adaptador não sabe onde fica o atlas, então o `references/probes/suite.md` orienta a guardar o arquivo na pasta da configuração local. O `doctor` não lê o arquivo;
  - a suíte recebe só o ambiente que o núcleo deu ao adaptador (o mínimo das probes e as `credentials` do adaptador), filtrado às `credentials` **daquela** jornada no arquivo, mais as variáveis `ATLAS_*` do contrato;
  - a URL base (SPEC-0096) e os valores das credenciais entram na máscara literal do núcleo; `failed_steps` passa pela redaction das probes;
  - o `suite.py` passa nas regras de arquitetura (só biblioteca padrão, processos sem shell).
- **Privacidade e dados pessoais:** a saída de uma suíte pode ter dado de teste. Por isso só sai `failed_steps`, no máximo 5 textos de até 200 caracteres, tirados das linhas do protocolo (seção 6) e mascarados. O resto da saída nunca é impresso, gravado nem registrado.
- **Disponibilidade e resiliência:**
  - id sem entrada no arquivo, comando não encontrado, credencial pedida que o adaptador não recebeu ou suíte que sai com 77 → `skipped`, com o motivo;
  - tempo esgotado numa jornada → `failed`, com `tempo esgotado (<n>s)`;
  - arquivo de jornadas ausente ou inválido → `status: error` (exit 1 do probe);
  - no `verify`, qualquer `skipped`, recusa ou erro deixa a verificação `not_verified`, nunca `ok`.
- **Acessibilidade (UI):** N/A — CLI sem interface gráfica.
- **Custo:** N/A — a suíte roda no ambiente de teste do time, que já existe.

## 6. Artefato A — Contrato
**Interface:** o atributo `journeys`, a capacidade `functional` no `probe`, o adaptador `suite` com o arquivo de jornadas e a verificação `functional` do `verify compare`.

```text
ATLAS (arquivo de fatos do coletor generic, escrito por uma pessoa)
  {"entities": [{"kind": "service", "id": "api", "attrs": {"journeys": ["checkout", "login"]}}]}
  journeys: lista de ids na regra de nome simples, sem repetição; lista de escalares (contrato @1)
  o build guarda no nó service:api; nenhum coletor da skill além do generic emite journeys

CONFIGURAÇÃO LOCAL (config.yml desta máquina; sem chave nova)
  access:
    urls: {dev: {base_url: https://dev.acme.example}}           # SPEC-0096; gravada pelo access setup (SPEC-0104)
  probes:
    adapters:
      suite:
        command: ["python3", "<pasta da skill>/assets/probes/suite.py",
                  "--journeys-file", "/caminho/absoluto/journeys.json"]
        verbs: [run]
        timeout: 300
        credentials: [CHECKOUT_TEST_USER, CHECKOUT_TEST_PASSWORD]

ARQUIVO DE JORNADAS (da máquina, nunca do atlas; lido só pelo adaptador suite; JSON)
  {"journeys": {
     "checkout": {"command": ["npx", "playwright", "test", "e2e/checkout.spec.ts"],
                  "cwd": "/caminho/absoluto/do/repositorio",           # opcional; padrão: a pasta temporária
                  "timeout": 120,                                       # opcional; 1 a 300, padrão 120
                  "credentials": ["CHECKOUT_TEST_USER", "CHECKOUT_TEST_PASSWORD"]}}}   # opcional; só nomes
  regras (o adaptador valida o arquivo inteiro antes de rodar qualquer jornada):
    chaves fechadas no topo (journeys) e em cada jornada (command, cwd, timeout, credentials)
    id da jornada na regra de nome simples
    command: lista não vazia de textos; command[0] nome sem pasta (PATH) ou caminho absoluto
    cwd: caminho absoluto; timeout: inteiro de 1 a 300; credentials: nomes ^[A-Z_][A-Z0-9_]*$
  inválido, ausente, ilegível ou acima de 1 MB → status error, message
    "arquivo de jornadas inválido: <campo> — <motivo>" (sem valor) ou "sem arquivo de jornadas (--journeys-file)"
  sem --journeys-file no command → status error "sem arquivo de jornadas (--journeys-file)"

PROBE
  atlas.py probe functional run --service <id> --env <ambiente> [--journey <id>]...
      [--confirm-production] [--json] [--atlas X]
  ordem: a do probe@2 (SPEC-0096), mais os passos marcados com *:
    1. probes desligadas → 4
    2. argumentos → 2; *--journey fora da regra de nome simples → 2 "--journey inválido"
    3. deployments do serviço no ambiente → 2
    *3a. capacidade functional e tier do ambiente diferente de test (inclusive sem tier) → 4
         "validação funcional só roda em ambiente tier: test (<ambiente> não é)" — com ou sem
         --confirm-production; nada roda, nem o --describe; probes.log: refused, reason not_test_tier
    *3b. capacidade functional: journeys do nó service (lidas e conferidas pela regra da SPEC-0096; fora da
         regra → 2 "alvo inválido no atlas: journeys …") vazias → 4 "sem jornadas curadas para <serviço>
         (attrs.journeys)", probes.log: refused, reason no_journeys; --journey fora das curadas → 2
         "jornada <id> não curada para <serviço>"
    7. adaptador da capacidade functional → 4
    8. entradas: target.journeys = as curadas, ou só as de --journey, na ordem curada (SPEC-0096);
       *--journey numa capacidade sem "journeys" em inputs → 2 "--journey não é aceito por <capacidade>"
    9. verbo run liberado → 4
    10. produção: já coberta pelo 3a (só tier: test chega aqui)
    11. acesso urls (SPEC-0096): faltou → 4 "sem acesso local: urls"; probes.log: refused, reason no_access,
        access urls
    12. roda o adaptador; 13. valida (genérica e *a própria de functional), mascara, imprime e registra
  exits: os do probe (0 ok · 1 adaptador com erro ou fora do contrato · 2 · 3 · 4)
  um resultado de jornada failed NÃO muda o exit do probe (0): o probe informa; o verify julga

PROBE@2 — DESCRIBE do adaptador suite
  {"contract": "probe@2", "adapter": "suite",
   "capabilities": {"functional": {"verbs": ["run"], "targets": ["deployment"], "access": ["urls"],
                                   "inputs": ["journeys"]}}}

PROBE@2 — ENTRADA (stdin), a da SPEC-0096
  {"contract": "probe@2", "capability": "functional", "verb": "run",
   "target": {"service": "api", "environment": "dev", "deployment": "dev-api",
              "urls": {"base_url": "https://dev.acme.example"}, "journeys": ["checkout", "login"]},
   "limits": {"lines": 200, "since_seconds": 1800}}
  sem clusters, context, namespace nem workloads

PROBE@2 — SAÍDA da capacidade functional (validação própria do núcleo, além da genérica)
  items: um por id de target.journeys, na mesma ordem, com chaves fechadas:
    {"journey": "<id>", "result": "passed" | "failed" | "skipped",
     "duration_seconds": <número >= 0>, "failed_steps": [<texto até 200 caracteres>, ... no máximo 5]}
  id que não estava na entrada, faltando, repetido, chave a mais, result fora da lista
    → exit 1 "saída fora do contrato: …"

ADAPTADOR suite (assets/probes/suite.py)
  valida o arquivo de jornadas (acima); depois, por id de target.journeys, em ordem:
    id sem entrada no arquivo → skipped, failed_steps ["jornada sem comando neste arquivo de jornadas"]
    credencial da jornada que não está no ambiente do adaptador → skipped, ["credencial não recebida: <NOME>"]
    executável não encontrado → skipped, ["comando da suíte não encontrado"]
    roda sem shell, em cwd (ou na pasta temporária), num grupo de processos próprio, com o timeout da jornada
    ambiente da suíte: o mínimo das probes (PATH, HOME, LANG…), as credentials DA JORNADA e
      ATLAS_SERVICE, ATLAS_ENVIRONMENT, ATLAS_JOURNEY e ATLAS_BASE_URL (de target.urls.base_url)
    exit 0 → passed · exit 77 → skipped ["a suíte pulou a jornada"] · outro → failed
    tempo esgotado → failed ["tempo esgotado (<n>s)"], o grupo da suíte é encerrado
    failed_steps: as linhas da saída padrão da suíte que começam com "ATLAS-FAILED-STEP: ", sem o prefixo,
      até 5, cada uma cortada em 200 caracteres; failed sem nenhuma → ["a suíte saiu com <n>"]
    nenhuma outra linha da suíte sai do adaptador
  jornadas do arquivo que não estão em target.journeys nunca rodam
  status error (exit 0) para entrada inválida e arquivo de jornadas ausente ou inválido, com message curta

VERIFY
  atlas.py verify compare ... [--functional] [--journey <id>]...
  sem --functional: nenhuma verificação functional (como hoje); --journey sem --functional → 2
  com --functional, por serviço e ambiente, depois das verificações do verify@2:
    tier diferente de test (inclusive sem tier) → not_verified "validação funcional só em tier: test";
      nenhum processo roda e nada é registrado para a functional
    alguma verificação delivery que não deu ok → not_verified "entrega não confirmada: a jornada rodaria
      contra outra versão" (não roda)
    senão roda probe functional run pelo run_probe (com os --journey):
      ok          — todas as jornadas passed (ao menos uma)
      failed      — alguma failed (as failed na evidência, com failed_steps)
      not_verified — nenhuma failed e alguma skipped ("jornada pulada: <ids>"); probe recusada (sem jornadas
                     curadas, sem acesso local: urls, sem adaptador), com erro (arquivo de jornadas inválido)
                     ou fora do contrato, com o motivo
  a verificação: {"deployment": "<o do alvo>", "resource": null, "check": "functional", "status", "evidence",
    "reason"} — as chaves das verificações de deployment do verify@2 (SPEC-0102)
  evidence: {"environment_tier": "test", "journeys": [{"journey", "result", "duration_seconds",
             "failed_steps"}]}
  veredito, exits e suggestion: as regras do verify@2, sem mudança (failed → degradou)
  validate_verify_result aceita check "functional" com essa evidência; o contrato continua verify@2
  o snapshot não muda
```

**Esclarecimentos (Emenda v2):**
- `test_probe_resource.py` (SPEC-0096) entra nos `touches`: três testes dele (`test_urls_and_journeys`, `test_the_log_has_resource_only_when_used`, `test_delivery_and_functional_through_the_cli`) esperam um `worker` sem jornadas com exit 0 e uma saída funcional que este contrato passa a recusar. Só esses testes mudam, para o comportamento desta spec (exit 4 sem jornadas curadas e saída funcional no contrato).

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `scripts/atlas.py`: as regras de `tier: test` e de jornadas curadas para a capacidade `functional`, `--journey`, a validação própria da saída de `functional`, a verificação `functional` do `verify compare` e o `ATLAS_VERSION`.
- `assets/probes/suite.py` (novo): o adaptador e a leitura do arquivo de jornadas.
- `references/probes/suite.md` (novo): o adaptador, o arquivo de jornadas, o protocolo `ATLAS-FAILED-STEP:`, os exits da suíte e os exemplos `json probe@2 functional ...`.
- `references/probes.md`: a capacidade `functional`, as regras de `tier: test` e de jornadas, `--journey` e o ponteiro para `probes/suite.md`.
- `references/verify.md`: `--functional`, `--journey` e a verificação.
- `references/collector-contract.md` e `references/collectors/generic.md`: o atributo `journeys`, com o exemplo no arquivo de fatos.
- `SKILL.md`, CHANGELOG da boson-atlas e `plugin.json`.
- Testes: `tests/test_probe_functional.py` (núcleo), `tests/test_probe_suite.py` (adaptador), `tests/test_verify_functional.py`, `tests/fixtures/functional/` (suítes falsas, arquivos de jornadas, atlas e configuração) e a regra de arquitetura que põe `assets/probes/suite.py` sob "só biblioteca padrão" e "processos sem shell" (`tests/architecture_rules.py`, verificada por `tests/test_architecture.py`).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Ambiente de produção | `tier: production` ou sem `tier`, com e sem `--confirm-production` | exit 4 com a mensagem de `tier: test`; nenhum processo, nem `--describe`; `probes.log` com `not_test_tier` | UT-01, IT-01 |
| Sem jornadas curadas | `journeys` ausente ou vazia | exit 4 "sem jornadas curadas"; `probes.log` com `no_journeys` | UT-02 |
| `--journey` | id curado; id não curado; id fora da regra; capacidade sem `journeys` em `inputs` | só as escolhidas vão em `target.journeys`; exit 2 nos outros três | UT-02 |
| Entrada do adaptador | jornadas curadas e `access.urls.dev` | `target.journeys` com os ids na ordem curada e `target.urls.base_url`; nenhum campo de cluster nem comando | UT-03, CT-01 |
| Sem URL base | sem `access.urls.<ambiente>` | exit 4 "sem acesso local: urls"; `probes.log` com `no_access`/`urls` | UT-03 |
| Saída fora do contrato | id a mais, faltando ou repetido, chave a mais, `result` fora da lista, `failed_steps` longo | exit 1 "saída fora do contrato", sem itens | UT-04, CT-01 |
| Máscara | URL base e valor da credencial na saída | `[REDACTED]` em itens e `message`; nada no `probes.log` | UT-04 |
| Arquivo de jornadas | válido; sem `--journeys-file`; ausente; JSON inválido; chave a mais; comando em texto ou com pasta relativa; `cwd` relativo; `timeout` fora; credencial fora da regra | roda; `status: error` com a mensagem do contrato, sem o valor, e nenhuma jornada roda | UT-05 |
| Jornada sem comando | id pedido que não está no arquivo; jornada do arquivo não pedida | `skipped` com o motivo; a não pedida nunca roda | UT-05, IT-01 |
| Suíte passou, falhou ou pulou | exit 0, exit 1 com linhas `ATLAS-FAILED-STEP:`, exit 77 | `passed`; `failed` com os passos (até 5, 200 caracteres); `skipped` | UT-06, IT-01 |
| Suíte não encontrada, lenta ou sem credencial | executável ausente, tempo esgotado, credencial não recebida | `skipped`, `failed` "tempo esgotado" com o grupo encerrado, `skipped` | UT-06 |
| Ambiente da suíte | credenciais de outra jornada e variáveis do shell | a suíte vê só o ambiente mínimo, as `ATLAS_*` e as credenciais da própria jornada; argv sem shell | UT-06 |
| Verify sem `--functional` | `compare` de hoje | nenhuma verificação `functional`; `--journey` sozinho → exit 2 | CH-01, UT-07 |
| Verify com `--functional` | passou, falhou, pulou, recusada, arquivo inválido, fora de teste, entrega não ok | `ok`, `failed`, `not_verified` com o motivo; fora de teste e sem entrega nada roda; veredito pelas regras do `verify@2` | UT-07, IT-02 |
| Contrato do resultado | `--json` com a verificação `functional` | validado pelo `validate_verify_result` do `verify@2` | CT-01 |
| Atlas como dado | coletores da skill e o arquivo de fatos | só o `generic` (arquivo da pessoa) traz `journeys`; o atlas fica intocado; o `suite.py` passa nas regras de arquitetura | UT-08 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dados o `probe` das capacidades de hoje e o `verify compare` sem `--functional`, quando rodam com os dublês atuais, então a saída, os exits e o `probes.log` ficam iguais (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado um atlas com `prod` em `tier: production` e `stage` sem `tier`, quando `probe functional run` roda em cada um, com e sem `--confirm-production`, então sai com 4 e a mensagem de `tier: test`, o adaptador falso não recebe nenhuma chamada (nem `--describe`, pelo registro de argv) e o `probes.log` tem uma linha `refused` com `reason: not_test_tier`. Em `dev` (`tier: test`) o adaptador roda.
- **UT-02** — Dado o nó `service:api`:
  - sem `journeys`, ou com lista vazia, o probe sai com 4 "sem jornadas curadas para api (attrs.journeys)", e o `probes.log` tem `reason: no_journeys`;
  - com `["checkout", "login"]` e `--journey login`, só `login` vai em `target.journeys`; `--journey refund` sai com 2 "jornada refund não curada para api"; `--journey "-x"` sai com 2 "--journey inválido";
  - `--journey checkout` numa capacidade sem `journeys` em `inputs` sai com 2 "--journey não é aceito por <capacidade>".
- **UT-03** — Dadas as jornadas curadas `checkout` e `login` e `access.urls.dev`, quando o probe roda com um adaptador falso que grava o stdin, então a entrada passa no validador do `probe@2`, `target.journeys` é `["checkout", "login"]`, `target.urls.base_url` é a de `dev`, e a entrada não tem `clusters`, `context`, `namespace`, `workloads` nem nenhum comando. Sem `access.urls.dev`, o probe sai com 4 "sem acesso local: urls", o adaptador não roda e o `probes.log` tem `reason: no_access` e `access: urls`.
- **UT-04** — Dado um adaptador falso que devolve saídas fora do contrato (id que não estava na entrada, id faltando, id repetido, chave `stdout`, `result: "ok"`, seis `failed_steps`, um passo com 201 caracteres), quando o probe roda, então sai com 1 "saída fora do contrato" e sem itens. Dada uma saída válida com a URL base e o valor de `CHECKOUT_TEST_PASSWORD` dentro de `failed_steps` e da `message`, a saída impressa e o `--json` trazem `[REDACTED]`, e o `probes.log` não tem nem a URL, nem a credencial, nem os passos.
- **UT-05** — Dado o adaptador `suite` rodando direto com uma entrada válida:
  - sem `--journeys-file` → `status: error` "sem arquivo de jornadas (--journeys-file)";
  - arquivo ausente, JSON inválido, chave `env` numa jornada, `command` em texto, `command` com `./x.sh`, `cwd` relativo, `timeout` 0 e 301, credencial `minha-senha` → `status: error` "arquivo de jornadas inválido: <campo> — <motivo>", sem o valor, e nenhuma suíte roda (o arquivo que as suítes falsas gravam não muda);
  - com o arquivo só de `checkout` e a entrada `["checkout", "login"]`, `login` sai `skipped` "jornada sem comando neste arquivo de jornadas", e uma jornada `refund` do arquivo, que não foi pedida, nunca roda.
- **UT-06** — Dado o adaptador `suite` com suítes falsas em Python:
  - exit 0 → `passed`, com `duration_seconds` maior ou igual a 0;
  - exit 1 com três linhas `ATLAS-FAILED-STEP:` e outras linhas quaisquer → `failed` com só os três passos, sem o prefixo; com sete linhas, só as cinco primeiras, cada uma cortada em 200;
  - exit 2 sem nenhuma linha do protocolo → `failed` com `["a suíte saiu com 2"]`;
  - exit 77 → `skipped`; executável inexistente → `skipped` "comando da suíte não encontrado"; credencial da jornada ausente do ambiente do adaptador → `skipped` "credencial não recebida: CHECKOUT_TEST_USER";
  - suíte que dorme além do `timeout` → `failed` "tempo esgotado (<n>s)", e o processo filho dela não fica vivo;
  - a suíte grava o próprio ambiente e argv: só o ambiente mínimo, `ATLAS_SERVICE`, `ATLAS_ENVIRONMENT`, `ATLAS_JOURNEY`, `ATLAS_BASE_URL` e as credenciais da própria jornada (não as de outra jornada, não as variáveis do shell), e o argv é a lista do arquivo, sem shell.
- **UT-07** — Dado o `verify compare` com probes falsas de `runtime` e de `functional`:
  - sem `--functional`, não há verificação `functional`; `--journey` sem `--functional` sai com 2;
  - com `--functional` em `dev` (`tier: test`): todas `passed` → `functional` ok e veredito `passou`; uma `failed` → `failed`, com a jornada e os passos na evidência, e veredito `degradou`; uma `skipped` e nenhuma `failed` → `not_verified` "jornada pulada: login", veredito `inconclusivo`; probe com erro (arquivo de jornadas inválido) ou recusada (sem URL base) → `not_verified` com o motivo;
  - em `prod` com `--confirm-production`: `functional` `not_verified` "validação funcional só em tier: test", e o adaptador `functional` não recebe nenhuma chamada nem entra no `probes.log`;
  - com `delivery` `failed`: `functional` `not_verified` "entrega não confirmada…", sem rodar;
  - a verificação traz `resource: null` e passa no `validate_verify_result`.
- **UT-08** — Os coletores que vêm com a skill (`github`, `argocd`, `aws`) nunca emitem `journeys`, e o `generic` copia `journeys` do arquivo de fatos. Em todos os testes desta spec, a árvore da pasta do atlas tem o mesmo hash antes e depois. A regra de arquitetura põe `assets/probes/suite.py` sob "só biblioteca padrão" e "processos sem shell", e falha com um `shell=True` de exemplo.

### 7.3 Testes de Integração
- **IT-01** — Num atlas temporário (com `journeys: ["checkout", "login"]` no arquivo de fatos do `generic`, `scan` e `build` de verdade, `dev` em `tier: test` e `prod` em `tier: production`), com a configuração local (`access.urls.dev` e o adaptador `suite` com `--journeys-file` apontando para um arquivo temporário) em `ATLAS_CONFIG_HOME` temporário, e o adaptador `suite` da skill de verdade rodando duas suítes falsas em Python (uma passa e outra falha com dois passos), quando `atlas.py probe functional run --service api --env dev --json` roda como processo, então a saída traz `checkout` `passed` e `login` `failed` com os dois passos, exit 0. Tirando `login` do arquivo de jornadas, `login` sai `skipped`. Com `--env prod --confirm-production`, sai com 4, e o arquivo que as suítes falsas gravam a cada execução não muda.
- **IT-02** — No mesmo atlas (sem recurso ligado ao deployment, para que `dependencies` e `signals` não entrem), com o adaptador `kubernetes` e o dublê de kubectl em estado saudável, quando `verify snapshot` e depois `verify compare --functional --json` rodam como processo, então o veredito é `passou` com as duas suítes passando e `degradou` (exit 1) com a suíte de `login` falhando, e a verificação `functional` traz as jornadas na evidência.

### 7.4 Testes de Contrato
- **CT-01** — Os blocos `json probe@2 functional describe|input|output valid|invalid` de `references/probes/suite.md` passam (os `valid`) e falham (os `invalid`) nos validadores do núcleo, inclusive a validação própria da saída de `functional`; o `--describe` do `suite.py` é o bloco `describe valid`; a saída real do `suite.py` no IT-01 passa no validador; o exemplo de arquivo de jornadas de `references/probes/suite.md` passa na validação do adaptador; o exemplo `verify@2` com a verificação `functional` em `references/verify.md` passa no `validate_verify_result`, e o mesmo exemplo com `"result": "ok"` numa jornada é recusado.

### 7.5 Testes E2E
- N/A — CLI sem jornada interativa de usuário; IT-01 e IT-02 rodam o `probe` e o `verify` como processo, de ponta a ponta, com o adaptador real e suítes falsas.

### 7.6 Outros
- N/A — a segurança (só `tier: test`, sem shell, máscara) está nos testes unitários e de arquitetura acima.

**Dublês e dados de teste:**
- Suítes falsas em Python, que gravam argv e ambiente num arquivo temporário e saem com o código pedido.
- Arquivos de jornadas temporários, válidos e inválidos.
- Adaptadores falsos de `tests/fixtures/fake-probes`, com registro de argv e stdin.
- Dublê de kubectl da SPEC-0089.
- Atlas, `HOME`, `ATLAS_CONFIG_HOME` e `XDG_CONFIG_HOME` temporários; nomes `acme`, `api`, `checkout`, `login`, `refund`, `dev`, `prod`; URL `https://dev.acme.example`.
- Sem rede, sem ferramenta de teste de verdade.

**Ambiente de execução:** local e CI (`python3 -m unittest discover -s skills/boson-atlas/tests`, Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin. Nada muda sem `probes.enabled: true`, o adaptador `suite` declarado com `--journeys-file` e `verbs: [run]`, `access.urls` do ambiente e `journeys` no atlas. No `verify`, só com `--functional`; na gluon-spec, só com `delivery_check.functional: true` (SPEC-0105).
- **Dados/schema:** atributo opcional `journeys` no `service` (contrato `@1`) e o arquivo de jornadas do adaptador, fora do atlas e da configuração. Nenhuma migração.
- **Compatibilidade:**
  - versões anteriores guardam `journeys` no nó, sem uso;
  - a configuração local não ganha chave nova;
  - o `verify@2` ganha um valor de `check`; quem lê só `verdict`, `checks` e `suggestion` segue igual.
- **Observabilidade:** o resultado por jornada no probe e na evidência do `verify`; o `probes.log` registra cada execução e cada recusa, sem resultado.
- **Rollback:** voltar a versão do plugin e tirar o adaptador `suite` da configuração local. O atributo `journeys` no atlas e o arquivo de jornadas podem ficar.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Onde fica o mapa jornada → comando? — Num arquivo de jornadas local, lido só pelo adaptador `suite`, com o caminho passado em `--journeys-file` no `command` do adaptador. O núcleo continua genérico e só entrega os ids (Architect, 2026-11-24, decisão da revisão cruzada)
- [x] Qual o formato do arquivo de jornadas? — JSON, porque o adaptador é só biblioteca padrão e não tem leitor de YAML. O `references/probes/suite.md` traz o exemplo (Architect, 2026-11-24, recomendado)
- [x] De onde vem a URL base do ambiente? — De `access.urls.<ambiente>.base_url` (ADR-0025, SPEC-0096), gravada pelo `access setup` (SPEC-0104), nunca do atlas (Architect, 2026-11-24, recomendado)
- [x] Como uma jornada entra como "curada"? — Pelo arquivo de fatos do coletor `generic`, escrito por uma pessoa e aprovado no PR do atlas (modo `repo`) ou editado por ela (modo `local`), o mesmo "quem confirma" do `references/curation.md`. Nenhum coletor infere jornadas e o `curate` não muda (Architect, 2026-11-24, recomendado)
- [x] Como a suíte diz o resultado e os passos que falharam? — Pelo exit (0 passou, 77 pulou, outro falhou) e pelas linhas `ATLAS-FAILED-STEP: <texto>` da saída padrão. Nenhuma outra linha sai, para não vazar dado de teste (Architect, 2026-11-24, recomendado)
- [x] Jornada `skipped` deixa a verificação `ok`? — Não: fica `not_verified` (veredito `inconclusivo`), porque jornada pulada não é prova (ADR-0026) (Architect, 2026-11-24, recomendado)
- [x] Roda a jornada com a entrega não confirmada? — Não: com `delivery` diferente de `ok`, a `functional` fica `not_verified` sem rodar, porque testaria outra versão (Architect, 2026-11-24, recomendado)
- [x] Um resultado `failed` muda o exit do `probe`? — Não: o probe informa (exit 0) e o `verify` julga, como nas outras capacidades (Architect, 2026-11-24, recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 0: Caracterização**
- [ ] CH-01 escrito(s) com a tag `SPEC-0103:<ID>`, passando no código atual, commitado(s) antes de qualquer mudança

**Fase 1: Contrato e implementação**
- [ ] Red: UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, UT-07, UT-08, IT-01, IT-02, CT-01 com a tag `SPEC-0103:<ID>`, falhando pelo motivo certo
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
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=59, skipped=1)) — 07f8dbf | 2026-11-26 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (Installed 1 package in 4ms) — 3094697 | 2026-11-26 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0103`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-26 | `test_probe_resource.py` nos `touches` | SPEC_DEFECT do Test-writer: três testes da SPEC-0096 contradizem as regras desta spec | SPEC-0096 (só testes) | thomas, 2026-11-26 (piloto automático com o recomendado) |
