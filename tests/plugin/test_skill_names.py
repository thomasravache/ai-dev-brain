"""Nomes das skills e identificadores mantidos (SPEC-0055, ADR-0018).

Run: python3 -m unittest discover -s tests/plugin -p test_skill_names.py

As skills passam a se chamar gluon-spec, photon-brain e boson-atlas (pasta, `name` e textos de apresentação);
scripts, pastas de configuração, contratos e saídas das CLIs ficam com os nomes de antes. Como nos testes de
arquitetura das skills, a busca por referência velha (UT-03) é testada contra um exemplo que a viola e contra os
arquivos versionados reais.

Este arquivo nunca escreve um caminho velho por extenso (ele monta "skills" + "/" + nome), para não ser acusado
pela própria busca sem precisar de uma exceção para si mesmo.
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / "skills"

# nome novo -> nome antigo (contrato da SPEC-0055, §6)
RENAMES = {
    "gluon-spec": "sdd-management",
    "photon-brain": "second-brain",
    "boson-atlas": "org-atlas",
}
OLD_NAMES = tuple(RENAMES.values())

# Versão de cada skill antes da troca (SPEC-0055:UT-05). Também marca até onde vão as "seções antigas" dos
# CHANGELOGs, que guardam o histórico com os caminhos velhos (exceção do UT-03).
BASELINE = {
    "gluon-spec": ("scripts/spec_graph.py", "SDD_TOOL_VERSION", "2026.11.1"),
    "photon-brain": ("scripts/brain.py", "BRAIN_VERSION", "2026.11.5"),
    "boson-atlas": ("scripts/atlas.py", "ATLAS_VERSION", "2026.11.2"),
}

# ---------------------------------------------------------------- busca por referência velha (UT-03)
#
# Exceções, todas estreitas e explícitas:
#   1. docs/specs/ e docs/adr/: histórico das decisões (não-objetivo da SPEC-0055).
#   2. skills/<nome novo ou antigo>/CHANGELOG.md: só as linhas dentro de seções "## [VERSÃO]" com versão menor ou
#      igual à de antes da troca (BASELINE). [Unreleased] e as seções novas, onde entra "passa a se chamar", são
#      varridas: a entrada da troca cita os nomes (`gluon-spec`, antes `sdd-management`), não o caminho velho.
#   3. ".claude/skills/<nome antigo>": cópia antiga instalada na máquina de quem usa, fora do repositório; o README
#      orienta apagá-la (§2 e §8 da spec). Só esse prefixo exato, nada mais com "skills/" no meio.
#   4. Identificadores mantidos pelo contrato ("org-atlas/collector@1", ".org-atlas/", "~/.config/org-atlas",
#      "~/.config/second-brain") não precisam de exceção: o padrão exige "skills/" logo antes do nome, sem letra,
#      dígito, "_" ou "-" antes de "skills", e nenhum desses caracteres depois do nome. O teste de exemplo garante
#      que eles não são acusados.
#   5. Arquivos que não são UTF-8 (binários) não são lidos.
EXEMPT_PREFIXES = ("docs/specs/", "docs/adr/")
INSTALLED_COPY_PREFIX = ".claude/"
OLD_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_-])skills/(" + "|".join(re.escape(n) for n in OLD_NAMES) + r")(?![A-Za-z0-9_-])")
CHANGELOG_SECTION_RE = re.compile(r"^## \[([^\]]+)\]")


def version_tuple(text):
    """'2026.11.1' -> (2026, 11, 1); None quando não é uma versão AAAA.MM.N."""
    if not re.fullmatch(r"\d+(\.\d+)*", text or ""):
        return None
    return tuple(int(part) for part in text.split("."))


def changelog_baseline(rel_path):
    """Versão de antes da troca para o CHANGELOG de uma skill (nome novo ou antigo), ou None."""
    parts = rel_path.split("/")
    if len(parts) != 3 or parts[0] != "skills" or parts[2] != "CHANGELOG.md":
        return None
    name = parts[1]
    by_old = {old: new for new, old in RENAMES.items()}
    new = name if name in BASELINE else by_old.get(name)
    return version_tuple(BASELINE[new][2]) if new else None


def old_ref_findings(text, rel_path):
    """Uma linha "<arquivo>:<linha> — skills/<nome antigo>" por referência velha fora das exceções."""
    if rel_path.startswith(EXEMPT_PREFIXES):
        return []
    baseline = changelog_baseline(rel_path)
    in_old_section = False
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        if baseline is not None:
            section = CHANGELOG_SECTION_RE.match(line)
            if section:
                version = version_tuple(section.group(1))
                in_old_section = version is not None and version <= baseline
            if in_old_section:
                continue
        for match in OLD_REF_RE.finditer(line):
            if line[:match.start()].endswith(INSTALLED_COPY_PREFIX):
                continue
            findings.append(f"{rel_path}:{number} — {match.group(0)}")
    return findings


def find_old_refs(root, rel_paths):
    """Varre os arquivos (caminhos relativos a root) e devolve os achados de old_ref_findings."""
    findings = []
    for rel in rel_paths:
        path = Path(root) / rel
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(old_ref_findings(text, rel))
    return findings


def git_files(*args):
    out = subprocess.run(["git", "ls-files", "-z", *args], cwd=REPO, check=True, capture_output=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


# ---------------------------------------------------------------- utilitários

def frontmatter(path):
    """Campos `name` e `description` do frontmatter de um SKILL.md (aceita `>-`, `|` e valor na mesma linha)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), len(lines))
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


