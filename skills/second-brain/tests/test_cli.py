"""Integração pela CLI: init, init --adopt/--force/--join, config, context add e doctor (SPEC-0017: IT-01 a IT-07).

Cada teste roda `python3 scripts/brain.py ...` como subprocesso num diretório temporário resolvido (macOS:
/var -> /private/var), com HOME e BRAIN_CONFIG_HOME isolados (brain_support.Sandbox). O vault fica em
<tmp>/Drive/Vault e a pasta de arquivos em <tmp>/Drive/Vault-files (fora do vault).

Saídas que os testes conferem (contrato da seção 6; mensagens de erro podem ir para stdout ou stderr):
    init (vault novo)          exit 0, "Vault criado em <vault>"
    init repetido igual        exit 0, "Vault já configurado"
    brain-config.yml diferente exit 2, "brain-config.yml já existe — use --join ou --force"
    --adopt sem vault          exit 2, "vault não encontrado: <vault>"
    files dentro do vault      exit 2, "files precisa ficar fora do vault"
    provider inválido          exit 2, mensagem com os quatro providers
    init --join sem config     exit 2, "vault sem brain-config.yml — rode init"
    config / doctor sem local  exit 3, "second-brain não configurado nesta máquina — rode init (ou init --join)"
    config --json              {"values": {...}, "origins": {...}} (ver test_config.load_config)
    log.md                     uma linha "- AAAA-MM-DD HH:MM <comando> <resumo>" no fim, por escrita no vault
                               (init: "- AAAA-MM-DD HH:MM init ..."; context add: "- ... context add ...")
    brain-config.yml gerado    assets/brain-config.yml com os comentários; só --map e --context mudam valores
    doctor                     linhas "OK|AVISO|ERRO <item> — <detalhe>", com os itens começando por
                               "configuração local", "vault", "files", "brain-config.yml", ... e
                               "processor <kind>" para cada processador (o executável é a primeira palavra de
                               `command`; ausente no PATH = AVISO). Exit 0 sem ERRO, 1 com ERRO.
    init --join                grava em config.yml o caminho do vault como recebido (ex.: um link simbólico),
                               sem escrever nada no vault.
"""
import os
import re
import shutil
import unittest

from brain_support import (
    INIT_LOG_LINE,
    LOG_LINE,
    NOT_CONFIGURED,
    SCRIPT,
    SKILL,
    Sandbox,
    doctor_lines,
    fn,
    output,
    snapshot,
)

STRUCTURE_DIRS = ("inbox", "raw", "projects", "areas", "resources", "archive", "mocs", "templates")
STRUCTURE_FILES = ("index.md", "log.md", "brain-config.yml")
OLD_MTIME = 1_600_000_000
ASSET_CONFIG = SKILL / "assets" / "brain-config.yml"


class CliTestCase(unittest.TestCase):
    def setUp(self):
        if not SCRIPT.exists():
            self.fail(f"{SCRIPT} não existe (SPEC-0017)")
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)

    def assertExit(self, result, code):
        self.assertEqual(result.returncode, code, output(result))
        self.assertNotIn("Traceback", output(result))


class InitArgsCliTest(CliTestCase):
    def test_invalid_init_arguments_exit_2_with_the_message(self):
        """SPEC-0017:UT-02"""
        self.box.vault.mkdir(parents=True)
        out = self.box.init(files=self.box.vault / "files")
        self.assertExit(out, 2)
        self.assertIn("files precisa ficar fora do vault", output(out))
        out = self.box.init(provider="dropbox")
        self.assertExit(out, 2)
        for provider in ("google-drive", "onedrive", "icloud", "local"):
            self.assertIn(provider, output(out))
        self.assertFalse((self.box.vault / "brain-config.yml").exists())


class NewVaultTest(CliTestCase):
    def test_init_creates_the_full_structure_and_both_configs(self):
        """SPEC-0017:IT-01"""
        out = self.box.new_vault()
        vault = self.box.vault
        self.assertExit(out, 0)
        self.assertIn(f"Vault criado em {vault}", out.stdout)
        for name in STRUCTURE_DIRS:
            self.assertTrue((vault / name).is_dir(), name)
        for name in STRUCTURE_FILES:
            self.assertTrue((vault / name).is_file(), name)
        self.assertTrue(list((vault / "templates").glob("*.md")), "templates/ sem modelos")
        for name in ("index.md", "log.md"):
            text = (vault / name).read_text(encoding="utf-8")
            self.assertRegex(text, r"<!-- brain:begin [^>]+-->", name)
            self.assertRegex(text, r"<!-- brain:end [^>]+-->", name)
        self.assertRegex((vault / "log.md").read_text(encoding="utf-8"), INIT_LOG_LINE)

        shared = (vault / "brain-config.yml").read_text(encoding="utf-8")
        for line in (ASSET_CONFIG.read_text(encoding="utf-8").splitlines()):
            if line.startswith("#"):
                self.assertIn(line, shared, "brain-config.yml perdeu os comentários do modelo")
        self.assertIn("college", shared)
        self.assertIn("projects/college", shared)
        self.assertNotIn(str(self.box.root), shared)

        local = self.box.config_home / "config.yml"
        self.assertTrue(local.is_file())
        text = local.read_text(encoding="utf-8")
        self.assertIn(str(vault), text)
        self.assertIn(str(self.box.files), text)
        self.assertIn("google-drive", text)
        self.assertTrue(self.box.files.is_dir())
        self.assertFalse((self.box.home / ".config" / "second-brain").exists(), "ignorou BRAIN_CONFIG_HOME")

        config = self.box.config_json()
        self.assertEqual(config["values"]["contexts"]["college"], {"folder": "projects/college", "title": "College"})
        self.assertEqual(config["values"]["vault"], str(vault))
        self.assertEqual(config["values"]["provider"], "google-drive")


