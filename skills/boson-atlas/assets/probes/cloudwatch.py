#!/usr/bin/env python3
"""cloudwatch probe adapter of the boson-atlas (SPEC-0100, ADR-0025, ADR-0026), contract probe@2 (SPEC-0096).

Usage: python3 cloudwatch.py --describe     -> the capabilities (signals: metrics)
       python3 cloudwatch.py < input.json   -> reads the probe@2 input on stdin, prints the probe@2 output

Read only: the one external process is the machine's AWS CLI, run with an argv list (never a shell) built only from
target.resource (kind, id and attrs type, engine, serverless, region), target.cloud.profile and limits, and from a
closed list (SPEC-0100, section 6):
    elasticache describe-replication-groups --replication-group-id <id>      (only the "elasticache" set, at most 1)
    cloudwatch get-metric-data --metric-data-queries <JSON built here, only MetricStat of the fixed table>
        --start-time <ISO> --end-time <ISO> --scan-by TimestampAscending [--next-token <token>]   (up to 5 pages)
always with --region, --profile, --output json, --no-cli-pager, --cli-read-timeout 20 and --cli-connect-timeout 10.
No metric name, namespace, dimension, statistic or expression comes from the input: only the resource name (checked
by regex) goes into the dimension value. Anything else is refused ("chamada não permitida") before any call. Errors
leave with exit 0 and status "error" with a fixed message; the profile, the stderr of the CLI, ARNs and account ids
are never printed (12 digits are masked here too). The core (atlas.py probe) applies the redaction and the limits
again. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

CONTRACT = "probe@2"
ADAPTER = "cloudwatch"
CAPABILITY = "signals"
VERB = "metrics"
TARGETS = ("datastore", "queue", "topic")
DESCRIBE = {"contract": CONTRACT, "adapter": ADAPTER,
            "capabilities": {CAPABILITY: {"verbs": [VERB], "targets": list(TARGETS), "access": ["cloud"]}}}
# the closed list: (service, operation) -> the options of the operation itself
OPERATIONS = {
    ("cloudwatch", "get-metric-data"): ("--metric-data-queries", "--start-time", "--end-time", "--scan-by",
                                        "--next-token"),
    ("elasticache", "describe-replication-groups"): ("--replication-group-id",),
}
READ_TIMEOUT, CONNECT_TIMEOUT = "20", "10"
PROCESS_TIMEOUT = 30  # seconds for one aws process
MAX_PAGES = 5
MAX_NODES = 6
MAX_QUERIES = 60
MAX_LINES = 2000
MAX_WINDOW = 86400
STATS = {"sum": "Sum", "avg": "Average", "max": "Maximum", "min": "Minimum"}

# the fixed sets of section 6: set -> (namespace, dimension, [(metric, kind, stat, unit)]), in table order
SETS = {
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
        ("ACUUtilization", "saturation", "max", "Percent"),  # only with serverless: true
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
SERVERLESS_ONLY = {("rds-aurora", "ACUUtilization")}
KIND_TYPES = {"queue": "sqs", "topic": "sns"}  # the type a queue / topic has (also when attrs.type is absent)

WORD_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}\Z")
RDS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,62}\Z")
CACHE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,39}\Z")
NODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,49}\Z")  # a member CacheClusterId (group id + node suffix)
QUEUE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,79}(\.fifo)?\Z")  # never starting with "-" (section 5)
TOPIC_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,255}(\.fifo)?\Z")
NAME_RES = {"rds": RDS_RE, "rds-aurora": RDS_RE, "elasticache": CACHE_RE, "elasticache-serverless": CACHE_RE,
            "sqs": QUEUE_RE, "sns": TOPIC_RE}
REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}\Z")
PROFILE_RE = re.compile(r"^[A-Za-z0-9_.+][A-Za-z0-9_.+-]{0,63}\Z")
ACCOUNT_ANY_RE = re.compile(r"\b[0-9]{12}\b")
REDACTED = "[REDACTED]"
# the contract messages (SPEC-0100, section 6)
NOT_FOUND = "aws não encontrado"
LOGIN = "renove o login da nuvem"
NO_PROFILE = "profile inexistente"
NO_CREDENTIALS = "sem credenciais da nuvem"
DENIED = "sem permissão (AccessDenied)"
THROTTLED = "limite de chamadas da nuvem"
NO_CONNECTION = "sem conexão com a nuvem"
TIMEOUT = "timeout"
NO_REGION = "recurso sem região no atlas"
NO_SIGNALS = "tipo de recurso sem sinais"
REFUSED = "chamada não permitida"
INVALID_INPUT = "entrada inválida"
AWS_FAILED = "falha da aws"
INVALID_ANSWER = "resposta inválida da aws"
NO_DATA = "sem dados na janela"
PARTIAL = "dados parciais"
NO_GROUP = "sem grupo"  # internal: ReplicationGroupNotFoundFault, handled by the caller (never printed)
ERROR_RULES = (  # (message, markers in the stderr), in order (the same triggers as aws-messaging, SPEC-0098)
    (LOGIN, ("Token has expired", "SSO session", "UnauthorizedSSOTokenError", "Error loading SSO Token",
             "ExpiredToken", "RequestExpired", "security token included in the request is expired")),
    (NO_PROFILE, ("could not be found",)),
    (NO_CREDENTIALS, ("Unable to locate credentials",)),
    (DENIED, ("AccessDenied", "AuthorizationError", "not authorized")),
    (THROTTLED, ("Throttling", "Rate exceeded")),
    (TIMEOUT, ("Read timeout", "Connect timeout")),
    (NO_CONNECTION, ("Could not connect to the endpoint URL", "Name or service not known",
                     "nodename nor servname", "getaddrinfo failed", "Temporary failure in name resolution")),
    (NO_GROUP, ("ReplicationGroupNotFoundFault",)),
)


class ProbeError(Exception):
    """An error with one of the fixed messages: becomes status "error" (exit 0)."""


# ---------------------------------------------------------------- input


def has_control(value):
    return isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value)


def metric_set(kind, attrs):
    """The set of the table for the resource (section 6), or ProbeError (NO_SIGNALS, INVALID_INPUT)."""
    rtype = attrs.get("type")
    serverless = attrs.get("serverless")
    if serverless is not None and not isinstance(serverless, bool):
        raise ProbeError(INVALID_INPUT)
    if kind in KIND_TYPES:
        if rtype is not None and rtype != KIND_TYPES[kind]:
            raise ProbeError(NO_SIGNALS)
        return KIND_TYPES[kind]
    if kind != "datastore":
        raise ProbeError(NO_SIGNALS)
    engine = attrs.get("engine")
    engine = engine if isinstance(engine, str) else ""
    if rtype == "rds":
        return "rds-aurora" if engine.startswith("aurora") else "rds"
    if rtype == "elasticache":
        if serverless is True:
            return "elasticache-serverless"
        if engine in ("valkey", "redis"):
            return "elasticache"
    raise ProbeError(NO_SIGNALS)


def check_input(data):
    """(set, name, region, serverless, profile, lines, since) of a probe@2 input, or ProbeError: INVALID_INPUT for a
    malformed input or a value outside the rules, REFUSED for a capability or verb outside the contract, NO_SIGNALS
    for a resource type without a set, NO_REGION without attrs.region. Nothing here calls the aws."""
    if not isinstance(data, dict) or data.get("contract") != CONTRACT:
        raise ProbeError(INVALID_INPUT)
    target, limits = data.get("target"), data.get("limits")
    if not isinstance(target, dict) or not isinstance(limits, dict):
        raise ProbeError(INVALID_INPUT)
    lines, since = limits.get("lines"), limits.get("since_seconds")
    for value in (lines, since):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ProbeError(INVALID_INPUT)
    if since > MAX_WINDOW:
        raise ProbeError(INVALID_INPUT)
    cloud, resource = target.get("cloud"), target.get("resource")
    if not isinstance(cloud, dict) or not isinstance(resource, dict):
        raise ProbeError(INVALID_INPUT)
    profile = cloud.get("profile")
    if not isinstance(profile, str) or has_control(profile) or not PROFILE_RE.match(profile):
        raise ProbeError(INVALID_INPUT)
    kind, name, attrs = resource.get("kind"), resource.get("id"), resource.get("attrs")
    if not isinstance(kind, str) or not isinstance(name, str) or not isinstance(attrs, dict):
        raise ProbeError(INVALID_INPUT)
    if any(has_control(v) for v in (kind, name, *attrs.values())):
        raise ProbeError(INVALID_INPUT)
    if data.get("capability") != CAPABILITY or data.get("verb") != VERB:
        raise ProbeError(REFUSED)
    chosen = metric_set(kind, attrs)
    region = attrs.get("region")
    if region is None or region == "":
        raise ProbeError(NO_REGION)
    if not isinstance(region, str) or not REGION_RE.match(region):
        raise ProbeError(INVALID_INPUT)
    if not NAME_RES[chosen].match(name):
        raise ProbeError(INVALID_INPUT)
    # only type, engine, serverless and region are ever used: metric, namespace, ARN or URL attributes are ignored
    return chosen, name, region, attrs.get("serverless") is True, profile, min(lines, MAX_LINES), since


# ---------------------------------------------------------------- aws


class Aws:
    """The only door to the AWS CLI: an operation of the closed list, with the common options of section 6."""

    def __init__(self, region, profile):
        self.region, self.profile = region, profile
        self.executable = None

    def call(self, service, operation, options=()):
        """The JSON object answered by `aws <service> <operation> <options...>`; ProbeError with a fixed message
        (NO_GROUP for a replication group that does not exist)."""
        allowed = OPERATIONS.get((service, operation))
        if allowed is None:
            raise ProbeError(REFUSED)
        argv = [service, operation]
        for option, value in options:
            if option not in allowed or not isinstance(value, str) or not value or value.startswith("-") \
                    or has_control(value):
                raise ProbeError(REFUSED)
            argv += [option, value]
        argv += ["--region", self.region, "--profile", self.profile, "--output", "json", "--no-cli-pager",
                 "--cli-read-timeout", READ_TIMEOUT, "--cli-connect-timeout", CONNECT_TIMEOUT]
        if self.executable is None:
            self.executable = shutil.which("aws") or ""
        if not self.executable:
            raise ProbeError(NOT_FOUND)
        try:
            proc = subprocess.run([self.executable, *argv], stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=PROCESS_TIMEOUT,
                                  check=False)
        except subprocess.TimeoutExpired:
            raise ProbeError(TIMEOUT) from None
        except OSError:
            raise ProbeError(NOT_FOUND) from None
        if proc.returncode != 0:
            raise ProbeError(classify(proc.stderr or ""))
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            raise ProbeError(INVALID_ANSWER) from None
        if not isinstance(data, dict):
            raise ProbeError(INVALID_ANSWER)
        return data


def classify(stderr):
    """The fixed message for a failed aws: never its text (it may quote the profile, an ARN or the account)."""
    for message, markers in ERROR_RULES:
        if any(marker in stderr for marker in markers):
            return message
    return AWS_FAILED


# ---------------------------------------------------------------- metrics


def cache_nodes(aws, group):
    """(node ids, truncated) of a replication group: up to 6, in name order; without a group, the id itself."""
    try:
        data = aws.call("elasticache", "describe-replication-groups", [("--replication-group-id", group)])
    except ProbeError as error:
        if str(error) == NO_GROUP:
            return [group], False
        raise
    groups = data.get("ReplicationGroups")
    if not isinstance(groups, list) or len(groups) != 1 or not isinstance(groups[0], dict):
        raise ProbeError(INVALID_ANSWER)
    found = set()
    members = groups[0].get("MemberClusters") or []
    node_groups = groups[0].get("NodeGroups") or []
    if not isinstance(members, list) or not isinstance(node_groups, list):
        raise ProbeError(INVALID_ANSWER)
    found.update(members)
    for node_group in node_groups:
        rows = node_group.get("NodeGroupMembers") or [] if isinstance(node_group, dict) else None
        if not isinstance(rows, list):
            raise ProbeError(INVALID_ANSWER)
        found.update(row.get("CacheClusterId") for row in rows if isinstance(row, dict))
    found.discard(None)
    if not found or any(not isinstance(node, str) or not NODE_RE.match(node) for node in found):
        raise ProbeError(INVALID_ANSWER)
    nodes = sorted(found)
    return nodes[:MAX_NODES], len(nodes) > MAX_NODES


def rows_of(chosen, serverless):
    return [row for row in SETS[chosen][2] if serverless or (chosen, row[0]) not in SERVERLESS_ONLY]


def build_queries(chosen, rows, values, period):
    """[(Id, row index)] and the MetricDataQueries: one MetricStat per metric and per dimension value."""
    namespace, dimension, _ = SETS[chosen]
    index, queries = [], []
    for r, (metric, _kind, stat, _unit) in enumerate(rows):
        for n, value in enumerate(values):
            qid = f"m{r}_{n}"
            index.append((qid, r))
            queries.append({"Id": qid, "MetricStat": {
                "Metric": {"Namespace": namespace, "MetricName": metric,
                           "Dimensions": [{"Name": dimension, "Value": value}]},
                "Period": period, "Stat": STATS[stat]}, "ReturnData": True, "Label": metric})
    if len(queries) > MAX_QUERIES:
        raise ProbeError(REFUSED)
    return index, queries


def read_pages(aws, queries, start, end):
    """({Id: [values]}, failed Ids, truncated) of up to 5 pages of get-metric-data; PartialData counts only on the
    last page read (Emenda v2)."""
    ids = {q["Id"] for q in queries}
    points = {qid: [] for qid in ids}
    failed = set()
    options = [("--metric-data-queries", json.dumps(queries, separators=(",", ":"))),
               ("--start-time", start), ("--end-time", end), ("--scan-by", "TimestampAscending")]
    token = None
    for page in range(MAX_PAGES):
        data = aws.call("cloudwatch", "get-metric-data",
                        options + ([("--next-token", token)] if token else []))
        results = data.get("MetricDataResults")
        if not isinstance(results, list):
            raise ProbeError(INVALID_ANSWER)
        partial = False
        for result in results:
            qid = result.get("Id") if isinstance(result, dict) else None
            values = result.get("Values") or [] if qid in ids else None
            if not isinstance(values, list):
                raise ProbeError(INVALID_ANSWER)
            for value in values:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not finite(value):
                    raise ProbeError(INVALID_ANSWER)
            points[qid].extend(values)
            code = result.get("StatusCode")
            if code in ("Forbidden", "InternalError"):
                failed.add(qid)
            elif code == "PartialData":
                partial = True
        token = data.get("NextToken")
        if token is not None and not (isinstance(token, str) and token):
            raise ProbeError(INVALID_ANSWER)
        if not token:
            return points, failed, partial
    return points, failed, True  # the 5th page still had a NextToken, or said PartialData


def finite(value):
    """True only for a number that is finite as a float; a huge integer (OverflowError) is not."""
    try:
        return math.isfinite(float(value))
    except (OverflowError, ArithmeticError):
        return False


def aggregate(stat, values):
    if not values:
        return None
    try:
        if stat == "sum":
            result = sum(values)
        elif stat == "avg":
            result = sum(values) / len(values)
        else:
            result = max(values) if stat == "max" else min(values)
    except (OverflowError, ArithmeticError):
        raise ProbeError(INVALID_ANSWER) from None
    if not finite(result):
        raise ProbeError(INVALID_ANSWER)  # e.g. 1e308 + 1e308 is inf: never "value": Infinity
    return result


def run_metrics(aws, chosen, name, serverless, lines, since):
    truncated, nodes = False, None
    values = [name]
    if chosen == "elasticache":
        values, truncated = cache_nodes(aws, name)
        nodes = len(values)
    period = max(60, math.ceil(since / 60 / 60) * 60)
    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(seconds=since)
    rows = rows_of(chosen, serverless)
    index, queries = build_queries(chosen, rows, values, period)
    points, failed, partial = read_pages(aws, queries, start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                         end.strftime("%Y-%m-%dT%H:%M:%SZ"))
    joined = [[] for _ in rows]
    broken = [False for _ in rows]
    for qid, r in index:
        joined[r].extend(points[qid])
        broken[r] = broken[r] or qid in failed
    items = []
    for r, (metric, kind, stat, unit) in enumerate(rows):
        found = [] if broken[r] else joined[r]
        item = {"name": metric, "stat": stat, "value": aggregate(stat, found), "kind": kind, "unit": unit,
                "period": period, "datapoints": len(found)}
        if nodes is not None:
            item["nodes"] = nodes
        items.append(item)
    if failed:
        message = PARTIAL
    elif all(item["datapoints"] == 0 for item in items):
        message = NO_DATA
    else:
        message = None
    truncated = truncated or partial or len(items) > lines
    return items[:lines], truncated, message


# ---------------------------------------------------------------- main


def mask(value):
    """Account ids (12 digits) out of every text of the output, besides the core's mask (SPEC-0100)."""
    if isinstance(value, str):
        return ACCOUNT_ANY_RE.sub(REDACTED, value)
    if isinstance(value, list):
        return [mask(v) for v in value]
    if isinstance(value, dict):
        return {k: mask(v) for k, v in value.items()}
    return value


