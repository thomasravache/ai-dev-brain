"""Integração pela CLI: lint, --json, --only, só leitura, desempenho, resiliência e a linha do doctor
(SPEC-0023: IT-01 a IT-05).

Cada teste cria o vault com o `brain.py init` real (SPEC-0017, contexto college) num diretório temporário com HOME
e BRAIN_CONFIG_HOME isolados (brain_support.Sandbox); a pasta `files` é <tmp>/Drive/Vault-files. Idade de item da
inbox = mtime (os.utime). Mensagens de erro podem ir para stdout ou stderr.

Saídas que os testes conferem (contrato da seção 6):
    lint [--json] [--only regra1,regra2]
        --json: {"findings": [{"rule", "severity", "path", "detail", "suggestion"}], "summary": {"error": N,
        "warn": M}}; path relativo ao vault com "/". Regras e severidades: broken-link, conflict-copy,
        missing-file e config = "error"; orphan, stale-inbox e frontmatter = "warn".
        texto: uma linha "<SEVERIDADE> <regra> <caminho> — <detalhe> (sugestão: …)" por achado (SEVERIDADE aceita
        como error/erro ou warn/aviso, em qualquer caixa) e o resumo "N erros, M avisos".
        exit 0 sem error; 1 com algum error; --only com regra desconhecida -> exit 2 e a lista das regras.
        Só lê: nada no vault nem na pasta files muda (conteúdo e mtime).
    conflict_patterns (brain-config.yml, lista de regex com o grupo "base"): os vaults do IT-01 gravam os padrões
        genéricos do contrato de forma explícita, para não depender dos padrões conferidos de cada provedor.
        Regex inválido -> achado "config" (detalhe, caminho ou sugestão citam conflict_patterns) e as demais
        regras rodam. Pasta files sem permissão -> achado "config" e a regra missing-file é pulada.
    doctor: linha "OK|AVISO|ERRO lint — N erros, M avisos (rode lint)"; ERRO quando há error (exit 1), AVISO
        quando só há warn, OK sem achados.
"""
import json
import os
import random
import re
import time
import unittest

from brain_support import Sandbox, doctor_lines, output, snapshot
from test_cli import CliTestCase

COLLEGE = ("--context", "college=projects/college:College")
DAY = 86400
RULES = ("broken-link", "conflict-copy", "missing-file", "orphan", "stale-inbox", "frontmatter")
SEVERITY = {"broken-link": "error", "conflict-copy": "error", "missing-file": "error", "config": "error",
            "orphan": "warn", "stale-inbox": "warn", "frontmatter": "warn"}
SEVERITY_WORDS = {"error": "error", "erro": "error", "warn": "warn", "warning": "warn", "aviso": "warn"}
GENERIC_PATTERNS = ("conflict_patterns:\n"
                    "  - '(?P<base>.+) \\(\\d+\\)\\.md$'\n"
                    "  - '(?P<base>.+)[ _-]conflict.*\\.md$'\n")
TEXT_LINE = re.compile(r"^(?P<severity>\S+) (?P<rule>[a-z-]+) (?P<path>.+?) — (?P<detail>.*)\(sugestão: .*\)\s*$")
# o vault do IT-01: um achado por regra (paths relativos ao vault)
EXPECTED = {
    "broken-link": "projects/college/Com link quebrado.md",
    "conflict-copy": "projects/college/Aula (1).md",
    "missing-file": "projects/college/Com anexo.md",
    "orphan": "projects/college/Solta.md",
    "stale-inbox": "inbox/ideia.txt",
    "frontmatter": "projects/college/Sem data.md",
}


def note_text(title, body="", created="2026-10-01", extra=""):
    lines = ["---", "type: note", f"title: {title}", "context: college"]
    if created:
        lines.append(f"created: {created}")
    return "\n".join(lines) + f"\ntags: []\n{extra}---\n\n# {title}\n\n{body or 'Texto de ' + title + '.'}\n"


