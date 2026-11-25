#!/usr/bin/env python3
"""aws-messaging probe adapter of the boson-atlas (SPEC-0098, ADR-0025, ADR-0026), contract probe@2 (SPEC-0096).

Usage: python3 aws-messaging.py --describe     -> the capabilities (messaging: queue, subscriptions)
       python3 aws-messaging.py < input.json   -> reads the probe@2 input on stdin, prints the probe@2 output

Read only: the one external process is the machine's AWS CLI, run with an argv list (never a shell) built only from
target.resource (id and attrs), target.cloud.profile and limits, and from a closed list (SPEC-0098, section 6):
    sqs get-queue-url --queue-name <name>
    sqs get-queue-attributes --queue-url <url from get-queue-url> --attribute-names ApproximateNumberOfMessages
        ApproximateNumberOfMessagesNotVisible ApproximateNumberOfMessagesDelayed RedrivePolicy
    cloudwatch get-metric-data --metric-data-queries <1 query: AWS/SQS ApproximateAgeOfOldestMessage> ...
    sts get-caller-identity
    sns list-subscriptions-by-topic --topic-arn <built from the caller identity>
    sns get-subscription-attributes --subscription-arn <arn from the listing, checked by regex>
always with --region, --profile, --output json, --no-cli-pager, --cli-read-timeout 20 and --cli-connect-timeout 10.
No message is ever read, received, deleted or moved, and no Policy is read. Anything else is refused ("chamada não
permitida") before any call. Errors leave with exit 0 and status "error" with a fixed message; the profile, the
stderr of the CLI, ARNs, URLs and account ids are never printed (12 digits are masked here too). The core (atlas.py
probe) applies the redaction and the limits again. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

CONTRACT = "probe@2"
ADAPTER = "aws-messaging"
CAPABILITY = "messaging"
VERB_KINDS = {"queue": "queue", "subscriptions": "topic"}  # verb -> the only resource kind it accepts
KIND_TYPES = {"queue": "sqs", "topic": "sns"}  # the attrs.type each kind accepts (when present)
DESCRIBE = {"contract": CONTRACT, "adapter": ADAPTER,
            "capabilities": {CAPABILITY: {"verbs": list(VERB_KINDS), "targets": ["queue", "topic"],
                                          "access": ["cloud"]}}}
QUEUE_ATTRIBUTES = ("ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible",
                    "ApproximateNumberOfMessagesDelayed", "RedrivePolicy")
# the closed list: (service, operation) -> the options of the operation itself
OPERATIONS = {
    ("sqs", "get-queue-url"): ("--queue-name",),
    ("sqs", "get-queue-attributes"): ("--queue-url", "--attribute-names"),
    ("cloudwatch", "get-metric-data"): ("--metric-data-queries", "--start-time", "--end-time", "--scan-by"),
    ("sts", "get-caller-identity"): (),
    ("sns", "list-subscriptions-by-topic"): ("--topic-arn",),
    ("sns", "get-subscription-attributes"): ("--subscription-arn",),
}
READ_TIMEOUT, CONNECT_TIMEOUT = "20", "10"
PROCESS_TIMEOUT = 30  # seconds for one aws process
MAX_SUBSCRIPTIONS = 100
MAX_LINES = 2000
AGE_WINDOW = 600  # seconds of ApproximateAgeOfOldestMessage read (period 60 s, the most recent point)
WORD_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}\Z")
QUEUE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,79}(\.fifo)?\Z")  # never starting with "-" (section 5)
TOPIC_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,255}(\.fifo)?\Z")
REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}\Z")
PROFILE_RE = re.compile(r"^[A-Za-z0-9_.+][A-Za-z0-9_.+-]{0,63}\Z")
ACCOUNT_RE = re.compile(r"^[0-9]{12}\Z")
ACCOUNT_ANY_RE = re.compile(r"\b[0-9]{12}\b")
PARTITION_RE = re.compile(r"^arn:(aws[a-z-]*):")
QUEUE_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?/[0-9]{12}/(?P<name>[^/\s]+)\Z")
SUBSCRIPTION_ARN_RE = re.compile(r"^arn:aws[a-z-]*:sns:[a-z0-9-]+:[0-9]{12}:[A-Za-z0-9_.-]{1,256}:[A-Za-z0-9-]{1,128}\Z")
SQS_ARN_RE = re.compile(r"^arn:aws[a-z-]*:sqs:[a-z0-9-]+:[0-9]{12}:(?P<name>[^:\s]+)\Z")
LAMBDA_ARN_RE = re.compile(r"^arn:aws[a-z-]*:lambda:[a-z0-9-]+:[0-9]{12}:function:(?P<name>[A-Za-z0-9_-]{1,64})"
                           r"(:[A-Za-z0-9_$-]+)?\Z")
FIREHOSE_ARN_RE = re.compile(r"^arn:aws[a-z-]*:firehose:[a-z0-9-]+:[0-9]{12}:deliverystream/"
                             r"(?P<name>[A-Za-z0-9_.-]{1,64})\Z")
PROTOCOL_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}\Z")
REDACTED = "[REDACTED]"
# the contract messages (SPEC-0098, section 6)
NOT_FOUND = "aws não encontrado"
LOGIN = "renove o login da nuvem"
NO_PROFILE = "profile inexistente"
NO_CREDENTIALS = "sem credenciais da nuvem"
DENIED = "sem permissão (AccessDenied)"
THROTTLED = "limite de chamadas da nuvem"
NO_CONNECTION = "sem conexão com a nuvem"
TIMEOUT = "timeout"
NO_REGION = "recurso sem região no atlas"
NO_QUEUE = "fila não encontrada"
NO_DLQ = "DLQ não encontrada"
NO_TOPIC = "tópico não encontrado"
REFUSED = "chamada não permitida"
INVALID_INPUT = "entrada inválida"
AWS_FAILED = "falha da aws"
INVALID_ANSWER = "resposta inválida da aws"
MISSING = "não existe"  # internal: QueueDoesNotExist / NotFound, mapped by the caller (never printed)
ERROR_RULES = (  # (message, markers in the stderr), in order
    (LOGIN, ("Token has expired", "SSO session", "UnauthorizedSSOTokenError", "Error loading SSO Token",
             "ExpiredToken", "RequestExpired", "security token included in the request is expired")),
    (NO_PROFILE, ("could not be found",)),
    (NO_CREDENTIALS, ("Unable to locate credentials",)),
    (DENIED, ("AccessDenied", "AuthorizationError", "not authorized")),
    (THROTTLED, ("Throttling", "Rate exceeded")),
    (TIMEOUT, ("Read timeout", "Connect timeout")),
    (NO_CONNECTION, ("Could not connect to the endpoint URL", "Name or service not known",
                     "nodename nor servname", "getaddrinfo failed", "Temporary failure in name resolution")),
    (MISSING, ("QueueDoesNotExist", "NonExistentQueue", "specified queue does not exist", "(NotFound)")),
)


class ProbeError(Exception):
    """An error with one of the fixed messages: becomes status "error" (exit 0)."""


# ---------------------------------------------------------------- input


def has_control(value):
    return isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value)


def check_input(data):
    """(verb, name, attrs view, profile, lines) of a probe@2 input, or ProbeError: INVALID_INPUT for a malformed
    input or a value outside the rules, REFUSED for a verb, kind or type outside the list, NO_REGION without
    attrs.region. Nothing here calls the aws."""
    if not isinstance(data, dict) or data.get("contract") != CONTRACT:
        raise ProbeError(INVALID_INPUT)
    target, limits = data.get("target"), data.get("limits")
    if not isinstance(target, dict) or not isinstance(limits, dict):
        raise ProbeError(INVALID_INPUT)
    lines, since = limits.get("lines"), limits.get("since_seconds")
    for value in (lines, since):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
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
    verb = data.get("verb")
    if data.get("capability") != CAPABILITY or verb not in VERB_KINDS or VERB_KINDS[verb] != kind:
        raise ProbeError(REFUSED)
    if "type" in attrs and attrs["type"] != KIND_TYPES[kind]:
        raise ProbeError(REFUSED)
    name_re = QUEUE_RE if kind == "queue" else TOPIC_RE
    if not name_re.match(name):
        raise ProbeError(INVALID_INPUT)
    dlq = attrs.get("dlq") if kind == "queue" else None
    if dlq is not None and not (isinstance(dlq, str) and QUEUE_RE.match(dlq)):
        raise ProbeError(INVALID_INPUT)
    region = attrs.get("region")
    if region is None or region == "":
        raise ProbeError(NO_REGION)
    if not isinstance(region, str) or not REGION_RE.match(region):
        raise ProbeError(INVALID_INPUT)
    # only region and dlq are ever used: an ARN or URL in another attribute is ignored (ADR-0025 rule 4)
    return verb, name, region, dlq, profile, min(lines, MAX_LINES)


# ---------------------------------------------------------------- aws


class Aws:
    """The only door to the AWS CLI: an operation of the closed list, with the common options of section 6."""

    def __init__(self, region, profile):
        self.region, self.profile = region, profile
        self.executable = None

    def call(self, service, operation, options=()):
        """The JSON object answered by `aws <service> <operation> <options...>`; ProbeError with a fixed message
        (MISSING for a queue, topic or subscription that does not exist)."""
        allowed = OPERATIONS.get((service, operation))
        if allowed is None:
            raise ProbeError(REFUSED)
        argv = [service, operation]
        for option, value in options:
            if option not in allowed:
                raise ProbeError(REFUSED)
            values = list(value) if isinstance(value, (list, tuple)) else [value]
            if not values or any(not isinstance(v, str) or not v or v.startswith("-") or has_control(v)
                                 for v in values):
                raise ProbeError(REFUSED)
            argv += [option, *values]
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


def renamed(error, message):
    """The error, with MISSING replaced by the message of what was missing."""
    return ProbeError(message) if str(error) == MISSING else error


# ---------------------------------------------------------------- helpers


def count(value):
    """A SQS counter (text of digits) as an int, or INVALID_ANSWER."""
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise ProbeError(INVALID_ANSWER)


def queue_url(aws, name, missing):
    try:
        data = aws.call("sqs", "get-queue-url", [("--queue-name", name)])
    except ProbeError as error:
        raise renamed(error, missing) from None
    url = data.get("QueueUrl")
    match = QUEUE_URL_RE.match(url) if isinstance(url, str) else None
    if not match or match.group("name") != name:
        raise ProbeError(INVALID_ANSWER)
    return url


def queue_attributes(aws, name, missing):
    url = queue_url(aws, name, missing)
    try:
        data = aws.call("sqs", "get-queue-attributes", [("--queue-url", url), ("--attribute-names", QUEUE_ATTRIBUTES)])
    except ProbeError as error:
        raise renamed(error, missing) from None
    attributes = data.get("Attributes")
    if not isinstance(attributes, dict):
        raise ProbeError(INVALID_ANSWER)
    return attributes


def redrive_target(attributes):
    """The queue name of the RedrivePolicy's deadLetterTargetArn; "" without RedrivePolicy."""
    raw = attributes.get("RedrivePolicy")
    if raw in (None, ""):
        return ""
    try:
        policy = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        raise ProbeError(INVALID_ANSWER) from None
    arn = policy.get("deadLetterTargetArn") if isinstance(policy, dict) else None
    if not isinstance(arn, str) or not arn:
        raise ProbeError(INVALID_ANSWER)
    return arn.rsplit(":", 1)[-1]


