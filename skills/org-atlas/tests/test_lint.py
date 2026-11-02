"""lint: só lê o atlas e aponta segredos, configuração inválida, coletores, referências quebradas, convenções
esperando decisão e páginas órfãs (SPEC-0039: UT-01 a UT-06, IT-01 a IT-03 e CT-01).

A fixture tests/fixtures/lint/atlas foi gerada pelos comandos reais (init, scan, build, curate confirm/reject) e
está limpa: todas as convenções decididas, nenhuma referência quebrada, nenhum segredo. Cada caso de regra é
montado numa cópia feita na hora do teste. tests/fixtures/lint/inferred/ guarda uma convenção inferred gerada
pelo curate (SPEC-0037@2) antes da decisão.

Contrato esperado das funções de scripts/atlas.py (o Implementer segue estes testes):

    lint_rules(only=None) -> list[str]
        As regras de --only ("a,b") na ordem do relatório; None = todas. Regra desconhecida = AtlasError(code=2).

    run_lint(atlas: Path, rules=None, today=None) -> list[dict]
        Achados das regras (None = todas), só lendo o atlas; `today` = AAAA-MM-DD (None = hoje em UTC). Cada
        achado: {"rule", "severity": "error" | "warn", "path" (relativo ao atlas; em secret-leak
        "<arquivo>:<linha>"), "detail", "suggestion"}. Erro: secret-leak, config, failed-collector. Aviso: stale,
        broken-ref, pending-convention, orphan-page. Um arquivo ilegível vira achado config e o lint segue.

CLI (seção 6): lint [--json] [--only regra,...]
    "<ERRO|AVISO> <regra> <caminho> — <detalhe> (sugestão: …)" por achado e o resumo "N erros, M avisos";
    exit 0 sem ERRO, 1 com ERRO, 2 com regra desconhecida em --only, 3 sem configuração.

Valores de segredo dos testes são montados em tempo de execução (nunca literais no arquivo).
"""
import datetime
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import SKILL, TESTS, Sandbox, fn, output, snapshot

SPEC = "SPEC-0039"
FIXTURE = TESTS / "fixtures" / "lint" / "atlas"
INFERRED = TESTS / "fixtures" / "lint" / "inferred" / "merge-method-squash.md"
MAINTENANCE = SKILL / "references" / "maintenance.md"
TODAY = "2026-11-02"  # o _scan.json da fixture é deste dia
RULES = ("secret-leak", "config", "failed-collector", "stale", "broken-ref", "pending-convention", "orphan-page")
ERRORS = ("secret-leak", "config", "failed-collector")
LINE_RE = re.compile(r"^(ERRO|AVISO) (\S+) (\S+) — (.+) \(sugestão: .+\)$")
SUMMARY_RE = re.compile(r"^(\d+) erros, (\d+) avisos$", re.MULTILINE)

# mesmos formatos da SPEC-0033 (references/redaction.md), montados na hora
PEM_BODY = "MIIEow" + "IBAAKCAQEA" * 4
SECRETS = {
    "private-key": "-----BEGIN RSA PRIVATE KEY-----\n" + PEM_BODY + "\n-----END RSA PRIVATE KEY-----",
    "url": "postgres://app:" + "s3nh4" + "-fake-0039" + "@db.interno:5432/app",
    "github-pat": "github_pat_" + "A1b2C3d4E5" * 3,
    "github": "ghp_" + "Zx9" * 12,
    "slack": "xoxb-" + "1234567890" + "-abcdefghij",
    "aws-access-key": "AKIA" + "ABCDEFGHIJKLMNOP",
    "jwt": "eyJ" + "a" * 10 + "." + "b" * 10 + "." + "c" * 10,
}
# a parte que nunca pode aparecer na saída
SECRET_CORE = {"private-key": PEM_BODY, "url": "s3nh4-fake-0039", **{k: v for k, v in SECRETS.items()
                                                                    if k not in ("private-key", "url")}}


def f(name):
    return fn(name, SPEC)


def utc_today():
    return datetime.datetime.now(datetime.timezone.utc).date()


def days_before(n, base=TODAY):
    return (datetime.date.fromisoformat(base) - datetime.timedelta(days=n)).isoformat()


def scan_state(**collectors):
    return {cid: {"seen_at": seen, "status": status, "entities": 1, "relations": 0}
            for cid, (seen, status) in collectors.items()}


def of_rule(findings, rule):
    return [x for x in findings if x["rule"] == rule]