class LintCliTestCase(CliTestCase):
    def make_vault(self, box=None):
        box = box or self.box
        box.vault.mkdir(parents=True)
        self.assertExit(box.init(*COLLEGE), 0)
        return box

    def put(self, rel, data, age_days=None, base=None):
        path = (base or self.box.vault) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")
        if age_days is not None:
            stamp = time.time() - age_days * DAY
            os.utime(path, (stamp, stamp))
        return path

    def add_config(self, text, box=None):
        path = (box or self.box).vault / "brain-config.yml"
        current = path.read_text(encoding="utf-8")
        path.write_text(current.rstrip("\n") + "\n" + text, encoding="utf-8")

    def full_vault(self):
        """Vault do IT-01: um exemplo de cada regra; as demais notas ligam para o MOC (não são órfãs)."""
        self.make_vault()
        self.add_config(GENERIC_PATTERNS)
        self.put("college/2026/a.pdf", b"%PDF-1.4\n", base=self.box.files)
        self.put("projects/college/Com link quebrado.md",
                 note_text("Com link quebrado", "Ver [[college]] e [[Inexistente]]."))
        aula = note_text("Aula", "Aula de cálculo, ver [[college]].")
        self.put("projects/college/Aula.md", aula)
        self.put("projects/college/Aula (1).md", aula)
        self.put("projects/college/Com anexo.md",
                 note_text("Com anexo", "Slides em anexo; ver [[college]].",
                           extra="files: [college/2026/a.pdf, college/2026/x.pdf]\n"))
        self.put("projects/college/Solta.md", note_text("Solta", "Nota sem nenhum link."))
        self.put("inbox/ideia.txt", "ideia parada na inbox\n", age_days=10)
        self.put("projects/college/Sem data.md", note_text("Sem data", "Ver [[college]].", created=None))

    def lint_json(self, *args, box=None, code=None):
        out = (box or self.box).run("lint", "--json", *args)
        if code is not None:
            self.assertExit(out, code)
        self.assertNotIn("Traceback", output(out))
        try:
            data = json.loads(out.stdout)
        except ValueError:
            self.fail(f"lint --json não imprimiu JSON: {output(out)}")
        self.assertIsInstance(data, dict, data)
        self.assertIsInstance(data.get("findings"), list, data)
        self.assertIsInstance(data.get("summary"), dict, data)
        for item in data["findings"]:
            self.assertTrue({"rule", "severity", "path", "detail", "suggestion"} <= set(item), item)
        return data

    def by_rule(self, data):
        rules = {}
        for item in data["findings"]:
            rules.setdefault(item["rule"], []).append(item)
        return rules


class LintReportTest(LintCliTestCase):
    def test_one_finding_per_rule_with_the_contract_severity_and_exit_1(self):
        """SPEC-0023:IT-01"""
        self.full_vault()
        data = self.lint_json(code=1)
        rules = self.by_rule(data)
        self.assertEqual(sorted(rules), sorted(RULES), data["findings"])
        for rule, path in EXPECTED.items():
            with self.subTest(rule=rule):
                self.assertEqual(len(rules[rule]), 1, rules[rule])
                item = rules[rule][0]
                self.assertEqual(item["severity"], SEVERITY[rule], item)
                self.assertEqual(item["path"], path, item)
                self.assertTrue(item["detail"].strip(), item)
        self.assertIn("Inexistente", rules["broken-link"][0]["detail"])
        self.assertIn("college/2026/x.pdf", rules["missing-file"][0]["detail"])
        self.assertEqual({k: data["summary"].get(k) for k in ("error", "warn")}, {"error": 3, "warn": 3})


