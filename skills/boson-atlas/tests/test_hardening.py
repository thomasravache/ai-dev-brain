"""Endurecimento do init e do doctor, chave proibida e conferência de collector/category no scan (SPEC-0046: UT-02,
UT-03, IT-01 e IT-02).
Run: python3 -m unittest discover -s skills/boson-atlas/tests -p test_hardening.py

Contrato esperado de scripts/atlas.py (o Implementer segue estes testes):

    is_forbidden_key(name) -> bool
        Afinada (UT-02): monkey, primary_key, sort_keys, tokenizer e public_key não são chave proibida; auth é.
        validate_collector_output descarta de attrs só as proibidas (dropped cita o nome, nunca o valor).

    scan (UT-03, Emenda v2): a saída de um coletor com `category` diferente da categoria declarada no
        atlas-config.yml é violação: "FALHA <id>", exit 1, o motivo cita category e snapshots/<id>.json não é
        gravado. Já `collector` diferente do id declarado (com a category igual, como o generic declarado como
        db-facts) é aceito: exit 0 e o snapshot vai para snapshots/<id-declarado>.json.

IT-01 e IT-02 são guardas (passam antes da mudança): erro de sistema de arquivos sem traceback e com exit 1,
backups .bak e .bak.1, init --join recusando --org/--mode/--force, ERRO para atlas relativo e mensagem própria para
profile com espaço. Tudo roda em Sandbox (HOME e ATLAS_CONFIG_HOME temporários); nunca toca ~/.config/org-atlas.
"""
import json
import os
import unittest

from helpers import Sandbox, doctor_lines, fn, output, snapshot

SPEC = "SPEC-0046"
FAKES = "{skill}/tests/fixtures/fake-collectors"
BUILD_FIXTURES = "{skill}/tests/fixtures/build"
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
NO_PERMISSIONS = "chmod não impede a escrita/leitura (root ou sem POSIX)"
ALLOWED_KEYS = ("monkey", "primary_key", "sort_keys", "tokenizer", "public_key")


def f(name):
    return fn(name, SPEC)


def output_with(attrs):
    return {
        "contract": "org-atlas/collector@1",
        "collector": "github",
        "category": "code",
        "collected_at": "2026-10-30T12:00:00Z",
        "entities": [{"kind": "repository", "id": "acme/api", "name": "api", "attrs": dict(attrs),
                      "source": "github"}],
        "relations": [],
    }


def atlas_config_text(collectors_block):
    return ("version: 1\n"
            "organization: Acme\n"
            "mode: local\n"
            "language: auto\n"
            "stale_days: 14\n"
            "categories: [code, delivery]\n"
            f"{collectors_block}\n"
            "redaction: {extra_patterns: []}\n")


def collector_block(cid, category, printed_id):
    """Coletor `cid` declarado com `category`; o static.py imprime collector=printed_id e category=code."""
    command = ["python3", f"{FAKES}/static.py", printed_id]
    return ("collectors:\n"
            f"  - id: {cid}\n"
            f"    category: {category}\n"
            "    command: [" + ", ".join(json.dumps(a) for a in command) + "]\n"
            "    timeout: 30")


class CliCase(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)

    def assertExit(self, result, code):
        self.assertEqual(result.returncode, code, output(result))

    def assertNoTraceback(self, result):
        self.assertNotIn("Traceback", output(result), output(result))


# --------------------------------------------------------------------------- unitários


class ForbiddenKeyTest(unittest.TestCase):
    def test_only_auth_is_a_forbidden_key(self):
        """SPEC-0046:UT-02"""
        forbidden = f("is_forbidden_key")
        for name in ALLOWED_KEYS:
            with self.subTest(name=name):
                self.assertFalse(forbidden(name), f"{name} não é chave proibida")
        self.assertTrue(forbidden("auth"), "auth é chave proibida")
        for name in ("password", "api_token", "client_secret", "db_pwd"):
            with self.subTest(name=name):
                self.assertTrue(forbidden(name), f"{name} continua proibida")

    def test_validation_drops_only_auth_from_attrs(self):
        """SPEC-0046:UT-02"""
        value = "valor-" + "0046"
        attrs = {name: "x" for name in ALLOWED_KEYS}
        attrs["auth"] = value
        clean, violations, dropped = f("validate_collector_output")(output_with(attrs))
        self.assertEqual(violations, [])
        self.assertEqual(sorted(clean["entities"][0]["attrs"]), sorted(ALLOWED_KEYS))
        self.assertEqual(len(dropped), 1, dropped)
        self.assertIn("attrs.auth", dropped[0])
        self.assertNotIn(value, json.dumps(dropped, ensure_ascii=False))