def oldest_age(aws, name):
    """(seconds or None, source) from ApproximateAgeOfOldestMessage: the most recent point of the last 10 minutes."""
    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(seconds=AGE_WINDOW)
    query = [{"Id": "age", "MetricStat": {"Metric": {"Namespace": "AWS/SQS", "MetricName": "ApproximateAgeOfOldestMessage",
                                                     "Dimensions": [{"Name": "QueueName", "Value": name}]},
                                          "Period": 60, "Stat": "Maximum"}, "ReturnData": True}]
    try:
        data = aws.call("cloudwatch", "get-metric-data", [
            ("--metric-data-queries", json.dumps(query, separators=(",", ":"))),
            ("--start-time", start.strftime("%Y-%m-%dT%H:%M:%SZ")),
            ("--end-time", end.strftime("%Y-%m-%dT%H:%M:%SZ")), ("--scan-by", "TimestampDescending")])
    except ProbeError as error:
        if str(error) == DENIED:
            return None, "sem permissão"  # only the age is lost (section 6)
        raise
    results = data.get("MetricDataResults")
    if not isinstance(results, list) or any(not isinstance(r, dict) for r in results):
        raise ProbeError(INVALID_ANSWER)
    values = (results[0].get("Values") if results else None) or []
    if not isinstance(values, list):
        raise ProbeError(INVALID_ANSWER)
    if not values:
        return None, "sem dados"
    value = values[0]  # TimestampDescending: the most recent first
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ProbeError(INVALID_ANSWER)
    return round(value), "cloudwatch"


