"""Núcleo do probe: contrato de adaptador probe@1, verbos permitidos, produção confirmada, limites, redaction, resumo
de logs e registro local (SPEC-0088: CH-01, UT-01 a UT-06, IT-01 e CT-01; ADR-0023, ADR-0010, ADR-0011).

Contrato (seção 6 da SPEC-0088) que estes testes fixam:

    config.yml (local; na forma com vários atlas, dentro da entrada do atlas):
        probes: {enabled, limits: {lines, since}, adapters: {<id>: {command, verbs, timeout, credentials}}}
        inválido -> exit 2 (config --json e probe) com "probes: <campo> inválido — <motivo>", sem o valor.
    atlas.py probe <capacidade> <verbo> --service <id> --env <ambiente> [--since] [--lines] [--summary]
        [--confirm-production] [--json]
        exit 0 ok · 1 erro do adaptador ou saída inválida · 2 argumento ou configuração inválida · 4 recusado.
        Recusas (exit 4): "probes desligadas"; "nenhum adaptador para <c>"; "verbo <v> não permitido";
        "ambiente <a> é de produção ou sem marcação: ... --confirm-production"; "sem acesso local ao cluster <c>".
    adaptador: <command> --describe -> {"contract": "probe@1", "adapter", "capabilities": {<c>: [verbos]}};
        entrada JSON no stdin; saída JSON validada (chaves fechadas, itens com escalares ou listas de escalares).
    registro: <pasta da configuração local>/probes.log, uma linha JSON por probe com exatamente as chaves
        at, atlas, service, environment, capability, verb, adapter, status, exit, confirmed_production.

Funções de scripts/atlas.py exigidas pelo CT-01 (nomes escolhidos por este test-writer; ver o relatório):
    validate_probe_describe(data) -> list[str]   # problemas; [] = válida
    validate_probe_input(data) -> list[str]
    validate_probe_output(data) -> list[str]

Leituras conservadoras desta suíte (ADR-0023; listadas no relatório do test-writer para o Architect):
    - CH-01 tem duas partes: a guarda (os comandos de hoje dão as mesmas saídas sem a chave probes ou com
      enabled: false — golden fixtures/probe/spec-0088-ch01-golden.json, gravado com o código anterior à SPEC-0088)
      passa agora; a recusa do `probe` desligado (exit 4) só passa com o subcomando. Na comparação, as linhas do
      doctor sobre probes/adaptadores e a chave "probes" do config --json são tiradas (o doctor ganha essas
      linhas pela spec).
    - O núcleo acrescenta "--describe" ao fim do command; command aceita caminho absoluto (exemplo da spec).
    - Os itens de log trazem o horário em "ts" (first_ts e last_ts vêm dele) e o texto em "line".
    - "Só as credenciais declaradas nele": um nome declarado nas credenciais de outro adaptador ou dos coletores
      não chega ao adaptador.
    - Probe recusada (exit 4 por verbo ou produção) também vai para o probes.log; o registro com probes desligadas
      não é verificado.
    - CT-01 lê de references/probes.md os blocos ```json probe@1 <describe|input|output> <valid|invalid>.

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); sem rede; nenhum kubectl ou
CLI de nuvem (os adaptadores são os scripts falsos de fixtures/fake-probes/); tokens montados em tempo de execução;
nomes genéricos (acme, api, cluster-dev).
"""
import copy
import json
import re
import sys
import time
import unittest
import urllib.parse

from helpers import (
    SKILL,
    TESTS,
    Sandbox,
    atlas,
    doctor_lines,
    fn,
    normalize,
    output,
    snapshot,
)
from test_access_map import (
    IMAGE_LINK_APPS,
    TIMESTAMP_RE,
    access_yaml,
    collectors_yaml,
    environments_yaml,
    resource,
    with_resources,
)

SPEC = "SPEC-0088"
FAKES = TESTS / "fixtures" / "fake-probes"
GOLDEN = TESTS / "fixtures" / "probe" / "spec-0088-ch01-golden.json"
PROBES_DOC = SKILL / "references" / "probes.md"
PATTERN = r"^(?:dev|qa|stg|sbx)-(?P<service>.+)$"
CONTEXTS = {"cluster-dev": "ctx-local-dev-0088", "cluster-qa": "ctx-local-qa-0088",
            "cluster-stg": "ctx-local-stg-0088"}  # cluster-sbx fica sem acesso local de propósito
ENVIRONMENTS = [("dev", "{tier: test}"), ("qa", "{tier: production}"), ("sbx", "{tier: test}")]  # stg sem tier
LOG_KEYS = {"at", "atlas", "service", "environment", "capability", "verb", "adapter", "status", "exit",
            "confirmed_production"}
OUTPUT_KEYS = {"contract", "adapter", "capability", "verb", "status", "items", "truncated", "message"}
OUTPUT_REQUIRED = OUTPUT_KEYS - {"message"}
SUMMARY_KEYS = {"signature", "level", "count", "first_ts", "last_ts", "sample"}
MARKER = "ITEM-MARCADOR-0088"
ERROR_MESSAGE = "MENSAGEM-ERRO-0088"
FAKE_VALUE = "valor-falso-SPEC0088-NAO"
FIELD_RE = r"probes: [\w.\[\]-]*{field}[\w.\[\]-]* inválido — \S"
DISABLED = "probes desligadas"
UUID = "5f2b8c1e-3d4a-4b6c-9e8f-0a1b2c3d4e5f"


def f(name):
    return fn(name, SPEC)


def fake_token():
    return "ghp_" + "Zx9" * 12  # montado em tempo de execução, como nos coletores falsos


def fake_email(n=""):
    return f"pessoa{n}.falsa" + "@" + "example.com"


# --------------------------------------------------------------------------- apoio


def probe_apps():
    """Applications de image-link (dev-api, qa-api) mais stg-api (ambiente sem tier) e sbx-api (tier test, cluster sem
    acesso local); dev-api com o workload Deployment/api."""
    base = json.loads(IMAGE_LINK_APPS.read_text(encoding="utf-8"))
    apps = list(base)
    for env in ("stg", "sbx"):
        app = copy.deepcopy(base[0])
        app["metadata"]["name"] = f"{env}-api"
        app["metadata"]["labels"]["env"] = env
        app["spec"]["destination"] = {"name": f"cluster-{env}", "namespace": f"api-{env}"}
        apps.append(app)
    return with_resources(apps, {"dev-api": [resource("Deployment", "api")],
                                 "qa-api": [resource("Deployment", "api", "api-qa")]})


def local_text(atlas_path, extra="", access=None, credentials="{}"):
    access = CONTEXTS if access is None else access
    text = f"atlas: {json.dumps(str(atlas_path))}\ncredentials: {credentials}\n"
    if access:
        text += access_yaml(list(access.items()))
    return text + extra


def adapter_yaml(aid, command, verbs=("status", "events", "logs"), timeout=5, credentials=(), raw=None):
    """Uma entrada de probes.adapters (indentada para ficar sob `  adapters:`); raw = linhas extras já prontas."""
    lines = [f"    {aid}:", "      command: [" + ", ".join(json.dumps(str(a)) for a in command) + "]"]
    if verbs is not None:
        lines.append("      verbs: [" + ", ".join(json.dumps(v) for v in verbs) + "]")
    if timeout is not None:
        lines.append(f"      timeout: {timeout}")
    if credentials:
        lines.append("      credentials: [" + ", ".join(json.dumps(c) for c in credentials) + "]")
    lines += list(raw or ())
    return "\n".join(lines) + "\n"


def probes_yaml(adapters, enabled=True, limits="{lines: 200, since: 30m}", indent=""):
    text = "probes:\n" + f"  enabled: {'true' if enabled else 'false'}\n"
    if limits is not None:
        text += f"  limits: {limits}\n"
    text += "  adapters:\n" + "".join(adapters)
    return "".join(indent + line + "\n" for line in text.splitlines())


def build_probe_atlas(box: Sandbox, local_extra=""):
    """init --mode local, Applications fora do atlas, environments e access; scan e build."""
    out = box.init(mode="local")
    assert out.returncode == 0, output(out)
    inputs = box.atlas.parent / "inputs"
    inputs.mkdir(exist_ok=True)
    (inputs / "apps.json").write_text(json.dumps(probe_apps()), encoding="utf-8")
    command = ["python3", "{skill}/assets/collectors/argocd.py", "--from", "argocd", "--input",
               "{atlas}/../inputs/apps.json", "--service-pattern", PATTERN]
    (box.atlas / "atlas-config.yml").write_text(collectors_yaml([("argocd", "delivery", command)])
                                                 + environments_yaml(ENVIRONMENTS), encoding="utf-8")
    box.write_local(local_text(box.atlas, local_extra))
    for step in ("scan", "build"):
        out = box.run(step)
        assert out.returncode == 0, f"{step} falhou: {output(out)}"


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


