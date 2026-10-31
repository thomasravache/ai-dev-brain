"""scan, contrato dos coletores, redaction, normalização e diff do atlas.py (SPEC-0033: UT-01 a UT-07, IT-01 a
IT-05 e CT-01).

Contrato esperado das funções de scripts/atlas.py (o Implementer segue estes testes):

    validate_collectors(collectors: list) -> list
        Valida a chave `collectors` do atlas-config.yml (escalares podem chegar como texto do parse_yaml) e
        devolve a lista com os padrões aplicados: `timeout` int (padrão 300), `enabled` bool (padrão True).
        Inválido -> AtlasError(code=2): id fora de ^[a-z0-9-]+$ ou repetido, category fora do ADR-0011, command
        que não é lista não vazia; qualquer item de command com caminho absoluto (/x, ~, C:\\ ou C:/, \\\\srv) ->
        "command não pode ter caminho absoluto — use {skill} ou {atlas}".

    resolve_command(command: list, skill, atlas) -> list[str]
        Troca os marcadores {skill} (pasta da skill) e {atlas} (pasta do atlas) em cada argumento.

    validate_collector_output(data: dict) -> (clean: dict, violations: list[str], dropped: list[str])
        Confere a saída de um coletor contra org-atlas/collector@1 (ADR-0011). `violations` vazia = válida; cada
        violação é um texto. Mensagens (CT-01 e references/collector-contract.md; o texto contém exatamente):
            contract não suportado: <valor>
            faltam campos: <campo>[, <campo>...]
            category desconhecida: <valor>
            entities[<i>]: kind desconhecido: <valor>
            entities[<i>]: chave repetida: <kind:id>
            entities[<i>]: attrs.<chave> não é escalar
            relations[<i>]: type desconhecido: <valor>
            relations[<i>]: from fora do formato kind:id: <valor>
            relations[<i>]: to fora do formato kind:id: <valor>
        Chave de attrs proibida (password, passwd, pwd, secret, token, key, credential, private; vale também para
        as chaves de um sinal) não é violação: sai de `clean` e entra em `dropped` como texto com a chave da
        entidade e o nome da chave (nunca o valor). Campo fora do contrato (na saída, na entidade, na relação
        ou no sinal) recebe o mesmo tratamento: descartado e reportado (decisão do Architect, revisão G4).
        Tipo errado num campo do contrato é violação (decisão do Architect, revisão G4 2), sem repetir o valor:
        name, id e source da entidade e source da relação são texto; inferred é bool; signals[].sample é lista
        de textos; total é número; pattern_counts é objeto plano de números; counts e present são objetos
        planos de escalares.

    redact(value, extra_patterns=()) -> (redacted, count: int)
        Percorre str, dict (valores e chaves) e list; demais escalares ficam como estão. Cada trecho que casa com
        um padrão de segredo (ghp_, gho_, github_pat_, xoxb-, AKIA, bloco PRIVATE KEY e PGP PRIVATE KEY BLOCK,
        JWT, credencial em URL, inclusive usuário vazio e senha com / ou @) ou com um extra_pattern vira
        "[REDACTED]"; `count` é o número de ocorrências. O resto do texto fica. extra_pattern inválido ou que
        casa com o texto vazio -> AtlasError(code=2) com a posição (extra_patterns[i]), nunca o texto.
        Padrão extra de largura zero (\\b, (?=a)) nunca insere [REDACTED]: é rejeitado (code 2, só a posição) ou
        ignorado. Sem falso positivo dentro de palavras (laughs_..., ASIAPACIFICNORTHEAST1); token colado a
        pontuação (_ghp_, =ghp_, token:ghp_) continua mascarado.

    normalize(data: dict) -> str
        Texto JSON do snapshot (o que vai para snapshots/<id>.json): entidades ordenadas por kind:id, relações
        em ordem determinística, chaves ordenadas e indentação fixa. Mesmo estado = mesmo texto.

    diff_snapshots(old: dict | None, new: dict) -> dict
        {"entities": {"added": [kind:id], "removed": [kind:id], "changed": [kind:id]},
         "relations": {"added": [str], "removed": [str]}}; cada relação é um texto com from, type e to.
        old None = primeiro scan (tudo adicionado).

CLI (seção 6; mensagens podem ir para stdout ou stderr):
    scan [--only id,...] [--json]
    "OK <id> — +A entidades, -R, ~C; +a relações, -r" | "OK <id> — sem mudanças" | "N valor(es) mascarado(s)"
    "FALHA <id> — <motivo>", com as últimas 20 linhas do stderr mascaradas como um todo (bloco PEM em várias
    linhas, token no limite do corte da linha); exit 0 sem falha, 1 com falha, 2 com configuração inválida ou --only desconhecido.
    snapshots/<id>.json e snapshots/_scan.json {"<id>": {"seen_at", "status", "entities", "relations"}};
    sem coletor habilitado não grava nada (nem a pasta snapshots/).

Valores de segredo dos testes são montados em tempo de execução (nunca literais no arquivo).
"""
import copy
import datetime
import json
import re
import shutil
import time
import unittest
from pathlib import Path

from helpers import SKILL, TESTS, Sandbox, fn, output, snapshot

SPEC = "SPEC-0033"
CONTRACT = "org-atlas/collector@1"
FIXTURES = TESTS / "fixtures"
CONTRACT_FIXTURES = FIXTURES / "contract"
FAKES = "{skill}/tests/fixtures/fake-collectors"
REFERENCE = SKILL / "references" / "collector-contract.md"
ABSOLUTE_MESSAGE = "command não pode ter caminho absoluto — use {skill} ou {atlas}"
REDACTED = "[REDACTED]"

# mesmos valores que os coletores falsos montam
FAKE_TOKEN = "ghp_" + "Zx9" * 12
FAKE_PASSWORD = "s3nh4" + "-fake-" + "0033"


