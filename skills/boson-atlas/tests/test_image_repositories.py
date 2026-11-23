"""Serviço ligado ao repositório do código pela imagem e caminho de entrega no build (SPEC-0082: CH-01, UT-01 a
UT-07, IT-01 e CT-01; ADR-0022).

Contrato (seção 6 da SPEC-0082) que estes testes fixam:

    Coletor argocd (assets/collectors/argocd.py)
        deployment.attrs.images: lista ordenada, sem repetição, de status.summary.images mais o parâmetro Helm ou a
            chave de values image.repository; cada imagem sem esquema (oci://, docker://), tag, digest nem host do
            registry (primeiro segmento com "." ou ":" ou igual a localhost), em minúsculas e casando
            ^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*$; credencial na URL ou caractere fora da regra = imagem
            descartada inteira (nenhum pedaço sai, nem no stderr).
        --service-pattern REGEX (grupo nomeado "service"): depois do rótulo e do nameOverride, antes do
            metadata.name; grupo que não casa ou não é um nome simples cai no metadata.name; regex inválida ou sem o
            grupo "service" = exit 2 com "--service-pattern inválido: <motivo>".
    atlas-config.yml (compartilhado): image_repositories {<imagem normalizada>: <dono>/<repositório>}; item inválido
        = exit 2 com "image_repositories: item N inválido — <motivo>" (N a partir de 1), sem nenhum texto do item, em
        config --json, build e lint.
    build, regra 4: deployment com deploys -> service:S e images -> S sourced_from repository (inferred, evidence
        "image:<I>"): mapa explícito, senão <dono>/<nome> igual, senão último segmento igual ao nome de um único
        repositório; senão nada.
    Página do serviço: "Repositórios" em "Código" (arestas image:) e "Configuração (GitOps)" (demais) só quando há
        aresta image:; região "Do commit até o pod" só quando há repositório de Código, com, na ordem, repositório do
        código, pipelines, imagem(ns), repositório de configuração e um item por deployment (ambiente, cluster,
        sync_status, health_status), sem texto de ferramenta fixo.

Leituras literais desta suíte (ver o relatório do test-writer):
    - CH-01: "páginas iguais às de hoje" = texto idêntico ao golden fixtures/build/spec-0082-ch01-golden.json, gerado
      com o código anterior à SPEC-0082 a partir dos snapshots acme sem `images`. Logo a região nova não pode ir para o
      modelo assets/pages/service.md: ela entra na página só quando há repositório de Código.
    - "a região não aparece" = o texto "Do commit até o pod" não está na página.
    - A região "Do commit até o pod" vai do título até o próximo título "## " (ou o fim da página).

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); sem rede; fixtures só com acme,
globex e team-x.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import TESTS, Sandbox, fn, output
from test_build import ACME_ORDER, acme_snapshots, regions, state
from test_collector_argocd import ARGOCD, ARGOCD_LIST, function

SPEC = "SPEC-0082"
FIXTURES = TESTS / "fixtures"
GOLDEN = FIXTURES / "build" / "spec-0082-ch01-golden.json"
IMAGE_LINK_APPS = FIXTURES / "argocd" / "image-link.json"
IMAGE_LINK_GITHUB = FIXTURES / "github" / "image-link"
REPLAY = "{skill}/tests/fixtures/build/replay.py"
DAY = "2026-10-30"
BUILT_AT = f"{DAY}T12:00:00Z"
PATTERN = r"^(?:dev|qa)-(?P<service>.+)$"
REGION_TITLE = "Do commit até o pod"
CODE_LABEL = "Código"
CONFIG_LABEL = "Configuração (GitOps)"
SERVICE_REGIONS_COMPARED = ("repository", "deployments", "depends-on", "used-by", "owners", "pipelines")
IMAGE_ITEM_RE = re.compile(r"image_repositories: item (\d+) inválido — \S")
PATTERN_INVALID = "--service-pattern inválido: "


# --------------------------------------------------------------------------- apoio


def ent(kind, eid, attrs=None, source="x", name=None):
    return {"kind": kind, "id": eid, "name": name or eid, "attrs": attrs or {}, "source": source}


def rel(src, rtype, dst, source="x"):
    return {"from": src, "to": dst, "type": rtype, "source": source}


def snap(cid, entities, relations=(), category="code"):
    return {"contract": "boson-atlas/collector@1", "collector": cid, "category": category,
            "collected_at": BUILT_AT, "entities": list(entities), "relations": list(relations)}


def repo(full, source="scm"):
    """repository:<dono>/<nome> como o coletor github emite (name = só o nome)."""
    return ent("repository", full, {"default_branch": "main"}, source, name=full.split("/", 1)[1])


def build_graph(snapshots, order):
    merged = fn("merge_snapshots", SPEC)(snapshots, order, state(*order))
    return fn("infer_relations", SPEC)(merged)


def edges_of(graph, src=None, rtype=None, dst=None):
    return [e for e in graph["edges"] if (src is None or e["from"] == src) and (rtype is None or e["type"] == rtype)
            and (dst is None or e["to"] == dst)]


def image_edges(graph):
    return [e for e in graph["edges"] if str(e.get("evidence", "")).startswith("image:")]


def without_images(snapshot):
    """Cópia do snapshot sem o atributo images dos deployments (o que um coletor anterior à SPEC-0082 grava); sem
    workloads também, que é ainda mais novo (SPEC-0087, Emenda v2: expected-acme.json passou a ter o atributo)."""
    data = copy.deepcopy(snapshot)
    for item in data.get("entities", []):
        if isinstance(item.get("attrs"), dict):
            item["attrs"].pop("images", None)
            item["attrs"].pop("workloads", None)
    return data


def golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def flow_region(text):
    """Texto da região "Do commit até o pod": do título até o próximo "## " (ou o fim); None sem o título."""
    start = text.find(REGION_TITLE)
    if start < 0:
        return None
    rest = text[start + len(REGION_TITLE):]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def atlas_config(collectors, categories="[code, delivery]", extra=""):
    lines = ["version: 1", "organization: Acme", "mode: local", "language: auto", "stale_days: 14",
             f"categories: {categories}", "collectors:"]
    for cid, category, command in collectors:
        lines += [f"  - id: {cid}", f"    category: {category}",
                  "    command: [" + ", ".join(json.dumps(a) for a in command) + "]", "    timeout: 60"]
    lines.append("redaction: {extra_patterns: []}")
    return "\n".join(lines) + "\n" + extra


def bare_app(name, images=(), source=None, labels=None):
    """Application mínima, sem rótulo de serviço nem nameOverride (a não ser que source/labels tragam)."""
    spec = {"project": "team-x", "destination": {"name": "cluster-dev", "namespace": "dev"},
            "source": source or {"repoURL": "https://github.com/acme/iac.git", "path": f"apps/{name}"}}
    metadata = {"name": name, "namespace": "argocd"}
    if labels is not None:
        metadata["labels"] = labels
    status = {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}}
    if images:
        status["summary"] = {"images": list(images)}
    return {"metadata": metadata, "spec": spec, "status": status}


def deployment_of(entities):
    return next(e for e in entities if e["kind"] == "deployment")


class CollectorCliCase(unittest.TestCase):
    """argocd.py como processo, com HOME temporário e --input (nunca uma CLI real)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write_apps(self, apps):
        path = self.tmp / "apps.json"
        path.write_text(json.dumps(apps), encoding="utf-8")
        return path

    def run_collector(self, *args):
        environ = dict(os.environ, HOME=str(self.tmp), XDG_CONFIG_HOME=str(self.tmp / ".config"))
        result = subprocess.run([sys.executable, str(ARGOCD), *[str(a) for a in args]], check=False, cwd=self.tmp,
                                capture_output=True, text=True, env=environ, timeout=120)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def collect(self, *args):
        result = self.run_collector(*args)
        self.assertEqual(result.returncode, 0, output(result))
        return json.loads(result.stdout), result