class ProbeCase(unittest.TestCase):
    """Um atlas por classe (o probe nunca escreve no atlas); cada teste tem a própria pasta de configuração local e o
    próprio registro de processos do dublê."""

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
        self.cfg = self.box.root / "cfg" / name
        self.record = self.box.root / "calls" / f"{name}.jsonl"
        self.record.parent.mkdir(parents=True, exist_ok=True)

    def fake(self, script, *extra, adapter="fake"):
        return [sys.executable, str(FAKES / script), "--record", str(self.record), "--adapter", adapter, *extra]

    def configure(self, probes_text, access=None, credentials="{}"):
        self.box.write_local(local_text(self.box.atlas, probes_text, access, credentials), config_home=self.cfg)

    def configure_ok(self, verbs=("status", "events", "logs"), described="status,events,logs", extra=(), **opts):
        self.configure(probes_yaml([adapter_yaml("fake", self.fake("ok.py", "--verbs", f"runtime={described}",
                                                                     *extra), verbs=verbs)]), **opts)

    def probe(self, *args, env=None):
        result = self.box.run("probe", *args, config_home=self.cfg, env=env)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

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

    def assertExit(self, result, code):
        self.assertEqual(result.returncode, code, output(result))

    def assertArgumentError(self, result, text):
        """exit 2 do próprio subcomando probe (não o "invalid choice" do argparse de hoje), com `text` no motivo."""
        self.assertExit(result, 2)
        self.assertNotIn("invalid choice", output(result))
        self.assertIn(text, output(result))

    def assertRefused(self, result, text):
        self.assertExit(result, 4)
        self.assertIn(text, output(result))
        self.assertEqual(self.calls("run"), [], "o adaptador rodou numa probe recusada")

    def json_out(self, result):
        self.assertExit(result, 0)
        return json.loads(result.stdout)


# --------------------------------------------------------------------------- CH-01


def _normalize(text, root, today):
    text = text.replace(str(root), "<ROOT>")
    text = TIMESTAMP_RE.sub("<TS>", text)
    return text.replace(today, "<TODAY>")


def ch01_outputs(probes_text="", recorder=None):
    """Atlas novo com o mapa de acesso e a configuração local (+ probes_text); saídas dos comandos de hoje,
    normalizadas (gravam o golden e servem à comparação)."""
    box = Sandbox()
    try:
        build_probe_atlas(box, probes_text.replace("<RECORD>", str(recorder or box.root / "calls.jsonl")))
        today = json.loads((box.atlas / "snapshots" / "_scan.json").read_text(encoding="utf-8"))["argocd"]["seen_at"]

        def norm(text):
            return _normalize(text, box.root, today)

        pages = {p.relative_to(box.atlas).as_posix(): norm(p.read_text(encoding="utf-8"))
                 for p in sorted(box.atlas.rglob("*.md"))}
        graph = json.loads(norm((box.atlas / "graph.json").read_text(encoding="utf-8")))
        context_json = json.loads(norm(box.run("context", "--json", "api").stdout))
        if context_json.get("version") == atlas().ATLAS_VERSION:
            context_json["version"] = "<VERSION>"
        context_markdown = norm(box.run("context", "api").stdout)
        doctor = box.run("doctor")
        lint = box.run("lint", "--json")
        lint_data = json.loads(norm(lint.stdout))
        config = box.run("config", "--json")
        return {"graph": graph, "pages": pages, "context_json": context_json, "context_markdown": context_markdown,
                "doctor": [norm(f"{s} {i} — {d}") for s, i, d in doctor_lines(doctor.stdout)],
                "doctor_exit": doctor.returncode, "lint": lint_data["findings"], "lint_errors": lint_data["errors"],
                "lint_exit": lint.returncode, "config": json.loads(norm(config.stdout)),
                "config_exit": config.returncode, "recorded": (box.root / "calls.jsonl").exists()}
    finally:
        box.cleanup()


def without_probe_additions(outputs: dict) -> dict:
    """Tira o que a SPEC-0088 acrescenta às saídas de hoje: a chave probes do config --json e as linhas de probes e
    adaptadores do doctor."""
    data = copy.deepcopy(outputs)
    for part in ("values", "origins"):
        data["config"].get(part, {}).pop("probes", None)
    data["doctor"] = [line for line in data["doctor"]
                      if not re.match(r"^\S+ [^—]*(probe|adaptador)", line, re.IGNORECASE)]
    return data


def record_golden():  # pragma: no cover — rodado uma vez, com o código anterior à SPEC-0088
    data = ch01_outputs()
    data.pop("recorded")
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


DISABLED_PROBES = ("probes:\n  enabled: false\n  adapters:\n    fake:\n"
                   f"      command: [{json.dumps(sys.executable)}, {json.dumps(str(FAKES / 'ok.py'))}, "
                   "\"--record\", \"<RECORD>\"]\n      verbs: [status]\n      timeout: 5\n")


class CharacterizationTest(unittest.TestCase):
    def test_todays_commands_give_todays_outputs_without_probes_or_disabled(self):
        """SPEC-0088:CH-01 — sem a chave probes, e com probes.enabled: false e um adaptador declarado, scan, build,
        context, doctor, lint e config --json dão as saídas do golden gravado antes da mudança (a não ser pelas
        linhas novas do doctor sobre probes e pela chave probes do config); nenhum adaptador roda."""
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        for name, text in (("sem a chave", ""), ("enabled: false", DISABLED_PROBES)):
            with self.subTest(variant=name):
                got = without_probe_additions(ch01_outputs(text))
                self.assertFalse(got.pop("recorded"), "um adaptador rodou com probes desligadas")
                self.assertTrue(got["context_json"]["services"], "o context não achou serviço: o teste não vale")
                for key in sorted(golden):
                    if key == "pages":
                        self.assertEqual(sorted(got["pages"]), sorted(golden["pages"]))
                        for path, page in golden["pages"].items():
                            self.assertEqual(got["pages"][path], page, path)
                    else:
                        self.assertEqual(got[key], golden[key], key)


class DisabledProbeTest(ProbeCase):
    def test_probe_without_the_key_or_disabled_is_refused_without_running_anything(self):
        """SPEC-0088:CH-01 — sem a chave probes, e com enabled: false, `probe runtime status --service api --env dev`
        sai com 4, "probes desligadas", e nenhum processo do adaptador roda (nem o --describe)."""
        variants = (("sem a chave", ""),
                    ("enabled: false", probes_yaml([adapter_yaml("fake", self.fake("ok.py"))], enabled=False)))
        for name, text in variants:
            with self.subTest(variant=name):
                self.configure(text)
                result = self.probe("runtime", "status", "--service", "api", "--env", "dev")
                self.assertExit(result, 4)
                self.assertIn(DISABLED, output(result))
                self.assertEqual(self.calls(), [], "um processo do adaptador rodou com probes desligadas")


# --------------------------------------------------------------------------- UT-01


