"""Revisão da SPEC-0044 (CHANGES_REQUESTED): `capture --print` com o vault inacessível, `--inbox` e a precedência do
modo só conector (SPEC-0044: IT-01, UT-02 e UT-03; ADR-0013).

Decisões do Architect registradas aqui:

1. (major, IT-01) `capture --print` não falha quando a configuração local existe mas o vault (ou o brain-config.yml
   dele, ou a inbox) está ausente ou ilegível — o caso do TCC do macOS, em que o agente não lê a pasta sincronizada.
   Usa então o layout.inbox se ele pôde ser lido, senão "inbox", ou o `--inbox` (permitido neste caso); nunca
   escreve nada e sai com 0. Casos: pasta do vault removida; vault com chmod 000 (pulado como root; a permissão
   volta no cleanup); brain-config.yml removido ou ilegível; inbox ilegível (chmod 000).
2. (UT-02) `--inbox ""` e `--inbox .` saem com 2 (nunca um caminho na raiz do vault); `--inbox ..`,
   `--inbox a/../../x` e `--inbox /etc` saem com 2.
3. (UT-02) com configuração legível, `--inbox x` sai com 2; `--inbox x` sem `--print` sai com 2.
4. (UT-03) a seção "Antes de qualquer fluxo" do SKILL.md diz a precedência: exit 3, ou um vault que o agente não
   consegue ler (exit 1 de um vault ilegível), com um conector disponível → modo só conector, a menos que a pessoa
   queira configurar/consertar esta máquina; e a linha do `capture` simples (ou o CHANGELOG) documenta que
   `--inbox` só vale com `--print`.
"""
import json
import os
import re
import shutil
import unittest

from brain_support import SKILL, output, snapshot
from test_connector import COLLEGE, PRINT_NAME
from test_inbox_cli import InboxCliTestCase
from test_inbox_instructions import SKILL_MD, sections

AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
CHANGELOG = SKILL / "CHANGELOG.md"


class ReviewPrintTestCase(InboxCliTestCase):
    def adopt_with_inbox(self):
        """Vault adotado com layout.inbox = Inbox, para distinguir o layout.inbox do padrão "inbox"."""
        self.box.vault.mkdir(parents=True)
        (self.box.vault / "Inbox").mkdir()
        self.assertExit(self.box.init("--adopt", "--map", "inbox=Inbox", *COLLEGE, provider="local"), 0)

    def lock(self, path):
        """chmod 000 em path; a permissão volta antes do cleanup do sandbox (ordem inversa do addCleanup)."""
        mode = path.stat().st_mode
        self.addCleanup(os.chmod, path, mode)
        os.chmod(path, 0)

    def assert_prints(self, pattern, *extra):
        """capture --print (texto e --json) sai com 0, caminho em pattern, conteúdo type: capture, nada escrito."""
        out = self.box.run("capture", "Ideia rápida", "--print", "--json", *extra)
        self.assertExit(out, 0)
        try:
            data = json.loads(out.stdout)
        except ValueError:
            self.fail(f"saída não é JSON: {output(out)}")
        self.assertRegex(data["path"], pattern)
        self.assertRegex(data["content"], r"^---\ntype: capture\ncreated: ")
        self.assertTrue(data["content"].endswith("\n\nIdeia rápida\n"), data["content"])
        text = self.box.run("capture", "Ideia rápida", "--print", *extra)
        self.assertExit(text, 0)
        self.assertRegex(text.stdout.partition("\n\n")[0], pattern)


class PrintWithUnreachableVaultTest(ReviewPrintTestCase):
    def check_unreachable(self, pattern, *extra):
        before = snapshot(self.box.root)
        self.assert_prints(pattern, *extra)
        self.assertEqual(snapshot(self.box.root), before, "--print não escreve nada (vault, log, configuração)")

    def test_print_with_the_vault_folder_removed_uses_inbox_or_the_inbox_option(self):
        """SPEC-0044:IT-01"""
        self.adopt_with_inbox()
        shutil.rmtree(self.box.vault)
        self.check_unreachable(rf"^inbox/{PRINT_NAME}$")
        self.check_unreachable(rf"^entrada/{PRINT_NAME}$", "--inbox", "entrada")
        self.assertFalse(self.box.vault.exists(), "o vault não é recriado")

    def test_print_with_the_brain_config_removed_uses_inbox(self):
        """SPEC-0044:IT-01"""
        self.adopt_with_inbox()
        (self.box.vault / "brain-config.yml").unlink()
        self.check_unreachable(rf"^inbox/{PRINT_NAME}$")
        self.check_unreachable(rf"^entrada/{PRINT_NAME}$", "--inbox", "entrada")

    @unittest.skipIf(AS_ROOT, "root lê pastas sem permissão")
    def test_print_with_an_unreadable_vault_uses_inbox_or_the_inbox_option(self):
        """SPEC-0044:IT-01"""
        self.adopt_with_inbox()
        before = snapshot(self.box.root)
        self.lock(self.box.vault)
        self.assert_prints(rf"^inbox/{PRINT_NAME}$")
        self.assert_prints(rf"^entrada/{PRINT_NAME}$", "--inbox", "entrada")
        os.chmod(self.box.vault, 0o755)
        self.assertEqual(snapshot(self.box.root), before, "--print não escreve nada")

    @unittest.skipIf(AS_ROOT, "root lê arquivos sem permissão")
    def test_print_with_an_unreadable_brain_config_uses_inbox(self):
        """SPEC-0044:IT-01"""
        self.adopt_with_inbox()
        self.lock(self.box.vault / "brain-config.yml")
        before = snapshot_dirs(self.box.root)
        self.assert_prints(rf"^inbox/{PRINT_NAME}$")
        self.assertEqual(snapshot_dirs(self.box.root), before, "--print não escreve nada")

    @unittest.skipIf(AS_ROOT, "root lê pastas sem permissão")
    def test_print_with_an_unreadable_inbox_uses_layout_inbox(self):
        """SPEC-0044:IT-01"""
        self.adopt_with_inbox()
        before = snapshot(self.box.root)
        self.lock(self.box.vault / "Inbox")
        self.assert_prints(rf"^Inbox/{PRINT_NAME}$")
        os.chmod(self.box.vault / "Inbox", 0o755)
        self.assertEqual(snapshot(self.box.root), before, "--print não escreve nada")


