"""Mapa de acesso: ambientes marcados, workloads e acesso local por cluster (SPEC-0087: CH-01, UT-01 a UT-05, IT-01 e
CT-01; ADR-0010, ADR-0011, ADR-0023).

Contrato (seção 6 da SPEC-0087) que estes testes fixam:

    atlas-config.yml (compartilhado), chave opcional:
        environments:
          dev: {tier: test}
          qa:  {tier: production}
        inválido (tier fora de test|production, nome fora da regra, valor que não é mapa) -> exit 2 em config --json,
        build e lint com "environments: item N inválido — <motivo>", sem o texto do item.
    build: environment do mapa -> attrs.tier; fora do mapa -> sem tier.
    config.yml (local; na forma com vários atlas, dentro da entrada): access.clusters.<cluster>.context (1 a 256
        caracteres, sem quebra de linha); inválido -> exit 2 com "access.clusters: item N inválido — <motivo>"; o
        valor nunca é impresso (config --json, doctor, lint, context).
    coletor argocd: deployment.attrs.workloads = ["<Kind>/<nome>", ...] ordenada, de status.resources com kind em
        {Deployment, StatefulSet, DaemonSet, Rollout} e nome pela regra de nome simples; nenhum -> sem o atributo.
    context --json: cada item de delivery.deployments ganha tier (só com marcação), namespace, workloads e access
        (true | false; só com cluster). Markdown: a linha do ambiente ganha "; tier `x`", "; namespace `x`",
        "; workloads `x`" e "; sem acesso local" quando access é false.
    doctor: AVISO de ambientes sem marcação ("sem marcação: dev, qa (conta como produção)") e AVISO "acesso
        <cluster>" "sem contexto local" (OK "contexto definido", sem o valor).
    lint: regra "untiered-environment" (aviso), um achado por ambiente sem tier.

Leituras literais desta suíte (ver o relatório do test-writer):
    - CH-01 "iguais aos de hoje" = igual ao golden fixtures/access/spec-0087-ch01-golden.json, gravado com o código
      anterior à SPEC-0087 (scan, build, context, doctor e lint pela CLI, com a pasta temporária trocada por <ROOT> e a
      data de hoje por <TODAY>). Como as fixtures já têm namespace e cluster, as chaves "namespace" e "access" de
      delivery.deployments (e as partes "; namespace" e "; sem acesso local" do Markdown) são tiradas antes de
      comparar; "tier" e "workloads" não podem aparecer. No doctor e no lint, só os avisos novos são tirados.
    - Emenda v2: as linhas do doctor seguem "<STATUS> <rótulo> — <detalhe>" e os testes procuram só os pedaços do
      contrato no texto inteiro da linha; access inválido = ERRO no doctor com exit 1, exit 2 em config --json, build
      e lint; access só existe quando o deployment tem cluster; a chave de access.clusters pode ser a URL do
      servidor; no Markdown, depois de cluster, sync e health: tier, namespace, workloads (juntos por ", " num
      trecho em crase só) e "sem acesso local".

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); sem rede; sem kubectl; nomes
genéricos (acme, globex, team-x); o contexto local é só um nome falso.
"""
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import SKILL, TESTS, Sandbox, doctor_lines, fn, output
from test_collector_argocd import function as collector_function
from test_context_delivery import image_link_snapshots
from test_image_repositories import bare_app

SPEC = "SPEC-0087"
FIXTURES = TESTS / "fixtures"
GOLDEN = FIXTURES / "access" / "spec-0087-ch01-golden.json"
IMAGE_LINK_APPS = FIXTURES / "argocd" / "image-link.json"
PREVIOUS_ATLAS = FIXTURES / "previous" / "atlas.py"
REPLAY = "{skill}/tests/fixtures/build/replay.py"
PATTERN = r"^(?:dev|qa)-(?P<service>.+)$"
SECRET_CONTEXT = "dev-ctx-SEGREDO-NAO"
ENV_ITEM_RE = re.compile(r"environments: item (\d+) inválido — \S")
ACCESS_ITEM_RE = re.compile(r"access\.clusters: item (\d+) inválido — \S")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")
NEW_DEPLOYMENT_KEYS = ("tier", "namespace", "workloads", "access")
UNTIERED = "untiered-environment"


def f(name):
    return fn(name, SPEC)


# --------------------------------------------------------------------------- apoio


def collectors_yaml(collectors):
    lines = ["version: 1", "organization: Acme", "mode: local", "language: auto", "stale_days: 14",
             "categories: [code, delivery]", "collectors:"]
    for cid, category, command in collectors:
        lines += [f"  - id: {cid}", f"    category: {category}",
                  "    command: [" + ", ".join(json.dumps(a) for a in command) + "]", "    timeout: 60"]
    lines.append("redaction: {extra_patterns: []}")
    return "\n".join(lines) + "\n"


def github(fixture):
    return ("github", "code", ["python3", "{skill}/assets/collectors/github.py", "--org", "acme", "--input",
                               f"{{skill}}/tests/fixtures/github/{fixture}"])


def argocd(input_path, pattern=True):
    command = ["python3", "{skill}/assets/collectors/argocd.py", "--from", "argocd", "--input", input_path]
    if pattern:
        command += ["--service-pattern", PATTERN]
    return ("argocd", "delivery", command)


