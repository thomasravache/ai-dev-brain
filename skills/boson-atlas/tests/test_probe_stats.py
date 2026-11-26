"""Motivo no probes.log, `probes stats` e as sugestões do `doctor` (SPEC-0104: CH-01, UT-06, UT-07, UT-08 e CT-01;
ADR-0023, ADR-0025, ADR-0010).

Contrato (seção 6 da SPEC-0104) que estes testes fixam:

    probes.log: fora de "ok", "reason" (código fechado do núcleo) e, nas recusas por acesso, "access"
        refused -> no_adapter | verb_not_allowed | production_unconfirmed | no_access | not_test_tier | no_journeys
        invalid -> invalid_args | no_deployment | not_linked | invalid_target
        error   -> adapter_failed | timeout | contract
        access  -> cluster | cloud | database | urls (só com reason no_access)
    atlas.py probes stats [--since 30d] [--json] [--atlas X]: contract probe-stats@1, chaves fechadas; --since de 1h a
        365d (senão exit 2); só as linhas do atlas escolhido e da janela; malformada = skipped_lines; sem reason =
        "unknown"; sem probes.log = total 0, exit 0; sem configuração local = exit 3.
    doctor: "AVISO uso das probes — <sugestão>", até 5 e depois "… e mais N: rode atlas.py probes stats"; nunca muda
        o exit; doctor --json: {"item": "uso das probes", "status": "AVISO", "detail": <sugestão>}.
    validate_probe_stats(data) -> lista de problemas (vazia = válido), com os blocos ```json probe-stats@1
        valid|invalid de references/probes.md.

Leituras desta suíte (listadas no relatório do test-writer):
    - Mapa dos motivos (UT-06): "alvo inexistente" (nenhum deployment do serviço no ambiente) = no_deployment;
      recurso que existe e não é ligado ao deployment = not_linked; campo do atlas fora da regra (target_problem) =
      invalid_target; argumento fora da regra (--lines 0) = invalid_args; adaptador com exit 1 = adapter_failed;
      tempo esgotado = timeout; saída fora do contrato = contract.
    - by_status, no_access e cada item de by_capability trazem sempre as quatro chaves (com 0); refused e no_adapter
      só as contagens > 0 (como no exemplo do contrato).
    - A sugestão de no_access database cita o datastore como "orders-db" ou "datastore:orders-db" (as duas leituras
      passam); as de mesma contagem podem sair em qualquer ordem entre si.
    - O doctor usa as mesmas sugestões do `probes stats --since 30d` do atlas escolhido (linhas de outro atlas e fora da
      janela não contam).
    - A linha de resumo do doctor é "AVISO uso das probes — … e mais N: rode atlas.py probes stats".

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); sem kubectl, AWS CLI, psql nem
rede (os adaptadores são os scripts falsos de fixtures/fake-probes/); nomes genéricos (acme, globex, api, worker).
"""
import datetime
import hashlib
import json
import re
import shutil
import sys
import unittest

from helpers import SKILL, TESTS, Sandbox, doctor_lines, fn, output
from test_probe import adapter_yaml
from test_probe_resource import LOG_KEYS, ResourceCase

SPEC = "SPEC-0104"
SETUP_ATLAS = TESTS / "fixtures" / "access-setup" / "atlas"
STATS = TESTS / "fixtures" / "probe-stats"
LOG_TEMPLATE = STATS / "probes.log.template"
FAKES = TESTS / "fixtures" / "fake-probes"
PROBES_DOC = SKILL / "references" / "probes.md"

REASONS = {
    "refused": {"no_adapter", "verb_not_allowed", "production_unconfirmed", "no_access", "not_test_tier",
                "no_journeys"},
    "invalid": {"invalid_args", "no_deployment", "not_linked", "invalid_target"},
    "error": {"adapter_failed", "timeout", "contract"},
}
ACCESS_KINDS = {"cluster", "cloud", "database", "urls"}
STATS_KEYS = {"contract", "atlas", "since", "total", "by_status", "refused", "no_access", "no_adapter",
              "by_capability", "skipped_lines", "suggestions"}
