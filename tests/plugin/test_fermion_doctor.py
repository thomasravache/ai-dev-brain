"""Doctor de instalação antiga do plugin fermion (SPEC-0061: UT-01 a UT-06, IT-01 e E2E-01; ADR-0019).

Run: python3 -m unittest discover -s tests/plugin -p test_fermion_doctor.py

Interface que estes testes exigem de `scripts/fermion_doctor.py` (seção 6 da SPEC-0061), sempre rodado como processo
(`python3 scripts/fermion_doctor.py [--project PASTA] [--json]`), nunca importado:

- plugin = a pasta acima de scripts/ (Path(__file__)); versões lidas por expressão regular de
  skills/gluon-spec/scripts/spec_graph.py (SDD_TOOL_VERSION), skills/photon-brain/scripts/brain.py (BRAIN_VERSION) e
  skills/boson-atlas/scripts/atlas.py (ATLAS_VERSION), comparadas como tupla de inteiros (2026.10.10 > 2026.10.9).
- pasta de skills do usuário = $CLAUDE_CONFIG_DIR/skills, senão $HOME/.claude/skills; do projeto =
  <projeto>/.claude/skills; projeto = --project, senão o cwd.
- --json: {"plugin_versions": {"gluon-spec", "photon-brain", "boson-atlas"}, "findings": [{"check", "level": "warn",
  "path", "detail", "fix"}]}. `path` pode ser absoluto ou relativo ao projeto (tools/sdd/spec_graph.py, AGENTS.md,
  .boson-atlas/skill); os testes aceitam a pasta ou o arquivo que denunciou o achado.
- texto: uma linha "AVISO <check> <caminho> — <detalhe>" por achado; sem achado, uma linha "OK <check> ..." por
  checagem (old-name-copy, stale-copy, stale-sdd-tool, old-sdd-block, stale-atlas, broken-leak-hook — SPEC-0068,
  old-config e old-atlas-folder — SPEC-0072).
- exit sempre 0, nada gravado, nenhum processo, nenhuma rede; link simbólico para fora da pasta conferida não é
  seguido; pasta sem permissão é ignorada; versão ilegível numa cópia vira "unreadable-version".

As regras do ADR-0019 (UT-06) ficam em tests/plugin/doctor_architecture_rules.py, carregado por caminho; o
`arch_test` roda `DoctorArchitectureTest` deste arquivo.

Isolamento: todo processo roda com HOME, CLAUDE_CONFIG_DIR e XDG_CONFIG_HOME temporários (variáveis CLAUDE_* do
ambiente real saem); nunca o ~/.claude, o ~/.claude.json nem a configuração real de quem roda. Os nomes antigos das
skills nunca aparecem aqui com o prefixo de pasta de skills por extenso (guarda da SPEC-0055): os caminhos são
montados por partes.
"""
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCTOR = REPO / "scripts" / "fermion_doctor.py"
DOCTOR_NAME = "scripts/fermion_doctor.py"
RULES = Path(__file__).resolve().parent / "doctor_architecture_rules.py"

# nome novo -> (script, constante de versão); nome antigo -> nome novo
SKILL_SCRIPTS = {
    "gluon-spec": ("spec_graph.py", "SDD_TOOL_VERSION"),
    "photon-brain": ("brain.py", "BRAIN_VERSION"),
    "boson-atlas": ("atlas.py", "ATLAS_VERSION"),
}
OLD_TO_NEW = {"sdd-management": "gluon-spec", "second-brain": "photon-brain", "org-atlas": "boson-atlas"}
# SPEC-0072:CH-01 — duas checagens novas, cada uma com a sua linha OK quando não há achado
CHECKS = ("old-name-copy", "stale-copy", "stale-sdd-tool", "old-sdd-block", "stale-atlas", "broken-leak-hook",
          "old-config", "old-atlas-folder")
# pasta da cópia da boson-atlas no atlas (SPEC-0070); a antiga é montada por partes (guarda da SPEC-0072)
NEW_COPY_DIR = ".boson-atlas"
OLD_COPY_DIR = "." + "org" + "-atlas"
WARN_LINE_RE = re.compile(r"^AVISO (\S+) (.+?) — (.+)$")
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
DOCTOR_TIMEOUT = 60
LOW_VERSION = "2026.10.1"
HOOK_HEADER = "## Instalação desatualizada (fermion)"
READ_LIMIT = 256 * 1024  # Emenda v2: só os primeiros 256 KB de cada arquivo


def read_version(path, constant):
    match = re.search(rf'^{constant} = "([^"]+)"', Path(path).read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"{constant} não encontrada em {path}"
    return match.group(1)


def plugin_versions(root=REPO):
    return {skill: read_version(Path(root) / "skills" / skill / "scripts" / script, constant)
            for skill, (script, constant) in SKILL_SCRIPTS.items()}


def version_line(skill, version):
    """Conteúdo mínimo de um script de skill: só a constante de versão (o doctor lê por expressão regular)."""
    _, constant = SKILL_SCRIPTS[skill]
    return f'#!/usr/bin/env python3\n"""Cópia de teste."""\n{constant} = "{version}"\n'


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def skill_copy(skills_dir, name, version=None, with_skill_md=True):
    """<skills_dir>/<name>/ com SKILL.md e, quando há versão, scripts/<script> com a constante (nome novo)."""
    folder = Path(skills_dir) / name
    folder.mkdir(parents=True, exist_ok=True)
    if with_skill_md:
        write(folder / "SKILL.md", f"---\nname: {name}\ndescription: cópia antiga de teste\n---\n# {name}\n")
    if version is not None:
        script, _ = SKILL_SCRIPTS[name]
        write(folder / "scripts" / script, version_line(name, version))
    return folder


def sdd_block(*names):
    return ("# Agentes\n\n<!-- sdd:start -->\n## Processo (SDD)\n"
            + "".join(f"Carregue a skill `{name}` antes de agir.\n" for name in names)
            + "<!-- sdd:end -->\n")


class Sandbox:
    """HOME, CLAUDE_CONFIG_DIR, XDG_CONFIG_HOME e projeto em pastas temporárias; ambiente sem CLAUDE_* real."""

    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.home = self.base / "home"
        self.config = self.base / "config"
        self.project = self.base / "projeto"
        for folder in (self.home, self.config, self.project):
            folder.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
        self.env.update({"HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.config),
                         "XDG_CONFIG_HOME": str(self.home / ".config"), "PYTHONDONTWRITEBYTECODE": "1"})
        real_home = Path(os.environ.get("HOME") or Path.home()).resolve()
        real_config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or real_home / ".claude").resolve()
        assert self.home.resolve() != real_home
        assert self.config.resolve() != real_config
        assert not self.config.is_relative_to(real_home), f"{self.config} dentro do HOME real"

    @property
    def user_skills(self):
        return self.config / "skills"

    @property
    def project_skills(self):
        return self.project / ".claude" / "skills"

    def up_to_date_project(self, versions=None):
        """tools/sdd na versão do plugin e bloco sdd:start que cita a gluon-spec (nada a avisar)."""
        versions = versions or plugin_versions()
        write(self.project / "tools" / "sdd" / "spec_graph.py", version_line("gluon-spec", versions["gluon-spec"]))
        write(self.project / "AGENTS.md", sdd_block("gluon-spec"))


