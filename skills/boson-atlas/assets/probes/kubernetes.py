#!/usr/bin/env python3
"""kubernetes probe adapter of the boson-atlas (SPEC-0089, ADR-0023), contract probe@1 (SPEC-0088).

Usage: python3 kubernetes.py --describe     -> the capabilities (runtime: status, events, logs)
       python3 kubernetes.py < input.json   -> reads the probe@1 input on stdin, prints the probe@1 output

Read only: the one external process is the machine's `kubectl`, run with an argv list (never a shell) built only
from the fields of `target` and `limits` and from a closed list (Emenda v3):
    kubectl get <resource> -o json --context=<target.context> -n <target.namespace> --request-timeout=20s
        resource in deployments, statefulsets, daemonsets, rollouts, replicasets, pods, events
        (at most one get per resource in a run)
    kubectl logs pod/<name> --all-containers --timestamps --prefix --since=<s>s --tail=<lines> --context=... -n ...
        --request-timeout=20s   (one per pod of the workload, up to 10 pods by name)
Nothing else is ever called: no Secret, no ConfigMap, no exec, describe or port-forward. A verb, a workload kind or a
name outside the rules is refused ("chamada não permitida") before any call. Errors leave with exit 0 and
status "error" with a fixed message; the context and the kubectl stderr are never printed. The core (atlas.py
probe) applies the redaction and the limits again (SPEC-0088). Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

CONTRACT = "probe@1"
ADAPTER = "kubernetes"
CAPABILITY = "runtime"
VERBS = ("status", "events", "logs")
DESCRIBE = {"contract": CONTRACT, "adapter": ADAPTER, "capabilities": {CAPABILITY: list(VERBS)}}
# the workload kinds and the resource each one is read from
WORKLOAD_RESOURCES = {"Deployment": "deployments", "StatefulSet": "statefulsets", "DaemonSet": "daemonsets",
                      "Rollout": "rollouts"}
RESOURCES = ("deployments", "statefulsets", "daemonsets", "rollouts", "replicasets", "pods", "events")
REQUEST_TIMEOUT = "20s"  # fixed: below the core's default timeout (60 s); the input does not carry it
PROCESS_TIMEOUT = 30  # seconds for one kubectl process (request timeout plus a margin)
MAX_LOG_PODS = 10
MAX_LINES = 2000
MESSAGE_MAX = 300
OUTPUT_BUDGET = 900 * 1024  # bytes of items: the core reads at most 1 MB of the adapter's stdout
WORD_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}\Z")
DNS_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\Z")
DNS_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?\Z")
LOG_LINE_RE = re.compile(r"^\[pod/(?P<pod>[^/\]]+)/(?P<container>[^\]]+)\] (?P<ts>\d{4}-\d{2}-\d{2}T\S+) ?(?P<line>.*)$")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
IMAGE_PATH_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*$")
IMAGE_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
IMAGE_DIGEST_RE = re.compile(r"^sha(?:256|384|512):[A-Fa-f0-9]+$")
# the contract messages (SPEC-0089, section 6)
NOT_FOUND = "kubectl não encontrado"
FORBIDDEN = "sem permissão (Forbidden)"
NO_CONTEXT = "contexto inexistente"
REFUSED = "chamada não permitida"
TIMEOUT = "timeout"
INVALID_INPUT = "entrada inválida"
INVALID_ANSWER = "resposta inválida do kubectl"
KUBECTL_FAILED = "falha do kubectl"
NO_TYPE = "sem o tipo de recurso"  # internal: the cluster has no such resource type (never printed)
TIMEOUT_RE = re.compile(r"deadline exceeded|timeout|timed out|i/o timeout", re.IGNORECASE)
NO_CONTEXT_RE = re.compile(r'context "[^"\n]*" does not exist|context was not found|no context exists',
                           re.IGNORECASE)
NO_RESOURCE_TYPE_RE = re.compile(r"doesn't have a resource type", re.IGNORECASE)


class ProbeError(Exception):
    """An error with one of the fixed messages: becomes status "error" (exit 0)."""


# ---------------------------------------------------------------- input


def check_input(data):
    """(verb, context, namespace, workloads as (kind, name), lines, since) of a probe@1 input, or ProbeError:
    REFUSED for a verb, kind or name outside the rules, INVALID_INPUT for a malformed input."""
    if not isinstance(data, dict) or data.get("contract") != CONTRACT:
        raise ProbeError(INVALID_INPUT)
    if data.get("capability") != CAPABILITY or data.get("verb") not in VERBS:
        raise ProbeError(REFUSED)
    target, limits = data.get("target"), data.get("limits")
    if not isinstance(target, dict) or not isinstance(limits, dict):
        raise ProbeError(INVALID_INPUT)
    context, namespace = target.get("context"), target.get("namespace")
    if not isinstance(context, str) or not context.strip() or context.startswith("-") or "\n" in context:
        raise ProbeError(REFUSED)
    if not isinstance(namespace, str) or not DNS_LABEL_RE.match(namespace):
        raise ProbeError(REFUSED)
    raw = target.get("workloads")
    if not isinstance(raw, list) or not raw:
        raise ProbeError(REFUSED)
    workloads = []
    for value in raw:
        if not isinstance(value, str):
            raise ProbeError(REFUSED)
        kind, sep, name = value.partition("/")
        if not sep or kind not in WORKLOAD_RESOURCES or not DNS_SUBDOMAIN_RE.match(name):
            raise ProbeError(REFUSED)
        if (kind, name) not in workloads:
            workloads.append((kind, name))
    lines, since = limits.get("lines"), limits.get("since_seconds")
    for number in (lines, since):
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ProbeError(INVALID_INPUT)
    return data["verb"], context, namespace, workloads, min(lines, MAX_LINES), since


# ---------------------------------------------------------------- kubectl


class Kubectl:
    """The only door to kubectl: `get <resource>` (once per resource) and `logs pod/<name>` (once per pod)."""

    def __init__(self, context, namespace):
        self.executable = shutil.which("kubectl")
        self.scope = [f"--context={context}", "-n", namespace, f"--request-timeout={REQUEST_TIMEOUT}"]
        self.cache = {}
        self.logged = set()

    def run(self, argv):
        if argv[0] not in ("get", "logs"):
            raise ProbeError(REFUSED)
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
            reason = classify(proc.stderr or "")
            raise ProbeError(KUBECTL_FAILED if reason == NO_TYPE and argv[0] != "get" else reason)
        return proc.stdout

    def get(self, resource):
        """The items of `kubectl get <resource> -o json`; a resource type the cluster does not have (the Rollout
        CRD absent) is an empty list."""
        if resource not in RESOURCES:
            raise ProbeError(REFUSED)
        if resource not in self.cache:
            try:
                text = self.run(["get", resource, "-o", "json", *self.scope])
            except ProbeError as error:
                if str(error) != NO_TYPE:
                    raise
                self.cache[resource] = []
                return self.cache[resource]
            try:
                data = json.loads(text)
            except ValueError:
                raise ProbeError(INVALID_ANSWER) from None
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                raise ProbeError(INVALID_ANSWER)
            self.cache[resource] = [item for item in items if isinstance(item, dict)]
        return self.cache[resource]

    def logs(self, pod, since, tail):
        if pod in self.logged or not DNS_SUBDOMAIN_RE.match(pod):
            raise ProbeError(REFUSED)
        self.logged.add(pod)
        return self.run(["logs", f"pod/{pod}", "--all-containers", "--timestamps", "--prefix", f"--since={since}s",
                         f"--tail={tail}", *self.scope])


def classify(stderr):
    """The fixed message for a failed kubectl: never its text (it may quote the context)."""
    if "Forbidden" in stderr or "forbidden" in stderr:
        return FORBIDDEN
    if NO_CONTEXT_RE.search(stderr):
        return NO_CONTEXT
    if TIMEOUT_RE.search(stderr):
        return TIMEOUT
    if NO_RESOURCE_TYPE_RE.search(stderr):
        return NO_TYPE
    return KUBECTL_FAILED


# ---------------------------------------------------------------- helpers


def meta(item, key):
    value = (item.get("metadata") or {}).get(key)
    return value if isinstance(value, (str, int, dict, list)) else None


def number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def selects(selector, labels):
    """Whether a label selector (matchLabels and matchExpressions) matches the labels; an empty one matches none."""
    if not isinstance(selector, dict):
        return False
    labels = labels if isinstance(labels, dict) else {}
    match_labels = selector.get("matchLabels") or {}
    expressions = selector.get("matchExpressions") or []
    if not match_labels and not expressions:
        return False
    if any(labels.get(key) != value for key, value in match_labels.items()):
        return False
    for expression in expressions:
        if not isinstance(expression, dict):
            return False
        key, operator = expression.get("key"), expression.get("operator")
        values = expression.get("values") or []
        if operator == "In" and labels.get(key) not in values:
            return False
        if operator == "NotIn" and key in labels and labels[key] in values:
            return False
        if operator == "Exists" and key not in labels:
            return False
        if operator == "DoesNotExist" and key in labels:
            return False
    return True


def find_workloads(kube, workloads):
    """{(kind, name): object or None} for each workload of the target."""
    found = {}
    for kind, name in workloads:
        objects = kube.get(WORKLOAD_RESOURCES[kind])
        found[(kind, name)] = next((o for o in objects if meta(o, "name") == name), None)
    return found


def pods_of(kube, workload):
    """The pods selected by the workload (spec.selector), sorted by name."""
    if workload is None:
        return []
    selector = (workload.get("spec") or {}).get("selector")
    pods = [p for p in kube.get("pods") if isinstance(meta(p, "name"), str) and selects(selector, meta(p, "labels"))]
    return sorted(pods, key=lambda p: meta(p, "name"))


def normalize_image(value):
    """An image reference -> "<path>[:<tag>][@<digest>]" without the registry host (path rule of SPEC-0082), or
    None when it does not fit (a credential, a space, an odd digest)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or any(c.isspace() for c in text):
        return None
    match = SCHEME_RE.match(text)
    text = text[match.end():] if match else text
    digest = ""
    if "@" in text:
        text, _, digest = text.partition("@")
        if not IMAGE_DIGEST_RE.match(digest):
            return None
    head, sep, last = text.rpartition("/")
    last, colon, tag = last.partition(":")
    if colon and not IMAGE_TAG_RE.match(tag):
        return None
    segments = (head.split("/") if sep else []) + [last]
    first = segments[0].lower()
    if len(segments) > 1 and ("." in first or ":" in first or first == "localhost"):
        segments = segments[1:]
    path = "/".join(segments).lower()
    if not path or not IMAGE_PATH_RE.match(path):
        return None
    return path + (f":{tag}" if colon else "") + (f"@{digest.lower()}" if digest else "")


