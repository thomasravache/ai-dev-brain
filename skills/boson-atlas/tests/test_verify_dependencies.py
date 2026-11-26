"""verify@2: dependências e sinais na foto e na comparação (SPEC-0102: CH-01, UT-01 a UT-11, IT-01, CT-01 e CT-02;
ADR-0026, ADR-0025, ADR-0024; sobre o núcleo do probe, SPEC-0088, e o alvo de recurso, SPEC-0096).

Contrato (seção 6 da SPEC-0102) que estes testes fixam:

    atlas.py verify snapshot ... [--resource <kind:id>]... [--max-resources 20]
        grava {"contract": "verify@2", ..., "deployments": {...verify@1...}, "dependencies": {"<kind:id>": {
        "deployment", "relations", "dlq_of", ["queue" | "subscriptions" | "migrations" | "tables" | "signals" |
        "permissions"]}}, "not_verified": [... {"deployment", "resource", "check", "reason"}]}
    atlas.py verify compare ... [--resource <kind:id>]... [--max-resources 20] [--max-new-dlq 0]
        [--max-queue-age 10m] [--expect-migration [<datastore>=]<migration>]... [--max-signal-increase 0.5]
        verificações por recurso: dependencies e signals, com "resource": "<kind:id>"; as de deployment com
        "resource": null; --json {"contract": "verify@2", "verdict", "checks", "suggestion"}

Leituras desta suíte (listadas no relatório do test-writer):
    - Os motivos fixos do contrato ("DLQ sem leitura agora", "ação receive não simulada", "permissão já negada antes do
      deploy", "probe de subscriptions cortada", "item fora do contrato de <capacidade> <verbo>: <campo>"...) são
      procurados no `reason` da verificação ou na evidência (evidence.not_verified), nunca só num dos dois.
    - "Sem adaptador": o motivo traz "nenhum adaptador para <capacidade>" (o texto do núcleo, como no exemplo 6.4).
    - Um `datastore` ligado por `config_refs` tem relations ["depends_on"] (seção 6.1 e o exemplo 6.4); a relação de
      um recurso ligado por dois deployments é conferida como conjunto.
    - A foto só é conferida aspecto a aspecto; o `permissions` da foto guarda as ações que o adaptador devolveu (o
      roteiro devolve só as exigidas pela relação).
    - UT-09 usa uma foto verify@1 do serviço orders montada no teste (o exemplo do references/verify.md é do api).
    - CT-02: um bloco `json verify-items <capacidade> <verbo> <valid|invalid>` é a lista de itens (ou um objeto com
      "items"); o inválido deixa o aspecto fora da foto e um not_verified com "item fora do contrato de <capacidade>
      <verbo>: <campo do contrato>" (ou, para messaging queue, "resposta de messaging queue com <n> item(ns)", ou
      "métrica repetida").
    - Toda execução confere: sem traceback, sem "unrecognized arguments" (a opção nova existe), a pasta do atlas
      igual, só verbos de leitura nos dois adaptadores falsos e nenhum valor de acesso local na saída nem no
      probes.log.

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); atlas e graph.json temporários;
nenhum aws, psql nem kubectl de verdade (os adaptadores são fixtures/fake-probes/scripted.py e scripted_resources.py;
no IT-01 o PATH começa por dublês que só registram e falham); nomes genéricos (acme, orders) e a conta de exemplo
123456789012, que precisa sair mascarada.
"""
import copy
import json
import os
import re
import shutil
import stat
import sys
import unittest
from typing import ClassVar

from helpers import SKILL, TESTS, Sandbox, atlas, fn, output, snapshot
from test_probe import adapter_yaml, probes_yaml
from test_probe_resource import access_text
from test_verify import COMMAND_RE, VerifyCase, baseline_data, deployment_state
from test_verify import DEPLOYMENTS as API_DEPLOYMENTS
from test_verify import OLD_IMAGE as API_OLD_IMAGE
from test_verify import PODS as API_PODS

SPEC = "SPEC-0102"
FAKES = TESTS / "fixtures" / "fake-probes"
SCRIPTED = FAKES / "scripted.py"
RESOURCES = FAKES / "scripted_resources.py"
FIXTURE = TESTS / "fixtures" / "probe-resource" / "atlas"
VERIFY_DOC = SKILL / "references" / "verify.md"

# sentinelas de acesso local (nunca saem em nada)
PROFILE = "acme-dev-read-0102"
PROD_PROFILE = "acme-prod-read-0102"
DB_USER = "ro_user_0102"
DB_NAME = "ordersdb0102"
CONTEXT_DEV = "ctx-local-dev-0102"
CONTEXT_PROD = "ctx-local-prod-0102"
PASSFILE_NAME = ".pgpass-0102"
ACCOUNT = "123456789012"

OLD_IMAGE = "acme/orders:2.0.1"
NEW_IMAGE = "acme/orders:2.0.2"
TS = "2026-11-24T09:00:00Z"
RUNTIME_VERBS = {"status", "events", "logs"}
RESOURCE_VERBS = ("queue", "subscriptions", "migrations", "tables", "metrics", "simulate")
RESOURCE_CAPABILITIES = {"messaging", "database", "signals", "permissions"}
DEPLOYMENT_CHECKS = ("delivery", "runtime", "logs")
RESOURCE_CHECKS = ("dependencies", "signals")
STATUSES = ("ok", "failed", "not_verified")
VERDICT_EXIT = {"passou": 0, "degradou": 1, "inconclusivo": 5}
RESOURCE_RE = re.compile(r"^(queue|topic|datastore):[A-Za-z0-9][A-Za-z0-9._-]*$")
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$")

NO_BASELINE = "sem foto de antes: dependências e sinais não se comparam"
OLD_BASELINE = "foto sem dependências"
OUT_OF_PHOTO = "recurso fora da foto"
NO_ADAPTER = "nenhum adaptador para"
BAD_RESOURCE = "--resource inválido — use <kind>:<id> com kind queue, topic ou datastore"
BAD_MAX = "--max-resources inválido — use um inteiro de 1 a 50"
TOO_MANY = "mais recursos em --resource que --max-resources"
BAD_INCREASE = "--max-signal-increase inválido — use um decimal de 0 a 100 (0.5 = 50%)"

# deployment -> (ambiente, cluster, workload)
ORDERS_DEPLOYMENTS = {"dev-orders": ("dev", "cluster-dev", "Deployment/orders"),
                      "dev-orders-worker": ("dev", "cluster-dev", "Deployment/orders-worker"),
                      "prod-orders": ("prod", "cluster-prod", "Deployment/orders")}
DEV_DEPLOYMENTS = ("dev-orders", "dev-orders-worker")

SUB_A_RAW = f"arn:aws:sqs:us-east-1:{ACCOUNT}:orders-audit"
SUB_A = "arn:aws:sqs:us-east-1:[REDACTED]:orders-audit"
SUB_B = "queue:orders-billing"
SUB_C = "queue:orders-search"
API_ACTIONS = {"publish": "sns:Publish", "send": "sqs:SendMessage", "receive": "sqs:ReceiveMessage",
               "delete": "sqs:DeleteMessage"}


def f(name):
    return fn(name, SPEC)


# --------------------------------------------------------------------------- grafo do atlas temporário


def node(key, **attrs):
    kind, name = key.split(":", 1)
    return {"key": key, "kind": kind, "name": name, "attrs": attrs, "conflicts": [], "seen_at": "2026-11-24",
            "sources": ["facts"]}


def edge(source, kind, target):
    return {"from": source, "to": target, "type": kind, "inferred": False, "sources": ["facts"]}


def orders_graph(minimal=False, extra_out=False):
    """O serviço orders: dev-orders e dev-orders-worker em dev (tier test), prod-orders em prod (production).
    dev-orders: consumes queue:orders (dlq orders-dlq), publishes topic:orders-events, depends_on
    datastore:orders-cache (valkey), writes bucket:orders-files e, por config_refs, datastore:orders-db (postgres);
    dev-orders-worker: publishes topic:orders-events (e queue:orders-out com extra_out); prod-orders: consumes
    queue:orders. queue:outra existe e não é ligada. minimal: só dev-orders com queue:orders e a DLQ (IT-01)."""
    nodes = [node("service:orders"), node("environment:dev"), node("environment:prod"), node("cluster:cluster-dev"),
             node("cluster:cluster-prod"), node("repository:acme/iac", default_branch="main"),
             node("queue:orders", region="us-east-1", dlq="orders-dlq"), node("queue:orders-dlq", region="us-east-1")]
    edges = []
    deployments = ("dev-orders",) if minimal else tuple(ORDERS_DEPLOYMENTS)
    for deployment in deployments:
        env, cluster, workload = ORDERS_DEPLOYMENTS[deployment]
        refs = ["DB_URL=orders-db.interno"] if deployment == "dev-orders" and not minimal else []
        nodes.append(node(f"deployment:{deployment}", config_refs=refs, images=["acme/orders"],
                          namespace=f"orders-{env}", workloads=[workload]))
        key = f"deployment:{deployment}"
        edges += [edge(key, "deploys", "service:orders"), edge(key, "runs_in", f"environment:{env}"),
                  edge(key, "runs_in", f"cluster:{cluster}"), edge(key, "sourced_from", "repository:acme/iac")]
    edges.append(edge("deployment:dev-orders", "consumes", "queue:orders"))
    if not minimal:
        nodes += [node("queue:outra", region="us-east-1"), node("topic:orders-events", region="us-east-1"),
                  node("datastore:orders-db", engine="postgres", host="orders-db.interno", region="us-east-1"),
                  node("datastore:orders-cache", engine="valkey", host="orders-cache.interno"),
                  node("bucket:orders-files", region="us-east-1")]
        edges += [edge("deployment:dev-orders", "publishes", "topic:orders-events"),
                  edge("deployment:dev-orders", "depends_on", "datastore:orders-cache"),
                  edge("deployment:dev-orders", "writes", "bucket:orders-files"),
                  edge("deployment:dev-orders-worker", "publishes", "topic:orders-events"),
                  edge("deployment:prod-orders", "consumes", "queue:orders")]
        if extra_out:
            nodes.append(node("queue:orders-out", region="us-east-1"))
            edges.append(edge("deployment:dev-orders-worker", "publishes", "queue:orders-out"))
    return {"version": 1, "organization": "Acme", "built_at": "2026-11-24", "nodes": nodes, "edges": edges}


ATLAS_CONFIG = ("version: 1\norganization: Acme\nmode: local\nlanguage: auto\nstale_days: 14\n"
                "categories: [code, delivery]\ncollectors: []\nredaction: {extra_patterns: []}\n"
                "environments:\n  dev: {tier: test}\n  prod: {tier: production}\n")


# --------------------------------------------------------------------------- estados dos adaptadores falsos


def answer(items, truncated=False):
    return {"items": copy.deepcopy(list(items)), "truncated": truncated}


def metric(name, stat_, value, kind):
    return {"name": name, "stat": stat_, "value": value, "kind": kind}


def perms(**decisions):
    return [{"action": a, "api_action": API_ACTIONS[a], "decision": d} for a, d in decisions.items()]


def photo_signals(window, metrics):
    return {"window_seconds": window,
            "metrics": {f"{m['name']}|{m['stat']}": {"kind": m["kind"], "value": m["value"]} for m in metrics}}


