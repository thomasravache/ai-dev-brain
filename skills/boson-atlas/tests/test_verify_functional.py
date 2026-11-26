"""Verificação `functional` do `verify compare --functional [--journey <id>]...` (SPEC-0103: CH-01, UT-07, IT-02 e a
parte verify do CT-01; ADR-0026 regra 4, ADR-0024; sobre o verify@2 da SPEC-0102).

Contrato (seção 6 da SPEC-0103) que estes testes fixam:

    sem --functional: nenhuma verificação functional (como hoje); --journey sem --functional -> exit 2
    com --functional, por serviço e ambiente, depois das verificações do verify@2:
        tier diferente de test (inclusive sem tier) -> not_verified "validação funcional só em tier: test"; nenhum
            processo roda e nada é registrado para a functional
        alguma delivery que não deu ok -> not_verified "entrega não confirmada: a jornada rodaria contra outra
            versão" (não roda)
        senão roda probe functional run pelo run_probe (com os --journey):
            ok — todas passed (ao menos uma) · failed — alguma failed · not_verified — nenhuma failed e alguma skipped
            ("jornada pulada: <ids>"), probe recusada, com erro ou fora do contrato, com o motivo
    a verificação: {"deployment", "resource": null, "check": "functional", "status", "evidence": {"environment_tier":
        "test", "journeys": [{"journey", "result", "duration_seconds", "failed_steps"}]}, "reason"}
    veredito, exits e suggestion: os do verify@2; validate_verify_result aceita check functional com essa evidência.

Leituras desta suíte (listadas no relatório do test-writer):
    - CH-01 é a guarda por golden (fixtures/functional/spec-0103-ch01-golden.json, gravado com o código anterior à
      SPEC-0103 por record_golden()): probe runtime status, verify snapshot, verify compare --json e em texto, e as
      linhas do probes.log (sem "at"), com os dublês de hoje, ficam iguais.
    - O veredito "passou" pede uma foto de antes (sem ela, logs fica not_verified): cada caso tira a foto com o
      mesmo estado saudável e depois compara.
    - Com tier fora de test e com a entrega não confirmada, o adaptador functional não recebe nenhuma chamada (nem o
      --describe) e o probes.log não tem nenhuma linha da capacidade functional.
    - A evidência de not_verified sem jornadas (recusa, erro, fora de teste) pode ter journeys [] — só as chaves são
      conferidas nos casos com jornadas.
    - CT-01 (parte verify): o bloco ```json de references/verify.md com "contract": "verify@2" e uma verificação
      functional passa no validate_verify_result; o mesmo bloco com "result": "ok" numa jornada é recusado.

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); fotos só em pastas temporárias;
sem rede; nenhum kubectl de verdade (o adaptador falso fixtures/fake-probes/scripted.py nos unitários e o kubectl falso
da SPEC-0089 no IT-02); suítes falsas de fixtures/functional/fake_suite.py; nomes acme, api, checkout, login, dev, prod.
"""
import copy
import json
import os
import re
import sys
import unittest

from helpers import SKILL, fn, output
from test_probe import adapter_yaml
from test_probe_functional import (
    CONTEXTS,
    FAKE_SUITE,
    FIXTURES,
    JOURNEYS,
    SPEC,
    SUITE,
    FunctionalCase,
    item,
    items,
)
from test_probe_kubernetes import install_kubectl
from test_verify import (
    KUBE_NEW,
    KUBE_OLD,
    NEW_IMAGE,
    OLD_IMAGE,
    SCRIPTED,
    deployment_state,
    kube_cluster,
)

GOLDEN = FIXTURES / "spec-0103-ch01-golden.json"
VERIFY_DOC = SKILL / "references" / "verify.md"
VERDICT_EXIT = {"passou": 0, "degradou": 1, "inconclusivo": 5}
NOT_TEST = "validação funcional só em tier: test"
NOT_DELIVERED = "entrega não confirmada"
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")


def functional_checks(data):
    return [c for c in data["checks"] if c["check"] == "functional"]


