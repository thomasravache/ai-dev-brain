"""Servidor MCP local do plugin fermion com as tools atlas (SPEC-0054: UT-01 a UT-06, IT-01 a IT-03; ADR-0017).

Run: python3 -m unittest discover -s mcp/tests

Interface que estes testes exigem de mcp/fermion_mcp.py (o Implementer segue estes testes):

    O módulo é importável sem efeito colateral: o laço de stdio só roda em main(), chamado sob
    `if __name__ == "__main__":`. Só biblioteca padrão, Python 3.9+.

    PLUGIN_ROOT: Path
        Raiz do plugin = a pasta acima de mcp/ (Path(__file__).resolve().parent.parent), nunca o cwd.

    run_cli(argv: list[str], timeout: float) -> subprocess.CompletedProcess
        Executor padrão: subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False), com
        argv em lista, sem shell e com o ambiente herdado. Não engole subprocess.TimeoutExpired nem OSError
        (FileNotFoundError): quem trata é o Server.

    Server(runner=run_cli, plugin_root=PLUGIN_ROOT)
        runner(argv, timeout) -> objeto com returncode (int), stdout (str) e stderr (str); chamado com
        timeout=120. Pode levantar subprocess.TimeoutExpired ou OSError.
        argv de cada tool = [<python>, "<plugin_root>/skills/boson-atlas/scripts/atlas.py", <comando>...], em que
        <python> é sys.executable ou "python3" (nome que começa com "python"), e <comando>... é exatamente:
            atlas_config        config --json
            atlas_doctor        doctor --json
            atlas_context       context [--hops H] [--limit L] [--max-chars M] --json -- <query.split()>
            atlas_lint          lint --json [--only a,b]
            atlas_curate_list   curate list --json [--status S]
        A versão de serverInfo vem de <plugin_root>/.claude-plugin/plugin.json.

        handle(message) -> dict | None
            Recebe UMA mensagem JSON-RPC já decodificada (qualquer valor JSON) e devolve a resposta como dict,
            ou None para notificação (mensagem sem "id"). Guarda o estado da era legada (initialize).

    main() -> None (ou int 0)
        Lê o stdin linha a linha, decodifica (falha = -32700 com id null), chama Server().handle e escreve cada
        resposta numa linha do stdout; diagnóstico só no stderr; sai com 0 quando o stdin fecha.

Contrato conferido: seção 6 (v2) da SPEC-0054 e o schema oficial MCP 2026-07-28 (DiscoverResult, resultType,
ttlMs/cacheScope em ListToolsResult, UnsupportedProtocolVersionError -32022).
"""
import contextlib
import io
import json
import re
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from helpers import (
    ATLAS_CLI,
    CAPS_KEY,
    CLI_TIMEOUT,
    LEGACY_VERSIONS,
    MODERN_VERSION,
    NOT_CONFIGURED,
    PLUGIN_JSON,
    REPO,
    RESPONSE_TIMEOUT,
    SERVER_INFO_KEY,
    SUPPORTED_VERSIONS,
    TIMEOUT_TEXT,
    TOOLS,
    Sandbox,
    ServerProcess,
    attr,
    call,
    modern_meta,
    notification,
    plugin_version,
    request,
    server_module,
    text_of,
)

MODERN_ONLY_FIELDS = ("resultType", "ttlMs", "cacheScope")


class FakeRunner:
    """Executor substituto: grava cada chamada e devolve o resultado configurado (ou levanta a exceção)."""

    def __init__(self, returncode=0, stdout="{}", stderr="", raises=None):
        self.calls = []
        self.returncode, self.stdout, self.stderr, self.raises = returncode, stdout, stderr, raises

    def __call__(self, argv, timeout):
        self.calls.append((list(argv), timeout))
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


def new_server(runner=None, **kwargs):
    return attr("Server")(runner=runner or FakeRunner(), **kwargs)


def result_of(case, response, id=1):
    case.assertIsNotNone(response, "request recebeu None (só notificação fica sem resposta)")
    case.assertEqual(response.get("jsonrpc"), "2.0", response)
    case.assertEqual(response.get("id"), id, response)
    case.assertNotIn("error", response, response)
    case.assertIn("result", response, response)
    return response["result"]


def error_of(case, response, code, id=1):
    case.assertIsNotNone(response, "request recebeu None (só notificação fica sem resposta)")
    case.assertEqual(response.get("jsonrpc"), "2.0", response)
    case.assertEqual(response.get("id"), id, response)
    case.assertNotIn("result", response, response)
    case.assertEqual(response.get("error", {}).get("code"), code, response)
    return response["error"]


def tools_by_name(case, result):
    tools = result.get("tools")
    case.assertIsInstance(tools, list, result)
    return {tool["name"]: tool for tool in tools}


