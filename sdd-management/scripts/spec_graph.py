#!/usr/bin/env python3
"""Deterministic tooling for the sdd-management skill (stdlib only). Run with --help."""
from __future__ import annotations

import argparse
import datetime as dt
import heapq
import json
import re
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict, deque
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_DIR / "references"

SPEC_ID_RE = re.compile(r"^SPEC-\d{4,}$")
ADR_ID_RE = re.compile(r"^ADR-\d{4,}$")
SPEC_REF_RE = re.compile(r"\bSPEC-\d{4,}\b")
CONTRACT_REF_RE = re.compile(r"^(SPEC-\d{4,})(?:@v?(\d+))?$")
TEST_ID_RE = re.compile(r"\b(?:CH|UT|IT|CT|E2E)-\d{2,}\b")
TEST_DEF_RE = re.compile(r"\*\*((?:CH|UT|IT|CT|E2E)-\d{2,})\*\*")
TEST_TAG_RE = re.compile(r"\b(SPEC-\d{4,}):((?:CH|UT|IT|CT|E2E)-\d{2,})\b")
PLACEHOLDER_RE = re.compile(r"\{\{[^{}]*\}\}")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
CONVENTIONAL_RE = re.compile(r"^(\w+)(?:\([^)]*\))?!?:")
WILDCARD_RE = re.compile(r"[*?]")
CHECKBOX_RE = re.compile(r"^\s*[-*] \[( |x|X)\]", re.M)
UNCHECKED_RE = re.compile(r"^\s*[-*] \[ \]", re.M)

STATUSES = ("proposed", "approved", "in-progress", "implemented", "deprecated")
OPEN = {"proposed", "approved", "in-progress"}
APPROVED_PLUS = {"approved", "in-progress", "implemented"}
DONE = {"implemented", "deprecated"}
STATUS_RANK = {"in-progress": 0, "approved": 1, "proposed": 2}
TIERS = ("lite", "full", "epic")
TYPES = ("feature", "fix", "refactor", "migration", "foundation")
TYPES_BY_TIER = {
    "lite": {"feature", "fix", "refactor"},
    "full": set(TYPES),
    "epic": {"feature", "migration", "foundation"},
}
SIZES = ("S", "M", "L")
ADR_STATUSES = ("proposed", "accepted", "superseded", "rejected")
ADR_ORIGINS = ("decision", "as-is")
GATE_ROWS = ("G0", "G1", "G2", "G3", "G4", "G5", "H2", "G6", "G7")
DELIVERY_SUBSECTIONS = ("O que foi entregue", "Como foi feito", "Verificação", "Definição de Pronto", "Deploy", "Pendências")
IMPEDIMENT_TYPES = ("spec", "decisão", "trabalho", "externo", "falha")
IMPEDIMENT_COLUMNS = ("ID", "Aberto em", "Fase/Gate", "Tipo", "Descrição", "Tentativas", "Responsável", "Resolução", "Fechado em")
IMP_ID_RE = re.compile(r"^IMP-(\d{2,})$")
ADR_REF_RE = re.compile(r"\bADR-\d{4,}\b")
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
GATE_STATUSES = ("N/A", "FAIL", "PENDING", "PASS")
LEGACY_DIRS = ("proposed", "approved", "implemented", "deprecated")
RED_TYPES = {"test"}
GREEN_TYPES = {"feat", "fix", "refactor", "perf"}

DEFAULT_TEST_PATHS = [
    "**/test/**", "**/tests/**", "**/__tests__/**", "**/e2e/**", "**/playwright/**", "**/cypress/**",
    "**/*Tests/**", "**/*Test/**", "**/*.test.*", "**/*.spec.*", "**/*.e2e.*",
    "**/*Tests.*", "**/*Test.*", "**/test_*.py", "**/*_test.*",
]
DEFAULT_SCOPE_EXEMPT = ["docs/specs/**", "docs/adr/**"]
DEFAULT_MANIFESTS = [
    "**/package.json", "**/*.csproj", "**/*.fsproj", "**/Directory.Packages.props", "**/packages.config",
    "**/requirements*.txt", "**/pyproject.toml", "**/Pipfile", "**/go.mod", "**/pom.xml",
    "**/build.gradle", "**/build.gradle.kts", "**/Gemfile", "**/Cargo.toml", "**/composer.json",
    "**/pubspec.yaml", "**/Package.swift", "**/Podfile",
]

# (heading keyword, must have content before approval)
REQUIRED_SECTIONS = {
    "full": [
        ("Visão Geral", True), ("Motivação", True), ("Dependências", True),
        ("Decisão Arquitetural", True), ("Requisitos Não-Funcionais", True),
        ("Contrato", True), ("Plano de Testes", True), ("Plano de Rollout", True),
        ("Questões em Aberto", True), ("Aprovação", False), ("Checklist", False),
        ("Registro de Gates", False), ("Registro de Impedimentos", False),
        ("Relatório de Entrega", False), ("Emendas", False),
    ],
    "lite": [
        ("Problema", True), ("Causa Raiz", True), ("Mudança Proposta", True),
        ("Plano de Testes", True), ("Questões em Aberto", True), ("Aprovação", False),
        ("Checklist", False), ("Registro de Gates", False), ("Registro de Impedimentos", False),
        ("Relatório de Entrega", False), ("Emendas", False),
    ],
    "epic": [
        ("Visão", True), ("Escopo", True), ("Arquitetura Alvo", True), ("Decomposição", True),
        ("Estratégia de Entrega", True), ("Riscos", True), ("Critérios de Aceite", True),
        ("Questões em Aberto", True), ("Aprovação", False), ("Registro de Impedimentos", False),
        ("Relatório de Entrega", False), ("Emendas", False),
    ],
}


# ---------------------------------------------------------------- text utils

def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def slugify(text: str, limit: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:limit].rstrip("-") or "spec"


def today() -> str:
    return dt.date.today().isoformat()


def valid_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def parse_scalar(value: str):
    value = value.strip()
    if not value:
        return ""
    if value[0] == '"':
        m = re.match(r'^"((?:[^"\\]|\\.)*)"', value)
        return json.loads('"' + m.group(1) + '"') if m else value[1:]
    if value[0] == "'":
        m = re.match(r"^'((?:[^']|'')*)'", value)
        return m.group(1).replace("''", "'") if m else value[1:]
    value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [parse_scalar(item) for item in inner.split(",") if item.strip()]
    return value


def parse_yaml_subset(text: str) -> dict:
    """Flat `key: value`, inline `[a, b]` lists and `- item` block lists."""
    data, key = {}, None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", raw)
        if item and key is not None:
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(parse_scalar(item.group(1)))
            continue
        pair = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", raw)
        if pair:
            key = pair.group(1)
            data[key] = parse_scalar(pair.group(2))
    return data


def fmt_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(fmt_value(v) for v in value) + "]"
    value = str(value)
    if value == "":
        return ""
    if (re.search(r":\s|\s#|^[\[\]{}&*!|>'\"%@`,-]|^\s|\s$", value)
            or value.lower() in ("true", "false", "null", "yes", "no", "~")):
        return json.dumps(value, ensure_ascii=False)
    return value


def split_frontmatter(text: str):
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    return None, text


def set_meta(text: str, key: str, value) -> str:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError("arquivo sem frontmatter")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("frontmatter sem '---' de fechamento")
    rendered = f"{key}: {fmt_value(value)}".rstrip()
    for i in range(1, end):
        if re.match(rf"^{re.escape(key)}\s*:", lines[i]):
            j = i + 1
            while j < end and re.match(r"^\s*-\s+", lines[j]):
                j += 1
            lines[i:j] = [rendered]
            return "\n".join(lines)
    lines.insert(end, rendered)
    return "\n".join(lines)


def parse_sections(body: str):
    sections, heading, buf, fence = [], None, [], False
    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            if heading is not None:
                sections.append((heading, "\n".join(buf)))
            heading, buf = line[3:].strip(), []
        elif heading is not None:
            buf.append(line)
    if heading is not None:
        sections.append((heading, "\n".join(buf)))
    return sections


def parse_tables(content: str):
    raw_tables, cur = [], []
    for line in content.split("\n"):
        s = line.strip()
        if s.startswith("|") and s.endswith("|") and len(s) > 1:
            cur.append([c.strip() for c in CELL_SPLIT_RE.split(s[1:-1])])
        elif cur:
            raw_tables.append(cur)
            cur = []
    if cur:
        raw_tables.append(cur)
    tables = []
    for t in raw_tables:
        if len(t) >= 2 and all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in t[1] if c):
            tables.append((t[0], t[2:]))
    return tables


def test_sort_key(tid: str):
    prefix, num = tid.split("-")
    return (["CH", "UT", "IT", "CT", "E2E"].index(prefix), int(num))


def parse_subsections(content: str):
    subs, heading, buf = [], None, []
    for line in content.split("\n"):
        if line.startswith("### "):
            if heading is not None:
                subs.append((heading, "\n".join(buf)))
            heading, buf = line[4:].strip(), []
        elif heading is not None:
            buf.append(line)
    if heading is not None:
        subs.append((heading, "\n".join(buf)))
    return subs


def find_sub(subs, keyword: str):
    key = norm(keyword)
    return next((content for heading, content in subs if key in norm(heading)), None)


def md_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


# ---------------------------------------------------------------- globs

def glob_regex(pattern: str):
    pattern = pattern.strip()
    if pattern.startswith("./"):
        pattern = pattern[2:]
    if not WILDCARD_RE.search(pattern):
        return re.compile("^" + re.escape(pattern.rstrip("/")) + "(?:/.*)?$")
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches_any(path: str, patterns) -> bool:
    return any(glob_regex(p).match(path) for p in patterns)