def finding_lines(text):
    return [LINE_RE.match(line) for line in text.splitlines() if LINE_RE.match(line)]


class Copy:
    """Cópia da fixture limpa numa pasta temporária."""

    def __init__(self, case):
        self.root = Path(tempfile.mkdtemp()).resolve()
        case.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.atlas = self.root / "acme-atlas"
        shutil.copytree(FIXTURE, self.atlas)

    def path(self, rel):
        return self.atlas / rel

    def append(self, rel, text):
        """Acrescenta texto ao fim do arquivo; devolve o número (1-based) da primeira linha acrescentada."""
        path = self.path(rel)
        old = path.read_text(encoding="utf-8")
        if not old.endswith("\n"):
            old += "\n"
        path.write_text(old + text + "\n", encoding="utf-8")
        return old.count("\n") + 1

    def set_scan(self, state):
        self.path("snapshots/_scan.json").write_text(json.dumps(state), encoding="utf-8")

    def set_summary(self, rel, body):
        path = self.path(rel)
        text = re.sub(r"(<!-- atlas:begin summary -->).*?(<!-- atlas:end summary -->)",
                      lambda m: m.group(1) + "\n" + body + "\n" + m.group(2), path.read_text(encoding="utf-8"),
                      count=1, flags=re.DOTALL)
        path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- unitários


class CleanFixtureTest(unittest.TestCase):
    def test_the_clean_fixture_has_no_finding(self):
        """SPEC-0039:IT-01 (a fixture limpa, pela função)"""
        self.assertEqual(f("run_lint")(FIXTURE, None, TODAY), [])

    def test_lint_rules(self):
        """SPEC-0039:IT-03 (lint_rules)"""
        rules = f("lint_rules")
        self.assertEqual(list(rules(None)), list(RULES))
        self.assertEqual(rules("stale"), ["stale"])
        self.assertEqual(rules("orphan-page,secret-leak"), ["secret-leak", "orphan-page"])
        with self.assertRaises(fn("AtlasError", "SPEC-0032")) as ctx:
            rules("nao-existe")
        self.assertEqual(ctx.exception.code, 2)


class SecretLeakTest(unittest.TestCase):
    def test_each_secret_pattern_is_found_with_file_line_and_type_but_never_the_value(self):
        """SPEC-0039:UT-01"""
        copy = Copy(self)
        expected = {}
        for name, value in SECRETS.items():
            rel = f"process/notes-{name}.md"
            copy.path(rel).write_text("# Notas\n\nTexto do time.\n", encoding="utf-8")
            expected[name] = (rel, copy.append(rel, f"credencial: {value}"))
        findings = of_rule(f("run_lint")(copy.atlas, ["secret-leak"], TODAY), "secret-leak")
        self.assertEqual(len(findings), len(SECRETS), findings)
        for name, (rel, line) in expected.items():
            with self.subTest(pattern=name):
                found = [x for x in findings if x["path"] == f"{rel}:{line}"]
                self.assertEqual(len(found), 1, findings)
                self.assertEqual(found[0]["severity"], "error")
                self.assertIn(f"padrão {name}", found[0]["detail"])
                self.assertTrue(found[0]["suggestion"].strip())
        dumped = json.dumps(findings, ensure_ascii=False)
        for name, core in SECRET_CORE.items():
            self.assertNotIn(core, dumped, f"o valor do padrão {name} apareceu no achado")

    def test_secrets_in_any_file_of_the_atlas_are_found(self):
        """SPEC-0039:UT-01 (todos os arquivos, inclusive configuração, convenções e fatos)"""
        copy = Copy(self)
        token = SECRETS["github"]
        places = {rel: copy.append(rel, f"# {token}" if rel.endswith(".yml") else f"nota: {token}")
                  for rel in ("atlas-config.yml", "conventions/pr-title-conventional.md", "ATLAS.md",
                              "services/search.md")}
        found = {x["path"] for x in of_rule(f("run_lint")(copy.atlas, ["secret-leak"], TODAY), "secret-leak")}
        self.assertEqual(found, {f"{rel}:{line}" for rel, line in places.items()})

    def test_redacted_text_and_ordinary_words_are_not_secrets(self):
        """SPEC-0039:UT-01 (sem falso positivo)"""
        copy = Copy(self)
        copy.append("services/search.md", "token: [REDACTED] e laughs_abcdefghijklmnopqrstuvwxyz ASIAPACIFICNORTHEAST1")
        self.assertEqual(f("run_lint")(copy.atlas, ["secret-leak"], TODAY), [])