def accepts(pattern, value):
    return re.search(pattern, value) is not None


# --------------------------------------------------------------------------- UT-01

class ToolsListTest(unittest.TestCase):
    def setUp(self):
        self.tools = tools_by_name(self, result_of(self, new_server().handle(request("tools/list"))))

    def test_exactly_the_five_tools(self):
        """SPEC-0054:UT-01"""
        self.assertEqual(sorted(self.tools), sorted(TOOLS))

    def test_every_tool_has_description_closed_object_schema_and_read_only_hint(self):
        """SPEC-0054:UT-01"""
        for name, tool in self.tools.items():
            with self.subTest(tool=name):
                self.assertIsInstance(tool.get("description"), str)
                self.assertTrue(tool["description"].strip(), "description vazia")
                schema = tool.get("inputSchema")
                self.assertIsInstance(schema, dict)
                self.assertEqual(schema.get("type"), "object")
                self.assertIs(schema.get("additionalProperties"), False)
                self.assertIs((tool.get("annotations") or {}).get("readOnlyHint"), True)

    def test_config_and_doctor_take_no_arguments(self):
        """SPEC-0054:UT-01"""
        for name in ("atlas_config", "atlas_doctor"):
            with self.subTest(tool=name):
                schema = self.tools[name]["inputSchema"]
                self.assertEqual(schema.get("properties", {}), {})
                self.assertEqual(schema.get("required", []), [])

    def test_context_schema_has_the_contract_ranges(self):
        """SPEC-0054:UT-01"""
        schema = self.tools["atlas_context"]["inputSchema"]
        self.assertEqual(schema.get("required"), ["query"])
        props = schema["properties"]
        self.assertEqual(sorted(props), ["hops", "limit", "max_chars", "query"])
        query = props["query"]
        self.assertEqual((query["type"], query["minLength"], query["maxLength"]), ("string", 1, 500))
        for key, low, high in (("hops", 0, 2), ("limit", 1, 200), ("max_chars", 500, 200000)):
            with self.subTest(prop=key):
                prop = props[key]
                self.assertEqual((prop["type"], prop["minimum"], prop["maximum"]), ("integer", low, high))

    def test_lint_schema_takes_an_optional_list_of_rule_names(self):
        """SPEC-0054:UT-01"""
        schema = self.tools["atlas_lint"]["inputSchema"]
        self.assertEqual(schema.get("required", []), [])
        self.assertEqual(sorted(schema["properties"]), ["only"])
        only = schema["properties"]["only"]
        self.assertEqual(only["type"], "array")
        self.assertEqual(only["items"]["type"], "string")
        pattern = only["items"]["pattern"]
        for good in ("secret-leak", "stale", "pending-convention"):
            self.assertTrue(accepts(pattern, good), f"{pattern} recusa {good}")
        for bad in ("Bad Rule", "stale;rm", "", "UPPER", "a,b"):
            self.assertFalse(accepts(pattern, bad), f"{pattern} aceita {bad!r}")

    def test_curate_list_schema_has_the_status_enum(self):
        """SPEC-0054:UT-01"""
        schema = self.tools["atlas_curate_list"]["inputSchema"]
        self.assertEqual(schema.get("required", []), [])
        self.assertEqual(sorted(schema["properties"]), ["status"])
        status = schema["properties"]["status"]
        self.assertEqual(status["type"], "string")
        self.assertEqual(sorted(status["enum"]), ["confirmed", "inferred", "rejected"])


# --------------------------------------------------------------------------- UT-02

INVALID_CALLS = [
    ("tool desconhecida", "atlas_scan", {}),
    ("tool que grava", "atlas_curate_confirm", {"id": "x"}),
    ("query ausente", "atlas_context", {}),
    ("query vazia", "atlas_context", {"query": ""}),
    ("query com 501 caracteres", "atlas_context", {"query": "a" * 501}),
    ("query não é texto", "atlas_context", {"query": 7}),
    ("hops 3", "atlas_context", {"query": "api", "hops": 3}),
    ("hops -1", "atlas_context", {"query": "api", "hops": -1}),
    ("hops texto", "atlas_context", {"query": "api", "hops": "1"}),
    ("hops booleano", "atlas_context", {"query": "api", "hops": True}),
    ("hops fracionário", "atlas_context", {"query": "api", "hops": 1.5}),
    ("limit 0", "atlas_context", {"query": "api", "limit": 0}),
    ("limit 201", "atlas_context", {"query": "api", "limit": 201}),
    ("max_chars 499", "atlas_context", {"query": "api", "max_chars": 499}),
    ("max_chars 200001", "atlas_context", {"query": "api", "max_chars": 200001}),
    ("chave extra no context", "atlas_context", {"query": "api", "extra": 1}),
    ("status pending", "atlas_curate_list", {"status": "pending"}),
    ("only com regra inválida", "atlas_lint", {"only": ["Bad Rule"]}),
    ("only não é lista", "atlas_lint", {"only": "stale"}),
    ("only com item que não é texto", "atlas_lint", {"only": [1]}),
    ("chave extra no config", "atlas_config", {"verbose": True}),
    ("chave extra no doctor", "atlas_doctor", {"fix": True}),
    ("arguments não é objeto", "atlas_config", ["x"]),
    ("query com NUL", "atlas_context", {"query": "api\x00rm"}),
    ("query com 0x01", "atlas_context", {"query": "api\x01"}),
    ("query com ESC", "atlas_context", {"query": "api \x1b[31m"}),
    ("query com 0x1f", "atlas_context", {"query": "\x1fapi"}),
    ("query com tab", "atlas_context", {"query": "api\tpay"}),
    ("query com quebra de linha", "atlas_context", {"query": "api\npay"}),
    ("query com retorno de carro", "atlas_context", {"query": "api\rpay"}),
]


