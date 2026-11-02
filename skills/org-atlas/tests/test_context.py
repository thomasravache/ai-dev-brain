"""context: pacote só de leitura do atlas para uma tarefa, com aviso de envelhecimento (SPEC-0038: UT-01 a UT-05,
IT-01 a IT-03 e CT-01). Lê o graph.json (SPEC-0036), as páginas services/*.md e as convenções da SPEC-0037@2.

Contrato esperado das funções de scripts/atlas.py (o Implementer segue estes testes):

    staleness_warnings(scan_state: dict, stale_days: int, today: str) -> list[str]
        Avisos a partir do snapshots/_scan.json: coletor ok com seen_at há mais de stale_days dias ->
        "Atlas com D dias desde o último scan de: A (stale_days: N)"; coletor com status failed ->
        "Último scan falhou: C".

    build_context(atlas: Path, query: str, hops=1, limit=8, max_chars=30000, today=None) -> dict
        Só lê o atlas (graph.json, snapshots/_scan.json, atlas-config.yml, services/*.md, conventions/*.md).
        `today` = AAAA-MM-DD (None = hoje em UTC). Devolve o pacote:
            {"query", "warnings": [str], "services": [{"key", "score", "reason", ...}],
             "dependencies": [{"from", "to", "type", "inferred", "evidence"?}],
             "rules": [{"id", ...}], "hints": [{"id", ...}], "omitted": [...]}
        services = serviços encontrados pela busca (nome, id, atributos e notas das páginas), por pontuação;
        dependencies = arestas até `hops` passos a partir deles; rules = convenções confirmed do escopo
        organization e dos repositórios dos serviços; hints = as inferred do mesmo escopo; rejected nunca.
        O que não cabe em max_chars vai para omitted; os avisos nunca são omitidos. Atlas sem scan =
        pacote vazio com o aviso "atlas ainda sem scan — rode scan".

    render_context(package: dict) -> str
        O pacote em Markdown, nesta ordem (cada seção só quando tem conteúdo): "## Aviso de envelhecimento",
        "## Serviços", "## Dependências", "## Convenções (regra)", "## Convenções (dica)" (marcadas "não
        confirmada"), "## Omitidos" (uma linha "- " por item omitido).

CLI (seção 6): context QUERY [--hops 0..2] [--limit N] [--max-chars N] [--json]
    nada encontrado: "Nada encontrado no atlas para: QUERY" e exit 0; --hops fora de 0..2: exit 2; sem
    configuração: exit 3.
"""
import datetime
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import SKILL, TESTS, Sandbox, fn, output, snapshot

SPEC = "SPEC-0038"
FIXTURE = TESTS / "fixtures" / "context" / "atlas"
CONTEXT_REFERENCE = SKILL / "references" / "context.md"
TODAY = "2026-11-02"  # o _scan.json da fixture é deste dia
WARNING_H = "## Aviso de envelhecimento"
SERVICES_H = "## Serviços"
DEPS_H = "## Dependências"
RULES_H = "## Convenções (regra)"
HINTS_H = "## Convenções (dica)"
OMITTED_H = "## Omitidos"
NO_SCAN = "atlas ainda sem scan — rode scan"
RULE_IDS = {"pr-title-conventional", "branch-prefix-feat-acme-backoffice"}
HINT_IDS = {"merge-method-squash"}
REJECTED = "pr-template-present"
OTHER_REPO = "branch-prefix-fix-acme-r3"  # confirmada, mas de um repositório que não é de serviço encontrado


def f(name):
    return fn(name, SPEC)


def utc_today():
    return datetime.datetime.now(datetime.timezone.utc).date()


def days_ago(n, base=None):
    return ((base or utc_today()) - datetime.timedelta(days=n)).isoformat()


def scan_state(**collectors):
    """facts=("2026-11-02", "ok") -> conteúdo do _scan.json."""
    return {cid: {"seen_at": seen, "status": status, "entities": 1, "relations": 0}
            for cid, (seen, status) in collectors.items()}


