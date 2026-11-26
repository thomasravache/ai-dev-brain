"""probe@2: recursos do grafo como alvo, mudança e jornadas como entrada, e acesso local à nuvem, ao banco e à URL
base (SPEC-0096: CH-01, UT-01 a UT-10, IT-01, IT-02 e CT-01; ADR-0025, ADR-0023, ADR-0010).

Contrato (seção 6 da SPEC-0096) que estes testes fixam:

    config.yml (local): access: {clusters, cloud: {<amb>: {profile}}, databases: {<datastore>: {user, database,
        passfile}}, urls: {<amb>: {base_url}}}; inválido -> config/context/lint exit 2 "access.<bloco>: item N
        inválido — <motivo>", doctor ERRO "acesso local"; config mostra só "definido".
    doctor: "acesso nuvem <amb>", "acesso url <amb>", "acesso banco <id>" (OK/AVISO/ERRO), o passfile só por stat.
    context: delivery.deployments[].cloud_access e service.database_access, só com as chaves locais.
    atlas.py probe <c> <v> --service <id> --env <amb> [--resource <kind:id>] [--commit <sha>] ...
        recurso pelo linked_resources(graph, service, env) (aresta do deployment, config_refs, dlq); exit 2 sem rodar
        nada quando o recurso é inválido, inexistente, não ligado ou com atributo fora da regra; probe@2 recebe só os
        blocos que declara (cluster, cloud, database, urls; change, journeys); PGPASSFILE só com database; exit 4
        "sem acesso local: <tipo>"; máscara do profile, usuário, banco, passfile, URL base e id de conta de nuvem;
        probes.log com resource e commit só quando usados.
    validate_probe_describe|input|output aceitam probe@1 e probe@2 ("contract precisa ser probe@1 ou probe@2").

Leituras desta suíte (listadas no relatório do test-writer):
    - "datastore das dependências do serviço" (UT-03) = os datastores das arestas de dependência do próprio serviço
      (como o `context` lista as dependências); billing-db, ligado só ao deployment de prod, fica de fora.
    - Na máscara (UT-08) a capacidade declara cloud, database e urls, para que todos os literais de acesso sejam
      conhecidos do núcleo; o adaptador ecoa os valores (o roteiro traz os textos).
    - CH-01 aqui confere a forma probe@1 na fixture desta spec; os goldens existentes de config, doctor e context
      são conferidos pelos CH-01 da SPEC-0087 (test_access_map) e da SPEC-0088 (test_probe), que continuam na suíte.
    - "o doctor nunca abre o arquivo" (UT-02) roda o doctor no processo do teste com open, io.open e os.open
      observados.

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); sem rede, sem AWS CLI, sem psql,
sem kubectl (os adaptadores são os scripts falsos de fixtures/fake-probes/); nomes genéricos (acme, api, example.test)
e a conta de exemplo 123456789012.
"""
import builtins
import contextlib
import copy
import io
import json
import os
import re
import shutil
import socket
import sys
import unittest
import urllib.parse
from unittest import mock

from helpers import SKILL, TESTS, Sandbox, atlas, doctor_lines, fn, output
from test_probe import adapter_yaml, probes_yaml

SPEC = "SPEC-0096"
FAKES = TESTS / "fixtures" / "fake-probes"
FIXTURE = TESTS / "fixtures" / "probe-resource" / "atlas"
PROBES_DOC = SKILL / "references" / "probes.md"

# sentinelas de acesso (nunca saem em nada)
PROFILE = "acme-dev-read"
DB_USER = "ro_user"
DB_NAME = "ordersdb"
BASE_URL = "https://api.dev.example.test"
CONTEXT = "ctx-local-dev-0096"
ACCOUNT = "123456789012"
PASSFILE_NAME = ".pgpass-0096"

LOG_KEYS = {"at", "atlas", "service", "environment", "capability", "verb", "adapter", "status", "exit",
            "confirmed_production"}
PROBE1_TARGET_KEYS = {"service", "environment", "deployment", "clusters", "context", "namespace", "workloads"}
CLUSTER_FIELDS = {"clusters", "context", "namespace", "workloads"}
BASE_TARGET = {"service", "environment", "deployment"}
ALL_VERBS = ("queue", "subscriptions", "migrations", "trace", "run", "status")
CAPS = {
    "messaging": {"verbs": ["queue", "subscriptions"], "targets": ["queue", "topic"], "access": ["cloud"]},
    "database": {"verbs": ["migrations"], "targets": ["datastore"], "access": ["database"]},
    "delivery": {"verbs": ["trace"], "targets": ["deployment"], "access": [], "inputs": ["change"]},
    "functional": {"verbs": ["run"], "targets": ["deployment"], "access": ["urls"], "inputs": ["journeys"]},
}
# SPEC-0103:UT-04 — a saída de functional: um item por jornada curada de api (checkout, login), chaves fechadas
FUNCTIONAL_ITEMS = [{"journey": j, "result": "passed", "duration_seconds": 0.5, "failed_steps": []}
                    for j in ("checkout", "login")]
ORDERS_ATTRS = {"region": "us-east-1", "dlq": "orders-dlq", "fifo": False, "retention_days": 4}
ARN = f"arn:aws:sqs:us-east-1:{ACCOUNT}:orders"
QUEUE_URL = f"https://sqs.us-east-1.amazonaws.com/{ACCOUNT}/orders"
ARN_MASKED = "arn:aws:sqs:us-east-1:[REDACTED]:orders"
QUEUE_URL_MASKED = "https://sqs.us-east-1.amazonaws.com/[REDACTED]/orders"


def f(name):
    return fn(name, SPEC)


def fixture_graph():
    return json.loads((FIXTURE / "graph.json").read_text(encoding="utf-8"))


def access_text(access):
    """access: {<bloco>: {<nome>: {<chave>: <valor>} | <YAML cru>}} em YAML (valores entre aspas duplas, JSON)."""
    if not access:
        return ""
    lines = ["access:"]
    for block, items in access.items():
        lines.append(f"  {block}:")
        for name, value in items.items():
            if isinstance(value, dict):
                inner = ", ".join(f"{key}: {json.dumps(item)}" for key, item in value.items())
                lines.append(f"    {json.dumps(name)}: {{{inner}}}")
            else:
                lines.append(f"    {json.dumps(name)}: {value}")
    return "\n".join(lines) + "\n"


def lowered(*texts):
    return "\n".join(texts).lower()


