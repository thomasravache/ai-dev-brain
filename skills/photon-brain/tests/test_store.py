"""Escrita segura do fluxo de guardar: caminho da nota, criação sem sobrescrever, relações e regiões geradas
(SPEC-0019: UT-01 a UT-04).

Contrato esperado das funções de scripts/brain.py (o Implementer segue estes testes; seção 4 e 6 da spec).
`values` é o load_config()["values"] (chaves "vault", "layout", "para", "contexts", ...). Erros previstos são
`brain.BrainError` (já existe), com `.code` = exit da CLI.

    note_path(title: str, context: str | None, values: dict) -> str
        Caminho da nota nova, relativo ao vault, com "/": "<pasta>/<título sanitizado>.md".
        pasta   : values["contexts"][context]["folder"]; sem contexto (None ou "") -> values["para"]["resources"].
        título  : cada caractere de / \\ : * ? " < > | # ^ [ ] vira espaço, espaços repetidos viram um só e as
                  pontas são aparadas ("Aula 1: Limites/Derivadas" -> "Aula 1 Limites Derivadas").
        Sem I/O. Pasta do contexto absoluta ou que sai do vault com ".." -> BrainError(code 2) com
        "fora do vault" na mensagem; contexto inexistente -> BrainError(code 2) com a lista dos contextos válidos.

    write_new_file(path: Path, text: str)
        Cria `path` (e as pastas que faltarem) com `text`. Arquivo existente -> BrainError(code 2) com a mensagem
        "nota já existe: <path>" e o arquivo não muda (nem conteúdo, nem mtime). Nunca sobrescreve.

    append_relation(text: str, target: str, why: str) -> str
        Pura: devolve o texto da nota com a linha "- [[<target>]] — <why>" no fim da seção "## Relations"
        (antes do próximo cabeçalho "## " ou do fim do arquivo). Sem a seção, ela é criada no fim do texto.
        A mesma linha já presente -> devolve o texto sem mudança. O resto do texto nunca muda.

    replace_region(text: str, name: str, content: str) -> str
        Pura: troca só o que está entre "<!-- brain:begin <name> -->" e "<!-- brain:end <name> -->" por
        `content`; sem a região, ela é acrescentada no fim do texto (com os dois marcadores). Texto fora da
        região (e as outras regiões) nunca muda.

    append_log(vault: Path, layout: dict, command: str, summary: str)   (já existe, SPEC-0017)
        Uma linha no fim do log.md: "- AAAA-MM-DD HH:MM <comando> <caminho> [<detalhe>]" — os comandos de
        escrita passam o caminho escrito (relativo ao vault) no início de `summary`. Coberto pelo IT-05/IT-07.

Os comandos (ingest, new-note, relate, index) escrevem no vault só por write_new_file e pela gravação do texto
devolvido por append_relation/replace_region, sempre com append_log (verificado na CLI, test_store_cli).
"""
import os
import posixpath
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from brain_support import brain, fn

SPEC = "SPEC-0019"
FORBIDDEN = '/\\:*?"<>|#^[]'
VALUES = {
    "vault": "/tmp/vault-de-teste",
    "layout": {"inbox": "inbox", "raw": "raw", "mocs": "mocs", "templates": "templates",
               "index": "index.md", "log": "log.md"},
    "para": {"projects": "projects", "areas": "areas", "resources": "resources", "archive": "archive"},
    "contexts": {
        "college": {"folder": "projects/college", "title": "College"},
        "bad": {"folder": "../fora", "title": "Bad"},
        "deep": {"folder": "projects/../../fora", "title": "Deep"},
        "abs": {"folder": "/etc", "title": "Abs"},
    },
}
BEGIN, END = "<!-- brain:begin notes -->", "<!-- brain:end notes -->"


def note_path(title, context, values=VALUES):
    return fn("note_path", SPEC)(title, context, values)


def append_relation(text, target, why):
    return fn("append_relation", SPEC)(text, target, why)


def replace_region(text, name, content):
    return fn("replace_region", SPEC)(text, name, content)


def blank_lines_collapsed(text):
    return re.sub(r"\n{3,}", "\n\n", text)