IMAGE_LINK_COLLECTORS = [github("image-link"), argocd("{skill}/tests/fixtures/argocd/image-link.json")]


def environments_yaml(items):
    """items = [(nome, valor YAML já formatado)]"""
    return "environments:\n" + "".join(f"  {name}: {value}\n" for name, value in items)


def access_yaml(items, indent=""):
    """items = [(cluster, contexto)]; o contexto vai entre aspas duplas (JSON), para caber quebra de linha."""
    text = f"{indent}access:\n{indent}  clusters:\n"
    for cluster, context in items:
        text += f"{indent}    {json.dumps(cluster)}: {{context: {json.dumps(context)}}}\n"
    return text


def with_resources(apps, resources_by_app):
    data = copy.deepcopy(apps)
    for app in data:
        resources = resources_by_app.get(app["metadata"]["name"])
        if resources is not None:
            app.setdefault("status", {})["resources"] = resources
    return data


def resource(kind, name, namespace="api-dev", group="apps"):
    return {"group": group, "version": "v1", "kind": kind, "namespace": namespace, "name": name,
            "status": "Synced", "health": {"status": "Healthy"}}


def deployments_of(package, key="service:api"):
    services = [s for s in package["services"] if s["key"] == key]
    if not services:
        raise AssertionError(f"{key} não está no pacote: {[s['key'] for s in package['services']]}")
    delivery = services[0].get("delivery")
    if delivery is None:
        raise AssertionError(f"{key} sem delivery (SPEC-0086)")
    return {d["id"]: d for d in delivery["deployments"]}


def env_line(markdown, env, deployment):
    found = [line.strip() for line in markdown.splitlines() if line.strip().startswith(f"- {env}: `{deployment}`")]
    if len(found) != 1:
        raise AssertionError(f"linha do ambiente {env} ({deployment}) não encontrada uma vez:\n{markdown}")
    return found[0]


def all_files_text(root: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted(root.rglob("*")) if p.is_file())


