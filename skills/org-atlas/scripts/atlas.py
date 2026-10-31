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
import json
import os
import re
import shutil
import sys
from pathlib import Path

ATLAS_VERSION = "2026.10.1"
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


# ---------------------------------------------------------------- collectors

def run_collector(argv):
    raise NotImplementedError("run_collector (SPEC-0033)")


def validate_collectors(collectors) -> list:
    raise NotImplementedError("validate_collectors (SPEC-0033)")


def resolve_command(command, skill, atlas) -> list:
    raise NotImplementedError("resolve_command (SPEC-0033)")


def validate_collector_output(data) -> tuple:
    raise NotImplementedError("validate_collector_output (SPEC-0033)")


def redact(value, extra_patterns=()) -> tuple:
    raise NotImplementedError("redact (SPEC-0033)")


def normalize(data) -> str:
    raise NotImplementedError("normalize (SPEC-0033)")


def diff_snapshots(old, new) -> dict:
    raise NotImplementedError("diff_snapshots (SPEC-0033)")


# ---------------------------------------------------------------- scan

def cmd_scan(only=None, as_json=False):
    raise NotImplementedError("scan (SPEC-0033)")


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
