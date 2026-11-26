"""Integração pela CLI: `append` e `new-note --body-file` (SPEC-0107: CH-01, UT-03 a UT-06, IT-01, IT-02).

Cada teste cria o vault com o `brain.py init` real num diretório temporário com HOME, XDG_CONFIG_HOME e
BRAIN_CONFIG_HOME isolados (brain_support.Sandbox). Mensagens de erro podem ir para stdout ou stderr.

Contrato (seção 6 da spec):
    append NOTA --section TÍTULO --text-file ARQ [--json]
        NOTA: caminho relativo ao vault ou nome da nota, resolvido como no relate.
        sucesso (exit 0): "acrescentado: <rel> — ## TÍTULO" | {"note", "section", "created_section"} (--json)
        BOM e fim de linha da nota preservados, inclusive nas linhas acrescentadas.
        log.md: "- <agora> append <rel> — ## TÍTULO" (nunca o texto acrescentado).
        exit 2, nada gravado: nota não encontrada | fora do vault (inclusive por link simbólico) | --text-file
        ausente, binário, vazio ou > 1 MiB | TÍTULO vazio, com quebra de linha, começando com "#" ou "Relations".
        exit 3: sem configuração.
    new-note --type T --title X [...] --body-file ARQ
        o texto do arquivo substitui as seções do modelo entre "# título" e "## Relations"; frontmatter e
        "## Relations" do modelo. log.md: "- <agora> new-note <rel> — <tipo>; com corpo".
        exit 2, nada criado: --body-file ausente, binário, vazio ou > 1 MiB; corpo com uma linha "## Relations".
"""
import datetime as dt
import json
import os
import re
import unittest

from brain_support import LOG_LINE, output, snapshot
from test_cli import CliTestCase

COLLEGE = ("--context", "college=projects/college:College")
MIB = 1024 * 1024
APPEND_LOG = re.compile(r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} append (.+) — ## (.+)$")
NEW_NOTE_LOG = re.compile(r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} new-note (.+) — (.+)$")
RELATE_LOG = re.compile(r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} relate (.+) → \[\[(.+)\]\] — (.+)$")


def today():
    return dt.date.today().isoformat()


class AppendCliTestCase(CliTestCase):
    """Vault criado pelo init com o contexto college."""

    def setUp(self):
        super().setUp()
        self.box.vault.mkdir(parents=True)
        self.assertExit(self.box.init(*COLLEGE), 0)

    def write(self, rel, data):
        path = self.box.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_bytes(data.encode("utf-8"))
        return path

    def read(self, rel):
        return (self.box.vault / rel).read_bytes().decode("utf-8")

    def text_file(self, name, data):
        """Arquivo de texto de entrada, fora do vault."""
        path = self.box.root / "entrada" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def log(self):
        return self.read("log.md")

    def new_log_lines(self, before):
        after = self.log()
        self.assertTrue(after.startswith(before), "log.md só recebe linhas no fim")
        return [line for line in after[len(before):].splitlines() if line.strip()]

    def note(self, rel="projects/college/Aula 1.md", body="## Summary\n\nTexto antigo.\n\n"):
        text = ("---\ntype: note\ntitle: \"Aula 1\"\ncontext: college\ncreated: 2026-01-01\ntags: []\n---\n\n"
                "# Aula 1\n\n" + body + "## Relations\n")
        self.write(rel, text)
        return rel, text

    def append(self, *args):
        return self.box.run("append", *args)

    def lint_findings(self):
        out = self.box.run("lint", "--json")
        try:
            data = json.loads(out.stdout)
        except ValueError:
            self.fail(f"lint --json não imprimiu JSON: {output(out)}")
        return sorted((f["rule"], f["path"], f["detail"]) for f in data["findings"])


class CharacterizationTest(AppendCliTestCase):
    def test_new_note_without_body_file_and_relate_are_unchanged(self):
        """SPEC-0107:CH-01 — new-note sem --body-file e relate como hoje (passa antes da mudança)."""
        # SPEC-0107:CH-01
        before = self.log()
        out = self.box.run("new-note", "--type", "note", "--title", "Aula 1", "--context", "college")
        self.assertExit(out, 0)
        self.assertEqual(out.stdout.strip(), "projects/college/Aula 1.md")
        out = self.box.run("new-note", "--type", "note", "--title", "Aula 2", "--json")
        self.assertExit(out, 0)
        self.assertEqual(json.loads(out.stdout), {"path": "resources/Aula 2.md"})
        created = today()
        self.assertEqual(self.read("projects/college/Aula 1.md"),
                         f"---\ntype: note\ntitle: \"Aula 1\"\ncontext: college\ncreated: {created}\ntags: []\n"
                         "---\n\n# Aula 1\n\n## Summary\n\n## Relations\n")
        out = self.box.run("relate", "Aula 1", "Aula 2", "--why", "continua")
        self.assertExit(out, 0)
        self.assertEqual(out.stdout.strip(), "projects/college/Aula 1.md: - [[Aula 2]] — continua")
        self.assertEqual(self.read("projects/college/Aula 1.md"),
                         f"---\ntype: note\ntitle: \"Aula 1\"\ncontext: college\ncreated: {created}\ntags: []\n"
                         "---\n\n# Aula 1\n\n## Summary\n\n## Relations\n\n- [[Aula 2]] — continua\n")
        lines = self.new_log_lines(before)
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual([NEW_NOTE_LOG.match(line).groups() if NEW_NOTE_LOG.match(line) else line
                          for line in lines[:2]],
                         [("projects/college/Aula 1.md", "note"), ("resources/Aula 2.md", "note")])
        m = RELATE_LOG.match(lines[2])
        self.assertTrue(m, lines[2])
        self.assertEqual(m.groups(), ("projects/college/Aula 1.md", "Aula 2", "continua"))


