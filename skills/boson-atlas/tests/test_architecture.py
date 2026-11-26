"""Testes de arquitetura da boson-atlas (ADR-0010, SPEC-0032:UT-05).
Run: python3 -m unittest discover -s skills/boson-atlas/tests -p test_architecture.py

Cada regra é testada contra um exemplo que a viola e contra o código real de skills/boson-atlas/:
- scripts/atlas.py é arquivo único (nenhum outro .py em scripts/) e importa só a biblioteca padrão;
- nenhum import de outra skill (gluon-spec, photon-brain, e pelos nomes antigos) nem de tools/, nem caminho para elas; e nenhum
  código de outra skill ou de tools/ importa atlas (o uso é só pela CLI);
- processo externo só dentro da função run_collector, sem shell; inclusive por import de nome ou com alias
  (from subprocess import run, import subprocess as sp, from os import system) — SPEC-0046:UT-01;
- nos coletores de assets/collectors/*.py, subprocess só na função que chama o executável do provedor (run_gh no
  github.py, run_cli no argocd.py), com lista de argumentos e sem shell; os.system/os.popen proibidos — SPEC-0046:UT-04;
- os coletores de assets/collectors/*.py, quando a pasta existe, importam só a biblioteca padrão e nada de
  outra skill;
- nenhum caminho pessoal absoluto em arquivos de skills/boson-atlas/ fora de tests/ (placeholders como
  /Users/<nome> são permitidos);
- a entrada de uma probe só ganha "resource" numa função que passa por linked_resources, e write_probe_log só grava as
  chaves da constante PROBE_LOG_KEYS (SPEC-0096, ADR-0025);
- os adaptadores de probe de assets/probes/ listados em PROBE_ADAPTERS_UNDER_RULES (o suite.py) importam só a
  biblioteca padrão e rodam processos sem shell (SPEC-0103).
"""
import unittest

import architecture_rules
from architecture_rules import (
    cross_skill_path_findings,
    import_findings,
    imports_of,
    personal_path_findings,
    shell_findings,
    subprocess_findings,
)
from helpers import SCRIPT, SKILL, load_atlas

ALLOWED_PROCESS_FUNCTIONS = ("run_collector",)
REPO = SKILL.parent.parent
COLLECTORS = SKILL / "assets" / "collectors"


# função do coletor que chama o executável do provedor (SPEC-0046:UT-04); coletor fora do mapa não roda processo
COLLECTOR_PROCESS_FUNCTIONS = {"github.py": ("run_gh",), "argocd.py": ("run_cli",), "aws.py": ("run_cli",)}


def collector_process_findings(*args, **kwargs):
    """architecture_rules.collector_process_findings(source, filename, allowed) (SPEC-0046:UT-04)."""
    rule = getattr(architecture_rules, "collector_process_findings", None)
    if rule is None:
        raise AssertionError("architecture_rules.collector_process_findings não existe (SPEC-0046)")
    return rule(*args, **kwargs)


def report(findings):
    return "\n".join(findings)


def script_source():
    if not SCRIPT.exists():
        raise AssertionError(f"{SCRIPT} não existe (SPEC-0032)")
    return SCRIPT.read_text(encoding="utf-8")


