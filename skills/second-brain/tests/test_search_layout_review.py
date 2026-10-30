"""Regressões da revisão G4 da SPEC-0026 (ajustes da busca; SPEC-0027: UT-04 e IT-03, parte das referências).

O que estes testes fixam (seção 3 da spec; pesos, formatos JSON e códigos de saída não mudam):

    parse_note(path, text)     uma cerca de fechamento só aceita espaços depois da marca (CommonMark): "```python"
                               dentro de um bloco ``` não fecha o bloco; "```   " fecha.
    related / build_context    index.md e log.md (layout.index e layout.log) comparados com _link_key (caixa e NFC):
                               "Index.md" com layout.index "index.md", e "Diário.md" em NFD com layout.log em NFC,
                               ficam fora de related e nunca são caminho na expansão do context.
    references/search.md       nenhuma linha de texto (fora de tabelas e de blocos de código) passa da quebra do
                               arquivo (WRAP caracteres; as linhas de texto quebram em ~120).
    references/query-flow.md   diz que o `context` não expande pelo `index.md` nem pelo `log.md`.
"""
import re
import unicodedata
import unittest

from brain_support import SKILL, fn

SPEC = "SPEC-0027"
SEARCH_MD = SKILL / "references" / "search.md"
QUERY_FLOW_MD = SKILL / "references" / "query-flow.md"
WRAP = 125
LOG_NFC = unicodedata.normalize("NFC", "Diário.md")
LOG_NFD = unicodedata.normalize("NFD", "Diário.md")
VALUES = {"layout": {"inbox": "inbox", "raw": "raw", "mocs": "mocs", "templates": "templates",
                     "index": "index.md", "log": LOG_NFC}}


def parse(path, text):
    return fn("parse_note", "SPEC-0018")(path, text, None)


def note(title, body):
    return f"---\ntitle: {title}\ntype: note\ncreated: 2026-10-30\n---\n# {title}\n\n{body}\n"


class ClosingFenceTest(unittest.TestCase):
    def test_a_closing_fence_accepts_only_spaces_after_the_mark(self):
        """SPEC-0027:UT-04"""
        parsed = parse("resources/cercas.md", "# Cercas\n\n```\n```python\n#x\n```\n\n#fim\n")
        self.assertNotIn("x", parsed.tags, "\"```python\" não fecha o bloco: #x é código")
        self.assertIn("fim", parsed.tags)
        parsed = parse("resources/til.md", "~~~\n~~~ bash\n#y\n~~~\n#z\n")
        self.assertNotIn("y", parsed.tags)
        self.assertIn("z", parsed.tags)
        parsed = parse("resources/espacos.md", "```\n#a\n```   \n#b\n")
        self.assertNotIn("a", parsed.tags)
        self.assertIn("b", parsed.tags, "cerca seguida só de espaços fecha o bloco")


class LayoutFilesKeyTest(unittest.TestCase):
    def notes(self, texts):
        return [parse(path, text) for path, text in texts.items()]

    def test_related_excludes_index_and_log_regardless_of_case_and_unicode_form(self):
        """SPEC-0027:UT-04"""
        notes = self.notes({
            "Index.md": "# Index\n\n- [[Redes]]\n- [[Banco]]\n\nprotocolo tcp redes roteamento\n",
            LOG_NFD: "# Diário\n\n- 2026-10-30 relate [[Redes]] protocolo tcp redes roteamento\n",
            "resources/Redes.md": note("Redes", "Protocolo TCP e roteamento entre redes. Ver [[Banco]]."),
            "resources/Banco.md": note("Banco", "Replicação de bancos em redes com protocolo tcp."),
        })
        related = fn("related", "SPEC-0018")
        for kwargs in ({"note": "resources/Redes.md"}, {"text": "protocolo tcp redes roteamento"}):
            with self.subTest(**kwargs):
                found = [r["path"] for r in related(notes, values=VALUES, **kwargs)]
                self.assertIn("resources/Banco.md", found)
                self.assertNotIn("Index.md", found, "Index.md é o layout.index (\"index.md\") em outra caixa")
                self.assertNotIn(LOG_NFD, found, "o log em NFD é o layout.log em NFC")

    def test_context_never_walks_through_index_or_log_regardless_of_case_and_unicode_form(self):
        """SPEC-0027:UT-04"""
        notes = self.notes({
            "Index.md": "# Index\n\n- [[Alfa]]\n- [[Bravo]]\n",
            LOG_NFD: "# Diário\n\n- 2026-10-30 relate [[Alfa]] e [[Charlie]]\n",
            "resources/Alfa.md": note("Alfa", "Deploy no kubernetes com a equipe."),
            "resources/Bravo.md": note("Bravo", "Receita de bolo de cenoura."),
            "resources/Charlie.md": note("Charlie", "Roteiro de praia no verão."),
        })
        data = fn("build_context", "SPEC-0020")(notes, "kubernetes", hops=2, values=VALUES)
        reasons = {n["path"]: n["reason"] for n in data["notes"] + data["omitted"]}
        self.assertTrue(reasons.get("resources/Alfa.md", "").startswith("search:"), reasons)
        for path in ("Index.md", LOG_NFD, "resources/Bravo.md", "resources/Charlie.md"):
            self.assertNotIn(path, reasons, f"{path!a} só é alcançada pelo index.md ou pelo log.md")


class ReferencesReviewTest(unittest.TestCase):
    def test_search_md_text_lines_follow_the_file_wrap(self):
        """SPEC-0027:IT-03 — texto de references/search.md"""
        long_lines, fence = [], False
        for number, line in enumerate(SEARCH_MD.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"^\s*(```|~~~)", line):
                fence = not fence
                continue
            if not fence and not line.lstrip().startswith("|") and len(line) > WRAP:
                long_lines.append((number, len(line)))
        self.assertEqual(long_lines, [], f"{SEARCH_MD}: linhas de texto com mais de {WRAP} caracteres")

    def test_query_flow_says_context_does_not_expand_through_index_or_log(self):
        """SPEC-0027:IT-03 — texto de references/query-flow.md"""
        text = QUERY_FLOW_MD.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if "index.md" in line and "log.md" in line]
        self.assertTrue(any(re.search(r"(?i)expan|atravess|caminho|vizinh", line) for line in lines),
                        f"{QUERY_FLOW_MD} deve dizer que o context não expande pelo index.md nem pelo log.md: "
                        f"{lines!r}")


if __name__ == "__main__":
    unittest.main()