class InvalidArgumentsTest(unittest.TestCase):
    def test_each_invalid_call_gets_32602_and_opens_no_process(self):
        """SPEC-0054:UT-02"""
        for label, name, arguments in INVALID_CALLS:
            with self.subTest(caso=label):
                runner = FakeRunner()
                response = new_server(runner).handle(call(name, arguments))
                error_of(self, response, -32602)
                self.assertEqual(runner.calls, [], f"{label}: a CLI foi chamada")

    def test_call_without_name_gets_32602(self):
        """SPEC-0054:UT-02"""
        runner = FakeRunner()
        error_of(self, new_server(runner).handle(request("tools/call", {"arguments": {}})), -32602)
        self.assertEqual(runner.calls, [])

    def test_valid_limits_are_accepted(self):
        """SPEC-0054:UT-02 (as bordas das faixas valem)"""
        for arguments in ({"query": "a", "hops": 0, "limit": 1, "max_chars": 500},
                          {"query": "a" * 500, "hops": 2, "limit": 200, "max_chars": 200000}):
            runner = FakeRunner()
            result_of(self, new_server(runner).handle(call("atlas_context", arguments)))
            self.assertEqual(len(runner.calls), 1)


# --------------------------------------------------------------------------- UT-03

def cli_prefix_ok(case, argv):
    case.assertIsInstance(argv, list)
    case.assertTrue(all(isinstance(a, str) for a in argv), argv)
    case.assertTrue(Path(argv[0]).name.startswith("python"), f"executável não é python: {argv[0]}")
    case.assertEqual(Path(argv[1]).resolve(), ATLAS_CLI.resolve())


class CommandLineTest(unittest.TestCase):
    def run_tool(self, name, arguments=None):
        runner = FakeRunner()
        result_of(self, new_server(runner).handle(call(name, arguments if arguments is not None else {})))
        self.assertEqual(len(runner.calls), 1)
        argv, timeout = runner.calls[0]
        cli_prefix_ok(self, argv)
        self.assertEqual(timeout, CLI_TIMEOUT)
        return argv[2:]

    def test_free_text_goes_after_double_dash_one_argument_per_word(self):
        """SPEC-0054:UT-03"""
        args = self.run_tool("atlas_context", {"query": "-rf --hops 9; rm"})
        self.assertEqual(args, ["context", "--json", "--", "-rf", "--hops", "9;", "rm"])

    def test_quotes_and_semicolons_stay_inside_their_word(self):
        """SPEC-0054:UT-03"""
        args = self.run_tool("atlas_context", {"query": "a\"b 'c; $(x) `y`"})
        self.assertEqual(args, ["context", "--json", "--", "a\"b", "'c;", "$(x)", "`y`"])

    def test_options_come_before_json_and_double_dash(self):
        """SPEC-0054:UT-03"""
        args = self.run_tool("atlas_context", {"query": "api payments", "hops": 2, "limit": 5, "max_chars": 1000})
        self.assertEqual(args, ["context", "--hops", "2", "--limit", "5", "--max-chars", "1000", "--json", "--",
                                "api", "payments"])

    def test_command_line_of_each_other_tool(self):
        """SPEC-0054:UT-03"""
        cases = [
            ("atlas_config", {}, ["config", "--json"]),
            ("atlas_doctor", {}, ["doctor", "--json"]),
            ("atlas_lint", {}, ["lint", "--json"]),
            ("atlas_lint", {"only": ["secret-leak", "stale"]}, ["lint", "--json", "--only", "secret-leak,stale"]),
            ("atlas_curate_list", {}, ["curate", "list", "--json"]),
            ("atlas_curate_list", {"status": "inferred"}, ["curate", "list", "--json", "--status", "inferred"]),
        ]
        for name, arguments, expected in cases:
            with self.subTest(tool=name, arguments=arguments):
                self.assertEqual(self.run_tool(name, arguments), expected)

    def test_missing_arguments_are_an_empty_object(self):
        """SPEC-0054:UT-03"""
        runner = FakeRunner()
        result_of(self, new_server(runner).handle(call("atlas_config")))
        self.assertEqual(runner.calls[0][0][2:], ["config", "--json"])

    def test_default_root_is_the_folder_above_mcp(self):
        """SPEC-0054:UT-03 (raiz do plugin pelo __file__, nunca o cwd)"""
        self.assertEqual(Path(attr("PLUGIN_ROOT")).resolve(), REPO.resolve())

    def test_default_runner_uses_an_argument_list_without_shell(self):
        """SPEC-0054:UT-03"""
        module = server_module()
        done = subprocess.CompletedProcess(["x"], 0, stdout="{}", stderr="")
        with mock.patch.object(module.subprocess, "run", return_value=done) as run:
            server = attr("Server")()
            result_of(self, server.handle(call("atlas_context", {"query": "-rf ; rm"})))
        self.assertEqual(run.call_count, 1)
        args, kwargs = run.call_args
        argv = args[0] if args else kwargs.get("args")
        cli_prefix_ok(self, argv)
        self.assertEqual(argv[2:], ["context", "--json", "--", "-rf", ";", "rm"])
        self.assertFalse(kwargs.get("shell", False), "shell precisa ficar desligado")
        self.assertEqual(kwargs.get("timeout"), CLI_TIMEOUT)
        self.assertIn("check", kwargs, "subprocess.run precisa de check= explícito")
        self.assertFalse(kwargs["check"])


