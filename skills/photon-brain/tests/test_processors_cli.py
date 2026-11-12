"""Integração pela CLI: processadores no ingest, comando process e doctor (SPEC-0022: IT-01 a IT-06).

Cada teste cria o vault com o `brain.py init` real (contexto college) num diretório temporário com HOME e
BRAIN_CONFIG_HOME isolados (brain_support.Sandbox) e grava `processors` no <vault>/brain-config.yml. Os
processadores são scripts Python escritos pelo teste e chamados com sys.executable: nada precisa de yt-dlp,
Whisper ou pdftotext. Um processador que não deve rodar cria um arquivo-marcador quando roda.

Saídas que os testes conferem (contrato da seção 6; avisos e erros podem ir para stdout ou stderr):
    brain-config.yml   processors.<kind>: {command, output (vtt|srt|txt), timeout (s), check}
    ingest FONTE [--context C] [--no-process] [--timestamps] [--text-file ARQ]
        kind detectado (youtube, video, audio, pdf) com processador e sem --no-process: o texto do processador
        sob "## Extracted text" da nota de fonte (raw/AAAA-MM-DD-<slug>.md) e a linha "ingest" no log.md.
        output vtt/srt: o maior arquivo da extensão em {output_dir}, convertido para texto; com --timestamps,
        linhas "[mm:ss](<url com ?t= ou &t=<s>s>) texto" no youtube.
        sem processador: nota com _(pending)_ (SPEC-0019) e aviso "sem processador para <kind>".
        --no-process ou --text-file: o processador não roda.
        falha (exit != 0, executável ausente, timeout): exit 0, "_(extraction failed: <motivo>)_" na nota e
        aviso com o stderr resumido (até 500 caracteres); no timeout o processo é encerrado.
    process ENTRADA [--kind K] [--out ARQ] [--timestamps]
        exit 0 com o texto no stdout ou em --out; sem processador: exit 2 "nenhum processador para <kind>";
        falha: exit 1 "processador <kind> falhou: <motivo>".
    doctor   "OK|AVISO processor <kind> — <executável> (<primeira linha da checagem>)"; a checagem é `check` ou
             "<executável> --version"; executável ausente = AVISO.
"""
import re
import shlex
import sys
import time
import unittest
from pathlib import Path

from brain_support import doctor_lines, fn, output
from test_store_cli import StoreCliTestCase, today

PY = shlex.quote(sys.executable)
EXTRACTED = "texto extraído do PDF"
STDERR_TOKEN = "boom-stderr-0022"
MISSING = "sb-missing-tool-0022"
FAILED = re.compile(r"_\(extraction failed: [^\n]+\)_")

FAKE_TEXT = """import sys
from pathlib import Path
Path(sys.argv[2]).write_text("texto extraído do PDF\\n", encoding="utf-8")
if len(sys.argv) > 3:
    Path(sys.argv[3]).write_text("rodou", encoding="utf-8")
"""
SMALL_VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nerrado\n"
BIG_VTT = """WEBVTT
Kind: captions
Language: pt

00:00:01.000 --> 00:00:04.000 align:start position:0%
Olá<00:00:01.500><c> turma</c>

00:00:04.010 --> 00:00:08.000 align:start position:0%
Olá turma
hoje<00:00:05.000><c> limites</c>

00:01:05.000 --> 00:01:09.000
hoje limites
derivadas no fim
"""
FAKE_VTT = f"""import sys
from pathlib import Path
out = Path(sys.argv[2])
(out / "abc.small.vtt").write_text({SMALL_VTT!r}, encoding="utf-8")
(out / "abc.pt.vtt").write_text({BIG_VTT!r}, encoding="utf-8")
"""
FAKE_FAIL = f"""import sys
sys.stderr.write({STDERR_TOKEN!r} + ": " + "E" * 2000 + "\\n")
sys.exit(3)
"""
FAKE_SLEEP = """import sys
import time
from pathlib import Path
time.sleep(5)
Path(sys.argv[1]).write_text("não foi encerrado", encoding="utf-8")
Path(sys.argv[2]).write_text("tarde demais", encoding="utf-8")
"""
FAKE_CHECK = 'print("fake-tool 9.9.9")\nprint("segunda linha")\n'