QUEUE = {"visible": 3, "in_flight": 1, "oldest_age_seconds": 40, "dlq_visible": 0}
DLQ_QUEUE = {"visible": 0, "in_flight": 0, "oldest_age_seconds": None, "dlq_visible": None}
OUT_QUEUE = {"visible": 0, "in_flight": 0, "oldest_age_seconds": None, "dlq_visible": None}
# a foto tem janela de 1800 s (--since 30m) e o compare de 600 s (--window 10m): sum/count por minuto iguais
QUEUE_METRICS_BASE = [metric("Errors", "sum", 30, "error"), metric("Latency", "p95", 200, "latency"),
                      metric("Depth", "max", 10, "saturation"), metric("Sent", "sum", 900, "traffic")]
QUEUE_METRICS_NOW = [metric("Errors", "sum", 10, "error"), metric("Latency", "p95", 200, "latency"),
                     metric("Depth", "max", 10, "saturation"), metric("Sent", "sum", 300, "traffic")]
TOPIC_METRICS = [metric("NumberOfNotificationsFailed", "sum", 0, "error"),
                 metric("NumberOfMessagesPublished", "sum", 100, "traffic")]
DB_METRICS = [metric("ReadLatency", "avg", 0.004, "latency"), metric("DatabaseConnections", "max", 12, "saturation")]
CACHE_METRICS = [metric("CacheLatency", "p99", 2.5, "latency")]
DLQ_METRICS = [metric("ApproximateAgeOfOldestMessage", "max", 5, "latency")]
OUT_METRICS = [metric("SendLatency", "p95", 50, "latency")]
SUBSCRIPTIONS_NOW = [{"destination": SUB_A_RAW, "filter_fingerprint": "fp-1a2b"},
                     {"destination": SUB_B, "filter_fingerprint": None}]
SUBSCRIPTIONS_PHOTO = [{"destination": SUB_A, "filter_fingerprint": "fp-1a2b"},
                       {"destination": SUB_B, "filter_fingerprint": None}]


def resources_now():
    """O "depois" que segue a foto padrão (baseline_dependencies): o compare dá ok em tudo."""
    return {
        "queue:orders": {"queue": answer([QUEUE]), "metrics": answer(QUEUE_METRICS_NOW),
                         "simulate": answer(perms(receive="allowed", delete="allowed"))},
        "queue:orders-dlq": {"queue": answer([DLQ_QUEUE]), "metrics": answer(DLQ_METRICS)},
        "queue:orders-out": {"queue": answer([OUT_QUEUE]), "metrics": answer(OUT_METRICS),
                             "simulate": answer(perms(send="allowed"))},
        "topic:orders-events": {"subscriptions": answer(SUBSCRIPTIONS_NOW), "metrics": answer(TOPIC_METRICS),
                                "simulate": answer(perms(publish="allowed"))},
        "datastore:orders-db": {"migrations": answer([{"id": "m1", "success": True}]),
                                "tables": answer([{"name": "public.orders"}, {"name": "public.items"}]),
                                "metrics": answer(DB_METRICS)},
        "datastore:orders-cache": {"metrics": answer(CACHE_METRICS)},
    }


def baseline_dependencies():
    return {
        "datastore:orders-cache": {"deployment": "dev-orders", "relations": ["depends_on"], "dlq_of": None,
                                   "signals": photo_signals(1800, CACHE_METRICS)},
        "datastore:orders-db": {"deployment": "dev-orders", "relations": ["depends_on"], "dlq_of": None,
                                "migrations": ["m1"], "tables": ["public.items", "public.orders"],
                                "signals": photo_signals(1800, DB_METRICS)},
        "queue:orders": {"deployment": "dev-orders", "relations": ["consumes"], "dlq_of": None,
                         "queue": dict(QUEUE), "signals": photo_signals(1800, QUEUE_METRICS_BASE),
                         "permissions": {"receive": "allowed", "delete": "allowed"}},
        "queue:orders-dlq": {"deployment": "dev-orders", "relations": [], "dlq_of": "queue:orders",
                             "queue": dict(DLQ_QUEUE), "signals": photo_signals(1800, DLQ_METRICS)},
        "topic:orders-events": {"deployment": "dev-orders", "relations": ["publishes"], "dlq_of": None,
                                "subscriptions": copy.deepcopy(SUBSCRIPTIONS_PHOTO),
                                "signals": photo_signals(1800, TOPIC_METRICS),
                                "permissions": {"publish": "allowed"}},
    }


def pods_of(deployment):
    name = ORDERS_DEPLOYMENTS[deployment][2].split("/", 1)[1]
    return [f"{name}-6b7c-aaaa", f"{name}-6b7c-bbbb"]


def runtime_state(deployment, image=NEW_IMAGE):
    workload = ORDERS_DEPLOYMENTS[deployment][2]
    pods = pods_of(deployment)
    items = [{"kind": "workload", "workload": workload, "found": True, "desired": 2, "updated": 2, "ready": 2,
              "available": 2, "rollout_complete": True}]
    items += [{"kind": "pod", "workload": workload, "pod": pod, "phase": "Running", "ready": True, "restarts": 0,
               "images": [image], "last_termination": ""} for pod in pods]
    logs = [{"workload": workload, "pod": pods[0], "container": "orders", "ts": TS, "line": "INFO request 1 ok"}]
    return {"status": answer(items), "events": answer([]), "logs": answer(logs)}


def runtime_entry(deployment, image=OLD_IMAGE):
    return {"images": [image], "ready": 2, "desired": 2, "restarts": {pod: 0 for pod in pods_of(deployment)},
            "warnings": [], "error_signatures": {}}


def baseline2(dependencies=None, deployments=DEV_DEPLOYMENTS, not_verified=(), environment="dev"):
    """Foto verify@2 do serviço orders: os deployments saudáveis com a imagem antiga e as dependências."""
    return {"contract": "verify@2", "service": "orders", "environment": environment, "taken_at": TS,
            "deployments": {d: runtime_entry(d) for d in deployments},
            "dependencies": baseline_dependencies() if dependencies is None else dependencies,
            "not_verified": list(not_verified)}


def baseline1(deployments=DEV_DEPLOYMENTS):
    return {"contract": "verify@1", "service": "orders", "environment": "dev", "taken_at": TS,
            "deployments": {d: runtime_entry(d) for d in deployments}, "not_verified": []}


def with_dep(base, resource, **fields):
    """A foto `base` com os campos do recurso trocados."""
    data = copy.deepcopy(base)
    data["dependencies"][resource].update(copy.deepcopy(fields))
    return data


# --------------------------------------------------------------------------- validadores verify@2 da suíte


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_text(value):
    return isinstance(value, str) and bool(value)


DEP_BASE_KEYS = {"deployment", "relations", "dlq_of"}
DEP_ASPECT_KEYS = {"queue", "subscriptions", "migrations", "tables", "signals", "permissions"}
QUEUE_KEYS = {"visible", "in_flight", "oldest_age_seconds", "dlq_visible"}
SNAPSHOT2_KEYS = {"contract", "service", "environment", "taken_at", "deployments", "dependencies", "not_verified"}
RESULT_KEYS = {"contract", "verdict", "checks", "suggestion"}
CHECK2_KEYS = {"deployment", "resource", "check", "status", "evidence", "reason"}


def dependency_problems(key, entry):
    where = f"dependencies.{key}"
    if not RESOURCE_RE.match(key):
        return [f"{where}: chave fora de <kind:id>"]
    if not isinstance(entry, dict) or not DEP_BASE_KEYS <= set(entry) <= DEP_BASE_KEYS | DEP_ASPECT_KEYS:
        return [f"{where}: chaves {sorted(entry) if isinstance(entry, dict) else entry}"]
    problems = []
    if not _is_text(entry["deployment"]):
        problems.append(f"{where}.deployment")
    if not isinstance(entry["relations"], list) or not all(_is_text(r) for r in entry["relations"]):
        problems.append(f"{where}.relations")
    if entry["dlq_of"] is not None and not (_is_text(entry["dlq_of"]) and RESOURCE_RE.match(entry["dlq_of"])):
        problems.append(f"{where}.dlq_of")
    if "queue" in entry:
        queue = entry["queue"]
        if not isinstance(queue, dict) or set(queue) != QUEUE_KEYS or not all(
                queue[k] is None or (_is_int(queue[k]) and queue[k] >= 0) for k in QUEUE_KEYS):
            problems.append(f"{where}.queue")
    if "subscriptions" in entry:
        subs = entry["subscriptions"]
        if not isinstance(subs, list) or not all(
                isinstance(s, dict) and set(s) == {"destination", "filter_fingerprint"} and _is_text(s["destination"])
                and (s["filter_fingerprint"] is None or _is_text(s["filter_fingerprint"])) for s in subs):
            problems.append(f"{where}.subscriptions")
    for aspect in ("migrations", "tables"):
        if aspect in entry:
            value = entry[aspect]
            if not isinstance(value, list) or not all(_is_text(v) for v in value) or value != sorted(value):
                problems.append(f"{where}.{aspect} (lista de textos ordenada)")
    if "signals" in entry:
        sig = entry["signals"]
        if not isinstance(sig, dict) or set(sig) != {"window_seconds", "metrics"} or not _is_int(
                sig.get("window_seconds")) or not isinstance(sig.get("metrics"), dict):
            problems.append(f"{where}.signals")
        else:
            for name, value in sig["metrics"].items():
                if "|" not in name or not isinstance(value, dict) or set(value) != {"kind", "value"} \
                        or value["kind"] not in ("error", "latency", "saturation", "traffic"):
                    problems.append(f"{where}.signals.metrics.{name}")
    if "permissions" in entry:
        value = entry["permissions"]
        if not isinstance(value, dict) or not all(v in ("allowed", "denied") for v in value.values()):
            problems.append(f"{where}.permissions")
    return problems


def snapshot2_problems(data) -> list:
    """Problemas de uma foto frente ao contrato verify@2 (seção 6.4 da SPEC-0102); [] = válida."""
    if not isinstance(data, dict):
        return ["a foto não é um objeto"]
    problems = []
    if set(data) != SNAPSHOT2_KEYS:
        problems.append(f"chaves {sorted(data)} != {sorted(SNAPSHOT2_KEYS)}")
    if data.get("contract") != "verify@2":
        problems.append(f"contract {data.get('contract')!r}")
    if not isinstance(data.get("taken_at"), str) or not ISO_UTC.match(data.get("taken_at")):
        problems.append("taken_at")
    if not isinstance(data.get("deployments"), dict):
        problems.append("deployments")
    dependencies = data.get("dependencies")
    if not isinstance(dependencies, dict):
        problems.append("dependencies não é um objeto")
        dependencies = {}
    for key, entry in dependencies.items():
        problems += dependency_problems(key, entry)
    for item in data.get("not_verified") if isinstance(data.get("not_verified"), list) else [None]:
        if not isinstance(item, dict):
            problems.append(f"not_verified: {item!r}")
        elif set(item) == {"deployment", "check", "reason"}:
            if item["check"] not in DEPLOYMENT_CHECKS or not _is_text(item["reason"]):
                problems.append(f"not_verified: {item!r}")
        elif set(item) == {"deployment", "resource", "check", "reason"}:
            if item["check"] not in RESOURCE_CHECKS or not _is_text(item["reason"]) \
                    or not RESOURCE_RE.match(str(item["resource"])):
                problems.append(f"not_verified: {item!r}")
        else:
            problems.append(f"not_verified com chaves erradas: {item!r}")
    return problems