def f(name):
    return fn(name, SPEC)


def error_class():
    return fn("AtlasError", "SPEC-0032")


def load_fixture(rel):
    return json.loads((CONTRACT_FIXTURES / rel).read_text(encoding="utf-8"))


def base_output():
    return load_fixture("valid/code-github.json")


def today_values():
    return {datetime.date.today().isoformat(), datetime.datetime.now(datetime.timezone.utc).date().isoformat()}


def entity_key(entity):
    return f"{entity['kind']}:{entity['id']}"


def collectors_yaml(collectors):
    """collectors: [(id, script, args, timeout)] -> bloco YAML da chave collectors."""
    lines = ["collectors:"]
    for cid, script, args, timeout, *rest in collectors:
        command = ["python3", f"{FAKES}/{script}", *args]
        lines.append(f"  - id: {cid}")
        lines.append("    category: code")
        lines.append("    command: [" + ", ".join(json.dumps(a) for a in command) + "]")
        lines.append(f"    timeout: {timeout}")
        if rest:
            lines.append(f"    enabled: {rest[0]}")
    return "\n".join(lines)


def atlas_config_text(collectors_block, extra_patterns="[]"):
    return ("version: 1\n"
            "organization: Acme\n"
            "mode: local\n"
            "language: auto\n"
            "stale_days: 14\n"
            "categories: [code, delivery]\n"
            f"{collectors_block}\n"
            f"redaction: {{extra_patterns: {extra_patterns}}}\n")


