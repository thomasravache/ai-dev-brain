#!/usr/bin/env python3
"""Deterministic tooling for the boson-atlas skill, formerly org-atlas (stdlib only, Python 3.9+). Run with --help.

Two configuration layers (ADR-0010): the local one, per machine, in $ATLAS_CONFIG_HOME/config.yml (atlas path and
credential names, never values) and the shared one, in <atlas>/atlas-config.yml (never an absolute path).
The local layer may hold several named atlases (`default:` + `atlases:`, ADR-0021); every command but init uses the
one chosen by select_atlas (--atlas, ATLAS_NAME, default, the only one) and only its credentials (SPEC-0079).
init creates the atlas structure from assets/ (or, with --join, only the local layer); config shows the effective
configuration with the origin of each value; doctor reports what is configured, what works and what is missing,
looking only at files, shutil.which and os.environ (never at a variable's value).
run_collector is the only function allowed to run an external process (SPEC-0033); it also runs the probe
adapters of `probe` (SPEC-0088, ADR-0023: off by default, allowed verbs, confirmed production, local log), also
the only route of `verify` (SPEC-0090, ADR-0024: snapshot outside the atlas, compare with a verdict).
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import hashlib
import json
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

ATLAS_VERSION = "2026.11.27"
SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets"
DEFAULT_SHARED_CONFIG = ASSETS_DIR / "atlas-config.yml"
PAGES_DIR = ASSETS_DIR / "pages"

SHARED_FILE = "atlas-config.yml"
MODES = ("repo", "local")
LOCAL_KEYS = ("atlas", "credentials", "access", "probes")
SHARED_KEYS = ("version", "organization", "mode", "language", "stale_days", "categories", "collectors",
               "redaction", "curation", "ci", "remotes", "image_repositories", "environments")
REQUIRED_SHARED = ("version", "organization", "mode")
SHARED_VERSION = "1"
STRUCTURE_DIRS = ("services", "platform", "conventions", "process", "snapshots")
STRUCTURE_PAGES = ("ATLAS.md", "glossary.md")  # copied from assets/pages/
KEEP_FILE = ".gitkeep"  # keeps the empty folders in a git repository (mode repo)
IGNORED_IN_EMPTY = (".git", ".DS_Store", "Thumbs.db", "desktop.ini")  # an "empty" folder may have them
ORIGIN_LOCAL, ORIGIN_ATLAS, ORIGIN_DEFAULT = "local", "atlas", "padrão"
NOT_CONFIGURED = "boson-atlas não configurado nesta máquina — rode init (ou init --join)"
LOCAL_HEADER = ("# boson-atlas — configuração local desta máquina (references/config.md). Não vai para o atlas.\n"
                "# credentials: só NOMES de variável de ambiente e de profile, nunca valores.\n")
# Local configuration folders under ~/.config (SPEC-0070, ADR-0020): the new one is read first and is the only one
# written; the old one is read as a fallback until its removal (SPEC-0073) and is never written, moved nor deleted.
CONFIG_DIR = "boson-atlas"
OLD_CONFIG_DIR = "org-atlas"
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


def _block_key(content: str):
    """(key, rest) of a `key: value` line, the key bare or between quotes ("acme/api": x or "acme/api" : x,
    SPEC-0082); else None."""
    if content[:1] in "\"'":
        try:
            key, end = _quoted(content, 0)
        except ValueError:
            return None
        rest = content[end:].lstrip(" \t")  # "acme/x" : acme/y also reads (SPEC-0082, Emenda v3)
        if rest == ":" or rest.startswith(": "):
            return key, rest[1:].strip()
        return None
    pair = KEY_RE.match(content)
    return (pair.group(1).strip(), (pair.group(2) or "").strip()) if pair else None


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
        pair = _block_key(rows[i][1])
        i += 1
        if not pair:
            continue
        key, rest = pair
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
        if ":" in name and not name.startswith('"'):  # a key like https://host: parse_yaml reads it back quoted
            name = json.dumps(str(key), ensure_ascii=False)
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

def config_override(config_home=None):
    """config_home, else $ATLAS_CONFIG_HOME, as a Path; None when neither is given (the default folders apply)."""
    if config_home:
        return Path(config_home)
    if os.environ.get("ATLAS_CONFIG_HOME"):
        return Path(os.environ["ATLAS_CONFIG_HOME"])
    return None


def default_config_path(name: str = CONFIG_DIR) -> Path:
    return Path.home() / ".config" / name / "config.yml"


def local_config_path(config_home=None) -> Path:
    """Where the local configuration is read (SPEC-0070): config_home or $ATLAS_CONFIG_HOME (no fallback), else the
    first existing of ~/.config/boson-atlas/config.yml and ~/.config/org-atlas/config.yml (fallback until
    SPEC-0073), else ~/.config/boson-atlas/config.yml (not configured)."""
    override = config_override(config_home)
    if override is not None:
        return override / "config.yml"
    for name in (CONFIG_DIR, OLD_CONFIG_DIR):
        path = default_config_path(name)
        if path.is_file():
            return path
    return default_config_path()


def local_config_write_path(config_home=None) -> Path:
    """Where the local configuration is written: config_home or $ATLAS_CONFIG_HOME, else always
    ~/.config/boson-atlas/config.yml; the old folder is never written (SPEC-0070, ADR-0020)."""
    override = config_override(config_home)
    return override / "config.yml" if override is not None else default_config_path()


def old_config_items(config_home=None) -> list:
    """doctor AVISO about the old default folder (none with an override): only the old one exists -> the copy
    command; both exist -> the old one is ignored (SPEC-0070)."""
    if config_override(config_home) is not None or not default_config_path(OLD_CONFIG_DIR).is_file():
        return []
    old, new = f"~/.config/{OLD_CONFIG_DIR}", f"~/.config/{CONFIG_DIR}"
    if default_config_path().is_file():
        return [("AVISO", f"{old} é ignorada (vale {new})", "pode apagá-la")]
    return [("AVISO", f"configuração no caminho antigo {old}",
             f"copie com: mkdir -p {new} && cp -p {old}/config.yml {new}/")]


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


def render_atlas_config(organization, mode, remotes=None) -> str:
    """Text of the atlas-config.yml that init writes: assets/atlas-config.yml with its comments; only
    organization and mode change, plus `remotes:` at the end when init --remote is given (SPEC-0080). Never holds
    an absolute path."""
    validate_mode(mode)
    remotes = validate_remotes(remotes)
    organization = str(organization or "").strip()
    if not organization:
        raise AtlasError("organização vazia — passe --org NOME", 2)
    if ABSOLUTE_RE.match(organization):
        raise AtlasError("organization não pode ser um caminho absoluto", 2)
    text = DEFAULT_SHARED_CONFIG.read_text(encoding="utf-8")
    expected = dict(parse_yaml(text), organization=organization, mode=mode)
    text = _set_value(_set_value(text, "organization", organization), "mode", mode)
    if remotes:
        expected["remotes"] = remotes
        text = text.rstrip("\n") + "\nremotes:\n" + "".join(f"  - {fmt_scalar(item)}\n" for item in remotes)
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


SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")  # https://, ssh://, git+ssh://
REMOTES_HINT = "use host/caminho, como github.com/acme"


def is_control(c: str) -> bool:
    """C0 (below 0x20), DEL and C1 (0x7f to 0x9f) control characters (SPEC-0080, Emenda v3 item 13)."""
    return ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F


def remote_item_problem(item):
    """Reason why an item of `remotes:` is not a lowercase host/path prefix, the first that applies (SPEC-0080,
    Emenda v5 item 17), or None for a valid item. The reason is fixed text and never quotes the item (item 16)."""
    if not isinstance(item, str):
        return "não é texto"
    if not item:
        return "vazio"
    if SCHEME_RE.match(item):
        return "tem esquema (ex.: https://)"
    if "@" in item:
        return "tem credenciais (@)"
    if any(c in item for c in "?#="):
        return "tem ? , # ou ="
    if ":" in item:
        return "tem : (porta ou formato scp)"
    if any(is_control(c) or c.isspace() for c in item):
        return "tem espaço ou caractere de controle"
    if item != item.lower():
        return "tem maiúsculas"
    if (item.startswith(("/", "~")) or item.endswith("/") or "\\" in item or ".." in item
            or any(segment in ("", ".", "..") for segment in item.split("/"))):
        return "tem barra no início ou no fim, // ou segmento . ou .."
    return None


def validate_remotes(remotes) -> list:
    """remotes = [host/path, ...] of atlas-config.yml (SPEC-0080): the list, or AtlasError (code 2) with the
    position (from 1) and the reason of the first invalid item, never its text (Emenda v5)."""
    if remotes in ("", None):
        return []
    if not isinstance(remotes, list):
        raise AtlasError("remotes precisa ser uma lista de prefixos host/caminho (ex.: [github.com/acme])", 2)
    for position, item in enumerate(remotes, start=1):
        reason = remote_item_problem(item)
        if reason:  # position and reason only: no text of the item, masked or not (Emenda v5, item 16)
            raise AtlasError(f"remotes: item {position} inválido — {reason}; {REMOTES_HINT}", 2)
    return list(remotes)


# a normalized image path (the argocd collector's rule) and a <owner>/<repository> (SPEC-0082)
IMAGE_PATH_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*\Z")
IMAGE_REPOSITORIES_HINT = 'use "<imagem>": <dono>/<repositório>, como "acme/legacy-api": acme/api-v1'


def _image_name_problem(text, what):
    """Reason why `text` (an image path or a repository) does not follow the name rule, or None. Fixed text that
    never quotes the item (SPEC-0082, the rule of SPEC-0080)."""
    if not isinstance(text, str):
        return f"{what} não é texto"
    if not text:
        return f"{what} vazio"
    if SCHEME_RE.match(text):
        return f"{what} tem esquema (ex.: https://)"
    if "@" in text:
        return f"{what} tem @"
    if any(is_control(c) or c.isspace() for c in text):
        return f"{what} tem espaço ou caractere de controle"
    if text != text.lower():
        return f"{what} tem maiúsculas"
    if not IMAGE_PATH_RE.match(text):
        return f"{what} fora da regra de nome (letras minúsculas, dígitos, . _ - e / entre segmentos)"
    return None


def image_repository_item_problem(image, repository):
    """Reason why an item of `image_repositories:` is invalid, the first that applies (the image, then the
    repository, which needs exactly one "/"), or None."""
    reason = _image_name_problem(image, "a imagem") or _image_name_problem(repository, "o repositório")
    if reason:
        return reason
    if repository.count("/") != 1:
        return "o repositório precisa ser <dono>/<nome> (exatamente uma /)"
    return None


def validate_image_repositories(mapping) -> dict:
    """image_repositories = {<normalized image>: <owner>/<repository>} of atlas-config.yml (SPEC-0082): the map, or
    AtlasError (code 2) with the position (from 1) and the reason of the first invalid item, never its text."""
    if mapping in ("", None):
        return {}
    if not isinstance(mapping, dict):
        raise AtlasError(f"image_repositories precisa ser um mapa — {IMAGE_REPOSITORIES_HINT}", 2)
    for position, (image, repository) in enumerate(mapping.items(), start=1):
        reason = image_repository_item_problem(image, repository)
        if reason:  # position and reason only: no text of the item, masked or not
            raise AtlasError(f"image_repositories: item {position} inválido — {reason}; {IMAGE_REPOSITORIES_HINT}", 2)
    return dict(mapping)


# the tier of an environment (SPEC-0087, ADR-0023): an environment without one counts as production for consumers
TIERS = ("test", "production")
# the simple name rule of an environment of the graph: letters, digits, . _ - (no space, no "/")
ENVIRONMENT_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\Z")
ENVIRONMENTS_HINT = "use <ambiente>: {tier: test} ou {tier: production}, como dev: {tier: test}"


def environment_item_problem(name, value):
    """Reason why an item of `environments:` is invalid, the first that applies (the name, the value, the tier), or
    None. Fixed text that never quotes the item (the rule of SPEC-0080 and SPEC-0082)."""
    if not isinstance(name, str) or not ENVIRONMENT_NAME_RE.match(name):
        return "o nome do ambiente está fora da regra de nome (letras, dígitos, . _ -, sem espaço)"
    if not isinstance(value, dict):
        return "o valor precisa ser um mapa {tier: test | production}"
    unknown = [key for key in value if key != "tier"]
    if unknown:
        return "o mapa aceita só a chave tier"
    if value.get("tier") not in TIERS:
        return "tier precisa ser test ou production"
    return None


def validate_environments(mapping) -> dict:
    """environments = {<environment>: {tier: test | production}} of atlas-config.yml (SPEC-0087): {environment:
    tier}, or AtlasError (code 2) with the position (from 1) and the reason of the first invalid item, never its
    text."""
    if mapping in ("", None):
        return {}
    if not isinstance(mapping, dict):
        raise AtlasError(f"environments precisa ser um mapa — {ENVIRONMENTS_HINT}", 2)
    for position, (name, value) in enumerate(mapping.items(), start=1):
        reason = environment_item_problem(name, value)
        if reason:  # position and reason only: no text of the item
            raise AtlasError(f"environments: item {position} inválido — {reason}; {ENVIRONMENTS_HINT}", 2)
    return {name: value["tier"] for name, value in mapping.items()}


ACCESS_TEXT_MAX = 256
ACCESS_HINT = "use access: {clusters: {<cluster>: {context: <nome do contexto do kubeconfig>}}}"
ACCESS_DEFINED = "definido"  # what config shows instead of a context: only that it exists
# the blocks of the local `access` (SPEC-0087 clusters; SPEC-0096 cloud, databases and urls), in this order
ACCESS_BLOCKS = ("clusters", "cloud", "databases", "urls")
ACCESS_HINTS = {
    "clusters": ACCESS_HINT,
    "cloud": "use access: {cloud: {<ambiente>: {profile: <nome do profile>}}}",
    "databases": "use access: {databases: {<datastore>: {user: <usuário>, database: <banco>, passfile: <caminho>}}}",
    "urls": "use access: {urls: {<ambiente>: {base_url: <https://…>}}}",
}
# the fields of an item of each block: (key, what the message calls it), all required (SPEC-0096)
ACCESS_FIELDS = {"cloud": (("profile", "o profile"),),
                 "databases": (("user", "o usuário"), ("database", "o banco"), ("passfile", "o arquivo de senhas")),
                 "urls": (("base_url", "a URL base"),)}
ACCESS_NAMES = {"cloud": "o nome do ambiente", "databases": "o id do datastore", "urls": "o nome do ambiente"}
BASE_URL_MAX = 2048


def _access_text_problem(text, what):
    """Reason why `text` is not a text of 1 to 256 characters without a line break (or another control character),
    or None. Never quotes the text."""
    if not isinstance(text, str):
        return f"{what} não é texto"
    if not text:
        return f"{what} vazio"
    if len(text) > ACCESS_TEXT_MAX:
        return f"{what} com mais de {ACCESS_TEXT_MAX} caracteres"
    if any(is_control(c) for c in text):
        return f"{what} com quebra de linha ou caractere de controle"
    return None


def _base_url_problem(url):
    """Reason why a base URL of access.urls is not an absolute http(s) URL without user or password, without
    space nor control character (SPEC-0096), or None. Never quotes the URL."""
    what = "a URL base"
    if not isinstance(url, str):
        return f"{what} não é texto"
    if not url:
        return f"{what} vazio"
    if len(url) > BASE_URL_MAX:
        return f"{what} com mais de {BASE_URL_MAX} caracteres"
    if any(is_control(c) for c in url):
        return f"{what} com quebra de linha ou caractere de controle"
    if any(c.isspace() for c in url):
        return f"{what} com espaço"
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        return f"{what} precisa ser http ou https absoluta"
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return f"{what} precisa ser http ou https absoluta"
    if "@" in parts.netloc:
        return f"{what} com usuário ou senha"
    if not host:
        return f"{what} precisa ser http ou https absoluta"
    return None


def _access_item_problem(block, name, entry):
    """Reason why one item of access.cloud, access.databases or access.urls is invalid (the first that applies), or
    None. Fixed text: never the name nor a value."""
    if not isinstance(name, str):
        return f"{ACCESS_NAMES[block]} não é texto"
    if not ENVIRONMENT_NAME_RE.match(name):
        return f"{ACCESS_NAMES[block]} fora da regra de nome"
    fields = ACCESS_FIELDS[block]
    keys = [key for key, _ in fields]
    if not isinstance(entry, dict):
        return "o valor precisa ser um mapa"
    if any(key not in keys for key in entry):
        return f"o mapa aceita só {_join_names(keys)}"
    for key in keys:
        if key not in entry:
            return f"falta {key}"
    for key, what in fields:
        value = entry[key]
        if key == "base_url":
            reason = _base_url_problem(value)
        else:
            reason = _access_text_problem(value, what)
            if reason is None and value.startswith("-"):
                reason = f"{what} começa com -"
            if reason is None and key == "passfile" and not (os.path.isabs(value) or value.startswith("~/")):
                reason = f"{what} precisa ser absoluto ou começar com ~/"
        if reason:
            return reason
    return None


def _join_names(names) -> str:
    names = list(names)
    if len(names) == 1:
        return f"a chave {names[0]}"
    return f"as chaves {', '.join(names[:-1])} e {names[-1]}"


def _clusters_access(clusters) -> dict:
    if clusters in ("", None):
        return {}
    if not isinstance(clusters, dict):
        raise AtlasError(f"access.clusters precisa ser um mapa — {ACCESS_HINT}", 2)
    for position, (cluster, entry) in enumerate(clusters.items(), start=1):
        reason = _access_text_problem(cluster, "o nome do cluster")
        if reason is None:
            if not isinstance(entry, dict):
                reason = "o valor precisa ser um mapa {context: <nome do contexto>}"
            elif any(key != "context" for key in entry):
                reason = "o mapa aceita só a chave context"
            else:
                reason = _access_text_problem(entry.get("context"), "o contexto")
        if reason:  # position and reason only: never the cluster nor the context
            raise AtlasError(f"access.clusters: item {position} inválido — {reason}; {ACCESS_HINT}", 2)
    return {str(cluster): entry["context"] for cluster, entry in clusters.items()}


def local_access(access) -> dict:
    """The local `access` of one entry (SPEC-0087, SPEC-0096), normalized: {"clusters": {cluster: context},
    "cloud": {environment: profile}, "databases": {datastore: {"user", "database", "passfile"}}, "urls":
    {environment: base_url}} (each block {} without it), or AtlasError (code 2) "access.<bloco>: item N inválido —
    <motivo>" with the position (from 1) and the reason of the first invalid item. No value is ever printed, not
    even in an error; the passfile is kept as written (expand it with expand_passfile)."""
    result = {block: {} for block in ACCESS_BLOCKS}
    if access in ("", None):
        return result
    if not isinstance(access, dict) or any(key not in ACCESS_BLOCKS for key in access):
        raise AtlasError("access aceita só as chaves clusters, cloud, databases e urls — "
                         f"{ACCESS_HINT}; {ACCESS_HINTS['cloud']}", 2)
    result["clusters"] = _clusters_access(access.get("clusters"))
    for block in ("cloud", "databases", "urls"):
        items = access.get(block)
        if items in ("", None):
            continue
        if not isinstance(items, dict):
            raise AtlasError(f"access.{block} precisa ser um mapa — {ACCESS_HINTS[block]}", 2)
        for position, (name, entry) in enumerate(items.items(), start=1):
            reason = _access_item_problem(block, name, entry)
            if reason:  # position and reason only: never the name nor a value
                raise AtlasError(f"access.{block}: item {position} inválido — {reason}; {ACCESS_HINTS[block]}", 2)
        if block == "cloud":
            result[block] = {name: entry["profile"] for name, entry in items.items()}
        elif block == "urls":
            result[block] = {name: entry["base_url"] for name, entry in items.items()}
        else:
            result[block] = {name: {key: entry[key] for key in ("user", "database", "passfile")}
                             for name, entry in items.items()}
    return result


def validate_access(access) -> dict:
    """{cluster: context} of the local `access` (SPEC-0087), after validating every block (local_access): an
    invalid item of any block = AtlasError (code 2). The context is a name of this machine's kubeconfig and is
    never printed, not even in an error."""
    return local_access(access)["clusters"]


def expand_passfile(path: str) -> str:
    """The passfile of access.databases as the tool reads it: "~/" expanded to the person's folder."""
    return os.path.expanduser(path) if path.startswith("~/") else path


def access_view(access: dict) -> dict:
    """What config shows of a valid `access` (local_access): each block that has items, with "definido" in place of
    every value (SPEC-0087, SPEC-0096)."""
    if not access:
        return {}
    view = {}
    if access.get("clusters"):
        view["clusters"] = {cluster: {"context": ACCESS_DEFINED} for cluster in access["clusters"]}
    if access.get("cloud"):
        view["cloud"] = {name: {"profile": ACCESS_DEFINED} for name in access["cloud"]}
    if access.get("databases"):
        view["databases"] = {name: {key: ACCESS_DEFINED for key in ("user", "database", "passfile")}
                             for name in access["databases"]}
    if access.get("urls"):
        view["urls"] = {name: {"base_url": ACCESS_DEFINED} for name in access["urls"]}
    return view


def ci_env_names(ci) -> list:
    names = ci.get("env") if isinstance(ci, dict) else None
    return [] if names in ("", None) else [names] if isinstance(names, str) else list(names)


def read_local(config_home=None):
    """(path, local layer) of this machine; without it raises AtlasError(NOT_CONFIGURED, 3)."""
    path = local_config_path(config_home)
    if not path.is_file():
        raise AtlasError(NOT_CONFIGURED, 3)
    return path, read_yaml(path)


# ---------------------------------------------------------------- several atlases (SPEC-0079, ADR-0021)

ATLAS_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\Z")
ATLAS_NAME_MAX = 63
MULTI_KEYS = ("default", "atlases")
DEFAULT_NAME = "default"  # name of the one-atlas entry whose organization cannot be read
SELECTED_BY_TEXT = {"option": "--atlas", "env": "ATLAS_NAME", "remote": "remote do projeto", "default": "default",
                    "single": "único"}
UNKNOWN_ATLAS = ("atlas não configurado nesta máquina: {typed} — rode init --join --atlas <caminho> "
                 "(atlas configurados: {names})")
NO_CHOICE = ("vários atlas configurados ({names}) e nenhum escolhido — use --atlas <nome>, ATLAS_NAME ou "
             "config --set-default <nome>")


class NoAtlasChosen(AtlasError):
    """Several atlases and no choice (exit 2); config --list shows "nenhum" and doctor an ERRO row instead."""


def atlas_name_of(organization) -> str:
    """Name of an entry derived from the organization: lowercase, anything outside [a-z0-9-] becomes "-", runs of
    "-" become one, "-" at the ends is removed, cut at 63 characters; empty = "default" (SPEC-0079, amendment v2)."""
    text = re.sub(r"[^a-z0-9-]", "-", str(organization or "").lower())
    text = re.sub(r"-+", "-", text).strip("-")[:ATLAS_NAME_MAX]
    return text or DEFAULT_NAME


def organization_of(atlas):
    """organization of <atlas>/atlas-config.yml as text, or None when it cannot be read (never raises)."""
    if not isinstance(atlas, str) or not atlas:
        return None
    try:
        data = read_yaml(Path(atlas) / SHARED_FILE)
    except (AtlasError, OSError, ValueError):
        return None
    organization = data.get("organization")
    return organization if isinstance(organization, str) and organization else None


def _names(entries) -> str:
    return ", ".join(sorted(entries))


def local_atlases(path: Path, local: dict) -> dict:
    """The atlases of the local layer: {"path", "form": "single" | "multi", "default": name | None,
    "entries": {name: {"atlas", "credentials"}}} (entries sorted by name in the multi form).

    Multi form: `default:` (optional, must be in atlases) + `atlases: {<name>: {atlas, credentials}}`. One-atlas
    form (`atlas:` + `credentials:`): one entry named after the organization of its atlas-config.yml (atlas_name_of).
    Both forms together, an invalid name, a default without entry or an unknown key = AtlasError (code 2) naming
    the key. Credentials are validated by whoever uses the chosen entry (doctor shows them as an ERRO row)."""
    if not any(key in local for key in MULTI_KEYS):
        atlas = local.get("atlas")
        name = atlas_name_of(organization_of(atlas)) if isinstance(atlas, str) and atlas else DEFAULT_NAME
        return {"path": path, "form": "single", "default": None, "entries": {name: local}}
    mixed = [key for key in local if key not in MULTI_KEYS]
    if mixed:
        known = [key for key in mixed if key in LOCAL_KEYS]
        if known:
            raise AtlasError(f"configuração local com as duas formas em {path}: atlases junto de "
                             f"{', '.join(known)} — deixe {', '.join(known)} só dentro de atlases.<nome> "
                             "(references/config.md)", 2)
        raise AtlasError(f"chave desconhecida em {path}: {', '.join(map(str, mixed))} — a forma de vários atlas "
                         "aceita só default e atlases (references/config.md)", 2)
    atlases = local.get("atlases")
    if not isinstance(atlases, dict) or not atlases:
        raise AtlasError(f"atlases precisa ser um mapa <nome>: {{atlas, credentials}} em {path}", 2)
    entries = {}
    for name, entry in atlases.items():
        if not ATLAS_NAME_RE.match(str(name)):
            raise AtlasError(f"nome de atlas inválido em {path}: {name} — use [a-z0-9][a-z0-9-]{{0,62}}", 2)
        if entry in ("", None):
            entry = {}
        if not isinstance(entry, dict):
            raise AtlasError(f"atlases.{name} precisa ser um mapa {{atlas, credentials}} em {path}", 2)
        unknown = [str(key) for key in entry if key not in LOCAL_KEYS]
        if unknown:
            raise AtlasError(f"chave desconhecida em atlases.{name}: {', '.join(unknown)} — use só "
                             f"{', '.join(LOCAL_KEYS)} ({path})", 2)
        entries[str(name)] = entry
    default = local.get("default")
    if default in ("", None):
        default = None
    elif not isinstance(default, str) or default not in entries:
        raise AtlasError(f"default: {default} não está em atlases ({_names(entries)}) em {path}", 2)
    return {"path": path, "form": "multi", "default": default, "entries": dict(sorted(entries.items()))}


def is_default(config: dict, name: str) -> bool:
    """The entry is the default: named by `default:`, or the only one when there is no `default:` (one-atlas form)."""
    if config["default"] is not None:
        return name == config["default"]
    return len(config["entries"]) == 1


def entry_atlas(entry) -> str:
    atlas = entry.get("atlas") if isinstance(entry, dict) else None
    return atlas if isinstance(atlas, str) else ""


def atlas_list(config: dict) -> list:
    """[{"name", "atlas", "default"}] sorted by name (config --json, contract SPEC-0079@1)."""
    return [{"name": name, "atlas": entry_atlas(config["entries"][name]), "default": is_default(config, name)}
            for name in sorted(config["entries"])]


def is_path_choice(value: str) -> bool:
    """--atlas / ATLAS_NAME is a folder when it has "/" or starts with "~" or "."; otherwise it is a name."""
    return "/" in value or value.startswith(("~", "."))


def same_folder(first: str, second: str) -> bool:
    """Both paths point to the same folder (~ expanded, relative to the current folder, symlinks resolved)."""
    return os.path.realpath(os.path.expanduser(first)) == os.path.realpath(os.path.expanduser(second))


def _find_atlas(config: dict, typed: str) -> str:
    entries = config["entries"]
    if is_path_choice(typed):
        found = [name for name, entry in entries.items() if entry_atlas(entry) and same_folder(entry_atlas(entry), typed)]
    else:
        found = [typed] if typed in entries else []
    if not found:
        raise AtlasError(UNKNOWN_ATLAS.format(typed=typed, names=_names(entries)), 3)
    return found[0]


GIT_TIMEOUT = 5
SCP_REMOTE_RE = re.compile(r"^(?:[^@/]+@)?([^:/]+):(.*)$")  # [user@]host:path (scp-like, never a scheme)
_REMOTE_CACHE = {}


def normalize_remote(url):
    """host/path of a git remote, lowercase, without scheme, credentials, port, ".git" nor slashes at the ends
    (SPEC-0080); None for a local path or anything without a host. Credentials never reach the result."""
    url = str(url or "").strip()
    if "://" in url:
        try:
            parts = urllib.parse.urlsplit(url)
            host = parts.hostname or ""
        except ValueError:
            return None
        path = parts.path
    else:
        match = SCP_REMOTE_RE.match(url)
        if not match or len(match.group(1)) == 1:  # C:/... is a Windows path, not host:path
            return None
        host, path = match.group(1), match.group(2)
    segments = [segment for segment in path.split("/") if segment]
    if segments and segments[-1].lower().endswith(".git"):
        segments[-1] = segments[-1][:-len(".git")]
    segments = [segment for segment in segments if segment]
    host = host.strip().lower()
    if not host or any(c.isspace() or c in "@:" for c in host):
        return None
    return "/".join([host] + segments).lower()


