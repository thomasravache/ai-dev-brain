#!/usr/bin/env python3
"""aws collector of the boson-atlas (SPEC-0097), category data (rds, elasticache) or messaging (sqs, sns): managed
databases and caches, queues, topics and the SNS -> SQS subscriptions of an AWS account, read with the AWS CLI of the
machine. Stdlib only, Python 3.9+; prints the boson-atlas/collector@1 output (ADR-0011).

Usage: python3 aws.py --services rds,elasticache|sqs,sns --region r1[,r2...] [--max-items N]

Only a closed list of describe/list/get operations is ever run (build_call): argv as a list, never a shell, stdin
closed, a timeout per call and --max-items on every list (a NextToken = failure, never a partial snapshot). The ids
are the resource names; no ARN, queue URL, account id, Owner, subscription ARN or FilterPolicy content leaves the
collector, and a resource with 12 digits in a row anywhere is dropped (ADR-0025). ATLAS_COLLECTOR_PROFILE (set by
the scan from credentials.<id>.profile) reaches the AWS CLI as AWS_PROFILE, without the static keys; it is never
printed. Errors of the AWS CLI become fixed messages: its stderr is never repeated (references/collectors/aws.md).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

CONTRACT = "boson-atlas/collector@1"
COLLECTOR = "aws"
CALL_TIMEOUT = 60  # seconds for each AWS CLI process
DEFAULT_MAX_ITEMS = 1000
MAX_ITEMS_LIMIT = 10000
MAX_REGIONS = 10
CATEGORIES = {"rds": "data", "elasticache": "data", "sqs": "messaging", "sns": "messaging"}
SERVICE_ORDER = ("rds", "elasticache", "sqs", "sns")
REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}$")
COMMON = ("--output", "json", "--no-cli-pager", "--cli-connect-timeout", "10", "--cli-read-timeout", "30")
# the closed table: (service, operation) -> (list key of the response | None, fixed flags, allowed extra arguments)
LISTS = {
    ("rds", "describe-db-clusters"): ("DBClusters", ()),
    ("rds", "describe-db-instances"): ("DBInstances", ()),
    ("elasticache", "describe-replication-groups"): ("ReplicationGroups", ()),
    ("elasticache", "describe-cache-clusters"): ("CacheClusters", ("--show-cache-node-info",)),
    ("elasticache", "describe-serverless-caches"): ("ServerlessCaches", ()),
    ("sqs", "list-queues"): ("QueueUrls", ()),
    ("sns", "list-topics"): ("Topics", ()),
    ("sns", "list-subscriptions"): ("Subscriptions", ()),
}
QUEUE_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(?::\d+)?/\d{12}/[A-Za-z0-9_.-]+$")
SUBSCRIPTION_ARN_RE = re.compile(r"^arn:[a-z0-9-]+:sns:[a-z0-9-]+:\d{12}:[A-Za-z0-9_.-]+:[A-Za-z0-9-]+$")
# a resource ARN: arn:<partition>:<service>:<region>:<account>:<name>
RESOURCE_ARN_RE = re.compile(r"^arn:[a-z0-9-]+:(sqs|sns):([a-z0-9-]+):(\d{12}):([A-Za-z0-9_.-]+)$")
NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
TWELVE_DIGITS = re.compile(r"\d{12}")
STATIC_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_DEFAULT_PROFILE")
NOT_ALLOWED = "chamada não permitida"
# stderr of the AWS CLI -> fixed message (the first that matches wins; the stderr itself never leaves)
LOGIN_RE = re.compile(r"Token has expired|SSO session|UnauthorizedSSOTokenError|ExpiredToken", re.IGNORECASE)
PROFILE_RE = re.compile(r"ProfileNotFound|could not be found")
NO_CREDENTIALS_RE = re.compile(r"Unable to locate credentials|NoCredentials")
DENIED_RE = re.compile(r"AccessDenied|UnauthorizedOperation|AuthorizationError|not authorized", re.IGNORECASE)
TIMEOUT_RE = re.compile(r"Read timeout|Connect timeout|timed out", re.IGNORECASE)

MSG_SERVICES = "--services precisa de rds, elasticache, sqs ou sns"
MSG_MIXED = "misture serviços de dados (rds, elasticache) e de mensageria (sqs, sns) em coletores separados"
MSG_REGION = "--region precisa de 1 a 10 regiões válidas, sem repetição"
MSG_MAX_ITEMS = "--max-items precisa ser um inteiro de 1 a 10000"


class CollectorError(Exception):
    """A failure that ends the collector with exit 1; the message is shown as is, after "aws: "."""


class NotAllowed(CollectorError):
    """A call outside the closed table: refused before running anything."""

    def __init__(self):
        super().__init__(NOT_ALLOWED)


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value):
    """A non-empty string, else None."""
    return value if isinstance(value, str) and value else None


def _port(value):
    """An integer port from 1 to 65535 (a text of digits included), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return value if isinstance(value, int) and 1 <= value <= 65535 else None


