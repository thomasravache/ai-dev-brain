"""Integração pela CLI: search, related e links (SPEC-0018: IT-01 a IT-05).

Cada teste cria o vault com o `brain.py init` real (SPEC-0017) num diretório temporário com HOME e
BRAIN_CONFIG_HOME isolados (brain_support.Sandbox) e escreve notas sintéticas direto no vault.

Saídas que os testes conferem (contrato da seção 6; mensagens de erro podem ir para stdout ou stderr):
    search QUERY [--context C] [--type T] [--tag G] [--limit N] [--json]
        texto : uma linha "<pontos>  <caminho>  — <título>" por resultado (mais um trecho de até 160 caracteres)
        json  : {"query", "results": [{"path", "title", "score", "snippet", "context", "type"}], "warnings": [...]}
                caminhos relativos ao vault com "/"; score decrescente; --type filtra por frontmatter.type
        sem resultado : "Nenhuma nota encontrada para: QUERY", exit 0
        sem configuração local : exit 3 (SPEC-0017)
    related (--note CAMINHO | --text TEXTO) [--limit N] [--json]
        json  : {"results": [{"path", "title", "score", "reasons": [...]}]} — sem a própria nota, decrescente
        --note inexistente : exit 2 "nota não encontrada: CAMINHO"
    links NOTA [--json]          (NOTA = caminho ou nome, resolvido por resolve_link)
        json  : {"outgoing": [{"target", "path" | null}], "backlinks": [caminhos], "broken": [alvos]}
        inexistente : exit 2
    warnings (--json) : cita o caminho de cada nota com frontmatter inválido ou que não é UTF-8; o comando segue.
    Ignorados: .obsidian/, .trash/, a pasta layout.templates e o que não é .md. Os comandos só leem o vault.
"""
import json
import random
import re
import time
import unittest

from brain_support import Sandbox, output, snapshot
from test_cli import CliTestCase

CONTEXTS = ("--context", "college=projects/college:College", "--context", "work=areas/work:Work")

NOTES = {
    "projects/college/redes.md": (
        "---\ntitle: Redes de computadores\ntype: aula\ntags: [redes]\n---\n"
        "Protocolo TCP e roteamento entre sub-redes. Ver [[deploy]].\n"
    ),
    "projects/college/banco.md": (
        "---\ntitle: Banco de dados\ntype: aula\ntags: [dados]\n---\n"
        "Protocolo de replicação entre servidores e índices.\n"
    ),
    "areas/work/deploy.md": (
        "---\ntitle: Deploy do serviço\ntype: reuniao\ntags: [redes, devops]\n---\n"
        "Protocolo de deploy no kubernetes com a equipe.\n"
    ),
    "resources/geral.md": (
        "---\ntitle: Referência HTTP\ntype: referencia\n---\n"
        "O protocolo HTTP em detalhes. #devops\n"
    ),
}
RESULT_KEYS = {"path", "title", "score", "snippet", "context", "type"}