class LintReadOnlyTest(LintCliTestCase):
    def test_lint_only_reads_and_prints_the_text_report(self):
        """SPEC-0023:IT-02"""
        self.full_vault()
        vault_before, files_before = snapshot(self.box.vault), snapshot(self.box.files)
        out = self.box.run("lint")
        self.assertExit(out, 1)
        lines = [m.groupdict() for m in map(TEXT_LINE.match, out.stdout.splitlines()) if m]
        self.assertEqual(sorted(line["rule"] for line in lines), sorted(RULES), out.stdout)
        for line in lines:
            with self.subTest(rule=line["rule"]):
                self.assertEqual(SEVERITY_WORDS.get(line["severity"].lower()), SEVERITY[line["rule"]], line)
                self.assertEqual(line["path"], EXPECTED[line["rule"]], line)
        self.assertIn("3 erros, 3 avisos", out.stdout)
        self.lint_json(code=1)
        self.lint_json("--only", "broken-link", code=1)
        self.assertEqual(snapshot(self.box.vault), vault_before, "lint não muda nada no vault")
        self.assertEqual(snapshot(self.box.files), files_before, "lint não muda nada na pasta files")

    def test_only_runs_the_given_rules(self):
        """SPEC-0023:IT-02"""
        self.full_vault()
        data = self.lint_json("--only", "broken-link", code=1)
        self.assertEqual([(i["rule"], i["path"]) for i in data["findings"]], [("broken-link", EXPECTED["broken-link"])])
        self.assertEqual({k: data["summary"].get(k) for k in ("error", "warn")}, {"error": 1, "warn": 0})
        out = self.box.run("lint", "--only", "broken-link")
        self.assertExit(out, 1)
        for rule in RULES[1:]:
            self.assertNotIn(f" {rule} ", out.stdout, f"--only broken-link mostrou {rule}")
        self.assertRegex(out.stdout, r"\b1 erros?, 0 avisos\b")
        data = self.lint_json("--only", "orphan,stale-inbox", code=0)
        self.assertEqual(sorted(i["rule"] for i in data["findings"]), ["orphan", "stale-inbox"])

    def test_only_with_an_unknown_rule_exits_2_with_the_list(self):
        """SPEC-0023:IT-02"""
        self.full_vault()
        for value in ("foo", "broken-link,foo"):
            with self.subTest(only=value):
                out = self.box.run("lint", "--only", value)
                self.assertExit(out, 2)
                self.assertIn("foo", output(out))
                for rule in RULES:
                    self.assertIn(rule, output(out), "a mensagem lista as regras")

    def test_clean_vault_prints_zero_errors_zero_warnings_and_exits_0(self):
        """SPEC-0023:IT-02"""
        self.make_vault()
        before = snapshot(self.box.vault)
        out = self.box.run("lint")
        self.assertExit(out, 0)
        self.assertIn("0 erros, 0 avisos", out.stdout)
        data = self.lint_json(code=0)
        self.assertEqual(data["findings"], [])
        self.assertEqual({k: data["summary"].get(k) for k in ("error", "warn")}, {"error": 0, "warn": 0})
        self.assertEqual(snapshot(self.box.vault), before)


class LintResilienceTest(LintCliTestCase):
    def test_invalid_conflict_pattern_is_a_config_finding_and_the_other_rules_run(self):
        """SPEC-0023:IT-04"""
        self.make_vault()
        self.add_config('conflict_patterns: ["("]\n')
        self.put("projects/college/Com link quebrado.md",
                 note_text("Com link quebrado", "Ver [[college]] e [[Inexistente]]."))
        self.put("projects/college/Solta.md", note_text("Solta", "Nota sem nenhum link."))
        data = self.lint_json(code=1)
        rules = self.by_rule(data)
        self.assertIn("config", rules, data["findings"])
        config = rules["config"]
        self.assertTrue(all(item["severity"] == "error" for item in config), config)
        self.assertTrue(any("conflict_patterns" in item["path"] + item["detail"] + item["suggestion"]
                            for item in config), config)
        self.assertEqual([i["path"] for i in rules.get("broken-link", [])], [EXPECTED["broken-link"]])
        self.assertEqual([i["path"] for i in rules.get("orphan", [])], [EXPECTED["orphan"]])
        out = self.box.run("lint")
        self.assertExit(out, 1)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root lê pastas sem permissão")
    def test_unreadable_files_folder_is_a_config_finding_and_missing_file_is_skipped(self):
        """SPEC-0023:IT-04"""
        self.make_vault()
        self.put("college/2026/a.pdf", b"%PDF-1.4\n", base=self.box.files)
        self.put("projects/college/Com anexo.md",
                 note_text("Com anexo", "Ver [[college]] e [[Inexistente]].",
                           extra="files: [college/2026/x.pdf]\n"))
        mode = self.box.files.stat().st_mode
        self.addCleanup(os.chmod, self.box.files, mode)  # roda antes do cleanup do sandbox (ordem inversa)
        os.chmod(self.box.files, 0)
        data = self.lint_json(code=1)
        rules = self.by_rule(data)
        self.assertIn("config", rules, data["findings"])
        self.assertTrue(all(item["severity"] == "error" for item in rules["config"]), rules["config"])
        self.assertNotIn("missing-file", rules, "missing-file é pulada com a pasta files inacessível")
        self.assertEqual([i["path"] for i in rules.get("broken-link", [])], ["projects/college/Com anexo.md"])


