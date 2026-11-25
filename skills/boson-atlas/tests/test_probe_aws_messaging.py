"""Adaptador de mensageria aws: filas, DLQ e assinaturas (SPEC-0098: UT-01 a UT-06, IT-01, IT-02, CT-01 e CT-02;
ADR-0010, ADR-0023, ADR-0025, ADR-0026).

Contrato (seção 6 da SPEC-0098) que estes testes fixam:

    assets/probes/aws-messaging.py --describe ->
        {"contract": "probe@2", "adapter": "aws-messaging", "capabilities": {"messaging": {"verbs": ["queue",
         "subscriptions"], "targets": ["queue", "topic"], "access": ["cloud"]}}}
    entrada probe@2 no stdin (target.resource {kind, id, attrs}, target.cloud.profile); saída probe@2 no stdout, exit 0
    também no erro (status "error", items [], mensagem fixa).
    chamadas: sqs get-queue-url | sqs get-queue-attributes (os 4 atributos) | cloudwatch get-metric-data |
        sts get-caller-identity | sns list-subscriptions-by-topic | sns get-subscription-attributes; sempre com
        --region, --profile, --output json, --no-cli-pager, --cli-read-timeout 20, --cli-connect-timeout 10.
    queue -> exatamente 1 item {visible, in_flight, oldest_age_seconds, dlq_visible, delayed, fifo,
        oldest_age_source, dlq, dlq_in_flight, redrive, redrive_matches_dlq}.
    subscriptions -> um item por assinatura {destination, filter_fingerprint, destination_fingerprint, protocol,
        pending_confirmation, raw_delivery, has_filter, filter_scope, filter_keys, has_dlq}; message "<n> assinaturas,
        <m> pendentes".

Leituras desta suíte (listadas no relatório do test-writer):
    - Os itens têm exatamente as chaves do bloco de contrato da seção 6 (a tabela 4a do ADR-0026 e os campos a mais).
    - Na assinatura pendente, filter_keys é null ou [] ("os campos de atributo null"); numa assinatura confirmada sem
      filtro, filter_keys é [] ou null e has_filter é false.
    - has_dlq é true quando a assinatura tem RedrivePolicy ("DLQ da assinatura, só se existe").
    - filter_fingerprint é exatamente "sha256:" + os 16 primeiros hex do sha256 do JSON canônico da seção 6;
      destination_fingerprint só tem o formato conferido (a junção de protocolo e endpoint não está fixada).
    - A idade vem como inteiro (o CloudWatch devolve 42.0; o item traz 42).
    - Na contagem de chamadas (UT-05) o adaptador pode pular uma chamada (ex.: a DLQ quando a fila já falhou), nunca
      passar dos máximos da seção 5.
    - O timeout do processo de 30 s não é exercitado (deixaria a suíte lenta): o "timeout" vem do texto da CLI.

Dublê: fixtures/aws-messaging/fake_aws.py, copiado como `aws` numa pasta temporária (o único item do PATH nos testes
unitários), com o cenário em fake-aws.json ao lado; registra cada argv. Isolamento: HOME, XDG_CONFIG_HOME e
ATLAS_CONFIG_HOME temporários; nenhum ~/.aws, nenhuma AWS de verdade, nenhuma rede; nomes acme, orders, orders-dlq,
orders-events, notify, região us-east-1 e a conta de exemplo 123456789012 (que precisa sair mascarada).
"""
import copy
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from helpers import SKILL, TESTS, Sandbox, fn, output
from test_probe import probes_yaml

SPEC = "SPEC-0098"
ADAPTER = SKILL / "assets" / "probes" / "aws-messaging.py"
REFERENCE = SKILL / "references" / "probes" / "aws-messaging.md"
FIXTURES = TESTS / "fixtures" / "aws-messaging"
FAKE_AWS = FIXTURES / "fake_aws.py"
ATLAS_FIXTURE = TESTS / "fixtures" / "probe-resource" / "atlas"

ACCOUNT = "123456789012"
OTHER_ACCOUNT = "999999999999"
REGION = "us-east-1"
PROFILE = "acme-dev-read-0098"
TOPIC = "orders-events"
TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCOUNT}:{TOPIC}"
SUB_IDS = {
    "sqs": "11111111-aaaa-4bbb-8ccc-000000000001",
    "lambda": "11111111-aaaa-4bbb-8ccc-000000000002",
    "https-a": "11111111-aaaa-4bbb-8ccc-000000000003",
    "https-b": "11111111-aaaa-4bbb-8ccc-000000000004",
}
EMAIL = "pessoa.falsa@example.test"
HOOK_A = "https://hooks-a.example.test/orders"
HOOK_B = "https://hooks-b.example.test/orders"
FILTER = {"event_type": ["created"], "region": ["br"]}
FILTER_VALUES = ("created", "br")

DESCRIBE = {"contract": "probe@2", "adapter": "aws-messaging",
            "capabilities": {"messaging": {"verbs": ["queue", "subscriptions"], "targets": ["queue", "topic"],
                                           "access": ["cloud"]}}}
QUEUE_KEYS = {"visible", "in_flight", "oldest_age_seconds", "dlq_visible", "delayed", "fifo", "oldest_age_source",
              "dlq", "dlq_in_flight", "redrive", "redrive_matches_dlq"}
SUB_KEYS = {"destination", "filter_fingerprint", "destination_fingerprint", "protocol", "pending_confirmation",
            "raw_delivery", "has_filter", "filter_scope", "filter_keys", "has_dlq"}
QUEUE_ATTRIBUTES = {"ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible",
                    "ApproximateNumberOfMessagesDelayed", "RedrivePolicy"}
FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{16}\Z")
DESTINATION_RE = re.compile(r"^[a-z][a-z0-9_-]*:(?:\[REDACTED\]|[A-Za-z0-9_.-]+)\Z")

REFUSED = "chamada não permitida"
INVALID_INPUT = "entrada inválida"
NO_REGION = "recurso sem região no atlas"
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
    ("sqs", "get-queue-url"): {"--queue-name"},
    ("sqs", "get-queue-attributes"): {"--queue-url", "--attribute-names"},
    ("cloudwatch", "get-metric-data"): {"--metric-data-queries", "--start-time", "--end-time", "--scan-by"},
    ("sts", "get-caller-identity"): set(),
    ("sns", "list-subscriptions-by-topic"): {"--topic-arn"},
    ("sns", "get-subscription-attributes"): {"--subscription-arn"},
}
COMMON = {"--region", "--profile", "--output", "--no-cli-pager", "--cli-read-timeout", "--cli-connect-timeout"}
QUEUE_MAX = {("sqs", "get-queue-url"): 2, ("sqs", "get-queue-attributes"): 2, ("cloudwatch", "get-metric-data"): 1}


def f(name):
    return fn(name, "SPEC-0096")


# --------------------------------------------------------------------------- cenário do dublê


