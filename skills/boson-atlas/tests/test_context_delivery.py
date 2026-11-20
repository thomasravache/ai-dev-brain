"""Caminho de entrega no `context` (SPEC-0086: CH-01, UT-01 a UT-04, IT-01 e CT-01; a SPEC-0082 pôs o caminho no
grafo e na página do serviço).

Contrato (seção 6 da SPEC-0086) que estes testes fixam:

    context --json: cada item de "services" ganha, quando o serviço tem caminho de entrega (ao menos um deployment,
    uma pipeline ou um repositório de código), a chave "delivery":
        {"code_repositories": [...],      # sourced_from com evidência image: (regra 4)
         "config_repositories": [...],    # os demais sourced_from, só quando há código; senão []
         "pipelines": [{"id", "name", "repository"}],   # as que fazem "builds" de um repositório sourced_from do
                                                       # serviço ou do próprio serviço; ordenadas por id
         "images": [...],                 # as mesmas da região "Do commit até o pod"
         "deployments": [{"id", "environments", "clusters", "sync_status"?, "health_status"?, "images"}]}
    listas em ordem alfabética (pipelines e deployments por id); chave de status ausente quando o atlas não tem;
    sem caminho de entrega -> sem "delivery"; nenhuma chave existente muda.

    context (Markdown): dentro do bloco do serviço, depois de "Deployments", só com "delivery":
        - Entrega:
          - Código: acme/api
          - Pipelines: Build (acme/api), Publish (acme/api)
          - Imagens: acme/api
          - Configuração (GitOps): acme/iac
          - dev: dev-api — cluster cluster-dev; sync Synced; health Healthy
    cada linha só quando tem valor; valores numa linha só, crase -> ' (SPEC-0048); o bloco faz parte do item do
    serviço no corte de --max-chars (ordem do corte inalterada).

Leituras literais desta suíte (ver o relatório do test-writer):
    - CH-01 "igual à de hoje, byte a byte" = igual ao golden fixtures/context/spec-0086-ch01-golden.json, gravado com o
      código anterior à SPEC-0086 (build_context + render_context, o que a CLI imprime).
    - O bloco "Entrega" no Markdown = a linha "- Entrega:" do item do serviço seguida das linhas recuadas "- ..."; os
      rótulos são comparados sem o recuo.
    - "depois de Deployments" = em algum ponto depois da linha "- Deployments:" do mesmo serviço.
    - "images" de cada deployment = o atributo images do deployment, ordenado; sem o atributo, [].

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); sem rede; nomes só acme, team-x.
"""
import datetime
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import TESTS, Sandbox, fn, output

SPEC = "SPEC-0086"
FIXTURE = TESTS / "fixtures" / "context" / "atlas"
GOLDEN = TESTS / "fixtures" / "context" / "spec-0086-ch01-golden.json"
TODAY = "2026-11-02"  # o _scan.json da fixture context é deste dia
BUILT_AT = f"{TODAY}T12:00:00Z"
DELIVERY_KEYS = {"code_repositories", "config_repositories", "pipelines", "images", "deployments"}
ENTREGA = "- Entrega:"
TOOL_WORDS = ("argo", "github", "kubernetes", "helm")
TAGS = ("7.7.1-rc9", "8.8.2")
REGISTRY_HOSTS = ("ghcr.io",)
PATTERN = r"^(?:dev|qa)-(?P<service>.+)$"

# delivery de service:api nas fixtures image-link (seção 6 da SPEC-0086)
API_DELIVERY = {
    "code_repositories": ["acme/api"],
    "config_repositories": ["acme/iac"],
    "pipelines": [{"id": "acme/api/build", "name": "Build", "repository": "acme/api"},
                  {"id": "acme/api/publish", "name": "Publish", "repository": "acme/api"}],
    "images": ["acme/api"],
    "deployments": [
        {"id": "dev-api", "environments": ["dev"], "clusters": ["cluster-dev"], "sync_status": "Synced",
         "health_status": "Healthy", "images": ["acme/api"]},
        {"id": "qa-api", "environments": ["qa"], "clusters": ["cluster-qa"], "sync_status": "OutOfSync",
         "health_status": "Degraded", "images": ["acme/api"]},
    ],
}


