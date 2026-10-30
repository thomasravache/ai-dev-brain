"""Emenda v2 da SPEC-0017: caminhos dentro do vault, adopt com log/index do usuário, pasta não vazia,
comentários preservados e doctor com brain-config.yml malformado (SPEC-0017: UT-07, IT-08 a IT-11).

Contrato conferido (seção 6, itens marcados "(v2)"; mensagens de erro podem ir para stdout ou stderr):
    load_config / comandos   valor de layout, para ou contexts.<c>.folder absoluto ou com ".." ->
                             falha "brain-config.yml: <chave> fora do vault" (comandos: exit 1)
    doctor                   ERRO na chave fora do vault; brain-config.yml ilegível ->
                             "ERRO brain-config.yml — <erro de leitura>" e os demais itens continuam
    init --adopt             log.md/index.md do usuário (sem <!-- brain:begin) -> exit 2
                             "<arquivo> já existe — use --map log=<outro> (ou --map index=<outro>)"; nada é escrito
    init sem --adopt         pasta com conteúdo e sem brain-config.yml -> exit 2 "vault não está vazio — use --adopt"
    context add              só insere linhas em contexts, com a indentação das entradas existentes;
                             contexts inline com itens -> exit 2 "contexts está em forma inline — converta para bloco"
    init                     brain-config.yml gerado a partir de assets/brain-config.yml, mantendo os comentários
"""
import difflib
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from brain_support import (
    INIT_LOG_LINE,
    SKILL,
    Sandbox,
    doctor_lines,
    fn,
    output,
    snapshot,
)
from test_cli import CliTestCase

ASSET_CONFIG = SKILL / "assets" / "brain-config.yml"
OUTSIDE = "fora do vault"

COMMENTED_CONFIG = """# brain-config do usuário — comentário de cabeçalho
version: 1
language: auto      # idioma do conteúdo
layout:
    inbox: inbox
    raw: raw
    mocs: mocs
    templates: templates
    index: index.md
    log: log.md
para:
    projects: projects
    areas: areas
    resources: resources
    archive: archive
contexts:           # meus contextos
    # comentário dentro de contexts
    college:
        folder: projects/college
        title: College
processors: {}      # nenhum ainda
"""


def comment_of(line: str):
    """Texto do comentário de uma linha YAML (linha inteira ou ' # ...' no fim), ou None."""
    stripped = line.strip()
    if stripped.startswith("#"):
        return stripped
    m = re.search(r"\s(#.*)$", line)
    return m.group(1).strip() if m else None


class OutsideVaultLoadConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.vault = self.tmp / "Vault"
        self.files = self.tmp / "Vault-files"
        self.vault.mkdir()
        self.files.mkdir()
        self.config_home = self.tmp / "config-home"
        self.config_home.mkdir()
        (self.config_home / "config.yml").write_text(
            f'vault: "{self.vault}"\nfiles: "{self.files}"\nprovider: local\n', encoding="utf-8")

    def write_shared(self, text):
        (self.vault / "brain-config.yml").write_text("version: 1\nlanguage: auto\n" + text, encoding="utf-8")

    def test_values_outside_the_vault_fail_naming_the_key(self):
        """SPEC-0017:UT-07"""
        load_config = fn("load_config")
        cases = (
            ("layout.log", "layout:\n  log: ../x.md\n"),
            ("layout.inbox", "layout:\n  inbox: /abs/inbox\n"),
            ("contexts.c.folder", "contexts:\n  c:\n    folder: ../../fora\n    title: C\n"),
            ("para.projects", "para:\n  projects: ../projects\n"),
        )
        for key, text in cases:
            with self.subTest(key=key):
                self.write_shared(text)
                with self.assertRaises(Exception) as caught:
                    load_config(self.config_home)
                self.assertIn(f"brain-config.yml: {key} {OUTSIDE}", str(caught.exception))
                self.assertEqual(getattr(caught.exception, "code", 1), 1)

    def test_relative_values_inside_the_vault_pass(self):
        """SPEC-0017:UT-07"""
        self.write_shared("layout:\n  inbox: Inbox\n  log: notes/log.md\n"
                          "para:\n  projects: Projects\n"
                          "contexts:\n  c:\n    folder: projects/c\n    title: C\n")
        values = fn("load_config")(self.config_home)["values"]
        self.assertEqual(values["layout"]["inbox"], "Inbox")
        self.assertEqual(values["layout"]["log"], "notes/log.md")
        self.assertEqual(values["para"]["projects"], "Projects")
        self.assertEqual(values["contexts"]["c"]["folder"], "projects/c")


