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
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import SCRIPT, SKILL, TESTS, Sandbox, fn, output, snapshot

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


# --------------------------------------------------------------------------- revisão G4 1 (regressão)

TOKEN = "ghp_" + "Zx9" * 12
TOKEN_PART = "Zx9Zx9"  # nem um pedaço do valor pode aparecer
SLACK_IDS = {  # ids de coletor válidos (^[a-z0-9-]+$) que são tokens do Slack
    "failed": "xoxb-" + "1111111111" + "-aaaaaaaaaa",
    "stale": "xoxp-" + "2222222222" + "-bbbbbbbbbb",
    "never": "xoxa-" + "3333333333" + "-cccccccccc",
}
SLACK_PARTS = ("1111111111", "2222222222", "3333333333")
CLI_TIMEOUT = 30
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
# Linux respeita RLIMIT_AS: o lint que lesse /dev/zero esgotaria a memória da máquina antes do timeout
MEMORY_CAP = 1024 * 1024 * 1024 if sys.platform.startswith("linux") else None


def _cap_memory():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_CAP, MEMORY_CAP))


def run_cli(sandbox, *args, timeout=CLI_TIMEOUT):
    """Como Sandbox.run, mas com tempo máximo: um lint que trava (FIFO, /dev/zero) falha o teste em vez de travar."""
    environ = dict(os.environ, HOME=str(sandbox.home), ATLAS_CONFIG_HOME=str(sandbox.config_home))
    try:
        return subprocess.run([sys.executable, str(SCRIPT), *[str(a) for a in args]], check=False, cwd=sandbox.root,
                              capture_output=True, text=True, env=environ, timeout=timeout,
                              preexec_fn=_cap_memory if MEMORY_CAP else None)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"lint não terminou em {timeout} s") from None


class LeakCase(LintCase):
    def lint_all(self, code=None):
        """(texto, json) do lint pela CLI; nenhum dos dois pode ter traceback."""
        text = run_cli(self.sandbox, "lint")
        as_json = run_cli(self.sandbox, "lint", "--json")
        for result in (text, as_json):
            self.assertNotIn("Traceback", output(result), output(result))
            if code is not None:
                self.assertEqual(result.returncode, code, output(result))
        return text, as_json

    def assert_no_secret(self, results, parts):
        for result in results:
            for part in parts:
                self.assertNotIn(part, output(result), f"um pedaço do segredo apareceu na saída: {part}")

    def config_lines(self, text):
        return [m for m in finding_lines(text) if m.group(2) == "config"]


class NoValueAnywhereTest(LeakCase):
    def test_convention_named_with_a_token_never_shows_it(self):
        """SPEC-0039:IT-02 (revisão G4: caminho, detalhe e sugestão nunca têm o valor)"""
        text = INFERRED.read_text(encoding="utf-8").replace("id: merge-method-squash", f"id: {TOKEN}")
        (self.atlas / "conventions" / f"{TOKEN}.md").write_text(text, encoding="utf-8")
        text_out, json_out = self.lint_all(code=1)
        self.assert_no_secret((text_out, json_out), (TOKEN, TOKEN_PART))
        rules = {x["rule"] for x in json.loads(json_out.stdout)["findings"]}
        self.assertIn("pending-convention", rules)
        self.assertIn("secret-leak", rules)  # o nome do arquivo é um segredo

    def test_collector_ids_that_are_tokens_never_show(self):
        """SPEC-0039:IT-02 (revisão G4: id de coletor failed, stale e nunca escaneado)"""
        config = self.atlas / "atlas-config.yml"
        block = "".join(f"  - id: {cid}\n    category: code\n    command: [\"python3\", \"-c\", \"print(1)\"]\n"
                        for cid in SLACK_IDS.values())
        config.write_text(config.read_text(encoding="utf-8").replace("collectors:\n", "collectors:\n" + block, 1),
                          encoding="utf-8")
        today = utc_today().isoformat()
        state = scan_state(facts=(today, "ok"), signals=(today, "ok"))
        state[SLACK_IDS["failed"]] = {"seen_at": today, "status": "failed", "entities": 0, "relations": 0}
        state[SLACK_IDS["stale"]] = {"seen_at": days_before(40, today), "status": "ok", "entities": 0, "relations": 0}
        self.set_scan(state)
        text_out, json_out = self.lint_all(code=1)
        self.assert_no_secret((text_out, json_out), (*SLACK_IDS.values(), *SLACK_PARTS))
        rules = [x["rule"] for x in json.loads(json_out.stdout)["findings"]]
        self.assertIn("failed-collector", rules)
        self.assertGreaterEqual(rules.count("stale"), 2, rules)  # o velho e o nunca escaneado