class ProcessorsCliTestCase(StoreCliTestCase):
    def setUp(self):
        super().setUp()
        self.make_vault()
        self.fakes = self.box.root / "fakes"
        self.fakes.mkdir()

    def fake(self, name, code):
        path = self.fakes / name
        path.write_text(code, encoding="utf-8")
        return shlex.quote(str(path))

    def marker(self, name):
        return self.box.root / "markers" / name

    def set_processors(self, processors):
        parse, dump = fn("parse_yaml"), fn("dump_yaml")
        shared = self.box.vault / "brain-config.yml"
        data = parse(shared.read_text(encoding="utf-8"))
        data["processors"] = processors
        shared.write_text(dump(data), encoding="utf-8")
        self.marker("x").parent.mkdir(exist_ok=True)

    def text_command(self, marker=None):
        extra = f" {shlex.quote(str(marker))}" if marker else ""
        return f"{PY} {self.fake('text.py', FAKE_TEXT)} {{input}} {{output}}{extra}"

    def ingest(self, *args):
        """Roda ingest e devolve (resultado, caminho da nota de fonte nova, texto dela)."""
        before = set(self.raw_files())
        out = self.box.run("ingest", *args)
        self.assertExit(out, 0)
        new = sorted(set(self.raw_files()) - before)
        self.assertEqual(len(new), 1, f"esperava uma nota de fonte nova: {new}\n{output(out)}")
        rel = f"raw/{new[0]}"
        self.assertRegex(rel, rf"^raw/{today()}-[^/]+\.md$")
        return out, rel, self.read(rel)

    def extracted(self, text):
        m = re.search(r"^## Extracted text\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        self.assertTrue(m, f"sem '## Extracted text':\n{text}")
        return m.group(1).strip()


class IngestWithProcessorTest(ProcessorsCliTestCase):
    def test_pdf_text_goes_under_extracted_text_and_is_logged(self):
        """SPEC-0022:IT-01"""
        self.set_processors({"pdf": {"command": self.text_command()}})
        pdf = self.source("slides.pdf", b"%PDF-1.4 slides")
        log_before = self.log()
        _, rel, text = self.ingest(pdf, "--context", "college")
        self.assertEqual(self.extracted(text), EXTRACTED, text)
        self.assertNotIn("_(pending)_", text)
        lines = self.new_log_lines(log_before)
        self.assertTrue(any(re.match(rf"^- {today()} \d{{2}}:\d{{2}} ingest {re.escape(rel)}\b", line)
                            for line in lines), lines)


class YoutubeTimestampsTest(ProcessorsCliTestCase):
    def setUp(self):
        super().setUp()
        command = f"{PY} {self.fake('vtt.py', FAKE_VTT)} {{input}} {{output_dir}}"
        self.set_processors({"youtube": {"command": command, "output": "vtt"}})

    def test_timestamps_link_each_line_to_the_moment_from_the_largest_vtt(self):
        """SPEC-0022:IT-02"""
        url = "https://youtu.be/abc"
        _, _, text = self.ingest(url, "--timestamps", "--context", "college")
        self.assertEqual(self.extracted(text).splitlines(), [
            f"[00:01]({url}?t=1s) Olá turma",
            f"[00:04]({url}?t=4s) hoje limites",
            f"[01:05]({url}?t=65s) derivadas no fim",
        ], text)

    def test_without_timestamps_the_largest_vtt_becomes_plain_text(self):
        """SPEC-0022:IT-02"""
        _, _, text = self.ingest("https://www.youtube.com/watch?v=abc", "--context", "college")
        body = self.extracted(text)
        self.assertEqual(" ".join(body.split()), "Olá turma hoje limites derivadas no fim", text)
        self.assertNotIn("errado", body, "o texto vem do maior .vtt")


class WithoutProcessingTest(ProcessorsCliTestCase):
    def test_no_processor_no_process_and_text_file_do_not_run_the_processor(self):
        """SPEC-0022:IT-03"""
        ran = self.marker("pdf-rodou")
        self.set_processors({"pdf": {"command": self.text_command(ran)}})

        out, _, text = self.ingest(self.source("aula.mp4", b"\x00video"), "--context", "college")
        self.assertIn("sem processador para video", output(out))
        self.assertEqual(self.extracted(text), "_(pending)_", text)

        pdf = self.source("slides.pdf", b"%PDF-1.4 slides")
        _, _, text = self.ingest(pdf, "--no-process", "--context", "college")
        self.assertFalse(ran.exists(), "--no-process: o processador rodou")
        self.assertEqual(self.extracted(text), "_(pending)_", text)

        typed = self.source("t.txt", "texto digitado pela pessoa\n")
        _, _, text = self.ingest(pdf, "--text-file", typed, "--context", "college")
        self.assertFalse(ran.exists(), "--text-file: o processador rodou")
        self.assertEqual(self.extracted(text), "texto digitado pela pessoa", text)

        self.ingest(pdf, "--context", "college")  # controle: sem as flags o mesmo processador roda
        self.assertTrue(ran.exists(), "o processador falso não criou o marcador quando devia rodar")


class ProcessorFailureTest(ProcessorsCliTestCase):
    def setUp(self):
        super().setUp()
        self.late = self.marker("dormiu-ate-o-fim")
        self.set_processors({
            "pdf": {"command": f"{PY} {self.fake('fail.py', FAKE_FAIL)} {{input}} {{output}}"},
            "video": {"command": f"{MISSING} {{input}} {{output}}"},
            "audio": {"command": f"{PY} {self.fake('sleep.py', FAKE_SLEEP)} {shlex.quote(str(self.late))} "
                                 "{output}", "timeout": 1},
        })

    def assertFailedNote(self, text):
        self.assertRegex(self.extracted(text), FAILED, text)

    def test_exit_3_keeps_the_raw_note_with_the_failure_and_a_short_stderr(self):
        """SPEC-0022:IT-04"""
        out, _, text = self.ingest(self.source("slides.pdf", b"%PDF-1.4"), "--context", "college")
        self.assertFailedNote(text)
        self.assertIn(STDERR_TOKEN, output(out), "o aviso traz o stderr do processador")
        self.assertNotIn("E" * 501, output(out), "stderr resumido em até 500 caracteres")
        self.assertNotIn("E" * 501, text)

    def test_missing_executable_keeps_the_raw_note_with_the_failure(self):
        """SPEC-0022:IT-04"""
        _, _, text = self.ingest(self.source("aula.mp4", b"\x00video"), "--context", "college")
        self.assertFailedNote(text)
        self.assertTrue(any((self.box.files / "college").rglob("aula.mp4")), "o bruto fica guardado")

    def test_timeout_kills_the_processor_and_keeps_the_raw_note(self):
        """SPEC-0022:IT-04"""
        start = time.monotonic()
        _, _, text = self.ingest(self.source("nota.m4a", b"\x00audio"), "--context", "college")
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 4.0, f"timeout: 1 não foi respeitado ({elapsed:.1f} s)")
        self.assertFailedNote(text)
        time.sleep(max(0.0, 6.5 - elapsed))  # vivo, o processo escreveria o marcador aos 5 s
        self.assertFalse(self.late.exists(), "o processo do timeout não foi encerrado")


