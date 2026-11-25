"""Contrato do coletor com o nome novo, o antigo aceito (SPEC-0071: CH-01, UT-01 a UT-06, IT-01 e CT-01; ADR-0011,
ADR-0020).

Contrato (seção 6 da spec) que os testes fixam:
    contract aceito: "boson-atlas/collector@1" | "<antigo>/collector@1" (até a SPEC-0073); mesmo formato e regras.
    outro valor -> violação "contract não suportado: <valor>"; a saída não é gravada.
    scan com saída fora do contrato: "saída fora do contrato boson-atlas/collector@1 (N violação(ões))".
    coletores de referência (generic, github, argocd) emitem "boson-atlas/collector@1"; o --help de cada um diz
        boson-atlas e não o nome antigo.
    snapshots gravados com qualquer dos dois nomes: build, lint e context aceitam, com o mesmo grafo.
    Emenda v2 (vendor e doctor):
        UT-05: CI mantida que não cita nenhuma das duas pastas (roda por um script intermediário) com .<antigo>/ no
            atlas não conta como migrada: vendor atualiza as duas cópias, não diz "pode apagar", e o doctor mostra o
            passo de migração (vendor --ci <ci> --force e git rm -r .<antigo>), não "apague com".
        UT-06: workflow do GitHub rodando .boson-atlas/skill desatualizada e ci/atlas-scan.sh personalizado rodando
            .<antigo>/skill: vendor --ci generic deixa as duas cópias iguais ao atlas.py instalado.

O nome antigo é montado por partes (OLD_CONTRACT). Isolamento: helpers.Sandbox (HOME, XDG_CONFIG_HOME e
ATLAS_CONFIG_HOME temporários); sem rede. O coletor de terceiro antigo é fixtures/fake-collectors/legacy_contract.py.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import unittest

from helpers import (
    NEW_SKILL_COPY,
    OLD_SKILL_COPY,
    SKILL,
    TESTS,
    Sandbox,
    doctor_lines,
    fn,
    output,
)
from test_rename import (
    CAN_DELETE_OLD,
    CI_FILES,
    MIGRATION_STEP,
    NEW_CALL,
    OLD_DIR,
    VendorCase,
    custom_ci,
    joined,
    json_rows,
    plant_copy,
)

SPEC = "SPEC-0071"
NEW_CONTRACT = "boson-atlas/collector@1"
OLD_CONTRACT = "org" + "-atlas/collector@1"
CONTRACT_FIXTURES = TESTS / "fixtures" / "contract"
LEGACY = "{skill}/tests/fixtures/fake-collectors/legacy_contract.py"
LEGACY_SCRIPT = TESTS / "fixtures" / "fake-collectors" / "legacy_contract.py"
MCP_COLLECTOR = SKILL.parents[1] / "mcp" / "tests" / "fixtures" / "collector.py"
COLLECTORS = SKILL / "assets" / "collectors"
OUT_OF_CONTRACT = f"saída fora do contrato {NEW_CONTRACT} (1 violação(ões))"

# CH-01: violações de cada fixture de contrato (guarda). Emenda v3: os fixtures usam o nome novo, com um único
# fixture válido explícito com o nome antigo (valid/old-contract-name.json) e boson-atlas/collector@9 no inválido
CURRENT_VIOLATIONS = {
    "invalid/attrs-not-scalar.json": ["entities[0]: attrs.owner não é escalar"],
    "invalid/category-unknown.json": ["category desconhecida: billing"],
    "invalid/contract-version.json": ["contract não suportado: boson-atlas/collector@9"],
    "invalid/duplicate-key.json": ["entities[2]: chave repetida: repository:acme/api"],
    "invalid/from-format.json": ["relations[0]: from fora do formato kind:id: acme/api/ci"],
    "invalid/kind-unknown.json": ["entities[2]: kind desconhecido: widget"],
    "invalid/missing-field.json": ["faltam campos: collected_at"],
    "invalid/to-format.json": ["relations[0]: to fora do formato kind:id: acme/api"],
    "invalid/type-unknown.json": ["relations[0]: type desconhecido: calls"],
    "valid/code-github.json": [],
    "valid/data-aws.json": [],  # SPEC-0097:CT-01 — exemplos do coletor aws
    "valid/delivery-argocd.json": [],
    "valid/messaging-aws.json": [],  # SPEC-0097:CT-01
    "valid/old-contract-name.json": [],
}
OLD_NAME_FIXTURE = "valid/old-contract-name.json"

EMITTER = '''"""Coletor de teste (SPEC-0071): a saída do contrato com o `contract` e o `kind` passados."""
import json
import sys

collector, contract, kind = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({
    "contract": contract,
    "collector": collector,
    "category": "code",
    "collected_at": "2026-10-30T12:00:00Z",
    "entities": [{"kind": kind, "id": "acme/api", "name": "api", "attrs": {}, "source": collector}],
    "relations": [],
}))
'''


def validate(data):
    return fn("validate_collector_output", SPEC)(copy.deepcopy(data))


def fixture(rel):
    return json.loads((CONTRACT_FIXTURES / rel).read_text(encoding="utf-8"))


def renamed(data, contract):
    """A mesma saída com `contract` trocado (só quando é o nome do contrato @1)."""
    data = copy.deepcopy(data)
    if data.get("contract") in (OLD_CONTRACT, NEW_CONTRACT):
        data["contract"] = contract
    return data


def atlas_config(collectors) -> str:
    """atlas-config.yml (modo local) com os coletores [(id, command)]."""
    lines = ["collectors:"]
    for cid, command in collectors:
        lines += [f"  - id: {cid}", "    category: code",
                  "    command: [" + ", ".join(json.dumps(a) for a in command) + "]", "    timeout: 60"]
    return ("version: 1\norganization: Acme\nmode: local\nlanguage: auto\nstale_days: 14\n"
            "categories: [code, delivery]\n" + "\n".join(lines) + "\nredaction: {extra_patterns: []}\n")


class AtlasCase(unittest.TestCase):
    """Atlas novo (init --mode local) num Sandbox."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        out = self.box.init(mode="local")
        self.assertEqual(out.returncode, 0, output(out))
        self.atlas = self.box.atlas
        self.snapshots = self.atlas / "snapshots"

    def configure(self, collectors):
        (self.atlas / "atlas-config.yml").write_text(atlas_config(collectors), encoding="utf-8")

    def run_cli(self, *args, code=0):
        out = self.box.run(*args)
        self.assertNotIn("Traceback", output(out))
        self.assertEqual(out.returncode, code, output(out))
        return out

    def emitter(self):
        folder = self.atlas / "fake"
        folder.mkdir(exist_ok=True)
        (folder / "emit.py").write_text(EMITTER, encoding="utf-8")
        return "{atlas}/fake/emit.py"

    def graph(self):
        data = json.loads((self.atlas / "graph.json").read_text(encoding="utf-8"))
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        return data["nodes"], data["edges"]