class SharedConfigProblemsTest(LeakCase):
    def setUp(self):
        super().setUp()
        path = self.atlas / "services" / "search.md"
        text = path.read_text(encoding="utf-8")
        self.secret_line = text.count("\n") + 1
        path.write_text(text + f"nota: {TOKEN}\n", encoding="utf-8")
        self.config = self.atlas / "atlas-config.yml"

    def assert_config_error_and_lint_goes_on(self):
        text_out, json_out = self.lint_all(code=1)
        self.assert_no_secret((text_out, json_out), (TOKEN, TOKEN_PART))
        self.assertTrue([m for m in self.config_lines(text_out.stdout) if m.group(3).startswith("atlas-config.yml")],
                        text_out.stdout)
        self.assertTrue([m for m in finding_lines(text_out.stdout)
                         if m.group(2) == "secret-leak" and m.group(3) == f"services/search.md:{self.secret_line}"],
                        f"o lint parou no atlas-config.yml:\n{text_out.stdout}")
        data = json.loads(json_out.stdout)
        self.assertTrue([x for x in data["findings"] if x["rule"] == "config"
                         and x["path"].startswith("atlas-config.yml")])

    def test_invalid_yaml_with_a_token_is_a_config_error(self):
        """SPEC-0039:UT-02 (revisão G4: YAML inválido com segredo)"""
        self.config.write_text(self.config.read_text(encoding="utf-8")
                               + f'organization: "Acme {TOKEN}\nmode: [local\n', encoding="utf-8")
        self.assert_config_error_and_lint_goes_on()

    def test_non_utf8_config_is_a_config_error(self):
        """SPEC-0039:UT-02 (revisão G4: atlas-config.yml não UTF-8)"""
        self.config.write_bytes(self.config.read_bytes() + b"# \xff\xfe\n")
        self.assert_config_error_and_lint_goes_on()

    @unittest.skipIf(IS_ROOT or os.name != "posix", "chmod 000 não impede a leitura (root ou sem POSIX)")
    def test_unreadable_config_is_a_config_error(self):
        """SPEC-0039:UT-02 (revisão G4: atlas-config.yml sem permissão de leitura)"""
        os.chmod(self.config, 0)
        self.addCleanup(os.chmod, self.config, 0o644)
        self.assert_config_error_and_lint_goes_on()

    def test_missing_config_is_a_config_error(self):
        """SPEC-0039:IT-01 (revisão G4: atlas-config.yml ausente; a configuração local só dá o caminho)"""
        self.config.unlink()
        self.assert_config_error_and_lint_goes_on()


