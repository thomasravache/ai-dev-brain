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


# ---------------------------------------------------------------- UT-09

REASONS = {"remote": "remote do projeto", "env": "ATLAS_NAME", "default": "padrão"}
NO_CHOICE_CLI = ("vários atlas configurados (acme, globex) e nenhum escolhido — use --atlas <nome>, ATLAS_NAME ou "
                 "config --set-default <nome>")
LEAKS = ("SEGREDO", "/caminho", "ACME_TOKEN", "github.com")


def chosen_line(name, reason, others):
    return (f"Atlas da organização (boson-atlas) para este projeto: {name} (escolhido por: {reason}). "
            f"Outros nesta máquina: {', '.join(others)}. Use a skill boson-atlas ou a tool MCP atlas_context.")


def no_choice_line(names):
    return (f"Vários atlas nesta máquina ({', '.join(names)}) e nenhum escolhido para este projeto: use --atlas, o "
            "parâmetro atlas das tools MCP ou declare remotes: no atlas-config.yml.")


def no_choice_answer(names=("acme", "globex")):
    """config --json sai com 2 (mensagem da CLI no stderr); config --list --json lista os atlas sem falhar."""
    listed = json.dumps({"atlases": [{"name": n, "atlas": f"/caminho/SEGREDO-{n}", "default": False,
                                      "organization": n.title()} for n in names],
                         "atlas_name": None, "selected_by": None})

    def answer(argv, timeout):
        if "--list" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout=listed, stderr="")
        return subprocess.CompletedProcess(argv, 2, stdout="", stderr=f"erro: {NO_CHOICE_CLI}\n")
    return answer


class AtlasLineTest(HookTestCase):
    def atlas_context(self, atlas_answer):
        project = make_project(self.base / f"p{len(list(self.base.iterdir()))}", sdd=False)
        runner = FakeRunner(atlas=atlas_answer)
        code, out, err = self.run_hook(runner, cwd=project)
        self.assertEqual(code, 0)
        return out, err, runner

    def assertAtlasLine(self, atlas_answer, expected):
        out, err, runner = self.atlas_context(atlas_answer)
        context = self.context(out)
        self.assertEqual(context.strip(), expected, err)
        for leak in LEAKS:
            self.assertNotIn(leak, context)
        for call in runner.calls_to("atlas.py"):
            self.assertEqual(call["argv"][2:3], ["config"], runner.calls)
            self.assertNotIn("--atlas", call["argv"], "o hook nunca escolhe o atlas")
        self.assert_timeouts(runner)

    def test_lines_of_the_contract_without_paths_remotes_or_credentials(self):
        """SPEC-0080:UT-09 — 1 atlas: linha de hoje; 2 atlas com selected_by remote, env ou default: nome e motivo;
        exit 2: a linha do passo; exit 3: nada; nenhuma linha com caminho, remote ou credencial."""
        with self.subTest(caso="1 atlas"):
            self.assertAtlasLine((0, config_json("acme", "single", ["acme"], default="acme"), ""), ATLAS_LINE)
        for selected_by, reason in REASONS.items():
            with self.subTest(caso=f"2 atlas, {selected_by}"):
                answer = (0, config_json("globex", selected_by, ["acme", "globex"], default="acme"), "")
                self.assertAtlasLine(answer, chosen_line("globex", reason, ["acme"]))
        with self.subTest(caso="3 atlas"):
            answer = (0, config_json("globex", "remote", ["acme", "globex", "initech"]), "")
            self.assertAtlasLine(answer, chosen_line("globex", "remote do projeto", ["acme", "initech"]))
        with self.subTest(caso="exit 2"):
            self.assertAtlasLine(no_choice_answer(), no_choice_line(["acme", "globex"]))
        with self.subTest(caso="exit 3"):
            out, _, _ = self.atlas_context((3, "", "erro: boson-atlas não configurado nesta máquina\n"))
            self.assertEqual(out, "", "não configurado: nenhuma linha do atlas")


# ---------------------------------------------------------------- CT-01