def tracked_skill_dirs():
    """Pastas de primeiro nível em skills/ com arquivo versionado ou novo não ignorado (sem __pycache__ velho)."""
    files = git_files("--cached", "--others", "--exclude-standard", "skills")
    return {p.split("/")[1] for p in files if p.count("/") >= 2 and (REPO / p).exists()}


def load_script(skill, script):
    path = SKILLS / skill / "scripts" / script
    if not path.is_file():
        raise AssertionError(f"{path.relative_to(REPO)} não existe")
    module_name = f"spec0055_{skill.replace('-', '_')}_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def read_version(skill):
    script, constant, _ = BASELINE[skill]
    path = SKILLS / skill / script
    if not path.is_file():
        raise AssertionError(f"{path.relative_to(REPO)} não existe")
    m = re.search(rf'^{constant} = "([^"]+)"', path.read_text(encoding="utf-8"), re.MULTILINE)
    if not m:
        raise AssertionError(f"{constant} não encontrado em {path.relative_to(REPO)}")
    return m.group(1)


def changelog_new_sections(skill):
    """Texto das seções do CHANGELOG com versão maior que a de antes da troca, ou [Unreleased]."""
    path = SKILLS / skill / "CHANGELOG.md"
    if not path.is_file():
        raise AssertionError(f"{path.relative_to(REPO)} não existe")
    baseline = version_tuple(BASELINE[skill][2])
    keep, chunks = False, []
    for line in path.read_text(encoding="utf-8").splitlines():
        section = CHANGELOG_SECTION_RE.match(line)
        if section:
            label = section.group(1)
            version = version_tuple(label)
            keep = label == "Unreleased" or (version is not None and version > baseline)
            continue
        if line.startswith("## "):
            keep = False
        if keep:
            chunks.append(line)
    return "\n".join(chunks)


# ---------------------------------------------------------------- UT-01

class SkillFoldersTest(unittest.TestCase):
    def test_skills_folder_has_exactly_the_new_names_and_name_matches_folder(self):
        """SPEC-0055:UT-01"""
        self.assertEqual(tracked_skill_dirs(), set(RENAMES), "skills/ deve ter só as três pastas novas")
        for skill in RENAMES:
            with self.subTest(skill=skill):
                skill_md = SKILLS / skill / "SKILL.md"
                self.assertTrue(skill_md.is_file(), f"{skill_md.relative_to(REPO)} não existe")
                self.assertEqual(frontmatter(skill_md).get("name"), skill)


# ---------------------------------------------------------------- UT-02

class OldNameAliasTest(unittest.TestCase):
    def test_description_cites_old_name_and_sdd_block_names_gluon_spec_before_sdd_management(self):
        """SPEC-0055:UT-02"""
        for skill, old in RENAMES.items():
            with self.subTest(skill=skill):
                skill_md = SKILLS / skill / "SKILL.md"
                self.assertTrue(skill_md.is_file(), f"{skill_md.relative_to(REPO)} não existe")
                description = frontmatter(skill_md).get("description", "")
                self.assertRegex(description, rf"antes\s+`?{re.escape(old)}`?",
                                 f"description de {skill} não cita o nome antigo ({old})")
        expected = "Carregue a skill `gluon-spec` (antes `sdd-management`)"
        for block in (SKILLS / "gluon-spec" / "assets" / "agents-snippet.md", REPO / "AGENTS.md"):
            with self.subTest(block=str(block.relative_to(REPO))):
                self.assertTrue(block.is_file(), f"{block.relative_to(REPO)} não existe")
                self.assertIn(expected, block.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- UT-03

class OldReferenceSearchTest(unittest.TestCase):
    def test_example_with_old_reference_is_reported_and_exceptions_are_not(self):
        """SPEC-0055:UT-03 (exemplo que viola a regra)"""
        old_path = "skills" + "/" + "sdd-management"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                "README.md": (f"cp -R {old_path} ~/.claude/skills/\n"
                              "rm -rf ~/.claude/skills/" + "second-brain\n"
                              "contrato org-atlas/collector@1 e pasta .org-atlas/skill\n"
                              "config em ~/.config/org-atlas e ~/.config/second-brain\n"
                              "skills/" + "org-atlas-v2 e myskills/" + "org-atlas não são o caminho velho\n"),
                ".github/workflows/ci.yml": "run: python -m unittest discover -s skills/" + "org-atlas/tests\n",
                "docs/specs/SPEC-0001-x.md": f"histórico: {old_path}\n",
                "docs/adr/ADR-0001-x.md": f"histórico: {old_path}\n",
                "skills/gluon-spec/CHANGELOG.md": (
                    "# Changelog\n\n## [Unreleased]\n\n"
                    f"- nova entrada citando {old_path}/CHANGELOG.md\n\n"
                    "## [2026.11.1] - 2026-11-02\n\n"
                    f"- entrada antiga citando {old_path}/CHANGELOG.md\n"),
            }
            for rel, text in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text, encoding="utf-8")
            (root / "binary.bin").write_bytes(b"\xff\xfe" + old_path.encode() + b"\x00\xff")
            findings = find_old_refs(root, [*files, "binary.bin"])
        self.assertEqual(findings, [
            f"README.md:1 — {old_path}",
            ".github/workflows/ci.yml:1 — skills/" + "org-atlas",
            "skills/gluon-spec/CHANGELOG.md:5 — " + old_path,
        ])

    def test_versioned_files_have_no_old_skill_path(self):
        """SPEC-0055:UT-03 (guarda: arquivos versionados reais)"""
        findings = find_old_refs(REPO, git_files())
        self.assertEqual(findings, [], "referência velha fora das exceções:\n" + "\n".join(findings))


