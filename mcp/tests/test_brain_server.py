"""Tools brain_* de leitura do segundo cérebro no servidor MCP fermion (SPEC-0059: UT-01 a UT-04, IT-01 a IT-03;
ADR-0017, ADR-0014). UT-05 fica em test_architecture.py.

Run: python3 -m unittest discover -s mcp/tests

Interface que estes testes exigem de mcp/fermion_mcp.py (seção 6 da SPEC-0059), além da SPEC-0054:

    tools/list traz as atlas_* e as oito brain_* (BRAIN_TOOLS), cada uma com description, inputSchema object com
    additionalProperties: false e annotations.readOnlyHint: true.

    argv de cada brain_* = [<python>, "<plugin_root>/skills/photon-brain/scripts/brain.py", <comando>...], com
    timeout=120, e <comando>... exatamente:
        brain_config       config --json
        brain_doctor       doctor --json
        brain_search       search [--context C] [--type T] [--tag G] [--limit L] --json -- <query.split()>
        brain_related      related (--note=N | --text=X) [--limit L] --json
        brain_links        links --json -- <note>
        brain_context      context [--context C] [--hops H] [--limit L] [--max-chars M] --json -- <query.split()>
        brain_inbox_list   inbox list --json
        brain_lint         lint --json [--only a,b]
    Nunca --include-confidential.

    Saída: exit 0 (e 1 em brain_doctor/brain_lint com stdout JSON objeto) → isError false, texto = stdout,
    structuredContent = stdout se for objeto JSON; exit 3 → BRAIN_NOT_CONFIGURED + stderr; outro exit → código e
    stderr; timeout → BRAIN_TIMEOUT_TEXT; CLI ausente → caminho procurado.

Os IT abrem o servidor real por stdio com HOME, ATLAS_CONFIG_HOME e BRAIN_CONFIG_HOME temporários (Sandbox) e um
vault criado pela própria CLI da photon-brain (Sandbox.fixture_vault); nunca a configuração real da máquina.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from helpers import (
    BRAIN_CLI,
    BRAIN_NOT_CONFIGURED,
    BRAIN_TIMEOUT_TEXT,
    BRAIN_TOOLS,
    CLI_TIMEOUT,
    OTHER_NOTE,
    PLUGIN_JSON,
    PUBLIC_NOTE,
    RESPONSE_TIMEOUT,
    SECRET_MARKER,
    SECRET_NOTE,
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

INCLUDE_CONFIDENTIAL = "--include-confidential"
CONTROL_SAMPLES = ("a\x00b", "a\x01", "a \x1b[31m", "\x1fa", "a\x7f")


def brain_names(tools):
    return sorted(name for name in tools if name.startswith("brain_"))


# --------------------------------------------------------------------------- UT-01

class BrainToolsListTest(unittest.TestCase):
    def setUp(self):
        self.tools = tools_by_name(self, result_of(self, new_server().handle(request("tools/list"))))

    def brain_tool(self, name):
        self.assertIn(name, self.tools, f"tools/list sem {name}")
        return self.tools[name]

    def props(self, name):
        return self.brain_tool(name)["inputSchema"].get("properties", {})

    def assert_string(self, prop, low, high):
        self.assertEqual((prop.get("type"), prop.get("minLength"), prop.get("maxLength")), ("string", low, high))

    def assert_integer(self, prop, low, high):
        self.assertEqual((prop.get("type"), prop.get("minimum"), prop.get("maximum")), ("integer", low, high))

    def test_the_eight_brain_tools_and_the_five_atlas_tools(self):
        """SPEC-0059:UT-01"""
        self.assertEqual(brain_names(self.tools), sorted(BRAIN_TOOLS))
        self.assertEqual(sorted(n for n in self.tools if n.startswith("atlas_")), sorted(TOOLS))

    def test_both_eras_list_the_brain_tools(self):
        """SPEC-0059:UT-01 (era legada depois do initialize e era moderna)"""
        server = new_server()
        result_of(self, server.handle(request("initialize", {"protocolVersion": "2025-11-25"}, id=1)), id=1)
        legacy = tools_by_name(self, result_of(self, server.handle(request("tools/list", id=2)), id=2))
        modern = tools_by_name(self, result_of(self, new_server().handle(request("tools/list", meta=modern_meta()))))
        self.assertEqual(brain_names(legacy), sorted(BRAIN_TOOLS))
        self.assertEqual(brain_names(modern), sorted(BRAIN_TOOLS))

    def test_every_brain_tool_has_description_closed_schema_and_read_only_hint(self):
        """SPEC-0059:UT-01"""
        for name in BRAIN_TOOLS:
            with self.subTest(tool=name):
                tool = self.brain_tool(name)
                self.assertIsInstance(tool.get("description"), str)
                self.assertTrue(tool["description"].strip(), "description vazia")
                schema = tool.get("inputSchema")
                self.assertIsInstance(schema, dict)
                self.assertEqual(schema.get("type"), "object")
                self.assertIs(schema.get("additionalProperties"), False)
                self.assertIs((tool.get("annotations") or {}).get("readOnlyHint"), True)

    def test_config_doctor_and_inbox_list_take_no_arguments(self):
        """SPEC-0059:UT-01"""
        for name in ("brain_config", "brain_doctor", "brain_inbox_list"):
            with self.subTest(tool=name):
                schema = self.brain_tool(name)["inputSchema"]
                self.assertEqual(schema.get("properties", {}), {})
                self.assertEqual(schema.get("required", []), [])

    def test_search_schema_has_the_contract_ranges(self):
        """SPEC-0059:UT-01"""
        schema = self.brain_tool("brain_search")["inputSchema"]
        self.assertEqual(schema.get("required"), ["query"])
        props = schema["properties"]
        self.assertEqual(sorted(props), ["context", "limit", "query", "tag", "type"])
        for key, low, high in (("query", 1, 500), ("context", 1, 100), ("type", 1, 50), ("tag", 1, 100)):
            with self.subTest(prop=key):
                self.assert_string(props[key], low, high)
        self.assert_integer(props["limit"], 1, 100)

    def test_related_schema_has_note_and_text_optional_and_says_exactly_one(self):
        """SPEC-0059:UT-01"""
        tool = self.brain_tool("brain_related")
        schema = tool["inputSchema"]
        self.assertEqual(schema.get("required", []), [])
        props = schema["properties"]
        self.assertEqual(sorted(props), ["limit", "note", "text"])
        self.assert_string(props["note"], 1, 500)
        self.assert_string(props["text"], 1, 2000)
        self.assert_integer(props["limit"], 1, 100)
        descriptions = " ".join(str(d) for d in (tool.get("description"), schema.get("description")) if d)
        self.assertIn("exatamente um de note ou text", descriptions.lower())

    def test_links_schema_requires_the_note(self):
        """SPEC-0059:UT-01"""
        schema = self.brain_tool("brain_links")["inputSchema"]
        self.assertEqual(schema.get("required"), ["note"])
        self.assertEqual(sorted(schema["properties"]), ["note"])
        self.assert_string(schema["properties"]["note"], 1, 500)

    def test_context_schema_has_the_contract_ranges(self):
        """SPEC-0059:UT-01"""
        schema = self.brain_tool("brain_context")["inputSchema"]
        self.assertEqual(schema.get("required"), ["query"])
        props = schema["properties"]
        self.assertEqual(sorted(props), ["context", "hops", "limit", "max_chars", "query"])
        self.assert_string(props["query"], 1, 500)
        self.assert_string(props["context"], 1, 100)
        for key, low, high in (("hops", 0, 2), ("limit", 1, 50), ("max_chars", 500, 200000)):
            with self.subTest(prop=key):
                self.assert_integer(props[key], low, high)

    def test_lint_schema_takes_an_optional_list_of_rule_names(self):
        """SPEC-0059:UT-01"""
        schema = self.brain_tool("brain_lint")["inputSchema"]
        self.assertEqual(schema.get("required", []), [])
        self.assertEqual(sorted(schema["properties"]), ["only"])
        only = schema["properties"]["only"]
        self.assertEqual((only["type"], only["items"]["type"]), ("array", "string"))
        pattern = only["items"]["pattern"]
        for good in ("broken-link", "orphan", "secret-in-note"):
            self.assertTrue(accepts(pattern, good), f"{pattern} recusa {good}")
        for bad in ("Bad", "broken link", "a,b", "", "x;rm"):
            self.assertFalse(accepts(pattern, bad), f"{pattern} aceita {bad!r}")

    def test_every_string_follows_the_query_pattern_of_spec_0054(self):
        """SPEC-0059:UT-01 (sem caracteres de controle, exceto tab, LF e CR)"""
        for name in BRAIN_TOOLS:
            for key, prop in self.props(name).items():
                if prop.get("type") != "string":
                    continue
                with self.subTest(tool=name, prop=key):
                    pattern = prop.get("pattern")
                    self.assertIsInstance(pattern, str, "string sem pattern")
                    self.assertTrue(accepts(pattern, "a\tb\nc\rd"), f"{pattern} recusa tab/LF/CR")
                    for bad in CONTROL_SAMPLES:
                        self.assertFalse(accepts(pattern, bad), f"{pattern} aceita {bad!r}")


# --------------------------------------------------------------------------- UT-02

INVALID_BRAIN_CALLS = [
    ("search sem query", "brain_search", {}),
    ("context com hops 3", "brain_context", {"query": "api", "hops": 3}),
    ("related com note e text", "brain_related", {"note": "a", "text": "b"}),
    ("related sem note nem text", "brain_related", {}),
    ("related só com limit", "brain_related", {"limit": 3}),
    ("lint com regra Bad", "brain_lint", {"only": ["Bad"]}),
    ("search com query só de espaços", "brain_search", {"query": "   "}),
    ("search com query só de tab e quebra", "brain_search", {"query": "\t\n\r "}),
    ("context com query só de espaços", "brain_context", {"query": "  "}),
    ("search com chave extra", "brain_search", {"query": "api", "include_confidential": True}),
    ("search com query vazia", "brain_search", {"query": ""}),
    ("search com query de 501", "brain_search", {"query": "a" * 501}),
    ("search com context vazio", "brain_search", {"query": "api", "context": ""}),
    ("search com context de 101", "brain_search", {"query": "api", "context": "c" * 101}),
    ("search com type de 51", "brain_search", {"query": "api", "type": "t" * 51}),
    ("search com tag de 101", "brain_search", {"query": "api", "tag": "g" * 101}),
    ("search com limit 0", "brain_search", {"query": "api", "limit": 0}),
    ("search com limit 101", "brain_search", {"query": "api", "limit": 101}),
    ("search com limit booleano", "brain_search", {"query": "api", "limit": True}),
    ("search com query não texto", "brain_search", {"query": 7}),
    ("search com query com NUL", "brain_search", {"query": "api\x00rm"}),
    ("search com tag com ESC", "brain_search", {"query": "api", "tag": "x\x1b[31m"}),
    ("related com note vazia", "brain_related", {"note": ""}),
    ("related com note de 501", "brain_related", {"note": "n" * 501}),
    ("related com text de 2001", "brain_related", {"text": "t" * 2001}),
    ("related com limit 101", "brain_related", {"text": "x", "limit": 101}),
    ("related com chave extra", "brain_related", {"text": "x", "include_confidential": True}),
    ("related com note com DEL", "brain_related", {"note": "a\x7f"}),
    ("links sem note", "brain_links", {}),
    ("links com note vazia", "brain_links", {"note": ""}),
    ("links com note de 501", "brain_links", {"note": "n" * 501}),
    ("links com chave extra", "brain_links", {"note": "a", "backlinks": True}),
    ("context sem query", "brain_context", {}),
    ("context com hops -1", "brain_context", {"query": "api", "hops": -1}),
    ("context com limit 51", "brain_context", {"query": "api", "limit": 51}),
    ("context com max_chars 499", "brain_context", {"query": "api", "max_chars": 499}),
    ("context com max_chars 200001", "brain_context", {"query": "api", "max_chars": 200001}),
    ("context com context de 101", "brain_context", {"query": "api", "context": "c" * 101}),
    ("lint com only texto", "brain_lint", {"only": "orphan"}),
    ("lint com item não texto", "brain_lint", {"only": [1]}),
    ("config com chave extra", "brain_config", {"verbose": True}),
    ("doctor com chave extra", "brain_doctor", {"fix": True}),
    ("inbox_list com chave extra", "brain_inbox_list", {"all": True}),
    ("arguments não é objeto", "brain_search", ["api"]),
    ("tool que grava: capture", "brain_capture", {"text": "x"}),
    ("tool que grava: new_note", "brain_new_note", {"title": "x"}),
    ("tool que grava: inbox_done", "brain_inbox_done", {"item": "inbox/x.md"}),
]


class BrainInvalidArgumentsTest(unittest.TestCase):
    def setUp(self):
        tools = tools_by_name(self, result_of(self, new_server().handle(request("tools/list"))))
        self.assertEqual(brain_names(tools), sorted(BRAIN_TOOLS), "tools brain_* ausentes do tools/list")

    def test_each_invalid_call_gets_32602_and_opens_no_process(self):
        """SPEC-0059:UT-02"""
        for label, name, arguments in INVALID_BRAIN_CALLS:
            with self.subTest(caso=label):
                runner = FakeRunner()
                error_of(self, new_server(runner).handle(call(name, arguments)), -32602)
                self.assertEqual(runner.calls, [], f"{label}: a CLI foi chamada")

    def test_valid_limits_are_accepted(self):
        """SPEC-0059:UT-02 (as bordas das faixas valem)"""
        valid = [
            ("brain_search", {"query": "a", "context": "c", "type": "t", "tag": "g", "limit": 1}),
            ("brain_search", {"query": "a" * 500, "context": "c" * 100, "type": "t" * 50, "tag": "g" * 100,
                              "limit": 100}),
            ("brain_related", {"note": "n" * 500, "limit": 100}),
            ("brain_related", {"text": "t" * 2000, "limit": 1}),
            ("brain_links", {"note": "n" * 500}),
            ("brain_context", {"query": "a", "hops": 0, "limit": 1, "max_chars": 500}),
            ("brain_context", {"query": "a" * 500, "context": "c" * 100, "hops": 2, "limit": 50,
                               "max_chars": 200000}),
            ("brain_lint", {"only": []}),
            ("brain_lint", {"only": ["broken-link", "orphan"]}),
        ]
        for name, arguments in valid:
            with self.subTest(tool=name, arguments={k: v if not isinstance(v, str) else len(v)
                                                    for k, v in arguments.items()}):
                runner = FakeRunner()
                result_of(self, new_server(runner).handle(call(name, arguments)))
                self.assertEqual(len(runner.calls), 1)


# --------------------------------------------------------------------------- UT-03

class BrainCommandLineTest(unittest.TestCase):
    def run_tool(self, name, arguments=None):
        runner = FakeRunner()
        result_of(self, new_server(runner).handle(call(name, arguments if arguments is not None else {})))
        self.assertEqual(len(runner.calls), 1, f"{name} não chamou a CLI uma vez")
        argv, timeout = runner.calls[0]
        self.assertIsInstance(argv, list)
        self.assertTrue(all(isinstance(a, str) for a in argv), argv)
        self.assertTrue(Path(argv[0]).name.startswith("python"), f"executável não é python: {argv[0]}")
        self.assertEqual(Path(argv[1]).resolve(), BRAIN_CLI.resolve())
        self.assertEqual(timeout, CLI_TIMEOUT)
        return argv[2:]

    def test_search_free_text_goes_after_double_dash(self):
        """SPEC-0059:UT-03"""
        args = self.run_tool("brain_search", {"query": "-rf --include-confidential; x"})
        self.assertEqual(args[-5:], ["--json", "--", "-rf", "--include-confidential;", "x"])
        self.assertEqual(args, ["search", "--json", "--", "-rf", "--include-confidential;", "x"])

    def test_links_note_goes_after_double_dash(self):
        """SPEC-0059:UT-03"""
        args = self.run_tool("brain_links", {"note": "--json"})
        self.assertEqual(args, ["links", "--json", "--", "--json"])

    def test_links_note_with_spaces_and_quotes_is_one_argument(self):
        """SPEC-0059:UT-03"""
        args = self.run_tool("brain_links", {"note": "Payments \"API\"; rm -rf"})
        self.assertEqual(args, ["links", "--json", "--", "Payments \"API\"; rm -rf"])

    def test_related_note_is_glued_to_its_option(self):
        """SPEC-0059:UT-03"""
        args = self.run_tool("brain_related", {"note": "-x"})
        self.assertIn("--note=-x", args)
        self.assertEqual(args, ["related", "--note=-x", "--json"])

    def test_related_text_is_glued_to_its_option(self):
        """SPEC-0059:UT-03"""
        args = self.run_tool("brain_related", {"text": "--include-confidential a; 'b'", "limit": 3})
        self.assertEqual(args, ["related", "--text=--include-confidential a; 'b'", "--limit", "3", "--json"])

    def test_context_never_becomes_context_add(self):
        """SPEC-0059:UT-03 ('context add' cria contexto)"""
        args = self.run_tool("brain_context", {"query": "add x"})
        self.assertEqual(args[0], "context")
        self.assertNotEqual(args[1], "add")
        self.assertTrue(args[1].startswith("--"), args)
        self.assertEqual(args[-3:], ["--", "add", "x"])
        self.assertEqual(args, ["context", "--json", "--", "add", "x"])

    def test_options_come_before_json_and_double_dash(self):
        """SPEC-0059:UT-03"""
        cases = [
            ("brain_search", {"query": "api payments", "context": "college", "type": "note", "tag": "api",
                              "limit": 5},
             ["search", "--context", "college", "--type", "note", "--tag", "api", "--limit", "5", "--json", "--",
              "api", "payments"]),
            ("brain_context", {"query": "a\tb\nc\rd", "context": "college", "hops": 2, "limit": 5,
                               "max_chars": 1000},
             ["context", "--context", "college", "--hops", "2", "--limit", "5", "--max-chars", "1000", "--json",
              "--", "a", "b", "c", "d"]),
        ]
        for name, arguments, expected in cases:
            with self.subTest(tool=name):
                self.assertEqual(self.run_tool(name, arguments), expected)

    def test_command_line_of_each_other_tool(self):
        """SPEC-0059:UT-03"""
        cases = [
            ("brain_config", {}, ["config", "--json"]),
            ("brain_doctor", {}, ["doctor", "--json"]),
            ("brain_inbox_list", {}, ["inbox", "list", "--json"]),
            ("brain_lint", {}, ["lint", "--json"]),
            ("brain_lint", {"only": ["broken-link", "orphan"]}, ["lint", "--json", "--only", "broken-link,orphan"]),
            ("brain_related", {"note": "Payments API", "limit": 2}, ["related", "--note=Payments API", "--limit",
                                                                      "2", "--json"]),
        ]
        for name, arguments, expected in cases:
            with self.subTest(tool=name, arguments=arguments):
                self.assertEqual(self.run_tool(name, arguments), expected)

    def test_no_brain_command_line_asks_for_confidential_notes(self):
        """SPEC-0059:UT-03 (nenhuma linha de comando tem --include-confidential antes do --)"""
        cases = [
            ("brain_config", {}),
            ("brain_doctor", {}),
            ("brain_search", {"query": "-rf --include-confidential; x", "context": "college", "type": "note",
                              "tag": "api", "limit": 5}),
            ("brain_related", {"note": "-x"}),
            ("brain_related", {"text": "segredo", "limit": 4}),
            ("brain_links", {"note": "--include-confidential"}),
            ("brain_context", {"query": "add x --include-confidential", "context": "college", "hops": 1,
                               "limit": 3, "max_chars": 900}),
            ("brain_inbox_list", {}),
            ("brain_lint", {"only": ["broken-link"]}),
        ]
        for name, arguments in cases:
            with self.subTest(tool=name, arguments=arguments):
                args = self.run_tool(name, arguments)
                options = args[:args.index("--")] if "--" in args else args
                self.assertFalse(any(a == INCLUDE_CONFIDENTIAL or a.startswith(INCLUDE_CONFIDENTIAL + "=")
                                     for a in options), args)

    def test_default_runner_uses_an_argument_list_without_shell(self):
        """SPEC-0059:UT-03 (sem shell)"""
        module = server_module()
        done = subprocess.CompletedProcess(["x"], 0, stdout="{}", stderr="")
        with mock.patch.object(module.subprocess, "run", return_value=done) as run:
            server = attr("Server")()
            result_of(self, server.handle(call("brain_search", {"query": "-rf ; rm"})))
        self.assertEqual(run.call_count, 1)
        args, kwargs = run.call_args
        argv = args[0] if args else kwargs.get("args")
        self.assertIsInstance(argv, list)
        self.assertEqual(Path(argv[1]).resolve(), BRAIN_CLI.resolve())
        self.assertEqual(argv[2:], ["search", "--json", "--", "-rf", ";", "rm"])
        self.assertFalse(kwargs.get("shell", False), "shell precisa ficar desligado")
        self.assertEqual(kwargs.get("timeout"), CLI_TIMEOUT)


# --------------------------------------------------------------------------- UT-04

REPORT = json.dumps({"version": "x", "items": [{"status": "ERRO", "item": "vault", "detail": "x"}], "ok": False},
                    ensure_ascii=False, indent=2) + "\n"


class BrainOutputMappingTest(unittest.TestCase):
    def result(self, name, runner, arguments=None):
        return result_of(self, new_server(runner).handle(call(name, arguments or {})))

    def test_exit_0_gives_text_and_structured_content(self):
        """SPEC-0059:UT-04"""
        stdout = json.dumps({"query": "api", "results": [], "confidential_omitted": 0}, indent=2) + "\n"
        result = self.result("brain_search", FakeRunner(0, stdout), {"query": "api"})
        self.assertEqual(text_of(result), stdout)
        self.assertEqual(result.get("structuredContent"), json.loads(stdout))
        self.assertIs(result.get("isError"), False)

    def test_structured_content_only_for_a_json_object(self):
        """SPEC-0059:UT-04"""
        for stdout in ('["a"]\n', "texto\n", "7\n", ""):
            with self.subTest(stdout=stdout):
                result = self.result("brain_config", FakeRunner(0, stdout))
                self.assertEqual(text_of(result) if result.get("content") else "", stdout)
                self.assertNotIn("structuredContent", result)
                self.assertIs(result.get("isError"), False)

    def test_exit_1_with_a_json_report_in_doctor_and_lint_is_not_an_error(self):
        """SPEC-0059:UT-04"""
        for name in ("brain_doctor", "brain_lint"):
            with self.subTest(tool=name):
                result = self.result(name, FakeRunner(1, REPORT, ""))
                self.assertIs(result.get("isError"), False)
                self.assertEqual(text_of(result), REPORT)
                self.assertEqual(result.get("structuredContent"), json.loads(REPORT))

    def test_exit_1_without_a_json_report_is_an_error_with_the_stderr(self):
        """SPEC-0059:UT-04 (erro de leitura do vault: OSError ou BrainError da CLI)"""
        stderr = "erro: [Errno 13] Permission denied: 'vault/index.md'\n"
        cases = [
            ("brain_doctor", {}, ""),
            ("brain_lint", {}, ""),
            ("brain_doctor", {}, '["não é objeto"]\n'),
            ("brain_search", {"query": "api"}, ""),
            ("brain_context", {"query": "api"}, ""),
        ]
        for name, arguments, stdout in cases:
            with self.subTest(tool=name, stdout=stdout):
                result = self.result(name, FakeRunner(1, stdout, stderr), arguments)
                self.assertIs(result.get("isError"), True)
                self.assertIn(stderr.strip(), text_of(result))
                self.assertNotIn("structuredContent", result)

    def test_exit_2_is_an_error_with_the_stderr(self):
        """SPEC-0059:UT-04 (lint com regra desconhecida, nota não encontrada, nota confidencial recusada)"""
        cases = [
            ("brain_lint", {"only": ["nope"]}, "erro: regra desconhecida: nope — regras: broken-link, orphan\n"),
            ("brain_links", {"note": "Nada"}, "erro: nota não encontrada: Nada\n"),
            ("brain_links", {"note": "Plano"},
             "erro: nota confidencial — use --include-confidential só se a pessoa pedir para incluí-la\n"),
            ("brain_related", {"note": "Plano"},
             "erro: nota confidencial — use --include-confidential só se a pessoa pedir para incluí-la\n"),
        ]
        for name, arguments, stderr in cases:
            with self.subTest(tool=name, stderr=stderr):
                result = self.result(name, FakeRunner(2, "", stderr), arguments)
                self.assertIs(result.get("isError"), True)
                self.assertIn(stderr.strip(), text_of(result))
                self.assertNotIn("structuredContent", result)

    def test_exit_3_points_to_onboarding_with_the_cli_stderr(self):
        """SPEC-0059:UT-04"""
        stderr = "erro: second-brain não configurado nesta máquina — rode init (ou init --join)\n"
        for name, arguments in (("brain_doctor", {}), ("brain_search", {"query": "x"}), ("brain_lint", {})):
            with self.subTest(tool=name):
                result = self.result(name, FakeRunner(3, "", stderr), arguments)
                self.assertIs(result.get("isError"), True)
                text = text_of(result)
                self.assertIn(BRAIN_NOT_CONFIGURED, text)
                self.assertIn(stderr.strip(), text)
                self.assertNotIn("structuredContent", result)

    def test_other_exit_gives_the_code_and_the_stderr(self):
        """SPEC-0059:UT-04"""
        result = self.result("brain_config", FakeRunner(4, "{}", "erro: inesperado\n"))
        self.assertIs(result.get("isError"), True)
        text = text_of(result)
        self.assertRegex(text, r"\b4\b")
        self.assertIn("erro: inesperado", text)
        self.assertNotIn("structuredContent", result)

    def test_timeout_is_an_error_result(self):
        """SPEC-0059:UT-04"""
        runner = FakeRunner(raises=subprocess.TimeoutExpired(["python3"], CLI_TIMEOUT))
        result = self.result("brain_doctor", runner)
        self.assertIs(result.get("isError"), True)
        self.assertIn(BRAIN_TIMEOUT_TEXT, text_of(result))

    def test_missing_python_names_the_path_searched(self):
        """SPEC-0059:UT-04 (FileNotFoundError)"""
        runner = FakeRunner(raises=FileNotFoundError(2, "No such file or directory", "python3"))
        result = self.result("brain_doctor", runner)
        self.assertIs(result.get("isError"), True)
        self.assertIn(runner.calls[0][0][0], text_of(result), "o texto precisa citar o caminho procurado")

    def test_other_os_error_is_an_error_result(self):
        """SPEC-0059:UT-04 (OSError)"""
        runner = FakeRunner(raises=PermissionError(13, "Permission denied", "python3"))
        result = self.result("brain_inbox_list", runner)
        self.assertIs(result.get("isError"), True)
        self.assertTrue(text_of(result).strip())

    def test_missing_cli_names_the_path_searched(self):
        """SPEC-0059:UT-04 (CLI ausente)"""
        sandbox = Sandbox()
        self.addCleanup(sandbox.cleanup)
        (sandbox.root / ".claude-plugin").mkdir()
        shutil.copy(PLUGIN_JSON, sandbox.root / ".claude-plugin" / "plugin.json")
        runner = FakeRunner()
        server = attr("Server")(runner=runner, plugin_root=sandbox.root)
        result = result_of(self, server.handle(call("brain_doctor", {})))
        self.assertIs(result.get("isError"), True)
        expected = sandbox.root / "skills" / "photon-brain" / "scripts" / "brain.py"
        self.assertIn(str(expected), text_of(result))
        self.assertEqual(runner.calls, [], "não chama a CLI que não existe")

    def test_modern_call_has_result_type(self):
        """SPEC-0059:UT-04 (era moderna)"""
        runner = FakeRunner(0, '{"items": []}\n')
        result = result_of(self, new_server(runner).handle(call("brain_inbox_list", {}, meta=modern_meta())))
        self.assertEqual(result.get("resultType"), "complete")
        self.assertIs(result.get("isError"), False)
        self.assertEqual(result.get("structuredContent"), {"items": []})


# --------------------------------------------------------------------------- IT-01 a IT-03

class BrainServerCase(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)

    def open_server(self, brain_config_home=None):
        server = ServerProcess(self.sandbox, brain_config_home=brain_config_home)
        self.addCleanup(server.close)
        return server

    def ask(self, server, name, arguments, id):
        response, elapsed = server.ask(call(name, arguments, id=id))
        return result_of(self, response, id=id), elapsed


class BrainSameResultAsCliTest(BrainServerCase):
    """Vault de fixture criado pela CLI (init + new-note); o servidor devolve o stdout da CLI."""

    CALLS = (
        ("brain_search", {"query": "payments plan"}, ["search", "--json", "--", "payments", "plan"]),
        ("brain_search", {"query": "payments", "context": "college", "tag": "api", "limit": 5},
         ["search", "--context", "college", "--tag", "api", "--limit", "5", "--json", "--", "payments"]),
        ("brain_context", {"query": "payments plan"}, ["context", "--json", "--", "payments", "plan"]),
        ("brain_context", {"query": "billing", "hops": 2, "limit": 3, "max_chars": 5000},
         ["context", "--hops", "2", "--limit", "3", "--max-chars", "5000", "--json", "--", "billing"]),
        ("brain_links", {"note": PUBLIC_NOTE}, ["links", "--json", "--", PUBLIC_NOTE]),
        ("brain_links", {"note": OTHER_NOTE}, ["links", "--json", "--", OTHER_NOTE]),
        ("brain_lint", {}, ["lint", "--json"]),
        ("brain_lint", {"only": ["broken-link", "orphan"]}, ["lint", "--json", "--only", "broken-link,orphan"]),
    )

    def setUp(self):
        super().setUp()
        self.sandbox.fixture_vault()

    def test_tools_return_the_cli_stdout_within_5_seconds(self):
        """SPEC-0059:IT-01"""
        server = self.open_server()
        response, _ = server.ask(request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                                        "clientInfo": {"name": "it", "version": "0"}}, id=0))
        result_of(self, response, id=0)
        server.send(notification("notifications/initialized"))
        for index, (name, arguments, cli_args) in enumerate(self.CALLS, 1):
            with self.subTest(tool=name, arguments=arguments):
                result, elapsed = self.ask(server, name, arguments, index)
                expected = self.sandbox.brain_cli(*cli_args)
                self.assertIn(expected.returncode, (0, 1) if name == "brain_lint" else (0,), expected.stderr)
                self.assertIs(result.get("isError"), False, text_of(result))
                self.assertEqual(text_of(result), expected.stdout)
                self.assertEqual(result.get("structuredContent"), json.loads(expected.stdout))
                self.assertLess(elapsed, RESPONSE_TIMEOUT)

    def test_fixture_has_content_for_each_tool(self):
        """SPEC-0059:IT-01 (a fixture não é vazia: a comparação vale)"""
        search = json.loads(self.sandbox.brain_cli("search", "--json", "--", "payments").stdout)
        self.assertIn(PUBLIC_NOTE, [r["title"] for r in search["results"]])
        links = json.loads(self.sandbox.brain_cli("links", "--json", "--", PUBLIC_NOTE).stdout)
        self.assertTrue(links["outgoing"] and links["backlinks"], links)
        lint = json.loads(self.sandbox.brain_cli("lint", "--json").stdout)
        self.assertIn("broken-link", [f["rule"] for f in lint["findings"]], "a fixture tem um link quebrado")

    def test_modern_call_returns_the_same_text(self):
        """SPEC-0059:IT-01 (era moderna)"""
        server = self.open_server()
        response, elapsed = server.ask(call("brain_links", {"note": PUBLIC_NOTE}, id=7, meta=modern_meta()))
        expected = self.sandbox.brain_cli("links", "--json", "--", PUBLIC_NOTE)
        result = result_of(self, response, id=7)
        self.assertEqual(result.get("resultType"), "complete")
        self.assertEqual(text_of(result), expected.stdout)
        self.assertLess(elapsed, RESPONSE_TIMEOUT)


class BrainNotConfiguredTest(BrainServerCase):
    def test_doctor_without_configuration_points_to_onboarding(self):
        """SPEC-0059:IT-02"""
        empty = self.sandbox.root / "empty-brain-config-home"
        empty.mkdir()
        server = self.open_server(brain_config_home=empty)
        result, elapsed = self.ask(server, "brain_doctor", {}, 1)
        self.assertIs(result.get("isError"), True)
        self.assertIn(BRAIN_NOT_CONFIGURED, text_of(result))
        self.assertLess(elapsed, RESPONSE_TIMEOUT)
        self.assertEqual(list(empty.iterdir()), [], "o servidor não grava configuração")
        self.assertFalse((self.sandbox.home / ".config" / "second-brain").exists(), "tocou a configuração do HOME")


class BrainConfidentialTest(BrainServerCase):
    """Nota `confidential: true` cujo título e corpo casam com "payments plan" nunca sai pelo MCP."""

    def setUp(self):
        super().setUp()
        self.sandbox.fixture_vault()
        self.secret_rel = self.sandbox.secret_path.relative_to(self.sandbox.vault).as_posix()

    def test_fixture_note_is_confidential_and_matches_the_query(self):
        """SPEC-0059:IT-03 (sem --include-confidential ela fica de fora; com ele, a CLI a devolve)"""
        text = self.sandbox.secret_path.read_text(encoding="utf-8")
        self.assertRegex(text, re.compile(r"^confidential: true$", re.MULTILINE))
        self.assertIn(SECRET_MARKER, text)
        out = self.sandbox.brain_cli("search", INCLUDE_CONFIDENTIAL, "--json", "--", "payments", "plan")
        self.assertIn(self.secret_rel, [r["path"] for r in json.loads(out.stdout)["results"]])
        out = self.sandbox.brain_cli("search", "--json", "--", "payments", "plan")
        self.assertGreaterEqual(json.loads(out.stdout)["confidential_omitted"], 1)

    def test_search_context_and_related_never_bring_the_confidential_note(self):
        """SPEC-0059:IT-03 (nenhum resultado traz o corpo; a nota não vem como resultado)"""
        server = self.open_server()
        calls = [
            ("brain_search", {"query": "payments plan"}, "results"),
            ("brain_search", {"query": "payments plan rollout code", "context": "college"}, "results"),
            ("brain_context", {"query": "payments plan", "hops": 2}, "notes"),
            ("brain_related", {"text": "payments plan rollout"}, "results"),
            ("brain_related", {"note": PUBLIC_NOTE}, "results"),
            ("brain_links", {"note": PUBLIC_NOTE}, None),
            ("brain_lint", {}, None),
            ("brain_inbox_list", {}, None),
            ("brain_doctor", {}, None),
        ]
        for index, (name, arguments, key) in enumerate(calls, 1):
            with self.subTest(tool=name, arguments=arguments):
                result, _ = self.ask(server, name, arguments, index)
                text = text_of(result)
                self.assertNotIn(SECRET_MARKER, text, "o corpo da nota confidencial saiu pelo MCP")
                if key is not None:
                    self.assertIs(result.get("isError"), False, text)
                    paths = [item.get("path") for item in result["structuredContent"][key]]
                    self.assertNotIn(self.secret_rel, paths)
                    self.assertTrue(paths, "consulta sem resultado: o teste não prova nada")
                if name == "brain_links":
                    self.assertNotIn(self.secret_rel, result["structuredContent"]["backlinks"])

    def test_related_and_links_by_name_are_refused(self):
        """SPEC-0059:IT-03 (recusa da CLI, sem o conteúdo da nota)"""
        server = self.open_server()
        refusal = self.sandbox.brain_cli("links", "--json", "--", SECRET_NOTE)
        self.assertEqual(refusal.returncode, 2, refusal.stderr)
        for index, (name, arguments) in enumerate((("brain_related", {"note": SECRET_NOTE}),
                                                  ("brain_links", {"note": SECRET_NOTE})), 1):
            with self.subTest(tool=name):
                result, _ = self.ask(server, name, arguments, index)
                text = text_of(result)
                self.assertIs(result.get("isError"), True, text)
                self.assertIn(refusal.stderr.strip(), text)
                self.assertNotIn(SECRET_MARKER, text)
                self.assertNotIn("structuredContent", result)

    def test_links_of_a_missing_note_is_an_error(self):
        """SPEC-0059:IT-03 (nota inexistente)"""
        server = self.open_server()
        expected = self.sandbox.brain_cli("links", "--json", "--", "Nota Que Nao Existe")
        self.assertEqual(expected.returncode, 2, expected.stderr)
        result, _ = self.ask(server, "brain_links", {"note": "Nota Que Nao Existe"}, 1)
        self.assertIs(result.get("isError"), True)
        self.assertIn(expected.stderr.strip(), text_of(result))


if __name__ == "__main__":
    unittest.main()
