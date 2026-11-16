"""Tools sdd_* de leitura do processo SDD no servidor MCP fermion (SPEC-0060: UT-01 a UT-04, IT-01 e IT-02;
ADR-0017). UT-05 fica em test_architecture.py.

Run: python3 -m unittest discover -s mcp/tests

Interface que estes testes exigem de mcp/fermion_mcp.py (seção 6 da SPEC-0060), além da SPEC-0054 e da SPEC-0059:

    tools/list traz as atlas_*, as brain_* e as seis sdd_* (SDD_TOOLS), cada uma com description, inputSchema
    object com additionalProperties: false e annotations.readOnlyHint: true:
        sdd_status      {ids: array de string ^SPEC-[0-9]{4,}$, 0..20 itens}
        sdd_validate    {ids: array de string ^(SPEC|ADR)-[0-9]{4,}$, 0..20 itens}
        sdd_next        {}
        sdd_waves       {}
        sdd_report      {id: string ^SPEC-[0-9]{4,}$ (obrigatório)}
        sdd_whats_new   {}
    O validador (_check) confere minItems/maxItems de qualquer array do schema.

    projeto = os.environ["CLAUDE_PROJECT_DIR"] se não vazio, senão os.getcwd() do servidor.
    argv de cada sdd_* = [<python>, "<plugin_root>/skills/gluon-spec/scripts/spec_graph.py", "--root", <projeto>,
    <comando>...], com timeout=120, e <comando>... exatamente:
        sdd_status      status [ids...]
        sdd_validate    validate [ids...]
        sdd_next        next
        sdd_waves       waves
        sdd_report      report <id>
        sdd_whats_new   whats-new          (nunca --ack)

    Saída: exit 0, e exit 1 só no sdd_validate → isError false, content texto = stdout, sem structuredContent;
    outro exit → isError true com o código e o stderr; timeout → SDD_TIMEOUT_TEXT; python ausente → caminho
    procurado; CLI ausente → caminho procurado, sem abrir processo.

Os UT põem CLAUDE_PROJECT_DIR no ambiente do processo de teste (mock.patch.dict), sem depender do ambiente real. Os
IT abrem o servidor real por stdio com HOME, SDD_CONFIG_HOME e XDG_* temporários (Sandbox.sdd_env) e um projeto
criado pela própria CLI da gluon-spec (Sandbox.fixture_project); nunca a configuração real da máquina.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import (
    BRAIN_TOOLS,
    CLI_TIMEOUT,
    PLUGIN_JSON,
    PROJECT_ENV,
    RESPONSE_TIMEOUT,
    SDD_CLI,
    SDD_TIMEOUT_TEXT,
    SDD_TOOLS,
    TOOLS,
    Sandbox,
    ServerProcess,
    attr,
    call,
    modern_meta,
    notification,
    request,
    server_module,
    text_of,
)
from test_server import (
    FakeRunner,
    accepts,
    error_of,
    new_server,
    result_of,
    tools_by_name,
)

FAKE_PROJECT = "/p"
MAX_IDS = 20
WRITE_FLAGS = ("--ack", "--apply", "--create", "--out")
VALID_SDD_ARGUMENTS = {
    "sdd_status": {"ids": ["SPEC-0001"]},
    "sdd_validate": {"ids": ["ADR-0001", "SPEC-0002"]},
    "sdd_next": {},
    "sdd_waves": {},
    "sdd_report": {"id": "SPEC-0001"},
    "sdd_whats_new": {},
}
EXPECTED_COMMANDS = (
    ("sdd_status", {}, ["status"]),
    ("sdd_status", {"ids": []}, ["status"]),
    ("sdd_status", {"ids": ["SPEC-0001", "SPEC-12345"]}, ["status", "SPEC-0001", "SPEC-12345"]),
    ("sdd_validate", {}, ["validate"]),
    ("sdd_validate", {"ids": ["ADR-0001", "SPEC-12345"]}, ["validate", "ADR-0001", "SPEC-12345"]),
    ("sdd_next", {}, ["next"]),
    ("sdd_waves", {}, ["waves"]),
    ("sdd_report", {"id": "SPEC-0060"}, ["report", "SPEC-0060"]),
    ("sdd_whats_new", {}, ["whats-new"]),
)


def sdd_names(tools):
    return sorted(name for name in tools if name.startswith("sdd_"))


def spec_ids(count, start=1):
    return [f"SPEC-{n:04d}" for n in range(start, start + count)]


class ProjectEnvCase(unittest.TestCase):
    """CLAUDE_PROJECT_DIR controlado pelo teste (o ambiente real pode ter outro valor)."""

    project = FAKE_PROJECT

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {PROJECT_ENV: self.project})
        patcher.start()
        self.addCleanup(patcher.stop)


# --------------------------------------------------------------------------- UT-01

class SddToolsListTest(unittest.TestCase):
    def setUp(self):
        self.tools = tools_by_name(self, result_of(self, new_server().handle(request("tools/list"))))

    def sdd_tool(self, name):
        self.assertIn(name, self.tools, f"tools/list sem {name}")
        return self.tools[name]

    def ids_schema(self, name):
        schema = self.sdd_tool(name)["inputSchema"]
        self.assertEqual(schema.get("required", []), [])
        self.assertEqual(sorted(schema.get("properties", {})), ["ids"])
        ids = schema["properties"]["ids"]
        self.assertEqual(ids.get("type"), "array")
        self.assertIn(ids.get("minItems", 0), (0,), "ids aceita lista vazia (0..20)")
        self.assertEqual(ids.get("maxItems"), MAX_IDS)
        self.assertEqual(ids.get("items", {}).get("type"), "string")
        return ids["items"]["pattern"]

    def test_the_six_sdd_tools_and_the_previous_tools_unchanged(self):
        """SPEC-0060:UT-01 (as atlas_* e brain_* das specs anteriores continuam iguais; conferido por prefixo)"""
        self.assertEqual(sdd_names(self.tools), sorted(SDD_TOOLS))
        self.assertEqual(sorted(n for n in self.tools if n.startswith("atlas_")), sorted(TOOLS))
        self.assertEqual(sorted(n for n in self.tools if n.startswith("brain_")), sorted(BRAIN_TOOLS))

    def test_both_eras_list_the_sdd_tools(self):
        """SPEC-0060:UT-01 (era legada depois do initialize e era moderna)"""
        server = new_server()
        result_of(self, server.handle(request("initialize", {"protocolVersion": "2025-11-25"}, id=1)), id=1)
        legacy = tools_by_name(self, result_of(self, server.handle(request("tools/list", id=2)), id=2))
        modern = tools_by_name(self, result_of(self, new_server().handle(request("tools/list", meta=modern_meta()))))
        self.assertEqual(sdd_names(legacy), sorted(SDD_TOOLS))
        self.assertEqual(sdd_names(modern), sorted(SDD_TOOLS))

    def test_every_sdd_tool_has_description_closed_schema_and_read_only_hint(self):
        """SPEC-0060:UT-01"""
        for name in SDD_TOOLS:
            with self.subTest(tool=name):
                tool = self.sdd_tool(name)
                self.assertIsInstance(tool.get("description"), str)
                self.assertTrue(tool["description"].strip(), "description vazia")
                schema = tool.get("inputSchema")
                self.assertIsInstance(schema, dict)
                self.assertEqual(schema.get("type"), "object")
                self.assertIs(schema.get("additionalProperties"), False)
                self.assertIs((tool.get("annotations") or {}).get("readOnlyHint"), True)

    def test_next_waves_and_whats_new_take_no_arguments(self):
        """SPEC-0060:UT-01"""
        for name in ("sdd_next", "sdd_waves", "sdd_whats_new"):
            with self.subTest(tool=name):
                schema = self.sdd_tool(name)["inputSchema"]
                self.assertEqual(schema.get("properties", {}), {})
                self.assertEqual(schema.get("required", []), [])

    def test_status_ids_are_specs_only(self):
        """SPEC-0060:UT-01 (padrão ^SPEC-[0-9]{4,}$, 0..20 itens)"""
        pattern = self.ids_schema("sdd_status")
        for good in ("SPEC-0001", "SPEC-0060", "SPEC-12345"):
            self.assertTrue(accepts(pattern, good), f"{pattern} recusa {good}")
        for bad in ("SPEC-1", "SPEC-001", "ADR-0001", "spec-0001", "SPEC-0001x", "xSPEC-0001", "--ack", "",
                    "SPEC-0001 SPEC-0002"):
            self.assertFalse(accepts(pattern, bad), f"{pattern} aceita {bad!r}")

    def test_validate_ids_are_specs_or_adrs(self):
        """SPEC-0060:UT-01 (padrão ^(SPEC|ADR)-[0-9]{4,}$, 0..20 itens)"""
        pattern = self.ids_schema("sdd_validate")
        for good in ("SPEC-0001", "ADR-0001", "ADR-12345", "SPEC-12345"):
            self.assertTrue(accepts(pattern, good), f"{pattern} recusa {good}")
        for bad in ("SPEC-1", "ADR-12", "EPIC-0001", "adr-0001", "ADR-0001;", "--apply", ""):
            self.assertFalse(accepts(pattern, bad), f"{pattern} aceita {bad!r}")

    def test_report_requires_one_spec_id(self):
        """SPEC-0060:UT-01"""
        schema = self.sdd_tool("sdd_report")["inputSchema"]
        self.assertEqual(schema.get("required"), ["id"])
        self.assertEqual(sorted(schema.get("properties", {})), ["id"])
        prop = schema["properties"]["id"]
        self.assertEqual(prop.get("type"), "string")
        pattern = prop.get("pattern")
        self.assertIsInstance(pattern, str)
        self.assertTrue(accepts(pattern, "SPEC-0060"))
        for bad in ("ADR-0001", "SPEC-1", "--ack", ""):
            self.assertFalse(accepts(pattern, bad), f"{pattern} aceita {bad!r}")


# --------------------------------------------------------------------------- UT-02

INVALID_SDD_CALLS = [
    ("status com id curto", "sdd_status", {"ids": ["SPEC-1"]}),
    ("status com ADR", "sdd_status", {"ids": ["ADR-0001"]}),
    ("status com 21 ids", "sdd_status", {"ids": spec_ids(MAX_IDS + 1)}),
    ("status com ids texto", "sdd_status", {"ids": "SPEC-0001"}),
    ("status com id não texto", "sdd_status", {"ids": [1]}),
    ("status com opção no lugar do id", "sdd_status", {"ids": ["--ack"]}),
    ("status com id e quebra de linha", "sdd_status", {"ids": ["SPEC-0001\n"]}),
    ("status com chave extra", "sdd_status", {"ids": [], "all": True}),
    ("validate com 21 ids", "sdd_validate", {"ids": spec_ids(MAX_IDS + 1)}),
    ("validate com id curto", "sdd_validate", {"ids": ["ADR-1"]}),
    ("validate com --apply", "sdd_validate", {"ids": ["--apply"]}),
    ("validate com id e ponto e vírgula", "sdd_validate", {"ids": ["SPEC-0001; rm"]}),
    ("report sem id", "sdd_report", {}),
    ("report com id --ack", "sdd_report", {"id": "--ack"}),
    ("report com ADR", "sdd_report", {"id": "ADR-0001"}),
    ("report com id lista", "sdd_report", {"id": ["SPEC-0001"]}),
    ("report com chave extra", "sdd_report", {"id": "SPEC-0001", "out": "x.md"}),
    ("next com chave extra", "sdd_next", {"all": True}),
    ("waves com chave extra", "sdd_waves", {"x": 1}),
    ("whats_new com ack", "sdd_whats_new", {"ack": True}),
    ("arguments não é objeto", "sdd_status", ["SPEC-0001"]),
    ("tool que grava: gate", "sdd_gate", {"id": "SPEC-0001"}),
    ("tool que grava: set", "sdd_set", {"id": "SPEC-0001"}),
    ("tool que grava: new", "sdd_new", {"title": "x"}),
    ("tool fora do escopo: export", "sdd_export", {}),
]


class SddInvalidArgumentsTest(ProjectEnvCase):
    def setUp(self):
        super().setUp()
        tools = tools_by_name(self, result_of(self, new_server().handle(request("tools/list"))))
        self.assertEqual(sdd_names(tools), sorted(SDD_TOOLS), "tools sdd_* ausentes do tools/list")

    def test_each_invalid_call_gets_32602_and_opens_no_process(self):
        """SPEC-0060:UT-02"""
        for label, name, arguments in INVALID_SDD_CALLS:
            with self.subTest(caso=label):
                runner = FakeRunner()
                error_of(self, new_server(runner).handle(call(name, arguments)), -32602)
                self.assertEqual(runner.calls, [], f"{label}: a CLI foi chamada")

    def test_valid_calls_reach_the_runner(self):
        """SPEC-0060:UT-02 (ADR e SPEC de 5 dígitos no validate; as bordas 0 e 20 dos ids valem)"""
        valid = [
            ("sdd_validate", {"ids": ["ADR-0001", "SPEC-12345"]}),
            ("sdd_status", {"ids": []}),
            ("sdd_status", {"ids": spec_ids(MAX_IDS)}),
            ("sdd_validate", {"ids": spec_ids(MAX_IDS)}),
            ("sdd_report", {"id": "SPEC-12345"}),
            ("sdd_next", {}),
            ("sdd_waves", None),
        ]
        for name, arguments in valid:
            with self.subTest(tool=name, arguments=arguments):
                runner = FakeRunner()
                result_of(self, new_server(runner).handle(call(name, arguments)))
                self.assertEqual(len(runner.calls), 1, "o válido precisa chegar ao executor")


class ArrayLimitsTest(unittest.TestCase):
    """O validador de argumentos (_check) passa a conferir minItems/maxItems (seção 6 da SPEC-0060)."""

    def test_validator_checks_min_and_max_items_of_any_array(self):
        """SPEC-0060:UT-02 (_check confere minItems/maxItems de qualquer array do schema)"""
        check = attr("_check")
        protocol_error = attr("ProtocolError")
        schema = {"type": "object", "additionalProperties": False, "properties": {
            "tags": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 3},
            "only_max": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 9}, "maxItems": 1},
        }}
        for arguments in ({"tags": ["a"]}, {"tags": []}, {"tags": ["a", "b", "c", "d"]}, {"only_max": [1, 2]}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(protocol_error) as caught:
                    check(arguments, schema, "arguments")
                self.assertEqual(caught.exception.code, -32602)
        for arguments in ({"tags": ["a", "b"]}, {"tags": ["a", "b", "c"]}, {"only_max": []}, {"only_max": [9]}, {}):
            with self.subTest(arguments=arguments):
                check(arguments, schema, "arguments")

    def test_array_limits_hold_in_nested_arrays(self):
        """SPEC-0060:UT-02 (o limite vale também para array dentro de array)"""
        check = attr("_check")
        protocol_error = attr("ProtocolError")
        schema = {"type": "array", "maxItems": 2,
                  "items": {"type": "array", "minItems": 1, "items": {"type": "string"}}}
        check([["a"], ["b", "c"]], schema, "arguments")
        for value in ([["a"], ["b"], ["c"]], [["a"], []]):
            with self.subTest(value=value), self.assertRaises(protocol_error):
                check(value, schema, "arguments")


# --------------------------------------------------------------------------- UT-03

class SddProjectDirTest(unittest.TestCase):
    """--root vem de CLAUDE_PROJECT_DIR (se não vazio) ou do cwd do servidor; nunca do agente."""

    def setUp(self):
        self.cwd = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cwd, True)
        previous = os.getcwd()
        os.chdir(self.cwd)
        self.addCleanup(os.chdir, previous)

    def status_argv(self, environ_change):
        patcher = mock.patch.dict(os.environ, environ_change)
        patcher.start()
        self.addCleanup(patcher.stop)
        if environ_change is None or PROJECT_ENV not in environ_change:
            os.environ.pop(PROJECT_ENV, None)
        runner = FakeRunner(0, "ok\n")
        result_of(self, new_server(runner).handle(call("sdd_status", {})))
        self.assertEqual(len(runner.calls), 1)
        argv, timeout = runner.calls[0]
        self.assertTrue(Path(argv[0]).name.startswith("python"), argv)
        self.assertEqual(Path(argv[1]).resolve(), SDD_CLI.resolve(), argv)
        self.assertEqual(timeout, CLI_TIMEOUT)
        return argv[2:]

    def test_project_dir_from_the_environment(self):
        """SPEC-0060:UT-03 (CLAUDE_PROJECT_DIR=/p)"""
        self.assertEqual(self.status_argv({PROJECT_ENV: FAKE_PROJECT}), ["--root", FAKE_PROJECT, "status"])

    def test_empty_project_dir_falls_back_to_the_server_cwd(self):
        """SPEC-0060:UT-03 (CLAUDE_PROJECT_DIR vazio)"""
        self.assertEqual(self.status_argv({PROJECT_ENV: ""}), ["--root", os.getcwd(), "status"])

    def test_missing_project_dir_falls_back_to_the_server_cwd(self):
        """SPEC-0060:UT-03 (sem CLAUDE_PROJECT_DIR)"""
        self.assertEqual(self.status_argv({}), ["--root", os.getcwd(), "status"])

    def test_cwd_fallback_is_not_the_plugin_root(self):
        """SPEC-0060:UT-03 (o cwd do servidor, não a raiz do plugin)"""
        args = self.status_argv({})
        self.assertNotEqual(Path(args[1]).resolve(), SDD_CLI.parents[3].resolve())
        self.assertEqual(Path(args[1]).resolve(), Path(self.cwd).resolve())


class SddCommandLineTest(ProjectEnvCase):
    def run_tool(self, name, arguments):
        runner = FakeRunner(0, "ok\n")
        result_of(self, new_server(runner).handle(call(name, arguments)))
        self.assertEqual(len(runner.calls), 1, f"{name} não chamou a CLI uma vez")
        argv, timeout = runner.calls[0]
        self.assertIsInstance(argv, list)
        self.assertTrue(all(isinstance(a, str) for a in argv), argv)
        self.assertTrue(Path(argv[0]).name.startswith("python"), f"executável não é python: {argv[0]}")
        self.assertEqual(Path(argv[1]).resolve(), SDD_CLI.resolve())
        self.assertEqual(timeout, CLI_TIMEOUT)
        return argv

    def test_command_line_of_each_tool(self):
        """SPEC-0060:UT-03"""
        for name, arguments, expected in EXPECTED_COMMANDS:
            with self.subTest(tool=name, arguments=arguments):
                self.assertEqual(self.run_tool(name, arguments)[2:], ["--root", FAKE_PROJECT] + expected)

    def test_no_command_line_writes(self):
        """SPEC-0060:UT-03 (nenhuma linha de comando de nenhuma sdd_* tem --ack, --apply, --create ou --out)"""
        for name, arguments, _ in EXPECTED_COMMANDS:
            with self.subTest(tool=name, arguments=arguments):
                argv = self.run_tool(name, arguments)
                for flag in WRITE_FLAGS:
                    self.assertFalse(any(a == flag or a.startswith(flag + "=") for a in argv), argv)

    def test_default_runner_uses_an_argument_list_without_shell(self):
        """SPEC-0060:UT-03 (sem shell)"""
        module = server_module()
        done = subprocess.CompletedProcess(["x"], 0, stdout="ok\n", stderr="")
        with mock.patch.object(module.subprocess, "run", return_value=done) as run:
            result_of(self, attr("Server")().handle(call("sdd_report", {"id": "SPEC-0001"})))
        self.assertEqual(run.call_count, 1)
        args, kwargs = run.call_args
        argv = args[0] if args else kwargs.get("args")
        self.assertIsInstance(argv, list)
        self.assertEqual(Path(argv[1]).resolve(), SDD_CLI.resolve())
        self.assertEqual(argv[2:], ["--root", FAKE_PROJECT, "report", "SPEC-0001"])
        self.assertFalse(kwargs.get("shell", False), "shell precisa ficar desligado")
        self.assertEqual(kwargs.get("timeout"), CLI_TIMEOUT)


# --------------------------------------------------------------------------- UT-04

class SddOutputMappingTest(ProjectEnvCase):
    def result(self, name, runner, arguments=None):
        return result_of(self, new_server(runner).handle(call(name, arguments or {})))

    def test_exit_0_gives_the_stdout_as_text_without_structured_content(self):
        """SPEC-0060:UT-04"""
        for stdout in ("SPEC-0001  proposed    SPEC (G0)  Fixture A\n", '{"ok": true}\n', ""):
            for name in SDD_TOOLS:
                with self.subTest(tool=name, stdout=stdout):
                    result = self.result(name, FakeRunner(0, stdout, "aviso\n"), VALID_SDD_ARGUMENTS[name])
                    self.assertIs(result.get("isError"), False)
                    self.assertEqual(text_of(result), stdout)
                    self.assertNotIn("structuredContent", result)

    def test_exit_1_in_validate_is_the_report_not_an_error(self):
        """SPEC-0060:UT-04 (exit 1 do validate = há ERRO na validação)"""
        stdout = "ERROR SPEC-0001: x\n\nG0 [projeto inteiro]: FAIL — 1 erro(s), 0 aviso(s)\n"
        result = self.result("sdd_validate", FakeRunner(1, stdout, ""))
        self.assertIs(result.get("isError"), False)
        self.assertEqual(text_of(result), stdout)
        self.assertNotIn("structuredContent", result)

    def test_exit_1_outside_validate_is_an_error_with_the_code_and_stderr(self):
        """SPEC-0060:UT-04 (exit 1 no sdd_status e nas outras é falha da CLI)"""
        stderr = "erro: falhou ao ler docs/specs\n"
        for name in ("sdd_status", "sdd_next", "sdd_waves", "sdd_report", "sdd_whats_new"):
            with self.subTest(tool=name):
                result = self.result(name, FakeRunner(1, "parcial\n", stderr), VALID_SDD_ARGUMENTS[name])
                self.assertIs(result.get("isError"), True)
                text = text_of(result)
                self.assertRegex(text, r"\b1\b")
                self.assertIn(stderr.strip(), text)
                self.assertNotIn("structuredContent", result)

    def test_exit_2_is_an_error_with_the_code_and_stderr(self):
        """SPEC-0060:UT-04 (ex.: spec não encontrada)"""
        cases = [
            ("sdd_report", {"id": "SPEC-0009"}, "erro: SPEC-0009 não encontrada\n"),
            ("sdd_validate", {"ids": ["ADR-0001"]}, "erro: não encontrado(s): ADR-0001\n"),
            ("sdd_status", {"ids": ["SPEC-0009"]}, "erro: não encontrado(s): SPEC-0009\n"),
        ]
        for name, arguments, stderr in cases:
            with self.subTest(tool=name):
                result = self.result(name, FakeRunner(2, "", stderr), arguments)
                self.assertIs(result.get("isError"), True)
                text = text_of(result)
                self.assertRegex(text, r"\b2\b")
                self.assertIn(stderr.strip(), text)
                self.assertNotIn("structuredContent", result)

    def test_timeout_is_an_error_result(self):
        """SPEC-0060:UT-04"""
        for name in SDD_TOOLS:
            with self.subTest(tool=name):
                runner = FakeRunner(raises=subprocess.TimeoutExpired(["python3"], CLI_TIMEOUT))
                result = self.result(name, runner, VALID_SDD_ARGUMENTS[name])
                self.assertIs(result.get("isError"), True)
                self.assertIn(SDD_TIMEOUT_TEXT, text_of(result))

    def test_missing_python_names_the_path_searched(self):
        """SPEC-0060:UT-04 (FileNotFoundError)"""
        runner = FakeRunner(raises=FileNotFoundError(2, "No such file or directory", "python3"))
        result = self.result("sdd_next", runner)
        self.assertIs(result.get("isError"), True)
        self.assertIn(runner.calls[0][0][0], text_of(result), "o texto precisa citar o caminho procurado")

    def test_missing_cli_names_the_path_searched(self):
        """SPEC-0060:UT-04 (CLI ausente)"""
        sandbox = Sandbox()
        self.addCleanup(sandbox.cleanup)
        (sandbox.root / ".claude-plugin").mkdir()
        shutil.copy(PLUGIN_JSON, sandbox.root / ".claude-plugin" / "plugin.json")
        runner = FakeRunner()
        server = attr("Server")(runner=runner, plugin_root=sandbox.root)
        result = result_of(self, server.handle(call("sdd_status", {})))
        self.assertIs(result.get("isError"), True)
        expected = sandbox.root / "skills" / "gluon-spec" / "scripts" / "spec_graph.py"
        self.assertIn(str(expected), text_of(result))
        self.assertEqual(runner.calls, [], "não chama a CLI que não existe")

    def test_modern_call_has_result_type(self):
        """SPEC-0060:UT-04 (era moderna)"""
        runner = FakeRunner(0, "Nenhuma spec pronta para despachar agora.\n")
        result = result_of(self, new_server(runner).handle(call("sdd_next", {}, meta=modern_meta())))
        self.assertEqual(result.get("resultType"), "complete")
        self.assertIs(result.get("isError"), False)
        self.assertEqual(text_of(result), "Nenhuma spec pronta para despachar agora.\n")
        self.assertNotIn("structuredContent", result)


# --------------------------------------------------------------------------- IT-01 e IT-02

class SddServerCase(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        self.sandbox.fixture_project()

    def open_server(self):
        server = ServerProcess(self.sandbox, env=self.sandbox.sdd_env())
        self.addCleanup(server.close)
        return server

    def ask(self, server, name, arguments, id):
        response, elapsed = server.ask(call(name, arguments, id=id))
        return result_of(self, response, id=id), elapsed


class SddSameResultAsCliTest(SddServerCase):
    """Projeto de fixture criado pela CLI (git init + dois new --tier lite); o servidor devolve o stdout da CLI."""

    CALLS = (
        ("sdd_status", {}, ["status"]),
        ("sdd_status", {"ids": ["SPEC-0001"]}, ["status", "SPEC-0001"]),
        ("sdd_validate", {}, ["validate"]),
        ("sdd_validate", {"ids": ["SPEC-0002"]}, ["validate", "SPEC-0002"]),
        ("sdd_next", {}, ["next"]),
    )

    def test_fixture_has_two_specs(self):
        """SPEC-0060:IT-01 (a fixture não é vazia: a comparação vale)"""
        out = self.sandbox.sdd_cli("status")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("SPEC-0001", out.stdout)
        self.assertIn("SPEC-0002", out.stdout)

    def test_status_validate_and_next_return_the_cli_stdout_within_5_seconds(self):
        """SPEC-0060:IT-01"""
        server = self.open_server()
        response, _ = server.ask(request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                                        "clientInfo": {"name": "it", "version": "0"}}, id=0))
        result_of(self, response, id=0)
        server.send(notification("notifications/initialized"))
        for index, (name, arguments, cli_args) in enumerate(self.CALLS, 1):
            with self.subTest(tool=name, arguments=arguments):
                result, elapsed = self.ask(server, name, arguments, index)
                expected = self.sandbox.sdd_cli(*cli_args)
                self.assertIn(expected.returncode, (0, 1) if name == "sdd_validate" else (0,), expected.stderr)
                self.assertTrue(expected.stdout.strip(), "a CLI não escreveu nada: a comparação não prova nada")
                self.assertIs(result.get("isError"), False, text_of(result))
                self.assertEqual(text_of(result), expected.stdout)
                self.assertNotIn("structuredContent", result)
                self.assertLess(elapsed, RESPONSE_TIMEOUT)

    def test_modern_call_returns_the_same_text(self):
        """SPEC-0060:IT-01 (era moderna)"""
        server = self.open_server()
        response, elapsed = server.ask(call("sdd_status", {}, id=7, meta=modern_meta()))
        expected = self.sandbox.sdd_cli("status")
        result = result_of(self, response, id=7)
        self.assertEqual(result.get("resultType"), "complete")
        self.assertEqual(text_of(result), expected.stdout)
        self.assertLess(elapsed, RESPONSE_TIMEOUT)


def snapshot(folder):
    """{caminho relativo: (bytes, mtime_ns)} de todo arquivo, e o conjunto de pastas, sob `folder`."""
    files, folders = {}, set()
    for path in sorted(Path(folder).rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if path.is_dir() and not path.is_symlink():
            folders.add(rel)
        else:
            files[rel] = (path.read_bytes() if path.is_file() else None, os.lstat(path).st_mtime_ns)
    return files, folders


class SddNothingWritesTest(SddServerCase):
    CALLS = (
        ("sdd_status", {}),
        ("sdd_validate", {}),
        ("sdd_next", {}),
        ("sdd_waves", {}),
        ("sdd_report", {"id": "SPEC-0001"}),
        ("sdd_whats_new", {}),
    )

    def test_the_six_tools_change_no_file_of_the_project(self):
        """SPEC-0060:IT-02 (conteúdo e mtime de todos os arquivos do projeto iguais antes e depois)"""
        before = snapshot(self.sandbox.project)
        self.assertTrue(any(rel.startswith("docs/specs/SPEC-0001") for rel in before[0]), sorted(before[0]))
        home_before = snapshot(self.sandbox.home)
        server = self.open_server()
        for index, (name, arguments) in enumerate(self.CALLS, 1):
            with self.subTest(tool=name):
                result, _ = self.ask(server, name, arguments, index)
                self.assertIs(result.get("isError"), False, text_of(result))
                self.assertTrue(text_of(result).strip(), f"{name} sem saída")
        server.close()
        after = snapshot(self.sandbox.project)
        self.assertEqual(sorted(after[1]), sorted(before[1]), "pastas do projeto mudaram")
        self.assertEqual(sorted(after[0]), sorted(before[0]), "arquivos do projeto criados ou apagados")
        for rel, (content, mtime) in before[0].items():
            with self.subTest(arquivo=rel):
                self.assertEqual(after[0][rel][0], content, "conteúdo mudou")
                self.assertEqual(after[0][rel][1], mtime, "mtime mudou")
        self.assertEqual(snapshot(self.sandbox.home), home_before, "o servidor gravou no HOME")

    def test_whats_new_never_acknowledges(self):
        """SPEC-0060:IT-02 (whats-new sem --ack: a versão do projeto continua desconhecida)"""
        server = self.open_server()
        first, _ = self.ask(server, "sdd_whats_new", {}, 1)
        second, _ = self.ask(server, "sdd_whats_new", {}, 2)
        self.assertEqual(text_of(first), text_of(second))
        self.assertEqual(text_of(second), self.sandbox.sdd_cli("whats-new").stdout)
        written = [rel for rel, (content, _) in snapshot(self.sandbox.project)[0].items()
                   if content and b"sdd_version" in content]
        self.assertEqual(written, [], "whats-new registrou sdd_version (--ack)")


if __name__ == "__main__":
    unittest.main()