class NotePathTest(unittest.TestCase):
    def test_context_folder_sanitized_title_resources_fallback_and_outside_vault(self):
        """SPEC-0019:UT-01"""
        self.assertEqual(note_path("Aula 1: Limites/Derivadas", "college"),
                         "projects/college/Aula 1 Limites Derivadas.md")
        self.assertEqual(note_path("Integrais por partes", None), "resources/Integrais por partes.md")
        self.assertEqual(note_path("Integrais por partes", ""), "resources/Integrais por partes.md")
        for context in ("bad", "deep", "abs"):
            with self.subTest(context=context):
                with self.assertRaises(brain().BrainError) as caught:
                    note_path("Integrais por partes", context)
                self.assertEqual(caught.exception.code, 2)
                self.assertIn("fora do vault", str(caught.exception))

    def test_every_forbidden_character_is_removed_from_the_file_name(self):
        """SPEC-0019:UT-01"""
        title = 'a/b\\c:d*e?f"g<h>i|j#k^l[m]n'
        path = note_path(title, "college")
        self.assertTrue(path.startswith("projects/college/") and path.endswith(".md"), path)
        name = path[len("projects/college/"):-len(".md")]
        self.assertFalse(set(name) & set(FORBIDDEN), name)
        self.assertEqual(name.split(), list("abcdefghijklmn"), name)
        self.assertNotIn("  ", name)

    def test_title_with_dots_never_leaves_the_folder(self):
        """SPEC-0019:UT-01"""
        path = note_path("../../segredo", None)
        normalized = posixpath.normpath(path)
        self.assertTrue(normalized.startswith("resources/"), path)
        self.assertEqual(posixpath.dirname(normalized), "resources", path)

    def test_unknown_context_lists_the_valid_ones(self):
        """SPEC-0019:UT-01"""
        with self.assertRaises(brain().BrainError) as caught:
            note_path("Nota", "inexistente")
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("college", str(caught.exception))


class WriteNewFileTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_existing_file_raises_note_exists_and_is_not_touched(self):
        """SPEC-0019:UT-02"""
        write_new_file = fn("write_new_file", SPEC)
        new = self.root / "projects" / "college" / "Nova.md"
        write_new_file(new, "conteúdo novo\n")
        self.assertEqual(new.read_text(encoding="utf-8"), "conteúdo novo\n")

        existing = self.root / "Existente.md"
        existing.write_text("texto do usuário\n", encoding="utf-8")
        os.utime(existing, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
        before = (existing.read_bytes(), existing.stat().st_mtime_ns)
        with self.assertRaises(brain().BrainError) as caught:
            write_new_file(existing, "outro texto\n")
        self.assertEqual(caught.exception.code, 2)
        self.assertIn(f"nota já existe: {existing}", str(caught.exception))
        self.assertEqual((existing.read_bytes(), existing.stat().st_mtime_ns), before)


class AppendRelationTest(unittest.TestCase):
    def test_section_created_at_the_end_when_missing(self):
        """SPEC-0019:UT-03"""
        original = "---\ntitle: A\n---\n# A\n\n## Summary\n\nresumo da nota A\n"
        result = append_relation(original, "B", "aplica")
        self.assertTrue(result.startswith(original.rstrip("\n")), result)
        self.assertRegex(result[len(original.rstrip("\n")):], r"^\n+## Relations\n+- \[\[B\]\] — aplica\n?$")
        self.assertEqual(append_relation(result, "B", "aplica"), result, "relação repetida não muda nada")

    def test_line_goes_at_the_end_of_the_section_before_the_next_heading(self):
        """SPEC-0019:UT-03"""
        original = ("# A\n\n## Summary\n\nresumo\n\n## Relations\n\n- [[C]] — contradiz\n\n"
                    "## Notes\n\ntexto do usuário depois\n")
        result = append_relation(original, "B", "aplica")
        lines = result.splitlines()
        self.assertEqual(lines.count("- [[B]] — aplica"), 1, result)
        self.assertEqual(lines.count("## Relations"), 1, result)
        self.assertLess(lines.index("- [[C]] — contradiz"), lines.index("- [[B]] — aplica"))
        self.assertLess(lines.index("- [[B]] — aplica"), lines.index("## Notes"))
        self.assertEqual(blank_lines_collapsed(result.replace("- [[B]] — aplica\n", "", 1)), original,
                         "só a linha nova entra; o resto do texto não muda")
        self.assertEqual(append_relation(result, "B", "aplica"), result, "relação repetida não muda nada")

    def test_empty_section_of_the_template_gets_the_line(self):
        """SPEC-0019:UT-03"""
        original = "# A\n\n## Summary\n\n## Relations\n"
        result = append_relation(original, "B", "aplica")
        self.assertEqual(result.count("## Relations"), 1, result)
        self.assertRegex(result, r"^# A\n\n## Summary\n\n## Relations\n+- \[\[B\]\] — aplica\n?$")
        self.assertEqual(append_relation(result, "B", "aplica"), result)


class ReplaceRegionTest(unittest.TestCase):
    def test_only_the_content_between_the_markers_changes(self):
        """SPEC-0019:UT-04"""
        before = "---\ntype: moc\ntitle: College\n---\n# College\n\nTexto do usuário antes.\n\n"
        after = "\n\n## Relations\n\nTexto do usuário depois — com acentuação.\n"
        original = f"{before}{BEGIN}\n- [[Antiga]]\n{END}{after}"
        content = "## lecture\n\n- [[Derivadas]]\n- [[Limites]]"
        result = replace_region(original, "notes", content)
        self.assertEqual(result.split(BEGIN)[0], before)
        self.assertEqual(result.split(END)[1], after)
        middle = result.split(BEGIN)[1].split(END)[0]
        self.assertEqual(middle.strip("\n"), content)
        self.assertNotIn("Antiga", result)
        self.assertEqual(replace_region(result, "notes", content), result, "mesmo conteúdo: texto igual")

    def test_other_regions_are_untouched(self):
        """SPEC-0019:UT-04"""
        original = ("# Index\n\nmeu texto\n\n<!-- brain:begin contexts -->\n- [[mocs/college]] — 3\n"
                    "<!-- brain:end contexts -->\n\n<!-- brain:begin recent -->\n- [[Velha]]\n"
                    "<!-- brain:end recent -->\n\nfim do usuário\n")
        result = replace_region(original, "recent", "- [[Nova]]")
        self.assertIn("<!-- brain:begin contexts -->\n- [[mocs/college]] — 3\n<!-- brain:end contexts -->", result)
        self.assertEqual(result.split("<!-- brain:begin recent -->")[0],
                         original.split("<!-- brain:begin recent -->")[0])
        self.assertEqual(result.split("<!-- brain:end recent -->")[1], "\n\nfim do usuário\n")
        self.assertIn("[[Nova]]", result)
        self.assertNotIn("[[Velha]]", result)

    def test_missing_region_is_appended_at_the_end(self):
        """SPEC-0019:UT-04"""
        original = "# MOC feito à mão\n\nTexto do usuário, sem região.\n"
        content = "- [[Derivadas]]"
        result = replace_region(original, "notes", content)
        self.assertTrue(result.startswith(original), result)
        tail = result[len(original):]
        self.assertEqual(tail.count(BEGIN), 1, tail)
        self.assertEqual(tail.count(END), 1, tail)
        self.assertLess(tail.index(BEGIN), tail.index(content))
        self.assertLess(tail.index(content), tail.index(END))
        self.assertTrue(tail.rstrip().endswith(END), tail)
        again = replace_region(result, "notes", content)
        self.assertEqual(again, result, "com a região já acrescentada, nada mais é acrescentado")


class ReviewRegressionUnitTest(unittest.TestCase):
    """Defeitos reproduzidos na revisão da SPEC-0019 (contrato seção 6 e NFRs seção 5)."""

    def test_replace_region_refuses_unbalanced_or_duplicated_markers(self):
        """SPEC-0019:UT-04"""
        cases = {
            "begin sem end": f"# MOC\n\n{BEGIN}\nTexto do usuário depois do begin órfão.\n",
            "end antes do begin": f"# MOC\n\n{END}\nTexto do usuário no meio.\n{BEGIN}\nMais texto meu.\n",
            "região duplicada": f"# MOC\n\n{BEGIN}\n- [[A]]\n{END}\n\nmeu texto\n\n{BEGIN}\n- [[B]]\n{END}\n",
            "end sem begin": f"# MOC\n\nTexto meu.\n{END}\nMais texto meu.\n",
        }
        for label, text in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(brain().BrainError) as caught:
                    replace_region(text, "notes", "- [[Derivadas]]")
                self.assertIn(caught.exception.code, (1, 2))
                self.assertIn("notes", str(caught.exception), "a mensagem nomeia a região")

    def test_existing_relation_with_alias_is_not_repeated(self):
        """SPEC-0019:UT-03"""
        original = "# A\n\n## Relations\n\n- [[B|Bee]] — aplica\n"
        self.assertEqual(append_relation(original, "B", "aplica"), original, "[[B|Bee]] já é a relação com B")

    def test_crlf_text_keeps_crlf_line_endings(self):
        """SPEC-0019:UT-03"""
        original = "# A\r\n\r\n## Summary\r\n\r\nresumo\r\n\r\n## Relations\r\n\r\n- [[C]] — contradiz\r\n"
        result = append_relation(original, "B", "aplica")
        self.assertIn("- [[B]] — aplica", result)
        self.assertNotRegex(result, r"(?<!\r)\n", "nenhuma linha termina só com LF num arquivo CRLF")
        without = "# A\r\n\r\n## Summary\r\n\r\nresumo\r\n"
        self.assertNotRegex(append_relation(without, "B", "aplica"), r"(?<!\r)\n")

    def test_replace_region_in_crlf_text_keeps_crlf_line_endings(self):
        """SPEC-0019:UT-04"""
        original = f"# MOC\r\n\r\nmeu texto\r\n\r\n{BEGIN}\r\n- [[Antiga]]\r\n{END}\r\n\r\nfim\r\n"
        result = replace_region(original, "notes", "### lecture\n\n- [[Derivadas]]\n- [[Limites]]")
        self.assertIn("[[Limites]]", result)
        self.assertNotRegex(result, r"(?<!\r)\n", "nenhuma linha termina só com LF num arquivo CRLF")
        appended = replace_region("# MOC\r\n\r\nsem região\r\n", "notes", "- [[A]]\n- [[B]]")
        self.assertNotRegex(appended, r"(?<!\r)\n")


if __name__ == "__main__":
    unittest.main()
