"""Captura pelo conector do provedor: `capture --print` monta o arquivo da captura sem escrever nada
(SPEC-0044: UT-01, UT-02, IT-01 e IT-02; ADR-0013).

O conector é usado pelo agente, nunca pelo `brain.py` (ADR-0007): o `brain.py` só monta o nome e o conteúdo, e o
agente cria o arquivo em <vault>/<layout.inbox>/ pelo conector. Os testes de CLI usam brain_support.Sandbox
(HOME e BRAIN_CONFIG_HOME isolados; o vault, quando existe, é criado pelo `init` real em <tmp>/Drive/Vault).

Interface esperada (contrato da seção 6):

    brain.py capture TEXTO --print [--context C] [--inbox PASTA] [--json]
        Não escreve nada: nem no vault, nem na configuração local, nem no log.md.
        Não exige configuração: com configuração usa layout.inbox; sem ela, "inbox" ou o --inbox informado.
        Caminho relativo ao vault: "<inbox>/AAAA-MM-DD-HHMMSS-<slug>.md" (o mesmo nome do capture, capture_name).
        Conteúdo: o mesmo do capture (frontmatter type: capture, created, context quando dado + o texto).
        Saída texto: "<caminho>\\n\\n<conteúdo>"; --json: {"path": "<caminho>", "content": "<conteúdo>"}.
        TEXTO vazio -> exit 2; contexto inválido com configuração -> exit 2. Em nenhum caso algo é escrito.

    capture_note(text: str, context=None, clock=None) -> str
        Pura (sem I/O): o conteúdo da nota de captura que o `capture` grava e o `capture --print` mostra, com
        created = clock().isoformat(timespec="seconds") (clock: callable sem argumentos que devolve datetime;
        None = datetime.now). O `capture` e o `capture --print` usam esta função e o capture_name da SPEC-0021.
"""
import datetime as dt
import json
import re
import unittest

from brain_support import fn, output, snapshot
from test_cli import CliTestCase
from test_inbox_cli import InboxCliTestCase, month

SPEC = "SPEC-0044"
FIXED = dt.datetime(2026, 10, 30, 14, 5, 9)
COLLEGE = ("--context", "college=projects/college:College")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}-\d{6}")
CREATED = re.compile(r"(?m)^created: .*$")
PRINT_NAME = r"(\d{4}-\d{2}-\d{2})-\d{6}-ideia-rapida\.md"


def normalize(text):
    """Tira o relógio (carimbo do nome e valor de created) para comparar duas execuções da CLI."""
    return CREATED.sub("created: <T>", STAMP.sub("<STAMP>", text))


class PrintCliTestCase(InboxCliTestCase):
    def print_json(self, *args, cwd=None):
        out = self.box.run("capture", *args, "--print", "--json", cwd=cwd)
        self.assertExit(out, 0)
        try:
            data = json.loads(out.stdout)
        except ValueError:
            self.fail(f"saída não é JSON: {output(out)}")
        self.assertIsInstance(data, dict, data)
        self.assertEqual(set(data), {"path", "content"}, data)
        return data


class CaptureNoteTest(unittest.TestCase):
    def test_capture_note_is_the_content_capture_writes(self):
        """SPEC-0044:UT-01"""
        capture_note = fn("capture_note", SPEC)
        self.assertEqual(capture_note("Ideia sobre grafos ", context="college", clock=lambda: FIXED),
                         "---\ntype: capture\ncreated: 2026-10-30T14:05:09\ncontext: college\n---\n\n"
                         "Ideia sobre grafos\n")
        self.assertEqual(capture_note("Ideia sobre grafos", clock=lambda: FIXED),
                         "---\ntype: capture\ncreated: 2026-10-30T14:05:09\n---\n\nIdeia sobre grafos\n")
        render = fn("render_capture", "SPEC-0021")
        self.assertEqual(capture_note("Ideia sobre grafos", context="college", clock=lambda: FIXED),
                         render("Ideia sobre grafos", FIXED.isoformat(timespec="seconds"), "college"),
                         "mesmo conteúdo do capture, byte a byte")


class PrintMatchesCaptureTest(PrintCliTestCase):
    def test_print_shows_the_same_path_and_content_that_capture_writes(self):
        """SPEC-0044:UT-01"""
        self.make_vault()
        printed = self.print_json("Ideia sobre grafos", "--context", "college")
        out = self.box.run("capture", "Ideia sobre grafos", "--context", "college")
        self.assertExit(out, 0)
        rel = self.rel([line for line in out.stdout.splitlines() if line.strip()][-1])
        written = (self.box.vault / rel).read_bytes().decode("utf-8")
        self.assertEqual(normalize(printed["path"]), normalize(rel), "mesmo nome do capture")
        self.assertEqual(normalize(printed["content"]), normalize(written), "mesmo conteúdo do capture")
        stamp = STAMP.search(printed["path"]).group(0)
        created = re.search(r"(?m)^created: (.*)$", printed["content"]).group(1)
        self.assertEqual(dt.datetime.strptime(stamp, "%Y-%m-%d-%H%M%S").isoformat(timespec="seconds"), created,
                         "o nome e o created vêm do mesmo instante")