def fingerprint(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def filter_keys(policy, scope):
    """The key paths of a filter policy, sorted; "." between levels in the MessageBody scope; never the values."""
    if scope != "MessageBody":
        return sorted(str(key) for key in policy)
    paths = []

    def walk(node, prefix):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict) and value:
                walk(value, path)
            else:
                paths.append(path)

    walk(policy, "")
    return sorted(paths)


def destination(protocol, endpoint):
    """(destination, destination_fingerprint) of a subscription from the listing: queue:/function:/stream:<name>,
    otherwise <protocol>:[REDACTED]; the fingerprint hashes the protocol and the endpoint without the account."""
    word = protocol if isinstance(protocol, str) and PROTOCOL_RE.match(protocol) else "other"
    endpoint = endpoint if isinstance(endpoint, str) else ""
    shown = f"{word}:{REDACTED}"
    for proto, regex, kind, rule in (("sqs", SQS_ARN_RE, "queue", QUEUE_RE),
                                     ("lambda", LAMBDA_ARN_RE, "function", None),
                                     ("firehose", FIREHOSE_ARN_RE, "stream", None)):
        match = regex.match(endpoint) if word == proto else None
        if match and (rule is None or rule.match(match.group("name"))):
            shown = f"{kind}:{match.group('name')}"
    return shown, fingerprint(word + "\n" + ACCOUNT_ANY_RE.sub(REDACTED, endpoint))