def result2_problems(data) -> list:
    """Problemas de uma saída `verify compare --json` frente ao contrato verify@2 (seção 6.5); [] = válida."""
    if not isinstance(data, dict):
        return ["a saída não é um objeto"]
    problems = []
    if not {"contract", "verdict", "checks"} <= set(data) <= RESULT_KEYS:
        problems.append(f"chaves {sorted(data)}")
    if data.get("contract") != "verify@2":
        problems.append(f"contract {data.get('contract')!r}")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        return problems + ["checks não é uma lista com itens"]
    for item in checks:
        if not isinstance(item, dict) or not {"deployment", "resource", "check", "status", "evidence"} <= set(item) \
                <= CHECK2_KEYS:
            problems.append(f"check com chaves erradas: {item!r}")
            continue
        if item["status"] not in STATUSES or not isinstance(item["evidence"], dict):
            problems.append(f"status ou evidence fora do contrato: {item!r}")
        if item["check"] in DEPLOYMENT_CHECKS:
            if item["resource"] is not None:
                problems.append(f"resource não nulo numa verificação de deployment: {item!r}")
        elif item["check"] in RESOURCE_CHECKS:
            if not (isinstance(item["resource"], str) and RESOURCE_RE.match(item["resource"])):
                problems.append(f"resource fora de <kind:id>: {item!r}")
        else:
            problems.append(f"check fora do contrato: {item!r}")
        if item["status"] == "not_verified" and not _is_text(item.get("reason")):
            problems.append(f"not_verified sem motivo: {item!r}")
    statuses = {item.get("status") for item in checks if isinstance(item, dict)}
    expected = "degradou" if "failed" in statuses else "inconclusivo" if "not_verified" in statuses else "passou"
    if data.get("verdict") != expected:
        problems.append(f"verdict {data.get('verdict')!r} fora da regra (esperado {expected})")
    suggestion = data.get("suggestion")
    if expected == "degradou":
        if not _is_text(suggestion) or COMMAND_RE.search(suggestion):
            problems.append(f"sugestão de degradou vazia ou com comando: {suggestion!r}")
    elif suggestion not in (None, ""):
        problems.append(f"suggestion fora de degradou: {suggestion!r}")
    return problems


# --------------------------------------------------------------------------- caso base


class DepsCase(unittest.TestCase):
    """Um atlas temporário por classe (o verify nunca escreve no atlas): o grafo de orders_graph(**GRAPH). Cada teste
    tem a própria configuração local, os próprios cenários dos dois adaptadores falsos, os próprios registros de
    processos e a própria pasta da tarefa."""

    GRAPH: ClassVar[dict] = {}

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox()
        try:
            shutil.copytree(FIXTURE, cls.box.atlas)
            (cls.box.atlas / "graph.json").write_text(json.dumps(orders_graph(**cls.GRAPH), indent=2),
                                                      encoding="utf-8")
            (cls.box.atlas / "atlas-config.yml").write_text(ATLAS_CONFIG, encoding="utf-8")
            secrets = cls.box.root / "secrets"
            secrets.mkdir()
            cls.passfile = secrets / PASSFILE_NAME
            cls.passfile.write_text("*:*:ordersdb0102:ro_user_0102:senha-falsa-0102\n", encoding="utf-8")
            os.chmod(cls.passfile, 0o600)
        except BaseException:
            cls.box.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.box.cleanup()

    def setUp(self):
        name = self.id().rsplit(".", 1)[-1]
        base = self.box.root / "t" / name
        if base.exists():
            shutil.rmtree(base)
        base.mkdir(parents=True)
        self.cfg = base / "cfg"
        self.task = base / "task"
        self.task.mkdir()
        self.rt_record = base / "runtime.jsonl"
        self.res_record = base / "resources.jsonl"
        self.v1_record = base / "probe1-resources.jsonl"
        self.rt_scenario = base / "runtime-scenario.json"
        self.res_scenario = base / "resources-scenario.json"
        self.describe = base / "describe.json"
        self.set_runtime()
        self.set_resources()
        self.configure()

    # -- configuração e estado

    def access(self, cloud=True, databases=True):
        data = {"clusters": {"cluster-dev": {"context": CONTEXT_DEV}, "cluster-prod": {"context": CONTEXT_PROD}}}
        if cloud:
            data["cloud"] = {"dev": {"profile": PROFILE}, "prod": {"profile": PROD_PROFILE}}
        if databases:
            data["databases"] = {"orders-db": {"user": DB_USER, "database": DB_NAME, "passfile": str(self.passfile)}}
        return data

    def configure(self, capabilities="all", probe1_resources=False, access=None, res_verbs=RESOURCE_VERBS):
        """O adaptador runtime (scripted.py, probe@1) e, conforme `capabilities`: "all" = o scripted_resources.py com
        as quatro capacidades de recurso; um dict = com só essas; None = nenhum adaptador de recurso.
        probe1_resources = mais um scripted.py probe@1 que declara messaging, signals e permissions."""
        runtime = [sys.executable, str(SCRIPTED), "--record", str(self.rt_record), "--scenario", str(self.rt_scenario)]
        adapters = [adapter_yaml("fake", runtime, verbs=tuple(RUNTIME_VERBS), timeout=60)]
        if capabilities is not None:
            command = [sys.executable, str(RESOURCES), "--record", str(self.res_record), "--scenario",
                       str(self.res_scenario), "--adapter", "res"]
            if capabilities != "all":
                self.describe.write_text(json.dumps({"capabilities": capabilities}), encoding="utf-8")
                command += ["--describe-file", str(self.describe)]
            adapters.append(adapter_yaml("res", command, verbs=res_verbs, timeout=60))
        if probe1_resources:
            command = [sys.executable, str(SCRIPTED), "--record", str(self.v1_record), "--scenario",
                       str(self.res_scenario), "--adapter", "res1", "--verbs", "messaging=queue,subscriptions",
                       "--verbs", "signals=metrics", "--verbs", "permissions=simulate"]
            adapters.append(adapter_yaml("res1", command, verbs=res_verbs, timeout=60))
        text = f"atlas: {json.dumps(str(self.box.atlas))}\ncredentials: {{}}\n"
        text += access_text(self.access() if access is None else access)
        text += probes_yaml(adapters, limits="{lines: 200, since: 30m}")
        self.box.write_local(text, config_home=self.cfg)

    def set_runtime(self, image=NEW_IMAGE, **states):
        data = {d: states.get(d) or runtime_state(d, image=image) for d in ORDERS_DEPLOYMENTS}
        self.rt_scenario.write_text(json.dumps(data), encoding="utf-8")

    def set_resources(self):
        """O cenário dos recursos volta a resources_now(); set_resource troca as respostas de um recurso."""
        self.scenario = resources_now()
        self.res_scenario.write_text(json.dumps(self.scenario), encoding="utf-8")

    def set_resource(self, resource, **verbs):
        self.scenario.setdefault(resource, {}).update(copy.deepcopy(verbs))
        self.res_scenario.write_text(json.dumps(self.scenario), encoding="utf-8")

    def write_baseline(self, data, name="foto.json"):
        path = self.task / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    # -- execução

    def calls(self, mode=None, record=None):
        path = record or self.res_record
        if not path.exists():
            return []
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [r for r in rows if mode is None or r["mode"] == mode]

    def resource_runs(self, resource=None):
        runs = [c["input"] for c in self.calls("run")]
        if resource is None:
            return runs
        kind, rid = resource.split(":", 1)
        return [r for r in runs if (r.get("target") or {}).get("resource", {}).get("kind") == kind
                and r["target"]["resource"].get("id") == rid]

    def reset_calls(self):
        for path in (self.rt_record, self.res_record, self.v1_record):
            if path.exists():
                path.unlink()

    def log(self):
        path = self.cfg / "probes.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def log_text(self):
        path = self.cfg / "probes.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def access_values(self):
        return (PROFILE, PROD_PROFILE, DB_USER, DB_NAME, CONTEXT_DEV, CONTEXT_PROD, str(self.passfile), PASSFILE_NAME)

    def verify(self, *args, env=None):
        """Roda `atlas.py verify ...`. Em toda execução (UT-10): sem traceback, a opção existe, a pasta do atlas igual,
        os adaptadores falsos só com verbos de leitura e nenhum valor de acesso local na saída nem no probes.log."""
        before = snapshot(self.box.atlas)
        result = self.box.run("verify", *args, config_home=self.cfg, env=env)
        text = output(result)
        self.assertNotIn("Traceback", text, text)
        self.assertNotIn("invalid choice", text, f"atlas.py sem o subcomando verify ({SPEC})")
        self.assertNotIn("unrecognized arguments", text, f"atlas.py verify sem a opção nova ({SPEC}): {text}")
        self.assertEqual(snapshot(self.box.atlas), before, "o verify mudou a pasta do atlas (ADR-0026)")
        for call in self.calls("run", record=self.rt_record):
            self.assertEqual(call["input"].get("capability"), "runtime", call)
            self.assertIn(call["input"].get("verb"), RUNTIME_VERBS, call)
        for call in self.calls("run") + self.calls("run", record=self.v1_record):
            self.assertIn(call["input"].get("capability"), RESOURCE_CAPABILITIES, call)
            self.assertIn(call["input"].get("verb"), RESOURCE_VERBS, call)
        lowered = (text + self.log_text()).lower()
        for value in self.access_values():
            self.assertNotIn(value.lower(), lowered, f"valor de acesso local apareceu: {value}")
        return result

    def take(self, *extra, out=None, env="dev"):
        out = out or self.task / "foto.json"
        return self.verify("snapshot", "--service", "orders", "--env", env, "--out", out, *extra)

    def photo(self, *extra, out=None, env="dev"):
        out = out or self.task / "foto.json"
        run = self.take(*extra, out=out, env=env)
        self.assertExit(run, 0)
        text = out.read_text(encoding="utf-8")
        data = json.loads(text)
        self.assertEqual(snapshot2_problems(data), [], json.dumps(data, ensure_ascii=False, indent=1))
        return data, text

    def compare(self, *extra, baseline=True, expect=NEW_IMAGE, env="dev", as_json=True):
        args = ["compare", "--service", "orders", "--env", env, "--expect-image", expect]
        if baseline is True:
            baseline = self.write_baseline(baseline2(), "baseline-padrao.json")
        elif isinstance(baseline, dict):
            baseline = self.write_baseline(baseline, "baseline.json")
        if baseline:
            args += ["--baseline", baseline]
        return self.verify(*args, *extra, *(["--json"] if as_json else []))

    def result(self, run, verdict=None):
        try:
            data = json.loads(run.stdout)
        except ValueError:
            self.fail(f"saída --json não é JSON (exit {run.returncode}): {output(run)}")
        self.assertEqual(result2_problems(data), [], json.dumps(data, ensure_ascii=False, indent=1))
        self.assertEqual(run.returncode, VERDICT_EXIT[data["verdict"]], output(run))
        if verdict is not None:
            self.assertEqual(data["verdict"], verdict, json.dumps(data, ensure_ascii=False, indent=1))
        return data

    def check(self, data, name, resource=None, deployment=None):
        found = [c for c in data["checks"] if c["check"] == name and c.get("resource") == resource
                 and (deployment is None or c["deployment"] == deployment)]
        self.assertEqual(len(found), 1, json.dumps(data["checks"], ensure_ascii=False, indent=1))
        return found[0]

    def status_of(self, *extra, resource, name="dependencies", baseline=True, verdict=None):
        data = self.result(self.compare(*extra, baseline=baseline), verdict)
        return self.check(data, name, resource)

    def assertExit(self, run, code):
        self.assertEqual(run.returncode, code, output(run))

    def assertMotive(self, item, text):
        where = (item.get("reason") or "") + " " + json.dumps(item.get("evidence"), ensure_ascii=False)
        self.assertIn(text, where, json.dumps(item, ensure_ascii=False, indent=1))

    def assertNoRun(self):
        self.assertEqual(self.calls("run"), [], "um adaptador de recurso rodou")
        self.assertEqual(self.calls("run", record=self.rt_record), [], "o adaptador runtime rodou")
        self.assertEqual(self.calls("run", record=self.v1_record), [], "o adaptador probe@1 rodou")

    def assertInvalid(self, run, text=None):
        self.assertExit(run, 2)
        if text:
            self.assertIn(text, output(run))
        self.assertNotIn('"verdict"', run.stdout)
        self.assertNoRun()


