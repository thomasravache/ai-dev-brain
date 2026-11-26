"""Adaptador cloudwatch: sinais das dependências (SPEC-0100: UT-01 a UT-06, IT-01, IT-02, CT-01 e CT-02; ADR-0010,
ADR-0023, ADR-0025, ADR-0026).

Contrato (seção 6 da SPEC-0100) que estes testes fixam:

    assets/probes/cloudwatch.py --describe ->
        {"contract": "probe@2", "adapter": "cloudwatch", "capabilities": {"signals": {"verbs": ["metrics"],
         "targets": ["datastore", "queue", "topic"], "access": ["cloud"]}}}
    entrada probe@2 no stdin (target.resource {kind, id, attrs}, target.cloud.profile, limits); saída probe@2 no
    stdout, exit 0 também no erro (status "error", items [], mensagem fixa).
    chamadas: cloudwatch get-metric-data (até 5 páginas, --next-token) | elasticache describe-replication-groups
        (no máximo uma, só no conjunto elasticache por nós); sempre com --region, --profile, --output json,
        --no-cli-pager, --cli-read-timeout 20, --cli-connect-timeout 10.
    metrics -> um item por métrica da tabela da seção 6, na ordem da tabela: {name, stat, value, kind, unit, period,
        datapoints} e, no elasticache por nós, mais "nodes".

Leituras desta suíte (listadas no relatório do test-writer):
    - Os itens têm exatamente as chaves do bloco de contrato da seção 6; "nodes" só no conjunto elasticache por nós.
    - As consultas trazem só {Id, MetricStat, ReturnData?, Label?}; o MetricStat só {Metric, Period, Stat} (sem
      Unit, que filtraria os pontos); o Metric tem exatamente uma dimensão; o Id segue a regra da AWS
      (^[a-z][A-Za-z0-9_]*$) e não se repete; o conjunto de consultas é exatamente o da tabela (uma por métrica e
      por nó), igual em todas as páginas, com o mesmo --start-time e --end-time.
    - Cache por nós: value é a regra da estatística sobre os pontos de todos os nós juntos (avg = média de todos os
      pontos, não média das médias) e datapoints é o total de pontos de todos os nós.
    - Os nós lidos vêm de MemberClusters/NodeGroupMembers do describe-replication-groups; acima de 6, os 6 primeiros
      em ordem de nome.
    - Páginas intermediárias do dublê vêm com StatusCode Complete; o adaptador junta os pontos de cada Id em todas as
      páginas (até 5). PartialData, mais de 5 páginas ou mais de 6 nós = truncated true.
    - limits.lines corta os itens na ordem da tabela e deixa truncated true (como nos outros adaptadores).
    - Verbo ou capacidade fora do contrato = "chamada não permitida", sem chamada (como no aws-messaging).
    - Os blocos inválidos da referência são recusados pelo leitor do núcleo (NaN, parse_constant) ou pelo validador.
    - O timeout de 30 s do processo não é exercitado (a suíte ficaria lenta): o "timeout" vem do texto da CLI.

Dublê: fixtures/cloudwatch/fake_aws.py, copiado como `aws` numa pasta temporária (o único item do PATH nos testes
unitários), com o cenário em fake-aws.json ao lado; registra cada argv. Isolamento: HOME, XDG_CONFIG_HOME e
ATLAS_CONFIG_HOME temporários; nenhum ~/.aws, nenhuma AWS de verdade, nenhuma rede; nomes acme, orders-db,
orders-cache, orders, orders-events, região us-east-1 e a conta de exemplo 123456789012 (que precisa sair mascarada).
"""
import copy
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from helpers import SKILL, TESTS, Sandbox, fn, output
from test_probe import probes_yaml

SPEC = "SPEC-0100"
ADAPTER = SKILL / "assets" / "probes" / "cloudwatch.py"
REFERENCE = SKILL / "references" / "probes" / "cloudwatch.md"
FIXTURES = TESTS / "fixtures" / "cloudwatch"
FAKE_AWS = FIXTURES / "fake_aws.py"
ATLAS_FIXTURE = TESTS / "fixtures" / "probe-resource" / "atlas"

ACCOUNT = "123456789012"
REGION = "us-east-1"
PROFILE = "acme-dev-read-0100"
DB, CACHE, QUEUE, TOPIC = "orders-db", "orders-cache", "orders", "orders-events"
NODES = ["orders-cache-001", "orders-cache-002"]

DESCRIBE = {"contract": "probe@2", "adapter": "cloudwatch",
            "capabilities": {"signals": {"verbs": ["metrics"], "targets": ["datastore", "queue", "topic"],
                                         "access": ["cloud"]}}}
ITEM_KEYS = {"name", "stat", "value", "kind", "unit", "period", "datapoints"}
STATS = {"sum": "Sum", "avg": "Average", "max": "Maximum", "min": "Minimum"}
KINDS = ("error", "latency", "saturation", "traffic")

# seção 6: conjunto -> (namespace, dimensão, [(métrica, kind, stat, unidade)]) na ordem da tabela
TABLE = {
    "rds": ("AWS/RDS", "DBInstanceIdentifier", [
        ("ReadLatency", "latency", "avg", "Seconds"), ("WriteLatency", "latency", "avg", "Seconds"),
        ("CPUUtilization", "saturation", "max", "Percent"),
        ("DatabaseConnections", "saturation", "max", "Count"), ("DiskQueueDepth", "saturation", "max", "Count"),
        ("FreeableMemory", "saturation", "min", "Bytes"), ("FreeStorageSpace", "saturation", "min", "Bytes"),
        ("ReadIOPS", "traffic", "avg", "Count/Second"), ("WriteIOPS", "traffic", "avg", "Count/Second")]),
    "rds-aurora": ("AWS/RDS", "DBClusterIdentifier", [
        ("ReadLatency", "latency", "avg", "Seconds"), ("WriteLatency", "latency", "avg", "Seconds"),
        ("CPUUtilization", "saturation", "max", "Percent"),
        ("DatabaseConnections", "saturation", "max", "Count"),
        ("FreeableMemory", "saturation", "min", "Bytes"),
        ("ACUUtilization", "saturation", "max", "Percent"),  # só com serverless: true
        ("ReadIOPS", "traffic", "avg", "Count/Second"), ("WriteIOPS", "traffic", "avg", "Count/Second")]),
    "elasticache": ("AWS/ElastiCache", "CacheClusterId", [
        ("ErrorCount", "error", "sum", "Count"), ("AuthenticationFailures", "error", "sum", "Count"),
        ("SuccessfulReadRequestLatency", "latency", "avg", "Microseconds"),
        ("SuccessfulWriteRequestLatency", "latency", "avg", "Microseconds"),
        ("EngineCPUUtilization", "saturation", "max", "Percent"),
        ("DatabaseMemoryUsagePercentage", "saturation", "max", "Percent"),
        ("CurrConnections", "saturation", "max", "Count"), ("Evictions", "saturation", "sum", "Count"),
        ("CacheHits", "traffic", "sum", "Count"), ("CacheMisses", "traffic", "sum", "Count")]),
    "elasticache-serverless": ("AWS/ElastiCache", "clusterId", [
        ("ThrottledCmds", "error", "sum", "Count"), ("AuthenticationFailures", "error", "sum", "Count"),
        ("SuccessfulReadRequestLatency", "latency", "avg", "Microseconds"),
        ("SuccessfulWriteRequestLatency", "latency", "avg", "Microseconds"),
        ("ElastiCacheProcessingUnits", "saturation", "sum", "Count"),
        ("BytesUsedForCache", "saturation", "max", "Bytes"), ("CurrConnections", "saturation", "max", "Count"),
        ("TotalCmdsCount", "traffic", "sum", "Count"), ("CacheHitRate", "traffic", "avg", "None")]),
    "sqs": ("AWS/SQS", "QueueName", [
        ("ApproximateAgeOfOldestMessage", "latency", "max", "Seconds"),
        ("ApproximateNumberOfMessagesVisible", "saturation", "max", "Count"),
        ("ApproximateNumberOfMessagesNotVisible", "saturation", "max", "Count"),
        ("NumberOfMessagesSent", "traffic", "sum", "Count"), ("NumberOfMessagesReceived", "traffic", "sum", "Count"),
        ("NumberOfMessagesDeleted", "traffic", "sum", "Count")]),
    "sns": ("AWS/SNS", "TopicName", [
        ("NumberOfNotificationsFailed", "error", "sum", "Count"),
        ("NumberOfMessagesPublished", "traffic", "sum", "Count"),
        ("NumberOfNotificationsDelivered", "traffic", "sum", "Count"),
        ("NumberOfNotificationsFilteredOut", "traffic", "sum", "Count"), ("PublishSize", "traffic", "avg", "Bytes")]),
}