def sections(markdown):
    """[(título "## ...", corpo)] na ordem do texto."""
    found, current, lines = [], None, []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if current is not None:
                found.append((current, "\n".join(lines)))
            current, lines = line.strip(), []
        elif current is not None:
            lines.append(line)
    if current is not None:
        found.append((current, "\n".join(lines)))
    return found


def section(markdown, title):
    for heading, body in sections(markdown):
        if heading == title:
            return body
    return None


def first_line(text):
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def deps(package):
    return {(d["from"], d["to"]) for d in package["dependencies"]}


def ids(items):
    return {item["id"] for item in items}


class FixtureCopy:
    """Cópia da fixture numa pasta temporária, com o _scan.json e o stale_days que o teste quiser."""

    def __init__(self, case, state=None, stale_days=None):
        self.root = Path(tempfile.mkdtemp()).resolve()
        case.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.atlas = self.root / "acme-atlas"
        shutil.copytree(FIXTURE, self.atlas)
        if state is not None:
            (self.atlas / "snapshots" / "_scan.json").write_text(json.dumps(state), encoding="utf-8")
        if stale_days is not None:
            path = self.atlas / "atlas-config.yml"
            text = path.read_text(encoding="utf-8").replace("stale_days: 14", f"stale_days: {stale_days}")
            path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- unitários