# --------------------------------------------------------------------------- UT-04

class OutputMappingTest(unittest.TestCase):
    def result(self, name, runner, arguments=None):
        return result_of(self, new_server(runner).handle(call(name, arguments or {})))

    def test_exit_0_gives_text_and_structured_content(self):
        """SPEC-0054:UT-04"""
        stdout = json.dumps({"version": "x", "values": {"mode": "local"}}, indent=2) + "\n"
        result = self.result("atlas_config", FakeRunner(0, stdout))
        self.assertEqual(text_of(result), stdout)
        self.assertEqual(result.get("structuredContent"), json.loads(stdout))
        self.assertIs(result.get("isError"), False)

    def test_structured_content_only_for_a_json_object(self):
        """SPEC-0054:UT-04"""
        for stdout in ('["a", "b"]\n', "texto qualquer\n", "42\n", ""):
            with self.subTest(stdout=stdout):
                result = self.result("atlas_config", FakeRunner(0, stdout))
                self.assertEqual(text_of(result) if result.get("content") else "", stdout)
                self.assertNotIn("structuredContent", result)
                self.assertIs(result.get("isError"), False)

    def test_exit_1_in_lint_is_a_report_not_an_error(self):
        """SPEC-0054:UT-04"""
        stdout = json.dumps({"ok": False, "errors": 1, "findings": []}) + "\n"
        result = self.result("atlas_lint", FakeRunner(1, stdout, "1 erro\n"))
        self.assertEqual(text_of(result), stdout)
        self.assertEqual(result.get("structuredContent"), json.loads(stdout))
        self.assertIs(result.get("isError"), False)

    def test_exit_1_outside_lint_is_an_error(self):
        """SPEC-0054:UT-04"""
        result = self.result("atlas_context", FakeRunner(1, "", "falhou feio\n"), {"query": "api"})
        self.assertIs(result.get("isError"), True)
        self.assertIn("1", text_of(result))
        self.assertIn("falhou feio", text_of(result))

    def test_exit_3_points_to_onboarding_with_the_cli_stderr(self):
        """SPEC-0054:UT-04"""
        stderr = "erro: org-atlas não configurado nesta máquina — rode init (ou init --join)\n"
        for name in ("atlas_doctor", "atlas_lint"):
            with self.subTest(tool=name):
                result = self.result(name, FakeRunner(3, "", stderr))
                self.assertIs(result.get("isError"), True)
                text = text_of(result)
                self.assertIn(NOT_CONFIGURED, text)
                self.assertIn(stderr.strip(), text)
                self.assertNotIn("structuredContent", result)

    def test_other_exit_gives_the_code_and_the_stderr(self):
        """SPEC-0054:UT-04"""
        result = self.result("atlas_context", FakeRunner(2, "", "erro: --hops fora de 0..2\n"), {"query": "api"})
        self.assertIs(result.get("isError"), True)
        text = text_of(result)
        self.assertRegex(text, r"\b2\b")
        self.assertIn("erro: --hops fora de 0..2", text)

    def test_timeout_is_an_error_result(self):
        """SPEC-0054:UT-04"""
        runner = FakeRunner(raises=subprocess.TimeoutExpired(["python3"], CLI_TIMEOUT))
        result = self.result("atlas_doctor", runner)
        self.assertIs(result.get("isError"), True)
        self.assertIn(TIMEOUT_TEXT, text_of(result))

    def test_missing_python_is_an_error_result(self):
        """SPEC-0054:UT-04"""
        runner = FakeRunner(raises=FileNotFoundError(2, "No such file or directory", "python3"))
        result = self.result("atlas_doctor", runner)
        self.assertIs(result.get("isError"), True)
        searched = runner.calls[0][0][0]
        self.assertIn(searched, text_of(result), "o texto precisa citar o caminho procurado")

    def test_unknown_method_with_control_characters_logs_a_single_clean_line(self):
        """SPEC-0054:UT-04 (observabilidade: uma linha no stderr por erro, sem texto injetado)"""
        method = "x\nINJETADO linha falsa\r\x1b[31mvermelho\x00fim\u2028sep"
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            response = new_server().handle(request(method, id=4))
        error_of(self, response, -32601, id=4)
        log = captured.getvalue()
        self.assertLessEqual(log.count("\n"), 1, f"mais de uma linha no stderr: {log!r}")
        self.assertTrue(log == "" or log.endswith("\n"), repr(log))
        self.assertNotIn("INJETADO", log)
        for char in ("\r", "\x1b", "\x00", "\u2028"):
            self.assertNotIn(char, log, f"caractere de controle {char!r} no stderr")

    def test_missing_cli_names_the_path_searched(self):
        """SPEC-0054:UT-04"""
        sandbox = Sandbox()
        self.addCleanup(sandbox.cleanup)
        (sandbox.root / ".claude-plugin").mkdir()
        shutil.copy(PLUGIN_JSON, sandbox.root / ".claude-plugin" / "plugin.json")
        runner = FakeRunner()
        server = attr("Server")(runner=runner, plugin_root=sandbox.root)
        result = result_of(self, server.handle(call("atlas_doctor", {})))
        self.assertIs(result.get("isError"), True)
        expected = sandbox.root / "skills" / "boson-atlas" / "scripts" / "atlas.py"
        self.assertIn(str(expected), text_of(result))
        self.assertEqual(runner.calls, [], "não chama a CLI que não existe")


