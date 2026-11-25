"""Adaptador postgres só de leitura: migrations e tabelas (SPEC-0099: UT-01 a UT-06, IT-01, IT-02, CT-01 e CT-02;
ADR-0010, ADR-0023, ADR-0025, ADR-0026).

Contrato (seção 6 da SPEC-0099) que estes testes fixam:

    assets/probes/postgres.py --describe ->
        {"contract": "probe@2", "adapter": "postgres", "capabilities": {"database": {"verbs": ["migrations",
         "tables"], "targets": ["datastore"], "access": ["database"]}}}
    entrada probe@2 no stdin (target.resource {kind: datastore, id, attrs}, target.database {user, name, passfile});
    saída probe@2 no stdout, exit 0 também no erro (status "error", items [], mensagem fixa).
    chamada: psql -X -w -q -A -t -v ON_ERROR_STOP=1 -h <host> -p <porta> -U <user> -d <name> -c <consulta>,
        ambiente sem PG* herdado (menos PGSSLMODE, PGSSLROOTCERT, PGSSLCERT, PGSSLKEY), mais PGPASSFILE, PGOPTIONS
        (default_transaction_read_only=on, statement_timeout=15000, lock_timeout=2000), PGCONNECT_TIMEOUT=10 e
        PGAPPNAME=boson-atlas-probe; cada consulta é de QUERIES e a resposta traz "ro".
    migrations -> itens {id, success, schema, table, tool, applied_at}, do mais recente ao mais antigo.
    tables -> itens {name, schema, table, estimated_rows}, em ordem de (schema, tabela).

Leituras desta suíte (listadas no relatório do test-writer):
    - A forma do JSON das respostas é a do dublê (fixtures/postgres/fake_psql.py): {"ro": "on"|"off", "rows": [...]};
      detect_migrations devolve {nspname, relname, columns}, list_tables {nspname, relname, reltuples} e
      read_<formato> as colunas do formato com os nomes da tabela de histórico. O dublê reconhece a consulta por
      pg_attribute (detecção), por relkind/reltuples (tabelas) e pelo "<schema>"."<tabela>" (leitura), e emula o
      servidor: aplica ORDER BY (... DESC), LIMIT e os filtros de relkind, relispartition e schemas do sistema que a
      consulta cita; na detecção devolve as tabelas cujo nome aparece como literal '<nome>' na consulta.
    - "No máximo 2 chamadas" (seção 5) vale para uma tabela de histórico; com n tabelas o teto é 1 + n (uma leitura
      por tabela, cada uma uma entrada de QUERIES), n <= 5.
    - applied_at é conferido só pelo prefixo "AAAA-MM-DDTHH:MM:SS" do valor gravado (o fuso do texto não está
      fixado); no Prisma a ordem não é conferida (finished_at pode ser nulo), só o id, o success e o applied_at.
    - "Pertence a QUERIES (depois de substituir os identificadores)": a consulta enviada, com os espaços
      normalizados, casa com algum texto de QUERIES em que os marcadores ({nome}, {}, %s, %(nome)s, $nome) valem
      identificadores, literais e números, sem ";" nem "--".
    - "Não cita outra tabela": todo FROM/JOIN aponta para pg_*, pg_catalog.*, information_schema.*, um CTE da própria
      consulta, uma função, uma subconsulta ou o "<schema>"."<tabela>" de histórico; nenhuma tabela da aplicação
      aparece no texto.
    - O timeout de 30 s do processo não é exercitado (a suíte ficaria lenta): o "tempo" vem do texto do psql.

Dublê: fixtures/postgres/fake_psql.py, copiado como `psql` numa pasta temporária (o único item do PATH nos testes
unitários), com o cenário em fake-psql.json ao lado; históricos gravados em fixtures/postgres/histories.json.
Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários; nenhum banco, nenhuma rede, nenhum ~/.pgpass real;
nomes acme, orders, billing e db-dev.acme.internal.
"""
import copy
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import SKILL, TESTS, Sandbox, fn, output
from test_probe import probes_yaml

SPEC = "SPEC-0099"
ADAPTER = SKILL / "assets" / "probes" / "postgres.py"
REFERENCE = SKILL / "references" / "probes" / "postgres.md"
FIXTURES = TESTS / "fixtures" / "postgres"
FAKE_PSQL = FIXTURES / "fake_psql.py"
HISTORIES = json.loads((FIXTURES / "histories.json").read_text(encoding="utf-8"))
ATLAS_FIXTURE = TESTS / "fixtures" / "probe-resource" / "atlas"

HOST = "db-dev.acme.internal"
DB_USER = "atlas_ro"
DB_NAME = "ordersdb"
SENTINEL = "sentinela-0099"
FORMATS = ("flyway", "rails", "golang-migrate", "ef", "alembic", "knex", "prisma")

DESCRIBE = {"contract": "probe@2", "adapter": "postgres",
            "capabilities": {"database": {"verbs": ["migrations", "tables"], "targets": ["datastore"],
                                          "access": ["database"]}}}