class PrintInboxFolderTest(PrintCliTestCase):
    def test_print_uses_layout_inbox_then_the_inbox_option_then_inbox(self):
        """SPEC-0044:UT-02"""
        self.box.vault.mkdir(parents=True)
        (self.box.vault / "Inbox").mkdir()
        self.assertExit(self.box.init("--adopt", "--map", "inbox=Inbox", *COLLEGE, provider="local"), 0)
        before = snapshot(self.box.root)
        path = self.print_json("Ideia rápida")["path"]
        self.assertRegex(path, rf"^Inbox/{PRINT_NAME}$", "com configuração: layout.inbox")
        self.assertEqual(snapshot(self.box.root), before, "--print não escreve nada (vault, log, configuração)")

        empty = self.box.root / "sem-config"
        cases = ((("--inbox", "entrada"), rf"^entrada/{PRINT_NAME}$"), ((), rf"^inbox/{PRINT_NAME}$"))
        for extra, pattern in cases:
            with self.subTest(extra=extra):
                out = self.box.run("capture", "Ideia rápida", "--print", "--json", *extra, config_home=empty)
                self.assertExit(out, 0)
                self.assertRegex(json.loads(out.stdout)["path"], pattern)
        self.assertFalse(empty.exists(), "sem configuração, nada é gravado")


class PrintWithoutConfigTest(PrintCliTestCase):
    def test_print_without_config_shows_path_and_content_and_writes_nothing(self):
        """SPEC-0044:IT-01"""
        before = snapshot(self.box.root)
        days = {dt.date.today().isoformat()}
        out = self.box.run("capture", "Ideia rápida", "--print")
        data = self.print_json("Ideia rápida")
        days.add(dt.date.today().isoformat())
        self.assertExit(out, 0)
        self.assertEqual(snapshot(self.box.root), before, "nada escrito: nem arquivo, nem configuração")
        self.assertFalse(self.box.config_home.exists(), "configuração local não é criada")

        m = re.match(rf"^inbox/{PRINT_NAME}$", data["path"])
        self.assertTrue(m, f"caminho fora do contrato: {data['path']}")
        self.assertIn(m.group(1), days)
        self.assertRegex(data["content"], r"^---\ntype: capture\ncreated: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\n---\n")
        self.assertTrue(data["content"].endswith("\n\nIdeia rápida\n"), data["content"])

        path, sep, content = out.stdout.partition("\n\n")
        self.assertTrue(sep, f"saída texto sem '<caminho>\\n\\n<conteúdo>': {out.stdout!r}")
        self.assertEqual(normalize(path), normalize(data["path"]))
        self.assertEqual(normalize(content).rstrip("\n"), normalize(data["content"]).rstrip("\n"))

    def test_print_empty_text_exits_2_and_writes_nothing(self):
        """SPEC-0044:IT-01"""
        before = snapshot(self.box.root)
        for text in ("", "   "):
            with self.subTest(text=text):
                self.assertExit(self.box.run("capture", text, "--print"), 2)
        self.assertEqual(snapshot(self.box.root), before)

    def test_print_invalid_context_with_config_exits_2_and_writes_nothing(self):
        """SPEC-0044:IT-01"""
        self.make_vault()
        before = snapshot(self.box.root)
        self.assertExit(self.box.run("capture", "Ideia rápida", "--print", "--context", "nao-existe"), 2)
        self.assertEqual(snapshot(self.box.root), before)


class ConnectorRoundTripTest(PrintCliTestCase):
    def test_file_from_print_written_outside_brain_py_is_a_text_item_and_inbox_done_moves_it(self):
        """SPEC-0044:IT-02"""
        self.make_vault()
        data = self.print_json("Ideia rápida", "--context", "college")
        self.assertRegex(data["path"], rf"^inbox/{PRINT_NAME}$")
        target = self.box.vault / data["path"]
        self.assertFalse(target.exists(), "--print não cria o arquivo")
        target.write_text(data["content"], encoding="utf-8")  # o conector cria o arquivo novo na inbox

        items = self.inbox_items()
        self.assertEqual([(self.rel(i["path"]), i["kind"]) for i in items], [(data["path"], "text")])
        self.assertIn("Ideia rápida", items[0]["preview"] or "", items[0])

        out = self.run_in_vault("inbox", "done", data["path"], "--note", "projects/college/ideia-rapida")
        self.assertExit(out, 0)
        self.assertFalse(target.exists(), "o item saiu da inbox")
        name = target.name
        moved = self.processed(name)
        self.assertTrue(moved.startswith(f"raw/processed/{month()}/"))
        self.assertEqual(self.read(moved), data["content"])
        self.assertEqual(self.inbox_items(), [])


class CaptureWithoutPrintUnchangedTest(CliTestCase):
    def test_capture_without_print_still_requires_config(self):
        """SPEC-0044:IT-01"""
        out = self.box.run("capture", "Ideia rápida")
        self.assertExit(out, 3)


if __name__ == "__main__":
    unittest.main()
