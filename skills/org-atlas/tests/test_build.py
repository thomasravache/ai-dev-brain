"""build: junção dos snapshots, inferência de relações, graph.json e páginas geradas (SPEC-0036: UT-01 a UT-06,
IT-01 a IT-03 e CT-01).

Contrato esperado das funções de scripts/atlas.py (o Implementer segue estes testes):

    merge_snapshots(snapshots: dict, order: list, scan_state: dict) -> dict
        `snapshots` = {<id do coletor>: <conteúdo de snapshots/<id>.json>}; `order` = ids na ordem do
        atlas-config.yml; `scan_state` = conteúdo de snapshots/_scan.json. Devolve o grafo
        {"nodes": [...], "edges": [...]} com nós e arestas no formato do graph.json (seção 6 da spec):
            nó     {"key": "kind:id", "kind", "name", "attrs", "sources": [<id do coletor>], "seen_at",
                    "conflicts": [{"attr", "values": {<id do coletor>: valor}}]}
            aresta {"from", "to", "type", "sources": [<id do coletor>], "inferred": False}
        Mesma chave kind:id em dois coletores = um nó, attrs combinados, as duas fontes. Mesmo atributo com
        valores diferentes = vale o primeiro coletor de `order` e o conflito entra em `conflicts` com o valor de
        cada coletor. Mesma relação (from, type, to) em dois coletores = uma aresta com as duas fontes.
        `sources` são ids de coletor (os de `order` e do _scan.json); `seen_at` é o do _scan.json do coletor.

    infer_relations(graph: dict) -> dict
        Grafo novo (o de entrada não muda) com as arestas declaradas e as inferidas (`inferred: True`):
        (1) deployment com `sourced_from` e `deploys` -> aresta do serviço para o repositório;
        (2) item de `config_refs` (KEY=host) de um deployment cujo host é igual ao `host` ou ao nome de um
            datastore, queue, topic ou bucket -> `depends_on` do serviço do deployment para essa entidade, com
            `evidence` = o item ("DB_URL=db.interno");
        (3) host igual ao nome de outro service -> `depends_on` entre os serviços, com `evidence`.
        Só igualdade: host desconhecido ou só parecido não gera aresta nem nó.

    render_graph(graph: dict, organization: str, built_at: str) -> str
        Texto do graph.json: {"version": 1, "organization", "built_at", "nodes", "edges"}; nós ordenados por
        `key`, arestas por (from, type, to). Mesmos snapshots (em qualquer ordem) = texto idêntico.

    render_pages(graph: dict, existing: dict, organization: str, previous=None) -> dict
        {<caminho relativo ao atlas>: <texto>} para "ATLAS.md", "services/<id>.md" e "platform/<categoria>.md".
        `existing` = {<caminho>: <texto atual>} das páginas que já existem; `previous` = grafo anterior (o
        graph.json lido do disco), para a data de uma entidade que sumiu. Só o conteúdo entre
        <!-- atlas:begin <nome> --> e <!-- atlas:end <nome> --> muda; página nova vem de assets/pages/.

CLI (seção 6; mensagens podem ir para stdout ou stderr):
    build [--json]   — também roda sozinho no fim de todo scan
    "Grafo: N nós, M arestas (I inferidas), C conflitos; P páginas atualizadas"
    grava <atlas>/graph.json, ATLAS.md, services/<id>.md e platform/<categoria>.md.
"""
import copy
import datetime
import json
import re
import unittest

from helpers import SKILL, TESTS, Sandbox, fn, output, snapshot

SPEC = "SPEC-0036"
FIXTURES = TESTS / "fixtures"
BUILD_FIXTURES = "{skill}/tests/fixtures/build"
GRAPH_REFERENCE = SKILL / "references" / "graph.md"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REF_RE = re.compile(r"^[a-z][a-z-]*:.+$")
REGION_RE = re.compile(r"<!-- atlas:begin ([\w-]+) -->(.*?)<!-- atlas:end \1 -->", re.DOTALL)
SUMMARY_RE = re.compile(r"Grafo: (\d+) nós, (\d+) arestas \((\d+) inferidas\), (\d+) conflitos; "
                        r"(\d+) páginas atualizadas")
NOT_SEEN_RE = re.compile(r"^_Não visto desde (\d{4}-\d{2}-\d{2})\._$")
SERVICE_REGIONS = ("summary", "repository", "deployments", "depends-on", "used-by", "owners", "pipelines", "sources")
ATLAS_REGIONS = ("summary", "services", "scans")
NODE_KEYS = ("key", "kind", "name", "attrs", "sources", "seen_at", "conflicts")
EDGE_KEYS = ("from", "to", "type", "sources", "inferred")
DAY = "2026-10-30"


def f(name):
    return fn(name, SPEC)


def constant(name):
    return fn(name, "SPEC-0033")


def today_values():
    return {datetime.date.today().isoformat(), datetime.datetime.now(datetime.timezone.utc).date().isoformat()}


def expected(name):
    """Saída esperada de um coletor da skill (SPEC-0034, SPEC-0035), como snapshot normalizado."""
    data = json.loads((FIXTURES / name / "expected-acme.json").read_text(encoding="utf-8"))
    category = {"github": "code", "argocd": "delivery"}[name]
    return {"contract": "org-atlas/collector@1", "collector": name, "category": category,
            "collected_at": f"{DAY}T12:00:00Z", "entities": data["entities"], "relations": data["relations"]}


def ent(kind, eid, attrs=None, source="x"):
    return {"kind": kind, "id": eid, "name": eid, "attrs": attrs or {}, "source": source}


