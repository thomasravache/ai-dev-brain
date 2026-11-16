"""Testes de arquitetura do servidor MCP (ADR-0017, SPEC-0054:UT-07, SPEC-0059:UT-05, SPEC-0060:UT-05).
Run: python3 -m unittest discover -s mcp/tests -p test_architecture.py

Cada regra é testada contra um exemplo que a viola e contra o código real de mcp/fermion_mcp.py:
- arquivo único: mcp/ tem só fermion_mcp.py como código (fora de tests/);
- só biblioteca padrão; nenhum import de código das skills nem de tools/, nem carregamento dinâmico de código;
- nenhum shell;
- processo externo só na função executora run_cli, e só para as CLIs aceitas (Emenda v3 da SPEC-0054,
  SPEC-0059, SPEC-0060): nenhum texto aponta para a CLI de outra skill nem cita outro script, e cada tool, rodada
  de verdade com subprocess.run substituído, abre só `<python> <raiz>/skills/boson-atlas/scripts/atlas.py ...`
  (atlas_*), `<python> <raiz>/skills/photon-brain/scripts/brain.py ...` (brain_*) ou
  `<python> <raiz>/skills/gluon-spec/scripts/spec_graph.py --root <projeto> ...` (sdd_*).
"""
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from architecture_rules import (
    dynamic_code_findings,
    import_findings,
    other_cli_findings,
    process_findings,
    script_findings,
    shell_findings,
)
from helpers import (
    ATLAS_CLI,
    BRAIN_CLI,
    BRAIN_TOOLS,
    MCP,
    PROJECT_ENV,
    SDD_CLI,
    SDD_TOOLS,
    SERVER,
    TOOLS,
    attr,
    call,
    server_module,
)

