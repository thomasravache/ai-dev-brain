#!/usr/bin/env python3
"""Deterministic tooling for the photon-brain skill, formerly second-brain (stdlib only, Python 3.9+). Run with --help.

Two configuration layers (ADR-0008): the local one, per machine, in $BRAIN_CONFIG_HOME/config.yml (vault, files,
provider) and the shared one, synced with the vault, in <vault>/brain-config.yml (layout, contexts, processors).
Writes to the vault only create files or append to them (ADR-0007); every write adds a line to log.md.
search, related and links only read the vault: an in-memory scan of the notes, without an index (SPEC-0018).
ingest, new-note, relate and index write only through write_new_file and the text of append_relation and
replace_region, always with a log.md line (SPEC-0019).
capture, inbox list, inbox done and ingest --move handle the inbox; move_out_of_inbox is the only function that
moves a file, and only out of the inbox, never overwriting nor deleting (SPEC-0021, ADR-0007).
capture --print writes nothing and needs no configuration: it shows the path and content of the capture for the
agent to create through the provider's connector (SPEC-0044, ADR-0013); brain.py itself never uses the network.
process, ingest and doctor run the processors declared in brain-config.yml; run_processor is the only function
that runs an external process: without a shell, in a temporary folder, with a timeout (SPEC-0022, ADR-0009).
lint only reads: each rule is a check_<rule> function over a single scan of the vault; it never fixes nor deletes
(SPEC-0023, ADR-0007).
export-notebooklm only reads the vault: it writes the package of a MOC to an empty folder outside it, creating each
file exclusively, and does not touch log.md (SPEC-0024).
Confidential items (SPEC-0050, ADR-0014): a secret never enters the vault; a secret-ref note only says where it is
(vault_ref, never opened). Notes with `confidential: true` stay out of search, related, context, links, index and
the export unless asked (--include-confidential; never in the export); ingest --confidential never runs a processor.
lint warns (secret-in-note, personal-data) without ever printing the value found.
backup writes a verified zip of the vault (vault/..., files/..., brain-backup.json with the sha256 of each entry) to
each folder of backup_targets, outside the vault and files; rotate_backups is the only function that removes a
backup, only names of its pattern and never the new one (SPEC-0051, ADR-0015). restore never overwrites: a note comes
back as a new file next to the current one, the whole backup goes to a new folder.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import errno
import hashlib
import html
import json
import math
import ntpath
import os
import posixpath
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
import zlib
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

BRAIN_VERSION = "2026.11.6"
SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets"
DEFAULT_SHARED_CONFIG = ASSETS_DIR / "brain-config.yml"
TEMPLATES_DIR = ASSETS_DIR / "templates"

PROVIDERS = ("google-drive", "onedrive", "icloud", "local")
LOCAL_KEYS = ("vault", "files", "provider", "backup_targets")  # backup_targets: list of folders of this machine
LAYOUT_DIRS = ("inbox", "raw", "mocs", "templates")
LAYOUT_FILES = ("index", "log")
LAYOUT_KEYS = LAYOUT_DIRS + LAYOUT_FILES
PARA_KEYS = ("projects", "areas", "resources", "archive")
SHARED_KEYS = ("version", "language", "layout", "para", "contexts", "processors", "inbox_stale_days",
               "conflict_patterns", "lint", "backup")
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
MAX_HOPS = 2  # context: link steps from the search results; export-notebooklm: from the notes the MOC cites
EXPORT_EXTRA = ("sources.md", "combined.md")  # export-notebooklm files that are not notes
TWO_HOPS = 0.5  # neighborhood of a note two links away (a direct link is 1)
SNIPPET_WIDTH, SNIPPET_LEAD = 160, 40  # snippet length and how much of it comes before the term
REASON_TERMS = 5  # shared terms listed in the "termos:" reason
FRONTMATTER_END_RE = re.compile(r"^(?:---|\.\.\.)[ \t\r]*$", re.MULTILINE)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
CLOSING_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*$")  # CommonMark: only spaces after a closing fence
INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)[^\n]*?(?<!`)\1(?!`)")  # a run of N backticks closed by N
WIKILINK_RE = re.compile(r"!?\[\[([^\[\]\n]+?)\]\]")
HEADING_RE = re.compile(r"^#[ \t]+(.+?)[ \t#]*$")
TAG_RE = re.compile(r"(?<!\S)#([\w/-]+)")
TOKEN_RE = re.compile(r"[^\W_]+")
MIN_TERM = 2  # shorter terms ("s" of [[Ref#s]], "x" of "x = 1") do not count
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
NOTE_TYPES = ("note", "lecture", "source", "video", "document", "link", "moc", "answer", "secret-ref")
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

# inbox: capture, list, done and ingest --move (SPEC-0021; details in references/inbox.md)
CAPTURE_WORDS = 6  # words of the text in the name of a capture
INBOX_TEXT_SUFFIXES = (".md", ".txt")
INBOX_LINK_SUFFIXES = (".url", ".webloc")
ICLOUD_SUFFIX = ".icloud"  # placeholder of a file iCloud has not downloaded yet
SYNCING_SECONDS = 600  # a 0-byte file modified less than this ago is still syncing
INBOX_READ_BYTES = 8192  # enough to classify and preview a text item (a longer text is not "only a URL")
PREVIEW_MAX = 120
STALE_DAYS_DEFAULT = 7
PROCESSED_DIR = "processed"  # <layout.raw>/processed/AAAA-MM/: text items taken out of the inbox
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")  # control characters: escaped in log.md and the output
LINK_IN_FILE_RE = re.compile(r"^URL=(\S+)|<string>(https?://[^<]+)</string>", re.MULTILINE | re.IGNORECASE)

# processors: commands of brain-config.yml that turn a source into text (SPEC-0022, ADR-0009; references/processors.md)
YOUTUBE_HOSTS = frozenset(("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"))
KIND_SUFFIXES = {
    "video": (".mp4", ".mov", ".mkv", ".webm", ".avi"),
    "audio": (".mp3", ".m4a", ".wav", ".ogg", ".opus"),
    "pdf": (".pdf",),
}
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
PROCESSOR_MARKERS = ("input", "output", "output_dir")
PROCESSOR_MARKER_RE = re.compile(r"\{(input|output|output_dir)\}")
PROCESSOR_TIMEOUT = 1800  # seconds, when the processor does not declare timeout
CHECK_TIMEOUT = 60  # seconds for the doctor check ("<executable> --version" or check)
STDERR_MAX = 500  # characters of the processor stderr in a failure message
SUBTITLE_SUFFIXES = (".vtt", ".srt")
SUBTITLE_TIME_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})[.,]\d+\s+-->")
SUBTITLE_TAG_RE = re.compile(r"<[^>\n]*>")
# lint (SPEC-0023): rule -> severity, in the order of the report; conflict patterns per provider documented in
# references/providers.md (generic patterns: the real names of each provider were not checked on this machine)
LINT_SEVERITY = {"broken-link": "error", "conflict-copy": "error", "missing-file": "error", "orphan": "warn",
                 "stale-inbox": "warn", "frontmatter": "warn", "secret-in-note": "warn", "personal-data": "warn",
                 "config": "error"}
LINT_LABELS = {"error": "ERRO", "warn": "AVISO"}
GENERIC_CONFLICT_PATTERNS = (r"(?P<base>.+) \(\d+\)\.md$", r"(?i)(?P<base>.+)[ _-]conflict.*\.md$")
MAX_CONFLICT_PATTERN = 500  # characters of a conflict pattern; longer ones are refused (never matched)
CONFLICT_PATTERNS = {provider: GENERIC_CONFLICT_PATTERNS for provider in PROVIDERS}
REQUIRED_FIELDS = ("title", "created")  # frontmatter of a note of the skill's types (references/note-types.md)
# confidential items (SPEC-0050, ADR-0014; references/confidential.md)
SECRET_REF_TYPE = "secret-ref"
VAULT_REF_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^\s\x00-\x1f\x7f][^\x00-\x1f\x7f]*")  # fullmatch; never opened
CONFIDENTIAL_LINE_RE = re.compile(r"^confidential[ \t]*:[ \t]*(?:true|True|TRUE)[ \t]*(?:#.*)?$", re.MULTILINE)
NOT_EXTRACTED = "_(confidential: not extracted)_"
CONFIDENTIAL_LINK = "[confidencial]"  # what the export writes in place of a link to a confidential note
INCLUDE_CONFIDENTIAL = "--include-confidential"
CONFIDENTIAL_REFUSED = f"nota confidencial — use {INCLUDE_CONFIDENTIAL} só se a pessoa pedir para incluí-la"
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
TOKEN_RE_SECRET = re.compile(r"(?<![\w-])(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|AKIA[0-9A-Z]{16}"
                             r"|xox[abpr]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9_-]{20,})(?![\w-])")
SECRET_LABEL_RE = re.compile(r"(?i)(?<![\w-])(?:senha|password|passwd|pwd|pin|token|api[ _-]?key|secret|segredo)"
                             r"(?![\w-])[*_]*[ \t]*[:=][*_]*[ \t]*(\S*)")
# values that are a marker, not a secret: ***, <...>, ${...}, {{...}}, xxx, ... and YAML booleans/null
SECRET_PLACEHOLDER_RE = re.compile(r"(?i)^(?:\*+|<.*|\$\{.*|\{\{.*|x{3,}\W*|\.{3,}|…|true|false|null|none|yes|no)$")
SECRET_MIN = 4  # characters of a labeled value
CPF_RE = re.compile(r"(?<![\w.-])(\d{3}\.\d{3}\.\d{3}-\d{2})(?![\w-])|(?i:\bCPF\b)\W{0,3}(\d{11})(?!\d)")
CNPJ_RE = re.compile(r"(?<![\w.-])(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})(?![\w-])|(?i:\bCNPJ\b)\W{0,3}(\d{14})(?!\d)")
CARD_RE = re.compile(r"(?<![\w.-])(\d{3,6}(?:[ -]\d{3,6}){2,4})(?![\w-])"
                     r"|(?i:\b(?:cart[aã]o|card)\b)\W{0,3}(\d{13,19})(?!\d)")
LABELED_DOCUMENT_RE = re.compile(r"(?i)(?<![\w-])(?:RG|CNH|passaporte|passport|SSN|DNI|NIF)(?![\w-])[ \t]*:[ \t]*\S*\d")
PERSONAL_DETECTORS = ("cpf", "cnpj", "card", "labeled-document")
PERSONAL_KINDS = {"cpf": "cpf", "cnpj": "cnpj", "card": "cartão", "labeled-document": "documento rotulado"}
BACKUP_DEFAULTS = {"keep": 10, "warn_days": 7, "with_files": False}  # backup: of brain-config.yml (SPEC-0051)
BACKUP_MINIMUM = {"keep": 1, "warn_days": 0}  # keep >= 1 (ADR-0015), warn_days >= 0
BACKUP_NAME_RE = re.compile(r"^second-brain-(\d{4}-\d{2}-\d{2}-\d{6})(-files)?\.zip$")  # the only names rotated
BACKUP_STAMP = "%Y-%m-%d-%H%M%S"
BACKUP_MANIFEST = "brain-backup.json"
BACKUP_PARTIAL = ".partial"
BACKUP_ROOTS = ("vault", "files")  # top folders of a backup zip: never an absolute path of this machine
NO_BACKUP_TARGET = "nenhum destino de backup — references/backup.md"


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


def inside_on_disk(child, parent) -> bool:
    """is_inside of the resolved paths, or child (or its nearest existing ancestor) is the same folder as parent or
    below it on disk (os.path.samefile): catches another case of the vault path on file systems that do not tell
    case apart (macOS, Windows)."""
    child, parent = Path(child).expanduser().resolve(), Path(parent).expanduser().resolve()
    if is_inside(str(child), str(parent)):
        return True
    with contextlib.suppress(OSError):
        if not parent.is_dir():
            return False
        for folder in (child, *child.parents):
            if folder.exists() and os.path.samefile(folder, parent):
                return True
    return False


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
    values, origins, problems, warnings = {}, {}, [], []
    for key in LOCAL_KEYS:
        if key == "backup_targets":  # a list of folders of this machine (SPEC-0051); anything else = none
            given = local.get(key) if isinstance(local.get(key), list) else []
            values[key] = [item for item in given if isinstance(item, str) and item]
            origins[key] = ORIGIN_LOCAL if values[key] else ORIGIN_DEFAULT
            continue
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
        elif key == "inbox_stale_days":  # a whole number of days; missing or invalid = the default
            given = stale_days(shared.get(key))
            values[key] = given if given is not None else stale_days(defaults.get(key)) or STALE_DAYS_DEFAULT
            origins[key] = ORIGIN_VAULT if given is not None else ORIGIN_DEFAULT
            if given is None and key in shared:
                warnings.append({"key": key, "message": (f"brain-config.yml: {key} inválido: {shared[key]} — use um "
                                                         f"número inteiro de dias >= 0; usando {values[key]}")})
        elif key == "backup":  # keep, warn_days and with_files; missing or invalid = the default (SPEC-0051)
            values[key], found, invalid = backup_settings(shared.get(key) if key in shared else None)
            origins[key] = ORIGIN_VAULT if found else ORIGIN_DEFAULT
            warnings += [{"key": name, "message": (f"brain-config.yml: {name} inválido: {given} — {rule}; usando "
                                                   f"{fmt_scalar(default)}")} for name, given, rule, default in invalid]
        elif key == "conflict_patterns":  # missing = the patterns of the local provider (references/providers.md)
            found = key in shared
            values[key] = shared[key] if found else list(CONFLICT_PATTERNS.get(values["provider"],
                                                                                GENERIC_CONFLICT_PATTERNS))
            origins[key] = ORIGIN_VAULT if found else ORIGIN_DEFAULT
        else:
            found = key in shared
            values[key] = shared[key] if found else defaults.get(key, {})
            origins[key] = ORIGIN_VAULT if found else ORIGIN_DEFAULT
    config = {"values": values, "origins": origins, "problems": problems + check_shared(values)}
    if warnings:  # invalid values that fell back to the default (shown by config --json and doctor)
        config["warnings"] = warnings
    return config


def stale_days(value):
    """inbox_stale_days as a whole number of days (>= 0), or None when absent or invalid."""
    try:
        days = int(str(value).strip())
    except ValueError:
        return None
    return days if days >= 0 else None


def backup_settings(given) -> tuple:
    """(settings, found, invalid) of the backup: key of brain-config.yml: settings = keep, warn_days and with_files
    (BACKUP_DEFAULTS for each missing or invalid value); invalid = (key, value, rule, default) of each value that
    fell back to the default, like inbox_stale_days."""
    settings, invalid = dict(BACKUP_DEFAULTS), []
    if given is None:
        return settings, False, invalid
    if not isinstance(given, dict):
        return settings, False, [("backup", fmt_flow(given), "use um mapa {keep, warn_days, with_files}", "padrão")]
    for name, minimum in BACKUP_MINIMUM.items():
        if name in given:
            number = stale_days(given[name])
            if number is not None and number >= minimum:
                settings[name] = number
            else:
                invalid.append((f"backup.{name}", given[name], f"use um número inteiro >= {minimum}",
                                BACKUP_DEFAULTS[name]))
    if "with_files" in given:
        flag = str(given["with_files"]).strip().lower()
        if flag in ("true", "false"):
            settings["with_files"] = flag == "true"
        else:
            invalid.append(("backup.with_files", given["with_files"], "use true ou false", "false"))
    return settings, True, invalid


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


def render_local_config(vault: str, files: str, provider: str, backup_targets=()) -> str:
    data = {"vault": vault, "files": files, "provider": provider}
    if backup_targets:
        data["backup_targets"] = list(backup_targets)
    return LOCAL_HEADER + dump_yaml(data)


def local_backup_targets(path: Path) -> list:
    """backup_targets of the local configuration already on disk (none when absent or unreadable): init keeps them
    when it rewrites this machine's configuration."""
    with contextlib.suppress(BrainError):
        if path.is_file():
            given = read_yaml(path).get("backup_targets")
            return [item for item in given if isinstance(item, str) and item] if isinstance(given, list) else []
    return []


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
        handle.write(f"- {now()} {one_line(command)} {one_line(summary)}\n")


def one_line(text: str) -> str:
    """text with each control character escaped ("\\n", "\\t", "\\x1b"): one line in log.md and in the output, and
    nothing the terminal interprets."""
    names = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
    return CONTROL_RE.sub(lambda m: names.get(m.group(), f"\\x{ord(m.group()):02x}"), str(text))


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
    lowered = text.lower()
    if lowered.isascii():
        return lowered
    return "".join(char for char in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(char))


def tokenize(text: str) -> list:
    """Terms of a text: folded words (letters and digits) of MIN_TERM or more characters that are not Portuguese or
    English stopwords."""
    return [term for term in TOKEN_RE.findall(fold(text)) if len(term) >= MIN_TERM and term not in STOPWORDS]


def unique(items) -> list:
    return list(dict.fromkeys(items))


class Note:
    """A note of the vault as parse_note reads it (path relative to the vault, with "/"). `terms` counts every term
    (title, tags and body: the vector of related); title_terms, tag_terms and body_terms are the fields of search;
    `text` is the whole note (frontmatter included), the content of the context package. A plain class, not a
    dataclass: the tests load brain.py by path, outside sys.modules. An unknown field = TypeError."""
    __slots__ = ("body", "body_terms", "context", "frontmatter", "links", "path", "tag_terms", "tags", "terms",
                 "text", "title", "title_terms", "warnings")

    def __init__(self, **fields):
        unknown = sorted(set(fields) - set(self.__slots__))
        if unknown:
            raise TypeError(f"Note: campos desconhecidos: {', '.join(unknown)}")
        for name in self.__slots__:
            setattr(self, name, fields.get(name))

    def __repr__(self) -> str:
        return f"Note({self.path!r}, title={self.title!r})"

    @property
    def note_type(self) -> str:
        value = self.frontmatter.get("type")
        return value.strip() if isinstance(value, str) else ""


def read_frontmatter(text: str):
    """(frontmatter, body, problem): YAML between a first line "---" and the next "---" (or "..."); a leading BOM
    is ignored. Invalid or unclosed YAML gives {} and the problem, never an exception."""
    first, sep, rest = text.lstrip("\ufeff").partition("\n")
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