def subscription_item(row, attributes):
    """One item of `subscriptions` (ADR-0026 table 4a and the extra fields); attributes None = not read."""
    shown, digest = destination(row.get("Protocol"), row.get("Endpoint"))
    protocol = row.get("Protocol") if isinstance(row.get("Protocol"), str) and PROTOCOL_RE.match(row["Protocol"]) \
        else "other"
    item = {"destination": shown, "filter_fingerprint": None, "destination_fingerprint": digest,
            "protocol": protocol, "pending_confirmation": row.get("SubscriptionArn") == "PendingConfirmation",
            "raw_delivery": None, "has_filter": None, "filter_scope": None, "filter_keys": None, "has_dlq": None}
    if attributes is None:
        return item
    raw = attributes.get("RawMessageDelivery")
    item["raw_delivery"] = raw == "true" if raw in ("true", "false") else None
    item["has_dlq"] = attributes.get("RedrivePolicy") not in (None, "")
    text = attributes.get("FilterPolicy")
    if text in (None, ""):
        item.update(has_filter=False, filter_keys=[])
        return item
    try:
        policy = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        policy = None
    if not isinstance(policy, dict):
        raise ProbeError(INVALID_ANSWER)
    scope = attributes.get("FilterPolicyScope") or "MessageAttributes"
    if scope not in ("MessageAttributes", "MessageBody"):
        raise ProbeError(INVALID_ANSWER)
    canonical = json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    item.update(has_filter=True, filter_scope=scope, filter_fingerprint=fingerprint(canonical),
                filter_keys=filter_keys(policy, scope))
    return item


# ---------------------------------------------------------------- verbs


