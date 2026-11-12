"""Coletor argocd da boson-atlas (SPEC-0035: UT-01 a UT-04, IT-01 a IT-03 e CT-01).

Contrato esperado de assets/collectors/argocd.py (o Implementer segue estes testes):

    argocd.py --from argocd|kubectl [--env-label CHAVE (padrão env)]
              [--service-label CHAVE (padrão app.kubernetes.io/part-of)]
              [--ref-suffixes _HOST,_URL,_DSN,_ADDR,_QUEUE,_TOPIC,_BUCKET (padrão)] [--input ARQUIVO]
        stdout: um objeto org-atlas/collector@1 com collector "argocd", category "delivery", collected_at ISO 8601
        UTC e source "argocd" em cada entidade e relação; exit 0.
        entidades: deployment:<metadata.name> {project, namespace (de destino), sync_status, health_status,
                       config_refs} (só esses), name = nome da Application
                   service:<serviço>, environment:<ambiente>, cluster:<destination.server, ou destination.name
                       quando não há server>; name = id, attrs {}; cada chave uma vez só na saída
        relações:  deployment -> service (deploys); deployment -> environment (runs_in);
                   deployment -> cluster (runs_in); deployment -> repository:<owner>/<repo> (sourced_from), só
                   quando o repoURL é do GitHub (https, https sem .git, ssh scp-like ou ssh://, com ou sem
                   credencial na URL)
        serviço: label --service-label da Application; sem ele, metadata.name.
        ambiente: label --env-label; sem ele, spec.destination.namespace.
        config_refs: lista ordenada e sem repetição de "CHAVE=host", de spec.source.helm.parameters (nome com
            pontos: a CHAVE é o último segmento, env.DB_URL -> DB_URL), helm.values (texto YAML: linhas
            "CHAVE: valor", com indentação, aspas simples ou duplas e linhas de comentário), helm.valuesObject
            (objeto aninhado, em qualquer profundidade) e plugin.env ({name, value}), só das chaves que terminam
            num sufixo de --ref-suffixes. Valor -> só o host (URL com esquema; host:porta; usuário:senha@host)
            ou o nome do recurso (sem esquema, sem "/"); valor vazio não gera referência. Usuário, senha, porta,
            caminho e query nunca saem.
        --input ARQUIVO: lê as Applications do arquivo (a lista do `argocd app list -o json` ou o objeto List do
            `kubectl get ... -o json`) e nunca chama CLI nenhuma.
        Sem --input: --from argocd roda `argocd app list -o json`; --from kubectl roda
            `kubectl get applications.argoproj.io -A -o json`. Só a CLI escolhida é chamada; nada de Secrets nem
            de manifestos renderizados.
        Erros (exit 1, sem traceback, nada no stdout):
            "<argocd|kubectl> não encontrado — veja references/collectors/argocd.md" (CLI fora do PATH);
            "sem acesso às Applications" (a CLI falha por credencial ou permissão);
            "resposta inválida da CLI" (stdout que não é JSON ou não é uma lista de Applications).
        Nunca saem valores inteiros de configuração, chaves fora da lista, credenciais, anotações nem Secrets.

    Funções (importadas pelo caminho nos testes unitários):
    host_of(value: str) -> str | None
    extract_config_refs(source: dict, suffixes=DEFAULT_REF_SUFFIXES) -> list[str]          (spec.source)
    repository_ref(repo_url: str | None) -> str | None                                   ("repository:o/r")
    service_and_environment(app: dict, env_label="env", service_label="app.kubernetes.io/part-of") -> (str, str)
    map_application(app: dict, env_label=..., service_label=..., suffixes=...) -> (entities, relations)
    map_applications(apps: list, env_label=..., service_label=..., suffixes=...) -> (entities, relations)
        (as entidades compartilhadas, como service, environment e cluster, aparecem uma vez só)

Fixtures: fixtures/argocd/acme/argocd-app-list.json e kubectl-applications.json (as mesmas quatro Applications de
um cluster fictício da organização acme, nos dois formatos), fixtures/argocd/expected-acme.json (saída esperada
sem o cabeçalho) e as CLIs falsas fixtures/argocd/fake_argocd.py e fake_kubectl.py (ver os docstrings). As
fixtures têm valores que parecem segredo (URL com senha, DSN com chave, token fora da lista, anotação
last-applied-configuration, Secret entre os recursos): nenhum deles pode sair no stdout.
"""
import copy
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

from helpers import SKILL, TESTS, Sandbox, fn, output

SPEC = "SPEC-0035"
CONTRACT = "org-atlas/collector@1"
ARGOCD = SKILL / "assets" / "collectors" / "argocd.py"
FIXTURES = TESTS / "fixtures" / "argocd"
ACME = FIXTURES / "acme"
ARGOCD_LIST = ACME / "argocd-app-list.json"
KUBECTL_LIST = ACME / "kubectl-applications.json"
EXPECTED = FIXTURES / "expected-acme.json"
FAKE_ARGOCD = FIXTURES / "fake_argocd.py"
FAKE_KUBECTL = FIXTURES / "fake_kubectl.py"
BOTH_FAKES = types.MappingProxyType({"argocd": FAKE_ARGOCD, "kubectl": FAKE_KUBECTL})
COLLECTED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
GUIDE = "veja references/collectors/argocd.md"
NO_ACCESS = "sem acesso às Applications"
INVALID = "resposta inválida da CLI"
IN_CLUSTER = "https://kubernetes.default.svc"
DEPLOYMENT_ATTRS = {"project", "namespace", "sync_status", "health_status", "config_refs"}
# pedaços das fixtures que nunca podem sair do coletor: credenciais, valores inteiros, chaves fora da lista,
# anotações e o Secret listado entre os recursos da Application
NEVER_OUT = ("fake-pass", "not-a-real-token", "fakepublickey", "sslmode", "debug=1", "5432", "/payments",
             "LOG_LEVEL", "DB_PASSWORD", "API_TOKEN", "NODE_ENV", "FEATURE_FLAGS", "last-applied", "api-db",
             "replicaCount", "acme-uploads/web")

