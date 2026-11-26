#!/usr/bin/env python3
"""argocd probe adapter of the boson-atlas (SPEC-0106, ADR-0023, ADR-0025), contract probe@2 (SPEC-0096).

Usage: python3 argocd.py [--app-namespace <ns>] --describe     -> the capabilities (gitops: application)
       python3 argocd.py [--app-namespace <ns>] < input.json   -> reads the probe@2 input, prints the probe@2 output

The Argo CD Application of a deployment (named as the deployment, the id the argocd collector writes, SPEC-0082),
read with `kubectl get`, never with the argocd CLI. Read only: the one external process is the machine's `kubectl`,
run with an argv list (never a shell) built only from target.deployment, the context and --app-namespace (an option
of the local command, default argocd, never from the atlas), from a closed list (SPEC-0106, section 6):
    kubectl get applications.argoproj.io <deployment> -n <app-namespace> -o json --context=<context>
        --request-timeout=20s   (one per run)
The context is target.context, or ATLAS_GITOPS_CONTEXT when declared in credentials and set (Argo CD in a management
cluster); the core masks its value like a credential. Nothing else is ever called: no -A, -l, --raw, --kubeconfig,
patch, annotate, apply or delete. Only the fields of section 6 are read: never spec.source(s), annotations or
status.resources. Images follow the rule of SPEC-0082 (path + :tag + @digest, without the registry host). Errors leave
with exit 0 and status "error" with a fixed message; the context and the kubectl stderr are never printed. Stdlib
only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

CONTRACT = "probe@2"
ADAPTER = "argocd"
CAPABILITY = "gitops"
VERB = "application"
DESCRIBE = {"contract": CONTRACT, "adapter": ADAPTER,
            "capabilities": {CAPABILITY: {"verbs": [VERB], "targets": ["deployment"], "access": ["cluster"]}}}
APP_TYPE = "applications.argoproj.io"
DEFAULT_APP_NAMESPACE = "argocd"
CONTEXT_ENV = "ATLAS_GITOPS_CONTEXT"
REQUEST_TIMEOUT = "20s"
PROCESS_TIMEOUT = 30  # seconds for the kubectl process (request timeout plus a margin)
TEXT_MAX = 300
DNS_SUBDOMAIN_MAX = 253
WORD_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}\Z")
DNS_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\Z")
DNS_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\Z")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
IMAGE_PATH_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*$")
IMAGE_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
IMAGE_DIGEST_RE = re.compile(r"^sha(?:256|384|512):[A-Fa-f0-9]+$")
# the contract messages (SPEC-0106, section 6)
NO_KUBECTL = "kubectl não encontrado"
FORBIDDEN = "sem permissão (Forbidden)"
NO_CONTEXT = "contexto inexistente"
TIMEOUT = "timeout"
NO_ARGOCD = "Argo CD ausente no cluster"
KUBECTL_FAILED = "falha do kubectl"
INVALID_ANSWER = "resposta inválida do kubectl"
REFUSED = "chamada não permitida"
INVALID_INPUT = "entrada inválida"
NOT_FOUND = "não encontrada"  # internal: the Application does not exist (never printed)
TIMEOUT_RE = re.compile(r"deadline exceeded|timeout|timed out|i/o timeout", re.IGNORECASE)
NO_CONTEXT_RE = re.compile(r'context "[^"\n]*" does not exist|context was not found|no context exists',
                           re.IGNORECASE)
NO_RESOURCE_TYPE_RE = re.compile(r"doesn't have a resource type", re.IGNORECASE)
NOT_FOUND_RE = re.compile(r"\(NotFound\)")


class ProbeError(Exception):
    """An error with one of the fixed messages: becomes status "error" (exit 0)."""


# ---------------------------------------------------------------- input


def has_control(value) -> bool:
    return isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value)


def context_ok(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not value.startswith("-") and not has_control(value)


def check_input(data, environ):
    """(application, context) of a probe@2 input, or ProbeError (INVALID_INPUT, REFUSED). Nothing here calls
    kubectl."""
    if not isinstance(data, dict) or data.get("contract") != CONTRACT or data.get("capability") != CAPABILITY:
        raise ProbeError(INVALID_INPUT)
    if data.get("verb") != VERB:
        raise ProbeError(REFUSED)
    target = data.get("target")
    if not isinstance(target, dict) or not isinstance(data.get("limits"), dict):
        raise ProbeError(INVALID_INPUT)
    name = target.get("deployment")
    if not isinstance(name, str) or len(name) > DNS_SUBDOMAIN_MAX or not DNS_SUBDOMAIN_RE.match(name):
        raise ProbeError(INVALID_INPUT)
    context = target.get("context")
    if not context_ok(context):
        raise ProbeError(INVALID_INPUT)
    override = environ.get(CONTEXT_ENV)
    if override:
        if not context_ok(override):
            raise ProbeError(INVALID_INPUT)
        context = override
    return name, context


def parse_options(argv):
    """(app namespace, describe) of the command line, or None when it is out of the usage."""
    namespace, describe, i = DEFAULT_APP_NAMESPACE, False, 0
    while i < len(argv):
        if argv[i] == "--app-namespace" and i + 1 < len(argv):
            namespace = argv[i + 1]
            i += 2
        elif argv[i] == "--describe" and i == len(argv) - 1:
            describe = True
            i += 1
        else:
            return None
    return namespace, describe


# ---------------------------------------------------------------- kubectl


def classify(stderr: str) -> str:
    """The fixed message (or NOT_FOUND) of a failed kubectl: never its text (it may quote the context)."""
    if "Forbidden" in stderr or "forbidden" in stderr:
        return FORBIDDEN
    if NO_CONTEXT_RE.search(stderr):
        return NO_CONTEXT
    if NO_RESOURCE_TYPE_RE.search(stderr):
        return NO_ARGOCD
    if NOT_FOUND_RE.search(stderr):
        return NOT_FOUND
    if TIMEOUT_RE.search(stderr):
        return TIMEOUT
    return KUBECTL_FAILED


def get_application(name, namespace, context):
    """The Application as kubectl prints it, or None when it does not exist (NotFound)."""
    if not DNS_SUBDOMAIN_RE.match(name) or not DNS_LABEL_RE.match(namespace) or not context_ok(context):
        raise ProbeError(REFUSED)
    argv = ["get", APP_TYPE, name, "-n", namespace, "-o", "json", f"--context={context}",
            f"--request-timeout={REQUEST_TIMEOUT}"]
    executable = shutil.which("kubectl")
    if not executable:
        raise ProbeError(NO_KUBECTL)
    try:
        proc = subprocess.run([executable, *argv], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=PROCESS_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise ProbeError(TIMEOUT) from None
    except OSError:
        raise ProbeError(NO_KUBECTL) from None
    if proc.returncode != 0:
        reason = classify(proc.stderr or "")
        if reason == NOT_FOUND:
            return None
        raise ProbeError(reason)
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise ProbeError(INVALID_ANSWER) from None
    if not isinstance(data, dict):
        raise ProbeError(INVALID_ANSWER)
    return data


# ---------------------------------------------------------------- helpers


def obj(value) -> dict:
    """An object of the Application: a dict, {} when absent, INVALID_ANSWER when it is anything else."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProbeError(INVALID_ANSWER)
    return value


