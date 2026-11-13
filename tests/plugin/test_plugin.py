"""Plugin fermion e marketplace fermion-lab (SPEC-0053, ADR-0016).

Run: python3 -m unittest discover -s tests/plugin -p test_plugin.py

O repositório inteiro é o plugin: `.claude-plugin/marketplace.json` (marketplace `fermion-lab`, um plugin `fermion`
com `"source": "./"`), `.claude-plugin/plugin.json` e o scan padrão de `skills/<pasta>/SKILL.md`. Como nos testes de
arquitetura das skills, as checagens (`manifest_findings`, `self_containment_findings`) são testadas contra exemplos
que violam a regra e contra o repositório real.

E2E-01 roda o Claude Code CLI de verdade (pulado sem ele) com a configuração isolada numa pasta temporária:
`CLAUDE_CONFIG_DIR` (documentado em code.claude.com/docs/en/env-vars: "All settings, session history, and plugins
are stored under this path") e `HOME` temporários, `CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL=1` e cwd
temporário (menos no `validate .`, que só lê). Nunca toca a configuração real de quem roda.
"""
import ast
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / "skills"
PLUGIN_DIR = ".claude-plugin"

SKILL_CLIS = {"gluon-spec": "spec_graph.py", "photon-brain": "brain.py", "boson-atlas": "atlas.py"}
SKILL_NAMES = tuple(SKILL_CLIS)
OLD_SKILL_NAMES = ("sdd-management", "second-brain", "org-atlas")

KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d+)$")  # AAAA.MM.N (ex.: 2026.11.1)
MARKETPLACE_KEYS = {"name", "owner", "plugins", "metadata"}
# Campos de plugin.json que declaram caminho de componente (manifest-reference); o contrato não declara nenhum.
COMPONENT_KEYS = ("commands", "agents", "skills", "hooks", "mcpServers", "outputStyles", "lspServers", "monitors",
                  "themes", "channels")