def parse_ts(value):
    """An RFC 3339 time ("2026-11-23T10:00:00Z", with or without fraction or offset) -> aware datetime, or None."""
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$", value.strip())
    if not match:
        return None
    try:
        moment = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    zone = match.group(2) or "Z"
    if zone == "Z":
        return moment.replace(tzinfo=timezone.utc)
    sign = 1 if zone[0] == "+" else -1
    offset = timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))
    return moment.replace(tzinfo=timezone(sign * offset))


def keep_recent(items, lines):
    """The last `lines` items that fit the output budget, and whether any was dropped."""
    truncated = len(items) > lines
    items = items[-lines:] if lines else []
    size, kept = 0, []
    for item in reversed(items):
        size += len(json.dumps(item, ensure_ascii=False).encode("utf-8")) + 2
        if size > OUTPUT_BUDGET:
            truncated = True
            break
        kept.append(item)
    return list(reversed(kept)), truncated


# ---------------------------------------------------------------- verbs


def workload_item(label, kind, workload):
    if workload is None:
        return {"kind": "workload", "workload": label, "found": False, "rollout_complete": False}
    spec, status = workload.get("spec") or {}, workload.get("status") or {}
    if kind == "DaemonSet":
        desired = number(status.get("desiredNumberScheduled"))
        updated = number(status.get("updatedNumberScheduled"))
        ready = number(status.get("numberReady"))
        available = number(status.get("numberAvailable"))
    else:
        replicas = spec.get("replicas")
        desired = replicas if isinstance(replicas, int) and not isinstance(replicas, bool) else 1
        updated = number(status.get("updatedReplicas"))
        ready = number(status.get("readyReplicas"))
        available = number(status.get("availableReplicas"))
    observed = number(status.get("observedGeneration"))
    generation = number(meta(workload, "generation"))
    complete = updated == desired == ready == available and observed >= generation
    return {"kind": "workload", "workload": label, "found": True, "desired": desired, "updated": updated,
            "ready": ready, "available": available, "rollout_complete": complete}