def answer(data, status, items, truncated, message=None):
    verb = data.get("verb") if isinstance(data, dict) else None
    output = {"contract": CONTRACT, "adapter": ADAPTER, "capability": CAPABILITY,
              "verb": verb if isinstance(verb, str) and WORD_RE.match(verb) else VERB, "status": status,
              "items": items, "truncated": truncated}
    if isinstance(data, dict) and isinstance(data.get("capability"), str) and WORD_RE.match(data["capability"]):
        output["capability"] = data["capability"]
    if message:
        output["message"] = message
    return mask(output)


def probe(data):
    try:
        chosen, name, region, serverless, profile, lines, since = check_input(data)
        items, truncated, message = run_metrics(Aws(region, profile), chosen, name, serverless, lines, since)
    except ProbeError as error:
        return answer(data, "error", [], False, str(error))
    except (AttributeError, TypeError, ValueError, KeyError, OverflowError):
        # a shape not foreseen: still a fixed message, never a traceback
        return answer(data, "error", [], False, INVALID_ANSWER)
    return answer(data, "ok", items, truncated, message)


def main(argv):
    if argv == ["--describe"]:
        print(json.dumps(DESCRIBE))
        return 0
    if argv:
        print("uso: cloudwatch.py --describe | cloudwatch.py < entrada.json", file=sys.stderr)
        return 2
    try:
        data = json.loads(sys.stdin.read())
    except ValueError:
        data = None
    print(json.dumps(probe(data), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