class VerifyFunctionalCase(FunctionalCase):
    """O atlas da SPEC-0103 com o adaptador falso de runtime (scripted.py, probe@1) antes do adaptador falso de
    functional (probe2.py): o runtime nunca pede o --describe do functional."""

    def setUp(self):
        super().setUp()
        self.runtime_record = self.work / "runtime-calls.jsonl"
        self.runtime_scenario = self.work / "runtime-scenario.json"
        self.photo = self.work / "foto.json"
        self.set_runtime()
        self.configure_verify()

    def runtime_adapter(self):
        command = [sys.executable, str(SCRIPTED), "--record", str(self.runtime_record), "--scenario",
                   str(self.runtime_scenario)]
        return adapter_yaml("fake", command, verbs=("status", "events", "logs"), timeout=60)

    def configure_verify(self, urls=True):
        self.configure([self.runtime_adapter(), self.adapter2()], urls=urls)

    def set_runtime(self, image=NEW_IMAGE):
        state = deployment_state("dev-api", image=image)
        self.runtime_scenario.write_text(json.dumps({"dev-api": state, "*": state}), encoding="utf-8")

    def verify(self, *args):
        result = self.run_atlas("verify", *args)
        self.assertNotIn("invalid choice", output(result))
        return result

    def take(self, env="dev", *extra):
        out = self.verify("snapshot", "--service", "api", "--env", env, "--out", self.photo, *extra)
        self.assertExit(out, 0)
        return out

    def compare(self, *extra, env="dev", baseline=True, as_json=True):
        args = ["compare", "--service", "api", "--env", env, "--expect-image", NEW_IMAGE]
        if baseline:
            args += ["--baseline", self.photo]
        return self.verify(*args, *extra, *(["--json"] if as_json else []))

    def result(self, run, verdict=None):
        try:
            data = json.loads(run.stdout)
        except ValueError:
            self.fail(f"saída --json não é JSON (exit {run.returncode}): {output(run)}")
        self.assertEqual(fn("validate_verify_result", "SPEC-0102")(data), [], data)
        self.assertEqual(run.returncode, VERDICT_EXIT[data["verdict"]], output(run))
        if verdict is not None:
            self.assertEqual(data["verdict"], verdict, json.dumps(data, ensure_ascii=False, indent=1))
        return data

    def functional(self, *extra, verdict=None, env="dev", baseline=True):
        """compare --functional --json: a verificação functional (exatamente uma), com as chaves do verify@2."""
        run = self.compare("--functional", *extra, env=env, baseline=baseline)
        self.assertNotIn("unrecognized arguments", output(run), f"o verify ainda não aceita --functional ({SPEC})")
        data = self.result(run, verdict)
        found = functional_checks(data)
        self.assertEqual(len(found), 1, data["checks"])
        check = found[0]
        self.assertEqual(set(check), {"deployment", "resource", "check", "status", "evidence", "reason"}, check)
        self.assertEqual(check["deployment"], "dev-api" if env == "dev" else f"{env}-api")
        self.assertIsNone(check["resource"])
        self.assertIsInstance(check["evidence"], dict)
        return check, data

    def functional_logged(self):
        return [line for line in self.log() if line.get("capability") == "functional"]


# --------------------------------------------------------------------------- CH-01


def _normalize(text, root):
    return TS_RE.sub("<TS>", text.replace(str(root), "<ROOT>"))


def ch01_outputs(case):
    """As saídas de hoje (os dublês atuais, sem --functional), normalizadas."""
    outputs = {}
    probe = case.probe("runtime", "status", "--json")
    outputs["probe runtime status --json"] = [probe.returncode, _normalize(probe.stdout, case.box.root)]
    snap = case.take()
    outputs["verify snapshot"] = [snap.returncode, _normalize(snap.stdout, case.box.root)]
    photo = json.loads(case.photo.read_text(encoding="utf-8"))
    photo["taken_at"] = "<TS>"
    outputs["foto"] = photo
    for name, as_json in (("verify compare --json", True), ("verify compare", False)):
        run = case.compare(as_json=as_json)
        outputs[name] = [run.returncode, _normalize(run.stdout, case.box.root)]
    outputs["probes.log"] = [{k: v for k, v in line.items() if k != "at"} for line in case.log()]
    return outputs


