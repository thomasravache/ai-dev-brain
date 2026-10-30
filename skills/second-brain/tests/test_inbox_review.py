"""Regressões da revisão (CHANGES_REQUESTED) da SPEC-0021: inbox e captura pelo celular.

Decisões do Architect que estes testes fixam (os IDs do plano entre parênteses):

1. (major, IT-04) `inbox done ITEM --note X`: X absoluto dentro do vault vira caminho relativo ao vault; X absoluto
   fora do vault -> exit 2, nada se move, nada vai para o log. O log.md nunca contém caminho absoluto.
2. (IT-03/IT-04) Item que é link simbólico é recusado com exit 2 por `ingest --move` e `inbox done`; nada se move e
   o log não ganha linha.
3. (IT-03/IT-04) Item dentro de subpasta oculta da inbox (qualquer parte do caminho começando com ".") é recusado
   com exit 2, coerente com o `inbox list`, que esconde essas pastas.
4. (UT-03/IT-04) Nome de item com caracteres de controle (ex.: quebra de linha) vai para o log.md e para a saída com
   os caracteres de controle escapados/colapsados: cada linha do log continua casando "^- AAAA-MM-DD HH:MM <cmd> ".
5. (UT-03/IT-02) .md/.txt com bytes NUL é classificado como `file`; a prévia nunca tem caracteres de controle; a
   prévia de .webloc tem as entidades XML resolvidas (&amp; -> &).
6. (IT-02) inbox_stale_days inválido (negativo, decimal, texto) cai no padrão 7, mas `config --json` e `doctor`
   mostram um aviso/problema que cita inbox_stale_days.
7. (IT-03/IT-02) `ingest --move` recusa item sincronizando (.icloud e arquivo de 0 bytes recente) com "ainda
   sincronizando"; `inbox list` mostra pela CLI um arquivo de 0 bytes recente como syncing.
8. (UT-04) references/mobile-capture.md não põe "pago" entre os fatos da fonte verificada; references/config.md
   documenta `inbox_stale_days`; references/inbox.md diz que o `ingest --move` falha com segurança quando `files`
   fica em outro volume.
"""
import json
import os
import re
import time
import unittest

from brain_support import SKILL, doctor_lines, fn, output, snapshot
from test_inbox import TempVaultCase
from test_inbox_cli import InboxCliTestCase
from test_inbox_instructions import read, sections

SPEC = "SPEC-0021"
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
DONE_LINE = re.compile(r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} inbox-done ")
MOVE_LINES = re.compile(r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} (inbox-move|ingest) ")
WEBLOC_AMP = (b'<?xml version="1.0"?><plist><dict><key>URL</key>'
              b"<string>https://example.com/busca?a=1&amp;b=2</string></dict></plist>")


class ReviewCliTestCase(InboxCliTestCase):
    def assertUnchanged(self, out, before_vault, before_drive, code=2):
        self.assertExit(out, code)
        self.assertEqual(snapshot(self.box.vault), before_vault, "nada se move e o log não muda")
        self.assertEqual(snapshot(self.box.root / "Drive"), before_drive, "files não muda")

    def snapshots(self):
        return snapshot(self.box.vault), snapshot(self.box.root / "Drive")

    def assertNoAbsolutePath(self):
        self.assertNotIn(str(self.box.root), self.log(), "log.md nunca tem caminho absoluto")


