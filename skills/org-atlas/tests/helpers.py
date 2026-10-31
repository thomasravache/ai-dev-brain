"""Apoio comum das suítes da org-atlas: carrega scripts/atlas.py e roda a CLI isolada.

- `load_atlas()` importa scripts/atlas.py pelo caminho (importlib), sem sys.path de outra skill (ADR-0010).
  Ausente ou com erro de import = None; `atlas()` e `fn(nome)` transformam isso em falha clara do teste.
- `Sandbox` cria um diretório temporário resolvido (macOS: /var -> /private/var) com HOME e ATLAS_CONFIG_HOME
  próprios e roda `python3 scripts/atlas.py ...` como subprocesso.
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
SCRIPT = SKILL / "scripts" / "atlas.py"
ASSET_CONFIG = SKILL / "assets" / "atlas-config.yml"
NOT_CONFIGURED = "org-atlas não configurado nesta máquina — rode init (ou init --join)"
DOCTOR_LINE = re.compile(r"^(OK|AVISO|ERRO) (.+?) — (.*)$")
# valor absoluto: /x, ~, C:\ ou C:/, \\servidor
ABSOLUTE = re.compile(r"^(/|~|[A-Za-z]:[\\/]|\\\\)")

STRUCTURE_DIRS = ("services", "platform", "conventions", "process", "snapshots")
STRUCTURE_FILES = ("ATLAS.md", "atlas-config.yml", "glossary.md")
SHARED_KEYS = ("version", "organization", "mode", "language", "stale_days", "categories", "collectors",
               "redaction")
# padrões do contrato (seção 6) para o atlas-config.yml
DEFAULTS = {
    "version": "1",
    "language": "auto",
    "stale_days": "14",
    "categories": ["code", "delivery"],
    "collectors": [],
    "redaction": {"extra_patterns": []},
}

_CACHE = {}


def load_atlas():
    if "module" not in _CACHE:
        module = None
        if SCRIPT.exists():
            spec = importlib.util.spec_from_file_location("atlas", SCRIPT)
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as exc:  # noqa: BLE001 — vira falha clara no teste
                _CACHE["error"] = f"{type(exc).__name__}: {exc}"
                module = None
        _CACHE["module"] = module
    return _CACHE["module"]


def atlas():
    module = load_atlas()
    if module is None:
        detail = _CACHE.get("error") or "arquivo não existe"
        raise AssertionError(f"{SCRIPT} não pôde ser carregado ({detail}) — SPEC-0032")
    return module


def fn(name, spec="SPEC-0032"):
    """Nome de atlas.py exigido pela spec `spec`; ausente = o teste falha pelo motivo certo."""
    f = getattr(atlas(), name, None)
    if f is None:
        raise AssertionError(f"atlas.{name} não existe ({spec})")
    return f


def normalize(value):
    """Escalares viram texto (o parser pode ou não converter tipos); dicts e listas mantêm a forma."""
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return str(value)


def leaves(value, path=""):
    """(caminho, valor) de cada escalar de um dict/list aninhado."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from leaves(item, f"{path}[{i}]")
    else:
        yield path, value


def absolute_values(data):
    return [(path, value) for path, value in leaves(data) if isinstance(value, str) and ABSOLUTE.match(value)]


class Sandbox:
    """Diretório temporário com HOME e ATLAS_CONFIG_HOME isolados (ADR-0002)."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.config_home = self.root / "config-home"
        self.atlas = self.root / "work" / "acme-atlas"

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run(self, *args, config_home=None, env=None, unset=()):
        environ = dict(os.environ)
        environ["HOME"] = str(self.home)
        environ["ATLAS_CONFIG_HOME"] = str(config_home or self.config_home)
        environ.update(env or {})
        for name in unset:
            environ.pop(name, None)
        return subprocess.run([sys.executable, str(SCRIPT), *[str(a) for a in args]], check=False,
                              cwd=self.root, capture_output=True, text=True, env=environ)

    def init(self, *extra, atlas=None, org="Acme", mode="repo", config_home=None):
        return self.run("init", "--atlas", atlas or self.atlas, "--org", org, "--mode", mode, *extra,
                        config_home=config_home)

    def new_atlas(self):
        """Atlas do IT-01: pasta vazia, criada por init no modo repo."""
        self.atlas.mkdir(parents=True)
        out = self.init()
        assert out.returncode == 0, f"init falhou ({out.returncode}): {out.stdout}{out.stderr}"
        return out

    def write_local(self, text, config_home=None):
        home = config_home or self.config_home
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yml").write_text(text, encoding="utf-8")
        return home / "config.yml"

    def config_json(self, config_home=None, env=None):
        out = self.run("config", "--json", config_home=config_home, env=env)
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