def literal_prefix(pattern: str) -> str:
    m = WILDCARD_RE.search(pattern)
    return pattern[:m.start()] if m else pattern


def patterns_overlap(a: str, b: str) -> bool:
    """Conservative: may report overlap that doesn't exist, never misses a real one."""
    wa, wb = bool(WILDCARD_RE.search(a)), bool(WILDCARD_RE.search(b))
    if not wa and not wb:
        a2, b2 = a.rstrip("/"), b.rstrip("/")
        return a2 == b2 or a2.startswith(b2 + "/") or b2.startswith(a2 + "/")
    if wa != wb:
        wild, lit = (a, b) if wa else (b, a)
        lit = lit.rstrip("/")
        prefix = literal_prefix(wild)
        return (bool(glob_regex(wild).match(lit))
                or prefix.startswith(lit + "/")
                or ("**" in wild and lit.startswith(prefix)))
    pa, pb = literal_prefix(a), literal_prefix(b)
    return pa.startswith(pb) or pb.startswith(pa)


# ---------------------------------------------------------------- model

class Doc:
    def __init__(self, path: Path, text: str):
        self.path = path
        self.text = text
        fm, self.body = split_frontmatter(text)
        self.has_frontmatter = fm is not None
        self.meta = parse_yaml_subset(fm) if fm is not None else {}
        self._sections = None

    def scalar(self, key: str) -> str:
        v = self.meta.get(key, "")
        return v.strip() if isinstance(v, str) else ""

    def list(self, key: str):
        v = self.meta.get(key)
        if isinstance(v, list):
            return [x.strip() for x in v if isinstance(x, str) and x.strip()]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    @property
    def id(self) -> str:
        return self.scalar("id")

    @property
    def title(self) -> str:
        return self.scalar("title")

    @property
    def status(self) -> str:
        return self.scalar("status").lower()

    @property
    def tier(self) -> str:
        return self.scalar("tier").lower()

    @property
    def type(self) -> str:
        return self.scalar("type").lower()

    @property
    def legacy(self) -> bool:
        return self.scalar("legacy").lower() in ("true", "yes", "1")

    def section(self, keyword: str):
        if self._sections is None:
            self._sections = parse_sections(self.body)
        key = norm(keyword)
        for heading, content in self._sections:
            if key in norm(heading):
                return content
        return None


def contract_refs(doc: Doc):
    refs = []
    for raw in doc.list("consumes_contract"):
        m = CONTRACT_REF_RE.match(raw)
        if m:
            refs.append((m.group(1), int(m.group(2)) if m.group(2) else None, raw))
        else:
            refs.append((None, None, raw))
    return refs


def contract_version(doc: Doc) -> int:
    try:
        return int(doc.scalar("contract_version") or 1)
    except ValueError:
        return 1


def plan_test_ids(doc: Doc):
    plan = COMMENT_RE.sub("", doc.section("Plano de Testes") or "")
    return sorted(set(TEST_ID_RE.findall(plan)), key=test_sort_key)


class Project:
    def __init__(self, root: Path):
        self.root = root
        self.specs_dir = root / "docs" / "specs"
        self.adr_dir = root / "docs" / "adr"
        self.config = self._load_config()
        self.specs = {}
        self.adrs = {}
        self.load_issues = []
        self._load()

    def _load_config(self) -> dict:
        path = self.specs_dir / "sdd-config.yml"
        return parse_yaml_subset(path.read_text(encoding="utf-8")) if path.exists() else {}

    def cfg(self, key: str, default: str = "") -> str:
        v = self.config.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else default

    def cfg_list(self, key: str, default):
        v = self.config.get(key)
        if isinstance(v, list) and v:
            return [x for x in v if x]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return list(default)

    def max_parallel(self) -> int:
        try:
            return max(0, int(self.cfg("max_parallel", "0")))
        except ValueError:
            return 0

    def _load_dir(self, folder: Path, prefix: str, store: dict):
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("*.md")):
            if path.name in ("INDEX.md", "README.md"):
                continue
            doc = Doc(path, path.read_text(encoding="utf-8"))
            if not doc.has_frontmatter:
                self.load_issues.append(("ERROR", path.name, "arquivo sem frontmatter — use `new`/`new-adr` ou `migrate`"))
                continue
            key = doc.id or path.stem
            if not key.startswith(prefix + "-"):
                self.load_issues.append(("WARN", path.name, f"id '{key}' não segue o padrão {prefix}-NNNN"))
            if key in store:
                self.load_issues.append(("ERROR", key, f"ID duplicado em {path.name} e {store[key].path.name}"))
                continue
            store[key] = doc

    def _load(self):
        self._load_dir(self.specs_dir, "SPEC", self.specs)
        self._load_dir(self.adr_dir, "ADR", self.adrs)
        legacy = [d for d in LEGACY_DIRS if (self.specs_dir / d).is_dir() and any((self.specs_dir / d).glob("*.md"))]
        if legacy:
            self.load_issues.append(("WARN", "docs/specs", f"layout legado encontrado ({', '.join(d + '/' for d in legacy)}) — rode `migrate`"))

    def children(self, epic_id: str):
        return sorted((d for d in self.specs.values() if d.scalar("parent") == epic_id), key=lambda d: d.id)

    def consumers(self, spec_id: str):
        out = []
        for d in sorted(self.specs.values(), key=lambda d: d.id):
            for pid, ver, _ in contract_refs(d):
                if pid == spec_id:
                    out.append((d, ver))
        return out

    def next_number(self, prefix: str) -> int:
        pattern = re.compile(rf"^{prefix}-(\d+)")
        folder, store = (self.specs_dir, self.specs) if prefix == "SPEC" else (self.adr_dir, self.adrs)
        nums = [0]
        if folder.is_dir():
            nums += [int(m.group(1)) for p in folder.rglob("*.md") for m in [pattern.match(p.name)] if m]
        nums += [int(m.group(1)) for k in store for m in [pattern.match(k)] if m]
        return max(nums) + 1

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)


def find_root(start: Path) -> Path:
    start = start.resolve()
    for p in [start, *start.parents]:
        if (p / "docs" / "specs").is_dir() or (p / ".git").exists():
            return p
    return start