STATUSES = ("ok", "error", "invalid", "refused")

SUGGEST_CLOUD = "3 probe(s) recusada(s) por falta de access.cloud em dev: rode atlas.py access setup"
SUGGEST_ADAPTER = "2 probe(s) sem adaptador para tracing: declare um em probes.adapters (references/probes.md)"
SUGGEST_ONES = [
    "1 probe(s) recusada(s) por falta de access.urls em dev: rode atlas.py access setup",
    "1 probe(s) recusada(s) por falta de access.clusters em dev: rode atlas.py access setup",
    "1 probe(s) com verbo não liberado em fake2: libere em probes.adapters.fake2.verbs se for de leitura",
    ("1 probe(s) funcional(is) sem jornadas curadas para api: declare journeys no arquivo de fatos do coletor generic "
     "(references/collectors/generic.md)"),
    ("1 probe(s) em recurso não ligado a api em dev: complete o mapa do atlas (coletor aws ou fatos do generic)"),
    "1 probe(s) sem deployment de worker em prod: mapeie o deployment no atlas",
]
SUGGEST_DATABASE = re.compile(r"^1 probe\(s\) recusada\(s\) por falta de access\.databases para "
                              r"(datastore:)?orders-db: rode atlas\.py access setup\Z")
EXPECTED_30D = {
    "contract": "probe-stats@1", "atlas": "acme", "since": "30d", "total": 21,
    "by_status": {"ok": 3, "error": 2, "invalid": 3, "refused": 13},
    "refused": {"no_access": 6, "no_adapter": 2, "verb_not_allowed": 1, "no_journeys": 1, "not_test_tier": 1,
                "production_unconfirmed": 1, "unknown": 1},
    "no_access": {"cluster": 1, "cloud": 3, "database": 1, "urls": 1},
    "no_adapter": {"tracing": 2},
    "by_capability": {
        "messaging": {"ok": 2, "error": 0, "invalid": 1, "refused": 5},
        "runtime": {"ok": 1, "error": 1, "invalid": 2, "refused": 2},
        "functional": {"ok": 0, "error": 0, "invalid": 0, "refused": 3},
        "database": {"ok": 0, "error": 1, "invalid": 0, "refused": 1},
        "tracing": {"ok": 0, "error": 0, "invalid": 0, "refused": 2},
    },
    "skipped_lines": 1,
}
DOCTOR_ITEM = "uso das probes"


def f(name):
    return fn(name, SPEC)


def render_log(template_text, now=None):
    """O probes.log de fixture com cada @AGO:<n>h@ / @AGO:<n>d@ trocado pelo instante <n> horas/dias antes de agora."""
    now = now or datetime.datetime.now(datetime.timezone.utc)

    def stamp(match):
        amount, unit = int(match.group(1)), match.group(2)
        delta = datetime.timedelta(hours=amount) if unit == "h" else datetime.timedelta(days=amount)
        return (now - delta).strftime("%Y-%m-%dT%H:%M:%SZ")

    return re.sub(r"@AGO:(\d+)([hd])@", stamp, template_text)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def usage_rows(text):
    return [detail for status, item, detail in doctor_lines(text) if item == DOCTOR_ITEM and status == "AVISO"]