def text(value) -> str:
    return value.strip()[:TEXT_MAX] if isinstance(value, str) else ""


def normalize_image(value):
    """An image reference -> "<path>[:<tag>][@<digest>]" without the registry host (path rule of SPEC-0082), or
    None when it does not fit (a credential, a space, an odd digest)."""
    if not isinstance(value, str):
        return None
    image = value.strip()
    if not image or any(c.isspace() for c in image):
        return None
    match = SCHEME_RE.match(image)
    image = image[match.end():] if match else image
    digest = ""
    if "@" in image:
        image, _, digest = image.partition("@")
        if not IMAGE_DIGEST_RE.match(digest):
            return None
    head, sep, last = image.rpartition("/")
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


def application_item(name, app):
    """The item of section 6: only metadata.name (checked), status.sync, status.health, status.operationState,
    status.reconciledAt and status.summary.images."""
    obj(app.get("metadata"))
    obj(app.get("spec"))
    status = obj(app.get("status"))
    sync, health = obj(status.get("sync")), obj(status.get("health"))
    operation, summary = obj(status.get("operationState")), obj(status.get("summary"))
    revision = text(sync.get("revision"))
    revisions = sync.get("revisions")
    if not revision and isinstance(revisions, list) and revisions:
        revision = text(revisions[0])
    raw = summary.get("images")
    if raw is not None and not isinstance(raw, list):
        raise ProbeError(INVALID_ANSWER)
    images = []
    for value in raw or []:
        image = normalize_image(value)
        if image and image not in images:
            images.append(image)
    return {"application": name, "found": True, "sync_status": text(sync.get("status")),
            "health_status": text(health.get("status")), "revision": revision,
            "operation_phase": text(operation.get("phase")), "operation_finished_at": text(operation.get("finishedAt")),
            "reconciled_at": text(status.get("reconciledAt")), "images": images}


# ---------------------------------------------------------------- main


def answer(data, status, items, message=None):
    verb = data.get("verb") if isinstance(data, dict) else None
    output = {"contract": CONTRACT, "adapter": ADAPTER, "capability": CAPABILITY,
              "verb": verb if isinstance(verb, str) and WORD_RE.match(verb) else VERB, "status": status,
              "items": items, "truncated": False}
    if message:
        output["message"] = message
    return output


def probe(data, namespace, environ):
    try:
        if not DNS_LABEL_RE.match(namespace):
            raise ProbeError(INVALID_INPUT)
        name, context = check_input(data, environ)
        app = get_application(name, namespace, context)
        item = {"application": name, "found": False} if app is None else application_item(name, app)
    except ProbeError as error:
        return answer(data, "error", [], str(error))
    except (AttributeError, TypeError, ValueError, KeyError):
        # a shape the checks did not foresee: still a fixed message, never a traceback
        return answer(data, "error", [], INVALID_ANSWER)
    return answer(data, "ok", [item])


def main(argv):
    options = parse_options(argv)
    if options is None:
        print("uso: argocd.py [--app-namespace <ns>] --describe | argocd.py [--app-namespace <ns>] < entrada.json",
              file=sys.stderr)
        return 2
    namespace, describe = options
    if describe:
        print(json.dumps(DESCRIBE))
        return 0
    try:
        data = json.loads(sys.stdin.read())
    except ValueError:
        data = None
    print(json.dumps(probe(data, namespace, os.environ), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
