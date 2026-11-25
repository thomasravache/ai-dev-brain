"""Coletor aws da boson-atlas (SPEC-0097: CH-01, UT-01 a UT-07, IT-01, IT-02 e CT-01).

Contrato esperado de assets/collectors/aws.py (o Implementer segue estes testes e a seção 6 da spec):

    aws.py --services <rds,elasticache | sqs,sns> --region <r1,r2,...> [--max-items N (1 a 10000, padrão 1000)]
        stdout: um objeto boson-atlas/collector@1 com collector "aws", category "data" (rds, elasticache) ou
        "messaging" (sqs, sns), source "aws" em tudo; entidades ordenadas por kind:id e relações por
        from/type/to; exit 0. datastore {type, engine, host, port (int), reader_host (quando há), region,
        serverless}; queue {type "sqs", fifo, region, dlq (id de outra queue da saída), filtered_topics};
        topic {type "sns", fifo, region}; topic -> queue "publishes" por assinatura SQS confirmada.
        Exit 2 (argumentos) e exit 1 (AWS CLI) com as mensagens fixas da seção 6, prefixo "aws: ", nunca o
        stderr da CLI, o profile, URL, ARN nem conta.
        ATLAS_COLLECTOR_PROFILE -> AWS_PROFILE no ambiente da AWS CLI, sem AWS_ACCESS_KEY_ID,
        AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN nem AWS_DEFAULT_PROFILE.

    Função (importada pelo caminho no UT-03):
    build_call(service: str, operation: str, region: str, max_items: int = 1000, extra=()) -> list[str]
        argv da chamada à AWS CLI, montado da tabela fechada: ["aws", <serviço>, <operação>, ..., "--region", r,
        "--output", "json", "--no-cli-pager", "--cli-connect-timeout", "10", "--cli-read-timeout", "30"], com
        "--max-items N" nas listas, "--show-cache-node-info" no describe-cache-clusters e `extra` só com os
        argumentos permitidos daquela operação (--queue-url + --attribute-names RedrivePolicy;
        --subscription-arn). Fora da tabela -> exceção cuja mensagem contém "chamada não permitida", sem
        executar nada.

    scripts/atlas.py (scan): o coletor <id> recebe ATLAS_COLLECTOR_PROFILE=<credentials.<id>.profile> quando
    definido; uma ATLAS_COLLECTOR_PROFILE herdada do shell nunca chega a coletor nenhum.

Dublês: fixtures/aws/fake_aws.py (copiado como `aws` no início do PATH; ver o docstring), as respostas gravadas
em fixtures/aws/responses/<cenário>/<região>/, o coletor espião fixtures/aws/env_spy.py e as Applications do
argocd em fixtures/aws/argocd-apps.json. Nenhuma AWS CLI real, rede ou ~/.aws real.
"""
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
from unittest import mock

from helpers import SKILL, TESTS, Sandbox, fn, output

SPEC = "SPEC-0097"
CONTRACT = "boson-atlas/collector@1"
AWS_PY = SKILL / "assets" / "collectors" / "aws.py"
FIXTURES = TESTS / "fixtures" / "aws"
RESPONSES = FIXTURES / "responses"
FAKE_AWS = FIXTURES / "fake_aws.py"
ARGOCD_APPS = FIXTURES / "argocd-apps.json"
CONTRACT_VALID = TESTS / "fixtures" / "contract" / "valid"
AWS_REFERENCE = SKILL / "references" / "collectors" / "aws.md"
CONTRACT_REFERENCE = SKILL / "references" / "collector-contract.md"
SKILL_MARK = "{skill}"
SPY = SKILL_MARK + "/tests/fixtures/aws/env_spy.py"
COLLECTED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ACCOUNT = "123456789012"
OTHER_ACCOUNT = "111122223333"
PROFILE = "acme-prod-readonly"
US = "us-east-1"
SA = "sa-east-1"
STATIC_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_DEFAULT_PROFILE")
# variáveis da máquina que nunca chegam aos testes (nenhuma AWS real)
SCRUB = ("AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE",
         "ATLAS_COLLECTOR_PROFILE", "FAKE_AWS_MODE", "FAKE_AWS_LOG", "FAKE_AWS_RESPONSES", *STATIC_KEYS)
COMMON = {"--region": None, "--output": "json", "--no-cli-pager": True, "--cli-connect-timeout": "10",
          "--cli-read-timeout": "30"}
LIST_OPERATIONS = {("rds", "describe-db-clusters"), ("rds", "describe-db-instances"),
                   ("elasticache", "describe-replication-groups"), ("elasticache", "describe-cache-clusters"),
                   ("elasticache", "describe-serverless-caches"), ("sqs", "list-queues"), ("sns", "list-topics"),
                   ("sns", "list-subscriptions")}
GET_OPERATIONS = {("sqs", "get-queue-attributes"), ("sns", "get-subscription-attributes")}
FLAGS = {"--no-cli-pager", "--show-cache-node-info"}

