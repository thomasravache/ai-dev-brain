"""Modo privado (SPEC-0002): o estado do SDD fica fora do repositório do time (ADR-0006).

Cada teste isola HOME, SDD_CONFIG_HOME e XDG_* num diretório temporário: nada lê ou grava o registro real.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
        for args in (("new", "--tier", "lite", "--title", "Corrige soma"), ("set", "SPEC-0001", "size=S"),
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


if __name__ == "__main__":
    unittest.main()
