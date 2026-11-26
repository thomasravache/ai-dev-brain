#!/usr/bin/env python3
"""iam probe adapter of the boson-atlas (SPEC-0101, ADR-0025, ADR-0026), contract probe@2 (SPEC-0096).

Usage: python3 iam.py --describe     -> the capabilities (permissions: simulate, on queue and topic)
       python3 iam.py < input.json   -> reads the probe@2 input on stdin, prints the probe@2 output

Whether each workload of the deployment has, on a queue or a topic, the permissions the relations of the graph ask
for. Read only: the external processes are the machine's `kubectl` and AWS CLI, run with argv lists (never a shell)
built only from target (resource id and region, cloud.profile, context, namespace, workloads) and from a closed list
(SPEC-0101, section 6):
    kubectl get <deployments|statefulsets|daemonsets|rollouts> <name> -o json --context=<ctx> -n <ns>
        --request-timeout=20s                                  (one per workload, up to 5)
    kubectl get serviceaccounts <sa> -o json ...               (one per distinct ServiceAccount)
    aws sts get-caller-identity                                (topic only: the account and partition of its ARN)
    aws sqs get-queue-url --queue-name <name>                  (queue only)
    aws sqs get-queue-attributes --queue-url <url> --attribute-names Policy QueueArn
    aws sns get-topic-attributes --topic-arn <arn>
    aws iam simulate-principal-policy --policy-source-arn <role> --action-names <actions...> --resource-arns <arn>
        [--resource-policy <compact JSON>]                     (one per distinct role)
every aws call with --region, --profile, --output json, --no-cli-pager, --cli-read-timeout 20 and
--cli-connect-timeout 10, and an environment without inherited AWS_PROFILE or static keys (AWS_PAGER=""). Every
role is resolved in the cluster before any aws call; a workload without an IRSA role, or a resource policy that
cannot be read, fails the whole run (never a partial "allowed"). The role ARN, the account, the queue URL, the
resource ARNs and the policy only go as arguments; the output carries only the role name, and 12 digits are masked.
Errors leave with exit 0 and status "error" with a fixed message, never the stderr of the tools. Stdlib only,
Python 3.9+.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

CONTRACT = "probe@2"
ADAPTER = "iam"
CAPABILITY = "permissions"
VERB = "simulate"
DESCRIBE = {"contract": CONTRACT, "adapter": ADAPTER,
            "capabilities": {CAPABILITY: {"verbs": [VERB], "targets": ["queue", "topic"],
                                          "access": ["cluster", "cloud"]}}}
# the actions of each resource kind, in output order: (abstract action, API action, relations that require it)
ACTIONS = {
    "queue": (("send", "sqs:SendMessage", ("depends_on", "publishes")),
              ("receive", "sqs:ReceiveMessage", ("consumes",)),
              ("delete", "sqs:DeleteMessage", ("consumes",))),
    "topic": (("publish", "sns:Publish", ("publishes",)),),
}
DECISIONS = {"allowed": ("allowed", None), "explicitDeny": ("denied", "explicit"),
             "implicitDeny": ("denied", "implicit")}
WORKLOAD_RESOURCES = {"Deployment": "deployments", "StatefulSet": "statefulsets", "DaemonSet": "daemonsets",
                      "Rollout": "rollouts"}
KUBE_RESOURCES = (*WORKLOAD_RESOURCES.values(), "serviceaccounts")
# the closed list of the aws: (service, operation) -> the options of the operation itself
OPERATIONS = {
    ("sts", "get-caller-identity"): (),
    ("sqs", "get-queue-url"): ("--queue-name",),
    ("sqs", "get-queue-attributes"): ("--queue-url", "--attribute-names"),
    ("sns", "get-topic-attributes"): ("--topic-arn",),
    ("iam", "simulate-principal-policy"): ("--policy-source-arn", "--action-names", "--resource-arns",
                                          "--resource-policy"),
}
ROLE_ANNOTATION = "eks.amazonaws.com/role-arn"
REQUEST_TIMEOUT = "20s"
READ_TIMEOUT, CONNECT_TIMEOUT = "20", "10"
PROCESS_TIMEOUT = 30  # seconds for one kubectl or aws process
MAX_WORKLOADS = 5
DROPPED_ENV = ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
               "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN", "AWS_CREDENTIAL_EXPIRATION")
WORD_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}\Z")
QUEUE_RE = re.compile(r"^(?!-)(?:[A-Za-z0-9_-]{1,80}|[A-Za-z0-9_-]{1,75}\.fifo)\Z")
TOPIC_RE = re.compile(r"^(?!-)(?:[A-Za-z0-9_-]{1,256}|[A-Za-z0-9_-]{1,251}\.fifo)\Z")
REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}\Z")
PROFILE_RE = re.compile(r"^[A-Za-z0-9_.+][A-Za-z0-9_.+-]{0,63}\Z")
DNS_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\Z")
DNS_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?\Z")
ROLE_ARN_RE = re.compile(r"^arn:aws[-a-z]*:iam::[0-9]{12}:role/[\w+=,.@/-]{1,512}\Z", re.ASCII)
ACCOUNT_RE = re.compile(r"^[0-9]{12}\Z")
ACCOUNT_ANY_RE = re.compile(r"\b[0-9]{12}\b")
PARTITION_RE = re.compile(r"^arn:(aws[-a-z]*):")
REDACTED = "[REDACTED]"
# the contract messages (SPEC-0101, section 6)
NO_KUBECTL = "kubectl não encontrado"
NO_AWS = "aws não encontrado"
LOGIN = "renove o login da nuvem"
FORBIDDEN = "sem permissão no cluster (Forbidden)"
NO_CONTEXT = "contexto inexistente"
NO_WORKLOAD = "workload não encontrado"
NO_IRSA = "workload sem role IRSA (Pod Identity não verificado nesta versão)"
NO_POLICY = "não foi possível ler a política do recurso"
NO_RESOURCE = "recurso não encontrado na nuvem"
NO_SIMULATE = "sem permissão para simular (iam:SimulatePrincipalPolicy)"
TIMEOUT = "timeout"
INVALID_INPUT = "entrada inválida"
NO_REGION = "recurso sem região no atlas"
REFUSED = "chamada não permitida"
NO_VERB = "verbo não suportado"
KUBECTL_FAILED = "falha do kubectl"
AWS_FAILED = "falha da aws"
BAD_KUBECTL = "resposta inválida do kubectl"
BAD_CLOUD = "resposta inválida da nuvem"
# internal reasons of a failed aws call, renamed by operation (never printed)
DENIED, MISSING = "denied", "missing"
TIMEOUT_MARKERS = ("timeout", "timed out", "deadline exceeded")
AWS_RULES = (  # (reason, markers in the lowercased stderr), in order
    (LOGIN, ("token has expired", "sso session", "expiredtoken", "unable to locate credentials",
             "the config profile")),
    (TIMEOUT, TIMEOUT_MARKERS),
    (BAD_CLOUD, ("nosuchentity",)),
    (DENIED, ("accessdenied", "authorizationerror")),
    (MISSING, ("nonexistentqueue", "notfound")),
)
NO_CONTEXT_RE = re.compile(r'context "[^"\n]*" does not exist|context was not found|no context exists',
                           re.IGNORECASE)


class ProbeError(Exception):
    """An error with one of the fixed messages: becomes status "error" (exit 0)."""


# ---------------------------------------------------------------- input


def has_control(value):
    return isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value)


def check_input(data):
    """(kind, name, region, profile, context, namespace, workloads as (kind, name), truncated) of a probe@2 input, or
    ProbeError (INVALID_INPUT, NO_VERB, NO_REGION). Nothing here calls a tool."""
    if not isinstance(data, dict) or data.get("contract") != CONTRACT or data.get("capability") != CAPABILITY:
        raise ProbeError(INVALID_INPUT)
    if data.get("verb") != VERB:
        raise ProbeError(NO_VERB)
    target, limits = data.get("target"), data.get("limits")
    if not isinstance(target, dict) or not isinstance(limits, dict):
        raise ProbeError(INVALID_INPUT)
    cloud, resource = target.get("cloud"), target.get("resource")
    if not isinstance(cloud, dict) or not isinstance(resource, dict):
        raise ProbeError(INVALID_INPUT)
    profile = cloud.get("profile")
    if not isinstance(profile, str) or not PROFILE_RE.match(profile):
        raise ProbeError(INVALID_INPUT)
    kind, name, attrs = resource.get("kind"), resource.get("id"), resource.get("attrs")
    if kind not in ACTIONS or not isinstance(name, str) or not isinstance(attrs, dict):
        raise ProbeError(INVALID_INPUT)
    if any(has_control(v) for v in attrs.values()):
        raise ProbeError(INVALID_INPUT)
    if not (QUEUE_RE if kind == "queue" else TOPIC_RE).match(name):
        raise ProbeError(INVALID_INPUT)
    region = attrs.get("region")
    if region is None or region == "":
        raise ProbeError(NO_REGION)
    if not isinstance(region, str) or not REGION_RE.match(region):
        raise ProbeError(INVALID_INPUT)
    # only the name and the region are used: an ARN or URL in another attribute is ignored (ADR-0025 rule 4)
    context, namespace = target.get("context"), target.get("namespace")
    if not isinstance(context, str) or not context.strip() or context.startswith("-") or has_control(context):
        raise ProbeError(INVALID_INPUT)
    if not isinstance(namespace, str) or not DNS_LABEL_RE.match(namespace):
        raise ProbeError(INVALID_INPUT)
    raw = target.get("workloads")
    if not isinstance(raw, list) or not raw:
        raise ProbeError(INVALID_INPUT)
    workloads = []
    for value in raw:
        if not isinstance(value, str):
            raise ProbeError(INVALID_INPUT)
        wkind, sep, wname = value.partition("/")
        if not sep or wkind not in WORKLOAD_RESOURCES or not DNS_SUBDOMAIN_RE.match(wname):
            raise ProbeError(INVALID_INPUT)
        if (wkind, wname) not in workloads:
            workloads.append((wkind, wname))
    return (kind, name, region, profile, context, namespace, workloads[:MAX_WORKLOADS],
            len(workloads) > MAX_WORKLOADS)


# ---------------------------------------------------------------- kubectl


class Kubectl:
    """The only door to kubectl: `get <resource> <name> -o json` of the closed list, once per object."""

    def __init__(self, context, namespace):
        self.scope = [f"--context={context}", "-n", namespace, f"--request-timeout={REQUEST_TIMEOUT}"]
        self.executable = None
        self.cache = {}

    def get(self, resource, name):
        if resource not in KUBE_RESOURCES or not DNS_SUBDOMAIN_RE.match(name):
            raise ProbeError(REFUSED)
        key = (resource, name)
        if key in self.cache:
            return self.cache[key]
        if self.executable is None:
            self.executable = shutil.which("kubectl") or ""
        if not self.executable:
            raise ProbeError(NO_KUBECTL)
        try:
            proc = subprocess.run([self.executable, "get", resource, name, "-o", "json", *self.scope],
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=PROCESS_TIMEOUT, check=False)
        except subprocess.TimeoutExpired:
            raise ProbeError(TIMEOUT) from None
        except OSError:
            raise ProbeError(NO_KUBECTL) from None
        if proc.returncode != 0:
            raise ProbeError(classify_kubectl(proc.stderr or ""))
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            raise ProbeError(BAD_KUBECTL) from None
        if not isinstance(data, dict):
            raise ProbeError(BAD_KUBECTL)
        self.cache[key] = data
        return data


def classify_kubectl(stderr):
    """The fixed message for a failed kubectl: never its text (it may quote the context)."""
    lowered = stderr.lower()
    if "forbidden" in lowered:
        return FORBIDDEN
    if NO_CONTEXT_RE.search(stderr):
        return NO_CONTEXT
    if any(marker in lowered for marker in TIMEOUT_MARKERS):
        return TIMEOUT
    if "(notfound)" in lowered or "not found" in lowered:
        return NO_WORKLOAD
    return KUBECTL_FAILED


def _field(data, *path):
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def resolve_roles(kube, workloads):
    """[(workload, role ARN)] for every workload, read from the IRSA annotation of its ServiceAccount."""
    resolved = []
    for kind, name in workloads:
        obj = kube.get(WORKLOAD_RESOURCES[kind], name)
        pod_spec = _field(obj, "spec", "template", "spec")
        if pod_spec is not None and not isinstance(pod_spec, dict):
            raise ProbeError(BAD_KUBECTL)
        pod_spec = pod_spec or {}
        sa = pod_spec.get("serviceAccountName") or pod_spec.get("serviceAccount") or "default"
        if not isinstance(sa, str) or not DNS_SUBDOMAIN_RE.match(sa):
            raise ProbeError(BAD_KUBECTL)
        annotations = _field(kube.get("serviceaccounts", sa), "metadata", "annotations")
        if annotations is not None and not isinstance(annotations, dict):
            raise ProbeError(BAD_KUBECTL)
        arn = (annotations or {}).get(ROLE_ANNOTATION)
        if arn in (None, ""):
            raise ProbeError(NO_IRSA)
        if not isinstance(arn, str) or not ROLE_ARN_RE.match(arn):
            raise ProbeError(BAD_KUBECTL)
        resolved.append((f"{kind}/{name}", arn))
    return resolved


# ---------------------------------------------------------------- aws


class Aws:
    """The only door to the AWS CLI: an operation of the closed list, with the common options of section 6."""

    def __init__(self, region, profile):
        self.region, self.profile = region, profile
        self.executable = None
        self.env = {k: v for k, v in os.environ.items() if k not in DROPPED_ENV}
        self.env["AWS_PAGER"] = ""

    def call(self, service, operation, options=()):
        """The JSON object of `aws <service> <operation> <options...>`; ProbeError with a fixed message or an
        internal reason (DENIED, MISSING) the caller renames."""
        allowed = OPERATIONS.get((service, operation))
        if allowed is None:
            raise ProbeError(REFUSED)
        argv = [service, operation]
        for option, value in options:
            values = list(value) if isinstance(value, (list, tuple)) else [value]
            if option not in allowed or not values or any(
                    not isinstance(v, str) or not v or v.startswith("-") or has_control(v) for v in values):
                raise ProbeError(REFUSED)
            argv += [option, *values]
        argv += ["--region", self.region, "--profile", self.profile, "--output", "json", "--no-cli-pager",
                 "--cli-read-timeout", READ_TIMEOUT, "--cli-connect-timeout", CONNECT_TIMEOUT]
        if self.executable is None:
            self.executable = shutil.which("aws") or ""
        if not self.executable:
            raise ProbeError(NO_AWS)
        try:
            proc = subprocess.run([self.executable, *argv], stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=PROCESS_TIMEOUT,
                                  check=False, env=self.env)
        except subprocess.TimeoutExpired:
            raise ProbeError(TIMEOUT) from None
        except OSError:
            raise ProbeError(NO_AWS) from None
        if proc.returncode != 0:
            raise ProbeError(classify_aws(proc.stderr or ""))
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            raise ProbeError(BAD_CLOUD) from None
        if not isinstance(data, dict):
            raise ProbeError(BAD_CLOUD)
        return data


def classify_aws(stderr):
    """The reason of a failed aws: never its text (it may quote the profile, an ARN or the account)."""
    lowered = stderr.lower()
    for reason, markers in AWS_RULES:
        if any(marker in lowered for marker in markers):
            return reason
    return AWS_FAILED


def read_call(aws, service, operation, options, denied):
    """A read of the resource: MISSING -> NO_RESOURCE, DENIED -> the given message."""
    try:
        return aws.call(service, operation, options)
    except ProbeError as error:
        reason = str(error)
        if reason == MISSING:
            raise ProbeError(NO_RESOURCE) from None
        if reason == DENIED:
            raise ProbeError(denied) from None
        raise


def compact_policy(raw):
    """The resource policy as compact JSON, or None when the resource has none."""
    if raw in (None, ""):
        return None
    try:
        policy = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        policy = None
    if not isinstance(policy, dict):
        raise ProbeError(BAD_CLOUD)
    return json.dumps(policy, separators=(",", ":"), ensure_ascii=False)


def queue_target(aws, name):
    """(QueueArn, policy) of the queue, its URL and ARN checked against the name and the region."""
    data = read_call(aws, "sqs", "get-queue-url", [("--queue-name", name)], AWS_FAILED)
    url = data.get("QueueUrl")
    url_re = re.compile(rf"^https://sqs\.{re.escape(aws.region)}\.amazonaws\.com/(?P<account>[0-9]{{12}})/"
                        rf"{re.escape(name)}\Z")
    url_match = url_re.match(url) if isinstance(url, str) else None
    if not url_match:
        raise ProbeError(BAD_CLOUD)
    data = read_call(aws, "sqs", "get-queue-attributes",
                     [("--queue-url", url), ("--attribute-names", ("Policy", "QueueArn"))], NO_POLICY)
    attributes = data.get("Attributes")
    if not isinstance(attributes, dict):
        raise ProbeError(BAD_CLOUD)
    arn = attributes.get("QueueArn")
    arn_re = re.compile(rf"^arn:aws[-a-z]*:sqs:{re.escape(aws.region)}:(?P<account>[0-9]{{12}}):{re.escape(name)}\Z")
    arn_match = arn_re.match(arn) if isinstance(arn, str) else None
    if not arn_match or arn_match.group("account") != url_match.group("account"):
        raise ProbeError(BAD_CLOUD)
    return arn, compact_policy(attributes.get("Policy"))


def topic_target(aws, name):
    """(topic ARN, policy): the ARN built from the caller identity (account and partition of the profile)."""
    identity = read_call(aws, "sts", "get-caller-identity", [], AWS_FAILED)
    account, caller = identity.get("Account"), identity.get("Arn")
    partition = PARTITION_RE.match(caller) if isinstance(caller, str) else None
    if not (isinstance(account, str) and ACCOUNT_RE.match(account)) or not partition:
        raise ProbeError(BAD_CLOUD)
    arn = f"arn:{partition.group(1)}:sns:{aws.region}:{account}:{name}"
    data = read_call(aws, "sns", "get-topic-attributes", [("--topic-arn", arn)], NO_POLICY)
    attributes = data.get("Attributes")
    if not isinstance(attributes, dict) or attributes.get("TopicArn", arn) != arn:
        raise ProbeError(BAD_CLOUD)
    return arn, compact_policy(attributes.get("Policy"))


def simulate(aws, role_arn, actions, resource_arn, policy):
    """{API action: (decision, deny_type)} of one simulate-principal-policy call."""
    options = [("--policy-source-arn", role_arn), ("--action-names", [api for _, api, _ in actions]),
               ("--resource-arns", resource_arn)]
    if policy is not None:
        options.append(("--resource-policy", policy))
    try:
        data = aws.call("iam", "simulate-principal-policy", options)
    except ProbeError as error:
        if str(error) == DENIED:
            raise ProbeError(NO_SIMULATE) from None
        if str(error) == MISSING:
            raise ProbeError(BAD_CLOUD) from None
        raise
    results = data.get("EvaluationResults")
    if not isinstance(results, list) or data.get("IsTruncated") is True:
        raise ProbeError(BAD_CLOUD)
    decisions = {}
    for result in results:
        if not isinstance(result, dict):
            raise ProbeError(BAD_CLOUD)
        decision = DECISIONS.get(result.get("EvalDecision"))
        if decision is None:
            raise ProbeError(BAD_CLOUD)
        decisions[result.get("EvalActionName")] = decision
    if any(api not in decisions for _, api, _ in actions):
        raise ProbeError(BAD_CLOUD)
    return decisions


# ---------------------------------------------------------------- run


def run(kind, name, region, profile, context, namespace, workloads):
    principals = resolve_roles(Kubectl(context, namespace), workloads)  # all roles before any aws call
    aws = Aws(region, profile)
    resource_arn, policy = (queue_target if kind == "queue" else topic_target)(aws, name)
    actions = ACTIONS[kind]
    simulations = {}
    for _, role_arn in principals:
        if role_arn not in simulations:
            simulations[role_arn] = simulate(aws, role_arn, actions, resource_arn, policy)
    items = []
    for workload, role_arn in principals:
        role = role_arn.rsplit("/", 1)[-1]
        for action, api, required in actions:
            decision, deny_type = simulations[role_arn][api]
            items.append({"workload": workload, "role": role, "action": action, "api_action": api,
                          "decision": decision, "deny_type": deny_type, "required_by": list(required),
                          "resource_policy": policy is not None})
    return items


def mask(value):
    """Account ids (12 digits) out of every text of the output, besides the core's mask (ADR-0025 rule 5)."""
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
    if message:
        output["message"] = message
    return mask(output)


def probe(data):
    try:
        kind, name, region, profile, context, namespace, workloads, truncated = check_input(data)
        items = run(kind, name, region, profile, context, namespace, workloads)
    except ProbeError as error:
        message = str(error)
        return answer(data, "error", [], False, AWS_FAILED if message in (DENIED, MISSING) else message)
    except (AttributeError, TypeError, ValueError, KeyError):
        # a shape not foreseen: still a fixed message, never a traceback
        return answer(data, "error", [], False, BAD_CLOUD)
    return answer(data, "ok", items, truncated)


def main(argv):
    if argv == ["--describe"]:
        print(json.dumps(DESCRIBE))
        return 0
    if argv:
        print("uso: iam.py --describe | iam.py < entrada.json", file=sys.stderr)
        return 2
    try:
        data = json.loads(sys.stdin.read())
    except ValueError:
        data = None
    print(json.dumps(probe(data), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
