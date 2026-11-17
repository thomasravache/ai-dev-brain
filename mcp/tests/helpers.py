"""Apoio comum da suíte mcp/tests (SPEC-0054, SPEC-0059, SPEC-0060): carrega mcp/fermion_mcp.py, cria um atlas de
fixture pela CLI da boson-atlas, um vault de fixture pela CLI da photon-brain e um projeto SDD de fixture pela CLI da
gluon-spec, e abre o servidor real por stdio.

- `server_module()` importa mcp/fermion_mcp.py pelo caminho (importlib). Ausente ou com erro de import vira uma
  falha clara do teste (AssertionError), não um erro de coleta.
- `Sandbox` cria um diretório temporário resolvido (macOS: /var -> /private/var) com HOME, ATLAS_CONFIG_HOME e
  BRAIN_CONFIG_HOME próprios; nunca toca as pastas de configuração do atlas e do cérebro em ~/.config (nomes novos e antigos) nem a configuração do Claude
  Code. `Sandbox.sdd_env()` acrescenta SDD_CONFIG_HOME e XDG_* temporários e CLAUDE_PROJECT_DIR apontando para o
  projeto de fixture (nunca o valor do ambiente real). Padrão copiado de skills/boson-atlas/tests/helpers.py e skills/photon-brain/tests/brain_support.py (sem
  importar de lá: ADR-0010 e ADR-0017).
- `ServerProcess` abre `python3 mcp/fermion_mcp.py` com stdin/stdout em pipe, uma mensagem JSON por linha.
"""
import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
MCP = TESTS.parent
REPO = MCP.parent
SERVER = MCP / "fermion_mcp.py"
ATLAS_CLI = REPO / "skills" / "boson-atlas" / "scripts" / "atlas.py"
BRAIN_CLI = REPO / "skills" / "photon-brain" / "scripts" / "brain.py"
SDD_CLI = REPO / "skills" / "gluon-spec" / "scripts" / "spec_graph.py"
PLUGIN_JSON = REPO / ".claude-plugin" / "plugin.json"
FAKE_COLLECTOR = TESTS / "fixtures" / "collector.py"
SPEC = "SPEC-0054"

LEGACY_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
MODERN_VERSION = "2026-07-28"
SUPPORTED_VERSIONS = [MODERN_VERSION, *LEGACY_VERSIONS]
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
CAPS_KEY = "io.modelcontextprotocol/clientCapabilities"
SERVER_INFO_KEY = "io.modelcontextprotocol/serverInfo"
TOOLS = ("atlas_config", "atlas_doctor", "atlas_context", "atlas_lint", "atlas_curate_list")
NOT_CONFIGURED = "atlas não configurado nesta máquina — rode a skill boson-atlas (onboarding)"
TIMEOUT_TEXT = "atlas.py não respondeu em 120 s"
# SPEC-0059 (seção 6): as oito tools de leitura do segundo cérebro
BRAIN_TOOLS = ("brain_config", "brain_doctor", "brain_search", "brain_related", "brain_links", "brain_context",
               "brain_inbox_list", "brain_lint")
BRAIN_NOT_CONFIGURED = "segundo cérebro não configurado nesta máquina — rode a skill photon-brain (onboarding)"
BRAIN_TIMEOUT_TEXT = "brain.py não respondeu em 120 s"
# vault de fixture (IT-01 a IT-03): duas notas públicas e uma confidencial, todas casando com "payments plan"
BRAIN_CONTEXT = "college"
PUBLIC_NOTE = "Payments API"
OTHER_NOTE = "Billing Flow"
SECRET_NOTE = "Payments Secret Plan"
SECRET_BODY = "Payments plan rollout code quokka7731 stays offline."
SECRET_MARKER = "quokka7731"  # só existe no corpo da nota confidencial
# SPEC-0060 (seção 6): as seis tools de leitura do processo SDD
SDD_TOOLS = ("sdd_status", "sdd_validate", "sdd_next", "sdd_waves", "sdd_report", "sdd_whats_new")
SDD_TIMEOUT_TEXT = "spec_graph.py não respondeu em 120 s"
PROJECT_ENV = "CLAUDE_PROJECT_DIR"
# projeto SDD de fixture (IT-01 e IT-02): git init + duas specs lite criadas pela CLI da gluon-spec
SDD_FIXTURE_TITLES = ("Fixture A", "Fixture B")
CLI_TIMEOUT = 120
RESPONSE_TIMEOUT = 5.0  # seção 5: cada resposta do IT-01 em menos de 5 s
PROCESS_TIMEOUT = 60

_CACHE = {}


def server_module():
    """mcp/fermion_mcp.py como módulo; falha clara do teste quando não existe ou não importa."""
    if "module" not in _CACHE:
        module, error = None, "arquivo não existe"
        if SERVER.exists():
            spec = importlib.util.spec_from_file_location("fermion_mcp", SERVER)
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as exc:  # noqa: BLE001 — vira falha clara no teste
                module, error = None, f"{type(exc).__name__}: {exc}"
        _CACHE["module"], _CACHE["error"] = module, error
    if _CACHE["module"] is None:
        raise AssertionError(f"{SERVER} não pôde ser carregado ({_CACHE['error']}) — {SPEC}")
    return _CACHE["module"]


