"""Testes de arquitetura da org-atlas (ADR-0010, SPEC-0032:UT-05).
Run: python3 -m unittest discover -s skills/org-atlas/tests -p test_architecture.py

Cada regra é testada contra um exemplo que a viola e contra o código real de skills/org-atlas/:
- scripts/atlas.py é arquivo único (nenhum outro .py em scripts/) e importa só a biblioteca padrão;
- nenhum import de outra skill (sdd-management, second-brain) nem de tools/, nem caminho para elas; e nenhum
  código de outra skill ou de tools/ importa atlas (o uso é só pela CLI);
- processo externo só dentro da função run_collector, sem shell;
- os coletores de assets/collectors/*.py, quando a pasta existe, importam só a biblioteca padrão e nada de
  outra skill;
- nenhum caminho pessoal absoluto em arquivos de skills/org-atlas/ fora de tests/ (placeholders como
  /Users/<nome> são permitidos).
"""
import unittest

from architecture_rules import (
    cross_skill_path_findings,
    import_findings,
    imports_of,
    personal_path_findings,
    shell_findings,
    subprocess_findings,
)
from helpers import SCRIPT, SKILL

ALLOWED_PROCESS_FUNCTIONS = ("run_collector",)
REPO = SKILL.parent.parent
COLLECTORS = SKILL / "assets" / "collectors"


def report(findings):
    return "\n".join(findings)


def script_source():
    if not SCRIPT.exists():
        raise AssertionError(f"{SCRIPT} não existe (SPEC-0032)")
    return SCRIPT.read_text(encoding="utf-8")


class ImportRulesTest(unittest.TestCase):
    def test_third_party_local_and_cross_skill_imports_are_reported(self):
        """SPEC-0032:UT-05"""
        source = (
            "import os\n"
            "import yaml\n"
            "from helpers import x\n"
            "import spec_graph\n"
            "from tools.sdd import spec_graph as sg\n"
            "import brain\n"
            "from urllib.parse import quote\n"
            "from . import y\n"
        )
        findings = import_findings(source, "scripts/atlas.py", local_modules=["helpers"])
        self.assertEqual(len(findings), 6, report(findings))
        self.assertIn("scripts/atlas.py:2", findings[0])
        self.assertIn("'yaml'", findings[0])
        self.assertIn("scripts/atlas.py:3", findings[1])
        self.assertIn("arquivo único", findings[1])
        self.assertIn("scripts/atlas.py:4", findings[2])
        self.assertIn("entre skills", findings[2])
        self.assertIn("scripts/atlas.py:5", findings[3])
        self.assertIn("entre skills", findings[3])
        self.assertIn("scripts/atlas.py:6", findings[4])
        self.assertIn("entre skills", findings[4])
        self.assertIn("scripts/atlas.py:8", findings[5])

    def test_paths_to_other_skills_and_tools_are_reported(self):
        """SPEC-0032:UT-05"""
        source = ('import sys\nsys.path.insert(0, "../sdd-management/scripts")\n'
                  'sys.path.insert(0, "../second-brain/scripts")\nX = "tools/sdd/spec_graph.py"\n')
        findings = cross_skill_path_findings(source, "scripts/atlas.py")
        self.assertEqual(len(findings), 3, report(findings))
        self.assertEqual(cross_skill_path_findings('CONFIG = "atlas-config.yml"\n', "scripts/atlas.py"), [])

    def test_atlas_is_a_single_file_using_only_the_standard_library(self):
        """SPEC-0032:UT-05"""
        source = script_source()
        others = sorted(p.name for p in SCRIPT.parent.glob("*.py") if p != SCRIPT)
        self.assertEqual(others, [], "scripts/ deve ter só atlas.py (arquivo único)")
        findings = import_findings(source, "scripts/atlas.py")
        findings += cross_skill_path_findings(source, "scripts/atlas.py")
        self.assertEqual(findings, [], report(findings))

    def test_no_other_skill_or_tools_imports_atlas(self):
        """SPEC-0032:UT-05"""
        self.assertEqual(imports_of("import atlas\nfrom atlas import load_config\nimport atlases\n", ("atlas",)),
                         [1, 2])
        offenders = []
        sources = [p for p in sorted((REPO / "skills").glob("*/scripts/*.py")) if SKILL not in p.parents]
        sources += sorted((REPO / "tools").rglob("*.py")) if (REPO / "tools").is_dir() else []
        for path in sources:
            lines = imports_of(path.read_text(encoding="utf-8"), ("atlas",))
            offenders += [f"{path.relative_to(REPO).as_posix()}:{line}" for line in lines]
        self.assertEqual(offenders, [], "outra skill ou tools/ importa atlas (o uso é só pela CLI):\n"
                         + report(offenders))


