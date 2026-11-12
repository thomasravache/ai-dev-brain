"""Regressões da revisão G4 da SPEC-0024 (exportação para o NotebookLM; SPEC-0027: UT-03 e IT-02).

O que estes testes fixam (seção 3 da spec; o formato do pacote da SPEC-0024 não muda):

    flatten_links(text)        não mexe em código: `[[x]]` inline e [[x]] dentro de cercas (``` ou ~~~) ficam como
                               estão; o resto continua virando texto simples.
    export_name(title, path, taken)
                               nomes comparados com unicodedata.normalize("NFC", …).casefold(): "Séries" em NFC e em
                               NFD (e "Straße" e "STRASSE") geram nomes diferentes, como o APFS os compara.
    export-notebooklm MOC --out PASTA
        falha no meio da escrita: nada fica em --out (a escrita vai para uma pasta temporária ao lado e é movida
        no final), e uma nova tentativa na mesma PASTA funciona;
        MOC = index, log, index.md ou log.md: exit 2, nada é escrito;
        todo MOC de layout.mocs é bloqueado como caminho: a nota alcançada só pelo MOC de outro contexto fica fora.

Falha simulada (IT-02): o comando roda num subprocesso (`python -c WRAPPER`, com HOME e BRAIN_CONFIG_HOME isolados)
que substitui builtins.open, io.open e os.open antes de executar scripts/brain.py com runpy. Toda abertura para
escrita de um arquivo sob a raiz do sandbox (fora do vault e da configuração local) é contada, e a terceira levanta
OSError(ENOSPC). Isso não depende de como o comando grava (open, Path.write_text, tempfile ou os.open) nem de onde
fica a pasta temporária; mover com os.replace/rename não abre arquivo e não é contado. pathlib, shutil e tempfile
são importados antes da troca (o pathlib guarda os.open como atributo de classe).
"""
import os
import subprocess
import sys
import unicodedata
import unittest

from brain_support import SCRIPT, fn, output, snapshot
from test_store_cli import StoreCliTestCase, note_text

SPEC = "SPEC-0027"
CONTEXTS = ("--context", "college=projects/college:College", "--context", "work=areas/work:Work")
OS_METADATA = (".DS_Store", "Thumbs.db", "desktop.ini")
WRAPPER = r"""
import builtins, errno, io, os, pathlib, runpy, shutil, sys, tempfile  # imported before the patch: pathlib keeps
# the real os.open as a class attribute (a Python function there would become a bound method)
root, fail_at, script = os.path.realpath(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
skip = tuple(os.path.realpath(p) + os.sep for p in sys.argv[4:6])
count = [0]
def hit(path):
    full = os.path.realpath(os.fsdecode(path))
    if not full.startswith(root + os.sep) or full.startswith(skip):
        return
    count[0] += 1
    if count[0] == fail_at:
        raise OSError(errno.ENOSPC, "falha simulada na escrita", full)
real_open, real_os_open = builtins.open, os.open
def fake_open(file, mode="r", *args, **kwargs):
    if isinstance(file, (str, bytes, os.PathLike)) and any(c in mode for c in "wxa+"):
        hit(file)
    return real_open(file, mode, *args, **kwargs)
def fake_os_open(path, flags, *args, **kwargs):
    if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
        hit(path)
    return real_os_open(path, flags, *args, **kwargs)
builtins.open = io.open = fake_open
os.open = fake_os_open
sys.argv = [script] + sys.argv[6:]
runpy.run_path(script, run_name="__main__")
"""


def key(name):
    return unicodedata.normalize("NFC", name).casefold()


class FlattenLinksReviewTest(unittest.TestCase):
    def test_flatten_links_keeps_code_untouched(self):
        """SPEC-0027:UT-03"""
        flatten_links = fn("flatten_links", "SPEC-0024")
        self.assertEqual(flatten_links("`[[codigo]]` e [[Nota]]"), "`[[codigo]]` e Nota")
        text = "Antes [[A|a]].\n\n```md\nVeja [[x]] e ![[img.png]].\n```\n\n~~~\n[[y]]\n~~~\n\nDepois [[B]].\n"
        self.assertEqual(flatten_links(text),
                         "Antes a.\n\n```md\nVeja [[x]] e ![[img.png]].\n```\n\n~~~\n[[y]]\n~~~\n\nDepois B.\n")