def project_remote(cwd=None):
    """Normalized `origin` remote of the folder (git config --get remote.origin.url, GIT_OPTIONAL_LOCKS=0, 5 s), or
    None: no git, no repository, no origin, timeout. Never raises and never prints (the remote is not shown)."""
    try:
        cwd = os.getcwd() if cwd is None else str(cwd)
    except OSError:  # the current folder was removed: the remote step is skipped (Emenda v3, item 12)
        return None
    if cwd in _REMOTE_CACHE:
        return _REMOTE_CACHE[cwd]
    try:  # run_collector: the only process runner of atlas.py (argv list, no shell, timeout, output captured)
        stdout, _ = run_collector(["git", "-C", cwd, "config", "--get", "remote.origin.url"], timeout=GIT_TIMEOUT,
                                  env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
        remote = normalize_remote(stdout)
    except (CollectorError, OSError, ValueError):
        remote = None
    _REMOTE_CACHE[cwd] = remote
    return remote


def atlas_remotes(entry) -> list:
    """`remotes:` of the atlas-config.yml of an entry; [] when the atlas cannot be read. Invalid items = AtlasError
    (code 2) naming the item."""
    atlas = entry_atlas(entry)
    if not atlas:
        return []
    try:
        shared = read_yaml(Path(atlas) / SHARED_FILE)
    except (AtlasError, OSError, ValueError):
        return []
    return validate_remotes(shared.get("remotes") if isinstance(shared, dict) else None)


def usable_remotes(entry):
    """atlas_remotes, or None when the atlas's `remotes:` is invalid: in the remote step such an atlas counts as
    having no remotes, so it never breaks the choice of another atlas (SPEC-0080, Emenda v3 item 8)."""
    try:
        return atlas_remotes(entry)
    except AtlasError:
        return None


def remote_matches(config: dict, cwd=None) -> list:
    """Names of the atlases whose longest `remotes:` prefix matches the project's remote by whole segments, all at
    the same (greatest) length; [] without remotes, without a remote or without a match. An atlas with an invalid
    `remotes:` counts as having none."""
    declared = {name: usable_remotes(entry) or [] for name, entry in config["entries"].items()}
    if not any(declared.values()):
        return []  # no git call when no atlas declares remotes:
    remote = project_remote(cwd)
    if not remote:
        return []
    segments = remote.split("/")
    best, names = 0, []
    for name in sorted(declared):
        length = max((len(item.split("/")) for item in declared[name]
                      if segments[:len(item.split("/"))] == item.split("/")), default=0)
        if length and length > best:
            best, names = length, [name]
        elif length and length == best:
            names.append(name)
    return names


def project_remote_choice(config: dict, cwd=None):
    """Step 3 of the order of choice (ADR-0021, SPEC-0080): the `origin` remote of the current folder matched
    against the `remotes:` of each atlas; (name, "remote") for the longest prefix, None without a match or with a
    tie (the order goes on to the default; doctor warns about the tie)."""
    names = remote_matches(config, cwd)
    return (names[0], "remote") if len(names) == 1 else None


def select_atlas(config: dict, choice=None, environ=None) -> tuple:
    """(name, selected_by) of the entry used by every command but init, the first that applies (ADR-0021):
    1. --atlas <name|folder> ("option"); 2. ATLAS_NAME ("env"); 3. the project's remote ("remote", SPEC-0080);
    4. `default:` ("default"); 5. the only atlas ("single"). A name or folder that is not configured = AtlasError
    (code 3) with the list and the step; several atlases and no choice = NoAtlasChosen (code 2)."""
    environ = os.environ if environ is None else environ
    for value, selected_by in ((choice, "option"), (environ.get("ATLAS_NAME"), "env")):
        if value not in (None, ""):
            return _find_atlas(config, str(value)), selected_by
    found = project_remote_choice(config)
    if found is not None:
        return found
    if config["default"] is not None:
        return config["default"], "default"
    if len(config["entries"]) == 1:
        return next(iter(config["entries"])), "single"
    raise NoAtlasChosen(NO_CHOICE.format(names=_names(config["entries"])), 2)


def where(config: dict, name: str) -> str:
    """The local file, plus the entry in the multi form (for messages)."""
    return f"{config['path']} (atlases.{name})" if config["form"] == "multi" else str(config["path"])


def chosen_atlas(config_home=None, choice=None) -> tuple:
    """(config, name, selected_by) of this machine: read_local + local_atlases + select_atlas."""
    path, local = read_local(config_home)
    config = local_atlases(path, local)
    name, selected_by = select_atlas(config, choice)
    return config, name, selected_by


def load_config(config_home=None, choice=None) -> dict:
    """Effective configuration of the chosen atlas (select_atlas): its entry of the local layer +
    <atlas>/atlas-config.yml + defaults, with the origin of each top-level value ("local" | "atlas" | "padrão"),
    plus "atlas_name", "selected_by" and "atlases" (SPEC-0079). Invalid credentials raise AtlasError (code 2)
    without writing anything; an unreadable atlas-config.yml raises AtlasError (code 1)."""
    config, name, selected_by = chosen_atlas(config_home, choice)
    local = config["entries"][name]
    values, origins = {}, {}
    atlas = local.get("atlas")
    present = isinstance(atlas, str) and atlas != ""
    values["atlas"], origins["atlas"] = (atlas if present else ""), (ORIGIN_LOCAL if present else ORIGIN_DEFAULT)
    credentials = local.get("credentials")
    validate_credentials(credentials)
    values["credentials"] = credentials if isinstance(credentials, dict) else {}
    origins["credentials"] = ORIGIN_LOCAL if "credentials" in local else ORIGIN_DEFAULT
    values["access"] = access_view(local_access(local.get("access")))  # never the context (SPEC-0087)
    origins["access"] = ORIGIN_LOCAL if "access" in local else ORIGIN_DEFAULT
    values["probes"] = probes_view(validate_probes(local.get("probes")))  # names only (SPEC-0088)
    origins["probes"] = ORIGIN_LOCAL if "probes" in local else ORIGIN_DEFAULT
    if values["atlas"]:
        require_readable_atlas(values["atlas"])
    shared_path = Path(values["atlas"]) / SHARED_FILE if values["atlas"] else None
    shared = read_yaml(shared_path) if shared_path and shared_path.is_file() else {}
    validate_ci(shared.get("ci"))
    validate_remotes(shared.get("remotes"))
    validate_image_repositories(shared.get("image_repositories"))
    validate_environments(shared.get("environments"))
    defaults = dict(default_shared(), organization="", mode="", remotes=[], image_repositories={}, environments={})
    for key in SHARED_KEYS:
        found = key in shared
        values[key] = shared[key] if found else defaults.get(key, "")
        origins[key] = ORIGIN_ATLAS if found else ORIGIN_DEFAULT
    return {"values": values, "origins": origins, "atlas_name": name, "selected_by": selected_by,
            "atlases": atlas_list(config)}


def render_local_config(atlas: str, credentials=None, access=None, probes=None) -> str:
    data = {"atlas": atlas, "credentials": credentials or {}}
    if access:  # SPEC-0087: kept as it is (only names of this machine's contexts)
        data["access"] = access
    if probes not in (None, ""):  # SPEC-0088: kept as it is (adapters and credential names only)
        data["probes"] = probes
    return LOCAL_HEADER + dump_yaml(data)


def render_atlases(entries: dict, default) -> str:
    """Text of the local layer: the one-atlas form while there is one entry (rollback to the previous version keeps
    working), the multi form (`default:` + `atlases:`) with two or more (ADR-0021)."""
    if len(entries) == 1:
        (entry,) = entries.values()
        return render_local_config(entry_atlas(entry), entry.get("credentials") or {}, entry.get("access"),
                                   entry.get("probes"))
    data = {"default": default} if default else {}
    data["atlases"] = {}
    for name, entry in sorted(entries.items()):
        data["atlases"][name] = {"atlas": entry_atlas(entry), "credentials": entry.get("credentials") or {}}
        if entry.get("access"):
            data["atlases"][name]["access"] = entry["access"]
        if entry.get("probes") not in (None, ""):
            data["atlases"][name]["probes"] = entry["probes"]
    return LOCAL_HEADER + dump_yaml(data)


def write_local_config(path: Path, text: str, backup_of=None):
    """The local layer lives outside the atlas: replaced atomically (it is the machine's pointer to the atlas).
    backup_of: file whose bytes go to config.yml.bak (or .bak.N) first, when the one-atlas form becomes the multi
    form (SPEC-0079); returns that backup path, or None."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if backup_of is not None:
        backup = backup_path(path)
        backup.write_bytes(Path(backup_of).read_bytes())
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return backup


def updated_local(atlas_path: str, name, organization, make_default=False) -> dict:
    """The local layer after init / init --join adds or updates the entry `name` -> atlas_path (SPEC-0079), without
    writing: {"text", "name", "default", "backup_of"}. name None = the name the folder already has on this machine,
    else atlas_name_of(organization) (so init --force with another organization keeps updating the same entry). An
    invalid --name, a name used by another folder or a folder already configured with another --name = AtlasError
    (code 2). The other entries and their credentials do not change; the same name and folder keep the entry's
    credentials; a new entry has none. The first entry becomes the default, --default makes `name` the default.

    Compatibility with the one-atlas form (ADR-0020, SPEC-0070 UT-03/UT-04): without --name, when the only entry
    has the derived name, init/init --join of another folder re-points that entry (as the previous version did,
    credentials kept) instead of failing; a second atlas of another organization is added. The same happens when the
    folder of the only entry is gone or its organization cannot be read (an atlas moved with mv, SPEC-0079 v4)."""
    if name not in (None, "") and not ATLAS_NAME_RE.match(name):
        raise AtlasError(f"--name inválido: {name} — use [a-z0-9][a-z0-9-]{{0,62}}", 2)
    read = local_config_path()  # full configuration, maybe from the old folder
    config = (local_atlases(read, read_yaml(read)) if read.is_file()
              else {"path": read, "form": None, "default": None, "entries": {}})
    entries = dict(config["entries"])
    same = [n for n, e in entries.items() if entry_atlas(e) and same_folder(entry_atlas(e), atlas_path)]
    repoint = False
    if name in (None, ""):
        name = same[0] if same else atlas_name_of(organization)
        only = entry_atlas(next(iter(entries.values()), {}))
        lost = bool(only) and organization_of(only) is None  # moved with mv (or unreadable): nothing to keep apart
        repoint = config["form"] == "single" and not same and (name in entries or lost)  # same org, other folder
    if config["form"] == "single" and (repoint or not entry_atlas(next(iter(entries.values()), {}))):
        entries = {name: next(iter(entries.values()))}  # this init fills or re-points it (credentials kept)
        same = [name]
    if name in entries and name not in same:
        raise AtlasError(f"nome já usado por outro atlas nesta máquina: {name} ({entry_atlas(entries[name])}) — "
                         "escolha outro nome com --name", 2)
    if same and name not in same:
        raise AtlasError(f"atlas já configurado nesta máquina com o nome {same[0]}: {atlas_path} — use --name "
                         f"{same[0]} (ou omita --name)", 2)
    credentials = (entries.get(name) or {}).get("credentials")
    validate_credentials(credentials)
    access = (entries.get(name) or {}).get("access")
    probes = (entries.get(name) or {}).get("probes")
    entries[name] = {"atlas": atlas_path, "credentials": credentials if isinstance(credentials, dict) else {}}
    if access:
        entries[name]["access"] = access
    if probes not in (None, ""):
        entries[name]["probes"] = probes
    default = config["default"]
    if config["form"] == "single":
        default = next(iter(config["entries"]))  # the only atlas was the default
    elif config["form"] is None:
        default = name  # the first entry becomes the default
    if make_default or (default is not None and default not in entries):
        default = name
    backup_of = read if config["form"] == "single" and len(entries) > 1 else None
    return {"text": render_atlases(entries, default), "name": name, "default": default, "backup_of": backup_of}


# ---------------------------------------------------------------- collector contract (ADR-0011)

CONTRACT = "boson-atlas/collector@1"
OLD_CONTRACT = "org-atlas/collector@1"  # same contract under the old name, accepted until SPEC-0073 (SPEC-0071)
# a breaking @2 keeps accepting the previous version (ADR-0011); the old name is an alias, not another version
SUPPORTED_CONTRACTS = (CONTRACT, OLD_CONTRACT)
# The name written in snapshots/<id>.json, whatever name the collector printed (SPEC-0071, amendment v3): the old one,
# so a machine still on the previous version (which knows only the old name) keeps building the same graph from a
# snapshot written here (ADR-0020). SPEC-0073, which removes the old name, switches this to CONTRACT.
SNAPSHOT_CONTRACT = OLD_CONTRACT
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
# (SPEC-0046) words anywhere in the name; whole parts of the name (api_token, db_pwd, basic_auth); ...token at
# the end (accesstoken, not tokenizer); key/keys as a part unless it names a data key (primary_key, sort_keys,
# public_key); and any name glued to key/keys at the end (privkey, hmackey, apikey), except a few common words
# (monkey) and a data-key qualifier glued to it (primarykey). When in doubt, the key is dropped.
FORBIDDEN_WORDS = ("password", "passwd", "secret", "credential")
FORBIDDEN_PARTS = ("token", "tokens", "private", "pwd", "auth", "authorization")
FORBIDDEN_ENDINGS = ("token", "tokens")
KEY_PARTS = ("key", "keys")
DATA_KEY_QUALIFIERS = ("primary", "sort", "public", "foreign", "partition", "range", "hash", "unique", "composite",
                       "natural", "surrogate", "row", "cache", "idempotency", "lookup", "index", "join")
KEY_WORDS = ("monkey", "donkey", "turkey", "hockey", "jockey", "whiskey")  # common words ending in key
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
    if any(word in text for word in FORBIDDEN_WORDS) or any(part in FORBIDDEN_PARTS for part in parts):
        return True
    if "".join(parts).endswith(FORBIDDEN_ENDINGS):
        return True
    if any(part in KEY_PARTS and (index == 0 or parts[index - 1] not in DATA_KEY_QUALIFIERS)
           for index, part in enumerate(parts)):
        return True
    last = parts[-1] if parts else ""
    if last in KEY_PARTS or not last.endswith(KEY_PARTS):
        return False
    stem = last[:-4] if last.endswith("keys") else last[:-3]
    return not (stem in DATA_KEY_QUALIFIERS or last in KEY_WORDS or last[:-1] in KEY_WORDS)


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
    """(clean, violations, dropped) of a collector output against boson-atlas/collector@1 (ADR-0011).

    violations empty = valid. A relation to an entity of another collector is valid (only the kind:id format is
    checked; dangling references are a lint warning, SPEC-0039). Only the contract's fields stay in `clean`
    (output, entity, relation and signal); any other field and every forbidden key (is_forbidden_key: password,
    secret, token, auth, api_key, privkey, credential, private...; in attrs and in a signal) is dropped and reported
    in `dropped` by where it was and its name, never its value. Dropping is not a violation."""
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
    # user may be empty (the scheme and :// followed directly by :password and @host); the password runs up to
    # the last @ before a space, so / and @ inside it are masked too (when in doubt, more is masked, never less).
    # Linear on hostile input without capping realistic sizes (SPEC-0092, Emenda v2): the scheme is up to 32
    # characters; the user never crosses : or /; the password is read up to its first @ without crossing another
    # ://, or, when it contains ://, up to 256 characters (the pieces after that first @ never backtrack)
    ("url", r"(?P<url>\b[A-Za-z][A-Za-z0-9+.-]{0,31}://[^\s/:@]*:)(?:(?:(?!://)[^\s@])*|[^\s@]{0,256})@(?:[^\s@]*@)*"),
    # tokens glued to punctuation (_ghp_, =ghp_, token:ghp_) are masked too
    ("github-pat", r"github_pat_[A-Za-z0-9_]{20,}"),
    # GitHub: standalone (not inside a word: laughs_...) or, glued to text, the exact 36-character body
    ("github", r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{36}(?![A-Za-z0-9])"),
    ("slack", r"xox[abposr]-[A-Za-z0-9-]{10,}"),
    ("aws-access-key", r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])"),  # not ASIAPACIFIC...1
    # Linear on hostile input (SPEC-0092, Emenda v2): unbounded only at the start of a base64 run (lookbehind), or,
    # glued to base64 before it (ghp_...eyJ...), header up to 1024 and payload up to 8192 characters
    ("jwt", r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_-]{8,1024}\.[A-Za-z0-9_-]{8,8192}\.[A-Za-z0-9_-]{8,}"),
)
# one compiled regex per built-in pattern, each matched on its own over the original text: a single alternation
# matches left to right without overlap, so the match of one token would hide a token glued to it (SPEC-0092)
SECRET_RE = tuple(re.compile(regex, re.DOTALL) for _, regex in SECRET_PATTERNS)
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


def _secret_span(match) -> tuple:
    """The part of a match of a SECRET_RE pattern that is masked: the "url" pattern keeps scheme://user: and the
    last @ (it masks only the password, even when empty); every other pattern masks the whole match."""
    if "url" in match.re.groupindex and match.group("url") is not None:
        return match.end("url"), match.end() - 1
    return match.start(), match.end()


def _masked_spans(text: str, extras: list) -> tuple:
    """(merged spans, count): every secret pattern and every extra pattern (in the probe, also PROBE_PATTERNS and
    the literals) finds its matches in the ORIGINAL text; the spans are joined (overlapping or touching ones become
    one) so no mask hides a match from another, in any order (Emenda v6 of SPEC-0088). Zero-width matches of an
    extra pattern (\\b, lookarounds) never mask. count = the occurrences: overlapping matches count once (a span
    already masked is not counted again), touching ones count apart."""
    spans = [_secret_span(match) for regex in SECRET_RE for match in regex.finditer(text)]
    for pattern in extras:  # a pattern with a "mask" group masks only that group (the account id, SPEC-0096)
        group = "mask" if "mask" in pattern.groupindex else 0
        spans += [match.span(group) for match in pattern.finditer(text) if match.end(group) > match.start(group)]
    merged, count, reach = [], 0, -1
    for start, end in sorted(spans):
        if start >= reach:
            count += 1
        reach = max(reach, end) if start < reach else end
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged, count


def _redact_text(text: str, extras: list) -> tuple:
    """(text with each merged span of _masked_spans replaced once by [REDACTED], count): one pass, never a mask
    over a marker already written (no [RE[REDACTED]TED])."""
    spans, count = _masked_spans(text, extras)
    if not spans:
        return text, count
    parts, position = [], 0
    for start, end in spans:
        parts += [text[position:start], REDACTED]
        position = end
    parts.append(text[position:])
    return "".join(parts), count


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


def run_collector(argv, timeout=COLLECTOR_TIMEOUT, env=None, input_text=None, max_bytes=None) -> tuple:
    """The only function of atlas.py that runs an external process (ADR-0010): argv as a list, never a shell, in a
    temporary folder and its own process group, with a timeout (the whole group is killed when it expires) and the
    output captured; env = its environment (None = this process's). Returns (stdout, stderr); exit ≠ 0, timeout or missing executable = CollectorError.
    input_text: text written to its stdin (None = no stdin). max_bytes: the most read from its stdout; more = the
    group is killed and CollectorError (the probe adapters, SPEC-0088)."""
    with tempfile.TemporaryDirectory(prefix="atlas-collector-") as tmp:
        bounded = max_bytes is not None
        try:
            proc = subprocess.Popen(argv, cwd=tmp,
                                    stdin=subprocess.DEVNULL if input_text is None else subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    encoding=None if bounded else "utf-8", errors=None if bounded else "replace",
                                    env=env, start_new_session=os.name != "nt")
        except FileNotFoundError as e:
            raise CollectorError(f"executável não encontrado: {argv[0]}") from e
        except OSError as e:
            raise CollectorError(f"não consegui executar {argv[0]}: {e.strerror or e}") from e
        if bounded:
            stdout, stderr = _bounded_communicate(proc, input_text, timeout, max_bytes)
        else:
            try:
                stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
            except subprocess.TimeoutExpired as e:
                _kill(proc)
                raise CollectorError(f"tempo esgotado ({timeout} s); processo encerrado") from e
            except BaseException:
                _kill(proc)
                raise
    if proc.returncode != 0:
        raise CollectorError(f"saiu com {proc.returncode}", stderr or "")
    return stdout or "", stderr or ""


def _kill_group(proc) -> None:
    """Kills the process and what it started (its process group on POSIX) and reaps it, without touching its pipes
    (the reader threads of _bounded_communicate own them)."""
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
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _bounded_communicate(proc, input_text, timeout, max_bytes) -> tuple:
    """(stdout, stderr) of a binary-mode process, reading at most max_bytes of stdout (and keeping at most
    max_bytes of stderr, the rest drained): over the limit or past the timeout, the group is killed and
    CollectorError. Text is decoded as UTF-8 (invalid bytes replaced)."""
    out, err, over = bytearray(), bytearray(), threading.Event()

    def pump(stream, buffer, limit, stop_when_over):
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                room = limit + 1 - len(buffer)
                if room > 0:
                    buffer.extend(chunk[:room])
                if len(buffer) > limit and stop_when_over:
                    over.set()
                    break
        except (OSError, ValueError):
            pass

    def feed():
        try:
            if input_text is not None:
                proc.stdin.write(input_text.encode("utf-8"))
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass

    threads = [threading.Thread(target=pump, args=(proc.stdout, out, max_bytes, True), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, err, max_bytes, False), daemon=True)]
    if proc.stdin is not None:
        threads.append(threading.Thread(target=feed, daemon=True))
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    try:
        while True:
            if over.is_set():
                _kill_group(proc)
                raise CollectorError(f"saída maior que {max_bytes} bytes; processo encerrado")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_group(proc)
                raise CollectorError(f"tempo esgotado ({timeout} s); processo encerrado")
            try:
                proc.wait(timeout=min(0.05, remaining))
            except subprocess.TimeoutExpired:
                continue
            for thread in threads[:2]:  # a child that keeps the pipes open is bounded by the same deadline
                thread.join(max(0.0, deadline - time.monotonic()))
            if any(thread.is_alive() for thread in threads[:2]):
                _kill_group(proc)
                raise CollectorError(f"tempo esgotado ({timeout} s); processo encerrado")
            if over.is_set():
                raise CollectorError(f"saída maior que {max_bytes} bytes; processo encerrado")
            break
    except BaseException:
        if proc.poll() is None:
            _kill_group(proc)
        raise
    for stream in (proc.stdout, proc.stderr):
        try:
            stream.close()
        except (OSError, ValueError):
            pass
    return out.decode("utf-8", "replace"), err[:max_bytes].decode("utf-8", "replace")


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


def write_exclusive(path: Path, text: str) -> None:
    """write_atomic for a file outside the atlas (the verify snapshot, Emenda v5 of SPEC-0090): the temporary file is
    created exclusively (mkstemp) in the destination folder, then renamed over `path`; a pre-existing file or link
    with a fixed temporary name is never followed. The file is private to the person (0600)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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


def identity_violations(data, collector: dict) -> list:
    """category of the output that differs from the category declared in atlas-config.yml (SPEC-0046, Emenda v2;
    an addition to boson-atlas/collector@1). `collector` is the name of whoever produced the output and may differ
    from the declared id (generic declared as db-facts): it is not checked, and the snapshot always goes by the
    declared id. A missing or non-text category is already a violation of validate_collector_output."""
    if not isinstance(data, dict):
        return []
    value, declared = data.get("category"), collector.get("category")
    if value in CATEGORIES and value != declared:  # an unknown category is already its own violation
        return [f"category da saída ({value}) diferente da declarada no atlas-config.yml ({declared})"]
    return []


def scan_one(collector: dict, atlas: Path, extras: list, today: str, env=None) -> dict:
    """Runs, validates, redacts, normalizes and writes one collector; returns its report (never raises for a
    failure of the collector: the previous snapshot is kept)."""
    cid = collector["id"]
    report = {"id": cid, "status": "failed", "reason": "", "violations": [], "stderr": [], "dropped": [],
              "redacted": 0, "diff": None}
    try:
        argv = resolve_command(collector["command"], SKILL_DIR, atlas)
        stdout, _ = run_collector(argv, collector["timeout"], env)
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
    violations += identity_violations(data, collector)
    if violations:
        report["reason"] = f"saída fora do contrato {CONTRACT} ({len(violations)} violação(ões))"
        report["violations"] = [_redact_text(v, extras)[0] for v in violations]
        return report
    clean["contract"] = SNAPSHOT_CONTRACT  # until SPEC-0073: the old name, readable by the previous version
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


def scan_config(choice=None):
    """(atlas folder, shared configuration) of the chosen atlas (select_atlas: --atlas, ATLAS_NAME, default, the only
    one) for scan, build, context, curate and vendor; problems = AtlasError."""
    config, name, _ = chosen_atlas(choice=choice)
    atlas = entry_atlas(config["entries"][name])
    if not atlas:
        raise AtlasError(f"atlas não definido em {where(config, name)} — rode init (ou init --join)", 3)
    require_readable_atlas(atlas)
    shared_path = Path(atlas) / SHARED_FILE
    if not shared_path.is_file():
        raise AtlasError(f"atlas sem atlas-config.yml — rode init: {shared_path}", 2)
    shared = read_yaml(shared_path)
    validate_image_repositories(shared.get("image_repositories"))  # SPEC-0082: exit 2 before any collector runs
    validate_environments(shared.get("environments"))  # SPEC-0087: the same for environments
    return Path(atlas), shared


def chosen_access(choice=None) -> dict:
    """The local `access` of the chosen atlas's entry (local_access: clusters, cloud, databases, urls; SPEC-0087,
    SPEC-0096); invalid = AtlasError (code 2)."""
    config, name, _ = chosen_atlas(choice=choice)
    return local_access(config["entries"][name].get("access"))


def declared_env_names(entry) -> set:
    """Variable names declared (env) in the credentials of one entry of the local layer, whatever the collector."""
    credentials = entry.get("credentials") if isinstance(entry, dict) else None
    if not isinstance(credentials, dict):
        return set()
    return {n for value in credentials.values() for n in env_names(value) if isinstance(n, str) and n}


def collector_environment(choice=None) -> dict:
    """Environment of the collectors of the chosen atlas (SPEC-0079 v4): this process's environment without the
    variables declared (env) only in the credentials of other atlases; a name also declared by the chosen atlas
    stays. Profiles and credential files are not touched: they depend on each collector's configuration."""
    config, name, _ = chosen_atlas(choice=choice)
    mine = declared_env_names(config["entries"][name])
    others = set()
    for other, entry in config["entries"].items():
        if other != name:
            others |= declared_env_names(entry)
    hidden = others - mine
    return {k: v for k, v in os.environ.items() if k not in hidden}


PROFILE_ENV = "ATLAS_COLLECTOR_PROFILE"


def collector_profiles(choice=None) -> dict:
    """{collector id: profile name} from credentials.<id>.profile of the chosen atlas's local entry (SPEC-0097):
    only the name, never read nor printed here."""
    config, name, _ = chosen_atlas(choice=choice)
    credentials = config["entries"][name].get("credentials")
    profiles = {}
    for cid, entry in (credentials.items() if isinstance(credentials, dict) else ()):
        profile = entry.get("profile") if isinstance(entry, dict) else None
        if isinstance(profile, str) and profile:
            profiles[cid] = profile
    return profiles


def environment_for(env: dict, profile) -> dict:
    """Environment of one collector (SPEC-0097): ATLAS_COLLECTOR_PROFILE inherited from the shell never reaches a
    collector; the collector with credentials.<id>.profile gets it with that name."""
    result = {k: v for k, v in env.items() if k != PROFILE_ENV}
    if profile:
        result[PROFILE_ENV] = profile
    return result


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


def cmd_scan(only=None, as_json=False, choice=None):
    """scan [--only id,...] [--json]: each enabled collector (or the --only ones) is run, validated, redacted,
    normalized and written to snapshots/<id>.json; snapshots/_scan.json keeps seen_at (date of the last good scan),
    status and counts. A failing collector keeps its previous snapshot and seen_at and does not stop the others.
    Exit 0 without failure, 1 with a failure, 2 with an invalid configuration or an unknown --only id."""
    atlas, shared = scan_config(choice)
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
    env = collector_environment(choice)
    profiles = collector_profiles(choice)
    for collector in selected:
        report = scan_one(collector, atlas, extras, today, environment_for(env, profiles.get(collector["id"])))
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
# region "Do commit até o pod" of a service page: only when the service has a code repository (SPEC-0082)
FLOW_REGION, FLOW_TITLE = "commit-to-pod", "Do commit até o pod"
# the image_repositories map kept by infer_relations in the graph in memory, never written to graph.json
IMAGE_MAP_KEY = "image_repositories"
FLOW_BLOCK = f"\n## {FLOW_TITLE}\n\n<!-- atlas:begin {FLOW_REGION} -->\n<!-- atlas:end {FLOW_REGION} -->\n"
FLOW_BLOCK_RE = re.compile(rf"\n## {FLOW_TITLE}\n\n<!-- atlas:begin {FLOW_REGION} -->.*?<!-- atlas:end {FLOW_REGION} -->\n",
                           re.DOTALL)
IMAGE_EVIDENCE = "image:"  # evidence of an edge of rule 4: the repository of the code (SPEC-0082)


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


def config_ref_targets(nodes) -> dict:
    """{host or name: keys of the entities it names} for the config_refs items (rules 2 and 3 of build): the `host`
    attr and the name of each datastore, queue, topic and bucket, and the name of each service. The one matching of
    build, also used by linked_resources (SPEC-0096)."""
    targets = {}
    for node in nodes:
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        if node.get("kind") in RESOURCE_KINDS:
            names = {node.get("name"), attrs.get("host")}
        elif node.get("kind") == "service":
            names = {node.get("name")}
        else:
            continue
        for name in sorted(n for n in names if isinstance(n, str) and n):
            targets.setdefault(name, []).append(node["key"])
    return targets


def _host_of(ref) -> str:
    """Host of a config_refs item (KEY=host): the text after the first '='; '' without it."""
    return ref.split("=", 1)[1] if isinstance(ref, str) and "=" in ref else ""


def _image_repository(image, image_map, repositories, by_name):
    """Key of the repository an image of a deployment comes from (rule 4, SPEC-0082), or None: the image in
    `image_map` -> that repository when it is in the graph (never a fallback: the map is the team's declaration);
    else repository:<image> in the graph; else the last segment of the image naming exactly one repository."""
    if image in image_map:
        key = f"repository:{image_map[image]}"
        return key if key in repositories else None
    key = f"repository:{image}"
    if "/" in image and key in repositories:
        return key
    found = by_name.get(image.rsplit("/", 1)[-1], [])
    return found[0] if len(found) == 1 else None


def _repository_lookup(nodes) -> tuple:
    """(keys of the repositories, {last segment of the repository id: keys}) of a graph's nodes, for
    _image_repository (rule 4)."""
    repositories = {k for k, n in nodes.items() if n["kind"] == "repository"}
    by_name = {}  # last segment of the repository id -> keys (rule 4, step 3)
    for key in sorted(repositories):
        by_name.setdefault(key.rsplit("/", 1)[-1].split(":", 1)[-1], []).append(key)
    return repositories, by_name


def infer_relations(graph: dict, image_repositories=None) -> dict:
    """New graph with the declared edges and the inferred ones (`inferred: true`); the input does not change.
    (1) deployment `sourced_from` repository + deployment `deploys` service -> service `sourced_from` repository;
    (2) a config_refs item (KEY=host) of a deployment whose host equals the `host` attr or the name of a datastore,
        queue, topic or bucket -> service `depends_on` that entity, with `evidence` = the item;
    (3) a host equal to the name of another service -> `depends_on` between the services;
    (4) after rule 1, an item I of the `images` attr of a deployment that deploys a service S and names a
        repository of the graph (_image_repository, with the `image_repositories` map) -> S `sourced_from` that
        repository, with `evidence` = "image:<I>" (SPEC-0082, ADR-0022).
    Only equality: an unknown or similar host creates no edge and no node. An inferred edge equal to a declared
    one (same from, type, to) is not added; the same inferred edge from several items keeps the smallest evidence;
    an edge of rule 4 equal to one of rule 1 is not added either (the edge of rule 1 stays as it is).
    The returned graph keeps the map under IMAGE_MAP_KEY, only in memory (graph.json has only nodes and edges), so
    the pages resolve every image of a service by the same rule (SPEC-0082, Emenda v3)."""
    nodes = {node["key"]: node for node in graph["nodes"]}
    edges = [dict(edge, sources=list(edge["sources"])) for edge in graph["edges"]]
    declared = {(e["from"], e["type"], e["to"]) for e in edges}
    out = {}
    for edge in edges:
        out.setdefault((edge["from"], edge["type"]), []).append(edge)
    targets = config_ref_targets(graph["nodes"])  # host or name -> keys of the entities it names (rules 2 and 3)
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
    image_map = image_repositories if isinstance(image_repositories, dict) else {}
    repositories, by_name = _repository_lookup(nodes)
    before = set(inferred)
    for key in sorted(k for k, n in nodes.items() if n["kind"] == "deployment"):
        images = nodes[key]["attrs"].get("images")
        deploys = [e for e in out.get((key, "deploys"), []) if e["to"].startswith("service:")]
        for image in sorted(i for i in (images if isinstance(images, list) else []) if isinstance(i, str)):
            target = _image_repository(image, image_map, repositories, by_name)
            if target is None:
                continue
            for deploy in deploys:
                if (deploy["to"], "sourced_from", target) not in before:
                    add(deploy["to"], "sourced_from", target, _union(deploy["sources"], nodes[target]["sources"]),
                        f"image:{image}")
    return {**graph, "nodes": [dict(node) for node in graph["nodes"]],
            "edges": edges + [inferred[key] for key in sorted(inferred)], IMAGE_MAP_KEY: dict(image_map)}


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
        image_map = graph.get(IMAGE_MAP_KEY)
        self.image_map = image_map if isinstance(image_map, dict) else {}
        self.repositories, self.by_name = _repository_lookup(self.nodes)
        self.access = set()  # clusters this machine has a local context for (context only, SPEC-0087)
        self.cloud = self.databases = None  # environments / datastores of the local access (SPEC-0096), or None

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


def _code_edges(key, index) -> list:
    """The `sourced_from` edges of a service to a repository inferred from an image (rule 4): the code."""
    return [e for e in index.out.get((key, "sourced_from"), []) if e["to"].startswith("repository:")
            and str(e.get("evidence", "")).startswith(IMAGE_EVIDENCE)]


def _repository_lines(repositories, code, index) -> list:
    """Lines of the "Repositório" region: the list of today without a code repository; else split into "Código"
    (edges of rule 4) and "Configuração (GitOps)" (the others) (SPEC-0082)."""
    if not code:
        return [f"- {index.label(r)}" for r in repositories]
    lines = []
    for title, group in (("Código", code), ("Configuração (GitOps)", [r for r in repositories if r not in code])):
        lines.append(f"- {title}:")
        lines += [f"  - {index.label(r)}" for r in group] or [f"  - {NONE_TEXT}"]
    return lines


def _deployment_images(deployment, index) -> list:
    """The `images` attr of a deployment: only its texts, as they are; [] without it."""
    attrs = index.nodes[deployment]["attrs"] if deployment in index.nodes else {}
    found = attrs.get("images")
    return [i for i in (found if isinstance(found, list) else []) if isinstance(i, str)]


def _code_images(code_edges, deployments, index) -> list:
    """Sorted images of the code (SPEC-0082, Emenda v3): the evidence of the edges of rule 4 and every image of
    `deployments` that leads to a code repository by rule 4."""
    code = {e["to"] for e in code_edges}
    images = {e["evidence"][len(IMAGE_EVIDENCE):] for e in code_edges}
    for deployment in deployments:
        images.update(i for i in _deployment_images(deployment, index)
                      if _image_repository(i, index.image_map, index.repositories, index.by_name) in code)
    return sorted(images)


def _service_pipelines(key, repositories, index) -> list:
    """Pipelines that build the service or any of its `sourced_from` repositories."""
    return _union(*(index.sources(target, "builds", "pipeline") for target in [key] + list(repositories)))


def _flow_lines(code_edges, config, by_env, index) -> list:
    """Lines of the "Do commit até o pod" region, only from the graph and without the name of any tool: the code
    repository, its pipelines, every image of the service's deployments that leads to it by rule 4 (not only the
    evidence of the edge, Emenda v3), the configuration repository and one item per deployment with environment,
    cluster and state (SPEC-0082)."""
    code = _union([e["to"] for e in code_edges])
    images = _code_images(code_edges, {d for group in by_env.values() for d in group}, index)
    pipelines = _union(*(index.sources(r, "builds", "pipeline") for r in code))
    lines = ["1. Código: " + ", ".join(index.label(r) for r in code),
             "2. Pipelines: " + (", ".join(f"{index.name(p)} (`{p.split(':', 1)[1]}`)" for p in pipelines)
                                 or NONE_TEXT),
             "3. Imagem: " + ", ".join(f"`{image}`" for image in images),
             "4. Configuração: " + (", ".join(index.label(r) for r in config) or NONE_TEXT),
             "5. Deployments:"]
    items = []
    for env in sorted(by_env, key=lambda e: (e == "", index.name(e) if e else "")):
        title = index.name(env) if env else "sem ambiente"
        for deployment in by_env[env]:
            attrs = index.nodes[deployment]["attrs"] if deployment in index.nodes else {}
            status = ", ".join(str(attrs[k]) for k in ("sync_status", "health_status") if attrs.get(k))
            clusters = ", ".join(f"`{index.name(c)}`" for c in index.targets(deployment, "runs_in", "cluster"))
            details = "; ".join(part for part in (f"cluster {clusters}" if clusters else "", status) if part)
            items.append(f"   - **{title}**: `{index.name(deployment)}`" + (f" — {details}" if details else ""))
    return lines + (items or [f"   - {NONE_TEXT}"])


def _with_flow_block(text: str, wanted: bool) -> str:
    """The page with the "Do commit até o pod" title and region when `wanted` (after the Pipelines region, else at
    the end), and without them otherwise, so a page without a code repository stays as today (SPEC-0082)."""
    marker = f"<!-- atlas:begin {FLOW_REGION} -->"
    if wanted and marker not in text:
        anchor = "<!-- atlas:end pipelines -->\n"
        at = text.find(anchor)
        if at < 0:
            return text.rstrip("\n") + "\n" + FLOW_BLOCK
        at += len(anchor)
        return text[:at] + FLOW_BLOCK + text[at:]
    if not wanted and marker in text:
        return FLOW_BLOCK_RE.sub("", text, count=1)
    return text


def _service_regions(key, index, scans) -> dict:
    node = index.nodes[key]
    repositories = _union(index.targets(key, "sourced_from", "repository"))
    code_edges = _code_edges(key, index)
    code = _union([e["to"] for e in code_edges])
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
    pipelines = _service_pipelines(key, repositories, index)
    sources = []
    for cid in node["sources"]:
        seen = (scans.get(cid) or {}).get("seen_at") if isinstance(scans.get(cid), dict) else None
        sources.append(f"- {cid}" + (f" (visto em {seen})" if seen else ""))
    regions = {
        "summary": _region(_summary_lines(node)),
        "repository": _region(_repository_lines(repositories, code, index)),
        "deployments": _region(deployment_lines),
        "depends-on": _region([f"- {index.label(e['to'])}{_edge_note(e)}"
                               for e in sorted(depends, key=lambda e: (e["to"], e["type"]))]),
        "used-by": _region([f"- {index.label(e['from'])}{_edge_note(e)}"
                            for e in sorted(used, key=lambda e: (e["from"], e["type"]))]),
        "owners": _region([f"- {index.name(t)} (`{t.split(':', 1)[1]}`)" for t in owners]),
        "pipelines": _region([f"- {index.name(p)} (`{p.split(':', 1)[1]}`)" for p in pipelines]),
        "sources": _region(sources),
    }
    if code:  # SPEC-0082: only with a code repository; without it the page is today's, byte for byte
        regions[FLOW_REGION] = _region(_flow_lines(code_edges, [r for r in repositories if r not in code], by_env,
                                                   index))
    return regions


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
        bodies = _service_regions(key, index, scans)
        text = _with_flow_block(text, FLOW_REGION in bodies)
        if FLOW_REGION not in bodies and f"<!-- atlas:begin {FLOW_REGION} -->" in text:  # moved by the team
            bodies[FLOW_REGION] = _region([])
        pages[path] = fill_regions(text, bodies)
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
    image_map = validate_image_repositories(shared.get("image_repositories"))
    graph = with_tiers(infer_relations(merge_snapshots(snapshots, ids, state), image_map),
                       validate_environments(shared.get("environments")))
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


def with_tiers(graph: dict, tiers: dict) -> dict:
    """The graph with attrs.tier on each environment named in `environments:` (SPEC-0087); the others stay without
    tier (they count as production for consumers, ADR-0023)."""
    for node in graph["nodes"]:
        if node.get("kind") == "environment":
            tier = tiers.get(str(node["key"]).split(":", 1)[1])
            if tier:
                node["attrs"] = dict(sorted({**node["attrs"], "tier": tier}.items()))
    return graph


def build_line(report: dict) -> str:
    return (f"Grafo: {report['nodes']} nós, {report['edges']} arestas ({report['inferred']} inferidas), "
            f"{report['conflicts']} conflitos; {len(report['pages'])} páginas atualizadas")


def print_build(report: dict) -> None:
    for warning in report["warnings"]:
        print(warning, file=sys.stderr)
    print(build_line(report))


def cmd_build(as_json=False, choice=None):
    """build [--json]: graph.json and the pages from the snapshots already on disk (also runs at the end of every
    scan). Exit 0; an unreadable snapshot is a warning."""
    atlas, shared = scan_config(choice)
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
VIA_RE = re.compile(r"^(PR #[0-9]+|local)\Z")  # ASCII digits only (not \d: "PR #３")
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
    """A collector text (sample title, repository name, pattern) as one Markdown line that cannot close the
    generated region."""
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
    pattern = _clean_line(pattern)
    if kind == "pr-title":
        return PR_TITLE_TITLES.get(pattern, f"Títulos de PR no padrão {pattern}")
    return f"Branches com o prefixo {pattern}"


def _item_evidence(kind, pattern, repos, by_repo, follows) -> str:
    """Evidence of a pr-title or branch-prefix convention over `repos` (the repositories in its scope)."""
    total = sum(_number(by_repo[r].get("total")) for r in repos)
    count = sum(_number((by_repo[r].get("pattern_counts" if kind == "pr-title" else "counts") or {}).get(pattern))
                for r in repos)
    unit = "PRs" if kind == "pr-title" else "branches"
    lines = [f"- Padrão: `{_clean_line(pattern)}`", (f"- Total: {total} {unit} da amostra; seguem o padrão: {count} "
                                         f"({_percent(count, total)})"),
             f"- Repositórios com o padrão dominante: {len([r for r in repos if r in follows])} de {len(repos)}"]
    for repo in repos:
        item = by_repo[repo]
        counts = item.get("pattern_counts" if kind == "pr-title" else "counts") or {}
        part, whole = _number(counts.get(pattern)), _number(item.get("total"))
        mark = "" if repo in follows else " — sem padrão dominante"
        lines.append(f"  - {_clean_line(repo)}: {part} de {whole} ({_percent(part, whole)}){mark}")
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
            proposals.append({"id": f"{base}-{_id_part(repo)}", "title": f"{title} em {_clean_line(repo)}", "kind": kind,
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
                lines.append(f"  - {_clean_line(repo)}: segue")
            elif kind == "merge-method" and other is None:
                lines.append(f"  - {_clean_line(repo)}: mais de um método (ou nenhum) permitido")
            elif other:
                lines.append(f"  - {_clean_line(repo)}: só `{other}`")
            else:
                lines.append(f"  - {_clean_line(repo)}: sem template")
        proposals.append({"id": f"{kind}-{pattern}", "title": title, "kind": kind, "scope": "organization",
                          "pattern": pattern, "evidence": "\n".join(lines)})
    return proposals


def _repo_suffix(repo) -> str:
    """Short stable suffix of a repository id (hash of `<org>/<name>`), as the slug of long page names (SPEC-0036)."""
    return hashlib.sha1(str(repo).encode("utf-8")).hexdigest()[:8]


def _without_id_collisions(proposals) -> list:
    """Repository-scope proposals whose id is shared with another proposal get "-<hash of the repository>"
    (acme/a-b and acme-a/b both give "...-acme-a-b"); an id without collision stays as it was. Depends only on the
    set of proposals, never on the order of the signals."""
    count = {}
    for proposal in proposals:
        count[proposal["id"]] = count.get(proposal["id"], 0) + 1
    for proposal in proposals:
        scope = proposal["scope"]
        if count[proposal["id"]] > 1 and scope.startswith("repository:"):
            proposal["id"] = f"{proposal['id']}-{_repo_suffix(scope[len('repository:'):])}"
    return proposals


def _id_pattern(kind, scope, cid):
    """The pattern part of a convention id (`_id_part` of the pattern) from its kind, scope and id, the way
    propose builds it: "<kind>-<pattern>" (organization) or "<kind>-<pattern>-<repository>[-<hash>]"; None when
    the id does not have that shape (written by hand)."""
    prefix = f"{kind}-"
    if not kind or not cid.startswith(prefix):
        return None
    rest = cid[len(prefix):]
    if scope.startswith("repository:"):
        repo = scope[len("repository:"):]
        for end in (f"-{_id_part(repo)}-{_repo_suffix(repo)}", f"-{_id_part(repo)}"):
            if rest.endswith(end) and len(rest) > len(end):
                return rest[:-len(end)]
        return None
    return rest or None


EVIDENCE_PATTERN_RE = re.compile(r"^- Padrão: `([^`\n]+)`$", re.MULTILINE)


def _rejections(conventions: dict) -> list:
    """{id, kind, scope, pattern} of the rejected conventions. The file has no `pattern` key (its format does not
    change): the pattern comes from the id (kind, scope and id of the frontmatter, the record a person decided on);
    an id written by hand falls back to the "- Padrão: `x`" line of the evidence; neither = None (id only)."""
    result = []
    for cid, (meta, text) in conventions.items():
        if meta.get("status") != "rejected":
            continue
        kind, scope = str(meta.get("kind") or ""), str(meta.get("scope") or "")
        pattern = _id_pattern(kind, scope, cid)
        if pattern is None:
            found = EVIDENCE_PATTERN_RE.search(page_regions(text).get("evidence", ""))
            pattern = found.group(1) if found else None
        result.append({"id": cid, "kind": kind, "scope": scope, "pattern": pattern})
    return result


def is_rejected(proposal: dict, rejections: list) -> bool:
    """True when a rejected convention has the same id, or the same kind and pattern in any scope: whoever rejects
    the rule rejects the rule, not the scope (ADR-0012). Patterns are compared as they appear in ids (_id_part)."""
    kind, pattern = proposal.get("kind"), _id_part(proposal.get("pattern"))
    for item in rejections or []:
        if item.get("id") == proposal.get("id"):
            return True
        if item.get("pattern") is not None and item.get("kind") == kind and _id_part(item["pattern"]) == pattern:
            return True
    return False


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
    return sorted(_without_id_collisions(proposals), key=lambda p: p["id"])


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
    of the existing ones, whatever their status. A rejected rule is never proposed again, in any scope: same id
    (its file already exists) or same kind and pattern (is_rejected). Never writes a decision."""
    collectors = validate_collectors(shared.get("collectors"))
    snapshots, warnings = read_snapshots(atlas, [c["id"] for c in collectors])
    signals = [s for cid in snapshots for s in snapshots[cid].get("signals", [])]
    proposals = propose_conventions(signals, shared.get("curation"))
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    organization = str(shared.get("organization") or "")
    folder = atlas / CONVENTIONS_DIR
    existing = _conventions(atlas)
    rejections = _rejections(existing)
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
        if is_rejected(proposal, rejections):
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
    atlas, shared = scan_config(args.atlas)
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
    fixed = {line.strip() for line in template.splitlines() if line.strip()} | {f"## {FLOW_TITLE}"}
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
    entry = {"key": key, "name": node["name"], "score": score, "reason": reason, "page": page,
             "repositories": [r.split(":", 1)[1] for r in repositories], "deployments": deployments,
             "owners": [{"id": t.split(":", 1)[1], "name": index.name(t)} for t in owners], "attrs": node["attrs"],
             "seen_at": node["seen_at"]}
    delivery = _delivery(key, repositories, index)
    if delivery:
        entry["delivery"] = delivery
    if index.databases is not None:  # SPEC-0096: only whether there is local access, never a value
        stores = _union(*(index.targets(key, rtype, "datastore") for rtype in DEPENDENCY_TYPES))
        entry["database_access"] = {d.split(":", 1)[1]: d.split(":", 1)[1] in index.databases
                                    for d in sorted(stores)}
    return entry


def _delivery(key, repositories, index):
    """The delivery path of a service (SPEC-0086), from the graph by the rules of the "Do commit até o pod" region
    (SPEC-0082): code repositories (rule 4), configuration repositories (the other `sourced_from`, only with code),
    the pipelines of the service and of its repositories, the images of the code and the deployments with
    environments, clusters, state and images. None without a deployment, a pipeline or a code repository."""
    code_edges = _code_edges(key, index)
    code = _union([e["to"] for e in code_edges])
    deployments = sorted(index.sources(key, "deploys", "deployment"), key=lambda d: d.split(":", 1)[1])
    pipelines = _service_pipelines(key, repositories, index)
    if not (code or deployments or pipelines):
        return None
    targets = [key] + list(repositories)
    pipeline_items = []
    for pipeline in pipelines:
        built = index.targets(pipeline, "builds", "repository")
        repository = next((r for r in built if r in targets), built[0] if built else "")
        pipeline_items.append({"id": pipeline.split(":", 1)[1], "name": index.name(pipeline),
                               "repository": repository.split(":", 1)[1] if repository else ""})
    pipeline_items.sort(key=lambda p: p["id"])
    deployment_items = []
    for deployment in deployments:
        attrs = index.nodes[deployment]["attrs"] if deployment in index.nodes else {}
        item = {"id": deployment.split(":", 1)[1],
                "environments": sorted(index.name(e) for e in index.targets(deployment, "runs_in", "environment")),
                "clusters": sorted(index.name(c) for c in index.targets(deployment, "runs_in", "cluster"))}
        for name in ("sync_status", "health_status"):
            if attrs.get(name):
                item[name] = str(attrs[name])
        item["images"] = sorted(_deployment_images(deployment, index))
        item.update(_access_fields(deployment, attrs, index))
        deployment_items.append(item)
    return {"code_repositories": [r.split(":", 1)[1] for r in sorted(code)],
            "config_repositories": (sorted(r.split(":", 1)[1] for r in repositories if r not in code)
                                    if code else []),
            "pipelines": pipeline_items,
            "images": _code_images(code_edges, deployments, index),
            "deployments": deployment_items}


def _deployment_tier(deployment, index):
    """The tier of a deployment from its environments (SPEC-0087): "production" when one is production, "test" when
    all are test; None without an environment or when one has no tier (it counts as production, ADR-0023)."""
    tiers = [index.nodes.get(e, {}).get("attrs", {}).get("tier")
             for e in index.targets(deployment, "runs_in", "environment")]
    if not tiers or any(tier not in TIERS for tier in tiers):
        return None
    return "production" if "production" in tiers else "test"


def _access_fields(deployment, attrs, index) -> dict:
    """tier, namespace, workloads and access of a deployment of delivery (SPEC-0087), each only with a value; access
    only when the deployment runs in a cluster (true when this machine has a local context for one of them)."""
    fields = {}
    tier = _deployment_tier(deployment, index)
    if tier:
        fields["tier"] = tier
    if isinstance(attrs.get("namespace"), str) and attrs["namespace"]:
        fields["namespace"] = attrs["namespace"]
    workloads = attrs.get("workloads")
    if isinstance(workloads, list):
        workloads = sorted({str(w) for w in workloads if isinstance(w, str) and w})
        if workloads:
            fields["workloads"] = workloads
    clusters = index.targets(deployment, "runs_in", "cluster")
    if clusters:
        names = {index.name(c) for c in clusters} | {c.split(":", 1)[1] for c in clusters}
        fields["access"] = bool(names & index.access)
    if index.cloud is not None:  # SPEC-0096: true when access.cloud has one of its environments
        envs = index.targets(deployment, "runs_in", "environment")
        names = {index.name(e) for e in envs} | {e.split(":", 1)[1] for e in envs}
        fields["cloud_access"] = bool(names & index.cloud)
    return fields


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
    decision; hints = inferred, and confirmed with an incomplete decision (`incomplete: true`); rejected never.
    The repository scope is compared without case: GitHub names are case-insensitive, and conventions curated before
    the lower-case ids (`scope: repository:Acme/API`) still apply (SPEC-0047)."""
    scopes = {"organization"} | {f"repository:{r}".casefold() for r in repositories}
    rules, hints = [], []
    for cid, (meta, _) in _conventions(atlas).items():
        if str(meta.get("scope") or "").casefold() not in scopes:
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


def build_context(atlas: Path, query: str, hops=1, limit=8, max_chars=30000, today=None, access=None, cloud=None,
                  databases=None) -> dict:
    """Read-only package for a task (references/context.md): staleness warnings, the services found by the query
    terms (name, id, attrs and the team notes of their pages, by score), the dependency edges up to `hops` steps,
    the confirmed (rules) and inferred (hints) conventions of the organization and of the services' repositories,
    and what did not fit in max_chars (omitted). An atlas without scan = empty package with the warning. `access`:
    the clusters this machine has a local context for (only their names, SPEC-0087); `cloud` and `databases`: the
    environments and datastores of access.cloud and access.databases, or None without the key (SPEC-0096)."""
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
    try:  # the map of build (SPEC-0082): delivery.images resolves like the page (SPEC-0086, Emenda v3)
        image_map = validate_image_repositories(shared.get("image_repositories"))
    except AtlasError:
        image_map = {}
    index = _Index({**graph, IMAGE_MAP_KEY: image_map}, _existing_service_pages(atlas))
    index.access = {str(cluster) for cluster in (access or ())}
    index.cloud = None if cloud is None else {str(name) for name in cloud}
    index.databases = None if databases is None else {str(name) for name in databases}
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
    name = service["name"] or service["key"]  # in a code span: a name never reads as a heading ("## Serviços")
    lines = [f"### `{name}` (`{service['key']}`)", "",
             f"- Página: {service['page']}",
             f"- Encontrado por: {service['reason']} (pontuação {service['score']})"]
    if service["repositories"]:
        lines.append(f"- Repositório: {', '.join(service['repositories'])}")
    if service["deployments"]:
        parts = [f"{', '.join(d['environments']) or 'sem ambiente'}: {d['id']}" for d in service["deployments"]]
        lines.append(f"- Deployments: {'; '.join(parts)}")
    if service.get("delivery"):
        lines += _delivery_lines(service["delivery"])
    if service.get("database_access"):
        lines.append("- Acesso local ao banco: " + ", ".join(
            f"`{store}` ({'sim' if ok else 'não'})" for store, ok in service["database_access"].items()))
    if service["owners"]:
        lines.append("- Donos: " + ", ".join(f"{o['name']} ({o['id']})" for o in service["owners"]))
    lines += [f"- {name}: {_fmt_value(value)}" for name, value in service["attrs"].items()]
    lines.append(f"- Visto em: {service['seen_at']}")
    return lines + [""]


def _delivery_lines(delivery) -> list:
    """The "Entrega" block of a service (SPEC-0086): each line only with a value, one per deployment."""
    def code(values):  # every atlas value in its own code span (Emenda v3); backticks are already "'" (_flat)
        return ", ".join(f"`{value}`" for value in values)

    pipelines = [f"`{p['name']}`" + (f" (`{p['repository']}`)" if p["repository"] else "")
                 for p in delivery["pipelines"]]
    lines = [f"  - {label}: {text}" for label, text in (
        ("Código", code(delivery["code_repositories"])), ("Pipelines", ", ".join(pipelines)),
        ("Imagens", code(delivery["images"])), ("Configuração (GitOps)", code(delivery["config_repositories"])))
        if text]
    for item in delivery["deployments"]:
        parts = [f"{label} {value}" for label, value in (
            ("cluster", code(item["clusters"])), ("sync", code([item["sync_status"]]) if "sync_status" in item else ""),
            ("health", code([item["health_status"]]) if "health_status" in item else ""),
            ("tier", code([item["tier"]]) if "tier" in item else ""),
            ("namespace", code([item["namespace"]]) if "namespace" in item else ""),
            ("workloads", f"`{', '.join(item['workloads'])}`" if item.get("workloads") else "")) if value]
        if item.get("access") is False:
            parts.append("sem acesso local")
        if item.get("cloud_access") is False:
            parts.append("sem acesso local à nuvem")
        lines.append(f"  - {', '.join(item['environments']) or 'sem ambiente'}: `{item['id']}`"
                     + (f" — {'; '.join(parts)}" if parts else ""))
    return ["- Entrega:"] + lines


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
    """Every text of the package on one line (newlines, CR and tabs become spaces) and without backticks (they
    become "'"): data from the atlas never becomes a heading or an item of the package, nor leaves a code span."""
    if isinstance(value, str):
        return " ".join(value.replace("`", "'").split())
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
    atlas, _ = scan_config(args.atlas)
    access = chosen_access(args.atlas)  # only names go on: no access value ever leaves (SPEC-0087, SPEC-0096)
    query = " ".join(args.query).strip()
    package = build_context(atlas, query, args.hops, args.limit, args.max_chars, access=set(access["clusters"]),
                            cloud=set(access["cloud"]) if access["cloud"] else None,
                            databases=set(access["databases"]) if access["databases"] else None)
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
              "orphan-page", "untiered-environment")
LINT_ERRORS = ("secret-leak", "config", "failed-collector")
VCS_DIRS = (".git", ".hg", ".svn", ".bzr", "_darcs", ".jj")
LINT_IGNORED_FILES = (".DS_Store", "Thumbs.db", "desktop.ini")
LINT_MAX_BYTES = 32 * 1024 * 1024  # a bigger file is not read (config finding): the lint stays fast and bounded
LINT_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
SECRET_REGEXES = tuple((name, regex) for (name, _), regex in zip(SECRET_PATTERNS, SECRET_RE))
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
    "untiered-environment": "marque o ambiente em environments: do atlas-config.yml com {tier: test} ou "
                            "{tier: production} (references/config.md)",
}
SHARED_SUGGESTION = "corrija o atlas-config.yml (references/config.md e references/collector-contract.md)"
READ_SUGGESTION = ("regrave o arquivo em UTF-8 válido; se é gerado (snapshots/, graph.json, regiões), rode "
                   "`atlas.py scan`")
GENERATED_SUGGESTION = "arquivo gerado com formato inesperado: rode `atlas.py scan` (ou `build`) para refazê-lo"
SPECIAL_SUGGESTION = ("o atlas só tem arquivos e pastas comuns: troque por uma cópia do conteúdo ou tire da pasta do "
                      "atlas")
OUTDATED_COPY = "cópia da skill desatualizada — rode `vendor`"
OUTDATED_SUGGESTION = ("rode `atlas.py vendor` para regravar {copy} com a versão instalada da skill "
                       "(references/modes.md)")
OLD_COPY_LEFT = "cópia antiga da skill, que nenhum arquivo de CI roda mais"
OLD_COPY_LEFT_SUGGESTION = "apague a pasta antiga: git rm -r .org-atlas (references/modes.md)"
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


def _finding(rule, path, detail, suggestion=None, severity=None) -> dict:
    severity = severity or ("error" if rule in LINT_ERRORS else "warn")
    return {"rule": rule, "severity": severity, "path": path, "detail": detail,
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
    """Every regular file of the atlas (VCS folders skipped, and <copy>/scripts/atlas.py of each of SKILL_COPIES
    (.boson-atlas/skill and .org-atlas/skill), the tool written
    by vendor, when identical to this atlas.py: its own patterns look like secrets), read once. A copy that differs
    is an outdated copy: a config warning in `outdated`, and it is still read and scanned (secret-leak drops only the
    matches whose text is also in this atlas.py, `tool_text`). Symlinks, FIFOs, sockets and devices are
    never read nor followed; they, unreadable files and folders, non-UTF-8 files (also kept, decoded with
    replacement, for secret-leak) and JSON with an invalid content or shape become `problems` (config findings)."""

    def __init__(self, atlas: Path):
        self.atlas, self.texts, self.lossy, self.names, self.problems, self._json = atlas, {}, {}, [], {}, {}
        self.outdated = {}  # rel -> (detail, suggestion): config warnings
        self.tool_text = ""  # this atlas.py, when a copy is outdated: its own regexes and examples are not secrets
        self._copy_tools = {f"{copy}/scripts/atlas.py" for copy in SKILL_COPIES}
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
                    copy = self._is_skill_copy(path, self.rel(path))
                    if copy == "outdated":
                        copy_dir = self.rel(path)[:-len("/scripts/atlas.py")]
                        if copy_dir == OLD_SKILL_COPY and ci_migrated(atlas):  # only removing it is left
                            self.outdated[self.rel(path)] = (OLD_COPY_LEFT, OLD_COPY_LEFT_SUGGESTION)
                        else:
                            self.outdated[self.rel(path)] = (OUTDATED_COPY,
                                                             OUTDATED_SUGGESTION.format(copy=copy_dir))
                        self.tool_text = self._tool_text()
                    elif copy:
                        continue
                    self.names.append((self.rel(path), name))
                    self._read(path, self.rel(path))

    def rel(self, path) -> str:
        try:
            rel = Path(path).relative_to(self.atlas).as_posix()
        except ValueError:
            return "."
        return rel or "."

    def _is_skill_copy(self, path, rel):
        """<copy>/scripts/atlas.py (any of SKILL_COPIES) written by vendor: "same" when identical to this atlas.py
        or, when the lint runs from the copy itself (nothing else to compare with), that same file; "outdated" when
        it is a regular file that differs (another version of the skill, or edited: still read and scanned); False
        for any other path, or when it is not a regular file or cannot be read (read as any file). Limitation: when
        the lint runs from the copy itself there is nothing to compare with, and an edit to it is not scanned."""
        if rel not in self._copy_tools:
            return False
        source = Path(__file__).resolve()
        try:
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode):
                return False
            if os.path.samefile(path, source):
                return "same"
            expected = source.read_bytes()
            if info.st_size != len(expected):
                return "outdated"
            with os.fdopen(os.open(path, LINT_OPEN_FLAGS), "rb") as handle:
                return "same" if handle.read(len(expected) + 1) == expected else "outdated"
        except OSError:
            return False

    @staticmethod
    def _tool_text() -> str:
        try:
            return Path(__file__).resolve().read_bytes().decode("utf-8", "replace")
        except OSError:
            return ""

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


def _radical(name) -> str:
    """A name up to its first dot, without the leading dots of a hidden file: acme-x.tar.gz and .acme-x.md give
    acme-x."""
    return name.lstrip(".").split(".", 1)[0]


def _name_patterns(name, patterns) -> list:
    """Patterns that match a file or folder name, its stem without the extension (^acme-[0-9a-f]{8}$ matches
    acme-feedface.md) or its radical up to the first dot (acme-feedface.tar.gz, .acme-feedface): the same pieces
    _mask_path masks."""
    found = set()
    for piece in {name, os.path.splitext(name)[0], _radical(name)}:
        if piece:
            found |= set(_matching_patterns(piece, patterns))
    return [label for label, _ in patterns if label in found]


def _lint_secrets(files: _AtlasFiles, extras) -> list:
    """secret-leak: each match of a redaction pattern (built-in and extra_patterns) in any file, by file:line and
    pattern name, and each file or folder whose name matches one; never the value. In an outdated copy of the tool
    (<copy>/scripts/atlas.py of any of SKILL_COPIES) a match whose text is also in the installed atlas.py (its own
    regexes and examples) is not a secret; any other match is."""
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
        known = files.tool_text if rel in files.outdated else ""
        for name, regex in patterns:
            for match in regex.finditer(text):
                if not match.group(0) or (known and match.group(0) in known):
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
    for rel, (detail, suggestion) in sorted(files.outdated.items()):
        findings.append(_finding("config", rel, detail, suggestion, severity="warn"))
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
                findings.append(_finding("broken-ref", rel, f"link para {_mask_link(target, extras)}: {problem}",
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


def graph_environments(graph) -> list:
    """Sorted ids of the environment nodes of a graph (graph.json); [] for a missing or malformed graph."""
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    return sorted({str(n["key"]).split(":", 1)[1] for n in (nodes if isinstance(nodes, list) else [])
                   if isinstance(n, dict) and n.get("kind") == "environment" and isinstance(n.get("key"), str)
                   and ":" in n["key"]})


def graph_clusters(graph) -> list:
    """Sorted names of the cluster nodes of a graph (graph.json); [] for a missing or malformed graph."""
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    return sorted({str(n.get("name") or n["key"].split(":", 1)[1]) for n in (nodes if isinstance(nodes, list) else [])
                   if isinstance(n, dict) and n.get("kind") == "cluster" and isinstance(n.get("key"), str)
                   and ":" in n["key"]})


def untiered_environments(graph, shared) -> list:
    """Environments of the graph without a tier in `environments:` (SPEC-0087); [] when the map is invalid (the
    config rule and the doctor already report it)."""
    try:
        tiers = validate_environments(shared.get("environments") if isinstance(shared, dict) else None)
    except AtlasError:
        return []
    return [name for name in graph_environments(graph) if name not in tiers]


def _lint_untiered(files: _AtlasFiles, shared) -> list:
    """One untiered-environment finding (warn) per environment of graph.json without a tier (SPEC-0087)."""
    return [_finding("untiered-environment", SHARED_FILE,
                     f"ambiente {name} sem marcação em environments: (conta como produção)")
            for name in untiered_environments(files.json(GRAPH_FILE), shared)]


def _mask_all(text, extras) -> str:
    """text with every piece that matches a secret pattern (built-in or extra) masked."""
    return _redact_text(str(text), [regex for _, regex in extras])[0]


def _mask_component(part, extras) -> str:
    """One "/" component masked by its radical (up to the first dot, after the leading dots), its stem without the
    extension and as a whole: the pieces _name_patterns tests."""
    lead = part[:len(part) - len(part.lstrip("."))]
    radical, dot, tail = part[len(lead):].partition(".")
    if radical:
        part = lead + _mask_all(radical, extras) + dot + tail
    stem, ext = os.path.splitext(part)
    return _mask_all(_mask_all(stem, extras) + ext if stem else part, extras)


def _mask_path(path, extras) -> str:
    """path with each "/" component masked on its own (an anchored pattern, ^...$, that matches a name is masked
    exactly as it is detected by _name_patterns), then the whole path (a pattern that crosses "/", like
    vault/[a-z0-9]{8})."""
    return _mask_all("/".join(_mask_component(part, extras) for part in str(path).split("/")), extras)


def _mask_link(target, extras) -> str:
    """A link target masked as a path without its "#fragment" or "?query", which comes back after (masked too)."""
    target = str(target)
    cut = min((i for i in (target.find("#"), target.find("?")) if i >= 0), default=len(target))
    return _mask_path(target[:cut], extras) + _mask_all(target[cut:], extras)


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
    if "untiered-environment" in rules:
        findings += _lint_untiered(files, shared)
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


def _lint_atlas(choice=None) -> Path:
    """The folder of the chosen atlas (select_atlas), from the local configuration of this machine only
    (atlas-config.yml is read by run_lint, as one more file of the atlas). Without configuration = AtlasError
    (code 3)."""
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
    config = local_atlases(path, local)
    name, _ = select_atlas(config, choice)
    validate_access(config["entries"][name].get("access"))  # SPEC-0087: exit 2, as config --json
    atlas = entry_atlas(config["entries"][name])
    if not atlas:
        raise AtlasError(f"atlas não definido em {where(config, name)} — rode init (ou init --join)", 3)
    if not os.path.isdir(atlas):
        raise AtlasError(f"pasta do atlas não encontrada: {atlas} — rode init (ou init --join)", 3)
    require_readable_atlas(atlas)
    return Path(atlas)


def _lint_image_repositories(atlas: Path) -> None:
    """An invalid `image_repositories:` (SPEC-0082) or `environments:` (SPEC-0087) ends lint with exit 2, as
    config --json and build. An unreadable
    or invalid atlas-config.yml is left to the config rule of the lint."""
    path = atlas / SHARED_FILE
    try:
        shared = parse_yaml(path.read_bytes().decode("utf-8")) if path.is_file() else {}
    except (OSError, UnicodeDecodeError, ValueError):
        return
    validate_image_repositories(shared.get("image_repositories"))
    validate_environments(shared.get("environments"))  # SPEC-0087: exit 2 too


def cmd_lint(args):
    """lint [--json] [--only rule,...]: read-only (never writes to the atlas). Exit 0 without ERRO, 1 with ERRO,
    2 with an unknown rule in --only, 3 not configured. Messages on stderr are masked too."""
    try:
        rules = lint_rules(args.only)
        atlas = _lint_atlas(args.atlas)
        _lint_image_repositories(atlas)
        findings = run_lint(atlas, rules)
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
# The copy of the skill the CI runs (python3 <copy>/scripts/atlas.py), SPEC-0070: vendor writes the first one; the
# second, of the old name, is still a copy of the tool for lint, build, scan and doctor, and vendor keeps it updated
# while a customized CI file still runs it. Nothing here deletes it (ADR-0019).
SKILL_COPIES = (".boson-atlas/skill", ".org-atlas/skill")
SKILL_COPY, OLD_SKILL_COPY = SKILL_COPIES
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


def copy_skill(atlas: Path, copy: str = SKILL_COPY) -> int:
    """Copy the skill into <atlas>/<copy>/ (.boson-atlas/skill by default), always overwritten (the CI runs this
    copy, never a customized one); returns how many files changed."""
    changed = 0
    for rel, source in skill_files():
        data, dest = source.read_bytes(), atlas / copy / rel
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


OLD_COPY_DIR = OLD_SKILL_COPY.split("/")[0]  # .org-atlas
REMOVE_OLD = f"git rm -r {OLD_COPY_DIR}"


def migration_step(ci: str) -> str:
    return f"para migrar: vendor --ci {ci} --force e depois {REMOVE_OLD}"


def ci_file_state(atlas: Path, rel: str) -> str:
    """"absent" | "unproven" | "unknown" | "new" for a CI file of CI_TARGETS (SPEC-0070 and SPEC-0071, amendments
    v2): a symlink, a file that cannot be read as UTF-8 text or one that cites the old folder may still run
    .org-atlas/skill ("unproven"); one that cites neither folder (it may run the tool through another script) is
    "unknown"; one that cites .boson-atlas/skill and not the old folder runs only the new copy ("new"). Only reads."""
    path = atlas / rel
    if path.is_symlink():
        return "unproven"
    if not path.exists():
        return "absent"
    try:
        if not path.is_file():
            return "unproven"
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "unproven"
    if OLD_COPY_DIR in text:
        return "unproven"
    return "new" if SKILL_COPY in text else "unknown"


MAY_RUN_OLD = ("unproven", "unknown")  # ci_file_state values that do not prove the CI left .org-atlas/skill


def old_ci_kinds(atlas: Path) -> list:
    """The kinds of CI_TARGETS whose file may still run the old copy (ci_file_state "unproven" or "unknown")."""
    return [kind for kind, (_, rel) in CI_TARGETS.items() if ci_file_state(atlas, rel) in MAY_RUN_OLD]


def new_ci_kinds(atlas: Path) -> list:
    """The kinds of CI_TARGETS whose file runs .boson-atlas/skill and not the old copy (ci_file_state "new")."""
    return [kind for kind, (_, rel) in CI_TARGETS.items() if ci_file_state(atlas, rel) == "new"]


def ci_migrated(atlas: Path) -> bool:
    """At least one CI file of CI_TARGETS and none that may still run the old copy: only removing it is left."""
    states = [ci_file_state(atlas, rel) for _, rel in CI_TARGETS.values()]
    return "new" in states and not any(state in MAY_RUN_OLD for state in states)


def vendor_copies(atlas: Path, ci: str, content: str, force: bool) -> list:
    """The copies vendor writes (SPEC-0070, SPEC-0071): .boson-atlas/skill unless the CI file of `ci` is kept
    (customized, without --force) and runs the old copy and not the new one, and no other CI file runs the new one
    nor .boson-atlas/ exists; .org-atlas/skill too when that happens or when it exists and some CI file of any kind
    that is kept may still run it (symlink, unreadable, cites the old folder or cites neither folder)."""
    target = CI_TARGETS[ci][1]
    dest = atlas / target
    kept = False
    if not force and dest.is_file():
        try:
            current = dest.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            current = None  # put_file reports it
        kept = current != content
        if kept and current is not None and not dest.is_symlink() and OLD_SKILL_COPY in current \
                and SKILL_COPY not in current:
            new_elsewhere = (atlas / SKILL_COPY.split("/")[0]).is_dir() or \
                any(kind != ci for kind in new_ci_kinds(atlas))
            return [SKILL_COPY, OLD_SKILL_COPY] if new_elsewhere else [OLD_SKILL_COPY]
    unproven = [kind for kind in old_ci_kinds(atlas) if kind != ci or kept]
    copies = [SKILL_COPY]
    if unproven and (atlas / OLD_COPY_DIR).is_dir():
        copies.append(OLD_SKILL_COPY)
    return copies


def cmd_vendor(args):
    """vendor --ci github|generic [--schedule CRON] [--force] (SPEC-0040): writes the CI files of the atlas of this
    machine and the copy of the skill they run; never runs git nor a platform CLI (ADR-0010). Everything is
    validated before the first write: mode local, an invalid ci or --schedule = exit 2."""
    atlas, shared = scan_config(args.atlas)
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
    for copy in vendor_copies(atlas, args.ci, content, args.force):
        changed = copy_skill(atlas, copy)
        print(f"{'atualizado' if changed else 'já atualizado'}: {copy}/ (cópia da skill, {ATLAS_VERSION})")
    put_file(atlas, target, content, args.force, executable=target.endswith(".sh"))
    if args.ci == "github":
        names = ci_env_names(ci)
        print(f"Agenda: {schedule} (UTC). Secrets esperados no repositório: {', '.join(names) or '(nenhum)'}")
    else:
        print(f"Na sua CI: rode `bash {target}` na raiz do atlas com as variáveis de ci.env; "
              "exit 0 sem mudança, 10 com mudança (abra o PR/MR), 1 com falha")
    new_dir, old_dir = SKILL_COPY.split("/")[0], OLD_COPY_DIR
    still_old = old_ci_kinds(atlas)
    for kind in still_old if (atlas / old_dir).is_dir() else ():
        if ci_file_state(atlas, CI_TARGETS[kind][1]) == "unknown":
            print(f"{CI_TARGETS[kind][1]} não cita {SKILL_COPY} e pode ainda rodar {OLD_SKILL_COPY} — troque o "
                  f"script do time para rodar {SKILL_COPY}, ou {migration_step(kind)}")
        else:
            print(f"a CI ainda roda {OLD_SKILL_COPY} — {migration_step(kind)}")
    if not still_old and (atlas / old_dir).is_dir():
        print(f"pode apagar {old_dir}/ ({REMOVE_OLD}) depois que a CI rodar com {new_dir}/")
    print(f"Faça commit de {new_dir}/ (ou {old_dir}/) e do arquivo da CI no atlas (o atlas.py não executa o git).")
    return 0


# ---------------------------------------------------------------- init

def backup_path(path: Path) -> Path:
    """<name>.bak (atlas-config.yml.bak, config.yml.bak), or .bak.1, .bak.2... so an older backup is never
    overwritten."""
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


def write_local_update(local_path: Path, update: dict) -> None:
    """Writes the local layer computed by updated_local (with config.yml.bak when it becomes the multi form)."""
    backup = write_local_config(local_path, update["text"], update["backup_of"])
    if backup is not None:
        print(f"Configuração anterior (um atlas só) em {backup}")


def print_entry(update: dict) -> None:
    mark = " (padrão)" if update["default"] == update["name"] else ""
    print(f"Atlas nesta máquina: {update['name']}{mark}")


def join_atlas(atlas_path: str, local_path: Path, name=None, make_default=False) -> int:
    """init --join: adds or updates the entry of an existing atlas in the local layer (updated_local)."""
    require_readable_atlas(atlas_path)
    shared = Path(atlas_path) / SHARED_FILE
    if not shared.is_file():
        raise AtlasError(f"atlas sem atlas-config.yml — rode init: {shared}", 2)
    data = read_yaml(shared)
    update = updated_local(atlas_path, name, data.get("organization"), make_default)
    write_local_update(local_path, update)
    print(f"Máquina ligada ao atlas em {atlas_path} ({data.get('organization', '')}, modo {data.get('mode', '')})")
    print_entry(update)
    print(f"Configuração local: {local_path}")
    return 0


def cmd_init(args):
    """init (new atlas, same configuration again, --force with .bak) or init --join (only the local layer), with
    --name N (default: derived from the organization) and --default (SPEC-0079): the entry N is added or updated and
    the other atlases of this machine do not change. Everything is validated before the first write; credentials
    already declared for the same entry are kept."""
    atlas_path = absolute(args.atlas)
    local_path = local_config_write_path()  # always the new folder (SPEC-0070); credentials come from the read path
    if args.join:
        extra = [flag for flag, given in (("--org", args.org), ("--mode", args.mode), ("--force", args.force),
                                          ("--remote", args.remote)) if given]
        if extra:
            raise AtlasError(f"init --join não aceita {', '.join(extra)}: a organização e o modo vêm do "
                             "atlas-config.yml do atlas", 2)
        return join_atlas(atlas_path, local_path, args.name, args.default)
    if not args.org or not args.mode:
        raise AtlasError("init precisa de --org NOME e --mode repo|local (ou --join para um atlas existente)", 2)
    shared_text = render_atlas_config(args.org, args.mode, args.remote)
    atlas = Path(atlas_path)
    shared = atlas / SHARED_FILE
    if atlas.exists() and not atlas.is_dir():
        raise AtlasError(f"não é uma pasta: {atlas_path}", 2)
    require_readable_atlas(atlas)
    update = updated_local(atlas_path, args.name, args.org.strip(), args.default)

    if shared.is_file():
        current = read_text(shared)
        if current == shared_text:
            write_local_update(local_path, update)
            print(f"Atlas já configurado em {atlas_path}")
            print_entry(update)
            print(f"Configuração local: {local_path}")
            return 0
        if not args.force:
            raise AtlasError("atlas-config.yml já existe — use --join ou --force", 2)
        backup = backup_path(shared)
        backup.write_text(current, encoding="utf-8")
        shared.write_text(shared_text, encoding="utf-8")
        write_local_update(local_path, update)
        print(f"atlas-config.yml substituído em {atlas_path} (anterior em {backup.name})")
        print_entry(update)
        print(f"Configuração local: {local_path}")
        return 0

    if atlas.is_dir() and not is_empty_folder(atlas):
        raise AtlasError(f"pasta não está vazia — escolha outra pasta: {atlas_path}", 2)
    created = create_structure(atlas, args.org.strip(), shared_text)
    write_local_update(local_path, update)
    print(f"Atlas criado em {atlas_path} (modo {args.mode})")
    for name in created:
        print(f"  {name}")
    print_entry(update)
    print(f"Configuração local: {local_path}")
    if args.mode == "local":
        print("Próximo passo: git init na pasta do atlas (o atlas.py não executa o git).")
    return 0


# ---------------------------------------------------------------- config

def describe(value) -> str:
    return fmt_flow(value) if isinstance(value, (dict, list)) else fmt_scalar(value)


def cmd_config_list(as_json, choice=None):
    """config --list [--json]: every atlas of this machine (name, folder, organization, default) and which one would
    be chosen now and why; several atlases without a choice is not an error here ("nenhum")."""
    path, local = read_local()
    config = local_atlases(path, local)
    try:
        name, selected_by = select_atlas(config, choice)
    except NoAtlasChosen:
        name = selected_by = None
    items = [dict(item, organization=organization_of(item["atlas"]) or "?") for item in atlas_list(config)]
    if as_json:
        print(json.dumps({"atlases": items, "atlas_name": name, "selected_by": selected_by}, ensure_ascii=False,
                         indent=2))
        return 0
    for item in items:
        mark = "  [default]" if item["default"] else ""
        print(f"{item['name']}  {item['atlas'] or '(sem pasta)'}  {item['organization']}{mark}")
    print(f"escolhido: {name} ({selected_by})" if name else "escolhido: nenhum")
    return 0


def cmd_set_default(name: str):
    """config --set-default <name>: writes `default: <name>` (multi form); a name that is not configured = exit 2
    without writing; with one entry the file does not change (it already is the default)."""
    path, local = read_local()
    config = local_atlases(path, local)
    entries = config["entries"]
    if name not in entries:
        raise AtlasError(f"atlas não configurado nesta máquina: {name} (atlas configurados: {_names(entries)})", 2)
    if is_default(config, name):
        print(f"{name} já é o atlas padrão desta máquina")
        return 0
    target = local_config_write_path()
    write_local_config(target, render_atlases(entries, name))
    print(f"Atlas padrão desta máquina: {name}")
    print(f"Configuração local: {target}")
    return 0


def cmd_config(args):
    """config [--json] [--atlas X]: effective configuration of the chosen atlas; --list and --set-default
    (SPEC-0079)."""
    if args.list:
        return cmd_config_list(args.json, args.atlas)
    if args.set_default is not None:
        return cmd_set_default(args.set_default)
    config = load_config(choice=args.atlas)
    if args.json:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0
    values, origins = config["values"], config["origins"]
    print(f"boson-atlas {ATLAS_VERSION} — configuração local: {local_config_path()}")
    print(f"atlas: {config['atlas_name']} (escolhido por: {SELECTED_BY_TEXT[config['selected_by']]})")
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


# ---------------------------------------------------------------- probes (references/probes.md, ADR-0023)

PROBE_CONTRACT = "probe@1"
PROBE_CONTRACT_2 = "probe@2"  # SPEC-0096, ADR-0025: targets, access and inputs declared per capability
PROBE_CONTRACTS = (PROBE_CONTRACT, PROBE_CONTRACT_2)
PROBE_TARGETS = ("deployment",) + RESOURCE_KINDS  # the target kinds a probe@2 capability may declare
PROBE_ACCESS = ("cluster", "cloud", "database", "urls")  # the local access blocks, in the order they are checked
PROBE_INPUTS = ("change", "journeys")
PROBE_CLUSTER_FIELDS = ("clusters", "context", "namespace", "workloads")  # only with cluster in access (together)
# the keys of a probes.log line, the one list write_probe_log uses (SPEC-0096): resource and commit only when used
PROBE_LOG_KEYS = ("at", "atlas", "service", "environment", "capability", "verb", "adapter", "status", "exit",
                  "confirmed_production", "resource", "commit")
RESOURCE_ARG_RE = re.compile(r"^(datastore|queue|topic|bucket):(\S+)\Z")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}\Z")
RESOURCE_ATTR_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}\Z")
RESOURCE_TEXT_MAX = 1024
REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-[0-9]{1,2}\Z")
PROBE_KEYS = ("enabled", "limits", "adapters")
PROBE_LIMIT_KEYS = ("lines", "since")
PROBE_ADAPTER_KEYS = ("command", "verbs", "timeout", "credentials")
PROBE_TIMEOUT, PROBE_TIMEOUT_MAX = 60, 300
PROBE_LINES, PROBE_LINES_MAX = 200, 2000
PROBE_SINCE, PROBE_SINCE_MAX = "30m", 24 * 3600
PROBE_MAX_BYTES = 1024 * 1024  # the most read from an adapter's stdout
PROBE_MESSAGE_MAX = 500
PROBE_LOG = "probes.log"
PROBES_DIR = ASSETS_DIR / "probes"  # adapters that come with the skill (an adapter without command)
PROBE_WORD_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}\Z")  # adapter ids, capabilities and verbs
SIMPLE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
# the target fields that come from the atlas (Emenda v4 of SPEC-0088): no adapter gets text that looks like an option
CLUSTER_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://\S+\Z")  # a server URL in target.clusters
DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?\Z")  # DNS-1123 label, up to 63
DNS_SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*\Z")
DNS_SUBDOMAIN_MAX = 253
DURATION_RE = re.compile(r"^(\d{1,6})([smhd])\Z")
DURATION_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
PROBES_OFF = "probes desligadas nesta máquina (probes.enabled) — references/probes.md"
# the environment of an adapter: these names (when set) plus the credentials declared in it, nothing else
PROBE_BASE_ENV = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "TZ", "TMPDIR",
                  "TMP", "TEMP", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE",
                  "APPDATA", "LOCALAPPDATA", "__CF_USER_TEXT_ENCODING")
