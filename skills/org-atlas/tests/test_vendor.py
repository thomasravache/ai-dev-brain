"""vendor --ci, chave ci e modos do atlas (SPEC-0040, contrato v2: UT-01 a UT-04 e IT-01 a IT-03).

Contrato da seção 6 que estes testes conferem (pela CLI; o Implementer escolhe as funções internas):

    atlas-config.yml:
      ci:
        env: [GH_TOKEN, ARGOCD_AUTH_TOKEN]     # só nomes (^[A-Z_][A-Z0-9_]*$); fora disso = exit 2
        schedule: "0 6 * * 1"

    atlas.py vendor --ci github|generic [--schedule CRON] [--force]
        Usa o atlas desta máquina (configuração local, como scan e lint).
        github : .github/workflows/atlas-scan.yml — schedule + workflow_dispatch (scan, lint, branch
                 atlas/scan-AAAA-MM-DD, gh pr create quando há mudança) e pull_request (lint); cada nome de ci.env
                 vira `NOME: ${{ secrets.NOME }}`; permissões só contents: write e pull-requests: write; toda ação
                 fixada por SHA de 40 caracteres.
        generic: ci/atlas-scan.sh — scan e lint; exit 0 sem mudança, 10 com mudança, 1 com falha.
        Nos dois: cópia da skill em .org-atlas/skill/ (scripts/atlas.py, assets/collectors/ e o que o scan usa),
                 sempre sobrescrita; workflow e script rodam python3 .org-atlas/skill/scripts/atlas.py; no CI,
                 init --join --atlas "$PWD" com ATLAS_CONFIG_HOME temporário (mantém o que já vier definido);
                 "mudança" = git status --porcelain não vazio depois do scan.
        Agenda: --schedule, senão ci.schedule, senão "0 6 * * 1".
        Arquivo igual: "já atualizado"; diferente sem --force: mantido, "customizado — N linha(s) diferem; use
                 --force para sobrescrever"; com --force: sobrescrito.
        mode: local: exit 2 "vendor --ci é do modo repo — veja references/modes.md".
    config, doctor e lint conhecem a chave ci; ci.env inválido sai com 2 também no config.

Valores parecidos com segredo são montados em tempo de execução (nunca literais no arquivo).
"""
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from helpers import SCRIPT, SKILL, Sandbox, doctor_lines, output

SPEC = "SPEC-0040"
WORKFLOW = Path(".github/workflows/atlas-scan.yml")
GENERIC = Path("ci/atlas-scan.sh")
COPY = Path(".org-atlas/skill")
COPY_SCRIPT = COPY / "scripts" / "atlas.py"
COPY_CALL = "python3 .org-atlas/skill/scripts/atlas.py"
DEFAULT_SCHEDULE = "0 6 * * 1"
LOCAL_MESSAGE = "vendor --ci é do modo repo — veja references/modes.md"
CI_BLOCK = 'ci:\n  env: [GH_TOKEN, ARGOCD_AUTH_TOKEN]\n  schedule: "{schedule}"\n'
SHA_USES = re.compile(r"^\s*-?\s*uses:\s*[^\s@]+@[0-9a-f]{40}(\s+#.*)?\s*$")
USES = re.compile(r"^\s*-?\s*uses:", re.MULTILINE)
PERMISSION = re.compile(r"^\s*(actions|checks|contents|deployments|id-token|issues|discussions|packages|pages|"
                        r"pull-requests|repository-projects|security-events|statuses|attestations|models)"
                        r":\s*(read|write|none)\s*(#.*)?$", re.MULTILINE)
HAS_GIT = shutil.which("git") is not None

FAKE_COLLECTOR = '''"""Coletor falso do IT-03 (SPEC-0040): a saída depende de FAKE_STATE (v1 | v2 | fail)."""
import json
import os
import sys

state = os.environ.get("FAKE_STATE", "v1")
if state == "fail":
    print("coletor falso falhou", file=sys.stderr)
    sys.exit(1)
names = ["a", "b"] if state == "v1" else ["a", "c"]
print(json.dumps({
    "contract": "org-atlas/collector@1",
    "collector": "fake",
    "category": "code",
    "collected_at": "2026-11-12T06:00:00Z",
    "entities": [{"kind": "repository", "id": "acme/" + n, "name": n, "attrs": {"default_branch": "main"},
                  "source": "fake"} for n in names],
    "relations": [],
}))
'''


def secret_like():
    """Valor com cara de token (nunca literal no arquivo)."""
    return "ghp_" + "Q7x" * 12