def die(msg: str, code: int = 2):
    print(f"erro: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- validation (G0)

def validate(project: Project, only=None):
    issues = []

    def add(level, subject, msg):
        issues.append((level, subject, msg))

    for level, subject, msg in project.load_issues:
        if only is None or subject in only:
            add(level, subject, msg)
    for sid in sorted(project.specs):
        if only is None or sid in only:
            validate_spec(project, project.specs[sid], add)
    for cycle in find_cycles(project):
        if only is None or any(n in only for n in cycle):
            add("ERROR", cycle[0], "ciclo em depends_on: " + " → ".join(cycle))
    for aid in sorted(project.adrs):
        if only is None or aid in only:
            validate_adr(project, project.adrs[aid], add)
    return issues


def validate_spec(project: Project, doc: Doc, add):
    sid = doc.id
    if not SPEC_ID_RE.match(sid):
        add("ERROR", sid or doc.path.name, "id inválido (esperado SPEC-NNNN)")
        return
    if doc.path.stem != sid and not doc.path.name.startswith(sid + "-"):
        add("ERROR", sid, f"nome do arquivo deve começar com '{sid}-' (atual: {doc.path.name})")
    if not doc.title:
        add("ERROR", sid, "title vazio")
    if doc.tier not in TIERS:
        add("ERROR", sid, f"tier inválido '{doc.tier}' (lite | full | epic)")
        return
    if doc.status not in STATUSES:
        add("ERROR", sid, f"status inválido '{doc.status}' ({' | '.join(STATUSES)})")
        return
    if not valid_date(doc.scalar("created")):
        add("ERROR", sid, "created deve ser uma data YYYY-MM-DD")
    placeholders = sorted(set(PLACEHOLDER_RE.findall(COMMENT_RE.sub("", doc.text))))
    if placeholders:
        shown = ", ".join(p[:40] for p in placeholders[:4]) + (" …" if len(placeholders) > 4 else "")
        add("ERROR", sid, f"{len(placeholders)} marcador(es) {{{{...}}}} não preenchido(s): {shown}")
    validate_refs(project, doc, add)
    if doc.legacy:
        if doc.status in OPEN:
            add("WARN", sid, "spec legada aberta — reescreva no template atual (depends_on, touches, seções) e remova `legacy`")
        return
    allowed_types = TYPES_BY_TIER[doc.tier]
    if not doc.type:
        add("ERROR", sid, f"type obrigatório ({' | '.join(t for t in TYPES if t in allowed_types)})")
    elif doc.type not in TYPES:
        add("ERROR", sid, f"type inválido '{doc.type}' ({' | '.join(TYPES)})")
    elif doc.type not in allowed_types:
        add("ERROR", sid, f"type {doc.type} não é permitido no tier {doc.tier} "
                          f"({' | '.join(t for t in TYPES if t in allowed_types)})")
    if doc.status in APPROVED_PLUS and not (doc.scalar("approved_by") and valid_date(doc.scalar("approved_at"))):
        add("ERROR", sid, "status exige aprovação humana registrada (approved_by + approved_at) — H1")
    for keyword, must_fill in REQUIRED_SECTIONS[doc.tier]:
        content = doc.section(keyword)
        if content is None:
            add("ERROR", sid, f"seção obrigatória ausente: '{keyword}'")
        elif must_fill and not COMMENT_RE.sub("", content).strip():
            add("ERROR", sid, f"seção vazia: '{keyword}'")
    validate_questions(doc, add)
    validate_impediments(project, doc, add)
    if doc.tier == "epic":
        validate_epic(project, doc, add)
    else:
        validate_executable(project, doc, add)


def validate_refs(project: Project, doc: Doc, add):
    sid, specs = doc.id, project.specs
    parent = doc.scalar("parent")
    if parent:
        if doc.tier == "epic":
            add("ERROR", sid, "épico não pode ter parent (use depends_on entre épicos)")
        elif parent not in specs:
            add("ERROR", sid, f"parent {parent} não existe")
        elif specs[parent].tier != "epic":
            add("ERROR", sid, f"parent {parent} não é um épico")
    for dep in doc.list("depends_on"):
        if dep == sid:
            add("ERROR", sid, "depends_on referencia a própria spec")
        elif dep not in specs:
            add("ERROR", sid, f"depends_on: {dep} não existe")
        elif specs[dep].status == "deprecated" and doc.status in OPEN:
            add("ERROR", sid, f"depende de {dep}, que está deprecated — reavalie a dependência")
    for pid, ver, raw in contract_refs(doc):
        if pid is None:
            add("ERROR", sid, f"consumes_contract inválido '{raw}' (formato SPEC-NNNN@versão)")
            continue
        if pid == sid:
            add("ERROR", sid, "consumes_contract referencia a própria spec")
            continue
        provider = specs.get(pid)
        if provider is None:
            add("ERROR", sid, f"consumes_contract: {pid} não existe")
            continue
        if provider.tier == "epic":
            add("ERROR", sid, f"{pid} é um épico e não tem contrato — aponte para a spec filha que define o contrato")
        current = contract_version(provider)
        if ver is None:
            add("ERROR", sid, f"fixe a versão do contrato consumido: {pid}@{current}")
        elif ver > current:
            add("ERROR", sid, f"{pid}@{ver} não existe (versão atual do contrato: v{current})")
        elif ver < current and doc.status in OPEN:
            add("WARN", sid, f"contrato de {pid} mudou (v{ver} → v{current}): revise esta spec e atualize o pin")
        if provider.status == "deprecated" and doc.status in OPEN:
            add("ERROR", sid, f"consome contrato de {pid}, que está deprecated")
    for adr in doc.list("adrs"):
        if adr not in project.adrs:
            add("ERROR", sid, f"adrs: {adr} não existe em docs/adr/")
        elif project.adrs[adr].status in ("superseded", "rejected") and doc.status in OPEN:
            add("WARN", sid, f"{adr} está {project.adrs[adr].status} — confirme se a decisão ainda vale")


def validate_executable(project: Project, doc: Doc, add):
    sid, status, tier = doc.id, doc.status, doc.tier
    size = doc.scalar("size").upper()
    if size not in SIZES:
        add("ERROR", sid, "size deve ser S ou M (L não é permitido)")
    elif size == "L":
        add("ERROR", sid, "size L é grande demais para um agente — quebre em um épico com specs S/M")
    elif tier == "lite" and size != "S":
        add("WARN", sid, "spec lite deveria ser S — se for maior, promova para full")
    touches = doc.list("touches")
    if not touches:
        add("ERROR" if status in APPROVED_PLUS else "WARN", sid,
            "touches vazio — declare os globs que a spec pode alterar (paralelismo e G4 dependem disso)")
    for pattern in touches:
        if pattern.startswith("**"):
            add("WARN", sid, f"touches '{pattern}' começa com ** e conflita com qualquer spec — seja específico")

    plan = COMMENT_RE.sub("", doc.section("Plano de Testes") or "")
    defined = set(TEST_ID_RE.findall(plan))
    dups = sorted(t for t, n in Counter(TEST_DEF_RE.findall(plan)).items() if n > 1)
    if dups:
        add("WARN", sid, f"IDs de teste definidos mais de uma vez: {', '.join(dups)}")
    if not defined:
        add("ERROR", sid, "plano de testes sem IDs (UT-01, IT-01, CT-01…) — No Test = No Handoff")
    kinds = {t.split("-")[0] for t in defined}
    user_facing = doc.scalar("user_facing").lower()
    if tier == "full":
        if "UT" not in kinds:
            add("ERROR", sid, "tier full exige ao menos um teste unitário (UT-xx)")
        if "IT" not in kinds:
            add("ERROR", sid, "tier full exige ao menos um teste de integração (IT-xx)")
        if (contract_refs(doc) or project.consumers(sid)) and "CT" not in kinds:
            add("ERROR", sid, "spec consome ou fornece contrato para outra spec: exige teste de contrato (CT-xx)")
        if user_facing not in ("true", "false"):
            add("ERROR", sid, "user_facing deve ser true ou false (true = altera jornada do usuário em UI ou API pública)")
        elif user_facing == "true" and "E2E" not in kinds:
            add("ERROR", sid, "user_facing: true exige ao menos um teste E2E (E2E-xx) da jornada afetada")
        if doc.type == "migration" and not doc.list("adrs"):
            add("ERROR", sid, "type migration exige o ADR da nova arquitetura/padrão em adrs")
        validate_contract_map(doc, defined, add)
    else:
        if project.consumers(sid):
            add("WARN", sid, "outra spec consome o contrato desta spec lite — contrato público pede tier full")
        if user_facing == "true" and "E2E" not in kinds:
            add("WARN", sid, "defeito em jornada de usuário: o teste de regressão deveria ser E2E (E2E-xx)")

    checklist = doc.section("Checklist")
    if checklist is not None:
        boxes = CHECKBOX_RE.findall(COMMENT_RE.sub("", checklist))
        if status in ("in-progress", "implemented") and not boxes:
            add("ERROR", sid, "checklist de implementação vazio — deve ser preenchido na fase PLAN")
        elif status == "approved" and not boxes:
            add("WARN", sid, "checklist de implementação ainda não preenchido (fase PLAN)")
        unchecked = sum(1 for b in boxes if b == " ")
        if status == "implemented" and unchecked:
            add("ERROR", sid, f"{unchecked} item(ns) do checklist não marcado(s)")

    gates = gate_table(doc)
    if gates is not None:
        missing = [g for g in GATE_ROWS if g not in gates]
        if missing:
            add("ERROR", sid, f"registro de gates sem as linhas: {', '.join(missing)}")
        for g, info in gates.items():
            if info["status"] not in GATE_STATUSES:
                add("ERROR", sid, f"gate {g}: status '{info['status']}' inválido (PENDING | PASS | FAIL | N/A)")
            elif info["status"] in ("PASS", "N/A") and not info["evidence"]:
                add("ERROR", sid, f"gate {g} marcado {info['status']} sem evidência")
        if status in APPROVED_PLUS and gates.get("G0", {}).get("status") != "PASS":
            add("WARN", sid, "G0 não registrado como PASS no registro de gates")
        if status == "implemented":
            pending = [g for g in GATE_ROWS if gates.get(g, {}).get("status") not in ("PASS", "N/A")]
            if pending:
                add("ERROR", sid, f"implemented exige todos os gates PASS/N/A — pendentes: {', '.join(pending)}")

    if status == "implemented":
        validate_delivery(doc, defined, add)


def validate_delivery(doc: Doc, defined, add):
    """Relatório de Entrega: what was done, how, and proof that every planned test passed (Definition of Done)."""
    sid = doc.id
    content = doc.section("Relatório de Entrega")
    if content is None:
        return
    subs = parse_subsections(COMMENT_RE.sub("", content))
    required = list(DELIVERY_SUBSECTIONS) + (["Prova de Correção"] if doc.type == "fix" else [])
    for name in required:
        body = find_sub(subs, name)
        if body is None:
            add("ERROR", sid, f"Relatório de Entrega sem a subseção '{name}'")
        elif not body.strip():
            add("ERROR", sid, f"Relatório de Entrega: '{name}' vazio")
    rows = {}
    for header, trs in parse_tables(find_sub(subs, "Verificação") or ""):
        cols = [norm(c) for c in header]
        if "resultado" not in cols:
            continue
        ri = cols.index("resultado")
        ei = cols.index("evidencia") if "evidencia" in cols else None
        for r in trs:
            for tid in TEST_ID_RE.findall(r[0] if r else ""):
                result = r[ri] if ri < len(r) else ""
                evidence = r[ei] if ei is not None and ei < len(r) else ""
                rows[tid] = (result.upper(), evidence.strip())
    missing = [t for t in sorted(defined, key=test_sort_key) if t not in rows]
    if missing:
        add("ERROR", sid, f"Verificação não comprova os testes do plano: {', '.join(missing)}")
    failing = sorted((t for t, (res, _) in rows.items() if "PASS" not in res), key=test_sort_key)
    if failing:
        add("ERROR", sid, f"Verificação com testes sem PASS: {', '.join(failing)}")
    no_evidence = sorted((t for t, (res, ev) in rows.items() if "PASS" in res and not ev), key=test_sort_key)
    if no_evidence:
        add("ERROR", sid, f"Verificação sem evidência (CI, commit ou relatório): {', '.join(no_evidence)}")
    dod = find_sub(subs, "Definição de Pronto") or ""
    if not CHECKBOX_RE.search(dod):
        add("ERROR", sid, "Definição de Pronto sem itens")
    elif UNCHECKED_RE.search(dod):
        add("ERROR", sid, "Definição de Pronto com itens não marcados — não está pronto")


def validate_contract_map(doc: Doc, defined, add):
    sid = doc.id
    content = COMMENT_RE.sub("", doc.section("Contrato") or "")
    tables = [(h, rows) for h, rows in parse_tables(content) if any(norm(c) == "testes" for c in h)]
    if not tables:
        add("ERROR", sid, "contrato sem 'Mapa de Comportamentos' (tabela com coluna 'Testes')")
        return
    for header, rows in tables:
        col = next(i for i, c in enumerate(header) if norm(c) == "testes")
        if not rows:
            add("ERROR", sid, "Mapa de Comportamentos sem linhas")
        for row in rows:
            label = row[0] if row and row[0] else "?"
            refs = TEST_ID_RE.findall(row[col] if col < len(row) else "")
            if not refs:
                add("ERROR", sid, f"comportamento '{label}' sem teste associado")
                continue
            missing = [r for r in refs if r not in defined]
            if missing:
                add("ERROR", sid, f"comportamento '{label}' referencia teste ausente do plano: {', '.join(missing)}")


def gate_table(doc: Doc):
    content = doc.section("Registro de Gates")
    if content is None:
        return None
    gates = {}
    for _, rows in parse_tables(COMMENT_RE.sub("", content)):
        for row in rows:
            words = row[0].split() if row else []
            key = words[0].upper() if words else ""
            if key in GATE_ROWS:
                cell = (row[1] if len(row) > 1 else "").strip().upper()
                status = next((s for s in GATE_STATUSES if s in cell), cell)
                gates[key] = {"status": status, "evidence": (row[2] if len(row) > 2 else "").strip()}
    return gates


def normalize_imp_type(value: str):
    key = norm(value or "").strip()
    return next((t for t in IMPEDIMENT_TYPES if norm(t) == key), None)


def impediments(doc: Doc):
    content = doc.section("Registro de Impedimentos")
    if content is None:
        return []
    items = []
    for header, rows in parse_tables(COMMENT_RE.sub("", content)):
        cols = [norm(c) for c in header]
        if "id" not in cols:
            continue
        idx = {name: cols.index(norm(name)) for name in IMPEDIMENT_COLUMNS if norm(name) in cols}
        for row in rows:
            item = {name: (row[i].strip().replace("\\|", "|") if i < len(row) else "") for name, i in idx.items()}
            for name in IMPEDIMENT_COLUMNS:
                item.setdefault(name, "")
            if item["ID"]:
                items.append(item)
    return items


def open_impediments(doc: Doc):
    return [i for i in impediments(doc) if not i["Fechado em"]]


def age_days(date: str) -> str:
    try:
        return f"{(dt.date.today() - dt.date.fromisoformat(date)).days}d"
    except ValueError:
        return "?"


def impediment_label(item) -> str:
    kind = normalize_imp_type(item["Tipo"]) or item["Tipo"]
    return f"{item['ID']} ({kind} → {item['Responsável'] or '?'}, {age_days(item['Aberto em'])})"


def validate_questions(doc: Doc, add):
    content = doc.section("Questões em Aberto")
    if content is None:
        return
    lines = COMMENT_RE.sub("", content).split("\n")
    pending = [l for l in lines if re.match(r"^\s*[-*] \[ \]", l)]
    if pending:
        add("ERROR", doc.id, f"{len(pending)} questão(ões) em aberto sem resposta — responda e registre antes do H1")
    for line in lines:
        if re.match(r"^\s*[-*] \[[xX]\]", line) and not re.search(r"\s[—–-]\s", line.split("]", 1)[1]):
            add("WARN", doc.id, f"questão marcada sem resposta registrada ('pergunta — resposta'): '{line.strip()[6:60]}'")


def validate_impediments(project: Project, doc: Doc, add):
    sid = doc.id
    emendas = COMMENT_RE.sub("", doc.section("Emendas") or "")
    amendment_rows = sum(len(rows) for _, rows in parse_tables(emendas))
    seen = set()
    for item in impediments(doc):
        iid = item["ID"]
        if not IMP_ID_RE.match(iid):
            add("ERROR", sid, f"impedimento com ID inválido '{iid}' (esperado IMP-NN)")
        if iid in seen:
            add("ERROR", sid, f"impedimento {iid} duplicado")
        seen.add(iid)
        kind = normalize_imp_type(item["Tipo"])
        if kind is None:
            add("ERROR", sid, f"{iid}: tipo '{item['Tipo']}' inválido ({' | '.join(IMPEDIMENT_TYPES)})")
        if not valid_date(item["Aberto em"]):
            add("ERROR", sid, f"{iid}: 'Aberto em' deve ser uma data YYYY-MM-DD")
        if not item["Descrição"]:
            add("ERROR", sid, f"{iid}: sem descrição do que falta")
        if not item["Responsável"]:
            add("ERROR", sid, f"{iid}: sem responsável — quem precisa agir?")
        closed, resolution = item["Fechado em"], item["Resolução"]
        if not closed:
            if doc.status == "implemented":
                add("ERROR", sid, f"{iid} aberto — spec não pode estar implemented com impedimento aberto")
            elif doc.status == "deprecated":
                add("WARN", sid, f"{iid} aberto em spec deprecated — feche registrando o cancelamento como resolução")
            continue
        if not valid_date(closed):
            add("ERROR", sid, f"{iid}: 'Fechado em' deve ser uma data YYYY-MM-DD")
        if not resolution:
            add("ERROR", sid, f"{iid}: fechado sem resolução")
        elif kind == "spec" and ("emenda" not in norm(resolution) or not amendment_rows):
            add("ERROR", sid, f"{iid}: impedimento de spec se resolve por emenda — cite-a (ex: 'Emenda v2') e registre-a na seção Emendas")
        elif kind == "trabalho":
            refs = SPEC_REF_RE.findall(resolution)
            if not refs:
                add("ERROR", sid, f"{iid}: impedimento de trabalho se resolve com uma spec — cite o SPEC-NNNN criado")
            for ref in refs:
                if ref not in project.specs:
                    add("ERROR", sid, f"{iid}: resolução cita {ref}, que não existe")
        elif kind == "decisão":
            for ref in ADR_REF_RE.findall(resolution):
                if ref not in project.adrs:
                    add("ERROR", sid, f"{iid}: resolução cita {ref}, que não existe em docs/adr/")


def validate_epic(project: Project, doc: Doc, add):
    sid = doc.id
    kids = project.children(sid)
    if doc.list("touches") or doc.list("consumes_contract"):
        add("WARN", sid, "épico não executa código: mova touches/consumes_contract para as specs filhas")
    if doc.status in APPROVED_PLUS and not kids:
        add("ERROR", sid, f"épico aprovado sem specs filhas (nenhuma spec com parent: {sid})")
    decomposition = COMMENT_RE.sub("", doc.section("Decomposição") or "")
    for kid in kids:
        if kid.id not in decomposition:
            add("WARN", sid, f"filha {kid.id} não aparece na seção Decomposição")
    for ref in sorted(set(SPEC_REF_RE.findall(decomposition))):
        if ref not in project.specs:
            add("WARN", sid, f"Decomposição cita {ref}, que ainda não existe")
        elif project.specs[ref].scalar("parent") != sid:
            add("WARN", sid, f"Decomposição cita {ref}, mas ela não tem parent: {sid}")
    criteria = COMMENT_RE.sub("", doc.section("Critérios de Aceite") or "")
    level = "ERROR" if doc.status == "implemented" else "WARN"
    for line in (l for l in criteria.split("\n") if CHECKBOX_RE.match(l)):
        label = re.sub(r"^\s*[-*] \[.\]\s*", "", line)[:60]
        refs = TEST_TAG_RE.findall(line)
        if not refs:
            add(level, sid, f"critério de aceite sem teste que o prove (SPEC-NNNN:E2E-xx): '{label}'")
        for spec_ref, tid in refs:
            child = project.specs.get(spec_ref)
            if child is None:
                add(level, sid, f"critério cita {spec_ref}:{tid}, mas {spec_ref} não existe")
            elif tid not in plan_test_ids(child):
                add(level, sid, f"critério cita {spec_ref}:{tid}, que não está no plano de testes de {spec_ref}")
    open_kids = [k.id for k in kids if k.status not in DONE]
    if doc.status == "implemented":
        if open_kids:
            add("ERROR", sid, f"épico implemented com filhas abertas: {', '.join(open_kids)}")
        if UNCHECKED_RE.search(criteria):
            add("ERROR", sid, "critérios de aceite do épico não marcados")
        if not COMMENT_RE.sub("", doc.section("Relatório de Entrega") or "").strip():
            add("ERROR", sid, "Relatório de Entrega do épico vazio")
    elif kids and not open_kids and doc.status != "deprecated":
        add("WARN", sid, "todas as filhas concluídas — valide os critérios de aceite e feche o épico")
    if doc.status == "proposed":
        early = [k.id for k in kids if k.status in APPROVED_PLUS]
        if early:
            add("WARN", sid, f"filhas aprovadas antes do épico: {', '.join(early)}")


def validate_adr(project: Project, adr: Doc, add):
    aid = adr.id
    if not ADR_ID_RE.match(aid):
        add("ERROR", aid or adr.path.name, "id inválido (esperado ADR-NNNN)")
        return
    if adr.path.stem != aid and not adr.path.name.startswith(aid + "-"):
        add("ERROR", aid, f"nome do arquivo deve começar com '{aid}-'")
    if adr.status not in ADR_STATUSES:
        add("ERROR", aid, f"status inválido '{adr.status}' ({' | '.join(ADR_STATUSES)})")
    origin = adr.scalar("origin").lower()
    if origin and origin not in ADR_ORIGINS:
        add("ERROR", aid, f"origin inválido '{origin}' ({' | '.join(ADR_ORIGINS)})")
    if PLACEHOLDER_RE.search(COMMENT_RE.sub("", adr.text)):
        add("ERROR", aid, "marcadores {{...}} não preenchidos")
    if adr.status == "accepted" and not adr.scalar("enforced_by"):
        add("WARN", aid, "ADR aceito sem enforced_by — informe o teste de arquitetura que o garante (G3) ou 'N/A — motivo'")
    if adr.status == "superseded":
        by = adr.scalar("superseded_by")
        if not by:
            add("ERROR", aid, "superseded exige superseded_by")
        elif by not in project.adrs:
            add("ERROR", aid, f"superseded_by: {by} não existe")
    sup = adr.scalar("supersedes")
    if sup and sup not in project.adrs:
        add("ERROR", aid, f"supersedes: {sup} não existe")


def find_cycles(project: Project):
    graph = {sid: [d for d in doc.list("depends_on") if d in project.specs] for sid, doc in project.specs.items()}
    color, stack, cycles = {}, [], []

    def visit(node):
        color[node] = 1
        stack.append(node)
        for nxt in graph[node]:
            if color.get(nxt) == 1:
                cycles.append(stack[stack.index(nxt):] + [nxt])
            elif nxt not in color:
                visit(nxt)
        stack.pop()
        color[node] = 2

    for node in sorted(graph):
        if node not in color:
            visit(node)
    return cycles


# ---------------------------------------------------------------- planning

def touches_overlap(a: Doc, b: Doc) -> bool:
    ta, tb = a.list("touches"), b.list("touches")
    if not ta or not tb:
        return True
    return any(patterns_overlap(x, y) for x in ta for y in tb)


def readiness(project: Project, doc: Doc):
    stops = "; ".join(impediment_label(i) for i in open_impediments(doc))
    if doc.status == "in-progress":
        if stops:
            return "stalled", f"🚧 parada por impedimento: {stops}"
        return "running", "🔄 em andamento"
    if doc.status == "proposed":
        return "blocked", "⏳ aguardando aprovação (H1)" + (f"; 🚧 impedimento: {stops}" if stops else "")
    blockers = [f"impedimento {stops}"] if stops else []
    for dep in doc.list("depends_on"):
        d = project.specs.get(dep)
        if d is None or d.status != "implemented":
            blockers.append(f"aguarda implementação de {dep}")
    for pid, ver, _ in contract_refs(doc):
        provider = project.specs.get(pid) if pid else None
        if provider is None:
            continue
        if provider.status not in APPROVED_PLUS:
            blockers.append(f"aguarda aprovação do contrato de {pid}")
        elif ver is None or ver < contract_version(provider):
            blockers.append(f"contrato de {pid} mudou (v{ver} → v{contract_version(provider)}): revisar spec")
    if not doc.list("touches"):
        blockers.append("touches vazio")
    if blockers:
        return "blocked", "⛔ " + "; ".join(blockers)
    return "ready", "✅ pronta"


def compute_waves(project: Project):
    specs = project.specs
    nodes = {sid for sid, d in specs.items() if d.status in OPEN and d.tier != "epic" and SPEC_ID_RE.match(sid)}
    deps = {sid: [d for d in specs[sid].list("depends_on") if d in nodes] for sid in nodes}
    indegree = {sid: len(deps[sid]) for sid in nodes}
    dependents = defaultdict(list)
    for sid, ds in deps.items():
        for d in ds:
            dependents[d].append(sid)
    heap = [(STATUS_RANK[specs[s].status], s) for s in nodes if indegree[s] == 0]
    heapq.heapify(heap)
    order = []
    while heap:
        _, sid = heapq.heappop(heap)
        order.append(sid)
        for t in dependents[sid]:
            indegree[t] -= 1
            if indegree[t] == 0:
                heapq.heappush(heap, (STATUS_RANK[specs[t].status], t))
    if len(order) < len(nodes):
        return None
    max_parallel = project.max_parallel()
    wave, members, notes = {}, defaultdict(list), defaultdict(list)
    for sid in order:
        w = 1 + max((wave[d] for d in deps[sid]), default=0)
        while True:
            clash = [o for o in members[w] if touches_overlap(specs[sid], specs[o])]
            if clash:
                reason = ("touches vazio, não roda em paralelo" if not specs[sid].list("touches")
                          else f"arquivos em comum com {', '.join(clash)}")
                notes[sid].append(f"saiu da onda {w}: {reason}")
                w += 1
                continue
            if max_parallel and len(members[w]) >= max_parallel:
                notes[sid].append(f"saiu da onda {w}: max_parallel={max_parallel}")
                w += 1
                continue
            break
        wave[sid] = w
        members[w].append(sid)
    return wave, dict(members), notes


def next_batch(project: Project, plan):
    wave = plan[0]
    specs = project.specs
    running = sorted(s for s in wave if specs[s].status == "in-progress")
    ready = sorted((s for s in wave if readiness(project, specs[s])[0] == "ready"), key=lambda s: (wave[s], s))
    max_parallel = project.max_parallel()
    batch, held = [], []
    for sid in ready:
        clash = [o for o in running + batch if touches_overlap(specs[sid], specs[o])]
        if clash:
            held.append((sid, f"arquivos em comum com {', '.join(clash)}"))
        elif max_parallel and len(running) + len(batch) >= max_parallel:
            held.append((sid, f"limite max_parallel={max_parallel}"))
        else:
            batch.append(sid)
    return running, batch, held


def require_plan(project: Project):
    plan = compute_waves(project)
    if plan is None:
        cycles = find_cycles(project)
        die("ciclo em depends_on impede o planejamento: " + "; ".join(" → ".join(c) for c in cycles), 1)
    return plan


# ---------------------------------------------------------------- commands

def cmd_validate(project: Project, ids):
    only = None
    if ids:
        unknown = [i for i in ids if i not in project.specs and i not in project.adrs]
        if unknown:
            die(f"não encontrado(s): {', '.join(unknown)}")
        only = set(ids)
        for i in ids:
            if i in project.specs and project.specs[i].tier == "epic":
                only |= {k.id for k in project.children(i)}
    issues = validate(project, only)
    errors = [i for i in issues if i[0] == "ERROR"]
    warns = [i for i in issues if i[0] == "WARN"]
    for level, subject, msg in sorted(issues, key=lambda x: (x[1], x[0] != "ERROR")):
        print(f"{level:<5} {subject}: {msg}")
    scope = ", ".join(sorted(only)) if only else "projeto inteiro"
    verdict = "PASS" if not errors else "FAIL"
    print(f"\nG0 [{scope}]: {verdict} — {len(errors)} erro(s), {len(warns)} aviso(s)")
    return 1 if errors else 0


def cmd_waves(project: Project):
    plan = require_plan(project)
    wave, members, notes = plan
    if not wave:
        print("Nenhuma spec aberta para planejar.")
        return 0
    specs = project.specs
    for w in sorted(members):
        print(f"\nOnda {w}")
        for sid in members[w]:
            d = specs[sid]
            print(f"  {sid}  {d.status:<11} {d.tier}/{d.scalar('size') or '?'}  {d.title}")
            print(f"             {readiness(project, d)[1]}")
            for note in notes.get(sid, []):
                print(f"             ↳ {note}")
    print()
    print_next(project, plan)
    return 0


def print_next(project: Project, plan):
    running, batch, held = next_batch(project, plan)
    specs = project.specs
    active = [s for s in running if readiness(project, specs[s])[0] == "running"]
    if active:
        print("Em andamento: " + ", ".join(active))
    for sid in running:
        state, label = readiness(project, specs[sid])
        if state == "stalled":
            print(f"Parada {sid}: {label}")
    for epic in sorted((d for d in specs.values() if d.tier == "epic" and d.status in OPEN), key=lambda d: d.id):
        for item in open_impediments(epic):
            print(f"Impedimento no épico {epic.id}: {impediment_label(item)} — {item['Descrição']}")
    if batch:
        print("Próximo lote (despachar em paralelo): " + ", ".join(batch))
        for sid in batch:
            d = specs[sid]
            print(f"  {sid}  {d.title}  → {', '.join(d.list('touches'))}")
    else:
        print("Nenhuma spec pronta para despachar agora.")
    for sid, why in held:
        print(f"  aguardando {sid}: {why}")
    blocked = [s for s in plan[0] if readiness(project, specs[s])[0] == "blocked"]
    for sid in sorted(blocked):
        print(f"  bloqueada {sid}: {readiness(project, specs[sid])[1]}")


def cmd_next(project: Project):
    print_next(project, require_plan(project))
    return 0


def mermaid_label(doc: Doc) -> str:
    title = doc.title.replace('"', "'")
    if len(title) > 40:
        title = title[:39] + "…"
    return f'{doc.id}<br/>{title}'


def build_index(project: Project) -> str:
    specs = project.specs
    plan = compute_waves(project)
    issues = validate(project)
    errors = sum(1 for i in issues if i[0] == "ERROR")
    warns = sum(1 for i in issues if i[0] == "WARN")
    out = [
        "# Índice de Specs",
        "",
        f"> Gerado por `spec_graph.py index` em {today()} — não edite manualmente.",
        "",
        "## Saúde",
        "",
        f"- Validação (G0): **{errors} erro(s), {warns} aviso(s)**" + (" — rode `spec_graph.py validate`" if issues else ""),
    ]
    counts = Counter(d.status for d in specs.values() if d.tier != "epic")
    out.append("- Specs: " + (", ".join(f"{s} {counts[s]}" for s in STATUSES if counts[s]) or "nenhuma"))
    all_imps = [(d, i) for d in sorted(specs.values(), key=lambda d: d.id) for i in impediments(d)]
    open_imps = [(d, i) for d, i in all_imps if not i["Fechado em"]]
    out.append(f"- Impedimentos: **{len(open_imps)} aberto(s)**, {len(all_imps) - len(open_imps)} resolvido(s)")
    out.append("")
    if open_imps:
        out += ["## Impedimentos Abertos", "",
                "| Spec | ID | Tipo | Fase/Gate | Responsável | Aberto em | Idade | Descrição |",
                "|---|---|---|---|---|---|---|---|"]
        for d, i in open_imps:
            out.append(f"| {d.id} | {i['ID']} | {normalize_imp_type(i['Tipo']) or md_cell(i['Tipo'])} | {md_cell(i['Fase/Gate'])} "
                       f"| {md_cell(i['Responsável'])} | {i['Aberto em']} | {age_days(i['Aberto em'])} | {md_cell(i['Descrição'])} |")
        out.append("")

    out += ["## Plano de Execução", ""]
    if plan is None:
        out.append("⛔ Ciclo em `depends_on` — planejamento impossível até ser resolvido.")
    elif not plan[0]:
        out.append("Nenhuma spec aberta.")
    else:
        wave, members, notes = plan
        running, batch, held = next_batch(project, plan)
        stalled = [s for s in running if readiness(project, specs[s])[0] == "stalled"]
        out.append(f"**Em andamento:** {', '.join(s for s in running if s not in stalled) or '—'}  ")
        out.append(f"**Paradas por impedimento:** {', '.join(stalled) or '—'}  ")
        out.append(f"**Próximo lote:** {', '.join(batch) or '—'}")
        out += ["", "| Onda | Spec | Título | Tier/Tam. | Status | Prontidão | Observação |", "|---|---|---|---|---|---|---|"]
        for w in sorted(members):
            for sid in members[w]:
                d = specs[sid]
                note = "; ".join(notes.get(sid, [])) or ""
                out.append(f"| {w} | {sid} | {md_cell(d.title)} | {d.tier}/{d.scalar('size') or '?'} | {d.status} "
                           f"| {md_cell(readiness(project, d)[1])} | {md_cell(note)} |")
    out.append("")

    epics = sorted((d for d in specs.values() if d.tier == "epic"), key=lambda d: d.id)
    if epics:
        out += ["## Épicos", "", "| Épico | Título | Status | Progresso |", "|---|---|---|---|"]
        for e in epics:
            kids = project.children(e.id)
            done = sum(1 for k in kids if k.status == "implemented")
            active = [k for k in kids if k.status != "deprecated"]
            out.append(f"| {e.id} | {md_cell(e.title)} | {e.status} | {done}/{len(active)} implementadas |")
        out.append("")

    open_ids = {sid for sid, d in specs.items() if d.status in OPEN and d.tier != "epic"}
    referenced = set()
    for sid in open_ids:
        referenced |= set(specs[sid].list("depends_on"))
        referenced |= {pid for pid, _, _ in contract_refs(specs[sid]) if pid}
    graph_ids = sorted(i for i in open_ids | referenced if i in specs and specs[i].tier != "epic")
    if graph_ids:
        out += ["## Grafo de Dependências", "",
                "Seta contínua: depende da implementação. Seta tracejada: consome contrato.", "", "```mermaid", "flowchart LR"]
        grouped = defaultdict(list)
        for sid in graph_ids:
            grouped[specs[sid].scalar("parent")].append(sid)
        node = lambda sid: "S" + sid.split("-")[1]
        klass = lambda sid: specs[sid].status.replace("-", "")
        for parent in sorted(grouped):
            indent = "  "
            if parent and parent in specs:
                out.append(f'  subgraph E{parent.split("-")[1]}["{parent} · {specs[parent].title.replace(chr(34), chr(39))}"]')
                indent = "    "
            for sid in grouped[parent]:
                out.append(f'{indent}{node(sid)}["{mermaid_label(specs[sid])}"]:::{klass(sid)}')
            if parent and parent in specs:
                out.append("  end")
        for sid in graph_ids:
            d = specs[sid]
            for dep in d.list("depends_on"):
                if dep in graph_ids:
                    out.append(f"  {node(dep)} --> {node(sid)}")
            for pid, ver, _ in contract_refs(d):
                if pid in graph_ids:
                    out.append(f"  {node(pid)} -. contrato v{ver or '?'} .-> {node(sid)}")
        out += [
            "  classDef proposed fill:#fef3c7,stroke:#d97706,color:#111",
            "  classDef approved fill:#dbeafe,stroke:#2563eb,color:#111",
            "  classDef inprogress fill:#ede9fe,stroke:#7c3aed,color:#111",
            "  classDef implemented fill:#dcfce7,stroke:#16a34a,color:#111",
            "  classDef deprecated fill:#f3f4f6,stroke:#9ca3af,color:#6b7280",
            "```", "",
        ]

    out += ["## Todas as Specs", "",
            "| ID | Título | Tier | Tipo | Status | Criada | Épico | Depende de | Consome contrato |",
            "|---|---|---|---|---|---|---|---|---|"]
    for sid in sorted(specs):
        d = specs[sid]
        out.append(f"| [{sid}]({d.path.name}) | {md_cell(d.title)} | {d.tier} | {d.type or '—'} | {d.status} | {d.scalar('created')} "
                   f"| {d.scalar('parent') or '—'} | {', '.join(d.list('depends_on')) or '—'} "
                   f"| {', '.join(d.list('consumes_contract')) or '—'} |")
    out.append("")

    if project.adrs:
        out += ["## ADRs", "", "| ID | Título | Status | Garantido por (G3) |", "|---|---|---|---|"]
        for aid in sorted(project.adrs):
            a = project.adrs[aid]
            out.append(f"| [{aid}](../adr/{a.path.name}) | {md_cell(a.title)} | {a.status} | {md_cell(a.scalar('enforced_by') or '—')} |")
        out.append("")
    return "\n".join(out)


def cmd_index(project: Project, stdout: bool):
    text = build_index(project)
    if stdout:
        print(text)
        return 0
    project.specs_dir.mkdir(parents=True, exist_ok=True)
    dest = project.specs_dir / "INDEX.md"
    dest.write_text(text, encoding="utf-8")
    print(f"escrito: {project.rel(dest)}")
    return 0


def run_git(root: Path, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def cmd_verify(project: Project, spec_id: str, base):
    doc = project.specs.get(spec_id)
    if doc is None:
        die(f"{spec_id} não encontrada")
    if doc.tier == "epic":
        die("verify roda por spec executável (lite/full), não por épico")
    root = project.root
    if run_git(root, "rev-parse", "--is-inside-work-tree")[0] != 0:
        die("não é um repositório git")
    base = base or project.cfg("base_branch", "main")
    code, merge_base, err = run_git(root, "merge-base", base, "HEAD")
    if code != 0:
        die(f"não foi possível achar merge-base com '{base}': {err.strip()}")
    merge_base = merge_base.strip()
    _, log, _ = run_git(root, "log", "--reverse", "--no-merges", "--format=%H%x1f%s%x1f%b%x1e", f"{merge_base}..HEAD")

    test_paths = project.cfg_list("test_paths", DEFAULT_TEST_PATHS)
    exempt = project.cfg_list("scope_exempt", DEFAULT_SCOPE_EXEMPT)
    commits = []
    for chunk in log.split("\x1e"):
        if not chunk.strip():
            continue
        parts = chunk.strip("\n").split("\x1f")
        sha, subject = parts[0].strip(), parts[1] if len(parts) > 1 else ""
        body = parts[2] if len(parts) > 2 else ""
        m = CONVENTIONAL_RE.match(subject)
        ctype = m.group(1).lower() if m else ""
        if ctype in RED_TYPES:
            kind = "red"
        elif ctype in GREEN_TYPES:
            kind = "green"
        elif ctype == "chore" and "scaffold" in subject.lower():
            kind = "scaffold"
        else:
            kind = "other"
        files = run_git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha)[1].split()
        commits.append({"sha": sha, "subject": subject, "body": body, "kind": kind, "files": files})

    ref_re = re.compile(rf"\b{re.escape(spec_id)}\b")
    mine = [c for c in commits if ref_re.search(c["subject"] + "\n" + c["body"])]
    untraced = [c for c in commits if not SPEC_REF_RE.search(c["subject"] + "\n" + c["body"])]
    short = lambda c: f"{c['sha'][:7]} {c['subject'][:72]}"
    is_test = lambda f: matches_any(f, test_paths)
    is_exempt = lambda f: matches_any(f, exempt)
    results = []

    reds = [i for i, c in enumerate(mine) if c["kind"] == "red"]
    greens = [i for i, c in enumerate(mine) if c["kind"] == "green"]
    if not mine:
        results.append(("FAIL", "G1", f"nenhum commit referencia {spec_id} em {base}..HEAD"))
    elif not reds:
        results.append(("FAIL", "G1", "nenhum commit test(...) — a fase Red não foi registrada"))
    else:
        early = [mine[i] for i in greens if i < reds[0]]
        if early:
            results.append(("FAIL", "G1", "implementação antes dos testes: " + "; ".join(short(c) for c in early)))
        else:
            results.append(("PASS", "G1", f"Red antes do Green — primeiro red: {short(mine[reds[0]])}"))
        bad = sorted({f for i in reds for f in mine[i]["files"] if not is_test(f) and not is_exempt(f)})
        if bad:
            results.append(("FAIL", "G1", "commits test(...) alteram arquivos fora de test_paths: " + ", ".join(bad)
                            + " — scaffolding de contrato vai em commit chore(...): scaffold"))
        else:
            results.append(("PASS", "G1", "commits red só alteram testes"))

    plan_ids = plan_test_ids(doc)
    if not plan_ids:
        results.append(("FAIL", "G1", "plano de testes sem IDs"))
    else:
        missing, outside = [], []
        for tid in plan_ids:
            tag = f"{spec_id}:{tid}"
            out = run_git(root, "grep", "-l", "-F", "-e", tag, "--", ".", ":(exclude)docs/specs")[1]
            found = [line for line in out.splitlines() if line.strip()]
            if not found:
                missing.append(tag)
            elif not any(is_test(f) for f in found):
                outside.append(tag)
        if missing:
            results.append(("FAIL", "G1", "testes do plano sem tag no código versionado: " + ", ".join(missing)))
        else:
            results.append(("PASS", "G1", f"rastreabilidade: {len(plan_ids)}/{len(plan_ids)} testes do plano no código ({', '.join(plan_ids)})"))
        if outside:
            results.append(("WARN", "G1", "tags encontradas só fora de test_paths: " + ", ".join(outside)))

    touches = doc.list("touches")
    changed = sorted({f for c in mine for f in c["files"]})
    out_of_scope = [f for f in changed if not is_exempt(f) and not matches_any(f, touches)]
    if not touches:
        results.append(("FAIL", "G4", "touches vazio — escopo não verificável"))
    elif out_of_scope:
        results.append(("FAIL", "G4", "arquivos alterados fora de touches: " + ", ".join(out_of_scope)))
    else:
        results.append(("PASS", "G4", f"escopo: {len(changed)} arquivo(s) dentro de touches"))

    if reds:
        edited = sorted({f"{f} ({c['sha'][:7]})" for i, c in enumerate(mine)
                         if i > reds[0] and c["kind"] != "red" for f in c["files"] if is_test(f)})
        if edited:
            results.append(("WARN", "G4", "testes alterados fora de commits red (reviewer deve justificar): " + ", ".join(edited)))
    manifests = project.cfg_list("dependency_manifests", DEFAULT_MANIFESTS)
    changed_manifests = [f for f in changed if matches_any(f, manifests)]
    if changed_manifests:
        if doc.type in ("migration", "foundation") or doc.list("adrs"):
            results.append(("INFO", "G4", "manifestos de dependência alterados — reviewer confirma que estão cobertos pelos ADRs: "
                            + ", ".join(changed_manifests)))
        else:
            results.append(("WARN", "G4", "manifestos de dependência alterados sem ADR na spec — lib/framework nova em projeto "
                            "existente exige ADR aprovado ou type migration; bump de versão precisa de justificativa: "
                            + ", ".join(changed_manifests)))
    scaffolds = [c for c in mine if c["kind"] == "scaffold"]
    if scaffolds:
        results.append(("INFO", "G4", "reviewer confirma que scaffold não tem lógica: " + "; ".join(short(c) for c in scaffolds)))
    if untraced:
        results.append(("WARN", "G4", f"{len(untraced)} commit(s) sem referência a spec: " + "; ".join(short(c) for c in untraced[:5])))
    if run_git(root, "status", "--porcelain")[1].strip():
        results.append(("WARN", "--", "há alterações não commitadas — não entram na verificação"))

    print(f"verify {spec_id} — base {base} @ {merge_base[:7]}, {len(mine)} commit(s) da spec\n")
    for level, gate, msg in results:
        print(f"[{gate}] {level:<4}  {msg}")
    fails = sum(1 for r in results if r[0] == "FAIL")
    warns = sum(1 for r in results if r[0] == "WARN")
    print(f"\nResultado: {'FAIL' if fails else 'PASS'} — {fails} falha(s), {warns} aviso(s)")
    return 1 if fails else 0


def cmd_impacted(project: Project, spec_id: str):
    doc = project.specs.get(spec_id)
    if doc is None:
        die(f"{spec_id} não encontrada")
    specs = project.specs
    current = contract_version(doc)
    print(f"{spec_id} — {doc.title} (contrato v{current})\n")
    consumers = project.consumers(spec_id)
    print("Consomem o contrato:")
    for d, ver in consumers:
        state = "em dia" if ver == current else f"DESATUALIZADO (pin @{ver})"
        print(f"  {d.id}  [{d.status}]  {d.title} — {state}")
    if not consumers:
        print("  —")
    direct = [d for d in sorted(specs.values(), key=lambda d: d.id) if spec_id in d.list("depends_on")]
    print("Dependem da implementação:")
    for d in direct:
        print(f"  {d.id}  [{d.status}]  {d.title}")
    if not direct:
        print("  —")
    reverse = defaultdict(set)
    for d in specs.values():
        for dep in d.list("depends_on"):
            reverse[dep].add(d.id)
    seen = {spec_id} | {d.id for d, _ in consumers} | {d.id for d in direct}
    queue = deque(sorted(seen - {spec_id}))
    transitive = []
    while queue:
        cur = queue.popleft()
        for nxt in sorted(reverse[cur]):
            if nxt not in seen:
                seen.add(nxt)
                transitive.append(nxt)
                queue.append(nxt)
    print("Impacto transitivo:")
    for sid in transitive:
        print(f"  {sid}  [{specs[sid].status}]  {specs[sid].title}")
    if not transitive:
        print("  —")
    return 0


def cmd_report(project: Project, spec_id: str):
    doc = project.specs.get(spec_id)
    if doc is None:
        die(f"{spec_id} não encontrada")
    meta = [f"**Tipo:** {doc.type or '?'}", f"**Tier:** {doc.tier}", f"**Status:** {doc.status}"]
    if doc.scalar("parent"):
        meta.append(f"**Épico:** {doc.scalar('parent')}")
    out = [f"## {doc.id} — {doc.title}", "", " · ".join(meta), ""]
    delivery = COMMENT_RE.sub("", doc.section("Relatório de Entrega") or "").strip()
    out += [delivery or "_Relatório de Entrega ainda não preenchido._", ""]
    if doc.tier == "epic":
        out += ["### Specs do épico", "", "| Spec | Título | Tipo | Status |", "|---|---|---|---|"]
        for kid in project.children(spec_id):
            out.append(f"| {kid.id} | {md_cell(kid.title)} | {kid.type} | {kid.status} |")
        out.append("")
    else:
        gates = COMMENT_RE.sub("", doc.section("Registro de Gates") or "").strip()
        if gates:
            out += ["### Registro de Gates", "", gates, ""]
    if impediments(doc):
        out += ["### Impedimentos", "", COMMENT_RE.sub("", doc.section("Registro de Impedimentos") or "").strip(), ""]
    out.append(f"Spec completa: `{project.rel(doc.path)}`")
    print("\n".join(out))
    return 0


def section_bounds(lines, keyword: str):
    key, start, fence = norm(keyword), None, False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fence = not fence
        if fence or not line.startswith("## "):
            continue
        if start is not None:
            return start, i
        if key in norm(line[3:]):
            start = i
    return (start, len(lines)) if start is not None else None


def impediment_table_lines(doc: Doc):
    lines = doc.text.split("\n")
    bounds = section_bounds(lines, "Registro de Impedimentos")
    if bounds is None:
        die(f"{doc.id} não tem a seção 'Registro de Impedimentos' — atualize a spec para o template atual")
    table = [i for i in range(bounds[0] + 1, bounds[1]) if lines[i].strip().startswith("|")]
    if len(table) < 2:
        die(f"{doc.id}: tabela do Registro de Impedimentos não encontrada")
    header = [norm(c.strip()) for c in CELL_SPLIT_RE.split(lines[table[0]].strip()[1:-1])]
    return lines, table, header


def cmd_impede(project: Project, spec_id: str, kind: str, reason: str, owner: str, phase, tried):
    doc = project.specs.get(spec_id)
    if doc is None:
        die(f"{spec_id} não encontrada")
    normalized = normalize_imp_type(kind)
    if normalized is None:
        die(f"tipo '{kind}' inválido ({' | '.join(IMPEDIMENT_TYPES)})")
    lines, table, header = impediment_table_lines(doc)
    numbers = [int(m.group(1)) for item in impediments(doc) for m in [IMP_ID_RE.match(item["ID"])] if m]
    iid = f"IMP-{max(numbers, default=0) + 1:02d}"
    values = {"ID": iid, "Aberto em": today(), "Fase/Gate": phase or "—", "Tipo": normalized,
              "Descrição": reason, "Tentativas": tried or "—", "Responsável": owner, "Resolução": "", "Fechado em": ""}
    cells = [md_cell(values.get(next((n for n in IMPEDIMENT_COLUMNS if norm(n) == col), ""), "")) for col in header]
    lines.insert(table[-1] + 1, "| " + " | ".join(cells) + " |")
    doc.path.write_text("\n".join(lines), encoding="utf-8")
    print(f"{spec_id}/{iid} aberto: {normalized} → {owner} — {reason}")
    return 0


def cmd_resolve(project: Project, spec_id: str, iid: str, resolution: str):
    doc = project.specs.get(spec_id)
    if doc is None:
        die(f"{spec_id} não encontrada")
    item = next((i for i in impediments(doc) if i["ID"] == iid), None)
    if item is None:
        die(f"{spec_id}: impedimento {iid} não encontrado")
    if item["Fechado em"]:
        die(f"{spec_id}/{iid} já foi fechado em {item['Fechado em']}")
    kind = normalize_imp_type(item["Tipo"])
    amendment_rows = sum(len(rows) for _, rows in parse_tables(COMMENT_RE.sub("", doc.section("Emendas") or "")))
    if kind == "spec" and ("emenda" not in norm(resolution) or not amendment_rows):
        die("impedimento de spec se resolve por emenda: registre-a na seção Emendas e cite-a (ex: 'Emenda v2 — ...')")
    if kind == "trabalho":
        refs = SPEC_REF_RE.findall(resolution)
        if not refs or any(r not in project.specs for r in refs):
            die("impedimento de trabalho se resolve com uma spec existente: cite o SPEC-NNNN criado (use `new` antes)")
    lines, table, header = impediment_table_lines(doc)
    for idx in table[2:]:
        cells = [c.strip() for c in CELL_SPLIT_RE.split(lines[idx].strip()[1:-1])]
        if cells and cells[0] == iid:
            cells += [""] * (len(header) - len(cells))
            cells[header.index(norm("Resolução"))] = md_cell(resolution)
            cells[header.index(norm("Fechado em"))] = today()
            lines[idx] = "| " + " | ".join(cells) + " |"
            break
    doc.path.write_text("\n".join(lines), encoding="utf-8")
    print(f"{spec_id}/{iid} resolvido em {today()}: {resolution}")
    return 0


def create_from_template(project: Project, template: str, folder: Path, prefix: str, title: str, slug):
    path = TEMPLATES_DIR / template
    if not path.exists():
        die(f"template não encontrado: {path}")
    number = project.next_number(prefix)
    new_id = f"{prefix}-{number:04d}"
    text = path.read_text(encoding="utf-8")
    text = text.replace("{{id}}", new_id).replace("{{created}}", today()).replace("{{title}}", title)
    text = set_meta(text, "title", title)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{new_id}-{slugify(slug or title)}.md"
    return new_id, dest, text


def cmd_new(project: Project, tier: str, title: str, slug, parent):
    if parent:
        p = project.specs.get(parent)
        if p is None or p.tier != "epic":
            die(f"--parent {parent} não existe ou não é um épico")
        if tier == "epic":
            die("épico não pode ter parent")
    new_id, dest, text = create_from_template(project, f"template-{tier}.md", project.specs_dir, "SPEC", title, slug)
    if parent:
        text = set_meta(text, "parent", parent)
    dest.write_text(text, encoding="utf-8")
    print(f"{new_id}  {project.rel(dest)}")
    return 0


def cmd_new_adr(project: Project, title: str, slug):
    new_id, dest, text = create_from_template(project, "template-adr.md", project.adr_dir, "ADR", title, slug)
    dest.write_text(text, encoding="utf-8")
    print(f"{new_id}  {project.rel(dest)}")
    return 0


def cmd_set(project: Project, args):
    ids = [a for a in args if "=" not in a]
    pairs = [a.split("=", 1) for a in args if "=" in a]
    if not ids or not pairs:
        die("uso: set ID [ID ...] chave=valor [chave=valor ...]")
    docs = []
    for i in ids:
        doc = project.specs.get(i) or project.adrs.get(i)
        if doc is None:
            die(f"{i} não encontrado")
        docs.append(doc)
    for doc in docs:
        text = doc.text
        for key, raw in pairs:
            if raw == "today":
                value = today()
            elif raw.strip().startswith("["):
                value = parse_scalar(raw)
            else:
                value = raw
            if key == "status":
                allowed = ADR_STATUSES if doc.id.startswith("ADR-") else STATUSES
                if value not in allowed:
                    die(f"status '{value}' inválido para {doc.id} ({' | '.join(allowed)})")
            if key == "tier" and value not in TIERS:
                die(f"tier '{value}' inválido ({' | '.join(TIERS)})")
            text = set_meta(text, key, value)
            print(f"{doc.id}: {key} = {fmt_value(value)}")
        doc.path.write_text(text, encoding="utf-8")
    return 0


def cmd_next_id(project: Project, kind: str):
    prefix = "SPEC" if kind == "spec" else "ADR"
    print(f"{prefix}-{project.next_number(prefix):04d}")
    return 0


def legacy_title(body: str, fallback: str) -> str:
    for line in body.split("\n"):
        if line.startswith("# "):
            title = re.sub(r"^(especifica[cç][aã]o t[eé]cnica|technical spec(ification)?|spec)\s*[:—-]\s*", "",
                           line[2:].strip(), flags=re.I)
            return title or fallback
    return fallback


def cmd_migrate(project: Project, apply: bool):
    items = []
    for folder in LEGACY_DIRS:
        d = project.specs_dir / folder
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", p.stem)
            if m:
                created, slug = m.group(1), m.group(2)
            else:
                created, slug = dt.date.fromtimestamp(p.stat().st_mtime).isoformat(), p.stem
            items.append((created, p.name, folder, p, slug))
    if not items:
        print("Nada a migrar: nenhum .md em docs/specs/{proposed,approved,implemented,deprecated}/.")
        return 0
    items.sort()
    number = project.next_number("SPEC")
    plan = []
    for created, _, folder, src, slug in items:
        sid = f"SPEC-{number:04d}"
        number += 1
        plan.append((sid, created, folder, src, project.specs_dir / f"{sid}-{slugify(slug)}.md"))
    for sid, created, folder, src, dst in plan:
        print(f"{sid}  [{folder}]  {project.rel(src)}  →  {project.rel(dst)}")
    if not apply:
        print("\nSimulação. Rode novamente com --apply para executar.")
        return 0

    in_git = run_git(project.root, "rev-parse", "--is-inside-work-tree")[0] == 0
    for sid, created, folder, src, dst in plan:
        text = src.read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        existing = parse_yaml_subset(fm) if fm is not None else {}
        meta = {
            "id": sid, "title": existing.get("title") or legacy_title(body, src.stem), "tier": "full",
            "type": "feature", "user_facing": "", "status": folder, "created": created, "legacy": True, "parent": "", "depends_on": [],
            "consumes_contract": [], "contract_version": "1", "touches": [], "adrs": [], "size": "M",
            "approved_by": "legacy" if folder in APPROVED_PLUS else "",
            "approved_at": created if folder in APPROVED_PLUS else "",
        }
        for k, v in existing.items():
            if k not in ("id", "status", "legacy"):
                meta[k] = v
        header = "\n".join(f"{k}: {fmt_value(v)}".rstrip() for k, v in meta.items())
        new_text = f"---\n{header}\n---\n{body.lstrip(chr(10))}"
        tracked = in_git and run_git(project.root, "ls-files", "--error-unmatch", str(src))[0] == 0
        if tracked:
            code, _, err = run_git(project.root, "mv", str(src), str(dst))
            if code != 0:
                die(f"git mv falhou para {src.name}: {err.strip()}")
        else:
            src.rename(dst)
        dst.write_text(new_text, encoding="utf-8")
    for folder in LEGACY_DIRS:
        d = project.specs_dir / folder
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    print(f"\nMigradas {len(plan)} spec(s) com `legacy: true` (validate checa só o frontmatter delas).")
    print("Specs abertas: reescreva no template atual, preencha depends_on/touches e remova `legacy` antes de planejar.")
    print("Links antigos por caminho (proposed/…/arquivo.md) precisam ser trocados por referências de ID.")
    if (project.specs_dir / "references").is_dir():
        print("docs/specs/references/ (template antigo) pode ser removida: os templates vivem na skill.")
    return 0


# ---------------------------------------------------------------- cli

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="spec_graph.py",
        description="Ferramentas determinísticas do SDD: G0, ondas de execução, índice e G1/G4 via git.")
    parser.add_argument("--root", help="raiz do projeto (padrão: detectada a partir do diretório atual)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate", help="G0: valida specs/ADRs (todos ou os IDs informados; épico inclui filhas)")
    p.add_argument("ids", nargs="*")
    sub.add_parser("waves", help="plano de execução em ondas + próximo lote")
    sub.add_parser("next", help="próximo lote pronto para despachar")
    p = sub.add_parser("index", help="gera docs/specs/INDEX.md")
    p.add_argument("--stdout", action="store_true")
    p = sub.add_parser("verify", help="G1/G4 via git: red antes do green, tags de teste, escopo")
    p.add_argument("id")
    p.add_argument("--base", help="branch base (padrão: base_branch do sdd-config.yml ou main)")
    p = sub.add_parser("impacted", help="specs afetadas por mudança no contrato/implementação de uma spec")
    p.add_argument("id")
    p = sub.add_parser("report", help="resumo de entrega (o que, como, verificação, gates) para PR/changelog")
    p.add_argument("id")
    p = sub.add_parser("impede", help="registra impedimento (spec | decisão | trabalho | externo | falha)")
    p.add_argument("id")
    p.add_argument("--type", required=True)
    p.add_argument("--reason", required=True, help="o que falta para prosseguir")
    p.add_argument("--owner", required=True, help="quem precisa agir")
    p.add_argument("--phase", help="fase ou gate em que parou (ex: G2, EXECUTE)")
    p.add_argument("--tried", help="o que já foi tentado")
    p = sub.add_parser("resolve", help="fecha impedimento apontando a resolução (emenda, ADR, SPEC-NNNN ou ação)")
    p.add_argument("id")
    p.add_argument("imp_id")
    p.add_argument("--resolution", required=True)
    p = sub.add_parser("new", help="cria spec a partir do template com o próximo ID")
    p.add_argument("--tier", choices=TIERS, required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--slug")
    p.add_argument("--parent")
    p = sub.add_parser("new-adr", help="cria ADR a partir do template")
    p.add_argument("--title", required=True)
    p.add_argument("--slug")
    p = sub.add_parser("set", help="atualiza frontmatter: set ID [ID ...] chave=valor (valor 'today' = data de hoje)")
    p.add_argument("args", nargs="+")
    p = sub.add_parser("next-id", help="próximo ID livre")
    p.add_argument("kind", choices=("spec", "adr"))
    p = sub.add_parser("migrate", help="converte o layout legado (pastas de status + nomes com data)")
    p.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else find_root(Path.cwd())
    project = Project(root)
    if args.command == "validate":
        return cmd_validate(project, args.ids)
    if args.command == "waves":
        return cmd_waves(project)
    if args.command == "next":
        return cmd_next(project)
    if args.command == "index":
        return cmd_index(project, args.stdout)
    if args.command == "verify":
        return cmd_verify(project, args.id, args.base)
    if args.command == "impacted":
        return cmd_impacted(project, args.id)
    if args.command == "report":
        return cmd_report(project, args.id)
    if args.command == "impede":
        return cmd_impede(project, args.id, args.type, args.reason, args.owner, args.phase, args.tried)
    if args.command == "resolve":
        return cmd_resolve(project, args.id, args.imp_id, args.resolution)
    if args.command == "new":
        return cmd_new(project, args.tier, args.title, args.slug, args.parent)
    if args.command == "new-adr":
        return cmd_new_adr(project, args.title, args.slug)
    if args.command == "set":
        return cmd_set(project, args.args)
    if args.command == "next-id":
        return cmd_next_id(project, args.kind)
    if args.command == "migrate":
        return cmd_migrate(project, args.apply)
    return 2


if __name__ == "__main__":
    sys.exit(main())
