# Adaptador de probe `postgres`

Adaptador da capacidade `database` do contrato `probe@2` (`references/probes.md`, SPEC-0096, ADR-0025). Vem com a skill em `assets/probes/postgres.py` (só biblioteca padrão, Python 3.9 ou mais novo) e usa o `psql` da máquina (cliente PostgreSQL 12 ou mais novo) numa sessão **só de leitura**, com o usuário, o banco e o arquivo de senhas que esta máquina declara em `access.databases` (SPEC-0099). Nunca lê linha de tabela da aplicação.

| Verbo | Alvo | Pergunta | Itens |
|---|---|---|---|
| `migrations` | `datastore` | Quais migrations estão aplicadas, e alguma falhou? | um por migration, do mais recente ao mais antigo |
| `tables` | `datastore` | Quais tabelas existem nos schemas da aplicação? | um por tabela, em ordem de (schema, tabela) |

Os itens seguem a tabela 4a do ADR-0026, que o `verify@2` lê (`migrations`: `id`, `success`; `tables`: `name`); os campos a mais são evidência e são ignorados por ele.

## Configurar

1. Instale o cliente `psql` e crie no banco um papel **só de leitura** para a probe (abaixo).
2. Crie o arquivo de senhas no formato `.pgpass` (`host:porta:banco:usuário:senha`, uma linha por banco) e feche-o: `chmod 600 <arquivo>`. O atlas guarda só o caminho; a senha nunca vai para a configuração (ADR-0010).
3. Ligue o acesso local ao banco em `access.databases` (`references/config.md`), com o id do `datastore` do atlas:

```yaml
access:
  databases:
    orders-db: {user: atlas_ro, database: ordersdb, passfile: ~/.config/boson-atlas/pgpass}
```

4. Ligue as probes e declare o adaptador no `config.yml` **desta máquina** (nunca no `atlas-config.yml`):

```yaml
probes:
  enabled: true
  adapters:
    postgres:                          # sem command: vale assets/probes/postgres.py da skill
      verbs: [migrations, tables]      # tire o que esta máquina não deve rodar
      timeout: 60
```

5. Rode `atlas.py doctor` e depois uma probe de teste:

```bash
python3 <skill-dir>/scripts/atlas.py probe database migrations --service api --env dev --resource datastore:orders-db
python3 <skill-dir>/scripts/atlas.py probe database tables --service api --env dev --resource datastore:orders-db
```

- **Recurso:** o `datastore` precisa estar ligado ao deployment do serviço no ambiente (`--resource`, `linked_resources`, SPEC-0096). Os atributos usados vêm do coletor `aws` (SPEC-0097) ou de um atlas escrito à mão: `engine` (`postgres` ou `aurora-postgresql`, sem diferenciar maiúsculas; obrigatório), `host` (hostname ou IPv4; obrigatório), `port` (1 a 65535; padrão 5432) e `migrations_table` (opcional, `<tabela>` ou `<schema>.<tabela>`, para uma tabela de histórico com nome próprio).
- **Fora desta versão:** IAM do RDS, certificado de cliente, senha na configuração, socket Unix e string de conexão (`postgresql://…`, `service=…`). `PGSSLMODE`, `PGSSLROOTCERT`, `PGSSLCERT` e `PGSSLKEY` do ambiente chegam ao `psql`; qualquer outra variável `PG*` (inclusive `PGPASSWORD`) é retirada.

### Papel só de leitura sugerido

A sessão só de leitura do adaptador é uma barreira; o papel é a outra (ADR-0023, ADR-0025). Os catálogos (`pg_class`, `pg_namespace`, `pg_attribute`) já são legíveis por qualquer papel; o `SELECT` vai só nas tabelas de histórico:

```sql
CREATE ROLE atlas_ro LOGIN PASSWORD '<senha>';
GRANT CONNECT ON DATABASE ordersdb TO atlas_ro;
GRANT USAGE ON SCHEMA public TO atlas_ro;
GRANT SELECT ON public.flyway_schema_history TO atlas_ro;   -- a tabela de histórico da sua ferramenta
ALTER ROLE atlas_ro SET default_transaction_read_only = on;
```

Sem o `GRANT SELECT`, o `tables` funciona e o `migrations` sai com `sem permissão no banco` (a tabela aparece no catálogo).

## O que é lido

Cada chamada tem uma forma só, como lista de argumentos e sem shell:

```text
psql -X -w -q -A -t -v ON_ERROR_STOP=1 -h <host> -p <porta> -U <usuário> -d <banco> -c <consulta de QUERIES>
ambiente: sem PG* herdado (menos PGSSLMODE, PGSSLROOTCERT, PGSSLCERT, PGSSLKEY), mais
  PGPASSFILE=<target.database.passfile>
  PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=2000
  PGCONNECT_TIMEOUT=10  PGAPPNAME=boson-atlas-probe
timeout do processo: 30 s
```

- `-w` nunca pede senha e `-X` não lê `~/.psqlrc`.
- As consultas são as da constante `QUERIES` do adaptador: um `SELECT` só cada, sem `;`, que devolve uma linha com um JSON `{"ro": <transaction_read_only>, "rows": [...]}`. Uma resposta com `ro` diferente de `on` (um pooler que descartou o `PGOPTIONS`) é recusada.
  - `detect_migrations`: `pg_class` ⨝ `pg_namespace` ⨝ `pg_attribute`, fora dos schemas do sistema, procurando as tabelas conhecidas (ou a de `migrations_table`) e as colunas delas; até 6 por (schema, tabela).
  - `read_<formato>`: só as colunas do formato, do `"<schema>"."<tabela>"` achado pela detecção, do mais recente ao mais antigo, `LIMIT lines+1`.
  - `list_tables`: `pg_class` ⨝ `pg_namespace`, `relkind` `r` ou `p`, sem partições filhas, fora de `pg_catalog`, `information_schema`, `pg_toast*` e `pg_temp*`; `nspname`, `relname`, `reltuples`.
- **`migrations`:** 1 detecção mais 1 leitura por tabela de histórico encontrada, até 5 (no máximo 6 chamadas). **`tables`:** 1 chamada.
- **Nunca:** linha de tabela da aplicação, `COUNT(*)`, amostras, `EXPLAIN`, escrita, DDL, `LOCK`, `VACUUM`, `ANALYZE`.
- Recusado **antes** de chamar o `psql`: verbo fora de `migrations` e `tables` (`verbo não suportado`); `engine` ausente ou outro (`engine não suportado`); sem `host` (`recurso sem host no atlas`); host fora de `^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$`, porta fora de 1..65535, usuário ou banco fora de `^[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}$`, `migrations_table` fora de `<parte>` ou `<parte>.<parte>` com `^[A-Za-z_][A-Za-z0-9_]{0,62}$`, arquivo de senhas que não é caminho absoluto (`entrada inválida`, sem citar o valor); arquivo de senhas ausente ou com permissão de grupo ou de outros no POSIX.

### Formatos de histórico

| Ferramenta (`tool`) | Tabela | Colunas lidas | `id` | `success` | `applied_at` |
|---|---|---|---|---|---|
| `flyway` | `flyway_schema_history` | `version`, `description` (só sem `version`), `installed_on`, `success` | `version`, ou `description` nas repetíveis | `success` | `installed_on` |
| `rails` | `schema_migrations` (sem `dirty`) | `version` | `version` | `true` | `null` |
| `golang-migrate` | `schema_migrations` | `version`, `dirty` | `version` | `not dirty` | `null` |
| `ef` | `__EFMigrationsHistory` | `MigrationId` | `MigrationId` | `true` | `null` |
| `alembic` | `alembic_version` | `version_num` (só as versões atuais) | `version_num` | `true` | `null` |
| `knex` | `knex_migrations` | `name`, `migration_time` | `name` | `true` | `migration_time` |
| `prisma` | `_prisma_migrations` | `migration_name`, `finished_at`, `rolled_back_at` | `migration_name` | `finished_at` não nulo e `rolled_back_at` nulo | `finished_at` |

Com `migrations_table`, o formato é reconhecido pelas colunas; nenhum casa → `tabela de migrations em formato desconhecido`.

## Saída

**`migrations`** — um item por migration, do mais recente ao mais antigo, até `limits.lines` (o excedente dá `truncated: true`):

```json
{"id": "20261120.1", "success": false, "schema": "public", "table": "flyway_schema_history", "tool": "flyway", "applied_at": "2026-11-20T10:00:00"}
```

- `success: false` = falhou, `dirty` ou pendente/pela metade (Flyway `success=false`, golang-migrate `dirty`, Prisma sem `finished_at` ou com `rolled_back_at`): não conta como aplicada.
- `applied_at`: ISO 8601; com fuso conhecido vira UTC com `Z`; `null` quando a ferramenta não guarda a data.
- Mais de 5 tabelas de histórico (um schema por cliente): lê as 5 primeiras por (schema, tabela) e `truncated: true`. Cada item diz `schema` e `table`.