class ConfigTest(unittest.TestCase):
    def test_absolute_path_and_unknown_key_are_errors(self):
        """SPEC-0039:UT-02"""
        absolute = Copy(self)
        path = absolute.path("atlas-config.yml")
        path.write_text(path.read_text(encoding="utf-8").replace("{atlas}/facts/graph.json", "/srv/atlas/facts.json"),
                        encoding="utf-8")
        unknown = Copy(self)
        unknown.append("atlas-config.yml", "colectors: []")
        for copy, word in ((absolute, "absoluto"), (unknown, "colectors")):
            with self.subTest(case=word):
                findings = of_rule(f("run_lint")(copy.atlas, ["config"], TODAY), "config")
                self.assertTrue(findings, "nenhum achado config")
                self.assertTrue(all(x["severity"] == "error" for x in findings))
                self.assertTrue([x for x in findings if x["path"].startswith("atlas-config.yml")
                                 and word in x["detail"]], findings)

    def test_unreadable_file_is_a_config_finding_and_lint_goes_on(self):
        """SPEC-0039:UT-02 (seção 5: arquivo ilegível -> config e o lint segue)"""
        copy = Copy(self)
        copy.path("services/ledger.md").write_bytes(b"# ledger\n\xff\xfe n\xe3o \xe9 UTF-8\n")
        copy.path("graph.json").write_text('{"nodes": [', encoding="utf-8")
        shutil.copy(INFERRED, copy.path("conventions/merge-method-squash.md"))
        findings = f("run_lint")(copy.atlas, None, TODAY)
        config_paths = {x["path"] for x in of_rule(findings, "config")}
        self.assertIn("services/ledger.md", config_paths)
        self.assertIn("graph.json", config_paths)
        self.assertEqual([x["path"] for x in of_rule(findings, "pending-convention")],
                         ["conventions/merge-method-squash.md"], "o lint parou no arquivo ilegível")


class CollectorTest(unittest.TestCase):
    def test_failed_collector_is_an_error_and_an_old_one_is_a_warning(self):
        """SPEC-0039:UT-03"""
        copy = Copy(self)
        copy.set_scan(scan_state(facts=(days_before(20), "ok"), signals=(days_before(1), "failed")))
        findings = f("run_lint")(copy.atlas, ["failed-collector", "stale"], TODAY)
        failed, stale = of_rule(findings, "failed-collector"), of_rule(findings, "stale")
        self.assertEqual(len(failed), 1, findings)
        self.assertEqual(len(stale), 1, findings)
        self.assertEqual((failed[0]["severity"], stale[0]["severity"]), ("error", "warn"))
        self.assertIn("signals", failed[0]["detail"])
        self.assertIn("facts", stale[0]["detail"])
        self.assertNotIn("signals", stale[0]["detail"])

    def test_stale_means_more_than_stale_days(self):
        """SPEC-0039:UT-03"""
        copy = Copy(self)
        copy.set_scan(scan_state(facts=(days_before(14), "ok"), signals=(TODAY, "ok")))
        self.assertEqual(f("run_lint")(copy.atlas, ["stale"], TODAY), [])
        copy.set_scan(scan_state(facts=(days_before(15), "ok"), signals=(TODAY, "ok")))
        self.assertEqual(len(f("run_lint")(copy.atlas, ["stale"], TODAY)), 1)