# personal data and secrets of log lines, on top of SECRET_PATTERNS and redaction.extra_patterns (SPEC-0088)
PROBE_PATTERNS = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),  # e-mail
    re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)"),  # CPF
    re.compile(r"(?<!\d)\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}(?!\d)"),  # CNPJ
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"(?i)\b[\w-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\s*[=:]\s*[^\s,;&\"']+"),
    # cloud account ids (SPEC-0096): only the 12 digits (group "mask") of an ARN (in any case: ARN:AWS:..., Emenda v2
    # of SPEC-0106), of a URL of the cloud and of an ECR registry host (<account>.dkr.ecr.<region>.amazonaws.com[.cn])
    re.compile(r"(?i)\barn:[A-Za-z0-9-]+:[A-Za-z0-9-]+:[A-Za-z0-9-]*:(?P<mask>\d{12})(?![0-9])"),
    re.compile(r"(?i)\bhttps?://[a-z0-9.-]+\.amazonaws\.com(?:\.cn)?/(?P<mask>\d{12})(?![0-9])"),
    re.compile(r"(?i)(?<![0-9])(?P<mask>\d{12})\.dkr\.ecr(?:-fips)?\.[a-z0-9-]+\.amazonaws\.com(?:\.cn)?\b"),
)
LOG_LEVELS = (("error", re.compile(r"(?i)\b(?:error|err|fatal|critical|crit|panic|exception)\b")),
              ("warn", re.compile(r"(?i)\b(?:warn|warning)\b")),
              ("info", re.compile(r"(?i)\binfo\b")))
