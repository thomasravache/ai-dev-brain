"""Tools atlas_* com o parâmetro `atlas` e rodando na pasta do projeto (SPEC-0080: CH-01, UT-08, IT-02 e CT-01;
ADR-0021). O hook e a CLI ficam em tests/plugin e skills/boson-atlas/tests.

Run: python3 -m unittest discover -s mcp/tests

Contrato (seção 6 da SPEC-0080) que estes testes fixam em mcp/fermion_mcp.py:

    atlas_config, atlas_doctor, atlas_context, atlas_lint e atlas_curate_list ganham o parâmetro opcional
        "atlas": string, 1–200 caracteres, sem caractere de controle → a CLI recebe "--atlas <valor>" (ou
        "--atlas=<valor>"), sempre antes do "--" do context. Sem "atlas", os argumentos são os de hoje (CH-01).
    Todas rodam a CLI com cwd = project_dir() (CLAUDE_PROJECT_DIR ou o cwd do servidor).
    Exit 2 da escolha (vários atlas sem escolha) → erro da tool com a mensagem da CLI; exit 3 → NOT_CONFIGURED.

O executor substituto aceita argumentos extras (posicionais ou por nome, como um `cwd=`), para não amarrar o teste à
forma como o servidor passa a pasta do projeto ao run_cli. Os IT abrem o servidor real por stdio com HOME, XDG_*,
ATLAS_CONFIG_HOME temporários, dois atlas criados pela CLI (coletor generic da boson-atlas) e repositórios git locais
com `origin` fictício; nunca a rede nem a configuração real da máquina.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from helpers import (
    ATLAS_CLI,
    CLI_TIMEOUT,
    NOT_CONFIGURED,
    PROCESS_TIMEOUT,
    PROJECT_ENV,
    TOOLS,
    Sandbox,
    ServerProcess,
    attr,
    call,
    request,
    text_of,
)

SPEC = "SPEC-0080"
HAS_GIT = shutil.which("git") is not None
# argumentos de hoje de cada tool sem "atlas" (SPEC-0054 seção 6)
TODAY = (
    ("atlas_config", {}, ["config", "--json"]),
    ("atlas_doctor", {}, ["doctor", "--json"]),
    ("atlas_context", {"query": "api payments"}, ["context", "--json", "--", "api", "payments"]),
    ("atlas_context", {"query": "api", "hops": 2, "limit": 5, "max_chars": 1000},
     ["context", "--hops", "2", "--limit", "5", "--max-chars", "1000", "--json", "--", "api"]),
    ("atlas_lint", {}, ["lint", "--json"]),
    ("atlas_lint", {"only": ["secret-leak", "stale"]}, ["lint", "--json", "--only", "secret-leak,stale"]),
    ("atlas_curate_list", {}, ["curate", "list", "--json"]),
    ("atlas_curate_list", {"status": "inferred"}, ["curate", "list", "--json", "--status", "inferred"]),
)


class Recorder:
    """Executor substituto: grava argv e timeout de cada chamada (aceita cwd e outros extras) e devolve o resultado
    configurado."""

    def __init__(self, returncode=0, stdout="{}", stderr=""):
        self.calls = []
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def __call__(self, argv, timeout=None, *args, **kwargs):
        self.calls.append({"argv": list(argv), "timeout": timeout, "extra": args, "kwargs": kwargs})
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


def new_server(runner):
    return attr("Server")(runner=runner)


def result_of(case, response, id=1):
    case.assertIsNotNone(response)
    case.assertNotIn("error", response, response)
    case.assertIn("result", response, response)
    return response["result"]


def cli_args(case, runner):
    """argv depois de `<python> atlas.py` da única chamada gravada, conferindo o prefixo e o timeout."""
    case.assertEqual(len(runner.calls), 1, runner.calls)
    argv = runner.calls[0]["argv"]
    case.assertTrue(Path(argv[0]).name.startswith("python"), argv)
    case.assertEqual(Path(argv[1]).resolve(), ATLAS_CLI.resolve(), argv)
    case.assertEqual(runner.calls[0]["timeout"], CLI_TIMEOUT, runner.calls[0])
    return argv[2:]


# ---------------------------------------------------------------- caracterização (CH-01)

class AtlasToolsCharacterizationTest(unittest.TestCase):
    def test_atlas_tools_without_atlas_pass_todays_arguments(self):
        """SPEC-0080:CH-01 — com um atlas só, as tools atlas_* chamadas sem `atlas` passam à CLI os argumentos de
        hoje (nenhum --atlas)."""
        self.assertEqual(sorted({name for name, _, _ in TODAY}), sorted(TOOLS))
        for name, arguments, expected in TODAY:
            with self.subTest(tool=name, arguments=arguments):
                runner = Recorder()
                result = result_of(self, new_server(runner).handle(call(name, arguments)))
                self.assertIs(result.get("isError"), False, result)
                args = cli_args(self, runner)
                self.assertEqual(args, expected)
                self.assertFalse([a for a in args if a == "--atlas" or a.startswith("--atlas=")], args)


# ---------------------------------------------------------------- UT-08

NO_CHOICE = ("vários atlas configurados (acme, globex) e nenhum escolhido — use --atlas <nome>, ATLAS_NAME ou "
             "config --set-default <nome>")
INVALID_ATLAS = (
    ("vazio", ""),
    ("201 caracteres", "a" * 201),
    ("NUL", "acme\x00"),
    ("0x01", "\x01acme"),
    ("ESC", "ac\x1b[31mme"),
    ("DEL", "acme\x7f"),
    ("quebra de linha", "acme\n--force"),
    ("tab", "acme\tglobex"),
    ("não é texto", 7),
)


def atlas_option(case, args):
    """(valor de --atlas, argumentos sem a opção); a opção vem uma vez só e antes do "--" do context."""
    head = args[:args.index("--")] if "--" in args else list(args)
    found = [i for i, a in enumerate(head) if a == "--atlas" or a.startswith("--atlas=")]
    case.assertEqual(len(found), 1, f"--atlas precisa aparecer uma vez antes do --: {args}")
    index = found[0]
    if head[index] == "--atlas":
        case.assertLess(index + 1, len(head), args)
        return head[index + 1], args[:index] + args[index + 2:]
    return head[index][len("--atlas="):], args[:index] + args[index + 1:]


class AtlasParameterTest(unittest.TestCase):
    def test_every_atlas_tool_declares_the_optional_atlas_parameter(self):
        """SPEC-0080:UT-08 — tools/list: as cinco atlas_* têm "atlas" string 1–200, opcional."""
        response = new_server(Recorder()).handle(request("tools/list"))
        tools = {tool["name"]: tool for tool in result_of(self, response)["tools"]}
        for name in TOOLS:
            with self.subTest(tool=name):
                schema = tools[name]["inputSchema"]
                prop = schema.get("properties", {}).get("atlas")
                self.assertIsInstance(prop, dict, f"{name} sem o parâmetro atlas")
                self.assertEqual((prop.get("type"), prop.get("minLength"), prop.get("maxLength")),
                                 ("string", 1, 200))
                self.assertNotIn("atlas", schema.get("required", []))
                self.assertIs(schema.get("additionalProperties"), False)

    def test_atlas_becomes_the_cli_option_and_nothing_else_changes(self):
        """SPEC-0080:UT-08 — atlas: "b" em cada tool → a CLI recebe --atlas b; o resto é o argv de hoje."""
        for name, arguments, expected in TODAY:
            for value in ("b", "globex", "~/atlas/globex", "/srv/atlas da acme", "a" * 200):
                with self.subTest(tool=name, arguments=arguments, atlas=value[:20]):
                    runner = Recorder()
                    result = result_of(self, new_server(runner).handle(call(name, dict(arguments, atlas=value))))
                    self.assertIs(result.get("isError"), False, result)
                    found, rest = atlas_option(self, cli_args(self, runner))
                    self.assertEqual(found, value)
                    self.assertEqual(rest, expected)

    def test_invalid_atlas_is_refused_by_the_schema_without_a_process(self):
        """SPEC-0080:UT-08 — atlas vazio, com mais de 200 caracteres ou com caractere de controle → -32602, sem
        abrir processo."""
        for name, arguments, _ in TODAY:
            for label, value in INVALID_ATLAS:
                with self.subTest(tool=name, caso=label):
                    runner = Recorder()
                    response = new_server(runner).handle(call(name, dict(arguments, atlas=value)))
                    self.assertEqual(response.get("error", {}).get("code"), -32602, response)
                    self.assertEqual(runner.calls, [])

    def test_exit_2_of_the_choice_is_a_tool_error_with_the_cli_message(self):
        """SPEC-0080:UT-08 — vários atlas sem escolha (exit 2) → isError com a mensagem da CLI; exit 3 continua
        NOT_CONFIGURED."""
        for name, arguments, _ in TODAY:
            with self.subTest(tool=name, saida=2):
                runner = Recorder(2, "", f"erro: {NO_CHOICE}\n")
                result = result_of(self, new_server(runner).handle(call(name, arguments)))
                self.assertIs(result.get("isError"), True, result)
                self.assertIn(NO_CHOICE, text_of(result))
                self.assertNotIn("structuredContent", result)
            with self.subTest(tool=name, saida=3):
                runner = Recorder(3, "", "erro: atlas não configurado nesta máquina: initech\n")
                result = result_of(self, new_server(runner).handle(call(name, dict(arguments, atlas="initech"))))
                self.assertIs(result.get("isError"), True, result)
                self.assertIn(NOT_CONFIGURED, text_of(result))
                self.assertIn("initech", text_of(result))


# ---------------------------------------------------------------- CT-01

class ConfigContractTest(unittest.TestCase):
    def test_atlas_config_keeps_the_choice_fields_of_the_contract(self):
        """SPEC-0080:CT-01 — para cada selected_by de SPEC-0079@1 mais remote, atlas_config (com e sem atlas)
        devolve atlas_name, selected_by e atlases como a CLI deu; campo desconhecido não atrapalha."""
        for selected_by in ("option", "env", "remote", "default", "single"):
            names = ["acme"] if selected_by == "single" else ["acme", "globex"]
            data = {"values": {"atlas": "/caminho/acme"}, "origins": {"atlas": "local"}, "atlas_name": "acme",
                    "selected_by": selected_by, "futuro": {"x": 1},
                    "atlases": [{"name": n, "atlas": f"/caminho/{n}", "default": n == "acme", "novo": True}
                                for n in names]}
            stdout = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            for arguments in ({}, {"atlas": "acme"}):
                with self.subTest(selected_by=selected_by, arguments=arguments):
                    runner = Recorder(0, stdout)
                    result = result_of(self, new_server(runner).handle(call("atlas_config", arguments)))
                    self.assertIs(result.get("isError"), False, result)
                    self.assertEqual(text_of(result), stdout)
                    structured = result.get("structuredContent") or {}
                    self.assertEqual((structured.get("atlas_name"), structured.get("selected_by")),
                                     ("acme", selected_by))
                    self.assertEqual([a["name"] for a in structured.get("atlases", [])], names)


# ---------------------------------------------------------------- IT-02

def generic_config(organization):
    """atlas-config.yml com o coletor generic da boson-atlas lendo {atlas}/facts/services.json."""
    command = ["python3", "{skill}/assets/collectors/generic.py", "--facts", "{atlas}/facts/services.json",
               "--category", "runtime", "--source", "facts"]
    return (f"version: 1\norganization: {organization}\nmode: repo\nlanguage: auto\nstale_days: 14\n"
            "categories: [code, delivery]\ncollectors:\n  - id: facts\n    category: runtime\n"
            "    command: [" + ", ".join(json.dumps(a) for a in command) + "]\n    timeout: 60\n"
            "redaction: {extra_patterns: []}\n")


def facts(service):
    return {"entities": [{"kind": "service", "id": service, "name": service, "attrs": {}},
                         {"kind": "datastore", "id": f"{service}-db", "name": f"{service}-db", "attrs": {}}],
            "relations": [{"from": f"service:{service}", "to": f"datastore:{service}-db", "type": "writes"}]}


@unittest.skipUnless(HAS_GIT, "git não está no PATH")
class ProjectFolderCase(unittest.TestCase):
    """Sandbox, atlas criados pela CLI e repositórios git locais (IT-02 e Emenda v3)."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        self.root = self.sandbox.root

    def environ(self, project=None):
        environ = {k: v for k, v in self.sandbox.env().items()
                   if k not in ("ATLAS_NAME", PROJECT_ENV, "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
        environ.update(XDG_CONFIG_HOME=str(self.sandbox.home / ".config"), GIT_CONFIG_NOSYSTEM="1",
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CEILING_DIRECTORIES=str(self.root))
        if project is not None:
            environ[PROJECT_ENV] = str(project)
        return environ

    def run_ok(self, argv, cwd, env=None):
        out = subprocess.run([str(a) for a in argv], cwd=str(cwd), env=env or self.environ(), capture_output=True,
                             text=True, timeout=PROCESS_TIMEOUT, check=False)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out

    def make_atlas(self, name, service, remote):
        """init + coletor generic + scan numa configuração de rascunho; depois remotes: [remote]."""
        path = self.root / "work" / f"{name}-atlas"
        path.mkdir(parents=True)
        env = dict(self.environ(), ATLAS_CONFIG_HOME=str(self.root / "scratch" / name))
        self.run_ok([sys.executable, ATLAS_CLI, "init", "--atlas", path, "--org", name.title(), "--mode", "repo"],
                    self.root, env)
        (path / "atlas-config.yml").write_text(generic_config(name.title()) + f"remotes:\n  - {remote}\n",
                                               encoding="utf-8")
        (path / "facts").mkdir()
        (path / "facts" / "services.json").write_text(json.dumps(facts(service)), encoding="utf-8")
        self.run_ok([sys.executable, ATLAS_CLI, "scan", "--atlas", path], self.root, env)
        return path

    def repo(self, name, origin):
        path = self.root / "repos" / name
        path.mkdir(parents=True)
        self.run_ok(["git", "-c", "init.defaultBranch=main", "init", "-q"], path)
        self.run_ok(["git", "remote", "add", "origin", origin], path)
        return path

    def two_atlases(self):
        acme = self.make_atlas("acme", "payments-api", "github.com/acme")
        globex = self.make_atlas("globex", "billing-api", "github.com/globex")
        self.sandbox.config_home.mkdir(parents=True, exist_ok=True)
        (self.sandbox.config_home / "config.yml").write_text(
            "atlases:\n"
            f"  acme:\n    atlas: \"{acme}\"\n    credentials: {{}}\n"
            f"  globex:\n    atlas: \"{globex}\"\n    credentials: {{}}\n", encoding="utf-8")


class ProjectFolderTest(ProjectFolderCase):
    def services(self, server, arguments, id):
        response, _ = server.ask(call("atlas_context", arguments, id=id), timeout=PROCESS_TIMEOUT)
        result = result_of(self, response, id=id)
        self.assertIs(result.get("isError"), False, text_of(result))
        return sorted(s["key"] for s in json.loads(text_of(result))["services"])

    def test_context_runs_in_the_project_folder(self):
        """SPEC-0080:IT-02 — servidor por stdio com CLAUDE_PROJECT_DIR em cada repositório: atlas_context sem atlas
        usa o atlas do remote; com atlas, o atlas pedido."""
        self.two_atlases()
        cases = (
            (self.repo("acme-payments", "git@github.com:acme/payments.git"), "service:payments-api", "globex",
             "service:billing-api"),
            (self.repo("globex-billing", "https://github.com/globex/billing.git"), "service:billing-api", "acme",
             "service:payments-api"),
        )
        for project, own, other, other_service in cases:
            with self.subTest(projeto=project.name):
                server = ServerProcess(self.sandbox, env=self.environ(project))
                self.addCleanup(server.close)
                self.assertEqual(self.services(server, {"query": "api"}, 1), [own])
                self.assertEqual(self.services(server, {"query": "api", "atlas": other}, 2), [other_service])
                response, _ = server.ask(call("atlas_config", {}, id=3), timeout=PROCESS_TIMEOUT)
                structured = result_of(self, response, id=3).get("structuredContent") or {}
                self.assertEqual(structured.get("selected_by"), "remote", structured)


# ---------------------------------------------------------------- Emenda v3 (UT-10 e UT-12)

SECRET = "SECRETTOK"
LEAKY_REMOTE = f"https://u:{SECRET}@github.com/globex"
MASKED_REMOTE = "https://***@github.com/globex"


class AmendmentCase(ProjectFolderCase):
    """acme e globex criados pela CLI; `globex_remote` vai como único item de remotes: da globex."""

    def configure(self, default=None, globex_remote="github.com/globex"):
        acme = self.make_atlas("acme", "payments-api", "github.com/acme")
        globex = self.make_atlas("globex", "billing-api", json.dumps(globex_remote))
        self.globex = globex
        self.sandbox.config_home.mkdir(parents=True, exist_ok=True)
        head = f"default: {default}\n" if default else ""
        (self.sandbox.config_home / "config.yml").write_text(
            head + "atlases:\n"
            f"  acme:\n    atlas: \"{acme}\"\n    credentials: {{}}\n"
            f"  globex:\n    atlas: \"{globex}\"\n    credentials: {{}}\n", encoding="utf-8")

    def atlas_config(self, project, arguments):
        server = ServerProcess(self.sandbox, env=self.environ(project))
        self.addCleanup(server.close)
        response, _ = server.ask(call("atlas_config", arguments, id=1), timeout=PROCESS_TIMEOUT)
        return result_of(self, response, id=1)


class AmendmentServerTest(AmendmentCase):
    def test_atlas_config_never_shows_the_token_of_an_invalid_remote(self):
        """SPEC-0080:UT-10 — globex com remotes: https://u:SECRETTOK@github.com/globex: atlas_config com atlas
        "globex" é erro da tool com o item mascarado, sem o token."""
        self.configure(default="acme", globex_remote=LEAKY_REMOTE)
        result = self.atlas_config(self.root, {"atlas": "globex"})
        text = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(SECRET, text, "o token do item de remotes: vazou pela tool")
        self.assertIs(result.get("isError"), True, result)
        self.assertIn(MASKED_REMOTE, text_of(result))

    def test_missing_project_dir_falls_back_to_the_server_folder(self):
        """SPEC-0080:UT-12 — atlas_config com CLAUDE_PROJECT_DIR numa pasta que não existe: usa o cwd do servidor,
        o passo do remote é pulado e responde com o atlas default."""
        self.configure(default="acme")
        result = self.atlas_config(self.root / "inexistente", {})
        self.assertIs(result.get("isError"), False, text_of(result))
        structured = result.get("structuredContent") or {}
        self.assertEqual((structured.get("atlas_name"), structured.get("selected_by")), ("acme", "default"),
                         structured)


# ---------------------------------------------------------------- Emenda v4 (UT-13)

TOK = "TOKZ9Q"
TOKEN_ITEMS = (
    f"{TOK}@github.com/acme",
    f"ghp_{TOK}@github.com:acme/x",
    f"https://github.com/acme?access_token={TOK}",
    f"https://github.com/acme#{TOK}",
    f"https:/u:{TOK}@h/x",
)


class TokenInRemotesServerTest(AmendmentCase):
    def test_atlas_config_never_shows_a_token_of_remotes(self):
        """SPEC-0080:UT-13 — globex com cada item que carrega um token (userinfo sem esquema, scp-like, query,
        fragment, esquema torto): atlas_config com atlas "globex" é erro da tool e o token não aparece."""
        self.configure(default="acme")
        server = ServerProcess(self.sandbox, env=self.environ(self.root))
        self.addCleanup(server.close)
        for id, item in enumerate(TOKEN_ITEMS, start=1):
            with self.subTest(item=item):
                (self.globex / "atlas-config.yml").write_text(
                    generic_config("Globex") + f"remotes:\n  - {json.dumps(item)}\n", encoding="utf-8")
                response, _ = server.ask(call("atlas_config", {"atlas": "globex"}, id=id), timeout=PROCESS_TIMEOUT)
                result = result_of(self, response, id=id)
                self.assertNotIn(TOK, json.dumps(result, ensure_ascii=False), "o token vazou pela tool")
                self.assertIs(result.get("isError"), True, result)
