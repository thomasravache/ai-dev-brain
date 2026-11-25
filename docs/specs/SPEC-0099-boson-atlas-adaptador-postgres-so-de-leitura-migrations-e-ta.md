---
id: SPEC-0099
title: "boson-atlas: adaptador postgres só de leitura — migrations e tabelas"
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
touches: [skills/boson-atlas/assets/probes/postgres.py, skills/boson-atlas/references/probes/postgres.md, skills/boson-atlas/tests/test_probe_postgres.py, skills/boson-atlas/tests/fixtures/postgres/**, skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0023, ADR-0025]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-24
---

# SPEC-0099 — boson-atlas: adaptador postgres só de leitura — migrations e tabelas

> Origem: épico SPEC-0095, adaptador da capacidade `database`. É o que o `verify@2` (SPEC-0102) usa para provar que a migration da entrega está aplicada e que nenhuma tabela sumiu.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Adaptador `postgres` do contrato `probe@2` (ADR-0025) para a capacidade `database`. Ele usa o `psql` da máquina numa sessão **só de leitura**, com o usuário, o banco e o arquivo de senhas que esta máquina declara em `access.databases`, e responde duas perguntas sobre um `datastore` PostgreSQL ligado ao serviço no ambiente:
- **`migrations`:** quais migrations estão aplicadas, e alguma falhou?
- **`tables`:** quais tabelas existem nos schemas da aplicação?

Ele só roda as consultas fixas dele, nos catálogos e na tabela de histórico de migrations. Nunca lê linha de tabela da aplicação.

## 2. Motivação & Escopo
**Motivação:** a rotina real de verificação depois do deploy (radar da SPEC-0075) confere a migration no banco. Hoje a pessoa abre um cliente SQL com uma credencial qualquer e olha a tabela de histórico. O núcleo `probe@2` (SPEC-0096) entrega o alvo e o acesso; falta o adaptador que faz essa leitura com as proteções das probes.

**Objetivos (dentro do escopo):**
- **`assets/probes/postgres.py`:** só stdlib, Python 3.9 ou mais novo, com `--describe` e o protocolo `probe@2`.
- **Conexão:** `psql` como lista de argumentos, sem shell; host e porta dos atributos do recurso; usuário e banco de `target.database`; senha só pelo arquivo de senhas (`PGPASSFILE`); sessão com `default_transaction_read_only=on`, `statement_timeout` e `lock_timeout` (`PGOPTIONS`), conferida em cada consulta.
- **`migrations`:** acha a tabela de histórico entre as ferramentas conhecidas (Flyway, Rails, golang-migrate, Entity Framework, Alembic, Knex, Prisma), ou a indicada no atributo `migrations_table` do recurso, e devolve os ids aplicados, com a data e o sucesso quando a ferramenta guarda.
- **`tables`:** nomes das tabelas dos schemas que não são do sistema, com a contagem estimada do catálogo (`pg_class.reltuples`).
- **Lista fechada de consultas:** o adaptador só manda ao `psql` as consultas da constante `QUERIES` dele, cada uma um `SELECT` só; os únicos trechos variáveis são identificadores validados e já checados no catálogo.
- **Erros com texto fixo:** autenticação, conexão, permissão, tempo e sessão que não ficou só de leitura, sem o host, o usuário, o banco nem o stderr do `psql`.
- **`references/probes/postgres.md`:** configuração, papel só de leitura sugerido, as consultas feitas e os exemplos de contrato.

**Não-objetivos (fora do escopo):**
- Ler dado de linha de qualquer tabela da aplicação, `COUNT(*)`, amostras ou `EXPLAIN`.
- Qualquer escrita, DDL, `LOCK`, `VACUUM`, `ANALYZE` ou função com efeito colateral.
- Outros bancos (MySQL, SQL Server) e caches (Valkey/Redis): ficam para adaptadores próprios da capacidade `database`.
- Autenticação por IAM do RDS, certificado de cliente ou senha na configuração: só arquivo de senhas nesta versão.
- Conexão por socket Unix ou por string de conexão (`postgresql://…`, `service=…`).
- Comparar com a foto de antes e decidir o veredito: é do `verify@2` (SPEC-0102).

## 3. Dependências
- **Implementações necessárias:** SPEC-0096 (`depends_on`), porque o IT-01, o IT-02 e o CT-01 usam o núcleo `probe@2` real (`atlas.py probe --resource` e os validadores). Do `probe@2` esta spec usa: o `--describe` do `probe@2` (`capabilities.<cap>.verbs/targets/access`), a entrada com `target.resource` (`kind`, `id`, `attrs` escalares) e `target.database` (`user`, `name`, `passfile`), e a saída `probe@2` (a do `probe@1` com `contract: probe@2`), validados por `validate_probe_describe`, `validate_probe_input` e `validate_probe_output` do `atlas.py`; e os itens da tabela da regra 4a do ADR-0026 (`database migrations`: `id`, `success`; `database tables`: `name`).
- **Contratos consumidos:** N/A — a dependência é de implementação (acima).
- **Pré-requisitos externos:** `psql` (cliente PostgreSQL 12 ou mais novo) no PATH da máquina que roda a probe. Nos testes ele é substituído por um dublê.

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **adaptador `kubernetes`:** `assets/probes/kubernetes.py` (SPEC-0089): stdlib, lista fechada de chamadas, erros com exit 0 e `status: error`, mensagens fixas, dublê de ferramenta em `tests/fixtures/kubernetes/fake_kubectl.py`;
- **contrato:** `probe@2` e acesso local `access.databases` (ADR-0025, SPEC-0096).

**Decisão:** script próprio em `assets/probes/postgres.py`, no molde do `kubernetes`. Cada chamada é `psql` com argumentos fixos e uma consulta da lista `QUERIES`. Cada consulta devolve uma linha só, com um JSON (`json_build_object`/`json_agg`) que traz também `current_setting('transaction_read_only')`; o adaptador recusa o resultado se a sessão não estiver só de leitura.

**Justificativa:** a sessão só de leitura do servidor é a barreira que independe do papel do banco (ADR-0025, consequência "ruim" sobre credencial). Conferir `transaction_read_only` na própria resposta cobre os poolers que descartam o `options` da conexão. A saída em JSON evita analisar texto com separador, e o dublê de `psql` fica simples.

**Desvio do padrão existente:** nenhum.

**Alternativas descartadas:**
- **Driver Python (`psycopg`):** dependência nova, contra o padrão stdlib dos adaptadores.
- **Consultas lidas da configuração ou do atlas:** o atlas seria comando, contra o ADR-0023.
- **Variáveis do `psql` (`:"tabela"`) para o identificador:** não funcionam com `-c`. O identificador é validado por expressão, conferido no catálogo e escrito entre aspas duplas.
- **`migrations_table` em `access.databases`:** pediria campo novo na entrada fechada do ADR-0025 e da SPEC-0096. O nome da tabela é um fato do banco, não acesso, e já chega em `target.resource.attrs` (ver Questões em Aberto).

**ADRs:** ADR-0010 (credencial só por referência), ADR-0023 (probes), ADR-0025 (alvo de recurso, `probe@2`, acesso ao banco).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:**
  - `migrations`: 1 chamada de detecção mais 1 de leitura por tabela de histórico encontrada (no máximo 1 + 5; com uma tabela, 2), cada leitura uma entrada própria de `QUERIES` (Emenda v2); `tables`: 1;
  - `PGCONNECT_TIMEOUT=10`, `statement_timeout=15s`, `lock_timeout=2s` e timeout de 30 s no processo;
  - no máximo 5 tabelas de histórico lidas numa execução e `limits.lines` itens na saída.
- **Segurança:**
  - sessão só de leitura (`PGOPTIONS`) e conferida em cada resposta;
  - lista fechada de consultas fixas, cada uma começando por `SELECT` ou `WITH … SELECT` (sem CTE de escrita), sem `;`, testada pelo dublê;
  - senha só pelo `PGPASSFILE`; `PGPASSWORD` e qualquer outra variável `PG*` herdada são retiradas do ambiente do `psql`, menos `PGSSLMODE`, `PGSSLROOTCERT` e `PGSSLCERT`/`PGSSLKEY` quando declaradas em `credentials`;
  - `-w` (nunca pede senha) e `-X` (não lê `~/.psqlrc`);
  - host, porta, usuário, banco e identificadores validados antes de qualquer chamada; nada que comece com `-` nem contenha `=`, espaço, `/` ou caractere de controle;
  - nenhuma mensagem leva o stderr do `psql`, o host, o usuário, o banco nem o caminho do arquivo de senhas.
- **Privacidade e dados pessoais:** nenhum dado de linha da aplicação é lido. A saída tem só nomes de schema, tabela e migration, datas e contagens estimadas, e passa pela redaction do núcleo (ADR-0025, regra 5).
- **Disponibilidade e resiliência:**
  - `psql` ausente, autenticação, conexão, tempo e permissão → `status: error` com o texto fixo, exit 0;
  - nenhuma tabela de histórico → `status: error` "nenhuma tabela de migrations encontrada": a verificação fica "não verificado", nunca "passou";
  - idempotente: só leitura, pode repetir.
- **Acessibilidade (UI):** N/A — sem interface gráfica.
- **Custo:** N/A — consultas de catálogo, sem serviço pago.

## 6. Artefato A — Contrato
**Interface:** a descrição e os dois verbos do adaptador `postgres`.

```text
--describe → {"contract": "probe@2", "adapter": "postgres",
              "capabilities": {"database": {"verbs": ["migrations", "tables"],
                                            "targets": ["datastore"], "access": ["database"]}}}

entrada (probe@2, SPEC-0096): target.resource = {kind: "datastore", id, attrs}
                              target.database = {user, name, passfile}
  attrs.engine          "postgres" | "aurora-postgresql" (sem diferenciar maiúsculas); outro ou ausente → "engine não suportado"
  attrs.host            hostname ou IPv4, até 253, [A-Za-z0-9.-], sem começar com "-"; ausente → "recurso sem host no atlas"
  attrs.port            inteiro 1..65535 (número ou texto de dígitos); ausente → 5432
  attrs.migrations_table  opcional; "<tabela>" ou "<schema>.<tabela>", cada parte ^[A-Za-z_][A-Za-z0-9_]{0,62}$
  target.database.user / .name   ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}$
  target.database.passfile       caminho absoluto, arquivo comum
  fora da regra → "entrada inválida" (sem citar o valor), nenhuma chamada

chamada (única forma permitida; ordem fixa):
  psql -X -w -q -A -t -v ON_ERROR_STOP=1 -h <host> -p <port> -U <user> -d <name> -c <consulta de QUERIES>
  ambiente do psql = o do adaptador sem nenhuma variável PG* (exceto PGSSLMODE, PGSSLROOTCERT, PGSSLCERT, PGSSLKEY), mais:
    PGPASSFILE=<target.database.passfile>
    PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=2000
    PGCONNECT_TIMEOUT=10   PGAPPNAME=boson-atlas-probe
  timeout do processo 30 s

QUERIES (todas fixas: uma instrução só, começando por SELECT ou WITH … SELECT, sem INSERT/UPDATE/DELETE em CTE, sem ";";
         resposta = uma linha com um JSON {"ro": "on"|"off", ...}):
  detect_migrations   procura em pg_class ⨝ pg_namespace ⨝ pg_attribute (schemas fora de pg_catalog,
                      information_schema, pg_toast*, pg_temp*) as tabelas conhecidas, ou a de attrs.migrations_table,
                      e as colunas delas; pelo catálogo, a tabela aparece mesmo sem GRANT, e a leitura sem
                      permissão vira "sem permissão no banco" (não "nenhuma tabela de migrations encontrada")
  read_<formato>      um por formato abaixo, só as colunas listadas, ORDER BY a data ou o id, LIMIT lines+1;
                      os identificadores "<schema>"."<tabela>" vêm só da resposta de detect_migrations
  list_tables         pg_class ⨝ pg_namespace, relkind in ('r','p'), sem partições filhas (relispartition = false),
                      schemas fora dos do sistema; colunas nspname, relname, reltuples

formatos de histórico (tabela → colunas lidas → item)
  flyway          flyway_schema_history   version, description¹, installed_on, success   id = version (ou description¹ se version é nula)
  rails           schema_migrations       version                                         (sem coluna dirty)
  golang-migrate  schema_migrations       version, dirty                                  success = not dirty
  ef              __EFMigrationsHistory   "MigrationId"
  alembic         alembic_version         version_num                                     (só as versões atuais)
  knex            knex_migrations         name, migration_time
  prisma          _prisma_migrations      migration_name, finished_at, rolled_back_at      success = finished_at não nula e rolled_back_at nula
  ¹ description só para as migrations repetíveis do Flyway, que não têm version
  attrs.migrations_table com outro nome: o formato é reconhecido pelas colunas; nenhum casa → "tabela de migrations em formato desconhecido"

migrations → itens, do mais recente para o mais antigo, até limits.lines (excedente → truncated: true):
  {"id": "20261120.1", "success": true, "schema": "public", "table": "flyway_schema_history", "tool": "flyway",
   "applied_at": "2026-11-20T10:00:00Z" | null}
  id e success são os campos do ADR-0026 (regra 4a); success: false = falhou, dirty ou pendente/pela metade
  (Flyway success=false, golang-migrate dirty, Prisma sem finished_at ou com rolled_back_at) e não conta como aplicada;
  schema, table, tool e applied_at são evidência extra
  mais de 5 tabelas de histórico → lê as 5 primeiras por (schema, tabela) e truncated: true

tables → itens em ordem de (schema, tabela), até limits.lines (excedente → truncated: true):
  {"name": "public.orders", "schema": "public", "table": "orders", "estimated_rows": 1200 | null}
  name = "<schema>.<tabela>" (campo do ADR-0026, regra 4a); estimated_rows extra (reltuples < 0 → null; arredondado)

erros → status: "error", items: [], exit 0, message:
  "psql não encontrado" | "falha de autenticação no banco" | "sem conexão com o banco" |
  "arquivo de senhas não encontrado" | "arquivo de senhas com permissão aberta (use chmod 600)" |
  "sem permissão no banco" | "consulta excedeu o tempo" | "sessão não ficou só de leitura" |
  "nenhuma tabela de migrations encontrada" | "tabela de migrations em formato desconhecido" |
  "engine não suportado" | "recurso sem host no atlas" | "entrada inválida" | "verbo não suportado" |
  "falha do psql" | "resposta inválida do psql"
  reconhecimento pelo stderr do psql (sem diferenciar maiúsculas):
    autenticação: "password authentication failed", "no password supplied", "authentication failed", "no pg_hba.conf entry"
    conexão: "could not connect", "could not translate host name", "connection refused", "timeout expired", "server closed the connection"
    permissão: "permission denied"     tempo: "statement timeout", "canceling statement due to"
    sessão: a resposta traz "ro" diferente de "on"
    psql: exit diferente de 0 sem casar nenhum → "falha do psql"; stdout que não é o JSON esperado → "resposta inválida do psql"
  o arquivo de senhas é checado antes da chamada (existe, é arquivo comum; no POSIX, sem permissão de grupo nem de outros)
```

**Esclarecimentos (Emenda v2):**
- O limite de chamadas de `migrations` é 1 + n, com n ≤ 5 tabelas de histórico; o texto anterior ("no máximo 2") só valia para uma tabela e contradizia a regra de uma entrada de `QUERIES` por leitura.

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `assets/probes/postgres.py` (novo), com a constante `QUERIES` e a função que monta o argv e o ambiente.
- `references/probes/postgres.md` (nova): configuração em `probes.adapters.postgres` e `access.databases`, o arquivo de senhas (formato `.pgpass`, `chmod 600`), um papel só de leitura sugerido (`CREATE ROLE … LOGIN`, `GRANT CONNECT`, `GRANT USAGE` nos schemas, `GRANT SELECT` só nas tabelas de histórico e `ALTER ROLE … SET default_transaction_read_only = on`; os catálogos já são legíveis), as consultas feitas e os blocos `json probe@2 describe|output valid|invalid` lidos pelo CT-01.
- `SKILL.md`: link para a referência, na lista de adaptadores.
- `scripts/atlas.py`: só o `ATLAS_VERSION`.
- `tests/test_probe_postgres.py` e `tests/fixtures/postgres/` (dublê de `psql` e respostas).

**`probes.log`:** nada novo nesta spec. O núcleo (SPEC-0096) registra `resource` e o status, nunca os itens, o usuário, o banco nem o arquivo de senhas.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Descrição | `--describe` | `probe@2`, capacidade `database`, verbos `migrations` e `tables`, alvo `datastore`, acesso `database` | CT-01 |
| Chamada e sessão | qualquer verbo com entrada válida | argv exatamente na forma do contrato; `PGPASSFILE`, `PGOPTIONS` só leitura, `PGCONNECT_TIMEOUT`; sem `PGPASSWORD` nem outro `PG*` herdado | UT-01, IT-01 |
| Porta | `attrs.port` ausente, número ou texto | `-p 5432` ou a porta do atributo | UT-01 |
| Migrations por ferramenta | histórico de cada um dos 7 formatos | itens `{id, success, schema, table, tool, applied_at}`, do mais recente ao mais antigo | UT-02, CT-02 |
| Migration falha ou pendente | Flyway `success=false`, golang-migrate `dirty`, Prisma sem `finished_at` ou com `rolled_back_at` | item com `success: false` | UT-02, CT-02 |
| Tabela indicada | `attrs.migrations_table` com nome próprio e colunas de Flyway | lida como `flyway`; formato desconhecido → erro fixo | UT-03 |
| Mais linhas que o limite | 300 migrations, `lines: 100`; mais de 5 tabelas de histórico | 100 itens mais recentes, `truncated: true` | UT-02 |
| Sem histórico | nenhuma tabela conhecida | `status: error` "nenhuma tabela de migrations encontrada" | UT-03 |
| Tabelas | schemas da aplicação, do sistema e partições | só as da aplicação, sem partições filhas, `name` = `schema.tabela`, `estimated_rows` ou `null` | UT-04, IT-02, CT-02 |
| Nunca dado de linha | qualquer verbo | toda consulta enviada está em `QUERIES`, começa por `SELECT` ou `WITH … SELECT`, não tem `;` e só toca catálogo ou tabela de histórico | UT-05, IT-01 |
| Identificador malicioso | `migrations_table` com aspas, `;`, espaço ou `-` | "entrada inválida", nenhuma chamada | UT-05 |
| Entrada inválida | host, usuário, banco ou passfile fora da regra; engine não postgres; sem host; verbo desconhecido | erro fixo, nenhuma chamada | UT-05 |
| Erros do psql | ausente, autenticação, conexão, permissão, tempo, exit sem motivo, JSON inválido | `status: error` com o texto fixo, exit 0, sem host, usuário, banco nem stderr | UT-06 |
| Arquivo de senhas | ausente ou com permissão aberta | erro fixo, sem o caminho, nenhuma chamada | UT-06 |
| Sessão não só de leitura | resposta com `ro: "off"` | `status: error` "sessão não ficou só de leitura", sem itens | UT-06 |
| Ponta a ponta | `atlas.py probe database migrations --resource datastore:orders-db` com o dublê | saída validada pelo núcleo; usuário, banco e passfile fora da saída e do `probes.log` | IT-01 |
| Contrato | describe e saídas de exemplo, válidas e inválidas | aceitas ou recusadas pelos validadores `probe@2` | CT-01 |
| Itens do `verify@2` | itens reais de `migrations` e `tables` | cumprem a tabela da regra 4a do ADR-0026 | CT-02 |

## 7. Artefato B — Plano de Testes (TDD)
<!-- Todo teste tem um ID e é escrito ANTES da implementação (Red). No código, cada teste carrega a tag `SPEC-0099:<ID>` — o G1 (`spec_graph.py verify`) verifica. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem testes: "N/A — motivo" SEM ID. Teste que protege comportamento existente e passa antes da mudança: marque `(guarda: passa antes da mudança)`. Estratégia completa: references/testing.md da skill. -->

### 7.1 Testes de Caracterização
- N/A — adaptador novo, sem comportamento anterior; o núcleo `probe@2` tem os testes dele na SPEC-0096.

### 7.2 Testes Unitários
- **UT-01** — Dado o dublê de `psql` no PATH, que grava argv e ambiente num arquivo, e uma entrada com `attrs.host: db-dev.acme.internal`, sem `port`, e o ambiente do adaptador com `PGPASSWORD`, `PGHOST`, `PGSERVICE` e `PGSSLMODE`, quando `tables` roda, então o argv é exatamente `psql -X -w -q -A -t -v ON_ERROR_STOP=1 -h db-dev.acme.internal -p 5432 -U <user> -d <name> -c <consulta>`, o ambiente tem `PGPASSFILE` igual ao passfile da entrada, `PGOPTIONS` com `default_transaction_read_only=on`, `statement_timeout=15000` e `lock_timeout=2000`, `PGCONNECT_TIMEOUT=10`, mantém `PGSSLMODE` e não tem `PGPASSWORD`, `PGHOST` nem `PGSERVICE`; com `attrs.port` igual a `6432` ou `"6432"`, então sai `-p 6432`.
- **UT-02** — Dado o dublê respondendo, para cada um dos formatos `flyway`, `rails`, `golang-migrate`, `ef`, `alembic`, `knex` e `prisma`, uma detecção e um histórico gravados, quando `migrations` roda, então os itens têm só as chaves `id`, `success`, `schema`, `table`, `tool` e `applied_at`, em ordem do mais recente ao mais antigo; `applied_at` é `null` em `rails`, `golang-migrate`, `ef` e `alembic`; Flyway com `success=false`, golang-migrate com `dirty=true` e Prisma sem `finished_at` ou com `rolled_back_at` dão `success: false`; com 300 linhas e `lines: 100` saem 100 itens e `truncated: true`; com 6 tabelas de histórico (um schema por cliente) são lidas as 5 primeiras por (schema, tabela) e `truncated: true`.
- **UT-03** — Dado `attrs.migrations_table: ops.db_history` com as colunas do Flyway, quando `migrations` roda, então a detecção procura essa tabela e os itens saem com `tool: flyway` e `table: db_history`; dado o mesmo nome com colunas de nenhum formato, então `status: error` "tabela de migrations em formato desconhecido"; dado um banco sem nenhuma tabela conhecida, então `status: error` "nenhuma tabela de migrations encontrada", sem itens.
- **UT-04** — Dado o dublê com tabelas em `public` e `billing`, uma em `pg_catalog`, uma partição filha e uma com `reltuples = -1`, quando `tables` roda, então saem só `public` e `billing`, sem a partição, ordenados por (schema, tabela), com `name` igual a `<schema>.<tabela>` e `estimated_rows` inteiro ou `null`, e as chaves são só `name`, `schema`, `table` e `estimated_rows`.
- **UT-05** — Em todos os testes, toda consulta registrada pelo dublê pertence a `QUERIES` (depois de substituir os identificadores), começa por `SELECT` ou por `WITH` seguido de um `SELECT` final, sem `INSERT`, `UPDATE`, `DELETE` nem `MERGE`, não tem `;` e não cita outra tabela além das de `pg_catalog` e da tabela de histórico detectada; dado `attrs.migrations_table` igual a `x"; drop table orders; --`, `public.orders limit 1`, `-x` ou com espaço, e dado host, usuário ou banco com `=`, espaço, `/` ou começando com `-`, passfile relativo, `attrs.engine: mysql`, recurso sem `host` ou verbo `query`, quando o adaptador roda, então sai o erro fixo do contrato e o dublê não registra nenhuma chamada.
- **UT-06** — Dado o `psql` ausente do PATH, ou o dublê saindo com 2 e cada stderr do contrato (autenticação, conexão, permissão, tempo, outro texto), ou com exit 0 e stdout que não é JSON, ou com `"ro": "off"`, quando qualquer verbo roda, então `status: error` vem com a mensagem do contrato, `items: []` e exit 0, e a saída não contém o host, o usuário, o banco, o caminho do arquivo de senhas nem o texto do stderr; dado o arquivo de senhas ausente ou com modo `0644` (no POSIX), então sai "arquivo de senhas não encontrado" ou "arquivo de senhas com permissão aberta (use chmod 600)" sem nenhuma chamada.

### 7.3 Testes de Integração
- **IT-01** — Dado um atlas temporário com `service:api`, o deployment `dev-api` em `environment:dev` (`tier: test`) com `depends_on` para `datastore:orders-db` (`engine: postgres`, `host: db-dev.acme.internal`), a configuração local temporária (`HOME`, `XDG_CONFIG_HOME` e `ATLAS_CONFIG_HOME` em pasta temporária) com `probes.enabled: true`, `probes.adapters.postgres` sem `command` e com `verbs: [migrations, tables]`, `access.databases.orders-db` com usuário, banco e um arquivo de senhas temporário `0600`, e o dublê de `psql` no PATH, quando `atlas.py probe database migrations --service api --env dev --resource datastore:orders-db --json` roda como processo, então sai com 0, a saída validada pelo núcleo traz os itens do histórico Flyway gravado, o dublê registrou só consultas de `QUERIES` com `PGPASSFILE` e `PGOPTIONS` só leitura, e nem a saída nem o `probes.log` contêm o usuário, o nome do banco, o caminho do arquivo de senhas ou o host.
- **IT-02** — Com o mesmo atlas e o dublê, quando `atlas.py probe database tables --service api --env dev --resource datastore:orders-db --json` roda, então sai com 0 e os itens são as tabelas da aplicação do UT-04; com o dublê respondendo falha de autenticação, então o `probe` sai com 1 e a mensagem "falha de autenticação no banco", sem o stderr do dublê.

### 7.4 Testes de Contrato
- **CT-01** — O `--describe` real do adaptador e os blocos `json probe@2 describe|output valid|invalid` de `references/probes/postgres.md` (pelo menos: describe válido; saída de `migrations` válida; saída de `tables` válida; saída de erro válida; describe com `targets: ["deployment"]` inválido para este adaptador; saída com item aninhado inválida; saída com chave fora do contrato inválida), quando passam por `validate_probe_describe` e `validate_probe_output` do `atlas.py`, são aceitos ou recusados como o bloco declara; e as saídas reais do UT-02, do UT-04 e do UT-06 também são aceitas.
- **CT-02** — Os itens reais de `migrations` (os 7 formatos do UT-02, com migrations falhas e pendentes) e de `tables` (o cenário do UT-04), conferidos contra a tabela da regra 4a do ADR-0026, cumprem: todo item de `migrations` tem `id` texto não vazio e `success` booleano, e `success` é `false` exatamente nas falhas, nas `dirty` e nas pendentes; todo item de `tables` tem `name` no formato `<schema>.<tabela>`, igual a `schema` + `.` + `table`. Um item de exemplo sem `success`, com `success` texto ou com `name` sem o schema é recusado pela mesma conferência.

### 7.5 Testes E2E
- N/A — sem jornada de usuário interativa (CLI chamada pelo agente); o IT-01 e o IT-02 rodam o comando de ponta a ponta com o dublê.

### 7.6 Outros
- N/A — a segurança (só leitura, lista fechada, nada sensível na saída) já está nos UT-01, UT-05, UT-06 e IT-01.

**Dublês e dados de teste:**
- `tests/fixtures/postgres/fake_psql.py`, copiado como `psql` numa pasta temporária no PATH: acha o cenário num arquivo ao lado dele, responde pela consulta recebida (por um marcador fixo de cada entrada de `QUERIES`), grava argv e as variáveis `PG*` num registro JSON e sai com 2 em qualquer argv fora da forma do contrato.
- Respostas gravadas por formato de histórico e por cenário de erro, só com nomes genéricos (`acme`, `orders`, `billing`, `db-dev.acme.internal`).
- Arquivo de senhas temporário, com conteúdo falso; nenhum banco, nenhuma rede, nenhum `~/.pgpass` real.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15), com `HOME`, `XDG_CONFIG_HOME` e `ATLAS_CONFIG_HOME` temporários.

## 8. Plano de Rollout
- **Estratégia:** deploy direto, pela versão do plugin. Só roda com `probes.enabled: true`, o adaptador declarado em `probes.adapters.postgres` com os verbos liberados e o acesso em `access.databases`.
- **Dados/schema:** N/A — nada gravado no atlas nem no banco.
- **Compatibilidade:** aditivo. Usa o `probe@2` da SPEC-0096; não muda o `probe@1` nem o adaptador `kubernetes`. `attrs.migrations_table` é opcional.
- **Observabilidade:** o `probes.log` do núcleo (com `resource`, sem resultado nem acesso) e o `doctor`, que acha o `psql` pelo `shutil.which` como para os outros adaptadores.
- **Rollback:** tirar o adaptador de `probes.adapters` (efeito imediato nesta máquina) ou voltar a versão do plugin.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
- [x] Onde fica a tabela de migrations fora do padrão? — No atributo `migrations_table` do `datastore`, que chega em `target.resource.attrs` sem mudar o contrato da SPEC-0096 (o nome da tabela é um fato do banco, não acesso). Colocar em `access.databases.<id>.migrations_table` pediria Emenda na SPEC-0096 e ajuste no ADR-0025, que fecham `target.database` em `user`, `name` e `passfile` (Architect, 2026-11-24, recomendado)
- [x] De onde vêm o host e a porta? — Dos atributos `host` (o mesmo que o `build` já usa para ligar `config_refs`) e `port` do recurso, com 5432 por padrão; nenhum campo novo em `access.databases`. O coletor `aws` (SPEC-0097) precisa trazer `engine`, `host` e `port` dos bancos para este adaptador funcionar sem nota manual (Architect, 2026-11-24, recomendado)
- [x] `tables` traz a contagem de linhas? — Só a estimada do catálogo (`pg_class.reltuples`, `null` quando nunca analisada): não lê a tabela, não custa e não é dado de linha. `COUNT(*)` fica fora (Architect, 2026-11-24, recomendado)
- [x] Banco sem tabela de histórico é `ok` vazio ou erro? — Erro "nenhuma tabela de migrations encontrada", para a verificação ficar "não verificado" com motivo e nunca "passou" sem prova (ADR-0026) (Architect, 2026-11-24, recomendado)
- [x] Mais de uma tabela de histórico (schema por cliente)? — Lê até 5, em ordem de (schema, tabela), e marca `truncated` se houver mais; cada item diz `schema` e `table` (Architect, 2026-11-24, recomendado)
- [x] E se um pooler (PgBouncer) descartar o `PGOPTIONS`? — Toda consulta devolve `current_setting('transaction_read_only')`; diferente de `on` vira erro "sessão não ficou só de leitura", sem itens. Como todas as consultas são `SELECT` de catálogo, nada é escrito mesmo nesse caso (Architect, 2026-11-24, recomendado)
- [x] Comportamento do `PGPASSFILE`, do `default_transaction_read_only` e das tabelas de cada ferramenta foi conferido? — Consultados de memória (documentação do PostgreSQL e das ferramentas), sem verificação nesta data; o implementer confere com o `psql` instalado e com as versões atuais das ferramentas, e qualquer diferença vira Emenda (Architect, 2026-11-24, recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Contrato e implementação**
- [x] Red: UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, IT-01, IT-02, CT-01, CT-02 com a tag `SPEC-0099:<ID>`, falhando pelo motivo certo
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
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=93, skipped=1)) — f049d26 | 2026-11-25 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (Installed 1 package in 4ms) — 9699414 | 2026-11-25 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 0198673 | 2026-11-25 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED — 0 major, 5 minor (fração de segundos no 3.9, PGSSLCERT/KEY vs texto, tabela de formato desconhecido derruba o verbo, ordem entre tabelas, desempate do Flyway) — a0978e1 | 2026-11-25 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — ac1039d | 2026-11-25 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-25 |
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
Adaptador `postgres` (`probe@2`, capacidade `database`), só de leitura pelo `psql`. O verbo `migrations` detecta e lê as tabelas de histórico de Flyway, Rails, golang-migrate, EF, Alembic, Knex e Prisma (no máximo 5) e traz cada migration com id e sucesso; `tables` lista as tabelas de usuário no formato `schema.tabela`. Versões: boson-atlas 2026.11.22 e plugin 2026.11.37.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- **`assets/probes/postgres.py`:** dicionário fechado `QUERIES` com 9 SELECTs; identificadores validados e citados, nunca fragmentos de SQL; `PGOPTIONS` força transação só de leitura e toda resposta traz `transaction_read_only`, recusada se não for `on`; `PG*` herdadas removidas (menos as de SSL); argv em lista, sem shell; mensagens de erro fixas, sem host, usuário nem banco.
- **Documentação:** `references/probes/postgres.md`, com o papel só de leitura sugerido.
- **Emenda v2:** `migrations` faz 1 + n chamadas (n ≤ 5 tabelas de histórico).

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A — `type: feature`. Red em 1e5383b (G1) e green em c578f3f (G2).

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | argv fixo, ambiente PG* limpo, PGOPTIONS só leitura e passfile | PASS | `test_probe_postgres.py`; G2 PASS em 9699414; G4 `verify` 10/10 |
| UT-02 | histórico dos 7 formatos de migration normalizado | PASS | `test_probe_postgres.py`; G2 PASS em 9699414; G4 `verify` 10/10 |
| UT-03 | tabela de histórico declarada em migrations_table | PASS | `test_probe_postgres.py`; G2 PASS em 9699414; G4 `verify` 10/10 |
| UT-04 | tables sem catálogo, partições filhas nem contagem desconhecida | PASS | `test_probe_postgres.py`; G2 PASS em 9699414; G4 `verify` 10/10 |
| UT-05 | toda consulta pertence a QUERIES e é um SELECT único | PASS | `test_probe_postgres.py`; G2 PASS em 9699414; G4 `verify` 10/10 |
| UT-06 | erros do psql e respostas fora do formato viram mensagens fixas | PASS | `test_probe_postgres.py`; G2 PASS em 9699414; G4 `verify` 10/10 |
| IT-01 | probe migrations de ponta a ponta com o atlas.py real | PASS | `test_probe_postgres.py`; G2 PASS em 9699414; G4 `verify` 10/10 |
| IT-02 | probe tables de ponta a ponta com o atlas.py real | PASS | `test_probe_postgres.py`; G2 PASS em 9699414; G4 `verify` 10/10 |
| CT-01 | describe e blocos válidos e inválidos do contrato probe@2 | PASS | `test_probe_postgres.py`; G2 PASS em 9699414; G4 `verify` 10/10 |
| CT-02 | itens conferidos contra a regra 4a do ADR-0026 | PASS | `test_probe_postgres.py`; G2 PASS em 9699414; G4 `verify` 10/10 |

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
Sem deploy: a skill chega pelo plugin `fermion` 2026.11.37 depois do merge. O adaptador só roda declarado em `probes.adapters`, com as probes ligadas e a credencial por referência.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
- **Minors do G4 no radar** do épico SPEC-0095:
  - fração de segundos com 1, 2, 4 ou 5 dígitos não é normalizada no Python 3.9;
  - `PGSSLCERT`/`PGSSLKEY` herdadas sempre, e o texto diz "quando declaradas";
  - uma tabela de histórico de formato desconhecido derruba o verbo inteiro;
  - com várias tabelas, a ordem é por tabela, não global;
  - Flyway ordenado por `installed_on` em vez de `installed_rank`.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0099`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-25 | Limite de chamadas de `migrations` passa a 1 + n (n ≤ 5) | Achado do Test-writer: "no máximo 2" contradiz uma entrada de `QUERIES` por leitura | nenhuma | thomas, 2026-11-25 (piloto automático com o recomendado) |
