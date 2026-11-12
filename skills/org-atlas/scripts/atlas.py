#!/usr/bin/env python3
"""Deterministic tooling for the org-atlas skill (stdlib only, Python 3.9+). Run with --help.

Two configuration layers (ADR-0010): the local one, per machine, in $ATLAS_CONFIG_HOME/config.yml (atlas path and
credential names, never values) and the shared one, in <atlas>/atlas-config.yml (never an absolute path).
init creates the atlas structure from assets/ (or, with --join, only the local layer); config shows the effective
configuration with the origin of each value; doctor reports what is configured, what works and what is missing,
looking only at files, shutil.which and os.environ (never at a variable's value).
run_collector is the only function allowed to run an external process (SPEC-0033).
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

ATLAS_VERSION = "2026.11.1"
SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets"
DEFAULT_SHARED_CONFIG = ASSETS_DIR / "atlas-config.yml"
PAGES_DIR = ASSETS_DIR / "pages"

SHARED_FILE = "atlas-config.yml"
MODES = ("repo", "local")
LOCAL_KEYS = ("atlas", "credentials")
SHARED_KEYS = ("version", "organization", "mode", "language", "stale_days", "categories", "collectors",
               "redaction", "curation", "ci")
REQUIRED_SHARED = ("version", "organization", "mode")
SHARED_VERSION = "1"
STRUCTURE_DIRS = ("services", "platform", "conventions", "process", "snapshots")
STRUCTURE_PAGES = ("ATLAS.md", "glossary.md")  # copied from assets/pages/
KEEP_FILE = ".gitkeep"  # keeps the empty folders in a git repository (mode repo)
IGNORED_IN_EMPTY = (".git", ".DS_Store", "Thumbs.db", "desktop.ini")  # an "empty" folder may have them
ORIGIN_LOCAL, ORIGIN_ATLAS, ORIGIN_DEFAULT = "local", "atlas", "padrão"
NOT_CONFIGURED = "org-atlas não configurado nesta máquina — rode init (ou init --join)"
LOCAL_HEADER = ("# org-atlas — configuração local desta máquina (references/config.md). Não vai para o atlas.\n"
                "# credentials: só NOMES de variável de ambiente e de profile, nunca valores.\n")
ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*\Z")  # \Z: "NAME\n" is not a name
KEY_RE = re.compile(r"^([^\s'\"#{}\[\],:][^:]*?)\s*:(?:\s+(.*))?$")
NEEDS_QUOTES_RE = re.compile(r":\s|:$|\s#|^[\[\]{}&*!|>'\"%@`,#?:-]|^\s|\s$|\"|\\")
ABSOLUTE_RE = re.compile(r"^(/|~|[A-Za-z]:[\\/]|\\\\)")
FLOW_SPECIAL = ",[]{}"


class AtlasError(Exception):
    """Error shown to the user without a traceback; `code` is the exit code."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- yaml subset

def strip_comment(line: str) -> str:
    """Remove the ` # ...` comment outside quotes (a whole-line comment becomes empty)."""
    quote, previous, skip = None, "", False
    for i, char in enumerate(line):
        if skip:
            skip = False
        elif quote:
            escape = "\\" if quote == '"' else "'"  # \" inside "...", '' inside '...'
            if char == escape and (quote == '"' or line[i + 1:i + 2] == "'"):
                skip = True
            elif char == quote:
                quote = None
        elif char in "\"'" and previous in ("", ":", "[", "{", ",", "-"):  # a quote opens only a value
            quote = char
        elif char == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
        if not char.isspace():
            previous = char
    return line.rstrip()


def _quoted(text: str, i: int):
    """(string, next index) of the quoted scalar starting at text[i]."""
    if text[i] == '"':
        m = re.compile(r'"((?:[^"\\]|\\.)*)"').match(text, i)
        if not m:
            raise ValueError(f"aspas sem fechar: {text[i:]}")
        return json.loads(m.group(0)), m.end()
    m = re.compile(r"'((?:[^']|'')*)'").match(text, i)
    if not m:
        raise ValueError(f"aspas sem fechar: {text[i:]}")
    return m.group(1).replace("''", "'"), m.end()


def _flow(text: str, i: int):
    """(value, next index) of a flow value — `{a: b}`, `[a, b]`, quoted or bare scalar — at text[i]."""
    while i < len(text) and text[i] == " ":
        i += 1
    if i >= len(text):
        return "", i
    if text[i] in "\"'":
        return _quoted(text, i)
    if text[i] in "[{":
        closing, items, data = ("]" if text[i] == "[" else "}"), [], {}
        i += 1
        while True:
            while i < len(text) and text[i] in " ,":
                i += 1
            if i >= len(text):
                raise ValueError(f"'{closing}' sem fechar: {text}")
            if text[i] == closing:
                return (items if closing == "]" else data), i + 1
            if closing == "]":
                value, i = _flow(text, i)
                items.append(value)
                continue
            key, i = _flow_key(text, i)
            data[key], i = _flow(text, i)
    end = i
    while end < len(text) and text[end] not in FLOW_SPECIAL:
        end += 1
    return text[i:end].strip(), end


def _flow_key(text: str, i: int):
    if text[i] in "\"'":
        key, i = _quoted(text, i)
    else:
        end = text.find(":", i)
        if end < 0:
            raise ValueError(f"chave sem ':' em {text}")
        key, i = text[i:end].strip(), end
    while i < len(text) and text[i] == " ":
        i += 1
    if i >= len(text) or text[i] != ":":
        raise ValueError(f"chave sem ':' em {text}")
    return key, i + 1


def parse_scalar(value: str):
    """Block-context value: quoted string, inline map/list or bare string (no type conversion)."""
    value = value.strip()
    if not value:
        return ""
    if value[0] in "\"'[{":
        parsed, end = _flow(value, 0)
        if value[end:].strip():
            raise ValueError(f"texto depois do valor: {value}")
        return parsed
    return value


def _is_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def parse_yaml(text: str) -> dict:
    """YAML subset of the skill: `key: value`, nested maps by indentation, inline `{}`/`[]`, `- item` lists (also
    of maps: `- id: x` followed by the other keys of the item), comments and quoted strings. Same style as the
    parser of the other skills, but written here (ADR-0010). Scalars stay strings."""
    rows = []
    for raw in text.splitlines():
        line = strip_comment(raw)
        if not line.strip():
            continue
        indent, content = len(line) - len(line.lstrip(" ")), line.strip()
        if content.startswith("- ") and KEY_RE.match(content[2:].strip()):  # first key of a map item
            rest = content[2:].lstrip()
            rows.append((indent, "-"))
            rows.append((indent + len(content) - len(rest), rest))
        else:
            rows.append((indent, content))
    if not rows:
        return {}
    value, _ = _parse_block(rows, 0, rows[0][0])
    return value if isinstance(value, dict) else {}


def _parse_block(rows, i: int, indent: int):
    if _is_item(rows[i][1]):
        items = []
        while i < len(rows) and rows[i][0] == indent and _is_item(rows[i][1]):
            rest = rows[i][1][1:].strip()
            i += 1
            if not rest and i < len(rows) and rows[i][0] > indent:
                value, i = _parse_block(rows, i, rows[i][0])
            else:
                value = parse_scalar(rest)
            items.append(value)
        return items, i
    data = {}
    while i < len(rows) and rows[i][0] >= indent:
        if rows[i][0] > indent:  # deeper line without a parent key: ignored
            i += 1
            continue
        pair = KEY_RE.match(rows[i][1])
        i += 1
        if not pair:
            continue
        key, rest = pair.group(1).strip(), (pair.group(2) or "").strip()
        if rest:
            data[key] = parse_scalar(rest)
        elif i < len(rows) and (rows[i][0] > indent or (rows[i][0] == indent and _is_item(rows[i][1]))):
            data[key], i = _parse_block(rows, i, rows[i][0])
        else:
            data[key] = ""
    return data, i


def fmt_scalar(value, flow: bool = False) -> str:
    value = "" if value is None else str(value)
    if (value == "" or NEEDS_QUOTES_RE.search(value) or "\n" in value
            or (flow and any(c in value for c in FLOW_SPECIAL))):
        return json.dumps(value, ensure_ascii=False)
    return value


def fmt_flow(value) -> str:
    if isinstance(value, dict):
        return "{" + ", ".join(f"{fmt_scalar(k, True)}: {fmt_flow(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(fmt_flow(v) for v in value) + "]"
    return fmt_scalar(value, flow=True)


def dump_yaml(data: dict, indent: int = 0) -> str:
    """Writer of the same subset: parse_yaml(dump_yaml(d)) == d for strings, lists and nested maps."""
    pad, lines = " " * indent, []
    for key, value in data.items():
        name = fmt_scalar(key)
        if isinstance(value, dict) and value:
            lines.append(f"{pad}{name}:\n{dump_yaml(value, indent + 2)}")
        elif isinstance(value, list) and value:
            lines.append(f"{pad}{name}:\n" + "".join(f"{pad}  - {fmt_flow(item)}\n" for item in value))
        else:
            lines.append(f"{pad}{name}: {fmt_flow(value)}\n")
    return "".join(lines)


def read_text(path: Path) -> str:
    """Text of a UTF-8 file; unreadable or not UTF-8 = AtlasError (code 1) naming the file, without a traceback."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise AtlasError(f"não consegui ler {path}: {e}", 1) from e


def read_yaml(path: Path) -> dict:
    try:
        return parse_yaml(read_text(path))
    except ValueError as e:
        raise AtlasError(f"não consegui ler {path}: {e}", 1) from e


# ---------------------------------------------------------------- paths

def local_config_path(config_home=None) -> Path:
    """$ATLAS_CONFIG_HOME/config.yml (default ~/.config/org-atlas/config.yml); config_home wins over both."""
    if config_home:
        base = Path(config_home)
    elif os.environ.get("ATLAS_CONFIG_HOME"):
        base = Path(os.environ["ATLAS_CONFIG_HOME"])
    else:
        base = Path.home() / ".config" / "org-atlas"
    return base / "config.yml"


def absolute(path) -> str:
    """Absolute path as typed (symlinks kept: each machine records its own path to the atlas)."""
    return os.path.abspath(os.path.expanduser(str(path)))


def absolute_values(value, path=""):
    """(key path, value) of each string that looks like an absolute path (ADR-0010: never in atlas-config.yml)."""
    if isinstance(value, dict):
        found = []
        for key, item in value.items():
            found += absolute_values(item, f"{path}.{key}" if path else str(key))
        return found
    if isinstance(value, list):
        found = []
        for index, item in enumerate(value):
            found += absolute_values(item, f"{path}[{index}]")
        return found
    return [(path, value)] if isinstance(value, str) and ABSOLUTE_RE.match(value) else []


# ---------------------------------------------------------------- configuration

def default_shared() -> dict:
    return parse_yaml(DEFAULT_SHARED_CONFIG.read_text(encoding="utf-8"))


def validate_mode(mode) -> None:
    if mode not in MODES:
        raise AtlasError(f"mode inválido: {mode} — use um de: {' | '.join(MODES)}", 2)


def _set_value(text: str, key: str, value: str) -> str:
    """text with the value of the top-level `key:` line replaced, keeping the line's trailing comment."""
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(key)}\s*:", line):
            body = line.rstrip("\r\n")
            comment = body[len(strip_comment(body)):]
            lines[index] = f"{key}: {fmt_scalar(value)}{comment}{line[len(body):]}"
            return "".join(lines)
    raise AtlasError(f"{DEFAULT_SHARED_CONFIG} sem a chave {key}", 1)


def render_atlas_config(organization, mode) -> str:
    """Text of the atlas-config.yml that init writes: assets/atlas-config.yml with its comments; only
    organization and mode change. Never holds an absolute path."""
    validate_mode(mode)
    organization = str(organization or "").strip()
    if not organization:
        raise AtlasError("organização vazia — passe --org NOME", 2)
    if ABSOLUTE_RE.match(organization):
        raise AtlasError("organization não pode ser um caminho absoluto", 2)
    text = DEFAULT_SHARED_CONFIG.read_text(encoding="utf-8")
    expected = dict(parse_yaml(text), organization=organization, mode=mode)
    text = _set_value(_set_value(text, "organization", organization), "mode", mode)
    if parse_yaml(text) != expected:
        raise AtlasError(f"não consegui gerar o atlas-config.yml a partir de {DEFAULT_SHARED_CONFIG}", 1)
    return text


def env_names(entry) -> list:
    names = entry.get("env", []) if isinstance(entry, dict) else []
    return [names] if isinstance(names, str) and names else list(names or [])


def validate_credentials(credentials) -> None:
    """credentials = {<collector>: {"env": [NAME, ...], "profile": <name>}}: only names, never values. The error
    message names the collector and never repeats the value received."""
    if credentials in ("", None):
        return
    if not isinstance(credentials, dict):
        raise AtlasError("credentials precisa ser um mapa <coletor>: {env: [NOME, ...], profile: <nome>}", 2)
    for collector, entry in credentials.items():
        problem = f"credentials aceita só nomes de variável: {collector}"
        if entry in ("", None):
            continue
        if not isinstance(entry, dict):
            raise AtlasError(problem, 2)
        names = entry.get("env", [])
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list) or any(not isinstance(n, str) or not ENV_NAME_RE.match(n) for n in names):
            raise AtlasError(problem, 2)
        profile = entry.get("profile", "")
        if not isinstance(profile, str) or any(c.isspace() for c in profile):
            raise AtlasError(f"credentials aceita só um nome de profile, sem espaços: {collector}", 2)


CI_KEYS = ("env", "schedule")
CRON_FIELD_RE = re.compile(r"^[0-9A-Za-z*/,?#-]+$")
CI_ENV_PROBLEM = "ci.env aceita só nomes de variável (^[A-Z_][A-Z0-9_]*$): o valor fica nos secrets da plataforma"


def valid_cron(value) -> bool:
    """A 5-field cron expression (minute hour day month weekday), as the CI platforms accept it."""
    fields = str(value).split() if isinstance(value, (str, int)) else []
    return len(fields) == 5 and all(CRON_FIELD_RE.match(f) for f in fields)


def validate_ci(ci) -> None:
    """ci = {env: [NAME, ...], schedule: CRON} (SPEC-0040): only variable names, never values. The error message
    never repeats the value received."""
    if ci in ("", None):
        return
    if not isinstance(ci, dict):
        raise AtlasError("ci precisa ser um mapa {env: [NOME, ...], schedule: CRON}", 2)
    unknown = [key for key in ci if key not in CI_KEYS]
    if unknown:
        raise AtlasError(f"ci aceita só as chaves {', '.join(CI_KEYS)}", 2)
    names = ci.get("env")
    names = [] if names in ("", None) else [names] if isinstance(names, str) else names
    if not isinstance(names, list) or any(not isinstance(n, str) or not ENV_NAME_RE.match(n) for n in names):
        raise AtlasError(CI_ENV_PROBLEM, 2)
    schedule = ci.get("schedule")
    if schedule not in (None, "") and not valid_cron(schedule):
        raise AtlasError("ci.schedule precisa ser uma expressão cron de 5 campos (ex.: \"0 6 * * 1\")", 2)


def ci_env_names(ci) -> list:
    names = ci.get("env") if isinstance(ci, dict) else None
    return [] if names in ("", None) else [names] if isinstance(names, str) else list(names)


def read_local(config_home=None):
    """(path, local layer) of this machine; without it raises AtlasError(NOT_CONFIGURED, 3)."""
    path = local_config_path(config_home)
    if not path.is_file():
        raise AtlasError(NOT_CONFIGURED, 3)
    return path, read_yaml(path)


def load_config(config_home=None) -> dict:
    """Effective configuration: local layer + <atlas>/atlas-config.yml + defaults, with the origin of each
    top-level value ("local" | "atlas" | "padrão"). Invalid credentials raise AtlasError (code 2) without writing
    anything; an unreadable atlas-config.yml raises AtlasError (code 1)."""
    _, local = read_local(config_home)
    values, origins = {}, {}
    atlas = local.get("atlas")
    present = isinstance(atlas, str) and atlas != ""
    values["atlas"], origins["atlas"] = (atlas if present else ""), (ORIGIN_LOCAL if present else ORIGIN_DEFAULT)
    credentials = local.get("credentials")
    validate_credentials(credentials)
    values["credentials"] = credentials if isinstance(credentials, dict) else {}
    origins["credentials"] = ORIGIN_LOCAL if "credentials" in local else ORIGIN_DEFAULT
    shared_path = Path(values["atlas"]) / SHARED_FILE if values["atlas"] else None
    shared = read_yaml(shared_path) if shared_path and shared_path.is_file() else {}
    validate_ci(shared.get("ci"))
    defaults = dict(default_shared(), organization="", mode="")
    for key in SHARED_KEYS:
        found = key in shared
        values[key] = shared[key] if found else defaults.get(key, "")
        origins[key] = ORIGIN_ATLAS if found else ORIGIN_DEFAULT
    return {"values": values, "origins": origins}


def render_local_config(atlas: str, credentials=None) -> str:
    return LOCAL_HEADER + dump_yaml({"atlas": atlas, "credentials": credentials or {}})


def write_local_config(path: Path, text: str):
    """The local layer lives outside the atlas: replaced atomically (it is the machine's pointer to the atlas)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def existing_credentials(path: Path) -> dict:
    """Credentials already declared in this machine's local layer (kept when init rewrites it)."""
    if not path.is_file():
        return {}
    credentials = read_yaml(path).get("credentials")
    validate_credentials(credentials)
    return credentials if isinstance(credentials, dict) else {}


# ---------------------------------------------------------------- collector contract (ADR-0011)

CONTRACT = "org-atlas/collector@1"
SUPPORTED_CONTRACTS = (CONTRACT,)  # a breaking @2 keeps accepting the previous version (ADR-0011)
CATEGORIES = ("code", "ci", "delivery", "runtime", "data", "messaging", "observability", "tracker", "docs",
              "secrets")
KINDS = ("repository", "service", "environment", "deployment", "cluster", "datastore", "queue", "topic", "bucket",
         "secret-ref", "pipeline", "team")
RELATION_TYPES = ("builds", "sourced_from", "deploys", "runs_in", "reads", "writes", "publishes", "consumes",
                  "depends_on", "owns")
OUTPUT_FIELDS = ("contract", "collector", "category", "collected_at", "entities", "relations")
OUTPUT_ALLOWED = OUTPUT_FIELDS + ("signals",)
ENTITY_FIELDS = ("kind", "id", "name", "attrs", "source")
RELATION_FIELDS = ("from", "to", "type", "source")
RELATION_ALLOWED = RELATION_FIELDS + ("inferred",)
SIGNAL_ALLOWED = ("type", "repository", "total", "pattern_counts", "sample", "counts", "present")
# keys whose name says "secret": dropped and reported, never a violation (ADR-0011); fields outside the contract
# get the same treatment (G4 review): only the contract's fields reach the snapshot
FORBIDDEN_WORDS = ("password", "passwd", "secret", "token", "credential")  # anywhere in the name (api_token)
FORBIDDEN_PARTS = ("key", "keys", "private", "pwd")  # a whole part of the name (api_key, db_pwd), or ...key at the end
ENTITY_REF_RE = re.compile(r"^([a-z][a-z-]*):(.+)$")
COLLECTED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")
NAME_PARTS_RE = re.compile(r"[a-z0-9]+")
SCALARS = (str, int, float, bool, type(None))


