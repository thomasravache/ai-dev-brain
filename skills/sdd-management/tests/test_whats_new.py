"""Novidades da skill para os projetos (SPEC-0013): CHANGELOG por versão, `whats-new [--ack]` e a linha do `status`.

Contrato esperado das funções puras de scripts/spec_graph.py (o Implementer segue estes testes):

    version_key(version: str) -> tuple[int, ...]
        "2026.10.10" -> (2026, 10, 10); compara versões numericamente (2026.10.10 > 2026.10.9).

    changelog_since(text: str, since: str | None, until: str) -> list[str]
        text  : conteúdo do CHANGELOG (Keep a Changelog, seções "## [AAAA.MM.N] - AAAA-MM-DD")
        devolve o texto completo de cada seção de versão (do cabeçalho "## [X] - data", incluído, até o próximo
        cabeçalho "## ", exclusivo) com since < X <= until (comparação por version_key), na ordem do arquivo.
        "[Unreleased]" e o preâmbulo nunca entram. since=None -> [].

    missing_config_keys(template_text: str, config: dict) -> list[tuple[str, str]]
        template_text : texto do sdd-config.template.yml
        config        : sdd-config do projeto já lido (parse_yaml_subset)
        devolve (chave, comentário) para cada chave de topo do template (linha sem indentação "chave:") ausente
        em config, na ordem do template. Chave presente com valor vazio ("" ou bloco vazio) conta como presente.
        Linhas comentadas ("# chave: ...") não são chaves. comentário = as linhas "#" imediatamente acima da
        chave (sem linha em branco no meio), sem o "#" e sem espaços nas pontas, unidas por um espaço; "" se não houver.

Testes de integração rodam a CLI em repositórios temporários (diretórios resolvidos, por causa de /var vs
/private/var no macOS) com o registro do usuário isolado (SDD_CONFIG_HOME). Para "skill sem CHANGELOG" (IT-05)
a pasta da skill é copiada para um diretório temporário sem CHANGELOG.md e roda-se o scripts/spec_graph.py
da cópia: a ferramenta lê CHANGELOG e template relativos ao próprio SKILL_DIR.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
SKILL = TESTS.parent
SCRIPT = SKILL / "scripts" / "spec_graph.py"
REFS = SKILL / "references"
REPO = SKILL.parent.parent
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(TESTS))
import spec_graph as sg
from test_private_mode import PrivateTestCase, git
from test_spec_graph import Project

CHANGELOG = SKILL / "CHANGELOG.md"
TEMPLATE = REFS / "sdd-config.template.yml"
VERSION = sg.SDD_TOOL_VERSION
OLD = "2026.10.8"
VERSION_HEADER = re.compile(r"^## \[(\d{4}\.\d{1,2}\.\d+)\] - \d{4}-\d{2}-\d{2}$")
NEWS_LINE = re.compile(r"Novidades da skill: (\d+) versão\(ões\) e (\d+) configuração\(ões\) nova\(s\) — rode whats-new")

SAMPLE_CHANGELOG = """# Changelog

Formato: Keep a Changelog.

## [Unreleased]
- ainda não lançado (SPEC-0099)

## [2026.10.10] - 2026-10-26
### Added
- whats-new (SPEC-0013)

## [2026.10.9] - 2026-10-20
### Added
- documentos vivos (SPEC-0011)
### Fixed
- caminho resolvido (SPEC-0012)

## [2026.10.8] - 2026-10-15
### Added
- modo privado (SPEC-0003)
"""

SAMPLE_TEMPLATE = """# Configuração SDD do projeto — cabeçalho geral.

base_branch: main
# Documentos vivos: guia de jornadas e mapa do sistema.
#   "" desliga um documento.
living_docs:
  journeys: docs/jornadas.md   # guia
  system_map: docs/arquitetura.md
