"""`verify track`: onde está a entrega de um commit — pipeline, imagem, GitOps e rollout (SPEC-0106: UT-08 a UT-14,
IT-01, IT-02 e CT-02, com a Emenda v2; ADR-0010, ADR-0023, ADR-0024, ADR-0025).

Contrato (seção 6 da SPEC-0106) que estes testes fixam:

    atlas.py verify track --service <id> --env <ambiente> --commit <sha> [--expect-image <imagem>]
        [--confirm-production] [--json] [--atlas X]
    probes pelo caminho do `probe`: pipeline runs (uma vez, alvo = o primeiro deployment do serviço no ambiente),
        gitops application e runtime status (por deployment, limits.lines 2000).
    etapas pipeline (uma, deployment "") e image, gitops, rollout (por deployment), cada uma com status pending,
        running, ok, failed ou not_verified, evidence e reason (obrigatório fora de ok).
    state: failed (exit 1) > running (6) > pending (6) > not_verified (5) > ok (0); current_stage = a primeira etapa
        não ok na ordem pipeline -> image -> gitops -> rollout (e deployments por id); "" em ok.
    outros exits: 2 argumento inválido, 3 sem configuração, 4 probes desligadas ou produção sem confirmação.
    --json: track@1 com as chaves fechadas contract, service, environment, commit, state, current_stage,
        expected_image, expected_image_source, stages.
    Emenda v2: a máscara do núcleo cobre a conta de 12 dígitos no host ECR (<conta>.dkr.ecr.<região>.amazonaws.com) e
        em ARN maiúsculo (ARN:AWS:...).

Leituras desta suíte (listadas no relatório do test-writer):
    - current_stage percorre as etapas na ordem pipeline, image, gitops, rollout e, dentro de cada etapa, os
      deployments por id (etapa antes de deployment): com dev-api em gitops running e dev-api-blue em image pending,
      current_stage é image.
    - `reason` pode faltar ou ser "" só em ok; os motivos fixos da seção 6 são conferidos como trecho do reason.
    - A evidência é conferida como texto (o pod, a URL da execução), sem fixar as chaves dela, salvo a lista `runs`
      do pipeline com os itens do adaptador.
    - Probe recusada (sem adaptador, sem verbo liberado) deixa a etapa not_verified; o exit continua o das etapas.
    - Os adaptadores falsos das regras de etapa ficam em fixtures/delivery-track/scripted_track.py (fake-probes/ não
      está nos touches e o scripted.py de lá é só probe@1, sem inputs change): três entradas em probes.adapters,
      fake-ci (probe@2, pipeline runs, access [], inputs change, credentials GH_TOKEN), fake-gitops (probe@2, gitops
      application, access cluster, credentials ATLAS_GITOPS_CONTEXT) e fake-runtime (probe@1, runtime).
    - Produção sem confirmação: exit 4 sem nenhuma execução (mode "run") de adaptador; o --describe pode rodar.
    - IT-01: o `verify compare` final usa a foto tirada pelo `verify snapshot` no estado "antes" (sem foto os logs
      ficam not_verified e o veredito seria inconclusivo); "todo argv do kubectl começa com get" vale para as chamadas
      do `track` (o snapshot e o compare também usam `kubectl logs`).
    - UT-14 (Emenda v2): o dublê ecoa, em itens e mensagens, o GH_TOKEN, o ATLAS_GITOPS_CONTEXT, o contexto do
      cluster, um host ECR e um ARN maiúsculo com a conta 123456789012; nada disso sai no Markdown, no --json, nas
      evidências nem no probes.log; a função de máscara do núcleo (probe_mask com probe_extras) também é conferida
      direto.

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); atlas temporário copiado de
fixtures/probe-resource/atlas; nenhum gh, kubectl, argocd ou rede reais (o gh falso de fixtures/github-actions e o
kubectl falso de fixtures/delivery-track no início do PATH nos testes de integração); nomes acme.
"""
import copy
import json
import os
import re
import shutil
import stat
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from helpers import SKILL, TESTS, Sandbox, fn, output, snapshot
from test_probe import adapter_yaml, probes_yaml

SPEC = "SPEC-0106"
ATLAS_FIXTURE = TESTS / "fixtures" / "probe-resource" / "atlas"
TRACK = TESTS / "fixtures" / "delivery-track"
STATES = TRACK / "states"
SCRIPTED = TRACK / "scripted_track.py"
FAKE_TRACK_KUBECTL = TRACK / "fake_kubectl.py"
FAKE_RUNTIME_KUBECTL = TESTS / "fixtures" / "kubernetes" / "fake_kubectl.py"
FAKE_GH = TESTS / "fixtures" / "github-actions" / "fake_gh.py"
VERIFY_DOC = SKILL / "references" / "verify.md"

COMMIT = "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567"
NEW = "acme/api:sha-0a1b2c3"
OLD = "acme/api:sha-9f8e7d6"
DIGEST = "sha256:" + "9f8e" * 16
OTHER_DIGEST = "sha256:" + "0a1b" * 16
CONTEXT = "ctx-local-dev-0106"
PROD_CONTEXT = "ctx-local-prod-0106"
GH_TOKEN = "fake-gh-token-0106-nao-real"
GITOPS_CONTEXT = "ctx-gestao-0106"
UNDECLARED = "fake-undeclared-0106-nao-real"
ACCOUNT = "123456789012"
ECR_TEXT = f"{ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com/acme/api:sha-0a1b2c3"
ARN_TEXT = f"ARN:AWS:IAM::{ACCOUNT}:ROLE/CI-DEPLOY"
SECRETS = (GH_TOKEN, GITOPS_CONTEXT, CONTEXT, PROD_CONTEXT, UNDECLARED, ACCOUNT)

STAGES = ("pipeline", "image", "gitops", "rollout")
STATUSES = ("pending", "running", "ok", "failed", "not_verified")
STATE_EXIT = {"failed": 1, "running": 6, "pending": 6, "not_verified": 5, "ok": 0}
RESULT_KEYS = {"contract", "service", "environment", "commit", "state", "current_stage", "expected_image",
               "expected_image_source", "stages"}
STAGE_KEYS = {"stage", "deployment", "status", "evidence", "reason"}
SOURCES = ("expect-image", "commit-tag", "")
WORKLOADS = {"dev-api": "Deployment/api", "dev-api-blue": "Deployment/api-blue"}
PODS = {"dev-api": ("api-7c2d-aaaa", "api-7c2d-bbbb", "api-7c2d-cccc"),
        "dev-api-blue": ("api-blue-5c6d-aaaa", "api-blue-5c6d-bbbb", "api-blue-5c6d-cccc")}
COMMAND_RE = re.compile(r"\bgh |\bkubectl |\bargocd ")
FORBIDDEN_WORDS = ("POST", "PATCH", "PUT", "DELETE", "rerun", "dispatch", "sync", "patch", "apply", "annotate",
                   "rollout", "delete")

NO_RUN = "nenhuma execução da CI para o commit ainda"
NO_CODE = "serviço sem repositório de código no atlas"
AMBIGUOUS = "mais de uma imagem com o commit: passe --expect-image"
UNKNOWN_IMAGE = "imagem do commit não identificada: passe --expect-image"
WAITING = "aguardando a imagem no GitOps"
CUT_STATUS = "probe de status cortada"
BAD_COMMIT = "commit precisa ser o sha completo (40 hexadecimais)"

DESCRIBES = {
    "fake-ci": {"contract": "probe@2", "adapter": "fake-ci",
                "capabilities": {"pipeline": {"verbs": ["runs"], "targets": ["deployment"], "access": [],
                                              "inputs": ["change"]}}},
    "fake-gitops": {"contract": "probe@2", "adapter": "fake-gitops",
                    "capabilities": {"gitops": {"verbs": ["application"], "targets": ["deployment"],
                                                "access": ["cluster"]}}},
    "fake-runtime": {"contract": "probe@1", "adapter": "fake-runtime",
                     "capabilities": {"runtime": ["status", "events", "logs"]}},
}
VERBS = {"fake-ci": ["runs"], "fake-gitops": ["application"], "fake-runtime": ["status", "events", "logs"]}
CREDENTIALS = {"fake-ci": ["GH_TOKEN"], "fake-gitops": ["ATLAS_GITOPS_CONTEXT"], "fake-runtime": []}

assert len(COMMIT) == 40


def f(name):
    return fn(name, SPEC)


# --------------------------------------------------------------------------- itens dos adaptadores falsos


