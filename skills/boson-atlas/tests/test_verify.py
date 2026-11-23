"""Verificação depois do deploy: `verify snapshot` (foto antes do merge, fora do atlas) e `verify compare` (entrega,
runtime e logs contra a foto e a imagem esperada, com veredito) — SPEC-0090: CH-01, UT-01 a UT-06, IT-01 e CT-01;
ADR-0024, ADR-0023; sobre o núcleo do probe (SPEC-0088) e o adaptador Kubernetes (SPEC-0089).

Contrato (seção 6 da SPEC-0090, com os Esclarecimentos da Emenda v2) que estes testes fixam:

    atlas.py verify snapshot --service <id> --env <ambiente> --out <arquivo> [--since 30m] [--confirm-production]
        por deployment do serviço no ambiente: probe runtime status, events e logs --summary (janela --since);
        grava {"contract": "verify@1", "service", "environment", "taken_at", "deployments": {<id>: {"images",
        "ready", "desired", "restarts": {<pod>: n}, "warnings": ["<motivo>|<objeto sem o sufixo do pod>"],
        "error_signatures": {<assinatura>: n}}}, "not_verified": [{"deployment", "check", "reason"}]}
        exits: 0 gravado · 2 argumento inválido (inclusive --out dentro da pasta do atlas) · 3 sem configuração ·
        4 recusado (regras do probe)
    atlas.py verify compare --service <id> --env <ambiente> --expect-image <imagem> [--baseline <arquivo>]
        [--window 10m] [--max-new-errors 0] [--max-new-restarts 0] [--confirm-production] [--json]
        checks por deployment: delivery, runtime e logs, cada um {"deployment", "check", "status": ok | failed |
        not_verified, "evidence": {...}, "reason"}; veredito degradou (algum failed) > inconclusivo (algum
        not_verified) > passou; --json {"contract": "verify@1", "verdict", "checks", "suggestion"}
        exits: 0 passou · 1 degradou · 5 inconclusivo · 2 argumento inválido · 3 sem configuração · 4 recusado
    Emenda v2: logs com truncated: true e nenhum item -> logs not_verified ("nenhum pod respondeu"), nunca ok;
        status com found: false -> runtime failed; o verify chama o caminho do probe (mesmas proteções e registro).

Leituras conservadoras desta suíte (ADR-0024: evidência que falta nunca vira `passou`; listadas no relatório do
test-writer para o Architect):
    - CH-01 tem duas partes: a guarda (os comandos de hoje, inclusive o `probe`, dão as mesmas saídas) passa agora; a
      recusa do `verify` com as probes desligadas (exit 4) só passa com o subcomando.
    - "Assinaturas de erro" = as de nível error do `--summary`; uma assinatura nova de nível info não conta.
    - A foto não guarda nenhuma linha de log inteira (UT-01 e o exemplo do contrato: error_signatures é
      assinatura -> contagem), nem o contexto do cluster.
    - Warning novo = "<motivo>|<objeto sem o sufixo do pod>" ausente da foto: BackOff em outro pod do mesmo
      workload (api-7f9c-bbbb no lugar de api-7f9c-aaaa) é o mesmo warning "BackOff|Pod/api" do UT-03.
    - Restarts novos = os de agora menos os da foto, por pod; pod que não estava na foto conta desde 0.
    - Probe que volta com status error, quebra (exit do adaptador) ou é recusada por verbo deixa as verificações
      que dependem dela em not_verified, com motivo (não exit 4 do comando inteiro): status -> delivery e
      runtime; logs -> logs.
    - Com found: false, a delivery também não é ok.
    - Foto cujo logs ficou em not_verified não serve de linha de base para os logs: a verificação logs daquele
      deployment não fica ok.
    - --out dentro do atlas (direto, numa subpasta ou por ..) e --expect-image sem tag nem digest são argumento
      inválido (exit 2) antes de qualquer probe rodar; --baseline ausente, que não é JSON, com chave desconhecida
      ou com contract diferente de verify@1 também saem com 2.
    - Produção sem --confirm-production: exit 4 sem nenhuma execução (mode "run") do adaptador; o --describe pode
      rodar, como no `probe`.
    - A janela dos logs é a da opção: no compare, limits.since_seconds do logs = --window (600 por padrão); no
      snapshot, = --since (1800 por padrão).
    - CT-01: o validador verify@1 desta suíte é o do próprio teste (chaves e tipos do contrato); references/verify.md
      tem de trazer pelo menos um exemplo de foto e um de saída --json (blocos ```json com "contract": "verify@1"),
      e o exemplo de foto é aceito pelo compare como --baseline.
    - A sugestão (só em degradou) cita o repositório de configuração do deployment (acme/iac) e não traz comando
      (kubectl, argocd, helm, git, linha começando com $).

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); fotos só em pastas temporárias;
sem rede; nenhum kubectl de verdade (o adaptador falso fixtures/fake-probes/scripted.py nos testes unitários e o
kubectl falso da SPEC-0089 no IT-01, com o PATH começando pela pasta dele); nomes genéricos (acme, api).
"""
import copy
import json
import os
import re
import sys
import unittest

from helpers import SKILL, TESTS, Sandbox, output, snapshot
from test_access_map import collectors_yaml, environments_yaml, resource
from test_probe import (
    CONTEXTS,
    DISABLED_PROBES,
    ENVIRONMENTS,
    GOLDEN,
    adapter_yaml,
    build_probe_atlas,
    ch01_outputs,
    local_text,
    probe_apps,
    probes_yaml,
    without_probe_additions,
)
from test_probe_kubernetes import install_kubectl, read_calls

SPEC = "SPEC-0090"
FAKES = TESTS / "fixtures" / "fake-probes"
SCRIPTED = FAKES / "scripted.py"
VERIFY_DOC = SKILL / "references" / "verify.md"
VERIFY_PATTERN = r"^(?:dev|qa|stg|sbx)-(?P<service>api)(?:-[a-z]+)?$"
OLD_DIGEST = "sha256:" + "0a1b" * 16
NEW_DIGEST = "sha256:" + "9f8e" * 16
OLD_IMAGE = f"acme/api:1.4.1@{OLD_DIGEST}"
NEW_IMAGE = f"acme/api:1.4.2@{NEW_DIGEST}"
DEPLOYMENTS = ("dev-api", "dev-api-blue")
WORKLOADS = {"dev-api": "Deployment/api", "dev-api-blue": "Deployment/api-blue"}
PODS = {"dev-api": ("api-7f9c-aaaa", "api-7f9c-bbbb", "api-7f9c-cccc"),
        "dev-api-blue": ("api-blue-5c6d-aaaa", "api-blue-5c6d-bbbb")}
CHECKS = ("delivery", "runtime", "logs")
STATUSES = ("ok", "failed", "not_verified")
VERDICT_EXIT = {"passou": 0, "degradou": 1, "inconclusivo": 5}
READ_VERBS = {"status", "events", "logs"}
NO_BASELINE = "sem foto de antes"
NO_POD = "nenhum pod respondeu"
CONFIG_REPO = "acme/iac"
DISABLED = "probes desligadas"
TS = "2026-11-23T10:00:00Z"
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$")
SNAPSHOT_KEYS = {"contract", "service", "environment", "taken_at", "deployments", "not_verified"}
SNAPSHOT_DEPLOYMENT_KEYS = {"images", "ready", "desired", "restarts", "warnings", "error_signatures"}
NOT_VERIFIED_KEYS = {"deployment", "check", "reason"}
RESULT_KEYS = {"contract", "verdict", "checks", "suggestion"}
CHECK_KEYS = {"deployment", "check", "status", "evidence", "reason"}
COMMAND_RE = re.compile(r"\bkubectl\b|\bargocd\b|\bhelm\b|\bgit (?:revert|push|reset|checkout)\b|^\s*\$ ", re.MULTILINE)
OLD_SIGNATURE = "ERROR user <n> not found"