class ResourceCase(unittest.TestCase):
    """Um atlas temporário por teste (cópia de fixtures/probe-resource/atlas), um passfile 0600 e o registro de
    processos dos adaptadores falsos."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        shutil.copytree(FIXTURE, self.box.atlas)
        self.record = self.box.root / "calls.jsonl"
        self.record1 = self.box.root / "calls-probe1.jsonl"
        self.scenario = self.box.root / "scenario.json"
        self.write_scenario({"*": {"items": [{"name": "ok"}]}})
        secrets = self.box.root / "secrets"
        secrets.mkdir()
        self.passfile = secrets / PASSFILE_NAME
        self.passfile.write_text("*:*:ordersdb:ro_user:senha-falsa-0096\n", encoding="utf-8")
        os.chmod(self.passfile, 0o600)

    # ------------------------------------------------------------------ montagem

    def access(self, clusters=True, cloud=True, databases=True, urls=True, passfile=None):
        data = {}
        if clusters:
            data["clusters"] = {"cluster-dev": {"context": CONTEXT}}
        if cloud:
            data["cloud"] = {"dev": {"profile": PROFILE}}
        if databases:
            data["databases"] = {"orders-db": {"user": DB_USER, "database": DB_NAME,
                                               "passfile": str(passfile or self.passfile)}}
        if urls:
            data["urls"] = {"dev": {"base_url": BASE_URL}}
        return data

    def adapter2(self, caps=None, aid="fake2", verbs=ALL_VERBS, credentials=(), contract="probe@2"):
        describe = self.box.root / "describe" / f"{aid}.json"
        describe.parent.mkdir(exist_ok=True)
        describe.write_text(json.dumps({"contract": contract, "adapter": aid,
                                        "capabilities": CAPS if caps is None else caps}), encoding="utf-8")
        command = [sys.executable, str(FAKES / "probe2.py"), "--record", str(self.record), "--describe-file",
                   str(describe), "--scenario", str(self.scenario), "--adapter", aid]
        return adapter_yaml(aid, command, verbs=verbs, timeout=10, credentials=credentials)

    def adapter1(self, described="messaging=queue", verbs=ALL_VERBS, aid="v1"):
        command = [sys.executable, str(FAKES / "ok.py"), "--record", str(self.record1), "--adapter", aid, "--verbs",
                   described]
        return adapter_yaml(aid, command, verbs=verbs, timeout=10)

    def configure(self, adapters=None, access=None, credentials="{}", raw_access=None):
        """Configuração local: o atlas, o acesso (padrão: todos os blocos) e as probes ligadas com `adapters`
        (padrão: o probe@2 com CAPS)."""
        access = self.access() if access is None else access
        text = f"atlas: {json.dumps(str(self.box.atlas))}\ncredentials: {credentials}\n"
        text += raw_access if raw_access is not None else access_text(access)
        if adapters is None:
            adapters = [self.adapter2()]
        if adapters:
            text += probes_yaml(list(adapters))
        self.box.write_local(text)

    def write_scenario(self, scenario):
        self.scenario.write_text(json.dumps(scenario), encoding="utf-8")

    def graph(self):
        return json.loads((self.box.atlas / "graph.json").read_text(encoding="utf-8"))

    def save_graph(self, graph):
        (self.box.atlas / "graph.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")

    def set_attrs(self, key, **attrs):
        graph = self.graph()
        node = next(n for n in graph["nodes"] if n["key"] == key)
        node["attrs"].update(attrs)
        self.save_graph(graph)

    # ------------------------------------------------------------------ execução

    def probe(self, capability, verb, *extra, service="api", env="dev", environ=None):
        result = self.box.run("probe", capability, verb, "--service", service, "--env", env, *extra, env=environ)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def calls(self, mode=None, record=None):
        path = record or self.record
        if not path.exists():
            return []
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [r for r in rows if mode is None or r["mode"] == mode]

    def reset_calls(self):
        for path in (self.record, self.record1):
            if path.exists():
                path.unlink()

    def received(self):
        runs = self.calls("run")
        self.assertEqual(len(runs), 1, runs)
        return runs[0]

    def log(self):
        path = self.box.config_home / "probes.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def log_text(self):
        path = self.box.config_home / "probes.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def assertExit(self, result, code):
        self.assertEqual(result.returncode, code, output(result))

    def assertInvalid(self, result, text):
        """exit 2 do próprio subcomando probe (não do argparse) com `text` no motivo."""
        self.assertExit(result, 2)
        self.assertNotIn("unrecognized arguments", output(result))
        self.assertNotIn("invalid choice", output(result))
        self.assertIn(text, output(result))

    def assertNothingRan(self):
        self.assertEqual(self.calls(), [], "um processo do adaptador rodou (nem o --describe pode)")
        self.assertEqual(self.calls(record=self.record1), [], "um processo do adaptador rodou")

    def assertNoAccessValue(self, *texts, extra=()):
        text = lowered(*texts)
        for secret in (PROFILE, DB_USER, DB_NAME, BASE_URL, CONTEXT, str(self.passfile), *extra):
            self.assertNotIn(secret.lower(), text, f"valor de acesso apareceu: {secret}")


# --------------------------------------------------------------------------- CH-01


class CharacterizationTest(ResourceCase):
    def test_probe1_without_new_keys_keeps_input_output_messages_and_log(self):
        """SPEC-0096:CH-01 — atlas e configuração sem access.cloud nem access.databases, adaptador probe@1 de hoje:
        `probe runtime status` entrega a entrada probe@1 de sempre (exatamente as chaves de target de hoje, sem
        resource), a saída probe@1, a linha do probes.log com exatamente as chaves de hoje (sem resource nem commit) e,
        sem access.clusters, a mensagem "sem acesso local ao cluster cluster-dev (access.clusters)"."""
        # SPEC-0096:CH-01
        self.configure([self.adapter1(described="runtime=status,events,logs")],
                       access={"clusters": {"cluster-dev": {"context": CONTEXT}}})
        result = self.probe("runtime", "status", "--json")
        self.assertExit(result, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["contract"], "probe@1")
        runs = self.calls("run", record=self.record1)
        self.assertEqual(len(runs), 1, runs)
        sent = runs[0]["input"]
        self.assertEqual(sent["contract"], "probe@1")
        self.assertEqual(set(sent), {"contract", "capability", "verb", "target", "limits"})
        self.assertEqual(sent["target"], {"service": "api", "environment": "dev", "deployment": "dev-api",
                                          "clusters": ["cluster-dev"], "context": CONTEXT, "namespace": "api-dev",
                                          "workloads": ["Deployment/api"]})
        self.assertEqual(set(self.log()[-1]), LOG_KEYS)
        self.assertNotIn(CONTEXT, output(result) + self.log_text())
        self.configure([self.adapter1(described="runtime=status,events,logs")], access={})
        result = self.probe("runtime", "status")
        self.assertExit(result, 4)
        self.assertIn("sem acesso local ao cluster cluster-dev (access.clusters)", output(result))
        # SPEC-0104:UT-06 — reason e access na recusa por acesso
        self.assertEqual(set(self.log()[-1]), LOG_KEYS | {"reason", "access"})

    def test_config_doctor_and_context_without_new_keys_show_only_todays_access(self):
        """SPEC-0096:CH-01 — só access.clusters: config --json mostra só o bloco clusters (definido); o doctor não tem
        linha de acesso à nuvem, ao banco nem à URL; o context não traz cloud_access nem database_access."""
        # SPEC-0096:CH-01
        self.configure([], access={"clusters": {"cluster-dev": {"context": CONTEXT}}})
        result = self.box.run("config", "--json")
        self.assertExit(result, 0)
        self.assertEqual(find_key(json.loads(result.stdout), "access"),
                         {"clusters": {"cluster-dev": {"context": "definido"}}})
        doctor = self.box.run("doctor")
        rows = doctor_lines(doctor.stdout)
        self.assertIn(("OK", "acesso cluster-dev", "contexto definido"), rows, doctor.stdout)
        self.assertFalse([r for r in rows if re.match(r"acesso (nuvem|banco|url) ", r[1])], doctor.stdout)
        package = self.box.run("context", "--json", "api")
        self.assertExit(package, 0)
        data = json.loads(package.stdout)
        self.assertIsNone(find_key(data, "cloud_access"))
        self.assertIsNone(find_key(data, "database_access"))
        self.assertNotIn("sem acesso local à nuvem", self.box.run("context", "api").stdout)


def find_key(data, key):
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = find_key(value, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = find_key(value, key)
            if found is not None:
                return found
    return None


# --------------------------------------------------------------------------- UT-01


class AccessConfigTest(ResourceCase):
    def test_valid_cloud_databases_and_urls_show_only_defined(self):
        """SPEC-0096:UT-01 — access.cloud, access.databases (passfile ~/...) e access.urls válidos: config e config
        --json mostram profile, user, database, passfile e base_url como "definido"; nenhum valor aparece."""
        # SPEC-0096:UT-01
        access = {"cloud": {"dev": {"profile": PROFILE}},
                  "databases": {"orders-db": {"user": DB_USER, "database": DB_NAME, "passfile": "~/x/.pgpass"}},
                  "urls": {"dev": {"base_url": BASE_URL}}}
        self.configure([], access=access)
        result = self.box.run("config", "--json")
        self.assertExit(result, 0)
        self.assertEqual(find_key(json.loads(result.stdout), "access"), {
            "cloud": {"dev": {"profile": "definido"}},
            "databases": {"orders-db": {"user": "definido", "database": "definido", "passfile": "definido"}},
            "urls": {"dev": {"base_url": "definido"}}})
        text = self.box.run("config")
        self.assertExit(text, 0)
        self.assertIn("definido", text.stdout)
        for shown in (result, text):
            self.assertNoAccessValue(output(shown), extra=("~/x/.pgpass", "x/.pgpass"))

    def invalid_cases(self):
        full = {"user": DB_USER, "database": DB_NAME, "passfile": str(self.passfile)}
        return [  # (caso, access, regex esperada, textos que não podem sair)
            ("chave desconhecida em access", {"cloud": {"dev": {"profile": PROFILE}}, "vpnzz": {"x": {"y": "z"}}},
             r"access", ("vpnzz",)),
            ("chave desconhecida em cloud.<amb>", {"cloud": {"dev": {"profile": PROFILE, "zzextra": "v"}}},
             r"access\.cloud: item 1 inválido — o mapa aceita só", ("zzextra",)),
            ("chave desconhecida em databases.<id>", {"databases": {"orders-db": dict(full, zzextra="v")}},
             r"access\.databases: item 1 inválido — o mapa aceita só", ("zzextra",)),
            ("falta passfile", {"databases": {"orders-db": full,
                                              "payments-db": {"user": DB_USER, "database": DB_NAME}}},
             r"access\.databases: item 2 inválido — falta passfile", ()),
            ("profile vazio", {"cloud": {"dev": {"profile": ""}}},
             r"access\.cloud: item 1 inválido — o profile vazio", ()),
            ("profile com quebra de linha", {"cloud": {"dev": {"profile": "acme\nzzlinha"}}},
             r"access\.cloud: item 1 inválido — o profile com quebra de linha ou caractere de controle",
             ("zzlinha",)),
            ("profile longo", {"cloud": {"dev": {"profile": "p" * 300}}},
             r"access\.cloud: item 1 inválido — o profile com mais de 256 caracteres", ("p" * 300,)),
            ("profile começa com -", {"cloud": {"dev": {"profile": "-zzopt"}}},
             r"access\.cloud: item 1 inválido — o profile começa com -", ("zzopt",)),
            ("passfile relativo", {"databases": {"orders-db": dict(full, passfile="x/zz.pgpass")}},
             r"access\.databases: item 1 inválido — o arquivo de senhas precisa ser absoluto ou começar com ~/",
             ("zz.pgpass",)),
            ("ambiente fora da regra", {"cloud": {"zz env": {"profile": PROFILE}}},
             r"access\.cloud: item 1 inválido — o nome do ambiente fora da regra de nome", ("zz env",)),
            ("URL base relativa", {"urls": {"dev": {"base_url": "/zzpath"}}},
             r"access\.urls: item 1 inválido — a URL base precisa ser http ou https absoluta", ("zzpath",)),
            ("URL base ftp", {"urls": {"dev": {"base_url": "ftp://zzhost.example.test"}}},
             r"access\.urls: item 1 inválido — a URL base precisa ser http ou https absoluta", ("zzhost",)),
            ("URL base com usuário e senha", {"urls": {"dev": {"base_url": "https://zzuser:zzpass@api.example.test"}}},
             r"access\.urls: item 1 inválido — a URL base com usuário ou senha", ("zzuser", "zzpass")),
            ("URL base com espaço", {"urls": {"dev": {"base_url": "https://api.example.test/zz caminho"}}},
             r"access\.urls: item 1 inválido — \S", ("zz caminho",)),
        ]

    def test_invalid_access_exits_2_with_position_and_reason_only(self):
        """SPEC-0096:UT-01 — chave desconhecida (em access, em cloud.<amb> e em databases.<id>), falta passfile,
        profile vazio, com quebra de linha, com mais de 256 ou começando com -, passfile relativo, ambiente fora da
        regra, URL base relativa, ftp, com usuário:senha@ ou com espaço: config --json sai com 2, "access.<bloco>: item
        N inválido — <motivo>", sem a chave nem o valor."""
        # SPEC-0096:UT-01
        for name, access, pattern, forbidden in self.invalid_cases():
            with self.subTest(case=name):
                self.configure([], access=access)
                result = self.box.run("config", "--json")
                self.assertNotIn("Traceback", output(result))
                self.assertExit(result, 2)
                self.assertRegex(output(result), pattern)
                for text in forbidden + (PROFILE, DB_USER, DB_NAME, str(self.passfile)):
                    self.assertNotIn(text, output(result))

    def test_invalid_access_fails_config_context_lint_and_doctor(self):
        """SPEC-0096:UT-01 — access.urls com usuário e senha: config, context e lint saem com 2; o doctor mostra ERRO
        "acesso local" e sai com 1; nenhum valor aparece."""
        # SPEC-0096:UT-01
        self.configure([], access={"cloud": {"dev": {"profile": PROFILE}},
                                   "urls": {"dev": {"base_url": "https://zzuser:zzpass@api.example.test"}}})
        for command in (("config",), ("context", "api"), ("lint",)):
            with self.subTest(command=command[0]):
                result = self.box.run(*command)
                self.assertNotIn("Traceback", output(result))
                self.assertExit(result, 2)
                self.assertRegex(output(result), r"access\.urls: item 1 inválido — a URL base com usuário ou senha")
                self.assertNotIn("zzpass", output(result))
        doctor = self.box.run("doctor")
        self.assertExit(doctor, 1)
        self.assertTrue([r for r in doctor_lines(doctor.stdout) if r[0] == "ERRO" and r[1] == "acesso local"],
                        doctor.stdout)
        self.assertNotIn("zzpass", output(doctor))
        self.assertNoAccessValue(output(doctor))