NO_DATA = "sem dados na janela"
PARTIAL = "dados parciais"
NO_SIGNALS = "tipo de recurso sem sinais"
NO_REGION = "recurso sem região no atlas"
REFUSED = "chamada não permitida"
INVALID_INPUT = "entrada inválida"
ERRORS = {
    "sso-expired": "renove o login da nuvem",
    "token-expired": "renove o login da nuvem",
    "profile-not-found": "profile inexistente",
    "no-credentials": "sem credenciais da nuvem",
    "denied": "sem permissão (AccessDenied)",
    "throttling": "limite de chamadas da nuvem",
    "no-connection": "sem conexão com a nuvem",
    "timeout": "timeout",
    "invalid-json": "resposta inválida da aws",
    "wrong-shape": "resposta inválida da aws",
    "fail": "falha da aws",
}

# lista fechada (seção 6): (serviço, operação) -> opções próprias aceitas
OPERATIONS = {
    ("cloudwatch", "get-metric-data"): {"--metric-data-queries", "--start-time", "--end-time", "--scan-by",
                                        "--next-token"},
    ("elasticache", "describe-replication-groups"): {"--replication-group-id"},
}
COMMON = {"--region", "--profile", "--output", "--no-cli-pager", "--cli-read-timeout", "--cli-connect-timeout"}
QUERY_ID_RE = re.compile(r"^[a-z][A-Za-z0-9_]*\Z")
PERCENTILE_RE = re.compile(r"^p[0-9]{1,2}(\.[0-9]+)?\Z")

RDS_ATTRS = {"type": "rds", "engine": "postgres", "serverless": False, "region": REGION}
AURORA_ATTRS = {"type": "rds", "engine": "aurora-postgresql", "serverless": False, "region": REGION}
CACHE_ATTRS = {"type": "elasticache", "engine": "valkey", "serverless": False, "region": REGION}
SERVERLESS_ATTRS = {"type": "elasticache", "engine": "valkey", "serverless": True, "region": REGION}
QUEUE_ATTRS = {"type": "sqs", "region": REGION}
TOPIC_ATTRS = {"type": "sns", "region": REGION}


def f(name):
    return fn(name, "SPEC-0096")


# --------------------------------------------------------------------------- tabela e cenário


def metric_set(kind, attrs):
    """O conjunto da tabela da seção 6 para um alvo válido (None fora da regra)."""
    rtype = attrs.get("type")
    if kind == "queue":
        return "sqs"
    if kind == "topic":
        return "sns"
    if rtype == "rds":
        return "rds-aurora" if str(attrs.get("engine") or "").startswith("aurora") else "rds"
    if rtype == "elasticache":
        return "elasticache-serverless" if attrs.get("serverless") is True else "elasticache"
    return None


def table_rows(name, serverless=False):
    """[(métrica, kind, stat, unidade)] do conjunto, na ordem da tabela (ACUUtilization só com serverless)."""
    rows = TABLE[name][2]
    if name == "rds-aurora" and not serverless:
        rows = [row for row in rows if row[0] != "ACUUtilization"]
    return rows


def expected_period(since):
    return max(60, math.ceil(since / 60 / 60) * 60)


def key(dimension, value, metric):
    return f"{dimension}={value}/{metric}"


def rds_scenario(dimension="DBInstanceIdentifier"):
    """UT-01: pontos de orders-db (ReadLatency 0.002 e 0.004, CPUUtilization 40 e 70, FreeStorageSpace 9e9 e 8e9)."""
    return {"account": ACCOUNT, "series": {
        key(dimension, DB, "ReadLatency"): [0.002, 0.004],
        key(dimension, DB, "CPUUtilization"): [40, 70],
        key(dimension, DB, "FreeStorageSpace"): [9e9, 8e9]}, "fail": []}


def cache_scenario():
    """UT-02: grupo orders-cache com dois nós."""
    return {"account": ACCOUNT, "groups": {CACHE: list(NODES)}, "series": {
        key("CacheClusterId", NODES[0], "CacheHits"): [10, 20],
        key("CacheClusterId", NODES[1], "CacheHits"): [5],
        key("CacheClusterId", NODES[0], "EngineCPUUtilization"): [30, 50],
        key("CacheClusterId", NODES[1], "EngineCPUUtilization"): [80],
        key("CacheClusterId", NODES[0], "SuccessfulReadRequestLatency"): [100, 200],
        key("CacheClusterId", NODES[1], "SuccessfulReadRequestLatency"): [300]}, "fail": []}


def queue_scenario():
    return {"account": ACCOUNT, "series": {
        key("QueueName", QUEUE, "ApproximateAgeOfOldestMessage"): [12, 40, 7],
        key("QueueName", QUEUE, "NumberOfMessagesSent"): [1, 2, 3, 4, 5, 6]}, "fail": []}


def install_aws(folder: Path, scenario: dict, record: Path):
    """Copia o dublê como `aws` (cabeçalho com o Python dos testes) e grava o cenário ao lado dele."""
    folder.mkdir(parents=True, exist_ok=True)
    body = FAKE_AWS.read_text(encoding="utf-8").split("\n", 1)[1]
    target = folder / "aws"
    target.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (folder / "fake-aws.json").write_text(json.dumps(dict(scenario, record=str(record))), encoding="utf-8")
    return target