def fake_token():
    return "ghp_" + "Vr7" * 12  # montado em tempo de execução, como nos coletores falsos


def fake_email():
    return "pessoa.verify" + "@" + "example.com"


# --------------------------------------------------------------------------- estado do adaptador falso


def workload_item(deployment, found=True, ready=None, complete=True):
    label = WORKLOADS[deployment]
    if not found:
        return {"kind": "workload", "workload": label, "found": False, "rollout_complete": False}
    desired = len(PODS[deployment])
    ready = desired if ready is None else ready
    return {"kind": "workload", "workload": label, "found": True, "desired": desired, "updated": desired,
            "ready": ready, "available": ready, "rollout_complete": complete}


def pod_item(deployment, pod, image=NEW_IMAGE, ready=True, restarts=0, last=""):
    return {"kind": "pod", "workload": WORKLOADS[deployment], "pod": pod, "phase": "Running", "ready": ready,
            "restarts": restarts, "images": [image], "last_termination": last}


def event_item(reason, obj, count=1):
    return {"reason": reason, "object": obj, "count": count, "last_ts": TS, "message": f"{reason} em {obj}"}


def log_item(deployment, line, pod=None):
    return {"workload": WORKLOADS[deployment], "pod": pod or PODS[deployment][0], "container": "api", "ts": TS,
            "line": line}


def deployment_state(deployment, image=NEW_IMAGE, images=None, restarts=None, not_ready=(), complete=True,
                     found=True, pods=None, events=(), logs=None, status=None, events_answer=None, logs_answer=None):
    """Respostas do adaptador falso para um deployment: status (workload + pods), events e logs. `images` e
    `restarts` são {pod: valor}; `status`, `events_answer` e `logs_answer` trocam a resposta inteira do verbo
    (por exemplo {"error": "..."} ou {"items": [], "truncated": True})."""
    pods = PODS[deployment] if pods is None else pods
    images, restarts = images or {}, restarts or {}
    ready = len([p for p in pods if p not in not_ready])
    items = [workload_item(deployment, found=found, ready=ready, complete=complete)]
    if found:
        items += [pod_item(deployment, pod, image=images.get(pod, image), ready=pod not in not_ready,
                           restarts=restarts.get(pod, 0)) for pod in pods]
    if logs is None:
        logs = [f"INFO request {n} ok" for n in range(1, 4)]
    return {"status": status or {"items": items, "truncated": False},
            "events": events_answer or {"items": [event_item(*e) for e in events], "truncated": False},
            "logs": logs_answer or {"items": [log_item(deployment, line) for line in logs], "truncated": False}}


def baseline_data(**overrides):
    """Foto verify@1 do estado "antes" (imagem 1.4.1), um deployment por chave; overrides[<deployment>] atualiza os
    campos dele; overrides["not_verified"] é a lista."""
    deployments = {}
    for deployment in DEPLOYMENTS:
        pods = PODS[deployment]
        entry = {"images": [OLD_IMAGE], "ready": len(pods), "desired": len(pods),
                 "restarts": {pod: 0 for pod in pods}, "warnings": [], "error_signatures": {}}
        entry.update(overrides.get(deployment, {}))
        deployments[deployment] = entry
    return {"contract": "verify@1", "service": "api", "environment": "dev", "taken_at": "2026-11-23T09:00:00Z",
            "deployments": deployments, "not_verified": list(overrides.get("not_verified", []))}


# --------------------------------------------------------------------------- validador verify@1 (CT-01)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def snapshot_problems(data) -> list:
    """Problemas de uma foto frente ao contrato verify@1 (seção 6); [] = válida."""
    if not isinstance(data, dict):
        return ["a foto não é um objeto"]
    problems = []
    if set(data) != SNAPSHOT_KEYS:
        problems.append(f"chaves {sorted(data)} != {sorted(SNAPSHOT_KEYS)}")
    if data.get("contract") != "verify@1":
        problems.append(f"contract {data.get('contract')!r}")
    for key in ("service", "environment"):
        if not isinstance(data.get(key), str) or not data.get(key):
            problems.append(f"{key} não é texto")
    if not isinstance(data.get("taken_at"), str) or not ISO_UTC.match(data.get("taken_at")):
        problems.append(f"taken_at não é ISO UTC: {data.get('taken_at')!r}")
    deployments = data.get("deployments")
    if not isinstance(deployments, dict):
        problems.append("deployments não é um objeto")
        deployments = {}
    for name, entry in deployments.items():
        if not isinstance(entry, dict) or set(entry) != SNAPSHOT_DEPLOYMENT_KEYS:
            problems.append(f"deployments.{name}: chaves {sorted(entry) if isinstance(entry, dict) else entry}")
            continue
        if not isinstance(entry["images"], list) or not all(isinstance(i, str) for i in entry["images"]):
            problems.append(f"deployments.{name}.images")
        for key in ("ready", "desired"):
            if not _is_int(entry[key]):
                problems.append(f"deployments.{name}.{key}")
        for key in ("restarts", "error_signatures"):
            value = entry[key]
            if not isinstance(value, dict) or not all(isinstance(k, str) and _is_int(v) for k, v in value.items()):
                problems.append(f"deployments.{name}.{key}")
        if not isinstance(entry["warnings"], list) or not all(isinstance(w, str) and "|" in w
                                                              for w in entry["warnings"]):
            problems.append(f"deployments.{name}.warnings")
    not_verified = data.get("not_verified")
    if not isinstance(not_verified, list):
        problems.append("not_verified não é uma lista")
        not_verified = []
    for item in not_verified:
        if not isinstance(item, dict) or set(item) != NOT_VERIFIED_KEYS or item.get("check") not in CHECKS \
                or not isinstance(item.get("reason"), str) or not item.get("reason"):
            problems.append(f"not_verified: {item!r}")
    return problems


def result_problems(data) -> list:
    """Problemas de uma saída `verify compare --json` frente ao contrato verify@1; [] = válida."""
    if not isinstance(data, dict):
        return ["a saída não é um objeto"]
    problems = []
    if not {"contract", "verdict", "checks"} <= set(data) <= RESULT_KEYS:
        problems.append(f"chaves {sorted(data)}")
    if data.get("contract") != "verify@1":
        problems.append(f"contract {data.get('contract')!r}")
    if data.get("verdict") not in VERDICT_EXIT:
        problems.append(f"verdict {data.get('verdict')!r}")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        return problems + ["checks não é uma lista com itens"]
    for item in checks:
        if not isinstance(item, dict) or not {"deployment", "check", "status", "evidence"} <= set(item) <= CHECK_KEYS:
            problems.append(f"check com chaves erradas: {item!r}")
            continue
        if item["check"] not in CHECKS or item["status"] not in STATUSES:
            problems.append(f"check ou status fora do contrato: {item!r}")
        if not isinstance(item["evidence"], dict):
            problems.append(f"evidence não é objeto: {item!r}")
        if item["status"] == "not_verified" and not (isinstance(item.get("reason"), str) and item["reason"]):
            problems.append(f"not_verified sem motivo: {item!r}")
    statuses = {item.get("status") for item in checks if isinstance(item, dict)}
    expected = "degradou" if "failed" in statuses else "inconclusivo" if "not_verified" in statuses else "passou"
    if data.get("verdict") != expected:
        problems.append(f"verdict {data.get('verdict')!r} fora da regra (esperado {expected})")
    suggestion = data.get("suggestion")
    if data.get("verdict") == "degradou":
        if not isinstance(suggestion, str) or not suggestion.strip():
            problems.append("degradou sem suggestion")
    elif suggestion not in (None, ""):
        problems.append(f"suggestion fora de degradou: {suggestion!r}")
    return problems