# --------------------------------------------------------------------------- UT-02


class DoctorAccessTest(ResourceCase):
    def doctor_rows(self, access):
        self.configure([], access=access)
        result = self.box.run("doctor")
        self.assertNotIn("Traceback", output(result))
        return result, doctor_lines(result.stdout)

    def bank_row(self, rows, did="orders-db"):
        found = [r for r in rows if r[1] == f"acesso banco {did}"]
        self.assertEqual(len(found), 1, rows)
        return found[0]

    @unittest.skipIf(os.name == "nt", "permissão do arquivo não é conferida no Windows")
    def test_passfile_permissions_and_absence(self):
        """SPEC-0096:UT-02 — passfile 0600, 0400, 0644 e inexistente: OK com permissão 0600, OK, ERRO "arquivo de
        senhas acessível por outros usuários" e ERRO "arquivo de senhas não encontrado", sem o caminho."""
        # SPEC-0096:UT-02
        missing = self.box.root / "secrets" / "nao-existe.pgpass"
        cases = ((0o600, self.passfile, "OK", "permissão 0600"), (0o400, self.passfile, "OK", None),
                 (0o644, self.passfile, "ERRO", "arquivo de senhas acessível por outros usuários"),
                 (None, missing, "ERRO", "arquivo de senhas não encontrado"))
        for mode, path, status, detail in cases:
            with self.subTest(mode=mode):
                if mode is not None:
                    os.chmod(path, mode)
                access = {"databases": {"orders-db": {"user": DB_USER, "database": DB_NAME, "passfile": str(path)}}}
                result, rows = self.doctor_rows(access)
                row = self.bank_row(rows)
                self.assertEqual(row[0], status, result.stdout)
                if detail:
                    self.assertIn(detail, row[2])
                if status == "OK":
                    self.assertIn("usuário, banco e arquivo de senhas definidos", row[2])
                self.assertNotIn(str(path), output(result))
                self.assertNoAccessValue(output(result), extra=(str(missing),))
        os.chmod(self.passfile, 0o600)

    def test_doctor_never_opens_the_passfile(self):
        """SPEC-0096:UT-02 — o doctor (rodado no processo do teste) confere o passfile só com stat: open, io.open e
        os.open nunca recebem o caminho do arquivo de senhas."""
        # SPEC-0096:UT-02
        self.configure([], access={"databases": {"orders-db": {"user": DB_USER, "database": DB_NAME,
                                                               "passfile": str(self.passfile)}}})
        module = atlas()
        opened = []
        real_open, real_os_open = builtins.open, os.open

        def spy(file, *args, **kwargs):
            opened.append(os.fspath(file) if isinstance(file, (str, bytes, os.PathLike)) else repr(file))
            return real_open(file, *args, **kwargs)

        def os_spy(path, *args, **kwargs):
            opened.append(os.fspath(path))
            return real_os_open(path, *args, **kwargs)

        environ = {"HOME": str(self.box.home), "XDG_CONFIG_HOME": str(self.box.home / ".config"),
                   "ATLAS_CONFIG_HOME": str(self.box.config_home)}
        out = io.StringIO()
        with mock.patch.dict(os.environ, environ), mock.patch("builtins.open", spy), \
                mock.patch("io.open", spy), mock.patch("os.open", os_spy), contextlib.redirect_stdout(out):
            module.cmd_doctor(False)
        rows = doctor_lines(out.getvalue())
        self.assertTrue([r for r in rows if r[1] == "acesso banco orders-db"], out.getvalue())
        self.assertFalse([p for p in opened if str(self.passfile) in str(p) or PASSFILE_NAME in str(p)], opened)

    def test_datastore_cloud_and_url_rows(self):
        """SPEC-0096:UT-02 — databases.<id> sem datastore no grafo: AVISO; cloud.dev (no grafo): OK "profile
        definido" e cloud.staging (fora): AVISO; urls.dev: OK "URL base definida" e urls.staging: AVISO; nenhuma linha
        traz a URL, o profile, o usuário nem o banco."""
        # SPEC-0096:UT-02
        access = {"cloud": {"dev": {"profile": PROFILE}, "staging": {"profile": "acme-stg-read"}},
                  "databases": {"ghost-db": {"user": DB_USER, "database": DB_NAME, "passfile": str(self.passfile)}},
                  "urls": {"dev": {"base_url": BASE_URL}, "staging": {"base_url": "https://stg.example.test"}}}
        result, rows = self.doctor_rows(access)
        expected = [("AVISO", "acesso banco ghost-db", "datastore não está no grafo"),
                    ("OK", "acesso nuvem dev", "profile definido"),
                    ("AVISO", "acesso nuvem staging", "ambiente não está no grafo"),
                    ("OK", "acesso url dev", "URL base definida"),
                    ("AVISO", "acesso url staging", "ambiente não está no grafo")]
        for status, item, detail in expected:
            with self.subTest(item=item):
                found = [r for r in rows if r[1] == item]
                self.assertEqual(len(found), 1, result.stdout)
                self.assertEqual(found[0][0], status, result.stdout)
                self.assertIn(detail, found[0][2])
        self.assertNoAccessValue(output(result), extra=("acme-stg-read", "https://stg.example.test"))