def read_calls(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line)["argv"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_argv(argv):
    """(palavras, {opção: valor | [valores] | True}) de um argv da AWS CLI (com espaço ou "=")."""
    words, options, i = [], {}, 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("-"):
            name, eq, value = arg.partition("=")
            if eq:
                options[name] = value
                i += 1
                continue
            values = []
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                values.append(argv[i])
                i += 1
            options[name] = True if not values else values[0] if len(values) == 1 else values
        else:
            words.append(arg)
            i += 1
    return words, options


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.timestamp()


def call_problems(argv, region, profile) -> list:
    """SPEC-0100:UT-05 — problemas de um argv frente à lista fechada da seção 6; [] = permitido."""
    words, options = parse_argv(argv)
    pair = tuple(words[:2])
    if len(words) != 2 or pair not in OPERATIONS:
        return [f"operação fora da lista: {words}"]
    problems = [] if argv[:2] == list(pair) else ["o argv não começa com <serviço> <operação>"]
    unknown = set(options) - COMMON - OPERATIONS[pair]
    if unknown:
        problems.append(f"opções fora da lista: {sorted(unknown)}")
    expected = {"--region": region, "--profile": profile, "--output": "json", "--no-cli-pager": True,
                "--cli-read-timeout": "20", "--cli-connect-timeout": "10"}
    for name, value in expected.items():
        if options.get(name) != value:
            problems.append(f"{name} diferente de {value!r}: {options.get(name)!r}")
    for name in OPERATIONS[pair]:
        if name in options and not isinstance(options[name], str):
            problems.append(f"{name} sem um valor só")
    if pair == ("cloudwatch", "get-metric-data") and options.get("--scan-by") != "TimestampAscending":
        problems.append("--scan-by diferente de TimestampAscending")
    return problems


def queries_of(argv) -> list:
    raw = parse_argv(argv)[1].get("--metric-data-queries")
    try:
        queries = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    return queries if isinstance(queries, list) else None


def query_problems(queries, set_name, dims, period, serverless=False) -> list:
    """SPEC-0100:UT-05 — as consultas de um get-metric-data frente à tabela: só MetricStat da tabela, exatamente uma
    por métrica e por valor de dimensão, sem Expression, até 60, Ids válidos e sem repetição."""
    if queries is None:
        return ["--metric-data-queries não é uma lista JSON (file:// e outros são proibidos)"]
    if len(queries) > 60:
        return [f"{len(queries)} consultas (máximo 60)"]
    namespace, dimension, _ = TABLE[set_name]
    problems, seen, ids = [], [], []
    for index, query in enumerate(queries):
        where = f"consulta {index}"
        if not isinstance(query, dict):
            problems.append(f"{where} não é objeto")
            continue
        if set(query) - {"Id", "MetricStat", "ReturnData", "Label"}:
            problems.append(f"{where} com chaves fora da regra: {sorted(set(query))}")
        if "Expression" in query or "MetricStat" not in query:
            problems.append(f"{where} sem MetricStat ou com Expression")
            continue
        if query.get("ReturnData") is False:
            problems.append(f"{where} com ReturnData false")
        ids.append(query.get("Id"))
        if not (isinstance(query.get("Id"), str) and QUERY_ID_RE.match(query["Id"])):
            problems.append(f"{where} com Id fora da regra da AWS")
        metric_stat = query["MetricStat"]
        if not isinstance(metric_stat, dict) or set(metric_stat) != {"Metric", "Period", "Stat"}:
            problems.append(f"{where}: MetricStat precisa ter só Metric, Period e Stat")
            continue
        metric = metric_stat["Metric"] if isinstance(metric_stat["Metric"], dict) else {}
        if set(metric) != {"Namespace", "MetricName", "Dimensions"}:
            problems.append(f"{where}: Metric precisa ter só Namespace, MetricName e Dimensions")
        dimensions = metric.get("Dimensions")
        if not (isinstance(dimensions, list) and len(dimensions) == 1 and isinstance(dimensions[0], dict)
                and set(dimensions[0]) == {"Name", "Value"}):
            problems.append(f"{where}: precisa de exatamente uma dimensão {{Name, Value}}")
            continue
        if metric_stat["Period"] != period:
            problems.append(f"{where}: Period {metric_stat['Period']!r} diferente de {period}")
        seen.append((metric.get("Namespace"), metric.get("MetricName"), dimensions[0]["Name"],
                     dimensions[0]["Value"], metric_stat["Stat"]))
    if len(set(ids)) != len(ids):
        problems.append("Id repetido")
    expected = Counter((namespace, row[0], dimension, value, STATS[row[2]])
                       for row in table_rows(set_name, serverless) for value in dims)
    if Counter(seen) != expected:
        problems.append(f"consultas diferentes da tabela ({set_name}): a mais {sorted(Counter(seen) - expected)}, "
                        f"faltando {sorted(expected - Counter(seen))}")
    return problems


def probe_input(kind="datastore", rid=DB, attrs=None, profile=PROFILE, lines=200, since=1800, contract="probe@2",
                verb="metrics", capability="signals"):
    if attrs is None:
        attrs = {"datastore": RDS_ATTRS, "queue": QUEUE_ATTRS, "topic": TOPIC_ATTRS}[kind]
    return {"contract": contract, "capability": capability, "verb": verb,
            "target": {"service": "api", "environment": "dev", "deployment": "dev-api",
                       "resource": {"kind": kind, "id": rid, "attrs": dict(attrs)}, "cloud": {"profile": profile}},
            "limits": {"lines": lines, "since_seconds": since}}


def table_4a_problems(out) -> list:
    """SPEC-0100:CT-02 — a conferência da tabela 4a do ADR-0026 (o que o verify@2 lê) sobre uma saída de metrics:
    name texto não vazio, stat em sum|count|avg|min|max|p<n>, value número finito ou null, kind em
    error|latency|saturation|traffic, sem dois itens com o mesmo (name, stat)."""
    items = out.get("items")
    if not isinstance(items, list):
        return ["items não é lista"]
    problems, seen = [], set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"items[{index}] não é objeto")
            continue
        name, stat_, value, kind = item.get("name"), item.get("stat"), item.get("value", "ausente"), item.get("kind")
        if not (isinstance(name, str) and name):
            problems.append(f"items[{index}].name precisa ser texto não vazio")
        if not (isinstance(stat_, str) and (stat_ in ("sum", "count", "avg", "min", "max")
                                            or PERCENTILE_RE.match(stat_))):
            problems.append(f"items[{index}].stat fora de sum|count|avg|min|max|p<n>")
        if not (value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)
                                  and math.isfinite(value))):
            problems.append(f"items[{index}].value precisa ser número finito ou null")
        if kind not in KINDS:
            problems.append(f"items[{index}].kind fora de error|latency|saturation|traffic")
        pair = (name, stat_)
        if pair in seen:
            problems.append(f"items[{index}] repete (name, stat)")
        seen.add(pair)
    return problems


# --------------------------------------------------------------------------- base