def require_doctor(test, script=DOCTOR):
    if not Path(script).is_file():
        test.fail(f"{DOCTOR_NAME} não existe (SPEC-0061)")


def run_doctor(test, sandbox, *, as_json=True, project=True, cwd=None, env=None, script=DOCTOR):
    """Roda o doctor como processo; exit 0 e nenhum Traceback são parte do contrato."""
    require_doctor(test, script)
    argv = [sys.executable, str(script)]
    if project:
        argv += ["--project", str(sandbox.project if project is True else project)]
    if as_json:
        argv.append("--json")
    result = subprocess.run(argv, cwd=str(cwd or sandbox.base), env=env or sandbox.env, capture_output=True,
                            text=True, timeout=DOCTOR_TIMEOUT, check=False)
    test.assertEqual(result.returncode, 0, f"exit {result.returncode}\n{result.stdout}\n{result.stderr}")
    test.assertNotIn("Traceback", result.stderr)
    if not as_json:
        return result.stdout
    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        test.fail(f"--json não imprimiu JSON ({exc}): {result.stdout[:300]!r}")
    test.assertIsInstance(data, dict, data)
    test.assertIsInstance(data.get("findings"), list, data)
    for finding in data["findings"]:
        test.assertIsInstance(finding, dict, finding)
        test.assertEqual(sorted(finding), ["check", "detail", "fix", "level", "path"], finding)
        test.assertEqual(finding["level"], "warn", finding)
        for key in ("check", "path", "detail", "fix"):
            test.assertIsInstance(finding[key], str, finding)
            test.assertTrue(finding[key].strip(), f"{key} vazio: {finding}")
    return data


def reported(path, project):
    """Caminho de um achado como Path normalizado: absoluto, ou relativo ao projeto."""
    found = Path(path)
    return Path(os.path.normpath(found if found.is_absolute() else Path(project) / found))


def by_check(data, check):
    return [f for f in data["findings"] if f["check"] == check]


def warn_lines(text):
    """{check: [(caminho, resto)]} das linhas AVISO do texto."""
    lines = {}
    for line in text.splitlines():
        match = WARN_LINE_RE.match(line.strip())
        if match:
            lines.setdefault(match.group(1), []).append((match.group(2), match.group(3)))
    return lines