# --------------------------------------------------------------------------- the closed list of calls


def build_call(service: str, operation: str, region: str, max_items: int = DEFAULT_MAX_ITEMS, extra=()) -> list:
    """argv of one AWS CLI call, from "aws", built only from the closed table (spec §6); anything else (another
    operation, argument or --attribute-names value) raises NotAllowed ("chamada não permitida") without running."""
    extra = tuple(extra)
    if not isinstance(region, str) or not REGION_RE.match(region):
        raise NotAllowed()
    if (service, operation) in LISTS:
        if extra or isinstance(max_items, bool) or not isinstance(max_items, int) \
                or not 1 <= max_items <= MAX_ITEMS_LIMIT:
            raise NotAllowed()
        flags = LISTS[(service, operation)][1]
        middle = (*flags, "--max-items", str(max_items))
    elif (service, operation) == ("sqs", "get-queue-attributes"):
        if len(extra) != 4 or extra[0] != "--queue-url" or extra[2] != "--attribute-names" \
                or extra[3] != "RedrivePolicy" or not isinstance(extra[1], str) or not QUEUE_URL_RE.match(extra[1]):
            raise NotAllowed()
        middle = extra
    elif (service, operation) == ("sns", "get-subscription-attributes"):
        if len(extra) != 2 or extra[0] != "--subscription-arn" or not isinstance(extra[1], str) \
                or not SUBSCRIPTION_ARN_RE.match(extra[1]):
            raise NotAllowed()
        middle = extra
    else:
        raise NotAllowed()
    return ["aws", service, operation, *middle, "--region", region, *COMMON]


def cli_environment() -> dict:
    """Environment of the AWS CLI: ATLAS_COLLECTOR_PROFILE -> AWS_PROFILE without the static keys; without it, the
    machine's default chain (the environment as it is)."""
    env = dict(os.environ)
    profile = env.pop("ATLAS_COLLECTOR_PROFILE", "")
    if profile:
        for name in STATIC_KEYS:
            env.pop(name, None)
        env["AWS_PROFILE"] = profile
    return env


def classify(stderr: str, service: str, operation: str, region: str) -> str:
    if LOGIN_RE.search(stderr):
        return "login da nuvem expirado — renove o login da nuvem"
    if PROFILE_RE.search(stderr):
        return "profile da AWS não encontrado — confira credentials.<id>.profile"
    if NO_CREDENTIALS_RE.search(stderr):
        return "sem credencial da AWS — declare o profile em credentials do coletor"
    if DENIED_RE.search(stderr):
        return f"sem permissão para {service} {operation} em {region}"
    if TIMEOUT_RE.search(stderr):
        return f"tempo esgotado em {service} {operation} ({region})"
    return f"falha da AWS CLI em {service} {operation} ({region})"