class CloudwatchCase(unittest.TestCase):
    """Uma pasta temporária por teste: HOME, configuração e a pasta do aws falso (o único item do PATH)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.record = self.root / "aws-calls.jsonl"
        self.scenario = rds_scenario()

    def install(self, scenario=None):
        self.record.unlink(missing_ok=True)
        self.installed = copy.deepcopy(self.scenario if scenario is None else scenario)
        install_aws(self.bin, self.installed, self.record)

    def environment(self, with_aws=True):
        path = self.bin if with_aws else self.root / "empty-bin"
        path.mkdir(exist_ok=True)
        env = {"PATH": str(path), "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
               "ATLAS_CONFIG_HOME": str(self.root / "config-home"), "LANG": "C.UTF-8"}
        for name in ("TMPDIR", "SYSTEMROOT"):
            if name in os.environ:
                env[name] = os.environ[name]
        return env

    def adapter(self, *args, stdin="", with_aws=True):
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        result = subprocess.run([sys.executable, str(ADAPTER), *args], input=stdin, capture_output=True, text=True,
                                cwd=self.root, env=self.environment(with_aws), timeout=180, check=False)
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        return result

    def run_probe(self, data, with_aws=True, raw=None):
        """Roda o adaptador; confere exit 0, a saída probe@2 (validador do núcleo), o pedido ecoado, nenhum profile,
        conta ou ARN na saída, e cada chamada contra a lista fechada e a tabela (UT-05)."""
        result = self.adapter(stdin=raw if raw is not None else json.dumps(data), with_aws=with_aws)
        self.assertEqual(result.returncode, 0, output(result))
        text = output(result)
        for value in (PROFILE, ACCOUNT, "arn:aws", "amazonaws.com"):
            self.assertNotIn(value, text, f"{value} apareceu na saída do adaptador")
        out = json.loads(result.stdout, parse_constant=f("_reject_constant"))
        self.assertEqual(f("validate_probe_output")(out), [], out)
        self.assertEqual({k: out.get(k) for k in ("contract", "adapter", "capability")},
                         {"contract": "probe@2", "adapter": "cloudwatch", "capability": "signals"})
        if isinstance(data, dict):
            self.assertEqual(out.get("verb"), data["verb"])
            self.assertAllowedCalls(data)
        return out

    def calls(self):
        return read_calls(self.record)

    def pairs(self):
        return [tuple(parse_argv(argv)[0][:2]) for argv in self.calls()]

    def metric_calls(self):
        return [argv for argv in self.calls() if tuple(parse_argv(argv)[0][:2]) == ("cloudwatch", "get-metric-data")]

    def expected_dims(self, data):
        resource = data["target"]["resource"]
        if metric_set(resource["kind"], resource["attrs"]) != "elasticache":
            return [resource["id"]]
        groups = getattr(self, "installed", {}).get("groups") or {}
        return sorted(groups.get(resource["id"], [resource["id"]]))[:6]

    def assertAllowedCalls(self, data):
        """SPEC-0100:UT-05 — todo argv da lista fechada, com as opções comuns; até 5 get-metric-data (a primeira sem
        --next-token, as outras com o token devolvido), no máximo uma describe-replication-groups e só no conjunto
        elasticache por nós; consultas exatamente as da tabela, iguais em todas as páginas; janela = since_seconds e
        end-time a poucos segundos do relógio do teste."""
        # SPEC-0100:UT-05
        resource = data["target"]["resource"]
        attrs = resource["attrs"]
        calls = self.calls()
        for argv in calls:
            self.assertEqual(call_problems(argv, attrs.get("region"), data["target"]["cloud"]["profile"]), [], argv)
        if not calls:
            return
        pairs = self.pairs()
        set_name = metric_set(resource["kind"], attrs)
        self.assertIsNotNone(set_name, f"houve chamada para um alvo fora da regra: {pairs}")
        describes = pairs.count(("elasticache", "describe-replication-groups"))
        self.assertLessEqual(describes, 1 if set_name == "elasticache" else 0, pairs)
        if describes:
            self.assertEqual(pairs[0], ("elasticache", "describe-replication-groups"), pairs)
            self.assertEqual(parse_argv(calls[0])[1].get("--replication-group-id"), resource["id"])
        metric_calls = self.metric_calls()
        self.assertLessEqual(len(metric_calls), 5, f"{len(metric_calls)} get-metric-data (máximo 5 páginas)")
        since = data["limits"]["since_seconds"]
        period = expected_period(since)
        windows = set()
        for page, argv in enumerate(metric_calls):
            options = parse_argv(argv)[1]
            self.assertEqual(options.get("--next-token"), None if page == 0 else f"page-{page + 1}", argv)
            self.assertEqual(query_problems(queries_of(argv), set_name, self.expected_dims(data), period,
                                            attrs.get("serverless") is True), [])
            start, end = parse_time(options.get("--start-time")), parse_time(options.get("--end-time"))
            self.assertIsNotNone(start, f"--start-time fora de ISO 8601 com fuso: {options.get('--start-time')}")
            self.assertIsNotNone(end, f"--end-time fora de ISO 8601 com fuso: {options.get('--end-time')}")
            self.assertEqual(end - start, since, "end-time - start-time diferente de since_seconds")
            self.assertLess(abs(datetime.now(timezone.utc).timestamp() - end), 60, "end-time longe do relógio")
            windows.add((options.get("--start-time"), options.get("--end-time"), options.get("--metric-data-queries")))
        self.assertLessEqual(len(windows), 1, "as páginas mudaram a janela ou as consultas")

    def assertError(self, out, message):
        self.assertEqual(out["status"], "error", out)
        self.assertEqual(out["items"], [], out)
        self.assertEqual(out.get("message"), message, out)

    def metrics(self, data, nodes=None):
        """Saída ok de metrics: os itens na ordem da tabela, com exatamente as chaves do contrato, kind, stat, unit e
        period da tabela, datapoints inteiro >= 0 e value número finito ou null."""
        out = self.run_probe(data)
        self.assertEqual(out["status"], "ok", out)
        resource = data["target"]["resource"]
        set_name = metric_set(resource["kind"], resource["attrs"])
        rows = table_rows(set_name, resource["attrs"].get("serverless") is True)
        rows = rows[:data["limits"]["lines"]]
        self.assertEqual([i.get("name") for i in out["items"]], [row[0] for row in rows], out)
        period = expected_period(data["limits"]["since_seconds"])
        keys = ITEM_KEYS | ({"nodes"} if set_name == "elasticache" else set())
        for item, (name, kind, stat_, unit) in zip(out["items"], rows):
            with self.subTest(metric=name):
                self.assertEqual(set(item), keys, item)
                self.assertEqual((item["kind"], item["stat"], item["unit"], item["period"]),
                                 (kind, stat_, unit, period), item)
                self.assertTrue(isinstance(item["datapoints"], int) and not isinstance(item["datapoints"], bool)
                                and item["datapoints"] >= 0, item)
                self.assertTrue(item["value"] is None or (isinstance(item["value"], (int, float))
                                                          and not isinstance(item["value"], bool)), item)
                if item["datapoints"] == 0:
                    self.assertIsNone(item["value"], item)
                if nodes is not None:
                    self.assertEqual(item["nodes"], nodes, item)
        self.assertEqual(table_4a_problems(out), [])
        return out

    @staticmethod
    def by_name(out):
        return {item["name"]: item for item in out["items"]}


# --------------------------------------------------------------------------- UT-01


class RdsTest(CloudwatchCase):
    def test_rds_instance_has_the_nine_metrics_aggregated_in_the_window(self):
        """SPEC-0100:UT-01 — datastore:orders-db (rds, postgres) com since 1800: os 9 itens do conjunto rds na ordem
        da tabela, dimensão DBInstanceIdentifier=orders-db, period 60, datapoints = pontos e value 0.003 (avg),
        70 (max) e 8e9 (min); métricas sem ponto saem null com datapoints 0."""
        # SPEC-0100:UT-01
        self.install()
        out = self.metrics(probe_input())
        self.assertEqual(len(out["items"]), 9)
        items = self.by_name(out)
        self.assertAlmostEqual(items["ReadLatency"]["value"], 0.003, places=9)
        self.assertEqual(items["CPUUtilization"]["value"], 70)
        self.assertEqual(items["FreeStorageSpace"]["value"], 8e9)
        for name in ("ReadLatency", "CPUUtilization", "FreeStorageSpace"):
            self.assertEqual(items[name]["datapoints"], 2, items[name])
        for name in ("WriteLatency", "DatabaseConnections", "DiskQueueDepth", "FreeableMemory", "ReadIOPS",
                     "WriteIOPS"):
            self.assertEqual((items[name]["value"], items[name]["datapoints"]), (None, 0), items[name])
        self.assertFalse(out["truncated"], out)
        self.assertNotIn(out.get("message"), (NO_DATA, PARTIAL), out)
        self.assertEqual(self.pairs(), [("cloudwatch", "get-metric-data")])

    def test_rds_without_engine_is_an_instance(self):
        """SPEC-0100:UT-01 — type rds sem engine: conjunto rds (instância), dimensão DBInstanceIdentifier."""
        # SPEC-0100:UT-01
        self.install()
        out = self.metrics(probe_input(attrs={"type": "rds", "region": REGION}))
        self.assertEqual(len(out["items"]), 9)

    def test_aurora_uses_the_cluster_dimension_and_acu_only_when_serverless(self):
        """SPEC-0100:UT-01 — engine aurora-postgresql: conjunto rds-aurora com DBClusterIdentifier; sem serverless
        7 itens (sem ACUUtilization), com serverless true 8 itens (com ACUUtilization)."""
        # SPEC-0100:UT-01
        for serverless, count in ((False, 7), (True, 8)):
            with self.subTest(serverless=serverless):
                self.install(rds_scenario("DBClusterIdentifier"))
                attrs = dict(AURORA_ATTRS, serverless=serverless)
                out = self.metrics(probe_input(attrs=attrs))
                self.assertEqual(len(out["items"]), count, out)
                self.assertEqual("ACUUtilization" in self.by_name(out), serverless)
                items = self.by_name(out)
                self.assertAlmostEqual(items["ReadLatency"]["value"], 0.003, places=9)
                self.assertEqual(items["CPUUtilization"]["value"], 70)

    def test_aurora_mysql_is_also_a_cluster(self):
        """SPEC-0100:UT-01 — qualquer engine que começa com aurora (aurora-mysql) vai para rds-aurora."""
        # SPEC-0100:UT-01
        self.install(rds_scenario("DBClusterIdentifier"))
        out = self.metrics(probe_input(attrs=dict(AURORA_ATTRS, engine="aurora-mysql")))
        self.assertEqual(len(out["items"]), 7)


# --------------------------------------------------------------------------- UT-02


class CacheNodesTest(CloudwatchCase):
    def test_replication_group_with_two_nodes_is_aggregated(self):
        """SPEC-0100:UT-02 — grupo orders-cache com orders-cache-001 e -002: uma describe-replication-groups,
        CacheClusterId de cada nó, CacheHits (sum) soma os nós (35), EngineCPUUtilization (max) pega o pior (80),
        SuccessfulReadRequestLatency (avg) é a média de todos os pontos juntos (200) e nodes 2 em todo item."""
        # SPEC-0100:UT-02
        self.install(cache_scenario())
        out = self.metrics(probe_input(rid=CACHE, attrs=CACHE_ATTRS), nodes=2)
        self.assertEqual(len(out["items"]), 10)
        items = self.by_name(out)
        self.assertEqual(items["CacheHits"]["value"], 35)
        self.assertEqual(items["EngineCPUUtilization"]["value"], 80)
        self.assertAlmostEqual(items["SuccessfulReadRequestLatency"]["value"], 200, places=6)
        self.assertEqual(items["CacheHits"]["datapoints"], 3)
        self.assertEqual(items["CacheMisses"]["value"], None)
        self.assertEqual(self.pairs().count(("elasticache", "describe-replication-groups")), 1)
        self.assertFalse(out["truncated"], out)

    def test_cache_without_replication_group_uses_its_own_id(self):
        """SPEC-0100:UT-02 — ReplicationGroupNotFoundFault: as consultas usam CacheClusterId=orders-cache e nodes 1."""
        # SPEC-0100:UT-02
        scenario = {"account": ACCOUNT, "groups": {}, "series": {
            key("CacheClusterId", CACHE, "CacheHits"): [4, 6]}, "fail": []}
        self.install(scenario)
        out = self.metrics(probe_input(rid=CACHE, attrs=CACHE_ATTRS), nodes=1)
        self.assertEqual(self.by_name(out)["CacheHits"]["value"], 10)
        self.assertEqual(self.pairs(), [("elasticache", "describe-replication-groups"),
                                        ("cloudwatch", "get-metric-data")])

    def test_redis_engine_and_missing_serverless_are_by_nodes(self):
        """SPEC-0100:UT-02 — engine redis e serverless ausente: conjunto elasticache por nós."""
        # SPEC-0100:UT-02
        self.install(cache_scenario())
        attrs = {"type": "elasticache", "engine": "redis", "region": REGION}
        out = self.metrics(probe_input(rid=CACHE, attrs=attrs), nodes=2)
        self.assertEqual(self.by_name(out)["CacheHits"]["value"], 35)


# --------------------------------------------------------------------------- UT-03


class TargetsAndWindowTest(CloudwatchCase):
    def test_serverless_cache_queue_and_topic_use_their_dimension(self):
        """SPEC-0100:UT-03 — elasticache serverless (clusterId, 9 itens, sem nodes, sem describe), queue (QueueName,
        6 itens) e topic (TopicName, 5 itens), com as métricas da tabela."""
        # SPEC-0100:UT-03
        cases = [
            (probe_input(rid=CACHE, attrs=SERVERLESS_ATTRS), {key("clusterId", CACHE, "TotalCmdsCount"): [3, 4]},
             "TotalCmdsCount", 7, 9),
            (probe_input("queue", QUEUE), queue_scenario()["series"], "ApproximateAgeOfOldestMessage", 40, 6),
            (probe_input("topic", TOPIC), {key("TopicName", TOPIC, "NumberOfNotificationsFailed"): [1, 0, 2],
                                           key("TopicName", TOPIC, "PublishSize"): [100, 300]},
             "NumberOfNotificationsFailed", 3, 5),
        ]
        for data, series, metric, value, count in cases:
            with self.subTest(kind=data["target"]["resource"]["kind"]):
                self.install({"account": ACCOUNT, "series": series, "fail": []})
                out = self.metrics(data)
                self.assertEqual(len(out["items"]), count, out)
                self.assertEqual(self.by_name(out)[metric]["value"], value)
                self.assertNotIn(("elasticache", "describe-replication-groups"), self.pairs())
                if data["target"]["resource"]["kind"] == "topic":
                    self.assertEqual(self.by_name(out)["PublishSize"]["value"], 200)

    def test_queue_and_topic_without_type_are_sqs_and_sns(self):
        """SPEC-0100:UT-03 — queue e topic sem attrs.type valem sqs e sns."""
        # SPEC-0100:UT-03
        for kind, rid, count in (("queue", QUEUE, 6), ("topic", TOPIC, 5)):
            with self.subTest(kind=kind):
                self.install(queue_scenario())
                out = self.metrics(probe_input(kind, rid, attrs={"region": REGION}))
                self.assertEqual(len(out["items"]), count)

    def test_period_follows_the_window(self):
        """SPEC-0100:UT-03 — since_seconds 1800 e 86400: period 60 e 1440 nos itens e nas consultas; end-time -
        start-time igual à janela (conferido em assertAllowedCalls)."""
        # SPEC-0100:UT-03
        for since, period in ((1800, 60), (86400, 1440), (3600, 60), (7200, 120)):
            with self.subTest(since=since):
                self.install(queue_scenario())
                out = self.metrics(probe_input("queue", QUEUE, since=since))
                self.assertEqual({item["period"] for item in out["items"]}, {period})

    def test_no_data_points_at_all(self):
        """SPEC-0100:UT-03 — nenhuma métrica com ponto: todo value null, datapoints 0, status ok, "sem dados na
        janela"."""
        # SPEC-0100:UT-03
        for data in (probe_input(), probe_input("queue", QUEUE), probe_input(rid=CACHE, attrs=SERVERLESS_ATTRS)):
            with self.subTest(kind=data["target"]["resource"]["kind"]):
                self.install({"account": ACCOUNT, "series": {}, "fail": []})
                out = self.metrics(data)
                self.assertTrue(out["items"])
                self.assertEqual({(i["value"], i["datapoints"]) for i in out["items"]}, {(None, 0)})
                self.assertEqual(out.get("message"), NO_DATA, out)
                self.assertFalse(out["truncated"], out)

    def test_pages_are_joined_up_to_five(self):
        """SPEC-0100:UT-03 — 3 páginas: três get-metric-data (a 2ª e a 3ª com --next-token), pontos juntados por Id
        (NumberOfMessagesSent soma 21 com 6 pontos), truncated false."""
        # SPEC-0100:UT-03
        scenario = queue_scenario()
        scenario["pages"] = 3
        self.install(scenario)
        out = self.metrics(probe_input("queue", QUEUE))
        self.assertEqual(len(self.metric_calls()), 3)
        sent = self.by_name(out)["NumberOfMessagesSent"]
        self.assertEqual((sent["value"], sent["datapoints"]), (21, 6))
        self.assertEqual(self.by_name(out)["ApproximateAgeOfOldestMessage"]["value"], 40)
        self.assertFalse(out["truncated"], out)

    def test_more_than_five_pages_is_truncated(self):
        """SPEC-0100:UT-03 — 7 páginas: exatamente 5 get-metric-data e truncated true."""
        # SPEC-0100:UT-03
        scenario = queue_scenario()
        scenario["pages"] = 7
        self.install(scenario)
        out = self.metrics(probe_input("queue", QUEUE))
        self.assertEqual(len(self.metric_calls()), 5)
        self.assertTrue(out["truncated"], out)

    def test_more_than_six_nodes_is_truncated(self):
        """SPEC-0100:UT-03 — grupo com 7 nós: consultas só dos 6 primeiros em ordem de nome (60 consultas),
        nodes 6 e truncated true."""
        # SPEC-0100:UT-03
        nodes = [f"{CACHE}-00{n}" for n in (7, 3, 1, 5, 2, 6, 4)]
        scenario = {"account": ACCOUNT, "groups": {CACHE: nodes}, "series": {
            key("CacheClusterId", f"{CACHE}-007", "CacheHits"): [1000],
            key("CacheClusterId", f"{CACHE}-001", "CacheHits"): [1]}, "fail": []}
        self.install(scenario)
        out = self.metrics(probe_input(rid=CACHE, attrs=CACHE_ATTRS), nodes=6)
        self.assertTrue(out["truncated"], out)
        self.assertEqual(self.by_name(out)["CacheHits"]["value"], 1)
        self.assertEqual(len(queries_of(self.metric_calls()[0])), 60)

    def test_partial_data_status_is_truncated(self):
        """SPEC-0100:UT-03 — uma consulta com StatusCode PartialData: truncated true, status ok."""
        # SPEC-0100:UT-03
        scenario = queue_scenario()
        scenario["status"] = {key("QueueName", QUEUE, "NumberOfMessagesSent"): "PartialData"}
        self.install(scenario)
        out = self.metrics(probe_input("queue", QUEUE))
        self.assertTrue(out["truncated"], out)

    def test_partial_data_only_on_intermediate_pages_is_not_truncated(self):
        """SPEC-0100:UT-03 (Emenda v2) — 3 páginas, PartialData só nas páginas 1 e 2 e Complete na última: os pontos
        das 3 páginas são juntados e truncated false (PartialData só conta na última página lida)."""
        # SPEC-0100:UT-03
        sent = key("QueueName", QUEUE, "NumberOfMessagesSent")
        scenario = queue_scenario()
        scenario["pages"] = 3
        scenario["page_status"] = [{sent: "PartialData"}, {sent: "PartialData"}, {sent: "Complete"}]
        self.install(scenario)
        out = self.metrics(probe_input("queue", QUEUE))
        self.assertEqual(len(self.metric_calls()), 3)
        item = self.by_name(out)["NumberOfMessagesSent"]
        self.assertEqual((item["value"], item["datapoints"]), (21, 6))
        self.assertFalse(out["truncated"], out)

    def test_partial_data_on_the_last_page_is_truncated(self):
        """SPEC-0100:UT-03 (Emenda v2) — 3 páginas, Complete nas páginas 1 e 2 e PartialData na última (a resposta
        sem NextToken): truncated true, status ok."""
        # SPEC-0100:UT-03
        sent = key("QueueName", QUEUE, "NumberOfMessagesSent")
        scenario = queue_scenario()
        scenario["pages"] = 3
        scenario["page_status"] = [{sent: "Complete"}, {sent: "Complete"}, {sent: "PartialData"}]
        self.install(scenario)
        out = self.metrics(probe_input("queue", QUEUE))
        self.assertEqual(len(self.metric_calls()), 3)
        self.assertTrue(out["truncated"], out)

    def test_forbidden_or_internal_error_query_is_null_with_partial_data(self):
        """SPEC-0100:UT-03 — uma consulta Forbidden (ou InternalError): aquela métrica sai null, as outras com valor,
        status ok e a mensagem "dados parciais"."""
        # SPEC-0100:UT-03
        for code in ("Forbidden", "InternalError"):
            with self.subTest(code=code):
                scenario = queue_scenario()
                scenario["status"] = {key("QueueName", QUEUE, "NumberOfMessagesSent"): code}
                self.install(scenario)
                out = self.metrics(probe_input("queue", QUEUE))
                items = self.by_name(out)
                self.assertIsNone(items["NumberOfMessagesSent"]["value"])
                self.assertEqual(items["ApproximateAgeOfOldestMessage"]["value"], 40)
                self.assertEqual(out.get("message"), PARTIAL, out)

    def test_lines_cut_the_items(self):
        """SPEC-0100:UT-03 — limits.lines 3: os 3 primeiros itens da tabela e truncated true."""
        # SPEC-0100:UT-03
        self.install()
        out = self.metrics(probe_input(lines=3))
        self.assertEqual(len(out["items"]), 3)
        self.assertTrue(out["truncated"], out)