class SpecialFilesTest(LeakCase):
    """Nada que não seja arquivo comum é lido nem seguido: vira achado config com o caminho."""

    def outside(self):
        folder = self.sandbox.root / "outside"
        folder.mkdir(exist_ok=True)
        (folder / "secret.md").write_text(f"token: {TOKEN}\n", encoding="utf-8")
        return folder

    def symlink(self, target, rel):
        link = self.atlas / rel
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as e:
            self.skipTest(f"sem symlink: {e}")
        return link

    def assert_named_and_not_read(self, rel):
        text_out, json_out = self.lint_all()
        self.assertEqual(text_out.returncode, 1, output(text_out))
        self.assert_no_secret((text_out, json_out), (TOKEN, TOKEN_PART))
        configs = [x for x in json.loads(json_out.stdout)["findings"] if x["rule"] == "config"]
        self.assertTrue([x for x in configs if x["path"] == rel or x["path"].startswith(rel + "/")], configs)
        leaks = [x for x in json.loads(json_out.stdout)["findings"]
                 if x["rule"] == "secret-leak" and x["path"].startswith(rel)]
        self.assertEqual(leaks, [], f"{rel} foi lido")

    def test_symlink_to_a_file_outside_the_atlas(self):
        """SPEC-0039:UT-02 (revisão G4: symlink para fora do atlas)"""
        self.symlink(self.outside() / "secret.md", "services/outside.md")
        self.assert_named_and_not_read("services/outside.md")

    def test_symlink_to_dev_zero(self):
        """SPEC-0039:UT-02 (revisão G4: symlink para /dev/zero termina logo)"""
        if not Path("/dev/zero").exists():
            self.skipTest("sem /dev/zero")
        if MEMORY_CAP is None:
            self.skipTest("sem limite de memória por processo nesta plataforma: ler /dev/zero esgotaria a máquina")
        self.symlink("/dev/zero", "process/zero.md")
        self.assert_named_and_not_read("process/zero.md")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "sem FIFO nesta plataforma")
    def test_fifo(self):
        """SPEC-0039:UT-02 (revisão G4: FIFO não é lido)"""
        os.mkfifo(self.atlas / "process" / "pipe.md")
        self.assert_named_and_not_read("process/pipe.md")

    def test_symlinked_directory(self):
        """SPEC-0039:UT-02 (revisão G4: pasta por symlink não é seguida)"""
        self.symlink(self.outside(), "platform/linked")
        self.assert_named_and_not_read("platform/linked")


@unittest.skipIf(IS_ROOT or os.name != "posix", "chmod 000 não impede a leitura (root ou sem POSIX)")
class UnreadableDirectoryTest(LeakCase):
    def test_unreadable_directory_is_a_config_finding(self):
        """SPEC-0039:UT-02 (revisão G4: pasta sem permissão)"""
        private = self.atlas / "process" / "private"
        private.mkdir()
        (private / "notes.md").write_text("notas\n", encoding="utf-8")
        os.chmod(private, 0)
        self.addCleanup(os.chmod, private, 0o755)
        for args in ((), ("--only", "secret-leak,config")):
            with self.subTest(args=args):
                result = run_cli(self.sandbox, "lint", "--json", *args)
                self.assertNotIn("Traceback", output(result), output(result))
                self.assertEqual(result.returncode, 1, output(result))
                configs = [x for x in json.loads(result.stdout)["findings"] if x["rule"] == "config"]
                self.assertTrue([x for x in configs if x["path"].startswith("process/private")], configs)


class SecretNamesAndBytesTest(unittest.TestCase):
    def test_secret_in_a_file_or_directory_name_is_a_masked_secret_leak(self):
        """SPEC-0039:UT-01 (revisão G4: segredo no nome do arquivo ou da pasta)"""
        copy = Copy(self)
        (copy.path("process") / f"{TOKEN}.md").write_text("conteúdo limpo\n", encoding="utf-8")
        folder = copy.path("process") / SLACK_IDS["failed"]
        folder.mkdir()
        (folder / "notes.md").write_text("conteúdo limpo\n", encoding="utf-8")
        findings = of_rule(f("run_lint")(copy.atlas, ["secret-leak"], TODAY), "secret-leak")
        dumped = json.dumps(findings, ensure_ascii=False)
        for part in (TOKEN, TOKEN_PART, SLACK_IDS["failed"], "1111111111"):
            self.assertNotIn(part, dumped)
        paths = [x["path"] for x in findings]
        self.assertTrue([p for p in paths if p.startswith("process/") and "[REDACTED]" in p and "/" not in p[8:]],
                        paths)  # o arquivo
        self.assertTrue([p for p in paths if p.startswith("process/[REDACTED]/")], paths)  # a pasta
        self.assertEqual(len(findings), 2, findings)

    def test_non_utf8_file_is_also_scanned_for_secrets(self):
        """SPEC-0039:UT-01 (revisão G4: arquivo não UTF-8 também é varrido)"""
        copy = Copy(self)
        copy.path("process/binary.md").write_bytes(b"\xff\xfe lixo\nsegunda " + TOKEN.encode() + b"\n")
        findings = f("run_lint")(copy.atlas, ["secret-leak", "config"], TODAY)
        self.assertIn("process/binary.md", [x["path"] for x in of_rule(findings, "config")])
        self.assertEqual([x["path"] for x in of_rule(findings, "secret-leak")], ["process/binary.md:2"])
        self.assertNotIn(TOKEN_PART, json.dumps(findings))

    def test_one_invalid_extra_pattern_does_not_disable_the_valid_ones(self):
        """SPEC-0039:UT-01 (revisão G4: extra_patterns)"""
        copy = Copy(self)
        config = copy.path("atlas-config.yml")
        config.write_text(config.read_text(encoding="utf-8").replace(
            "redaction: {extra_patterns: []}", "redaction: {extra_patterns: ['acme-internal-[0-9]{4}', '(unclosed']}"),
            encoding="utf-8")
        internal = "acme-internal-" + "4321"
        line = copy.append("services/search.md", f"chave interna: {internal}")
        findings = f("run_lint")(copy.atlas, ["secret-leak", "config"], TODAY)
        self.assertEqual([x["path"] for x in of_rule(findings, "secret-leak")], [f"services/search.md:{line}"])
        self.assertTrue([x for x in of_rule(findings, "config") if x["path"] == "atlas-config.yml"])
        self.assertNotIn(internal, json.dumps(findings))