def fenced_lines(lines):
    """(line, in_code) of each line: True for the fence lines and the lines inside a fenced code block (``` or ~~~).
    A fence closes only with the same character, at least the same length (```` is not closed by ```) and nothing
    but spaces after the mark ("```python" inside a ``` block is code, as in CommonMark)."""
    fence = None
    for line in lines:
        if fence is None:
            m = FENCE_RE.match(line)
            if m:
                fence = m.group(1)
            yield line, fence is not None
            continue
        m = CLOSING_FENCE_RE.match(line)
        if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
            fence = None
        yield line, True


def prose(body: str) -> str:
    """Body without fenced code blocks (fenced_lines) and inline code: where tags, links and headings count."""
    lines = [line for line, code in fenced_lines(body.splitlines()) if not code]
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


# ---------------------------------------------------------------- confidential items (pure; SPEC-0050, ADR-0014)

def is_vault_ref(value) -> bool:
    """True only for "<esquema>://<caminho>": scheme [a-z][a-z0-9+.-]*, non-empty path. Only the format is checked:
    brain.py never resolves nor opens the reference (ADR-0014)."""
    return isinstance(value, str) and bool(VAULT_REF_RE.fullmatch(value))


def frontmatter_block(text: str) -> str:
    """The raw YAML between the first "---" and the next "---" (or "..."), with "\n" line endings (a leading BOM
    and CRLF endings do not hide it); "" without a closed frontmatter."""
    first, sep, rest = (text or "").lstrip("\ufeff").replace("\r\n", "\n").partition("\n")
    end = FRONTMATTER_END_RE.search(rest) if first.rstrip() == "---" and sep else None
    return rest[:end.start()] if end else ""


def marked_confidential(frontmatter: dict, text: str) -> bool:
    """True only when the frontmatter has `confidential: true` as the YAML boolean: parse_scalar does not convert
    types, so the line is read as written ("true" in quotes, yes, false or anything else = not confidential)."""
    value = frontmatter.get("confidential") if isinstance(frontmatter, dict) else None
    return (isinstance(value, str) and value.lower() == "true"
            and bool(CONFIDENTIAL_LINE_RE.search(frontmatter_block(text))))


def is_confidential(note: Note) -> bool:
    """True when the note has `confidential: true` (marked_confidential)."""
    return marked_confidential(note.frontmatter, note.text or "")


def confidential_paths(notes) -> set:
    return {note.path for note in notes if is_confidential(note)}


def visible_notes(notes: list, include_confidential: bool = False) -> list:
    """The notes a command shows: all with include_confidential, else the ones without confidential: true."""
    return list(notes) if include_confidential else [note for note in notes if not is_confidential(note)]


def with_frontmatter_keys(text: str, keys: dict) -> str:
    """Text with each "key: value" of keys in the frontmatter: a key already there is replaced (its line), a
    missing one goes before the closing "---"; without a frontmatter one is created. Used by new-note for
    confidential: true and vault_ref, whatever the template of the vault has."""
    nl = newline_of(text)
    first, sep, rest = text.partition("\n")
    end = FRONTMATTER_END_RE.search(rest) if first.rstrip() == "---" and sep else None
    if end is None:
        head = "".join(f"{key}: {value}{nl}" for key, value in keys.items())
        return f"---{nl}{head}---{nl}{text}"
    lines, done = rest[:end.start()].splitlines(), set()
    for i, line in enumerate(lines):
        m = KEY_RE.match(line)
        if m and m.group(1) in keys and m.group(1) not in done:
            lines[i] = f"{m.group(1)}: {keys[m.group(1)]}"
            done.add(m.group(1))
    lines += [f"{key}: {value}" for key, value in keys.items() if key not in done]
    return first + "\n" + "".join(f"{line}{nl}" for line in lines) + rest[end.start():]


def _secret_kind(line: str):
    """The kind of secret written in a line, or None: "chave privada", "token" or "senha rotulada"."""
    if PRIVATE_KEY_RE.search(line):
        return "chave privada"
    if TOKEN_RE_SECRET.search(line):
        return "token"
    for m in SECRET_LABEL_RE.finditer(line):
        value = m.group(1).strip("\"'`")
        if len(value) >= SECRET_MIN and not SECRET_PLACEHOLDER_RE.match(value):
            return "senha rotulada"
    return None


def find_secrets(text: str) -> list:
    """[(line, kind)] of each line of text (1 = the first) with a private key block, a token with a known prefix
    or a labeled password; placeholders (***, <...>, ${...}, {{...}}, xxx) do not count. Never the value."""
    found = []
    for number, line in enumerate((text or "").splitlines(), 1):
        kind = _secret_kind(line)
        if kind:
            found.append((number, kind))
    return found


def _digits(text: str) -> list:
    return [int(char) for char in text if char.isdigit()]


def valid_cpf(text: str) -> bool:
    """The two check digits of a CPF (11 digits, not all the same)."""
    d = _digits(text)
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for size in (9, 10):
        total = sum(digit * weight for digit, weight in zip(d[:size], range(size + 1, 1, -1)))
        if (total * 10 % 11) % 10 != d[size]:
            return False
    return True


def valid_cnpj(text: str) -> bool:
    """The two check digits of a CNPJ (14 digits, not all the same)."""
    d = _digits(text)
    if len(d) != 14 or len(set(d)) == 1:
        return False
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        rest = sum(digit * weight for digit, weight in zip(d[:size], weights)) % 11
        if (0 if rest < 2 else 11 - rest) != d[size]:
            return False
    return True


def valid_card(text: str) -> bool:
    """13 to 19 digits, not all the same, that pass the Luhn check."""
    d = _digits(text)
    if not 13 <= len(d) <= 19 or len(set(d)) == 1:
        return False
    total = sum(digit if i % 2 == 0 else (digit * 2 - 9 if digit > 4 else digit * 2)
                for i, digit in enumerate(reversed(d)))
    return total % 10 == 0


PERSONAL_CHECKS = {  # detector -> (regex with one value per alternative group, validator of the value)
    "cpf": (CPF_RE, valid_cpf),
    "cnpj": (CNPJ_RE, valid_cnpj),
    "card": (CARD_RE, valid_card),
    "labeled-document": (LABELED_DOCUMENT_RE, None),
}


def _personal_hit(line: str, detector: str) -> bool:
    pattern, valid = PERSONAL_CHECKS[detector]
    for m in pattern.finditer(line):
        value = next((group for group in m.groups() if group), m.group(0))
        if valid is None or valid(value):
            return True
    return False


def find_personal_data(text: str, detectors=None, patterns=None) -> list:
    """[(line, kind)] of the personal data written in text (1 = the first line), one per line and kind: valid CPF,
    CNPJ and card (check digits, Luhn), labeled document (RG, CNH, passaporte...: with a digit) and each extra
    pattern ({name: compiled regex}) under its name. detectors = the ones turned on (None = all). E-mail and phone
    do not count. Never the value."""
    detectors = PERSONAL_DETECTORS if detectors is None else [d for d in detectors if d in PERSONAL_CHECKS]
    extra = dict(patterns or {})
    found = []
    for number, line in enumerate((text or "").splitlines(), 1):
        if not any(char.isdigit() for char in line) and not extra:
            continue
        found += [(number, PERSONAL_KINDS[d]) for d in detectors if _personal_hit(line, d)]
        found += [(number, name) for name, pattern in extra.items() if pattern.search(line)]
    return found


def compile_personal_data(lint) -> tuple:
    """(detectors, patterns, problems) of the `lint` key of brain-config.yml: lint.personal_data = the detectors
    turned on (absent = all of PERSONAL_DETECTORS); lint.personal_data_patterns = {name: regex} extra. A regex that
    is invalid, longer than MAX_CONFLICT_PATTERN or with a nested quantifier is a problem naming the pattern (the
    protection of compile_conflict_patterns), never compiled; the others still count."""
    if not lint:
        lint = {}
    if not isinstance(lint, dict):
        return list(PERSONAL_DETECTORS), {}, [f"lint precisa ser um mapa: {one_line(lint)}"]
    problems, given = [], lint.get("personal_data")
    if given is None:
        detectors = list(PERSONAL_DETECTORS)
    else:
        items = [given] if isinstance(given, str) else given if isinstance(given, list) else None
        if items is None:
            items = list(PERSONAL_DETECTORS)
            problems.append(f"lint.personal_data precisa ser uma lista: {one_line(given)} — usando todos")
        names = [str(item).strip() for item in items if str(item).strip()]
        unknown = [name for name in names if name not in PERSONAL_DETECTORS]
        if unknown:
            problems.append(f"lint.personal_data: detector desconhecido {one_line(', '.join(unknown))} — detectores: "
                            f"{', '.join(PERSONAL_DETECTORS)}")
        detectors = [name for name in PERSONAL_DETECTORS if name in names]
    extra = lint.get("personal_data_patterns") or {}
    if not isinstance(extra, dict):
        problems.append(f"lint.personal_data_patterns precisa ser um mapa nome: regex: {one_line(extra)}")
        return detectors, {}, problems
    patterns = {}
    for name, item in extra.items():
        text, label = str(item), f"lint.personal_data_patterns.{one_line(name)}"
        if len(text) > MAX_CONFLICT_PATTERN:
            problems.append(f"{label}: regex com {len(text)} caracteres (limite {MAX_CONFLICT_PATTERN}) — não usado")
        elif nested_quantifier(text):
            problems.append(f"{label}: regex com quantificador aninhado {one_line(text)!r} — como (a+)+, trava a "
                            "busca; não usado")
        else:
            try:
                patterns[str(name)] = re.compile(text)
            except re.error as e:
                problems.append(f"{label}: regex inválido {one_line(text)!r} ({e}) — não usado")
    return detectors, patterns, problems


# ---------------------------------------------------------------- links and search (read only)

def _link_key(target: str) -> str:
    """Comparison key of a link target or a note path: NFC (a name typed in NFC finds a file stored in NFD), "/",
    without a leading "./" or "/" nor ".md", lowercased."""
    key = unicodedata.normalize("NFC", target.strip().replace("\\", "/"))
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


def walk_vault(values: dict):
    """(absolute path, path relative to the vault) of every file, in path order, except .obsidian/, .trash/ (any
    hidden folder) and the layout.templates folder."""
    vault = vault_dir(values)
    templates = posixpath.normpath(str(values["layout"]["templates"]).replace("\\", "/"))
    for root, dirs, files in os.walk(vault):
        base = Path(root).relative_to(vault).as_posix()
        prefix = "" if base == "." else base + "/"
        dirs[:] = sorted(d for d in dirs if not ignored_dir(prefix + d, templates))
        for name in sorted(files):
            yield Path(root) / name, prefix + name


def is_note(rel: str) -> bool:
    return rel.lower().endswith(".md")


def hidden_note(rel: str) -> bool:
    """A .md file whose name starts with ".": Obsidian does not index it, so it is not a note."""
    return is_note(rel) and posixpath.basename(rel).startswith(".")


def walk_notes(values: dict):
    """(absolute path, path relative to the vault) of every .md note of walk_vault, except hidden ones
    (hidden_note)."""
    return ((path, rel) for path, rel in walk_vault(values) if is_note(rel) and not hidden_note(rel))


def scan_vault(config: dict) -> list:
    """Every .md note of the vault of load_config(), in path order, except hidden files, .obsidian/, .trash/ and
    the layout.templates folder. Only reads; the problems of each note are in Note.warnings."""
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


def search(notes: list, query: str, context=None, note_type=None, tag=None, limit=10,
           include_confidential=False) -> list:
    """Notes of the query by score: sum per query term of tf * idf, weighting title 3, tags 2 and body 1.
    Only score > 0, descending; filters by context, frontmatter.type and tag. Confidential notes are left out
    (never counted in the idf either) unless include_confidential."""
    notes = visible_notes(notes, include_confidential)
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
    """Undirected neighborhood of each note: the notes it links to and the ones that link to it. The index may know
    more notes than `notes` (the confidential ones left out): a link to one of them is not an edge."""
    graph = {note.path: set() for note in notes}
    for note in notes:
        for target in note.links:
            dest = index.resolve(target)
            if dest and dest != note.path and dest in graph:
                graph[note.path].add(dest)
                graph[dest].add(note.path)
    return graph


def generated_paths(values=None) -> set:
    """_link_key of the generated index.md and log.md (layout.index and layout.log; the defaults when values is
    None): "Index.md" or a name in NFD is still the generated file."""
    layout = values["layout"] if values else {"index": "index.md", "log": "log.md"}
    return {_link_key(path) for path in layout_paths(layout, LAYOUT_FILES)}


def generated_notes(paths, values=None) -> set:
    """The paths (of notes) that are the generated index.md or log.md, compared with _link_key."""
    keys = generated_paths(values)
    return {path for path in paths if _link_key(path) in keys}


def moc_notes(paths, values=None) -> set:
    """The paths (of notes) under layout.mocs ("mocs" when values is None), compared with _link_key."""
    folder = _link_key(posixpath.normpath(str(values["layout"]["mocs"] if values else "mocs").replace("\\", "/")))
    return {path for path in paths if _link_key(path).startswith(folder + "/")}


def related(notes: list, note=None, text=None, limit=10, values=None, include_confidential=False) -> list:
    """Notes like `note` (a Note.path) or like a free `text`, by 0.5 * TF-IDF cosine + 0.2 * tag Jaccard
    + 0.1 * same context + 0.2 * neighborhood (1 direct link, 0.5 two hops). Excludes the note itself and the
    generated index.md and log.md (never results nor a path between neighbors); descending; each result says why
    (reasons). Confidential notes are neither results nor neighbors unless include_confidential; a confidential
    `note` without it = BrainError (exit 2)."""
    index = LinkIndex(n.path for n in notes)
    if note is not None:
        ref = next((n for n in notes if n.path == note), None)
        if ref is None:
            raise BrainError(f"nota não encontrada: {note}")
        if not include_confidential and is_confidential(ref):
            raise BrainError(CONFIDENTIAL_REFUSED)
    notes = visible_notes(notes, include_confidential)
    generated = generated_notes((n.path for n in notes), values)
    graph = link_graph(notes, index)
    if note is not None:
        direct = graph[ref.path] - generated
    else:
        ref = parse_note("", text or "")
        direct = {index.resolve(target) for target in ref.links} & graph.keys() - generated
    two_hops = set().union(*(graph[p] for p in direct)) - direct - {ref.path} - generated if direct else set()

    df = Counter()
    for n in notes:
        df.update(n.terms.keys())
    idf = {term: inverse_frequency(count, len(notes)) for term, count in df.items()}
    ref_vector = {t: tf * idf[t] for t, tf in ref.terms.items() if t in idf}
    ref_norm = math.sqrt(sum(w * w for w in ref_vector.values()))
    ref_tags = set(ref.tags)

    scored = []
    for n in notes:
        if n.path == ref.path or n.path in generated:
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


def note_links(notes: list, path: str, index: LinkIndex, include_confidential=False) -> dict:
    """Outgoing links of the note at `path` (resolved or None), its backlinks and its broken targets. Without
    include_confidential a confidential note is neither an outgoing link nor a backlink (nor broken: it exists),
    "confidential_omitted" counts them (distinct notes), and a confidential `path` = BrainError (exit 2)."""
    note = next(n for n in notes if n.path == path)
    hidden = set() if include_confidential else confidential_paths(notes)
    if path in hidden:
        raise BrainError(CONFIDENTIAL_REFUSED)
    resolved = [{"target": target, "path": index.resolve(target)} for target in note.links]
    outgoing = [item for item in resolved if item["path"] not in hidden]
    linking = [n.path for n in notes if n.path != path and any(index.resolve(target) == path for target in n.links)]
    backlinks = sorted(p for p in linking if p not in hidden)
    omitted = {item["path"] for item in resolved if item["path"] in hidden} | (set(linking) & hidden)
    return {"outgoing": outgoing, "backlinks": backlinks,
            "broken": [item["target"] for item in outgoing if item["path"] is None],
            "confidential_omitted": len(omitted)}


# ---------------------------------------------------------------- query: context package (pure)

def moc_path(context: str, values=None) -> str:
    """Path of the MOC of a context: <layout.mocs>/<context>.md ("mocs" when values is None)."""
    mocs = values["layout"]["mocs"] if values else "mocs"
    return f"{posixpath.normpath(str(mocs).replace(chr(92), '/'))}/{context}.md"


def neighbors(seeds: list, graph: dict, hops: int, blocked=()) -> dict:
    """Distance (1..hops) of every note reached from the seeds by the undirected link graph (breadth first); the
    blocked notes are neither reached nor walked through."""
    seen, frontier, found = set(seeds) | set(blocked), list(seeds), {}
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


def context_picks(notes: list, index: LinkIndex, query: str, context, hops: int, limit: int, values) -> list:
    """[(path, reason)] of build_context in the contract order (MOC, search results, link neighbors); `notes` are
    the ones that may be picked and `index` resolves links over the whole vault."""
    by_path = {note.path: note for note in notes}
    results = search(notes, query, context=context, limit=limit, include_confidential=True)
    moc = moc_path(context, values) if context and results else None
    picked = [(moc, "moc")] if moc in by_path else []  # (path, reason) in the contract order
    generated = generated_notes(by_path, values)
    seeds = [r["path"] for r in results if r["path"] != moc and r["path"] not in generated]
    picked += [(r["path"], f"search:{r['score']}") for r in results if r["path"] != moc]
    blocked = ([moc] if moc else []) + sorted(generated)  # the MOC comes first but is never walked through
    found = neighbors(seeds, link_graph(notes, index), hops, blocked) if seeds and hops > 0 else {}
    picked += [(path, f"link:{distance}")
               for path, distance in sorted(found.items(), key=lambda item: (item[1], by_path[item[0]].title.lower(),
                                                                              item[0]))]
    return picked