class ConfigContractTest(HookTestCase):
    def test_hook_reads_atlas_name_selected_by_and_atlases_and_ignores_unknown_fields(self):
        """SPEC-0080:CT-01 — cada selected_by de SPEC-0079@1 mais remote: com 1 atlas, a linha de hoje; com 2, o
        nome de atlas_name, o motivo de selected_by e os outros de atlases; campo desconhecido é ignorado."""
        project = make_project(self.base / "p", sdd=False)

        def line(stdout):
            code, out, _ = self.run_hook(FakeRunner(atlas=(0, stdout, "")), cwd=project)
            self.assertEqual(code, 0)
            return self.context(out).strip()

        for selected_by in ("option", "env", "remote", "default", "single"):
            with self.subTest(atlas=1, selected_by=selected_by):
                self.assertEqual(line(config_json("acme", selected_by, ["acme"], default="acme", futuro=[1])),
                                 ATLAS_LINE)
        for selected_by, reason in REASONS.items():
            with self.subTest(atlas=2, selected_by=selected_by):
                stdout = json.loads(config_json("globex", selected_by, ["acme", "globex"], default="acme"))
                stdout["futuro"] = {"campo": "novo"}
                for item in stdout["atlases"]:
                    item["organization"] = "?"
                self.assertEqual(line(json.dumps(stdout)), chosen_line("globex", reason, ["acme"]))
        for selected_by in ("option", "single"):  # o hook nunca passa --atlas; o texto do motivo não está no contrato
            with self.subTest(atlas=2, selected_by=selected_by):
                text = line(config_json("globex", selected_by, ["acme", "globex"]))
                self.assertTrue(text.startswith("Atlas da organização (boson-atlas) para este projeto: globex "
                                                "(escolhido por: "), text)
                self.assertIn("Outros nesta máquina: acme.", text)


# ---------------------------------------------------------------- E2E-01

MCP_SERVER = REPO / "mcp" / "fermion_mcp.py"


def generic_config(organization, remote):
    command = ["python3", "{skill}/assets/collectors/generic.py", "--facts", "{atlas}/facts/services.json",
               "--category", "runtime", "--source", "facts"]
    return (f"version: 1\norganization: {organization}\nmode: repo\nlanguage: auto\nstale_days: 14\n"
            "categories: [code, delivery]\ncollectors:\n  - id: facts\n    category: runtime\n"
            "    command: [" + ", ".join(json.dumps(a) for a in command) + "]\n    timeout: 60\n"
            f"redaction: {{extra_patterns: []}}\nremotes:\n  - {remote}\n")


