"""Exportação para o NotebookLM: flatten_links e o comando export-notebooklm (SPEC-0024: UT-01 e IT-01).

Interface que os testes esperam (seção 3 da spec):

    brain.flatten_links(text) -> str
        os wikilinks viram texto simples: [[Nota]] -> "Nota", [[Nota|apelido]] -> "apelido"; os embeds de anexo
        viram "(anexo: nome)": ![[grafico.png]] -> "(anexo: grafico.png)". O resto do texto não muda.

    brain.py export-notebooklm MOC --out PASTA [--hops 0..2] [--combined]
        MOC = nome do contexto (ex.: college) ou caminho do MOC no vault (ex.: mocs/college.md).
        Junta o MOC, as notas que ele cita e os vizinhos delas por link até --hops (padrão 1), reusando a expansão
        do `context` (SPEC-0020: o MOC nunca é atravessado, então index.md e o que só o MOC alcança ficam fora).
        Grava em PASTA, fora do vault:
            um .md por nota, com o título da nota no topo (primeira linha não vazia, com ou sem "# ");
            sources.md: a lista das notas exportadas e de onde veio cada uma (o caminho da nota no vault);
            combined.md (só com --combined): todas as notas num único arquivo.
        Nenhum arquivo exportado tem wikilinks ("[[") nem embeds ("![["): passam por flatten_links.
        O vault nunca muda (nem o log.md). PASTA dentro do vault, ou já com arquivos, sai com 2 e nada é escrito:
        o comando nunca sobrescreve.

O IT-01 cria o vault com o `brain.py init` real (SPEC-0017) e as notas com `new-note`, `relate` e `index`
(SPEC-0019), num diretório temporário com HOME e BRAIN_CONFIG_HOME isolados (brain_support.Sandbox). O `created`
das notas é removido antes do `index`, para o index.md ligar só ao MOC (como no IT-01 da SPEC-0020): assim o
pacote tem exatamente o MOC, as duas notas que ele cita e a vizinha.
"""
import re
import unittest

from brain_support import fn, output, snapshot
from test_store_cli import COLLEGE, StoreCliTestCase

MOC = "mocs/college.md"
INTEGRAIS = "projects/college/Integrais por partes.md"
TAYLOR = "projects/college/Séries de Taylor.md"
PRODUCT = "resources/Regra do produto.md"
TITLES = {MOC: "College", INTEGRAIS: "Integrais por partes", TAYLOR: "Séries de Taylor",
          PRODUCT: "Regra do produto"}
INTEGRAIS_BODY = "Integração por partes: veja [[Regra do produto|a regra]] e ![[grafico.png]].\n"
TAYLOR_BODY = "Série de Taylor aproxima uma função por polinômios.\n"
PRODUCT_BODY = "A derivada do produto u v é u' v + u v'.\n"
EXTRA = ("sources.md", "combined.md")


def first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip().lstrip("#").strip()
    return ""


class FlattenLinksTest(unittest.TestCase):
    def test_flatten_links_turns_wikilinks_into_text_and_embeds_into_attachment_marks(self):
        """SPEC-0024:UT-01"""
        flatten_links = fn("flatten_links", "SPEC-0024")
        self.assertEqual(flatten_links("Veja [[Regra do produto]], [[Integrais|integrais]] e ![[grafico.png]]"),
                         "Veja Regra do produto, integrais e (anexo: grafico.png)")


