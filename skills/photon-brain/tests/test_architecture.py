"""Testes de arquitetura da photon-brain (ADR-0007, SPEC-0017:UT-06).
Run: python3 -m unittest discover -s skills/photon-brain/tests -p test_architecture.py

Cada regra é testada contra um exemplo que a viola e contra o código real de skills/photon-brain/:
- scripts/brain.py é arquivo único (nenhum outro .py em scripts/) e importa só a biblioteca padrão;
- nenhum import de skills/gluon-spec (spec_graph, architecture_rules) nem de tools/, nem caminho para elas;
- nenhuma biblioteca de rede (ADR-0008);
- processo externo só dentro da função run_processor (ADR-0009), que existe, roda o processo e nunca usa shell
  (SPEC-0022:UT-04), inclusive por import de nome ou alias (from subprocess import run, import subprocess as sp,
  from os import system) — SPEC-0062:UT-01;
- nenhum caminho pessoal absoluto em arquivos de skills/photon-brain/ fora de tests/ (placeholders como
  /Users/<nome> são permitidos);
- remoção de arquivo (os.remove, os.unlink, Path.unlink, os.rmdir, Path.rmdir, shutil.rmtree) só em
  rotate_backups e na lista fechada de limpezas do que a própria chamada criou (ADR-0015, SPEC-0051:UT-07);
- EMBEDDED_SHARED_DEFAULTS (os padrões da configuração embutidos no brain.py, para a cópia sem assets/) é igual ao
  assets/brain-config.yml lido pelo parse_yaml do script; uma chave mudada só num dos dois lados reprova, conferido
  numa cópia temporária da skill (SPEC-0111:UT-02).
"""
import ast
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from brain_architecture_rules import (
    cross_skill_path_findings,
    import_findings,
    personal_path_findings,
    removal_findings,
    shared_defaults_findings,
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
        source = ('import sys\nsys.path.insert(0, "../sdd-management/scripts")\nX = "tools/sdd/spec_graph.py"\n'
                  'sys.path.insert(0, "../gluon-spec/scripts")\n')
        findings = cross_skill_path_findings(source, "scripts/brain.py")
        self.assertEqual(len(findings), 3, report(findings))
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

    def test_process_imported_by_name_or_alias_outside_run_processor_is_reported(self):
        """SPEC-0062:UT-01"""
        source = (
            "from subprocess import run\n"
            "import subprocess as sp\n"
            "from os import system\n"
            "import os\n"
            "from os import path\n"
            "def run_processor(argv):\n"
            "    sp.Popen(argv)\n"
            "    return run(argv)\n"
            "def doctor():\n"
            "    run(['pdftotext', '-v'])\n"
            "    sp.check_output(['ls'])\n"
            "    system('ls')\n"
            "    return path.exists('x'), os.getcwd()\n"
        )
        findings = subprocess_findings(source, "scripts/brain.py", ALLOWED_PROCESS_FUNCTIONS)
        lines = [int(f.split(":")[1].split(" ")[0]) for f in findings]
        self.assertEqual(lines, [1, 2, 3, 10, 11, 12], report(findings))
        for finding, line in zip(findings, (1, 2, 3, 10, 11, 12)):
            self.assertIn(f"scripts/brain.py:{line} ", finding)
            self.assertIn("processos externos só em run_processor", finding)
        for finding in findings[3:]:
            self.assertIn("doctor", finding)

    def test_process_imported_by_name_or_alias_inside_run_processor_is_not_reported(self):
        """SPEC-0062:UT-01"""
        source = (
            "import os\n"
            "from os import path\n"
            "def run_processor(argv):\n"
            "    from subprocess import run\n"
            "    import subprocess as sp\n"
            "    from os import system\n"
            "    sp.Popen(argv)\n"
            "    system('ls')\n"
            "    return run(argv), path.exists('x'), os.getcwd()\n"
        )
        findings = subprocess_findings(source, "scripts/brain.py", ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual(findings, [], report(findings))

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

    def test_aliases_and_references_to_removal_functions_are_reported(self):
        """SPEC-0051:UT-07"""
        source = (
            "import os as o\n"
            "import shutil as s\n"
            "import os\n"
            "from pathlib import Path\n"
            "def rotate_backups(folder, keep):\n"
            "    o.remove(folder / 'a.zip')\n"
            "def sneaky(p):\n"
            "    o.remove(p)\n"
            "    rm = os.remove\n"
            "    u = Path.unlink\n"
            "    getattr(os, 'remove')(p)\n"
            "    s.rmtree(p)\n"
            "    getattr(o, 'rmdir')(p)\n"
            "    getattr(p, 'unlink')()\n"
            "    names = ['a']\n"
            "    names.remove('a')\n"
            "    getattr(names, 'remove')('a')\n"
            "    return rm, u\n"
        )
        findings = removal_findings(source, "scripts/brain.py", ("rotate_backups",))
        lines = [int(f.split(":")[1].split(" ")[0]) for f in findings]
        self.assertEqual(lines, [8, 9, 10, 11, 12, 13, 14], report(findings))
        self.assertTrue(all("sneaky" in f for f in findings), report(findings))

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
            "ok: ~/.config/photon-brain/config.yml\n"
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


# SPEC-0111:UT-02 — mudança só do lado da constante, acrescentada ao fim da cópia do script: vale para a constante
# em texto YAML ou já em dicionário (a última atribuição é a que o módulo carregado tem)
EMBEDDED_CHANGE = """

def _spec0111_change(value):
    import copy as _copy
    import re as _re
    if isinstance(value, str):
        return _re.sub(r"(?m)^(\\s+inbox\\s*:\\s*)inbox\\b", r"\\1entrada", value, count=1)
    value = _copy.deepcopy(value)
    value["layout"]["inbox"] = "entrada"
    return value


EMBEDDED_SHARED_DEFAULTS = _spec0111_change(EMBEDDED_SHARED_DEFAULTS)
"""


class SharedDefaultsRulesTest(unittest.TestCase):
    """SPEC-0111:UT-02 — padrões embutidos iguais a assets/brain-config.yml."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.copy = self.root / "photon-brain"
        shutil.copytree(SKILL, self.copy, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        self.script = self.copy / "scripts" / "brain.py"
        self.config = self.copy / "assets" / "brain-config.yml"

    def findings(self):
        return shared_defaults_findings(self.script, self.config)

    def test_brain_embedded_defaults_match_assets_brain_config(self):
        """SPEC-0111:UT-02"""
        # SPEC-0111:UT-02
        script_source()  # a skill precisa existir para a regra valer
        findings = shared_defaults_findings(SCRIPT, SKILL / "assets" / "brain-config.yml")
        self.assertEqual(findings, [], report(findings))

    def test_rule_passes_on_an_unchanged_copy_of_the_skill(self):
        """SPEC-0111:UT-02"""
        # SPEC-0111:UT-02
        self.assertEqual(self.findings(), [], report(self.findings()))

    def test_key_changed_only_in_assets_brain_config_is_reported(self):
        """SPEC-0111:UT-02"""
        # SPEC-0111:UT-02
        text = self.config.read_text(encoding="utf-8")
        changed = re.sub(r"(?m)^inbox_stale_days:\s*7\b", "inbox_stale_days: 9", text, count=1)
        self.assertNotEqual(changed, text, "assets/brain-config.yml precisa ter inbox_stale_days: 7")
        self.config.write_text(changed, encoding="utf-8")
        findings = self.findings()
        self.assertEqual(len(findings), 1, report(findings))
        self.assertIn("inbox_stale_days", findings[0])
        self.assertIn("scripts/brain.py:", findings[0])
        self.assertIn("EMBEDDED_SHARED_DEFAULTS", findings[0])

    def test_key_changed_only_in_the_embedded_constant_is_reported(self):
        """SPEC-0111:UT-02"""
        # SPEC-0111:UT-02
        with self.script.open("a", encoding="utf-8") as script:
            script.write(EMBEDDED_CHANGE)
        findings = self.findings()
        self.assertEqual(len(findings), 1, report(findings))
        self.assertIn("layout.inbox", findings[0])
        self.assertIn("EMBEDDED_SHARED_DEFAULTS", findings[0])

    def test_key_only_in_one_side_is_reported(self):
        """SPEC-0111:UT-02"""
        # SPEC-0111:UT-02
        text = self.config.read_text(encoding="utf-8")
        self.config.write_text(text + "spec0111_extra: 1\n", encoding="utf-8")
        findings = self.findings()
        self.assertEqual(len(findings), 1, report(findings))
        self.assertIn("spec0111_extra", findings[0])

    def test_rule_reports_a_script_without_the_constant(self):
        """SPEC-0111:UT-02 — sem a constante a regra reprova, nunca passa por não ter o que comparar."""
        # SPEC-0111:UT-02
        script = self.root / "sem-constante.py"
        script.write_text("def parse_yaml(text):\n    return {}\n", encoding="utf-8")
        findings = shared_defaults_findings(script, self.config)
        self.assertEqual(len(findings), 1, report(findings))
        self.assertIn("EMBEDDED_SHARED_DEFAULTS não existe", findings[0])


if __name__ == "__main__":
    unittest.main()