class ConfigTest(ProbeCase):
    def test_a_valid_probes_key_shows_in_config_json_without_credential_values(self):
        """SPEC-0088:UT-01 — probes com adaptador, verbos, timeout e credenciais válidos: config --json sai com 0 e
        mostra enabled, o adaptador, os verbos, o timeout e os nomes das credenciais; o valor da credencial no
        ambiente nunca aparece."""
        self.configure(probes_yaml([adapter_yaml("fake", self.fake("ok.py"), verbs=("status", "logs"), timeout=7,
                                                 credentials=("PROBE_FAKE_TOKEN",))]))
        result = self.box.run("config", "--json", config_home=self.cfg, env={"PROBE_FAKE_TOKEN": FAKE_VALUE})
        self.assertExit(result, 0)
        self.assertNotIn(FAKE_VALUE, output(result))
        probes = find_key(json.loads(result.stdout), "probes")
        self.assertIsInstance(probes, dict, f"config --json sem a chave probes: {result.stdout}")
        probes = normalize(probes)
        self.assertIn(probes.get("enabled"), ("True", "true"))
        adapter = probes.get("adapters", {}).get("fake")
        self.assertIsInstance(adapter, dict, probes)
        self.assertEqual(adapter.get("verbs"), ["status", "logs"])
        self.assertEqual(adapter.get("timeout"), "7")
        self.assertEqual(adapter.get("credentials"), ["PROBE_FAKE_TOKEN"])

    def invalid_cases(self):
        def adapter(**opts):
            return probes_yaml([adapter_yaml("fake", self.fake("ok.py"), **opts)])

        return [
            ("timeout 0", adapter(timeout=0), "timeout", None),
            ("timeout acima de 300", adapter(timeout=4242), "timeout", "4242"),
            ("lines 0", probes_yaml([adapter_yaml("fake", self.fake("ok.py"))], limits="{lines: 0, since: 30m}"),
             "lines", None),
            ("lines acima de 2000", probes_yaml([adapter_yaml("fake", self.fake("ok.py"))],
                                                limits="{lines: 7777, since: 30m}"), "lines", "7777"),
            ("since acima de 24h", probes_yaml([adapter_yaml("fake", self.fake("ok.py"))],
                                               limits="{lines: 200, since: 99h}"), "since", "99h"),
            ("verbo com espaço", adapter(verbs=("status", "get pods")), "verbs", "get pods"),
            ("credencial com valor", adapter(credentials=(f"PROBE_FAKE_TOKEN={FAKE_VALUE}",)), "credentials",
             FAKE_VALUE),
        ]

    def test_an_invalid_field_exits_2_without_the_value(self):
        """SPEC-0088:UT-01 — timeout fora de 1..300, lines fora de 1..2000, since acima de 24h, verbo com espaço e
        credencial com valor: config --json e probe saem com 2, "probes: <campo> inválido — <motivo>", sem o valor
        e sem rodar o adaptador."""
        for name, text, field, value in self.invalid_cases():
            for command in (("config", "--json"), ("probe", "runtime", "status", "--service", "api", "--env", "dev")):
                with self.subTest(case=name, command=command[0]):
                    self.configure(text)
                    result = self.box.run(*command, config_home=self.cfg)
                    self.assertNotIn("Traceback", output(result))
                    self.assertExit(result, 2)
                    self.assertRegex(output(result), FIELD_RE.format(field=field))
                    if value is not None:
                        self.assertNotIn(value, output(result))
                    self.assertEqual(self.calls("run"), [])

    def test_probes_inside_an_entry_of_the_multi_atlas_form(self):
        """SPEC-0088:UT-01 — na forma com vários atlas, probes fica dentro da entrada: config --json sai com 0 e mostra
        probes, e `probe runtime status` roda o adaptador da entrada escolhida."""
        entry = local_text(self.box.atlas, probes_yaml([adapter_yaml("fake", self.fake("ok.py"))]))
        text = "default: acme\natlases:\n  acme:\n" + "".join(f"    {line}\n" for line in entry.splitlines())
        self.box.write_local(text, config_home=self.cfg)
        result = self.box.run("config", "--json", config_home=self.cfg)
        self.assertExit(result, 0)
        self.assertIsInstance(find_key(json.loads(result.stdout), "probes"), dict)
        result = self.probe("runtime", "status", "--service", "api", "--env", "dev", "--json")
        self.assertExit(result, 0)
        self.assertEqual(len(self.calls("run")), 1)

    def test_doctor_shows_probes_on_or_off_and_each_adapter_found_or_not(self):
        """SPEC-0088:UT-01 (doctor, seção 2) — com probes ligadas, uma linha das probes ("ligadas") e uma por
        adaptador: o encontrado em OK, o de executável ausente fora de OK; desligadas, a linha diz "desligadas"."""
        missing = str(self.box.root / "nao-existe" / "adaptador-ausente")
        self.configure(probes_yaml([adapter_yaml("fake", self.fake("ok.py")),
                                    adapter_yaml("ausente", [missing], verbs=("status",))]))
        result = self.box.run("doctor", config_home=self.cfg)
        self.assertNotIn("Traceback", output(result))
        rows = [(s, f"{i} — {d}") for s, i, d in doctor_lines(result.stdout)]
        probe_rows = [text for _, text in rows if "probe" in text.lower()]
        self.assertTrue(any("ligad" in text.lower() and "deslig" not in text.lower() for text in probe_rows),
                        result.stdout)
        fake_rows = [s for s, text in rows if re.search(r"\bfake\b", text)]
        missing_rows = [s for s, text in rows if re.search(r"\bausente\b", text)]
        self.assertEqual(fake_rows[:1], ["OK"], result.stdout)
        self.assertTrue(missing_rows and missing_rows[0] != "OK", result.stdout)
        self.configure(probes_yaml([adapter_yaml("fake", self.fake("ok.py"))], enabled=False))
        result = self.box.run("doctor", config_home=self.cfg)
        self.assertTrue(any("probe" in f"{i} {d}".lower() and "deslig" in f"{i} {d}".lower()
                            for _, i, d in doctor_lines(result.stdout)), result.stdout)


# --------------------------------------------------------------------------- UT-02


class VerbsTest(ProbeCase):
    def test_a_verb_outside_the_intersection_is_refused_and_the_adapter_never_runs(self):
        """SPEC-0088:UT-02 — adaptador declara runtime: [status, logs] e a configuração libera [status]: `probe
        runtime logs` e `probe runtime delete` saem com 4, "verbo <v> não permitido", sem rodar o adaptador."""
        self.configure_ok(verbs=("status",), described="status,logs")
        for verb in ("logs", "delete"):
            with self.subTest(verb=verb):
                result = self.probe("runtime", verb, "--service", "api", "--env", "dev")
                self.assertRefused(result, f"verbo {verb} não permitido")

    def test_a_verb_allowed_by_the_config_but_not_declared_by_the_adapter_is_refused(self):
        """SPEC-0088:UT-02 — configuração libera [status, delete] e o adaptador declara [status, logs]: delete sai
        com 4 sem rodar; status (na interseção) roda uma vez e sai com 0."""
        self.configure_ok(verbs=("status", "delete"), described="status,logs")
        self.assertRefused(self.probe("runtime", "delete", "--service", "api", "--env", "dev"),
                           "verbo delete não permitido")
        self.assertExit(self.probe("runtime", "status", "--service", "api", "--env", "dev", "--json"), 0)
        self.assertEqual(len(self.calls("run")), 1)

    def test_a_capability_without_adapter_is_refused(self):
        """SPEC-0088:UT-02 (passo 3 do contrato) — nenhum adaptador declara sql: exit 4, "nenhum adaptador para
        sql", sem rodar nada."""
        self.configure_ok()
        self.assertRefused(self.probe("sql", "status", "--service", "api", "--env", "dev"),
                           "nenhum adaptador para sql")

    def test_a_target_without_deployment_exits_2(self):
        """SPEC-0088:UT-02 (passo 2 do contrato) — serviço ou ambiente sem deployment no grafo: exit 2 do probe, com o
        nome procurado no motivo, sem rodar."""
        self.configure_ok()
        for args in (("--service", "api", "--env", "nope"), ("--service", "nope", "--env", "dev")):
            with self.subTest(args=args):
                self.assertArgumentError(self.probe("runtime", "status", *args), "nope")
                self.assertEqual(self.calls("run"), [])


# --------------------------------------------------------------------------- UT-03


class ProductionTest(ProbeCase):
    def test_production_and_untiered_environments_need_confirmation(self):
        """SPEC-0088:UT-03 — qa (tier production) e stg (sem tier): sem --confirm-production, exit 4 com a mensagem do
        contrato e o adaptador sem rodar; com a opção, roda e registra confirmed_production: true."""
        self.configure_ok()
        for env in ("qa", "stg"):
            with self.subTest(env=env):
                before = len(self.calls("run"))
                result = self.probe("runtime", "status", "--service", "api", "--env", env)
                self.assertExit(result, 4)
                self.assertIn(f"ambiente {env} é de produção ou sem marcação", output(result))
                self.assertIn("--confirm-production", output(result))
                self.assertEqual(len(self.calls("run")), before)
                result = self.probe("runtime", "status", "--service", "api", "--env", env, "--confirm-production",
                                    "--json")
                self.assertExit(result, 0)
                self.assertEqual(len(self.calls("run")), before + 1)
                last = self.log()[-1]
                self.assertEqual((last["environment"], last["confirmed_production"]), (env, True))

    def test_a_test_environment_runs_without_confirmation(self):
        """SPEC-0088:UT-03 — dev (tier test) roda sem --confirm-production e registra confirmed_production: false."""
        self.configure_ok()
        self.assertExit(self.probe("runtime", "status", "--service", "api", "--env", "dev", "--json"), 0)
        self.assertEqual(len(self.calls("run")), 1)
        last = self.log()[-1]
        self.assertEqual((last["environment"], last["confirmed_production"]), ("dev", False))

    def test_a_cluster_without_local_access_is_refused(self):
        """SPEC-0088:UT-03 — sbx (tier test) roda em cluster-sbx, que não está em access.clusters: exit 4, "sem acesso
        local ao cluster cluster-sbx"; qa confirmado sem cluster-qa em access também sai com 4."""
        self.configure_ok()
        self.assertRefused(self.probe("runtime", "status", "--service", "api", "--env", "sbx"),
                           "sem acesso local ao cluster cluster-sbx")
        self.configure_ok(access={"cluster-dev": CONTEXTS["cluster-dev"]})
        self.assertRefused(self.probe("runtime", "status", "--service", "api", "--env", "qa", "--confirm-production"),
                           "sem acesso local ao cluster cluster-qa")


# --------------------------------------------------------------------------- UT-04