# ---------------------------------------------------------------- caracterização (CH-01)

class CharacterizationTest(unittest.TestCase):
    def test_current_contract_fixtures_keep_their_violations(self):
        """SPEC-0071:CH-01 (guarda: passa antes e depois da mudança)"""
        found = sorted(p.relative_to(CONTRACT_FIXTURES).as_posix() for p in CONTRACT_FIXTURES.glob("*/*.json"))
        self.assertEqual(found, sorted(CURRENT_VIOLATIONS), "fixtures de contrato mudaram")
        for rel, expected in CURRENT_VIOLATIONS.items():
            with self.subTest(rel):
                _, violations, dropped = validate(fixture(rel))
                self.assertEqual(violations, expected)
                self.assertEqual(dropped, [])
        for rel in CURRENT_VIOLATIONS:
            with self.subTest(name=rel):
                contract = fixture(rel).get("contract", "")
                if rel == OLD_NAME_FIXTURE:
                    self.assertEqual(contract, OLD_CONTRACT, "o fixture explícito do nome antigo (compatibilidade)")
                else:
                    self.assertTrue(contract.startswith("boson-atlas/collector@"), f"{rel}: {contract}")
        old_named = fixture(OLD_NAME_FIXTURE)
        self.assertEqual(dict(old_named, contract=NEW_CONTRACT), fixture("valid/code-github.json"),
                         "o fixture do nome antigo só difere no contract")


# ---------------------------------------------------------------- unitários (UT-01 a UT-04)