class AppendFormatTest(AppendCliTestCase):
    def test_bom_and_crlf_are_kept_including_the_added_lines(self):
        """SPEC-0107:UT-03 — BOM e CRLF mantidos, seção nova e seção existente."""
        # SPEC-0107:UT-03
        rel = "projects/college/Crlf.md"
        text = ("﻿---\r\ntype: note\r\ntitle: \"Crlf\"\r\ncreated: 2026-01-01\r\n---\r\n\r\n# Crlf\r\n\r\n"
                "## Summary\r\n\r\nAntigo.\r\n\r\n## Relations\r\n\r\n- [[Aula 2]] — continua\r\n")
        self.write(rel, text)
        addition = self.text_file("add.txt", "Linha um.\nLinha dois.\n")
        for _ in range(2):  # a primeira cria a seção, a segunda acrescenta a ela
            self.assertExit(self.append(rel, "--section", "Resumo", "--text-file", addition), 0)
        data = (self.box.vault / rel).read_bytes()
        self.assertTrue(data.startswith("﻿".encode()), data[:10])
        self.assertEqual(data.count("﻿".encode()), 1, data)
        new = data.decode("utf-8")
        self.assertNotRegex(new, r"(?<!\r)\n", "toda linha termina com CRLF, inclusive as acrescentadas")
        self.assertEqual(new.count("Linha um.\r\nLinha dois.\r\n"), 2, new)
        self.assertTrue(new.startswith(text[:text.index("## Relations")].rstrip("\r\n")), new)
        self.assertTrue(new.endswith("## Relations\r\n\r\n- [[Aula 2]] — continua\r\n"), new)


class AppendErrorsTest(AppendCliTestCase):
    def assertRefused(self, out, rel, vault_before):
        self.assertExit(out, 2)
        self.assertNotIn("usage:", output(out), "recusado pelo comando, não pelo parser")
        self.assertEqual(snapshot(self.box.vault), vault_before, f"nada muda no vault: {output(out)}")

    def test_invalid_titles_exit_2_and_change_nothing(self):
        """SPEC-0107:UT-04 — título vazio, com quebra de linha, começando com # ou igual a Relations."""
        # SPEC-0107:UT-04
        rel, _ = self.note()
        addition = self.text_file("add.txt", "Texto.\n")
        vault_before = snapshot(self.box.vault)
        for title in ("", "   ", "Linha\nquebrada", "#Resumo", "# Resumo", "## Resumo", "Relations"):
            with self.subTest(title=title):
                self.assertRefused(self.append(rel, "--section", title, "--text-file", addition), rel, vault_before)

    def test_invalid_text_files_exit_2_and_change_nothing(self):
        """SPEC-0107:UT-04 — --text-file ausente, binário, vazio ou maior que 1 MiB."""
        # SPEC-0107:UT-04
        rel, _ = self.note()
        files = {
            "ausente": self.box.root / "entrada" / "nao-existe.txt",
            "binário": self.text_file("bin.txt", b"abc\x00\x01\x02def\n"),
            "vazio": self.text_file("vazio.txt", b""),
            "grande": self.text_file("grande.txt", b"a" * (MIB + 1)),
        }
        vault_before = snapshot(self.box.vault)
        for name, path in files.items():
            with self.subTest(arquivo=name):
                self.assertRefused(self.append(rel, "--section", "Resumo", "--text-file", path), rel, vault_before)

    def test_text_file_of_exactly_1_mib_is_accepted(self):
        """SPEC-0107:UT-04 — o limite é "maior que 1 MiB": 1 MiB exato passa."""
        # SPEC-0107:UT-04
        rel, _ = self.note()
        path = self.text_file("limite.txt", b"a" * (MIB - 1) + b"\n")
        self.assertExit(self.append(rel, "--section", "Resumo", "--text-file", path), 0)

    def test_missing_or_outside_notes_exit_2_and_change_nothing(self):
        """SPEC-0107:UT-04 — nota não encontrada ou fora do vault (caminho e link simbólico)."""
        # SPEC-0107:UT-04
        self.note()
        outside = self.box.root / "fora" / "Externa.md"
        outside.parent.mkdir(parents=True)
        outside_text = "# Externa\n\n## Relations\n"
        outside.write_text(outside_text, encoding="utf-8")
        link = self.box.vault / "projects" / "college" / "Link.md"
        os.symlink(outside, link)
        addition = self.text_file("add.txt", "Texto.\n")
        vault_before = snapshot(self.box.vault)
        for ref in ("Não Existe", "projects/college/Nao Existe.md", "../fora/Externa.md", str(outside),
                    "projects/college/Link.md", "Link"):
            with self.subTest(nota=ref):
                self.assertRefused(self.append(ref, "--section", "Resumo", "--text-file", addition), ref,
                                   vault_before)
                self.assertEqual(outside.read_text(encoding="utf-8"), outside_text, "o arquivo de fora não muda")

    def test_without_config_exit_3(self):
        """SPEC-0107:UT-04 — sem configuração, exit 3 como os outros comandos."""
        # SPEC-0107:UT-04
        addition = self.text_file("add.txt", "Texto.\n")
        out = self.box.run("append", "Aula 1", "--section", "Resumo", "--text-file", addition,
                           config_home=self.box.root / "sem-config")
        self.assertExit(out, 3)


