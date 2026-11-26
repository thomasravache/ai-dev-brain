"""Validação funcional no núcleo do probe: só em `tier: test`, só com jornadas curadas, `--journey` e a validação própria
da saída de `functional` (SPEC-0103: UT-01 a UT-04 e UT-08; ADR-0026 regra 4, ADR-0025, ADR-0023, ADR-0012).

Contrato (seção 6 da SPEC-0103) que estes testes fixam:

    atlas (arquivo de fatos do coletor generic): {"kind": "service", "id": "api", "attrs": {"journeys": [...]}}
    atlas.py probe functional run --service <id> --env <ambiente> [--journey <id>]... [--confirm-production] [--json]
        2   --journey fora da regra de nome simples -> "--journey inválido"
        3a  capacidade functional e tier diferente de test (inclusive sem tier) -> 4 "validação funcional só roda em
            ambiente tier: test (<ambiente> não é)", com ou sem --confirm-production; nada roda, nem o --describe;
            probes.log: refused, reason not_test_tier
        3b  journeys do serviço vazias ou ausentes -> 4 "sem jornadas curadas para <serviço> (attrs.journeys)",
            probes.log: refused, reason no_journeys; --journey fora das curadas -> 2 "jornada <id> não curada para
            <serviço>"
        8   target.journeys = as curadas, ou só as de --journey, na ordem curada; --journey numa capacidade sem
            journeys em inputs -> 2 "--journey não é aceito por <capacidade>"
        11  sem access.urls.<ambiente> -> 4 "sem acesso local: urls" (SPEC-0096), reason no_access, access urls
        13  saída de functional: um item por id de target.journeys, na mesma ordem, chaves fechadas {journey, result
            (passed | failed | skipped), duration_seconds (>= 0), failed_steps (até 5 textos de até 200)}; fora disso
            -> exit 1 "saída fora do contrato", sem itens. Uma jornada failed não muda o exit (0).

Leituras desta suíte (listadas no relatório do test-writer):
    - O atlas é montado de verdade (init, arquivo de fatos do generic, scan e build) uma vez por classe, com dev em
      tier: test, prod em tier: production e stage sem tier; access.urls existe para os três ambientes, para que a
      recusa de prod e stage seja a de tier e não a de acesso.
    - "Sem jornadas" usa serviços próprios: worker (sem o atributo) e batch (lista vazia), cada um com um deployment
      em dev; a mensagem leva o nome do serviço.
    - --journey "-x" vai como --journey=-x (senão o argparse o lê como opção).
    - A capacidade sem journeys em inputs é `smoke` (run, alvo deployment, acesso urls), declarada pelo mesmo
      adaptador falso.
    - A validação própria de functional fica no núcleo numa função pública validate_functional_output(data, journeys)
      -> list (problemas; [] = válida), usada também pelo CT-01 (test_probe_suite.py).
    - UT-03 e a parte de máscara do UT-04 já valem desde a SPEC-0096 e passam antes da mudança; o UT-08 dos coletores
      também (o generic copia attrs como estão).

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); sem rede, sem kubectl, sem
ferramenta de teste de verdade (adaptador falso fixtures/fake-probes/probe2.py); nomes acme, api, checkout, login,
refund, dev, prod; URL https://dev.acme.example. A pasta do atlas tem o mesmo conteúdo antes e depois de cada comando.
"""
import importlib.util
import json
import re
import shutil
import sys
import unittest

from helpers import SKILL, TESTS, Sandbox, fn, output, snapshot
from test_access_map import collectors_yaml, environments_yaml
from test_probe import adapter_yaml, probes_yaml

SPEC = "SPEC-0103"
FAKES = TESTS / "fixtures" / "fake-probes"
FIXTURES = TESTS / "fixtures" / "functional"
FACTS = FIXTURES / "facts.json"
FAKE_SUITE = FIXTURES / "fake_suite.py"
SUITE = SKILL / "assets" / "probes" / "suite.py"
COLLECTORS = SKILL / "assets" / "collectors"

BASE_URL = "https://dev.acme.example"
BASE_URLS = {"dev": BASE_URL, "prod": "https://prod.acme.example", "stage": "https://stage.acme.example"}
CONTEXTS = {"cluster-dev": "ctx-local-dev-0103", "cluster-prod": "ctx-local-prod-0103",
            "cluster-stage": "ctx-local-stage-0103"}