class OutputTest(ProbeCase):
    def items_file(self, items, name="items.json"):
        path = self.box.root / "items" / f"{self.id().rsplit('.', 1)[-1]}-{name}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items), encoding="utf-8")
        return str(path)

    def test_secrets_in_items_are_masked(self):
        """SPEC-0088:UT-04 — item com token=ghp_... e um e-mail (no texto e num campo): exit 0, nem o token nem o
        e-mail aparecem; o texto mascarado traz [REDACTED]."""
        token, email = fake_token(), fake_email()
        items = [{"ts": "2026-11-20T10:00:00Z", "line": f"login ok token={token} para {email}", "user": email}]
        self.configure_ok(extra=("--items", self.items_file(items)))
        result = self.probe("runtime", "logs", "--service", "api", "--env", "dev", "--json")
        data = self.json_out(result)
        for secret in (token, email):
            self.assertNotIn(secret, output(result))
        self.assertIn("[REDACTED]", data["items"][0]["line"])

    def test_items_above_the_limit_are_truncated(self):
        """SPEC-0088:UT-04 — o adaptador devolve 500 itens: com --lines 50 saem 50 e truncated: true; sem --lines, vale
        probes.limits.lines (20)."""
        self.configure_ok(extra=("--repeat", "500"))
        data = self.json_out(self.probe("runtime", "status", "--service", "api", "--env", "dev", "--lines", "50",
                                        "--json"))
        self.assertEqual((len(data["items"]), data["truncated"]), (50, True))
        self.configure(probes_yaml([adapter_yaml("fake", self.fake("ok.py", "--repeat", "500"))],
                                   limits="{lines: 20, since: 30m}"))
        data = self.json_out(self.probe("runtime", "status", "--service", "api", "--env", "dev", "--json"))
        self.assertEqual((len(data["items"]), data["truncated"]), (20, True))

    def test_invalid_output_exits_1_with_the_reason_and_no_item(self):
        """SPEC-0088:UT-04 — chave fora do contrato, JSON inválido, item com objeto, contract errado e status fora de
        ok|error: exit 1 com o motivo e nenhum item impresso (o marcador do item nunca aparece)."""
        reasons = {"unknown-key": "chave_extra_0088", "badjson": "json"}
        for kind in ("unknown-key", "badjson", "nested-item", "wrong-contract", "bad-status"):
            with self.subTest(kind=kind):
                self.configure(probes_yaml([adapter_yaml("fake", self.fake("invalid.py", "--kind", kind))]))
                for extra in ((), ("--json",)):
                    result = self.probe("runtime", "status", "--service", "api", "--env", "dev", *extra)
                    self.assertExit(result, 1)
                    self.assertNotIn(MARKER, output(result))
                    self.assertTrue(output(result).strip(), "exit 1 sem motivo")
                    if kind in reasons:
                        self.assertIn(reasons[kind], output(result).lower())

    def test_a_timeout_exits_1_with_the_reason_and_no_item(self):
        """SPEC-0088:UT-04 — adaptador que demora mais que o timeout (1 s): exit 1 com o motivo (tempo esgotado), sem
        item, em bem menos que o sono do adaptador."""
        self.configure(probes_yaml([adapter_yaml("fake", self.fake("slow.py"), timeout=1)]))
        started = time.monotonic()
        result = self.probe("runtime", "status", "--service", "api", "--env", "dev", "--json")
        self.assertLess(time.monotonic() - started, 20)
        self.assertExit(result, 1)
        self.assertNotIn(MARKER, output(result))
        self.assertRegex(output(result).lower(), r"tempo|timeout")

    def test_an_error_message_is_masked(self):
        """SPEC-0088:UT-04 — adaptador com status error e message com token e e-mail: exit 1, a mensagem aparece com o
        token e o e-mail mascarados."""
        self.configure(probes_yaml([adapter_yaml("fake", self.fake("error.py"))]))
        for extra in ((), ("--json",)):
            with self.subTest(extra=extra):
                result = self.probe("runtime", "status", "--service", "api", "--env", "dev", *extra)
                self.assertExit(result, 1)
                self.assertIn(ERROR_MESSAGE, output(result))
                self.assertNotIn("ghp_" + "Qw8" * 12, output(result))
                self.assertNotIn("pessoa.falsa" + "@" + "example.com", output(result))

    def test_limits_out_of_range_in_the_arguments_exit_2(self):
        """SPEC-0088:UT-04 (limites) — --lines 0 ou acima de 2000 e --since acima de 24h: exit 2, sem rodar."""
        self.configure_ok()
        for args in (("--lines", "0"), ("--lines", "2001"), ("--since", "25h"), ("--since", "abc")):
            with self.subTest(args=args):
                result = self.probe("runtime", "status", "--service", "api", "--env", "dev", *args)
                self.assertArgumentError(result, args[0].lstrip("-"))
                self.assertEqual(self.calls("run"), [])


# --------------------------------------------------------------------------- UT-05


class LocalLogTest(ProbeCase):
    def test_each_probe_leaves_one_local_line_without_results_and_nothing_in_the_atlas(self):
        """SPEC-0088:UT-05 — probes com sucesso, com erro e recusadas (verbo e produção): probes.log na pasta da
        configuração local com uma linha por probe, exatamente as chaves do contrato, sem items, message nem o
        contexto; a árvore do atlas fica igual (conteúdo e mtime)."""
        self.configure(probes_yaml([
            adapter_yaml("fake", self.fake("ok.py", "--verbs", "runtime=status,logs"), verbs=("status", "logs")),
            adapter_yaml("broken", self.fake("error.py", "--verbs", "failing=status", adapter="broken"),
                         verbs=("status",)),
        ]))
        before = snapshot(self.box.atlas)
        runs = [(("runtime", "status", "--env", "dev", "--json"), 0, "fake", "dev", "runtime", "status"),
                (("failing", "status", "--env", "dev"), 1, "broken", "dev", "failing", "status"),
                (("runtime", "delete", "--env", "dev"), 4, "fake", "dev", "runtime", "delete"),
                (("runtime", "status", "--env", "qa"), 4, "fake", "qa", "runtime", "status")]
        for args, code, *_ in runs:
            self.assertExit(self.probe(args[0], args[1], "--service", "api", *args[2:]), code)
        self.assertEqual(snapshot(self.box.atlas), before, "o probe mudou a pasta do atlas")
        lines = self.log()
        self.assertEqual(len(lines), len(runs), lines)
        for line, (_, code, adapter, env, capability, verb) in zip(lines, runs):
            # SPEC-0104:UT-06 — reason fora do ok
            self.assertEqual(set(line), LOG_KEYS if line["status"] == "ok" else LOG_KEYS | {"reason"})
            self.assertEqual((line["atlas"], line["service"], line["environment"], line["capability"], line["verb"],
                              line["adapter"], line["exit"]), ("acme", "api", env, capability, verb, adapter, code))
            self.assertIs(line["confirmed_production"], False)
            self.assertIsInstance(line["at"], str)
        self.assertEqual([line["status"] for line in lines[:2]], ["ok", "error"])
        text = (self.cfg / "probes.log").read_text(encoding="utf-8")
        for forbidden in (ERROR_MESSAGE, "restarts", *CONTEXTS.values(), '"items"', '"message"'):
            self.assertNotIn(forbidden, text)
        self.assertFalse(list(self.box.atlas.rglob("probes.log")))


# --------------------------------------------------------------------------- UT-06


class SummaryTest(ProbeCase):
    def summary(self, items):
        path = self.box.root / "items" / f"{self.id().rsplit('.', 1)[-1]}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items), encoding="utf-8")
        self.configure_ok(extra=("--items", str(path)))
        result = self.probe("runtime", "logs", "--service", "api", "--env", "dev", "--summary", "--json")
        return result, self.json_out(result)["items"]

    def test_log_lines_are_grouped_by_level_and_signature(self):
        """SPEC-0088:UT-06 — ERROR user 123 not found, ERROR user 456 not found, WARN retry 3 of 5 e ERROR id <uuid>
        failed: duas assinaturas de erro (a do user com 2, primeiro e último horário certos; a do UUID com 1) e uma de
        aviso, ordenadas por nível e contagem, com exatamente as chaves do contrato."""
        lines = [("2026-11-20T10:00:00Z", "ERROR user 123 not found"), ("2026-11-20T10:01:00Z", "WARN retry 3 of 5"),
                 ("2026-11-20T10:02:00Z", "ERROR user 456 not found"),
                 ("2026-11-20T10:03:00Z", f"ERROR id {UUID} failed")]
        _, items = self.summary([{"ts": ts, "line": line} for ts, line in lines])
        self.assertEqual(len(items), 3, items)
        for item in items:
            self.assertEqual(set(item), SUMMARY_KEYS)
        self.assertEqual([i["level"] for i in items], ["error", "error", "warn"])
        user, uuid_item, warn = items
        self.assertEqual((user["count"], user["first_ts"], user["last_ts"]),
                         (2, "2026-11-20T10:00:00Z", "2026-11-20T10:02:00Z"))
        self.assertTrue(user["signature"].startswith("ERROR user ") and user["signature"].endswith(" not found"),
                        user["signature"])
        for number in ("123", "456"):
            self.assertNotIn(number, user["signature"])
        self.assertIn(user["sample"], {"ERROR user 123 not found", "ERROR user 456 not found"})
        self.assertEqual((uuid_item["count"], uuid_item["first_ts"], uuid_item["last_ts"]),
                         (1, "2026-11-20T10:03:00Z", "2026-11-20T10:03:00Z"))
        self.assertNotIn(UUID, uuid_item["signature"])
        self.assertNotIn("5f2b", uuid_item["signature"])
        self.assertIn("failed", uuid_item["signature"])
        self.assertEqual(warn["count"], 1)
        self.assertIn("retry", warn["signature"])
        self.assertIsNone(re.search(r"\b[35]\b", warn["signature"]), warn["signature"])

    def test_hex_emails_and_quoted_text_are_replaced_and_samples_are_masked(self):
        """SPEC-0088:UT-06 — hexadecimais de 8 ou mais, e-mails e textos entre aspas viram marcadores: duas linhas INFO
        que só diferem neles dão uma assinatura info × 2; duas sem nível dão uma other × 2; a amostra sai mascarada."""
        lines = [("2026-11-20T11:00:00Z", f"INFO cache deadbeef0123 refreshed for {fake_email(1)}"),
                 ("2026-11-20T11:01:00Z", 'job "nightly" done'),
                 ("2026-11-20T11:02:00Z", f"INFO cache cafebabe4567 refreshed for {fake_email(2)}"),
                 ("2026-11-20T11:03:00Z", 'job "weekly" done')]
        result, items = self.summary([{"ts": ts, "line": line} for ts, line in lines])
        self.assertEqual([(i["level"], i["count"]) for i in items], [("info", 2), ("other", 2)], items)
        for text in ("deadbeef0123", "cafebabe4567", "nightly", "weekly", "@example.com"):
            self.assertNotIn(text, items[0]["signature"] + items[1]["signature"])
        self.assertNotIn("@example.com", output(result))

    def test_summary_without_items_exits_0_with_zero_signatures(self):
        """SPEC-0088:UT-06 (Emenda v4) — adaptador sem itens (janela vazia) com --summary: exit 0 e zero assinaturas,
        em --json e em texto."""
        result, items = self.summary([])
        self.assertEqual(items, [], result.stdout)
        self.assertExit(self.probe("runtime", "logs", "--service", "api", "--env", "dev", "--summary"), 0)

    def test_summary_of_items_without_line_still_exits_2(self):
        """SPEC-0088:UT-06 (Emenda v4) — itens sem nenhum line com --summary: exit 2, em --json e em texto."""
        path = self.box.root / "items" / f"{self.id().rsplit('.', 1)[-1]}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([{"name": "api", "ready": "1/1"}]), encoding="utf-8")
        self.configure_ok(extra=("--items", str(path)))
        for extra in ((), ("--json",)):
            with self.subTest(extra=extra):
                self.assertExit(self.probe("runtime", "logs", "--service", "api", "--env", "dev", "--summary",
                                           *extra), 2)