ALLOWED_PROCESS_FUNCTIONS = ("run_cli",)
NAME = "mcp/fermion_mcp.py"
VALID_ARGUMENTS = {
    "atlas_config": {},
    "atlas_doctor": {},
    "atlas_context": {"query": "api", "hops": 1, "limit": 3, "max_chars": 1000},
    "atlas_lint": {"only": ["stale"]},
    "atlas_curate_list": {"status": "confirmed"},
    "brain_config": {},
    "brain_doctor": {},
    "brain_search": {"query": "api", "context": "college", "type": "note", "tag": "api", "limit": 3},
    "brain_related": {"note": "Payments API", "limit": 3},
    "brain_links": {"note": "Payments API"},
    "brain_context": {"query": "api", "context": "college", "hops": 1, "limit": 3, "max_chars": 1000},
    "brain_inbox_list": {},
    "brain_lint": {"only": ["broken-link"]},
    "sdd_status": {"ids": ["SPEC-0001"]},
    "sdd_validate": {"ids": ["ADR-0001", "SPEC-0002"]},
    "sdd_next": {},
    "sdd_waves": {},
    "sdd_report": {"id": "SPEC-0001"},
    "sdd_whats_new": {},
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

    def test_shell_through_aliases_getattr_and_kwargs_unpacking_is_reported(self):
        """SPEC-0054:UT-07 (alias, getattr e ** numa chamada de processo)"""
        source = (
            "import os\n"
            "import subprocess\n"
            "import subprocess as sp\n"
            "from os import system as s\n"
            "def run_cli(argv, timeout):\n"
            "    subprocess.run(argv, check=False, **{'shell': True})\n"
            "    opts = {}\n"
            "    subprocess.run(argv, check=False, **opts)\n"
            "    sp.getoutput('ls')\n"
            "    s('ls')\n"
            "    getattr(os, 'system')('ls')\n"
            "    sp.run(argv, shell=True, check=False)\n"
            "    dict(**opts)\n"
        )
        findings = shell_findings(source, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (6, 8, 9, 10, 11, 12)],
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

    def test_process_through_aliases_and_getattr_is_reported(self):
        """SPEC-0054:UT-07 (alias de módulo, alias de função e getattr)"""
        source = (
            "import os\n"
            "import subprocess\n"
            "import subprocess as sp\n"
            "from os import system as s\n"
            "def run_cli(argv, timeout):\n"
            "    return subprocess.run(argv, timeout=timeout, check=False)\n"
            "def tools_call(name):\n"
            "    sp.run(['ls'], check=False)\n"
            "    s('ls')\n"
            "    getattr(subprocess, 'run')(['ls'])\n"
            "    getattr(os, 'system')('ls')\n"
            "    getattr(sp, name)(['ls'])\n"
            "    getattr(name, 'run')\n"
            "import asyncio as aio\n"
        )
        findings = process_findings(source, NAME, ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual([f.split(" — ")[0] for f in findings],
                         [f"{NAME}:{n}" for n in (3, 4, 8, 9, 10, 11, 12, 14)], report(findings))
        self.assertIn("tools_call", findings[2])

    def test_aliases_inside_run_cli_are_still_reported(self):
        """SPEC-0054:UT-07 (dentro da executora o alias também é acusado: o chamado tem de ser legível)"""
        source = (
            "import subprocess as sp\n"
            "def run_cli(argv, timeout):\n"
            "    return getattr(sp, 'run')(argv, timeout=timeout, check=False)\n"
        )
        findings = process_findings(source, NAME, ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (1, 3)], report(findings))

    def test_other_skill_clis_are_reported(self):
        """SPEC-0054:UT-07 (Emenda v3: as CLIs da photon-brain e da gluon-spec passam a ser aceitas, SPEC-0059 e
        SPEC-0060; a pasta antiga continua acusada)"""
        source = (
            "ATLAS = 'skills/boson-atlas/scripts/atlas.py'\n"
            "SDD = 'sdd-management/scripts/spec_graph.py'\n"
            "BRAIN = 'skills/photon-brain/scripts/brain.py'\n"
            "OLD = 'tools/sdd/spec_graph.py'\n"
            "METHODS = ('tools/list', 'tools/call')\n"
        )
        findings = other_cli_findings(source, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (2, 4)],
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


class BrainBoundaryTest(unittest.TestCase):
    """SPEC-0059:UT-05 — processo só para atlas.py e brain.py das skills; nada de skills/ importado; sem shell."""

    def test_scripts_other_than_atlas_and_brain_are_reported(self):
        """SPEC-0059:UT-05 (spec_graph.py, aceito desde a SPEC-0060, conta como violação na lista da SPEC-0059)"""
        source = (
            "ATLAS = ('skills', 'boson-atlas', 'scripts', 'atlas.py')\n"
            "BRAIN = ('skills', 'photon-brain', 'scripts', 'brain.py')\n"
            "SDD = 'skills/gluon-spec/scripts/spec_graph.py'\n"
            "OTHER = ('skills', 'photon-brain', 'scripts', 'backup.py')\n"
            "TEXT = f'brain.py saiu com o código {1}'\n"
            "SHELLY = f'{x}/run_me.py --json'\n"
            "METHODS = ('tools/list', 'tools/call')\n"
        )
        findings = script_findings(source, NAME, allowed=("atlas.py", "brain.py"))
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (3, 4, 6)],
                         report(findings))

    def test_photon_brain_is_accepted_and_other_skills_are_not(self):
        """SPEC-0059:UT-05 (a gluon-spec é aceita desde a SPEC-0060; a pasta antiga dela continua acusada)"""
        source = (
            "BRAIN = 'skills/photon-brain/scripts/brain.py'\n"
            "HINT = 'rode a skill photon-brain (onboarding)'\n"
            "SDD = 'sdd-management/scripts/spec_graph.py'\n"
            "OLD_BRAIN = 'second-brain/scripts/brain.py'\n"  # pasta antiga, sem o prefixo (guarda da SPEC-0055)
            "OLD_SDD = 'sdd-management/scripts/x'\n"
            "TOOLS_DIR = 'tools/sdd'\n"
        )
        findings = other_cli_findings(source, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (3, 4, 5, 6)],
                         report(findings))

    def test_importing_brain_code_is_reported(self):
        """SPEC-0059:UT-05"""
        source = (
            "import json\n"
            "import brain\n"
            "from brain import search\n"
            "from brain_support import fn\n"
            "import photon_brain.scripts\n"
        )
        findings = import_findings(source, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (2, 3, 4, 5)],
                         report(findings))
        loader = (
            "import importlib.util, runpy\n"
            "spec = importlib.util.spec_from_file_location('brain', 'skills/photon-brain/scripts/brain.py')\n"
            "runpy.run_path('skills/photon-brain/scripts/brain.py')\n"
        )
        findings = dynamic_code_findings(loader, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (2, 3)], report(findings))

    def test_shell_for_the_brain_cli_is_reported(self):
        """SPEC-0059:UT-05"""
        source = (
            "import subprocess\n"
            "def run_cli(argv, timeout):\n"
            "    subprocess.run(argv, check=False)\n"
            "    subprocess.run('python3 brain.py search --json -- x', shell=True, check=False)\n"
        )
        findings = shell_findings(source, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:4"], report(findings))

    def test_server_cites_only_the_accepted_scripts(self):
        """SPEC-0059:UT-05 (código real sem achado)"""
        source = server_source()
        findings = (script_findings(source, NAME) + other_cli_findings(source, NAME)
                    + process_findings(source, NAME, ALLOWED_PROCESS_FUNCTIONS) + shell_findings(source, NAME)
                    + import_findings(source, NAME) + dynamic_code_findings(source, NAME))
        self.assertEqual(findings, [], report(findings))

    def test_every_tool_opens_only_the_atlas_or_the_brain_cli(self):
        """SPEC-0059:UT-05 (comportamento: atlas_* abrem atlas.py e brain_* abrem brain.py, sem shell)"""
        module = server_module()
        done = subprocess.CompletedProcess(["x"], 0, stdout="{}", stderr="")
        names = TOOLS + BRAIN_TOOLS
        with mock.patch.object(module.subprocess, "run", return_value=done) as run, \
                mock.patch.object(module.subprocess, "Popen", side_effect=AssertionError("Popen não é usado")):
            server = attr("Server")()
            for index, name in enumerate(names, 1):
                with self.subTest(tool=name):
                    response = server.handle(call(name, VALID_ARGUMENTS[name], id=index)) or {}
                    self.assertIn("result", response, f"{name}: {response}")
        self.assertEqual(run.call_count, len(names))
        for name, (args, kwargs) in zip(names, run.call_args_list):
            argv = args[0] if args else kwargs.get("args")
            with self.subTest(tool=name):
                self.assertIsInstance(argv, list)
                self.assertTrue(Path(argv[0]).name.startswith("python"), argv)
                expected = BRAIN_CLI if name.startswith("brain_") else ATLAS_CLI
                self.assertEqual(Path(argv[1]).resolve(), expected.resolve(), argv)
                self.assertFalse(kwargs.get("shell", False))



class SddBoundaryTest(unittest.TestCase):
    """SPEC-0060:UT-05 — processo só para atlas.py, brain.py e spec_graph.py das skills; nada de skills/ importado;
    sem shell."""

    def test_scripts_other_than_the_three_clis_are_reported(self):
        """SPEC-0060:UT-05"""
        source = (
            "ATLAS = ('skills', 'boson-atlas', 'scripts', 'atlas.py')\n"
            "BRAIN = ('skills', 'photon-brain', 'scripts', 'brain.py')\n"
            "SDD = ('skills', 'gluon-spec', 'scripts', 'spec_graph.py')\n"
            "TEXT = f'spec_graph.py não respondeu em {120} s'\n"
            "OTHER = ('skills', 'gluon-spec', 'scripts', 'board_sync.py')\n"
            "HOOK = 'hooks/session_start.py'\n"
            "SHELLY = f'{x}/run_me.py --json'\n"
            "VENDORED = 'tools/sdd/spec_graph.py'\n"
        )
        findings = script_findings(source, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (5, 6, 7)],
                         report(findings))

    def test_gluon_spec_is_accepted_and_old_folders_are_not(self):
        """SPEC-0060:UT-05 (a pasta da gluon-spec é aceita; a antiga, a do org-atlas e tools/sdd continuam acusadas)"""
        source = (
            "SDD = 'skills/gluon-spec/scripts/spec_graph.py'\n"
            "PARTS = ('skills', 'gluon-spec', 'scripts', 'spec_graph.py')\n"
            "OLD_SDD = 'sdd-management/scripts/spec_graph.py'\n"
            "VENDORED = 'tools/sdd/spec_graph.py'\n"
            "OLD_ATLAS = 'org-atlas/scripts/atlas.py'\n"
            "OLD_BRAIN = 'second-brain/scripts/brain.py'\n"
            "METHODS = ('tools/list', 'tools/call')\n"
        )
        findings = other_cli_findings(source, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (3, 4, 5, 6)],
                         report(findings))

    def test_importing_spec_graph_code_is_reported(self):
        """SPEC-0060:UT-05"""
        source = (
            "import json\n"
            "import spec_graph\n"
            "from spec_graph import main\n"
            "import gluon_spec.scripts\n"
            "from tools.sdd import spec_graph\n"
        )
        findings = import_findings(source, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (2, 3, 4, 5)],
                         report(findings))
        loader = (
            "import importlib.util, runpy\n"
            "spec = importlib.util.spec_from_file_location('sg', 'skills/gluon-spec/scripts/spec_graph.py')\n"
            "runpy.run_path('skills/gluon-spec/scripts/spec_graph.py')\n"
        )
        findings = dynamic_code_findings(loader, NAME)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:{n}" for n in (2, 3)], report(findings))

    def test_process_or_shell_for_the_sdd_cli_outside_run_cli_is_reported(self):
        """SPEC-0060:UT-05"""
        source = (
            "import subprocess\n"
            "def run_cli(argv, timeout):\n"
            "    subprocess.run(argv, check=False)\n"
            "    subprocess.run('python3 spec_graph.py status', shell=True, check=False)\n"
            "def sdd_status():\n"
            "    subprocess.run(['python3', 'spec_graph.py', 'status'], check=False)\n"
        )
        self.assertEqual([f.split(" — ")[0] for f in shell_findings(source, NAME)], [f"{NAME}:4"])
        findings = process_findings(source, NAME, ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual([f.split(" — ")[0] for f in findings], [f"{NAME}:6"], report(findings))

    def test_server_has_no_finding(self):
        """SPEC-0060:UT-05 (código real sem achado)"""
        source = server_source()
        findings = (script_findings(source, NAME) + other_cli_findings(source, NAME)
                    + process_findings(source, NAME, ALLOWED_PROCESS_FUNCTIONS) + shell_findings(source, NAME)
                    + import_findings(source, NAME) + dynamic_code_findings(source, NAME))
        self.assertEqual(findings, [], report(findings))

    def test_every_tool_opens_only_its_cli(self):
        """SPEC-0060:UT-05 (comportamento: atlas_* → atlas.py, brain_* → brain.py, sdd_* → spec_graph.py --root)"""
        module = server_module()
        done = subprocess.CompletedProcess(["x"], 0, stdout="{}", stderr="")
        names = TOOLS + BRAIN_TOOLS + SDD_TOOLS
        clis = {"atlas": ATLAS_CLI, "brain": BRAIN_CLI, "sdd": SDD_CLI}
        with mock.patch.dict(os.environ, {PROJECT_ENV: "/p"}), \
                mock.patch.object(module.subprocess, "run", return_value=done) as run, \
                mock.patch.object(module.subprocess, "Popen", side_effect=AssertionError("Popen não é usado")):
            server = attr("Server")()
            for index, name in enumerate(names, 1):
                with self.subTest(tool=name):
                    response = server.handle(call(name, VALID_ARGUMENTS[name], id=index)) or {}
                    self.assertIn("result", response, f"{name}: {response}")
        self.assertEqual(run.call_count, len(names))
        for name, (args, kwargs) in zip(names, run.call_args_list):
            argv = args[0] if args else kwargs.get("args")
            with self.subTest(tool=name):
                self.assertIsInstance(argv, list)
                self.assertTrue(Path(argv[0]).name.startswith("python"), argv)
                self.assertEqual(Path(argv[1]).resolve(), clis[name.split("_")[0]].resolve(), argv)
                if name.startswith("sdd_"):
                    self.assertEqual(argv[2:4], ["--root", "/p"], argv)
                self.assertFalse(kwargs.get("shell", False))


if __name__ == "__main__":
    unittest.main()
