"""Coletor github da org-atlas (SPEC-0034 v2: UT-01 a UT-04, UT-06, IT-01 a IT-03 e CT-01).

Contrato esperado de assets/collectors/github.py (o Implementer segue estes testes):

    github.py --org ORG [--repos a,b] [--pr-sample N (padrão 100)] [--input PASTA]
        stdout: um objeto org-atlas/collector@1 com collector "github", category "code", collected_at ISO 8601
        UTC e source "github" em cada entidade e relação; exit 0.
        entidades: repository:<org>/<nome> {language, default_branch, topics, archived, visibility} (só esses)
                   pipeline:<org>/<repo>/<arquivo do workflow sem extensão>, name = name do workflow, {file: path}
                   team:<org>/<time>, name = <time>, attrs {}
        relações:  pipeline -> repository (builds); team -> repository (owns, via CODEOWNERS)
        sinais (um de cada por repositório):
            {type: "pr-titles", repository, total, pattern_counts: {conventional, ticket_key, other}, sample}
                cada título conta em uma categoria só: Conventional Commits (tipo(escopo)!: ...) antes de chave de
                ticket (ABC-123), o resto é other; a soma é total; sample tem no máximo 10 títulos da amostra.
            {type: "branch-prefixes", repository, total, counts: {"feat/": n, ...}} (prefixo = 1º segmento + "/")
            {type: "merge-methods", repository, present: {merge, squash, rebase}} de allow_merge_commit,
                allow_squash_merge e allow_rebase_merge (GET repos/{org}/{repo}); sem esses campos o sinal é
                omitido e um aviso com <org>/<repo> vai para o stderr (o exit continua 0).
            {type: "pr-template", repository, present: {pr_template: bool}}: pull_request_template.md (qualquer
                caixa) ou a pasta PULL_REQUEST_TEMPLATE/ em .github/, na raiz ou em docs/ (contents API).
        --pr-sample N: só os N primeiros PRs da resposta de pulls entram nos sinais (total = min(N, PRs)).
        --repos a,b: só esses repositórios (e o que vem deles: pipelines, times donos, sinais).
        --input PASTA: lê repos.json, workflows/<repo>.json, codeowners/<repo>, pulls/<repo>.json,
            repo/<repo>.json e pr-template/<repo> (existir = template presente) e nunca chama o gh.
        Sem --input: `gh api` (com --paginate nas listas), lido com a biblioteca padrão (sem --jq).
        Erros (exit 1, sem traceback): "gh não encontrado — instale e autentique (references/collectors/github.md)",
        "gh sem acesso à organização ORG", "organização não encontrada: ORG".
        Nunca saem logins de autores nem corpo de PR.

    Funções (importadas pelo caminho nos testes unitários):
    count_title_patterns(titles: list[str]) -> {"total": int, "pattern_counts": {...}, "sample": list[str]}
    count_branch_prefixes(branches: list[str]) -> {"total": int, "counts": {"<prefixo>/": int}}
    map_repository(org: str, repo: dict) -> dict                       (entidade repository)
    map_workflows(org: str, repo_name: str, response: dict) -> (entities, relations)
    parse_codeowners(org: str, repo_name: str, text: str) -> (entities, relations)   (só times; sem repetição)
    map_policy(full_name: str, repo_response: dict, has_template: bool) -> (signals, warnings: list[str])

Fixtures: fixtures/github/acme (organização fictícia), fixtures/github/expected-acme.json (saída esperada sem o
cabeçalho; a amostra dos pr-titles é conferida à parte) e os gh falsos fixtures/github/fake_gh.py e
fake_gh_noauth.py (ver os docstrings).
"""
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import SKILL, TESTS, Sandbox, fn, output

SPEC = "SPEC-0034"
CONTRACT = "org-atlas/collector@1"
GITHUB = SKILL / "assets" / "collectors" / "github.py"
FIXTURES = TESTS / "fixtures" / "github"
ACME = FIXTURES / "acme"
EXPECTED = FIXTURES / "expected-acme.json"
FAKE_GH = FIXTURES / "fake_gh.py"
FAKE_GH_NOAUTH = FIXTURES / "fake_gh_noauth.py"
COLLECTED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
GH_MISSING = "gh não encontrado — instale e autentique (references/collectors/github.md)"
SAMPLE_MAX = 10

_CACHE = {}


