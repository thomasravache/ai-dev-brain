"""Adaptador de probe de runtime Kubernetes: estado, eventos e logs (SPEC-0089: UT-01 a UT-05, IT-01 e CT-01;
ADR-0023; contrato probe@1 da SPEC-0088).

Contrato (seção 6 da SPEC-0089) que estes testes fixam:

    assets/probes/kubernetes.py --describe ->
        {"contract": "probe@1", "adapter": "kubernetes", "capabilities": {"runtime": ["status", "events", "logs"]}}
    entrada probe@1 no stdin; saída probe@1 no stdout (exit 0 também no erro, com status "error", items [] e a
    mensagem do contrato: "kubectl não encontrado" | "sem permissão (Forbidden)" | "contexto inexistente" |
    "chamada não permitida" | "timeout").
    chamadas permitidas, sempre com --context <target.context>, -n <target.namespace> e --request-timeout:
        kubectl get <recurso> [<nome>] -o json    recurso ∈ deployments, statefulsets, daemonsets, rollouts,
                                                  replicasets, pods, events
        kubectl logs <Kind>/<nome> --all-containers --timestamps --since=<s>s --tail=<n> --prefix
    status: um item por workload ({kind: workload, workload, found, desired, updated, ready, available,
        rollout_complete}) e um por pod ({kind: pod, workload, pod, phase, ready, restarts, images,
        last_termination}); imagem = caminho normalizado (SPEC-0082) + ":<tag>" + "@<digest>", sem o host.
    events: {reason, object, count, last_ts, message}, só Warning, só dos workloads e dos pods deles, na janela;
        message até 300 caracteres.
    logs: {workload, pod, container, ts, line}, os mais recentes até limits.lines; excedente -> truncated: true.

Leituras conservadoras desta suíte (ADR-0023; listadas no relatório do test-writer para o Architect):
    - "todo argv começa com get ou logs" (UT-05): as opções globais vêm depois do subcomando.
    - As únicas opções aceitas são as do contrato: em get, --context, -n/--namespace, --request-timeout e -o json;
      em logs, essas (sem -o) mais --all-containers, --timestamps, --prefix, --since e --tail. Nada de -l, -A,
      --kubeconfig, --raw ou outra. Com espaço ou "=" tanto faz; a ordem das opções também.
    - "No máximo um get por tipo de recurso e um logs por workload" vale para cada execução do adaptador.
    - --since é exatamente since_seconds em segundos ("1800s"); --tail é um inteiro de 1 a limits.lines;
      --request-timeout é um número positivo (com s, m ou ms, ou sem unidade). O valor exato da folga não é fixado.
    - Erro da ferramenta e chamada recusada saem com exit 0 e status "error" (references/probes.md, "Escrever um
      adaptador", passo 5).
    - Um verbo fora de status/events/logs, ou um workload de kind fora da lista (Secret, ConfigMap), é
      "chamada não permitida", sem nenhuma chamada ao kubectl.
    - A redaction das linhas fica com o núcleo: o UT-03 não exige que o adaptador mascare nem que deixe de mascarar;
      o IT-01 confere que um e-mail de linha de log sai mascarado pelo núcleo.
    - IT-01 usa o adaptador sem `command` (Emenda v2: o núcleo cai em assets/probes/kubernetes.py) e sem
      credenciais: o kubectl falso acha o próprio cenário ao lado dele (o núcleo só passa a base fixa de variáveis).

Isolamento: pasta temporária com HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME próprios; o PATH dos testes unitários é
só a pasta do kubectl falso (fixtures/kubernetes/fake_kubectl.py, copiado como `kubectl`), então nenhum kubectl de
verdade, nenhum ~/.kube e nenhuma rede; nomes genéricos (acme, api, worker).
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

from helpers import SKILL, TESTS, Sandbox, fn, output, snapshot
from test_probe import CONTEXTS, build_probe_atlas, local_text, probes_yaml

SPEC = "SPEC-0089"
ADAPTER = SKILL / "assets" / "probes" / "kubernetes.py"
FIXTURES = TESTS / "fixtures" / "kubernetes"
FAKE_KUBECTL = FIXTURES / "fake_kubectl.py"
CLUSTER = FIXTURES / "cluster"
CONTEXT = "ctx-acme-local-0089"
NAMESPACE = "acme-apps"
DIGEST = "sha256:" + "abc0" * 16
API_IMAGE = f"acme/api:1.4.2@{DIGEST}"
WORKER_IMAGE = "acme/worker:2.0.0"
API_PODS = ("api-7f9c-aaaa", "api-7f9c-bbbb", "api-7f9c-cccc")
WORKER_PODS = ("worker-5d8b-aaaa", "worker-5d8b-bbbb")
RESOURCES = ("deployments", "statefulsets", "daemonsets", "rollouts", "replicasets", "pods", "events")
LOG_KINDS = {"deployment", "statefulset", "daemonset", "rollout", "replicaset", "pod"}
GLOBAL_OPTIONS = {"--context", "-n", "--namespace", "--request-timeout"}
GET_OPTIONS = GLOBAL_OPTIONS | {"-o", "--output"}
LOGS_OPTIONS = GLOBAL_OPTIONS | {"--since", "--tail"}
LOGS_FLAGS = {"--all-containers", "--timestamps", "--prefix"}
TIMEOUT_RE = re.compile(r"^\d+(?:\.\d+)?(?:ms|s|m)?$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
WORKLOAD_KEYS = {"kind", "workload", "found", "desired", "updated", "ready", "available", "rollout_complete"}
POD_KEYS = {"kind", "workload", "pod", "phase", "ready", "restarts", "images", "last_termination"}
EVENT_KEYS = {"reason", "object", "count", "last_ts", "message"}
LOG_KEYS = {"workload", "pod", "container", "ts", "line"}
DESCRIBE = {"contract": "probe@1", "adapter": "kubernetes", "capabilities": {"runtime": ["status", "events", "logs"]}}
FAIL_MESSAGES = {"forbidden": "sem permissão (Forbidden)", "nocontext": "contexto inexistente", "timeout": "timeout"}
REFUSED = "chamada não permitida"
EMAIL = "pessoa.falsa@example.com"


def f(name):
    return fn(name, "SPEC-0088")


def probe_input(verb, workloads=("Deployment/api",), lines=200, since=1800, capability="runtime", context=CONTEXT,
                namespace=NAMESPACE):
    return {"contract": "probe@1", "capability": capability, "verb": verb,
            "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "clusters": ["cluster-dev"],
                       "context": context, "namespace": namespace, "workloads": list(workloads)},
            "limits": {"lines": lines, "since_seconds": since}}


def install_kubectl(folder: Path, record: Path, fail=""):
    """Copia o kubectl falso como `kubectl` (cabeçalho com o Python dos testes) e grava o cenário ao lado dele."""
    folder.mkdir(parents=True, exist_ok=True)
    body = FAKE_KUBECTL.read_text(encoding="utf-8").split("\n", 1)[1]
    target = folder / "kubectl"
    target.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    scenario = {"record": str(record), "fixtures": str(CLUSTER), "fail": fail}
    (folder / "fake-kubectl.json").write_text(json.dumps(scenario), encoding="utf-8")
    return target


def read_calls(record: Path) -> list:
    if not record.exists():
        return []
    return [json.loads(line)["argv"] for line in record.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_argv(argv, value_options, flags):
    """(palavras posicionais, {opção: valor}, opções desconhecidas) de um argv de kubectl."""
    words, options, unknown, i = [], {}, [], 0
    while i < len(argv):
        arg = argv[i]
        name, eq, value = arg.partition("=")
        if name in value_options:
            if not eq:
                value = argv[i + 1] if i + 1 < len(argv) else None
                i += 1
            options["-n" if name == "--namespace" else "-o" if name == "--output" else name] = value
        elif name in flags and (not eq or value == "true"):
            options[name] = True
        elif arg.startswith("-"):
            unknown.append(arg)
        else:
            words.append(arg)
        i += 1
    return words, options, unknown


def call_problems(argv, data) -> list:
    """Problemas de um argv frente à lista fechada da SPEC-0089 (seção 6) para a entrada `data`; [] = permitido."""
    target, limits = data["target"], data["limits"]
    if not argv or argv[0] not in ("get", "logs"):
        return [f"subcomando fora da lista: {argv[:1]}"]
    joined = " ".join(argv).lower()
    problems = [f"lê {word}" for word in ("secret", "configmap") if word in joined]
    if argv[0] == "get":
        words, options, unknown = parse_argv(argv[1:], GET_OPTIONS, set())
        if not words or words[0] not in RESOURCES or len(words) > 2:
            problems.append(f"recurso fora da lista: {words}")
        if options.get("-o") != "json":
            problems.append("get sem -o json")
    else:
        words, options, unknown = parse_argv(argv[1:], LOGS_OPTIONS, LOGS_FLAGS)
        if "-o" in options:
            problems.append("logs com -o")
        kind = words[0].partition("/")[0].lower() if len(words) == 1 and "/" in words[0] else None
        if kind not in LOG_KINDS:
            problems.append(f"logs de algo fora da lista: {words}")
        missing = LOGS_FLAGS - set(options)
        if missing:
            problems.append(f"logs sem {sorted(missing)}")
        if options.get("--since") != f"{limits['since_seconds']}s":
            problems.append(f"--since diferente de {limits['since_seconds']}s: {options.get('--since')}")
        tail = str(options.get("--tail"))
        if not tail.isdigit() or not 1 <= int(tail) <= limits["lines"]:
            problems.append(f"--tail fora de 1..{limits['lines']}: {options.get('--tail')}")
    if unknown:
        problems.append(f"opções fora da lista: {unknown}")
    if options.get("--context") != target["context"]:
        problems.append("--context diferente do target.context")
    if options.get("-n") != target["namespace"]:
        problems.append(f"-n diferente do target.namespace: {options.get('-n')}")
    if not TIMEOUT_RE.match(str(options.get("--request-timeout"))) or str(options.get("--request-timeout"))[0] == "0":
        problems.append(f"--request-timeout ausente ou inválido: {options.get('--request-timeout')}")
    return problems


def words_of(argv):
    if argv[0] == "get":
        return parse_argv(argv[1:], GET_OPTIONS, set())[0]
    return parse_argv(argv[1:], LOGS_OPTIONS, LOGS_FLAGS)[0]


class KubectlCase(unittest.TestCase):
    """Uma pasta temporária por teste: HOME, configuração e a pasta do kubectl falso (o único item do PATH)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.record = self.root / "kubectl-calls.jsonl"

    def install(self, fail=""):
        install_kubectl(self.bin, self.record, fail)

    def environment(self):
        env = {"PATH": str(self.bin), "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"),
               "ATLAS_CONFIG_HOME": str(self.root / "config-home"), "LANG": "C.UTF-8"}
        for name in ("TMPDIR", "SYSTEMROOT"):
            if name in os.environ:
                env[name] = os.environ[name]
        return env

    def adapter(self, *args, stdin=""):
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        result = subprocess.run([sys.executable, str(ADAPTER), *args], input=stdin, capture_output=True, text=True,
                                cwd=self.root, env=self.environment(), timeout=120, check=False)
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        return result

    def run_probe(self, data):
        """Roda o adaptador com `data` no stdin; confere exit 0, a saída probe@1 (validador do núcleo), o pedido
        ecoado, o contexto fora da saída e cada chamada ao kubectl contra a lista fechada (UT-05)."""
        result = self.adapter(stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0, output(result))
        self.assertNotIn(data["target"]["context"], result.stdout + result.stderr, "o contexto apareceu na saída")
        out = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(out), [], out)
        self.assertEqual({k: out[k] for k in ("contract", "adapter", "capability", "verb")},
                         {"contract": "probe@1", "adapter": "kubernetes", "capability": data["capability"],
                          "verb": data["verb"]})
        self.assertAllowedCalls(data)
        return out

    def calls(self):
        return read_calls(self.record)

    def assertAllowedCalls(self, data):
        """SPEC-0089:UT-05 — todo argv começa com get ou logs, com um recurso da lista e as opções do contrato; no
        máximo um get por recurso e um logs por workload; nenhum Secret nem ConfigMap."""
        calls = self.calls()
        for argv in calls:
            self.assertEqual(call_problems(argv, data), [], argv)
        gets = [words_of(a)[0] for a in calls if a[0] == "get"]
        for resource in set(gets):
            self.assertLessEqual(gets.count(resource), 1, f"mais de um get de {resource}: {calls}")
        self.assertLessEqual(sum(1 for a in calls if a[0] == "logs"), len(data["target"]["workloads"]), calls)

    def assertError(self, out, message):
        self.assertEqual(out["status"], "error", out)
        self.assertEqual(out["items"], [], out)
        self.assertIn(message, out.get("message", ""), out)