class DoctorTestCase(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox(self)
        self.versions = plugin_versions()

    def assert_path(self, finding, *candidates):
        found = reported(finding["path"], self.sandbox.project)
        expected = {Path(os.path.normpath(c)) for c in candidates}
        self.assertIn(found, expected, f"caminho do achado {finding['path']!r} não é nenhum de {sorted(expected)}")


# ---------------------------------------------------------------- UT-01

class UpToDateTest(DoctorTestCase):
    def test_nothing_to_report_gives_empty_findings_plugin_versions_and_only_ok_lines(self):
        """SPEC-0061:UT-01"""
        self.sandbox.up_to_date_project()
        self.assertFalse(self.sandbox.user_skills.exists())
        data = run_doctor(self, self.sandbox)
        self.assertEqual(data["findings"], [], json.dumps(data, ensure_ascii=False, indent=1))
        self.assertEqual(data.get("plugin_versions"), self.versions)

        text = run_doctor(self, self.sandbox, as_json=False)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        self.assertTrue(lines, "o texto não tem nenhuma linha")
        for line in lines:
            self.assertTrue(line.startswith("OK "), f"linha que não é OK: {line!r}")
        for check in CHECKS:
            self.assertTrue(any(check in line for line in lines), f"sem linha OK para {check}:\n{text}")


# ---------------------------------------------------------------- UT-02

class OldNameCopyTest(DoctorTestCase):
    def test_old_name_copies_in_user_and_project_skills(self):
        """SPEC-0061:UT-02"""
        self.sandbox.up_to_date_project()
        user_copy = skill_copy(self.sandbox.user_skills, "sdd-management")
        project_copy = skill_copy(self.sandbox.project_skills, "org-atlas")
        expected = {"gluon-spec": user_copy, "boson-atlas": project_copy}

        for label, kwargs in (("--project", {}), ("cwd", {"project": False, "cwd": self.sandbox.project})):
            with self.subTest(projeto=label):
                data = run_doctor(self, self.sandbox, **kwargs)
                findings = by_check(data, "old-name-copy")
                self.assertEqual(len(findings), 2, json.dumps(data, ensure_ascii=False, indent=1))
                self.assertEqual([f["check"] for f in data["findings"]], ["old-name-copy"] * 2)
                for new, folder in expected.items():
                    finding = [f for f in findings if new in f["detail"] + " " + f["fix"]]
                    self.assertEqual(len(finding), 1, f"nenhum achado cita {new}: {findings}")
                    self.assert_path(finding[0], folder, folder / "SKILL.md")

        lines = warn_lines(run_doctor(self, self.sandbox, as_json=False)).get("old-name-copy", [])
        self.assertEqual(len(lines), 2, lines)
        for new, folder in expected.items():
            matching = [rest for path, rest in lines if reported(path, self.sandbox.project) in
                        {folder, folder / "SKILL.md"}]
            self.assertEqual(len(matching), 1, f"linha AVISO de {folder} ausente: {lines}")
            self.assertIn(new, matching[0])

    def test_home_skills_are_used_only_without_claude_config_dir(self):
        """SPEC-0061:UT-02 (pasta do usuário: $CLAUDE_CONFIG_DIR/skills, senão $HOME/.claude/skills)"""
        self.sandbox.up_to_date_project()
        home_copy = skill_copy(self.sandbox.home / ".claude" / "skills", "second-brain")
        with self.subTest(caso="com CLAUDE_CONFIG_DIR: o HOME não é conferido"):
            self.assertEqual(run_doctor(self, self.sandbox)["findings"], [])
        with self.subTest(caso="sem CLAUDE_CONFIG_DIR: $HOME/.claude/skills"):
            env = {k: v for k, v in self.sandbox.env.items() if k != "CLAUDE_CONFIG_DIR"}
            findings = by_check(run_doctor(self, self.sandbox, env=env), "old-name-copy")
            self.assertEqual(len(findings), 1, findings)
            self.assert_path(findings[0], home_copy, home_copy / "SKILL.md")
            self.assertIn("photon-brain", findings[0]["detail"] + " " + findings[0]["fix"])

    def test_old_name_folder_without_skill_md_is_not_reported(self):
        """SPEC-0061:UT-02 (só conta <pasta>/<nome antigo>/SKILL.md)"""
        self.sandbox.up_to_date_project()
        skill_copy(self.sandbox.user_skills, "second-brain", with_skill_md=False)
        write(self.sandbox.user_skills / "org-atlas" / "README.md", "sem SKILL.md\n")
        self.assertEqual(run_doctor(self, self.sandbox)["findings"], [])


# ---------------------------------------------------------------- UT-03

def fake_plugin(root, versions):
    """Cópia mínima do plugin: o doctor real em scripts/ e as três CLIs só com a constante de versão."""
    root = Path(root)
    (root / "scripts").mkdir(parents=True)
    if DOCTOR.is_file():
        shutil.copy2(DOCTOR, root / "scripts" / DOCTOR.name)
    plugin_json = REPO / ".claude-plugin" / "plugin.json"
    if plugin_json.is_file():
        write(root / ".claude-plugin" / "plugin.json", plugin_json.read_text(encoding="utf-8"))
    for skill, version in versions.items():
        script, _ = SKILL_SCRIPTS[skill]
        write(root / "skills" / skill / "scripts" / script, version_line(skill, version))
        write(root / "skills" / skill / "SKILL.md", f"---\nname: {skill}\ndescription: x\n---\n")
    return root


class StaleCopyTest(DoctorTestCase):
    def test_only_the_older_copy_is_reported(self):
        """SPEC-0061:UT-03"""
        self.sandbox.up_to_date_project()
        stale = skill_copy(self.sandbox.user_skills, "gluon-spec", LOW_VERSION)
        skill_copy(self.sandbox.user_skills, "photon-brain", self.versions["photon-brain"])
        data = run_doctor(self, self.sandbox)
        findings = by_check(data, "stale-copy")
        self.assertEqual(len(findings), 1, json.dumps(data, ensure_ascii=False, indent=1))
        self.assertEqual(len(data["findings"]), 1, data["findings"])
        finding = findings[0]
        self.assert_path(finding, stale, stale / "scripts" / "spec_graph.py")
        self.assertIn(LOW_VERSION, finding["detail"])
        self.assertIn(self.versions["gluon-spec"], finding["detail"])
        self.assertIn(str(Path("skills") / "gluon-spec"), finding["fix"])

        lines = warn_lines(run_doctor(self, self.sandbox, as_json=False))
        self.assertEqual(len(lines.get("stale-copy", [])), 1, lines)
        self.assertIn(LOW_VERSION, lines["stale-copy"][0][1])

    def test_versions_compare_as_integer_tuples(self):
        """SPEC-0061:UT-03 (2026.10.10 é maior que 2026.10.9; cópia mais nova que o plugin não é aviso)"""
        require_doctor(self)
        plugin = fake_plugin(self.sandbox.base / "plugin", {"gluon-spec": "2026.10.10", "photon-brain": "2026.10.9",
                                                            "boson-atlas": "2026.10.9"})
        versions = plugin_versions(plugin)
        self.sandbox.up_to_date_project(versions)
        stale = skill_copy(self.sandbox.user_skills, "gluon-spec", "2026.10.9")      # menor: aviso
        skill_copy(self.sandbox.user_skills, "photon-brain", "2026.10.10")           # maior: nada
        skill_copy(self.sandbox.project_skills, "boson-atlas", "2026.10.9")          # igual: nada
        data = run_doctor(self, self.sandbox, script=plugin / "scripts" / DOCTOR.name)
        self.assertEqual(data.get("plugin_versions"), versions)
        self.assertEqual([f["check"] for f in data["findings"]], ["stale-copy"],
                         json.dumps(data, ensure_ascii=False, indent=1))
        self.assert_path(data["findings"][0], stale, stale / "scripts" / "spec_graph.py")
        self.assertIn("2026.10.9", data["findings"][0]["detail"])
        self.assertIn("2026.10.10", data["findings"][0]["detail"])


# ---------------------------------------------------------------- UT-04

class StaleProjectTest(DoctorTestCase):
    def test_stale_sdd_tool_old_sdd_block_and_stale_atlas_with_commands(self):
        """SPEC-0061:UT-04 (SPEC-0072:CH-01: o atlas vendorizado na pasta nova, .boson-atlas/skill)"""
        project = self.sandbox.project
        write(project / "tools" / "sdd" / "spec_graph.py", version_line("gluon-spec", LOW_VERSION))
        write(project / "AGENTS.md", sdd_block("sdd-management"))
        write(project / "CLAUDE.md", sdd_block("gluon-spec", "sdd-management"))  # já cita o novo: nada
        write(project / "GEMINI.md", "Antes se chamava sdd-management (fora do bloco).\n")  # sem bloco: nada
        write(project / NEW_COPY_DIR / "skill" / "scripts" / "atlas.py", version_line("boson-atlas", LOW_VERSION))
        write(project / NEW_COPY_DIR / "skill" / "SKILL.md", "---\nname: boson-atlas\ndescription: x\n---\n")

        data = run_doctor(self, self.sandbox)
        dump = json.dumps(data, ensure_ascii=False, indent=1)
        self.assertEqual(sorted(f["check"] for f in data["findings"]),
                         ["old-sdd-block", "stale-atlas", "stale-sdd-tool"], dump)

        tool = by_check(data, "stale-sdd-tool")[0]
        self.assert_path(tool, project / "tools" / "sdd" / "spec_graph.py", project / "tools" / "sdd")
        self.assertIn(LOW_VERSION, tool["detail"])
        self.assertIn(self.versions["gluon-spec"], tool["detail"])
        self.assertIn(str(Path("skills") / "gluon-spec" / "scripts" / "spec_graph.py") + " whats-new", tool["fix"])
        self.assertIn("vendor", tool["fix"].split("whats-new", 1)[1])

        block = by_check(data, "old-sdd-block")[0]
        self.assert_path(block, project / "AGENTS.md")
        self.assertIn("spec_graph.py vendor --agents", block["fix"])

        atlas = by_check(data, "stale-atlas")[0]
        self.assert_path(atlas, project / NEW_COPY_DIR / "skill", project / NEW_COPY_DIR / "skill" / "scripts" /
                         "atlas.py")
        self.assertIn(LOW_VERSION, atlas["detail"])
        self.assertIn(self.versions["boson-atlas"], atlas["detail"])
        self.assertIn(str(Path("skills") / "boson-atlas" / "scripts" / "atlas.py") + " vendor --ci", atlas["fix"])
        self.assertRegex(atlas["fix"], r"github\|generic")

        lines = warn_lines(run_doctor(self, self.sandbox, as_json=False))
        self.assertEqual(sorted(lines), ["old-sdd-block", "stale-atlas", "stale-sdd-tool"], lines)

    def test_plugin_path_with_space_is_shell_quoted_in_the_commands(self):
        """SPEC-0061:UT-04 (Emenda v2: caminho do plugin com espaço vai entre aspas de shell, shlex.quote)"""
        require_doctor(self)
        plugin = fake_plugin(self.sandbox.base / "plugin com espaço", {"gluon-spec": "2026.11.3",
                                                                     "photon-brain": "2026.11.3",
                                                                     "boson-atlas": "2026.11.3"})
        project = self.sandbox.project
        write(project / "tools" / "sdd" / "spec_graph.py", version_line("gluon-spec", LOW_VERSION))
        write(project / "AGENTS.md", sdd_block("sdd-management"))
        write(project / NEW_COPY_DIR / "skill" / "scripts" / "atlas.py", version_line("boson-atlas", LOW_VERSION))
        stale = skill_copy(self.sandbox.user_skills, "gluon-spec", LOW_VERSION)
        data = run_doctor(self, self.sandbox, script=plugin / "scripts" / DOCTOR.name)
        dump = json.dumps(data, ensure_ascii=False, indent=1)
        self.assertEqual(sorted(f["check"] for f in data["findings"]),
                         ["old-sdd-block", "stale-atlas", "stale-copy", "stale-sdd-tool"], dump)
        spec_graph = shlex.quote(str(plugin / "skills" / "gluon-spec" / "scripts" / "spec_graph.py"))
        atlas = shlex.quote(str(plugin / "skills" / "boson-atlas" / "scripts" / "atlas.py"))
        self.assertTrue(spec_graph.startswith("'"), spec_graph)
        self.assertIn(spec_graph + " whats-new", by_check(data, "stale-sdd-tool")[0]["fix"])
        self.assertIn(spec_graph + " vendor --agents", by_check(data, "old-sdd-block")[0]["fix"])
        self.assertIn(atlas + " vendor --ci", by_check(data, "stale-atlas")[0]["fix"])
        self.assertIn(shlex.quote(str(plugin / "skills" / "gluon-spec")), by_check(data, "stale-copy")[0]["fix"])
        self.assert_path(by_check(data, "stale-copy")[0], stale, stale / "scripts" / "spec_graph.py")

    def test_up_to_date_vendored_atlas_and_tools_are_not_reported(self):
        """SPEC-0061:UT-04 (mesma versão do plugin: nada; SPEC-0072:CH-01: na pasta nova)"""
        self.sandbox.up_to_date_project()
        write(self.sandbox.project / NEW_COPY_DIR / "skill" / "scripts" / "atlas.py",
              version_line("boson-atlas", self.versions["boson-atlas"]))
        self.assertEqual(run_doctor(self, self.sandbox)["findings"], [])


# ---------------------------------------------------------------- SPEC-0072 (nomes técnicos antigos)

OLD_BRAIN, NEW_BRAIN = "second" + "-brain", "photon-brain"
OLD_ATLAS, NEW_ATLAS = "org" + "-atlas", "boson-atlas"
CHECKS_BEFORE_0072 = CHECKS[:6]
OVERRIDES = {"brain": "BRAIN_CONFIG_HOME", "atlas": "ATLAS_CONFIG_HOME"}


def copy_command(old, new):
    """O comando de cópia das skills (SPEC-0069 e SPEC-0070)."""
    return f"mkdir -p ~/.config/{new} && cp -p ~/.config/{old}/config.yml ~/.config/{new}/"


class OldNamesCase(DoctorTestCase):
    def setUp(self):
        super().setUp()
        # sem as sobrescritas do ambiente real: a pasta padrão é a do HOME temporário
        self.env = {k: v for k, v in self.sandbox.env.items() if k not in OVERRIDES.values()}

    def config_dir(self, name):
        folder = self.sandbox.home / ".config" / name
        write(folder / "config.yml", "vault: /x\n")
        return folder

    def text_of(self, finding):
        return f"{finding['path']} {finding['detail']} {finding['fix']}"


class OldNamesGuardTest(OldNamesCase):
    def test_nothing_old_keeps_todays_output(self):
        """SPEC-0072:CH-01 (guarda: passa antes da mudança; depois, uma linha OK a mais por checagem nova)"""
        self.sandbox.up_to_date_project()
        self.config_dir(NEW_BRAIN)
        self.config_dir(NEW_ATLAS)
        data = run_doctor(self, self.sandbox, env=self.env)
        self.assertEqual(data["findings"], [], json.dumps(data, ensure_ascii=False, indent=1))
        lines = [line.strip() for line in run_doctor(self, self.sandbox, as_json=False, env=self.env).splitlines()
                 if line.strip()]
        for line in lines:
            self.assertTrue(line.startswith("OK "), line)
        for check in CHECKS_BEFORE_0072:
            self.assertEqual(len([line for line in lines if line.startswith(f"OK {check} ")]), 1, lines)


class OldConfigTest(OldNamesCase):
    def check_pair(self, old, new, kind):
        old_dir = self.config_dir(old)
        with self.subTest(kind=kind, case="só a antiga"):
            found = by_check(run_doctor(self, self.sandbox, env=self.env), "old-config")
            self.assertEqual(len(found), 1, found)
            self.assertIn(old, found[0]["path"])
            self.assertIn(copy_command(old, new), self.text_of(found[0]))
            text = warn_lines(run_doctor(self, self.sandbox, as_json=False, env=self.env))
            self.assertEqual(len(text.get("old-config", [])), 1, text)
        self.config_dir(new)
        with self.subTest(kind=kind, case="as duas"):
            found = by_check(run_doctor(self, self.sandbox, env=self.env), "old-config")
            self.assertEqual(len(found), 1, found)
            self.assertIn("pode apagar", self.text_of(found[0]))
            self.assertNotIn("cp -p", self.text_of(found[0]))
        with self.subTest(kind=kind, case="com a sobrescrita"):
            override = self.sandbox.base / f"{kind}-override"
            override.mkdir()
            env = dict(self.env, **{OVERRIDES[kind]: str(override)})
            self.assertEqual(by_check(run_doctor(self, self.sandbox, env=env), "old-config"), [])
        self.assertEqual(sorted(p.name for p in old_dir.iterdir()), ["config.yml"], "o doctor só lê")

    def test_old_brain_config(self):
        """SPEC-0072:UT-01 (photon-brain)"""
        self.check_pair(OLD_BRAIN, NEW_BRAIN, "brain")

    def test_old_atlas_config(self):
        """SPEC-0072:UT-01 (boson-atlas)"""
        self.check_pair(OLD_ATLAS, NEW_ATLAS, "atlas")

    def test_override_with_only_the_old_folder_gives_no_finding(self):
        """SPEC-0072:UT-01 (BRAIN_CONFIG_HOME e ATLAS_CONFIG_HOME definidos: nenhum achado)"""
        self.config_dir(OLD_BRAIN)
        self.config_dir(OLD_ATLAS)
        env = dict(self.env)
        for kind, name in OVERRIDES.items():
            override = self.sandbox.base / f"{kind}-override"
            override.mkdir()
            env[name] = str(override)
        self.assertEqual(by_check(run_doctor(self, self.sandbox, env=env), "old-config"), [])


class OldAtlasFolderTest(OldNamesCase):
    def test_stale_atlas_in_both_folders_and_old_folder_only_for_the_old_one(self):
        """SPEC-0072:UT-02"""
        projects = {}
        for folder in (OLD_COPY_DIR, NEW_COPY_DIR):
            project = self.sandbox.base / f"projeto{folder}"
            write(project / folder / "skill" / "scripts" / "atlas.py", version_line("boson-atlas", LOW_VERSION))
            projects[folder] = project
        for folder, project in projects.items():
            with self.subTest(folder=folder):
                data = run_doctor(self, self.sandbox, project=project, env=self.env)
                stale = by_check(data, "stale-atlas")
                self.assertEqual(len(stale), 1, data["findings"])
                self.assert_path_in(stale[0], project, folder)
                self.assertIn(LOW_VERSION, stale[0]["detail"])
                old = by_check(data, "old-atlas-folder")
                if folder == OLD_COPY_DIR:
                    self.assertEqual(len(old), 1, data["findings"])
                    self.assert_path_in(old[0], project, folder)
                    self.assertIn("vendor", self.text_of(old[0]))
                    self.assertIn(f"git rm -r {OLD_COPY_DIR}", self.text_of(old[0]))
                else:
                    self.assertEqual(old, [], data["findings"])

    def assert_path_in(self, finding, project, folder):
        found = reported(finding["path"], project)
        self.assertTrue(found == project / folder or (project / folder) in found.parents,
                        f"{finding['path']} fora de {folder}")


# ---------------------------------------------------------------- UT-05

class UnreadableTest(DoctorTestCase):
    def test_copy_without_version_constant_is_unreadable_version(self):
        """SPEC-0061:UT-05 (spec_graph.py copiado sem constante de versão)"""
        self.sandbox.up_to_date_project()
        copy = skill_copy(self.sandbox.user_skills, "gluon-spec")
        write(copy / "scripts" / "spec_graph.py", "#!/usr/bin/env python3\nprint('sem versão')\n")
        data = run_doctor(self, self.sandbox)
        self.assertEqual([f["check"] for f in data["findings"]], ["unreadable-version"],
                         json.dumps(data, ensure_ascii=False, indent=1))
        self.assert_path(data["findings"][0], copy / "scripts" / "spec_graph.py", copy)
        lines = warn_lines(run_doctor(self, self.sandbox, as_json=False))
        self.assertEqual(list(lines), ["unreadable-version"], lines)

    def test_reading_is_limited_to_the_first_256_kb(self):
        """SPEC-0061:UT-05 (Emenda v2: constante depois dos primeiros 256 KB → unreadable-version; no topo → lida)"""
        padding = "# preenchimento para passar dos 256 KB da leitura limitada\n" * (READ_LIMIT // 50 + 200)
        self.assertGreater(len(padding.encode("utf-8")), READ_LIMIT)
        constant = f'SDD_TOOL_VERSION = "{LOW_VERSION}"\n'
        cases = (("constante depois de 256 KB", padding + constant, "unreadable-version"),
                 ("constante no topo", constant + padding, "stale-copy"))
        for label, text, expected in cases:
            with self.subTest(caso=label):
                sandbox = Sandbox(self)
                sandbox.up_to_date_project()
                copy = skill_copy(sandbox.user_skills, "gluon-spec")
                write(copy / "scripts" / "spec_graph.py", text)
                self.assertGreater((copy / "scripts" / "spec_graph.py").stat().st_size, READ_LIMIT)
                data = run_doctor(self, sandbox)
                self.assertEqual([f["check"] for f in data["findings"]], [expected],
                                 json.dumps(data, ensure_ascii=False, indent=1))
                self.assert_path(data["findings"][0], copy, copy / "scripts" / "spec_graph.py")

    @unittest.skipIf(IS_ROOT, "root lê pastas sem permissão (os.geteuid() == 0)")
    def test_skills_folder_without_read_permission_is_ignored(self):
        """SPEC-0061:UT-05 (pasta de skills com chmod 000)"""
        self.sandbox.up_to_date_project()
        skill_copy(self.sandbox.project_skills, "second-brain")
        skill_copy(self.sandbox.project_skills, "gluon-spec", LOW_VERSION)
        self.sandbox.project_skills.chmod(0)
        self.addCleanup(self.sandbox.project_skills.chmod, 0o755)
        for as_json in (True, False):
            with self.subTest(json=as_json):
                result = run_doctor(self, self.sandbox, as_json=as_json)
                if as_json:
                    self.assertEqual(result["findings"], [], result)

    def test_symlink_pointing_outside_the_skills_folder_is_not_followed(self):
        """SPEC-0061:UT-05 (<config>/skills/gluon-spec como link simbólico para fora)"""
        self.sandbox.up_to_date_project()
        outside = skill_copy(self.sandbox.base / "fora", "gluon-spec", LOW_VERSION)
        self.sandbox.user_skills.mkdir(parents=True)
        (self.sandbox.user_skills / "gluon-spec").symlink_to(outside, target_is_directory=True)
        data = run_doctor(self, self.sandbox)
        self.assertEqual(data["findings"], [], json.dumps(data, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- UT-06

def load_rules(test):
    if not RULES.is_file():
        test.fail(f"{RULES.name} não existe")
    spec = importlib.util.spec_from_file_location("fermion_doctor_architecture_rules", RULES)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lines_of(findings):
    return [int(f.split(" — ")[0].rsplit(":", 1)[1]) for f in findings]


class DoctorArchitectureTest(unittest.TestCase):
    """ADR-0019: o doctor só importa a stdlib, não abre processo, não usa rede e não grava, apaga nem move arquivo."""

    def setUp(self):
        self.rules = load_rules(self)

    def test_rules_report_violating_examples(self):
        """SPEC-0061:UT-06 (exemplo que viola cada regra)"""
        imports = ("import json\n"                    # 1
                   "import yaml\n"                    # 2
                   "from requests import get\n"       # 3
                   "from . import vizinho\n"          # 4
                   "import re, os.path\n")            # 5
        self.assertEqual(lines_of(self.rules.import_findings(imports, DOCTOR_NAME)), [2, 3, 4])

        process = ("import subprocess\n"                         # 1
                   "import os\n"                                 # 2
                   "from subprocess import run\n"                # 3
                   "import subprocess as sp\n"                   # 4
                   "os.system('ls')\n"                           # 5
                   "os.popen('ls')\n"                            # 6
                   "os.execv('/bin/ls', ['ls'])\n"               # 7
                   "from os import spawnv\n"                     # 8
                   "import multiprocessing\n"                    # 9
                   "os.getcwd()\n")                              # 10
        found = self.rules.process_findings(process, DOCTOR_NAME)
        self.assertEqual(sorted(set(lines_of(found))), [1, 3, 4, 5, 6, 7, 8, 9], "\n".join(found))

        network = ("import socket\n"                             # 1
                   "import urllib.request\n"                     # 2
                   "from urllib.parse import quote\n"            # 3
                   "import http.client\n"                        # 4
                   "import asyncio\n"                            # 5
                   "asyncio.open_connection('h', 1)\n"           # 6
                   "import json\n")                              # 7
        found = self.rules.network_findings(network, DOCTOR_NAME)
        self.assertEqual(sorted(set(lines_of(found))), [1, 2, 3, 4, 6], "\n".join(found))

        writes = ("from pathlib import Path\n"                   # 1
                  "import os, shutil\n"                          # 2
                  "open('a', 'w')\n"                             # 3
                  "open('a', mode='a')\n"                        # 4
                  "open('a', 'r+')\n"                            # 5
                  "Path('a').write_text('x')\n"                  # 6
                  "Path('a').unlink()\n"                         # 7
                  "shutil.rmtree('a')\n"                         # 8
                  "Path('a').rename('b')\n"                      # 9
                  "os.rename('a', 'b')\n"                        # 10
                  "os.remove('a')\n"                             # 11
                  "os.replace('a', 'b')\n"                       # 12
                  "Path('a').open('wb')\n"                       # 13
                  "Path('a').mkdir()\n"                          # 14
                  "shutil.copy('a', 'b')\n"                      # 15
                  "from os import remove\n"                      # 16
                  "open('a', modo)\n"                            # 17
                  "Path('a').write_bytes(b'')\n"                 # 18
                  "open('a')\n"                                  # 19 leitura
                  "open('a', 'r', encoding='utf-8')\n"           # 20 leitura
                  "Path('a').read_text(encoding='utf-8')\n"      # 21 leitura
                  "Path('a').open(encoding='utf-8')\n"           # 22 leitura
                  "'a-b'.replace('-', '_')\n"                    # 23 texto
                  "[1].remove(1)\n"                              # 24 lista
                  "{}.copy()\n"                                  # 25 dicionário
                  "import sys\n"                                 # 26
                  "sys.stdout.write('ok')\n")                    # 27 stdout
        found = self.rules.write_findings(writes, DOCTOR_NAME)
        self.assertEqual(sorted(set(lines_of(found))), list(range(3, 19)), "\n".join(found))

        dynamic = ("import importlib\n"                          # 1
                   "import runpy\n"                              # 2
                   "exec('x')\n"                                 # 3
                   "__import__('spec_graph')\n"                  # 4
                   "import re\n"                                 # 5
                   "re.compile('x')\n")                          # 6
        found = self.rules.dynamic_code_findings(dynamic, DOCTOR_NAME)
        self.assertEqual(sorted(set(lines_of(found))), [1, 2, 3, 4], "\n".join(found))

    def test_rules_report_the_g4_bypasses(self):
        """SPEC-0061:UT-06 (Emenda v2: getattr de processo, tempfile, ctypes, sqlite3, shelve, dbm, logging.FileHandler)"""
        cases = {
            "process_findings": (("import os\n"
                                 "getattr(os, 'system')('ls')\n"                       # 2
                                 "import subprocess as s\n"                            # 3
                                 "getattr(s, nome)\n"                                  # 4
                                 "getattr(objeto, 'system')\n"), [2, 3, 4]),            # 5: não é módulo de processo
            "write_findings": (("import tempfile\n"                                    # 1
                               "tempfile.mkdtemp()\n"                                 # 2
                               "from tempfile import NamedTemporaryFile\n"            # 3
                               "import sqlite3\n"                                     # 4
                               "import shelve\n"                                      # 5
                               "import dbm.dumb\n"                                    # 6
                               "import logging\n"                                     # 7
                               "logging.FileHandler('x.log')\n"                       # 8
                               "from logging import FileHandler\n"                    # 9
                               "logging.getLogger('x')\n"                             # 10: só lê
                               "import os\n"                                          # 11
                               "getattr(os, 'remove')('x')\n"), [1, 2, 3, 4, 5, 6, 8, 9, 12]),
            "dynamic_code_findings": (("import ctypes\n"                               # 1
                                      "from ctypes import CDLL\n"                     # 2
                                      "import json\n"), [1, 2]),
        }
        for rule, (source, expected) in cases.items():
            with self.subTest(regra=rule):
                found = getattr(self.rules, rule)(source, DOCTOR_NAME)
                self.assertEqual(sorted(set(lines_of(found))), expected, "\n".join(found))
        everything = "\n".join(source for source, _ in cases.values())
        self.assertTrue(self.rules.all_findings(everything, DOCTOR_NAME))

    def test_findings_carry_file_line_and_rule(self):
        """SPEC-0061:UT-06 (formato "<arquivo>:<linha> — <regra> — <achado>")"""
        found = self.rules.all_findings("import json\nimport subprocess\nopen('x', 'w')\n", DOCTOR_NAME)
        self.assertTrue(found)
        for line in found:
            self.assertRegex(line, rf"^{re.escape(DOCTOR_NAME)}:\d+ — .+ — .+$")

    def test_real_doctor_has_no_finding(self):
        """SPEC-0061:UT-06 (código real de scripts/fermion_doctor.py)"""
        require_doctor(self)
        source = DOCTOR.read_text(encoding="utf-8")
        found = self.rules.all_findings(source, DOCTOR_NAME)
        self.assertEqual(found, [], "\n".join(found))



# ---------------------------------------------------------------- SPEC-0068: hook do leak-check quebrado

LEAK_HOOK_TEMPLATE = REPO / "skills" / "gluon-spec" / "assets" / "hooks" / "pre-push-leak"
# Hook das versões antes da SPEC-0057: chama direto o caminho gravado.
OLD_LEAK_HOOK = """#!/bin/sh
# SDD modo privado: recusa o push quando há marcas do SDD (IDs de spec e ADR, tags de teste, seções, caminho do spec_root).
# Instalado por `spec_graph.py private init` em .git/hooks (não versionado). Escape do próprio git: git push --no-verify
zero=$(git hash-object --stdin </dev/null | tr '0-9a-f' '0')
status=0
while read -r local_ref local_sha remote_ref remote_sha; do
  [ "$local_sha" = "$zero" ] && continue
  "__PYTHON__" "__SDD_TOOL__" leak-check --range "$remote_sha..$local_sha" --branch "${remote_ref#refs/heads/}" || status=1
done
[ "$status" -eq 0 ] || echo "pre-push: marcas do SDD encontradas — remova-as antes de enviar ao time" >&2
exit $status
"""


def leak_hook(git_dir, tool, template=None):
    """<git_dir>/hooks/pre-push com as substituições do `private init` (template atual ou OLD_LEAK_HOOK)."""
    text = template if template is not None else LEAK_HOOK_TEMPLATE.read_text(encoding="utf-8")
    return write(Path(git_dir) / "hooks" / "pre-push",
                 text.replace("__PYTHON__", sys.executable).replace("__SDD_TOOL__", str(tool)))


class BrokenLeakHookTest(DoctorTestCase):
    """SPEC-0068: o doctor acusa o pre-push do leak-check que aponta para ferramenta inexistente (só avisa).

    Contrato: o doctor não roda processos (nem git); lê <projeto>/.git — pasta, ou arquivo "gitdir: <caminho>" de
    worktree, seguindo o arquivo `commondir` quando existe — e confere <git common dir>/hooks/pre-push. O hook é do
    SDD quando a 2ª linha começa com "# SDD modo privado: recusa o push". Caminho gravado: o valor de
    `recorded="..."` (template atual) ou, no hook antigo, o 2º trecho entre aspas da linha que chama `leak-check`.
    Achado `broken-leak-hook` quando o caminho gravado não existe e nenhuma alternativa da busca do hook existe
    (plugin fermion do installed_plugins.json, cópias de skill do usuário, tools/sdd/ não rastreado); `path` = o
    hook (ou a pasta hooks); `fix` contém "private hooks --refresh". Hook de outra origem nunca é achado.
    """

    def missing_tool(self):
        return self.sandbox.base / "sumiu" / "skills" / "gluon-spec" / "scripts" / "spec_graph.py"

    def assert_broken(self, hook):
        data = run_doctor(self, self.sandbox)
        findings = by_check(data, "broken-leak-hook")
        self.assertEqual(len(findings), 1, json.dumps(data, ensure_ascii=False, indent=1))
        self.assert_path(findings[0], hook, hook.parent)
        self.assertIn("private hooks --refresh", findings[0]["fix"])
        lines = warn_lines(run_doctor(self, self.sandbox, as_json=False)).get("broken-leak-hook", [])
        self.assertEqual(len(lines), 1, lines)

    def assert_nothing(self):
        data = run_doctor(self, self.sandbox)
        self.assertEqual(by_check(data, "broken-leak-hook"), [], json.dumps(data, ensure_ascii=False, indent=1))

    def test_sdd_hook_with_a_missing_tool_is_reported(self):
        """SPEC-0068:UT-01 (doctor: template atual e hook antigo, caminho gravado inexistente, nada no config)"""
        git_dir = self.sandbox.project / ".git"
        for label, template in (("atual", None), ("antigo", OLD_LEAK_HOOK)):
            with self.subTest(hook=label):
                hook = leak_hook(git_dir, self.missing_tool(), template)
                self.assert_broken(hook)

    def test_hook_in_the_common_dir_of_a_worktree_is_reported(self):
        """SPEC-0068:UT-01 (doctor: .git arquivo `gitdir:` de worktree, hooks na pasta comum)"""
        main_git = self.sandbox.base / "principal" / ".git"
        worktree_git = main_git / "worktrees" / "projeto"
        write(worktree_git / "commondir", "../..\n")
        write(worktree_git / "HEAD", "ref: refs/heads/x\n")
        write(self.sandbox.project / ".git", f"gitdir: {worktree_git}\n")
        hook = leak_hook(main_git, self.missing_tool())
        self.assert_broken(hook)

    def test_existing_tool_or_foreign_hook_is_not_reported(self):
        """SPEC-0068:UT-01 (doctor: ferramenta gravada existe, ou pre-push de outra origem)"""
        git_dir = self.sandbox.project / ".git"
        tool = write(self.sandbox.base / "ferramenta" / "spec_graph.py", version_line("gluon-spec", LOW_VERSION))
        for label, template in (("atual", None), ("antigo", OLD_LEAK_HOOK)):
            with self.subTest(hook=label):
                leak_hook(git_dir, tool, template)
                self.assert_nothing()
        with self.subTest(hook="outra origem"):
            write(git_dir / "hooks" / "pre-push", "#!/bin/sh\necho time\n")
            self.assert_nothing()



class BrokenLeakHookIndexTest(DoctorTestCase):
    """SPEC-0068 Emenda v3: o doctor só aceita tools/sdd/spec_graph.py como alternativa quando NÃO é rastreado,
    lendo o índice v2/v3 com o nome ancorado na entrada (índice v4, ilegível ou grande: não aceita). Os testes
    preparam o repositório com git; o doctor em si não roda processos."""

    def setUp(self):
        super().setUp()
        self.git_env = dict(self.sandbox.env, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                            GIT_COMMITTER_EMAIL="t@t")
        self.git("init", "-q", "-b", "main")
        write(self.sandbox.project / "README.md", "# projeto\n")
        self.missing = self.sandbox.base / "sumiu" / "skills" / "gluon-spec" / "scripts" / "spec_graph.py"
        self.hook = leak_hook(self.sandbox.project / ".git", self.missing)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.sandbox.project, env=self.git_env, capture_output=True,
                              text=True, timeout=DOCTOR_TIMEOUT, check=True).stdout

    def commit(self, *paths):
        self.git("add", "--", *paths)
        self.git("commit", "-qm", "x")

    def findings(self):
        data = run_doctor(self, self.sandbox)
        return by_check(data, "broken-leak-hook"), json.dumps(data, ensure_ascii=False, indent=1)

    def test_tracked_tool_in_an_index_v4_is_not_an_alternative(self):
        """SPEC-0068:UT-01 (Emenda v3: índice v4 com tools/sdd rastreado → achado)"""
        write(self.sandbox.project / "tools" / "sdd" / "README.md", "ferramenta\n")
        write(self.sandbox.project / "tools" / "sdd" / "spec_graph.py", "print('x')\n")
        self.commit("README.md", "tools")
        self.git("update-index", "--index-version", "4")
        self.assertEqual(self.git("update-index", "--show-index-version").strip(), "4")
        found, data = self.findings()
        self.assertEqual(len(found), 1, data)
        self.assert_path(found[0], self.hook, self.hook.parent)

    def test_untracked_tool_with_an_index_v2_is_an_alternative(self):
        """SPEC-0068:UT-01 (Emenda v3: índice v2, tools/sdd não rastreado → sem achado)"""
        self.commit("README.md")
        self.git("update-index", "--index-version", "2")
        write(self.sandbox.project / "tools" / "sdd" / "spec_graph.py", "print('x')\n")
        found, data = self.findings()
        self.assertEqual(found, [], data)

    def test_tracked_path_that_only_ends_with_the_tool_name_is_not_confused(self):
        """SPEC-0068:UT-01 (Emenda v3: x/tools/sdd rastreado não faz o tools/sdd não rastreado parecer rastreado)"""
        write(self.sandbox.project / "x" / "tools" / "sdd" / "spec_graph.py", "print('x')\n")
        self.commit("README.md", "x")
        self.git("update-index", "--index-version", "2")
        write(self.sandbox.project / "tools" / "sdd" / "spec_graph.py", "print('x')\n")
        self.assertEqual(self.git("ls-files").split(), ["README.md", "x/tools/sdd/spec_graph.py"])
        found, data = self.findings()
        self.assertEqual(found, [], data)

    def test_valid_fermion_plugin_is_an_alternative(self):
        """SPEC-0068:UT-01 (plugin fermion válido no installed_plugins.json → sem achado)"""
        self.commit("README.md")
        install = self.sandbox.base / "cache" / "fermion" / "9.9.9"
        write(install / "skills" / "gluon-spec" / "scripts" / "spec_graph.py", version_line("gluon-spec", LOW_VERSION))
        write(self.sandbox.config / "plugins" / "installed_plugins.json", json.dumps(
            {"version": 2, "plugins": {"fermion@fermion-lab": [{"scope": "user", "installPath": str(install),
                                                                "version": "x"}]}}))
        found, data = self.findings()
        self.assertEqual(found, [], data)


# ---------------------------------------------------------------- IT-01

def snapshot(*roots):
    """{caminho: (conteúdo, mtime_ns)} de todo arquivo e {caminho: None} de toda pasta, sem seguir links."""
    state = {}
    for root in roots:
        for folder, dirs, files in os.walk(root):
            state[folder] = None
            for name in dirs:
                path = os.path.join(folder, name)
                if os.path.islink(path):
                    state[path] = ("link", os.readlink(path))
            for name in files:
                path = os.path.join(folder, name)
                info = os.lstat(path)
                content = os.readlink(path) if os.path.islink(path) else Path(path).read_bytes()
                state[path] = (content, info.st_mtime_ns)
    return state


class DoctorProcessTest(DoctorTestCase):
    def test_real_process_reports_and_changes_nothing_in_under_one_second(self):
        """SPEC-0061:IT-01"""
        require_doctor(self)
        project = self.sandbox.project
        real_spec_graph = (REPO / "skills" / "gluon-spec" / "scripts" / "spec_graph.py").read_text(encoding="utf-8")
        reduced, count = re.subn(r'^SDD_TOOL_VERSION = "[^"]+"', f'SDD_TOOL_VERSION = "{LOW_VERSION}"',
                                 real_spec_graph, flags=re.MULTILINE)
        self.assertEqual(count, 1)
        write(project / "tools" / "sdd" / "spec_graph.py", reduced)
        write(project / "AGENTS.md", sdd_block("gluon-spec"))
        old_copy = skill_copy(self.sandbox.user_skills, "second-brain")
        before = snapshot(project, self.sandbox.config, self.sandbox.home)

        argv = [sys.executable, str(DOCTOR), "--project", str(project), "--json"]
        started = time.monotonic()
        result = subprocess.run(argv, cwd=str(self.sandbox.base), env=self.sandbox.env, capture_output=True,
                                text=True, timeout=DOCTOR_TIMEOUT, check=False)
        elapsed = time.monotonic() - started

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(elapsed, 1.0, f"o doctor levou {elapsed:.2f} s")
        data = json.loads(result.stdout)
        checks = sorted(f["check"] for f in data["findings"])
        self.assertEqual(checks, ["old-name-copy", "stale-sdd-tool"], result.stdout)
        self.assert_path(by_check(data, "old-name-copy")[0], old_copy, old_copy / "SKILL.md")
        self.assertIn(LOW_VERSION, by_check(data, "stale-sdd-tool")[0]["detail"])
        self.assertEqual(snapshot(project, self.sandbox.config, self.sandbox.home), before,
                         "o doctor mudou, criou ou apagou arquivo")


# ---------------------------------------------------------------- E2E-01

REDIRECT_ENV_RE = re.compile(r"^(?:CLAUDE_CODE_PLUGIN_|CLAUDE_PLUGIN_|CLAUDE_CONFIG_DIR$|CLAUDE_[A-Z_]*"
                             r"(?:PLUGIN|MARKETPLACE)|XDG_(?:CONFIG|DATA|CACHE|STATE)_HOME$)")


def isolated_claude_env(tmp):
    """(env, home, config, work) com HOME, CLAUDE_CONFIG_DIR e XDG_CONFIG_HOME temporários (SPEC-0053:E2E-01)."""
    home, config, work = Path(tmp) / "home", Path(tmp) / "config", Path(tmp) / "work"
    for folder in (home, config, work):
        folder.mkdir()
    env = {k: v for k, v in os.environ.items() if not REDIRECT_ENV_RE.match(k)}
    isolated = {"HOME": str(home), "CLAUDE_CONFIG_DIR": str(config), "XDG_CONFIG_HOME": str(home / ".config"),
                "CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL": "1",
                "ATLAS_CONFIG_HOME": str(Path(tmp) / "atlas-config"),
                "BRAIN_CONFIG_HOME": str(Path(tmp) / "brain-config"),
                "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    env.update(isolated)
    real_home = Path(os.environ.get("HOME") or Path.home()).resolve()
    real_config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or real_home / ".claude").resolve()
    assert config.resolve() != real_config
    assert not config.resolve().is_relative_to(real_home), f"{config} dentro do HOME real {real_home}"
    assert Path(env["HOME"]).resolve() != real_home
    return env, home, config, work


class OldInstallJourneyTest(unittest.TestCase):
    def test_warning_appears_in_session_context_and_goes_away_after_the_fix(self):
        """SPEC-0061:E2E-01 [jornada: atualização de instalação antiga]"""
        claude = shutil.which("claude")
        if not claude:
            self.skipTest("Claude Code CLI (claude) não está no PATH; E2E-01 roda localmente no G4 e no G5")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            env, _, config, work = isolated_claude_env(tmp)

            def claude_run(*args, cwd=work):
                return subprocess.run([claude, "plugin", *args], cwd=cwd, env=env, capture_output=True, text=True,
                                      timeout=300, check=False)

            def ok(result):
                self.assertEqual(result.returncode, 0, f"{result.args}\n{result.stdout}\n{result.stderr}")
                return result.stdout

            ok(claude_run("marketplace", "add", str(REPO), "--scope", "user", "--json"))
            ok(claude_run("install", "fermion@fermion-lab", "--scope", "user", "--json"))
            installed = {p.get("id"): p for p in json.loads(ok(claude_run("list", "--json")))}
            self.assertIn("fermion@fermion-lab", installed, installed)
            install_path = Path(installed["fermion@fermion-lab"].get("installPath", ""))
            self.assertTrue(install_path.resolve().is_relative_to(config.resolve()),
                            f"cache fora da configuração isolada: {install_path}")
            self.assertTrue((install_path / "scripts" / DOCTOR.name).is_file(),
                            f"a cópia instalada não traz {DOCTOR_NAME}")

            old_copy = skill_copy(config / "skills", "org-atlas")
            project = tmp / "projeto"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, env=env, check=True, capture_output=True)

            hooks = json.loads((install_path / "hooks" / "hooks.json").read_text(encoding="utf-8"))
            entry = hooks["hooks"]["SessionStart"][0]["hooks"][0]
            command = shutil.which(entry["command"], path=env.get("PATH"))
            self.assertIsNotNone(command, f"{entry['command']} não está no PATH")
            args = [a.replace("${CLAUDE_PLUGIN_ROOT}", str(install_path)) for a in entry.get("args", [])]
            stdin = json.dumps({"session_id": "e2e-0061", "hook_event_name": "SessionStart", "source": "startup",
                                "cwd": str(project)})
            hook_env = {**env, "CLAUDE_PLUGIN_ROOT": str(install_path), "CLAUDE_PROJECT_DIR": str(project)}

            def session_context():
                result = subprocess.run([command, *args], input=stdin, cwd=project, env=hook_env,
                                        capture_output=True, text=True, timeout=entry.get("timeout", 30),
                                        check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                if not result.stdout.strip():
                    return ""
                return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

            context = session_context()
            self.assertIn(HOOK_HEADER, context)
            block = context[context.index(HOOK_HEADER):]
            self.assertIn(str(old_copy), block, "o aviso não mostra o caminho da cópia antiga")
            self.assertIn("boson-atlas", block)
            self.assertIn("remova", block.lower())

            shutil.rmtree(old_copy)  # a instrução do aviso
            self.assertNotIn(HOOK_HEADER, session_context())


if __name__ == "__main__":
    unittest.main()
