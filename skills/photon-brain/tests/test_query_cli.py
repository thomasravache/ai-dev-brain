"""Integração pela CLI: context, o tipo answer e a jornada de consultar (SPEC-0020: IT-01 a IT-04).

Cada teste cria o vault com o `brain.py init` real (SPEC-0017) e as notas com `new-note`, `relate` e `index`
(SPEC-0019), num diretório temporário com HOME e BRAIN_CONFIG_HOME isolados (brain_support.Sandbox). O corpo das
notas é acrescentado ao arquivo criado pelo new-note, como o agente faz no fluxo de guardar. O IT-04 gera o vault
de 5.000 notas escrevendo os arquivos direto (como o IT-05 da SPEC-0018).

Saídas que os testes conferem (contrato da seção 6; mensagens de erro podem ir para stdout ou stderr):
    context QUERY [--context C] [--hops N=1] [--limit N=8] [--max-chars N=40000] [--json]
        json  : {"query", "notes": [{"path", "title", "reason", "content"}], "omitted": [{"path", "title", "reason"}],
                 "broken": [...]} — reason "moc" | "search:<pontos>" | "link:<distância>"; caminhos relativos ao
                vault com "/"; ordem MOC, busca por pontuação, vizinhos por distância e depois título; sem repetir.
        texto : para cada nota "=== <caminho> (<motivo>) ===" e o conteúdo; no fim "Omitidas:" e "Links quebrados:"
                (os testes só exigem esses rótulos quando há o que listar).
        nada encontrado : "Nenhuma nota encontrada para: QUERY", exit 0
        --hops fora de 0..2 : exit 2, com a mensagem citando hops (o comando context existe: não é "invalid choice")
    Decisão A do Architect (revisão CHANGES_REQUESTED): com --context o MOC entra primeiro, mas nunca é atravessado
        na expansão de vizinhos; notas alcançáveis só pelo MOC (irmãs do contexto, index.md) não entram como link:N.
    new-note --type answer : modelo answer (type: answer, "## Question", "## Answer", "## Gaps", "## Relations").
"""
import json
import random
import re
import time
import unittest

from brain_support import Sandbox, output
from test_store_cli import COLLEGE, StoreCliTestCase, region, today

REASON = re.compile(r"^(moc|search:(\d+(?:[.,]\d+)?)|link:(\d+))$")
NOTE_KEYS = {"path", "title", "reason", "content"}
OMITTED_KEYS = {"path", "title", "reason"}
INTEGRAIS = "projects/college/Integrais por partes.md"
INTEGRAIS_BODY = "Integração por partes: a integral de u dv é u v menos a integral de v du.\n"
PRODUCT = "resources/Regra do produto.md"
PRODUCT_BODY = "A derivada do produto u v é u' v + u v'.\n"
DERIVADAS = "resources/Derivadas.md"
DERIVADAS_BODY = "Taxa de variação instantânea de uma função.\n"
OUTSIDE = "resources/Integrais no escritório.md"
OUTSIDE_BODY = "Planilha de integrais de custos, fora da faculdade.\n"
MOC = "mocs/college.md"
ANSWER = "projects/college/P2 de Cálculo II.md"