class AtlasCase(unittest.TestCase):
    """Atlas novo (init --mode local) num Sandbox."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        out = self.sandbox.init(mode="local")
        self.assertEqual(out.returncode, 0, output(out))
        self.atlas = self.sandbox.atlas

    def configure(self, text):
        (self.atlas / "atlas-config.yml").write_text(text, encoding="utf-8")

    def cli(self, *args, code=0):
        result = self.sandbox.run(*args)
        self.assertNotIn("Traceback", output(result), output(result))
        if code is not None:
            self.assertEqual(result.returncode, code, output(result))
        return result

    def graph(self):
        return json.loads((self.atlas / "graph.json").read_text(encoding="utf-8"))

    def page(self, rel_path):
        return (self.atlas / rel_path).read_text(encoding="utf-8")

    def service_pages(self):
        return {p.name: p.read_text(encoding="utf-8") for p in sorted((self.atlas / "services").glob("*.md"))}


# --------------------------------------------------------------------------- CH-01


class CharacterizationTest(AtlasCase):
    def test_acme_snapshots_without_images_give_todays_graph_and_pages(self):
        """SPEC-0082:CH-01 — os snapshots acme de hoje (github e argocd de expected-acme.json, sem images, e o
        db-facts) dão o graph.json e as páginas do golden gravado antes da mudança: nenhuma aresta nova, nenhuma
        região nova, nenhum "Código"/"Configuração (GitOps)" nem "Do commit até o pod"."""
        want = golden()
        snapshots = {cid: without_images(data) for cid, data in acme_snapshots().items()}
        graph = build_graph(snapshots, ACME_ORDER)
        self.assertEqual(image_edges(graph), [], "aresta com evidência image: sem atributo images")
        self.assertEqual(fn("render_graph", SPEC)(graph, "Acme", BUILT_AT), want["graph"])
        pages = fn("render_pages", SPEC)(graph, {}, "Acme", scans=state(*ACME_ORDER))
        self.assertEqual(sorted(pages), sorted(want["pages"]))
        for path, text in sorted(want["pages"].items()):
            with self.subTest(page=path):
                self.assertEqual(sorted(regions(pages[path])), sorted(regions(text)), "região nova ou que sumiu")
                self.assertEqual(pages[path], text)
                if path.startswith("services/"):
                    for word in (REGION_TITLE, CODE_LABEL, CONFIG_LABEL):
                        self.assertNotIn(word, pages[path])

    def test_scan_and_build_with_the_acme_collectors_give_todays_edges_and_service_regions(self):
        """SPEC-0082:CH-01 — scan e build num atlas temporário com os coletores reais github e argocd sobre as fixtures
        acme de hoje (mais o db-facts): as mesmas arestas do golden (sem aresta nova; a imagem acme/api do api-prod
        e do api-staging já coincide com o repoURL) e as mesmas regiões de repositório, deployments, dependências,
        donos e pipelines, sem região nova."""
        self.configure(atlas_config([
            ("github", "code", ["python3", "{skill}/assets/collectors/github.py", "--org", "acme", "--input",
                                "{skill}/tests/fixtures/github/acme"]),
            ("argocd", "delivery", ["python3", "{skill}/assets/collectors/argocd.py", "--from", "argocd",
                                    "--input", "{skill}/tests/fixtures/argocd/acme/argocd-app-list.json"]),
            ("db-facts", "data", ["python3", "{skill}/assets/collectors/generic.py", "--facts",
                                  "{skill}/tests/fixtures/build/db-facts.json", "--category", "data",
                                  "--source", "db-facts"]),
        ]))
        result = self.cli("scan")
        for cid in ACME_ORDER:
            self.assertRegex(output(result), re.compile(rf"^OK {cid} — ", re.MULTILINE))
        want = golden()
        want_graph = json.loads(want["graph"])
        graph = self.graph()

        def edge_set(g):
            return sorted((e["from"], e["type"], e["to"], bool(e.get("inferred"))) for e in g["edges"])

        self.assertEqual(edge_set(graph), edge_set(want_graph))
        self.assertEqual(sorted(n["key"] for n in graph["nodes"]), sorted(n["key"] for n in want_graph["nodes"]))
        pages = self.service_pages()
        self.assertEqual(sorted(pages), sorted(p[len("services/"):] for p in want["pages"]
                                               if p.startswith("services/")))
        for name, text in pages.items():
            with self.subTest(page=name):
                old = want["pages"][f"services/{name}"]
                self.assertEqual(sorted(regions(text)), sorted(regions(old)), "região nova ou que sumiu")
                for region in SERVICE_REGIONS_COMPARED:
                    self.assertEqual(regions(text)[region], regions(old)[region], region)
                for word in (REGION_TITLE, CODE_LABEL, CONFIG_LABEL):
                    self.assertNotIn(word, text)


# --------------------------------------------------------------------------- UT-01 e UT-02 (coletor)


class ImagesAttributeTest(unittest.TestCase):
    def test_images_are_normalized_sorted_and_without_repetition(self):
        """SPEC-0082:UT-01 — status.summary.images com ghcr.io/acme/api:1.4.2, ghcr.io/acme/api@sha256:abc,
        docker.io/library/redis:7 e o parâmetro Helm image.repository=registry.interno:5000/acme/worker dão
        images = ["acme/api", "acme/worker", "library/redis"]."""
        source = {"repoURL": "https://github.com/acme/iac.git", "path": "apps/api",
                  "helm": {"parameters": [{"name": "image.repository", "value": "registry.interno:5000/acme/worker"},
                                          {"name": "image.tag", "value": "3.3.3"}]}}
        app = bare_app("dev-api", images=["ghcr.io/acme/api:1.4.2", "ghcr.io/acme/api@sha256:abc",
                                          "docker.io/library/redis:7"], source=source)
        entities, _ = function("map_application")(app)
        attrs = deployment_of(entities)["attrs"]
        self.assertIn("images", attrs, "o deployment não traz o atributo images (SPEC-0082)")
        self.assertEqual(attrs["images"], ["acme/api", "acme/worker", "library/redis"])

    def test_image_repository_from_helm_values_object_and_values_text(self):
        """SPEC-0082:UT-01 — a chave image.repository também vem de helm.valuesObject e de helm.values (texto YAML);
        o esquema (oci://, docker://), a porta do registry e localhost saem."""
        cases = (
            ("valuesObject", {"valuesObject": {"image": {"repository": "oci://registry.interno:5000/acme/worker",
                                                         "tag": "3.3.3"}}}, ["acme/worker"]),
            ("values", {"values": "replicaCount: 2\nimage:\n  repository: docker://localhost/acme/worker\n"
                                  "  tag: \"3.3.3\"\n"}, ["acme/worker"]),
            ("localhost:porta", {"parameters": [{"name": "image.repository",
                                                 "value": "localhost:5000/team-x/tool"}]}, ["team-x/tool"]),
        )
        for name, helm, want in cases:
            with self.subTest(origem=name):
                app = bare_app("dev-api", source={"repoURL": "https://github.com/acme/iac.git", "helm": helm})
                entities, _ = function("map_application")(app)
                attrs = deployment_of(entities)["attrs"]
                self.assertIn("images", attrs, "o deployment não traz o atributo images (SPEC-0082)")
                self.assertEqual(attrs["images"], want)

    def test_deployment_without_a_valid_image_has_no_images_attribute(self):
        """SPEC-0082:UT-01 (Emenda v2) — deployment sem nenhuma imagem válida não ganha o atributo images (a chave
        some, nem lista vazia), para o snapshot ficar igual ao de hoje: sem status.summary.images nem
        image.repository, com a lista vazia ou só com imagens descartadas. Ao lado, uma Application com imagem
        válida traz images (o atributo existe)."""
        entities, _ = function("map_application")(bare_app("dev-web", images=["ghcr.io/acme/web:2.0.3"]))
        self.assertEqual(deployment_of(entities)["attrs"].get("images"), ["acme/web"],
                         "o deployment não traz o atributo images (SPEC-0082)")
        empty_summary = bare_app("dev-api")
        empty_summary["status"]["summary"] = {"images": []}
        cases = (
            ("sem imagem", bare_app("dev-api")),
            ("lista vazia", empty_summary),
            ("só imagens descartadas", bare_app("dev-api", images=["user:tok@ghcr.io/acme/api", "ghcr.io/acme/a b"])),
            ("image.repository inválido", bare_app("dev-api", source={
                "repoURL": "https://github.com/acme/iac.git",
                "helm": {"parameters": [{"name": "image.repository", "value": "user:tok@ghcr.io/acme/api"}]}})),
        )
        for name, app in cases:
            with self.subTest(caso=name):
                entities, _ = function("map_application")(app)
                self.assertNotIn("images", deployment_of(entities)["attrs"])


UNSAFE_IMAGES = ("user:tok@ghcr.io/acme/api", "123456789012.dkr.ecr.us-east-1.amazonaws.com/api",
                 "ghcr.io/Acme/API", "ghcr.io/acme/a b")
NEVER_OUT = ("tok", "123456789012", "amazonaws")


class UnsafeImagesTest(CollectorCliCase):
    def test_unsafe_images_are_dropped_and_the_ecr_host_never_leaves(self):
        """SPEC-0082:UT-02 — user:tok@ghcr.io/acme/api e ghcr.io/acme/a b são descartadas, a do ECR vira api e
        ghcr.io/Acme/API vira acme/api."""
        entities, relations = function("map_application")(bare_app("dev-api", images=UNSAFE_IMAGES))
        attrs = deployment_of(entities)["attrs"]
        self.assertIn("images", attrs, "o deployment não traz o atributo images (SPEC-0082)")
        self.assertEqual(attrs["images"], ["acme/api", "api"])
        text = json.dumps(entities) + json.dumps(relations)
        for piece in NEVER_OUT:
            self.assertNotIn(piece, text)

    def test_no_piece_of_the_unsafe_images_in_any_collector_output(self):
        """SPEC-0082:UT-02 — pela CLI (--input): tok, 123456789012 e amazonaws não aparecem no stdout nem no stderr,
        e as imagens que sobram são acme/api e api."""
        path = self.write_apps([bare_app("dev-api", images=UNSAFE_IMAGES)])
        data, result = self.collect("--from", "argocd", "--input", path)
        attrs = deployment_of(data["entities"])["attrs"]
        self.assertEqual(attrs.get("images"), ["acme/api", "api"])
        for piece in NEVER_OUT:
            with self.subTest(piece=piece):
                self.assertNotIn(piece, result.stdout)
                self.assertNotIn(piece, result.stderr)


class ImageEdgeCasesTest(unittest.TestCase):
    def test_host_case_bare_host_dot_dot_segment_and_docker_io(self):
        """SPEC-0082:UT-01 (Emenda v3) — host em maiúsculas (GHCR.IO/Acme/Api:1 -> acme/api), host sem caminho
        (ghcr.io e ghcr.io:443 são descartadas), segmento ".." (descartada) e docker.io/x -> x."""
        cases = (
            ("host em maiúsculas", "GHCR.IO/Acme/Api:1", ["acme/api"]),
            ("host sem caminho", "ghcr.io", None),
            ("host:porta sem caminho", "ghcr.io:443", None),
            ("segmento ..", "ghcr.io/acme/../api", None),
            ("docker.io/x", "docker.io/x", ["x"]),
        )
        for name, image, want in cases:
            with self.subTest(caso=name):
                entities, _ = function("map_application")(bare_app("dev-api", images=[image]))
                self.assertEqual(deployment_of(entities)["attrs"].get("images"), want)


# credencial antes do "@" com "host:porta" depois (parece um digest alg:hex) e digest que não é sha256/384/512
CREDENTIAL_IMAGES = ("admin:secret@registry:5000", "AKIAABCDEFGHIJKLMNOP@reg:5000",
                     "glpat-abcdefghij1234567890@reg:443", "oci://deploy:tok123@registry:443",
                     "ghp_" + "a1B2c3D4e5" * 3 + "f6G7h8" + "@registry:5000")
OTHER_DIGEST_IMAGES = ("a/b@md5:abcdef",)
CREDENTIAL_PIECES = ("secret", "admin", "akia", "glpat", "tok123", "ghp_")
SHA_DIGESTS = ("ghcr.io/acme/api@sha256:abc", "ghcr.io/acme/api@sha384:" + "0a" * 48,
               "ghcr.io/acme/api@sha512:" + "0b" * 64)


class DigestTest(CollectorCliCase):
    def test_credential_before_at_with_host_port_after_is_dropped(self):
        """SPEC-0082:UT-02 (Emenda v3) — só sha256:, sha384: e sha512: seguidos de hexadecimal são digest: uma
        credencial antes do "@" com "host:porta" depois (admin:secret@registry:5000, chave AKIA, token glpat-, ghp_,
        oci://deploy:tok123@registry:443) e um digest md5: descartam a imagem inteira (sem o atributo images)."""
        self.assertEqual(len(CREDENTIAL_IMAGES[-1]), len("ghp_") + 36 + len("@registry:5000"))
        for image in CREDENTIAL_IMAGES + OTHER_DIGEST_IMAGES:
            with self.subTest(imagem=image):
                entities, relations = function("map_application")(bare_app("dev-api", images=[image]))
                self.assertNotIn("images", deployment_of(entities)["attrs"])
                text = (json.dumps(entities) + json.dumps(relations)).lower()
                for piece in CREDENTIAL_PIECES:
                    self.assertNotIn(piece, text)

    def test_sha_digests_are_removed(self):
        """SPEC-0082:UT-02 (Emenda v3) — ghcr.io/acme/api@sha256:, @sha384: e @sha512: com hexadecimal dão
        acme/api."""
        for image in SHA_DIGESTS:
            with self.subTest(imagem=image):
                entities, _ = function("map_application")(bare_app("dev-api", images=[image]))
                self.assertEqual(deployment_of(entities)["attrs"].get("images"), ["acme/api"])

    def test_no_piece_of_a_credential_in_any_collector_output(self):
        """SPEC-0082:UT-02 (Emenda v3) — pela CLI (--input): com as imagens de credencial e md5 ao lado de uma
        imagem válida, só a válida sobra, e secret, admin, akia, glpat, tok123 e ghp_ (sem diferenciar maiúsculas)
        não aparecem no stdout nem no stderr."""
        images = CREDENTIAL_IMAGES + OTHER_DIGEST_IMAGES + ("ghcr.io/acme/web:2.0.3",)
        path = self.write_apps([bare_app("dev-api", images=images)])
        data, result = self.collect("--from", "argocd", "--input", path)
        self.assertEqual(deployment_of(data["entities"])["attrs"].get("images"), ["acme/web"])
        for piece in CREDENTIAL_PIECES:
            with self.subTest(piece=piece):
                self.assertNotIn(piece, result.stdout.lower())
                self.assertNotIn(piece, result.stderr.lower())


# --------------------------------------------------------------------------- UT-03 (coletor)


def services_of(data):
    """{deployment: serviço} pelas relações deploys."""
    return {r["from"].split(":", 1)[1]: r["to"] for r in data["relations"] if r["type"] == "deploys"}


class ServicePatternTest(CollectorCliCase):
    def test_pattern_names_the_service_after_the_label_and_the_name_override(self):
        """SPEC-0082:UT-03 — com --service-pattern '^(?:dev|qa)-(?P<service>.+)$': dev-api e qa-api dão service:api,
        prod-api dá service:prod-api; o rótulo e o nameOverride continuam vencendo; grupo que captura um nome
        inválido (dev--x) cai no nome da Application."""
        apps = [
            bare_app("dev-api"), bare_app("qa-api"), bare_app("prod-api"),
            bare_app("dev-billing", labels={"app.kubernetes.io/part-of": "billing-x"}),
            bare_app("qa-acct", source={"repoURL": "https://charts.interno/helm", "chart": "account",
                                        "helm": {"valuesObject": {"nameOverride": "account"}}}),
            bare_app("dev--x"),
        ]
        data, _ = self.collect("--from", "argocd", "--input", self.write_apps(apps), "--service-pattern", PATTERN)
        self.assertEqual(services_of(data), {
            "dev-api": "service:api", "qa-api": "service:api", "prod-api": "service:prod-api",
            "dev-billing": "service:billing-x", "qa-acct": "service:account", "dev--x": "service:dev--x",
        })
        keys = {f"{e['kind']}:{e['id']}" for e in data["entities"]}
        self.assertNotIn("service:dev-api", keys)
        self.assertNotIn("service:qa-api", keys)

    def test_group_that_does_not_match_falls_back_to_the_application_name(self):
        """SPEC-0082:UT-03 — um grupo service opcional que não participa do casamento cai no nome da Application."""
        pattern = r"^(?:dev-(?P<service>.+)|standalone)$"
        apps = [bare_app("dev-api"), bare_app("standalone")]
        data, _ = self.collect("--from", "argocd", "--input", self.write_apps(apps), "--service-pattern", pattern)
        self.assertEqual(services_of(data), {"dev-api": "service:api", "standalone": "service:standalone"})

    def test_invalid_pattern_or_without_the_service_group_exits_2(self):
        """SPEC-0082:UT-03 — regex quebrada ou sem o grupo nomeado service = exit 2 com "--service-pattern
        inválido: <motivo>", sem nada no stdout."""
        path = self.write_apps([bare_app("dev-api")])
        for name, pattern in (("regex quebrada", "^(dev|qa-(?P<service>.+)$"), ("sem o grupo", r"^(?:dev|qa)-(.+)$")):
            with self.subTest(caso=name):
                result = self.run_collector("--from", "argocd", "--input", path, "--service-pattern", pattern)
                self.assertEqual(result.returncode, 2, output(result))
                self.assertRegex(output(result), re.escape(PATTERN_INVALID) + r"\S")
                self.assertFalse(result.stdout.strip().startswith(("{", "[")), "nada do contrato numa falha")


# --------------------------------------------------------------------------- UT-04 e UT-05 (build, regra 4)


def image_snapshots(images, repositories, config_repo="acme/iac"):
    """Snapshots com deployment:dev-api (images, deploys service:api, sourced_from o repositório de configuração) e
    os repositórios dados."""
    gitops = snap("gitops", [
        ent("deployment", "dev-api", {"sync_status": "Synced", "health_status": "Healthy", "images": list(images)},
            "gitops"),
        ent("service", "api", {}, "gitops"),
    ], [rel("deployment:dev-api", "deploys", "service:api", "gitops"),
        rel("deployment:dev-api", "sourced_from", f"repository:{config_repo}", "gitops")], category="delivery")
    scm = snap("scm", [repo(r) for r in sorted(set(repositories) | {config_repo})])
    return {"scm": scm, "gitops": gitops}


class RuleFourTest(unittest.TestCase):
    def test_image_owner_and_name_link_the_service_to_the_code_repository(self):
        """SPEC-0082:UT-04 — deployment:dev-api com images [acme/api], deploys service:api e sourced_from
        repository:acme/iac, mais repository:acme/api: service:api sourced_from repository:acme/api (inferred,
        evidence "image:acme/api"), além da aresta da regra 1 para acme/iac."""
        graph = build_graph(image_snapshots(["acme/api"], ["acme/api"]), ["scm", "gitops"])
        code = edges_of(graph, "service:api", "sourced_from", "repository:acme/api")
        self.assertEqual(len(code), 1, graph["edges"])
        self.assertIs(code[0]["inferred"], True)
        self.assertEqual(code[0]["evidence"], "image:acme/api")
        config = edges_of(graph, "service:api", "sourced_from", "repository:acme/iac")
        self.assertEqual(len(config), 1, graph["edges"])
        self.assertIs(config[0]["inferred"], True)
        self.assertFalse(str(config[0].get("evidence", "")).startswith("image:"))

    def test_image_of_an_unknown_repository_gives_no_edge_and_no_node(self):
        """SPEC-0082:UT-04 — imagem sem repositório no grafo: nenhuma aresta image: e nenhum nó novo."""
        snapshots = image_snapshots(["acme/api", "acme/ghost"], ["acme/api"])
        graph = build_graph(snapshots, ["scm", "gitops"])
        self.assertEqual(sorted(e["to"] for e in image_edges(graph)), ["repository:acme/api"])
        self.assertNotIn("repository:acme/ghost", {n["key"] for n in graph["nodes"]})


class RuleFourByNameTest(unittest.TestCase):
    def test_last_segment_equal_to_a_single_repository_name(self):
        """SPEC-0082:UT-05 — imagem team-x/api e um único repositório de nome api (acme/api): liga a ele, com
        evidence "image:team-x/api"; com acme/api e globex/api, ou sem repositório api, não liga nada."""
        graph = build_graph(image_snapshots(["team-x/api"], ["acme/api"]), ["scm", "gitops"])
        edges = image_edges(graph)
        self.assertEqual([(e["from"], e["type"], e["to"], e["evidence"]) for e in edges],
                         [("service:api", "sourced_from", "repository:acme/api", "image:team-x/api")])
        self.assertIs(edges[0]["inferred"], True)
        for name, repositories in (("dois api", ["acme/api", "globex/api"]), ("nenhum api", ["acme/web"])):
            with self.subTest(caso=name):  # com dois (acme/api e globex/api) ou nenhum, não há aresta
                graph = build_graph(image_snapshots(["team-x/api"], repositories), ["scm", "gitops"])
                self.assertEqual(image_edges(graph), [])
                self.assertEqual([e["to"] for e in edges_of(graph, "service:api", "sourced_from")],
                                 ["repository:acme/iac"])

    def test_owner_and_name_equal_wins_over_the_name_only_match(self):
        """SPEC-0082:UT-05 — passo 2 antes do 3: imagem acme/api com acme/api e globex/api liga só a acme/api."""
        graph = build_graph(image_snapshots(["acme/api"], ["acme/api", "globex/api"]), ["scm", "gitops"])
        self.assertEqual([e["to"] for e in image_edges(graph)], ["repository:acme/api"])


# --------------------------------------------------------------------------- UT-06 (mapa explícito)


IMAGE_MAP_COLLECTORS = [
    ("github", "code", ["python3", REPLAY, "github", "code", "{skill}/tests/fixtures/github/image-map.json"]),
    ("argocd", "delivery", ["python3", REPLAY, "argocd", "delivery", "{skill}/tests/fixtures/argocd/image-map.json"]),
]
# (chave, valor) inválidos: valor sem "/", maiúsculas, esquema, "@" e chave com maiúsculas
INVALID_ITEMS = (
    ("acme/k-one", "acmeapione"),
    ("acme/k-two", "Acme/Api-Two"),
    ("acme/k-three", "https://github.com/acme/k-three-v"),
    ("acme/k-four", "user@acme/k-four-v"),
    ("Acme/K-Five", "acme/k-five-v"),
)


def mapping_yaml(items, quoted_keys=False):
    lines = ["image_repositories:"]
    for key, value in items:
        lines.append(f"  {json.dumps(key) if quoted_keys else key}: {json.dumps(value)}")
    return "\n".join(lines) + "\n"


class ImageRepositoriesTest(AtlasCase):
    def test_explicit_map_wins_over_the_convention(self):
        """SPEC-0082:UT-06 — image_repositories {"acme/legacy-api": "acme/api-v1"}: a imagem acme/legacy-api liga
        service:legacy a repository:acme/api-v1 (evidence image:acme/legacy-api), mesmo existindo acme/legacy-api; a
        chave é conhecida (lint não acusa chave desconhecida)."""
        for name, quoted in (("chave entre aspas, como no exemplo da spec", True), ("chave sem aspas", False)):
            with self.subTest(forma=name):
                self.configure(atlas_config(IMAGE_MAP_COLLECTORS,
                                            extra=mapping_yaml([("acme/legacy-api", "acme/api-v1")], quoted)))
                self.cli("config", "--json")
                self.cli("scan")
                graph = self.graph()
                edges = [(e["from"], e["to"], e.get("evidence")) for e in image_edges(graph)]
                self.assertEqual(edges, [("service:legacy", "repository:acme/api-v1", "image:acme/legacy-api")])
                self.assertEqual(edges_of(graph, "service:legacy", "sourced_from", "repository:acme/legacy-api"), [])
                lint = self.cli("lint", code=None)
                self.assertNotIn("chave desconhecida: image_repositories", output(lint))

    def test_invalid_item_exits_2_with_the_position_and_without_the_item(self):
        """SPEC-0082:UT-06 — um item inválido (valor sem "/", maiúsculas, esquema, "@") dá exit 2 com
        "image_repositories: item N inválido — <motivo>", sem nenhum texto do item, em config --json, build e
        lint."""
        for key, value in INVALID_ITEMS:
            with self.subTest(item=f"{key}: {value}"):
                self.configure(atlas_config(IMAGE_MAP_COLLECTORS,
                                            extra=mapping_yaml([("acme/legacy-api", "acme/api-v1"), (key, value)])))
                for command in (("config", "--json"), ("build",), ("lint",)):
                    with self.subTest(command=command[0]):
                        result = self.cli(*command, code=2)
                        text = output(result)
                        match = IMAGE_ITEM_RE.search(text)
                        self.assertIsNotNone(match, text)
                        self.assertEqual(match.group(1), "2")
                        for piece in (key, value, key.lower(), value.lower()):
                            self.assertNotIn(piece, text, "a mensagem cita o item")
                        self.assertNotIn("***", text, "a mensagem não cita o item, nem mascarado")

    def test_map_to_a_repository_missing_from_the_graph_gives_no_edge_and_no_fallback(self):
        """SPEC-0082:UT-06 (Emenda v2) — imagem que está em image_repositories mas aponta para um repositório ausente
        do grafo não gera aresta e não cai nos passos 2 e 3, mesmo existindo o <dono>/<nome> igual (acme/legacy-api)
        ou um único repositório com o mesmo nome (team-x/legacy-api -> legacy-api): o mapa é a declaração do time e
        vence a convenção. Uma imagem fora do mapa (acme/api-v1) continua ligando pelo passo 2."""
        gitops = json.loads((FIXTURES / "argocd" / "image-map.json").read_text(encoding="utf-8"))
        gitops["entities"][0]["attrs"]["images"] = ["acme/api-v1", "acme/legacy-api", "team-x/legacy-api"]
        facts = self.atlas / "facts"
        facts.mkdir(parents=True, exist_ok=True)
        (facts / "image-map-missing.json").write_text(json.dumps(gitops), encoding="utf-8")
        collectors = [IMAGE_MAP_COLLECTORS[0],
                      ("argocd", "delivery", ["python3", REPLAY, "argocd", "delivery",
                                              "{atlas}/facts/image-map-missing.json"])]
        mapping = [("acme/legacy-api", "acme/ghost"), ("team-x/legacy-api", "acme/ghost")]
        self.configure(atlas_config(collectors, extra=mapping_yaml(mapping, quoted_keys=True)))
        self.cli("config", "--json")
        self.cli("scan")
        graph = self.graph()
        edges = [(e["from"], e["to"], e.get("evidence")) for e in image_edges(graph)]
        self.assertEqual(edges, [("service:legacy", "repository:acme/api-v1", "image:acme/api-v1")])
        self.assertEqual(edges_of(graph, "service:legacy", "sourced_from", "repository:acme/legacy-api"), [])
        self.assertNotIn("repository:acme/ghost", {n["key"] for n in graph["nodes"]})
        self.assertEqual(edges_of(graph, dst="repository:acme/ghost"), [])

    def test_quoted_key_with_a_space_before_the_colon_is_read(self):
        """SPEC-0082:UT-06 (Emenda v3) — a chave entre aspas com espaço antes dos dois-pontos
        ("acme/legacy-api" : acme/api-v1) também é lida, e o mapa vence a convenção."""
        extra = 'image_repositories:\n  "acme/legacy-api" : acme/api-v1\n'
        self.configure(atlas_config(IMAGE_MAP_COLLECTORS, extra=extra))
        self.cli("config", "--json")
        self.cli("scan")
        graph = self.graph()
        edges = [(e["from"], e["to"], e.get("evidence")) for e in image_edges(graph)]
        self.assertEqual(edges, [("service:legacy", "repository:acme/api-v1", "image:acme/legacy-api")])
        self.assertEqual(edges_of(graph, "service:legacy", "sourced_from", "repository:acme/legacy-api"), [])

    def test_doctor_reports_an_invalid_item_without_the_item(self):
        """SPEC-0082:UT-06 (Emenda v3) — doctor e doctor --json com um item inválido em image_repositories acusam o
        erro (exit diferente de 0) com só a posição e o motivo, sem nenhum texto do item."""
        key, value = INVALID_ITEMS[0]
        self.configure(atlas_config(IMAGE_MAP_COLLECTORS,
                                    extra=mapping_yaml([("acme/legacy-api", "acme/api-v1"), (key, value)])))
        for command in (("doctor",), ("doctor", "--json")):
            with self.subTest(command=" ".join(command)):
                result = self.cli(*command, code=None)
                self.assertNotEqual(result.returncode, 0, output(result))
                text = output(result)
                match = IMAGE_ITEM_RE.search(text)
                self.assertIsNotNone(match, text)
                self.assertEqual(match.group(1), "2")
                for piece in (key, value):
                    self.assertNotIn(piece, text, "a mensagem cita o item")
                if command[-1] == "--json":
                    data = json.loads(result.stdout)
                    self.assertIs(data["ok"], False)
                    self.assertTrue(any(c["status"] == "ERRO" and IMAGE_ITEM_RE.search(c["detail"])
                                        for c in data["checks"]), data)


# --------------------------------------------------------------------------- UT-07 (página do serviço)


PIPELINES = (("acme/api/build", "Build"), ("acme/api/publish", "Publish"))


def page_snapshots(with_image=True):
    """Serviço api: dois deployments (dev em cluster-dev, qa em cluster-qa), configurados de acme/iac; com
    with_image, a imagem team-x/api (que casa com acme/api pelo nome); acme/api tem as pipelines Build e Publish e o
    dono team-x."""
    images = ["team-x/api"] if with_image else []
    deployments = (("dev-api", "dev", "cluster-dev", "Synced", "Healthy"),
                   ("qa-api", "qa", "cluster-qa", "OutOfSync", "Degraded"))
    entities, relations = [ent("service", "api", {}, "gitops")], []
    for name, env, cluster, sync, health in deployments:
        attrs = {"sync_status": sync, "health_status": health}
        if with_image:
            attrs["images"] = images
        entities += [ent("deployment", name, attrs, "gitops"), ent("environment", env, {}, "gitops"),
                     ent("cluster", cluster, {}, "gitops")]
        relations += [rel(f"deployment:{name}", "deploys", "service:api", "gitops"),
                      rel(f"deployment:{name}", "runs_in", f"environment:{env}", "gitops"),
                      rel(f"deployment:{name}", "runs_in", f"cluster:{cluster}", "gitops"),
                      rel(f"deployment:{name}", "sourced_from", "repository:acme/iac", "gitops")]
    gitops = snap("gitops", entities, relations, category="delivery")
    scm_entities = [repo("acme/api"), repo("acme/iac"), ent("team", "acme/team-x", {}, "scm", name="team-x")]
    scm_relations = [rel("team:acme/team-x", "owns", "repository:acme/api", "scm")]
    for pid, pname in PIPELINES:
        scm_entities.append(ent("pipeline", pid, {"file": f".github/workflows/{pid.rsplit('/', 1)[1]}.yml"}, "scm",
                                name=pname))
        scm_relations.append(rel(f"pipeline:{pid}", "builds", "repository:acme/api", "scm"))
    return {"scm": snap("scm", scm_entities, scm_relations), "gitops": gitops}


def page_graph(with_image=True):
    """Grafo da página; com with_image, garante a aresta da regra 4 (para isolar a página da regra)."""
    graph = build_graph(page_snapshots(with_image), ["scm", "gitops"])
    if with_image and not edges_of(graph, "service:api", "sourced_from", "repository:acme/api"):
        graph = dict(graph, edges=graph["edges"] + [
            {"from": "service:api", "to": "repository:acme/api", "type": "sourced_from",
             "sources": ["gitops", "scm"], "inferred": True, "evidence": "image:team-x/api"}])
    return graph


class ServicePageTest(unittest.TestCase):
    def render(self, with_image=True):
        pages = fn("render_pages", SPEC)(page_graph(with_image), {}, "Acme", scans=state("scm", "gitops"))
        return pages["services/api.md"]

    def test_repositories_split_into_code_and_gitops_configuration(self):
        """SPEC-0082:UT-07 — "Repositórios" mostra "Código: acme/api" e "Configuração (GitOps): acme/iac"; as
        pipelines e o dono de acme/api entram em "Pipelines" e "Donos"."""
        page = self.render()
        found = regions(page)
        repository = found["repository"]
        self.assertIn(CODE_LABEL, repository, repository)
        self.assertIn(CONFIG_LABEL, repository, repository)
        code_part, _, config_part = repository.partition(CONFIG_LABEL)
        code_part = code_part[code_part.find(CODE_LABEL):]
        self.assertIn("acme/api", code_part)
        self.assertNotIn("acme/iac", code_part)
        self.assertIn("acme/iac", config_part)
        self.assertNotIn("acme/api", config_part)
        for pid, pname in PIPELINES:
            self.assertIn(pname, found["pipelines"])
            self.assertIn(pid, found["pipelines"])
        self.assertIn("team-x", found["owners"])

    def test_commit_to_pod_region_lists_the_delivery_path_in_order(self):
        """SPEC-0082:UT-07 — a região "Do commit até o pod" lista, na ordem, o repositório do código, as pipelines, a
        imagem, o repositório de configuração e um item por deployment com ambiente, cluster e estado, sem texto
        de ferramenta fixo. Sem aresta de imagem, a região não aparece e "Repositórios" fica como hoje."""
        flow = flow_region(self.render())
        self.assertIsNotNone(flow, f'a página não tem a região "{REGION_TITLE}"')
        positions = [("repositório do código", flow.find("acme/api")),
                     ("pipeline Build", flow.find("Build")), ("pipeline Publish", flow.find("Publish")),
                     ("imagem", flow.find("team-x/api")), ("repositório de configuração", flow.find("acme/iac"))]
        for what, at in positions:
            self.assertGreaterEqual(at, 0, f"{what} não está na região:\n{flow}")
        self.assertLess(positions[0][1], min(positions[1][1], positions[2][1]), flow)
        self.assertLess(max(positions[1][1], positions[2][1]), positions[3][1], flow)
        self.assertLess(positions[3][1], positions[4][1], flow)
        after_config = flow[positions[4][1]:]
        lines = after_config.splitlines()
        for env, cluster, sync, health in (("dev", "cluster-dev", "Synced", "Healthy"),
                                           ("qa", "cluster-qa", "OutOfSync", "Degraded")):
            with self.subTest(deployment=env):
                items = [line for line in lines if cluster in line]
                self.assertEqual(len(items), 1, f"um item por deployment ({cluster}):\n{flow}")
                for piece in (env, sync, health):
                    self.assertIn(piece, items[0])
        lowered = flow.lower()
        for tool in ("argo", "github", "helm", "kubernetes", "docker"):
            self.assertNotIn(tool, lowered, f"texto de ferramenta fixo na região: {tool}")
        # sem aresta de imagem, a região não aparece e "Repositórios" fica como hoje
        page = self.render(with_image=False)
        self.assertNotIn(REGION_TITLE, page)
        repository = regions(page)["repository"]
        self.assertNotIn(CODE_LABEL, repository)
        self.assertNotIn(CONFIG_LABEL, repository)
        self.assertIn("acme/iac", repository)


class ServicePageEmendaTest(unittest.TestCase):
    def test_commit_to_pod_region_lists_every_image_that_leads_to_the_code_repository(self):
        """SPEC-0082:UT-07 (Emenda v3) — a região "Do commit até o pod" lista todas as imagens dos deployments do
        serviço que levam ao repositório do código, e não só a da evidência da aresta: images [acme/api,
        acme/api-worker] com image_repositories {"acme/api-worker": "acme/api"} e o repositório acme/api -> a linha
        da imagem traz acme/api e acme/api-worker."""
        snapshots = page_snapshots()
        for item in snapshots["gitops"]["entities"]:
            if item["kind"] == "deployment":
                item["attrs"]["images"] = ["acme/api", "acme/api-worker"]
        merged = fn("merge_snapshots", SPEC)(snapshots, ["scm", "gitops"], state("scm", "gitops"))
        graph = fn("infer_relations", SPEC)(merged, {"acme/api-worker": "acme/api"})
        self.assertTrue(edges_of(graph, "service:api", "sourced_from", "repository:acme/api"), graph["edges"])
        pages = fn("render_pages", SPEC)(graph, {}, "Acme", scans=state("scm", "gitops"))
        flow = flow_region(pages["services/api.md"])
        self.assertIsNotNone(flow, f'a página não tem a região "{REGION_TITLE}"')
        before_config = flow[:flow.find("acme/iac")]
        last_pipeline = "acme/api/publish"  # as imagens ficam entre as pipelines e o repositório de configuração
        self.assertIn(last_pipeline, before_config, flow)
        image_text = before_config[before_config.rfind(last_pipeline) + len(last_pipeline):]
        for image in ("acme/api-worker", "acme/api"):
            with self.subTest(imagem=image):
                self.assertRegex(image_text, rf"(?<![\w/.-]){re.escape(image)}(?![\w/.-])", flow)

    def test_page_rebuilt_after_the_code_repository_disappears_equals_a_fresh_page(self):
        """SPEC-0082:UT-07 (Emenda v3) — a página que tinha a região "Do commit até o pod", refeita depois que o
        repositório do código some, é igual, byte a byte, à página nova sem a região; e refazer duas vezes a mesma
        página não muda nada."""
        render = fn("render_pages", SPEC)
        scans = state("scm", "gitops")
        path = "services/api.md"
        with_region = render(page_graph(), {}, "Acme", scans=scans)[path]
        self.assertIsNotNone(flow_region(with_region), f'a página não tem a região "{REGION_TITLE}"')
        self.assertEqual(render(page_graph(), {path: with_region}, "Acme", scans=scans)[path], with_region,
                         "refazer a página com a região muda o texto")
        snapshots = page_snapshots()
        scm = snapshots["scm"]
        scm["entities"] = [e for e in scm["entities"] if not (e["kind"] == "repository" and e["id"] == "acme/api")]
        scm["relations"] = [r for r in scm["relations"] if r["to"] != "repository:acme/api"]
        gone = build_graph(snapshots, ["scm", "gitops"])
        self.assertEqual(image_edges(gone), [])
        fresh = render(gone, {}, "Acme", scans=scans)[path]
        self.assertNotIn(REGION_TITLE, fresh)
        rebuilt = render(gone, {path: with_region}, "Acme", scans=scans)[path]
        self.assertEqual(rebuilt, fresh)
        self.assertEqual(render(gone, {path: rebuilt}, "Acme", scans=scans)[path], rebuilt)


# --------------------------------------------------------------------------- IT-01


TAGS = ("7.7.1-rc9", "8.8.2")
REGISTRY_HOSTS = ("ghcr.io",)


class CommitToPodScanTest(AtlasCase):
    def test_scan_and_build_link_the_service_to_the_code_repository(self):
        """SPEC-0082:IT-01 — github (acme/api com as pipelines Build e Publish, acme/iac) e argocd (dev-api e qa-api
        com repoURL de acme/iac, imagem ghcr.io/acme/api:<tag> e --service-pattern): scan e build num atlas
        temporário dão um só service:api com dois deployments, a página com as pipelines de acme/api e a região
        "Do commit até o pod", e nenhum snapshot, página nem graph.json com tag ou host de registry."""
        self.configure(atlas_config([
            ("github", "code", ["python3", "{skill}/assets/collectors/github.py", "--org", "acme", "--input",
                                "{skill}/tests/fixtures/github/image-link"]),
            ("argocd", "delivery", ["python3", "{skill}/assets/collectors/argocd.py", "--from", "argocd",
                                    "--input", "{skill}/tests/fixtures/argocd/image-link.json",
                                    "--service-pattern", PATTERN]),
        ]))
        result = self.cli("scan")
        text = output(result)
        self.assertRegex(text, re.compile(r"^OK github — ", re.MULTILINE))
        self.assertRegex(text, re.compile(r"^OK argocd — ", re.MULTILINE))
        graph = self.graph()
        keys = {n["key"] for n in graph["nodes"]}
        self.assertEqual(sorted(k for k in keys if k.startswith("service:")), ["service:api"])
        self.assertEqual(sorted(e["from"] for e in edges_of(graph, rtype="deploys", dst="service:api")),
                         ["deployment:dev-api", "deployment:qa-api"])
        code = edges_of(graph, "service:api", "sourced_from", "repository:acme/api")
        self.assertEqual([e.get("evidence") for e in code], ["image:acme/api"])
        self.assertEqual(len(edges_of(graph, "service:api", "sourced_from", "repository:acme/iac")), 1)

        page = self.page("services/api.md")
        pipelines = regions(page)["pipelines"]
        for name in ("Build", "Publish"):
            self.assertIn(name, pipelines)
        self.assertIsNotNone(flow_region(page), f'a página não tem a região "{REGION_TITLE}"')

        files = [p for p in sorted((self.atlas / "snapshots").rglob("*")) if p.is_file()]
        files += sorted((self.atlas / "services").glob("*.md")) + sorted((self.atlas / "platform").glob("*.md"))
        files += [self.atlas / "ATLAS.md", self.atlas / "graph.json"]
        for path in files:
            content = path.read_text(encoding="utf-8")
            for piece in TAGS + REGISTRY_HOSTS + ("sha256",):
                with self.subTest(file=path.name, piece=piece):
                    self.assertNotIn(piece, content)


# --------------------------------------------------------------------------- CT-01


class ImagesContractTest(CollectorCliCase):
    def test_snapshot_with_images_is_accepted_by_the_contract_now_and_before(self):
        """SPEC-0082:CT-01 — a saída do argocd sobre as fixtures acme (com status.summary.images) traz images nos
        deployments e passa no validador @1 sem violação nem descarte; a lógica da versão anterior (validação que não
        conhece o atributo, emulada com o atributo sob um nome desconhecido) também aceita e mantém o valor."""
        data, _ = self.collect("--from", "argocd", "--input", ARGOCD_LIST)
        images = {e["id"]: e["attrs"].get("images") for e in data["entities"] if e["kind"] == "deployment"}
        self.assertEqual(images, {"api-prod": ["acme/api"], "api-staging": ["acme/api"], "web": ["acme/web"],
                                  "ingress-nginx": ["ingress-nginx/controller"]})
        validate = fn("validate_collector_output", SPEC)
        clean, violations, dropped = validate(data)
        self.assertEqual((violations, dropped), ([], []))
        self.assertEqual({e["id"]: e["attrs"].get("images") for e in clean["entities"] if e["kind"] == "deployment"},
                         images)
        before = copy.deepcopy(data)
        for item in before["entities"]:
            if item["kind"] == "deployment":
                item["attrs"]["zz_attr_unknown_to_this_version"] = item["attrs"].pop("images")
        clean, violations, dropped = validate(before)
        self.assertEqual((violations, dropped), ([], []))
        kept = {e["id"]: e["attrs"].get("zz_attr_unknown_to_this_version") for e in clean["entities"]
                if e["kind"] == "deployment"}
        self.assertEqual(kept, images)

    def test_without_the_attribute_the_graph_is_todays(self):
        """SPEC-0082:CT-01 — a mesma saída do argocd, com images removido, junto do github e do db-facts de hoje,
        dá o graph.json do golden (o de hoje)."""
        data, _ = self.collect("--from", "argocd", "--input", ARGOCD_LIST)
        self.assertTrue(any("images" in e["attrs"] for e in data["entities"] if e["kind"] == "deployment"),
                        "o coletor não produz images (SPEC-0082)")
        snapshots = acme_snapshots()
        snapshots["argocd"] = without_images(dict(data, collected_at=BUILT_AT))
        graph = build_graph(snapshots, ACME_ORDER)
        self.assertEqual(fn("render_graph", SPEC)(graph, "Acme", BUILT_AT), golden()["graph"])

    def test_build_keeps_a_snapshot_with_images(self):
        """SPEC-0082:CT-01 — read_snapshots (que revalida o contrato no build) não descarta um snapshot com images."""
        data, _ = self.collect("--from", "argocd", "--input", ARGOCD_LIST)
        self.assertTrue(any("images" in e["attrs"] for e in data["entities"] if e["kind"] == "deployment"),
                        "o coletor não produz images (SPEC-0082)")
        atlas = self.tmp / "atlas"
        (atlas / "snapshots").mkdir(parents=True)
        (atlas / "snapshots" / "argocd.json").write_text(json.dumps(data), encoding="utf-8")
        snapshots, warnings = fn("read_snapshots", SPEC)(atlas, ["argocd"])
        self.assertEqual(warnings, [])
        self.assertIn("argocd", snapshots)


if __name__ == "__main__":
    unittest.main()
