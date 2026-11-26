"""Adaptador github-actions: as execuções da CI de um commit (SPEC-0106: UT-01 a UT-04 e a parte do adaptador no
CT-01; ADR-0010, ADR-0023, ADR-0025).

Contrato (seção 6 da SPEC-0106) que estes testes fixam:

    assets/probes/github-actions.py --describe ->
        {"contract": "probe@2", "adapter": "github-actions", "capabilities": {"pipeline": {"verbs": ["runs"],
         "targets": ["deployment"], "access": [], "inputs": ["change"]}}}
    entrada probe@2 no stdin com target.change = {"commit": <40 hexadecimais>, "repositories": [<dono>/<repo>...]};
    saída probe@2 no stdout, exit 0 também no erro (status "error", items [], mensagem fixa, sem o stderr do gh).
    gh: exatamente `api -X GET repos/<dono>/<repo>/actions/runs -f head_sha=<sha> -f per_page=100`, um por
        repositório, até 10 repositórios.
    runs -> um item por execução {repository, found, workflow, path, event, status, conclusion, attempt,
        started_at, duration_seconds, url}, ordenados por repositório e started_at; 404 -> {repository, found: false}.

Leituras desta suíte (listadas no relatório do test-writer):
    - Os itens de execução têm exatamente as 11 chaves do bloco da seção 6; o de 404, exatamente repository e found.
    - `attempt` = run_attempt; `workflow` = name; `path` = path; `started_at` = run_started_at; a URL é o html_url
      sem query, sem fragmento e sem usuário.
    - Verbo fora de `runs` -> "entrada inválida" ou "chamada não permitida" (a spec aceita os dois).
    - Com 12 repositórios, os 10 primeiros na ordem da entrada (o núcleo já os manda em ordem).
    - "Demorando além do timeout" (30 s) não é exercitado com espera de verdade: o gh falso imprime o erro de rede de
      tempo esgotado do gh real ("i/o timeout"), como o "timeout" vem do texto da CLI nos adaptadores da SPEC-0101.
    - O limite de requisições vale com HTTP 403 e com HTTP 429 (o texto "API rate limit exceeded").
    - Um erro (401, 403, limite, timeout, JSON inválido) num repositório derruba a execução inteira (status error),
      só o 404 vira item found: false.

Dublê: fixtures/github-actions/fake_gh.py, copiado como `gh` numa pasta temporária (o único item do PATH), com o
cenário em JSON ao lado; registra cada argv e o GH_TOKEN recebido. Isolamento: HOME, XDG_CONFIG_HOME e
ATLAS_CONFIG_HOME temporários; nenhum gh real, nenhuma rede; nomes acme.
"""
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

from helpers import SKILL, TESTS, fn, output

SPEC = "SPEC-0106"
ADAPTER = SKILL / "assets" / "probes" / "github-actions.py"
REFERENCE = SKILL / "references" / "probes" / "github-actions.md"
FIXTURES = TESTS / "fixtures" / "github-actions"
FAKE_GH = FIXTURES / "fake_gh.py"
RUNS = FIXTURES / "runs"

COMMIT = "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567"
TOKEN = "fake-gh-token-0106-nao-real"
SENTINEL = "SENTINEL-STDERR-0106"
ECHO = "ECO-DO-GH-0106"
HIDDEN = ("SENTINEL-TITLE-0106", "sentinel-branch-0106", "pessoa-sentinela-0106", "Pessoa Sentinela",
          "check_suite_focus", "#logs", "pull_requests", "display_title", "head_commit", "actor", "head_branch")

DESCRIBE = {"contract": "probe@2", "adapter": "github-actions",
            "capabilities": {"pipeline": {"verbs": ["runs"], "targets": ["deployment"], "access": [],
                                          "inputs": ["change"]}}}
RUN_KEYS = {"repository", "found", "workflow", "path", "event", "status", "conclusion", "attempt", "started_at",
            "duration_seconds", "url"}
MISSING_KEYS = {"repository", "found"}