def run_queue(aws, name, dlq, lines):
    attributes = queue_attributes(aws, name, NO_QUEUE)
    visible = count(attributes.get("ApproximateNumberOfMessages"))
    in_flight = count(attributes.get("ApproximateNumberOfMessagesNotVisible"))
    delayed = count(attributes.get("ApproximateNumberOfMessagesDelayed"))
    target = redrive_target(attributes)
    item = {"visible": visible, "in_flight": in_flight, "oldest_age_seconds": None, "dlq_visible": None,
            "delayed": delayed, "fifo": name.endswith(".fifo"), "oldest_age_source": "sem dados", "dlq": None,
            "dlq_in_flight": None, "redrive": bool(target), "redrive_matches_dlq": None}
    if dlq:
        dlq_attributes = queue_attributes(aws, dlq, NO_DLQ)
        item.update(dlq=f"queue:{dlq}", dlq_visible=count(dlq_attributes.get("ApproximateNumberOfMessages")),
                    dlq_in_flight=count(dlq_attributes.get("ApproximateNumberOfMessagesNotVisible")))
        if target:
            item["redrive_matches_dlq"] = target == dlq
    age, source = oldest_age(aws, name)
    item.update(oldest_age_seconds=age, oldest_age_source=source)
    return [item], False, None


def run_subscriptions(aws, name, dlq, lines):
    identity = aws.call("sts", "get-caller-identity")
    account, arn = identity.get("Account"), identity.get("Arn")
    partition = PARTITION_RE.match(arn) if isinstance(arn, str) else None
    if not (isinstance(account, str) and ACCOUNT_RE.match(account)) or not partition:
        raise ProbeError(INVALID_ANSWER)
    topic_arn = f"arn:{partition.group(1)}:sns:{aws.region}:{account}:{name}"
    try:
        listing = aws.call("sns", "list-subscriptions-by-topic", [("--topic-arn", topic_arn)])
    except ProbeError as error:
        raise renamed(error, NO_TOPIC) from None
    rows = listing.get("Subscriptions")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ProbeError(INVALID_ANSWER)
    pending = sum(1 for row in rows if row.get("SubscriptionArn") == "PendingConfirmation")
    message = f"{len(rows)} assinaturas, {pending} pendentes"
    ordered = sorted(rows, key=lambda row: destination(row.get("Protocol"), row.get("Endpoint")))
    limit = min(lines, MAX_SUBSCRIPTIONS)
    items = []
    for row in ordered[:limit]:
        sub_arn = row.get("SubscriptionArn")
        attributes = None
        if isinstance(sub_arn, str) and SUBSCRIPTION_ARN_RE.match(sub_arn):
            try:
                data = aws.call("sns", "get-subscription-attributes", [("--subscription-arn", sub_arn)])
            except ProbeError as error:
                raise renamed(error, NO_TOPIC) from None
            attributes = data.get("Attributes")
            if not isinstance(attributes, dict):
                raise ProbeError(INVALID_ANSWER)
        items.append(subscription_item(row, attributes))
    return items, len(rows) > limit, message


VERB_RUNNERS = {"queue": run_queue, "subscriptions": run_subscriptions}


# ---------------------------------------------------------------- main


def mask(value):
    """Account ids (12 digits) out of every text of the output, besides the core's mask (SPEC-0098)."""
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
              "verb": verb if isinstance(verb, str) and WORD_RE.match(verb) else "queue", "status": status,
              "items": items, "truncated": truncated}
    if isinstance(data, dict) and isinstance(data.get("capability"), str) and WORD_RE.match(data["capability"]):
        output["capability"] = data["capability"]
    if message:
        output["message"] = message
    return mask(output)


def probe(data):
    try:
        verb, name, region, dlq, profile, lines = check_input(data)
        items, truncated, message = VERB_RUNNERS[verb](Aws(region, profile), name, dlq, lines)
    except ProbeError as error:
        return answer(data, "error", [], False, str(error))
    except (AttributeError, TypeError, ValueError, KeyError):
        # a shape not foreseen: still a fixed message, never a traceback
        return answer(data, "error", [], False, INVALID_ANSWER)
    return answer(data, "ok", items, truncated, message)


def main(argv):
    if argv == ["--describe"]:
        print(json.dumps(DESCRIBE))
        return 0
    if argv:
        print("uso: aws-messaging.py --describe | aws-messaging.py < entrada.json", file=sys.stderr)
        return 2
    try:
        data = json.loads(sys.stdin.read())
    except ValueError:
        data = None
    print(json.dumps(probe(data), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