class AccessCase(unittest.TestCase):
    """Atlas novo (init --mode local) num Sandbox, com a configuração local reescrita pelo teste."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        out = self.sandbox.init(mode="local")
        self.assertEqual(out.returncode, 0, output(out))
        self.atlas = self.sandbox.atlas

    def configure(self, collectors, extra=""):
        (self.atlas / "atlas-config.yml").write_text(collectors_yaml(collectors) + extra, encoding="utf-8")

    def write_local(self, extra="", atlas=None):
        text = f"atlas: {json.dumps(str(atlas or self.atlas))}\ncredentials: {{}}\n" + extra
        return self.sandbox.write_local(text)

    def write_apps(self, apps, name="apps.json"):
        (self.atlas / name).write_text(json.dumps(apps), encoding="utf-8")
        return f"{{atlas}}/{name}"

    def cli(self, *args, code=0):
        result = self.sandbox.run(*args)
        self.assertNotIn("Traceback", output(result), output(result))
        if code is not None:
            self.assertEqual(result.returncode, code, output(result))
        return result

    def graph(self):
        return json.loads((self.atlas / "graph.json").read_text(encoding="utf-8"))

    def node(self, key):
        found = [n for n in self.graph()["nodes"] if n["key"] == key]
        if not found:
            raise AssertionError(f"{key} não está no grafo")
        return found[0]

    def doctor_text_lines(self, *extra):
        result = self.cli("doctor", *extra, code=None)
        return result, [f"{s} {i} — {d}" for s, i, d in doctor_lines(result.stdout)]


# --------------------------------------------------------------------------- CH-01


CH01_CASES = {
    # nome: (fixture do github, Applications sem status.resources, --service-pattern, consulta do context); a lista
    # acme é a de fixtures/argocd/acme/argocd-app-list.json sem status.resources (fora do atlas: o lint não a lê)
    "image-link": ("image-link", "{skill}/tests/fixtures/argocd/image-link.json", True, "api"),
    "acme": ("acme", "{skill}/tests/fixtures/access/acme-without-resources.json", False, "api web"),
}


def _normalize(text, root, today):
    text = text.replace(str(root), "<ROOT>")
    text = TIMESTAMP_RE.sub("<TS>", text)
    return text.replace(today, "<TODAY>")


def ch01_outputs(case: "AccessCase", name: str) -> dict:
    """scan + build + context + doctor + lint pela CLI, sem environments, access nem status.resources, normalizados
    (gravam o golden e servem à comparação)."""
    fixture, apps, pattern, query = CH01_CASES[name]
    case.configure([github(fixture), argocd(apps, pattern)])
    case.cli("scan")
    case.cli("build")
    today = json.loads((case.atlas / "snapshots" / "_scan.json").read_text(encoding="utf-8"))["argocd"]["seen_at"]
    root = case.sandbox.root

    def norm(text):
        return _normalize(text, root, today)

    pages = {p.relative_to(case.atlas).as_posix(): norm(p.read_text(encoding="utf-8"))
             for p in sorted(case.atlas.rglob("*.md"))}
    graph = json.loads(norm((case.atlas / "graph.json").read_text(encoding="utf-8")))
    context_json = json.loads(norm(case.cli("context", "--json", *query.split()).stdout))
    context_markdown = norm(case.cli("context", *query.split()).stdout)
    doctor = case.cli("doctor", code=None)
    lint = case.cli("lint", "--json", code=None)
    lint_data = json.loads(norm(lint.stdout))
    return {"graph": graph, "pages": pages, "context_json": context_json, "context_markdown": context_markdown,
            "doctor": [norm(f"{s} {i} — {d}") for s, i, d in doctor_lines(doctor.stdout)],
            "doctor_exit": doctor.returncode, "lint": lint_data["findings"], "lint_errors": lint_data["errors"],
            "lint_exit": lint.returncode}


def without_new_fields(outputs: dict) -> dict:
    """Tira das saídas atuais o que a SPEC-0087 acrescenta sem as chaves novas (ver o docstring do módulo)."""
    data = copy.deepcopy(outputs)
    for service in data["context_json"]["services"]:
        for item in service.get("delivery", {}).get("deployments", []):
            item.pop("namespace", None)
            item.pop("access", None)
    markdown = re.sub(r"; namespace `[^`\n]*`", "", data["context_markdown"])
    data["context_markdown"] = markdown.replace("; sem acesso local", "")
    data["doctor"] = [line for line in data["doctor"]
                      if not (line.startswith("AVISO ") and ("sem marcação" in line or "sem contexto local" in line))]
    data["lint"] = [item for item in data["lint"] if item["rule"] != UNTIERED]
    return data


class CharacterizationTest(AccessCase):
    def test_todays_fixtures_without_the_new_keys_give_todays_outputs(self):
        """SPEC-0087:CH-01 — fixtures image-link e acme (sem status.resources), sem environments nem access: graph.json,
        páginas e pacote do context iguais ao golden gravado antes da mudança (sem tier nem workloads); doctor e lint
        iguais, a não ser pelos avisos novos documentados; o exit de ERRO não muda."""
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        for name in CH01_CASES:
            with self.subTest(fixture=name):
                self.setUp()  # um atlas novo por caso
                want = golden[name]
                got = without_new_fields(ch01_outputs(self, name))
                self.assertTrue(got["context_json"]["services"], "o context não achou serviço: o teste não vale")
                self.assertEqual(got["graph"], want["graph"])
                self.assertEqual(sorted(got["pages"]), sorted(want["pages"]))
                for path, text in want["pages"].items():
                    self.assertEqual(got["pages"][path], text, path)
                self.assertEqual(got["context_json"], want["context_json"])
                self.assertEqual(got["context_markdown"], want["context_markdown"])
                self.assertEqual(got["doctor"], want["doctor"])
                self.assertEqual(got["doctor_exit"], want["doctor_exit"])
                self.assertEqual(got["lint"], want["lint"])
                self.assertEqual((got["lint_errors"], got["lint_exit"]), (want["lint_errors"], want["lint_exit"]))


# --------------------------------------------------------------------------- UT-01


class EnvironmentsTest(AccessCase):
    def test_build_writes_the_tier_of_each_marked_environment(self):
        """SPEC-0087:UT-01 — environments {dev: {tier: test}, qa: {tier: production}}: depois do build,
        environment:dev tem tier test e environment:qa tem tier production; a chave é conhecida (o lint não acusa)."""
        self.configure(IMAGE_LINK_COLLECTORS,
                       environments_yaml([("dev", "{tier: test}"), ("qa", "{tier: production}")]))
        self.cli("config", "--json")
        self.cli("scan")
        self.cli("build")
        self.assertEqual(self.node("environment:dev")["attrs"].get("tier"), "test")
        self.assertEqual(self.node("environment:qa")["attrs"].get("tier"), "production")
        lint = self.cli("lint", code=None)
        self.assertNotIn("environments", output(lint), output(lint))
        self.assertEqual(lint.returncode, 0, output(lint))

    def test_an_environment_outside_the_map_has_no_tier(self):
        """SPEC-0087:UT-01 — com só dev no mapa, environment:qa fica sem tier e environment:dev tem tier test."""
        self.configure(IMAGE_LINK_COLLECTORS, environments_yaml([("dev", "{tier: test}")]))
        self.cli("scan")
        self.cli("build")
        self.assertEqual(self.node("environment:dev")["attrs"].get("tier"), "test")
        self.assertNotIn("tier", self.node("environment:qa")["attrs"])

    def test_an_invalid_item_exits_2_with_the_position_and_without_the_item(self):
        """SPEC-0087:UT-01 — tier staging, nome com espaço ou valor que não é mapa: exit 2 com
        "environments: item 2 inválido — <motivo>" em config --json, build e lint, sem o texto do item."""
        cases = (("tier desconhecido", "qa", "{tier: staging}", ("staging",)),
                 ("nome com espaço", "my env", "{tier: test}", ("my env",)),
                 ("valor que não é mapa", "qa", "weird-value", ("weird-value",)))
        for label, key, value, pieces in cases:
            with self.subTest(caso=label):
                self.configure(IMAGE_LINK_COLLECTORS, environments_yaml([("dev", "{tier: test}"), (key, value)]))
                for command in (("config", "--json"), ("build",), ("lint",)):
                    with self.subTest(command=command[0]):
                        text = output(self.cli(*command, code=2))
                        match = ENV_ITEM_RE.search(text)
                        self.assertIsNotNone(match, text)
                        self.assertEqual(match.group(1), "2")
                        for piece in pieces:
                            self.assertNotIn(piece, text, "a mensagem cita o item")


# --------------------------------------------------------------------------- UT-02


def mapped_deployment(app):
    entities, _ = collector_function("map_application")(app)
    return next(e for e in entities if e["kind"] == "deployment")


class WorkloadsTest(unittest.TestCase):
    def test_only_the_allowed_kinds_sorted(self):
        """SPEC-0087:UT-02 — status.resources com Deployment/api, Service/api, Secret/api-db, Rollout/api-canary e um
        nome inválido: workloads é ["Deployment/api", "Rollout/api-canary"]; o Secret nunca sai."""
        app = bare_app("dev-api")
        app["status"]["resources"] = [
            resource("Rollout", "api-canary", group="argoproj.io"),
            resource("Service", "api", group=""),
            resource("Deployment", "api"),
            resource("Secret", "api-db", group=""),
            resource("Deployment", "bad name"),
        ]
        deployment = mapped_deployment(app)
        self.assertEqual(deployment["attrs"].get("workloads"), ["Deployment/api", "Rollout/api-canary"])
        self.assertNotIn("api-db", json.dumps(deployment))
        self.assertNotIn("bad name", json.dumps(deployment))

    def test_statefulset_and_daemonset_are_workloads_without_repetition(self):
        """SPEC-0087:UT-02 — StatefulSet e DaemonSet também são workloads; repetidos saem uma vez, em ordem."""
        app = bare_app("dev-api")
        app["status"]["resources"] = [resource("StatefulSet", "db"), resource("DaemonSet", "agent"),
                                      resource("StatefulSet", "db"), resource("ConfigMap", "api-config", group="")]
        self.assertEqual(mapped_deployment(app)["attrs"].get("workloads"), ["DaemonSet/agent", "StatefulSet/db"])

    def test_without_a_valid_workload_there_is_no_attribute(self):
        """SPEC-0087:UT-02 — sem status.resources, ou só com Service, Secret e nome inválido: sem o atributo
        workloads (o atributo existe quando há workload: guarda de que o teste vale)."""
        with_one = bare_app("dev-api")
        with_one["status"]["resources"] = [resource("Deployment", "api")]
        self.assertIn("workloads", mapped_deployment(with_one)["attrs"], "o coletor não emite workloads")
        none = bare_app("dev-api")
        self.assertNotIn("workloads", mapped_deployment(none)["attrs"])
        invalid = bare_app("dev-api")
        invalid["status"]["resources"] = [resource("Service", "api", group=""), resource("Secret", "api-db", group=""),
                                          resource("Deployment", "bad name"), {"kind": "Deployment"}]
        self.assertNotIn("workloads", mapped_deployment(invalid)["attrs"])


# --------------------------------------------------------------------------- UT-03


INVALID_CONTEXTS = (  # (caso, contexto, pedaço que não pode sair)
    ("vazio", "", None),
    ("quebra de linha", "ctx-LINHA\nQUEBRADA-NAO", "ctx-LINHA"),
    ("mais de 256", "ctx-LONGO-NAO-" + "x" * 250, "ctx-LONGO-NAO-"),
)


class LocalAccessTest(AccessCase):
    def setUp(self):
        super().setUp()
        self.configure(IMAGE_LINK_COLLECTORS)
        self.cli("scan")

    def test_a_defined_context_counts_and_never_shows(self):
        """SPEC-0087:UT-03 — access.clusters.cluster-dev.context dev-ctx-SEGREDO-NAO: o doctor mostra o acesso de
        cluster-dev como definido; o valor não aparece em config, config --json, doctor, doctor --json, lint,
        lint --json nem context."""
        self.write_local(access_yaml([("cluster-dev", SECRET_CONTEXT)]))
        texts = []
        for command in (("config",), ("config", "--json"), ("lint",), ("lint", "--json"), ("context", "api"),
                        ("context", "--json", "api")):
            texts.append(output(self.cli(*command, code=None)))
        doctor, lines = self.doctor_text_lines()
        texts += [output(doctor), output(self.cli("doctor", "--json", code=None))]
        for text in texts:
            self.assertNotIn(SECRET_CONTEXT, text)
            self.assertNotIn("SEGREDO", text)
        defined = [line for line in lines if line.startswith("OK ") and "acesso cluster-dev" in line]
        self.assertEqual(len(defined), 1, lines)
        self.assertIn("contexto definido", defined[0])
        self.assertEqual(self.cli("config", "--json", code=None).returncode, 0)

    def test_an_invalid_context_exits_2_without_the_value(self):
        """SPEC-0087:UT-03 — contexto vazio, com quebra de linha ou com mais de 256 caracteres no item 2: exit 2 com
        "access.clusters: item 2 inválido — <motivo>" em config --json e lint; o doctor acusa com uma linha ERRO e o
        exit de erro de sempre (1) (Emenda v2); o valor nunca sai."""
        for label, context, piece in INVALID_CONTEXTS:
            with self.subTest(caso=label):
                self.write_local(access_yaml([("cluster-dev", SECRET_CONTEXT), ("cluster-qa", context)]))
                results = [self.cli("config", "--json", code=2), self.cli("lint", code=2)]
                doctor = self.cli("doctor", code=1)
                errors = [f"{st} {i} — {d}" for st, i, d in doctor_lines(doctor.stdout) if st == "ERRO"]
                self.assertTrue([x for x in errors if ACCESS_ITEM_RE.search(x)], output(doctor))
                for result in results + [doctor]:
                    text = output(result)
                    match = ACCESS_ITEM_RE.search(text)
                    self.assertIsNotNone(match, text)
                    self.assertEqual(match.group(1), "2")
                    self.assertNotIn(SECRET_CONTEXT, text)
                    if piece:
                        self.assertNotIn(piece, text)

    def test_a_context_of_256_characters_is_accepted(self):
        """SPEC-0087:UT-03 — o limite é 256: um contexto de 256 caracteres é aceito (config --json exit 0) e conta
        como definido no doctor."""
        context = "ctx-" + "y" * 252
        self.write_local(access_yaml([("cluster-dev", context)]))
        self.assertNotIn(context, output(self.cli("config", "--json")))
        _, lines = self.doctor_text_lines()
        self.assertTrue([line for line in lines if line.startswith("OK ") and "acesso cluster-dev" in line], lines)


class MultiAtlasAccessTest(unittest.TestCase):
    """Forma com vários atlas: cada entrada tem o seu access."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.acme = self.make_atlas(self.box.root / "work" / "acme-atlas", "Acme")
        self.globex = self.make_atlas(self.box.root / "work" / "globex-atlas", "Globex")
        text = ("default: acme\natlases:\n"
                f"  acme:\n    atlas: {json.dumps(str(self.acme))}\n    credentials: {{}}\n"
                + access_yaml([("cluster-dev", "ctx-acme-NAO")], indent="    ")
                + f"  globex:\n    atlas: {json.dumps(str(self.globex))}\n    credentials: {{}}\n"
                + access_yaml([("cluster-qa", "ctx-globex-NAO")], indent="    "))
        self.box.write_local(text)

    def make_atlas(self, path, organization):
        path.mkdir(parents=True)
        scratch = self.box.root / "scratch" / path.name
        out = self.box.init(atlas=path, org=organization, mode="local", config_home=scratch)
        self.assertEqual(out.returncode, 0, output(out))
        text = collectors_yaml(IMAGE_LINK_COLLECTORS).replace("organization: Acme", f"organization: {organization}")
        (path / "atlas-config.yml").write_text(text, encoding="utf-8")
        out = self.box.run("scan", config_home=scratch)
        self.assertEqual(out.returncode, 0, output(out))
        return path

    def test_each_atlas_uses_its_own_access(self):
        """SPEC-0087:UT-03 — acme tem acesso a cluster-dev e globex a cluster-qa: doctor --atlas e context --json
        --atlas de cada um mostram o seu acesso (dev-api true/false conforme o atlas); nenhum valor sai."""
        want = {"acme": ("cluster-dev", "cluster-qa", {"dev-api": True, "qa-api": False}),
                "globex": ("cluster-qa", "cluster-dev", {"dev-api": False, "qa-api": True})}
        for name, (defined, missing, access) in want.items():
            with self.subTest(atlas=name):
                doctor = self.box.run("doctor", "--atlas", name)
                self.assertNotIn("Traceback", output(doctor))
                lines = [f"{s} {i} — {d}" for s, i, d in doctor_lines(doctor.stdout)]
                self.assertTrue([x for x in lines if x.startswith("OK ") and f"acesso {defined}" in x],
                                output(doctor))
                self.assertTrue([x for x in lines if x.startswith("AVISO ") and f"acesso {missing}" in x
                                 and "sem contexto local" in x], output(doctor))
                context = self.box.run("context", "--json", "--atlas", name, "api")
                self.assertEqual(context.returncode, 0, output(context))
                deployments = deployments_of(json.loads(context.stdout))
                self.assertEqual({d: deployments[d].get("access") for d in access}, access)
                for text in (output(doctor), output(context)):
                    self.assertNotIn("ctx-acme-NAO", text)
                    self.assertNotIn("ctx-globex-NAO", text)