class DoneNoteAbsolutePathTest(ReviewCliTestCase):
    def test_absolute_note_inside_the_vault_is_logged_relative(self):
        """SPEC-0021:IT-04 — decisão 1"""
        self.make_vault()
        self.assertExit(self.box.run("new-note", "--type", "note", "--title", "Ideia sobre grafos",
                                     "--context", "college"), 0)
        cases = (("inbox/a.md", self.box.vault / "projects/college/Ideia sobre grafos.md",
                  "projects/college/Ideia sobre grafos"),
                 ("inbox/b.md", self.box.vault / "projects/college/Rascunho futuro.md",
                  "projects/college/Rascunho futuro"))
        for item, note, relative in cases:
            with self.subTest(note=str(note)):
                self.put(item, "Texto do celular.\n")
                log_before = self.log()
                out = self.run_in_vault("inbox", "done", item, "--note", note)
                self.assertExit(out, 0)
                lines = self.new_log_lines(log_before)
                self.assertTrue(any(re.search(rf"nota: {re.escape(relative)}(\.md)?\s*$", line) for line in lines),
                                lines)
                self.assertNotIn(str(note), output(out) + "".join(lines))
                self.assertNoAbsolutePath()

    def test_absolute_note_outside_the_vault_exits_2_and_nothing_moves(self):
        """SPEC-0021:IT-04 — decisão 1"""
        self.make_vault()
        outside = self.put("fora/nota.md", "# Nota fora\n", base=self.box.root)
        self.put("inbox/c.md", "Texto do celular.\n")
        before = self.snapshots()
        out = self.run_in_vault("inbox", "done", "inbox/c.md", "--note", outside)
        self.assertUnchanged(out, *before)
        self.assertTrue((self.box.vault / "inbox/c.md").is_file(), "o item fica na inbox")
        self.assertNoAbsolutePath()


class SymlinkItemTest(ReviewCliTestCase):
    def test_symlinked_items_are_refused_by_ingest_move_and_done(self):
        """SPEC-0021:IT-03 — decisão 2"""
        self.make_vault()
        pdf = self.put("fora/segredo.pdf", b"%PDF-1.4 fora", base=self.box.root)
        note = self.put("raw/nota.md", "Nota guardada.\n")
        links = {"inbox/atalho.pdf": pdf, "inbox/atalho.md": note}
        for rel, target in links.items():
            (self.box.vault / rel).symlink_to(target)
        cases = (("ingest", "inbox/atalho.pdf", "--move", "--context", "college"),
                 ("inbox", "done", "inbox/atalho.md"))
        for args in cases:
            with self.subTest(args=args):
                before = self.snapshots()
                out = self.run_in_vault(*args)
                self.assertUnchanged(out, *before)
                for rel, target in links.items():
                    self.assertTrue((self.box.vault / rel).is_symlink(), f"{rel} continua na inbox")
                    self.assertTrue(target.is_file(), f"o alvo de {rel} não muda")
        self.assertEqual(pdf.read_bytes(), b"%PDF-1.4 fora")
        self.assertEqual(note.read_text(encoding="utf-8"), "Nota guardada.\n")


class HiddenSubfolderTest(ReviewCliTestCase):
    def test_items_in_hidden_inbox_subfolders_are_refused(self):
        """SPEC-0021:IT-04 — decisão 3"""
        self.make_vault()
        self.put("inbox/.oculta/aula.pdf", b"%PDF-1.4 oculto")
        self.put("inbox/.oculta/nota.md", "Texto oculto.\n")
        self.put("inbox/visivel/.mais/fundo.md", "Mais fundo.\n")
        self.assertEqual(self.inbox_items(), [], "inbox list esconde as subpastas ocultas")
        cases = (("ingest", "inbox/.oculta/aula.pdf", "--move", "--context", "college"),
                 ("inbox", "done", "inbox/.oculta/nota.md"),
                 ("inbox", "done", "inbox/visivel/.mais/fundo.md"))
        for args in cases:
            with self.subTest(args=args):
                before = self.snapshots()
                self.assertUnchanged(self.run_in_vault(*args), *before)


