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
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ATLAS_VERSION = "2026.10.2"
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
    if as_json:
        print(json.dumps({"version": ATLAS_VERSION, "ok": not failed, "collectors": reports},
                         ensure_ascii=False, indent=2))
    else:
        print_scan(reports)
    return 1 if failed else 0


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
    except AtlasError as e:
        print(f"erro: {e}", file=sys.stderr)
        return e.code
    except OSError as e:  # permission, read-only disk...: a clear message, never a traceback
        print(f"erro: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