def redrive(target, count=5):
    return json.dumps({"deadLetterTargetArn": f"arn:aws:sqs:{REGION}:{ACCOUNT}:{target}", "maxReceiveCount": count})


def queue_attrs(visible, in_flight, delayed=0, dlq=None):
    attrs = {"ApproximateNumberOfMessages": str(visible), "ApproximateNumberOfMessagesNotVisible": str(in_flight),
             "ApproximateNumberOfMessagesDelayed": str(delayed),
             "QueueArn": f"arn:aws:sqs:{REGION}:{ACCOUNT}:x",
             "Policy": json.dumps({"Statement": [{"Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:root"}}]})}
    if dlq:
        attrs["RedrivePolicy"] = redrive(dlq)
    return attrs


def sub_arn(key):
    return f"{TOPIC_ARN}:{SUB_IDS[key]}"


def listing(arn, protocol, endpoint, topic_arn=TOPIC_ARN):
    return {"SubscriptionArn": arn, "Owner": ACCOUNT, "Protocol": protocol, "Endpoint": endpoint,
            "TopicArn": topic_arn}


def sub_attributes(arn, protocol, endpoint, raw="false", filter_policy=None, scope="MessageAttributes",
                   dlq=None, topic_arn=TOPIC_ARN):
    attrs = {"SubscriptionArn": arn, "TopicArn": topic_arn, "Owner": ACCOUNT, "Protocol": protocol,
             "Endpoint": endpoint, "PendingConfirmation": "false", "ConfirmationWasAuthenticated": "true",
             "RawMessageDelivery": raw, "SubscriptionPrincipal": f"arn:aws:iam::{ACCOUNT}:role/acme"}
    if filter_policy is not None:
        attrs["FilterPolicy"] = filter_policy if isinstance(filter_policy, str) else json.dumps(filter_policy)
        attrs["FilterPolicyScope"] = scope
    if dlq:
        attrs["RedrivePolicy"] = json.dumps({"deadLetterTargetArn": f"arn:aws:sqs:{REGION}:{ACCOUNT}:{dlq}"})
    return attrs


