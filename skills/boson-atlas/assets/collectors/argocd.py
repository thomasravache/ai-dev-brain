#!/usr/bin/env python3
"""argocd collector of the boson-atlas (SPEC-0035), category delivery: deployments, services, environments, clusters,
the source repository of each deployment and its configuration references, read from the Argo CD Applications.
Stdlib only, Python 3.9+; prints the boson-atlas/collector@1 output (ADR-0011).

Usage: python3 argocd.py --from argocd|kubectl [--env-label KEY] [--service-label KEY]
                         [--service-pattern REGEX] [--ref-suffixes HOST,URL,...] [--input FILE]

Only the Application list is read (`argocd app list -o json` or `kubectl get applications.argoproj.io -A -o json`):
never Secrets, rendered manifests or cluster state. From the Helm parameters, Helm values and plugin env only the
key names ending in a configured suffix leave the collector, each with the bare host or resource name of its value:
user, password, port, path and query are stripped here, before the scan's redaction (two layers, spec §4); an AWS
SQS queue URL or SQS/SNS ARN gives only the queue or topic name, never the account or the region (SPEC-0076).
The service of an Application is its service label, else the root nameOverride of its Helm values, else the group
"service" of --service-pattern over its name, else its name (SPEC-0082). The images of a deployment (status.summary
.images and the Helm image.repository) leave only as their path: never the registry host (it may hold an account id),
the tag, the digest or a credential; an image that does not fit the name rule is dropped whole (SPEC-0082).
The chosen CLI is the only external process, run by run_cli: argv as a list, never a shell, with a timeout.
--input FILE reads a recorded list instead of calling a CLI (references/collectors/argocd.md).
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
from pathlib import Path

CONTRACT = "boson-atlas/collector@1"
COLLECTOR = "argocd"
CATEGORY = "delivery"
DEFAULT_ENV_LABEL = "env"
DEFAULT_SERVICE_LABEL = "app.kubernetes.io/part-of"
# HOST and URL also cover _HOST and _URL; without "_" they match .NET keys (RouterEndpoint, ServiceUrl) (SPEC-0076)
DEFAULT_REF_SUFFIXES = ("HOST", "URL", "URI", "ENDPOINT", "DSN", "ADDR", "_QUEUE", "_TOPIC", "_BUCKET")
CLI_TIMEOUT = 120  # seconds for the one CLI call
GUIDE = "references/collectors/argocd.md"
NO_ACCESS = "sem acesso às Applications"
INVALID = "resposta inválida da CLI"
# the one read-only command per CLI
COMMANDS = {
    "argocd": ("app", "list", "-o", "json"),
    "kubectl": ("get", "applications.argoproj.io", "-A", "-o", "json"),
}
# stderr of a CLI that failed for lack of a login, a configured server or permission (argocd gRPC codes and
# "server address unspecified", kubectl API errors)
ACCESS_DENIED = re.compile(r"Unauthenticated|PermissionDenied|permission denied|Unauthorized|Forbidden|"
                           r"must be logged in|token is expired|invalid session|not logged in|"
                           r"server address unspecified", re.IGNORECASE)
# a host name, IPv4 or bracketed IPv6, or a resource name (queue, topic, bucket): nothing else leaves host_of
HOST_RE = re.compile(r"^(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)$")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
# the SQS endpoints: regional (sqs.<region>.amazonaws.com), FIPS (sqs-fips.<region>.amazonaws.com), legacy
# (<region>.queue.amazonaws.com) and VPC endpoint ([<vpce-id>.]sqs.<region>.vpce.amazonaws.com) (SPEC-0076)
SQS_HOST_RE = re.compile(r"^(?:sqs(?:-fips)?\.[a-z0-9-]+|(?:[a-z0-9-]+\.)?queue|(?:[a-z0-9.-]+\.)?sqs\.[a-z0-9-]+\.vpce)"
                         r"\.amazonaws\.com(?:\.cn)?$", re.IGNORECASE)
# any AWS VPC endpoint host: never leaves whole (Emenda v4)
VPCE_HOST_RE = re.compile(r"\.vpce\.amazonaws\.com(?:\.cn)?$", re.IGNORECASE)
# YAML null and boolean literals, YAML 1.1 booleans included (accepted by Helm): never a host or a service name
# (SPEC-0076, Emendas v3 and v4)
YAML_LITERALS = frozenset(("null", "~", "true", "false", "yes", "no", "on", "off", "y", "n"))
# the path of an SQS queue URL: /<account>/<queue>
SQS_PATH_RE = re.compile(r"^/\d{12}/([^/?#]+)$")
# arn:<partition>:sqs|sns:<region>:<account>:<name>
AWS_ARN_RE = re.compile(r"^arn:[a-z0-9-]+:(?:sqs|sns):[a-z0-9-]+:\d{12}:(.+)$")
# a root "nameOverride: value" line of a Helm values text (no indentation, not a list item)
NAME_OVERRIDE_LINE_RE = re.compile(r"^nameOverride\s*:(?:\s+(.*))?$")
# "KEY: value" in a Helm values text, optionally as a list item ("- KEY: value")
YAML_LINE_RE = re.compile(r"^\s*(?:-\s+)?([A-Za-z0-9_.-]+)\s*:(?:\s+(.*))?$")
# the normalized path of an image: lower case segments separated by "/" (SPEC-0082)
IMAGE_PATH_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*$")
# the digest after "@" of an image reference (sha256:<hex>)
IMAGE_DIGEST_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+.-]*:[A-Fa-f0-9]+$")
IMAGE_REPOSITORY_KEY = "image.repository"
# GitHub repoURL: https/http/ssh/git:// (credentials allowed) or scp-like git@github.com:owner/repo
GITHUB_RE = re.compile(
    r"^(?:(?:https?|ssh|git)://(?:[^/]*@)?(?:www\.)?github\.com(?::\d+)?/|[^@/\s]+@github\.com:)"
    r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", re.IGNORECASE)


class CollectorError(Exception):
    """A failure that ends the collector with exit 1; the message is shown as is."""


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def entity(kind: str, eid: str, name: str, attrs: dict) -> dict:
    return {"kind": kind, "id": eid, "name": name, "attrs": attrs, "source": COLLECTOR}


def relation(source_ref: str, target_ref: str, rtype: str) -> dict:
    return {"from": source_ref, "to": target_ref, "type": rtype, "source": COLLECTOR}


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _text(value):
    """A non-empty string, else None."""
    return value if isinstance(value, str) and value else None


# --------------------------------------------------------------------------- configuration references


def _strip_port(hostport: str):
    """host[:port] -> host; None when what follows ":" is not a port (it may be user:password)."""
    if hostport.startswith("["):  # [IPv6]:port
        end = hostport.find("]")
        if end < 0:
            return None
        rest = hostport[end + 1:]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return None
        return hostport[:end + 1]
    host, sep, port = hostport.partition(":")
    if sep and not port.isdigit():
        return None
    return host


def _resource_name(name):
    """A queue or topic name when it is a strict resource name (HOST_RE), else None."""
    return name if name and HOST_RE.match(name) else None


def host_of(value):
    """Configuration value -> only the host or the resource name (no credential, port, path or query); None when
    nothing safe is left. A URL gives its host (s3://bucket/x gives the bucket); host:port and user:pass@host give
    the host; a bare name stays as it is.

    A YAML null or boolean literal (null, ~, true, false and the YAML 1.1 yes, no, on, off, y, n, any case) gives
    None, and so does a value, with or without a scheme, whose authority has "=", ";" or "," (a connection string
    such as Server=db;Password=p@ss or sqlserver://db;password=p@ss, whose text after "@" may be part of the
    password) (SPEC-0076, Emendas v3 and v4).

    AWS (SPEC-0076), before the generic rule: an SQS queue URL (https://sqs.<region>.amazonaws.com/<account>/<queue>,
    the FIPS sqs-fips.<region>.amazonaws.com, the VPC endpoint [<vpce-id>.]sqs.<region>.vpce.amazonaws.com or the
    legacy https://<region>.queue.amazonaws.com/<account>/<queue>) and an SQS or SNS ARN
    (arn:<partition>:sqs|sns:<region>:<account>:<name>) give only the queue or topic name. The account, the region
    and the rest of the URL never leave: an SQS endpoint without exactly /<account>/<queue> as its path (no account,
    extra path, query) gives None, never the regional host alone; any other ARN gives None; an "@" anywhere in
    an SQS or ARN value gives None; and a VPC endpoint host of any other service (*.vpce.amazonaws.com) gives
    None, so no VPC endpoint host ever leaves whole (Emenda v4).

    Generic rule (G4 review): drop the scheme; the authority is the text up to the first "/", "?" or "#". An "@"
    after that point (path, query or fragment: it may be a password) makes the value ambiguous and gives None —
    losing a reference is acceptable, leaking never is. Otherwise the host is what follows the last "@" of the
    authority, without the port, and must be a strict host name, IP or resource name, else None."""
    if not isinstance(value, str):
        return None
    value = value.strip().strip("\"'").strip()
    if not value or any(c.isspace() for c in value) or value.lower() in YAML_LITERALS:
        return None
    if value[:4].lower() == "arn:":
        match = AWS_ARN_RE.match(value)
        return _resource_name(match.group(1)) if match and "@" not in value else None
    match = SCHEME_RE.match(value)
    rest = value[match.end():] if match else value
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if any(c in authority for c in "=;,"):
        return None
    host = _strip_port(authority.rsplit("@", 1)[-1])
    if host and SQS_HOST_RE.match(host):
        if "@" in value:
            return None
        path = SQS_PATH_RE.match(rest[len(authority):])
        return _resource_name(path.group(1)) if path else None
    if host and VPCE_HOST_RE.search(host):
        return None
    if "@" in rest[len(authority):]:
        return None
    if not host or not HOST_RE.match(host):
        return None
    return host


def _matches(key: str, suffixes) -> bool:
    upper = key.upper()
    return any(upper.endswith(suffix.upper()) for suffix in suffixes if suffix)


def _ref(key, value, suffixes):
    """"KEY=host" when the key ends in a suffix and the value has a host, else None."""
    if not isinstance(key, str) or not key or not _matches(key, suffixes):
        return None
    host = host_of(value)
    return f"{key}={host}" if host else None


def _from_name_value(items, suffixes, dotted=False) -> list:
    """[{name, value}, ...] (Helm parameters, plugin env) -> refs; dotted = the key is the last segment of name."""
    refs = []
    for item in _list(items):
        item = _dict(item)
        name = item.get("name")
        if dotted and isinstance(name, str):
            name = name.rsplit(".", 1)[-1]
        ref = _ref(name, item.get("value"), suffixes)
        if ref:
            refs.append(ref)
    return refs


def _unquote(value: str) -> str:
    """A YAML scalar as written on one line -> its text: quotes removed, a trailing comment dropped."""
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        return value[1:end] if end > 0 else value[1:]
    return value.split(" #", 1)[0].strip()


def _from_values_text(text, suffixes) -> list:
    """Helm values as YAML text -> refs, line by line: "KEY: value" (indented, quoted or not) and the env list form
    "- name: KEY" followed by "value: ...". Comment lines and trailing comments are ignored."""
    refs, pending = [], None
    for line in text.splitlines() if isinstance(text, str) else []:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        match = YAML_LINE_RE.match(line)
        if not match:
            continue
        if stripped.startswith("-"):
            pending = None
        key, value = match.group(1), _unquote((match.group(2) or "").strip())
        if key == "name":
            pending = value
            continue
        if key == "value" and pending:
            ref = _ref(pending, value, suffixes)
            pending = None
        else:
            ref = _ref(key, value, suffixes)
        if ref:
            refs.append(ref)
    return refs


def _from_values_object(node, suffixes) -> list:
    """Helm valuesObject (nested, any depth) -> refs from string values of matching keys and from {name, value}
    items (the env list form)."""
    refs = []
    if isinstance(node, dict):
        if isinstance(node.get("name"), str) and "value" in node:
            ref = _ref(node["name"], node.get("value"), suffixes)
            if ref:
                refs.append(ref)
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                refs += _from_values_object(value, suffixes)
            else:
                ref = _ref(key, value, suffixes)
                if ref:
                    refs.append(ref)
    elif isinstance(node, list):
        for item in node:
            refs += _from_values_object(item, suffixes)
    return refs


def extract_config_refs(source, suffixes=DEFAULT_REF_SUFFIXES) -> list:
    """spec.source of an Application -> sorted list, without repetition, of "KEY=host" (helm.parameters,
    helm.values, helm.valuesObject and plugin.env), only for keys ending in one of `suffixes` (any case)."""
    source = _dict(source)
    helm, plugin = _dict(source.get("helm")), _dict(source.get("plugin"))
    refs = _from_name_value(helm.get("parameters"), suffixes, dotted=True)
    refs += _from_values_text(helm.get("values"), suffixes)
    refs += _from_values_object(helm.get("valuesObject"), suffixes)
    refs += _from_name_value(plugin.get("env"), suffixes)
    return sorted(set(refs))


# --------------------------------------------------------------------------- mapping (pure functions)


def repository_ref(repo_url):
    """repoURL -> "repository:<owner>/<repo>" when it is a GitHub repository (https with or without .git or
    credentials, scp-like ssh or ssh://); else None (Helm chart repositories, other hosts). The id is lower case,
    as GitHub names are case-insensitive and the github collector emits them so (SPEC-0047)."""
    match = GITHUB_RE.match(repo_url.strip()) if isinstance(repo_url, str) else None
    return f"repository:{match.group(1)}/{match.group(2)}".lower() if match else None


def _simple_name(value):
    """A nameOverride value -> the name when it is a simple name (HOST_RE: no template, space or empty) and not a
    YAML null or boolean literal (null, ~, true, false, any case: Emenda v3), else None."""
    if not isinstance(value, str) or value.lower() in YAML_LITERALS:
        return None
    return value if HOST_RE.match(value) else None


def _name_override_in_text(text):
    """The first valid root "nameOverride: value" line of a Helm values text (no indentation), else None."""
    for line in text.splitlines() if isinstance(text, str) else []:
        match = NAME_OVERRIDE_LINE_RE.match(line)
        if match:
            name = _simple_name(_unquote((match.group(1) or "").strip()))
            if name:
                return name
    return None


def name_override(source):
    """spec.source of an Application -> its root Helm nameOverride when it is a simple name, else None. Argo CD and
    Helm precedence: helm.parameters (name exactly nameOverride), then helm.valuesObject (root key), then
    helm.values (a line without indentation); an invalid value is skipped and the next place is tried (SPEC-0076)."""
    helm = _dict(_dict(source).get("helm"))
    for item in _list(helm.get("parameters")):
        item = _dict(item)
        if item.get("name") == "nameOverride":
            name = _simple_name(item.get("value"))
            if name:
                return name
    name = _simple_name(_dict(helm.get("valuesObject")).get("nameOverride"))
    return name or _name_override_in_text(helm.get("values"))


def _service_from_pattern(name, service_pattern):
    """The group "service" of service_pattern (a compiled regex) searched in the Application name, when it takes
    part in the match and is a simple name (_simple_name); else None (SPEC-0082)."""
    if service_pattern is None or not isinstance(name, str):
        return None
    match = service_pattern.search(name)
    return _simple_name(match.group("service")) if match else None


def service_and_environment(app, env_label=DEFAULT_ENV_LABEL, service_label=DEFAULT_SERVICE_LABEL,
                            service_pattern=None):
    """Application -> (service, environment). Service: the service label; else the root Helm nameOverride of the
    first source (spec.source, then spec.sources) with a valid one (name_override, SPEC-0076); else the group
    "service" of service_pattern over the Application name, when it is a simple name (SPEC-0082); else the
    Application name. Environment: the environment label; else the destination namespace (None when there is
    none)."""
    app = _dict(app)
    metadata = _dict(app.get("metadata"))
    labels = _dict(metadata.get("labels"))
    spec = _dict(app.get("spec"))
    destination = _dict(spec.get("destination"))
    service = _text(labels.get(service_label))
    for source in _sources(spec) if not service else []:
        service = name_override(source)
        if service:
            break
    service = service or _service_from_pattern(_text(metadata.get("name")), service_pattern)
    service = service or _text(metadata.get("name"))
    environment = _text(labels.get(env_label)) or _text(destination.get("namespace"))
    return service, environment


def _cluster_id(destination: dict):
    """destination.server (without userinfo, should a URL carry one), or destination.name."""
    server = _text(destination.get("server"))
    if server:
        return re.sub(r"^([A-Za-z][A-Za-z0-9+.-]*://)[^/]*@", r"\1", server)
    return _text(destination.get("name"))


def _sources(spec: dict) -> list:
    """spec.source plus spec.sources (multi-source Applications)."""
    sources = [spec["source"]] if isinstance(spec.get("source"), dict) else []
    return sources + [s for s in _list(spec.get("sources")) if isinstance(s, dict)]


def normalize_image(value):
    """An image reference -> its normalized path, or None when it is dropped whole (SPEC-0082). The scheme
    (oci://, docker://), the digest ("@sha256:..."), the tag (":1.4.2", in the last segment) and the registry host
    (the first segment when it has "." or ":" or is localhost) are removed and the rest is lower case; it must match
    IMAGE_PATH_RE. A space, a credential ("user:pass@host/..."), any other "@" or nothing left = None. Nothing of a
    dropped image is ever returned or printed."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or any(c.isspace() for c in text):
        return None
    match = SCHEME_RE.match(text)
    text = text[match.end():] if match else text
    if "@" in text:
        name, _, digest = text.partition("@")  # "@" before a "/" = a credential, not a digest: dropped
        if not IMAGE_DIGEST_RE.match(digest):
            return None
        text = name
    head, sep, last = text.rpartition("/")
    last = last.split(":", 1)[0]
    segments = (head.split("/") if sep else []) + [last]
    first = segments[0].lower()
    if "." in first or ":" in first or first == "localhost":
        segments = segments[1:]
    path = "/".join(segments).lower()
    return path if path and IMAGE_PATH_RE.match(path) else None


def _image_repository_in_text(text):
    """The "repository" key directly under a root "image:" key of a Helm values text, else None."""
    root, child = None, None
    for line in text.splitlines() if isinstance(text, str) else []:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        match = YAML_LINE_RE.match(line)
        indent = len(line) - len(stripped)
        if indent == 0:
            root, child = (match.group(1) if match and not stripped.startswith("-") else None), None
            continue
        if root != "image" or not match or stripped.startswith("-"):
            continue
        child = indent if child is None else child
        if indent == child and match.group(1) == "repository":
            return _unquote((match.group(2) or "").strip())
    return None


def image_references(app) -> list:
    """The raw image references of an Application, in this order: status.summary.images, then the Helm
    image.repository of each source (helm.parameters, helm.valuesObject, helm.values)."""
    app = _dict(app)
    found = [i for i in _list(_dict(_dict(app.get("status")).get("summary")).get("images")) if isinstance(i, str)]
    for source in _sources(_dict(app.get("spec"))):
        helm = _dict(source.get("helm"))
        for item in _list(helm.get("parameters")):
            item = _dict(item)
            if item.get("name") == IMAGE_REPOSITORY_KEY and isinstance(item.get("value"), str):
                found.append(item["value"])
        repository = _dict(_dict(helm.get("valuesObject")).get("image")).get("repository")
        if isinstance(repository, str):
            found.append(repository)
        repository = _image_repository_in_text(helm.get("values"))
        if repository:
            found.append(repository)
    return found


def images_of(app) -> list:
    """Sorted list, without repetition, of the normalized images of an Application (normalize_image); [] when no
    image is valid."""
    return sorted({image for image in map(normalize_image, image_references(app)) if image})


def map_application(app, env_label=DEFAULT_ENV_LABEL, service_label=DEFAULT_SERVICE_LABEL,
                    suffixes=DEFAULT_REF_SUFFIXES, service_pattern=None):
    """One Application -> (entities deployment, service, environment, cluster; relations deploys, runs_in and
    sourced_from). Only the contract attrs of the deployment leave: annotations, status.resources and history
    are never read. `images` is there only when the Application has a valid image (SPEC-0082, Emenda v2)."""
    app = _dict(app)
    name = _text(_dict(app.get("metadata")).get("name"))
    if not name:
        return [], []
    spec, status = _dict(app.get("spec")), _dict(app.get("status"))
    destination = _dict(spec.get("destination"))
    sources = _sources(spec)
    refs = sorted({ref for source in sources for ref in extract_config_refs(source, suffixes)})
    deployment_ref = f"deployment:{name}"
    attrs = {
        "project": _text(spec.get("project")),
        "namespace": _text(destination.get("namespace")),
        "sync_status": _text(_dict(status.get("sync")).get("status")),
        "health_status": _text(_dict(status.get("health")).get("status")),
        "config_refs": refs,
    }
    images = images_of(app)
    if images:
        attrs["images"] = images
    entities = [entity("deployment", name, name, attrs)]
    relations = []
    service, environment = service_and_environment(app, env_label, service_label, service_pattern)
    for kind, eid, rtype in (("service", service, "deploys"), ("environment", environment, "runs_in"),
                             ("cluster", _cluster_id(destination), "runs_in")):
        if eid:
            entities.append(entity(kind, eid, eid, {}))
            relations.append(relation(deployment_ref, f"{kind}:{eid}", rtype))
    repositories = set()
    for source in sources:
        repo = repository_ref(source.get("repoURL"))
        if repo and repo not in repositories:
            repositories.add(repo)
            relations.append(relation(deployment_ref, repo, "sourced_from"))
    return entities, relations


def map_applications(apps, env_label=DEFAULT_ENV_LABEL, service_label=DEFAULT_SERVICE_LABEL,
                     suffixes=DEFAULT_REF_SUFFIXES, warnings=None, service_pattern=None):
    """List of Applications -> (entities without a repeated kind:id, relations without repetition). Shared
    entities (service, environment, cluster) appear once. A repeated Application name (Applications in several
    namespaces) keeps the whole first Application: the later one adds no entity or relation, and a warning naming
    it is appended to `warnings` when a list is given."""
    entities, relations, seen, linked, names = [], [], set(), set(), set()
    for app in _list(apps):
        name = _text(_dict(_dict(app).get("metadata")).get("name"))
        if name in names:
            if warnings is not None:
                namespace = _text(_dict(_dict(app).get("metadata")).get("namespace"))
                where = f" (namespace {namespace})" if namespace else ""
                warnings.append(f"aviso: Application repetida ignorada: {name}{where} — fica a primeira")
            continue
        app_entities, app_relations = map_application(app, env_label, service_label, suffixes, service_pattern)
        if name:
            names.add(name)
        for item in app_entities:
            key = (item["kind"], item["id"])
            if key not in seen:
                seen.add(key)
                entities.append(item)
        for item in app_relations:
            key = (item["from"], item["to"], item["type"])
            if key not in linked:
                linked.add(key)
                relations.append(item)
    return entities, relations


# --------------------------------------------------------------------------- sources: --input file and the CLI


def applications_of(data):
    """The Applications of a response: the list of `argocd app list -o json` (null = none) or the List object of
    `kubectl get -o json`; None when it is neither or an item is not an Application object."""
    if data is None:
        return []
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    if not isinstance(data, list):
        return None
    if not all(isinstance(item, dict) and isinstance(item.get("metadata"), dict) for item in data):
        return None
    return data


def read_input(path: str) -> list:
    """The Applications of a recorded response (--input), in either CLI format."""
    file = Path(path)
    if not file.is_file():
        raise CollectorError(f"--input: arquivo não encontrado: {path}")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise CollectorError(f"--input: {path}: não consegui ler o JSON ({type(e).__name__})") from None
    apps = applications_of(data)
    if apps is None:
        raise CollectorError(f"--input: {path}: não é uma lista de Applications")
    return apps


def run_cli(cli: str) -> list:
    """The only external process of the collector: the chosen CLI's read-only list command, argv as a list, never
    a shell, stdin closed (no prompt), with a timeout. Returns the Applications."""
    missing = f"{cli} não encontrado — veja {GUIDE}"
    executable = shutil.which(cli)
    if executable is None:
        raise CollectorError(missing)
    env = dict(os.environ, NO_COLOR="1")
    try:
        proc = subprocess.run([executable, *COMMANDS[cli]], stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=CLI_TIMEOUT, env=env,
                              check=False)
    except FileNotFoundError:
        raise CollectorError(missing) from None
    except subprocess.TimeoutExpired:
        raise CollectorError(f"{cli}: tempo esgotado ({CLI_TIMEOUT} s)") from None
    except OSError as e:
        raise CollectorError(f"não consegui executar {cli}: {e.strerror or e}") from None
    if proc.returncode != 0:
        stderr = proc.stderr or ""
        if ACCESS_DENIED.search(stderr):
            raise CollectorError(f"{NO_ACCESS} ({cli} saiu com {proc.returncode}) — veja {GUIDE}")
        last = stderr.strip().splitlines()[-1:] or [""]
        detail = f": {last[0][:200]}" if last[0] else ""
        raise CollectorError(f"{cli} falhou (saiu com {proc.returncode}){detail}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise CollectorError(f"{INVALID} ({cli}: não é JSON)") from None
    apps = applications_of(data)
    if apps is None:
        raise CollectorError(f"{INVALID} ({cli}: não é uma lista de Applications)")
    return apps


# --------------------------------------------------------------------------- collection


def parse_suffixes(text: str) -> tuple:
    return tuple(s.strip() for s in (text or "").split(",") if s.strip())


def compile_service_pattern(text):
    """--service-pattern -> compiled regex, None when not given; ValueError with the reason (never the pattern)
    when it does not compile or has no group named "service" (SPEC-0082)."""
    if text is None:
        return None
    try:
        pattern = re.compile(text)
    except re.error as e:
        raise ValueError(f"regex que não compila ({e.msg})") from None
    if "service" not in pattern.groupindex:
        raise ValueError('falta o grupo nomeado "service" (?P<service>...)')
    return pattern


def build_parser():
    parser = argparse.ArgumentParser(prog="argocd.py", description="Coletor argocd da boson-atlas")
    parser.add_argument("--from", dest="source", required=True, choices=("argocd", "kubectl"),
                        help="CLI que lê as Applications")
    parser.add_argument("--env-label", default=DEFAULT_ENV_LABEL, help="label do ambiente")
    parser.add_argument("--service-label", default=DEFAULT_SERVICE_LABEL, help="label do serviço")
    parser.add_argument("--service-pattern", default=None,
                        help='regex sobre o nome da Application com o grupo "service" (ex.: ^(?:dev|qa)-(?P<service>.+)$)')
    parser.add_argument("--ref-suffixes", default=",".join(DEFAULT_REF_SUFFIXES),
                        help="sufixos das chaves de configuração extraídas (a,b)")
    parser.add_argument("--input", default=None, help="arquivo JSON com as Applications em vez da CLI")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    suffixes = parse_suffixes(args.ref_suffixes)
    if not suffixes:
        parser.error("--ref-suffixes precisa de ao menos um sufixo")
    try:
        service_pattern = compile_service_pattern(args.service_pattern)
    except ValueError as e:
        parser.error(f"--service-pattern inválido: {e}")
    try:
        apps = read_input(args.input) if args.input else run_cli(args.source)
        warnings = []
        entities, relations = map_applications(apps, args.env_label, args.service_label, suffixes, warnings,
                                               service_pattern)
    except CollectorError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(warning, file=sys.stderr)
    data = {"contract": CONTRACT, "collector": COLLECTOR, "category": CATEGORY, "collected_at": utc_now(),
            "entities": entities, "relations": relations}
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