def run_item(status="completed", conclusion="success", repository="acme/api", workflow="Build", n=1, **extra):
    done = status == "completed"
    item = {"repository": repository, "found": True, "workflow": workflow,
            "path": f".github/workflows/{workflow.lower()}.yml", "event": "push", "status": status,
            "conclusion": conclusion if done else "", "attempt": 1, "started_at": f"2026-11-24T10:0{n}:00Z",
            "duration_seconds": 300 if done else None,
            "url": f"https://github.com/{repository}/actions/runs/{1000 + n}"}
    item.update(extra)
    return item


def runs(*items, truncated=False):
    return {"items": list(items), "truncated": truncated}


def app(name="dev-api", sync="Synced", health="Healthy", phase="Succeeded", images=(NEW,), found=True):
    if not found:
        return {"items": [{"application": name, "found": False}], "truncated": False}
    return {"items": [{"application": name, "found": True, "sync_status": sync, "health_status": health,
                       "revision": "4f1c2d3e", "operation_phase": phase,
                       "operation_finished_at": "2026-11-24T10:09:00Z", "reconciled_at": "2026-11-24T10:10:00Z",
                       "images": list(images)}], "truncated": False}


def status(deployment="dev-api", image=NEW, images=None, ready=None, restarts=None, complete=True, found=True,
           truncated=False, pods=None):
    """Resposta de runtime status: o workload e os pods; images/ready/restarts são {pod: valor}."""
    label = WORKLOADS[deployment]
    pods = PODS[deployment] if pods is None else pods
    images, ready, restarts = images or {}, ready or {}, restarts or {}
    if not found:
        return {"items": [{"kind": "workload", "workload": label, "found": False, "rollout_complete": False}],
                "truncated": truncated}
    count = len([p for p in pods if ready.get(p, True)])
    items = [{"kind": "workload", "workload": label, "found": True, "desired": len(pods), "updated": len(pods),
              "ready": count, "available": count, "rollout_complete": complete}]
    for pod in pods:
        items.append({"kind": "pod", "workload": label, "pod": pod, "phase": "Running", "ready": ready.get(pod, True),
                      "restarts": restarts.get(pod, 0), "images": [images.get(pod, image)], "last_termination": ""})
    return {"items": items, "truncated": truncated}


# --------------------------------------------------------------------------- validador track@1 desta suíte


def _scalar(value):
    return isinstance(value, (str, int, float, bool, type(None)))


def _flat(value):
    return isinstance(value, dict) and all(_scalar(v) or (isinstance(v, list) and all(_scalar(x) for x in v))
                                           for v in value.values())


def first_open(stages) -> str:
    order = sorted((STAGES.index(s["stage"]), s["deployment"]) for s in stages
                   if isinstance(s, dict) and s.get("stage") in STAGES and s.get("status") != "ok")
    return STAGES[order[0][0]] if order else ""


def state_of(statuses) -> str:
    for state in ("failed", "running", "pending", "not_verified"):
        if state in statuses:
            return state
    return "ok"


def track_problems(data) -> list:
    """Problemas de uma saída `verify track --json` frente ao track@1 da seção 6; [] = válida."""
    if not isinstance(data, dict):
        return ["a saída não é um objeto"]
    problems = []
    if set(data) != RESULT_KEYS:
        problems.append(f"chaves {sorted(data)} != {sorted(RESULT_KEYS)}")
    if data.get("contract") != "track@1":
        problems.append(f"contract {data.get('contract')!r}")
    if not (isinstance(data.get("commit"), str) and re.match(r"^[0-9a-f]{40}\Z", data["commit"])):
        problems.append(f"commit {data.get('commit')!r}")
    if data.get("state") not in STATE_EXIT:
        problems.append(f"state {data.get('state')!r}")
    if data.get("expected_image_source") not in SOURCES or not isinstance(data.get("expected_image"), str):
        problems.append("expected_image ou expected_image_source fora do contrato")
    elif (data["expected_image"] == "") != (data["expected_image_source"] == ""):
        problems.append("expected_image e expected_image_source vazios só juntos")
    stages = data.get("stages")
    if not isinstance(stages, list) or not stages:
        return problems + ["stages não é uma lista com itens"]
    for item in stages:
        if not isinstance(item, dict) or not {"stage", "deployment", "status", "evidence"} <= set(item) <= STAGE_KEYS:
            problems.append(f"etapa com chaves erradas: {item!r}")
            continue
        if item["stage"] not in STAGES or item["status"] not in STATUSES:
            problems.append(f"stage ou status fora do contrato: {item!r}")
        if not isinstance(item["deployment"], str) or (item["stage"] == "pipeline") != (item["deployment"] == ""):
            problems.append(f"deployment da etapa: {item!r}")
        reason = item.get("reason", "")
        if not isinstance(reason, str) or (item["status"] != "ok" and not reason.strip()):
            problems.append(f"reason vazio fora de ok: {item!r}")
        evidence = item["evidence"]
        if not isinstance(evidence, dict):
            problems.append(f"evidence não é objeto: {item!r}")
            continue
        for key, value in evidence.items():
            if key == "runs" and item["stage"] == "pipeline":
                if not (isinstance(value, list) and all(_flat(v) for v in value)):
                    problems.append("evidence.runs precisa ser uma lista de objetos planos")
            elif not (_scalar(value) or (isinstance(value, list) and all(_scalar(v) for v in value))):
                problems.append(f"evidence.{key} não é escalar nem lista de escalares")
    if [s.get("stage") for s in stages if isinstance(s, dict)].count("pipeline") != 1:
        problems.append("precisa de exatamente uma etapa pipeline")
    statuses = {s.get("status") for s in stages if isinstance(s, dict)}
    if data.get("state") != state_of(statuses):
        problems.append(f"state {data.get('state')!r} fora da regra (esperado {state_of(statuses)})")
    if data.get("current_stage") != first_open(stages):
        problems.append(f"current_stage {data.get('current_stage')!r} (esperado {first_open(stages)!r})")
    return problems


def doc_blocks() -> list:
    """(rótulo, dados) dos blocos ```json track@1 valid|invalid de references/verify.md."""
    text = VERIFY_DOC.read_text(encoding="utf-8")
    return [(m.group(1), json.loads(m.group(2)))
            for m in re.finditer(r"```json track@1 (valid|invalid)[ \t]*\n(.*?)```", text, re.DOTALL)]


# --------------------------------------------------------------------------- atlas e caso base


def graph_of(atlas: Path) -> dict:
    return json.loads((atlas / "graph.json").read_text(encoding="utf-8"))


def save_graph(atlas: Path, graph: dict):
    (atlas / "graph.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")


def edge(source, target, kind, evidence=None):
    item = {"from": source, "inferred": False, "sources": ["facts"], "to": target, "type": kind}
    if evidence:
        item["evidence"] = evidence
    return item


def add_blue(atlas: Path):
    """Um segundo deployment do serviço api em dev: dev-api-blue (Deployment/api-blue, cluster-dev)."""
    graph = graph_of(atlas)
    node = copy.deepcopy(next(n for n in graph["nodes"] if n["key"] == "deployment:dev-api"))
    node.update(key="deployment:dev-api-blue", name="dev-api-blue",
                attrs={"config_refs": [], "images": ["acme/api"], "namespace": "api-dev",
                       "workloads": ["Deployment/api-blue"]})
    graph["nodes"].append(node)
    graph["edges"] += [edge("deployment:dev-api-blue", "service:api", "deploys"),
                       edge("deployment:dev-api-blue", "cluster:cluster-dev", "runs_in"),
                       edge("deployment:dev-api-blue", "environment:dev", "runs_in"),
                       edge("deployment:dev-api-blue", "repository:acme/gitops", "sourced_from")]
    save_graph(atlas, graph)


def add_code_repository(atlas: Path, name="worker"):
    """Mais um repositório de código do serviço api (aresta da regra 4, image:acme/<name>): acme/<name> entra em
    delivery.code_repositories e acme/<name> em delivery.images."""
    graph = graph_of(atlas)
    graph["nodes"].append({"attrs": {"default_branch": "main"}, "conflicts": [], "key": f"repository:acme/{name}",
                           "kind": "repository", "name": name, "seen_at": "2026-11-24", "sources": ["facts"]})
    graph["edges"].append(edge("service:api", f"repository:acme/{name}", "sourced_from", f"image:acme/{name}"))
    save_graph(atlas, graph)


def drop_code_repository(atlas: Path):
    """O serviço api sem repositório de código (sem a aresta image:acme/api)."""
    graph = graph_of(atlas)
    graph["edges"] = [e for e in graph["edges"] if str(e.get("evidence", "")) != "image:acme/api"]
    save_graph(atlas, graph)


