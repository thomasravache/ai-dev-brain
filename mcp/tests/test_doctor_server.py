"""Tool fermion_doctor no servidor MCP fermion (SPEC-0061:UT-08; ADR-0017, ADR-0019). As regras de arquitetura da
tool ficam em test_architecture.py (DoctorBoundaryTest).

Run: python3 -m unittest discover -s mcp/tests

Interface que estes testes exigem de mcp/fermion_mcp.py (seção 6 da SPEC-0061), além da SPEC-0054, SPEC-0059 e
SPEC-0060:

    tools/list traz, além das tools anteriores (iguais, campo a campo, ao retrato em
    fixtures/tools_before_spec_0061.json), a tool fermion_doctor: description não vazia,
    inputSchema {"type": "object", "properties": {}, "additionalProperties": false} (sem required) e
    annotations.readOnlyHint: true.

    tools/call fermion_doctor {} (ou sem arguments) → argv = [<python>, "<plugin_root>/scripts/fermion_doctor.py",
    "--project", <projeto>, "--json"], com <projeto> = CLAUDE_PROJECT_DIR se não vazio, senão o cwd do servidor
    (lido a cada chamada, como nas sdd_*). Qualquer outra chave em arguments → -32602 sem abrir processo.

    Saída: exit 0 → isError false, content texto = stdout e structuredContent = o JSON do doctor (com findings);
    outro exit, timeout ou python ausente → isError true; doctor ausente em <plugin_root>/scripts → isError true
    com o caminho procurado, sem abrir processo.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import (
    BRAIN_TOOLS,
    PROJECT_ENV,
    REPO,
    SDD_TOOLS,
    TESTS,
    TOOLS,
    call,
    modern_meta,
    request,
    text_of,
)
from test_server import FakeRunner, error_of, new_server, result_of, tools_by_name

DOCTOR_TOOL = "fermion_doctor"
DOCTOR = REPO / "scripts" / "fermion_doctor.py"
BEFORE = TESTS / "fixtures" / "tools_before_spec_0061.json"
FAKE_PROJECT = "/p"
DOCTOR_JSON = {
    "plugin_versions": {"gluon-spec": "2026.11.3", "photon-brain": "2026.11.6", "boson-atlas": "2026.11.6"},
    "findings": [{"check": "old-name-copy", "level": "warn", "path": "/h/.claude/skills/antiga",
                  "detail": "cópia com o nome antigo", "fix": "remova a pasta"}],
}


def previous_tools():
    return {tool["name"]: tool for tool in json.loads(BEFORE.read_text(encoding="utf-8"))}


class ProjectEnvCase(unittest.TestCase):
    """CLAUDE_PROJECT_DIR controlado pelo teste (o ambiente real pode ter outro valor)."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {PROJECT_ENV: FAKE_PROJECT})
        patcher.start()
        self.addCleanup(patcher.stop)


# --------------------------------------------------------------------------- UT-08: tools/list

class DoctorToolListTest(unittest.TestCase):
    def setUp(self):
        self.tools = tools_by_name(self, result_of(self, new_server().handle(request("tools/list"))))

    def doctor_tool(self, tools=None):
        tools = self.tools if tools is None else tools
        self.assertTrue(DOCTOR_TOOL in tools, f"tools/list sem {DOCTOR_TOOL}: {sorted(tools)}")
        return tools[DOCTOR_TOOL]

    def test_doctor_tool_has_empty_closed_schema_and_read_only_hint(self):
        """SPEC-0061:UT-08 (inputSchema vazio e fechado, readOnlyHint: true)"""
        tool = self.doctor_tool()
        self.assertIsInstance(tool.get("description"), str)
        self.assertTrue(tool["description"].strip(), "description vazia")
        schema = dict(tool.get("inputSchema") or {})
        self.assertEqual(schema.pop("required", []), [])
        self.assertEqual(schema, {"type": "object", "properties": {}, "additionalProperties": False})
        self.assertIs((tool.get("annotations") or {}).get("readOnlyHint"), True)

    def test_both_eras_list_the_doctor_tool(self):
        """SPEC-0061:UT-08 (era legada depois do initialize e era moderna)"""
        server = new_server()
        result_of(self, server.handle(request("initialize", {"protocolVersion": "2025-11-25"}, id=1)), id=1)
        legacy = tools_by_name(self, result_of(self, server.handle(request("tools/list", id=2)), id=2))
        modern = tools_by_name(self, result_of(self, new_server().handle(request("tools/list", meta=modern_meta()))))
        self.assertEqual(self.doctor_tool(legacy), self.doctor_tool(modern))

    def test_previous_tools_are_unchanged(self):
        """SPEC-0061:UT-08 (as atlas_*, brain_* e sdd_* continuam iguais ao retrato de antes da SPEC-0061)"""
        before = previous_tools()
        self.assertEqual(sorted(before), sorted(TOOLS + BRAIN_TOOLS + SDD_TOOLS), "retrato fora do esperado")
        self.assertEqual(sorted(self.tools), sorted([*before, DOCTOR_TOOL]))
        for name, tool in before.items():
            with self.subTest(tool=name):
                self.assertEqual(self.tools[name], tool)


