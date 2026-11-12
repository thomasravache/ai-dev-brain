"""Coletor generic da boson-atlas (SPEC-0034: UT-05, IT-04 e a parte generic do CT-01).

Contrato esperado de assets/collectors/generic.py (o Implementer segue estes testes):

    generic.py --facts ARQUIVO --category C [--source NOME]
        ARQUIVO (JSON): {"entities": [{"kind", "id", "name", "attrs"}], "relations": [{"from", "to", "type"}]}
        stdout: um objeto org-atlas/collector@1 com collector "generic", category C, collected_at ISO 8601 UTC
        (AAAA-MM-DDTHH:MM:SSZ) e source NOME (padrão "generic") em cada entidade e relação; exit 0.
        Arquivo inexistente ou JSON inválido: exit 1 "<arquivo>: <motivo>" (o caminho como foi passado).
        Entidade sem kind ou sem id: exit 1 com o índice (entities[<i>]) e o campo que falta. Nunca traceback.

    convert_facts(facts: dict, category: str, source: str = "generic") -> dict
        Os fatos já lidos -> a saída do contrato (mesmo formato do stdout).
"""
import copy
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest

from helpers import SKILL, TESTS, fn, output

SPEC = "SPEC-0034"
CONTRACT = "org-atlas/collector@1"
GENERIC = SKILL / "assets" / "collectors" / "generic.py"
FIXTURES = TESTS / "fixtures" / "generic"
FACTS = FIXTURES / "facts.json"
COLLECTED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_CACHE = {}


def collector():
    """assets/collectors/generic.py importado pelo caminho (sem sys.path)."""
    if "module" not in _CACHE:
        if not GENERIC.exists():
            raise AssertionError(f"{GENERIC} não existe ({SPEC})")
        spec = importlib.util.spec_from_file_location("org_atlas_collector_generic", GENERIC)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CACHE["module"] = module
    return _CACHE["module"]


def function(name):
    f = getattr(collector(), name, None)
    if f is None:
        raise AssertionError(f"generic.{name} não existe ({SPEC})")
    return f


def facts():
    return json.loads(FACTS.read_text(encoding="utf-8"))


def run_generic(*args):
    with tempfile.TemporaryDirectory() as cwd:
        return subprocess.run([sys.executable, str(GENERIC), *[str(a) for a in args]], check=False, cwd=cwd,
                              capture_output=True, text=True)


def with_source(items, source):
    return [dict(item, source=source) for item in items]


class GenericAssertions(unittest.TestCase):
    def assert_converted(self, data, category, source):
        self.assertIsInstance(data, dict)
        self.assertEqual(data.get("contract"), CONTRACT)
        self.assertEqual(data.get("collector"), "generic")
        self.assertEqual(data.get("category"), category)
        self.assertRegex(str(data.get("collected_at")), COLLECTED_AT)
        expected = facts()
        self.assertEqual(data.get("entities"), with_source(expected["entities"], source))
        self.assertEqual(data.get("relations"), with_source(expected["relations"], source))


# --------------------------------------------------------------------------- unitários


class ConvertFactsTest(GenericAssertions):
    def test_facts_become_the_contract_output_with_source(self):
        """SPEC-0034:UT-05 — cabeçalho do contrato e entidades/relações com source (padrão "generic")."""
        given = facts()
        data = function("convert_facts")(copy.deepcopy(given), "runtime")
        self.assert_converted(data, "runtime", "generic")
        self.assertEqual(given, facts(), "convert_facts não altera os fatos recebidos")

    def test_source_option_is_used_in_every_fact(self):
        """SPEC-0034:UT-05 — --source NOME vira o source de cada entidade e relação; collector segue "generic"."""
        data = function("convert_facts")(facts(), "docs", source="handbook")
        self.assert_converted(data, "docs", "handbook")


# --------------------------------------------------------------------------- integração


class GenericCliTest(GenericAssertions):
    def test_valid_facts_file_prints_the_output_and_exits_0(self):
        """SPEC-0034:IT-04 — arquivo válido gera a saída do contrato no stdout."""
        result = run_generic("--facts", FACTS, "--category", "runtime")
        self.assertEqual(result.returncode, 0, output(result))
        self.assert_converted(json.loads(result.stdout), "runtime", "generic")
        result = run_generic("--facts", FACTS, "--category", "runtime", "--source", "handbook")
        self.assertEqual(result.returncode, 0, output(result))
        self.assert_converted(json.loads(result.stdout), "runtime", "handbook")

    def test_missing_or_invalid_file_exits_1_with_the_file_and_the_reason(self):
        """SPEC-0034:IT-04 — arquivo inexistente ou JSON inválido: exit 1 "<arquivo>: <motivo>"."""
        for name, path in (("JSON inválido", FIXTURES / "invalid-json.json"),
                           ("arquivo inexistente", FIXTURES / "nao-existe.json")):
            with self.subTest(name):
                result = run_generic("--facts", path, "--category", "runtime")
                self.assertEqual(result.returncode, 1, output(result))
                self.assertNotIn("Traceback", output(result))
                self.assertRegex(output(result), re.escape(f"{path}: ") + r"\S")

    def test_entity_without_kind_or_id_exits_1_with_the_index(self):
        """SPEC-0034:IT-04 — entidade sem id (ou sem kind): exit 1 com o índice e o campo."""
        for name, path, index, field in (("sem id", FIXTURES / "missing-id.json", 1, "id"),
                                         ("sem kind", FIXTURES / "missing-kind.json", 0, "kind")):
            with self.subTest(name):
                result = run_generic("--facts", path, "--category", "runtime")
                self.assertEqual(result.returncode, 1, output(result))
                text = output(result)
                self.assertNotIn("Traceback", text)
                self.assertIn(f"entities[{index}]", text)
                self.assertIn(field, text.split(f"entities[{index}]", 1)[1])
                self.assertFalse(result.stdout.strip().startswith(("{", "[")), "nada de saída parcial no stdout")


# --------------------------------------------------------------------------- contrato


class GenericContractTest(unittest.TestCase):
    def test_generic_output_passes_the_collector_contract(self):
        """SPEC-0034:CT-01 — saída de generic.py passa no validate_collector_output (SPEC-0033@1)."""
        result = run_generic("--facts", FACTS, "--category", "runtime")
        self.assertEqual(result.returncode, 0, output(result))
        data = json.loads(result.stdout)
        _, violations, dropped = fn("validate_collector_output", "SPEC-0033")(data)
        self.assertEqual(violations, [])
        self.assertEqual(dropped, [])


if __name__ == "__main__":
    unittest.main()