# --------------------------------------------------------------------------- UT-03


class ContextAccessTest(ResourceCase):
    def test_cloud_and_database_access_in_the_package(self):
        """SPEC-0096:UT-03 — access.cloud só para dev e access.databases só para orders-db: o deployment de dev tem
        cloud_access true, o de prod false; database_access é {"orders-db": true, "payments-db": false}; o Markdown diz
        "sem acesso local à nuvem" no de prod; nenhum valor de acesso aparece."""
        # SPEC-0096:UT-03
        self.configure([], access=self.access(clusters=False, urls=False))
        result = self.box.run("context", "--json", "api")
        self.assertExit(result, 0)
        package = json.loads(result.stdout)
        service = next(s for s in package["services"] if s["key"] == "service:api")
        deployments = {d["id"]: d for d in service["delivery"]["deployments"]}
        self.assertIs(deployments["dev-api"].get("cloud_access"), True)
        self.assertIs(deployments["prod-api"].get("cloud_access"), False)
        self.assertEqual(service.get("database_access"), {"orders-db": True, "payments-db": False})
        markdown = self.box.run("context", "api")
        self.assertExit(markdown, 0)
        lines = markdown.stdout.splitlines()
        prod = [line for line in lines if "`prod-api`" in line and line.strip().startswith("- prod")]
        dev = [line for line in lines if "`dev-api`" in line and line.strip().startswith("- dev")]
        self.assertTrue(prod and dev, markdown.stdout)
        self.assertIn("sem acesso local à nuvem", prod[0])
        self.assertNotIn("sem acesso local à nuvem", dev[0])
        self.assertNoAccessValue(output(result), output(markdown))

    def test_without_the_keys_the_fields_do_not_show(self):
        """SPEC-0096:UT-03 — sem access.cloud e sem access.databases, nem cloud_access nem database_access aparecem."""
        # SPEC-0096:UT-03
        self.configure([], access={})
        package = json.loads(self.box.run("context", "--json", "api").stdout)
        self.assertIsNone(find_key(package, "cloud_access"))
        self.assertIsNone(find_key(package, "database_access"))


# --------------------------------------------------------------------------- UT-04


class ResourceTargetTest(ResourceCase):
    def test_linked_resources_reach_the_adapter_with_the_linking_deployment(self):
        """SPEC-0096:UT-04 — com --env dev, queue:orders (aresta writes do deployment), datastore:orders-db
        (config_refs) e queue:orders-dlq (dlq de fila ligada) chegam ao adaptador em target.resource, com deployment
        dev-api; os atributos são só os escalares do nó."""
        # SPEC-0096:UT-04
        fn("linked_resources", SPEC)
        self.configure()
        cases = (("messaging", "queue", "queue:orders", {"kind": "queue", "id": "orders", "attrs": ORDERS_ATTRS}),
                 ("messaging", "queue", "queue:orders-dlq",
                  {"kind": "queue", "id": "orders-dlq", "attrs": {"region": "us-east-1"}}),
                 ("database", "migrations", "datastore:orders-db",
                  {"kind": "datastore", "id": "orders-db",
                   "attrs": {"engine": "postgres", "host": "orders-db.interno", "region": "us-east-1"}}))
        for capability, verb, resource, expected in cases:
            with self.subTest(resource=resource):
                self.reset_calls()
                result = self.probe(capability, verb, "--resource", resource, "--json")
                self.assertExit(result, 0)
                target = self.received()["input"]["target"]
                self.assertEqual(target["resource"], expected)
                self.assertEqual((target["deployment"], target["environment"], target["service"]),
                                 ("dev-api", "dev", "api"))

    def test_unlinked_missing_or_malformed_resources_exit_2_without_any_process(self):
        """SPEC-0096:UT-04 — topic:events (só do serviço) e datastore:billing-db (só do deployment de prod): exit 2
        "recurso <kind:id> não ligado a api em dev"; queue:nada: "não existe no atlas"; queue, orders e service:api:
        "--resource inválido". Em todos, nenhum processo do adaptador roda (nem o --describe)."""
        # SPEC-0096:UT-04
        self.configure()
        cases = (("topic:events", "recurso topic:events não ligado a api em dev"),
                 ("datastore:billing-db", "recurso datastore:billing-db não ligado a api em dev"),
                 ("queue:nada", "recurso queue:nada não existe no atlas"),
                 ("queue", "--resource inválido"), ("orders", "--resource inválido"),
                 ("service:api", "--resource inválido"), ("cluster:cluster-dev", "--resource inválido"))
        for resource, message in cases:
            with self.subTest(resource=resource):
                result = self.probe("messaging", "queue", "--resource", resource)
                self.assertInvalid(result, message)
                self.assertNothingRan()


# --------------------------------------------------------------------------- UT-05


class ResourceAttrsTest(ResourceCase):
    def test_attributes_out_of_the_rules_exit_2_without_the_value(self):
        """SPEC-0096:UT-05 — atributo do recurso ligado com texto começando com -, com quebra de linha, de 1025
        caracteres, region "us east 1" ou "useast-1", ou chave Bad-Key: exit 2 "alvo inválido no atlas: resource.",
        sem o valor, e nenhum processo roda."""
        # SPEC-0096:UT-05
        cases = (("começa com -", {"note": "-valor-proibido-0096"}, "valor-proibido-0096"),
                 ("quebra de linha", {"note": "linha1\nlinha2-0096"}, "linha2-0096"),
                 ("1025 caracteres", {"note": "z" * 1025}, "z" * 1025),
                 ("region com espaço", {"region": "us east 1"}, "us east 1"),
                 ("region sem hífen", {"region": "useast-1"}, "useast-1"),
                 ("chave inválida", {"Bad-Key": "x"}, None))
        for name, attrs, value in cases:
            with self.subTest(case=name):
                shutil.copy(FIXTURE / "graph.json", self.box.atlas / "graph.json")
                self.set_attrs("queue:orders", **attrs)
                self.configure()
                result = self.probe("messaging", "queue", "--resource", "queue:orders")
                self.assertInvalid(result, "alvo inválido no atlas: resource.")
                if value:
                    self.assertNotIn(value, output(result))
                self.assertEqual(self.calls("run"), [])
                self.assertNothingRan()

    def test_null_lists_and_objects_do_not_reach_the_adapter_and_do_not_refuse(self):
        """SPEC-0096:UT-05 — tags (lista), policy (objeto) e owner_note (null) de queue:orders não chegam em
        target.resource.attrs e não recusam; us-gov-west-1 é região válida."""
        # SPEC-0096:UT-05
        self.set_attrs("queue:orders", region="us-gov-west-1")
        self.configure()
        result = self.probe("messaging", "queue", "--resource", "queue:orders", "--json")
        self.assertExit(result, 0)
        attrs = self.received()["input"]["target"]["resource"]["attrs"]
        self.assertEqual(attrs, dict(ORDERS_ATTRS, region="us-gov-west-1"))


# --------------------------------------------------------------------------- UT-06