INVALID_INPUT = "entrada inválida"
REFUSED = "chamada não permitida"
ERRORS = {"401": "sem autenticação no GitHub", "noauth": "sem autenticação no GitHub", "403": "sem permissão (403)",
          "rate-limit": "limite de requisições do GitHub", "rate-limit-429": "limite de requisições do GitHub",
          "timeout": "timeout", "invalid-json": "resposta inválida do gh"}

EXPECTED_UT01 = [
    {"repository": "acme/api", "found": True, "workflow": "Build", "path": ".github/workflows/build.yml",
     "event": "push", "status": "completed", "conclusion": "success", "attempt": 1,
     "started_at": "2026-11-24T10:00:00Z", "duration_seconds": 312,
     "url": "https://github.com/acme/api/actions/runs/1001"},
    {"repository": "acme/api", "found": True, "workflow": "Publish", "path": ".github/workflows/publish.yml",
     "event": "push", "status": "in_progress", "conclusion": "", "attempt": 1,
     "started_at": "2026-11-24T10:06:00Z", "duration_seconds": None,
     "url": "https://github.com/acme/api/actions/runs/1002"},
    {"repository": "acme/web", "found": True, "workflow": "Build", "path": ".github/workflows/build.yml",
     "event": "push", "status": "completed", "conclusion": "failure", "attempt": 2,
     "started_at": "2026-11-24T10:01:00Z", "duration_seconds": 150,
     "url": "https://github.com/acme/web/actions/runs/1101"},
]


def f(name):
    return fn(name, "SPEC-0096")


def install_gh(folder: Path, scenario: dict, record: Path) -> Path:
    """Copia o gh falso como `gh` (cabeçalho com o Python dos testes) e grava o cenário ao lado dele."""
    folder.mkdir(parents=True, exist_ok=True)
    body = FAKE_GH.read_text(encoding="utf-8").split("\n", 1)[1]
    target = folder / "gh"
    target.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (folder / "fake-gh.json").write_text(json.dumps(dict(scenario, record=str(record))), encoding="utf-8")
    return target


