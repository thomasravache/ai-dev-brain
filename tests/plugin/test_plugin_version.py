"""Versão do plugin fermion sobe quando as skills mudam, e author no plugin.json (SPEC-0056).

Run: python3 -m unittest discover -s tests/plugin -p test_plugin_version.py

A checagem mora em `tests/plugin/check_plugin_version.py` (questão respondida da spec: na CI do repositório). Este
arquivo exige dela:

- `version_findings(changed_paths, base_version, head_version) -> list[str]`: achados (lista vazia = ok). Se algum
  caminho está em `skills/**` e a versão da HEAD não é maior que a da base (comparação de `AAAA.MM.N` como tupla de
  inteiros), há achado. Sem mudança em `skills/**`, nada é exigido.
- CLI `python3 tests/plugin/check_plugin_version.py --base <ref>`, rodada na raiz do repositório: compara
  `git diff --name-only <base>...HEAD`, a versão de `git show <base>:.claude-plugin/plugin.json` e a do
  `.claude-plugin/plugin.json` da árvore; imprime os achados e sai com 1 quando há achado, 0 quando não há.
  Na CI: `python3 tests/plugin/check_plugin_version.py --base origin/main`.

O IT-01 cria repositórios git temporários (configuração do git isolada por variáveis de ambiente) e nunca toca o
repositório real.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN_JSON = REPO / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO / ".claude-plugin" / "marketplace.json"
CHECK_SCRIPT = Path(__file__).resolve().parent / "check_plugin_version.py"

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def load_check(test):
    """Importa check_plugin_version.py; falha (não erro) com mensagem clara quando ainda não existe."""
    if not CHECK_SCRIPT.is_file():
        test.fail(f"{CHECK_SCRIPT.relative_to(REPO)} não existe (checagem da SPEC-0056)")
    spec = importlib.util.spec_from_file_location("check_plugin_version", CHECK_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "version_findings", None)):
        test.fail("check_plugin_version.py não define version_findings(changed_paths, base, head)")
    return module


def json_strings_and_keys(value):
    """Todas as chaves e strings de um JSON, em profundidade."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from json_strings_and_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from json_strings_and_keys(item)
    elif isinstance(value, str):
        yield value


class VersionFindingsTest(unittest.TestCase):
    def setUp(self):
        self.check = load_check(self)

    def findings(self, paths, base, head):
        result = self.check.version_findings(paths, base, head)
        self.assertIsInstance(result, list)
        return result

    def test_skills_change_requires_bigger_version(self):
        """SPEC-0056:UT-01"""
        skills_diff = ["skills/gluon-spec/SKILL.md", "README.md"]

        # muda skills/** sem subir a versão: acusa
        same = self.findings(skills_diff, "2026.11.1", "2026.11.1")
        self.assertTrue(same, "skills/** mudou e a versão ficou igual, mas não houve achado")
        self.assertTrue(all(isinstance(f, str) and f for f in same))
        self.assertTrue(any("2026.11.1" in f for f in same), same)

        # versão menor também acusa
        self.assertTrue(self.findings(skills_diff, "2026.11.2", "2026.11.1"))

        # versão maior não acusa, comparando como tupla (2026.10 > 2026.9, ao contrário da comparação de texto)
        self.assertEqual(self.findings(skills_diff, "2026.11.1", "2026.11.2"), [])
        self.assertEqual(self.findings(skills_diff, "2026.9.3", "2026.10.1"), [])
        self.assertEqual(self.findings(skills_diff, "2026.11.9", "2026.11.10"), [])
        self.assertEqual(self.findings(skills_diff, "2026.12.4", "2027.1.1"), [])
        self.assertTrue(self.findings(skills_diff, "2026.10.1", "2026.9.9"))

        # versão da HEAD fora do formato AAAA.MM.N acusa
        self.assertTrue(self.findings(skills_diff, "2026.11.1", "2026.11"))

        # sem mudança em skills/**, nada é exigido (nem caminhos que só parecem com skills/)
        for paths in ([], ["README.md", ".claude-plugin/plugin.json"],
                      ["tests/skills/x.py", "skillsfoo/a.md", "docs/skills/b.md"]):
            with self.subTest(paths=paths):
                self.assertEqual(self.findings(paths, "2026.11.1", "2026.11.1"), [])