LEVEL_ORDER = {"error": 0, "warn": 1, "info": 2, "other": 3}
SIGNATURE_RULES = (  # (regex, marker), in this order
    (re.compile(r"\"[^\"]*\"|'[^']*'"), "<texto>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"\b(?:0x)?[0-9a-fA-F]{8,}\b"), "<hex>"),
    (re.compile(r"\d+(?:[.,:]\d+)*"), "<n>"),
)


def _probe_error(field, reason) -> AtlasError:
    """The configuration error of the contract: "probes: <field> inválido — <reason>" (never the value), exit 2."""
    return AtlasError(f"probes: {field} inválido — {reason} (references/probes.md)", 2)


def _key_name(key, fallback) -> str:
    """A key safe to show in a message (a simple name), else `fallback`."""
    return key if isinstance(key, str) and SIMPLE_KEY_RE.match(key) else fallback


def _int_of(value):
    """An integer from int or digit text (parse_yaml keeps scalars as text); None for anything else (bool too)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.match(r"^\d{1,9}\Z", value.strip()):
        return int(value.strip())
    return None


def parse_duration(value):
    """Seconds of a duration like 30s, 30m, 2h or 1d; None when it is not one (or is zero)."""
    match = DURATION_RE.match(str(value).strip()) if isinstance(value, (str, int)) else None
    if not match or isinstance(value, bool):
        return None
    seconds = int(match.group(1)) * DURATION_SECONDS[match.group(2)]
    return seconds or None


def _name_list(value):
    """A list of texts from a list or one text; None when it is neither."""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return None


def _command_head_ok(head: str) -> bool:
    """command[0] is a bare name (looked up in PATH) or an absolute path; a relative path with a folder is not."""
    separators = {"/", os.sep, os.altsep} - {None}
    return os.path.isabs(head) or not any(sep in head for sep in separators)


def _probe_adapter(aid: str, entry) -> dict:
    where = f"adapters.{aid}"
    if entry in (None, ""):
        entry = {}
    if not isinstance(entry, dict):
        raise _probe_error(where, "precisa ser um mapa {command, verbs, timeout, credentials}")
    for key in entry:
        if key not in PROBE_ADAPTER_KEYS:
            raise _probe_error(f"{where}.{_key_name(key, 'chave')}", "chave desconhecida — use command, verbs, "
                               "timeout e credentials")
    command = entry.get("command")
    if command in (None, ""):
        command = None
    elif (not isinstance(command, list) or not command
          or any(not isinstance(arg, str) or not arg or any(is_control(c) for c in arg) for arg in command)):
        raise _probe_error(f"{where}.command", "precisa ser uma lista não vazia [executável, argumentos...] "
                           "(sem shell)")
    if command and not _command_head_ok(command[0]):
        raise _probe_error(f"{where}.command", "o executável é um nome sem pasta (procurado no PATH) ou um caminho "
                           "absoluto, nunca um caminho relativo")
    verbs = _name_list(entry.get("verbs"))
    if verbs is None or any(not PROBE_WORD_RE.match(verb) for verb in verbs):
        raise _probe_error(f"{where}.verbs", "cada verbo é uma palavra minúscula, sem espaço (letras, dígitos, - "
                           "e _)")
    timeout = entry.get("timeout")
    if timeout in (None, ""):
        timeout = PROBE_TIMEOUT
    else:
        timeout = _int_of(timeout)
        if timeout is None or not 1 <= timeout <= PROBE_TIMEOUT_MAX:
            raise _probe_error(f"{where}.timeout", f"precisa ser um número inteiro de segundos, de 1 a "
                               f"{PROBE_TIMEOUT_MAX}")
    credentials = _name_list(entry.get("credentials"))
    if credentials is None or any(not ENV_NAME_RE.match(name) for name in credentials):
        raise _probe_error(f"{where}.credentials", "aceita só nomes de variável de ambiente (^[A-Z_][A-Z0-9_]*$), "
                           "nunca valores (ADR-0010)")
    return {"command": list(command) if command else None, "verbs": list(dict.fromkeys(verbs)),
            "timeout": timeout, "credentials": list(dict.fromkeys(credentials))}


def validate_probes(probes):
    """The local `probes` key of one atlas entry (SPEC-0088), normalized: {"enabled", "limits": {"lines", "since",
    "since_seconds"}, "adapters": {<id>: {"command" | None, "verbs", "timeout", "credentials"}}}; None without the
    key. Invalid = AtlasError (code 2) "probes: <campo> inválido — <motivo>", never the value."""
    if probes is None:
        return None
    if probes == "":
        probes = {}
    if not isinstance(probes, dict):
        raise _probe_error("probes", "precisa ser um mapa {enabled, limits, adapters}")
    for key in probes:
        if key not in PROBE_KEYS:
            raise _probe_error(_key_name(key, "chave"), "chave desconhecida — use enabled, limits e adapters")
    enabled = probes.get("enabled")
    if enabled in (None, ""):
        enabled = False
    elif not isinstance(enabled, bool):
        text = str(enabled).strip().lower()
        if text not in BOOLEANS:
            raise _probe_error("enabled", "use true ou false")
        enabled = BOOLEANS[text]
    limits = probes.get("limits")
    if limits in (None, ""):
        limits = {}
    if not isinstance(limits, dict):
        raise _probe_error("limits", "precisa ser um mapa {lines, since}")
    for key in limits:
        if key not in PROBE_LIMIT_KEYS:
            raise _probe_error(f"limits.{_key_name(key, 'chave')}", "chave desconhecida — use lines e since")
    lines = limits.get("lines")
    lines = PROBE_LINES if lines in (None, "") else _int_of(lines)
    if lines is None or not 1 <= lines <= PROBE_LINES_MAX:
        raise _probe_error("limits.lines", f"precisa ser um número inteiro de 1 a {PROBE_LINES_MAX}")
    since = limits.get("since")
    since = PROBE_SINCE if since in (None, "") else since
    seconds = parse_duration(since)
    if seconds is None or seconds > PROBE_SINCE_MAX:
        raise _probe_error("limits.since", "precisa ser uma duração como 30m ou 2h, até 24h")
    adapters = probes.get("adapters")
    if adapters in (None, ""):
        adapters = {}
    if not isinstance(adapters, dict):
        raise _probe_error("adapters", "precisa ser um mapa <id>: {command, verbs, timeout, credentials}")
    result = {}
    for position, (aid, entry) in enumerate(adapters.items(), start=1):
        if not isinstance(aid, str) or not PROBE_WORD_RE.match(aid):
            raise _probe_error(f"adapters[{position}]", "o id do adaptador é uma palavra minúscula (letras, dígitos, "
                               "- e _)")
        result[aid] = _probe_adapter(aid, entry)
    return {"enabled": enabled, "limits": {"lines": lines, "since": str(since).strip(), "since_seconds": seconds},
            "adapters": result}


def probes_view(probes) -> dict:
    """What config shows of `probes` (the defaults without the key): names only, never a credential value."""
    probes = probes or {"enabled": False, "limits": {"lines": PROBE_LINES, "since": PROBE_SINCE}, "adapters": {}}
    adapters = {}
    for aid, adapter in probes["adapters"].items():
        adapters[aid] = {"command": adapter["command"] if adapter["command"] else "(embutido na skill)",
                         "verbs": adapter["verbs"], "timeout": adapter["timeout"],
                         "credentials": adapter["credentials"]}
    return {"enabled": probes["enabled"],
            "limits": {"lines": probes["limits"]["lines"], "since": probes["limits"]["since"]},
            "adapters": adapters}


def adapter_command(aid: str, adapter: dict):
    """The argv of an adapter: its command, or the adapter of the skill (assets/probes/<id>.py) when it has none;
    None when neither exists. Never built from text of the atlas (ADR-0023)."""
    if adapter["command"]:
        return list(adapter["command"])
    bundled = PROBES_DIR / f"{aid}.py"
    return [sys.executable, str(bundled)] if bundled.is_file() else None


def probe_environment(adapter: dict, passfile=None) -> dict:
    """The environment of an adapter: PROBE_BASE_ENV plus the credentials declared in it (by name, ADR-0010); a
    name declared only for another adapter or for the collectors never reaches it. `passfile`: PGPASSFILE, only for
    a capability that declares database (SPEC-0096); no other variable is added."""
    names = list(PROBE_BASE_ENV) + list(adapter["credentials"])
    environment = {name: os.environ[name] for name in names if name in os.environ}
    if passfile:
        environment["PGPASSFILE"] = passfile
    return environment


def probe_extras(shared) -> list:
    """Compiled patterns of the probe redaction: the valid redaction.extra_patterns plus PROBE_PATTERNS."""
    compiled, _ = _extra_patterns(shared or {})
    return [regex for _, regex in compiled] + list(PROBE_PATTERNS)


def probe_mask(value, extras):
    """value with every secret or personal datum replaced by [REDACTED] (redact + PROBE_PATTERNS)."""
    return redact(value, extras)[0]


# ---------------------------------------------------------------- probe@1 contract (validators)

def _show(key) -> str:
    return str(key)[:64] if isinstance(key, str) else f"<{type(key).__name__}>"


def _closed_keys(data: dict, allowed, required, where="") -> list:
    prefix = f"{where}." if where else ""
    problems = [f"chave fora do contrato: {prefix}{_show(key)}" for key in data if key not in allowed]
    problems += [f"falta a chave {prefix}{key}" for key in required if key not in data]
    return problems


def _contract_problem(data) -> list:
    return [] if data.get("contract") in PROBE_CONTRACTS else ["contract precisa ser probe@1 ou probe@2"]


def _word_problem(value, what) -> list:
    if not isinstance(value, str) or not PROBE_WORD_RE.match(value):
        return [f"{what} precisa ser uma palavra minúscula, sem espaço (letras, dígitos, - e _)"]
    return []


def _choice_list_problems(value, key, allowed, where, required) -> list:
    """Problems of one list of a probe@2 capability (targets, access, inputs): a list (not empty when `required`)
    of the `allowed` words, without repetition."""
    if not isinstance(value, list) or (required and not value):
        return [f"{where}.{key} precisa ser uma lista{' não vazia' if required else ''} de {', '.join(allowed)}"]
    if any(not isinstance(item, str) or item not in allowed for item in value):
        return [f"{where}.{key} aceita só {', '.join(allowed)}"]
    if len(set(value)) != len(value):
        return [f"{where}.{key} tem item repetido"]
    return []


def _capability2_problems(cap, value) -> list:
    """Problems of one capability of a probe@2 description: {verbs, targets, access?, inputs?} (SPEC-0096)."""
    where = f"capabilities.{_show(cap)}"
    if not isinstance(value, dict):
        return [f"{where} precisa ser um objeto {{verbs, targets, access, inputs}}"]
    problems = _closed_keys(value, ("verbs", "targets", "access", "inputs"), ("verbs", "targets"), where)
    if "verbs" in value:
        verbs = value["verbs"]
        if not isinstance(verbs, list) or not verbs:
            problems.append(f"{where}.verbs precisa ser uma lista não vazia de verbos")
        else:
            for verb in verbs:
                problems += _word_problem(verb, f"um verbo de {where}")
    for key, allowed, required in (("targets", PROBE_TARGETS, True), ("access", PROBE_ACCESS, False),
                                   ("inputs", PROBE_INPUTS, False)):
        if key in value:
            problems += _choice_list_problems(value[key], key, allowed, where, required)
    access = value.get("access")
    if isinstance(access, list) and "database" in access and value.get("targets") != ["datastore"]:
        problems.append(f"{where}: database em access só com targets [datastore]")
    return problems


def validate_probe_describe(data) -> list:
    """Problems of the answer of `<command> --describe` (probe@1 or probe@2); [] = valid. Never quotes a value."""
    if not isinstance(data, dict):
        return ["a descrição precisa ser um objeto JSON"]
    problems = _closed_keys(data, ("contract", "adapter", "capabilities"), ("contract", "adapter", "capabilities"))
    problems += _contract_problem(data)
    if "adapter" in data:
        problems += _word_problem(data["adapter"], "adapter")
    capabilities = data.get("capabilities")
    if "capabilities" in data:
        if not isinstance(capabilities, dict) or not capabilities:
            problems.append("capabilities precisa ser um mapa não vazio <capacidade>: [verbos]")
        else:
            for cap, verbs in capabilities.items():
                problems += _word_problem(cap, "o nome de uma capacidade")
                if data.get("contract") == PROBE_CONTRACT_2:
                    problems += _capability2_problems(cap, verbs)
                    continue
                if not isinstance(verbs, list) or not verbs:
                    problems.append(f"capabilities.{_show(cap)} precisa ser uma lista não vazia de verbos")
                    continue
                for verb in verbs:
                    problems += _word_problem(verb, f"um verbo de capabilities.{_show(cap)}")
    return problems


def capability_spec(described: dict, capability: str):
    """The capability of a valid description, normalized: {"contract", "verbs", "targets", "access", "inputs"}; a
    probe@1 capability accepts only a deployment and needs the cluster (SPEC-0096). None when not declared."""
    value = described["capabilities"].get(capability)
    if value is None:
        return None
    if described["contract"] == PROBE_CONTRACT:
        return {"contract": PROBE_CONTRACT, "verbs": list(value), "targets": ["deployment"], "access": ["cluster"],
                "inputs": []}
    return {"contract": PROBE_CONTRACT_2, "verbs": list(value["verbs"]), "targets": list(value["targets"]),
            "access": list(value.get("access") or []), "inputs": list(value.get("inputs") or [])}


def _text_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def _text_problem(value, where) -> list:
    return [] if isinstance(value, str) and value else [f"{where} precisa ser um texto não vazio"]


def _block_problems(target: dict, key: str, fields) -> list:
    """Problems of one object of a probe@2 target whose keys are exactly `fields`, each a non-empty text."""
    where = f"target.{key}"
    value = target[key]
    if not isinstance(value, dict):
        return [f"{where} precisa ser um objeto {{{', '.join(fields)}}}"]
    problems = _closed_keys(value, fields, fields, where)
    for field in fields:
        if field in value:
            problems += _text_problem(value[field], f"{where}.{field}")
    return problems


def _resource_problems(resource) -> list:
    if not isinstance(resource, dict):
        return ["target.resource precisa ser um objeto {kind, id, attrs}"]
    problems = _closed_keys(resource, ("kind", "id", "attrs"), ("kind", "id", "attrs"), "target.resource")
    if "kind" in resource and resource["kind"] not in RESOURCE_KINDS:
        problems.append(f"target.resource.kind precisa ser {', '.join(RESOURCE_KINDS)}")
    if "id" in resource:
        problems += _text_problem(resource["id"], "target.resource.id")
    attrs = resource.get("attrs")
    if "attrs" in resource:
        if not isinstance(attrs, dict):
            problems.append("target.resource.attrs precisa ser um objeto")
        elif any(not isinstance(k, str) or isinstance(v, (type(None), list, dict)) or not _probe_scalar(v)
                 for k, v in attrs.items()):
            problems.append("target.resource.attrs aceita só valores escalares (texto, número, booleano)")
    return problems


def _change_problems(change) -> list:
    if not isinstance(change, dict):
        return ["target.change precisa ser um objeto {commit, repositories}"]
    problems = _closed_keys(change, ("commit", "repositories"), ("commit", "repositories"), "target.change")
    if "commit" in change and not (isinstance(change["commit"], str) and COMMIT_RE.match(change["commit"])):
        problems.append("target.change.commit precisa ser um sha de 7 a 40 caracteres hexadecimais minúsculos")
    if "repositories" in change and not (_text_list(change["repositories"]) and change["repositories"]):
        problems.append("target.change.repositories precisa ser uma lista não vazia de textos")
    return problems


def _target2_problems(target: dict) -> list:
    """Problems of the target of a probe@2 input (SPEC-0096): the base fields, and each optional block closed."""
    base = ("service", "environment", "deployment")
    optional = ("resource",) + PROBE_CLUSTER_FIELDS + ("cloud", "database", "urls", "change", "journeys")
    problems = _closed_keys(target, base + optional, base, "target")
    for key in base:
        if key in target:
            problems += _text_problem(target[key], f"target.{key}")
    present = [key for key in PROBE_CLUSTER_FIELDS if key in target]
    if present and len(present) != len(PROBE_CLUSTER_FIELDS):
        problems.append("target.clusters, target.context, target.namespace e target.workloads vêm juntos")
    if "context" in target:
        problems += _text_problem(target["context"], "target.context")
    if "namespace" in target and not isinstance(target["namespace"], str):
        problems.append("target.namespace precisa ser um texto")
    for key in ("clusters", "workloads"):
        if key in target and not _text_list(target[key]):
            problems.append(f"target.{key} precisa ser uma lista de textos")
    if "resource" in target:
        problems += _resource_problems(target["resource"])
    for key, fields in (("cloud", ("profile",)), ("database", ("user", "name", "passfile")), ("urls", ("base_url",))):
        if key in target:
            problems += _block_problems(target, key, fields)
    if "change" in target:
        problems += _change_problems(target["change"])
    if "journeys" in target and not (isinstance(target["journeys"], list)
                                     and all(isinstance(j, str) and j for j in target["journeys"])):
        problems.append("target.journeys precisa ser uma lista de textos")
    return problems


def validate_probe_input(data) -> list:
    """Problems of the input written to an adapter's stdin (probe@1 or probe@2); [] = valid."""
    if not isinstance(data, dict):
        return ["a entrada precisa ser um objeto JSON"]
    keys = ("contract", "capability", "verb", "target", "limits")
    problems = _closed_keys(data, keys, keys) + _contract_problem(data)
    for key in ("capability", "verb"):
        if key in data:
            problems += _word_problem(data[key], key)
    target = data.get("target")
    if "target" in data:
        if not isinstance(target, dict):
            problems.append("target precisa ser um objeto")
        elif data.get("contract") == PROBE_CONTRACT_2:
            problems += _target2_problems(target)
        else:
            fields = ("service", "environment", "deployment") + PROBE_CLUSTER_FIELDS
            problems += _closed_keys(target, fields, fields, "target")
            for key in ("service", "environment", "deployment", "context"):
                if key in target and (not isinstance(target[key], str) or not target[key]):
                    problems.append(f"target.{key} precisa ser um texto não vazio")
            if "namespace" in target and not isinstance(target["namespace"], str):
                problems.append("target.namespace precisa ser um texto")
            for key in ("clusters", "workloads"):
                if key in target and not _text_list(target[key]):
                    problems.append(f"target.{key} precisa ser uma lista de textos")
    limits = data.get("limits")
    if "limits" in data:
        if not isinstance(limits, dict):
            problems.append("limits precisa ser um objeto {lines, since_seconds}")
        else:
            problems += _closed_keys(limits, ("lines", "since_seconds"), ("lines", "since_seconds"), "limits")
            for key, top in (("lines", PROBE_LINES_MAX), ("since_seconds", PROBE_SINCE_MAX)):
                value = limits.get(key)
                if key in limits and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= top):
                    problems.append(f"limits.{key} precisa ser um inteiro de 1 a {top}")
    return problems


def _probe_scalar(value) -> bool:
    return isinstance(value, (str, int, float, bool, type(None)))


def validate_probe_output(data) -> list:
    """Problems of the JSON an adapter prints (probe@1 or probe@2); [] = valid: closed keys, status ok | error, items as a
    list of objects whose values are scalars or lists of scalars. Never quotes a value (key names only)."""
    if not isinstance(data, dict):
        return ["a saída precisa ser um objeto JSON"]
    allowed = ("contract", "adapter", "capability", "verb", "status", "items", "truncated", "message")
    problems = _closed_keys(data, allowed, allowed[:-1]) + _contract_problem(data)
    for key in ("adapter", "capability", "verb"):
        if key in data:
            problems += _word_problem(data[key], key)
    if "status" in data and data["status"] not in ("ok", "error"):
        problems.append("status precisa ser ok ou error")
    if "truncated" in data and not isinstance(data["truncated"], bool):
        problems.append("truncated precisa ser true ou false")
    if "message" in data and not isinstance(data["message"], str):
        problems.append("message precisa ser um texto")
    items = data.get("items")
    if "items" in data:
        if not isinstance(items, list):
            problems.append("items precisa ser uma lista de objetos")
        else:
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    problems.append(f"items[{index}] precisa ser um objeto")
                    continue
                for key, value in item.items():
                    if not isinstance(key, str) or not key:
                        problems.append(f"items[{index}] tem uma chave que não é texto")
                    elif not (_probe_scalar(value) or (isinstance(value, list)
                                                         and all(_probe_scalar(v) for v in value))):
                        problems.append(f"items[{index}].{_show(key)} precisa ser escalar ou lista de escalares")
    return problems


# ---------------------------------------------------------------- probe: summary of log lines

def log_level(line: str) -> str:
    for level, regex in LOG_LEVELS:
        if regex.search(line):
            return level
    return "other"


def log_signature(line: str) -> str:
    """The line with quoted text, e-mails, UUIDs, hexadecimals of 8 or more and numbers replaced by markers."""
    for regex, marker in SIGNATURE_RULES:
        line = regex.sub(marker, line)
    return line


def summarize_log(items: list) -> list:
    """--summary: the items with "line" grouped by (level, signature) into {"signature", "level", "count",
    "first_ts", "last_ts", "sample"}, sorted by level (error, warn, info, other), count (desc) and signature."""
    groups = {}
    for item in items:
        line = item.get("line")
        if not isinstance(line, str):
            continue
        ts = item.get("ts") if isinstance(item.get("ts"), str) else ""
        key = (log_level(line), log_signature(line))
        group = groups.setdefault(key, {"signature": key[1], "level": key[0], "count": 0, "first_ts": ts,
                                        "last_ts": ts, "sample": line})
        group["count"] += 1
        if ts and (not group["first_ts"] or ts < group["first_ts"]):
            group["first_ts"] = ts
        if ts and (not group["last_ts"] or ts > group["last_ts"]):
            group["last_ts"] = ts
    return sorted(groups.values(), key=lambda g: (LEVEL_ORDER[g["level"]], -g["count"], g["signature"]))


# ---------------------------------------------------------------- probe: the command

def probe_log_path() -> Path:
    """<folder of this machine's local configuration>/probes.log (never in the atlas, ADR-0023)."""
    return local_config_write_path().parent / PROBE_LOG


def write_probe_log(record: dict, extras) -> None:
    """Appends one JSON line with the keys of PROBE_LOG_KEYS that the record has (resource and commit only when
    used, SPEC-0096): never items, message, the context nor any access value."""
    line = {key: record[key] for key in PROBE_LOG_KEYS if key in record}
    line = probe_mask(line, extras)
    path = probe_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as e:
        print(f"aviso: não consegui gravar o registro local {path}: {e.strerror or e}", file=sys.stderr)