# --------------------------------------------------------------------------- UT-04


class ContextFieldsTest(AccessCase):
    """Snapshots gravados (replay) com namespace e workloads (dev-api com dois); dev marcado como test."""

    URL_CLUSTER = "https://kubernetes.default.svc"

    def write_snapshots(self, dev_cluster="cluster-dev", qa_cluster=True):
        """dev-api roda em `dev_cluster`; sem `qa_cluster`, qa-api fica sem cluster no grafo (Emenda v2)."""
        snapshots = image_link_snapshots()
        gitops = snapshots["gitops"]
        workloads = {"dev-api": ["StatefulSet/api-cache", "Deployment/api"], "qa-api": ["Deployment/api"]}
        for entity in gitops["entities"]:
            if entity["kind"] == "deployment":
                entity["attrs"]["namespace"] = f"api-{entity['id'].split('-', 1)[0]}"
                entity["attrs"]["workloads"] = sorted(workloads[entity["id"]])
            if entity["kind"] == "cluster" and entity["id"] == "cluster-dev":
                entity["id"] = entity["name"] = dev_cluster
        for relation in gitops["relations"]:
            if relation["to"] == "cluster:cluster-dev":
                relation["to"] = f"cluster:{dev_cluster}"
        if not qa_cluster:
            gitops["entities"] = [e for e in gitops["entities"] if (e["kind"], e["id"]) != ("cluster", "cluster-qa")]
            gitops["relations"] = [r for r in gitops["relations"] if r["to"] != "cluster:cluster-qa"]
        facts = self.atlas / "facts"
        facts.mkdir(exist_ok=True)
        for cid, data in snapshots.items():
            (facts / f"{cid}.json").write_text(json.dumps(data), encoding="utf-8")
        self.collectors = [("scm", "code", ["python3", REPLAY, "scm", "code", "{atlas}/facts/scm.json"]),
                           ("gitops", "delivery", ["python3", REPLAY, "gitops", "delivery",
                                                   "{atlas}/facts/gitops.json"])]

    def run_context(self, environments, access, **snapshot_options):
        self.write_snapshots(**snapshot_options)
        self.configure(self.collectors, environments_yaml(environments) if environments else "")
        self.write_local(access_yaml(access) if access else "")
        self.cli("scan")
        self.cli("build")
        package = json.loads(self.cli("context", "--json", "api").stdout)
        return deployments_of(package), self.cli("context", "api").stdout

    def test_json_and_markdown_bring_tier_namespace_workloads_and_access(self):
        """SPEC-0087:UT-04 (Emenda v2) — dev (tier test, acesso a cluster-dev, dois workloads) e qa (sem tier, sem
        acesso): dev-api traz tier test, namespace api-dev, workloads ordenados e access true; qa-api não tem tier e
        tem access false. No Markdown, as partes novas vêm depois de cluster, sync e health, na ordem tier,
        namespace, workloads (juntos por ", " num trecho em crase só) e "sem acesso local"."""
        deployments, markdown = self.run_context([("dev", "{tier: test}")], [("cluster-dev", SECRET_CONTEXT)])
        dev, qa = deployments["dev-api"], deployments["qa-api"]
        self.assertEqual({k: dev.get(k) for k in NEW_DEPLOYMENT_KEYS},
                         {"tier": "test", "namespace": "api-dev", "workloads": ["Deployment/api", "StatefulSet/api-cache"],
                          "access": True})
        self.assertNotIn("tier", qa)
        self.assertEqual({k: qa.get(k) for k in ("namespace", "workloads", "access")},
                         {"namespace": "api-qa", "workloads": ["Deployment/api"], "access": False})
        self.assertEqual(env_line(markdown, "dev", "dev-api"),
                         "- dev: `dev-api` — cluster `cluster-dev`; sync `Synced`; health `Healthy`; tier `test`; "
                         "namespace `api-dev`; workloads `Deployment/api, StatefulSet/api-cache`")
        self.assertEqual(env_line(markdown, "qa", "qa-api"),
                         "- qa: `qa-api` — cluster `cluster-qa`; sync `OutOfSync`; health `Degraded`; "
                         "namespace `api-qa`; workloads `Deployment/api`; sem acesso local")
        self.assertNotIn(SECRET_CONTEXT, markdown + json.dumps(deployments))

    def test_without_access_every_deployment_has_access_false(self):
        """SPEC-0087:UT-04 — sem access nesta máquina e sem environments: access false e sem tier nos dois
        deployments; as duas linhas terminam em "; sem acesso local"."""
        deployments, markdown = self.run_context([], [])
        for name in ("dev-api", "qa-api"):
            self.assertIs(deployments[name].get("access"), False, deployments[name])
            self.assertNotIn("tier", deployments[name])
        for env, name in (("dev", "dev-api"), ("qa", "qa-api")):
            self.assertTrue(env_line(markdown, env, name).endswith("; sem acesso local"), markdown)

    def test_a_deployment_without_a_cluster_has_no_access_key(self):
        """SPEC-0087:UT-04 (Emenda v2) — qa-api sem cluster no grafo: sem a chave access e sem "sem acesso local" na
        linha; dev-api (com cluster e acesso) continua com access true."""
        deployments, markdown = self.run_context([], [("cluster-dev", SECRET_CONTEXT)], qa_cluster=False)
        self.assertEqual(deployments["qa-api"]["clusters"], [], "qa-api ainda tem cluster: o teste não vale")
        self.assertNotIn("access", deployments["qa-api"])
        self.assertIs(deployments["dev-api"].get("access"), True, deployments["dev-api"])
        qa_line = env_line(markdown, "qa", "qa-api")
        self.assertNotIn("acesso", qa_line)
        self.assertTrue(qa_line.endswith("; workloads `Deployment/api`"), qa_line)

    def test_a_cluster_named_by_its_server_url_is_a_valid_access_key(self):
        """SPEC-0087:UT-03 e UT-04 (Emenda v2) — o cluster de dev-api é a URL do servidor
        (https://kubernetes.default.svc): access.clusters com essa chave é aceito (config --json exit 0), dev-api tem
        access true, o doctor mostra o OK "contexto definido" desse cluster e o valor não sai."""
        deployments, markdown = self.run_context([], [(self.URL_CLUSTER, SECRET_CONTEXT)], dev_cluster=self.URL_CLUSTER)
        self.assertEqual(deployments["dev-api"]["clusters"], [self.URL_CLUSTER])
        self.assertIs(deployments["dev-api"].get("access"), True, deployments["dev-api"])
        self.assertIs(deployments["qa-api"].get("access"), False, deployments["qa-api"])
        config = self.cli("config", "--json")
        doctor, lines = self.doctor_text_lines()
        defined = [x for x in lines if x.startswith("OK ") and f"acesso {self.URL_CLUSTER}" in x]
        self.assertEqual(len(defined), 1, lines)
        self.assertIn("contexto definido", defined[0])
        for text in (markdown, json.dumps(deployments), output(config), output(doctor)):
            self.assertNotIn(SECRET_CONTEXT, text)