class SearchCliTestCase(CliTestCase):
    def make_vault(self, notes=NOTES):
        self.box.vault.mkdir(parents=True)
        out = self.box.init(*CONTEXTS)
        self.assertExit(out, 0)
        self.write(notes)

    def write(self, notes):
        for rel, text in notes.items():
            path = self.box.vault / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(text, bytes):
                path.write_bytes(text)
            else:
                path.write_text(text, encoding="utf-8")

    def json_of(self, *args, code=0):
        out = self.box.run(*args, "--json")
        self.assertExit(out, code)
        try:
            return json.loads(out.stdout)
        except ValueError:
            self.fail(f"saída não é JSON: {output(out)}")

    def search_paths(self, *args):
        return [r["path"] for r in self.json_of("search", *args)["results"]]

    def assertDescending(self, results):
        scores = [r["score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True), results)


class SearchCliTest(SearchCliTestCase):
    def test_search_filters_json_text_and_no_results(self):
        """SPEC-0018:IT-01"""
        self.make_vault()
        data = self.json_of("search", "protocolo")
        self.assertEqual(data["query"], "protocolo")
        self.assertIsInstance(data["warnings"], list)
        self.assertCountEqual([r["path"] for r in data["results"]], list(NOTES))
        self.assertDescending(data["results"])
        for result in data["results"]:
            with self.subTest(path=result["path"]):
                self.assertTrue(RESULT_KEYS <= set(result), result)
                self.assertLessEqual(len(result["snippet"]), 160)
                self.assertIn("protocolo", result["snippet"].lower())
        by_path = {r["path"]: r for r in data["results"]}
        self.assertEqual(by_path["projects/college/redes.md"]["title"], "Redes de computadores")
        self.assertEqual(by_path["projects/college/redes.md"]["context"], "college")
        self.assertEqual(by_path["areas/work/deploy.md"]["context"], "work")
        self.assertEqual(by_path["areas/work/deploy.md"]["type"], "reuniao")

        self.assertCountEqual(self.search_paths("protocolo", "--context", "college"),
                              ["projects/college/redes.md", "projects/college/banco.md"])
        self.assertEqual(self.search_paths("protocolo", "--type", "reuniao"), ["areas/work/deploy.md"])
        self.assertCountEqual(self.search_paths("protocolo", "--tag", "devops"),
                              ["areas/work/deploy.md", "resources/geral.md"])
        self.assertEqual(self.search_paths("protocolo", "--context", "college", "--type", "reuniao"), [])
        self.assertEqual(len(self.search_paths("protocolo", "--limit", "1")), 1)

        out = self.box.run("search", "kubernetes")
        self.assertExit(out, 0)
        self.assertRegex(out.stdout, r"(?m)^\s*\d+(?:[.,]\d+)?\s+areas/work/deploy\.md\s+—\s+Deploy do serviço\s*$")
        self.assertNotIn("projects/college/redes.md", out.stdout)

        out = self.box.run("search", "xyzinexistente")
        self.assertExit(out, 0)
        self.assertIn("Nenhuma nota encontrada para: xyzinexistente", output(out))

    def test_search_without_local_configuration_exits_3(self):
        """SPEC-0018:IT-01"""
        out = self.box.run("search", "protocolo", config_home=self.box.root / "sem-config")
        self.assertExit(out, 3)
        self.assertNotIn("invalid choice", output(out))


class RelatedCliTest(SearchCliTestCase):
    def test_related_by_note_by_text_and_missing_note(self):
        """SPEC-0018:IT-02"""
        self.make_vault()
        results = self.json_of("related", "--note", "projects/college/redes.md")["results"]
        found = [r["path"] for r in results]
        self.assertTrue(found, "related --note sem resultados")
        self.assertNotIn("projects/college/redes.md", found)
        self.assertDescending(results)
        for result in results:
            with self.subTest(path=result["path"]):
                self.assertTrue({"path", "title", "score", "reasons"} <= set(result), result)
                self.assertTrue(result["reasons"], result)
        self.assertIn("areas/work/deploy.md", found)
        self.assertIn("projects/college/banco.md", found)
        deploy = results[found.index("areas/work/deploy.md")]
        self.assertIn("link direto", deploy["reasons"])
        self.assertTrue(any(r.startswith("tags:") and "redes" in r for r in deploy["reasons"]), deploy)
        banco = results[found.index("projects/college/banco.md")]
        self.assertIn("mesmo contexto", banco["reasons"])

        results = self.json_of("related", "--text", "protocolo no kubernetes")["results"]
        self.assertTrue(results, "related --text sem resultados")
        self.assertEqual(results[0]["path"], "areas/work/deploy.md", results)
        self.assertDescending(results)
        self.assertTrue(any(r.startswith("termos:") for r in results[0]["reasons"]), results[0])

        out = self.box.run("related", "--note", "projects/college/redes.md")
        self.assertExit(out, 0)
        self.assertIn("areas/work/deploy.md", out.stdout)

        out = self.box.run("related", "--note", "inexistente.md")
        self.assertExit(out, 2)
        self.assertIn("nota não encontrada: inexistente.md", output(out))


LINK_NOTES = {
    "resources/hub.md": "# Hub\n\nVeja [[Alvo|o alvo]] e [[Fantasma#parte]].\n",
    "resources/Alvo.md": "# Alvo\n\nSem links.\n",
    "inbox/fan1.md": "# Fã 1\n\nAponta para [[hub]].\n",
    "projects/fan2.md": "# Fã 2\n\nAponta para [[resources/hub]].\n",
}


class LinksCliTest(SearchCliTestCase):
    def test_links_outgoing_backlinks_and_broken_by_path_and_name(self):
        """SPEC-0018:IT-03"""
        self.make_vault(LINK_NOTES)
        expected_out = [{"target": "Alvo", "path": "resources/Alvo.md"}, {"target": "Fantasma", "path": None}]
        for ref in ("resources/hub.md", "hub"):
            with self.subTest(ref=ref):
                data = self.json_of("links", ref)
                self.assertEqual(data["outgoing"], expected_out)
                self.assertCountEqual(data["backlinks"], ["inbox/fan1.md", "projects/fan2.md"])
                self.assertEqual(data["broken"], ["Fantasma"])
        out = self.box.run("links", "hub")
        self.assertExit(out, 0)
        self.assertIn("Fantasma", out.stdout)
        out = self.box.run("links", "inexistente")
        self.assertExit(out, 2)
        self.assertNotIn("invalid choice", output(out))


INVALID_NOTES = {
    "inbox/quebrada.md": "---\ntitle: [sem fechar\n---\nTexto com palavrachave.\n",
    "inbox/latin.md": "# Ação\n\nTexto em latin-1 com palavrachave e acentuação.\n".encode("latin-1"),
    "resources/boa.md": "# Boa\n\nNota válida com palavrachave.\n",
    ".obsidian/plugin.md": "palavrachave do obsidian\n",
    ".trash/apagada.md": "palavrachave na lixeira\n",
    "templates/modelo.md": "palavrachave no template\n",
    "resources/dados.txt": "palavrachave fora de nota\n",
}


class InvalidNotesCliTest(SearchCliTestCase):
    def test_invalid_notes_become_warnings_and_ignored_folders_never_appear(self):
        """SPEC-0018:IT-04"""
        self.make_vault(INVALID_NOTES)
        before = snapshot(self.box.vault)
        data = self.json_of("search", "palavrachave")
        found = [r["path"] for r in data["results"]]
        self.assertCountEqual(found, ["inbox/quebrada.md", "inbox/latin.md", "resources/boa.md"])
        warnings = json.dumps(data["warnings"], ensure_ascii=False)
        self.assertIn("inbox/quebrada.md", warnings)
        self.assertIn("inbox/latin.md", warnings)
        self.assertNotIn("resources/boa.md", warnings)
        for args in (("related", "--text", "palavrachave"), ("related", "--note", "resources/boa.md")):
            with self.subTest(args=args):
                related = [r["path"] for r in self.json_of(*args)["results"]]
                for path in related:
                    self.assertFalse(re.match(r"(\.obsidian|\.trash|templates)/", path), related)
                    self.assertTrue(path.endswith(".md"), related)
        out = self.box.run("links", "plugin")
        self.assertExit(out, 2)
        self.assertEqual(snapshot(self.box.vault), before, "search, related e links não escrevem no vault")


PERF_NOTES = 5000
PERF_LIMIT = 2.0


class PerformanceCliTest(unittest.TestCase):
    """RNF de desempenho: vault de 5.000 notas de ~1 KB, cada comando em menos de 2 s (time.monotonic)."""

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox()
        cls.box.vault.mkdir(parents=True)
        out = cls.box.init(*CONTEXTS)
        if out.returncode != 0:
            cls.box.cleanup()
            raise AssertionError(f"init falhou ({out.returncode}): {output(out)}")
        rng = random.Random(18)
        words = [f"termo{i}" for i in range(3000)]
        folders = ("projects/college", "areas/work", "resources", "inbox", "archive")
        tags = [f"tag{i}" for i in range(50)]
        for i in range(PERF_NOTES):
            folder = folders[i % len(folders)]
            body = []
            while sum(len(w) + 1 for w in body) < 900:
                body.append(rng.choice(words))
            links = " ".join(f"[[nota{rng.randrange(PERF_NOTES)}]]" for _ in range(3))
            text = (f"---\ntitle: Nota {i} {rng.choice(words)}\ntype: note\n"
                    f"tags: [{rng.choice(tags)}, {rng.choice(tags)}]\n---\n"
                    f"{' '.join(body)}\n\n{links}\n")
            path = cls.box.vault / folder / f"nota{i}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.box.cleanup()

    def timed(self, *args):
        start = time.monotonic()
        out = self.box.run(*args)
        elapsed = time.monotonic() - start
        self.assertEqual(out.returncode, 0, output(out))
        self.assertNotIn("Traceback", output(out))
        return out, elapsed

    def test_search_and_related_take_under_2_seconds_on_5000_notes(self):
        """SPEC-0018:IT-05"""
        for args in (("search", "termo42 termo7"),
                     ("search", "termo42", "--json"),
                     ("related", "--note", "resources/nota2.md", "--json"),
                     ("related", "--text", "termo42 termo7 termo1999", "--json")):
            with self.subTest(args=args):
                out, elapsed = self.timed(*args)
                self.assertLess(elapsed, PERF_LIMIT, f"{' '.join(args)} levou {elapsed:.2f} s")
                if "--json" in args:
                    self.assertTrue(json.loads(out.stdout)["results"], "sem resultados no vault de 5.000 notas")


if __name__ == "__main__":
    unittest.main()
