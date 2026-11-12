"""Inbox: nome da captura, saída da inbox sem sobrescrever e classificação dos itens (SPEC-0021: UT-01 a UT-03).

Contrato esperado das funções de scripts/brain.py (o Implementer segue estes testes; seções 4 e 6 da spec).
Erros previstos são `brain.BrainError` (já existe), com `.code` = exit da CLI.

    capture_name(text: str, existing=(), clock=None) -> str
        Pura (sem I/O): nome do arquivo da captura, "AAAA-MM-DD-HHMMSS-<slug>.md", com a data e a hora de
        `clock()` (um callable sem argumentos que devolve datetime; None = datetime.now) e o slug das 6
        primeiras palavras de `text` no formato de `slugify` (minúsculas ASCII, acentos removidos, "-").
        `existing` = nomes já presentes na inbox: nome tomado -> "<base>-1.md", "-2"...

    move_out_of_inbox(item: Path, dest: Path, vault: Path, layout: dict) -> Path
        A única função que move arquivo (ADR-0007, seção 4). Move `item` (que precisa estar dentro de
        <vault>/<layout["inbox"]>, já resolvido: "inbox/../raw/x" é fora) para `dest`, criando as pastas que
        faltarem; `dest` já existente -> "<stem>-1<ext>", "-2"... e o arquivo existente nunca muda.
        Devolve o caminho final. Origem fora da inbox -> BrainError(code 2), nada se move nem se cria.
        `dest` pode ficar fora do vault (a pasta files do `ingest --move`). A linha do log.md é conferida na CLI
        (test_inbox_cli, IT-03/IT-04); parâmetros extras para o log precisam de valor padrão.

    classify_inbox_item(path: Path, now: float | None = None) -> str
        "text" (.md, .txt) | "link" (.url, .webloc, ou .md/.txt cujo texto é só uma URL) | "file" (o resto) |
        "syncing" (placeholder do iCloud "*.icloud", ou arquivo de 0 bytes com mtime recente em relação a
        `now`, em segundos desde a época; None = agora). Nome com caracteres estranhos vindos do celular é
        aceito (seção 5).
"""
import datetime as dt
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from brain_support import brain, fn

SPEC = "SPEC-0021"
LAYOUT = {"inbox": "inbox", "raw": "raw", "mocs": "mocs", "templates": "templates",
          "index": "index.md", "log": "log.md"}
FIXED = dt.datetime(2026, 10, 30, 14, 5, 9)
WEBLOC = (b'<?xml version="1.0"?><plist><dict><key>URL</key>'
          b"<string>https://example.com</string></dict></plist>")


def capture_name(text, existing=()):
    return fn("capture_name", SPEC)(text, existing=existing, clock=lambda: FIXED)


class TempVaultCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.vault = self.root / "Vault"
        for folder in ("inbox", "raw", "mocs", "templates"):
            (self.vault / folder).mkdir(parents=True)
        (self.vault / "log.md").write_text("# Log\n", encoding="utf-8")

    def put(self, rel, data, base=None):
        path = (base or self.vault) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")
        return path


class CaptureNameTest(unittest.TestCase):
    def test_same_second_gets_suffix_1_and_slug_has_the_first_six_words(self):
        """SPEC-0021:UT-01"""
        text = "Ideia para o TCC sobre grafos de conhecimento"
        first = capture_name(text)
        self.assertEqual(first, "2026-10-30-140509-ideia-para-o-tcc-sobre-grafos.md")
        second = capture_name(text, existing={first})
        self.assertEqual(second, "2026-10-30-140509-ideia-para-o-tcc-sobre-grafos-1.md")
        third = capture_name(text, existing={first, second})
        self.assertEqual(third, "2026-10-30-140509-ideia-para-o-tcc-sobre-grafos-2.md")
        self.assertEqual(capture_name("Revisão de cálculo amanhã às 9h na biblioteca"),
                         "2026-10-30-140509-revisao-de-calculo-amanha-as-9h.md")