class ImportRulesTest(unittest.TestCase):
    def test_third_party_local_and_cross_skill_imports_are_reported(self):
        """SPEC-0032:UT-05"""
        source = (
            "import os\n"
            "import yaml\n"
            "from helpers import x\n"
            "import spec_graph\n"
            "from tools.sdd import spec_graph as sg\n"
            "import brain\n"
            "from urllib.parse import quote\n"
            "from . import y\n"
        )
        findings = import_findings(source, "scripts/atlas.py", local_modules=["helpers"])
        self.assertEqual(len(findings), 6, report(findings))
        self.assertIn("scripts/atlas.py:2", findings[0])
        self.assertIn("'yaml'", findings[0])
        self.assertIn("scripts/atlas.py:3", findings[1])
        self.assertIn("arquivo único", findings[1])
        self.assertIn("scripts/atlas.py:4", findings[2])
        self.assertIn("entre skills", findings[2])
        self.assertIn("scripts/atlas.py:5", findings[3])
        self.assertIn("entre skills", findings[3])
        self.assertIn("scripts/atlas.py:6", findings[4])
        self.assertIn("entre skills", findings[4])
        self.assertIn("scripts/atlas.py:8", findings[5])

    def test_paths_to_other_skills_and_tools_are_reported(self):
        """SPEC-0032:UT-05"""
        source = ('import sys\nsys.path.insert(0, "../sdd-management/scripts")\n'
                  'sys.path.insert(0, "../second-brain/scripts")\nX = "tools/sdd/spec_graph.py"\n'
                  'sys.path.insert(0, "../gluon-spec/scripts")\nsys.path.insert(0, "../photon-brain/scripts")\n')
        findings = cross_skill_path_findings(source, "scripts/atlas.py")
        self.assertEqual(len(findings), 5, report(findings))
        self.assertEqual(cross_skill_path_findings('CONFIG = "atlas-config.yml"\n', "scripts/atlas.py"), [])

    def test_atlas_is_a_single_file_using_only_the_standard_library(self):
        """SPEC-0032:UT-05"""
        source = script_source()
        others = sorted(p.name for p in SCRIPT.parent.glob("*.py") if p != SCRIPT)
        self.assertEqual(others, [], "scripts/ deve ter só atlas.py (arquivo único)")
        findings = import_findings(source, "scripts/atlas.py")
        findings += cross_skill_path_findings(source, "scripts/atlas.py")
        self.assertEqual(findings, [], report(findings))

    def test_no_other_skill_or_tools_imports_atlas(self):
        """SPEC-0032:UT-05"""
        self.assertEqual(imports_of("import atlas\nfrom atlas import load_config\nimport atlases\n", ("atlas",)),
                         [1, 2])
        offenders = []
        sources = [p for p in sorted((REPO / "skills").glob("*/scripts/*.py")) if SKILL not in p.parents]
        sources += sorted((REPO / "tools").rglob("*.py")) if (REPO / "tools").is_dir() else []
        for path in sources:
            lines = imports_of(path.read_text(encoding="utf-8"), ("atlas",))
            offenders += [f"{path.relative_to(REPO).as_posix()}:{line}" for line in lines]
        self.assertEqual(offenders, [], "outra skill ou tools/ importa atlas (o uso é só pela CLI):\n"
                         + report(offenders))


class CollectorRulesTest(unittest.TestCase):
    def test_collectors_use_only_the_standard_library(self):
        """SPEC-0032:UT-05"""
        bad = import_findings("import json\nimport requests\nimport brain\n", "assets/collectors/github.py")
        self.assertEqual(len(bad), 2, report(bad))
        if not COLLECTORS.is_dir():
            return  # a pasta chega com a SPEC-0033/0034; a regra vale assim que existir
        findings = []
        for path in sorted(COLLECTORS.glob("*.py")):
            rel = path.relative_to(SKILL).as_posix()
            source = path.read_text(encoding="utf-8")
            findings += import_findings(source, rel) + cross_skill_path_findings(source, rel)
        self.assertEqual(findings, [], report(findings))