def snapshot_dirs(root):
    """snapshot sem ler o conteúdo dos arquivos (há um arquivo ilegível): só nomes e mtime."""
    return {path.relative_to(root).as_posix(): path.stat().st_mtime_ns for path in sorted(root.rglob("*"))}


class PrintInboxOptionTest(ReviewPrintTestCase):
    BAD = ("", ".", "..", "a/../../x", "/etc", "./", "a/..")

    def test_inbox_option_at_the_vault_root_or_outside_it_exits_2(self):
        """SPEC-0044:UT-02"""
        empty = self.box.root / "sem-config"
        for folder in self.BAD:
            with self.subTest(folder=folder, config=False):
                out = self.box.run("capture", "Ideia rápida", "--print", "--json", "--inbox", folder,
                                   config_home=empty)
                self.assertExit(out, 2)
        self.assertFalse(empty.exists(), "sem configuração, nada é gravado")

    def test_inbox_option_at_the_vault_root_or_outside_it_exits_2_with_the_vault_missing(self):
        """SPEC-0044:UT-02"""
        self.make_vault()
        shutil.rmtree(self.box.vault)
        before = snapshot(self.box.root)
        for folder in self.BAD:
            with self.subTest(folder=folder):
                self.assertExit(self.box.run("capture", "Ideia rápida", "--print", "--inbox", folder), 2)
        self.assertEqual(snapshot(self.box.root), before)

    def test_inbox_option_with_a_readable_config_or_without_print_exits_2(self):
        """SPEC-0044:UT-02"""
        self.make_vault()
        before = snapshot(self.box.root)
        cases = (("--print", "--inbox", "x"), ("--inbox", "x"), ("--print", "--json", "--inbox", "x"))
        for extra in cases:
            with self.subTest(extra=extra):
                self.assertExit(self.box.run("capture", "Ideia rápida", *extra), 2)
        self.assertEqual(snapshot(self.box.root), before, "nada escrito")
        empty = self.box.root / "sem-config"
        self.assertExit(self.box.run("capture", "Ideia rápida", "--inbox", "x", config_home=empty), 2)
        self.assertFalse(empty.exists())


EXIT_3 = r"exit 3"
EXIT_1 = r"exit 1"
UNREADABLE = r"n[ãa]o (consegue|consigo|d[áa] para) ler|ileg[íi]vel|inacess[íi]vel|sem acesso|can(no|')t read|unreadable"
UNLESS = r"a menos que|exceto se|salvo se|exceto quando|unless|except when"
SETUP = r"configurar|consertar|corrigir|arrumar|ligar (esta|a) m[áa]quina|set ?up|fix"


class ConnectorPrecedenceInstructionsTest(unittest.TestCase):
    def test_before_any_flow_gives_the_connector_mode_precedence_with_its_exception(self):
        """SPEC-0044:UT-03"""
        bodies = sections(SKILL_MD.read_text(encoding="utf-8"), r"antes de qualquer fluxo|before any flow")
        self.assertTrue(bodies, "SKILL.md sem a seção 'Antes de qualquer fluxo'")
        lines = [line for line in "\n".join(bodies).splitlines() if re.search(r"(?i)conector|connector", line)]
        self.assertTrue(lines, "'Antes de qualquer fluxo' não cita o conector")
        rules = {"exit 3": EXIT_3, "exit 1": EXIT_1, "vault ilegível": UNREADABLE,
                 "a menos que": UNLESS, "configurar/consertar esta máquina": SETUP}
        for rule, pattern in rules.items():
            with self.subTest(rule=rule):
                self.assertTrue(any(re.search(rf"(?i){pattern}", line) for line in lines),
                                f"regra do modo só conector sem '{rule}': {lines}")

    def test_inbox_option_is_documented_as_print_only(self):
        """SPEC-0044:UT-03"""
        print_only = r"--inbox`?[^\n]{0,40}(s[óo] vale|s[óo] funciona|only works|only with|exige)[^\n]{0,20}--print"
        rows = [line for line in SKILL_MD.read_text(encoding="utf-8").splitlines()
                if line.startswith("| `capture TEXTO") and "--print" not in line.split("|")[1]]
        self.assertTrue(rows, "SKILL.md sem a linha do capture simples na tabela de comandos")
        documented = any(re.search(rf"(?i){print_only}", row) for row in rows)
        top = "\n".join(CHANGELOG.read_text(encoding="utf-8").split("\n## ")[1:3])  # [Unreleased] e a mais nova
        documented = documented or bool(re.search(rf"(?i){print_only}", top))
        self.assertTrue(documented, "nem a linha do capture simples nem o CHANGELOG dizem que --inbox só vale com --print")


if __name__ == "__main__":
    unittest.main()
