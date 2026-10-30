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

Decisões do Architect após a revisão (CHANGES_REQUESTED), fixadas pelos testes de regressão abaixo:
    A. Com context, o MOC do contexto entra primeiro, mas NUNCA é atravessado na expansão de vizinhos (traria o
       contexto inteiro): notas alcançáveis só pelo MOC não entram como link:N. Sem context, o MOC é uma nota comum
       (atravessada como qualquer outra). (UT-01; IT-01 em test_query_cli)
    B. O corte por max_chars é "pula e continua": na ordem de prioridade, cada nota entra inteira se ainda couber; a
       que não cabe vai para omitted e as seguintes continuam sendo tentadas (uma nota grande bem ranqueada não
       empurra notas pequenas e relevantes para omitted). A ordem de "notes" segue a prioridade. (UT-02)
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


# MOC do contexto college liga a A (resultado da busca) e às irmãs S1 e S2, que só o MOC liga. A -> B -> C.
MOC_GRAPH = {
    "mocs/college.md": "---\ntype: moc\ntitle: College\ncontext: college\n---\n# College\n\n"
                       "- [[A]]\n- [[S1]]\n- [[S2]]\n",
    "A.md": "---\ncontext: college\n---\n# A\n\nA zebra listrada. Ver [[B]].\n",
    "B.md": "---\ncontext: college\n---\n# B\n\nCavalos. Ver [[C]].\n",
    "C.md": "# C\n\nBurros e mulas.\n",
    "S1.md": "---\ncontext: college\n---\n# S1\n\nCálculo diferencial.\n",
    "S2.md": "---\ncontext: college\n---\n# S2\n\nÁlgebra linear.\n",
}


class BuildContextMocNotTraversedTest(unittest.TestCase):
    def notes(self):
        return [parse(path, text) for path, text in MOC_GRAPH.items()]

    def test_moc_comes_first_but_is_not_traversed_with_context(self):
        """SPEC-0020:UT-01"""
        data = build(self.notes(), "zebra", context="college", hops=2)
        found = paths_of(data["notes"]) + paths_of(data["omitted"])
        reasons = {item["path"]: item["reason"] for item in data["notes"]}
        self.assertEqual(data["notes"][0]["path"], "mocs/college.md", data["notes"])
        self.assertEqual(reasons["mocs/college.md"], "moc")
        self.assertRegex(reasons.get("A.md", ""), REASON_SEARCH, data["notes"])
        self.assertEqual(reasons.get("B.md"), "link:1", data["notes"])
        self.assertEqual(reasons.get("C.md"), "link:2", "vizinho real a dois passos (por B, não pelo MOC)")
        for sibling in ("S1.md", "S2.md"):
            with self.subTest(sibling=sibling):
                self.assertNotIn(sibling, found, "nota alcançável só pelo MOC não entra (decisão A)")
        self.assertEqual(paths_of(data["notes"]), ["mocs/college.md", "A.md", "B.md", "C.md"], data["notes"])

    def test_without_context_the_moc_is_an_ordinary_note(self):
        """SPEC-0020:UT-01"""
        data = build(self.notes(), "zebra", hops=2)
        reasons = {item["path"]: item["reason"] for item in data["notes"]}
        self.assertRegex(reasons.get("A.md", ""), REASON_SEARCH, data["notes"])
        self.assertEqual(reasons.get("mocs/college.md"), "link:1", "sem context o MOC é vizinho comum")
        self.assertEqual(reasons.get("S1.md"), "link:2", "sem context o MOC é atravessado")
        self.assertEqual(reasons.get("S2.md"), "link:2")


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

    def test_a_big_top_note_that_does_not_fit_does_not_push_small_ones_out(self):
        """SPEC-0020:UT-02"""
        texts = {
            "N1.md": padded("# Zebra alfa\n\nzebra zebra zebra no título e no corpo.", 45000),
            "N2.md": "# Beta\n\nzebra zebra\n",
            "N3.md": "# Gama\n\numa zebra!!\n",
        }
        self.assertEqual({path: len(text) for path, text in texts.items()},
                         {"N1.md": 45000, "N2.md": 20, "N3.md": 20})
        notes = [parse(path, text) for path, text in texts.items()]
        ranked = [r["path"] for r in fn("search", "SPEC-0018")(notes, "zebra")]
        self.assertEqual(ranked, ["N1.md", "N2.md", "N3.md"], "pré-condição: prioridade N1, N2, N3")

        data = build(notes, "zebra", hops=0, max_chars=40000)
        self.assertEqual(paths_of(data["notes"]), ["N2.md", "N3.md"], "pula a que não cabe e continua (decisão B)")
        self.assertEqual(paths_of(data["omitted"]), ["N1.md"], data["omitted"])
        self.assertRegex(data["omitted"][0]["reason"], REASON_SEARCH)
        self.assertNotIn("content", data["omitted"][0])
        for item in data["notes"]:
            self.assertEqual(item["content"], texts[item["path"]], "nota entra inteira")


if __name__ == "__main__":
    unittest.main()