# --------------------------------------------------------------------------- UT-05

class LegacyEraTest(unittest.TestCase):
    def test_initialize_echoes_a_supported_version(self):
        """SPEC-0054:UT-05"""
        result = result_of(self, new_server().handle(request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})))
        self.assertEqual(result.get("protocolVersion"), "2025-06-18")
        self.assertEqual(result.get("capabilities"), {"tools": {}})
        self.assertEqual(result.get("serverInfo"), {"name": "fermion", "version": plugin_version()})

    def test_each_legacy_version_is_echoed(self):
        """SPEC-0054:UT-05"""
        for version in LEGACY_VERSIONS:
            with self.subTest(version=version):
                result = result_of(self, new_server().handle(request("initialize", {"protocolVersion": version})))
                self.assertEqual(result["protocolVersion"], version)

    def test_unsupported_version_falls_back_to_2025_11_25(self):
        """SPEC-0054:UT-05"""
        for version in ("1999-01-01", MODERN_VERSION):
            with self.subTest(version=version):
                result = result_of(self, new_server().handle(request("initialize", {"protocolVersion": version})))
                self.assertEqual(result["protocolVersion"], "2025-11-25")

    def test_handshake_sequence(self):
        """SPEC-0054:UT-05"""
        server = new_server()
        result_of(self, server.handle(request("initialize", {"protocolVersion": "2025-06-18"}, id=1)))
        self.assertIsNone(server.handle(notification("notifications/initialized")))
        self.assertEqual(result_of(self, server.handle(request("ping", id=2)), id=2), {})
        tools = tools_by_name(self, result_of(self, server.handle(request("tools/list", id=3)), id=3))
        self.assertEqual(sorted(tools), sorted(TOOLS))

    def test_tools_are_served_before_initialize(self):
        """SPEC-0054:UT-05 (cliente legado tolerante)"""
        runner = FakeRunner()
        server = new_server(runner)
        result_of(self, server.handle(request("tools/list")))
        result_of(self, server.handle(call("atlas_config", {}, id=2)), id=2)
        self.assertEqual(len(runner.calls), 1)

    def test_legacy_results_have_no_modern_fields(self):
        """SPEC-0054:UT-05 (v2: respostas legadas seguem o schema legado)"""
        server = new_server()
        responses = [
            server.handle(request("initialize", {"protocolVersion": "2025-11-25"}, id=1)),
            server.handle(request("tools/list", id=2)),
            server.handle(call("atlas_config", {}, id=3)),
            server.handle(request("ping", id=4)),
        ]
        for index, response in enumerate(responses, 1):
            result = result_of(self, response, id=index)
            for field in MODERN_ONLY_FIELDS:
                self.assertNotIn(field, result, f"resposta legada {index} tem {field}")

    def test_notifications_never_get_a_response(self):
        """SPEC-0054:UT-05"""
        server = new_server()
        for method in ("notifications/initialized", "notifications/cancelled", "nao/existe"):
            with self.subTest(method=method):
                self.assertIsNone(server.handle(notification(method, {})))