# --------------------------------------------------------------------------- UT-04


class ErrorTest(CloudwatchCase):
    def test_cli_failures_become_fixed_messages(self):
        """SPEC-0100:UT-04 — SSO expirado, token expirado, profile inexistente, sem credenciais, AccessDenied,
        Throttling, sem conexão, timeout, JSON inválido, JSON de outra forma e outro erro: exit 0, status error,
        items [] e a mensagem fixa; profile, ARN e conta fora da saída (conferido em run_probe)."""
        # SPEC-0100:UT-04
        for mode, message in ERRORS.items():
            for data in (probe_input(), probe_input("queue", QUEUE)):
                with self.subTest(mode=mode, kind=data["target"]["resource"]["kind"]):
                    scenario = rds_scenario()
                    scenario["fail"] = [{"mode": mode}]
                    self.install(scenario)
                    out = self.run_probe(data)
                    self.assertError(out, message)

    def test_failures_of_the_replication_group_call(self):
        """SPEC-0100:UT-04 — SSO expirado e AccessDenied na describe-replication-groups: a mensagem fixa e nenhuma
        get-metric-data."""
        # SPEC-0100:UT-04
        for mode in ("sso-expired", "denied"):
            with self.subTest(mode=mode):
                scenario = cache_scenario()
                scenario["fail"] = [{"mode": mode, "service": "elasticache"}]
                self.install(scenario)
                out = self.run_probe(probe_input(rid=CACHE, attrs=CACHE_ATTRS))
                self.assertError(out, ERRORS[mode])
                self.assertEqual(self.metric_calls(), [])

    def assertInvalidAnswer(self, scenario, data):
        """Exit 0, sem traceback (conferido em adapter), nenhum Infinity/NaN no stdout e a saída probe@2 com status
        error e "resposta inválida da aws"."""
        self.install(scenario)
        raw = self.adapter(stdin=json.dumps(data))
        self.assertEqual(raw.returncode, 0, output(raw))
        for constant in ("Infinity", "NaN"):
            self.assertNotIn(constant, raw.stdout, f"{constant} na saída do adaptador")
        self.install(scenario)
        self.assertError(self.run_probe(data), ERRORS["invalid-json"])

    def test_non_finite_values_are_an_invalid_answer(self):
        """SPEC-0100:UT-04 (Emenda v2) — Values com NaN, Infinity, -Infinity ou 1e999 no JSON da aws: "resposta
        inválida da aws", exit 0, nada não finito na saída."""
        # SPEC-0100:UT-04
        sent = key("QueueName", QUEUE, "NumberOfMessagesSent")
        for raw in ("[1.0, NaN]", "[Infinity]", "[-Infinity, 2.0]", "[1e999]"):
            with self.subTest(values=raw):
                scenario = queue_scenario()
                scenario["raw"] = {sent: raw}
                self.assertInvalidAnswer(scenario, probe_input("queue", QUEUE))

    def test_aggregation_overflow_is_an_invalid_answer(self):
        """SPEC-0100:UT-04 (Emenda v2) — valores finitos cuja agregação estoura (sum de [1e308, 1e308] e avg de
        [1e308, 1e308]): "resposta inválida da aws", nunca Infinity na saída."""
        # SPEC-0100:UT-04
        cases = [("sum", queue_scenario(), key("QueueName", QUEUE, "NumberOfMessagesSent"), probe_input("queue", QUEUE)),
                 ("avg", rds_scenario(), key("DBInstanceIdentifier", DB, "ReadLatency"), probe_input())]
        for stat_, scenario, series, data in cases:
            with self.subTest(stat=stat_):
                scenario["series"][series] = [1e308, 1e308]
                self.assertInvalidAnswer(scenario, data)

    def test_huge_integer_value_is_an_invalid_answer(self):
        """SPEC-0100:UT-04 (Emenda v2) — um inteiro JSON de ~400 dígitos em Values: "resposta inválida da aws", exit 0,
        sem traceback."""
        # SPEC-0100:UT-04
        scenario = queue_scenario()
        scenario["raw"] = {key("QueueName", QUEUE, "NumberOfMessagesSent"): "[1, " + "9" * 400 + "]"}
        self.assertInvalidAnswer(scenario, probe_input("queue", QUEUE))

    def test_without_aws_on_the_path(self):
        """SPEC-0100:UT-04 — sem aws no PATH: "aws não encontrado", sem chamada."""
        # SPEC-0100:UT-04
        self.install()
        out = self.run_probe(probe_input(), with_aws=False)
        self.assertError(out, "aws não encontrado")
        self.assertEqual(self.calls(), [])


