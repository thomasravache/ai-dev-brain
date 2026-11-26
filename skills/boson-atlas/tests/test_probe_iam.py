"""Adaptador de simulação de IAM: permissão do workload na fila ou no tópico (SPEC-0101: UT-01 a UT-06, IT-01, IT-02,
CT-01 e CT-02; ADR-0010, ADR-0023, ADR-0025, ADR-0026).

Contrato (seção 6 da SPEC-0101) que estes testes fixam:

    assets/probes/iam.py --describe ->
        {"contract": "probe@2", "adapter": "iam", "capabilities": {"permissions": {"verbs": ["simulate"],
         "targets": ["queue", "topic"], "access": ["cluster", "cloud"]}}}
    entrada probe@2 no stdin (target.resource {kind, id, attrs}, target.cloud.profile, target.context, namespace,
    workloads); saída probe@2 no stdout, exit 0 também no erro (status "error", items [], mensagem fixa).
    kubectl: get <deployments|statefulsets|daemonsets|rollouts|serviceaccounts> <nome> -o json --context <ctx>
        -n <ns> --request-timeout=20s.
    aws: sts get-caller-identity | sqs get-queue-url | sqs get-queue-attributes (Policy QueueArn) |
        sns get-topic-attributes | iam simulate-principal-policy; sempre com --region, --profile, --output json,
        --no-cli-pager, --cli-read-timeout 20, --cli-connect-timeout 10.
    simulate -> um item por (workload, ação) {workload, role, action, api_action, decision, deny_type, required_by,
        resource_policy}.

Leituras desta suíte (listadas no relatório do test-writer):
    - Os itens têm exatamente as 8 chaves do bloco da seção 6, em ordem de workload (a ordem da entrada) e da lista
      de ações (send, receive, delete; publish).
    - Todos os papéis são resolvidos no cluster antes de qualquer chamada à aws (UT-03: "nenhuma chamada à aws").
    - Verbo fora de simulate -> "verbo não suportado"; kind de recurso fora de queue/topic (bucket) -> "entrada
      inválida" ou "chamada não permitida" (a spec não fixa qual dos dois); o resto fora da regra -> "entrada inválida".
    - `--resource-policy` é a política em JSON compacto: sem quebra de linha nem espaço depois de "," e ":" (fora de
      textos), com o mesmo conteúdo da política devolvida.
    - O ambiente da aws traz AWS_PAGER="" e nenhum AWS_PROFILE, AWS_DEFAULT_PROFILE, AWS_ACCESS_KEY_ID,
      AWS_SECRET_ACCESS_KEY ou AWS_SESSION_TOKEN herdados.
    - O `--context` do kubectl pode vir como "--context X" ou "--context=X"; o timeout como
      "--request-timeout=20s" ou "--request-timeout 20s".
    - Com 6 workloads, os 5 primeiros (na ordem da entrada) e nenhum get do sexto.
    - O timeout do processo (30 s) não é exercitado: o "timeout" vem do texto da CLI.

Dublês: fixtures/iam/fake_kubectl.py e fixtures/iam/fake_aws.py, copiados como `kubectl` e `aws` em pastas
temporárias (os únicos itens do PATH nos testes unitários), com o cenário em JSON ao lado; registram cada argv (e as
variáveis AWS_* da aws). Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários; nenhum ~/.aws ou
~/.kube, nenhuma nuvem, nenhum cluster, nenhuma rede; nomes acme, orders, orders-events, orders-worker, região
us-east-1 e a conta de exemplo da documentação da AWS 123456789012, só nas respostas dos dublês.
"""
import copy
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

SPEC = "SPEC-0101"
ADAPTER = SKILL / "assets" / "probes" / "iam.py"
REFERENCE = SKILL / "references" / "probes" / "iam.md"
FIXTURES = TESTS / "fixtures" / "iam"
FAKE_KUBECTL = FIXTURES / "fake_kubectl.py"
FAKE_AWS = FIXTURES / "fake_aws.py"
ATLAS_FIXTURE = TESTS / "fixtures" / "probe-resource" / "atlas"

ACCOUNT = "123456789012"
OTHER_ACCOUNT = "999999999999"
REGION = "us-east-1"
PROFILE = "acme-dev-iam-0101"
CONTEXT = "ctx-local-dev-0101"
NAMESPACE = "orders-dev"
QUEUE = "orders"
BARE_QUEUE = "orders-bare"
TOPIC = "orders-events"
ROLE = "orders-worker-dev"
SENTINEL = "SENTINEL-STDERR-0101"
LEAKED = {"AWS_PROFILE": "leaked-profile-0101", "AWS_DEFAULT_PROFILE": "leaked-default-0101",
          "AWS_ACCESS_KEY_ID": "AKIAFAKELEAK0101XXXX", "AWS_SECRET_ACCESS_KEY": "fake-leaked-secret-0101",
          "AWS_SESSION_TOKEN": "fake-leaked-token-0101"}

DESCRIBE = {"contract": "probe@2", "adapter": "iam",
            "capabilities": {"permissions": {"verbs": ["simulate"], "targets": ["queue", "topic"],
                                             "access": ["cluster", "cloud"]}}}
ITEM_KEYS = {"workload", "role", "action", "api_action", "decision", "deny_type", "required_by", "resource_policy"}
QUEUE_ACTIONS = [("send", "sqs:SendMessage", ["depends_on", "publishes"]),
                 ("receive", "sqs:ReceiveMessage", ["consumes"]),
                 ("delete", "sqs:DeleteMessage", ["consumes"])]
TOPIC_ACTIONS = [("publish", "sns:Publish", ["publishes"])]
ABSTRACT_ACTIONS = {"publish", "send", "receive", "delete", "read", "write"}

INVALID_INPUT = "entrada inválida"
NO_REGION = "recurso sem região no atlas"
REFUSED = "chamada não permitida"
NO_VERB = "verbo não suportado"
BAD_CLOUD = "resposta inválida da nuvem"
BAD_KUBECTL = "resposta inválida do kubectl"
NO_IRSA = "workload sem role IRSA (Pod Identity não verificado nesta versão)"
NO_POLICY = "não foi possível ler a política do recurso"
NO_RESOURCE = "recurso não encontrado na nuvem"
NO_WORKLOAD = "workload não encontrado"
LOGIN = "renove o login da nuvem"
KUBECTL_ERRORS = {"forbidden": "sem permissão no cluster (Forbidden)", "nocontext": "contexto inexistente",
                  "timeout": "timeout", "invalid-json": BAD_KUBECTL, "fail": "falha do kubectl"}
AWS_ERRORS = {"sso-expired": LOGIN, "token-expired": LOGIN, "profile-not-found": LOGIN, "no-credentials": LOGIN,
              "timeout": "timeout", "invalid-json": BAD_CLOUD, "fail": "falha da aws"}

KUBE_RESOURCES = {"deployments", "statefulsets", "daemonsets", "rollouts", "serviceaccounts"}
KIND_RESOURCE = {"Deployment": "deployments", "StatefulSet": "statefulsets", "DaemonSet": "daemonsets",
                 "Rollout": "rollouts"}
# lista fechada (seção 6): (serviço, operação) -> opções próprias aceitas
OPERATIONS = {
    ("sts", "get-caller-identity"): set(),
    ("sqs", "get-queue-url"): {"--queue-name"},
    ("sqs", "get-queue-attributes"): {"--queue-url", "--attribute-names"},
    ("sns", "get-topic-attributes"): {"--topic-arn"},
    ("iam", "simulate-principal-policy"): {"--policy-source-arn", "--action-names", "--resource-arns",
                                           "--resource-policy"},
}
COMMON = {"--region", "--profile", "--output", "--no-cli-pager", "--cli-read-timeout", "--cli-connect-timeout"}
SIMULATE = ("iam", "simulate-principal-policy")