class ScanIdentityTest(CliCase):
    def setUp(self):
        super().setUp()
        out = self.box.init(mode="local")
        self.assertExit(out, 0)
        self.atlas = self.box.atlas

    def scan_with(self, cid, category, printed_id):
        (self.atlas / "atlas-config.yml").write_text(atlas_config_text(collector_block(cid, category, printed_id)),
                                                     encoding="utf-8")
        result = self.box.run("scan")
        self.assertNoTraceback(result)
        return result

    def test_matching_collector_and_category_write_the_snapshot(self):
        """SPEC-0046:UT-03"""
        out = self.scan_with("fake-ok", "code", "fake-ok")
        self.assertExit(out, 0)
        self.assertTrue((self.atlas / "snapshots" / "fake-ok.json").is_file())

    def test_collector_different_from_the_declared_id_is_accepted(self):
        """SPEC-0046:UT-03"""
        out = self.scan_with("fake-a", "code", "fake-b")
        self.assertExit(out, 0)
        self.assertNotRegex(output(out), r"(?m)^FALHA fake-a")
        self.assertTrue((self.atlas / "snapshots" / "fake-a.json").is_file(), "snapshot não gravado pelo id declarado")
        self.assertFalse((self.atlas / "snapshots" / "fake-b.json").exists(), "snapshot gravado pelo collector da saída")

    def test_generic_declared_as_db_facts_writes_the_snapshot_by_the_declared_id(self):
        """SPEC-0046:UT-03"""
        command = ["python3", "{skill}/assets/collectors/generic.py", "--facts", f"{BUILD_FIXTURES}/db-facts.json",
                   "--category", "data", "--source", "db-facts"]
        block = ("collectors:\n"
                 "  - id: db-facts\n"
                 "    category: data\n"
                 "    command: [" + ", ".join(json.dumps(a) for a in command) + "]\n"
                 "    timeout: 60")
        (self.atlas / "atlas-config.yml").write_text(atlas_config_text(block), encoding="utf-8")
        out = self.box.run("scan")
        self.assertNoTraceback(out)
        self.assertExit(out, 0)
        self.assertNotRegex(output(out), r"(?m)^FALHA db-facts")
        self.assertTrue((self.atlas / "snapshots" / "db-facts.json").is_file(), "snapshot não gravado como db-facts")
        self.assertFalse((self.atlas / "snapshots" / "generic.json").exists(), "snapshot gravado como generic")

    def test_category_different_from_the_declared_one_is_a_violation(self):
        """SPEC-0046:UT-03"""
        out = self.scan_with("fake-c", "delivery", "fake-c")
        self.assertExit(out, 1)
        self.assertRegex(output(out), r"(?m)^FALHA fake-c — ")
        self.assertIn("category", output(out).split("FALHA fake-c", 1)[1])
        self.assertFalse((self.atlas / "snapshots" / "fake-c.json").exists(), "snapshot gravado com violação")


# --------------------------------------------------------------------------- integração (guardas)


class FileSystemErrorTest(CliCase):
    def assertCleanError(self, result):
        self.assertExit(result, 1)
        self.assertNoTraceback(result)
        text = output(result)
        self.assertTrue("erro:" in text or "ERRO" in text, text)

    @unittest.skipIf(IS_ROOT or os.name != "posix", NO_PERMISSIONS)
    def test_init_in_a_folder_without_write_permission_exits_1(self):
        """SPEC-0046:IT-01"""
        parent = self.box.root / "readonly"
        parent.mkdir()
        os.chmod(parent, 0o555)
        self.addCleanup(os.chmod, parent, 0o755)
        out = self.box.init(atlas=parent / "acme-atlas")
        self.assertCleanError(out)
        self.assertIn("erro:", output(out))
        self.assertFalse((self.box.config_home / "config.yml").exists())

    def test_init_with_an_atlas_config_that_is_not_utf8_exits_1(self):
        """SPEC-0046:IT-01"""
        self.box.atlas.mkdir(parents=True)
        (self.box.atlas / "atlas-config.yml").write_bytes(b"version: 1\norganization: Ac\xe9me\xff\n")
        out = self.box.init()
        self.assertCleanError(out)
        self.assertIn("erro:", output(out))
        self.assertIn("atlas-config.yml", output(out))

    @unittest.skipIf(IS_ROOT or os.name != "posix", NO_PERMISSIONS)
    def test_doctor_on_an_atlas_without_permission_exits_1(self):
        """SPEC-0046:IT-01"""
        self.box.new_atlas()
        os.chmod(self.box.atlas, 0)
        self.addCleanup(os.chmod, self.box.atlas, 0o755)
        out = self.box.run("doctor")
        self.assertCleanError(out)
        errors = [item for status, item, _ in doctor_lines(out.stdout) if status == "ERRO"]
        self.assertTrue(any(item.startswith("pasta do atlas") for item in errors), out.stdout)