# --------------------------------------------------------------------------- Emenda v4 (achados da rodada 1 do G4)


CONTEXT_DEV = CONTEXTS["cluster-dev"]
CREDENTIAL_VALUE = FAKE_VALUE + "-credencial"


class ContextMaskingTest(ProbeCase):
    """Emenda v4 — o contexto escolhido e os valores das credenciais declaradas são mascarados em tudo o que vem do
    adaptador (itens, chaves, message, cauda do stderr, amostra do --summary, falha do contrato)."""

    def run_echo(self, mode, verb="status", extra=()):
        self.configure(probes_yaml([adapter_yaml("fake", self.fake("echo_context.py", "--mode", mode, "--env-name",
                                                                   "PROBE_FAKE_TOKEN"),
                                                 credentials=("PROBE_FAKE_TOKEN",))]))
        results = []
        for flag in ((), ("--json",)):
            result = self.probe("runtime", verb, "--service", "api", "--env", "dev", *extra, *flag,
                                env={"PROBE_FAKE_TOKEN": CREDENTIAL_VALUE})
            runs = self.calls("run")
            self.assertTrue(runs, "o adaptador não rodou: o teste não vale")
            self.assertEqual(runs[-1]["input"]["target"]["context"], CONTEXT_DEV)
            results.append(result)
        return results

    def assertMasked(self, results):
        log = (self.cfg / "probes.log").read_text(encoding="utf-8") if (self.cfg / "probes.log").exists() else ""
        for text in [output(r) for r in results] + [log]:
            self.assertNotIn(CONTEXT_DEV, text, "o contexto escolhido vazou na saída do probe")
            self.assertNotIn(CREDENTIAL_VALUE, text, "o valor de uma credencial declarada vazou na saída do probe")

    def test_context_echoed_in_stderr_on_exit_1_is_masked(self):
        """SPEC-0088:UT-04 (Emenda v4) — adaptador que sai com 1 e escreve o contexto e o valor da credencial
        declarada no stderr: o probe sai com 1 e a cauda do stderr mostrada não traz nenhum dos dois (texto e
        --json); o probes.log também não."""
        results = self.run_echo("stderr")
        for result in results:
            self.assertExit(result, 1)
        self.assertMasked(results)

    def test_context_echoed_in_the_error_message_is_masked(self):
        """SPEC-0088:UT-04 (Emenda v4) — status error com o contexto e o valor da credencial na message: exit 1 e a
        mensagem mostrada (texto e --json) sem nenhum dos dois."""
        results = self.run_echo("message")
        for result in results:
            self.assertExit(result, 1)
        self.assertMasked(results)

    def test_context_echoed_in_item_keys_and_values_is_masked(self):
        """SPEC-0088:UT-04 (Emenda v4) — itens cuja chave e cujo valor são o contexto (e o valor da credencial):
        exit 0 e nem as chaves nem os valores impressos (texto e --json) trazem os dois."""
        results = self.run_echo("items")
        for result in results:
            self.assertExit(result, 0)
        self.assertMasked(results)

    def test_context_echoed_in_log_lines_is_masked_in_the_summary(self):
        """SPEC-0088:UT-06 (Emenda v4) — linhas de log com o contexto e o valor da credencial no meio, com --summary:
        exit 0 e nem a amostra nem a assinatura (texto e --json) trazem os dois."""
        results = self.run_echo("summary", verb="logs", extra=("--summary",))
        for result in results:
            self.assertExit(result, 0)
        self.assertMasked(results)

    def test_context_in_a_key_of_an_output_outside_the_contract_is_masked(self):
        """SPEC-0088:UT-04 (Emenda v4) — item com o contexto (e o valor da credencial) como chave de um objeto: exit 1
        por saída fora do contrato, e o texto da falha não cita a chave crua."""
        results = self.run_echo("contract")
        for result in results:
            self.assertExit(result, 1)
        self.assertMasked(results)

    def test_context_echoed_as_the_adapter_field_is_masked(self):
        """SPEC-0088:UT-04 (Emenda v4) — o campo adapter da saída é o próprio contexto: ele não aparece na saída do
        probe (texto e --json)."""
        self.assertMasked(self.run_echo("adapter"))


class InvalidJsonV4Test(ProbeCase):
    def test_deep_nesting_nan_and_infinity_exit_1_as_invalid_json(self):
        """SPEC-0088:UT-04 (Emenda v4) — saída com "[" × 100000 (RecursionError no parser), com NaN ou com
        Infinity/-Infinity: exit 1 como JSON inválido, com o motivo, sem traceback e sem item impresso; nenhuma
        constante fora do JSON padrão sai em --json."""
        for kind in ("deep", "nan", "infinity"):
            self.configure(probes_yaml([adapter_yaml("fake", self.fake("invalid.py", "--kind", kind))]))
            for extra in ((), ("--json",)):
                with self.subTest(kind=kind, extra=extra):
                    result = self.probe("runtime", "status", "--service", "api", "--env", "dev", *extra)
                    self.assertExit(result, 1)
                    self.assertNotIn(MARKER, output(result))
                    self.assertIn("json", output(result).lower())
                    for constant in ("NaN", "Infinity"):
                        self.assertNotIn(constant, result.stdout)


class CommandPathTest(ProbeCase):
    def relative_scripts(self):
        """box.root/x.py e box.root/rel/x.py, executáveis, que repassam ao ok.py (o cwd da CLI nos testes é
        box.root: se o caminho relativo fosse aceito, o doctor os acharia)."""
        body = (f"#!{sys.executable}\nimport os, sys\nos.execv({sys.executable!r}, [{sys.executable!r}, "
                f"{str(FAKES / 'ok.py')!r}] + sys.argv[1:])\n")
        for rel in ("x.py", "rel/x.py"):
            path = self.box.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)

    def test_a_relative_command_is_refused_in_config_probe_and_doctor(self):
        """SPEC-0088:UT-01 (Emenda v4) — command com caminho relativo que tem separador (./x.py, rel/x.py): config
        --json e probe saem com 2, "probes: ...command inválido — ...", sem rodar o adaptador; o doctor mostra um
        ERRO (e não OK) para ele."""
        self.relative_scripts()
        for rel in ("./x.py", "rel/x.py"):
            with self.subTest(command=rel):
                self.configure(probes_yaml([adapter_yaml("fake", [rel, "--record", str(self.record)])]))
                result = self.box.run("config", "--json", config_home=self.cfg)
                self.assertNotIn("Traceback", output(result))
                self.assertExit(result, 2)
                self.assertRegex(output(result), FIELD_RE.format(field="command"))
                result = self.probe("runtime", "status", "--service", "api", "--env", "dev", "--json")
                self.assertExit(result, 2)
                self.assertRegex(output(result), FIELD_RE.format(field="command"))
                self.assertEqual(self.calls(), [], "o adaptador de command relativo rodou")
                rows = doctor_lines(self.box.run("doctor", config_home=self.cfg).stdout)
                self.assertFalse([r for r in rows if r[0] == "OK" and re.search(r"\bfake\b", r[1])], rows)
                errors = [r for r in rows if r[0] == "ERRO" and re.search(r"probe|adaptador", r[1], re.IGNORECASE)]
                self.assertTrue(errors, rows)

    def test_a_bare_name_on_path_and_an_absolute_path_stay_valid(self):
        """SPEC-0088:UT-01 (Emenda v4, guarda) — command com nome sem separador achado no PATH (python3) e com caminho
        absoluto: config --json sai com 0, o probe roda e o doctor mostra o adaptador em OK."""
        absolute = self.fake("ok.py")
        bare = ["python3", *absolute[1:]]
        for command in (bare, absolute):
            with self.subTest(command=command[0]):
                self.configure(probes_yaml([adapter_yaml("fake", command)]))
                self.assertExit(self.box.run("config", "--json", config_home=self.cfg), 0)
                self.assertExit(self.probe("runtime", "status", "--service", "api", "--env", "dev", "--json"), 0)
                rows = doctor_lines(self.box.run("doctor", config_home=self.cfg).stdout)
                self.assertEqual([r[0] for r in rows if re.search(r"\bfake\b", r[1])][:1], ["OK"], rows)