def _probe_limits(args, probes) -> tuple:
    """(lines, since_seconds) from --lines/--since or probes.limits; out of range = AtlasError (code 2)."""
    lines = probes["limits"]["lines"]
    if args.lines is not None:
        lines = _int_of(args.lines)
        if lines is None or not 1 <= lines <= PROBE_LINES_MAX:
            raise AtlasError(f"--lines precisa ser um número inteiro de 1 a {PROBE_LINES_MAX}", 2)
    seconds = probes["limits"]["since_seconds"]
    if args.since is not None:
        seconds = parse_duration(args.since)
        if seconds is None or seconds > PROBE_SINCE_MAX:
            raise AtlasError("--since inválido — use uma duração como 30m ou 2h, até 24h", 2)
    return lines, seconds


def read_probe_graph(atlas: Path) -> dict:
    """graph.json of the atlas for a probe; without one = AtlasError (code 2)."""
    graph = read_json_file(atlas / GRAPH_FILE)
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(
            graph.get("edges"), list):
        raise AtlasError("atlas sem graph.json — rode scan e build", 2)
    return graph


def _service_key(index, service: str) -> str:
    """The key of service <service>: service:<service>, else the first service named <service>."""
    key = f"service:{service}"
    if key not in index.nodes:
        key = next((k for k, node in sorted(index.nodes.items())
                    if node["kind"] == "service" and node.get("name") == service), key)
    return key


def _environment_deployments(index, service: str, environment: str) -> list:
    """[(deployment key, environment id)] of the deployments of service <service> that run_in environment
    <environment> (by id or name), sorted by key: the one rule of probe_targets and linked_resources."""
    found = []
    for deployment in sorted(index.sources(_service_key(index, service), "deploys", "deployment")):
        for env in index.targets(deployment, "runs_in", "environment"):
            eid = env.split(":", 1)[1]
            if environment in (eid, index.name(env)):
                found.append((deployment, eid))
                break
    return found


def probe_targets(atlas: Path, service: str, environment: str, graph=None) -> list:
    """Every deployment of service:<service> that runs_in environment:<environment>, from graph.json, sorted by id:
    [{"deployment", "environment", "clusters", "cluster_ids", "namespace", "workloads", "config_repositories"}].
    None found = AtlasError (code 2) naming what was looked for."""
    index = _Index(graph if graph is not None else read_probe_graph(atlas))
    found = _environment_deployments(index, service, environment)
    if not found:
        raise AtlasError(f"nenhum deployment de service:{service} em environment:{environment} no atlas (veja "
                         "`context` ou rode scan e build)", 2)
    targets = []
    for deployment, eid in found:
        attrs = index.nodes.get(deployment, {}).get("attrs", {})
        clusters = index.targets(deployment, "runs_in", "cluster")
        workloads = attrs.get("workloads") if isinstance(attrs.get("workloads"), list) else []
        repositories = index.targets(deployment, "sourced_from", "repository")
        targets.append({"deployment": deployment.split(":", 1)[1], "environment": eid,
                        "clusters": sorted({index.name(c) for c in clusters}),
                        "cluster_ids": {index.name(c): c.split(":", 1)[1] for c in clusters},
                        "namespace": attrs["namespace"] if isinstance(attrs.get("namespace"), str) else "",
                        "workloads": sorted({str(w) for w in workloads if isinstance(w, str) and w}),
                        "config_repositories": sorted(r.split(":", 1)[1] for r in repositories)})
    return targets


def linked_resources(graph: dict, service: str, env: str) -> list:
    """The resources (datastore, queue, topic, bucket) linked to the deployments of service <service> in environment
    <env> (ADR-0025, rule 1), from the graph already read and nothing else: for each deployment D, in id order, (1)
    an edge D -> R of type depends_on, reads, writes, publishes or consumes; (2) a config_refs item of D that rule 2
    of build resolves to R (config_ref_targets, the same matching); (3) the queue named by the text `dlq` attr of a
    queue of (1) or (2) (dlq). [{"resource", "relation", "deployment"}] without repetition, sorted by (deployment,
    resource, relation); [] when nothing links. The one function of --resource and of verify@2 (SPEC-0096)."""
    index = _Index(graph)
    hosts = config_ref_targets(graph["nodes"])

    def resource(key):
        return key in index.nodes and index.nodes[key].get("kind") in RESOURCE_KINDS

    found = set()
    for deployment, _ in _environment_deployments(index, service, env):
        linked = [(r, rtype) for rtype in DEPENDENCY_TYPES for r in index.targets(deployment, rtype) if resource(r)]
        refs = (index.nodes.get(deployment, {}).get("attrs") or {}).get("config_refs")
        for ref in (refs if isinstance(refs, list) else []):
            if isinstance(ref, str):
                linked += [(r, "config_ref") for r in hosts.get(_host_of(ref), []) if resource(r)]
        for key, _ in list(linked):
            if index.nodes[key].get("kind") != "queue":
                continue
            dlq = (index.nodes[key].get("attrs") or {}).get("dlq")
            target = f"queue:{dlq}" if isinstance(dlq, str) and dlq else None
            if target and target != key and target in index.nodes and index.nodes[target].get("kind") == "queue":
                linked.append((target, "dlq"))
        found |= {(deployment.split(":", 1)[1], key, relation) for key, relation in linked}
    return [{"resource": key, "relation": relation, "deployment": deployment}
            for deployment, key, relation in sorted(found)]


def _resource_attrs(node: dict, rid: str) -> tuple:
    """(problem, attrs) of the node of a --resource (SPEC-0096): attrs = only its scalar attributes (text, number,
    boolean); a key out of ^[a-z][a-z0-9_]{0,63}$, a text over 1024, with a control character or starting with -,
    a region out of the rule or a dlq out of the name rule is a problem (fixed text, never the value)."""
    if not ENVIRONMENT_NAME_RE.match(rid):
        return "id fora da regra de nome (letras, dígitos, . _ -, sem espaço, sem começar com -)", None
    attrs = {}
    raw = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
    for key, value in raw.items():
        if value is None or isinstance(value, (list, dict)) or not _probe_scalar(value):
            continue
        if isinstance(value, float) and not math.isfinite(value):
            continue
        if not isinstance(key, str) or not RESOURCE_ATTR_KEY_RE.match(key):
            return "attrs com uma chave fora da regra (^[a-z][a-z0-9_]{0,63}$)", None
        if isinstance(value, str):
            if len(value) > RESOURCE_TEXT_MAX:
                return f"{key} com mais de {RESOURCE_TEXT_MAX} caracteres", None
            if any(is_control(c) for c in value):
                return f"{key} com quebra de linha ou caractere de controle", None
            if value.startswith("-"):
                return f"{key} começa com -", None
            if key == "dlq" and not ENVIRONMENT_NAME_RE.match(value):
                return "dlq fora da regra de nome (o id de outra fila)", None
        if key == "region" and not (isinstance(value, str) and REGION_RE.match(value)):
            return "region fora da regra (como us-east-1)", None
        attrs[key] = value
    return None, attrs


def probe_resource(graph: dict, service: str, env: str, kind: str, rid: str) -> tuple:
    """(target.resource, id of the deployment that links it) of --resource <kind>:<rid> (SPEC-0096): the node must
    exist, be in linked_resources(graph, service, env) (its first entry gives the deployment) and have its
    attributes in the rules. Otherwise AtlasError (code 2), before any process runs."""
    key = f"{kind}:{rid}"
    node = next((n for n in graph["nodes"] if isinstance(n, dict) and n.get("key") == key), None)
    if node is None or node.get("kind") != kind:
        raise AtlasError(f"recurso {key} não existe no atlas (veja `context` ou rode scan e build)", 2)
    links = [link for link in linked_resources(graph, service, env) if link["resource"] == key]
    if not links:
        raise AtlasError(f"recurso {key} não ligado a {service} em {env} (ADR-0025: só um recurso ligado ao "
                         "deployment do serviço no ambiente)", 2)
    problem, attrs = _resource_attrs(node, rid)
    if problem:
        raise AtlasError(f"alvo inválido no atlas: resource.{problem} — corrija o atlas (references/probes.md)", 2)
    return {"kind": kind, "id": rid, "attrs": attrs}, links[0]["deployment"]


def probe_change_repositories(graph: dict, service: str) -> list:
    """delivery.code_repositories of the service (SPEC-0086: the repositories inferred from the image), for
    target.change; none, or an id out of <dono>/<nome>, = AtlasError (code 2)."""
    index = _Index(graph)
    key = _service_key(index, service)
    repositories = sorted({e["to"].split(":", 1)[1] for e in _code_edges(key, index)})
    if not repositories:
        raise AtlasError(f"nenhum repositório de código de service:{service} no atlas para --commit (veja "
                         "`context`)", 2)
    for repository in repositories:
        owner, sep, name = repository.partition("/")
        if not sep or not ENVIRONMENT_NAME_RE.match(owner) or not ENVIRONMENT_NAME_RE.match(name):
            raise AtlasError("alvo inválido no atlas: change.repositories com um id fora de <dono>/<nome> — corrija "
                             "o atlas (references/probes.md)", 2)
    return repositories


def probe_journeys(graph: dict, service: str) -> list:
    """The `journeys` attr of the service (curated ids, ADR-0026), without repetition, in order; [] without it. Not a
    list, or an id out of the simple name rule = AtlasError (code 2), never the value."""
    index = _Index(graph)
    node = index.nodes.get(_service_key(index, service)) or {}
    journeys = (node.get("attrs") or {}).get("journeys")
    if journeys is None:
        return []
    if not isinstance(journeys, list) or any(not isinstance(j, str) or not ENVIRONMENT_NAME_RE.match(j)
                                             for j in journeys):
        raise AtlasError("alvo inválido no atlas: journeys com um id fora da regra de nome (letras, dígitos, . _ -, "
                         "sem espaço) — corrija o atlas (references/probes.md)", 2)
    return list(dict.fromkeys(journeys))


def _adapter_failure(aid, step, error: CollectorError, extras) -> AtlasError:
    tail = stderr_tail(error.stderr, extras)
    detail = probe_mask(error.reason, extras)
    text = f"adaptador {aid}: {step} falhou — {detail}"
    if tail:
        text += "\n" + "\n".join(f"  {line}" for line in tail)
    return AtlasError(text, 1)


def _reject_surrogates(data) -> None:
    """ValueError when a string (key or value) of the adapter output has a lone surrogate (no UTF-8; Emenda v5)."""
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError("surrogate solto") from None
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _reject_constant(name):
    raise ValueError(f"{name} não é JSON padrão")


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("número fora do JSON padrão")
    return value


def literal_variants(value: str) -> set:
    """The forms of a value that the literal mask catches (Emenda v5): raw, escaped as inside a JSON string (ASCII
    or not, with or without "/" as "\\/") and URL-encoded (no safe characters)."""
    forms = {value, urllib.parse.quote(value, safe="")}
    for ascii_only in (True, False):
        escaped = json.dumps(value, ensure_ascii=ascii_only)[1:-1]
        forms |= {escaped, escaped.replace("/", "\\/")}
    return {form for form in forms if form}


def literal_masks(values) -> list:
    """Patterns that mask each non-empty value literally (the context and the declared credentials, Emenda v4), in
    every form of literal_variants and without case difference (Emenda v5). They match the original text together
    with the secret patterns and the spans are joined (Emenda v6), so neither breaks the other."""
    forms = set()
    for value in values:
        if isinstance(value, str) and value:
            forms |= literal_variants(value)
    unique = sorted(forms, key=lambda form: (-len(form), form))
    return [re.compile(re.escape(form), re.IGNORECASE) for form in unique]


def adapter_values(adapter: dict) -> list:
    """The values (in this environment) of the credentials declared in the adapter."""
    return [os.environ.get(name, "") for name in adapter["credentials"]]


def cluster_problem(cluster) -> bool:
    """True when a target.clusters entry is neither a simple name (ENVIRONMENT_NAME_RE) nor a server URL without
    space or control character and not starting with - (Emenda v5)."""
    if not isinstance(cluster, str):
        return True
    if ENVIRONMENT_NAME_RE.match(cluster):
        return False
    return (cluster.startswith("-") or not CLUSTER_URL_RE.match(cluster)
            or any(ch.isspace() or not ch.isprintable() for ch in cluster))


def target_problem(target: dict, service: str):
    """Why a target field from the atlas is out of the rules of Emenda v4 (fixed text, never the value), or None:
    namespace a DNS-1123 label, each workload Kind/name (name a DNS-1123 subdomain, Kind not starting with -),
    service, deployment and environment by the simple name rule (ENVIRONMENT_NAME_RE); each cluster by
    cluster_problem (Emenda v5)."""
    for what, value in (("service", service), ("environment", target["environment"]),
                        ("deployment", target["deployment"])):
        if not isinstance(value, str) or not ENVIRONMENT_NAME_RE.match(value):
            return f"{what} fora da regra de nome (letras, dígitos, . _ -, sem espaço, sem começar com -)"
    namespace = target["namespace"]
    if namespace and not DNS_LABEL_RE.match(namespace):
        return "namespace fora do DNS-1123 (minúsculas, dígitos e -, até 63, sem começar ou terminar com -)"
    for workload in target["workloads"]:
        kind, sep, name = workload.partition("/")
        if (not sep or not kind or kind.startswith("-") or len(name) > DNS_SUBDOMAIN_MAX
                or not DNS_SUBDOMAIN_RE.match(name)):
            return ("workload fora de Kind/nome (o nome em DNS-1123 subdomínio, até 253; nenhum dos dois começa "
                    "com -)")
    if any(cluster_problem(cluster) for cluster in target["clusters"]):
        return ("cluster fora da regra de nome (letras, dígitos, . _ -) ou de URL de servidor (sem espaço, sem "
                "caractere de controle, sem começar com -)")
    return None


def _run_adapter(aid, argv, adapter, extras, input_text=None, contract=PROBE_CONTRACT, passfile=None) -> dict:
    """Runs one adapter (run_collector: list, no shell, timeout, 1 MB) and parses its JSON; failure = exit 1."""
    step = "--describe" if input_text is None else "a consulta"
    try:
        stdout, _ = run_collector(argv, timeout=adapter["timeout"], env=probe_environment(adapter, passfile),
                                  input_text=input_text, max_bytes=PROBE_MAX_BYTES)
    except CollectorError as e:
        raise _adapter_failure(aid, step, e, extras) from None
    try:
        data = json.loads(stdout, parse_constant=_reject_constant, parse_float=_finite_float)
        _reject_surrogates(data)
        return data
    except (ValueError, RecursionError):  # also NaN/Infinity, numbers out of range and deep nesting (Emenda v4)
        raise AtlasError(f"adaptador {aid}: {step} — a saída não é JSON válido (contrato {contract})",
                         1) from None


def _contract_failure(aid, what, problems, extras, contract=PROBE_CONTRACT) -> AtlasError:
    shown = probe_mask(problems[:10], extras)
    return AtlasError(f"adaptador {aid}: {what} fora do contrato {contract} — {'; '.join(shown)}", 1)


def choose_adapter(probes, capability, extras, literals, kind="deployment") -> tuple:
    """(id, adapter, argv, capability_spec) of the first adapter whose --describe declares the capability and
    accepts the target `kind` (deployment, or the kind of --resource; a probe@1 adapter accepts only deployment,
    SPEC-0096); none = AtlasError (code 4). The core appends --describe to the end of the command. `extras` are the
    secret patterns; `literals` the values masked literally with them, in one pass (Emenda v6 of SPEC-0088)."""
    for aid, adapter in probes["adapters"].items():
        argv = adapter_command(aid, adapter)
        if argv is None:
            raise AtlasError(f"probes: adapters.{aid}.command inválido — sem command e a skill não traz o adaptador "
                             f"{aid}", 2)
        masks = extras + literal_masks(literals + adapter_values(adapter))
        described = _run_adapter(aid, argv + ["--describe"], adapter, masks)
        problems = validate_probe_describe(described)
        if problems:
            contract = described.get("contract") if described.get("contract") in PROBE_CONTRACTS else PROBE_CONTRACT
            raise _contract_failure(aid, "--describe", problems, masks, contract)
        spec = capability_spec(described, capability)
        if spec and kind in spec["targets"]:
            return aid, adapter, argv, spec
    if kind != "deployment":
        raise AtlasError(f"nenhum adaptador para {capability} com alvo {kind} (probes.adapters)", 4)
    raise AtlasError(f"nenhum adaptador para {capability} (probes.adapters)", 4)


def _item_line(item: dict) -> str:
    parts = []
    for key, value in item.items():
        shown = ", ".join(_fmt_value(v) for v in value) if isinstance(value, list) else _fmt_value(value)
        parts.append(f"{key}: {shown}")
    return " · ".join(parts)


def print_probe(result: dict, request: dict, summary: bool) -> None:
    count = len(result["items"])
    head = (f"probe {request['capability']} {request['verb']} — {request['service']} em {request['environment']} "
            f"(deployment {request['deployment']}), adaptador {result['adapter']}: {result['status']}, "
            f"{count} {'assinatura(s)' if summary else 'item(ns)'}")
    print(head + (" — truncado" if result["truncated"] else ""))
    for item in result["items"]:
        if summary:
            print(f"- [{item['level']}] ×{item['count']} {item['signature']} ({item['first_ts']} → {item['last_ts']})")
            print(f"  exemplo: {item['sample']}")
        else:
            print(f"- {_item_line(item)}")
    if result.get("message"):
        print(f"mensagem: {result['message']}")


def _probe_arguments(args, record: dict) -> tuple:
    """(kind, id, commit) of --resource and --commit (SPEC-0096), checked before anything is read: --resource as
    <kind>:<id> with kind datastore, queue, topic or bucket; --commit in lower case, 7 to 40 hexadecimal
    characters. Invalid = AtlasError (code 2). The record of probes.log gets them only when used."""
    resource, commit = getattr(args, "resource", None), getattr(args, "commit", None)
    kind = rid = None
    if resource is not None:
        match = RESOURCE_ARG_RE.match(resource)
        if not match or any(is_control(c) for c in resource):
            raise AtlasError("--resource inválido — use <kind>:<id> com kind datastore, queue, topic ou bucket", 2)
        kind, rid = match.groups()
        record["resource"] = f"{kind}:{rid}"
    if commit is not None:
        commit = commit.lower()
        if not COMMIT_RE.match(commit):
            raise AtlasError("--commit inválido — use o sha do commit, de 7 a 40 caracteres hexadecimais minúsculos",
                             2)
        record["commit"] = commit
    return kind, rid, commit


def _no_access(what: str) -> AtlasError:
    """The refusal of a probe@2 capability without the local access it declares (SPEC-0096): the type, never a
    value."""
    block = {"cluster": "clusters", "database": "databases"}.get(what, what)
    return AtlasError(f"sem acesso local: {what} — declare access.{block} na configuração local desta máquina "
                      "(references/config.md)", 4)


def _probe_query(args, record: dict, probes: dict, entry: dict, extras_box: list, deployment=None) -> dict:
    """One probe through the core (the protections of SPEC-0088 and SPEC-0096), without printing: {"result",
    "message", "extras", "request_view", "aid"}; result["status"] is "ok" or "error". `deployment` picks that
    deployment of the service in the environment (verify, SPEC-0090); None = the first by id, as `probe` does, or
    the one that links --resource. Refusals and failures raise AtlasError with the exit code of `probe`."""
    for what, value in (("capacidade", args.capability), ("verbo", args.verb)):
        if not PROBE_WORD_RE.match(value):
            raise AtlasError(f"{what} inválido — use uma palavra minúscula, sem espaço (letras, dígitos, - e _)", 2)
    lines, since_seconds = _probe_limits(args, probes)
    for what, value in (("--service", args.service), ("--env", args.env)):
        if not ENVIRONMENT_NAME_RE.match(value):
            raise AtlasError(f"{what} inválido — use um nome do atlas (letras, dígitos, . _ -, sem espaço, sem "
                             "começar com -)", 2)
    kind, rid, commit = _probe_arguments(args, record)
    access = local_access(entry.get("access"))
    atlas, shared = scan_config(args.atlas)
    extras = probe_extras(shared)
    extras_box[:] = extras
    tiers = validate_environments(shared.get("environments"))
    graph = read_probe_graph(atlas)
    targets = probe_targets(atlas, args.service, args.env, graph)
    resource = None
    if kind:  # the resource from the graph, linked to the deployment of the environment (ADR-0025)
        resource, deployment = probe_resource(graph, args.service, args.env, kind, rid)
    repositories = probe_change_repositories(graph, args.service) if commit is not None else None
    target = next((t for t in targets if t["deployment"] == deployment), None) if deployment else targets[0]
    if target is None:
        raise AtlasError(f"deployment {deployment} não é de service:{args.service} em environment:{args.env}", 2)
    problem = target_problem(target, args.service)
    if problem:  # checked before any process runs, --describe included (Emenda v4)
        raise AtlasError(f"alvo inválido no atlas: {problem} — corrija o atlas (references/probes.md)", 2)
    reachable = [c for c in target["clusters"] if c in access["clusters"]
                 or target["cluster_ids"].get(c) in access["clusters"]]
    context = (access["clusters"].get(reachable[0]) or access["clusters"][target["cluster_ids"][reachable[0]]]
               if reachable else None)
    environments = (target["environment"], args.env)
    profile = next((access["cloud"][e] for e in environments if e in access["cloud"]), None)
    base_url = next((access["urls"][e] for e in environments if e in access["urls"]), None)
    database = access["databases"].get(rid) if kind == "datastore" else None
    passfile = expand_passfile(database["passfile"]) if database else None
    # no access value ever shows in what comes from the adapter; patterns and literals mask in one pass (Emenda v6)
    literals = [context, profile, base_url]
    if database:
        literals += [database["user"], database["database"], database["passfile"], passfile]
    patterns = extras
    extras = patterns + literal_masks(literals)
    extras_box[:] = extras
    aid, adapter, argv, spec = choose_adapter(probes, args.capability, patterns, literals, kind or "deployment")
    record["adapter"] = aid
    extras = patterns + literal_masks(literals + adapter_values(adapter))
    extras_box[:] = extras
    if "change" in spec["inputs"] and commit is None:
        raise AtlasError(f"{args.capability} exige --commit (o sha da mudança)", 2)
    if commit is not None and "change" not in spec["inputs"]:
        raise AtlasError(f"--commit não é aceito por {args.capability} (o adaptador {aid} não declara change)", 2)
    journeys = probe_journeys(graph, args.service) if "journeys" in spec["inputs"] else None
    allowed = [verb for verb in spec["verbs"] if verb in adapter["verbs"]]
    if args.verb not in allowed:
        raise AtlasError(f"verbo {args.verb} não permitido para {args.capability} no adaptador {aid} (permitidos: "
                         f"{', '.join(allowed) or 'nenhum'}; a interseção dos verbos do adaptador com "
                         f"probes.adapters.{aid}.verbs)", 4)
    if tiers.get(target["environment"]) != "test" and not args.confirm_production:
        raise AtlasError(f"ambiente {args.env} é de produção ou sem marcação: confirme com a pessoa e use "
                         "--confirm-production", 4)
    probe1 = spec["contract"] == PROBE_CONTRACT
    if probe1 and not target["clusters"]:
        raise AtlasError(f"sem acesso local ao cluster: o deployment {target['deployment']} não tem cluster no "
                         "atlas", 4)
    if probe1 and not reachable:
        raise AtlasError(f"sem acesso local ao cluster {', '.join(target['clusters'])} (access.clusters)", 4)
    declared = spec["access"]
    for what, missing in (("cluster", not reachable), ("cloud", profile is None),
                          ("database", database is None or passfile_problem(passfile)[0] == "não encontrado"),
                          ("urls", base_url is None)):
        if what in declared and missing:
            raise _no_access(what)
    limits = {"lines": lines, "since_seconds": since_seconds}
    cluster_fields = {"clusters": target["clusters"], "context": context, "namespace": target["namespace"],
                      "workloads": target["workloads"]}
    if probe1:
        request = {"contract": PROBE_CONTRACT, "capability": args.capability, "verb": args.verb,
                   "target": {"service": args.service, "environment": target["environment"],
                              "deployment": target["deployment"], **cluster_fields},
                   "limits": limits}
    else:  # probe@2: only the blocks the capability declares (ADR-0025)
        fields = {"service": args.service, "environment": target["environment"], "deployment": target["deployment"]}
        if resource is not None:
            fields["resource"] = resource
        if "cluster" in declared:
            fields.update(cluster_fields)
        if "cloud" in declared:
            fields["cloud"] = {"profile": profile}
        if "database" in declared:
            fields["database"] = {"user": database["user"], "name": database["database"], "passfile": passfile}
        if "urls" in declared:
            fields["urls"] = {"base_url": base_url}
        if "change" in spec["inputs"]:
            fields["change"] = {"commit": commit, "repositories": repositories}
        if journeys is not None:
            fields["journeys"] = journeys
        request = {"contract": PROBE_CONTRACT_2, "capability": args.capability, "verb": args.verb,
                   "target": fields, "limits": limits}
    contract = spec["contract"]
    problems = validate_probe_input(request)
    if problems:  # the atlas has a value the contract does not accept: never sent to the adapter
        raise AtlasError(f"alvo fora do contrato {contract} — {'; '.join(probe_mask(problems, extras))}", 2)
    data = _run_adapter(aid, argv, adapter, extras, json.dumps(request, ensure_ascii=False), contract,
                        passfile if "database" in declared else None)
    problems = validate_probe_output(data)
    if not problems:
        if data["contract"] != contract:
            problems.append("contract diferente do --describe do adaptador")
        problems += [f"{key} diferente do pedido" for key in ("capability", "verb") if data[key] != request[key]]
        if data["adapter"] != aid:
            problems.append("adapter diferente do id do adaptador que rodou")
    if problems:
        raise _contract_failure(aid, "a saída", problems, extras, contract)
    message = probe_mask(str(data.get("message") or ""), extras)[:PROBE_MESSAGE_MAX]
    request_view = {"capability": args.capability, "verb": args.verb, "service": args.service,
                    "environment": args.env, "deployment": target["deployment"]}
    outcome = {"message": message, "extras": extras, "request_view": request_view, "aid": aid}
    if data["status"] == "error":
        result = {key: data[key] for key in ("contract", "adapter", "capability", "verb", "status")}
        # the message is already masked: masking it again would put a marker inside a marker (Emenda v6)
        return dict(outcome, result=dict(probe_mask(result, extras), items=[], truncated=False, message=message))
    items = probe_mask(data["items"], extras)
    truncated = bool(data["truncated"]) or len(items) > lines
    items = items[:lines]
    if args.summary:
        if items and not any(isinstance(item.get("line"), str) for item in items):
            raise AtlasError("--summary vale só para verbos que devolvem linhas de log (itens com line)", 2)
        items = summarize_log(items)
    result = {"contract": contract, "adapter": aid,
              "capability": args.capability, "verb": args.verb, "status": "ok", "items": items,
              "truncated": truncated}
    if message:
        result["message"] = message
    return dict(outcome, result=result)