class MalformedShapesTest(unittest.TestCase):
    def lint(self, copy):
        return f("run_lint")(copy.atlas, None, TODAY)

    def test_malformed_graph_and_scan_state_are_config_findings(self):
        """SPEC-0039:UT-02 (revisão G4: formatos inesperados, sem traceback)"""
        cases = {
            "graph.json": (json.dumps({"nodes": [{"key": ["a"]}], "edges": [{"from": ["a"], "to": "x:y"}]}),),
            "graph.json ": (json.dumps("x"),),
            "snapshots/_scan.json": (json.dumps([{"facts": "ok"}]),),
        }
        for rel, (content,) in cases.items():
            with self.subTest(file=rel):
                copy = Copy(self)
                copy.path(rel.strip()).write_text(content, encoding="utf-8")
                findings = self.lint(copy)
                self.assertIn(rel.strip(), [x["path"] for x in of_rule(findings, "config")], findings)

    def test_graph_node_with_a_list_key_does_not_crash_broken_ref(self):
        """SPEC-0039:UT-04 (revisão G4)"""
        copy = Copy(self)
        graph = json.loads(copy.path("graph.json").read_text(encoding="utf-8"))
        graph["nodes"].append({"key": ["service", "x"], "kind": "service"})
        copy.path("graph.json").write_text(json.dumps(graph), encoding="utf-8")
        findings = f("run_lint")(copy.atlas, ["broken-ref", "config"], TODAY)
        self.assertIn("graph.json", [x["path"] for x in findings])


class LinkEdgeCasesTest(unittest.TestCase):
    def test_links_in_code_blocks_are_ignored(self):
        """SPEC-0039:UT-04 (revisão G4: blocos de código)"""
        copy = Copy(self)
        copy.append("services/backoffice.md", "\n```markdown\n[cercado](missing-fenced.md)\n```\n\n"
                                              "    [indentado](missing-indented.md)\n\n~~~\n[til](missing-tilde.md)\n~~~")
        self.assertEqual(of_rule(f("run_lint")(copy.atlas, ["broken-ref"], TODAY), "broken-ref"), [])

    def test_percent_encoded_targets_are_unquoted(self):
        """SPEC-0039:UT-04 (revisão G4: %20)"""
        copy = Copy(self)
        copy.path("process/meu arquivo.md").write_text("# nota\n", encoding="utf-8")
        copy.append("services/backoffice.md", "[existe](../process/meu%20arquivo.md) e [falta](../process/nao%20existe.md)")
        findings = of_rule(f("run_lint")(copy.atlas, ["broken-ref"], TODAY), "broken-ref")
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("nao", findings[0]["detail"])

    def test_targets_outside_the_atlas_root_are_broken(self):
        """SPEC-0039:UT-04 (revisão G4: link que sai da raiz do atlas)"""
        copy = Copy(self)
        (copy.root / "outside.md").write_text("fora do atlas\n", encoding="utf-8")
        copy.append("services/backoffice.md", "[fora](../../outside.md)")
        findings = of_rule(f("run_lint")(copy.atlas, ["broken-ref"], TODAY), "broken-ref")
        self.assertEqual([x["path"] for x in findings], ["services/backoffice.md"], findings)