def rel(src, rtype, dst, source="x"):
    return {"from": src, "to": dst, "type": rtype, "source": source}


def snap(cid, entities, relations=(), category="code"):
    return {"contract": "org-atlas/collector@1", "collector": cid, "category": category,
            "collected_at": f"{DAY}T12:00:00Z", "entities": list(entities), "relations": list(relations)}


def state(*cids, day=DAY):
    return {cid: {"seen_at": day, "status": "ok", "entities": 0, "relations": 0} for cid in cids}


def db_facts():
    data = json.loads((FIXTURES / "build" / "db-facts.json").read_text(encoding="utf-8"))
    entities = [dict(e, source="db-facts") for e in data["entities"]]
    relations = [dict(r, source="db-facts") for r in data["relations"]]
    return snap("db-facts", entities, relations, category="data")


def acme_snapshots():
    return {"github": expected("github"), "argocd": expected("argocd"), "db-facts": db_facts()}


ACME_ORDER = ["github", "argocd", "db-facts"]


def acme_graph():
    merged = f("merge_snapshots")(acme_snapshots(), ACME_ORDER, state(*ACME_ORDER))
    return f("infer_relations")(merged)


def nodes_by_key(graph):
    return {node["key"]: node for node in graph["nodes"]}


def find_edges(graph, src=None, dst=None, rtype=None, inferred=None):
    return [e for e in graph["edges"]
            if (src is None or e["from"] == src) and (dst is None or e["to"] == dst)
            and (rtype is None or e["type"] == rtype) and (inferred is None or e.get("inferred") is inferred)]


def inferred_pairs(graph, rtype=None):
    return {(e["from"], e["to"]) for e in find_edges(graph, rtype=rtype, inferred=True)}


def regions(text):
    return {m.group(1): m.group(2) for m in REGION_RE.finditer(text)}


def outside(text):
    """O texto do time: tudo menos o conteúdo das regiões geradas (os marcadores ficam)."""
    return REGION_RE.sub(lambda m: f"<!-- atlas:begin {m.group(1)} --><!-- atlas:end {m.group(1)} -->", text)


def set_region(text, name, body):
    pattern = re.compile(rf"(<!-- atlas:begin {re.escape(name)} -->).*?(<!-- atlas:end {re.escape(name)} -->)", re.DOTALL)
    return pattern.sub(lambda m: m.group(1) + body + m.group(2), text, count=1)


def add_team_notes(text, title_note, notes_note):
    """Uma linha do time logo depois do título e outra depois de "## Notas"."""
    lines = text.splitlines(keepends=True)
    lines.insert(1, f"\n{title_note}\n")
    marker = next(i for i, line in enumerate(lines) if line.strip() == "## Notas")
    lines.insert(marker + 1, f"\n{notes_note}\n")
    return "".join(lines)


# --------------------------------------------------------------------------- unitários


class MergeSnapshotsTest(unittest.TestCase):
    def test_same_entity_in_two_collectors_is_one_node_with_both_attrs_and_sources(self):
        """SPEC-0036:UT-01"""
        snapshots = {
            "argocd": snap("argocd", [ent("service", "payments", {"namespace": "payments-prod"}, "argocd")]),
            "db-facts": snap("db-facts", [ent("service", "payments", {"tier": 1, "language": "go"}, "db-facts")]),
        }
        graph = f("merge_snapshots")(snapshots, ["argocd", "db-facts"], state("argocd", "db-facts"))
        self.assertEqual([n["key"] for n in graph["nodes"]], ["service:payments"])
        node = graph["nodes"][0]
        self.assertEqual(node["kind"], "service")
        self.assertEqual(node["name"], "payments")
        self.assertEqual(node["attrs"], {"namespace": "payments-prod", "tier": 1, "language": "go"})
        self.assertEqual(set(node["sources"]), {"argocd", "db-facts"})
        self.assertEqual(node["conflicts"], [])
        self.assertEqual(node["seen_at"], DAY)

    def test_same_relation_in_two_collectors_is_one_edge_with_both_sources(self):
        """SPEC-0036:UT-01"""
        relation = ("team:acme/payments", "owns", "repository:acme/api")
        snapshots = {
            "github": snap("github", [ent("repository", "acme/api", source="github")],
                           [rel(*relation, source="github")]),
            "owners": snap("owners", [ent("team", "acme/payments", source="owners")], [rel(*relation, source="owners")]),
        }
        graph = f("merge_snapshots")(snapshots, ["github", "owners"], state("github", "owners"))
        edges = find_edges(graph, "team:acme/payments", "repository:acme/api", "owns")
        self.assertEqual(len(edges), 1, graph["edges"])
        self.assertEqual(set(edges[0]["sources"]), {"github", "owners"})
        self.assertIs(edges[0]["inferred"], False)

    def test_seen_at_of_a_node_is_the_one_of_its_collector_in_scan_state(self):
        """SPEC-0036:UT-01"""
        snapshots = {"github": snap("github", [ent("repository", "acme/api", source="github")]),
                     "argocd": snap("argocd", [ent("deployment", "api-prod", source="argocd")])}
        scan_state = {**state("github", day="2026-10-28"), **state("argocd", day="2026-10-30")}
        nodes = nodes_by_key(f("merge_snapshots")(snapshots, ["github", "argocd"], scan_state))
        self.assertEqual(nodes["repository:acme/api"]["seen_at"], "2026-10-28")
        self.assertEqual(nodes["deployment:api-prod"]["seen_at"], "2026-10-30")
        self.assertEqual(nodes["repository:acme/api"]["sources"], ["github"])

    def test_github_argocd_and_generic_snapshots_keep_every_entity_and_relation(self):
        """SPEC-0036:UT-01"""
        snapshots = acme_snapshots()
        graph = f("merge_snapshots")(copy.deepcopy(snapshots), ACME_ORDER, state(*ACME_ORDER))
        keys = {f"{e['kind']}:{e['id']}" for s in snapshots.values() for e in s["entities"]}
        relations = {(r["from"], r["type"], r["to"]) for s in snapshots.values() for r in s["relations"]}
        self.assertEqual(sorted(n["key"] for n in graph["nodes"]), sorted(keys))
        self.assertEqual({(e["from"], e["type"], e["to"]) for e in graph["edges"]}, relations)
        self.assertEqual(len(graph["edges"]), len(relations))
        self.assertTrue(all(e["inferred"] is False for e in graph["edges"]))