class AdoptWithUserLogTest(CliTestCase):
    def user_vault(self, name):
        vault = self.box.vault
        (vault / "Notas").mkdir(parents=True)
        (vault / "Notas" / "b.md").write_text("# B\nnota\n", encoding="utf-8")
        (vault / name).write_text(f"# Meu {name}\n\n- algo que eu escrevi\n", encoding="utf-8")
        return snapshot(vault)

    def test_adopt_refuses_a_user_log_or_index_and_writes_nothing(self):
        """SPEC-0017:IT-08"""
        for name, key in (("log.md", "log"), ("index.md", "index")):
            with self.subTest(file=name):
                self.box = Sandbox()
                self.addCleanup(self.box.cleanup)
                before = self.user_vault(name)
                out = self.box.init("--adopt", provider="local")
                self.assertExit(out, 2)
                self.assertIn(f"{name} já existe — use --map {key}=", output(out))
                self.assertEqual(snapshot(self.box.vault), before, "o vault mudou")
                self.assertFalse((self.box.config_home / "config.yml").exists(), "gravou a configuração local")

    def test_adopt_with_map_log_creates_the_skill_log_elsewhere(self):
        """SPEC-0017:IT-08"""
        vault = self.box.vault
        before = self.user_vault("log.md")
        out = self.box.init("--adopt", "--map", "log=brain-log.md", provider="local")
        self.assertExit(out, 0)
        self.assertEqual(snapshot(vault)["log.md"], before["log.md"], "log.md do usuário mudou")
        self.assertEqual(snapshot(vault)["Notas/b.md"], before["Notas/b.md"])
        self.assertTrue((vault / "brain-log.md").is_file())
        self.assertRegex((vault / "brain-log.md").read_text(encoding="utf-8"), INIT_LOG_LINE)
        self.assertEqual(self.box.config_json()["values"]["layout"]["log"], "brain-log.md")


class NotEmptyWithoutAdoptTest(CliTestCase):
    def test_init_in_a_folder_with_notes_suggests_adopt_and_creates_nothing(self):
        """SPEC-0017:IT-09"""
        vault = self.box.vault
        (vault / "Notas").mkdir(parents=True)
        (vault / "Notas" / "b.md").write_text("# B\nnota\n", encoding="utf-8")
        (vault / "solta.md").write_text("# Solta\n", encoding="utf-8")
        before = snapshot(vault)
        out = self.box.init("--context", "college=projects/college:College")
        self.assertExit(out, 2)
        self.assertIn("vault não está vazio — use --adopt", output(out))
        self.assertEqual(snapshot(vault), before, "init criou ou alterou algo no vault")
        self.assertFalse(self.box.files.exists(), "init criou a pasta files")
        self.assertFalse((self.box.config_home / "config.yml").exists(), "init gravou a configuração local")