def _rename(graph, old, new):
    """graph com o nó `old` (chave kind:id) trocado por `new` nas chaves, nos nomes e nas arestas."""
    for node in graph["nodes"]:
        if node["key"] == old:
            node["key"] = new
            node["name"] = new.split(":", 1)[1]
    for edge in graph["edges"]:
        for side in ("from", "to", "evidence"):
            if edge.get(side) == old:
                edge[side] = new
    return graph


def _set_attr(key, attr, value):
    def change(graph):
        for node in graph["nodes"]:
            if node["key"] == key:
                node["attrs"][attr] = value
        return graph
    return change


def _renamed(old, new):
    return lambda graph: _rename(graph, old, new)


DEV_DEPLOYMENT = "deployment:dev-api"
TARGET_CASES = [
    ("namespace com maiúscula", _set_attr(DEV_DEPLOYMENT, "namespace", "Api-Dev"), ()),
    ("namespace com _", _set_attr(DEV_DEPLOYMENT, "namespace", "api_dev"), ()),
    ("namespace com .", _set_attr(DEV_DEPLOYMENT, "namespace", "api.dev"), ()),
    ("namespace com 64", _set_attr(DEV_DEPLOYMENT, "namespace", "a" * 64), ()),
    ("namespace com -", _set_attr(DEV_DEPLOYMENT, "namespace", "-api-dev"), ()),
    ("workload sem Kind", _set_attr(DEV_DEPLOYMENT, "workloads", ["api"]), ()),
    ("workload com maiúscula", _set_attr(DEV_DEPLOYMENT, "workloads", ["Deployment/Api"]), ()),
    ("workload com _", _set_attr(DEV_DEPLOYMENT, "workloads", ["Deployment/api_x"]), ()),
    ("workload com nome -", _set_attr(DEV_DEPLOYMENT, "workloads", ["Deployment/-api"]), ()),
    ("workload com -", _set_attr(DEV_DEPLOYMENT, "workloads", ["-Deployment/api"]), ()),
    ("workload acima de 253", _set_attr(DEV_DEPLOYMENT, "workloads", ["Deployment/" + "a" * 254]), ()),
    ("deployment com -", _renamed(DEV_DEPLOYMENT, "deployment:-dev-api"), ()),
    ("deployment com espaço", _renamed(DEV_DEPLOYMENT, "deployment:dev api"), ()),
    ("deployment com /", _renamed(DEV_DEPLOYMENT, "deployment:dev/api"), ()),
    ("service com -", _renamed("service:api", "service:-api"), ("--service=-api",)),
    ("service com espaço", _renamed("service:api", "service:api x"), ("--service", "api x")),
    ("environment com -", _renamed("environment:dev", "environment:-dev"), ("--env=-dev",)),
    ("environment com /", _renamed("environment:dev", "environment:dev/x"), ("--env", "dev/x")),
]


class TargetFieldsTest(ProbeCase):
    def test_target_fields_out_of_the_rules_exit_2_without_running_anything(self):
        """SPEC-0088:UT-02 (passo 2 do contrato, Emenda v4) — graph.json com namespace fora do DNS-1123, workload fora
        de Kind/nome DNS-1123 subdomínio, campo começando com - e service, deployment ou environment fora da regra de
        nome simples: `probe` sai com 2 e nenhum processo do adaptador roda (nem o --describe, nem a consulta)."""
        graph_path = self.box.atlas / "graph.json"
        original = graph_path.read_text(encoding="utf-8")
        self.configure_ok()
        try:
            for name, change, args in TARGET_CASES:
                with self.subTest(case=name):
                    graph_path.write_text(json.dumps(change(json.loads(original))), encoding="utf-8")
                    args = args or ("--service", "api", "--env", "dev")
                    if not any(a.startswith("--service") for a in args):
                        args = ("--service", "api", *args)
                    if not any(a.startswith("--env") for a in args):
                        args = (*args, "--env", "dev")
                    before = len(self.calls())
                    result = self.probe("runtime", "status", *args, "--confirm-production", "--json")
                    self.assertExit(result, 2)
                    self.assertEqual(len(self.calls()), before, "um processo do adaptador rodou com o alvo inválido")
        finally:
            graph_path.write_text(original, encoding="utf-8")
        result = self.probe("runtime", "status", "--service", "api", "--env", "dev", "--json")
        self.assertExit(result, 0)  # guarda: o alvo de verdade roda (o teste não vale sem isso)


# --------------------------------------------------------------------------- Emenda v5

SECRET_V5 = "SUPERSECRETVALUE" + "0088"  # montado em tempo de execução
ARN_CONTEXT = "arn:aws:eks:region:000000000000:cluster/example"
CREDENTIAL_V5 = FAKE_VALUE + "/credencial:0088"
ECHO_MODES = (("stderr", "status", (), 1), ("message", "status", (), 1), ("items", "status", (), 0),
              ("summary", "logs", ("--summary",), 0))


def _strings(data):
    """Todas as chaves e textos de um JSON já decodificado (a forma escapada some no dump do --json)."""
    if isinstance(data, dict):
        return [t for key, value in data.items() for t in [str(key)] + _strings(value)]
    if isinstance(data, list):
        return [t for value in data for t in _strings(value)]
    return [data] if isinstance(data, str) else []


def _variants(value):
    r"""As formas do valor que a Emenda v5 manda mascarar: escapada em JSON (com \/), codificada em URL e em
    maiúsculas (a comparação é sem diferença de maiúsculas)."""
    return {"json": json.dumps(value, ensure_ascii=False)[1:-1].replace("/", "\\/"),
            "url": urllib.parse.quote(value, safe=""), "upper": value.upper()}


class MaskV5Case(ProbeCase):
    def run_echo_v5(self, mode, verb, extra, context, form, secret=None, credential=None):
        """Roda o echo_context.py com o contexto `context` no cluster-dev (texto e --json) e devolve os textos a
        conferir: as saídas, os textos do JSON decodificado e o probes.log."""
        fake = self.fake("echo_context.py", "--mode", mode, "--form", form,
                         *(("--secret", secret) if secret else ()),
                         *(("--env-name", "PROBE_FAKE_TOKEN") if credential else ()))
        self.configure(probes_yaml([adapter_yaml("fake", fake, credentials=("PROBE_FAKE_TOKEN",) if credential
                                                 else ())]), access=dict(CONTEXTS, **{"cluster-dev": context}))
        texts, codes = [], []
        for flag in ((), ("--json",)):
            result = self.probe("runtime", verb, "--service", "api", "--env", "dev", *extra, *flag,
                                env={"PROBE_FAKE_TOKEN": credential} if credential else None)
            runs = self.calls("run")
            self.assertTrue(runs, "o adaptador não rodou: o teste não vale")
            self.assertEqual(runs[-1]["input"]["target"]["context"], context)
            texts.append(output(result))
            codes.append(result.returncode)
            if flag and result.stdout.strip():
                try:
                    texts += _strings(json.loads(result.stdout))
                except ValueError:
                    pass
        log = self.cfg / "probes.log"
        texts.append(log.read_text(encoding="utf-8") if log.exists() else "")
        return texts, codes


class MaskOrderTest(MaskV5Case):
    def test_a_short_context_does_not_stop_the_secret_pattern(self):
        """SPEC-0088:UT-04 (Emenda v5, ordem da máscara) — contexto curto (api; e access) e um adaptador que escreve
        <contexto>_key=<segredo> (api_key=..., access_key=...) no stderr, na message, num item e numa linha do
        --summary: os padrões de segredo rodam antes do literal do contexto, então o valor do segredo não aparece em
        nenhuma saída (texto e --json) nem no probes.log."""
        for context in ("api", "access"):
            for mode, verb, extra, code in ECHO_MODES:
                with self.subTest(context=context, mode=mode):
                    texts, codes = self.run_echo_v5(mode, verb, extra, context, "keyed", secret=SECRET_V5)
                    self.assertEqual(codes, [code, code], texts)
                    for text in texts:
                        self.assertNotIn(SECRET_V5, text, f"{context}_key=<segredo> vazou: o literal do contexto "
                                                          "rodou antes dos padrões de segredo")


