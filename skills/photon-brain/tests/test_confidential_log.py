"""Título de nota confidencial fora do log.md na busca e no contexto (SPEC-0064: UT-01 e IT-01).

O log.md gerado registra o caminho de cada nota escrita, inclusive das confidenciais ("new-note <caminho> — note;
confidencial") e das que viraram confidenciais depois. Sem --include-confidential, search e context leem o log.md
sem as linhas que citam uma nota confidencial (o caminho como o log.md o escreve, linhas antigas incluídas): nem o
título nem o caminho aparecem em resultado, snippet ou conteúdo. Com --include-confidential nada muda. O arquivo
log.md não muda (só acréscimo, ADR-0007).

O vault é criado pela CLI real (brain_support.Sandbox: HOME e BRAIN_CONFIG_HOME temporários, nunca a configuração
real). O UT-01 chama search e build_context de brain.py com as notas de load_vault; o IT-01 roda a CLI como processo.
O UT-02 (Emenda v2, revisão G4) cobre o arquivo guardado de uma nota de fonte confidencial (linha inbox-move do
ingest --move: nome original em inbox/ e caminho em <files>/), um [[link|apelido]] para a confidencial, linhas antigas
em MAIÚSCULAS, em NFD e com "\\" no caminho, e o caminho com fronteira à esquerda (sem falso positivo por sufixo).
"""
import json
import unicodedata
import unittest

from brain_support import Sandbox, fn, output

SPEC = "SPEC-0064"
SECRET_TITLE = "Payments Secret Plan"
SECRET = f"projects/college/{SECRET_TITLE}.md"
# nota comum quando foi criada (linha antiga do log.md sem "confidencial"), marcada confidencial depois
LATER_TITLE = "Zebracorn Merger Memo"
LATER = f"projects/college/{LATER_TITLE}.md"
COMMON_TITLE = "Quokka Budget Review"
COMMON = f"projects/college/{COMMON_TITLE}.md"
# linha antiga escrita à mão no formato do log.md, de antes da nota virar confidencial
OLD_LINE = f"- 2025-12-01 09:00 new-note {SECRET} — note\n"
HIDDEN = (SECRET_TITLE, SECRET, LATER_TITLE, LATER)
QUERIES = ("payments secret plan", "zebracorn merger memo")