# pr_merge_pattern: "Merge pull request"
h2_policy: per-wave
"""

_USER_ENV = {}


def setUpModule():
    """Isola o registro do usuário (projects.json), como as demais suítes."""
    _USER_ENV["SDD_CONFIG_HOME"] = os.environ.get("SDD_CONFIG_HOME")
    _USER_ENV["dir"] = tempfile.mkdtemp()
    os.environ["SDD_CONFIG_HOME"] = _USER_ENV["dir"]


def tearDownModule():
    if _USER_ENV["SDD_CONFIG_HOME"] is None:
        os.environ.pop("SDD_CONFIG_HOME", None)
    else:
        os.environ["SDD_CONFIG_HOME"] = _USER_ENV["SDD_CONFIG_HOME"]
    shutil.rmtree(_USER_ENV["dir"], ignore_errors=True)


def fn(name):
    """Função de spec_graph exigida pela SPEC-0013; ausente = o teste falha pelo motivo certo, sem quebrar a suíte."""
    f = getattr(sg, name, None)
    if f is None:
        raise AssertionError(f"spec_graph.{name} não existe (SPEC-0013)")
    return f


def vkey(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


def changelog_versions() -> list:
    """Versões (em ordem do arquivo) do CHANGELOG real da skill; ausente = falha pelo motivo certo."""
    if not CHANGELOG.exists():
        raise AssertionError(f"{CHANGELOG} não existe (SPEC-0013)")
    return [m.group(1) for m in (VERSION_HEADER.match(line) for line in CHANGELOG.read_text(encoding="utf-8")
                                 .splitlines()) if m]


def vendor_tool(root: Path, version: str):
    """tools/sdd/spec_graph.py do projeto: cópia do script com SDD_TOOL_VERSION trocada."""
    text = SCRIPT.read_text(encoding="utf-8")
    text = re.sub(r'SDD_TOOL_VERSION = "[^"]+"', f'SDD_TOOL_VERSION = "{version}"', text, count=1)
    target = root / "tools" / "sdd" / "spec_graph.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def after(out: str, header: str, text: str) -> bool:
    """`text` aparece depois de `header` na saída."""
    start = out.find(header)
    return start >= 0 and text in out[start + len(header):]


def line_with(out: str, text: str) -> str:
    return next((line for line in out.splitlines() if text in line), "")


class TempProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def outdated(self) -> Project:
        """Projeto do IT-01: tools/sdd em 2026.10.8 e sdd-config sem living_docs."""
        p = Project(self.tmp / "antigo")
        vendor_tool(p.root, OLD)
        return p

    def current(self) -> Project:
        """Projeto do IT-02: tools/sdd na versão da skill e sdd-config com todas as chaves do template."""
        p = Project(self.tmp / "atual")
        vendor_tool(p.root, VERSION)
        (p.root / "docs/specs/sdd-config.yml").write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
        return p


class ChangelogSinceTest(unittest.TestCase):
    def test_sections_between_versions_in_file_order(self):
        """SPEC-0013:UT-01"""
        changelog_since = fn("changelog_since")
        version_key = fn("version_key")
        self.assertEqual(version_key("2026.10.10"), (2026, 10, 10))
        self.assertGreater(version_key("2026.10.10"), version_key("2026.10.9"))
        sections = changelog_since(SAMPLE_CHANGELOG, "2026.10.8", "2026.10.10")
        self.assertEqual(len(sections), 2, sections)
        self.assertTrue(sections[0].startswith("## [2026.10.10] - 2026-10-26"), sections[0])
        self.assertIn("whats-new (SPEC-0013)", sections[0])
        self.assertTrue(sections[1].startswith("## [2026.10.9] - 2026-10-20"), sections[1])
        self.assertIn("caminho resolvido (SPEC-0012)", sections[1])
        joined = "\n".join(sections)
        for absent in ("[Unreleased]", "SPEC-0099", "[2026.10.8]", "modo privado", "Keep a Changelog"):
            self.assertNotIn(absent, joined)
        # numérica, não textual: "2026.10.10" < "2026.10.9" como texto
        only_new = changelog_since(SAMPLE_CHANGELOG, "2026.10.9", "2026.10.10")
        self.assertEqual([s.splitlines()[0] for s in only_new], ["## [2026.10.10] - 2026-10-26"])
        self.assertEqual(changelog_since(SAMPLE_CHANGELOG, "2026.10.10", "2026.10.10"), [])
        self.assertEqual(changelog_since(SAMPLE_CHANGELOG, None, "2026.10.10"), [])


class MissingConfigKeysTest(unittest.TestCase):
    def test_top_level_keys_missing_with_template_comment(self):
        """SPEC-0013:UT-02"""
        missing_config_keys = fn("missing_config_keys")
        config = {"base_branch": "main", "h2_policy": "per-wave"}
        self.assertEqual(missing_config_keys(SAMPLE_TEMPLATE, config),
                         [("living_docs", 'Documentos vivos: guia de jornadas e mapa do sistema. "" desliga um documento.')])
        for present in ({"journeys": "", "system_map": ""}, ""):
            self.assertEqual(missing_config_keys(SAMPLE_TEMPLATE, dict(config, living_docs=present)), [], present)
        parsed = sg.parse_yaml_subset('base_branch: main\nh2_policy: per-wave\nliving_docs:\n  journeys: ""\n')
        self.assertEqual(missing_config_keys(SAMPLE_TEMPLATE, parsed), [])
        keys = [k for k, _ in missing_config_keys(SAMPLE_TEMPLATE, {})]
        self.assertEqual(keys, ["base_branch", "living_docs", "h2_policy"])
        self.assertEqual(dict(missing_config_keys(SAMPLE_TEMPLATE, {}))["base_branch"], "")


class SkillChangelogTest(unittest.TestCase):
    def test_skill_changelog_is_grouped_by_version_newest_first(self):
        """SPEC-0013:UT-03"""
        self.assertTrue(CHANGELOG.exists(), f"{CHANGELOG} não existe")
        lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
        headers = [line for line in lines if line.startswith("## ")]
        self.assertTrue(headers, "CHANGELOG sem seções")
        versions = []
        for i, header in enumerate(headers):
            if header.strip() == "## [Unreleased]":
                self.assertEqual(i, 0, "[Unreleased] deve ser a primeira seção")
                continue
            m = VERSION_HEADER.match(header)
            self.assertIsNotNone(m, f"cabeçalho fora do formato '## [AAAA.MM.N] - AAAA-MM-DD': {header!r}")
            versions.append(m.group(1))
        self.assertIn(VERSION, versions, f"SDD_TOOL_VERSION {VERSION} sem seção no CHANGELOG da skill")
        self.assertEqual(versions, sorted(versions, key=vkey, reverse=True), "seções fora da ordem (mais nova primeiro)")
        self.assertEqual(len(versions), len(set(versions)), "versão repetida")
        first = next(i for i, line in enumerate(lines) if line.startswith("## "))
        loose = [line for line in lines[:first] if line.lstrip().startswith("- ")]
        self.assertEqual(loose, [], "entradas fora de qualquer seção de versão")


class InstructionsTest(unittest.TestCase):
    def test_instructions_mention_whats_new_and_sdd_version(self):
        """SPEC-0013:UT-04"""
        for path in (SKILL / "SKILL.md", REFS / "brownfield.md"):
            self.assertTrue("whats-new" in path.read_text(encoding="utf-8"), f"{path.name} não cita whats-new")
        self.assertTrue("sdd_version" in sg.parse_yaml_subset(TEMPLATE.read_text(encoding="utf-8")),
                        "template sem a chave sdd_version")
        self.assertTrue("skills/sdd-management/CHANGELOG.md" in (REPO / "README.md").read_text(encoding="utf-8"),
                        "README não cita skills/sdd-management/CHANGELOG.md")


class WhatsNewTest(TempProjectTest):
    def test_outdated_project_lists_news_new_keys_and_update_steps(self):
        """SPEC-0013:IT-01"""
        p = self.outdated()
        res = p.run("whats-new")
        out = res.stdout
        self.assertEqual(res.returncode, 0, out + res.stderr)
        self.assertIn(f"Projeto: {OLD} · skill: {VERSION}", out)
        self.assertIn(f"Novidades desde {OLD}:", out)
        expected = [v for v in changelog_versions() if vkey(OLD) < vkey(v) <= vkey(VERSION)]
        self.assertIn(VERSION, expected)
        positions = []
        for v in expected:
            self.assertTrue(after(out, f"Novidades desde {OLD}:", f"[{v}]"), f"seção {v} ausente:\n{out}")
            positions.append(out.find(f"[{v}]"))
        self.assertEqual(positions, sorted(positions), "seções fora da ordem do arquivo")
        for v in changelog_versions():
            if vkey(v) <= vkey(OLD):
                self.assertNotIn(f"[{v}]", out, f"seção antiga {v} listada")
        header = "Configurações novas (ausentes no seu sdd-config):"
        self.assertTrue(after(out, header, "- living_docs:"), out)
        self.assertIn("Documentos vivos", line_with(out, "- living_docs:"))
        self.assertNotIn("- base_branch:", out)
        self.assertTrue(after(out, "Para se atualizar:", "vendor --force"), out)
        self.assertTrue(after(out, "Para se atualizar:", "copie a chave do template references/sdd-config.template.yml"),
                        out)

    def test_up_to_date_project(self):
        """SPEC-0013:IT-02"""
        p = self.current()
        res = p.run("whats-new")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(f"Projeto em dia com a skill ({VERSION}).", res.stdout)
        for absent in ("Novidades desde", "Configurações novas", "vendor --force"):
            self.assertNotIn(absent, res.stdout)

    def test_status_line_only_when_there_is_news(self):
        """SPEC-0013:IT-03"""
        res = self.outdated().run("status")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        m = NEWS_LINE.search(res.stdout)
        self.assertIsNotNone(m, res.stdout)
        self.assertGreaterEqual(int(m.group(1)), 1)
        self.assertGreaterEqual(int(m.group(2)), 1)
        res = self.current().run("status")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertNotIn("Novidades da skill", res.stdout + res.stderr)

    def test_project_without_vendored_tool_uses_sdd_version_and_ack(self):
        """SPEC-0013:IT-04"""
        p = Project(self.tmp / "sem-vendor")
        config = p.root / "docs/specs/sdd-config.yml"
        res = p.run("whats-new")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("desconhecida", line_with(res.stdout, "Projeto:"))
        self.assertIn("Versão do projeto desconhecida — rode whats-new --ack depois de revisar", res.stdout)
        self.assertNotIn("Novidades desde", res.stdout)
        self.assertTrue(after(res.stdout, "Configurações novas (ausentes no seu sdd-config):", "- living_docs:"))
        self.assertTrue(after(res.stdout, "Para se atualizar:", "whats-new --ack"), res.stdout)

        config.write_text(config.read_text(encoding="utf-8") + f'sdd_version: "{OLD}"\n', encoding="utf-8")
        res = p.run("whats-new")
        self.assertIn(f"Projeto: {OLD} · skill: {VERSION}", res.stdout)
        self.assertIn(f"Novidades desde {OLD}:", res.stdout)

        res = p.run("whats-new", "--ack")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(f"sdd_version = {VERSION}", res.stdout)
        text = config.read_text(encoding="utf-8")
        self.assertEqual(sg.parse_yaml_subset(text).get("sdd_version"), VERSION)
        self.assertEqual(len(re.findall(r"^sdd_version\s*:", text, re.M)), 1, "linha sdd_version duplicada")
        self.assertIn("base_branch: main", text)
        res = p.run("whats-new")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(f"Projeto: {VERSION} · skill: {VERSION}", res.stdout)
        self.assertNotIn("Novidades desde", res.stdout)
        self.assertNotIn("desconhecida", res.stdout)

    def test_skill_without_changelog_still_lists_new_keys(self):
        """SPEC-0013:IT-05"""
        skill_copy = self.tmp / "skill"
        shutil.copytree(SKILL, skill_copy, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        (skill_copy / "CHANGELOG.md").unlink(missing_ok=True)
        p = self.outdated()
        res = subprocess.run([sys.executable, str(skill_copy / "scripts" / "spec_graph.py"), "whats-new"],
                             cwd=p.root, capture_output=True, text=True, check=False)
        out = res.stdout + res.stderr
        self.assertEqual(res.returncode, 0, out)
        self.assertIn("CHANGELOG da skill não encontrado", out)
        self.assertTrue(after(out, "Configurações novas (ausentes no seu sdd-config):", "- living_docs:"), out)


class PrivateWhatsNewTest(PrivateTestCase):
    def test_private_mode_reads_and_acks_in_spec_root(self):
        """SPEC-0013:CT-01"""
        self.e.init()
        with mock.patch.dict(os.environ, self.e.env, clear=True):
            config_path = sg.Project(self.e.repo).config_path
        self.assertEqual(config_path, self.e.spec_root.resolve() / "sdd-config.yml")
        text = re.sub(r"^sdd_version\s*:.*\n?", "", config_path.read_text(encoding="utf-8"), flags=re.M)
        config_path.write_text(text.rstrip("\n") + f'\nsdd_version: "{OLD}"\n', encoding="utf-8")
        git(self.e.spec_root, "add", "-A", env=self.e.env)
        git(self.e.spec_root, "commit", "-qm", "teste: sdd_version antiga", env=self.e.env)
        before = len(self.e.root_log())

        res = self.e.run("whats-new")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(f"Projeto: {OLD} · skill: {VERSION}", res.stdout)
        self.assertIn(f"Novidades desde {OLD}:", res.stdout)

        res = self.e.run("whats-new", "--ack")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(f"sdd_version = {VERSION}", res.stdout)
        self.assertEqual(sg.parse_yaml_subset(config_path.read_text(encoding="utf-8")).get("sdd_version"), VERSION)
        self.assertEqual(len(self.e.root_log()), before + 1, "ack não foi commitado no spec_root")
        self.assertEqual(git(self.e.spec_root, "status", "--porcelain", env=self.e.env), "")
        self.assertEqual(self.e.repo_status(), "", "o repositório do time mudou")
        self.assertFalse((self.e.repo / "docs").exists())

        res = self.e.run("whats-new")
        self.assertIn(f"Projeto: {VERSION} · skill: {VERSION}", res.stdout)


if __name__ == "__main__":
    unittest.main()