# --------------------------------------------------------------------------- revisão G4 2 (regressão)

ANCHORED = "'^acme-[0-9a-f]{8}$'"


def acme(hex8):
    return "acme-" + hex8[:4] + hex8[4:]


class AnchoredPatternPathTest(LeakCase):
    """Um extra_pattern ancorado (^...$) casa com um componente do caminho ou com o nome sem extensão; o caminho
    é mascarado do mesmo jeito que é detectado, então o valor nunca aparece."""

    def setUp(self):
        super().setUp()
        config = self.atlas / "atlas-config.yml"
        text = config.read_text(encoding="utf-8")
        self.assertIn("redaction: {extra_patterns: []}", text)
        config.write_text(text.replace("redaction: {extra_patterns: []}",
                                       f"redaction: {{extra_patterns: [{ANCHORED}]}}"), encoding="utf-8")

    def assert_hidden(self, value, *rules):
        text_out, json_out = self.lint_all(code=1)
        hex8 = value[len("acme-"):]
        self.assert_no_secret((text_out, json_out), (value, hex8))
        found = {x["rule"] for x in json.loads(json_out.stdout)["findings"]}
        for rule in ("secret-leak", *rules):
            self.assertIn(rule, found, json_out.stdout)
        self.assertIn("secret-leak", {m.group(2) for m in finding_lines(text_out.stdout)})

    def test_folder_name(self):
        """SPEC-0039:UT-01 (revisão G4 2: pasta process/acme-<hex>/)"""
        value = acme("cafebabe")
        (self.atlas / "process" / value).mkdir()
        (self.atlas / "process" / value / "notes.md").write_text("conteúdo limpo\n", encoding="utf-8")
        self.assert_hidden(value)

    def test_file_without_extension(self):
        """SPEC-0039:UT-01 (revisão G4 2: arquivo sem extensão)"""
        value = acme("deadbeef")
        (self.atlas / "process" / value).write_text("conteúdo limpo\n", encoding="utf-8")
        self.assert_hidden(value)

    def test_file_stem(self):
        """SPEC-0039:IT-02 (revisão G4 2: nome sem a extensão)"""
        value = acme("feedface")
        (self.atlas / "process" / f"{value}.md").write_text("conteúdo limpo\n", encoding="utf-8")
        self.assert_hidden(value)

    def test_inferred_convention_named_with_the_value(self):
        """SPEC-0039:IT-02 (revisão G4 2: convenção inferred com o valor no nome)"""
        value = acme("0badc0de")
        text = INFERRED.read_text(encoding="utf-8").replace("id: merge-method-squash", f"id: {value}")
        (self.atlas / "conventions" / f"{value}.md").write_text(text, encoding="utf-8")
        self.assert_hidden(value, "pending-convention")


@unittest.skipIf(IS_ROOT or os.name != "posix", "chmod 000 não impede a leitura (root ou sem POSIX)")
class LinkIntoUnreadableDirectoryTest(unittest.TestCase):
    def test_links_into_an_unreadable_folder_are_not_reported_missing(self):
        """SPEC-0039:UT-04 (revisão G4 2: pasta ilegível já é achado config)"""
        copy = Copy(self)
        private = copy.path("process/private")
        private.mkdir()
        (private / "notes.md").write_text("notas\n", encoding="utf-8")
        copy.append("services/backoffice.md", "[privado](../process/private/notes.md)")
        os.chmod(private, 0)
        self.addCleanup(os.chmod, private, 0o755)
        findings = f("run_lint")(copy.atlas, ["broken-ref", "config"], TODAY)
        self.assertTrue([x for x in of_rule(findings, "config") if x["path"].startswith("process/private")], findings)
        missing = [x for x in of_rule(findings, "broken-ref") if "private" in x["detail"] and "não existe" in x["detail"]]
        self.assertEqual(missing, [], "link para pasta ilegível reportado como inexistente")

if __name__ == "__main__":
    unittest.main()