class AdapterChoiceTest(ResourceCase):
    def test_probe1_never_gets_a_resource_and_probe2_is_chosen(self):
        """SPEC-0096:UT-06 — probe@1 (primeiro, declara messaging) e probe@2 com targets [queue] e access [cloud]
        (segundo): `probe messaging queue --resource queue:orders` roda só o probe@2; o probe@1 só roda o --describe.
        Com --resource datastore:orders-db: exit 4 "nenhum adaptador para messaging com alvo datastore"."""
        # SPEC-0096:UT-06
        caps = {"messaging": {"verbs": ["queue"], "targets": ["queue"], "access": ["cloud"]}}
        self.configure([self.adapter1(), self.adapter2(caps)])
        result = self.probe("messaging", "queue", "--resource", "queue:orders", "--json")
        self.assertExit(result, 0)
        self.assertEqual(self.calls("run", record=self.record1), [], "o probe@1 recebeu um recurso")
        self.assertTrue(self.calls("describe", record=self.record1))
        self.assertEqual(self.received()["input"]["target"]["resource"]["id"], "orders")
        before = len(self.calls("run"))
        result = self.probe("messaging", "queue", "--resource", "datastore:orders-db")
        self.assertExit(result, 4)
        self.assertIn("nenhum adaptador para messaging com alvo datastore", output(result))
        self.assertEqual(len(self.calls("run")), before)
        self.assertEqual(self.calls("run", record=self.record1), [])

    def test_missing_local_access_is_refused_by_type(self):
        """SPEC-0096:UT-06 — sem access.cloud.dev: exit 4 "sem acesso local: cloud"; database declarado e sem
        access.databases.orders-db, ou com o passfile inexistente: "sem acesso local: database"; cluster declarado e
        sem access.clusters: "sem acesso local: cluster"; urls declarado e sem access.urls.dev: "sem acesso local:
        urls". O adaptador não roda e nenhum valor de acesso sai."""
        # SPEC-0096:UT-06
        missing = self.box.root / "secrets" / "nao-existe.pgpass"
        cluster_caps = dict(CAPS, messaging={"verbs": ["queue"], "targets": ["queue"], "access": ["cluster"]})
        cases = (
            ("cloud", CAPS, self.access(cloud=False), ("messaging", "queue", "--resource", "queue:orders")),
            ("database", CAPS, self.access(databases=False),
             ("database", "migrations", "--resource", "datastore:orders-db")),
            ("database", CAPS, self.access(passfile=missing),
             ("database", "migrations", "--resource", "datastore:orders-db")),
            ("cluster", cluster_caps, self.access(clusters=False), ("messaging", "queue", "--resource", "queue:orders")),
            ("urls", CAPS, self.access(urls=False), ("functional", "run")),
        )
        for kind, caps, access, args in cases:
            with self.subTest(kind=kind, args=args):
                self.reset_calls()
                self.configure([self.adapter2(caps)], access=access)
                result = self.probe(*args)
                self.assertExit(result, 4)
                self.assertIn(f"sem acesso local: {kind}", output(result))
                self.assertEqual(self.calls("run"), [])
                self.assertNoAccessValue(output(result), extra=(str(missing),))

    def test_a_resource_of_a_production_environment_needs_confirmation(self):
        """SPEC-0096:UT-06 — queue:orders ligado ao deployment de prod (sem tier): sem --confirm-production, exit 4 com
        a mensagem de produção e o adaptador sem rodar; com a opção (e access.cloud.prod), roda com deployment
        prod-api."""
        # SPEC-0096:UT-06
        access = self.access()
        access["cloud"]["prod"] = {"profile": "acme-prod-read"}
        self.configure(access=access)
        result = self.probe("messaging", "queue", "--resource", "queue:orders", env="prod")
        self.assertExit(result, 4)
        self.assertIn("ambiente prod é de produção ou sem marcação", output(result))
        self.assertEqual(self.calls("run"), [])
        result = self.probe("messaging", "queue", "--resource", "queue:orders", "--confirm-production", "--json",
                            env="prod")
        self.assertExit(result, 0)
        target = self.received()["input"]["target"]
        self.assertEqual((target["deployment"], target["environment"]), ("prod-api", "prod"))
        self.assertEqual(target["cloud"], {"profile": "acme-prod-read"})


# --------------------------------------------------------------------------- UT-07


class MinimalInputTest(ResourceCase):
    def allowed_env(self, credentials=()):
        return set(atlas().PROBE_BASE_ENV) | set(credentials)

    def test_cloud_only_gets_only_the_cloud_block_and_no_new_variable(self):
        """SPEC-0096:UT-07 — capacidade que declara só cloud: target tem service, environment, deployment, resource e
        cloud.profile, sem database, urls, campos de cluster, change nem journeys; o ambiente do adaptador não tem
        PGPASSFILE nem variável fora da base (AWS_PROFILE e PGPASSFILE do ambiente do teste não chegam)."""
        # SPEC-0096:UT-07
        self.configure()
        result = self.probe("messaging", "queue", "--resource", "queue:orders", "--json",
                            environ={"AWS_PROFILE": "nao-deve-chegar", "PGPASSFILE": "/nao/deve/chegar"})
        self.assertExit(result, 0)
        run = self.received()
        target = run["input"]["target"]
        self.assertEqual(set(target), BASE_TARGET | {"resource", "cloud"})
        self.assertEqual(target["cloud"], {"profile": PROFILE})
        self.assertEqual(set(run["env"]) - self.allowed_env(), set())
        self.assertEqual(f("validate_probe_input")(run["input"]), [])

    def test_empty_access_gets_only_the_base_fields(self):
        """SPEC-0096:UT-07 — access: [] com targets [queue] e [deployment]: target só com service, environment,
        deployment (e resource, quando há)."""
        # SPEC-0096:UT-07
        caps = {"messaging": {"verbs": ["queue"], "targets": ["queue"], "access": []},
                "inventory": {"verbs": ["status"], "targets": ["deployment"]}}
        self.configure([self.adapter2(caps)])
        for args, keys in ((("messaging", "queue", "--resource", "queue:orders"), BASE_TARGET | {"resource"}),
                           (("inventory", "status"), BASE_TARGET)):
            with self.subTest(args=args):
                self.reset_calls()
                self.assertExit(self.probe(*args, "--json"), 0)
                run = self.received()
                self.assertEqual(set(run["input"]["target"]), keys)
                self.assertNotIn("PGPASSFILE", run["env"])
                self.assertEqual(f("validate_probe_input")(run["input"]), [])

    def test_database_gets_the_block_and_pgpassfile_expanded(self):
        """SPEC-0096:UT-07 — database declarado e passfile ~/.pgpass-0096: target.database = {user, name, passfile
        expandido}, PGPASSFILE igual ao passfile expandido, e nenhuma outra variável nova."""
        # SPEC-0096:UT-07
        home_passfile = self.box.home / PASSFILE_NAME
        home_passfile.write_text("*:*:ordersdb:ro_user:x\n", encoding="utf-8")
        os.chmod(home_passfile, 0o600)
        access = self.access()
        access["databases"]["orders-db"]["passfile"] = f"~/{PASSFILE_NAME}"
        self.configure(access=access)
        result = self.probe("database", "migrations", "--resource", "datastore:orders-db", "--json")
        self.assertExit(result, 0)
        run = self.received()
        target = run["input"]["target"]
        self.assertEqual(set(target), BASE_TARGET | {"resource", "database"})
        self.assertEqual(target["database"], {"user": DB_USER, "name": DB_NAME, "passfile": str(home_passfile)})
        self.assertEqual(run["env"].get("PGPASSFILE"), str(home_passfile))
        self.assertEqual(set(run["env"]) - self.allowed_env(("PGPASSFILE",)), set())
        self.assertEqual(f("validate_probe_input")(run["input"]), [])

    def test_cluster_gets_the_four_cluster_fields_together(self):
        """SPEC-0096:UT-07 — cluster declarado: clusters, context, namespace e workloads vêm juntos, como no probe@1."""
        # SPEC-0096:UT-07
        caps = {"inventory": {"verbs": ["status"], "targets": ["deployment"], "access": ["cluster"]}}
        self.configure([self.adapter2(caps)])
        self.assertExit(self.probe("inventory", "status", "--json"), 0)
        run = self.received()
        target = run["input"]["target"]
        self.assertEqual(set(target), BASE_TARGET | CLUSTER_FIELDS)
        self.assertEqual((target["clusters"], target["context"], target["namespace"], target["workloads"]),
                         (["cluster-dev"], CONTEXT, "api-dev", ["Deployment/api"]))
        self.assertEqual(f("validate_probe_input")(run["input"]), [])

    def test_urls_and_journeys(self):
        """SPEC-0096:UT-07 — urls em access e inputs [journeys]: target.urls.base_url e target.journeys igual ao
        atributo journeys do serviço, sem repetição e em ordem (["checkout", "login"]); um serviço sem o atributo sai
        com 4 "sem jornadas curadas" sem rodar a consulta (SPEC-0103:UT-02); uma jornada com espaço no atlas: exit 2
        "alvo inválido no atlas: journeys", sem o valor, e a capacidade não roda."""
        # SPEC-0096:UT-07
        access = self.access()
        self.configure(access=access)
        self.write_scenario({"run": {"items": FUNCTIONAL_ITEMS}})  # SPEC-0103:UT-04 — saída no contrato de functional
        self.assertExit(self.probe("functional", "run", "--json"), 0)
        run = self.received()
        target = run["input"]["target"]
        self.assertEqual(set(target), BASE_TARGET | {"urls", "journeys"})
        self.assertEqual(target["urls"], {"base_url": BASE_URL})
        self.assertEqual(target["journeys"], ["checkout", "login"])
        self.assertEqual(f("validate_probe_input")(run["input"]), [])
        self.reset_calls()
        result = self.probe("functional", "run", "--json", service="worker")
        self.assertExit(result, 4)  # SPEC-0103:UT-02 — sem jornadas curadas, recusada
        self.assertIn("sem jornadas curadas para worker (attrs.journeys)", output(result))  # SPEC-0103:UT-02
        self.assertEqual(self.calls("run"), [])  # SPEC-0103:UT-02
        self.reset_calls()
        self.set_attrs("service:api", journeys=["check out-0096"])
        result = self.probe("functional", "run")
        self.assertInvalid(result, "alvo inválido no atlas: journeys")
        self.assertNotIn("check out-0096", output(result))
        self.assertEqual(self.calls("run"), [])