def run_probe(args, name: str, probes: dict, entry: dict, deployment=None) -> dict:
    """_probe_query with its line in probes.log (written whatever the outcome, ADR-0023): the one path of `probe`
    and `verify` to an adapter. Raises the AtlasError of a refusal or failure after logging it."""
    record = {"atlas": name, "service": args.service, "environment": args.env, "capability": args.capability,
              "verb": args.verb, "adapter": "", "confirmed_production": bool(args.confirm_production)}
    extras_box = list(PROBE_PATTERNS)  # _probe_query adds redaction.extra_patterns once the atlas is read
    code = 1
    try:
        outcome = _probe_query(args, record, probes, entry, extras_box, deployment)
        code = 0 if outcome["result"]["status"] == "ok" else 1
        return outcome
    except AtlasError as e:
        code = e.code
        raise
    finally:
        record["status"] = {0: "ok", 1: "error", 2: "invalid", 4: "refused"}.get(code, "error")
        record["exit"] = code
        record["at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        write_probe_log(record, extras_box)


def cmd_probe(args):
    """probe <capacidade> <verbo> --service <id> --env <ambiente> (SPEC-0088, ADR-0023): a read-only query through
    a declared adapter. Off by default (exit 4); invalid `probes` or argument = 2; refused (verb, production
    without --confirm-production, no local access, no adapter) = 4; adapter failure or invalid output = 1. Every
    probe that passes the on/off check leaves one line in probes.log (never the result); nothing goes to the
    atlas."""
    config, name, _ = chosen_atlas(choice=args.atlas)
    entry = config["entries"][name]
    probes = validate_probes(entry.get("probes"))
    if not probes or not probes["enabled"]:
        raise AtlasError(PROBES_OFF, 4)
    outcome = run_probe(args, name, probes, entry)
    result, message = outcome["result"], outcome["message"]
    if result["status"] == "error":
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        print(f"erro: adaptador {outcome['aid']} respondeu com erro: {message or '(sem mensagem)'}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print_probe(result, outcome["request_view"], args.summary)
    return 0


# ---------------------------------------------------------------- verify (references/verify.md, ADR-0024)

VERIFY_CONTRACT = "verify@2"  # what snapshot writes and compare prints (SPEC-0102, ADR-0026)
VERIFY_CONTRACT_1 = "verify@1"  # still accepted as --baseline (SPEC-0090)
VERIFY_CONTRACTS = (VERIFY_CONTRACT_1, VERIFY_CONTRACT)
# The one registry of checks (the extension point of SPEC-0102): each check with its level. A "deployment" check has
# "resource": null, is observed by _verify_observe and compared by _delivery_check, _runtime_check or _logs_check; a
# "resource" check has "resource": "<kind:id>", is observed by _verify_observe_resource and compared by
# _dependencies_check or _signals_check. SPEC-0103 adds functional (deployment) here.
VERIFY_CHECK_LEVELS = {"delivery": "deployment", "runtime": "deployment", "logs": "deployment",
                       "dependencies": "resource", "signals": "resource"}
VERIFY_CHECKS = tuple(VERIFY_CHECK_LEVELS)
VERIFY_DEPLOYMENT_CHECKS = tuple(c for c, level in VERIFY_CHECK_LEVELS.items() if level == "deployment")
VERIFY_RESOURCE_CHECKS = tuple(c for c, level in VERIFY_CHECK_LEVELS.items() if level == "resource")
VERIFY_STATUSES = ("ok", "failed", "not_verified")
VERDICT_EXITS = {"passou": 0, "degradou": 1, "inconclusivo": 5}
VERIFY_SNAPSHOT_KEYS_1 = ("contract", "service", "environment", "taken_at", "deployments", "not_verified")
VERIFY_SNAPSHOT_KEYS = VERIFY_SNAPSHOT_KEYS_1 + ("dependencies",)
VERIFY_DEPLOYMENT_KEYS = ("images", "ready", "desired", "restarts", "warnings", "error_signatures")
VERIFY_NOT_VERIFIED_KEYS = ("deployment", "check", "reason")
VERIFY_RESOURCE_NOT_VERIFIED_KEYS = ("deployment", "resource", "check", "reason")
VERIFY_RESULT_KEYS = ("contract", "verdict", "checks", "suggestion")
VERIFY_CHECK_KEYS_1 = ("deployment", "check", "status", "evidence", "reason")
VERIFY_CHECK_KEYS = ("deployment", "resource", "check", "status", "evidence", "reason")
VERIFY_DEPENDENCY_BASE_KEYS = ("deployment", "relations", "dlq_of")
VERIFY_QUEUE_FIELDS = ("visible", "in_flight", "oldest_age_seconds", "dlq_visible")
VERIFY_SINCE, VERIFY_WINDOW = "30m", "10m"
# the resources of verify@2 (ADR-0026 4a: bucket stays out in this version)
VERIFY_RESOURCE_RE = re.compile(r"^(datastore|queue|topic):(.+)\Z")
VERIFY_RESOURCE_CAPABILITIES = ("messaging", "database", "signals", "permissions")
VERIFY_MAX_RESOURCES, VERIFY_MAX_RESOURCES_MAX = 20, 50
VERIFY_MAX_QUEUE_AGE, VERIFY_MAX_SIGNAL_INCREASE = "10m", "0.5"
POSTGRES_ENGINES = ("postgres", "aurora-postgresql")
# aspect -> (check, capability, verb): the probes of a resource (section 6.1 of SPEC-0102)
VERIFY_ASPECTS = {"queue": ("dependencies", "messaging", "queue"),
                  "subscriptions": ("dependencies", "messaging", "subscriptions"),
                  "migrations": ("dependencies", "database", "migrations"),
                  "tables": ("dependencies", "database", "tables"),
                  "permissions": ("dependencies", "permissions", "simulate"),
                  "signals": ("signals", "signals", "metrics")}
# (relation, kind) -> the actions it requires (ADR-0026 rule 3); any other pair requires none
REQUIRED_ACTIONS = {("publishes", "topic"): ("publish",), ("publishes", "queue"): ("send",),
                    ("consumes", "queue"): ("receive", "delete"), ("depends_on", "queue"): ("send",)}
PERMISSION_ACTIONS = ("publish", "send", "receive", "delete", "read", "write")
PERMISSION_DECISIONS = ("allowed", "denied")
METRIC_KINDS = ("error", "latency", "saturation", "traffic")
METRIC_STAT_RE = re.compile(r"^(sum|count|avg|min|max|p\d{1,2}(\.\d)?)\Z")
MIGRATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
INCREASE_RE = re.compile(r"^\d+(\.\d+)?\Z")
NO_RESOURCE_BASELINE = "sem foto de antes: dependências e sinais não se comparam"
OLD_BASELINE = "foto sem dependências"
OUT_OF_PHOTO = "recurso fora da foto"
NOTHING_COMPARABLE = "nenhuma métrica de erro ou latência comparável"
VERIFY_VERBS = ("status", "events", "logs")
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\Z")
# the expected image: the normalized path (no registry host, SPEC-0082) with ":<tag>" and/or "@<digest>"
EXPECT_IMAGE_RE = re.compile(r"^(?P<path>[a-z0-9][a-z0-9._/-]*[a-z0-9]|[a-z0-9])"
                             r"(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9._-]{0,127}))?"
                             r"(?:@(?P<digest>[A-Za-z0-9_+.-]+:[A-Fa-f0-9]{16,}))?\Z")
LIMIT_RE = re.compile(r"^\d{1,6}\Z")
NO_BASELINE = "sem foto de antes: erros novos e antigos não se separam"
NO_POD = "nenhum pod respondeu (probe de logs cortada e sem linha)"
# a probe that came back with truncated: true (Emenda v5): its checks are not verified, never ok
CUT_PROBE = "probe de {verb} cortada: um pod ou uma linha da janela pode ter ficado de fora"
# the suggestion of `degradou` never carries a command (Emenda v3): checked before it is printed
SUGGESTION_COMMAND_RE = re.compile(r"\bkubectl\b|\bargocd\b|\bhelm\b|\bgit (?:revert|push|reset|checkout)\b|^\s*\$ ",
                                   re.MULTILINE)


def _verify_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _verify_text(value) -> bool:
    return isinstance(value, str) and bool(value)


def _verify_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _resource_key_problem(value) -> bool:
    """True when `value` is not a "<kind>:<id>" of verify@2 (kind datastore, queue or topic; id by the name rule)."""
    match = VERIFY_RESOURCE_RE.match(value) if isinstance(value, str) else None
    return not match or not ENVIRONMENT_NAME_RE.match(match.group(2))


def _sorted_texts(value) -> bool:
    return isinstance(value, list) and all(_verify_text(v) for v in value) and value == sorted(value)


def _dependency_problems(key, entry) -> list:
    """Problems of one entry of `dependencies` of a verify@2 photo (section 6.4 of SPEC-0102)."""
    where = f"dependencies.{_show(key)}"
    if _resource_key_problem(key):
        return [f"{where}: a chave precisa ser <kind>:<id> com kind datastore, queue ou topic"]
    if not isinstance(entry, dict):
        return [f"{where} precisa ser um objeto"]
    problems = _closed_keys(entry, VERIFY_DEPENDENCY_BASE_KEYS + tuple(VERIFY_ASPECTS), VERIFY_DEPENDENCY_BASE_KEYS,
                            where)
    if "deployment" in entry and not _verify_text(entry["deployment"]):
        problems.append(f"{where}.deployment precisa ser um texto não vazio")
    if "relations" in entry and not (isinstance(entry["relations"], list)
                                     and all(_verify_text(r) for r in entry["relations"])):
        problems.append(f"{where}.relations precisa ser uma lista de textos")
    if entry.get("dlq_of") is not None and _resource_key_problem(entry["dlq_of"]):
        problems.append(f"{where}.dlq_of precisa ser <kind>:<id> ou null")
    queue = entry.get("queue")
    if "queue" in entry and not (isinstance(queue, dict) and set(queue) == set(VERIFY_QUEUE_FIELDS)
                                 and _verify_int(queue["visible"]) and _verify_int(queue["in_flight"])
                                 and all(queue[k] is None or _verify_int(queue[k])
                                         for k in ("oldest_age_seconds", "dlq_visible"))):
        problems.append(f"{where}.queue precisa ter {', '.join(VERIFY_QUEUE_FIELDS)} (inteiros >= 0; os dois últimos "
                        "podem ser null)")
    subs = entry.get("subscriptions")
    if "subscriptions" in entry and not (isinstance(subs, list) and all(
            isinstance(s, dict) and set(s) == {"destination", "filter_fingerprint"} and _verify_text(s["destination"])
            and (s["filter_fingerprint"] is None or _verify_text(s["filter_fingerprint"])) for s in subs)):
        problems.append(f"{where}.subscriptions precisa ser uma lista de {{destination, filter_fingerprint}}")
    for aspect in ("migrations", "tables"):
        if aspect in entry and not _sorted_texts(entry[aspect]):
            problems.append(f"{where}.{aspect} precisa ser uma lista ordenada de textos")
    signals = entry.get("signals")
    if "signals" in entry:
        if not (isinstance(signals, dict) and set(signals) == {"window_seconds", "metrics"}
                and _verify_int(signals["window_seconds"]) and isinstance(signals["metrics"], dict)):
            problems.append(f"{where}.signals precisa ser {{window_seconds, metrics}}")
        else:
            for name, value in signals["metrics"].items():
                metric, sep, stat = str(name).rpartition("|")
                if not (sep and metric and METRIC_STAT_RE.match(stat) and isinstance(value, dict)
                        and set(value) == {"kind", "value"} and value["kind"] in METRIC_KINDS
                        and (value["value"] is None or _verify_number(value["value"]))):
                    problems.append(f"{where}.signals.metrics.{_show(name)} precisa ser <name>|<stat>: {{kind, value}}")
    permissions = entry.get("permissions")
    if "permissions" in entry and not (isinstance(permissions, dict) and all(
            a in PERMISSION_ACTIONS and d in PERMISSION_DECISIONS for a, d in permissions.items())):
        problems.append(f"{where}.permissions precisa ser um mapa <ação>: allowed | denied")
    return problems


def validate_verify_snapshot(data) -> list:
    """Problems of a snapshot file, verify@1 (SPEC-0090) or verify@2 (SPEC-0102, with `dependencies`); [] = valid.
    Closed keys at every level; any other contract is refused."""
    if not isinstance(data, dict):
        return ["a foto precisa ser um objeto JSON"]
    v1 = data.get("contract") == VERIFY_CONTRACT_1
    keys = VERIFY_SNAPSHOT_KEYS_1 if v1 else VERIFY_SNAPSHOT_KEYS
    problems = _closed_keys(data, keys, keys)
    if data.get("contract") not in VERIFY_CONTRACTS:
        problems.append(f"contract precisa ser {' ou '.join(VERIFY_CONTRACTS)}")
    for key in ("service", "environment"):
        if key in data and not _verify_text(data[key]):
            problems.append(f"{key} precisa ser um texto não vazio")
    if "taken_at" in data and not (isinstance(data["taken_at"], str) and ISO_UTC_RE.match(data["taken_at"])):
        problems.append("taken_at precisa ser uma data ISO em UTC (2026-11-23T10:00:00Z)")
    deployments = data.get("deployments")
    if "deployments" in data and not isinstance(deployments, dict):
        problems.append("deployments precisa ser um mapa <deployment>: {...}")
    for name, entry in (deployments.items() if isinstance(deployments, dict) else ()):
        where = f"deployments.{_show(name)}"
        if not isinstance(entry, dict):
            problems.append(f"{where} precisa ser um objeto")
            continue
        problems += _closed_keys(entry, VERIFY_DEPLOYMENT_KEYS, VERIFY_DEPLOYMENT_KEYS, where)
        if "images" in entry and not (isinstance(entry["images"], list)
                                      and all(_verify_text(i) for i in entry["images"])):
            problems.append(f"{where}.images precisa ser uma lista de textos")
        for key in ("ready", "desired"):
            if key in entry and not _verify_int(entry[key]):
                problems.append(f"{where}.{key} precisa ser um inteiro >= 0")
        for key in ("restarts", "error_signatures"):
            value = entry.get(key)
            if key in entry and not (isinstance(value, dict)
                                     and all(_verify_text(k) and _verify_int(v) for k, v in value.items())):
                problems.append(f"{where}.{key} precisa ser um mapa <texto>: <inteiro >= 0>")
        if "warnings" in entry and not (isinstance(entry["warnings"], list)
                                        and all(_verify_text(w) and "|" in w for w in entry["warnings"])):
            problems.append(f"{where}.warnings precisa ser uma lista de \"<motivo>|<objeto>\"")
    dependencies = data.get("dependencies")
    if "dependencies" in data and not v1:
        if not isinstance(dependencies, dict):
            problems.append("dependencies precisa ser um mapa <kind:id>: {...}")
        else:
            for key, entry in dependencies.items():
                problems += _dependency_problems(key, entry)
    not_verified = data.get("not_verified")
    if "not_verified" in data and not isinstance(not_verified, list):
        problems.append("not_verified precisa ser uma lista")
    for position, item in enumerate(not_verified if isinstance(not_verified, list) else [], 1):
        where = f"not_verified[{position}]"
        if not isinstance(item, dict):
            problems.append(f"{where} precisa ser um objeto")
            continue
        resource = "resource" in item and not v1
        keys = VERIFY_RESOURCE_NOT_VERIFIED_KEYS if resource else VERIFY_NOT_VERIFIED_KEYS
        checks = VERIFY_RESOURCE_CHECKS if resource else VERIFY_DEPLOYMENT_CHECKS
        problems += _closed_keys(item, keys, keys, where)
        if "deployment" in item and not _verify_text(item["deployment"]):
            problems.append(f"{where}.deployment precisa ser um texto não vazio")
        if resource and _resource_key_problem(item["resource"]):
            problems.append(f"{where}.resource precisa ser <kind>:<id> com kind datastore, queue ou topic")
        if "check" in item and item["check"] not in checks:
            problems.append(f"{where}.check precisa ser um de: {', '.join(checks)}")
        if "reason" in item and not _verify_text(item["reason"]):
            problems.append(f"{where}.reason precisa ser um texto não vazio")
    return problems


def verdict_of(statuses) -> str:
    """degradou when one check failed; else inconclusivo when one was not verified; else passou."""
    statuses = set(statuses)
    return "degradou" if "failed" in statuses else "inconclusivo" if "not_verified" in statuses else "passou"


def validate_verify_result(data) -> list:
    """Problems of the output of `verify compare --json`, verify@1 (SPEC-0090: checks without resource) or verify@2
    (SPEC-0102: resource in every check, null in the deployment checks and <kind:id> in the resource checks); [] =
    valid: closed keys, the verdict by the rule, reason in every not_verified, a suggestion only in degradou and
    never with a command."""
    if not isinstance(data, dict):
        return ["a saída precisa ser um objeto JSON"]
    problems = _closed_keys(data, VERIFY_RESULT_KEYS, VERIFY_RESULT_KEYS)
    if data.get("contract") not in VERIFY_CONTRACTS:
        problems.append(f"contract precisa ser {' ou '.join(VERIFY_CONTRACTS)}")
    v1 = data.get("contract") == VERIFY_CONTRACT_1
    keys = VERIFY_CHECK_KEYS_1 if v1 else VERIFY_CHECK_KEYS
    allowed_checks = VERIFY_DEPLOYMENT_CHECKS if v1 else VERIFY_CHECKS
    if "verdict" in data and data["verdict"] not in VERDICT_EXITS:
        problems.append(f"verdict precisa ser um de: {', '.join(VERDICT_EXITS)}")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        return problems + ["checks precisa ser uma lista não vazia"]
    for position, item in enumerate(checks, 1):
        where = f"checks[{position}]"
        if not isinstance(item, dict):
            problems.append(f"{where} precisa ser um objeto")
            continue
        problems += _closed_keys(item, keys, tuple(k for k in keys if k != "reason"), where)
        if "deployment" in item and not _verify_text(item["deployment"]):
            problems.append(f"{where}.deployment precisa ser um texto não vazio")
        if "check" in item and item["check"] not in allowed_checks:
            problems.append(f"{where}.check precisa ser um de: {', '.join(allowed_checks)}")
        if not v1 and "resource" in item and item.get("check") in VERIFY_CHECK_LEVELS:
            if VERIFY_CHECK_LEVELS[item["check"]] == "deployment" and item["resource"] is not None:
                problems.append(f"{where}.resource precisa ser null em {item['check']}")
            if VERIFY_CHECK_LEVELS[item["check"]] == "resource" and _resource_key_problem(item["resource"]):
                problems.append(f"{where}.resource precisa ser <kind>:<id> com kind datastore, queue ou topic")
        if "status" in item and item["status"] not in VERIFY_STATUSES:
            problems.append(f"{where}.status precisa ser um de: {', '.join(VERIFY_STATUSES)}")
        if "evidence" in item and not isinstance(item["evidence"], dict):
            problems.append(f"{where}.evidence precisa ser um objeto")
        if "reason" in item and not isinstance(item["reason"], str):
            problems.append(f"{where}.reason precisa ser um texto")
        if item.get("status") == "not_verified" and not _verify_text(item.get("reason")):
            problems.append(f"{where}: not_verified precisa de reason")
    statuses = [item.get("status") for item in checks if isinstance(item, dict)]
    if data.get("verdict") in VERDICT_EXITS and data["verdict"] != verdict_of(statuses):
        problems.append(f"verdict fora da regra (failed > not_verified > ok: {verdict_of(statuses)})")
    suggestion = data.get("suggestion")
    if "suggestion" in data and not isinstance(suggestion, str):
        problems.append("suggestion precisa ser um texto")
    elif data.get("verdict") == "degradou" and not (suggestion or "").strip():
        problems.append("degradou precisa de suggestion")
    elif data.get("verdict") != "degradou" and suggestion:
        problems.append("suggestion só em degradou")
    elif suggestion and SUGGESTION_COMMAND_RE.search(suggestion):
        problems.append("suggestion não pode trazer comando")
    return problems


def parse_image_ref(value) -> tuple:
    """(path, tag, digest) of an image reference as the adapters give it ("<path>[:<tag>][@<digest>]")."""
    path, _, digest = str(value).partition("@")
    tag = ""
    if path.rfind(":") > path.rfind("/"):
        path, tag = path.rsplit(":", 1)
    return path, tag, digest


EXPECT_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def normalize_expected_image(value) -> str:
    """--expect-image normalized like the adapter's normalize_image (Emenda v5 of SPEC-0090): the scheme and the
    registry host (first segment with "." or ":" or "localhost") taken out, the path and the digest in lower case.
    The text is returned as is when it does not split (EXPECT_IMAGE_RE then refuses it)."""
    text = str(value or "").strip()
    match = EXPECT_SCHEME_RE.match(text)
    text = text[match.end():] if match else text
    text, at, digest = text.partition("@")
    head, sep, last = text.rpartition("/")
    last, colon, tag = last.partition(":")
    segments = (head.split("/") if sep else []) + [last]
    first = segments[0].lower()
    if len(segments) > 1 and ("." in first or ":" in first or first == "localhost"):
        segments = segments[1:]
    return "/".join(segments).lower() + (f":{tag}" if colon else "") + (f"@{digest.lower()}" if at else "")


def image_matches(image, expected: tuple) -> bool:
    """True when a pod image is the expected one: the same path and the digest, when given; else the tag."""
    path, tag, digest = parse_image_ref(image)
    want_path, want_tag, want_digest = expected
    if path != want_path:
        return False
    return digest == want_digest if want_digest else tag == want_tag


def _verify_duration(value, option) -> int:
    seconds = parse_duration(value)
    if seconds is None or seconds > PROBE_SINCE_MAX:
        raise AtlasError(f"{option} inválido — use uma duração como 10m ou 2h, até 24h", 2)
    return seconds


def _verify_limit(value, option) -> int:
    if not isinstance(value, str) or not LIMIT_RE.match(value.strip()):
        raise AtlasError(f"{option} precisa ser um número inteiro >= 0", 2)
    return int(value)


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def _same_folder(path: Path, identity: tuple) -> bool:
    """True when `path` is the folder of `identity` (st_dev, st_ino): the file, not the text of the path."""
    try:
        info = os.stat(path)
    except OSError:
        return False
    return (info.st_dev, info.st_ino) == identity


def _verify_out(value, atlas: Path) -> Path:
    """The --out of the snapshot, resolved (.., symlinks): never inside the atlas folder (ADR-0024), exit 2. The
    parent folder and every folder above it are compared with the atlas folder by identity (st_dev, st_ino, Emenda
    v5 of SPEC-0090), so neither another case (macOS) nor a link into the atlas gets through."""
    out = Path(os.path.expanduser(str(value))).resolve()
    folder = Path(atlas).expanduser().resolve()
    inside = _inside(out, folder)
    if not inside:
        try:
            info = os.stat(folder)
        except OSError:
            info = None
        if info is not None:
            identity = (info.st_dev, info.st_ino)
            inside = any(_same_folder(p, identity) for p in (out.parent, *out.parent.parents))
    if inside:
        raise AtlasError("--out dentro da pasta do atlas: a foto é um arquivo da tarefa, fora do atlas "
                         "(references/verify.md)", 2)
    if out.is_dir():
        raise AtlasError("--out é uma pasta: indique o arquivo da foto", 2)
    if not out.parent.is_dir():
        raise AtlasError("--out numa pasta que não existe: crie a pasta da tarefa antes", 2)
    return out


def _verify_baseline(value, service: str, environment: str) -> dict:
    """The --baseline file, read and validated (verify@1 or verify@2) for this service and environment; else exit
    2."""
    path = Path(os.path.expanduser(str(value)))
    if not path.is_file():
        raise AtlasError("--baseline não encontrado: indique a foto gravada pelo verify snapshot", 2)
    try:
        data = json.loads(read_text(path), parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise AtlasError(f"--baseline não é JSON válido (contrato {' ou '.join(VERIFY_CONTRACTS)})", 2) from None
    problems = validate_verify_snapshot(data)
    if problems:
        raise AtlasError(f"--baseline fora do contrato {' ou '.join(VERIFY_CONTRACTS)} — {'; '.join(problems[:10])}",
                         2)
    if (data["service"], data["environment"]) != (service, environment):
        raise AtlasError("--baseline é a foto de outro serviço ou ambiente", 2)
    return data


def _verify_setup(args) -> dict:
    """What both phases need before any probe: the chosen atlas (exit 3 without configuration), the probes on (exit
    4), --env/--service by the name rule, the deployments of the service in the environment (exit 2), and production
    only with --confirm-production (exit 4: no query runs)."""
    config, name, _ = chosen_atlas(choice=args.atlas)
    entry = config["entries"][name]
    probes = validate_probes(entry.get("probes"))
    if not probes or not probes["enabled"]:
        raise AtlasError(PROBES_OFF, 4)
    for what, value in (("--service", args.service), ("--env", args.env)):
        if not ENVIRONMENT_NAME_RE.match(value):
            raise AtlasError(f"{what} inválido — use um nome do atlas (letras, dígitos, . _ -, sem espaço, sem "
                             "começar com -)", 2)
    atlas, shared = scan_config(args.atlas)
    return {"name": name, "entry": entry, "probes": probes, "atlas": atlas, "shared": shared}


def _verify_targets(setup, args, graph) -> list:
    """The deployments of the service in the environment, each by the rules of the target (exit 2)."""
    targets = probe_targets(setup["atlas"], args.service, args.env, graph)
    for target in targets:
        problem = target_problem(target, args.service)
        if problem:
            raise AtlasError(f"alvo inválido no atlas: {problem} — corrija o atlas (references/probes.md)", 2)
    return targets


def _verify_production(setup, args, targets) -> None:
    """Production (or no tier) only with --confirm-production (exit 4), for every target before any probe."""
    tiers = validate_environments(setup["shared"].get("environments"))
    for target in targets:
        if tiers.get(target["environment"]) != "test" and not args.confirm_production:
            raise AtlasError(f"ambiente {args.env} é de produção ou sem marcação: confirme com a pessoa e use "
                             "--confirm-production", 4)


def _verify_observe(setup, args, target, window: str) -> dict:
    """The 3 probes of one deployment (status, events, logs --summary), each by run_probe (the path, protections,
    mask and log of `probe`): {verb: {"result"} | {"reason"}}. A refusal, failure or answer with error becomes the
    reason (the check is not verified), never a pass."""
    seen = {}
    for verb in VERIFY_VERBS:
        query = argparse.Namespace(capability="runtime", verb=verb, service=args.service, env=args.env,
                                   since=window, lines=PROBE_LINES_MAX, summary=verb == "logs",
                                   confirm_production=args.confirm_production, atlas=args.atlas, json=True)
        try:
            outcome = run_probe(query, setup["name"], setup["probes"], setup["entry"], target["deployment"])
        except AtlasError as e:
            seen[verb] = {"reason": f"probe {verb}: {e}"}
            continue
        result = outcome["result"]
        if result["status"] != "ok":
            seen[verb] = {"reason": f"probe {verb} respondeu com erro: {outcome['message'] or '(sem mensagem)'}"}
        elif result["truncated"]:  # a cut probe never gives ok (Emenda v5): a pod or an old line may be missing
            seen[verb] = {"reason": NO_POD if verb == "logs" and not result["items"] else CUT_PROBE.format(verb=verb)}
        else:
            seen[verb] = {"result": result}
    return seen


def _owner_names(target, pods) -> tuple:
    """({pod: workload name}, workload names) of a deployment: the owner of each object of a warning."""
    owner = {}
    names = {w.split("/", 1)[1] for w in target["workloads"] if "/" in w}
    for pod in pods:
        workload = pod.get("workload")
        if isinstance(workload, str) and "/" in workload:
            names.add(workload.split("/", 1)[1])
            if isinstance(pod.get("pod"), str):
                owner[pod["pod"]] = workload.split("/", 1)[1]
    return owner, names


def warning_key(event: dict, owner: dict, names) -> str:
    """"<reason>|<Kind>/<name>" with a pod (or ReplicaSet) name replaced by the workload that owns it (Emenda v3):
    the same reason on another pod of the workload is the same warning."""
    reason = str(event.get("reason") or "")
    kind, _, name = str(event.get("object") or "").partition("/")
    if name in owner:
        name = owner[name]
    else:
        name = max((n for n in names if name == n or name.startswith(n + "-")), key=len, default=name)
    return f"{reason}|{kind}/{name}"


def _status_parts(seen) -> tuple:
    """(workloads, pods) of the status probe; ([], []) when it did not answer."""
    items = seen["status"]["result"]["items"] if "result" in seen["status"] else []
    workloads = [i for i in items if isinstance(i, dict) and i.get("kind") == "workload"]
    pods = [i for i in items if isinstance(i, dict) and i.get("kind") == "pod"]
    return workloads, pods


def _observed(target, seen) -> dict:
    """The state of one deployment as the snapshot keeps it (no log line, only signatures and counts)."""
    workloads, pods = _status_parts(seen)
    owner, names = _owner_names(target, pods)
    images = sorted({str(i) for pod in pods for i in (pod.get("images") or []) if isinstance(i, str) and i})
    restarts = {}
    for pod in pods:
        if isinstance(pod.get("pod"), str) and pod["pod"]:
            restarts[pod["pod"]] = pod["restarts"] if _verify_int(pod.get("restarts")) else 0
    events = seen["events"]["result"]["items"] if "result" in seen["events"] else []
    warnings = sorted({warning_key(e, owner, names) for e in events if isinstance(e, dict) and e.get("reason")})
    signatures = {}
    for group in (seen["logs"]["result"]["items"] if "result" in seen["logs"] else []):
        if isinstance(group, dict) and group.get("level") == "error" and isinstance(group.get("signature"), str):
            signatures[group["signature"]] = signatures.get(group["signature"], 0) + int(group.get("count") or 0)
    return {"images": images,
            "ready": sum(w["ready"] for w in workloads if w.get("found") is not False and _verify_int(w.get("ready"))),
            "desired": sum(w["desired"] for w in workloads
                           if w.get("found") is not False and _verify_int(w.get("desired"))),
            "restarts": restarts, "warnings": warnings, "error_signatures": signatures}


def _logs_problem(seen):
    """Why the logs of one observation cannot be used (refused, failed or cut), or None."""
    return seen["logs"].get("reason")


# ---- verify@2: the resources of the service (SPEC-0102, ADR-0026)


def _verify_resource_options(args) -> tuple:
    """(requested, max_resources) of --resource and --max-resources, checked before anything is read (exit 2):
    each --resource as <kind>:<id> with kind queue, topic or datastore and the id by the name rule, a repeated one
    counted once; --max-resources an integer from 1 to 50; more --resource than --max-resources is refused."""
    text = str(getattr(args, "max_resources", None) or VERIFY_MAX_RESOURCES).strip()
    if not re.match(r"^\d{1,3}\Z", text) or not 1 <= int(text) <= VERIFY_MAX_RESOURCES_MAX:
        raise AtlasError(f"--max-resources inválido — use um inteiro de 1 a {VERIFY_MAX_RESOURCES_MAX}", 2)
    requested = []
    for value in getattr(args, "resource", None) or []:
        if _resource_key_problem(value) or any(is_control(c) for c in value):
            raise AtlasError("--resource inválido — use <kind>:<id> com kind queue, topic ou datastore", 2)
        if value not in requested:
            requested.append(value)
    if len(requested) > int(text):
        raise AtlasError("mais recursos em --resource que --max-resources", 2)
    return requested, int(text)


def _resource_adapter_declared(setup) -> bool:
    """True when an adapter of probes.adapters declares, in a probe@2 --describe, one of the resource capabilities
    (messaging, database, signals, permissions). Only --describe runs (never a query); an adapter whose description
    fails or is out of the contract counts as not declaring."""
    patterns = probe_extras(setup["shared"])
    for aid, adapter in setup["probes"]["adapters"].items():
        argv = adapter_command(aid, adapter)
        if argv is None:
            continue
        try:
            described = _run_adapter(aid, argv + ["--describe"], adapter,
                                     patterns + literal_masks(adapter_values(adapter)))
        except AtlasError:
            continue
        if validate_probe_describe(described) or described["contract"] != PROBE_CONTRACT_2:
            continue
        if any(cap in described["capabilities"] for cap in VERIFY_RESOURCE_CAPABILITIES):
            return True
    return False


def _scope_entry(graph, links, key) -> dict:
    """One resource of the scope: the deployment that links it (the first by id), the relations of that link (a
    config_refs counts as depends_on), dlq_of (the queue whose `dlq` names it, when it is linked only so) and the
    aspects of its kind (section 6.1 of SPEC-0102)."""
    kind, rid = key.split(":", 1)
    nodes = {n.get("key"): n for n in graph["nodes"] if isinstance(n, dict)}
    mine = [link for link in links if link["resource"] == key]
    real = [link for link in mine if link["relation"] != "dlq"]
    deployment = (real or mine)[0]["deployment"]
    relations = sorted({"depends_on" if link["relation"] == "config_ref" else link["relation"]
                        for link in real if link["deployment"] == deployment})
    dlq_of = None
    if not real:
        mains = sorted({link["resource"] for link in links if link["deployment"] == deployment
                        and link["relation"] != "dlq" and link["resource"].startswith("queue:")
                        and ((nodes.get(link["resource"]) or {}).get("attrs") or {}).get("dlq") == rid})
        dlq_of = mains[0] if mains else None
    required = list(dict.fromkeys(a for relation in relations for a in REQUIRED_ACTIONS.get((relation, kind), ())))
    engine = ((nodes.get(key) or {}).get("attrs") or {}).get("engine")
    if kind == "queue":
        aspects = ["queue"] + (["permissions"] if required and not dlq_of else [])
    elif kind == "topic":
        aspects = ["subscriptions"] + (["permissions"] if required else [])
    else:
        aspects = ["migrations", "tables"] if engine in POSTGRES_ENGINES else []
    checks = (("dependencies",) if aspects else ()) + ("signals",)
    return {"resource": key, "kind": kind, "id": rid, "deployment": deployment, "relations": relations,
            "dlq_of": dlq_of, "required": required, "aspects": aspects + ["signals"], "checks": checks}


def _verify_scope(setup, args, graph, requested) -> list:
    """The resources of verify@2, in kind:id order (section 6.1 of SPEC-0102): the --resource list (each linked to
    the deployment of the service in the environment, SPEC-0096, else exit 2), or every queue, topic and datastore
    of linked_resources but a queue linked only as the dlq of another one. Without --resource and without any
    adapter that declares a resource capability (probe@2), the scope is empty: verify stays as verify@1."""
    links = linked_resources(graph, args.service, args.env)
    if requested:
        for key in requested:
            kind, rid = key.split(":", 1)
            probe_resource(graph, args.service, args.env, kind, rid)
        keys = requested
    else:
        keys = sorted({link["resource"] for link in links if link["relation"] != "dlq"
                       and link["resource"].split(":", 1)[0] in ("datastore", "queue", "topic")})
        if keys and not _resource_adapter_declared(setup):
            return []
    return [_scope_entry(graph, links, key) for key in sorted(keys)]


def _parse_expect_migrations(values) -> list:
    """[(datastore id or None, migration)] of --expect-migration [<datastore>=]<migration>; out of the form = 2."""
    parsed = []
    for value in values or []:
        datastore, sep, migration = str(value).rpartition("=")
        if (sep and not ENVIRONMENT_NAME_RE.match(datastore)) or not MIGRATION_RE.match(migration):
            raise AtlasError("--expect-migration inválido — use [<datastore>=]<migration> (a migration com letras, "
                             "dígitos, . _ -, até 128 caracteres)", 2)
        parsed.append((datastore if sep else None, migration))
    return parsed


def _expected_migrations(parsed, scope) -> dict:
    """{"datastore:<id>": [migrations]}: the short form goes to the one datastore of the scope (zero or more than one
    = exit 2); a datastore out of the scope = exit 2."""
    keys = {entry["resource"] for entry in scope}
    datastores = sorted(k for k in keys if k.startswith("datastore:"))
    expected = {}
    for datastore, migration in parsed:
        if datastore is None:
            if len(datastores) != 1:
                raise AtlasError(f"--expect-migration {migration} ambígua: use <datastore>=<migration>", 2)
            key = datastores[0]
        else:
            key = f"datastore:{datastore}"
            if key not in keys:
                raise AtlasError(f"recurso {key} fora do escopo do verify", 2)
        expected.setdefault(key, [])
        if migration not in expected[key]:
            expected[key].append(migration)
    return expected


def _verify_increase(value) -> float:
    text = str(value if value is not None else VERIFY_MAX_SIGNAL_INCREASE).strip()
    if not INCREASE_RE.match(text) or float(text) > 100:
        raise AtlasError("--max-signal-increase inválido — use um decimal de 0 a 100 (0.5 = 50%)", 2)
    return float(text)


def _item_rules(aspect) -> tuple:
    """(field, test) of the items of an aspect: the table of rule 4a of ADR-0026 (section 6.2 of SPEC-0102)."""
    count_or_none = (lambda v: v is None or _verify_int(v))
    return {"queue": (("visible", _verify_int), ("in_flight", _verify_int), ("oldest_age_seconds", count_or_none),
                      ("dlq_visible", count_or_none)),
            "subscriptions": (("destination", _verify_text),
                              ("filter_fingerprint", lambda v: v is None or _verify_text(v))),
            "migrations": (("id", _verify_text), ("success", lambda v: v is None or isinstance(v, bool))),
            "tables": (("name", _verify_text),),
            "signals": (("name", _verify_text), ("stat", lambda v: isinstance(v, str) and bool(METRIC_STAT_RE.match(v))),
                        ("value", lambda v: v is None or _verify_number(v)), ("kind", lambda v: v in METRIC_KINDS)),
            "permissions": (("action", lambda v: v in PERMISSION_ACTIONS), ("api_action", lambda v: isinstance(v, str)),
                            ("decision", lambda v: v in PERMISSION_DECISIONS))}[aspect]


def _aspect_now(aspect, items, window_seconds) -> tuple:
    """(state, problem) of the items of one probe: only the fields of rule 4a of ADR-0026 (extra fields dropped); an
    item out of the contract gives the problem (the aspect is then not verified)."""
    _, capability, verb = VERIFY_ASPECTS[aspect]
    if aspect == "queue" and len(items) != 1:
        return None, f"resposta de messaging queue com {len(items)} item(ns), esperado 1"
    for item in items:
        for field, test in _item_rules(aspect):
            if not isinstance(item, dict) or field not in item or not test(item[field]):
                return None, f"item fora do contrato de {capability} {verb}: {field}"
    if aspect == "queue":
        return {k: items[0][k] for k in VERIFY_QUEUE_FIELDS}, None
    if aspect == "subscriptions":
        subs = [{"destination": i["destination"], "filter_fingerprint": i["filter_fingerprint"]} for i in items]
        return sorted(subs, key=lambda s: (s["destination"], s["filter_fingerprint"] or "")), None
    if aspect == "migrations":
        return {"applied": sorted({i["id"] for i in items if i["success"] is not False}),
                "not_applied": sorted({i["id"] for i in items if i["success"] is False})}, None
    if aspect == "tables":
        return sorted({i["name"] for i in items}), None
    if aspect == "signals":
        metrics = {}
        for item in items:
            name = f"{item['name']}|{item['stat']}"
            if name in metrics:
                return None, f"métrica repetida: {name}"
            metrics[name] = {"kind": item["kind"], "value": item["value"]}
        return {"window_seconds": window_seconds, "metrics": metrics}, None
    decisions, api_actions = {}, {}
    for item in items:  # the same action with different decisions counts as denied (conservative reading)
        action = item["action"]
        decisions[action] = "denied" if "denied" in (decisions.get(action), item["decision"]) else "allowed"
        api_actions.setdefault(action, item["api_action"])
    return {"decisions": decisions, "api_actions": api_actions}, None


def _photo_value(aspect, now):
    """What the photo keeps of an aspect (section 6.4 of SPEC-0102)."""
    if aspect == "migrations":
        return now["applied"]
    if aspect == "permissions":
        return now["decisions"]
    return now


def _verify_observe_resource(setup, args, entry, window: str) -> dict:
    """The probes of one resource, one per aspect of its kind, each by run_probe (the path, protections, mask and log
    of `probe`, with "resource" in probes.log): {aspect: {"now", "truncated"} | {"reason"}}. A refusal, failure,
    answer with error or item out of the contract becomes the reason (never a pass)."""
    seen = {}
    window_seconds = parse_duration(window)
    for aspect in entry["aspects"]:
        _, capability, verb = VERIFY_ASPECTS[aspect]
        query = argparse.Namespace(capability=capability, verb=verb, service=args.service, env=args.env,
                                   since=window, lines=PROBE_LINES_MAX, summary=False,
                                   confirm_production=args.confirm_production, atlas=args.atlas, json=True,
                                   resource=entry["resource"], commit=None)
        try:
            outcome = run_probe(query, setup["name"], setup["probes"], setup["entry"], entry["deployment"])
        except AtlasError as e:
            seen[aspect] = {"reason": f"probe {'recusada' if e.code == 4 else 'falhou'} — {e}"}
            continue
        result = outcome["result"]
        if result["status"] != "ok":
            seen[aspect] = {"reason": f"probe de {verb} respondeu com erro: {outcome['message'] or '(sem mensagem)'}"}
            continue
        now, problem = _aspect_now(aspect, result["items"], window_seconds)
        seen[aspect] = {"reason": problem} if problem else {"now": now, "truncated": bool(result["truncated"])}
    return seen


def _cut_reason(aspect) -> str:
    return f"probe de {VERIFY_ASPECTS[aspect][2]} cortada"


def _queue_aspect(now, base, dlq_of, limits) -> tuple:
    """(status, evidence, reason) of the queue aspect against the photo: the DLQ growth (or, for a queue in the role
    dlq_of, its own growth) above --max-new-dlq, or the age that crossed --max-queue-age after the deploy."""
    max_new, max_age = limits["max_new_dlq"], limits["max_queue_age"]
    above = base["oldest_age_seconds"] is not None and base["oldest_age_seconds"] > max_age
    evidence = {"now": now, "baseline": base, "new_dlq": None, "max_new_dlq": max_new,
                "max_queue_age_seconds": max_age, "age_above_limit_in_baseline": above}
    if dlq_of:
        evidence["new_dlq"] = now["visible"] - base["visible"]
        if evidence["new_dlq"] > max_new:
            return "failed", evidence, f"a DLQ ganhou {evidence['new_dlq']} mensagem(ns), acima de {max_new}"
        return "ok", evidence, ""
    reasons, unverified = [], ""
    if now["dlq_visible"] is None:
        if base["dlq_visible"] is not None:
            unverified = "DLQ sem leitura agora"
    else:
        evidence["new_dlq"] = now["dlq_visible"] - (base["dlq_visible"] or 0)
        if evidence["new_dlq"] > max_new:
            reasons.append(f"a DLQ ganhou {evidence['new_dlq']} mensagem(ns), acima de {max_new}")
    age = now["oldest_age_seconds"]
    if age is not None and age > max_age and not above:
        reasons.append(f"mensagem mais antiga com {age}s, acima de {max_age}s depois do deploy")
    if reasons:
        return "failed", evidence, "; ".join(reasons)
    return ("not_verified", evidence, unverified) if unverified else ("ok", evidence, "")


def _subscriptions_aspect(now, base) -> tuple:
    def grouped(subs):
        found = {}
        for sub in subs:
            found.setdefault(sub["destination"], set()).add(sub["filter_fingerprint"] or "")
        return found
    before, after = grouped(base), grouped(now)
    missing = sorted(d for d in before if d not in after)
    changed = sorted(d for d in before if d in after and before[d] != after[d])
    evidence = {"missing": missing, "changed": changed, "new": sorted(d for d in after if d not in before)}
    reasons = ([f"{len(missing)} assinatura(s) sumiu(ram)"] if missing else []) + (
        [f"{len(changed)} assinatura(s) mudou(aram) de filtro"] if changed else [])
    return ("failed", evidence, "; ".join(reasons)) if reasons else ("ok", evidence, "")


def _migrations_aspect(now, base, expected, truncated) -> tuple:
    applied = set(now["applied"])
    missing = [m for m in expected if m not in applied]
    evidence = {"expected": expected, "missing": missing, "not_applied": now["not_applied"],
                "new_since_baseline": len(applied - set(base)) if base is not None else None}
    if truncated and missing:  # finding is proof; not finding in a cut list is not
        return "not_verified", evidence, _cut_reason("migrations")
    if missing:
        return "failed", evidence, f"migration(ões) esperada(s) não aplicada(s): {', '.join(missing)}"
    return "ok", evidence, ""


def _tables_aspect(now, base) -> tuple:
    missing = sorted(set(base) - set(now))
    evidence = {"missing": missing, "new": len(set(now) - set(base))}
    if missing:
        return "failed", evidence, f"{len(missing)} tabela(s) sumiu(ram)"
    return "ok", evidence, ""


def _permissions_aspect(now, base, required) -> tuple:
    decisions = now["decisions"]
    evidence = {"required": {a: decisions.get(a, "ausente") for a in required},
                "api_actions": {a: now["api_actions"][a] for a in required if a in now["api_actions"]},
                "denied_in_baseline": []}
    failed, unverified = [], []
    for action in required:
        if action not in decisions:
            unverified.append(f"ação {action} não simulada")
        elif action not in base:
            unverified.append(f"ação {action} fora da foto")
        elif base[action] == "allowed" and decisions[action] == "denied":
            failed.append(action)
        elif base[action] == "denied" and decisions[action] == "denied":
            evidence["denied_in_baseline"].append(action)
            unverified.append("permissão já negada antes do deploy")
    if failed:
        return "failed", evidence, f"permissão negada depois do deploy: {', '.join(failed)}"
    if unverified:
        return "not_verified", evidence, "; ".join(dict.fromkeys(unverified))
    return "ok", evidence, ""


def _dependencies_check(entry, photo, seen, limits) -> dict:
    """The dependencies check of one resource against the photo (section 6.3 of SPEC-0102), a pure function: failed
    when one aspect fails; else not_verified when one could not be verified; else ok."""
    evidence = {"relations": entry["relations"], "dlq_of": entry["dlq_of"]}
    statuses, failed, unverified = [], [], {}
    for aspect in entry["aspects"]:
        if aspect == "signals":
            continue
        observed = seen[aspect]
        if "reason" in observed:
            unverified[aspect] = observed["reason"]
            continue
        now, truncated = observed["now"], observed["truncated"]
        base = photo.get(aspect)
        if truncated and aspect != "migrations":
            unverified[aspect] = _cut_reason(aspect)
            continue
        if base is None and aspect != "migrations":
            unverified[aspect] = f"{aspect} ausente da foto"
            continue
        if aspect == "queue":
            status, part, reason = _queue_aspect(now, base, entry["dlq_of"], limits)
        elif aspect == "subscriptions":
            status, part, reason = _subscriptions_aspect(now, base)
        elif aspect == "migrations":
            status, part, reason = _migrations_aspect(now, base, limits["migrations"].get(entry["resource"], []),
                                                      truncated)
        elif aspect == "tables":
            status, part, reason = _tables_aspect(now, base)
        else:
            status, part, reason = _permissions_aspect(now, base, entry["required"])
        evidence[aspect] = part
        statuses.append(status)
        if status == "failed":
            failed.append(f"{aspect}: {reason}")
        elif status == "not_verified":
            unverified[aspect] = reason
    evidence["not_verified"] = unverified
    deployment, resource = entry["deployment"], entry["resource"]
    if failed:
        return _check(deployment, "dependencies", "failed", evidence, "; ".join(failed), resource)
    if unverified:
        reason = "; ".join(f"{aspect}: {why}" for aspect, why in unverified.items())
        return _check(deployment, "dependencies", "not_verified", evidence, reason, resource)
    return _check(deployment, "dependencies", "ok", evidence, "dependências seguem a foto", resource)


def _per_minute(value, stat, window_seconds):
    """sum and count normalized per minute (the windows of the photo and of now differ); the others as they come."""
    if value is None or stat not in ("sum", "count"):
        return value
    return value / (window_seconds / 60)


def _signals_check(entry, photo, seen, window_seconds: int, increase: float) -> dict:
    """The signals check of one resource against the photo (section 6.3 of SPEC-0102), a pure function: an error or
    latency metric worse than the photo by more than --max-signal-increase fails; saturation and traffic never fail."""
    deployment, resource = entry["deployment"], entry["resource"]
    evidence = {"window_seconds": window_seconds, "baseline_window_seconds": None, "max_signal_increase": increase,
                "worse": [], "compared": 0, "without_baseline": [], "without_data": [], "other": []}
    observed = seen["signals"]
    reason = observed.get("reason")
    if reason is None and observed["truncated"]:
        reason = _cut_reason("signals")
    if reason is None and photo.get("signals") is None:
        reason = "signals ausente da foto"
    if reason:
        return _check(deployment, "signals", "not_verified", evidence, f"signals: {reason}", resource)
    base = photo["signals"]
    evidence["baseline_window_seconds"] = base["window_seconds"]
    for name, metric in sorted(observed["now"]["metrics"].items()):
        stat = name.rpartition("|")[2]
        kind = metric["kind"]
        before = base["metrics"].get(name)
        now = _per_minute(metric["value"], stat, window_seconds)
        then = _per_minute(before["value"], stat, base["window_seconds"]) if before else None
        if kind not in ("error", "latency"):
            evidence["other"].append({"metric": name, "kind": kind, "baseline": then, "now": now})
            continue
        if now is None:
            evidence["without_data"].append(name)
            continue
        if before is None or (kind == "latency" and not then):
            evidence["without_baseline"].append(name)
            continue
        evidence["compared"] += 1
        worse = now > 0 if not then else now > then * (1 + increase)
        if worse:
            evidence["worse"].append({"metric": name, "kind": kind, "baseline": then, "now": now})
    if evidence["worse"]:
        names = ", ".join(w["metric"] for w in evidence["worse"])
        return _check(deployment, "signals", "failed", evidence,
                      f"{len(evidence['worse'])} métrica(s) pior(es) que a foto acima de {increase:g}: {names}",
                      resource)
    if not evidence["compared"]:
        return _check(deployment, "signals", "not_verified", evidence, f"signals: {NOTHING_COMPARABLE}", resource)
    return _check(deployment, "signals", "ok", evidence,
                  f"{evidence['compared']} métrica(s) de erro ou latência dentro do limite", resource)


def _resource_skipped(entry, reason) -> list:
    """The checks of one resource that are not verified before any probe (cut, no photo, old photo, out of it)."""
    evidence = {"dependencies": {"relations": entry["relations"], "dlq_of": entry["dlq_of"]}, "signals": {}}
    return [_check(entry["deployment"], name, "not_verified", dict(evidence[name]), reason, entry["resource"])
            for name in entry["checks"]]


def _resource_checks(setup, args, scope, max_resources, baseline, limits, window) -> list:
    """The dependencies and signals checks of every resource of the scope (section 6.3 of SPEC-0102). Without a
    verify@2 photo, no resource probe runs."""
    checks = []
    for position, entry in enumerate(scope):
        reason = None
        if position >= max_resources:
            reason = f"acima de --max-resources ({max_resources})"
        elif baseline is None:
            reason = NO_RESOURCE_BASELINE
        elif baseline["contract"] != VERIFY_CONTRACT:
            reason = OLD_BASELINE
        elif entry["resource"] not in baseline["dependencies"]:
            reason = OUT_OF_PHOTO
        if reason:
            checks += _resource_skipped(entry, reason)
            continue
        photo = baseline["dependencies"][entry["resource"]]
        seen = _verify_observe_resource(setup, args, entry, window)
        if "dependencies" in entry["checks"]:
            checks.append(_dependencies_check(entry, photo, seen, limits))
        checks.append(_signals_check(entry, photo, seen, limits["window_seconds"], limits["increase"]))
    return checks


def _resource_photo(setup, args, scope, max_resources, window) -> tuple:
    """(dependencies, not_verified) of the photo: only the fields of rule 4a of ADR-0026; an aspect the probe did not
    sustain stays out, with its reason (starting with the aspect) in not_verified."""
    dependencies, not_verified = {}, []
    for position, entry in enumerate(scope):
        base = {"deployment": entry["deployment"], "resource": entry["resource"]}
        if position >= max_resources:
            not_verified += [dict(base, check=name, reason=f"acima de --max-resources ({max_resources})")
                             for name in entry["checks"]]
            continue
        state = {"deployment": entry["deployment"], "relations": entry["relations"], "dlq_of": entry["dlq_of"]}
        for aspect, observed in _verify_observe_resource(setup, args, entry, window).items():
            check = VERIFY_ASPECTS[aspect][0]
            if "reason" in observed:
                not_verified.append(dict(base, check=check, reason=f"{aspect}: {observed['reason']}"))
            elif observed["truncated"]:
                not_verified.append(dict(base, check=check, reason=f"{aspect}: {_cut_reason(aspect)}"))
            else:
                state[aspect] = _photo_value(aspect, observed["now"])
        dependencies[entry["resource"]] = state
    return dependencies, not_verified


def _verify_plan(setup, args) -> dict:
    """What both phases check before any probe, after the arguments: the deployments (exit 2), the resources of the
    scope (exit 2 for a --resource out of the graph)."""
    requested, max_resources = _verify_resource_options(args)
    graph = read_probe_graph(setup["atlas"])
    targets = _verify_targets(setup, args, graph)
    scope = _verify_scope(setup, args, graph, requested)
    return {"targets": targets, "scope": scope, "max_resources": max_resources}


def cmd_verify_snapshot(args) -> int:
    """verify snapshot (SPEC-0090, SPEC-0102, ADR-0024, ADR-0026): the photo of a service in an environment before the
    merge, with the dependencies of the scope, in a task file outside the atlas."""
    setup = _verify_setup(args)
    out = _verify_out(args.out, setup["atlas"])
    window = args.since or VERIFY_SINCE
    _verify_duration(window, "--since")
    plan = _verify_plan(setup, args)
    targets = plan["targets"]
    _verify_production(setup, args, targets)
    deployments, not_verified = {}, []
    for target in targets:
        seen = _verify_observe(setup, args, target, window)
        deployments[target["deployment"]] = _observed(target, seen)
        missing = []
        if "reason" in seen["status"]:
            missing += [("delivery", seen["status"]["reason"]), ("runtime", seen["status"]["reason"])]
        elif "reason" in seen["events"]:
            missing.append(("runtime", seen["events"]["reason"]))
        if _logs_problem(seen):
            missing.append(("logs", _logs_problem(seen)))
        not_verified += [{"deployment": target["deployment"], "check": check, "reason": reason}
                         for check, reason in missing]
    dependencies, resources_not_verified = _resource_photo(setup, args, plan["scope"], plan["max_resources"], window)
    not_verified += resources_not_verified
    photo = {"contract": VERIFY_CONTRACT, "service": args.service, "environment": args.env,
             "taken_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "deployments": deployments, "dependencies": dependencies, "not_verified": not_verified}
    problems = validate_verify_snapshot(photo)
    if problems:  # never written out of the contract
        raise AtlasError(f"foto fora do contrato {VERIFY_CONTRACT} — {'; '.join(problems[:10])}", 1)
    write_exclusive(out, json.dumps(photo, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"foto {VERIFY_CONTRACT} gravada em {out}: {args.service} em {args.env}, {len(deployments)} deployment(s), "
          f"{len(dependencies)} recurso(s), {len(not_verified)} verificação(ões) não feita(s)")
    for item in not_verified:
        where = f"{item['deployment']} · {item['resource']}" if "resource" in item else item["deployment"]
        print(f"- não verificado: {where} · {item['check']} — {item['reason']}")
    print("a foto é da tarefa: apague o arquivo no fim (references/verify.md)")
    return 0


def _check(deployment, check, status, evidence, reason, resource=None) -> dict:
    return {"deployment": deployment, "resource": resource, "check": check, "status": status, "evidence": evidence,
            "reason": reason}


def _delivery_check(target, seen, expect: str) -> dict:
    deployment = target["deployment"]
    if "reason" in seen["status"]:
        return _check(deployment, "delivery", "not_verified", {"expected": expect}, seen["status"]["reason"])
    expected = parse_image_ref(normalize_expected_image(expect))
    workloads, pods = _status_parts(seen)
    missing = sorted(str(w.get("workload")) for w in workloads if w.get("found") is False)
    complete = bool(workloads) and all(w.get("rollout_complete") is True for w in workloads)
    ready = [p for p in pods if p.get("ready") is True]
    other = [{"pod": str(p.get("pod")), "images": [str(i) for i in (p.get("images") or [])]} for p in ready
             if not any(image_matches(i, expected) for i in (p.get("images") or []))]
    evidence = {"expected": expect, "rollout_complete": complete, "ready_pods": len(ready),
                "pods_with_other_image": other, "workloads_not_found": missing}
    reasons = []
    if missing:
        reasons.append(f"workload não encontrado: {', '.join(missing)}")
    if not workloads:
        reasons.append("a probe de status não trouxe o workload")
    elif not complete:
        reasons.append("rollout não concluído")
    if not ready:
        reasons.append("nenhum pod pronto")
    if other:
        reasons.append(f"{len(other)} pod(s) pronto(s) com outra imagem")
    if reasons:
        return _check(deployment, "delivery", "failed", evidence, "; ".join(reasons))
    return _check(deployment, "delivery", "ok", evidence, f"{len(ready)} pod(s) pronto(s) com {expect}")


def _baseline_entry(baseline, deployment, check):
    """The snapshot entry of a deployment usable for `check`, or None (no photo, deployment absent from it, or
    that check not verified in it)."""
    if not baseline or deployment not in baseline["deployments"]:
        return None
    if any(i["deployment"] == deployment and i["check"] == check for i in baseline["not_verified"]):
        return None
    return baseline["deployments"][deployment]


def _runtime_check(target, seen, baseline, max_restarts: int) -> dict:
    deployment = target["deployment"]
    if "reason" in seen["status"]:
        return _check(deployment, "runtime", "not_verified", {}, seen["status"]["reason"])
    workloads, pods = _status_parts(seen)
    before = _baseline_entry(baseline, deployment, "runtime") or {"restarts": {}, "warnings": []}
    now = _observed(target, seen)
    missing = sorted(str(w.get("workload")) for w in workloads if w.get("found") is False)
    not_ready = sorted(str(p.get("pod")) for p in pods if p.get("ready") is not True)
    new_restarts = {}
    for pod, count in now["restarts"].items():
        extra = count - before["restarts"].get(pod, 0)
        if extra > 0:
            new_restarts[pod] = extra
    total = sum(new_restarts.values())
    evidence = {"workloads_not_found": missing, "not_ready_pods": not_ready, "new_restarts": new_restarts,
                "new_restarts_total": total, "max_new_restarts": max_restarts,
                "baseline": "foto" if _baseline_entry(baseline, deployment, "runtime") else "sem foto (desde 0)"}
    reasons = []
    if missing:
        reasons.append(f"workload não encontrado: {', '.join(missing)}")
    if not workloads:
        reasons.append("a probe de status não trouxe o workload")
    if not_ready:
        reasons.append(f"{len(not_ready)} pod(s) não pronto(s)")
    if total > max_restarts:
        reasons.append(f"{total} restart(s) novo(s), acima de {max_restarts}")
    if "reason" in seen["events"]:
        evidence["new_warnings"] = []
        if reasons:
            return _check(deployment, "runtime", "failed", evidence, "; ".join(reasons))
        return _check(deployment, "runtime", "not_verified", evidence, seen["events"]["reason"])
    new_warnings = [w for w in now["warnings"] if w not in set(before["warnings"])]
    evidence["new_warnings"] = new_warnings
    if new_warnings:
        reasons.append(f"{len(new_warnings)} aviso(s) novo(s)")
    if reasons:
        return _check(deployment, "runtime", "failed", evidence, "; ".join(reasons))
    return _check(deployment, "runtime", "ok", evidence, "pods prontos, sem restart nem aviso novo")


def _logs_check(target, seen, baseline, max_errors: int, window_seconds: int) -> dict:
    deployment = target["deployment"]
    evidence = {"window_seconds": window_seconds, "max_new_errors": max_errors}
    problem = _logs_problem(seen)
    if problem:
        return _check(deployment, "logs", "not_verified", evidence, problem)
    if not baseline:
        return _check(deployment, "logs", "not_verified", evidence, NO_BASELINE)
    before = _baseline_entry(baseline, deployment, "logs")
    if before is None:
        return _check(deployment, "logs", "not_verified", evidence,
                      "a foto não tem os logs deste deployment: erros novos e antigos não se separam")
    now = _observed(target, seen)["error_signatures"]
    new = {sig: count for sig, count in sorted(now.items()) if sig not in before["error_signatures"]}
    evidence.update(new_error_signatures=new, known_error_signatures=len(now) - len(new),
                    truncated=bool(seen["logs"]["result"]["truncated"]))
    if len(new) > max_errors:
        return _check(deployment, "logs", "failed", evidence,
                      f"{len(new)} assinatura(s) de erro nova(s), acima de {max_errors}")
    return _check(deployment, "logs", "ok", evidence, f"{len(new)} assinatura(s) de erro nova(s)")


def verify_suggestion(targets) -> str:
    """The fixed text of `degradou`: the person decides the rollback, through the configuration repository of the
    delivery (SPEC-0086); never a command, never executed."""
    repositories = sorted({r for t in targets for r in t["config_repositories"]})
    where = (f"no repositório de configuração do delivery ({', '.join(repositories)})" if repositories
             else "no repositório de configuração do delivery (não encontrado no atlas: veja o `context` do serviço)")
    text = ("Degradou: mostre as evidências à pessoa e deixe que ela decida se volta a versão anterior. O rollback, "
            f"se ela decidir, é feito {where}, pelo fluxo de mudança do time. O verify não executa nenhuma ação "
            "no ambiente.")
    return "" if SUGGESTION_COMMAND_RE.search(text) else text


def print_verify(result: dict, args) -> None:
    print(f"# verify — {args.service} em {args.env}: {result['verdict']}")
    print()
    print(f"Imagem esperada: `{args.expect_image}`.")
    print()
    print("| deployment | recurso | verificação | status | motivo |")
    print("|---|---|---|---|---|")
    for item in result["checks"]:
        reason = item["reason"].replace("|", "\\|")
        print(f"| {item['deployment']} | {item['resource'] or ''} | {item['check']} | {item['status']} | {reason} |")
    print()
    print("## Evidências")
    for item in result["checks"]:
        where = f"{item['deployment']} · {item['resource']}" if item["resource"] else item["deployment"]
        print(f"- {where} · {item['check']}: `{json.dumps(item['evidence'], ensure_ascii=False)}`")
    if result["suggestion"]:
        print()
        print("## Sugestão")
        print(result["suggestion"])


def cmd_verify_compare(args) -> int:
    """verify compare (SPEC-0090, SPEC-0102, ADR-0024, ADR-0026): delivery, runtime and logs of each deployment against
    the snapshot and the expected image, dependencies and signals of each resource of the scope against the photo;
    verdict passou (0), degradou (1) or inconclusivo (5). Nothing is written to the atlas."""
    setup = _verify_setup(args)
    match = EXPECT_IMAGE_RE.match(normalize_expected_image(args.expect_image))
    if not match or not (match.group("tag") or match.group("digest")):
        raise AtlasError("--expect-image inválido — use o caminho da imagem com :<tag> e/ou @<digest> (ex.: "
                         "acme/api:1.4.2)", 2)
    window = args.window or VERIFY_WINDOW
    window_seconds = _verify_duration(window, "--window")
    max_errors = _verify_limit(args.max_new_errors, "--max-new-errors")
    max_restarts = _verify_limit(args.max_new_restarts, "--max-new-restarts")
    limits = {"max_new_dlq": _verify_limit(args.max_new_dlq, "--max-new-dlq"),
              "max_queue_age": _verify_duration(args.max_queue_age or VERIFY_MAX_QUEUE_AGE, "--max-queue-age"),
              "increase": _verify_increase(args.max_signal_increase), "window_seconds": window_seconds}
    migrations = _parse_expect_migrations(args.expect_migration)
    baseline = _verify_baseline(args.baseline, args.service, args.env) if args.baseline is not None else None
    plan = _verify_plan(setup, args)
    limits["migrations"] = _expected_migrations(migrations, plan["scope"])
    targets = plan["targets"]
    _verify_production(setup, args, targets)
    checks = []
    for target in targets:
        seen = _verify_observe(setup, args, target, window)
        checks += [_delivery_check(target, seen, args.expect_image),
                   _runtime_check(target, seen, baseline, max_restarts),
                   _logs_check(target, seen, baseline, max_errors, window_seconds)]
    checks += _resource_checks(setup, args, plan["scope"], plan["max_resources"], baseline, limits, window)
    verdict = verdict_of(c["status"] for c in checks)
    result = {"contract": VERIFY_CONTRACT, "verdict": verdict, "checks": checks,
              "suggestion": verify_suggestion(targets) if verdict == "degradou" else ""}
    problems = validate_verify_result(result)
    if problems:
        raise AtlasError(f"resultado fora do contrato {VERIFY_CONTRACT} — {'; '.join(problems[:10])}", 1)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print_verify(result, args)
    return VERDICT_EXITS[verdict]


# ---- verify track: where the delivery of a commit is (SPEC-0106, ADR-0024)

TRACK_CONTRACT = "track@1"
TRACK_STAGES = ("pipeline", "image", "gitops", "rollout")
TRACK_STATUSES = ("pending", "running", "ok", "failed", "not_verified")
TRACK_STATE_ORDER = ("failed", "running", "pending", "not_verified")  # the first one present is the state; else ok
TRACK_EXITS = {"failed": 1, "running": 6, "pending": 6, "not_verified": 5, "ok": 0}
TRACK_RESULT_KEYS = ("contract", "service", "environment", "commit", "state", "current_stage", "expected_image",
                     "expected_image_source", "stages")
TRACK_STAGE_KEYS = ("stage", "deployment", "status", "evidence", "reason")
TRACK_SOURCES = ("expect-image", "commit-tag")
TRACK_COMMIT_RE = re.compile(r"^[0-9a-f]{40}\Z")
TRACK_FAILED_CONCLUSIONS = ("failure", "timed_out", "cancelled", "startup_failure", "action_required")
TRACK_OK_CONCLUSIONS = ("success", "neutral", "skipped")
TRACK_TAG_PIECE_RE = re.compile(r"[-_.]")
TRACK_MIN_PIECE = 7  # a piece of the tag that is a prefix of the commit with at least this many characters
BAD_COMMIT = "commit precisa ser o sha completo (40 hexadecimais)"
NO_RUN = "nenhuma execução da CI para o commit ainda"
NO_CODE = "serviço sem repositório de código no atlas"
AMBIGUOUS_IMAGE = "mais de uma imagem com o commit: passe --expect-image"
UNKNOWN_IMAGE = "imagem do commit não identificada: passe --expect-image"
WAITING_IMAGE = "aguardando a imagem no GitOps"
CUT_STATUS = "probe de status cortada"
NO_EXPECTED = "sem imagem esperada"


def _track_flat(value) -> bool:
    """A flat object: every value a scalar or a list of scalars (an item of the adapter)."""
    return isinstance(value, dict) and all(
        _probe_scalar(v) or (isinstance(v, list) and all(_probe_scalar(x) for x in v)) for v in value.values())


def track_state(statuses) -> str:
    """failed > running > pending > not_verified > ok (SPEC-0106, section 6)."""
    statuses = set(statuses)
    return next((state for state in TRACK_STATE_ORDER if state in statuses), "ok")


def track_current_stage(stages) -> str:
    """The first stage whose status is not ok, in the order pipeline -> image -> gitops -> rollout and, inside a stage,
    the deployments by id; "" when every stage is ok."""
    open_stages = sorted((TRACK_STAGES.index(s["stage"]), s["deployment"]) for s in stages
                         if isinstance(s, dict) and s.get("stage") in TRACK_STAGES and s.get("status") != "ok"
                         and isinstance(s.get("deployment"), str))
    return TRACK_STAGES[open_stages[0][0]] if open_stages else ""


def _track_stage_problems(position, item) -> list:
    where = f"stages[{position}]"
    if not isinstance(item, dict):
        return [f"{where} precisa ser um objeto"]
    problems = _closed_keys(item, TRACK_STAGE_KEYS, TRACK_STAGE_KEYS[:-1], where)
    if "stage" in item and item["stage"] not in TRACK_STAGES:
        problems.append(f"{where}.stage precisa ser um de: {', '.join(TRACK_STAGES)}")
    if "status" in item and item["status"] not in TRACK_STATUSES:
        problems.append(f"{where}.status precisa ser um de: {', '.join(TRACK_STATUSES)}")
    deployment = item.get("deployment")
    if "deployment" in item:
        if not isinstance(deployment, str):
            problems.append(f"{where}.deployment precisa ser um texto")
        elif item.get("stage") == "pipeline" and deployment:
            problems.append(f"{where}.deployment precisa ser \"\" no pipeline")
        elif item.get("stage") in TRACK_STAGES[1:] and not deployment:
            problems.append(f"{where}.deployment precisa ser o id do deployment")
    reason = item.get("reason", "")
    if not isinstance(reason, str):
        problems.append(f"{where}.reason precisa ser um texto")
    elif item.get("status") != "ok" and not reason.strip():
        problems.append(f"{where}: reason obrigatório fora de ok")
    evidence = item.get("evidence")
    if "evidence" in item:
        if not isinstance(evidence, dict):
            problems.append(f"{where}.evidence precisa ser um objeto")
        else:
            for key, value in evidence.items():
                if key == "runs" and item.get("stage") == "pipeline":
                    if not (isinstance(value, list) and all(_track_flat(v) for v in value)):
                        problems.append(f"{where}.evidence.runs precisa ser uma lista de objetos planos")
                elif not (_probe_scalar(value) or (isinstance(value, list) and all(_probe_scalar(v) for v in value))):
                    problems.append(f"{where}.evidence.{_show(key)} precisa ser escalar ou lista de escalares")
    return problems


def validate_track_result(data) -> list:
    """Problems of the output of `verify track --json` (track@1, SPEC-0106); [] = valid: closed keys, the commit as a
    full sha, stage and status in their lists, exactly one pipeline stage (deployment ""), reason in every stage out
    of ok, evidence with scalars (and, in the pipeline, the list runs of flat objects), and state and current_stage
    by the rule. Never quotes a value."""
    if not isinstance(data, dict):
        return ["a saída precisa ser um objeto JSON"]
    problems = _closed_keys(data, TRACK_RESULT_KEYS, TRACK_RESULT_KEYS)
    if data.get("contract") != TRACK_CONTRACT:
        problems.append(f"contract precisa ser {TRACK_CONTRACT}")
    for key in ("service", "environment"):
        if key in data and not _verify_text(data[key]):
            problems.append(f"{key} precisa ser um texto não vazio")
    if "commit" in data and not (isinstance(data["commit"], str) and TRACK_COMMIT_RE.match(data["commit"])):
        problems.append("commit precisa ser o sha completo (40 hexadecimais minúsculos)")
    if "state" in data and data["state"] not in TRACK_EXITS:
        problems.append(f"state precisa ser um de: {', '.join(TRACK_EXITS)}")
    image, source = data.get("expected_image"), data.get("expected_image_source")
    if not isinstance(image, str) or source not in TRACK_SOURCES + ("",):
        problems.append(f"expected_image precisa ser um texto e expected_image_source um de: "
                        f"{', '.join(TRACK_SOURCES)} ou \"\"")
    elif (image == "") != (source == ""):
        problems.append("expected_image e expected_image_source ficam vazios juntos")
    stages = data.get("stages")
    if not isinstance(stages, list) or not stages:
        return problems + ["stages precisa ser uma lista não vazia"]
    for position, item in enumerate(stages, 1):
        problems += _track_stage_problems(position, item)
    if [s.get("stage") for s in stages if isinstance(s, dict)].count("pipeline") != 1:
        problems.append("stages precisa ter exatamente uma etapa pipeline")
    statuses = [s.get("status") for s in stages if isinstance(s, dict)]
    if data.get("state") in TRACK_EXITS and data["state"] != track_state(statuses):
        problems.append(f"state fora da regra (failed > running > pending > not_verified > ok: "
                        f"{track_state(statuses)})")
    if "current_stage" in data and data["current_stage"] != track_current_stage(stages):
        problems.append("current_stage precisa ser a primeira etapa não ok (pipeline, image, gitops, rollout)")
    return problems


def _track_stage(stage, deployment, status, evidence, reason) -> dict:
    return {"stage": stage, "deployment": deployment, "status": status, "evidence": evidence, "reason": reason}


def _track_probe(setup, args, capability, verb, deployment, commit=None, lines=None) -> dict:
    """One probe of the track by run_probe (the path, protections, mask and log of `probe`): {"result"} or
    {"reason"}. A refusal, failure or answer with error becomes the reason (the stage is not verified)."""
    query = argparse.Namespace(capability=capability, verb=verb, service=args.service, env=args.env, since=None,
                               lines=lines, summary=False, confirm_production=args.confirm_production,
                               atlas=args.atlas, json=True, resource=None, commit=commit)
    try:
        outcome = run_probe(query, setup["name"], setup["probes"], setup["entry"], deployment)
    except AtlasError as e:
        return {"reason": f"probe {capability} {verb} {'recusada' if e.code == 4 else 'falhou'} — {e}"}
    if outcome["result"]["status"] != "ok":
        return {"reason": f"probe {capability} {verb} respondeu com erro: {outcome['message'] or '(sem mensagem)'}"}
    return {"result": outcome["result"]}


def _pipeline_stage(seen, repositories) -> dict:
    """The pipeline stage from the items of pipeline runs (section 6 of SPEC-0106): a failure seen wins (also in a cut
    probe); a cut probe or a repository without access is not verified; then running, pending (no run) and ok."""
    evidence = {"repositories": repositories, "runs": []}
    if not repositories:
        return _track_stage("pipeline", "", "not_verified", evidence, NO_CODE)
    if "reason" in seen:
        return _track_stage("pipeline", "", "not_verified", evidence, seen["reason"])
    result = seen["result"]
    items = [item for item in result["items"] if isinstance(item, dict)]
    runs = [item for item in items if item.get("found") is not False]
    missing = sorted(str(item.get("repository")) for item in items if item.get("found") is False)
    evidence.update(runs=items, missing_repositories=missing)
    failed = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") in TRACK_FAILED_CONCLUSIONS]
    if failed:
        conclusions = ", ".join(sorted({str(r.get("conclusion")) for r in failed}))
        return _track_stage("pipeline", "", "failed", evidence,
                            f"{len(failed)} execução(ões) da CI terminou(aram) com {conclusions}")
    if result["truncated"]:
        return _track_stage("pipeline", "", "not_verified", evidence,
                            "probe de runs cortada: alguma execução pode ter ficado de fora")
    if missing:
        return _track_stage("pipeline", "", "not_verified", evidence,
                            f"repositório sem acesso ou inexistente: {', '.join(missing)}")
    running = [r for r in runs if r.get("status") != "completed"]
    if running:
        return _track_stage("pipeline", "", "running", evidence, f"{len(running)} execução(ões) da CI em andamento")
    if not runs:
        return _track_stage("pipeline", "", "pending", evidence, NO_RUN)
    odd = sorted({str(r.get("conclusion")) for r in runs if r.get("conclusion") not in TRACK_OK_CONCLUSIONS})
    if odd:
        return _track_stage("pipeline", "", "not_verified", evidence,
                            f"conclusão da CI não reconhecida: {', '.join(odd)}")
    return _track_stage("pipeline", "", "ok", evidence, f"{len(runs)} execução(ões) da CI concluída(s) com sucesso")


def _track_application(seen) -> tuple:
    """(the Application item, None) of a gitops application answer, or (None, the reason)."""
    if "reason" in seen:
        return None, seen["reason"]
    items = [item for item in seen["result"]["items"] if isinstance(item, dict)]
    if not items:
        return None, "a probe de gitops não trouxe a Application"
    if items[0].get("found") is False:
        return None, f"Application {items[0].get('application')} não encontrada no GitOps"
    return items[0], None


def _app_images(app) -> list:
    return [str(i) for i in (app.get("images") or []) if isinstance(i, str) and i] if app else []


def _tag_has_commit(tag: str, commit: str) -> bool:
    """True when the tag is the commit, or has a piece (split by "-", "_" or ".") of 7 or more characters that is a
    prefix of the commit."""
    if tag.lower() == commit:
        return True
    return any(len(piece) >= TRACK_MIN_PIECE and commit.startswith(piece.lower())
               for piece in TRACK_TAG_PIECE_RE.split(tag))


def track_commit_image(apps, delivery_images, commit) -> tuple:
    """(image, problem) of the image of the commit among the images of the Applications: the one whose path is in
    delivery.images (all, when the list is empty) and whose tag carries the commit; two different ones = the
    ambiguity problem; none = ("", "")."""
    paths = {parse_image_ref(normalize_expected_image(image))[0] for image in delivery_images}
    found = []
    for app in apps:
        for image in _app_images(app):
            path, tag, _ = parse_image_ref(image)
            if (not paths or path in paths) and tag and _tag_has_commit(tag, commit) and image not in found:
                found.append(image)
    if len(found) > 1:
        return "", AMBIGUOUS_IMAGE
    return (found[0], "") if found else ("", "")


def _synced_healthy(app) -> bool:
    return bool(app) and app.get("sync_status") == "Synced" and app.get("health_status") == "Healthy"


def _image_stage(target, seen, expected, image_problem, pipeline_status) -> dict:
    """The image stage of one deployment: ok when the expected image is in the Application; pending while it is not
    (or, with no expected image, while the delivery still moves); not_verified without the Application, with an
    ambiguous image or with no image of the commit once the delivery stopped."""
    deployment = target["deployment"]
    evidence = {"expected": expected[0] if expected else ""}
    app, reason = _track_application(seen)
    if reason:
        return _track_stage("image", deployment, "not_verified", evidence, reason)
    images = _app_images(app)
    evidence.update(application=str(app.get("application") or ""), images=images,
                    sync_status=str(app.get("sync_status") or ""), health_status=str(app.get("health_status") or ""))
    if expected:
        wanted = parse_image_ref(expected[0])
        if any(image_matches(image, wanted) for image in images):
            return _track_stage("image", deployment, "ok", evidence, "imagem esperada na Application")
        return _track_stage("image", deployment, "pending", evidence, "a imagem esperada ainda não está na Application")
    if image_problem:
        return _track_stage("image", deployment, "not_verified", evidence, image_problem)
    if pipeline_status != "ok" or not _synced_healthy(app):
        return _track_stage("image", deployment, "pending", evidence,
                            "a imagem do commit ainda não apareceu na Application")
    return _track_stage("image", deployment, "not_verified", evidence, UNKNOWN_IMAGE)


def _gitops_stage(target, seen, image) -> dict:
    """The gitops stage of one deployment, after its image stage (section 6 of SPEC-0106)."""
    deployment = target["deployment"]
    app, _ = _track_application(seen)
    evidence = {}
    if app:
        evidence = {key: str(app.get(key) or "") for key in ("application", "sync_status", "health_status",
                                                              "revision", "operation_phase", "operation_finished_at",
                                                              "reconciled_at")}
    if image["status"] == "not_verified":
        return _track_stage("gitops", deployment, "not_verified", evidence,
                            f"etapa image não verificada: {image['reason']}")
    if image["status"] == "pending":
        return _track_stage("gitops", deployment, "pending", evidence, WAITING_IMAGE)
    sync, health, phase = evidence["sync_status"], evidence["health_status"], evidence["operation_phase"]
    shown = f"sync {sync or '?'}, health {health or '?'}, fase {phase or '?'}"
    if health in ("Degraded", "Missing") or phase in ("Failed", "Error"):
        return _track_stage("gitops", deployment, "failed", evidence, f"Application com problema ({shown})")
    if health in ("Suspended", "Unknown"):
        return _track_stage("gitops", deployment, "not_verified", evidence, f"Application sem saúde conclusiva "
                            f"({shown})")
    if phase == "Running" or health == "Progressing" or sync == "OutOfSync":
        return _track_stage("gitops", deployment, "running", evidence, f"Application aplicando a mudança ({shown})")
    if sync == "Synced" and health == "Healthy":
        return _track_stage("gitops", deployment, "ok", evidence, "Application sincronizada e saudável")
    return _track_stage("gitops", deployment, "not_verified", evidence, f"estado da Application não reconhecido "
                        f"({shown})")


def _rollout_stage(target, seen, expected) -> dict:
    """The rollout stage of one deployment from runtime status (section 6 of SPEC-0106): matched with the expected
    image by the digest, when it has one, else by the tag (the rule of compare)."""
    deployment = target["deployment"]
    evidence = {"expected": expected[0] if expected else ""}
    if not expected:
        return _track_stage("rollout", deployment, "not_verified", evidence, NO_EXPECTED)
    if "reason" in seen:
        return _track_stage("rollout", deployment, "not_verified", evidence, seen["reason"])
    result = seen["result"]
    if result["truncated"]:
        return _track_stage("rollout", deployment, "not_verified", evidence, CUT_STATUS)
    items = [item for item in result["items"] if isinstance(item, dict)]
    workloads = [item for item in items if item.get("kind") == "workload"]
    pods = [item for item in items if item.get("kind") == "pod"]
    wanted = parse_image_ref(expected[0])

    def matches(pod):
        return any(isinstance(i, str) and image_matches(i, wanted) for i in (pod.get("images") or []))

    new = [pod for pod in pods if matches(pod)]
    missing = sorted(str(w.get("workload")) for w in workloads if w.get("found") is False)
    crashing = sorted(str(p.get("pod")) for p in new if p.get("ready") is not True
                      and _verify_int(p.get("restarts")) and p["restarts"] > 0)
    complete = bool(workloads) and all(w.get("rollout_complete") is True for w in workloads)
    evidence.update(rollout_complete=complete, pods=len(pods), pods_with_expected_image=len(new),
                    ready_pods_with_expected_image=len([p for p in new if p.get("ready") is True]),
                    crashing_pods=crashing, workloads_not_found=missing)
    if not workloads:
        return _track_stage("rollout", deployment, "not_verified", evidence, "a probe de status não trouxe o workload")
    if missing:
        return _track_stage("rollout", deployment, "failed", evidence, f"workload não encontrado: {', '.join(missing)}")
    if crashing:
        return _track_stage("rollout", deployment, "failed", evidence,
                            f"pod(s) com a imagem esperada reiniciando sem ficar pronto(s): {', '.join(crashing)}")
    if not new:
        return _track_stage("rollout", deployment, "pending", evidence, "nenhum pod com a imagem esperada ainda")
    if complete and all(p.get("ready") is True and matches(p) for p in pods):
        return _track_stage("rollout", deployment, "ok", evidence, f"{len(new)} pod(s) pronto(s) com a imagem esperada")
    return _track_stage("rollout", deployment, "running", evidence,
                        f"rollout em andamento: {len(new)} de {len(pods)} pod(s) com a imagem esperada")


def _track_masks(setup) -> list:
    """The patterns of the probe redaction plus every local access value and every declared credential value of this
    machine, masked literally in the evidence and reasons (on top of the mask of each probe)."""
    access = local_access(setup["entry"].get("access"))
    literals = [v for block in ("clusters", "cloud", "urls") for v in (access.get(block) or {}).values()
                if isinstance(v, str)]
    literals += [v for adapter in setup["probes"]["adapters"].values() for v in adapter_values(adapter)]
    return probe_extras(setup["shared"]) + literal_masks(literals)


def print_track(result: dict) -> None:
    print(f"# verify track — {result['service']} em {result['environment']}: {result['state']}")
    print()
    print(f"Commit: `{result['commit']}`.")
    print(f"Etapa atual: {result['current_stage'] or '(nenhuma: a entrega chegou)'}.")
    if result["expected_image"]:
        print(f"Imagem esperada: `{result['expected_image']}` ({result['expected_image_source']}).")
    else:
        print("Imagem esperada: (não identificada).")
    print()
    print("| Etapa | Deployment | Status | Motivo |")
    print("|---|---|---|---|")
    for item in result["stages"]:
        reason = str(item.get("reason") or "").replace("|", "\\|").replace("\n", " ")
        print(f"| {item['stage']} | {item['deployment'] or '-'} | {item['status']} | {reason} |")
    print()
    if result["state"] == "ok":
        print("A entrega chegou: use a imagem esperada no --expect-image do verify compare.")
    elif TRACK_EXITS[result["state"]] == 6:
        print("Ainda não chegou: repita o verify track depois da janela.")


def cmd_verify_track(args) -> int:
    """verify track (SPEC-0106, ADR-0024): where the delivery of a commit is — pipeline, image, gitops and rollout —
    by the probes pipeline runs (once), gitops application and runtime status (per deployment). Exits 0 ok, 1 failed,
    5 not_verified, 6 running or pending; 2 argument, 3 no configuration, 4 probes off or production without
    --confirm-production. Read only: nothing is written but the lines of probes.log."""
    setup = _verify_setup(args)
    commit = str(args.commit).lower()
    if not TRACK_COMMIT_RE.match(commit):
        raise AtlasError(BAD_COMMIT, 2)
    expected = None
    if args.expect_image is not None:
        text = normalize_expected_image(args.expect_image)
        match = EXPECT_IMAGE_RE.match(text)
        if not match or not (match.group("tag") or match.group("digest")):
            raise AtlasError("--expect-image inválido — use o caminho da imagem com :<tag> e/ou @<digest> (ex.: "
                             "acme/api:1.4.2)", 2)
        expected = (text, "expect-image")
    graph = read_probe_graph(setup["atlas"])
    targets = _verify_targets(setup, args, graph)
    _verify_production(setup, args, targets)
    index = _Index(graph)
    key = _service_key(index, args.service)
    code_edges = _code_edges(key, index)
    repositories = sorted({edge["to"].split(":", 1)[1] for edge in code_edges})
    delivery_images = _code_images(code_edges, index.sources(key, "deploys", "deployment"), index)
    pipeline_seen = (_track_probe(setup, args, "pipeline", "runs", targets[0]["deployment"], commit=commit)
                     if repositories else {})
    gitops_seen = {t["deployment"]: _track_probe(setup, args, "gitops", "application", t["deployment"])
                   for t in targets}
    status_seen = {t["deployment"]: _track_probe(setup, args, "runtime", "status", t["deployment"],
                                                 lines=PROBE_LINES_MAX) for t in targets}
    pipeline = _pipeline_stage(pipeline_seen, repositories)
    image_problem = ""
    if expected is None:
        apps = [_track_application(seen)[0] for seen in gitops_seen.values()]
        found, image_problem = track_commit_image([a for a in apps if a], delivery_images, commit)
        expected = (found, "commit-tag") if found else None
    images = [_image_stage(t, gitops_seen[t["deployment"]], expected, image_problem, pipeline["status"])
              for t in targets]
    gitops = [_gitops_stage(t, gitops_seen[t["deployment"]], image) for t, image in zip(targets, images)]
    rollout = [_rollout_stage(t, status_seen[t["deployment"]], expected) for t in targets]
    masks = _track_masks(setup)
    stages = []
    for item in [pipeline] + images + gitops + rollout:
        item["evidence"], item["reason"] = probe_mask(item["evidence"], masks), probe_mask(item["reason"], masks)
        stages.append(item)
    state = track_state(s["status"] for s in stages)
    result = {"contract": TRACK_CONTRACT, "service": args.service, "environment": args.env, "commit": commit,
              "state": state, "current_stage": track_current_stage(stages),
              "expected_image": expected[0] if expected else "", "expected_image_source": expected[1] if expected
              else "", "stages": stages}
    problems = validate_track_result(result)
    if problems:
        raise AtlasError(f"resultado fora do contrato {TRACK_CONTRACT} — {'; '.join(problems[:10])}", 1)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print_track(result)
    return TRACK_EXITS[state]


def cmd_verify(args) -> int:
    """verify snapshot | compare | track (SPEC-0090, SPEC-0106): read-only, through the probes; exits 0/1/5
    (verdict), 6 (track: not there yet), 2 argument, 3 no configuration, 4 probes off or production without
    --confirm-production."""
    if args.phase == "snapshot":
        return cmd_verify_snapshot(args)
    if args.phase == "track":
        return cmd_verify_track(args)
    return cmd_verify_compare(args)


def probe_checks(local: dict) -> list:
    """doctor rows of the probes (SPEC-0088): on or off, and each adapter found or not (shutil.which only; no
    process runs). A missing adapter is ERRO with the probes on and AVISO with them off; no row without the key."""
    if not isinstance(local, dict) or "probes" not in local:  # without the key the doctor stays as it was
        return []
    try:
        probes = validate_probes(local.get("probes"))
    except AtlasError as e:
        return [("ERRO", "probes", str(e))]
    rows = [("OK", "probes", f"ligadas, {len(probes['adapters'])} adaptador(es)" if probes["enabled"]
             else "desligadas (probes.enabled: false)")]
    missing = "ERRO" if probes["enabled"] else "AVISO"
    for aid, adapter in probes["adapters"].items():
        argv = adapter_command(aid, adapter)
        if argv is None:
            rows.append((missing, f"adaptador {aid}", "sem command e a skill não traz esse adaptador"))
        elif shutil.which(argv[0]) or (Path(argv[0]).is_file() and os.access(argv[0], os.X_OK)):
            rows.append(("OK", f"adaptador {aid}", f"executável {argv[0]} encontrado"))
        else:
            rows.append((missing, f"adaptador {aid}", f"executável {argv[0]} não encontrado"))
    return rows


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
    if "remotes" in data:
        try:
            validate_remotes(data["remotes"])
        except AtlasError as e:
            problems.append(str(e))
    if "image_repositories" in data:
        try:
            validate_image_repositories(data["image_repositories"])
        except AtlasError as e:
            problems.append(str(e))
    if "environments" in data:
        try:
            validate_environments(data["environments"])
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


def unreadable_atlas(atlas) -> str:
    """Problem of an existing atlas folder that cannot be listed or entered ("" when it can, or when it is not a
    folder). Newer Pythons answer False in Path.exists()/is_file() on PermissionError, so a folder without
    permission would look empty; this check runs before them (SPEC-0046)."""
    atlas = Path(atlas)
    try:
        if not atlas.is_dir():
            return ""
        if os.access(atlas, os.R_OK | os.X_OK):
            with os.scandir(atlas) as entries:
                next(entries, None)
            return ""
    except PermissionError:
        pass
    except OSError as e:
        return f"não consegui ler {atlas}: {e.strerror or e}"
    return f"sem permissão de leitura: {atlas} — dê permissão de leitura e de listagem à pasta"


def require_readable_atlas(atlas) -> None:
    """AtlasError (exit 1) when the atlas folder exists but cannot be read (unreadable_atlas)."""
    problem = unreadable_atlas(atlas)
    if problem:
        raise AtlasError(f"pasta do atlas {problem}", 1)


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


def other_atlas_items(config: dict, chosen) -> list:
    """doctor AVISO for each other atlas of this machine whose folder no longer exists (SPEC-0079)."""
    rows = []
    for name, entry in config["entries"].items():
        atlas = entry_atlas(entry)
        if name == chosen:
            continue
        try:
            missing = not atlas or not Path(atlas).is_dir()
        except OSError:
            missing = True
        if missing:
            detail = (f"pasta não existe: {atlas or '(sem pasta)'} — tire a entrada {name} de {config['path']} ou "
                      "rode init --join")
            rows.append(("AVISO", f"atlas {name}", detail))
    return rows


def remote_tie_items(config: dict) -> list:
    """doctor AVISO when the folder's remote matches more than one atlas at the same length (the remote step is
    skipped); names only, never the remote (SPEC-0080)."""
    names = remote_matches(config)
    if len(names) < 2:
        return []
    detail = (f"o remote desta pasta casa com mais de um atlas no mesmo comprimento ({', '.join(names)}) e não "
              "escolhe nenhum — deixe o prefixo em remotes: de um só atlas ou use --atlas")
    return [("AVISO", "remote do projeto", detail)]


def invalid_remotes_items(config: dict) -> list:
    """doctor AVISO for each atlas whose `remotes:` is invalid (the remote step ignores it); the name only, never the
    item (SPEC-0080, Emenda v3 item 8)."""
    rows = []
    for name in sorted(config["entries"]):
        if usable_remotes(config["entries"][name]) is None:
            detail = ("remotes: inválido no atlas-config.yml — o passo do remote ignora este atlas; rode lint com "
                      f"--atlas {name} para ver o item")
            rows.append(("AVISO", f"remotes do atlas {name}", detail))
    return rows


def doctor_rows(config_home=None, choice=None) -> list:
    """(status, item, detail) for each item of the contract, for the chosen atlas (select_atlas) and only its
    credentials; raises AtlasError(NOT_CONFIGURED, 3) without the local layer and AtlasError (code 3) for a name or
    folder that is not configured. Several atlases without a choice = an ERRO row. Runs no process but the read-only
    `git config` of the remote step (only when an atlas declares remotes:) and never prints a variable's value."""
    path, raw = read_local(config_home)
    config = local_atlases(path, raw)
    try:
        name, selected_by = select_atlas(config, choice)
    except NoAtlasChosen as e:
        name, selected_by, no_choice = None, None, str(e)
    local = config["entries"][name] if name else {}
    rows = []
    credentials = local.get("credentials")
    try:
        validate_credentials(credentials)
        rows.append(("OK", "configuração local", str(path)))
    except AtlasError as e:
        rows.append(("ERRO", "configuração local", f"{e} ({path})"))
        credentials = {}
    try:
        access = local_access(local.get("access"))
    except AtlasError as e:  # position and reason only: never the context (SPEC-0087)
        rows.append(("ERRO", "acesso local", f"{e} ({path})"))
        access = None
    entries = config["entries"]
    rows.append(("OK", "Atlas configurados", f"{len(entries)} ({_names(entries)})"))
    rows += other_atlas_items(config, name)
    rows += invalid_remotes_items(config) + remote_tie_items(config)
    if name is None:
        rows.append(("ERRO", "atlas escolhido", no_choice))
        return rows
    rows.append(("OK", "atlas escolhido", f"{name} (escolhido por: {SELECTED_BY_TEXT[selected_by]})"))
    atlas = local.get("atlas")
    if not isinstance(atlas, str) or not atlas:
        rows.append(("ERRO", "pasta do atlas", f"atlas não definido em {path} — rode init (ou init --join)"))
        return rows + credential_checks(credentials) + probe_checks(local)
    if not Path(atlas).is_absolute():
        detail = f"caminho relativo: {atlas} — use o caminho absoluto em {path} (ou rode init --join)"
        rows.append(("ERRO", "pasta do atlas", detail))
        return rows + credential_checks(credentials) + probe_checks(local)
    try:
        if not Path(atlas).is_dir():
            rows.append(("ERRO", "pasta do atlas", f"não existe: {atlas}"))
            return rows + credential_checks(credentials) + probe_checks(local)
        problem = unreadable_atlas(atlas)
        if problem:
            rows.append(("ERRO", "pasta do atlas", problem))
            return rows + credential_checks(credentials) + probe_checks(local)
        found, shared = atlas_checks(Path(atlas))
    except OSError as e:
        rows.append(("ERRO", "pasta do atlas", f"não consegui ler {atlas}: {e.strerror or e}"))
        return rows + credential_checks(credentials) + probe_checks(local)
    rows.append(("OK", "pasta do atlas", atlas))
    rows += found + old_copy_items(Path(atlas)) + collector_checks((shared or {}).get("collectors"))
    return (rows + credential_checks(credentials) + access_map_items(Path(atlas), shared, access)
            + probe_checks(local))


def access_map_items(atlas: Path, shared, access) -> list:
    """doctor rows of the access map (SPEC-0087), from graph.json: one AVISO with the environments without a tier
    (they count as production) and, when `access` (local_access) is valid, one row per cluster: OK "contexto
    definido" (never the context) or AVISO "sem contexto local"; then one row per item of access.cloud, access.urls
    and access.databases (SPEC-0096, local_access_items)."""
    try:
        graph = read_json_file(atlas / GRAPH_FILE)
    except (AtlasError, OSError):  # an unreadable graph.json is the lint's to report
        graph = None
    rows = []
    untiered = untiered_environments(graph, shared or {})
    if untiered:
        rows.append(("AVISO", "ambientes sem marcação", f"{', '.join(untiered)} (conta como produção)"))
    if access is not None:
        for cluster in graph_clusters(graph):
            if cluster in access["clusters"]:
                rows.append(("OK", f"acesso {cluster}", "contexto definido"))
            else:
                rows.append(("AVISO", f"acesso {cluster}", "sem contexto local"))
        rows += local_access_items(graph, access)
    return rows


def _graph_names(graph, kind) -> set:
    """Ids and names of the nodes of `kind` of a graph.json (empty for an unreadable graph)."""
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    names = set()
    for node in nodes if isinstance(nodes, list) else []:
        if isinstance(node, dict) and node.get("kind") == kind and isinstance(node.get("key"), str):
            names.add(node["key"].split(":", 1)[-1])
            if isinstance(node.get("name"), str):
                names.add(node["name"])
    return names


def passfile_problem(path: str):
    """Why the passfile of access.databases is not usable, by os.stat only (the file is never opened, SPEC-0096):
    "não encontrado" (missing or not a regular file), "acessível por outros usuários" (a group or other bit, not
    checked on Windows), or None. Returns (problem, mode)."""
    try:
        info = os.stat(expand_passfile(path))
    except (OSError, ValueError):
        return "não encontrado", None
    if not stat.S_ISREG(info.st_mode):
        return "não encontrado", None
    mode = stat.S_IMODE(info.st_mode)
    if os.name != "nt" and mode & 0o077:
        return "acessível por outros usuários", mode
    return None, mode


def local_access_items(graph, access) -> list:
    """doctor rows of access.cloud, access.urls and access.databases (SPEC-0096), never a value: OK when defined (and,
    for a database, the passfile is a regular file closed to other users, checked by os.stat only), ERRO for a
    missing or open passfile, AVISO for an environment or a datastore that is not in the graph."""
    rows = []
    environments = _graph_names(graph, "environment") if graph is not None else None
    datastores = _graph_names(graph, "datastore") if graph is not None else None
    for block, label, detail in (("cloud", "nuvem", "profile definido"), ("urls", "url", "URL base definida")):
        for name in access[block]:
            if environments is not None and name not in environments:
                rows.append(("AVISO", f"acesso {label} {name}", "ambiente não está no grafo"))
            else:
                rows.append(("OK", f"acesso {label} {name}", detail))
    for name, entry in access["databases"].items():
        item = f"acesso banco {name}"
        problem, mode = passfile_problem(entry["passfile"])
        if problem == "não encontrado":
            rows.append(("ERRO", item, "arquivo de senhas não encontrado"))
        elif problem:
            rows.append(("ERRO", item, "arquivo de senhas acessível por outros usuários (use chmod 600)"))
        elif datastores is not None and name not in datastores:
            rows.append(("AVISO", item, "datastore não está no grafo"))
        else:
            checked = ("permissão não conferida no Windows" if os.name == "nt"
                       else f"arquivo com permissão {mode:04o}")
            rows.append(("OK", item, f"usuário, banco e arquivo de senhas definidos; {checked}"))
    return rows


def old_copy_items(atlas: Path) -> list:
    """doctor AVISO when the atlas still has the folder of the old name (.org-atlas/, written by the vendor of a
    previous version), with the migration step; the doctor only reads the atlas (SPEC-0070)."""
    if not (atlas / OLD_COPY_DIR).is_dir():
        return []
    item = f"pasta {OLD_COPY_DIR}/ no atlas"
    if ci_migrated(atlas):
        detail = f"cópia da skill no nome antigo, que a CI não roda mais — apague com: {REMOVE_OLD}"
        return [("AVISO", item, detail)]
    kinds = old_ci_kinds(atlas) or [kind for kind, (_, target) in CI_TARGETS.items() if (atlas / target).is_file()]
    return [("AVISO", item, f"cópia da skill no nome antigo — {migration_step((kinds or ['github|generic'])[0])}")]


def cmd_doctor(as_json, choice=None):
    rows = doctor_rows(choice=choice)
    rows[1:1] = old_config_items()
    has_error = any(status == "ERRO" for status, _, _ in rows)
    if as_json:
        checks = [{"status": s, "item": i, "detail": d} for s, i, d in rows]
        print(json.dumps({"version": ATLAS_VERSION, "ok": not has_error, "checks": checks},
                         ensure_ascii=False, indent=2))
    else:
        for status, item, detail in rows:
            print(f"{status} {item} — {detail}")
    return 1 if has_error else 0


def add_atlas_option(parser) -> None:
    """--atlas <name|folder> of every command but init (select_atlas, ADR-0021)."""
    parser.add_argument("--atlas", help=("atlas desta máquina (nome ou pasta); sem ele: ATLAS_NAME, o remote do "
                                         "projeto, o default ou o único configurado"))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="atlas.py", description="Ferramentas determinísticas da boson-atlas.")
    parser.add_argument("--version", action="version", version=f"boson-atlas {ATLAS_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init", help="cria um atlas novo ou só liga esta máquina (--join)")
    p.add_argument("--atlas", required=True, help="pasta do atlas")
    p.add_argument("--org", help="nome da organização")
    p.add_argument("--mode", help="repo | local")
    p.add_argument("--force", action="store_true", help="substitui atlas-config.yml diferente (anterior em .bak)")
    p.add_argument("--join", action="store_true", help="atlas já configurado: grava só a configuração local")
    p.add_argument("--name", help="nome do atlas nesta máquina (padrão: derivado da organização)")
    p.add_argument("--default", action="store_true", help="torna este atlas o padrão desta máquina")
    p.add_argument("--remote", action="append", metavar="PREFIXO",
                   help="prefixo host/caminho dos repositórios da organização (remotes:); pode repetir")
    p = sub.add_parser("config", help="configuração efetiva e a origem de cada valor (local | atlas | padrão)")
    p.add_argument("--json", action="store_true")
    add_atlas_option(p)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="todos os atlas desta máquina e qual seria escolhido")
    group.add_argument("--set-default", metavar="NOME", help="torna NOME o atlas padrão desta máquina")
    p = sub.add_parser("doctor", help="o que está configurado, o que funciona e o que falta")
    p.add_argument("--json", action="store_true")
    add_atlas_option(p)
    p = sub.add_parser("scan", help="roda os coletores, valida, mascara, grava snapshots/ e mostra o diff")
    p.add_argument("--only", help="ids dos coletores separados por vírgula")
    p.add_argument("--json", action="store_true")
    add_atlas_option(p)
    p = sub.add_parser("build", help="junta os snapshots no graph.json, infere relações e gera as páginas")
    p.add_argument("--json", action="store_true")
    add_atlas_option(p)
    p = sub.add_parser("lint", help="só lê e aponta o que precisa de atenção no atlas (segredos, coletores, referências)")
    p.add_argument("--only", help="regras separadas por vírgula")
    p.add_argument("--json", action="store_true")
    add_atlas_option(p)
    p = sub.add_parser("context", help="pacote só de leitura do atlas para uma tarefa (serviços, dependências, convenções)")
    p.add_argument("query", nargs="+", help="termos da tarefa")
    p.add_argument("--hops", type=int, default=1, help="passos no grafo a partir dos serviços encontrados (0..2)")
    p.add_argument("--limit", type=int, default=8, help="quantos serviços no máximo")
    p.add_argument("--max-chars", type=int, default=30000, help="tamanho máximo do pacote")
    p.add_argument("--json", action="store_true")
    add_atlas_option(p)
    p = sub.add_parser("probe", help="consulta só de leitura na infraestrutura por um adaptador declarado (desligada "
                                     "por padrão; references/probes.md)")
    p.add_argument("capability", help="capacidade (runtime, ...)")
    p.add_argument("verb", help="verbo de leitura (status, events, logs, ...)")
    p.add_argument("--service", required=True, help="id do serviço no atlas")
    p.add_argument("--env", required=True, help="ambiente do deployment")
    p.add_argument("--since", help="janela de tempo (30m, 2h; até 24h; padrão: probes.limits.since)")
    p.add_argument("--lines", help="máximo de itens (1..2000; padrão: probes.limits.lines)")
    p.add_argument("--summary", action="store_true", help="agrupa linhas de log por nível e assinatura")
    p.add_argument("--confirm-production", action="store_true",
                   help="só depois do \"sim\" da pessoa: ambiente de produção ou sem marcação")
    p.add_argument("--resource", help="recurso do grafo ligado ao deployment: <kind>:<id> (datastore, queue, topic, "
                                      "bucket)")
    p.add_argument("--commit", help="sha da mudança (7 a 40 hexadecimais), para a capacidade que declara change")
    p.add_argument("--json", action="store_true")
    add_atlas_option(p)
    p = sub.add_parser("verify", help="foto antes do merge e comparação depois do deploy, com veredito (só leitura, "
                                      "pelas probes; references/verify.md)")
    phases = p.add_subparsers(dest="phase", required=True)
    q = phases.add_parser("snapshot", help="grava a foto do serviço no ambiente num arquivo da tarefa, fora do atlas")
    q.add_argument("--service", required=True, help="id do serviço no atlas")
    q.add_argument("--env", required=True, help="ambiente dos deployments")
    q.add_argument("--out", required=True, help="arquivo da foto (fora da pasta do atlas)")
    q.add_argument("--since", help=f"janela dos eventos, logs e sinais (padrão {VERIFY_SINCE}; até 24h)")
    q.add_argument("--resource", action="append", help="restringe as dependências a este recurso ligado: "
                                                       "<kind>:<id> (queue, topic, datastore; repetível)")
    q.add_argument("--max-resources", help=f"máximo de recursos verificados (1..{VERIFY_MAX_RESOURCES_MAX}; padrão "
                                           f"{VERIFY_MAX_RESOURCES})")
    q.add_argument("--confirm-production", action="store_true",
                   help="só depois do \"sim\" da pessoa: ambiente de produção ou sem marcação")
    add_atlas_option(q)
    q = phases.add_parser("compare", help="compara o estado atual com a foto e a imagem esperada: passou, degradou "
                                          "ou inconclusivo")
    q.add_argument("--service", required=True, help="id do serviço no atlas")
    q.add_argument("--env", required=True, help="ambiente dos deployments")
    q.add_argument("--expect-image", required=True, help="imagem esperada: caminho com :<tag> e/ou @<digest>")
    q.add_argument("--baseline", help="a foto do verify snapshot (sem ela, os logs ficam não verificados)")
    q.add_argument("--window", help=f"janela dos eventos, logs e sinais (padrão {VERIFY_WINDOW}; até 24h)")
    q.add_argument("--max-new-errors", default="0", help="assinaturas de erro novas toleradas (padrão 0)")
    q.add_argument("--max-new-restarts", default="0", help="restarts novos tolerados (padrão 0)")
    q.add_argument("--resource", action="append", help="restringe as dependências a este recurso ligado: "
                                                       "<kind>:<id> (queue, topic, datastore; repetível)")
    q.add_argument("--max-resources", help=f"máximo de recursos verificados (1..{VERIFY_MAX_RESOURCES_MAX}; padrão "
                                           f"{VERIFY_MAX_RESOURCES})")
    q.add_argument("--max-new-dlq", default="0", help="mensagens novas toleradas na DLQ (padrão 0)")
    q.add_argument("--max-queue-age", help=f"idade máxima da mensagem mais antiga (padrão {VERIFY_MAX_QUEUE_AGE}; até "
                                           "24h)")
    q.add_argument("--expect-migration", action="append", help="migration que precisa estar aplicada: "
                                                               "[<datastore>=]<migration> (repetível)")
    q.add_argument("--max-signal-increase", help="piora tolerada nas métricas de erro e latência (0 a 100; padrão "
                                                 f"{VERIFY_MAX_SIGNAL_INCREASE} = 50%%)")
    q.add_argument("--confirm-production", action="store_true",
                   help="só depois do \"sim\" da pessoa: ambiente de produção ou sem marcação")
    q.add_argument("--json", action="store_true")
    add_atlas_option(q)
    q = phases.add_parser("track", help="onde está a entrega de um commit: pipeline, imagem, GitOps e rollout "
                                        "(exit 6 = ainda não chegou)")
    q.add_argument("--service", required=True, help="id do serviço no atlas")
    q.add_argument("--env", required=True, help="ambiente dos deployments")
    q.add_argument("--commit", required=True, help="sha completo do commit (40 hexadecimais)")
    q.add_argument("--expect-image", help="imagem esperada (senão, a da Application cuja tag carrega o commit)")
    q.add_argument("--confirm-production", action="store_true",
                   help="só depois do \"sim\" da pessoa: ambiente de produção ou sem marcação")
    q.add_argument("--json", action="store_true")
    add_atlas_option(q)
    p = sub.add_parser("curate", help="propõe convenções (inferred) e registra a decisão humana (confirm | reject)")
    curate = p.add_subparsers(dest="action", required=True)
    q = curate.add_parser("propose", help="cria ou atualiza conventions/<id>.md a partir dos sinais")
    q.add_argument("--json", action="store_true")
    add_atlas_option(q)
    q = curate.add_parser("list", help="convenções e o status de cada uma")
    q.add_argument("--status", choices=("inferred", "confirmed", "rejected"))
    q.add_argument("--json", action="store_true")
    add_atlas_option(q)
    for action in ("confirm", "reject"):
        q = curate.add_parser(action, help=f"{action}: decisão humana sobre uma convenção (exige --by e --via)")
        add_atlas_option(q)
        q.add_argument("id")
        q.add_argument("--by", help="quem decide")
        q.add_argument("--via", help="'PR #<n>' ou 'local'")
        if action == "reject":
            q.add_argument("--reason", help="motivo (opcional)")
    p = sub.add_parser("vendor", help="modo repo: instala no atlas o scan agendado da CI e a cópia da skill que ela roda")
    p.add_argument("--ci", required=True, choices=tuple(CI_TARGETS), help="github (GitHub Actions) | generic (script)")
    p.add_argument("--schedule", help="agenda cron (padrão: ci.schedule, senão \"0 6 * * 1\")")
    p.add_argument("--force", action="store_true", help="sobrescreve o arquivo da CI customizado")
    add_atlas_option(p)
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            return cmd_init(args)
        if args.command == "config":
            return cmd_config(args)
        if args.command == "doctor":
            return cmd_doctor(args.json, args.atlas)
        if args.command == "scan":
            return cmd_scan(args.only, args.json, args.atlas)
        if args.command == "build":
            return cmd_build(args.json, args.atlas)
        if args.command == "lint":
            return cmd_lint(args)
        if args.command == "context":
            return cmd_context(args)
        if args.command == "curate":
            return cmd_curate(args)
        if args.command == "probe":
            return cmd_probe(args)
        if args.command == "verify":
            return cmd_verify(args)
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