class ScanCase(unittest.TestCase):
    """Atlas novo (init --mode local) num Sandbox, com os coletores falsos declarados."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        out = self.sandbox.init(mode="local")
        self.assertEqual(out.returncode, 0, output(out))
        self.atlas = self.sandbox.atlas
        self.snapshots = self.atlas / "snapshots"

    def configure(self, collectors, extra_patterns="[]"):
        text = atlas_config_text(collectors_yaml(collectors), extra_patterns)
        (self.atlas / "atlas-config.yml").write_text(text, encoding="utf-8")

    def configure_raw(self, block):
        (self.atlas / "atlas-config.yml").write_text(atlas_config_text(block), encoding="utf-8")

    def scan(self, *args):
        result = self.sandbox.run("scan", *args)
        self.assertNotIn("Traceback", output(result), output(result))
        return result

    def scan_state(self):
        path = self.snapshots / "_scan.json"
        self.assertTrue(path.is_file(), "snapshots/_scan.json não foi gravado")
        return json.loads(path.read_text(encoding="utf-8"))

    def snapshot_of(self, cid):
        path = self.snapshots / f"{cid}.json"
        self.assertTrue(path.is_file(), f"snapshots/{cid}.json não foi gravado")
        return path.read_text(encoding="utf-8")

    def assert_line(self, result, pattern):
        self.assertRegex(output(result), re.compile(pattern, re.MULTILINE))


# --------------------------------------------------------------------------- unitários


class ValidateCollectorOutputTest(unittest.TestCase):
    def test_valid_output_has_no_violation(self):
        """SPEC-0033:UT-01"""
        data = base_output()
        clean, violations, dropped = f("validate_collector_output")(copy.deepcopy(data))
        self.assertEqual(violations, [])
        self.assertEqual(dropped, [])
        self.assertEqual(clean, data)

    def test_valid_output_without_signals_is_accepted(self):
        """SPEC-0033:UT-01"""
        data = base_output()
        data.pop("signals")
        _, violations, _ = f("validate_collector_output")(data)
        self.assertEqual(violations, [])

    def test_each_violation_is_reported_with_the_right_reason(self):
        """SPEC-0033:UT-02"""
        cases = {
            "contrato @9": (lambda d: d.update(contract="org-atlas/collector@9"),
                            "contract não suportado: org-atlas/collector@9"),
            "kind desconhecido": (lambda d: d["entities"].append(
                {"kind": "widget", "id": "acme/w", "name": "w", "attrs": {}, "source": "github"}),
                                  "entities[3]: kind desconhecido: widget"),
            "type desconhecido": (lambda d: d["relations"][1].update(type="calls"),
                                  "relations[1]: type desconhecido: calls"),
            "chave repetida": (lambda d: d["entities"].append(dict(d["entities"][0], name="copia")),
                               "entities[3]: chave repetida: repository:acme/api"),
            "from sem kind:": (lambda d: d["relations"][0].update({"from": "acme/api/ci"}),
                               "relations[0]: from fora do formato kind:id: acme/api/ci"),
            "attrs não escalar": (lambda d: d["entities"][0]["attrs"].update(owner={"login": "ana"}),
                                  "entities[0]: attrs.owner não é escalar"),
        }
        validate = f("validate_collector_output")
        for name, (mutate, expected) in cases.items():
            with self.subTest(name):
                data = base_output()
                mutate(data)
                _, violations, _ = validate(data)
                self.assertEqual(len(violations), 1, violations)
                self.assertIn(expected, violations[0])

    def test_list_of_scalars_in_attrs_is_not_a_violation(self):
        """SPEC-0033:UT-02"""
        data = base_output()
        data["entities"][0]["attrs"]["topics"] = ["payments", "go", 3, True]
        _, violations, _ = f("validate_collector_output")(data)
        self.assertEqual(violations, [])
        data["entities"][0]["attrs"]["topics"] = ["payments", {"name": "go"}]
        _, violations, _ = f("validate_collector_output")(data)
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("entities[0]: attrs.topics não é escalar", violations[0])

    def test_wrong_types_in_contract_fields_are_violations(self):
        """SPEC-0033:UT-02"""
        value = "hunter" + "2"
        nested = {"password": value}
        cases = {
            "entity name objeto": lambda d: d["entities"][0].update(name=dict(nested)),
            "entity id objeto": lambda d: d["entities"][0].update(id=dict(nested)),
            "entity source objeto": lambda d: d["entities"][0].update(source=dict(nested)),
            "relation source objeto": lambda d: d["relations"][0].update(source=dict(nested)),
            "relation inferred não booleano": lambda d: d["relations"][0].update(inferred=value),
            "sample com item não texto": lambda d: d["signals"][0].update(sample=[dict(nested)]),
            "total não numérico": lambda d: d["signals"][0].update(total=value),
            "pattern_counts aninhado": lambda d: d["signals"][0].update(pattern_counts={"db": dict(nested)}),
            "counts aninhado": lambda d: d["signals"][0].update(counts={"db": dict(nested)}),
            "present aninhado": lambda d: d["signals"][0].update(present={"db": dict(nested)}),
            "pattern_counts com valor não numérico": lambda d: d["signals"][0].update(pattern_counts={"x": value}),
        }
        validate = f("validate_collector_output")
        for name, mutate in cases.items():
            with self.subTest(name):
                data = base_output()
                mutate(data)
                _, violations, dropped = validate(data)
                self.assertGreaterEqual(len(violations), 1, f"tipo errado precisa ser violação: {violations}")
                self.assertNotIn(value, json.dumps([violations, dropped], ensure_ascii=False),
                                 "o valor não aparece no relatório")

    def test_right_types_in_optional_fields_are_valid(self):
        """SPEC-0033:UT-02"""
        data = base_output()
        data["relations"][0]["inferred"] = True
        data["signals"][0]["counts"] = {"dockerfile": 3, "helm": 0}
        data["signals"][0]["present"] = {"dockerfile": True, "codeowners": False}
        _, violations, dropped = f("validate_collector_output")(data)
        self.assertEqual(violations, [])
        self.assertEqual(dropped, [])

    def test_forbidden_attr_key_is_dropped_and_reported(self):
        """SPEC-0033:UT-03"""
        secret = "pw-" + "fake-0033"
        data = base_output()
        data["entities"][0]["attrs"]["password"] = secret
        data["entities"][1]["attrs"]["token"] = "tk-" + "fake-0033"
        clean, violations, dropped = f("validate_collector_output")(data)
        self.assertEqual(violations, [], "chave proibida não falha o coletor")
        attrs = {entity_key(e): e["attrs"] for e in clean["entities"]}
        self.assertNotIn("password", attrs["repository:acme/api"])
        self.assertNotIn("token", attrs["pipeline:acme/api/ci"])
        self.assertEqual(attrs["repository:acme/api"]["default_branch"], "main", "as outras chaves ficam")
        self.assertEqual(len(dropped), 2, dropped)
        self.assertTrue(any("repository:acme/api" in d and "password" in d for d in dropped), dropped)
        self.assertTrue(any("pipeline:acme/api/ci" in d and "token" in d for d in dropped), dropped)
        self.assertNotIn(secret, json.dumps([clean, dropped]), "o valor da chave proibida não aparece")


    def test_forbidden_key_rule_covers_passwd_and_pwd(self):
        """SPEC-0033:UT-03"""
        data = base_output()
        data["entities"][0]["attrs"]["passwd"] = "pw-" + "fake-0033a"
        data["entities"][0]["attrs"]["pwd"] = "pw-" + "fake-0033b"
        clean, violations, dropped = f("validate_collector_output")(data)
        self.assertEqual(violations, [])
        attrs = clean["entities"][0]["attrs"]
        self.assertNotIn("passwd", attrs)
        self.assertNotIn("pwd", attrs)
        self.assertTrue(any("passwd" in d for d in dropped), dropped)
        self.assertTrue(any("pwd" in d and "passwd" not in d for d in dropped), dropped)
        self.assertNotIn("fake-0033", json.dumps([clean, dropped]))

    def test_fields_outside_the_contract_are_dropped_and_reported(self):
        """SPEC-0033:UT-03"""
        secret = "pw-" + "fake-0033-field"
        data = base_output()
        data["debug"] = {"password": secret}  # campo fora do contrato no topo da saída
        data["entities"][0]["password"] = secret  # campo fora do contrato direto na entidade
        data["relations"][0]["note"] = secret  # campo fora do contrato na relação
        data["signals"][0]["password"] = secret  # chave proibida num sinal
        clean, violations, dropped = f("validate_collector_output")(data)
        self.assertEqual(violations, [], "campo fora do contrato é descartado, não é violação")
        self.assertNotIn("debug", clean)
        self.assertNotIn("password", clean["entities"][0])
        self.assertNotIn("note", clean["relations"][0])
        self.assertNotIn("password", clean["signals"][0])
        self.assertEqual(clean["entities"][0]["attrs"]["default_branch"], "main", "o resto da entidade fica")
        self.assertEqual(clean["signals"][0]["total"], 200, "o resto do sinal fica")
        for name in ("debug", "password", "note"):
            self.assertTrue(any(name in d for d in dropped), f"{name} não foi reportado: {dropped}")
        self.assertGreaterEqual(len(dropped), 4, dropped)
        self.assertNotIn(secret, json.dumps(dropped), "o relatório não mostra o valor")
        self.assertNotIn(secret, f("normalize")(clean), "o valor não chega ao snapshot")


class RedactTest(unittest.TestCase):
    EXTRA = (r"acme-internal-[0-9]{4}",)

    def secrets(self):
        return {
            "ghp_": "ghp_" + "Zx9" * 12,
            "gho_": "gho_" + "Ab1" * 12,
            "github_pat_": "github_pat_" + "A1" * 11 + "_" + "b2c" * 19 + "d2",
            "xoxb-": "xoxb-" + "1234567890" + "-" + "1234567890123" + "-" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8",
            "AKIA": "AKIA" + "IOSFODNN7" + "EXAMPLE",
            "private key": ("-----BEGIN " + "RSA PRIVATE KEY-----\n" + "MIIEow" + "IBAAKCAQEAfake0033\n"
                            "c2Vjb25kbGluZWZha2U=\n" + "-----END RSA PRIVATE KEY-----"),
            "JWT": "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJ" + "zdWIiOiIxMjMifQ" + "." + "SflKxwRJSMeKKF2QT4fwpM",
            "extra_pattern": "acme-internal-" + "4821",
        }

    def test_each_secret_pattern_becomes_redacted_and_is_counted(self):
        """SPEC-0033:UT-04"""
        redact = f("redact")
        for name, secret in self.secrets().items():
            with self.subTest(name):
                text = f"antes {secret} depois"
                result, count = redact(text, self.EXTRA)
                self.assertEqual(count, 1, result)
                self.assertIn(REDACTED, result)
                self.assertNotIn(secret, result)
                self.assertTrue(result.startswith("antes "), result)
                self.assertTrue(result.endswith(" depois"), result)
        with self.subTest("corpo da chave privada"):
            result, _ = redact(self.secrets()["private key"])
            self.assertNotIn("MIIEow", result)
            self.assertNotIn("c2Vjb25kbGluZWZha2U=", result)

    def test_url_credential_becomes_redacted(self):
        """SPEC-0033:UT-04"""
        url = "https://bot:" + FAKE_PASSWORD + "@git.acme.example/acme/api.git"
        result, count = f("redact")(f"clone {url} agora")
        self.assertEqual(count, 1, result)
        self.assertIn(REDACTED, result)
        self.assertNotIn(FAKE_PASSWORD, result)
        self.assertTrue(result.startswith("clone "), result)
        self.assertTrue(result.endswith(" agora"), result)

    def test_extra_pattern_only_applies_when_configured(self):
        """SPEC-0033:UT-04"""
        value = "build " + "acme-internal-" + "4821"
        self.assertEqual(f("redact")(value), (value, 0))
        result, count = f("redact")(value, self.EXTRA)
        self.assertEqual((result, count), ("build " + REDACTED, 1))

    def test_count_matches_every_occurrence_in_nested_values(self):
        """SPEC-0033:UT-04"""
        tokens = self.secrets()
        data = {
            "entities": [{"kind": "repository", "id": "acme/api", "name": "api",
                          "attrs": {"description": f"{tokens['ghp_']} e {tokens['AKIA']}",
                                    "clone_url": "https://bot:" + FAKE_PASSWORD + "@git.acme.example/a.git",
                                    "stars": 7, "archived": False, "topics": ["go", tokens["JWT"]]}}],
            "relations": [],
        }
        result, count = f("redact")(data)
        self.assertEqual(count, 4)
        text = json.dumps(result)
        for secret in (tokens["ghp_"], tokens["AKIA"], tokens["JWT"], FAKE_PASSWORD):
            self.assertNotIn(secret, text)
        attrs = result["entities"][0]["attrs"]
        self.assertEqual(attrs["stars"], 7)
        self.assertIs(attrs["archived"], False)
        self.assertEqual(attrs["topics"][0], "go")
        self.assertEqual(sorted(attrs), sorted(data["entities"][0]["attrs"]), "chaves não são mascaradas")

    def test_ordinary_values_are_untouched(self):
        """SPEC-0033:UT-04"""
        data = base_output()
        result, count = f("redact")(copy.deepcopy(data))
        self.assertEqual(count, 0)
        self.assertEqual(result, data)


    def test_url_credential_variants_leave_no_part_of_the_password(self):
        """SPEC-0033:UT-04"""
        cases = {
            "usuário vazio": ("redis://:" + "r3dis-" + "pw0033" + "@cache:6379", ("pw0033",)),
            "barra na senha": ("https://user:" + "p4ss" + "/" + "w0rd0033" + "@host.example/x",
                               ("p4ss", "w0rd0033")),
            "@ na senha": ("https://user:" + "p" + "@" + "ss0033" + "@host.example/x", ("ss0033", "p@ss")),
        }
        for name, (url, parts) in cases.items():
            with self.subTest(name):
                result, count = f("redact")(f"conecta {url} agora")
                self.assertGreaterEqual(count, 1, result)
                self.assertIn(REDACTED, result)
                for part in parts:
                    self.assertNotIn(part, result)
                self.assertTrue(result.startswith("conecta "), result)
                self.assertTrue(result.endswith(" agora"), result)

    def test_pgp_private_key_block_is_redacted(self):
        """SPEC-0033:UT-04"""
        block = ("-----BEGIN " + "PGP PRIVATE KEY BLOCK-----\n\n" + "lQOYBF" + "pgpbody0033fake\n" + "=AbCd\n"
                 + "-----END " + "PGP PRIVATE KEY BLOCK-----")
        result, count = f("redact")(f"antes {block} depois")
        self.assertEqual(count, 1, result)
        self.assertIn(REDACTED, result)
        self.assertNotIn("pgpbody0033fake", result)
        self.assertNotIn("PGP PRIVATE KEY BLOCK", result)

    def test_secret_used_as_a_key_is_redacted(self):
        """SPEC-0033:UT-04"""
        token = self.secrets()["ghp_"]
        data = {"entities": [{"kind": "repository", "id": "acme/api", "name": "api",
                              "attrs": {token: "valor", "default_branch": "main"}, "source": "github"}],
                "relations": [],
                "signals": [{"type": "pr-titles", "repository": "acme/api", "total": 3,
                             "pattern_counts": {token: 3, "conventional": 1}, "sample": []}]}
        result, count = f("redact")(data)
        self.assertEqual(count, 2)
        self.assertNotIn(token, json.dumps(result))
        self.assertNotIn(token, f("normalize")(result))
        self.assertEqual(result["entities"][0]["attrs"]["default_branch"], "main")
        self.assertEqual(result["signals"][0]["pattern_counts"]["conventional"], 1)

    def test_zero_width_extra_pattern_never_inserts_redacted(self):
        """SPEC-0033:UT-04"""
        text = "abacate acme api"
        for pattern in (r"\b", r"(?=a)"):
            with self.subTest(pattern):
                try:
                    result, count = f("redact")(text, [pattern])
                except error_class() as e:  # rejeitar na configuração também cumpre o contrato
                    self.assertEqual(e.code, 2)
                    self.assertIn("extra_patterns[0]", str(e))
                    self.assertNotIn(pattern, str(e), "a mensagem só aponta a posição")
                    continue
                self.assertEqual((result, count), (text, 0), "casamento de largura zero não mascara nada")

    def test_ordinary_words_that_resemble_tokens_are_untouched(self):
        """SPEC-0033:UT-04"""
        for text in ("laughs_abcdefghijklmnopqrstuvwxyz", "ASIAPACIFICNORTHEAST1"):
            with self.subTest(text):
                self.assertEqual(f("redact")(text), (text, 0))

    def test_tokens_glued_to_punctuation_are_still_redacted(self):
        """SPEC-0033:UT-04"""
        token = self.secrets()["ghp_"]
        for prefix in ("_", "=", "token:"):
            with self.subTest(prefix):
                result, count = f("redact")(prefix + token)
                self.assertEqual(count, 1, result)
                self.assertNotIn(token, result)
                self.assertEqual(result, prefix + REDACTED)

    def test_extra_pattern_matching_the_empty_string_is_rejected(self):
        """SPEC-0033:UT-04"""
        with self.assertRaises(error_class()) as ctx:
            f("redact")("texto", ["acme-[0-9]+", "z*"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("extra_patterns[1]", str(ctx.exception))
        self.assertNotIn("z*", str(ctx.exception), "a mensagem só aponta a posição")


class NormalizeTest(unittest.TestCase):
    def shuffled(self, data):
        other = copy.deepcopy(data)
        other["entities"].reverse()
        other["relations"].reverse()
        for entity in other["entities"]:
            entity["attrs"] = dict(reversed(list(entity["attrs"].items())))
        return dict(reversed(list(other.items())))

    def test_same_output_in_any_order_gives_identical_json(self):
        """SPEC-0033:UT-05"""
        normalize = f("normalize")
        data = base_output()
        text = normalize(copy.deepcopy(data))
        self.assertIsInstance(text, str)
        self.assertEqual(normalize(self.shuffled(data)), text)
        self.assertEqual(normalize(json.loads(text)), text, "normalizar o snapshot gravado não muda nada")

    def test_entities_are_sorted_by_key_and_content_is_kept(self):
        """SPEC-0033:UT-05"""
        data = base_output()
        parsed = json.loads(f("normalize")(self.shuffled(data)))
        keys = [entity_key(e) for e in parsed["entities"]]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(sorted(keys), sorted(entity_key(e) for e in data["entities"]))
        def relations(snapshot):
            return sorted((r["from"], r["type"], r["to"]) for r in snapshot["relations"])

        self.assertEqual(relations(parsed), relations(data))
        by_key = {entity_key(e): e for e in parsed["entities"]}
        self.assertEqual(by_key["repository:acme/api"]["attrs"], data["entities"][0]["attrs"])


class DiffSnapshotsTest(unittest.TestCase):
    def snapshots(self):
        old = base_output()
        new = copy.deepcopy(old)
        new["entities"] = [e for e in new["entities"] if entity_key(e) != "team:acme/payments"]  # removida
        new["entities"][0]["attrs"]["default_branch"] = "trunk"  # alterada: repository:acme/api
        new["entities"].append({"kind": "repository", "id": "acme/web", "name": "web", "attrs": {},
                                "source": "github"})  # nova
        new["relations"] = [r for r in new["relations"] if r["type"] != "owns"]  # removida
        new["relations"].append({"from": "pipeline:acme/api/ci", "to": "repository:acme/web", "type": "builds",
                                 "source": "github"})  # nova
        return old, new

    def test_lists_added_removed_and_changed(self):
        """SPEC-0033:UT-06"""
        old, new = self.snapshots()
        diff = f("diff_snapshots")(old, new)
        self.assertEqual(sorted(diff["entities"]["added"]), ["repository:acme/web"])
        self.assertEqual(sorted(diff["entities"]["removed"]), ["team:acme/payments"])
        self.assertEqual(sorted(diff["entities"]["changed"]), ["repository:acme/api"])
        added, removed = diff["relations"]["added"], diff["relations"]["removed"]
        self.assertEqual(len(added), 1, added)
        self.assertEqual(len(removed), 1, removed)
        for part in ("pipeline:acme/api/ci", "builds", "repository:acme/web"):
            self.assertIn(part, added[0])
        for part in ("team:acme/payments", "owns", "repository:acme/api"):
            self.assertIn(part, removed[0])

    def test_same_state_has_no_difference(self):
        """SPEC-0033:UT-06"""
        old = base_output()
        diff = f("diff_snapshots")(old, copy.deepcopy(old))
        self.assertEqual(diff, {"entities": {"added": [], "removed": [], "changed": []},
                                "relations": {"added": [], "removed": []}})

    def test_first_scan_adds_everything(self):
        """SPEC-0033:UT-06"""
        new = base_output()
        diff = f("diff_snapshots")(None, new)
        self.assertEqual(sorted(diff["entities"]["added"]), sorted(entity_key(e) for e in new["entities"]))
        self.assertEqual(len(diff["relations"]["added"]), len(new["relations"]))
        self.assertEqual(diff["entities"]["removed"] + diff["entities"]["changed"] + diff["relations"]["removed"],
                         [])


class CollectorsConfigTest(unittest.TestCase):
    def collector(self, command, **extra):
        return dict({"id": "github", "category": "code", "command": command}, **extra)

    def test_absolute_path_in_command_is_rejected(self):
        """SPEC-0033:UT-07"""
        validate = f("validate_collectors")
        commands = {
            "executável absoluto": ["/usr/bin/python3", "{skill}/assets/collectors/github.py"],
            "script absoluto": ["python3", "/opt/collectors/github.py"],
            "home": ["python3", "~/collectors/github.py"],
            "windows": ["python3", "C:\\collectors\\github.py"],
            "opção curta colada": ["python3", "{skill}/assets/collectors/github.py", "-o/etc/x"],
        }
        for name, command in commands.items():
            with self.subTest(name):
                with self.assertRaises(error_class()) as ctx:
                    validate([self.collector(command)])
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn(ABSOLUTE_MESSAGE, str(ctx.exception))

    def test_valid_collectors_get_defaults(self):
        """SPEC-0033:UT-07"""
        result = f("validate_collectors")([
            self.collector(["python3", "{skill}/assets/collectors/github.py", "--org", "acme"]),
            {"id": "argo-cd", "category": "delivery", "command": ["argocd-collector", "{atlas}/snapshots"],
             "timeout": "2", "enabled": "false"},
        ])
        self.assertEqual([c["id"] for c in result], ["github", "argo-cd"])
        self.assertEqual(result[0]["timeout"], 300)
        self.assertIs(result[0]["enabled"], True)
        self.assertEqual(result[1]["timeout"], 2)
        self.assertIs(result[1]["enabled"], False)

    def test_invalid_collector_declarations_are_rejected(self):
        """SPEC-0033:UT-07"""
        validate = f("validate_collectors")
        ok = ["python3", "{skill}/assets/collectors/github.py"]
        cases = {
            "id fora do formato": [dict(self.collector(ok), id="GitHub_1")],
            "id repetido": [self.collector(ok), self.collector(ok)],
            "category desconhecida": [dict(self.collector(ok), category="billing")],
            "command sem lista": [self.collector("python3 github.py")],
            "command vazio": [self.collector([])],
        }
        for name, collectors in cases.items():
            with self.subTest(name):
                with self.assertRaises(error_class()) as ctx:
                    validate(collectors)
                self.assertEqual(ctx.exception.code, 2)

    def test_skill_and_atlas_markers_are_resolved(self):
        """SPEC-0033:UT-07"""
        skill, atlas = Path("/srv/org-atlas"), Path("/srv/acme-atlas")
        resolved = f("resolve_command")(
            ["python3", "{skill}/assets/collectors/github.py", "--out", "{atlas}/snapshots", "--org", "acme"],
            skill, atlas)
        self.assertEqual(resolved, ["python3", "/srv/org-atlas/assets/collectors/github.py", "--out",
                                    "/srv/acme-atlas/snapshots", "--org", "acme"])


class ScanAbsoluteCommandTest(ScanCase):
    def test_scan_with_absolute_command_exits_2(self):
        """SPEC-0033:UT-07"""
        self.configure_raw("collectors:\n"
                           "  - id: github\n"
                           "    category: code\n"
                           "    command: [python3, /opt/collectors/github.py]\n")
        result = self.scan()
        self.assertEqual(result.returncode, 2, output(result))
        self.assertIn(ABSOLUTE_MESSAGE, output(result))
        self.assertFalse((self.snapshots / "github.json").exists())


# --------------------------------------------------------------------------- integração


class FirstScanTest(ScanCase):
    def test_first_scan_writes_snapshot_and_scan_state(self):
        """SPEC-0033:IT-01"""
        self.configure([("fake-ok", "static.py", ["fake-ok"], 10),
                        ("fake-off", "static.py", ["fake-off"], 10, "false")])
        result = self.scan()
        self.assertEqual(result.returncode, 0, output(result))
        self.assert_line(result, r"^OK fake-ok — \+3 entidades, -0, ~0; \+2 relações, -0")
        snapshot = json.loads(self.snapshot_of("fake-ok"))
        keys = [entity_key(e) for e in snapshot["entities"]]
        self.assertEqual(keys, ["pipeline:fake-ok/api/ci", "repository:fake-ok/api", "repository:fake-ok/web"])
        self.assertEqual(len(snapshot["relations"]), 2)
        state = self.scan_state()
        self.assertIn("fake-ok", state)
        self.assertIn(state["fake-ok"]["seen_at"], today_values())
        self.assertEqual(state["fake-ok"]["status"], "ok")
        self.assertEqual(int(state["fake-ok"]["entities"]), 3)
        self.assertEqual(int(state["fake-ok"]["relations"]), 2)
        self.assertFalse((self.snapshots / "fake-off.json").exists(), "coletor com enabled: false não roda")
        self.assertNotIn("fake-off", state)

    def test_scan_without_enabled_collectors_writes_nothing(self):
        """SPEC-0033:IT-01"""
        shutil.rmtree(self.snapshots)
        for collectors in ([], [("fake-off", "static.py", ["fake-off"], 10, "false")]):
            with self.subTest(collectors=len(collectors)):
                if collectors:
                    self.configure(collectors)
                else:
                    self.configure_raw("collectors: []")
                before = snapshot(self.atlas)
                result = self.scan()
                self.assertEqual(result.returncode, 0, output(result))
                self.assertFalse(self.snapshots.exists(), "nem a pasta snapshots/ vazia é criada")
                self.assertEqual(snapshot(self.atlas), before, "scan sem coletor habilitado não grava nada")

    def test_scan_json_prints_a_json_report(self):
        """SPEC-0033:IT-01"""
        self.configure([("fake-ok", "static.py", ["fake-ok"], 10)])
        result = self.scan("--json")
        self.assertEqual(result.returncode, 0, output(result))
        report = json.loads(result.stdout)
        self.assertIn("fake-ok", json.dumps(report))
        self.assertTrue((self.snapshots / "fake-ok.json").is_file())


class RepeatedScanTest(ScanCase):
    def test_second_scan_shows_only_the_differences_and_third_shows_no_changes(self):
        """SPEC-0033:IT-02"""
        state_file = self.atlas / "fake-state.txt"
        self.configure([("fake-var", "variable.py", ["fake-var", "{atlas}/fake-state.txt"], 10)])
        first = self.scan()
        self.assertEqual(first.returncode, 0, output(first))
        self.assert_line(first, r"^OK fake-var — \+4 entidades, -0, ~0; \+2 relações, -0")

        state_file.write_text("v2", encoding="utf-8")
        second = self.scan()
        self.assertEqual(second.returncode, 0, output(second))
        self.assert_line(second, r"^OK fake-var — \+1 entidades, -1, ~0; \+0 relações, -0")
        keys = {entity_key(e) for e in json.loads(self.snapshot_of("fake-var"))["entities"]}
        self.assertIn("repository:acme/c", keys)
        self.assertNotIn("repository:acme/b", keys)
        written = self.snapshot_of("fake-var")

        state_file.write_text("v2-shuffled", encoding="utf-8")
        third = self.scan()
        self.assertEqual(third.returncode, 0, output(third))
        self.assert_line(third, r"^OK fake-var — sem mudanças")
        self.assertEqual(self.snapshot_of("fake-var"), written, "mesmo estado em outra ordem = mesmo arquivo")


class RedactionScanTest(ScanCase):
    def test_planted_secrets_never_reach_the_snapshot_or_the_output(self):
        """SPEC-0033:IT-03"""
        self.configure([("fake-secrets", "planted_secrets.py", ["fake-secrets"], 10)])
        result = self.scan()
        self.assertEqual(result.returncode, 0, output(result))
        self.assert_line(result, r"^OK fake-secrets — ")
        self.assertIn("2 valor(es) mascarado(s)", output(result))
        text = self.snapshot_of("fake-secrets")
        self.assertEqual(text.count(REDACTED), 2, text)
        attrs = json.loads(text)["entities"][0]["attrs"]
        self.assertEqual(attrs["default_branch"], "main")
        for secret in (FAKE_TOKEN, FAKE_PASSWORD):
            self.assertNotIn(secret, output(result))
            for path in self.atlas.rglob("*"):
                if path.is_file():
                    self.assertNotIn(secret, path.read_text(encoding="utf-8", errors="replace"), path)


    def test_secret_used_as_attrs_or_signal_key_never_reaches_the_snapshot(self):
        """SPEC-0033:IT-03"""
        self.configure([("fake-secrets", "planted_secrets.py", ["fake-secrets", "--keys"], 10)])
        result = self.scan()
        self.assertEqual(result.returncode, 0, output(result))
        self.assert_line(result, r"^OK fake-secrets — ")
        text = self.snapshot_of("fake-secrets")
        self.assertIn(REDACTED, text)
        self.assertNotIn(FAKE_TOKEN, text)
        self.assertNotIn(FAKE_TOKEN, output(result))
        for path in self.atlas.rglob("*"):
            if path.is_file():
                self.assertNotIn(FAKE_TOKEN, path.read_text(encoding="utf-8", errors="replace"), path)

    def test_wrong_type_in_a_contract_field_fails_without_snapshot_or_value(self):
        """SPEC-0033:IT-03"""
        value = "hunter" + "2"
        self.configure([("fake-bad-types", "bad_types.py", ["fake-bad-types"], 10)])
        result = self.scan()
        self.assertEqual(result.returncode, 1, output(result))
        self.assert_line(result, r"^FALHA fake-bad-types — \S")
        self.assertFalse((self.snapshots / "fake-bad-types.json").exists())
        self.assertNotIn(value, output(result))
        for path in self.atlas.rglob("*"):
            if path.is_file():
                self.assertNotIn(value, path.read_text(encoding="utf-8", errors="replace"), path)

    def test_extra_pattern_matching_the_empty_string_exits_2(self):
        """SPEC-0033:IT-03"""
        self.configure([("fake-ok", "static.py", ["fake-ok"], 10)], extra_patterns='["z*"]')
        result = self.scan()
        self.assertEqual(result.returncode, 2, output(result))
        self.assertIn("extra_patterns[0]", output(result))
        self.assertNotIn("z*", output(result), "a mensagem só aponta a posição")
        self.assertFalse((self.snapshots / "fake-ok.json").exists())


class FailingCollectorsTest(ScanCase):
    OLD_DATE = "2020-01-01"
    FAILING = ("fake-exit1", "fake-slow", "fake-badjson")

    def seed_previous_scan(self):
        state = {}
        for cid in self.FAILING:
            previous = {"contract": CONTRACT, "collector": cid, "category": "code",
                        "collected_at": "2020-01-01T00:00:00Z",
                        "entities": [{"kind": "repository", "id": f"acme/{cid}", "name": cid, "attrs": {},
                                      "source": cid}],
                        "relations": []}
            (self.snapshots / f"{cid}.json").write_text(json.dumps(previous, indent=2) + "\n", encoding="utf-8")
            state[cid] = {"seen_at": self.OLD_DATE, "status": "ok", "entities": 1, "relations": 0}
        (self.snapshots / "_scan.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        return {cid: (self.snapshots / f"{cid}.json").read_bytes() for cid in self.FAILING}

    def test_failures_keep_previous_snapshots_and_do_not_stop_the_valid_collector(self):
        """SPEC-0033:IT-04"""
        self.configure([("fake-exit1", "fail.py", [], 10),
                        ("fake-slow", "slow.py", ["fake-slow"], 1),
                        ("fake-badjson", "badjson.py", [], 10),
                        ("fake-ok", "static.py", ["fake-ok"], 10)])
        previous = self.seed_previous_scan()
        started = time.monotonic()
        result = self.scan()
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 1, output(result))
        self.assertLess(elapsed, 20, "o coletor lento precisa ser interrompido pelo timeout")
        for cid in self.FAILING:
            with self.subTest(cid):
                self.assert_line(result, rf"^FALHA {cid} — \S")
                self.assertEqual((self.snapshots / f"{cid}.json").read_bytes(), previous[cid],
                                 "snapshot anterior mantido")
        self.assert_line(result, r"^OK fake-ok — \+3 entidades")
        self.assertTrue((self.snapshots / "fake-ok.json").is_file())
        state = self.scan_state()
        for cid in self.FAILING:
            with self.subTest(cid):
                self.assertEqual(state[cid]["seen_at"], self.OLD_DATE, "seen_at não avança")
                self.assertEqual(state[cid]["status"], "failed")
        self.assertIn(state["fake-ok"]["seen_at"], today_values())
        self.assertEqual(state["fake-ok"]["status"], "ok")

    def test_collector_stderr_is_limited_to_the_last_20_lines_and_redacted(self):
        """SPEC-0033:IT-04"""
        self.configure([("fake-exit1", "fail.py", [], 10)])
        result = self.scan()
        self.assertEqual(result.returncode, 1, output(result))
        self.assert_line(result, r"^FALHA fake-exit1 — \S")
        text = output(result)
        self.assertIn("stderr-linha-25", text)
        self.assertIn("stderr-linha-06", text)
        self.assertNotIn("stderr-linha-05", text)
        self.assertNotIn(FAKE_TOKEN, text)


    def test_multiline_private_key_in_stderr_is_redacted(self):
        """SPEC-0033:IT-04"""
        self.configure([("fake-leaky", "leaky_stderr.py", ["pem"], 10)])
        result = self.scan()
        self.assertEqual(result.returncode, 1, output(result))
        self.assert_line(result, r"^FALHA fake-leaky — \S")
        text = output(result)
        self.assertIn("depois-0033", text, "o stderr é mostrado")
        self.assertNotIn("IBAAKCAQEAbodyline0033", text)
        self.assertNotIn("c2Vjb25kYm9keWxpbmUwMDMz", text)

    def test_token_cut_by_the_line_limit_leaks_no_prefix(self):
        """SPEC-0033:IT-04"""
        self.configure([("fake-leaky", "leaky_stderr.py", ["long"], 10)])
        result = self.scan()
        self.assertEqual(result.returncode, 1, output(result))
        self.assert_line(result, r"^FALHA fake-leaky — \S")
        text = output(result)
        self.assertIn("depois-0033", text, "o stderr é mostrado")
        self.assertIn("x" * 100, text, "a linha longa é mostrada (cortada)")
        self.assertNotIn("ghp_", text, "nenhum pedaço do token aparece")


class OnlyOptionTest(ScanCase):
    def test_unknown_id_exits_2(self):
        """SPEC-0033:IT-05"""
        self.configure([("fake-ok", "static.py", ["fake-ok"], 10)])
        result = self.scan("--only", "nao-existe")
        self.assertEqual(result.returncode, 2, output(result))
        self.assertIn("nao-existe", output(result))
        self.assertFalse((self.snapshots / "fake-ok.json").exists(), "nada roda com id desconhecido")

    def test_only_runs_the_given_collectors(self):
        """SPEC-0033:IT-05"""
        self.configure([("fake-ok", "static.py", ["fake-ok"], 10),
                        ("fake-two", "static.py", ["fake-two"], 10)])
        result = self.scan("--only", "fake-two")
        self.assertEqual(result.returncode, 0, output(result))
        self.assertTrue((self.snapshots / "fake-two.json").is_file())
        self.assertFalse((self.snapshots / "fake-ok.json").exists())
        self.assertNotIn("fake-ok", self.scan_state())


# --------------------------------------------------------------------------- contrato


def doc_json_blocks(text):
    blocks = []
    for body in re.findall(r"```json\s*\n(.*?)```", text, re.DOTALL):
        try:
            blocks.append(json.loads(body))
        except ValueError:
            continue
    return blocks


class ContractExamplesTest(unittest.TestCase):
    def expected(self):
        return json.loads((CONTRACT_FIXTURES / "expected-violations.json").read_text(encoding="utf-8"))

    def test_valid_examples_pass_the_validator(self):
        """SPEC-0033:CT-01"""
        examples = sorted((CONTRACT_FIXTURES / "valid").glob("*.json"))
        self.assertGreaterEqual(len(examples), 2)
        for path in examples:
            with self.subTest(path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                _, violations, dropped = f("validate_collector_output")(data)
                self.assertEqual(violations, [])
                self.assertEqual(dropped, [])

    def test_invalid_examples_fail_with_the_documented_message(self):
        """SPEC-0033:CT-01"""
        expected = self.expected()
        examples = sorted(p.relative_to(CONTRACT_FIXTURES).as_posix()
                          for p in (CONTRACT_FIXTURES / "invalid").glob("*.json"))
        self.assertEqual(examples, sorted(expected), "cada exemplo inválido tem a mensagem esperada")
        for rel, message in expected.items():
            with self.subTest(rel):
                _, violations, _ = f("validate_collector_output")(load_fixture(rel))
                self.assertTrue(any(message in v for v in violations), f"{message!r} não está em {violations}")

    def test_reference_documents_every_example_and_message(self):
        """SPEC-0033:CT-01"""
        self.assertTrue(REFERENCE.is_file(), f"{REFERENCE} não existe ({SPEC})")
        text = REFERENCE.read_text(encoding="utf-8")
        self.assertIn(CONTRACT, text)
        blocks = doc_json_blocks(text)
        for path in sorted(CONTRACT_FIXTURES.glob("*/*.json")):
            rel = path.relative_to(CONTRACT_FIXTURES).as_posix()
            with self.subTest(rel):
                self.assertIn(json.loads(path.read_text(encoding="utf-8")), blocks,
                              f"o exemplo {rel} não está como bloco ```json em {REFERENCE.name}")
        for rel, message in self.expected().items():
            with self.subTest(f"mensagem {rel}"):
                self.assertIn(message, text)


if __name__ == "__main__":
    unittest.main()