class ExportNameReviewTest(unittest.TestCase):
    def test_names_that_differ_only_in_unicode_form_or_case_folding_do_not_collide(self):
        """SPEC-0027:UT-03"""
        export_name = fn("export_name", "SPEC-0024")
        for first, second in ((unicodedata.normalize("NFC", "Séries"), unicodedata.normalize("NFD", "Séries")),
                              ("Straße", "STRASSE")):
            with self.subTest(first=ascii(first), second=ascii(second)):
                taken = {"sources.md", "combined.md"}
                a = export_name(first, "a/x.md", taken)
                b = export_name(second, "b/y.md", taken)
                self.assertNotEqual(key(a), key(b), f"{a!a} e {b!a} são o mesmo arquivo no APFS")


class ExportReviewCliTest(StoreCliTestCase):
    def build_vault(self):
        """MOC college cita Integrais e Taylor; Integrais liga a Regra e ao MOC work, que cita Deploy."""
        self.make_vault(CONTEXTS)
        self.write("projects/college/Integrais.md",
                   note_text("Integrais", "lecture", "college", body="Ver [[Regra]] e [[work]]."))
        self.write("projects/college/Taylor.md", note_text("Taylor", "lecture", "college", body="Polinômios."))
        self.write("resources/Regra.md", note_text("Regra", body="Regra do produto."))
        self.write("areas/work/Deploy.md", note_text("Deploy", context="work", body="Deploy no cluster."))
        self.write("mocs/college.md", "---\ntype: moc\ntitle: College\ncontext: college\ncreated: 2026-01-01\n---\n"
                                      "# College\n\n- [[Integrais]]\n- [[Taylor]]\n")
        self.write("mocs/work.md", "---\ntype: moc\ntitle: Work\ncontext: work\ncreated: 2026-01-01\n---\n"
                                   "# Work\n\n- [[Deploy]]\n")

    def run_failing(self, *args, fail_at=3):
        env = dict(os.environ, HOME=str(self.box.home), BRAIN_CONFIG_HOME=str(self.box.config_home))
        argv = [sys.executable, "-c", WRAPPER, self.box.root, fail_at, SCRIPT, self.box.vault, self.box.config_home,
                *args]
        return subprocess.run([str(a) for a in argv], check=False, cwd=self.box.root, capture_output=True, text=True,
                              env=env, timeout=60)

    def entries(self, folder):
        return sorted(p.name for p in folder.iterdir() if p.name not in OS_METADATA) if folder.exists() else []

    def test_a_failure_while_writing_leaves_out_empty_and_a_retry_works(self):
        """SPEC-0027:IT-02"""
        self.build_vault()
        before = snapshot(self.box.vault)
        for existing in (True, False):
            with self.subTest(out_exists=existing):
                out = self.box.root / f"notebooklm-{existing}"
                if existing:
                    out.mkdir()
                failed = self.run_failing("export-notebooklm", "college", "--out", out, "--combined")
                self.assertNotEqual(failed.returncode, 0, output(failed))
                self.assertNotIn("Traceback", output(failed))
                self.assertIn("falha simulada", output(failed), "a falha simulada aconteceu na escrita")
                self.assertEqual(self.entries(out), [], "falha no meio: nada fica em --out")

                again = self.box.run("export-notebooklm", "college", "--out", out, "--combined")
                self.assertExit(again, 0)
                self.assertIn("sources.md", self.entries(out), "a nova tentativa na mesma pasta funciona")
        self.assertEqual(snapshot(self.box.vault), before, "o vault não muda")

    def test_index_and_log_are_refused_as_moc(self):
        """SPEC-0027:IT-02"""
        self.build_vault()
        before = snapshot(self.box.vault)
        for ref in ("index", "log", "index.md", "log.md"):
            with self.subTest(moc=ref):
                out = self.box.root / f"export-{ref}"
                result = self.box.run("export-notebooklm", ref, "--out", out)
                self.assertExit(result, 2)
                self.assertEqual(self.entries(out), [], "nada é escrito")
        self.assertEqual(snapshot(self.box.vault), before)

    def test_the_moc_of_another_context_is_never_walked_through(self):
        """SPEC-0027:IT-02"""
        self.build_vault()
        out = self.box.root / "notebooklm"
        data = self.json_of("export-notebooklm", "college", "--out", out, "--hops", "2")
        paths = [item["path"] for item in data["notes"]]
        for path in ("mocs/college.md", "projects/college/Integrais.md", "projects/college/Taylor.md",
                     "resources/Regra.md"):
            self.assertIn(path, paths)
        self.assertNotIn("areas/work/Deploy.md", paths, "Deploy só é alcançada pelo MOC work")
        sources = (out / "sources.md").read_text(encoding="utf-8")
        self.assertNotIn("areas/work/Deploy.md", sources)


if __name__ == "__main__":
    unittest.main()