def build_context(notes: list, query: str, context=None, hops=1, limit=8, max_chars=40000, values=None,
                  include_confidential=False) -> dict:
    """Package of notes that answer the query: the MOC of `context` (when given), the search results by score and
    their link neighbors (outgoing links and backlinks) up to `hops` steps, by distance and title; no note repeats.
    The MOC is never walked through (it would bring the whole context): notes reached only through it stay out;
    without `context` the MOC is an ordinary note. The generated index.md and log.md may be search results but are
    never walked through either. In that priority order each note goes in whole when it still
    fits max_chars (sum of len(content)); one that does not fit goes to "omitted" (path, title, reason) and the
    next ones are still tried. "broken" lists the broken links of the notes in the package. Nothing found by
    the search = empty package (no MOC alone). Without include_confidential the confidential notes are neither
    picked nor walked through (a link to one is not broken) and "confidential_omitted" counts the distinct ones that
    the package would have picked with them."""
    by_path = {note.path: note for note in notes}
    index = LinkIndex(by_path)
    shown = visible_notes(notes, include_confidential)
    picked = context_picks(shown, index, query, context, hops, limit, values)
    hidden = by_path.keys() - {note.path for note in shown}
    every = context_picks(notes, index, query, context, hops, limit, values) if hidden else []
    package, omitted, broken, size = [], [], [], 0
    for path, reason in picked:
        note = by_path[path]
        content = note.text or ""
        if size + len(content) <= max_chars:
            size += len(content)
            package.append({"path": path, "title": note.title, "reason": reason, "content": content})
        else:
            omitted.append({"path": path, "title": note.title, "reason": reason})
        broken += [{"note": path, "target": target} for target in note.links if index.resolve(target) is None]
    return {"query": query, "notes": package, "omitted": omitted, "broken": broken,
            "confidential_omitted": len({path for path, _ in every if path in hidden})}


# ---------------------------------------------------------------- export: NotebookLM package (pure; SPEC-0024)

def flatten_links(text: str, hidden=None) -> str:
    """Wikilinks as plain text ([[Nota]] -> "Nota", [[Nota|apelido]] -> "apelido", [[Nota#seção]] -> "Nota >
    seção") and attachment embeds as "(anexo: nome)" (![[grafico.png]]); code (fenced blocks of fenced_lines and
    inline `code` or ``code``) and the rest of the text do not change. hidden(page) True = the link (alias and
    section included) becomes CONFIDENTIAL_LINK: the export never writes the title of a confidential note."""
    def plain(match) -> str:
        target, _, alias = match.group(1).partition("|")
        target = target.rstrip("\\").strip()
        page, _, section = target.partition("#")
        page, section = page.strip(), section.strip()
        if hidden is not None and page and hidden(page):
            return CONFIDENTIAL_LINK
        name = posixpath.basename(page)
        if match.group(0).startswith("!") and posixpath.splitext(name)[1].lower() not in ("", ".md"):
            return f"(anexo: {name})"
        if alias.strip():
            return alias.strip()
        return f"{page} > {section}" if page and section else page or section

    def outside_code(line: str) -> str:
        parts, start = [], 0
        for code in INLINE_CODE_RE.finditer(line):  # inline code (any backtick run) is kept as is
            parts += [WIKILINK_RE.sub(plain, line[start:code.start()]), code.group(0)]
            start = code.end()
        return "".join(parts) + WIKILINK_RE.sub(plain, line[start:])
    return "".join(line if code else outside_code(line) for line, code in fenced_lines(text.splitlines(True)))


def export_notes(notes: list, moc: str, hops: int, values=None, include_confidential=False) -> list:
    """[(path, origin)] of the NotebookLM package of the MOC at `moc`: the MOC, the notes it cites (in its order)
    and their link neighbors up to `hops` steps, by distance and title (neighbors of build_context). The MOC is
    never walked through, nor any other MOC of layout.mocs, nor the generated index.md and log.md: notes reached
    only through them stay out. Confidential notes are never cited nor walked through (include_confidential only
    serves to count what was left out)."""
    by_path = {note.path: note for note in notes}
    index = LinkIndex(by_path)
    shown = visible_notes(notes, include_confidential)
    hidden = by_path.keys() - {note.path for note in shown}
    blocked = [moc] + sorted((generated_notes(by_path, values) | moc_notes(by_path, values)) - {moc})
    cited = unique(path for path in (index.resolve(target) for target in by_path[moc].links)
                   if path and path not in blocked and path not in hidden)
    found = neighbors(cited, link_graph(shown, index), hops, blocked) if cited and hops > 0 else {}
    picked = [(moc, "MOC")] + [(path, "citada pelo MOC") for path in cited]
    picked += [(path, f"link:{distance}")
               for path, distance in sorted(found.items(), key=lambda item: (item[1], by_path[item[0]].title.lower(),
                                                                              item[0]))]
    return picked


def export_text(note: Note, hidden=None) -> str:
    """The note for the NotebookLM: the title as the first line (no frontmatter), the body without the
    brain:begin/end markers and with flatten_links (a link to a confidential note = CONFIDENTIAL_LINK)."""
    lines = [line for line in (note.body or "").splitlines() if not re.match(r"^\s*<!-- brain:(?:begin|end) ", line)]
    body = flatten_links("\n".join(lines), hidden).strip()
    title = flatten_links(note.title)
    first = body.splitlines()[0] if body else ""
    heading = HEADING_RE.match(first)
    if not (heading and heading.group(1).strip() == title):
        body = f"# {title}\n\n{body}" if body else f"# {title}"
    return body + "\n"


def export_key(name: str) -> str:
    """How the file system (APFS) compares two exported names: NFC and casefold ("Straße" = "STRASSE")."""
    return unicodedata.normalize("NFC", name).casefold()


def export_name(title: str, path: str, taken: set) -> str:
    """File name of an exported note: the sanitized title (else the vault file name), with " (2)", " (3)"... when
    the name is already taken (by another note, sources.md or combined.md); taken holds export_key of the names."""
    try:
        stem = sanitize_title(title)
    except BrainError:
        stem = posixpath.splitext(posixpath.basename(path))[0]
    name, n = f"{stem}.md", 1
    while export_key(name) in taken:
        n += 1
        name = f"{stem} ({n}).md"
    taken.add(export_key(name))
    return name


def export_package(notes: list, moc: str, hops: int, values=None) -> dict:
    """{"notes": [{"path", "title", "origin", "file"}], "files": {name: text}, "confidential_omitted": N}: one .md
    per note of export_notes, sources.md (where each one came from) and combined.md (every note in one file;
    dropped without --combined). A confidential note never goes in (N = the distinct ones left out); a
    confidential MOC = BrainError (exit 2)."""
    by_path = {note.path: note for note in notes}
    if is_confidential(by_path[moc]):
        raise BrainError("MOC confidencial — o export-notebooklm nunca exporta item confidencial")
    hidden = confidential_paths(notes)
    every = export_notes(notes, moc, hops, values, include_confidential=True) if hidden else []
    index = LinkIndex(by_path)
    secret = (lambda page: index.resolve(page) in hidden) if hidden else None
    taken = {export_key(name) for name in EXPORT_EXTRA}
    items, files = [], {}
    for path, origin in export_notes(notes, moc, hops, values):
        note = by_path[path]
        name = export_name(note.title, path, taken)
        files[name] = export_text(note, secret)
        items.append({"path": path, "title": note.title, "origin": origin, "file": name})
    moc_title = flatten_links(by_path[moc].title)
    lines = [f"# Fontes — {moc_title}", "", f"Pacote para o NotebookLM exportado do MOC {moc} (hops: {hops}).", ""]
    lines += [f"- {item['file']} — {flatten_links(item['title'])} — {item['path']} ({item['origin']})"
              for item in items]
    files["sources.md"] = "\n".join(lines) + "\n"
    files["combined.md"] = (f"# {moc_title} — todas as notas\n\n"
                            + "\n---\n\n".join(files[item["file"]] for item in items))
    return {"notes": items, "files": files, "confidential_omitted": len({path for path, _ in every if path in hidden})}


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


def slugify(title: str, fallback: str = "fonte") -> str:
    """Lowercase ASCII slug of a title for the name of a source note ("Aula 1: Limites" -> "aula-1-limites")."""
    slug = re.sub(r"[^a-z0-9]+", "-", fold(title)).strip("-")
    return slug[:SLUG_MAX].strip("-") or fallback


def kebab(name: str) -> str:
    """Folder name in kebab-case: lowercase without accents, each run outside [a-z0-9] becomes "-", no dash at the
    ends; only symbols = "" ("Cálculo_II" -> "calculo-ii")."""
    return re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-")


def is_kebab(name: str) -> bool:
    return bool(name) and kebab(name) == name


def kebab_name(name: str) -> str:
    """Context name passed through kebab: changed = notice on stdout; empty after the change = BrainError (exit 2)."""
    adjusted = kebab(name)
    if not adjusted:
        raise BrainError(f"nome de contexto inválido: {name} (o kebab-case precisa de letras a–z ou dígitos 0–9; "
                         "nomes só com outros alfabetos não são aceitos)")
    if adjusted != name:
        print(f"nome ajustado para kebab-case: `{name}` → `{adjusted}`")
    return adjusted


def layout_folders(shared: dict) -> list:
    """Folders of the vault's layout and para (vault-relative, as configured)."""
    folders = [shared["layout"][key] for key in LAYOUT_DIRS] + [shared["para"][key] for key in PARA_KEYS]
    return [folder for folder in folders if isinstance(folder, str) and folder]


def kebab_folder(vault: str, folder: str, mapped=()) -> str:
    """Context folder relative to the vault with each part passed through kebab; the leading parts that match a
    folder of `mapped` (layout/para, case-insensitive) keep the configured spelling; changed = notice on stdout; a
    part that becomes empty = BrainError (exit 2)."""
    rel = relative_folder(vault, folder)
    rel_parts = rel.split("/")
    kept = []
    for candidate in mapped:
        parts = candidate.replace("\\", "/").strip("/").split("/")
        if len(kept) < len(parts) <= len(rel_parts) and [p.lower() for p in parts] == [
                p.lower() for p in rel_parts[:len(parts)]]:
            kept = parts
    parts = kept + [kebab(part) for part in rel_parts[len(kept):]]
    if not all(parts):
        raise BrainError(f"pasta inválida: {folder} (parte sem letras a–z nem dígitos 0–9 para o kebab-case)")
    adjusted = "/".join(parts)
    if adjusted != rel:
        print(f"nome ajustado para kebab-case: `{rel}` → `{adjusted}`")
    return adjusted


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


def render_source_note(title: str, date: str, context, file_rel, url, extracted: str, opaque=None) -> str:
    """Source note of ingest: frontmatter type: source, title, context, created, tags, source_url or files, and
    the extracted text (or _(pending)_) under "## Extracted text". opaque = (size, sha256) of a confidential file
    (ingest --confidential): confidential: true, size and sha256, and NOT_EXTRACTED in place of any text."""
    frontmatter = {"type": "source", "title": title}
    if context:
        frontmatter["context"] = context
    frontmatter.update(created=date, tags=[])
    if url:
        frontmatter["source_url"] = url
    else:
        frontmatter["files"] = [file_rel]
    if opaque is not None:
        frontmatter.update(confidential="true", size=str(opaque[0]), sha256=opaque[1])
        extracted = NOT_EXTRACTED
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
    """What index needs of a note: path, title, type, context, created (AAAA-MM-DD or "") and whether it is
    confidential (then it is listed neither in a MOC nor in index.md)."""
    __slots__ = ("confidential", "context", "created", "note_type", "path", "title")

    def __init__(self, path, title, note_type, context, created, confidential=False):
        self.path, self.title, self.note_type, self.context, self.created = path, title, note_type, context, created
        self.confidential = confidential


def index_entry(rel: str, text: str, contexts) -> IndexEntry:
    """IndexEntry of a note (only the frontmatter and the title are read: no terms, so index stays fast)."""
    frontmatter, body, _ = read_frontmatter(text)
    title = note_title(rel, frontmatter, "" if isinstance(frontmatter.get("title"), str) else prose(body))
    note_type = frontmatter.get("type")
    return IndexEntry(rel, title, note_type.strip() if isinstance(note_type, str) else "",
                      note_context(rel, frontmatter, contexts), created_date(frontmatter.get("created")),
                      marked_confidential(frontmatter, text))


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


def parse_contexts(values, vault: str, mapped=()) -> dict:
    """--context nome=pasta[:título] → {nome: {folder, title}}; name and folder in kebab-case (leading parts mapped
    in the layout/para kept), title as typed; two names with the same kebab = BrainError (exit 2)."""
    contexts, origin = {}, {}
    for name, rest in parse_pairs(values, "--context"):
        folder, _, title = rest.partition(":")
        key = kebab_name(name)
        if key in contexts:
            raise BrainError(f"contextos com o mesmo nome em kebab-case: {origin[key]} e {name} → {key}")
        origin[key] = name
        contexts[key] = {"folder": kebab_folder(vault, folder, mapped), "title": title.strip() or name}
    return contexts


def check_context_name(name: str):
    if not CONTEXT_NAME_RE.match(name):
        raise BrainError(f"nome de contexto inválido: {name} (use letras, números, '_' ou '-')")


def is_empty_vault(folder: Path) -> bool:
    """Empty for init: nothing but OS_METADATA and the `.obsidian/` the Obsidian app creates with a new vault."""
    return all(e.name in OS_METADATA or (e.name == ".obsidian" and e.is_dir()) for e in folder.iterdir())


def check_user_files(vault: Path, layout: dict):
    """index.md and log.md of the user (without the brain:begin markers) are never adopted nor appended to."""
    for key in ("log", "index"):
        path = vault / layout[key]
        if path.is_file() and BRAIN_MARKER not in path.read_text(encoding="utf-8", errors="replace"):
            raise BrainError(f"{layout[key]} já existe — use --map {key}=<outro>")


def cmd_init(args, config_home=None) -> int:
    vault_s, files_s = absolute(args.vault), absolute(args.files)
    error = validate_init_args(vault_s, files_s, args.provider)
    if error is None and inside_on_disk(files_s, vault_s):
        error = "files precisa ficar fora do vault"
    if error:
        raise BrainError(error)
    vault, local_path = Path(vault_s), local_config_path(config_home)
    shared_path = shared_config_path(vault_s)
    local_text = render_local_config(vault_s, files_s, args.provider, local_backup_targets(local_path))

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
    mapped = layout_folders(parse_yaml(render_brain_config(vault_s, layout=layout)))
    rendered = render_brain_config(vault_s, layout=layout, contexts=parse_contexts(args.context, vault_s, mapped))
    backup = None
    if shared_path.exists():
        if read_yaml(shared_path) == parse_yaml(rendered):
            write_local_config(local_path, local_text)
            print(f"Vault já configurado: {vault_s}")
            print(f"Configuração local gravada em {local_path}")
            return 0
        if not args.force:
            raise BrainError("brain-config.yml já existe — use --join ou --force")
    elif not args.adopt and vault.is_dir() and not is_empty_vault(vault):
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
    for warning in config.get("warnings", []):
        print(f"aviso: {warning['message']}", file=sys.stderr)
    print(f"second-brain {BRAIN_VERSION} — configuração local: {local_config_path(config_home)}")
    for key in ("vault", "files", "provider", "version", "language", "inbox_stale_days"):
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
    name = kebab_name(args.name)
    contexts = values["contexts"] if isinstance(values["contexts"], dict) else {}
    stored = next((key for key in contexts if key == name or kebab(str(key)) == name), None)
    if stored is not None:
        raise BrainError(f"contexto já existe: {stored}" + (f" (mesmo kebab-case de {args.name})"
                                                             if stored != args.name else ""))
    item = {"folder": kebab_folder(str(vault), args.folder, layout_folders(values)), "title": args.title or args.name}
    text = add_context_text(shared_path.read_text(encoding="utf-8"), name, item)
    if parse_yaml(text).get("contexts", {}).get(name) != item:
        raise BrainError(f"não consegui acrescentar o contexto em {shared_path}", 1)
    shared_path.write_text(text, encoding="utf-8")
    layout = values["layout"]
    created = create_context(vault, layout, name, item)
    append_log(vault, layout, "context add", f"{name} → {item['folder']}"
               + (f" (criado: {', '.join(created)})" if created else ""))
    print(f"Contexto {name} → {item['folder']} ({item['title']})")
    for path in created:
        print(f"  criado: {path}")
    return 0


def doctor_items(config: dict, local_path: Path) -> list:
    """(status, item, detail) for each check; reads the disk and runs only the check of each processor."""
    values, rows = config["values"], [("OK", "configuração local", str(local_path))]
    vault, files = values["vault"], values["files"]
    vault_ok = bool(vault) and Path(vault).is_dir()
    if vault_ok:
        rows.append(("OK", "vault", vault))
    else:
        rows.append(("ERRO", "vault", (f"pasta não encontrada: {vault or '(sem vault na configuração local)'} — "
                                       "o app do provedor já sincronizou? (references/providers.md)")))
    if files and Path(files).is_dir():
        inside = vault and inside_on_disk(files, vault)
        rows.append(("ERRO", "files", "precisa ficar fora do vault") if inside else ("OK", "files", files))
    else:
        rows.append(("ERRO", "files", f"pasta não encontrada: {files or '(sem files na configuração local)'}"))
    rows += kebab_path_items("vault", vault) + kebab_path_items("files", files)
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
    rows += [("AVISO", warning["key"], warning["message"]) for warning in config.get("warnings", [])]

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
        rows += kebab_context_items(str(name), folder, f"contexts.{name}.folder" in problems)
    rows += processor_items(values["processors"])
    rows.append(lint_item(values, problems))
    rows.append(confidential_item(values, problems))
    rows += backup_items(values)
    return rows + provider_items(values)


def kebab_path_items(key: str, path: str) -> list:
    """AVISO for the folder (and the folder that holds it) of the vault or of files outside kebab-case; the paths
    are the user's choice, so nothing is renamed."""
    if not path:
        return []
    pure = _pure(path)
    rows = []
    for label, part in ((key, pure.name), (f"{key} (pasta-mãe)", pure.parent.name)):
        if part and not is_kebab(part):
            detail = (f"pasta fora do kebab-case: {part} (sugestão: {kebab(part) or '?'}) — "
                      "renomeie no provedor se quiser; o brain.py não renomeia")
            rows.append(("AVISO", label, detail))
    return rows


def kebab_context_items(name: str, folder: str, outside: bool) -> list:
    """AVISO for a stored context whose name or folder is outside kebab-case; nothing is renamed."""
    rows = []
    if CONTEXT_NAME_RE.match(name) and not is_kebab(name):
        rows.append(("AVISO", f"contexto {name}", f"nome fora do kebab-case: {name} (sugestão: {kebab(name) or '?'})"))
    parts = posixpath.normpath(str(folder)).split("/") if folder else []
    if parts and not outside and not all(is_kebab(part) for part in parts):
        suggestion = "/".join(kebab(part) or "?" for part in parts)
        rows.append(("AVISO", f"contexto {name}", f"pasta fora do kebab-case: {folder} (sugestão: {suggestion})"))
    return rows