class ContractNamesTest(unittest.TestCase):
    def test_both_names_are_accepted_without_violation(self):
        """SPEC-0071:UT-01"""
        base = fixture("valid/code-github.json")
        cleaned = {}
        for contract in (NEW_CONTRACT, OLD_CONTRACT):
            with self.subTest(contract=contract):
                clean, violations, dropped = validate(renamed(base, contract))
                self.assertEqual(violations, [])
                self.assertEqual(dropped, [])
                cleaned[contract] = clean
        self.assertEqual(renamed(cleaned.get(NEW_CONTRACT, {}), OLD_CONTRACT), cleaned.get(OLD_CONTRACT),
                         "as duas saídas validadas só diferem no nome do contrato")
        self.assertEqual(fn("CONTRACT", SPEC), NEW_CONTRACT)
        self.assertEqual(set(fn("SUPPORTED_CONTRACTS", SPEC)), {NEW_CONTRACT, OLD_CONTRACT})

    def test_unknown_contract_is_a_violation(self):
        """SPEC-0071:UT-02"""
        for value in ("boson-atlas/collector@2", "outro/collector@1"):
            with self.subTest(contract=value):
                data = fixture("valid/code-github.json")
                data["contract"] = value
                _, violations, _ = validate(data)
                self.assertEqual(violations, [f"contract não suportado: {value}"])


class ReferenceCollectorsTest(unittest.TestCase):
    def test_reference_collectors_say_boson_atlas(self):
        """SPEC-0071:UT-03 (o contract de cada um e o --help; a saída com os fixtures está nos testes de cada
        coletor, com o comentário SPEC-0071:CH-01)"""
        facts = TESTS / "fixtures" / "generic" / "facts.json"
        out = subprocess.run([sys.executable, str(COLLECTORS / "generic.py"), "--facts", str(facts),
                              "--category", "data"], capture_output=True, text=True, check=False)
        self.assertEqual(out.returncode, 0, output(out))
        self.assertEqual(json.loads(out.stdout)["contract"], NEW_CONTRACT)
        for name in ("generic.py", "github.py", "argocd.py"):
            with self.subTest(collector=name):
                text = (COLLECTORS / name).read_text(encoding="utf-8")
                self.assertIn(f'CONTRACT = "{NEW_CONTRACT}"', text)
                helped = subprocess.run([sys.executable, str(COLLECTORS / name), "--help"], capture_output=True,
                                        text=True, check=False)
                self.assertEqual(helped.returncode, 0, output(helped))
                self.assertIn("boson-atlas", helped.stdout)
                self.assertNotIn("org" + "-atlas", helped.stdout)


class ScanMessagesTest(AtlasCase):
    def test_unknown_contract_fails_the_collector_without_snapshot(self):
        """SPEC-0071:UT-02 (pelo scan)"""
        emit = self.emitter()
        for i, value in enumerate(("boson-atlas/collector@2", "outro/collector@1")):
            with self.subTest(contract=value):
                cid = f"fake-{i}"
                self.configure([(cid, ["python3", emit, cid, value, "repository"])])
                out = self.run_cli("scan", code=1)
                self.assertIn(f"FALHA {cid}", out.stdout)
                report = self.run_cli("scan", "--json", code=1).stdout
                self.assertIn(f"contract não suportado: {value}", report)
                self.assertFalse((self.snapshots / f"{cid}.json").exists(), "nada é gravado")

    def test_out_of_contract_message_names_the_new_contract(self):
        """SPEC-0071:UT-04"""
        emit = self.emitter()
        for contract in (NEW_CONTRACT, OLD_CONTRACT):
            with self.subTest(contract=contract):
                self.configure([("fake", ["python3", emit, "fake", contract, "widget"])])
                out = self.run_cli("scan", code=1)
                self.assertIn(f"FALHA fake — {OUT_OF_CONTRACT}", out.stdout)
                self.assertNotIn(OLD_CONTRACT, out.stdout)


# ---------------------------------------------------------------- vendor e doctor (UT-05, UT-06, Emenda v2)

INDIRECT_CI = ("#!/usr/bin/env bash\n# CI do time: roda a ferramenta pelo script de apoio do time\n"
               "set -euo pipefail\nbash team/run-atlas.sh\n")


