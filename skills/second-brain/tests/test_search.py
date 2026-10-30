"""Leitura de notas, resolução de links, pontuação da busca e das relacionadas (SPEC-0018: UT-01 a UT-04).

Contrato esperado das funções puras de scripts/brain.py (o Implementer segue estes testes; seção 6 da spec):

    parse_note(path: str, text: str, contexts: dict | None = None) -> Note
        path     : caminho relativo ao vault, com "/" (ex.: "projects/college/aula.md").
        text     : conteúdo já decodificado da nota.
        contexts : values["contexts"] de load_config() — {nome: {"folder": pasta relativa, "title": ...}}.
        Sem I/O. Devolve um objeto com atributos (dataclass ou namedtuple):
          path        : o caminho recebido.
          title       : frontmatter.title, senão o primeiro "# Título", senão o nome do arquivo sem .md.
          frontmatter : dict (vazio se não houver ou se o YAML for inválido; inválido não levanta exceção).
          tags        : list[str] — frontmatter.tags (lista ou string) e depois cada "#tag" do texto, na ordem,
                        sem "#", em minúsculas. Não contam: "#" de blocos de código (```),
                        títulos ("# Título") e o "#seção" dentro de um wikilink ([[Z#seção]]).
          links       : list[str] — alvos dos wikilinks na ordem do texto: [[X]], [[Y|apelido]], [[Z#seção]],
                        ![[img.png]] -> "X", "Y", "Z", "img.png" (sem seção nem apelido).
          context     : frontmatter.context, senão o nome do contexto cuja pasta contém a nota, senão None/"".
          terms       : termos do texto (forma livre; minúsculas, sem acentos, sem stopwords pt/en).
        A tag `type` do frontmatter (frontmatter["type"]) é o "tipo" usado por search --type.

    resolve_link(target: str, paths) -> str | None
        paths : iterável dos caminhos relativos das notas do vault (Note.path).
        target com "/" -> caminho relativo ao vault, com ou sem ".md";
        sem "/" -> nota de mesmo nome de arquivo (sem ".md"), sem diferenciar maiúsculas;
        vários candidatos -> o de caminho mais curto; nenhum -> None (link quebrado).

    scan_vault(config: dict) -> list[Note]
        config = load_config(). Lê todo .md do vault, ignorando .obsidian/, .trash/ e a pasta layout.templates.
        Nota com frontmatter inválido ou que não é UTF-8 é lida como texto (errors="replace") e gera um aviso que
        os comandos publicam em "warnings" no --json (forma do aviso livre; coberta pelo IT-04 em test_search_cli).

    search(notes: list, query: str, context=None, note_type=None, tag=None, limit=10) -> list[dict]
        Pontuação: soma por termo da consulta de tf * idf, com peso 3 no título, 2 nas tags, 1 no corpo; a
        consulta é tokenizada como as notas (minúsculas, sem acentos). Só notas com pontuação > 0, em ordem
        decrescente. Cada resultado: {"path", "title", "score", "snippet", "context", "type"}; snippet tem até
        160 caracteres e contém o termo.

    related(notes: list, note: str | None = None, text: str | None = None, limit=10) -> list[dict]
        note = Note.path da nota de referência (ou text = texto livre). Pontuação:
          0,5 * cosseno TF-IDF + 0,2 * Jaccard das tags + 0,1 * mesmo contexto + 0,2 * vizinhança
          (1 se link direto em qualquer sentido, 0,5 se a dois passos).
        Exclui a própria nota; ordem decrescente; cada resultado: {"path", "title", "score", "reasons"} com
        motivos como "tags: x, y", "mesmo contexto", "link direto", "termos: a, b".
"""
import unittest

from brain_support import fn

SPEC = "SPEC-0018"
COLLEGE = {"college": {"folder": "projects/college", "title": "College"}}

FULL_NOTE = """---
title: Título da Nota
tags: [a]
context: college
---
# Outro título

Texto com #b no corpo.

```python
x = 1
#c
```

Links: [[X]], [[Y|apelido]], [[Z#seção]] e ![[img.png]].
"""

FILLER = (
    ("filler/um.md", "# Jardinagem\n\nPlantas, rega e adubo para a horta de casa.\n"),
    ("filler/dois.md", "# Culinária\n\nReceita de bolo de cenoura com cobertura de chocolate.\n"),
    ("filler/tres.md", "# Viagem\n\nRoteiro de praia, montanha e trilhas no verão.\n"),
)


def parse(path, text, contexts=None):
    return fn("parse_note", SPEC)(path, text, contexts)


def paths_of(results):
    return [r["path"] for r in results]