# --------------------------------------------------------------------------- UT-06

class ModernEraTest(unittest.TestCase):
    def test_server_discover_follows_the_official_discover_result(self):
        """SPEC-0054:UT-06"""
        result = result_of(self, new_server().handle(request("server/discover", meta=modern_meta())))
        self.assertEqual(result.get("resultType"), "complete")
        self.assertCountEqual(result.get("supportedVersions", []), SUPPORTED_VERSIONS)
        self.assertEqual(result.get("capabilities"), {"tools": {}})
        self.assertEqual(result.get("ttlMs"), 3600000)
        self.assertEqual(result.get("cacheScope"), "private")
        self.assertEqual((result.get("_meta") or {}).get(SERVER_INFO_KEY),
                         {"name": "fermion", "version": plugin_version()})
        self.assertNotIn("serverInfo", result, "v2: a identidade fica em _meta, não no topo")

    def test_modern_tools_list_is_cacheable(self):
        """SPEC-0054:UT-06"""
        result = result_of(self, new_server().handle(request("tools/list", meta=modern_meta())))
        self.assertEqual(result.get("resultType"), "complete")
        self.assertEqual(result.get("ttlMs"), 3600000)
        self.assertEqual(result.get("cacheScope"), "private")
        self.assertEqual(sorted(tools_by_name(self, result)), sorted(TOOLS))

    def test_modern_tools_call_has_result_type(self):
        """SPEC-0054:UT-06"""
        runner = FakeRunner(0, '{"ok": true}\n')
        result = result_of(self, new_server(runner).handle(call("atlas_doctor", {}, meta=modern_meta())))
        self.assertEqual(result.get("resultType"), "complete")
        self.assertIs(result.get("isError"), False)
        self.assertEqual(text_of(result), '{"ok": true}\n')
        self.assertEqual(len(runner.calls), 1)

    def test_missing_client_capabilities_is_tolerated(self):
        """SPEC-0054:UT-06"""
        meta = modern_meta(capabilities=False)
        self.assertNotIn(CAPS_KEY, meta)
        server = new_server()
        self.assertEqual(result_of(self, server.handle(request("server/discover", meta=meta))).get("resultType"),
                         "complete")
        result = result_of(self, server.handle(request("tools/list", id=2, meta=meta)), id=2)
        self.assertEqual(result.get("resultType"), "complete")

    def test_unsupported_version_gets_32022_with_supported_and_requested(self):
        """SPEC-0054:UT-06"""
        error = error_of(self, new_server().handle(request("tools/list", meta=modern_meta("1900-01-01"))), -32022)
        self.assertEqual(error.get("message"), "Unsupported protocol version")
        data = error.get("data") or {}
        self.assertCountEqual(data.get("supported", []), SUPPORTED_VERSIONS)
        self.assertEqual(data.get("requested"), "1900-01-01")

    def test_unsupported_version_on_tools_call_opens_no_process(self):
        """SPEC-0054:UT-06"""
        runner = FakeRunner()
        response = new_server(runner).handle(call("atlas_doctor", {}, meta=modern_meta("1900-01-01")))
        error_of(self, response, -32022)
        self.assertEqual(runner.calls, [])

    def test_unsupported_version_on_server_discover(self):
        """SPEC-0054:UT-06"""
        error = error_of(self, new_server().handle(request("server/discover", meta=modern_meta("1900-01-01"))),
                         -32022)
        self.assertEqual(error["data"]["requested"], "1900-01-01")


# --------------------------------------------------------------------------- transporte (unidade)