def pod_item(label, pod):
    spec, status = pod.get("spec") or {}, pod.get("status") or {}
    statuses = [s for s in status.get("containerStatuses") or [] if isinstance(s, dict)]
    images = []
    for container in spec.get("containers") or []:
        image = normalize_image(container.get("image") if isinstance(container, dict) else None)
        if image and image not in images:
            images.append(image)
    conditions = [c for c in status.get("conditions") or [] if isinstance(c, dict)]
    ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)
    last = ""
    for container in statuses:
        reason = ((container.get("lastState") or {}).get("terminated") or {}).get("reason")
        if isinstance(reason, str) and reason:
            last = reason
            break
    phase = status.get("phase")
    return {"kind": "pod", "workload": label, "pod": meta(pod, "name"), "phase": phase if isinstance(phase, str)
            else "", "ready": ready, "restarts": sum(number(s.get("restartCount")) for s in statuses),
            "images": images, "last_termination": last[:MESSAGE_MAX]}


def run_status(kube, workloads, lines, since):
    found = find_workloads(kube, workloads)
    items = []
    for kind, name in workloads:
        label, workload = f"{kind}/{name}", found[(kind, name)]
        items.append(workload_item(label, kind, workload))
        items += [pod_item(label, pod) for pod in pods_of(kube, workload)]
    truncated = len(items) > lines
    return items[:lines], truncated