def is_scalar_value(value) -> bool:
    """attrs value allowed by the contract: a scalar or a list of scalars."""
    return isinstance(value, SCALARS) or (isinstance(value, list) and all(isinstance(v, SCALARS) for v in value))


def is_forbidden_key(name) -> bool:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name)).lower()  # camelCase -> camel_case
    parts = NAME_PARTS_RE.findall(text)
    return (any(word in text for word in FORBIDDEN_WORDS) or any(part in FORBIDDEN_PARTS for part in parts)
            or text.endswith(("key", "keys")))


def entity_ref_problem(value) -> bool:
    """True when value is not kind:id with a kind of the contract."""
    m = ENTITY_REF_RE.match(value) if isinstance(value, str) else None
    return not m or m.group(1) not in KINDS


def _keep_fields(obj: dict, allowed, where: str, dropped: list) -> dict:
    """obj with only the contract's fields; each other field is dropped and reported by name (never by value)."""
    kept = {}
    for name, value in obj.items():
        if name not in allowed:
            dropped.append(f"{where}: campo {name} descartado (fora do contrato)")
        elif is_forbidden_key(name):
            dropped.append(f"{where}: {name} descartada (chave proibida)")
        else:
            kept[name] = value
    return kept


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _text_fields(obj: dict, fields, where: str, violations: list) -> None:
    """Each present field of `fields` must be text; the message never repeats the value (it may be a secret)."""
    for name in fields:
        if name in obj and not isinstance(obj[name], str):
            violations.append(f"{where}: {name} precisa ser texto")


def _check_entity(index: int, entity, seen: set, violations: list, dropped: list):
    where = f"entities[{index}]"
    if not isinstance(entity, dict):
        violations.append(f"{where}: precisa ser um objeto {{kind, id, name, attrs, source}}")
        return entity
    missing = [field for field in ENTITY_FIELDS if field not in entity]
    if missing:
        violations.append(f"{where}: faltam campos: {', '.join(missing)}")
    _text_fields(entity, ("kind", "id", "name", "source"), where, violations)
    kind, eid = entity.get("kind"), entity.get("id")
    if isinstance(kind, str) and kind not in KINDS:
        violations.append(f"{where}: kind desconhecido: {kind}")
    named = isinstance(kind, str) and isinstance(eid, str)
    key = f"{kind}:{eid}" if named else where
    if named:
        if key in seen:
            violations.append(f"{where}: chave repetida: {key}")
        seen.add(key)
    clean = _keep_fields(entity, ENTITY_FIELDS, key, dropped)
    attrs = entity.get("attrs", {})
    if not isinstance(attrs, dict):
        violations.append(f"{where}: attrs precisa ser um objeto")
        return clean
    kept = {}
    for name, value in attrs.items():
        if is_forbidden_key(name):
            dropped.append(f"{key}: attrs.{name} descartada (chave proibida)")
            continue
        if not is_scalar_value(value):
            violations.append(f"{where}: attrs.{name} não é escalar")
        kept[name] = value
    if "attrs" in clean:
        clean["attrs"] = kept
    return clean


def _check_relation(index: int, relation, violations: list, dropped: list):
    where = f"relations[{index}]"
    if not isinstance(relation, dict):
        violations.append(f"{where}: precisa ser um objeto {{from, to, type, source}}")
        return relation
    missing = [field for field in RELATION_FIELDS if field not in relation]
    if missing:
        violations.append(f"{where}: faltam campos: {', '.join(missing)}")
    _text_fields(relation, RELATION_FIELDS, where, violations)
    if "inferred" in relation and not isinstance(relation["inferred"], bool):
        violations.append(f"{where}: inferred precisa ser true ou false")
    if isinstance(relation.get("type"), str) and relation["type"] not in RELATION_TYPES:
        violations.append(f"{where}: type desconhecido: {relation['type']}")
    for end in ("from", "to"):
        if isinstance(relation.get(end), str) and entity_ref_problem(relation[end]):
            violations.append(f"{where}: {end} fora do formato kind:id: {relation[end]}")
    return _keep_fields(relation, RELATION_ALLOWED, where, dropped)


def _flat_object(value, allowed) -> bool:
    return isinstance(value, dict) and all(allowed(v) for v in value.values())


def _check_signal(index: int, signal, violations: list, dropped: list):
    where = f"signals[{index}]"
    if not isinstance(signal, dict) or not isinstance(signal.get("type"), str):
        violations.append(f"{where}: precisa ser um objeto com type")
        return signal
    _text_fields(signal, ("repository",), where, violations)
    if "sample" in signal and not (isinstance(signal["sample"], list)
                                   and all(isinstance(item, str) for item in signal["sample"])):
        violations.append(f"{where}: sample precisa ser uma lista de textos")
    if "total" in signal and not _is_number(signal["total"]):
        violations.append(f"{where}: total precisa ser um número")
    if "pattern_counts" in signal and not _flat_object(signal["pattern_counts"], _is_number):
        violations.append(f"{where}: pattern_counts precisa ser um objeto de números")
    if "counts" in signal and not _flat_object(signal["counts"], _is_number):
        violations.append(f"{where}: counts precisa ser um objeto de números")
    if "present" in signal and not _flat_object(signal["present"], lambda v: isinstance(v, bool)):
        violations.append(f"{where}: present precisa ser um objeto de booleanos")
    return _keep_fields(signal, SIGNAL_ALLOWED, where, dropped)


def validate_collector_output(data) -> tuple:
    """(clean, violations, dropped) of a collector output against org-atlas/collector@1 (ADR-0011).

    violations empty = valid. A relation to an entity of another collector is valid (only the kind:id format is
    checked; dangling references are a lint warning, SPEC-0039). Only the contract's fields stay in `clean`
    (output, entity, relation and signal); any other field and every forbidden key (password, passwd, pwd, secret,
    token, key, credential, private — in attrs and in a signal) is dropped and reported in `dropped` by where it
    was and its name, never its value. Dropping is not a violation."""
    if not isinstance(data, dict):
        return data, ["a saída não é um objeto JSON"], []
    violations, dropped = [], []
    missing = [field for field in OUTPUT_FIELDS if field not in data]
    if missing:
        violations.append(f"faltam campos: {', '.join(missing)}")
    _text_fields(data, ("contract", "category", "collected_at"), "saída", violations)
    if isinstance(data.get("contract"), str) and data["contract"] not in SUPPORTED_CONTRACTS:
        violations.append(f"contract não suportado: {data['contract']}")
    if "collector" in data and not (isinstance(data["collector"], str) and data["collector"]):
        violations.append("collector precisa ser um texto não vazio")
    if isinstance(data.get("category"), str) and data["category"] not in CATEGORIES:
        violations.append(f"category desconhecida: {data['category']}")
    if isinstance(data.get("collected_at"), str) and not COLLECTED_AT_RE.match(data["collected_at"]):
        violations.append(f"collected_at fora do formato ISO 8601 UTC (AAAA-MM-DDTHH:MM:SSZ): {data['collected_at']}")
    clean = _keep_fields(data, OUTPUT_ALLOWED, "saída", dropped)
    entities = data.get("entities", [])
    if not isinstance(entities, list):
        violations.append("entities precisa ser uma lista")
    else:
        seen = set()
        clean["entities"] = [_check_entity(i, e, seen, violations, dropped) for i, e in enumerate(entities)]
    relations = data.get("relations", [])
    if not isinstance(relations, list):
        violations.append("relations precisa ser uma lista")
    else:
        clean["relations"] = [_check_relation(i, r, violations, dropped) for i, r in enumerate(relations)]
    if "signals" in data:
        signals = data["signals"]
        if not isinstance(signals, list):
            violations.append("signals precisa ser uma lista")
        else:
            clean["signals"] = [_check_signal(i, s, violations, dropped) for i, s in enumerate(signals)]
    return clean, violations, dropped


# ---------------------------------------------------------------- redaction (references/redaction.md)

