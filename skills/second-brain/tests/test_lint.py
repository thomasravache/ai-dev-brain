"""Regras do lint, uma a uma, sem a CLI (SPEC-0023: UT-01 a UT-04).

Contrato esperado das funções de scripts/brain.py (o Implementer segue estes testes; seções 4 e 6 da spec).
Cada regra é uma função `check_<regra>` que só lê e devolve list[Finding]; o `lint` as registra num dicionário e
as roda sobre uma única varredura (scan_vault + LinkIndex). As assinaturas abaixo são as que os testes usam:

    Finding
        objeto com os atributos rule, severity, path, detail e suggestion (uma classe simples, como Note; os
        testes também aceitam um dict com essas chaves). severity: "error" | "warn". path: relativo ao vault,
        com "/". É o item de {"findings": [...]} do `lint --json`.

    check_broken_link(notes: list[Note], index: LinkIndex) -> list[Finding]
        um achado (rule "broken-link", severity "error") por wikilink de Note.links que index.resolve (o mesmo
        resolve_link da SPEC-0018) não resolve. path = a nota que tem o link; detail cita o alvo.
        Leitura do contrato: "wikilink que não resolve (resolve_link)" — "[[Existe]]", "[[existe#seção]]" e
        "[[Existe|apelido]]" resolvem. Embeds de anexo ("![[img.png]]") não estão fixados por estes testes.

    check_conflict_copy(paths, patterns) -> list[Finding]
        paths = caminhos relativos ao vault (com "/") dos arquivos varridos; patterns = lista de regex (texto)
        aplicadas ao NOME do arquivo, cada uma com o grupo "base". Achado (rule "conflict-copy", severity
        "error") só quando o nome casa e o original "<base>.md" existe na MESMA pasta. path = a cópia; detail ou
        suggestion citam o original. Regex inválido não é tratado aqui (é o achado `config` do lint, IT-04).

    check_missing_file(notes: list[Note], files: Path) -> list[Finding]
        um achado (rule "missing-file", severity "error") por item de frontmatter.files (caminho relativo à
        pasta files) que não existe em `files`. path = a nota; detail cita o caminho ausente.

    check_orphan(notes: list[Note], index: LinkIndex, layout: dict) -> list[Finding]
        layout = values["layout"] (inbox, raw, mocs, templates, index, log). Achado (rule "orphan", severity
        "warn") para a nota sem link de saída que resolve, sem link de entrada e fora de qualquer MOC; não
        avalia notas em raw/, inbox/, mocs/, templates/, nem index.md e log.md.

As regras stale-inbox, frontmatter e config são conferidas pela CLI (test_lint_cli: IT-01 e IT-04).
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from brain_support import fn

SPEC = "SPEC-0023"
LAYOUT = {"inbox": "inbox", "raw": "raw", "mocs": "mocs", "templates": "templates",
          "index": "index.md", "log": "log.md"}
GENERIC_PATTERNS = [r"(?P<base>.+) \(\d+\)\.md$", r"(?P<base>.+)[ _-]conflict.*\.md$"]
FIELDS = ("rule", "severity", "path", "detail", "suggestion")


def note_text(title, body="", extra=""):
    return (f"---\ntype: note\ntitle: {title}\ncreated: 2026-10-01\ntags: []\n{extra}---\n\n# {title}\n\n"
            f"{body}\n")


def parse(path, text):
    return fn("parse_note", "SPEC-0018")(path, text, None)


def link_index(notes):
    return fn("LinkIndex", "SPEC-0018")(n.path for n in notes)


def as_dict(finding):
    """Finding como dict (atributos ou chaves), conferindo os cinco campos do contrato."""
    if isinstance(finding, dict):
        data = {name: finding.get(name) for name in FIELDS}
    else:
        data = {name: getattr(finding, name, None) for name in FIELDS}
    for name in FIELDS:
        if not isinstance(data[name], str) or (name != "suggestion" and not data[name]):
            raise AssertionError(f"Finding sem {name} válido: {finding!r}")
    return data


def findings(result):
    assert isinstance(result, list), f"check_* devolve list[Finding], veio {type(result).__name__}"
    return [as_dict(item) for item in result]


class BrokenLinkTest(unittest.TestCase):
    def test_only_the_link_that_does_not_resolve_is_reported(self):
        """SPEC-0023:UT-01"""
        notes = [
            parse("projects/college/Existe.md", note_text("Existe", "Texto.")),
            parse("projects/college/Fonte.md",
                  note_text("Fonte", "Ver [[Existe]], [[existe#seção]], [[Existe|apelido]] e [[Inexistente]].")),
        ]
        found = findings(fn("check_broken_link", SPEC)(notes, link_index(notes)))
        self.assertEqual(len(found), 1, found)
        item = found[0]
        self.assertEqual((item["rule"], item["severity"], item["path"]),
                         ("broken-link", "error", "projects/college/Fonte.md"))
        self.assertIn("Inexistente", item["detail"])

    def test_vault_without_broken_links_has_no_findings(self):
        """SPEC-0023:UT-01"""
        notes = [parse("a.md", note_text("A", "[[b]]")), parse("sub/b.md", note_text("B", "[[A]] [[a.md]] [[sub/b#topo]]"))]
        self.assertEqual(findings(fn("check_broken_link", SPEC)(notes, link_index(notes))), [])


class ConflictCopyTest(unittest.TestCase):
    def check(self, paths, patterns=GENERIC_PATTERNS):
        return findings(fn("check_conflict_copy", SPEC)(list(paths), list(patterns)))

    def test_copies_with_the_original_in_the_same_folder_are_reported(self):
        """SPEC-0023:UT-02"""
        paths = ["projects/college/Aula.md", "projects/college/Aula (1).md",
                 "projects/college/Plano.md", "projects/college/Plano conflict 2026-10-30.md",
                 "projects/college/Aula 2.md"]
        found = self.check(paths)
        self.assertEqual(sorted(item["path"] for item in found),
                         ["projects/college/Aula (1).md", "projects/college/Plano conflict 2026-10-30.md"], found)
        for item in found:
            with self.subTest(path=item["path"]):
                self.assertEqual((item["rule"], item["severity"]), ("conflict-copy", "error"))
                original = "Aula.md" if "Aula" in item["path"] else "Plano.md"
                self.assertIn(original, item["detail"] + item["suggestion"], "achado cita o original")

    def test_a_suffix_without_the_original_in_the_same_folder_is_not_reported(self):
        """SPEC-0023:UT-02"""
        # "Aula 2.md" sozinho: nem com um padrão que casa com o sufixo " 2" ele vira achado
        self.assertEqual(self.check(["projects/college/Aula 2.md"], [r"(?P<base>.+) \d+\.md$"]), [])
        # o original existe, mas em outra pasta
        self.assertEqual(self.check(["Resumo.md", "projects/college/Resumo (1).md",
                                     "projects/college/Outro conflict.md"]), [])


class MissingFileTest(unittest.TestCase):
    def setUp(self):
        self.files = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.files, True)

    def test_only_the_missing_file_of_frontmatter_files_is_reported(self):
        """SPEC-0023:UT-03"""
        (self.files / "college" / "2026").mkdir(parents=True)
        (self.files / "college" / "2026" / "a.pdf").write_bytes(b"%PDF-1.4\n")
        notes = [
            parse("raw/2026-10-01-aula.md",
                  note_text("Aula", extra="files: [college/2026/a.pdf, college/2026/b.pdf]\n")),
            parse("raw/2026-10-02-ok.md", note_text("Ok", extra="files: [college/2026/a.pdf]\n")),
            parse("projects/college/Sem arquivos.md", note_text("Sem arquivos")),
        ]
        found = findings(fn("check_missing_file", SPEC)(notes, self.files))
        self.assertEqual(len(found), 1, found)
        item = found[0]
        self.assertEqual((item["rule"], item["severity"], item["path"]),
                         ("missing-file", "error", "raw/2026-10-01-aula.md"))
        self.assertIn("college/2026/b.pdf", item["detail"])
        self.assertNotIn("a.pdf", item["detail"])


class OrphanTest(unittest.TestCase):
    def test_only_the_note_without_links_and_outside_any_moc_is_reported(self):
        """SPEC-0023:UT-04"""
        texts = {
            "projects/college/Solta.md": note_text("Solta", "Sem nenhum link."),
            "projects/college/Citada.md": note_text("Citada", "Só o MOC cita esta nota."),
            "mocs/college.md": "---\ntype: moc\ntitle: College\ncreated: 2026-10-01\n---\n\n- [[Citada]]\n",
            "projects/college/Alvo.md": note_text("Alvo", "Recebe um backlink."),
            "projects/college/Fonte.md": note_text("Fonte", "Aponta para [[Alvo]]."),
            "raw/2026-10-01-bruto.md": note_text("Bruto", "Nota de fonte solta."),
            "inbox/2026-10-01-ideia.md": note_text("Ideia", "Captura solta."),
            "mocs/vazio.md": "---\ntype: moc\ntitle: Vazio\ncreated: 2026-10-01\n---\n\nNada.\n",
            "index.md": "# Index\n",
            "log.md": "# Log\n",
        }
        notes = [parse(path, text) for path, text in texts.items()]
        found = findings(fn("check_orphan", SPEC)(notes, link_index(notes), dict(LAYOUT)))
        self.assertEqual([(item["rule"], item["severity"], item["path"]) for item in found],
                         [("orphan", "warn", "projects/college/Solta.md")], found)


if __name__ == "__main__":
    unittest.main()
