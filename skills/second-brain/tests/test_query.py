"""Pacote de contexto do fluxo de consultar: expansão por links, ordem e corte por tamanho (SPEC-0020: UT-01, UT-02).

Contrato esperado da função pura de scripts/brain.py (o Implementer segue estes testes; seção 4 e 6 da spec).
A spec escreve build_context(query, filtros, hops, limit, max_chars); a assinatura fixada aqui segue a de
search(notes, query, context=None, ...) da SPEC-0018, recebendo as notas já lidas (sem I/O):

    build_context(notes: list, query: str, context=None, hops=1, limit=8, max_chars=40000, values=None) -> dict
        notes   : list[Note] de scan_vault/parse_note (SPEC-0018).
        context : nome do contexto; filtra a busca (search(..., context=context)) e põe o MOC do contexto primeiro.
        values  : load_config()["values"] — usado só para achar o MOC (<layout.mocs>/<context>.md); None = layout
                  padrão ("mocs"). Os testes unitários não usam context nem values.
        1. search(notes, query, context=context, limit=limit) — os resultados entram com reason "search:<pontos>".
        2. com context, o MOC entra primeiro, com reason "moc".
        3. vizinhos em largura (links de saída resolvidos por resolve_link e backlinks) até `hops` passos a partir
           das notas da busca, com reason "link:<distância>"; nenhuma nota se repete (vale a menor distância).
        4. ordem: MOC, resultados da busca pela pontuação, vizinhos pela distância e depois pelo título.
        5. as notas entram inteiras (content = texto da nota) enquanto a soma de len(content) couber em max_chars;
           as demais vão para "omitted" só com path, title e reason.
        Devolve {"query": query, "notes": [{"path", "title", "reason", "content"}],
                 "omitted": [{"path", "title", "reason"}], "broken": [...]}.
        "broken" lista os alvos de links que não resolvem, encontrados durante a expansão (forma do item livre:
        o alvo como string ou um dict que o contenha); link quebrado nunca levanta exceção.
        hops fora de 0..2 é validado pela CLI (exit 2, IT-02 em test_query_cli).
"""
import re
import unittest

from brain_support import fn

SPEC = "SPEC-0020"
REASON_SEARCH = re.compile(r"^search:\d+(?:[.,]\d+)?$")

# A (resultado da busca) -> B -> C; D -> A; A -> nota inexistente. Só A tem o termo "zebra".
GRAPH = {
    "A.md": "# A\n\nA zebra listrada mora na savana. Ver [[B]] e [[Fantasma]].\n",
    "B.md": "# B\n\nCavalos e pôneis. Ver [[C]].\n",
    "C.md": "# C\n\nBurros e mulas de carga.\n",
    "D.md": "# D\n\nSavana africana, ver [[A]].\n",
    "E.md": "# E\n\nNota solta sobre jardinagem, sem links.\n",
}


def parse(path, text):
    return fn("parse_note", "SPEC-0018")(path, text, None)


def build(notes, query, **kwargs):
    return fn("build_context", SPEC)(notes, query, **kwargs)


def paths_of(items):
    return [item["path"] for item in items]


def padded(head, size=1000):
    """Texto de exatamente `size` caracteres que começa por head."""
    filler = " palavra"
    text = head
    while len(text) < size - 1:
        text += filler
    return text[:size - 1] + "\n"


class BuildContextExpansionTest(unittest.TestCase):
    def notes(self):
        return [parse(path, text) for path, text in GRAPH.items()]

    def test_neighbors_up_to_hops_without_repeats_and_broken_links(self):
        """SPEC-0020:UT-01"""
        notes = self.notes()

        one = build(notes, "zebra", hops=1)
        self.assertTrue({"query", "notes", "omitted", "broken"} <= set(one), one)
        self.assertEqual(one["query"], "zebra")
        self.assertEqual(paths_of(one["notes"]), ["A.md", "B.md", "D.md"], one["notes"])
        reasons = {item["path"]: item["reason"] for item in one["notes"]}
        self.assertRegex(reasons["A.md"], REASON_SEARCH)
        self.assertEqual(reasons["B.md"], "link:1", "link de saída de A")
        self.assertEqual(reasons["D.md"], "link:1", "backlink de A")
        for item in one["notes"]:
            with self.subTest(path=item["path"]):
                self.assertTrue({"path", "title", "reason", "content"} <= set(item), item)
                self.assertIn(GRAPH[item["path"]].strip().splitlines()[-1], item["content"], "nota inteira")
        self.assertEqual(one["notes"][0]["title"], "A")
        self.assertEqual(one["omitted"], [])
        self.assertTrue(any("Fantasma" in str(item) for item in one["broken"]), one["broken"])

        two = build(notes, "zebra", hops=2)
        found = paths_of(two["notes"])
        self.assertEqual(found, ["A.md", "B.md", "D.md", "C.md"], two["notes"])
        self.assertEqual(len(found), len(set(found)), "nenhuma nota se repete")
        self.assertEqual(two["notes"][-1]["reason"], "link:2")
        self.assertNotIn("E.md", found, "nota sem link com o resultado não entra")
        self.assertTrue(any("Fantasma" in str(item) for item in two["broken"]), two["broken"])
        self.assertFalse(any(str(item) in ("B", "C", "D") for item in two["broken"]), "links resolvidos não são quebrados")

        zero = build(notes, "zebra", hops=0)
        self.assertEqual(paths_of(zero["notes"]), ["A.md"], "hops=0: só a busca")

    def test_default_hops_is_one(self):
        """SPEC-0020:UT-01"""
        self.assertEqual(paths_of(build(self.notes(), "zebra")["notes"]), ["A.md", "B.md", "D.md"])


class BuildContextSizeLimitTest(unittest.TestCase):
    def test_notes_that_do_not_fit_max_chars_go_to_omitted(self):
        """SPEC-0020:UT-02"""
        texts = {
            "N1.md": padded("# Zebra alfa\n\nzebra no título e no corpo."),
            "N2.md": padded("# Beta\n\nzebra zebra zebra no corpo."),
            "N3.md": padded("# Gama\n\numa zebra só."),
        }
        for path, text in texts.items():
            self.assertEqual(len(text), 1000, path)
        notes = [parse(path, text) for path, text in texts.items()]

        data = build(notes, "zebra", hops=0, max_chars=2500)
        self.assertEqual(paths_of(data["notes"]), ["N1.md", "N2.md"], data["notes"])
        self.assertLessEqual(sum(len(item["content"]) for item in data["notes"]), 2500)
        for item in data["notes"]:
            self.assertGreaterEqual(len(item["content"]), 990, "nota entra inteira, não cortada")
        self.assertEqual(len(data["omitted"]), 1, data["omitted"])
        omitted = data["omitted"][0]
        self.assertEqual(omitted["path"], "N3.md")
        self.assertEqual(omitted["title"], "Gama")
        self.assertRegex(omitted["reason"], REASON_SEARCH)
        self.assertNotIn("content", omitted, "omitida vai só com título, caminho e motivo")

        everything = build(notes, "zebra", hops=0)
        self.assertEqual(paths_of(everything["notes"]), ["N1.md", "N2.md", "N3.md"], "padrão 40.000 cabe tudo")
        self.assertEqual(everything["omitted"], [])


if __name__ == "__main__":
    unittest.main()