def run_events(kube, workloads, lines, since):
    found = find_workloads(kube, workloads)
    objects = set()
    for (kind, name), workload in found.items():
        objects.add((kind, name))
        objects.update(("Pod", meta(pod, "name")) for pod in pods_of(kube, workload))
        if kind == "Deployment" and workload is not None:
            for replicaset in kube.get("replicasets"):
                owners = meta(replicaset, "ownerReferences") or []
                if any(isinstance(o, dict) and o.get("kind") == "Deployment" and o.get("name") == name
                       for o in owners):
                    objects.add(("ReplicaSet", meta(replicaset, "name")))
    limit = datetime.now(timezone.utc) - timedelta(seconds=since)
    selected = []
    for event in kube.get("events"):
        if event.get("type") != "Warning":
            continue
        involved = event.get("involvedObject") or event.get("regarding") or {}
        key = (involved.get("kind"), involved.get("name")) if isinstance(involved, dict) else (None, None)
        if key not in objects:
            continue
        series = event.get("series") if isinstance(event.get("series"), dict) else {}
        last_ts = next((v for v in (event.get("lastTimestamp"), series.get("lastObservedTime"),
                                    event.get("eventTime"), meta(event, "creationTimestamp")) if parse_ts(v)), None)
        if last_ts is None or parse_ts(last_ts) < limit:
            continue
        count = number(event.get("count")) or number(series.get("count")) or 1
        reason, message = event.get("reason"), event.get("message")
        selected.append((parse_ts(last_ts), {
            "reason": reason if isinstance(reason, str) else "", "object": f"{key[0]}/{key[1]}", "count": count,
            "last_ts": last_ts, "message": message.strip()[:MESSAGE_MAX] if isinstance(message, str) else ""}))
    selected.sort(key=lambda pair: pair[0])
    return keep_recent([item for _, item in selected], lines)


def run_logs(kube, workloads, lines, since):
    found = find_workloads(kube, workloads)
    rows, truncated, seen = [], False, set()
    for kind, name in workloads:
        pods = [meta(pod, "name") for pod in pods_of(kube, found[(kind, name)])]
        pods = [pod for pod in pods if pod not in seen]
        if len(pods) > MAX_LOG_PODS:
            truncated = True
        for pod in pods[:MAX_LOG_PODS]:
            seen.add(pod)
            streams = {}
            for raw in kube.logs(pod, since, lines).splitlines():
                match = LOG_LINE_RE.match(raw)
                if not match or match.group("pod") != pod:
                    continue
                stamp = parse_ts(match.group("ts"))
                if stamp is None:
                    continue
                container = match.group("container")
                streams[container] = streams.get(container, 0) + 1
                rows.append((stamp, match.group("ts"), {"workload": f"{kind}/{name}", "pod": pod,
                                                        "container": container, "ts": match.group("ts"),
                                                        "line": match.group("line")}))
            if any(count >= lines for count in streams.values()):
                truncated = True  # --tail may have cut this container
    rows.sort(key=lambda row: (row[0], row[1]))
    items, cut = keep_recent([item for _, _, item in rows], lines)
    return items, truncated or cut


VERB_RUNNERS = {"status": run_status, "events": run_events, "logs": run_logs}


# ---------------------------------------------------------------- main


def answer(data, status, items, truncated, message=None):
    verb = data.get("verb") if isinstance(data, dict) else None
    output = {"contract": CONTRACT, "adapter": ADAPTER, "capability": CAPABILITY,
              "verb": verb if isinstance(verb, str) and WORD_RE.match(verb) else "status", "status": status,
              "items": items, "truncated": truncated}
    if isinstance(data, dict) and isinstance(data.get("capability"), str) and WORD_RE.match(data["capability"]):
        output["capability"] = data["capability"]
    if message:
        output["message"] = message
    return output


def probe(data):
    try:
        verb, context, namespace, workloads, lines, since = check_input(data)
        kube = Kubectl(context, namespace)
        items, truncated = VERB_RUNNERS[verb](kube, workloads, lines, since)
    except ProbeError as error:
        return answer(data, "error", [], False, str(error))
    return answer(data, "ok", items, truncated)


def main(argv):
    if argv == ["--describe"]:
        print(json.dumps(DESCRIBE))
        return 0
    if argv:
        print("uso: kubernetes.py --describe | kubernetes.py < entrada.json", file=sys.stderr)
        return 2
    try:
        data = json.loads(sys.stdin.read())
    except ValueError:
        data = None
    print(json.dumps(probe(data), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