def set_tiers(atlas: Path, tiers: dict):
    path = atlas / "atlas-config.yml"
    text = path.read_text(encoding="utf-8").split("environments:")[0]
    text += "environments:\n" + "".join(f"  {env}: {{tier: {tier}}}\n" for env, tier in tiers.items())
    path.write_text(text, encoding="utf-8")


def home_files(home: Path) -> dict:
    """snapshot do HOME temporário sem Library/ (o python3 do macOS grava ali o cache de bytecode de todo processo
    Python, com PYTHONPYCACHEPREFIX em ~/Library/Caches/com.apple.python: não é escrita do track)."""
    return {k: v for k, v in snapshot(home).items() if k != "Library" and not k.startswith("Library/")}


def access_yaml():
    return (f"access:\n  clusters:\n    \"cluster-dev\": {{context: {json.dumps(CONTEXT)}}}\n"
            f"    \"cluster-prod\": {{context: {json.dumps(PROD_CONTEXT)}}}\n")


class TrackCase(unittest.TestCase):
    """Um atlas temporário por teste (cópia de fixtures/probe-resource/atlas: service:api com o código acme/api,
    dev-api em dev tier test no cluster-dev, prod-api em prod sem tier), o acesso local aos dois clusters, os três
    adaptadores falsos e o registro de processos deles."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        shutil.copytree(ATLAS_FIXTURE, self.box.atlas)
        self.record = self.box.root / "calls.jsonl"
        self.scenario_path = self.box.root / "scenario.json"
        self.describe_dir = self.box.root / "describe"
        self.describe_dir.mkdir()
        for aid, data in DESCRIBES.items():
            (self.describe_dir / f"{aid}.json").write_text(json.dumps(data), encoding="utf-8")
        self.scenario = {"runs": {"*": runs(run_item())}, "application": {"*": app()},
                         "status": {"dev-api": status("dev-api"), "dev-api-blue": status("dev-api-blue")}}
        self.write_scenario()
        self.configure()

    # -- configuração e cenário

    def adapter(self, aid):
        command = [sys.executable, str(SCRIPTED), "--record", str(self.record), "--describe-file",
                   str(self.describe_dir / f"{aid}.json"), "--scenario", str(self.scenario_path), "--adapter", aid]
        return adapter_yaml(aid, command, verbs=VERBS[aid], timeout=60, credentials=CREDENTIALS[aid])

    def configure(self, adapters=("fake-ci", "fake-gitops", "fake-runtime"), enabled=True, present=True):
        text = f"atlas: {json.dumps(str(self.box.atlas))}\ncredentials: {{}}\n" + access_yaml()
        if present:
            text += probes_yaml([self.adapter(aid) for aid in adapters], enabled=enabled)
        self.box.write_local(text)

    def write_scenario(self, **changes):
        """changes[<verbo>] = {<deployment> | "*": resposta} troca a resposta do verbo inteiro."""
        self.scenario.update(changes)
        self.scenario_path.write_text(json.dumps(self.scenario), encoding="utf-8")

    # -- execução

    def environ(self):
        return {"GH_TOKEN": GH_TOKEN, "ATLAS_GITOPS_CONTEXT": GITOPS_CONTEXT, "GITHUB_TOKEN": UNDECLARED}

    def calls(self, mode=None, adapter=None):
        if not self.record.exists():
            return []
        rows = [json.loads(line) for line in self.record.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [r for r in rows if (mode is None or r["mode"] == mode) and (adapter is None or r["adapter"] == adapter)]

    def log_text(self):
        path = self.box.config_home / "probes.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def log(self):
        return [json.loads(line) for line in self.log_text().splitlines() if line.strip()]

    def track(self, *extra, commit=COMMIT, service="api", env="dev", as_json=True, config_home=None):
        """Roda `atlas.py verify track ...`; em toda execução (UT-14): sem traceback, o subcomando existe, a pasta do
        atlas e o HOME ficam iguais, na configuração local só o probes.log muda, nenhum valor de credencial, de
        contexto ou da conta sai na saída nem no probes.log, e a saída --json é track@1 válida com o exit do state
        (CT-02)."""
        atlas_before, home_before = snapshot(self.box.atlas), home_files(self.box.home)
        config = config_home or self.box.config_home
        config_before = {k: v for k, v in snapshot(config).items() if k != "probes.log"} if config.exists() else {}
        args = ["verify", "track", "--service", service, "--env", env, "--commit", commit, *extra]
        result = self.box.run(*args, *(["--json"] if as_json else []), env=self.environ(), config_home=config_home)
        text = output(result)
        self.assertNotIn("Traceback", text, text)
        self.assertNotIn("invalid choice", text, f"atlas.py ainda não tem verify track ({SPEC})")
        self.assertNotIn("unrecognized arguments", text, f"atlas.py ainda não tem verify track ({SPEC})")
        # SPEC-0106:UT-14
        self.assertEqual(snapshot(self.box.atlas), atlas_before, "o track mudou a pasta do atlas")
        self.assertEqual(home_files(self.box.home), home_before, "o track mudou o HOME")
        if config.exists():
            after = {k: v for k, v in snapshot(config).items() if k != "probes.log"}
            self.assertEqual(after, config_before, "o track criou ou mudou um arquivo além do probes.log")
        everything = (text + self.log_text()).lower()
        for secret in SECRETS:
            self.assertNotIn(secret.lower(), everything, f"{secret} apareceu na saída ou no probes.log")
        for call in self.calls("run"):
            self.assertIn((call["input"].get("capability"), call["input"].get("verb")),
                          {("pipeline", "runs"), ("gitops", "application"), ("runtime", "status")}, call)
        if as_json and result.returncode in STATE_EXIT.values() and result.stdout.strip().startswith("{"):
            data = json.loads(result.stdout)
            self.assertEqual(track_problems(data), [], json.dumps(data, ensure_ascii=False, indent=1))
            # SPEC-0106:CT-02
            self.assertEqual(f("validate_track_result")(data), [], data)
            self.assertEqual(result.returncode, STATE_EXIT[data["state"]], output(result))
        return result

    def data(self, *extra, **kwargs):
        result = self.track(*extra, **kwargs)
        try:
            return json.loads(result.stdout)
        except ValueError:
            self.fail(f"saída --json não é JSON (exit {result.returncode}): {output(result)}")

    def stage(self, data, name, deployment="dev-api"):
        deployment = "" if name == "pipeline" else deployment
        found = [s for s in data["stages"] if s["stage"] == name and s["deployment"] == deployment]
        self.assertEqual(len(found), 1, data["stages"])
        return found[0]

    def assertStage(self, data, name, expected, deployment="dev-api", reason=None):
        item = self.stage(data, name, deployment)
        self.assertEqual(item["status"], expected, json.dumps(data, ensure_ascii=False, indent=1))
        if reason is not None:
            self.assertIn(reason, item.get("reason", ""), item)
        return item

    def assertExit(self, result, code, text=None):
        self.assertEqual(result.returncode, code, output(result))
        if text is not None:
            self.assertIn(text, output(result))

    def assertNoRun(self):
        self.assertEqual(self.calls("run"), [], "um adaptador rodou")


# --------------------------------------------------------------------------- UT-08


class PipelineStageTest(TrackCase):
    def test_no_run_is_pending(self):
        """SPEC-0106:UT-08 — pipeline runs sem itens: pipeline pending "nenhuma execução da CI para o commit
        ainda"."""
        # SPEC-0106:UT-08
        self.write_scenario(runs={"*": runs()})
        self.assertStage(self.data(), "pipeline", "pending", reason=NO_RUN)

    def test_queued_or_in_progress_is_running(self):
        """SPEC-0106:UT-08 — uma execução queued ou in_progress (com outra success): pipeline running."""
        # SPEC-0106:UT-08
        for state in ("queued", "in_progress", "waiting"):
            with self.subTest(status=state):
                self.write_scenario(runs={"*": runs(run_item(), run_item(state, n=2, workflow="Publish"))})
                self.assertStage(self.data(), "pipeline", "running")

    def test_a_failure_with_another_in_progress_is_failed(self):
        """SPEC-0106:UT-08 — completed/failure com outra em andamento: pipeline failed; failure, timed_out,
        cancelled, startup_failure e action_required contam como falha."""
        # SPEC-0106:UT-08
        self.write_scenario(runs={"*": runs(run_item("completed", "failure"), run_item("in_progress", n=2))})
        self.assertStage(self.data(), "pipeline", "failed")
        for conclusion in ("timed_out", "cancelled", "startup_failure", "action_required"):
            with self.subTest(conclusion=conclusion):
                self.write_scenario(runs={"*": runs(run_item(), run_item("completed", conclusion, n=2))})
                self.assertStage(self.data(), "pipeline", "failed")

    def test_success_neutral_and_skipped_are_ok(self):
        """SPEC-0106:UT-08 — todas completed com success, neutral ou skipped: pipeline ok, com as execuções em
        evidence.runs."""
        # SPEC-0106:UT-08
        items = (run_item(), run_item(conclusion="neutral", n=2, workflow="Lint"),
                 run_item(conclusion="skipped", n=3, workflow="Docs"))
        self.write_scenario(runs={"*": runs(*items)})
        item = self.assertStage(self.data(), "pipeline", "ok")
        self.assertEqual(len(item["evidence"].get("runs", [])), 3, item)

    def test_a_repository_without_access_is_not_verified(self):
        """SPEC-0106:UT-08 — um repositório found: false sem outra falha: pipeline not_verified (nunca ok)."""
        # SPEC-0106:UT-08
        self.write_scenario(runs={"*": runs(run_item(), {"repository": "acme/x", "found": False})})
        self.assertStage(self.data(), "pipeline", "not_verified")

    def test_service_without_code_repository(self):
        """SPEC-0106:UT-08 — serviço sem code_repositories no atlas: pipeline not_verified "serviço sem repositório
        de código no atlas", sem rodar o pipeline runs; o track não sai com 2."""
        # SPEC-0106:UT-08
        drop_code_repository(self.box.atlas)
        result = self.track()
        self.assertIn(result.returncode, (5, 6), output(result))
        data = json.loads(result.stdout)
        self.assertStage(data, "pipeline", "not_verified", reason=NO_CODE)
        self.assertEqual(self.calls("run", "fake-ci"), [])

    def test_without_a_pipeline_adapter(self):
        """SPEC-0106:UT-08 — nenhum adaptador declara pipeline: pipeline not_verified com o motivo da recusa
        ("nenhum adaptador para pipeline"); as outras etapas seguem."""
        # SPEC-0106:UT-08
        self.configure(adapters=("fake-gitops", "fake-runtime"))
        data = self.data("--expect-image", NEW)
        self.assertStage(data, "pipeline", "not_verified", reason="nenhum adaptador para pipeline")
        self.assertStage(data, "rollout", "ok")

    def test_errors_and_cut_probes(self):
        """SPEC-0106:UT-08 — probe com erro ou que quebrou: not_verified; cortada só com sucessos: not_verified;
        cortada com um failure visto: failed."""
        # SPEC-0106:UT-08
        for name, answer, expected in (("erro", {"error": "limite de requisições do GitHub"}, "not_verified"),
                                       ("quebrou", {"exit": 3, "stderr": "falhou"}, "not_verified"),
                                       ("cortada ok", runs(run_item(), truncated=True), "not_verified"),
                                       ("cortada failure", runs(run_item("completed", "failure"), truncated=True),
                                        "failed")):
            with self.subTest(case=name):
                self.write_scenario(runs={"*": answer})
                self.assertStage(self.data(), "pipeline", expected)

    def test_the_pipeline_probe_gets_the_change(self):
        """SPEC-0106:UT-08 — o pipeline runs roda uma vez, com o alvo do primeiro deployment do serviço no ambiente
        (dev-api) e target.change = {commit, repositories: ["acme/api"]}; a credencial chega só pelo nome declarado."""
        # SPEC-0106:UT-08
        add_blue(self.box.atlas)
        self.data()
        calls = self.calls("run", "fake-ci")
        self.assertEqual(len(calls), 1, calls)
        target = calls[0]["input"]["target"]
        self.assertEqual(target["deployment"], "dev-api")
        self.assertEqual(target["change"], {"commit": COMMIT, "repositories": ["acme/api"]})
        self.assertEqual(calls[0]["env"].get("GH_TOKEN"), GH_TOKEN)
        self.assertNotIn("GITHUB_TOKEN", calls[0]["env"])
        self.assertNotIn("ATLAS_GITOPS_CONTEXT", calls[0]["env"])