def processor_items(processors) -> list:
    """"OK|AVISO processor <kind> — <executable> (<first line of the check>)": the check (or "<executable>
    --version") runs through run_processor; an executable missing from the PATH is not run."""
    if not isinstance(processors, dict) or not processors:
        return [("OK", "processadores", "nenhum configurado")]
    rows = []
    for kind in processors:
        item = processor_of(kind, processors)
        executable = executable_of(str(item.get("command", ""))) if item else ""
        found = shutil.which(executable) if executable else None
        if not executable:
            rows.append(("AVISO", f"processor {kind}", "sem command"))
        elif not found:
            rows.append(("AVISO", f"processor {kind}", f"{executable} (executável não encontrado no PATH)"))
        else:
            try:
                rows.append(("OK", f"processor {kind}", f"{found} ({run_processor(kind, '', processors, check=True)})"))
            except ProcessorError as e:
                rows.append(("AVISO", f"processor {kind}", f"{found} (checagem falhou: {e.reason})"))
    return rows


def provider_items(values: dict) -> list:
    provider = values["provider"]
    if provider not in PROVIDERS:
        return [("ERRO", "provider", f"inválido: {provider or '(vazio)'} — use um de: {', '.join(PROVIDERS)}")]
    status, note = PROVIDER_NOTES[provider]
    return [(status, f"provider {provider}", note)]


def confidential_item(values: dict, problems: dict) -> tuple:
    """The doctor line of confidential items: "OK confidential — N notas confidenciais" (only the number: never a
    title nor a path)."""
    if problems:
        return ("AVISO", "confidential", "não conferido (brain-config.yml com valores fora do vault)")
    count = 0
    try:
        for path, _ in walk_notes(values):
            text = path.read_bytes().decode("utf-8-sig", errors="replace")
            if CONFIDENTIAL_LINE_RE.search(frontmatter_block(text)):  # only then the YAML is parsed
                count += marked_confidential(read_frontmatter(text)[0], text)
    except (BrainError, OSError) as e:
        return ("AVISO", "confidential", f"não conferido: {e.strerror if isinstance(e, OSError) else e}")
    return ("OK", "confidential", f"{count} notas confidenciais")


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


def load_vault(config_home=None):
    """(values, notes, warnings) of the configured vault; not configured locally = BrainError(NOT_CONFIGURED, 3)."""
    config = load_config(config_home)
    notes = scan_vault(config)
    return config["values"], notes, [warning for note in notes for warning in note.warnings]


def load_notes(config_home=None):
    """(notes, warnings) of the configured vault (load_vault without the configuration values)."""
    return load_vault(config_home)[1:]


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


def has_confidential(notes: list) -> bool:
    return any(is_confidential(note) for note in notes)


def confidential_omitted(every: list, notes: list) -> int:
    """How many distinct confidential notes are in `every`, the output the command would give with
    --include-confidential (the ones left out of the output without it)."""
    return len({item["path"] for item in every} & confidential_paths(notes))


def print_confidential_omitted(omitted: int):
    if omitted:
        print(f"({omitted} nota(s) confidencial(is) fora da lista — {INCLUDE_CONFIDENTIAL} só a pedido da pessoa)")


def cmd_search(args, config_home=None) -> int:
    check_limit(args.limit)
    query = " ".join(args.query)
    notes, warnings = load_notes(config_home)
    include = args.include_confidential
    results = search(notes, query, context=args.context, note_type=args.type, tag=args.tag, limit=args.limit,
                     include_confidential=include)
    omitted = 0 if include or not has_confidential(notes) else confidential_omitted(
        search(notes, query, context=args.context, note_type=args.type, tag=args.tag, limit=args.limit,
               include_confidential=True), notes)
    if args.json:
        print_json({"query": query, "results": results, "warnings": warnings, "confidential_omitted": omitted})
        return 0
    print_warnings(warnings)
    if not results:
        print(f"Nenhuma nota encontrada para: {query}")
    for result in results:
        print(f"{result['score']:.2f}  {result['path']}  — {result['title']}")
        if result["snippet"]:
            print(f"    {result['snippet']}")
    print_confidential_omitted(omitted)
    return 0


def cmd_related(args, config_home=None) -> int:
    check_limit(args.limit)
    values, notes, warnings = load_vault(config_home)
    include = args.include_confidential
    path = find_note(args.note, LinkIndex(n.path for n in notes)) if args.note is not None else None
    results = related(notes, note=path, text=args.text, limit=args.limit, values=values,
                      include_confidential=include)
    omitted = 0 if include or not has_confidential(notes) else confidential_omitted(
        related(notes, note=path, text=args.text, limit=args.limit, values=values, include_confidential=True), notes)
    if args.json:
        print_json({"results": results, "warnings": warnings, "confidential_omitted": omitted})
        return 0
    print_warnings(warnings)
    if not results:
        print("Nenhuma nota relacionada encontrada.")
    for result in results:
        print(f"{result['score']:.2f}  {result['path']}  — {result['title']}")
        print(f"    {'; '.join(result['reasons'])}")
    print_confidential_omitted(omitted)
    return 0


def cmd_links(args, config_home=None) -> int:
    notes, warnings = load_notes(config_home)
    index = LinkIndex(n.path for n in notes)
    path = find_note(args.note, index)
    data = note_links(notes, path, index, include_confidential=args.include_confidential)
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
    print_confidential_omitted(data["confidential_omitted"])
    return 0


def cmd_context(args, config_home=None) -> int:
    check_limit(args.limit)
    if not 0 <= args.hops <= MAX_HOPS:
        raise BrainError(f"--hops precisa estar entre 0 e {MAX_HOPS}: {args.hops}")
    if args.max_chars < 1:
        raise BrainError(f"--max-chars precisa ser maior que zero: {args.max_chars}")
    query = " ".join(args.query)
    values, notes, warnings = load_vault(config_home)
    data = build_context(notes, query, context=args.context, hops=args.hops, limit=args.limit,
                         max_chars=args.max_chars, values=values, include_confidential=args.include_confidential)
    if args.json:
        print_json(dict(data, warnings=warnings))
        return 0
    print_warnings(warnings)
    if not data["notes"] and not data["omitted"]:
        print(f"Nenhuma nota encontrada para: {query}")
        print_confidential_omitted(data["confidential_omitted"])
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
    print_confidential_omitted(data["confidential_omitted"])
    return 0


def find_moc(ref: str, values: dict, index: LinkIndex) -> str:
    """Path of the MOC named by a context name (<layout.mocs>/<name>.md) or by a note path or name; the generated
    index.md or log.md = BrainError (code 2): they list the whole vault and are not a MOC."""
    path = index.resolve(moc_path(ref, values)) if CONTEXT_NAME_RE.match(ref) else None
    path = path or index.resolve(ref)
    if path is None:
        raise BrainError(f"MOC não encontrado: {ref}")
    if generated_notes([path], values):
        raise BrainError(f"{one_line(path)} não é um MOC: index.md e log.md são gerados e listam o vault inteiro "
                         "— use o MOC de um contexto")
    return path


def export_folder(out: str, vault: Path) -> Path:
    """--out resolved: inside the vault or already with files = BrainError(code 2), before anything is written."""
    folder = Path(out).expanduser().resolve()
    if inside_on_disk(folder, vault):
        raise BrainError(f"--out dentro do vault: {out} — o export-notebooklm não escreve no vault")
    if folder.exists() and not folder.is_dir():
        raise BrainError(f"--out não é uma pasta: {out}")
    if folder.is_dir() and any(entry.name not in OS_METADATA for entry in folder.iterdir()):
        raise BrainError(f"--out já tem arquivos: {out} — o export-notebooklm nunca sobrescreve; use uma pasta vazia")
    return folder


def export_staging(folder: Path) -> Path:
    """A new hidden folder next to --out (same file system, so the final move is a rename)."""
    folder.parent.mkdir(parents=True, exist_ok=True)
    while True:
        staging = folder.parent / f".{folder.name}.brain-{os.urandom(4).hex()}"
        try:
            staging.mkdir()
            return staging
        except FileExistsError:
            continue


def write_export(folder: Path, files: dict):
    """Write the package into a temporary folder next to --out and move it into --out at the end: a failure
    leaves nothing in --out (an existing empty --out stays usable) = BrainError (code 1), without a traceback. Any
    other exception (KeyboardInterrupt included) cleans up the same way and propagates; only a SIGKILL can leave the
    hidden folder behind."""
    staging, moved = None, []
    try:
        staging = export_staging(folder)
        for name, text in files.items():  # exclusive create inside a new folder: nothing is overwritten
            with open(staging / name, "x", encoding="utf-8") as handle:
                handle.write(text)
        if folder.is_dir():  # empty, or only OS metadata (export_folder): move each file
            for name in files:
                if (folder / name).exists():
                    raise FileExistsError(errno.EEXIST, "já existe", str(folder / name))
                os.replace(staging / name, folder / name)
                moved.append(folder / name)
            staging.rmdir()
        else:
            os.replace(staging, folder)
    except BaseException as e:
        for path in moved:
            with contextlib.suppress(OSError):
                path.unlink()
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        if not isinstance(e, OSError):
            raise
        where = Path(os.fsdecode(e.filename)).name if e.filename else folder.name
        raise BrainError(f"não consegui gravar {one_line(str(where))} em {one_line(str(folder))}: "
                         f"{e.strerror or e} — nada ficou em --out", 1) from e


def cmd_export_notebooklm(args, config_home=None) -> int:
    if not 0 <= args.hops <= MAX_HOPS:
        raise BrainError(f"--hops precisa estar entre 0 e {MAX_HOPS}: {args.hops}")
    values, notes, warnings = load_vault(config_home)
    folder = export_folder(args.out, vault_dir(values))
    moc = find_moc(args.moc, values, LinkIndex(note.path for note in notes))
    data = export_package(notes, moc, args.hops, values)
    files = {name: text for name, text in data["files"].items() if args.combined or name != "combined.md"}
    write_export(folder, files)
    if args.json:
        print_json({"moc": moc, "out": str(folder), "notes": data["notes"], "files": list(files),
                    "warnings": warnings, "confidential_omitted": data["confidential_omitted"]})
        return 0
    print_warnings(warnings)
    print(f"Pacote do NotebookLM: {len(data['notes'])} notas de {moc} em {one_line(str(folder))}")
    for item in data["notes"]:
        print(f"  {item['file']} — {item['path']} ({item['origin']})")
    print(f"  {', '.join(name for name in files if name in EXPORT_EXTRA)}")
    if data["confidential_omitted"]:
        print(f"  ({data['confidential_omitted']} nota(s) confidencial(is) fora do pacote: nunca são exportadas)")
    print("Suba os arquivos como fontes no NotebookLM (references/notebooklm.md).")
    return 0


# ---------------------------------------------------------------- backup and restore (SPEC-0051, ADR-0015)

def backup_name(with_files: bool = False, clock=None) -> str:
    """"second-brain-AAAA-MM-DD-HHMMSS[-files].zip" with the time of clock() (None = datetime.now). Pure."""
    stamp = (clock or dt.datetime.now)().strftime(BACKUP_STAMP)
    return f"second-brain-{stamp}{'-files' if with_files else ''}.zip"


def backup_moment(name: str):
    """datetime of the stamp of a backup name, or None when the name is not of the pattern."""
    match = BACKUP_NAME_RE.match(name)
    if not match:
        return None
    try:
        return dt.datetime.strptime(match.group(1), BACKUP_STAMP)
    except ValueError:
        return None


def backup_names(folder: Path) -> list:
    """Names of the pattern in folder (files only), from the newest to the oldest stamp; OSError propagates."""
    names = [entry.name for entry in os.scandir(folder)
             if backup_moment(entry.name) and entry.is_file(follow_symlinks=False)]
    return sorted(names, key=lambda name: (backup_moment(name), name), reverse=True)


def rotate_backups(folder, keep: int = BACKUP_DEFAULTS["keep"], new=None, discard=None) -> list:
    """The only removal of brain.py outside the closed cleanup list (ADR-0015). Returns the names removed.

    Rotation: in folder (a backup target, never inside the vault nor files), only the names of BACKUP_NAME_RE count,
    each kind (with and without -files) apart; the oldest beyond `keep` (at least 1) are removed, and `new` (the zip
    this backup just wrote and verified) never is. Every other file of the folder stays.
    discard: the "<name>.partial" this backup created and could not finish: that file alone is removed, and nothing
    is rotated (the call that failed never costs an older backup)."""
    folder = Path(folder)
    if discard is not None:
        discard = Path(discard)
        name = discard.name
        if (discard.parent == folder and name.endswith(BACKUP_PARTIAL)
                and backup_moment(name[:-len(BACKUP_PARTIAL)]) and discard.is_file()):
            discard.unlink()
            return [name]
        return []
    keep = max(1, int(keep))
    removed = []
    for with_files in (False, True):
        names = [name for name in backup_names(folder) if bool(BACKUP_NAME_RE.match(name).group(2)) == with_files]
        for name in names[keep:]:
            if name != new:
                (folder / name).unlink()
                removed.append(name)
    return sorted(removed)


def tree_files(root: Path):
    """(absolute path, posix path relative to root) of every file below root, in path order (hidden folders
    included: a backup keeps .obsidian/ and .trash/). Left out: what is not a regular file (a broken link, a socket,
    a pipe) and a symbolic link that points outside root (its content is not the vault's); folder links are not
    followed (os.walk)."""
    real_root = Path(root).resolve()
    for base, dirs, files in os.walk(root):
        dirs.sort()
        rel = Path(base).relative_to(root).as_posix()
        for name in sorted(files):
            path = Path(base) / name
            if not path.is_file():
                continue
            if path.is_symlink() and not is_inside(str(path.resolve()), str(real_root)):
                continue
            yield path, name if rel == "." else f"{rel}/{name}"


def build_manifest(vault, files=None, clock=None, skipped=None) -> dict:
    """brain-backup.json of a backup: brain_version, created, with_files (files given) and entries, the sha256 of
    each "vault/<rel>" and "files/<rel>". Paths are relative: no folder of this machine goes into the zip.
    A file that cannot be read stays out of the entries; its "vault/<rel>" goes into `skipped` (a list) when given,
    else the OSError propagates."""
    entries = {}
    for root, folder in (("vault", vault), ("files", files)):
        if folder is not None:
            for path, rel in tree_files(Path(folder)):
                try:
                    entries[f"{root}/{rel}"] = file_digest(path)[1]
                except OSError:
                    if skipped is None:
                        raise
                    skipped.append(f"{root}/{rel}")
    return {"brain_version": BRAIN_VERSION, "created": (clock or dt.datetime.now)().isoformat(timespec="seconds"),
            "with_files": files is not None, "entries": entries}


def backup_source(entry: str, vault: Path, files) -> Path:
    root, _, rel = entry.partition("/")
    return (vault if root == "vault" else Path(files)) / rel


def zip_file_entry(zf, entry: str, source: Path):
    """source copied in blocks into the entry of an open zip; returns its sha256, or None when source is gone."""
    try:
        info = zipfile.ZipInfo.from_file(source, entry)
        handle = open(source, "rb")  # noqa: SIM115 — closed by the with below; opened here to catch a removed file
    except FileNotFoundError:
        return None
    info.compress_type = zipfile.ZIP_DEFLATED
    digest = hashlib.sha256()
    with handle, zf.open(info, "w", force_zip64=True) as dest:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
            dest.write(block)
    return digest.hexdigest()


def write_backup_zip(partial: Path, manifest: dict, vault: Path, files=None):
    """Write the zip into `partial`, created exclusively (FileExistsError when it exists): each entry of the
    manifest read in blocks, then brain-backup.json. A file changed since the manifest gets the sha256 of what was
    written; a file gone since then leaves the manifest. Failures (OSError) propagate to the caller."""
    with open(partial, "xb") as handle, zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for entry in list(manifest["entries"]):
            digest = zip_file_entry(zf, entry, backup_source(entry, vault, files))
            if digest is None:
                del manifest["entries"][entry]
            else:
                manifest["entries"][entry] = digest
        zf.writestr(BACKUP_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))


def safe_entry(name: str) -> bool:
    """False for a zip entry that could land outside the destination: empty, absolute ("/x", "\\x", "C:..."), a
    folder (ending in "/"), or with a ".." part."""
    text = str(name).replace("\\", "/")
    if not text or text.startswith("/") or text.endswith("/") or re.match(r"^[A-Za-z]:", text) or "\x00" in text:
        return False
    return ".." not in text.split("/")


def read_manifest(zf) -> dict:
    """The manifest of an open backup zip; missing or invalid = ValueError with the reason."""
    try:
        manifest = json.loads(zf.read(BACKUP_MANIFEST).decode("utf-8"))
    except KeyError:
        raise ValueError(f"sem {BACKUP_MANIFEST}") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"{BACKUP_MANIFEST} inválido: {e}") from None
    if not isinstance(manifest, dict) or not isinstance(manifest.get("entries"), dict):
        raise ValueError(f"{BACKUP_MANIFEST} inválido: sem entries")  # noqa: TRY004 — a reason, like the others
    return manifest