# --------------------------------------------------------------------------- UT-08: tools/call

class DoctorCallTest(ProjectEnvCase):
    def doctor_argv(self, arguments=None, runner=None):
        runner = runner or FakeRunner(0, json.dumps(DOCTOR_JSON))
        result_of(self, new_server(runner).handle(call(DOCTOR_TOOL, arguments)))
        self.assertEqual(len(runner.calls), 1, "fermion_doctor não abriu o doctor uma vez")
        argv, timeout = runner.calls[0]
        self.assertIsInstance(argv, list)
        self.assertTrue(all(isinstance(a, str) for a in argv), argv)
        self.assertTrue(Path(argv[0]).name.startswith("python"), argv)
        self.assertEqual(Path(argv[1]).resolve(), DOCTOR.resolve(), argv)
        self.assertTrue(isinstance(timeout, (int, float)) and timeout > 0, timeout)
        return argv

    def test_command_line_is_project_and_json(self):
        """SPEC-0061:UT-08 (fermion_doctor.py --project <projeto> --json)"""
        for arguments in ({}, None):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.doctor_argv(arguments)[2:], ["--project", FAKE_PROJECT, "--json"])

    def test_project_falls_back_to_the_server_cwd(self):
        """SPEC-0061:UT-08 (CLAUDE_PROJECT_DIR vazio ou ausente: o cwd do servidor)"""
        cwd = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cwd, True)
        previous = os.getcwd()
        os.chdir(cwd)
        self.addCleanup(os.chdir, previous)
        for label, change in (("vazio", lambda: os.environ.__setitem__(PROJECT_ENV, "")),
                              ("ausente", lambda: os.environ.pop(PROJECT_ENV, None))):
            with self.subTest(caso=label):
                change()
                argv = self.doctor_argv({})
                self.assertEqual(argv[2], "--project")
                self.assertEqual(Path(argv[3]).resolve(), Path(cwd).resolve())
                self.assertEqual(argv[4:], ["--json"])

    def test_any_argument_is_rejected_without_a_process(self):
        """SPEC-0061:UT-08 (inputSchema fechado: -32602 sem abrir processo)"""
        for arguments in ({"project": "/outro"}, {"json": False}, {"fix": True}, ["--project"], "x"):
            with self.subTest(arguments=arguments):
                runner = FakeRunner()
                error_of(self, new_server(runner).handle(call(DOCTOR_TOOL, arguments)), -32602)
                self.assertEqual(runner.calls, [])

    def test_exit_0_gives_structured_content_with_findings(self):
        """SPEC-0061:UT-08 (exit 0 → isError false com structuredContent)"""
        stdout = json.dumps(DOCTOR_JSON, ensure_ascii=False)
        result = result_of(self, new_server(FakeRunner(0, stdout)).handle(call(DOCTOR_TOOL, {})))
        self.assertIs(result.get("isError"), False)
        self.assertEqual(result.get("structuredContent"), DOCTOR_JSON)
        self.assertIn("findings", result["structuredContent"])
        self.assertEqual(text_of(result), stdout)

    def test_no_findings_is_still_a_success(self):
        """SPEC-0061:UT-08 (findings vazio)"""
        empty = {"plugin_versions": DOCTOR_JSON["plugin_versions"], "findings": []}
        result = result_of(self, new_server(FakeRunner(0, json.dumps(empty))).handle(call(DOCTOR_TOOL, {})))
        self.assertIs(result.get("isError"), False)
        self.assertEqual(result.get("structuredContent"), empty)

    def test_failures_are_tool_errors(self):
        """SPEC-0061:UT-08 (exit diferente de 0, timeout e python ausente → isError true)"""
        cases = {
            "exit 2": FakeRunner(2, "", "uso: fermion_doctor.py ...\n"),
            "timeout": FakeRunner(raises=subprocess.TimeoutExpired(["python3"], 120)),
            "python ausente": FakeRunner(raises=FileNotFoundError(2, "No such file or directory", "python3")),
        }
        for label, runner in cases.items():
            with self.subTest(caso=label):
                result = result_of(self, new_server(runner).handle(call(DOCTOR_TOOL, {})))
                self.assertIs(result.get("isError"), True, result)
                self.assertTrue(text_of(result).strip())

    def test_missing_doctor_is_reported_without_a_process(self):
        """SPEC-0061:UT-08 (doctor ausente na raiz do plugin)"""
        root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, root, True)
        runner = FakeRunner()
        result = result_of(self, new_server(runner, plugin_root=root).handle(call(DOCTOR_TOOL, {})))
        self.assertIs(result.get("isError"), True)
        self.assertIn(str(root / "scripts" / "fermion_doctor.py"), text_of(result))
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