# --------------------------------------------------------------------------- UT-09


class ExpectedImageTest(TrackCase):
    def test_expect_image_is_normalized(self):
        """SPEC-0106:UT-09 — --expect-image ghcr.io/acme/api:1.4.2: expected_image acme/api:1.4.2, source
        expect-image; com a imagem nas da Application, image ok."""
        # SPEC-0106:UT-09
        self.write_scenario(application={"*": app(images=("acme/api:1.4.2",))},
                            status={"dev-api": status(image="acme/api:1.4.2")})
        data = self.data("--expect-image", "ghcr.io/acme/api:1.4.2")
        self.assertEqual((data["expected_image"], data["expected_image_source"]), ("acme/api:1.4.2", "expect-image"))
        self.assertStage(data, "image", "ok")

    def test_tag_with_the_commit(self):
        """SPEC-0106:UT-09 — sem --expect-image, imagens acme/api:sha-0a1b2c3 e acme/sidecar:2.0: expected_image
        acme/api:sha-0a1b2c3, source commit-tag, image ok."""
        # SPEC-0106:UT-09
        self.write_scenario(application={"*": app(images=(NEW, "acme/sidecar:2.0"))})
        data = self.data()
        self.assertEqual((data["expected_image"], data["expected_image_source"]), (NEW, "commit-tag"))
        self.assertStage(data, "image", "ok")

    def test_other_pieces_and_the_full_sha_match(self):
        """SPEC-0106:UT-09 — pedaço separado por _ ou . com 7+ caracteres do commit, ou a tag igual ao commit:
        commit-tag."""
        # SPEC-0106:UT-09
        for image in ("acme/api:1.4.2_0a1b2c3d", "acme/api:build.0a1b2c3d4e", f"acme/api:{COMMIT}"):
            with self.subTest(image=image):
                self.write_scenario(application={"*": app(images=(image,))}, status={"dev-api": status(image=image)})
                data = self.data()
                self.assertEqual((data["expected_image"], data["expected_image_source"]), (image, "commit-tag"))

    def test_a_piece_of_six_characters_does_not_match(self):
        """SPEC-0106:UT-09 — só acme/api:sha-0a1b2c (6 caracteres), pipeline ok e Application Synced/Healthy: nenhuma
        imagem esperada, image not_verified "imagem do commit não identificada: passe --expect-image"."""
        # SPEC-0106:UT-09
        self.write_scenario(application={"*": app(images=("acme/api:sha-0a1b2c",))})
        data = self.data()
        self.assertEqual((data["expected_image"], data["expected_image_source"]), ("", ""))
        self.assertStage(data, "image", "not_verified", reason=UNKNOWN_IMAGE)
        self.assertStage(data, "rollout", "not_verified")

    def test_an_image_outside_delivery_images_does_not_count(self):
        """SPEC-0106:UT-09 — acme/sidecar:sha-0a1b2c3 (fora de delivery.images = [acme/api]): não vira a imagem
        esperada."""
        # SPEC-0106:UT-09
        self.write_scenario(application={"*": app(images=("acme/sidecar:sha-0a1b2c3", OLD))})
        data = self.data()
        self.assertEqual(data["expected_image"], "")
        self.assertStage(data, "image", "not_verified", reason=UNKNOWN_IMAGE)

    def test_two_images_with_the_commit_are_ambiguous(self):
        """SPEC-0106:UT-09 — acme/api:sha-0a1b2c3 e acme/worker:0a1b2c3d, ambos em delivery.images: image
        not_verified "mais de uma imagem com o commit: passe --expect-image", sem imagem esperada."""
        # SPEC-0106:UT-09
        add_code_repository(self.box.atlas, "worker")
        self.write_scenario(application={"*": app(images=(NEW, "acme/worker:0a1b2c3d"))})
        data = self.data()
        self.assertEqual(data["expected_image"], "")
        self.assertStage(data, "image", "not_verified", reason=AMBIGUOUS)

    def test_no_image_while_the_delivery_moves_is_pending(self):
        """SPEC-0106:UT-09 — sem imagem com o commit e a pipeline running: image pending; com a Application
        OutOfSync (pipeline ok): image pending."""
        # SPEC-0106:UT-09
        self.write_scenario(runs={"*": runs(run_item("in_progress"))}, application={"*": app(images=(OLD,))})
        self.assertStage(self.data(), "image", "pending")
        self.write_scenario(runs={"*": runs(run_item())}, application={"*": app(sync="OutOfSync", images=(OLD,))})
        self.assertStage(self.data(), "image", "pending")

    def test_expected_image_not_yet_in_the_application(self):
        """SPEC-0106:UT-09 — --expect-image acme/api:1.4.2 e a Application ainda com a anterior: image pending."""
        # SPEC-0106:UT-09
        self.write_scenario(application={"*": app(images=("acme/api:1.4.1",))})
        self.assertStage(self.data("--expect-image", "acme/api:1.4.2"), "image", "pending")