# --------------------------------------------------------------------------- UT-01


class StatusTest(KubectlCase):
    def test_rollout_complete_and_failing_with_images_without_registry_host(self):
        """SPEC-0089:UT-01 — Deployment api com 3 de 3 prontas e pods com ghcr.io/acme/api:1.4.2@sha256:…; worker
        com 1 de 2 prontas e um pod em CrashLoop com 4 restarts e último término OOMKilled. `status` dá api com
        rollout_complete true e imagens acme/api:1.4.2@sha256:… (sem ghcr.io); worker com rollout_complete false e o
        pod com restarts 4 e last_termination OOMKilled; o workload billing (fora do alvo) não aparece."""
        self.install()
        data = probe_input("status", workloads=("Deployment/api", "Deployment/worker"))
        out = self.run_probe(data)
        self.assertEqual(out["status"], "ok", out)
        workloads = {i["workload"]: i for i in out["items"] if i.get("kind") == "workload"}
        pods = {i["pod"]: i for i in out["items"] if i.get("kind") == "pod"}
        self.assertEqual(set(workloads), {"Deployment/api", "Deployment/worker"})
        self.assertEqual(set(pods), set(API_PODS) | set(WORKER_PODS))
        for item in out["items"]:
            self.assertLessEqual(set(item), WORKLOAD_KEYS if item.get("kind") == "workload" else POD_KEYS, item)
        self.assertEqual({k: workloads["Deployment/api"].get(k) for k in WORKLOAD_KEYS},
                         {"kind": "workload", "workload": "Deployment/api", "found": True, "desired": 3,
                          "updated": 3, "ready": 3, "available": 3, "rollout_complete": True})
        worker = workloads["Deployment/worker"]
        self.assertEqual((worker.get("found"), worker.get("desired"), worker.get("ready"),
                          worker.get("rollout_complete")), (True, 2, 1, False), worker)
        for name in API_PODS:
            self.assertEqual({k: pods[name].get(k) for k in POD_KEYS},
                             {"kind": "pod", "workload": "Deployment/api", "pod": name, "phase": "Running",
                              "ready": True, "restarts": 0, "images": [API_IMAGE], "last_termination": ""})
        crash = pods["worker-5d8b-bbbb"]
        self.assertEqual((crash.get("workload"), crash.get("ready"), crash.get("restarts"),
                          crash.get("last_termination"), crash.get("images")),
                         ("Deployment/worker", False, 4, "OOMKilled", [WORKER_IMAGE]), crash)
        self.assertEqual(pods["worker-5d8b-aaaa"].get("images"), [WORKER_IMAGE])
        text = json.dumps(out)
        for host in ("ghcr.io", "registry.example.com"):
            self.assertNotIn(host, text)
        self.assertNotIn("billing", text)
        fetched = {words_of(a)[0] for a in self.calls() if a[0] == "get"}
        self.assertLessEqual({"deployments", "pods"}, fetched, self.calls())
        self.assertFalse([a for a in self.calls() if a[0] == "logs"], "status chamou logs")

    def test_a_missing_workload_is_an_item_with_found_false(self):
        """SPEC-0089:UT-01 — um workload do alvo que não existe no cluster vira um item com found: false (status ok,
        sem pods dele); o que existe continua normal."""
        self.install()
        out = self.run_probe(probe_input("status", workloads=("Deployment/api", "Deployment/ghost")))
        self.assertEqual(out["status"], "ok", out)
        workloads = {i["workload"]: i for i in out["items"] if i.get("kind") == "workload"}
        self.assertEqual(workloads["Deployment/ghost"].get("found"), False, out)
        self.assertEqual(workloads["Deployment/api"].get("found"), True, out)
        self.assertFalse([i for i in out["items"] if i.get("kind") == "pod" and i["workload"] == "Deployment/ghost"])