def attr(name):
    """Nome exigido de fermion_mcp.py; ausente = o teste falha pelo motivo certo."""
    value = getattr(server_module(), name, None)
    if value is None:
        raise AssertionError(f"fermion_mcp.{name} não existe ({SPEC})")
    return value


def plugin_version():
    return json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"]


def request(method, params=None, id=1, meta=None):
    message = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None or meta is not None:
        message["params"] = dict(params or {})
    if meta is not None:
        message["params"]["_meta"] = meta
    return message


def notification(method, params=None):
    message = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        message["params"] = params
    return message


def modern_meta(version=MODERN_VERSION, capabilities=True):
    meta = {VERSION_KEY: version, "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "0"}}
    if capabilities:
        meta[CAPS_KEY] = {}
    return meta


def call(name, arguments=None, id=1, meta=None):
    params = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return request("tools/call", params, id=id, meta=meta)


def text_of(result):
    """Texto do primeiro bloco de content de um CallToolResult."""
    content = result.get("content")
    assert isinstance(content, list) and content, f"content vazio ou ausente: {result}"
    assert content[0].get("type") == "text", f"primeiro bloco não é text: {content[0]}"
    return content[0]["text"]


def atlas_config_text(collector_command):
    command = "[" + ", ".join(json.dumps(a) for a in collector_command) + "]"
    return ("version: 1\norganization: Acme\nmode: local\nlanguage: auto\nstale_days: 14\n"
            "categories: [code, delivery]\ncollectors:\n  - id: fake\n    category: code\n"
            f"    command: {command}\n    timeout: 60\nredaction: {{extra_patterns: []}}\n")


class Sandbox:
    """Diretório temporário com HOME e ATLAS_CONFIG_HOME isolados."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.config_home = self.root / "config-home"
        self.brain_config_home = self.root / "brain-config-home"
        self.atlas = self.root / "work" / "acme-atlas"
        self.vault = self.root / "drive" / "vault"
        self.files = self.root / "drive" / "files"
        self.project = self.root / "work" / "sdd-project"

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def env(self, config_home=None, brain_config_home=None):
        environ = dict(os.environ)
        environ["HOME"] = str(self.home)
        environ["ATLAS_CONFIG_HOME"] = str(config_home or self.config_home)
        environ["BRAIN_CONFIG_HOME"] = str(brain_config_home or self.brain_config_home)
        return environ

    def cli(self, *args, config_home=None):
        return subprocess.run([sys.executable, str(ATLAS_CLI), *[str(a) for a in args]], check=False,
                              cwd=self.root, capture_output=True, text=True, env=self.env(config_home),
                              timeout=PROCESS_TIMEOUT)

    def fixture_atlas(self):
        """init (modo local) + scan com o coletor falso de fixtures/collector.py, tudo pela CLI."""
        self.atlas.mkdir(parents=True)
        out = self.cli("init", "--atlas", self.atlas, "--org", "Acme", "--mode", "local")
        assert out.returncode == 0, f"init falhou ({out.returncode}): {out.stdout}{out.stderr}"
        (self.atlas / "fake").mkdir()
        shutil.copy(FAKE_COLLECTOR, self.atlas / "fake" / "collector.py")
        (self.atlas / "atlas-config.yml").write_text(
            atlas_config_text(["python3", "{atlas}/fake/collector.py", "fake"]), encoding="utf-8")
        out = self.cli("scan")
        assert out.returncode == 0, f"scan falhou ({out.returncode}): {out.stdout}{out.stderr}"

    def brain_cli(self, *args, brain_config_home=None):
        return subprocess.run([sys.executable, str(BRAIN_CLI), *[str(a) for a in args]], check=False,
                              cwd=self.root, capture_output=True, text=True,
                              env=self.env(brain_config_home=brain_config_home), timeout=PROCESS_TIMEOUT)

    def _brain_ok(self, *args):
        out = self.brain_cli(*args)
        assert out.returncode == 0, f"brain.py {args[0]} falhou ({out.returncode}): {out.stdout}{out.stderr}"
        return out

    def _new_note(self, title, body, *extra):
        out = self._brain_ok("new-note", "--type", "note", "--title", title, "--context", BRAIN_CONTEXT, *extra,
                             "--json")
        path = self.vault / json.loads(out.stdout)["path"]
        with open(path, "a", encoding="utf-8") as handle:  # corpo acrescentado à nota criada pela CLI
            handle.write("\n" + body + "\n")
        return path

    def fixture_vault(self):
        """init (provedor local, contexto college) + três notas por new-note, tudo pela CLI da photon-brain:
        duas públicas que se linkam e uma `confidential: true` cujo título e corpo casam com "payments plan"."""
        out = self._brain_ok("init", "--vault", self.vault, "--files", self.files, "--provider", "local",
                             "--context", f"{BRAIN_CONTEXT}=projects/{BRAIN_CONTEXT}:College")
        self._new_note(PUBLIC_NOTE, f"Payments plan uses the ledger. See [[{OTHER_NOTE}]].", "--tags",
                       "api,payments")
        self._new_note(OTHER_NOTE, f"Billing charges payments monthly. See [[{PUBLIC_NOTE}]] and [[Missing Note]].",
                       "--tags", "api")
        self.secret_path = self._new_note(SECRET_NOTE, f"{SECRET_BODY} See [[{PUBLIC_NOTE}]].", "--confidential")
        return out


    def sdd_env(self):
        """Ambiente da CLI da gluon-spec e do servidor nos IT da SPEC-0060: HOME, SDD_CONFIG_HOME e XDG_* dentro
        do sandbox; CLAUDE_PROJECT_DIR = projeto de fixture."""
        environ = self.env()
        for key, folder in (("SDD_CONFIG_HOME", "sdd-config-home"), ("XDG_CONFIG_HOME", "xdg-config"),
                            ("XDG_DATA_HOME", "xdg-data"), ("XDG_CACHE_HOME", "xdg-cache"),
                            ("XDG_STATE_HOME", "xdg-state")):
            environ[key] = str(self.root / folder)
        environ["GIT_CONFIG_NOSYSTEM"] = "1"
        environ[PROJECT_ENV] = str(self.project)
        return environ

    def sdd_cli(self, *args):
        """spec_graph.py --root <projeto> <args>, com o ambiente de sdd_env() e o cwd do servidor (raiz do sandbox)."""
        argv = [sys.executable, str(SDD_CLI), "--root", str(self.project), *[str(a) for a in args]]
        return subprocess.run(argv, check=False, cwd=self.root, capture_output=True, text=True, env=self.sdd_env(),
                              timeout=PROCESS_TIMEOUT)

    def fixture_project(self):
        """git init + `new --tier lite --title ...` duas vezes, tudo pela CLI da gluon-spec."""
        self.project.mkdir(parents=True)
        out = subprocess.run(["git", "init", "-q"], check=False, cwd=self.project, capture_output=True, text=True,
                             env=self.sdd_env(), timeout=PROCESS_TIMEOUT)
        assert out.returncode == 0, f"git init falhou ({out.returncode}): {out.stdout}{out.stderr}"
        for title in SDD_FIXTURE_TITLES:
            out = self.sdd_cli("new", "--tier", "lite", "--title", title)
            assert out.returncode == 0, f"new {title!r} falhou ({out.returncode}): {out.stdout}{out.stderr}"


class ServerProcess:
    """O servidor real (python3 mcp/fermion_mcp.py) por stdio; stderr vai para um arquivo do sandbox."""

    def __init__(self, sandbox, config_home=None, brain_config_home=None, env=None):
        if not SERVER.exists():
            raise AssertionError(f"{SERVER} não existe ({SPEC})")
        self.stderr_path = sandbox.root / "server-stderr.txt"
        self._stderr = open(self.stderr_path, "w", encoding="utf-8")  # noqa: SIM115 — fechado em close()
        self.proc = subprocess.Popen([sys.executable, str(SERVER)], cwd=sandbox.root,
                                     env=env if env is not None else sandbox.env(config_home, brain_config_home),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr,
                                     text=True, encoding="utf-8", bufsize=1)
        self.lines = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)  # EOF

    def stderr(self):
        self._stderr.flush()
        return self.stderr_path.read_text(encoding="utf-8")

    def send_line(self, line):
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def send_bytes(self, data):
        """Bytes crus no stdin (ex.: linha que não é UTF-8), sem passar pela codificação do pipe de texto."""
        self.proc.stdin.flush()
        self.proc.stdin.buffer.write(data)
        self.proc.stdin.buffer.flush()

    def send(self, message):
        self.send_line(json.dumps(message))

    def receive(self, timeout=RESPONSE_TIMEOUT):
        """(resposta decodificada, segundos até chegar)."""
        start = time.monotonic()
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError(f"servidor não respondeu em {timeout} s; stderr:\n{self.stderr()}") from None
        elapsed = time.monotonic() - start
        if line is None:
            raise AssertionError(f"servidor fechou o stdout sem responder (exit {self.proc.poll()}); stderr:\n"
                                 f"{self.stderr()}")
        try:
            return json.loads(line), elapsed
        except ValueError:
            raise AssertionError(f"linha do stdout não é JSON: {line!r}") from None

    def ask(self, message, timeout=RESPONSE_TIMEOUT):
        self.send(message)
        response, elapsed = self.receive(timeout)
        return response, elapsed

    def close_stdin(self):
        self.proc.stdin.close()

    def rest_of_stdout(self, timeout=PROCESS_TIMEOUT):
        """Linhas que ainda chegarem até o EOF do stdout."""
        rest, deadline = [], time.monotonic() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                raise AssertionError("stdout do servidor não fechou") from None
            if line is None:
                return rest
            rest.append(line)

    def close(self):
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
        if self.proc.stdout:
            self.proc.stdout.close()
        self._stderr.close()
