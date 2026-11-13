"""Testes de arquitetura do servidor MCP (ADR-0017, SPEC-0054:UT-07).
Run: python3 -m unittest discover -s mcp/tests -p test_architecture.py

Cada regra é testada contra um exemplo que a viola e contra o código real de mcp/fermion_mcp.py:
- arquivo único: mcp/ tem só fermion_mcp.py como código (fora de tests/);
- só biblioteca padrão; nenhum import de código das skills nem de tools/, nem carregamento dinâmico de código;
- nenhum shell;
- processo externo só na função executora run_cli, e só para a CLI do atlas: nenhum texto aponta para a CLI de
  outra skill, e cada tool, rodada de verdade com subprocess.run substituído, abre só
  `<python> <raiz>/skills/boson-atlas/scripts/atlas.py ...`.
"""
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from architecture_rules import (
    dynamic_code_findings,
    import_findings,
    other_cli_findings,
    process_findings,
    shell_findings,
)
from helpers import ATLAS_CLI, MCP, SERVER, TOOLS, attr, call, server_module

ALLOWED_PROCESS_FUNCTIONS = ("run_cli",)
NAME = "mcp/fermion_mcp.py"
VALID_ARGUMENTS = {
    "atlas_config": {},
    "atlas_doctor": {},
    "atlas_context": {"query": "api", "hops": 1, "limit": 3, "max_chars": 1000},
    "atlas_lint": {"only": ["stale"]},
    "atlas_curate_list": {"status": "confirmed"},
}


def report(findings):
    return "\n".join(findings)


def server_source():
    if not SERVER.exists():
        raise AssertionError(f"{SERVER} não existe (SPEC-0054)")
    return SERVER.read_text(encoding="utf-8")


class ImportRulesTest(unittest.TestCase):
    def test_third_party_relative_and_skill_imports_are_reported(self):
        """SPEC-0054:UT-07"""
        source = (
            "import json\n"
            "import mcp\n"
            "import atlas\n"
            "from tools.sdd import spec_graph\n"
            "from . import x\n"
            "import brain\n"
            "from subprocess import PIPE\n"
        )
        findings = import_findings(source, NAME)
        self.assertEqual(len(findings), 5, report(findings))
        self.assertIn(f"{NAME}:2", findings[0])
        self.assertIn("biblioteca padrão", findings[0])
        for finding, line in zip(findings[1:], (3, 4, 5, 6)):
            self.assertIn(f"{NAME}:{line}", finding)
            self.assertIn("skills/", finding)

    def test_dynamic_loading_of_code_is_reported(self):
        """SPEC-0054:UT-07"""
        source = (
            "import importlib, importlib.util, runpy, sys\n"
            "sys.path.insert(0, 'skills/boson-atlas/scripts')\n"
            "atlas = importlib.import_module('atlas')\n"
            "spec = importlib.util.spec_from_file_location('atlas', 'x.py')\n"
            "runpy.run_path('skills/boson-atlas/scripts/atlas.py')\n"
            "exec(open('x.py').read())\n"
            "__import__('atlas')\n"
            "sys.path = ['x'] + sys.path\n"
            "from importlib import import_module\n"
            "import re\n"
            "pattern = re.compile('x')\n"
        )
        findings = dynamic_code_findings(source, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings],
                         [f"{NAME}:{n}" for n in (2, 3, 4, 5, 6, 7, 8, 9)], report(findings))

    def test_server_uses_only_the_standard_library_and_loads_no_skill_code(self):
        """SPEC-0054:UT-07"""
        source = server_source()
        findings = import_findings(source, NAME) + dynamic_code_findings(source, NAME)
        self.assertEqual(findings, [], report(findings))

    def test_server_is_a_single_file(self):
        """SPEC-0054:UT-07"""
        server_source()
        others = sorted(p.relative_to(MCP).as_posix() for p in MCP.rglob("*.py")
                        if p != SERVER and "tests" not in p.relative_to(MCP).parts)
        self.assertEqual(others, [], "mcp/ deve ter só fermion_mcp.py como código (arquivo único)")


class ShellRulesTest(unittest.TestCase):
    def test_shell_is_reported(self):
        """SPEC-0054:UT-07"""
        source = (
            "import os, subprocess\n"
            "def run_cli(argv, timeout):\n"
            "    subprocess.run(argv, shell=False, check=False)\n"
            "    subprocess.run(' '.join(argv), shell=True, check=False)\n"
            "    os.system('ls')\n"
            "    subprocess.getoutput('ls')\n"
            "    flag = True\n"
            "    subprocess.run(argv, shell=flag, check=False)\n"
        )
        findings = shell_findings(source, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (4, 5, 6, 8)],
                         report(findings))

    def test_server_never_uses_a_shell(self):
        """SPEC-0054:UT-07"""
        findings = shell_findings(server_source(), NAME)
        self.assertEqual(findings, [], report(findings))


class ProcessRulesTest(unittest.TestCase):
    def test_process_outside_run_cli_is_reported(self):
        """SPEC-0054:UT-07"""
        source = (
            "import os\n"
            "import subprocess\n"
            "from subprocess import run\n"
            "def run_cli(argv, timeout):\n"
            "    return subprocess.run(argv, timeout=timeout, check=False)\n"
            "def tools_call(name):\n"
            "    subprocess.Popen(['gh', 'api'])\n"
            "os.execv('/bin/ls', ['ls'])\n"
        )
        findings = process_findings(source, NAME, ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (3, 7, 8)],
                         report(findings))
        self.assertIn("tools_call", findings[1])

    def test_other_skill_clis_are_reported(self):
        """SPEC-0054:UT-07"""
        source = (
            "ATLAS = 'skills/boson-atlas/scripts/atlas.py'\n"
            "SDD = 'skills/gluon-spec/scripts/spec_graph.py'\n"
            "BRAIN = 'skills/photon-brain/scripts/brain.py'\n"
            "OLD = 'tools/sdd/spec_graph.py'\n"
            "METHODS = ('tools/list', 'tools/call')\n"
        )
        findings = other_cli_findings(source, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (2, 3, 4)],
                         report(findings))

    def test_server_runs_processes_only_in_run_cli_and_only_for_the_atlas(self):
        """SPEC-0054:UT-07"""
        source = server_source()
        findings = process_findings(source, NAME, ALLOWED_PROCESS_FUNCTIONS) + other_cli_findings(source, NAME)
        self.assertEqual(findings, [], report(findings))

    def test_every_tool_opens_only_the_atlas_cli(self):
        """SPEC-0054:UT-07 (comportamento: cada tool, com subprocess.run substituído)"""
        module = server_module()
        done = subprocess.CompletedProcess(["x"], 0, stdout="{}", stderr="")
        with mock.patch.object(module.subprocess, "run", return_value=done) as run, \
                mock.patch.object(module.subprocess, "Popen", side_effect=AssertionError("Popen não é usado")):
            server = attr("Server")()
            for index, name in enumerate(TOOLS, 1):
                response = server.handle(call(name, VALID_ARGUMENTS[name], id=index))
                self.assertIn("result", response or {}, response)
        self.assertEqual(run.call_count, len(TOOLS))
        for args, kwargs in run.call_args_list:
            argv = args[0] if args else kwargs.get("args")
            self.assertIsInstance(argv, list)
            self.assertTrue(Path(argv[0]).name.startswith("python"), argv)
            self.assertEqual(Path(argv[1]).resolve(), ATLAS_CLI.resolve(), argv)
            self.assertFalse(kwargs.get("shell", False))


if __name__ == "__main__":
    unittest.main()