def f(name):
    return fn(name, SPEC)


# --------------------------------------------------------------------------- apoio


def ent(kind, eid, attrs=None, source="x", name=None):
    return {"kind": kind, "id": eid, "name": name or eid, "attrs": attrs or {}, "source": source}


def rel(src, rtype, dst, source="x"):
    return {"from": src, "to": dst, "type": rtype, "source": source}


def snap(cid, entities, relations=(), category="code"):
    return {"contract": "boson-atlas/collector@1", "collector": cid, "category": category,
            "collected_at": BUILT_AT, "entities": list(entities), "relations": list(relations)}


def repo(full, source="scm"):
    return ent("repository", full, {"default_branch": "main"}, source, name=full.split("/", 1)[1])


def image_link_snapshots(publish_name="Publish"):
    """Os snapshots que os coletores github e argocd dão sobre as fixtures image-link (SPEC-0082), com as entidades
    fora de ordem (qa antes de dev, publish antes de build) para a ordem do pacote ser do context."""
    entities, relations = [ent("service", "api", {}, "gitops")], []
    for name, env, cluster, sync, health in (("qa-api", "qa", "cluster-qa", "OutOfSync", "Degraded"),
                                             ("dev-api", "dev", "cluster-dev", "Synced", "Healthy")):
        attrs = {"project": "team-x", "sync_status": sync, "health_status": health, "config_refs": [],
                 "images": ["acme/api"]}
        entities += [ent("deployment", name, attrs, "gitops"), ent("environment", env, {}, "gitops"),
                     ent("cluster", cluster, {}, "gitops")]
        relations += [rel(f"deployment:{name}", "deploys", "service:api", "gitops"),
                      rel(f"deployment:{name}", "runs_in", f"environment:{env}", "gitops"),
                      rel(f"deployment:{name}", "runs_in", f"cluster:{cluster}", "gitops"),
                      rel(f"deployment:{name}", "sourced_from", "repository:acme/iac", "gitops")]
    scm_entities = [repo("acme/api"), repo("acme/iac"), ent("team", "acme/team-x", {}, "scm", name="team-x")]
    scm_relations = [rel("team:acme/team-x", "owns", "repository:acme/api", "scm")]
    for pid, pname in (("acme/api/publish", publish_name), ("acme/api/build", "Build")):
        scm_entities.append(ent("pipeline", pid, {"file": f".github/workflows/{pid.rsplit('/', 1)[1]}.yml"}, "scm",
                                name=pname))
        scm_relations.append(rel(f"pipeline:{pid}", "builds", "repository:acme/api", "scm"))
    return {"scm": snap("scm", scm_entities, scm_relations), "gitops": snap("gitops", entities, relations, "delivery")}


def config_only_snapshots():
    """Serviço api ligado só por repoURL (acme/iac), sem imagem: dev-api (cluster-dev, só health_status) e qa-api
    (sem cluster, Synced/Healthy); a pipeline Deploy faz build de acme/iac."""
    entities = [ent("service", "api", {}, "gitops"), ent("environment", "dev", {}, "gitops"),
                ent("environment", "qa", {}, "gitops"), ent("cluster", "cluster-dev", {}, "gitops"),
                ent("deployment", "qa-api", {"sync_status": "Synced", "health_status": "Healthy"}, "gitops"),
                ent("deployment", "dev-api", {"health_status": "Healthy"}, "gitops")]
    relations = []
    for name, env in (("dev-api", "dev"), ("qa-api", "qa")):
        relations += [rel(f"deployment:{name}", "deploys", "service:api", "gitops"),
                      rel(f"deployment:{name}", "runs_in", f"environment:{env}", "gitops"),
                      rel(f"deployment:{name}", "sourced_from", "repository:acme/iac", "gitops")]
    relations.append(rel("deployment:dev-api", "runs_in", "cluster:cluster-dev", "gitops"))
    scm_entities = [repo("acme/iac"), ent("pipeline", "acme/iac/deploy", {"file": ".github/workflows/deploy.yml"},
                                          "scm", name="Deploy")]
    scm_relations = [rel("pipeline:acme/iac/deploy", "builds", "repository:acme/iac", "scm")]
    return {"scm": snap("scm", scm_entities, scm_relations), "gitops": snap("gitops", entities, relations, "delivery")}