**`tables`** — um item por tabela, em ordem de (schema, tabela), até `limits.lines`:

```json
{"name": "public.orders", "schema": "public", "table": "orders", "estimated_rows": 1200}
```

- `estimated_rows`: `pg_class.reltuples` arredondado (estimativa do catálogo, sem ler a tabela); `null` quando a tabela nunca foi analisada.
- Saem tabelas comuns e partições mães; partições filhas, visões e schemas do sistema não.

## Erros

Saem com exit 0, `status: error`, `items: []` e uma mensagem fixa, **sem** o stderr do `psql`, o host, o usuário, o banco nem o caminho do arquivo de senhas:

| Mensagem | Quando |
|---|---|
| `psql não encontrado` | sem `psql` no `PATH` do adaptador |
| `falha de autenticação no banco` | "password authentication failed", "no password supplied", "authentication failed", "no pg_hba.conf entry" |
| `sem conexão com o banco` | "could not connect", "could not translate host name", "connection refused", "timeout expired", "server closed the connection" |
| `sem permissão no banco` | "permission denied" (por exemplo, leitura da tabela de histórico sem `GRANT SELECT`) |
| `consulta excedeu o tempo` | "statement timeout", "canceling statement due to", ou o processo passou de 30 s |
| `sessão não ficou só de leitura` | a resposta trouxe `ro` diferente de `on` |
| `arquivo de senhas não encontrado` / `arquivo de senhas com permissão aberta (use chmod 600)` | conferido por `os.stat` antes da chamada |
| `nenhuma tabela de migrations encontrada` | nenhuma tabela conhecida (nem a de `migrations_table`): o `verify` fica "não verificado", nunca "passou" |
| `tabela de migrations em formato desconhecido` | a tabela achada não tem as colunas de nenhum formato |
| `engine não suportado` / `recurso sem host no atlas` / `entrada inválida` / `verbo não suportado` | entrada fora da regra, sem nenhuma chamada |
| `falha do psql` / `resposta inválida do psql` | outro erro, ou stdout que não é o JSON esperado |

O adaptador não grava nada; o `probes.log` é do núcleo, com `resource` e sem resultado nem acesso (ADR-0025 regra 6).

## Exemplos do contrato

Blocos lidos pelo teste de contrato (CT-01) contra os validadores `probe@2` do núcleo.

```json probe@2 describe valid
{"contract": "probe@2", "adapter": "postgres", "capabilities": {"database": {"verbs": ["migrations", "tables"], "targets": ["datastore"], "access": ["database"]}}}
```

```json probe@2 describe invalid
{"contract": "probe@2", "adapter": "postgres", "capabilities": {"database": {"verbs": ["migrations"], "targets": ["deployment"], "access": ["database"]}}}
```

```json probe@2 input valid
{"contract": "probe@2", "capability": "database", "verb": "migrations", "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "resource": {"kind": "datastore", "id": "orders-db", "attrs": {"engine": "postgres", "host": "db-dev.acme.internal", "port": 5432}}, "database": {"user": "atlas_ro", "name": "ordersdb", "passfile": "/var/lib/acme/pgpass"}}, "limits": {"lines": 200, "since_seconds": 1800}}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "postgres", "capability": "database", "verb": "migrations", "status": "ok", "items": [{"id": "20261120.1", "success": false, "schema": "public", "table": "flyway_schema_history", "tool": "flyway", "applied_at": "2026-11-20T10:00:00"}, {"id": "2", "success": true, "schema": "public", "table": "flyway_schema_history", "tool": "flyway", "applied_at": "2026-11-10T10:00:00"}], "truncated": false}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "postgres", "capability": "database", "verb": "tables", "status": "ok", "items": [{"name": "billing.invoices", "schema": "billing", "table": "invoices", "estimated_rows": 50}, {"name": "public.orders", "schema": "public", "table": "orders", "estimated_rows": null}], "truncated": false}
```

```json probe@2 output valid
{"contract": "probe@2", "adapter": "postgres", "capability": "database", "verb": "migrations", "status": "error", "items": [], "truncated": false, "message": "falha de autenticação no banco"}
```

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "postgres", "capability": "database", "verb": "migrations", "status": "ok", "items": [{"id": "2", "success": true, "history": {"schema": "public", "table": "flyway_schema_history"}}], "truncated": false}
```

```json probe@2 output invalid
{"contract": "probe@2", "adapter": "postgres", "capability": "database", "verb": "tables", "status": "ok", "items": [], "truncated": false, "host": "[REDACTED]"}
```