class ProcessRulesTest(unittest.TestCase):
    def test_process_outside_run_collector_is_reported(self):
        """SPEC-0032:UT-05"""
        source = (
            "import os\n"
            "import subprocess\n"
            "def run_collector(argv):\n"
            "    return subprocess.run(argv)\n"
            "def doctor():\n"
            "    subprocess.run(['gh', '--version'])\n"
            "os.system('ls')\n"
        )
        findings = subprocess_findings(source, "scripts/atlas.py", ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual(len(findings), 2, report(findings))
        self.assertIn("scripts/atlas.py:6", findings[0])
        self.assertIn("doctor", findings[0])
        self.assertIn("scripts/atlas.py:7", findings[1])

    def test_process_imported_by_name_or_alias_outside_run_collector_is_reported(self):
        """SPEC-0046:UT-01"""
        source = (
            "from subprocess import run\n"
            "import subprocess as sp\n"
            "from os import system\n"
            "import os\n"
            "import subprocess\n"
            "from os import path\n"
            "def doctor():\n"
            "    return path.exists('x')\n"
        )
        findings = subprocess_findings(source, "scripts/atlas.py", ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual(len(findings), 3, report(findings))
        for finding, line in zip(findings, (1, 2, 3)):
            self.assertIn(f"scripts/atlas.py:{line} ", finding)
            self.assertIn("processos externos só em run_collector", finding)

    def test_process_imported_by_name_or_alias_inside_run_collector_is_not_reported(self):
        """SPEC-0046:UT-01"""
        source = (
            "def run_collector(argv):\n"
            "    from subprocess import run\n"
            "    import subprocess as sp\n"
            "    from os import system, popen\n"
            "    sp.Popen(argv)\n"
            "    return run(argv)\n"
        )
        findings = subprocess_findings(source, "scripts/atlas.py", ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual(findings, [], report(findings))

    def test_process_imported_by_name_from_os_popen_exec_spawn_is_reported(self):
        """SPEC-0046:UT-01"""
        source = ("from os import popen\n"
                  "from os import execv\n"
                  "from os import spawnv\n"
                  "def doctor():\n"
                  "    from os import system as sh\n")
        findings = subprocess_findings(source, "scripts/atlas.py", ALLOWED_PROCESS_FUNCTIONS)
        self.assertEqual(len(findings), 4, report(findings))
        self.assertIn("doctor", findings[3])

    def test_shell_is_reported(self):
        """SPEC-0032:UT-05"""
        source = ("import subprocess\n"
                  "def run_collector(argv):\n"
                  "    subprocess.run(argv, shell=False)\n"
                  "    subprocess.run(' '.join(argv), shell=True)\n")
        findings = shell_findings(source, "scripts/atlas.py")
        self.assertEqual(len(findings), 1, report(findings))
        self.assertIn("scripts/atlas.py:4", findings[0])

    def test_atlas_runs_processes_only_in_run_collector_and_never_with_shell(self):
        """SPEC-0032:UT-05"""
        source = script_source()
        findings = subprocess_findings(source, "scripts/atlas.py", ALLOWED_PROCESS_FUNCTIONS)
        findings += shell_findings(source, "scripts/atlas.py")
        self.assertEqual(findings, [], report(findings))


class CollectorProcessRulesTest(unittest.TestCase):
    GOOD = (
        "import subprocess\n"
        "def run_gh(gh, args, path):\n"
        "    proc = subprocess.run([gh, *args], stdin=subprocess.DEVNULL, capture_output=True, timeout=60)\n"
        "    return proc.stdout\n"
        "def collect():\n"
        "    try:\n"
        "        return run_gh('gh', ['api'], 'x')\n"
        "    except subprocess.TimeoutExpired:\n"
        "        return None\n"
    )

    def test_collector_process_outside_the_provider_function_or_with_shell_is_reported(self):
        """SPEC-0046:UT-04"""
        cases = {
            "subprocess.run fora de run_gh": (("import subprocess\n"
                                               "def collect(gh):\n"
                                               "    return subprocess.run([gh, 'api'])\n"), 3),
            "subprocess no nível de módulo": (("import subprocess\n"
                                               "subprocess.check_output(['gh', 'api'])\n"), 2),
            "shell=True em run_gh": (("import subprocess\n"
                                      "def run_gh(gh, args):\n"
                                      "    return subprocess.run([gh, *args], shell=True)\n"), 3),
            "texto em vez de lista em run_gh": (("import subprocess\n"
                                                 "def run_gh(gh, args):\n"
                                                 "    return subprocess.run(gh + ' api')\n"), 3),
            "os.system em run_gh": (("import os\n"
                                     "def run_gh(gh, args):\n"
                                     "    return os.system('gh api')\n"), 3),
            "os.popen em run_gh": (("import os\n"
                                    "def run_gh(gh, args):\n"
                                    "    return os.popen('gh api').read()\n"), 3),
            "import com alias fora de run_gh": (("import subprocess as sp\n"
                                                 "def run_gh(gh, args):\n"
                                                 "    return [gh, *args]\n"), 1),
        }
        for name, (source, line) in cases.items():
            with self.subTest(name):
                findings = collector_process_findings(source, "assets/collectors/github.py", ("run_gh",))
                self.assertTrue(findings, f"{name}: nenhum achado")
                self.assertTrue(any(f"assets/collectors/github.py:{line} " in f for f in findings), report(findings))

    def test_collector_process_with_unpacked_kwargs_in_the_provider_function_is_reported(self):
        """SPEC-0046:UT-04"""
        # `**opts` pode esconder shell=True, então a chamada é reportada mesmo dentro de run_gh
        source = ("import subprocess\n"
                  "def run_gh(gh, args, opts):\n"
                  "    return subprocess.run([\"gh\"], **opts)\n")
        findings = collector_process_findings(source, "assets/collectors/github.py", ("run_gh",))
        self.assertTrue(findings, "kwargs desempacotados em run_gh: nenhum achado")
        self.assertTrue(any("assets/collectors/github.py:3 " in f for f in findings), report(findings))

    def test_collector_process_only_in_the_provider_function_with_a_list_is_not_reported(self):
        """SPEC-0046:UT-04"""
        findings = collector_process_findings(self.GOOD, "assets/collectors/github.py", ("run_gh",))
        self.assertEqual(findings, [], report(findings))

    def test_real_collectors_run_processes_only_in_the_provider_function(self):
        """SPEC-0046:UT-04"""
        github = COLLECTORS / "github.py"
        self.assertTrue(github.is_file(), f"{github} não existe (SPEC-0034)")
        findings = []
        for path in sorted(COLLECTORS.glob("*.py")):
            rel = path.relative_to(SKILL).as_posix()
            allowed = COLLECTOR_PROCESS_FUNCTIONS.get(path.name, ())
            findings += collector_process_findings(path.read_text(encoding="utf-8"), rel, allowed)
        self.assertEqual(findings, [], report(findings))


class PersonalPathRulesTest(unittest.TestCase):
    def test_personal_absolute_paths_are_reported_and_placeholders_are_not(self):
        """SPEC-0032:UT-05"""
        text = (
            "atlas: /Users/ana/work/acme-atlas\n"
            "atlas: C:\\Users\\ana\\work\\acme-atlas\n"
            "linux: /home/ana/acme-atlas\n"
            "ok: /Users/<nome>/work/acme-atlas\n"
            "ok: ~/.config/boson-atlas/config.yml\n"
        )
        findings = personal_path_findings(text, "references/config.md")
        self.assertEqual(len(findings), 3, report(findings))
        self.assertIn("references/config.md:1", findings[0])
        self.assertIn("references/config.md:2", findings[1])
        self.assertIn("references/config.md:3", findings[2])

    def test_skill_files_have_no_personal_absolute_path(self):
        """SPEC-0032:UT-05"""
        script_source()  # a skill precisa existir para a varredura valer
        findings = []
        for path in sorted(SKILL.rglob("*")):
            rel = path.relative_to(SKILL)
            if not path.is_file() or rel.parts[0] == "tests" or "__pycache__" in rel.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            findings += personal_path_findings(text, rel.as_posix())
        self.assertEqual(findings, [], report(findings))


def probe_rule(name):
    """architecture_rules.<name> (SPEC-0096)."""
    rule = getattr(architecture_rules, name, None)
    if rule is None:
        raise AssertionError(f"architecture_rules.{name} não existe (SPEC-0096)")
    return rule


# chaves do probes.log de hoje (SPEC-0088) e as desta spec; a SPEC-0104 acrescenta reason e access
PROBE_LOG_TODAY = {"at", "atlas", "service", "environment", "capability", "verb", "adapter", "status", "exit",
                   "confirmed_production"}
PROBE_LOG_LATER = {"reason", "access"}


class ProbeRulesTest(unittest.TestCase):
    def test_a_resource_written_outside_the_resolution_is_reported(self):
        """SPEC-0096:G3 — "resource" no alvo (dict com service, target["resource"] = e target.update(resource=)) numa
        função que não chega a linked_resources é violação; dentro de quem passa por ela (direta ou indiretamente),
        não; sem a função de resolução, uma violação."""
        # SPEC-0096:G3
        source = (
            "def linked_resources(graph, service, env):\n"
            "    return [{'resource': 'queue:a', 'relation': 'writes', 'deployment': 'd'}]\n"
            "def resolve(graph, args):\n"
            "    return linked_resources(graph, args.service, args.env)\n"
            "def good(graph, args):\n"
            "    found = resolve(graph, args)\n"
            "    target = {'service': 's'}\n"
            "    target['resource'] = found[0]\n"
            "    return {'service': 's', 'resource': found[0]}\n"
            "def bad_literal(args):\n"
            "    return {'service': 's', 'deployment': 'd', 'resource': args.resource}\n"
            "def bad_store(request, args):\n"
            "    request['target']['resource'] = args.resource\n"
            "def bad_update(target, args):\n"
            "    target.update(resource=args.resource)\n"
        )
        findings = probe_rule("probe_resource_findings")(source, "scripts/atlas.py")
        self.assertEqual(len(findings), 3, report(findings))
        self.assertIn("scripts/atlas.py:11", findings[0])
        self.assertIn("bad_literal()", findings[0])
        self.assertIn("scripts/atlas.py:13", findings[1])
        self.assertIn("scripts/atlas.py:15", findings[2])
        missing = probe_rule("probe_resource_findings")("def f():\n    return 1\n", "scripts/atlas.py")
        self.assertEqual(len(missing), 1, report(missing))
        self.assertIn("linked_resources", missing[0])

    def test_a_log_line_with_fixed_keys_or_without_the_constant_is_reported(self):
        """SPEC-0096:G3 — write_probe_log com as chaves escritas à mão (como hoje) ou com chave fixa extra, ou sem a
        constante PROBE_LOG_KEYS, é violação; a linha montada só a partir de PROBE_LOG_KEYS, não."""
        # SPEC-0096:G3
        good = ("PROBE_LOG_KEYS = ('at', 'atlas') + ('resource', 'commit')\n"
                "def write_probe_log(record, extras):\n"
                "    line = {key: record[key] for key in PROBE_LOG_KEYS if key in record}\n"
                "    return json.dumps(line, sort_keys=True)\n")
        self.assertEqual(probe_rule("probe_log_findings")(good, "scripts/atlas.py"), [])
        today = ("def write_probe_log(record, extras):\n"
                 "    line = {key: record[key] for key in ('at', 'atlas')}\n"
                 "    return line\n")
        findings = probe_rule("probe_log_findings")(today, "scripts/atlas.py")
        self.assertEqual(len(findings), 2, report(findings))
        self.assertTrue(any("PROBE_LOG_KEYS não é uma constante" in f for f in findings), report(findings))
        self.assertTrue(any("não usa PROBE_LOG_KEYS" in f for f in findings), report(findings))
        extra = good.replace("    return json", "    line['profile'] = record['profile']\n    return json")
        findings = probe_rule("probe_log_findings")(extra, "scripts/atlas.py")
        self.assertEqual(len(findings), 1, report(findings))
        self.assertIn("chave fixa", findings[0])
        literal = good.replace("    return json", "    line = dict(line, context=record['context'])\n    return json")
        self.assertEqual(len(probe_rule("probe_log_findings")(literal, "scripts/atlas.py")), 1)

    def test_atlas_follows_both_probe_rules(self):
        """SPEC-0096:G3 — o atlas.py real: o recurso da entrada só passa por linked_resources, write_probe_log só usa
        PROBE_LOG_KEYS, e a constante tem as chaves de hoje mais resource e commit (e, no máximo, reason e access da
        SPEC-0104), nunca um campo de acesso nem de resultado."""
        # SPEC-0096:G3
        source = script_source()
        findings = (probe_rule("probe_resource_findings")(source, "scripts/atlas.py")
                    + probe_rule("probe_log_findings")(source, "scripts/atlas.py"))
        self.assertEqual(findings, [], report(findings))
        module = load_atlas()
        keys = set(getattr(module, "PROBE_LOG_KEYS", ()) or ())
        self.assertTrue(PROBE_LOG_TODAY | {"resource", "commit"} <= keys, keys)
        self.assertEqual(keys - PROBE_LOG_TODAY - {"resource", "commit"} - PROBE_LOG_LATER, set(), keys)
        for forbidden in ("items", "message", "context", "profile", "user", "database", "passfile", "base_url"):
            self.assertNotIn(forbidden, keys)

    def test_log_keys_are_exactly_the_closed_set(self):
        """SPEC-0104:UT-06 — a regra do conjunto fechado: PROBE_LOG_KEYS com uma chave a mais (profile) ou a menos é
        violação; exatamente as de hoje, resource, commit, reason e access, não; e o atlas.py real segue a regra."""
        # SPEC-0104:UT-06
        rule = probe_rule("probe_log_key_set_findings")
        keys = sorted(PROBE_LOG_TODAY | {"resource", "commit"} | PROBE_LOG_LATER)
        exact = f"PROBE_LOG_KEYS = {tuple(keys)!r}\n"
        self.assertEqual(rule(exact, "scripts/atlas.py"), [])
        extra = f"PROBE_LOG_KEYS = {tuple(keys + ['profile'])!r}\n"
        findings = rule(extra, "scripts/atlas.py")
        self.assertEqual(len(findings), 1, report(findings))
        self.assertIn("profile", findings[0])
        missing = f"PROBE_LOG_KEYS = {tuple(k for k in keys if k != 'reason')!r}\n"
        self.assertEqual(len(rule(missing, "scripts/atlas.py")), 1)
        self.assertEqual(len(rule("X = 1\n", "scripts/atlas.py")), 1)
        findings = rule(script_source(), "scripts/atlas.py")
        self.assertEqual(findings, [], report(findings))


PROBES = SKILL / "assets" / "probes"


class ProbeAdapterRulesTest(unittest.TestCase):
    def test_an_adapter_with_shell_or_third_party_import_is_reported(self):
        """SPEC-0103:UT-08 — a regra dos adaptadores de probe: um suite.py de exemplo com shell=True e import de
        terceiro tem os dois achados; o mesmo com lista de argumentos e só a biblioteca padrão, nenhum."""
        # SPEC-0103:UT-08
        rule = probe_rule("probe_adapter_findings")
        bad = ("import subprocess\n"
               "import requests\n"
               "def run_journey(command):\n"
               "    return subprocess.run(' '.join(command), shell=True)\n")
        findings = rule(bad, "assets/probes/suite.py")
        self.assertEqual(len(findings), 2, report(findings))
        self.assertTrue(any("assets/probes/suite.py:4" in f and "shell" in f for f in findings), report(findings))
        self.assertTrue(any("requests" in f for f in findings), report(findings))
        good = ("import subprocess\n"
                "def run_journey(command):\n"
                "    return subprocess.run(command, shell=False, start_new_session=True)\n")
        self.assertEqual(rule(good, "assets/probes/suite.py"), [])

    def test_suite_adapter_follows_the_rules(self):
        """SPEC-0103:UT-08 — assets/probes/suite.py está sob "só biblioteca padrão" e "processos sem shell"
        (PROBE_ADAPTERS_UNDER_RULES) e o arquivo real passa nas duas."""
        # SPEC-0103:UT-08
        self.assertIn("suite.py", getattr(architecture_rules, "PROBE_ADAPTERS_UNDER_RULES", ()))
        rule = probe_rule("probe_adapter_findings")
        findings = []
        for name in architecture_rules.PROBE_ADAPTERS_UNDER_RULES:
            path = PROBES / name
            self.assertTrue(path.is_file(), f"{path} não existe (SPEC-0103)")
            findings += rule(path.read_text(encoding="utf-8"), path.relative_to(SKILL).as_posix())
        self.assertEqual(findings, [], report(findings))


if __name__ == "__main__":
    unittest.main()