# --------------------------------------------------------------------------- CH-01


class CharacterizationTest(VerifyCase):
    """O atlas da SPEC-0090 (serviço api, nenhum recurso ligado) com o adaptador runtime de hoje."""

    def pairs(self, run):
        data = json.loads(run.stdout)
        return data, sorted((c["deployment"], c["check"], c["status"]) for c in data["checks"])

    def test_without_resources_verify_gives_todays_checks_verdict_and_exit(self):
        """SPEC-0102:CH-01 — guarda: sem recurso ligado e com uma foto verify@1, o compare no estado saudável dá as
        três verificações ok por deployment, passou e exit 0; no CrashLoop (pod não pronto, restarts e BackOff
        novos), runtime failed, degradou e exit 1; o snapshot grava os mesmos deployments e not_verified de hoje."""
        # SPEC-0102:CH-01
        run = self.compare()
        data, pairs = self.pairs(run)
        self.assertEqual(pairs, sorted((d, c, "ok") for d in API_DEPLOYMENTS for c in DEPLOYMENT_CHECKS))
        self.assertEqual((data["verdict"], run.returncode), ("passou", 0))
        crash = deployment_state("dev-api", not_ready=("api-7f9c-cccc",), restarts={"api-7f9c-cccc": 4},
                                 events=[("BackOff", "Pod/api-7f9c-cccc", 3)])
        self.set_state(**{"dev-api": crash})
        run = self.compare()
        data, pairs = self.pairs(run)
        expected = [(d, c, "ok") for d in API_DEPLOYMENTS for c in DEPLOYMENT_CHECKS]
        expected[expected.index(("dev-api", "runtime", "ok"))] = ("dev-api", "runtime", "failed")
        self.assertEqual(pairs, sorted(expected))
        self.assertEqual((data["verdict"], run.returncode), ("degradou", 1))
        self.set_state(**{d: deployment_state(d, image=API_OLD_IMAGE) for d in API_DEPLOYMENTS})
        out = self.task / "foto-ch01.json"
        self.assertEqual(self.take(out).returncode, 0)
        photo = json.loads(out.read_text(encoding="utf-8"))
        expected_deployments = {
            d: {"images": [API_OLD_IMAGE], "ready": len(API_PODS[d]), "desired": len(API_PODS[d]),
                "restarts": {p: 0 for p in API_PODS[d]}, "warnings": [], "error_signatures": {}}
            for d in API_DEPLOYMENTS}
        self.assertEqual(photo["deployments"], expected_deployments)
        self.assertEqual(photo["not_verified"], [])
        self.assertEqual(baseline_data()["deployments"].keys(), photo["deployments"].keys())


# --------------------------------------------------------------------------- UT-01


class SnapshotTest(DepsCase):
    def test_snapshot_keeps_only_the_contract_fields_sorted_and_masked(self):
        """SPEC-0102:UT-01 — fila (com o campo extra sample_body), tópico (assinaturas com o ARN da conta
        123456789012) e banco PostgreSQL (migrations e tabelas fora de ordem): a foto é verify@2 válida, com
        dependencies só com os campos da regra 4a do ADR-0026, listas ordenadas, a conta como [REDACTED], sem
        sample_body e sem o profile, o usuário, o banco nem o passfile; as probes de recurso pedem lines 2000 e
        since_seconds 1800."""
        # SPEC-0102:UT-01
        self.set_runtime(image=OLD_IMAGE)
        body = "pedido 42 do cliente zz-0102"
        self.set_resource("queue:orders", queue=answer([dict(QUEUE, sample_body=body)]),
                          metrics=answer(QUEUE_METRICS_BASE))
        self.set_resource("topic:orders-events", subscriptions=answer(list(reversed(SUBSCRIPTIONS_NOW))))
        self.set_resource("datastore:orders-db", migrations=answer([
            {"id": "20261124_add_status", "success": True}, {"id": "20261120_create_orders", "success": None},
            {"id": "20261125_half", "success": False}]))
        data, text = self.photo()
        self.assertEqual(f("validate_verify_snapshot")(data), [])
        deps = data["dependencies"]
        self.assertEqual(deps["queue:orders"], {
            "deployment": "dev-orders", "relations": ["consumes"], "dlq_of": None, "queue": QUEUE,
            "signals": photo_signals(1800, QUEUE_METRICS_BASE),
            "permissions": {"receive": "allowed", "delete": "allowed"}})
        topic = deps["topic:orders-events"]
        self.assertEqual(topic["subscriptions"], SUBSCRIPTIONS_PHOTO)
        self.assertEqual(topic["deployment"], "dev-orders")
        db = deps["datastore:orders-db"]
        self.assertEqual(db["relations"], ["depends_on"])
        self.assertEqual(db["migrations"], ["20261120_create_orders", "20261124_add_status"])
        self.assertEqual(db["tables"], ["public.items", "public.orders"])
        self.assertEqual(db["signals"], photo_signals(1800, DB_METRICS))
        self.assertEqual(data["not_verified"], [])
        self.assertNotIn(ACCOUNT, text)
        self.assertIn(SUB_A, text)
        for forbidden in ("sample_body", body, *self.access_values()):
            self.assertNotIn(forbidden, text)
        runs = self.resource_runs()
        self.assertTrue(runs)
        self.assertEqual({(r["limits"]["lines"], r["limits"]["since_seconds"]) for r in runs},
                         {(atlas().PROBE_LINES_MAX, 1800)})


# --------------------------------------------------------------------------- UT-02


class ScopeTest(DepsCase):
    def test_default_scope_comes_from_the_graph_without_dlq_and_bucket(self):
        """SPEC-0102:UT-02 — sem --resource: entram datastore:orders-cache, datastore:orders-db, queue:orders e
        topic:orders-events, cada um uma vez (o tópico de dois deployments fica com o primeiro, dev-orders); a DLQ
        ligada só por dlq e o bucket ficam de fora; o cache (valkey) só tem signals e nenhuma probe database."""
        # SPEC-0102:UT-02
        data, _ = self.photo()
        deps = data["dependencies"]
        self.assertEqual(sorted(deps), ["datastore:orders-cache", "datastore:orders-db", "queue:orders",
                                        "topic:orders-events"])
        self.assertEqual(deps["topic:orders-events"]["deployment"], "dev-orders")
        self.assertEqual(set(deps["topic:orders-events"]["relations"]), {"publishes"})
        self.assertEqual(set(deps["datastore:orders-cache"]) - DEP_BASE_KEYS, {"signals"})
        cache = self.resource_runs("datastore:orders-cache")
        self.assertEqual([(r["capability"], r["verb"]) for r in cache], [("signals", "metrics")])
        self.assertEqual(self.resource_runs("queue:orders-dlq"), [])
        self.assertEqual(self.resource_runs("bucket:orders-files"), [])
        self.assertEqual(len([r for r in self.resource_runs("topic:orders-events") if r["verb"] == "subscriptions"]),
                         1)

    def test_resource_restricts_and_the_dlq_comes_as_dlq_of(self):
        """SPEC-0102:UT-02 — --resource queue:orders-dlq: só ela entra, com dlq_of queue:orders, e só as probes queue
        e metrics (a DLQ não tem relação nem permissões)."""
        # SPEC-0102:UT-02
        data, _ = self.photo("--resource", "queue:orders-dlq")
        self.assertEqual(list(data["dependencies"]), ["queue:orders-dlq"])
        self.assertEqual(data["dependencies"]["queue:orders-dlq"]["dlq_of"], "queue:orders")
        self.assertEqual(sorted(r["verb"] for r in self.resource_runs()), ["metrics", "queue"])

    def test_an_invalid_or_unlinked_resource_exits_2_without_probes(self):
        """SPEC-0102:UT-02 — --resource queue:outra (existe e não é ligada), fila:orders e bucket:orders-files: exit
        2 com a mensagem do contrato, nada gravado e nenhuma linha run nos registros."""
        # SPEC-0102:UT-02
        cases = (("queue:outra", "recurso queue:outra não ligado a orders em dev"), ("fila:orders", BAD_RESOURCE),
                 ("bucket:orders-files", BAD_RESOURCE))
        for resource, message in cases:
            with self.subTest(resource=resource):
                out = self.task / "nao.json"
                self.assertInvalid(self.take("--resource", resource, out=out), message)
                self.assertFalse(out.exists())
                self.assertInvalid(self.compare("--resource", resource), message)

    def test_max_resources_cuts_in_snapshot_and_compare(self):
        """SPEC-0102:UT-02 — --max-resources 2: os dois primeiros pela ordem (os datastores) são verificados; a fila
        e o tópico ficam em not_verified "acima de --max-resources (2)", sem probe; o compare com o mesmo limite dá
        o mesmo corte, também sem probe para eles."""
        # SPEC-0102:UT-02
        data, _ = self.photo("--max-resources", "2")
        cut = {"queue:orders", "topic:orders-events"}
        items = [i for i in data["not_verified"] if i.get("resource") in cut]
        self.assertEqual(sorted((i["resource"], i["check"]) for i in items),
                         sorted((r, c) for r in cut for c in RESOURCE_CHECKS))
        for item in items:
            self.assertIn("acima de --max-resources (2)", item["reason"])
        for resource in cut:
            self.assertEqual(self.resource_runs(resource), [])
            self.assertFalse(DEP_ASPECT_KEYS & set(data["dependencies"].get(resource, {})))
        self.assertTrue(self.resource_runs("datastore:orders-db"))
        self.reset_calls()
        result = self.result(self.compare("--max-resources", "2"))
        for resource in cut:
            self.assertEqual(self.resource_runs(resource), [])
            for name in RESOURCE_CHECKS:
                item = self.check(result, name, resource)
                self.assertEqual(item["status"], "not_verified", item)
                self.assertMotive(item, "acima de --max-resources (2)")

    def test_invalid_limits_exit_2_without_probes(self):
        """SPEC-0102:UT-02 — --max-resources 0 e 51, e três --resource com --max-resources 2: exit 2 com a mensagem do
        contrato, no snapshot e no compare, sem probe."""
        # SPEC-0102:UT-02
        three = ("--resource", "queue:orders", "--resource", "topic:orders-events", "--resource",
                 "datastore:orders-db", "--max-resources", "2")
        for extra, message in ((("--max-resources", "0"), BAD_MAX), (("--max-resources", "51"), BAD_MAX),
                               (three, TOO_MANY)):
            with self.subTest(extra=extra):
                self.assertInvalid(self.take(*extra), message)
                self.assertInvalid(self.compare(*extra), message)


