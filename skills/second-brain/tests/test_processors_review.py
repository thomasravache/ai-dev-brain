"""Regressões da revisão (CHANGES_REQUESTED) da SPEC-0022: processadores de vídeo e documento.

Decisões do Architect que estes testes fixam (os IDs do plano entre parênteses):

1. (major, IT-04) No timeout, o grupo de processos inteiro do processador é encerrado, não só o filho direto: um
   neto que o processador lançou (ex.: o ffmpeg que o Whisper chama) também morre, no `ingest` e no `process`.
   Só POSIX (no Windows o teste é pulado).
2. (minor, IT-05) `process --out ARQ` nunca sobrescreve: ARQ que já existe -> exit 2 com "já existe" e o arquivo
   fica igual; ARQ dentro do vault -> exit 2 e nada é gravado.
3. (minor, UT-05) references/processors.md: a seção do pdf diz que a página de manual foi lida em
   manpages.debian.org (cópia da página do upstream), com a versão e a data, "não executado nesta máquina"; a seção
   do Whisper diz que o ffmpeg é pré-requisito.
"""
import os
import re
import shlex
import time
import unittest

from brain_support import output, snapshot
from test_processors_cli import EXTRACTED, FAILED, PY, ProcessorsCliTestCase
from test_processors_instructions import DATE, PROCESSORS_MD, VERSION, sections

# O processador lança um neto (outro python) que grava "started" na hora e "done" depois de 3 s, espera o neto
# começar e dorme bem além do timeout. Encerrado só o filho, o neto órfão grava "done".
FAKE_GRANDPARENT = """import subprocess
import sys
import time
from pathlib import Path
started, done = Path(sys.argv[1]), Path(sys.argv[2])
child = (
    "import sys, time\\n"
    "from pathlib import Path\\n"
    "Path(sys.argv[1]).write_text('começou', encoding='utf-8')\\n"
    "time.sleep(3)\\n"
    "Path(sys.argv[2]).write_text('neto sobreviveu', encoding='utf-8')\\n"
)
subprocess.Popen([sys.executable, "-c", child, str(started), str(done)],
                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
deadline = time.monotonic() + 10
while not started.exists() and time.monotonic() < deadline:
    time.sleep(0.02)
time.sleep(30)
"""
GRANDCHILD_WAIT = 4.5  # segundos depois do retorno; vivo, o neto grava "done" ~3 s depois de começar


@unittest.skipIf(os.name == "nt", "grupo de processos: só POSIX")
class TimeoutKillsProcessGroupTest(ProcessorsCliTestCase):
    def setUp(self):
        super().setUp()
        self.started = self.marker("neto-comecou")
        self.done = self.marker("neto-terminou")
        command = (f"{PY} {self.fake('grandparent.py', FAKE_GRANDPARENT)} "
                   f"{shlex.quote(str(self.started))} {shlex.quote(str(self.done))} {{input}} {{output}}")
        self.set_processors({"audio": {"command": command, "timeout": 1}})

    def assertGrandchildKilled(self):
        time.sleep(GRANDCHILD_WAIT)
        if not self.started.exists():
            self.skipTest("o neto não chegou a começar antes do timeout (máquina carregada); teste inconclusivo")
        self.assertFalse(self.done.exists(), "timeout: o neto do processador não foi encerrado (grupo de processos)")

    def test_ingest_timeout_kills_the_grandchild(self):
        """SPEC-0022:IT-04 — decisão 1"""
        _, _, text = self.ingest(self.source("nota.m4a", b"\x00audio"), "--context", "college")
        self.assertRegex(self.extracted(text), FAILED, text)
        self.assertGrandchildKilled()

    def test_process_timeout_kills_the_grandchild(self):
        """SPEC-0022:IT-04 — decisão 1"""
        out = self.box.run("process", self.source("nota.m4a", b"\x00audio"))
        self.assertExit(out, 1)
        self.assertIn("processador audio falhou: ", output(out))
        self.assertGrandchildKilled()


class ProcessOutNeverOverwritesTest(ProcessorsCliTestCase):
    def setUp(self):
        super().setUp()
        self.set_processors({"pdf": {"command": self.text_command()}})
        self.pdf = self.source("slides.pdf", b"%PDF-1.4 slides")

    def test_existing_out_file_exits_2_and_is_left_unchanged(self):
        """SPEC-0022:IT-05 — decisão 2"""
        target = self.box.root / "existente.txt"
        target.write_text("conteúdo antigo\n", encoding="utf-8")
        before = target.stat().st_mtime_ns
        out = self.box.run("process", self.pdf, "--out", target)
        self.assertExit(out, 2)
        self.assertIn("já existe", output(out))
        self.assertEqual(target.read_text(encoding="utf-8"), "conteúdo antigo\n")
        self.assertEqual(target.stat().st_mtime_ns, before)
        self.assertNotIn(EXTRACTED, output(out))

    def test_out_inside_the_vault_exits_2_and_writes_nothing(self):
        """SPEC-0022:IT-05 — decisão 2"""
        for rel in ("t.txt", "raw/t.txt"):
            with self.subTest(rel):
                before = snapshot(self.box.vault)
                target = self.box.vault / rel
                out = self.box.run("process", self.pdf, "--out", target)
                self.assertExit(out, 2)
                self.assertFalse(target.exists(), f"--out dentro do vault gravou {rel}")
                self.assertEqual(snapshot(self.box.vault), before, "o vault mudou")


NOT_RUN = re.compile(r"n[ãa]o executad[oa] nesta m[áa]quina|not (?:run|executed) on this machine", re.IGNORECASE)


class ProcessorsGuideReviewTest(unittest.TestCase):
    def setUp(self):
        if not PROCESSORS_MD.is_file():
            self.fail(f"{PROCESSORS_MD} não existe (SPEC-0022)")
        self.found = sections(PROCESSORS_MD.read_text(encoding="utf-8"))

    def section(self, title, tool):
        matching = [body for t, body in self.found
                    if re.search(title, t, re.IGNORECASE) and re.search(tool, body, re.IGNORECASE)]
        self.assertTrue(matching, f"sem seção {title} ({tool}) em processors.md")
        return matching[0]

    def test_pdf_section_cites_manpages_debian_with_version_date_and_not_run(self):
        """SPEC-0022:UT-05 — decisão 3"""
        body = self.section(r"\bpdf|pdftotext", r"pdftotext")
        self.assertIn("manpages.debian.org", body, "pdf: a página de manual veio de manpages.debian.org")
        self.assertRegex(body, VERSION, "pdf: sem a versão")
        self.assertRegex(body, DATE, "pdf: sem a data (AAAA-MM-DD)")
        self.assertRegex(body, NOT_RUN, "pdf: falta 'não executado nesta máquina'")

    def test_whisper_section_states_the_ffmpeg_prerequisite(self):
        """SPEC-0022:UT-05 — decisão 3"""
        body = self.section(r"v[íi]deo|[áa]udio|whisper", r"whisper")
        self.assertRegex(body, r"(?i)\bffmpeg\b", "Whisper: falta o pré-requisito ffmpeg")


if __name__ == "__main__":
    unittest.main()