JOURNEYS = ["checkout", "login"]
USER_NAME, PASSWORD_NAME = "CHECKOUT_TEST_USER", "CHECKOUT_TEST_PASSWORD"
USER_VALUE, PASSWORD_VALUE = "usuario-falso-0103", "senha-falsa-0103-xyz"
TIER_REFUSAL = "validação funcional só roda em ambiente tier: test ({env} não é)"
ITEM_KEYS = {"journey", "result", "duration_seconds", "failed_steps"}
CAPS = {
    "functional": {"verbs": ["run"], "targets": ["deployment"], "access": ["urls"], "inputs": ["journeys"]},
    "smoke": {"verbs": ["run"], "targets": ["deployment"], "access": ["urls"]},
}


def f(name):
    return fn(name, SPEC)


def item(journey, result="passed", duration=0.5, steps=()):
    return {"journey": journey, "result": result, "duration_seconds": duration, "failed_steps": list(steps)}


def items(*journeys, result="passed"):
    return [item(j, result) for j in journeys]


# --------------------------------------------------------------------------- atlas e configuração


def build_functional_atlas(box: Sandbox):
    """init --mode local; as jornadas entram pelo arquivo de fatos do generic (fixtures/functional/facts.json, dentro
    do atlas, como o arquivo escrito por uma pessoa); scan e build de verdade. dev: tier test, prod: tier production,
    stage sem tier."""
    out = box.init(mode="local")
    assert out.returncode == 0, output(out)
    facts = box.atlas / "facts"
    facts.mkdir(exist_ok=True)
    shutil.copy(FACTS, facts / "delivery.json")
    command = ["python3", "{skill}/assets/collectors/generic.py", "--facts", "{atlas}/facts/delivery.json",
               "--category", "delivery"]
    (box.atlas / "atlas-config.yml").write_text(
        collectors_yaml([("facts", "delivery", command)])
        + environments_yaml([("dev", "{tier: test}"), ("prod", "{tier: production}")]), encoding="utf-8")
    box.write_local(f"atlas: {json.dumps(str(box.atlas))}\ncredentials: {{}}\n")
    for step in ("scan", "build"):
        out = box.run(step)
        assert out.returncode == 0, f"{step} falhou: {output(out)}"
    graph = json.loads((box.atlas / "graph.json").read_text(encoding="utf-8"))
    api = next(n for n in graph["nodes"] if n["key"] == "service:api")
    assert api["attrs"].get("journeys") == JOURNEYS, api


def access_text(clusters=True, urls=True):
    lines = []
    if clusters:
        lines.append("  clusters:")
        lines += [f"    {json.dumps(c)}: {{context: {json.dumps(ctx)}}}" for c, ctx in CONTEXTS.items()]
    if urls:
        chosen = BASE_URLS if urls is True else urls
        lines.append("  urls:")
        lines += [f"    {json.dumps(env)}: {{base_url: {json.dumps(url)}}}" for env, url in chosen.items()]
    return ("access:\n" + "\n".join(lines) + "\n") if lines else ""