class VendorCase(unittest.TestCase):
    """Atlas novo no modo repo (init pela CLI), com a configuração local isolada no Sandbox."""

    mode = "repo"

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.box.atlas.mkdir(parents=True)
        out = self.box.init(mode=self.mode)
        self.assertEqual(out.returncode, 0, output(out))
        self.atlas = self.box.atlas

    # ------------------------------------------------------------------ apoio

    def shared_path(self):
        return self.atlas / "atlas-config.yml"

    def add_to_config(self, text):
        path = self.shared_path()
        old = path.read_text(encoding="utf-8")
        if not old.endswith("\n"):
            old += "\n"
        path.write_text(old + text, encoding="utf-8")

    def add_ci(self, schedule=DEFAULT_SCHEDULE):
        self.add_to_config(CI_BLOCK.format(schedule=schedule))

    def vendor(self, *args):
        return self.box.run("vendor", *args)

    def assert_vendor_ran(self, result, code=0):
        """O comando vendor existe (argparse não recusou) e saiu com `code`."""
        text = output(result)
        self.assertNotIn("usage:", text, f"vendor não é um comando do atlas.py ({SPEC}): {text}")
        self.assertEqual(result.returncode, code, text)

    def read(self, rel):
        path = self.atlas / rel
        self.assertTrue(path.is_file(), f"{rel} não foi gerado: {sorted(p.name for p in self.atlas.iterdir())}")
        return path.read_text(encoding="utf-8")

    def workflow(self, *extra):
        out = self.vendor("--ci", "github", *extra)
        self.assert_vendor_ran(out)
        return self.read(WORKFLOW)

    def assert_nothing_written(self):
        for rel in (".github", "ci", ".org-atlas"):
            self.assertFalse((self.atlas / rel).exists(), f"{rel} não devia existir")


def cron_of(text):
    """Valores de cron: no workflow (aspas simples ou duplas, ou sem aspas)."""
    return [m.group(2) for m in re.finditer(r"cron:\s*(['\"]?)([^'\"\n#]+?)\1\s*(#.*)?$", text, re.MULTILINE)]


# --------------------------------------------------------------------------- unitários


class WorkflowContentTest(VendorCase):
    def test_workflow_has_schedule_env_from_secrets_minimal_permissions_and_actions_pinned_by_sha(self):
        """SPEC-0040:UT-01"""
        self.add_ci()
        text = self.workflow("--schedule", "15 3 * * 2")
        self.assertEqual(cron_of(text), ["15 3 * * 2"], text)
        for name in ("GH_TOKEN", "ARGOCD_AUTH_TOKEN"):
            with self.subTest(env=name):
                self.assertRegex(text, rf"(?m)^\s*{name}:\s*\$\{{\{{\s*secrets\.{name}\s*\}}\}}\s*$")
        permissions = {(m.group(1), m.group(2)) for m in PERMISSION.finditer(text)}
        self.assertEqual(permissions, {("contents", "write"), ("pull-requests", "write")}, text)
        self.assertNotRegex(text, r"(?m)^\s*permissions:\s*(write-all|read-all)")
        uses = [line for line in text.splitlines() if USES.match(line)]
        self.assertTrue(uses, "nenhuma ação (uses:) no workflow")
        for line in uses:
            with self.subTest(uses=line.strip()):
                self.assertRegex(line, SHA_USES)

    def test_workflow_triggers_and_steps(self):
        """SPEC-0040:UT-01 (gatilhos e passos: scan, lint, branch atlas/scan-, gh pr create, init --join)"""
        self.add_ci()
        text = self.workflow()
        for word in ("schedule:", "workflow_dispatch", "pull_request", "gh pr create", "atlas/scan-",
                     "init --join", "ATLAS_CONFIG_HOME", f"{COPY_CALL} scan", f"{COPY_CALL} lint"):
            with self.subTest(word=word):
                self.assertIn(word, text)
        self.assertNotIn(str(SKILL), text, "caminho absoluto da skill no workflow")

    def test_schedule_precedence(self):
        """SPEC-0040:UT-01 (agenda: --schedule, senão ci.schedule, senão "0 6 * * 1")"""
        self.assertEqual(cron_of(self.workflow()), [DEFAULT_SCHEDULE], "sem ci nem --schedule")
        self.add_ci(schedule="30 4 * * 5")
        self.assertEqual(cron_of(self.workflow("--force")), ["30 4 * * 5"], "ci.schedule")
        self.assertEqual(cron_of(self.workflow("--force", "--schedule", "0 1 * * *")), ["0 1 * * *"],
                         "--schedule vence ci.schedule")