ATLAS_CONFIG = ("version: 1\norganization: Acme\nmode: local\nlanguage: auto\nstale_days: 14\n"
                "categories: [code, delivery]\ncollectors: []\nredaction: {extra_patterns: []}\n")


def write_atlas(case, snapshots, order=("scm", "gitops")):
    """Atlas temporário só com o que o context lê: atlas-config.yml, snapshots/_scan.json e o graph.json do build
    (merge + inferência, com a regra 4) dos snapshots."""
    root = Path(tempfile.mkdtemp()).resolve()
    case.addCleanup(shutil.rmtree, root, True)
    atlas = root / "acme-atlas"
    (atlas / "snapshots").mkdir(parents=True)
    state = {cid: {"seen_at": TODAY, "status": "ok", "entities": 1, "relations": 0} for cid in order}
    (atlas / "snapshots" / "_scan.json").write_text(json.dumps(state), encoding="utf-8")
    (atlas / "atlas-config.yml").write_text(ATLAS_CONFIG, encoding="utf-8")
    merged = f("merge_snapshots")(snapshots, list(order), state)
    graph = f("infer_relations")(merged)
    (atlas / "graph.json").write_text(f("render_graph")(graph, "Acme", BUILT_AT), encoding="utf-8")
    return atlas


def service_of(package, key="service:api"):
    found = [s for s in package["services"] if s["key"] == key]
    if not found:
        raise AssertionError(f"{key} não está no pacote: {[s['key'] for s in package['services']]}")
    return found[0]


def service_block(markdown, key):
    """Linhas do item do serviço `key` no Markdown: do título "### ... (`key`)" até o próximo título."""
    lines = markdown.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("### ") and f"(`{key}`)" in line), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(("### ", "## "))), len(lines))
    return lines[start:end]


def entrega_lines(block):
    """As linhas recuadas logo abaixo de "- Entrega:", sem o recuo; None sem a linha "- Entrega:"."""
    if ENTREGA not in block:
        return None
    at = block.index(ENTREGA)
    found = []
    for line in block[at + 1:]:
        if line[:1].isspace() and line.strip().startswith("- "):
            found.append(line.strip())
        else:
            break
    return found


def without_entrega(markdown):
    """O Markdown sem os blocos "- Entrega:" (a linha e as linhas recuadas abaixo dela)."""
    kept, inside = [], False
    for line in markdown.splitlines(keepends=True):
        if line.rstrip("\n") == ENTREGA:
            inside = True
            continue
        if inside and line[:1].isspace() and line.strip().startswith("- "):
            continue
        inside = False
        kept.append(line)
    return "".join(kept)


def strip_delivery(package):
    data = json.loads(json.dumps(package))
    for service in data["services"]:
        service.pop("delivery", None)
    return data


# --------------------------------------------------------------------------- CH-01


def ch01_variant(atlas):
    """Cópia da fixture context com service:search ligado a acme/r3 só por sourced_from (configuração, sem evidência
    image:) e sem deployment nem pipeline: ainda sem caminho de entrega."""
    path = atlas / "graph.json"
    graph = json.loads(path.read_text(encoding="utf-8"))
    graph["edges"].append({"from": "service:search", "to": "repository:acme/r3", "type": "sourced_from",
                           "sources": ["facts"]})
    graph["edges"].sort(key=lambda e: (e["from"], e["type"], e["to"]))
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


CH01_CASES = (  # (nome, consulta, hops, variante); os serviços encontrados não têm caminho de entrega
    ("ledger", "ledger", 1, False),
    ("search", "search", 2, False),
    ("ledger-search", "ledger search", 0, False),
    ("search-config-repo", "search", 1, True),
)
CH01_WITH_PATH = ("cashout-backoffice", "cashout backoffice", 2, False)  # backoffice tem deployment