class QueryCliTestCase(StoreCliTestCase):
    def build_vault(self):
        """Vault do IT-01: contexto college, MOC e notas ligadas.

        Integrais por partes (college) -> Regra do produto (resources) -> Derivadas (resources); Integrais tem um
        link quebrado; "Integrais no escritório" tem o termo mas fica fora do contexto college.
        """
        self.make_vault(COLLEGE)
        for title, note_type, context, body in (
                ("Integrais por partes", "lecture", "college", INTEGRAIS_BODY + "Ver [[Nota que sumiu]].\n"),
                ("Regra do produto", "note", None, PRODUCT_BODY),
                ("Derivadas", "note", None, DERIVADAS_BODY),
                ("Integrais no escritório", "note", None, OUTSIDE_BODY)):
            args = ["new-note", "--type", note_type, "--title", title]
            if context:
                args += ["--context", context]
            path = self.rel(self.json_of(*args)["path"])
            self.append(path, body)
        self.assertExit(self.box.run("relate", "Integrais por partes", "Regra do produto", "--why", "aplica"), 0)
        self.assertExit(self.box.run("relate", "Regra do produto", "Derivadas", "--why", "usa"), 0)
        self.assertExit(self.box.run("index", "--context", "college"), 0)

    def append(self, rel, body):
        path = self.box.vault / rel
        path.write_text(path.read_text(encoding="utf-8") + "\n" + body, encoding="utf-8")

    def context_json(self, *args):
        data = self.json_of("context", *args)
        self.assertTrue({"query", "notes", "omitted", "broken"} <= set(data), data)
        return data

    def assertContractOrder(self, notes):
        """MOC, depois busca por pontuação decrescente, depois vizinhos por distância e título; sem repetir."""
        paths = [n["path"] for n in notes]
        self.assertEqual(len(paths), len(set(paths)), f"nota repetida: {paths}")
        rank = []
        for note in notes:
            self.assertTrue(NOTE_KEYS <= set(note), note)
            m = REASON.match(note["reason"])
            self.assertTrue(m, f"motivo fora do contrato: {note['reason']!r}")
            if m.group(1) == "moc":
                rank.append((0, 0, ""))
            elif m.group(2) is not None:
                rank.append((1, -float(m.group(2).replace(",", ".")), ""))
            else:
                rank.append((2, int(m.group(3)), note["title"].lower()))
        kinds = [r[0] for r in rank]
        self.assertEqual(kinds, sorted(kinds), f"ordem MOC, busca, vizinhos: {notes}")
        for kind in (1, 2):
            group = [r[1:] for r in rank if r[0] == kind]
            if kind == 1:
                group = [r[0] for r in group]
            self.assertEqual(group, sorted(group), f"ordem dentro do grupo {kind}: {paths}")