class InvalidEnvTest(VendorCase):
    def test_env_value_that_is_not_a_variable_name_exits_2_without_echo_or_writes(self):
        """SPEC-0040:UT-02"""
        for bad in (secret_like(), "gh_token", "GH-TOKEN", "1TOKEN", "GH_TOKEN=abc"):
            with self.subTest(value=bad[:4]):
                path = self.shared_path()
                original = path.read_text(encoding="utf-8")
                self.add_to_config(f'ci:\n  env: [GH_TOKEN, "{bad}"]\n')
                try:
                    for kind in ("github", "generic"):
                        out = self.vendor("--ci", kind)
                        self.assert_vendor_ran(out, 2)
                        self.assertNotIn(bad, output(out), "a mensagem repete o valor recebido")
                        self.assert_nothing_written()
                finally:
                    path.write_text(original, encoding="utf-8")


# --------------------------------------------------------------------------- integração


class SkillCopyTest(VendorCase):
    def assert_copy_is_current(self):
        copy = self.atlas / COPY_SCRIPT
        self.assertTrue(copy.is_file(), f"{COPY_SCRIPT} não existe")
        self.assertEqual(copy.read_bytes(), SCRIPT.read_bytes(), "a cópia difere do atlas.py da skill")
        collectors = sorted(p.name for p in (SKILL / "assets" / "collectors").iterdir() if p.is_file())
        self.assertTrue(collectors)
        for name in collectors:
            with self.subTest(collector=name):
                copied = self.atlas / COPY / "assets" / "collectors" / name
                self.assertTrue(copied.is_file(), f"coletor {name} não foi copiado")
                self.assertEqual(copied.read_bytes(), (SKILL / "assets" / "collectors" / name).read_bytes())

    def test_vendor_copies_the_skill_always_overwritten_and_both_files_call_the_copy(self):
        """SPEC-0040:UT-03"""
        workflow = self.workflow()
        self.assert_copy_is_current()
        out = self.vendor("--ci", "generic")
        self.assert_vendor_ran(out)
        script = self.read(GENERIC)
        self.assert_copy_is_current()
        for name, text in (("workflow", workflow), ("script", script)):
            with self.subTest(file=name):
                self.assertIn(COPY_CALL, text)
                self.assertNotIn(str(SKILL), text, "caminho absoluto da skill")
        (self.atlas / COPY_SCRIPT).write_text("# alterado à mão\n", encoding="utf-8")
        out = self.vendor("--ci", "generic")
        self.assert_vendor_ran(out)
        self.assertIn("já atualizado", output(out))
        self.assert_copy_is_current()

    def test_copy_is_overwritten_even_when_the_workflow_is_customized(self):
        """SPEC-0040:UT-03 (a cópia é sempre sobrescrita, mesmo sem --force)"""
        self.workflow()
        path = self.atlas / WORKFLOW
        path.write_text(path.read_text(encoding="utf-8") + "# customizado\n", encoding="utf-8")
        collector = self.atlas / COPY / "assets" / "collectors" / "github.py"
        collector.write_text("# alterado à mão\n", encoding="utf-8")
        out = self.vendor("--ci", "github")
        self.assert_vendor_ran(out)
        self.assertTrue(path.read_text(encoding="utf-8").endswith("# customizado\n"), "workflow não foi mantido")
        self.assert_copy_is_current()


class CiKeyTest(VendorCase):
    def test_config_doctor_and_lint_know_the_ci_key(self):
        """SPEC-0040:UT-04"""
        self.add_ci()
        config = self.box.config_json()
        self.assertIn("ci", config["values"], "config não conhece a chave ci")
        self.assertEqual(config["origins"].get("ci"), "atlas")
        ci = config["values"]["ci"]
        self.assertEqual([str(n) for n in ci["env"]], ["GH_TOKEN", "ARGOCD_AUTH_TOKEN"])
        self.assertEqual(str(ci["schedule"]), DEFAULT_SCHEDULE)

        doctor = self.box.run("doctor")
        rows = doctor_lines(output(doctor))
        self.assertEqual(doctor.returncode, 0, output(doctor))
        self.assertFalse([r for r in rows if r[0] == "ERRO"], rows)

        lint = self.box.run("lint", "--json")
        self.assertIn(lint.returncode, (0, 1), output(lint))
        findings = json.loads(lint.stdout)["findings"]
        unknown = [x for x in findings if x["rule"] == "config" and "ci" in x["detail"]]
        self.assertFalse(unknown, f"lint acusa a chave ci: {unknown}")
        self.assertEqual(lint.returncode, 0, output(lint))

    def test_invalid_ci_env_exits_2_in_config(self):
        """SPEC-0040:UT-04 (ci.env inválido -> config sai com 2, sem repetir o valor)"""
        bad = secret_like()
        self.add_to_config(f'ci:\n  env: ["{bad}"]\n')
        for args in (("config",), ("config", "--json")):
            with self.subTest(args=args):
                out = self.box.run(*args)
                self.assertEqual(out.returncode, 2, output(out))
                self.assertNotIn(bad, output(out))


