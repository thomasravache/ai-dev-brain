"""Apoio comum das suítes da second-brain: carrega scripts/brain.py e roda a CLI isolada.

- `load_brain()` importa scripts/brain.py pelo caminho (importlib), sem sys.path de outra skill (ADR-0007).
  Ausente ou com erro de import = None; `brain()` e `fn(nome)` transformam isso em falha clara do teste.
- `Sandbox` cria um diretório temporário resolvido (macOS: /var -> /private/var) com HOME e BRAIN_CONFIG_HOME
  próprios e roda `python3 scripts/brain.py ...` como subprocesso.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SKILL = TESTS.parent
SCRIPT = SKILL / "scripts" / "brain.py"
NOT_CONFIGURED = "second-brain não configurado nesta máquina — rode init (ou init --join)"
LOG_LINE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} ")
INIT_LOG_LINE = re.compile(r"^(?:[-*] )?\d{4}-\d{2}-\d{2} \d{2}:\d{2} init\b", re.MULTILINE)
DOCTOR_LINE = re.compile(r"^(OK|AVISO|ERRO) (.+?) — (.*)$")

_CACHE = {}


def load_brain():
    if "module" not in _CACHE:
        module = None
        if SCRIPT.exists():
            spec = importlib.util.spec_from_file_location("brain", SCRIPT)
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as exc:  # noqa: BLE001 — vira falha clara no teste
                _CACHE["error"] = f"{type(exc).__name__}: {exc}"
                module = None
        _CACHE["module"] = module
    return _CACHE["module"]


def brain():
    module = load_brain()
    if module is None:
        detail = _CACHE.get("error") or "arquivo não existe"
        raise AssertionError(f"{SCRIPT} não pôde ser carregado ({detail}) — SPEC-0017")
    return module


def fn(name):
    """Função de brain.py exigida pela SPEC-0017; ausente = o teste falha pelo motivo certo."""
    f = getattr(brain(), name, None)
    if f is None:
        raise AssertionError(f"brain.{name} não existe (SPEC-0017)")
    return f


class Sandbox:
    """Diretório temporário com HOME e BRAIN_CONFIG_HOME isolados (ADR-0002)."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.config_home = self.root / "config-home"
        self.vault = self.root / "Drive" / "Vault"
        self.files = self.root / "Drive" / "Vault-files"

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run(self, *args, config_home=None):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env["BRAIN_CONFIG_HOME"] = str(config_home or self.config_home)
        return subprocess.run([sys.executable, str(SCRIPT), *[str(a) for a in args]], check=False,
                              cwd=self.root, capture_output=True, text=True, env=env)

    def init(self, *extra, vault=None, files=None, provider="google-drive", config_home=None):
        return self.run("init", "--vault", vault or self.vault, "--files", files or self.files,
                        "--provider", provider, *extra, config_home=config_home)

    def new_vault(self):
        """Vault do IT-01: vazio, criado por init com o contexto college."""
        self.vault.mkdir(parents=True)
        out = self.init("--context", "college=projects/college:College")
        assert out.returncode == 0, f"init falhou ({out.returncode}): {out.stdout}{out.stderr}"
        return out

    def config_json(self, config_home=None):
        out = self.run("config", "--json", config_home=config_home)
        assert out.returncode == 0, f"config --json falhou ({out.returncode}): {out.stdout}{out.stderr}"
        return json.loads(out.stdout)


def output(result):
    return result.stdout + result.stderr


def snapshot(root: Path) -> dict:
    """Conteúdo e mtime de cada arquivo e pasta sob root (relativos)."""
    state = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        data = path.read_bytes() if path.is_file() else None
        state[rel] = (data, path.stat().st_mtime_ns)
    return state


def doctor_lines(text: str) -> list:
    """(status, item, detalhe) de cada linha "OK|AVISO|ERRO <item> — <detalhe>"."""
    rows = []
    for line in text.splitlines():
        m = DOCTOR_LINE.match(line.strip())
        if m:
            rows.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
    return rows