# mensagens fixas da seção 6
MSG_SERVICES = "--services precisa de rds, elasticache, sqs ou sns"
MSG_MIXED = "misture serviços de dados (rds, elasticache) e de mensageria (sqs, sns) em coletores separados"
MSG_REGION = "--region precisa de 1 a 10 regiões válidas, sem repetição"
MSG_MAX_ITEMS = "--max-items precisa ser um inteiro de 1 a 10000"
MSG_NO_CLI = "AWS CLI não encontrada no PATH"
MSG_LOGIN = "login da nuvem expirado — renove o login da nuvem"
MSG_NO_CREDENTIALS = "sem credencial da AWS — declare o profile em credentials do coletor"
MSG_PROFILE = re.compile(r"^aws: profile da AWS não encontrado — confira credentials\.\S+\.profile$")
NOT_ALLOWED = "chamada não permitida"
IGNORED_LINE = re.compile(r"^aws: \d+ recurso\(s\) ignorado\(s\): 12 dígitos seguidos$")
REPEATED_LINE = re.compile(r"^aws: \d+ recurso\(s\) repetido\(s\) em outra região ignorado\(s\)$")

DATA_ATTRS = {
    "orders-db": {"type": "rds", "engine": "aurora-postgresql",
                  "host": "orders-db.cluster-abc123.us-east-1.rds.amazonaws.com", "port": 5432,
                  "reader_host": "orders-db.cluster-ro-abc123.us-east-1.rds.amazonaws.com", "region": US,
                  "serverless": True},
    "billing-db": {"type": "rds", "engine": "postgres", "host": "billing-db.abc123.us-east-1.rds.amazonaws.com",
                   "port": 5432, "region": US, "serverless": False},
    "orders-cache": {"type": "elasticache", "engine": "valkey",
                     "host": "orders-cache.abc123.ng.0001.use1.cache.amazonaws.com", "port": 6379,
                     "reader_host": "orders-cache-ro.abc123.ng.0001.use1.cache.amazonaws.com", "region": US,
                     "serverless": False},
    "sessions": {"type": "elasticache", "engine": "redis",
                 "host": "sessions.abc123.clustercfg.use1.cache.amazonaws.com", "port": 6379, "region": US,
                 "serverless": False},
    "catalog-mc": {"type": "elasticache", "engine": "memcached",
                   "host": "catalog-mc.abc123.cfg.use1.cache.amazonaws.com", "port": 11211, "region": US,
                   "serverless": False},
    "rates-cache": {"type": "elasticache", "engine": "valkey",
                    "host": "rates-cache-abc123.serverless.use1.cache.amazonaws.com", "port": 6379,
                    "reader_host": "rates-cache-abc123.serverless.use1.cache.amazonaws.com", "region": US,
                    "serverless": True},
}
QUEUE_ATTRS = {
    "orders": {"type": "sqs", "fifo": False, "region": US, "dlq": "orders-dlq", "filtered_topics": ["order-events"]},
    "orders-dlq": {"type": "sqs", "fifo": False, "region": US},
    "refunds": {"type": "sqs", "fifo": False, "region": US},
    "payments.fifo": {"type": "sqs", "fifo": True, "region": US},
}
TOPIC_ATTRS = {
    "order-events": {"type": "sns", "fifo": False, "region": US},
    "payments.fifo": {"type": "sns", "fifo": True, "region": US},
}
MESSAGING_RELATIONS = [
    {"from": "topic:order-events", "to": "queue:audit", "type": "publishes", "source": "aws"},
    {"from": "topic:order-events", "to": "queue:orders", "type": "publishes", "source": "aws"},
    {"from": "topic:payments.fifo", "to": "queue:payments.fifo", "type": "publishes", "source": "aws"},
]

_CACHE = {}


