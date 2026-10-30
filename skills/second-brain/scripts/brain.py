#!/usr/bin/env python3
"""Deterministic tooling for the second-brain skill (stdlib only, Python 3.9+). Run with --help.

Two configuration layers (ADR-0008): the local one, per machine, in $BRAIN_CONFIG_HOME/config.yml (vault, files,
provider) and the shared one, synced with the vault, in <vault>/brain-config.yml (layout, contexts, processors).
Writes to the vault only create files or append to them (ADR-0007); every write adds a line to log.md.
search, related and links only read the vault: an in-memory scan of the notes, without an index (SPEC-0018).
ingest, new-note, relate and index write only through write_new_file and the text of append_relation and
replace_region, always with a log.md line (SPEC-0019).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import ntpath
import os
import posixpath
import re
import shlex
import shutil
import sys
import unicodedata
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath

BRAIN_VERSION = "2026.10.4"
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
CONTEXT_NAME_RE = re.compile(r"^[\w][\w-]*$")
KEY_RE = re.compile(r"^([^\s'\"#{}\[\],:][^:]*?)\s*:(?:\s+(.*))?$")
NEEDS_QUOTES_RE = re.compile(r":\s|:$|\s#|^[\[\]{}&*!|>'\"%@`,#?:-]|^\s|\s$|\"|\\")
FLOW_SPECIAL = ",[]{}"
DOCTOR_STATUSES = ("OK", "AVISO", "ERRO")
BRAIN_MARKER = "<!-- brain:begin"  # generated regions of index.md and log.md: the file is the skill's
OS_METADATA = (".DS_Store", "Thumbs.db", "desktop.ini")  # not content: an "empty" vault may have them
PROVIDER_NOTES = {  # only the facts of the verified source of ADR-0008 (https://obsidian.md/help/sync-notes)
    "google-drive": ("AVISO", ("no iOS o Obsidian não suporta oficialmente o Google Drive; no celular, prefira o "
                               "Obsidian Sync (references/providers.md)")),
    "onedrive": ("AVISO", ("o OneDrive não é suportado oficialmente no iOS e pode não funcionar bem no Android "
                           "(Dropsync/FolderSync); veja references/providers.md")),
    "icloud": ("AVISO", ("recomendado no iPhone e no iPad, só entre aparelhos Apple; nos outros aparelhos, o "
                         "Obsidian Sync funciona em todos (references/providers.md)")),
    "local": ("AVISO", ("pasta local não sincroniza com o celular sozinha; o Obsidian Sync funciona em todos "
                        "(references/providers.md)")),
}

# search, related and links (SPEC-0018; scoring explained in references/search.md)
SEARCH_WEIGHTS = {"title": 3, "tags": 2, "body": 1}
RELATED_WEIGHTS = {"terms": 0.5, "tags": 0.2, "context": 0.1, "links": 0.2}
MAX_HOPS = 2  # context: link steps from the search results
TWO_HOPS = 0.5  # neighborhood of a note two links away (a direct link is 1)
SNIPPET_WIDTH, SNIPPET_LEAD = 160, 40  # snippet length and how much of it comes before the term
REASON_TERMS = 5  # shared terms listed in the "termos:" reason
FRONTMATTER_END_RE = re.compile(r"^(?:---|\.\.\.)[ \t\r]*$", re.MULTILINE)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
WIKILINK_RE = re.compile(r"!?\[\[([^\[\]\n]+?)\]\]")
HEADING_RE = re.compile(r"^#[ \t]+(.+?)[ \t#]*$")
TAG_RE = re.compile(r"(?<!\S)#([\w/-]+)")
TOKEN_RE = re.compile(r"[^\W_]+")
COMBINING_RE = re.compile(r"[̀-ͯ᪰-᫿᷀-᷿⃐-⃿︠-︯]")
STOPWORDS_TEXT = """  # Portuguese and English, already folded (no accents)
a o as os um uma uns umas de do da dos das no na nos nas num numa em ao aos pelo pela pelos pelas por para pra
com sem sob sobre entre ate apos e ou mas porem nem que se como mais menos muito muita muitos muitas pouco ja nao
sim tambem so seu sua seus suas meu minha meus minhas teu tua nosso nossa dele dela deles delas este esta estes
estas esse essa esses essas isto isso aquilo aquele aquela eu tu ele ela vos eles elas voce voces me te lhe lhes
ser foi era sao estar estao ter tem tinha ha havia quando onde qual quais quem cujo cuja la lo
the an and or but if of to in on at by for with from as is are was were be been being it its this that these
those there here i you he she we they them his her their our your my not yes do does did have has had will would
can could should so than then too very just also into over under about after before up down out what which who
whom when where why how all any each both few more most other some such only own same
"""
STOPWORDS = frozenset(STOPWORDS_TEXT.split())

# store flow: ingest, new-note, relate and index (SPEC-0019; note types in references/note-types.md)
NOTE_TYPES = ("note", "lecture", "source", "video", "document", "link", "moc", "answer")
TITLE_FORBIDDEN = frozenset('/\\:*?"<>|#^[]')  # characters a note title cannot keep in its file name
RELATIONS_HEADING = "## Relations"
RELATION_LINE_RE = re.compile(r"^[-*][ \t]+\[\[([^\[\]\n]+?)\]\][ \t]*—[ \t]*(.*?)[ \t]*$")
SECTION_END_RE = re.compile(r"^#{1,2}[ \t]")  # a "## " (or "# ") heading ends the Relations section
URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
PLACEHOLDER_LINE_RE = re.compile(r"""^([^\s:#][^:]*:[ \t]*)(["']?)\{(\w+)\}\2[ \t]*$""")
MARKER_RE = re.compile(r"\{(\w+)\}")
SLUG_MAX = 60
NAME_MAX_BYTES = 200  # UTF-8 bytes of a note's file name before ".md" (file systems allow 255)
INBOX_FILES = "inbox"  # folder of <files> for an ingest without context
RECENT_LIMIT = 20
PENDING_TEXT = "_(pending)_"


class BrainError(Exception):
    """Erro previsto: a CLI imprime a mensagem e sai com o código, sem traceback."""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- yaml subset

def strip_comment(line: str) -> str:
    """Remove the ` # ...` comment outside quotes (a whole-line comment becomes empty). Inside quotes, `\\"` of a
    double-quoted value and `''` of a single-quoted one do not close the quote."""
    quote, previous, skip = None, "", False
    for i, char in enumerate(line):
        if skip:
            skip = False
        elif quote:
            escape = '\\' if quote == '"' else "'"  # \" inside "...", '' inside '...'
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


def outside_vault(value: str) -> bool:
    """True when a vault-relative value of brain-config.yml is absolute or climbs with '..' (ADR-0008)."""
    return is_absolute(value) or ".." in value.replace("\\", "/").split("/")


def check_shared(values: dict) -> list:
    """(key, message) for each layout, para or contexts.<c>.folder value outside the vault."""
    problems = []
    for section, keys in (("layout", LAYOUT_KEYS), ("para", PARA_KEYS)):
        problems += [(f"{section}.{key}", values[section][key]) for key in keys]
    contexts = values["contexts"] if isinstance(values["contexts"], dict) else {}
    for name, item in contexts.items():
        folder = item.get("folder") if isinstance(item, dict) else None
        if isinstance(folder, str) and folder:
            problems.append((f"contexts.{name}.folder", folder))
    return [(key, f"brain-config.yml: {key} fora do vault: {value}") for key, value in problems
            if outside_vault(value)]


def read_config(config_home=None) -> dict:
    """Effective configuration without raising on the vault layer: like load_config plus `problems`, the
    (key, message) pairs of an unreadable brain-config.yml ("brain-config.yml") or values outside the vault.
    Used by doctor, which reports them and goes on; without local configuration raises BrainError(NOT_CONFIGURED, 3)."""
    local_path = local_config_path(config_home)
    if not local_path.is_file():
        raise BrainError(NOT_CONFIGURED, 3)
    local = read_yaml(local_path)
    values, origins, problems = {}, {}, []
    for key in LOCAL_KEYS:
        present = isinstance(local.get(key), str) and local.get(key) != ""
        values[key] = local[key] if present else ""
        origins[key] = ORIGIN_LOCAL if present else ORIGIN_DEFAULT
    shared = {}
    if values["vault"] and shared_config_path(values["vault"]).is_file():
        try:
            shared = read_yaml(shared_config_path(values["vault"]))
        except BrainError as e:
            problems.append(("brain-config.yml", str(e)))
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
    return {"values": values, "origins": origins, "problems": problems + check_shared(values)}


def load_config(config_home=None) -> dict:
    """Effective configuration: local layer + <vault>/brain-config.yml + defaults, with the origin of each value.
    Without local configuration raises BrainError(NOT_CONFIGURED, 3); an unreadable brain-config.yml or a layout,
    para or contexts.<c>.folder value outside the vault raises BrainError(..., 1) naming the key."""
    config = read_config(config_home)
    problems = config.pop("problems")
    if problems:
        raise BrainError(problems[0][1], 1)
    return config


def validate_init_args(vault: str, files: str, provider: str):
    """Contract errors of init (pure, no I/O): message or None."""
    if provider not in PROVIDERS:
        return f"provider inválido: {provider} — use um de: {', '.join(PROVIDERS)}"
    if is_inside(files, vault):
        return "files precisa ficar fora do vault"
    return None


def render_brain_config(vault: str, layout=None, contexts=None) -> str:
    """Text of the brain-config.yml that init writes: assets/brain-config.yml with its comments, changing only the
    values of --map and the contexts of --context. Never holds an absolute path: folders inside the vault become
    relative to it."""
    text = DEFAULT_SHARED_CONFIG.read_text(encoding="utf-8")
    expected = parse_yaml(text)
    for key, folder in (layout or {}).items():
        section = "layout" if key in LAYOUT_KEYS else "para" if key in PARA_KEYS else None
        if section is None:
            raise BrainError(f"chave de --map desconhecida: {key} — use uma de: {', '.join(LAYOUT_KEYS + PARA_KEYS)}")
        expected[section][key] = relative_folder(vault, folder)
        text = set_child_value(text, section, key, expected[section][key])
    for name, item in (contexts or {}).items():
        entry = {"folder": relative_folder(vault, item["folder"]), "title": item.get("title") or name}
        expected["contexts"] = dict(expected["contexts"] or {}, **{name: entry})
        text = add_context_text(text, name, entry)
    if parse_yaml(text) != expected:
        raise BrainError(f"não consegui gerar o brain-config.yml a partir de {DEFAULT_SHARED_CONFIG}", 1)
    return text


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


def create_file(path: Path, text: str) -> bool:
    """Create path with text (and the missing folders); an existing file is never touched (False). Used by init,
    which skips what already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError:
        return False
    return True


def write_new_file(path: Path, text: str):
    """Create path with text; an existing file is never overwritten: BrainError(code 2) "nota já existe: <path>"."""
    if not create_file(path, text):
        raise BrainError(f"nota já existe: {path}")


def append_log(vault: Path, layout: dict, command: str, summary: str):
    """One line at the end of log.md per write in the vault: "- AAAA-MM-DD HH:MM <comando> <resumo>"; the store
    commands start the summary with the path written (relative to the vault)."""
    log = vault / layout["log"]
    if not log.exists():
        create_file(log, render_log())
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
    """The {key} markers of fields replaced in a single pass: a value that holds "{date}" stays literal."""
    return MARKER_RE.sub(lambda m: str(fields[m.group(1)]) if m.group(1) in fields else m.group(0), text)


def moc_text(vault: Path, layout: dict, name: str, title: str) -> str:
    """MOC of a context from the vault's templates/moc.md (falls back to the skill's)."""
    template = vault / layout["templates"] / "moc.md"
    if not template.is_file():
        template = TEMPLATES_DIR / "moc.md"
    return render_note(template.read_text(encoding="utf-8"), title=title, context=name,
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
        if create_file(vault / rel, template.read_text(encoding="utf-8")):
            created.append(rel)
    for key, text in (("index", render_index()), ("log", render_log())):
        if create_file(vault / layout[key], text):
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
    if create_file(vault / moc, moc_text(vault, layout, name, item.get("title") or name)):
        created.append(moc)
    return created


def _top_level(lines: list, key: str):
    """Index of the top-level `key:` line, or None."""
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    return next((i for i, line in enumerate(lines) if pattern.match(line)), None)


def _children(lines: list, start: int) -> range:
    """Lines below lines[start] that belong to it: indented lines (blank ones in between included)."""
    end, last = start + 1, start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][0] in " \t"):
        end += 1
        if lines[end - 1].strip():
            last = end
    return range(start + 1, last)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _child_indent(lines: list, start: int) -> int:
    """Indentation of the entries under lines[start]; without entries, the first indented key of the file (or 2)."""
    for i in list(_children(lines, start)) + list(range(len(lines))):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith("#") and _indent(lines[i]) > 0:
            return _indent(lines[i])
    return 2


def _join(lines: list, text: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    return newline.join(lines) + newline


def set_child_value(text: str, section: str, key: str, value: str) -> str:
    """Text with `section.key` set to value on its own line; the comment of the line and every other line stay."""
    lines = text.splitlines()
    start = _top_level(lines, section)
    if start is not None:
        for i in _children(lines, start):
            content = strip_comment(lines[i])
            pair = re.match(r"^(\s+)([^\s:#][^:]*?)(\s*:\s*)(.*)$", content)
            if pair and pair.group(2) == key and len(pair.group(1)) == _child_indent(lines, start):
                lines[i] = pair.group(1) + key + pair.group(3) + fmt_scalar(value) + lines[i][len(content):]
                return _join(lines, text)
    raise BrainError(f"{section}.{key} não está em forma de bloco no modelo {DEFAULT_SHARED_CONFIG}", 1)


def add_context_text(text: str, name: str, item: dict) -> str:
    """brain-config.yml with one more context: only inserts a line inside `contexts:`, with the indentation of the
    existing entries; comments, order and every other line stay. Inline contexts with items = BrainError (exit 2)."""
    lines = text.splitlines()
    start = _top_level(lines, "contexts")
    if start is None:
        lines += ["contexts:", f"{' ' * _child_indent(lines, len(lines) - 1)}{fmt_scalar(name)}: {fmt_flow(item)}"]
        return _join(lines, text)
    content = strip_comment(lines[start])
    rest = content.split(":", 1)[1].strip()
    if rest == "{}":  # empty inline map becomes a block; the comment keeps its column
        tail = lines[start][len(content):]
        lines[start] = content.replace("{}", "  ", 1) + tail if tail.strip() else content.replace("{}", "").rstrip()
    elif rest:
        raise BrainError("contexts está em forma inline — converta para bloco")
    lines.insert(_children(lines, start).stop, f"{' ' * _child_indent(lines, start)}{fmt_scalar(name)}: {fmt_flow(item)}")
    return _join(lines, text)


# ---------------------------------------------------------------- notes, links and search (read only)

def fold(text: str) -> str:
    """Lowercase without accents (NFKD minus combining marks): "Integração" -> "integracao"."""
    return COMBINING_RE.sub("", unicodedata.normalize("NFKD", text.lower()))


def tokenize(text: str) -> list:
    """Terms of a text: folded words (letters and digits) that are not Portuguese or English stopwords."""
    return [term for term in TOKEN_RE.findall(fold(text)) if term not in STOPWORDS]


def unique(items) -> list:
    return list(dict.fromkeys(items))


class Note:
    """A note of the vault as parse_note reads it (path relative to the vault, with "/"). `terms` counts every term
    (title, tags and body: the vector of related); title_terms, tag_terms and body_terms are the fields of search;
    `text` is the whole note (frontmatter included), the content of the context package. A plain class, not a
    dataclass: the tests load brain.py by path, outside sys.modules."""
    __slots__ = ("body", "body_terms", "context", "frontmatter", "links", "path", "tag_terms", "tags", "terms",
                 "text", "title", "title_terms", "warnings")

    def __init__(self, **fields):
        for name in self.__slots__:
            setattr(self, name, fields.get(name))

    def __repr__(self) -> str:
        return f"Note({self.path!r}, title={self.title!r})"

    @property
    def note_type(self) -> str:
        value = self.frontmatter.get("type")
        return value.strip() if isinstance(value, str) else ""


def read_frontmatter(text: str):
    """(frontmatter, body, problem): YAML between a first line "---" and the next "---" (or "..."). Invalid or
    unclosed YAML gives {} and the problem, never an exception."""
    first, sep, rest = text.partition("\n")
    if first.rstrip() != "---" or not sep:
        return {}, text, None
    end = FRONTMATTER_END_RE.search(rest)
    if not end:
        return {}, text, "frontmatter sem fechamento"
    body = rest[end.end():]
    try:
        data = parse_yaml(rest[:end.start()])
    except (ValueError, IndexError, TypeError) as e:
        return {}, body, f"frontmatter inválido ({e})"
    return data, body, None


def prose(body: str) -> str:
    """Body without fenced code blocks (``` or ~~~) and inline code: where tags, links and headings count."""
    lines, fence = [], None
    for line in body.splitlines():
        m = FENCE_RE.match(line)
        if m:
            if fence is None:
                fence = m.group(1)
            elif m.group(1) == fence:
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return INLINE_CODE_RE.sub(" ", "\n".join(lines))


def link_target(raw: str) -> str:
    """[[alvo#seção|apelido]] -> "alvo" (the "\\|" of links inside tables included)."""
    return raw.split("|", 1)[0].split("#", 1)[0].rstrip("\\").strip()


def frontmatter_tags(value) -> list:
    """frontmatter.tags as a list or as a string ("a, b" or "a b"), without "#", lowercased."""
    if isinstance(value, str):
        value = re.split(r"[,\s]+", value)
    if not isinstance(value, list):
        return []
    tags = (str(item).strip().lstrip("#").lower() for item in value)
    return [tag for tag in tags if tag]


def text_tags(text: str) -> list:
    """#tags of a text (a heading "# Título" is not a tag, nor a number like "#1")."""
    return [tag.lower() for tag in TAG_RE.findall(text) if not tag.isdigit()]


def note_context(path: str, frontmatter: dict, contexts) -> str:
    """frontmatter.context, else the context whose folder holds the note (the deepest one), else ""."""
    given = frontmatter.get("context")
    if isinstance(given, str) and given.strip():
        return given.strip()
    parts, best, depth = path.split("/"), "", 0
    for name, item in (contexts if isinstance(contexts, dict) else {}).items():
        folder = item.get("folder") if isinstance(item, dict) else None
        if not isinstance(folder, str) or not folder.strip():
            continue
        folder_parts = posixpath.normpath(folder.strip().replace("\\", "/")).split("/")
        if len(parts) > len(folder_parts) > depth and parts[:len(folder_parts)] == folder_parts:
            best, depth = name, len(folder_parts)
    return best


def note_title(path: str, frontmatter: dict, plain: str) -> str:
    """frontmatter.title, else the first "# Título" of the prose, else the file name without .md."""
    title = frontmatter.get("title")
    if not isinstance(title, str) or not title.strip():
        heading = next((m.group(1) for m in map(HEADING_RE.match, plain.splitlines()) if m), "")
        title = heading or posixpath.splitext(posixpath.basename(path))[0]
    return title.strip()


def parse_note(path: str, text: str, contexts=None) -> Note:
    """Note of `text` (already decoded) at `path` (relative to the vault), without I/O. contexts is the
    values["contexts"] of load_config(); an invalid frontmatter becomes {} and a warning, never an exception."""
    frontmatter, body, problem = read_frontmatter(text)
    plain = prose(body)
    title = note_title(path, frontmatter, plain)
    links = unique(target for target in (link_target(m) for m in WIKILINK_RE.findall(plain)) if target)
    tags = unique(frontmatter_tags(frontmatter.get("tags")) + text_tags(WIKILINK_RE.sub(" ", plain)))
    title_terms, tag_terms, body_terms = tokenize(title), tokenize(" ".join(tags)), tokenize(body)
    return Note(path=path, title=title, frontmatter=frontmatter, tags=tags, links=links,
                context=note_context(path, frontmatter, contexts), terms=Counter(title_terms + tag_terms + body_terms),
                body=body, text=text, title_terms=Counter(title_terms), tag_terms=Counter(tag_terms),
                body_terms=Counter(body_terms), warnings=[f"{path}: {problem} — lida sem frontmatter"] if problem else [])


def _link_key(target: str) -> str:
    key = target.strip().replace("\\", "/")
    while key.startswith(("./", "/")):
        key = key[1:] if key.startswith("/") else key[2:]
    if key.lower().endswith(".md"):
        key = key[:-3]
    return key.lower()


class LinkIndex:
    """Obsidian-like resolution of [[links]] over the note paths, with dicts built once (one lookup per link)."""

    def __init__(self, paths):
        self.by_path, self.by_name = {}, {}
        for path in sorted(set(paths), key=lambda p: (len(p), p)):  # shortest path first: it wins the ties
            key = _link_key(path)
            self.by_path.setdefault(key, path)
            self.by_name.setdefault(key.rsplit("/", 1)[-1], []).append(path)

    def resolve(self, target: str):
        """Path of the note or None (broken). With "/" = path relative to the vault (with or without .md, or its
        ending); without = file name, ignoring case; several candidates = the shortest path."""
        key = _link_key(target)
        if not key:
            return None
        if "/" not in key:
            found = self.by_name.get(key)
            return found[0] if found else None
        if key in self.by_path:
            return self.by_path[key]
        suffix = "/" + key
        return next((p for p in self.by_name.get(key.rsplit("/", 1)[-1], ()) if _link_key(p).endswith(suffix)), None)


def resolve_link(target: str, paths):
    """Path of the note a link points to, or None (broken); paths = the Note.path of the vault or a LinkIndex."""
    index = paths if isinstance(paths, LinkIndex) else LinkIndex(paths)
    return index.resolve(target)


def ignored_dir(rel: str, templates: str) -> bool:
    """.obsidian/, .trash/ (and any other hidden folder, which Obsidian does not index) and layout.templates."""
    return posixpath.basename(rel).startswith(".") or rel == templates


def read_note(path: Path, rel: str, contexts) -> Note:
    """Note on disk: a file that is not UTF-8 is read with errors="replace" and gets a warning."""
    problem = None
    try:
        data = path.read_bytes()
    except OSError as e:
        data, problem = b"", f"não consegui ler ({e.strerror or e})"
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text, problem = data.decode("utf-8", errors="replace"), "não é UTF-8 — lida com caracteres substituídos"
    note = parse_note(rel, text, contexts)
    if problem:
        note.warnings.insert(0, f"{rel}: {problem}")
    return note


def vault_dir(values: dict) -> Path:
    """The configured vault folder; missing = BrainError (exit 1)."""
    vault = Path(values["vault"]) if values["vault"] else None
    if vault is None or not vault.is_dir():
        raise BrainError(f"vault não encontrado: {values['vault'] or '(sem vault na configuração local)'}", 1)
    return vault


def walk_notes(values: dict):
    """(absolute path, path relative to the vault) of every .md note, in path order, except .obsidian/, .trash/
    and the layout.templates folder."""
    vault = vault_dir(values)
    templates = posixpath.normpath(str(values["layout"]["templates"]).replace("\\", "/"))
    for root, dirs, files in os.walk(vault):
        base = Path(root).relative_to(vault).as_posix()
        prefix = "" if base == "." else base + "/"
        dirs[:] = sorted(d for d in dirs if not ignored_dir(prefix + d, templates))
        for name in sorted(files):
            if name.lower().endswith(".md"):
                yield Path(root) / name, prefix + name


def scan_vault(config: dict) -> list:
    """Every .md note of the vault of load_config(), in path order, except .obsidian/, .trash/ and the
    layout.templates folder. Only reads; the problems of each note are in Note.warnings."""
    values = config["values"]
    contexts = values["contexts"] if isinstance(values["contexts"], dict) else {}
    return [read_note(path, rel, contexts) for path, rel in walk_notes(values)]


def inverse_frequency(df: int, total: int) -> float:
    return math.log(1 + total / df) if df else 0.0


def first_match(text: str, terms) -> int:
    """Index in text of the first term (compared folded), or -1."""
    folded, origin = [], []
    for i, char in enumerate(text):
        piece = char.lower() if char < "\x80" else fold(char)
        folded.append(piece)
        origin.extend([i] * len(piece))
    joined = "".join(folded)
    best = -1
    for term in terms:
        m = re.search(rf"(?<![^\W_]){re.escape(term)}(?![^\W_])", joined)
        if m and (best < 0 or origin[m.start()] < best):
            best = origin[m.start()]
    return best


def make_snippet(note: Note, terms) -> str:
    """Up to SNIPPET_WIDTH characters of the body around the first query term (the start of the body without it)."""
    flat = " ".join(note.body.split()) or note.title
    pos = max(first_match(flat, terms), 0)
    start = max(0, min(pos - SNIPPET_LEAD, len(flat) - SNIPPET_WIDTH))
    piece = flat[start:start + SNIPPET_WIDTH]
    if start > 0:
        piece = "…" + piece[1:]
    if start + SNIPPET_WIDTH < len(flat):
        piece = piece[:-1] + "…"
    return piece


def search(notes: list, query: str, context=None, note_type=None, tag=None, limit=10) -> list:
    """Notes of the query by score: sum per query term of tf * idf, weighting title 3, tags 2 and body 1.
    Only score > 0, descending; filters by context, frontmatter.type and tag."""
    terms = unique(tokenize(query))
    if not terms:
        return []
    idf = {term: inverse_frequency(sum(1 for n in notes if term in n.terms), len(notes)) for term in terms}
    wanted_type = fold(note_type.strip()) if note_type else None
    wanted_tag = tag.strip().lstrip("#").lower() if tag else None
    scored = []
    for note in notes:
        if ((context and note.context != context) or (wanted_type and fold(note.note_type) != wanted_type)
                or (wanted_tag and wanted_tag not in note.tags)):
            continue
        score = sum(idf[t] * (SEARCH_WEIGHTS["title"] * note.title_terms[t] + SEARCH_WEIGHTS["tags"] * note.tag_terms[t]
                              + SEARCH_WEIGHTS["body"] * note.body_terms[t]) for t in terms if t in note.terms)
        if score > 0:
            scored.append((score, note))
    scored.sort(key=lambda item: (-item[0], item[1].path))
    return [{"path": note.path, "title": note.title, "score": round(score, 3), "snippet": make_snippet(note, terms),
             "context": note.context or None, "type": note.note_type or None}
            for score, note in scored[:limit]]


def link_graph(notes: list, index: LinkIndex) -> dict:
    """Undirected neighborhood of each note: the notes it links to and the ones that link to it."""
    graph = {note.path: set() for note in notes}
    for note in notes:
        for target in note.links:
            dest = index.resolve(target)
            if dest and dest != note.path:
                graph[note.path].add(dest)
                graph[dest].add(note.path)
    return graph


def related(notes: list, note=None, text=None, limit=10) -> list:
    """Notes like `note` (a Note.path) or like a free `text`, by 0.5 * TF-IDF cosine + 0.2 * tag Jaccard
    + 0.1 * same context + 0.2 * neighborhood (1 direct link, 0.5 two hops). Excludes the note itself; descending;
    each result says why (reasons)."""
    index = LinkIndex(n.path for n in notes)
    graph = link_graph(notes, index)
    if note is not None:
        ref = next((n for n in notes if n.path == note), None)
        if ref is None:
            raise BrainError(f"nota não encontrada: {note}")
        direct = graph[ref.path]
    else:
        ref = parse_note("", text or "")
        direct = {index.resolve(target) for target in ref.links} - {None}
    two_hops = set().union(*(graph[p] for p in direct)) - direct - {ref.path} if direct else set()

    df = Counter()
    for n in notes:
        df.update(n.terms.keys())
    idf = {term: inverse_frequency(count, len(notes)) for term, count in df.items()}
    ref_vector = {t: tf * idf[t] for t, tf in ref.terms.items() if t in idf}
    ref_norm = math.sqrt(sum(w * w for w in ref_vector.values()))
    ref_tags = set(ref.tags)

    scored = []
    for n in notes:
        if n.path == ref.path:
            continue
        shared = ref_vector.keys() & n.terms.keys() if ref_norm else set()
        contributions = {t: ref_vector[t] * n.terms[t] * idf[t] for t in shared}
        cosine = 0.0
        if contributions:
            norm = math.sqrt(sum((tf * idf[t]) ** 2 for t, tf in n.terms.items()))
            cosine = sum(contributions.values()) / (ref_norm * norm)
        common_tags = [tag for tag in ref.tags if tag in n.tags]
        jaccard = len(common_tags) / len(ref_tags | set(n.tags)) if common_tags else 0.0
        same_context = bool(ref.context) and n.context == ref.context
        neighborhood = 1.0 if n.path in direct else TWO_HOPS if n.path in two_hops else 0.0
        score = (RELATED_WEIGHTS["terms"] * cosine + RELATED_WEIGHTS["tags"] * jaccard
                 + RELATED_WEIGHTS["context"] * same_context + RELATED_WEIGHTS["links"] * neighborhood)
        if score > 0:
            scored.append((score, n, common_tags, same_context, neighborhood, contributions))
    scored.sort(key=lambda item: (-item[0], item[1].path))
    return [{"path": n.path, "title": n.title, "score": round(score, 4),
             "reasons": related_reasons(common_tags, same_context, neighborhood, contributions)}
            for score, n, common_tags, same_context, neighborhood, contributions in scored[:limit]]


def related_reasons(common_tags, same_context, neighborhood, contributions) -> list:
    reasons = []
    if common_tags:
        reasons.append("tags: " + ", ".join(common_tags))
    if same_context:
        reasons.append("mesmo contexto")
    if neighborhood:
        reasons.append("link direto" if neighborhood == 1.0 else "link a dois passos")
    if contributions:
        top = sorted(contributions, key=lambda t: (-contributions[t], t))[:REASON_TERMS]
        reasons.append("termos: " + ", ".join(top))
    return reasons


def note_links(notes: list, path: str, index: LinkIndex) -> dict:
    """Outgoing links of the note at `path` (resolved or None), its backlinks and its broken targets."""
    note = next(n for n in notes if n.path == path)
    outgoing = [{"target": target, "path": index.resolve(target)} for target in note.links]
    backlinks = sorted(n.path for n in notes
                       if n.path != path and any(index.resolve(target) == path for target in n.links))
    return {"outgoing": outgoing, "backlinks": backlinks,
            "broken": [item["target"] for item in outgoing if item["path"] is None]}


# ---------------------------------------------------------------- query: context package (pure)

def moc_path(context: str, values=None) -> str:
    """Path of the MOC of a context: <layout.mocs>/<context>.md ("mocs" when values is None)."""
    mocs = values["layout"]["mocs"] if values else "mocs"
    return f"{posixpath.normpath(str(mocs).replace(chr(92), '/'))}/{context}.md"


def neighbors(seeds: list, graph: dict, hops: int) -> dict:
    """Distance (1..hops) of every note reached from the seeds by the undirected link graph (breadth first)."""
    seen, frontier, found = set(seeds), list(seeds), {}
    for distance in range(1, hops + 1):
        reached = []
        for path in frontier:
            for nxt in graph.get(path, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    found[nxt] = distance
                    reached.append(nxt)
        frontier = reached
    return found


def build_context(notes: list, query: str, context=None, hops=1, limit=8, max_chars=40000, values=None) -> dict:
    """Package of notes that answer the query: the MOC of `context` (when given), the search results by score and
    their link neighbors (outgoing links and backlinks) up to `hops` steps, by distance and title; no note repeats.
    Whole notes while the sum of their content fits max_chars; from the first that does not fit on, the notes go to
    "omitted" (path, title, reason). "broken" lists the broken links of the notes in the package. Nothing found by
    the search = empty package (no MOC alone)."""
    by_path = {note.path: note for note in notes}
    index = LinkIndex(by_path)
    results = search(notes, query, context=context, limit=limit)
    moc = moc_path(context, values) if context and results else None
    picked = [(moc, "moc")] if moc in by_path else []  # (path, reason) in the contract order
    seeds = [r["path"] for r in results if r["path"] != moc]
    picked += [(r["path"], f"search:{r['score']}") for r in results if r["path"] != moc]
    found = neighbors(seeds, link_graph(notes, index), hops) if seeds and hops > 0 else {}
    found.pop(moc, None)
    picked += [(path, f"link:{distance}")
               for path, distance in sorted(found.items(), key=lambda item: (item[1], by_path[item[0]].title.lower(),
                                                                              item[0]))]
    package, omitted, broken, size = [], [], [], 0
    for path, reason in picked:
        note = by_path[path]
        content = note.text or ""
        if not omitted and size + len(content) <= max_chars:
            size += len(content)
            package.append({"path": path, "title": note.title, "reason": reason, "content": content})
        else:
            omitted.append({"path": path, "title": note.title, "reason": reason})
        broken += [{"note": path, "target": target} for target in note.links if index.resolve(target) is None]
    return {"query": query, "notes": package, "omitted": omitted, "broken": broken}


# ---------------------------------------------------------------- store: note paths, relations, regions (pure)

def inside_vault(folder, what: str) -> str:
    """Folder relative to the vault, with "/" ("" = the vault root); absolute or climbing out with ".." =
    BrainError(code 2) "<what> fora do vault"."""
    text = str(folder or "").strip().replace("\\", "/")
    rel = posixpath.normpath(text) if text else "."
    if is_absolute(text) or rel == ".." or rel.startswith("../"):
        raise BrainError(f"{what} fora do vault: {folder}")
    return "" if rel == "." else rel


def check_context(context: str, values: dict) -> dict:
    """The contexts.<context> item; unknown context = BrainError(code 2) with the valid ones."""
    contexts = values["contexts"] if isinstance(values["contexts"], dict) else {}
    if context not in contexts:
        valid = ", ".join(contexts) if contexts else "nenhum configurado (crie com brain.py context add)"
        raise BrainError(f"contexto inexistente: {context} — contextos válidos: {valid}")
    check_context_name(context)  # a hand-edited brain-config.yml may hold a name like "../x"
    item = contexts[context]
    return item if isinstance(item, dict) else {}


def sanitize_title(title: str) -> str:
    """File name of a title: each forbidden character (and control character) becomes a space, repeated spaces
    become one and the ends lose spaces and dots ("Aula 1: Limites/Derivadas" -> "Aula 1 Limites Derivadas").
    Longer than NAME_MAX_BYTES in UTF-8 = cut there, never in the middle of a character."""
    name = "".join(" " if char in TITLE_FORBIDDEN or char < " " else char for char in title)
    name = " ".join(name.split()).strip(" .")
    name = name.encode("utf-8")[:NAME_MAX_BYTES].decode("utf-8", errors="ignore").strip(" .")
    if not name:
        raise BrainError(f"título sem caracteres válidos para o nome do arquivo: {title!r}")
    return name


def note_path(title: str, context, values: dict) -> str:
    """Path of a new note, relative to the vault: <contexts.<c>.folder or para.resources>/<sanitized title>.md.
    No I/O; a folder outside the vault or an unknown context = BrainError(code 2)."""
    if context:
        folder = inside_vault(check_context(context, values).get("folder"), f"contexts.{context}.folder")
    else:
        folder = inside_vault(values["para"]["resources"], "para.resources")
    return posixpath.join(folder, sanitize_title(title) + ".md")


def relation_line(target: str, why: str) -> str:
    return f"- [[{target}]] — {why}"


def newline_of(text: str) -> str:
    """The line ending of a text: "\\r\\n" when it has one, else "\\n"."""
    return "\r\n" if "\r\n" in text else "\n"


def same_relation(line: str, target: str, why: str) -> bool:
    """True when line is "- [[X]] — why" and X resolves like target (alias and section ignored, any case)."""
    m = RELATION_LINE_RE.match(line.strip())
    return bool(m) and (_link_key(link_target(m.group(1))) == _link_key(link_target(target))
                        and " ".join(m.group(2).split()) == " ".join(why.split()))


def append_relation(text: str, target: str, why: str) -> str:
    """Text with "- [[target]] — why" at the end of the "## Relations" section (before the next "## " heading or
    the end of the file); without the section, it is created at the end. A line of the section already linking to
    the same note (alias or section aside, any case) with the same reason = the text unchanged. The inserted lines
    use the text's line ending. Pure; the rest of the text never changes."""
    line, nl = relation_line(target, why), newline_of(text)
    lines = text.splitlines(keepends=True)
    start = next((i for i, item in enumerate(lines) if item.rstrip() == RELATIONS_HEADING), None)
    if start is None:
        base = text.rstrip("\r\n")
        return f"{base}{nl}{nl}{RELATIONS_HEADING}{nl}{nl}{line}{nl}" if base else f"{RELATIONS_HEADING}{nl}{nl}{line}{nl}"
    end = next((i for i in range(start + 1, len(lines)) if SECTION_END_RE.match(lines[i])), len(lines))
    if any(same_relation(item, target, why) for item in lines[start + 1:end]):
        return text
    last = max(i for i in range(start, end) if lines[i].strip())
    if not lines[last].endswith("\n"):
        lines[last] += nl
    lines.insert(last + 1, (nl if last == start else "") + line + nl)
    return "".join(lines)


def region_markers(name: str):
    return f"<!-- brain:begin {name} -->", f"<!-- brain:end {name} -->"


def replace_region(text: str, name: str, content: str) -> str:
    """Text with only what is between "<!-- brain:begin <name> -->" and "<!-- brain:end <name> -->" replaced by
    content; without the region, it is appended at the end with both markers. Exactly one begin before exactly one
    end, or neither; anything else (orphan begin or end, end before begin, duplicated region) = BrainError (code 2)
    naming the region, so nothing of the user is ever swallowed. Uses the text's line ending. Pure; the text
    outside the region (other regions included) never changes."""
    begin, end = region_markers(name)
    nl = newline_of(text)
    body = nl.join(content.strip("\n").split("\n")) if content.strip("\n") else ""
    block = f"{begin}{nl}{body}{nl}{end}" if body else f"{begin}{nl}{end}"
    begins, ends = text.count(begin), text.count(end)
    if begins == 0 and ends == 0:
        separator = "" if not text else nl if text.endswith("\n") else nl + nl
        return text + separator + block + nl
    start, stop = text.find(begin), text.find(end)
    if begins != 1 or ends != 1 or stop < start + len(begin):
        raise BrainError(f"região {name} com marcadores inválidos ({begins} begin, {ends} end"
                         + (", end antes do begin" if begins == ends == 1 else "")
                         + f") — corrija {begin} … {end} à mão; nada foi alterado")
    return text[:start] + block + text[stop + len(end):]


def slugify(title: str) -> str:
    """Lowercase ASCII slug of a title for the name of a source note ("Aula 1: Limites" -> "aula-1-limites")."""
    slug = re.sub(r"[^a-z0-9]+", "-", fold(title)).strip("-")
    return slug[:SLUG_MAX].strip("-") or "fonte"


def render_note(template: str, tags=(), **fields) -> str:
    """Note from a template: the {title}, {date}, {context} and {source} markers filled. In the frontmatter a line
    whose value is only a marker gets a YAML-safe value (a quoted marker stays quoted) or disappears when the value
    is empty (absent key); `tags` are merged into the tags key."""
    first, sep, rest = template.partition("\n")
    end = FRONTMATTER_END_RE.search(rest) if first.rstrip() == "---" and sep else None
    if end is None:
        return fill_template(template, **fields)
    lines, has_tags = [], False
    for line in rest[:end.start()].splitlines():
        m = PLACEHOLDER_LINE_RE.match(line)
        if m and m.group(3) in fields:
            value = fields[m.group(3)]
            if value:
                lines.append(m.group(1) + (json.dumps(value, ensure_ascii=False) if m.group(2) else fmt_scalar(value)))
            continue
        line = fill_template(line, **fields)
        if tags and re.match(r"^tags\s*:", line):
            has_tags = True
            given = frontmatter_tags(parse_scalar(line.split(":", 1)[1]))
            line = f"tags: {fmt_flow(unique(given + list(tags)))}"
        lines.append(line)
    if tags and not has_tags:
        lines.append(f"tags: {fmt_flow(list(tags))}")
    head = first + "\n" + "".join(f"{line}\n" for line in lines)
    return head + fill_template(rest[end.start():], **fields)


def render_source_note(title: str, date: str, context, file_rel, url, extracted: str) -> str:
    """Source note of ingest: frontmatter type: source, title, context, created, tags, source_url or files, and
    the extracted text (or _(pending)_) under "## Extracted text"."""
    frontmatter = {"type": "source", "title": title}
    if context:
        frontmatter["context"] = context
    frontmatter.update(created=date, tags=[])
    if url:
        frontmatter["source_url"] = url
    else:
        frontmatter["files"] = [file_rel]
    text = extracted.strip("\n").rstrip() or PENDING_TEXT
    return (f"---\n{dump_yaml(frontmatter)}---\n\n# {title}\n\n## Summary\n\n## Extracted text\n\n{text}\n\n"
            f"{RELATIONS_HEADING}\n")


def link_name(path: str, index: LinkIndex) -> str:
    """How a [[link]] names the note: the file name without .md, or the path without .md when the name alone would
    resolve to another note."""
    stem = posixpath.splitext(posixpath.basename(path))[0]
    return stem if index.resolve(stem) == path else posixpath.splitext(path)[0]


def wikilink(path: str, title: str, index: LinkIndex) -> str:
    target = link_name(path, index)
    if target == title or any(char in title for char in "[]|"):
        return f"[[{target}]]"
    return f"[[{target}|{title}]]"


class IndexEntry:
    """What index needs of a note: path, title, type, context and created (AAAA-MM-DD or "")."""
    __slots__ = ("context", "created", "note_type", "path", "title")

    def __init__(self, path, title, note_type, context, created):
        self.path, self.title, self.note_type, self.context, self.created = path, title, note_type, context, created


def index_entry(rel: str, text: str, contexts) -> IndexEntry:
    """IndexEntry of a note (only the frontmatter and the title are read: no terms, so index stays fast)."""
    frontmatter, body, _ = read_frontmatter(text)
    title = note_title(rel, frontmatter, "" if isinstance(frontmatter.get("title"), str) else prose(body))
    note_type = frontmatter.get("type")
    return IndexEntry(rel, title, note_type.strip() if isinstance(note_type, str) else "",
                      note_context(rel, frontmatter, contexts), created_date(frontmatter.get("created")))


def created_date(value) -> str:
    """AAAA-MM-DD of frontmatter.created when it starts with a real date (2026-13-45 is not one), else ""."""
    m = DATE_PREFIX_RE.match(str(value or "").strip())
    if not m:
        return ""
    try:
        return dt.date.fromisoformat(m.group(1)).isoformat()
    except ValueError:
        return ""


def moc_notes_content(entries: list, index: LinkIndex) -> str:
    """Region "notes" of a MOC: a "### <type>" label per type (v1 order, then the others), the notes of the group
    as "- [[Título]]" ordered by title."""
    groups = {}
    for entry in entries:
        groups.setdefault(entry.note_type or "(sem type)", []).append(entry)
    order = [t for t in NOTE_TYPES if t in groups] + sorted(t for t in groups if t not in NOTE_TYPES)
    lines = []
    for note_type in order:
        lines += [f"### {note_type}", ""]
        for entry in sorted(groups[note_type], key=lambda e: (fold(e.title), e.title, e.path)):
            lines.append(f"- {wikilink(entry.path, entry.title, index)}")
        lines.append("")
    return "\n".join(lines).strip("\n") or "_(nenhuma nota)_"


def index_contexts_content(contexts: dict, counts: dict, mocs: str) -> str:
    """Region "contexts" of index.md: one line per context with the link to its MOC and the number of notes."""
    lines = []
    for name, item in contexts.items():
        title = (item.get("title") if isinstance(item, dict) else None) or name
        lines.append(f"- [[{posixpath.join(mocs, name)}|{title}]] — {counts.get(name, 0)} nota(s)")
    return "\n".join(lines) or "_(nenhum contexto)_"


def index_recent_content(entries: list, index: LinkIndex) -> str:
    """Region "recent" of index.md: the RECENT_LIMIT notes with the newest created, newest first."""
    dated = sorted((e for e in entries if e.created), key=lambda e: e.path)
    dated.sort(key=lambda e: e.created, reverse=True)
    lines = [f"- {wikilink(e.path, e.title, index)} — {e.created}" for e in dated[:RECENT_LIMIT]]
    return "\n".join(lines) or "_(nenhuma nota com created)_"


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


def check_user_files(vault: Path, layout: dict):
    """index.md and log.md of the user (without the brain:begin markers) are never adopted nor appended to."""
    for key in ("log", "index"):
        path = vault / layout[key]
        if path.is_file() and BRAIN_MARKER not in path.read_text(encoding="utf-8", errors="replace"):
            raise BrainError(f"{layout[key]} já existe — use --map {key}=<outro>")


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
    elif not args.adopt and vault.is_dir() and any(e.name not in OS_METADATA for e in vault.iterdir()):
        raise BrainError("vault não está vazio — use --adopt")
    check_user_files(vault, parse_yaml(rendered)["layout"])
    if shared_path.exists():
        backup = backup_path(shared_path)
        shutil.copy2(shared_path, backup)

    new_vault = not vault.exists()
    vault.mkdir(parents=True, exist_ok=True)
    Path(files_s).mkdir(parents=True, exist_ok=True)
    created = create_structure(vault, parse_yaml(rendered), args.adopt)
    if backup:
        shared_path.write_text(rendered, encoding="utf-8")  # the only overwrite: --force, previous kept in .bak
    elif create_file(shared_path, rendered):
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
            if section == "contexts" and not CONTEXT_NAME_RE.match(str(name)):
                print(f"aviso: nome de contexto inválido: {name} — os comandos o recusam", file=sys.stderr)
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
        rows.append(("ERRO", "vault", (f"pasta não encontrada: {vault or '(sem vault na configuração local)'} — "
                                       "o app do provedor já sincronizou? (references/providers.md)")))
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
    problems = dict(config["problems"])
    if "brain-config.yml" in problems:  # unreadable: the items that depend on it are not checked
        rows.append(("ERRO", "brain-config.yml", problems["brain-config.yml"]))
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
            if f"{section}.{key}" in problems:
                rows.append(("ERRO", f"{section}.{key}", f"fora do vault: {rel} — use um caminho relativo ao vault"))
                continue
            path = root / rel
            exists = path.is_file() if key in LAYOUT_FILES else path.is_dir()
            rows.append(("OK" if exists else "AVISO", f"{section}.{key}", rel if exists else f"não existe: {rel}"))
    contexts = values["contexts"] if isinstance(values["contexts"], dict) else {}
    if not contexts:
        rows.append(("OK", "contextos", "nenhum (crie com brain.py context add)"))
    for name, item in contexts.items():
        folder = item.get("folder", "") if isinstance(item, dict) else ""
        moc = root / values["layout"]["mocs"] / f"{name}.md"
        if not CONTEXT_NAME_RE.match(str(name)):
            rows.append(("ERRO", f"contexto {name}", "nome de contexto inválido (use letras, números, '_' ou '-')"))
        elif f"contexts.{name}.folder" in problems:
            rows.append(("ERRO", f"contexto {name}", f"contexts.{name}.folder fora do vault: {folder}"))
        elif "layout.mocs" in problems:
            rows.append(("AVISO", f"contexto {name}", f"{folder}; MOC não conferido (layout.mocs fora do vault)"))
        elif not folder or not (root / folder).is_dir():
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
    rows = doctor_items(read_config(config_home), local_config_path(config_home))
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


def check_limit(limit: int):
    if limit < 1:
        raise BrainError(f"--limit precisa ser maior que zero: {limit}")


def load_notes(config_home=None):
    """(notes, warnings) of the configured vault; without local configuration, BrainError(NOT_CONFIGURED, 3)."""
    notes = scan_vault(load_config(config_home))
    return notes, [warning for note in notes for warning in note.warnings]


def print_json(data: dict):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def print_warnings(warnings: list):
    for warning in warnings:
        print(f"aviso: {warning}", file=sys.stderr)


def find_note(ref: str, index: LinkIndex) -> str:
    """Path of the note named by a path or a name (resolve_link); not found = BrainError (exit 2)."""
    path = index.resolve(ref)
    if path is None:
        raise BrainError(f"nota não encontrada: {ref}")
    return path


def cmd_search(args, config_home=None) -> int:
    check_limit(args.limit)
    query = " ".join(args.query)
    notes, warnings = load_notes(config_home)
    results = search(notes, query, context=args.context, note_type=args.type, tag=args.tag, limit=args.limit)
    if args.json:
        print_json({"query": query, "results": results, "warnings": warnings})
        return 0
    print_warnings(warnings)
    if not results:
        print(f"Nenhuma nota encontrada para: {query}")
    for result in results:
        print(f"{result['score']:.2f}  {result['path']}  — {result['title']}")
        if result["snippet"]:
            print(f"    {result['snippet']}")
    return 0


def cmd_related(args, config_home=None) -> int:
    check_limit(args.limit)
    notes, warnings = load_notes(config_home)
    if args.note is not None:
        path = find_note(args.note, LinkIndex(n.path for n in notes))
        results = related(notes, note=path, limit=args.limit)
    else:
        results = related(notes, text=args.text, limit=args.limit)
    if args.json:
        print_json({"results": results, "warnings": warnings})
        return 0
    print_warnings(warnings)
    if not results:
        print("Nenhuma nota relacionada encontrada.")
    for result in results:
        print(f"{result['score']:.2f}  {result['path']}  — {result['title']}")
        print(f"    {'; '.join(result['reasons'])}")
    return 0


def cmd_links(args, config_home=None) -> int:
    notes, warnings = load_notes(config_home)
    index = LinkIndex(n.path for n in notes)
    path = find_note(args.note, index)
    data = note_links(notes, path, index)
    if args.json:
        print_json(dict(data, warnings=warnings))
        return 0
    print_warnings(warnings)
    print(f"Links de saída de {path} ({len(data['outgoing'])}):")
    for item in data["outgoing"]:
        print(f"  {item['target']} → {item['path'] or 'quebrado'}")
    print(f"Backlinks ({len(data['backlinks'])}):")
    for backlink in data["backlinks"]:
        print(f"  {backlink}")
    print(f"Quebrados ({len(data['broken'])}):")
    for target in data["broken"]:
        print(f"  {target}")
    return 0


def cmd_context(args, config_home=None) -> int:
    check_limit(args.limit)
    if not 0 <= args.hops <= MAX_HOPS:
        raise BrainError(f"--hops precisa estar entre 0 e {MAX_HOPS}: {args.hops}")
    if args.max_chars < 1:
        raise BrainError(f"--max-chars precisa ser maior que zero: {args.max_chars}")
    query = " ".join(args.query)
    config = load_config(config_home)
    notes = scan_vault(config)
    warnings = [warning for note in notes for warning in note.warnings]
    data = build_context(notes, query, context=args.context, hops=args.hops, limit=args.limit,
                         max_chars=args.max_chars, values=config["values"])
    if args.json:
        print_json(dict(data, warnings=warnings))
        return 0
    print_warnings(warnings)
    if not data["notes"] and not data["omitted"]:
        print(f"Nenhuma nota encontrada para: {query}")
        return 0
    for item in data["notes"]:
        print(f"=== {item['path']} ({item['reason']}) ===")
        print(item["content"].rstrip("\n"))
        print()
    if data["omitted"]:
        print("Omitidas:")
        for item in data["omitted"]:
            print(f"  {item['path']} — {item['title']} ({item['reason']})")
    if data["broken"]:
        print("Links quebrados:")
        for item in data["broken"]:
            print(f"  {item['note']} → {item['target']}")
    return 0


# ---------------------------------------------------------------- store commands (create, append, regions)

def today() -> str:
    return dt.date.today().isoformat()


def store_config(config_home=None):
    """(values, vault, layout) of the configured vault for the store commands."""
    values = load_config(config_home)["values"]
    return values, vault_dir(values), values["layout"]


def read_exact(path: Path, rel: str) -> str:
    """Text of a note exactly as on disk (line endings and BOM kept), so a rewrite only changes what it adds."""
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as e:
        raise BrainError(f"{rel} não é UTF-8 — não foi alterado", 1) from e


def write_target(vault: Path, rel: str) -> Path:
    """The file to rewrite for the note rel: itself, or the file its symbolic link points to when that file is
    inside the vault; a link to outside the vault = BrainError (code 2), nothing written."""
    path = vault / rel
    if not path.is_symlink():
        return path
    real = path.resolve()
    if not is_inside(str(real), str(vault.resolve())) or real.is_symlink() or not real.is_file():
        raise BrainError(f"{rel} é um link simbólico para fora do vault ({real}) — não foi alterado")
    return real


def rewrite_file(path: Path, text: str):
    """Replace path with text through a hidden temporary file in the same folder (no half-written note); used only
    for the text of append_relation and replace_region, on the path given by write_target (never a link)."""
    if path.is_symlink():
        raise BrainError(f"{path} é um link simbólico — não foi alterado")
    tmp = path.with_name(f".{path.name}.brain-tmp")
    tmp.write_bytes(text.encode("utf-8"))
    shutil.copymode(path, tmp)
    os.replace(tmp, path)


def copy_to_files(source: Path, values: dict, context) -> str:
    """Copy of source into <files>/<context or inbox>/<AAAA>/<name>, never overwriting (<stem>-1<ext>, -2...);
    returns the path relative to files. Files folder missing or not writable = BrainError (exit 1)."""
    files = values["files"]
    if not files or not Path(files).is_dir():
        raise BrainError(f"pasta files não encontrada: {files or '(sem files na configuração local)'}", 1)
    if context:
        check_context_name(context)
    folder = f"{context or INBOX_FILES}/{dt.date.today().year}"
    if posixpath.normpath(folder) != folder or folder.startswith(("/", "..")):
        raise BrainError(f"contexto fora da pasta files: {context}")
    target, stem, suffix = Path(files) / folder, source.stem, source.suffix
    name, n, created = source.name, 0, None
    try:
        target.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                with open(source, "rb") as src, open(target / name, "xb") as dest:
                    created = target / name
                    shutil.copyfileobj(src, dest)
                return f"{folder}/{name}"
            except FileExistsError:
                n += 1
                name = f"{stem}-{n}{suffix}"
    except OSError as e:
        if created is not None and created.exists():
            created.unlink()  # only the incomplete copy this call created; nothing else is ever removed
        raise BrainError(f"não consegui copiar para a pasta files ({target}): {e.strerror or e}", 1) from e


def free_raw_path(vault: Path, layout: dict, title: str) -> str:
    """raw/AAAA-MM-DD-<slug>.md, or -1, -2... so a source note of the same day is never overwritten."""
    base = posixpath.join(inside_vault(layout["raw"], "layout.raw"), f"{today()}-{slugify(title)}")
    candidate, n = f"{base}.md", 0
    while (vault / candidate).exists():
        n += 1
        candidate = f"{base}-{n}.md"
    return candidate


def cmd_ingest(args, config_home=None) -> int:
    values, vault, layout = store_config(config_home)
    source = args.source.strip()
    url = source if URL_RE.match(source) else None
    if args.context:
        check_context(args.context, values)
    if url is None and not Path(source).is_file():
        raise BrainError(f"fonte não encontrada: {args.source}")
    extracted = ""
    if args.text_file:
        if not Path(args.text_file).is_file():
            raise BrainError(f"arquivo de texto não encontrado: {args.text_file}")
        try:
            extracted = Path(args.text_file).read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as e:
            raise BrainError(f"--text-file não é UTF-8: {args.text_file}") from e
    default_title = re.sub(r"^https?://", "", url, flags=re.IGNORECASE).rstrip("/") if url else Path(source).stem
    title = " ".join((args.title or default_title).split()) or "fonte"

    file_rel = None if url else copy_to_files(Path(source), values, args.context)  # the copy comes first
    raw_rel = free_raw_path(vault, layout, title)
    try:
        write_new_file(vault / raw_rel, render_source_note(title, today(), args.context, file_rel, url, extracted))
    except OSError as e:
        kept = f"; a cópia ficou em {file_rel} (na pasta files)" if file_rel else ""
        raise BrainError(f"não consegui criar a nota de fonte {raw_rel}: {e.strerror or e}{kept}", 1) from e
    append_log(vault, layout, "ingest", f"{raw_rel} — {url or file_rel}")
    if args.json:
        print_json({"raw": raw_rel, "file": file_rel, "url": url})
        return 0
    print(f"Nota de fonte: {raw_rel}")
    print(f"Link: {url}" if url else f"Arquivo copiado: {file_rel} (na pasta files)")
    return 0


def source_value(source, vault: Path) -> str:
    """frontmatter.source of new-note: a URL as is, a note of the vault as "[[<path without .md>]]"."""
    text = (source or "").strip()
    if not text or URL_RE.match(text) or (text.startswith("[[") and text.endswith("]]")):
        return text
    if is_absolute(text):
        if not is_inside(text, str(vault)):
            raise BrainError(f"--source fora do vault: {text}")
        text = _pure(text).relative_to(_pure(str(vault))).as_posix()
    rel = inside_vault(text, "--source")
    return f"[[{rel[:-3] if rel.lower().endswith('.md') else rel}]]"


def cmd_new_note(args, config_home=None) -> int:
    values, vault, layout = store_config(config_home)
    if args.type not in NOTE_TYPES:
        raise BrainError(f"tipo desconhecido: {args.type} — use um de: {', '.join(NOTE_TYPES)}")
    title = " ".join(args.title.split())
    rel = note_path(title, args.context, values)
    tags = unique(frontmatter_tags(args.tags or ""))
    template = vault / layout["templates"] / f"{args.type}.md"
    if not template.is_file():
        template = TEMPLATES_DIR / f"{args.type}.md"
    text = render_note(template.read_text(encoding="utf-8"), tags=tags, title=title, date=today(),
                       context=args.context or "", source=source_value(args.source, vault))
    write_new_file(vault / rel, text)
    append_log(vault, layout, "new-note", f"{rel} — {args.type}")
    if args.json:
        print_json({"path": rel})
    else:
        print(rel)
    return 0


def cmd_relate(args, config_home=None) -> int:
    values, vault, layout = store_config(config_home)
    why = " ".join(args.why.split())
    if not why:
        raise BrainError("--why precisa do motivo da relação")
    index = LinkIndex(rel for _, rel in walk_notes(values))
    source, target = find_note(args.source, index), find_note(args.target, index)
    if source == target:
        raise BrainError(f"uma nota não se relaciona com ela mesma: {source}")
    pairs = [(source, target)] + ([(target, source)] if args.both else [])
    changes = []
    for note, other in pairs:  # everything is read and checked before the first write
        text = read_exact(vault / note, note)
        name = link_name(other, index)
        new = append_relation(text, name, why)
        changes.append((note, name, text, new, write_target(vault, note) if new != text else None))
    for note, name, text, new, path in changes:
        line = relation_line(name, why)
        if new == text:
            print(f"relação já existe: {note} {line}")
            continue
        rewrite_file(path, new)
        append_log(vault, layout, "relate", f"{note} → [[{name}]] — {why}")
        print(f"{note}: {line}")
    return 0


def plan_region_file(vault: Path, rel: str, regions: dict, new_text, detail: str):
    """(path to write, new text, created, detail) of the regions of rel (created from new_text() when missing), or
    None when nothing changes. Only reads: invalid markers or a link out of the vault = BrainError naming rel."""
    path = vault / rel
    target = write_target(vault, rel)  # a link out of the vault is refused before anything is read
    exists = target.exists()
    text = read_exact(target, rel) if exists else new_text()
    result = text
    try:
        for name, content in regions.items():
            result = replace_region(result, name, content)
    except BrainError as e:
        raise BrainError(f"{rel}: {e}", e.code) from e
    if not exists:
        return path, result, True, detail + " (criado)"
    if result == text:
        return None
    return target, result, False, detail


def cmd_index(args, config_home=None) -> int:
    values, vault, layout = store_config(config_home)
    contexts = values["contexts"] if isinstance(values["contexts"], dict) else {}
    if args.context:
        check_context(args.context, values)
    for name in contexts:  # every name is checked before anything is written
        check_context_name(name)
    mocs = inside_vault(layout["mocs"], "layout.mocs")
    own = {posixpath.normpath(layout["index"]), posixpath.normpath(layout["log"])}
    paths, entries = [], []
    for path, rel in walk_notes(values):
        paths.append(rel)
        if rel in own or (mocs and rel.startswith(mocs + "/")):
            continue
        text = path.read_bytes().decode("utf-8", errors="replace")
        entries.append(index_entry(rel, text, contexts))
    links = LinkIndex(paths)
    by_context = {name: [e for e in entries if e.context == name] for name in contexts}

    plans = []  # every file is read and checked before the first write
    for name in ([args.context] if args.context else list(contexts)):
        rel, notes = inside_vault(posixpath.join(mocs, f"{name}.md"), f"MOC de {name}"), by_context[name]
        title = (contexts[name].get("title") if isinstance(contexts[name], dict) else None) or name
        plans.append((rel, plan_region_file(vault, rel, {"notes": moc_notes_content(notes, links)},
                                            lambda n=name, t=title: moc_text(vault, layout, n, t),
                                            f"{len(notes)} nota(s)")))
    regions = {"contexts": index_contexts_content(contexts, {k: len(v) for k, v in by_context.items()}, mocs),
               "recent": index_recent_content(entries, links)}
    index_rel = inside_vault(layout["index"], "layout.index")
    plans.append((index_rel, plan_region_file(vault, index_rel, regions, render_index,
                                              f"{len(contexts)} contexto(s), "
                                              f"{min(len(entries), RECENT_LIMIT)} recente(s)")))
    written = []
    for rel, plan in plans:
        if plan is None:
            continue
        path, text, created, detail = plan
        if created:
            write_new_file(path, text)
        else:
            rewrite_file(path, text)
        append_log(vault, layout, "index", f"{rel} — {detail}")
        written.append(rel)
    for rel in written:
        print(f"atualizado: {rel}")
    if not written:
        print("Índices já atualizados.")
    return 0


# ---------------------------------------------------------------- cli

def context_add_parser() -> argparse.ArgumentParser:
    """`context add` (exactly "add" right after "context"); any other text after "context" is a query."""
    p = argparse.ArgumentParser(prog="brain.py context add", description="registra um contexto, cria a pasta e o MOC")
    p.add_argument("name")
    p.add_argument("--folder", required=True, help="pasta relativa ao vault")
    p.add_argument("--title", help="título do MOC (padrão: o nome)")
    return p


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="brain.py",
        description=("Ferramentas determinísticas do second-brain: onboarding do vault, configuração, diagnóstico, "
                     "busca e fluxo de guardar."))
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
    p = sub.add_parser("context", help="pacote de notas para uma pergunta (só leitura); 'context add' cria um contexto",
                       description=("context QUERY: MOC do contexto, resultados da busca e vizinhos por link, até "
                                    "--max-chars. Se o primeiro argumento é exatamente 'add', é o 'context add' "
                                    "(cria um contexto); para buscar a palavra add, use 'context -- add'."))
    p.add_argument("query", nargs="+", metavar="QUERY")
    p.add_argument("--context", help="só notas deste contexto na busca; o MOC dele entra primeiro")
    p.add_argument("--hops", type=int, default=1, help=f"passos de link a partir da busca (0..{MAX_HOPS}, padrão 1)")
    p.add_argument("--limit", type=int, default=8, help="resultados da busca (padrão 8)")
    p.add_argument("--max-chars", type=int, default=40000, help="soma máxima do conteúdo das notas (padrão 40000)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("doctor", help="o que está configurado, o que funciona e o que falta")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("search", help="busca por termos, com pontuação (título 3, tags 2, corpo 1); só leitura")
    p.add_argument("query", nargs="+", metavar="QUERY")
    p.add_argument("--context", help="só notas deste contexto")
    p.add_argument("--type", help="só notas com este frontmatter.type")
    p.add_argument("--tag", help="só notas com esta tag")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("related", help="notas parecidas com uma nota ou com um texto, com os motivos; só leitura")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--note", metavar="CAMINHO", help="caminho (ou nome) da nota de referência")
    group.add_argument("--text", metavar="TEXTO", help="texto livre de referência")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("links", help="links de saída, backlinks e links quebrados de uma nota; só leitura")
    p.add_argument("note", metavar="NOTA", help="caminho ou nome da nota")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("ingest", help="guarda uma fonte (arquivo ou URL): cópia em files e nota de fonte em raw/")
    p.add_argument("source", metavar="FONTE", help="arquivo local ou URL http(s)")
    p.add_argument("--context", help="contexto da fonte (sem ele, a cópia vai para <files>/inbox)")
    p.add_argument("--title", help="título da nota de fonte (padrão: o nome do arquivo ou a URL)")
    p.add_argument("--text-file", metavar="ARQ", help="texto extraído da fonte (UTF-8), sob '## Extracted text'")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("new-note", help="cria uma nota a partir do modelo do tipo; nunca sobrescreve")
    p.add_argument("--type", required=True, help=" | ".join(NOTE_TYPES))
    p.add_argument("--title", required=True)
    p.add_argument("--context", help="contexto (sem ele, a nota vai para para.resources)")
    p.add_argument("--source", metavar="CAMINHO_OU_URL", help="nota de fonte (raw/...) ou URL")
    p.add_argument("--tags", metavar="A,B", help="tags separadas por vírgula")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("relate", help="acrescenta '- [[PARA]] — motivo' na seção Relations de DE")
    p.add_argument("source", metavar="DE", help="caminho ou nome da nota")
    p.add_argument("target", metavar="PARA", help="caminho ou nome da nota")
    p.add_argument("--why", required=True, help="motivo da relação (ex.: aplica, contradiz, exemplo de)")
    p.add_argument("--both", action="store_true", help="também em PARA, apontando para DE")
    p = sub.add_parser("index", help="regenera as regiões geradas dos MOCs e do index.md")
    p.add_argument("--context", help="só o MOC deste contexto (e o index.md)")
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:2] == ["context", "add"]:
        args = context_add_parser().parse_args(argv[2:])
        args.command = "context add"
    else:
        args = parser.parse_args(argv)

    try:
        if args.command == "init":
            return cmd_init(args)
        if args.command == "config":
            return cmd_config(args.json)
        if args.command == "context add":
            return cmd_context_add(args)
        if args.command == "context":
            return cmd_context(args)
        if args.command == "doctor":
            return cmd_doctor(args.json)
        if args.command == "search":
            return cmd_search(args)
        if args.command == "related":
            return cmd_related(args)
        if args.command == "links":
            return cmd_links(args)
        if args.command == "ingest":
            return cmd_ingest(args)
        if args.command == "new-note":
            return cmd_new_note(args)
        if args.command == "relate":
            return cmd_relate(args)
        if args.command == "index":
            return cmd_index(args)
    except BrainError as e:
        print(f"erro: {e}", file=sys.stderr)
        return e.code
    except OSError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