def run_cli(executable: str, args: list, env: dict, service: str, operation: str, region: str) -> str:
    """The only external process of the collector: one AWS CLI call built by build_call, argv as a list, never a
    shell, stdin closed, with a timeout. Returns its stdout; a failure becomes a fixed CollectorError."""
    try:
        proc = subprocess.run([executable, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=CALL_TIMEOUT, env=env, check=False)
    except FileNotFoundError:
        raise CollectorError("AWS CLI não encontrada no PATH") from None
    except subprocess.TimeoutExpired:
        raise CollectorError(f"tempo esgotado em {service} {operation} ({region})") from None
    except OSError:
        raise CollectorError(f"falha da AWS CLI em {service} {operation} ({region})") from None
    if proc.returncode != 0:
        raise CollectorError(classify(proc.stderr or "", service, operation, region))
    return proc.stdout


class Cli:
    """Runs the calls of build_call: the only external process of the collector."""

    def __init__(self, max_items: int):
        self.max_items = max_items
        self.env = cli_environment()
        self.executable = None

    def run(self, service: str, operation: str, region: str, extra=()) -> dict:
        argv = build_call(service, operation, region, self.max_items, extra)
        if self.executable is None:
            self.executable = shutil.which("aws", path=self.env.get("PATH"))
            if self.executable is None:
                raise CollectorError("AWS CLI não encontrada no PATH")
        stdout = run_cli(self.executable, argv[1:], self.env, service, operation, region)
        invalid = f"resposta inválida da AWS CLI em {service} {operation}"
        try:
            data = json.loads(stdout or "{}")
        except ValueError:
            raise CollectorError(invalid) from None
        if not isinstance(data, dict):
            raise CollectorError(invalid)
        if (service, operation) in LISTS:
            if data.get("NextToken"):
                raise CollectorError(f"limite de {self.max_items} itens atingido em {service} {operation} "
                                     f"({region}) — aumente --max-items")
            items = data.get(LISTS[(service, operation)][0], [])
            if not isinstance(items, list):
                raise CollectorError(invalid)
        return data

    def items(self, service: str, operation: str, region: str) -> list:
        return self.run(service, operation, region).get(LISTS[(service, operation)][0], []) or []


# --------------------------------------------------------------------------- data: rds and elasticache


def datastore(region: str, kind_type: str, engine, endpoint, serverless: bool, reader=None) -> dict:
    """attrs of one datastore; endpoint = (host, port) or None."""
    attrs = {"type": kind_type, "region": region, "serverless": serverless}
    if _text(engine):
        attrs["engine"] = engine.lower()
    host, port = endpoint if endpoint else (None, None)
    if _text(host):
        attrs["host"] = host
        port = _port(port)
        if port is not None:
            attrs["port"] = port
    if _text(reader):
        attrs["reader_host"] = reader
    return attrs


def _endpoint(value):
    value = _dict(value)
    return (value.get("Address"), value.get("Port")) if _text(value.get("Address")) else None


def collect_rds(cli: Cli, region: str) -> list:
    found = []
    for cluster in cli.items("rds", "describe-db-clusters", region):
        cluster = _dict(cluster)
        cid = _text(cluster.get("DBClusterIdentifier"))
        if not cid:
            continue
        serverless = cluster.get("EngineMode") == "serverless" or \
            cluster.get("ServerlessV2ScalingConfiguration") is not None
        endpoint = (cluster["Endpoint"], cluster.get("Port")) if _text(cluster.get("Endpoint")) else None
        found.append(("datastore", cid, datastore(region, "rds", cluster.get("Engine"), endpoint, serverless,
                                                  cluster.get("ReaderEndpoint"))))
    for instance in cli.items("rds", "describe-db-instances", region):
        instance = _dict(instance)
        iid = _text(instance.get("DBInstanceIdentifier"))
        if not iid or instance.get("DBClusterIdentifier"):
            continue
        found.append(("datastore", iid, datastore(region, "rds", instance.get("Engine"),
                                                  _endpoint(instance.get("Endpoint")), False)))
    return found


def collect_elasticache(cli: Cli, region: str) -> list:
    groups = [_dict(g) for g in cli.items("elasticache", "describe-replication-groups", region)]
    clusters = [_dict(c) for c in cli.items("elasticache", "describe-cache-clusters", region)]
    found = []
    for group in groups:
        gid = _text(group.get("ReplicationGroupId"))
        if not gid:
            continue
        engine = group.get("Engine") or next((c.get("Engine") for c in clusters
                                              if c.get("ReplicationGroupId") == gid and _text(c.get("Engine"))), None)
        node_groups = group.get("NodeGroups") if isinstance(group.get("NodeGroups"), list) else []
        first = _dict(node_groups[0]) if node_groups else {}
        endpoint = _endpoint(group.get("ConfigurationEndpoint")) or _endpoint(first.get("PrimaryEndpoint"))
        reader = _dict(first.get("ReaderEndpoint")).get("Address")
        found.append(("datastore", gid, datastore(region, "elasticache", engine, endpoint, False, reader)))
    for cluster in clusters:
        cid = _text(cluster.get("CacheClusterId"))
        if not cid or cluster.get("ReplicationGroupId"):
            continue
        nodes = cluster.get("CacheNodes") if isinstance(cluster.get("CacheNodes"), list) else []
        endpoint = _endpoint(cluster.get("ConfigurationEndpoint")) or \
            (_endpoint(_dict(nodes[0]).get("Endpoint")) if nodes else None)
        found.append(("datastore", cid, datastore(region, "elasticache", cluster.get("Engine"), endpoint, False)))
    for cache in cli.items("elasticache", "describe-serverless-caches", region):
        cache = _dict(cache)
        name = _text(cache.get("ServerlessCacheName"))
        if not name:
            continue
        found.append(("datastore", name, datastore(region, "elasticache", cache.get("Engine"),
                                                   _endpoint(cache.get("Endpoint")), True,
                                                   _dict(cache.get("ReaderEndpoint")).get("Address"))))
    return found


# --------------------------------------------------------------------------- messaging: sqs and sns


def _arn(value):
    """(service, region, account, name) of an SQS/SNS resource ARN, else None."""
    match = RESOURCE_ARN_RE.match(value) if isinstance(value, str) else None
    return match.groups() if match else None


def collect_sqs(cli: Cli, region: str, state: dict) -> list:
    found = []
    for url in cli.items("sqs", "list-queues", region):
        if not isinstance(url, str) or not QUEUE_URL_RE.match(url):
            continue
        account, name = url.rstrip("/").split("/")[-2:]
        if not NAME_RE.match(name):
            continue
        attrs = {"type": "sqs", "fifo": name.endswith(".fifo"), "region": region}
        found.append(("queue", name, attrs))
        answer = cli.run("sqs", "get-queue-attributes", region,
                         ("--queue-url", url, "--attribute-names", "RedrivePolicy"))
        policy = _dict(answer.get("Attributes")).get("RedrivePolicy")
        if policy is None:
            continue
        try:
            target = _arn(_dict(json.loads(policy)).get("deadLetterTargetArn")) if isinstance(policy, str) else None
        except ValueError:
            target = None
        if target and target[0] == "sqs" and target[2] == account:
            state["redrive"][(name, region)] = (target[3], target[1])
        else:
            state["outside_dlq"] += 1
    return found


def collect_sns(cli: Cli, region: str, state: dict) -> list:
    found = []
    for topic in cli.items("sns", "list-topics", region):
        parsed = _arn(_dict(topic).get("TopicArn"))
        if parsed and parsed[0] == "sns":
            name = parsed[3]
            found.append(("topic", name, {"type": "sns", "fifo": name.endswith(".fifo"), "region": region}))
    for item in cli.items("sns", "list-subscriptions", region):
        item = _dict(item)
        if item.get("Protocol") != "sqs":
            continue
        arn = item.get("SubscriptionArn")
        if arn == "PendingConfirmation":
            state["pending"] += 1
            continue
        topic, queue = _arn(item.get("TopicArn")), _arn(item.get("Endpoint"))
        if not isinstance(arn, str) or not SUBSCRIPTION_ARN_RE.match(arn) or not topic or not queue \
                or topic[0] != "sns" or queue[0] != "sqs":
            continue
        answer = cli.run("sns", "get-subscription-attributes", region, ("--subscription-arn", arn))
        filtered = bool(_text(_dict(answer.get("Attributes")).get("FilterPolicy")))
        state["subscriptions"].append((topic[3], queue[3], queue[1], filtered))
    return found


# --------------------------------------------------------------------------- assembly


def _has_twelve_digits(eid: str, attrs: dict) -> bool:
    values = [eid]
    for value in attrs.values():
        values += value if isinstance(value, list) else [value]
    return any(isinstance(v, str) and TWELVE_DIGITS.search(v) for v in values)


def collect(services: list, regions: list, cli: Cli) -> tuple:
    """(category, entities, relations, stderr lines) of one run."""
    state = {"redrive": {}, "outside_dlq": 0, "pending": 0, "subscriptions": []}
    kept, ignored, repeated = {}, 0, 0
    for region in regions:
        found = []
        for service in services:
            if service == "rds":
                found += collect_rds(cli, region)
            elif service == "elasticache":
                found += collect_elasticache(cli, region)
            elif service == "sqs":
                found += collect_sqs(cli, region, state)
            else:
                found += collect_sns(cli, region, state)
        for kind, eid, attrs in found:
            if _has_twelve_digits(eid, attrs):
                ignored += 1
            elif (kind, eid) in kept:
                repeated += 1
            else:
                kept[(kind, eid)] = attrs
    queues = {eid: attrs for (kind, eid), attrs in kept.items() if kind == "queue"}
    for (name, region), (target, target_region) in sorted(state["redrive"].items()):
        attrs = queues.get(name)
        if attrs is None or attrs["region"] != region:
            continue  # the queue itself was dropped or repeated
        other = queues.get(target)
        if target != name and other is not None and other["region"] == target_region:
            attrs["dlq"] = target
        else:
            state["outside_dlq"] += 1
    relations = set()
    for topic, queue, queue_region, filtered in state["subscriptions"]:
        if TWELVE_DIGITS.search(topic) or TWELVE_DIGITS.search(queue):
            ignored += 1
            continue
        relations.add((f"topic:{topic}", "publishes", f"queue:{queue}"))
        attrs = queues.get(queue)
        if filtered and attrs is not None and attrs["region"] == queue_region:
            attrs["filtered_topics"] = sorted(set(attrs.get("filtered_topics", [])) | {topic})
    entities = [{"kind": kind, "id": eid, "name": eid, "attrs": attrs, "source": COLLECTOR}
                for (kind, eid), attrs in sorted(kept.items(), key=lambda kv: f"{kv[0][0]}:{kv[0][1]}")]
    rels = [{"from": f, "to": t, "type": rtype, "source": COLLECTOR} for f, rtype, t in sorted(relations)]
    lines = []
    if ignored:
        lines.append(f"{ignored} recurso(s) ignorado(s): 12 dígitos seguidos")
    if repeated:
        lines.append(f"{repeated} recurso(s) repetido(s) em outra região ignorado(s)")
    if state["outside_dlq"]:
        lines.append(f"{state['outside_dlq']} DLQ(s) ilegível(is) ou fora do snapshot omitida(s)")
    if state["pending"]:
        lines.append(f"{state['pending']} assinatura(s) pendente(s) ignorada(s)")
    return CATEGORIES[services[0]], entities, rels, lines


# --------------------------------------------------------------------------- arguments


class Usage(Exception):
    """Invalid arguments: exit 2 with the fixed message."""


def parse_services(text) -> list:
    names = [s.strip() for s in (text or "").split(",") if s.strip()]
    if not names or any(n not in CATEGORIES for n in names):
        raise Usage(MSG_SERVICES)
    if len({CATEGORIES[n] for n in names}) > 1:
        raise Usage(MSG_MIXED)
    return [s for s in SERVICE_ORDER if s in names]


def parse_regions(text) -> list:
    regions = [r.strip() for r in (text or "").split(",")]
    if not 1 <= len(regions) <= MAX_REGIONS or len(set(regions)) != len(regions) \
            or any(not REGION_RE.match(r) for r in regions):
        raise Usage(MSG_REGION)
    return regions


def parse_max_items(text) -> int:
    text = str(text).strip()
    if not text.isdigit() or not 1 <= int(text) <= MAX_ITEMS_LIMIT:
        raise Usage(MSG_MAX_ITEMS)
    return int(text)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, f"aws: {message}\n")


def build_parser():
    parser = Parser(prog="aws.py", description="Coletor aws da boson-atlas")
    parser.add_argument("--services", required=True, help="rds,elasticache (data) ou sqs,sns (messaging)")
    parser.add_argument("--region", required=True, help="regiões separadas por vírgula (até 10)")
    parser.add_argument("--max-items", default=str(DEFAULT_MAX_ITEMS), help="itens por lista (1 a 10000)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        services = parse_services(args.services)
        regions = parse_regions(args.region)
        max_items = parse_max_items(args.max_items)
    except Usage as e:
        print(f"aws: {e}", file=sys.stderr)
        return 2
    try:
        category, entities, relations, lines = collect(services, regions, Cli(max_items))
    except CollectorError as e:
        print(f"aws: {e}", file=sys.stderr)
        return 1
    data = {"contract": CONTRACT, "collector": COLLECTOR, "category": category, "collected_at": utc_now(),
            "entities": entities, "relations": relations}
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    for line in lines:
        print(f"aws: {line}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