class ExportNotebookLMCliTest(StoreCliTestCase):
    def build_vault(self):
        """MOC college citando Integrais por partes e Séries de Taylor; Integrais ligada a Regra do produto."""
        self.make_vault(COLLEGE)
        for title, note_type, context, body in (
                ("Integrais por partes", "lecture", "college", INTEGRAIS_BODY),
                ("Séries de Taylor", "lecture", "college", TAYLOR_BODY),
                ("Regra do produto", "note", None, PRODUCT_BODY)):
            args = ["new-note", "--type", note_type, "--title", title]
            if context:
                args += ["--context", context]
            rel = self.rel(self.json_of(*args)["path"])
            path = self.box.vault / rel
            text = re.sub(r"(?m)^created:.*\n", "", path.read_text(encoding="utf-8"), count=1)
            path.write_text(text + "\n" + body, encoding="utf-8")
        self.assertExit(self.box.run("relate", "Integrais por partes", "Regra do produto", "--why", "aplica"), 0)
        self.assertExit(self.box.run("index", "--context", "college"), 0)
        moc = self.read(MOC)
        for title in ("Integrais por partes", "Séries de Taylor"):
            self.assertIn(f"[[{title}]]", moc, "o MOC cita as duas notas do contexto")
        self.assertNotIn("Regra do produto", moc, "a vizinha não é citada pelo MOC")
        self.assertNotIn("[[Integrais por partes]]", self.read("index.md"), "index.md liga só ao MOC")

    def export_files(self, out):
        return {p.name: p.read_text(encoding="utf-8") for p in out.iterdir() if p.is_file()}

    def test_export_writes_one_file_per_note_sources_and_combined_without_touching_the_vault(self):
        """SPEC-0024:IT-01"""
        self.build_vault()
        out = self.box.root / "notebooklm"
        out.mkdir()
        before = snapshot(self.box.vault)

        result = self.box.run("export-notebooklm", "college", "--out", out, "--combined")
        self.assertExit(result, 0)
        self.assertEqual(snapshot(self.box.vault), before, "o vault não muda (nem o log.md)")
        self.assertEqual([p.name for p in out.iterdir() if p.is_dir()], [], "só arquivos em --out")

        files = self.export_files(out)
        for name in EXTRA:
            self.assertIn(name, files, f"{name} ausente em --out: {sorted(files)}")
        notes = {name: text for name, text in files.items() if name not in EXTRA}
        self.assertTrue(all(name.endswith(".md") for name in notes), sorted(files))
        self.assertEqual(len(notes), 4, f"um .md por nota (MOC, as duas notas e a vizinha): {sorted(files)}")
        self.assertEqual(sorted(first_line(text) for text in notes.values()), sorted(TITLES.values()),
                         "cada arquivo começa pelo título da nota")

        by_title = {first_line(text): text for text in notes.values()}
        self.assertIn("Integração por partes: veja a regra e (anexo: grafico.png).", by_title["Integrais por partes"])
        self.assertIn(TAYLOR_BODY.strip(), by_title["Séries de Taylor"])
        self.assertIn(PRODUCT_BODY.strip(), by_title["Regra do produto"])
        self.assertIn("Integrais por partes", by_title["College"], "o MOC exportado lista as notas")

        for rel in TITLES:
            self.assertIn(rel, files["sources.md"], "sources.md diz de onde veio cada nota")
        for title in TITLES.values():
            self.assertIn(title, files["combined.md"])
        for body in (TAYLOR_BODY, PRODUCT_BODY):
            self.assertIn(body.strip(), files["combined.md"])
        self.assertIn("(anexo: grafico.png)", files["combined.md"])

        for name, text in files.items():
            with self.subTest(file=name):
                self.assertNotIn("[[", text, "wikilinks viram texto simples")

        exported = snapshot(out)
        again = self.box.run("export-notebooklm", "college", "--out", out, "--combined")
        self.assertEqual(again.returncode, 2, output(again))
        self.assertNotIn("Traceback", output(again))
        self.assertEqual(snapshot(out), exported, "pasta com arquivos: nada é sobrescrito")
        self.assertEqual(snapshot(self.box.vault), before)

        inside = self.box.vault / "export"
        result = self.box.run("export-notebooklm", "college", "--out", inside, "--combined")
        self.assertEqual(result.returncode, 2, output(result))
        self.assertNotIn("Traceback", output(result))
        self.assertFalse(inside.exists(), "--out dentro do vault: nada é criado")
        self.assertEqual(snapshot(self.box.vault), before, "o vault não muda")


if __name__ == "__main__":
    unittest.main()