class CharacterizationTest(VerifyFunctionalCase):
    def test_todays_probe_and_verify_keep_their_outputs(self):
        """SPEC-0103:CH-01 — o probe das capacidades de hoje e o verify compare sem --functional, com os dublês
        atuais: a saída, os exits e o probes.log ficam iguais ao golden gravado antes da mudança; nenhuma verificação
        functional e nenhuma chamada ao adaptador functional."""
        # SPEC-0103:CH-01
        self.assertTrue(GOLDEN.exists(), f"{GOLDEN} não existe — rode record_golden() com o código anterior")
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(ch01_outputs(self), golden)
        self.assertEqual(self.calls("run"), [])


def record_golden():  # pragma: no cover — rodado uma vez, com o código anterior à SPEC-0103
    """python3 -c 'import test_verify_functional as t; t.record_golden()' (cwd: tests/)."""
    CharacterizationTest.setUpClass()
    try:
        case = CharacterizationTest("test_todays_probe_and_verify_keep_their_outputs")
        case.setUp()
        GOLDEN.write_text(json.dumps(ch01_outputs(case), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")
    finally:
        CharacterizationTest.tearDownClass()


# --------------------------------------------------------------------------- UT-07


class VerifyFunctionalTest(VerifyFunctionalCase):
    def test_without_functional_there_is_no_functional_check(self):
        """SPEC-0103:UT-07 — sem --functional não há verificação functional e o adaptador functional não roda;
        --journey sem --functional sai com 2, sem ser o "unrecognized arguments" do argparse."""
        # SPEC-0103:UT-07
        self.take()
        data = self.result(self.compare(), "passou")
        self.assertEqual(functional_checks(data), [])
        self.assertEqual(self.calls("run"), [])
        run = self.compare("--journey", "login")
        self.assertExit(run, 2)
        self.assertNotIn("unrecognized arguments", output(run), f"o verify ainda não aceita --journey ({SPEC})")
        self.assertIn("--functional", output(run))

    def test_all_journeys_passed_is_ok_and_passes(self):
        """SPEC-0103:UT-07 — em dev (tier: test), todas passed: functional ok, evidência com environment_tier test e
        as jornadas, veredito passou, exit 0; o probe recebeu as duas jornadas curadas."""
        # SPEC-0103:UT-07
        self.take()
        check, _ = self.functional(verdict="passou")
        self.assertEqual(check["status"], "ok", check)
        self.assertEqual(check["evidence"]["environment_tier"], "test")
        self.assertEqual(check["evidence"]["journeys"], items(*JOURNEYS))
        self.assertEqual(self.received()["input"]["target"]["journeys"], JOURNEYS)

    def test_journey_option_goes_to_the_probe(self):
        """SPEC-0103:UT-07 — --functional --journey login: só login vai em target.journeys e a evidência tem só ela."""
        # SPEC-0103:UT-07
        self.take()
        self.write_scenario({"run": {"items": items("login")}})
        check, _ = self.functional("--journey", "login", verdict="passou")
        self.assertEqual(self.received()["input"]["target"]["journeys"], ["login"])
        self.assertEqual([j["journey"] for j in check["evidence"]["journeys"]], ["login"])

    def test_a_failed_journey_fails_and_degrades(self):
        """SPEC-0103:UT-07 — uma jornada failed: functional failed, a jornada e os passos na evidência, veredito
        degradou, exit 1."""
        # SPEC-0103:UT-07
        self.take()
        failed = item("login", "failed", 4.2, ["campo senha não apareceu"])
        self.write_scenario({"run": {"items": [item("checkout"), failed]}})
        check, data = self.functional(verdict="degradou")
        self.assertEqual(check["status"], "failed", check)
        self.assertIn(failed, check["evidence"]["journeys"])
        self.assertTrue(data["suggestion"])

    def test_a_skipped_journey_is_not_verified(self):
        """SPEC-0103:UT-07 — uma skipped e nenhuma failed: not_verified "jornada pulada: login", inconclusivo."""
        # SPEC-0103:UT-07
        self.take()
        self.write_scenario({"run": {"items": [item("checkout"),
                                               item("login", "skipped", 0, ["a suíte pulou a jornada"])]}})
        check, _ = self.functional(verdict="inconclusivo")
        self.assertEqual(check["status"], "not_verified", check)
        self.assertIn("jornada pulada: login", check["reason"])

    def test_a_probe_error_or_refusal_is_not_verified_with_the_reason(self):
        """SPEC-0103:UT-07 — probe com erro (arquivo de jornadas inválido) ou recusada (sem URL base): not_verified
        com o motivo, nunca ok."""
        # SPEC-0103:UT-07
        self.take()
        self.write_scenario({"run": {"error": "arquivo de jornadas inválido: journeys.checkout.cwd — precisa ser um "
                                              "caminho absoluto"}})
        check, _ = self.functional(verdict="inconclusivo")
        self.assertEqual(check["status"], "not_verified", check)
        self.assertIn("arquivo de jornadas inválido", check["reason"])
        self.configure_verify(urls={"prod": "https://prod.acme.example"})
        check, _ = self.functional(verdict="inconclusivo")
        self.assertEqual(check["status"], "not_verified", check)
        self.assertIn("sem acesso local: urls", check["reason"])

    def test_outside_tier_test_nothing_runs(self):
        """SPEC-0103:UT-07 — prod com --confirm-production e stage (sem tier) com --confirm-production: functional
        not_verified "validação funcional só em tier: test", e o adaptador functional não recebe nenhuma chamada nem
        entra no probes.log."""
        # SPEC-0103:UT-07
        for env in ("prod", "stage"):
            with self.subTest(env=env):
                self.reset_calls()
                check, _ = self.functional("--confirm-production", env=env, baseline=False)
                self.assertEqual(check["status"], "not_verified", check)
                self.assertIn(NOT_TEST, check["reason"])
                self.assertEqual(self.calls(), [], "o adaptador functional foi chamado fora de tier: test")
                self.assertEqual(self.functional_logged(), [])

    def test_delivery_not_ok_does_not_run_the_journeys(self):
        """SPEC-0103:UT-07 — delivery failed (os pods com a imagem antiga): functional not_verified "entrega não
        confirmada…", sem rodar o adaptador functional e sem linha dele no probes.log."""
        # SPEC-0103:UT-07
        self.take()
        self.set_runtime(image=OLD_IMAGE)
        check, data = self.functional(verdict="degradou")
        delivery = next(c for c in data["checks"] if c["check"] == "delivery")
        self.assertEqual(delivery["status"], "failed", delivery)
        self.assertEqual(check["status"], "not_verified", check)
        self.assertIn(NOT_DELIVERED, check["reason"])
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.functional_logged(), [])


# --------------------------------------------------------------------------- IT-02


class EndToEndTest(FunctionalCase):
    """verify snapshot e verify compare --functional como processo, com o adaptador kubernetes e o kubectl falso
    (saudável) e o adaptador suite com duas suítes falsas."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        clusters = cls.box.root / "clusters"
        cls.before = kube_cluster(clusters / "before", "6a1b", KUBE_OLD, 4, lines=["INFO request 1 ok"])
        cls.after = kube_cluster(clusters / "after", "7c2d", KUBE_NEW, 5, lines=["INFO request 2 ok"])

    def setUp(self):
        super().setUp()
        self.bin = self.work / "bin"
        self.kube_record = self.work / "kubectl-calls.jsonl"
        self.suite_record = self.work / "suite-calls.jsonl"
        self.journeys_path = self.work / "journeys.json"
        self.photo = self.work / "foto.json"
        kubernetes = '    kubernetes:\n      verbs: ["status", "events", "logs"]\n      timeout: 60\n'
        suite = adapter_yaml("suite", [sys.executable, str(SUITE), "--journeys-file", str(self.journeys_path)],
                             verbs=("run",), timeout=120)
        self.configure([kubernetes, suite])

    def write_journeys(self, login_exit=0):
        def command(code, *steps):
            argv = [sys.executable, str(FAKE_SUITE), "--record", str(self.suite_record), "--exit", str(code)]
            for step in steps:
                argv += ["--step", step]
            return argv

        steps = ("campo senha não apareceu",) if login_exit else ()
        self.journeys_path.write_text(json.dumps({"journeys": {
            "checkout": {"command": command(0)}, "login": {"command": command(login_exit, *steps)}}}),
            encoding="utf-8")

    def verify(self, *args):
        environ = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        return self.run_atlas("verify", *args, environ=environ)

    def phases(self):
        install_kubectl(self.bin, self.kube_record, fixtures=(self.before,))
        run = self.verify("snapshot", "--service", "api", "--env", "dev", "--out", self.photo)
        self.assertExit(run, 0)
        install_kubectl(self.bin, self.kube_record, fixtures=(self.after,))
        run = self.verify("compare", "--service", "api", "--env", "dev", "--baseline", self.photo,
                          "--expect-image", "acme/api:1.4.2", "--functional", "--json")
        self.assertNotIn("unrecognized arguments", output(run), f"o verify ainda não aceita --functional ({SPEC})")
        data = json.loads(run.stdout)
        self.assertEqual(fn("validate_verify_result", "SPEC-0102")(data), [], data)
        self.assertEqual(run.returncode, VERDICT_EXIT[data["verdict"]], output(run))
        for context in CONTEXTS.values():
            self.assertNotIn(context, output(run))
        found = functional_checks(data)
        self.assertEqual(len(found), 1, data["checks"])
        return found[0], data

    def test_compare_functional_passes_with_both_suites_passing(self):
        """SPEC-0103:IT-02 — kubectl falso saudável e as duas suítes passando: veredito passou, exit 0, e a
        verificação functional ok com as duas jornadas na evidência."""
        # SPEC-0103:IT-02
        self.write_journeys()
        check, data = self.phases()
        self.assertEqual(data["verdict"], "passou", json.dumps(data, ensure_ascii=False, indent=1))
        self.assertEqual(check["status"], "ok", check)
        self.assertEqual([(j["journey"], j["result"]) for j in check["evidence"]["journeys"]],
                         [("checkout", "passed"), ("login", "passed")])

    def test_compare_functional_degrades_with_the_login_suite_failing(self):
        """SPEC-0103:IT-02 — a suíte de login falhando: veredito degradou, exit 1, e a verificação functional failed
        com o passo na evidência."""
        # SPEC-0103:IT-02
        self.write_journeys(login_exit=1)
        check, data = self.phases()
        self.assertEqual(data["verdict"], "degradou", json.dumps(data, ensure_ascii=False, indent=1))
        self.assertEqual(check["status"], "failed", check)
        login = next(j for j in check["evidence"]["journeys"] if j["journey"] == "login")
        self.assertEqual((login["result"], login["failed_steps"]), ("failed", ["campo senha não apareceu"]))


# --------------------------------------------------------------------------- CT-01 (verify)


class VerifyDocTest(unittest.TestCase):
    def test_verify_md_functional_example_follows_verify_2(self):
        """SPEC-0103:CT-01 — o exemplo verify@2 com a verificação functional de references/verify.md passa no
        validate_verify_result; o mesmo exemplo com "result": "ok" numa jornada é recusado."""
        # SPEC-0103:CT-01
        text = VERIFY_DOC.read_text(encoding="utf-8")
        examples = []
        for block in re.findall(r"```json[^\n]*\n(.*?)```", text, re.DOTALL):
            try:
                data = json.loads(block)
            except ValueError:
                continue
            if (isinstance(data, dict) and data.get("contract") == "verify@2" and isinstance(data.get("checks"), list)
                    and any(isinstance(c, dict) and c.get("check") == "functional" for c in data["checks"])):
                examples.append(data)
        self.assertTrue(examples, "references/verify.md sem exemplo verify@2 com a verificação functional")
        validate = fn("validate_verify_result", "SPEC-0102")
        example = examples[0]
        self.assertEqual(validate(example), [], example)
        broken = copy.deepcopy(example)
        check = next(c for c in broken["checks"] if c["check"] == "functional")
        self.assertTrue(check["evidence"].get("journeys"), "o exemplo functional precisa trazer jornadas")
        check["evidence"]["journeys"][0]["result"] = "ok"
        self.assertTrue(validate(broken), "result ok numa jornada foi aceito")


if __name__ == "__main__":
    unittest.main()