# --------------------------------------------------------------------------- UT-03


class QueueTest(DepsCase):
    def queue(self, now, *extra, base=None, resource="queue:orders"):
        self.set_resource(resource, queue=answer([now]))
        baseline = baseline2()
        if base is not None:
            baseline = with_dep(baseline, resource, queue=base)
        return self.status_of("--resource", resource, *extra, resource=resource, baseline=baseline)

    def test_new_messages_in_the_dlq_fail_above_the_limit(self):
        """SPEC-0102:UT-03 — dlq_visible 0 na foto e 2 agora: com --max-new-dlq 0 (padrão) dependencies failed e
        new_dlq 2 na evidência; com --max-new-dlq 2, ok."""
        # SPEC-0102:UT-03
        item = self.queue(dict(QUEUE, dlq_visible=2))
        self.assertEqual(item["status"], "failed", item)
        self.assertEqual(item["evidence"]["queue"]["new_dlq"], 2)
        self.assertEqual(self.queue(dict(QUEUE, dlq_visible=2), "--max-new-dlq", "2")["status"], "ok")

    def test_age_fails_only_when_it_crossed_the_limit_after_the_deploy(self):
        """SPEC-0102:UT-03 — oldest_age_seconds 40 na foto e 900 agora com --max-queue-age 10m: failed; com 700 na
        foto (já acima), não falha e a evidência traz age_above_limit_in_baseline: true."""
        # SPEC-0102:UT-03
        item = self.queue(dict(QUEUE, oldest_age_seconds=900), "--max-queue-age", "10m")
        self.assertEqual(item["status"], "failed", item)
        item = self.queue(dict(QUEUE, oldest_age_seconds=900), "--max-queue-age", "10m",
                          base=dict(QUEUE, oldest_age_seconds=700))
        self.assertNotEqual(item["status"], "failed", item)
        self.assertIs(item["evidence"]["queue"]["age_above_limit_in_baseline"], True)

    def test_a_dlq_without_reading_now_is_not_verified(self):
        """SPEC-0102:UT-03 — dlq_visible número na foto e null agora: not_verified "DLQ sem leitura agora"."""
        # SPEC-0102:UT-03
        item = self.queue(dict(QUEUE, dlq_visible=None))
        self.assertEqual(item["status"], "not_verified", item)
        self.assertMotive(item, "DLQ sem leitura agora")

    def test_a_requested_dlq_fails_by_growth_and_age_does_not_count(self):
        """SPEC-0102:UT-03 — --resource queue:orders-dlq (papel dlq_of): visible 0 → 3 dá failed; visible 0 com uma
        idade alta dá ok (a idade não conta)."""
        # SPEC-0102:UT-03
        grown = self.queue(dict(DLQ_QUEUE, visible=3, oldest_age_seconds=5000), resource="queue:orders-dlq")
        self.assertEqual(grown["status"], "failed", grown)
        old = self.queue(dict(DLQ_QUEUE, oldest_age_seconds=5000), resource="queue:orders-dlq")
        self.assertEqual(old["status"], "ok", old)

    def test_invalid_queue_limits_exit_2(self):
        """SPEC-0102:UT-03 — --max-new-dlq -1 e --max-queue-age 2x: exit 2, sem probe."""
        # SPEC-0102:UT-03
        for extra in (("--max-new-dlq", "-1"), ("--max-queue-age", "2x"), ("--max-queue-age", "25h")):
            with self.subTest(extra=extra):
                self.assertInvalid(self.compare("--resource", "queue:orders", *extra))


# --------------------------------------------------------------------------- UT-04


class SubscriptionsTest(DepsCase):
    def subscriptions(self, items, truncated=False):
        self.set_resource("topic:orders-events", subscriptions=answer(items, truncated))
        return self.status_of("--resource", "topic:orders-events", resource="topic:orders-events")

    def test_a_missing_subscription_fails(self):
        """SPEC-0102:UT-04 — a assinatura A sumiu: failed, com A em missing."""
        # SPEC-0102:UT-04
        item = self.subscriptions([SUBSCRIPTIONS_NOW[1]])
        self.assertEqual(item["status"], "failed", item)
        self.assertIn(SUB_A, item["evidence"]["subscriptions"]["missing"])

    def test_a_changed_filter_fails(self):
        """SPEC-0102:UT-04 — A com outro filtro (fp2): failed, com A em changed."""
        # SPEC-0102:UT-04
        item = self.subscriptions([dict(SUBSCRIPTIONS_NOW[0], filter_fingerprint="fp-9z8y"), SUBSCRIPTIONS_NOW[1]])
        self.assertEqual(item["status"], "failed", item)
        self.assertIn(SUB_A, json.dumps(item["evidence"]["subscriptions"]["changed"]))

    def test_a_new_subscription_is_ok_and_shows_in_the_evidence(self):
        """SPEC-0102:UT-04 — as duas iguais e uma C nova: ok, com C em new."""
        # SPEC-0102:UT-04
        item = self.subscriptions(SUBSCRIPTIONS_NOW + [{"destination": SUB_C, "filter_fingerprint": "fp-c"}])
        self.assertEqual(item["status"], "ok", item)
        self.assertIn(SUB_C, json.dumps(item["evidence"]["subscriptions"]["new"]))

    def test_a_cut_list_is_not_verified(self):
        """SPEC-0102:UT-04 — a probe de subscriptions cortada: not_verified "probe de subscriptions cortada"."""
        # SPEC-0102:UT-04
        item = self.subscriptions(SUBSCRIPTIONS_NOW, truncated=True)
        self.assertEqual(item["status"], "not_verified", item)
        self.assertMotive(item, "probe de subscriptions cortada")


# --------------------------------------------------------------------------- UT-05


class DatabaseTest(DepsCase):
    DB = ("--resource", "datastore:orders-db")

    def db(self, *extra, migrations=None, tables=None, migrations_cut=False, tables_cut=False):
        if migrations is not None:
            self.set_resource("datastore:orders-db", migrations=answer(migrations, migrations_cut))
        elif migrations_cut:
            self.set_resource("datastore:orders-db", migrations=answer([{"id": "m1", "success": True}], True))
        if tables is not None or tables_cut:
            names = tables if tables is not None else ["public.orders", "public.items"]
            self.set_resource("datastore:orders-db", tables=answer([{"name": n} for n in names], tables_cut))
        return self.status_of(*self.DB, *extra, resource="datastore:orders-db")

    M1: ClassVar[dict] = {"id": "m1", "success": True}

    def test_expected_migration(self):
        """SPEC-0102:UT-05 — --expect-migration m2: aplicada (success true) dá ok com new_since_baseline 1; ausente,
        failed com m2 em missing; com success false, failed com m2 em missing e em not_applied; com success null, ok;
        a forma orders-db=m2 dá o mesmo resultado."""
        # SPEC-0102:UT-05
        item = self.db("--expect-migration", "m2", migrations=[self.M1, {"id": "m2", "success": True}])
        self.assertEqual(item["status"], "ok", item)
        self.assertEqual(item["evidence"]["migrations"]["new_since_baseline"], 1)
        item = self.db("--expect-migration", "m2", migrations=[self.M1])
        self.assertEqual(item["status"], "failed", item)
        self.assertIn("m2", item["evidence"]["migrations"]["missing"])
        item = self.db("--expect-migration", "m2", migrations=[self.M1, {"id": "m2", "success": False}])
        self.assertEqual(item["status"], "failed", item)
        self.assertIn("m2", item["evidence"]["migrations"]["missing"])
        self.assertIn("m2", item["evidence"]["migrations"]["not_applied"])
        item = self.db("--expect-migration", "m2", migrations=[self.M1, {"id": "m2", "success": None}])
        self.assertEqual(item["status"], "ok", item)
        for applied, status in (([self.M1, {"id": "m2", "success": True}], "ok"), ([self.M1], "failed")):
            with self.subTest(form="orders-db=m2", status=status):
                item = self.db("--expect-migration", "orders-db=m2", migrations=applied)
                self.assertEqual(item["status"], status, item)

    def test_a_cut_migration_list_proves_only_what_it_found(self):
        """SPEC-0102:UT-05 — lista de migrations cortada com m2: ok; cortada sem m2: not_verified."""
        # SPEC-0102:UT-05
        item = self.db("--expect-migration", "m2", migrations=[self.M1, {"id": "m2", "success": True}],
                       migrations_cut=True)
        self.assertEqual(item["status"], "ok", item)
        item = self.db("--expect-migration", "m2", migrations=[self.M1], migrations_cut=True)
        self.assertEqual(item["status"], "not_verified", item)

    def test_tables(self):
        """SPEC-0102:UT-05 — public.items sumida: failed; uma tabela nova: ok; tabelas cortadas: not_verified."""
        # SPEC-0102:UT-05
        item = self.db(tables=["public.orders"])
        self.assertEqual(item["status"], "failed", item)
        self.assertIn("public.items", item["evidence"]["tables"]["missing"])
        item = self.db(tables=["public.orders", "public.items", "public.audit"])
        self.assertEqual(item["status"], "ok", item)
        self.assertEqual(item["evidence"]["tables"]["new"], 1)
        item = self.db(tables_cut=True)
        self.assertEqual(item["status"], "not_verified", item)

    def test_invalid_expect_migration_exits_2_without_probes(self):
        """SPEC-0102:UT-05 — "m 2", m2 com dois datastores no escopo (orders-db e orders-cache, sem --resource) e
        outro-db=m2 (fora do escopo): exit 2 com as mensagens do contrato, sem probe."""
        # SPEC-0102:UT-05
        self.assertInvalid(self.compare(*self.DB, "--expect-migration", "m 2"))
        self.assertInvalid(self.compare("--expect-migration", "m2"),
                           "--expect-migration m2 ambígua: use <datastore>=<migration>")
        self.assertInvalid(self.compare(*self.DB, "--expect-migration", "outro-db=m2"),
                           "recurso datastore:outro-db fora do escopo do verify")


# --------------------------------------------------------------------------- UT-06