def git_files(*args, cwd=REPO):
    out = subprocess.run(["git", "ls-files", "-z", *args], cwd=cwd, check=True, capture_output=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def report(findings):
    return "\n".join(str(f) for f in findings)


# ---------------------------------------------------------------- manifestos (UT-01..UT-03)

def _load_json(path, label, findings):
    """Lê um manifesto; acrescenta '<label>-missing' ou '<label>-json' e devolve None quando não dá."""
    if not path.is_file():
        findings.append(f"{label}-missing: {PLUGIN_DIR}/{path.name} não existe")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        findings.append(f"{label}-json: {PLUGIN_DIR}/{path.name} não é JSON válido ({exc})")
        return None
    if not isinstance(data, dict):
        findings.append(f"{label}-json: {PLUGIN_DIR}/{path.name} não é um objeto JSON")
        return None
    return data


def _non_empty_str(value):
    return isinstance(value, str) and value.strip() != ""


def manifest_findings(root):
    """Achados "<código>: <detalhe>" dos dois manifestos em <root>/.claude-plugin/ (lista vazia = válidos).

    Checa o formato do contrato (SPEC-0053 §6), não os valores exatos (UT-01 e UT-02 conferem esses).
    """
    findings = []
    base = Path(root) / PLUGIN_DIR
    market = _load_json(base / "marketplace.json", "marketplace", findings)
    plugin = _load_json(base / "plugin.json", "plugin", findings)

    entry = None
    if market is not None:
        name = market.get("name")
        if not (isinstance(name, str) and KEBAB_RE.match(name)):
            findings.append(f"marketplace-name: nome {name!r} fora de kebab-case")
        extra = sorted(set(market) - MARKETPLACE_KEYS)
        if extra:
            findings.append(f"marketplace-keys: chaves de topo fora do contrato: {extra}")
        owner = market.get("owner")
        if not (isinstance(owner, dict) and _non_empty_str(owner.get("name"))):
            findings.append("marketplace-owner: owner.name vazio ou ausente")
        plugins = market.get("plugins")
        if not (isinstance(plugins, list) and len(plugins) == 1 and isinstance(plugins[0], dict)):
            findings.append("marketplace-plugins: plugins deve ter exatamente um plugin")
        else:
            entry = plugins[0]
            entry_name = entry.get("name")
            if not (isinstance(entry_name, str) and KEBAB_RE.match(entry_name)):
                findings.append(f"entry-name: plugins[0].name {entry_name!r} fora de kebab-case")
            if entry.get("source") != "./":
                findings.append(f"entry-source: plugins[0].source {entry.get('source')!r} diferente de \"./\"")
            if not _non_empty_str(entry.get("description")):
                findings.append("entry-description: plugins[0].description vazia ou ausente")

    if plugin is not None:
        name = plugin.get("name")
        if not (isinstance(name, str) and KEBAB_RE.match(name)):
            findings.append(f"plugin-name: nome {name!r} fora de kebab-case")
        elif entry is not None and isinstance(entry.get("name"), str) and entry.get("name") != name:
            findings.append(f"name-mismatch: plugin.json {name!r} e marketplace {entry.get('name')!r}")
        version = plugin.get("version")
        match = VERSION_RE.match(version) if isinstance(version, str) else None
        if not (match and 1 <= int(match.group(2)) <= 12):
            findings.append(f"plugin-version: versão {version!r} fora de AAAA.MM.N")
        if not _non_empty_str(plugin.get("description")):
            findings.append("plugin-description: description vazia ou ausente")
        if not _non_empty_str(plugin.get("repository")):
            findings.append("plugin-repository: repository vazio ou ausente")
        declared = [key for key in COMPONENT_KEYS if key in plugin]
        if declared:
            findings.append(f"plugin-components: caminho de componente declarado: {declared}")
    return findings


def codes(findings):
    return [f.split(":", 1)[0] for f in findings]


def read_manifest(name):
    path = REPO / PLUGIN_DIR / name
    if not path.is_file():
        raise AssertionError(f"{PLUGIN_DIR}/{name} não existe")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- frontmatter e scan (UT-04)

def frontmatter(path):
    """Campos do frontmatter de um SKILL.md (aceita `>-`, `|` e valor na mesma linha); {} sem frontmatter."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}
    fields, i = {}, 1
    while i < end:
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", lines[i])
        i += 1
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if value in (">-", ">", "|", "|-", ">+", "|+", ""):
            block = []
            while i < end and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            value = " ".join(part for part in block if part)
        fields[key] = value.strip("\"'")
    return fields


def scanned_skills(root):
    """Simula o scan padrão do Claude Code: skills/<pasta>/SKILL.md versionados (o plugin é a cópia do git)."""
    return sorted(p.split("/")[1] for p in git_files("skills", cwd=root)
                  if p.count("/") == 2 and p.endswith("/SKILL.md") and (Path(root) / p).is_file())


# ---------------------------------------------------------------- autocontenção (UT-05, contrato v2)
#
# Vale só para o que a skill resolve a partir da própria pasta:
#   1. link Markdown relativo ([x](caminho)) num .md da skill cujo destino, resolvido a partir do arquivo, sai de
#      skills/<nome>/ (links em blocos e trechos de código, URLs, âncoras e caminhos absolutos ou com ~ não contam);
#   2. "<skill-dir>/.." em qualquer texto da skill;
#   3. nos scripts .py: Path(__file__) (ou os.path.dirname(__file__)) subindo além da pasta da skill, sys.path com
#      "..", "tools" ou o nome de outra skill, e string com "../<outra skill>".
# Caminhos do projeto, vault ou atlas de quem usa (docs/specs/, tools/sdd/, ../{repo}.worktrees) são permitidos.
# tests/ da skill fica fora (fixtures e exemplos de violação), assim como __pycache__ e arquivos não UTF-8.

MD_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE_RE = re.compile(r"^(\s*)(```|~~~)")
INLINE_CODE_RE = re.compile(r"`+[^`\n]*`+")
SKILL_DIR_UP_RE = re.compile(r"<skill-dir>/\.\.(?:/|$|[\s`'\")])")
OTHER_SKILL_RE = re.compile(
    r"(?:^|/)\.\./(?:" + "|".join(re.escape(n) for n in SKILL_NAMES + OLD_SKILL_NAMES) + r")(?:/|$)")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
EXCLUDED_DIRS = {"tests", "__pycache__"}


def _skill_files(skill_dir):
    for path in sorted(Path(skill_dir).rglob("*")):
        rel = path.relative_to(skill_dir)
        if path.is_symlink() or not path.is_file() or EXCLUDED_DIRS.intersection(rel.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        yield rel, text


def _escapes(rel_file, target):
    """True quando `target`, resolvido a partir da pasta de rel_file (relativo à skill), sai da pasta da skill."""
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(rel_file.as_posix()), target))
    return joined == ".." or joined.startswith("../")


def markdown_link_findings(text, rel):
    findings, in_fence = [], False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in MD_LINK_RE.finditer(INLINE_CODE_RE.sub("", line)):
            target = match.group(1).split("#", 1)[0].split("?", 1)[0]
            if not target or SCHEME_RE.match(target) or target.startswith(("/", "~")):
                continue
            if _escapes(rel, target):
                findings.append((rel.as_posix(), number, f"link relativo sai da skill: {match.group(1)}"))
    return findings


def skill_dir_up_findings(text, rel):
    return [(rel.as_posix(), number, "<skill-dir>/.. sai da skill")
            for number, line in enumerate(text.splitlines(), start=1) if SKILL_DIR_UP_RE.search(line)]


def _is_file_name(node):
    return isinstance(node, ast.Name) and node.id == "__file__"


def _levels_up(node):
    """Quantos níveis acima de __file__ a expressão chega (Path(__file__).parent/.parents[n], os.path.dirname)."""
    if isinstance(node, ast.Attribute):
        if node.attr == "parent":
            inner = _levels_up(node.value)
            return None if inner is None else inner + 1
        return None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
        inner = _levels_up(node.value.value)
        index = node.slice
        if inner is None or not (isinstance(index, ast.Constant) and isinstance(index.value, int)):
            return None
        return inner + index.value + 1
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in ("Path", "PurePath") and node.args and _is_file_name(node.args[0]):
            return 0
        if name in ("resolve", "absolute") and isinstance(func, ast.Attribute):
            return _levels_up(func.value)
        if name in ("abspath", "realpath", "normpath") and node.args:
            return _levels_up(node.args[0])
        if name == "dirname" and node.args:
            inner = _levels_up(node.args[0])
            return None if inner is None else inner + 1
    if _is_file_name(node):
        return 0
    return None


def _strings(node):
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def script_findings(source, rel):
    """Achados (arquivo, linha, motivo) de um .py da skill; rel é o caminho relativo à pasta da skill."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [(rel.as_posix(), exc.lineno or 0, "script não compila")]
    depth = len(rel.parts)  # a pasta da skill fica depth níveis acima de __file__
    findings = []
    for node in ast.walk(tree):
        levels = _levels_up(node) if isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)) else None
        if levels is not None and levels > depth:
            findings.append((rel.as_posix(), node.lineno, "Path(__file__) sobe além da pasta da skill"))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("insert", "append", "extend")
                and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "path"
                and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "sys"):
            for text in _strings(node):
                parts = set(re.split(r"[\\/]", text))
                if ".." in parts or "tools" in parts or parts & set(SKILL_NAMES + OLD_SKILL_NAMES):
                    findings.append((rel.as_posix(), node.lineno, f"sys.path aponta para fora da skill: {text!r}"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and OTHER_SKILL_RE.search(node.value):
            findings.append((rel.as_posix(), node.lineno, f"caminho para outra skill: {node.value!r}"))
    return findings


def self_containment_findings(skill_dir):
    """Achados "<arquivo>:<linha> — <motivo>" (um por linha) do que a skill resolve para fora da própria pasta."""
    skill_dir = Path(skill_dir)
    raw = []
    for rel, text in _skill_files(skill_dir):
        raw.extend(skill_dir_up_findings(text, rel))
        if rel.suffix == ".md":
            raw.extend(markdown_link_findings(text, rel))
        if rel.suffix == ".py":
            raw.extend(script_findings(text, rel))
    seen, findings = set(), []
    for file, line, reason in sorted(raw):
        if (file, line) not in seen:
            seen.add((file, line))
            findings.append(f"{file}:{line} — {reason}")
    return findings


# ---------------------------------------------------------------- UT-01

class MarketplaceManifestTest(unittest.TestCase):
    def test_marketplace_has_contract_fields_and_single_fermion_plugin(self):
        """SPEC-0053:UT-01"""
        market = read_manifest("marketplace.json")
        self.assertEqual(market.get("name"), "fermion-lab")
        self.assertLessEqual(set(market), MARKETPLACE_KEYS, "chave de topo fora de name/owner/plugins/metadata")
        owner = market.get("owner")
        self.assertIsInstance(owner, dict)
        self.assertTrue(_non_empty_str(owner.get("name")), "owner.name vazio")
        self.assertNotIn("email", owner, "o owner é só o login público, sem e-mail (§5)")
        plugins = market.get("plugins")
        self.assertIsInstance(plugins, list)
        self.assertEqual(len(plugins), 1, "um único plugin")
        self.assertEqual(plugins[0].get("name"), "fermion")
        self.assertEqual(plugins[0].get("source"), "./")
        self.assertTrue(_non_empty_str(plugins[0].get("description")), "plugins[0].description vazia")


# ---------------------------------------------------------------- UT-02

class PluginManifestTest(unittest.TestCase):
    def test_plugin_json_matches_marketplace_and_declares_no_component_path(self):
        """SPEC-0053:UT-02"""
        plugin = read_manifest("plugin.json")
        market = read_manifest("marketplace.json")
        self.assertEqual(plugin.get("name"), "fermion")
        self.assertEqual(plugin.get("name"), market["plugins"][0].get("name"))
        version = plugin.get("version")
        match = VERSION_RE.match(version) if isinstance(version, str) else None
        self.assertTrue(match and 1 <= int(match.group(2)) <= 12, f"version {version!r} fora de AAAA.MM.N")
        self.assertTrue(_non_empty_str(plugin.get("description")), "description vazia")
        self.assertEqual(plugin.get("repository"), "https://github.com/thomasravache/ai-dev-brain")
        self.assertNotIn("license", plugin, "o repositório ainda não tem licença (§2)")
        self.assertEqual([k for k in COMPONENT_KEYS if k in plugin], [], "caminho de componente declarado")


# ---------------------------------------------------------------- UT-03

VALID_MARKETPLACE = {"name": "fermion-lab", "owner": {"name": "thomasravache"},
                     "plugins": [{"name": "fermion", "source": "./", "description": "SDD, cérebro e atlas."}]}
VALID_PLUGIN = {"name": "fermion", "version": "2026.11.1", "description": "Skills.",
                "repository": "https://github.com/thomasravache/ai-dev-brain"}


def write_manifests(root, marketplace=VALID_MARKETPLACE, plugin=VALID_PLUGIN):
    base = Path(root) / PLUGIN_DIR
    base.mkdir(parents=True, exist_ok=True)
    for name, data in (("marketplace.json", marketplace), ("plugin.json", plugin)):
        text = data if isinstance(data, str) else json.dumps(data)
        (base / name).write_text(text, encoding="utf-8")


class ManifestCheckTest(unittest.TestCase):
    def test_each_invalid_manifest_has_its_own_finding(self):
        """SPEC-0053:UT-03 (exemplos que violam a regra)"""
        entry = VALID_MARKETPLACE["plugins"][0]
        cases = {
            "JSON quebrado (marketplace)": ({"marketplace": '{"name": "fermion-lab",'}, ["marketplace-json"]),
            "JSON quebrado (plugin)": ({"plugin": '{"name": '}, ["plugin-json"]),
            "nome Fermion_Lab": ({"marketplace": {**VALID_MARKETPLACE, "name": "Fermion_Lab"}},
                                 ["marketplace-name"]),
            "plugin.json com name diferente": ({"plugin": {**VALID_PLUGIN, "name": "fermion-x"}},
                                               ["name-mismatch"]),
            "source ./plugins/x": ({"marketplace": {**VALID_MARKETPLACE,
                                                    "plugins": [{**entry, "source": "./plugins/x"}]}},
                                   ["entry-source"]),
            "chave de topo extra": ({"marketplace": {**VALID_MARKETPLACE, "extra": 1}}, ["marketplace-keys"]),
            "dois plugins": ({"marketplace": {**VALID_MARKETPLACE, "plugins": [entry, entry]}},
                             ["marketplace-plugins"]),
            "versão fora de AAAA.MM.N": ({"plugin": {**VALID_PLUGIN, "version": "1.0.0"}}, ["plugin-version"]),
            "caminho de componente": ({"plugin": {**VALID_PLUGIN, "skills": "./skills"}}, ["plugin-components"]),
        }
        with tempfile.TemporaryDirectory() as tmp:
            write_manifests(tmp)
            self.assertEqual(manifest_findings(tmp), [], "a base dos exemplos deve ser válida")
        for label, (override, expected) in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                write_manifests(tmp, override.get("marketplace", VALID_MARKETPLACE),
                                override.get("plugin", VALID_PLUGIN))
                findings = manifest_findings(tmp)
                self.assertEqual(codes(findings), expected, report(findings))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(codes(manifest_findings(tmp)), ["marketplace-missing", "plugin-missing"])

    def test_repository_manifests_have_no_finding(self):
        """SPEC-0053:UT-03 (guarda: manifestos reais)"""
        findings = manifest_findings(REPO)
        self.assertEqual(findings, [], report(findings))


# ---------------------------------------------------------------- UT-04

class SkillScanTest(unittest.TestCase):
    def test_default_scan_finds_the_three_skills_with_name_and_description(self):
        """SPEC-0053:UT-04"""
        self.assertEqual(scanned_skills(REPO), sorted(SKILL_NAMES))
        for skill in SKILL_NAMES:
            with self.subTest(skill=skill):
                fields = frontmatter(SKILLS / skill / "SKILL.md")
                self.assertEqual(fields.get("name"), skill)
                self.assertTrue(_non_empty_str(fields.get("description")), "description vazia")


# ---------------------------------------------------------------- UT-05

class SelfContainmentTest(unittest.TestCase):
    def test_example_skill_reports_escapes_but_not_target_project_paths(self):
        """SPEC-0053:UT-05 (exemplo que viola a regra)"""
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "skills" / "exemplo"
            files = {
                "SKILL.md": ("---\nname: exemplo\ndescription: Exemplo.\n---\n"
                             "Veja [x](../shared/a.md).\n"                                 # 5: acusado
                             "Rode `python3 <skill-dir>/../tools/sdd/x`.\n"                # 6: acusado
                             "Antes, rode `docs/specs/INDEX.md`.\n"                        # 7: projeto alvo
                             "Use o `tools/sdd/spec_graph.py` do projeto.\n"               # 8: projeto alvo
                             "Worktrees em `../{repo}.worktrees` e [ok](references/r.md).\n"
                             "Links [web](https://example.com/../x), [âncora](#topo), `[c](../x.md)`.\n"
                             "```\n[bloco](../../fora.md)\n```\n"
                             "Rode `<skill-dir>/scripts/x.py`.\n"),
                "references/r.md": "[volta](../SKILL.md) e [projeto](../../outra/x.md)\n",  # 1: acusado
                "scripts/x.py": ("import sys\nfrom pathlib import Path\n\n"
                                 'sys.path.insert(0, str(Path(__file__).parents[2] / "tools"))\n'  # 4: acusado
                                 "HERE = Path(__file__).resolve().parent.parent\n"
                                 'VENDORED = "tools/sdd/spec_graph.py"\n'
                                 'WORKTREE = "../{repo}.worktrees"\n'),
                "tests/test_x.py": 'import sys\nsys.path.insert(0, "../gluon-spec/scripts")\n',
                "tests/fixtures/a.md": "[fora](../../../x.md)\n",
            }
            for rel, text in files.items():
                (skill / rel).parent.mkdir(parents=True, exist_ok=True)
                (skill / rel).write_text(text, encoding="utf-8")
            findings = self_containment_findings(skill)
        self.assertEqual([f.split(" — ")[0] for f in findings],
                         ["SKILL.md:5", "SKILL.md:6", "references/r.md:1", "scripts/x.py:4"], report(findings))

    def test_script_paths_to_other_skill_or_above_skill_are_reported(self):
        """SPEC-0053:UT-05 (exemplo: caminhos de script)"""
        source = ("import os, sys\nfrom pathlib import Path\n"
                  'sys.path.append("../photon-brain/scripts")\n'                              # 3
                  "ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"  # 4
                  'OTHER = "../boson-atlas/scripts/atlas.py"\n'                               # 5
                  "SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
                  "OK = Path(__file__).parents[1]\n")
        findings = script_findings(source, Path("scripts/x.py"))
        self.assertEqual(sorted({line for _, line, _ in findings}), [3, 4, 5], report(findings))

    def test_real_skills_are_self_contained(self):
        """SPEC-0053:UT-05 (guarda: as três skills reais, fora de tests/)"""
        for skill in SKILL_NAMES:
            with self.subTest(skill=skill):
                self.assertTrue((SKILLS / skill).is_dir(), f"skills/{skill} não existe")
                findings = self_containment_findings(SKILLS / skill)
                self.assertEqual(findings, [], report(findings))


# ---------------------------------------------------------------- IT-01

def copy_tracked(rel_paths, src_root, dest_root, strip=""):
    """Copia os arquivos (relativos a src_root) para dest_root, tirando o prefixo `strip`; links viram links."""
    for rel in rel_paths:
        src = Path(src_root) / rel
        if not (src.is_file() or src.is_symlink()):
            continue  # apagado na árvore e ainda no índice
        dest = Path(dest_root) / rel[len(strip):]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest, follow_symlinks=False)


def run_help(script, cwd):
    return subprocess.run([sys.executable, str(script), "--help"], cwd=cwd, capture_output=True, text=True,
                          timeout=60, check=False)


class PluginCopyTest(unittest.TestCase):
    def test_clis_run_from_plugin_cache_copy_and_from_lone_skill_copy(self):
        """SPEC-0053:IT-01"""
        tracked = git_files()
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache" / "fermion-lab" / "fermion" / "2026.11.1"
            copy_tracked(tracked, REPO, cache)
            for manifest in ("marketplace.json", "plugin.json"):
                self.assertTrue((cache / PLUGIN_DIR / manifest).is_file(),
                                f"{PLUGIN_DIR}/{manifest} não está nos arquivos versionados copiados para o cache")
            for skill, cli in SKILL_CLIS.items():
                with self.subTest(copy="cache", skill=skill):
                    result = run_help(cache / "skills" / skill / "scripts" / cli, cwd=tmp)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                with self.subTest(copy="pasta sozinha", skill=skill):
                    prefix = f"skills/{skill}/"
                    lone = Path(tmp) / "lone" / skill
                    copy_tracked([p for p in tracked if p.startswith(prefix)], REPO, lone, strip=prefix)
                    self.assertTrue((lone / "SKILL.md").is_file(), f"{prefix}SKILL.md não foi copiado")
                    result = run_help(lone / "scripts" / cli, cwd=tmp)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


# ---------------------------------------------------------------- E2E-01

class PluginInstallJourneyTest(unittest.TestCase):
    def test_validate_add_marketplace_install_and_list_with_isolated_config(self):
        """SPEC-0053:E2E-01 [jornada: instalação do plugin]"""
        claude = shutil.which("claude")
        if not claude:
            self.skipTest("Claude Code CLI (claude) não está no PATH; E2E-01 roda localmente no G4 e no G5")
        real_config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").resolve()
        with tempfile.TemporaryDirectory() as tmp:
            home, config, work = Path(tmp) / "home", Path(tmp) / "config", Path(tmp) / "work"
            for folder in (home, config, work):
                folder.mkdir()
            env = dict(os.environ)
            env.update({"HOME": str(home), "CLAUDE_CONFIG_DIR": str(config), "XDG_CONFIG_HOME": str(home / ".config"),
                        "CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL": "1"})
            self.assertNotEqual(config.resolve(), real_config)

            def claude_run(*args, cwd=work):
                return subprocess.run([claude, "plugin", *args], cwd=cwd, env=env, capture_output=True, text=True,
                                      timeout=300, check=False)

            def ok(result):
                self.assertEqual(result.returncode, 0, f"{result.args}\n{result.stdout}\n{result.stderr}")
                return result.stdout

            ok(claude_run("validate", ".", cwd=REPO))
            ok(claude_run("marketplace", "add", str(REPO), "--scope", "user", "--json"))
            marketplaces = json.loads(ok(claude_run("marketplace", "list", "--json")))
            self.assertIn("fermion-lab", [m.get("name") for m in marketplaces])
            ok(claude_run("install", "fermion@fermion-lab", "--scope", "user", "--json"))
            installed = {p.get("id"): p for p in json.loads(ok(claude_run("list", "--json")))}
            self.assertIn("fermion@fermion-lab", installed, report(installed))
            plugin = installed["fermion@fermion-lab"]
            self.assertTrue(plugin.get("enabled"), "plugin fermion instalado mas não habilitado")
            install_path = Path(plugin.get("installPath", ""))
            self.assertTrue(install_path.resolve().is_relative_to(config.resolve()),
                            f"cache fora da configuração isolada: {install_path}")
            self.assertEqual(scanned_skills_in(install_path), sorted(SKILL_NAMES))
            details = ok(claude_run("details", "fermion@fermion-lab"))
            for skill in SKILL_NAMES:
                self.assertIn(skill, details)


def scanned_skills_in(plugin_root):
    """Pastas skills/<nome>/SKILL.md de uma cópia instalada (sem git)."""
    return sorted(p.parent.name for p in Path(plugin_root).glob("skills/*/SKILL.md"))


if __name__ == "__main__":
    unittest.main()
