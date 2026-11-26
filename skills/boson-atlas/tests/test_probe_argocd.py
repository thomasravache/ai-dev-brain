"""Adaptador argocd: a Application do Argo CD de um deployment, lida com `kubectl get` (SPEC-0106: UT-05 a UT-07 e a
parte do adaptador no CT-01; ADR-0010, ADR-0023, ADR-0025; regra de imagem da SPEC-0082).

Contrato (seção 6 da SPEC-0106) que estes testes fixam:

    assets/probes/argocd.py [--app-namespace <ns>] --describe ->
        {"contract": "probe@2", "adapter": "argocd", "capabilities": {"gitops": {"verbs": ["application"],
         "targets": ["deployment"], "access": ["cluster"]}}}
    entrada probe@2 (target.deployment = o nome da Application, target.context); saída probe@2, exit 0 também no
    erro (status "error", items [], mensagem fixa, sem o stderr do kubectl).
    kubectl: exatamente `get applications.argoproj.io <deployment> -n <app-namespace> -o json --context=<contexto>
        --request-timeout=20s` (app-namespace padrão argocd; contexto = ATLAS_GITOPS_CONTEXT quando definida no
        ambiente do adaptador, senão target.context).
    application -> um item {application, found, sync_status, health_status, revision, operation_phase,
        operation_finished_at, reconciled_at, images}; NotFound -> {application, found: false}.

Leituras desta suíte (listadas no relatório do test-writer):
    - O argv é exatamente o da seção 6, nessa ordem e com "=" em --context e --request-timeout.
    - As opções do command local chegam antes de --describe (o núcleo acrescenta --describe ao fim do command).
    - `images` é comparado como conjunto (a spec não fixa a ordem); referência fora da regra (credencial, espaço) não
      sai, e o host do registro sai (também o host ECR com a conta).
    - Texto ausente -> ""; `images` ausente -> [].
    - Verbo fora de `application` -> "entrada inválida" ou "chamada não permitida" (a spec aceita os dois).
    - "status não é objeto" -> "resposta inválida do kubectl".
    - O timeout do processo (30 s) não é exercitado com espera: o "timeout" vem do texto do kubectl real.

Dublê: fixtures/delivery-track/fake_kubectl.py, copiado como `kubectl` numa pasta temporária (o único item do PATH),
com as Applications de fixtures/delivery-track/argocd/applications.json (a dev-api traz spec.source.helm.values com
"password: s3cr3t" e a anotação last-applied-configuration). Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME
temporários; nenhum cluster, nenhuma rede; nomes acme.
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
ADAPTER = SKILL / "assets" / "probes" / "argocd.py"
REFERENCE = SKILL / "references" / "probes" / "argocd.md"
TRACK = TESTS / "fixtures" / "delivery-track"
FAKE_KUBECTL = TRACK / "fake_kubectl.py"
APPS = TRACK / "argocd"

CONTEXT = "ctx-local-dev-0106"
GITOPS_CONTEXT = "ctx-gestao-0106"
SENTINEL = "SENTINEL-STDERR-0106"
ACCOUNT = "123456789012"
HIDDEN = ("s3cr3t", "password", "last-applied", "repoURL", "github.com/acme/iac", "helm", "resources", "ghcr.io",
          "registry.example.com", "user:pass", "amazonaws.com", ACCOUNT, SENTINEL)

DESCRIBE = {"contract": "probe@2", "adapter": "argocd",
            "capabilities": {"gitops": {"verbs": ["application"], "targets": ["deployment"], "access": ["cluster"]}}}
ITEM_KEYS = {"application", "found", "sync_status", "health_status", "revision", "operation_phase",
             "operation_finished_at", "reconciled_at", "images"}
EXPECTED_DEV_API = {"application": "dev-api", "found": True, "sync_status": "Synced", "health_status": "Healthy",
                    "revision": "4f1c2d3e5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d", "operation_phase": "Succeeded",
                    "operation_finished_at": "2026-11-24T10:09:00Z", "reconciled_at": "2026-11-24T10:10:00Z",
                    "images": ["acme/api:sha-0a1b2c3"]}
INVALID_INPUT = "entrada inválida"
REFUSED = "chamada não permitida"
ERRORS = {"forbidden": "sem permissão (Forbidden)", "nocontext": "contexto inexistente", "timeout": "timeout",
          "nocrd": "Argo CD ausente no cluster", "fail": "falha do kubectl",
          "invalid-json": "resposta inválida do kubectl"}
FORBIDDEN_OPTIONS = ("-A", "--all-namespaces", "-l", "--selector", "--raw", "--kubeconfig", "-w", "--watch")


def f(name):
    return fn(name, "SPEC-0096")


def install_kubectl(folder: Path, record: Path, fixtures=(APPS,), fail="", runtime=None) -> Path:
    """Copia o kubectl falso da SPEC-0106 como `kubectl` (cabeçalho com o Python dos testes) e grava o cenário ao
    lado dele."""
    folder.mkdir(parents=True, exist_ok=True)
    body = FAKE_KUBECTL.read_text(encoding="utf-8").split("\n", 1)[1]
    target = folder / "kubectl"
    target.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    scenario = {"record": str(record), "fixtures": [str(p) for p in fixtures], "fail": fail, "echo": CONTEXT}
    if runtime:
        scenario["runtime"] = str(runtime)
    (folder / "fake-kubectl.json").write_text(json.dumps(scenario), encoding="utf-8")
    return target


def read_calls(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line)["argv"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def allowed_argv(name="dev-api", namespace="argocd", context=CONTEXT) -> list:
    """SPEC-0106:UT-05 — o único argv permitido."""
    return ["get", "applications.argoproj.io", name, "-n", namespace, "-o", "json", f"--context={context}",
            "--request-timeout=20s"]


def probe_input(deployment="dev-api", context=CONTEXT, verb="application"):
    return {"contract": "probe@2", "capability": "gitops", "verb": verb,
            "target": {"service": "api", "environment": "dev", "deployment": deployment,
                       "clusters": ["cluster-dev"], "context": context, "namespace": "api-dev",
                       "workloads": ["Deployment/api"]},
            "limits": {"lines": 200, "since_seconds": 1800}}


class ArgocdCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "kube-bin"
        self.record = self.root / "kubectl-calls.jsonl"

    def install(self, fail="", fixtures=(APPS,)):
        self.record.unlink(missing_ok=True)
        install_kubectl(self.bin, self.record, fixtures=fixtures, fail=fail)

    def environment(self, with_kubectl=True, gitops_context=None):
        empty = self.root / "empty-bin"
        empty.mkdir(exist_ok=True)
        env = {"PATH": str(self.bin if with_kubectl else empty), "HOME": str(self.home),
               "XDG_CONFIG_HOME": str(self.home / ".config"), "ATLAS_CONFIG_HOME": str(self.root / "config-home"),
               "LANG": "C.UTF-8"}
        if gitops_context is not None:
            env["ATLAS_GITOPS_CONTEXT"] = gitops_context
        for name in ("TMPDIR", "SYSTEMROOT"):
            if name in os.environ:
                env[name] = os.environ[name]
        return env

    def adapter(self, *args, stdin="", with_kubectl=True, gitops_context=None):
        self.assertTrue(ADAPTER.is_file(), f"{ADAPTER.relative_to(SKILL)} não existe ({SPEC})")
        result = subprocess.run([sys.executable, str(ADAPTER), *args], input=stdin, capture_output=True, text=True,
                                cwd=self.root, env=self.environment(with_kubectl, gitops_context), timeout=120,
                                check=False)
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        return result

    def run_probe(self, data, *args, with_kubectl=True, gitops_context=None):
        """Roda o adaptador; confere exit 0, a saída probe@2 (validador do núcleo), nada sensível na saída (UT-07),
        as chaves dos itens e todo argv contra a lista fechada (UT-07)."""
        result = self.adapter(*args, stdin=json.dumps(data), with_kubectl=with_kubectl,
                              gitops_context=gitops_context)
        self.assertEqual(result.returncode, 0, output(result))
        text = output(result)
        for value in (CONTEXT, GITOPS_CONTEXT, *HIDDEN):
            self.assertNotIn(value, text, f"{value} apareceu na saída do adaptador")
        out = json.loads(result.stdout)
        self.assertEqual(f("validate_probe_output")(out), [], out)
        self.assertEqual({k: out.get(k) for k in ("contract", "adapter", "capability")},
                         {"contract": "probe@2", "adapter": "argocd", "capability": "gitops"})
        if out["status"] == "ok":
            self.assertEqual(len(out["items"]), 1, out)
            item = out["items"][0]
            self.assertEqual(set(item), ITEM_KEYS if item.get("found") else {"application", "found"}, item)
        self.assertCallsInTheList()
        return out

    def calls(self):
        return read_calls(self.record)

    def assertCallsInTheList(self):
        """SPEC-0106:UT-07 — todo argv começa com get applications.argoproj.io e não tem -A, -l, --raw nem
        --kubeconfig; no máximo um por execução."""
        # SPEC-0106:UT-07
        calls = self.calls()
        self.assertLessEqual(len(calls), 1, calls)
        for argv in calls:
            self.assertEqual(argv[:2], ["get", "applications.argoproj.io"], argv)
            for option in FORBIDDEN_OPTIONS:
                self.assertFalse([a for a in argv if a == option or a.startswith(option + "=")], argv)
            for word in ("patch", "annotate", "apply", "delete", "edit", "sync", "rollback"):
                self.assertNotIn(word, argv)

    def assertError(self, out, message):
        self.assertEqual(out["status"], "error", out)
        self.assertEqual(out["items"], [], out)
        self.assertEqual(out.get("message"), message, out)

    def ok(self, data, *args, gitops_context=None):
        out = self.run_probe(data, *args, gitops_context=gitops_context)
        self.assertEqual(out["status"], "ok", out)
        return out


def same_images(item):
    return dict(item, images=sorted(item["images"]))


# --------------------------------------------------------------------------- UT-05


class ApplicationTest(ArgocdCase):
    def test_application_fields_and_argv(self):
        """SPEC-0106:UT-05 — a Application dev-api (Synced, Healthy, revision, operationState Succeeded,
        summary.images com ghcr.io/acme/api:sha-0a1b2c3): o item do contrato com images ["acme/api:sha-0a1b2c3"] e o
        argv get applications.argoproj.io dev-api -n argocd -o json --context=<ctx> --request-timeout=20s."""
        # SPEC-0106:UT-05
        self.install()
        out = self.ok(probe_input())
        self.assertEqual(out["items"], [EXPECTED_DEV_API])
        self.assertIs(out["truncated"], False)
        self.assertEqual(self.calls(), [allowed_argv()])

    def test_app_namespace_option(self):
        """SPEC-0106:UT-05 — com --app-namespace gitops no command, o argv usa -n gitops (e lê a Application desse
        namespace, OutOfSync na fixture)."""
        # SPEC-0106:UT-05
        self.install()
        out = self.ok(probe_input(), "--app-namespace", "gitops")
        self.assertEqual(self.calls(), [allowed_argv(namespace="gitops")])
        self.assertEqual(out["items"][0]["sync_status"], "OutOfSync")
        self.assertEqual(out["items"][0]["revision"], "9e9e9e9e")

    def test_management_cluster_context(self):
        """SPEC-0106:UT-05 — com ATLAS_GITOPS_CONTEXT definida no ambiente do adaptador, o argv usa esse contexto no
        lugar de target.context; o valor não sai."""
        # SPEC-0106:UT-05
        self.install()
        self.ok(probe_input(), gitops_context=GITOPS_CONTEXT)
        self.assertEqual(self.calls(), [allowed_argv(context=GITOPS_CONTEXT)])

    def test_revisions_of_a_multi_source_application_and_the_image_rule(self):
        """SPEC-0106:UT-05 — Application com spec.sources e status.sync.revisions (sem revision): revision é o
        primeiro; images pela regra da SPEC-0082/kubernetes: tag e digest ficam, o host do registro (também o ECR
        com a conta) sai, referência com credencial ou espaço não sai."""
        # SPEC-0106:UT-05
        self.install()
        out = self.ok(probe_input("dev-multi"))
        item = out["items"][0]
        self.assertEqual(item["revision"], "aaa111")
        self.assertEqual(sorted(item["images"]), sorted(["acme/web:2.0@sha256:" + "ab" * 32, "acme/worker:3.1"]))

    def test_missing_texts_become_empty(self):
        """SPEC-0106:UT-05 — Application sem status: sync_status, health_status, revision, operation_phase,
        operation_finished_at e reconciled_at "" e images []."""
        # SPEC-0106:UT-05
        self.install()
        out = self.ok(probe_input("dev-bare"))
        self.assertEqual(out["items"], [{"application": "dev-bare", "found": True, "sync_status": "",
                                         "health_status": "", "revision": "", "operation_phase": "",
                                         "operation_finished_at": "", "reconciled_at": "", "images": []}])


# --------------------------------------------------------------------------- UT-06


class ErrorTest(ArgocdCase):
    def test_missing_application(self):
        """SPEC-0106:UT-06 — Application inexistente (NotFound): {"application": "dev-ghost", "found": false}."""
        # SPEC-0106:UT-06
        self.install()
        out = self.ok(probe_input("dev-ghost"))
        self.assertEqual(out["items"], [{"application": "dev-ghost", "found": False}])
        self.assertEqual(self.calls(), [allowed_argv("dev-ghost")])

    def test_kubectl_missing_from_the_path(self):
        """SPEC-0106:UT-06 — sem kubectl no PATH: "kubectl não encontrado"."""
        # SPEC-0106:UT-06
        self.install()
        self.assertError(self.run_probe(probe_input(), with_kubectl=False), "kubectl não encontrado")

    def test_kubectl_failures_become_fixed_messages(self):
        """SPEC-0106:UT-06 — Forbidden, contexto inexistente, timeout, "the server doesn't have a resource type",
        outra falha e JSON inválido: a mensagem fixa do contrato, items [], sem traceback, sem o stderr nem o
        contexto."""
        # SPEC-0106:UT-06
        for mode, message in ERRORS.items():
            with self.subTest(mode=mode):
                self.install(fail=mode)
                self.assertError(self.run_probe(probe_input()), message)

    def test_status_that_is_not_an_object(self):
        """SPEC-0106:UT-06 — Application cujo status não é objeto: "resposta inválida do kubectl"."""
        # SPEC-0106:UT-06
        self.install()
        self.assertError(self.run_probe(probe_input("dev-broken")), "resposta inválida do kubectl")


# --------------------------------------------------------------------------- UT-07


class AllowListTest(ArgocdCase):
    def test_secrets_of_the_application_never_leave(self):
        """SPEC-0106:UT-07 — a dev-api da fixture tem spec.source.helm.values com password: s3cr3t, repoURL, a
        anotação last-applied-configuration e status.resources: nada disso aparece na saída (run_probe)."""
        # SPEC-0106:UT-07
        raw = (APPS / "applications.json").read_text(encoding="utf-8")
        for value in ("s3cr3t", "last-applied-configuration", "repoURL", "resources"):
            self.assertIn(value, raw, "a fixture perdeu o dado sensível que o teste procura")
        self.install()
        out = self.ok(probe_input())
        self.assertEqual(out["items"], [EXPECTED_DEV_API])

    def test_names_and_namespaces_out_of_dns_1123_are_refused_without_any_call(self):
        """SPEC-0106:UT-07 — nome de Application fora do DNS-1123 (maiúsculas, _, espaço, começando com - ou .,
        mais de 253) ou --app-namespace fora do rótulo DNS-1123 (maiúsculas, começando com -, mais de 63, com .):
        recusado sem nenhuma chamada; contexto começando com -: idem."""
        # SPEC-0106:UT-07
        for name in ("-dev-api", "Dev-Api", "dev_api", "dev api", ".dev-api", "a" * 254, "dev-api/x"):
            with self.subTest(application=name):
                self.install()
                out = self.run_probe(probe_input(name))
                self.assertEqual((out["status"], out["items"]), ("error", []), out)
                self.assertIn(out.get("message"), (INVALID_INPUT, REFUSED))
                self.assertEqual(self.calls(), [])
        for namespace in ("-gitops", "GitOps", "a" * 64, "git.ops", "git_ops"):
            with self.subTest(namespace=namespace):
                self.install()
                result = self.adapter("--app-namespace", namespace, stdin=json.dumps(probe_input()))
                self.assertEqual(self.calls(), [], output(result))
                if result.returncode == 0 and result.stdout.strip():
                    out = json.loads(result.stdout)
                    self.assertEqual(out.get("status"), "error", out)
                    self.assertIn(out.get("message"), (INVALID_INPUT, REFUSED))
        with self.subTest(context="-x"):
            self.install()
            out = self.run_probe(probe_input(context="--kubeconfig=/tmp/x"))
            self.assertEqual(out["status"], "error", out)
            self.assertEqual(self.calls(), [])

    def test_other_verbs_are_refused_without_any_call(self):
        """SPEC-0106:UT-07 — verbo diferente de application (sync, refresh, rollback, list): "entrada inválida" ou
        "chamada não permitida", sem chamada."""
        # SPEC-0106:UT-07
        for verb in ("sync", "refresh", "rollback", "list"):
            with self.subTest(verb=verb):
                self.install()
                out = self.run_probe(probe_input(verb=verb))
                self.assertEqual((out["status"], out["items"]), ("error", []), out)
                self.assertIn(out.get("message"), (INVALID_INPUT, REFUSED))
                self.assertEqual(self.calls(), [])

    def test_input_out_of_the_contract_is_refused(self):
        """SPEC-0106:UT-07 — sem target.context, com capability errada ou contract probe@1: "entrada inválida" sem
        chamada."""
        # SPEC-0106:UT-07
        no_context = probe_input()
        del no_context["target"]["context"]
        for name, data in (("sem context", no_context), ("capability", dict(probe_input(), capability="pipeline")),
                           ("probe@1", dict(probe_input(), contract="probe@1"))):
            with self.subTest(case=name):
                self.install()
                out = self.run_probe(data)
                self.assertEqual((out["status"], out.get("message")), ("error", INVALID_INPUT), out)
                self.assertEqual(self.calls(), [])


# --------------------------------------------------------------------------- CT-01

DOC_BLOCK_RE = re.compile(r"```json probe@2 (describe|input|output) (valid|invalid)[ \t]*\n(.*?)```", re.DOTALL)
VALIDATORS = {"describe": "validate_probe_describe", "input": "validate_probe_input",
              "output": "validate_probe_output"}


class ContractTest(ArgocdCase):
    def test_describe_follows_probe_2(self):
        """SPEC-0106:CT-01 — `argocd.py --describe` (também com --app-namespace antes) imprime exatamente a descrição
        do contrato, aceita pelo validate_probe_describe do núcleo, sem chamar o kubectl."""
        # SPEC-0106:CT-01
        self.install()
        for args in (("--describe",), ("--app-namespace", "gitops", "--describe")):
            with self.subTest(args=args):
                result = self.adapter(*args)
                self.assertEqual(result.returncode, 0, output(result))
                data = json.loads(result.stdout)
                self.assertEqual(data, DESCRIBE)
                self.assertEqual(f("validate_probe_describe")(data), [])
        self.assertEqual(self.calls(), [])

    def test_real_inputs_and_outputs_pass_the_core_validators(self):
        """SPEC-0106:CT-01 — a entrada usada passa no validate_probe_input; as saídas reais (ok, NotFound e cada erro)
        passam no validate_probe_output (run_probe)."""
        # SPEC-0106:CT-01
        self.assertEqual(f("validate_probe_input")(probe_input()), [])
        self.install()
        self.assertEqual(self.run_probe(probe_input())["status"], "ok")
        self.install()
        self.assertEqual(self.run_probe(probe_input("dev-ghost"))["status"], "ok")
        for mode in ERRORS:
            with self.subTest(mode=mode):
                self.install(fail=mode)
                self.assertEqual(self.run_probe(probe_input())["status"], "error")

    def test_examples_of_the_reference(self):
        """SPEC-0106:CT-01 — references/probes/argocd.md traz blocos ```json probe@2 <tipo> <valid|invalid>: o
        describe válido (igual ao do contrato), a saída válida da seção 6 e a inválida com um item aninhado (source);
        os válidos passam nos validadores do núcleo e os inválidos são recusados com motivo; nenhum bloco válido traz
        repoURL, source, helm nem host de registro."""
        # SPEC-0106:CT-01
        self.assertTrue(REFERENCE.is_file(), f"{REFERENCE.relative_to(SKILL)} não existe ({SPEC})")
        text = REFERENCE.read_text(encoding="utf-8")
        blocks = [(m.group(1), m.group(2), json.loads(m.group(3))) for m in DOC_BLOCK_RE.finditer(text)]
        self.assertIn(DESCRIBE, [b[2] for b in blocks if b[:2] == ("describe", "valid")], "sem o describe valid")
        valid_out = [b[2] for b in blocks if b[:2] == ("output", "valid")]
        self.assertTrue([o for o in valid_out if o.get("status") == "ok"], "sem saída ok de application")
        nested = [b[2] for b in blocks if b[:2] == ("output", "invalid")
                  and any(isinstance(v, dict) for i in b[2].get("items") or [] if isinstance(i, dict)
                          for v in i.values())]
        self.assertTrue(nested, "sem saída inválida com item aninhado (source)")
        for kind, verdict, data in blocks:
            with self.subTest(kind=kind, verdict=verdict, data=json.dumps(data)[:80]):
                problems = f(VALIDATORS[kind])(data)
                if verdict == "valid":
                    self.assertEqual(problems, [])
                else:
                    self.assertTrue(problems and all(isinstance(p, str) and p for p in problems), problems)
        valid = "\n".join(json.dumps(b[2]) for b in blocks if b[1] == "valid")
        for value in ("repoURL", "\"source\"", "helm", "ghcr.io", "amazonaws.com"):
            self.assertNotIn(value, valid)


if __name__ == "__main__":
    unittest.main()
