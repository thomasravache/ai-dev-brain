#!/usr/bin/env python3
"""postgres probe adapter of the boson-atlas (SPEC-0099, ADR-0023, ADR-0025, ADR-0026), contract probe@2 (SPEC-0096).

Usage: python3 postgres.py --describe     -> the capabilities (database: migrations, tables)
       python3 postgres.py < input.json   -> reads the probe@2 input on stdin, prints the probe@2 output

Read only: the one external process is the machine's psql, run with an argv list (never a shell) in one fixed form
    psql -X -w -q -A -t -v ON_ERROR_STOP=1 -h <host> -p <port> -U <user> -d <name> -c <a query of QUERIES>
with host and port from target.resource.attrs, user and name from target.database, the password only through
PGPASSFILE, no inherited PG* variable (but PGSSLMODE, PGSSLROOTCERT, PGSSLCERT and PGSSLKEY) and a read-only session
(PGOPTIONS default_transaction_read_only=on, statement_timeout, lock_timeout), checked again in every answer
("ro"). Every query is a single SELECT of the closed list QUERIES, over the catalog or a migrations history table
found in the catalog; no row of an application table is ever read. Errors leave with exit 0 and status "error" with
a fixed message; the host, the user, the database, the passfile and the stderr of psql are never printed. The core
(atlas.py probe) applies the redaction and the limits again. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone

CONTRACT = "probe@2"
ADAPTER = "postgres"
CAPABILITY = "database"
VERBS = ("migrations", "tables")
DESCRIBE = {"contract": CONTRACT, "adapter": ADAPTER,
            "capabilities": {CAPABILITY: {"verbs": list(VERBS), "targets": ["datastore"], "access": ["database"]}}}
ENGINES = ("postgres", "aurora-postgresql")
DEFAULT_PORT = 5432
PROCESS_TIMEOUT = 30  # seconds for one psql process
MAX_HISTORIES = 5  # history tables read in one run
MAX_LINES = 2000
KEPT_PG = ("PGSSLMODE", "PGSSLROOTCERT", "PGSSLCERT", "PGSSLKEY")  # the only inherited PG* variables kept
SESSION = {"PGOPTIONS": "-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=2000",
           "PGCONNECT_TIMEOUT": "10", "PGAPPNAME": "boson-atlas-probe"}
PREFIX = ("-X", "-w", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1")
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}\Z")
ROLE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}\Z")  # target.database.user and .name
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}\Z")  # schema and table names written between double quotes
WORD_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}\Z")

# the known history tables (SPEC-0099, section 6)
KNOWN_TABLES = ("flyway_schema_history", "schema_migrations", "__EFMigrationsHistory", "alembic_version",
                "knex_migrations", "_prisma_migrations")
# format -> the columns that recognize it, in the order they are tried (golang-migrate before rails: same table)
FORMATS = (
    ("flyway", ("version", "description", "installed_on", "success")),
    ("prisma", ("migration_name", "finished_at", "rolled_back_at")),
    ("knex", ("name", "migration_time")),
    ("golang-migrate", ("version", "dirty")),
    ("ef", ("MigrationId",)),
    ("alembic", ("version_num",)),
    ("rails", ("version",)),
)

_RO = "'ro', current_setting('transaction_read_only')"


def _read(columns, order):
    """A read_<format> query: only the listed columns of the history table, newest first, LIMIT lines+1."""
    return (f"SELECT json_build_object({_RO}, 'rows', COALESCE((SELECT json_agg(h ORDER BY {order}) FROM "
            f"(SELECT {columns} FROM {{table}} ORDER BY {order} LIMIT {{limit}}) h), '[]'::json))")


# the closed list: the only texts ever sent to psql. Placeholders: {names} (literals of validated identifiers),
# {schema} (a literal of a validated identifier or ''), {table} ("<schema>"."<table>" found by detect_migrations,
# validated) and {limit} (an integer).
QUERIES = {
    "detect_migrations": (
        f"SELECT json_build_object({_RO}, 'rows', COALESCE((SELECT json_agg(d ORDER BY d.nspname, d.relname) FROM "
        "(SELECT n.nspname, c.relname, (SELECT json_agg(a.attname ORDER BY a.attnum) FROM pg_catalog.pg_attribute a "
        "WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped) AS columns "
        "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind IN ('r', 'p') AND c.relname IN ({names}) AND ({schema} = '' OR n.nspname = {schema}) "
        "AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg\\_toast%' "
        "AND n.nspname NOT LIKE 'pg\\_temp%' ORDER BY n.nspname, c.relname LIMIT 6) d), '[]'::json))"),
    "list_tables": (
        f"SELECT json_build_object({_RO}, 'rows', COALESCE((SELECT json_agg(t ORDER BY t.nspname, t.relname) FROM "
        "(SELECT n.nspname, c.relname, c.reltuples FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition "
        "AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg\\_toast%' "
        "AND n.nspname NOT LIKE 'pg\\_temp%' ORDER BY n.nspname, c.relname LIMIT {limit}) t), '[]'::json))"),
    "read_flyway": _read("version, CASE WHEN version IS NULL THEN description END AS description, installed_on, "
                         "success", "installed_on DESC"),
    "read_rails": _read("version", "version DESC"),
    "read_golang-migrate": _read("version, dirty", "version DESC"),
    "read_ef": _read('"MigrationId"', '"MigrationId" DESC'),
    "read_alembic": _read("version_num", "version_num DESC"),
    "read_knex": _read("name, migration_time", "migration_time DESC, name DESC"),
    "read_prisma": _read("migration_name, finished_at, rolled_back_at", "migration_name DESC"),
}

# the contract messages (SPEC-0099, section 6)
NOT_FOUND = "psql não encontrado"
AUTH = "falha de autenticação no banco"
NO_CONNECTION = "sem conexão com o banco"
NO_PASSFILE = "arquivo de senhas não encontrado"
OPEN_PASSFILE = "arquivo de senhas com permissão aberta (use chmod 600)"
DENIED = "sem permissão no banco"
TIMEOUT = "consulta excedeu o tempo"
NOT_READ_ONLY = "sessão não ficou só de leitura"
NO_HISTORY = "nenhuma tabela de migrations encontrada"
UNKNOWN_FORMAT = "tabela de migrations em formato desconhecido"
BAD_ENGINE = "engine não suportado"
NO_HOST = "recurso sem host no atlas"
INVALID_INPUT = "entrada inválida"
BAD_VERB = "verbo não suportado"
PSQL_FAILED = "falha do psql"
INVALID_ANSWER = "resposta inválida do psql"
ERROR_RULES = (  # (message, markers in the lowercased stderr), in order
    (AUTH, ("password authentication failed", "no password supplied", "authentication failed",
            "no pg_hba.conf entry")),
    (NO_CONNECTION, ("could not connect", "could not translate host name", "connection refused", "timeout expired",
                     "server closed the connection")),
    (DENIED, ("permission denied",)),
    (TIMEOUT, ("statement timeout", "canceling statement due to")),
)


class ProbeError(Exception):
    """An error with one of the fixed messages: becomes status "error" (exit 0)."""


# ---------------------------------------------------------------- input


def has_control(value):
    return isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value)


def port_of(value):
    if value is None:
        return DEFAULT_PORT
    if isinstance(value, bool):
        raise ProbeError(INVALID_INPUT)
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if not isinstance(value, int) or not 1 <= value <= 65535:
        raise ProbeError(INVALID_INPUT)
    return value


def history_table(value):
    """(schema or "", table) of attrs.migrations_table, or None without it."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProbeError(INVALID_INPUT)
    parts = value.split(".")
    if len(parts) not in (1, 2) or not all(IDENT_RE.match(part) for part in parts):
        raise ProbeError(INVALID_INPUT)
    return ("", parts[0]) if len(parts) == 1 else (parts[0], parts[1])