class TransportUnitTest(unittest.TestCase):
    def test_non_request_objects_get_32600(self):
        """SPEC-0054:IT-03 (unidade: objeto que não é request)"""
        server = new_server()
        for message in ([1, 2], "texto", {"jsonrpc": "2.0", "id": 9}, {"jsonrpc": "1.0", "id": 9, "method": "ping"}):
            with self.subTest(message=message):
                response = server.handle(message)
                self.assertIsNotNone(response)
                self.assertEqual(response.get("error", {}).get("code"), -32600, response)

    def test_null_id_is_an_invalid_request(self):
        """SPEC-0054:IT-03 (unidade: RequestId do schema 2026-07-28 é string ou inteiro, nunca null)"""
        server = new_server()
        for method in ("ping", "tools/list", "nao/existe"):
            with self.subTest(method=method):
                response = server.handle({"jsonrpc": "2.0", "id": None, "method": method})
                self.assertIsNotNone(response, "id null não é notificação")
                self.assertIn("id", response)
                self.assertIsNone(response["id"])
                self.assertNotIn("result", response, response)
                self.assertEqual(response.get("error", {}).get("code"), -32600, response)

    def test_unknown_method_gets_32601_and_the_server_keeps_answering(self):
        """SPEC-0054:IT-03 (unidade)"""
        server = new_server()
        error_of(self, server.handle(request("resources/list", id=5)), -32601, id=5)
        self.assertEqual(result_of(self, server.handle(request("ping", id=6)), id=6), {})


# --------------------------------------------------------------------------- IT-01 a IT-03

class ServerCase(unittest.TestCase):
    def open_server(self, config_home=None):
        server = ServerProcess(self.sandbox, config_home=config_home)
        self.addCleanup(server.close)
        return server

    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)


class SameResultAsCliTest(ServerCase):
    """Atlas de fixture criado pela CLI (init + scan com o coletor falso); o servidor devolve o stdout da CLI."""

    CALLS = (
        ("atlas_context", {"query": "api payments", "hops": 1}, ["context", "--hops", "1", "--json", "--", "api",
                                                                 "payments"]),
        ("atlas_context", {"query": "billing"}, ["context", "--json", "--", "billing"]),
        ("atlas_lint", {}, ["lint", "--json"]),
        ("atlas_lint", {"only": ["pending-convention", "stale"]}, ["lint", "--json", "--only",
                                                                   "pending-convention,stale"]),
        ("atlas_curate_list", {}, ["curate", "list", "--json"]),
        ("atlas_curate_list", {"status": "inferred"}, ["curate", "list", "--json", "--status", "inferred"]),
    )

    def setUp(self):
        super().setUp()
        self.sandbox.fixture_atlas()

    def test_tools_return_the_cli_stdout_within_5_seconds(self):
        """SPEC-0054:IT-01"""
        server = self.open_server()
        response, _ = server.ask(request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                                        "clientInfo": {"name": "it", "version": "0"}}, id=0))
        self.assertEqual(result_of(self, response, id=0)["serverInfo"]["name"], "fermion")
        server.send(notification("notifications/initialized"))
        for index, (name, arguments, cli_args) in enumerate(self.CALLS, 1):
            with self.subTest(tool=name, arguments=arguments):
                response, elapsed = server.ask(call(name, arguments, id=index))
                expected = self.sandbox.cli(*cli_args)
                self.assertIn(expected.returncode, (0, 1) if name == "atlas_lint" else (0,), expected.stderr)
                result = result_of(self, response, id=index)
                self.assertIs(result.get("isError"), False, text_of(result))
                self.assertEqual(text_of(result), expected.stdout)
                self.assertEqual(result.get("structuredContent"), json.loads(expected.stdout))
                self.assertLess(elapsed, RESPONSE_TIMEOUT)

    def test_fixture_has_content_for_each_tool(self):
        """SPEC-0054:IT-01 (a fixture não é vazia: a comparação vale)"""
        context = json.loads(self.sandbox.cli("context", "--json", "--", "api").stdout)
        self.assertEqual(context["services"][0]["key"], "service:api")
        listed = json.loads(self.sandbox.cli("curate", "list", "--json").stdout)
        self.assertTrue(listed["conventions"], "curate list sem convenções na fixture")

    def test_modern_call_returns_the_same_text(self):
        """SPEC-0054:IT-01 (era moderna)"""
        server = self.open_server()
        response, elapsed = server.ask(call("atlas_curate_list", {"status": "inferred"}, id=7, meta=modern_meta()))
        expected = self.sandbox.cli("curate", "list", "--json", "--status", "inferred")
        result = result_of(self, response, id=7)
        self.assertEqual(result.get("resultType"), "complete")
        self.assertEqual(text_of(result), expected.stdout)
        self.assertLess(elapsed, RESPONSE_TIMEOUT)


class NotConfiguredTest(ServerCase):
    def test_doctor_without_configuration_points_to_onboarding(self):
        """SPEC-0054:IT-02"""
        empty = self.sandbox.root / "empty-config-home"
        empty.mkdir()
        server = self.open_server(config_home=empty)
        response, _ = server.ask(call("atlas_doctor", {}, id=1))
        result = result_of(self, response)
        self.assertIs(result.get("isError"), True)
        self.assertIn(NOT_CONFIGURED, text_of(result))
        self.assertEqual(list(empty.iterdir()), [], "o servidor não grava configuração")