# --------------------------------------------------------------------------- UT-02


class EventsTest(KubectlCase):
    def test_only_warnings_of_the_workload_and_its_pods_inside_the_window(self):
        """SPEC-0089:UT-02 — eventos Warning e Normal, dentro e fora da janela, de pods de api e de outros
        workloads: `events` de Deployment/api (janela 1800 s) devolve só os Warning de Pod/api-7f9c-aaaa (mensagem
        cortada em 300 caracteres) e de Deployment/api; nada de Normal, do Warning de 2 h atrás nem de worker ou
        billing."""
        self.install()
        out = self.run_probe(probe_input("events"))
        self.assertEqual(out["status"], "ok", out)
        for item in out["items"]:
            self.assertLessEqual(set(item), EVENT_KEYS, item)
        found = {(i.get("object"), i.get("reason")): i for i in out["items"]}
        self.assertEqual(set(found), {("Pod/api-7f9c-aaaa", "Unhealthy"),
                                      ("Deployment/api", "ProgressDeadlineExceeded")}, out)
        unhealthy = found[("Pod/api-7f9c-aaaa", "Unhealthy")]
        self.assertEqual(unhealthy.get("count"), 3)
        self.assertRegex(str(unhealthy.get("last_ts")), TS_RE)
        events = json.loads((CLUSTER / "events.json").read_text(encoding="utf-8"))["items"]
        original = next(e["message"] for e in events if e["reason"] == "Unhealthy")
        self.assertGreater(len(original), 300)
        self.assertLessEqual(len(unhealthy["message"]), 300)
        self.assertTrue(unhealthy["message"].startswith(original[:250]), unhealthy["message"])
        self.assertEqual(found[("Deployment/api", "ProgressDeadlineExceeded")].get("message"),
                         "Deployment api has timed out progressing.")
        self.assertIn("events", {words_of(a)[0] for a in self.calls() if a[0] == "get"})