class MoveOutOfInboxTest(TempVaultCase):
    def move(self, item, dest):
        return fn("move_out_of_inbox", SPEC)(item, dest, self.vault, LAYOUT)

    def test_existing_destination_gets_suffix_1_and_source_outside_inbox_is_refused(self):
        """SPEC-0021:UT-02"""
        item = self.put("inbox/ideia.md", "Ideia nova vinda do celular.\n")
        existing = self.put("raw/processed/2026-10/ideia.md", "Ideia antiga, já processada.\n")
        mtime = existing.stat().st_mtime_ns

        final = Path(self.move(item, self.vault / "raw/processed/2026-10/ideia.md"))
        self.assertEqual(final, self.vault / "raw/processed/2026-10/ideia-1.md")
        self.assertEqual(final.read_text(encoding="utf-8"), "Ideia nova vinda do celular.\n")
        self.assertFalse(item.exists(), "o item saiu da inbox")
        self.assertEqual(existing.read_text(encoding="utf-8"), "Ideia antiga, já processada.\n")
        self.assertEqual(existing.stat().st_mtime_ns, mtime, "o destino existente não muda")

        again = self.put("inbox/ideia.md", "Terceira versão.\n")
        final = Path(self.move(again, self.vault / "raw/processed/2026-10/ideia.md"))
        self.assertEqual(final, self.vault / "raw/processed/2026-10/ideia-2.md")

        pdf = self.put("inbox/Scan às 14h (1) ✨.pdf", b"%PDF-1.4 celular")
        files = self.root / "Vault-files"
        final = Path(self.move(pdf, files / "college" / "2026" / pdf.name))
        self.assertEqual(final.read_bytes(), b"%PDF-1.4 celular", "destino fora do vault (files) e nome estranho")
        self.assertFalse(pdf.exists())

        outside = (
            self.put("raw/solta.md", "fora da inbox\n"),
            self.put("fora.md", "fora do vault\n", base=self.root),
        )
        for source in (*outside, self.vault / "inbox" / ".." / "raw" / "solta.md"):
            with self.subTest(source=str(source)):
                dest = self.vault / "raw/processed/2026-10" / f"novo-{source.name}"
                with self.assertRaises(brain().BrainError) as caught:
                    self.move(source, dest)
                self.assertEqual(caught.exception.code, 2)
                self.assertTrue(source.exists(), "a origem fora da inbox não se move")
                self.assertFalse(dest.exists(), "nada é criado no destino")


class ClassifyInboxItemTest(TempVaultCase):
    def classify(self, path, now):
        return fn("classify_inbox_item", SPEC)(path, now=now)

    def test_kinds_text_link_file_and_syncing(self):
        """SPEC-0021:UT-03"""
        now = time.time()
        items = {
            "a.md": ("Ideia sobre grafos de conhecimento.\n", "text"),
            "b.txt": ("https://example.com/artigo-sobre-grafos\n", "link"),
            "c.webloc": (WEBLOC, "link"),
            "d.pdf": (b"%PDF-1.4 aula", "file"),
            "e.pdf.icloud": (b"bplist00\x01\x02placeholder", "syncing"),
            "f-recente": (b"", "syncing"),
            "g.url": ("[InternetShortcut]\nURL=https://example.com\n", "link"),
            "Foto 30-10 às 14.05 (1) ✨.jpg": (b"\xff\xd8\xff jpeg", "file"),
        }
        old = now - 3 * 86400
        for name, (data, _) in items.items():
            path = self.put(f"inbox/{name}", data)
            os.utime(path, (old, old))
        recent = self.vault / "inbox" / "f-recente"
        os.utime(recent, (now, now))
        for name, (_, kind) in items.items():
            with self.subTest(name=name):
                self.assertEqual(self.classify(self.vault / "inbox" / name, now), kind)


if __name__ == "__main__":
    unittest.main()