def verify_backup(zip_path) -> tuple:
    """(ok, detail) of a backup zip: it opens, every name is safe (safe_entry), and each entry of the manifest
    exists and matches its sha256. detail = "N entradas", or the reason (zip inválido, entrada faltando, sha256
    diferente, entrada perigosa)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            manifest = read_manifest(zf)
            names = set(zf.namelist())
            unsafe = sorted(name for name in names | set(manifest["entries"]) if not safe_entry(name))
            if unsafe:
                return False, f"entrada perigosa: {one_line(unsafe[0])}"
            for entry, expected in manifest["entries"].items():
                if entry not in names:
                    return False, f"entrada faltando: {one_line(entry)}"
                digest = hashlib.sha256()
                with zf.open(entry) as handle:
                    for block in iter(lambda: handle.read(1 << 20), b""):
                        digest.update(block)
                if digest.hexdigest() != expected:
                    return False, f"sha256 diferente: {one_line(entry)}"
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, zlib.error, NotImplementedError) as e:
        return False, f"zip inválido: {e}"
    except ValueError as e:  # the manifest (read_manifest)
        return False, str(e)
    except OSError as e:
        return False, f"não consegui ler o zip: {e.strerror or e}"
    return True, f"{len(manifest['entries'])} entradas"


def zip_summary(path: Path) -> dict:
    """name, created, size, entries and with_files of a backup zip of a target, read from the manifest (entries None
    and "detail" when it cannot be read)."""
    moment, item = backup_moment(path.name), {"name": path.name}
    item["created"] = moment.isoformat() if moment else None
    item["with_files"] = bool(BACKUP_NAME_RE.match(path.name).group(2))
    try:
        item["size"] = path.stat().st_size
        with zipfile.ZipFile(path) as zf:
            manifest = read_manifest(zf)
        item["entries"], item["with_files"] = len(manifest["entries"]), bool(manifest.get("with_files"))
    except (OSError, ValueError, EOFError, zipfile.BadZipFile, zlib.error) as e:
        item.setdefault("size", None)
        item["entries"], item["detail"] = None, f"não consegui ler: {getattr(e, 'strerror', None) or e}"
    return item


def target_problem(folder: Path):
    """Why a backup target cannot be used (missing, not a folder, not readable), or None."""
    if not folder.exists():
        return "pasta não encontrada"
    if not folder.is_dir():
        return "não é uma pasta"
    try:
        os.scandir(folder).close()
    except OSError as e:
        return e.strerror or str(e)
    return None


def check_backup_target(target: str, values: dict, what: str) -> str:
    """target as an absolute path; inside the vault or the files folder = BrainError (exit 2), before any write."""
    folder = absolute(target)
    for key in ("vault", "files"):
        if values.get(key) and inside_on_disk(folder, values[key]):
            raise BrainError(f"{what} dentro {'do vault' if key == 'vault' else 'da pasta files'}: {target} — "
                             "o backup fica sempre fora deles (references/backup.md)")
    return folder


def same_folder(a: str, b: str) -> bool:
    """True when a and b are the same folder: the same resolved path, or the same folder on disk (samefile)."""
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def distinct_folders(folders) -> list:
    """folders without repeats, the first spelling of each folder kept (same_folder)."""
    kept = []
    for folder in folders:
        if not any(same_folder(folder, other) for other in kept):
            kept.append(folder)
    return kept


def stale_partials(folder: Path) -> list:
    """Names "<backup name>.partial" in a target: left by an interrupted backup (or one running right now). Only
    reported: brain.py never removes them (ADR-0015); the person can delete them by hand."""
    names = [entry.name for entry in os.scandir(folder) if entry.name.endswith(BACKUP_PARTIAL)
             and backup_moment(entry.name[:-len(BACKUP_PARTIAL)]) and entry.is_file(follow_symlinks=False)]
    return sorted(names)


PARTIAL_HINT = "backup interrompido; pode ser apagado à mão (references/backup.md)"


def cmd_backup_target_add(args, config_home=None) -> int:
    config = read_config(config_home)
    values, local_path = config["values"], local_config_path(config_home)
    folder = check_backup_target(args.folder, values, "destino")
    known = next((target for target in values["backup_targets"] if same_folder(folder, target)), None)
    if known is not None:
        print(f"destino já existe: {known}" + (f" (mesma pasta de {folder})" if known != folder else ""))
        return 0
    local = read_yaml(local_path)
    local["backup_targets"] = values["backup_targets"] + [folder]
    write_local_config(local_path, LOCAL_HEADER + dump_yaml(local))
    print(f"Destino de backup acrescentado: {folder} (configuração local: {local_path})")
    problem = target_problem(Path(folder))
    if problem:
        print(f"aviso: {folder} — {problem}; o backup nesse destino falha até a pasta existir", file=sys.stderr)
    return 0


def backup_to(folder: Path, name: str, manifest: dict, vault: Path, files, keep: int) -> dict:
    """One target of the backup: <name>.partial written and verified, renamed to <name>, then rotation (ADR-0015).
    A failure leaves the older backups as they were and removes only the .partial this call created."""
    result = {"path": str(folder), "status": "failed", "detail": "", "removed": []}
    problem = target_problem(folder)
    if problem:
        result["detail"] = problem
        return result
    final, partial = folder / name, folder / (name + BACKUP_PARTIAL)
    if final.exists() or partial.exists():
        result["detail"] = f"já existe: {(final if final.exists() else partial).name}"
        return result
    try:
        write_backup_zip(partial, manifest, vault, files)
    except FileExistsError:
        result["detail"] = f"já existe: {partial.name}"
        return result
    except OSError as e:
        result["detail"] = f"não consegui gravar o zip: {e.strerror or e}"
        with contextlib.suppress(OSError):
            rotate_backups(folder, keep, discard=partial)
        return result
    ok, detail = verify_backup(partial)
    if not ok:
        result["detail"] = f"zip gravado não confere: {detail}"
        with contextlib.suppress(OSError):
            rotate_backups(folder, keep, discard=partial)
        return result
    try:
        if final.exists():  # never overwrite: another backup took the name meanwhile
            raise FileExistsError(errno.EEXIST, "já existe", str(final))
        os.rename(partial, final)
    except OSError as e:
        result["detail"] = f"já existe: {final.name}" if isinstance(e, FileExistsError) else \
            f"não consegui renomear o zip: {e.strerror or e}"
        with contextlib.suppress(OSError):
            rotate_backups(folder, keep, discard=partial)
        return result
    result["status"], result["detail"] = "ok", detail
    try:
        result["removed"] = rotate_backups(folder, keep, new=name)
    except OSError as e:
        result["detail"] = f"{detail}; rotação falhou: {e.strerror or e}"
    return result


def cmd_backup(args, config_home=None) -> int:
    values = load_config(config_home)["values"]
    vault, settings = vault_dir(values), values["backup"]
    targets = args.dest or values["backup_targets"]
    if not targets:
        raise BrainError(NO_BACKUP_TARGET)
    folders = distinct_folders(check_backup_target(target, values, "--dest" if args.dest else "destino")
                               for target in targets)
    with_files = args.with_files or settings["with_files"]
    files = values["files"] if with_files else None
    if with_files and not (files and Path(files).is_dir()):
        raise BrainError(f"pasta files não encontrada: {files or '(sem files na configuração local)'}", 1)
    clock = dt.datetime.now().replace(microsecond=0)
    name = backup_name(with_files, clock=lambda: clock)
    skipped = []  # files that could not be read: out of the zip, and the exit is 1
    manifest = build_manifest(vault, Path(files) if files else None, clock=lambda: clock, skipped=skipped)
    results = [backup_to(Path(folder), name, manifest, vault, files, settings["keep"]) for folder in folders]
    ok = sum(1 for item in results if item["status"] == "ok")
    if ok:
        failed = len(results) - ok
        append_log(vault, values["layout"], "backup",
                   f"— {name} → {ok} destino(s)" + (f", {failed} falhou(aram)" if failed else "")
                   + (f", {len(skipped)} arquivo(s) sem leitura fora do zip" if skipped else ""))
    code = 0 if ok == len(results) and not skipped else 1
    if args.json:
        print_json({"name": name, "entries": len(manifest["entries"]), "targets": results, "skipped": skipped})
        return code
    print(f"Backup {name} — {len(manifest['entries'])} entradas")
    for item in skipped:
        print(f"AVISO {one_line(item)} — sem leitura: ficou fora do zip")
    for item in results:
        print(f"{'OK' if item['status'] == 'ok' else 'ERRO'} {one_line(item['path'])} — {one_line(item['detail'])}")
        for removed in item["removed"]:
            print(f"  removido (rotação, backup.keep {settings['keep']}): {removed}")
    return code


def cmd_backup_list(args, config_home=None) -> int:
    values = read_config(config_home)["values"]
    targets = []
    for target in values["backup_targets"]:
        folder = Path(target)
        item = {"path": target, "status": "ok", "detail": "", "backups": [], "partials": []}
        problem = target_problem(folder)
        if problem is None:
            try:
                item["backups"] = [zip_summary(folder / name) for name in backup_names(folder)]
                item["partials"] = stale_partials(folder)
            except OSError as e:
                problem = e.strerror or str(e)
        if problem:
            item["status"], item["detail"] = "failed", f"inacessível ({problem})"
        else:
            item["detail"] = f"{len(item['backups'])} backup(s)"
        targets.append(item)
    if args.json:
        print_json({"targets": targets})
        return 0
    if not targets:
        print("nenhum destino configurado (references/backup.md)")
    for item in targets:
        print(f"{one_line(item['path'])} — {item['detail']}")
        for backup in item["backups"]:
            entries = backup["entries"] if backup["entries"] is not None else backup.get("detail", "?")
            print(f"  {backup['name']}  {backup['created']}  {backup['size']} bytes  {entries} entradas"
                  + ("  (com files)" if backup["with_files"] else ""))
        for partial in item["partials"]:
            print(f"  AVISO {partial} — {PARTIAL_HINT}")
    return 0


def cmd_backup_verify(args, config_home=None) -> int:
    results, warnings = [], []
    if args.zip:
        path = Path(args.zip).expanduser()
        if not path.is_file():
            raise BrainError(f"zip não encontrado: {args.zip}")
        results.append((path, *verify_backup(path)))
    else:
        targets = read_config(config_home)["values"]["backup_targets"]
        if not targets:
            raise BrainError(NO_BACKUP_TARGET)
        for target in targets:
            problem = target_problem(Path(target))
            names = []
            if problem is None:
                try:
                    names = backup_names(Path(target))
                except OSError as e:
                    problem = e.strerror or str(e)
            if problem or not names:
                warnings.append((target, f"inacessível ({problem})" if problem else "nenhum backup"))
            else:
                path = Path(target) / names[0]
                results.append((path, *verify_backup(path)))
    code = 0 if all(ok for _, ok, _ in results) else 1
    if args.json:
        print_json({"ok": code == 0, "verified": len(results),
                    "backups": [{"zip": str(path), "ok": ok, "detail": detail}
                                                  for path, ok, detail in results],
                    "warnings": [{"path": target, "detail": detail} for target, detail in warnings]})
        return code
    for target, detail in warnings:
        print(f"AVISO {one_line(target)} — {detail}")
    for path, ok, detail in results:
        print(f"{'OK' if ok else 'ERRO'} {one_line(str(path))} — {detail}")
    return code


def restore_zip(source: str) -> Path:
    """--from of restore, as an absolute path: an existing zip (missing = exit 2) that passes verify_backup (else
    exit 1)."""
    path = Path(absolute(source))
    if not path.is_file():
        raise BrainError(f"zip não encontrado: {source}")
    ok, detail = verify_backup(path)
    if not ok:
        raise BrainError(f"backup não confere: {one_line(str(path))} — {detail}; nada foi gravado", 1)
    return path


def restored_name(rel: str, date: str, n: int = 0) -> str:
    """"<pasta>/<nome> (restaurado AAAA-MM-DD).md", then "...)-1.md", "...)-2.md"."""
    folder, base = posixpath.split(rel)
    stem, suffix = posixpath.splitext(base)
    name = f"{stem} (restaurado {date}){f'-{n}' if n else ''}{suffix}"
    return posixpath.join(folder, name) if folder else name


def create_bytes(path: Path, data: bytes) -> bool:
    """create_file for bytes: path created exclusively (and the missing folders); an existing file = False."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "xb") as handle:
            handle.write(data)
    except FileExistsError:
        return False
    return True


def cmd_restore_note(args, config_home=None) -> int:
    _, vault, layout = store_config(config_home)
    rel = inside_vault(args.note, "nota")
    path = restore_zip(args.source)
    with zipfile.ZipFile(path) as zf:
        entries = read_manifest(zf)["entries"]
        if f"vault/{rel}" not in entries:
            raise BrainError(f"nota não está no backup: {rel} ({path.name})")
        data = zf.read(f"vault/{rel}")
    date, n = today(), 0
    if not inside_on_disk(vault / restored_name(rel, date), vault):  # a folder linked outside the vault
        raise BrainError(f"restore fora do vault: {rel} — a pasta aponta para fora do vault; nada foi gravado")
    while not create_bytes(vault / restored_name(rel, date, n), data):
        n += 1
    new = restored_name(rel, date, n)
    append_log(vault, layout, "restore", f"{new} ← {rel} de {path.name}")
    if args.json:
        print_json({"note": rel, "restored": new, "from": str(path)})
        return 0
    print(f"Restaurado: {new} (de {path.name}) — a nota atual não mudou; compare e escolha")
    return 0


def restore_folder(out: str, values: dict) -> Path:
    """--to of restore: a new or empty folder outside the vault and the files folder, else BrainError (exit 2)."""
    folder = Path(check_backup_target(out, values, "--to"))
    if folder.exists() and not folder.is_dir():
        raise BrainError(f"--to não é uma pasta: {out}")
    if folder.is_dir() and any(entry.name not in OS_METADATA for entry in folder.iterdir()):
        raise BrainError(f"--to já tem arquivos: {out} — o restore nunca sobrescreve; use uma pasta nova ou vazia")
    return folder


def cmd_restore_all(args, config_home=None) -> int:
    """The whole backup into a new folder. Works on a machine without configuration (the computer that was lost):
    then only the folder itself is checked."""
    try:
        values = read_config(config_home)["values"]
    except BrainError as e:
        if e.code != 3:
            raise
        values = {}
    folder = restore_folder(args.to, values)
    path = restore_zip(args.source)
    with zipfile.ZipFile(path) as zf:
        entries = read_manifest(zf)["entries"]
        bad = sorted(entry for entry in entries if entry.split("/", 1)[0] not in BACKUP_ROOTS or "/" not in entry)
        if bad:
            raise BrainError(f"backup não confere: entrada fora de vault/ e files/: {one_line(bad[0])}; nada foi "
                             "gravado", 1)
        written = 0
        try:
            for entry in sorted(entries):
                target = folder.joinpath(*entry.split("/"))
                if not inside_on_disk(target, folder):
                    raise BrainError(f"entrada perigosa: {one_line(entry)}", 1)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(entry) as src, open(target, "xb") as dest:
                    shutil.copyfileobj(src, dest, 1 << 20)
                moment = time.mktime(zf.getinfo(entry).date_time + (0, 0, -1))
                os.utime(target, (moment, moment))
                written += 1
        except OSError as e:
            raise BrainError(f"restauração incompleta em {one_line(str(folder))} ({written} de {len(entries)} "
                             f"arquivos): {e.strerror or e}", 1) from e
    roots = sorted({entry.split("/", 1)[0] for entry in entries})
    if args.json:
        print_json({"from": str(path), "to": str(folder), "entries": written, "roots": roots})
        return 0
    print(f"Backup {path.name} restaurado em {one_line(str(folder))}: {written} arquivos em "
          f"{', '.join(f'{root}/' for root in roots)}")
    print("Nada no vault mudou; compare e copie o que quiser.")
    return 0


def cmd_restore(args, config_home=None) -> int:
    if bool(args.note) == bool(args.to):
        raise BrainError("informe NOTA (uma nota do vault) ou --to PASTA (o backup inteiro), um dos dois")
    return cmd_restore_note(args, config_home) if args.note else cmd_restore_all(args, config_home)


def backup_items(values: dict) -> list:
    """Doctor lines of the backup: one per target (age of the newest backup, from the name's stamp)."""
    targets = values.get("backup_targets") or []
    if not targets:
        return [("AVISO", "backup", "nenhum destino configurado (references/backup.md)")]
    warn_days, rows = values["backup"]["warn_days"], []
    for target in targets:
        problem = target_problem(Path(target))
        names = []
        if problem is None:
            try:
                names = backup_names(Path(target))
            except OSError as e:
                problem = e.strerror or str(e)
        item = f"backup {target}"
        if problem:
            rows.append(("AVISO", item, f"inacessível ({problem})"))
        elif not names:
            rows.append(("AVISO", item, "nenhum backup"))
        else:
            days = max(0, (dt.datetime.now() - backup_moment(names[0])).days)
            if days > warn_days:
                rows.append(("AVISO", item, f"último há {days} dia(s), mais que warn_days ({warn_days}) ({names[0]})"))
            else:
                rows.append(("OK", item, f"último há {days} dia(s) ({names[0]})"))
        if problem is None:
            with contextlib.suppress(OSError):
                rows += [("AVISO", f"backup {target} .partial", f"{name} — {PARTIAL_HINT}")
                         for name in stale_partials(Path(target))]
    return rows


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


def files_folder(values: dict, context):
    """(files root, "<context or inbox>/<AAAA>") where ingest puts a file. Files folder missing = BrainError (exit 1)."""
    files = values["files"]
    if not files or not Path(files).is_dir():
        raise BrainError(f"pasta files não encontrada: {files or '(sem files na configuração local)'}", 1)
    if context:
        check_context_name(context)
    folder = f"{context or INBOX_FILES}/{dt.date.today().year}"
    if posixpath.normpath(folder) != folder or folder.startswith(("/", "..")):
        raise BrainError(f"contexto fora da pasta files: {context}")
    return Path(files), folder


def copy_to_files(source: Path, values: dict, context) -> str:
    """Copy of source into <files>/<context or inbox>/<AAAA>/<name>, never overwriting (<stem>-1<ext>, -2...);
    returns the path relative to files. Files folder missing or not writable = BrainError (exit 1)."""
    files, folder = files_folder(values, context)
    target, stem, suffix = files / folder, source.stem, source.suffix
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


def file_digest(path: Path) -> tuple:
    """(size in bytes, sha256 hex) of a stored file, read in blocks; only the numbers go into the vault."""
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    return size, digest.hexdigest()


def check_confidential_ingest(args, url):
    """ingest --confidential takes only a file and never extracts: a URL, --text-file, --kind or --timestamps =
    BrainError (exit 2), before anything is written."""
    if url is not None:
        raise BrainError("--confidential só vale para arquivo: um link não é guardado como item confidencial")
    given = [flag for flag, value in (("--text-file", args.text_file), ("--kind", args.kind),
                                      ("--timestamps", args.timestamps)) if value]
    if given:
        raise BrainError(f"--confidential não extrai texto: não use {', '.join(given)} "
                         "(o documento fica opaco, references/confidential.md)")