class ConfidentialLogTestCase(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.box.new_vault()
        self.cli("new-note", "--type", "note", "--title", SECRET_TITLE, "--confidential", "--context", "college")
        self.cli("new-note", "--type", "note", "--title", COMMON_TITLE, "--context", "college")
        self.cli("new-note", "--type", "note", "--title", LATER_TITLE, "--context", "college")
        later = self.box.vault / LATER
        text = later.read_text(encoding="utf-8")
        self.assertIn("\ntags: []\n", text)
        later.write_text(text.replace("\ntags: []\n", "\ntags: []\nconfidential: true\n", 1), encoding="utf-8")
        self.log_path = self.box.vault / "log.md"
        with open(self.log_path, "a", encoding="utf-8") as handle:
            handle.write(OLD_LINE)
        self.log_text = self.log_path.read_text(encoding="utf-8")
        for path in (SECRET, LATER, COMMON):
            self.assertIn(path, self.log_text, "o log.md gerado pela CLI cita o caminho de cada nota")

    def cli(self, *args):
        out = self.box.run(*args)
        self.assertEqual(out.returncode, 0, f"{args}: {output(out)}")
        return out

    def assertNothingHidden(self, data, label):
        """data: a saída (objeto ou texto JSON); o campo "query" só repete a consulta e fica fora da checagem."""
        if isinstance(data, str):
            data = json.loads(data)
        if isinstance(data, dict):
            data = {key: value for key, value in data.items() if key != "query"}
        low = json.dumps(data, ensure_ascii=False).lower()
        for item in HIDDEN:
            self.assertNotIn(item.lower(), low, f"{label}: {item!r} vazou na saída")

    def assertLogUnchanged(self):
        self.assertEqual(self.log_path.read_text(encoding="utf-8"), self.log_text, "log.md só recebe acréscimos")


class ConfidentialLogUnitTest(ConfidentialLogTestCase):
    def test_search_and_context_read_log_without_confidential_lines(self):
        """SPEC-0064:UT-01"""
        values, notes, _ = fn("load_vault", SPEC)(str(self.box.config_home))
        search, build_context = fn("search", SPEC), fn("build_context", SPEC)
        for query in QUERIES:
            with self.subTest(query=query):
                results = search(notes, query)
                self.assertNothingHidden(results, f"search {query!r}")
                package = build_context(notes, query, values=values)
                self.assertNothingHidden(package, f"context {query!r}")

        # o log.md continua no pacote quando ainda casa (linha da nota comum), sem as linhas das confidenciais
        package = build_context(notes, "quokka", values=values)
        log = [n for n in package["notes"] if n["path"] == "log.md"]
        self.assertEqual(len(log), 1, package)
        self.assertIn(COMMON, log[0]["content"])
        self.assertNothingHidden(package, "context 'quokka'")
        results = search(notes, "quokka")
        self.assertIn("log.md", [r["path"] for r in results])
        self.assertNothingHidden(results, "search 'quokka'")

        # com --include-confidential o log.md volta a trazer as linhas (inclusive a antiga)
        shown = search(notes, "payments secret plan", include_confidential=True)
        self.assertIn("log.md", [r["path"] for r in shown])
        package = build_context(notes, "payments secret plan", values=values, include_confidential=True)
        log = [n for n in package["notes"] if n["path"] == "log.md"]
        self.assertEqual(len(log), 1, package)
        self.assertIn(f"new-note {SECRET} — note; confidencial", log[0]["content"])
        self.assertIn(OLD_LINE.strip(), log[0]["content"])
        self.assertIn(f"new-note {LATER} — note", log[0]["content"])
        self.assertLogUnchanged()


class ConfidentialLogCliTest(ConfidentialLogTestCase):
    def test_cli_search_and_context_json_never_print_the_confidential_title(self):
        """SPEC-0064:IT-01"""
        for query in QUERIES:
            for command in ("search", "context"):
                with self.subTest(command=command, query=query):
                    out = self.cli(command, "--json", "--", *query.split())
                    json.loads(out.stdout)
                    self.assertNothingHidden(out.stdout, f"{command} --json {query!r}")

        out = self.cli("search", "--json", "--", "quokka")
        data = json.loads(out.stdout)
        log = [r for r in data["results"] if r["path"] == "log.md"]
        self.assertEqual(len(log), 1, "a linha do log.md sobre uma nota comum continua encontrável")
        self.assertIn(COMMON_TITLE, log[0]["snippet"])
        self.assertNothingHidden(out.stdout, "search --json quokka")

        out = self.cli("context", "--json", "--", "quokka")
        data = json.loads(out.stdout)
        log = [n for n in data["notes"] if n["path"] == "log.md"]
        self.assertEqual(len(log), 1, data)
        self.assertIn(COMMON, log[0]["content"])
        self.assertNothingHidden(out.stdout, "context --json quokka")

        out = self.cli("context", "--json", "--include-confidential", "--", "payments", "secret", "plan")
        self.assertIn(SECRET, out.stdout)
        self.assertLogUnchanged()


CONTRACT = "Contrato Fulano Beltrano"
CONTRACT_INBOX = f"inbox/{CONTRACT}.pdf"
ACCENT_TITLE = "Orçamento Sigiloso"
ACCENT = f"projects/college/{ACCENT_TITLE}.md"
BUSINESS = "projects/college/Business Plan.md"
PLANO_B = "projects/college/plano-b.md"
# confidenciais na raiz, escritas à mão: o caminho de cada uma é sufixo do de uma nota comum
ROOT_SECRETS = {"Plan.md": "Plan", "plano.md": "plano"}
# o que nenhuma saída pode trazer nos casos 1 a 3 (comparado sem caixa, em NFC e com "\\" virando "/")
HIDDEN_V2 = (CONTRACT, CONTRACT_INBOX, f"<files>/college/2026/{CONTRACT}.pdf", SECRET_TITLE, SECRET,
             ACCENT_TITLE, ACCENT)
OLD_LINES = (
    # [[link|apelido]] para a confidencial numa linha relate
    f"- 2026-11-10 10:00 relate {COMMON} → [[{SECRET_TITLE}|apelido]] — exemplo\n",
    # linhas antigas: MAIÚSCULAS, NFD e "\\" no caminho
    f"- 2025-01-01 09:00 new-note {SECRET.upper()} — note\n",
    unicodedata.normalize("NFD", f"- 2025-02-01 09:00 new-note {ACCENT} — note\n"),
    f"- 2025-03-01 09:00 new-note {SECRET.replace('/', chr(92))} — note\n",
)


def comparable(data) -> str:
    """A saída sem o campo "query" (que só repete a consulta), como texto sem caixa, em NFC e com "/" no lugar de "\\"."""
    if isinstance(data, dict):
        data = {key: value for key, value in data.items() if key != "query"}
    text = unicodedata.normalize("NFC", json.dumps(data, ensure_ascii=False))
    return text.replace("\\\\", "/").replace("\\", "/").lower()


class ConfidentialLogAmendmentTest(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.box.new_vault()
        (self.box.vault / CONTRACT_INBOX).write_bytes(b"%PDF-1.4 contrato fim")
        self.cli("ingest", "--move", "--confidential", "--context", "college", CONTRACT_INBOX, cwd=self.box.vault)
        for title, extra in ((SECRET_TITLE, ("--confidential",)), (ACCENT_TITLE, ("--confidential",)),
                             (COMMON_TITLE, ()), ("Business Plan", ()), ("plano-b", ())):
            self.cli("new-note", "--type", "note", "--title", title, "--context", "college", *extra)
        self.log_path = self.box.vault / "log.md"
        lines = list(OLD_LINES)
        for rel, title in ROOT_SECRETS.items():
            (self.box.vault / rel).write_text(f"---\ntype: note\ntitle: {title}\ncreated: 2026-10-01\ntags: []\n"
                                              f"confidential: true\n---\n\n# {title}\n\nNota sigilosa.\n",
                                              encoding="utf-8")
            lines.append(f"- 2026-11-11 10:00 new-note {rel} — note; confidencial\n")
        with open(self.log_path, "a", encoding="utf-8") as handle:
            handle.writelines(lines)
        self.log_text = self.log_path.read_text(encoding="utf-8")
        for path in (f"inbox-move {CONTRACT_INBOX} → <files>/", f"new-note {SECRET}", f"new-note {ACCENT}",
                     f"new-note {BUSINESS}", f"new-note {PLANO_B}"):
            self.assertIn(path, self.log_text, "linhas gravadas pela CLI")
        self.values, self.notes, _ = fn("load_vault", SPEC)(str(self.box.config_home))

    def cli(self, *args, cwd=None):
        out = self.box.run(*args, cwd=cwd)
        self.assertEqual(out.returncode, 0, f"{args}: {output(out)}")
        return out

    def outputs(self, query):
        """(rótulo, saída) de search e de context para a consulta, com as notas e a configuração do vault."""
        results = fn("search", SPEC)(self.notes, query, values=self.values)
        package = fn("build_context", SPEC)(self.notes, query, values=self.values)
        return (("search", results), ("context", package))

    def log_of(self, label, data):
        if label == "search":
            return [r["snippet"] for r in data if r["path"] == "log.md"]
        return [n["content"] for n in data["notes"] if n["path"] == "log.md"]

    def test_stored_file_links_old_lines_and_suffix_stay_right(self):
        """SPEC-0064:UT-02"""
        cases = (("arquivo guardado", "contrato fulano beltrano"), ("link com apelido", "payments secret plan apelido"),
                 ("linhas antigas", "payments secret plan"), ("linha antiga em NFD", "orçamento sigiloso"),
                 ("linhas do log", "new-note note"))
        for case, query in cases:
            for label, data in self.outputs(query):
                with self.subTest(case=case, command=label):
                    text = comparable(data)
                    for item in HIDDEN_V2:
                        self.assertNotIn(unicodedata.normalize("NFC", item).lower(), text,
                                         f"{label} {query!r}: {item!r} vazou na saída")

        # sem falso positivo por sufixo: a linha da nota comum continua encontrável e a da confidencial, não
        for case, query, common, secret in (("sufixo Plan.md", "business plan", BUSINESS, "Plan.md"),
                                            ("plano.md × plano-b.md", "plano", PLANO_B, "plano.md")):
            for label, data in self.outputs(query):
                with self.subTest(case=case, command=label):
                    log = self.log_of(label, data)
                    self.assertEqual(len(log), 1, f"{label} {query!r}: o log.md continua encontrável: {data}")
                    if label == "context":
                        self.assertIn(f"new-note {common} — note", log[0])
                    else:
                        self.assertIn(common.rsplit("/", 1)[1].lower(), log[0].lower())
                    self.assertNotIn(f"new-note {secret} — note; confidencial".lower(), comparable(data))
        self.assertEqual(self.log_path.read_text(encoding="utf-8"), self.log_text, "log.md só recebe acréscimos")


if __name__ == "__main__":
    unittest.main()