# --------------------------------------------------------------------------- UT-03


class LogsTest(KubectlCase):
    def test_the_most_recent_lines_of_every_pod_and_container_with_truncation(self):
        """SPEC-0089:UT-03 — dois pods, dois containers e 300 linhas: `logs` com lines 100 devolve as 100 mais
        recentes (requests 201 a 300), cada uma com workload, pod, container, ts e line (sem o prefixo do kubectl),
        e truncated: true; uma única chamada `logs Deployment/api` com --all-containers --timestamps --prefix
        --since=1800s --tail."""
        self.install()
        out = self.run_probe(probe_input("logs", lines=100))
        self.assertEqual(out["status"], "ok", out)
        self.assertIs(out["truncated"], True, out)
        self.assertEqual(len(out["items"]), 100)
        numbers = set()
        for item in out["items"]:
            self.assertEqual(set(item), LOG_KEYS, item)
            self.assertEqual(item["workload"], "Deployment/api")
            self.assertIn(item["pod"], ("api-7f9c-aaaa", "api-7f9c-bbbb"))
            self.assertIn(item["container"], ("api", "proxy"))
            self.assertRegex(item["ts"], TS_RE)
            self.assertFalse(item["line"].startswith("[pod/"), item)
            self.assertNotRegex(item["line"], r"^\d{4}-\d{2}-\d{2}T", item)
            match = re.search(r"request (\d{3})", item["line"])
            self.assertIsNotNone(match, item)
            numbers.add(int(match.group(1)))
        self.assertEqual(numbers, set(range(201, 301)))
        self.assertEqual({(i["pod"], i["container"]) for i in out["items"]},
                         {("api-7f9c-aaaa", "api"), ("api-7f9c-aaaa", "proxy"), ("api-7f9c-bbbb", "api"),
                          ("api-7f9c-bbbb", "proxy")})
        logs = [a for a in self.calls() if a[0] == "logs"]
        self.assertEqual(len(logs), 1, self.calls())
        self.assertEqual([w.lower() for w in words_of(logs[0])], ["deployment/api"])

    def test_fewer_lines_than_the_limit_are_not_truncated(self):
        """SPEC-0089:UT-03 — com lines 2000 (acima das 300 linhas) saem as 300, truncated: false."""
        self.install()
        out = self.run_probe(probe_input("logs", lines=2000))
        self.assertEqual(out["status"], "ok", out)
        self.assertEqual(len(out["items"]), 300)
        self.assertIs(out["truncated"], False)