class ContextCliTest(QueryCliTestCase):
    def test_context_puts_the_moc_first_then_search_results_then_neighbors(self):
        """SPEC-0020:IT-01"""
        self.build_vault()
        data = self.context_json("integrais", "--context", "college", "--hops", "1")
        self.assertEqual(data["query"], "integrais")
        notes = data["notes"]
        self.assertContractOrder(notes)
        by_path = {n["path"]: n for n in notes}

        self.assertEqual(notes[0]["path"], MOC, notes)
        self.assertEqual(notes[0]["reason"], "moc")
        self.assertEqual(notes[0]["title"], "College")
        self.assertIn("[[Integrais por partes]]", notes[0]["content"])

        self.assertIn(INTEGRAIS, by_path, notes)
        self.assertTrue(by_path[INTEGRAIS]["reason"].startswith("search:"), by_path[INTEGRAIS])
        self.assertEqual(by_path[INTEGRAIS]["title"], "Integrais por partes")
        self.assertIn(INTEGRAIS_BODY.strip(), by_path[INTEGRAIS]["content"], "nota inteira no pacote")

        self.assertIn(PRODUCT, by_path, "vizinho por link de saída, mesmo fora do contexto")
        self.assertEqual(by_path[PRODUCT]["reason"], "link:1")
        self.assertIn(PRODUCT_BODY.strip(), by_path[PRODUCT]["content"])
        self.assertNotIn(DERIVADAS, by_path, "a dois passos não entra com --hops 1")

        for note in notes:
            if note["reason"].startswith("search:"):
                self.assertTrue(note["path"].startswith("projects/college/"), f"busca filtrada por college: {note}")
        self.assertNotEqual(by_path.get(OUTSIDE, {}).get("reason", "").split(":")[0], "search")
        self.assertEqual(data["omitted"], [])
        self.assertTrue(any("Nota que sumiu" in str(item) for item in data["broken"]), data["broken"])

        two = self.context_json("integrais", "--context", "college", "--hops", "2")
        self.assertContractOrder(two["notes"])
        self.assertEqual(two["notes"][0]["path"], MOC)
        self.assertEqual({n["path"]: n["reason"] for n in two["notes"]}.get(DERIVADAS), "link:2", two["notes"])

        small = self.context_json("integrais", "--context", "college", "--max-chars", "10")
        self.assertTrue(small["omitted"], "nada cabe em 10 caracteres")
        for item in small["omitted"]:
            self.assertTrue(OMITTED_KEYS <= set(item), item)
        kept = {n["path"] for n in small["notes"]}
        self.assertFalse(kept & {o["path"] for o in small["omitted"]}, "nota em notes e em omitted")

        out = self.box.run("context", "integrais", "--context", "college")
        self.assertExit(out, 0)
        headers = re.findall(r"(?m)^=== (.+?) \((.+?)\) ===\s*$", out.stdout)
        self.assertTrue(headers, out.stdout)
        self.assertEqual(headers[0], (MOC, "moc"))
        self.assertIn((PRODUCT, "link:1"), headers)
        self.assertIn(INTEGRAIS_BODY.strip(), out.stdout)
        self.assertRegex(out.stdout, r"(?m)^Links quebrados:")
        self.assertIn("Nota que sumiu", out.stdout.split("Links quebrados:", 1)[1])

        out = self.box.run("context", "integrais", "--context", "college", "--max-chars", "10")
        self.assertExit(out, 0)
        self.assertRegex(out.stdout, r"(?m)^Omitidas:")
        self.assertIn(INTEGRAIS, out.stdout.split("Omitidas:", 1)[1])

    def test_context_moc_is_not_traversed_with_two_hops(self):
        """SPEC-0020:IT-01"""
        self.build_vault()
        siblings = []
        for title in ("Séries de Taylor", "Limites laterais"):
            siblings.append(self.rel(self.json_of("new-note", "--type", "lecture", "--title", title,
                                                  "--context", "college")["path"]))
        # Sem created, as notas ficam fora da região "recent" do index.md: assim o index.md só liga ao MOC, e o
        # único caminho de "Integrais por partes" até as irmãs e o index.md passa pelo MOC.
        for rel in [INTEGRAIS, PRODUCT, DERIVADAS, OUTSIDE] + siblings:
            path = self.box.vault / rel
            text = path.read_text(encoding="utf-8")
            path.write_text(re.sub(r"(?m)^created:.*\n", "", text, count=1), encoding="utf-8")
        self.assertExit(self.box.run("index", "--context", "college"), 0)
        moc = self.read(MOC)
        for title in ("Integrais por partes", "Séries de Taylor", "Limites laterais"):
            self.assertIn(f"[[{title}]]", moc, "o MOC lista as irmãs")
        self.assertIn("mocs/college", self.read("index.md"), "o index.md liga ao MOC")
        self.assertNotIn("[[Integrais por partes]]", self.read("index.md"), "index.md não liga direto à nota")

        data = self.context_json("integrais", "--context", "college", "--hops", "2")
        self.assertContractOrder(data["notes"])
        by_path = {n["path"]: n["reason"] for n in data["notes"]}
        listed = set(by_path) | {o["path"] for o in data["omitted"]}
        self.assertEqual(data["notes"][0]["path"], MOC)
        self.assertEqual(data["notes"][0]["reason"], "moc")
        self.assertTrue(by_path.get(INTEGRAIS, "").startswith("search:"), data["notes"])
        self.assertEqual(by_path.get(PRODUCT), "link:1", data["notes"])
        self.assertEqual(by_path.get(DERIVADAS), "link:2", "vizinho real a dois passos, por Regra do produto")
        for rel in siblings + ["index.md"]:
            with self.subTest(path=rel):
                self.assertNotIn(rel, listed, "alcançável só pelo MOC: não entra (decisão A)")

    def test_context_without_results_and_invalid_hops(self):
        """SPEC-0020:IT-02"""
        self.build_vault()
        out = self.box.run("context", "termo-inexistente")
        self.assertExit(out, 0)
        self.assertIn("Nenhuma nota encontrada para: termo-inexistente", output(out))

        data = self.context_json("termo-inexistente")
        self.assertEqual(data["notes"], [])

        for hops in ("3", "-1"):
            with self.subTest(hops=hops):
                out = self.box.run("context", "x", "--hops", hops)
                self.assertExit(out, 2)
                self.assertNotRegex(output(out), r"invalid choice: '(?:context|x)'", "o comando context QUERY precisa existir")
                self.assertIn("hops", output(out))
        for hops in ("0", "2"):
            with self.subTest(hops=hops):
                self.assertExit(self.box.run("context", "integrais", "--hops", hops), 0)


