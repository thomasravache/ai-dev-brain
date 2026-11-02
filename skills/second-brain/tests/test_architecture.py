"""Testes de arquitetura da second-brain (ADR-0007, SPEC-0017:UT-06).
Run: python3 -m unittest discover -s skills/second-brain/tests -p test_architecture.py

Cada regra é testada contra um exemplo que a viola e contra o código real de skills/second-brain/:
- scripts/brain.py é arquivo único (nenhum outro .py em scripts/) e importa só a biblioteca padrão;
- nenhum import de skills/sdd-management (spec_graph, architecture_rules) nem de tools/, nem caminho para elas;
- nenhuma biblioteca de rede (ADR-0008);
- processo externo só dentro da função run_processor (ADR-0009), que existe, roda o processo e nunca usa shell
  (SPEC-0022:UT-04);
- nenhum caminho pessoal absoluto em arquivos de skills/second-brain/ fora de tests/ (placeholders como
  /Users/<nome> são permitidos);
- remoção de arquivo (os.remove, os.unlink, Path.unlink, os.rmdir, Path.rmdir, shutil.rmtree) só em
  rotate_backups e na lista fechada de limpezas do que a própria chamada criou (ADR-0015, SPEC-0051:UT-07).
"""
import ast
import unittest

from brain_architecture_rules import (
    cross_skill_path_findings,
    import_findings,
    personal_path_findings,
    removal_findings,
    subprocess_findings,
)
from brain_support import SCRIPT, SKILL

ALLOWED_PROCESS_FUNCTIONS = ("run_processor",)
# ADR-0015: entrar nesta lista exige emenda do ADR (emenda v1 da SPEC-0051)
ALLOWED_REMOVAL_FUNCTIONS = ("rotate_backups", "write_export", "copy_to_files", "move_out_of_inbox")


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


class RemovalRulesTest(unittest.TestCase):
    def test_removal_outside_the_allowed_functions_is_reported(self):
        """SPEC-0051:UT-07"""
        source = (
            "import os\n"
            "import shutil\n"
            "from pathlib import Path\n"
            "def rotate_backups(folder, keep):\n"
            "    os.remove(folder / 'a.zip')\n"
            "    (folder / 'b.zip').unlink()\n"
            "def write_export(folder, files):\n"
            "    shutil.rmtree(folder, ignore_errors=True)\n"
            "def cmd_restore(args):\n"
            "    Path(args.note).unlink()\n"
            "    os.unlink(args.note)\n"
            "def tidy(folder):\n"
            "    folder.rmdir()\n"
            "    os.rmdir(folder)\n"
            "    shutil.rmtree(folder)\n"
            "    names = ['a']\n"
            "    names.remove('a')\n"
            "from os import remove\n"
        )
        allowed = ("rotate_backups", "write_export")
        findings = removal_findings(source, "scripts/brain.py", allowed)
        self.assertEqual(len(findings), 6, report(findings))
        self.assertIn("scripts/brain.py:10", findings[0])
        self.assertIn("cmd_restore", findings[0])
        self.assertIn("scripts/brain.py:11", findings[1])
        self.assertIn("os.unlink", findings[1])
        self.assertIn("scripts/brain.py:13", findings[2])
        self.assertIn("tidy", findings[2])
        self.assertIn("scripts/brain.py:14", findings[3])
        self.assertIn("os.rmdir", findings[3])
        self.assertIn("scripts/brain.py:15", findings[4])
        self.assertIn("shutil.rmtree", findings[4])
        self.assertIn("scripts/brain.py:18", findings[5])
        self.assertIn("remove", findings[5])

    def test_brain_removes_files_only_in_rotate_backups_and_the_closed_cleanup_list(self):
        """SPEC-0051:UT-07"""
        findings = removal_findings(script_source(), "scripts/brain.py", ALLOWED_REMOVAL_FUNCTIONS)
        self.assertEqual(findings, [], report(findings))

    def test_rotate_backups_exists_and_is_where_backups_are_removed(self):
        """SPEC-0051:UT-07"""
        tree = ast.parse(script_source())
        functions = [node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef) and node.name == "rotate_backups"]
        self.assertEqual(len(functions), 1, "brain.py precisa de uma função rotate_backups (ADR-0015, SPEC-0051)")
        inside = removal_findings(ast.unparse(functions[0]), "scripts/brain.py", allowed=())
        self.assertTrue(inside, "rotate_backups precisa ser onde os backups antigos são removidos (ADR-0015)")


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
