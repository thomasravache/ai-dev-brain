"""Testes de arquitetura da second-brain (ADR-0007, SPEC-0017:UT-06).
Run: python3 -m unittest discover -s skills/second-brain/tests -p test_architecture.py

Cada regra é testada contra um exemplo que a viola e contra o código real de skills/second-brain/:
- scripts/brain.py é arquivo único (nenhum outro .py em scripts/) e importa só a biblioteca padrão;
- nenhum import de skills/sdd-management (spec_graph, architecture_rules) nem de tools/, nem caminho para elas;
- nenhuma biblioteca de rede (ADR-0008);
- processo externo só dentro da função run_processor (ADR-0009), que existe, roda o processo e nunca usa shell
  (SPEC-0022:UT-04);
- nenhum caminho pessoal absoluto em arquivos de skills/second-brain/ fora de tests/ (placeholders como
  /Users/<nome> são permitidos).
"""
import ast
import unittest

from brain_architecture_rules import (
    cross_skill_path_findings,
    import_findings,
    personal_path_findings,
    subprocess_findings,
)
from brain_support import SCRIPT, SKILL

ALLOWED_PROCESS_FUNCTIONS = ("run_processor",)


def report(findings):
    return "\n".join(findings)


def script_source():
    if not SCRIPT.exists():
        raise AssertionError(f"{SCRIPT} não existe (SPEC-0017)")
    return SCRIPT.read_text(encoding="utf-8")


class ImportRulesTest(unittest.TestCase):
    def test_third_party_local_cross_skill_and_network_imports_are_reported(self):
        """SPEC-0017:UT-06"""
        source = (
            "import os\n"
            "import yaml\n"
            "from helpers import x\n"
            "import spec_graph\n"
            "from tools.sdd import spec_graph as sg\n"
            "import urllib.request\n"
            "from urllib.parse import quote\n"
            "from . import y\n"
        )
        findings = import_findings(source, "scripts/brain.py", local_modules=["helpers"])
        self.assertEqual(len(findings), 6, report(findings))
        self.assertIn("scripts/brain.py:2", findings[0])
        self.assertIn("'yaml'", findings[0])
        self.assertIn("scripts/brain.py:3", findings[1])
        self.assertIn("arquivo único", findings[1])
        self.assertIn("scripts/brain.py:4", findings[2])
        self.assertIn("entre skills", findings[2])
        self.assertIn("scripts/brain.py:5", findings[3])
        self.assertIn("entre skills", findings[3])
        self.assertIn("scripts/brain.py:6", findings[4])
        self.assertIn("rede", findings[4])
        self.assertIn("scripts/brain.py:8", findings[5])

    def test_paths_to_the_other_skill_are_reported(self):
        """SPEC-0017:UT-06"""
        source = 'import sys\nsys.path.insert(0, "../sdd-management/scripts")\nX = "tools/sdd/spec_graph.py"\n'
        findings = cross_skill_path_findings(source, "scripts/brain.py")
        self.assertEqual(len(findings), 2, report(findings))
        self.assertEqual(cross_skill_path_findings('LOG = "log.md"\n', "scripts/brain.py"), [])

    def test_brain_is_a_single_file_using_only_the_standard_library(self):
        """SPEC-0017:UT-06"""
        source = script_source()
        others = sorted(p.name for p in SCRIPT.parent.glob("*.py") if p != SCRIPT)
        self.assertEqual(others, [], "scripts/ deve ter só brain.py (arquivo único)")
        findings = import_findings(source, "scripts/brain.py")
        findings += cross_skill_path_findings(source, "scripts/brain.py")
        self.assertEqual(findings, [], report(findings))


class ProcessRulesTest(unittest.TestCase):
    def test_process_outside_run_processor_is_reported(self):
        """SPEC-0017:UT-06"""
        source = (
            "import os\n"
            "import subprocess\n"
            "def run_processor(argv):\n"
            "    return subprocess.run(argv)\n"
            "def doctor():\n"
            "    subprocess.run(['pdftotext', '-v'])\n"
            "os.system('ls')\n"
        )
        findings = subprocess_findings(source, "scripts/brain.py", ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual(len(findings), 2, report(findings))
        self.assertIn("scripts/brain.py:6", findings[0])
        self.assertIn("doctor", findings[0])
        self.assertIn("scripts/brain.py:7", findings[1])

    def test_brain_runs_processes_only_in_run_processor(self):
        """SPEC-0017:UT-06 SPEC-0022:UT-04"""
        findings = subprocess_findings(script_source(), "scripts/brain.py", ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual(findings, [], report(findings))

    def test_run_processor_is_the_one_place_that_runs_a_process_and_never_with_shell(self):
        """SPEC-0022:UT-04"""
        tree = ast.parse(script_source())
        functions = [node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef) and node.name == "run_processor"]
        self.assertEqual(len(functions), 1, "brain.py precisa de uma função run_processor (SPEC-0022)")
        calls = [node for node in ast.walk(functions[0]) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                 and node.func.value.id == "subprocess"]
        self.assertTrue(calls, "run_processor precisa rodar o processo com subprocess (SPEC-0022)")
        shell = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.keyword) and node.arg == "shell"
                 and not (isinstance(node.value, ast.Constant) and node.value.value is False)]
        self.assertEqual(shell, [], f"shell= em brain.py (linhas {shell}): processos rodam sem shell (ADR-0009)")


class PersonalPathRulesTest(unittest.TestCase):
    def test_personal_absolute_paths_are_reported_and_placeholders_are_not(self):
        """SPEC-0017:UT-06"""
        text = (
            "vault: /Users/ana/Drive/Vault\n"
            "files: C:\\Users\\ana\\OneDrive\\files\n"
            "linux: /home/ana/vault\n"
            "ok: /Users/<nome>/Library/CloudStorage\n"
            "ok: ~/.config/second-brain/config.yml\n"
        )
        findings = personal_path_findings(text, "references/config.md")
        self.assertEqual(len(findings), 3, report(findings))
        self.assertIn("references/config.md:1", findings[0])
        self.assertIn("references/config.md:2", findings[1])
        self.assertIn("references/config.md:3", findings[2])

    def test_skill_files_have_no_personal_absolute_path(self):
        """SPEC-0017:UT-06"""
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