class ContextVariantsTest(MaskV5Case):
    def test_json_url_and_upper_forms_of_the_context_are_masked(self):
        r"""SPEC-0088:UT-04 (Emenda v5, variantes) — contexto ARN genérico (com / e :) que o adaptador escreve
        escapado em JSON (com \/), codificado em URL e em maiúsculas, no stderr, na message, num item e numa linha do
        --summary: nenhuma dessas formas aparece (sem diferença de maiúsculas) nas saídas nem no probes.log."""
        for form, variant in _variants(ARN_CONTEXT).items():
            for mode, verb, extra, code in ECHO_MODES:
                with self.subTest(form=form, mode=mode):
                    texts, codes = self.run_echo_v5(mode, verb, extra, ARN_CONTEXT, form)
                    self.assertEqual(codes, [code, code], texts)
                    for text in texts:
                        self.assertNotIn(variant.lower(), text.lower(), f"a forma {form} do contexto vazou")

    def test_json_url_and_upper_forms_of_a_declared_credential_are_masked(self):
        r"""SPEC-0088:UT-04 (Emenda v5, variantes) — o mesmo para o valor de uma credencial declarada (com / e :):
        nenhuma das formas (JSON com \/, URL, maiúsculas) aparece nas saídas nem no probes.log."""
        for form, variant in _variants(CREDENTIAL_V5).items():
            for mode, verb, extra, code in ECHO_MODES:
                with self.subTest(form=form, mode=mode):
                    texts, codes = self.run_echo_v5(mode, verb, extra, CONTEXT_DEV, form, credential=CREDENTIAL_V5)
                    self.assertEqual(codes, [code, code], texts)
                    for text in texts:
                        self.assertNotIn(variant.lower(), text.lower(), f"a forma {form} da credencial vazou")



# --------------------------------------------------------------------------- Emenda v6

# montados em tempo de execução (genéricos): uma senha com cara de e-mail seguida de um sufixo, e uma senha com um
# gatilho de padrão (token=) no meio
EMAIL_LIKE_CREDENTIAL = "Xy7" + "@" + "k9.Zq" + "!" + "rT5pLmQw"
TRIGGER_TAIL = "DEF" + "SECRETTAIL"
TRIGGER_CREDENTIAL = "zz " + "token" + "=ABC " + TRIGGER_TAIL
OVERLAP_PREFIX = "ctx-0088-ov"
OVERLAP_CONTEXT = OVERLAP_PREFIX + ".api"  # o padrão api_key=... começa no meio do contexto
NESTED_RE = re.compile(r"\[[A-Za-z]*\[REDACTED\]|\[REDACTED\][A-Za-z]*\]")


def _fragments(value, size=4):
    return {value[i:i + size] for i in range(len(value) - size + 1)}


class MaskOnePassTest(MaskV5Case):
    """Emenda v6 — a máscara numa passada só: todos os padrões de segredo e todos os literais (contexto e valores das
    credenciais, com as variantes) casam no texto original, os trechos são juntados e cada trecho resultante vira um
    [REDACTED] só."""

    def assertNoNested(self, text):
        self.assertIsNone(NESTED_RE.search(text), f"marcador aninhado: uma máscara rodou sobre outra: {text!r}")

    def test_a_credential_shaped_like_an_email_is_masked_whole(self):
        """SPEC-0088:UT-04 (Emenda v6) — valor de credencial declarada com cara de e-mail seguido de um sufixo
        (<a>@<b>.<tld>!<resto>), ecoado no stderr, na message, num item e numa linha do --summary: nenhum trecho de 4
        caracteres do valor (em especial o sufixo depois do e-mail) aparece nas saídas (texto e --json) nem no
        probes.log."""
        suffix = EMAIL_LIKE_CREDENTIAL[EMAIL_LIKE_CREDENTIAL.index("!"):]
        for mode, verb, extra, code in ECHO_MODES:
            with self.subTest(mode=mode):
                texts, codes = self.run_echo_v5(mode, verb, extra, CONTEXT_DEV, "raw",
                                                credential=EMAIL_LIKE_CREDENTIAL)
                self.assertEqual(codes, [code, code], texts)
                for text in texts:
                    self.assertNotIn(suffix, text, "o sufixo da senha com cara de e-mail vazou: o padrão de e-mail "
                                                   "mascarou só o começo e o literal não casou mais")
                    for fragment in _fragments(EMAIL_LIKE_CREDENTIAL):
                        self.assertNotIn(fragment, text, f"um trecho do valor da credencial vazou: {fragment!r}")
                    self.assertNoNested(text)

    def test_a_credential_with_a_pattern_trigger_inside_is_masked_whole(self):
        """SPEC-0088:UT-04 (Emenda v6) — valor de credencial declarada com um gatilho de padrão no meio
        (... token=<x> <resto>), ecoado no stderr, na message, num item e numa linha do --summary: o resto depois do
        trecho casado pelo padrão não aparece nas saídas (texto e --json) nem no probes.log."""
        for mode, verb, extra, code in ECHO_MODES:
            with self.subTest(mode=mode):
                texts, codes = self.run_echo_v5(mode, verb, extra, CONTEXT_DEV, "raw", credential=TRIGGER_CREDENTIAL)
                self.assertEqual(codes, [code, code], texts)
                for text in texts:
                    self.assertNotIn(TRIGGER_TAIL, text, "o resto da credencial depois de token=<x> vazou")
                    self.assertNoNested(text)

    def test_a_context_overlapping_a_secret_pattern_becomes_a_single_marker(self):
        """SPEC-0088:UT-04 (Emenda v6, sobreposição) — contexto <prefixo>.api e um adaptador que escreve
        <contexto>_key=<segredo>: o padrão api_key=... começa no meio do contexto; o trecho juntado (contexto inteiro
        e segredo) vira um [REDACTED] só, sem sobrar o prefixo do contexto nem o segredo, e sem marcador aninhado."""
        for mode, verb, extra, code in ECHO_MODES:
            with self.subTest(mode=mode):
                texts, codes = self.run_echo_v5(mode, verb, extra, OVERLAP_CONTEXT, "keyed", secret=SECRET_V5)
                self.assertEqual(codes, [code, code], texts)
                for text in texts:
                    self.assertNotIn(SECRET_V5, text, "o segredo vazou")
                    self.assertNotIn(OVERLAP_PREFIX, text, "o prefixo do contexto sobrou: o padrão mascarou antes "
                                                           "e o literal do contexto não casou mais")
                    self.assertNoNested(text)

    def test_a_context_inside_the_marker_text_does_not_nest_markers(self):
        """SPEC-0088:UT-04 (Emenda v6, sobreposição) — contexto de 3 letras que também é um pedaço do texto do
        marcador (dac, de [REDACTED]) e uma credencial declarada, ecoados no stderr, na message, num item e numa
        linha do --summary: cada trecho casado vira um [REDACTED] só, sem marcador aninhado como [RE[REDACTED]TED]
        (a máscara não roda sobre o que já foi mascarado)."""
        context = "da" + "c"
        for mode, verb, extra, code in ECHO_MODES:
            with self.subTest(mode=mode):
                texts, codes = self.run_echo_v5(mode, verb, extra, context, "raw", credential=CREDENTIAL_VALUE)
                self.assertEqual(codes, [code, code], texts)
                for text in texts:
                    self.assertNotIn(CREDENTIAL_VALUE, text, "o valor da credencial vazou")
                    self.assertNoNested(text)

class LoneSurrogateTest(ProbeCase):
    def test_a_lone_surrogate_in_the_output_exits_1_as_invalid_json(self):
        r"""SPEC-0088:UT-04 (Emenda v5) — saída do adaptador com "line": "\ud800 bad" num item, ou com um surrogate
        solto num valor de item: exit 1 como JSON inválido, com o motivo, sem traceback e sem item impresso (texto e
        --json)."""
        for kind in ("surrogate-line", "surrogate-value"):
            self.configure(probes_yaml([adapter_yaml("fake", self.fake("invalid.py", "--kind", kind))]))
            for extra in ((), ("--json",)):
                with self.subTest(kind=kind, extra=extra):
                    result = self.probe("runtime", "status", "--service", "api", "--env", "dev", *extra)
                    self.assertExit(result, 1)
                    self.assertNotIn(MARKER, output(result))
                    self.assertIn("json", output(result).lower())


DEV_CLUSTER = "cluster:cluster-dev"


def _cluster_named(name):
    """graph com o nome do nó cluster:cluster-dev trocado por `name` (o id fica: o access.clusters ainda o acha)."""
    def change(graph):
        nodes = [node for node in graph["nodes"] if node["key"] == DEV_CLUSTER]
        assert nodes, f"{DEV_CLUSTER} não está no graph.json: o teste não vale"
        for node in nodes:
            node["name"] = name
        return graph
    return change


class TargetClustersTest(ProbeCase):
    def run_cases(self, names, code):
        graph_path = self.box.atlas / "graph.json"
        original = graph_path.read_text(encoding="utf-8")
        try:
            for name in names:
                with self.subTest(cluster=name):
                    graph_path.write_text(json.dumps(_cluster_named(name)(json.loads(original))), encoding="utf-8")
                    before = len(self.calls())
                    result = self.probe("runtime", "status", "--service", "api", "--env", "dev", "--json")
                    self.assertExit(result, code)
                    if code == 2:
                        self.assertEqual(len(self.calls()), before, "um processo do adaptador rodou com o cluster "
                                                                    "inválido")
                    else:
                        self.assertEqual(self.calls("run")[-1]["input"]["target"]["clusters"], [name])
        finally:
            graph_path.write_text(original, encoding="utf-8")

    def test_cluster_names_out_of_the_rule_exit_2_without_running_anything(self):
        """SPEC-0088:UT-02 (Emenda v5, clusters do alvo) — target.clusters com um nome que começa com -, com espaço
        ou com caractere de controle: `probe` sai com 2 e nenhum processo do adaptador roda (nem o --describe)."""
        self.configure_ok()
        self.run_cases(["-cluster-dev", "cluster dev", "cluster\x07dev", "-https://kubernetes.default.svc",
                        "https://kubernetes.default.svc/a b"], 2)

    def test_a_simple_name_and_a_server_url_still_run(self):
        """SPEC-0088:UT-02 (Emenda v5, guarda) — um nome simples e a URL https://kubernetes.default.svc continuam
        rodando (exit 0, o adaptador recebe o nome em target.clusters)."""
        self.configure_ok()
        self.run_cases(["cluster-dev-b", "https://kubernetes.default.svc"], 0)