class CiWithoutFolderTest(VendorCase):
    def test_kept_ci_that_cites_no_folder_is_not_migrated(self):
        """SPEC-0071:UT-05"""
        plant_copy(self.atlas_dir, OLD_SKILL_COPY, outdated=True)
        team = self.atlas_dir / "team" / "run-atlas.sh"
        team.parent.mkdir(parents=True)
        team.write_text(custom_ci("generic"), encoding="utf-8")  # o script de apoio roda a cópia antiga
        script = self.atlas_dir / CI_FILES["generic"]
        script.parent.mkdir(parents=True)
        script.write_text(INDIRECT_CI, encoding="utf-8")
        self.assertNotIn(OLD_DIR, INDIRECT_CI)
        self.assertNotIn(NEW_SKILL_COPY, INDIRECT_CI)

        out = self.vendor("--ci", "generic")
        self.assertEqual(script.read_text(encoding="utf-8"), INDIRECT_CI, "CI personalizada mantida sem --force")
        self.assert_copy_is_current(OLD_SKILL_COPY)
        self.assert_copy_is_current(NEW_SKILL_COPY)
        self.assertNotIn(CAN_DELETE_OLD, output(out), "nada prova que a CI parou de rodar a cópia antiga")
        # Emenda v3: o aviso do caso "desconhecido" também sugere trocar o script para rodar a cópia nova
        warning = [line for line in out.stdout.splitlines() if line.startswith(CI_FILES["generic"].as_posix())]
        self.assertEqual(len(warning), 1, out.stdout)
        self.assertIn("troque", warning[0], "sugere trocar o script")
        self.assertIn(f"rodar {NEW_SKILL_COPY}", warning[0])
        self.assertIn(MIGRATION_STEP, warning[0])

        for args in (("doctor",), ("doctor", "--json")):
            with self.subTest(args=args):
                doctor = self.box.run(*args)
                self.assertNotIn("Traceback", output(doctor))
                rows = json_rows(doctor.stdout) if "--json" in args else doctor_lines(doctor.stdout)
                found = [line for line in joined(rows) if line.startswith("AVISO ") and MIGRATION_STEP in line]
                self.assertEqual(len(found), 1, output(doctor))
                self.assertIn("vendor --ci", found[0], "o doctor mostra o passo de migração")
                self.assertIn("--force", found[0])
                self.assertNotIn("apague com", found[0])


class TwoCiKindsTest(VendorCase):
    def test_vendor_generic_updates_both_copies_when_each_ci_runs_one(self):
        """SPEC-0071:UT-06"""
        self.vendor("--ci", "github")
        workflow = (self.atlas_dir / CI_FILES["github"]).read_text(encoding="utf-8")
        self.assertIn(NEW_CALL, workflow, "fixture: o workflow do GitHub roda a cópia nova")
        plant_copy(self.atlas_dir, NEW_SKILL_COPY, outdated=True)
        plant_copy(self.atlas_dir, OLD_SKILL_COPY, outdated=True)
        script = self.atlas_dir / CI_FILES["generic"]
        script.parent.mkdir(parents=True)
        script.write_text(custom_ci("generic"), encoding="utf-8")

        self.vendor("--ci", "generic")
        self.assert_copy_is_current(NEW_SKILL_COPY)
        self.assert_copy_is_current(OLD_SKILL_COPY)
        self.assertEqual(script.read_text(encoding="utf-8"), custom_ci("generic"), "CI personalizada mantida")


# ---------------------------------------------------------------- integração (IT-01)

class OldSnapshotsTest(AtlasCase):
    def test_snapshots_and_collector_with_the_old_name_work_and_give_the_same_graph(self):
        """SPEC-0071:IT-01"""
        self.configure([("legacy", ["python3", LEGACY, "legacy"])])
        self.run_cli("scan")
        snapshot = self.snapshots / "legacy.json"
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        self.assertEqual(data["contract"], OLD_CONTRACT, "snapshot gravado com o nome do coletor de terceiro")

        build = self.run_cli("build")
        self.assertNotIn("fora do contrato", output(build))
        before = self.graph()
        self.assertTrue(before[0], "o grafo tem os nós do coletor antigo")

        lint = self.run_cli("lint", "--json")
        self.assertEqual(json.loads(lint.stdout)["errors"], 0, lint.stdout)
        context = self.run_cli("context", "billing", "--json")
        self.assertIn("billing", context.stdout)

        data["contract"] = NEW_CONTRACT
        snapshot.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        build = self.run_cli("build")
        self.assertNotIn("fora do contrato", output(build), "snapshot com o nome novo é aceito no build")
        self.assertEqual(self.graph(), before, "o grafo é o mesmo com os dois nomes")
        lint = self.run_cli("lint", "--json")
        self.assertEqual(json.loads(lint.stdout)["errors"], 0, lint.stdout)
        context = self.run_cli("context", "billing", "--json")
        self.assertIn("billing", context.stdout)


# ---------------------------------------------------------------- contrato (CT-01)