class BrokenRefTest(unittest.TestCase):
    def test_edge_to_a_missing_node_and_link_to_a_missing_page_are_two_warnings(self):
        """SPEC-0039:UT-04"""
        copy = Copy(self)
        graph = json.loads(copy.path("graph.json").read_text(encoding="utf-8"))
        graph["edges"].append({"from": "service:backoffice", "to": "datastore:ghost-db", "type": "depends_on",
                               "sources": ["facts"], "inferred": False})
        graph["edges"].sort(key=lambda e: (e["from"], e["type"], e["to"]))
        copy.path("graph.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        copy.append("services/backoffice.md", "Veja também [o legado](../platform/ghost.md) e [site](https://example.com).")
        findings = of_rule(f("run_lint")(copy.atlas, ["broken-ref"], TODAY), "broken-ref")
        self.assertEqual(len(findings), 2, findings)
        self.assertTrue(all(x["severity"] == "warn" for x in findings))
        self.assertTrue([x for x in findings if x["path"] == "graph.json" and "datastore:ghost-db" in x["detail"]],
                        findings)
        self.assertTrue([x for x in findings if x["path"] == "services/backoffice.md" and "ghost.md" in x["detail"]],
                        findings)


class PendingConventionTest(unittest.TestCase):
    def test_only_the_inferred_convention_is_pending(self):
        """SPEC-0039:UT-05"""
        copy = Copy(self)
        shutil.copy(INFERRED, copy.path("conventions/merge-method-squash.md"))
        findings = of_rule(f("run_lint")(copy.atlas, ["pending-convention"], TODAY), "pending-convention")
        self.assertEqual([(x["path"], x["severity"]) for x in findings],
                         [("conventions/merge-method-squash.md", "warn")])
        self.assertIn("merge-method-squash", findings[0]["detail"] + findings[0]["suggestion"])


class OrphanPageTest(unittest.TestCase):
    def test_page_not_seen_for_more_than_twice_stale_days_is_a_warning(self):
        """SPEC-0039:UT-06"""
        for days, expected in ((30, 1), (29, 1), (28, 0), (20, 0)):
            with self.subTest(days=days):
                copy = Copy(self)
                copy.set_summary("services/search.md", f"_Não visto desde {days_before(days)}._")
                findings = of_rule(f("run_lint")(copy.atlas, ["orphan-page"], TODAY), "orphan-page")
                self.assertEqual(len(findings), expected, findings)
                if expected:
                    self.assertEqual((findings[0]["path"], findings[0]["severity"]), ("services/search.md", "warn"))


# --------------------------------------------------------------------------- integração (CLI)


class LintCase(unittest.TestCase):
    """A fixture limpa copiada para um Sandbox e ligada por init --join, com o _scan.json de hoje (UTC)."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        self.atlas = self.sandbox.atlas
        self.atlas.parent.mkdir(parents=True)
        shutil.copytree(FIXTURE, self.atlas)
        today = utc_today().isoformat()
        self.set_scan(scan_state(facts=(today, "ok"), signals=(today, "ok")))
        out = self.sandbox.run("init", "--join", "--atlas", self.atlas)
        self.assertEqual(out.returncode, 0, output(out))

    def set_scan(self, state):
        (self.atlas / "snapshots" / "_scan.json").write_text(json.dumps(state), encoding="utf-8")

    def lint(self, *args, code=0):
        result = self.sandbox.run("lint", *args)
        self.assertNotIn("Traceback", output(result), output(result))
        self.assertEqual(result.returncode, code, output(result))
        return result

    def summary(self, result):
        match = SUMMARY_RE.search(result.stdout)
        self.assertIsNotNone(match, f"sem o resumo 'N erros, M avisos':\n{output(result)}")
        return int(match.group(1)), int(match.group(2))


class CleanAtlasTest(LintCase):
    def test_clean_atlas_exits_0_with_zero_findings(self):
        """SPEC-0039:IT-01"""
        result = self.lint()
        self.assertEqual(self.summary(result), (0, 0))
        self.assertEqual(finding_lines(result.stdout), [])
        self.assertEqual(json.loads(self.lint("--json").stdout)["findings"], [])

    def test_lint_writes_nothing(self):
        """SPEC-0039:IT-01 (só leitura)"""
        shutil.copy(INFERRED, self.atlas / "conventions" / "merge-method-squash.md")
        before = snapshot(self.atlas)
        self.lint()
        self.lint("--json")
        self.assertEqual(snapshot(self.atlas), before)

    def test_without_configuration_exits_3(self):
        """SPEC-0039:IT-01"""
        result = self.sandbox.run("lint", config_home=self.sandbox.root / "nowhere")
        self.assertNotIn("Traceback", output(result))
        self.assertEqual(result.returncode, 3, output(result))

    def test_reference_documents_every_rule_and_its_suggestion(self):
        """SPEC-0039:IT-01 (references/maintenance.md)"""
        self.assertTrue(MAINTENANCE.is_file(), "references/maintenance.md não existe")
        text = MAINTENANCE.read_text(encoding="utf-8")
        for word in (*RULES, "ERRO", "AVISO", "sugestão", "--only", "--json", "stale_days"):
            self.assertIn(word, text, word)


class SecretInNoteTest(LintCase):
    def test_token_in_a_service_note_exits_1_with_file_and_line_and_no_value(self):
        """SPEC-0039:IT-02"""
        token = SECRETS["github"]
        path = self.atlas / "services" / "backoffice.md"
        text = path.read_text(encoding="utf-8")
        line = text.count("\n") + 1 + (0 if text.endswith("\n") else 1)
        path.write_text(text + ("" if text.endswith("\n") else "\n") + f"Token do bot: {token}\n", encoding="utf-8")
        result = self.lint(code=1)
        self.assertRegex(result.stdout, re.compile(
            rf"^ERRO secret-leak services/backoffice\.md:{line} — .*padrão github.* \(sugestão: .+\)$", re.MULTILINE))
        self.assertEqual(self.summary(result), (1, 0))
        self.assertNotIn(token, output(result))
        as_json = self.lint("--json", code=1)
        self.assertNotIn(token, output(as_json))
        self.assertEqual([x["rule"] for x in json.loads(as_json.stdout)["findings"]], ["secret-leak"])


class OnlyTest(LintCase):
    def setUp(self):
        super().setUp()
        self.set_scan(scan_state(facts=(days_before(20, utc_today().isoformat()), "ok"),
                                 signals=(utc_today().isoformat(), "ok")))
        shutil.copy(INFERRED, self.atlas / "conventions" / "merge-method-squash.md")

    def test_only_stale_shows_only_that_rule(self):
        """SPEC-0039:IT-03"""
        everything = {m.group(2) for m in finding_lines(self.lint().stdout)}
        self.assertEqual(everything, {"stale", "pending-convention"})
        result = self.lint("--only", "stale")
        lines = finding_lines(result.stdout)
        self.assertEqual([(m.group(1), m.group(2)) for m in lines], [("AVISO", "stale")])
        self.assertEqual(self.summary(result), (0, 1))
        both = {m.group(2) for m in finding_lines(self.lint("--only", "stale,pending-convention").stdout)}
        self.assertEqual(both, {"stale", "pending-convention"})

    def test_unknown_rule_exits_2(self):
        """SPEC-0039:IT-03"""
        result = self.lint("--only", "nao-existe", code=2)
        self.assertIn("nao-existe", output(result))
        self.lint("--only", "stale,nao-existe", code=2)

    def test_failed_collector_makes_lint_exit_1(self):
        """SPEC-0039:IT-03 (erro -> exit 1, também filtrado)"""
        self.set_scan(scan_state(facts=(utc_today().isoformat(), "ok"), signals=(utc_today().isoformat(), "failed")))
        result = self.lint("--only", "failed-collector", code=1)
        self.assertEqual([(m.group(1), m.group(2)) for m in finding_lines(result.stdout)],
                         [("ERRO", "failed-collector")])
        self.lint("--only", "pending-convention", code=0)


# --------------------------------------------------------------------------- contrato


class ConventionFilesContractTest(unittest.TestCase):
    """Convenções geradas pelo curate da SPEC-0037@2 num atlas novo (init -> scan -> curate)."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        self.assertEqual(self.sandbox.init(mode="local").returncode, 0)
        self.atlas = self.sandbox.atlas
        shutil.copy(FIXTURE / "atlas-config.yml", self.atlas / "atlas-config.yml")
        shutil.copytree(FIXTURE / "facts", self.atlas / "facts")
        result = self.sandbox.run("scan")
        self.assertEqual(result.returncode, 0, output(result))

    def pending(self):
        result = self.sandbox.run("lint", "--only", "pending-convention", "--json")
        self.assertNotIn("Traceback", output(result), output(result))
        self.assertEqual(result.returncode, 0, output(result))
        return sorted(x["path"] for x in json.loads(result.stdout)["findings"])

    def test_lint_reads_curate_files_and_warns_only_the_inferred(self):
        """SPEC-0039:CT-01"""
        files = sorted(f"conventions/{p.name}" for p in (self.atlas / "conventions").glob("*.md"))
        self.assertEqual(len(files), 5, files)
        self.assertEqual(self.pending(), files)
        for args in (("confirm", "pr-title-conventional", "--by", "thomas", "--via", "PR #3"),
                     ("reject", "pr-template-present", "--by", "ana", "--via", "local")):
            self.assertEqual(self.sandbox.run("curate", *args).returncode, 0)
        decided = {"conventions/pr-title-conventional.md", "conventions/pr-template-present.md"}
        self.assertEqual(self.pending(), sorted(set(files) - decided))


if __name__ == "__main__":
    unittest.main()