# --------------------------------------------------------------------------- UT-08


class MaskTest(ResourceCase):
    def passfile_forms(self):
        expanded = str(self.box.home / PASSFILE_NAME)
        return [f"~/{PASSFILE_NAME}", expanded, json.dumps(expanded)[1:-1], json.dumps(expanded)[1:-1].replace("/", "\\/"),
                urllib.parse.quote(expanded, safe=""), expanded.upper()]

    def setup_echo(self):
        home_passfile = self.box.home / PASSFILE_NAME
        home_passfile.write_text("x\n", encoding="utf-8")
        os.chmod(home_passfile, 0o600)
        access = self.access()
        access["databases"]["orders-db"]["passfile"] = f"~/{PASSFILE_NAME}"
        caps = {"database": {"verbs": ["migrations"], "targets": ["datastore"],
                             "access": ["cloud", "database", "urls"]},
                "messaging": CAPS["messaging"]}
        self.configure([self.adapter2(caps)], access=access)
        echoed = [PROFILE, DB_USER, DB_NAME, BASE_URL, *self.passfile_forms()]
        return echoed

    def assertMasked(self, result, echoed):
        text = lowered(output(result), self.log_text())
        for secret in echoed + [ACCOUNT]:
            self.assertNotIn(secret.lower(), text, f"apareceu: {secret}")

    def test_access_values_and_account_ids_are_masked_everywhere(self):
        """SPEC-0096:UT-08 — o adaptador ecoa nos itens e na message o profile, o usuário, o banco, a URL base, o
        passfile (cru, expandido, escapado em JSON, em URL e em maiúsculas), um ARN e uma URL de fila com conta:
        nada disso nem 123456789012 sai no stdout, no stderr ou no probes.log; o ARN e a URL saem com [REDACTED] no
        lugar da conta."""
        # SPEC-0096:UT-08
        echoed = self.setup_echo()
        line = " | ".join(echoed)
        self.write_scenario({"migrations": {"items": [{"line": line}, {"arn": ARN, "url": QUEUE_URL}],
                                            "message": f"vi {line} em {ARN}"}})
        for extra in ((), ("--json",)):
            with self.subTest(extra=extra):
                result = self.probe("database", "migrations", "--resource", "datastore:orders-db", *extra)
                self.assertExit(result, 0)
                self.assertMasked(result, echoed)
                self.assertIn(ARN_MASKED, result.stdout)
                self.assertIn(QUEUE_URL_MASKED, result.stdout)

    def test_stderr_and_summary_are_masked(self):
        """SPEC-0096:UT-08 — o mesmo eco no stderr de um adaptador que sai com 3 e nas linhas do --summary: nada sai."""
        # SPEC-0096:UT-08
        echoed = self.setup_echo()
        line = " | ".join(echoed)
        self.write_scenario({"migrations": {"exit": 3, "stderr": f"falhou: {line} {ARN} {QUEUE_URL}"}})
        result = self.probe("database", "migrations", "--resource", "datastore:orders-db")
        self.assertExit(result, 1)
        self.assertMasked(result, echoed)
        self.write_scenario({"migrations": {"items": [
            {"ts": "2026-11-24T10:00:00Z", "line": f"ERROR {line} {ARN}"},
            {"ts": "2026-11-24T10:01:00Z", "line": f"ERROR {line} {QUEUE_URL}"}]}})
        result = self.probe("database", "migrations", "--resource", "datastore:orders-db", "--summary", "--json")
        self.assertExit(result, 0)
        self.assertMasked(result, echoed)

    def test_the_log_has_resource_only_when_used(self):
        """SPEC-0096:UT-08 — a linha do probes.log de `--resource queue:orders` tem resource "queue:orders"; a de uma
        probe sem --resource não tem a chave."""
        # SPEC-0096:UT-08
        self.configure()
        self.assertExit(self.probe("messaging", "queue", "--resource", "queue:orders", "--json"), 0)
        self.assertEqual(self.log()[-1].get("resource"), "queue:orders")
        self.write_scenario({"run": {"items": FUNCTIONAL_ITEMS}})  # SPEC-0103:UT-04 — saída no contrato de functional
        self.assertExit(self.probe("functional", "run", "--json"), 0)
        last = self.log()[-1]
        self.assertNotIn("resource", last)
        self.assertNotIn("commit", last)
        self.assertEqual(set(last), LOG_KEYS)


# --------------------------------------------------------------------------- UT-09


class ChangeTest(ResourceCase):
    def configure_delivery(self, adapters=None):
        self.write_scenario({"trace": {"items": [{"commit": "3f2ef04", "state": "deployed"}]}})
        self.configure(adapters or [self.adapter2(credentials=("FAKE_CI_TOKEN",))])

    def test_commit_reaches_the_adapter_with_the_code_repositories(self):
        """SPEC-0096:UT-09 — `probe delivery trace --commit 3F2EF04`: target.change = {"commit": "3f2ef04",
        "repositories": ["acme/api"]} (sem o repositório de configuração acme/gitops), nenhum campo de cluster; o
        commit sai sem máscara; o probes.log tem commit "3f2ef04"; a credencial da CI chega só pelo nome declarado."""
        # SPEC-0096:UT-09
        self.configure_delivery()
        token, other = "valor-ci-falso-0096", "outro-valor-ci-0096"
        result = self.probe("delivery", "trace", "--commit", "3F2EF04", "--json",
                            environ={"FAKE_CI_TOKEN": token, "OTHER_CI_TOKEN": other})
        self.assertExit(result, 0)
        run = self.received()
        target = run["input"]["target"]
        self.assertEqual(target["change"], {"commit": "3f2ef04", "repositories": ["acme/api"]})
        self.assertEqual(set(target), BASE_TARGET | {"change"})
        self.assertEqual(f("validate_probe_input")(run["input"]), [])
        self.assertIn("3f2ef04", result.stdout)
        self.assertEqual(run["env"].get("FAKE_CI_TOKEN"), token)
        self.assertNotIn("OTHER_CI_TOKEN", run["env"])
        self.assertEqual(self.log()[-1].get("commit"), "3f2ef04")
        self.assertNotIn(token, output(result) + self.log_text())

    def test_invalid_commit_exits_2_without_any_process(self):
        """SPEC-0096:UT-09 — --commit abc, 3f2ef0z e um sha de 41 caracteres: exit 2 "--commit inválido", sem
        processo."""
        # SPEC-0096:UT-09
        self.configure_delivery()
        for sha in ("abc", "3f2ef0z", "a" * 41):
            with self.subTest(sha=sha):
                self.assertInvalid(self.probe("delivery", "trace", "--commit", sha), "--commit inválido")
                self.assertNothingRan()

    def test_required_or_not_accepted_commit(self):
        """SPEC-0096:UT-09 — delivery sem --commit: exit 2 "delivery exige --commit"; --commit em messaging (sem
        change) e num adaptador probe@1: exit 2 "--commit não é aceito por <capacidade>"; a capacidade não roda."""
        # SPEC-0096:UT-09
        self.configure_delivery()
        self.assertInvalid(self.probe("delivery", "trace"), "delivery exige --commit")
        self.assertInvalid(self.probe("messaging", "queue", "--resource", "queue:orders", "--commit", "3f2ef04"),
                           "--commit não é aceito por messaging")
        self.assertEqual(self.calls("run"), [])
        self.configure([self.adapter1(described="runtime=status")])
        self.assertInvalid(self.probe("runtime", "status", "--commit", "3f2ef04"),
                           "--commit não é aceito por runtime")
        self.assertEqual(self.calls("run", record=self.record1), [])

    def test_a_service_without_code_repository_exits_2(self):
        """SPEC-0096:UT-09 — service:worker só com repositório de configuração: exit 2 "nenhum repositório de código
        de service:worker no atlas para --commit", sem processo."""
        # SPEC-0096:UT-09
        self.configure_delivery()
        result = self.probe("delivery", "trace", "--commit", "3f2ef04", service="worker")
        self.assertInvalid(result, "nenhum repositório de código de service:worker no atlas para --commit")
        self.assertNothingRan()


# --------------------------------------------------------------------------- UT-10


LINKED_DEV = ({"resource": "datastore:orders-db", "relation": "config_ref", "deployment": "dev-api"},
              {"resource": "queue:orders", "relation": "writes", "deployment": "dev-api"},
              {"resource": "queue:orders-dlq", "relation": "dlq", "deployment": "dev-api"})


