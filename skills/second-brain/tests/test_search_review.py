"""Regressões das revisões das SPEC-0018 e SPEC-0020: ajustes da busca (SPEC-0026: UT-01, UT-02, IT-01, IT-02).

O que estes testes fixam (seção 3 da spec; pesos, formatos JSON, mensagens e códigos de saída não mudam):

    scan_vault(config)         arquivo .md oculto (nome começando com ".") não é lido, como no Obsidian.
    resolve_link(target, paths)
                               alvo e caminhos comparados em NFC: [[Ação]] digitado em NFC acha "Ação.md" gravado em
                               NFD (macOS, provedores de sincronização) e o contrário; vale também para alvo com "/".
    parse_note(path, text)     uma cerca só fecha com outra do mesmo caractere e com pelo menos o mesmo tamanho
                               (```` não fecha com ```); termos com menos de 2 caracteres não contam.
    Note(**campos)             campo desconhecido = TypeError.
    related                    log.md e index.md (layout.log e layout.index) nunca aparecem; search ainda os acha.
    context --hops N           log.md e index.md nunca servem de caminho na expansão de vizinhos: nenhuma nota
                               entra como link:N alcançada só por eles.
    references/search.md       diz que todo ![[anexo]] aparece em "broken" do links (não só anexos fora do vault).
"""
import os
import re
import unicodedata
import unittest

from brain_support import SKILL, Sandbox, brain, fn
from test_search_cli import SearchCliTestCase

SPEC = "SPEC-0026"
SEARCH_MD = SKILL / "references" / "search.md"
NFC_ACAO = unicodedata.normalize("NFC", "Ação")
NFD_ACAO = unicodedata.normalize("NFD", "Ação")

FENCES = """# Cercas

````md
```
#x
```
````

#fora

```
#y
````

#depois
"""


def parse(path, text, contexts=None):
    return fn("parse_note", "SPEC-0018")(path, text, contexts)


def resolve(target, paths):
    return fn("resolve_link", "SPEC-0018")(target, paths)


def nfc(path):
    return unicodedata.normalize("NFC", path) if path else path