class VendorCliTest(VendorCase):
    def test_vendor_github_creates_the_workflow_and_a_second_run_is_up_to_date(self):
        """SPEC-0040:IT-01"""
        out = self.vendor("--ci", "github")
        self.assert_vendor_ran(out)
        first = self.read(WORKFLOW)
        again = self.vendor("--ci", "github")
        self.assert_vendor_ran(again)
        self.assertIn("já atualizado", output(again))
        self.assertEqual(self.read(WORKFLOW), first)

    def test_customized_workflow_is_kept_without_force_and_overwritten_with_force(self):
        """SPEC-0040:IT-02"""
        original = self.workflow()
        path = self.atlas / WORKFLOW
        path.write_text(original + "# passo extra do time\n", encoding="utf-8")
        out = self.vendor("--ci", "github")
        self.assertNotIn("usage:", output(out))
        self.assertRegex(output(out), r"customizado — 1 linha\(s\) diferem; use --force para sobrescrever")
        self.assertEqual(path.read_text(encoding="utf-8"), original + "# passo extra do time\n")
        forced = self.vendor("--ci", "github", "--force")
        self.assert_vendor_ran(forced)
        self.assertEqual(path.read_text(encoding="utf-8"), original)


class LocalModeTest(VendorCase):
    mode = "local"

    def test_vendor_in_local_mode_exits_2(self):
        """SPEC-0040:IT-02 (mode: local)"""
        for kind in ("github", "generic"):
            with self.subTest(kind=kind):
                out = self.vendor("--ci", kind)
                self.assert_vendor_ran(out, 2)
                self.assertIn(LOCAL_MESSAGE, output(out))
                self.assert_nothing_written()


@unittest.skipUnless(HAS_GIT, "git não está no PATH")
class GenericScriptTest(VendorCase):
    def git(self, *args):
        env = dict(os.environ, HOME=str(self.box.home), GIT_CONFIG_NOSYSTEM="1",
                   GIT_AUTHOR_NAME="Teste", GIT_AUTHOR_EMAIL="teste@example.invalid",
                   GIT_COMMITTER_NAME="Teste", GIT_COMMITTER_EMAIL="teste@example.invalid")
        out = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
                             cwd=self.atlas, capture_output=True, text=True, env=env, check=False)
        self.assertEqual(out.returncode, 0, output(out))
        return out

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)

    def run_script(self, state):
        empty = self.box.root / f"ci-config-{state}"
        empty.mkdir()  # sem configuração local na máquina do CI
        env = dict(os.environ, HOME=str(self.box.home), ATLAS_CONFIG_HOME=str(empty), FAKE_STATE=state)
        return subprocess.run(["bash", str(GENERIC)], cwd=self.atlas, capture_output=True, text=True, env=env,
                              check=False, timeout=300)

    def test_generic_script_uses_the_copy_and_exits_10_with_change_0_without_and_1_with_failure(self):
        """SPEC-0040:IT-03"""
        self.add_to_config('collectors:\n  - id: fake\n    category: code\n'
                           '    command: ["python3", "{skill}/assets/collectors/fake_ci.py"]\n')
        path = self.shared_path()
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("collectors: []\n", "", 1), encoding="utf-8")  # uma chave collectors só
        out = self.vendor("--ci", "generic")
        self.assert_vendor_ran(out)
        script = self.read(GENERIC)
        self.assertIn(COPY_CALL, script)
        # o coletor falso só existe na cópia: {skill} precisa apontar para .org-atlas/skill/
        (self.atlas / COPY / "assets" / "collectors" / "fake_ci.py").write_text(FAKE_COLLECTOR, encoding="utf-8")
        self.git("init", "-q")
        self.commit("atlas")

        first = self.run_script("v1")
        self.assertEqual(first.returncode, 10, f"primeiro scan muda a árvore: {output(first)}")
        self.assertTrue((self.atlas / "snapshots" / "fake.json").is_file(), output(first))
        self.commit("scan v1")

        same = self.run_script("v1")
        self.assertEqual(same.returncode, 0, f"mesma saída do coletor = sem mudança: {output(same)}")
        self.assertEqual(self.git("status", "--porcelain").stdout, "")

        changed = self.run_script("v2")
        self.assertEqual(changed.returncode, 10, f"coletor mudou a saída: {output(changed)}")
        self.commit("scan v2")

        failed = self.run_script("fail")
        self.assertEqual(failed.returncode, 1, f"coletor falhando: {output(failed)}")


if __name__ == "__main__":
    unittest.main()