class ControlCharacterNameTest(ReviewCliTestCase):
    def assertClean(self, text, what):
        self.assertIsNone(CONTROL.search(text), f"{what} com caractere de controle: {text!r}")

    def test_done_logs_and_prints_a_name_with_control_characters_on_one_line(self):
        """SPEC-0021:IT-04 — decisão 4"""
        self.make_vault()
        name = "linha\nnova\t\x1b[2J.md"
        self.put(f"inbox/{name}", "Ideia com nome estranho.\n")
        listed = self.run_in_vault("inbox", "list")
        self.assertExit(listed, 0)
        self.assertFalse([line for line in listed.stdout.splitlines() if line.startswith("nova")],
                         f"o nome quebrou a saída do inbox list: {listed.stdout!r}")
        self.assertClean(listed.stdout.replace("\n", ""), "inbox list")

        log_before = self.log()
        out = self.run_in_vault("inbox", "done", f"inbox/{name}")
        self.assertExit(out, 0)
        self.processed(name)
        self.assertEqual(len(out.stdout.strip().splitlines()), 1, f"saída em uma linha: {out.stdout!r}")
        self.assertClean(out.stdout.strip(), "saída do inbox done")
        lines = self.new_log_lines(log_before)
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0], DONE_LINE)
        self.assertClean(self.log().replace("\n", ""), "log.md")

    def test_ingest_move_logs_a_name_with_control_characters_on_one_line_each(self):
        """SPEC-0021:IT-03 — decisão 4"""
        self.make_vault()
        name = "scan\nnovo\t\x1b.pdf"
        self.put(f"inbox/{name}", b"%PDF-1.4 celular")
        log_before = self.log()
        out = self.run_in_vault("ingest", f"inbox/{name}", "--move", "--context", "college", "--json")
        self.assertExit(out, 0)
        lines = self.new_log_lines(log_before)
        self.assertEqual(len(lines), 2, lines)
        for line in lines:
            with self.subTest(line=line):
                self.assertRegex(line, MOVE_LINES)
        self.assertClean(self.log().replace("\n", ""), "log.md")


class ClassifyNulTest(TempVaultCase):
    def test_text_with_nul_bytes_is_a_file(self):
        """SPEC-0021:UT-03 — decisão 5"""
        classify = fn("classify_inbox_item", SPEC)
        old = time.time() - 3 * 86400
        for name in ("binario.md", "binario.txt"):
            with self.subTest(name=name):
                path = self.put(f"inbox/{name}", b"texto\x00\x01\x02binario")
                os.utime(path, (old, old))
                self.assertEqual(classify(path, now=time.time()), "file")


class PreviewTest(ReviewCliTestCase):
    def test_previews_have_no_control_characters_and_webloc_entities_are_unescaped(self):
        """SPEC-0021:IT-02 — decisão 5"""
        self.make_vault()
        self.put("inbox/controle.md", "Linha com\x07sino e\x1b[31mcor\x7f no fim.\n", age_days=3)
        self.put("inbox/nul.txt", b"texto\x00binario", age_days=2)
        self.put("inbox/busca.webloc", WEBLOC_AMP, age_days=1)
        by_path = {self.rel(i["path"]): i for i in self.inbox_items()}
        with self.subTest(item="inbox/nul.txt"):
            self.assertEqual(by_path["inbox/nul.txt"]["kind"], "file")
            self.assertFalse(by_path["inbox/nul.txt"]["preview"], "file não tem prévia")
        with self.subTest(item="inbox/controle.md"):
            preview = by_path["inbox/controle.md"]["preview"]
            self.assertEqual(by_path["inbox/controle.md"]["kind"], "text")
            self.assertIsNone(CONTROL.search(preview), f"prévia com caractere de controle: {preview!r}")
            self.assertIn("sino", preview)
        with self.subTest(item="inbox/busca.webloc"):
            self.assertEqual(by_path["inbox/busca.webloc"]["kind"], "link")
            self.assertEqual(by_path["inbox/busca.webloc"]["preview"], "https://example.com/busca?a=1&b=2")


