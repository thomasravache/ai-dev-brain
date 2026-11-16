"""Título de nota confidencial fora do log.md na busca e no contexto (SPEC-0064: UT-01 e IT-01).

O log.md gerado registra o caminho de cada nota escrita, inclusive das confidenciais ("new-note <caminho> — note;
confidencial") e das que viraram confidenciais depois. Sem --include-confidential, search e context leem o log.md
sem as linhas que citam uma nota confidencial (o caminho como o log.md o escreve, linhas antigas incluídas): nem o
título nem o caminho aparecem em resultado, snippet ou conteúdo. Com --include-confidential nada muda. O arquivo
log.md não muda (só acréscimo, ADR-0007).

O vault é criado pela CLI real (brain_support.Sandbox: HOME e BRAIN_CONFIG_HOME temporários, nunca a configuração
real). O UT-01 chama search e build_context de brain.py com as notas de load_vault; o IT-01 roda a CLI como processo.
"""
import json
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

    def assertNothingHidden(self, text, label):
        low = text.lower()
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
                self.assertNothingHidden(json.dumps(results, ensure_ascii=False), f"search {query!r}")
                package = build_context(notes, query, values=values)
                self.assertNothingHidden(json.dumps(package, ensure_ascii=False), f"context {query!r}")

        # o log.md continua no pacote quando ainda casa (linha da nota comum), sem as linhas das confidenciais
        package = build_context(notes, "quokka", values=values)
        log = [n for n in package["notes"] if n["path"] == "log.md"]
        self.assertEqual(len(log), 1, package)
        self.assertIn(COMMON, log[0]["content"])
        self.assertNothingHidden(json.dumps(package, ensure_ascii=False), "context 'quokka'")
        results = search(notes, "quokka")
        self.assertIn("log.md", [r["path"] for r in results])
        self.assertNothingHidden(json.dumps(results, ensure_ascii=False), "search 'quokka'")

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


if __name__ == "__main__":
    unittest.main()