# --------------------------------------------------------------------------- UT-05


class AllowListTest(CloudwatchCase):
    def test_every_call_of_every_target_is_in_the_list(self):
        """SPEC-0100:UT-05 — rds, aurora (com e sem serverless), cache por nós, cache serverless, queue e topic: todo
        argv é cloudwatch get-metric-data ou elasticache describe-replication-groups com as opções comuns; as
        consultas são exatamente as da tabela (até 60, só MetricStat, sem Expression), conferidas em run_probe."""
        # SPEC-0100:UT-05
        cases = [probe_input(), probe_input(attrs=AURORA_ATTRS), probe_input(attrs=dict(AURORA_ATTRS, serverless=True)),
                 probe_input(rid=CACHE, attrs=CACHE_ATTRS), probe_input(rid=CACHE, attrs=SERVERLESS_ATTRS),
                 probe_input("queue", QUEUE), probe_input("topic", TOPIC)]
        for data in cases:
            resource = data["target"]["resource"]
            with self.subTest(set=metric_set(resource["kind"], resource["attrs"]),
                              serverless=resource["attrs"].get("serverless")):
                self.install(cache_scenario())
                out = self.run_probe(data)
                self.assertEqual(out["status"], "ok", out)
                self.assertEqual(len(self.metric_calls()), 1)
                for argv in self.metric_calls():
                    queries = queries_of(argv)
                    self.assertLessEqual(len(queries), 60)
                    self.assertNotIn("Expression", json.dumps(queries))

    def test_free_metric_attributes_are_ignored(self):
        """SPEC-0100:UT-05 — attrs com metric, namespace, expression, dimension e stat: as consultas são as mesmas da
        tabela (iguais às de um alvo sem essas chaves)."""
        # SPEC-0100:UT-05
        def queries(attrs):
            self.install()
            self.run_probe(probe_input(attrs=attrs))
            found = queries_of(self.metric_calls()[0])
            return sorted(json.dumps(q["MetricStat"], sort_keys=True) for q in found)

        plain = queries(RDS_ATTRS)
        loaded = queries(dict(RDS_ATTRS, metric="CPUCreditBalance", namespace="AWS/EC2", stat="p99",
                              expression="SEARCH('{AWS/RDS} MetricName', 'Sum', 60)", dimension="InstanceId",
                              arn=f"arn:aws:rds:{REGION}:{ACCOUNT}:db:{DB}"))
        self.assertEqual(loaded, plain)
        self.assertNotIn("CPUCreditBalance", json.dumps(loaded))
        self.assertNotIn("SEARCH", json.dumps(loaded))

    def test_other_verbs_and_capabilities_are_refused_without_any_call(self):
        """SPEC-0100:UT-05 — verbo alarms, verbo logs e capacidade messaging: "chamada não permitida", sem chamada."""
        # SPEC-0100:UT-05
        self.install()
        for data in (probe_input(verb="alarms"), probe_input(verb="logs"), probe_input(capability="messaging")):
            with self.subTest(verb=data["verb"], capability=data["capability"]):
                result = self.adapter(stdin=json.dumps(data))
                self.assertEqual(result.returncode, 0, output(result))
                out = json.loads(result.stdout)
                self.assertEqual(f("validate_probe_output")(out), [], out)
                self.assertError(out, REFUSED)
        self.assertEqual(self.calls(), [])