class ConflictTest(unittest.TestCase):
    def snapshots(self):
        return {"alpha": snap("alpha", [ent("service", "api", {"tier": 2, "lang": "go"}, "alpha")]),
                "zeta": snap("zeta", [ent("service", "api", {"tier": 1, "lang": "go"}, "zeta")])}

    def test_first_collector_in_config_order_wins_and_the_conflict_is_recorded(self):
        """SPEC-0036:UT-02"""
        node = f("merge_snapshots")(self.snapshots(), ["zeta", "alpha"], state("alpha", "zeta"))["nodes"][0]
        self.assertEqual(node["attrs"], {"tier": 1, "lang": "go"})
        self.assertEqual(node["conflicts"], [{"attr": "tier", "values": {"zeta": 1, "alpha": 2}}])

    def test_the_winner_follows_the_config_order_not_the_name(self):
        """SPEC-0036:UT-02"""
        node = f("merge_snapshots")(self.snapshots(), ["alpha", "zeta"], state("alpha", "zeta"))["nodes"][0]
        self.assertEqual(node["attrs"]["tier"], 2)
        self.assertEqual(node["conflicts"], [{"attr": "tier", "values": {"alpha": 2, "zeta": 1}}])

    def test_equal_values_are_not_a_conflict(self):
        """SPEC-0036:UT-02"""
        snapshots = {"a": snap("a", [ent("repository", "acme/api", {"topics": ["go", "pay"], "archived": False}, "a")]),
                     "b": snap("b", [ent("repository", "acme/api", {"topics": ["go", "pay"], "archived": False}, "b")])}
        node = f("merge_snapshots")(snapshots, ["a", "b"], state("a", "b"))["nodes"][0]
        self.assertEqual(node["conflicts"], [])
        self.assertEqual(node["attrs"], {"topics": ["go", "pay"], "archived": False})


class RepositoryOfServiceTest(unittest.TestCase):
    def merged(self):
        snapshots = {"github": expected("github"), "argocd": expected("argocd")}
        return f("merge_snapshots")(snapshots, ["github", "argocd"], state("github", "argocd"))

    def test_deployment_with_sourced_from_and_deploys_links_the_service_to_the_repository(self):
        """SPEC-0036:UT-03"""
        graph = f("infer_relations")(self.merged())
        for service, repository in (("service:api", "repository:acme/api"), ("service:web", "repository:acme/web")):
            edges = find_edges(graph, service, repository, "sourced_from", inferred=True)
            self.assertEqual(len(edges), 1, f"{service} -> {repository}: {graph['edges']}")
            self.assertEqual(find_edges(graph, service, repository, inferred=True), edges)  # só sourced_from
        # ingress-nginx não tem sourced_from: nenhum repositório inventado
        self.assertEqual(find_edges(graph, "service:ingress-nginx", inferred=True), [])

    def test_declared_edges_stay_and_the_input_graph_does_not_change(self):
        """SPEC-0036:UT-03"""
        merged = self.merged()
        before = copy.deepcopy(merged)
        graph = f("infer_relations")(merged)
        self.assertEqual(merged, before, "infer_relations mudou o grafo de entrada")
        for edge in before["edges"]:
            self.assertIn(edge, graph["edges"])
        self.assertEqual(graph["nodes"], before["nodes"])


