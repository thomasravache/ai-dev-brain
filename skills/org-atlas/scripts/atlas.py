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
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
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
               "redaction")
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
ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
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
            if hasattr(pattern, "subn"):
                compiled.append(pattern)
                continue
            if not isinstance(pattern, str) or not pattern:
                raise AtlasError(f"redaction.extra_patterns[{index}] precisa ser uma regex (texto não vazio)", 2)
            try:
                regex = re.compile(pattern)
            except re.error as e:
                raise AtlasError(f"redaction.extra_patterns[{index}] não é uma regex válida: {e}", 2) from e
            if regex.search("") is not None:  # would insert [REDACTED] between every character
                raise AtlasError(f"redaction.extra_patterns[{index}] casa com o texto vazio — "
                                 "exija ao menos um caractere", 2)
            compiled.append(regex)
        _EXTRA_CACHE[key] = compiled
    return _EXTRA_CACHE[key]


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
    failed = failed or not build["ok"]
    if as_json:
        print(json.dumps({"version": ATLAS_VERSION, "ok": not failed, "collectors": reports, "build": build},
                         ensure_ascii=False, indent=2))
    else:
        print_scan(reports)
        if build["ok"]:
            print_build(build)
        else:
            print(f"erro no build: {build['error']}", file=sys.stderr)
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


# ---------------------------------------------------------------- curate (conventions)

def propose_conventions(signals: list, curation=None) -> list:
    raise NotImplementedError("SPEC-0037: propose_conventions")


def cmd_curate(args):
    raise NotImplementedError("SPEC-0037: curate")


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
        if args.command == "curate":
            return cmd_curate(args)
    except AtlasError as e:
        print(f"erro: {e}", file=sys.stderr)
        return e.code
    except OSError as e:  # permission, read-only disk...: a clear message, never a traceback
        print(f"erro: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