class InitHardeningTest(CliCase):
    def test_two_forces_in_a_row_keep_bak_and_bak_1(self):
        """SPEC-0046:IT-02"""
        self.box.new_atlas()
        shared = self.box.atlas / "atlas-config.yml"
        first = shared.read_text(encoding="utf-8").rstrip("\n") + "\nnote: primeira edição\n"
        shared.write_text(first, encoding="utf-8")
        out = self.box.init("--force")
        self.assertExit(out, 0)
        second = shared.read_text(encoding="utf-8").rstrip("\n") + "\nnote: segunda edição\n"
        shared.write_text(second, encoding="utf-8")
        out = self.box.init("--force")
        self.assertExit(out, 0)
        self.assertEqual((self.box.atlas / "atlas-config.yml.bak").read_text(encoding="utf-8"), first)
        self.assertEqual((self.box.atlas / "atlas-config.yml.bak.1").read_text(encoding="utf-8"), second)
        self.assertNotIn("edição", shared.read_text(encoding="utf-8"))

    def test_join_refuses_org_mode_and_force(self):
        """SPEC-0046:IT-02"""
        self.box.new_atlas()
        before = snapshot(self.box.atlas)
        other = self.box.root / "config-home-2"
        for extra in (("--mode", "x"), ("--org", "Other"), ("--force",)):
            with self.subTest(extra=extra):
                out = self.box.run("init", "--join", "--atlas", self.box.atlas, *extra, config_home=other)
                self.assertExit(out, 2)
                self.assertNoTraceback(out)
                self.assertIn("init --join não aceita", output(out))
                self.assertIn(extra[0], output(out))
                self.assertFalse((other / "config.yml").exists())
                self.assertEqual(snapshot(self.box.atlas), before)

    def test_relative_atlas_in_the_local_config_is_an_error_in_doctor(self):
        """SPEC-0046:IT-02"""
        self.box.new_atlas()
        self.box.write_local('atlas: "work/acme-atlas"\n')
        out = self.box.run("doctor")
        self.assertExit(out, 1)
        self.assertNoTraceback(out)
        rows = [(item, detail) for status, item, detail in doctor_lines(out.stdout) if status == "ERRO"]
        self.assertTrue(any(item.startswith("pasta do atlas") and "caminho relativo" in detail
                            for item, detail in rows), out.stdout)

    def test_profile_with_a_space_has_its_own_message_without_the_value(self):
        """SPEC-0046:IT-02"""
        self.box.new_atlas()
        profile = "perfil secreto 0046"
        self.box.write_local(f'atlas: "{self.box.atlas}"\n'
                             "credentials:\n"
                             f'  github: {{env: [GITHUB_TOKEN], profile: "{profile}"}}\n')
        out = self.box.run("config")
        self.assertExit(out, 2)
        self.assertNoTraceback(out)
        self.assertIn("credentials aceita só um nome de profile, sem espaços: github", output(out))
        self.assertNotIn(profile, output(out))
        out = self.box.run("doctor")
        self.assertExit(out, 1)
        self.assertNoTraceback(out)
        rows = [detail for status, item, detail in doctor_lines(out.stdout)
                if status == "ERRO" and item.startswith("configuração local")]
        self.assertTrue(rows and "sem espaços: github" in rows[0], out.stdout)
        self.assertNotIn(profile, output(out))


if __name__ == "__main__":
    unittest.main()