def doc_examples() -> list:
    """Os blocos ```json de references/verify.md com "contract": "verify@1"."""
    text = VERIFY_DOC.read_text(encoding="utf-8")
    found = []
    for block in re.findall(r"```json[^\n]*\n(.*?)```", text, re.DOTALL):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("contract") == "verify@1":
            found.append(data)
    return found


# --------------------------------------------------------------------------- atlas e caso base


def verify_apps():
    """As Applications do probe (dev-api, qa-api, stg-api, sbx-api) mais dev-api-blue: dois deployments do serviço
    api no ambiente dev (Deployment/api e Deployment/api-blue)."""
    apps = probe_apps()
    blue = copy.deepcopy(apps[0])
    blue["metadata"]["name"] = "dev-api-blue"
    blue["status"]["resources"] = [resource("Deployment", "api-blue")]
    return apps + [blue]


def build_verify_atlas(box: Sandbox):
    out = box.init(mode="local")
    assert out.returncode == 0, output(out)
    inputs = box.atlas.parent / "inputs"
    inputs.mkdir(exist_ok=True)
    (inputs / "apps.json").write_text(json.dumps(verify_apps()), encoding="utf-8")
    command = ["python3", "{skill}/assets/collectors/argocd.py", "--from", "argocd", "--input",
               "{atlas}/../inputs/apps.json", "--service-pattern", VERIFY_PATTERN]
    (box.atlas / "atlas-config.yml").write_text(collectors_yaml([("argocd", "delivery", command)])
                                                 + environments_yaml(ENVIRONMENTS), encoding="utf-8")
    box.write_local(local_text(box.atlas))
    for step in ("scan", "build"):
        out = box.run(step)
        assert out.returncode == 0, f"{step} falhou: {output(out)}"
    graph = json.loads((box.atlas / "graph.json").read_text(encoding="utf-8"))
    dev = {e["from"] for e in graph["edges"] if e["type"] == "runs_in" and e["to"] == "environment:dev"}
    assert {f"deployment:{d}" for d in DEPLOYMENTS} <= dev, f"atlas sem os dois deployments de dev: {dev}"