class StatsCase(unittest.TestCase):
    """Um atlas temporário (cópia de fixtures/access-setup/atlas), a configuração local de um atlas só (acme) e o
    probes.log de fixture na pasta da configuração local."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        shutil.copytree(SETUP_ATLAS, self.box.atlas)
        self.box.write_local(f"atlas: {json.dumps(str(self.box.atlas))}\ncredentials: {{}}\n")
        self.log_path = self.box.config_home / "probes.log"

    def write_log(self, text=None):
        self.log_path.write_text(render_log(LOG_TEMPLATE.read_text(encoding="utf-8")) if text is None else text,
                                 encoding="utf-8")

    def run_atlas(self, *args):
        result = self.box.run(*args)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def stats(self, *extra, code=0):
        result = self.run_atlas("probes", "stats", "--json", *extra)
        self.assertEqual(result.returncode, code, output(result))
        return json.loads(result.stdout) if code == 0 else None

    def assertSuggestions(self, suggestions):
        """As 9 sugestões da fixture (30 dias, acme): a de 3, a de 2 e as de 1 em qualquer ordem entre si."""
        self.assertEqual(len(suggestions), 9, suggestions)
        self.assertEqual(suggestions[0], SUGGEST_CLOUD)
        self.assertEqual(suggestions[1], SUGGEST_ADAPTER)
        rest = suggestions[2:]
        database = [s for s in rest if SUGGEST_DATABASE.match(s)]
        self.assertEqual(len(database), 1, rest)
        self.assertEqual(sorted(s for s in rest if s not in database), sorted(SUGGEST_ONES))


# --------------------------------------------------------------------------- CH-01


class CharacterizationTest(ResourceCase):
    def test_ok_line_doctor_and_join_stay_as_today(self):
        """SPEC-0104:CH-01 — `probe` ok grava a linha com exatamente as chaves de hoje (mais resource com --resource);
        o doctor com um probes.log só de linhas ok é igual ao doctor sem probes.log; e init --join mantém o access da
        entrada."""
        # SPEC-0104:CH-01
        self.configure([self.adapter1(described="runtime=status,events,logs")],
                       access={"clusters": {"cluster-dev": {"context": "ctx-local-dev-0104"}}})
        before = self.box.run("doctor")
        self.assertNotIn("Traceback", output(before))
        result = self.probe("runtime", "status", "--json")
        self.assertExit(result, 0)
        lines = self.log()
        self.assertEqual(len(lines), 1, lines)
        self.assertEqual(set(lines[0]), LOG_KEYS, lines[0])
        self.assertEqual(lines[0]["status"], "ok")
        after = self.box.run("doctor")
        self.assertEqual(after.returncode, before.returncode, output(after))
        self.assertEqual(after.stdout, before.stdout)

        self.configure()  # probe@2 com todos os blocos de acesso
        if self.log_path().exists():
            self.log_path().unlink()
        result = self.probe("messaging", "queue", "--resource", "queue:orders", "--json")
        self.assertExit(result, 0)
        lines = self.log()
        self.assertEqual(set(lines[-1]), LOG_KEYS | {"resource"}, lines[-1])

        config = self.box.config_home / "config.yml"
        access_before = self.access_of(config)
        joined = self.box.run("init", "--join", "--atlas", self.box.atlas)
        self.assertEqual(joined.returncode, 0, output(joined))
        self.assertEqual(self.access_of(config), access_before)

    def log_path(self):
        return self.box.config_home / "probes.log"

    def access_of(self, config):
        data = fn("read_yaml")(config)
        entry = data if "atlas" in data else next(iter(data["atlases"].values()))
        return entry.get("access")


# --------------------------------------------------------------------------- UT-06


class ReasonTest(ResourceCase):
    """Cada recusa, inválido e erro do probe deixa o reason certo (e o access, nas recusas por acesso)."""

    def last_line(self):
        lines = self.log()
        self.assertTrue(lines, "nenhuma linha no probes.log")
        return lines[-1]

    def assertReason(self, result, code, status, reason, access=None):
        self.assertExit(result, code)
        line = self.last_line()
        self.assertEqual(line["status"], status, line)
        self.assertEqual(line.get("reason"), reason, line)
        self.assertIn(reason, REASONS[status])
        new = set(line) - LOG_KEYS - {"resource", "commit"}
        if access is None:
            self.assertEqual(new, {"reason"}, line)
        else:
            self.assertEqual(new, {"reason", "access"}, line)
            self.assertEqual(line["access"], access, line)

    def test_refusals_have_their_reason(self):
        """SPEC-0104:UT-06 — recusas (exit 4): sem adaptador, verbo, produção sem confirmação e sem acesso ao cluster,
        à nuvem, ao banco e à URL base, com reason e access."""
        # SPEC-0104:UT-06
        self.configure()
        self.assertReason(self.probe("tracing", "spans"), 4, "refused", "no_adapter")
        self.assertReason(self.probe("messaging", "queue", "--env", "prod", "--resource", "queue:orders"), 4,
                          "refused", "production_unconfirmed")
        self.configure([self.adapter2(verbs=("subscriptions",))])
        self.assertReason(self.probe("messaging", "queue", "--resource", "queue:orders"), 4, "refused",
                          "verb_not_allowed")
        self.configure([self.adapter1(described="runtime=status,events,logs")], access={})
        self.assertReason(self.probe("runtime", "status"), 4, "refused", "no_access", "cluster")
        self.configure(access=self.access(cloud=False))
        self.assertReason(self.probe("messaging", "queue", "--resource", "queue:orders"), 4, "refused", "no_access",
                          "cloud")
        self.configure(access=self.access(databases=False))
        self.assertReason(self.probe("database", "migrations", "--resource", "datastore:orders-db"), 4, "refused",
                          "no_access", "database")
        self.configure(access=self.access(urls=False))
        self.assertReason(self.probe("functional", "run"), 4, "refused", "no_access", "urls")

    def test_invalid_probes_have_their_reason(self):
        """SPEC-0104:UT-06 — inválidos (exit 2): argumento fora da regra, alvo inexistente (sem deployment), recurso
        não ligado e campo inválido do atlas."""
        # SPEC-0104:UT-06
        self.configure()
        self.assertReason(self.probe("messaging", "queue", "--resource", "queue:orders", "--lines", "0"), 2,
                          "invalid", "invalid_args")
        self.assertReason(self.probe("messaging", "queue", "--env", "qa"), 2, "invalid", "no_deployment")
        self.assertReason(self.probe("database", "migrations", "--resource", "datastore:billing-db"), 2, "invalid",
                          "not_linked")
        self.set_attrs("deployment:dev-api", namespace="Fora_Da_Regra")
        self.assertReason(self.probe("messaging", "queue", "--resource", "queue:orders"), 2, "invalid",
                          "invalid_target")

    def test_errors_have_their_reason(self):
        """SPEC-0104:UT-06 — erros (exit 1): adaptador com exit 1, tempo esgotado e saída fora do contrato."""
        # SPEC-0104:UT-06
        self.configure()
        self.write_scenario({"*": {"exit": 1, "stderr": "falha falsa"}})
        self.assertReason(self.probe("messaging", "queue", "--resource", "queue:orders"), 1, "error",
                          "adapter_failed")
        self.write_scenario({"*": {"items": [], "extra": {"zzextra": 1}}})
        self.assertReason(self.probe("messaging", "queue", "--resource", "queue:orders"), 1, "error", "contract")
        slow = adapter_yaml("slow", [sys.executable, str(FAKES / "slow.py"), "--record", str(self.record1),
                                     "--adapter", "slow"], timeout=1)
        self.configure([slow])
        self.assertReason(self.probe("runtime", "status"), 1, "error", "timeout")

    def test_ok_has_no_reason(self):
        """SPEC-0104:UT-06 — uma probe ok não traz reason nem access."""
        # SPEC-0104:UT-06
        self.configure()
        result = self.probe("messaging", "queue", "--resource", "queue:orders")
        self.assertExit(result, 0)
        line = self.last_line()
        self.assertEqual(line["status"], "ok")
        self.assertNotIn("reason", line)
        self.assertNotIn("access", line)

    def test_log_keys_constant_is_the_closed_set(self):
        """SPEC-0104:UT-06 — PROBE_LOG_KEYS é exatamente o conjunto do contrato: as de hoje, resource, commit, reason e
        access (a regra de arquitetura está em test_architecture.py)."""
        # SPEC-0104:UT-06
        keys = set(fn("PROBE_LOG_KEYS"))
        self.assertEqual(keys, LOG_KEYS | {"resource", "commit", "reason", "access"})


# --------------------------------------------------------------------------- UT-07


class StatsTest(StatsCase):
    def test_counts_filters_and_suggestions(self):
        """SPEC-0104:UT-07 — probes stats --json sobre a fixture: só acme e só a janela de 30 dias, a linha malformada
        em skipped_lines, a antiga sem reason em refused.unknown, e as sugestões do contrato, uma por grupo,
        ordenadas por contagem."""
        # SPEC-0104:UT-07
        self.write_log()
        data = self.stats()
        self.assertEqual(set(data), STATS_KEYS, data)
        for key, value in EXPECTED_30D.items():
            self.assertEqual(data[key], value, key)
        self.assertSuggestions(data["suggestions"])
        for suggestion in data["suggestions"]:
            self.assertNotIn("globex", suggestion)
        self.assertEqual(f("validate_probe_stats")(data), [])

    def test_since_window(self):
        """SPEC-0104:UT-07 — --since 1d (e 24h) só conta as linhas do último dia."""
        # SPEC-0104:UT-07
        self.write_log()
        for since in ("1d", "24h"):
            data = self.stats("--since", since)
            self.assertEqual(data["since"], since)
            self.assertEqual(data["total"], 4, data)
            self.assertEqual(data["by_status"], {"ok": 3, "error": 0, "invalid": 0, "refused": 1})
            self.assertEqual(data["suggestions"],
                             ["1 probe(s) recusada(s) por falta de access.cloud em dev: rode atlas.py access setup"])

    def test_invalid_since_exits_2(self):
        """SPEC-0104:UT-07 — --since 0d, 400d, 30x, 0h → exit 2."""
        # SPEC-0104:UT-07
        self.write_log()
        for since in ("0d", "400d", "30x", "0h"):
            result = self.run_atlas("probes", "stats", "--json", "--since", since)
            self.assertEqual(result.returncode, 2, f"{since}: {output(result)}")
            self.assertNotIn("invalid choice", output(result))

    def test_without_log_is_empty(self):
        """SPEC-0104:UT-07 — sem probes.log: total 0, sem sugestões, exit 0."""
        # SPEC-0104:UT-07
        data = self.stats()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["suggestions"], [])
        self.assertEqual(data["skipped_lines"], 0)
        self.assertEqual(data["by_status"], {"ok": 0, "error": 0, "invalid": 0, "refused": 0})
        self.assertEqual(data["no_access"], {"cluster": 0, "cloud": 0, "database": 0, "urls": 0})
        self.assertFalse(self.log_path.exists(), "probes stats não grava o probes.log")

    def test_without_local_config_exits_3(self):
        """SPEC-0104:UT-07 — sem configuração local, exit 3."""
        # SPEC-0104:UT-07
        (self.box.config_home / "config.yml").unlink()
        result = self.run_atlas("probes", "stats", "--json")
        self.assertEqual(result.returncode, 3, output(result))

    def test_markdown_has_counts_and_suggestions(self):
        """SPEC-0104:UT-07 — sem --json: Markdown com as contagens e as sugestões."""
        # SPEC-0104:UT-07
        self.write_log()
        result = self.run_atlas("probes", "stats")
        self.assertEqual(result.returncode, 0, output(result))
        self.assertIn("21", result.stdout)
        for suggestion in [SUGGEST_CLOUD, SUGGEST_ADAPTER] + SUGGEST_ONES:
            self.assertIn(suggestion, result.stdout)
        self.assertNotIn("globex", result.stdout)

    def test_other_atlas_option(self):
        """SPEC-0104:UT-07 — --atlas escolhe as linhas: com acme e globex configurados, --atlas globex conta só a linha
        de globex."""
        # SPEC-0104:UT-07
        other = self.box.root / "work" / "globex-atlas"
        shutil.copytree(SETUP_ATLAS, other)
        (other / "atlas-config.yml").write_text(
            (other / "atlas-config.yml").read_text(encoding="utf-8").replace("Acme", "Globex"), encoding="utf-8")
        self.box.write_local(f"default: acme\natlases:\n  acme:\n    atlas: {json.dumps(str(self.box.atlas))}\n"
                             f"    credentials: {{}}\n  globex:\n    atlas: {json.dumps(str(other))}\n"
                             "    credentials: {}\n")
        self.write_log()
        data = self.stats("--atlas", "globex")
        self.assertEqual(data["atlas"], "globex")
        self.assertEqual(data["total"], 1, data)
        self.assertEqual(data["no_access"]["cloud"], 1)
        self.assertEqual(self.stats()["total"], 21)


# --------------------------------------------------------------------------- UT-08


class DoctorTest(StatsCase):
    def test_doctor_shows_up_to_five_suggestions(self):
        """SPEC-0104:UT-08 — com a fixture: 5 linhas "AVISO uso das probes — <sugestão>" e a de resumo; exit igual ao
        de sem o log; config.yml e atlas com o mesmo hash; doctor --json com os mesmos checks."""
        # SPEC-0104:UT-08
        before = self.run_atlas("doctor")
        self.assertEqual(usage_rows(before.stdout), [])
        config = self.box.config_home / "config.yml"
        self.write_log()
        hashes = (file_hash(config), tree_hash(self.box.atlas), file_hash(self.log_path))
        result = self.run_atlas("doctor")
        self.assertEqual(result.returncode, before.returncode, output(result))
        rows = usage_rows(result.stdout)
        self.assertEqual(len(rows), 6, rows)
        self.assertEqual(rows[0], SUGGEST_CLOUD)
        self.assertEqual(rows[1], SUGGEST_ADAPTER)
        for row in rows[2:5]:
            self.assertTrue(row in SUGGEST_ONES or SUGGEST_DATABASE.match(row), row)
        self.assertEqual(rows[5], "… e mais 4: rode atlas.py probes stats")
        self.assertNotIn("globex", result.stdout)
        as_json = self.run_atlas("doctor", "--json")
        self.assertEqual(as_json.returncode, before.returncode, output(as_json))
        checks = [c for c in json.loads(as_json.stdout)["checks"] if c["item"] == DOCTOR_ITEM]
        self.assertTrue(all(c["status"] == "AVISO" for c in checks), checks)
        self.assertEqual([c["detail"] for c in checks], rows)
        self.assertEqual((file_hash(config), tree_hash(self.box.atlas), file_hash(self.log_path)), hashes)

    def test_doctor_without_suggestions_has_no_line(self):
        """SPEC-0104:UT-08 — sem probes.log, ou só com linhas ok, nenhuma linha nova e a saída igual."""
        # SPEC-0104:UT-08
        before = self.run_atlas("doctor")
        ok_only = "\n".join(line for line in render_log(LOG_TEMPLATE.read_text(encoding="utf-8")).splitlines()
                            if '"status": "ok"' in line) + "\n"
        self.write_log(ok_only)
        after = self.run_atlas("doctor")
        self.assertEqual(after.returncode, before.returncode)
        self.assertEqual(usage_rows(after.stdout), [])
        self.assertEqual(after.stdout, before.stdout)

    def test_doctor_ignores_lines_older_than_30_days(self):
        """SPEC-0104:UT-08 — só linhas de mais de 30 dias: nenhuma linha "uso das probes"."""
        # SPEC-0104:UT-08
        old = [line for line in LOG_TEMPLATE.read_text(encoding="utf-8").splitlines() if "@AGO:40d@" in line]
        self.assertEqual(len(old), 1)
        self.write_log(render_log(old[0] + "\n"))
        self.assertEqual(usage_rows(self.run_atlas("doctor").stdout), [])


# --------------------------------------------------------------------------- CT-01


STATS_BLOCK_RE = re.compile(r"```json probe-stats@1 (valid|invalid)\n(.*?)\n```", re.DOTALL)
JSON_BLOCK_RE = re.compile(r"```json[^\n]*\n(.*?)\n```", re.DOTALL)
VALID_STATS = {"contract": "probe-stats@1", "atlas": "acme", "since": "30d", "total": 12,
               "by_status": {"ok": 7, "error": 1, "invalid": 1, "refused": 3},
               "refused": {"no_access": 3},
               "no_access": {"cluster": 0, "cloud": 3, "database": 0, "urls": 0},
               "no_adapter": {},
               "by_capability": {"messaging": {"ok": 7, "error": 1, "invalid": 1, "refused": 3}},
               "skipped_lines": 0,
               "suggestions": ["3 probe(s) recusada(s) por falta de access.cloud em dev: rode atlas.py access setup"]}


class ContractTest(unittest.TestCase):
    def test_reference_blocks_and_validator(self):
        """SPEC-0104:CT-01 — os blocos ```json probe-stats@1 valid|invalid de references/probes.md: ao menos um válido
        e três inválidos; os válidos passam e os inválidos falham no validate_probe_stats."""
        # SPEC-0104:CT-01
        validate = f("validate_probe_stats")
        text = PROBES_DOC.read_text(encoding="utf-8")
        blocks = [(m.group(1), json.loads(m.group(2))) for m in STATS_BLOCK_RE.finditer(text)]
        self.assertGreaterEqual(len([b for b in blocks if b[0] == "valid"]), 1, "nenhum bloco probe-stats@1 valid")
        self.assertGreaterEqual(len([b for b in blocks if b[0] == "invalid"]), 3, "menos de 3 blocos invalid")
        for verdict, data in blocks:
            with self.subTest(verdict=verdict, data=json.dumps(data)[:80]):
                problems = validate(data)
                if verdict == "valid":
                    self.assertEqual(problems, [])
                else:
                    self.assertTrue(problems, "bloco inválido aceito")

    def test_validator_refuses_extra_key_contract_and_negative_count(self):
        """SPEC-0104:CT-01 — chave a mais, contract errado e contagem negativa são recusados; o exemplo do contrato
        passa."""
        # SPEC-0104:CT-01
        validate = f("validate_probe_stats")
        self.assertEqual(validate(VALID_STATS), [])
        bad = [dict(VALID_STATS, extra=1), dict(VALID_STATS, contract="probe-stats@2"),
               dict(VALID_STATS, total=-1),
               dict(VALID_STATS, no_access={"cluster": 0, "cloud": -3, "database": 0, "urls": 0}),
               {k: v for k, v in VALID_STATS.items() if k != "suggestions"}, "não é objeto"]
        for data in bad:
            with self.subTest(data=str(data)[:80]):
                self.assertTrue(validate(data), "aceito")

    def test_log_example_uses_only_contract_codes(self):
        """SPEC-0104:CT-01 — o exemplo de linha do probes.log com reason (e access) em references/probes.md usa só os
        códigos do contrato."""
        # SPEC-0104:CT-01
        text = PROBES_DOC.read_text(encoding="utf-8")
        examples = []
        for match in JSON_BLOCK_RE.finditer(text):
            for line in match.group(1).splitlines():
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if isinstance(data, dict) and "reason" in data and "capability" in data:
                    examples.append(data)
        self.assertTrue(examples, "nenhum exemplo de linha do probes.log com reason em probes.md")
        for data in examples:
            with self.subTest(data=json.dumps(data)[:80]):
                self.assertIn(data["status"], REASONS)
                self.assertIn(data["reason"], REASONS[data["status"]])
                if "access" in data:
                    self.assertEqual(data["reason"], "no_access")
                    self.assertIn(data["access"], ACCESS_KINDS)
                self.assertEqual(set(data) - LOG_KEYS - {"resource", "commit", "reason", "access"}, set())


if __name__ == "__main__":
    unittest.main()