class AdoptVaultTest(CliTestCase):
    def test_adopt_keeps_existing_files_and_creates_only_what_is_missing(self):
        """SPEC-0017:IT-02"""
        vault = self.box.vault
        (vault / "Inbox").mkdir(parents=True)
        (vault / "Notas").mkdir()
        (vault / ".obsidian").mkdir()
        (vault / "Inbox" / "a.md").write_text("# A\nideia\n", encoding="utf-8")
        (vault / "Notas" / "b.md").write_text("# B\nnota\n", encoding="utf-8")
        (vault / ".obsidian" / "app.json").write_text('{"x": 1}\n', encoding="utf-8")
        for sub in ("Inbox", "Notas", ".obsidian"):
            for path in [vault / sub, *(vault / sub).rglob("*")]:
                os.utime(path, (OLD_MTIME, OLD_MTIME))
        before = {sub: snapshot(vault / sub) for sub in ("Inbox", "Notas", ".obsidian")}
        before_mtimes = {sub: (vault / sub).stat().st_mtime_ns for sub in before}

        out = self.box.init("--adopt", "--map", "inbox=Inbox", provider="local")
        self.assertExit(out, 0)

        for sub, state in before.items():
            self.assertEqual(snapshot(vault / sub), state, f"{sub}/ mudou")
            self.assertEqual((vault / sub).stat().st_mtime_ns, before_mtimes[sub], f"{sub}/ mudou")
        self.assertEqual(sorted(os.listdir(vault)),
                         sorted([".obsidian", "Inbox", "Notas", "raw", "templates", "index.md", "log.md",
                                 "brain-config.yml"]))
        self.assertTrue((vault / "raw").is_dir())
        self.assertTrue((vault / "templates").is_dir())
        self.assertRegex((vault / "log.md").read_text(encoding="utf-8"), INIT_LOG_LINE)
        config = self.box.config_json()
        self.assertEqual(config["values"]["layout"]["inbox"], "Inbox")
        self.assertEqual(config["origins"]["layout.inbox"], "vault")

    def test_adopt_without_vault_exits_2(self):
        """SPEC-0017:IT-02"""
        out = self.box.init("--adopt", provider="local")
        self.assertExit(out, 2)
        self.assertIn(f"vault não encontrado: {self.box.vault}", output(out))
        self.assertFalse(self.box.vault.exists())


class ReinitTest(CliTestCase):
    def test_same_init_again_only_writes_local_config(self):
        """SPEC-0017:IT-03"""
        self.box.new_vault()
        before = snapshot(self.box.vault)
        other_home = self.box.root / "config-home-2"
        out = self.box.init("--context", "college=projects/college:College", config_home=other_home)
        self.assertExit(out, 0)
        self.assertIn("Vault já configurado", out.stdout)
        self.assertTrue((other_home / "config.yml").is_file())
        self.assertEqual(snapshot(self.box.vault), before)

    def test_different_brain_config_needs_force_and_force_keeps_a_backup(self):
        """SPEC-0017:IT-03"""
        self.box.new_vault()
        shared = self.box.vault / "brain-config.yml"
        edited = shared.read_text(encoding="utf-8").rstrip("\n") + "\nnote: editado à mão\n"
        shared.write_text(edited, encoding="utf-8")

        out = self.box.init("--context", "college=projects/college:College")
        self.assertExit(out, 2)
        self.assertIn("brain-config.yml já existe — use --join ou --force", output(out))
        self.assertEqual(shared.read_text(encoding="utf-8"), edited)
        self.assertFalse((self.box.vault / "brain-config.yml.bak").exists())

        out = self.box.init("--context", "college=projects/college:College", "--force")
        self.assertExit(out, 0)
        self.assertEqual((self.box.vault / "brain-config.yml.bak").read_text(encoding="utf-8"), edited)
        self.assertNotIn("editado à mão", shared.read_text(encoding="utf-8"))
        self.assertIn("projects/college", shared.read_text(encoding="utf-8"))