# --------------------------------------------------------------------------- IT-01


class EndToEndTest(ProbeCase):
    def test_the_cli_runs_a_real_fake_adapter_with_only_its_declared_credentials(self):
        """SPEC-0088:IT-01 — atlas temporário com o mapa de acesso e o adaptador falso env_names.py: `atlas.py probe
        runtime status --service api --env dev --json` sai com 0; a saída segue probe@1; a entrada no stdin é a do
        contrato (alvo, contexto local e limites padrão; --since 2h --lines 50 viram since_seconds 7200 e lines 50);
        o registro ganha uma linha por probe; o adaptador recebe a credencial declarada nele e não as declaradas
        em outro adaptador ou nos coletores; nenhum valor de credencial aparece em saída, registro ou atlas."""
        self.configure(probes_yaml([
            adapter_yaml("fake", self.fake("env_names.py", "--verbs", "runtime=status,logs"),
                         credentials=("PROBE_FAKE_TOKEN",)),
            adapter_yaml("other", self.fake("env_names.py", "--verbs", "other=status", adapter="other"),
                         verbs=("status",), credentials=("OTHER_ADAPTER_TOKEN",)),
        ]), credentials="{argocd: {env: [COLLECTOR_ARGO_TOKEN]}}")
        values = {"PROBE_FAKE_TOKEN": FAKE_VALUE + "-1", "OTHER_ADAPTER_TOKEN": FAKE_VALUE + "-2",
                  "COLLECTOR_ARGO_TOKEN": FAKE_VALUE + "-3"}
        before = snapshot(self.box.atlas)
        result = self.probe("runtime", "status", "--service", "api", "--env", "dev", "--json", env=values)
        data = self.json_out(result)
        self.assertLessEqual(set(data), OUTPUT_KEYS)
        self.assertLessEqual(OUTPUT_REQUIRED, set(data))
        self.assertEqual({k: data[k] for k in ("contract", "adapter", "capability", "verb", "status", "truncated")},
                         {"contract": "probe@1", "adapter": "fake", "capability": "runtime", "verb": "status",
                          "status": "ok", "truncated": False})
        names = [item["name"] for item in data["items"]]
        self.assertIn("PROBE_FAKE_TOKEN", names)
        self.assertNotIn("OTHER_ADAPTER_TOKEN", names)
        self.assertNotIn("COLLECTOR_ARGO_TOKEN", names)
        runs = self.calls("run")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["input"], {
            "contract": "probe@1", "capability": "runtime", "verb": "status",
            "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "clusters": ["cluster-dev"],
                       "context": CONTEXTS["cluster-dev"], "namespace": "api-dev", "workloads": ["Deployment/api"]},
            "limits": {"lines": 200, "since_seconds": 1800}})
        self.assertEqual(len(self.log()), 1)
        result2 = self.probe("runtime", "status", "--service", "api", "--env", "dev", "--since", "2h", "--lines", "50",
                             "--json", env=values)
        self.assertExit(result2, 0)
        self.assertEqual(self.calls("run")[-1]["input"]["limits"], {"lines": 50, "since_seconds": 7200})
        self.assertEqual(len(self.log()), 2)
        texts = [output(result), output(result2), (self.cfg / "probes.log").read_text(encoding="utf-8")]
        texts += [p.read_text(encoding="utf-8", errors="replace") for p in self.box.atlas.rglob("*") if p.is_file()]
        for text in texts:
            for value in values.values():
                self.assertNotIn(value, text)
        self.assertNotIn(CONTEXTS["cluster-dev"], output(result) + texts[2])
        self.assertEqual(snapshot(self.box.atlas), before)


# --------------------------------------------------------------------------- CT-01


VALID = {
    "describe": [{"contract": "probe@1", "adapter": "kubernetes", "capabilities": {"runtime": ["status", "events",
                                                                                               "logs"]}}],
    "input": [{"contract": "probe@1", "capability": "runtime", "verb": "logs",
               "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "clusters": ["cluster-dev"],
                          "context": "ctx-dev", "namespace": "api", "workloads": ["Deployment/api"]},
               "limits": {"lines": 200, "since_seconds": 1800}}],
    "output": [{"contract": "probe@1", "adapter": "kubernetes", "capability": "runtime", "verb": "logs",
                "status": "ok", "items": [{"ts": "2026-11-20T10:00:00Z", "line": "INFO up", "containers": ["api", "x"],
                                           "restarts": 0, "ready": True}],
                "truncated": False, "message": "texto curto"},
               {"contract": "probe@1", "adapter": "kubernetes", "capability": "runtime", "verb": "status",
                "status": "error", "items": [], "truncated": False, "message": "falhou"}],
}


def _without(data, key):
    data = copy.deepcopy(data)
    data.pop(key)
    return data


def _with(data, **changes):
    data = copy.deepcopy(data)
    data.update(changes)
    return data


INVALID = {
    "describe": [
        _without(VALID["describe"][0], "contract"),
        _with(VALID["describe"][0], contract="probe@3"),
        _with(VALID["describe"][0], capabilities="runtime"),
        _with(VALID["describe"][0], capabilities={"runtime": ["status", "get pods"]}),
    ],
    "input": [
        _without(VALID["input"][0], "target"),
        _with(VALID["input"][0], contract="probe@3"),
        _with(VALID["input"][0], limits={"lines": 5000, "since_seconds": 1800}),
    ],
    "output": [
        _with(VALID["output"][0], chave_extra_0088="x"),
        _with(VALID["output"][0], status="talvez"),
        _with(VALID["output"][0], contract="probe@9"),
        _with(VALID["output"][0], items={"name": "api"}),
        _with(VALID["output"][0], items=[{"name": "api", "spec": {"replicas": 1}}]),
        _with(VALID["output"][0], items=[{"name": "api", "list": [{"nested": 1}]}]),
        _without(VALID["output"][0], "items"),
    ],
}
DOC_BLOCK_RE = re.compile(r"```json probe@1 (describe|input|output) (valid|invalid)[ \t]*\n(.*?)```", re.DOTALL)


class ContractTest(unittest.TestCase):
    def validator(self, kind):
        return f(f"validate_probe_{kind}")

    def assertValid(self, kind, data):
        problems = self.validator(kind)(copy.deepcopy(data))
        self.assertEqual(list(problems), [], data)

    def assertInvalid(self, kind, data):
        problems = list(self.validator(kind)(copy.deepcopy(data)))
        self.assertTrue(problems, f"{kind} inválido aceito: {data}")
        self.assertTrue(all(isinstance(p, str) and p.strip() for p in problems), problems)

    def test_valid_examples_pass_and_each_invalid_one_is_refused_with_the_reason(self):
        """SPEC-0088:CT-01 — exemplos de --describe, entrada e saída de probe@1: os válidos passam (sem problemas) e
        cada inválido (sem contract, contract errado, tipos errados, verbo com espaço, chave fora do contrato, item com
        objeto, lines acima de 2000) é recusado com um motivo em texto; a chave fora do contrato aparece no motivo."""
        for kind in VALID:
            self.validator(kind)
        for kind, examples in VALID.items():
            for i, data in enumerate(examples):
                with self.subTest(kind=kind, valid=i):
                    self.assertValid(kind, data)
        for kind, examples in INVALID.items():
            for i, data in enumerate(examples):
                with self.subTest(kind=kind, invalid=i):
                    self.assertInvalid(kind, data)
        problems = self.validator("output")(copy.deepcopy(INVALID["output"][0]))
        self.assertIn("chave_extra_0088", " ".join(problems))

    def test_the_examples_of_references_probes_md_follow_the_validator(self):
        """SPEC-0088:CT-01 — references/probes.md traz exemplos em blocos ```json probe@1 <describe|input|output>
        <valid|invalid>, ao menos um válido e um inválido de cada; o validador aceita os válidos e recusa os
        inválidos."""
        self.assertTrue(PROBES_DOC.is_file(), f"{PROBES_DOC} não existe ({SPEC})")
        blocks = DOC_BLOCK_RE.findall(PROBES_DOC.read_text(encoding="utf-8"))
        found = {(kind, validity) for kind, validity, _ in blocks}
        for kind in ("describe", "input", "output"):
            for validity in ("valid", "invalid"):
                self.assertIn((kind, validity), found, f"probes.md sem exemplo {kind} {validity}")
        for kind, validity, body in blocks:
            with self.subTest(kind=kind, validity=validity, body=body[:60]):
                data = json.loads(body)
                if validity == "valid":
                    self.assertValid(kind, data)
                else:
                    self.assertInvalid(kind, data)


if __name__ == "__main__":
    unittest.main()