class ProcessCommandTest(ProcessorsCliTestCase):
    def setUp(self):
        super().setUp()
        self.set_processors({
            "pdf": {"command": self.text_command()},
            "audio": {"command": f"{PY} {self.fake('fail.py', FAKE_FAIL)} {{input}} {{output}}"},
        })

    def test_process_exits_0_2_and_1(self):
        """SPEC-0022:IT-05"""
        pdf = self.source("slides.pdf", b"%PDF-1.4 slides")
        target = self.box.root / "t.txt"
        out = self.box.run("process", pdf, "--out", target)
        self.assertExit(out, 0)
        self.assertEqual(target.read_text(encoding="utf-8").strip(), EXTRACTED)

        out = self.box.run("process", pdf)
        self.assertExit(out, 0)
        self.assertEqual(out.stdout.strip(), EXTRACTED)

        out = self.box.run("process", self.source("slides.bin", b"%PDF-1.4"), "--kind", "pdf")
        self.assertExit(out, 0)
        self.assertEqual(out.stdout.strip(), EXTRACTED)

        out = self.box.run("process", self.source("aula.mp4", b"\x00video"))
        self.assertExit(out, 2)
        self.assertIn("nenhum processador para video — veja references/processors.md", output(out))

        out = self.box.run("process", self.source("nota.m4a", b"\x00audio"))
        self.assertExit(out, 1)
        self.assertIn("processador audio falhou: ", output(out))
        self.assertIn(STDERR_TOKEN, output(out))


class DoctorProcessorsTest(ProcessorsCliTestCase):
    def test_doctor_runs_each_check_and_warns_on_missing_executable(self):
        """SPEC-0022:IT-06"""
        self.set_processors({
            "pdf": {"command": self.text_command(), "check": f"{PY} {self.fake('check.py', FAKE_CHECK)}"},
            "audio": {"command": self.text_command()},
            "video": {"command": f"{MISSING} {{input}} {{output}}"},
        })
        out = self.box.run("doctor")
        self.assertExit(out, 0)
        rows = {item: (status, detail) for status, item, detail in doctor_lines(out.stdout)}
        executable = Path(sys.executable).name

        status, detail = rows.get("processor pdf", (None, ""))
        self.assertEqual(status, "OK", out.stdout)
        self.assertIn(executable, detail)
        self.assertTrue(detail.endswith("(fake-tool 9.9.9)"), out.stdout)
        self.assertNotIn("segunda linha", out.stdout)

        status, detail = rows.get("processor audio", (None, ""))
        self.assertEqual(status, "OK", out.stdout)
        self.assertRegex(detail, r"\(Python 3\.\d+[^)]*\)$", "sem check: '<executável> --version'")

        status, detail = rows.get("processor video", (None, ""))
        self.assertEqual(status, "AVISO", out.stdout)
        self.assertIn(MISSING, detail)


if __name__ == "__main__":
    unittest.main()