class LinkedResourcesTest(unittest.TestCase):
    EXPECTED = LINKED_DEV

    def test_linked_resources_of_the_fixture(self):
        """SPEC-0096:UT-10 — linked_resources(graph, "api", "dev") devolve exatamente o datastore por config_ref, a fila
        por writes e a DLQ, nessa ordem e sem repetição; nada de topic:events (só do serviço) nem de
        datastore:billing-db (só de prod)."""
        # SPEC-0096:UT-10
        self.assertEqual(f("linked_resources")(fixture_graph(), "api", "dev"), list(self.EXPECTED))

    def test_dlq_that_is_not_text_or_points_nowhere_links_nothing(self):
        """SPEC-0096:UT-10 — dlq como lista, como número ou apontando para fila inexistente: só os dois primeiros, sem
        erro; um ambiente sem deployment dá []."""
        # SPEC-0096:UT-10
        for dlq in (["orders-dlq"], 5, "nao-existe"):
            with self.subTest(dlq=dlq):
                graph = fixture_graph()
                next(n for n in graph["nodes"] if n["key"] == "queue:orders")["attrs"]["dlq"] = dlq
                self.assertEqual(f("linked_resources")(graph, "api", "dev"), list(self.EXPECTED[:2]))
        self.assertEqual(f("linked_resources")(fixture_graph(), "api", "qa"), [])

    def test_prod_and_duplicates(self):
        """SPEC-0096:UT-10 — em prod: billing-db por reads, queue:orders por writes e a DLQ; uma aresta repetida não
        repete a entrada."""
        # SPEC-0096:UT-10
        graph = fixture_graph()
        graph["edges"].append(copy.deepcopy(next(e for e in graph["edges"] if e["from"] == "deployment:prod-api"
                                                  and e["type"] == "writes")))
        self.assertEqual(f("linked_resources")(graph, "api", "prod"), [
            {"resource": "datastore:billing-db", "relation": "reads", "deployment": "prod-api"},
            {"resource": "queue:orders", "relation": "writes", "deployment": "prod-api"},
            {"resource": "queue:orders-dlq", "relation": "dlq", "deployment": "prod-api"}])

    def test_reads_nothing_but_the_graph(self):
        """SPEC-0096:UT-10 — a função não abre arquivo nem socket: só o grafo recebido."""
        # SPEC-0096:UT-10
        linked = f("linked_resources")
        graph = fixture_graph()

        def forbidden(*args, **kwargs):
            raise AssertionError("linked_resources leu fora do grafo")

        with mock.patch("builtins.open", forbidden), mock.patch("io.open", forbidden), \
                mock.patch("os.open", forbidden), mock.patch.object(socket, "socket", forbidden):
            self.assertEqual(linked(graph, "api", "dev"), list(self.EXPECTED))


# --------------------------------------------------------------------------- IT-01 e IT-02


class EndToEndTest(ResourceCase):
    def test_messaging_database_and_unlinked_through_the_cli(self):
        """SPEC-0096:IT-01 — atlas.py como processo: `probe messaging queue --resource queue:orders-dlq --json` segue
        probe@2, o adaptador recebe o recurso (ligado pela DLQ) e target.cloud.profile, o probes.log tem resource;
        `probe database migrations --resource datastore:orders-db --json` entrega target.database e PGPASSFILE;
        `--resource topic:events` sai com 2 sem processo; nenhuma saída nem o probes.log traz o profile, o usuário, o
        banco, o passfile ou a conta."""
        # SPEC-0096:IT-01
        self.write_scenario({"queue": {"items": [{"queue": "orders-dlq", "arn": ARN, "visible": 0}]},
                             "migrations": {"items": [{"pending": 0}]}})
        self.configure()
        outputs = []
        result = self.probe("messaging", "queue", "--resource", "queue:orders-dlq", "--json")
        outputs.append(output(result))
        self.assertExit(result, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["contract"], "probe@2")
        self.assertEqual(f("validate_probe_output")(data), [])
        run = self.received()
        self.assertEqual(run["input"]["contract"], "probe@2")
        self.assertEqual(run["input"]["target"]["resource"]["id"], "orders-dlq")
        self.assertEqual(run["input"]["target"]["cloud"], {"profile": PROFILE})
        self.assertEqual(self.log()[-1].get("resource"), "queue:orders-dlq")
        self.reset_calls()
        result = self.probe("database", "migrations", "--resource", "datastore:orders-db", "--json")
        outputs.append(output(result))
        self.assertExit(result, 0)
        run = self.received()
        self.assertEqual(run["input"]["target"]["database"],
                         {"user": DB_USER, "name": DB_NAME, "passfile": str(self.passfile)})
        self.assertEqual(run["env"].get("PGPASSFILE"), str(self.passfile))
        self.reset_calls()
        result = self.probe("messaging", "queue", "--resource", "topic:events", "--json")
        outputs.append(output(result))
        self.assertInvalid(result, "não ligado a api em dev")
        self.assertNothingRan()
        self.assertNoAccessValue(*outputs, self.log_text(), extra=(ACCOUNT,))

    def test_delivery_and_functional_through_the_cli(self):
        """SPEC-0096:IT-02 — `probe delivery trace --commit 3f2ef04 --json` (inputs [change], access [], credentials
        [FAKE_CI_TOKEN]): target.change com os repositórios de código, nenhum campo de cluster, FAKE_CI_TOKEN pelo
        nome, sem PGPASSFILE nem outra variável nova, e commit no probes.log. `probe functional run --json` (urls e
        journeys): target.urls.base_url e target.journeys, e a URL não sai no stdout, no stderr nem no probes.log."""
        # SPEC-0096:IT-02
        self.write_scenario({"trace": {"items": [{"commit": "3f2ef04"}]},
                             # SPEC-0103:UT-04 — um item por jornada curada, no contrato de functional
                             "run": {"items": FUNCTIONAL_ITEMS, "message": f"rodou em {BASE_URL}"}})
        self.configure([self.adapter2(credentials=("FAKE_CI_TOKEN",))])
        result = self.probe("delivery", "trace", "--commit", "3f2ef04", "--json",
                            environ={"FAKE_CI_TOKEN": "valor-ci-falso-0096"})
        self.assertExit(result, 0)
        run = self.received()
        target = run["input"]["target"]
        self.assertEqual(target["change"], {"commit": "3f2ef04", "repositories": ["acme/api"]})
        self.assertFalse(CLUSTER_FIELDS & set(target))
        self.assertIn("FAKE_CI_TOKEN", run["env"])
        allowed = set(atlas().PROBE_BASE_ENV) | {"FAKE_CI_TOKEN"}
        self.assertEqual(set(run["env"]) - allowed, set())
        self.assertEqual(self.log()[-1].get("commit"), "3f2ef04")
        self.reset_calls()
        result = self.probe("functional", "run", "--json")
        self.assertExit(result, 0)
        target = self.received()["input"]["target"]
        self.assertEqual(target["urls"], {"base_url": BASE_URL})
        self.assertEqual(target["journeys"], ["checkout", "login"])
        self.assertNotIn(BASE_URL.lower(), lowered(output(result), self.log_text()))


# --------------------------------------------------------------------------- CT-01


BLOCK_RE = re.compile(r"```json (probe@[12]) (describe|input|output) (valid|invalid)\n(.*?)\n```", re.DOTALL)