class LintDoctorTest(LintCliTestCase):
    def lint_row(self, out):
        rows = [row for row in doctor_lines(out.stdout) if row[1] == "lint"]
        self.assertEqual(len(rows), 1, f"doctor sem uma linha 'lint':\n{out.stdout}")
        return rows[0]

    def test_doctor_shows_the_lint_summary_and_exits_1_with_errors(self):
        """SPEC-0023:IT-05"""
        self.full_vault()
        out = self.box.run("doctor")
        self.assertExit(out, 1)
        self.assertEqual(self.lint_row(out), ("ERRO", "lint", "3 erros, 3 avisos (rode lint)"))

    def test_doctor_lint_line_is_aviso_with_only_warnings_and_ok_when_clean(self):
        """SPEC-0023:IT-05"""
        self.make_vault()
        out = self.box.run("doctor")
        self.assertEqual(self.lint_row(out), ("OK", "lint", "0 erros, 0 avisos (rode lint)"))
        self.put("projects/college/Solta.md", note_text("Solta", "Nota sem nenhum link."))
        self.put("projects/college/Outra solta.md", note_text("Outra solta", "Também sem links."))
        out = self.box.run("doctor")
        self.assertExit(out, 0)
        self.assertEqual(self.lint_row(out), ("AVISO", "lint", "0 erros, 2 avisos (rode lint)"))


PERF_NOTES = 5000
PERF_LIMIT = 3.0


class LintPerformanceTest(unittest.TestCase):
    """RNF de desempenho: lint num vault de 5.000 notas de ~1 KB em menos de 3 s (time.monotonic, uma execução)."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.box.vault.mkdir(parents=True)
        out = self.box.init(*COLLEGE)
        self.assertEqual(out.returncode, 0, output(out))
        config = self.box.vault / "brain-config.yml"
        config.write_text(config.read_text(encoding="utf-8") + GENERIC_PATTERNS, encoding="utf-8")
        rng = random.Random(23)
        words = [f"termo{i}" for i in range(3000)]
        folders = ("projects/college", "areas/work", "resources", "archive")
        for i in range(PERF_NOTES):
            folder = folders[i % len(folders)]
            body = []
            while sum(len(w) + 1 for w in body) < 900:
                body.append(rng.choice(words))
            # alguns alvos não existem (broken-link); a cada 10 notas um anexo ausente (missing-file)
            links = " ".join(f"[[nota{rng.randrange(PERF_NOTES + 200)}]]" for _ in range(3))
            extra = f"files: [college/2026/x{i}.pdf]\n" if i % 10 == 0 else ""
            created = "" if i % 50 == 0 else "created: 2026-10-01\n"
            text = (f"---\ntype: note\ntitle: Nota {i}\n{created}tags: []\n{extra}---\n"
                    f"{' '.join(body)}\n\n{links}\n")
            path = self.box.vault / folder / f"nota{i}.md"
            if i % 100 == 99:  # cópia de conflito da nota anterior, na pasta dela (o total segue 5.000)
                previous = self.box.vault / folders[(i - 1) % len(folders)] / f"nota{i - 1}.md"
                path, text = previous.with_name(f"nota{i - 1} (1).md"), previous.read_text(encoding="utf-8")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        for i in range(20):
            self.put_inbox(f"item{i}.txt", age_days=i)

    def put_inbox(self, name, age_days):
        path = self.box.vault / "inbox" / name
        path.write_text(f"captura {name}\n", encoding="utf-8")
        stamp = time.time() - age_days * DAY
        os.utime(path, (stamp, stamp))

    def test_lint_takes_under_3_seconds_on_5000_notes(self):
        """SPEC-0023:IT-03"""
        start = time.monotonic()
        out = self.box.run("lint", "--json")
        elapsed = time.monotonic() - start
        self.assertIn(out.returncode, (0, 1), output(out))
        self.assertNotIn("Traceback", output(out))
        self.assertLess(elapsed, PERF_LIMIT, f"lint levou {elapsed:.2f} s")
        rules = {item["rule"] for item in json.loads(out.stdout)["findings"]}
        self.assertTrue({"broken-link", "conflict-copy", "missing-file", "stale-inbox", "frontmatter"} <= rules, rules)


if __name__ == "__main__":
    unittest.main()