def cmd_ingest(args, config_home=None) -> int:
    values, vault, layout = store_config(config_home)
    source = args.source.strip()
    url = source if URL_RE.match(source) else None
    if args.confidential:
        check_confidential_ingest(args, url)
    if args.context:
        check_context(args.context, values)
    if args.move:  # only an item of the inbox, checked before anything is written
        if url is not None:
            raise BrainError(MOVE_ONLY_INBOX)
        source = str(inbox_item(source, vault, layout, MOVE_ONLY_INBOX))
        if classify_inbox_item(Path(source)) == "syncing":
            raise BrainError(f"ainda sincronizando: {args.source} — espere o app do provedor baixar o arquivo")
    if url is None and not Path(source).is_file():
        raise BrainError(f"fonte não encontrada: {args.source}")
    kind = args.kind or detect_kind(source)
    process = bool(kind) and not args.text_file and not args.no_process and not args.confidential
    if process and not processor_of(kind, values["processors"]):
        process = False
        print_warnings([f"sem processador para {kind} — veja references/processors.md"])
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

    if url:
        file_rel = None
    elif args.move:  # the file goes first: out of the inbox into files (logged by move_out_of_inbox)
        files, folder = files_folder(values, args.context)
        moved = move_out_of_inbox(Path(source), files / folder / Path(source).name, vault, layout, files=files)
        file_rel = f"{folder}/{moved.name}"
    else:
        file_rel = copy_to_files(Path(source), values, args.context)  # the copy comes first
    extraction, opaque = "", None
    if args.confidential:  # opaque: never a processor, only the size and the hash of the stored file
        opaque = file_digest(Path(values["files"]) / file_rel)
        extraction = "; confidencial"
    if process:  # on the stored copy (or the URL); a failure keeps the raw and is written in the note
        try:
            extracted = run_processor(kind, url or str(Path(values["files"]) / file_rel), values["processors"],
                                      args.timestamps)
            extraction = f"; texto extraído ({kind})"
        except ProcessorError as e:
            print_warnings([str(e)])
            extracted = f"_(extraction failed: {one_line(e.reason)})_"
            extraction = f"; extração falhou ({kind}): {e.reason}"
    raw_rel = free_raw_path(vault, layout, title)
    try:
        write_new_file(vault / raw_rel, render_source_note(title, today(), args.context, file_rel, url, extracted,
                                                           opaque))
    except OSError as e:
        where = "o arquivo foi movido para" if args.move else "a cópia ficou em"
        kept = f"; {where} {file_rel} (na pasta files)" if file_rel else ""
        raise BrainError(f"não consegui criar a nota de fonte {raw_rel}: {e.strerror or e}{kept}", 1) from e
    append_log(vault, layout, "ingest", f"{raw_rel} — {url or file_rel}{extraction}")
    if args.json:
        print_json(dict({"raw": raw_rel, "file": file_rel, "url": url}, **({"confidential": True} if opaque else {})))
        return 0
    print(f"Nota de fonte: {one_line(raw_rel)}" + (" (confidencial: texto não extraído)" if opaque else ""))
    if url:
        print(f"Link: {url}")
    else:
        print(f"Arquivo {'movido da inbox' if args.move else 'copiado'}: {one_line(file_rel)} (na pasta files)")
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


def check_secret_ref(note_type: str, vault_ref):
    """--vault-ref only with type secret-ref, which requires it in the <esquema>://<caminho> format = BrainError
    (exit 2) otherwise. The reference is only validated, never opened (ADR-0014)."""
    if note_type != SECRET_REF_TYPE:
        if vault_ref is not None:
            raise BrainError(f"--vault-ref só vale com --type {SECRET_REF_TYPE}")
        return
    if vault_ref is None:
        raise BrainError(f"--type {SECRET_REF_TYPE} precisa de --vault-ref <esquema>://<caminho> "
                         "(ex.: keepass://Pessoal/Banco) — o segredo fica no gerenciador de senhas")
    if not is_vault_ref(vault_ref.strip()):
        raise BrainError(f"--vault-ref fora do formato <esquema>://<caminho> (ex.: keepass://Pessoal/Banco): "
                         f"{one_line(vault_ref)}")


def cmd_new_note(args, config_home=None) -> int:
    values, vault, layout = store_config(config_home)
    if args.type not in NOTE_TYPES:
        raise BrainError(f"tipo desconhecido: {args.type} — use um de: {', '.join(NOTE_TYPES)}")
    check_secret_ref(args.type, args.vault_ref)
    vault_ref = (args.vault_ref or "").strip()
    title = " ".join(args.title.split())
    rel = note_path(title, args.context, values)
    tags = unique(frontmatter_tags(args.tags or ""))
    template = vault / layout["templates"] / f"{args.type}.md"
    if not template.is_file():
        template = TEMPLATES_DIR / f"{args.type}.md"
    text = render_note(template.read_text(encoding="utf-8"), tags=tags, title=title, date=today(),
                       context=args.context or "", source=source_value(args.source, vault), vault_ref=vault_ref)
    confidential = args.confidential or args.type == SECRET_REF_TYPE
    if confidential:  # whatever the vault's template has: confidential: true (and vault_ref in a secret-ref)
        keys = {"confidential": "true"}
        if vault_ref:
            keys["vault_ref"] = json.dumps(vault_ref, ensure_ascii=False)
        text = with_frontmatter_keys(text, keys)
    write_new_file(vault / rel, text)
    append_log(vault, layout, "new-note", f"{rel} — {args.type}" + ("; confidencial" if confidential else ""))
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
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
        entry = index_entry(rel, text, contexts)
        if not entry.confidential:  # a confidential note is never listed (SPEC-0050)
            entries.append(entry)
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


# ---------------------------------------------------------------- inbox: capture, list, done (SPEC-0021)

MOVE_ONLY_INBOX = "--move só vale para itens da inbox"


def capture_name(text: str, existing=(), clock=None) -> str:
    """Name of a capture, "AAAA-MM-DD-HHMMSS-<slug of the first CAPTURE_WORDS words>.md", with the time of clock()
    (None = datetime.now); a name in `existing` gets "-1", "-2"... Pure (no I/O)."""
    stamp = (clock or dt.datetime.now)().strftime("%Y-%m-%d-%H%M%S")
    base = f"{stamp}-{slugify(' '.join(text.split()[:CAPTURE_WORDS]), fallback='captura')}"
    taken, name, n = set(existing), f"{base}.md", 0
    while name in taken:
        n += 1
        name = f"{base}-{n}.md"
    return name


def render_capture(text: str, created: str, context) -> str:
    frontmatter = {"type": "capture", "created": created}
    if context:
        frontmatter["context"] = context
    return f"---\n{dump_yaml(frontmatter)}---\n\n{text.strip()}\n"


def capture_note(text: str, context=None, clock=None) -> str:
    """Content of the capture note that `capture` writes and `capture --print` shows: frontmatter type: capture,
    created = clock().isoformat(timespec="seconds") (None = datetime.now), context when given, then the text.
    Pure (no I/O)."""
    return render_capture(text, (clock or dt.datetime.now)().isoformat(timespec="seconds"), context)


def inbox_dir(vault: Path, layout: dict) -> Path:
    return vault / inside_vault(layout["inbox"], "layout.inbox")


def in_inbox(path: Path, vault: Path, layout: dict) -> bool:
    """True when path is a file below the inbox, with the folders resolved ("inbox/../raw/x" is outside; a vault
    reached through a symbolic link is the same vault). The item itself is not resolved: it is what moves, and a
    symbolic link is never an item."""
    folder = Path(os.path.realpath(path.parent))
    return (is_inside(str(folder), os.path.realpath(inbox_dir(vault, layout))) and path.is_file()
            and not path.is_symlink())


def hidden_in_inbox(path: Path, vault: Path, layout: dict) -> bool:
    """True when `inbox list` hides path: a hidden subfolder of the inbox (any part starting with "."), OS metadata
    or a hidden file that is not an iCloud placeholder."""
    folder = _pure(os.path.realpath(path.parent)).relative_to(_pure(os.path.realpath(inbox_dir(vault, layout))))
    hidden_name = path.name.startswith(".") and not path.name.lower().endswith(ICLOUD_SUFFIX)
    return any(part.startswith(".") for part in folder.parts) or hidden_name or path.name in OS_METADATA


def inbox_item(item: str, vault: Path, layout: dict, outside: str = "item fora da inbox") -> Path:
    """Path of ITEM as the CLI receives it (absolute, relative to the current folder or to the vault); missing =
    BrainError(2) "item não encontrado", outside the inbox = BrainError(2, outside)."""
    given = Path(os.path.expanduser(item.strip()))
    candidates = [given] if given.is_absolute() else [Path.cwd() / given, vault / given]
    path = next((c for c in candidates if c.exists() or c.is_symlink()), None)
    if path is None:
        raise BrainError(f"item não encontrado: {one_line(item)}")
    if path.is_symlink():
        raise BrainError(f"item é um link simbólico (não é processado): {one_line(item)}")
    if not in_inbox(path, vault, layout):
        raise BrainError(f"{outside}: {one_line(item)}")
    if hidden_in_inbox(path, vault, layout):
        raise BrainError(f"item numa pasta ou arquivo oculto da inbox (o inbox list não o mostra): {one_line(item)}")
    return path


def shown_path(path: Path, vault: Path, files=None) -> str:
    """How log.md names a path: relative to the vault, "<files>/..." inside files, else only the name (log.md is
    synced with the vault and never holds an absolute path)."""
    real = os.path.realpath(path)
    for root, prefix in ((vault, ""), (files, "<files>/")):
        if root is not None and is_inside(real, os.path.realpath(root)):
            return prefix + Path(real).relative_to(os.path.realpath(root)).as_posix()
    return path.name


def move_out_of_inbox(item: Path, dest: Path, vault: Path, layout: dict, command: str = "inbox-move", note=None,
                      files=None) -> Path:
    """The only function that moves a file (ADR-0007): `item`, inside the inbox, goes to `dest` (folders created as
    needed); an existing dest gets "<stem>-1<ext>", "-2"... and is never touched. Returns the final path and logs
    "<command> <item> → <dest> [nota: <note>]". A source outside the inbox = BrainError(2), nothing moved or
    created. Never deletes: the destination name is reserved with an exclusive create and the item is renamed onto
    that empty reservation; when it cannot be renamed (another disk) only the reservation goes and the item stays."""
    item, dest = Path(item), Path(dest)
    if not in_inbox(item, vault, layout):
        raise BrainError(f"item fora da inbox: {one_line(item)}")
    origin = shown_path(item, vault, files)
    dest.parent.mkdir(parents=True, exist_ok=True)
    candidate, n = dest, 0
    while True:
        try:
            with open(candidate, "xb"):
                break
        except FileExistsError:
            n += 1
            candidate = dest.with_name(f"{dest.stem}-{n}{dest.suffix}")
    try:
        os.replace(item, candidate)
    except OSError as e:
        candidate.unlink()  # only the empty reservation this call created; the item stays in the inbox
        raise BrainError(f"não consegui mover {origin} para {candidate.parent}: {e.strerror or e} — o item ficou "
                         "na inbox (use ingest sem --move para copiar)", 1) from e
    summary = f"{origin} → {shown_path(candidate, vault, files)}" + (f" nota: {note}" if note else "")
    append_log(vault, layout, command, summary)
    return candidate