# --------------------------------------------------------------------------- UT-05


class WarningsTest(AccessCase):
    def setUp(self):
        super().setUp()
        self.configure(IMAGE_LINK_COLLECTORS)
        self.cli("scan")

    def test_doctor_warns_of_untiered_environments_and_clusters_without_access(self):
        """SPEC-0087:UT-05 — sem environments nem access: o doctor mostra o AVISO de ambientes sem marcação (dev, qa,
        conta como produção) e um AVISO de acesso por cluster (cluster-dev, cluster-qa); o exit é o de antes (0)."""
        doctor, lines = self.doctor_text_lines()
        untiered = [line for line in lines if line.startswith("AVISO ") and "sem marcação" in line]
        self.assertEqual(len(untiered), 1, lines)
        self.assertIn("dev, qa", untiered[0])
        self.assertIn("conta como produção", untiered[0])
        for cluster in ("cluster-dev", "cluster-qa"):
            found = [line for line in lines if line.startswith("AVISO ") and f"acesso {cluster}" in line]
            self.assertEqual(len(found), 1, lines)
            self.assertIn("sem contexto local", found[0])
        self.assertEqual(doctor.returncode, 0, output(doctor))

    def test_lint_has_one_untiered_environment_warning_per_environment(self):
        """SPEC-0087:UT-05 — o lint tem um achado untiered-environment (aviso) para dev e outro para qa; com dev
        marcado, só o de qa; os achados não mudam o exit de ERRO (0)."""
        lint = self.cli("lint", "--json", code=0)
        findings = [x for x in json.loads(lint.stdout)["findings"] if x["rule"] == UNTIERED]
        self.assertEqual(len(findings), 2, findings)
        self.assertTrue(all(x["severity"] == "warn" for x in findings), findings)
        self.assertTrue(any("dev" in (x["path"] + x["detail"]) for x in findings), findings)
        self.assertTrue(any("qa" in (x["path"] + x["detail"]) for x in findings), findings)
        self.configure(IMAGE_LINK_COLLECTORS, environments_yaml([("dev", "{tier: test}")]))
        self.cli("build")
        findings = [x for x in json.loads(self.cli("lint", "--json", code=0).stdout)["findings"]
                    if x["rule"] == UNTIERED]
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("qa", findings[0]["path"] + findings[0]["detail"])
        self.assertIn(UNTIERED, output(self.cli("lint", code=0)))

    def test_all_marked_and_accessible_gives_no_new_warning(self):
        """SPEC-0087:UT-05 — com dev e qa marcados e acesso aos dois clusters: nenhum AVISO de marcação nem de
        acesso, dois OK "contexto definido" e nenhum achado untiered-environment."""
        self.configure(IMAGE_LINK_COLLECTORS,
                       environments_yaml([("dev", "{tier: test}"), ("qa", "{tier: production}")]))
        self.write_local(access_yaml([("cluster-dev", "ctx-a-NAO"), ("cluster-qa", "ctx-b-NAO")]))
        self.cli("build")
        _, lines = self.doctor_text_lines()
        self.assertFalse([x for x in lines if "sem marcação" in x or "sem contexto local" in x], lines)
        self.assertEqual(len([x for x in lines if x.startswith("OK ") and "contexto definido" in x]), 2, lines)
        lint = json.loads(self.cli("lint", "--json", code=0).stdout)
        self.assertFalse([x for x in lint["findings"] if x["rule"] == UNTIERED])
        self.assertIn(UNTIERED, lint["rules"], "a regra nova não está na lista de regras")