REDACTED = "[REDACTED]"
PRIVATE_KEY_HEADER = r"[A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----"  # PEM (RSA, EC, OPENSSH...) and PGP blocks
SECRET_PATTERNS = (  # (name, regex); the "url" one keeps scheme://user: and masks only the password
    ("private-key", rf"-----BEGIN {PRIVATE_KEY_HEADER}(?:.*?-----END {PRIVATE_KEY_HEADER}|.*\Z)"),
    # user may be empty (redis://:pw@host); the password runs up to the last @ before a space, so / and @
    # inside it are masked too (when in doubt, more is masked, never less)
    ("url", r"(?P<url>\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]*:)(?:[^\s@]*@)+"),
    # tokens glued to punctuation (_ghp_, =ghp_, token:ghp_) are masked too
    ("github-pat", r"github_pat_[A-Za-z0-9_]{20,}"),
    # GitHub: standalone (not inside a word: laughs_...) or, glued to text, the exact 36-character body
    ("github", r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{36}(?![A-Za-z0-9])"),
    ("slack", r"xox[abposr]-[A-Za-z0-9-]{10,}"),
    ("aws-access-key", r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])"),  # not ASIAPACIFIC...1
    ("jwt", r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
)
SECRET_RE = re.compile("|".join(f"(?:{regex})" for _, regex in SECRET_PATTERNS), re.DOTALL)
_EXTRA_CACHE = {}


def compile_extra_patterns(extra_patterns) -> list:
    """Compiled redaction.extra_patterns; an invalid one = AtlasError (code 2) naming its position, not its text."""
    key = tuple(p if isinstance(p, str) else p.pattern for p in extra_patterns or ())
    if key not in _EXTRA_CACHE:
        compiled = []
        for index, pattern in enumerate(extra_patterns or ()):
            compiled.append(compile_extra_pattern(index, pattern))
        _EXTRA_CACHE[key] = compiled
    return _EXTRA_CACHE[key]


def compile_extra_pattern(index: int, pattern):
    """One compiled entry of redaction.extra_patterns (position `index`); invalid = AtlasError (code 2)."""
    if hasattr(pattern, "subn"):
        return pattern
    if not isinstance(pattern, str) or not pattern:
        raise AtlasError(f"redaction.extra_patterns[{index}] precisa ser uma regex (texto não vazio)", 2)
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise AtlasError(f"redaction.extra_patterns[{index}] não é uma regex válida: {e}", 2) from e
    if regex.search("") is not None:  # would insert [REDACTED] between every character
        raise AtlasError(f"redaction.extra_patterns[{index}] casa com o texto vazio — "
                         "exija ao menos um caractere", 2)
    return regex


def _mask(match) -> str:
    prefix = match.group("url")
    return f"{prefix}{REDACTED}@" if prefix else REDACTED


def _redact_text(text: str, extras: list) -> tuple:
    text, count = SECRET_RE.subn(_mask, text)
    for pattern in extras:
        text, n = _sub_non_empty(pattern, text)
        count += n
    return text, count


def _sub_non_empty(pattern, text: str) -> tuple:
    """pattern.subn(REDACTED, text) that ignores zero-width matches (\\b, lookarounds): they never mask."""
    count = 0

    def mask(match):
        nonlocal count
        if not match.group(0):
            return ""
        count += 1
        return REDACTED

    return pattern.sub(mask, text), count


def _redact_keys(item: dict, extras: list) -> tuple:
    """({original key: masked key}, count) for the keys of a dict. Masked keys that collide in the same object
    are kept apart with "#2", "#3"... in the order of the original keys (deterministic, whatever the input
    order); a key equal to an existing one is avoided the same way."""
    masked, count = {}, 0
    for key in item:
        if isinstance(key, str):
            masked[key], n = _redact_text(key, extras)
            count += n
        else:
            masked[key] = key
    changed = sorted((k for k in item if masked[k] != k), key=str)
    taken = {k for k in item if masked[k] == k}
    for key in changed:
        base, candidate, n = masked[key], masked[key], 1
        while candidate in taken:
            n += 1
            candidate = f"{base}#{n}"
        masked[key] = candidate
        taken.add(candidate)
    return masked, count


def redact(value, extra_patterns=()) -> tuple:
    """(redacted, count): every piece of a string (also dict keys and values, and lists) that matches a secret
    pattern or an extra pattern becomes [REDACTED]; count = occurrences. Other scalars stay as they are."""
    extras = compile_extra_patterns(extra_patterns)

    def walk(item):
        if isinstance(item, str):
            return _redact_text(item, extras)
        if isinstance(item, dict):
            keys, total = _redact_keys(item, extras)
            result = {}
            for key, child in item.items():
                result[keys[key]], n = walk(child)
                total += n
            return result, total
        if isinstance(item, list):
            result, total = [], 0
            for child in item:
                masked, n = walk(child)
                result.append(masked)
                total += n
            return result, total
        return item, 0

    return walk(value)


# ---------------------------------------------------------------- snapshots and diff

def entity_key(entity) -> str:
    return f"{entity.get('kind')}:{entity.get('id')}"


def relation_key(relation) -> str:
    return f"{relation.get('from')} {relation.get('type')} {relation.get('to')}"


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def normalize(data) -> str:
    """Snapshot text (snapshots/<id>.json): entities sorted by kind:id, relations by from/type/to, signals by
    content, sorted keys, 2-space indentation, final newline. Same state = same text (idempotent)."""
    snapshot = dict(data)
    snapshot["entities"] = sorted(data.get("entities", []), key=lambda e: (entity_key(e), _canonical(e)))
    snapshot["relations"] = sorted(data.get("relations", []),
                                   key=lambda r: (str(r.get("from")), str(r.get("type")), str(r.get("to")),
                                                  _canonical(r)))
    if "signals" in data:
        snapshot["signals"] = sorted(data["signals"], key=_canonical)
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def diff_snapshots(old, new) -> dict:
    """Entities added/removed/changed (by kind:id) and relations added/removed ("<from> <type> <to>") from old to
    new; old None = first scan (everything added)."""
    old = old or {}
    old_entities = {entity_key(e): e for e in old.get("entities", [])}
    new_entities = {entity_key(e): e for e in new.get("entities", [])}
    old_relations = {relation_key(r) for r in old.get("relations", [])}
    new_relations = {relation_key(r) for r in new.get("relations", [])}
    return {
        "entities": {
            "added": sorted(set(new_entities) - set(old_entities)),
            "removed": sorted(set(old_entities) - set(new_entities)),
            "changed": sorted(k for k in set(new_entities) & set(old_entities) if new_entities[k] != old_entities[k]),
        },
        "relations": {
            "added": sorted(new_relations - old_relations),
            "removed": sorted(old_relations - new_relations),
        },
    }


def has_changes(diff: dict) -> bool:
    return any(diff["entities"].values()) or any(diff["relations"].values())


# ---------------------------------------------------------------- collectors

COLLECTOR_ID_RE = re.compile(r"^[a-z0-9-]+$")
COLLECTOR_TIMEOUT = 300
ABSOLUTE_MESSAGE = "command não pode ter caminho absoluto — use {skill} ou {atlas}"
ABSOLUTE_ARG_RE = re.compile(r"(^|=|^-[A-Za-z0-9])(/|~|[A-Za-z]:[\\/]|\\\\)")  # also --out=/x, -o/x
STDERR_LINES = 20
STDERR_LINE_MAX = 500
BOOLEANS = {"true": True, "false": False}


class CollectorError(Exception):
    """A collector that could not run or failed: `reason` and the last lines of its stderr (not yet redacted)."""

    def __init__(self, reason, stderr=""):
        super().__init__(reason)
        self.reason = reason
        self.stderr = stderr


def _timeout_of(name, value) -> int:
    if value in (None, ""):
        return COLLECTOR_TIMEOUT
    text = str(value).strip()
    if isinstance(value, bool) or not re.match(r"^\d+$", text) or int(text) < 1:
        raise AtlasError(f"coletor {name}: timeout precisa ser um número inteiro de segundos (≥ 1): {value}", 2)
    return int(text)


def _enabled_of(name, value) -> bool:
    if value in (None, ""):
        return True
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text not in BOOLEANS:
        raise AtlasError(f"coletor {name}: enabled precisa ser true ou false: {value}", 2)
    return BOOLEANS[text]


def validate_collectors(collectors) -> list:
    """The `collectors` key of atlas-config.yml, validated, with defaults (timeout 300, enabled true). Scalars may
    come as text from parse_yaml. Invalid = AtlasError (code 2)."""
    if collectors in (None, ""):
        return []
    if not isinstance(collectors, list):
        raise AtlasError("collectors precisa ser uma lista (references/collector-contract.md)", 2)
    result, ids = [], set()
    for index, item in enumerate(collectors):
        if not isinstance(item, dict):
            raise AtlasError(f"collectors[{index}] precisa ser um mapa com id, category e command", 2)
        cid = item.get("id")
        if not isinstance(cid, str) or not COLLECTOR_ID_RE.match(cid):
            raise AtlasError(f"collectors[{index}]: id inválido: {cid} — use letras minúsculas, números e '-'", 2)
        if cid in ids:
            raise AtlasError(f"collectors: id repetido: {cid}", 2)
        ids.add(cid)
        category = item.get("category")
        if category not in CATEGORIES:
            raise AtlasError(f"coletor {cid}: category desconhecida: {category} — use um de: "
                             f"{' | '.join(CATEGORIES)}", 2)
        command = item.get("command")
        if (not isinstance(command, list) or not command
                or any(not isinstance(arg, str) or not arg for arg in command)):
            raise AtlasError(f"coletor {cid}: command precisa ser uma lista não vazia [executável, argumentos...] "
                             "(sem shell)", 2)
        if any(ABSOLUTE_ARG_RE.search(arg) for arg in command):
            raise AtlasError(f"coletor {cid}: {ABSOLUTE_MESSAGE}", 2)
        result.append(dict(item, command=list(command), timeout=_timeout_of(cid, item.get("timeout")),
                           enabled=_enabled_of(cid, item.get("enabled"))))
    return result


def resolve_command(command, skill, atlas) -> list:
    """command with {skill} (the skill folder) and {atlas} (the atlas folder) replaced in each argument."""
    return [str(arg).replace("{skill}", str(skill)).replace("{atlas}", str(atlas)) for arg in command]


def _kill(proc) -> None:
    """Kills the collector and what it started (its process group on POSIX), then reaps it."""
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.communicate(timeout=5)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


def run_collector(argv, timeout=COLLECTOR_TIMEOUT) -> tuple:
    """The only function of atlas.py that runs an external process (ADR-0010): argv as a list, never a shell, in a
    temporary folder and its own process group, with a timeout (the whole group is killed when it expires) and the
    output captured. Returns (stdout, stderr); exit ≠ 0, timeout or missing executable = CollectorError."""
    with tempfile.TemporaryDirectory(prefix="atlas-collector-") as tmp:
        try:
            proc = subprocess.Popen(argv, cwd=tmp, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                                    start_new_session=os.name != "nt")
        except FileNotFoundError as e:
            raise CollectorError(f"executável não encontrado: {argv[0]}") from e
        except OSError as e:
            raise CollectorError(f"não consegui executar {argv[0]}: {e.strerror or e}") from e
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as e:
            _kill(proc)
            raise CollectorError(f"tempo esgotado ({timeout} s); processo encerrado") from e
        except BaseException:
            _kill(proc)
            raise
    if proc.returncode != 0:
        raise CollectorError(f"saiu com {proc.returncode}", stderr or "")
    return stdout or "", stderr or ""


def stderr_tail(text: str, extras: list) -> list:
    """Last STDERR_LINES lines of a collector's stderr, each cut to STDERR_LINE_MAX characters. The whole text is
    redacted first, so a multi-line key block or a token at the cut never leaks a piece."""
    masked, _ = _redact_text(text or "", extras)
    return [line[:STDERR_LINE_MAX] for line in masked.rstrip().splitlines()[-STDERR_LINES:]]


# ---------------------------------------------------------------- scan

SNAPSHOTS_DIR = "snapshots"
SCAN_STATE = "_scan.json"


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_json_file(path: Path):
    """Parsed JSON of a file, or None when it does not exist or is not valid JSON (unreadable = AtlasError)."""
    if not path.is_file():
        return None
    try:
        return json.loads(read_text(path))
    except ValueError:
        return None


def _without_collected_at(snapshot) -> dict:
    return {k: v for k, v in (snapshot or {}).items() if k != "collected_at"}


def scan_one(collector: dict, atlas: Path, extras: list, today: str) -> dict:
    """Runs, validates, redacts, normalizes and writes one collector; returns its report (never raises for a
    failure of the collector: the previous snapshot is kept)."""
    cid = collector["id"]
    report = {"id": cid, "status": "failed", "reason": "", "violations": [], "stderr": [], "dropped": [],
              "redacted": 0, "diff": None}
    try:
        argv = resolve_command(collector["command"], SKILL_DIR, atlas)
        stdout, _ = run_collector(argv, collector["timeout"])
    except CollectorError as e:
        report["reason"] = _redact_text(e.reason, extras)[0]
        report["stderr"] = stderr_tail(e.stderr, extras)
        return report
    try:
        data = json.loads(stdout)
    except ValueError as e:
        report["reason"] = f"JSON inválido na saída: {e.msg} (linha {e.lineno}, coluna {e.colno})"
        return report
    clean, violations, dropped = validate_collector_output(data)
    if violations:
        report["reason"] = f"saída fora do contrato {CONTRACT} ({len(violations)} violação(ões))"
        report["violations"] = [_redact_text(v, extras)[0] for v in violations]
        return report
    snapshot, count = redact(clean, extras)
    text = normalize(snapshot)
    snapshot = json.loads(text)
    path = atlas / SNAPSHOTS_DIR / f"{cid}.json"
    previous = read_json_file(path)
    diff = diff_snapshots(previous, snapshot)
    try:
        # same state (collected_at aside) = the file stays as it is: no noise in the atlas history
        if previous is None or _without_collected_at(previous) != _without_collected_at(snapshot):
            write_atomic(path, text)
    except OSError as e:
        report["reason"] = f"não consegui gravar {path.name}: {e.strerror or e}"
        return report
    report.update(status="ok", dropped=[_redact_text(d, extras)[0] for d in dropped], redacted=count, diff=diff,
                  seen_at=today, entities=len(snapshot["entities"]), relations=len(snapshot["relations"]))
    return report


def scan_line(report: dict) -> str:
    if report["status"] != "ok":
        return f"FALHA {report['id']} — {report['reason']}"
    diff = report["diff"]
    if not has_changes(diff):
        return f"OK {report['id']} — sem mudanças"
    e, r = diff["entities"], diff["relations"]
    return (f"OK {report['id']} — +{len(e['added'])} entidades, -{len(e['removed'])}, ~{len(e['changed'])}; "
            f"+{len(r['added'])} relações, -{len(r['removed'])}")


def print_scan(reports: list) -> None:
    for report in reports:
        print(scan_line(report))
        for violation in report["violations"]:
            print(f"  {violation}")
        if report["stderr"]:
            print(f"  stderr (últimas {STDERR_LINES} linhas):")
            for line in report["stderr"]:
                print(f"    {line}")
        for item in report["dropped"]:
            print(f"  {item}")
        if report["redacted"]:
            print(f"  {report['redacted']} valor(es) mascarado(s)")
    failed = sum(1 for r in reports if r["status"] != "ok")
    print(f"{len(reports)} coletor(es), {failed} com falha")


def scan_config():
    """(atlas folder, shared configuration) of this machine for scan; problems = AtlasError."""
    path, local = read_local()
    atlas = local.get("atlas")
    if not isinstance(atlas, str) or not atlas:
        raise AtlasError(f"atlas não definido em {path} — rode init (ou init --join)", 3)
    shared_path = Path(atlas) / SHARED_FILE
    if not shared_path.is_file():
        raise AtlasError(f"atlas sem atlas-config.yml — rode init: {shared_path}", 2)
    return Path(atlas), read_yaml(shared_path)


def selected_collectors(collectors: list, only) -> list:
    if not only:
        return [c for c in collectors if c["enabled"]]
    wanted = [name.strip() for name in str(only).split(",") if name.strip()]
    by_id = {c["id"]: c for c in collectors}
    unknown = [name for name in wanted if name not in by_id]
    if unknown:
        raise AtlasError(f"coletor não declarado em atlas-config.yml: {', '.join(unknown)}", 2)
    disabled = [name for name in wanted if not by_id[name]["enabled"]]
    if disabled:
        raise AtlasError(f"coletor com enabled: false: {', '.join(disabled)} — habilite no atlas-config.yml", 2)
    return [by_id[name] for name in dict.fromkeys(wanted)]


def cmd_scan(only=None, as_json=False):
    """scan [--only id,...] [--json]: each enabled collector (or the --only ones) is run, validated, redacted,
    normalized and written to snapshots/<id>.json; snapshots/_scan.json keeps seen_at (date of the last good scan),
    status and counts. A failing collector keeps its previous snapshot and seen_at and does not stop the others.
    Exit 0 without failure, 1 with a failure, 2 with an invalid configuration or an unknown --only id."""
    atlas, shared = scan_config()
    collectors = validate_collectors(shared.get("collectors"))
    redaction = shared.get("redaction")
    extra = redaction.get("extra_patterns") if isinstance(redaction, dict) else None
    if extra not in (None, "") and not isinstance(extra, list):
        raise AtlasError("redaction.extra_patterns precisa ser uma lista de regex", 2)
    extras = compile_extra_patterns(extra or [])
    selected = selected_collectors(collectors, only)
    if not selected:  # nothing runs, nothing is written (not even snapshots/)
        if as_json:
            print(json.dumps({"version": ATLAS_VERSION, "ok": True, "collectors": []}, ensure_ascii=False, indent=2))
        else:
            print("nenhum coletor habilitado em atlas-config.yml (references/collector-contract.md)")
        return 0
    snapshots = atlas / SNAPSHOTS_DIR
    snapshots.mkdir(parents=True, exist_ok=True)
    state_path = snapshots / SCAN_STATE
    state = read_json_file(state_path)
    state = state if isinstance(state, dict) else {}
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    reports = []
    for collector in selected:
        report = scan_one(collector, atlas, extras, today)
        previous = state.get(collector["id"]) if isinstance(state.get(collector["id"]), dict) else {}
        if report["status"] == "ok":
            state[collector["id"]] = {"seen_at": today, "status": "ok", "entities": report["entities"],
                                      "relations": report["relations"]}
        else:  # seen_at does not move: the facts of this collector are as old as its last good scan
            state[collector["id"]] = {"seen_at": previous.get("seen_at"), "status": "failed",
                                      "entities": previous.get("entities", 0),
                                      "relations": previous.get("relations", 0)}
        reports.append(report)
    write_atomic(state_path, json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    failed = any(r["status"] != "ok" for r in reports)
    try:  # SPEC-0036: graph.json and the pages, also with a failed collector
        build = build_atlas(atlas, shared)
    except (AtlasError, OSError) as e:  # scan --json stays one object: the error goes into "build"
        build = {"ok": False, "error": str(e)}
    try:  # SPEC-0037: proposals (inferred) and fresh evidence; never a decision
        curation = curate_propose(atlas, shared)
    except (AtlasError, OSError) as e:
        curation = {"ok": False, "error": str(e)}
    failed = failed or not build["ok"] or not curation["ok"]
    if as_json:
        print(json.dumps({"version": ATLAS_VERSION, "ok": not failed, "collectors": reports, "build": build,
                          "curation": curation}, ensure_ascii=False, indent=2))
    else:
        print_scan(reports)
        if build["ok"]:
            print_build(build)
        else:
            print(f"erro no build: {build['error']}", file=sys.stderr)
        if curation["ok"]:
            print(curation_line(curation))
        else:
            print(f"erro na curadoria: {curation['error']}", file=sys.stderr)
    return 1 if failed else 0


# ---------------------------------------------------------------- build (graph and pages)

GRAPH_FILE = "graph.json"
GRAPH_VERSION = 1
SERVICE_PAGE, PLATFORM_PAGE, ATLAS_PAGE = "service.md", "platform.md", "ATLAS.md"
SERVICES_DIR, PLATFORM_DIR = "services", "platform"
# category of the platform/<category>.md page of each kind (services have their own pages)
KIND_CATEGORY = {"repository": "code", "team": "code", "pipeline": "ci", "deployment": "delivery",
                 "environment": "delivery", "cluster": "runtime", "datastore": "data", "bucket": "data",
                 "queue": "messaging", "topic": "messaging", "secret-ref": "secrets"}
RESOURCE_KINDS = ("datastore", "queue", "topic", "bucket")  # config_refs host -> depends_on (rule 2)
DEPENDENCY_TYPES = ("depends_on", "reads", "writes", "publishes", "consumes")
REGION_SUB_RE = re.compile(r"(<!-- atlas:begin ([\w-]+) -->)(.*?)(<!-- atlas:end \2 -->)", re.DOTALL)
NOT_SEEN_RE = re.compile(r"^_Não visto desde (\d{4}-\d{2}-\d{2})\._$")
SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")
SLUG_MAX = 80  # longer slugs are cut and get "-<hash of the id>" (file names stay well under 100 characters)
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
# the service a page belongs to: "- Chave: `<key>`" in its summary region, or the template line "Serviço `<key>`"
OWNER_SUMMARY_RE = re.compile(r"^- Chave: `([^`]+)`", re.MULTILINE)
OWNER_INTRO_RE = re.compile(r"^Serviço `(service:[^`]+)`", re.MULTILINE)
NONE_TEXT = "_(nenhum)_"


def _source_order(order, extra) -> list:
    """Collector ids in the order of atlas-config.yml, then any other id (sorted): the merge order."""
    known = list(dict.fromkeys(order))
    return known + sorted(set(extra) - set(known))


def _day_of(collected_at) -> str:
    text = str(collected_at or "")
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else ""


def merge_snapshots(snapshots: dict, order: list, scan_state: dict) -> dict:
    """One graph {"nodes", "edges"} from the snapshots of every collector ({id: snapshot}). Same kind:id = one node
    with the attrs combined and every source; the same attr with different values = the first collector of `order`
    wins and the conflict is recorded with the value of each collector. Same (from, type, to) = one edge with every
    source. seen_at of a node = the most recent seen_at (snapshots/_scan.json) of its collectors."""
    scan_state = scan_state if isinstance(scan_state, dict) else {}
    ids = _source_order(order, snapshots)
    rank = {cid: index for index, cid in enumerate(ids)}
    nodes, edges = {}, {}
    for cid in ids:
        snapshot = snapshots.get(cid)
        if not isinstance(snapshot, dict):
            continue
        entry = scan_state.get(cid) if isinstance(scan_state.get(cid), dict) else {}
        seen = str(entry.get("seen_at") or "") or _day_of(snapshot.get("collected_at"))
        for entity in snapshot.get("entities", []):
            key = entity_key(entity)
            attrs = entity.get("attrs") if isinstance(entity.get("attrs"), dict) else {}
            node = nodes.get(key)
            if node is None:
                node = nodes[key] = {"key": key, "kind": entity.get("kind"), "name": str(entity.get("name") or
                                                                                      entity.get("id")),
                                     "attrs": {}, "sources": [], "seen_at": "", "values": {}}
            if cid not in node["sources"]:
                node["sources"].append(cid)
            node["seen_at"] = max(node["seen_at"], seen)
            for name, value in attrs.items():
                node["values"].setdefault(name, {})[cid] = value
        for relation in snapshot.get("relations", []):
            key = (relation.get("from"), relation.get("type"), relation.get("to"))
            edge = edges.get(key)
            if edge is None:
                edge = edges[key] = {"from": key[0], "to": key[2], "type": key[1], "sources": [],
                                     "inferred": relation.get("inferred") is True}
            if cid not in edge["sources"]:
                edge["sources"].append(cid)
    result = []
    for key in sorted(nodes):
        node = nodes[key]
        values = node.pop("values")
        conflicts = []
        for name in sorted(values):
            by_source = dict(sorted(values[name].items(), key=lambda item: rank[item[0]]))
            first = next(iter(by_source.values()))
            node["attrs"][name] = first
            if any(_canonical(value) != _canonical(first) for value in by_source.values()):
                conflicts.append({"attr": name, "values": by_source})
        node["attrs"] = dict(sorted(node["attrs"].items()))
        node["conflicts"] = conflicts
        result.append(node)
    return {"nodes": result, "edges": [edges[key] for key in sorted(edges, key=lambda k: tuple(map(str, k)))]}


def _union(*lists) -> list:
    return list(dict.fromkeys(item for items in lists for item in items))


def _host_of(ref) -> str:
    """Host of a config_refs item (KEY=host): the text after the first '='; '' without it."""
    return ref.split("=", 1)[1] if isinstance(ref, str) and "=" in ref else ""


def infer_relations(graph: dict) -> dict:
    """New graph with the declared edges and the inferred ones (`inferred: true`); the input does not change.
    (1) deployment `sourced_from` repository + deployment `deploys` service -> service `sourced_from` repository;
    (2) a config_refs item (KEY=host) of a deployment whose host equals the `host` attr or the name of a datastore,
        queue, topic or bucket -> service `depends_on` that entity, with `evidence` = the item;
    (3) a host equal to the name of another service -> `depends_on` between the services.
    Only equality: an unknown or similar host creates no edge and no node. An inferred edge equal to a declared
    one (same from, type, to) is not added; the same inferred edge from several items keeps the smallest evidence."""
    nodes = {node["key"]: node for node in graph["nodes"]}
    edges = [dict(edge, sources=list(edge["sources"])) for edge in graph["edges"]]
    declared = {(e["from"], e["type"], e["to"]) for e in edges}
    out = {}
    for edge in edges:
        out.setdefault((edge["from"], edge["type"]), []).append(edge)
    targets = {}  # host or name -> keys of the entities it names (rules 2 and 3)
    for node in graph["nodes"]:
        if node["kind"] in RESOURCE_KINDS:
            names = {node["name"], node["attrs"].get("host")}
        elif node["kind"] == "service":
            names = {node["name"]}
        else:
            continue
        for name in names:
            if isinstance(name, str) and name:
                targets.setdefault(name, []).append(node["key"])
    inferred = {}

    def add(src, rtype, dst, sources, evidence):
        key = (src, rtype, dst)
        if key in declared or src == dst:
            return
        edge = inferred.get(key)
        if edge is None:
            inferred[key] = {"from": src, "to": dst, "type": rtype, "sources": list(sources), "inferred": True,
                             "evidence": evidence}
            return
        edge["sources"] = _union(edge["sources"], sources)
        edge["evidence"] = min(edge["evidence"], evidence)

    for key in sorted(k for k, n in nodes.items() if n["kind"] == "deployment"):
        deployment = nodes[key]
        deploys = [e for e in out.get((key, "deploys"), []) if e["to"].startswith("service:")]
        if not deploys:
            continue
        for deploy in deploys:
            for source in out.get((key, "sourced_from"), []):
                add(deploy["to"], "sourced_from", source["to"], _union(deploy["sources"], source["sources"]), key)
        refs = deployment["attrs"].get("config_refs")
        for ref in sorted(r for r in (refs if isinstance(refs, list) else []) if isinstance(r, str)):
            for target in targets.get(_host_of(ref), []):
                for deploy in deploys:
                    add(deploy["to"], "depends_on", target,
                        _union(deployment["sources"], nodes[target]["sources"]), ref)
    return {**graph, "nodes": [dict(node) for node in graph["nodes"]],
            "edges": edges + [inferred[key] for key in sorted(inferred)]}


def _graph_node(node) -> dict:
    return {"key": node["key"], "kind": node["kind"], "name": node["name"], "attrs": node["attrs"],
            "sources": node["sources"], "seen_at": node["seen_at"], "conflicts": node["conflicts"]}


def _graph_edge(edge) -> dict:
    result = {"from": edge["from"], "to": edge["to"], "type": edge["type"], "sources": edge["sources"],
              "inferred": bool(edge.get("inferred"))}
    if "evidence" in edge:
        result["evidence"] = edge["evidence"]
    return result


def render_graph(graph: dict, organization: str, built_at: str) -> str:
    """Text of graph.json (contract v1, references/graph.md): nodes sorted by key, edges by (from, type, to),
    sorted keys, 2-space indentation, final newline. Same graph = same text."""
    data = {"version": GRAPH_VERSION, "organization": organization, "built_at": built_at,
            "nodes": [_graph_node(n) for n in sorted(graph["nodes"], key=lambda n: n["key"])],
            "edges": [_graph_edge(e) for e in sorted(graph["edges"], key=lambda e: (e["from"], e["type"], e["to"]))]}
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


# ---- pages

def slug(entity_id) -> str:
    """File name (without .md) of an entity's page: only letters, digits, '.', '_' and '-'; more than SLUG_MAX
    characters = cut and suffixed with a short hash of the id; a Windows reserved name (con, prn, aux, nul, com1-9,
    lpt1-9, with or without extension) gets '_' after its first part."""
    text = SLUG_RE.sub("-", str(entity_id)).strip("-.") or "-"
    if len(text) > SLUG_MAX:
        digest = hashlib.sha1(str(entity_id).encode("utf-8")).hexdigest()[:10]
        text = f"{text[:SLUG_MAX].rstrip('-.')}-{digest}"
    first, dot, rest = text.partition(".")
    if first.casefold() in WINDOWS_RESERVED:
        text = f"{first}_{dot}{rest}"
    return text


def page_owner(text: str):
    """Key of the service a page belongs to (its summary "- Chave:" line, else the template intro line) or None."""
    found = OWNER_SUMMARY_RE.search(page_regions(text).get("summary", "")) or OWNER_INTRO_RE.search(text)
    return found.group(1) if found else None


def service_page_names(keys, existing: dict) -> dict:
    """{service key: file name without .md}. An existing page keeps belonging to its service (page_owner); a new
    service gets a slug that collides (ignoring case) neither with another name nor with any existing file, with
    -2, -3... when needed. A file of a service that is gone is never given to another one. Deterministic."""
    files = sorted(p[len(SERVICES_DIR) + 1:-3] for p in existing
                   if p.startswith(SERVICES_DIR + "/") and p.endswith(".md"))
    keys = sorted(keys)
    wanted, result = set(keys), {}
    taken = {name.casefold() for name in files}
    for name in files:
        owner = page_owner(existing[f"{SERVICES_DIR}/{name}.md"])
        if owner in wanted and owner not in result:
            result[owner] = name
    for key in keys:
        if key in result:
            continue
        base = slug(key.split(":", 1)[1])
        candidate, n = base, 1
        while candidate.casefold() in taken:
            n += 1
            candidate = f"{base}-{n}"
        taken.add(candidate.casefold())
        result[key] = candidate
    return result


def _fmt_value(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ", ".join(_fmt_value(v) for v in value) or "—"
    return "—" if value is None else json.dumps(value, ensure_ascii=False)


def _region(lines) -> str:
    return "\n" + "\n".join(lines or [NONE_TEXT]) + "\n"


def fill_regions(text: str, bodies: dict) -> str:
    """text with the content of each region named in `bodies` replaced; everything else stays as it is."""
    return REGION_SUB_RE.sub(lambda m: m.group(1) + bodies[m.group(2)] + m.group(4) if m.group(2) in bodies
                             else m.group(0), text)


def page_regions(text: str) -> dict:
    return {m.group(2): m.group(3) for m in REGION_SUB_RE.finditer(text)}


class _Index:
    """Lookups over a graph for the pages: nodes by key, edges by (from, type) and by (to, type)."""

    def __init__(self, graph, existing=None):
        self.nodes = {node["key"]: node for node in graph["nodes"]}
        self.out, self.into = {}, {}
        for edge in sorted(graph["edges"], key=lambda e: (e["from"], e["type"], e["to"])):
            self.out.setdefault((edge["from"], edge["type"]), []).append(edge)
            self.into.setdefault((edge["to"], edge["type"]), []).append(edge)
        services = [key for key, node in self.nodes.items() if node["kind"] == "service"]
        self.slugs = service_page_names(services, existing or {})

    def targets(self, key, rtype, kind=None) -> list:
        return [e["to"] for e in self.out.get((key, rtype), []) if kind is None or e["to"].startswith(kind + ":")]

    def sources(self, key, rtype, kind=None) -> list:
        return [e["from"] for e in self.into.get((key, rtype), [])
                if kind is None or e["from"].startswith(kind + ":")]

    def name(self, key) -> str:
        node = self.nodes.get(key)
        return node["name"] if node else key.split(":", 1)[-1]

    def label(self, key, here="services") -> str:
        """Markdown for an entity: a link to its page (service or platform/<category>.md) and its key."""
        kind = key.split(":", 1)[0]
        prefix = "" if here == "services" else "../services/"
        if key in self.slugs:
            return f"[{self.name(key)}]({prefix}{self.slugs[key]}.md)"
        category = KIND_CATEGORY.get(kind)
        if key in self.nodes and category:
            target = f"{category}.md" if here == "platform" else f"../{PLATFORM_DIR}/{category}.md"
            return f"[{self.name(key)}]({target}) (`{key}`)"
        return f"`{key}`"


def _edge_note(edge) -> str:
    notes = [] if edge["type"] == "depends_on" else [edge["type"]]
    if edge.get("inferred"):
        notes.append(f"inferida de `{edge['evidence']}`" if edge.get("evidence") else "inferida")
    return f" — {', '.join(notes)}" if notes else ""


def _summary_lines(node) -> list:
    lines = [f"- Chave: `{node['key']}`", f"- Visto em: {node['seen_at'] or '—'}",
             f"- Fontes: {', '.join(node['sources'])}"]
    lines += [f"- {name}: {_fmt_value(value)}" for name, value in node["attrs"].items()]
    for conflict in node["conflicts"]:
        values = "; ".join(f"{cid} = {_fmt_value(v)}" for cid, v in conflict["values"].items())
        lines.append(f"- Conflito em `{conflict['attr']}`: {values}")
    return lines


def _service_regions(key, index, scans) -> dict:
    node = index.nodes[key]
    repositories = _union(index.targets(key, "sourced_from", "repository"))
    deployments = index.sources(key, "deploys", "deployment")
    by_env = {}
    for deployment in deployments:
        envs = index.targets(deployment, "runs_in", "environment") or [""]
        for env in envs:
            by_env.setdefault(env, []).append(deployment)
    deployment_lines = []
    for env in sorted(by_env, key=lambda e: (e == "", index.name(e) if e else "")):
        title = index.name(env) if env else "sem ambiente"
        for deployment in by_env[env]:
            attrs = index.nodes[deployment]["attrs"] if deployment in index.nodes else {}
            status = ", ".join(str(attrs[k]) for k in ("sync_status", "health_status") if attrs.get(k))
            clusters = ", ".join(f"`{index.name(c)}`" for c in index.targets(deployment, "runs_in", "cluster"))
            details = "; ".join(part for part in (status, f"cluster {clusters}" if clusters else "") if part)
            deployment_lines.append(f"- **{title}**: `{index.name(deployment)}`" + (f" ({details})" if details else ""))
    depends = [e for rtype in DEPENDENCY_TYPES for e in index.out.get((key, rtype), [])]
    used = [e for rtype in DEPENDENCY_TYPES for e in index.into.get((key, rtype), [])]
    owners = _union(*(index.sources(target, "owns", "team") for target in [key] + repositories))
    pipelines = _union(*(index.sources(target, "builds", "pipeline") for target in [key] + repositories))
    sources = []
    for cid in node["sources"]:
        seen = (scans.get(cid) or {}).get("seen_at") if isinstance(scans.get(cid), dict) else None
        sources.append(f"- {cid}" + (f" (visto em {seen})" if seen else ""))
    return {
        "summary": _region(_summary_lines(node)),
        "repository": _region([f"- {index.label(r)}" for r in repositories]),
        "deployments": _region(deployment_lines),
        "depends-on": _region([f"- {index.label(e['to'])}{_edge_note(e)}"
                               for e in sorted(depends, key=lambda e: (e["to"], e["type"]))]),
        "used-by": _region([f"- {index.label(e['from'])}{_edge_note(e)}"
                            for e in sorted(used, key=lambda e: (e["from"], e["type"]))]),
        "owners": _region([f"- {index.name(t)} (`{t.split(':', 1)[1]}`)" for t in owners]),
        "pipelines": _region([f"- {index.name(p)} (`{p.split(':', 1)[1]}`)" for p in pipelines]),
        "sources": _region(sources),
    }


def _platform_regions(category, index) -> dict:
    lines = []
    for kind in [k for k in KINDS if KIND_CATEGORY.get(k) == category]:
        keys = sorted(k for k, n in index.nodes.items() if n["kind"] == kind)
        if not keys:
            continue
        lines += ([""] if lines else []) + [f"### {kind}", ""]
        for key in keys:
            node = index.nodes[key]
            attrs = "; ".join(f"{name}: {_fmt_value(value)}" for name, value in node["attrs"].items())
            used = _union(*(index.sources(key, rtype, "service") for rtype in DEPENDENCY_TYPES))
            parts = [part for part in (attrs, f"usado por {', '.join(index.label(s, 'platform') for s in used)}"
                                       if used else "", f"visto em {node['seen_at']}" if node["seen_at"] else "")
                     if part]
            lines.append(f"- **{node['name']}** (`{key}`)" + (f" — {' — '.join(parts)}" if parts else ""))
    return {"entities": _region(lines)}


def _atlas_regions(graph, index, scans, categories) -> dict:
    counts = {}
    for node in graph["nodes"]:
        counts[node["kind"]] = counts.get(node["kind"], 0) + 1
    inferred = sum(1 for e in graph["edges"] if e.get("inferred"))
    conflicts = sum(len(n["conflicts"]) for n in graph["nodes"])
    summary = [(f"- {len(graph['nodes'])} entidades, {len(graph['edges'])} relações ({inferred} inferidas), "
                f"{conflicts} conflitos")]
    summary += [f"- {kind}: {counts[kind]}" for kind in KINDS if kind in counts]
    if categories:
        summary.append("- Plataforma: " + ", ".join(f"[{c}]({PLATFORM_DIR}/{c}.md)" for c in categories))
    services = []
    for key in sorted(index.slugs, key=lambda k: (index.name(k), k)):
        repositories = ", ".join("`" + r.split(":", 1)[1] + "`" for r in index.targets(key, "sourced_from",
                                                                                     "repository"))
        extra = f" — repositório {repositories}" if repositories else ""
        services.append(f"- [{index.name(key)}]({SERVICES_DIR}/{index.slugs[key]}.md){extra}")
    scan_lines = []
    for cid in sorted(scans):
        entry = scans[cid] if isinstance(scans[cid], dict) else {}
        status = entry.get("status") or "?"
        counts_text = (f", {entry['entities']} entidades, {entry['relations']} relações"
                       if "entities" in entry and "relations" in entry else "")
        scan_lines.append(f"- {cid}: {entry.get('seen_at') or 'nunca'} ({status}{counts_text})")
    scans_body = _region(scan_lines)
    # "snapshots" = name of the scans region in ATLAS.md of atlases created before 2026.11.1
    return {"summary": _region(summary), "services": _region(services), "scans": scans_body, "snapshots": scans_body}


def _template(name: str, organization: str, **values) -> str:
    text = (PAGES_DIR / name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text.replace("{organization}", organization)


def _scans_from_nodes(graph) -> dict:
    scans = {}
    for node in graph["nodes"]:
        for cid in node["sources"]:
            entry = scans.setdefault(cid, {"seen_at": ""})
            entry["seen_at"] = max(entry["seen_at"], node["seen_at"])
    return scans


def render_pages(graph: dict, existing: dict, organization: str, previous=None, scans=None) -> dict:
    """{path relative to the atlas: text} of ATLAS.md, services/<id>.md and platform/<category>.md. `existing` =
    {path: current text} of the pages that already exist (only their regions change; a new page comes from
    assets/pages/); `previous` = the previous graph (graph.json on disk), for the date of a service that is gone;
    `scans` = snapshots/_scan.json (seen_at per collector; without it, derived from the nodes). A page of a service
    that is gone stays: its summary becomes "_Não visto desde AAAA-MM-DD._" and its other regions are emptied."""
    existing = existing or {}
    scans = scans if isinstance(scans, dict) else _scans_from_nodes(graph)
    index = _Index(graph, existing)
    pages = {}
    for key, name in index.slugs.items():
        path = f"{SERVICES_DIR}/{name}.md"
        node = index.nodes[key]
        eid = key.split(":", 1)[1]
        title = eid if node["name"] == eid else f"{node['name']} ({eid})"
        text = existing.get(path) or _template(SERVICE_PAGE, organization, title=title, key=key)
        pages[path] = fill_regions(text, _service_regions(key, index, scans))
    previous_seen = {}
    if isinstance(previous, dict) and isinstance(previous.get("nodes"), list):
        previous_seen = {n["key"]: str(n.get("seen_at") or "") for n in previous["nodes"]
                         if isinstance(n, dict) and n.get("kind") == "service" and isinstance(n.get("key"), str)}
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    for path in sorted(p for p in existing if p.startswith(SERVICES_DIR + "/") and p not in pages):
        text = existing[path]
        current = NOT_SEEN_RE.match(page_regions(text).get("summary", "").strip())
        day = current.group(1) if current else previous_seen.get(page_owner(text)) or today
        bodies = {name: "\n" for name in page_regions(text)}
        bodies["summary"] = f"\n_Não visto desde {day}._\n"
        pages[path] = fill_regions(text, bodies)
    categories = sorted({KIND_CATEGORY[n["kind"]] for n in graph["nodes"] if n["kind"] in KIND_CATEGORY})
    for path in sorted({f"{PLATFORM_DIR}/{c}.md" for c in categories}
                       | {p for p in existing if p.startswith(PLATFORM_DIR + "/")}):
        category = path[len(PLATFORM_DIR) + 1:-3]
        text = existing.get(path) or _template(PLATFORM_PAGE, organization, category=category)
        pages[path] = fill_regions(text, _platform_regions(category, index))
    text = existing.get(ATLAS_PAGE) or _template(ATLAS_PAGE, organization)
    pages[ATLAS_PAGE] = fill_regions(text, _atlas_regions(graph, index, scans, categories))
    return pages


# ---- build command

def read_snapshots(atlas: Path, ids) -> tuple:
    """({id: snapshot}, warnings) of snapshots/<id>.json for the declared collectors; a missing file is skipped (the
    collector never ran) and an unreadable one is a warning (the build goes on with the others)."""
    snapshots, warnings = {}, []
    for cid in ids:
        path = atlas / SNAPSHOTS_DIR / f"{cid}.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            data = None
        problems = validate_collector_output(data)[1] if isinstance(data, dict) else ["não é um objeto JSON"]
        if problems:
            warnings.append(f"aviso: {SNAPSHOTS_DIR}/{cid}.json ilegível ou fora do contrato — ignorado no build")
            continue
        snapshots[cid] = data
    return snapshots, warnings


def _existing_pages(atlas: Path) -> dict:
    pages = {}
    if (atlas / ATLAS_PAGE).is_file():
        pages[ATLAS_PAGE] = read_text(atlas / ATLAS_PAGE)
    for folder in (SERVICES_DIR, PLATFORM_DIR):
        if (atlas / folder).is_dir():
            for path in sorted((atlas / folder).glob("*.md")):
                pages[f"{folder}/{path.name}"] = read_text(path)
    return pages


def _without_built_at(text) -> str:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return ""
    return _canonical({k: v for k, v in data.items() if k != "built_at"}) if isinstance(data, dict) else ""


def build_atlas(atlas: Path, shared: dict) -> dict:
    """Merges the snapshots, infers the relations and writes graph.json and the pages (only what changed; the
    graph keeps its built_at when nothing else changed). Returns the report of the build."""
    collectors = validate_collectors(shared.get("collectors"))
    ids = [c["id"] for c in collectors]
    snapshots, warnings = read_snapshots(atlas, ids)
    state = read_json_file(atlas / SNAPSHOTS_DIR / SCAN_STATE)
    state = state if isinstance(state, dict) else {}
    organization = str(shared.get("organization") or "")
    graph = infer_relations(merge_snapshots(snapshots, ids, state))
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    text = render_graph(graph, organization, today)
    graph_path = atlas / GRAPH_FILE
    old_text = read_text(graph_path) if graph_path.is_file() else None
    previous = None
    if old_text is not None:
        try:
            previous = json.loads(old_text)
        except ValueError:
            previous = None
    if old_text is None or _without_built_at(old_text) != _without_built_at(text):
        write_atomic(graph_path, text)
    scans = {cid: state[cid] for cid in ids if isinstance(state.get(cid), dict)}
    existing = _existing_pages(atlas)
    pages = render_pages(graph, existing, organization, previous, scans)
    updated = []
    for path in sorted(pages):
        if existing.get(path) != pages[path]:
            target = atlas / path
            target.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(target, pages[path])
            updated.append(path)
    return {"ok": True, "nodes": len(graph["nodes"]), "edges": len(graph["edges"]),
            "inferred": sum(1 for e in graph["edges"] if e.get("inferred")),
            "conflicts": sum(len(n["conflicts"]) for n in graph["nodes"]), "pages": updated, "warnings": warnings}


def build_line(report: dict) -> str:
    return (f"Grafo: {report['nodes']} nós, {report['edges']} arestas ({report['inferred']} inferidas), "
            f"{report['conflicts']} conflitos; {len(report['pages'])} páginas atualizadas")


def print_build(report: dict) -> None:
    for warning in report["warnings"]:
        print(warning, file=sys.stderr)
    print(build_line(report))


def cmd_build(as_json=False):
    """build [--json]: graph.json and the pages from the snapshots already on disk (also runs at the end of every
    scan). Exit 0; an unreadable snapshot is a warning."""
    atlas, shared = scan_config()
    report = build_atlas(atlas, shared)
    if as_json:
        print(json.dumps({"version": ATLAS_VERSION, **report}, ensure_ascii=False, indent=2))
    else:
        print_build(report)
    return 0


# ---------------------------------------------------------------- curate (conventions, ADR-0012)

CONVENTIONS_DIR = "conventions"
CONVENTION_PAGE = "convention.md"
CURATION_DEFAULTS = {"min_share": 0.6, "min_total": 20, "min_repos": 3}
CONVENTION_KINDS = ("pr-title", "branch-prefix", "merge-method", "pr-template")
CONVENTION_STATUSES = ("inferred", "confirmed", "rejected")
CONVENTION_KEYS = ("id", "title", "kind", "scope", "status", "proposed_at", "confirmed_by", "confirmed_at",
                   "confirmed_via", "reason")
CONVENTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
VIA_RE = re.compile(r"^(PR #\d+|local)$")
BAD_VIA = "--via aceita 'PR #<n>' ou 'local'"
SAMPLE_MAX = 10
MERGE_METHODS = ("merge", "squash", "rebase")
# signal type -> convention kind; per-item kinds (a pattern dominates in a repository) and per-repository kinds
ITEM_SIGNALS = {"pr-titles": "pr-title", "branch-prefixes": "branch-prefix"}
REPOSITORY_SIGNALS = {"merge-methods": "merge-method", "pr-template": "pr-template"}
PR_TITLE_TITLES = {"conventional": "Títulos de PR em Conventional Commits",
                   "ticket_key": "Títulos de PR com chave de ticket",
                   "other": "Títulos de PR sem Conventional Commits nem chave de ticket"}


def curation_settings(curation) -> dict:
    """{min_share, min_total, min_repos} from the `curation` key (values may come as text from parse_yaml);
    missing = the default; invalid = AtlasError (code 2)."""
    curation = curation if isinstance(curation, dict) else {}
    result = {}
    for key, default in CURATION_DEFAULTS.items():
        value = curation.get(key, default)
        if value in (None, ""):
            value = default
        try:
            number = float(value) if key == "min_share" else int(str(value).strip())
        except (TypeError, ValueError):
            number = None
        valid = number is not None and not isinstance(value, bool) and (
            0 < number <= 1 if key == "min_share" else number >= 1)
        if not valid:
            rule = "um número entre 0 e 1" if key == "min_share" else "um número inteiro ≥ 1"
            raise AtlasError(f"curation.{key} precisa ser {rule}: {value}", 2)
        result[key] = number
    return result


def _number(value) -> float:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _percent(part, whole) -> str:
    return f"{round(100 * part / whole) if whole else 0}%"


def _id_part(text) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "x"


def _clean_line(text) -> str:
    """A sample title as one Markdown line that cannot close the generated region."""
    return " ".join(str(text).split()).replace("<!--", "&lt;!--").replace("-->", "--&gt;")


def _signals_by_type(signals) -> dict:
    """{type: {repository: signal}}: the first signal of each type per repository (snapshots in config order)."""
    result = {}
    for item in signals or []:
        if not isinstance(item, dict) or not isinstance(item.get("repository"), str):
            continue
        result.setdefault(item.get("type"), {}).setdefault(item["repository"], item)
    return result


def _item_title(kind, pattern) -> str:
    if kind == "pr-title":
        return PR_TITLE_TITLES.get(pattern, f"Títulos de PR no padrão {pattern}")
    return f"Branches com o prefixo {pattern}"


def _item_evidence(kind, pattern, repos, by_repo, follows) -> str:
    """Evidence of a pr-title or branch-prefix convention over `repos` (the repositories in its scope)."""
    total = sum(_number(by_repo[r].get("total")) for r in repos)
    count = sum(_number((by_repo[r].get("pattern_counts" if kind == "pr-title" else "counts") or {}).get(pattern))
                for r in repos)
    unit = "PRs" if kind == "pr-title" else "branches"
    lines = [f"- Padrão: `{pattern}`", (f"- Total: {total} {unit} da amostra; seguem o padrão: {count} "
                                         f"({_percent(count, total)})"),
             f"- Repositórios com o padrão dominante: {len([r for r in repos if r in follows])} de {len(repos)}"]
    for repo in repos:
        item = by_repo[repo]
        counts = item.get("pattern_counts" if kind == "pr-title" else "counts") or {}
        part, whole = _number(counts.get(pattern)), _number(item.get("total"))
        mark = "" if repo in follows else " — sem padrão dominante"
        lines.append(f"  - {repo}: {part} de {whole} ({_percent(part, whole)}){mark}")
    sample = [title for repo in repos if repo in follows
              for title in (by_repo[repo].get("sample") or []) if isinstance(title, str)][:SAMPLE_MAX]
    if sample:
        lines.append("- Amostra:")
        lines += [f"  - {_clean_line(title)}" for title in sample]
    return "\n".join(lines)


def _item_proposals(kind, by_repo, settings) -> list:
    """pr-title and branch-prefix: a pattern dominates in a repository with ≥ min_share of ≥ min_total items;
    organization scope when more than half of the repositories with the signal have the same dominant pattern."""
    field = "pattern_counts" if kind == "pr-title" else "counts"
    dominant = {}
    for repo, item in by_repo.items():
        total, counts = _number(item.get("total")), item.get(field)
        if total < settings["min_total"] or not isinstance(counts, dict) or total <= 0:
            continue
        best = sorted(((_number(n), p) for p, n in counts.items()), key=lambda item: (-item[0], item[1]))
        if best and best[0][0] / total >= settings["min_share"]:
            dominant[repo] = best[0][1]
    repos, proposals = sorted(by_repo), []
    for pattern in sorted(set(dominant.values())):
        follows = sorted(r for r, p in dominant.items() if p == pattern)
        base = f"{kind}-{_id_part(pattern)}"
        title = _item_title(kind, pattern)
        if len(follows) * 2 > len(repos):
            proposals.append({"id": base, "title": title, "kind": kind, "scope": "organization",
                              "pattern": pattern, "evidence": _item_evidence(kind, pattern, repos, by_repo, follows)})
            continue
        for repo in follows:
            proposals.append({"id": f"{base}-{_id_part(repo)}", "title": f"{title} em {repo}", "kind": kind,
                              "scope": f"repository:{repo}", "pattern": pattern,
                              "evidence": _item_evidence(kind, pattern, [repo], by_repo, follows)})
    return proposals


def _repository_pattern(kind, item):
    present = item.get("present") if isinstance(item.get("present"), dict) else {}
    if kind == "pr-template":
        return "present" if present.get("pr_template") is True else None
    allowed = [m for m in MERGE_METHODS if present.get(m) is True]
    return allowed[0] if len(allowed) == 1 else None  # several methods allowed count for no pattern


def _repository_proposals(kind, by_repo, settings) -> list:
    """merge-method and pr-template: items = repositories with the signal; a pattern dominates with ≥ min_share of
    them and ≥ min_repos repositories with the signal; scope always organization."""
    repos = sorted(by_repo)
    if len(repos) < settings["min_repos"]:
        return []
    patterns = {repo: _repository_pattern(kind, by_repo[repo]) for repo in repos}
    proposals = []
    for pattern in sorted({p for p in patterns.values() if p}):
        follows = [r for r in repos if patterns[r] == pattern]
        if len(follows) / len(repos) < settings["min_share"]:
            continue
        if kind == "pr-template":
            title, label = "Repositórios com template de PR", "template de PR presente"
        else:
            title, label = f"Merge de PR só por {pattern}", f"só `{pattern}` permitido"
        lines = [f"- Padrão: {label}", (f"- Repositórios com o sinal: {len(repos)}; seguem o padrão: "
                                        f"{len(follows)} ({_percent(len(follows), len(repos))})")]
        for repo in repos:
            other = patterns[repo] if kind == "merge-method" else None
            if repo in follows:
                lines.append(f"  - {repo}: segue")
            elif kind == "merge-method" and other is None:
                lines.append(f"  - {repo}: mais de um método (ou nenhum) permitido")
            elif other:
                lines.append(f"  - {repo}: só `{other}`")
            else:
                lines.append(f"  - {repo}: sem template")
        proposals.append({"id": f"{kind}-{pattern}", "title": title, "kind": kind, "scope": "organization",
                          "pattern": pattern, "evidence": "\n".join(lines)})
    return proposals


def propose_conventions(signals: list, curation=None) -> list:
    """Proposals {id, title, kind, scope, pattern, evidence} from the signals of the snapshots, sorted by id
    (references/curation.md). Never decides: every proposal is only a candidate for status inferred."""
    settings = curation_settings(curation)
    by_type = _signals_by_type(signals)
    proposals = []
    for signal_type, kind in ITEM_SIGNALS.items():
        proposals += _item_proposals(kind, by_type.get(signal_type, {}), settings)
    for signal_type, kind in REPOSITORY_SIGNALS.items():
        proposals += _repository_proposals(kind, by_type.get(signal_type, {}), settings)
    return sorted(proposals, key=lambda p: p["id"])


def split_frontmatter(text: str) -> tuple:
    """(frontmatter text, body) of a convention file; without a frontmatter = ("", text)."""
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end < 0:
        return "", text
    return text[4:end + 1], text[end + 5:]


def read_convention(path: Path) -> tuple:
    """(metadata with text values, text) of conventions/<id>.md."""
    text = read_text(path)
    head, _ = split_frontmatter(text)
    try:
        data = parse_yaml(head) if head else {}
    except ValueError:
        data = {}
    return {k: "" if v is None else str(v) for k, v in data.items()}, text


def _conventions(atlas: Path) -> dict:
    folder = atlas / CONVENTIONS_DIR
    if not folder.is_dir():
        return {}
    return {path.stem: read_convention(path) for path in sorted(folder.glob("*.md"))}


def _new_convention(proposal: dict, organization: str, today: str) -> str:
    text = _template(CONVENTION_PAGE, organization, id=proposal["id"], title=proposal["title"],
                     title_yaml=fmt_scalar(proposal["title"]), kind=proposal["kind"],
                     scope=fmt_scalar(proposal["scope"]), proposed_at=today)
    return fill_regions(text, {"evidence": "\n" + proposal["evidence"] + "\n"})


def curate_propose(atlas: Path, shared: dict) -> dict:
    """Creates conventions/<id>.md (status inferred) for each new proposal and refreshes only the evidence region
    of the existing ones, whatever their status (a rejected id is never proposed again: its file already exists).
    Never writes a decision."""
    collectors = validate_collectors(shared.get("collectors"))
    snapshots, warnings = read_snapshots(atlas, [c["id"] for c in collectors])
    signals = [s for cid in snapshots for s in snapshots[cid].get("signals", [])]
    proposals = propose_conventions(signals, shared.get("curation"))
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    organization = str(shared.get("organization") or "")
    folder = atlas / CONVENTIONS_DIR
    existing = _conventions(atlas)
    new, updated = [], []
    for proposal in proposals:
        path = folder / f"{proposal['id']}.md"
        if proposal["id"] in existing:
            text = existing[proposal["id"]][1]
            changed = fill_regions(text, {"evidence": "\n" + proposal["evidence"] + "\n"})
            if changed != text:
                write_atomic(path, changed)
                updated.append(proposal["id"])
            continue
        folder.mkdir(parents=True, exist_ok=True)
        write_atomic(path, _new_convention(proposal, organization, today))
        new.append(proposal["id"])
    current = _conventions(atlas)
    waiting = [cid for cid, (meta, _) in current.items() if meta.get("status") == "inferred"]
    return {"ok": True, "new": new, "updated": updated, "waiting": waiting, "warnings": warnings}


def curation_line(report: dict) -> str:
    return (f"Convenções: {len(report['new'])} nova(s), {len(report['updated'])} atualizada(s), "
            f"{len(report['waiting'])} esperando decisão")


def _decision_lines(head: str, values: dict) -> str:
    """Frontmatter text with each `key:` line of `values` replaced (or added at the end)."""
    lines = head.splitlines()
    for key, value in values.items():
        line = f"{key}: {value}".rstrip()
        for index, current in enumerate(lines):
            if re.match(rf"^{re.escape(key)}\s*:", current):
                lines[index] = line
                break
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def _write_decision(atlas: Path, args, action: str, status: str) -> int:
    """The only writer of a decision (ADR-0012): checks --by, --via and the current status, then records status,
    confirmed_by, confirmed_at, confirmed_via (and reason on reject) in the frontmatter. Exit 2 when refused."""
    by, via = (args.by or "").strip(), (args.via or "").strip()
    if not by or not via:
        raise AtlasError(f"{action} exige --by e --via", 2)
    if not VIA_RE.match(via):
        raise AtlasError(BAD_VIA, 2)
    cid = args.id
    path = atlas / CONVENTIONS_DIR / f"{cid}.md"
    if not CONVENTION_ID_RE.match(cid or "") or not path.is_file():
        raise AtlasError(f"convenção não encontrada: {cid}", 2)
    meta, text = read_convention(path)
    if meta.get("status") != "inferred":
        raise AtlasError(f"convenção já está {meta.get('status') or 'sem status'}", 2)
    head, body = split_frontmatter(text)
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    values = {"status": status, "confirmed_by": fmt_scalar(by), "confirmed_at": today,
              "confirmed_via": json.dumps(via, ensure_ascii=False)}
    reason = (getattr(args, "reason", None) or "").strip()
    if reason:
        values["reason"] = fmt_scalar(reason)
    write_atomic(path, "---\n" + _decision_lines(head, values) + "---\n" + body)
    print(f"{cid}: {status} por {by} ({via})")
    return 0


def confirm_convention(atlas: Path, args) -> int:
    return _write_decision(atlas, args, "confirm", "confirmed")


def reject_convention(atlas: Path, args) -> int:
    return _write_decision(atlas, args, "reject", "rejected")


def _list_conventions(atlas: Path, status, as_json) -> int:
    rows = []
    for cid, (meta, _) in _conventions(atlas).items():
        if status and meta.get("status") != status:
            continue
        row = {key: meta.get(key, "") for key in CONVENTION_KEYS}
        row["id"] = cid
        rows.append(row)
    if as_json:
        print(json.dumps({"version": ATLAS_VERSION, "conventions": rows}, ensure_ascii=False, indent=2))
        return 0
    for row in rows:
        decided = (f" — {row['confirmed_by']}, {row['confirmed_at']}, {row['confirmed_via']}"
                   if row["confirmed_by"] else "")
        print(f"{row['status'] or '?'} {row['id']} — {row['title']} ({row['scope']}){decided}")
    print(f"{len(rows)} convenção(ões)")
    return 0


def cmd_curate(args):
    """curate propose [--json] | list [--status S] [--json] | confirm ID --by --via | reject ID --by --via
    [--reason]. Only confirm and reject record a decision; propose (also run at the end of every scan) only
    creates inferred conventions and refreshes evidence."""
    atlas, shared = scan_config()
    if args.action == "propose":
        report = curate_propose(atlas, shared)
        if args.json:
            print(json.dumps({"version": ATLAS_VERSION, **report}, ensure_ascii=False, indent=2))
        else:
            for warning in report["warnings"]:
                print(warning, file=sys.stderr)
            print(curation_line(report))
        return 0
    if args.action == "list":
        return _list_conventions(atlas, args.status, args.json)
    if args.action == "confirm":
        return confirm_convention(atlas, args)
    return reject_convention(atlas, args)


# ---------------------------------------------------------------- context (read-only package for a task)

MAX_HOPS = 2
NO_SCAN = "atlas ainda sem scan — rode scan"
NOTHING_FOUND = "Nada encontrado no atlas para: {query}"
DEFAULT_STALE_DAYS = 14
CONTEXT_HEADINGS = {"warnings": "## Aviso de envelhecimento", "services": "## Serviços",
                    "dependencies": "## Dependências", "rules": "## Convenções (regra)",
                    "hints": "## Convenções (dica)", "omitted": "## Omitidos"}
TERM_RE = re.compile(r"[\w.-]+", re.UNICODE)
# weight of a query term found in: the name or id (whole), part of the name or id, the attrs, the team notes
SCORE_EXACT, SCORE_PART, SCORE_ATTRS, SCORE_NOTES = 10, 6, 3, 1
OMITTED_MAX = 50  # omitted items listed one by one; the rest becomes a single "… e mais N" line


def _days_between(first: str, last: str):
    try:
        return (datetime.date.fromisoformat(last) - datetime.date.fromisoformat(first)).days
    except (TypeError, ValueError):
        return None


def staleness_warnings(scan_state, stale_days, today) -> list:
    """Warnings from snapshots/_scan.json: a collector with status ok and seen_at more than stale_days days before
    `today` -> "Atlas com D dias desde o último scan de: A, B (stale_days: N)" (one line per D, oldest first); a
    collector whose last scan failed -> "Último scan falhou: C, D"; an entry without a usable seen_at ->
    "Atlas sem data válida do último scan de: E (stale_days: N)". Collectors sorted by id; deterministic. (A
    declared collector missing from the state is warned by build_context: "Nunca escaneado: F".)"""
    stale, failed, undated = {}, [], []
    for cid in sorted(scan_state if isinstance(scan_state, dict) else {}):
        entry = scan_state[cid] if isinstance(scan_state[cid], dict) else {}
        if entry.get("status") == "failed":
            failed.append(cid)
            continue
        days = _days_between(str(entry.get("seen_at") or ""), today)
        if days is None:  # no usable seen_at: as old as it gets
            undated.append(cid)
        elif days > int(stale_days):
            stale.setdefault(days, []).append(cid)
    warnings = [f"Atlas com {days} dias desde o último scan de: {', '.join(stale[days])} (stale_days: {stale_days})"
                for days in sorted(stale, reverse=True)]
    if undated:
        warnings.append(f"Atlas sem data válida do último scan de: {', '.join(undated)} (stale_days: {stale_days})")
    if failed:
        warnings.append(f"Último scan falhou: {', '.join(failed)}")
    return warnings


def _stale_days(shared: dict) -> int:
    value = shared.get("stale_days", DEFAULT_STALE_DAYS)
    if value in (None, ""):
        return DEFAULT_STALE_DAYS
    if isinstance(value, bool) or not re.match(r"^\d+$", str(value).strip()):
        raise AtlasError(f"stale_days precisa ser um número inteiro de dias: {value}", 2)
    return int(str(value).strip())


def _query_terms(query: str) -> list:
    return list(dict.fromkeys(t for t in TERM_RE.findall(query.casefold()) if len(t) > 1))


def _team_text(text: str, template: str) -> str:
    """The text of a service page written by people: outside the generated regions and without the template's
    fixed lines (title, introduction, headings)."""
    fixed = {line.strip() for line in template.splitlines() if line.strip()}
    outside = REGION_SUB_RE.sub("", text)
    return "\n".join(line for line in outside.splitlines() if line.strip() and line.strip() not in fixed)


def _score_service(node, notes: str, terms) -> tuple:
    """(score, reason) of a service for the query terms: name/id, attrs and the team notes of its page."""
    eid = node["key"].split(":", 1)[1]
    names = {node["name"].casefold(), eid.casefold()}
    words = set(TERM_RE.findall(" ".join(names)))
    attrs = " ".join(f"{k} {_fmt_value(v)}" for k, v in node["attrs"].items()).casefold()
    notes = notes.casefold()
    score, hits = 0, {"nome": [], "atributos": [], "notas": []}
    for term in terms:
        if term in names or term in words:
            score += SCORE_EXACT
            hits["nome"].append(term)
        elif any(term in name for name in names):
            score += SCORE_PART
            hits["nome"].append(term)
        if term in attrs:
            score += SCORE_ATTRS
            hits["atributos"].append(term)
        if term in notes:
            score += SCORE_NOTES
            hits["notas"].append(term)
    reason = "; ".join(f"{where}: {', '.join(found)}" for where, found in hits.items() if found)
    return score, reason


def _service_entry(key, index, page, score, reason) -> dict:
    node = index.nodes[key]
    deployments = []
    for deployment in index.sources(key, "deploys", "deployment"):
        envs = [index.name(e) for e in index.targets(deployment, "runs_in", "environment")]
        deployments.append({"id": deployment.split(":", 1)[1], "environments": envs})
    repositories = _union(index.targets(key, "sourced_from", "repository"))
    owners = _union(*(index.sources(t, "owns", "team") for t in [key] + repositories))
    return {"key": key, "name": node["name"], "score": score, "reason": reason, "page": page,
            "repositories": [r.split(":", 1)[1] for r in repositories], "deployments": deployments,
            "owners": [{"id": t.split(":", 1)[1], "name": index.name(t)} for t in owners], "attrs": node["attrs"],
            "seen_at": node["seen_at"]}


def _dependencies(starts, index, hops) -> list:
    """Dependency edges (depends_on, reads, writes, publishes, consumes, both directions) reached in up to `hops`
    steps from the found services; sorted by (from, type, to)."""
    seen, frontier, edges = set(starts), list(starts), {}
    for _ in range(hops):
        following = []
        for key in frontier:
            for rtype in DEPENDENCY_TYPES:
                for edge in index.out.get((key, rtype), []) + index.into.get((key, rtype), []):
                    edges[(edge["from"], edge["type"], edge["to"])] = edge
                    other = edge["to"] if edge["from"] == key else edge["from"]
                    if other not in seen:
                        seen.add(other)
                        following.append(other)
        frontier = sorted(following)
    result = []
    for key in sorted(edges):
        edge = edges[key]
        item = {"from": edge["from"], "to": edge["to"], "type": edge["type"], "inferred": bool(edge.get("inferred"))}
        if edge.get("evidence"):
            item["evidence"] = edge["evidence"]
        result.append(item)
    return result


def _complete_decision(meta) -> bool:
    """confirmed_by, a confirmed_at date and a confirmed_via in the contract format ("PR #n" | "local")."""
    by, via = str(meta.get("confirmed_by") or "").strip(), str(meta.get("confirmed_via") or "").strip()
    try:
        datetime.date.fromisoformat(str(meta.get("confirmed_at") or ""))
    except ValueError:
        return False
    return bool(by) and bool(VIA_RE.match(via))


def _context_conventions(atlas: Path, repositories) -> tuple:
    """(rules, hints): conventions of the organization scope and of `repositories`. Rules = confirmed with a complete
    decision; hints = inferred, and confirmed with an incomplete decision (`incomplete: true`); rejected never."""
    scopes = {"organization"} | {f"repository:{r}" for r in repositories}
    rules, hints = [], []
    for cid, (meta, _) in _conventions(atlas).items():
        if meta.get("scope") not in scopes:
            continue
        item = {key: meta.get(key, "") for key in CONVENTION_KEYS if key != "reason"}
        item["id"], item["path"] = cid, f"{CONVENTIONS_DIR}/{cid}.md"
        if meta.get("status") == "confirmed":
            if _complete_decision(meta):
                rules.append(item)
            else:  # confirmed by hand without who, when or where: not a rule (ADR-0012)
                item["incomplete"] = True
                hints.append(item)
        elif meta.get("status") == "inferred":
            hints.append(item)
    return rules, hints


def _empty_package(query, warnings) -> dict:
    return {"query": query, "warnings": warnings, "services": [], "dependencies": [], "rules": [], "hints": [],
            "omitted": []}


def _omitted_label(section, item) -> str:
    if section == "services":
        return f"serviço {item['name']} (`{item['key']}`, {item['page']})"
    if section == "dependencies":
        return f"dependência `{item['from']}` → `{item['to']}` ({item['type']})"
    label = "convenção (regra)" if section == "rules" else "convenção (dica)"
    return f"{label} `{item['id']}` ({item['path']})"


def _fit(package: dict, max_chars: int) -> dict:
    """The package with the longest prefix of its items (services, rules, dependencies, hints, in this order) whose
    Markdown fits in max_chars; the rest goes to `omitted` (one line per item, the first OMITTED_MAX of them, then
    one "… e mais N" line). Warnings are never omitted."""
    order = ("services", "rules", "dependencies", "hints")
    items = [(section, item) for section in order for item in package[section]]

    def keep(count):
        kept = dict(package, **{section: [] for section in order})
        for section, item in items[:count]:
            kept[section].append(item)
        rest = items[count:]
        kept["omitted"] = [_omitted_label(section, item) for section, item in rest[:OMITTED_MAX]]
        if len(rest) > OMITTED_MAX:
            kept["omitted"].append(f"… e mais {len(rest) - OMITTED_MAX} item(ns) — use termos mais específicos, "
                                   "--hops menor ou --max-chars maior")
        return kept

    if len(render_context(keep(len(items)))) <= max_chars:
        return keep(len(items))
    low, high = 0, len(items) - 1  # the largest count that fits (0 if none)
    while low < high:
        middle = (low + high + 1) // 2
        if len(render_context(keep(middle))) <= max_chars:
            low = middle
        else:
            high = middle - 1
    return keep(low)


def build_context(atlas: Path, query: str, hops=1, limit=8, max_chars=30000, today=None) -> dict:
    """Read-only package for a task (references/context.md): staleness warnings, the services found by the query
    terms (name, id, attrs and the team notes of their pages, by score), the dependency edges up to `hops` steps,
    the confirmed (rules) and inferred (hints) conventions of the organization and of the services' repositories,
    and what did not fit in max_chars (omitted). An atlas without scan = empty package with the warning."""
    atlas = Path(atlas)
    today = today or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    shared_path = atlas / SHARED_FILE
    shared = read_yaml(shared_path) if shared_path.is_file() else {}
    state = read_json_file(atlas / SNAPSHOTS_DIR / SCAN_STATE)
    graph = read_json_file(atlas / GRAPH_FILE)
    if not isinstance(state, dict) or not state or not isinstance(graph, dict) or not isinstance(
            graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        return _empty_package(query, [NO_SCAN])
    try:
        declared = {c["id"] for c in validate_collectors(shared.get("collectors"))}
    except AtlasError:
        declared = set()
    if declared:
        state = {cid: entry for cid, entry in state.items() if cid in declared}
    warnings = staleness_warnings(state, _stale_days(shared), today)
    never = sorted(declared - set(state))
    if never:
        warnings.append(f"Nunca escaneado: {', '.join(never)}")
    package = _empty_package(query, warnings)
    index = _Index(graph, _existing_service_pages(atlas))
    organization = str(shared.get("organization") or graph.get("organization") or "")
    terms = _query_terms(query)
    found = []
    for key, name in index.slugs.items():
        node = index.nodes[key]
        page = f"{SERVICES_DIR}/{name}.md"
        path = atlas / page
        notes = ""
        if path.is_file():
            eid = key.split(":", 1)[1]
            title = eid if node["name"] == eid else f"{node['name']} ({eid})"
            notes = _team_text(read_text(path), _template(SERVICE_PAGE, organization, title=title, key=key))
        score, reason = _score_service(node, notes, terms)
        if score > 0:
            found.append((score, key, page, reason))
    found.sort(key=lambda item: (-item[0], item[1]))
    package["services"] = [_service_entry(key, index, page, score, reason)
                           for score, key, page, reason in found[:limit]]
    if not package["services"]:
        return package
    starts = [s["key"] for s in package["services"]]
    package["dependencies"] = _dependencies(starts, index, hops)
    repositories = _union(*(s["repositories"] for s in package["services"]))
    package["rules"], package["hints"] = _context_conventions(atlas, repositories)
    return _fit(package, max_chars)


def _existing_service_pages(atlas: Path) -> dict:
    folder = atlas / SERVICES_DIR
    if not folder.is_dir():
        return {}
    return {f"{SERVICES_DIR}/{path.name}": read_text(path) for path in sorted(folder.glob("*.md"))}


def _service_lines(service) -> list:
    lines = [f"### {service['name']} (`{service['key']}`)", "",
             f"- Página: {service['page']}",
             f"- Encontrado por: {service['reason']} (pontuação {service['score']})"]
    if service["repositories"]:
        lines.append(f"- Repositório: {', '.join(service['repositories'])}")
    if service["deployments"]:
        parts = [f"{', '.join(d['environments']) or 'sem ambiente'}: {d['id']}" for d in service["deployments"]]
        lines.append(f"- Deployments: {'; '.join(parts)}")
    if service["owners"]:
        lines.append("- Donos: " + ", ".join(f"{o['name']} ({o['id']})" for o in service["owners"]))
    lines += [f"- {name}: {_fmt_value(value)}" for name, value in service["attrs"].items()]
    lines.append(f"- Visto em: {service['seen_at']}")
    return lines + [""]


def _dependency_line(edge) -> str:
    note = edge["type"]
    if edge["inferred"]:
        note += f", inferida de `{edge['evidence']}`" if edge.get("evidence") else ", inferida"
    return f"- `{edge['from']}` → `{edge['to']}` — {note}"


def _convention_line(item, hint) -> str:
    where = item["scope"]
    if hint:
        note = "não confirmada (decisão incompleta)" if item.get("incomplete") else "não confirmada"
        return f"- `{item['id']}` — {item['title']} ({where}; {item['path']}) — {note}"
    return (f"- `{item['id']}` — {item['title']} ({where}; confirmada por {item['confirmed_by']} em "
            f"{item['confirmed_at']} via {item['confirmed_via']}; {item['path']})")


def _flat(value):
    """Every text of the package on one line (newlines, CR and tabs become spaces): data from the atlas never
    becomes a heading or an item of the package."""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, dict):
        return {_flat(key): _flat(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_flat(item) for item in value]
    return value


def render_context(package: dict) -> str:
    """The package in Markdown, in the contract order; each section only when it has content (the warning, when
    there is one, is always first). Every value is flattened to one line first (_flat)."""
    package = _flat(package)
    parts = []

    def add(section, lines):
        if lines:
            parts.append("\n".join([CONTEXT_HEADINGS[section], "", *lines]).rstrip() + "\n")

    add("warnings", [f"- {w}" for w in package["warnings"]])
    add("services", [line for s in package["services"] for line in _service_lines(s)])
    add("dependencies", [_dependency_line(e) for e in package["dependencies"]])
    add("rules", [_convention_line(c, False) for c in package["rules"]])
    add("hints", [_convention_line(c, True) for c in package["hints"]])
    add("omitted", [f"- {item}" for item in package["omitted"]])
    return "\n".join(parts)


def cmd_context(args):
    """context QUERY [--hops 0..2] [--limit N] [--max-chars N] [--json]: read-only package (never writes to the
    atlas). Nothing found = the fixed message and exit 0; invalid argument = exit 2; not configured = exit 3."""
    if not 0 <= args.hops <= MAX_HOPS:
        raise AtlasError(f"--hops precisa estar entre 0 e {MAX_HOPS}: {args.hops}", 2)
    if args.limit < 1:
        raise AtlasError(f"--limit precisa ser maior que zero: {args.limit}", 2)
    if args.max_chars < 1:
        raise AtlasError(f"--max-chars precisa ser maior que zero: {args.max_chars}", 2)
    atlas, _ = scan_config()
    query = " ".join(args.query).strip()
    package = build_context(atlas, query, args.hops, args.limit, args.max_chars)
    nothing = not package["services"]
    if args.json:
        data = {"version": ATLAS_VERSION, **package}
        if nothing:
            data["message"] = NOTHING_FOUND.format(query=query)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    text = render_context(package)
    if text:
        print(text)
    if nothing:
        print(NOTHING_FOUND.format(query=query))
    return 0


# ---------------------------------------------------------------- lint (read-only checks of the atlas)

LINT_RULES = ("secret-leak", "config", "failed-collector", "stale", "broken-ref", "pending-convention",
              "orphan-page")
LINT_ERRORS = ("secret-leak", "config", "failed-collector")
VCS_DIRS = (".git", ".hg", ".svn", ".bzr", "_darcs", ".jj")
LINT_IGNORED_FILES = (".DS_Store", "Thumbs.db", "desktop.ini")
LINT_MAX_BYTES = 32 * 1024 * 1024  # a bigger file is not read (config finding): the lint stays fast and bounded
LINT_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
SECRET_REGEXES = tuple((name, re.compile(regex, re.DOTALL)) for name, regex in SECRET_PATTERNS)
LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^)]*[\"'])?\s*\)")
CODE_SPAN_RE = re.compile(r"`[^`\n]*`")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INDENTED_CODE_RE = re.compile(r"^(?: {4}|\t)")
EXTERNAL_LINK_RE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//|#)")  # http:, https:, mailto:, //host, #anchor
YAML_ERROR_RE = re.compile(r"^(aspas sem fechar|'.' sem fechar|chave sem ':'|texto depois do valor)")
LINT_SUGGESTIONS = {
    "secret-leak": "apague o valor do arquivo (o histórico do git também guarda) e troque a credencial; nunca copie "
                   "o valor para outro lugar",
    "failed-collector": "rode `atlas.py scan --only <id>` e veja o motivo da FALHA (credencial, timeout, contrato)",
    "stale": "rode `atlas.py scan` (ou `scan --only <id>`) para atualizar os fatos desse coletor",
    "pending-convention": "mostre a evidência a uma pessoa e registre a decisão: `atlas.py curate confirm <id> --by "
                          "NOME --via \"PR #n\"|local` ou `curate reject <id> ...`",
    "orphan-page": "confirme com o time se a entidade foi desligada; se sim, apague a página (decisão do time) ou "
                   "mova as notas para outra página",
}
SHARED_SUGGESTION = "corrija o atlas-config.yml (references/config.md e references/collector-contract.md)"
READ_SUGGESTION = ("regrave o arquivo em UTF-8 válido; se é gerado (snapshots/, graph.json, regiões), rode "
                   "`atlas.py scan`")
GENERATED_SUGGESTION = "arquivo gerado com formato inesperado: rode `atlas.py scan` (ou `build`) para refazê-lo"
SPECIAL_SUGGESTION = ("o atlas só tem arquivos e pastas comuns: troque por uma cópia do conteúdo ou tire da pasta do "
                      "atlas")
PERMISSION_SUGGESTION = "dê permissão de leitura (e de listagem, numa pasta) ou tire da pasta do atlas"


def lint_rules(only=None) -> list:
    """The rules of --only ("a,b") in report order; None = all of them. Unknown rule = AtlasError (code 2)."""
    if only in (None, ""):
        return list(LINT_RULES)
    wanted = [name.strip() for name in str(only).split(",") if name.strip()]
    unknown = [name for name in wanted if name not in LINT_RULES]
    if unknown:
        raise AtlasError(f"regra desconhecida em --only: {', '.join(unknown)} — use: {', '.join(LINT_RULES)}", 2)
    return [rule for rule in LINT_RULES if rule in wanted]


def _finding(rule, path, detail, suggestion=None) -> dict:
    return {"rule": rule, "severity": "error" if rule in LINT_ERRORS else "warn", "path": path, "detail": detail,
            "suggestion": suggestion or LINT_SUGGESTIONS.get(rule, "")}


def _special_kind(mode) -> str:
    if stat.S_ISLNK(mode):
        return "link simbólico"
    if stat.S_ISFIFO(mode):
        return "FIFO"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
        return "dispositivo"
    return "arquivo especial"


class _AtlasFiles:
    """Every regular file of the atlas (VCS folders skipped, and .org-atlas/skill/scripts/atlas.py, the tool written
    by vendor, whose own patterns look like secrets; every other file of the copy is read), read once. Symlinks, FIFOs, sockets and devices are
    never read nor followed; they, unreadable files and folders, non-UTF-8 files (also kept, decoded with
    replacement, for secret-leak) and JSON with an invalid content or shape become `problems` (config findings)."""

    def __init__(self, atlas: Path):
        self.atlas, self.texts, self.lossy, self.names, self.problems, self._json = atlas, {}, {}, [], {}, {}
        self._copy_tool = f"{SKILL_COPY}/scripts/atlas.py"
        for root, dirs, files in os.walk(atlas, onerror=self._walk_error):
            kept = []
            for name in sorted(d for d in dirs if d not in VCS_DIRS):
                path = os.path.join(root, name)
                rel = self.rel(path)
                self.names.append((rel + "/", name))
                try:
                    mode = os.lstat(path).st_mode
                except OSError as e:
                    self.problem(rel, f"pasta ilegível: {e.strerror or 'erro de leitura'}", PERMISSION_SUGGESTION)
                    continue
                if stat.S_ISDIR(mode):
                    kept.append(name)
                else:  # a symlink to a folder: listed by os.walk, never followed
                    self.problem(rel, f"{_special_kind(mode)}: não é lido nem seguido", SPECIAL_SUGGESTION)
            dirs[:] = kept
            for name in sorted(files):
                if name not in LINT_IGNORED_FILES:
                    path = os.path.join(root, name)
                    if self._is_skill_copy(path, self.rel(path)):
                        continue
                    self.names.append((self.rel(path), name))
                    self._read(path, self.rel(path))

    def rel(self, path) -> str:
        try:
            rel = Path(path).relative_to(self.atlas).as_posix()
        except ValueError:
            return "."
        return rel or "."

    def _is_skill_copy(self, path, rel) -> bool:
        """.org-atlas/skill/scripts/atlas.py as vendor wrote it: identical to this atlas.py or, when the lint runs from
        the copy itself (nothing else to compare with), that same file. Limitation: an edit to the atlas.py of the
        copy is not scanned when the lint runs from it."""
        if rel != self._copy_tool:
            return False
        source = Path(__file__).resolve()
        try:
            info = os.lstat(path)
            if stat.S_ISREG(info.st_mode) and os.path.samefile(path, source):
                return True
            expected = source.read_bytes()
            if not stat.S_ISREG(info.st_mode) or info.st_size != len(expected):
                return False
            with os.fdopen(os.open(path, LINT_OPEN_FLAGS), "rb") as handle:
                return handle.read(len(expected) + 1) == expected
        except OSError:
            return False

    def problem(self, rel, detail, suggestion=READ_SUGGESTION) -> None:
        self.problems.setdefault(rel, (detail, suggestion))

    def _walk_error(self, error) -> None:
        self.problem(self.rel(error.filename or self.atlas),
                     f"pasta ilegível: {error.strerror or 'erro de leitura'}", PERMISSION_SUGGESTION)

    def _read(self, path, rel) -> None:
        try:
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode):
                self.problem(rel, f"{_special_kind(info.st_mode)}: não é lido nem seguido", SPECIAL_SUGGESTION)
                return
            if info.st_size > LINT_MAX_BYTES:
                self.problem(rel, f"arquivo com mais de {LINT_MAX_BYTES // (1024 * 1024)} MB: não é lido",
                             "tire o arquivo do atlas (o atlas guarda texto) ou divida-o")
                return
            # O_NOFOLLOW and O_NONBLOCK: a file swapped for a symlink or a FIFO after lstat is not followed nor waited
            with os.fdopen(os.open(path, LINT_OPEN_FLAGS), "rb") as handle:
                mode = os.fstat(handle.fileno()).st_mode
                if not stat.S_ISREG(mode):
                    self.problem(rel, f"{_special_kind(mode)}: não é lido nem seguido", SPECIAL_SUGGESTION)
                    return
                data = handle.read(LINT_MAX_BYTES + 1)
        except OSError as e:
            self.problem(rel, f"arquivo ilegível: {e.strerror or 'erro de leitura'}", PERMISSION_SUGGESTION)
            return
        if len(data) > LINT_MAX_BYTES:
            self.problem(rel, f"arquivo com mais de {LINT_MAX_BYTES // (1024 * 1024)} MB: não é lido",
                         "tire o arquivo do atlas (o atlas guarda texto) ou divida-o")
            return
        try:
            self.texts[rel] = data.decode("utf-8")
        except UnicodeDecodeError:
            self.lossy[rel] = data.decode("utf-8", "replace")  # still searched for secrets
            self.problem(rel, "arquivo ilegível: não é UTF-8")

    def json(self, rel):
        """Parsed JSON of a file, or None (missing, unreadable or invalid: invalid is a problem). Parsed once."""
        if rel not in self._json:
            value = None
            if rel in self.texts:
                try:
                    value = json.loads(self.texts[rel])
                except ValueError as e:
                    self.problem(rel, f"JSON inválido: {e.msg} (linha {e.lineno})")
            self._json[rel] = value
        return self._json[rel]


def _lint_patterns(extras) -> list:
    return list(SECRET_REGEXES) + [(f"extra_patterns[{index}]", regex) for index, regex in extras]


def _matching_patterns(text, patterns) -> list:
    return [name for name, regex in patterns if any(m.group(0) for m in regex.finditer(text))]


def _name_patterns(name, patterns) -> list:
    """Patterns that match a file or folder name, or its stem without the extension (^acme-[0-9a-f]{8}$ matches
    acme-feedface.md): the same pieces _mask_path masks."""
    stem = os.path.splitext(name)[0]
    found = set(_matching_patterns(name, patterns)) | (set(_matching_patterns(stem, patterns)) if stem else set())
    return [label for label, _ in patterns if label in found]


def _lint_secrets(files: _AtlasFiles, extras) -> list:
    """secret-leak: each match of a redaction pattern (built-in and extra_patterns) in any file, by file:line and
    pattern name, and each file or folder whose name matches one; never the value."""
    findings, seen = [], set()
    patterns = _lint_patterns(extras)
    for rel, name in files.names:
        found = _name_patterns(name, patterns)
        if found:
            where = "da pasta" if rel.endswith("/") else "do arquivo"
            findings.append(_finding("secret-leak", rel, f"padrão {', '.join(found)} no nome {where} (o valor não é "
                                                         "mostrado)", "renomeie sem o valor e troque a credencial "
                                                                      "(o histórico do git também guarda o nome)"))
    for rel, text in (*files.texts.items(), *files.lossy.items()):
        for name, regex in patterns:
            for match in regex.finditer(text):
                if not match.group(0):
                    continue
                line = text.count("\n", 0, match.start()) + 1
                if (rel, line, name) in seen:
                    continue
                seen.add((rel, line, name))
                findings.append(_finding("secret-leak", f"{rel}:{line}", f"padrão {name} (o valor não é mostrado)"))
    return findings


def _lint_config(files: _AtlasFiles, problems) -> list:
    findings = [_finding("config", SHARED_FILE, problem, SHARED_SUGGESTION) for problem in problems]
    for rel, (detail, suggestion) in sorted(files.problems.items()):
        findings.append(_finding("config", rel, detail, suggestion))
    return findings


def _yaml_problem(error) -> str:
    """The parser message repeats the text of the line (maybe a value): only its fixed kind is shown."""
    kind = YAML_ERROR_RE.match(str(error))
    return f"YAML inválido{f' ({kind.group(1)})' if kind else ''} — o trecho não é mostrado (pode ter um valor)"


def _extra_patterns(shared) -> tuple:
    """([(index, compiled)] of the valid redaction.extra_patterns, problems): one invalid entry is reported and the
    valid ones are still used."""
    redaction = shared.get("redaction")
    extra = redaction.get("extra_patterns") if isinstance(redaction, dict) else None
    if extra in (None, ""):
        return [], []
    if not isinstance(extra, list):
        return [], ["redaction.extra_patterns precisa ser uma lista de regex"]
    compiled, problems = [], []
    for index, pattern in enumerate(extra):
        try:
            compiled.append((index, compile_extra_pattern(index, pattern)))
        except AtlasError as e:
            problems.append(str(e))
    return compiled, problems


def _shared_problems(files: _AtlasFiles) -> tuple:
    """(shared configuration, problems, [(index, extra pattern)]) of atlas-config.yml: missing, invalid YAML,
    check_shared, unknown keys, collectors and redaction. Unreadable or not UTF-8 is already a problem of files."""
    if SHARED_FILE not in files.texts:
        missing = SHARED_FILE not in files.problems
        return {}, [f"{SHARED_FILE} não existe — rode init"] if missing else [], []
    try:
        shared = parse_yaml(files.texts[SHARED_FILE])
    except ValueError as e:
        return {}, [_yaml_problem(e)], []
    problems = check_shared(shared)
    problems += [f"chave desconhecida: {key} (válidas: {', '.join(SHARED_KEYS)})" for key in shared
                 if key not in SHARED_KEYS]
    if not problems:  # check_shared already names absolute paths and wrong shapes
        try:
            validate_collectors(shared.get("collectors"))
        except AtlasError as e:
            problems.append(str(e))
    extras, extra_problems = _extra_patterns(shared)
    return shared, problems + extra_problems, extras


def _graph_shape(files: _AtlasFiles):
    """(node keys, edges with text ends) of graph.json, or None (missing or invalid); a wrong shape is a problem."""
    graph = files.json(GRAPH_FILE)
    if graph is None:
        return None
    if not (isinstance(graph, dict) and isinstance(graph.get("nodes"), list) and isinstance(graph.get("edges"), list)):
        files.problem(GRAPH_FILE, "formato inesperado: precisa ser um objeto com as listas nodes e edges "
                                  "(references/graph.md)", GENERATED_SUGGESTION)
        return None
    nodes = [n for n in graph["nodes"] if isinstance(n, dict) and isinstance(n.get("key"), str)]
    edges = [e for e in graph["edges"] if isinstance(e, dict) and isinstance(e.get("from"), str)
             and isinstance(e.get("to"), str)]
    keys, bad_nodes, bad_edges = {n["key"] for n in nodes}, len(graph["nodes"]) - len(nodes), len(graph["edges"]) - len(edges)
    if bad_nodes or bad_edges:
        files.problem(GRAPH_FILE, f"formato inesperado: {bad_nodes} nó(s) sem key de texto, {bad_edges} aresta(s) "
                                  "sem from e to de texto (references/graph.md)", GENERATED_SUGGESTION)
    return keys, edges


def _scan_entries(files: _AtlasFiles, shared) -> tuple:
    """(declared collector ids, {id: entry} of _scan.json for them); a wrong shape is a problem."""
    try:
        declared = [c["id"] for c in validate_collectors(shared.get("collectors"))]
    except AtlasError:
        declared = []
    rel = f"{SNAPSHOTS_DIR}/{SCAN_STATE}"
    state = files.json(rel)
    if state is not None and not isinstance(state, dict):
        files.problem(rel, "formato inesperado: precisa ser um objeto {id do coletor: {seen_at, status, ...}}",
                      GENERATED_SUGGESTION)
    state = state if isinstance(state, dict) else {}
    bad = sum(1 for entry in state.values() if not isinstance(entry, dict))
    if bad:
        files.problem(rel, f"formato inesperado: {bad} entrada(s) de coletor que não são objeto", GENERATED_SUGGESTION)
    if declared:
        state = {cid: entry for cid, entry in state.items() if cid in declared}
    return declared, {cid: entry if isinstance(entry, dict) else {} for cid, entry in sorted(state.items())}


def _lint_collectors(declared, state, stale_days, today, rules, extras) -> list:
    findings, path = [], f"{SNAPSHOTS_DIR}/{SCAN_STATE}"
    shown = {cid: _mask_all(cid, extras) for cid in set(declared) | set(state)}  # an id may look like a secret
    for cid, entry in state.items():
        if entry.get("status") == "failed":
            if "failed-collector" in rules:
                seen = entry.get("seen_at") or "nunca"
                findings.append(_finding("failed-collector", path,
                                         f"coletor {shown[cid]}: o último scan falhou (último scan bom: {seen})",
                                         LINT_SUGGESTIONS["failed-collector"].replace("<id>", shown[cid])))
            continue
        if "stale" not in rules:
            continue
        days = _days_between(str(entry.get("seen_at") or ""), today)
        if days is None:
            detail = f"coletor {shown[cid]}: sem data válida do último scan"
        elif days > stale_days:
            detail = f"coletor {shown[cid]}: {days} dias desde o último scan (stale_days: {stale_days})"
        else:
            continue
        findings.append(_finding("stale", path, detail, LINT_SUGGESTIONS["stale"].replace("<id>", shown[cid])))
    if "stale" in rules:
        for cid in sorted(set(declared) - set(state)):
            findings.append(_finding("stale", path, f"coletor {shown[cid]}: nunca escaneado",
                                     LINT_SUGGESTIONS["stale"].replace("<id>", shown[cid])))
    return findings


def _without_code(text: str) -> str:
    """Markdown text without fenced (``` and ~~~) and indented code blocks, nor code spans: links there are text."""
    lines, fence, previous_blank, in_indented = [], None, True, False
    for line in text.split("\n"):
        opening = FENCE_RE.match(line)
        if fence:
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence) \
                    and not line.strip().strip(fence[0]):
                fence = None
            lines.append("")
            continue
        if opening:
            fence, in_indented = opening.group(1), False
            lines.append("")
            continue
        blank = not line.strip()
        if not blank and INDENTED_CODE_RE.match(line) and (previous_blank or in_indented):
            in_indented = True
            lines.append("")
        else:
            in_indented = in_indented and blank
            lines.append(line)
        previous_blank = blank
    return CODE_SPAN_RE.sub("", "\n".join(lines))


def _link_problem(atlas_root: str, base: str, target: str, problems=()):
    """None when a relative link reaches an existing path inside the atlas, or a path under a folder that could not
    be read (already a config finding: it cannot be checked); else why it is broken."""
    local = urllib.parse.unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not local:
        return None
    resolved = os.path.normpath(os.path.join(base, local))
    if resolved != atlas_root and not resolved.startswith(atlas_root.rstrip(os.sep) + os.sep):
        return "aponta para fora do atlas"
    parts = os.path.relpath(resolved, atlas_root).replace(os.sep, "/").split("/")
    if any("/".join(parts[:i]) in problems for i in range(1, len(parts))):
        return None
    try:
        found = os.path.lexists(resolved)
    except (OSError, ValueError):
        found = False
    return None if found else "o arquivo não existe"


def _lint_broken_refs(files: _AtlasFiles, extras) -> list:
    findings = []
    graph = _graph_shape(files)
    if graph:
        keys, edges = graph
        for edge in edges:
            for end in ("from", "to"):
                if edge[end] not in keys:
                    findings.append(_finding(
                        "broken-ref", GRAPH_FILE,
                        f"aresta {edge['from']} {edge.get('type')} {edge['to']}: {edge[end]} não existe",
                        "rode o coletor que declara a entidade (scan) ou corrija o coletor que aponta para ela"))
    atlas_root = os.path.normpath(os.path.abspath(files.atlas))
    for rel in sorted(r for r in files.texts if r.endswith(".md")):
        base = os.path.dirname(os.path.join(atlas_root, rel))
        for target in sorted({m.group(1) for m in LINK_RE.finditer(_without_code(files.texts[rel]))}):
            if EXTERNAL_LINK_RE.match(target):
                continue
            problem = _link_problem(atlas_root, base, target, files.problems)
            if problem:
                findings.append(_finding("broken-ref", rel, f"link para {_mask_path(target, extras)}: {problem}",
                                         "corrija o link ou crie a página; links são relativos à página e ficam "
                                         "dentro do atlas"))
    return findings


def _lint_conventions(files: _AtlasFiles, extras) -> list:
    findings = []
    for rel in sorted(r for r in files.texts if r.startswith(f"{CONVENTIONS_DIR}/") and r.endswith(".md")):
        head, _ = split_frontmatter(files.texts[rel])
        try:
            meta = parse_yaml(head) if head else {}
        except ValueError:
            meta = {}
        if str(meta.get("status") or "") == "inferred":
            cid = _mask_all(rel[len(CONVENTIONS_DIR) + 1:-3], extras)
            findings.append(_finding("pending-convention", rel, f"convenção {cid} esperando decisão (inferred)",
                                     LINT_SUGGESTIONS["pending-convention"].replace("<id>", cid)))
    return findings


def _lint_orphans(files: _AtlasFiles, stale_days, today) -> list:
    findings = []
    for rel in sorted(r for r in files.texts if r.startswith(f"{SERVICES_DIR}/") and r.endswith(".md")):
        found = NOT_SEEN_RE.match(page_regions(files.texts[rel]).get("summary", "").strip())
        days = _days_between(found.group(1), today) if found else None
        if days is not None and days > 2 * stale_days:
            findings.append(_finding("orphan-page", rel, f"não visto há {days} dias (desde {found.group(1)}; "
                                                         f"limite 2 × stale_days = {2 * stale_days})"))
    return findings


def _mask_all(text, extras) -> str:
    """text with every piece that matches a secret pattern (built-in or extra) masked."""
    return _redact_text(str(text), [regex for _, regex in extras])[0]


def _mask_path(path, extras) -> str:
    """path with each "/" component, and that component's stem without the extension, masked on its own: an
    anchored pattern (^...$) that matches a name is masked exactly as it is detected (_name_patterns)."""
    masked = []
    for part in str(path).split("/"):
        stem, ext = os.path.splitext(part)
        masked.append(_mask_all(_mask_all(stem, extras) + ext if stem else part, extras))
    return "/".join(masked)


def _mask_finding_path(finding, extras) -> str:
    """The path of a finding masked by _mask_path; the ":<line>" of secret-leak stays out of the last component."""
    path, line = finding["path"], ""
    if finding["rule"] == "secret-leak" and ":" in path and path.rsplit(":", 1)[1].isdigit():
        path, line = path.rsplit(":", 1)
        line = f":{line}"
    return _mask_path(path, extras) + line


def _finding_order(finding) -> tuple:
    path, line = finding["path"], 0
    if finding["rule"] == "secret-leak" and ":" in path:
        head, number = path.rsplit(":", 1)
        if number.isdigit():
            path, line = head, int(number)
    return (LINT_RULES.index(finding["rule"]), path, line, finding["detail"])


def run_lint(atlas: Path, rules=None, today=None) -> list:
    """Findings {rule, severity, path, detail, suggestion} of the rules (None = all), only reading the regular files
    of the atlas (references/maintenance.md). An unreadable file is a config finding and the lint goes on. No value
    of a secret ever shows: every text field is masked. Sorted by rule (report order), path, line and detail."""
    atlas = Path(atlas)
    rules = list(LINT_RULES) if rules is None else list(rules)
    today = today or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    files = _AtlasFiles(atlas)
    shared, problems, extras = _shared_problems(files)
    try:
        stale_days = _stale_days(shared)
    except AtlasError:
        stale_days = DEFAULT_STALE_DAYS  # check_shared already reported it
    declared, state = _scan_entries(files, shared)
    findings = []
    if "secret-leak" in rules:
        findings += _lint_secrets(files, extras)
    findings += _lint_collectors(declared, state, stale_days, today, rules, extras)
    if "broken-ref" in rules:
        findings += _lint_broken_refs(files, extras)
    if "pending-convention" in rules:
        findings += _lint_conventions(files, extras)
    if "orphan-page" in rules:
        findings += _lint_orphans(files, stale_days, today)
    if "config" in rules:  # last, after every JSON file was parsed and checked
        _graph_shape(files)
        for rel in sorted(r for r in files.texts if r.startswith(f"{SNAPSHOTS_DIR}/") and r.endswith(".json")):
            files.json(rel)
        findings += _lint_config(files, problems)
    for finding in findings:  # a path, id, key or link that looks like a secret is never shown either
        finding["path"] = _mask_finding_path(finding, extras)
        for key in ("detail", "suggestion"):
            finding[key] = _mask_all(finding[key], extras)
    return sorted(findings, key=_finding_order)


def lint_line(finding) -> str:
    label = "ERRO" if finding["severity"] == "error" else "AVISO"
    return f"{label} {finding['rule']} {finding['path']} — {finding['detail']} (sugestão: {finding['suggestion']})"


def _lint_atlas() -> Path:
    """The atlas folder, from the local configuration of this machine only (atlas-config.yml is read by run_lint,
    as one more file of the atlas). Without configuration = AtlasError (code 3)."""
    path = local_config_path()
    if not path.is_file():
        raise AtlasError(NOT_CONFIGURED, 3)
    try:
        local = parse_yaml(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        reason = e.strerror if isinstance(e, OSError) and e.strerror else "não é UTF-8"
        raise AtlasError(f"não consegui ler {path}: {reason}", 1) from None
    except ValueError as e:
        raise AtlasError(f"não consegui ler {path}: {_yaml_problem(e)}", 1) from None
    atlas = local.get("atlas")
    if not isinstance(atlas, str) or not atlas:
        raise AtlasError(f"atlas não definido em {path} — rode init (ou init --join)", 3)
    if not os.path.isdir(atlas):
        raise AtlasError(f"pasta do atlas não encontrada: {atlas} — rode init (ou init --join)", 3)
    return Path(atlas)


def cmd_lint(args):
    """lint [--json] [--only rule,...]: read-only (never writes to the atlas). Exit 0 without ERRO, 1 with ERRO,
    2 with an unknown rule in --only, 3 not configured. Messages on stderr are masked too."""
    try:
        rules = lint_rules(args.only)
        findings = run_lint(_lint_atlas(), rules)
    except AtlasError as e:
        raise AtlasError(_mask_all(e, []), e.code) from None
    except OSError as e:
        raise AtlasError(_mask_all(f"não consegui ler o atlas: {e.strerror or 'erro de leitura'}", []), 1) from None
    errors = sum(1 for x in findings if x["severity"] == "error")
    warnings = len(findings) - errors
    if args.json:
        print(json.dumps({"version": ATLAS_VERSION, "ok": errors == 0, "rules": rules, "errors": errors,
                          "warnings": warnings, "findings": findings}, ensure_ascii=False, indent=2))
    else:
        for finding in findings:
            print(lint_line(finding))
        print(f"{errors} erros, {warnings} avisos")
    return 1 if errors else 0


# ---------------------------------------------------------------- vendor (modo repo: scan agendado na CI)

CI_TARGETS = {"github": ("github-atlas-scan.yml", ".github/workflows/atlas-scan.yml"),
              "generic": ("atlas-scan.sh", "ci/atlas-scan.sh")}
SKILL_COPY = ".org-atlas/skill"  # the tool the CI runs: python3 .org-atlas/skill/scripts/atlas.py
DEFAULT_SCHEDULE = "0 6 * * 1"
LOCAL_ONLY = "vendor --ci é do modo repo — veja references/modes.md"
COPY_SKIPPED = ("__pycache__",)


def skill_files() -> list:
    """(relative path, source) of what the copy of the skill needs: scripts/atlas.py and every file of assets/
    (collectors, pages, models). Symlinks and caches are never copied."""
    files = [("scripts/atlas.py", Path(__file__).resolve())]
    for root, dirs, names in os.walk(ASSETS_DIR):
        dirs[:] = sorted(d for d in dirs if d not in COPY_SKIPPED and not os.path.islink(os.path.join(root, d)))
        for name in sorted(names):
            path = Path(root) / name
            if path.is_file() and not path.is_symlink() and not name.endswith(".pyc"):
                files.append((path.relative_to(SKILL_DIR).as_posix(), path))
    return files


def copy_skill(atlas: Path) -> int:
    """Copy the skill into <atlas>/.org-atlas/skill/, always overwritten (the CI runs this copy, never a customized
    one); returns how many files changed."""
    changed = 0
    for rel, source in skill_files():
        data, dest = source.read_bytes(), atlas / SKILL_COPY / rel
        if dest.is_file() and not dest.is_symlink() and dest.read_bytes() == data:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            dest.unlink()
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        if source.suffix in (".py", ".sh"):
            dest.chmod(0o755)
        changed += 1
    return changed


def render_workflow(names: list, schedule: str) -> str:
    """The GitHub Actions workflow from assets/ci/: the schedule and, in the Scan step only, one env entry per
    ci.env name, read from the secret of the same name (the value stays in the platform's vault)."""
    text = read_text(ASSETS_DIR / "ci" / CI_TARGETS["github"][0])
    env = "".join(f"          {name}: ${{{{ secrets.{name} }}}}\n" for name in names)
    return text.replace("__SCHEDULE__", schedule).replace("__ENV__", f"        env:\n{env}" if names else "")


def differing_lines(current: str, content: str) -> int:
    return sum(1 for line in difflib.unified_diff(current.splitlines(), content.splitlines(), lineterm="")
               if line[:1] in "+-" and line[:3] not in ("+++", "---"))


def put_file(atlas: Path, rel: str, content: str, force: bool, executable: bool = False) -> None:
    """Same file = "já atualizado"; different without --force = kept, with how many lines differ; else written."""
    dest = atlas / rel
    if dest.is_file():
        current = read_text(dest)
        if current == content:
            print(f"já atualizado: {rel}")
            return
        if not force:
            print(f"mantido: {rel} — customizado — {differing_lines(current, content)} linha(s) diferem; "
                  "use --force para sobrescrever")
            return
    elif dest.exists() or dest.is_symlink():
        raise AtlasError(f"não é um arquivo comum: {rel}", 2)
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(dest, content)
    if executable:
        dest.chmod(0o755)
    print(f"escrito: {rel}")


def cmd_vendor(args):
    """vendor --ci github|generic [--schedule CRON] [--force] (SPEC-0040): writes the CI files of the atlas of this
    machine and the copy of the skill they run; never runs git nor a platform CLI (ADR-0010). Everything is
    validated before the first write: mode local, an invalid ci or --schedule = exit 2."""
    atlas, shared = scan_config()
    if shared.get("mode") == "local":
        raise AtlasError(LOCAL_ONLY, 2)
    problems = check_shared(shared)
    if problems:
        raise AtlasError(f"atlas-config.yml inválido: {'; '.join(problems)}", 2)
    ci = shared.get("ci") if isinstance(shared.get("ci"), dict) else {}
    if args.schedule is not None and not valid_cron(args.schedule):
        raise AtlasError("--schedule precisa ser uma expressão cron de 5 campos (ex.: \"0 6 * * 1\")", 2)
    schedule = " ".join(str(args.schedule or ci.get("schedule") or DEFAULT_SCHEDULE).split())
    source, target = CI_TARGETS[args.ci]
    if args.ci == "github":
        content = render_workflow(ci_env_names(ci), schedule)
    else:
        content = read_text(ASSETS_DIR / "ci" / source)
    changed = copy_skill(atlas)
    print(f"{'atualizado' if changed else 'já atualizado'}: {SKILL_COPY}/ (cópia da skill, {ATLAS_VERSION})")
    put_file(atlas, target, content, args.force, executable=target.endswith(".sh"))
    if args.ci == "github":
        names = ci_env_names(ci)
        print(f"Agenda: {schedule} (UTC). Secrets esperados no repositório: {', '.join(names) or '(nenhum)'}")
    else:
        print(f"Na sua CI: rode `bash {target}` na raiz do atlas com as variáveis de ci.env; "
              "exit 0 sem mudança, 10 com mudança (abra o PR/MR), 1 com falha")
    print("Faça commit de .org-atlas/ e do arquivo da CI no atlas (o atlas.py não executa o git).")
    return 0


# ---------------------------------------------------------------- init

def backup_path(path: Path) -> Path:
    """atlas-config.yml.bak, or .bak.1, .bak.2... so an older backup is never overwritten."""
    candidate, n = path.with_name(path.name + ".bak"), 0
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.name}.bak.{n}")
    return candidate


def page_text(name: str, organization: str) -> str:
    return (PAGES_DIR / name).read_text(encoding="utf-8").replace("{organization}", organization)


def is_empty_folder(folder: Path) -> bool:
    return all(entry.name in IGNORED_IN_EMPTY for entry in folder.iterdir())


def create_structure(atlas: Path, organization: str, shared_text: str) -> list:
    """Create the atlas structure in an empty folder; returns what was created (relative names)."""
    atlas.mkdir(parents=True, exist_ok=True)
    created = []
    for name in STRUCTURE_PAGES:
        (atlas / name).write_text(page_text(name, organization), encoding="utf-8")
        created.append(name)
    (atlas / SHARED_FILE).write_text(shared_text, encoding="utf-8")
    created.append(SHARED_FILE)
    for name in STRUCTURE_DIRS:
        (atlas / name).mkdir(exist_ok=True)
        (atlas / name / KEEP_FILE).write_text("", encoding="utf-8")
        created.append(f"{name}/")
    return created


def join_atlas(atlas_path: str, local_path: Path) -> int:
    shared = Path(atlas_path) / SHARED_FILE
    if not shared.is_file():
        raise AtlasError(f"atlas sem atlas-config.yml — rode init: {shared}", 2)
    data = read_yaml(shared)
    credentials = existing_credentials(local_path)
    write_local_config(local_path, render_local_config(atlas_path, credentials))
    print(f"Máquina ligada ao atlas em {atlas_path} ({data.get('organization', '')}, modo {data.get('mode', '')})")
    print(f"Configuração local: {local_path}")
    return 0


def cmd_init(args):
    """init (new atlas, same configuration again, --force with .bak) or init --join (only the local layer).
    Everything is validated before the first write; credentials already declared on this machine are kept."""
    atlas_path = absolute(args.atlas)
    local_path = local_config_path()
    if args.join:
        extra = [flag for flag, given in (("--org", args.org), ("--mode", args.mode), ("--force", args.force))
                 if given]
        if extra:
            raise AtlasError(f"init --join não aceita {', '.join(extra)}: a organização e o modo vêm do "
                             "atlas-config.yml do atlas", 2)
        return join_atlas(atlas_path, local_path)
    if not args.org or not args.mode:
        raise AtlasError("init precisa de --org NOME e --mode repo|local (ou --join para um atlas existente)", 2)
    shared_text = render_atlas_config(args.org, args.mode)
    credentials = existing_credentials(local_path)
    atlas = Path(atlas_path)
    shared = atlas / SHARED_FILE
    if atlas.exists() and not atlas.is_dir():
        raise AtlasError(f"não é uma pasta: {atlas_path}", 2)
    local_text = render_local_config(atlas_path, credentials)

    if shared.is_file():
        current = read_text(shared)
        if current == shared_text:
            write_local_config(local_path, local_text)
            print(f"Atlas já configurado em {atlas_path}")
            print(f"Configuração local: {local_path}")
            return 0
        if not args.force:
            raise AtlasError("atlas-config.yml já existe — use --join ou --force", 2)
        backup = backup_path(shared)
        backup.write_text(current, encoding="utf-8")
        shared.write_text(shared_text, encoding="utf-8")
        write_local_config(local_path, local_text)
        print(f"atlas-config.yml substituído em {atlas_path} (anterior em {backup.name})")
        print(f"Configuração local: {local_path}")
        return 0

    if atlas.is_dir() and not is_empty_folder(atlas):
        raise AtlasError(f"pasta não está vazia — escolha outra pasta: {atlas_path}", 2)
    created = create_structure(atlas, args.org.strip(), shared_text)
    write_local_config(local_path, local_text)
    print(f"Atlas criado em {atlas_path} (modo {args.mode})")
    for name in created:
        print(f"  {name}")
    print(f"Configuração local: {local_path}")
    if args.mode == "local":
        print("Próximo passo: git init na pasta do atlas (o atlas.py não executa o git).")
    return 0


# ---------------------------------------------------------------- config

def describe(value) -> str:
    return fmt_flow(value) if isinstance(value, (dict, list)) else fmt_scalar(value)


def cmd_config(as_json):
    config = load_config()
    if as_json:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0
    values, origins = config["values"], config["origins"]
    print(f"org-atlas {ATLAS_VERSION} — configuração local: {local_config_path()}")
    for key in LOCAL_KEYS + SHARED_KEYS:
        if key == "credentials" and values[key]:
            print(f"credentials: ({origins[key]})")
            for collector, entry in values[key].items():
                entry = entry if isinstance(entry, dict) else {}
                parts = [f"env {', '.join(env_names(entry))}"] if env_names(entry) else []
                parts += [f"profile {entry['profile']}"] if entry.get("profile") else []
                print(f"  {collector}: {'; '.join(parts) or '(nada declarado)'}")
            continue
        print(f"{key}: {describe(values[key])} ({origins[key]})")
    return 0


# ---------------------------------------------------------------- doctor

def check_shared(data: dict) -> list:
    """Problems of atlas-config.yml: version, required keys and their shape, absolute paths."""
    problems = []
    missing = [key for key in REQUIRED_SHARED if data.get(key) in (None, "")]
    if missing:
        problems.append(f"faltam chaves: {', '.join(missing)}")
    if "version" in data and str(data["version"]) != SHARED_VERSION:
        problems.append(f"version {data['version']} não suportada (esta skill usa {SHARED_VERSION})")
    if data.get("mode") not in (None, "") and data["mode"] not in MODES:
        problems.append(f"mode inválido: {data['mode']} — use um de: {' | '.join(MODES)}")
    if "stale_days" in data and not re.match(r"^\d+$", str(data["stale_days"])):
        problems.append(f"stale_days precisa ser um número inteiro de dias: {data['stale_days']}")
    for key in ("categories", "collectors"):
        if key in data and not isinstance(data[key], list):
            problems.append(f"{key} precisa ser uma lista")
    if "redaction" in data and not isinstance(data["redaction"], dict):
        problems.append("redaction precisa ser um mapa")
    if "curation" in data:
        if not isinstance(data["curation"], dict):
            problems.append("curation precisa ser um mapa {min_share, min_total, min_repos}")
        else:
            try:
                curation_settings(data["curation"])
            except AtlasError as e:
                problems.append(str(e))
    if "ci" in data:
        try:
            validate_ci(data["ci"])
        except AtlasError as e:
            problems.append(str(e))
    problems += [f"caminho absoluto em {key}" for key, _ in absolute_values(data)]
    return problems


def collector_checks(collectors) -> list:
    """One row per declared collector: its executable (command[0]) found or not, with shutil.which only."""
    rows = []
    for index, item in enumerate(collectors if isinstance(collectors, list) else []):
        item = item if isinstance(item, dict) else {}
        name = item.get("id") or f"#{index + 1}"
        command = item.get("command")
        if not isinstance(command, list) or not command or not command[0]:
            rows.append(("ERRO", f"coletor {name}", "sem command (lista com o executável e os argumentos)"))
            continue
        executable = str(command[0]).replace("{skill}", str(SKILL_DIR))
        if shutil.which(executable):
            rows.append(("OK", f"coletor {name}", f"executável {command[0]} encontrado"))
        else:
            rows.append(("ERRO", f"coletor {name}", f"executável {command[0]} não encontrado no PATH"))
    return rows


def credential_checks(credentials) -> list:
    """One row per declared variable ("definida" | "não definida", looking only at the name in os.environ) and
    per profile (only the name: the atlas.py never reads a profile)."""
    rows = []
    for collector, entry in (credentials or {}).items():
        for name in env_names(entry):
            if name in os.environ:
                rows.append(("OK", f"credencial {collector} {name}", "definida"))
            else:
                rows.append(("AVISO", f"credencial {collector} {name}", "não definida"))
        profile = entry.get("profile") if isinstance(entry, dict) else None
        if profile:
            rows.append(("OK", f"credencial {collector} profile", f"{profile} (só o nome; não é verificado)"))
    return rows


def atlas_checks(atlas: Path) -> tuple:
    """(rows, shared) for atlas-config.yml, the structure and git of an existing atlas folder."""
    rows, shared = [], None
    shared_path = atlas / SHARED_FILE
    if not shared_path.is_file():
        rows.append(("ERRO", "atlas-config.yml", f"não existe em {atlas} — rode init"))
    else:
        try:
            shared = read_yaml(shared_path)
        except AtlasError as e:
            rows.append(("ERRO", "atlas-config.yml", str(e)))
    if shared is not None:
        problems = check_shared(shared)
        if problems:
            rows.append(("ERRO", "atlas-config.yml", "; ".join(problems)))
        else:
            rows.append(("OK", "atlas-config.yml",
                         f"versão {shared['version']}, {shared['organization']}, modo {shared['mode']}"))

    missing = [f"{n}/" for n in STRUCTURE_DIRS if not (atlas / n).is_dir()]
    missing += [n for n in STRUCTURE_PAGES if not (atlas / n).is_file()]
    if missing:
        rows.append(("ERRO", "estrutura", f"faltam: {', '.join(missing)}"))
    else:
        rows.append(("OK", "estrutura", ", ".join(STRUCTURE_PAGES + tuple(f"{n}/" for n in STRUCTURE_DIRS))))

    if (atlas / ".git").exists():  # a folder (repository) or a file (worktree, submodule)
        rows.append(("OK", "git", "a pasta é um repositório git"))
    else:
        rows.append(("AVISO", "git", ("a pasta não é um repositório git — rode git init (modo local) ou clone o "
                                      "repositório do atlas (modo repo)")))
    return rows, shared


def doctor_rows(config_home=None) -> list:
    """(status, item, detail) for each item of the contract; raises AtlasError(NOT_CONFIGURED, 3) without the
    local layer. Never runs a process and never prints a variable's value."""
    path, local = read_local(config_home)
    rows = []
    credentials = local.get("credentials")
    try:
        validate_credentials(credentials)
        rows.append(("OK", "configuração local", str(path)))
    except AtlasError as e:
        rows.append(("ERRO", "configuração local", f"{e} ({path})"))
        credentials = {}
    atlas = local.get("atlas")
    if not isinstance(atlas, str) or not atlas:
        rows.append(("ERRO", "pasta do atlas", f"atlas não definido em {path} — rode init (ou init --join)"))
        return rows + credential_checks(credentials)
    if not Path(atlas).is_absolute():
        detail = f"caminho relativo: {atlas} — use o caminho absoluto em {path} (ou rode init --join)"
        rows.append(("ERRO", "pasta do atlas", detail))
        return rows + credential_checks(credentials)
    try:
        if not Path(atlas).is_dir():
            rows.append(("ERRO", "pasta do atlas", f"não existe: {atlas}"))
            return rows + credential_checks(credentials)
        found, shared = atlas_checks(Path(atlas))
    except OSError as e:
        rows.append(("ERRO", "pasta do atlas", f"não consegui ler {atlas}: {e.strerror or e}"))
        return rows + credential_checks(credentials)
    rows.append(("OK", "pasta do atlas", atlas))
    rows += found + collector_checks((shared or {}).get("collectors"))
    return rows + credential_checks(credentials)


def cmd_doctor(as_json):
    rows = doctor_rows()
    has_error = any(status == "ERRO" for status, _, _ in rows)
    if as_json:
        checks = [{"status": s, "item": i, "detail": d} for s, i, d in rows]
        print(json.dumps({"version": ATLAS_VERSION, "ok": not has_error, "checks": checks},
                         ensure_ascii=False, indent=2))
    else:
        for status, item, detail in rows:
            print(f"{status} {item} — {detail}")
    return 1 if has_error else 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="atlas.py", description="Ferramentas determinísticas do org-atlas.")
    parser.add_argument("--version", action="version", version=f"org-atlas {ATLAS_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init", help="cria um atlas novo ou só liga esta máquina (--join)")
    p.add_argument("--atlas", required=True, help="pasta do atlas")
    p.add_argument("--org", help="nome da organização")
    p.add_argument("--mode", help="repo | local")
    p.add_argument("--force", action="store_true", help="substitui atlas-config.yml diferente (anterior em .bak)")
    p.add_argument("--join", action="store_true", help="atlas já configurado: grava só a configuração local")
    p = sub.add_parser("config", help="configuração efetiva e a origem de cada valor (local | atlas | padrão)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("doctor", help="o que está configurado, o que funciona e o que falta")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("scan", help="roda os coletores, valida, mascara, grava snapshots/ e mostra o diff")
    p.add_argument("--only", help="ids dos coletores separados por vírgula")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("build", help="junta os snapshots no graph.json, infere relações e gera as páginas")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("lint", help="só lê e aponta o que precisa de atenção no atlas (segredos, coletores, referências)")
    p.add_argument("--only", help="regras separadas por vírgula")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("context", help="pacote só de leitura do atlas para uma tarefa (serviços, dependências, convenções)")
    p.add_argument("query", nargs="+", help="termos da tarefa")
    p.add_argument("--hops", type=int, default=1, help="passos no grafo a partir dos serviços encontrados (0..2)")
    p.add_argument("--limit", type=int, default=8, help="quantos serviços no máximo")
    p.add_argument("--max-chars", type=int, default=30000, help="tamanho máximo do pacote")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("curate", help="propõe convenções (inferred) e registra a decisão humana (confirm | reject)")
    curate = p.add_subparsers(dest="action", required=True)
    q = curate.add_parser("propose", help="cria ou atualiza conventions/<id>.md a partir dos sinais")
    q.add_argument("--json", action="store_true")
    q = curate.add_parser("list", help="convenções e o status de cada uma")
    q.add_argument("--status", choices=("inferred", "confirmed", "rejected"))
    q.add_argument("--json", action="store_true")
    for action in ("confirm", "reject"):
        q = curate.add_parser(action, help=f"{action}: decisão humana sobre uma convenção (exige --by e --via)")
        q.add_argument("id")
        q.add_argument("--by", help="quem decide")
        q.add_argument("--via", help="'PR #<n>' ou 'local'")
        if action == "reject":
            q.add_argument("--reason", help="motivo (opcional)")
    p = sub.add_parser("vendor", help="modo repo: instala no atlas o scan agendado da CI e a cópia da skill que ela roda")
    p.add_argument("--ci", required=True, choices=tuple(CI_TARGETS), help="github (GitHub Actions) | generic (script)")
    p.add_argument("--schedule", help="agenda cron (padrão: ci.schedule, senão \"0 6 * * 1\")")
    p.add_argument("--force", action="store_true", help="sobrescreve o arquivo da CI customizado")
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            return cmd_init(args)
        if args.command == "config":
            return cmd_config(args.json)
        if args.command == "doctor":
            return cmd_doctor(args.json)
        if args.command == "scan":
            return cmd_scan(args.only, args.json)
        if args.command == "build":
            return cmd_build(args.json)
        if args.command == "lint":
            return cmd_lint(args)
        if args.command == "context":
            return cmd_context(args)
        if args.command == "curate":
            return cmd_curate(args)
        if args.command == "vendor":
            return cmd_vendor(args)
    except AtlasError as e:
        print(f"erro: {e}", file=sys.stderr)
        return e.code
    except OSError as e:  # permission, read-only disk...: a clear message, never a traceback
        print(f"erro: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