class AppendLogTest(AppendCliTestCase):
    def test_log_line_has_path_and_title_never_the_text(self):
        """SPEC-0107:UT-05 — uma linha no formato LOG_LINE com caminho e ## título, sem o texto."""
        # SPEC-0107:UT-05
        rel, _ = self.note()
        secret_lines = ["Primeira linha distinta 7f3a.", "Segunda linha distinta 9b1c."]
        addition = self.text_file("add.txt", "\n".join(secret_lines) + "\n")
        for ref, created in (("Aula 1", True), (rel, False)):  # por nome e por caminho
            with self.subTest(nota=ref):
                before = self.log()
                out = self.append(ref, "--section", "Resumo", "--text-file", addition, "--json")
                self.assertExit(out, 0)
                self.assertEqual(json.loads(out.stdout),
                                 {"note": rel, "section": "Resumo", "created_section": created})
                lines = self.new_log_lines(before)
                self.assertEqual(len(lines), 1, lines)
                self.assertRegex(lines[0], LOG_LINE)
                m = APPEND_LOG.match(lines[0])
                self.assertTrue(m, lines[0])
                self.assertEqual(m.groups(), (rel, "Resumo"))
                for secret in secret_lines:
                    self.assertNotIn(secret, self.log())
                    self.assertNotIn(secret[:20], lines[0])

    def test_text_output(self):
        """SPEC-0107:UT-05 — saída de texto "acrescentado: <rel> — ## TÍTULO"."""
        # SPEC-0107:UT-05
        rel, _ = self.note()
        addition = self.text_file("add.txt", "Texto.\n")
        out = self.append("Aula 1", "--section", "Resumo", "--text-file", addition)
        self.assertExit(out, 0)
        self.assertEqual(out.stdout.strip(), f"acrescentado: {rel} — ## Resumo")