class PermissionsTest(DepsCase):
    def permissions(self, resource, decisions, baseline=None):
        self.set_resource(resource, simulate=answer(perms(**decisions)))
        return self.status_of("--resource", resource, resource=resource, baseline=baseline or baseline2())

    def test_consumes_and_publishes(self):
        """SPEC-0102:UT-06 — queue:orders (consumes; receive e delete allowed na foto): delete denied agora dá failed
        com delete em required; tudo allowed dá ok; simulate sem receive dá not_verified "ação receive não
        simulada". topic:orders-events (publishes): publish denied dá failed."""
        # SPEC-0102:UT-06
        item = self.permissions("queue:orders", {"receive": "allowed", "delete": "denied"})
        self.assertEqual(item["status"], "failed", item)
        self.assertEqual(item["evidence"]["permissions"]["required"]["delete"], "denied")
        self.assertEqual(self.permissions("queue:orders", {"receive": "allowed", "delete": "allowed"})["status"], "ok")
        item = self.permissions("queue:orders", {"delete": "allowed"})
        self.assertEqual(item["status"], "not_verified", item)
        self.assertMotive(item, "ação receive não simulada")
        item = self.permissions("topic:orders-events", {"publish": "denied"})
        self.assertEqual(item["status"], "failed", item)

    def test_already_denied_in_the_baseline_is_not_verified(self):
        """SPEC-0102:UT-06 — delete já denied na foto: denied agora dá not_verified "permissão já negada antes do
        deploy", com delete em denied_in_baseline (nunca failed nem ok); allowed agora dá ok."""
        # SPEC-0102:UT-06
        base = with_dep(baseline2(), "queue:orders", permissions={"receive": "allowed", "delete": "denied"})
        item = self.permissions("queue:orders", {"receive": "allowed", "delete": "denied"}, baseline=base)
        self.assertEqual(item["status"], "not_verified", item)
        self.assertMotive(item, "permissão já negada antes do deploy")
        self.assertIn("delete", item["evidence"]["permissions"]["denied_in_baseline"])
        item = self.permissions("queue:orders", {"receive": "allowed", "delete": "allowed"}, baseline=base)
        self.assertEqual(item["status"], "ok", item)


class PublishedQueuePermissionsTest(DepsCase):
    GRAPH: ClassVar[dict] = {"extra_out": True}

    def test_publishes_on_a_queue_requires_send(self):
        """SPEC-0102:UT-06 — queue:orders-out ligada por publishes (send allowed na foto): send denied agora dá
        failed; send allowed agora dá ok."""
        # SPEC-0102:UT-06
        deps = baseline_dependencies()
        deps["queue:orders-out"] = {"deployment": "dev-orders-worker", "relations": ["publishes"], "dlq_of": None,
                                    "queue": dict(OUT_QUEUE), "signals": photo_signals(1800, OUT_METRICS),
                                    "permissions": {"send": "allowed"}}
        base = baseline2(deps)
        for decision, status in (("denied", "failed"), ("allowed", "ok")):
            with self.subTest(send=decision):
                self.set_resource("queue:orders-out", simulate=answer(perms(send=decision)))
                item = self.status_of("--resource", "queue:orders-out", resource="queue:orders-out", baseline=base)
                self.assertEqual(item["status"], status, item)
                self.assertEqual(item["evidence"]["permissions"]["required"], {"send": decision})


# --------------------------------------------------------------------------- UT-07


class SignalsTest(DepsCase):
    def signals(self, *extra, now=None, base=None):
        if now is not None:
            self.set_resource("queue:orders", metrics=answer(now))
        baseline = baseline2()
        if base is not None:
            baseline = with_dep(baseline, "queue:orders", signals=photo_signals(1800, base))
        return self.status_of("--resource", "queue:orders", *extra, resource="queue:orders", name="signals",
                              baseline=baseline)

    @staticmethod
    def now_with(**values):
        """QUEUE_METRICS_NOW com valores trocados por nome (Errors, Latency, Depth, Sent)."""
        return [dict(m, value=values.get(m["name"], m["value"])) for m in QUEUE_METRICS_NOW]

    def test_errors_per_minute_above_the_increase_fail(self):
        """SPEC-0102:UT-07 — Errors|sum 30 em 1800 s na foto (1,0/min); agora, em 600 s, 16 (1,6/min, +60%) dá
        failed com a métrica em worse; 15 (+50%) dá ok."""
        # SPEC-0102:UT-07
        item = self.signals(now=self.now_with(Errors=16))
        self.assertEqual(item["status"], "failed", item)
        self.assertIn("Errors|sum", [w["metric"] for w in item["evidence"]["worse"]])
        self.assertEqual(self.signals(now=self.now_with(Errors=15))["status"], "ok")

    def test_latency_above_the_increase_fails(self):
        """SPEC-0102:UT-07 — Latency|p95 200 na foto: 301 dá failed; 300 dá ok."""
        # SPEC-0102:UT-07
        self.assertEqual(self.signals(now=self.now_with(Latency=301))["status"], "failed")
        self.assertEqual(self.signals(now=self.now_with(Latency=300))["status"], "ok")

    def test_errors_from_zero_fail(self):
        """SPEC-0102:UT-07 — erro 0 na foto e 1 agora: failed."""
        # SPEC-0102:UT-07
        base = [dict(m, value=0) if m["name"] == "Errors" else m for m in QUEUE_METRICS_BASE]
        self.assertEqual(self.signals(now=self.now_with(Errors=1), base=base)["status"], "failed")

    def test_latency_without_baseline_is_not_compared(self):
        """SPEC-0102:UT-07 — latência null na foto: não comparada (without_baseline); com o erro comparável, ok."""
        # SPEC-0102:UT-07
        base = [dict(m, value=None) if m["name"] == "Latency" else m for m in QUEUE_METRICS_BASE]
        item = self.signals(now=self.now_with(Latency=900), base=base)
        self.assertEqual(item["status"], "ok", item)
        self.assertIn("Latency|p95", json.dumps(item["evidence"]["without_baseline"]))

    def test_saturation_and_traffic_never_fail(self):
        """SPEC-0102:UT-07 — Depth (saturation) e Sent (traffic) muito maiores: ok, os dois em other."""
        # SPEC-0102:UT-07
        item = self.signals(now=self.now_with(Depth=10000, Sent=900000))
        self.assertEqual(item["status"], "ok", item)
        other = json.dumps(item["evidence"]["other"])
        self.assertIn("Depth|max", other)
        self.assertIn("Sent|sum", other)

    def test_nothing_comparable_is_not_verified(self):
        """SPEC-0102:UT-07 — só métricas traffic (na foto e agora): not_verified "nenhuma métrica de erro ou latência
        comparável"."""
        # SPEC-0102:UT-07
        traffic = [m for m in QUEUE_METRICS_BASE if m["kind"] == "traffic"]
        item = self.signals(now=[m for m in QUEUE_METRICS_NOW if m["kind"] == "traffic"], base=traffic)
        self.assertEqual(item["status"], "not_verified", item)
        self.assertMotive(item, "nenhuma métrica de erro ou latência comparável")

    def test_compare_asks_for_the_window(self):
        """SPEC-0102:UT-07 — a probe metrics do compare pede since_seconds = --window (600 por padrão)."""
        # SPEC-0102:UT-07
        self.signals()
        metrics = [r for r in self.resource_runs("queue:orders") if r["verb"] == "metrics"]
        self.assertEqual([r["limits"]["since_seconds"] for r in metrics], [600])

    def test_invalid_increase_exits_2(self):
        """SPEC-0102:UT-07 — --max-signal-increase -0.1, abc e 101: exit 2 com a mensagem do contrato, sem probe."""
        # SPEC-0102:UT-07
        for value in ("-0.1", "abc", "101"):
            with self.subTest(value=value):
                self.assertInvalid(self.compare("--resource", "queue:orders", "--max-signal-increase", value),
                                   BAD_INCREASE)


# --------------------------------------------------------------------------- UT-08


NO_MESSAGING = {"signals": {"verbs": ["metrics"], "targets": ["datastore", "queue", "topic"], "access": ["cloud"]},
                "permissions": {"verbs": ["simulate"], "targets": ["queue", "topic"], "access": ["cloud"]}}


class UnverifiedTest(DepsCase):
    def unverified(self, verdict="inconclusivo", baseline=None, name="dependencies"):
        data = self.result(self.compare("--resource", "queue:orders", baseline=baseline or baseline2()), verdict)
        item = self.check(data, name, "queue:orders")
        self.assertEqual(item["status"], "not_verified", item)
        return item

    def test_without_a_probe2_adapter_for_messaging(self):
        """SPEC-0102:UT-08 — nenhum adaptador probe@2 declara messaging: o aspecto queue fica not_verified com
        "nenhum adaptador para messaging"; veredito inconclusivo, exit 5."""
        # SPEC-0102:UT-08
        self.configure(capabilities=NO_MESSAGING)
        self.assertMotive(self.unverified(), f"{NO_ADAPTER} messaging")

    def test_only_a_probe1_adapter(self):
        """SPEC-0102:UT-08 — só um adaptador probe@1 declara messaging, signals e permissions: as duas verificações
        da fila ficam not_verified e o probe@1 nunca recebe um recurso."""
        # SPEC-0102:UT-08
        self.configure(capabilities=None, probe1_resources=True)
        self.unverified()
        self.unverified(name="signals")
        self.assertEqual(self.calls("run", record=self.v1_record), [])

    def test_without_local_cloud_access(self):
        """SPEC-0102:UT-08 — sem access.cloud (a probe sai com 4 "sem acesso local: cloud"): not_verified com esse
        motivo, sem nenhum valor de acesso."""
        # SPEC-0102:UT-08
        self.configure(access=self.access(cloud=False))
        self.assertMotive(self.unverified(), "sem acesso local: cloud")

    def test_probe_error_exit_cut_and_out_of_contract(self):
        """SPEC-0102:UT-08 — a probe queue com status error "renove o login da nuvem", o adaptador saindo com 3, a
        resposta cortada e um item sem dlq_visible: dependencies not_verified (com o motivo do contrato), nunca ok;
        veredito inconclusivo."""
        # SPEC-0102:UT-08
        missing = {k: v for k, v in QUEUE.items() if k != "dlq_visible"}
        cases = (("erro", {"error": "token expirado: renove o login da nuvem"}, "renove o login da nuvem"),
                 ("exit 3", {"exit": 3, "stderr": "quebrou"}, None),
                 ("cortada", answer([QUEUE], truncated=True), "probe de queue cortada"),
                 ("sem dlq_visible", answer([missing]), "item fora do contrato de messaging queue: dlq_visible"),
                 ("dois itens", answer([QUEUE, QUEUE]), "resposta de messaging queue com 2 item(ns), esperado 1"))
        for name, response, motive in cases:
            with self.subTest(case=name):
                self.set_resources()
                self.set_resource("queue:orders", queue=response)
                item = self.unverified()
                if motive:
                    self.assertMotive(item, motive)

    def test_a_resource_out_of_the_photo(self):
        """SPEC-0102:UT-08 — queue:orders ligada agora e ausente da foto: dependencies e signals not_verified
        "recurso fora da foto"."""
        # SPEC-0102:UT-08
        deps = baseline_dependencies()
        deps.pop("queue:orders")
        for name in RESOURCE_CHECKS:
            with self.subTest(check=name):
                self.assertMotive(self.unverified(baseline=baseline2(deps), name=name), OUT_OF_PHOTO)

    def test_a_repeated_metric_is_not_verified(self):
        """SPEC-0102:UT-08 — signals metrics com o mesmo name|stat repetido: signals not_verified "métrica repetida:
        Errors|sum"."""
        # SPEC-0102:UT-08
        self.set_resource("queue:orders", metrics=answer(QUEUE_METRICS_NOW + [QUEUE_METRICS_NOW[0]]))
        self.assertMotive(self.unverified(name="signals"), "métrica repetida: Errors|sum")


