"""Testes de arquitetura da skill (ADR-0001). Run: python3 -m unittest discover -s tests -p test_architecture.py

Cada regra é testada contra um exemplo que a viola e contra o código real (guarda).
"""
import unittest
from pathlib import Path

from architecture_rules import (
    import_findings,
    subprocess_findings,
    vendor_copy_findings,
)

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "spec_graph.py"
SKILLS_ROOT = SKILL.parent
# Únicas funções que podem abrir processos: git e o comando que o projeto declara no sdd-config (gate --run).
ALLOWED_PROCESS_FUNCTIONS = ("run_git", "run_shell")


def report(findings):
    return "\n".join(findings)


class ImportRulesTest(unittest.TestCase):
    def test_third_party_and_local_imports_are_reported(self):
        """SPEC-0001:UT-01"""
        source = "import os\nimport yaml\nfrom helpers import x\n"
        findings = import_findings(source, "scripts/spec_graph.py", local_modules=["helpers"])
        self.assertEqual(len(findings), 2, report(findings))
        self.assertIn("scripts/spec_graph.py:2", findings[0])
        self.assertIn("'yaml'", findings[0])
        self.assertIn("scripts/spec_graph.py:3", findings[1])
        self.assertIn("'helpers'", findings[1])
        self.assertIn("arquivo único", findings[1])

    def test_script_imports_only_standard_library(self):
        """SPEC-0001:UT-02 (guarda)"""
        local = [p.stem for p in SCRIPT.parent.glob("*.py") if p != SCRIPT]
        findings = import_findings(SCRIPT.read_text(encoding="utf-8"), "scripts/spec_graph.py", local_modules=local)
        self.assertEqual(findings, [], report(findings))


class ProcessRulesTest(unittest.TestCase):
    def test_process_outside_allowed_functions_is_reported(self):
        """SPEC-0001:UT-03"""
        source = (
            "import subprocess\n"
            "def run_git(root, *args):\n"
            "    return subprocess.run(['git', *args])\n"
            "def open_pr():\n"
            "    subprocess.run(['gh', 'pr', 'list'])\n"
        )
        findings = subprocess_findings(source, "scripts/spec_graph.py", ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual(len(findings), 1, report(findings))
        self.assertIn("scripts/spec_graph.py:5", findings[0])
        self.assertIn("open_pr", findings[0])

    def test_script_runs_only_git_and_configured_commands(self):
        """SPEC-0001:UT-04 (guarda)"""
        findings = subprocess_findings(SCRIPT.read_text(encoding="utf-8"), "scripts/spec_graph.py",
                                       ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual(findings, [], report(findings))


class VendorCopyRulesTest(unittest.TestCase):
    def test_loading_the_vendored_copy_is_reported_and_citing_its_path_is_not(self):
        """SPEC-0001:UT-05"""
        source = (
            "import sys\n"
            "from tools.sdd import spec_graph\n"
            "sys.path.insert(0, \"tools/sdd\")\n"
        )
        findings = vendor_copy_findings(source, "tests/x.py")
        self.assertEqual(len(findings), 2, report(findings))
        self.assertIn("tests/x.py:2", findings[0])
        self.assertIn("tests/x.py:3", findings[1])
        self.assertEqual(vendor_copy_findings('VENDORED_TOOL = "tools/sdd/spec_graph.py"\n', "s.py"), [])

    def test_skills_never_load_the_vendored_copy(self):
        """SPEC-0001:UT-06 (guarda)"""
        findings = []
        for path in sorted(SKILLS_ROOT.rglob("*.py")):
            rel = path.relative_to(SKILLS_ROOT.parent).as_posix()
            findings += vendor_copy_findings(path.read_text(encoding="utf-8"), rel)
        self.assertEqual(findings, [], report(findings))


if __name__ == "__main__":
    unittest.main()
