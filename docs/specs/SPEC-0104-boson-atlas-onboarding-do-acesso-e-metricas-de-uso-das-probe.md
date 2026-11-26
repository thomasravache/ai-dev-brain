---
id: SPEC-0104
title: "boson-atlas: onboarding do acesso e métricas de uso das probes"
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
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/references/config.md, skills/boson-atlas/references/probes.md, skills/boson-atlas/references/access-setup.md, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, skills/boson-atlas/tests/test_access_setup.py, skills/boson-atlas/tests/test_probe_stats.py, skills/boson-atlas/tests/test_probe.py, skills/boson-atlas/tests/test_probe_resource.py, skills/boson-atlas/tests/fixtures/access-setup/**, skills/boson-atlas/tests/fixtures/probe-stats/**, skills/boson-atlas/tests/architecture_rules.py, skills/boson-atlas/tests/test_architecture.py, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0023, ADR-0025]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-24
---

# SPEC-0104 — boson-atlas: onboarding do acesso e métricas de uso das probes

> Origem: épico SPEC-0095. Thomas pediu (2026-11-24) que a pessoa configure o acesso por perguntas simples e que as métricas de uso mostrem o que ainda falta mapear. Hoje o acesso local (`access.clusters` da SPEC-0087, `access.cloud` e `access.databases` da SPEC-0096) é escrito à mão no `config.yml`.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Duas peças pequenas que fecham o ciclo do acesso local:
- **`atlas.py access setup`**: um onboarding em linguagem simples. Pergunta, para cada cluster, ambiente e banco do grafo, qual contexto do kubectl, qual profile da nuvem, qual URL base do ambiente de teste e, para cada banco PostgreSQL, qual usuário só de leitura, banco e arquivo de senhas esta máquina usa. Mostra o que já detectou (só nomes), deixa pular e grava em `access.*`. Depois de gravar, nunca imprime os valores. Tem um modo não interativo, por opções, para testes e scripts.
- **`atlas.py probes stats`** e as sugestões do `doctor`: contam o `probes.log` (verificadas, recusadas por motivo, sem acesso por tipo, sem adaptador por capacidade, alvo que o atlas não liga) e propõem o que falta configurar ou mapear. É sempre proposta; nada é alterado sozinho.

## 2. Motivação & Escopo
**Motivação:** sem acesso local, as probes de recursos (SPEC-0096) e o `verify@2` (SPEC-0102) ficam "não verificado". Escrever o YAML à mão exige saber as chaves, os nomes do grafo e os nomes locais, e é onde a pessoa desiste. Além disso, ninguém sabe hoje quais verificações deixaram de rodar por falta de acesso, de adaptador ou de mapa: o `probes.log` guarda as recusas, mas sem o motivo e sem uma leitura agregada. O épico mede o sucesso exatamente por esses números (SPEC-0095, seção 5).

**Objetivos (dentro do escopo):**
- **`access setup` interativo:**
  - lê do `graph.json` os clusters, os ambientes com recursos, os ambientes `tier: test` e os `datastore` de PostgreSQL;
  - detecta, só lendo, os contextos do kubeconfig (`kubectl config get-contexts -o name`) e os profiles do arquivo de configuração da AWS CLI (só os nomes das seções);
  - pergunta em linguagem simples, sugere o detectado e deixa pular (Enter) ou manter o valor atual;
  - recomenda papel e usuário só de leitura;
  - mostra o resumo do que vai gravar (só `definido` ou `não definido`) e grava só depois do "sim".
- **`access setup` não interativo**, por opções `--cluster`, `--cloud`, `--db-user`, `--db-name` e `--db-passfile`, com `--dry-run`.
- **URL base do ambiente:** o setup pergunta e grava `access.urls.<ambiente>.base_url`, chave definida e validada pela SPEC-0096, e as métricas e sugestões contam as recusas por falta dela.
- **Motivo no `probes.log`:** cada linha que não é `ok` ganha `reason` (um código fechado) e, nas recusas por acesso, `access` (`cluster`, `cloud`, `database` ou `urls`). Os códigos são do núcleo, nunca do texto do adaptador. A regra de chaves fechadas do `write_probe_log` passa a ser: as de hoje, mais `resource` e `commit` (SPEC-0096), mais `reason` e `access`.
- **`atlas.py probes stats`** (`--since`, `--json`): as contagens do `probes.log` do atlas escolhido e as sugestões.
- **Sugestões no `doctor`:** uma linha `AVISO uso das probes — …` por sugestão dos últimos 30 dias, apontando o comando ou a chave.

**Não-objetivos (fora do escopo):**
- **Ler segredos:** o setup nunca lê o arquivo de credenciais da nuvem, o conteúdo do kubeconfig além dos nomes de contexto, nem o conteúdo do arquivo de senhas. Só confere se o arquivo de senhas existe e as permissões dele.
- **Fazer login** na nuvem (SSO) ou testar a conexão: quem testa é a probe.
- **Criar usuário, papel ou profile.**
- **Corrigir sozinho** a configuração ou o atlas a partir das métricas.
- **Mandar as métricas para fora da máquina:** ficam no `probes.log` local.
- **Os comandos das jornadas funcionais** (o arquivo de jornadas do adaptador `suite`, `--journeys-file`, SPEC-0103): ficam fora do setup nesta onda. A URL base do ambiente (`access.urls`) entra.

## 3. Dependências
- **Implementações necessárias:** SPEC-0096. As chaves `access.cloud` e `access.databases`, a validação delas, a máscara e o caminho das recusas `sem acesso local: <tipo>` (exit 4) vêm de lá; Lá também está `access.urls.<ambiente>.base_url` (validação, `definido` no `config` e no `doctor`, exit 4 `sem acesso local: urls`, máscara). Esta spec só grava nessas chaves e acrescenta o motivo às linhas do registro. Pela SPEC-0096 também chega o `write_probe_log` com `resource` e `commit` e a regra de arquitetura das chaves fechadas do registro, que esta spec estende.
- **Contratos consumidos:** N/A (vêm com a implementação).
- **Pré-requisitos externos:** N/A. `kubectl` e o arquivo de configuração da AWS CLI são opcionais: sem eles, o setup só pergunta, sem sugerir.

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **escrita da configuração local:** `cmd_init` (`init --join` mantém `access` e `probes` da entrada), com a forma de vários atlas de `references/config.md`;
- **validação do acesso:** a de `access.clusters` (SPEC-0087) e a de `access.cloud`, `access.databases` e `access.urls` (SPEC-0096), com mensagens que dizem a posição e o motivo, nunca o valor;
- **registro:** a linha do `probes.log` escrita por `run_probe` (SPEC-0088);
- **diagnóstico:** as linhas `OK|AVISO|ERRO <item> — <detalhe>` do `cmd_doctor`;
- **testes:** `tests/test_access_map.py`, `tests/test_probe.py` e a ferramenta falsa no `PATH` (`fake_kubectl.py`).

**Decisão:**
- `access setup` é um subcomando do `atlas.py`. Uma função pura monta as perguntas a partir do grafo e da detecção, e outra aplica as respostas à entrada do atlas. A entrada e a saída do terminal são injetadas, para testar sem terminal.
- A gravação reaproveita a escrita do `init` (arquivo temporário exclusivo, renomeado, permissão 0600) e muda só `access` da entrada escolhida.
- A detecção roda `kubectl` como lista de argumentos, sem shell, com timeout, e lê o arquivo de configuração da AWS CLI com o `configparser` da biblioteca padrão, pegando só os nomes das seções.
- O motivo das recusas é escrito por `run_probe` no mesmo lugar em que a linha já é escrita. `probes stats` e o `doctor` leem o arquivo e agregam por chaves que já não têm valor sensível.

**Justificativa:**
- O onboarding é a parte que só a pessoa sabe responder, como o nome local do contexto ou do profile (ADR-0025, consequência "ruim"), e as perguntas vêm do grafo, então só se pergunta o que o atlas usa.
- As métricas saem de um arquivo que já existe e já é seguro (sem resultado nem acesso). Falta só o motivo, que o núcleo conhece.

**Desvio do padrão existente:** nenhum.

**Alternativas descartadas:**
- **Perguntas dentro do `init`:** o `init` liga a máquina ao atlas antes do `build`; sem grafo, não há o que perguntar. O setup roda depois e pode ser repetido.
- **Ler o `~/.kube/config` direto:** exigiria um parser de YAML e leria o arquivo inteiro (com certificados e tokens). O `kubectl config get-contexts -o name` devolve só os nomes.
- **Motivo da recusa pelo texto da mensagem:** frágil e arriscado, porque a mensagem pode mudar de texto. Um código fechado é estável e não carrega valor.
- **Métricas fora da máquina** (enviadas para o atlas): o `probes.log` é local por regra (ADR-0023).

**ADRs:** ADR-0010 (credencial só por nome), ADR-0023 (registro local, sem resultado), ADR-0025 (acesso local por referência, nunca impresso).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:**
  - a detecção do `kubectl` tem timeout de 10 s; estourou, o setup segue sem sugestões de contexto;
  - `probes stats` e o `doctor` leem o `probes.log` linha a linha, sem carregar tudo; o `doctor` olha só os últimos 30 dias.
- **Segurança:**
  - só leitura no ambiente: o único processo é `kubectl config get-contexts -o name`, como lista e sem shell;
  - do arquivo de configuração da AWS CLI (`AWS_CONFIG_FILE` ou `~/.aws/config`) saem só os nomes das seções; o arquivo de credenciais nunca é aberto;
  - do arquivo de senhas, só `os.stat` (existe, é arquivo, permissão); nunca é aberto;
  - depois de gravar, nenhuma saída (setup, `config`, `doctor`, `probes stats`, `probes.log`) mostra o contexto, o profile, o usuário, o nome do banco ou o caminho do arquivo de senhas;
  - as opções do modo não interativo também nunca são ecoadas;
  - um valor inválido sai com a posição e o motivo, sem o valor.
- **Privacidade e dados pessoais:** os nomes locais podem ter id de conta ou nome de pessoa. Por isso só aparecem durante a pergunta, no terminal da própria pessoa, e nunca em log ou JSON.
- **Disponibilidade e resiliência:**
  - sem `kubectl`, sem o arquivo da AWS CLI ou com eles ilegíveis, o setup pergunta sem sugerir;
  - linha malformada no `probes.log` é pulada e contada (`skipped_lines`);
  - linha antiga, sem `reason`, conta como `unknown`.
- **Acessibilidade (UI):** N/A — CLI; as perguntas são texto simples, uma por linha, sem cor obrigatória.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** os subcomandos `access setup` e `probes stats`, as chaves `reason` e `access` do `probes.log` e as linhas novas do `doctor`.

```text
atlas.py access setup [--atlas X]                                    # interativo (exige terminal)
atlas.py access setup [--atlas X] [--dry-run]
    [--cluster <cluster>=<contexto>]... [--cloud <ambiente>=<profile>]...
    [--db-user <datastore>=<usuário>]... [--db-name <datastore>=<banco>]... [--db-passfile <datastore>=<caminho>]...
    [--base-url <ambiente>=<url>]...
  com qualquer uma das opções → não interativo; sem opções e sem terminal no stdin → exit 2
    "access setup interativo precisa de um terminal; use --cluster, --cloud, --base-url ou --db-*"
  ordem: 1. configuração local (3) · 2. graph.json ausente → exit 2 "sem graph.json: rode atlas.py build"
         3. nomes: <cluster> precisa ser cluster:<n> do grafo, <ambiente> environment:<n>, <datastore> datastore:<id>
            → senão exit 2 "<tipo> <nome> não está no atlas" (nome do atlas ou da opção, dentro da regra de nome;
            fora da regra, "opção --cloud: item <i> inválido — nome fora da regra")
         4. valores: as regras de access.* (SPEC-0087; cloud, databases e urls da SPEC-0096), pela mesma função → exit 2 "--cloud: item <i> inválido — <motivo>",
            sem o valor; --db-* de um datastore precisa trazer user, database e passfile juntos, ou já tê-los na
            entrada → senão exit 2 "datastore <id>: faltam <campos>"
         5. grava (ou, com --dry-run, só mostra o resumo) e sai com 0
  perguntas do modo interativo, nesta ordem, só para o que o grafo usa:
    clusters de algum deployment:
      "Qual o contexto do kubectl do cluster <cluster>? Detectados: 1) <ctx> 2) <ctx> — número, nome ou Enter para pular"
    ambientes com recurso (datastore, queue, topic, bucket) ligado a um deployment:
      "Qual profile da AWS você usa no ambiente <ambiente>? (use um profile só de leitura) Detectados: 1) … —
       número, nome ou Enter para pular"
    ambientes tier: test (environments: do atlas-config.yml):
      "Qual a URL base do ambiente <ambiente> (para as jornadas funcionais em teste)? — URL http(s) ou Enter para
       pular"
    cada datastore com engine postgres ou aurora-postgresql (um bloco por banco):
      "Qual usuário só de leitura do banco <datastore>?" · "Qual o nome do banco?" ·
      "Qual o arquivo de senhas (.pgpass) desse usuário?" (sugere ~/.pgpass quando existe)
    valor já definido: "já definido — Enter mantém, '-' apaga, ou digite outro" (o valor não aparece)
    resposta inválida: repete a pergunta com o motivo, até 3 vezes; depois, pula
    sugestão de detectado: o contexto cujo nome contém o nome do cluster; o profile cujo nome contém o do ambiente
  avisos (não impedem gravar):
    "arquivo de senhas de <datastore> não encontrado"
    "arquivo de senhas de <datastore> legível por outros: o psql ignora (use chmod 600)"
  resumo antes de gravar (e no --dry-run), uma linha por item, nunca o valor:
    "access.clusters.<cluster>: definido | não definido | mantido | apagado"
    "access.cloud.<ambiente>: …"  "access.urls.<ambiente>: …"  "access.databases.<datastore>: …"
    interativo: "Gravar? [s/N]" — só "s" ou "sim" grava; senão, nada muda e sai com 0 "nada gravado"
  gravação: só a chave access da entrada do atlas escolhido; o resto do config.yml fica igual; arquivo temporário
    exclusivo e renomeado, permissão 0600
  exits: 0 gravado, nada gravado ou dry-run · 2 argumento, nome ou valor inválido · 3 sem configuração local

detecção (só leitura):
  kubectl: ["kubectl", "config", "get-contexts", "-o", "name"], timeout 10 s, ambiente do shell (KUBECONFIG
    inclusive); ausente, erro ou tempo esgotado → nenhuma sugestão
  AWS: AWS_CONFIG_FILE ou ~/.aws/config, configparser; "[default]" → default, "[profile x]" → x; outras seções
    ignoradas; nunca abre AWS_SHARED_CREDENTIALS_FILE nem ~/.aws/credentials

probes.log (linha de hoje + chaves novas, só fora de "ok"):
  "reason": código fechado
    refused  → no_adapter | verb_not_allowed | production_unconfirmed | no_access | not_test_tier | no_journeys
               (not_test_tier e no_journeys são usados pela capacidade functional da SPEC-0103)
    invalid  → invalid_args | no_deployment | not_linked | invalid_target
    error    → adapter_failed | timeout | contract
  "access": cluster | cloud | database | urls   (só com reason no_access)
  com probes desligadas, nada é registrado (como hoje)
  chaves fechadas do write_probe_log: at, atlas, service, environment, capability, verb, adapter, status, exit,
    confirmed_production (hoje) + resource, commit (SPEC-0096) + reason, access; a regra de arquitetura da SPEC-0096
    (tests/architecture_rules.py) passa a aceitar exatamente esse conjunto

atlas.py probes stats [--since 30d] [--json] [--atlas X]
  --since: <n>d ou <n>h, de 1h a 365d → senão exit 2
  lê o probes.log da pasta da configuração local; só as linhas do atlas escolhido ("atlas") e dentro de --since
  --json (chaves fechadas, contrato probe-stats@1):
    {"contract": "probe-stats@1", "atlas": "acme", "since": "30d", "total": 12,
     "by_status": {"ok": 7, "error": 1, "invalid": 1, "refused": 3},
     "refused": {"no_access": 3},
     "no_access": {"cluster": 0, "cloud": 3, "database": 0, "urls": 0},
     "no_adapter": {"<capacidade>": <n>},
     "by_capability": {"<capacidade>": {"ok": n, "error": n, "invalid": n, "refused": n}},
     "skipped_lines": 0,
     "suggestions": ["3 probe(s) recusada(s) por falta de access.cloud em dev: rode atlas.py access setup"]}
    refused e no_adapter só com contagens maiores que 0; reason ausente conta como "unknown"
  sem --json: Markdown com as mesmas contagens e as sugestões
  sem probes.log: total 0, sem sugestões, exit 0
  exits: 0 · 2 --since inválido · 3 sem configuração local

sugestões (probes stats e doctor), agregadas por chave, uma por grupo, ordenadas por contagem:
  no_access cluster, ambiente A    → "N probe(s) recusada(s) por falta de access.clusters em A: rode atlas.py access setup"
  no_access cloud, ambiente A      → "N probe(s) recusada(s) por falta de access.cloud em A: rode atlas.py access setup"
  no_access database, recurso R    → "N probe(s) recusada(s) por falta de access.databases para R: rode atlas.py access setup"
  no_access urls, ambiente A       → "N probe(s) recusada(s) por falta de access.urls em A: rode atlas.py access setup"
  no_journeys, serviço S           → "N probe(s) funcional(is) sem jornadas curadas para S: declare journeys no
                                       arquivo de fatos do coletor generic (references/collectors/generic.md)"
  no_adapter, capacidade C         → "N probe(s) sem adaptador para C: declare um em probes.adapters (references/probes.md)"
  verb_not_allowed, adaptador D    → "N probe(s) com verbo não liberado em D: libere em probes.adapters.D.verbs se for de leitura"
  not_linked, serviço S, ambiente A → "N probe(s) em recurso não ligado a S em A: complete o mapa do atlas (coletor aws ou fatos do generic)"
  no_deployment, serviço S, ambiente A → "N probe(s) sem deployment de S em A: mapeie o deployment no atlas"
  (production_unconfirmed, not_test_tier, invalid_args e os de error não viram sugestão: são escolhas ou falhas,
   não falta de mapa ou acesso)
  todos os nomes vêm do registro (do atlas ou da configuração), nunca valor de acesso

doctor (com o probes.log da pasta local e alguma sugestão nos últimos 30 dias):
  "AVISO uso das probes — <sugestão>" (uma linha por sugestão, até 5; "… e mais N: rode atlas.py probes stats")
  sem probes.log ou sem sugestão → nenhuma linha (o doctor fica como antes); nunca muda o exit por isso
  doctor --json: cada uma como um check {"item": "uso das probes", "status": "AVISO", "detail": "<sugestão>"}
```

**Esclarecimentos (Emenda v2):**
- `test_probe.py` (SPEC-0088 UT-05) e `test_probe_resource.py` (SPEC-0096 CH-01) entram nos `touches`: eles exigem que as linhas recusadas e de erro do `probes.log` tenham exatamente as chaves antigas, e este contrato acrescenta `reason` (e `access` em `no_access`) fora do `ok`. Só essas asserções mudam, para o conjunto novo de `PROBE_LOG_KEYS`.

**Design:** N/A — sem interface gráfica; as perguntas estão no contrato.

**Arquivos/módulos afetados:**
- `scripts/atlas.py`: os subcomandos `access setup` e `probes stats`, a detecção, a escrita de `access` (validada pelo `validate_access` da SPEC-0096), o `reason` e o `access` no registro, as sugestões do `doctor`, o validador `validate_probe_stats` e o `ATLAS_VERSION`.
- `references/access-setup.md` (novo): o passo a passo do onboarding, as perguntas e o modo não interativo.
- `references/config.md`: ponteiro para o setup na seção `access`.
- `references/probes.md`: `reason` e `access` no registro, `probes stats` e as sugestões, com os exemplos `json probe-stats@1 valid|invalid`.
- `SKILL.md`, CHANGELOG da boson-atlas e `plugin.json`.
- Testes: `tests/test_access_setup.py`, `tests/test_probe_stats.py`, `tests/fixtures/access-setup/` (kubectl falso de contextos, `.aws/config`, grafo e configurações), `tests/fixtures/probe-stats/` (`probes.log` de fixture e o adaptador falso de mensageria) e a regra de chaves fechadas do registro em `tests/architecture_rules.py`, verificada por `tests/test_architecture.py`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Detecção | `kubectl` falso com 3 contextos; arquivo da AWS com `[default]` e `[profile dev-ro]` | sugestões só com os nomes; argv do kubectl exatamente o do contrato; arquivo de credenciais não aberto | UT-01 |
| Detecção indisponível | sem `kubectl`, kubectl lento ou com erro, sem arquivo da AWS | perguntas sem sugestão, sem erro | UT-01 |
| Perguntas | grafo com 2 clusters, `dev` (`tier: test`) com fila e `orders-db` postgres | uma pergunta por item que o grafo usa, na ordem (contexto, profile, URL base, banco); recomenda só leitura | UT-02 |
| Respostas interativas | número, nome, Enter, `-`, inválido 3 vezes, "N" no fim | grava o escolhido, pula, apaga, repete com o motivo, nada gravado | UT-02 |
| Não interativo | `--cluster`, `--cloud`, `--base-url` e `--db-*` válidos | grava só `access`; o resto do `config.yml` igual; 0600 | UT-03, IT-01 |
| Nome fora do atlas | cluster, ambiente ou datastore que o grafo não tem | exit 2 "<tipo> <nome> não está no atlas"; nada gravado | UT-03 |
| Valor inválido | quebra de linha, vazio, mais de 256; URL base com usuário e senha ou fora de http(s) | exit 2 com posição e motivo, sem o valor | UT-03 |
| Banco incompleto | `--db-user` sem `--db-name`/`--db-passfile` e sem valores na entrada | exit 2 "faltam <campos>" | UT-03 |
| Dry-run | `--dry-run` | só o resumo; arquivo igual byte a byte | UT-03 |
| Sem terminal | sem opções e stdin não é terminal | exit 2 com a mensagem do contrato | UT-03 |
| Sem grafo ou sem configuração | sem `graph.json`; sem `config.yml` | exit 2 "rode atlas.py build"; exit 3 | UT-03 |
| Valores nunca impressos | depois de gravar | setup, `config`, `config --json`, `doctor`, `probes stats` e `probes.log` sem nenhum dos valores | UT-04, IT-01 |
| Arquivo de senhas | ausente; permissão 0644 | os dois avisos do contrato; conteúdo nunca lido | UT-05 |
| Motivo no registro | cada recusa, inválido e erro do probe | `reason` com o código certo; `access` nas recusas por acesso; `ok` sem as chaves | UT-06 |
| Chaves fechadas do registro | `write_probe_log` | só as de hoje, `resource`, `commit`, `reason` e `access`; a regra de arquitetura recusa outra | UT-06 |
| Estatísticas | log com várias linhas, outro atlas, fora da janela, malformada, sem `reason` | contagens do contrato; filtradas; `skipped_lines`; `unknown` | UT-07, CT-01 |
| `--since` inválido | `0d`, `400d`, `30x` | exit 2 | UT-07 |
| Sugestões | recusas por acesso (inclusive `urls`), adaptador, verbo, sem jornadas, não ligado, sem deployment | o texto do contrato por grupo; as outras não viram sugestão | UT-07, UT-08 |
| Doctor | log com sugestões; sem log | linhas `AVISO uso das probes`, até 5 e o resto resumido; sem linha; exit igual; nada gravado | UT-08, IT-01 |
| Registro de hoje | `probes.log` e comandos sem as opções novas | linhas `ok` iguais; comandos iguais | CH-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dado o `atlas.py` de hoje, quando `probe` dá `ok` e `config`, `doctor` e `init --join` rodam sem `probes.log` com recusas, então a linha `ok` do registro tem as mesmas chaves, o `doctor` não ganha linha nova e o `init --join` mantém o `access` da entrada (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dados um `kubectl` falso no `PATH` que imprime `ctx-dev`, `ctx-prod` e `arn:aws:eks:us-east-1:123456789012:cluster/dev` e grava o argv, e um `HOME` temporário com `.aws/config` (`[default]`, `[profile dev-ro]`, `[sso-session x]`) e `.aws/credentials` sem permissão de leitura, quando a detecção roda, então os contextos são os três nomes, os profiles são `default` e `dev-ro`, o argv gravado é `config get-contexts -o name` e nada falha por causa do arquivo de credenciais. Sem `kubectl` no `PATH`, com um `kubectl` que sai com 1 ou que dorme além do timeout, e sem `.aws/config`, as listas vêm vazias, sem exceção.
- **UT-02** — Dados um grafo com `cluster:cluster-dev` e `cluster:cluster-prod`, `environment:dev` com `queue:orders` ligada ao deployment e `datastore:orders-db` com `engine: postgres`, e uma entrada falsa de terminal, quando o setup interativo roda, então:
  - as perguntas saem na ordem do contrato (contexto por cluster, profile por ambiente com recurso, URL base de `dev` por ser `tier: test`, e o bloco usuário, banco e arquivo de senhas de `orders-db`), com as sugestões numeradas e a recomendação de só leitura;
  - "1" escolhe o primeiro detectado, um nome digitado vale como está, Enter pula, `-` apaga um valor existente e "já definido" não mostra o valor;
  - três respostas inválidas seguidas pulam o item, com o motivo a cada vez;
  - "N" no "Gravar?" não muda o arquivo e sai com 0 "nada gravado".
- **UT-03** — No modo não interativo:
  - `--cluster cluster-dev=ctx-dev --cloud dev=dev-ro --base-url dev=https://dev.acme.example --db-user orders-db=reader --db-name orders-db=orders --db-passfile orders-db=<tmp>/.pgpass` grava os quatro blocos em `access`, mantém `atlas`, `credentials` e `probes` da entrada e as outras entradas iguais, e o arquivo fica com 0600;
  - `--cloud qa=x` com `qa` fora do grafo → exit 2 "ambiente qa não está no atlas";
  - um profile com quebra de linha → exit 2 "--cloud: item 1 inválido — …" sem o valor; `--base-url dev=https://u:p@dev.acme.example` e `--base-url dev=ftp://dev.acme.example` → exit 2 pelas regras de `access.urls` da SPEC-0096, sem o valor;
  - `--db-user orders-db=reader` sozinho → exit 2 "datastore orders-db: faltam database, passfile";
  - `--dry-run` mostra o resumo e deixa o arquivo igual byte a byte;
  - sem opções e com stdin que não é terminal → exit 2 com a mensagem do contrato; sem `graph.json` → exit 2; sem configuração local → exit 3.
- **UT-04** — Depois do UT-03, as saídas de `access setup`, `config`, `config --json`, `doctor`, `doctor --json` e `probes stats --json` e o `probes.log` não contêm `ctx-dev`, `dev-ro`, `https://dev.acme.example`, `reader`, `orders` como nome de banco nem o caminho do arquivo de senhas; aparecem só `definido`, `não definido`, `mantido` ou `apagado`.
- **UT-05** — Com `--db-passfile` para um arquivo que não existe, o setup avisa "arquivo de senhas de orders-db não encontrado" e grava; com um arquivo 0644, avisa "legível por outros"; nos dois casos o arquivo nunca é aberto (o teste usa um arquivo sem permissão de leitura para o dono e confere que não há erro).
- **UT-06** — Com adaptadores falsos, quando o probe é recusado ou falha por cada motivo do contrato (sem adaptador, verbo, produção sem confirmação, sem acesso ao cluster, à nuvem e ao banco, alvo inexistente, recurso não ligado, campo inválido do atlas, adaptador com exit 1, tempo esgotado, saída fora do contrato), então a linha do `probes.log` traz o `status` de hoje, o `reason` certo e, nas recusas por acesso, o `access` certo, e nenhuma outra chave nova; uma probe `ok` não traz `reason` nem `access`. A regra de arquitetura confere que o `write_probe_log` só grava as chaves fechadas do contrato (as de hoje, `resource`, `commit`, `reason` e `access`) e falha com uma chave a mais.
- **UT-07** — Dado um `probes.log` de fixture com linhas de `acme` e de outro atlas, dentro e fora de 30 dias, uma linha malformada e linhas antigas sem `reason`, quando `probes stats --json` roda, então as contagens são as esperadas (com linhas `no_access` de `urls`, `no_journeys` e `not_test_tier` na fixture), só do atlas escolhido e da janela, `skipped_lines` é 1, as antigas contam em `refused.unknown`, e as sugestões têm o texto do contrato, uma por grupo, ordenadas por contagem. `--since 0d`, `--since 400d` e `--since 30x` saem com 2; sem `probes.log`, `total` é 0 e sai com 0.
- **UT-08** — Dado o mesmo `probes.log`, quando o `doctor` roda, então há uma linha `AVISO uso das probes — <sugestão>` por sugestão dos últimos 30 dias, até 5 e a linha de resumo depois disso; o exit do `doctor` é o mesmo de sem o log; o `config.yml` e o atlas ficam com o mesmo hash. Sem `probes.log`, ou só com linhas `ok`, nenhuma linha nova.

### 7.3 Testes de Integração
- **IT-01** — Num atlas temporário com `graph.json` de verdade (`build` sobre fixtures com `cluster-dev`, `environment:dev` com `queue:orders` ligada ao deployment de `api`), `HOME`, `ATLAS_CONFIG_HOME` e `XDG_CONFIG_HOME` temporários, um `kubectl` falso no `PATH` e um adaptador falso de mensageria que declara `access: ["cloud"]`, como processos do `atlas.py` de verdade:
  1. `probe messaging queue --service api --env dev --resource queue:orders` sai com 4 por falta de `access.cloud`;
  2. `doctor` mostra "AVISO uso das probes — 1 probe(s) recusada(s) por falta de access.cloud em dev: rode atlas.py access setup", e `probes stats --json` conta `no_access.cloud: 1`;
  3. `access setup --cloud dev=dev-ro` grava;
  4. o mesmo probe passa da recusa e o adaptador falso recebe `target.cloud.profile`;
  5. nenhuma saída dos quatro passos mostra `dev-ro`.

### 7.4 Testes de Contrato
- **CT-01** — Os blocos `json probe-stats@1 valid|invalid` de `references/probes.md` passam (os `valid`) e falham (os `invalid`, com chave a mais, `contract` errado ou contagem negativa) no `validate_probe_stats`; a saída real de `probes stats --json` do UT-07 passa no validador; o exemplo de linha do `probes.log` com `reason` e `access` usa só os códigos do contrato.

### 7.5 Testes E2E
- N/A — CLI sem jornada de usuário em interface; o modo interativo é testado com entrada e saída injetadas (UT-02) e o fluxo completo roda como processo no IT-01.

### 7.6 Outros
- N/A — os requisitos de segurança (nada impresso, nada lido além dos nomes) estão no UT-01, UT-04 e UT-05.

**Dublês e dados de teste:**
- `kubectl` falso no `PATH` (no estilo de `fake_kubectl.py`), que imprime contextos e grava o argv.
- `HOME` com `.aws/config` e `.aws/credentials` falsos, `AWS_CONFIG_FILE` apontando para temporário, `.pgpass` temporário.
- `probes.log` de fixture.
- Adaptador falso de mensageria com `access: ["cloud"]`.
- Atlas, `ATLAS_CONFIG_HOME` e `XDG_CONFIG_HOME` temporários; nomes `acme`, `api`, `orders`, `orders-db`, `dev`, `prod`; `123456789012` só como exemplo de conta que nunca deve aparecer.
- Nenhum teste toca `~/.kube`, `~/.aws` nem `~/.config` reais.

**Ambiente de execução:** local e CI (`python3 -m unittest discover -s skills/boson-atlas/tests`, Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin. O setup só roda quando chamado; as sugestões do `doctor` só aparecem com recusas no `probes.log`.
- **Dados/schema:** chaves novas `reason` e `access` nas linhas do `probes.log`, só fora de `ok`. Nenhuma migração: linhas antigas contam como `unknown`.
- **Compatibilidade:**
  - quem lê o `probes.log` por chave segue funcionando;
  - o setup grava só chaves que a SPEC-0096 já aceita, então uma máquina com a versão da SPEC-0096 lê a configuração gravada;
  - uma versão anterior à SPEC-0096 sai com 2 com `access.cloud` gravado, aviso que vai no CHANGELOG.
- **Observabilidade:** o próprio `probes stats` e as linhas do `doctor`; são a métrica de sucesso do épico ("dependências verificadas contra não verificadas" e "campos que o agente teve de descobrir").
- **Rollback:** voltar a versão do plugin. A configuração gravada pelo setup continua válida e editável à mão; as chaves novas do registro são ignoradas.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] O setup lê o kubeconfig direto? — Não: usa `kubectl config get-contexts -o name`, que devolve só os nomes, sem certificados nem tokens. Sem `kubectl`, pergunta sem sugerir (Architect, 2026-11-24, recomendado)
- [x] As sugestões do `doctor` são ERRO ou AVISO? — AVISO, sem mudar o exit: são propostas, e a falta de acesso é escolha legítima de uma máquina (Architect, 2026-11-24, recomendado)
- [x] Como saber o motivo de uma recusa antiga? — Não dá: linhas sem `reason` contam como `unknown`. O `reason` passa a ser gravado pelo núcleo, como código fechado, nunca a partir da mensagem (Architect, 2026-11-24, recomendado)
- [x] Quais bancos o setup pergunta? — Só os `datastore` com `engine` `postgres` ou `aurora-postgresql` (ADR-0026, 4a), o único adaptador de banco do épico (SPEC-0099). Outro motor entra quando tiver adaptador (Architect, 2026-11-24, recomendado)
- [x] O setup configura as jornadas funcionais (SPEC-0103)? — Só a URL base (`access.urls`), perguntada para os ambientes `tier: test`. Os comandos das jornadas pedem outro tipo de pergunta e ficam para depois, se o uso mostrar a necessidade (Architect, 2026-11-24, recomendado)
- [x] Quem cria a chave `access.urls`? — A SPEC-0096 (validação, `definido`, exit 4 `sem acesso local: urls` e máscara). Esta spec só pergunta, grava e conta as recusas (Architect, 2026-11-24, recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 0: Caracterização**
- [x] CH-01 escrito(s) com a tag `SPEC-0104:<ID>`, passando no código atual, commitado(s) antes de qualquer mudança

**Fase 1: Contrato e implementação**
- [x] Red: UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, UT-07, UT-08, IT-01, CT-01 com a tag `SPEC-0104:<ID>`, falhando pelo motivo certo
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
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=41, skipped=1)) — cf51be6 | 2026-11-25 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (Installed 1 package in 4ms) — d6fbf5b | 2026-11-25 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — bee68b3 | 2026-11-25 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED — 0 major, 5 minor (write_access perde comentários, reason padrão sem código, --cloud repetido, deployment sem cluster vira no_access, --cluster com '-') — 14ae0d4 | 2026-11-26 |
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
Onboarding do acesso local e métricas de uso das probes no boson-atlas: `atlas.py access setup` (interativo, com os contextos do `kubectl` e os profiles da AWS detectados, ou por opções) grava `access.clusters`, `access.cloud`, `access.databases` e `access.urls` na configuração local da máquina, só por nome; o `probes.log` passa a registrar `reason` (código fechado) e `access` nas recusas e falhas; `atlas.py probes stats` resume o uso por status, capacidade e acesso faltante, e o `doctor` mostra as sugestões em "uso das probes". Versões: boson-atlas 2026.11.26 e plugin 2026.11.41.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- **`scripts/atlas.py`:** `AtlasError` carrega `reason` e `access`; `PROBE_LOG_KEYS` ganha as duas chaves; detecção pelo `run_collector` com timeout de 10 s e `configparser` só nos nomes das seções; validação compartilhada (`_access_field_problem`) entre o setup e a leitura; escrita atômica com permissão 0600; `validate_probe_stats` para a saída do `stats`.
- **Documentação:** `references/access-setup.md` (novo), `references/probes.md` e `references/config.md`.
- **Emenda v2:** as asserções antigas das chaves do `probes.log` (SPEC-0088 e SPEC-0096) passam a aceitar `reason` e `access` fora do `ok`.

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A — `type: feature`. Red em cf51be6 (G1) e green em 6064038 e d6fbf5b (G2).

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| CH-01 | probe ok, config, doctor e init --join sem recusas ficam iguais | PASS | `test_access_setup.py` e `test_probe_stats.py`; G2 PASS em d6fbf5b; G4 `verify` 11/11 |
| UT-01 | detecção de contextos do kubectl e profiles da aws, só leitura | PASS | `test_access_setup.py` e `test_probe_stats.py`; G2 PASS em d6fbf5b; G4 `verify` 11/11 |
| UT-02 | modo interativo: perguntas numeradas, recusa com motivo e resumo | PASS | `test_access_setup.py` e `test_probe_stats.py`; G2 PASS em d6fbf5b; G4 `verify` 11/11 |
| UT-03 | modo não interativo: mantido, apagado e mescla dos campos do banco | PASS | `test_access_setup.py` e `test_probe_stats.py`; G2 PASS em d6fbf5b; G4 `verify` 11/11 |
| UT-04 | nenhum valor de credencial nas saídas depois do setup | PASS | `test_access_setup.py` e `test_probe_stats.py`; G2 PASS em d6fbf5b; G4 `verify` 11/11 |
| UT-05 | arquivo de senhas ausente vira aviso e grava | PASS | `test_access_setup.py` e `test_probe_stats.py`; G2 PASS em d6fbf5b; G4 `verify` 11/11 |
| UT-06 | reason e access fechados no probes.log por motivo | PASS | `test_access_setup.py` e `test_probe_stats.py`; G2 PASS em d6fbf5b; G4 `verify` 11/11 |
| UT-07 | probes stats só do atlas escolhido, na janela, ignorando linhas ruins | PASS | `test_access_setup.py` e `test_probe_stats.py`; G2 PASS em d6fbf5b; G4 `verify` 11/11 |
| UT-08 | doctor com as linhas de uso das probes e o limite de 5 sugestões | PASS | `test_access_setup.py` e `test_probe_stats.py`; G2 PASS em d6fbf5b; G4 `verify` 11/11 |
| IT-01 | setup e probe de ponta a ponta num atlas temporário | PASS | `test_access_setup.py` e `test_probe_stats.py`; G2 PASS em d6fbf5b; G4 `verify` 11/11 |
| CT-01 | blocos probe-stats@1 válidos e inválidos do probes.md | PASS | `test_access_setup.py` e `test_probe_stats.py`; G2 PASS em d6fbf5b; G4 `verify` 11/11 |

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
Sem deploy: a skill chega pelo plugin `fermion` 2026.11.41 depois do merge. O `access setup` só grava a configuração local da máquina, nunca o atlas.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
- **Minors do G4 no radar** do épico SPEC-0095:
  - `write_access` regrava o `config.yml` e perde comentários (o texto do `access-setup.md` diz que o resto fica igual);
  - `AtlasError` sem `reason` cai num padrão (código 1 vira `adapter_failed`);
  - `--cloud dev=x --cloud dev=y` fica com o último sem aviso;
  - deployment sem cluster no atlas é registrado como `no_access` e sugere `access setup`;
  - `--cluster C=-ctx` é aceito.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0104`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-25 | `test_probe.py` e `test_probe_resource.py` nos `touches` | TEST_DEFECT do Implementer: asserções antigas das chaves do `probes.log` contradizem o UT-06 | SPEC-0088, SPEC-0096 (só testes) | thomas, 2026-11-25 (piloto automático com o recomendado) |