def read_rows(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def allowed_argv(repository, commit=COMMIT) -> list:
    """SPEC-0106:UT-04 — o único argv permitido para um repositório."""
    return ["api", "-X", "GET", f"repos/{repository}/actions/runs", "-f", f"head_sha={commit}", "-f", "per_page=100"]


def probe_input(repositories=("acme/api", "acme/web"), commit=COMMIT, verb="runs", lines=200):
    return {"contract": "probe@2", "capability": "pipeline", "verb": verb,
            "target": {"service": "api", "environment": "dev", "deployment": "dev-api",
                       "change": {"commit": commit, "repositories": list(repositories)}},
            "limits": {"lines": lines, "since_seconds": 1800}}


def gh_run(rid, repository="acme/api", name="Build", status="completed", conclusion="success",
           started="2026-11-24T10:00:00Z", updated="2026-11-24T10:01:00Z"):
    return {"id": rid, "name": name, "path": ".github/workflows/build.yml", "event": "push", "status": status,
            "conclusion": conclusion, "run_attempt": 1, "run_started_at": started, "created_at": started,
            "updated_at": updated, "head_sha": COMMIT, "head_branch": "feature/sentinel-branch-0106",
            "display_title": "feat: SENTINEL-TITLE-0106", "actor": {"login": "pessoa-sentinela-0106"},
            "html_url": f"https://github.com/{repository}/actions/runs/{rid}"}


class GithubActionsCase(unittest.TestCase):
    """Uma pasta temporária por teste: HOME, configuração e a pasta do gh falso (o PATH)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "gh-bin"
        self.record = self.root / "gh-calls.jsonl"

    def install(self, fail=None, repos=None, fixtures=None):
        self.record.unlink(missing_ok=True)
        scenario = {"fixtures": [str(fixtures or RUNS)], "repos": repos or {}, "fail": fail or {}, "echo": ECHO}
        install_gh(self.bin, scenario, self.record)

    def environment(self, with_gh=True, token=True):
        empty = self.root / "empty-bin"
        empty.mkdir(exist_ok=True)
        env = {"PATH": str(self.bin if with_gh else empty), "HOME": str(self.home),
               "XDG_CONFIG_HOME": str(self.home / ".config"), "ATLAS_CONFIG_HOME": str(self.root / "config-home"),
               "LANG": "C.UTF-8"}
        if token:
            env["GH_TOKEN"] = TOKEN
        for name in ("TMPDIR", "SYSTEMROOT"):
            if name in os.environ:
                env[name] = os.environ[name]
        return env

    def adapter(self, *args, stdin="", with_gh=True, token=True):
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        result = subprocess.run([sys.executable, str(ADAPTER), *args], input=stdin, capture_output=True, text=True,
                                cwd=self.root, env=self.environment(with_gh, token), timeout=120, check=False)
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        return result

    def run_probe(self, data, with_gh=True, token=True):
        """Roda o adaptador; confere exit 0, a saída probe@2 (validador do núcleo), o pedido ecoado, nada do stderr
        do gh nem do token na saída, as chaves dos itens e todo argv contra a lista fechada (UT-04)."""
        result = self.adapter(stdin=json.dumps(data), with_gh=with_gh, token=token)
        self.assertEqual(result.returncode, 0, output(result))
        text = output(result)
        for value in (TOKEN, SENTINEL, ECHO, *HIDDEN):
            self.assertNotIn(value, text, f"{value} apareceu na saída do adaptador")
        out = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(out), [], out)
        self.assertEqual({k: out.get(k) for k in ("contract", "adapter", "capability")},
                         {"contract": "probe@2", "adapter": "github-actions", "capability": "pipeline"})
        if out["status"] == "ok":
            for item in out["items"]:
                self.assertEqual(set(item), RUN_KEYS if item.get("found") else MISSING_KEYS, item)
        self.assertAllowedCalls(data)
        return out

    def calls(self):
        return [row["argv"] for row in read_rows(self.record)]

    def assertAllowedCalls(self, data):
        """SPEC-0106:UT-04 — todo argv é exatamente o permitido, de um repositório da entrada, uma vez cada."""
        # SPEC-0106:UT-04
        change = data["target"]["change"]
        allowed = [allowed_argv(r, change["commit"]) for r in change["repositories"]]
        calls = self.calls()
        for argv in calls:
            self.assertIn(argv, allowed, f"argv fora da lista fechada: {argv}")
        for argv in calls:
            self.assertEqual(calls.count(argv), 1, f"mais de uma chamada para o mesmo repositório: {argv}")

    def assertError(self, out, message):
        self.assertEqual(out["status"], "error", out)
        self.assertEqual(out["items"], [], out)
        self.assertEqual(out.get("message"), message, out)

    def ok(self, data):
        out = self.run_probe(data)
        self.assertEqual(out["status"], "ok", out)
        return out


# --------------------------------------------------------------------------- UT-01


class RunsTest(GithubActionsCase):
    def test_runs_of_two_repositories(self):
        """SPEC-0106:UT-01 — acme/api (Build completed/success, Publish in_progress) e acme/web (Build
        completed/failure, tentativa 2): um item por execução, ordenado por repositório e início, com os campos do
        contrato, duration_seconds só nas terminadas, conclusion "" na em andamento, a URL sem query nem fragmento e
        nenhum título, autor ou branch."""
        # SPEC-0106:UT-01
        self.install()
        out = self.ok(probe_input())
        self.assertEqual(out["items"], EXPECTED_UT01)
        self.assertIs(out["truncated"], False)
        self.assertEqual(self.calls(), [allowed_argv("acme/api"), allowed_argv("acme/web")])

    def test_url_without_user_query_or_fragment(self):
        """SPEC-0106:UT-01 — html_url com usuário, query e fragmento: a URL sai só com esquema, host e caminho."""
        # SPEC-0106:UT-01
        run = gh_run(4001)
        run["html_url"] = "https://pessoa-sentinela-0106:x@github.com/acme/api/actions/runs/4001?a=1&b=2#frag"
        self.install(repos={"acme/api": {"total_count": 1, "workflow_runs": [run]}})
        out = self.ok(probe_input(("acme/api",)))
        self.assertEqual([i["url"] for i in out["items"]], ["https://github.com/acme/api/actions/runs/4001"])

    def test_statuses_of_the_api_pass_through(self):
        """SPEC-0106:UT-01 — queued, waiting, requested e pending saem como a API diz, com conclusion "" e
        duration_seconds null; conclusion null da API vira ""."""
        # SPEC-0106:UT-01
        runs = [gh_run(5000 + n, status=s, conclusion=None, started=f"2026-11-24T10:0{n}:00Z")
                for n, s in enumerate(("queued", "waiting", "requested", "pending"))]
        self.install(repos={"acme/api": {"total_count": 4, "workflow_runs": runs}})
        out = self.ok(probe_input(("acme/api",)))
        self.assertEqual([(i["status"], i["conclusion"], i["duration_seconds"]) for i in out["items"]],
                         [("queued", "", None), ("waiting", "", None), ("requested", "", None), ("pending", "", None)])

    def test_no_run_for_the_commit(self):
        """SPEC-0106:UT-01 — nenhuma execução para o commit: status ok, items [], truncated false."""
        # SPEC-0106:UT-01
        self.install(repos={"acme/api": {"total_count": 0, "workflow_runs": []}})
        out = self.ok(probe_input(("acme/api",)))
        self.assertEqual((out["items"], out["truncated"]), ([], False))


# --------------------------------------------------------------------------- UT-02


class TruncationTest(GithubActionsCase):
    def test_total_count_above_the_returned_runs(self):
        """SPEC-0106:UT-02 — total_count 150 com 100 execuções devolvidas: truncated true."""
        # SPEC-0106:UT-02
        runs = [gh_run(6000 + n, started=f"2026-11-24T10:{n // 60:02d}:{n % 60:02d}Z") for n in range(100)]
        self.install(repos={"acme/api": {"total_count": 150, "workflow_runs": runs}})
        out = self.ok(probe_input(("acme/api",), lines=2000))
        self.assertIs(out["truncated"], True)

    def test_more_runs_than_the_line_limit(self):
        """SPEC-0106:UT-02 — 8 execuções e limits.lines 5: truncated true."""
        # SPEC-0106:UT-02
        runs = [gh_run(7000 + n, started=f"2026-11-24T10:0{n}:00Z") for n in range(8)]
        self.install(repos={"acme/api": {"total_count": 8, "workflow_runs": runs}})
        out = self.ok(probe_input(("acme/api",), lines=5))
        self.assertIs(out["truncated"], True)

    def test_more_than_ten_repositories(self):
        """SPEC-0106:UT-02 — 12 repositórios na entrada: só os 10 primeiros são chamados e truncated true."""
        # SPEC-0106:UT-02
        names = [f"acme/r{n:02d}" for n in range(1, 13)]
        repos = {name: {"total_count": 1, "workflow_runs": [gh_run(8000 + i, name)]} for i, name in enumerate(names)}
        self.install(repos=repos)
        out = self.ok(probe_input(names))
        self.assertIs(out["truncated"], True)
        self.assertEqual(self.calls(), [allowed_argv(name) for name in names[:10]])
        self.assertEqual(sorted({i["repository"] for i in out["items"]}), names[:10])


# --------------------------------------------------------------------------- UT-03


class ErrorTest(GithubActionsCase):
    def test_gh_missing_from_the_path(self):
        """SPEC-0106:UT-03 — sem gh no PATH: "gh não encontrado"."""
        # SPEC-0106:UT-03
        self.install()
        self.assertError(self.run_probe(probe_input(), with_gh=False), "gh não encontrado")

    def test_gh_failures_become_fixed_messages(self):
        """SPEC-0106:UT-03 — 401, gh sem login, 403, 403 e 429 de limite, timeout de rede e JSON inválido, em qualquer
        repositório: status error com a mensagem fixa do contrato, items [], sem o stderr do gh nem o token."""
        # SPEC-0106:UT-03
        for mode, message in ERRORS.items():
            for where in ("*", "acme/web"):
                with self.subTest(mode=mode, where=where):
                    self.install(fail={where: mode})
                    self.assertError(self.run_probe(probe_input()), message)

    def test_404_in_one_repository(self):
        """SPEC-0106:UT-03 — 404 em acme/x: {"repository": "acme/x", "found": false} e os itens de acme/api seguem,
        na ordem do repositório."""
        # SPEC-0106:UT-03
        self.install()
        out = self.ok(probe_input(("acme/api", "acme/x")))
        self.assertEqual(out["items"], EXPECTED_UT01[:2] + [{"repository": "acme/x", "found": False}])
        self.install(fail={"acme/api": "404"})
        out = self.ok(probe_input(("acme/api", "acme/web")))
        self.assertEqual(out["items"], [{"repository": "acme/api", "found": False}, EXPECTED_UT01[2]])


# --------------------------------------------------------------------------- UT-04


class AllowListTest(GithubActionsCase):
    def test_every_call_is_the_allowed_one(self):
        """SPEC-0106:UT-04 — numa execução normal, o registro do gh falso tem exatamente um argv permitido por
        repositório, nenhum outro (nada de --paginate, --input, POST, workflow, run, rerun)."""
        # SPEC-0106:UT-04
        self.install()
        self.ok(probe_input())
        calls = self.calls()
        self.assertEqual(calls, [allowed_argv("acme/api"), allowed_argv("acme/web")])
        for argv in calls:
            for word in ("--paginate", "--input", "POST", "PATCH", "PUT", "DELETE", "workflow", "rerun",
                         "dispatch", "cancel"):
                self.assertNotIn(word, " ".join(argv))

    def test_inputs_out_of_the_rule_are_refused_without_any_call(self):
        """SPEC-0106:UT-04 — commit de 7 caracteres, com maiúsculas ou com g; repositório -x/api, .x/api, acme/-x,
        acme/../x, acme/..x, acme/api?x=1, acme/api#x, acme/api&x, acme/api/extra, sem dono; lista vazia: "entrada
        inválida" sem nenhuma chamada. Verbo diferente de runs: "entrada inválida" ou "chamada não permitida", sem
        chamada."""
        # SPEC-0106:UT-04
        cases = [("commit curto", probe_input(commit=COMMIT[:7])),
                 ("commit maiúsculo", probe_input(commit=COMMIT.upper())),
                 ("commit com g", probe_input(commit="g" + COMMIT[1:])),
                 ("lista vazia", probe_input(repositories=()))]
        for repository in ("-x/api", ".x/api", "acme/-x", "acme/.x", "acme/../x", "acme/..x", "acme/api?x=1",
                           "acme/api#x", "acme/api&x", "acme/api/extra", "api", "acme/", "/api", "acme/a pi"):
            cases.append((repository, probe_input(repositories=("acme/api", repository))))
        for name, data in cases:
            with self.subTest(case=name):
                self.install()
                out = self.run_probe(data)
                self.assertError(out, INVALID_INPUT)
                self.assertEqual(self.calls(), [])
        for verb in ("rerun", "dispatch", "status"):
            with self.subTest(verb=verb):
                self.install()
                out = self.run_probe(probe_input(verb=verb))
                self.assertEqual((out["status"], out["items"]), ("error", []), out)
                self.assertIn(out.get("message"), (INVALID_INPUT, REFUSED))
                self.assertEqual(self.calls(), [])

    def test_input_out_of_the_contract_is_refused(self):
        """SPEC-0106:UT-04 — sem target.change, com capability errada ou contract probe@1: "entrada inválida" sem
        chamada."""
        # SPEC-0106:UT-04
        no_change = probe_input()
        del no_change["target"]["change"]
        other_cap = dict(probe_input(), capability="gitops")
        old = dict(probe_input(), contract="probe@1")
        for name, data in (("sem change", no_change), ("capability", other_cap), ("probe@1", old)):
            with self.subTest(case=name):
                self.install()
                result = self.adapter(stdin=json.dumps(data))
                self.assertEqual(result.returncode, 0, output(result))
                out = json.loads(result.stdout)
                self.assertEqual((out["status"], out.get("message")), ("error", INVALID_INPUT), out)
                self.assertEqual(self.calls(), [])

    def test_the_token_reaches_gh_only_from_the_environment(self):
        """SPEC-0106:UT-04 — o gh recebe o GH_TOKEN do ambiente do adaptador (o que o núcleo deu) e nada o põe no
        argv; sem GH_TOKEN no ambiente, o gh não recebe nenhum."""
        # SPEC-0106:UT-04
        self.install()
        self.ok(probe_input(("acme/api",)))
        rows = read_rows(self.record)
        self.assertEqual([r["gh_token"] for r in rows], [TOKEN])
        self.assertNotIn(TOKEN, json.dumps([r["argv"] for r in rows]))
        self.install()
        self.run_probe(probe_input(("acme/api",)), token=False)
        self.assertEqual([r["gh_token"] for r in read_rows(self.record)], [None])


# --------------------------------------------------------------------------- CT-01

DOC_BLOCK_RE = re.compile(r"```json probe@2 (describe|input|output) (valid|invalid)[ \t]*\n(.*?)```", re.DOTALL)
VALIDATORS = {"describe": "validate_probe_describe", "input": "validate_probe_input",
              "output": "validate_probe_output"}


class ContractTest(GithubActionsCase):
    def test_describe_follows_probe_2(self):
        """SPEC-0106:CT-01 — `github-actions.py --describe` imprime exatamente a descrição do contrato, aceita pelo
        validate_probe_describe do núcleo, sem chamar o gh."""
        # SPEC-0106:CT-01
        self.install()
        result = self.adapter("--describe")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(data, DESCRIBE)
        self.assertEqual(f("validate_probe_describe")(data), [])
        self.assertEqual(self.calls(), [])

    def test_real_inputs_and_outputs_pass_the_core_validators(self):
        """SPEC-0106:CT-01 — a entrada usada passa no validate_probe_input; as saídas reais de runs (com e sem 404) e
        de cada erro passam no validate_probe_output (run_probe)."""
        # SPEC-0106:CT-01
        data = probe_input(("acme/api", "acme/x"))
        self.assertEqual(f("validate_probe_input")(data), [])
        self.install()
        self.assertEqual(self.run_probe(data)["status"], "ok")
        for mode in ERRORS:
            with self.subTest(mode=mode):
                self.install(fail={"*": mode})
                self.assertEqual(self.run_probe(data)["status"], "error")

    def test_examples_of_the_reference(self):
        """SPEC-0106:CT-01 — references/probes/github-actions.md traz blocos ```json probe@2 <tipo> <valid|invalid>:
        ao menos o describe válido (igual ao do contrato), uma saída válida de runs e uma saída inválida; os válidos
        passam nos validadores do núcleo e os inválidos são recusados com motivo; nenhum bloco válido traz título,
        autor, branch nem URL com query."""
        # SPEC-0106:CT-01
        self.assertTrue(REFERENCE.is_file(), f"{REFERENCE.relative_to(SKILL)} não existe ({SPEC})")
        text = REFERENCE.read_text(encoding="utf-8")
        blocks = [(m.group(1), m.group(2), json.loads(m.group(3))) for m in DOC_BLOCK_RE.finditer(text)]
        self.assertIn(DESCRIBE, [b[2] for b in blocks if b[:2] == ("describe", "valid")], "sem o describe valid")
        self.assertTrue([b for b in blocks if b[:2] == ("output", "valid") and b[2].get("status") == "ok"],
                        "sem saída ok de runs")
        self.assertTrue([b for b in blocks if b[:2] == ("output", "invalid")], "sem saída inválida")
        for kind, verdict, data in blocks:
            with self.subTest(kind=kind, verdict=verdict, data=json.dumps(data)[:80]):
                problems = f(VALIDATORS[kind])(data)
                if verdict == "valid":
                    self.assertEqual(problems, [])
                else:
                    self.assertTrue(problems and all(isinstance(p, str) and p for p in problems), problems)
        valid = "\n".join(json.dumps(b[2]) for b in blocks if b[1] == "valid")
        for value in ("display_title", "head_branch", "actor", "?"):
            self.assertNotIn(value, valid)


if __name__ == "__main__":
    unittest.main()