def topic_subscriptions(filter_policy=None, scope="MessageAttributes"):
    """(listagem, atributos) do tópico orders-events: sqs para orders com filtro, lambda notify (com DLQ), duas
    https e um e-mail pendente."""
    filter_policy = FILTER if filter_policy is None else filter_policy
    endpoints = {"sqs": ("sqs", f"arn:aws:sqs:{REGION}:{ACCOUNT}:orders"),
                 "lambda": ("lambda", f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:notify"),
                 "https-a": ("https", HOOK_A), "https-b": ("https", HOOK_B)}
    rows = [listing(sub_arn(k), p, e) for k, (p, e) in endpoints.items()]
    rows.append(listing("PendingConfirmation", "email", EMAIL))
    attrs = {
        sub_arn("sqs"): sub_attributes(sub_arn("sqs"), "sqs", endpoints["sqs"][1], raw="true",
                                       filter_policy=filter_policy, scope=scope),
        sub_arn("lambda"): sub_attributes(sub_arn("lambda"), "lambda", endpoints["lambda"][1], dlq="notify-dlq"),
        sub_arn("https-a"): sub_attributes(sub_arn("https-a"), "https", HOOK_A),
        sub_arn("https-b"): sub_attributes(sub_arn("https-b"), "https", HOOK_B),
    }
    return rows, attrs


def base_scenario():
    rows, attrs = topic_subscriptions()
    return {"account": ACCOUNT, "partition": "aws",
            "queues": {"orders": queue_attrs(12, 3, 0, dlq="orders-dlq"), "orders-dlq": queue_attrs(2, 0),
                       "jobs.fifo": queue_attrs(5, 1), "other-dlq": queue_attrs(9, 0)},
            "metrics": {"orders": [42, 40, 35], "jobs.fifo": [7]},
            "topics": {TOPIC: rows, "empty-events": []},
            "subscriptions": attrs,
            "fail": []}


def many_subscriptions(count):
    topic_arn = f"arn:aws:sns:{REGION}:{ACCOUNT}:bulk-events"
    rows, attrs = [], {}
    for n in range(count):
        arn = f"{topic_arn}:00000000-0000-4000-8000-{n:012d}"
        endpoint = f"arn:aws:sqs:{REGION}:{ACCOUNT}:q-{n:03d}"
        rows.append(listing(arn, "sqs", endpoint, topic_arn))
        attrs[arn] = sub_attributes(arn, "sqs", endpoint, topic_arn=topic_arn)
    return rows, attrs


def canonical_fingerprint(policy):
    text = json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


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


def call_problems(argv, region, profile) -> list:
    """SPEC-0098:UT-05 — problemas de um argv frente à lista fechada da seção 6; [] = permitido."""
    words, options = parse_argv(argv)
    pair = tuple(words[:2])
    if len(words) != 2 or pair not in OPERATIONS:
        return [f"operação fora da lista: {words}"]
    if argv[:2] != list(pair):
        problems = ["o argv não começa com <serviço> <operação>"]
    else:
        problems = []
    unknown = set(options) - COMMON - OPERATIONS[pair]
    if unknown:
        problems.append(f"opções fora da lista: {sorted(unknown)}")
    expected = {"--region": region, "--profile": profile, "--output": "json", "--no-cli-pager": True,
                "--cli-read-timeout": "20", "--cli-connect-timeout": "10"}
    for name, value in expected.items():
        if options.get(name) != value:
            problems.append(f"{name} diferente de {value!r}: {options.get(name)!r}")
    if pair == ("sqs", "get-queue-attributes"):
        names = options.get("--attribute-names")
        names = [names] if isinstance(names, str) else list(names) if isinstance(names, list) else []
        if set(names) != QUEUE_ATTRIBUTES or len(names) != len(QUEUE_ATTRIBUTES):
            problems.append(f"get-queue-attributes pede outros atributos: {names}")
    if pair == ("cloudwatch", "get-metric-data"):
        problems += metric_problems(options)
    for key in ("--queue-name", "--queue-url", "--topic-arn", "--subscription-arn"):
        if key in options and not isinstance(options[key], str):
            problems.append(f"{key} sem um valor só")
    return problems


def metric_problems(options) -> list:
    try:
        queries = json.loads(options.get("--metric-data-queries") or "")
    except (TypeError, ValueError):
        return ["--metric-data-queries não é JSON (file:// e outros são proibidos)"]
    if not isinstance(queries, list) or len(queries) != 1:
        return [f"get-metric-data com {len(queries) if isinstance(queries, list) else '?'} consultas"]
    stat_ = (queries[0] or {}).get("MetricStat") or {}
    metric = stat_.get("Metric") or {}
    problems = []
    if (metric.get("Namespace"), metric.get("MetricName")) != ("AWS/SQS", "ApproximateAgeOfOldestMessage"):
        problems.append("métrica diferente de AWS/SQS ApproximateAgeOfOldestMessage")
    if [d.get("Name") for d in metric.get("Dimensions") or []] != ["QueueName"]:
        problems.append("dimensão diferente de QueueName")
    if (stat_.get("Stat"), stat_.get("Period")) != ("Maximum", 60):
        problems.append("estatística diferente de Maximum, 60 s")
    if options.get("--scan-by") != "TimestampDescending":
        problems.append("--scan-by diferente de TimestampDescending")
    start, end = parse_time(options.get("--start-time")), parse_time(options.get("--end-time"))
    if start is None or end is None or not 540 <= (end - start) <= 660:
        problems.append("janela diferente de 10 minutos")
    return problems


def parse_time(value):
    if not isinstance(value, str):
        return None
    if re.match(r"^\d+(\.\d+)?\Z", value):
        return float(value)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def probe_input(verb, rid=None, attrs=None, kind=None, profile=PROFILE, lines=200, contract="probe@2"):
    kind = kind or ("topic" if verb == "subscriptions" else "queue")
    rid = rid or (TOPIC if kind == "topic" else "orders")
    if attrs is None:
        attrs = {"region": REGION, "type": "sns" if kind == "topic" else "sqs"}
        if rid == "orders":
            attrs["dlq"] = "orders-dlq"
    return {"contract": contract, "capability": "messaging", "verb": verb,
            "target": {"service": "api", "environment": "dev", "deployment": "dev-api",
                       "resource": {"kind": kind, "id": rid, "attrs": attrs}, "cloud": {"profile": profile}},
            "limits": {"lines": lines, "since_seconds": 1800}}


def table_4a_problems(verb, out) -> list:
    """SPEC-0098:CT-02 — a conferência da tabela 4a do ADR-0026 (o que o verify@2 lê) sobre uma saída ok."""
    items = out.get("items")
    if not isinstance(items, list):
        return ["items não é lista"]
    problems = []

    def count(value):
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    if verb == "queue":
        if len(items) != 1:
            return [f"queue com {len(items)} itens (exatamente 1)"]
        item = items[0]
        for key in ("visible", "in_flight"):
            if not count(item.get(key)):
                problems.append(f"{key} precisa ser inteiro >= 0")
        for key in ("oldest_age_seconds", "dlq_visible"):
            if key not in item or not (item[key] is None or count(item[key])):
                problems.append(f"{key} precisa ser inteiro >= 0 ou null")
        return problems
    seen = set()
    for index, item in enumerate(items):
        destination = item.get("destination")
        if not (isinstance(destination, str) and DESTINATION_RE.match(destination)):
            problems.append(f"items[{index}].destination fora de kind:id ou <protocolo>:[REDACTED]")
        fingerprint = item.get("filter_fingerprint", "ausente")
        if not (fingerprint is None or (isinstance(fingerprint, str) and FINGERPRINT_RE.match(fingerprint))):
            problems.append(f"items[{index}].filter_fingerprint fora de sha256:<16 hex> ou null")
        pair = (destination, item.get("destination_fingerprint"))
        if pair in seen:
            problems.append(f"items[{index}] repete (destination, destination_fingerprint)")
        seen.add(pair)
    return problems


# --------------------------------------------------------------------------- base


class AwsCase(unittest.TestCase):
    """Uma pasta temporária por teste: HOME, configuração e a pasta do aws falso (o único item do PATH)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.record = self.root / "aws-calls.jsonl"
        self.scenario = base_scenario()

    def install(self, scenario=None):
        self.record.unlink(missing_ok=True)
        install_aws(self.bin, self.scenario if scenario is None else scenario, self.record)

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
        conta, ARN ou URL da fila na saída, e cada chamada contra a lista fechada (UT-05)."""
        result = self.adapter(stdin=raw if raw is not None else json.dumps(data), with_aws=with_aws)
        self.assertEqual(result.returncode, 0, output(result))
        text = output(result)
        for value in (PROFILE, ACCOUNT, OTHER_ACCOUNT, "arn:aws", "amazonaws.com", *SUB_IDS.values()):
            self.assertNotIn(value, text, f"{value} apareceu na saída do adaptador")
        out = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(out), [], out)
        self.assertEqual({k: out.get(k) for k in ("contract", "adapter", "capability")},
                         {"contract": "probe@2", "adapter": "aws-messaging", "capability": "messaging"})
        if isinstance(data, dict):
            self.assertEqual(out.get("verb"), data["verb"])
            self.assertAllowedCalls(data)
        return out

    def calls(self):
        return read_calls(self.record)

    def pairs(self):
        return [tuple(parse_argv(argv)[0][:2]) for argv in self.calls()]

    def assertAllowedCalls(self, data):
        """SPEC-0098:UT-05 — todo argv da lista fechada, com as opções comuns, e os máximos da seção 5."""
        # SPEC-0098:UT-05
        attrs = data["target"]["resource"]["attrs"]
        region = attrs.get("region") if isinstance(attrs, dict) else None
        for argv in self.calls():
            self.assertEqual(call_problems(argv, region, data["target"]["cloud"]["profile"]), [], argv)
        pairs = self.pairs()
        if data["verb"] == "queue":
            for pair in pairs:
                self.assertIn(pair, QUEUE_MAX, f"queue chamou {pair}")
            for pair, top in QUEUE_MAX.items():
                self.assertLessEqual(pairs.count(pair), top, f"{pair} mais de {top} vezes: {pairs}")
        elif data["verb"] == "subscriptions":
            for pair in pairs:
                self.assertIn(pair, {("sts", "get-caller-identity"), ("sns", "list-subscriptions-by-topic"),
                                     ("sns", "get-subscription-attributes")}, f"subscriptions chamou {pair}")
            self.assertLessEqual(pairs.count(("sts", "get-caller-identity")), 1, pairs)
            self.assertLessEqual(pairs.count(("sns", "list-subscriptions-by-topic")), 1, pairs)
            self.assertLessEqual(pairs.count(("sns", "get-subscription-attributes")), 100, len(pairs))

    def assertError(self, out, message):
        self.assertEqual(out["status"], "error", out)
        self.assertEqual(out["items"], [], out)
        self.assertEqual(out.get("message"), message, out)

    def option_of(self, pair, name):
        return [parse_argv(a)[1].get(name) for a in self.calls() if tuple(parse_argv(a)[0][:2]) == pair]

    def queue_item(self, data):
        out = self.run_probe(data)
        self.assertEqual(out["status"], "ok", out)
        self.assertEqual(len(out["items"]), 1, out)
        item = out["items"][0]
        self.assertEqual(set(item), QUEUE_KEYS, item)
        return item

    def subscriptions(self, data):
        out = self.run_probe(data)
        self.assertEqual(out["status"], "ok", out)
        for item in out["items"]:
            self.assertEqual(set(item), SUB_KEYS, item)
        return out


# --------------------------------------------------------------------------- UT-01