QUEUE_POLICY = {"Version": "2012-10-17", "Id": "orders-policy",
                "Statement": [{"Sid": "AllowWorker", "Effect": "Allow",
                               "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"},
                               "Action": ["sqs:ReceiveMessage", "sqs:DeleteMessage"],
                               "Resource": f"arn:aws:sqs:{REGION}:{ACCOUNT}:{QUEUE}"}]}
TOPIC_POLICY = {"Version": "2012-10-17",
                "Statement": [{"Sid": "AllowPublish", "Effect": "Allow",
                               "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"},
                               "Action": "sns:Publish",
                               "Resource": f"arn:aws:sns:{REGION}:{ACCOUNT}:{TOPIC}"}]}


def f(name):
    return fn(name, "SPEC-0096")


def role_arn(name=ROLE, partition="aws", path=""):
    return f"arn:{partition}:iam::{ACCOUNT}:role/{path}{name}"


def queue_url(name=QUEUE, region=REGION):
    return f"https://sqs.{region}.amazonaws.com/{ACCOUNT}/{name}"


def queue_arn(name=QUEUE, region=REGION):
    return f"arn:aws:sqs:{region}:{ACCOUNT}:{name}"


def topic_arn(name=TOPIC, region=REGION, partition="aws"):
    return f"arn:{partition}:sns:{region}:{ACCOUNT}:{name}"


# --------------------------------------------------------------------------- cenários dos dublês


def workload_object(kind, name, sa="worker", field="serviceAccountName"):
    pod_spec = {"containers": [{"name": "app", "image": "acme/orders-worker:1.0.0"}]}
    if sa is not None:
        pod_spec[field] = sa
    return {"apiVersion": "apps/v1", "kind": kind,
            "metadata": {"name": name, "namespace": NAMESPACE, "uid": "00000000-0000-4000-8000-000000000101"},
            "spec": {"replicas": 1, "selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": {"app": name}}, "spec": pod_spec}}}


def sa_object(name, arn):
    annotations = {"kubectl.kubernetes.io/last-applied-configuration": "{}"}
    if arn is not None:
        annotations["eks.amazonaws.com/role-arn"] = arn
    return {"apiVersion": "v1", "kind": "ServiceAccount",
            "metadata": {"name": name, "namespace": NAMESPACE, "annotations": annotations}}


def base_kube():
    return {"objects": {"deployments/worker": workload_object("Deployment", "worker"),
                        "serviceaccounts/worker": sa_object("worker", role_arn())},
            "fail": ""}


def base_aws():
    return {"account": ACCOUNT, "partition": "aws",
            "queues": {QUEUE: {"Policy": json.dumps(QUEUE_POLICY, indent=2)}, BARE_QUEUE: {}},
            "topics": {TOPIC: {"Policy": json.dumps(TOPIC_POLICY, indent=2)}},
            "roles": [ROLE, "api-dev"],
            "decisions": {},
            "fail": []}


def install_fake(source: Path, folder: Path, name: str, scenario_name: str, scenario: dict, record: Path):
    """Copia o dublê como `name` (cabeçalho com o Python dos testes) e grava o cenário ao lado dele."""
    folder.mkdir(parents=True, exist_ok=True)
    body = source.read_text(encoding="utf-8").split("\n", 1)[1]
    target = folder / name
    target.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (folder / scenario_name).write_text(json.dumps(dict(scenario, record=str(record))), encoding="utf-8")
    return target


def read_rows(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_aws(argv):
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


def parse_kube(argv):
    """(palavras, {opção: valor}) de um argv do kubectl (com espaço ou "="); opção sem valor = True."""
    words, options, i = [], {}, 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("-"):
            name, eq, value = arg.partition("=")
            if eq:
                options[name] = value
            elif i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                options[name] = argv[i + 1]
                i += 1
            else:
                options[name] = True
        else:
            words.append(arg)
        i += 1
    return words, options


def as_list(value):
    return value if isinstance(value, list) else [value] if isinstance(value, str) else []


def aws_call_problems(argv, region, profile) -> list:
    """SPEC-0101:UT-05 — problemas de um argv da aws frente à lista fechada da seção 6; [] = permitido."""
    words, options = parse_aws(argv)
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
    if pair == ("sqs", "get-queue-attributes"):
        names = as_list(options.get("--attribute-names"))
        if sorted(names) != ["Policy", "QueueArn"]:
            problems.append(f"get-queue-attributes pede outros atributos: {names}")
    for key in ("--queue-name", "--queue-url", "--topic-arn", "--policy-source-arn", "--resource-arns",
                "--resource-policy"):
        if key in options and not isinstance(options[key], str):
            problems.append(f"{key} sem um valor só")
    for value in argv:
        if value in (OTHER_ACCOUNT,) or OTHER_ACCOUNT in value:
            problems.append("um valor do attrs do atlas chegou à aws")
    return problems


def kube_call_problems(argv, context, namespace) -> list:
    """SPEC-0101:UT-05 — problemas de um argv do kubectl frente à lista fechada da seção 6; [] = permitido."""
    words, options = parse_kube(argv)
    if len(words) != 3 or words[0] != "get" or words[1] not in KUBE_RESOURCES or argv[0] != "get":
        return [f"chamada fora da lista: {argv}"]
    problems = []
    if words[2].startswith("-"):
        problems.append("nome começando com -")
    allowed = {"-o", "--output", "--context", "-n", "--namespace", "--request-timeout"}
    unknown = set(options) - allowed
    if unknown:
        problems.append(f"opções fora da lista: {sorted(unknown)}")
    if options.get("-o", options.get("--output")) != "json":
        problems.append("sem -o json")
    if options.get("--context") != context:
        problems.append(f"--context diferente: {options.get('--context')!r}")
    if options.get("-n", options.get("--namespace")) != namespace:
        problems.append("namespace diferente")
    if options.get("--request-timeout") != "20s":
        problems.append("sem --request-timeout=20s")
    return problems


def probe_input(kind="queue", rid=None, attrs=None, workloads=("Deployment/worker",), verb="simulate",
                profile=PROFILE, contract="probe@2"):
    rid = rid or (TOPIC if kind == "topic" else QUEUE)
    attrs = {"region": REGION} if attrs is None else attrs
    return {"contract": contract, "capability": "permissions", "verb": verb,
            "target": {"service": "orders-worker", "environment": "dev", "deployment": "dev-orders-worker",
                       "resource": {"kind": kind, "id": rid, "attrs": attrs},
                       "clusters": ["cluster-dev"], "context": CONTEXT, "namespace": NAMESPACE,
                       "workloads": list(workloads), "cloud": {"profile": profile}},
            "limits": {"lines": 200, "since_seconds": 1800}}


def expected_items(workload="Deployment/worker", role=ROLE, actions=QUEUE_ACTIONS, decisions=None, policy=True):
    decisions = decisions or {}
    items = []
    for action, api, required in actions:
        decision, deny = decisions.get(api, ("allowed", None))
        items.append({"workload": workload, "role": role, "action": action, "api_action": api,
                      "decision": decision, "deny_type": deny, "required_by": required, "resource_policy": policy})
    return items


def table_4a_problems(out) -> list:
    """SPEC-0101:CT-02 — a conferência da tabela 4a do ADR-0026 (o que o verify@2 lê) sobre os itens de simulate."""
    items = out.get("items")
    if not isinstance(items, list) or not items:
        return ["items precisa ser uma lista não vazia"]
    problems = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"items[{index}] não é objeto")
            continue
        if item.get("action") not in ABSTRACT_ACTIONS:
            problems.append(f"items[{index}].action fora de {sorted(ABSTRACT_ACTIONS)}")
        api = item.get("api_action")
        if not (isinstance(api, str) and api.strip()):
            problems.append(f"items[{index}].api_action precisa ser um texto não vazio")
        if item.get("decision") not in ("allowed", "denied"):
            problems.append(f"items[{index}].decision precisa ser allowed ou denied")
    return problems