# --------------------------------------------------------------------------- UT-04


class ErrorTest(KubectlCase):
    def test_kubectl_failures_become_contract_errors_without_the_context(self):
        """SPEC-0089:UT-04 — Forbidden, contexto inexistente (o kubectl cita o nome do contexto) e timeout, em cada
        verbo: status error, items [], a mensagem do contrato e o nome do contexto fora da saída."""
        for fail, message in FAIL_MESSAGES.items():
            for verb in ("status", "events", "logs"):
                with self.subTest(fail=fail, verb=verb):
                    self.record.unlink(missing_ok=True)
                    self.install(fail)
                    out = self.run_probe(probe_input(verb))
                    self.assertError(out, message)
                    self.assertTrue(self.calls(), "o kubectl não foi chamado")

    def test_without_kubectl_on_the_path(self):
        """SPEC-0089:UT-04 — sem kubectl no PATH: status error, items [] e "kubectl não encontrado", em cada verbo."""
        for verb in ("status", "events", "logs"):
            with self.subTest(verb=verb):
                out = self.run_probe(probe_input(verb))
                self.assertError(out, "kubectl não encontrado")


# --------------------------------------------------------------------------- UT-05


class AllowListTest(KubectlCase):
    def test_secret_configmap_and_verbs_outside_the_list_are_refused_without_any_call(self):
        """SPEC-0089:UT-05 — workload Secret/x ou ConfigMap/x (em cada verbo) e verbos exec, delete, describe e
        port-forward: status error "chamada não permitida" e nenhuma chamada ao kubectl."""
        cases = [probe_input(verb, workloads=(workload,)) for workload in ("Secret/x", "ConfigMap/x")
                 for verb in ("status", "events", "logs")]
        cases += [probe_input(verb) for verb in ("exec", "delete", "describe", "port-forward")]
        self.install()
        for data in cases:
            with self.subTest(verb=data["verb"], workloads=data["target"]["workloads"]):
                self.record.unlink(missing_ok=True)
                out = self.run_probe(data)
                self.assertError(out, REFUSED)
                self.assertEqual(self.calls(), [], "o kubectl rodou numa chamada recusada")

    def test_a_workload_name_that_looks_like_an_option_never_becomes_one(self):
        """SPEC-0089:UT-05 — nomes de workload com cara de opção ou de outro recurso não viram argumento do
        kubectl: toda chamada continua na lista fechada (sem --raw, -A, secrets…)."""
        self.install()
        for workload in ("Deployment/--raw=/api/v1/secrets", "Deployment/-A", "Deployment/api secrets"):
            for verb in ("status", "events", "logs"):
                with self.subTest(workload=workload, verb=verb):
                    self.record.unlink(missing_ok=True)
                    out = self.run_probe(probe_input(verb, workloads=(workload,)))
                    self.assertIn(out["status"], ("ok", "error"))
                    for argv in self.calls():
                        self.assertFalse([a for a in argv if a in ("-A", "--all-namespaces") or "raw" in a], argv)

    def test_every_call_of_every_verb_is_get_or_logs_of_an_allowed_resource(self):
        """SPEC-0089:UT-05 — status, events e logs de Deployment/api e StatefulSet/db: cada argv começa com get ou
        logs, com recurso da lista, --context e -n da entrada, --request-timeout e -o json no get."""
        self.install()
        for verb in ("status", "events", "logs"):
            with self.subTest(verb=verb):
                self.record.unlink(missing_ok=True)
                self.run_probe(probe_input(verb, workloads=("Deployment/api", "StatefulSet/db")))
                self.assertTrue(self.calls(), "o kubectl não foi chamado")