# --------------------------------------------------------------------------- UT-09


class OldBaselineTest(DepsCase):
    def test_a_verify1_baseline_leaves_the_new_checks_not_verified_without_probes(self):
        """SPEC-0102:UT-09 — foto verify@1 com recursos ligados e adaptador de recurso declarado: delivery, runtime e
        logs ok, dependencies e signals de cada recurso not_verified "foto sem dependências", saída verify@2 válida e
        nenhuma probe de recurso."""
        # SPEC-0102:UT-09
        data = self.result(self.compare(baseline=baseline1()), "inconclusivo")
        self.assertEqual(f("validate_verify_result")(data), [])
        for item in data["checks"]:
            if item["check"] in DEPLOYMENT_CHECKS:
                self.assertEqual(item["status"], "ok", item)
            else:
                self.assertEqual(item["status"], "not_verified", item)
                self.assertMotive(item, OLD_BASELINE)
        resources = {c["resource"] for c in data["checks"] if c["check"] in RESOURCE_CHECKS}
        self.assertEqual(resources, {"datastore:orders-cache", "datastore:orders-db", "queue:orders",
                                     "topic:orders-events"})
        self.assertEqual(self.resource_runs(), [])

    def test_without_baseline_the_new_checks_are_not_verified_without_probes(self):
        """SPEC-0102:UT-09 — sem --baseline: dependencies e signals not_verified "sem foto de antes: dependências e
        sinais não se comparam", sem probe de recurso."""
        # SPEC-0102:UT-09
        data = self.result(self.compare(baseline=None), "inconclusivo")
        news = [c for c in data["checks"] if c["check"] in RESOURCE_CHECKS]
        self.assertTrue(news, data["checks"])
        for item in news:
            self.assertEqual(item["status"], "not_verified", item)
            self.assertMotive(item, NO_BASELINE)
        self.assertEqual(self.resource_runs(), [])


# --------------------------------------------------------------------------- UT-10


class VerdictSafetyTest(DepsCase):
    TWO = ("--resource", "queue:orders", "--resource", "topic:orders-events")

    def test_verdict_combinations(self):
        """SPEC-0102:UT-10 — as cinco verificações em dois recursos: tudo ok = passou/0 sem sugestão; uma failed
        (DLQ) = degradou/1 com sugestão sem comando; uma not_verified (sinais do tópico sem nada comparável) =
        inconclusivo/5; failed e not_verified = degradou/1."""
        # SPEC-0102:UT-10
        data = self.result(self.compare(*self.TWO), "passou")
        self.assertEqual(sorted({c["check"] for c in data["checks"]}), sorted(DEPLOYMENT_CHECKS + RESOURCE_CHECKS))
        self.assertEqual(len(data["checks"]), 2 * 3 + 2 * 2)
        self.assertTrue(all(c["status"] == "ok" for c in data["checks"]), data["checks"])
        self.assertIn(data.get("suggestion"), (None, ""))
        traffic_only = answer([m for m in TOPIC_METRICS if m["kind"] == "traffic"])
        cases = ((("dlq",), "degradou"), (("topic",), "inconclusivo"), (("dlq", "topic"), "degradou"))
        for changes, verdict in cases:
            with self.subTest(changes=changes):
                self.set_resources()
                if "dlq" in changes:
                    self.set_resource("queue:orders", queue=answer([dict(QUEUE, dlq_visible=3)]))
                if "topic" in changes:
                    self.set_resource("topic:orders-events", metrics=traffic_only)
                data = self.result(self.compare(*self.TWO), verdict)
                if verdict == "degradou":
                    self.assertTrue(data["suggestion"])
                    self.assertIsNone(COMMAND_RE.search(data["suggestion"]), data["suggestion"])

    def test_markdown_has_the_resource_column(self):
        """SPEC-0102:UT-10 — sem --json, o Markdown traz o veredito e a coluna "recurso" com o kind:id, no mesmo
        exit."""
        # SPEC-0102:UT-10
        self.set_resource("queue:orders", queue=answer([dict(QUEUE, dlq_visible=3)]))
        run = self.compare("--resource", "queue:orders", as_json=False)
        self.assertExit(run, 1)
        self.assertIn("degradou", run.stdout)
        self.assertIn("recurso", run.stdout)
        self.assertIn("queue:orders", run.stdout)

    def test_production_needs_confirmation_and_resource_probes_are_logged(self):
        """SPEC-0102:UT-10 — prod sem --confirm-production: snapshot e compare saem com 4, sem nenhuma linha run e sem
        nada no probes.log; com a confirmação, o snapshot roda e cada probe de recurso entra no probes.log com
        resource (queue:orders) e confirmed_production true."""
        # SPEC-0102:UT-10
        out = self.task / "foto-prod.json"
        self.assertExit(self.take(out=out, env="prod"), 4)
        self.assertFalse(out.exists())
        base = self.write_baseline(baseline2(deployments=("prod-orders",), environment="prod",
                                             dependencies={"queue:orders": dict(
                                                 baseline_dependencies()["queue:orders"], deployment="prod-orders")}),
                                   "foto-prod-base.json")
        self.assertExit(self.compare(baseline=base, env="prod"), 4)
        self.assertNoRun()
        self.assertEqual(self.log(), [])
        data, _ = self.photo("--confirm-production", out=out, env="prod")
        self.assertEqual(list(data["dependencies"]), ["queue:orders"])
        entries = [e for e in self.log() if e["capability"] != "runtime"]
        self.assertTrue(entries, self.log())
        self.assertEqual(len(entries), len(self.resource_runs()))
        for entry in entries:
            self.assertEqual(entry.get("resource"), "queue:orders", entry)
            self.assertIs(entry["confirmed_production"], True)


# --------------------------------------------------------------------------- UT-11


ONLY_MESSAGING = {"messaging": {"verbs": ["queue", "subscriptions"], "targets": ["queue", "topic"],
                                "access": ["cloud"]}}


class NoResourceAdapterTest(DepsCase):
    def test_without_any_resource_adapter_verify_stays_as_verify1(self):
        """SPEC-0102:UT-11 — só o adaptador runtime, sem --resource, com recursos ligados: a foto tem dependencies {},
        o compare só emite delivery, runtime e logs (passou/0 no estado saudável) e nenhuma probe de recurso roda."""
        # SPEC-0102:UT-11
        self.configure(capabilities=None)
        self.set_runtime(image=OLD_IMAGE)
        data, _ = self.photo()
        self.assertEqual(data["dependencies"], {})
        self.assertEqual([i for i in data["not_verified"] if "resource" in i], [])
        self.set_runtime()
        result = self.result(self.compare(baseline=self.task / "foto.json"), "passou")
        self.assertEqual(sorted((c["deployment"], c["check"]) for c in result["checks"]),
                         sorted((d, c) for d in DEV_DEPLOYMENTS for c in DEPLOYMENT_CHECKS))
        self.assertEqual(self.resource_runs(), [])
        self.assertFalse([e for e in self.log() if e["capability"] != "runtime"], self.log())

    def test_one_resource_adapter_turns_the_scope_on(self):
        """SPEC-0102:UT-11 — só um adaptador probe@2 de messaging: a fila tem o aspecto queue verificado e
        permissions e signals not_verified com o motivo; os datastores ficam not_verified (o cache só em signals);
        veredito inconclusivo, exit 5."""
        # SPEC-0102:UT-11
        self.configure(capabilities=ONLY_MESSAGING)
        self.set_runtime(image=OLD_IMAGE)
        self.photo()
        self.set_runtime()
        data = self.result(self.compare(baseline=self.task / "foto.json"), "inconclusivo")
        queue = self.check(data, "dependencies", "queue:orders")
        self.assertEqual(queue["status"], "not_verified", queue)
        self.assertIn("queue", queue["evidence"])
        self.assertMotive(queue, f"{NO_ADAPTER} permissions")
        self.assertMotive(self.check(data, "signals", "queue:orders"), f"{NO_ADAPTER} signals")
        for name in RESOURCE_CHECKS:
            self.assertEqual(self.check(data, name, "datastore:orders-db")["status"], "not_verified")
        self.assertEqual(self.check(data, "signals", "datastore:orders-cache")["status"], "not_verified")
        self.assertFalse([c for c in data["checks"] if c["check"] == "dependencies"
                          and c["resource"] == "datastore:orders-cache"])

    def test_a_resource_option_turns_the_scope_on(self):
        """SPEC-0102:UT-11 — nenhum adaptador de recurso e --resource queue:orders: a fila entra e fica not_verified
        nas duas verificações, com o motivo."""
        # SPEC-0102:UT-11
        self.configure(capabilities=None)
        data, _ = self.photo("--resource", "queue:orders")
        self.assertEqual(list(data["dependencies"]), ["queue:orders"])
        result = self.result(self.compare("--resource", "queue:orders"), "inconclusivo")
        for name in RESOURCE_CHECKS:
            item = self.check(result, name, "queue:orders")
            self.assertEqual(item["status"], "not_verified", item)
            self.assertMotive(item, NO_ADAPTER)


# --------------------------------------------------------------------------- IT-01


IT_CAPABILITIES = {
    "messaging": {"verbs": ["queue", "subscriptions"], "targets": ["queue", "topic"], "access": ["cloud"]},
    "signals": {"verbs": ["metrics"], "targets": ["datastore", "queue", "topic"], "access": ["cloud"]},
    "permissions": {"verbs": ["simulate"], "targets": ["queue", "topic"], "access": ["cloud"]}}
IT_QUEUE = {"visible": 2, "in_flight": 0, "oldest_age_seconds": 30, "dlq_visible": 0}
IT_METRICS = [metric("Errors", "sum", 0, "error"), metric("Latency", "p95", 120, "latency")]


