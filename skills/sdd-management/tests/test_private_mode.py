"""Modo privado (SPEC-0002): o estado do SDD fica fora do repositório do time (ADR-0006).

Cada teste isola HOME, SDD_CONFIG_HOME e XDG_* num diretório temporário: nada lê ou grava o registro real.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "spec_graph.py"
sys.path.insert(0, str(SCRIPT.parent))
import spec_graph as sg

BANNER = "MODO PRIVADO"


def git(cwd, *args, env=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


class PrivateEnv:
    """Diretório temporário com um repositório "do time", um remoto bare e o ambiente do usuário isolado."""

    def __init__(self, tmp: Path, remote_url="git@github.com:Org/Repo.git"):
        self.tmp = tmp
        tmp.mkdir(parents=True, exist_ok=True)
        self.home = tmp / "home"
        self.config_home = tmp / "config"
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), SDD_CONFIG_HOME=str(self.config_home),
                        XDG_CONFIG_HOME=str(tmp / "xdg-config"), XDG_DATA_HOME=str(tmp / "xdg-data"),
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                        GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_NOSYSTEM="1")
        self.repo = tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main", env=self.env)
        (self.repo / "README.md").write_text("# time\n", encoding="utf-8")
        git(self.repo, "add", "-A", env=self.env)
        git(self.repo, "commit", "-qm", "init", env=self.env)
        if remote_url:
            git(self.repo, "remote", "add", "origin", remote_url, env=self.env)
        self.spec_root = tmp / "sdd" / "Org" / "Repo"

    @property
    def registry(self) -> Path:
        return self.config_home / "projects.json"

    def run(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd or self.repo, capture_output=True,
                              text=True, env=self.env, check=False)

    def init(self, *extra):
        out = self.run("private", "init", "--spec-root", str(self.spec_root), *extra)
        assert out.returncode == 0, out.stdout + out.stderr
        return out

    def repo_status(self) -> str:
        return git(self.repo, "status", "--porcelain", "--untracked-files=all", env=self.env)

    def root_log(self) -> list:
        return git(self.spec_root, "log", "--format=%s", env=self.env).splitlines()


class PrivateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.e = PrivateEnv(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class RemoteNormalizationTest(unittest.TestCase):
    def test_same_repository_in_every_url_form_gives_the_same_key(self):
        """SPEC-0003:UT-01"""
        for url in ("git@github.com:Org/Repo.git", "https://user@github.com/Org/Repo",
                    "ssh://git@GitHub.com:22/Org/Repo.git"):
            self.assertEqual(sg.normalize_remote(url), "github.com/Org/Repo", url)
        self.assertEqual(sg.normalize_remote("https://gitlab.example.com/grupo/sub/repo.git"),
                         "gitlab.example.com/grupo/sub/repo")


class ResolveModeTest(unittest.TestCase):
    def test_lookup_by_remote_by_path_and_missing(self):
        """SPEC-0003:UT-02"""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        with_remote = PrivateEnv(tmp / "a").repo
        no_remote_env = PrivateEnv(tmp / "b", remote_url=None)
        other = PrivateEnv(tmp / "c", remote_url="git@github.com:Org/Other.git")
        config = tmp / "config"
        config.mkdir()
        (config / "projects.json").write_text(json.dumps({"projects": {
            "github.com/Org/Repo": {"mode": "private", "spec_root": str(tmp / "sdd/repo"), "sync": "none"},
            str(no_remote_env.repo.resolve()): {"mode": "private", "spec_root": str(tmp / "sdd/local"), "sync": "push"},
        }}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"SDD_CONFIG_HOME": str(config)}):
            mode = sg.resolve_mode(with_remote)
            self.assertEqual((mode["mode"], Path(mode["spec_root"]), mode["sync"]), ("private", tmp / "sdd/repo", "none"))
            mode = sg.resolve_mode(no_remote_env.repo)
            self.assertEqual((Path(mode["spec_root"]), mode["sync"]), (tmp / "sdd/local", "push"))
            self.assertIsNone(sg.resolve_mode(other.repo))
        with mock.patch.dict(os.environ, {"SDD_CONFIG_HOME": str(tmp / "nowhere")}):
            self.assertIsNone(sg.resolve_mode(with_remote))


class ModeContractTest(PrivateTestCase):
    def test_project_exposes_the_mode_api(self):
        """SPEC-0003:CT-01"""
        with mock.patch.dict(os.environ, self.e.env, clear=True):
            full = sg.Project(self.e.repo)
            self.assertFalse(full.private)
            self.assertIsNone(full.spec_root)
            self.assertEqual(full.specs_dir, self.e.repo / "docs" / "specs")
            self.assertEqual(full.adr_dir, self.e.repo / "docs" / "adr")
            self.assertEqual(full.config_path, self.e.repo / "docs" / "specs" / "sdd-config.yml")
        self.e.init()
        with mock.patch.dict(os.environ, self.e.env, clear=True):
            private = sg.Project(self.e.repo)
            self.assertTrue(private.private)
            self.assertEqual(private.spec_root, self.e.spec_root)
            self.assertEqual(private.sync, "none")
            self.assertEqual(private.specs_dir, self.e.spec_root / "specs")
            self.assertEqual(private.adr_dir, self.e.spec_root / "adr")
            self.assertEqual(private.config_path, self.e.spec_root / "sdd-config.yml")
            (private.specs_dir / "nota.md").write_text("x\n", encoding="utf-8")
            before = len(self.e.root_log())
            sg.commit_records(private, "sdd: teste")
            self.assertEqual(len(self.e.root_log()), before + 1)


class PrivateInitTest(PrivateTestCase):
    def test_init_registers_and_creates_versioned_spec_root(self):
        """SPEC-0003:IT-01"""
        out = self.e.init()
        self.assertIn("modo privado ativado para github.com/Org/Repo", out.stdout)
        entry = json.loads(self.e.registry.read_text(encoding="utf-8"))["projects"]["github.com/Org/Repo"]
        self.assertEqual((entry["mode"], Path(entry["spec_root"]), entry["sync"]), ("private", self.e.spec_root, "none"))
        for name in ("specs", "adr", "sdd-config.yml", ".git"):
            self.assertTrue((self.e.spec_root / name).exists(), name)
        self.assertEqual(len(self.e.root_log()), 1)
        self.assertEqual(self.e.repo_status(), "")

    def test_repository_with_versioned_sdd_is_refused(self):
        """SPEC-0003:IT-07"""
        (self.e.repo / "docs/specs").mkdir(parents=True)
        (self.e.repo / "docs/specs/sdd-config.yml").write_text("base_branch: main\n", encoding="utf-8")
        git(self.e.repo, "add", "-A", env=self.e.env)
        git(self.e.repo, "commit", "-qm", "sdd", env=self.e.env)
        out = self.e.run("private", "init", "--spec-root", str(self.e.spec_root))
        self.assertEqual(out.returncode, 2, out.stdout)
        self.assertIn("modo completo", out.stderr)
        self.assertFalse(self.e.registry.exists())

    def test_invalid_registry_stops_every_command(self):
        """SPEC-0003:IT-08"""
        self.e.config_home.mkdir()
        self.e.registry.write_text("{ quebrado", encoding="utf-8")
        out = self.e.run("status")
        self.assertEqual(out.returncode, 2)
        self.assertIn(str(self.e.registry), out.stderr)

    def test_off_removes_entry_and_keeps_spec_root(self):
        """SPEC-0003:IT-09"""
        self.e.init()
        out = self.e.run("private", "off")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(str(self.e.spec_root), out.stdout)
        self.assertNotIn("github.com/Org/Repo", json.loads(self.e.registry.read_text(encoding="utf-8"))["projects"])
        self.assertTrue(self.e.spec_root.is_dir())
        self.assertNotIn(BANNER, self.e.run("status").stderr)


class PrivateWorkTest(PrivateTestCase):
    def test_commands_write_only_to_spec_root_and_commit_there(self):
        """SPEC-0003:IT-02"""
        self.e.init()
        before = len(self.e.root_log())
        for args in (("new", "--tier", "lite", "--title", "Corrige soma"), ("set", "SPEC-0001", "external=[jira:PAY-1]"),
                     ("gate", "SPEC-0001", "G0", "--run"), ("index",)):
            out = self.e.run(*args)
            self.assertTrue(out.stderr.startswith(BANNER), (args, out.stderr))
        self.assertTrue(list((self.e.spec_root / "specs").glob("SPEC-0001-*.md")))
        self.assertTrue((self.e.spec_root / "specs" / "INDEX.md").exists())
        self.assertGreaterEqual(len(self.e.root_log()), before + 4)
        self.assertEqual(self.e.repo_status(), "")
        self.assertFalse((self.e.repo / "docs").exists())

    def test_repository_only_commands_are_refused(self):
        """SPEC-0003:IT-03"""
        self.e.init()
        for args in (("vendor", "--ci", "generic"), ("pr-check",)):
            out = self.e.run(*args)
            self.assertEqual(out.returncode, 2, args)
            self.assertIn("não se aplica em modo privado", out.stderr)
        self.assertEqual(self.e.repo_status(), "")

    def test_worktree_resolves_the_same_spec_root(self):
        """SPEC-0003:IT-05"""
        self.e.init()
        wt = self.tmp / "wt"
        git(self.e.repo, "worktree", "add", "-q", "-b", "feat/x", str(wt), env=self.e.env)
        out = self.e.run("status", cwd=wt)
        self.assertIn(str(self.e.spec_root), out.stderr)

    def test_sync_push_none_failure_and_pending_warnings(self):
        """SPEC-0003:IT-06"""
        bare = self.tmp / "remote.git"
        git(self.tmp, "init", "-q", "--bare", str(bare), env=self.e.env)
        self.e.init("--sync", "push")
        git(self.e.spec_root, "remote", "add", "origin", str(bare), env=self.e.env)
        git(self.e.spec_root, "push", "-q", "-u", "origin", "HEAD", env=self.e.env)
        self.assertEqual(self.e.run("new", "--tier", "lite", "--title", "Um").returncode, 0)
        head = git(self.e.spec_root, "rev-parse", "HEAD", env=self.e.env).strip()
        self.assertIn(head, git(bare, "log", "--all", "--format=%H", env=self.e.env))

        self.e.run("private", "init", "--spec-root", str(self.e.spec_root), "--sync", "none")
        self.assertEqual(self.e.run("new", "--tier", "lite", "--title", "Dois").returncode, 0)
        head = git(self.e.spec_root, "rev-parse", "HEAD", env=self.e.env).strip()
        self.assertNotIn(head, git(bare, "log", "--all", "--format=%H", env=self.e.env))

        self.e.run("private", "init", "--spec-root", str(self.e.spec_root), "--sync", "push")
        git(self.e.spec_root, "remote", "set-url", "origin", str(self.tmp / "inexistente.git"), env=self.e.env)
        out = self.e.run("new", "--tier", "lite", "--title", "Tres")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("push", out.stderr)

        (self.e.spec_root / "specs" / "rascunho.md").write_text("x\n", encoding="utf-8")
        for args in (("status",), ("private", "status")):
            out = self.e.run(*args)
            self.assertIn("sem commit", out.stdout + out.stderr, args)


class FullModeGuardTest(PrivateTestCase):
    def test_entry_for_another_repository_keeps_full_mode(self):
        """SPEC-0003:IT-04 (guarda)"""
        self.e.config_home.mkdir()
        self.e.registry.write_text(json.dumps({"projects": {"github.com/Org/Other": {
            "mode": "private", "spec_root": str(self.tmp / "sdd/other"), "sync": "none"}}}), encoding="utf-8")
        for args in (("new", "--tier", "lite", "--title", "Corrige soma"), ("validate",), ("index",), ("status",)):
            out = self.e.run(*args)
            self.assertNotIn(BANNER, out.stderr, args)
        self.assertTrue(list((self.e.repo / "docs/specs").glob("SPEC-0001-*.md")))
        self.assertTrue((self.e.repo / "docs/specs/INDEX.md").exists())
        self.assertFalse((self.tmp / "sdd").exists())


def commit_file(env, rel, content, message):
    path = env.repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(env.repo, "add", "-A", env=env.env)
    git(env.repo, "commit", "-qm", message, env=env.env)


def pass_gates(spec: Path, *gates):
    """Prepara a tabela de gates para um teste que exercita um gate posterior (a ordem é exigida pelo gate)."""
    names = {"G0": "G0 Spec", "G1": "G1 Red", "G2": "G2 Green", "G3": "G3 Arquitetura", "G4": "G4 Review",
             "G5": "G5 Integração & CI", "H2": "H2 Integração aprovada", "G6": "G6 Deploy"}
    text = spec.read_text(encoding="utf-8")
    for g in gates:
        text = text.replace(f"| {names[g]} | PENDING | | |", f"| {names[g]} | PASS | preparado pelo teste | 2026-10-14 |")
    spec.write_text(text, encoding="utf-8")


class LeakPatternsTest(unittest.TestCase):
    SPEC_ROOT = Path("/home/u/sdd/org/repo")

    def test_default_patterns_find_each_mark_with_its_line(self):
        """SPEC-0004:UT-01"""
        text = ("// ver SPEC-0003\n"
                "segue o ADR-0006\n"
                "def test_x():  # SPEC-0003:UT-01\n"
                "## Mapa de Comportamentos\n"
                "specs em /home/u/sdd/org/repo/specs\n")
        found = sg.leak_findings(text, "a.py", sg.build_leak_patterns(self.SPEC_ROOT, [], adr_ids=["ADR-0006"]), [])
        self.assertEqual(sorted({line for _, line, _, _ in found}), [1, 2, 3, 4, 5], found)
        self.assertTrue(all(origin == "a.py" for origin, _, _, _ in found))

    def test_user_patterns_and_allowlist(self):
        """SPEC-0004:UT-02"""
        patterns = sg.build_leak_patterns(self.SPEC_ROOT, [r"\bProjetoFenix\b"])
        found = sg.leak_findings("x = 'ProjetoFenix'\ny = 'SPEC-0000-exemplo'\n", "b.py", patterns,
                                 ["SPEC-0000-exemplo"])
        self.assertEqual([(line, snippet) for _, line, _, snippet in found], [(1, "x = 'ProjetoFenix'")])

    def test_ordinary_code_is_clean(self):
        """SPEC-0004:UT-03 (guarda)"""
        text = ("def test_it_01_total(): assert soma(1, 1) == 2  # IT-01\n"
                "# a spec do cliente pede ADR sem número\n"
                "UT-01 = 'código de erro'\n")
        self.assertEqual(sg.leak_findings(text, "c.py", sg.build_leak_patterns(self.SPEC_ROOT, []), []), [])


class LeakCheckCommandTest(PrivateTestCase):
    def setUp(self):
        super().setUp()
        self.e.init()

    def test_reads_patterns_from_the_spec_root_config(self):
        """SPEC-0004:CT-01"""
        config = self.e.spec_root / "sdd-config.yml"
        config.write_text(config.read_text(encoding="utf-8") + '\nleak_patterns:\n  - "ProjetoFenix"\n', encoding="utf-8")
        (self.e.repo / "a.py").write_text(f"x = 'ProjetoFenix'\ny = '{self.e.spec_root}'\n", encoding="utf-8")
        git(self.e.repo, "add", "a.py", env=self.e.env)
        out = self.e.run("leak-check", "--staged")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("a.py:1", out.stdout)
        self.assertIn("a.py:2", out.stdout)

    def test_staged_diff(self):
        """SPEC-0004:IT-01"""
        commit_file(self.e, "src/a.py", "x = 1\n", "base")
        (self.e.repo / "src/a.py").write_text("x = 1\n// ver SPEC-0003\n", encoding="utf-8")
        git(self.e.repo, "add", "-A", env=self.e.env)
        out = self.e.run("leak-check", "--staged")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("src/a.py:2", out.stdout)

    def test_commit_message_in_range(self):
        """SPEC-0004:IT-02"""
        commit_file(self.e, "src/a.py", "x = 1\n", "corrige soma\n\nRefs: SPEC-0003")
        sha = git(self.e.repo, "rev-parse", "--short=7", "HEAD", env=self.e.env).strip()
        out = self.e.run("leak-check", "--range", "HEAD~1..HEAD")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn(f"commit {sha}", out.stdout)

    def test_branch_name(self):
        """SPEC-0004:IT-03"""
        out = self.e.run("leak-check", "--branch", "sdd/SPEC-0003-x")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("branch", out.stdout)

    def test_pre_push_hook_blocks_marks_and_lets_clean_pushes_through(self):
        """SPEC-0004:IT-04"""
        hook = Path(git(self.e.repo, "rev-parse", "--git-path", "hooks", env=self.e.env).strip())
        hook = (self.e.repo / hook / "pre-push") if not hook.is_absolute() else hook / "pre-push"
        self.assertTrue(hook.exists())
        bare = self.tmp / "team.git"
        git(self.tmp, "init", "-q", "--bare", str(bare), env=self.e.env)
        git(self.e.repo, "remote", "add", "team", str(bare), env=self.e.env)
        commit_file(self.e, "src/a.py", "x = 1\n", "soma")
        ok = subprocess.run(["git", "push", "-q", "team", "HEAD:refs/heads/limpa"], cwd=self.e.repo,
                            capture_output=True, text=True, env=self.e.env, check=False)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        commit_file(self.e, "src/a.py", "x = 2\n", "corrige\n\nRefs: SPEC-0003")
        bad = subprocess.run(["git", "push", "-q", "team", "HEAD:refs/heads/suja"], cwd=self.e.repo,
                             capture_output=True, text=True, env=self.e.env, check=False)
        self.assertNotEqual(bad.returncode, 0)
        self.assertNotIn("suja", git(bare, "branch", env=self.e.env))

    def test_wrong_regex_is_an_error(self):
        """SPEC-0004:IT-08"""
        config = self.e.spec_root / "sdd-config.yml"
        config.write_text(config.read_text(encoding="utf-8") + '\nleak_patterns:\n  - "(quebrada"\n', encoding="utf-8")
        out = self.e.run("leak-check", "--branch", "feat/x")
        self.assertEqual(out.returncode, 2)
        self.assertIn("(quebrada", out.stderr)

    def test_team_adrs_are_not_leaks_but_mine_are(self):
        """SPEC-0004:IT-11"""
        self.assertEqual(self.e.run("new-adr", "--title", "Minha decisão").returncode, 0)
        (self.e.repo / "a.py").write_text("# segue o ADR-0002 do time\n", encoding="utf-8")
        (self.e.repo / "b.py").write_text("# ver ADR-0001\n", encoding="utf-8")
        git(self.e.repo, "add", "a.py", "b.py", env=self.e.env)
        out = self.e.run("leak-check", "--staged")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("b.py:1", out.stdout)
        self.assertNotIn("a.py", out.stdout)

    def test_fifty_commits_in_under_two_seconds(self):
        """SPEC-0004:IT-10"""
        for i in range(50):
            commit_file(self.e, f"src/m{i}.py", f"x = {i}\n", f"passo {i}")
        start = time.monotonic()
        out = self.e.run("leak-check", "--range", "HEAD~50..HEAD")
        elapsed = time.monotonic() - start
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertLess(elapsed, 2.0)


class LeakIntegrationTest(PrivateTestCase):
    def test_team_hook_manager_prevents_installing_the_hook(self):
        """SPEC-0004:IT-05"""
        git(self.e.repo, "config", "core.hooksPath", ".team-hooks", env=self.e.env)
        out = self.e.init()
        self.assertIn("core.hooksPath", out.stdout)
        self.assertFalse((self.e.repo / ".git/hooks/pre-push").exists())
        self.assertFalse((self.e.repo / ".team-hooks").exists())
        other = PrivateEnv(self.tmp / "husky", remote_url="git@github.com:Org/Husky.git")
        (other.repo / ".husky").mkdir()
        other.spec_root = self.tmp / "sdd2"
        out = other.init()
        self.assertIn("husky", out.stdout)
        self.assertFalse((other.repo / ".git/hooks/pre-push").exists())

    def test_worktree_branch_and_folder_have_no_spec_id(self):
        """SPEC-0004:IT-06"""
        self.e.init()
        self.assertEqual(self.e.run("new", "--tier", "full", "--title", "Múltiplos cartões").returncode, 0)
        out = self.e.run("worktree", "SPEC-0001", "--create")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("feat/multiplos-cartoes", git(self.e.repo, "branch", "--list", env=self.e.env))
        self.assertNotIn("SPEC", out.stdout)

    def test_gate_with_leaked_commit_fails(self):
        """SPEC-0004:IT-07"""
        self.e.init()
        self.e.run("new", "--tier", "lite", "--title", "Corrige soma")
        spec = next((self.e.spec_root / "specs").glob("SPEC-0001-*.md"))
        pass_gates(spec, "G0", "G1", "G2", "G3")
        git(self.e.repo, "switch", "-q", "-c", "fix/corrige-soma", env=self.e.env)
        commit_file(self.e, "src/a.py", "x = 1\n", "corrige soma\n\nRefs: SPEC-0001")
        self.e.run("gate", "SPEC-0001", "G4", "--run", "--by", "revisor: APPROVED")
        row = next(line for line in spec.read_text(encoding="utf-8").splitlines() if line.startswith("| G4"))
        self.assertIn("FAIL", row)
        self.assertIn("vazamento", row)

    def test_full_mode_has_nothing_to_check(self):
        """SPEC-0004:IT-09 (guarda)"""
        out = self.e.run("leak-check")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("modo completo", out.stdout)


PLAN_LINE = "- **UT-01** — {{teste de regressão: Dado..., quando..., então...}}"
LITE_PLACEHOLDERS = {
    "{{CH-01 — comportamento atual preservado | Caracterização: N/A — área já coberta}}": "Caracterização: N/A — área coberta",
    "{{IT-01 ou E2E-01 — regressão no nível do defeito | Integração/E2E: N/A — motivo}}": "Integração: N/A — cálculo puro",
}


def write_plan(spec: Path, ut_line: str):
    """Plano do lite com um único teste (UT-01) e as outras categorias N/A."""
    text = spec.read_text(encoding="utf-8").replace(PLAN_LINE, ut_line)
    for placeholder, value in LITE_PLACEHOLDERS.items():
        text = text.replace(placeholder, value)
    spec.write_text(text, encoding="utf-8")
TEST_CMD = "test -f src/soma.py"


def gate_row(spec: Path, gate: str) -> str:
    return next(line for line in spec.read_text(encoding="utf-8").splitlines() if line.startswith(f"| {gate} "))


def sha7(env, rev="HEAD"):
    return git(env.repo, "rev-parse", "--short=7", rev, env=env.env).strip()


class TraceUnitTest(unittest.TestCase):
    def test_role_comes_from_the_files(self):
        """SPEC-0005:UT-01"""
        paths = sg.DEFAULT_TEST_PATHS
        self.assertEqual(sg.role_by_files(["tests/a_test.py"], paths), "red")
        self.assertEqual(sg.role_by_files(["src/a.py", "tests/a_test.py"], paths), "green")
        self.assertEqual(sg.role_by_files(["src/a.py"], paths), "green")

    def test_plan_line_target(self):
        """SPEC-0005:UT-02"""
        self.assertEqual(sg.parse_test_target("- **UT-01** — Dado x → tests/x.py::test_y"), ("tests/x.py", "test_y"))
        self.assertEqual(sg.parse_test_target("- **UT-01** — Dado x -> tests/x.py::test_y"), ("tests/x.py", "test_y"))
        self.assertIsNone(sg.parse_test_target("- **UT-01** — Dado x, quando y, então z."))


class TraceTestCase(PrivateTestCase):
    """Repositório em modo privado com uma spec lite cujo teste do plano aponta tests/test_soma.py::test_soma."""

    target = "tests/test_soma.py::test_soma"

    def setUp(self):
        super().setUp()
        self.e.init()
        config = self.e.spec_root / "sdd-config.yml"
        config.write_text(config.read_text(encoding="utf-8").replace('test: ""', f'test: "{TEST_CMD}"'), encoding="utf-8")
        self.e.run("new", "--tier", "lite", "--title", "Corrige soma")
        self.spec = next((self.e.spec_root / "specs").glob("SPEC-0001-*.md"))
        write_plan(self.spec, f"- **UT-01** — Dado 1 e 1, quando soma, então 2 → {self.target}")
        self.e.run("set", "SPEC-0001", "touches=[src/**, tests/**]")
        git(self.e.repo, "switch", "-q", "-c", "fix/corrige-soma", env=self.e.env)

    def red(self):
        commit_file(self.e, "tests/test_soma.py", "def test_soma():\n    assert soma(1, 1) == 2\n", "adiciona teste da soma")
        return sha7(self.e)

    def green(self):
        commit_file(self.e, "src/soma.py", "def soma(a, b):\n    return a + b\n", "implementa a soma")
        return sha7(self.e)

    def verify(self):
        return self.e.run("verify", "SPEC-0001").stdout


class TraceVerifyTest(TraceTestCase):
    def test_config_comes_from_the_spec_root(self):
        """SPEC-0005:CT-01"""
        config = self.e.spec_root / "sdd-config.yml"
        config.write_text(config.read_text(encoding="utf-8") + '\ntest_paths:\n  - "checks/**"\n', encoding="utf-8")
        text = self.spec.read_text(encoding="utf-8").replace(self.target, "checks/soma_check.py::test_soma")
        self.spec.write_text(text, encoding="utf-8")
        self.e.run("set", "SPEC-0001", "touches=[src/**, checks/**]")
        commit_file(self.e, "checks/soma_check.py", "def test_soma(): pass\n", "adiciona checagem")
        self.green()
        out = self.verify()
        self.assertIn("[G1] PASS  Red antes do Green", out)
        self.assertNotIn("[G1] FAIL", out)

    def test_red_before_green_without_marks(self):
        """SPEC-0005:IT-01"""
        self.red()
        self.green()
        out = self.verify()
        self.assertIn("[G1] PASS  Red antes do Green", out)
        self.assertNotIn("[G1] FAIL", out)
        self.assertIn("[G4] PASS", out)

    def test_green_before_red_fails(self):
        """SPEC-0005:IT-02"""
        early = self.green()
        self.red()
        out = self.verify()
        self.assertIn("[G1] FAIL  implementação antes dos testes", out)
        self.assertIn(early, out)

    def test_missing_planned_test_fails(self):
        """SPEC-0005:IT-03"""
        self.spec.write_text(self.spec.read_text(encoding="utf-8").replace("::test_soma", "::test_inexistente"),
                             encoding="utf-8")
        self.red()
        self.green()
        out = self.verify()
        self.assertIn("tests/test_soma.py::test_inexistente", out)
        self.assertIn("UT-01", out)

    def test_commits_are_recorded_in_the_spec_root(self):
        """SPEC-0005:IT-08"""
        pass_gates(self.spec, "G0")
        red, green = self.red(), self.green()
        self.e.run("gate", "SPEC-0001", "G1", "--run", "--at", red)
        self.e.run("gate", "SPEC-0001", "G2", "--run")
        text = self.spec.read_text(encoding="utf-8")
        self.assertIn("## Commits", text)
        rows = [line for line in text.splitlines() if line.startswith(("| red ", "| green "))]
        self.assertTrue(any(red in r for r in rows) and any(green in r for r in rows), rows)
        self.assertTrue(all(len(r.split("|")[3].strip()) >= 7 for r in rows), rows)
        self.assertEqual(self.e.repo_status(), "")
        self.assertIn("sdd: gate", "\n".join(self.e.root_log()))


class GateAtRedCommitTest(TraceTestCase):
    def test_g1_at_red_commit_in_private_and_full_modes(self):
        """SPEC-0005:IT-04"""
        pass_gates(self.spec, "G0")
        red = self.red()
        self.green()
        self.e.run("gate", "SPEC-0001", "G1", "--run", "--at", red)
        row = gate_row(self.spec, "G1")
        self.assertIn("PASS", row)
        self.assertIn(red, row)
        self.assertEqual(self.e.run("gate", "SPEC-0001", "G1", "--run", "--at", "0123abc").returncode, 2)
        self.assertEqual(len(git(self.e.repo, "worktree", "list", env=self.e.env).splitlines()), 1)

        full = PrivateEnv(self.tmp / "full", remote_url=None)
        (full.repo / "docs/specs").mkdir(parents=True)
        (full.repo / "docs/specs/sdd-config.yml").write_text(f'base_branch: main\ntest: "{TEST_CMD}"\n', encoding="utf-8")
        git(full.repo, "add", "-A", env=full.env)
        git(full.repo, "commit", "-qm", "chore: sdd", env=full.env)
        full.run("new", "--tier", "lite", "--title", "Corrige soma")
        spec = next((full.repo / "docs/specs").glob("SPEC-0001-*.md"))
        write_plan(spec, "- **UT-01** — Dado 1 e 1, então 2")
        pass_gates(spec, "G0")
        full.run("set", "SPEC-0001", "touches=[src/**, tests/**, docs/**]")
        git(full.repo, "add", "-A", env=full.env)
        git(full.repo, "commit", "-qm", "docs: spec\n\nRefs: SPEC-0001", env=full.env)
        git(full.repo, "switch", "-q", "-c", "sdd/SPEC-0001", env=full.env)
        commit_file(full, "tests/test_soma.py", "# SPEC-0001:UT-01\ndef test_soma(): pass\n", "test: soma\n\nRefs: SPEC-0001")
        full_red = sha7(full)
        commit_file(full, "src/soma.py", "def soma(a, b): return a + b\n", "fix: soma\n\nRefs: SPEC-0001")
        full.run("gate", "SPEC-0001", "G1", "--run")
        row = gate_row(spec, "G1")
        self.assertIn("FAIL", row)
        self.assertIn("--at", row)
        git(full.repo, "add", "-A", env=full.env)
        git(full.repo, "commit", "-qm", "docs: registra G1\n\nRefs: SPEC-0001", env=full.env)
        full.run("gate", "SPEC-0001", "G1", "--run", "--at", full_red)
        row = gate_row(spec, "G1")
        self.assertIn("PASS", row)
        self.assertIn(full_red, row)


class MergeDetectionTest(TraceTestCase):
    def deliver(self):
        """Red, green e G1 registrado (o registro de commits guarda SHAs e patch-ids); depois volta para a main."""
        pass_gates(self.spec, "G0")
        red = self.red()
        self.green()
        self.e.run("gate", "SPEC-0001", "G1", "--run", "--at", red)
        git(self.e.repo, "switch", "-q", "main", env=self.e.env)
        pass_gates(self.spec, "G2", "G3", "G4", "G5", "H2", "G6")

    def test_squash(self):
        """SPEC-0005:IT-05"""
        self.deliver()
        git(self.e.repo, "merge", "-q", "--squash", "fix/corrige-soma", env=self.e.env)
        git(self.e.repo, "commit", "-qm", "Corrige soma (#12)", env=self.e.env)
        self.e.run("gate", "SPEC-0001", "G7", "--run")
        row = gate_row(self.spec, "G7")
        self.assertIn("squash", row)
        self.assertIn(sha7(self.e), row)

    def test_rebase(self):
        """SPEC-0005:IT-06"""
        self.deliver()
        commit_file(self.e, "docs/outra.md", "mudança do time\n", "outra mudança do time")
        commits = git(self.e.repo, "rev-list", "--reverse", "main..fix/corrige-soma", env=self.e.env).split()
        git(self.e.repo, "cherry-pick", *commits, env=self.e.env)
        self.e.run("gate", "SPEC-0001", "G7", "--run")
        self.assertIn("rebase", gate_row(self.spec, "G7"))

    def test_merge_commit_and_missing_merge(self):
        """SPEC-0005:IT-07"""
        self.deliver()
        self.e.run("gate", "SPEC-0001", "G7", "--run")
        row = gate_row(self.spec, "G7")
        self.assertIn("FAIL", row)
        self.assertIn("não encontrado", row)
        git(self.e.repo, "merge", "-q", "--no-ff", "fix/corrige-soma", "-m", "Merge feature", env=self.e.env)
        self.e.run("gate", "SPEC-0001", "G7", "--run")
        self.assertIn("merge", gate_row(self.spec, "G7"))


class FullModeVerifyGuardTest(PrivateTestCase):
    def test_full_mode_verify_still_uses_messages_and_tags(self):
        """SPEC-0005:IT-09 (guarda)"""
        repo = self.e
        (repo.repo / "docs/specs").mkdir(parents=True)
        (repo.repo / "docs/specs/sdd-config.yml").write_text("base_branch: main\n", encoding="utf-8")
        git(repo.repo, "add", "-A", env=repo.env)
        git(repo.repo, "commit", "-qm", "chore: sdd", env=repo.env)
        repo.run("new", "--tier", "lite", "--title", "Corrige soma")
        spec = next((repo.repo / "docs/specs").glob("SPEC-0001-*.md"))
        write_plan(spec, "- **UT-01** — Dado 1 e 1, então 2")
        repo.run("set", "SPEC-0001", "touches=[src/**, tests/**]")
        git(repo.repo, "add", "-A", env=repo.env)
        git(repo.repo, "commit", "-qm", "docs: spec\n\nRefs: SPEC-0001", env=repo.env)
        git(repo.repo, "switch", "-q", "-c", "sdd/SPEC-0001", env=repo.env)
        commit_file(repo, "tests/test_soma.py", "# SPEC-0001:UT-01\n", "test: soma\n\nRefs: SPEC-0001")
        commit_file(repo, "src/soma.py", "x = 1\n", "fix: soma\n\nRefs: SPEC-0001")
        out = repo.run("verify", "SPEC-0001").stdout
        self.assertIn("[G1] PASS  Red antes do Green", out)
        self.assertIn("rastreabilidade: 1/1", out)
        self.assertNotIn("[G1] FAIL", out)


TEAM_TEMPLATE = "## Summary\n<!-- what changes and why -->\n\n## How to test\n\n## Checklist\n- [ ] tests pass\n"


def fill_lite(spec: Path, ut_line: str):
    """Spec lite completa (sem marcadores), com um único teste no plano."""
    write_plan(spec, ut_line)
    text = spec.read_text(encoding="utf-8")
    text = text.replace("{{- [ ] dúvida que precisa de resposta e quem responde | Nenhuma}}", "Nenhuma")
    text = text.replace("{{Comportamento atual vs. esperado. Para bug: passos de reprodução, ambiente e impacto.}}",
                        "A soma de 1 e 1 devolve 3 em vez de 2.")
    text = re.sub(r"\{\{([^{}|]*)(?:\|[^{}]*)?\}\}", lambda m: m.group(1).strip(), text)
    spec.write_text(text, encoding="utf-8")


def fill_delivery(spec: Path, red: str, green: str):
    """Relatório de Entrega do lite preenchido e Definição de Pronto marcada (o G7 exige)."""
    text = spec.read_text(encoding="utf-8")
    for heading, body in (("### O que foi entregue", "A soma volta a devolver 2 para 1 e 1."),
                          ("### Como foi feito", "Correção do operador na função soma."),
                          ("### Deploy", "N/A — sem deploy no teste."), ("### Pendências", "Nenhuma")):
        text = text.replace(heading + "\n", f"{heading}\n{body}\n", 1)
    text = text.replace("### Prova de Correção\n<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa "
                        "depois (commit green + execução). Outros tipos: \"N/A\". -->",
                        f"### Prova de Correção\nUT-01 falhou em {red} e passa em {green}.")
    text = text.replace("| Teste | Comportamento | Resultado | Evidência |\n|---|---|---|---|",
                        f"| Teste | Comportamento | Resultado | Evidência |\n|---|---|---|---|\n| UT-01 | soma 1 e 1 | PASS | {green} |")
    start = text.index("### Definição de Pronto")
    end = text.index("### Deploy")
    text = text[:start] + text[start:end].replace("- [ ]", "- [x]") + text[end:]
    spec.write_text(text, encoding="utf-8")


class TeamConventionsUnitTest(unittest.TestCase):
    def test_detection_from_history_and_files(self):
        """SPEC-0006:UT-01"""
        merges = sg.detect_team_conventions([2, 2, 1, 2, 2], ["feat: a", "fix(x): b", "chore: c", "docs: d", "feat: e"],
                                            {".husky", ".github/pull_request_template.md"})
        self.assertEqual(merges, {"merge": "merge", "commits": "conventional", "hooks": "husky",
                                  "pr_template": ".github/pull_request_template.md"})
        linear = sg.detect_team_conventions([1, 1, 1], ["Ajusta tela", "corrige bug do login", "WIP"], set())
        self.assertEqual(linear, {"merge": "linear", "commits": "livre", "hooks": "nenhum", "pr_template": ""})
        empty = sg.detect_team_conventions([], [], set(), hooks_path=".hooks")
        self.assertEqual(empty, {"merge": "desconhecida", "commits": "desconhecida", "hooks": "core.hooksPath",
                                 "pr_template": ""})

    def test_pr_title_follows_the_team(self):
        """SPEC-0006:UT-02"""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        e = PrivateEnv(tmp)
        e.init()
        e.run("new", "--tier", "full", "--title", "Suporte a múltiplos cartões")
        config = e.spec_root / "sdd-config.yml"
        base = config.read_text(encoding="utf-8")
        for style, expected in (("conventional", "feat: suporte a múltiplos cartões"),
                                ("livre", "Suporte a múltiplos cartões")):
            config.write_text(base + f"\nteam:\n  commits: {style}\n", encoding="utf-8")
            title = e.run("pr", "SPEC-0001", "--title").stdout.strip()
            self.assertEqual(title, expected)
            self.assertNotIn("SPEC", title)

    def test_agent_instructions_cover_the_private_mode(self):
        """SPEC-0006:UT-03"""
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/private-mode.md", skill)
        guide = (SKILL / "references" / "private-mode.md").read_text(encoding="utf-8")
        headings = [line[3:] for line in guide.splitlines() if line.startswith("## ")]
        for topic in ("Ativação", "Onde fica o quê", "Commits e branch", "Gates", "Leak-check", "Limites"):
            self.assertTrue(any(topic in h for h in headings), topic)


class TeamConventionsTest(PrivateTestCase):
    def test_init_detects_and_records_team_conventions(self):
        """SPEC-0006:IT-01"""
        (self.e.repo / ".husky").mkdir()
        (self.e.repo / ".husky/pre-commit").write_text("npm test\n", encoding="utf-8")
        commit_file(self.e, ".github/pull_request_template.md", TEAM_TEMPLATE, "chore: template de PR")
        for i in range(30):
            git(self.e.repo, "switch", "-q", "-c", f"f{i}", env=self.e.env)
            commit_file(self.e, f"src/m{i}.py", f"x = {i}\n", f"feat: módulo {i}")
            git(self.e.repo, "switch", "-q", "main", env=self.e.env)
            git(self.e.repo, "merge", "-q", "--no-ff", f"f{i}", "-m", f"Merge pull request #{i}", env=self.e.env)
        out = self.e.init()
        self.assertIn("Detectado:", out.stdout)
        config = sg.parse_yaml_subset((self.e.spec_root / "sdd-config.yml").read_text(encoding="utf-8"))
        self.assertEqual(config["team"], {"merge": "merge", "commits": "conventional", "hooks": "husky",
                                          "pr_template": ".github/pull_request_template.md"})
        start = time.monotonic()
        self.assertEqual(self.e.run("private", "detect").returncode, 0)
        self.assertLess(time.monotonic() - start, 1.5)


class NeutralPrTest(PrivateTestCase):
    def prepare(self, template=None):
        if template:
            commit_file(self.e, ".github/pull_request_template.md", template, "chore: template de PR")
        self.e.init()
        self.e.run("new", "--tier", "lite", "--title", "Corrige soma")
        self.spec = next((self.e.spec_root / "specs").glob("SPEC-0001-*.md"))
        fill_lite(self.spec, "- **UT-01** — Dado 1 e 1, quando soma, então 2 → tests/test_soma.py::test_soma")

    def test_fills_the_team_template(self):
        """SPEC-0006:IT-02"""
        self.prepare(TEAM_TEMPLATE)
        out = self.e.run("pr", "SPEC-0001", "--out", str(self.tmp / "pr.md"))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        body = (self.tmp / "pr.md").read_text(encoding="utf-8")
        self.assertIn("## Summary", body)
        self.assertIn("## How to test", body)
        summary = body.split("## Summary", 1)[1].split("## How to test", 1)[0]
        self.assertIn("A soma de 1 e 1 devolve 3", summary)
        tests = body.split("## How to test", 1)[1].split("## Checklist", 1)[0]
        self.assertIn("Dado 1 e 1, quando soma, então 2", tests)
        self.assertIn("## Checklist\n- [ ] tests pass", body)
        self.assertEqual(self.e.run("leak-check", "--message", str(self.tmp / "pr.md")).returncode, 0)

    def test_neutral_body_without_template(self):
        """SPEC-0006:IT-03"""
        self.prepare()
        out = self.e.run("pr", "SPEC-0001")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        for heading in ("## O que muda", "## Como testar", "## Riscos e rollback"):
            self.assertIn(heading, out.stdout)
        for mark in ("SPEC-", "<!-- sdd", "Gates", "Refs:", "UT-01"):
            self.assertNotIn(mark, out.stdout)

    def test_leaking_body_is_refused(self):
        """SPEC-0006:IT-04"""
        self.prepare()
        self.e.run("new-adr", "--title", "Decisão minha")
        self.spec.write_text(self.spec.read_text(encoding="utf-8").replace(
            "A soma de 1 e 1 devolve 3 em vez de 2.", "A soma devolve 3 em vez de 2, ver ADR-0001."), encoding="utf-8")
        out = self.e.run("pr", "SPEC-0001", "--out", str(self.tmp / "pr.md"))
        self.assertEqual(out.returncode, 1)
        self.assertIn("ADR-0001", out.stdout + out.stderr)
        self.assertFalse((self.tmp / "pr.md").exists())

    def test_full_mode_pr_is_unchanged(self):
        """SPEC-0006:IT-06 (guarda)"""
        (self.e.repo / "docs/specs").mkdir(parents=True)
        (self.e.repo / "docs/specs/sdd-config.yml").write_text("base_branch: main\n", encoding="utf-8")
        self.e.run("new", "--tier", "lite", "--title", "Corrige soma")
        out = self.e.run("pr", "SPEC-0001")
        self.assertIn("[SPEC-0001]", out.stdout.splitlines()[0])
        self.assertIn("<!-- sdd: SPEC-0001", out.stdout)
        self.assertIn("## Gates", out.stdout)


class ModeConsumerContractTest(PrivateTestCase):
    def test_pr_reads_team_block_from_the_spec_root_config(self):
        """SPEC-0006:CT-01"""
        self.e.init()
        self.e.run("new", "--tier", "lite", "--title", "Corrige soma")
        config = self.e.spec_root / "sdd-config.yml"
        config.write_text(config.read_text(encoding="utf-8") + "\nteam:\n  commits: livre\n", encoding="utf-8")
        (self.e.repo / "docs/specs").mkdir(parents=True)
        (self.e.repo / "docs/specs/sdd-config.yml").write_text("team:\n  commits: conventional\n", encoding="utf-8")
        self.assertEqual(self.e.run("pr", "SPEC-0001", "--title").stdout.strip(), "Corrige soma")


class PrivateJourneyTest(PrivateTestCase):
    def test_whole_private_journey_leaves_no_mark(self):
        """SPEC-0006:IT-05"""
        e = self.e
        commit_file(e, "src/soma.py", "def soma(a, b):\n    return a + b + 1\n", "Primeira versão da soma")
        e.init()
        config = e.spec_root / "sdd-config.yml"
        config.write_text(config.read_text(encoding="utf-8")
                          .replace('test: ""', 'test: "grep -q \'return a + b$\' src/soma.py"')
                          .replace('arch_test: ""', 'arch_test: "true"').replace('ci: ""', 'ci: "true"'),
                          encoding="utf-8")
        e.run("new", "--tier", "lite", "--title", "Corrige soma")
        spec = next((e.spec_root / "specs").glob("SPEC-0001-*.md"))
        fill_lite(spec, "- **UT-01** — Dado 1 e 1, quando soma, então 2 → tests/test_soma.py::test_soma")
        e.run("set", "SPEC-0001", "touches=[src/**, tests/**]", "status=approved", "approved_by=thomas", "approved_at=today")
        self.assertIn("PASS", e.run("gate", "SPEC-0001", "G0", "--run").stdout)
        out = e.run("worktree", "SPEC-0001", "--create")
        wt = Path(out.stdout.splitlines()[0].split(": ", 1)[1])
        work = PrivateEnv.__new__(PrivateEnv)
        work.__dict__.update(e.__dict__, repo=wt)
        commit_file(work, "tests/test_soma.py", "from src.soma import soma\n\n\ndef test_soma():\n    assert soma(1, 1) == 2\n",
                    "Adiciona teste da soma")
        red = sha7(work)
        e.run("gate", "SPEC-0001", "G1", "--run", "--cwd", str(wt))
        commit_file(work, "src/soma.py", "def soma(a, b):\n    return a + b\n", "Corrige a soma")
        green = sha7(work)
        for gate, extra in (("G2", ()), ("G3", ()), ("G4", ("--by", "revisor: APPROVED")), ("G5", ())):
            e.run("gate", "SPEC-0001", gate, "--run", "--cwd", str(wt), *extra)
        e.run("gate", "SPEC-0001", "H2", "--by", "thomas")
        e.run("gate", "SPEC-0001", "G6", "--na", "sem deploy no teste — SPEC-0001")
        pr = self.tmp / "pr.md"
        self.assertEqual(e.run("pr", "SPEC-0001", "--out", str(pr)).returncode, 0)
        git(e.repo, "merge", "-q", "--squash", "fix/corrige-soma", env=e.env)
        git(e.repo, "commit", "-qm", "Corrige soma (#7)", env=e.env)
        fill_delivery(spec, red, green)
        e.run("gate", "SPEC-0001", "G7", "--run")

        for leftover in ("docs/specs", "docs/adr", "tools/sdd", ".githooks"):
            self.assertFalse((e.repo / leftover).exists(), leftover)
        zero = "0" * 40
        scan = e.run("leak-check", "--range", f"{zero}..main", "--branch", "fix/corrige-soma", "--message", str(pr))
        self.assertEqual(scan.returncode, 0, scan.stdout)
        for gate in ("G1", "G2", "G4", "G7"):
            self.assertIn("| PASS |", gate_row(spec, gate), gate)
        self.assertIn("ci exit 0", gate_row(spec, "G5"))
        self.assertIn("squash", gate_row(spec, "G7"))


if __name__ == "__main__":
    unittest.main()