MIGRATION_KEYS = {"id", "success", "schema", "table", "tool", "applied_at"}
TABLE_KEYS = {"name", "schema", "table", "estimated_rows"}
PREFIX = ["psql", "-X", "-w", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

INVALID_INPUT = "entrada inválida"
ERRORS = {
    "auth": "falha de autenticação no banco",
    "no-password": "falha de autenticação no banco",
    "hba": "falha de autenticação no banco",
    "connect": "sem conexão com o banco",
    "refused": "sem conexão com o banco",
    "permission": "sem permissão no banco",
    "timeout": "consulta excedeu o tempo",
    "other": "falha do psql",
    "invalid-json": "resposta inválida do psql",
}
READ_ONLY_OFF = "sessão não ficou só de leitura"
NO_HISTORY = "nenhuma tabela de migrations encontrada"
UNKNOWN_FORMAT = "tabela de migrations em formato desconhecido"
WRITE_WORDS_RE = re.compile(r"(?i)\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|copy|lock|"
                            r"vacuum|analyze|call|set|reset|listen|notify|prepare|execute|explain)\b")
QUOTED_PAIR_RE = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*\.\s*"([A-Za-z_][A-Za-z0-9_]*)"')
NAME = r'(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_$]*)'
FROM_RE = re.compile(r"(?i)\b(\w+)?\s*\b(?:from|join)\s+(" + NAME + r"(?:\s*\.\s*" + NAME + r")?)\s*(\()?")
CTE_RE = re.compile(r"(?i)\b([A-Za-z_][A-Za-z0-9_]*)\s+as\s+(?:not\s+)?(?:materialized\s+)?\(")
NOT_TABLE_BEFORE = {"epoch", "year", "month", "day", "hour", "minute", "second", "both", "leading", "trailing",
                    "distinct"}
PLACEHOLDER_RE = re.compile(r"\{[A-Za-z0-9_]*\}|%\([A-Za-z0-9_]+\)s|%s|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")
PLACEHOLDER_VALUE = r"[A-Za-z0-9_\"'., ]*"
APP_TABLES = (("public", "orders"), ("public", "customers"), ("billing", "invoices"))


def f(name):
    return fn(name, "SPEC-0096")


# --------------------------------------------------------------------------- cenário do dublê


def history(fmt, nspname=None, relname=None, rows=None):
    data = copy.deepcopy(HISTORIES[fmt])
    entry = {"nspname": nspname or data["nspname"], "relname": relname or data["relname"],
             "columns": data["columns"], "rows": data["rows"] if rows is None else rows}
    return entry


def app_tables():
    """pg_class do cenário do UT-04, fora de ordem: tabelas em public e billing, uma do sistema, uma partição filha,
    uma visão, uma nunca analisada (reltuples -1) e uma partição mãe com reltuples quebrado (50.4)."""
    return [
        {"nspname": "public", "relname": "orders", "relkind": "r", "relispartition": False, "reltuples": 1199.6},
        {"nspname": "pg_catalog", "relname": "pg_class", "relkind": "r", "relispartition": False, "reltuples": 400.0},
        {"nspname": "billing", "relname": "invoices_2026_11", "relkind": "r", "relispartition": True,
         "reltuples": 30.0},
        {"nspname": "public", "relname": "customers", "relkind": "r", "relispartition": False, "reltuples": -1.0},
        {"nspname": "public", "relname": "order_totals", "relkind": "v", "relispartition": False, "reltuples": 0.0},
        {"nspname": "billing", "relname": "invoices", "relkind": "p", "relispartition": False, "reltuples": 50.4},
        {"nspname": "information_schema", "relname": "sql_features", "relkind": "r", "relispartition": False,
         "reltuples": 700.0},
    ]


EXPECTED_TABLES = [
    {"name": "billing.invoices", "schema": "billing", "table": "invoices", "estimated_rows": 50},
    {"name": "public.customers", "schema": "public", "table": "customers", "estimated_rows": None},
    {"name": "public.orders", "schema": "public", "table": "orders", "estimated_rows": 1200},
]


def base_scenario(*formats):
    formats = formats or ("flyway",)
    return {"ro": "on", "histories": [history(fmt) for fmt in formats], "tables": app_tables(), "fail": []}


def install_psql(folder: Path, scenario: dict, record: Path):
    """Copia o dublê como `psql` (cabeçalho com o Python dos testes) e grava o cenário ao lado dele."""
    folder.mkdir(parents=True, exist_ok=True)
    body = FAKE_PSQL.read_text(encoding="utf-8").split("\n", 1)[1]
    target = folder / "psql"
    target.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (folder / "fake-psql.json").write_text(json.dumps(dict(scenario, record=str(record))), encoding="utf-8")
    return target


def read_records(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def probe_input(verb, attrs=None, passfile="/nonexistent/.pgpass", user=DB_USER, name=DB_NAME, lines=200,
                kind="datastore", rid="orders-db"):
    if attrs is None:
        attrs = {"engine": "postgres", "host": HOST}
    return {"contract": "probe@2", "capability": "database", "verb": verb,
            "target": {"service": "api", "environment": "dev", "deployment": "dev-api",
                       "resource": {"kind": kind, "id": rid, "attrs": attrs},
                       "database": {"user": user, "name": name, "passfile": str(passfile)}},
            "limits": {"lines": lines, "since_seconds": 1800}}


def load_queries():
    """Os textos da constante QUERIES do adaptador (dict, lista ou tupla; textos dentro de estruturas também)."""
    spec = importlib.util.spec_from_file_location("postgres_probe_0099", ADAPTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    queries = getattr(module, "QUERIES", None)
    if queries is None:
        raise AssertionError(f"postgres.py sem a constante QUERIES ({SPEC})")
    texts = []

    def walk(value):
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(queries)
    return texts


def normalized(text):
    return " ".join(text.split())


def template_regex(template):
    text = normalized(template)
    uses_format = bool(re.search(r"\{[A-Za-z0-9_]*\}", text.replace("{{", "").replace("}}", "")))
    parts, last = [], 0
    for match in PLACEHOLDER_RE.finditer(text):
        literal = text[last:match.start()]
        if uses_format:
            literal = literal.replace("{{", "{").replace("}}", "}")
        parts.append(re.escape(literal))
        parts.append(PLACEHOLDER_VALUE)
        last = match.end()
    tail = text[last:]
    if uses_format:
        tail = tail.replace("{{", "{").replace("}}", "}")
    parts.append(re.escape(tail))
    return re.compile("".join(parts), re.DOTALL)


def query_problems(query, templates, history_tables) -> list:
    """SPEC-0099:UT-05 — problemas de uma consulta enviada ao psql; [] = permitida."""
    problems = []
    text = normalized(query)
    upper = text.upper()
    if ";" in text:
        problems.append("a consulta tem ;")
    if "--" in text or "/*" in text:
        problems.append("a consulta tem comentário")
    if not (upper.startswith("SELECT ") or (upper.startswith("WITH ") and " SELECT " in f" {upper} ")):
        problems.append("a consulta não começa por SELECT nem por WITH ... SELECT")
    words = sorted({w.lower() for w in WRITE_WORDS_RE.findall(text)})
    if words:
        problems.append(f"palavras fora de leitura: {words}")
    if not any(regex.fullmatch(text) for regex in templates):
        problems.append("a consulta não pertence a QUERIES")
    allowed_pairs = {(s, t) for s, t in history_tables}
    for pair in QUOTED_PAIR_RE.findall(text):
        if pair not in allowed_pairs:
            problems.append(f"identificador fora das tabelas de histórico: {pair}")
    ctes = {name.lower() for name in CTE_RE.findall(text)}
    for before, target, call in FROM_RE.findall(text):
        if call or (before and before.lower() in NOT_TABLE_BEFORE):
            continue
        plain = target.replace('"', "").replace(" ", "")
        low = plain.lower()
        quoted = QUOTED_PAIR_RE.fullmatch(target.replace(" ", ""))
        if quoted and quoted.groups() in allowed_pairs:
            continue
        if low.startswith(("pg_", "pg_catalog.", "information_schema.")) or low in ctes or low == "lateral":
            continue
        problems.append(f"FROM/JOIN fora do catálogo e do histórico: {target}")
    for schema, table in APP_TABLES:
        if f"{schema}.{table}" in text or f'"{table}"' in text:
            problems.append(f"a consulta cita a tabela da aplicação {schema}.{table}")
    return problems


def table_4a_problems(verb, out) -> list:
    """SPEC-0099:CT-02 — a conferência da tabela 4a do ADR-0026 (o que o verify@2 lê) sobre uma saída ok."""
    items = out.get("items")
    if not isinstance(items, list):
        return ["items não é lista"]
    problems = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"items[{index}] não é objeto")
            continue
        if verb == "migrations":
            if not (isinstance(item.get("id"), str) and item["id"].strip()):
                problems.append(f"items[{index}].id precisa ser texto não vazio")
            if not isinstance(item.get("success"), bool):
                problems.append(f"items[{index}].success precisa ser booleano")
        else:
            name = item.get("name")
            if not (isinstance(name, str) and re.match(r"^[^.\s]+\.[^.\s]+\Z", name)):
                problems.append(f"items[{index}].name fora de <schema>.<tabela>")
            elif name != f"{item.get('schema')}.{item.get('table')}":
                problems.append(f"items[{index}].name diferente de schema.table")
    return problems


# --------------------------------------------------------------------------- base


class PostgresCase(unittest.TestCase):
    """Uma pasta temporária por teste: HOME, configuração, o arquivo de senhas 0600 e a pasta do psql falso (o único
    item do PATH)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.record = self.root / "psql-calls.jsonl"
        secrets = self.root / "secrets"
        secrets.mkdir()
        self.passfile = secrets / "pgpass-0099"
        self.passfile.write_text(f"{HOST}:5432:{DB_NAME}:{DB_USER}:senha-falsa-0099\n", encoding="utf-8")
        os.chmod(self.passfile, 0o600)
        self.scenario = base_scenario()
        self.extra_env = {}

    def install(self, scenario=None):
        self.record.unlink(missing_ok=True)
        install_psql(self.bin, self.scenario if scenario is None else scenario, self.record)

    def environment(self, with_psql=True):
        path = self.bin if with_psql else self.root / "empty-bin"
        path.mkdir(exist_ok=True)
        env = {"PATH": str(path), "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
               "ATLAS_CONFIG_HOME": str(self.root / "config-home"), "LANG": "C.UTF-8"}
        for name in ("TMPDIR", "SYSTEMROOT"):
            if name in os.environ:
                env[name] = os.environ[name]
        env.update(self.extra_env)
        return env

    def adapter(self, *args, stdin="", with_psql=True):
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        result = subprocess.run([sys.executable, str(ADAPTER), *args], input=stdin, capture_output=True, text=True,
                                cwd=self.root, env=self.environment(with_psql), timeout=180, check=False)
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        return result

    def data(self, verb, **kwargs):
        kwargs.setdefault("passfile", self.passfile)
        return probe_input(verb, **kwargs)

    def run_probe(self, data, with_psql=True, raw=None):
        """Roda o adaptador; confere exit 0, a saída probe@2 (validador do núcleo), o pedido ecoado, nenhum host,
        usuário, banco, caminho do arquivo de senhas nem stderr do psql na saída, e cada consulta contra a lista
        fechada (UT-05)."""
        result = self.adapter(stdin=raw if raw is not None else json.dumps(data), with_psql=with_psql)
        self.assertEqual(result.returncode, 0, output(result))
        text = output(result)
        for value in (HOST, DB_USER, DB_NAME, str(self.passfile), self.passfile.name, SENTINEL, "senha-falsa"):
            self.assertNotIn(value, text, f"{value} apareceu na saída do adaptador")
        out = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(out), [], out)
        self.assertEqual({k: out.get(k) for k in ("contract", "adapter", "capability")},
                         {"contract": "probe@2", "adapter": "postgres", "capability": "database"})
        if isinstance(data, dict):
            self.assertEqual(out.get("verb"), data["verb"])
            self.assertAllowedCalls(data)
        return out

    def records(self):
        return read_records(self.record)

    def queries(self):
        return [r["argv"][-1] for r in self.records()]

    def assertAllowedCalls(self, data):
        """SPEC-0099:UT-01/UT-05 — todo argv na forma única, toda consulta da lista fechada e os máximos da seção 5."""
        # SPEC-0099:UT-05
        records = self.records()
        if not records:
            return
        templates = [template_regex(t) for t in load_queries()]
        tables = [(h["nspname"], h["relname"]) for h in self.current_scenario().get("histories") or []]
        target = data["target"]
        port = str((target["resource"]["attrs"] or {}).get("port", 5432))
        for row in records:
            argv = ["psql", *row["argv"]]
            self.assertTrue(row["allowed"], f"chamada recusada pelo dublê: {argv[:-1]}")
            self.assertEqual(argv[:-1], PREFIX + ["-h", target["resource"]["attrs"].get("host"), "-p", port,
                                                  "-U", target["database"]["user"], "-d",
                                                  target["database"]["name"], "-c"])
            self.assertEqual(query_problems(argv[-1], templates, tables), [], argv[-1])
        kinds = [row["query"] for row in records]
        if data["verb"] == "tables":
            self.assertEqual(kinds, ["list"], kinds)
        elif data["verb"] == "migrations":
            self.assertEqual(kinds[0], "detect", kinds)
            self.assertEqual(kinds.count("detect"), 1, kinds)
            self.assertLessEqual(kinds.count("read"), 5, kinds)
            self.assertNotIn("list", kinds)

    def current_scenario(self):
        path = self.bin / "fake-psql.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def assertError(self, out, message):
        self.assertEqual(out["status"], "error", out)
        self.assertEqual(out["items"], [], out)
        self.assertEqual(out.get("message"), message, out)

    def migrations(self, data=None):
        out = self.run_probe(data or self.data("migrations"))
        self.assertEqual(out["status"], "ok", out)
        for item in out["items"]:
            self.assertEqual(set(item), MIGRATION_KEYS, item)
        return out

    def assertExpected(self, fmt, items, schema=None, table=None):
        expected = HISTORIES[fmt]["expected"]
        schema = schema or HISTORIES[fmt]["nspname"]
        table = table or HISTORIES[fmt]["relname"]
        got = [(i["id"], i["success"]) for i in items]
        if fmt == "prisma":
            self.assertEqual(sorted(got), sorted((e[0], e[1]) for e in expected), items)
        else:
            self.assertEqual(got, [(e[0], e[1]) for e in expected], items)
        by_id = {i["id"]: i for i in items}
        for ident, _, stamp in expected:
            item = by_id[ident]
            self.assertIs(type(item["success"]), bool, item)
            self.assertEqual((item["schema"], item["table"], item["tool"]), (schema, table, fmt), item)
            if stamp is None:
                self.assertIsNone(item["applied_at"], item)
            else:
                self.assertIsInstance(item["applied_at"], str, item)
                self.assertTrue(STAMP_RE.match(item["applied_at"]), item)
                self.assertTrue(item["applied_at"].startswith(stamp), item)


# --------------------------------------------------------------------------- UT-01


class CallTest(PostgresCase):
    def test_argv_and_environment_of_the_call(self):
        """SPEC-0099:UT-01 — tables com attrs.host db-dev.acme.internal e sem port, e o ambiente do adaptador com
        PGPASSWORD, PGHOST, PGSERVICE e PGSSLMODE: argv exato com -p 5432; PGPASSFILE do passfile da entrada,
        PGOPTIONS só leitura com os tempos, PGCONNECT_TIMEOUT=10, PGAPPNAME, PGSSLMODE mantido, sem PGPASSWORD,
        PGHOST nem PGSERVICE."""
        # SPEC-0099:UT-01
        self.install()
        self.extra_env = {"PGPASSWORD": "senha-falsa-env", "PGHOST": "outro-host.acme.internal",
                          "PGSERVICE": "acme-service", "PGSSLMODE": "require", "PGUSER": "postgres",
                          "PGDATABASE": "postgres", "PGPORT": "5433"}
        out = self.run_probe(self.data("tables"))
        self.assertEqual(out["status"], "ok", out)
        records = self.records()
        self.assertEqual(len(records), 1, records)
        argv = ["psql", *records[0]["argv"]]
        self.assertEqual(argv[:-1], PREFIX + ["-h", HOST, "-p", "5432", "-U", DB_USER, "-d", DB_NAME, "-c"])
        env = records[0]["env"]
        self.assertEqual(env.get("PGPASSFILE"), str(self.passfile))
        options = env.get("PGOPTIONS", "")
        settings = dict(re.findall(r"-c\s*([a-z_]+)\s*=\s*(\S+)", options))
        self.assertEqual(settings, {"default_transaction_read_only": "on", "statement_timeout": "15000",
                                    "lock_timeout": "2000"}, options)
        self.assertEqual(env.get("PGCONNECT_TIMEOUT"), "10")
        self.assertEqual(env.get("PGAPPNAME"), "boson-atlas-probe")
        self.assertEqual(env.get("PGSSLMODE"), "require")
        for name in ("PGPASSWORD", "PGHOST", "PGSERVICE", "PGUSER", "PGDATABASE", "PGPORT"):
            self.assertNotIn(name, env, f"{name} herdado chegou ao psql")
        allowed = {"PGPASSFILE", "PGOPTIONS", "PGCONNECT_TIMEOUT", "PGAPPNAME", "PGSSLMODE", "PGSSLROOTCERT",
                   "PGSSLCERT", "PGSSLKEY"}
        self.assertEqual(set(env) - allowed, set(), env)

    def test_port_from_the_attribute(self):
        """SPEC-0099:UT-01 — attrs.port 6432 (número) ou "6432" (texto): -p 6432."""
        # SPEC-0099:UT-01
        for port in (6432, "6432"):
            with self.subTest(port=port):
                self.install()
                attrs = {"engine": "postgres", "host": HOST, "port": port}
                out = self.run_probe(self.data("tables", attrs=attrs))
                self.assertEqual(out["status"], "ok", out)
                argv = self.records()[0]["argv"]
                self.assertEqual(argv[argv.index("-p") + 1], "6432")

    def test_aurora_engine_in_any_case(self):
        """SPEC-0099:UT-01 — engine "Aurora-PostgreSQL" (sem diferenciar maiúsculas) é aceito."""
        # SPEC-0099:UT-01
        self.install()
        out = self.run_probe(self.data("tables", attrs={"engine": "Aurora-PostgreSQL", "host": HOST}))
        self.assertEqual(out["status"], "ok", out)


# --------------------------------------------------------------------------- UT-02


class MigrationsTest(PostgresCase):
    def test_each_history_format(self):
        """SPEC-0099:UT-02 — Flyway, Rails, golang-migrate, EF, Alembic, Knex e Prisma: itens só com id, success,
        schema, table, tool e applied_at, do mais recente ao mais antigo; applied_at null em rails, golang-migrate,
        ef e alembic; Flyway success=false, golang-migrate dirty e Prisma pendente ou desfeita dão success false."""
        # SPEC-0099:UT-02
        for fmt in FORMATS:
            with self.subTest(format=fmt):
                self.install(base_scenario(fmt))
                out = self.migrations()
                self.assertIn(out.get("truncated"), (None, False), out)
                self.assertExpected(fmt, out["items"])
                self.assertLessEqual(len(self.records()), 2, [r["query"] for r in self.records()])

    def test_more_rows_than_the_limit(self):
        """SPEC-0099:UT-02 — 300 migrations Flyway e lines 100: as 100 mais recentes e truncated true."""
        # SPEC-0099:UT-02
        rows = [{"version": str(n), "description": f"m{n}", "installed_on": f"2026-{1 + n // 28 % 12:02d}-"
                 f"{1 + n % 28:02d}T10:00:00", "success": True} for n in range(1, 301)]
        rows.sort(key=lambda r: r["installed_on"])
        scenario = base_scenario()
        scenario["histories"] = [history("flyway", rows=rows)]
        self.install(scenario)
        out = self.migrations(self.data("migrations", lines=100))
        self.assertEqual(len(out["items"]), 100, out)
        self.assertIs(out.get("truncated"), True, out)
        newest = [r["version"] for r in reversed(rows)][:100]
        self.assertEqual([i["id"] for i in out["items"]], newest)

    def test_more_than_five_history_tables(self):
        """SPEC-0099:UT-02 — 6 tabelas de histórico (um schema por cliente): lidas as 5 primeiras por (schema,
        tabela), truncated true, nenhuma leitura da sexta."""
        # SPEC-0099:UT-02
        tenants = ["tenant_f", "tenant_c", "tenant_a", "tenant_e", "tenant_b", "tenant_d"]
        scenario = base_scenario()
        scenario["histories"] = [history("flyway", nspname=t) for t in tenants]
        self.install(scenario)
        out = self.migrations()
        self.assertIs(out.get("truncated"), True, out)
        self.assertEqual({i["schema"] for i in out["items"]},
                         {"tenant_a", "tenant_b", "tenant_c", "tenant_d", "tenant_e"})
        self.assertEqual(len(out["items"]), 5 * len(HISTORIES["flyway"]["rows"]), out)
        self.assertFalse([q for q in self.queries() if '"tenant_f"' in q], "a sexta tabela foi lida")
        self.assertLessEqual(len(self.records()), 6)


# --------------------------------------------------------------------------- UT-03


class MigrationsTableTest(PostgresCase):
    def test_declared_table_with_flyway_columns(self):
        """SPEC-0099:UT-03 — attrs.migrations_table ops.db_history com as colunas do Flyway: a detecção procura essa
        tabela e os itens saem com tool flyway e table db_history."""
        # SPEC-0099:UT-03
        scenario = base_scenario()
        scenario["histories"] = [history("flyway", nspname="ops", relname="db_history")]
        self.install(scenario)
        attrs = {"engine": "postgres", "host": HOST, "migrations_table": "ops.db_history"}
        out = self.migrations(self.data("migrations", attrs=attrs))
        self.assertExpected("flyway", out["items"], schema="ops", table="db_history")
        detect = self.queries()[0]
        self.assertIn("'db_history'", detect)

    def test_declared_table_without_schema(self):
        """SPEC-0099:UT-03 — attrs.migrations_table só com a tabela (db_history, em public): lida como flyway."""
        # SPEC-0099:UT-03
        scenario = base_scenario()
        scenario["histories"] = [history("flyway", relname="db_history")]
        self.install(scenario)
        attrs = {"engine": "postgres", "host": HOST, "migrations_table": "db_history"}
        out = self.migrations(self.data("migrations", attrs=attrs))
        self.assertExpected("flyway", out["items"], table="db_history")

    def test_declared_table_in_an_unknown_format(self):
        """SPEC-0099:UT-03 — a mesma tabela com colunas de nenhum formato: "tabela de migrations em formato
        desconhecido"."""
        # SPEC-0099:UT-03
        scenario = base_scenario()
        scenario["histories"] = [{"nspname": "ops", "relname": "db_history", "columns": ["step", "applied"],
                                  "rows": [{"step": "a", "applied": True}]}]
        self.install(scenario)
        attrs = {"engine": "postgres", "host": HOST, "migrations_table": "ops.db_history"}
        out = self.run_probe(self.data("migrations", attrs=attrs))
        self.assertError(out, UNKNOWN_FORMAT)

    def test_database_without_history(self):
        """SPEC-0099:UT-03 — banco sem nenhuma tabela conhecida: "nenhuma tabela de migrations encontrada", sem
        itens e sem leitura."""
        # SPEC-0099:UT-03
        scenario = base_scenario()
        scenario["histories"] = []
        self.install(scenario)
        out = self.run_probe(self.data("migrations"))
        self.assertError(out, NO_HISTORY)
        self.assertEqual([r["query"] for r in self.records()], ["detect"])


# --------------------------------------------------------------------------- UT-04


class TablesTest(PostgresCase):
    def test_only_application_tables(self):
        """SPEC-0099:UT-04 — public e billing, sem pg_catalog, information_schema, partição filha nem visão; ordem
        (schema, tabela); name schema.tabela; estimated_rows inteiro arredondado ou null (reltuples -1)."""
        # SPEC-0099:UT-04
        self.install()
        out = self.run_probe(self.data("tables"))
        self.assertEqual(out["status"], "ok", out)
        for item in out["items"]:
            self.assertEqual(set(item), TABLE_KEYS, item)
        self.assertEqual(out["items"], EXPECTED_TABLES)
        for item in out["items"]:
            self.assertTrue(item["estimated_rows"] is None or type(item["estimated_rows"]) is int, item)
        self.assertIn(out.get("truncated"), (None, False), out)

    def test_more_tables_than_the_limit(self):
        """SPEC-0099:UT-04 — 3 tabelas da aplicação e lines 2: as 2 primeiras por (schema, tabela), truncated true."""
        # SPEC-0099:UT-04
        self.install()
        out = self.run_probe(self.data("tables", lines=2))
        self.assertEqual(out["items"], EXPECTED_TABLES[:2])
        self.assertIs(out.get("truncated"), True, out)


# --------------------------------------------------------------------------- UT-05


class AllowListTest(PostgresCase):
    def test_every_query_of_every_scenario_is_in_the_list(self):
        """SPEC-0099:UT-05 — em todos os formatos e em tables, toda consulta pertence a QUERIES, começa por SELECT ou
        WITH ... SELECT, não escreve, não tem ; e só cita catálogo ou a tabela de histórico detectada (run_probe)."""
        # SPEC-0099:UT-05
        self.install()
        self.run_probe(self.data("tables"))
        self.assertTrue(self.records())
        for fmt in FORMATS:
            with self.subTest(format=fmt):
                self.install(base_scenario(fmt))
                self.run_probe(self.data("migrations"))
                self.assertTrue(self.records())

    def test_queries_constant_is_read_only(self):
        """SPEC-0099:UT-05 — cada texto de QUERIES começa por SELECT ou WITH, não tem ; nem palavra de escrita."""
        # SPEC-0099:UT-05
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        texts = load_queries()
        self.assertGreaterEqual(len(texts), 9, "QUERIES precisa de detect, list e um read por formato (7)")
        for text in texts:
            norm = normalized(text)
            self.assertTrue(norm.upper().startswith(("SELECT ", "WITH ")), norm[:60])
            self.assertNotIn(";", norm)
            self.assertEqual(WRITE_WORDS_RE.findall(norm), [], norm[:80])
            self.assertFalse(re.search(r"(?i)\bselect\s+\*|\.\*", norm), f"SELECT * em QUERIES: {norm[:80]}")

    def test_the_check_refuses_bad_queries(self):
        """SPEC-0099:UT-05 — a conferência recusa escrita, ;, CTE de escrita e tabela da aplicação."""
        # SPEC-0099:UT-05
        templates = [re.compile(".*", re.DOTALL)]
        for query in ("DELETE FROM pg_class", "SELECT 1; DROP TABLE orders",
                      "WITH x AS (INSERT INTO t VALUES (1) RETURNING 1) SELECT * FROM x",
                      "SELECT json_agg(o) FROM public.orders o", 'SELECT 1 FROM "public"."orders"'):
            with self.subTest(query=query):
                self.assertTrue(query_problems(query, templates, [("public", "flyway_schema_history")]))
        ok = ("SELECT json_build_object('ro', current_setting('transaction_read_only')) FROM pg_catalog.pg_class c "
              "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace")
        self.assertEqual(query_problems(ok, templates, []), [])

    def test_malicious_migrations_table_is_refused_without_any_call(self):
        """SPEC-0099:UT-05 — migrations_table com aspas, ;, espaço, -, ponto demais ou nome longo: "entrada
        inválida" e nenhuma chamada."""
        # SPEC-0099:UT-05
        for value in ('x"; drop table orders; --', "public.orders limit 1", "-x", "a b", "a.b.c", "1abc",
                      "x" * 64, "public."):
            with self.subTest(value=value):
                self.install()
                attrs = {"engine": "postgres", "host": HOST, "migrations_table": value}
                out = self.run_probe(self.data("migrations", attrs=attrs))
                self.assertError(out, INVALID_INPUT)
                self.assertEqual(self.records(), [])

    def test_inputs_out_of_the_rule_are_refused_without_any_call(self):
        """SPEC-0099:UT-05 — host, usuário ou banco com =, espaço, / ou começando com -; porta fora de 1..65535;
        passfile relativo; engine mysql ou ausente; sem host; verbo query: o erro fixo do contrato e nenhuma
        chamada."""
        # SPEC-0099:UT-05
        attrs = {"engine": "postgres", "host": HOST}
        cases = []
        for bad in ("db=x", "db x", "db/x", "-db", "db\nx", "a" * 254):
            cases.append((f"host {bad!r}", "tables", {"attrs": dict(attrs, host=bad)}, INVALID_INPUT))
        for bad in ("ro=x", "ro x", "ro/x", "-ro", "r\to", "r" * 64):
            cases.append((f"user {bad!r}", "tables", {"user": bad}, INVALID_INPUT))
            cases.append((f"name {bad!r}", "tables", {"name": bad}, INVALID_INPUT))
        for bad in (0, 70000, "abc", "-1", True, 5432.5):
            cases.append((f"port {bad!r}", "tables", {"attrs": dict(attrs, port=bad)}, INVALID_INPUT))
        cases += [
            ("passfile relativo", "tables", {"passfile": "secrets/pgpass-0099"}, INVALID_INPUT),
            ("engine mysql", "tables", {"attrs": dict(attrs, engine="mysql")}, "engine não suportado"),
            ("engine ausente", "migrations", {"attrs": {"host": HOST}}, "engine não suportado"),
            ("sem host", "tables", {"attrs": {"engine": "postgres"}}, "recurso sem host no atlas"),
            ("verbo query", "query", {}, "verbo não suportado"),
        ]
        for label, verb, kwargs, message in cases:
            with self.subTest(case=label):
                self.install()
                out = self.run_probe(self.data(verb, **kwargs))
                self.assertError(out, message)
                self.assertEqual(self.records(), [], label)


# --------------------------------------------------------------------------- UT-06


class ErrorTest(PostgresCase):
    def test_psql_failures_become_fixed_messages(self):
        """SPEC-0099:UT-06 — o dublê sai com 2 e o stderr de autenticação, conexão, permissão, tempo ou outro texto,
        ou com exit 0 e stdout que não é JSON: status error com a mensagem do contrato, items [] e exit 0, sem host,
        usuário, banco, passfile nem o stderr (run_probe)."""
        # SPEC-0099:UT-06
        for mode, message in ERRORS.items():
            for verb in ("migrations", "tables"):
                with self.subTest(mode=mode, verb=verb):
                    scenario = base_scenario()
                    scenario["fail"] = [{"mode": mode}]
                    self.install(scenario)
                    out = self.run_probe(self.data(verb))
                    self.assertError(out, message)

    def test_permission_denied_on_the_history_read(self):
        """SPEC-0099:UT-06 — a detecção acha a tabela pelo catálogo e a leitura sem GRANT falha: "sem permissão no
        banco" (não "nenhuma tabela de migrations encontrada")."""
        # SPEC-0099:UT-06
        scenario = base_scenario()
        scenario["fail"] = [{"mode": "permission", "query": "read"}]
        self.install(scenario)
        out = self.run_probe(self.data("migrations"))
        self.assertError(out, ERRORS["permission"])

    def test_session_not_read_only(self):
        """SPEC-0099:UT-06 — resposta com "ro": "off" (em todas as consultas, ou só na leitura, como um pooler que
        descartou o PGOPTIONS): "sessão não ficou só de leitura", sem itens."""
        # SPEC-0099:UT-06
        for verb, change in (("tables", {"ro": "off"}), ("migrations", {"ro": "off"}),
                             ("migrations", {"ro_off_for": ["read"]})):
            with self.subTest(verb=verb, change=change):
                scenario = base_scenario()
                scenario.update(change)
                self.install(scenario)
                out = self.run_probe(self.data(verb))
                self.assertError(out, READ_ONLY_OFF)

    def test_without_psql_on_the_path(self):
        """SPEC-0099:UT-06 — sem psql no PATH: "psql não encontrado", exit 0."""
        # SPEC-0099:UT-06
        for verb in ("migrations", "tables"):
            with self.subTest(verb=verb):
                out = self.run_probe(self.data(verb), with_psql=False)
                self.assertError(out, "psql não encontrado")

    def test_passfile_missing_or_open(self):
        """SPEC-0099:UT-06 — arquivo de senhas ausente ou 0644 (POSIX): mensagem fixa sem o caminho e nenhuma
        chamada."""
        # SPEC-0099:UT-06
        self.install()
        out = self.run_probe(self.data("tables", passfile=self.root / "secrets" / "missing-0099"))
        self.assertError(out, "arquivo de senhas não encontrado")
        self.assertEqual(self.records(), [])
        if os.name == "posix":
            os.chmod(self.passfile, 0o644)
            out = self.run_probe(self.data("migrations"))
            self.assertError(out, "arquivo de senhas com permissão aberta (use chmod 600)")
            self.assertEqual(self.records(), [])


# --------------------------------------------------------------------------- CT-02


class Table4aTest(PostgresCase):
    def real_outputs(self):
        outputs = []
        for fmt in FORMATS:
            self.install(base_scenario(fmt))
            outputs.append(self.migrations())
        self.install()
        tables = self.run_probe(self.data("tables"))
        return outputs, tables

    def test_real_outputs_follow_table_4a(self):
        """SPEC-0099:CT-02 — itens reais de migrations (7 formatos, com falhas e pendentes) e de tables cumprem a
        tabela 4a do ADR-0026: id texto não vazio e success booleano, false exatamente nas falhas, dirty e
        pendentes; name <schema>.<tabela> igual a schema + "." + table."""
        # SPEC-0099:CT-02
        migrations, tables = self.real_outputs()
        failed = {(fmt, e[0]) for fmt in FORMATS for e in HISTORIES[fmt]["expected"] if not e[1]}
        self.assertEqual(len(failed), 4)
        for fmt, out in zip(FORMATS, migrations):
            self.assertEqual(table_4a_problems("migrations", out), [], fmt)
            for item in out["items"]:
                self.assertEqual(item["success"], (fmt, item["id"]) not in failed, item)
        self.assertEqual(table_4a_problems("tables", tables), [])
        self.assertEqual(len(tables["items"]), 3)

    def test_the_same_check_refuses_broken_items(self):
        """SPEC-0099:CT-02 — a mesma conferência recusa item de migrations sem success ou com success texto, e item
        de tables com name sem o schema."""
        # SPEC-0099:CT-02
        migrations, tables = self.real_outputs()
        out = migrations[0]
        missing = copy.deepcopy(out)
        del missing["items"][0]["success"]
        self.assertTrue(table_4a_problems("migrations", missing))
        text = copy.deepcopy(out)
        text["items"][0]["success"] = "true"
        self.assertTrue(table_4a_problems("migrations", text))
        bare = copy.deepcopy(tables)
        bare["items"][0]["name"] = bare["items"][0]["table"]
        self.assertTrue(table_4a_problems("tables", bare))


# --------------------------------------------------------------------------- CT-01

DOC_BLOCK_RE = re.compile(r"```json probe@2 (describe|input|output) (valid|invalid)[ \t]*\n(.*?)```", re.DOTALL)
VALIDATORS = {"describe": "validate_probe_describe", "input": "validate_probe_input",
              "output": "validate_probe_output"}


class ContractTest(PostgresCase):
    def test_describe_follows_probe_2(self):
        """SPEC-0099:CT-01 — `postgres.py --describe` imprime exatamente a descrição do contrato, aceita pelo
        validate_probe_describe do núcleo, sem chamar o psql."""
        # SPEC-0099:CT-01
        self.install()
        result = self.adapter("--describe")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(data, DESCRIBE)
        self.assertEqual(f("validate_probe_describe")(data), [])
        self.assertEqual(self.records(), [])

    def test_real_outputs_pass_the_core_validator(self):
        """SPEC-0099:CT-01 — as entradas usadas passam no validate_probe_input; as saídas reais do UT-02, do UT-04 e
        do UT-06 passam no validate_probe_output (run_probe)."""
        # SPEC-0099:CT-01
        cases = [("", "migrations"), ("", "tables"), ("auth", "migrations"), ("timeout", "tables")]
        for mode, verb in cases:
            with self.subTest(mode=mode, verb=verb):
                data = self.data(verb)
                self.assertEqual(f("validate_probe_input")(data), [])
                scenario = base_scenario()
                scenario["fail"] = [{"mode": mode}] if mode else []
                self.install(scenario)
                out = self.run_probe(data)
                self.assertEqual(out["status"], "error" if mode else "ok", out)

    def test_examples_of_the_reference(self):
        """SPEC-0099:CT-01 — references/probes/postgres.md traz blocos ```json probe@2 <describe|output>
        <valid|invalid>: describe válido; saídas válidas de migrations, de tables e de erro; describe com targets
        ["deployment"], saída com item aninhado e saída com chave fora do contrato inválidos; os válidos passam e os
        inválidos são recusados com motivo."""
        # SPEC-0099:CT-01
        self.assertTrue(REFERENCE.is_file(), f"{REFERENCE.relative_to(SKILL)} não existe ({SPEC})")
        text = REFERENCE.read_text(encoding="utf-8")
        blocks = [(m.group(1), m.group(2), json.loads(m.group(3))) for m in DOC_BLOCK_RE.finditer(text)]
        valid_describe = [b for b in blocks if b[:2] == ("describe", "valid")]
        self.assertTrue(valid_describe, "sem bloco describe valid")
        valid_outputs = [b[2] for b in blocks if b[:2] == ("output", "valid")]
        verbs = {(o.get("verb"), o.get("status")) for o in valid_outputs}
        for pair in (("migrations", "ok"), ("tables", "ok")):
            self.assertIn(pair, verbs, f"sem saída válida de {pair}")
        self.assertTrue([o for o in valid_outputs if o.get("status") == "error"], "sem saída de erro válida")
        invalid_describe = [b[2] for b in blocks if b[:2] == ("describe", "invalid")]
        self.assertTrue([d for d in invalid_describe
                         if ((d.get("capabilities") or {}).get("database") or {}).get("targets") == ["deployment"]],
                        "sem describe inválido com targets [deployment]")
        self.assertGreaterEqual(len([b for b in blocks if b[:2] == ("output", "invalid")]), 2,
                                "menos de 2 blocos output invalid (item aninhado e chave fora do contrato)")
        for kind, verdict, data in blocks:
            with self.subTest(kind=kind, verdict=verdict, data=json.dumps(data)[:80]):
                problems = f(VALIDATORS[kind])(data)
                if verdict == "valid":
                    self.assertEqual(problems, [])
                else:
                    self.assertTrue(problems and all(isinstance(p, str) and p for p in problems), problems)
        for data in valid_outputs:
            if data.get("status") == "ok" and data.get("verb") in ("migrations", "tables"):
                self.assertEqual(table_4a_problems(data["verb"], data), [], data)


# --------------------------------------------------------------------------- IT-01 e IT-02


class EndToEndTest(unittest.TestCase):
    """Atlas temporário (cópia de fixtures/probe-resource/atlas, com datastore:orders-db em db-dev.acme.internal e a
    aresta depends_on do deployment dev-api), access.databases.orders-db com um arquivo de senhas 0600, o adaptador
    postgres sem command e o psql falso no início do PATH."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        shutil.copytree(ATLAS_FIXTURE, self.box.atlas)
        graph_path = self.box.atlas / "graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        node = next(n for n in graph["nodes"] if n["key"] == "datastore:orders-db")
        node["attrs"] = {"engine": "postgres", "host": HOST}
        graph["edges"].append({"from": "deployment:dev-api", "inferred": False, "sources": ["facts"],
                               "to": "datastore:orders-db", "type": "depends_on"})
        graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        secrets = self.box.root / "secrets"
        secrets.mkdir()
        self.passfile = secrets / "pgpass-0099"
        self.passfile.write_text(f"{HOST}:5432:{DB_NAME}:{DB_USER}:senha-falsa-0099\n", encoding="utf-8")
        os.chmod(self.passfile, 0o600)
        adapter = '    postgres:\n      verbs: ["migrations", "tables"]\n      timeout: 120\n'
        access = (f"access:\n  databases:\n    \"orders-db\": {{user: {json.dumps(DB_USER)}, database: "
                  f"{json.dumps(DB_NAME)}, passfile: {json.dumps(str(self.passfile))}}}\n")
        local = f"atlas: {json.dumps(str(self.box.atlas))}\ncredentials: {{}}\n" + access + probes_yaml([adapter])
        self.box.write_local(local)
        self.bin = self.box.root / "bin"
        self.record = self.box.root / "psql-calls.jsonl"
        self.log_path = self.box.config_home / "probes.log"

    def install(self, scenario):
        self.record.unlink(missing_ok=True)
        install_psql(self.bin, scenario, self.record)

    def probe(self, verb):
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        result = self.box.run("probe", "database", verb, "--service", "api", "--env", "dev", "--resource",
                              "datastore:orders-db", "--json", env=env)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def log_text(self):
        return self.log_path.read_text(encoding="utf-8") if self.log_path.exists() else ""

    def assertNothingSensitive(self, *texts):
        everything = "\n".join(texts)
        for value in (DB_USER, DB_NAME, str(self.passfile), self.passfile.name, HOST, SENTINEL, "senha-falsa"):
            self.assertNotIn(value, everything, f"{value} apareceu na saída ou no probes.log")

    def test_migrations_through_the_core(self):
        """SPEC-0099:IT-01 — `atlas.py probe database migrations --resource datastore:orders-db --json` como processo:
        exit 0, saída validada pelo núcleo com os itens do histórico Flyway; o psql falso só recebeu consultas de
        QUERIES com PGPASSFILE e PGOPTIONS só leitura; usuário, banco, passfile e host fora da saída e do
        probes.log."""
        # SPEC-0099:IT-01
        self.install(base_scenario("flyway"))
        result = self.probe("migrations")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(data), [], data)
        self.assertEqual((data["adapter"], data["capability"], data["verb"], data["status"]),
                         ("postgres", "database", "migrations", "ok"))
        self.assertEqual([(i["id"], i["success"]) for i in data["items"]],
                         [(e[0], e[1]) for e in HISTORIES["flyway"]["expected"]])
        records = read_records(self.record)
        self.assertTrue(records, "o psql falso não foi chamado")
        templates = [template_regex(t) for t in load_queries()]
        tables = [(HISTORIES["flyway"]["nspname"], HISTORIES["flyway"]["relname"])]
        for row in records:
            self.assertTrue(row["allowed"], row["argv"][:-1])
            self.assertEqual(query_problems(row["argv"][-1], templates, tables), [], row["argv"][-1])
            self.assertEqual(os.path.realpath(row["env"].get("PGPASSFILE", "")), os.path.realpath(self.passfile))
            self.assertIn("default_transaction_read_only=on", row["env"].get("PGOPTIONS", ""))
            self.assertNotIn("PGPASSWORD", row["env"])
        self.assertNothingSensitive(output(result), self.log_text())
        lines = [json.loads(line) for line in self.log_text().splitlines() if line.strip()]
        self.assertEqual([(line.get("resource"), line.get("status"), line.get("adapter")) for line in lines],
                         [("datastore:orders-db", "ok", "postgres")])

    def test_tables_and_authentication_failure_through_the_core(self):
        """SPEC-0099:IT-02 — `atlas.py probe database tables ...`: exit 0 com as tabelas do UT-04; com o psql falso
        respondendo falha de autenticação: exit 1 e "falha de autenticação no banco", sem o stderr do dublê."""
        # SPEC-0099:IT-02
        self.install(base_scenario())
        result = self.probe("tables")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(data), [], data)
        self.assertEqual(data["items"], EXPECTED_TABLES)
        scenario = base_scenario()
        scenario["fail"] = [{"mode": "auth"}]
        self.install(scenario)
        failed = self.probe("tables")
        self.assertEqual(failed.returncode, 1, output(failed))
        data = json.loads(failed.stdout)
        self.assertEqual(data["status"], "error", data)
        self.assertIn("falha de autenticação no banco", data.get("message", ""))
        self.assertNothingSensitive(output(result), output(failed), self.log_text())
        self.assertNotIn("password authentication failed", output(failed))


if __name__ == "__main__":
    unittest.main()