def ch01_atlas(case, variant):
    root = Path(tempfile.mkdtemp()).resolve()
    case.addCleanup(shutil.rmtree, root, True)
    atlas = root / "acme-atlas"
    shutil.copytree(FIXTURE, atlas)
    if variant:
        ch01_variant(atlas)
    return atlas


class CharacterizationTest(unittest.TestCase):
    def test_services_without_a_delivery_path_give_todays_package_byte_for_byte(self):
        """SPEC-0086:CH-01 — serviços sem deployment, pipeline nem repositório de código (também um só com repositório
        de configuração): o pacote em JSON e em Markdown é igual, byte a byte, ao golden gravado antes da mudança, e
        nenhum serviço tem a chave delivery."""
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        for name, query, hops, variant in CH01_CASES:
            with self.subTest(caso=name):
                want = golden[name]
                package = f("build_context")(ch01_atlas(self, variant), query, hops=hops, today=TODAY)
                self.assertTrue(package["services"], "o caso não encontrou serviço: a comparação não vale")
                for service in package["services"]:
                    self.assertNotIn("delivery", service)
                self.assertEqual(json.dumps(package, ensure_ascii=False, indent=2), want["json"])
                self.assertEqual(f("render_context")(package), want["markdown"])

    def test_services_with_a_delivery_path_keep_todays_keys(self):
        """SPEC-0086:CH-01 — para os serviços com caminho de entrega (backoffice tem deployment), as chaves
        de antes ficam iguais: o pacote sem delivery é igual ao golden, e o Markdown sem os blocos "Entrega" também."""
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        name, query, hops, variant = CH01_WITH_PATH
        want = golden[name]
        package = f("build_context")(ch01_atlas(self, variant), query, hops=hops, today=TODAY)
        self.assertEqual(json.dumps(strip_delivery(package), ensure_ascii=False, indent=2), want["json"])
        self.assertEqual(without_entrega(f("render_context")(package)), want["markdown"])


# --------------------------------------------------------------------------- UT-01 e UT-02


class DeliveryJsonTest(unittest.TestCase):
    def test_image_link_service_has_the_contract_delivery_in_order(self):
        """SPEC-0086:UT-01 — grafo das fixtures image-link (código acme/api, configuração acme/iac, pipelines Build e
        Publish de acme/api, deployments dev-api e qa-api com cluster e estado): context "api" traz delivery
        exatamente como o contrato, com as listas em ordem; as chaves de antes não mudam."""
        atlas = write_atlas(self, image_link_snapshots())
        package = f("build_context")(atlas, "api", today=TODAY)
        service = service_of(package)
        self.assertIn("delivery", service, "service:api sem a chave delivery (SPEC-0086)")
        self.assertEqual(service["delivery"], API_DELIVERY)
        self.assertEqual(service["repositories"], ["acme/api", "acme/iac"])
        self.assertEqual(sorted(d["id"] for d in service["deployments"]), ["dev-api", "qa-api"])
        for deployment in service["deployments"]:
            self.assertEqual(set(deployment), {"id", "environments"})

    def test_service_linked_only_by_repo_url_has_empty_repositories_and_no_missing_status(self):
        """SPEC-0086:UT-02 — serviço ligado só por repoURL, com pipeline e deployment: code_repositories e
        config_repositories são [], pipelines e deployments estão presentes e o deployment sem sync_status não tem
        a chave."""
        atlas = write_atlas(self, config_only_snapshots())
        service = service_of(f("build_context")(atlas, "api", today=TODAY))
        self.assertIn("delivery", service, "service:api sem a chave delivery (SPEC-0086)")
        delivery = service["delivery"]
        self.assertEqual(set(delivery), DELIVERY_KEYS)
        self.assertEqual(delivery["code_repositories"], [])
        self.assertEqual(delivery["config_repositories"], [])
        self.assertEqual(delivery["images"], [])
        self.assertEqual(delivery["pipelines"], [{"id": "acme/iac/deploy", "name": "Deploy", "repository": "acme/iac"}])
        self.assertEqual([d["id"] for d in delivery["deployments"]], ["dev-api", "qa-api"])
        dev, qa = delivery["deployments"]
        self.assertNotIn("sync_status", dev)
        self.assertEqual(dev["health_status"], "Healthy")
        self.assertEqual(dev["clusters"], ["cluster-dev"])
        self.assertEqual(dev["environments"], ["dev"])
        self.assertEqual(dev["images"], [])
        self.assertEqual(qa["clusters"], [])
        self.assertEqual((qa["sync_status"], qa["health_status"]), ("Synced", "Healthy"))