def collector():
    """assets/collectors/aws.py importado pelo caminho (sem sys.path)."""
    if "module" not in _CACHE:
        if not AWS_PY.exists():
            raise AssertionError(f"{AWS_PY} não existe ({SPEC})")
        spec = importlib.util.spec_from_file_location("boson_atlas_collector_aws", AWS_PY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CACHE["module"] = module
    return _CACHE["module"]


def function(name):
    f = getattr(collector(), name, None)
    if f is None:
        raise AssertionError(f"aws.{name} não existe ({SPEC})")
    return f


def entity(kind, eid, attrs):
    return {"kind": kind, "id": eid, "name": eid, "attrs": attrs, "source": "aws"}


def entity_key(item):
    return f"{item['kind']}:{item['id']}"


def make_bin(with_aws=True):
    """Pasta temporária com o dublê copiado como `aws`, executável (ou vazia, sem aws)."""
    folder = Path(tempfile.mkdtemp()).resolve()
    if with_aws:
        target = folder / "aws"
        shutil.copyfile(FAKE_AWS, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return folder


def parse_call(argv):
    """(serviço, operação, {opção: valor | True}) de um argv registrado pelo dublê (sem o executável)."""
    positional, options, i = [], {}, 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("--"):
            if arg in FLAGS:
                options[arg] = True
                i += 1
            else:
                options[arg] = argv[i + 1] if i + 1 < len(argv) else None
                i += 2
        else:
            positional.append(arg)
            i += 1
    return tuple(positional[:2]), positional[2:], options


def fixture(scenario, region, name):
    path = RESPONSES / scenario / region / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def clean_environ():
    return {k: v for k, v in os.environ.items() if k not in SCRUB}


class AwsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = self.tmp / "aws-calls.jsonl"

    def run_aws(self, *args, scenario="acme", mode=None, env=None, with_aws=True):
        folder = make_bin(with_aws)
        self.addCleanup(shutil.rmtree, folder, True)
        environ = clean_environ()
        environ.update(HOME=str(self.tmp), FAKE_AWS_LOG=str(self.log), FAKE_AWS_RESPONSES=str(RESPONSES / scenario),
                       AWS_CONFIG_FILE=str(self.tmp / "no-aws-config"),
                       AWS_SHARED_CREDENTIALS_FILE=str(self.tmp / "no-aws-credentials"))
        environ["PATH"] = str(folder) + (os.pathsep + os.environ.get("PATH", "") if with_aws else "")
        if mode:
            environ["FAKE_AWS_MODE"] = mode
        environ.update(env or {})
        if not AWS_PY.exists():
            self.fail(f"{AWS_PY} não existe ({SPEC})")
        result = subprocess.run([sys.executable, str(AWS_PY), *args], capture_output=True, text=True, env=environ,
                                cwd=self.tmp, timeout=120, check=False)
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        return result

    def calls(self):
        if not self.log.is_file():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def collect(self, *args, **kw):
        result = self.run_aws(*args, **kw)
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        return data, result

    def assertHeader(self, data, category):
        self.assertEqual(data.get("contract"), CONTRACT)
        self.assertEqual(data.get("collector"), "aws")
        self.assertEqual(data.get("category"), category)
        self.assertRegex(data.get("collected_at", ""), COLLECTED_AT)
        for item in data["entities"] + data["relations"]:
            self.assertEqual(item.get("source"), "aws", item)

    def assertSorted(self, data):
        keys = [entity_key(e) for e in data["entities"]]
        self.assertEqual(keys, sorted(keys), "entidades fora da ordem kind:id")
        rels = [(r["from"], r["type"], r["to"]) for r in data["relations"]]
        self.assertEqual(rels, sorted(rels), "relações fora da ordem from/type/to")


# --------------------------------------------------------------------------- UT-01 e UT-02: saída


class DataStoresTest(AwsCase):
    def test_rds_and_elasticache_become_datastores(self):
        """SPEC-0097:UT-01 — Aurora serverless com membros, RDS avulso (porta em texto), grupo Valkey sem Engine,
        grupo em cluster mode, Memcached avulso e cache serverless viram exatamente seis datastore."""
        # SPEC-0097:UT-01
        data, result = self.collect("--services", "rds,elasticache", "--region", US)
        self.assertHeader(data, "data")
        self.assertSorted(data)
        self.assertEqual(data["relations"], [])
        got = {e["id"]: e for e in data["entities"]}
        self.assertEqual(sorted(got), sorted(DATA_ATTRS), "membros de cluster não viram entidade")
        for eid, attrs in DATA_ATTRS.items():
            with self.subTest(datastore=eid):
                self.assertEqual(got[eid], entity("datastore", eid, attrs))
                self.assertIsInstance(got[eid]["attrs"]["port"], int)
                self.assertNotIn("migrations_table", got[eid]["attrs"])
        for member in ("orders-db-1", "orders-db-2", "orders-cache-001", "sessions-0001-001"):
            self.assertNotIn(member, result.stdout)

    def test_instance_without_endpoint_has_no_host_nor_port(self):
        """SPEC-0097:UT-01 — uma instância criando (sem Endpoint) sai sem host e sem port."""
        # SPEC-0097:UT-01
        data, _ = self.collect("--services", "rds", "--region", US, scenario="creating")
        self.assertHeader(data, "data")
        self.assertEqual(data["entities"], [entity("datastore", "ledger-db",
                                                   {"type": "rds", "engine": "postgres", "region": US,
                                                    "serverless": False})])


class MessagingTest(AwsCase):
    def test_queues_topics_and_subscriptions(self):
        """SPEC-0097:UT-02 — redrive (DLQ no snapshot e de outra conta), FIFO, assinatura com e sem filtro,
        pendente, HTTP e de fila de outra região."""
        # SPEC-0097:UT-02
        data, result = self.collect("--services", "sqs,sns", "--region", US)
        self.assertHeader(data, "messaging")
        self.assertSorted(data)
        queues = {e["id"]: e for e in data["entities"] if e["kind"] == "queue"}
        topics = {e["id"]: e for e in data["entities"] if e["kind"] == "topic"}
        self.assertEqual({e["kind"] for e in data["entities"]}, {"queue", "topic"})
        self.assertEqual(sorted(queues), sorted(QUEUE_ATTRS))
        self.assertEqual(sorted(topics), sorted(TOPIC_ATTRS))
        for qid, attrs in QUEUE_ATTRS.items():
            with self.subTest(queue=qid):
                self.assertEqual(queues[qid], entity("queue", qid, attrs))
        for tid, attrs in TOPIC_ATTRS.items():
            with self.subTest(topic=tid):
                self.assertEqual(topics[tid], entity("topic", tid, attrs))
        self.assertIn(queues["orders"]["attrs"]["dlq"], queues, "dlq é o id de outra fila da mesma saída")
        self.assertEqual(sorted(data["relations"], key=lambda r: (r["from"], r["type"], r["to"])),
                         MESSAGING_RELATIONS)
        # refunds-dlq (outra conta): atributo omitido e stderr só com a contagem
        lines = [line for line in result.stderr.splitlines() if line.strip()]
        self.assertTrue(lines, "a DLQ fora do snapshot (e a assinatura pendente) aparecem como contagem no stderr")
        for line in lines:
            self.assertRegex(line, r"^aws: \d+ ")
            for leak in ("refunds", "arn:", "https://", ACCOUNT, OTHER_ACCOUNT, "PendingConfirmation", "hooks"):
                self.assertNotIn(leak, line)


# --------------------------------------------------------------------------- UT-03: lista fechada


class ClosedListTest(AwsCase):
    def check_calls(self, scenario, max_items="1000"):
        calls = self.calls()
        self.assertTrue(calls, "o dublê não registrou chamada nenhuma")
        listed_urls, confirmed_arns, list_counts = {}, {}, {}
        for index, call in enumerate(calls):
            (service, operation), extra_positional, options = parse_call(call["argv"])
            with self.subTest(call=call["argv"]):
                self.assertEqual(extra_positional, [], "argumento posicional fora da tabela")
                self.assertIn((service, operation), LIST_OPERATIONS | GET_OPERATIONS, "operação fora da tabela")
                region = options.get("--region")
                expected = dict(COMMON, **{"--region": region})
                self.assertIn(region, (US, SA))
                if (service, operation) in LIST_OPERATIONS:
                    expected["--max-items"] = max_items
                    if operation == "describe-cache-clusters":
                        expected["--show-cache-node-info"] = True
                    list_counts[(service, operation, region)] = list_counts.get((service, operation, region), 0) + 1
                    if (service, operation) == ("sqs", "list-queues"):
                        data = fixture(scenario, region, "sqs-list-queues.json")
                        listed_urls.setdefault(region, set()).update(data.get("QueueUrls", []))
                    if (service, operation) == ("sns", "list-subscriptions"):
                        data = fixture(scenario, region, "sns-list-subscriptions.json")
                        confirmed_arns.setdefault(region, set()).update(
                            s["SubscriptionArn"] for s in data.get("Subscriptions", [])
                            if s["Protocol"] == "sqs" and s["SubscriptionArn"] != "PendingConfirmation")
                elif operation == "get-queue-attributes":
                    expected["--queue-url"] = options.get("--queue-url")
                    expected["--attribute-names"] = "RedrivePolicy"
                    self.assertIn(options.get("--queue-url"), listed_urls.get(region, set()),
                                  "a URL veio da resposta do list-queues anterior")
                else:
                    expected["--subscription-arn"] = options.get("--subscription-arn")
                    self.assertIn(options.get("--subscription-arn"), confirmed_arns.get(region, set()),
                                  "o ARN veio de uma assinatura SQS confirmada do list-subscriptions anterior")
                self.assertEqual(options, expected)
        self.assertTrue(all(count == 1 for count in list_counts.values()),
                        f"uma chamada de lista por operação e região: {list_counts}")
        return calls

    def test_every_call_is_in_the_closed_table(self):
        """SPEC-0097:UT-03 — todo argv dos cenários de UT-01 e UT-02 bate com a tabela de chamadas permitidas."""
        # SPEC-0097:UT-03
        self.collect("--services", "rds,elasticache", "--region", US)
        self.check_calls("acme")
        self.log.unlink()
        self.collect("--services", "sqs,sns", "--region", US)
        calls = self.check_calls("acme")
        operations = [tuple(parse_call(c["argv"])[0]) for c in calls]
        self.assertEqual(operations.count(("sqs", "get-queue-attributes")), 4, "um por fila")
        self.assertEqual(operations.count(("sns", "get-subscription-attributes")), 3,
                         "um por assinatura SQS confirmada")

    def test_build_call_refuses_anything_outside_the_table(self):
        """SPEC-0097:UT-03 — build_call recusa receive-message, purge-queue, publish, delete-db-instance e
        --attribute-names All com "chamada não permitida", sem executar nada; o coletor não usa shell=True."""
        # SPEC-0097:UT-03
        build_call = function("build_call")
        url = f"https://sqs.{US}.amazonaws.com/{ACCOUNT}/orders"
        refused = [("sqs", "receive-message", ()), ("sqs", "purge-queue", ()), ("sns", "publish", ()),
                   ("rds", "delete-db-instance", ()),
                   ("sqs", "get-queue-attributes", ("--queue-url", url, "--attribute-names", "All"))]
        with mock.patch("subprocess.run", side_effect=AssertionError("executou")) as run, \
                mock.patch("subprocess.Popen", side_effect=AssertionError("executou")) as popen:
            for service, operation, extra in refused:
                with self.subTest(call=(service, operation, extra)):
                    with self.assertRaises(BaseException) as caught:
                        build_call(service, operation, US, extra=extra)
                    self.assertIn(NOT_ALLOWED, str(caught.exception))
            argv = build_call("sqs", "get-queue-attributes", US,
                              extra=("--queue-url", url, "--attribute-names", "RedrivePolicy"))
            listing = build_call("rds", "describe-db-instances", US, max_items=7)
        self.assertEqual(run.call_count + popen.call_count, 0)
        self.assertEqual(argv[:3], ["aws", "sqs", "get-queue-attributes"])
        self.assertEqual(parse_call(argv[1:])[2], dict(COMMON, **{"--region": US, "--queue-url": url,
                                                                  "--attribute-names": "RedrivePolicy"}))
        self.assertEqual(listing[:3], ["aws", "rds", "describe-db-instances"])
        self.assertEqual(parse_call(listing[1:])[2], dict(COMMON, **{"--region": US, "--max-items": "7"}))
        source = AWS_PY.read_text(encoding="utf-8")
        for forbidden in ("shell=True", "os.system", "os.popen"):
            self.assertNotIn(forbidden, source)


# --------------------------------------------------------------------------- UT-04: erros da AWS CLI


class CliErrorsTest(AwsCase):
    LEAKS = (PROFILE, ACCOUNT, "https://", "arn:", "Unable to locate", "Token has expired", "ExpiredToken",
             "could not be found", "AccessDenied", "Read timeout", "something odd", "broken", "Traceback")

    def assertFixedError(self, result, expected):
        self.assertEqual(result.returncode, 1, output(result))
        self.assertEqual(result.stdout, "", "stdout fica vazio")
        message = result.stderr.strip()
        if isinstance(expected, re.Pattern):
            self.assertRegex(message, expected)
        else:
            self.assertEqual(message, f"aws: {expected}")
        for leak in self.LEAKS:
            self.assertNotIn(leak, result.stderr)

    def test_each_cli_error_becomes_a_fixed_message(self):
        """SPEC-0097:UT-04 — sem credencial, SSO expirado, token expirado, profile inexistente, AccessDenied,
        tempo esgotado, JSON inválido e código 255: exit 1 com a mensagem fixa, sem o texto do dublê."""
        # SPEC-0097:UT-04
        op = "elasticache:describe-serverless-caches"
        cases = [
            ("no-credentials", ("sqs,sns",), MSG_NO_CREDENTIALS),
            ("sso-expired", ("sqs,sns",), MSG_LOGIN),
            ("token-expired", ("sqs,sns",), MSG_LOGIN),
            ("profile-not-found", ("sqs,sns",), MSG_PROFILE),
            (f"denied:{op}", ("rds,elasticache",), f"sem permissão para elasticache describe-serverless-caches em {US}"),
            (f"slow:{op}", ("rds,elasticache",), f"tempo esgotado em elasticache describe-serverless-caches ({US})"),
            (f"invalid-json:{op}", ("rds,elasticache",),
             "resposta inválida da AWS CLI em elasticache describe-serverless-caches"),
            (f"fail:{op}", ("rds,elasticache",), f"falha da AWS CLI em elasticache describe-serverless-caches ({US})"),
        ]
        for mode, (services,), expected in cases:
            with self.subTest(mode=mode):
                result = self.run_aws("--services", services, "--region", US, mode=mode,
                                      env={"ATLAS_COLLECTOR_PROFILE": PROFILE})
                self.assertFixedError(result, expected)

    def test_missing_cli(self):
        """SPEC-0097:UT-04 — PATH sem aws: exit 1, "AWS CLI não encontrada no PATH"."""
        # SPEC-0097:UT-04
        result = self.run_aws("--services", "sqs,sns", "--region", US, with_aws=False)
        self.assertFixedError(result, MSG_NO_CLI)


# --------------------------------------------------------------------------- UT-05: limite e argumentos


class LimitsAndArgumentsTest(AwsCase):
    def test_next_token_fails_instead_of_a_partial_snapshot(self):
        """SPEC-0097:UT-05 — NextToken em sqs list-queues com --max-items 2: exit 1 com a mensagem do limite."""
        # SPEC-0097:UT-05
        result = self.run_aws("--services", "sqs", "--region", US, "--max-items", "2",
                              mode="next-token:sqs:list-queues")
        self.assertEqual(result.returncode, 1, output(result))
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(),
                         f"aws: limite de 2 itens atingido em sqs list-queues ({US}) — aumente --max-items")
        lists = [parse_call(c["argv"]) for c in self.calls()]
        lists = [opts for (pair, _, opts) in lists if pair in LIST_OPERATIONS]
        self.assertTrue(lists)
        self.assertTrue(all(opts.get("--max-items") == "2" for opts in lists))

    def test_max_items_reaches_every_list_call(self):
        """SPEC-0097:UT-05 — --max-items N chega a toda chamada de lista."""
        # SPEC-0097:UT-05
        self.collect("--services", "rds,elasticache", "--region", US, "--max-items", "50")
        lists = [opts for (pair, _, opts) in map(lambda c: parse_call(c["argv"]), self.calls())
                 if pair in LIST_OPERATIONS]
        self.assertEqual(len(lists), 5)
        self.assertTrue(all(opts.get("--max-items") == "50" for opts in lists))

    def test_invalid_arguments_exit_2_without_calling_the_cli(self):
        """SPEC-0097:UT-05 — serviço desconhecido, categorias misturadas, região repetida ou inválida e --max-items
        fora da faixa: exit 2 com a mensagem fixa, sem nenhuma chamada registrada."""
        # SPEC-0097:UT-05
        cases = [
            (("--services", "s3", "--region", US), MSG_SERVICES),
            (("--services", "rds,sqs", "--region", US), MSG_MIXED),
            (("--services", "sqs", "--region", f"{US},{US}"), MSG_REGION),
            (("--services", "sqs", "--region", "Brasil"), MSG_REGION),
            (("--services", "sqs", "--region", US, "--max-items", "0"), MSG_MAX_ITEMS),
            (("--services", "sqs", "--region", US, "--max-items", "10001"), MSG_MAX_ITEMS),
        ]
        for args, message in cases:
            with self.subTest(args=args):
                result = self.run_aws(*args)
                self.assertEqual(result.returncode, 2, output(result))
                self.assertEqual(result.stdout, "")
                self.assertIn(message, result.stderr)
                self.assertEqual(self.calls(), [], "a AWS CLI não pode ser chamada")


# --------------------------------------------------------------------------- UT-06: conta e dados sensíveis


class SensitiveDataTest(AwsCase):
    def test_accounts_arns_urls_and_filters_never_leave(self):
        """SPEC-0097:UT-06 — ARNs, URLs, Owner, FilterPolicy e Policy nas respostas; fila com 12 dígitos e fila
        repetida em sa-east-1."""
        # SPEC-0097:UT-06
        data, result = self.collect("--services", "sqs,sns", "--region", f"{US},{SA}", scenario="sensitive")
        for leak in (ACCOUNT, "arn:", "https://", "customer_tier", "Owner"):
            self.assertNotIn(leak, result.stdout)
        keys = {entity_key(e): e for e in data["entities"]}
        self.assertNotIn("queue:report-202411241200", keys)
        self.assertNotIn("202411241200", result.stdout)
        self.assertEqual(keys["queue:orders"]["attrs"]["region"], US, "fica o da primeira região de --region")
        self.assertEqual(keys["topic:order-events"]["attrs"]["region"], US)
        self.assertEqual(keys["queue:orders"]["attrs"].get("filtered_topics"), ["order-events"])
        lines = [line for line in result.stderr.splitlines() if line.strip()]
        self.assertTrue(any(IGNORED_LINE.match(line) for line in lines), result.stderr)
        self.assertTrue(any(REPEATED_LINE.match(line) for line in lines), result.stderr)
        for line in lines:
            self.assertRegex(line, r"^aws: \d+ ", "stderr só com contagens")
            for leak in ("orders", "report", ACCOUNT, "arn:", "https://", SA):
                self.assertNotIn(leak, line)


# --------------------------------------------------------------------------- UT-07 e CH-01: profile por coletor


def atlas_config(collectors, categories="[code, delivery, data, messaging]"):
    """atlas-config.yml com os coletores [(id, category, command)]."""
    lines = ["version: 1", "organization: Acme", "mode: repo", "language: auto", "stale_days: 14",
             f"categories: {categories}", "collectors:"]
    for cid, category, command in collectors:
        lines += [f"  - id: {cid}", f"    category: {category}",
                  "    command: [" + ", ".join(json.dumps(a) for a in command) + "]", "    timeout: 120"]
    lines.append("redaction: {extra_patterns: []}")
    return "\n".join(lines) + "\n"


def aws_command(services, regions=US):
    return ["python3", SKILL_MARK + "/assets/collectors/aws.py", "--services", services, "--region", regions]


class ScanAtlasCase(unittest.TestCase):
    """Atlas criado pelo init real num Sandbox (HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários), com o dublê
    da AWS CLI no início do PATH."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.box.new_atlas()
        self.atlas = self.box.atlas
        self.snapshots = self.atlas / "snapshots"
        self.bin = make_bin()
        self.addCleanup(shutil.rmtree, self.bin, True)
        self.log = self.box.root / "aws-calls.jsonl"

    def configure(self, collectors, credentials=None):
        (self.atlas / "atlas-config.yml").write_text(atlas_config(collectors), encoding="utf-8")
        local = self.box.config_home / "config.yml"
        text = local.read_text(encoding="utf-8")
        block = "credentials:\n" + "".join(f"  {cid}: {entry}\n" for cid, entry in (credentials or {}).items())
        if credentials:
            text = text.replace("credentials: {}\n", block)
            self.assertIn(block, text, "fixture: não consegui declarar as credenciais na configuração local")
            local.write_text(text, encoding="utf-8")

    def scan_env(self, mode=None, extra=None):
        env = {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""), "FAKE_AWS_LOG": str(self.log),
               "FAKE_AWS_RESPONSES": str(RESPONSES / "acme"),
               "AWS_CONFIG_FILE": str(self.box.root / "no-aws-config"),
               "AWS_SHARED_CREDENTIALS_FILE": str(self.box.root / "no-aws-credentials")}
        if mode:
            env["FAKE_AWS_MODE"] = mode
        env.update(extra or {})
        return env

    def scan(self, *args, mode=None, extra=None, unset=SCRUB):
        env = self.scan_env(mode, extra)
        result = self.box.run("scan", *args, env=env, unset=tuple(name for name in unset if name not in env))
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def aws_calls(self):
        if not self.log.is_file():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def atlas_files_text(self):
        return {p.relative_to(self.atlas).as_posix(): p.read_text(encoding="utf-8", errors="replace")
                for p in self.atlas.rglob("*") if p.is_file() and ".git" not in p.parts}


class ProfileCharacterizationTest(ScanAtlasCase):
    def test_collector_environment_without_profile_is_unchanged(self):
        """SPEC-0097:CH-01 — sem credentials.<id>.profile, o coletor recebe o ambiente do scan (o isolamento entre
        atlas continua) e nenhuma ATLAS_COLLECTOR_PROFILE (guarda: passa antes da mudança)."""
        # SPEC-0097:CH-01
        seen = self.box.root / "spy-env.json"
        # {atlas} = <raiz>/work/acme-atlas, logo {atlas}/../../spy-env.json = <raiz>/spy-env.json
        self.configure([("spy", "code", ["python3", SPY, "{atlas}/../../spy-env.json", "spy"])])
        env = self.scan_env(extra={"ATLAS_SPY_TOKEN_0097": "x"})
        result = self.box.run("scan", env=env, unset=tuple(name for name in SCRUB if name not in env))
        self.assertEqual(result.returncode, 0, output(result))
        got = json.loads(seen.read_text(encoding="utf-8"))
        self.assertIsNone(got["profile"])
        self.assertNotIn("ATLAS_COLLECTOR_PROFILE", got["names"])
        expected = {k for k in os.environ if k not in SCRUB} | set(env) | {"HOME", "XDG_CONFIG_HOME",
                                                                          "ATLAS_CONFIG_HOME"}
        # o próprio Python/SO pode acrescentar variáveis ao processo filho (ex.: __CF_USER_TEXT_ENCODING, PWD)
        added = set(got["names"]) - expected
        self.assertTrue(all(name.startswith("__") or name in ("PWD", "OLDPWD", "SHLVL", "_", "LC_CTYPE")
                            for name in added), f"variáveis novas no ambiente do coletor: {sorted(added)}")
        self.assertEqual(expected - set(got["names"]), set(), "o coletor perdeu variáveis do ambiente do scan")


class ProfilePerCollectorTest(ScanAtlasCase):
    def test_only_the_declared_collector_gets_the_profile(self):
        """SPEC-0097:UT-07 — credentials.aws-messaging.profile, um segundo coletor sem profile e
        ATLAS_COLLECTOR_PROFILE e chaves estáticas no shell."""
        # SPEC-0097:UT-07
        self.configure([("aws-messaging", "messaging", aws_command("sqs,sns")),
                        ("spy", "code", ["python3", SPY, "{atlas}/../../spy-env.json", "spy"])],
                       credentials={"aws-messaging": f"{{profile: {PROFILE}}}"})
        shell = {"ATLAS_COLLECTOR_PROFILE": "shell-inherited-profile", "AWS_ACCESS_KEY_ID": "AKIA" + "FAKE0097" * 2,
                 "AWS_SECRET_ACCESS_KEY": "fake-secret-0097", "AWS_SESSION_TOKEN": "fake-session-0097",
                 "AWS_DEFAULT_PROFILE": "shell-default-profile"}
        result = self.scan(extra=shell)
        self.assertEqual(result.returncode, 0, output(result))
        spy = json.loads((self.box.root / "spy-env.json").read_text(encoding="utf-8"))
        self.assertIsNone(spy["profile"], "o coletor sem profile não recebe a variável herdada do shell")
        self.assertNotIn("ATLAS_COLLECTOR_PROFILE", spy["names"])
        calls = self.aws_calls()
        self.assertTrue(calls, "o coletor aws não chamou a AWS CLI")
        for call in calls:
            self.assertEqual(call["aws_profile"], PROFILE, "a AWS CLI recebe AWS_PROFILE com o nome declarado")
            for name in STATIC_KEYS:
                self.assertNotIn(name, call["env"])
        self.assertNotIn(PROFILE, output(result))
        self.assertNotIn("shell-inherited-profile", output(result))
        for rel, text in self.atlas_files_text().items():
            if rel.startswith("snapshots/") or rel == "graph.json":
                self.assertNotIn(PROFILE, text, rel)


# --------------------------------------------------------------------------- IT-01 e IT-02: ponta a ponta


class EndToEndTest(ScanAtlasCase):
    def configure_all(self):
        self.configure([("aws-data", "data", aws_command("rds,elasticache")),
                        ("aws-messaging", "messaging", aws_command("sqs,sns")),
                        ("argocd", "delivery", ["python3", SKILL_MARK + "/assets/collectors/argocd.py", "--from",
                                                "kubectl", "--input",
                                                SKILL_MARK + "/tests/fixtures/aws/argocd-apps.json"])],
                       credentials={"aws-data": f"{{profile: {PROFILE}}}",
                                    "aws-messaging": f"{{profile: {PROFILE}}}"})

    def first_scan(self):
        self.configure_all()
        result = self.scan("--json")
        self.assertEqual(result.returncode, 0, output(result))
        return result

    def test_scan_and_build_link_services_to_aws_resources(self):
        """SPEC-0097:IT-01 — scan com aws-data, aws-messaging e argocd (--input): snapshots válidos, depends_on
        inferidas para fila, tópico e banco, publishes do tópico para a fila, nenhuma conta no atlas."""
        # SPEC-0097:IT-01
        self.first_scan()
        validate = fn("validate_collector_output", SPEC)
        for cid in ("aws-data", "aws-messaging"):
            with self.subTest(snapshot=cid):
                data = json.loads((self.snapshots / f"{cid}.json").read_text(encoding="utf-8"))
                _, violations, dropped = validate(data)
                self.assertEqual((violations, dropped), ([], []))
        graph = json.loads((self.atlas / "graph.json").read_text(encoding="utf-8"))
        edges = {(e["from"], e["type"], e["to"]): e for e in graph["edges"]}
        expected = {"queue:orders": "ORDERS_QUEUE_URL=orders", "topic:order-events": "ORDER_EVENTS_TOPIC=order-events",
                    "datastore:orders-db": "DB_HOST=orders-db.cluster-abc123.us-east-1.rds.amazonaws.com"}
        for target, evidence in expected.items():
            with self.subTest(depends_on=target):
                edge = edges.get(("service:api", "depends_on", target))
                self.assertIsNotNone(edge, f"falta service:api depends_on {target}")
                self.assertTrue(edge.get("inferred"))
                self.assertEqual(edge.get("evidence"), evidence)
        self.assertIn(("topic:order-events", "publishes", "queue:orders"), edges)
        for rel, text in self.atlas_files_text().items():
            with self.subTest(file=rel):
                for leak in (ACCOUNT, "arn:", PROFILE):
                    self.assertNotIn(leak, text)

    def test_isolated_failure_keeps_previous_snapshot(self):
        """SPEC-0097:IT-02 — depois do IT-01, SSO expirado só no sqs: FALHA aws-messaging com a mensagem fixa,
        snapshot e seen_at mantidos, aws-data ok, exit 1."""
        # SPEC-0097:IT-02
        self.first_scan()
        before = (self.snapshots / "aws-messaging.json").read_bytes()
        state_before = json.loads((self.snapshots / "_scan.json").read_text(encoding="utf-8"))
        result = self.scan(mode="sso-expired:sqs")
        self.assertEqual(result.returncode, 1, output(result))
        self.assertIn("FALHA aws-messaging — saiu com 1", output(result))
        self.assertIn(MSG_LOGIN, output(result))
        for leak in (PROFILE, ACCOUNT, "Token has expired"):
            self.assertNotIn(leak, output(result))
        self.assertEqual((self.snapshots / "aws-messaging.json").read_bytes(), before)
        state = json.loads((self.snapshots / "_scan.json").read_text(encoding="utf-8"))
        self.assertEqual(state["aws-messaging"]["status"], "failed")
        self.assertEqual(state["aws-messaging"]["seen_at"], state_before["aws-messaging"]["seen_at"])
        self.assertEqual(state["aws-data"]["status"], "ok")


# --------------------------------------------------------------------------- CT-01: contrato


def json_blocks(path: Path):
    """Objetos JSON dos blocos ```json de um Markdown (os que não são JSON válido ficam de fora)."""
    text = path.read_text(encoding="utf-8")
    found = []
    for block in re.findall(r"```json\n(.*?)```", text, re.DOTALL):
        try:
            found.append(json.loads(block))
        except ValueError:
            continue
    return found


class ContractTest(AwsCase):
    def assertValidAwsOutput(self, data):
        atlas_module_validate = fn("validate_collector_output", SPEC)
        kinds, types = fn("KINDS", SPEC), fn("RELATION_TYPES", SPEC)
        clean, violations, dropped = atlas_module_validate(data)
        self.assertEqual(violations, [])
        self.assertEqual(dropped, [], "nenhum campo nem chave descartada")
        queues = {e["id"] for e in data["entities"] if e["kind"] == "queue"}
        for item in data["entities"]:
            self.assertIn(item["kind"], kinds)
            attrs = item["attrs"]
            if "port" in attrs:
                self.assertIsInstance(attrs["port"], int)
                self.assertNotIsInstance(attrs["port"], bool)
            if "dlq" in attrs:
                self.assertIn(attrs["dlq"], queues)
                self.assertNotEqual(attrs["dlq"], item["id"])
            for key, value in attrs.items():
                scalar = (str, int, float, bool)
                self.assertTrue(isinstance(value, scalar) or (isinstance(value, list) and
                                                              all(isinstance(v, scalar) for v in value)), key)
        for rel in data["relations"]:
            self.assertIn(rel["type"], types)

    def test_examples_and_outputs_follow_the_contract(self):
        """SPEC-0097:CT-01 — data-aws.json e messaging-aws.json (iguais aos blocos das referências) e as saídas
        de UT-01 e UT-02 passam no validador @1 sem violação nem descarte."""
        # SPEC-0097:CT-01
        examples = {}
        for name in ("data-aws.json", "messaging-aws.json"):
            with self.subTest(example=name):
                data = json.loads((CONTRACT_VALID / name).read_text(encoding="utf-8"))
                examples[name] = data
                self.assertValidAwsOutput(data)
        data, _ = self.collect("--services", "rds,elasticache", "--region", US)
        self.assertValidAwsOutput(data)
        data, _ = self.collect("--services", "sqs,sns", "--region", US)
        self.assertValidAwsOutput(data)

    def test_reference_blocks_equal_the_examples(self):
        """SPEC-0097:CT-01 — os exemplos ficam iguais aos blocos de references/collectors/aws.md e de
        references/collector-contract.md."""
        # SPEC-0097:CT-01
        for reference in (AWS_REFERENCE, CONTRACT_REFERENCE):
            self.assertTrue(reference.is_file(), f"{reference} não existe ({SPEC})")
            blocks = [b for b in json_blocks(reference) if isinstance(b, dict) and b.get("collector") == "aws"]
            for name in ("data-aws.json", "messaging-aws.json"):
                with self.subTest(reference=reference.name, example=name):
                    example = json.loads((CONTRACT_VALID / name).read_text(encoding="utf-8"))
                    self.assertIn(example, blocks, f"{reference.name} não traz o bloco igual a {name}")


if __name__ == "__main__":
    unittest.main()