VALID2 = {
    "describe": [
        {"contract": "probe@2", "adapter": "aws-messaging", "capabilities": {"messaging": {
            "verbs": ["queue", "subscriptions"], "targets": ["queue", "topic"], "access": ["cloud"]}}},
        {"contract": "probe@2", "adapter": "smoke", "capabilities": {"functional": {
            "verbs": ["run"], "targets": ["deployment"], "access": ["urls"], "inputs": ["journeys"]}}},
        {"contract": "probe@2", "adapter": "pg", "capabilities": {"database": {
            "verbs": ["migrations"], "targets": ["datastore"], "access": ["database"]}}},
    ],
    "input": [
        {"contract": "probe@2", "capability": "messaging", "verb": "queue", "target": {
            "service": "api", "environment": "dev", "deployment": "dev-api",
            "resource": {"kind": "queue", "id": "orders-dlq", "attrs": {"region": "us-east-1", "name": "orders-dlq"}},
            "cloud": {"profile": "acme-dev-read"}}, "limits": {"lines": 200, "since_seconds": 1800}},
        {"contract": "probe@2", "capability": "delivery", "verb": "trace", "target": {
            "service": "api", "environment": "dev", "deployment": "dev-api",
            "change": {"commit": "3f2ef04", "repositories": ["acme/api", "acme/gitops"]}},
         "limits": {"lines": 200, "since_seconds": 1800}},
        {"contract": "probe@2", "capability": "functional", "verb": "run", "target": {
            "service": "api", "environment": "dev", "deployment": "dev-api",
            "urls": {"base_url": "https://api.dev.example.test"}, "journeys": ["checkout"]},
         "limits": {"lines": 200, "since_seconds": 1800}},
        {"contract": "probe@2", "capability": "database", "verb": "migrations", "target": {
            "service": "api", "environment": "dev", "deployment": "dev-api",
            "resource": {"kind": "datastore", "id": "orders-db", "attrs": {}},
            "database": {"user": "ro_user", "name": "ordersdb", "passfile": "/home/<nome>/.pgpass"}},
         "limits": {"lines": 200, "since_seconds": 1800}},
        {"contract": "probe@2", "capability": "inventory", "verb": "status", "target": {
            "service": "api", "environment": "dev", "deployment": "dev-api", "clusters": ["cluster-dev"],
            "context": "ctx-dev", "namespace": "api", "workloads": ["Deployment/api"]},
         "limits": {"lines": 200, "since_seconds": 1800}},
    ],
    "output": [
        {"contract": "probe@2", "adapter": "aws-messaging", "capability": "messaging", "verb": "queue",
         "status": "ok", "items": [{"name": "orders", "visible": 0, "tags": ["a"]}], "truncated": False},
        {"contract": "probe@2", "adapter": "pg", "capability": "database", "verb": "migrations", "status": "error",
         "items": [], "truncated": False, "message": "sem permissão"},
    ],
}


def _with(data, path, value=None, drop=False):
    out = copy.deepcopy(data)
    node = out
    for key in path[:-1]:
        node = node[key]
    if drop:
        node.pop(path[-1])
    else:
        node[path[-1]] = value
    return out


def invalid2():
    d_msg, i_msg, i_db, i_chg, i_cl, o_msg = (VALID2["describe"][0], VALID2["input"][0], VALID2["input"][3],
                                             VALID2["input"][1], VALID2["input"][4], VALID2["output"][0])
    return {
        "describe": [
            ("targets cluster", _with(d_msg, ["capabilities", "messaging", "targets"], ["cluster"])),
            ("inputs secrets", _with(d_msg, ["capabilities", "messaging", "inputs"], ["secrets"])),
            ("database sem datastore", _with(d_msg, ["capabilities", "messaging", "access"], ["database"])),
            ("targets vazio", _with(d_msg, ["capabilities", "messaging", "targets"], [])),
            ("access repetido", _with(d_msg, ["capabilities", "messaging", "access"], ["cloud", "cloud"])),
            ("chave extra", _with(d_msg, ["capabilities", "messaging", "zzextra"], True)),
        ],
        "input": [
            ("clusters sem context", _with(i_cl, ["target", "context"], drop=True)),
            ("database sem passfile", _with(i_db, ["target", "database", "passfile"], drop=True)),
            ("commit em maiúsculas", _with(i_chg, ["target", "change", "commit"], "3F2EF04")),
            ("resource com kind cluster", _with(i_msg, ["target", "resource", "kind"], "cluster")),
            ("journeys não lista", _with(VALID2["input"][2], ["target", "journeys"], "checkout")),
            ("target com chave extra", _with(i_msg, ["target", "zzextra"], "x")),
        ],
        "output": [
            ("chave extra", _with(o_msg, ["extra"], "x")),
            ("status fora", _with(o_msg, ["status"], "maybe")),
            ("item com objeto", _with(o_msg, ["items"], [{"spec": {"replicas": 1}}])),
        ],
    }


VALIDATORS = {"describe": "validate_probe_describe", "input": "validate_probe_input",
              "output": "validate_probe_output"}


class ContractTest(ResourceCase):
    def doc_blocks(self):
        text = PROBES_DOC.read_text(encoding="utf-8")
        return [(m.group(1), m.group(2), m.group(3), json.loads(m.group(4))) for m in BLOCK_RE.finditer(text)]

    def test_examples_of_the_reference_are_accepted_or_refused(self):
        """SPEC-0096:CT-01 — os blocos ```json probe@1|probe@2 <tipo> <valid|invalid> de references/probes.md: ao menos
        dois válidos e dois inválidos de cada tipo em probe@2, cobrindo target.resource, cloud, database, urls, change
        e journeys; os válidos passam e cada inválido é recusado com motivo."""
        # SPEC-0096:CT-01
        blocks = self.doc_blocks()
        for kind in VALIDATORS:
            for verdict in ("valid", "invalid"):
                count = len([b for b in blocks if b[:3] == ("probe@2", kind, verdict)])
                self.assertGreaterEqual(count, 2, f"probe@2 {kind} {verdict}: {count} bloco(s) em probes.md")
        covered = set()
        for contract, kind, verdict, data in blocks:
            if contract == "probe@2" and kind == "input" and isinstance(data.get("target"), dict):
                covered |= set(data["target"])
        self.assertTrue({"resource", "cloud", "database", "urls", "change", "journeys"} <= covered, covered)
        for contract, kind, verdict, data in blocks:
            with self.subTest(contract=contract, kind=kind, verdict=verdict, data=json.dumps(data)[:80]):
                problems = f(VALIDATORS[kind])(data)
                if verdict == "valid":
                    self.assertEqual(problems, [])
                else:
                    self.assertTrue(problems and all(isinstance(p, str) and p for p in problems), problems)

    def test_contract_samples_of_the_spec(self):
        """SPEC-0096:CT-01 — os exemplos válidos da spec passam; os inválidos (targets cluster, inputs secrets,
        clusters sem context, database com alvo queue, database sem passfile, commit em maiúsculas, saída com extra e
        os demais) são recusados com motivo, sem citar o valor."""
        # SPEC-0096:CT-01
        for kind, samples in VALID2.items():
            for data in samples:
                with self.subTest(kind=kind, valid=json.dumps(data)[:80]):
                    self.assertEqual(f(VALIDATORS[kind])(data), [])
        for kind, samples in invalid2().items():
            for name, data in samples:
                with self.subTest(kind=kind, invalid=name):
                    problems = f(VALIDATORS[kind])(data)
                    self.assertTrue(problems, f"{name} foi aceito")
                    joined = " ".join(problems)
                    for value in ("3F2EF04", "ro_user", "ordersdb", "acme-dev-read"):
                        self.assertNotIn(value, joined)

    def test_probe1_stays_valid_and_never_carries_a_resource(self):
        """SPEC-0096:CT-01 — probe@1 continua válido nos três validadores; uma entrada probe@1 com target.resource ou
        target.cloud é recusada."""
        # SPEC-0096:CT-01
        describe = {"contract": "probe@1", "adapter": "kubernetes", "capabilities": {"runtime": ["status", "logs"]}}
        entry = {"contract": "probe@1", "capability": "runtime", "verb": "logs",
                 "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "clusters": ["c"],
                            "context": "ctx", "namespace": "api", "workloads": ["Deployment/api"]},
                 "limits": {"lines": 200, "since_seconds": 1800}}
        out = {"contract": "probe@1", "adapter": "kubernetes", "capability": "runtime", "verb": "logs", "status": "ok",
               "items": [], "truncated": False}
        self.assertEqual(f("validate_probe_describe")(describe), [])
        self.assertEqual(f("validate_probe_input")(entry), [])
        self.assertEqual(f("validate_probe_output")(out), [])
        for key, value in (("resource", {"kind": "queue", "id": "orders", "attrs": {}}),
                           ("cloud", {"profile": "acme-dev-read"})):
            with self.subTest(key=key):
                self.assertTrue(f("validate_probe_input")(_with(entry, ["target", key], value)))

    def test_an_unknown_contract_is_refused_by_name(self):
        """SPEC-0096:CT-01 — contract probe@3 nos três validadores: "contract precisa ser probe@1 ou probe@2"."""
        # SPEC-0096:CT-01
        for kind, samples in VALID2.items():
            with self.subTest(kind=kind):
                problems = f(VALIDATORS[kind])(dict(samples[0], contract="probe@3"))
                self.assertIn("contract precisa ser probe@1 ou probe@2", problems)

    def test_an_output_with_another_contract_than_the_describe_exits_1(self):
        """SPEC-0096:CT-01 — adaptador probe@2 que responde contract probe@1: exit 1, fora do contrato, sem item."""
        # SPEC-0096:CT-01
        self.write_scenario({"queue": {"contract": "probe@1", "items": [{"name": "ITEM-MARCADOR-0096"}]}})
        self.configure()
        result = self.probe("messaging", "queue", "--resource", "queue:orders", "--json")
        self.assertExit(result, 1)
        self.assertIn("fora do contrato", output(result))
        self.assertNotIn("ITEM-MARCADOR-0096", output(result))


if __name__ == "__main__":
    unittest.main()