# --------------------------------------------------------------------------- IT-01


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox()
        try:
            build_probe_atlas(cls.box)
        except BaseException:
            cls.box.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.box.cleanup()

    def setUp(self):
        name = self.id().rsplit(".", 1)[-1]
        self.bin = self.box.root / "bin" / name
        self.record = self.box.root / "calls" / f"{name}.jsonl"
        self.record.parent.mkdir(parents=True, exist_ok=True)
        install_kubectl(self.bin, self.record)
        adapter = '    kubernetes:\n      verbs: ["status", "events", "logs"]\n      timeout: 60\n'
        self.box.write_local(local_text(self.box.atlas, probes_yaml([adapter])))
        self.log_path = self.box.config_home / "probes.log"
        self.log_path.unlink(missing_ok=True)

    def probe(self, *args):
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        result = self.box.run("probe", *args, env=env)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def log(self):
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_status_through_the_core_with_the_bundled_adapter(self):
        """SPEC-0089:IT-01 — atlas temporário com o mapa de acesso, probes ligadas com o adaptador kubernetes sem
        `command` (o da skill) e o kubectl falso no PATH: `atlas.py probe runtime status --service api --env dev
        --json` sai com 0, a saída passa no validador probe@1 do núcleo e traz Deployment/api com rollout_complete
        true e os 3 pods com acme/api:1.4.2@sha256:…; o kubectl recebeu o contexto e o namespace do alvo; o
        probes.log tem a linha da probe (adaptador kubernetes, ok, exit 0); o contexto não aparece na saída nem no
        registro; nada muda no atlas."""
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        before = snapshot(self.box.atlas)
        result = self.probe("runtime", "status", "--service", "api", "--env", "dev", "--json")
        self.assertEqual(result.returncode, 0, output(result))
        out = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(out), [], out)
        self.assertEqual((out["adapter"], out["capability"], out["verb"], out["status"]),
                         ("kubernetes", "runtime", "status", "ok"), out)
        workloads = {i["workload"]: i for i in out["items"] if i.get("kind") == "workload"}
        self.assertEqual(set(workloads), {"Deployment/api"})
        self.assertIs(workloads["Deployment/api"].get("rollout_complete"), True)
        pods = {i["pod"]: i for i in out["items"] if i.get("kind") == "pod"}
        self.assertEqual(set(pods), set(API_PODS))
        for item in pods.values():
            self.assertEqual(item.get("images"), [API_IMAGE])
        calls = read_calls(self.record)
        self.assertTrue(calls, "o kubectl falso não foi chamado")
        data = probe_input("status", context=CONTEXTS["cluster-dev"], namespace="api-dev")
        for argv in calls:
            self.assertEqual(call_problems(argv, data), [], argv)
        lines = self.log()
        self.assertEqual(len(lines), 1, lines)
        self.assertEqual({k: lines[0].get(k) for k in ("service", "environment", "capability", "verb", "adapter",
                                                       "status", "exit")},
                         {"service": "api", "environment": "dev", "capability": "runtime", "verb": "status",
                          "adapter": "kubernetes", "status": "ok", "exit": 0})
        self.assertNotIn(CONTEXTS["cluster-dev"], output(result) + self.log_path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot(self.box.atlas), before)

    def test_log_lines_go_through_the_core_redaction(self):
        """SPEC-0089:IT-01 — `atlas.py probe runtime logs ... --json` com o adaptador da skill: sai com 0, saída
        probe@1 válida com itens de log (ts e line) e o e-mail de uma linha mascarado pelo núcleo."""
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        result = self.probe("runtime", "logs", "--service", "api", "--env", "dev", "--lines", "50", "--json")
        self.assertEqual(result.returncode, 0, output(result))
        out = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(out), [], out)
        self.assertEqual(len(out["items"]), 50)
        self.assertIs(out["truncated"], True)
        self.assertTrue(all("ts" in i and "line" in i for i in out["items"]), out)
        self.assertNotIn(EMAIL, result.stdout)
        self.assertIn("[REDACTED]", result.stdout)