# --------------------------------------------------------------------------- UT-03


class DeliveryMarkdownTest(unittest.TestCase):
    def test_entrega_block_comes_after_deployments_in_the_contract_order_on_one_line(self):
        """SPEC-0086:UT-03 — bloco "Entrega" depois de "Deployments", com as linhas na ordem do contrato; o nome de
        pipeline com crase e quebra de linha sai numa linha só, com '; nenhum texto de ferramenta fixo."""
        atlas = write_atlas(self, image_link_snapshots(publish_name="Pub`lish\nnow"))
        markdown = f("render_context")(f("build_context")(atlas, "api", today=TODAY))
        block = service_block(markdown, "service:api")
        self.assertIsNotNone(block, markdown)
        self.assertIn(ENTREGA, block, f'o serviço não tem o bloco "Entrega":\n{markdown}')
        deployments = next((i for i, line in enumerate(block) if line.startswith("- Deployments:")), None)
        self.assertIsNotNone(deployments, markdown)
        self.assertGreater(block.index(ENTREGA), deployments, markdown)
        self.assertEqual(entrega_lines(block), [
            "- Código: acme/api",
            "- Pipelines: Build (acme/api), Pub'lish now (acme/api)",
            "- Imagens: acme/api",
            "- Configuração (GitOps): acme/iac",
            "- dev: dev-api — cluster cluster-dev; sync Synced; health Healthy",
            "- qa: qa-api — cluster cluster-qa; sync OutOfSync; health Degraded",
        ])
        self.assertNotIn("now", [line.strip()[:3] for line in markdown.splitlines()])
        self.assertNotIn("`lish", markdown)
        lowered = "\n".join(entrega_lines(block)).lower()
        for word in TOOL_WORDS:
            self.assertNotIn(word, lowered, f"texto de ferramenta fixo no bloco: {word}")

    def test_only_the_lines_with_a_value(self):
        """SPEC-0086:UT-03 — sem repositório de código nem imagem, o bloco não tem "Código", "Imagens" nem
        "Configuração (GitOps)"; o deployment sem sync_status não traz "sync"."""
        atlas = write_atlas(self, config_only_snapshots())
        markdown = f("render_context")(f("build_context")(atlas, "api", today=TODAY))
        block = service_block(markdown, "service:api")
        self.assertIsNotNone(block, markdown)
        lines = entrega_lines(block)
        self.assertIsNotNone(lines, f'o serviço não tem o bloco "Entrega":\n{markdown}')
        for label in ("- Código:", "- Imagens:", "- Configuração (GitOps):"):
            self.assertFalse([line for line in lines if line.startswith(label)], f"{label} sem valor:\n{markdown}")
        self.assertIn("- Pipelines: Deploy (acme/iac)", lines)
        dev = [line for line in lines if line.startswith("- dev: dev-api")]
        self.assertEqual(len(dev), 1, lines)
        self.assertNotIn("sync", dev[0])
        self.assertIn("cluster cluster-dev", dev[0])
        self.assertIn("health Healthy", dev[0])
        qa = [line for line in lines if line.startswith("- qa: qa-api")]
        self.assertEqual(len(qa), 1, lines)
        self.assertNotIn("cluster", qa[0])
        self.assertIn("sync Synced", qa[0])


# --------------------------------------------------------------------------- UT-04