class CollectorRulesTest(unittest.TestCase):
    def test_collectors_use_only_the_standard_library(self):
        """SPEC-0032:UT-05"""
        bad = import_findings("import json\nimport requests\nimport brain\n", "assets/collectors/github.py")
        self.assertEqual(len(bad), 2, report(bad))
        if not COLLECTORS.is_dir():
            return  # a pasta chega com a SPEC-0033/0034; a regra vale assim que existir
        findings = []
        for path in sorted(COLLECTORS.glob("*.py")):
            rel = path.relative_to(SKILL).as_posix()
            source = path.read_text(encoding="utf-8")
            findings += import_findings(source, rel) + cross_skill_path_findings(source, rel)
        self.assertEqual(findings, [], report(findings))


class ProcessRulesTest(unittest.TestCase):
    def test_process_outside_run_collector_is_reported(self):
        """SPEC-0032:UT-05"""
        source = (
            "import os\n"
            "import subprocess\n"
            "def run_collector(argv):\n"
            "    return subprocess.run(argv)\n"
            "def doctor():\n"
            "    subprocess.run(['gh', '--version'])\n"
            "os.system('ls')\n"
        )
        findings = subprocess_findings(source, "scripts/atlas.py", ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual(len(findings), 2, report(findings))
        self.assertIn("scripts/atlas.py:6", findings[0])
        self.assertIn("doctor", findings[0])
        self.assertIn("scripts/atlas.py:7", findings[1])

    def test_shell_is_reported(self):
        """SPEC-0032:UT-05"""
        source = ("import subprocess\n"
                  "def run_collector(argv):\n"
                  "    subprocess.run(argv, shell=False)\n"
                  "    subprocess.run(' '.join(argv), shell=True)\n")
        findings = shell_findings(source, "scripts/atlas.py")
        self.assertEqual(len(findings), 1, report(findings))
        self.assertIn("scripts/atlas.py:4", findings[0])

    def test_atlas_runs_processes_only_in_run_collector_and_never_with_shell(self):
        """SPEC-0032:UT-05"""
        source = script_source()
        findings = subprocess_findings(source, "scripts/atlas.py", ALLOWED_PROCESS_FUNCTIONS)
        findings += shell_findings(source, "scripts/atlas.py")
        self.assertEqual(findings, [], report(findings))


class PersonalPathRulesTest(unittest.TestCase):
    def test_personal_absolute_paths_are_reported_and_placeholders_are_not(self):
        """SPEC-0032:UT-05"""
        text = (
            "atlas: /Users/ana/work/acme-atlas\n"
            "atlas: C:\\Users\\ana\\work\\acme-atlas\n"
            "linux: /home/ana/acme-atlas\n"
            "ok: /Users/<nome>/work/acme-atlas\n"
            "ok: ~/.config/org-atlas/config.yml\n"
        )
        findings = personal_path_findings(text, "references/config.md")
        self.assertEqual(len(findings), 3, report(findings))
        self.assertIn("references/config.md:1", findings[0])
        self.assertIn("references/config.md:2", findings[1])
        self.assertIn("references/config.md:3", findings[2])

    def test_skill_files_have_no_personal_absolute_path(self):
        """SPEC-0032:UT-05"""
        script_source()  # a skill precisa existir para a varredura valer
        findings = []
        for path in sorted(SKILL.rglob("*")):
            rel = path.relative_to(SKILL)
            if not path.is_file() or rel.parts[0] == "tests" or "__pycache__" in rel.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            findings += personal_path_findings(text, rel.as_posix())
        self.assertEqual(findings, [], report(findings))


if __name__ == "__main__":
    unittest.main()