def collector():
    """assets/collectors/github.py importado pelo caminho (sem sys.path)."""
    if "module" not in _CACHE:
        if not GITHUB.exists():
            raise AssertionError(f"{GITHUB} não existe ({SPEC})")
        spec = importlib.util.spec_from_file_location("org_atlas_collector_github", GITHUB)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CACHE["module"] = module
    return _CACHE["module"]


def function(name):
    f = getattr(collector(), name, None)
    if f is None:
        raise AssertionError(f"github.{name} não existe ({SPEC})")
    return f


def load(rel):
    path = ACME / rel
    return json.loads(path.read_text(encoding="utf-8"))


def expected():
    data = json.loads(EXPECTED.read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


def titles_of(repo):
    return [pr["title"] for pr in load(f"pulls/{repo}.json")]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def comparable(data):
    """entities, relations e signals em ordem estável; a amostra dos pr-titles fica de fora (conferida à parte)."""
    signals = []
    for signal in data.get("signals", []):
        signal = dict(signal)
        if signal.get("type") == "pr-titles":
            signal.pop("sample", None)
        signals.append(signal)
    return {
        "entities": sorted(data.get("entities", []), key=canonical),
        "relations": sorted(data.get("relations", []), key=canonical),
        "signals": sorted(signals, key=canonical),
    }


def samples(data):
    return {s.get("repository"): s.get("sample") for s in data.get("signals", []) if s.get("type") == "pr-titles"}


def expected_for(wanted):
    """expected-acme.json só com os repositórios `wanted` ({"acme/api", ...}) e o que vem deles."""
    full = expected()
    relations = [r for r in full["relations"] if r["to"].split(":", 1)[1] in wanted]
    owners = {r["from"] for r in relations}
    entities = [e for e in full["entities"]
                if (e["kind"] == "repository" and e["id"] in wanted)
                or (e["kind"] == "pipeline" and e["id"].rsplit("/", 1)[0] in wanted)
                or f"{e['kind']}:{e['id']}" in owners]
    signals = [s for s in full["signals"] if s["repository"] in wanted]
    return {"entities": entities, "relations": relations, "signals": signals}


def big_org(folder, prs=250):
    """Organização acme com um repositório `big` de `prs` PRs (mais de uma página da API), em `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    repo = dict(load("repos.json")[0], id=2001, name="big", full_name="acme/big")
    (folder / "repos.json").write_text(json.dumps([repo]), encoding="utf-8")
    for sub in ("repo", "pulls"):
        (folder / sub).mkdir(exist_ok=True)
    (folder / "repo" / "big.json").write_text(json.dumps(dict(repo, allow_merge_commit=True,
                                                              allow_squash_merge=True,
                                                              allow_rebase_merge=False)), encoding="utf-8")
    pulls = [{"number": prs - i, "title": f"feat: change {prs - i}", "state": "closed",
              "head": {"ref": f"feat/change-{prs - i}"}, "base": {"ref": "main"}} for i in range(prs)]
    (folder / "pulls" / "big.json").write_text(json.dumps(pulls), encoding="utf-8")
    return folder


def make_bin(fake):
    """Pasta temporária com `fake` copiado como `gh` executável."""
    folder = Path(tempfile.mkdtemp()).resolve()
    target = folder / "gh"
    shutil.copyfile(fake, target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return folder


class GithubCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = self.tmp / "gh-calls.jsonl"

    def run_github(self, *args, fake=None, path=None, env=None):
        """Roda github.py; fake = gh falso no início do PATH; path = PATH inteiro (sem o do sistema)."""
        environ = dict(os.environ)
        environ["HOME"] = str(self.tmp)
        environ["FAKE_GH_FIXTURES"] = str(ACME)
        environ["FAKE_GH_LOG"] = str(self.log)
        if fake is not None:
            folder = make_bin(fake)
            self.addCleanup(shutil.rmtree, folder, True)
            environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
        if path is not None:
            environ["PATH"] = str(path)
        environ.update(env or {})
        result = subprocess.run([sys.executable, str(GITHUB), *[str(a) for a in args]], check=False, cwd=self.tmp,
                                capture_output=True, text=True, env=environ)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def gh_calls(self):
        if not self.log.is_file():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def collect(self, *args, **kwargs):
        result = self.run_github(*args, **kwargs)
        self.assertEqual(result.returncode, 0, output(result))
        return json.loads(result.stdout), result

    def assert_header(self, data):
        self.assertEqual(data.get("contract"), CONTRACT)
        self.assertEqual(data.get("collector"), "github")
        self.assertEqual(data.get("category"), "code")
        self.assertRegex(str(data.get("collected_at")), COLLECTED_AT)

    def assert_samples(self, data, limit=None):
        for repo, sample in samples(data).items():
            with self.subTest(sample=repo):
                titles = titles_of(repo.split("/", 1)[1])
                if limit is not None:
                    titles = titles[:limit]
                self.assertIsInstance(sample, list)
                self.assertEqual(len(sample), min(SAMPLE_MAX, len(titles)))
                self.assertTrue(set(sample) <= set(titles), sample)

    def assert_failure(self, result, message):
        self.assertEqual(result.returncode, 1, output(result))
        self.assertIn(message, output(result))
        self.assertFalse(result.stdout.strip().startswith("{"), "nada de saída do contrato numa falha")


# --------------------------------------------------------------------------- unitários


class TitlePatternsTest(unittest.TestCase):
    TITLES = (
        "feat(api): add refunds endpoint",
        "fix: retry on 503",
        "feat!: drop v1 routes",
        "chore(deps): bump x from 1.0 to 1.1",
        "PAY-123 add webhook",
        "[OPS-42] rotate certs",
        "Update README",
        "WIP",
        "docs: explain retries",
        "feat add thing without colon",
        "refactor(core)!: split module",
        "ab-12 lowercase is not a ticket",
    )

    def test_conventional_ticket_and_other_are_counted_and_sample_is_limited(self):
        """SPEC-0034:UT-01 — Conventional Commits, chave de ticket e outros; amostra com no máximo 10."""
        result = function("count_title_patterns")(list(self.TITLES))
        self.assertEqual(result["total"], 12)
        self.assertEqual(result["pattern_counts"], {"conventional": 6, "ticket_key": 2, "other": 4})
        self.assertEqual(sum(result["pattern_counts"].values()), result["total"])
        self.assertEqual(len(result["sample"]), SAMPLE_MAX)
        self.assertTrue(set(result["sample"]) <= set(self.TITLES))
        self.assertTrue(all(isinstance(t, str) for t in result["sample"]))

    def test_small_or_empty_samples(self):
        """SPEC-0034:UT-01 — com menos de 10 títulos a amostra traz todos; sem títulos, tudo zero."""
        small = function("count_title_patterns")(["fix: a", "OPS-1 b", "c"])
        self.assertEqual(small["total"], 3)
        self.assertEqual(small["pattern_counts"], {"conventional": 1, "ticket_key": 1, "other": 1})
        self.assertEqual(sorted(small["sample"]), sorted(["fix: a", "OPS-1 b", "c"]))
        empty = function("count_title_patterns")([])
        self.assertEqual(empty, {"total": 0, "pattern_counts": {"conventional": 0, "ticket_key": 0, "other": 0},
                                 "sample": []})

    def test_branch_prefixes_are_counted_by_first_segment(self):
        """SPEC-0034:UT-01 — prefixos de branch (feat/, fix/...) pelo primeiro segmento."""
        result = function("count_branch_prefixes")(
            ["feat/a", "feat/api/b", "fix/c", "dependabot/npm_and_yarn/x-1.2"])
        self.assertEqual(result, {"total": 4, "counts": {"feat/": 2, "fix/": 1, "dependabot/": 1}})


    def test_branch_prefixes_count_only_known_types(self):
        """SPEC-0034:UT-01 — revisão G4: só prefixos de tipo conhecidos (sem caixa, chave minúscula); outro
        primeiro segmento (login, bot) conta só no total, como branch sem "/"."""
        branches = ["feat/a", "FIX/b", "Feature/c", "hotfix/d", "bugfix/e", "perf/f", "dependabot/npm/x",
                    "renovate/y", "release/1.0", "ana-dev/fix-x", "copilot/x", "main-hotfix", "wip/z"]
        result = function("count_branch_prefixes")(branches)
        self.assertEqual(result["total"], len(branches))
        self.assertEqual(result["counts"], {"feat/": 1, "fix/": 1, "feature/": 1, "hotfix/": 1, "bugfix/": 1,
                                            "perf/": 1, "dependabot/": 1, "renovate/": 1, "release/": 1})
        self.assertNotIn("ana-dev", json.dumps(result))
        known = ("feat", "fix", "chore", "docs", "refactor", "test", "perf", "build", "ci", "style", "revert",
                 "feature", "bugfix", "hotfix", "release", "dependabot", "renovate")
        everything = function("count_branch_prefixes")([f"{k.upper()}/x" for k in known])
        self.assertEqual(everything["counts"], {f"{k}/": 1 for k in known})


class MapRepositoryTest(unittest.TestCase):
    def test_repository_has_only_the_contract_attributes(self):
        """SPEC-0034:UT-02 — repository:<org>/<nome> com language, default_branch, topics, archived, visibility."""
        repos = {r["name"]: r for r in load("repos.json")}
        self.assertEqual(function("map_repository")("acme", repos["api"]), {
            "kind": "repository", "id": "acme/api", "name": "api",
            "attrs": {"language": "Go", "default_branch": "main", "topics": ["payments", "go"], "archived": False,
                      "visibility": "private"},
            "source": "github"})
        self.assertEqual(function("map_repository")("acme", repos["legacy"]), {
            "kind": "repository", "id": "acme/legacy", "name": "legacy",
            "attrs": {"language": None, "default_branch": "master", "topics": [], "archived": True,
                      "visibility": "private"},
            "source": "github"})


    def test_repository_id_uses_the_canonical_full_name(self):
        """SPEC-0034:UT-02 — revisão G4: o id vem do full_name da API, não da caixa de --org."""
        repos = {r["name"]: r for r in load("repos.json")}
        result = function("map_repository")("ACME", repos["api"])
        self.assertEqual(result["id"], "acme/api")
        self.assertEqual(result["name"], "api")


class MapWorkflowsTest(unittest.TestCase):
    def test_one_pipeline_per_workflow_and_builds(self):
        """SPEC-0034:UT-03 — um pipeline por workflow (id pelo arquivo sem extensão) e a relação builds."""
        entities, relations = function("map_workflows")("acme", "api", load("workflows/api.json"))
        self.assertEqual(sorted(entities, key=canonical), sorted([
            {"kind": "pipeline", "id": "acme/api/ci", "name": "CI", "attrs": {"file": ".github/workflows/ci.yml"},
             "source": "github"},
            {"kind": "pipeline", "id": "acme/api/release", "name": "Release",
             "attrs": {"file": ".github/workflows/release.yml"}, "source": "github"},
        ], key=canonical))
        self.assertEqual(sorted(relations, key=canonical), sorted([
            {"from": "pipeline:acme/api/ci", "to": "repository:acme/api", "type": "builds", "source": "github"},
            {"from": "pipeline:acme/api/release", "to": "repository:acme/api", "type": "builds",
             "source": "github"},
        ], key=canonical))

    def test_yaml_extension_and_no_workflows(self):
        """SPEC-0034:UT-03 — .yaml também perde a extensão; sem workflows, nada."""
        entities, relations = function("map_workflows")("acme", "infra", load("workflows/infra.json"))
        self.assertEqual([e["id"] for e in entities], ["acme/infra/terraform"])
        self.assertEqual(entities[0]["name"], "Terraform Plan")
        self.assertEqual([r["from"] for r in relations], ["pipeline:acme/infra/terraform"])
        self.assertEqual(function("map_workflows")("acme", "legacy", load("workflows/legacy.json")), ([], []))


    def test_paginated_output_is_read_page_by_page(self):
        """SPEC-0034:UT-03 — revisão G4: a saída do gh api --paginate (páginas JSON coladas) vira uma lista de
        páginas, inclusive objetos de actions/workflows."""
        parse = function("parse_pages")
        self.assertEqual(parse('[{"name": "a"}]\n[{"name": "b"}, {"name": "c"}][]'),
                         [[{"name": "a"}], [{"name": "b"}, {"name": "c"}], []])
        self.assertEqual(parse('{"total_count": 2, "workflows": [{"id": 1}]}{"total_count": 2, "workflows": '
                               '[{"id": 2}]}\n'),
                         [{"total_count": 2, "workflows": [{"id": 1}]}, {"total_count": 2, "workflows": [{"id": 2}]}])
        self.assertEqual(parse(""), [])


class ParseCodeownersTest(unittest.TestCase):
    TEXT = ("# Donos\n"
            "\n"
            "*        @acme/payments @ana-dev\n"
            "/docs/   @acme/docs-team ana@example.com   # comentário no fim\n"
            "*.go     @acme/payments\n")

    def test_only_teams_become_team_and_owns(self):
        """SPEC-0034:UT-04 — só times viram team com owns; usuários e e-mails são ignorados, sem repetição."""
        entities, relations = function("parse_codeowners")("acme", "api", self.TEXT)
        self.assertEqual(sorted(entities, key=canonical), sorted([
            {"kind": "team", "id": "acme/payments", "name": "payments", "attrs": {}, "source": "github"},
            {"kind": "team", "id": "acme/docs-team", "name": "docs-team", "attrs": {}, "source": "github"},
        ], key=canonical))
        self.assertEqual(sorted(relations, key=canonical), sorted([
            {"from": "team:acme/payments", "to": "repository:acme/api", "type": "owns", "source": "github"},
            {"from": "team:acme/docs-team", "to": "repository:acme/api", "type": "owns", "source": "github"},
        ], key=canonical))
        dump = json.dumps([entities, relations])
        self.assertNotIn("ana-dev", dump)
        self.assertNotIn("example.com", dump)

    def test_codeowners_with_only_users_has_no_team(self):
        """SPEC-0034:UT-04 — CODEOWNERS só com pessoas não gera nada."""
        text = (ACME / "codeowners" / "infra").read_text(encoding="utf-8")
        self.assertEqual(function("parse_codeowners")("acme", "infra", text), ([], []))


    def test_team_handles_are_case_insensitive(self):
        """SPEC-0034:UT-04 — revisão G4: @Acme/Payments e @acme/payments são um time só, id em minúsculas."""
        text = "*  @Acme/Payments\n/docs/  @acme/payments @ACME/Docs-Team\n"
        entities, relations = function("parse_codeowners")("acme", "api", text)
        self.assertEqual(sorted(e["id"] for e in entities), ["acme/docs-team", "acme/payments"])
        self.assertEqual(sorted(r["from"] for r in relations), ["team:acme/docs-team", "team:acme/payments"])
        self.assertTrue(all(r["to"] == "repository:acme/api" for r in relations), relations)


class MapPolicyTest(unittest.TestCase):
    def assert_booleans(self, signals):
        for signal in signals:
            self.assertIsInstance(signal.get("present"), dict, signal)
            self.assertTrue(all(type(v) is bool for v in signal["present"].values()), signal)

    def test_merge_methods_and_template_are_objects_of_booleans(self):
        """SPEC-0034:UT-06 — allow_* viram merge-methods e o template vira pr-template, só com booleanos."""
        signals, warnings = function("map_policy")("acme/api", load("repo/api.json"), True)
        self.assertEqual(warnings, [])
        self.assertEqual(sorted(signals, key=canonical), sorted([
            {"type": "merge-methods", "repository": "acme/api",
             "present": {"merge": False, "squash": True, "rebase": False}},
            {"type": "pr-template", "repository": "acme/api", "present": {"pr_template": True}},
        ], key=canonical))
        self.assert_booleans(signals)

    def test_without_allow_fields_merge_methods_is_omitted_with_a_warning(self):
        """SPEC-0034:UT-06 — sem allow_* (token sem permissão) o merge-methods é omitido e há um aviso."""
        signals, warnings = function("map_policy")("acme/legacy", load("repo/legacy.json"), False)
        self.assertEqual(signals, [{"type": "pr-template", "repository": "acme/legacy",
                                    "present": {"pr_template": False}}])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("acme/legacy", warnings[0])
        self.assert_booleans(signals)


    def test_template_listing_ignores_items_that_are_not_objects(self):
        """SPEC-0034:UT-06 — revisão G4: item da listagem que não é objeto é ignorado, sem exceção."""
        has = function("has_template_entry")
        self.assertTrue(has(["x", None, 3, {"name": "Pull_Request_Template.md", "type": "file"}]))
        self.assertTrue(has([["a"], {"name": "PULL_REQUEST_TEMPLATE", "type": "dir"}]))
        self.assertFalse(has(["pull_request_template.md", None, {"name": "README.md", "type": "file"}]))
        self.assertFalse(has({"name": "pull_request_template.md", "type": "file"}))


# --------------------------------------------------------------------------- integração


class InputFolderTest(GithubCase):
    def test_input_folder_generates_the_expected_output(self):
        """SPEC-0034:IT-01 — --input com as fixtures da acme: repositórios, pipelines, times e sinais."""
        # gh que falha no PATH: com --input o coletor nunca chama o gh
        data, result = self.collect("--org", "acme", "--input", ACME, fake=FAKE_GH_NOAUTH)
        self.assertEqual(self.gh_calls(), [], "com --input o gh não é chamado")
        self.assert_header(data)
        self.assertEqual(comparable(data), comparable(expected()))
        self.assert_samples(data)
        self.assertTrue(all(e.get("source") == "github" for e in data["entities"] + data["relations"]))
        self.assertIn("acme/legacy", result.stderr, "aviso do merge-methods omitido no stderr")
        for private in ("ana-dev", "bruno-dev", "carla-dev", "Corpo privado"):
            self.assertNotIn(private, result.stdout, "logins de autor e corpo de PR não saem do coletor")

    def test_pr_sample_limits_the_prs_read(self):
        """SPEC-0034:IT-01 — --pr-sample N: só os N primeiros PRs entram nos sinais."""
        data, _ = self.collect("--org", "acme", "--input", ACME, "--pr-sample", "5")
        totals = {(s["type"], s["repository"]): s["total"] for s in data["signals"]
                  if s["type"] in ("pr-titles", "branch-prefixes")}
        want = {"acme/api": 5, "acme/web": 5, "acme/infra": 3, "acme/mobile": 3, "acme/legacy": 2}
        self.assertEqual(totals, {(kind, repo): n for repo, n in want.items()
                                  for kind in ("pr-titles", "branch-prefixes")})
        for signal in data["signals"]:
            if signal["type"] == "pr-titles":
                self.assertEqual(sum(signal["pattern_counts"].values()), signal["total"])
        self.assert_samples(data, limit=5)

    def test_repos_option_keeps_only_the_given_repositories(self):
        """SPEC-0034:IT-01 — --repos api,web: só esses repositórios e o que vem deles."""
        data, _ = self.collect("--org", "acme", "--input", ACME, "--repos", "api,web")
        self.assertEqual(comparable(data), comparable(expected_for({"acme/api", "acme/web"})))

    def test_org_and_repos_are_case_insensitive(self):
        """SPEC-0034:IT-01 — revisão G4: --org ACME dá os mesmos ids (full_name da API); --repos API acha api."""
        data, _ = self.collect("--org", "ACME", "--input", ACME)
        self.assertEqual(comparable(data), comparable(expected()))
        data, _ = self.collect("--org", "acme", "--input", ACME, "--repos", "API,Web")
        self.assertEqual(comparable(data), comparable(expected_for({"acme/api", "acme/web"})))

    def test_codeowners_that_is_not_utf8_does_not_crash(self):
        """SPEC-0034:IT-01 — revisão G4: CODEOWNERS que não é UTF-8 no --input não gera traceback."""
        folder = self.tmp / "acme-bad-codeowners"
        shutil.copytree(ACME, folder)
        (folder / "codeowners" / "api").write_bytes(b"\xff\xfe* @acme/payments \xe9quipe\n")
        result = self.run_github("--org", "acme", "--input", folder)
        self.assertEqual(result.returncode, 0, output(result))
        self.assertNotIn("Traceback", output(result))
        json.loads(result.stdout)

    def test_logins_in_branch_names_never_leave_the_collector(self):
        """SPEC-0034:IT-01 — revisão G4: branch com login (ana-dev/...) ou bot (copilot/...) conta só no total."""
        data, result = self.collect("--org", "acme", "--input", ACME)
        self.assertNotIn("ana-dev", result.stdout)
        self.assertNotIn("copilot", result.stdout)
        prefixes = {s["repository"]: s for s in data["signals"] if s["type"] == "branch-prefixes"}
        self.assertEqual(prefixes["acme/api"]["total"], 16)
        self.assertEqual(sum(prefixes["acme/api"]["counts"].values()), 14)


class FakeGhTest(GithubCase):
    def test_fake_gh_on_path_gives_the_same_output_as_input(self):
        """SPEC-0034:IT-02 — sem --input, com o gh falso no PATH, a saída é a mesma do --input."""
        via_input, _ = self.collect("--org", "acme", "--input", ACME)
        via_gh, result = self.collect("--org", "acme", fake=FAKE_GH)
        self.assert_header(via_gh)
        self.assertEqual(comparable(via_gh), comparable(via_input))
        self.assertEqual(comparable(via_gh), comparable(expected()))
        self.assertEqual(samples(via_gh), samples(via_input))
        self.assertIn("acme/legacy", result.stderr, "aviso do merge-methods omitido no stderr")
        calls = self.gh_calls()
        api_calls = [c for c in calls if c[:1] == ["api"]]
        self.assertTrue(api_calls, "o coletor precisa chamar gh api")
        repo_lists = [c for c in api_calls if any(a.strip("/").split("?")[0] == "orgs/acme/repos" for a in c)]
        self.assertTrue(repo_lists, "a lista de repositórios vem de gh api orgs/<org>/repos")
        self.assertTrue(all("--paginate" in c for c in repo_lists), "listas com --paginate (seção 4)")

    def test_fake_gh_with_pr_sample_and_repos(self):
        """SPEC-0034:IT-02 — --pr-sample e --repos dão o mesmo resultado pelo gh e pelo --input."""
        args = ("--org", "acme", "--repos", "api,infra", "--pr-sample", "4")
        via_input, _ = self.collect(*args, "--input", ACME)
        via_gh, _ = self.collect(*args, fake=FAKE_GH)
        self.assertEqual(comparable(via_gh), comparable(via_input))
        self.assertEqual(samples(via_gh), samples(via_input))


    def test_fake_gh_with_org_in_another_case(self):
        """SPEC-0034:IT-02 — revisão G4: pelo gh, --org ACME e --repos API dão os ids canônicos."""
        data, _ = self.collect("--org", "ACME", fake=FAKE_GH)
        self.assertEqual(comparable(data), comparable(expected()))
        data, _ = self.collect("--org", "acme", "--repos", "API,web", fake=FAKE_GH)
        self.assertEqual(comparable(data), comparable(expected_for({"acme/api", "acme/web"})))

    def test_paginated_lists_are_merged(self):
        """SPEC-0034:IT-02 — revisão G4: listas com --paginate em várias páginas são juntadas."""
        data, _ = self.collect("--org", "acme", fake=FAKE_GH, env={"FAKE_GH_PAGINATE_SIZE": "1"})
        self.assertEqual(comparable(data), comparable(expected()))

    def test_pr_sample_reads_more_than_one_page(self):
        """SPEC-0034:IT-02 — revisão G4: --pr-sample 150 lê 150 PRs, mesmo passando de uma página (100)."""
        folder = big_org(self.tmp / "big-org")
        env = {"FAKE_GH_FIXTURES": str(folder)}
        for name, kwargs in (("gh falso", {"fake": FAKE_GH}), ("--input", {"args": ("--input", folder)})):
            with self.subTest(name):
                data, _ = self.collect("--org", "acme", "--pr-sample", "150", *kwargs.get("args", ()),
                                       fake=kwargs.get("fake"), env=env)
                totals = {s["type"]: s.get("total") for s in data["signals"] if s["repository"] == "acme/big"}
                self.assertEqual(totals["pr-titles"], 150)
                self.assertEqual(totals["branch-prefixes"], 150)
                pr_titles = next(s for s in data["signals"] if s["type"] == "pr-titles")
                self.assertEqual(pr_titles["pattern_counts"], {"conventional": 150, "ticket_key": 0, "other": 0})


class GhFailureTest(GithubCase):
    def test_gh_without_authentication_exits_1(self):
        """SPEC-0034:IT-03 — gh sem autenticação (ou token inválido): exit 1 "gh sem acesso à organização ORG"."""
        for mode in ("missing", "bad"):
            with self.subTest(auth=mode):
                result = self.run_github("--org", "acme", fake=FAKE_GH_NOAUTH, env={"FAKE_GH_AUTH": mode})
                self.assert_failure(result, "gh sem acesso à organização acme")

    def test_gh_not_installed_exits_1(self):
        """SPEC-0034:IT-03 — gh ausente do PATH: exit 1 com a mensagem do contrato."""
        empty = self.tmp / "empty-bin"
        empty.mkdir()
        result = self.run_github("--org", "acme", path=empty)
        self.assert_failure(result, GH_MISSING)

    def test_unknown_organization_exits_1(self):
        """SPEC-0034:IT-03 — organização inexistente: exit 1 "organização não encontrada: ORG"."""
        result = self.run_github("--org", "ghost", fake=FAKE_GH)
        self.assert_failure(result, "organização não encontrada: ghost")


    def test_rate_limit_exits_1_with_a_rate_limit_message(self):
        """SPEC-0034:IT-03 — revisão G4: 403 de limite de requisições ("API rate limit exceeded") sai com 1 e
        fala do limite, não de falta de acesso — na primeira chamada e no meio da coleta."""
        for name, env in (("primeira chamada", {"FAKE_GH_FAIL": "rate-limit"}),
                          ("nos PRs", {"FAKE_GH_FAIL": "rate-limit", "FAKE_GH_FAIL_ON": "/pulls"})):
            with self.subTest(name):
                result = self.run_github("--org", "acme", fake=FAKE_GH, env=env)
                self.assertEqual(result.returncode, 1, output(result))
                self.assertRegex(output(result), re.compile("limite", re.IGNORECASE))
                self.assertNotIn("sem acesso", output(result))
                self.assertFalse(result.stdout.strip().startswith("{"), "nada de saída do contrato numa falha")

    def test_plain_403_on_the_organization_is_no_access(self):
        """SPEC-0034:IT-03 — revisão G4: 403 comum em orgs/<org>/repos segue "gh sem acesso à organização"."""
        result = self.run_github("--org", "acme", fake=FAKE_GH, env={"FAKE_GH_FAIL": "forbidden"})
        self.assert_failure(result, "gh sem acesso à organização acme")
        self.assertNotRegex(output(result), re.compile("limite", re.IGNORECASE))


# --------------------------------------------------------------------------- contrato


def atlas_config(collectors):
    lines = ["version: 1", "organization: Acme", "mode: local", "language: auto", "stale_days: 14",
             "categories: [code, runtime]", "collectors:"]
    for cid, category, command in collectors:
        lines += [f"  - id: {cid}", f"    category: {category}",
                  "    command: [" + ", ".join(json.dumps(a) for a in command) + "]", "    timeout: 60"]
    lines.append("redaction: {extra_patterns: []}")
    return "\n".join(lines) + "\n"


class GithubContractTest(GithubCase):
    def test_github_output_passes_the_collector_contract(self):
        """SPEC-0034:CT-01 — saída de github.py (fixtures, pelo --input e pelo gh falso) passa no validador."""
        validate = fn("validate_collector_output", "SPEC-0033")
        for name, kwargs in (("--input", {"args": ("--input", ACME)}), ("gh falso", {"fake": FAKE_GH})):
            with self.subTest(name):
                data, _ = self.collect("--org", "acme", *kwargs.get("args", ()), fake=kwargs.get("fake"))
                _, violations, dropped = validate(data)
                self.assertEqual(violations, [])
                self.assertEqual(dropped, [])

    def test_scan_with_both_collectors_declared_ends_ok(self):
        """SPEC-0034:CT-01 — scan de um atlas com generic e github declarados ({skill}) termina com OK."""
        sandbox = Sandbox()
        self.addCleanup(sandbox.cleanup)
        out = sandbox.init(mode="local")
        self.assertEqual(out.returncode, 0, output(out))
        config = atlas_config([
            ("github", "code", ["python3", "{skill}/assets/collectors/github.py", "--org", "acme", "--input",
                                "{skill}/tests/fixtures/github/acme"]),
            ("generic", "runtime", ["python3", "{skill}/assets/collectors/generic.py", "--facts",
                                    "{skill}/tests/fixtures/generic/facts.json", "--category", "runtime"]),
        ])
        (sandbox.atlas / "atlas-config.yml").write_text(config, encoding="utf-8")
        result = sandbox.run("scan")
        text = output(result)
        self.assertEqual(result.returncode, 0, text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("FALHA", text)
        self.assertNotIn("descartad", text, "nada fora do contrato nem chave proibida")
        self.assertRegex(text, re.compile(r"^OK github — ", re.MULTILINE))
        self.assertRegex(text, re.compile(r"^OK generic — ", re.MULTILINE))
        state = json.loads((sandbox.atlas / "snapshots" / "_scan.json").read_text(encoding="utf-8"))
        full = expected()
        self.assertEqual(state["github"]["status"], "ok")
        self.assertEqual(state["github"]["entities"], len(full["entities"]))
        self.assertEqual(state["github"]["relations"], len(full["relations"]))
        self.assertEqual(state["generic"]["status"], "ok")
        self.assertEqual(state["generic"]["entities"], 3)
        self.assertEqual(state["generic"]["relations"], 3)


if __name__ == "__main__":
    unittest.main()