class NewNoteBodyFileTest(AppendCliTestCase):
    def test_body_file_replaces_the_template_sections(self):
        """SPEC-0107:UT-06 — frontmatter do modelo, # título, o corpo e ## Relations; log "com corpo"."""
        # SPEC-0107:UT-06
        body = self.text_file("corpo.md", "## Ideias\n\n- uma\n- duas\n\n### Detalhe\n\nTexto do corpo.\n")
        before = self.log()
        out = self.box.run("new-note", "--type", "note", "--title", "Aula 3", "--context", "college",
                           "--body-file", body, "--json")
        self.assertExit(out, 0)
        rel = json.loads(out.stdout)["path"]
        self.assertEqual(rel, "projects/college/Aula 3.md")
        text = self.read(rel)
        self.assertTrue(text.startswith(f"---\ntype: note\ntitle: \"Aula 3\"\ncontext: college\ncreated: {today()}\n"
                                        "tags: []\n---\n\n# Aula 3\n\n"), text)
        self.assertNotIn("## Summary", text, "as seções do modelo saem")
        self.assertRegex(text, r"# Aula 3\n\n## Ideias\n\n- uma\n- duas\n\n### Detalhe\n\nTexto do corpo\.\n\n*"
                               r"## Relations\n\Z")
        self.assertEqual(text.count("## Relations"), 1, text)
        lines = self.new_log_lines(before)
        self.assertEqual(len(lines), 1, lines)
        m = NEW_NOTE_LOG.match(lines[0])
        self.assertTrue(m, lines[0])
        self.assertEqual(m.groups(), (rel, "note; com corpo"))
        self.assertNotIn("Texto do corpo", self.log())

    def test_invalid_body_exits_2_and_creates_nothing(self):
        """SPEC-0107:UT-06 — corpo com ## Relations ou arquivo ausente/binário/vazio/grande: exit 2, nada criado."""
        # SPEC-0107:UT-06
        bodies = {
            "com Relations": self.text_file("rel.md", "## Ideias\n\nA.\n\n## Relations\n\n- [[X]] — y\n"),
            "ausente": self.box.root / "entrada" / "nao-existe.md",
            "binário": self.text_file("bin.md", b"abc\x00\x01def\n"),
            "vazio": self.text_file("vazio.md", b""),
            "grande": self.text_file("grande.md", b"a" * (MIB + 1)),
        }
        vault_before = snapshot(self.box.vault)
        for name, path in bodies.items():
            with self.subTest(corpo=name):
                out = self.box.run("new-note", "--type", "note", "--title", "Aula 4", "--context", "college",
                                   "--body-file", path)
                self.assertExit(out, 2)
                self.assertNotIn("usage:", output(out), "recusado pelo comando, não pelo parser")
                self.assertFalse((self.box.vault / "projects" / "college" / "Aula 4.md").exists())
                self.assertEqual(snapshot(self.box.vault), vault_before, "nada criado, log igual")


class AppendJourneyTest(AppendCliTestCase):
    def test_two_appends_on_the_same_note(self):
        """SPEC-0107:IT-01 — seção nova e depois a mesma seção: os dois textos na ordem, lint igual, 2 linhas."""
        # SPEC-0107:IT-01
        self.assertExit(self.box.run("new-note", "--type", "note", "--title", "Aula 1", "--context", "college"), 0)
        rel = "projects/college/Aula 1.md"
        lint_before = self.lint_findings()
        log_before = self.log()
        first = self.text_file("um.txt", "Primeiro texto.\n")
        second = self.text_file("dois.txt", "Segundo texto.\n")
        out = self.append("Aula 1", "--section", "Resumo", "--text-file", first, "--json")
        self.assertExit(out, 0)
        self.assertEqual(json.loads(out.stdout), {"note": rel, "section": "Resumo", "created_section": True})
        out = self.append(rel, "--section", "Resumo", "--text-file", second, "--json")
        self.assertExit(out, 0)
        self.assertEqual(json.loads(out.stdout), {"note": rel, "section": "Resumo", "created_section": False})
        text = self.read(rel)
        self.assertEqual(text.count("## Resumo"), 1, text)
        self.assertRegex(text, r"## Summary\n\n+## Resumo\n\nPrimeiro texto\.\n\nSegundo texto\.\n\n*## Relations\n\Z")
        self.assertEqual(self.lint_findings(), lint_before, "o lint não acusa nada novo")
        lines = self.new_log_lines(log_before)
        lines = [line for line in lines if " lint " not in line]
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(all(APPEND_LOG.match(line) for line in lines), lines)

    def test_new_note_with_body_then_relate(self):
        """SPEC-0107:IT-02 — new-note --body-file e relate: corpo e relação na nota, as duas linhas no log."""
        # SPEC-0107:IT-02
        self.assertExit(self.box.run("new-note", "--type", "note", "--title", "Aula 2"), 0)
        body = self.text_file("corpo.md", "## Ideias\n\nCorpo da aula.\n")
        before = self.log()
        out = self.box.run("new-note", "--type", "note", "--title", "Aula 1", "--context", "college",
                           "--body-file", body)
        self.assertExit(out, 0)
        rel = out.stdout.strip()
        self.assertEqual(rel, "projects/college/Aula 1.md")
        self.assertExit(self.box.run("relate", "Aula 1", "Aula 2", "--why", "continua"), 0)
        text = self.read(rel)
        self.assertRegex(text, r"# Aula 1\n\n## Ideias\n\nCorpo da aula\.\n\n*## Relations\n\n- \[\[Aula 2\]\] — "
                               r"continua\n\Z")
        lines = self.new_log_lines(before)
        self.assertEqual(len(lines), 2, lines)
        m = NEW_NOTE_LOG.match(lines[0])
        self.assertTrue(m, lines[0])
        self.assertEqual(m.groups(), (rel, "note; com corpo"))
        m = RELATE_LOG.match(lines[1])
        self.assertTrue(m, lines[1])
        self.assertEqual(m.groups(), (rel, "Aula 2", "continua"))
        self.assertEqual(self.lint_findings(), [], "vault sem achados")


if __name__ == "__main__":
    unittest.main()