class ConfigRefsTest(unittest.TestCase):
    def graph(self, config_refs, others):
        entities = [ent("deployment", "api-prod", {"config_refs": config_refs}, "argocd"),
                    ent("service", "api", source="argocd")]
        snapshots = {"argocd": snap("argocd", entities, [rel("deployment:api-prod", "deploys", "service:api", "argocd")],
                                    category="delivery"),
                     "facts": snap("facts", others, category="data")}
        merged = f("merge_snapshots")(snapshots, ["argocd", "facts"], state("argocd", "facts"))
        return merged, f("infer_relations")(merged)

    def test_datastore_host_and_service_name_give_two_depends_on_with_evidence_and_unknown_host_gives_none(self):
        """SPEC-0036:UT-04"""
        others = [ent("datastore", "payments-db", {"host": "db.interno"}, "facts"), ent("service", "ledger", source="facts")]
        refs = ["DB_URL=db.interno", "LEDGER_URL=ledger", "SENTRY_DSN=o0.ingest.example.io"]
        merged, graph = self.graph(refs, others)
        inferred = find_edges(graph, rtype="depends_on", inferred=True)
        self.assertEqual({(e["from"], e["to"], e.get("evidence")) for e in inferred},
                         {("service:api", "datastore:payments-db", "DB_URL=db.interno"),
                          ("service:api", "service:ledger", "LEDGER_URL=ledger")})
        self.assertEqual(len(inferred), 2, inferred)
        self.assertEqual(graph["nodes"], merged["nodes"], "host desconhecido virou nó")
        self.assertFalse([e for e in graph["edges"] if "o0.ingest.example.io" in json.dumps(e)])

    def test_queue_topic_bucket_and_datastore_match_by_name(self):
        """SPEC-0036:UT-04"""
        others = [ent("queue", "orders-staging", source="facts"), ent("topic", "payments.events", source="facts"),
                  ent("bucket", "acme-uploads", source="facts"), ent("datastore", "redis-prod", source="facts")]
        refs = ["CACHE_HOST=redis-prod", "EVENTS_TOPIC=payments.events", "ORDERS_QUEUE=orders-staging",
                "UPLOADS_BUCKET=acme-uploads"]
        _, graph = self.graph(refs, others)
        self.assertEqual({(e["from"], e["to"], e.get("evidence")) for e in find_edges(graph, inferred=True)},
                         {("service:api", "datastore:redis-prod", "CACHE_HOST=redis-prod"),
                          ("service:api", "topic:payments.events", "EVENTS_TOPIC=payments.events"),
                          ("service:api", "queue:orders-staging", "ORDERS_QUEUE=orders-staging"),
                          ("service:api", "bucket:acme-uploads", "UPLOADS_BUCKET=acme-uploads")})

    def test_similar_hosts_and_the_own_service_name_give_no_edge(self):
        """SPEC-0036:UT-04"""
        others = [ent("datastore", "payments-db", {"host": "db.interno"}, "facts"), ent("service", "ledger", source="facts")]
        refs = ["BACKUP_URL=db.interno.backup", "LEDGER_URL=ledger.acme.example", "SELF_URL=api", "X_HOST=payments"]
        merged, graph = self.graph(refs, others)
        self.assertEqual(find_edges(graph, inferred=True), [], "só igualdade de host ou de nome gera aresta")
        self.assertEqual(graph["nodes"], merged["nodes"])


class DeterminismTest(unittest.TestCase):
    @staticmethod
    def shuffled(snapshots):
        out = {}
        for cid in reversed(list(snapshots)):
            data = copy.deepcopy(snapshots[cid])
            data["entities"] = [dict(e, attrs=dict(reversed(list(e["attrs"].items()))))
                                for e in reversed(data["entities"])]
            data["relations"] = list(reversed(data["relations"]))
            out[cid] = data
        return out

    def render(self, snapshots):
        merged = f("merge_snapshots")(snapshots, ACME_ORDER, state(*ACME_ORDER))
        return f("render_graph")(f("infer_relations")(merged), "Acme", DAY)

    def test_same_snapshots_in_another_order_give_an_identical_graph_json(self):
        """SPEC-0036:UT-05"""
        snapshots = acme_snapshots()
        # um conflito também precisa sair igual
        snapshots["db-facts"]["entities"].append(ent("service", "api", {"tier": 1}, "db-facts"))
        snapshots["argocd"]["entities"] = [ent("service", "api", {"tier": 3}, "argocd") if e["id"] == "api"
                                           and e["kind"] == "service" else e for e in snapshots["argocd"]["entities"]]
        first = self.render(copy.deepcopy(snapshots))
        second = self.render(self.shuffled(snapshots))
        self.assertIsInstance(first, str)
        self.assertEqual(first, second)
        self.assertEqual(first, self.render(copy.deepcopy(snapshots)))

    def test_graph_json_nodes_and_edges_are_sorted_by_key(self):
        """SPEC-0036:UT-05"""
        graph = acme_graph()
        shuffled = dict(graph, nodes=list(reversed(graph["nodes"])), edges=list(reversed(graph["edges"])))
        text = f("render_graph")(shuffled, "Acme", DAY)
        self.assertEqual(text, f("render_graph")(graph, "Acme", DAY))
        data = json.loads(text)
        keys = [n["key"] for n in data["nodes"]]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(keys), len(set(keys)))
        edge_keys = [(e["from"], e["type"], e["to"]) for e in data["edges"]]
        self.assertEqual(edge_keys, sorted(edge_keys))
        self.assertEqual(len(edge_keys), len(set(edge_keys)))


class RenderPagesTest(unittest.TestCase):
    def test_regenerating_a_page_changes_only_the_regions(self):
        """SPEC-0036:UT-06"""
        graph = acme_graph()
        render = f("render_pages")
        fresh = render(graph, {}, "Acme")["services/api.md"]
        edited = add_team_notes(fresh, "Contexto escrito pelo time, logo depois do título.",
                                "Nota do time: o api fala com o legado por fila.")
        edited = set_region(edited, "summary", "\nconteúdo antigo\n")
        again = render(graph, {"services/api.md": edited}, "Acme")["services/api.md"]
        self.assertEqual(outside(again), outside(edited), "texto fora das regiões mudou")
        self.assertEqual(regions(again), regions(fresh), "regiões não foram regeneradas")
        self.assertIn("Nota do time: o api fala com o legado por fila.", again)

    def test_new_pages_come_with_title_regions_and_notes(self):
        """SPEC-0036:UT-06"""
        pages = f("render_pages")(acme_graph(), {}, "Acme")
        for service in ("api", "web", "ingress-nginx", "billing"):
            text = pages[f"services/{service}.md"]
            self.assertTrue(text.startswith("# ") and service in text.splitlines()[0], text[:200])
            self.assertTrue(set(SERVICE_REGIONS) <= set(regions(text)), f"{service}: {sorted(regions(text))}")
            self.assertIn("## Notas", [line.strip() for line in text.splitlines()])
        self.assertTrue(set(ATLAS_REGIONS) <= set(regions(pages["ATLAS.md"])), sorted(regions(pages["ATLAS.md"])))
        platform = {path: text for path, text in pages.items() if path.startswith("platform/")}
        self.assertTrue(platform, f"nenhuma página platform/: {sorted(pages)}")
        categories = constant("CATEGORIES")
        for path, text in platform.items():
            self.assertRegex(path, r"^platform/[a-z]+\.md$")
            self.assertIn(path[len("platform/"):-3], categories)
            self.assertIn("entities", regions(text), path)
            self.assertIn("## Notas", [line.strip() for line in text.splitlines()])