# --------------------------------------------------------------------------- IT-01


IT01_CONTEXT = "ctx-local-IT01-NAO"


class EndToEndTest(AccessCase):
    def test_scan_build_and_context_give_the_new_fields_and_never_the_local_context(self):
        """SPEC-0087:IT-01 — fixtures image-link com status.resources, environments {dev: test, qa: production} e
        access a cluster-dev: scan, build e context --json "api" dão dev-api {tier test, namespace api-dev, workloads
        [Deployment/api], access true} e qa-api {tier production, namespace api-qa, workloads [Deployment/api,
        StatefulSet/api-cache], access false}; o contexto local não está em nenhum arquivo do atlas nem em saída
        nenhuma, e o Secret listado não sai."""
        apps = with_resources(json.loads(IMAGE_LINK_APPS.read_text(encoding="utf-8")), {
            "dev-api": [resource("Deployment", "api"), resource("Service", "api", group=""),
                        resource("Secret", "api-db-creds", group="")],
            "qa-api": [resource("StatefulSet", "api-cache", "api-qa"), resource("Deployment", "api", "api-qa")],
        })
        self.configure([github("image-link"), argocd(self.write_apps(apps))],
                       environments_yaml([("dev", "{tier: test}"), ("qa", "{tier: production}")]))
        self.write_local(access_yaml([("cluster-dev", IT01_CONTEXT)]))
        outputs = [output(self.cli("scan")), output(self.cli("build"))]
        context = self.cli("context", "--json", "api")
        outputs.append(output(context))
        deployments = deployments_of(json.loads(context.stdout))
        self.assertEqual({k: deployments["dev-api"].get(k) for k in NEW_DEPLOYMENT_KEYS},
                         {"tier": "test", "namespace": "api-dev", "workloads": ["Deployment/api"], "access": True})
        self.assertEqual({k: deployments["qa-api"].get(k) for k in NEW_DEPLOYMENT_KEYS},
                         {"tier": "production", "namespace": "api-qa",
                          "workloads": ["Deployment/api", "StatefulSet/api-cache"], "access": False})
        for command in (("context", "api"), ("config",), ("config", "--json"), ("doctor",), ("doctor", "--json"),
                        ("lint",), ("lint", "--json"), ("build", "--json")):
            outputs.append(output(self.cli(*command, code=None)))
        atlas_text = all_files_text(self.atlas)
        for text in outputs + [atlas_text]:
            self.assertNotIn(IT01_CONTEXT, text)
            self.assertNotIn("api-db-creds", text)


