#!/usr/bin/env python3
"""Deterministic tooling for the second-brain skill (stdlib only, Python 3.9+). Run with --help.

Two configuration layers (ADR-0008): the local one, per machine, in $BRAIN_CONFIG_HOME/config.yml (vault, files,
provider) and the shared one, synced with the vault, in <vault>/brain-config.yml (layout, contexts, processors).
Writes to the vault only create files or append to them (ADR-0007); every write adds a line to log.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import ntpath
import os
import posixpath
import re
import shlex
import shutil
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

BRAIN_VERSION = "2026.10.1"
SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets"
DEFAULT_SHARED_CONFIG = ASSETS_DIR / "brain-config.yml"
TEMPLATES_DIR = ASSETS_DIR / "templates"

PROVIDERS = ("google-drive", "onedrive", "icloud", "local")
LOCAL_KEYS = ("vault", "files", "provider")
LAYOUT_DIRS = ("inbox", "raw", "mocs", "templates")
LAYOUT_FILES = ("index", "log")
LAYOUT_KEYS = LAYOUT_DIRS + LAYOUT_FILES
PARA_KEYS = ("projects", "areas", "resources", "archive")
SHARED_KEYS = ("version", "language", "layout", "para", "contexts", "processors")
SHARED_VERSION = "1"
ADOPT_DIRS = ("inbox", "raw", "templates")  # --adopt never creates PARA folders the user does not have

ORIGIN_LOCAL, ORIGIN_VAULT, ORIGIN_DEFAULT = "local", "vault", "padrão"
NOT_CONFIGURED = "second-brain não configurado nesta máquina — rode init (ou init --join)"
LOCAL_HEADER = "# second-brain — configuração local desta máquina (references/config.md). Não vai para o vault.\n"
SHARED_HEADER = ("# second-brain — configuração compartilhada do vault (references/config.md).\n"
                 "# Sincroniza com o vault; só caminhos relativos ao vault.\n")
CONTEXT_NAME_RE = re.compile(r"^[\w][\w-]*$")
KEY_RE = re.compile(r"^([^\s'\"#{}\[\],:][^:]*?)\s*:(?:\s+(.*))?$")
NEEDS_QUOTES_RE = re.compile(r":\s|:$|\s#|^[\[\]{}&*!|>'\"%@`,#?:-]|^\s|\s$|\"|\\")
FLOW_SPECIAL = ",[]{}"
DOCTOR_STATUSES = ("OK", "AVISO", "ERRO")
PROVIDER_NOTES = {
    "google-drive": ("AVISO", "no iOS o Obsidian não suporta oficialmente o Google Drive; no celular, prefira o "
                              "Obsidian Sync (references/providers.md)"),
    "onedrive": ("AVISO", "o OneDrive não é suportado oficialmente no iOS e pode não funcionar bem no Android "
                          "(Dropsync/FolderSync); veja references/providers.md"),
    "icloud": ("AVISO", "recomendado no iPhone e no iPad, só entre aparelhos Apple; no Android use o Obsidian "
                        "Sync (references/providers.md)"),
    "local": ("AVISO", "pasta local não sincroniza com o celular sozinha; use o Obsidian Sync ou outro app "
                       "(references/providers.md)"),
}


class BrainError(Exception):
    """Erro previsto: a CLI imprime a mensagem e sai com o código, sem traceback."""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- yaml subset

def strip_comment(line: str) -> str:
    """Remove the ` # ...` comment outside quotes (a whole-line comment becomes empty)."""
    quote, previous = None, ""
    for i, char in enumerate(line):
        if quote:
            if char == quote:
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


def parse_yaml(text: str) -> dict:
    """YAML subset of the skill: `key: value`, nested maps by indentation, inline `{}`/`[]`, `- item` lists,
    comments and quoted strings. Same style as parse_yaml_subset of the SDD skill, but written here (ADR-0007)."""
    rows = []
    for raw in text.splitlines():
        line = strip_comment(raw)
        if line.strip():
            rows.append((len(line) - len(line.lstrip(" ")), line.strip()))
    if not rows:
        return {}
    value, _ = _parse_block(rows, 0, rows[0][0])
    return value if isinstance(value, dict) else {}


def _parse_block(rows, i: int, indent: int):
    if rows[i][1] == "-" or rows[i][1].startswith("- "):
        items = []
        while i < len(rows) and rows[i][0] == indent and (rows[i][1] == "-" or rows[i][1].startswith("- ")):
            items.append(parse_scalar(rows[i][1][1:]))
            i += 1
        return items, i
    data = {}
    while i < len(rows) and rows[i][0] >= indent:
        if rows[i][0] > indent:  # deeper line without a parent key: ignored, like parse_yaml_subset
            i += 1
            continue
        pair = KEY_RE.match(rows[i][1])
        i += 1
        if not pair:
            continue
        key, rest = pair.group(1).strip(), (pair.group(2) or "").strip()
        if rest:
            data[key] = parse_scalar(rest)
        elif i < len(rows) and (rows[i][0] > indent or (rows[i][0] == indent and rows[i][1].startswith("-"))):
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


# ---------------------------------------------------------------- paths

def _pure(path: str):
    """Pure path in the flavor of the text (C:\\... or \\\\server = Windows), with '..' collapsed."""
    if re.match(r"^([A-Za-z]:|\\\\)", path) or ("\\" in path and "/" not in path):
        return PureWindowsPath(ntpath.normpath(path))
    return PurePosixPath(posixpath.normpath(path))


def is_inside(child: str, parent: str) -> bool:
    """True when child is parent or below it, comparing path parts (not text prefixes)."""
    a, b = _pure(child), _pure(parent)
    if type(a) is not type(b):
        return False
    parts_a, parts_b = a.parts, b.parts
    if isinstance(a, PureWindowsPath):
        parts_a, parts_b = tuple(p.lower() for p in parts_a), tuple(p.lower() for p in parts_b)
    return parts_a[:len(parts_b)] == parts_b


def is_absolute(path: str) -> bool:
    return bool(re.match(r"^(/|~|[A-Za-z]:[\\/]|\\\\)", path))


def relative_folder(vault: str, folder: str) -> str:
    """Folder relative to the vault (an absolute path inside the vault is converted); outside = BrainError."""
    folder = folder.strip()
    if is_absolute(folder):
        if not is_inside(folder, vault):
            raise BrainError(f"pasta fora do vault: {folder}")
        rel = _pure(folder).relative_to(_pure(vault)).as_posix()
    else:
        rel = posixpath.normpath(folder.replace("\\", "/"))
    if rel in ("", ".") or rel == ".." or rel.startswith("../"):
        raise BrainError(f"pasta precisa ficar dentro do vault: {folder}")
    return rel


def local_config_path(config_home=None) -> Path:
    """$BRAIN_CONFIG_HOME/config.yml (default ~/.config/second-brain/config.yml); config_home wins over both."""
    if config_home:
        base = Path(config_home)
    elif os.environ.get("BRAIN_CONFIG_HOME"):
        base = Path(os.environ["BRAIN_CONFIG_HOME"])
    else:
        base = Path.home() / ".config" / "second-brain"
    return base / "config.yml"


def shared_config_path(vault: str) -> Path:
    return Path(vault) / "brain-config.yml"


def absolute(path: str) -> str:
    """Absolute path as typed (symlinks kept: each machine records its own path to the vault)."""
    return os.path.abspath(os.path.expanduser(str(path)))


# ---------------------------------------------------------------- configuration

def default_shared() -> dict:
    return parse_yaml(DEFAULT_SHARED_CONFIG.read_text(encoding="utf-8"))


def read_yaml(path: Path) -> dict:
    try:
        return parse_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise BrainError(f"não consegui ler {path}: {e}", 1) from e


def load_config(config_home=None) -> dict:
    """Effective configuration: local layer + <vault>/brain-config.yml + defaults, with the origin of each value.
    Without local configuration raises BrainError(NOT_CONFIGURED, 3)."""
    local_path = local_config_path(config_home)
    if not local_path.is_file():
        raise BrainError(NOT_CONFIGURED, 3)
    local = read_yaml(local_path)
    values, origins = {}, {}
    for key in LOCAL_KEYS:
        present = isinstance(local.get(key), str) and local.get(key) != ""
        values[key] = local[key] if present else ""
        origins[key] = ORIGIN_LOCAL if present else ORIGIN_DEFAULT
    shared = {}
    if values["vault"] and shared_config_path(values["vault"]).is_file():
        shared = read_yaml(shared_config_path(values["vault"]))
    defaults = default_shared()
    for key in SHARED_KEYS:
        if key in ("layout", "para"):
            given = shared.get(key) if isinstance(shared.get(key), dict) else {}
            values[key] = {}
            for sub in (LAYOUT_KEYS if key == "layout" else PARA_KEYS):
                found = isinstance(given.get(sub), str) and given[sub] != ""
                values[key][sub] = given[sub] if found else defaults[key][sub]
                origins[f"{key}.{sub}"] = ORIGIN_VAULT if found else ORIGIN_DEFAULT
        else:
            found = key in shared
            values[key] = shared[key] if found else defaults.get(key, {})
            origins[key] = ORIGIN_VAULT if found else ORIGIN_DEFAULT
    return {"values": values, "origins": origins}


def validate_init_args(vault: str, files: str, provider: str):
    """Contract errors of init (pure, no I/O): message or None."""
    if provider not in PROVIDERS:
        return f"provider inválido: {provider} — use um de: {', '.join(PROVIDERS)}"
    if is_inside(files, vault):
        return "files precisa ficar fora do vault"
    return None


def render_brain_config(vault: str, layout=None, contexts=None) -> str:
    """Text of the brain-config.yml that init writes: the default of assets/ plus --map and --context.
    Never holds an absolute path: folders inside the vault become relative to it."""
    data = default_shared()
    for key, folder in (layout or {}).items():
        section = "layout" if key in LAYOUT_KEYS else "para" if key in PARA_KEYS else None
        if section is None:
            raise BrainError(f"chave de --map desconhecida: {key} — use uma de: {', '.join(LAYOUT_KEYS + PARA_KEYS)}")
        data[section][key] = relative_folder(vault, folder)
    if contexts:
        data["contexts"] = {name: {"folder": relative_folder(vault, item["folder"]),
                                   "title": item.get("title") or name}
                            for name, item in contexts.items()}
    return SHARED_HEADER + dump_yaml(data)


def render_local_config(vault: str, files: str, provider: str) -> str:
    return LOCAL_HEADER + dump_yaml({"vault": vault, "files": files, "provider": provider})


def write_local_config(path: Path, text: str):
    """The local layer lives outside the vault: replaced atomically (it is the machine's pointer to the vault)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- vault writes (create or append only)

def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def write_new_file(path: Path, text: str) -> bool:
    """Create path with text; an existing file is never touched (False)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError:
        return False
    return True


def append_log(vault: Path, layout: dict, command: str, summary: str):
    """One line at the end of log.md per write in the vault: "- AAAA-MM-DD HH:MM <comando> <resumo>"."""
    log = vault / layout["log"]
    if not log.exists():
        write_new_file(log, render_log())
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(f"- {now()} {command} {summary}\n")


def render_index() -> str:
    return ("# Index\n\n"
            "<!-- brain:begin contexts -->\n<!-- brain:end contexts -->\n\n"
            "<!-- brain:begin recent -->\n<!-- brain:end recent -->\n")


def render_log() -> str:
    return ("# Log\n\n"
            "<!-- brain:begin about -->\n"
            "Uma linha por escrita do brain.py no vault, a mais nova no fim.\n"
            "<!-- brain:end about -->\n\n")


def fill_template(text: str, **fields) -> str:
    for key, value in fields.items():
        text = text.replace("{" + key + "}", value)
    return text


def moc_text(vault: Path, layout: dict, name: str, title: str) -> str:
    """MOC of a context from the vault's templates/moc.md (falls back to the skill's)."""
    template = vault / layout["templates"] / "moc.md"
    if not template.is_file():
        template = TEMPLATES_DIR / "moc.md"
    return fill_template(template.read_text(encoding="utf-8"), title=title, context=name,
                         date=dt.date.today().isoformat(), source="")


def backup_path(path: Path) -> Path:
    """brain-config.yml.bak, or .bak.1, .bak.2... so an older backup is never overwritten."""
    candidate, n = path.with_name(path.name + ".bak"), 0
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.name}.bak.{n}")
    return candidate


def create_structure(vault: Path, shared: dict, adopt: bool) -> list:
    """Create what is missing (folders, templates, index.md, log.md); returns the paths created."""
    layout, created = shared["layout"], []
    folders = [layout[key] for key in (ADOPT_DIRS if adopt else LAYOUT_DIRS)]
    if not adopt:
        folders += [shared["para"][key] for key in PARA_KEYS]
    for folder in folders:
        path = vault / folder
        if not path.exists():
            path.mkdir(parents=True)
            created.append(f"{folder}/")
    for template in sorted(TEMPLATES_DIR.glob("*.md")):
        rel = f"{layout['templates']}/{template.name}"
        if write_new_file(vault / rel, template.read_text(encoding="utf-8")):
            created.append(rel)
    for key, text in (("index", render_index()), ("log", render_log())):
        if write_new_file(vault / layout[key], text):
            created.append(layout[key])
    if not adopt:
        for name, item in shared["contexts"].items():
            created += create_context(vault, layout, name, item)
    return created


def create_context(vault: Path, layout: dict, name: str, item: dict) -> list:
    created = []
    folder = vault / item["folder"]
    if not folder.exists():
        folder.mkdir(parents=True)
        created.append(f"{item['folder']}/")
    moc = f"{layout['mocs']}/{name}.md"
    if write_new_file(vault / moc, moc_text(vault, layout, name, item.get("title") or name)):
        created.append(moc)
    return created


def add_context_text(text: str, name: str, item: dict) -> str:
    """brain-config.yml with one more context, appended inside `contexts:` so comments and order stay."""
    entry = f"  {fmt_scalar(name)}: {fmt_flow(item)}"
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^contexts\s*:(.*)$", line)
        if not m:
            continue
        rest = strip_comment(m.group(1)).strip()
        if rest == "{}":
            lines[i:i + 1] = ["contexts:", entry]
        elif rest == "":
            end = i + 1
            while end < len(lines) and (not lines[end].strip() or lines[end][0] in " #"):
                end += 1
            while end > i + 1 and not lines[end - 1].strip():
                end -= 1
            lines.insert(end, entry)
        else:
            break  # inline map with items: rewritten below
        return "\n".join(lines) + "\n"
    data = parse_yaml(text)
    contexts = data.get("contexts") if isinstance(data.get("contexts"), dict) else {}
    data["contexts"] = dict(contexts, **{name: item})
    return SHARED_HEADER + dump_yaml(data)


# ---------------------------------------------------------------- commands

def parse_pairs(values, flag: str) -> list:
    pairs = []
    for value in values or []:
        key, sep, rest = value.partition("=")
        if not sep or not key.strip() or not rest.strip():
            raise BrainError(f"{flag} espera chave=valor: {value}")
        pairs.append((key.strip(), rest.strip()))
    return pairs


def parse_contexts(values) -> dict:
    """--context nome=pasta[:título] → {nome: {folder, title}}."""
    contexts = {}
    for name, rest in parse_pairs(values, "--context"):
        folder, _, title = rest.partition(":")
        check_context_name(name)
        contexts[name] = {"folder": folder.strip(), "title": title.strip() or name}
    return contexts


def check_context_name(name: str):
    if not CONTEXT_NAME_RE.match(name):
        raise BrainError(f"nome de contexto inválido: {name} (use letras, números, '_' ou '-')")


def cmd_init(args, config_home=None) -> int:
    vault_s, files_s = absolute(args.vault), absolute(args.files)
    error = validate_init_args(vault_s, files_s, args.provider)
    if error is None and is_inside(str(Path(files_s).resolve()), str(Path(vault_s).resolve())):
        error = "files precisa ficar fora do vault"
    if error:
        raise BrainError(error)
    vault, local_path = Path(vault_s), local_config_path(config_home)
    shared_path = shared_config_path(vault_s)
    local_text = render_local_config(vault_s, files_s, args.provider)

    if args.join:
        if args.adopt or args.map or args.context or args.force:
            raise BrainError("init --join só grava a configuração local: não use --adopt, --map, --context nem --force")
        if not shared_path.is_file():
            raise BrainError("vault sem brain-config.yml — rode init")
        Path(files_s).mkdir(parents=True, exist_ok=True)
        write_local_config(local_path, local_text)
        print(f"Configuração local gravada em {local_path} — vault {vault_s}")
        print("Próximo passo: brain.py doctor")
        return 0

    if args.adopt and not vault.is_dir():
        raise BrainError(f"vault não encontrado: {vault_s}")
    layout = dict(parse_pairs(args.map, "--map"))
    rendered = render_brain_config(vault_s, layout=layout, contexts=parse_contexts(args.context))
    backup = None
    if shared_path.exists():
        if read_yaml(shared_path) == parse_yaml(rendered):
            write_local_config(local_path, local_text)
            print(f"Vault já configurado: {vault_s}")
            print(f"Configuração local gravada em {local_path}")
            return 0
        if not args.force:
            raise BrainError("brain-config.yml já existe — use --join ou --force")
        backup = backup_path(shared_path)
        shutil.copy2(shared_path, backup)

    new_vault = not vault.exists()
    vault.mkdir(parents=True, exist_ok=True)
    Path(files_s).mkdir(parents=True, exist_ok=True)
    created = create_structure(vault, parse_yaml(rendered), args.adopt)
    if backup:
        shared_path.write_text(rendered, encoding="utf-8")  # the only overwrite: --force, previous kept in .bak
    elif write_new_file(shared_path, rendered):
        created.append("brain-config.yml")
    mode = "--adopt" if args.adopt else "--force" if backup else "vault novo" if new_vault else "vault vazio"
    detail = f"{len(created)} item(ns) criado(s)" + (f", anterior em {backup.name}" if backup else "")
    append_log(vault, parse_yaml(rendered)["layout"], "init", f"{mode} — {detail}")
    write_local_config(local_path, local_text)

    print(f"{'Vault adotado' if args.adopt else 'Vault criado'} em {vault_s}")
    for item in created:
        print(f"  criado: {item}")
    if backup:
        print(f"  brain-config.yml substituído; o anterior ficou em {backup.name}")
    print(f"Configuração local gravada em {local_path}")
    print("Próximo passo: brain.py doctor")
    return 0


def cmd_config(as_json: bool, config_home=None) -> int:
    config = load_config(config_home)
    if as_json:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0
    values, origins = config["values"], config["origins"]
    print(f"second-brain {BRAIN_VERSION} — configuração local: {local_config_path(config_home)}")
    for key in ("vault", "files", "provider", "version", "language"):
        print(f"{key}: {values[key]}  ({origins[key]})")
    for section, keys in (("layout", LAYOUT_KEYS), ("para", PARA_KEYS)):
        for key in keys:
            print(f"{section}.{key}: {values[section][key]}  ({origins[f'{section}.{key}']})")
    for section in ("contexts", "processors"):
        items = values[section] if isinstance(values[section], dict) else {}
        print(f"{section}: {len(items)}  ({origins[section]})")
        for name, item in items.items():
            print(f"  {name}: {fmt_flow(item)}")
    if not values["vault"] or not shared_config_path(values["vault"]).is_file():
        print(f"aviso: brain-config.yml não encontrado no vault {values['vault']} — valores padrão", file=sys.stderr)
    return 0


def cmd_context_add(args, config_home=None) -> int:
    config = load_config(config_home)
    values = config["values"]
    vault, shared_path = Path(values["vault"]), shared_config_path(values["vault"])
    if not vault.is_dir():
        raise BrainError(f"vault não encontrado: {vault}", 1)
    if not shared_path.is_file():
        raise BrainError("vault sem brain-config.yml — rode init", 1)
    check_context_name(args.name)
    contexts = values["contexts"] if isinstance(values["contexts"], dict) else {}
    if args.name in contexts:
        raise BrainError(f"contexto já existe: {args.name}")
    item = {"folder": relative_folder(str(vault), args.folder), "title": args.title or args.name}
    text = add_context_text(shared_path.read_text(encoding="utf-8"), args.name, item)
    if parse_yaml(text).get("contexts", {}).get(args.name) != item:
        raise BrainError(f"não consegui acrescentar o contexto em {shared_path}", 1)
    shared_path.write_text(text, encoding="utf-8")
    layout = values["layout"]
    created = create_context(vault, layout, args.name, item)
    append_log(vault, layout, "context add", f"{args.name} → {item['folder']}"
               + (f" (criado: {', '.join(created)})" if created else ""))
    print(f"Contexto {args.name} → {item['folder']} ({item['title']})")
    for path in created:
        print(f"  criado: {path}")
    return 0


def doctor_items(config: dict, local_path: Path) -> list:
    """(status, item, detail) for each check; only reads the disk and shutil.which (no process runs)."""
    values, rows = config["values"], [("OK", "configuração local", str(local_path))]
    vault, files = values["vault"], values["files"]
    vault_ok = bool(vault) and Path(vault).is_dir()
    if vault_ok:
        rows.append(("OK", "vault", vault))
    else:
        rows.append(("ERRO", "vault", f"pasta não encontrada: {vault or '(sem vault na configuração local)'} — "
                                      "o app do provedor já sincronizou? (references/providers.md)"))
    if files and Path(files).is_dir():
        inside = vault and is_inside(str(Path(files).resolve()), str(Path(vault).resolve()))
        rows.append(("ERRO", "files", "precisa ficar fora do vault") if inside else ("OK", "files", files))
    else:
        rows.append(("ERRO", "files", f"pasta não encontrada: {files or '(sem files na configuração local)'}"))
    if not vault_ok:
        return rows + provider_items(values)

    shared_path = shared_config_path(vault)
    if not shared_path.is_file():
        rows.append(("ERRO", "brain-config.yml", f"ausente em {vault} — rode init (ou init --adopt)"))
        return rows + provider_items(values)
    shared = read_yaml(shared_path)
    unknown = sorted(set(shared) - set(SHARED_KEYS))
    version = str(shared.get("version", ""))
    if version != SHARED_VERSION:
        rows.append(("AVISO", "brain-config.yml", f"versão {version or 'ausente'}; esta skill usa {SHARED_VERSION}"))
    elif unknown:
        rows.append(("AVISO", "brain-config.yml", f"versão {version}; chaves desconhecidas: {', '.join(unknown)}"))
    else:
        missing = [key for key in SHARED_KEYS if key not in shared]
        rows.append(("OK", "brain-config.yml", f"versão {version}"
                     + (f"; padrão para: {', '.join(missing)}" if missing else "")))

    root = Path(vault)
    for section, keys in (("layout", LAYOUT_KEYS), ("para", PARA_KEYS)):
        for key in keys:
            rel = values[section][key]
            path = root / rel
            exists = path.is_file() if key in LAYOUT_FILES else path.is_dir()
            rows.append(("OK" if exists else "AVISO", f"{section}.{key}", rel if exists else f"não existe: {rel}"))
    contexts = values["contexts"] if isinstance(values["contexts"], dict) else {}
    if not contexts:
        rows.append(("OK", "contextos", "nenhum (crie com brain.py context add)"))
    for name, item in contexts.items():
        folder = item.get("folder", "") if isinstance(item, dict) else ""
        moc = root / values["layout"]["mocs"] / f"{name}.md"
        if not folder or not (root / folder).is_dir():
            rows.append(("AVISO", f"contexto {name}", f"pasta não existe: {folder or '(sem folder)'}"))
        else:
            rows.append(("OK" if moc.is_file() else "AVISO", f"contexto {name}",
                         folder + ("" if moc.is_file() else f"; MOC ausente: {moc.relative_to(root).as_posix()}")))
    rows += processor_items(values["processors"])
    return rows + provider_items(values)


def processor_items(processors) -> list:
    if not isinstance(processors, dict) or not processors:
        return [("OK", "processadores", "nenhum configurado")]
    rows = []
    for kind, item in processors.items():
        command = item.get("command", "") if isinstance(item, dict) else ""
        try:
            executable = shlex.split(command)[0] if command.strip() else ""
        except ValueError:
            executable = ""
        if not executable:
            rows.append(("AVISO", f"processor {kind}", "sem command"))
        elif shutil.which(executable):
            rows.append(("OK", f"processor {kind}", shutil.which(executable)))
        else:
            rows.append(("AVISO", f"processor {kind}", f"executável não encontrado no PATH: {executable}"))
    return rows


def provider_items(values: dict) -> list:
    provider = values["provider"]
    if provider not in PROVIDERS:
        return [("ERRO", "provider", f"inválido: {provider or '(vazio)'} — use um de: {', '.join(PROVIDERS)}")]
    status, note = PROVIDER_NOTES[provider]
    return [(status, f"provider {provider}", note)]


def cmd_doctor(as_json: bool, config_home=None) -> int:
    rows = doctor_items(load_config(config_home), local_config_path(config_home))
    code = 1 if any(status == "ERRO" for status, _, _ in rows) else 0
    if as_json:
        items = [{"status": s, "item": i, "detail": d} for s, i, d in rows]
        print(json.dumps({"version": BRAIN_VERSION, "items": items, "ok": code == 0}, ensure_ascii=False, indent=2))
        return code
    for status, item, detail in rows:
        print(f"{status} {item} — {detail}")
    counts = {status: sum(1 for s, _, _ in rows if s == status) for status in DOCTOR_STATUSES}
    print(f"{counts['ERRO']} erro(s), {counts['AVISO']} aviso(s)")
    return code


# ---------------------------------------------------------------- cli

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="brain.py",
        description="Ferramentas determinísticas do second-brain: onboarding do vault, configuração e diagnóstico.")
    parser.add_argument("--version", action="version", version=f"second-brain {BRAIN_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init", help="cria um vault novo, adota um existente (--adopt) ou só liga esta máquina (--join)")
    p.add_argument("--vault", required=True, help="pasta do vault (dentro da pasta sincronizada do provedor)")
    p.add_argument("--files", required=True, help="pasta dos arquivos pesados, fora do vault")
    p.add_argument("--provider", required=True, help=" | ".join(PROVIDERS))
    p.add_argument("--adopt", action="store_true", help="vault existente: nada é movido; cria só o que falta")
    p.add_argument("--map", action="append", metavar="CHAVE=PASTA", help="pasta já usada (chave de layout/para)")
    p.add_argument("--context", action="append", metavar="NOME=PASTA[:TÍTULO]", help="contexto inicial")
    p.add_argument("--force", action="store_true", help="substitui brain-config.yml diferente (anterior em .bak)")
    p.add_argument("--join", action="store_true", help="vault já configurado: grava só a configuração local")
    p = sub.add_parser("config", help="configuração efetiva e a origem de cada valor (local | vault | padrão)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("context", help="contextos do vault")
    csub = p.add_subparsers(dest="action", required=True)
    p = csub.add_parser("add", help="registra um contexto, cria a pasta e o MOC")
    p.add_argument("name")
    p.add_argument("--folder", required=True, help="pasta relativa ao vault")
    p.add_argument("--title", help="título do MOC (padrão: o nome)")
    p = sub.add_parser("doctor", help="o que está configurado, o que funciona e o que falta")
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            return cmd_init(args)
        if args.command == "config":
            return cmd_config(args.json)
        if args.command == "context":
            return cmd_context_add(args)
        if args.command == "doctor":
            return cmd_doctor(args.json)
    except BrainError as e:
        print(f"erro: {e}", file=sys.stderr)
        return e.code
    except OSError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