class SearchTest(unittest.TestCase):
    def test_backoffice_comes_first_with_score_and_reason(self):
        """SPEC-0038:UT-01"""
        package = f("build_context")(FIXTURE, "cashout backoffice", today=TODAY)
        keys = [s["key"] for s in package["services"]]
        self.assertEqual(keys[0], "service:backoffice", package["services"])
        first = package["services"][0]
        self.assertIsInstance(first["score"], (int, float))
        self.assertGreater(first["score"], 0)
        self.assertTrue(isinstance(first["reason"], str) and first["reason"].strip())
        scores = [s["score"] for s in package["services"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertIn("service:ledger", keys)  # "cashout" nos atributos
        self.assertNotIn("service:search", keys)

    def test_service_section_has_page_repository_deployments_and_owners(self):
        """SPEC-0038:UT-01"""
        markdown = f("render_context")(f("build_context")(FIXTURE, "backoffice", today=TODAY))
        body = section(markdown, SERVICES_H)
        self.assertIsNotNone(body, markdown)
        for word in ("services/backoffice.md", "acme/backoffice", "backoffice-prod", "prod", "pay"):
            self.assertIn(word, body)

    def test_notes_of_the_service_page_are_searched(self):
        """SPEC-0038:UT-01"""
        package = f("build_context")(FIXTURE, "lojistas", today=TODAY)  # só na nota do time em backoffice.md
        self.assertEqual([s["key"] for s in package["services"]][:1], ["service:backoffice"])

    def test_build_context_only_reads_the_atlas(self):
        """SPEC-0038:UT-01 (seção 5: só leitura)"""
        before = snapshot(FIXTURE)
        f("build_context")(FIXTURE, "cashout backoffice", hops=2, today=TODAY)
        self.assertEqual(snapshot(FIXTURE), before)


class HopsTest(unittest.TestCase):
    def package(self, hops):
        return f("build_context")(FIXTURE, "backoffice", hops=hops, today=TODAY)

    def test_hops_0_1_and_2(self):
        """SPEC-0038:UT-02"""
        self.assertEqual(deps(self.package(0)), set(), "--hops 0: só o nó")
        one = deps(self.package(1))
        self.assertIn(("service:backoffice", "service:payments"), one)
        self.assertFalse([d for d in one if "datastore:payments-db" in d], "--hops 1 trouxe dois passos")
        two = deps(self.package(2))
        self.assertIn(("service:backoffice", "service:payments"), two)
        self.assertIn(("service:payments", "datastore:payments-db"), two)

    def test_dependencies_show_type_inferred_and_evidence(self):
        """SPEC-0038:UT-02"""
        package = self.package(1)
        edge = next(d for d in package["dependencies"] if (d["from"], d["to"]) == ("service:backoffice",
                                                                                   "service:payments"))
        self.assertEqual((edge["type"], edge["inferred"], edge.get("evidence")),
                         ("depends_on", True, "PAYMENTS_URL=payments"))
        body = section(f("render_context")(package), DEPS_H)
        self.assertIsNotNone(body)
        for word in ("depends_on", "inferida", "PAYMENTS_URL=payments", "payments"):
            self.assertIn(word, body)


class ConventionsTest(unittest.TestCase):
    def test_confirmed_are_rules_inferred_are_hints_and_rejected_never_appear(self):
        """SPEC-0038:UT-03"""
        package = f("build_context")(FIXTURE, "backoffice", today=TODAY)
        self.assertEqual(ids(package["rules"]), RULE_IDS)
        self.assertEqual(ids(package["hints"]), HINT_IDS)
        markdown = f("render_context")(package)
        titles = [heading for heading, _ in sections(markdown)]
        self.assertLess(titles.index(RULES_H), titles.index(HINTS_H))
        for cid in RULE_IDS:
            self.assertIn(cid, section(markdown, RULES_H))
        self.assertIn("merge-method-squash", section(markdown, HINTS_H))
        self.assertIn("não confirmada", section(markdown, HINTS_H))
        for absent in (REJECTED, OTHER_REPO):
            self.assertNotIn(absent, markdown)
            self.assertNotIn(absent, json.dumps(package, ensure_ascii=False))


class StalenessTest(unittest.TestCase):
    def test_stale_and_failed_collectors_are_both_cited(self):
        """SPEC-0038:UT-04"""
        state = scan_state(github=("2026-10-13", "ok"), argocd=("2026-11-01", "failed"),
                           facts=("2026-11-02", "ok"))
        text = "\n".join(f("staleness_warnings")(state, 14, TODAY))
        self.assertIn("Atlas com 20 dias desde o último scan de: github (stale_days: 14)", text)
        self.assertIn("Último scan falhou: argocd", text)
        self.assertNotIn("facts", text)

    def test_stale_means_more_than_stale_days(self):
        """SPEC-0038:UT-04"""
        warnings = f("staleness_warnings")
        self.assertEqual(warnings(scan_state(github=("2026-10-19", "ok")), 14, TODAY), [])  # 14 dias
        self.assertTrue(warnings(scan_state(github=("2026-10-18", "ok")), 14, TODAY))  # 15 dias
        self.assertEqual(warnings(scan_state(github=(TODAY, "ok")), 14, TODAY), [])

    def test_package_reads_scan_state_and_stale_days_of_the_atlas(self):
        """SPEC-0038:UT-04"""
        old = FixtureCopy(self, scan_state(facts=("2026-10-13", "ok"), signals=(TODAY, "ok")))
        package = f("build_context")(old.atlas, "backoffice", today=TODAY)
        self.assertIn("Atlas com 20 dias desde o último scan de: facts (stale_days: 14)", "\n".join(package["warnings"]))
        self.assertEqual(first_line(f("render_context")(package)), WARNING_H)
        relaxed = FixtureCopy(self, scan_state(facts=("2026-10-13", "ok"), signals=(TODAY, "ok")), stale_days=30)
        self.assertEqual(f("build_context")(relaxed.atlas, "backoffice", today=TODAY)["warnings"], [])

    def test_atlas_without_scan_gives_an_empty_package_with_the_warning(self):
        """SPEC-0038:UT-04 (seção 5: atlas sem scan)"""
        root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        shutil.copy(FIXTURE / "atlas-config.yml", root / "atlas-config.yml")
        package = f("build_context")(root, "backoffice", today=TODAY)
        self.assertIn(NO_SCAN, package["warnings"])
        self.assertEqual((package["services"], package["dependencies"], package["rules"], package["hints"]),
                         ([], [], [], []))


class MaxCharsTest(unittest.TestCase):
    def test_what_does_not_fit_is_listed_in_omitted(self):
        """SPEC-0038:UT-05"""
        build, render = f("build_context"), f("render_context")
        full = build(FIXTURE, "cashout backoffice", hops=2, today=TODAY)
        self.assertEqual(full["omitted"], [])
        self.assertIsNone(section(render(full), OMITTED_H))
        small = build(FIXTURE, "cashout backoffice", hops=2, max_chars=300, today=TODAY)
        self.assertTrue(small["omitted"], "nada foi para Omitidos com max_chars=300")
        body = section(render(small), OMITTED_H)
        self.assertIsNotNone(body)
        self.assertEqual(len([line for line in body.splitlines() if line.startswith("- ")]), len(small["omitted"]))

    def test_the_warning_is_never_omitted(self):
        """SPEC-0038:UT-05"""
        old = FixtureCopy(self, scan_state(facts=("2026-10-13", "ok"), signals=(TODAY, "ok")))
        package = f("build_context")(old.atlas, "cashout backoffice", max_chars=1, today=TODAY)
        self.assertTrue(package["warnings"])
        self.assertEqual(first_line(f("render_context")(package)), WARNING_H)


# --------------------------------------------------------------------------- integração (CLI)


class ContextCase(unittest.TestCase):
    """A fixture copiada para um Sandbox e ligada por init --join, com o _scan.json de hoje (UTC)."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        self.atlas = self.sandbox.atlas
        self.atlas.parent.mkdir(parents=True)
        shutil.copytree(FIXTURE, self.atlas)
        self.set_scan(scan_state(facts=(utc_today().isoformat(), "ok"), signals=(utc_today().isoformat(), "ok")))
        out = self.sandbox.run("init", "--join", "--atlas", self.atlas)
        self.assertEqual(out.returncode, 0, output(out))

    def set_scan(self, state):
        (self.atlas / "snapshots" / "_scan.json").write_text(json.dumps(state), encoding="utf-8")

    def context(self, *args, code=0):
        result = self.sandbox.run("context", *args)
        self.assertNotIn("Traceback", output(result), output(result))
        self.assertEqual(result.returncode, code, output(result))
        return result


class ContextCliTest(ContextCase):
    def test_known_term_gives_the_package_in_the_contract_order(self):
        """SPEC-0038:IT-01"""
        out = self.context("cashout", "backoffice").stdout
        titles = [heading for heading, _ in sections(out)]
        for title in (SERVICES_H, DEPS_H, RULES_H, HINTS_H):
            self.assertIn(title, titles, out)
        self.assertEqual([t for t in titles if t != OMITTED_H], [SERVICES_H, DEPS_H, RULES_H, HINTS_H])
        self.assertIn("services/backoffice.md", section(out, SERVICES_H))
        self.assertIn("PAYMENTS_URL=payments", section(out, DEPS_H))
        self.assertNotIn("payments-db", section(out, DEPS_H), "--hops padrão é 1")

    def test_json_package(self):
        """SPEC-0038:IT-01"""
        data = json.loads(self.context("cashout", "backoffice", "--json", "--hops", "2").stdout)
        self.assertEqual(data["services"][0]["key"], "service:backoffice")
        self.assertIn(("service:payments", "datastore:payments-db"), deps(data))
        self.assertEqual(ids(data["rules"]), RULE_IDS)

    def test_unknown_term_prints_the_fixed_message_and_exits_0(self):
        """SPEC-0038:IT-01"""
        out = self.context("zzz-inexistente", "qwerty")
        self.assertIn("Nada encontrado no atlas para: zzz-inexistente qwerty", output(out))
        self.assertIsNone(section(out.stdout, SERVICES_H))

    def test_hops_out_of_range_exits_2(self):
        """SPEC-0038:IT-01"""
        for hops in ("3", "-1"):
            with self.subTest(hops=hops):
                self.context("backoffice", "--hops", hops, code=2)

    def test_without_configuration_exits_3(self):
        """SPEC-0038:IT-01"""
        result = self.sandbox.run("context", "backoffice", config_home=self.sandbox.root / "nowhere")
        self.assertNotIn("Traceback", output(result))
        self.assertEqual(result.returncode, 3, output(result))

    def test_context_writes_nothing(self):
        """SPEC-0038:IT-01 (seção 5: só leitura)"""
        before = snapshot(self.atlas)
        self.context("cashout", "backoffice", "--hops", "2")
        self.context("cashout", "--json")
        self.assertEqual(snapshot(self.atlas), before)


class StaleCliTest(ContextCase):
    def test_old_scan_puts_the_warning_first(self):
        """SPEC-0038:IT-02"""
        self.set_scan(scan_state(facts=(days_ago(20), "ok"), signals=(utc_today().isoformat(), "ok")))
        out = self.context("cashout", "backoffice").stdout
        self.assertEqual(first_line(out), WARNING_H, out)
        self.assertIn("Atlas com 20 dias desde o último scan de: facts (stale_days: 14)", section(out, WARNING_H))
        self.assertIn(SERVICES_H, out)

    def test_failed_collector_puts_the_warning_first(self):
        """SPEC-0038:IT-02"""
        self.set_scan(scan_state(facts=(utc_today().isoformat(), "ok"), signals=(days_ago(1), "failed")))
        out = self.context("backoffice").stdout
        self.assertEqual(first_line(out), WARNING_H, out)
        self.assertIn("Último scan falhou: signals", section(out, WARNING_H))

    def test_nothing_found_still_shows_the_warning(self):
        """SPEC-0038:IT-02"""
        self.set_scan(scan_state(facts=(days_ago(30), "ok"), signals=(days_ago(30), "ok")))
        out = self.context("zzz-inexistente")
        self.assertEqual(first_line(out.stdout), WARNING_H, out.stdout)
        self.assertIn("Nada encontrado no atlas para: zzz-inexistente", output(out))

    def test_atlas_without_scan_warns_and_exits_0(self):
        """SPEC-0038:IT-02 (seção 5: atlas sem scan)"""
        sandbox = Sandbox()
        self.addCleanup(sandbox.cleanup)
        sandbox.new_atlas()
        result = sandbox.run("context", "backoffice")
        self.assertNotIn("Traceback", output(result))
        self.assertEqual(result.returncode, 0, output(result))
        self.assertIn(NO_SCAN, output(result))


# --------------------------------------------------------------------------- jornada e contrato


# repositórios só dos sinais: 6, mais que os 5 do GitHub (que também emite sinais), para o padrão valer para a
# organização inteira pelas regras da SPEC-0037@2
JOURNEY_REPOS = [f"acme/s{i}" for i in range(1, 7)]


def journey_signals():
    signals = []
    for repo in JOURNEY_REPOS:
        signals.append({"type": "pr-titles", "repository": repo, "total": 30,
                        "pattern_counts": {"conventional": 21, "ticket_key": 3, "other": 6}})
        signals.append({"type": "branch-prefixes", "repository": repo, "total": 30, "counts": {"feat/": 21, "fix/": 6}})
        signals.append({"type": "merge-methods", "repository": repo,
                        "present": {"merge": False, "squash": True, "rebase": False}})
    return signals


def journey_config():
    replay = ["python3", "{skill}/tests/fixtures/build/replay.py"]
    collectors = [
        ("github", "code", [*replay, "github", "code", "{skill}/tests/fixtures/github/expected-acme.json"]),
        ("argocd", "delivery", [*replay, "argocd", "delivery", "{skill}/tests/fixtures/argocd/expected-acme.json"]),
        ("db-facts", "data", ["python3", "{skill}/assets/collectors/generic.py", "--facts",
                              "{skill}/tests/fixtures/build/db-facts.json", "--category", "data", "--source",
                              "db-facts"]),
        ("signals", "code", ["python3", "{skill}/tests/fixtures/curate/signals.py", "signals",
                             "{atlas}/facts/signals.json"]),
    ]
    lines = ["collectors:"]
    for cid, category, command in collectors:
        lines += [f"  - id: {cid}", f"    category: {category}",
                  "    command: [" + ", ".join(json.dumps(a) for a in command) + "]", "    timeout: 60"]
    return ("version: 1\norganization: Acme\nmode: local\nlanguage: auto\nstale_days: 14\n"
            "categories: [code, delivery]\n" + "\n".join(lines) + "\nredaction: {extra_patterns: []}\n")


class JourneyCase(unittest.TestCase):
    """init -> scan (GitHub, Argo CD, banco generic e sinais de PR) pela CLI, como a pessoa faria."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        out = self.sandbox.init(mode="local")
        self.assertEqual(out.returncode, 0, output(out))
        self.atlas = self.sandbox.atlas
        (self.atlas / "atlas-config.yml").write_text(journey_config(), encoding="utf-8")
        (self.atlas / "facts").mkdir()
        (self.atlas / "facts" / "signals.json").write_text(json.dumps({"signals": journey_signals()}),
                                                          encoding="utf-8")
        self.run_cli("scan")

    def run_cli(self, *args, code=0):
        result = self.sandbox.run(*args)
        self.assertNotIn("Traceback", output(result), output(result))
        self.assertEqual(result.returncode, code, output(result))
        return result


class JourneyTest(JourneyCase):
    def test_init_scan_confirm_and_context_bring_service_database_and_rule(self):
        """SPEC-0038:IT-03"""
        self.run_cli("curate", "confirm", "pr-title-conventional", "--by", "thomas", "--via", "PR #3")
        out = self.run_cli("context", "api").stdout
        self.assertIn("api", section(out, SERVICES_H) or "", out)
        deps_body = section(out, DEPS_H) or ""
        for word in ("payments-db", "inferida", "DB_URL=db-prod.interno"):
            self.assertIn(word, deps_body)
        self.assertIn("pr-title-conventional", section(out, RULES_H) or "", out)
        data = json.loads(self.run_cli("context", "api", "--json").stdout)
        self.assertEqual(data["services"][0]["key"], "service:api")
        edge = next(d for d in data["dependencies"] if (d["from"], d["to"]) == ("service:api", "datastore:payments-db"))
        self.assertIs(edge["inferred"], True)
        self.assertEqual(edge["evidence"], "DB_URL=db-prod.interno")
        self.assertIn("pr-title-conventional", ids(data["rules"]))
        self.assertEqual(data["warnings"], [])


class ConventionContractTest(JourneyCase):
    def test_context_separates_the_three_statuses_of_curate_files(self):
        """SPEC-0038:CT-01"""
        files = {p.stem for p in (self.atlas / "conventions").glob("*.md")}
        self.assertTrue({"branch-prefix-feat", "merge-method-squash", "pr-title-conventional"} <= files, files)
        self.run_cli("curate", "confirm", "pr-title-conventional", "--by", "thomas", "--via", "PR #3")
        self.run_cli("curate", "reject", "branch-prefix-feat", "--by", "ana", "--via", "local", "--reason", "legado")
        listed = json.loads(self.run_cli("curate", "list", "--status", "inferred", "--json").stdout)
        inferred = {cid for cid in files if cid in json.dumps(listed)}
        self.assertIn("merge-method-squash", inferred)
        data = json.loads(self.run_cli("context", "api", "--json").stdout)
        self.assertEqual(ids(data["rules"]), {"pr-title-conventional"})
        self.assertEqual(ids(data["hints"]), inferred)
        out = self.run_cli("context", "api").stdout
        self.assertIn("pr-title-conventional", section(out, RULES_H) or "", out)
        self.assertIn("merge-method-squash", section(out, HINTS_H) or "", out)
        self.assertIn("não confirmada", section(out, HINTS_H))
        for text in (out, json.dumps(data)):
            self.assertNotIn("branch-prefix-feat", text)

    def test_reference_documents_the_package(self):
        """SPEC-0038:CT-01"""
        self.assertTrue(CONTEXT_REFERENCE.is_file(), "references/context.md não existe")
        text = CONTEXT_REFERENCE.read_text(encoding="utf-8")
        for word in (WARNING_H, SERVICES_H, DEPS_H, RULES_H, HINTS_H, OMITTED_H, "Nada encontrado no atlas para",
                     NO_SCAN, "--hops", "--max-chars", "--limit", "warnings", "services", "dependencies", "rules",
                     "hints", "omitted", "stale_days"):
            self.assertIn(word, text, word)


if __name__ == "__main__":
    unittest.main()
