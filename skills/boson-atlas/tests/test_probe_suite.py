"""Adaptador `suite` (assets/probes/suite.py): o arquivo de jornadas local, as suítes do time chamadas sem shell e o
resultado por jornada (SPEC-0103: UT-05, UT-06, IT-01 e CT-01; ADR-0026 regra 4, ADR-0025, ADR-0023, ADR-0010).

Contrato (seção 6 da SPEC-0103) que estes testes fixam:

    command: ["python3", "<skill>/assets/probes/suite.py", "--journeys-file", "/caminho/absoluto/journeys.json"]
    --describe -> {"contract": "probe@2", "adapter": "suite", "capabilities": {"functional": {"verbs": ["run"],
                   "targets": ["deployment"], "access": ["urls"], "inputs": ["journeys"]}}}
    arquivo de jornadas (JSON): {"journeys": {"<id>": {"command": [...], "cwd"?, "timeout"? (1 a 300, padrão 120),
        "credentials"? [nomes]}}}, chaves fechadas, validado inteiro antes de qualquer jornada; inválido, ausente ou
        ilegível -> status error "arquivo de jornadas inválido: <campo> — <motivo>" (sem o valor); sem
        --journeys-file -> status error "sem arquivo de jornadas (--journeys-file)"
    por id de target.journeys, em ordem: sem entrada no arquivo -> skipped ["jornada sem comando neste arquivo de
        jornadas"]; credencial da jornada ausente -> skipped ["credencial não recebida: <NOME>"]; executável não
        encontrado -> skipped ["comando da suíte não encontrado"]; exit 0 -> passed; 77 -> skipped ["a suíte pulou a
        jornada"]; outro -> failed com as linhas "ATLAS-FAILED-STEP: " (até 5, 200 caracteres) ou ["a suíte saiu com
        <n>"]; tempo esgotado -> failed ["tempo esgotado (<n>s)"] e o grupo da suíte encerrado
    ambiente da suíte: o mínimo das probes, as credentials DA JORNADA e ATLAS_SERVICE, ATLAS_ENVIRONMENT,
        ATLAS_JOURNEY e ATLAS_BASE_URL; jornadas do arquivo que não foram pedidas nunca rodam.

Leituras desta suíte (listadas no relatório do test-writer):
    - "Arquivo ausente" (caminho que não existe) entra no grupo de UT-05 da mensagem "arquivo de jornadas inválido:"; a
      seção 6 também cita "sem arquivo de jornadas (--journeys-file)" para esse caso, e por isso as duas são aceitas
      nele (e só nele).
    - "Sem o valor": o texto que tornou o arquivo inválido (o command em texto, ./x.sh, o cwd relativo, minha-senha)
      não aparece na message; o campo é livre, desde que a message tenha "<campo> — <motivo>".
    - O "ambiente mínimo" do adaptador é medido contra PROBE_BASE_ENV do núcleo (o adaptador não importa o núcleo,
      mas não pode passar outro nome à suíte).
    - O adaptador expõe validate_journeys(data) -> list (problemas; [] = válido), usada pelo CT-01 para o exemplo de
      arquivo de jornadas de references/probes/suite.md.
    - CT-01 lê de references/probes/suite.md os blocos ```json probe@2 functional <describe|input|output>
      <valid|invalid>; a saída é conferida contra as jornadas do primeiro bloco "input valid"; o exemplo de arquivo
      de jornadas é o bloco ```json cujo objeto tem a chave "journeys" como mapa.

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); sem rede e sem ferramenta de teste
de verdade (as suítes são fixtures/functional/fake_suite.py); nomes acme, api, checkout, login, refund, dev, prod.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

from helpers import SKILL, atlas, fn, output
from test_probe import adapter_yaml
from test_probe_functional import (
    BASE_URL,
    FAKE_SUITE,
    JOURNEYS,
    PASSWORD_NAME,
    PASSWORD_VALUE,
    SPEC,
    SUITE,
    USER_NAME,
    USER_VALUE,
    FunctionalCase,
)

SUITE_DOC = SKILL / "references" / "probes" / "suite.md"
DESCRIBE = {"contract": "probe@2", "adapter": "suite", "capabilities": {"functional": {
    "verbs": ["run"], "targets": ["deployment"], "access": ["urls"], "inputs": ["journeys"]}}}
ITEM_KEYS = {"journey", "result", "duration_seconds", "failed_steps"}
NO_COMMAND = "jornada sem comando neste arquivo de jornadas"
NOT_FOUND = "comando da suíte não encontrado"
SKIPPED_BY_SUITE = "a suíte pulou a jornada"
INVALID_FILE = "arquivo de jornadas inválido: "
NO_FILE = "sem arquivo de jornadas (--journeys-file)"
ATLAS_VARS = {"ATLAS_SERVICE", "ATLAS_ENVIRONMENT", "ATLAS_JOURNEY", "ATLAS_BASE_URL"}
LOGIN_TOKEN_NAME, LOGIN_TOKEN_VALUE = "LOGIN_TEST_TOKEN", "token-falso-login-0103"
SHELL_VAR = "SHELL_ONLY_VAR_0103"
DOC_BLOCK_RE = re.compile(r"```json probe@2 functional (describe|input|output) (valid|invalid)[ \t]*\n(.*?)```",
                          re.DOTALL)
JSON_BLOCK_RE = re.compile(r"```json[^\n]*\n(.*?)```", re.DOTALL)


def suite_input(journeys=JOURNEYS, base_url=BASE_URL):
    return {"contract": "probe@2", "capability": "functional", "verb": "run",
            "target": {"service": "api", "environment": "dev", "deployment": "dev-api",
                       "urls": {"base_url": base_url}, "journeys": list(journeys)},
            "limits": {"lines": 200, "since_seconds": 1800}}


_CACHE = {}


def suite_module():
    """assets/probes/suite.py importado pelo caminho (sem sys.path)."""
    if "module" not in _CACHE:
        if not SUITE.exists():
            raise AssertionError(f"{SUITE} não existe ({SPEC})")
        spec = importlib.util.spec_from_file_location("atlas_probe_suite_0103", SUITE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CACHE["module"] = module
    return _CACHE["module"]


def doc_blocks():
    if not SUITE_DOC.exists():
        raise AssertionError(f"{SUITE_DOC} não existe ({SPEC})")
    text = SUITE_DOC.read_text(encoding="utf-8")
    return text, [(m.group(1), m.group(2), json.loads(m.group(3))) for m in DOC_BLOCK_RE.finditer(text)]


class SuiteCase(unittest.TestCase):
    """O adaptador rodando direto, como o núcleo o chama: argv em lista, a entrada no stdin e só o ambiente que o
    núcleo daria (o mínimo das probes e as credentials declaradas)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.suite_record = os.path.join(self.root, "suite-calls.jsonl")

    def suite_command(self, *extra):
        return [sys.executable, str(FAKE_SUITE), "--record", self.suite_record, *extra]

    def journeys_file(self, data, name="journeys.json", raw=None):
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(raw if raw is not None else json.dumps(data))
        return path

    def adapter_env(self, **extra):
        environ = {name: os.environ[name] for name in ("PATH", "HOME", "LANG") if name in os.environ}
        environ.update(extra)
        return environ

    def run_suite(self, args, data=None, environ=None, timeout=60):
        if not SUITE.exists():
            self.fail(f"{SUITE} não existe ({SPEC})")
        proc = subprocess.run([sys.executable, str(SUITE), *args], check=False, capture_output=True, text=True,
                              input=json.dumps(suite_input() if data is None else data), cwd=self.root,
                              env=self.adapter_env() if environ is None else environ, timeout=timeout)
        self.assertNotIn("Traceback", proc.stdout + proc.stderr, proc.stdout + proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        try:
            out = json.loads(proc.stdout)
        except ValueError:
            self.fail(f"a saída do suite.py não é JSON: {proc.stdout!r}")
        self.assertEqual(fn("validate_probe_output", "SPEC-0096")(out), [], out)
        return out

    def run_journeys(self, journeys, requested=JOURNEYS, environ=None):
        """O suite.py com o arquivo de jornadas `journeys` e a entrada com `requested`: os itens (status ok)."""
        path = self.journeys_file({"journeys": journeys})
        out = self.run_suite(["--journeys-file", path], suite_input(requested), environ)
        self.assertEqual(out["status"], "ok", out)
        self.assertEqual([i["journey"] for i in out["items"]], list(requested), out["items"])
        for entry in out["items"]:
            self.assertEqual(set(entry), ITEM_KEYS, entry)
        return {i["journey"]: i for i in out["items"]}

    def suite_calls(self):
        if not os.path.exists(self.suite_record):
            return []
        with open(self.suite_record, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


# --------------------------------------------------------------------------- UT-05


class JourneysFileTest(SuiteCase):
    def valid(self):
        return {"checkout": {"command": self.suite_command(), "timeout": 30,
                             "credentials": [USER_NAME, PASSWORD_NAME]},
                "refund": {"command": self.suite_command("--exit", "1")}}

    def test_without_journeys_file_option_is_an_error(self):
        """SPEC-0103:UT-05 — command sem --journeys-file: status error "sem arquivo de jornadas (--journeys-file)",
        exit 0, nenhuma suíte roda."""
        # SPEC-0103:UT-05
        out = self.run_suite([])
        self.assertEqual((out["status"], out.get("message")), ("error", NO_FILE), out)
        self.assertEqual(out["items"], [])
        self.assertEqual(self.suite_calls(), [])

    def test_an_invalid_file_is_an_error_without_the_value_and_runs_nothing(self):
        """SPEC-0103:UT-05 — arquivo ausente, JSON inválido, chave env numa jornada, chave a mais no topo, command em
        texto, command com ./x.sh, cwd relativo, timeout 0 e 301, credencial minha-senha: status error "arquivo de
        jornadas inválido: <campo> — <motivo>", sem o valor, e nenhuma suíte roda (o registro das suítes falsas não
        muda), mesmo havendo uma jornada válida no arquivo."""
        # SPEC-0103:UT-05
        def journey(**change):
            data = {"journeys": self.valid()}
            data["journeys"]["checkout"].update(change)
            return data

        cases = {
            "chave env": (journey(env={"X": "1"}), None),
            "chave a mais no topo": (dict(journey(), suites={}), None),
            "command em texto": (journey(command="python3 roda-suite-0103.py"), "roda-suite-0103"),
            "command relativo": (journey(command=["./x.sh"]), "./x.sh"),
            "command vazio": (journey(command=[]), None),
            "cwd relativo": (journey(cwd="repo-0103/e2e"), "repo-0103"),
            "timeout 0": (journey(timeout=0), None),
            "timeout 301": (journey(timeout=301), None),
            "credencial fora da regra": (journey(credentials=["minha-senha"]), "minha-senha"),
            "id fora da regra": ({"journeys": dict(self.valid(), **{"check out": {"command": ["true"]}})}, None),
        }
        for name, (data, value) in cases.items():
            with self.subTest(name):
                path = self.journeys_file(data, name="case.json")
                out = self.run_suite(["--journeys-file", path])
                message = out.get("message") or ""
                self.assertEqual(out["status"], "error", out)
                self.assertTrue(message.startswith(INVALID_FILE), message)
                self.assertIn(" — ", message[len(INVALID_FILE):], message)
                if value:
                    self.assertNotIn(value, message)
                self.assertEqual(out["items"], [])
                self.assertEqual(self.suite_calls(), [], "uma suíte rodou com o arquivo inválido")
        with self.subTest("JSON inválido"):
            path = self.journeys_file(None, name="broken.json", raw='{"journeys": {"checkout": ')
            out = self.run_suite(["--journeys-file", path])
            self.assertEqual(out["status"], "error", out)
            self.assertTrue((out.get("message") or "").startswith(INVALID_FILE), out)
            self.assertEqual(self.suite_calls(), [])
        with self.subTest("arquivo ausente"):
            out = self.run_suite(["--journeys-file", os.path.join(self.root, "nao-existe.json")])
            self.assertEqual(out["status"], "error", out)
            message = out.get("message") or ""
            self.assertTrue(message.startswith(INVALID_FILE) or message == NO_FILE, message)
            self.assertEqual(self.suite_calls(), [])

    def test_a_requested_journey_without_command_is_skipped_and_unrequested_ones_never_run(self):
        """SPEC-0103:UT-05 — arquivo com checkout e refund, entrada ["checkout", "login"]: login sai skipped "jornada
        sem comando neste arquivo de jornadas", checkout roda e refund (não pedida) nunca roda."""
        # SPEC-0103:UT-05
        journeys = {"checkout": {"command": self.suite_command()},
                    "refund": {"command": self.suite_command("--exit", "1")}}
        found = self.run_journeys(journeys)
        self.assertEqual(found["checkout"]["result"], "passed", found)
        self.assertEqual((found["login"]["result"], found["login"]["failed_steps"]), ("skipped", [NO_COMMAND]))
        self.assertEqual([c["env"].get("ATLAS_JOURNEY") for c in self.suite_calls()], ["checkout"])

    def test_describe_is_the_contract_one(self):
        """SPEC-0103:UT-05 (contrato) — --describe (com o --journeys-file do command) imprime a descrição probe@2 da
        seção 6, que passa no validate_probe_describe do núcleo."""
        # SPEC-0103:UT-05
        path = self.journeys_file({"journeys": self.valid()})
        proc = subprocess.run([sys.executable, str(SUITE), "--journeys-file", path, "--describe"], check=False,
                              capture_output=True, text=True, cwd=self.root, env=self.adapter_env())
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data, DESCRIBE)
        self.assertEqual(fn("validate_probe_describe", "SPEC-0096")(data), [])
        self.assertEqual(self.suite_calls(), [])


# --------------------------------------------------------------------------- UT-06


class SuiteResultTest(SuiteCase):
    def one(self, command, environ=None, **opts):
        return self.run_journeys({"checkout": dict(opts, command=command)}, ["checkout"], environ)["checkout"]

    def test_exit_0_passes(self):
        """SPEC-0103:UT-06 — exit 0 -> passed, duration_seconds número >= 0, failed_steps []."""
        # SPEC-0103:UT-06
        found = self.one(self.suite_command())
        self.assertEqual((found["result"], found["failed_steps"]), ("passed", []))
        self.assertIsInstance(found["duration_seconds"], (int, float))
        self.assertNotIsInstance(found["duration_seconds"], bool)
        self.assertGreaterEqual(found["duration_seconds"], 0)

    def test_failed_steps_come_only_from_the_protocol_lines(self):
        """SPEC-0103:UT-06 — exit 1 com três linhas ATLAS-FAILED-STEP: e outras linhas: failed com só os três passos,
        sem o prefixo; nenhuma outra linha da suíte sai do adaptador."""
        # SPEC-0103:UT-06
        steps = ["abrir o carrinho", "pagar com cartão de teste", "ver o recibo"]
        args = ["--exit", "1", "--noise", "LINHA-QUALQUER-0103 dado de teste"]
        for step in steps:
            args += ["--step", step]
        path = self.journeys_file({"journeys": {"checkout": {"command": self.suite_command(*args)}}})
        proc = subprocess.run([sys.executable, str(SUITE), "--journeys-file", path], check=False, capture_output=True,
                              text=True, input=json.dumps(suite_input(["checkout"])), cwd=self.root,
                              env=self.adapter_env())
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("LINHA-QUALQUER-0103", proc.stdout + proc.stderr)
        self.assertNotIn("ATLAS-FAILED-STEP", proc.stdout + proc.stderr)
        found = json.loads(proc.stdout)["items"][0]
        self.assertEqual((found["result"], found["failed_steps"]), ("failed", steps))

    def test_at_most_five_steps_cut_at_200(self):
        """SPEC-0103:UT-06 — sete linhas do protocolo, de 250 caracteres: só as cinco primeiras, cada uma cortada em
        200."""
        # SPEC-0103:UT-06
        steps = [f"{n}" + "p" * 249 for n in range(7)]
        args = ["--exit", "1"]
        for step in steps:
            args += ["--step", step]
        found = self.one(self.suite_command(*args))
        self.assertEqual(found["result"], "failed")
        self.assertEqual(found["failed_steps"], [s[:200] for s in steps[:5]])

    def test_other_exit_without_protocol_lines(self):
        """SPEC-0103:UT-06 — exit 2 sem linha do protocolo: failed com ["a suíte saiu com 2"]."""
        # SPEC-0103:UT-06
        found = self.one(self.suite_command("--exit", "2"))
        self.assertEqual((found["result"], found["failed_steps"]), ("failed", ["a suíte saiu com 2"]))

    def test_exit_77_skips(self):
        """SPEC-0103:UT-06 — exit 77: skipped ["a suíte pulou a jornada"]."""
        # SPEC-0103:UT-06
        found = self.one(self.suite_command("--exit", "77"))
        self.assertEqual((found["result"], found["failed_steps"]), ("skipped", [SKIPPED_BY_SUITE]))

    def test_missing_executable_skips(self):
        """SPEC-0103:UT-06 — executável inexistente (caminho absoluto ou nome fora do PATH): skipped "comando da suíte
        não encontrado"."""
        # SPEC-0103:UT-06
        for command in ([os.path.join(self.root, "nao-existe-0103")], ["suite-inexistente-0103"]):
            with self.subTest(command=command[0]):
                found = self.one(command)
                self.assertEqual((found["result"], found["failed_steps"]), ("skipped", [NOT_FOUND]))

    def test_a_credential_not_received_skips_without_running(self):
        """SPEC-0103:UT-06 — a jornada pede CHECKOUT_TEST_USER e o ambiente do adaptador não tem: skipped "credencial
        não recebida: CHECKOUT_TEST_USER", e a suíte não roda."""
        # SPEC-0103:UT-06
        found = self.one(self.suite_command(), credentials=[USER_NAME])
        self.assertEqual((found["result"], found["failed_steps"]), ("skipped", [f"credencial não recebida: {USER_NAME}"]))
        self.assertEqual(self.suite_calls(), [])

    def test_timeout_fails_and_ends_the_whole_group(self):
        """SPEC-0103:UT-06 — suíte que dorme além do timeout da jornada (1 s) e abre um processo filho: failed
        "tempo esgotado (1s)", o adaptador volta logo e o processo filho dela não fica vivo."""
        # SPEC-0103:UT-06
        child = os.path.join(self.root, "child.pid")
        started = time.monotonic()
        found = self.one(self.suite_command("--child-pid", child, "--sleep", "30"), timeout=1)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual((found["result"], found["failed_steps"]), ("failed", ["tempo esgotado (1s)"]))
        with open(child, encoding="utf-8") as handle:
            pid = int(handle.read().strip())
        deadline = time.monotonic() + 5
        alive = True
        while alive and time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                alive = False
            except PermissionError:
                break
        if alive:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        self.assertFalse(alive, "o processo filho da suíte continuou vivo depois do tempo esgotado")

    def test_suite_environment_and_argv(self):
        """SPEC-0103:UT-06 — a suíte grava o próprio ambiente e argv: só o ambiente mínimo, ATLAS_SERVICE,
        ATLAS_ENVIRONMENT, ATLAS_JOURNEY, ATLAS_BASE_URL e as credenciais da própria jornada (não as da outra
        jornada nem as variáveis do shell); o argv é a lista do arquivo, sem shell; o cwd é o do arquivo."""
        # SPEC-0103:UT-06
        literal = ["a b; echo injetado-0103", "$HOME", "*", "`id`"]
        repo = os.path.join(self.root, "repo")
        os.mkdir(repo)
        journeys = {"checkout": {"command": self.suite_command(*literal), "cwd": repo,
                                 "credentials": [USER_NAME, PASSWORD_NAME]},
                    "login": {"command": self.suite_command(), "credentials": [LOGIN_TOKEN_NAME]}}
        environ = self.adapter_env(**{USER_NAME: USER_VALUE, PASSWORD_NAME: PASSWORD_VALUE,
                                      LOGIN_TOKEN_NAME: LOGIN_TOKEN_VALUE, SHELL_VAR: "do-shell"})
        found = self.run_journeys(journeys, environ=environ)
        self.assertEqual({j: i["result"] for j, i in found.items()}, {"checkout": "passed", "login": "passed"})
        calls = {c["env"]["ATLAS_JOURNEY"]: c for c in self.suite_calls()}
        self.assertEqual(set(calls), set(JOURNEYS))
        base = set(atlas().PROBE_BASE_ENV)
        checkout, login = calls["checkout"], calls["login"]
        self.assertEqual(set(checkout["env"]) - base, ATLAS_VARS | {USER_NAME, PASSWORD_NAME}, checkout["env"])
        self.assertEqual(set(login["env"]) - base, ATLAS_VARS | {LOGIN_TOKEN_NAME}, login["env"])
        self.assertEqual({k: checkout["env"][k] for k in sorted(ATLAS_VARS)},
                         {"ATLAS_BASE_URL": BASE_URL, "ATLAS_ENVIRONMENT": "dev", "ATLAS_JOURNEY": "checkout",
                          "ATLAS_SERVICE": "api"})
        self.assertEqual((checkout["env"][USER_NAME], checkout["env"][PASSWORD_NAME]), (USER_VALUE, PASSWORD_VALUE))
        self.assertEqual(checkout["argv"], ["--record", self.suite_record, *literal])
        self.assertEqual(os.path.realpath(checkout["cwd"]), repo)
        self.assertNotEqual(os.path.realpath(login["cwd"]), self.root, "sem cwd, a suíte roda na pasta temporária")


# --------------------------------------------------------------------------- IT-01


class EndToEndTest(FunctionalCase):
    """atlas.py probe como processo, com o adaptador suite de verdade e duas suítes falsas."""

    def setUp(self):
        super().setUp()
        self.suite_record = self.work / "suite-calls.jsonl"
        self.journeys_path = self.work / "journeys.json"

    def suite_command(self, *extra):
        return [sys.executable, str(FAKE_SUITE), "--record", str(self.suite_record), *extra]

    def write_journeys(self, with_login=True):
        journeys = {"checkout": {"command": self.suite_command()}}
        if with_login:
            journeys["login"] = {"command": self.suite_command("--exit", "1", "--step", "campo senha não apareceu",
                                                               "--step", "botão entrar desabilitado")}
        self.journeys_path.write_text(json.dumps({"journeys": journeys}), encoding="utf-8")

    def configure_suite(self):
        command = [sys.executable, str(SUITE), "--journeys-file", str(self.journeys_path)]
        self.configure([adapter_yaml("suite", command, verbs=("run",), timeout=120)])

    def suite_lines(self):
        return self.suite_record.read_text(encoding="utf-8") if self.suite_record.exists() else ""

    def test_probe_functional_run_with_the_real_suite_adapter(self):
        """SPEC-0103:IT-01 — atlas com journeys ["checkout", "login"] (generic, scan e build de verdade), access.urls.dev
        e o adaptador suite com --journeys-file: `probe functional run --service api --env dev --json` traz checkout
        passed e login failed com os dois passos, exit 0, e a saída passa nos validadores; sem login no arquivo,
        login sai skipped; com --env prod --confirm-production, exit 4 e nenhuma suíte roda."""
        # SPEC-0103:IT-01
        self.write_journeys()
        self.configure_suite()
        result = self.probe("functional", "run", "--json")
        self.assertExit(result, 0)
        data = json.loads(result.stdout)
        self.assertEqual(fn("validate_probe_output", "SPEC-0096")(data), [])
        self.assertEqual(fn("validate_functional_output", SPEC)(data, JOURNEYS), [])  # SPEC-0103:CT-01
        found = {i["journey"]: i for i in data["items"]}
        self.assertEqual([i["journey"] for i in data["items"]], JOURNEYS)
        self.assertEqual(found["checkout"]["result"], "passed")
        self.assertEqual((found["login"]["result"], found["login"]["failed_steps"]),
                         ("failed", ["campo senha não apareceu", "botão entrar desabilitado"]))
        self.assertNotIn(BASE_URL, output(result))
        self.write_journeys(with_login=False)
        result = self.probe("functional", "run", "--json")
        self.assertExit(result, 0)
        found = {i["journey"]: i for i in json.loads(result.stdout)["items"]}
        self.assertEqual((found["login"]["result"], found["login"]["failed_steps"]), ("skipped", [NO_COMMAND]))
        before = self.suite_lines()
        result = self.probe("functional", "run", "--confirm-production", env="prod")
        self.assertOwnError(result, 4, "validação funcional só roda em ambiente tier: test (prod não é)")
        self.assertEqual(self.suite_lines(), before, "uma suíte rodou em produção")


# --------------------------------------------------------------------------- CT-01


class ContractTest(SuiteCase):
    def test_suite_md_blocks_pass_and_fail_in_the_core_validators(self):
        """SPEC-0103:CT-01 — os blocos ```json probe@2 functional describe|input|output valid|invalid de
        references/probes/suite.md: os valid passam nos validadores do núcleo (a saída também na validação própria de
        functional, contra as jornadas do primeiro input valid) e cada invalid falha; o --describe do suite.py é o
        bloco describe valid."""
        # SPEC-0103:CT-01
        _, blocks = doc_blocks()
        kinds = {(kind, verdict) for kind, verdict, _ in blocks}
        for needed in (("describe", "valid"), ("input", "valid"), ("output", "valid"), ("output", "invalid")):
            self.assertIn(needed, kinds, f"references/probes/suite.md sem bloco json probe@2 functional {needed}")
        inputs = [data for kind, verdict, data in blocks if (kind, verdict) == ("input", "valid")]
        journeys = inputs[0]["target"]["journeys"]
        validators = {"describe": fn("validate_probe_describe", "SPEC-0096"),
                      "input": fn("validate_probe_input", "SPEC-0096")}
        generic_output = fn("validate_probe_output", "SPEC-0096")
        functional = fn("validate_functional_output", SPEC)
        for index, (kind, verdict, data) in enumerate(blocks):
            with self.subTest(block=index, kind=kind, verdict=verdict):
                if kind == "output":
                    problems = generic_output(data) or functional(data, journeys)
                else:
                    problems = validators[kind](data)
                if verdict == "valid":
                    self.assertEqual(problems, [], data)
                else:
                    self.assertTrue(problems, f"bloco invalid aceito: {data}")
        described = [data for kind, verdict, data in blocks if (kind, verdict) == ("describe", "valid")]
        self.assertEqual(described[0], DESCRIBE)
        path = self.journeys_file({"journeys": {}})
        proc = subprocess.run([sys.executable, str(SUITE), "--journeys-file", path, "--describe"], check=False,
                              capture_output=True, text=True, cwd=self.root, env=self.adapter_env())
        self.assertEqual(proc.returncode, 0, output(proc))
        self.assertEqual(json.loads(proc.stdout), described[0])

    def test_suite_md_journeys_file_example_passes_the_adapter_validation(self):
        """SPEC-0103:CT-01 — o exemplo de arquivo de jornadas de references/probes/suite.md passa no validate_journeys
        do adaptador, e o mesmo exemplo com uma chave env numa jornada é recusado."""
        # SPEC-0103:CT-01
        text, _ = doc_blocks()
        examples = []
        for block in JSON_BLOCK_RE.findall(text):
            try:
                data = json.loads(block)
            except ValueError:
                continue
            if isinstance(data, dict) and isinstance(data.get("journeys"), dict) and data["journeys"]:
                examples.append(data)
        self.assertTrue(examples, "references/probes/suite.md sem exemplo de arquivo de jornadas")
        validate = getattr(suite_module(), "validate_journeys", None)
        self.assertIsNotNone(validate, f"suite.validate_journeys não existe ({SPEC})")
        self.assertEqual(validate(examples[0]), [])
        broken = json.loads(json.dumps(examples[0]))
        first = next(iter(broken["journeys"]))
        broken["journeys"][first]["env"] = {"X": "1"}
        self.assertTrue(validate(broken))


if __name__ == "__main__":
    unittest.main()