# --------------------------------------------------------------------------- base


class IamCase(unittest.TestCase):
    """Uma pasta temporária por teste: HOME, configuração e as pastas do kubectl e da aws falsos (o PATH)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.kube_bin = self.root / "kube-bin"
        self.aws_bin = self.root / "aws-bin"
        self.kube_record = self.root / "kubectl-calls.jsonl"
        self.aws_record = self.root / "aws-calls.jsonl"
        self.kube = base_kube()
        self.aws = base_aws()

    def install(self, kube=None, aws=None):
        self.kube_record.unlink(missing_ok=True)
        self.aws_record.unlink(missing_ok=True)
        install_fake(FAKE_KUBECTL, self.kube_bin, "kubectl", "fake-kubectl.json", self.kube if kube is None else kube,
                     self.kube_record)
        install_fake(FAKE_AWS, self.aws_bin, "aws", "fake-aws.json", self.aws if aws is None else aws,
                     self.aws_record)

    def environment(self, with_kubectl=True, with_aws=True):
        empty = self.root / "empty-bin"
        empty.mkdir(exist_ok=True)
        folders = [str(self.kube_bin)] if with_kubectl else []
        folders += [str(self.aws_bin)] if with_aws else []
        env = {"PATH": os.pathsep.join(folders or [str(empty)]), "HOME": str(self.home),
               "XDG_CONFIG_HOME": str(self.home / ".config"), "ATLAS_CONFIG_HOME": str(self.root / "config-home"),
               "LANG": "C.UTF-8", **LEAKED}
        for name in ("TMPDIR", "SYSTEMROOT"):
            if name in os.environ:
                env[name] = os.environ[name]
        return env

    def adapter(self, *args, stdin="", with_kubectl=True, with_aws=True):
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        result = subprocess.run([sys.executable, str(ADAPTER), *args], input=stdin, capture_output=True, text=True,
                                cwd=self.root, env=self.environment(with_kubectl, with_aws), timeout=180,
                                check=False)
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        return result

    def run_probe(self, data, raw=None, with_kubectl=True, with_aws=True):
        """Roda o adaptador; confere exit 0, a saída probe@2 (validador do núcleo), o pedido ecoado, nada sensível na
        saída (UT-04, UT-06), as chaves dos itens e cada chamada contra a lista fechada (UT-05)."""
        result = self.adapter(stdin=raw if raw is not None else json.dumps(data), with_kubectl=with_kubectl,
                              with_aws=with_aws)
        self.assertEqual(result.returncode, 0, output(result))
        text = output(result)
        for value in (PROFILE, CONTEXT, ACCOUNT, OTHER_ACCOUNT, "arn:", "https://sqs", "amazonaws.com", SENTINEL,
                      *LEAKED.values()):
            self.assertNotIn(value, text, f"{value} apareceu na saída do adaptador")
        out = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(out), [], out)
        self.assertEqual({k: out.get(k) for k in ("contract", "adapter", "capability")},
                         {"contract": "probe@2", "adapter": "iam", "capability": "permissions"})
        if out["status"] == "ok":
            # SPEC-0101:UT-04
            for item in out["items"]:
                self.assertEqual(set(item), ITEM_KEYS, item)
        if isinstance(data, dict):
            self.assertEqual(out.get("verb"), data["verb"])
            self.assertAllowedCalls(data)
        return out

    def kube_calls(self):
        return [row["argv"] for row in read_rows(self.kube_record)]

    def aws_rows(self):
        return read_rows(self.aws_record)

    def aws_calls(self):
        return [row["argv"] for row in self.aws_rows()]

    def pairs(self):
        return [tuple(parse_aws(argv)[0][:2]) for argv in self.aws_calls()]

    def option_of(self, pair, name):
        return [parse_aws(a)[1].get(name) for a in self.aws_calls() if tuple(parse_aws(a)[0][:2]) == pair]

    def kube_gets(self):
        return [tuple(parse_kube(argv)[0][1:3]) for argv in self.kube_calls()]

    def assertAllowedCalls(self, data):
        """SPEC-0101:UT-05 — todo argv da lista fechada, com as opções comuns, e os máximos da seção 5."""
        # SPEC-0101:UT-05
        target = data["target"]
        attrs = target["resource"]["attrs"]
        region = attrs.get("region") if isinstance(attrs, dict) else None
        for argv in self.kube_calls():
            self.assertEqual(kube_call_problems(argv, target["context"], target["namespace"]), [], argv)
        for row in self.aws_rows():
            self.assertEqual(aws_call_problems(row["argv"], region, target["cloud"]["profile"]), [], row["argv"])
            env = row["env"]
            for name in LEAKED:
                self.assertNotIn(name, env, f"{name} herdado chegou à aws")
            self.assertEqual(env.get("AWS_PAGER"), "", "AWS_PAGER precisa ser vazio")
        gets = self.kube_gets()
        for get in set(gets):
            self.assertEqual(gets.count(get), 1, f"kubectl get {get} mais de uma vez")
        pairs = self.pairs()
        for pair in (("sts", "get-caller-identity"), ("sqs", "get-queue-url"), ("sqs", "get-queue-attributes"),
                     ("sns", "get-topic-attributes")):
            self.assertLessEqual(pairs.count(pair), 1, f"{pair} mais de uma vez: {pairs}")
        if target["resource"]["kind"] == "queue":
            self.assertNotIn(("sts", "get-caller-identity"), pairs, "get-caller-identity numa fila")
            self.assertNotIn(("sns", "get-topic-attributes"), pairs)
        if target["resource"]["kind"] == "topic":
            self.assertNotIn(("sqs", "get-queue-url"), pairs)
            self.assertNotIn(("sqs", "get-queue-attributes"), pairs)
        roles = {parse_aws(a)[1].get("--policy-source-arn") for a in self.aws_calls()
                 if tuple(parse_aws(a)[0][:2]) == SIMULATE}
        self.assertEqual(pairs.count(SIMULATE), len(roles), "mais de uma simulação para o mesmo papel")

    def assertError(self, out, message):
        self.assertEqual(out["status"], "error", out)
        self.assertEqual(out["items"], [], out)
        self.assertEqual(out.get("message"), message, out)

    def ok(self, data):
        out = self.run_probe(data)
        self.assertEqual(out["status"], "ok", out)
        return out


# --------------------------------------------------------------------------- UT-01


class SimulateTest(IamCase):
    def test_queue_with_policy(self):
        """SPEC-0101:UT-01 — Deployment/worker com a ServiceAccount worker anotada com o papel orders-worker-dev e a
        fila orders com Policy: get-queue-attributes usa a QueueUrl do get-queue-url, a simulação recebe as três
        ações da fila, o QueueArn e a política em JSON compacto; 3 itens send, receive e delete com required_by do
        mapa e resource_policy true."""
        # SPEC-0101:UT-01
        self.install()
        out = self.ok(probe_input())
        self.assertEqual(out["items"], expected_items())
        self.assertIs(out.get("truncated", False), False)
        self.assertEqual(self.kube_gets(), [("deployments", "worker"), ("serviceaccounts", "worker")])
        pairs = self.pairs()
        self.assertEqual(self.option_of(("sqs", "get-queue-url"), "--queue-name"), [QUEUE])
        self.assertEqual(self.option_of(("sqs", "get-queue-attributes"), "--queue-url"), [queue_url()])
        self.assertLess(pairs.index(("sqs", "get-queue-url")), pairs.index(("sqs", "get-queue-attributes")))
        self.assertLess(pairs.index(("sqs", "get-queue-attributes")), pairs.index(SIMULATE))
        self.assertEqual(pairs.count(SIMULATE), 1)
        self.assertEqual(self.option_of(SIMULATE, "--policy-source-arn"), [role_arn()])
        self.assertEqual(sorted(as_list(self.option_of(SIMULATE, "--action-names")[0])),
                         sorted(api for _, api, _ in QUEUE_ACTIONS))
        self.assertEqual(self.option_of(SIMULATE, "--resource-arns"), [queue_arn()])
        policy = self.option_of(SIMULATE, "--resource-policy")[0]
        self.assertIsInstance(policy, str)
        self.assertEqual(json.loads(policy), QUEUE_POLICY)
        self.assertNotIn("\n", policy)
        self.assertNotRegex(policy, r'[,:] ', "a política não está em JSON compacto")

    def test_topic(self):
        """SPEC-0101:UT-01 — tópico orders-events: uma sts get-caller-identity, o ARN arn:aws:sns:us-east-1:<conta>:
        orders-events no get-topic-attributes e na simulação, e só o item publish (sns:Publish) com required_by
        ["publishes"]."""
        # SPEC-0101:UT-01
        self.install()
        out = self.ok(probe_input("topic"))
        self.assertEqual(out["items"], expected_items(actions=TOPIC_ACTIONS))
        self.assertEqual(self.pairs().count(("sts", "get-caller-identity")), 1)
        self.assertLess(self.pairs().index(("sts", "get-caller-identity")),
                        self.pairs().index(("sns", "get-topic-attributes")))
        self.assertEqual(self.option_of(("sns", "get-topic-attributes"), "--topic-arn"), [topic_arn()])
        self.assertEqual(self.option_of(SIMULATE, "--resource-arns"), [topic_arn()])
        self.assertEqual(as_list(self.option_of(SIMULATE, "--action-names")[0]), ["sns:Publish"])
        self.assertEqual(json.loads(self.option_of(SIMULATE, "--resource-policy")[0]), TOPIC_POLICY)

    def test_topic_partition_comes_from_the_caller_identity(self):
        """SPEC-0101:UT-01 — com a identidade numa partição aws-cn, o ARN do tópico usa arn:aws-cn."""
        # SPEC-0101:UT-01
        self.aws["partition"] = "aws-cn"
        self.kube["objects"]["serviceaccounts/worker"] = sa_object("worker", role_arn(partition="aws-cn"))
        self.install()
        self.ok(probe_input("topic", attrs={"region": "cn-north-1"}))
        self.assertEqual(self.option_of(("sns", "get-topic-attributes"), "--topic-arn"),
                         [topic_arn(region="cn-north-1", partition="aws-cn")])

    def test_queue_without_policy(self):
        """SPEC-0101:UT-01 — fila sem o atributo Policy: a simulação vai sem --resource-policy e os itens têm
        resource_policy false."""
        # SPEC-0101:UT-01
        self.install()
        out = self.ok(probe_input(rid=BARE_QUEUE))
        self.assertEqual(out["items"], expected_items(policy=False))
        self.assertEqual(self.pairs().count(SIMULATE), 1)
        self.assertEqual(self.option_of(SIMULATE, "--resource-policy"), [None])
        self.assertEqual(self.option_of(SIMULATE, "--resource-arns"), [queue_arn(BARE_QUEUE)])

    def test_required_by_map(self):
        """SPEC-0101:UT-01 — o mapa fixo: send ["depends_on", "publishes"], receive e delete ["consumes"], publish
        ["publishes"]."""
        # SPEC-0101:UT-01
        self.install()
        queue = self.ok(probe_input())
        self.install()
        topic = self.ok(probe_input("topic"))
        got = {i["action"]: (i["api_action"], i["required_by"]) for i in queue["items"] + topic["items"]}
        self.assertEqual(got, {"send": ("sqs:SendMessage", ["depends_on", "publishes"]),
                               "receive": ("sqs:ReceiveMessage", ["consumes"]),
                               "delete": ("sqs:DeleteMessage", ["consumes"]),
                               "publish": ("sns:Publish", ["publishes"])})

    def test_role_is_only_the_name(self):
        """SPEC-0101:UT-01 — papel com caminho (role/apps/orders-worker-dev): role sai só orders-worker-dev."""
        # SPEC-0101:UT-01
        self.kube["objects"]["serviceaccounts/worker"] = sa_object("worker", role_arn(path="apps/"))
        self.install()
        out = self.ok(probe_input())
        self.assertEqual({i["role"] for i in out["items"]}, {ROLE})
        self.assertEqual(self.option_of(SIMULATE, "--policy-source-arn"), [role_arn(path="apps/")])


# --------------------------------------------------------------------------- UT-02


class DecisionTest(IamCase):
    def test_allowed_explicit_and_implicit_deny(self):
        """SPEC-0101:UT-02 — allowed, explicitDeny e implicitDeny viram allowed (deny_type null), denied/explicit e
        denied/implicit."""
        # SPEC-0101:UT-02
        self.aws["decisions"] = {"sqs:SendMessage": "allowed", "sqs:ReceiveMessage": "explicitDeny",
                                 "sqs:DeleteMessage": "implicitDeny"}
        self.install()
        out = self.ok(probe_input())
        self.assertEqual(out["items"], expected_items(decisions={"sqs:ReceiveMessage": ("denied", "explicit"),
                                                                 "sqs:DeleteMessage": ("denied", "implicit")}))

    def test_unknown_decision_is_an_invalid_answer(self):
        """SPEC-0101:UT-02 — EvalDecision fora dos três valores: status error "resposta inválida da nuvem"."""
        # SPEC-0101:UT-02
        self.aws["decisions"] = {"sqs:ReceiveMessage": "maybeAllowed"}
        self.install()
        self.assertError(self.run_probe(probe_input()), BAD_CLOUD)

    def test_shared_role_means_one_simulation(self):
        """SPEC-0101:UT-02 — Deployment/api e Deployment/api-canary com a mesma ServiceAccount: um get da
        ServiceAccount, uma simulação e itens para os dois workloads, em ordem de workload."""
        # SPEC-0101:UT-02
        self.kube["objects"] = {"deployments/api": workload_object("Deployment", "api", sa="api"),
                                "deployments/api-canary": workload_object("Deployment", "api-canary", sa="api"),
                                "serviceaccounts/api": sa_object("api", role_arn("api-dev"))}
        self.install()
        out = self.ok(probe_input(workloads=("Deployment/api", "Deployment/api-canary")))
        self.assertEqual(out["items"], expected_items("Deployment/api", "api-dev")
                         + expected_items("Deployment/api-canary", "api-dev"))
        self.assertEqual(self.pairs().count(SIMULATE), 1)
        self.assertEqual(self.kube_gets().count(("serviceaccounts", "api")), 1)

    def test_two_roles_mean_two_simulations(self):
        """SPEC-0101:UT-02 — dois workloads com papéis diferentes: uma simulação por papel e os itens de cada um."""
        # SPEC-0101:UT-02
        self.kube["objects"].update({"deployments/api": workload_object("Deployment", "api", sa="api"),
                                     "serviceaccounts/api": sa_object("api", role_arn("api-dev"))})
        self.install()
        out = self.ok(probe_input(workloads=("Deployment/api", "Deployment/worker")))
        self.assertEqual(out["items"], expected_items("Deployment/api", "api-dev") + expected_items())
        self.assertEqual(sorted(self.option_of(SIMULATE, "--policy-source-arn")),
                         sorted([role_arn("api-dev"), role_arn()]))

    def test_more_than_five_workloads_are_cut(self):
        """SPEC-0101:UT-02 — 6 workloads: só os 5 primeiros (15 itens), truncated true e nenhum get do sexto."""
        # SPEC-0101:UT-02
        names = [f"worker-{n}" for n in range(1, 7)]
        for name in names:
            self.kube["objects"][f"deployments/{name}"] = workload_object("Deployment", name)
        self.install()
        out = self.ok(probe_input(workloads=[f"Deployment/{n}" for n in names]))
        self.assertIs(out["truncated"], True)
        self.assertEqual([i["workload"] for i in out["items"]],
                         [f"Deployment/{n}" for n in names[:5] for _ in QUEUE_ACTIONS])
        self.assertNotIn(("deployments", "worker-6"), self.kube_gets())
        self.assertEqual(self.pairs().count(SIMULATE), 1)


# --------------------------------------------------------------------------- UT-03


class PrincipalTest(IamCase):
    def test_service_account_without_irsa(self):
        """SPEC-0101:UT-03 — ServiceAccount sem eks.amazonaws.com/role-arn: erro de Pod Identity e nenhuma chamada
        à aws."""
        # SPEC-0101:UT-03
        self.kube["objects"]["serviceaccounts/worker"] = sa_object("worker", None)
        self.install()
        self.assertError(self.run_probe(probe_input()), NO_IRSA)
        self.assertEqual(self.aws_calls(), [])

    def test_one_workload_without_irsa_fails_the_whole_run(self):
        """SPEC-0101:UT-03 — dois workloads, o segundo sem papel IRSA: erro da execução inteira, nenhum item e
        nenhuma chamada à aws."""
        # SPEC-0101:UT-03
        self.kube["objects"].update({"deployments/zeta": workload_object("Deployment", "zeta", sa="zeta"),
                                     "serviceaccounts/zeta": sa_object("zeta", None)})
        self.install()
        self.assertError(self.run_probe(probe_input(workloads=("Deployment/worker", "Deployment/zeta"))), NO_IRSA)
        self.assertEqual(self.aws_calls(), [])

    def test_missing_workload(self):
        """SPEC-0101:UT-03 — workload ausente (NotFound): "workload não encontrado", sem chamada à aws."""
        # SPEC-0101:UT-03
        self.install()
        self.assertError(self.run_probe(probe_input(workloads=("Deployment/ghost",))), NO_WORKLOAD)
        self.assertEqual(self.aws_calls(), [])

    def test_pod_template_without_service_account_uses_default(self):
        """SPEC-0101:UT-03 — pod template sem serviceAccountName: o adaptador lê a ServiceAccount default."""
        # SPEC-0101:UT-03
        self.kube["objects"] = {"deployments/worker": workload_object("Deployment", "worker", sa=None),
                                "serviceaccounts/default": sa_object("default", role_arn())}
        self.install()
        out = self.ok(probe_input())
        self.assertEqual(out["items"], expected_items())
        self.assertIn(("serviceaccounts", "default"), self.kube_gets())

    def test_legacy_service_account_field(self):
        """SPEC-0101:UT-03 — pod template só com o campo serviceAccount (antigo): vale esse nome."""
        # SPEC-0101:UT-03
        self.kube["objects"]["deployments/worker"] = workload_object("Deployment", "worker", field="serviceAccount")
        self.install()
        self.ok(probe_input())
        self.assertIn(("serviceaccounts", "worker"), self.kube_gets())

    def test_workload_kinds_map_to_their_resources(self):
        """SPEC-0101:UT-03 — StatefulSet, DaemonSet e Rollout são lidos de statefulsets, daemonsets e rollouts."""
        # SPEC-0101:UT-03
        for kind, resource in KIND_RESOURCE.items():
            with self.subTest(kind=kind):
                self.kube["objects"] = {f"{resource}/worker": workload_object(kind, "worker"),
                                        "serviceaccounts/worker": sa_object("worker", role_arn())}
                self.install()
                out = self.ok(probe_input(workloads=(f"{kind}/worker",)))
                self.assertEqual(out["items"], expected_items(f"{kind}/worker"))
                self.assertEqual(self.kube_gets()[0], (resource, "worker"))

    def test_missing_resource_in_the_cloud(self):
        """SPEC-0101:UT-03 — NonExistentQueue no get-queue-url e NotFound no get-topic-attributes: "recurso não
        encontrado na nuvem", sem simulação."""
        # SPEC-0101:UT-03
        self.install()
        self.assertError(self.run_probe(probe_input(rid="ghost")), NO_RESOURCE)
        self.assertNotIn(SIMULATE, self.pairs())
        self.install()
        self.assertError(self.run_probe(probe_input("topic", rid="ghost-events")), NO_RESOURCE)
        self.assertNotIn(SIMULATE, self.pairs())

    def test_unreadable_policy_means_no_simulation(self):
        """SPEC-0101:UT-03 — AccessDenied no get-queue-attributes e AuthorizationError no get-topic-attributes:
        "não foi possível ler a política do recurso", nenhuma simulação e nenhum item."""
        # SPEC-0101:UT-03
        for kind, service, operation in (("queue", "sqs", "get-queue-attributes"),
                                         ("topic", "sns", "get-topic-attributes")):
            with self.subTest(kind=kind):
                aws = base_aws()
                aws["fail"] = [{"mode": "denied", "service": service, "operation": operation}]
                self.install(aws=aws)
                self.assertError(self.run_probe(probe_input(kind)), NO_POLICY)
                self.assertNotIn(SIMULATE, self.pairs())

    def test_role_annotation_out_of_the_rule(self):
        """SPEC-0101:UT-03 — anotação com ARN fora da regra (conta curta, user em vez de role, com espaço, começando
        com -): "resposta inválida do kubectl" e nenhuma chamada à aws."""
        # SPEC-0101:UT-03
        for arn in ("arn:aws:iam::12345:role/orders-worker-dev", f"arn:aws:iam::{ACCOUNT}:user/orders-worker-dev",
                    f"arn:aws:iam::{ACCOUNT}:role/orders worker", f"-arn:aws:iam::{ACCOUNT}:role/x", "orders-worker"):
            with self.subTest(arn=arn):
                self.kube["objects"]["serviceaccounts/worker"] = sa_object("worker", arn)
                self.install()
                self.assertError(self.run_probe(probe_input()), BAD_KUBECTL)
                self.assertEqual(self.aws_calls(), [])