# --------------------------------------------------------------------------- integração (CLI)


def build_config(argocd_without=()):
    replay = ["python3", f"{BUILD_FIXTURES}/replay.py"]
    without = [arg for key in argocd_without for arg in ("--without", key)]
    collectors = [
        ("github", "code", [*replay, "github", "code", "{skill}/tests/fixtures/github/expected-acme.json"]),
        ("argocd", "delivery", [*replay, "argocd", "delivery", "{skill}/tests/fixtures/argocd/expected-acme.json",
                                *without]),
        ("db-facts", "data", ["python3", "{skill}/assets/collectors/generic.py", "--facts",
                              f"{BUILD_FIXTURES}/db-facts.json", "--category", "data", "--source", "db-facts"]),
    ]
    lines = ["collectors:"]
    for cid, category, command in collectors:
        lines += [f"  - id: {cid}", f"    category: {category}",
                  "    command: [" + ", ".join(json.dumps(a) for a in command) + "]", "    timeout: 60"]
    return ("version: 1\norganization: Acme\nmode: local\nlanguage: auto\nstale_days: 14\n"
            "categories: [code, delivery]\n" + "\n".join(lines) + "\nredaction: {extra_patterns: []}\n")


ACME_INFERRED = {("service:api", "repository:acme/api"), ("service:web", "repository:acme/web"),
                 ("service:api", "datastore:payments-db")}