# --------------------------------------------------------------------------- UT-10


class GitopsStageTest(TrackCase):
    def gitops(self, **app_args):
        self.write_scenario(application={"*": app(**app_args)})
        return self.data("--expect-image", NEW)

    def test_synced_and_healthy_is_ok(self):
        """SPEC-0106:UT-10 — image ok e Application Synced/Healthy: gitops ok."""
        # SPEC-0106:UT-10
        self.assertStage(self.gitops(), "gitops", "ok")

    def test_moving_is_running(self):
        """SPEC-0106:UT-10 — image ok e OutOfSync, Progressing ou operation_phase Running: gitops running."""
        # SPEC-0106:UT-10
        for args in ({"sync": "OutOfSync"}, {"health": "Progressing"}, {"phase": "Running"}):
            with self.subTest(**args):
                self.assertStage(self.gitops(**args), "gitops", "running")

    def test_broken_is_failed(self):
        """SPEC-0106:UT-10 — image ok e Degraded, Missing, operation_phase Failed ou Error: gitops failed."""
        # SPEC-0106:UT-10
        for args in ({"health": "Degraded"}, {"health": "Missing"}, {"phase": "Failed"}, {"phase": "Error"}):
            with self.subTest(**args):
                self.assertStage(self.gitops(**args), "gitops", "failed")

    def test_suspended_or_unknown_is_not_verified(self):
        """SPEC-0106:UT-10 — image ok e Suspended ou Unknown: gitops not_verified."""
        # SPEC-0106:UT-10
        for health in ("Suspended", "Unknown"):
            with self.subTest(health=health):
                self.assertStage(self.gitops(health=health), "gitops", "not_verified")

    def test_waiting_for_the_image(self):
        """SPEC-0106:UT-10 — image pending (a Application Synced/Healthy na versão anterior): gitops pending
        "aguardando a imagem no GitOps"."""
        # SPEC-0106:UT-10
        data = self.gitops(images=(OLD,))
        self.assertStage(data, "image", "pending")
        self.assertStage(data, "gitops", "pending", reason=WAITING)

    def test_missing_application_refused_or_failed_probe(self):
        """SPEC-0106:UT-10 — Application found: false, probe com erro, adaptador que quebra ou nenhum adaptador de
        gitops: image e gitops not_verified, com o motivo."""
        # SPEC-0106:UT-10
        for name, answer in (("ausente", app(found=False)), ("erro", {"error": "sem permissão (Forbidden)"}),
                             ("quebrou", {"exit": 2, "stderr": "falhou"})):
            with self.subTest(case=name):
                self.write_scenario(application={"*": answer})
                data = self.data("--expect-image", NEW)
                self.assertStage(data, "image", "not_verified")
                self.assertStage(data, "gitops", "not_verified")
        self.configure(adapters=("fake-ci", "fake-runtime"))
        data = self.data("--expect-image", NEW)
        self.assertStage(data, "gitops", "not_verified", reason="nenhum adaptador para gitops")


# --------------------------------------------------------------------------- UT-11


class RolloutStageTest(TrackCase):
    def rollout(self, *extra, **status_args):
        self.write_scenario(status={"dev-api": status(**status_args)})
        return self.data("--expect-image", NEW, *extra)

    def test_complete_with_the_image_is_ok(self):
        """SPEC-0106:UT-11 — rollout completo e todos os pods prontos na imagem esperada: rollout ok, state ok."""
        # SPEC-0106:UT-11
        data = self.rollout()
        self.assertStage(data, "rollout", "ok")
        self.assertEqual((data["state"], data["current_stage"]), ("ok", ""))

    def test_part_of_the_pods_is_running(self):
        """SPEC-0106:UT-11 — um pod novo e dois antigos com rollout_complete false: rollout running."""
        # SPEC-0106:UT-11
        pods = PODS["dev-api"]
        self.assertStage(self.rollout(images={pods[1]: OLD, pods[2]: OLD}, complete=False), "rollout", "running")

    def test_no_pod_with_the_image_is_pending(self):
        """SPEC-0106:UT-11 — nenhum pod na imagem esperada: rollout pending."""
        # SPEC-0106:UT-11
        self.assertStage(self.rollout(image=OLD), "rollout", "pending")

    def test_missing_workload_is_failed(self):
        """SPEC-0106:UT-11 — workload found: false: rollout failed."""
        # SPEC-0106:UT-11
        self.assertStage(self.rollout(found=False), "rollout", "failed")

    def test_a_new_pod_restarting_is_failed_with_the_pod_in_the_evidence(self):
        """SPEC-0106:UT-11 — um pod na imagem nova não pronto e com restarts 3: rollout failed, o pod na evidência."""
        # SPEC-0106:UT-11
        pod = PODS["dev-api"][2]
        item = self.assertStage(self.rollout(ready={pod: False}, restarts={pod: 3}, complete=False), "rollout",
                                "failed")
        self.assertIn(pod, json.dumps(item["evidence"]), item)

    def test_a_cut_status_probe_is_not_verified(self):
        """SPEC-0106:UT-11 — runtime status com truncated: true: rollout not_verified "probe de status cortada"."""
        # SPEC-0106:UT-11
        self.assertStage(self.rollout(truncated=True), "rollout", "not_verified", reason=CUT_STATUS)

    def test_without_expected_image_is_not_verified(self):
        """SPEC-0106:UT-11 — sem imagem esperada (nenhuma imagem com o commit): rollout not_verified."""
        # SPEC-0106:UT-11
        self.write_scenario(application={"*": app(images=(OLD,))})
        self.assertStage(self.data(), "rollout", "not_verified")

    def test_status_probe_error_or_refused(self):
        """SPEC-0106:UT-11 — runtime status com erro ou sem adaptador de runtime: rollout not_verified."""
        # SPEC-0106:UT-11
        self.write_scenario(status={"*": {"error": "sem permissão (Forbidden)"}})
        self.assertStage(self.data("--expect-image", NEW), "rollout", "not_verified")
        self.configure(adapters=("fake-ci", "fake-gitops"))
        self.assertStage(self.data("--expect-image", NEW), "rollout", "not_verified", reason="nenhum adaptador")

    def test_the_digest_decides_when_given(self):
        """SPEC-0106:UT-11 — --expect-image acme/api@sha256:<d>: pods com outra tag e o mesmo digest dão rollout ok;
        pods com a tag sha-0a1b2c3 e outro digest dão pending."""
        # SPEC-0106:UT-11
        self.write_scenario(application={"*": app(images=(f"acme/api:1.4.2@{DIGEST}",))},
                            status={"dev-api": status(image=f"acme/api:1.4.2@{DIGEST}")})
        self.assertStage(self.data("--expect-image", f"acme/api@{DIGEST}"), "rollout", "ok")
        self.write_scenario(status={"dev-api": status(image=f"{NEW}@{OTHER_DIGEST}")})
        self.assertStage(self.data("--expect-image", f"acme/api@{DIGEST}"), "rollout", "pending")

    def test_the_status_probe_asks_for_2000_lines(self):
        """SPEC-0106:UT-11 — o runtime status do track pede limits.lines 2000, como o verify."""
        # SPEC-0106:UT-11
        self.data("--expect-image", NEW)
        calls = self.calls("run", "fake-runtime")
        self.assertTrue(calls)
        self.assertEqual({c["input"]["limits"]["lines"] for c in calls}, {2000})


# --------------------------------------------------------------------------- UT-12