class HiddenAndUnicodeScanTest(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.box.vault.mkdir(parents=True)
        out = self.box.init()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def write(self, rel, text):
        path = self.box.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def scan(self):
        config = fn("load_config")(self.box.config_home)
        return fn("scan_vault", "SPEC-0018")(config)

    def test_hidden_md_files_are_not_scanned(self):
        """SPEC-0026:UT-01"""
        self.write(".dot.md", "# Oculta\n\nNão deveria aparecer.\n")
        self.write("resources/.oculta.md", "# Oculta 2\n\nTambém não.\n")
        self.write("resources/visivel.md", "# Visível\n\nAparece.\n")
        paths = [note.path for note in self.scan()]
        self.assertIn("resources/visivel.md", paths)
        self.assertNotIn(".dot.md", paths, "arquivo oculto não é indexado (o Obsidian não indexa)")
        self.assertNotIn("resources/.oculta.md", paths)

    def test_nfc_link_resolves_to_a_file_name_stored_in_nfd(self):
        """SPEC-0026:UT-01"""
        self.write(f"resources/{NFD_ACAO}.md", "# Ação\n\nNome gravado em NFD.\n")
        on_disk = os.listdir(self.box.vault / "resources")
        if f"{NFD_ACAO}.md" not in on_disk:
            self.skipTest(f"o sistema de arquivos normaliza nomes para NFC: {on_disk!r}")
        self.write("resources/fonte.md", f"# Fonte\n\nVer [[{NFC_ACAO}]].\n")
        paths = [note.path for note in self.scan()]
        found = resolve(NFC_ACAO, paths)
        self.assertIsNotNone(found, f"[[Ação]] em NFC não achou o arquivo em NFD: {paths!r}")
        self.assertEqual(nfc(found), f"resources/{NFC_ACAO}.md")
        self.assertEqual(nfc(resolve(f"resources/{NFC_ACAO}", paths)), f"resources/{NFC_ACAO}.md")


class ParseFixesTest(unittest.TestCase):
    def test_link_and_path_keys_are_compared_in_nfc(self):
        """SPEC-0026:UT-01"""
        for stored, typed in ((NFD_ACAO, NFC_ACAO), (NFC_ACAO, NFD_ACAO)):
            with self.subTest(stored=ascii(stored), typed=ascii(typed)):
                paths = [f"resources/{stored}.md", "resources/outra.md"]
                self.assertEqual(resolve(typed, paths), f"resources/{stored}.md")
                self.assertEqual(resolve(f"resources/{typed}", paths), f"resources/{stored}.md")
                self.assertEqual(resolve(f"resources/{typed}.md", paths), f"resources/{stored}.md")

    def test_a_fence_closes_only_with_the_same_char_and_at_least_the_same_length(self):
        """SPEC-0026:UT-01"""
        note = parse("resources/cercas.md", FENCES)
        self.assertNotIn("x", note.tags, "``` dentro de ```` não fecha a cerca: #x é código")
        self.assertIn("fora", note.tags, "```` fecha a cerca de 4 crases")
        self.assertNotIn("y", note.tags, "#y está dentro da cerca de 3 crases")
        self.assertIn("depois", note.tags, "```` (mais longa) fecha a cerca de 3 crases")

        note = parse("resources/til.md", "~~~~\n~~~\n#dentro\n```\n~~~~\n#fim\n")
        self.assertNotIn("dentro", note.tags)
        self.assertIn("fim", note.tags)

    def test_terms_shorter_than_two_characters_do_not_count(self):
        """SPEC-0026:UT-01"""
        note = parse("resources/curto.md", "# Curto\n\nVer [[Ref#s]] e x = 1 no item b.\n")
        self.assertIn("ref", note.terms)
        short = sorted(term for term in note.terms if len(term) < 2)
        self.assertEqual(short, [], "termos de 1 caractere não contam na pontuação")
        self.assertEqual(sorted(t for t in fn("tokenize", SPEC)("a b c x y z") if len(t) < 2), [])


class StrictNoteTest(unittest.TestCase):
    def test_note_rejects_unknown_fields(self):
        """SPEC-0026:UT-02"""
        note_class = getattr(brain(), "Note", None)
        self.assertIsNotNone(note_class, "brain.Note não existe (SPEC-0018)")
        self.assertEqual(note_class(path="a.md", title="A").path, "a.md")
        with self.assertRaises(TypeError):
            note_class(path="a.md", titel="erro de digitação")


class SearchDocTest(unittest.TestCase):
    def test_search_md_says_every_attachment_embed_is_broken_in_links(self):
        """SPEC-0026:UT-01 — texto de references/search.md"""
        text = SEARCH_MD.read_text(encoding="utf-8")
        self.assertFalse(re.search(r"anexos fora do vault aparecem como quebrados", text),
                         "não é só o anexo fora do vault: todo ![[anexo]] aparece em broken")
        lines = [line for line in text.splitlines() if "![[" in line and "broken" in line]
        self.assertTrue(any(re.search(r"\b(todo|todos|qualquer|sempre|every|always)\b", line, re.IGNORECASE)
                            for line in lines),
                        f"{SEARCH_MD} deve dizer que todo ![[anexo]] aparece em broken do links: {lines!r}")


LOG_LINES = "".join(f"- 2026-10-{day:02d} 10:00 new-note resources/Redes de computadores.md — protocolo tcp "
                    f"roteamento redes item {day} s a b\n" for day in range(1, 29))


class SearchReviewCliTestCase(SearchCliTestCase):
    def make_plain_vault(self):
        """Vault do init sem contextos (sem MOC: o index.md só lista as notas recentes)."""
        self.box.vault.mkdir(parents=True)
        self.assertExit(self.box.init(), 0)

    def note_text(self, title, body):
        return f"---\ntitle: {title}\ntype: note\ncreated: 2026-10-30\n---\n# {title}\n\n{body}\n"

    def append(self, rel, text):
        path = self.box.vault / rel
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


class RelatedLayoutFilesCliTest(SearchReviewCliTestCase):
    def test_related_never_lists_log_or_index_but_search_still_finds_them(self):
        """SPEC-0026:IT-01"""
        self.make_plain_vault()
        self.write({
            "resources/Redes de computadores.md": self.note_text(
                "Redes de computadores", "Protocolo TCP e roteamento entre sub-redes. Ver [[Ref#s]]."),
            "resources/Ref.md": self.note_text("Ref", "Referência de protocolos de redes."),
            "resources/Banco de dados.md": self.note_text("Banco de dados", "Índices e replicação de redes."),
        })
        self.assertExit(self.box.run("index"), 0)
        self.append("log.md", LOG_LINES)
        index_text = (self.box.vault / "index.md").read_text(encoding="utf-8")
        self.assertIn("[[Redes de computadores]]", index_text, "index.md lista as notas recentes")

        for args in (("--note", "resources/Redes de computadores.md"), ("--text", "protocolo tcp redes roteamento")):
            with self.subTest(args=args):
                found = [r["path"] for r in self.json_of("related", *args)["results"]]
                self.assertTrue(found, f"related {args} sem resultados")
                self.assertNotIn("log.md", found, "log.md fica fora de related")
                self.assertNotIn("index.md", found, "index.md fica fora de related")

        self.assertIn("log.md", self.search_paths("init"), "search ainda acha o log.md")
        self.assertIn("index.md", self.search_paths("index"), "search ainda acha o index.md")


class ContextLayoutFilesCliTest(SearchReviewCliTestCase):
    def test_context_never_expands_through_index_or_log(self):
        """SPEC-0026:IT-02"""
        self.make_plain_vault()
        self.write({
            "resources/Alfa.md": self.note_text("Alfa", "Deploy no kubernetes com a equipe. Ver [[Vizinho]]."),
            "resources/Vizinho.md": self.note_text("Vizinho", "Ver também [[Segundo passo]]."),
            "resources/Segundo passo.md": self.note_text("Segundo passo", "Fim da cadeia."),
            "resources/Bravo.md": self.note_text("Bravo", "Receita de bolo de cenoura."),
            "resources/Charlie.md": self.note_text("Charlie", "Roteiro de praia no verão."),
        })
        self.assertExit(self.box.run("index"), 0)
        index_text = (self.box.vault / "index.md").read_text(encoding="utf-8")
        for title in ("Alfa", "Bravo", "Charlie"):
            self.assertIn(f"[[{title}]]", index_text, "index.md lista as notas recentes")
        self.write({"resources/Eco.md": self.note_text("Eco", "Ligada só pelo log.")})
        self.append("log.md", "- 2026-10-30 10:00 relate resources/Alfa.md — [[Alfa]] e [[Eco]]\n")

        data = self.json_of("context", "kubernetes", "--hops", "2")
        reasons = {n["path"]: n["reason"] for n in data["notes"]}
        reasons.update({n["path"]: n["reason"] for n in data["omitted"]})
        self.assertTrue(reasons.get("resources/Alfa.md", "").startswith("search:"), reasons)
        self.assertEqual(reasons.get("resources/Vizinho.md"), "link:1", reasons)
        self.assertEqual(reasons.get("resources/Segundo passo.md"), "link:2", reasons)
        for path in ("resources/Bravo.md", "resources/Charlie.md"):
            self.assertNotIn(path, reasons, f"{path} só é alcançada pelo index.md")
        self.assertNotIn("resources/Eco.md", reasons, "Eco só é alcançada pelo log.md")


if __name__ == "__main__":
    unittest.main()