class VerifyCase(unittest.TestCase):
    """Um atlas por classe (o verify nunca escreve no atlas); cada teste tem a própria configuração local, o próprio
    cenário do adaptador falso, o próprio registro de processos e a própria pasta da tarefa (onde ficam as fotos)."""

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox()
        try:
            build_verify_atlas(cls.box)
        except BaseException:
            cls.box.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.box.cleanup()

    def setUp(self):
        name = self.id().rsplit(".", 1)[-1]
        self.cfg = self.box.root / "cfg" / name
        self.record = self.box.root / "calls" / f"{name}.jsonl"
        self.record.parent.mkdir(parents=True, exist_ok=True)
        self.task = self.box.root / "task" / name
        self.task.mkdir(parents=True, exist_ok=True)
        self.scenario = self.task / "scenario.json"
        self.set_state()
        self.configure()

    # -- configuração e estado

    def configure(self, verbs=("status", "events", "logs"), enabled=True, present=True):
        command = [sys.executable, str(SCRIPTED), "--record", str(self.record), "--scenario", str(self.scenario)]
        text = probes_yaml([adapter_yaml("fake", command, verbs=verbs, timeout=60)], enabled=enabled) if present else ""
        self.box.write_local(local_text(self.box.atlas, text), config_home=self.cfg)

    def set_state(self, **states):
        """states[<deployment>] = deployment_state(...); os que faltam ficam saudáveis com a imagem nova."""
        data = {d: states.get(d) or deployment_state(d) for d in DEPLOYMENTS}
        data["*"] = deployment_state("dev-api")
        self.scenario.write_text(json.dumps(data), encoding="utf-8")

    def write_baseline(self, data, name="foto.json"):
        path = self.task / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    # -- execução

    def calls(self, mode=None):
        if not self.record.exists():
            return []
        rows = [json.loads(line) for line in self.record.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [r for r in rows if mode is None or r["mode"] == mode]

    def log(self):
        path = self.cfg / "probes.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def verify(self, *args, config_home=None):
        """Roda `atlas.py verify ...`; em toda execução (UT-06): sem traceback, o subcomando existe, a pasta do atlas
        fica igual, o adaptador só recebeu verbos de leitura de runtime e o contexto do cluster não sai."""
        before = snapshot(self.box.atlas)
        result = self.box.run("verify", *args, config_home=config_home or self.cfg)
        text = output(result)
        self.assertNotIn("Traceback", text, text)
        self.assertNotIn("invalid choice", text, f"atlas.py ainda não tem o subcomando verify ({SPEC})")
        self.assertEqual(snapshot(self.box.atlas), before, "o verify mudou a pasta do atlas (ADR-0024)")
        for call in self.calls("run"):
            data = call["input"]
            self.assertEqual(data.get("capability"), "runtime", call)
            self.assertIn(data.get("verb"), READ_VERBS, call)
        for context in CONTEXTS.values():
            self.assertNotIn(context, text)
        return result

    def take(self, out=None, *extra, env="dev"):
        out = out or self.task / "foto.json"
        return self.verify("snapshot", "--service", "api", "--env", env, "--out", out, *extra)

    def compare(self, *extra, baseline=True, expect=NEW_IMAGE, env="dev", as_json=True):
        args = ["compare", "--service", "api", "--env", env, "--expect-image", expect]
        if baseline is True:
            baseline = self.write_baseline(baseline_data())
        if baseline:
            args += ["--baseline", baseline]
        return self.verify(*args, *extra, *(["--json"] if as_json else []))

    def result(self, run, verdict=None):
        """A saída --json validada contra o verify@1; com `verdict`, confere o veredito e o exit dele."""
        try:
            data = json.loads(run.stdout)
        except ValueError:
            self.fail(f"saída --json não é JSON (exit {run.returncode}): {output(run)}")
        self.assertEqual(result_problems(data), [], data)
        self.assertEqual(run.returncode, VERDICT_EXIT[data["verdict"]], output(run))
        pairs = sorted((c["deployment"], c["check"]) for c in data["checks"])
        self.assertEqual(pairs, sorted((d, c) for d in DEPLOYMENTS for c in CHECKS), data["checks"])
        if verdict is not None:
            self.assertEqual(data["verdict"], verdict, json.dumps(data, ensure_ascii=False, indent=1))
        return data

    def check(self, data, deployment, name):
        found = [c for c in data["checks"] if c["deployment"] == deployment and c["check"] == name]
        self.assertEqual(len(found), 1, data["checks"])
        return found[0]

    def assertExit(self, run, code):
        self.assertEqual(run.returncode, code, output(run))

    def assertNoRun(self):
        self.assertEqual(self.calls("run"), [], "o adaptador rodou")


# --------------------------------------------------------------------------- CH-01


class CharacterizationTest(unittest.TestCase):
    def test_todays_commands_give_todays_outputs(self):
        """SPEC-0090:CH-01 — guarda: com probes.enabled: false e um adaptador declarado, scan, build, context, doctor,
        lint e config --json dão as saídas do golden de antes das probes (tirando o que a SPEC-0088 acrescentou);
        nenhum adaptador roda."""
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        got = without_probe_additions(ch01_outputs(DISABLED_PROBES))
        self.assertFalse(got.pop("recorded"), "um adaptador rodou com probes desligadas")
        for key in sorted(golden):
            self.assertEqual(got[key], golden[key], key)


class ProbeStillWorksTest(VerifyCase):
    def test_probe_runs_as_today(self):
        """SPEC-0090:CH-01 — guarda: `probe runtime status --service api --env dev --json` com probes ligadas sai com
        0 e devolve os itens do adaptador (o deployment dev-api, primeiro pelo id), como antes do verify."""
        self.set_state(**{"dev-api": deployment_state("dev-api", image=OLD_IMAGE)})
        run = self.box.run("probe", "runtime", "status", "--service", "api", "--env", "dev", "--json",
                           config_home=self.cfg)
        self.assertExit(run, 0)
        data = json.loads(run.stdout)
        self.assertEqual((data["contract"], data["status"], data["verb"]), ("probe@1", "ok", "status"))
        pods = [i for i in data["items"] if i.get("kind") == "pod"]
        self.assertEqual(sorted(p["pod"] for p in pods), list(PODS["dev-api"]))
        self.assertEqual({tuple(p["images"]) for p in pods}, {(OLD_IMAGE,)})
        self.assertEqual([c["input"]["target"]["deployment"] for c in self.calls("run")], ["dev-api"])


class DisabledVerifyTest(VerifyCase):
    def test_verify_without_probes_is_refused(self):
        """SPEC-0090:CH-01 — sem a chave probes, e com probes.enabled: false, `verify snapshot` e `verify compare` saem
        com 4, "probes desligadas", sem rodar o adaptador e sem gravar a foto."""
        out = self.task / "foto.json"
        for name, opts in (("sem a chave", {"present": False}), ("enabled: false", {"enabled": False})):
            with self.subTest(variant=name):
                self.configure(**opts)
                run = self.take(out)
                self.assertExit(run, 4)
                self.assertIn(DISABLED, output(run))
                self.assertFalse(out.exists(), "a foto foi gravada com as probes desligadas")
                run = self.compare()
                self.assertExit(run, 4)
                self.assertIn(DISABLED, output(run))
                self.assertNoRun()


# --------------------------------------------------------------------------- UT-01


class SnapshotTest(VerifyCase):
    def snapshot_state(self):
        token, email = fake_token(), fake_email()
        raw = ["INFO request 7 ok", "ERROR user 123 not found", "ERROR user 456 not found",
               f"ERROR auth failed for {email} with token={token}", "INFO request 8 ok"]
        state = deployment_state(
            "dev-api", image=OLD_IMAGE, restarts={"api-7f9c-bbbb": 1},
            events=[("BackOff", "Pod/api-7f9c-bbbb", 7), ("FailedMount", "Pod/api-7f9c-cccc", 2)], logs=raw)
        self.set_state(**{"dev-api": state, "dev-api-blue": deployment_state("dev-api-blue", image=OLD_IMAGE)})
        return raw, token, email

    def test_snapshot_has_state_events_and_signatures_without_log_lines(self):
        """SPEC-0090:UT-01 — 3 pods prontos com a imagem 1.4.1, 2 eventos Warning e logs com 2 assinaturas de erro:
        `verify snapshot` sai com 0 e grava uma foto verify@1 com as imagens, réplicas prontas e desejadas, restarts
        por pod, os 2 warnings ("<motivo>|...") e as assinaturas de erro com contagem (a de nível info fica fora);
        nenhuma linha de log inteira, nem o e-mail, o token ou o contexto do cluster; um probe de status, events e
        logs por deployment, com os logs na janela --since (30m por padrão)."""
        raw, token, email = self.snapshot_state()
        out = self.task / "foto.json"
        run = self.take(out)
        self.assertExit(run, 0)
        self.assertTrue(out.is_file(), "verify snapshot não gravou o --out")
        text = out.read_text(encoding="utf-8")
        data = json.loads(text)
        self.assertEqual(snapshot_problems(data), [], data)
        self.assertEqual((data["service"], data["environment"]), ("api", "dev"))
        self.assertEqual(sorted(data["deployments"]), sorted(DEPLOYMENTS))
        self.assertEqual(data["not_verified"], [])
        api = data["deployments"]["dev-api"]
        self.assertEqual(api["images"], [OLD_IMAGE])
        self.assertEqual((api["ready"], api["desired"]), (3, 3))
        self.assertEqual(api["restarts"], {"api-7f9c-aaaa": 0, "api-7f9c-bbbb": 1, "api-7f9c-cccc": 0})
        self.assertEqual(sorted(w.split("|", 1)[0] for w in api["warnings"]), ["BackOff", "FailedMount"])
        self.assertTrue(all("Pod/" in w for w in api["warnings"]), api["warnings"])
        self.assertEqual(len(api["error_signatures"]), 2, api["error_signatures"])
        self.assertEqual(api["error_signatures"].get(OLD_SIGNATURE), 2, api["error_signatures"])
        self.assertFalse([s for s in api["error_signatures"] if s.startswith("INFO")], api["error_signatures"])
        for line in raw:
            self.assertNotIn(line, text, "a foto guardou uma linha de log inteira")
        for secret in (token, email, *CONTEXTS.values()):
            self.assertNotIn(secret, text)
        runs = self.calls("run")
        by_deployment = {}
        for call in runs:
            by_deployment.setdefault(call["input"]["target"]["deployment"], []).append(call["input"]["verb"])
        self.assertEqual({d: sorted(v) for d, v in by_deployment.items()},
                         {d: ["events", "logs", "status"] for d in DEPLOYMENTS})
        logs = [c["input"] for c in runs if c["input"]["verb"] == "logs"]
        self.assertEqual({c["limits"]["since_seconds"] for c in logs}, {1800})

    def test_snapshot_since_option_sets_the_log_window(self):
        """SPEC-0090:UT-01 — `--since 15m` vira limits.since_seconds 900 na probe de logs."""
        self.snapshot_state()
        self.assertExit(self.take(None, "--since", "15m"), 0)
        logs = [c["input"] for c in self.calls("run") if c["input"]["verb"] == "logs"]
        self.assertTrue(logs)
        self.assertEqual({c["limits"]["since_seconds"] for c in logs}, {900})

    def test_out_inside_the_atlas_exits_2_and_writes_nothing(self):
        """SPEC-0090:UT-01 — `--out` dentro da pasta do atlas (na raiz, numa subpasta, ou fora com .. que volta para
        dentro) sai com 2, não cria arquivo e nenhuma probe roda (a pasta do atlas fica igual)."""
        self.snapshot_state()
        outside = self.box.root / "fora"
        outside.mkdir(exist_ok=True)
        paths = [self.box.atlas / "foto.json", self.box.atlas / "snapshots" / "foto.json",
                 outside / ".." / self.box.atlas.relative_to(self.box.root) / "foto.json"]
        for path in paths:
            with self.subTest(path=str(path)):
                run = self.take(path)
                self.assertExit(run, 2)
                self.assertFalse(os.path.exists(path), "a foto foi gravada dentro do atlas")
                self.assertNoRun()

    def test_a_logs_probe_that_answered_nothing_is_recorded_as_not_verified(self):
        """SPEC-0090:UT-01 (Emenda v2) — a probe de logs de dev-api volta com truncated: true e nenhum item: a foto é
        gravada (exit 0) com {"deployment": "dev-api", "check": "logs", "reason"} em not_verified."""
        self.set_state(**{"dev-api": deployment_state("dev-api", image=OLD_IMAGE,
                                                      logs_answer={"items": [], "truncated": True})})
        out = self.task / "foto.json"
        self.assertExit(self.take(out), 0)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(snapshot_problems(data), [], data)
        self.assertIn(("dev-api", "logs"), [(i["deployment"], i["check"]) for i in data["not_verified"]])


# --------------------------------------------------------------------------- UT-02


class DeliveryTest(VerifyCase):
    def delivery(self, expect, **state):
        self.set_state(**{"dev-api": deployment_state("dev-api", **state)})
        data = self.result(self.compare(expect=expect))
        return self.check(data, "dev-api", "delivery")

    def test_expected_digest_on_every_ready_pod_and_rollout_complete_is_ok(self):
        """SPEC-0090:UT-02 — `--expect-image acme/api@sha256:<novo>`, todos os pods prontos com o digest novo e
        rollout_complete true: delivery ok."""
        self.assertEqual(self.delivery(f"acme/api@{NEW_DIGEST}")["status"], "ok")

    def test_a_pod_with_the_old_digest_fails_with_pod_and_image_in_the_evidence(self):
        """SPEC-0090:UT-02 — um pod com sha256:<antigo>: delivery failed, com o nome do pod e a imagem antiga na
        evidência."""
        item = self.delivery(f"acme/api@{NEW_DIGEST}", images={"api-7f9c-cccc": OLD_IMAGE})
        self.assertEqual(item["status"], "failed", item)
        evidence = json.dumps(item["evidence"])
        self.assertIn("api-7f9c-cccc", evidence)
        self.assertIn(OLD_DIGEST, evidence)

    def test_rollout_not_complete_fails(self):
        """SPEC-0090:UT-02 — rollout_complete false (com os pods já na imagem nova): delivery failed."""
        self.assertEqual(self.delivery(f"acme/api@{NEW_DIGEST}", complete=False)["status"], "failed")

    def test_the_digest_wins_over_the_tag(self):
        """SPEC-0090:UT-02 — com digest na imagem esperada, a tag igual não basta: pods acme/api:1.4.2@<antigo> com
        `--expect-image acme/api:1.4.2@<novo>` dão delivery failed."""
        item = self.delivery(f"acme/api:1.4.2@{NEW_DIGEST}", image=f"acme/api:1.4.2@{OLD_DIGEST}")
        self.assertEqual(item["status"], "failed", item)

    def test_without_digest_the_tag_is_checked(self):
        """SPEC-0090:UT-02 — `--expect-image acme/api:1.4.2`, sem digest: pods com a tag 1.4.2 (qualquer digest) dão
        ok; um pod com a 1.4.1 dá failed."""
        self.assertEqual(self.delivery("acme/api:1.4.2")["status"], "ok")
        self.assertEqual(self.delivery("acme/api:1.4.2", image=f"acme/api:1.4.2@{OLD_DIGEST}")["status"], "ok")
        item = self.delivery("acme/api:1.4.2", images={"api-7f9c-aaaa": OLD_IMAGE})
        self.assertEqual(item["status"], "failed", item)
        self.assertIn("api-7f9c-aaaa", json.dumps(item["evidence"]))

    def test_another_image_path_fails(self):
        """SPEC-0090:UT-02 — pods com outro caminho de imagem (acme/other:1.4.2) e `--expect-image acme/api:1.4.2`:
        delivery failed."""
        self.assertEqual(self.delivery("acme/api:1.4.2", image="acme/other:1.4.2")["status"], "failed")

    def test_an_expected_image_without_tag_or_digest_exits_2(self):
        """SPEC-0090:UT-02 — `--expect-image acme/api` (sem ":<tag>" nem "@<digest>") é argumento inválido: exit 2,
        sem rodar probe."""
        run = self.compare(expect="acme/api")
        self.assertExit(run, 2)
        self.assertNoRun()


# --------------------------------------------------------------------------- UT-03


class RuntimeTest(VerifyCase):
    def runtime(self, *extra, deployment="dev-api", **state):
        state.setdefault("events", [("BackOff", "Pod/api-7f9c-aaaa", 3)])
        state.setdefault("restarts", {"api-7f9c-aaaa": 2})
        self.set_state(**{deployment: deployment_state(deployment, **state)})
        baseline = self.write_baseline(baseline_data(**{"dev-api": {
            "restarts": {"api-7f9c-aaaa": 2, "api-7f9c-bbbb": 0, "api-7f9c-cccc": 0},
            "warnings": ["BackOff|Pod/api"]}}))
        data = self.result(self.compare(*extra, baseline=baseline))
        return self.check(data, deployment, "runtime")

    def test_what_was_already_in_the_snapshot_does_not_count(self):
        """SPEC-0090:UT-03 — foto com restarts {api-7f9c-aaaa: 2} e o warning BackOff|Pod/api; agora api-7f9c-aaaa
        com 2 e o mesmo BackOff: runtime ok."""
        self.assertEqual(self.runtime()["status"], "ok")

    def test_the_same_reason_on_another_pod_of_the_workload_is_not_new(self):
        """SPEC-0090:UT-03 — BackOff agora em api-7f9c-bbbb (o objeto sem o sufixo do pod é o mesmo Pod/api):
        runtime ok."""
        self.assertEqual(self.runtime(events=[("BackOff", "Pod/api-7f9c-bbbb", 1)])["status"], "ok")

    def test_new_restarts_above_the_limit_fail(self):
        """SPEC-0090:UT-03 — api-7f9c-aaaa com 3 e --max-new-restarts 0 (padrão): runtime failed, com o pod na
        evidência; com --max-new-restarts 1: ok."""
        item = self.runtime(restarts={"api-7f9c-aaaa": 3})
        self.assertEqual(item["status"], "failed", item)
        self.assertIn("api-7f9c-aaaa", json.dumps(item["evidence"]))
        self.assertEqual(self.runtime("--max-new-restarts", "1", restarts={"api-7f9c-aaaa": 3})["status"], "ok")

    def test_a_pod_not_in_the_snapshot_counts_from_zero(self):
        """SPEC-0090:UT-03 — depois do rollout, pods novos (api-8d3e-*): sem restarts, runtime ok; um deles com 1
        restart, runtime failed."""
        pods = ("api-8d3e-aaaa", "api-8d3e-bbbb", "api-8d3e-cccc")
        self.assertEqual(self.runtime(pods=pods, restarts={}, events=[])["status"], "ok")
        self.assertEqual(self.runtime(pods=pods, restarts={"api-8d3e-bbbb": 1}, events=[])["status"], "failed")

    def test_a_new_warning_fails(self):
        """SPEC-0090:UT-03 — um warning FailedMount novo: runtime failed, com o motivo na evidência."""
        item = self.runtime(events=[("BackOff", "Pod/api-7f9c-aaaa", 3), ("FailedMount", "Pod/api-7f9c-cccc", 1)])
        self.assertEqual(item["status"], "failed", item)
        self.assertIn("FailedMount", json.dumps(item["evidence"]))

    def test_a_pod_not_ready_fails(self):
        """SPEC-0090:UT-03 — um pod não pronto: runtime failed, com o pod na evidência."""
        item = self.runtime(not_ready=("api-7f9c-cccc",))
        self.assertEqual(item["status"], "failed", item)
        self.assertIn("api-7f9c-cccc", json.dumps(item["evidence"]))

    def test_a_workload_not_found_fails(self):
        """SPEC-0090:UT-03 (Emenda v2) — status com found: false para o workload: runtime failed (e a delivery não
        fica ok); veredito degradou."""
        self.set_state(**{"dev-api": deployment_state("dev-api", found=False)})
        data = self.result(self.compare(), "degradou")
        self.assertEqual(self.check(data, "dev-api", "runtime")["status"], "failed")
        self.assertNotEqual(self.check(data, "dev-api", "delivery")["status"], "ok")


# --------------------------------------------------------------------------- UT-04


class LogsTest(VerifyCase):
    def logs(self, lines, *extra, baseline=None, logs_answer=None):
        self.set_state(**{"dev-api": deployment_state("dev-api", logs=lines, logs_answer=logs_answer)})
        if baseline is None:
            baseline = self.write_baseline(baseline_data(**{"dev-api": {"error_signatures": {OLD_SIGNATURE: 2}}}))
        data = self.result(self.compare(*extra, baseline=baseline))
        return self.check(data, "dev-api", "logs")

    def test_a_new_signature_counts_against_the_limit(self):
        """SPEC-0090:UT-04 — foto com ERROR user <n> not found; agora essa e uma nova (ERROR timeout calling ...):
        com --max-new-errors 0 (padrão), logs failed com a assinatura nova na evidência; com --max-new-errors 1, ok."""
        lines = ["ERROR user 77 not found", 'ERROR timeout calling "billing"', "INFO request 1 ok"]
        item = self.logs(lines)
        self.assertEqual(item["status"], "failed", item)
        self.assertIn("timeout calling", json.dumps(item["evidence"]))
        self.assertEqual(self.logs(lines, "--max-new-errors", "1")["status"], "ok")

    def test_only_the_old_signature_is_ok(self):
        """SPEC-0090:UT-04 — só a assinatura que já estava na foto (mesmo com outra contagem): logs ok."""
        self.assertEqual(self.logs(["ERROR user 1 not found"] * 5)["status"], "ok")

    def test_a_new_info_signature_does_not_count(self):
        """SPEC-0090:UT-04 — uma assinatura nova de nível info (INFO cache warmed): logs ok."""
        self.assertEqual(self.logs(["INFO cache warmed", "ERROR user 3 not found"])["status"], "ok")

    def test_without_baseline_logs_are_not_verified(self):
        """SPEC-0090:UT-04 — sem --baseline, logs fica not_verified com o motivo do contrato ("sem foto de antes")
        em todos os deployments, e o veredito nunca é passou."""
        self.set_state(**{"dev-api": deployment_state("dev-api", logs=["INFO request 1 ok"])})
        data = self.result(self.compare(baseline=None))
        for deployment in DEPLOYMENTS:
            item = self.check(data, deployment, "logs")
            self.assertEqual(item["status"], "not_verified", item)
            self.assertIn(NO_BASELINE, item["reason"])
        self.assertEqual(data["verdict"], "inconclusivo")

    def test_logs_that_answered_nothing_are_not_verified(self):
        """SPEC-0090:UT-04 (Emenda v2) — a probe de logs volta com truncated: true e nenhum item: logs not_verified,
        "nenhum pod respondeu", nunca ok."""
        item = self.logs([], logs_answer={"items": [], "truncated": True})
        self.assertEqual(item["status"], "not_verified", item)
        self.assertIn(NO_POD, item["reason"])

    def test_a_baseline_without_logs_does_not_make_logs_ok(self):
        """SPEC-0090:UT-04 — a foto marcou os logs de dev-api como not_verified (sem assinaturas): agora, com uma
        assinatura de erro, a verificação logs de dev-api não fica ok e o veredito não é passou."""
        baseline = self.write_baseline(baseline_data(not_verified=[
            {"deployment": "dev-api", "check": "logs", "reason": NO_POD}]))
        item = self.logs(["ERROR user 1 not found"], baseline=baseline)
        self.assertNotEqual(item["status"], "ok", item)

    def test_the_window_option_sets_the_log_window(self):
        """SPEC-0090:UT-04 — a probe de logs do compare usa a janela --window: 600 s por padrão (10m), 300 s com
        --window 5m."""
        for extra, seconds in (((), 600), (("--window", "5m"), 300)):
            with self.subTest(window=seconds):
                self.record.unlink(missing_ok=True)
                self.logs(["INFO request 1 ok"], *extra)
                logs = [c["input"] for c in self.calls("run") if c["input"]["verb"] == "logs"]
                self.assertTrue(logs)
                self.assertEqual({c["limits"]["since_seconds"] for c in logs}, {seconds})


# --------------------------------------------------------------------------- UT-05


class VerdictTest(VerifyCase):
    def test_all_ok_passes_with_exit_0(self):
        """SPEC-0090:UT-05 — os dois deployments com as três verificações ok: passou, exit 0, sem sugestão."""
        data = self.result(self.compare(), "passou")
        self.assertTrue(all(c["status"] == "ok" for c in data["checks"]), data["checks"])
        self.assertIn(data.get("suggestion"), (None, ""))

    def test_one_failed_degrades_with_exit_1_and_a_suggestion_without_command(self):
        """SPEC-0090:UT-05 — só a delivery de dev-api failed: degradou, exit 1; a sugestão cita o repositório de
        configuração (acme/iac) e não traz nenhum comando; nada é executado além das probes de leitura."""
        self.set_state(**{"dev-api": deployment_state("dev-api", image=OLD_IMAGE)})
        data = self.result(self.compare(), "degradou")
        self.assertEqual(self.check(data, "dev-api", "delivery")["status"], "failed")
        self.assertIn(CONFIG_REPO, data["suggestion"])
        self.assertIsNone(COMMAND_RE.search(data["suggestion"]), data["suggestion"])

    def test_one_not_verified_is_inconclusive_with_exit_5(self):
        """SPEC-0090:UT-05 — só os logs de dev-api-blue not_verified (probe sem resposta): inconclusivo, exit 5."""
        self.set_state(**{"dev-api-blue": deployment_state("dev-api-blue",
                                                           logs_answer={"items": [], "truncated": True})})
        data = self.result(self.compare(), "inconclusivo")
        self.assertEqual(self.check(data, "dev-api-blue", "logs")["status"], "not_verified")

    def test_failed_wins_over_not_verified(self):
        """SPEC-0090:UT-05 — delivery de dev-api failed e logs de dev-api-blue not_verified: degradou, exit 1."""
        self.set_state(**{"dev-api": deployment_state("dev-api", complete=False),
                          "dev-api-blue": deployment_state("dev-api-blue",
                                                           logs_answer={"items": [], "truncated": True})})
        self.result(self.compare(), "degradou")

    def test_a_probe_error_or_crash_is_not_verified_never_ok(self):
        """SPEC-0090:UT-05 — a probe de status de dev-api com status error, ou o adaptador quebrando (exit 3) na de
        logs: as verificações que dependem dela ficam not_verified, com motivo; veredito inconclusivo, exit 5."""
        cases = (("status error", {"status": {"error": "sem permissão (Forbidden)"}}, ("delivery", "runtime")),
                 ("adaptador quebrou", {"logs_answer": {"exit": 3, "stderr": "falhou"}}, ("logs",)))
        for name, state, checks in cases:
            with self.subTest(case=name):
                self.set_state(**{"dev-api": deployment_state("dev-api", **state)})
                data = self.result(self.compare(), "inconclusivo")
                for check in checks:
                    item = self.check(data, "dev-api", check)
                    self.assertEqual(item["status"], "not_verified", item)

    def test_a_refused_verb_is_not_verified_never_ok(self):
        """SPEC-0090:UT-05 — a configuração libera só status e events: a probe de logs é recusada (verbo não
        permitido), logs fica not_verified com motivo nos dois deployments e o veredito é inconclusivo, exit 5."""
        self.configure(verbs=("status", "events"))
        data = self.result(self.compare(), "inconclusivo")
        for deployment in DEPLOYMENTS:
            item = self.check(data, deployment, "logs")
            self.assertEqual(item["status"], "not_verified", item)
        self.assertFalse([c for c in self.calls("run") if c["input"]["verb"] == "logs"])

    def test_markdown_output_shows_the_verdict(self):
        """SPEC-0090:UT-05 — sem --json, a saída em Markdown traz o veredito e a sugestão, com o mesmo exit."""
        self.set_state(**{"dev-api": deployment_state("dev-api", image=OLD_IMAGE)})
        run = self.compare(as_json=False)
        self.assertExit(run, 1)
        self.assertIn("degradou", run.stdout)
        self.assertIn(CONFIG_REPO, run.stdout)

    def test_invalid_arguments_exit_2_and_no_config_exits_3(self):
        """SPEC-0090:UT-05 — --window fora do formato, --max-new-errors negativo, --max-new-restarts que não é número e
        a falta de --expect-image saem com 2; sem configuração local, compare e snapshot saem com 3."""
        for extra in (("--window", "dez"), ("--max-new-errors", "-1"), ("--max-new-restarts", "x")):
            with self.subTest(extra=extra):
                self.assertExit(self.compare(*extra), 2)
        run = self.verify("compare", "--service", "api", "--env", "dev", "--json")
        self.assertExit(run, 2)
        self.assertNoRun()
        empty = self.box.root / "cfg-vazio"
        empty.mkdir(exist_ok=True)
        run = self.verify("compare", "--service", "api", "--env", "dev", "--expect-image", NEW_IMAGE,
                          config_home=empty)
        self.assertExit(run, 3)
        run = self.verify("snapshot", "--service", "api", "--env", "dev", "--out", self.task / "x.json",
                          config_home=empty)
        self.assertExit(run, 3)
        self.assertFalse((self.task / "x.json").exists())


# --------------------------------------------------------------------------- UT-06


class SafetyTest(VerifyCase):
    def test_each_probe_is_logged_and_only_reads(self):
        """SPEC-0090:UT-06 — snapshot e compare fazem 3 probes por deployment (status, events, logs), todas de
        runtime, e cada uma entra no probes.log local; a pasta do atlas fica igual (conferido em cada execução)."""
        self.set_state(**{d: deployment_state(d, image=OLD_IMAGE) for d in DEPLOYMENTS})
        self.assertExit(self.take(), 0)
        self.set_state()
        self.result(self.compare(baseline=self.task / "foto.json"))
        runs = self.calls("run")
        self.assertEqual(len(runs), 12, [c["input"]["verb"] for c in runs])
        log = self.log()
        self.assertEqual(len(log), 12, log)
        self.assertEqual(sorted(entry["verb"] for entry in log), sorted(["status", "events", "logs"] * 4))
        self.assertTrue(all(entry["capability"] == "runtime" and entry["environment"] == "dev" for entry in log))

    def test_production_without_confirmation_is_refused_without_calls(self):
        """SPEC-0090:UT-06 — qa (tier production) sem --confirm-production: snapshot e compare saem com 4, citando
        --confirm-production; o adaptador não roda e a foto não é gravada. Com a opção, o compare roda e o registro
        marca confirmed_production: true."""
        out = self.task / "foto-qa.json"
        run = self.take(out, env="qa")
        self.assertExit(run, 4)
        self.assertIn("--confirm-production", output(run))
        self.assertFalse(out.exists())
        baseline = self.write_baseline(dict(baseline_data(), environment="qa"), "foto-qa-base.json")
        run = self.compare(baseline=baseline, env="qa")
        self.assertExit(run, 4)
        self.assertIn("--confirm-production", output(run))
        self.assertNoRun()
        run = self.compare("--confirm-production", baseline=None, env="qa")
        self.assertIn(run.returncode, (0, 1, 5), output(run))
        self.assertTrue(self.calls("run"), "com --confirm-production o compare não rodou as probes")
        self.assertTrue(self.log() and all(e["confirmed_production"] is True for e in self.log()), self.log())


# --------------------------------------------------------------------------- CT-01


class ContractTest(VerifyCase):
    def test_snapshot_and_json_output_follow_verify_1(self):
        """SPEC-0090:CT-01 — a foto gravada pelo snapshot e a saída --json do compare passam no validador verify@1
        (chaves e tipos do contrato; veredito pela regra failed > not_verified > ok)."""
        self.set_state(**{d: deployment_state(d, image=OLD_IMAGE) for d in DEPLOYMENTS})
        out = self.task / "foto.json"
        self.assertExit(self.take(out), 0)
        self.assertEqual(snapshot_problems(json.loads(out.read_text(encoding="utf-8"))), [])
        self.set_state()
        self.result(self.compare(baseline=out), "passou")

    def test_compare_refuses_a_baseline_outside_the_contract(self):
        """SPEC-0090:CT-01 — --baseline com chave desconhecida, com contract verify@2, que não é JSON ou que não existe:
        compare sai com 2, sem veredito."""
        unknown = dict(baseline_data(), extra="x")
        other = dict(baseline_data(), contract="verify@2")
        cases = (("chave desconhecida", self.write_baseline(unknown, "unknown.json")),
                 ("outra versão", self.write_baseline(other, "v2.json")))
        bad = self.task / "nao-json.json"
        bad.write_text("{isto não é json", encoding="utf-8")
        cases += (("não é JSON", bad), ("ausente", self.task / "nao-existe.json"))
        for name, path in cases:
            with self.subTest(case=name):
                run = self.compare(baseline=path)
                self.assertExit(run, 2)
                self.assertNotIn('"verdict"', run.stdout)

    def test_verify_md_has_the_same_examples(self):
        """SPEC-0090:CT-01 — references/verify.md traz pelo menos um exemplo de foto e um de saída --json, ambos válidos
        no verify@1, e o exemplo de foto é aceito como --baseline pelo compare (exit diferente de 2)."""
        self.assertTrue(VERIFY_DOC.is_file(), f"{VERIFY_DOC.relative_to(SKILL)} não existe ({SPEC})")
        examples = doc_examples()
        snapshots = [e for e in examples if "taken_at" in e]
        results = [e for e in examples if "verdict" in e]
        self.assertTrue(snapshots, "verify.md sem exemplo de foto verify@1")
        self.assertTrue(results, "verify.md sem exemplo de saída --json verify@1")
        for example in snapshots:
            self.assertEqual(snapshot_problems(example), [], example)
        for example in results:
            self.assertEqual(result_problems(example), [], example)
        run = self.compare(baseline=self.write_baseline(dict(snapshots[0], service="api", environment="dev"),
                                                        "exemplo.json"))
        self.assertIn(run.returncode, (0, 1, 5), output(run))


# --------------------------------------------------------------------------- IT-01

KUBE_OLD = "ghcr.io/acme/api:1.4.1@" + OLD_DIGEST
KUBE_NEW = "ghcr.io/acme/api:1.4.2@" + NEW_DIGEST


def kube_pod(name, rs, image, ready=True, restarts=0, crash=False):
    state = {"waiting": {"reason": "CrashLoopBackOff"}} if crash else {"running": {"startedAt": "{{now-1200}}"}}
    last = {"terminated": {"reason": "Error", "exitCode": 1}} if crash else {}
    return {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": name, "namespace": "api-dev", "labels": {"app": "api", "pod-template-hash": rs},
                         "ownerReferences": [{"apiVersion": "apps/v1", "kind": "ReplicaSet", "name": f"api-{rs}",
                                              "controller": True}]},
            "spec": {"containers": [{"name": "api", "image": image}]},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
                       "containerStatuses": [{"name": "api", "image": image, "ready": ready, "restartCount": restarts,
                                              "started": not crash, "state": state, "lastState": last}]}}