# --------------------------------------------------------------------------- UT-04


class NothingSensitiveTest(IamCase):
    def test_ok_outputs_carry_no_arn_url_account_profile_or_context(self):
        """SPEC-0101:UT-04 — nas saídas ok de fila, fila sem política e tópico: nada de arn:, https://sqs,
        123456789012, profile nem contexto (conferido em run_probe), e os itens só com as 8 chaves do contrato."""
        # SPEC-0101:UT-04
        for data in (probe_input(), probe_input(rid=BARE_QUEUE), probe_input("topic")):
            with self.subTest(resource=data["target"]["resource"]["id"]):
                self.install()
                out = self.ok(data)
                self.assertTrue(out["items"])
                for item in out["items"]:
                    self.assertEqual(set(item), ITEM_KEYS)
                text = json.dumps(out, ensure_ascii=False)
                for value in ("arn:", "https://sqs", ACCOUNT, PROFILE, CONTEXT):
                    self.assertNotIn(value, text)


# --------------------------------------------------------------------------- UT-05


class AllowListTest(IamCase):
    def test_every_call_is_in_the_list_with_the_counts_of_section_5(self):
        """SPEC-0101:UT-05 — fila: 2 gets do kubectl, 1 get-queue-url, 1 get-queue-attributes, 1 simulação, nenhuma
        sts; tópico: 1 sts, 1 get-topic-attributes, 1 simulação; todo argv com as opções comuns (run_probe)."""
        # SPEC-0101:UT-05
        self.install()
        self.ok(probe_input())
        self.assertEqual(len(self.kube_calls()), 2)
        self.assertEqual(sorted(self.pairs()), sorted([("sqs", "get-queue-url"), ("sqs", "get-queue-attributes"),
                                                       SIMULATE]))
        self.install()
        self.ok(probe_input("topic"))
        self.assertEqual(sorted(self.pairs()), sorted([("sts", "get-caller-identity"),
                                                       ("sns", "get-topic-attributes"), SIMULATE]))

    def test_inherited_aws_credentials_never_reach_the_cli(self):
        """SPEC-0101:UT-05 — com AWS_PROFILE, AWS_DEFAULT_PROFILE, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY e
        AWS_SESSION_TOKEN no ambiente do adaptador, nenhum chega à aws, que recebe AWS_PAGER vazio."""
        # SPEC-0101:UT-05
        self.install()
        self.ok(probe_input())
        rows = self.aws_rows()
        self.assertTrue(rows)
        for row in rows:
            for name in LEAKED:
                self.assertNotIn(name, row["env"])
            self.assertEqual(row["env"].get("AWS_PAGER"), "")

    def test_inputs_out_of_the_rule_are_refused_without_any_call(self):
        """SPEC-0101:UT-05 — verbo attach, workload Secret/x, nome começando com -, profile com espaço, fila com /,
        fila de 81 caracteres, sem attrs.region, região us-east-100 ou US-east-1, stdin probe@1 ou que não é JSON:
        o erro fixo do contrato e nenhum dublê chamado."""
        # SPEC-0101:UT-05
        self.install()
        cases = {
            "verb": (probe_input(verb="attach"), NO_VERB),
            "secret": (probe_input(workloads=("Secret/x",)), INVALID_INPUT),
            "workload-dash": (probe_input(workloads=("Deployment/-worker",)), INVALID_INPUT),
            "name-dash": (probe_input(rid="-orders"), INVALID_INPUT),
            "topic-dash": (probe_input("topic", rid="-events"), INVALID_INPUT),
            "profile-space": (probe_input(profile="acme dev"), INVALID_INPUT),
            "profile-dash": (probe_input(profile="--debug"), INVALID_INPUT),
            "slash": (probe_input(rid="orders/x"), INVALID_INPUT),
            "long": (probe_input(rid="q" * 81), INVALID_INPUT),
            "fifo-long": (probe_input(rid="q" * 76 + ".fifo"), INVALID_INPUT),
            "no-region": (probe_input(attrs={}), NO_REGION),
            "no-region-topic": (probe_input("topic", attrs={"arn": f"arn:aws:sns:{REGION}:{OTHER_ACCOUNT}:x"}),
                                NO_REGION),
            "region-100": (probe_input(attrs={"region": "us-east-100"}), INVALID_INPUT),
            "region-upper": (probe_input(attrs={"region": "US-east-1"}), INVALID_INPUT),
            "probe1": (probe_input(contract="probe@1"), INVALID_INPUT),
        }
        for name, (data, message) in cases.items():
            with self.subTest(case=name):
                self.install()
                out = self.run_probe(None, raw=json.dumps(data))
                self.assertError(out, message)
                self.assertEqual(self.kube_calls(), [], "o kubectl foi chamado")
                self.assertEqual(self.aws_calls(), [], "a aws foi chamada")
        for raw in ("{", "", "[]"):
            with self.subTest(raw=raw):
                self.install()
                self.assertError(self.run_probe(None, raw=raw), INVALID_INPUT)
                self.assertEqual(self.kube_calls() + self.aws_calls(), [])

    def test_a_bucket_is_refused_without_any_call(self):
        """SPEC-0101:UT-05 — recurso de kind bucket (fora de targets): status error ("entrada inválida" ou "chamada
        não permitida") e nenhum dublê chamado."""
        # SPEC-0101:UT-05
        self.install()
        out = self.run_probe(None, raw=json.dumps(probe_input("bucket", rid="orders-files")))
        self.assertEqual((out["status"], out["items"]), ("error", []), out)
        self.assertIn(out.get("message"), (INVALID_INPUT, REFUSED))
        self.assertEqual(self.kube_calls() + self.aws_calls(), [])

    def test_regions_in_the_rule_are_accepted(self):
        """SPEC-0101:UT-05 — us-east-1 e ap-southeast-12 passam da validação e chegam à aws com --region."""
        # SPEC-0101:UT-05
        for region in ("us-east-1", "ap-southeast-12"):
            with self.subTest(region=region):
                self.install()
                self.ok(probe_input(attrs={"region": region}))
                self.assertEqual(set(self.option_of(("sqs", "get-queue-url"), "--region")), {region})

    def test_fifo_names_at_the_limit_are_accepted(self):
        """SPEC-0101:UT-05 — fila de 80 caracteres e fila .fifo de 80 no total passam da validação."""
        # SPEC-0101:UT-05
        for name in ("q" * 80, "q" * 75 + ".fifo"):
            with self.subTest(length=len(name)):
                self.aws["queues"][name] = {}
                self.install()
                self.ok(probe_input(rid=name))
                self.assertEqual(self.option_of(("sqs", "get-queue-url"), "--queue-name"), [name])

    def test_arn_and_url_of_the_atlas_are_ignored(self):
        """SPEC-0101:UT-05 — attrs.arn e attrs.url apontando para outra fila em outra conta: não aparecem em nenhum
        argv; o adaptador usa só o nome e a região."""
        # SPEC-0101:UT-05
        self.install()
        attrs = {"region": REGION, "arn": f"arn:aws:sqs:{REGION}:{OTHER_ACCOUNT}:evil",
                 "url": f"https://sqs.{REGION}.amazonaws.com/{OTHER_ACCOUNT}/evil"}
        self.ok(probe_input(attrs=attrs))
        everything = json.dumps(self.aws_calls() + self.kube_calls())
        self.assertNotIn(OTHER_ACCOUNT, everything)
        self.assertNotIn("evil", everything)

    def test_queue_url_and_arn_out_of_the_rule_stop_before_the_simulation(self):
        """SPEC-0101:UT-05 — QueueUrl com outro host ou outro nome, e QueueArn com outro nome, outra região ou conta
        que não tem 12 dígitos: "resposta inválida da nuvem" e nenhuma simulação."""
        # SPEC-0101:UT-05
        cases = {
            "url-host": {"queue_url": {QUEUE: f"https://sqs.{REGION}.evil.example/{ACCOUNT}/{QUEUE}"}},
            "url-name": {"queue_url": {QUEUE: queue_url("other")}},
            "url-region": {"queue_url": {QUEUE: queue_url(region="eu-west-1")}},
            "arn-name": {"queue_arn": {QUEUE: queue_arn("other")}},
            "arn-region": {"queue_arn": {QUEUE: queue_arn(region="eu-west-1")}},
            "arn-account": {"queue_arn": {QUEUE: f"arn:aws:sqs:{REGION}:12345:{QUEUE}"}},
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                aws = base_aws()
                aws.update(change)
                self.install(aws=aws)
                self.assertError(self.run_probe(probe_input()), BAD_CLOUD)
                self.assertNotIn(SIMULATE, self.pairs())


# --------------------------------------------------------------------------- UT-06


class ErrorTest(IamCase):
    def test_tools_missing_from_the_path(self):
        """SPEC-0101:UT-06 — sem kubectl no PATH: "kubectl não encontrado"; sem aws: "aws não encontrado"."""
        # SPEC-0101:UT-06
        self.install()
        self.assertError(self.run_probe(probe_input(), with_kubectl=False), "kubectl não encontrado")
        self.assertEqual(self.aws_calls(), [])
        self.install()
        self.assertError(self.run_probe(probe_input(), with_aws=False), "aws não encontrado")

    def test_kubectl_failures_become_fixed_messages(self):
        """SPEC-0101:UT-06 — Forbidden, contexto inexistente, timeout, JSON inválido e outro erro do kubectl (no
        workload e na ServiceAccount): a mensagem do contrato, sem o stderr nem o contexto, e nenhuma chamada à
        aws."""
        # SPEC-0101:UT-06
        for mode, message in KUBECTL_ERRORS.items():
            for where in (None, "serviceaccounts"):
                with self.subTest(mode=mode, where=where):
                    kube = base_kube()
                    kube["fail"] = mode
                    if where:
                        kube["fail_on"] = where
                    self.install(kube=kube)
                    self.assertError(self.run_probe(probe_input()), message)
                    self.assertEqual(self.aws_calls(), [])

    def test_aws_failures_become_fixed_messages(self):
        """SPEC-0101:UT-06 — SSO expirado, token expirado, profile inexistente, sem credenciais, timeout, JSON
        inválido e outro erro, em cada operação da fila e do tópico: a mensagem do contrato, items [], sem stderr,
        profile, ARN ou conta."""
        # SPEC-0101:UT-06
        operations = {"queue": [("sqs", "get-queue-url"), ("sqs", "get-queue-attributes"), SIMULATE],
                      "topic": [("sts", "get-caller-identity"), ("sns", "get-topic-attributes"), SIMULATE]}
        for mode, message in AWS_ERRORS.items():
            for kind, pairs in operations.items():
                for service, operation in pairs:
                    with self.subTest(mode=mode, operation=operation):
                        aws = base_aws()
                        aws["fail"] = [{"mode": mode, "service": service, "operation": operation}]
                        self.install(aws=aws)
                        self.assertError(self.run_probe(probe_input(kind)), message)

    def test_simulation_errors(self):
        """SPEC-0101:UT-06 — AccessDenied na simulação: "sem permissão para simular (iam:SimulatePrincipalPolicy)";
        papel inexistente (NoSuchEntity): "resposta inválida da nuvem"."""
        # SPEC-0101:UT-06
        aws = base_aws()
        aws["fail"] = [{"mode": "denied", "service": "iam", "operation": "simulate-principal-policy"}]
        self.install(aws=aws)
        self.assertError(self.run_probe(probe_input()),
                         "sem permissão para simular (iam:SimulatePrincipalPolicy)")
        aws = base_aws()
        aws["roles"] = []
        self.install(aws=aws)
        self.assertError(self.run_probe(probe_input()), BAD_CLOUD)
        aws = base_aws()
        aws["fail"] = [{"mode": "nosuchentity", "service": "iam"}]
        self.install(aws=aws)
        self.assertError(self.run_probe(probe_input("topic")), BAD_CLOUD)


# --------------------------------------------------------------------------- CT-02


class Table4aTest(IamCase):
    def real_outputs(self):
        self.install()
        queue = self.ok(probe_input())
        self.install()
        topic = self.ok(probe_input("topic"))
        aws = base_aws()
        aws["decisions"] = {"sqs:SendMessage": "allowed", "sqs:ReceiveMessage": "explicitDeny",
                            "sqs:DeleteMessage": "implicitDeny"}
        self.install(aws=aws)
        decisions = self.ok(probe_input())
        return queue, topic, decisions

    def test_real_items_follow_table_4a(self):
        """SPEC-0101:CT-02 — os itens reais de fila, tópico e das três decisões cumprem a tabela 4a do ADR-0026:
        action abstrata, api_action não vazia, decision só allowed ou denied (nunca implicitDeny nem explicitDeny)."""
        # SPEC-0101:CT-02
        outs = self.real_outputs()
        for out in outs:
            self.assertEqual(table_4a_problems(out), [], out)
        decisions = {i["decision"] for out in outs for i in out["items"]}
        self.assertEqual(decisions, {"allowed", "denied"})

    def test_the_same_check_refuses_broken_items(self):
        """SPEC-0101:CT-02 — a mesma conferência recusa item com action "sqs:SendMessage", sem api_action e com
        decision "implicitDeny"."""
        # SPEC-0101:CT-02
        queue, _, _ = self.real_outputs()
        for change in ({"action": "sqs:SendMessage"}, {"api_action": None}, {"decision": "implicitDeny"},
                       {"decision": "explicitDeny"}):
            with self.subTest(change=change):
                broken = copy.deepcopy(queue)
                item = broken["items"][0]
                for key, value in change.items():
                    if value is None:
                        del item[key]
                    else:
                        item[key] = value
                self.assertTrue(table_4a_problems(broken))


# --------------------------------------------------------------------------- CT-01

DOC_BLOCK_RE = re.compile(r"```json probe@2 (describe|input|output) (valid|invalid)[ \t]*\n(.*?)```", re.DOTALL)
VALIDATORS = {"describe": "validate_probe_describe", "input": "validate_probe_input",
              "output": "validate_probe_output"}


class ContractTest(IamCase):
    def test_describe_follows_probe_2(self):
        """SPEC-0101:CT-01 — `iam.py --describe` imprime exatamente a descrição do contrato, aceita pelo
        validate_probe_describe do núcleo, sem chamar nenhum dublê."""
        # SPEC-0101:CT-01
        self.install()
        result = self.adapter("--describe")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(data, DESCRIBE)
        self.assertEqual(f("validate_probe_describe")(data), [])
        self.assertEqual(self.kube_calls() + self.aws_calls(), [])

    def test_real_inputs_and_outputs_pass_the_core_validators(self):
        """SPEC-0101:CT-01 — as entradas usadas passam no validate_probe_input; as saídas reais do UT-01 (fila e
        tópico), do UT-03 (Pod Identity) e do UT-06 (login) passam no validate_probe_output (run_probe)."""
        # SPEC-0101:CT-01
        no_irsa = base_kube()
        no_irsa["objects"]["serviceaccounts/worker"] = sa_object("worker", None)
        login = base_aws()
        login["fail"] = [{"mode": "sso-expired"}]
        cases = [("queue", None, None, "ok"), ("topic", None, None, "ok"), ("queue", no_irsa, None, "error"),
                 ("topic", None, login, "error")]
        for kind, kube, aws, status in cases:
            with self.subTest(kind=kind, status=status):
                data = probe_input(kind)
                self.assertEqual(f("validate_probe_input")(data), [])
                self.install(kube=kube, aws=aws)
                self.assertEqual(self.run_probe(data)["status"], status)

    def test_examples_of_the_reference(self):
        """SPEC-0101:CT-01 — references/probes/iam.md traz blocos ```json probe@2 <describe|output> <valid|invalid>:
        describe válido; saída ok de fila (sqs:), saída ok de tópico (sns:), saída de erro; describe com access
        ["database"] inválido; ao menos 2 saídas inválidas (item aninhado, chave fora do contrato); os válidos passam
        e os inválidos são recusados com motivo; nenhum bloco válido com conta, ARN ou URL da AWS."""
        # SPEC-0101:CT-01
        self.assertTrue(REFERENCE.is_file(), f"{REFERENCE.relative_to(SKILL)} não existe ({SPEC})")
        text = REFERENCE.read_text(encoding="utf-8")
        blocks = [(m.group(1), m.group(2), json.loads(m.group(3))) for m in DOC_BLOCK_RE.finditer(text)]
        valid_describe = [b[2] for b in blocks if b[:2] == ("describe", "valid")]
        self.assertTrue(valid_describe, "sem bloco describe valid")
        valid_out = [b[2] for b in blocks if b[:2] == ("output", "valid")]

        def apis(out):
            return [str(i.get("api_action", "")) for i in out.get("items") or [] if isinstance(i, dict)]

        self.assertTrue([o for o in valid_out if o.get("status") == "ok" and any(a.startswith("sqs:") for a in apis(o))],
                        "sem saída ok de fila")
        self.assertTrue([o for o in valid_out if o.get("status") == "ok" and any(a.startswith("sns:") for a in apis(o))],
                        "sem saída ok de tópico")
        self.assertTrue([o for o in valid_out if o.get("status") == "error"], "sem saída de erro")
        invalid_describe = [b[2] for b in blocks if b[:2] == ("describe", "invalid")]
        self.assertTrue([d for d in invalid_describe if "database" in json.dumps(d)],
                        "sem describe inválido com access database")
        self.assertGreaterEqual(len([b for b in blocks if b[:2] == ("output", "invalid")]), 2,
                                "menos de 2 blocos output invalid")
        for kind, verdict, data in blocks:
            with self.subTest(kind=kind, verdict=verdict, data=json.dumps(data)[:80]):
                problems = f(VALIDATORS[kind])(data)
                if verdict == "valid":
                    self.assertEqual(problems, [])
                else:
                    self.assertTrue(problems and all(isinstance(p, str) and p for p in problems), problems)
        for out in valid_out:
            if out.get("status") == "ok":
                self.assertEqual(table_4a_problems(out), [], out)
        for value in (ACCOUNT, "arn:aws", "amazonaws.com"):
            self.assertNotIn(value, "\n".join(json.dumps(b[2]) for b in blocks if b[1] == "valid"))


# --------------------------------------------------------------------------- IT-01 e IT-02


class EndToEndTest(unittest.TestCase):
    """Atlas temporário (cópia de fixtures/probe-resource/atlas, com service:orders-worker, o deployment
    dev-orders-worker em environment:dev e cluster-dev, consumes queue:orders e publishes topic:orders-events, só com
    region nos atributos), access.clusters e access.cloud.dev.profile, o adaptador iam sem command e os dublês de
    kubectl e aws no início do PATH."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        shutil.copytree(ATLAS_FIXTURE, self.box.atlas)
        graph_path = self.box.atlas / "graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        template = next(n for n in graph["nodes"] if n["key"] == "service:worker")
        queue = next(n for n in graph["nodes"] if n["key"] == "queue:orders")
        queue["attrs"] = {"region": REGION}
        topic = copy.deepcopy(next(n for n in graph["nodes"] if n["key"] == "topic:events"))
        topic.update(key=f"topic:{TOPIC}", name=TOPIC, attrs={"region": REGION})
        service = copy.deepcopy(template)
        service.update(key="service:orders-worker", name="orders-worker", attrs={})
        deployment = copy.deepcopy(next(n for n in graph["nodes"] if n["key"] == "deployment:dev-worker"))
        deployment.update(key="deployment:dev-orders-worker", name="dev-orders-worker",
                          attrs={"config_refs": [], "namespace": NAMESPACE, "workloads": ["Deployment/worker"]})
        graph["nodes"] += [topic, service, deployment]

        def edge(source, target, kind):
            return {"from": source, "inferred": False, "sources": ["facts"], "to": target, "type": kind}

        graph["edges"] += [edge("deployment:dev-orders-worker", "service:orders-worker", "deploys"),
                           edge("deployment:dev-orders-worker", "cluster:cluster-dev", "runs_in"),
                           edge("deployment:dev-orders-worker", "environment:dev", "runs_in"),
                           edge("deployment:dev-orders-worker", "queue:orders", "consumes"),
                           edge("deployment:dev-orders-worker", f"topic:{TOPIC}", "publishes")]
        graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        adapter = '    iam:\n      verbs: ["simulate"]\n      timeout: 120\n'
        access = (f"access:\n  clusters:\n    \"cluster-dev\": {{context: {json.dumps(CONTEXT)}}}\n"
                  f"  cloud:\n    \"dev\": {{profile: {json.dumps(PROFILE)}}}\n")
        local = f"atlas: {json.dumps(str(self.box.atlas))}\ncredentials: {{}}\n" + access + probes_yaml([adapter])
        self.box.write_local(local)
        self.bin = self.box.root / "bin"
        self.kube_record = self.box.root / "kubectl-calls.jsonl"
        self.aws_record = self.box.root / "aws-calls.jsonl"
        self.log_path = self.box.config_home / "probes.log"

    def install(self, aws=None):
        self.kube_record.unlink(missing_ok=True)
        self.aws_record.unlink(missing_ok=True)
        install_fake(FAKE_KUBECTL, self.bin, "kubectl", "fake-kubectl.json", base_kube(), self.kube_record)
        install_fake(FAKE_AWS, self.bin, "aws", "fake-aws.json", aws or base_aws(), self.aws_record)

    def probe(self, resource):
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        result = self.box.run("probe", "permissions", "simulate", "--service", "orders-worker", "--env", "dev",
                              "--resource", resource, "--json", env=env)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def log_text(self):
        return self.log_path.read_text(encoding="utf-8") if self.log_path.exists() else ""

    def assertCallsInTheList(self):
        kube = [row["argv"] for row in read_rows(self.kube_record)]
        aws = [row["argv"] for row in read_rows(self.aws_record)]
        self.assertTrue(kube, "o kubectl falso não foi chamado")
        self.assertTrue(aws, "a aws falsa não foi chamada")
        for argv in kube:
            self.assertEqual(kube_call_problems(argv, CONTEXT, NAMESPACE), [], argv)
        for argv in aws:
            self.assertEqual(aws_call_problems(argv, REGION, PROFILE), [], argv)
        return aws

    def assertNothingSensitive(self, *texts):
        everything = "\n".join(texts)
        for value in (PROFILE, CONTEXT, "arn:", ACCOUNT, SENTINEL):
            self.assertNotIn(value, everything, f"{value} apareceu na saída ou no probes.log")

    def test_queue_through_the_core(self):
        """SPEC-0101:IT-01 — `atlas.py probe permissions simulate --service orders-worker --env dev --resource
        queue:orders --json` como processo: exit 0, saída validada pelo núcleo com os itens do UT-01, os dublês só
        com chamadas da lista fechada com o profile e o contexto da configuração; nem a saída nem o probes.log com
        profile, contexto, arn: ou 123456789012."""
        # SPEC-0101:IT-01
        self.install()
        result = self.probe("queue:orders")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(data), [], data)
        self.assertEqual((data["adapter"], data["capability"], data["verb"], data["status"]),
                         ("iam", "permissions", "simulate", "ok"))
        self.assertEqual(data["items"], expected_items())
        self.assertCallsInTheList()
        self.assertNothingSensitive(output(result), self.log_text())
        lines = [json.loads(line) for line in self.log_text().splitlines() if line.strip()]
        self.assertEqual([(line.get("resource"), line.get("status"), line.get("adapter")) for line in lines],
                         [("queue:orders", "ok", "iam")])

    def test_topic_and_unreadable_policy_through_the_core(self):
        """SPEC-0101:IT-02 — `... --resource topic:orders-events`: exit 0 e o item sns:Publish; com a leitura da
        política do tópico negada: exit 1, "não foi possível ler a política do recurso", nenhum item allowed e
        nenhuma simulação registrada."""
        # SPEC-0101:IT-02
        self.install()
        result = self.probe(f"topic:{TOPIC}")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(data), [], data)
        self.assertEqual(data["items"], expected_items(actions=TOPIC_ACTIONS))
        self.assertCallsInTheList()
        aws = base_aws()
        aws["fail"] = [{"mode": "denied", "service": "sns", "operation": "get-topic-attributes"}]
        self.install(aws)
        failed = self.probe(f"topic:{TOPIC}")
        self.assertEqual(failed.returncode, 1, output(failed))
        data = json.loads(failed.stdout)
        self.assertEqual(data["status"], "error", data)
        self.assertIn(NO_POLICY, data.get("message", ""))
        self.assertFalse([i for i in data.get("items") or [] if i.get("decision") == "allowed"])
        calls = self.assertCallsInTheList()
        self.assertNotIn(SIMULATE, [tuple(parse_aws(a)[0][:2]) for a in calls])
        self.assertNothingSensitive(output(result), output(failed), self.log_text())


if __name__ == "__main__":
    unittest.main()