class DeliveryFitTest(unittest.TestCase):
    def test_entrega_block_never_appears_without_its_service_and_the_cut_order_is_todays(self):
        """SPEC-0086:UT-04 — com --max-chars que corta serviços, o bloco "Entrega" só aparece com o seu serviço (um
        por serviço mantido que tem delivery, nenhum de serviço omitido) e a ordem do corte (serviços -> regras ->
        dependências -> dicas) é a de hoje."""
        build, render = f("build_context"), f("render_context")
        query = "cashout backoffice payments"
        full = build(FIXTURE, query, hops=2, today=TODAY)
        with_path = [s["key"] for s in full["services"] if s["key"] in ("service:backoffice", "service:payments")]
        self.assertEqual(sorted(with_path), ["service:backoffice", "service:payments"], full["services"])
        for key in with_path:
            self.assertIn("delivery", service_of(full, key), f"{key} tem deployment e não tem delivery (SPEC-0086)")
            self.assertIsNotNone(entrega_lines(service_block(render(full), key)), f'{key} sem o bloco "Entrega"')
        order = ("services", "rules", "dependencies", "hints")
        cut_services = False
        for max_chars in range(100, len(render(full)) + 50, 20):
            package = build(FIXTURE, query, hops=2, max_chars=max_chars, today=TODAY)
            markdown = render(package)
            kept = {s["key"] for s in package["services"]}
            if len(kept) < len(full["services"]):
                cut_services = True
            with self.subTest(max_chars=max_chars):
                self.assertEqual(markdown.count(ENTREGA), len([s for s in package["services"] if "delivery" in s]))
                for service in full["services"]:
                    block = service_block(markdown, service["key"])
                    if service["key"] not in kept:
                        self.assertIsNone(block)
                    elif "delivery" in service:
                        self.assertIsNotNone(entrega_lines(block), f"{service['key']} mantido sem o bloco")
                for before, after in zip(order, order[1:]):
                    if package[after]:
                        self.assertEqual(len(package[before]), len(full[before]),
                                         f"{after} entrou antes de todo {before} caber")
        self.assertTrue(cut_services, "nenhum tamanho cortou serviços: o teste não vale")


# --------------------------------------------------------------------------- IT-01


def atlas_config(collectors):
    lines = ["version: 1", "organization: Acme", "mode: local", "language: auto", "stale_days: 14",
             "categories: [code, delivery]", "collectors:"]
    for cid, category, command in collectors:
        lines += [f"  - id: {cid}", f"    category: {category}",
                  "    command: [" + ", ".join(json.dumps(a) for a in command) + "]", "    timeout: 60"]
    lines.append("redaction: {extra_patterns: []}")
    return "\n".join(lines) + "\n"