class TransportTest(ServerCase):
    def test_bad_lines_do_not_stop_the_server_and_eof_exits_0(self):
        """SPEC-0054:IT-03"""
        server = self.open_server()
        server.send_line("{isto não é json")
        server.send(request("nao/existe", id=2))
        server.send(notification("notifications/initialized"))
        server.send(request("ping", id=3))
        first, _ = server.receive()
        self.assertEqual(first.get("jsonrpc"), "2.0")
        self.assertIn("id", first)
        self.assertIsNone(first["id"])
        self.assertEqual(first.get("error", {}).get("code"), -32700, first)
        second, _ = server.receive()
        error_of(self, second, -32601, id=2)
        third, _ = server.receive()
        self.assertEqual(result_of(self, third, id=3), {}, "a notificação recebeu resposta ou o ping falhou")
        server.close_stdin()
        self.assertEqual(server.rest_of_stdout(), [], "o servidor escreveu algo além das respostas")
        self.assertEqual(server.proc.wait(timeout=10), 0, server.stderr())

    def test_stdout_carries_only_protocol_lines(self):
        """SPEC-0054:IT-03 (stdout reservado ao protocolo)"""
        server = self.open_server()
        server.send_line("")
        server.send_line("[")
        server.send(request("ping", id=1))
        start = time.monotonic()
        responses = []
        while True:
            response, _ = server.receive()
            responses.append(response)
            if response.get("id") == 1 or time.monotonic() - start > RESPONSE_TIMEOUT:
                break
        self.assertEqual(responses[-1].get("result"), {}, responses)
        for response in responses[:-1]:
            self.assertEqual(response.get("error", {}).get("code"), -32700, response)
        server.close_stdin()
        self.assertEqual(server.rest_of_stdout(), [])
        self.assertEqual(server.proc.wait(timeout=10), 0, server.stderr())


    def assert_parse_error_then_ping(self, server, ping_id):
        response, _ = server.receive()
        self.assertEqual(response.get("jsonrpc"), "2.0", response)
        self.assertIn("id", response)
        self.assertIsNone(response["id"], response)
        self.assertEqual(response.get("error", {}).get("code"), -32700, response)
        server.send(request("ping", id=ping_id))
        response, _ = server.receive()
        self.assertEqual(result_of(self, response, id=ping_id), {}, "o servidor parou de responder")

    def finish(self, server):
        server.close_stdin()
        self.assertEqual(server.rest_of_stdout(), [], "o servidor escreveu algo além das respostas")
        code = server.proc.wait(timeout=10)
        stderr = server.stderr()
        self.assertEqual(code, 0, stderr)
        self.assertNotIn("Traceback", stderr)

    def test_deeply_nested_json_is_a_parse_error(self):
        """SPEC-0054:IT-03 (JSON aninhado demais não derruba o servidor)"""
        server = self.open_server()
        server.send_line("[" * 100000)
        self.assert_parse_error_then_ping(server, 1)
        depth = 3000
        params = '{"a": ' + "[" * depth + "]" * depth + "}"
        server.send_line('{"jsonrpc": "2.0", "id": 2, "method": "ping", "params": ' + params + "}")
        self.assert_parse_error_then_ping(server, 3)
        self.finish(server)

    def test_line_that_is_not_utf8_is_a_parse_error(self):
        """SPEC-0054:IT-03 (bytes que não são UTF-8 não derrubam o servidor)"""
        server = self.open_server()
        server.send_bytes(b"\xff\xfe{}\n")
        self.assert_parse_error_then_ping(server, 1)
        server.send_bytes(b'{"jsonrpc": "2.0", "id": 2, "method": "\xc3\x28"}\n')
        self.assert_parse_error_then_ping(server, 3)
        self.finish(server)

    def test_control_characters_in_a_method_do_not_forge_log_lines(self):
        """SPEC-0054:IT-03 (stderr: uma linha por erro, sem o texto injetado)"""
        server = self.open_server()
        before = server.stderr()
        response, _ = server.ask(request("x\nINJETADO linha falsa\r\x1b[31m", id=1))
        error_of(self, response, -32601, id=1)
        self.finish(server)
        log = server.stderr()[len(before):]
        self.assertLessEqual(log.count("\n"), 1, f"mais de uma linha no stderr: {log!r}")
        self.assertNotIn("INJETADO", log)
        self.assertNotIn("\x1b", log)
        self.assertNotIn("\r", log)


if __name__ == "__main__":
    unittest.main()