# --------------------------------------------------------------------------- CT-01


class ContractTest(KubectlCase):
    def test_describe_follows_probe_1(self):
        """SPEC-0089:CT-01 — `kubernetes.py --describe` imprime exatamente a descrição do contrato, aceita pelo
        validate_probe_describe do núcleo, sem chamar o kubectl."""
        self.install()
        result = self.adapter("--describe")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        self.assertEqual(data, DESCRIBE)
        self.assertEqual(f("validate_probe_describe")(data), [])
        self.assertEqual(self.calls(), [])

    def test_every_output_passes_the_core_validator(self):
        """SPEC-0089:CT-01 — as saídas de status, events e logs, de um erro do kubectl (Forbidden) e de uma chamada
        recusada passam no validate_probe_output do núcleo (e as entradas usadas no validate_probe_input)."""
        cases = [("", probe_input(verb)) for verb in ("status", "events", "logs")]
        cases += [("forbidden", probe_input("status")), ("", probe_input("status", workloads=("Secret/x",)))]
        for fail, data in cases:
            with self.subTest(fail=fail, verb=data["verb"], workloads=data["target"]["workloads"]):
                self.assertEqual(f("validate_probe_input")(data), [])
                self.record.unlink(missing_ok=True)
                self.install(fail)
                out = self.run_probe(data)  # já confere validate_probe_output
                self.assertIn(out["status"], ("ok", "error"))


if __name__ == "__main__":
    unittest.main()