class ParseNoteTest(unittest.TestCase):
    def test_parse_note_reads_frontmatter_tags_and_wikilinks(self):
        """SPEC-0018:UT-01"""
        note = parse("projects/college/aula.md", FULL_NOTE, COLLEGE)
        self.assertEqual(note.path, "projects/college/aula.md")
        self.assertEqual(note.title, "Título da Nota")
        self.assertEqual(note.frontmatter.get("title"), "Título da Nota")
        self.assertEqual(note.frontmatter.get("context"), "college")
        self.assertEqual(list(note.tags), ["a", "b"], "#c está em bloco de código e #seção num wikilink")
        self.assertEqual(list(note.links), ["X", "Y", "Z", "img.png"])
        self.assertEqual(note.context, "college")

    def test_title_falls_back_to_heading_then_file_name(self):
        """SPEC-0018:UT-01"""
        self.assertEqual(parse("inbox/a.md", "# Primeiro Título\n\ntexto\n# Segundo\n").title, "Primeiro Título")
        self.assertEqual(parse("inbox/Sem Título.md", "só texto, sem cabeçalho\n").title, "Sem Título")

    def test_tags_accept_a_string_and_are_lowercased(self):
        """SPEC-0018:UT-01"""
        note = parse("inbox/a.md", "---\ntags: Unica\n---\ncorpo com #Outra\n")
        self.assertEqual(list(note.tags), ["unica", "outra"])

    def test_context_comes_from_the_context_folder_when_not_in_frontmatter(self):
        """SPEC-0018:UT-01"""
        inside = parse("projects/college/sub/aula.md", "corpo\n", COLLEGE)
        self.assertEqual(inside.context, "college")
        outside = parse("projects/collegex/aula.md", "corpo\n", COLLEGE)
        self.assertFalse(outside.context, "pasta com o mesmo prefixo de texto não é o contexto")

    def test_invalid_frontmatter_becomes_empty_without_raising(self):
        """SPEC-0018:UT-01"""
        note = parse("inbox/quebrada.md", "---\ntitle: [sem fechar\n---\n# Título do Corpo\n")
        self.assertEqual(note.frontmatter, {})
        self.assertEqual(note.title, "Título do Corpo")


class ResolveLinkTest(unittest.TestCase):
    PATHS = ("a/Nota.md", "b/c/Nota.md", "Outra.md")

    def test_resolve_link_by_name_path_case_and_shortest_candidate(self):
        """SPEC-0018:UT-02"""
        resolve = fn("resolve_link", SPEC)
        self.assertEqual(resolve("nota", self.PATHS), "a/Nota.md")
        self.assertEqual(resolve("b/c/Nota", self.PATHS), "b/c/Nota.md")
        self.assertEqual(resolve("b/c/Nota.md", self.PATHS), "b/c/Nota.md")
        self.assertEqual(resolve("OUTRA", self.PATHS), "Outra.md")
        self.assertIsNone(resolve("inexistente", self.PATHS))


class SearchScoringTest(unittest.TestCase):
    def notes(self):
        notes = [
            parse("title.md", "# Integracao contínua\n\nAnotações gerais sobre o pipeline.\n"),
            parse("body.md", "# Outra coisa\n\nUm parágrafo que fala de integracao no meio.\n"),
            parse("accent.md", "# Diário\n\nHoje estudei integração de dados com a equipe.\n"),
        ]
        return notes + [parse(path, text) for path, text in FILLER]

    def test_title_scores_higher_and_accents_are_ignored(self):
        """SPEC-0018:UT-03"""
        search = fn("search", SPEC)
        notes = self.notes()
        results = search(notes, "integracao")
        found = paths_of(results)
        self.assertEqual(found[0], "title.md", results)
        self.assertCountEqual(found, ["title.md", "body.md", "accent.md"])
        self.assertGreater(results[0]["score"], next(r["score"] for r in results if r["path"] == "body.md"))
        scores = [r["score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for result in results:
            self.assertTrue({"path", "title", "score", "snippet", "context", "type"} <= set(result), result)
            self.assertLessEqual(len(result["snippet"]), 160)
        self.assertEqual(paths_of(search(notes, "integração")), found)


class RelatedScoringTest(unittest.TestCase):
    def notes(self):
        notes = [
            parse("A.md", "---\ntags: [x, y]\n---\n# A\n\nRedes neurais, aprendizado profundo e gradiente.\n"),
            parse("B.md", "---\ntags: [x, y]\n---\n# B\n\nResumo da semana. Ver [[A]].\n"),
            parse("C.md", "# C\n\nRedes de pesca, futebol na praia e montanha.\n"),
        ]
        return notes + [parse(path, text) for path, text in FILLER]

    def test_shared_tags_and_direct_link_beat_shared_terms(self):
        """SPEC-0018:UT-04"""
        results = fn("related", SPEC)(self.notes(), note="A.md")
        found = paths_of(results)
        self.assertNotIn("A.md", found)
        self.assertIn("B.md", found)
        self.assertIn("C.md", found)
        self.assertLess(found.index("B.md"), found.index("C.md"), results)
        scores = [r["score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))
        b = results[found.index("B.md")]
        self.assertTrue({"path", "title", "score", "reasons"} <= set(b), b)
        tag_reasons = [r for r in b["reasons"] if r.startswith("tags:")]
        self.assertEqual(len(tag_reasons), 1, b["reasons"])
        self.assertIn("x", tag_reasons[0])
        self.assertIn("y", tag_reasons[0])
        self.assertIn("link direto", b["reasons"])
        c = results[found.index("C.md")]
        self.assertTrue(any(r.startswith("termos:") for r in c["reasons"]), c["reasons"])


if __name__ == "__main__":
    unittest.main()