def mcp_context(env, project, query):
    """atlas_context pelo servidor MCP real (stdio), com CLAUDE_PROJECT_DIR = project; devolve o result."""
    messages = [
        {"jsonrpc": "2.0", "id": 0, "method": "initialize",
         "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "e2e", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "atlas_context",
                                                                       "arguments": {"query": query}}},
    ]
    environ = dict(env, CLAUDE_PROJECT_DIR=str(project))
    out = subprocess.run([sys.executable, str(MCP_SERVER)], input="".join(json.dumps(m) + "\n" for m in messages),
                         cwd=str(project.parent), env=environ, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    assert out.returncode == 0, out.stderr
    responses = {r.get("id"): r for r in map(json.loads, out.stdout.splitlines())}
    return responses[1]["result"]


@unittest.skipUnless(HAS_GIT, "git não está no PATH")
class TwoOrganizationsJourneyTest(unittest.TestCase):
    def make_atlas(self, env, base, organization, service, remote):
        path = base / "work" / f"{organization.lower()}-atlas"
        path.mkdir(parents=True)
        out = cli(env, base, "init", "--atlas", path, "--org", organization, "--mode", "repo")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        (path / "atlas-config.yml").write_text(generic_config(organization, remote), encoding="utf-8")
        (path / "facts").mkdir()
        facts = {"entities": [{"kind": "service", "id": service, "name": service, "attrs": {}}], "relations": []}
        (path / "facts" / "services.json").write_text(json.dumps(facts), encoding="utf-8")
        out = cli(env, base, "scan", "--atlas", path)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return path

    def step(self, env, project, line, service):
        code, context, stderr = run_hook(env, project)
        self.assertEqual(code, 0, stderr)
        self.assertIn(line, context, stderr)
        self.assertNotIn(ATLAS_LINE, context)
        for leak in (str(project.parent.parent), "github.com", "initech/x"):
            self.assertNotIn(leak, context)
        result = mcp_context(env, project, "api")
        self.assertIs(result.get("isError"), False, result)
        services = json.loads(result["content"][0]["text"])["services"]
        self.assertEqual([s["key"] for s in services], [f"service:{service}"])

    def test_person_with_two_organizations(self):
        """SPEC-0080:E2E-01 — dois atlas com remotes:; sessão num repositório de B: hook diz b (remote do projeto) e
        atlas_context sem atlas responde com o grafo de B; num de A, A; sem remote conhecido, o default."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            env = isolated_env(base / "env")
            env["GIT_CEILING_DIRECTORIES"] = str(base)
            self.make_atlas(env, base, "Acme", "payments-api", "github.com/acme")  # 1: o primeiro é o default
            self.make_atlas(env, base, "Globex", "billing-api", "github.com/globex")
            listed = json.loads(cli(env, base, "config", "--list", "--json").stdout)
            self.assertEqual([(a["name"], a["default"]) for a in listed["atlases"]],
                             [("acme", True), ("globex", False)])

            globex = git_repo(env, base / "src" / "billing", "git@github.com:globex/billing.git")
            self.step(env, globex, chosen_line("globex", "remote do projeto", ["acme"]), "billing-api")  # 2 e 3
            acme = git_repo(env, base / "src" / "payments", "https://github.com/acme/payments.git")
            self.step(env, acme, chosen_line("acme", "remote do projeto", ["globex"]), "payments-api")  # 4
            other = git_repo(env, base / "src" / "other", "https://github.com/initech/x.git")
            self.step(env, other, chosen_line("acme", "padrão", ["globex"]), "payments-api")  # 5


# ---------------------------------------------------------------- UT-12 (Emenda v3, item 9)

INVALID_CHOSEN_CLI = ("item inválido em remotes: https://***@github.com/acme — remotes aceita só prefixos host/caminho "
                      "em minúsculas")


def chosen_but_invalid_answer():
    """config --json sai com 2 por outro motivo (remotes: inválido no atlas escolhido); config --list --json mostra
    que há um atlas escolhido (atlas_name "acme")."""
    listed = json.dumps({"atlases": [{"name": n, "atlas": f"/caminho/SEGREDO-{n}", "default": n == "acme",
                                      "organization": n.title()} for n in ("acme", "globex")],
                         "atlas_name": "acme", "selected_by": "default"})

    def answer(argv, timeout):
        if "--list" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout=listed, stderr="")
        return subprocess.CompletedProcess(argv, 2, stdout="", stderr=f"erro: {INVALID_CHOSEN_CLI}\n")
    return answer


class OtherExit2Test(HookTestCase):
    def test_exit_2_with_a_chosen_atlas_is_not_no_choice(self):
        """SPEC-0080:UT-12 — config --json com exit 2 e config --list --json com atlas_name "acme": o hook não diz
        "nenhum escolhido"; tira o bloco do atlas e manda uma linha ao stderr."""
        project = make_project(self.base / "p", sdd=False)
        runner = FakeRunner(atlas=chosen_but_invalid_answer())
        code, out, err = self.run_hook(runner, cwd=project)
        self.assertEqual(code, 0)
        context = self.context(out) if out.strip() else ""
        self.assertNotIn("nenhum escolhido", context)
        self.assertNotIn("Vários atlas", context)
        self.assertNotIn("Atlas da organização", context, "exit 2 do atlas escolhido tira o bloco do atlas")
        self.assertTrue(err.strip(), "a falha da CLI vai ao stderr")
        for leak in LEAKS:
            self.assertNotIn(leak, context)
        self.assert_timeouts(runner)