class QueueTest(AwsCase):
    def test_queue_with_dlq_and_redrive_policy(self):
        """SPEC-0098:UT-01 — fila orders (12 visíveis, 3 em voo, 0 atrasadas, RedrivePolicy para orders-dlq), DLQ com
        2 visíveis e idade 42: exatamente um item com as contagens, a idade do CloudWatch e redrive_matches_dlq
        true; as URLs vêm de sqs get-queue-url (o atributo url com conta no attrs é ignorado)."""
        # SPEC-0098:UT-01
        self.install()
        attrs = {"region": REGION, "type": "sqs", "dlq": "orders-dlq",
                 "url": f"https://sqs.{REGION}.amazonaws.com/{OTHER_ACCOUNT}/evil"}
        item = self.queue_item(probe_input("queue", attrs=attrs))
        self.assertEqual({k: item[k] for k in ("visible", "in_flight", "oldest_age_seconds", "dlq_visible",
                                                "delayed", "oldest_age_source", "dlq", "redrive",
                                                "redrive_matches_dlq", "fifo", "dlq_in_flight")},
                         {"visible": 12, "in_flight": 3, "oldest_age_seconds": 42, "dlq_visible": 2, "delayed": 0,
                          "oldest_age_source": "cloudwatch", "dlq": "queue:orders-dlq", "redrive": True,
                          "redrive_matches_dlq": True, "fifo": False, "dlq_in_flight": 0})
        for key in ("visible", "in_flight", "oldest_age_seconds", "dlq_visible", "delayed"):
            self.assertIs(type(item[key]), int, f"{key}: {item[key]!r}")
        self.assertEqual(sorted(self.option_of(("sqs", "get-queue-url"), "--queue-name")), ["orders", "orders-dlq"])
        self.assertEqual(sorted(self.option_of(("sqs", "get-queue-attributes"), "--queue-url")),
                         [f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/orders",
                          f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/orders-dlq"])
        self.assertNotIn(OTHER_ACCOUNT, json.dumps(self.calls()), "o atributo url do atlas foi usado")

    def test_fifo_queue_without_dlq(self):
        """SPEC-0098:UT-01 — jobs.fifo sem attrs.dlq e sem RedrivePolicy: fifo true, redrive false, dlq_visible,
        dlq, dlq_in_flight e redrive_matches_dlq null, uma fila só consultada."""
        # SPEC-0098:UT-01
        self.install()
        item = self.queue_item(probe_input("queue", rid="jobs.fifo", attrs={"region": REGION, "type": "sqs"}))
        self.assertEqual({k: item[k] for k in ("visible", "in_flight", "fifo", "redrive", "dlq_visible", "dlq",
                                                "dlq_in_flight", "redrive_matches_dlq", "oldest_age_seconds")},
                         {"visible": 5, "in_flight": 1, "fifo": True, "redrive": False, "dlq_visible": None,
                          "dlq": None, "dlq_in_flight": None, "redrive_matches_dlq": None,
                          "oldest_age_seconds": 7})
        self.assertEqual(self.option_of(("sqs", "get-queue-url"), "--queue-name"), ["jobs.fifo"])

    def test_redrive_policy_pointing_to_another_queue(self):
        """SPEC-0098:UT-01 — RedrivePolicy de orders aponta para other-dlq e attrs.dlq é orders-dlq:
        redrive_matches_dlq false, redrive true, dlq_visible da orders-dlq."""
        # SPEC-0098:UT-01
        self.scenario["queues"]["orders"] = queue_attrs(12, 3, 0, dlq="other-dlq")
        self.install()
        item = self.queue_item(probe_input("queue"))
        self.assertIs(item["redrive"], True)
        self.assertIs(item["redrive_matches_dlq"], False)
        self.assertEqual(item["dlq_visible"], 2)
        self.assertEqual(item["dlq"], "queue:orders-dlq")

    def test_dlq_without_redrive_policy(self):
        """SPEC-0098:UT-01 — attrs.dlq sem RedrivePolicy na fila: redrive false e redrive_matches_dlq null, a DLQ
        ainda é lida."""
        # SPEC-0098:UT-01
        self.scenario["queues"]["orders"] = queue_attrs(12, 3, 0)
        self.install()
        item = self.queue_item(probe_input("queue"))
        self.assertIs(item["redrive"], False)
        self.assertIsNone(item["redrive_matches_dlq"])
        self.assertEqual(item["dlq_visible"], 2)


# --------------------------------------------------------------------------- UT-02


class QueueDegradedTest(AwsCase):
    def test_age_without_data_points(self):
        """SPEC-0098:UT-02 — get-metric-data sem pontos: oldest_age_seconds null com "sem dados", resto preenchido,
        status ok."""
        # SPEC-0098:UT-02
        self.scenario["metrics"] = {}
        self.install()
        item = self.queue_item(probe_input("queue"))
        self.assertIsNone(item["oldest_age_seconds"])
        self.assertEqual(item["oldest_age_source"], "sem dados")
        self.assertEqual((item["visible"], item["in_flight"], item["dlq_visible"]), (12, 3, 2))

    def test_age_without_permission(self):
        """SPEC-0098:UT-02 — AccessDenied só no get-metric-data: oldest_age_seconds null com "sem permissão", status
        ok e as contagens preenchidas."""
        # SPEC-0098:UT-02
        self.scenario["fail"] = [{"mode": "denied", "service": "cloudwatch", "operation": "get-metric-data"}]
        self.install()
        item = self.queue_item(probe_input("queue"))
        self.assertIsNone(item["oldest_age_seconds"])
        self.assertEqual(item["oldest_age_source"], "sem permissão")
        self.assertEqual((item["visible"], item["in_flight"], item["dlq_visible"]), (12, 3, 2))

    def test_missing_queue_and_missing_dlq(self):
        """SPEC-0098:UT-02 — QueueDoesNotExist para a fila: "fila não encontrada"; para a DLQ: "DLQ não
        encontrada"; status error e items []."""
        # SPEC-0098:UT-02
        self.install()
        out = self.run_probe(probe_input("queue", rid="ghost", attrs={"region": REGION, "type": "sqs"}))
        self.assertError(out, "fila não encontrada")
        del self.scenario["queues"]["orders-dlq"]
        self.install()
        out = self.run_probe(probe_input("queue"))
        self.assertError(out, "DLQ não encontrada")


# --------------------------------------------------------------------------- UT-03


class SubscriptionsTest(AwsCase):
    def test_one_item_per_subscription_with_masked_destinations_and_filter_keys(self):
        """SPEC-0098:UT-03 — orders-events com sqs filtrada, lambda notify, duas https e um e-mail pendente: cinco
        itens, nenhum do tópico; queue:orders, function:notify, https:[REDACTED] duas vezes com impressões digitais
        diferentes; chaves e hash do filtro; pendente com pending_confirmation true; message "5 assinaturas, 1
        pendentes"; nenhum valor do filtro, e-mail ou host na saída; ordem por destination e
        destination_fingerprint."""
        # SPEC-0098:UT-03
        self.install()
        out = self.subscriptions(probe_input("subscriptions"))
        items = out["items"]
        self.assertEqual(len(items), 5, items)
        self.assertEqual(out.get("message"), "5 assinaturas, 1 pendentes")
        self.assertIs(out["truncated"], False)
        destinations = sorted(i["destination"] for i in items)
        self.assertEqual(destinations, sorted(["queue:orders", "function:notify", "https:[REDACTED]",
                                               "https:[REDACTED]", "email:[REDACTED]"]))
        order = [(i["destination"], i["destination_fingerprint"]) for i in items]
        self.assertEqual(order, sorted(order), "ordem diferente de (destination, destination_fingerprint)")
        for item in items:
            self.assertRegex(item["destination_fingerprint"], FINGERPRINT_RE)
        https = [i for i in items if i["destination"] == "https:[REDACTED]"]
        self.assertNotEqual(https[0]["destination_fingerprint"], https[1]["destination_fingerprint"])
        by = {i["destination"]: i for i in items}
        sqs = by["queue:orders"]
        self.assertEqual((sqs["protocol"], sqs["has_filter"], sqs["filter_scope"], sqs["filter_keys"],
                          sqs["raw_delivery"], sqs["pending_confirmation"], sqs["has_dlq"]),
                         ("sqs", True, "MessageAttributes", ["event_type", "region"], True, False, False))
        self.assertEqual(sqs["filter_fingerprint"], canonical_fingerprint(FILTER))
        notify = by["function:notify"]
        self.assertEqual((notify["protocol"], notify["has_filter"], notify["filter_fingerprint"],
                          notify["raw_delivery"], notify["has_dlq"]), ("lambda", False, None, False, True))
        self.assertIn(notify["filter_keys"], ([], None))
        for item in https:
            self.assertEqual((item["protocol"], item["filter_fingerprint"], item["pending_confirmation"]),
                             ("https", None, False))
        pending = by["email:[REDACTED]"]
        self.assertIs(pending["pending_confirmation"], True)
        for key in ("raw_delivery", "has_filter", "filter_scope", "filter_fingerprint", "has_dlq"):
            self.assertIsNone(pending[key], key)
        self.assertIn(pending["filter_keys"], ([], None))
        text = json.dumps(out, ensure_ascii=False)
        for value in (*FILTER_VALUES, EMAIL, "hooks-a", "hooks-b", "example.test", TOPIC_ARN, "notify-dlq"):
            self.assertNotIn(f'"{value}"' if value in FILTER_VALUES else value, text, value)
        self.assertNotIn("PendingConfirmation", self.option_of(("sns", "get-subscription-attributes"),
                                                               "--subscription-arn"))
        self.assertEqual(self.pairs().count(("sns", "get-subscription-attributes")), 4)

    def test_filter_fingerprint_is_stable_and_changes_with_a_value(self):
        """SPEC-0098:UT-03 — o mesmo filtro com as chaves em outra ordem dá a mesma impressão digital; com
        ["deleted"] dá outra; o valor novo não sai."""
        # SPEC-0098:UT-03
        self.install()
        first = self.subscriptions(probe_input("subscriptions"))
        reordered = '{"region": ["br"], "event_type": ["created"]}'
        _rows, attrs = topic_subscriptions(filter_policy=reordered)
        self.scenario["subscriptions"] = attrs
        self.install()
        second = self.subscriptions(probe_input("subscriptions"))
        _rows, attrs = topic_subscriptions(filter_policy={"event_type": ["deleted"], "region": ["br"]})
        self.scenario["subscriptions"] = attrs
        self.install()
        third = self.subscriptions(probe_input("subscriptions"))

        def fingerprint(out):
            return next(i["filter_fingerprint"] for i in out["items"] if i["destination"] == "queue:orders")

        self.assertEqual(fingerprint(first), fingerprint(second))
        self.assertNotEqual(fingerprint(first), fingerprint(third))
        self.assertNotIn('"deleted"', json.dumps(third))

    def test_message_body_filter_keys_are_dotted_paths(self):
        """SPEC-0098:UT-03 — filtro no escopo MessageBody com chave aninhada: filter_keys ["event_type",
        "payload.status"], filter_scope MessageBody, sem os valores."""
        # SPEC-0098:UT-03
        policy = {"payload": {"status": ["paid"]}, "event_type": ["created"]}
        _rows, attrs = topic_subscriptions(filter_policy=policy, scope="MessageBody")
        self.scenario["subscriptions"] = attrs
        self.install()
        out = self.subscriptions(probe_input("subscriptions"))
        sqs = next(i for i in out["items"] if i["destination"] == "queue:orders")
        self.assertEqual((sqs["filter_scope"], sqs["filter_keys"]), ("MessageBody", ["event_type", "payload.status"]))
        self.assertEqual(sqs["filter_fingerprint"], canonical_fingerprint(policy))
        self.assertNotIn('"paid"', json.dumps(out))

    def test_topic_arn_is_built_from_the_caller_identity(self):
        """SPEC-0098:UT-03 — o ARN do tópico vem da conta e da partição de sts get-caller-identity; um atributo arn
        no attrs (outra conta) é ignorado."""
        # SPEC-0098:UT-03
        self.install()
        attrs = {"region": REGION, "type": "sns", "arn": f"arn:aws:sns:{REGION}:{OTHER_ACCOUNT}:{TOPIC}"}
        self.subscriptions(probe_input("subscriptions", attrs=attrs))
        self.assertEqual(self.pairs().count(("sts", "get-caller-identity")), 1)
        self.assertEqual(self.option_of(("sns", "list-subscriptions-by-topic"), "--topic-arn"), [TOPIC_ARN])
        self.assertNotIn(OTHER_ACCOUNT, json.dumps(self.calls()))

    def test_partition_comes_from_the_caller_identity(self):
        """SPEC-0098:UT-03 — com a identidade numa partição aws-cn, o ARN do tópico usa arn:aws-cn."""
        # SPEC-0098:UT-03
        self.scenario["partition"] = "aws-cn"
        self.install()
        self.subscriptions(probe_input("subscriptions", attrs={"region": "cn-north-1", "type": "sns"}))
        self.assertEqual(self.option_of(("sns", "list-subscriptions-by-topic"), "--topic-arn"),
                         [f"arn:aws-cn:sns:cn-north-1:{ACCOUNT}:{TOPIC}"])

    def test_more_than_one_hundred_subscriptions_are_cut(self):
        """SPEC-0098:UT-03 — 150 assinaturas e lines 200: 100 itens, truncated true, no máximo 100
        get-subscription-attributes, message com o total listado."""
        # SPEC-0098:UT-03
        rows, attrs = many_subscriptions(150)
        self.scenario["topics"]["bulk-events"] = rows
        self.scenario["subscriptions"] = attrs
        self.install()
        out = self.subscriptions(probe_input("subscriptions", rid="bulk-events", lines=200))
        self.assertEqual(len(out["items"]), 100)
        self.assertIs(out["truncated"], True)
        self.assertEqual(out.get("message"), "150 assinaturas, 0 pendentes")
        self.assertLessEqual(self.pairs().count(("sns", "get-subscription-attributes")), 100)

    def test_more_than_limits_lines_are_cut(self):
        """SPEC-0098:UT-03 — cinco assinaturas e lines 3: 3 itens e truncated true."""
        # SPEC-0098:UT-03
        self.install()
        out = self.subscriptions(probe_input("subscriptions", lines=3))
        self.assertEqual(len(out["items"]), 3)
        self.assertIs(out["truncated"], True)
        self.assertEqual(out.get("message"), "5 assinaturas, 1 pendentes")

    def test_topic_without_subscriptions(self):
        """SPEC-0098:UT-03 — listagem vazia: items [], status ok, message "0 assinaturas, 0 pendentes"."""
        # SPEC-0098:UT-03
        self.install()
        out = self.subscriptions(probe_input("subscriptions", rid="empty-events"))
        self.assertEqual(out["items"], [])
        self.assertEqual(out.get("message"), "0 assinaturas, 0 pendentes")

    def test_missing_topic(self):
        """SPEC-0098:UT-03 — NotFound na listagem: status error, "tópico não encontrado"."""
        # SPEC-0098:UT-03
        self.install()
        out = self.run_probe(probe_input("subscriptions", rid="ghost-events"))
        self.assertError(out, "tópico não encontrado")


# --------------------------------------------------------------------------- UT-04


class ErrorTest(AwsCase):
    def test_cli_failures_become_fixed_messages(self):
        """SPEC-0098:UT-04 — SSO expirado, token expirado, profile inexistente, sem credenciais, AccessDenied,
        Throttling, sem conexão, timeout, JSON inválido, JSON de outra forma e outro erro, em queue e em
        subscriptions: exit 0, status error, items [] e a mensagem fixa; profile, ARN, URL e conta fora da saída
        (conferido em run_probe)."""
        # SPEC-0098:UT-04
        for mode, message in ERRORS.items():
            for verb in ("queue", "subscriptions"):
                with self.subTest(mode=mode, verb=verb):
                    scenario = base_scenario()
                    scenario["fail"] = [{"mode": mode}]
                    self.install(scenario)
                    out = self.run_probe(probe_input(verb))
                    self.assertError(out, message)

    def test_sns_authorization_error_is_access_denied(self):
        """SPEC-0098:UT-04 — AuthorizationError do sns na listagem: "sem permissão (AccessDenied)"."""
        # SPEC-0098:UT-04
        self.scenario["fail"] = [{"mode": "denied", "service": "sns"}]
        self.install()
        out = self.run_probe(probe_input("subscriptions"))
        self.assertError(out, "sem permissão (AccessDenied)")

    def test_without_aws_on_the_path(self):
        """SPEC-0098:UT-04 — sem aws no PATH: "aws não encontrado", sem chamada."""
        # SPEC-0098:UT-04
        self.install()
        for verb in ("queue", "subscriptions"):
            with self.subTest(verb=verb):
                out = self.run_probe(probe_input(verb), with_aws=False)
                self.assertError(out, "aws não encontrado")
        self.assertEqual(self.calls(), [])


# --------------------------------------------------------------------------- UT-05


class AllowListTest(AwsCase):
    def test_kind_swapped_unknown_verb_and_other_types_are_refused_without_any_call(self):
        """SPEC-0098:UT-05 — queue com alvo topic, subscriptions com alvo queue, verbo desconhecido, verbo
        "receive" e type fora de sqs/sns: "chamada não permitida" e nenhuma chamada registrada."""
        # SPEC-0098:UT-05
        self.install()
        cases = {
            "queue-topic": probe_input("queue", kind="topic", rid=TOPIC, attrs={"region": REGION}),
            "subscriptions-queue": probe_input("subscriptions", kind="queue", rid="orders",
                                               attrs={"region": REGION}),
            "unknown": dict(probe_input("queue"), verb="status"),
            "receive": dict(probe_input("queue"), verb="receive"),
            "purge": dict(probe_input("queue"), verb="purge-queue"),
            "type-queue": probe_input("queue", attrs={"region": REGION, "type": "kinesis"}),
            "type-topic": probe_input("subscriptions", attrs={"region": REGION, "type": "sqs"}),
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                self.record.unlink(missing_ok=True)
                out = self.run_probe(data)
                self.assertError(out, REFUSED)
                self.assertEqual(self.calls(), [], "o aws foi chamado")

    def test_every_call_of_every_scenario_is_in_the_list(self):
        """SPEC-0098:UT-05 — nos cenários de queue e subscriptions, todo argv começa com (serviço, operação) da
        lista, traz --region, --profile, --output json, --no-cli-pager e os timeouts, nenhuma opção fora da lista,
        get-queue-attributes só com os quatro atributos, e as contagens da seção 5 (fila com DLQ: 2 get-queue-url, 2
        get-queue-attributes, 1 get-metric-data; assinaturas: 1 sts, 1 listagem, 1 get por assinatura não
        pendente)."""
        # SPEC-0098:UT-05
        self.install()
        self.queue_item(probe_input("queue"))
        self.assertEqual(sorted(self.pairs()), sorted([("sqs", "get-queue-url")] * 2
                                                      + [("sqs", "get-queue-attributes")] * 2
                                                      + [("cloudwatch", "get-metric-data")]))
        self.install()
        self.subscriptions(probe_input("subscriptions"))
        self.assertEqual(sorted(self.pairs()), sorted([("sts", "get-caller-identity"),
                                                       ("sns", "list-subscriptions-by-topic")]
                                                      + [("sns", "get-subscription-attributes")] * 4))

    def test_the_metric_query_is_for_the_queue_of_the_target(self):
        """SPEC-0098:UT-05 — a consulta do get-metric-data é a da fila do alvo (QueueName = id do recurso)."""
        # SPEC-0098:UT-05
        self.install()
        self.queue_item(probe_input("queue"))
        queries = json.loads(self.option_of(("cloudwatch", "get-metric-data"), "--metric-data-queries")[0])
        dimensions = queries[0]["MetricStat"]["Metric"]["Dimensions"]
        self.assertEqual(dimensions, [{"Name": "QueueName", "Value": "orders"}])


# --------------------------------------------------------------------------- UT-06


class InputTest(AwsCase):
    def test_names_regions_and_profiles_out_of_the_rule_are_refused_without_any_call(self):
        """SPEC-0098:UT-06 — nome de fila com - no começo, com espaço, com 81 caracteres, tópico com - no começo,
        dlq com - no começo, região "us-east-1; rm", profile com quebra de linha ou começando com -, stdin probe@1 e
        stdin que não é JSON: "entrada inválida"; attrs.region ausente: "recurso sem região no atlas"; nenhuma
        chamada."""
        # SPEC-0098:UT-06
        self.install()
        sqs = {"region": REGION, "type": "sqs"}
        cases = {
            "dash": (probe_input("queue", rid="-orders", attrs=sqs), INVALID_INPUT),
            "space": (probe_input("queue", rid="ord ers", attrs=sqs), INVALID_INPUT),
            "long": (probe_input("queue", rid="q" * 81, attrs=sqs), INVALID_INPUT),
            "topic-dash": (probe_input("subscriptions", rid="-events", attrs={"region": REGION}), INVALID_INPUT),
            "dlq-dash": (probe_input("queue", attrs=dict(sqs, dlq="-orders-dlq")), INVALID_INPUT),
            "region": (probe_input("queue", attrs={"region": "us-east-1; rm", "type": "sqs"}), INVALID_INPUT),
            "no-region": (probe_input("queue", attrs={"type": "sqs", "dlq": "orders-dlq"}), NO_REGION),
            "no-region-topic": (probe_input("subscriptions", attrs={"type": "sns"}), NO_REGION),
            "profile-newline": (probe_input("queue", profile="acme\nread"), INVALID_INPUT),
            "profile-dash": (probe_input("queue", profile="--debug"), INVALID_INPUT),
            "probe1": (probe_input("queue", contract="probe@1"), INVALID_INPUT),
        }
        for name, (data, message) in cases.items():
            with self.subTest(case=name):
                self.record.unlink(missing_ok=True)
                out = self.run_probe(None, raw=json.dumps(data))
                self.assertError(out, message)
                self.assertEqual(self.calls(), [], "o aws foi chamado")
        for raw in ("{", "", "[]"):
            with self.subTest(raw=raw):
                out = self.run_probe(None, raw=raw)
                self.assertError(out, INVALID_INPUT)
                self.assertEqual(self.calls(), [])

    def test_the_eighty_character_queue_name_is_accepted(self):
        """SPEC-0098:UT-06 — o limite: um nome de 80 caracteres passa da validação e chega ao get-queue-url."""
        # SPEC-0098:UT-06
        name = "q" * 80
        self.scenario["queues"][name] = queue_attrs(1, 0)
        self.install()
        item = self.queue_item(probe_input("queue", rid=name, attrs={"region": REGION, "type": "sqs"}))
        self.assertEqual(item["visible"], 1)

    def test_account_ids_from_the_answers_never_show(self):
        """SPEC-0098:UT-06 — respostas com 123456789012 em ARNs e URLs (fila, DLQ, RedrivePolicy, Policy, assinaturas,
        identidade): nenhum 123456789012 na saída do adaptador, em queue e em subscriptions (conferido em
        run_probe)."""
        # SPEC-0098:UT-06
        self.install()
        self.queue_item(probe_input("queue"))
        self.install()
        out = self.subscriptions(probe_input("subscriptions"))
        self.assertTrue(out["items"])


# --------------------------------------------------------------------------- CT-02


class Table4aTest(AwsCase):
    def real_outputs(self):
        self.install()
        queue = self.run_probe(probe_input("queue"))
        self.install()
        fifo = self.run_probe(probe_input("queue", rid="jobs.fifo", attrs={"region": REGION, "type": "sqs"}))
        self.install()
        subs = self.run_probe(probe_input("subscriptions"))
        return queue, fifo, subs

    def test_real_outputs_follow_table_4a(self):
        """SPEC-0098:CT-02 — as saídas reais de queue (com DLQ e FIFO sem DLQ) e de subscriptions cumprem a tabela 4a
        do ADR-0026: 1 item com visible e in_flight inteiros >= 0, oldest_age_seconds e dlq_visible inteiros ou null;
        um item por assinatura com destination kind:id ou <protocolo>:[REDACTED], filter_fingerprint sha256:<16 hex>
        ou null e pares (destination, destination_fingerprint) sem repetição."""
        # SPEC-0098:CT-02
        queue, fifo, subs = self.real_outputs()
        self.assertEqual(table_4a_problems("queue", queue), [])
        self.assertEqual(table_4a_problems("queue", fifo), [])
        self.assertEqual(table_4a_problems("subscriptions", subs), [])
        self.assertEqual(len(subs["items"]), 5)

    def test_the_same_check_refuses_broken_outputs(self):
        """SPEC-0098:CT-02 — a mesma conferência recusa queue com um item a mais, queue sem in_flight e subscriptions
        com um item-resumo do tópico."""
        # SPEC-0098:CT-02
        queue, _, subs = self.real_outputs()
        extra = copy.deepcopy(queue)
        extra["items"].append(dict(extra["items"][0]))
        self.assertTrue(table_4a_problems("queue", extra))
        missing = copy.deepcopy(queue)
        del missing["items"][0]["in_flight"]
        self.assertTrue(table_4a_problems("queue", missing))
        summary = copy.deepcopy(subs)
        summary["items"].append({"topic": TOPIC, "subscriptions": 5, "pending": 1})
        self.assertTrue(table_4a_problems("subscriptions", summary))


# --------------------------------------------------------------------------- CT-01

DOC_BLOCK_RE = re.compile(r"```json probe@2 (describe|input|output) (valid|invalid)[ \t]*\n(.*?)```", re.DOTALL)
VALIDATORS = {"describe": "validate_probe_describe", "input": "validate_probe_input",
              "output": "validate_probe_output"}


class ContractTest(AwsCase):
    def test_describe_follows_probe_2(self):
        """SPEC-0098:CT-01 — `aws-messaging.py --describe` imprime exatamente a descrição do contrato, aceita pelo
        validate_probe_describe do núcleo, sem chamar a aws."""
        # SPEC-0098:CT-01
        self.install()
        result = self.adapter("--describe")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(data, DESCRIBE)
        self.assertEqual(f("validate_probe_describe")(data), [])
        self.assertEqual(self.calls(), [])

    def test_real_outputs_pass_the_core_validator(self):
        """SPEC-0098:CT-01 — as entradas usadas passam no validate_probe_input; as saídas reais de queue,
        subscriptions, de um erro da aws e de uma chamada recusada passam no validate_probe_output (run_probe)."""
        # SPEC-0098:CT-01
        cases = [("", probe_input("queue")), ("", probe_input("subscriptions")),
                 ("sso-expired", probe_input("queue")), ("", probe_input("queue", kind="topic", rid=TOPIC))]
        for mode, data in cases:
            with self.subTest(mode=mode, verb=data["verb"], kind=data["target"]["resource"]["kind"]):
                self.assertEqual(f("validate_probe_input")(data), [])
                scenario = base_scenario()
                scenario["fail"] = [{"mode": mode}] if mode else []
                self.install(scenario)
                out = self.run_probe(data)
                self.assertIn(out["status"], ("ok", "error"))

    def test_examples_of_the_reference(self):
        """SPEC-0098:CT-01 — references/probes/aws-messaging.md traz blocos ```json probe@2 <describe|input|output>
        <valid|invalid>: ao menos um válido de cada tipo e os inválidos de describe e de output (verbo com espaço,
        targets com kind desconhecido, item com objeto aninhado, chave a mais na saída); os válidos passam e os
        inválidos são recusados com motivo."""
        # SPEC-0098:CT-01
        self.assertTrue(REFERENCE.is_file(), f"{REFERENCE.relative_to(SKILL)} não existe ({SPEC})")
        text = REFERENCE.read_text(encoding="utf-8")
        blocks = [(m.group(1), m.group(2), json.loads(m.group(3))) for m in DOC_BLOCK_RE.finditer(text)]
        for kind in VALIDATORS:
            self.assertTrue([b for b in blocks if b[:2] == (kind, "valid")], f"sem bloco {kind} valid")
        for kind in ("describe", "output"):
            self.assertGreaterEqual(len([b for b in blocks if b[:2] == (kind, "invalid")]), 2,
                                    f"menos de 2 blocos {kind} invalid")
        for kind, verdict, data in blocks:
            with self.subTest(kind=kind, verdict=verdict, data=json.dumps(data)[:80]):
                problems = f(VALIDATORS[kind])(data)
                if verdict == "valid":
                    self.assertEqual(problems, [])
                else:
                    self.assertTrue(problems and all(isinstance(p, str) and p for p in problems), problems)
        for value in (ACCOUNT, "arn:aws", "amazonaws.com"):
            self.assertNotIn(value, "\n".join(json.dumps(b[2]) for b in blocks if b[1] == "valid"))


# --------------------------------------------------------------------------- IT-01 e IT-02


class EndToEndTest(unittest.TestCase):
    """Atlas temporário (cópia de fixtures/probe-resource/atlas, com type sqs em queue:orders e o tópico
    orders-events ligado ao dev-api), access.cloud.dev.profile, o adaptador aws-messaging sem command e a AWS CLI
    falsa no início do PATH."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        shutil.copytree(ATLAS_FIXTURE, self.box.atlas)
        graph_path = self.box.atlas / "graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        node = next(n for n in graph["nodes"] if n["key"] == "queue:orders")
        node["attrs"]["type"] = "sqs"
        topic = copy.deepcopy(next(n for n in graph["nodes"] if n["key"] == "topic:events"))
        topic.update(key=f"topic:{TOPIC}", name=TOPIC, attrs={"region": REGION, "type": "sns"})
        graph["nodes"].append(topic)
        graph["edges"].append({"from": "deployment:dev-api", "inferred": False, "sources": ["facts"],
                               "to": f"topic:{TOPIC}", "type": "publishes"})
        graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        adapter = '    aws-messaging:\n      verbs: ["queue", "subscriptions"]\n      timeout: 120\n'
        local = (f"atlas: {json.dumps(str(self.box.atlas))}\ncredentials: {{}}\n"
                 f"access:\n  cloud:\n    \"dev\": {{profile: {json.dumps(PROFILE)}}}\n" + probes_yaml([adapter]))
        self.box.write_local(local)
        self.bin = self.box.root / "bin"
        self.record = self.box.root / "aws-calls.jsonl"
        self.log_path = self.box.config_home / "probes.log"

    def install(self, scenario):
        install_aws(self.bin, scenario, self.record)

    def probe(self, verb, resource):
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        result = self.box.run("probe", "messaging", verb, "--service", "api", "--env", "dev", "--resource", resource,
                              "--json", env=env)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def log(self):
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_queue_and_subscriptions_through_the_core(self):
        """SPEC-0098:IT-01 — `atlas.py probe messaging queue --resource queue:orders` e `subscriptions --resource
        topic:orders-events` como processos: saídas válidas no núcleo com os itens do UT-01 e do UT-03; o argv só
        tem operações da lista de leitura, com o profile do access.cloud.dev; profile e conta fora da saída e do
        probes.log, que tem a linha com resource."""
        # SPEC-0098:IT-01
        self.install(base_scenario())
        result = self.probe("queue", "queue:orders")
        self.assertEqual(result.returncode, 0, output(result))
        queue = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(queue), [], queue)
        self.assertEqual((queue["adapter"], queue["capability"], queue["verb"], queue["status"]),
                         ("aws-messaging", "messaging", "queue", "ok"))
        self.assertEqual(len(queue["items"]), 1, queue)
        item = queue["items"][0]
        self.assertEqual({k: item.get(k) for k in ("visible", "in_flight", "oldest_age_seconds", "dlq_visible",
                                                    "redrive_matches_dlq", "dlq")},
                         {"visible": 12, "in_flight": 3, "oldest_age_seconds": 42, "dlq_visible": 2,
                          "redrive_matches_dlq": True, "dlq": "queue:orders-dlq"})
        result2 = self.probe("subscriptions", f"topic:{TOPIC}")
        self.assertEqual(result2.returncode, 0, output(result2))
        subs = json.loads(result2.stdout)
        self.assertEqual(f("validate_probe_output")(subs), [], subs)
        self.assertEqual(len(subs["items"]), 5, subs)
        self.assertEqual(sorted(i["destination"] for i in subs["items"]),
                         sorted(["queue:orders", "function:notify", "https:[REDACTED]", "https:[REDACTED]",
                                 "email:[REDACTED]"]))
        self.assertEqual(subs.get("message"), "5 assinaturas, 1 pendentes")
        calls = read_calls(self.record)
        self.assertTrue(calls, "a aws falsa não foi chamada")
        for argv in calls:
            self.assertEqual(call_problems(argv, REGION, PROFILE), [], argv)
        log_text = self.log_path.read_text(encoding="utf-8") if self.log_path.exists() else ""
        everything = output(result) + output(result2) + log_text
        for value in (PROFILE, ACCOUNT):
            self.assertNotIn(value, everything, f"{value} apareceu na saída ou no probes.log")
        lines = self.log()
        self.assertEqual([(line.get("resource"), line.get("status"), line.get("adapter")) for line in lines],
                         [("queue:orders", "ok", "aws-messaging"), (f"topic:{TOPIC}", "ok", "aws-messaging")])

    def test_expired_login_exits_1_and_is_logged_without_the_profile(self):
        """SPEC-0098:IT-02 — a AWS CLI falsa responde SSO expirado: exit 1, status error com "renove o login da
        nuvem", probes.log com status error e sem o profile."""
        # SPEC-0098:IT-02
        scenario = base_scenario()
        scenario["fail"] = [{"mode": "sso-expired"}]
        self.install(scenario)
        result = self.probe("queue", "queue:orders")
        self.assertEqual(result.returncode, 1, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "error", data)
        self.assertIn("renove o login da nuvem", data.get("message", ""))
        self.assertNotIn(PROFILE, output(result))
        lines = self.log()
        self.assertEqual(len(lines), 1, lines)
        self.assertEqual((lines[0].get("status"), lines[0].get("resource")), ("error", "queue:orders"))
        self.assertNotIn(PROFILE, self.log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