def read_head(path: Path) -> str:
    """The first INBOX_READ_BYTES of a text item, decoded (not UTF-8 = replaced characters)."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(INBOX_READ_BYTES)
    except OSError:
        return ""
    return data.decode("utf-8-sig", errors="replace")


def item_text(path: Path) -> str:
    """Text of an inbox item for the kind and the preview: the body of a .md/.txt (without frontmatter) or the URL
    of a .url/.webloc."""
    suffix, text = path.suffix.lower(), read_head(path)
    if suffix in INBOX_LINK_SUFFIXES:
        m = LINK_IN_FILE_RE.search(text)
        if not m:
            return ""
        return (m.group(1) or html.unescape(m.group(2))).strip()  # .webloc is XML: "&amp;" is "&"
    return read_frontmatter(text)[1].strip() if suffix == ".md" else text.strip()


def classify_inbox_item(path: Path, now=None) -> str:
    """"text" (.md, .txt) | "link" (.url, .webloc, or a .md/.txt whose text is only a URL) | "file" (the rest) |
    "syncing" (an iCloud "*.icloud" placeholder, or a 0-byte file modified less than SYNCING_SECONDS before `now`,
    seconds since the epoch; None = now)."""
    path = Path(path)
    if path.name.lower().endswith(ICLOUD_SUFFIX):
        return "syncing"
    stat = path.stat()
    if stat.st_size == 0 and (time.time() if now is None else now) - stat.st_mtime < SYNCING_SECONDS:
        return "syncing"
    suffix = path.suffix.lower()
    if suffix in INBOX_LINK_SUFFIXES:
        return "link"
    if suffix in INBOX_TEXT_SUFFIXES:
        if "\x00" in read_head(path):  # NUL bytes: binary content with a text name
            return "file"
        return "link" if URL_RE.match(item_text(path)) else "text"
    return "file"


def walk_inbox(vault: Path, layout: dict):
    """(path, path relative to the vault) of each file of the inbox, its subfolders included except hidden ones;
    hidden files and OS metadata are skipped, except iCloud placeholders (".x.pdf.icloud")."""
    folder = inbox_dir(vault, layout)
    if not folder.is_dir():
        return
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            if visible_in_inbox(name):
                path = Path(root) / name
                yield path, path.relative_to(vault).as_posix()


def visible_in_inbox(name: str) -> bool:
    """False for a hidden file (except an iCloud placeholder) and OS metadata, which `inbox list` skips."""
    hidden = name.startswith(".") and not name.lower().endswith(ICLOUD_SUFFIX)
    return not hidden and name not in OS_METADATA


def inbox_entries(vault: Path, layout: dict, stale_after: int, now=None, items=None) -> list:
    """The items of `inbox list`, oldest first: path, kind, size, age_days, stale and preview. items = the (path,
    path relative to the vault) to describe; None = walk_inbox (lint passes the ones of its single scan)."""
    now = time.time() if now is None else now
    rows = []
    for path, rel in walk_inbox(vault, layout) if items is None else items:
        try:
            stat = path.stat()
            kind = classify_inbox_item(path, now)
        except OSError:
            continue  # vanished while listing (the provider moved it)
        age = max(0.0, (now - stat.st_mtime) / 86400)
        preview = " ".join(CONTROL_RE.sub(" ", item_text(path)).split()) if kind in ("text", "link") else ""
        if len(preview) > PREVIEW_MAX:
            preview = preview[:PREVIEW_MAX - 1] + "…"
        rows.append((stat.st_mtime, rel, {"path": rel, "kind": kind, "size": stat.st_size,
                                          "age_days": round(age, 2), "stale": age > stale_after, "preview": preview}))
    return [entry for _, _, entry in sorted(rows, key=lambda row: (row[0], row[1]))]


def capture_config(args, config_home=None):
    """(values, vault, inbox folder relative to the vault) of a capture. Without --print: the configured vault and
    layout.inbox (--inbox = BrainError code 2). With --print nothing is written, so a vault, brain-config.yml or inbox
    the agent cannot read never fails it (the macOS TCC case, SPEC-0044): layout.inbox when brain-config.yml could
    be read, else --inbox or "inbox", with values None and vault None when unreadable. --inbox is only for an
    unreadable or missing shared configuration and never names the vault root nor a folder outside it (code 2)."""
    inbox = getattr(args, "inbox", None)
    if inbox is not None and not args.print:
        raise BrainError("--inbox só vale com --print")
    if not args.print:
        values, vault, layout = store_config(config_home)
        return values, vault, inside_vault(layout["inbox"], "layout.inbox")
    option = print_inbox(inbox) if inbox is not None else None
    try:
        config = read_config(config_home)
    except BrainError as e:
        if e.code != 3:
            raise
        return None, None, option or "inbox"
    except OSError:  # the vault folder cannot even be inspected
        return None, None, option or "inbox"
    values = config["values"]
    unreadable = any(key == "brain-config.yml" for key, _ in config["problems"])
    problems = [message for key, message in config["problems"] if key != "brain-config.yml"]
    if unreadable or not shared_readable(values):
        return None, None, option or "inbox"
    if problems:
        raise BrainError(problems[0], 1)
    if option is not None:
        raise BrainError("--inbox só vale quando o brain-config.yml do vault não pode ser lido; nesta máquina a "
                         f"inbox é layout.inbox: {values['layout']['inbox']}")
    try:
        vault = vault_dir(values)
    except (BrainError, OSError):
        vault = None
    return values, vault, inside_vault(values["layout"]["inbox"], "layout.inbox")


def print_inbox(folder: str) -> str:
    """--inbox of capture --print relative to the vault, checked without touching the disk: the vault root ("",
    ".", "a/..") or outside the vault = BrainError(code 2)."""
    rel = inside_vault(folder, "--inbox")
    if not rel:
        raise BrainError(f"--inbox não pode ser a raiz do vault: {folder!r} — use uma pasta, como inbox")
    return rel


def shared_readable(values: dict) -> bool:
    """True when <vault>/brain-config.yml exists and can be inspected (read_config then read it)."""
    if not values["vault"]:
        return False
    try:
        return shared_config_path(values["vault"]).is_file()
    except OSError:
        return False


def inbox_names(folder) -> set:
    """Names already in the inbox folder (to avoid a name clash); a missing or unreadable folder = empty set."""
    if folder is None:
        return set()
    try:
        return {p.name for p in folder.iterdir()} if folder.is_dir() else set()
    except OSError:
        return set()


def cmd_capture(args, config_home=None) -> int:
    text = args.text.strip()
    if not text:
        raise BrainError("texto da captura vazio")
    values, vault, inbox = capture_config(args, config_home)
    if args.context and values is not None:
        check_context(args.context, values)
    moment = dt.datetime.now()
    existing = inbox_names(vault / inbox if vault is not None else None)
    rel = posixpath.join(inbox, capture_name(text, existing, lambda: moment))
    content = capture_note(text, args.context, lambda: moment)
    if args.print:  # writes nothing: the agent creates the file through the connector (SPEC-0044)
        if args.json:
            print_json({"path": rel, "content": content})
        else:
            print(f"{rel}\n\n{content}", end="")
        return 0
    write_new_file(vault / rel, content)
    append_log(vault, values["layout"], "capture", rel)
    if args.json:
        print_json({"path": rel})
    else:
        print(rel)
    return 0


def cmd_inbox_list(args, config_home=None) -> int:
    values, vault, layout = store_config(config_home)
    items = inbox_entries(vault, layout, values["inbox_stale_days"])
    if args.json:
        print_json({"items": items})
        return 0
    if not items:
        print("Inbox vazia")
        return 0
    for item in items:
        flag = " (parado)" if item["stale"] else ""
        print(f"{item['kind']:<7} {item['age_days']:>6.1f}d {item['size']:>9}  {one_line(item['path'])}{flag}")
        if item["preview"]:
            print(f"    {item['preview']}")
    syncing = sum(1 for item in items if item["kind"] == "syncing")
    print(f"{len(items)} item(ns)" + (f", {syncing} ainda sincronizando (não processe)" if syncing else ""))
    return 0


def cmd_inbox_done(args, config_home=None) -> int:
    values, vault, layout = store_config(config_home)
    item = inbox_item(args.item, vault, layout)
    kind = classify_inbox_item(item)
    if kind == "file":
        raise BrainError(f"arquivo: use ingest --move — {args.item}")
    if kind == "syncing":
        raise BrainError(f"ainda sincronizando: {args.item} — espere o app do provedor baixar o arquivo")
    note = None
    if args.note:
        ref = note_ref(args.note, vault)
        found = LinkIndex(rel for _, rel in walk_notes(values)).resolve(ref)
        note = found or " ".join(ref.split())
    raw = inside_vault(layout["raw"], "layout.raw")
    dest = vault / raw / PROCESSED_DIR / dt.date.today().strftime("%Y-%m") / item.name
    origin = shown_path(item, vault)
    final = move_out_of_inbox(item, dest, vault, layout, command="inbox-done", note=note)
    print(one_line(f"{origin} → {shown_path(final, vault)}" + (f" (nota: {note})" if note else "")))
    return 0


def note_ref(note: str, vault: Path) -> str:
    """--note of inbox done as log.md records it: an absolute path inside the vault becomes relative to the vault;
    outside the vault = BrainError(2), before anything moves (log.md never holds an absolute path)."""
    text = note.strip()
    if not is_absolute(text):
        return text
    real, root = os.path.realpath(os.path.expanduser(text)), os.path.realpath(vault)
    if not is_inside(real, root):
        raise BrainError("--note fora do vault: use uma nota do vault (caminho relativo ao vault ou nome)")
    return Path(real).relative_to(root).as_posix()


# ---------------------------------------------------------------- processors (SPEC-0022, ADR-0009)
class ProcessorError(BrainError):
    """Failure of a processor (executable missing, exit != 0, timeout, empty text): the reason is kept apart for
    the source note ("_(extraction failed: <reason>)_")."""

    def __init__(self, kind: str, reason: str):
        super().__init__(f"processador {kind} falhou: {reason}", 1)
        self.reason = reason


def detect_kind(source: str):
    """youtube (http(s) URL of a YouTube host), video, audio or pdf (by the extension); anything else = None."""
    text = source.strip()
    if SCHEME_RE.match(text):
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        return "youtube" if parts.scheme.lower() in ("http", "https") and host in YOUTUBE_HOSTS else None
    suffix = posixpath.splitext(text.replace("\\", "/"))[1].lower()
    return next((kind for kind, suffixes in KIND_SUFFIXES.items() if suffix in suffixes), None)


def build_args(command: str, input: str, output: str, output_dir: str) -> list:
    """shlex.split(command) with {input}, {output} and {output_dir} replaced in each argument, in a single pass (a
    value is never split, interpreted nor searched for markers again). No shell ever sees the result."""
    values = {"input": input, "output": output, "output_dir": output_dir}
    try:
        words = shlex.split(command)
    except ValueError as e:
        raise BrainError(f"command inválido ({e}): {command}") from e
    return [PROCESSOR_MARKER_RE.sub(lambda m: values[m.group(1)], word) for word in words]


def moment_link(url: str, seconds: int) -> str:
    """url pointing at the moment: ?t=<s>s, or &t=<s>s when the URL already has a query."""
    return f"{url}{'&' if urlsplit(url).query else '?'}t={seconds}s"


def subtitles_to_text(text: str, timestamps: bool = False, url=None) -> str:
    """.vtt or .srt -> text: no header, cue numbers, timing lines, markup nor blank lines; a line that repeats one
    of the previous cue (YouTube automatic captions) appears once. timestamps: "[mm:ss] text" with the start of
    the first cue showing the line; with a YouTube url, "[mm:ss](<url>?t=<s>s) text"."""
    rows = text.lstrip("﻿").splitlines()
    cues = []
    for i, row in enumerate(rows):
        line = row.strip()
        m = SUBTITLE_TIME_RE.match(line)
        if m:
            cues.append((int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3)), []))
            continue
        if not cues or not line:  # header (WEBVTT, Kind:, Language:) or blank line
            continue
        if line.isdigit() and i + 1 < len(rows) and SUBTITLE_TIME_RE.match(rows[i + 1].strip()):
            continue  # number of the next .srt cue
        clean = " ".join(html.unescape(SUBTITLE_TAG_RE.sub("", line)).split())
        if clean:
            cues[-1][1].append(clean)
    out, previous = [], set()
    for start, lines in cues:
        for line in lines:
            if line in previous:
                continue
            if not timestamps:
                out.append(line)
                continue
            stamp = f"{start // 60:02d}:{start % 60:02d}"
            out.append(f"[{stamp}]({moment_link(url, start)}) {line}" if url else f"[{stamp}] {line}")
        previous = set(lines)
    return "\n".join(out)


def processor_of(kind, processors) -> dict:
    """The entry processors[kind] with a command, or {} when there is none."""
    item = processors.get(kind) if isinstance(processors, dict) and kind else None
    return item if isinstance(item, dict) and str(item.get("command") or "").strip() else {}


def executable_of(command: str) -> str:
    """First word of a command ("" when it cannot be split)."""
    try:
        words = shlex.split(command)
    except ValueError:
        return ""
    return words[0] if words else ""


def short_stderr(stderr: str) -> str:
    """stderr of a processor in one line, up to STDERR_MAX characters."""
    return " ".join((stderr or "").split())[:STDERR_MAX]


def read_text_file(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace").lstrip("﻿")


def processor_text(item: dict, output: Path, output_dir: Path, stdout: str):
    """(text, suffix): from {output}, else from the largest file with the `output` extension in {output_dir},
    else from stdout."""
    ext = str(item.get("output") or "").strip().lstrip(".").lower()
    if output.is_file() and output.stat().st_size:
        return read_text_file(output), output.suffix.lower()
    if ext:
        found = [p for p in output_dir.rglob("*") if p.is_file() and p.suffix.lower() == f".{ext}"]
        if found:
            largest = max(found, key=lambda p: (p.stat().st_size, p.name))
            return read_text_file(largest), largest.suffix.lower()
    return stdout, f".{ext}" if ext else ""


def kill_process_group(proc) -> None:
    """Kills the processor and everything it started (its process group, POSIX; on Windows only the process),
    then reaps it. Signals only, never runs a process."""
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.communicate(timeout=5)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


def run_processor(kind: str, source: str, processors: dict, timestamps: bool = False, check: bool = False) -> str:
    """The only place of brain.py that runs an external process (ADR-0009): the command of processors[kind] (or,
    with check, its check command, by default "<executable> --version") as a list of arguments, without a shell,
    in a temporary folder and its own process group, with a timeout (the whole group is killed when it expires) and the output captured. Returns the text
    (with check, the first line of the check output). No processor = BrainError (code 2); failure = ProcessorError
    (code 1) "processador <kind> falhou: <reason>" with the stderr cut to STDERR_MAX characters."""
    item = processor_of(kind, processors)
    if not item:
        raise BrainError(f"nenhum processador para {kind} — veja references/processors.md")
    command = str(item["command"])
    if check:
        command = str(item.get("check") or "").strip() or f"{shlex.quote(executable_of(command))} --version"
    try:
        timeout = CHECK_TIMEOUT if check else int(str(item.get("timeout") or PROCESSOR_TIMEOUT).strip())
    except ValueError as e:
        raise ProcessorError(kind, f"timeout inválido: {item.get('timeout')}") from e
    if timeout < 1:
        raise ProcessorError(kind, f"timeout inválido: {item.get('timeout')}")
    is_url = URL_RE.match(source.strip()) is not None
    entry = source.strip() if is_url or check else str(Path(source).resolve())
    ext = str(item.get("output") or "txt").strip().lstrip(".").lower() or "txt"
    with tempfile.TemporaryDirectory(prefix="brain-processor-") as tmp:
        output, output_dir = Path(tmp) / f"output.{ext}", Path(tmp) / "out"
        output_dir.mkdir()
        try:
            args = build_args(command, entry, str(output), str(output_dir))
        except BrainError as e:
            raise ProcessorError(kind, str(e)) from e
        if not args:
            raise ProcessorError(kind, "command vazio")
        try:
            # Own session/process group: on timeout (or any error) the whole group dies, grandchildren included.
            proc = subprocess.Popen(args, cwd=tmp, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                                    start_new_session=os.name != "nt")
        except FileNotFoundError as e:
            raise ProcessorError(kind, f"executável não encontrado: {args[0]}") from e
        except OSError as e:
            raise ProcessorError(kind, f"não consegui executar {args[0]}: {e.strerror or e}") from e
        try:
            stdout, stderr_text = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as e:
            kill_process_group(proc)
            raise ProcessorError(kind, f"tempo esgotado ({timeout} s); processo encerrado") from e
        except BaseException:
            kill_process_group(proc)
            raise
        stderr = short_stderr(stderr_text)
        if proc.returncode != 0:
            raise ProcessorError(kind, f"saiu com {proc.returncode}" + (f": {stderr}" if stderr else ""))
        if check:
            lines = [line.strip() for line in (stdout or stderr_text or "").splitlines() if line.strip()]
            return lines[0] if lines else "sem saída"
        text, suffix = processor_text(item, output, output_dir, stdout or "")
    if suffix in SUBTITLE_SUFFIXES:
        text = subtitles_to_text(text, timestamps, source.strip() if kind == "youtube" and is_url else None)
    text = text.strip()
    if not text:
        raise ProcessorError(kind, "saída vazia" + (f": {stderr}" if stderr else ""))
    return text


def cmd_process(args, config_home=None) -> int:
    values = load_config(config_home)["values"]
    source = args.source.strip()
    if not URL_RE.match(source) and not Path(source).is_file():
        raise BrainError(f"fonte não encontrada: {args.source}")
    kind = args.kind or detect_kind(source)
    if not kind:
        raise BrainError(f"tipo não reconhecido: {args.source} — use --kind (youtube, video, audio, pdf...)")
    out = Path(args.out).expanduser().resolve() if args.out else None
    if out is not None:  # never overwrites and never writes into the vault (checked before running)
        if out.exists() or out.is_symlink():
            raise BrainError(f"já existe: {args.out}")
        if values["vault"] and inside_on_disk(out, values["vault"]):
            raise BrainError(f"--out dentro do vault: {args.out} — o process não escreve no vault")
    text = run_processor(kind, source, values["processors"], args.timestamps)
    if out is not None:
        try:
            with open(out, "x", encoding="utf-8") as f:
                f.write(text + "\n")
        except FileExistsError as e:
            raise BrainError(f"já existe: {args.out}") from e
        except OSError as e:
            raise BrainError(f"não consegui gravar {args.out}: {e.strerror or e}", 1) from e
        print(f"Texto ({kind}): {one_line(args.out)}", file=sys.stderr)
    else:
        print(text)
    return 0


# ---------------------------------------------------------------- lint (read only; SPEC-0023)

class Finding:
    """A finding of lint: rule, severity (of LINT_SEVERITY), path relative to the vault, detail and suggestion.
    A plain class, like Note."""
    __slots__ = ("detail", "path", "rule", "severity", "suggestion")
    FIELDS = ("rule", "severity", "path", "detail", "suggestion")  # order of the JSON item

    def __init__(self, rule: str, path: str, detail: str, suggestion: str):
        self.rule, self.severity, self.path = rule, LINT_SEVERITY[rule], path
        self.detail, self.suggestion = detail, suggestion

    def __repr__(self) -> str:
        return f"Finding({self.rule!r}, {self.path!r}, {self.detail!r})"

    def as_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.FIELDS}


def attachment_exists(target: str, attachments) -> bool:
    """True when a link with an extension other than .md ("![[img.png]]") names a file of the vault, by name
    (ignoring case) or by path, as Obsidian resolves attachments; attachments = a LinkIndex of those files."""
    suffix = posixpath.splitext(target)[1].lower()
    return attachments is not None and suffix not in ("", ".md") and attachments.resolve(target) is not None


def check_broken_link(notes: list, index: LinkIndex, attachments=None) -> list:
    """One error per link of each note that resolves neither to a note (resolve_link) nor to an attachment."""
    return [Finding("broken-link", note.path, f"[[{one_line(target)}]] não resolve",
                    "crie a nota (new-note) ou corrija o link")
            for note in notes for target in note.links
            if index.resolve(target) is None and not attachment_exists(target, attachments)]


def check_conflict_copy(paths, patterns) -> list:
    """One error per file whose name matches a pattern (regex text or compiled, with the group "base") and whose
    original "<base>.md" exists in the same folder."""
    compiled = [re.compile(pattern) for pattern in patterns]
    existing, found = set(paths), []
    for path in paths:
        folder, name = posixpath.split(path)
        for pattern in compiled:
            m = pattern.match(name)
            base = m.groupdict().get("base") if m else None
            original = posixpath.join(folder, base + ".md") if base else None
            if original and original != path and original in existing:
                found.append(Finding("conflict-copy", path, f"cópia de conflito de {posixpath.basename(original)}",
                                     f"compare com {original} e escolha a versão certa; nada é apagado sozinho"))
                break
    return found


def frontmatter_files(value) -> list:
    """frontmatter.files as a list of non-empty strings (a single string is one item)."""
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [str(item).strip() for item in items if str(item).strip()]


def check_missing_file(notes: list, files: Path) -> list:
    """One error per item of frontmatter.files (relative to the files folder) that does not exist there; an
    absolute item or one that climbs with ".." is "fora da pasta files"."""
    found = []
    for note in notes:
        for item in frontmatter_files(note.frontmatter.get("files")):
            outside = outside_vault(item)
            if outside or not (files / item).exists():
                found.append(Finding("missing-file", note.path,
                                     f"{one_line(item)} {'fora da' if outside else 'não existe na'} pasta files",
                                     "confira se o arquivo foi sincronizado ou corrija o caminho em files"))
    return found


def layout_paths(layout: dict, keys) -> list:
    return [posixpath.normpath(str(layout[key]).replace("\\", "/")) for key in keys]


def check_orphan(notes: list, index: LinkIndex, layout: dict) -> list:
    """One warning per note with no outgoing link that resolves, no incoming link and outside any MOC (a MOC's
    links are incoming links). Notes of raw/, inbox/, mocs/ and templates/, index.md and log.md and confidential
    notes (never listed in a MOC) are not judged; the lists of index.md and log.md do not count as incoming links."""
    folders = [_link_key(folder) + "/" for folder in layout_paths(layout, LAYOUT_DIRS)]
    generated = generated_notes((note.path for note in notes), {"layout": layout})
    linked = set()
    for note in notes:
        if note.path in generated:
            continue
        targets = {index.resolve(target) for target in note.links} - {None, note.path}
        if targets:
            linked |= targets | {note.path}
    return [Finding("orphan", note.path, "sem links de entrada nem de saída e fora de qualquer MOC",
                    "relacione com relate ou ligue a uma nota nova; se a nota tem contexto, index a põe no MOC dele")
            for note in notes if note.path not in linked and note.path not in generated
            and not _link_key(note.path).startswith(tuple(folders)) and not is_confidential(note)]


def check_stale_inbox(entries: list, stale_after: int) -> list:
    """One warning per item of inbox_entries older than inbox_stale_days."""
    return [Finding("stale-inbox", entry["path"], f"na inbox há {entry['age_days']:.0f} dias (limite {stale_after})",
                    "processe a inbox (inbox list, ingest --move, inbox done)")
            for entry in entries if entry["stale"]]


def frontmatter_problem(note: Note):
    """Why the frontmatter of a note was not read (unclosed or invalid YAML), or None."""
    if note.frontmatter or not note.text.startswith("---"):
        return None
    return read_frontmatter(note.text)[2]


def check_frontmatter(notes: list) -> list:
    """One warning per note whose frontmatter is not read, or whose type is one of the skill's (NOTE_TYPES) and
    lacks title or created."""
    found = []
    for note in notes:
        problem = frontmatter_problem(note)
        missing = [] if problem or note.note_type not in NOTE_TYPES else [
            key for key in REQUIRED_FIELDS if not str(note.frontmatter.get(key) or "").strip()]
        if problem:
            found.append(Finding("frontmatter", note.path, problem, "corrija o YAML entre as linhas ---"))
        elif missing:
            found.append(Finding("frontmatter", note.path, f"type {note.note_type} sem {' e '.join(missing)}",
                                 f"acrescente {', '.join(missing)} ao frontmatter (references/note-types.md)"))
    return found


def check_secret_in_note(notes: list) -> list:
    """One warning per line of a note without confidential: true with a secret (find_secrets): "<path>:<line>"
    and the kind, never the value."""
    return [Finding("secret-in-note", f"{note.path}:{line}", kind,
                    "tire o valor da nota e guarde no gerenciador de senhas; no vault, só uma nota secret-ref "
                    "(references/confidential.md)")
            for note in notes if not is_confidential(note) for line, kind in find_secrets(note.text)]


def check_personal_data(notes: list, detectors=None, patterns=None) -> list:
    """One warning per line and kind of personal data (find_personal_data) in a note without confidential: true:
    "<path>:<line>" and the kind, never the value."""
    return [Finding("personal-data", f"{note.path}:{line}", kind,
                    "tire o dado da nota ou marque a nota com confidential: true; documento pessoal entra com "
                    "ingest --confidential (references/confidential.md)")
            for note in notes if not is_confidential(note)
            for line, kind in find_personal_data(note.text, detectors, patterns)]


def _repeats_group(pattern: str, i: int) -> bool:
    """True when the text at i repeats the group before it: "+", "*", "{n,}" or a count whose maximum is 2 or more
    ({n}, {n,m}); "?", {0,1}, {1} and anything that is not a quantifier do not."""
    if pattern.startswith(("+", "*"), i):
        return True
    m = re.compile(r"\{(\d*)(,(\d*))?\}").match(pattern, i)
    if not m or (m.group(2) is None and not m.group(1)):
        return False
    top = m.group(3) if m.group(2) is not None else m.group(1)
    return not top or int(top) >= 2


def nested_quantifier(pattern: str) -> bool:
    """True when a group with a repeated item inside ("+", "*" or "{n,}") is itself repeated (_repeats_group):
    (a+)+, (a*)*, (?:a+)+, (\\w+\\s?)+, (a+){20}, (a*){2,5}... the shapes that backtrack catastrophically. Read on
    the text, before compiling: escapes and [classes] are skipped. Best effort: overlapping alternatives such as
    (a|aa)+ are not detected."""
    repeat = re.compile(r"[+*]|\{\d*,\d*\}")
    stack, i, n = [], 0, len(pattern)
    while i < n:
        char = pattern[i]
        if char == "\\":
            i += 2
            continue
        if char == "[":
            i += 1
            i += 1 if i < n and pattern[i] == "^" else 0
            i += 1 if i < n and pattern[i] == "]" else 0
            while i < n and pattern[i] != "]":
                i += 2 if pattern[i] == "\\" else 1
        elif char == "(":
            stack.append(False)
        elif char == ")" and stack:
            inner = stack.pop()
            if inner and _repeats_group(pattern, i + 1):
                return True
            if stack:
                stack[-1] = stack[-1] or inner
        elif stack and repeat.match(pattern, i):
            stack[-1] = True
        i += 1
    return False


def compile_conflict_patterns(value):
    """(compiled patterns, problems) of conflict_patterns: a list of regex (a single string is one) with the group
    "base"; an invalid regex, one without "base", one longer than MAX_CONFLICT_PATTERN or with a nested
    quantifier (nested_quantifier) is a problem, never compiled nor matched, and the others still count."""
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else [] if not value else None
    if items is None:
        return [], [f"conflict_patterns precisa ser uma lista de regex: {one_line(value)}"]
    compiled, problems = [], []
    for item in items:
        text = str(item)
        if len(text) > MAX_CONFLICT_PATTERN:
            problems.append(f"conflict_patterns: regex com {len(text)} caracteres {one_line(text[:40])!r}... "
                            f"(limite {MAX_CONFLICT_PATTERN}) — não usado")
            continue
        if nested_quantifier(text):
            problems.append(f"conflict_patterns: regex com quantificador aninhado {one_line(text)!r} — como "
                            "(a+)+, trava a busca; não usado")
            continue
        try:
            pattern = re.compile(text)
        except re.error as e:
            problems.append(f"conflict_patterns: regex inválido {one_line(item)!r} ({e})")
            continue
        if "base" in pattern.groupindex:
            compiled.append(pattern)
        else:
            problems.append(f"conflict_patterns: regex sem o grupo base {one_line(item)!r}")
    return compiled, problems


class LintVault:
    """What the rules read, from a single scan of the vault (walk_vault): notes, the link index of the notes and
    of the attachments, every file path, the inbox items, the files folder (None = inaccessible), the valid
    conflict patterns and the config findings, each with the rule it affects."""
    __slots__ = ("attachments", "config", "detectors", "files", "inbox", "index", "notes", "paths", "patterns",
                 "personal_patterns", "values")

    def __init__(self, values: dict):
        vault, layout = vault_dir(values), values["layout"]
        contexts = values["contexts"] if isinstance(values["contexts"], dict) else {}
        inbox = layout_paths(layout, ("inbox",))[0] + "/"
        self.values, self.paths, self.notes, self.config = values, [], [], []
        attachments, inbox_items = [], []
        for path, rel in walk_vault(values):
            if hidden_note(rel):  # not a note (walk_notes), not judged
                continue
            self.paths.append(rel)
            if is_note(rel):
                self.notes.append(read_note(path, rel, contexts))
            else:
                attachments.append(rel)
            if rel.startswith(inbox) and visible_in_inbox(path.name):
                inbox_items.append((path, rel))
        self.index, self.attachments = LinkIndex(n.path for n in self.notes), LinkIndex(attachments)
        self.inbox = inbox_entries(vault, layout, values["inbox_stale_days"], items=inbox_items)
        self.patterns, problems = compile_conflict_patterns(values.get("conflict_patterns"))
        self.config += [("conflict-copy", Finding("config", "brain-config.yml", problem,
                                                  "corrija conflict_patterns (references/maintenance.md)"))
                        for problem in problems]
        self.detectors, self.personal_patterns, problems = compile_personal_data(values.get("lint"))
        self.config += [("personal-data", Finding("config", "brain-config.yml", problem,
                                                  "corrija lint.personal_data ou lint.personal_data_patterns "
                                                  "(references/confidential.md)"))
                        for problem in problems]
        self.files = Path(values["files"]) if values["files"] else None
        try:
            if self.files is None:
                raise OSError("sem files na configuração local")
            os.listdir(self.files)
        except OSError as e:
            self.files = None
            self.config.append(("missing-file", Finding(
                "config", "<files>", f"pasta files inacessível: {values['files'] or '(vazia)'} "
                f"({getattr(e, 'strerror', None) or e}); missing-file não rodou",
                "confira a pasta files e a permissão de leitura (brain.py doctor)")))


LINT_CHECKS = {  # rule -> check over the LintVault; "config" findings come from the LintVault itself
    "broken-link": lambda v: check_broken_link(v.notes, v.index, v.attachments),
    "conflict-copy": lambda v: check_conflict_copy(v.paths, v.patterns),
    "missing-file": lambda v: [] if v.files is None else check_missing_file(v.notes, v.files),
    "orphan": lambda v: check_orphan(v.notes, v.index, v.values["layout"]),
    "stale-inbox": lambda v: check_stale_inbox(v.inbox, v.values["inbox_stale_days"]),
    "frontmatter": lambda v: check_frontmatter(v.notes),
    "secret-in-note": lambda v: check_secret_in_note(v.notes),
    "personal-data": lambda v: check_personal_data(v.notes, v.detectors, v.personal_patterns),
    "config": lambda v: [],
}


def lint_rules(only=None) -> list:
    """The rules of --only ("a,b"), in report order; None = all. An unknown rule = BrainError (exit 2)."""
    if only is None:
        return list(LINT_SEVERITY)
    given = [rule.strip() for rule in str(only).split(",") if rule.strip()]
    if not given:
        raise BrainError(f"nenhuma regra em --only — regras: {', '.join(LINT_SEVERITY)}")
    unknown = [rule for rule in given if rule not in LINT_SEVERITY]
    if unknown:
        raise BrainError(f"regra desconhecida: {one_line(', '.join(unknown))} — regras: {', '.join(LINT_SEVERITY)}")
    return [rule for rule in LINT_SEVERITY if rule in given]


LINE_RULES = ("secret-in-note", "personal-data")  # rules whose path is "<caminho>:<linha>"


def finding_place(finding: Finding) -> tuple:
    """(path, line) to order findings: the line of LINE_RULES as a number (line 5 before line 17), else 0."""
    if finding.rule in LINE_RULES:
        path, _, line = finding.path.rpartition(":")
        if path and line.isdigit():
            return path, int(line)
    return finding.path, 0


def run_lint(values: dict, rules=None) -> list:
    """Findings of the rules (None = all) over a single scan of the vault, errors first; only reads."""
    rules = list(LINT_SEVERITY) if rules is None else rules
    vault = LintVault(values)
    found = [finding for affected, finding in vault.config if "config" in rules or affected in rules]
    for rule in rules:
        found += LINT_CHECKS[rule](vault)
    order = {rule: i for i, rule in enumerate(LINT_SEVERITY)}
    return sorted(found, key=lambda f: (f.severity != "error", order[f.rule]) + finding_place(f) + (f.detail,))


def lint_summary(findings: list) -> dict:
    return {severity: sum(1 for f in findings if f.severity == severity) for severity in LINT_LABELS}


def summary_text(summary: dict) -> str:
    return f"{summary['error']} erros, {summary['warn']} avisos"


def lint_item(values: dict, problems: dict) -> tuple:
    """The doctor line of lint: "OK|AVISO|ERRO lint — N erros, M avisos (rode lint)"."""
    if problems:
        return ("AVISO", "lint", "não conferido (brain-config.yml com valores fora do vault)")
    try:
        summary = lint_summary(run_lint(values))
    except (BrainError, OSError) as e:
        return ("AVISO", "lint", f"não conferido: {e}")
    status = "ERRO" if summary["error"] else "AVISO" if summary["warn"] else "OK"
    return (status, "lint", f"{summary_text(summary)} (rode lint)")


def cmd_lint(args, config_home=None) -> int:
    rules = lint_rules(args.only)
    findings = run_lint(load_config(config_home)["values"], rules)
    summary = lint_summary(findings)
    if args.json:
        print_json({"findings": [f.as_dict() for f in findings], "summary": summary})
    else:
        for f in findings:
            print(f"{LINT_LABELS[f.severity]} {f.rule} {one_line(f.path)} — {f.detail} (sugestão: {f.suggestion})")
        print(summary_text(summary))
    return 1 if summary["error"] else 0


# ---------------------------------------------------------------- cli

def add_include_confidential(p: argparse.ArgumentParser):
    p.add_argument(INCLUDE_CONFIDENTIAL, action="store_true",
                   help="inclui notas com confidential: true (só quando a pessoa pede; references/confidential.md)")


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
                     "busca, fluxo de guardar, inbox, processadores, manutenção (lint) e exportação para o NotebookLM."))
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
                                    "(cria um contexto); para buscar a palavra add, use 'context -- add' (depois do -- tudo é consulta)."))
    p.add_argument("query", nargs="+", metavar="QUERY")
    p.add_argument("--context", help="só notas deste contexto na busca; o MOC dele entra primeiro")
    p.add_argument("--hops", type=int, default=1, help=f"passos de link a partir da busca (0..{MAX_HOPS}, padrão 1)")
    p.add_argument("--limit", type=int, default=8, help="resultados da busca (padrão 8)")
    p.add_argument("--max-chars", type=int, default=40000, help="soma máxima do conteúdo das notas (padrão 40000)")
    add_include_confidential(p)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("doctor", help="o que está configurado, o que funciona e o que falta")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("export-notebooklm", help="pacote de um MOC para subir no NotebookLM, fora do vault; só lê o vault")
    p.add_argument("moc", metavar="MOC", help="nome do contexto (ex.: college) ou caminho do MOC no vault")
    p.add_argument("--out", required=True, metavar="PASTA", help="pasta vazia (ou nova) fora do vault")
    p.add_argument("--hops", type=int, default=1,
                   help=f"passos de link a partir das notas citadas pelo MOC (0..{MAX_HOPS}, padrão 1)")
    p.add_argument("--combined", action="store_true", help="grava também combined.md, com todas as notas")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("search", help="busca por termos, com pontuação (título 3, tags 2, corpo 1); só leitura")
    p.add_argument("query", nargs="+", metavar="QUERY")
    p.add_argument("--context", help="só notas deste contexto")
    p.add_argument("--type", help="só notas com este frontmatter.type")
    p.add_argument("--tag", help="só notas com esta tag")
    p.add_argument("--limit", type=int, default=10)
    add_include_confidential(p)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("related", help="notas parecidas com uma nota ou com um texto, com os motivos; só leitura")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--note", metavar="CAMINHO", help="caminho (ou nome) da nota de referência")
    group.add_argument("--text", metavar="TEXTO", help="texto livre de referência")
    p.add_argument("--limit", type=int, default=10)
    add_include_confidential(p)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("links", help="links de saída, backlinks e links quebrados de uma nota; só leitura")
    p.add_argument("note", metavar="NOTA", help="caminho ou nome da nota")
    add_include_confidential(p)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("ingest", help="guarda uma fonte (arquivo ou URL): cópia em files e nota de fonte em raw/")
    p.add_argument("source", metavar="FONTE", help="arquivo local ou URL http(s)")
    p.add_argument("--context", help="contexto da fonte (sem ele, a cópia vai para <files>/inbox)")
    p.add_argument("--title", help="título da nota de fonte (padrão: o nome do arquivo ou a URL)")
    p.add_argument("--text-file", metavar="ARQ", help="texto extraído da fonte (UTF-8), sob '## Extracted text'")
    p.add_argument("--move", action="store_true", help="item da inbox: move para files em vez de copiar")
    p.add_argument("--kind", help="tipo da fonte para o processador (padrão: detectado; youtube, video, audio, pdf)")
    p.add_argument("--no-process", action="store_true", help="não roda o processador do tipo")
    p.add_argument("--timestamps", action="store_true", help="legendas com '[mm:ss]' (no YouTube, link para o trecho)")
    p.add_argument("--confidential", action="store_true",
                   help="documento confidencial: guarda o arquivo opaco (tamanho e sha256), nunca roda processador")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("process", help="roda o processador do tipo da fonte e devolve o texto (references/processors.md)")
    p.add_argument("source", metavar="ENTRADA", help="arquivo local ou URL http(s)")
    p.add_argument("--kind", help="tipo da fonte (padrão: detectado; youtube, video, audio, pdf)")
    p.add_argument("--out", metavar="ARQ", help="grava o texto neste arquivo novo (fora do vault) em vez do stdout")
    p.add_argument("--timestamps", action="store_true", help="legendas com '[mm:ss]' (no YouTube, link para o trecho)")
    p = sub.add_parser("new-note", help="cria uma nota a partir do modelo do tipo; nunca sobrescreve")
    p.add_argument("--type", required=True, help=" | ".join(NOTE_TYPES))
    p.add_argument("--title", required=True)
    p.add_argument("--context", help="contexto (sem ele, a nota vai para para.resources)")
    p.add_argument("--source", metavar="CAMINHO_OU_URL", help="nota de fonte (raw/...) ou URL")
    p.add_argument("--tags", metavar="A,B", help="tags separadas por vírgula")
    p.add_argument("--vault-ref", metavar="REF",
                   help="só com --type secret-ref: onde o segredo está no gerenciador (<esquema>://<caminho>)")
    p.add_argument("--confidential", action="store_true", help="marca a nota com confidential: true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("relate", help="acrescenta '- [[PARA]] — motivo' na seção Relations de DE")
    p.add_argument("source", metavar="DE", help="caminho ou nome da nota")
    p.add_argument("target", metavar="PARA", help="caminho ou nome da nota")
    p.add_argument("--why", required=True, help="motivo da relação (ex.: aplica, contradiz, exemplo de)")
    p.add_argument("--both", action="store_true", help="também em PARA, apontando para DE")
    p = sub.add_parser("index", help="regenera as regiões geradas dos MOCs e do index.md")
    p.add_argument("--context", help="só o MOC deste contexto (e o index.md)")
    p = sub.add_parser("capture", help="nota rápida na inbox, com data e hora no nome")
    p.add_argument("text", metavar="TEXTO")
    p.add_argument("--context", help="contexto da captura (vai no frontmatter)")
    p.add_argument("--print", action="store_true",
                   help="só mostra o caminho e o conteúdo, sem escrever nada (para o conector do provedor)")
    p.add_argument("--inbox", metavar="PASTA", help="só com --print, quando o vault ou o brain-config.yml não pode ser lido: pasta da inbox (padrão: inbox)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("inbox", help="itens da inbox (list) e saída de um item já guardado (done)")
    inbox = p.add_subparsers(dest="inbox_command", required=True)
    q = inbox.add_parser("list", help="itens da inbox, do mais antigo para o mais novo; só leitura")
    q.add_argument("--json", action="store_true")
    q = inbox.add_parser("done", help="move um item de texto ou link já guardado para raw/processed/AAAA-MM/")
    q.add_argument("item", metavar="ITEM", help="caminho do item (ex.: inbox/<nome>)")
    q.add_argument("--note", metavar="CAMINHO", help="nota criada a partir do item (vai no log)")
    p = sub.add_parser("lint", help="achados de manutenção do vault (links, conflitos, órfãs, inbox); só leitura")
    p.add_argument("--json", action="store_true")
    p.add_argument("--only", metavar="REGRA,...", help=f"só estas regras: {', '.join(LINT_SEVERITY)}")
    p = sub.add_parser("backup", help="zip datado e verificado do vault em cada destino, com rotação (references/backup.md)",
                       description=("backup: um zip por destino (backup_targets ou --dest), gravado como .partial, "
                                    "verificado e renomeado; depois a rotação mantém backup.keep por destino. "
                                    "Também: backup list, backup verify [ZIP] e backup target add PASTA."))
    p.add_argument("--dest", action="append", metavar="PASTA", help="destino desta execução (repetível; substitui backup_targets)")
    p.add_argument("--with-files", action="store_true", help="inclui a pasta files (nome -files.zip)")
    p.add_argument("--json", action="store_true")
    backup = p.add_subparsers(dest="backup_command")
    q = backup.add_parser("list", help="backups de cada destino, do mais novo para o mais velho; só leitura")
    q.add_argument("--json", action="store_true")
    q = backup.add_parser("verify", help="confere um zip (ou o mais novo de cada destino) com o manifesto")
    q.add_argument("zip", nargs="?", metavar="ZIP")
    q.add_argument("--json", action="store_true")
    q = backup.add_parser("target", help="destinos de backup desta máquina (configuração local)")
    target = q.add_subparsers(dest="target_command", required=True)
    t = target.add_parser("add", help="acrescenta PASTA (fora do vault e da pasta files) a backup_targets")
    t.add_argument("folder", metavar="PASTA")
    p = sub.add_parser("restore", help="recupera uma nota como arquivo novo, ou o backup inteiro numa pasta nova")
    p.add_argument("note", nargs="?", metavar="NOTA", help="caminho da nota relativo ao vault")
    p.add_argument("--from", dest="source", required=True, metavar="ZIP", help="zip do backup")
    p.add_argument("--to", metavar="PASTA", help="pasta nova ou vazia, fora do vault, para o backup inteiro")
    p.add_argument("--json", action="store_true")
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
        if args.command == "export-notebooklm":
            return cmd_export_notebooklm(args)
        if args.command == "search":
            return cmd_search(args)
        if args.command == "related":
            return cmd_related(args)
        if args.command == "links":
            return cmd_links(args)
        if args.command == "ingest":
            return cmd_ingest(args)
        if args.command == "process":
            return cmd_process(args)
        if args.command == "new-note":
            return cmd_new_note(args)
        if args.command == "relate":
            return cmd_relate(args)
        if args.command == "index":
            return cmd_index(args)
        if args.command == "capture":
            return cmd_capture(args)
        if args.command == "inbox":
            return cmd_inbox_list(args) if args.inbox_command == "list" else cmd_inbox_done(args)
        if args.command == "lint":
            return cmd_lint(args)
        if args.command == "backup":
            command = getattr(args, "backup_command", None)
            if command == "list":
                return cmd_backup_list(args)
            if command == "verify":
                return cmd_backup_verify(args)
            if command == "target":
                return cmd_backup_target_add(args)
            return cmd_backup(args)
        if args.command == "restore":
            return cmd_restore(args)
    except BrainError as e:
        print(f"erro: {e}", file=sys.stderr)
        return e.code
    except OSError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