class DeliveryScanTest(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        out = self.sandbox.init(mode="local")
        self.assertEqual(out.returncode, 0, output(out))
        self.atlas = self.sandbox.atlas

    def cli(self, *args):
        result = self.sandbox.run(*args)
        self.assertNotIn("Traceback", output(result), output(result))
        self.assertEqual(result.returncode, 0, output(result))
        return result

    def test_scan_build_and_context_give_the_delivery_of_api_without_tag_or_registry_host(self):
        """SPEC-0086:IT-01 — fixtures image-link (SPEC-0082): scan, build e context --json "api" num atlas temporário
        dão o delivery de service:api com o código, a configuração, as duas pipelines, a imagem e os dois
        deployments; nenhuma saída tem tag nem host de registry."""
        (self.atlas / "atlas-config.yml").write_text(atlas_config([
            ("github", "code", ["python3", "{skill}/assets/collectors/github.py", "--org", "acme", "--input",
                                "{skill}/tests/fixtures/github/image-link"]),
            ("argocd", "delivery", ["python3", "{skill}/assets/collectors/argocd.py", "--from", "argocd",
                                    "--input", "{skill}/tests/fixtures/argocd/image-link.json",
                                    "--service-pattern", PATTERN]),
        ]), encoding="utf-8")
        outputs = [output(self.cli("scan")), output(self.cli("build"))]
        result = self.cli("context", "--json", "api")
        outputs.append(output(result))
        data = json.loads(result.stdout)
        service = service_of(data)
        self.assertIn("delivery", service, "service:api sem a chave delivery (SPEC-0086)")
        self.assertEqual(service["delivery"], API_DELIVERY)
        outputs.append(output(self.cli("context", "api")))
        for text in outputs:
            for piece in TAGS + REGISTRY_HOSTS + ("sha256",):
                with self.subTest(piece=piece):
                    self.assertNotIn(piece, text)


# --------------------------------------------------------------------------- CT-01


SERVICE_TYPES = {"key": str, "name": str, "score": (int, float), "reason": str, "page": str, "repositories": list,
                 "deployments": list, "owners": list, "attrs": dict, "seen_at": str}
PACKAGE_TYPES = {"version": str, "query": str, "warnings": list, "services": list, "dependencies": list,
                 "rules": list, "hints": list, "omitted": list}


class DeliveryContractTest(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        atlas = self.sandbox.atlas
        atlas.parent.mkdir(parents=True)
        shutil.copytree(FIXTURE, atlas)
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        state = {cid: {"seen_at": today, "status": "ok", "entities": 1, "relations": 0} for cid in ("facts", "signals")}
        (atlas / "snapshots" / "_scan.json").write_text(json.dumps(state), encoding="utf-8")
        out = self.sandbox.run("init", "--join", "--atlas", atlas)
        self.assertEqual(out.returncode, 0, output(out))

    def test_todays_keys_and_types_stay_and_delivery_has_the_five_keys(self):
        """SPEC-0086:CT-01 — context --json nas fixtures acme: todas as chaves de antes (references/context.md) existem
        com os mesmos tipos; delivery, quando existe, é um objeto com as cinco chaves do contrato; os serviços com
        deployment (backoffice e payments) têm delivery."""
        result = self.sandbox.run("context", "--json", "--hops", "2", "cashout", "backoffice", "payments")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        for key, kind in PACKAGE_TYPES.items():
            self.assertIsInstance(data.get(key), kind, key)
        self.assertTrue(data["services"])
        with_delivery = set()
        for service in data["services"]:
            with self.subTest(service=service["key"]):
                for key, kind in SERVICE_TYPES.items():
                    self.assertIn(key, service)
                    self.assertIsInstance(service[key], kind, key)
                for item in service["deployments"]:
                    self.assertEqual(set(item), {"id", "environments"})
                    self.assertIsInstance(item["id"], str)
                    self.assertIsInstance(item["environments"], list)
                for owner in service["owners"]:
                    self.assertEqual(set(owner), {"id", "name"})
                if "delivery" not in service:
                    continue
                with_delivery.add(service["key"])
                delivery = service["delivery"]
                self.assertIsInstance(delivery, dict)
                self.assertEqual(set(delivery), DELIVERY_KEYS)
                for key in ("code_repositories", "config_repositories", "images"):
                    self.assertIsInstance(delivery[key], list)
                    self.assertTrue(all(isinstance(v, str) for v in delivery[key]), key)
                    self.assertEqual(delivery[key], sorted(delivery[key]), key)
                for pipeline in delivery["pipelines"]:
                    self.assertEqual(set(pipeline), {"id", "name", "repository"})
                self.assertEqual([p["id"] for p in delivery["pipelines"]],
                                 sorted(p["id"] for p in delivery["pipelines"]))
                for item in delivery["deployments"]:
                    self.assertTrue({"id", "environments", "clusters", "images"} <= set(item), item)
                    self.assertTrue(set(item) <= {"id", "environments", "clusters", "images", "sync_status",
                                                  "health_status"}, item)
                    for key in ("environments", "clusters", "images"):
                        self.assertIsInstance(item[key], list)
                self.assertEqual([d["id"] for d in delivery["deployments"]],
                                 sorted(d["id"] for d in delivery["deployments"]))
        self.assertEqual(with_delivery, {"service:backoffice", "service:payments"})
        for item in data["dependencies"]:
            self.assertTrue({"from", "to", "type", "inferred"} <= set(item))
        self.assertTrue(re.match(r"\S", data["version"]))


if __name__ == "__main__":
    unittest.main()