class AnswerCliTest(QueryCliTestCase):
    def test_answer_note_is_saved_related_to_cited_notes_and_indexed(self):
        """SPEC-0020:IT-03"""
        self.build_vault()
        data = self.json_of("new-note", "--type", "answer", "--title", "P2 de Cálculo II", "--context", "college")
        path = self.rel(data["path"])
        self.assertEqual(path, ANSWER)
        text = self.read(path)
        note = self.note(path)
        self.assertEqual(note.frontmatter.get("type"), "answer")
        self.assertEqual(note.frontmatter.get("title"), "P2 de Cálculo II")
        self.assertEqual(note.frontmatter.get("context"), "college")
        self.assertEqual(str(note.frontmatter.get("created")), today())
        positions = []
        for heading in ("# P2 de Cálculo II", "## Question", "## Answer", "## Gaps", "## Relations"):
            m = re.search(rf"(?m)^{re.escape(heading)}\s*$", text)
            self.assertTrue(m, f"nota answer sem {heading}:\n{text}")
            positions.append(m.start())
        self.assertEqual(positions, sorted(positions), "seções na ordem do modelo")
        self.assertNotRegex(text, r"\{(title|date|context|source)\}")

        out = self.box.run("relate", "P2 de Cálculo II", "Integrais por partes", "--why", "cita", "--both")
        self.assertExit(out, 0)
        self.assertIn("- [[Integrais por partes]] — cita", self.read(ANSWER).split("## Relations", 1)[1])
        self.assertIn("- [[P2 de Cálculo II]] — cita", self.read(INTEGRAIS).split("## Relations", 1)[1])

        out = self.box.run("index", "--context", "college")
        self.assertExit(out, 0)
        listed = region(self.read(MOC), "notes").splitlines()
        self.assertIn("- [[P2 de Cálculo II]]", listed)
        self.assertIn("- [[Integrais por partes]]", listed)


PERF_NOTES = 5000
PERF_LIMIT = 2.0
PERF_CONTEXTS = ("--context", "college=projects/college:College", "--context", "work=areas/work:Work")


class ContextPerformanceCliTest(unittest.TestCase):
    """RNF de desempenho: context --hops 2 num vault de 5.000 notas de ~1 KB em menos de 2 s (time.monotonic)."""

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox()
        cls.box.vault.mkdir(parents=True)
        out = cls.box.init(*PERF_CONTEXTS)
        if out.returncode != 0:
            cls.box.cleanup()
            raise AssertionError(f"init falhou ({out.returncode}): {output(out)}")
        rng = random.Random(20)
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
                    f"{' '.join(body)}\n\n{links} [[nota-quebrada-{i}]]\n")
            path = cls.box.vault / folder / f"nota{i}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.box.cleanup()

    def test_context_with_two_hops_takes_under_2_seconds_on_5000_notes(self):
        """SPEC-0020:IT-04"""
        for args in (("termo42 termo7", "--hops", "2", "--json"),
                     ("termo42", "--context", "college", "--hops", "2", "--json")):
            with self.subTest(args=args):
                start = time.monotonic()
                out = self.box.run("context", *args)
                elapsed = time.monotonic() - start
                self.assertEqual(out.returncode, 0, output(out))
                self.assertNotIn("Traceback", output(out))
                self.assertLess(elapsed, PERF_LIMIT, f"context {' '.join(args)} levou {elapsed:.2f} s")
                data = json.loads(out.stdout)
                self.assertTrue(data["notes"], "sem notas no vault de 5.000 notas")
                self.assertLessEqual(sum(len(n["content"]) for n in data["notes"]), 40000, "--max-chars padrão")
                reasons = [n["reason"] for n in data["notes"]] + [o["reason"] for o in data["omitted"]]
                self.assertIn("link:2", reasons, "expansão a dois passos")
                self.assertTrue(data["broken"], "links quebrados listados")


if __name__ == "__main__":
    unittest.main()