class StateTest(TrackCase):
    def setUp(self):
        super().setUp()
        add_blue(self.box.atlas)

    def combo(self, pipeline=None, blue_app=None, blue_status=None, api_app=None, expect=True):
        self.write_scenario(runs={"*": pipeline or runs(run_item())},
                            application={"dev-api": api_app or app("dev-api"),
                                         "dev-api-blue": blue_app or app("dev-api-blue")},
                            status={"dev-api": status("dev-api"),
                                    "dev-api-blue": blue_status or status("dev-api-blue")})
        return self.track(*(["--expect-image", NEW] if expect else []))

    def check(self, result, state, current):
        self.assertEqual(result.returncode, STATE_EXIT[state], output(result))
        data = json.loads(result.stdout)
        self.assertEqual((data["state"], data["current_stage"]), (state, current),
                         json.dumps(data, ensure_ascii=False, indent=1))
        self.assertEqual(len(data["stages"]), 1 + 3 * 2, data["stages"])
        return data

    def test_all_ok_exits_0(self):
        """SPEC-0106:UT-12 — tudo ok nos dois deployments: state ok, exit 0, current_stage ""."""
        # SPEC-0106:UT-12
        self.check(self.combo(), "ok", "")

    def test_failed_wins_and_exits_1(self):
        """SPEC-0106:UT-12 — pipeline failure: failed, exit 1, current_stage pipeline; pipeline running com o
        workload do dev-api-blue ausente: failed (vence running), current_stage pipeline."""
        # SPEC-0106:UT-12
        self.check(self.combo(pipeline=runs(run_item("completed", "failure"))), "failed", "pipeline")
        self.check(self.combo(pipeline=runs(run_item("in_progress")), blue_status=status("dev-api-blue", found=False)),
                   "failed", "pipeline")

    def test_running_exits_6(self):
        """SPEC-0106:UT-12 — dev-api ok e dev-api-blue com rollout em andamento: running, exit 6, current_stage
        rollout; pipeline running com o resto pending: running (vence pending)."""
        # SPEC-0106:UT-12
        pods = PODS["dev-api-blue"]
        self.check(self.combo(blue_status=status("dev-api-blue", images={pods[1]: OLD, pods[2]: OLD}, complete=False)),
                   "running", "rollout")
        self.check(self.combo(pipeline=runs(run_item("in_progress")), blue_app=app("dev-api-blue", images=(OLD,))),
                   "running", "pipeline")

    def test_pending_exits_6(self):
        """SPEC-0106:UT-12 — dev-api-blue com a Application ainda na imagem anterior: pending, exit 6, current_stage
        image; pipeline sem execução e dev-api-blue Suspended: pending (vence not_verified), current_stage
        pipeline."""
        # SPEC-0106:UT-12
        self.check(self.combo(blue_app=app("dev-api-blue", images=(OLD,)),
                              blue_status=status("dev-api-blue", image=OLD)), "pending", "image")
        self.check(self.combo(pipeline=runs(), blue_app=app("dev-api-blue", health="Suspended")), "pending",
                   "pipeline")

    def test_not_verified_exits_5(self):
        """SPEC-0106:UT-12 — tudo ok e dev-api-blue Suspended: not_verified, exit 5, current_stage gitops."""
        # SPEC-0106:UT-12
        self.check(self.combo(blue_app=app("dev-api-blue", health="Suspended")), "not_verified", "gitops")

    def test_current_stage_goes_stage_by_stage(self):
        """SPEC-0106:UT-12 — dev-api com gitops running e dev-api-blue com image pending: current_stage image (a
        etapa vem antes do deployment na ordem)."""
        # SPEC-0106:UT-12
        self.check(self.combo(api_app=app("dev-api", sync="OutOfSync"),
                              blue_app=app("dev-api-blue", images=(OLD,)),
                              blue_status=status("dev-api-blue", image=OLD)), "running", "image")

    def test_one_probe_of_each_kind(self):
        """SPEC-0106:UT-12 — o registro de chamadas mostra uma probe pipeline runs por track e uma gitops application
        e uma runtime status por deployment (e nenhuma outra); o probes.log tem uma linha por probe."""
        # SPEC-0106:UT-12
        self.check(self.combo(), "ok", "")
        runs_calls = self.calls("run", "fake-ci")
        gitops_calls = self.calls("run", "fake-gitops")
        runtime_calls = self.calls("run", "fake-runtime")
        self.assertEqual(len(runs_calls), 1, runs_calls)
        self.assertEqual(sorted(c["input"]["target"]["deployment"] for c in gitops_calls), ["dev-api", "dev-api-blue"])
        self.assertEqual(sorted(c["input"]["target"]["deployment"] for c in runtime_calls),
                         ["dev-api", "dev-api-blue"])
        self.assertEqual({c["input"]["verb"] for c in runtime_calls}, {"status"})
        self.assertEqual(len(self.calls("run")), 5)
        lines = self.log()
        self.assertEqual(sorted((l["capability"], l["verb"]) for l in lines),
                         sorted([("pipeline", "runs"), ("gitops", "application"), ("gitops", "application"),
                                 ("runtime", "status"), ("runtime", "status")]), lines)
        self.assertEqual({l.get("commit") for l in lines if l["capability"] == "pipeline"}, {COMMIT})


# --------------------------------------------------------------------------- UT-13


class ArgumentsTest(TrackCase):
    def test_upper_case_commit_is_accepted_in_lower_case(self):
        """SPEC-0106:UT-13 — --commit de 40 hexadecimais em maiúsculas: aceito; chega ao adaptador e à saída em
        minúsculas."""
        # SPEC-0106:UT-13
        data = self.data(commit=COMMIT.upper())
        self.assertEqual(data["commit"], COMMIT)
        self.assertEqual([c["input"]["target"]["change"]["commit"] for c in self.calls("run", "fake-ci")], [COMMIT])

    def test_short_or_non_hex_commit_exits_2(self):
        """SPEC-0106:UT-13 — --commit 0a1b2c3, com g ou de 41 caracteres: exit 2 "commit precisa ser o sha completo
        (40 hexadecimais)", sem nenhuma probe."""
        # SPEC-0106:UT-13
        for commit in ("0a1b2c3", "g" + COMMIT[1:], COMMIT + "0", COMMIT[:39]):
            with self.subTest(commit=commit):
                self.assertExit(self.track(commit=commit), 2, BAD_COMMIT)
                self.assertNoRun()
                self.assertEqual(self.log(), [])

    def test_expect_image_without_tag_exits_2(self):
        """SPEC-0106:UT-13 — --expect-image acme/api (sem tag nem digest): exit 2, sem probe."""
        # SPEC-0106:UT-13
        self.assertExit(self.track("--expect-image", "acme/api"), 2)
        self.assertNoRun()

    def test_service_without_deployment_in_the_environment_exits_2(self):
        """SPEC-0106:UT-13 — serviço worker em prod e api em qa (sem deployment): exit 2, sem probe."""
        # SPEC-0106:UT-13
        for service, env in (("worker", "prod"), ("api", "qa")):
            with self.subTest(service=service, env=env):
                self.assertExit(self.track(service=service, env=env), 2, "nenhum deployment")
                self.assertNoRun()

    def test_probes_off_exits_4_without_log(self):
        """SPEC-0106:UT-13 — probes.enabled false e sem a chave probes: exit 4 "probes desligadas", nada roda e
        nenhuma linha no probes.log."""
        # SPEC-0106:UT-13
        for opts in ({"enabled": False}, {"present": False}):
            with self.subTest(**opts):
                self.configure(**opts)
                self.assertExit(self.track(), 4, "probes desligadas")
                self.assertEqual(self.calls(), [])
                self.assertEqual(self.log_text(), "")

    def test_production_without_confirmation_exits_4(self):
        """SPEC-0106:UT-13 — ambiente sem tier (prod) e com tier production, sem --confirm-production: exit 4 antes
        de qualquer execução de adaptador; com --confirm-production, roda."""
        # SPEC-0106:UT-13
        for tiers in ({"dev": "test"}, {"dev": "test", "prod": "production"}):
            with self.subTest(tiers=tiers):
                set_tiers(self.box.atlas, tiers)
                self.assertExit(self.track(env="prod"), 4, "--confirm-production")
                self.assertNoRun()
        result = self.track("--confirm-production", "--expect-image", NEW, env="prod")
        self.assertIn(result.returncode, STATE_EXIT.values(), output(result))
        self.assertTrue(self.calls("run"))

    def test_without_local_configuration_exits_3(self):
        """SPEC-0106:UT-13 — sem config.yml local: exit 3, nada roda."""
        # SPEC-0106:UT-13
        empty = self.box.root / "sem-config"
        empty.mkdir()
        self.assertExit(self.track(config_home=empty), 3)
        self.assertNoRun()


# --------------------------------------------------------------------------- UT-14