def kube_event(reason, pod, ago=60):
    return {"apiVersion": "v1", "kind": "Event", "metadata": {"name": f"{pod}.{reason}", "namespace": "api-dev"},
            "type": "Warning", "reason": reason, "count": 2, "message": f"{reason} em {pod}",
            "involvedObject": {"kind": "Pod", "name": pod, "namespace": "api-dev"},
            "firstTimestamp": f"{{{{now-{ago + 60}}}}}", "lastTimestamp": f"{{{{now-{ago}}}}}",
            "source": {"component": "kubelet"}}


def kube_cluster(folder, rs, image, generation, crash_pod=None, events=(), lines=()):
    """Um cluster fictício com Deployment/api (3 réplicas) no formato do kubectl falso da SPEC-0089."""
    folder.mkdir(parents=True, exist_ok=True)
    names = [f"api-{rs}-{suffix}" for suffix in ("aaaa", "bbbb", "cccc")]
    ready = 3 - (1 if crash_pod else 0)
    deployment = {"apiVersion": "apps/v1", "kind": "Deployment",
                  "metadata": {"name": "api", "namespace": "api-dev", "generation": generation,
                               "labels": {"app": "api"}},
                  "spec": {"replicas": 3, "selector": {"matchLabels": {"app": "api"}},
                           "template": {"metadata": {"labels": {"app": "api"}}, "spec": {"containers": []}}},
                  "status": {"observedGeneration": generation, "replicas": 3, "updatedReplicas": 3,
                             "readyReplicas": ready, "availableReplicas": ready}}
    replicaset = {"apiVersion": "apps/v1", "kind": "ReplicaSet",
                  "metadata": {"name": f"api-{rs}", "namespace": "api-dev",
                               "labels": {"app": "api", "pod-template-hash": rs},
                               "ownerReferences": [{"apiVersion": "apps/v1", "kind": "Deployment", "name": "api",
                                                    "controller": True}]},
                  "spec": {"selector": {"matchLabels": {"app": "api", "pod-template-hash": rs}}}}
    pods = [kube_pod(name, rs, image, ready=name != crash_pod, restarts=4 if name == crash_pod else 0,
                     crash=name == crash_pod) for name in names]
    logs = [f"[pod/{names[i % 3]}/api] {{{{nano-{120 - i}}}}} {line}" for i, line in enumerate(lines)]

    def listing(items):
        return {"apiVersion": "v1", "kind": "List", "items": items, "metadata": {}}

    files = {"deployments.json": listing([deployment]), "replicasets.json": listing([replicaset]),
             "pods.json": listing(pods), "events.json": listing([kube_event(r, p) for r, p in events]),
             "logs.json": {"Deployment/api": logs}}
    for name, data in files.items():
        (folder / name).write_text(json.dumps(data), encoding="utf-8")
    return folder


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox()
        try:
            build_probe_atlas(cls.box)
        except BaseException:
            cls.box.cleanup()
            raise
        clusters = cls.box.root / "clusters"
        cls.before = kube_cluster(clusters / "before", "6a1b", KUBE_OLD, 4,
                                  events=[("Unhealthy", "api-6a1b-aaaa")],
                                  lines=["INFO request 1 ok", "ERROR user 123 not found", "ERROR user 456 not found",
                                         "INFO request 2 ok"])
        cls.healthy = kube_cluster(clusters / "after-ok", "7c2d", KUBE_NEW, 5,
                                   lines=["INFO request 3 ok", "ERROR user 789 not found", "INFO request 4 ok"])
        cls.broken = kube_cluster(clusters / "after-bad", "7c2d", KUBE_NEW, 5, crash_pod="api-7c2d-cccc",
                                  events=[("BackOff", "api-7c2d-cccc")],
                                  lines=["INFO request 3 ok", 'ERROR timeout calling "billing"',
                                         "ERROR user 789 not found"])

    @classmethod
    def tearDownClass(cls):
        cls.box.cleanup()

    def setUp(self):
        name = self.id().rsplit(".", 1)[-1]
        self.bin = self.box.root / "bin" / name
        self.record = self.box.root / "calls" / f"{name}.jsonl"
        self.record.parent.mkdir(parents=True, exist_ok=True)
        self.task = self.box.root / "task" / name
        self.task.mkdir(parents=True, exist_ok=True)
        adapter = '    kubernetes:\n      verbs: ["status", "events", "logs"]\n      timeout: 60\n'
        self.box.write_local(local_text(self.box.atlas, probes_yaml([adapter])))

    def verify(self, *args):
        before = snapshot(self.box.atlas)
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        run = self.box.run("verify", *args, env=env)
        self.assertNotIn("Traceback", output(run), output(run))
        self.assertNotIn("invalid choice", output(run), f"atlas.py ainda não tem o subcomando verify ({SPEC})")
        self.assertEqual(snapshot(self.box.atlas), before, "o verify mudou a pasta do atlas")
        return run

    def phases(self, after):
        """snapshot com o estado "antes" -> o dublê passa ao estado `after` -> compare --expect-image 1.4.2."""
        out = self.task / "foto.json"
        install_kubectl(self.bin, self.record, fixtures=(self.before,))
        run = self.verify("snapshot", "--service", "api", "--env", "dev", "--out", out)
        self.assertEqual(run.returncode, 0, output(run))
        photo = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(snapshot_problems(photo), [], photo)
        self.assertEqual(photo["deployments"]["dev-api"]["images"], ["acme/api:1.4.1@" + OLD_DIGEST])
        self.assertIn(OLD_SIGNATURE, photo["deployments"]["dev-api"]["error_signatures"])
        install_kubectl(self.bin, self.record, fixtures=(after,))
        run = self.verify("compare", "--service", "api", "--env", "dev", "--baseline", out, "--expect-image",
                          "acme/api:1.4.2", "--json")
        data = json.loads(run.stdout)
        self.assertEqual(result_problems(data), [], data)
        self.assertEqual(run.returncode, VERDICT_EXIT[data["verdict"]], output(run))
        calls = read_calls(self.record)
        self.assertTrue(calls, "o kubectl falso não foi chamado")
        self.assertEqual({argv[0] for argv in calls}, {"get", "logs"}, calls)
        self.assertNotIn(CONTEXTS["cluster-dev"], out.read_text(encoding="utf-8") + output(run))
        return {c["check"]: c for c in data["checks"] if c["deployment"] == "dev-api"}, data

    def test_snapshot_then_healthy_rollout_passes(self):
        """SPEC-0090:IT-01 — atlas temporário com o mapa de acesso, probes ligadas, o adaptador kubernetes da skill e o
        kubectl falso: snapshot com o estado "antes" (1.4.1), o dublê passa ao "depois" saudável (1.4.2, pods
        novos, só a assinatura de erro antiga) e o compare --expect-image acme/api:1.4.2 dá passou, exit 0; o
        kubectl só recebeu get e logs; a pasta do atlas não muda."""
        checks, data = self.phases(self.healthy)
        self.assertEqual(data["verdict"], "passou", json.dumps(data, ensure_ascii=False, indent=1))
        self.assertEqual({name: item["status"] for name, item in checks.items()},
                         {"delivery": "ok", "runtime": "ok", "logs": "ok"})

    def test_snapshot_then_crashloop_and_new_error_degrades(self):
        """SPEC-0090:IT-01 — o "depois" com um pod em CrashLoopBackOff (não pronto, 4 restarts, BackOff) e uma
        assinatura de erro nova: degradou, exit 1, com runtime e logs failed e as evidências (o pod e a assinatura
        nova) e a sugestão citando o repositório de configuração."""
        checks, data = self.phases(self.broken)
        self.assertEqual(data["verdict"], "degradou", json.dumps(data, ensure_ascii=False, indent=1))
        self.assertEqual(checks["runtime"]["status"], "failed", checks["runtime"])
        self.assertIn("api-7c2d-cccc", json.dumps(checks["runtime"]["evidence"]))
        self.assertEqual(checks["logs"]["status"], "failed", checks["logs"])
        self.assertIn("timeout calling", json.dumps(checks["logs"]["evidence"]))
        self.assertIn(CONFIG_REPO, data["suggestion"])


if __name__ == "__main__":
    unittest.main()