class CommentsPreservedTest(CliTestCase):
    def test_context_add_only_inserts_lines_with_the_existing_indentation(self):
        """SPEC-0017:IT-10"""
        self.box.new_vault()
        shared = self.box.vault / "brain-config.yml"
        shared.write_text(COMMENTED_CONFIG, encoding="utf-8")

        out = self.box.run("context", "add", "work", "--folder", "areas/work")
        self.assertExit(out, 0)
        after = shared.read_text(encoding="utf-8")
        old, new = COMMENTED_CONFIG.splitlines(), after.splitlines()
        ops = difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes()
        self.assertEqual([op for op in ops if op[0] not in ("equal", "insert")], [], after)
        inserts = [op for op in ops if op[0] == "insert"]
        self.assertEqual(len(inserts), 1, after)
        _, at, _, start, end = inserts[0]
        self.assertGreater(at, old.index("contexts:           # meus contextos"), after)
        self.assertLessEqual(at, old.index("processors: {}      # nenhum ainda"), after)
        self.assertRegex(new[start], r"^ {4}work\s*:", after)
        for line in new[start + 1:end]:
            self.assertRegex(line, r"^ {5,}\S", after)
        contexts = self.box.config_json()["values"]["contexts"]
        self.assertEqual(contexts["work"]["folder"], "areas/work")
        self.assertEqual(contexts["college"], {"folder": "projects/college", "title": "College"})

    def test_inline_contexts_with_items_exit_2_and_leave_the_file(self):
        """SPEC-0017:IT-10"""
        self.box.new_vault()
        vault = self.box.vault
        shared = vault / "brain-config.yml"
        text = COMMENTED_CONFIG.split("contexts:")[0] + (
            "contexts: {college: {folder: projects/college}}\nprocessors: {}\n")
        shared.write_text(text, encoding="utf-8")
        before = snapshot(vault)

        out = self.box.run("context", "add", "work", "--folder", "areas/work")
        self.assertExit(out, 2)
        self.assertIn("contexts está em forma inline — converta para bloco", output(out))
        self.assertEqual(shared.read_text(encoding="utf-8"), text)
        self.assertEqual(snapshot(vault), before, "o vault mudou")

    def test_init_keeps_the_comments_of_the_skill_model(self):
        """SPEC-0017:IT-10"""
        model = ASSET_CONFIG.read_text(encoding="utf-8").splitlines()
        comments = [c for c in (comment_of(line) for line in model) if c]
        self.assertTrue(comments, "assets/brain-config.yml sem comentários")
        changed = re.compile(r"^(  inbox|contexts)\s*:")
        unchanged = [line for line in model if not changed.match(line)]
        for extra in ((), ("--map", "inbox=Inbox")):
            with self.subTest(extra=extra):
                self.box = Sandbox()
                self.addCleanup(self.box.cleanup)
                self.box.vault.mkdir(parents=True)
                out = self.box.init("--context", "college=projects/college:College", *extra)
                self.assertExit(out, 0)
                generated = (self.box.vault / "brain-config.yml").read_text(encoding="utf-8")
                for comment in comments:
                    self.assertIn(comment, generated)
                lines = generated.splitlines()
                matcher = difflib.SequenceMatcher(a=unchanged, b=lines, autojunk=False)
                kept = sum(block.size for block in matcher.get_matching_blocks())
                self.assertEqual(kept, len(unchanged), f"linhas do modelo alteradas:\n{generated}")
                values = self.box.config_json()["values"]
                self.assertEqual(values["contexts"]["college"]["folder"], "projects/college")
                self.assertEqual(values["layout"]["inbox"], "Inbox" if extra else "inbox")


class ValidationAndMalformedTest(CliTestCase):
    def escape_log(self):
        self.box.new_vault()
        shared = self.box.vault / "brain-config.yml"
        text = shared.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^  log: log\.md")
        text = re.sub(r"(?m)^  log: log\.md", "  log: ../escaped.md", text)
        shared.write_text(text, encoding="utf-8")
        return text

    def test_value_outside_the_vault_blocks_context_add_and_is_an_error_in_doctor(self):
        """SPEC-0017:IT-11"""
        text = self.escape_log()
        vault = self.box.vault
        escaped = vault.parent / "escaped.md"
        before = snapshot(vault)

        out = self.box.run("context", "add", "work", "--folder", "areas/work")
        self.assertExit(out, 1)
        self.assertIn(f"brain-config.yml: layout.log {OUTSIDE}", output(out))
        self.assertFalse(escaped.exists(), "escreveu fora do vault")
        self.assertEqual(snapshot(vault), before, "o vault mudou")
        self.assertEqual((vault / "brain-config.yml").read_text(encoding="utf-8"), text)

        out = self.box.run("doctor")
        self.assertExit(out, 1)
        errors = [(item, detail) for status, item, detail in doctor_lines(out.stdout) if status == "ERRO"]
        self.assertTrue(any("layout.log" in item + " " + detail for item, detail in errors), out.stdout)
        self.assertFalse(escaped.exists(), "doctor escreveu fora do vault")

    def test_unreadable_brain_config_is_an_error_and_doctor_goes_on(self):
        """SPEC-0017:IT-11"""
        self.box.new_vault()
        shared = self.box.vault / "brain-config.yml"
        text = re.sub(r"(?m)^language: auto", 'language: "auto', shared.read_text(encoding="utf-8"))
        self.assertIn('language: "auto', text)
        shared.write_text(text, encoding="utf-8")

        out = self.box.run("doctor")
        self.assertExit(out, 1)
        rows = doctor_lines(out.stdout)
        self.assertTrue(any(status == "ERRO" and item == "brain-config.yml" for status, item, _ in rows),
                        out.stdout)
        ok = [item for status, item, _ in rows if status == "OK"]
        for item in ("configuração local", "vault"):
            self.assertTrue(any(i.startswith(item) for i in ok), f"OK {item} ausente:\n{out.stdout}")


if __name__ == "__main__":
    unittest.main()