class SafetyTest(TrackCase):
    def echoing_scenario(self):
        """O dublê ecoa a credencial, o contexto do gestor, o contexto do cluster, um host ECR e um ARN maiúsculo com
        a conta em itens e mensagens."""
        echo = f"{{{{env:GH_TOKEN}}}} {{{{env:ATLAS_GITOPS_CONTEXT}}}} {ECR_TEXT} {ARN_TEXT}"
        self.write_scenario(
            runs={"*": runs(run_item(workflow=f"Build {echo}"), run_item(n=2, workflow="Push",
                                                                         path=f"push to {ECR_TEXT}",
                                                                         event=ARN_TEXT))},
            application={"*": {"items": [dict(app()["items"][0], revision=f"{{{{target:context}}}} {echo}")],
                               "truncated": False, "message": f"{{{{target:context}}}} {echo}"}},
            status={"dev-api": {"items": [dict(i, last_termination=f"{{{{target:context}}}} {echo}")
                                          if i["kind"] == "pod" else i for i in status()["items"]],
                                "truncated": False, "message": f"{{{{target:context}}}} {echo}"}})

    def test_nothing_written_and_nothing_leaked_with_json(self):
        """SPEC-0106:UT-14 — com o dublê ecoando GH_TOKEN, ATLAS_GITOPS_CONTEXT, o contexto, o host ECR e o ARN
        maiúsculo: o --json (evidências incluídas) e o probes.log sem nenhum desses valores nem a conta; a pasta do
        atlas igual e só o probes.log a mais na configuração local (conferido em track())."""
        # SPEC-0106:UT-14
        self.echoing_scenario()
        data = self.data("--expect-image", NEW)
        self.assertTrue(self.calls("run", "fake-ci"), "o dublê não rodou")
        runs_seen = self.stage(data, "pipeline")["evidence"].get("runs", [])
        self.assertTrue(runs_seen, "evidence.runs vazia: o eco não foi exercitado")
        self.assertTrue(self.box.config_home.joinpath("probes.log").exists())

    def test_errors_with_the_values_in_the_message_are_masked(self):
        """SPEC-0106:UT-14 — probes que respondem com erro trazendo os valores na mensagem: nada sai nos motivos."""
        # SPEC-0106:UT-14
        echo = f"{{{{env:GH_TOKEN}}}} {{{{env:ATLAS_GITOPS_CONTEXT}}}} {ECR_TEXT} {ARN_TEXT}"
        self.write_scenario(runs={"*": {"error": f"falhou {echo}"}},
                            application={"*": {"error": f"falhou {{{{target:context}}}} {echo}"}},
                            status={"*": {"error": f"falhou {{{{target:context}}}} {echo}"}})
        self.track("--expect-image", NEW)
        self.track("--expect-image", NEW, as_json=False)

    def test_markdown_output(self):
        """SPEC-0106:UT-14 — sem --json: o estado, a etapa atual, a imagem esperada e uma tabela etapa | deployment |
        status | motivo, sem nenhum texto de comando (gh, kubectl, argocd) e sem os valores ecoados."""
        # SPEC-0106:UT-14
        self.write_scenario(application={"*": app(sync="OutOfSync")})
        result = self.track(as_json=False)
        self.assertExit(result, 6)
        text = result.stdout
        for value in ("running", "gitops", NEW):
            self.assertIn(value, text)
        header = [line for line in text.splitlines() if line.count("|") >= 3 and all(
            word in line.lower() for word in ("etapa", "deployment", "status", "motivo"))]
        self.assertTrue(header, f"sem a tabela etapa | deployment | status | motivo:\n{text}")
        self.assertIsNone(COMMAND_RE.search(text), text)
        self.echoing_scenario()
        self.track("--expect-image", NEW, as_json=False)

    def test_core_mask_covers_ecr_host_and_upper_case_arn(self):
        """SPEC-0106:UT-14 (Emenda v2) — probe_mask com probe_extras: a conta some do host ECR
        (<conta>.dkr.ecr.<região>.amazonaws.com, também em .cn) e do ARN em maiúsculas; o ARN minúsculo e a URL de fila
        seguem mascarados; a imagem sem conta não é mexida."""
        # SPEC-0106:UT-14
        mask, extras = fn("probe_mask", SPEC), fn("probe_extras", SPEC)({})
        for text in (ECR_TEXT, f"https://{ECR_TEXT}", f"{ACCOUNT}.dkr.ecr.cn-north-1.amazonaws.com.cn/acme/api:1",
                     f"pull {ACCOUNT}.DKR.ECR.US-EAST-1.AMAZONAWS.COM/acme/api", ARN_TEXT,
                     f"Arn:Aws:Sqs:us-east-1:{ACCOUNT}:orders", f"arn:aws:sqs:us-east-1:{ACCOUNT}:orders",
                     f"https://sqs.us-east-1.amazonaws.com/{ACCOUNT}/orders"):
            with self.subTest(text=text):
                masked = mask(text, extras)
                self.assertNotIn(ACCOUNT, masked)
                self.assertIn("[REDACTED]", masked)
        self.assertEqual(mask("acme/api:sha-0a1b2c3", extras), "acme/api:sha-0a1b2c3")


# --------------------------------------------------------------------------- CT-02


class ContractTest(TrackCase):
    def valid_result(self):
        return self.data("--expect-image", NEW)

    def test_validate_track_result_refuses_broken_results(self):
        """SPEC-0106:CT-02 — validate_track_result aceita a saída real e recusa: chave a mais (no topo e numa etapa),
        stage fora da lista, status fora da lista, reason vazio fora de ok, contract diferente."""
        # SPEC-0106:CT-02
        validate = f("validate_track_result")
        data = self.valid_result()
        self.assertEqual(validate(data), [])
        broken = []
        extra = copy.deepcopy(data)
        extra["verdict"] = "passou"
        broken.append(("chave a mais", extra))
        extra_stage = copy.deepcopy(data)
        extra_stage["stages"][0]["command"] = "x"
        broken.append(("chave a mais na etapa", extra_stage))
        for key, value in (("stage", "deploy"), ("status", "degradou")):
            changed = copy.deepcopy(data)
            changed["stages"][0][key] = value
            broken.append((f"{key} fora", changed))
        empty = copy.deepcopy(data)
        empty["stages"][0].update(status="not_verified", reason="")
        empty["state"], empty["current_stage"] = "not_verified", empty["stages"][0]["stage"]
        broken.append(("reason vazio", empty))
        contract = copy.deepcopy(data)
        contract["contract"] = "verify@1"
        broken.append(("contract", contract))
        for name, value in broken:
            with self.subTest(case=name):
                problems = validate(value)
                self.assertTrue(problems and all(isinstance(p, str) and p for p in problems), problems)

    def test_examples_of_verify_md(self):
        """SPEC-0106:CT-02 — references/verify.md traz blocos ```json track@1 valid|invalid (ao menos um válido e
        um inválido); validate_track_result aceita os válidos e recusa os inválidos, como o rótulo diz; os válidos
        também passam no validador desta suíte."""
        # SPEC-0106:CT-02
        self.assertTrue(VERIFY_DOC.is_file())
        blocks = doc_blocks()
        self.assertTrue([b for b in blocks if b[0] == "valid"], "sem bloco json track@1 valid em verify.md")
        self.assertTrue([b for b in blocks if b[0] == "invalid"], "sem bloco json track@1 invalid em verify.md")
        validate = f("validate_track_result")
        for label, data in blocks:
            with self.subTest(label=label, data=json.dumps(data)[:80]):
                if label == "valid":
                    self.assertEqual(validate(data), [])
                    self.assertEqual(track_problems(data), [])
                else:
                    self.assertTrue(validate(data))


# --------------------------------------------------------------------------- IT-01 e IT-02


def install_gh(folder: Path, record: Path, fixtures):
    folder.mkdir(parents=True, exist_ok=True)
    body = FAKE_GH.read_text(encoding="utf-8").split("\n", 1)[1]
    target = folder / "gh"
    target.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (folder / "fake-gh.json").write_text(json.dumps({"record": str(record), "fixtures": [str(fixtures)],
                                                     "echo": GH_TOKEN}), encoding="utf-8")


def install_kubectl(folder: Path, record: Path, state: Path):
    """O kubectl falso da SPEC-0106 em `folder` e, numa subpasta, o da SPEC-0089 para as leituras de runtime, os dois
    com as respostas do estado `state`."""
    runtime_dir = folder / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    body = FAKE_RUNTIME_KUBECTL.read_text(encoding="utf-8").split("\n", 1)[1]
    runtime = runtime_dir / "kubectl-runtime"
    runtime.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    (runtime_dir / "fake-kubectl.json").write_text(json.dumps(
        {"record": str(record.with_name(record.stem + "-runtime.jsonl")), "fixtures": [str(state)], "fail": "",
         "pod_fail": {}, "now": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}), encoding="utf-8")
    body = FAKE_TRACK_KUBECTL.read_text(encoding="utf-8").split("\n", 1)[1]
    target = folder / "kubectl"
    target.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (folder / "fake-kubectl.json").write_text(json.dumps({"record": str(record), "fixtures": [str(state)],
                                                          "fail": "", "echo": CONTEXT, "runtime": str(runtime)}),
                                              encoding="utf-8")