class EndToEndTest(DepsCase):
    GRAPH: ClassVar[dict] = {"minimal": True}

    def tools(self):
        """aws, psql e kubectl falsos no começo do PATH: só registram que foram chamados e falham."""
        folder = self.task / "bin"
        folder.mkdir(exist_ok=True)
        self.marker = self.task / "real-tools.txt"
        for name in ("aws", "psql", "kubectl"):
            path = folder / name
            path.write_text(f"#!/bin/sh\necho {name} >> '{self.marker}'\nexit 99\n", encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return {"PATH": f"{folder}{os.pathsep}{os.environ.get('PATH', '')}"}

    def phases(self, dlq_after):
        env = self.tools()
        self.configure(capabilities=IT_CAPABILITIES, access=self.access(databases=False))
        self.set_runtime(image=OLD_IMAGE)
        self.set_resource("queue:orders", queue=answer([IT_QUEUE]), metrics=answer(IT_METRICS),
                          simulate=answer(perms(receive="allowed", delete="allowed")))
        out = self.task / "foto.json"
        run = self.verify("snapshot", "--service", "orders", "--env", "dev", "--out", out, env=env)
        self.assertExit(run, 0)
        photo = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(snapshot2_problems(photo), [], photo)
        self.assertEqual(photo["dependencies"]["queue:orders"]["queue"], IT_QUEUE)
        self.set_runtime()
        self.set_resource("queue:orders", queue=answer([dict(IT_QUEUE, dlq_visible=dlq_after)]))
        run = self.verify("compare", "--service", "orders", "--env", "dev", "--baseline", out, "--expect-image",
                          NEW_IMAGE, "--json", env=env)
        data = self.result(run)
        self.assertFalse(self.marker.exists(), "um aws, psql ou kubectl foi chamado")
        return data

    def test_dependencies_following_the_photo_pass(self):
        """SPEC-0102:IT-01 — snapshot "antes" (dlq_visible 0), o roteiro passa ao "depois" igual (dlq 0, permissões
        allowed, sinais iguais) e o compare --expect-image acme/orders:2.0.2 dá passou, exit 0, com dependencies e
        signals de queue:orders ok."""
        # SPEC-0102:IT-01
        data = self.phases(0)
        self.assertEqual(data["verdict"], "passou", json.dumps(data, ensure_ascii=False, indent=1))
        self.assertEqual(self.check(data, "dependencies", "queue:orders")["status"], "ok")
        self.assertEqual(self.check(data, "signals", "queue:orders")["status"], "ok")

    def test_a_growing_dlq_degrades(self):
        """SPEC-0102:IT-01 — o "depois" com dlq_visible 4: degradou, exit 1, dependencies de queue:orders failed com
        new_dlq 4 na evidência."""
        # SPEC-0102:IT-01
        data = self.phases(4)
        self.assertEqual(data["verdict"], "degradou")
        item = self.check(data, "dependencies", "queue:orders")
        self.assertEqual(item["status"], "failed", item)
        self.assertEqual(item["evidence"]["queue"]["new_dlq"], 4)


# --------------------------------------------------------------------------- CT-01 e CT-02


BLOCK_RE = re.compile(r"```json([^\n]*)\n(.*?)```", re.DOTALL)
ITEM_FIELDS = {("messaging", "queue"): {"visible", "in_flight", "oldest_age_seconds", "dlq_visible"},
               ("messaging", "subscriptions"): {"destination", "filter_fingerprint"},
               ("database", "migrations"): {"id", "success"},
               ("database", "tables"): {"name"},
               ("signals", "metrics"): {"name", "stat", "value", "kind"},
               ("permissions", "simulate"): {"action", "api_action", "decision"}}
ASPECT_OF = {("messaging", "queue"): ("queue:orders", "queue", "dependencies"),
             ("messaging", "subscriptions"): ("topic:orders-events", "subscriptions", "dependencies"),
             ("database", "migrations"): ("datastore:orders-db", "migrations", "dependencies"),
             ("database", "tables"): ("datastore:orders-db", "tables", "dependencies"),
             ("signals", "metrics"): ("queue:orders", "signals", "signals"),
             ("permissions", "simulate"): ("queue:orders", "permissions", "dependencies")}


def doc_blocks():
    """[(etiquetas depois de ```json, dado)] de references/verify.md; bloco que não é JSON fica de fora."""
    text = VERIFY_DOC.read_text(encoding="utf-8")
    found = []
    for tags, body in BLOCK_RE.findall(text):
        try:
            found.append((tags.split(), json.loads(body)))
        except ValueError:
            continue
    return found


def result_sample():
    """Uma saída verify@2 válida montada no teste (independente do verify.md)."""
    checks = [{"deployment": "dev-orders", "resource": None, "check": c, "status": "ok", "evidence": {},
               "reason": ""} for c in DEPLOYMENT_CHECKS]
    checks += [{"deployment": "dev-orders", "resource": "queue:orders", "check": c, "status": "ok", "evidence": {},
                "reason": ""} for c in RESOURCE_CHECKS]
    return {"contract": "verify@2", "verdict": "passou", "checks": checks, "suggestion": ""}


class ContractTest(DepsCase):
    def test_validators_accept_both_contracts_and_refuse_the_rest(self):
        """SPEC-0102:CT-01 — validate_verify_snapshot e validate_verify_result aceitam verify@1 e verify@2 válidos e
        recusam: chave desconhecida, resource faltando numa verificação verify@2, resource com kind inválido,
        dependencies ausente numa foto verify@2 e contract verify@3."""
        # SPEC-0102:CT-01
        snap, result = f("validate_verify_snapshot"), f("validate_verify_result")
        photo2, photo1, out2 = baseline2(), baseline1(), result_sample()
        out1 = {"contract": "verify@1", "verdict": "passou", "suggestion": "",
                "checks": [{k: v for k, v in c.items() if k != "resource"} for c in out2["checks"][:3]]}
        for name, data, validator in (("foto verify@2", photo2, snap), ("foto verify@1", photo1, snap),
                                      ("saída verify@2", out2, result), ("saída verify@1", out1, result)):
            with self.subTest(valid=name):
                self.assertEqual(validator(data), [])
        no_resource = copy.deepcopy(out2)
        no_resource["checks"][3].pop("resource")
        bad_kind = copy.deepcopy(out2)
        bad_kind["checks"][3]["resource"] = "bucket:orders-files"
        no_deps = copy.deepcopy(photo2)
        no_deps.pop("dependencies")
        invalid = (("foto com chave desconhecida", dict(photo2, extra="x"), snap),
                   ("foto sem dependencies", no_deps, snap),
                   ("foto verify@3", dict(photo2, contract="verify@3"), snap),
                   ("foto verify@1 com dependencies", dict(photo2, contract="verify@1"), snap),
                   ("saída com chave desconhecida", dict(out2, extra="x"), result),
                   ("saída sem resource", no_resource, result),
                   ("saída com kind inválido", bad_kind, result),
                   ("saída verify@3", dict(out2, contract="verify@3"), result))
        for name, data, validator in invalid:
            with self.subTest(invalid=name):
                self.assertTrue(validator(data), f"{name} foi aceito")

    def test_verify_md_examples_of_both_contracts(self):
        """SPEC-0102:CT-01 — references/verify.md traz exemplos ```json de foto e de saída verify@1 e verify@2, válidos
        nos validadores, e blocos `verify@2 snapshot invalid` e `verify@2 result invalid`, recusados; o exemplo de
        foto verify@2 é aceito pelo compare como --baseline (exit diferente de 2) e um inválido sai com 2."""
        # SPEC-0102:CT-01
        snap, result = f("validate_verify_snapshot"), f("validate_verify_result")
        blocks = doc_blocks()
        plain = [data for tags, data in blocks if not tags and isinstance(data, dict)]
        for contract in ("verify@1", "verify@2"):
            photos = [d for d in plain if d.get("contract") == contract and "taken_at" in d]
            outs = [d for d in plain if d.get("contract") == contract and "verdict" in d]
            self.assertTrue(photos, f"verify.md sem exemplo de foto {contract}")
            self.assertTrue(outs, f"verify.md sem exemplo de saída {contract}")
            for data in photos:
                self.assertEqual(snap(data), [], data)
            for data in outs:
                self.assertEqual(result(data), [], data)
        for kind, validator in (("snapshot", snap), ("result", result)):
            marked = [d for tags, d in blocks if tags == ["verify@2", kind, "invalid"]]
            self.assertTrue(marked, f"verify.md sem bloco `json verify@2 {kind} invalid`")
            for data in marked:
                self.assertTrue(validator(data), data)
        example = next(d for d in plain if d.get("contract") == "verify@2" and "taken_at" in d)
        run = self.compare(baseline=dict(example, service="orders", environment="dev"))
        self.assertIn(run.returncode, (0, 1, 5), output(run))
        broken = baseline2()
        broken.pop("dependencies")
        self.assertExit(self.compare(baseline=broken), 2)

    def test_verify_items_blocks_drive_the_aspects(self):
        """SPEC-0102:CT-02 — cada bloco `json verify-items <capacidade> <verbo> <valid|invalid>` do verify.md (um
        válido e um inválido por par da regra 4a do ADR-0026; entre os inválidos, uma assinatura com endpoint no lugar
        de destination e uma migration sem success), devolvido como os itens do adaptador falso: os válidos sustentam o
        aspecto na foto, só com os campos do contrato; os inválidos deixam o aspecto fora e um not_verified com o nome
        do campo no motivo."""
        # SPEC-0102:CT-02
        blocks = [(tuple(tags[1:3]), tags[3], data) for tags, data in doc_blocks()
                  if len(tags) == 4 and tags[0] == "verify-items"]
        for pair in ITEM_FIELDS:
            for verdict in ("valid", "invalid"):
                self.assertTrue([b for b in blocks if b[0] == pair and b[1] == verdict],
                                f"verify.md sem bloco verify-items {' '.join(pair)} {verdict}")
        invalid_items = [i for pair, verdict, data in blocks if verdict == "invalid"
                         for i in (data.get("items", []) if isinstance(data, dict) else data) if isinstance(i, dict)]
        self.assertTrue([i for i in invalid_items if "endpoint" in i and "destination" not in i],
                        "falta o inválido de subscriptions com endpoint")
        self.assertTrue([i for i in invalid_items if "id" in i and "success" not in i and "name" not in i],
                        "falta o inválido de migrations sem success")
        for n, (pair, verdict, data) in enumerate(blocks):
            items = data.get("items") if isinstance(data, dict) else data
            resource, aspect, check = ASPECT_OF[pair]
            with self.subTest(block=f"{' '.join(pair)} {verdict} #{n}"):
                self.set_resources()
                self.set_resource(resource, **{pair[1]: answer(items)})
                photo, _ = self.photo("--resource", resource, out=self.task / f"ct02-{n}.json")
                entry = photo["dependencies"][resource]
                reasons = [i["reason"] for i in photo["not_verified"]
                           if i.get("resource") == resource and i["check"] == check]
                if verdict == "valid":
                    self.assertIn(aspect, entry, photo)
                    self.assertFalse([r for r in reasons if r.startswith(aspect)], reasons)
                    self.assertAspectShape(pair, entry[aspect], items)
                else:
                    self.assertNotIn(aspect, entry, photo)
                    self.assertTrue(any(self.names_a_field(pair, r) for r in reasons), reasons)

    def names_a_field(self, pair, reason):
        prefix = f"item fora do contrato de {pair[0]} {pair[1]}: "
        if prefix in reason:
            return reason.split(prefix, 1)[1].split()[0].strip(".,;") in ITEM_FIELDS[pair]
        return "resposta de messaging queue com" in reason or "métrica repetida" in reason

    def assertAspectShape(self, pair, value, items):
        if pair == ("messaging", "queue"):
            self.assertEqual(set(value), ITEM_FIELDS[pair])
        elif pair == ("messaging", "subscriptions"):
            self.assertEqual(len(value), len(items))
            self.assertTrue(all(set(s) == ITEM_FIELDS[pair] for s in value), value)
        elif pair == ("database", "migrations"):
            self.assertEqual(value, sorted(i["id"] for i in items if i.get("success") is not False))
        elif pair == ("database", "tables"):
            self.assertEqual(value, sorted(i["name"] for i in items))
        elif pair == ("signals", "metrics"):
            self.assertEqual(set(value["metrics"]), {f"{i['name']}|{i['stat']}" for i in items})
            self.assertTrue(all(set(v) == {"kind", "value"} for v in value["metrics"].values()), value)
        else:
            self.assertTrue(set(value) <= {i["action"] for i in items}, value)
            self.assertTrue(set(value.values()) <= {"allowed", "denied"}, value)


if __name__ == "__main__":
    unittest.main()
