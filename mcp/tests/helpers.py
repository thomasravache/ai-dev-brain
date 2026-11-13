"""Apoio comum da suíte mcp/tests (SPEC-0054): carrega mcp/fermion_mcp.py, cria um atlas de fixture pela CLI da
boson-atlas e abre o servidor real por stdio.

- `server_module()` importa mcp/fermion_mcp.py pelo caminho (importlib). Ausente ou com erro de import vira uma
  falha clara do teste (AssertionError), não um erro de coleta.
- `Sandbox` cria um diretório temporário resolvido (macOS: /var -> /private/var) com HOME e ATLAS_CONFIG_HOME
  próprios; nunca toca ~/.config/org-atlas nem a configuração do Claude Code. Padrão copiado de
  skills/boson-atlas/tests/helpers.py (sem importar de lá: ADR-0010 e ADR-0017).
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
        self.atlas = self.root / "work" / "acme-atlas"

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def env(self, config_home=None):
        environ = dict(os.environ)
        environ["HOME"] = str(self.home)
        environ["ATLAS_CONFIG_HOME"] = str(config_home or self.config_home)
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


class ServerProcess:
    """O servidor real (python3 mcp/fermion_mcp.py) por stdio; stderr vai para um arquivo do sandbox."""

    def __init__(self, sandbox, config_home=None):
        if not SERVER.exists():
            raise AssertionError(f"{SERVER} não existe ({SPEC})")
        self.stderr_path = sandbox.root / "server-stderr.txt"
        self._stderr = open(self.stderr_path, "w", encoding="utf-8")  # noqa: SIM115 — fechado em close()
        self.proc = subprocess.Popen([sys.executable, str(SERVER)], cwd=sandbox.root, env=sandbox.env(config_home),
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