# --------------------------------------------------------------------------- UT-06


class InputTest(CloudwatchCase):
    def test_inputs_out_of_the_rule_are_refused_without_any_call(self):
        """SPEC-0100:UT-06 — datastore sem type, com type sqs, queue com type sns, elasticache memcached, serverless
        "sim", sem região, região "us-east-1; rm", id com - no começo, fila com 81 caracteres, profile com quebra de
        linha e stdin que não é probe@2: a mensagem fixa e nenhuma chamada."""
        # SPEC-0100:UT-06
        no_type = {k: v for k, v in RDS_ATTRS.items() if k != "type"}
        no_region = {k: v for k, v in RDS_ATTRS.items() if k != "region"}
        cases = [
            ("datastore sem type", probe_input(attrs=no_type), NO_SIGNALS),
            ("datastore com type sqs", probe_input(attrs={"type": "sqs", "region": REGION}), NO_SIGNALS),
            ("queue com type sns", probe_input("queue", QUEUE, attrs={"type": "sns", "region": REGION}), NO_SIGNALS),
            ("topic com type rds", probe_input("topic", TOPIC, attrs={"type": "rds", "region": REGION}), NO_SIGNALS),
            ("datastore com type s3", probe_input(attrs={"type": "s3", "region": REGION}), NO_SIGNALS),
            ("memcached", probe_input(rid=CACHE, attrs=dict(CACHE_ATTRS, engine="memcached")), NO_SIGNALS),
            ("serverless sim", probe_input(rid=CACHE, attrs=dict(CACHE_ATTRS, serverless="sim")), INVALID_INPUT),
            ("sem região", probe_input(attrs=no_region), NO_REGION),
            ("região com ;", probe_input(attrs=dict(RDS_ATTRS, region="us-east-1; rm")), INVALID_INPUT),
            ("id com -", probe_input(rid="-orders-db"), INVALID_INPUT),
            ("id rds com 64", probe_input(rid="a" * 64), INVALID_INPUT),
            ("id cache com 41", probe_input(rid="c" * 41, attrs=CACHE_ATTRS), INVALID_INPUT),
            ("fila com 81", probe_input("queue", "q" * 81), INVALID_INPUT),
            ("tópico com espaço", probe_input("topic", "orders events"), INVALID_INPUT),
            ("profile com quebra", probe_input(profile="acme\nread"), INVALID_INPUT),
            ("profile com - no começo", probe_input(profile="--debug"), INVALID_INPUT),
            ("probe@1", probe_input(contract="probe@1"), INVALID_INPUT),
        ]
        for label, data, message in cases:
            with self.subTest(case=label):
                self.install()
                out = self.run_probe(data)
                self.assertError(out, message)
                self.assertEqual(self.calls(), [], label)
        for raw in ("isto não é json", "[]", json.dumps({"contract": "probe@2"})):
            with self.subTest(raw=raw[:20]):
                self.install()
                result = self.adapter(stdin=raw)
                self.assertEqual(result.returncode, 0, output(result))
                out = json.loads(result.stdout)
                self.assertEqual(f("validate_probe_output")(out), [], out)
                self.assertError(out, INVALID_INPUT)
                self.assertEqual(self.calls(), [])

    def test_names_at_the_limit_are_accepted(self):
        """SPEC-0100:UT-06 — os limites: fila de 80 caracteres e .fifo, id rds de 63 e cache de 40 chegam à aws."""
        # SPEC-0100:UT-06
        for data in (probe_input("queue", "q" * 80), probe_input("queue", "jobs.fifo"),
                     probe_input(rid="a" * 63), probe_input(rid="c" * 40, attrs=SERVERLESS_ATTRS)):
            with self.subTest(rid=data["target"]["resource"]["id"][:12]):
                self.install()
                out = self.run_probe(data)
                self.assertEqual(out["status"], "ok", out)
                self.assertTrue(self.metric_calls())

    def test_account_ids_from_the_answers_never_show(self):
        """SPEC-0100:UT-06 — respostas com 123456789012 em ARNs e mensagens (grupo de replicação, consulta
        Forbidden): a conta não aparece na saída (conferido em run_probe)."""
        # SPEC-0100:UT-06
        scenario = cache_scenario()
        scenario["status"] = {key("CacheClusterId", NODES[0], "CacheMisses"): "Forbidden"}
        self.install(scenario)
        out = self.run_probe(probe_input(rid=CACHE, attrs=CACHE_ATTRS))
        self.assertEqual(out["status"], "ok", out)
        self.assertNotIn(ACCOUNT, json.dumps(out))


# --------------------------------------------------------------------------- CT-02


class Table4aTest(CloudwatchCase):
    def real_outputs(self):
        outputs = []
        for scenario, data in ((rds_scenario(), probe_input()), (cache_scenario(), probe_input(rid=CACHE, attrs=CACHE_ATTRS)),
                               (queue_scenario(), probe_input("queue", QUEUE)),
                               (queue_scenario(), probe_input(rid=CACHE, attrs=SERVERLESS_ATTRS)),
                               (queue_scenario(), probe_input("topic", TOPIC))):
            self.install(scenario)
            outputs.append(self.run_probe(data))
        return outputs

    def test_real_outputs_follow_table_4a(self):
        """SPEC-0100:CT-02 — as saídas reais de metrics (rds, cache por nós, fila, cache serverless e tópico) cumprem
        a tabela 4a do ADR-0026: name, stat em sum|count|avg|min|max|p<n>, value finito ou null, kind em
        error|latency|saturation|traffic e sem (name, stat) repetido."""
        # SPEC-0100:CT-02
        for out in self.real_outputs():
            with self.subTest(items=len(out["items"])):
                self.assertEqual(out["status"], "ok", out)
                self.assertTrue(out["items"])
                self.assertEqual(table_4a_problems(out), [])

    def test_the_same_check_refuses_broken_outputs(self):
        """SPEC-0100:CT-02 — a mesma conferência recusa um item com category no lugar de kind, stat Average, value em
        texto e um (name, stat) repetido."""
        # SPEC-0100:CT-02
        self.install()
        out = self.run_probe(probe_input())
        category = copy.deepcopy(out)
        category["items"][0]["category"] = category["items"][0].pop("kind")
        self.assertTrue(table_4a_problems(category))
        average = copy.deepcopy(out)
        average["items"][0]["stat"] = "Average"
        self.assertTrue(table_4a_problems(average))
        text = copy.deepcopy(out)
        text["items"][0]["value"] = "0.003"
        self.assertTrue(table_4a_problems(text))
        repeated = copy.deepcopy(out)
        repeated["items"].append(dict(repeated["items"][0]))
        self.assertTrue(table_4a_problems(repeated))
        infinite = copy.deepcopy(out)
        infinite["items"][0]["value"] = float("inf")
        self.assertTrue(table_4a_problems(infinite))


# --------------------------------------------------------------------------- CT-01

DOC_BLOCK_RE = re.compile(r"```json probe@2 (describe|input|output) (valid|invalid)[ \t]*\n(.*?)```", re.DOTALL)
VALIDATORS = {"describe": "validate_probe_describe", "input": "validate_probe_input",
              "output": "validate_probe_output"}