class JoinTest(CliTestCase):
    def test_join_writes_only_the_local_config_for_another_path(self):
        """SPEC-0017:IT-04"""
        self.box.new_vault()
        link = self.box.root / "OtherMachine" / "Vault"
        link.parent.mkdir()
        link.symlink_to(self.box.vault, target_is_directory=True)
        before = snapshot(self.box.vault)
        second = self.box.root / "config-home-2"

        out = self.box.init("--join", vault=link, config_home=second)
        self.assertExit(out, 0)
        self.assertEqual(snapshot(self.box.vault), before, "join escreveu no vault")
        self.assertIn(str(link), (second / "config.yml").read_text(encoding="utf-8"))

        first, other = self.box.config_json(), self.box.config_json(config_home=second)
        self.assertIn("college", first["values"]["contexts"])
        self.assertEqual(first["values"]["contexts"], other["values"]["contexts"])
        self.assertEqual(other["values"]["vault"], str(link))

    def test_join_without_brain_config_exits_2(self):
        """SPEC-0017:IT-04"""
        empty = self.box.root / "Empty"
        empty.mkdir()
        third = self.box.root / "config-home-3"
        out = self.box.init("--join", vault=empty, config_home=third)
        self.assertExit(out, 2)
        self.assertIn("vault sem brain-config.yml — rode init", output(out))
        self.assertFalse((third / "config.yml").exists())
        self.assertEqual(os.listdir(empty), [])


class NotConfiguredTest(CliTestCase):
    def test_config_and_doctor_without_local_config_exit_3(self):
        """SPEC-0017:IT-05"""
        self.box.config_home.mkdir()
        for args in (("config",), ("config", "--json"), ("doctor",)):
            with self.subTest(args=args):
                out = self.box.run(*args)
                self.assertExit(out, 3)
                self.assertIn(NOT_CONFIGURED, output(out))


class DoctorTest(CliTestCase):
    def add_missing_processor(self):
        parse, dump = fn("parse_yaml"), fn("dump_yaml")
        shared = self.box.vault / "brain-config.yml"
        data = parse(shared.read_text(encoding="utf-8"))
        data["processors"] = {"pdf": {"command": "sb-missing-pdftotext-0017 {input} {output}"}}
        shared.write_text(dump(data), encoding="utf-8")

    def test_healthy_vault_is_ok_and_missing_processor_is_a_warning(self):
        """SPEC-0017:IT-06"""
        self.box.new_vault()
        self.add_missing_processor()
        out = self.box.run("doctor")
        self.assertExit(out, 0)
        rows = doctor_lines(out.stdout)
        self.assertTrue(rows, out.stdout)
        ok = [item for status, item, _ in rows if status == "OK"]
        for item in ("configuração local", "vault", "files", "brain-config.yml"):
            self.assertTrue(any(i.startswith(item) for i in ok), f"OK {item} ausente:\n{out.stdout}")
        self.assertEqual([row for row in rows if row[0] == "ERRO"], [], out.stdout)
        warnings = [(item, detail) for status, item, detail in rows if status == "AVISO"]
        self.assertTrue(any("pdf" in item and "sb-missing-pdftotext-0017" in item + detail
                            for item, detail in warnings), out.stdout)

    def test_missing_vault_is_an_error_without_traceback(self):
        """SPEC-0017:IT-06"""
        self.box.new_vault()
        shutil.rmtree(self.box.vault)
        out = self.box.run("doctor")
        self.assertExit(out, 1)
        errors = [(item, detail) for status, item, detail in doctor_lines(out.stdout) if status == "ERRO"]
        self.assertTrue(any(item.startswith("vault") for item, _ in errors), out.stdout)
        self.assertIn(str(self.box.vault), out.stdout)


class ContextAddTest(CliTestCase):
    def test_context_add_registers_creates_folder_and_moc_and_logs(self):
        """SPEC-0017:IT-07"""
        self.box.new_vault()
        vault = self.box.vault
        log_before = (vault / "log.md").read_text(encoding="utf-8")

        out = self.box.run("context", "add", "work", "--folder", "areas/work", "--title", "Work")
        self.assertExit(out, 0)
        contexts = self.box.config_json()["values"]["contexts"]
        self.assertEqual(contexts["work"], {"folder": "areas/work", "title": "Work"})
        self.assertIn("college", contexts)
        self.assertTrue((vault / "areas" / "work").is_dir())
        self.assertTrue((vault / "mocs" / "work.md").is_file())
        log_after = (vault / "log.md").read_text(encoding="utf-8")
        self.assertGreater(len(LOG_LINE.findall(log_after)), len(LOG_LINE.findall(log_before)))
        self.assertTrue(log_after.startswith(log_before), "log.md só recebe linhas no fim")
        new_lines = log_after[len(log_before):].splitlines()
        self.assertTrue(any(re.match(r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} context add .*\bwork\b", line)
                            for line in new_lines), log_after)

        shared_before = (vault / "brain-config.yml").read_text(encoding="utf-8")
        out = self.box.run("context", "add", "work", "--folder", "areas/work", "--title", "Work")
        self.assertExit(out, 2)
        self.assertEqual((vault / "brain-config.yml").read_text(encoding="utf-8"), shared_before)


if __name__ == "__main__":
    unittest.main()