# ---------------------------------------------------------------- UT-04

class KeptIdentifiersTest(unittest.TestCase):
    def test_scripts_keep_their_names_config_folders_contract_and_outputs(self):
        """SPEC-0055:UT-04"""
        for skill, script in (("gluon-spec", "spec_graph.py"), ("photon-brain", "brain.py"),
                              ("boson-atlas", "atlas.py")):
            with self.subTest(script=f"{skill}/scripts/{script}"):
                self.assertTrue((SKILLS / skill / "scripts" / script).is_file(),
                                f"skills/{skill}/scripts/{script} não existe")

        brain = load_script("photon-brain", "brain.py")
        atlas = load_script("boson-atlas", "atlas.py")
        sdd = load_script("gluon-spec", "spec_graph.py")

        with tempfile.TemporaryDirectory() as home:
            env = {k: v for k, v in os.environ.items() if k not in ("BRAIN_CONFIG_HOME", "ATLAS_CONFIG_HOME")}
            env["HOME"] = home
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(brain.local_config_path(),
                                 Path(home) / ".config" / "second-brain" / "config.yml")
                self.assertEqual(atlas.local_config_path(),
                                 Path(home) / ".config" / "org-atlas" / "config.yml")
            with mock.patch.dict(os.environ, {"BRAIN_CONFIG_HOME": f"{home}/b", "ATLAS_CONFIG_HOME": f"{home}/a"}):
                self.assertEqual(brain.local_config_path(), Path(home) / "b" / "config.yml")
                self.assertEqual(atlas.local_config_path(), Path(home) / "a" / "config.yml")

        self.assertEqual(atlas.CONTRACT, "org-atlas/collector@1")
        self.assertEqual(atlas.SKILL_COPY, ".org-atlas/skill")
        self.assertTrue(brain.BACKUP_NAME_RE.match("second-brain-2026-11-12-101010.zip"),
                        "nome de backup second-brain-AAAA-MM-DD-HHMMSS.zip mudou")
        self.assertEqual(sdd.VENDORED_TOOL, "tools/sdd/spec_graph.py")
        self.assertIn("<!-- sdd:start -->", sdd.AGENT_BLOCK_RE.pattern)
        self.assertIn("sdd-config.yml", (SKILLS / "gluon-spec" / "scripts" / "spec_graph.py").read_text(
            encoding="utf-8"))

        for skill, script, prefix in (("photon-brain", "brain.py", "second-brain "),
                                      ("boson-atlas", "atlas.py", "org-atlas ")):
            with self.subTest(version_output=skill):
                out = subprocess.run([sys.executable, str(SKILLS / skill / "scripts" / script), "--version"],
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertTrue(out.stdout.startswith(prefix), f"--version mudou: {out.stdout!r}")


# ---------------------------------------------------------------- UT-05

class VersionAndChangelogTest(unittest.TestCase):
    def test_version_is_bumped_and_changelog_has_rename_entry(self):
        """SPEC-0055:UT-05"""
        for skill, (_, constant, before) in BASELINE.items():
            with self.subTest(skill=skill):
                current = read_version(skill)
                self.assertIsNotNone(version_tuple(current), f"{constant} inválido: {current}")
                self.assertGreater(version_tuple(current), version_tuple(before),
                                   f"{constant} deveria subir de {before}")
                self.assertIn("passa a se chamar", changelog_new_sections(skill),
                              f"CHANGELOG de {skill} sem a entrada da troca de nome")


if __name__ == "__main__":
    unittest.main()