class InvalidStaleDaysTest(ReviewCliTestCase):
    def test_invalid_stale_days_falls_back_to_7_with_a_warning(self):
        """SPEC-0021:IT-02 — decisão 6"""
        self.make_vault()
        shared = self.box.vault / "brain-config.yml"
        original = shared.read_text(encoding="utf-8")
        self.assertRegex(original, r"(?m)^inbox_stale_days:")
        for raw in ("-3", "2.5", "sete"):
            with self.subTest(value=raw):
                shared.write_text(re.sub(r"(?m)^inbox_stale_days:.*$", f"inbox_stale_days: {raw}", original),
                                  encoding="utf-8")
                config = self.box.config_json()
                self.assertEqual(config["values"].get("inbox_stale_days"), 7)
                self.assertEqual([i["stale"] for i in self.inbox_items()], [], "inbox list segue funcionando")
                with self.subTest(value=raw, command="config --json"):
                    rest = {k: v for k, v in config.items() if k not in ("values", "origins")}
                    self.assertIn("inbox_stale_days", json.dumps(rest, ensure_ascii=False),
                                  f"config --json sem aviso de inbox_stale_days: {rest}")
                with self.subTest(value=raw, command="doctor"):
                    out = self.box.run("doctor")
                    self.assertNotIn("Traceback", output(out))
                    rows = [row for row in doctor_lines(out.stdout)
                            if row[0] in ("AVISO", "ERRO") and "inbox_stale_days" in f"{row[1]} {row[2]}"]
                    self.assertTrue(rows, f"doctor sem aviso de inbox_stale_days:\n{out.stdout}")


class SyncingMoveTest(ReviewCliTestCase):
    def test_ingest_move_refuses_syncing_items_and_list_shows_a_recent_empty_file_as_syncing(self):
        """SPEC-0021:IT-03 — decisão 7"""
        self.make_vault()
        self.put("inbox/video.mov.icloud", b"bplist00\x01placeholder", age_days=1)
        self.put("inbox/.foto.jpg.icloud", b"bplist00\x01placeholder", age_days=1)
        self.put("inbox/chegando.pdf", b"")
        kinds = {self.rel(i["path"]): i["kind"] for i in self.inbox_items()}
        self.assertEqual(kinds.get("inbox/chegando.pdf"), "syncing", kinds)
        listed = self.run_in_vault("inbox", "list")
        self.assertExit(listed, 0)
        self.assertIn("ainda sincronizando", listed.stdout)
        for item in ("inbox/video.mov.icloud", "inbox/.foto.jpg.icloud", "inbox/chegando.pdf"):
            with self.subTest(item=item):
                before = self.snapshots()
                out = self.run_in_vault("ingest", item, "--move", "--context", "college")
                self.assertUnchanged(out, *before)
                self.assertIn("ainda sincronizando", output(out))


class ReviewInstructionsTest(unittest.TestCase):
    def test_mobile_capture_does_not_list_paid_among_the_verified_facts(self):
        """SPEC-0021:UT-04 — decisão 8"""
        text = read(SKILL / "references" / "mobile-capture.md")
        m = re.search(r"\*\*Fonte verificada:\*\*.*?\n\n((?:- .*\n?)+)", text)
        self.assertTrue(m, "mobile-capture.md sem a lista de fatos da fonte verificada")
        self.assertNotRegex(m.group(1), r"(?i)\bpag[oa]s?\b|\bpaid\b", "'pago' não está na fonte verificada")

    def test_config_md_documents_inbox_stale_days(self):
        """SPEC-0021:UT-04 — decisão 8"""
        self.assertIn("inbox_stale_days", read(SKILL / "references" / "config.md"))

    def test_inbox_md_says_ingest_move_fails_safely_on_another_volume(self):
        """SPEC-0021:UT-04 — decisão 8"""
        bodies = sections(read(SKILL / "references" / "inbox.md"), r"ingest .*--move")
        self.assertTrue(bodies, "inbox.md sem seção do ingest --move")
        self.assertRegex("\n".join(bodies), r"(?i)outro (volume|disco)|(another|other|different) (volume|disk)")


if __name__ == "__main__":
    unittest.main()
