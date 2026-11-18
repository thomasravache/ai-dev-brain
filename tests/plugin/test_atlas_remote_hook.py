"""Linha do atlas no hook de início de sessão com vários atlas e a jornada das duas organizações (SPEC-0080: CH-01,
UT-09, CT-01 e E2E-01; ADR-0021).

Run: python3 -m unittest discover -s tests/plugin -p test_atlas_remote_hook.py

Contrato (seção 6 da SPEC-0080) do bloco do atlas em hooks/session_start.py, a partir de `config --json` rodado na
pasta da sessão:
    exit 0, 1 atlas configurado → a linha de hoje (ATLAS_LINE), sem mudança
    exit 0, 2+ atlas → "Atlas da organização (boson-atlas) para este projeto: <nome> (escolhido por: remote do
        projeto|ATLAS_NAME|padrão). Outros nesta máquina: <nomes>. Use a skill boson-atlas ou a tool MCP
        atlas_context."
    exit 2 (vários sem escolha) → "Vários atlas nesta máquina (<nomes>) e nenhum escolhido para este projeto: use
        --atlas, o parâmetro atlas das tools MCP ou declare remotes: no atlas-config.yml."
    exit 3 → nada
    Nenhuma linha traz caminho, remote ou credencial. <nomes> segue a ordem de `atlases` (por nome), separada por
    ", " (como as mensagens da CLI).

Na saída 2, o executor substituto responde tanto ao `config --json` (exit 2 com a mensagem da CLI no stderr) quanto a
um `config --list --json` (que não falha com vários atlas), para não amarrar o teste à forma como o hook descobre os
nomes.

Os testes de processo (CH-01 e E2E-01) usam HOME, XDG_*, ATLAS_CONFIG_HOME e BRAIN_CONFIG_HOME temporários
(test_session_start.isolated_env), atlas criados pela CLI com o coletor generic e repositórios git locais com `origin`
fictício; nunca a rede nem a configuração real da máquina.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_session_start import (
    ATLAS_LINE,
    HOOK,
    FakeRunner,
    HookTestCase,
    hook_stdin,
    isolated_env,
    make_project,
)

SPEC = "SPEC-0080"
REPO = Path(__file__).resolve().parents[2]
ATLAS_CLI = REPO / "skills" / "boson-atlas" / "scripts" / "atlas.py"
HAS_GIT = shutil.which("git") is not None
TIMEOUT = 120


def config_json(name, selected_by, names, default=None, **extra):
    """Saída de `config --json` (contrato SPEC-0079@1) com caminhos e credenciais que nunca podem vazar."""
    data = {
        "values": {"atlas": f"/caminho/SEGREDO-{name}", "credentials": {"facts": {"env": ["ACME_TOKEN"]}},
                   "organization": name.title(), "mode": "repo"},
        "origins": {"atlas": "local", "credentials": "local", "organization": "atlas", "mode": "atlas"},
        "atlas_name": name,
        "selected_by": selected_by,
        "atlases": [{"name": n, "atlas": f"/caminho/SEGREDO-{n}", "default": n == default} for n in sorted(names)],
    }
    data.update(extra)
    return json.dumps(data, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- caracterização (CH-01)

def cli(env, cwd, *args):
    return subprocess.run([sys.executable, str(ATLAS_CLI), *[str(a) for a in args]], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=TIMEOUT, check=False)


def git(env, cwd, *args):
    out = subprocess.run(["git", "-c", "init.defaultBranch=main", *args], cwd=cwd, env=env, capture_output=True,
                         text=True, timeout=TIMEOUT, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    return out


def git_repo(env, path, origin=None):
    """Repositório git local; `origin` fictício (nunca acessado)."""
    path.mkdir(parents=True)
    git(env, path, "init", "-q")
    if origin:
        git(env, path, "remote", "add", "origin", origin)
    return path


def run_hook(env, cwd):
    """O hook como processo; devolve (exit, additionalContext ou "", stderr)."""
    result = subprocess.run([sys.executable, str(HOOK)], input=hook_stdin(cwd), cwd=str(cwd), env=env,
                            capture_output=True, text=True, timeout=60, check=False)
    context = ""
    if result.stdout.strip():
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    return result.returncode, context, result.stderr


class HookCharacterizationTest(HookTestCase):
    def test_one_atlas_keeps_todays_line_whatever_the_selected_by(self):
        """SPEC-0080:CH-01 — com um atlas só, a linha do hook é a de hoje, sem nome, motivo nem caminho."""
        project = make_project(self.base / "p", sdd=False)
        for selected_by in ("single", "default", "env", "option", "remote"):
            with self.subTest(selected_by=selected_by):
                runner = FakeRunner(atlas=(0, config_json("acme", selected_by, ["acme"], default="acme"), ""))
                code, out, _ = self.run_hook(runner, cwd=project)
                self.assertEqual(code, 0)
                self.assertEqual(self.context(out).strip(), ATLAS_LINE)
                calls = runner.calls_to("atlas.py")
                self.assertEqual([c["argv"][2:] for c in calls], [["config", "--json"]], runner.calls)

    @unittest.skipUnless(HAS_GIT, "git não está no PATH")
    def test_one_atlas_configured_by_the_cli_gives_todays_line(self):
        """SPEC-0080:CH-01 — processo: um atlas configurado pela CLI (com remotes: que casa o projeto) e o hook
        rodando num repositório git com origin: a linha de hoje."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            env = isolated_env(base / "env")
            atlas = base / "work" / "acme-atlas"
            atlas.mkdir(parents=True)
            out = cli(env, base, "init", "--atlas", atlas, "--org", "Acme", "--mode", "repo")
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            with open(atlas / "atlas-config.yml", "a", encoding="utf-8") as handle:
                handle.write("remotes:\n  - github.com/acme\n")
            project = git_repo(env, base / "src" / "api", "https://github.com/acme/api.git")
            code, context, stderr = run_hook(env, project)
            self.assertEqual(code, 0, stderr)
            self.assertIn(ATLAS_LINE, context, stderr)
            self.assertNotIn("para este projeto", context)
            self.assertNotIn(str(atlas), context)