def read_argvs(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class EndToEndTest(unittest.TestCase):
    """Atlas temporário (serviço api com code_repositories [acme/api] e config_repositories [acme/iac], dev-api em dev
    tier test no cluster-dev com access.clusters), as probes ligadas com os adaptadores github-actions (credentials
    GH_TOKEN), argocd e kubernetes da skill (sem command) e o gh e o kubectl falsos no início do PATH."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        shutil.copytree(ATLAS_FIXTURE, self.box.atlas)
        graph = graph_of(self.box.atlas)
        for node in graph["nodes"]:
            if node["key"] == "repository:acme/gitops":
                node.update(key="repository:acme/iac", name="iac")
        for item in graph["edges"]:
            for end in ("from", "to"):
                if item[end] == "repository:acme/gitops":
                    item[end] = "repository:acme/iac"
        save_graph(self.box.atlas, graph)
        adapters = ('    github-actions:\n      verbs: ["runs"]\n      timeout: 120\n      credentials: ["GH_TOKEN"]\n'
                    '    argocd:\n      verbs: ["application"]\n      timeout: 120\n'
                    '    kubernetes:\n      verbs: ["status", "events", "logs"]\n      timeout: 120\n')
        self.box.write_local(f"atlas: {json.dumps(str(self.box.atlas))}\ncredentials: {{}}\n" + access_yaml()
                             + probes_yaml([adapters]))
        self.bin = self.box.root / "bin"
        self.gh_record = self.box.root / "gh-calls.jsonl"
        self.kube_record = self.box.root / "kubectl-calls.jsonl"
        self.task = self.box.root / "task"
        self.task.mkdir()

    def state(self, kube, gh=None):
        install_gh(self.bin / "gh", self.gh_record, (STATES / (gh or kube) / "gh"))
        install_kubectl(self.bin / "kube", self.kube_record, STATES / kube)

    def reset_records(self):
        for path in (self.gh_record, self.kube_record):
            path.unlink(missing_ok=True)

    def run_atlas(self, *args):
        for name in ("github-actions", "argocd"):
            path = SKILL / "assets" / "probes" / f"{name}.py"
            self.assertTrue(path.is_file(), f"{path.relative_to(SKILL)} não existe ({SPEC})")
        before = snapshot(self.box.atlas)
        env = {"PATH": f"{self.bin / 'gh'}{os.pathsep}{self.bin / 'kube'}{os.pathsep}{os.environ.get('PATH', '')}",
               "GH_TOKEN": GH_TOKEN, "GITHUB_TOKEN": UNDECLARED}
        result = self.box.run(*args, env=env)
        text = output(result)
        self.assertNotIn("Traceback", text, text)
        self.assertNotIn("invalid choice", text, f"atlas.py ainda não tem verify track ({SPEC})")
        self.assertEqual(snapshot(self.box.atlas), before, "o verify mudou a pasta do atlas")
        log = self.box.config_home / "probes.log"
        everything = (text + (log.read_text(encoding="utf-8") if log.exists() else "")).lower()
        for secret in SECRETS:
            self.assertNotIn(secret.lower(), everything, f"{secret} apareceu na saída ou no probes.log")
        return result

    def track(self, *extra):
        result = self.run_atlas("verify", "track", "--service", "api", "--env", "dev", "--commit", COMMIT, "--json",
                                *extra)
        data = json.loads(result.stdout) if result.stdout.strip().startswith("{") else None
        self.assertIsNotNone(data, output(result))
        self.assertEqual(track_problems(data), [], json.dumps(data, ensure_ascii=False, indent=1))
        self.assertEqual(f("validate_track_result")(data), [], data)
        self.assertEqual(result.returncode, STATE_EXIT[data["state"]], output(result))
        return result, data

    def assertOnlyReads(self, track_phase):
        """Todo argv do gh é o GET de acme/api; todo argv do kubectl do track começa com get; nenhum tem verbo de
        escrita."""
        gh = read_argvs(self.gh_record)
        for row in gh:
            self.assertEqual(row["argv"], ["api", "-X", "GET", "repos/acme/api/actions/runs", "-f",
                                           f"head_sha={COMMIT}", "-f", "per_page=100"], row)
            self.assertEqual(row["gh_token"], GH_TOKEN)
            self.assertNotIn("GITHUB_TOKEN", row["env_names"])
        kube = [row["argv"] for row in read_argvs(self.kube_record)]
        for argv in kube:
            self.assertEqual(argv[0], "get" if track_phase else argv[0], argv)
            self.assertIn(argv[0], ("get", "logs"), argv)
        for argv in [row["argv"] for row in gh] + kube:
            for word in FORBIDDEN_WORDS:
                self.assertNotIn(word, argv, argv)
        return gh, kube

    def test_ci_then_gitops_then_rollout_then_compare_passes(self):
        """SPEC-0106:IT-01 — verify snapshot no estado antes; track real três vezes com o dublê passando de estado:
        CI in_progress -> exit 6, running, current_stage pipeline; CI success e Application OutOfSync com
        acme/api:sha-0a1b2c3 -> exit 6, current_stage gitops; Application Synced/Healthy e pods prontos -> exit 0, ok,
        expected_image acme/api:sha-0a1b2c3. Depois, verify compare --expect-image <expected_image> com a foto dá
        passou. Uma chamada ao gh e uma get applications por track; só leituras; probes.log com uma linha por probe,
        todas ok."""
        # SPEC-0106:IT-01
        photo = self.task / "foto.json"
        self.state("antes")
        result = self.run_atlas("verify", "snapshot", "--service", "api", "--env", "dev", "--out", photo)
        self.assertEqual(result.returncode, 0, output(result))
        log = self.box.config_home / "probes.log"
        log.unlink(missing_ok=True)
        expected = [("ci", "running", "pipeline", ""), ("gitops", "running", "gitops", NEW),
                    ("pronto", "ok", "", NEW)]
        for state, want, current, image in expected:
            with self.subTest(state=state):
                self.reset_records()
                self.state(state)
                result, data = self.track()
                self.assertEqual((data["state"], data["current_stage"], data["expected_image"]), (want, current, image),
                                 json.dumps(data, ensure_ascii=False, indent=1))
                self.assertEqual(result.returncode, 0 if want == "ok" else 6)
                gh, kube = self.assertOnlyReads(track_phase=True)
                self.assertEqual(len(gh), 1, gh)
                self.assertEqual(len([a for a in kube if a[:2] == ["get", "applications.argoproj.io"]]), 1, kube)
        self.assertEqual(data["expected_image_source"], "commit-tag")
        lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 9, lines)
        self.assertEqual({l["status"] for l in lines}, {"ok"}, lines)
        self.assertEqual(sorted({(l["capability"], l["verb"], l["adapter"]) for l in lines}),
                         [("gitops", "application", "argocd"), ("pipeline", "runs", "github-actions"),
                          ("runtime", "status", "kubernetes")])
        self.reset_records()
        result = self.run_atlas("verify", "compare", "--service", "api", "--env", "dev", "--baseline", photo,
                                "--expect-image", data["expected_image"], "--json")
        compared = json.loads(result.stdout)
        self.assertEqual((result.returncode, compared["verdict"]), (0, "passou"),
                         json.dumps(compared, ensure_ascii=False, indent=1))
        self.assertOnlyReads(track_phase=False)

    def test_ci_failure_and_production_without_confirmation(self):
        """SPEC-0106:IT-02 — CI completed/failure: track real sai com 1, state failed, current_stage pipeline e a
        execução com a URL (sem query) na evidência, sem chamada de escrita. Com o ambiente trocado para tier
        production e sem --confirm-production: exit 4 e os registros dos dois dublês vazios."""
        # SPEC-0106:IT-02
        self.state("ci", gh="falha")
        result, data = self.track()
        self.assertEqual((result.returncode, data["state"], data["current_stage"]), (1, "failed", "pipeline"))
        pipeline = next(s for s in data["stages"] if s["stage"] == "pipeline")
        evidence = json.dumps(pipeline["evidence"])
        self.assertIn("https://github.com/acme/api/actions/runs/2002", evidence)
        self.assertNotIn("check_suite_focus", evidence)
        self.assertOnlyReads(track_phase=True)
        set_tiers(self.box.atlas, {"dev": "production"})
        self.reset_records()
        result = self.run_atlas("verify", "track", "--service", "api", "--env", "dev", "--commit", COMMIT, "--json")
        self.assertEqual(result.returncode, 4, output(result))
        self.assertEqual(read_argvs(self.gh_record), [])
        self.assertEqual(read_argvs(self.kube_record), [])


if __name__ == "__main__":
    unittest.main()