class ContractFixturesTest(unittest.TestCase):
    def test_valid_fixtures_pass_with_both_names_and_invalid_ones_fail_the_same_way(self):
        """SPEC-0071:CT-01"""
        for rel, expected in CURRENT_VIOLATIONS.items():
            for contract in (NEW_CONTRACT, OLD_CONTRACT):
                with self.subTest(rel=rel, contract=contract):
                    _, violations, dropped = validate(renamed(fixture(rel), contract))
                    self.assertEqual(violations, expected)
                    self.assertEqual(dropped, [])

    def test_mcp_fixture_emits_the_new_name_and_the_legacy_fixture_the_old_one(self):
        """SPEC-0071:CT-01 (fixture do MCP e coletor de terceiro antigo)"""
        for script, contract in ((MCP_COLLECTOR, NEW_CONTRACT), (LEGACY_SCRIPT, OLD_CONTRACT)):
            with self.subTest(fixture=script.name):
                self.assertTrue(script.is_file(), script)
                out = subprocess.run([sys.executable, str(script), "fake"], capture_output=True, text=True,
                                     check=False)
                self.assertEqual(out.returncode, 0, output(out))
                data = json.loads(out.stdout)
                self.assertEqual(data["contract"], contract)
                _, violations, dropped = validate(data)
                self.assertEqual(violations, [])
                self.assertEqual(dropped, [])


# ---------------------------------------------------------------- Emenda v3 (IT-02 e SKILL.md)

PREVIOUS_ATLAS = TESTS / "fixtures" / "previous" / "atlas.py"


class PreviousVersionBuildTest(AtlasCase):
    def run_previous(self, *args):
        """O atlas.py da versão anterior (fixtures/previous) rodando como skill instalada: scripts/atlas.py e os
        assets/ numa pasta temporária, com a mesma configuração isolada do Sandbox."""
        skill = self.box.root / "previous-skill"
        if not skill.exists():
            (skill / "scripts").mkdir(parents=True)
            shutil.copy(PREVIOUS_ATLAS, skill / "scripts" / "atlas.py")
            shutil.copytree(SKILL / "assets", skill / "assets", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        env = dict(os.environ, HOME=str(self.box.home), XDG_CONFIG_HOME=str(self.box.home / ".config"),
                   ATLAS_CONFIG_HOME=str(self.box.config_home))
        out = subprocess.run([sys.executable, str(skill / "scripts" / "atlas.py"), *args], cwd=self.box.root,
                             capture_output=True, text=True, env=env, check=False)
        self.assertNotIn("Traceback", output(out))
        return out

    def test_previous_version_builds_the_same_graph_from_a_snapshot_written_now(self):
        """SPEC-0071:IT-02 (Emenda v3)"""
        self.assertTrue(PREVIOUS_ATLAS.is_file(), f"{PREVIOUS_ATLAS} não existe")
        version = self.run_previous("--version")
        self.assertEqual(version.stdout.strip(), "boson-atlas 2026.11.7", "fixture: a versão anterior")
        facts = self.atlas / "facts" / "services.json"
        facts.parent.mkdir()
        facts.write_text(json.dumps({
            "entities": [{"kind": "service", "id": "billing", "name": "billing", "attrs": {}},
                         {"kind": "service", "id": "api", "name": "api", "attrs": {}},
                         {"kind": "datastore", "id": "payments-db", "name": "payments-db", "attrs": {}}],
            "relations": [{"from": "service:billing", "to": "service:api", "type": "depends_on"},
                          {"from": "service:api", "to": "datastore:payments-db", "type": "writes"}]}),
            encoding="utf-8")
        self.configure([("facts", ["python3", "{skill}/assets/collectors/generic.py", "--facts",
                                   "{atlas}/facts/services.json", "--category", "code", "--source", "facts"])])
        self.run_cli("scan")
        written = json.loads((self.snapshots / "facts.json").read_text(encoding="utf-8"))
        self.assertEqual(written["contract"], OLD_CONTRACT,
                         "até a SPEC-0073 o scan grava o nome antigo, que a versão anterior lê")

        self.run_cli("build")
        current = self.graph()
        self.assertTrue(current[0], "o build desta versão tem nós")
        previous_build = self.run_previous("build")
        self.assertEqual(previous_build.returncode, 0, output(previous_build))
        self.assertNotIn("fora do contrato", output(previous_build), "a versão anterior aceita o snapshot")
        self.assertEqual(self.graph(), current, "o build da versão anterior gera os mesmos nós e arestas")


class SkillDocTest(unittest.TestCase):
    def test_skill_md_names_the_new_contract(self):
        """SPEC-0071:UT-03 (Emenda v3: SKILL.md cita o contrato novo; o antigo só como compatibilidade)"""
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(NEW_CONTRACT, text)
        lines = [line for line in text.splitlines() if OLD_CONTRACT in line and NEW_CONTRACT not in line]
        self.assertEqual(lines, [], "SKILL.md descreve o contrato com o nome antigo")


if __name__ == "__main__":
    unittest.main()