def check_input(data):
    """(verb, connection, declared table, lines) of a probe@2 input, or ProbeError with the fixed message. Nothing
    here calls psql."""
    if not isinstance(data, dict) or data.get("contract") != CONTRACT:
        raise ProbeError(INVALID_INPUT)
    if data.get("capability") != CAPABILITY or data.get("verb") not in VERBS:
        raise ProbeError(BAD_VERB)
    target, limits = data.get("target"), data.get("limits")
    if not isinstance(target, dict) or not isinstance(limits, dict):
        raise ProbeError(INVALID_INPUT)
    lines = limits.get("lines")
    if isinstance(lines, bool) or not isinstance(lines, int) or lines < 1:
        raise ProbeError(INVALID_INPUT)
    resource, database = target.get("resource"), target.get("database")
    if not isinstance(resource, dict) or not isinstance(database, dict):
        raise ProbeError(INVALID_INPUT)
    attrs = resource.get("attrs")
    if resource.get("kind") != "datastore" or not isinstance(attrs, dict):
        raise ProbeError(INVALID_INPUT)
    engine = attrs.get("engine")
    if not isinstance(engine, str) or engine.lower() not in ENGINES:
        raise ProbeError(BAD_ENGINE)
    host = attrs.get("host")
    if host is None or host == "":
        raise ProbeError(NO_HOST)
    if not isinstance(host, str) or not HOST_RE.match(host):
        raise ProbeError(INVALID_INPUT)
    port = port_of(attrs.get("port"))
    user, name, passfile = database.get("user"), database.get("name"), database.get("passfile")
    for value in (user, name):
        if not isinstance(value, str) or not ROLE_RE.match(value):
            raise ProbeError(INVALID_INPUT)
    if not isinstance(passfile, str) or has_control(passfile) or not os.path.isabs(passfile):
        raise ProbeError(INVALID_INPUT)
    declared = history_table(attrs.get("migrations_table"))
    return data["verb"], {"host": host, "port": port, "user": user, "name": name, "passfile": passfile}, declared, \
        min(lines, MAX_LINES)


