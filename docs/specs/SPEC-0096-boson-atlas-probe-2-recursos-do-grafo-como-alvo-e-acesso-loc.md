---
id: SPEC-0096
title: "boson-atlas: probe@2 — recursos do grafo como alvo e acesso local à nuvem e ao banco"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-24
parent: SPEC-0095
depends_on: []
consumes_contract: []
contract_version: 2
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/references/probes.md, skills/boson-atlas/references/config.md, skills/boson-atlas/references/context.md, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, skills/boson-atlas/tests/test_probe_resource.py, skills/boson-atlas/tests/test_probe.py, skills/boson-atlas/tests/architecture_rules.py, skills/boson-atlas/tests/test_architecture.py, skills/boson-atlas/tests/fixtures/fake-probes/probe2.py, skills/boson-atlas/tests/fixtures/probe-resource/**, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0023, ADR-0025]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-24
---

# SPEC-0096 — boson-atlas: probe@2 — recursos do grafo como alvo e acesso local à nuvem e ao banco

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

> Origem: épico SPEC-0095, primeira filha (ADR-0025). É o núcleo que os adaptadores SPEC-0098 a SPEC-0101 e a SPEC-0106 consomem pelo contrato (`SPEC-0096@1`). O alvo de mudança (`--commit`) entrou a pedido do Architect para a SPEC-0106 (2026-11-24).

## 1. Visão Geral
O `atlas.py probe` passa a mirar, além do deployment, um **recurso do grafo** (`datastore`, `queue`, `topic` ou `bucket`) ligado ao deployment do serviço no ambiente: `--resource <kind:id>`. A lista dos recursos ligados sai de uma função única do núcleo, `linked_resources`, que o `verify@2` (SPEC-0102) também usa. O probe passa também a aceitar duas entradas opcionais por capacidade: a **mudança** (`--commit <sha>`, para os adaptadores que acompanham uma entrega) e as **jornadas** curadas do serviço (ADR-0026).

A máquina declara, só na camada local e só por referência, como chega à nuvem (o profile da CLI por ambiente), ao banco (usuário, nome do banco e o arquivo de senhas) e à URL base de cada ambiente. Nenhum desses valores sai em `config`, `context`, `doctor`, `probe`, `verify` nem no `probes.log`.

O contrato dos adaptadores ganha a versão `probe@2`: o `--describe` declara, por capacidade, os verbos, os tipos de alvo, o acesso e as entradas de que precisa, e o núcleo entrega só os blocos declarados. Os adaptadores `probe@1` (o `kubernetes` da skill) continuam funcionando sem mudança e nunca recebem um alvo de recurso.

## 2. Motivação & Escopo
**Motivação:** a rotina real de verificação depois do deploy (SPEC-0075) olha as dependências da entrega: a migration no banco, a fila e a DLQ, as assinaturas do tópico, a permissão do workload e os sinais de cada recurso. As probes de hoje (ADR-0023, SPEC-0088) só miram um deployment num cluster. Sem um núcleo que valide o recurso pelo grafo e entregue o acesso local sem imprimi-lo, cada adaptador refaria a descoberta e poderia sair do escopo ou vazar o profile e o caminho do arquivo de senhas.

**Objetivos (dentro do escopo):**
- `atlas.py probe <capacidade> <verbo> --service <id> --env <ambiente> [--resource <kind:id>] [--commit <sha>]`, com as opções de hoje.
- Função única `linked_resources(graph, service, env)` com a regra de ligação do recurso ao deployment do serviço no ambiente (ADR-0025, regra 1), usada pelo `--resource` e consumida pelo `verify@2` (SPEC-0102); o recurso é conferido antes de qualquer processo rodar, e os atributos dele como os campos do alvo da SPEC-0088.
- Camada local: `access.cloud.<ambiente>.profile`, `access.databases.<id>.{user, database, passfile}` e `access.urls.<ambiente>.base_url`, validados, mostrados só como `definido`, e as linhas novas do `doctor` (o arquivo de senhas existe e tem permissão 0600 ou mais fechada, sem ler o conteúdo).
- Contrato `probe@2` (describe com `verbs`, `targets`, `access` e `inputs`; entrada; saída), com as entradas `change` e `journeys` e o acesso `urls`, e os validadores `validate_probe_describe`, `validate_probe_input` e `validate_probe_output` aceitando `probe@1` e `probe@2`.
- Recusa exit 4 `sem acesso local: cluster|cloud|database|urls` para adaptadores `probe@2`.
- Máscara literal com o profile, o usuário, o nome do banco e o arquivo de senhas; padrão novo para o id de conta de nuvem (12 dígitos em ARN e em URL de fila).
- `PGPASSFILE` no ambiente do adaptador quando ele declara `database`; o resto do ambiente continua mínimo.
- `probes.log` com `resource` e `commit`, só quando usados.
- `references/probes.md`, `references/config.md`, `references/context.md`, `SKILL.md`, CHANGELOG, `ATLAS_VERSION` e a versão do plugin.

**Não-objetivos (fora do escopo):**
- Adaptadores concretos: mensageria (SPEC-0098), PostgreSQL (SPEC-0099), CloudWatch (SPEC-0100), IAM (SPEC-0101) e entrega de um commit (SPEC-0106).
- O coletor que traz os recursos e o atributo `dlq` (SPEC-0097).
- A curadoria das jornadas e a validação funcional (SPEC-0103): esta spec só entrega o atributo `journeys` do serviço ao adaptador que o declara.
- `verify@2` (SPEC-0102): o `verify` desta spec continua usando só alvo de deployment.
- Onboarding do acesso e métricas de uso (SPEC-0104).
- Um tipo de acesso para a CI: a credencial da CI de um adaptador usa o mecanismo que já existe, `probes.adapters.<id>.credentials` (nome da variável, por exemplo `GH_TOKEN`).
- Fazer login na nuvem, ler o conteúdo do arquivo de senhas ou conferir se o profile e o usuário são só de leitura.
- Verbos de escrita, em qualquer forma.

## 3. Dependências
- **Implementações necessárias:** N/A — o núcleo do probe (SPEC-0088) e o mapa de acesso (SPEC-0087) já estão implementados na `main`.
- **Contratos consumidos:** N/A — os contratos internos usados (`probe@1`, `access.clusters`, regras do `build` em `references/graph.md`) são da própria skill e já estão implementados.
- **Pré-requisitos externos:** N/A — os testes usam só adaptadores falsos; nenhuma CLI de nuvem nem `psql`.

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Padrões de referência em `skills/boson-atlas/scripts/atlas.py`:
- **alvo e campos conferidos antes de rodar:** `probe_targets`, `target_problem` e `cluster_problem` (SPEC-0088, Emendas v4 e v5);
- **acesso local por referência:** `validate_access` e `access_view` (SPEC-0087);
- **regra de dependência por configuração:** a regra 2 do `build` em `references/graph.md` (`config_refs` → `datastore`, `queue`, `topic`, `bucket` por `attrs.host` ou `name`);
- **repositórios de código do serviço:** `delivery.code_repositories` do `context` (SPEC-0086, `references/context.md`);
- **máscara numa passada só:** `probe_mask`, `PROBE_PATTERNS` e a união dos trechos (SPEC-0088, Emenda v6);
- **ambiente do adaptador:** `probe_environment` (lista permitida);
- **testes:** os adaptadores falsos de `tests/fixtures/fake-probes/` e o padrão de `tests/test_probe.py`.

**Decisão:** estender o subcomando `probe` e a chave local `access` seguindo o ADR-0025 à risca:
- a resolução do recurso fica numa função única, `linked_resources`, que reutiliza o casamento de `config_refs` do `build` (nada de regra paralela) e que o `verify@2` consome;
- o contrato é escolhido pelo `contract` do `--describe` de cada adaptador: `probe@1` aceita só alvo `deployment` com acesso `cluster` implícito; `probe@2` declara `targets`, `access` (pode ser vazio) e `inputs` por capacidade, e só recebe os blocos que declara (os campos de cluster só com `cluster`);
- os literais novos entram na mesma lista de literais da máscara (com as variantes da Emenda v5 da SPEC-0088), e o padrão do id de conta entra em `PROBE_PATTERNS`.

**Justificativa:** mantém o alvo validado pelo núcleo e a regra de produção num lugar só, e o atlas como dado, nunca como comando (ADR-0025). Os adaptadores só recebem o que declaram, então um adaptador de fila nunca vê o arquivo de senhas e um adaptador `probe@1` nunca vê um recurso.

**Desvio do padrão existente:** nenhum. É uma versão nova do contrato no mesmo molde, aprovada pelo ADR-0025.

**Alternativas descartadas:**
- o adaptador receber só o serviço e o ambiente e descobrir os recursos (ADR-0025, opção 2);
- comandos de verificação por recurso no atlas (ADR-0025, opção 3);
- um tipo `access.ci` para a credencial da CI: duplicaria `credentials`, que já entrega a variável por nome só ao adaptador que a declara (ADR-0010);
- exportar o profile como `AWS_PROFILE` no ambiente do adaptador: o ADR-0025 entrega o profile na entrada (`target.cloud.profile`), e o adaptador o passa como argumento.

**ADRs:** ADR-0025 (aplicado; esta spec é o `enforced_by` dele), ADR-0023, ADR-0010.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** a resolução do recurso é uma passada no `graph.json` já lido (linear no número de arestas do deployment). Limites de hoje inalterados: timeout por adaptador, `--lines`, 1 MB lido do adaptador.
- **Segurança:**
  - nenhum processo roda (nem o `--describe`) antes de o recurso estar ligado e com os atributos conferidos;
  - o adaptador só recebe os blocos de acesso e as entradas que declara; `probe@1` nunca recebe recurso;
  - a URL base precisa ser `https://` ou `http://` absoluta e sem credencial (`usuário:senha@`); nunca é impressa;
  - profile, usuário, nome do banco e arquivo de senhas nunca saem em saída, erro, `doctor`, `context`, `config` nem no `probes.log`, e são mascarados literalmente no que vem do adaptador; a URL base também não sai em `config`, `doctor`, `context` nem no `probes.log`;
  - nenhum atributo de recurso no atlas leva id de conta (ADR-0025); a máscara do id de conta cobre o que o adaptador devolver;
  - ids de conta de nuvem saem como `[REDACTED]`;
  - o `doctor` confere o arquivo de senhas só com `stat`, sem abrir;
  - verificado pelos testes UT-01 a UT-09 e IT-01 (busca das sentinelas em toda saída e no registro).
- **Privacidade e dados pessoais:** os padrões de dados pessoais das probes continuam valendo; o `probes.log` não guarda resultado nem acesso.
- **Disponibilidade e resiliência:** recurso ausente, não ligado ou com atributo fora da regra → exit 2 sem rodar nada; acesso local ausente → exit 4; o resto como na SPEC-0088 (exit 1 sem saída parcial).
- **Acessibilidade (UI):** N/A — CLI sem interface gráfica.
- **Custo:** N/A — o núcleo não chama nenhuma API; o custo das consultas é dos adaptadores (SPEC-0098 a SPEC-0101).

## 6. Artefato A — Contrato
**Interface:** opções `--resource` e `--commit` do `probe`; chaves locais `access.cloud`, `access.databases` e `access.urls`; contrato `probe@2`; linhas novas do `doctor`, campos novos do `context` e do `probes.log`.

```text
config.yml (local; na forma com vários atlas, dentro da entrada do atlas) — nunca no atlas-config.yml
  access:
    clusters:  {<cluster>: {context: <nome>}}                    # SPEC-0087, sem mudança
    cloud:     {<ambiente>: {profile: <nome do profile da CLI da nuvem>}}
    databases: {<id do datastore>: {user: <usuário>, database: <nome do banco>, passfile: <caminho>}}
    urls:      {<ambiente>: {base_url: <URL base do ambiente>}}
  regras:
    - access aceita só clusters, cloud, databases e urls; cloud.<ambiente> só profile; databases.<id> só user,
      database e passfile, as três obrigatórias; urls.<ambiente> só base_url
    - base_url: texto de 1 a 2048, esquema https ou http, com host, absoluta, sem usuário nem senha
      (sem "@" antes do host), sem espaço nem caractere de controle
    - <ambiente> e <id do datastore> seguem a regra de nome simples (ENVIRONMENT_NAME_RE)
    - profile, user e database: texto de 1 a 256, sem quebra de linha nem caractere de controle, sem "-" no começo
    - passfile: caminho absoluto ou começando com "~/" (expandido para a pasta da pessoa), mesmas regras de texto
    - senha nunca: só o caminho do arquivo de senhas no formato da ferramenta (.pgpass)
  inválido → config, context e lint saem com 2; doctor ERRO "acesso local" (exit 1); mensagem só com a posição
    (a partir de 1) e o motivo, nunca a chave nem o valor:
    "access.cloud: item 1 inválido — o profile com quebra de linha ou caractere de controle; use access: {cloud: {<ambiente>: {profile: <nome do profile>}}}"
    "access.databases: item 2 inválido — falta passfile; use access: {databases: {<datastore>: {user: <usuário>, database: <banco>, passfile: <caminho>}}}"
    "access.urls: item 1 inválido — a URL base com usuário ou senha; use access: {urls: {<ambiente>: {base_url: <https://…>}}}"
    motivos: "o nome do ambiente|o id do datastore|o profile|o usuário|o banco|o arquivo de senhas|a URL base" + "não é texto"
      | "vazio" | "com mais de 256 caracteres" | "com quebra de linha ou caractere de controle" | "começa com -"
      | "fora da regra de nome" (ambiente, datastore) | "precisa ser absoluto ou começar com ~/" (passfile)
      | "precisa ser http ou https absoluta" | "com usuário ou senha" (URL base)
      | "falta <campo>" | "o mapa aceita só <chaves>" | "o valor precisa ser um mapa"

config / config --json → access: {clusters: {<c>: {context: definido}},
                                  cloud: {<ambiente>: {profile: definido}},
                                  databases: {<id>: {user: definido, database: definido, passfile: definido}},
                                  urls: {<ambiente>: {base_url: definido}}}
  (cada bloco só quando existe na configuração; nunca um valor)

doctor (uma linha por item declarado; nunca o valor):
  OK    acesso nuvem <ambiente> — profile definido
  AVISO acesso nuvem <ambiente> — ambiente não está no grafo
  OK    acesso url <ambiente> — URL base definida
  AVISO acesso url <ambiente> — ambiente não está no grafo
  OK    acesso banco <id> — usuário, banco e arquivo de senhas definidos; arquivo com permissão 0600
  AVISO acesso banco <id> — datastore não está no grafo
  ERRO  acesso banco <id> — arquivo de senhas não encontrado            (não existe ou não é arquivo)
  ERRO  acesso banco <id> — arquivo de senhas acessível por outros usuários (use chmod 600)
                                                                          (algum bit de grupo ou outros)
  OK    acesso banco <id> — … ; permissão não conferida no Windows       (os.name == "nt")
  conferência só por os.stat: o doctor nunca abre nem lê o arquivo de senhas

context (pacote JSON e Markdown; nunca um valor):
  delivery.deployments[]: + "cloud_access": true|false   só quando a camada local tem access.cloud
                            (true quando há access.cloud.<ambiente> para algum ambiente do deployment)
  serviço: + "database_access": {<id do datastore>: true|false}   só quando a camada local tem access.databases,
            para cada datastore das dependências do serviço
  Markdown: "sem acesso local à nuvem" na linha do deployment quando cloud_access é false

atlas.py probe <capacidade> <verbo> --service <id> --env <ambiente>
    [--resource <kind:id>] [--commit <sha>]
    [--since 30m] [--lines N] [--summary] [--confirm-production] [--json] [--atlas X]
  1. sem probes.enabled: true → exit 4 "probes desligadas nesta máquina (probes.enabled)" (como hoje)
  2. argumentos (antes de qualquer processo):
     --lines/--since como hoje
     --resource fora de "<kind>:<id>" ou kind fora de datastore|queue|topic|bucket → exit 2
       "--resource inválido — use <kind>:<id> com kind datastore, queue, topic ou bucket"
     --commit normalizado para minúsculas e, depois, fora de ^[0-9a-f]{7,40}$ → exit 2
       "--commit inválido — use o sha do commit, de 7 a 40 caracteres hexadecimais minúsculos"
  3. deployments: os de service:<id> que runs_in environment:<ambiente> (como hoje; nenhum → exit 2)
  4. recurso (só com --resource):
     a. nó <kind>:<id> do graph.json; nenhum → exit 2
        "recurso <kind:id> não existe no atlas (veja `context` ou rode scan e build)"
     b. ligado: <kind>:<id> está em linked_resources(graph, service, env) (abaixo); vale a primeira entrada
        dele (pela ordem da função), que dá o deployment do alvo
        fora → exit 2 "recurso <kind:id> não ligado a <serviço> em <ambiente>"
        (uma aresta só do serviço, sem o deployment do ambiente, não basta; um recurso ligado ao deployment de
        outro ambiente também não)
     c. atributos do recurso conferidos (ver "Campos do recurso"); fora da regra → exit 2
        "alvo inválido no atlas: resource.<campo> …", sem o valor
  5. mudança (só com --commit; o sha já normalizado para minúsculas no passo 2): repositories = o
     delivery.code_repositories do serviço (SPEC-0086: os repository sourced_from inferidos pela imagem), em
     ordem; nenhum → exit 2 "nenhum repositório de código de service:<id> no atlas para --commit"; um id fora de
     "<dono>/<nome>" (cada parte na regra de nome simples) → exit 2 "alvo inválido no atlas: change.repositories …"
     jornadas (só quando a capacidade escolhida declara journeys, conferidas antes de rodá-la): journeys = o
     atributo journeys do nó do serviço (lista de ids curados, ADR-0026), sem repetição, em ordem; sem o
     atributo → lista vazia; um id fora da regra de nome simples → exit 2 "alvo inválido no atlas: journeys …"
  6. campos do deployment conferidos como hoje (SPEC-0088, Emendas v4 e v5)
  7. adaptador: o primeiro em adapters cujo --describe declara a capacidade E aceita o tipo de alvo
     (deployment sem --resource; o kind do recurso com ele). probe@1 aceita só deployment.
     nenhum → exit 4 "nenhum adaptador para <capacidade>" (sem --resource, como hoje) ou
     "nenhum adaptador para <capacidade> com alvo <kind>" (com --resource)
  8. entradas: capacidade com "change" em inputs e sem --commit → exit 2 "<capacidade> exige --commit";
     --commit numa capacidade sem "change" em inputs (inclui probe@1) → exit 2 "--commit não é aceito por <capacidade>"
  9. verbo fora de (verbos do describe ∩ verbs da configuração) → exit 4 "verbo <v> não permitido" (como hoje)
 10. produção: tier do ambiente diferente de test (inclui sem tier) e sem --confirm-production → exit 4 (como
     hoje); o recurso herda o ambiente do deployment que o liga
 11. acesso, na ordem cluster, cloud, database, urls, só para o que a capacidade declara em access (lista
     vazia = nenhum acesso local; probe@1 = cluster):
     - cluster: como hoje (primeiro cluster do deployment, pelo nome, com access.clusters)
     - cloud: access.cloud.<ambiente>.profile
     - database: access.databases.<id do recurso>, com o passfile existente como arquivo (só os.stat);
       database só é declarável com targets ["datastore"]
     - urls: access.urls.<ambiente>.base_url
     faltou → exit 4 "sem acesso local: cluster|cloud|database|urls" (probe@2), sem citar o valor;
     probe@1 mantém "sem acesso local ao cluster <c> (access.clusters)"
 12. roda o adaptador (entrada no stdin, ambiente abaixo, timeout); 13. valida a saída contra o contrato do
     describe dele, mascara, corta, imprime e registra (como hoje)
  exit: 0 ok · 1 erro do adaptador ou saída inválida · 2 argumento, configuração ou alvo inválido, recurso
        inexistente ou não ligado, --commit faltando ou não aceito · 3 sem configuração · 4 recusado

Campos do recurso (passo 4c; o que vai em target.resource):
  kind  ∈ datastore|queue|topic|bucket;  id = o id do nó sem "<kind>:", na regra de nome simples
  attrs = só os atributos escalares do nó (texto, número, booleano); null, listas e objetos ficam de fora
  cada chave de attrs: ^[a-z][a-z0-9_]{0,63}$
  cada texto de attrs: até 1024 caracteres, sem caractere de controle, sem "-" no começo
  attrs.region, quando há: ^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$  (us-east-1, sa-east-1, us-gov-west-1)
  attrs.dlq, quando há: texto com o id (sem "queue:") de outra fila do grafo
  nenhum atributo de recurso no atlas leva id de conta (nada de ARN nem URL com conta, ADR-0025); o adaptador
  que precisa de ARN ou URL monta pela própria CLI, com operações de leitura

linked_resources(graph, service, env) — função única do núcleo (scripts/atlas.py), usada pelo --resource e
  pelo verify@2 (SPEC-0102):
  entrada: o graph.json já lido, o id do serviço e o ambiente
  para cada deployment D de service:<service> que runs_in environment:<env>, em ordem de id:
    1. aresta D → R de tipo depends_on, reads, writes, publishes ou consumes, com R de kind datastore, queue,
       topic ou bucket → (R, <tipo da aresta>)
    2. item CHAVE=host de D.attrs.config_refs que a regra 2 do build (references/graph.md) resolve para R
       (host igual ao attrs.host ou ao name), pela mesma função do build → (R, "config_ref")
    3. para cada fila Q dos passos 1 e 2 com attrs.dlq texto igual ao id de outra queue:<dlq> → (queue:<dlq>, "dlq")
  saída: lista de {"resource": "<kind:id>", "relation": "<depends_on|reads|writes|publishes|consumes|config_ref|dlq>",
         "deployment": "<id de D>"}, sem repetição de (resource, relation, deployment), ordenada por
         (deployment, resource, relation); lista vazia quando nada liga; nunca lê nada fora do grafo
  dlq que não é texto, ou que aponta para fila inexistente, não liga nada (e não é erro)

Ambiente do adaptador: o de hoje (base fixa + credentials do adaptador) e, só quando a capacidade escolhida
  declara database, PGPASSFILE=<passfile expandido>. Nenhuma outra variável nova (o profile vai na entrada).
  A credencial de uma CI (ex.: GH_TOKEN) vem por probes.adapters.<id>.credentials, como hoje.

probe@2 — descrição: <command> --describe →
  {"contract": "probe@2", "adapter": "<id>",
   "capabilities": {"<capacidade>": {"verbs": [...], "targets": [...], "access": [...], "inputs": [...]}}}
  chaves fechadas; por capacidade: verbs (obrigatória, lista não vazia de palavras), targets (obrigatória,
  lista não vazia, sem repetição, de deployment|datastore|queue|topic|bucket), access (opcional, padrão [],
  pode ser [], sem repetição, de cluster|cloud|database|urls), inputs (opcional, padrão [], sem repetição, de
  change|journeys);
  database em access só com targets == ["datastore"]
probe@2 — entrada (stdin):
  {"contract": "probe@2", "capability", "verb",
   "target": {"service", "environment", "deployment",                    sempre
              "resource": {"kind", "id", "attrs": {…}},                  só com --resource
              "clusters", "context", "namespace", "workloads",            só com cluster em access (juntos)
              "cloud": {"profile"},                                      só com cloud em access
              "database": {"user", "name", "passfile"},                  só com database em access
              "urls": {"base_url"},                                      só com urls em access
              "change": {"commit", "repositories": [...]},               só com change em inputs
              "journeys": [<ids>]},                                      só com journeys em inputs
   "limits": {"lines", "since_seconds"}}
  chaves fechadas; deployment = o que liga o recurso (passo 4b) ou o primeiro pelo id
probe@2 — saída: a do probe@1 (mesmas chaves fechadas e regras), com "contract": "probe@2". Uma saída cujo
  contract difere do contract do describe do adaptador está fora do contrato (exit 1).
probe@1: describe, entrada, saída, mensagens e registro sem mudança (CH-01).

Validadores (scripts/atlas.py): validate_probe_describe, validate_probe_input e validate_probe_output aceitam
  probe@1 e probe@2 pelo campo contract (outro valor → "contract precisa ser probe@1 ou probe@2"); devolvem
  list[str], vazia = válido; nunca citam um valor.

Máscara (numa passada só, SPEC-0088 Emenda v6): literais = contexto + valores das credenciais + profile +
  user + database + passfile (cru e expandido) + base_url, com as variantes (maiúsculas, JSON escapado, URL); padrão novo
  em PROBE_PATTERNS, que troca só os 12 dígitos:
    arn:<partição>:<serviço>:<região?>:<12 dígitos>:…        → arn:aws:sqs:us-east-1:[REDACTED]:orders
    https://<host>.amazonaws.com[.cn]/<12 dígitos>/…         → https://sqs.us-east-1.amazonaws.com/[REDACTED]/orders
  vale para itens, message, cauda do stderr, --summary e para o probes.log. O commit não é mascarado.

probes.log: + "resource": "<kind:id>" (só com --resource) e + "commit": "<sha>" (só com --commit); sem eles a
  linha fica igual à de hoje. Nunca items, message, contexto, profile, usuário, banco, arquivo de senhas nem URL base.
  Chaves fechadas numa constante única do núcleo (PROBE_LOG_KEYS), que write_probe_log e a regra de arquitetura
  usam: as de hoje + resource + commit. Specs seguintes estendem a mesma constante (a SPEC-0104 acrescenta
  reason, um código fechado do núcleo, e access, só o tipo: cluster|cloud|database|urls, nunca o valor);
  a regra de arquitetura confere a constante, não uma lista copiada.
```

**Exemplos do contrato** (vão para `references/probes.md` em blocos `json probe@2 <describe|input|output> <valid|invalid>`, lidos pelo CT-01; os de `probe@1` ficam como estão):

```json
{"contract": "probe@2", "adapter": "aws-messaging", "capabilities": {"messaging": {"verbs": ["queue", "subscriptions"], "targets": ["queue", "topic"], "access": ["cloud"]}}}
```

```json
{"contract": "probe@2", "capability": "messaging", "verb": "queue", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "resource": {"kind": "queue", "id": "orders-dlq", "attrs": {"region": "us-east-1", "name": "orders-dlq"}}, "cloud": {"profile": "acme-dev-read"}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json
{"contract": "probe@2", "capability": "delivery", "verb": "trace", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "change": {"commit": "3f2ef04", "repositories": ["acme/api", "acme/gitops"]}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json
{"contract": "probe@2", "adapter": "smoke", "capabilities": {"functional": {"verbs": ["run"], "targets": ["deployment"], "access": ["urls"], "inputs": ["journeys"]}}}
```

```json
{"contract": "probe@2", "capability": "functional", "verb": "run", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "urls": {"base_url": "https://api.dev.example.test"}, "journeys": ["checkout"]}, "limits": {"lines": 200, "since_seconds": 1800}}
```

Inválidos de exemplo: describe com `targets: ["cluster"]`; describe com `inputs: ["secrets"]`; entrada com `target.clusters` sem `context`; describe com `access: ["database"]` e `targets: ["queue"]`; entrada `probe@2` com `target.database` sem `passfile`; entrada com `target.change.commit` em maiúsculas; saída `probe@2` com `extra`.

**Esclarecimentos (Emenda v2):**
- **Teste antigo do `probe@1`:** o CT-01 da SPEC-0088 (`tests/test_probe.py`) usava uma entrada `probe@1` relabelada como `contract: probe@2` como exemplo inválido. Com esta spec, os validadores aceitam `probe@2`, e essa entrada passa a ser válida. O exemplo inválido passa a usar um contrato que não existe (`probe@3`). Por isso `tests/test_probe.py` entra nos `touches`.
- **Ambiente base no macOS:** o `__CF_USER_TEXT_ENCODING` entra no ambiente base do adaptador. O macOS põe essa variável em todo processo filho, e ela não é credencial. Fica documentado em `references/probes.md` e `references/config.md`.

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `scripts/atlas.py`: `validate_access` e `access_view` (cloud, databases e urls), `probe_targets` e a função nova `linked_resources` (reutilizando o casamento de `config_refs` do `build`), conferência dos campos do recurso e da mudança, escolha do adaptador por alvo, montagem da entrada `probe@2`, `probe_environment` (PGPASSFILE), literais e `PROBE_PATTERNS`, `write_probe_log`, `probe_checks` do `doctor`, `_access_fields` do `context`, validadores e `ATLAS_VERSION`.
- `references/probes.md`: opções novas, passos, exits, `linked_resources`, contrato `probe@2` com exemplos marcados, ambiente do adaptador, máscara, registro e "Escrever um adaptador".
- `references/config.md`: `access.cloud`, `access.databases` e `access.urls`, mensagens e linhas do `doctor`.
- `references/context.md`: `cloud_access` e `database_access`.
- `SKILL.md`: a linha do `probe` e as regras de uso (`--resource`, `--commit`, nunca imprimir acesso).
- Testes: `tests/test_probe_resource.py`, `tests/fixtures/fake-probes/probe2.py` (adaptador falso `probe@2` com roteiro), `tests/fixtures/probe-resource/` (graph.json e configurações) e as regras novas de `tests/architecture_rules.py`.
- CHANGELOG e `version` do `plugin.json`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| probe@1 inalterado | adaptador `probe@1`, sem `--resource`, sem `access.cloud/databases` | entrada, saída, mensagens, `probes.log` e goldens de `config`/`doctor`/`context` iguais aos de hoje | CH-01 |
| Acesso local válido | `access.cloud`, `access.databases` e `access.urls` válidos | `config`/`config --json` mostram só `definido` | UT-01 |
| Acesso local inválido | chave desconhecida, campo faltando, controle, `-` no começo, passfile relativo, URL base relativa, `ftp:` ou com usuário e senha | exit 2 com posição e motivo, sem chave nem valor; `doctor` ERRO `acesso local` | UT-01 |
| `doctor` do banco | passfile 0600, ausente, 0644; datastore fora do grafo | OK; ERRO não encontrado; ERRO permissão; AVISO; o arquivo nunca é aberto | UT-02 |
| `doctor` da nuvem e da URL | ambiente no grafo e fora dele | OK `profile definido` / `URL base definida`; AVISO | UT-02 |
| `context` | com e sem `access.cloud/databases` | `cloud_access`/`database_access` só verdadeiro/falso; ausentes sem as chaves | UT-03 |
| Recursos ligados | `linked_resources` com aresta do deployment, `config_refs` e DLQ; `dlq` não texto ou de fila inexistente | lista com `resource`, `relation` e `deployment`, ordenada e sem repetição; nada fora do grafo | UT-10 |
| Recurso ligado | aresta do deployment, `config_refs`, DLQ de fila ligada | o adaptador recebe o recurso e o deployment que o liga | UT-04, IT-01 |
| Recurso não ligado | aresta só do serviço; ligado só no deployment de outro ambiente | exit 2 `não ligado a`; nenhum processo roda | UT-04, IT-01 |
| Recurso inexistente ou `--resource` inválido | nó ausente; sem `:`; kind `service`/`cluster` | exit 2; nenhum processo roda | UT-04 |
| Atributo do recurso fora da regra | texto com `-` no começo, controle, região inválida, chave inválida | exit 2 `alvo inválido no atlas: resource.…`, sem o valor; nenhum processo | UT-05 |
| Escolha do adaptador | `probe@1` primeiro e `probe@2` depois; nenhum aceita o kind | o `probe@1` nunca recebe recurso; exit 4 `nenhum adaptador para X com alvo K` | UT-06 |
| Sem acesso local | falta cloud, database (ou passfile ausente), cluster ou urls | exit 4 `sem acesso local: <tipo>` sem o valor; adaptador não roda | UT-06, IT-01 |
| Produção | recurso ligado ao deployment de ambiente sem `tier: test` | exit 4 sem `--confirm-production` | UT-06 |
| Entrada mínima | capacidade declara só `cloud`; capacidade com `access: []` | só `target.cloud` (ou nenhum bloco); sem campos de cluster, `database`, `urls`, `change`, `journeys`; sem `PGPASSFILE` | UT-07 |
| URL base e jornadas | capacidade com `urls` e `inputs: [journeys]` | `target.urls.base_url` e `target.journeys` do atributo do serviço; jornada fora da regra → exit 2 | UT-07, IT-02 |
| Banco | capacidade declara `database` | `target.database` e `PGPASSFILE` no ambiente; ambiente continua mínimo | UT-07, IT-01 |
| Máscara | adaptador ecoa profile, usuário, banco, passfile e ARN/URL com conta | tudo `[REDACTED]` em saída, erro, stderr, `--summary` e `probes.log` | UT-08, IT-01 |
| Registro | probe com `--resource` e com `--commit`; probe sem eles | `resource`/`commit` presentes só quando usados | UT-08, UT-09 |
| Mudança | `--commit` válido (inclusive em maiúsculas) com `inputs: [change]` | `target.change` com o commit em minúsculas e só `delivery.code_repositories`; commit não mascarado | UT-09, IT-02 |
| Mudança inválida | sha curto ou com caractere não hexadecimal; exige e falta; não aceita; serviço sem repositório de código | exit 2 com a mensagem do contrato; nenhum processo (salvo o `--describe` nos casos de exigir/não aceitar) | UT-09 |
| Contrato | describe, entrada e saída `probe@1` e `probe@2`, válidos e inválidos | validadores aceitam os válidos e recusam os inválidos com motivo; exemplos lidos do `references/probes.md` | CT-01 |
| Saída com contrato trocado | adaptador `probe@2` responde `probe@1` | exit 1, fora do contrato | CT-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dado um atlas e uma configuração local sem `access.cloud` nem `access.databases`, com o adaptador falso `probe@1` de hoje, quando `probe runtime status`, `config --json`, `doctor` e `context` rodam, então a entrada do adaptador, a saída, as mensagens (inclusive `sem acesso local ao cluster <c> (access.clusters)`) e a linha do `probes.log` são as de hoje, sem `resource` nem `commit`, e os goldens existentes de `config`, `doctor` e `context` não mudam (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado `access` com `cloud: {dev: {profile: P}}`, `databases: {orders-db: {user: U, database: D, passfile: ~/x/.pgpass}}` e `urls: {dev: {base_url: https://api.dev.example.test}}`, quando `config` e `config --json` rodam, então mostram `profile: definido`, `user: definido`, `database: definido`, `passfile: definido` e `base_url: definido`, e nenhum de P, U, D, do caminho ou da URL aparece. Os casos inválidos dão exit 2 com `access.cloud: item N inválido — <motivo>` ou `access.databases: item N inválido — <motivo>`, sem a chave nem o valor: chave desconhecida em `access`, em `cloud.<ambiente>` e em `databases.<id>`; falta `passfile`; profile vazio, com quebra de linha, com mais de 256 caracteres ou começando com `-`; passfile relativo; nome de ambiente fora da regra; URL base relativa, com esquema `ftp`, com `usuário:senha@` ou com espaço (`access.urls: item N inválido — …`). O `doctor` mostra ERRO `acesso local` e sai com 1.
- **UT-02** — Dado um passfile num diretório temporário com permissão 0600, 0400, 0644 e um caminho inexistente, quando o `doctor` roda, então as linhas são, nessa ordem, OK com permissão 0600, OK, ERRO `arquivo de senhas acessível por outros usuários` e ERRO `arquivo de senhas não encontrado`, sem o caminho; o `doctor` nunca abre o arquivo (o `open` embutido, observado, não recebe o caminho). Um `databases.<id>` sem datastore no grafo dá AVISO; `cloud.<ambiente>` no grafo dá OK `profile definido` e fora dele AVISO; `urls.<ambiente>` no grafo dá OK `URL base definida` e fora dele AVISO; nenhuma linha traz a URL.
- **UT-03** — Dado `access.cloud` só para `dev` e `access.databases` só para `orders-db`, quando `context --json` roda para `api`, então o deployment de `dev` tem `cloud_access: true`, o de `prod` `cloud_access: false`, e `database_access` é `{"orders-db": true, "payments-db": false}`; o Markdown diz `sem acesso local à nuvem` no de `prod`; sem as chaves, os campos não aparecem; nenhum valor de acesso aparece no pacote.
- **UT-04** — Dado o `graph.json` da fixture (deployment `dev-api` com `writes` → `queue:orders`, `config_refs` `DB_URL=orders-db.interno` casando com `datastore:orders-db`, `queue:orders` com `dlq: orders-dlq`; `service:api` com `depends_on` → `topic:events` sem aresta do deployment; `datastore:billing-db` ligado só ao deployment `prod-api`), quando `probe` roda com `--env dev` e `--resource` em `queue:orders`, `datastore:orders-db` e `queue:orders-dlq`, então o adaptador recebe o recurso com `deployment: dev-api`. A busca do recurso usa `linked_resources`. Com `topic:events` e `datastore:billing-db` → exit 2 `recurso <kind:id> não ligado a api em dev`; com `queue:nada` → exit 2 `não existe no atlas`; com `queue`, `orders` e `service:api` → exit 2 `--resource inválido`. Em todos os casos de exit 2 o registro de processos do dublê fica vazio (nem o `--describe`).
- **UT-05** — Dado um recurso ligado cujo nó tem `attrs` com texto começando com `-`, texto com quebra de linha, texto de 1025 caracteres, `region: "us east 1"`, `region: "useast-1"` ou uma chave `Bad-Key`, quando `probe --resource` roda, então sai com 2, `alvo inválido no atlas: resource.<campo> …`, sem o valor, e nenhum processo roda. Atributos `null`, listas e objetos não chegam ao adaptador e não recusam.
- **UT-06** — Dados um adaptador `probe@1` (primeiro) e um `probe@2` com `targets: ["queue"]`, `access: ["cloud"]` (segundo), quando `probe messaging queue --resource queue:orders` roda, então só o `probe@2` recebe a entrada (o `probe@1` só roda o `--describe`). Com `--resource datastore:orders-db` → exit 4 `nenhum adaptador para messaging com alvo datastore`. Sem `access.cloud.dev` → exit 4 `sem acesso local: cloud`; com `database` declarado e sem `access.databases.orders-db`, ou com o passfile inexistente → exit 4 `sem acesso local: database`; com `cluster` declarado e sem `access.clusters` → exit 4 `sem acesso local: cluster`; com `urls` declarado e sem `access.urls.dev` → exit 4 `sem acesso local: urls`; nenhum valor de acesso na mensagem e o adaptador não roda. Num ambiente sem `tier: test`, sem `--confirm-production` → exit 4 com a mensagem de produção.
- **UT-07** — Dada uma capacidade `probe@2` que declara só `cloud`, quando a probe roda, então a entrada tem `target.cloud.profile` e não tem `database`, `urls`, `clusters`, `context`, `namespace`, `workloads`, `change` nem `journeys`; com `access: []`, a entrada tem só `service`, `environment`, `deployment` (e o recurso, quando há); e o ambiente do adaptador não tem `PGPASSFILE` nem nenhuma variável fora da base e das `credentials`. Com `database` declarado, a entrada tem `target.database` (`user`, `name`, `passfile` expandido) e o ambiente tem `PGPASSFILE` igual ao passfile expandido. Com `cluster` declarado, os quatro campos do cluster vêm juntos, como no `probe@1`, e só nesse caso. Com `urls` em `access` e `inputs: ["journeys"]`, a entrada tem `target.urls.base_url` e `target.journeys` igual ao atributo `journeys` do serviço (`["checkout", "login"]`), e um serviço sem o atributo dá `journeys: []`; uma jornada com espaço no atlas → exit 2 `alvo inválido no atlas: journeys …`, sem o valor, e a capacidade não roda. A entrada passa em `validate_probe_input`.
- **UT-08** — Dado um adaptador `probe@2` que ecoa nos itens, na `message`, no stderr (com exit 3) e nas linhas do `--summary` o profile, o usuário, o nome do banco, a URL base, o passfile (cru, expandido, escapado em JSON e codificado em URL, em maiúsculas), `arn:aws:sqs:us-east-1:123456789012:orders` e `https://sqs.us-east-1.amazonaws.com/123456789012/orders`, quando a probe roda, então nenhum desses valores nem `123456789012` aparece no stdout, no stderr nem no `probes.log`, o ARN sai `arn:aws:sqs:us-east-1:[REDACTED]:orders` e a URL `https://sqs.us-east-1.amazonaws.com/[REDACTED]/orders`. A linha do `probes.log` tem `resource: "queue:orders"`, e uma probe sem `--resource` não tem a chave.
- **UT-09** — Dada uma capacidade `probe@2` com `inputs: ["change"]` e `targets: ["deployment"]`, e o `service:api` com `sourced_from` → `repository:acme/api` pela imagem (evidência `image:`, em `delivery.code_repositories`) e → `repository:acme/gitops` pelo deployment (só em `config_repositories`), quando `probe delivery trace --commit 3F2EF04` roda, então a entrada tem `target.change` = `{"commit": "3f2ef04", "repositories": ["acme/api"]}`, sem o repositório de configuração, o commit aparece sem máscara na saída e o `probes.log` tem `commit: "3f2ef04"`. `--commit abc`, `--commit 3f2ef0z` e um sha de 41 caracteres → exit 2 `--commit inválido`, sem processo; a capacidade sem `--commit` → exit 2 `delivery exige --commit`; `--commit` numa capacidade sem `change` (e num adaptador `probe@1`) → exit 2 `--commit não é aceito por <capacidade>`; um serviço só com repositório de configuração → exit 2 `nenhum repositório de código de service:<id> no atlas para --commit`. A credencial da CI chega só pelo nome declarado em `credentials`.

- **UT-10** — Dado o `graph.json` da fixture, quando `linked_resources(graph, "api", "dev")` roda, então devolve exatamente `{"resource": "datastore:orders-db", "relation": "config_ref", "deployment": "dev-api"}`, `{"resource": "queue:orders", "relation": "writes", "deployment": "dev-api"}` e `{"resource": "queue:orders-dlq", "relation": "dlq", "deployment": "dev-api"}`, nessa ordem e sem repetição, e não traz `topic:events` (só do serviço) nem `datastore:billing-db` (só de `prod`). Com `dlq` como lista, como número ou apontando para fila inexistente, nada a mais é ligado e não há erro; um ambiente sem deployment dá `[]`; a função não lê arquivo nem rede (só o grafo recebido).

### 7.3 Testes de Integração
- **IT-01** — Com o `atlas.py` de verdade rodando como processo, um atlas temporário com a fixture `probe-resource/graph.json`, `HOME`, `ATLAS_CONFIG_HOME` e `XDG_CONFIG_HOME` temporários, um passfile 0600 temporário e o adaptador falso `tests/fixtures/fake-probes/probe2.py` (com roteiro, que grava a entrada e os nomes e valores do ambiente recebidos num arquivo do teste), quando roda `probe messaging queue --service api --env dev --resource queue:orders-dlq --json`, então a saída segue `probe@2`, a entrada recebida tem o recurso (ligado pela DLQ) e `target.cloud.profile`, o `probes.log` tem uma linha com `resource`; quando roda `probe database migrations --resource datastore:orders-db --json`, o adaptador recebe `target.database` e `PGPASSFILE`; quando roda com `--resource topic:events` (ligado só ao serviço), sai com 2 e o arquivo de registro do dublê fica vazio; e em nenhum stdout, stderr ou linha do `probes.log` das três execuções aparece o profile, o usuário, o nome do banco, o passfile ou o id de conta.
- **IT-02** — Com o mesmo arranjo e uma capacidade `delivery` com `inputs: ["change"]`, `access: []` e `credentials: [FAKE_CI_TOKEN]`, quando roda `probe delivery trace --service api --env dev --commit 3f2ef04 --json`, então o adaptador recebe `target.change` com os repositórios de código do serviço, nenhum campo de cluster e a variável `FAKE_CI_TOKEN` pelo nome, sem `PGPASSFILE` nem outra variável nova, e o `probes.log` tem `commit`. Com uma capacidade `functional` com `access: ["urls"]` e `inputs: ["journeys"]`, `probe functional run --service api --env dev --json` entrega `target.urls.base_url` e `target.journeys`, e a URL não aparece no stdout, no stderr nem no `probes.log`.

### 7.4 Testes de Contrato
- **CT-01** — Dados os blocos `json probe@1 …` e `json probe@2 <describe|input|output> <valid|invalid>` de `references/probes.md` (lidos do documento: ao menos dois válidos e dois inválidos de cada tipo em `probe@2`, incluindo `target.resource`, `target.cloud`, `target.database`, `target.urls`, `target.change` e `target.journeys`), quando `validate_probe_describe`, `validate_probe_input` e `validate_probe_output` rodam, então os válidos de `probe@1` e `probe@2` passam e cada inválido é recusado com motivo, sem citar valor; um `contract: probe@3` é recusado com `contract precisa ser probe@1 ou probe@2`. E, com o adaptador falso, uma saída cujo `contract` difere do do `--describe` dá exit 1 fora do contrato. Este é o contrato `SPEC-0096@1` que os adaptadores consomem.

### 7.5 Testes E2E
- N/A — CLI sem jornada de usuário; IT-01 e IT-02 rodam o `atlas.py` como processo, e a jornada de verificação é da SPEC-0102.

### 7.6 Outros
- Segurança (G3): `tests/architecture_rules.py` ganha duas regras verificadas por `test_architecture.py` — a montagem da entrada de probe só inclui `resource` vindo da função de resolução do recurso, e `write_probe_log` só grava as chaves de `PROBE_LOG_KEYS` (nesta spec, as de hoje mais `resource` e `commit`; a SPEC-0104 acrescenta `reason` e `access` na mesma constante), nunca um valor de acesso. O comportamento é coberto por UT-04, UT-08 e IT-01.

**Dublês e dados de teste:**
- `tests/fixtures/fake-probes/probe2.py`: adaptador falso `probe@2` com roteiro (describe configurável por argumento, resposta por verbo, eco opcional de campos da entrada e do ambiente, stderr e exit), registrando cada chamada num arquivo do teste. Fica nos testes, não na skill.
- Os adaptadores falsos `probe@1` de hoje (`ok.py`, `scripted.py`).
- `tests/fixtures/probe-resource/`: `graph.json` com serviço, deployments de `dev` e `prod`, fila com DLQ, banco por `config_refs`, tópico ligado só ao serviço, repositórios; `atlas-config.yml` com `dev` `tier: test` e `prod` sem tier.
- Sentinelas de acesso (`acme-dev-read`, `ro_user`, `ordersdb`, caminho temporário) e a conta de exemplo `123456789012`, procuradas em toda saída e no registro.
- Sem rede, sem AWS CLI, sem `psql`, sem `kubectl`; `HOME`, `ATLAS_CONFIG_HOME` e `XDG_CONFIG_HOME` temporários.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin (`ATLAS_VERSION` e `plugin.json`). As probes seguem desligadas por padrão (`probes.enabled`), e nada muda para quem não usa `--resource`, `--commit` nem as chaves novas.
- **Dados/schema:** chaves locais novas e opcionais (`access.cloud`, `access.databases`, `access.urls`) e dois campos opcionais no `probes.log`. Nada no atlas.
- **Compatibilidade:**
  - aditiva: adaptadores `probe@1` funcionam sem mudança e continuam recebendo a entrada `probe@1`;
  - uma versão anterior do `atlas.py` recusa `access.cloud`/`access.databases`/`access.urls` (o `access` dela aceita só `clusters`): quem voltar a versão tira essas chaves;
  - o contrato publicado para os adaptadores é `SPEC-0096@1` (`probe@2`).
- **Observabilidade:** linhas novas do `doctor` (nuvem, banco e URL base), `resource` e `commit` no `probes.log` (base das métricas da SPEC-0104).
- **Rollback:** voltar a versão do plugin e tirar as chaves novas da camada local (`access.cloud`, `access.databases`, `access.urls`); ou só `probes.enabled: false`.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] O profile da nuvem vai na entrada ou como `AWS_PROFILE` no ambiente do adaptador? — Na entrada (`target.cloud.profile`), como diz o ADR-0025; o ambiente só ganha `PGPASSFILE`, que é a forma da ferramenta de banco. Nenhuma variável de nuvem é exportada pelo núcleo (Architect, 2026-11-24, recomendado)
- [x] Qual o formato do atributo `dlq`? — Só texto, com o id (sem `queue:`) de outra `queue` do grafo, como no ADR-0025; o coletor (SPEC-0097) grava assim (Architect, 2026-11-24, recomendado)
- [x] Quais repositórios vão em `target.change.repositories`? — Só os de código, `delivery.code_repositories` do serviço (SPEC-0086), como no ADR-0025; o commit é normalizado para minúsculas antes de validar (Architect, 2026-11-24, recomendado)
- [x] Onde fica a URL base de um ambiente? — Na camada local, `access.urls.<ambiente>.base_url`, só com `http`/`https` absoluta e sem credencial; a conta de teste segue por referência (ADR-0025, ADR-0026) (Architect, 2026-11-24, recomendado)
- [x] A credencial da CI precisa de um tipo novo `access.ci`? — Não: usa `probes.adapters.<id>.credentials`, que já entrega a variável só por nome e só ao adaptador que a declara (ADR-0010) (Architect, 2026-11-24, recomendado)
- [x] O `probe` confere o arquivo de senhas? — Só que ele existe como arquivo (por `stat`, sem abrir); a permissão é conferida pelo `doctor`, e a sessão só de leitura pelo adaptador (SPEC-0099) (Architect, 2026-11-24, recomendado)
- [x] `database` pode ser declarado com outros alvos além de `datastore`? — Não: o acesso ao banco é por datastore, então `database` em `access` exige `targets: ["datastore"]` (Architect, 2026-11-24, recomendado)
- [x] Nome de banco curto (ex.: `orders`) mascarado literalmente pode esconder o nome de uma fila igual na saída. Aceita-se? — Sim, como o ADR-0025 manda (o vazamento é pior que o excesso de máscara); fica no radar, junto do contexto curto da SPEC-0088 (Architect, 2026-11-24, recomendado)
- [x] `resource` e `commit` sempre no `probes.log`, com `null` quando não usados? — Não: só quando usados, para a linha de uma probe de deployment ficar igual à de hoje (CH-01) (Architect, 2026-11-24, recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 0: Caracterização**
- [x] CH-01 escrito(s) com a tag `SPEC-0096:<ID>`, passando no código atual, commitado(s) antes de qualquer mudança

**Fase 1: Contrato e implementação**
- [x] Red: UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, UT-07, UT-08, UT-09, UT-10, IT-01, IT-02, CT-01 com a tag `SPEC-0096:<ID>`, falhando pelo motivo certo
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
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=91, skipped=1)) — 4b627eb | 2026-11-24 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — b3743c0 | 2026-11-25 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — f1708a4 | 2026-11-25 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente (subagente): APPROVED — 0 major, 5 minor (máscara de conta no host ECR e ARN em maiúsculas, literais de outros ambientes, regra G3 pelo nome, resource gravado antes da conferência, base_url com barra final) — 89e63fe | 2026-11-25 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — c5ec590 | 2026-11-25 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-25 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-25 |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->
`atlas.py probe` passa a mirar um banco, cache, fila ou tópico ligado ao deployment do serviço no ambiente (`--resource <kind:id>`), e a receber um commit (`--commit`). O acesso fica na configuração local: `access.cloud`, `access.databases` e `access.urls`. O contrato `probe@2` declara `targets`, `access` e `inputs`, e o `probe@1` continua funcionando. Nenhum valor de acesso aparece em saída, erro, `context`, `doctor` ou `probes.log`; o id de conta de nuvem sai mascarado. Versões: boson-atlas 2026.11.19 e plugin 2026.11.34.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- **`scripts/atlas.py`:**
  - `linked_resources` é a função única que liga recurso e deployment, com o mesmo casamento de `config_refs` do `build`, extraído para `config_ref_targets` sem mudar o comportamento;
  - `probe_resource` confere o recurso antes de qualquer processo;
  - os validadores aceitam `probe@1` e `probe@2`;
  - a máscara literal cobre os valores de acesso;
  - o `probes.log` é montado pela constante `PROBE_LOG_KEYS`.
- **Referências:** `references/probes.md`, `config.md` e `context.md`.
- **Emenda v2:**
  - o exemplo inválido do CT-01 da SPEC-0088 passou a usar um contrato inexistente;
  - o `__CF_USER_TEXT_ENCODING` do macOS entrou no ambiente base do adaptador.
- **Execução:** a sessão caiu no meio da implementação; um segundo implementador retomou o trabalho não commitado, sem descartar nada.

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A — `type: feature`. Red em 4b627eb (91 falhas pelo motivo certo, G1) e green em 70b0958 e b3743c0 (G2).

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| CH-01 | adaptador probe@1 de hoje segue igual | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| UT-01 | acesso cloud e databases validado, só "definido" no config | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| UT-02 | doctor confere o passfile só por stat | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| UT-03 | context mostra só se há acesso | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| UT-04 | recurso ligado ao deployment do ambiente; não ligado sai com 2 | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| UT-05 | attrs do recurso conferidos antes de qualquer processo | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| UT-06 | probe@1 nunca recebe recurso; sem acesso sai com 4 | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| UT-07 | só os blocos de acesso declarados chegam ao adaptador | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| UT-08 | máscara literal dos valores de acesso e do id de conta | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| UT-09 | --commit vira target.change com os repositórios de código | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| UT-10 | linked_resources devolve recurso, relação e deployment | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| IT-01 | probe de recurso de ponta a ponta com o atlas.py real | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| IT-02 | capacidade de mudança com credencial por nome | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |
| CT-01 | blocos probe@1 e probe@2 da referência válidos e inválidos | PASS | `test_probe_resource.py` e `test_architecture.py`; G2 PASS (suíte completa e lint) em b3743c0; G4 `verify` 14/14 |

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
Sem deploy: a skill chega pelo plugin `fermion` 2026.11.34 depois do merge (`claude plugin update fermion@fermion-lab`). As probes continuam desligadas por padrão (`probes.enabled`).

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
- **Máscara do id de conta no host do ECR** (`123456789012.dkr.ecr…`) e em ARN em maiúsculas: entra como Emenda da SPEC-0106, cujo adaptador ecoa imagens, antes de ela começar.
- **Minors do G4 no radar** do épico SPEC-0095:
  - literais de acesso de outros ambientes fora da máscara;
  - a regra G3 que reconhece o alvo pelo nome da variável;
  - o `resource` gravado no `probes.log` antes da conferência;
  - o `base_url` com barra final.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0096`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-25 | Esclarecimentos (Emenda v2): `tests/test_probe.py` nos `touches` para corrigir o exemplo inválido do CT-01 da SPEC-0088; `__CF_USER_TEXT_ENCODING` no ambiente base | TEST_DEFECT relatado no G2 | — | thomas, 2026-11-25 (piloto automático com o recomendado) |