class FunctionalCase(unittest.TestCase):
    """Um atlas por classe (o probe nunca escreve no atlas); cada teste tem a própria configuração local, o próprio
    cenário e o próprio registro de processos do adaptador falso."""

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox()
        try:
            build_functional_atlas(cls.box)
        except BaseException:
            cls.box.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.box.cleanup()

    def setUp(self):
        name = self.id().rsplit(".", 1)[-1]
        self.work = self.box.root / "work-tests" / name
        self.work.mkdir(parents=True, exist_ok=True)
        self.cfg = self.work / "cfg"
        self.record = self.work / "calls.jsonl"
        self.scenario = self.work / "scenario.json"
        self.write_scenario({"run": {"items": items(*JOURNEYS)}})

    # -- configuração

    def adapter2(self, caps=None, aid="fake2", verbs=("run",), credentials=()):
        describe = self.work / f"describe-{aid}.json"
        describe.write_text(json.dumps({"contract": "probe@2", "adapter": aid,
                                        "capabilities": CAPS if caps is None else caps}), encoding="utf-8")
        command = [sys.executable, str(FAKES / "probe2.py"), "--record", str(self.record), "--describe-file",
                   str(describe), "--scenario", str(self.scenario), "--adapter", aid]
        return adapter_yaml(aid, command, verbs=verbs, timeout=20, credentials=credentials)

    def configure(self, adapters=None, clusters=True, urls=True, credentials="{}"):
        text = f"atlas: {json.dumps(str(self.box.atlas))}\ncredentials: {credentials}\n"
        text += access_text(clusters, urls)
        text += probes_yaml(list(adapters if adapters is not None else [self.adapter2()]))
        self.box.write_local(text, config_home=self.cfg)

    def write_scenario(self, scenario):
        self.scenario.write_text(json.dumps(scenario), encoding="utf-8")

    # -- execução

    def run_atlas(self, *args, environ=None):
        """atlas.py com a configuração deste teste; sem traceback e com a pasta do atlas intocada (UT-08)."""
        before = snapshot(self.box.atlas)
        result = self.box.run(*args, config_home=self.cfg, env=environ)
        self.assertNotIn("Traceback", output(result), output(result))
        self.assertEqual(snapshot(self.box.atlas), before, "o comando mudou a pasta do atlas (SPEC-0103:UT-08)")
        return result

    def probe(self, capability, verb, *extra, service="api", env="dev", environ=None):
        return self.run_atlas("probe", capability, verb, "--service", service, "--env", env, *extra, environ=environ)

    def calls(self, mode=None):
        if not self.record.exists():
            return []
        rows = [json.loads(line) for line in self.record.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [r for r in rows if mode is None or r["mode"] == mode]

    def reset_calls(self):
        if self.record.exists():
            self.record.unlink()

    def received(self):
        runs = self.calls("run")
        self.assertEqual(len(runs), 1, runs)
        return runs[0]

    def log(self):
        path = self.cfg / "probes.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def log_text(self):
        path = self.cfg / "probes.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def assertExit(self, result, code):
        self.assertEqual(result.returncode, code, output(result))

    def assertOwnError(self, result, code, text):
        """exit `code` do próprio subcomando (não do argparse), com `text` na mensagem."""
        self.assertExit(result, code)
        self.assertNotIn("unrecognized arguments", output(result), f"o probe ainda não aceita a opção ({SPEC})")
        self.assertIn(text, output(result))

    def assertLastLog(self, status, reason, **extra):
        lines = self.log()
        self.assertTrue(lines, "nenhuma linha no probes.log")
        last = lines[-1]
        self.assertEqual((last.get("status"), last.get("reason")), (status, reason), last)
        for key, value in extra.items():
            self.assertEqual(last.get(key), value, last)
        return last


# --------------------------------------------------------------------------- UT-01


class TierTest(FunctionalCase):
    def test_functional_outside_tier_test_is_refused_before_any_process(self):
        """SPEC-0103:UT-01 — prod (tier: production) e stage (sem tier), com e sem --confirm-production: exit 4 com a
        mensagem de tier: test, o adaptador falso não recebe nenhuma chamada (nem --describe) e o probes.log tem
        refused com reason not_test_tier; em dev (tier: test) o adaptador roda."""
        # SPEC-0103:UT-01
        self.configure()
        for env in ("prod", "stage"):
            for confirm in ((), ("--confirm-production",)):
                with self.subTest(env=env, confirm=bool(confirm)):
                    self.reset_calls()
                    result = self.probe("functional", "run", *confirm, env=env)
                    self.assertOwnError(result, 4, TIER_REFUSAL.format(env=env))
                    self.assertEqual(self.calls(), [], "um processo do adaptador rodou (nem o --describe pode)")
                    self.assertLastLog("refused", "not_test_tier", environment=env,
                                       confirmed_production=bool(confirm))
        self.reset_calls()
        result = self.probe("functional", "run", "--json")
        self.assertExit(result, 0)
        self.assertEqual(len(self.calls("run")), 1, self.calls())
        self.assertEqual(self.log()[-1]["status"], "ok")


# --------------------------------------------------------------------------- UT-02


class CuratedJourneysTest(FunctionalCase):
    def test_without_curated_journeys_is_refused(self):
        """SPEC-0103:UT-02 — serviço sem o atributo journeys (worker) ou com lista vazia (batch): exit 4 "sem jornadas
        curadas para <serviço> (attrs.journeys)", nenhuma execução do adaptador, probes.log com reason no_journeys."""
        # SPEC-0103:UT-02
        self.configure()
        for service in ("worker", "batch"):
            with self.subTest(service=service):
                self.reset_calls()
                result = self.probe("functional", "run", service=service)
                self.assertOwnError(result, 4, f"sem jornadas curadas para {service} (attrs.journeys)")
                self.assertEqual(self.calls("run"), [])
                self.assertLastLog("refused", "no_journeys", service=service)

    def test_journey_option_restricts_to_curated_ids(self):
        """SPEC-0103:UT-02 — com ["checkout", "login"] curadas: --journey login manda só login em target.journeys;
        --journey refund sai com 2 "jornada refund não curada para api"; --journey=-x sai com 2 "--journey
        inválido"; nos dois casos de erro o adaptador não roda."""
        # SPEC-0103:UT-02
        self.configure()
        self.write_scenario({"run": {"items": items("login")}})
        result = self.probe("functional", "run", "--journey", "login", "--json")
        self.assertExit(result, 0)
        self.assertEqual(self.received()["input"]["target"]["journeys"], ["login"])
        for args, text in ((("--journey", "refund"), "jornada refund não curada para api"),
                           (("--journey=-x",), "--journey inválido")):
            with self.subTest(args=args):
                self.reset_calls()
                result = self.probe("functional", "run", *args)
                self.assertOwnError(result, 2, text)
                self.assertEqual(self.calls("run"), [])

    def test_journey_option_keeps_the_curated_order(self):
        """SPEC-0103:UT-02 — --journey login --journey checkout: target.journeys na ordem curada (checkout, login)."""
        # SPEC-0103:UT-02
        self.configure()
        result = self.probe("functional", "run", "--journey", "login", "--journey", "checkout", "--json")
        self.assertExit(result, 0)
        self.assertEqual(self.received()["input"]["target"]["journeys"], JOURNEYS)

    def test_journey_option_on_a_capability_without_journeys_input_exits_2(self):
        """SPEC-0103:UT-02 — --journey checkout em `smoke` (sem journeys em inputs): exit 2 "--journey não é aceito
        por smoke", sem rodar a consulta."""
        # SPEC-0103:UT-02
        self.configure()
        result = self.probe("smoke", "run", "--journey", "checkout")
        self.assertOwnError(result, 2, "--journey não é aceito por smoke")
        self.assertEqual(self.calls("run"), [])


# --------------------------------------------------------------------------- UT-03


class AdapterInputTest(FunctionalCase):
    def test_input_has_journeys_and_base_url_and_nothing_else(self):
        """SPEC-0103:UT-03 — jornadas curadas e access.urls.dev: a entrada passa no validate_probe_input, target é
        exatamente {service, environment, deployment, urls: {base_url}, journeys: ["checkout", "login"]}, sem campo de
        cluster e sem nenhum comando."""
        # SPEC-0103:UT-03
        self.configure()
        result = self.probe("functional", "run", "--json")
        self.assertExit(result, 0)
        sent = self.received()["input"]
        self.assertEqual(fn("validate_probe_input", "SPEC-0096")(sent), [])
        self.assertEqual(sent["contract"], "probe@2")
        self.assertEqual(sent["target"], {"service": "api", "environment": "dev", "deployment": "dev-api",
                                          "urls": {"base_url": BASE_URL}, "journeys": JOURNEYS})
        self.assertNotIn("command", json.dumps(sent))

    def test_without_base_url_is_refused_with_no_access_urls(self):
        """SPEC-0103:UT-03 — sem access.urls.dev: exit 4 "sem acesso local: urls", a consulta não roda e o probes.log
        tem reason no_access e access urls."""
        # SPEC-0103:UT-03
        self.configure(urls={"prod": BASE_URLS["prod"]})
        result = self.probe("functional", "run")
        self.assertOwnError(result, 4, "sem acesso local: urls")
        self.assertEqual(self.calls("run"), [])
        self.assertLastLog("refused", "no_access", access="urls")


# --------------------------------------------------------------------------- UT-04


OUT_OF_CONTRACT = {
    "id que não estava na entrada": items("checkout", "login", "refund"),
    "id faltando": items("checkout"),
    "id repetido": items("checkout", "checkout"),
    "chave stdout": [dict(item("checkout"), stdout="linha da suíte"), item("login")],
    "result ok": [item("checkout", result="ok"), item("login")],
    "seis failed_steps": [item("checkout", "failed", steps=[f"passo {n}" for n in range(6)]), item("login")],
    "passo com 201 caracteres": [item("checkout", "failed", steps=["x" * 201]), item("login")],
}


class FunctionalOutputTest(FunctionalCase):
    def test_output_out_of_the_functional_contract_exits_1_without_items(self):
        """SPEC-0103:UT-04 — itens fora da validação própria de functional (id a mais, faltando, repetido, chave
        stdout, result "ok", seis failed_steps, passo de 201 caracteres): exit 1 "saída fora do contrato", sem
        itens na saída."""
        # SPEC-0103:UT-04
        self.configure()
        for name, answer in OUT_OF_CONTRACT.items():
            with self.subTest(name):
                self.write_scenario({"run": {"items": answer}})
                result = self.probe("functional", "run", "--json")
                self.assertExit(result, 1)
                self.assertIn("saída fora do contrato", output(result))
                self.assertNotIn('"journey"', result.stdout)
                self.assertNotIn("linha da suíte", output(result))

    def test_a_failed_journey_does_not_change_the_exit(self):
        """SPEC-0103:UT-04 (contrato) — uma jornada failed numa saída válida: exit 0, o probe informa e o verify
        julga."""
        # SPEC-0103:UT-04
        self.configure()
        self.write_scenario({"run": {"items": [item("checkout"), item("login", "failed", 1.2, ["botão sumiu"])]}})
        result = self.probe("functional", "run", "--json")
        self.assertExit(result, 0)
        data = json.loads(result.stdout)
        self.assertEqual([i["result"] for i in data["items"]], ["passed", "failed"])
        self.assertEqual(data["items"][1]["failed_steps"], ["botão sumiu"])

    def test_base_url_and_credential_are_masked_and_never_logged(self):
        """SPEC-0103:UT-04 — saída válida com a URL base e o valor de CHECKOUT_TEST_PASSWORD em failed_steps e na
        message: a saída de texto e o --json trazem [REDACTED] e nenhum dos dois valores; o probes.log não tem a URL,
        a credencial nem os passos."""
        # SPEC-0103:UT-04
        self.configure([self.adapter2(credentials=(PASSWORD_NAME,))])
        steps = [f"abriu {BASE_URL}/carrinho", f"credencial usada {PASSWORD_VALUE}"]
        self.write_scenario({"run": {"items": [item("checkout", "failed", 2.0, steps), item("login")],
                                     "message": f"rodou contra {BASE_URL} com {PASSWORD_VALUE}"}})
        environ = {PASSWORD_NAME: PASSWORD_VALUE}
        for extra in ((), ("--json",)):
            with self.subTest(json=bool(extra)):
                result = self.probe("functional", "run", *extra, environ=environ)
                self.assertExit(result, 0)
                text = output(result)
                self.assertIn("[REDACTED]", text)
                self.assertNotIn(BASE_URL, text)
                self.assertNotIn(PASSWORD_VALUE, text)
        log = self.log_text()
        for value in (BASE_URL, PASSWORD_VALUE, "carrinho", "credencial usada"):
            self.assertNotIn(value, log)

    def test_functional_validator_is_public(self):
        """SPEC-0103:UT-04 — validate_functional_output(data, journeys) do núcleo: a saída válida dá [] e cada caso
        fora do contrato dá ao menos um problema, sem citar valor."""
        # SPEC-0103:UT-04
        validate = f("validate_functional_output")

        def out(answer):
            return {"contract": "probe@2", "adapter": "suite", "capability": "functional", "verb": "run",
                    "status": "ok", "items": answer, "truncated": False}

        self.assertEqual(validate(out(items(*JOURNEYS)), JOURNEYS), [])
        self.assertEqual(validate(out([item("checkout", "skipped", 0, ["a suíte pulou a jornada"]),
                                       item("login", "failed", 3, ["a"] * 5)]), JOURNEYS), [])
        for name, answer in OUT_OF_CONTRACT.items():
            with self.subTest(name):
                problems = validate(out(answer), JOURNEYS)
                self.assertTrue(problems, name)
                self.assertNotIn("linha da suíte", " ".join(problems))
        self.assertTrue(validate(out([item("checkout", duration=-1), item("login")]), JOURNEYS))


# --------------------------------------------------------------------------- UT-08 (atlas como dado)


class AtlasAsDataTest(unittest.TestCase):
    def test_only_generic_brings_journeys(self):
        """SPEC-0103:UT-08 — os coletores que vêm com a skill (github, argocd, aws) nunca emitem journeys (o atributo
        não aparece no código deles); o generic copia journeys do arquivo de fatos como está."""
        # SPEC-0103:UT-08
        for name in ("github.py", "argocd.py", "aws.py"):
            with self.subTest(collector=name):
                source = (COLLECTORS / name).read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"\bjourneys\b", source), f"{name} emite journeys")
        spec = importlib.util.spec_from_file_location("atlas_generic_0103", COLLECTORS / "generic.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        facts = json.loads(FACTS.read_text(encoding="utf-8"))
        data = module.convert_facts(facts, "delivery")
        api = next(e for e in data["entities"] if e["kind"] == "service" and e["id"] == "api")
        self.assertEqual(api["attrs"]["journeys"], JOURNEYS)
        _, violations, dropped = fn("validate_collector_output", "SPEC-0033")(data)
        self.assertEqual((violations, dropped), ([], []))


if __name__ == "__main__":
    unittest.main()