# --------------------------------------------------------------------------- CT-01


def previous_atlas():
    spec = importlib.util.spec_from_file_location("boson_atlas_previous_spec0087", PREVIOUS_ATLAS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractTest(AccessCase):
    def collector_snapshot(self, resources):
        apps = with_resources(json.loads(IMAGE_LINK_APPS.read_text(encoding="utf-8")),
                              {"dev-api": resources, "qa-api": resources})
        path = self.atlas / "apps-ct01.json"
        path.write_text(json.dumps(apps), encoding="utf-8")
        environ = dict(os.environ, HOME=str(self.sandbox.home), XDG_CONFIG_HOME=str(self.sandbox.home / ".config"))
        out = subprocess.run([sys.executable, str(SKILL / "assets" / "collectors" / "argocd.py"), "--from", "argocd",
                              "--input", str(path), "--service-pattern", PATTERN], check=False, capture_output=True,
                             text=True, env=environ, cwd=self.sandbox.root, timeout=120)
        self.assertEqual(out.returncode, 0, output(out))
        return json.loads(out.stdout)

    def test_a_snapshot_with_workloads_is_accepted_by_contract_one_and_by_the_previous_version(self):
        """SPEC-0087:CT-01 — o snapshot do argocd com workloads (lista de escalares) passa no validador @1 atual sem
        violação nem campo descartado, e no validador da versão anterior (fixtures/previous), que ignora o atributo
        desconhecido sem violação."""
        data = self.collector_snapshot([resource("Deployment", "api")])
        deployments = [e for e in data["entities"] if e["kind"] == "deployment"]
        self.assertTrue(deployments)
        for item in deployments:
            self.assertEqual(item["attrs"].get("workloads"), ["Deployment/api"], "o coletor não emite workloads")
        for label, validate in (("atual", f("validate_collector_output")),
                                ("anterior", previous_atlas().validate_collector_output)):
            with self.subTest(validador=label):
                clean, violations, dropped = validate(copy.deepcopy(data))
                self.assertEqual(violations, [])
                self.assertEqual(dropped, [])
                kept = [e for e in clean["entities"] if e["kind"] == "deployment"]
                self.assertTrue(all(isinstance(v, str) for e in kept for v in e["attrs"].get("workloads", [])))

    def test_without_the_attribute_the_graph_is_todays(self):
        """SPEC-0087:CT-01 — o grafo do snapshot com workloads, tirado o atributo, é igual ao grafo do snapshot sem
        status.resources (o atributo não cria nó nem aresta)."""
        with_workloads = self.collector_snapshot([resource("Deployment", "api")])
        self.assertTrue(any("workloads" in e["attrs"] for e in with_workloads["entities"]),
                        "o coletor não emite workloads")
        without = self.collector_snapshot([])
        state = {"argocd": {"seen_at": "2026-11-23", "status": "ok", "entities": 1, "relations": 0}}

        def graph_of(snapshot):
            merged = f("merge_snapshots")({"argocd": snapshot}, ["argocd"], state)
            return json.loads(f("render_graph")(f("infer_relations")(merged), "Acme", "2026-11-23"))

        graph = graph_of(with_workloads)
        for node in graph["nodes"]:
            node["attrs"].pop("workloads", None)
        self.assertEqual(graph, graph_of(without))


# --------------------------------------------------------------------------- gravação do golden do CH-01


def record_golden():  # pragma: no cover — rodado uma vez, com o código anterior à SPEC-0087
    golden = {}
    for name in CH01_CASES:
        case = AccessCase()
        case.setUp()
        try:
            golden[name] = ch01_outputs(case, name)
        finally:
            for cleanup in reversed(case._cleanups):
                cleanup[0](*cleanup[1], **cleanup[2])
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