class BuildCase(unittest.TestCase):
    """Atlas novo (init --mode local) com os coletores falsos de GitHub e Argo CD e o generic com o banco."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        out = self.sandbox.init(mode="local")
        self.assertEqual(out.returncode, 0, output(out))
        self.atlas = self.sandbox.atlas
        self.configure()

    def configure(self, argocd_without=()):
        (self.atlas / "atlas-config.yml").write_text(build_config(argocd_without), encoding="utf-8")

    def run_cli(self, *args, code=0):
        result = self.sandbox.run(*args)
        self.assertNotIn("Traceback", output(result), output(result))
        self.assertEqual(result.returncode, code, output(result))
        return result

    def scan(self):
        return self.run_cli("scan")

    def graph(self):
        path = self.atlas / "graph.json"
        self.assertTrue(path.is_file(), "graph.json não foi gravado na pasta do atlas")
        return json.loads(path.read_text(encoding="utf-8"))

    def page(self, rel_path):
        path = self.atlas / rel_path
        self.assertTrue(path.is_file(), f"{rel_path} não foi gerado")
        return path.read_text(encoding="utf-8")

    def summary(self, result):
        match = SUMMARY_RE.search(output(result))
        self.assertIsNotNone(match, f"sem a linha 'Grafo: ...':\n{output(result)}")
        return [int(n) for n in match.groups()]


class AtlasBuildTest(BuildCase):
    def test_scan_builds_the_repository_deployment_service_database_chain(self):
        """SPEC-0036:IT-01"""
        result = self.scan()
        graph = self.graph()
        nodes = nodes_by_key(graph)
        self.assertEqual(len(nodes), 28, sorted(nodes))  # 13 do GitHub, 13 do Argo CD, 2 do generic
        declared = [("deployment:api-prod", "sourced_from", "repository:acme/api"),
                    ("deployment:api-prod", "deploys", "service:api")]
        for src, rtype, dst in declared:
            edges = find_edges(graph, src, dst, rtype)
            self.assertEqual(len(edges), 1, f"{src} {rtype} {dst}")
            self.assertIs(edges[0]["inferred"], False)
            self.assertEqual(edges[0]["sources"], ["argocd"])
        db = find_edges(graph, "service:api", "datastore:payments-db", "depends_on", inferred=True)
        self.assertEqual(len(db), 1, graph["edges"])
        self.assertEqual(db[0]["evidence"], "DB_URL=db-prod.interno")
        self.assertEqual(inferred_pairs(graph), ACME_INFERRED)
        for service, repository in (("service:api", "repository:acme/api"), ("service:web", "repository:acme/web")):
            self.assertEqual(len(find_edges(graph, service, repository, "sourced_from", inferred=True)), 1,
                             f"{service} sourced_from {repository} (inferida) não está no graph.json")
        self.assertEqual(nodes["datastore:payments-db"]["sources"], ["db-facts"])
        self.assertEqual(nodes["repository:acme/api"]["sources"], ["github"])
        self.assertIn(nodes["service:api"]["seen_at"], today_values())
        n, m, i, c, p = self.summary(result)
        self.assertEqual((n, m, i), (len(graph["nodes"]), len(graph["edges"]), len(inferred_pairs(graph))))
        self.assertEqual(c, sum(len(node["conflicts"]) for node in graph["nodes"]))
        self.assertGreaterEqual(p, 5)  # ATLAS.md e os quatro serviços, ao menos

    def test_scan_writes_atlas_service_and_platform_pages(self):
        """SPEC-0036:IT-01"""
        self.scan()
        atlas_regions = regions(self.page("ATLAS.md"))
        self.assertTrue(set(ATLAS_REGIONS) <= set(atlas_regions), sorted(atlas_regions))
        for service in ("api", "web", "ingress-nginx", "billing"):
            self.assertIn(f"services/{service}.md", atlas_regions["services"])
        scans = atlas_regions["scans"]
        for cid in ACME_ORDER:
            self.assertIn(cid, scans)
        self.assertTrue(any(day in scans for day in today_values()), scans)
        counts = {"repository": 5, "pipeline": 5, "team": 3, "deployment": 4, "service": 4, "environment": 3,
                  "cluster": 3, "datastore": 1}
        for kind, count in counts.items():
            self.assertIn(str(count), atlas_regions["summary"], kind)

        api = regions(self.page("services/api.md"))
        self.assertTrue(set(SERVICE_REGIONS) <= set(api), sorted(api))
        self.assertTrue(api["summary"].strip())
        self.assertNotIn("Não visto desde", api["summary"])
        self.assertIn("acme/api", api["repository"])
        for word in ("api-prod", "api-staging", "prod", "staging"):
            self.assertIn(word, api["deployments"])
        self.assertIn("payments-db", api["depends-on"])
        self.assertIn("billing", api["used-by"])
        for team in ("payments", "docs-team"):
            self.assertIn(team, api["owners"])
        for pipeline in ("ci", "release"):
            self.assertIn(pipeline, api["pipelines"])
        self.assertIn("argocd", api["sources"])
        self.assertIn("api", regions(self.page("services/billing.md"))["depends-on"])

        platform = sorted((self.atlas / "platform").glob("*.md"))
        self.assertTrue(platform, "nenhuma página em platform/")
        with_db = [p for p in platform if "payments-db" in regions(p.read_text(encoding="utf-8")).get("entities", "")]
        self.assertEqual(len(with_db), 1, [p.name for p in platform])
        self.assertIn(with_db[0].stem, constant("CATEGORIES"))

    def test_build_alone_rebuilds_graph_and_pages_from_the_snapshots(self):
        """SPEC-0036:IT-01"""
        self.scan()
        graph = self.page("graph.json")
        self.page("services/web.md")
        (self.atlas / "graph.json").unlink()
        (self.atlas / "services" / "web.md").unlink()
        result = self.run_cli("build")
        self.summary(result)
        self.assertEqual((self.atlas / "graph.json").read_text(encoding="utf-8"), graph)
        self.assertTrue(set(SERVICE_REGIONS) <= set(regions(self.page("services/web.md"))))

    def test_build_json_prints_one_object(self):
        """SPEC-0036:IT-01"""
        self.scan()
        result = self.run_cli("build", "--json")
        self.assertIsInstance(json.loads(result.stdout), dict)

    def test_unreadable_snapshot_is_a_warning_and_the_build_goes_on(self):
        """SPEC-0036:IT-01 (seção 5: snapshot ilegível -> aviso e o build segue com os outros)"""
        self.scan()
        text = (self.atlas / "atlas-config.yml").read_text(encoding="utf-8")
        broken = ('  - id: broken\n    category: code\n    command: ["python3", "{skill}/tests/fixtures/build/replay.py"]\n'
                  "    timeout: 60\nredaction:")
        (self.atlas / "atlas-config.yml").write_text(text.replace("redaction:", broken, 1), encoding="utf-8")
        (self.atlas / "snapshots" / "broken.json").write_text('{"entities": [', encoding="utf-8")
        self.page("graph.json")
        (self.atlas / "graph.json").unlink()
        result = self.run_cli("build")
        lines = [line for line in output(result).splitlines() if "aviso" in line.lower() and "broken" in line]
        self.assertTrue(lines, f"sem aviso sobre snapshots/broken.json:\n{output(result)}")
        self.assertEqual(len(self.graph()["nodes"]), 28)


class TeamTextTest(BuildCase):
    def test_team_note_in_a_service_page_survives_a_new_scan(self):
        """SPEC-0036:IT-02"""
        self.scan()
        path = self.atlas / "services" / "api.md"
        edited = add_team_notes(self.page("services/api.md"), "Dono de plantão: time payments.",
                                "Nota do time: o deploy de sexta precisa de aprovação.")
        path.write_text(edited, encoding="utf-8")
        self.configure(argocd_without=("deployment:api-staging",))  # as regiões precisam mudar
        self.scan()
        again = path.read_text(encoding="utf-8")
        self.assertEqual(outside(again), outside(edited))
        self.assertIn("Nota do time: o deploy de sexta precisa de aprovação.", again)
        self.assertNotIn("api-staging", regions(again)["deployments"])
        self.assertIn("api-prod", regions(again)["deployments"])

    def test_build_writes_nothing_outside_the_regions_and_graph_json(self):
        """SPEC-0036:IT-02"""
        atlas_page = self.page("ATLAS.md")
        self.scan()
        self.assertEqual(outside(self.page("ATLAS.md")), outside(atlas_page))
        generated = ("ATLAS.md", "graph.json", "services", "platform")
        before = {k: v for k, v in snapshot(self.atlas).items() if not k.startswith(generated)}
        self.run_cli("build")
        after = {k: v for k, v in snapshot(self.atlas).items() if not k.startswith(generated)}
        self.assertEqual(after, before)


class RemovedEntityTest(BuildCase):
    def test_removed_service_keeps_its_page_with_not_seen_since_and_the_team_notes(self):
        """SPEC-0036:IT-03"""
        self.scan()
        path = self.atlas / "services" / "web.md"
        edited = add_team_notes(self.page("services/web.md"), "Contexto do time sobre o web.",
                                "Nota do time: o web vai ser desligado em dezembro.")
        path.write_text(edited, encoding="utf-8")
        self.configure(argocd_without=("service:web", "deployment:web"))
        for _ in range(2):  # o segundo scan sem o serviço mantém a mesma data
            self.scan()
            self.assertNotIn("service:web", nodes_by_key(self.graph()))
            self.assertTrue(path.is_file(), "a página do serviço que sumiu foi apagada")
            text = path.read_text(encoding="utf-8")
            found = regions(text)
            match = NOT_SEEN_RE.match(found["summary"].strip())
            self.assertIsNotNone(match, found["summary"])
            self.assertIn(match.group(1), today_values())
            for name in SERVICE_REGIONS[1:]:
                self.assertEqual(found[name].strip(), "", f"região {name} devia ficar vazia")
            self.assertEqual(outside(text), outside(edited))


# --------------------------------------------------------------------------- nomes das páginas (revisão G4 1)

WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                    *(f"lpt{i}" for i in range(1, 10))}
KEY_LINE_RE = re.compile(r"^- Chave: `([^`]+)`", re.MULTILINE)


def services_config():
    command = ["python3", "{skill}/assets/collectors/generic.py", "--facts", "{atlas}/facts/services.json",
               "--category", "runtime", "--source", "facts"]
    return ("version: 1\norganization: Acme\nmode: local\nlanguage: auto\nstale_days: 14\n"
            "categories: [code, delivery]\ncollectors:\n  - id: facts\n    category: runtime\n"
            "    command: [" + ", ".join(json.dumps(a) for a in command) + "]\n    timeout: 60\n"
            "redaction: {extra_patterns: []}\n")


class PageNamesTest(BuildCase):
    """Um coletor generic com os serviços num arquivo de fatos que o teste reescreve entre os scans."""

    def configure(self, argocd_without=()):
        (self.atlas / "atlas-config.yml").write_text(services_config(), encoding="utf-8")

    def services(self, *ids):
        folder = self.atlas / "facts"
        folder.mkdir(exist_ok=True)
        facts = {"entities": [{"kind": "service", "id": sid} for sid in ids], "relations": []}
        (folder / "services.json").write_text(json.dumps(facts), encoding="utf-8")

    def pages(self):
        return sorted((self.atlas / "services").glob("*.md"))

    def page_of(self, key):
        """O arquivo cuja região summary diz "- Chave: `<key>`" (exatamente um)."""
        found = [p for p in self.pages()
                 if key in KEY_LINE_RE.findall(regions(p.read_text(encoding="utf-8")).get("summary", ""))]
        self.assertEqual(len(found), 1, f"{key}: {[p.name for p in self.pages()]}")
        return found[0]

    def add_note(self, path, note):
        path.write_text(add_team_notes(path.read_text(encoding="utf-8"), "Contexto do time.", note), encoding="utf-8")

    def test_existing_page_keeps_its_service_when_a_case_only_twin_appears(self):
        """SPEC-0036:IT-02 (revisão G4: o nome da página não muda e não colide sem diferenciar maiúsculas)"""
        self.services("Payments")
        self.scan()
        upper = self.page_of("service:Payments")
        self.add_note(upper, "Nota do time sobre o Payments.")
        self.services("Payments", "payments")
        self.scan()
        names = [p.name for p in self.pages()]
        self.assertEqual(len({n.casefold() for n in names}), 2, f"nomes que colidem sem diferenciar maiúsculas: {names}")
        self.assertEqual(self.page_of("service:Payments"), upper)
        self.assertIn("Nota do time sobre o Payments.", upper.read_text(encoding="utf-8"))
        lower = self.page_of("service:payments")
        self.assertNotEqual(lower.name.casefold(), upper.name.casefold())
        self.assertNotIn("Nota do time sobre o Payments.", lower.read_text(encoding="utf-8"))

    def test_page_of_a_gone_service_is_not_taken_by_another_with_the_same_slug(self):
        """SPEC-0036:IT-03 (revisão G4: a-b some e a/b continua no próprio arquivo)"""
        self.services("a-b", "a/b")
        self.scan()
        dash, slash = self.page_of("service:a-b"), self.page_of("service:a/b")
        self.assertNotEqual(dash, slash)
        self.add_note(dash, "Nota do time sobre o a-b.")
        self.services("a/b")
        self.scan()
        self.assertEqual(self.page_of("service:a/b"), slash, "a/b mudou de arquivo")
        slash_text = slash.read_text(encoding="utf-8")
        self.assertNotIn("Nota do time sobre o a-b.", slash_text)
        self.assertIsNone(NOT_SEEN_RE.match(regions(slash_text)["summary"].strip()), "a/b marcado como sumido")
        self.assertTrue(dash.is_file(), "a página do a-b foi apagada")
        dash_text = dash.read_text(encoding="utf-8")
        self.assertIn("Nota do time sobre o a-b.", dash_text)
        self.assertIsNotNone(NOT_SEEN_RE.match(regions(dash_text)["summary"].strip()), regions(dash_text)["summary"])

    def test_very_long_ids_get_short_distinct_and_stable_file_names(self):
        """SPEC-0036:IT-01 (revisão G4: id de 300 caracteres)"""
        prefix = "svc-" + "abcdefghij" * 29
        long_a, long_b = (prefix + "-alpha")[:300], (prefix + "-omega")[:296] + "beta"
        self.assertEqual((len(long_a), len(long_b)), (300, 300))
        self.services(long_a, long_b)
        self.scan()
        first = {key: self.page_of(key).name for key in (f"service:{long_a}", f"service:{long_b}")}
        self.assertEqual(len(set(first.values())), 2, first)
        for name in first.values():
            self.assertLessEqual(len(name), 100, name)
        self.run_cli("build")
        self.scan()
        again = {key: self.page_of(key).name for key in first}
        self.assertEqual(again, first)
        self.assertEqual(len(self.pages()), 2, [p.name for p in self.pages()])

    def test_windows_reserved_names_get_a_suffix(self):
        """SPEC-0036:IT-01 (revisão G4: con, prn, aux, nul, com1-9 e lpt1-9, com ou sem extensão)"""
        ids = ("con", "PRN", "Aux", "nul", "com1", "COM9", "lpt1", "lpt9", "con.txt", "nul.tar.gz")
        self.services(*ids)
        self.scan()
        for sid in ids:
            name = self.page_of(f"service:{sid}").name
            self.assertNotIn(name.split(".")[0].casefold(), WINDOWS_RESERVED, f"{sid}: {name}")
        self.assertEqual(len({p.name.casefold() for p in self.pages()}), len(ids))

    def test_scan_json_reports_a_build_failure_inside_the_single_json_object(self):
        """SPEC-0036:IT-01 (revisão G4: build que falha no scan --json)"""
        self.services("api")
        self.scan()
        self.page_of("service:api").write_bytes(b"# api\n\xff\xfe n\xe3o \xe9 UTF-8\n")
        result = self.sandbox.run("scan", "--json")
        self.assertNotIn("Traceback", output(result), output(result))
        self.assertNotEqual(result.returncode, 0, output(result))
        try:
            data = json.loads(result.stdout)
        except ValueError:
            self.fail(f"stdout não é um único objeto JSON:\n{result.stdout}\n{result.stderr}")
        self.assertIsInstance(data, dict)
        self.assertIn("collectors", data)
        self.assertEqual([c["id"] for c in data["collectors"]], ["facts"])
        self.assertIsInstance(data.get("build"), dict, data)
        self.assertIs(data["build"].get("ok"), False, data["build"])
        self.assertIsInstance(data["build"].get("error"), str)
        self.assertTrue(data["build"]["error"].strip())


# --------------------------------------------------------------------------- contrato


class GraphContractTest(BuildCase):
    def assert_graph_contract(self, data):
        self.assertEqual(data["version"], 1)
        self.assertIsInstance(data["version"], int)
        self.assertEqual(data["organization"], "Acme")
        self.assertRegex(data["built_at"], DATE_RE)
        kinds, relation_types = constant("KINDS"), constant("RELATION_TYPES")
        keys = [n["key"] for n in data["nodes"]]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(keys), len(set(keys)))
        for node in data["nodes"]:
            for key in NODE_KEYS:
                self.assertIn(key, node, node)
            self.assertIn(node["kind"], kinds)
            self.assertTrue(node["key"].startswith(node["kind"] + ":"), node["key"])
            self.assertIsInstance(node["name"], str)
            self.assertIsInstance(node["attrs"], dict)
            self.assertTrue(node["sources"] and all(isinstance(s, str) for s in node["sources"]), node)
            self.assertRegex(node["seen_at"], DATE_RE)
            self.assertIsInstance(node["conflicts"], list)
            for conflict in node["conflicts"]:
                self.assertIsInstance(conflict["attr"], str)
                self.assertIsInstance(conflict["values"], dict)
        edge_keys = [(e["from"], e["type"], e["to"]) for e in data["edges"]]
        self.assertEqual(edge_keys, sorted(edge_keys))
        self.assertEqual(len(edge_keys), len(set(edge_keys)))
        for edge in data["edges"]:
            for key in EDGE_KEYS:
                self.assertIn(key, edge, edge)
            self.assertRegex(edge["from"], REF_RE)
            self.assertRegex(edge["to"], REF_RE)
            self.assertIn(edge["type"], relation_types)
            self.assertIsInstance(edge["inferred"], bool)
            self.assertTrue(edge["sources"] and all(isinstance(s, str) for s in edge["sources"]), edge)
            if "evidence" in edge:
                self.assertIsInstance(edge["evidence"], str)

    def test_graph_json_follows_the_contract(self):
        """SPEC-0036:CT-01"""
        self.scan()
        data = self.graph()
        self.assert_graph_contract(data)
        self.assertIn(data["built_at"], today_values())
        self.assertEqual(inferred_pairs(data), ACME_INFERRED)

    def test_render_graph_follows_the_contract(self):
        """SPEC-0036:CT-01"""
        data = json.loads(f("render_graph")(acme_graph(), "Acme", DAY))
        self.assert_graph_contract(data)
        self.assertEqual(data["built_at"], DAY)

    def test_same_snapshots_give_the_same_graph_json_file(self):
        """SPEC-0036:CT-01"""
        self.scan()
        first = self.page("graph.json").encode("utf-8")
        self.run_cli("build")
        self.assertEqual((self.atlas / "graph.json").read_bytes(), first)
        self.scan()
        self.assertEqual((self.atlas / "graph.json").read_bytes(), first)

    def test_reference_documents_every_key_of_graph_json(self):
        """SPEC-0036:CT-01"""
        self.assertTrue(GRAPH_REFERENCE.is_file(), "references/graph.md não existe")
        text = GRAPH_REFERENCE.read_text(encoding="utf-8")
        for key in ("version", "organization", "built_at", "nodes", "edges", *NODE_KEYS, *EDGE_KEYS, "evidence", "sourced_from"):
            self.assertRegex(text, rf"\b{re.escape(key)}\b", key)


if __name__ == "__main__":
    unittest.main()