class PluginAuthorTest(unittest.TestCase):
    def test_author_matches_marketplace_owner_without_email(self):
        """SPEC-0056:UT-02"""
        plugin = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        marketplace = json.loads(MARKETPLACE_JSON.read_text(encoding="utf-8"))

        author = plugin.get("author")
        self.assertIsInstance(author, dict, "plugin.json não tem author como objeto")
        self.assertEqual(author.get("name"), marketplace["owner"]["name"])
        self.assertEqual(set(author), {"name"}, f"author deve ter só name: {author}")

        for path, data in ((PLUGIN_JSON, plugin), (MARKETPLACE_JSON, marketplace)):
            for text in json_strings_and_keys(data):
                with self.subTest(file=path.name, text=text):
                    self.assertNotEqual(text, "email")
                    self.assertIsNone(EMAIL_RE.search(text))


GIT_ENV = {
    "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


class CheckAgainstBaseTest(unittest.TestCase):
    def setUp(self):
        if not CHECK_SCRIPT.is_file():
            self.fail(f"{CHECK_SCRIPT.relative_to(REPO)} não existe (checagem da SPEC-0056)")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {**os.environ, **GIT_ENV}
        self.git("init", "-q")
        self.write_plugin("2026.11.1")
        self.write("skills/gluon-spec/SKILL.md", "v1\n")
        self.write("README.md", "v1\n")
        self.base = self.commit("base")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_plugin(self, version):
        self.write(".claude-plugin/plugin.json",
                   json.dumps({"name": "fermion", "version": version}, indent=2) + "\n")

    def commit(self, message):
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def run_check(self):
        return subprocess.run([sys.executable, str(CHECK_SCRIPT), "--base", self.base], cwd=self.root,
                              env=self.env, check=False, capture_output=True, text=True)

    def test_check_against_base_commit(self):
        """SPEC-0056:IT-01"""
        cases = (
            ("skills sem subir a versão", "2026.11.1", True, 1),
            ("skills com a versão maior", "2026.11.2", True, 0),
            ("sem mudança em skills", "2026.11.1", False, 0),
        )
        for label, version, touch_skills, expected in cases:
            with self.subTest(case=label):
                self.git("reset", "-q", "--hard", self.base)
                self.write("README.md", f"{label}\n")
                if touch_skills:
                    self.write("skills/gluon-spec/SKILL.md", f"{label}\n")
                self.write_plugin(version)
                self.commit(label)
                result = self.run_check()
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                if expected:
                    self.assertIn("2026.11.1", result.stdout + result.stderr)

    def test_invalid_head_plugin_json(self):
        """SPEC-0056:IT-01 (plugin.json da HEAD com JSON inválido: achado, sem Traceback)"""
        self.write("skills/gluon-spec/SKILL.md", "v2\n")
        self.write(".claude-plugin/plugin.json", '{"name": "fermion", "version": \n')
        self.commit("plugin.json inválido")
        result = self.run_check()
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertNotIn("Traceback", output)
        self.assertIn("plugin.json", output)

    def test_base_version_out_of_format_warns(self):
        """SPEC-0056:IT-01 (versão da base fora de AAAA.MM.N: aviso, não bloqueia)"""
        self.write_plugin("2026.11")
        self.base = self.commit("base com versão fora do formato")
        self.write("skills/gluon-spec/SKILL.md", "v2\n")
        self.write_plugin("2026.11.2")
        self.commit("skills com versão válida")
        result = self.run_check()
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        warnings = [line for line in output.splitlines() if "aviso" in line.lower()]
        self.assertTrue(warnings, f"sem linha de aviso na saída:\n{output}")
        self.assertTrue(any("2026.11" in line for line in warnings), output)


if __name__ == "__main__":
    unittest.main()