class ContractTest(CloudwatchCase):
    def test_describe_follows_probe_2(self):
        """SPEC-0100:CT-01 — `cloudwatch.py --describe` imprime exatamente a descrição do contrato, aceita pelo
        validate_probe_describe do núcleo, sem chamar a aws."""
        # SPEC-0100:CT-01
        self.install()
        result = self.adapter("--describe")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(data, DESCRIBE)
        self.assertEqual(f("validate_probe_describe")(data), [])
        self.assertEqual(self.calls(), [])

    def test_real_outputs_pass_the_core_validator(self):
        """SPEC-0100:CT-01 — as entradas usadas passam no validate_probe_input; as saídas reais de metrics com
        valores, sem dados, de um erro da aws e de uma entrada recusada passam no validate_probe_output (e no leitor
        do núcleo, sem NaN) em run_probe."""
        # SPEC-0100:CT-01
        cases = [(rds_scenario(), probe_input(), "ok"),
                 ({"account": ACCOUNT, "series": {}, "fail": []}, probe_input("queue", QUEUE), "ok"),
                 (dict(rds_scenario(), fail=[{"mode": "sso-expired"}]), probe_input(), "error"),
                 (rds_scenario(), probe_input(attrs={"type": "s3", "region": REGION}), "error")]
        for scenario, data, status in cases:
            with self.subTest(status=status, kind=data["target"]["resource"]["kind"]):
                self.assertEqual(f("validate_probe_input")(data), [])
                self.install(scenario)
                out = self.run_probe(data)
                self.assertEqual(out["status"], status, out)

    def test_examples_of_the_reference(self):
        """SPEC-0100:CT-01 — references/probes/cloudwatch.md traz blocos ```json probe@2 <describe|input|output>
        <valid|invalid>: ao menos um válido de cada tipo, ao menos 2 inválidos de describe (targets com kind
        desconhecido, access desconhecido) e 3 de output (item com objeto aninhado, value NaN, chave a mais); os
        válidos passam no leitor e no validador do núcleo, os inválidos são recusados por um deles."""
        # SPEC-0100:CT-01
        self.assertTrue(REFERENCE.is_file(), f"{REFERENCE.relative_to(SKILL)} não existe ({SPEC})")
        text = REFERENCE.read_text(encoding="utf-8")
        blocks = [(m.group(1), m.group(2), m.group(3)) for m in DOC_BLOCK_RE.finditer(text)]
        for kind in VALIDATORS:
            self.assertTrue([b for b in blocks if b[:2] == (kind, "valid")], f"sem bloco {kind} valid")
        self.assertGreaterEqual(len([b for b in blocks if b[:2] == ("describe", "invalid")]), 2)
        self.assertGreaterEqual(len([b for b in blocks if b[:2] == ("output", "invalid")]), 3)
        self.assertTrue([b for b in blocks if b[:2] == ("output", "invalid") and "NaN" in b[2]],
                        "sem bloco output invalid com value NaN")
        reader = {"parse_constant": f("_reject_constant"), "parse_float": f("_finite_float")}
        for kind, verdict, raw in blocks:
            with self.subTest(kind=kind, verdict=verdict, data=raw[:80]):
                try:
                    data = json.loads(raw, **reader)
                except ValueError:
                    self.assertEqual(verdict, "invalid", f"bloco valid que o núcleo não lê: {raw[:80]}")
                    continue
                problems = f(VALIDATORS[kind])(data)
                if verdict == "valid":
                    self.assertEqual(problems, [])
                    if kind == "output" and data.get("status") == "ok":
                        self.assertEqual(table_4a_problems(data), [])
                else:
                    self.assertTrue(problems and all(isinstance(p, str) and p for p in problems), problems)
        valid_text = "\n".join(b[2] for b in blocks if b[1] == "valid")
        for value in (ACCOUNT, "arn:aws", "amazonaws.com"):
            self.assertNotIn(value, valid_text)


# --------------------------------------------------------------------------- IT-01 e IT-02


class EndToEndTest(unittest.TestCase):
    """Atlas temporário (cópia de fixtures/probe-resource/atlas, com datastore:orders-db rds/postgres, queue:orders
    sqs e topic:orders-events ligados ao dev-api), access.cloud.dev.profile, o adaptador cloudwatch sem command e a
    AWS CLI falsa no início do PATH."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        shutil.copytree(ATLAS_FIXTURE, self.box.atlas)
        graph_path = self.box.atlas / "graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        nodes = {n["key"]: n for n in graph["nodes"]}
        nodes[f"datastore:{DB}"]["attrs"].update(RDS_ATTRS)
        nodes[f"queue:{QUEUE}"]["attrs"]["type"] = "sqs"
        topic = copy.deepcopy(nodes["topic:events"])
        topic.update(key=f"topic:{TOPIC}", name=TOPIC, attrs=dict(TOPIC_ATTRS))
        graph["nodes"].append(topic)
        for target, relation in ((f"datastore:{DB}", "depends_on"), (f"topic:{TOPIC}", "publishes")):
            graph["edges"].append({"from": "deployment:dev-api", "inferred": False, "sources": ["facts"],
                                   "to": target, "type": relation})
        graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        adapter = '    cloudwatch:\n      verbs: ["metrics"]\n      timeout: 120\n'
        local = (f"atlas: {json.dumps(str(self.box.atlas))}\ncredentials: {{}}\n"
                 f"access:\n  cloud:\n    \"dev\": {{profile: {json.dumps(PROFILE)}}}\n" + probes_yaml([adapter]))
        self.box.write_local(local)
        self.bin = self.box.root / "bin"
        self.record = self.box.root / "aws-calls.jsonl"
        self.log_path = self.box.config_home / "probes.log"

    def install(self, scenario):
        install_aws(self.bin, scenario, self.record)

    def probe(self, resource):
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        result = self.box.run("probe", "signals", "metrics", "--service", "api", "--env", "dev", "--resource",
                              resource, "--since", "30m", "--json", env=env)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def log(self):
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_metrics_through_the_core(self):
        """SPEC-0100:IT-01 — `atlas.py probe signals metrics --resource datastore:orders-db --since 30m --json` como
        processo: saída válida no núcleo com os itens do UT-01; o argv só tem as operações da lista, com o profile do
        access.cloud.dev; profile e conta fora da saída e do probes.log, que tem a linha com resource."""
        # SPEC-0100:IT-01
        self.install(rds_scenario())
        result = self.probe(f"datastore:{DB}")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(data), [], data)
        self.assertEqual((data["adapter"], data["capability"], data["verb"], data["status"]),
                         ("cloudwatch", "signals", "metrics", "ok"))
        self.assertEqual([i["name"] for i in data["items"]], [row[0] for row in TABLE["rds"][2]])
        self.assertEqual(table_4a_problems(data), [])
        items = {i["name"]: i for i in data["items"]}
        self.assertAlmostEqual(items["ReadLatency"]["value"], 0.003, places=9)
        self.assertEqual((items["CPUUtilization"]["value"], items["FreeStorageSpace"]["value"]), (70, 8e9))
        self.assertEqual({i["period"] for i in data["items"]}, {60})
        calls = read_calls(self.record)
        self.assertTrue(calls, "a aws falsa não foi chamada")
        for argv in calls:
            self.assertEqual(call_problems(argv, REGION, PROFILE), [], argv)
            self.assertEqual(query_problems(queries_of(argv), "rds", [DB], 60), [])
            options = parse_argv(argv)[1]
            self.assertEqual(parse_time(options["--end-time"]) - parse_time(options["--start-time"]), 1800)
        log_text = self.log_path.read_text(encoding="utf-8") if self.log_path.exists() else ""
        for value in (PROFILE, ACCOUNT):
            self.assertNotIn(value, output(result) + log_text, f"{value} apareceu na saída ou no probes.log")
        self.assertEqual([(line.get("resource"), line.get("status"), line.get("adapter")) for line in self.log()],
                         [(f"datastore:{DB}", "ok", "cloudwatch")])

    def test_queue_and_topic_through_the_core(self):
        """SPEC-0100:IT-01 — queue:orders e topic:orders-events ligados ao dev-api: saídas ok com os conjuntos sqs e
        sns."""
        # SPEC-0100:IT-01
        self.install(queue_scenario())
        for resource, set_name in ((f"queue:{QUEUE}", "sqs"), (f"topic:{TOPIC}", "sns")):
            with self.subTest(resource=resource):
                result = self.probe(resource)
                self.assertEqual(result.returncode, 0, output(result))
                data = json.loads(result.stdout)
                self.assertEqual(data["status"], "ok", data)
                self.assertEqual([i["name"] for i in data["items"]], [row[0] for row in TABLE[set_name][2]])

    def test_expired_login_exits_1_and_is_logged_without_the_profile(self):
        """SPEC-0100:IT-02 — a AWS CLI falsa responde SSO expirado: exit 1, status error com "renove o login da
        nuvem", probes.log com status error e sem o profile."""
        # SPEC-0100:IT-02
        scenario = rds_scenario()
        scenario["fail"] = [{"mode": "sso-expired"}]
        self.install(scenario)
        result = self.probe(f"datastore:{DB}")
        self.assertEqual(result.returncode, 1, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "error", data)
        self.assertIn("renove o login da nuvem", data.get("message", ""))
        self.assertNotIn(PROFILE, output(result))
        lines = self.log()
        self.assertEqual(len(lines), 1, lines)
        self.assertEqual((lines[0].get("status"), lines[0].get("resource")), ("error", f"datastore:{DB}"))
        self.assertNotIn(PROFILE, self.log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