_CACHE = {}


def collector():
    """assets/collectors/argocd.py importado pelo caminho (sem sys.path)."""
    if "module" not in _CACHE:
        if not ARGOCD.exists():
            raise AssertionError(f"{ARGOCD} não existe ({SPEC})")
        spec = importlib.util.spec_from_file_location("org_atlas_collector_argocd", ARGOCD)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CACHE["module"] = module
    return _CACHE["module"]


def function(name):
    f = getattr(collector(), name, None)
    if f is None:
        raise AssertionError(f"argocd.{name} não existe ({SPEC})")
    return f


def applications():
    """As Applications da fixture (formato do argocd app list), novas a cada chamada."""
    return json.loads(ARGOCD_LIST.read_text(encoding="utf-8"))


def application(name):
    return next(copy.deepcopy(a) for a in applications() if a["metadata"]["name"] == name)


def expected():
    data = json.loads(EXPECTED.read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def comparable(data):
    """entities e relations em ordem estável (a ordem da saída não faz parte do contrato)."""
    return {"entities": sorted(data.get("entities", []), key=canonical),
            "relations": sorted(data.get("relations", []), key=canonical)}


def entity(kind, eid, attrs=None):
    return {"kind": kind, "id": eid, "name": eid, "attrs": attrs or {}, "source": "argocd"}


def relation(source_ref, target_ref, rtype):
    return {"from": source_ref, "to": target_ref, "type": rtype, "source": "argocd"}


def targets(relations, rtype, kind=None):
    """{deployment: alvo} das relações de um tipo (e, opcional, de um kind de destino)."""
    found = {}
    for r in relations:
        if r["type"] == rtype and (kind is None or r["to"].startswith(kind + ":")):
            found[r["from"].split(":", 1)[1]] = r["to"]
    return found


def make_bin(**fakes):
    """Pasta temporária com cada CLI falsa copiada com o nome pedido (argocd=..., kubectl=...), executável."""
    folder = Path(tempfile.mkdtemp()).resolve()
    for name, fake in fakes.items():
        target = folder / name
        shutil.copyfile(fake, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return folder


def json_output(argv):
    """True quando os argumentos pedem saída JSON (-o json, -o=json, -ojson, --output json, --output=json)."""
    for i, arg in enumerate(argv):
        if arg in ("-o", "--output") and argv[i + 1:i + 2] == ["json"]:
            return True
        if arg in ("-o=json", "-ojson", "--output=json"):
            return True
    return False


class ArgocdCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = self.tmp / "cli-calls.jsonl"

    def run_argocd(self, *args, fakes=None, path=None, env=None):
        """Roda argocd.py; fakes = {nome: CLI falsa} no início do PATH; path = PATH inteiro (sem o do sistema)."""
        environ = dict(os.environ)
        environ["HOME"] = str(self.tmp)
        environ["FAKE_ARGOCD_OUTPUT"] = str(ARGOCD_LIST)
        environ["FAKE_KUBECTL_OUTPUT"] = str(KUBECTL_LIST)
        environ["FAKE_CLI_LOG"] = str(self.log)
        environ.pop("FAKE_CLI_FAIL", None)
        if fakes:
            folder = make_bin(**fakes)
            self.addCleanup(shutil.rmtree, folder, True)
            environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
        if path is not None:
            environ["PATH"] = str(path)
        environ.update(env or {})
        result = subprocess.run([sys.executable, str(ARGOCD), *[str(a) for a in args]], check=False, cwd=self.tmp,
                                capture_output=True, text=True, env=environ)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def calls(self, cli=None):
        if not self.log.is_file():
            return []
        rows = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [row["argv"] for row in rows if cli is None or row["cli"] == cli]

    def collect(self, *args, **kwargs):
        result = self.run_argocd(*args, **kwargs)
        self.assertEqual(result.returncode, 0, output(result))
        return json.loads(result.stdout), result

    def assert_header(self, data):
        self.assertEqual(data.get("contract"), CONTRACT)
        self.assertEqual(data.get("collector"), "argocd")
        self.assertEqual(data.get("category"), "delivery")
        self.assertRegex(str(data.get("collected_at")), COLLECTED_AT)

    def assert_nothing_secret(self, text):
        for fragment in NEVER_OUT:
            with self.subTest(never_out=fragment):
                self.assertNotIn(fragment, text)

    def assert_failure(self, result, message):
        self.assertEqual(result.returncode, 1, output(result))
        self.assertIn(message, output(result))
        self.assertFalse(result.stdout.strip().startswith(("{", "[")), "nada de saída do contrato numa falha")


# --------------------------------------------------------------------------- unitários


class MapApplicationTest(unittest.TestCase):
    def test_application_becomes_deployment_service_environment_and_cluster(self):
        """SPEC-0035:UT-01 — uma Application gera deployment, service, environment e cluster, com deploys e
        runs_in (ambiente e cluster)."""
        entities, relations = function("map_application")(application("ingress-nginx"))
        self.assertEqual(sorted(entities, key=canonical), sorted([
            {"kind": "deployment", "id": "ingress-nginx", "name": "ingress-nginx",
             "attrs": {"project": "platform", "namespace": "ingress", "sync_status": "Synced",
                       "health_status": "Healthy", "config_refs": []},
             "source": "argocd"},
            entity("service", "ingress-nginx"),
            entity("environment", "prod"),
            entity("cluster", IN_CLUSTER),
        ], key=canonical))
        self.assertEqual(sorted(relations, key=canonical), sorted([
            relation("deployment:ingress-nginx", "service:ingress-nginx", "deploys"),
            relation("deployment:ingress-nginx", "environment:prod", "runs_in"),
            relation("deployment:ingress-nginx", f"cluster:{IN_CLUSTER}", "runs_in"),
        ], key=canonical))

    def test_deployment_has_only_the_contract_attributes(self):
        """SPEC-0035:UT-01 — o deployment traz só project, namespace, sync_status, health_status e config_refs,
        com o estado de sync e de saúde da Application."""
        entities, _ = function("map_application")(application("api-staging"))
        deployment = next(e for e in entities if e["kind"] == "deployment")
        self.assertEqual(deployment["id"], "api-staging")
        self.assertEqual(deployment["name"], "api-staging")
        self.assertEqual(set(deployment["attrs"]), DEPLOYMENT_ATTRS)
        self.assertEqual(deployment["attrs"]["project"], "payments")
        self.assertEqual(deployment["attrs"]["namespace"], "payments-staging")
        self.assertEqual(deployment["attrs"]["sync_status"], "OutOfSync")
        self.assertEqual(deployment["attrs"]["health_status"], "Progressing")

    def test_cluster_comes_from_the_server_or_the_name(self):
        """SPEC-0035:UT-01 — cluster:<destination.server>; sem server, cluster:<destination.name>."""
        _, staging = function("map_application")(application("api-staging"))
        self.assertIn(relation("deployment:api-staging", "cluster:https://10.20.0.1:6443", "runs_in"), staging)
        entities, web = function("map_application")(application("web"))
        self.assertIn(relation("deployment:web", "cluster:eks-prod-1", "runs_in"), web)
        self.assertIn(entity("cluster", "eks-prod-1"), entities)

    def test_applications_share_service_environment_and_cluster_once(self):
        """SPEC-0035:UT-01 — a lista das Applications da fixture gera a saída esperada, cada chave kind:id uma
        vez só (api-prod e api-staging dividem o serviço; api-prod e ingress-nginx, o ambiente e o cluster)."""
        entities, relations = function("map_applications")(applications())
        keys = [f"{e['kind']}:{e['id']}" for e in entities]
        self.assertEqual(len(keys), len(set(keys)), keys)
        self.assertEqual(comparable({"entities": entities, "relations": relations}), comparable(expected()))

    def test_duplicate_application_name_keeps_the_first(self):
        """SPEC-0035:UT-01 — revisão G4: duas Applications com o mesmo metadata.name em namespaces diferentes: fica
        a primeira (a segunda não gera deployment nem relações) e a saída continua sem chave repetida."""
        first = application("api-prod")
        second = application("api-prod")
        second["metadata"]["namespace"] = "team-a"
        second["metadata"]["labels"] = {"app.kubernetes.io/part-of": "other", "env": "qa"}
        second["spec"]["project"] = "team-a"
        entities, relations = function("map_applications")([first, second])
        keys = [f"{e['kind']}:{e['id']}" for e in entities]
        self.assertEqual(len(keys), len(set(keys)), keys)
        deployments = [e for e in entities if e["kind"] == "deployment"]
        self.assertEqual(len(deployments), 1, deployments)
        self.assertEqual(deployments[0]["attrs"]["project"], "payments")
        self.assertEqual(targets(relations, "deploys"), {"api-prod": "service:api"})
        self.assertEqual(targets(relations, "runs_in", "environment"), {"api-prod": "environment:prod"})
        self.assertNotIn(relation("deployment:api-prod", "environment:qa", "runs_in"), relations)
        self.assertNotIn(relation("deployment:api-prod", "service:other", "deploys"), relations)

    def test_one_thousand_applications_in_less_than_ten_seconds(self):
        """SPEC-0035:UT-01 — requisito de desempenho (seção 5): 1.000 Applications (fixture gerada) mapeadas em
        menos de 10 s depois da resposta da CLI."""
        base = applications()
        apps = []
        for i in range(1000):
            app = copy.deepcopy(base[i % len(base)])
            app["metadata"]["name"] = f"{app['metadata']['name']}-{i:04d}"
            app["spec"]["destination"]["namespace"] = f"ns-{i % 50:02d}"
            apps.append(app)
        start = time.monotonic()
        entities, relations = function("map_applications")(apps)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 10.0)
        self.assertEqual(sum(1 for e in entities if e["kind"] == "deployment"), 1000)
        self.assertEqual(sum(1 for r in relations if r["type"] == "deploys"), 1000)


class ServiceAndEnvironmentTest(unittest.TestCase):
    def test_labels_are_used_when_present(self):
        """SPEC-0035:UT-02 — com os labels padrão (app.kubernetes.io/part-of e env), serviço e ambiente vêm deles."""
        derive = function("service_and_environment")
        self.assertEqual(derive(application("api-prod")), ("api", "prod"))
        self.assertEqual(derive(application("api-staging")), ("api", "staging"))

    def test_without_labels_name_and_destination_namespace_are_used(self):
        """SPEC-0035:UT-02 — sem os labels, o serviço é o nome da Application e o ambiente, o namespace de destino;
        cada um cai no fallback sozinho."""
        derive = function("service_and_environment")
        self.assertEqual(derive(application("web")), ("web", "frontend"))
        self.assertEqual(derive(application("ingress-nginx")), ("ingress-nginx", "prod"))
        bare = application("web")
        del bare["metadata"]["labels"]
        self.assertEqual(derive(bare), ("web", "frontend"))

    def test_configured_label_keys(self):
        """SPEC-0035:UT-02 — --env-label e --service-label trocam as chaves; quem não tem o label configurado
        usa o nome e o namespace."""
        derive = function("service_and_environment")
        web = application("web")
        self.assertEqual(derive(web, env_label="acme.io/stage", service_label="acme.io/component"),
                         ("storefront", "production"))
        self.assertEqual(derive(application("api-prod"), env_label="acme.io/stage",
                                service_label="acme.io/component"), ("api-prod", "payments-prod"))

    def test_mapping_uses_the_derived_service_and_environment(self):
        """SPEC-0035:UT-02 — map_application liga o deployment ao serviço e ao ambiente derivados."""
        _, relations = function("map_application")(application("web"), env_label="acme.io/stage",
                                                    service_label="acme.io/component")
        self.assertIn(relation("deployment:web", "service:storefront", "deploys"), relations)
        self.assertIn(relation("deployment:web", "environment:production", "runs_in"), relations)
        _, relations = function("map_application")(application("web"))
        self.assertIn(relation("deployment:web", "service:web", "deploys"), relations)
        self.assertIn(relation("deployment:web", "environment:frontend", "runs_in"), relations)


class ConfigRefsTest(unittest.TestCase):
    URL = "postgres://user:senha@db.interno:5432/app?ssl=true"
    WANT = ("CACHE_HOST=redis.interno", "DB_URL=db.interno")

    def assert_clean(self, refs):
        text = json.dumps(refs)
        for fragment in ("user", "senha", "5432", "/app", "ssl", "LOG_LEVEL", "debug"):
            self.assertNotIn(fragment, text)

    def test_helm_parameters(self):
        """SPEC-0035:UT-03 — helm.parameters com DB_URL (URL com senha), CACHE_HOST e LOG_LEVEL: saem só
        DB_URL=db.interno e CACHE_HOST=redis.interno."""
        source = {"repoURL": "https://github.com/acme/api.git", "helm": {"parameters": [
            {"name": "DB_URL", "value": self.URL},
            {"name": "CACHE_HOST", "value": "redis.interno"},
            {"name": "LOG_LEVEL", "value": "debug"}]}}
        refs = function("extract_config_refs")(source)
        self.assertEqual(refs, list(self.WANT))
        self.assert_clean(refs)

    def test_helm_values_text(self):
        """SPEC-0035:UT-03 — helm.values (texto YAML, com indentação, aspas e comentário) dá o mesmo resultado."""
        values = ("# configuração\n"
                  "env:\n"
                  f"  DB_URL: \"{self.URL}\"\n"
                  "  CACHE_HOST: 'redis.interno'\n"
                  "  LOG_LEVEL: debug\n")
        refs = function("extract_config_refs")({"helm": {"values": values}})
        self.assertEqual(refs, list(self.WANT))
        self.assert_clean(refs)

    def test_helm_values_object(self):
        """SPEC-0035:UT-03 — helm.valuesObject aninhado dá o mesmo resultado."""
        source = {"helm": {"valuesObject": {"env": {"DB_URL": self.URL, "LOG_LEVEL": "debug"},
                                            "cache": {"CACHE_HOST": "redis.interno"}, "replicaCount": 2}}}
        refs = function("extract_config_refs")(source)
        self.assertEqual(refs, list(self.WANT))
        self.assert_clean(refs)

    def test_plugin_env(self):
        """SPEC-0035:UT-03 — plugin.env ({name, value}) dá o mesmo resultado."""
        source = {"plugin": {"name": "envsubst", "env": [
            {"name": "LOG_LEVEL", "value": "debug"},
            {"name": "DB_URL", "value": self.URL},
            {"name": "CACHE_HOST", "value": "redis.interno"}]}}
        refs = function("extract_config_refs")(source)
        self.assertEqual(refs, list(self.WANT))
        self.assert_clean(refs)

    def test_all_places_together_sorted_without_repetition(self):
        """SPEC-0035:UT-03 — parâmetros (nome com pontos: vale o último segmento), values, valuesObject e plugin
        juntos: lista ordenada, sem repetição, de todos os sufixos padrão."""
        source = {
            "helm": {
                "parameters": [{"name": "env.DB_URL", "value": self.URL},
                               {"name": "image.tag", "value": "1.2.3"}],
                "values": "env:\n  EVENTS_TOPIC: payments.events\n  CACHE_HOST: redis.interno\n",
                "valuesObject": {"env": {"ORDERS_QUEUE": "orders", "CACHE_HOST": "redis.interno"}},
            },
            "plugin": {"env": [{"name": "SENTRY_DSN", "value": "https://fakepublickey@o0.ingest.example.io/42"},
                               {"name": "UPLOADS_BUCKET", "value": "s3://acme-uploads/web/"},
                               {"name": "CACHE_ADDR", "value": "cache.interno:6379"}]},
        }
        refs = function("extract_config_refs")(source)
        self.assertEqual(refs, ["CACHE_ADDR=cache.interno", "CACHE_HOST=redis.interno", "DB_URL=db.interno",
                                "EVENTS_TOPIC=payments.events", "ORDERS_QUEUE=orders",
                                "SENTRY_DSN=o0.ingest.example.io", "UPLOADS_BUCKET=acme-uploads"])
        self.assertNotIn("fakepublickey", json.dumps(refs))

    def test_configured_suffixes(self):
        """SPEC-0035:UT-03 — --ref-suffixes troca a lista: com só _HOST, DB_URL fica de fora."""
        source = {"helm": {"parameters": [{"name": "DB_URL", "value": self.URL},
                                          {"name": "CACHE_HOST", "value": "redis.interno"}]}}
        self.assertEqual(function("extract_config_refs")(source, suffixes=("_HOST",)), ["CACHE_HOST=redis.interno"])

    def test_source_without_values_has_no_refs(self):
        """SPEC-0035:UT-03 — sem helm nem plugin (ou com valor vazio) não há referência."""
        extract = function("extract_config_refs")
        self.assertEqual(extract({"repoURL": "https://github.com/acme/api.git", "path": "k8s"}), [])
        self.assertEqual(extract({"helm": {"parameters": [{"name": "DB_HOST", "value": ""}]}}), [])

    def test_host_of_keeps_only_the_host_or_resource_name(self):
        """SPEC-0035:UT-03 — host_of tira usuário, senha, porta, caminho e query; nome de recurso fica igual."""
        host_of = function("host_of")
        cases = {
            self.URL: "db.interno",
            "redis.interno": "redis.interno",
            "redis://:fake-pass@redis.interno:6379/0": "redis.interno",
            "amqp://admin:fake-pass@mq.interno:5672/%2F?heartbeat=30": "mq.interno",
            "admin:fake-pass@mq.interno:5672": "mq.interno",
            "cache.interno:6379": "cache.interno",
            "https://api.acme.example/v1?debug=1": "api.acme.example",
            "s3://acme-uploads/web/": "acme-uploads",
            "orders-events": "orders-events",
            "payments.events": "payments.events",
        }
        for value, want in cases.items():
            with self.subTest(value=value):
                self.assertEqual(host_of(value), want)


    AMBIGUOUS = (
        # "@" depois do fim da autoridade (no caminho, na query ou no fragmento): pode ser senha, nunca sai
        "postgres://app:Secr3t@Pass/word@db:5432/app",
        "redis://:p@ss/w0rd@cache:6379",
        "postgres://user:ab@cd#ef@db/x",
        "postgres://user:ab@cd?ef@db/x",
        "amqp://u:Tr0ub4dor@3/x@rabbit",
        "app:Secr3t@Pass/word@db:5432",
        "user:ab@cd/ef@db",
        "u:ab@cd#x@db",
        "postgres://u:p#ss@db/x",
        "postgres://u:p?ss@db/x",
        "postgres://u:p#s/s@db/x",
        "postgres://db/app?sslpassword=Hunter2@x/y",
        "postgres://u:pw@db/app?password=s3cr3t@x",
        "https://h/x?token=abc@def",
        "https://h/path@pwd123",
        "https://u:p@h/?redirect=http://evil@leak",
        "https://api.example.com/?email=ana@acme.com",
        "s3://bucket/key@v2",
        "http://h/a?x=1#y@z",
    )
    UNAMBIGUOUS = types.MappingProxyType({
        "postgres://user:senha@db.interno:5432/app?ssl=true": "db.interno",
        "redis://:p@ss@cache:6379": "cache",  # "@" só dentro da autoridade: o host vem depois do último
    })

    def test_at_sign_after_the_authority_gives_no_host(self):
        """SPEC-0035:UT-03 — revisão G4 (rodada 2): sem o esquema, a autoridade vai até o primeiro "/", "?" ou "#";
        com "@" depois desse ponto (caminho, query ou fragmento) o valor é ambíguo e host_of devolve None (perder
        a referência é aceitável; vazar, nunca)."""
        host_of = function("host_of")
        for value in self.AMBIGUOUS:
            with self.subTest(value=value):
                self.assertIsNone(host_of(value))

    def test_at_sign_only_inside_the_authority_gives_the_host_after_the_last_one(self):
        """SPEC-0035:UT-03 — revisão G4 (rodada 2): com "@" só dentro da autoridade, o host é o texto depois do
        último "@" da autoridade, sem porta."""
        host_of = function("host_of")
        for value, want in self.UNAMBIGUOUS.items():
            with self.subTest(value=value):
                self.assertEqual(host_of(value), want)

    def test_host_of_never_returns_a_piece_of_userinfo_path_query_or_fragment(self):
        """SPEC-0035:UT-03 — revisão G4: o resultado é None ou um hostname/IP estrito, e nunca contém um pedaço do
        usuário, da senha, do caminho, da query ou do fragmento."""
        host_of = function("host_of")
        for value in (*self.AMBIGUOUS, *self.UNAMBIGUOUS):
            with self.subTest(value=value):
                host = host_of(value)
                if host is None:
                    continue
                self.assertRegex(host, r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$")
                rest = value.split("://", 1)[-1]
                authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
                outside = rest[len(authority):]
                userinfo = authority.rsplit("@", 1)[0] if "@" in authority else ""
                for piece in re.split(r"[:@/#?=&]", userinfo + "/" + outside):
                    if len(piece) >= 2:
                        self.assertNotIn(piece, host)


class RepositoryRefTest(unittest.TestCase):
    def test_github_https_and_ssh_become_the_same_repository(self):
        """SPEC-0035:UT-04 — https://github.com/acme/api.git e git@github.com:acme/api.git viram
        repository:acme/api (também sem .git, com / no fim, ssh:// e com credencial na URL)."""
        ref = function("repository_ref")
        for url in ("https://github.com/acme/api.git", "git@github.com:acme/api.git", "https://github.com/acme/api",
                    "https://github.com/acme/api/", "ssh://git@github.com/acme/api.git",
                    "https://ci-bot:fake-pass@github.com/acme/api.git"):
            with self.subTest(url=url):
                self.assertEqual(ref(url), "repository:acme/api")

    def test_other_sources_have_no_repository(self):
        """SPEC-0035:UT-04 — repositório de chart Helm, Git de outro host ou repoURL ausente: sem repositório."""
        ref = function("repository_ref")
        for url in ("https://charts.example.com/stable", "https://git.example.com/acme/api.git", "", None):
            with self.subTest(url=url):
                self.assertIsNone(ref(url))

    def test_mapping_adds_sourced_from_only_for_github(self):
        """SPEC-0035:UT-04 — map_application liga o deployment ao repositório (sourced_from) só quando o repoURL
        é do GitHub; o chart Helm não ganha sourced_from."""
        _, staging = function("map_application")(application("api-staging"))
        self.assertIn(relation("deployment:api-staging", "repository:acme/api", "sourced_from"), staging)
        _, web = function("map_application")(application("web"))
        self.assertIn(relation("deployment:web", "repository:acme/web", "sourced_from"), web)
        _, ingress = function("map_application")(application("ingress-nginx"))
        self.assertEqual([r for r in ingress if r["type"] == "sourced_from"], [])


# --------------------------------------------------------------------------- integração


class InputFileTest(ArgocdCase):
    FAILING = BOTH_FAKES

    def test_input_generates_the_expected_output(self):
        """SPEC-0035:IT-01 — --input com as Applications da acme gera a saída esperada, sem chamar CLI nenhuma
        e sem nada que pareça segredo no stdout."""
        data, result = self.collect("--from", "argocd", "--input", ARGOCD_LIST, fakes=self.FAILING,
                                    env={"FAKE_CLI_FAIL": "forbidden"})
        self.assertEqual(self.calls(), [], "com --input nenhuma CLI é chamada")
        self.assert_header(data)
        self.assertEqual(comparable(data), comparable(expected()))
        self.assertTrue(all(e.get("source") == "argocd" for e in data["entities"] + data["relations"]))
        for item in data["entities"]:
            if item["kind"] == "deployment":
                self.assertEqual(set(item["attrs"]), DEPLOYMENT_ATTRS, item)
        self.assert_nothing_secret(result.stdout)

    def test_input_in_the_kubectl_format(self):
        """SPEC-0035:IT-01 — --input com o List do kubectl (com a anotação last-applied-configuration) gera a
        mesma saída."""
        data, result = self.collect("--from", "kubectl", "--input", KUBECTL_LIST, fakes=self.FAILING,
                                    env={"FAKE_CLI_FAIL": "forbidden"})
        self.assertEqual(self.calls(), [], "com --input nenhuma CLI é chamada")
        self.assert_header(data)
        self.assertEqual(comparable(data), comparable(expected()))
        self.assert_nothing_secret(result.stdout)

    def test_label_options(self):
        """SPEC-0035:IT-01 — --env-label e --service-label mudam serviço e ambiente; sem o label, nome e
        namespace."""
        data, _ = self.collect("--from", "argocd", "--input", ARGOCD_LIST, "--env-label", "acme.io/stage",
                               "--service-label", "acme.io/component")
        self.assertEqual(targets(data["relations"], "deploys"), {
            "api-prod": "service:api-prod", "api-staging": "service:api-staging", "web": "service:storefront",
            "ingress-nginx": "service:ingress-nginx"})
        self.assertEqual(targets(data["relations"], "runs_in", "environment"), {
            "api-prod": "environment:payments-prod", "api-staging": "environment:payments-staging",
            "web": "environment:production", "ingress-nginx": "environment:ingress"})
        services = sorted(e["id"] for e in data["entities"] if e["kind"] == "service")
        self.assertEqual(services, ["api-prod", "api-staging", "ingress-nginx", "storefront"])

    def test_ref_suffixes_option(self):
        """SPEC-0035:IT-01 — --ref-suffixes _HOST,_TOPIC: só essas chaves entram em config_refs."""
        data, _ = self.collect("--from", "argocd", "--input", ARGOCD_LIST, "--ref-suffixes", "_HOST,_TOPIC")
        refs = {e["id"]: e["attrs"]["config_refs"] for e in data["entities"] if e["kind"] == "deployment"}
        self.assertEqual(refs, {"api-prod": ["CACHE_HOST=redis-prod.interno", "EVENTS_TOPIC=payments.events"],
                                "api-staging": [], "web": [], "ingress-nginx": []})

    def test_empty_list_gives_an_empty_output(self):
        """SPEC-0035:IT-01 — cluster sem Applications (lista vazia nos dois formatos): saída válida e vazia."""
        for source, text in (("argocd", "[]"), ("kubectl", '{"apiVersion": "v1", "kind": "List", "items": []}')):
            with self.subTest(source=source):
                path = self.tmp / f"empty-{source}.json"
                path.write_text(text, encoding="utf-8")
                data, _ = self.collect("--from", source, "--input", path)
                self.assert_header(data)
                self.assertEqual((data["entities"], data["relations"]), ([], []))

    def test_passwords_with_at_slash_hash_and_query_never_leave_the_collector(self):
        """SPEC-0035:IT-01 — revisão G4 (rodada 2): Application com senhas que têm "@", "/", "#" e "?" em
        helm.parameters e helm.values: exit 0, sem traceback; valor ambíguo ("@" depois da autoridade) não gera
        referência para a chave, e nenhum pedaço das senhas sai no stdout."""
        app = application("ingress-nginx")
        app["metadata"]["name"] = "leaky"
        app["spec"]["source"]["helm"] = {
            "parameters": [{"name": "env.DB_URL", "value": "postgres://app:Secr3t@Pass/word@db:5432/app"},
                           {"name": "env.REPLICA_URL", "value": "postgres://db/app?sslpassword=Hunter2@x/y"}],
            "values": ("env:\n"
                       "  CACHE_URL: \"redis://:s3c#ret@cache:6379/0\"\n"
                       "  BROKER_URL: 'amqp://u:Tr0ub4dor@3/x@rabbit'\n"
                       "  QUEUE_ADDR: u:ab@cd#x@mq\n"
                       "  AUDIT_URL: postgres://u:pw@db/app?password=s3cr3t@x\n"
                       "  DATABASE_URL: postgres://db.interno/app?user=app&password=Pa55@word\n"
                       "  REDIS_URL: redis://:p@ss@cache:6379\n"),
        }
        app["status"]["sync"]["comparedTo"]["source"] = copy.deepcopy(app["spec"]["source"])
        app["status"]["history"][0]["source"] = copy.deepcopy(app["spec"]["source"])
        path = self.tmp / "leaky.json"
        path.write_text(json.dumps([app]), encoding="utf-8")
        data, result = self.collect("--from", "argocd", "--input", path)
        refs = next(e["attrs"]["config_refs"] for e in data["entities"] if e["kind"] == "deployment")
        self.assertEqual(refs, ["REDIS_URL=cache"])
        for fragment in ("Secr3t", "Pass", "word", "Pa55", "Hunter2", "s3cr3t", "s3c#ret", "s3c", "Tr0ub4dor",
                         "3/x", "ab@cd", "cd#x", "p@ss", "password", "5432", "6379", "DB_URL", "DATABASE_URL",
                         "CACHE_URL", "BROKER_URL", "QUEUE_ADDR", "AUDIT_URL", "REPLICA_URL"):
            with self.subTest(never_out=fragment):
                self.assertNotIn(fragment, result.stdout)

    def test_duplicate_application_name_warns_on_stderr(self):
        """SPEC-0035:UT-01 — revisão G4: pela CLI, Application repetida (mesmo nome, outro namespace): exit 0, a
        primeira fica e um aviso com o nome vai para o stderr."""
        first = application("web")
        second = application("web")
        second["metadata"]["namespace"] = "team-b"
        second["spec"]["project"] = "team-b"
        path = self.tmp / "duplicate.json"
        path.write_text(json.dumps([first, second]), encoding="utf-8")
        data, result = self.collect("--from", "argocd", "--input", path)
        self.assertIn("web", result.stderr)
        deployments = [e for e in data["entities"] if e["kind"] == "deployment"]
        self.assertEqual([d["id"] for d in deployments], ["web"])
        self.assertEqual(deployments[0]["attrs"]["project"], "frontend")
        _, violations, dropped = fn("validate_collector_output", "SPEC-0033")(data)
        self.assertEqual((violations, dropped), ([], []))

    def test_missing_input_file_exits_1(self):
        """SPEC-0035:IT-01 — --input com arquivo que não existe: exit 1, sem traceback e sem saída do contrato."""
        result = self.run_argocd("--from", "argocd", "--input", self.tmp / "nope.json")
        self.assertEqual(result.returncode, 1, output(result))
        self.assertFalse(result.stdout.strip().startswith(("{", "[")), "nada de saída do contrato numa falha")


class FakeCliTest(ArgocdCase):
    BOTH = BOTH_FAKES

    def test_argocd_on_path_gives_the_same_output_as_input(self):
        """SPEC-0035:IT-02 — --from argocd com o argocd falso no PATH: mesma saída do --input, por
        `argocd app list -o json`, sem chamar o kubectl."""
        via_input, _ = self.collect("--from", "argocd", "--input", ARGOCD_LIST)
        via_cli, result = self.collect("--from", "argocd", fakes=self.BOTH)
        self.assert_header(via_cli)
        self.assertEqual(comparable(via_cli), comparable(via_input))
        self.assertEqual(comparable(via_cli), comparable(expected()))
        calls = self.calls("argocd")
        self.assertTrue(any(c[:2] == ["app", "list"] and json_output(c) for c in calls), calls)
        self.assertFalse(any(word in c for c in calls for word in ("manifests", "resources", "get")), calls)
        self.assertEqual(self.calls("kubectl"), [], "--from argocd não chama o kubectl")
        self.assert_nothing_secret(result.stdout)

    def test_kubectl_on_path_gives_the_same_output_as_input(self):
        """SPEC-0035:IT-02 — --from kubectl com o kubectl falso no PATH: mesma saída do --input, por
        `kubectl get applications.argoproj.io -A -o json`, sem Secrets e sem chamar o argocd."""
        via_input, _ = self.collect("--from", "kubectl", "--input", KUBECTL_LIST)
        via_cli, result = self.collect("--from", "kubectl", fakes=self.BOTH)
        self.assert_header(via_cli)
        self.assertEqual(comparable(via_cli), comparable(via_input))
        self.assertEqual(comparable(via_cli), comparable(expected()))
        calls = self.calls("kubectl")
        self.assertTrue(any(c[:1] == ["get"] and "applications.argoproj.io" in c and json_output(c)
                            and ("-A" in c or "--all-namespaces" in c) for c in calls), calls)
        self.assertFalse(any("secret" in arg.lower() for c in calls for arg in c), calls)
        self.assertEqual(self.calls("argocd"), [], "--from kubectl não chama o argocd")
        self.assert_nothing_secret(result.stdout)

    def test_both_clis_give_the_same_output(self):
        """SPEC-0035:IT-02 — argocd e kubectl falsos sobre o mesmo cluster dão a mesma saída."""
        via_argocd, _ = self.collect("--from", "argocd", fakes=self.BOTH)
        via_kubectl, _ = self.collect("--from", "kubectl", fakes=self.BOTH)
        self.assertEqual(comparable(via_argocd), comparable(via_kubectl))


class CliFailureTest(ArgocdCase):
    BOTH = BOTH_FAKES

    def test_cli_without_access_exits_1(self):
        """SPEC-0035:IT-03 — CLI falsa falhando o acesso (sessão inválida ou RBAC negando): exit 1 "sem acesso às
        Applications"."""
        for cli in ("argocd", "kubectl"):
            for mode in ("unauthenticated", "forbidden"):
                with self.subTest(cli=cli, mode=mode):
                    result = self.run_argocd("--from", cli, fakes=self.BOTH, env={"FAKE_CLI_FAIL": mode})
                    self.assert_failure(result, NO_ACCESS)

    def test_cli_not_installed_exits_1(self):
        """SPEC-0035:IT-03 — CLI fora do PATH: exit 1 "<cli> não encontrado — veja references/collectors/argocd.md",
        também quando só a outra CLI existe (sem trocar de CLI por conta própria)."""
        empty = self.tmp / "empty-bin"
        empty.mkdir()
        for cli, other, fake in (("argocd", "kubectl", FAKE_KUBECTL), ("kubectl", "argocd", FAKE_ARGOCD)):
            with self.subTest(cli=cli, path="vazio"):
                result = self.run_argocd("--from", cli, path=empty)
                self.assert_failure(result, f"{cli} não encontrado — {GUIDE}")
            with self.subTest(cli=cli, path=f"só {other}"):
                only_other = make_bin(**{other: fake})
                self.addCleanup(shutil.rmtree, only_other, True)
                result = self.run_argocd("--from", cli, path=only_other)
                self.assert_failure(result, f"{cli} não encontrado — {GUIDE}")
                self.assertEqual(self.calls(other), [], f"--from {cli} não chama o {other}")

    def test_argocd_without_server_configured_exits_1_with_no_access(self):
        """SPEC-0035:IT-03 — revisão G4: argocd sem contexto/servidor ("Argo CD server address unspecified"): exit 1
        com "sem acesso às Applications" (e o guia)."""
        result = self.run_argocd("--from", "argocd", fakes=self.BOTH, env={"FAKE_CLI_FAIL": "unconfigured"})
        self.assert_failure(result, NO_ACCESS)
        self.assertIn("references/collectors/argocd.md", output(result))

    def test_invalid_cli_response_exits_1(self):
        """SPEC-0035:IT-03 — CLI que responde algo que não é JSON, ou JSON que não é lista de Applications:
        exit 1 "resposta inválida da CLI"."""
        for cli in ("argocd", "kubectl"):
            for mode in ("garbage", "shape"):
                with self.subTest(cli=cli, mode=mode):
                    result = self.run_argocd("--from", cli, fakes=self.BOTH, env={"FAKE_CLI_FAIL": mode})
                    self.assert_failure(result, INVALID)


# --------------------------------------------------------------------------- contrato


def atlas_config(collectors):
    lines = ["version: 1", "organization: Acme", "mode: local", "language: auto", "stale_days: 14",
             "categories: [delivery]", "collectors:"]
    for cid, category, command in collectors:
        lines += [f"  - id: {cid}", f"    category: {category}",
                  "    command: [" + ", ".join(json.dumps(a) for a in command) + "]", "    timeout: 60"]
    lines.append("redaction: {extra_patterns: []}")
    return "\n".join(lines) + "\n"


class ArgocdContractTest(ArgocdCase):
    def test_argocd_output_passes_the_collector_contract(self):
        """SPEC-0035:CT-01 — saída de argocd.py (fixtures, pelo --input e pelas CLIs falsas) passa no
        validate_collector_output da SPEC-0033@1, sem violação e sem nada descartado."""
        validate = fn("validate_collector_output", "SPEC-0033")
        runs = (("--input argocd", ("--from", "argocd", "--input", ARGOCD_LIST), None),
                ("--input kubectl", ("--from", "kubectl", "--input", KUBECTL_LIST), None),
                ("argocd falso", ("--from", "argocd"), {"argocd": FAKE_ARGOCD}),
                ("kubectl falso", ("--from", "kubectl"), {"kubectl": FAKE_KUBECTL}))
        for name, args, fakes in runs:
            with self.subTest(name):
                data, _ = self.collect(*args, fakes=fakes)
                _, violations, dropped = validate(data)
                self.assertEqual(violations, [])
                self.assertEqual(dropped, [])

    def test_scan_with_the_collector_declared_ends_ok(self):
        """SPEC-0035:CT-01 — scan de um atlas com o coletor argocd declarado ({skill}) termina com OK, sem nada
        descartado nem mascarado (a higiene das URLs já vem do coletor)."""
        sandbox = Sandbox()
        self.addCleanup(sandbox.cleanup)
        out = sandbox.init(mode="local")
        self.assertEqual(out.returncode, 0, output(out))
        config = atlas_config([
            ("argocd", "delivery", ["python3", "{skill}/assets/collectors/argocd.py", "--from", "argocd",
                                    "--input", "{skill}/tests/fixtures/argocd/acme/argocd-app-list.json"]),
        ])
        (sandbox.atlas / "atlas-config.yml").write_text(config, encoding="utf-8")
        result = sandbox.run("scan")
        text = output(result)
        self.assertEqual(result.returncode, 0, text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("FALHA", text)
        self.assertNotIn("descartad", text, "nada fora do contrato nem chave proibida")
        self.assertNotIn("mascarad", text, "nenhum valor que pareça segredo chega ao scan")
        self.assertRegex(text, re.compile(r"^OK argocd — ", re.MULTILINE))
        state = json.loads((sandbox.atlas / "snapshots" / "_scan.json").read_text(encoding="utf-8"))
        full = expected()
        self.assertEqual(state["argocd"]["status"], "ok")
        self.assertEqual(state["argocd"]["entities"], len(full["entities"]))
        self.assertEqual(state["argocd"]["relations"], len(full["relations"]))
        snapshot = (sandbox.atlas / "snapshots" / "argocd.json").read_text(encoding="utf-8")
        self.assert_nothing_secret(snapshot)


if __name__ == "__main__":
    unittest.main()