def check_passfile(path):
    """The passfile exists, is a regular file and (POSIX) is closed to group and others; checked by os.stat only."""
    try:
        info = os.stat(path)
    except OSError:
        raise ProbeError(NO_PASSFILE) from None
    if not stat.S_ISREG(info.st_mode):
        raise ProbeError(NO_PASSFILE)
    if os.name == "posix" and info.st_mode & 0o077:
        raise ProbeError(OPEN_PASSFILE)


# ---------------------------------------------------------------- psql


def quote_literal(value):
    if not IDENT_RE.match(value) and value != "":
        raise ProbeError(INVALID_INPUT)
    return f"'{value}'"


def quote_table(schema, table):
    if not (IDENT_RE.match(schema) and IDENT_RE.match(table)):
        raise ProbeError(INVALID_ANSWER)
    return f'"{schema}"."{table}"'


def psql_environment(passfile):
    """The adapter's environment without any PG* variable (but the SSL ones), plus the read-only session."""
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("PG") or k in KEPT_PG}
    environment.update(SESSION)
    environment["PGPASSFILE"] = passfile
    return environment


class Psql:
    """The only door to psql: the fixed form of section 6 with a query of QUERIES."""

    def __init__(self, connection):
        self.connection = connection
        self.executable = None
        self.calls = 0

    def argv(self, query):
        c = self.connection
        return [*PREFIX, "-h", c["host"], "-p", str(c["port"]), "-U", c["user"], "-d", c["name"], "-c", query]

    def query(self, key, **values):
        """The rows answered by the query QUERIES[key] with its placeholders filled; ProbeError with a fixed message
        (NOT_READ_ONLY when the session was not read only)."""
        template = QUERIES[key]
        text = " ".join(template.format(**values).split())
        if self.executable is None:
            self.executable = shutil.which("psql") or ""
        if not self.executable:
            raise ProbeError(NOT_FOUND)
        self.calls += 1
        try:
            proc = subprocess.run([self.executable, *self.argv(text)], stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=PROCESS_TIMEOUT,
                                  env=psql_environment(self.connection["passfile"]), check=False)
        except subprocess.TimeoutExpired:
            raise ProbeError(TIMEOUT) from None
        except OSError:
            raise ProbeError(NOT_FOUND) from None
        if proc.returncode != 0:
            raise ProbeError(classify(proc.stderr or ""))
        try:
            data = json.loads(proc.stdout.strip())
        except ValueError:
            raise ProbeError(INVALID_ANSWER) from None
        if not isinstance(data, dict):
            raise ProbeError(INVALID_ANSWER)
        if data.get("ro") != "on":
            raise ProbeError(NOT_READ_ONLY)
        rows = data.get("rows")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ProbeError(INVALID_ANSWER)
        return rows


def classify(stderr):
    """The fixed message for a failed psql: never its text (it quotes the host, the user and the database)."""
    low = stderr.lower()
    for message, markers in ERROR_RULES:
        if any(marker in low for marker in markers):
            return message
    return PSQL_FAILED


# ---------------------------------------------------------------- helpers


