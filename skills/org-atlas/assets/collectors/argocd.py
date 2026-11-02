#!/usr/bin/env python3
"""argocd collector of the org-atlas (SPEC-0035), category delivery: deployments, services, environments, clusters,
the source repository of each deployment and its configuration references, read from the Argo CD Applications.
Stdlib only, Python 3.9+; prints the org-atlas/collector@1 output (ADR-0011).

Usage: python3 argocd.py --from argocd|kubectl [--env-label KEY] [--service-label KEY]
                         [--ref-suffixes _HOST,_URL,...] [--input FILE]

Only the Application list is read (`argocd app list -o json` or `kubectl get applications.argoproj.io -A -o json`):
never Secrets, rendered manifests or cluster state. From the Helm parameters, Helm values and plugin env only the
key names ending in a configured suffix leave the collector, each with the bare host or resource name of its value:
user, password, port, path and query are stripped here, before the scan's redaction (two layers, spec §4).
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

CONTRACT = "org-atlas/collector@1"
COLLECTOR = "argocd"
CATEGORY = "delivery"
DEFAULT_ENV_LABEL = "env"
DEFAULT_SERVICE_LABEL = "app.kubernetes.io/part-of"
DEFAULT_REF_SUFFIXES = ("_HOST", "_URL", "_DSN", "_ADDR", "_QUEUE", "_TOPIC", "_BUCKET")
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
# "KEY: value" in a Helm values text, optionally as a list item ("- KEY: value")
YAML_LINE_RE = re.compile(r"^\s*(?:-\s+)?([A-Za-z0-9_.-]+)\s*:(?:\s+(.*))?$")
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


def host_of(value):
    """Configuration value -> only the host or the resource name (no credential, port, path or query); None when
    nothing safe is left. A URL gives its host (s3://bucket/x gives the bucket); host:port and user:pass@host give
    the host; a bare name stays as it is.

    Rule (G4 review): drop the scheme; the authority is the text up to the first "/", "?" or "#". An "@" after
    that point (path, query or fragment: it may be a password) makes the value ambiguous and gives None — losing a
    reference is acceptable, leaking never is. Otherwise the host is what follows the last "@" of the authority,
    without the port, and must be a strict host name, IP or resource name, else None."""
    if not isinstance(value, str):
        return None
    value = value.strip().strip("\"'").strip()
    if not value or any(c.isspace() for c in value):
        return None
    match = SCHEME_RE.match(value)
    rest = value[match.end():] if match else value
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if "@" in rest[len(authority):]:
        return None
    host = _strip_port(authority.rsplit("@", 1)[-1])
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
    credentials, scp-like ssh or ssh://); else None (Helm chart repositories, other hosts)."""
    match = GITHUB_RE.match(repo_url.strip()) if isinstance(repo_url, str) else None
    return f"repository:{match.group(1)}/{match.group(2)}" if match else None


def service_and_environment(app, env_label=DEFAULT_ENV_LABEL, service_label=DEFAULT_SERVICE_LABEL):
    """Application -> (service, environment): the label when present; else the Application name and the
    destination namespace (None when the destination has no namespace)."""
    app = _dict(app)
    metadata = _dict(app.get("metadata"))
    labels = _dict(metadata.get("labels"))
    destination = _dict(_dict(app.get("spec")).get("destination"))
    service = _text(labels.get(service_label)) or _text(metadata.get("name"))
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


def map_application(app, env_label=DEFAULT_ENV_LABEL, service_label=DEFAULT_SERVICE_LABEL,
                    suffixes=DEFAULT_REF_SUFFIXES):
    """One Application -> (entities deployment, service, environment, cluster; relations deploys, runs_in and
    sourced_from). Only the contract attrs of the deployment leave: annotations, status.resources and history
    are never read."""
    app = _dict(app)
    name = _text(_dict(app.get("metadata")).get("name"))
    if not name:
        return [], []
    spec, status = _dict(app.get("spec")), _dict(app.get("status"))
    destination = _dict(spec.get("destination"))
    sources = _sources(spec)
    refs = sorted({ref for source in sources for ref in extract_config_refs(source, suffixes)})
    deployment_ref = f"deployment:{name}"
    entities = [entity("deployment", name, name, {
        "project": _text(spec.get("project")),
        "namespace": _text(destination.get("namespace")),
        "sync_status": _text(_dict(status.get("sync")).get("status")),
        "health_status": _text(_dict(status.get("health")).get("status")),
        "config_refs": refs,
    })]
    relations = []
    service, environment = service_and_environment(app, env_label, service_label)
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
                     suffixes=DEFAULT_REF_SUFFIXES, warnings=None):
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
        app_entities, app_relations = map_application(app, env_label, service_label, suffixes)
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


def build_parser():
    parser = argparse.ArgumentParser(prog="argocd.py", description="Coletor argocd da org-atlas")
    parser.add_argument("--from", dest="source", required=True, choices=("argocd", "kubectl"),
                        help="CLI que lê as Applications")
    parser.add_argument("--env-label", default=DEFAULT_ENV_LABEL, help="label do ambiente")
    parser.add_argument("--service-label", default=DEFAULT_SERVICE_LABEL, help="label do serviço")
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
        apps = read_input(args.input) if args.input else run_cli(args.source)
        warnings = []
        entities, relations = map_applications(apps, args.env_label, args.service_label, suffixes, warnings)
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