def stamp(value):
    """A timestamp of the history as ISO 8601 text (UTC with Z when the zone is known), or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return text if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", text) else None
    if parsed.tzinfo is None:
        return parsed.replace(microsecond=0).isoformat()
    return parsed.astimezone(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"


def text_id(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def format_of(columns):
    present = set(columns)
    for name, needed in FORMATS:
        if present.issuperset(needed):
            return name
    return None


def migration_item(tool, row):
    """(id, success, applied_at) of one history row of the format."""
    if tool == "flyway":
        ident = text_id(row.get("version")) or text_id(row.get("description"))
        return ident, row.get("success") is True, stamp(row.get("installed_on"))
    if tool == "golang-migrate":
        return text_id(row.get("version")), row.get("dirty") is False, None
    if tool == "prisma":
        finished = row.get("finished_at")
        success = finished is not None and row.get("rolled_back_at") is None
        return text_id(row.get("migration_name")), success, stamp(finished)
    if tool == "knex":
        return text_id(row.get("name")), True, stamp(row.get("migration_time"))
    column = {"rails": "version", "ef": "MigrationId", "alembic": "version_num"}[tool]
    return text_id(row.get(column)), True, None


# ---------------------------------------------------------------- verbs


def run_migrations(psql, declared, lines):
    if declared:
        schema, names = declared[0], [declared[1]]
    else:
        schema, names = "", list(KNOWN_TABLES)
    found = psql.query("detect_migrations", names=", ".join(quote_literal(n) for n in names),
                       schema=quote_literal(schema))
    tables = []
    for row in found:
        nspname, relname, columns = row.get("nspname"), row.get("relname"), row.get("columns")
        if not isinstance(nspname, str) or not isinstance(relname, str) or not isinstance(columns, list):
            raise ProbeError(INVALID_ANSWER)
        if relname not in names or (schema and nspname != schema):
            continue
        tables.append((nspname, relname, columns))
    if not tables:
        raise ProbeError(NO_HISTORY)
    tables.sort(key=lambda t: (t[0], t[1]))
    truncated = len(tables) > MAX_HISTORIES
    chosen = []
    for nspname, relname, columns in tables[:MAX_HISTORIES]:
        tool = format_of(columns)
        if tool is None:
            raise ProbeError(UNKNOWN_FORMAT)
        chosen.append((nspname, relname, tool))
    items = []
    for nspname, relname, tool in chosen:
        rows = psql.query(f"read_{tool}", table=quote_table(nspname, relname), limit=lines + 1)
        if len(rows) > lines:
            truncated, rows = True, rows[:lines]
        for row in rows:
            ident, success, applied_at = migration_item(tool, row)
            if ident is None:
                raise ProbeError(INVALID_ANSWER)
            items.append({"id": ident, "success": success, "schema": nspname, "table": relname, "tool": tool,
                          "applied_at": applied_at})
    if len(items) > lines:
        truncated, items = True, items[:lines]
    return items, truncated


def run_tables(psql, declared, lines):
    rows = psql.query("list_tables", limit=lines + 1)
    items = []
    for row in rows:
        nspname, relname, reltuples = row.get("nspname"), row.get("relname"), row.get("reltuples")
        if not isinstance(nspname, str) or not isinstance(relname, str) or not nspname or not relname:
            raise ProbeError(INVALID_ANSWER)
        if isinstance(reltuples, bool) or not isinstance(reltuples, (int, float)) or reltuples < 0:
            estimated = None
        else:
            estimated = round(reltuples)
        items.append({"name": f"{nspname}.{relname}", "schema": nspname, "table": relname,
                      "estimated_rows": estimated})
    items.sort(key=lambda item: (item["schema"], item["table"]))
    truncated = len(items) > lines
    return items[:lines], truncated


VERB_RUNNERS = {"migrations": run_migrations, "tables": run_tables}


# ---------------------------------------------------------------- main


def answer(data, status, items, truncated, message=None):
    verb = data.get("verb") if isinstance(data, dict) else None
    output = {"contract": CONTRACT, "adapter": ADAPTER, "capability": CAPABILITY,
              "verb": verb if isinstance(verb, str) and WORD_RE.match(verb) else "tables", "status": status,
              "items": items, "truncated": truncated}
    if message:
        output["message"] = message
    return output


def probe(data):
    try:
        verb, connection, declared, lines = check_input(data)
        check_passfile(connection["passfile"])
        items, truncated = VERB_RUNNERS[verb](Psql(connection), declared, lines)
    except ProbeError as error:
        return answer(data, "error", [], False, str(error))
    except (AttributeError, TypeError, ValueError, KeyError):
        # a shape not foreseen: still a fixed message, never a traceback
        return answer(data, "error", [], False, INVALID_ANSWER)
    return answer(data, "ok", items, truncated)


def main(argv):
    if argv == ["--describe"]:
        print(json.dumps(DESCRIBE))
        return 0
    if argv:
        print("uso: postgres.py --describe | postgres.py < entrada.json", file=sys.stderr)
        return 2
    try:
        data = json.loads(sys.stdin.read())
    except ValueError:
        data = None
    print(json.dumps(probe(data), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
