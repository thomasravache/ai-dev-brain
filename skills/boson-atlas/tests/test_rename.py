"""boson-atlas com o nome novo: configuração local com leitura dupla, pasta .boson-atlas no atlas e textos
(SPEC-0070: UT-01 a UT-08, IT-01 e IT-02; ADR-0020).

Contrato (seção 6 da spec) que os testes fixam:
    local_config_path(config_home=None) -> Path (leitura, primeiro que existir):
        config_home | $ATLAS_CONFIG_HOME -> DIR/config.yml (sem reserva)
        ~/.config/boson-atlas/config.yml
        ~/.config/<antigo>/config.yml (reserva até a SPEC-0073)
        nenhum -> ~/.config/boson-atlas/config.yml
    local_config_write_path(config_home=None) -> Path (gravação): DIR/config.yml da sobrescrita, senão sempre
        ~/.config/boson-atlas/config.yml, com a configuração completa; a pasta antiga nunca é gravada, movida nem
        apagada. O atlas.py não tem `config set`: quem grava é init e init --join (UT-03 usa init --join).
    NOT_CONFIGURED: "boson-atlas não configurado nesta máquina — rode init (ou init --join)"
    --version: "boson-atlas <ATLAS_VERSION>"; --help, cabeçalho do config.yml local, a saída de `config`,
        assets/atlas-config.yml e assets/ci/* dizem boson-atlas (nunca o nome antigo) e rodam .boson-atlas/skill.
    SKILL_COPIES = (".boson-atlas/skill", ".<antigo>/skill"): lint/build/scan e a checagem de cópia desatualizada
        tratam as duas do mesmo jeito (a cópia da ferramenta nunca é conteúdo do atlas).
    vendor --ci github|generic [--force]:
        arquivo de CI ausente ou regravado -> grava .boson-atlas/skill/ e a CI aponta para ela; com .<antigo>/ no
            atlas imprime CAN_DELETE_OLD (abaixo); nunca apaga nada.
        arquivo de CI mantido (sem --force) que roda .<antigo>/skill -> atualiza .<antigo>/skill/ (e não cria
            .boson-atlas/) e imprime still_runs_old(<ci>).
        instrução final: COMMIT_HINT.
    doctor (texto e --json, mesmo formato e exit code):
        só a antiga -> AVISO com OLD_COPY_CMD; as duas -> AVISO com OLD_IGNORED; sobrescrita -> nenhum aviso de
        caminho antigo; atlas com .<antigo>/ -> AVISO com o passo de migração do vendor ("vendor", "--force" e
        "git rm -r .<antigo>").
      Os testes conferem "<item> — <detalhe>" de cada linha AVISO, então vale o texto inteiro no detalhe ou dividido
      entre item e detalhe.

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox); nos casos da pasta padrão, sem
ATLAS_CONFIG_HOME (Sandbox.run_default, ou os.environ trocado só durante a chamada em processo). O nome antigo está
só em OLD_CONFIG_DIR (helpers). A "máquina da versão anterior" é montada gravando a configuração via
ATLAS_CONFIG_HOME=<HOME>/.config/<antigo>, que é onde a versão anterior gravava por padrão, e a cópia antiga da
skill é plantada em .<antigo>/skill/ (o que o vendor da versão anterior gravava). Sem rede.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import (
    NEW_CONFIG_DIR,
    NEW_SKILL_COPY,
    NOT_CONFIGURED,
    OLD_CONFIG_DIR,
    OLD_SKILL_COPY,
    SCRIPT,
    SKILL,
    Sandbox,
    atlas,
    doctor_lines,
    fn,
    output,
    snapshot,
)

SPEC = "SPEC-0070"
CI_ASSETS = SKILL / "assets" / "ci"
CI_FILES = {"github": Path(".github/workflows/atlas-scan.yml"), "generic": Path("ci/atlas-scan.sh")}
NEW_CALL = f"python3 {NEW_SKILL_COPY}/scripts/atlas.py"
OLD_CALL = f"python3 {OLD_SKILL_COPY}/scripts/atlas.py"
OLD_DIR = f".{OLD_CONFIG_DIR}"  # a pasta antiga no atlas
NEW_DIR = f".{NEW_CONFIG_DIR}"
OLD_COPY_CMD = (f"mkdir -p ~/.config/{NEW_CONFIG_DIR} && cp -p ~/.config/{OLD_CONFIG_DIR}/config.yml "
                f"~/.config/{NEW_CONFIG_DIR}/")
OLD_IGNORED = f"~/.config/{OLD_CONFIG_DIR} é ignorada"
CAN_DELETE_OLD = f"pode apagar {OLD_DIR}/ (git rm -r {OLD_DIR}) depois que a CI rodar com {NEW_DIR}/"
COMMIT_HINT = f"Faça commit de {NEW_DIR}/ (ou {OLD_DIR}/) e do arquivo da CI"
MIGRATION_STEP = f"git rm -r {OLD_DIR}"
HAS_GIT = shutil.which("git") is not None


def still_runs_old(ci: str) -> str:
    return (f"a CI ainda roda {OLD_SKILL_COPY} — para migrar: vendor --ci {ci} --force e depois "
            f"git rm -r {OLD_DIR}")


def joined(rows) -> list:
    """"<status> <item> — <detalhe>" de cada (status, item, detalhe)."""
    return [f"{status} {item} — {detail}" for status, item, detail in rows]


def json_rows(text: str) -> list:
    return [(c["status"], c["item"], c["detail"]) for c in json.loads(text)["checks"]]


def facts_config(mode="repo") -> str:
    """atlas-config.yml com o coletor generic lendo {atlas}/facts/services.json (o {skill} é a skill que roda)."""
    command = ["python3", "{skill}/assets/collectors/generic.py", "--facts", "{atlas}/facts/services.json",
               "--category", "runtime", "--source", "facts"]
    return (f"version: 1\norganization: Acme\nmode: {mode}\nlanguage: auto\nstale_days: 14\n"
            "categories: [code, delivery]\ncollectors:\n  - id: facts\n    category: runtime\n"
            "    command: [" + ", ".join(json.dumps(a) for a in command) + "]\n    timeout: 60\n"
            "redaction: {extra_patterns: []}\n")


def write_facts(atlas_dir: Path) -> None:
    folder = atlas_dir / "facts"
    folder.mkdir(exist_ok=True)
    facts = {"entities": [{"kind": "service", "id": "payments-api", "name": "payments-api", "attrs": {}},
                          {"kind": "datastore", "id": "payments-db", "name": "payments-db", "attrs": {}}],
             "relations": [{"from": "service:payments-api", "to": "datastore:payments-db", "type": "writes"}]}
    (folder / "services.json").write_text(json.dumps(facts), encoding="utf-8")


def plant_copy(atlas_dir: Path, copy: str, outdated=False) -> Path:
    """A cópia da skill que o vendor grava (scripts/atlas.py e assets/), plantada em <atlas>/<copy>/; `outdated`
    simula a cópia de uma versão anterior da skill (só o atlas.py difere)."""
    root = atlas_dir / copy
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    text = SCRIPT.read_text(encoding="utf-8")
    if outdated:
        text = text.replace('ATLAS_VERSION = "', 'ATLAS_VERSION = "0.', 1) + "\n# versão anterior da skill\n"
    (root / "scripts" / "atlas.py").write_text(text, encoding="utf-8")
    shutil.copytree(SKILL / "assets", root / "assets", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return root


def old_generated_script() -> str:
    """ci/atlas-scan.sh como a versão anterior gerava: o modelo rodando a cópia antiga."""
    text = (CI_ASSETS / "atlas-scan.sh").read_text(encoding="utf-8")
    return text.replace(NEW_SKILL_COPY, OLD_SKILL_COPY).replace(f"# {NEW_CONFIG_DIR}", f"# {OLD_CONFIG_DIR}")


def custom_ci(kind: str) -> str:
    """Arquivo de CI personalizado pelo time que ainda roda a cópia antiga."""
    if kind == "generic":
        return old_generated_script() + "# passo extra do time\n"
    return ("# workflow do time (personalizado)\nname: atlas-scan\non:\n  workflow_dispatch:\n"
            "jobs:\n  scan:\n    runs-on: ubuntu-latest\n    steps:\n"
            f"      - run: {OLD_CALL} init --join --atlas \"$PWD\"\n"
            f"      - run: {OLD_CALL} scan\n"
            f"      - run: {OLD_CALL} lint\n")


class RenameCase(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.old = self.box.default_dir(OLD_CONFIG_DIR)
        self.new = self.box.default_dir(NEW_CONFIG_DIR)

    def assertExit(self, result, code):
        self.assertEqual(result.returncode, code, output(result))
        self.assertNotIn("Traceback", output(result))

    def default_env(self, **extra) -> dict:
        """os.environ do teste em processo: HOME e XDG temporários, sem ATLAS_CONFIG_HOME (salvo `extra`)."""
        env = {k: v for k, v in os.environ.items() if k != "ATLAS_CONFIG_HOME"}
        env.update(HOME=str(self.box.home), XDG_CONFIG_HOME=str(self.box.home / ".config"), **extra)
        return env

    def resolve(self, config_home=None, **extra):
        read, write = fn("local_config_path", SPEC), fn("local_config_write_path", SPEC)
        with mock.patch.dict(os.environ, self.default_env(**extra), clear=True):
            return read(config_home), write(config_home)

    @staticmethod
    def put(folder: Path, text="atlas: /x\n") -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.yml").write_text(text, encoding="utf-8")
        return folder / "config.yml"

    def new_atlas(self, config_home=None, mode="repo", path=None):
        """Atlas novo criado por init (configuração em `config_home`, padrão a do Sandbox) com o coletor generic."""
        target = path or self.box.atlas
        target.mkdir(parents=True, exist_ok=True)
        self.assertExit(self.box.init(atlas=target, mode=mode, config_home=config_home), 0)
        (target / "atlas-config.yml").write_text(facts_config(mode), encoding="utf-8")
        write_facts(target)
        return target

    def old_machine(self, copy=True):
        """Máquina configurada pela versão anterior: config.yml só em ~/.config/<antigo>; atlas real com o coletor
        generic e, com `copy`, a cópia da skill em .<antigo>/skill/ (como o vendor anterior gravava)."""
        self.new_atlas(config_home=self.old)
        self.assertTrue((self.old / "config.yml").is_file(), "fixture: init não gravou a configuração antiga")
        self.assertFalse(self.new.exists(), "fixture: a pasta nova não deveria existir")
        if copy:
            plant_copy(self.box.atlas, OLD_SKILL_COPY)
        return self.old / "config.yml"


# ---------------------------------------------------------------- resolução (UT-01, UT-02, UT-04)

class ResolutionTest(RenameCase):
    def test_reads_the_old_folder_alone_and_the_new_one_when_both_exist(self):
        """SPEC-0070:UT-01"""
        old = self.put(self.old)
        self.assertEqual(self.resolve()[0], old, "só a antiga: a leitura usa a antiga como reserva")
        new = self.put(self.new)
        self.assertEqual(self.resolve()[0], new, "as duas: vale a nova")

    def test_without_any_folder_read_and_write_point_to_the_new_folder(self):
        """SPEC-0070:UT-02"""
        expected = self.box.home / ".config" / NEW_CONFIG_DIR / "config.yml"
        self.assertEqual(self.resolve(), (expected, expected))

    def test_write_path_is_always_the_new_folder_even_with_only_the_old_one(self):
        """SPEC-0070:UT-03 (resolução da gravação)"""
        self.put(self.old)
        read, write = self.resolve()
        self.assertEqual(read, self.old / "config.yml")
        self.assertEqual(write, self.new / "config.yml", "a gravação nunca vai para a pasta antiga")

    def test_override_uses_only_its_folder_without_fallback(self):
        """SPEC-0070:UT-04"""
        self.put(self.old)
        self.put(self.new)
        override = self.box.root / "override"
        expected = override / "config.yml"
        with self.subTest(via="ATLAS_CONFIG_HOME"):
            self.assertEqual(self.resolve(ATLAS_CONFIG_HOME=str(override)), (expected, expected),
                             "sobrescrita sem config.yml não cai na reserva")
        with self.subTest(via="config_home"):
            self.assertEqual(self.resolve(config_home=override), (expected, expected))
        with self.subTest(via="config_home vence ATLAS_CONFIG_HOME"):
            other = self.box.root / "other"
            self.assertEqual(self.resolve(config_home=override, ATLAS_CONFIG_HOME=str(other)),
                             (expected, expected))


# ---------------------------------------------------------------- gravação (UT-02, UT-03, UT-04)

class WriteTest(RenameCase):
    def test_init_on_a_machine_without_configuration_creates_only_the_new_folder(self):
        """SPEC-0070:UT-02"""
        out = self.box.run_default("config")
        self.assertExit(out, 3)
        self.assertIn(NOT_CONFIGURED, output(out))
        self.box.atlas.mkdir(parents=True)
        out = self.box.run_default("init", "--atlas", self.box.atlas, "--org", "Acme", "--mode", "repo")
        self.assertExit(out, 0)
        self.assertIn(f"Configuração local: {self.new / 'config.yml'}", out.stdout)
        self.assertEqual(sorted(p.name for p in (self.box.home / ".config").iterdir()), [NEW_CONFIG_DIR])
        self.assertEqual(sorted(p.name for p in self.new.iterdir()), ["config.yml"])
        self.assertFalse(self.old.exists())
        data = json.loads(self.box.run_default("config", "--json").stdout)
        self.assertEqual(data["values"]["atlas"], str(self.box.atlas))

    def test_init_join_with_only_the_old_folder_writes_the_full_config_in_the_new_one(self):
        """SPEC-0070:UT-03"""
        self.box.atlas.mkdir(parents=True)
        self.assertExit(self.box.init(config_home=self.box.root / "scratch-a"), 0)
        old = self.box.write_local(f'atlas: "{self.box.atlas}"\n'
                                   "credentials:\n"
                                   "  github: {env: [GITHUB_TOKEN], profile: work}\n", config_home=self.old)
        before = old.read_bytes()
        other = self.box.root / "work" / "other-atlas"
        other.mkdir(parents=True)
        self.assertExit(self.box.init(atlas=other, config_home=self.box.root / "scratch-b"), 0)

        out = self.box.run_default("init", "--join", "--atlas", other)
        self.assertExit(out, 0)
        new = self.new / "config.yml"
        self.assertTrue(new.is_file(), f"a gravação não foi para {new}: {output(out)}")
        self.assertEqual(old.read_bytes(), before, "a pasta antiga fica idêntica byte a byte")
        self.assertEqual(sorted(p.name for p in self.old.iterdir()), ["config.yml"], "a antiga não é tocada")
        written = fn("parse_yaml")(new.read_text(encoding="utf-8"))
        self.assertEqual(written.get("atlas"), str(other), "a mudança do comando entra")
        self.assertEqual(written.get("credentials"), {"github": {"env": ["GITHUB_TOKEN"], "profile": "work"}},
                         "o resto da configuração vem da antiga")
        self.assertTrue(new.read_text(encoding="utf-8").startswith(f"# {NEW_CONFIG_DIR}"), "cabeçalho novo")
        data = json.loads(self.box.run_default("config", "--json").stdout)
        self.assertEqual(data["values"]["atlas"], str(other), "depois da gravação vale a nova")

    def test_override_is_the_only_folder_read_and_written_and_doctor_has_no_old_path_warning(self):
        """SPEC-0070:UT-04"""
        self.old_machine(copy=False)
        override = self.box.root / "override"
        shutil.copytree(self.old, override)
        shutil.copytree(self.old, self.new)
        defaults = {name: snapshot(self.box.default_dir(name)) for name in (OLD_CONFIG_DIR, NEW_CONFIG_DIR)}
        other = self.box.root / "work" / "other-atlas"
        other.mkdir(parents=True)
        self.assertExit(self.box.init(atlas=other, config_home=self.box.root / "scratch"), 0)
        self.assertExit(self.box.run("init", "--join", "--atlas", other, config_home=override), 0)
        written = fn("parse_yaml")((override / "config.yml").read_text(encoding="utf-8"))
        self.assertEqual(written.get("atlas"), str(other))
        for name, state in defaults.items():
            self.assertEqual(snapshot(self.box.default_dir(name)), state, f"{name} não muda com a sobrescrita")
        text = self.box.run("doctor", config_home=override)
        js = self.box.run("doctor", "--json", config_home=override)
        for out in (text, js):
            self.assertNotIn("Traceback", output(out))
            self.assertNotIn(OLD_CONFIG_DIR, output(out), "nenhum aviso de caminho antigo com a sobrescrita")
            self.assertNotIn("ignorada", output(out))
        self.assertIn(("OK", "configuração local", str(override / "config.yml")), json_rows(js.stdout))


# ---------------------------------------------------------------- vendor (UT-05)

class VendorTest(RenameCase):
    def setUp(self):
        super().setUp()
        self.atlas_dir = self.new_atlas()

    def vendor(self, *args):
        out = self.box.run("vendor", *args)
        self.assertNotIn("usage:", output(out))
        self.assertExit(out, 0)
        return out

    def assert_copy_is_current(self, copy):
        path = self.atlas_dir / copy / "scripts" / "atlas.py"
        self.assertTrue(path.is_file(), f"{copy}/scripts/atlas.py não existe")
        self.assertEqual(path.read_bytes(), SCRIPT.read_bytes(), f"{copy} difere do atlas.py da skill")
        for name in ("generic.py", "github.py", "argocd.py"):
            copied = self.atlas_dir / copy / "assets" / "collectors" / name
            self.assertTrue(copied.is_file(), f"{copy}: coletor {name} não foi copiado")

    def test_atlas_without_ci_gets_the_new_folder_and_a_ci_that_runs_it(self):
        """SPEC-0070:UT-05 (a: atlas sem CI)"""
        for kind, rel in CI_FILES.items():
            with self.subTest(ci=kind):
                out = self.vendor("--ci", kind)
                self.assert_copy_is_current(NEW_SKILL_COPY)
                text = (self.atlas_dir / rel).read_text(encoding="utf-8")
                self.assertIn(NEW_CALL, text)
                self.assertNotIn(OLD_SKILL_COPY, text)
                self.assertFalse((self.atlas_dir / OLD_DIR).exists(), f"{OLD_DIR}/ não devia ser criada")
                self.assertIn(COMMIT_HINT, out.stdout)
                self.assertNotIn(CAN_DELETE_OLD, output(out), f"sem {OLD_DIR}/ não há o que apagar")

    def test_ci_regenerated_with_force_moves_to_the_new_folder_and_says_the_old_one_can_go(self):
        """SPEC-0070:UT-05 (b: .<antigo>/ e CI da versão anterior regravada com --force)"""
        plant_copy(self.atlas_dir, OLD_SKILL_COPY, outdated=True)
        script = self.atlas_dir / CI_FILES["generic"]
        script.parent.mkdir(parents=True)
        script.write_text(old_generated_script(), encoding="utf-8")
        old_state = snapshot(self.atlas_dir / OLD_DIR)

        out = self.vendor("--ci", "generic", "--force")
        text = script.read_text(encoding="utf-8")
        self.assertEqual(text, (CI_ASSETS / "atlas-scan.sh").read_text(encoding="utf-8"), "CI regravada do modelo")
        self.assertIn(NEW_CALL, text)
        self.assertNotIn(OLD_SKILL_COPY, text)
        self.assert_copy_is_current(NEW_SKILL_COPY)
        self.assertEqual(snapshot(self.atlas_dir / OLD_DIR), old_state, f"{OLD_DIR}/ nunca é apagada nem mudada")
        self.assertIn(CAN_DELETE_OLD, output(out))
        self.assertIn(COMMIT_HINT, out.stdout)
        self.assertNotIn(still_runs_old("generic"), output(out))

    def test_customized_ci_that_runs_the_old_copy_keeps_it_updated_and_shows_how_to_migrate(self):
        """SPEC-0070:UT-05 (c: CI personalizada que roda .<antigo>/skill, mantida sem --force)"""
        for kind, rel in CI_FILES.items():
            with self.subTest(ci=kind):
                plant_copy(self.atlas_dir, OLD_SKILL_COPY, outdated=True)
                path = self.atlas_dir / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(custom_ci(kind), encoding="utf-8")
                before = path.read_bytes()
                files_before = set(snapshot(self.atlas_dir))

                out = self.vendor("--ci", kind)
                self.assertIn(f"mantido: {rel.as_posix()}", out.stdout)
                self.assertEqual(path.read_bytes(), before, "CI personalizada mantida sem --force")
                self.assert_copy_is_current(OLD_SKILL_COPY)
                self.assertFalse((self.atlas_dir / NEW_DIR).exists(),
                                 f"a CI roda {OLD_SKILL_COPY}: {NEW_DIR}/ não é gravada")
                self.assertIn(still_runs_old(kind), output(out))
                self.assertIn(COMMIT_HINT, out.stdout)
                self.assertNotIn(CAN_DELETE_OLD, output(out))
                missing = files_before - set(snapshot(self.atlas_dir))
                self.assertEqual(missing, set(), "o vendor nunca apaga nada")


# ---------------------------------------------------------------- a cópia não é conteúdo (UT-06)

class SkillCopyIsNotContentTest(RenameCase):
    def lint(self):
        out = self.box.run("lint", "--json")
        self.assertNotIn("Traceback", output(out))
        return out, json.loads(out.stdout)["findings"]

    def test_lint_ignores_both_copies_and_warns_an_outdated_copy_in_both(self):
        """SPEC-0070:UT-06 (lint)"""
        for copy in (NEW_SKILL_COPY, OLD_SKILL_COPY):
            with self.subTest(copy=copy):
                self.box = Sandbox()  # um atlas novo para cada pasta
                self.addCleanup(self.box.cleanup)
                atlas_dir = self.new_atlas()
                plant_copy(atlas_dir, copy)
                out, findings = self.lint()
                self.assertEqual(out.returncode, 0, output(out))
                about_copy = [x for x in findings if x["path"].startswith(copy)]
                self.assertEqual(about_copy, [], f"a cópia em {copy} virou conteúdo do atlas")

                plant_copy(atlas_dir, copy, outdated=True)
                out, findings = self.lint()
                tool = f"{copy}/scripts/atlas.py"
                leaks = [x for x in findings if x["rule"] == "secret-leak" and x["path"].startswith(tool)]
                self.assertEqual(leaks, [], "as regex da própria ferramenta viraram secret-leak")
                warnings = [x for x in findings if x["rule"] == "config" and x["path"] == tool]
                self.assertEqual(len(warnings), 1, findings)
                self.assertEqual(warnings[0]["severity"], "warn")
                self.assertIn("vendor", warnings[0]["detail"] + " " + warnings[0]["suggestion"])
                self.assertEqual(out.returncode, 0, output(out))

    def test_build_does_not_index_either_copy(self):
        """SPEC-0070:UT-06 (build)"""
        atlas_dir = self.new_atlas()
        self.assertExit(self.box.run("scan"), 0)

        def state():
            graph = json.loads((atlas_dir / "graph.json").read_text(encoding="utf-8"))
            pages = sorted(p.relative_to(atlas_dir).as_posix() for folder in ("services", "platform")
                           for p in (atlas_dir / folder).rglob("*.md"))
            return graph.get("nodes"), graph.get("edges"), pages

        self.assertExit(self.box.run("build"), 0)
        expected = state()
        self.assertTrue(expected[2], "fixture: o build gerou páginas")
        for copy in (OLD_SKILL_COPY, NEW_SKILL_COPY):
            with self.subTest(copy=copy):
                plant_copy(atlas_dir, copy)
                self.assertExit(self.box.run("build"), 0)
                self.assertEqual(state(), expected, f"o build indexou a cópia em {copy}")


# ---------------------------------------------------------------- doctor (UT-07)

class DoctorTest(RenameCase):
    def check(self, text, js, base_text, base_js, warning, path=None):
        """Mesmo exit code e formato do doctor de referência, as linhas dele todas e um AVISO a mais com `warning`."""
        self.assertEqual(text.returncode, base_text.returncode, "exit code sem mudança")
        self.assertEqual(js.returncode, base_js.returncode, "exit code sem mudança (--json)")
        self.assertNotIn("Traceback", output(text) + output(js))
        text_rows = doctor_lines(text.stdout)
        self.assertEqual(len(text_rows), len(text.stdout.strip().splitlines()),
                         "toda linha no formato OK|AVISO|ERRO <item> — <detalhe>")
        found = [line for line in joined(text_rows) if line.startswith("AVISO ") and warning in line]
        self.assertEqual(len(found), 1, f"um AVISO com {warning!r}:\n{text.stdout}")

        data, base = json.loads(js.stdout), json.loads(base_js.stdout)
        self.assertEqual(set(data), set(base), "chaves do --json iguais")
        self.assertEqual(data["ok"], base["ok"])
        for item in data["checks"]:
            self.assertEqual(set(item), {"status", "item", "detail"}, item)
        rows = json_rows(js.stdout)
        self.assertEqual(len([line for line in joined(rows) if line.startswith("AVISO ") and warning in line]), 1,
                         f"um AVISO com {warning!r} no --json: {rows}")
        if path is not None:
            self.assertIn(("OK", "configuração local", str(path)), rows, "a linha de hoje mostra o caminho lido")
        kept = [row for row in json_rows(base_js.stdout) if row[1] != "configuração local"]
        for row in kept:
            self.assertIn(row, rows, "as outras linhas do doctor não mudam")
        return rows

    def test_doctor_warns_with_the_copy_command_and_then_that_the_old_folder_is_ignored(self):
        """SPEC-0070:UT-07 (configuração antiga, depois as duas)"""
        self.old_machine(copy=False)
        base_text, base_js = self.box.run("doctor", config_home=self.old), \
            self.box.run("doctor", "--json", config_home=self.old)
        with self.subTest(case="só a antiga"):
            text, js = self.box.run_default("doctor"), self.box.run_default("doctor", "--json")
            rows = self.check(text, js, base_text, base_js, OLD_COPY_CMD, self.old / "config.yml")
            self.assertFalse([r for r in joined(rows) if OLD_IGNORED in r], "sem aviso de pasta ignorada")
        shutil.copytree(self.old, self.new)
        with self.subTest(case="as duas"):
            text, js = self.box.run_default("doctor"), self.box.run_default("doctor", "--json")
            rows = self.check(text, js, base_text, base_js, OLD_IGNORED, self.new / "config.yml")
            self.assertFalse([r for r in joined(rows) if OLD_COPY_CMD in r], "sem o comando de cópia")
        self.assertEqual(sorted(p.name for p in self.old.iterdir()), ["config.yml"], "a antiga não é tocada")

    def test_doctor_warns_when_the_atlas_has_the_old_folder(self):
        """SPEC-0070:UT-07 (atlas com .<antigo>/)"""
        self.new_atlas()
        base_text, base_js = self.box.run("doctor"), self.box.run("doctor", "--json")
        plant_copy(self.box.atlas, OLD_SKILL_COPY)
        state = snapshot(self.box.atlas)
        text, js = self.box.run("doctor"), self.box.run("doctor", "--json")
        rows = self.check(text, js, base_text, base_js, MIGRATION_STEP)
        warning = next(line for line in joined(rows) if line.startswith("AVISO ") and MIGRATION_STEP in line)
        for part in (f"{OLD_DIR}/", "vendor", "--force"):
            self.assertIn(part, warning, "o AVISO mostra o passo de migração do vendor")
        self.assertEqual(snapshot(self.box.atlas), state, "o doctor só lê o atlas")
        self.assertNotIn(OLD_COPY_CMD, output(text) + output(js), "a sobrescrita não tem aviso de configuração antiga")


# ---------------------------------------------------------------- textos (UT-08)

class TextsTest(RenameCase):
    def test_version_help_not_configured_init_header_config_and_assets_say_boson_atlas(self):
        """SPEC-0070:UT-08"""
        out = self.box.run_default("--version")
        self.assertExit(out, 0)
        self.assertEqual(out.stdout.strip(), f"{NEW_CONFIG_DIR} {atlas().ATLAS_VERSION}")

        out = self.box.run_default("--help")
        self.assertExit(out, 0)
        self.assertIn(NEW_CONFIG_DIR, out.stdout)
        self.assertNotIn(OLD_CONFIG_DIR, out.stdout)

        for args in (("config",), ("config", "--json"), ("doctor",), ("lint",), ("scan",)):
            with self.subTest(not_configured=args):
                out = self.box.run_default(*args)
                self.assertExit(out, 3)
                self.assertIn(NOT_CONFIGURED, output(out))
                self.assertNotIn(OLD_CONFIG_DIR, output(out))

        self.box.atlas.mkdir(parents=True)
        out = self.box.run_default("init", "--atlas", self.box.atlas, "--org", "Acme", "--mode", "repo")
        self.assertExit(out, 0)
        self.assertNotIn(OLD_CONFIG_DIR, output(out))
        local = (self.new / "config.yml").read_text(encoding="utf-8")
        self.assertTrue(local.startswith(f"# {NEW_CONFIG_DIR}"), local.splitlines()[:1])
        self.assertNotIn(OLD_CONFIG_DIR, local)
        out = self.box.run_default("config")
        self.assertExit(out, 0)
        self.assertIn(f"{NEW_CONFIG_DIR} {atlas().ATLAS_VERSION}", out.stdout)
        self.assertNotIn(OLD_CONFIG_DIR, output(out))

        asset = (SKILL / "assets" / "atlas-config.yml").read_text(encoding="utf-8")
        self.assertTrue(asset.startswith(f"# {NEW_CONFIG_DIR}"), asset.splitlines()[:1])
        self.assertNotIn(OLD_CONFIG_DIR, asset)
        shared = (self.box.atlas / "atlas-config.yml").read_text(encoding="utf-8")
        self.assertTrue(shared.startswith(f"# {NEW_CONFIG_DIR}"), "atlas novo recebe o cabeçalho novo")

        names = sorted(p.name for p in CI_ASSETS.iterdir() if p.is_file())
        self.assertEqual(names, ["atlas-scan.sh", "github-atlas-scan.yml"])
        for name in names:
            with self.subTest(ci_asset=name):
                text = (CI_ASSETS / name).read_text(encoding="utf-8")
                self.assertIn(NEW_CONFIG_DIR, text.splitlines()[0] + text.splitlines()[1])
                self.assertIn(NEW_CALL, text)
                self.assertNotIn(OLD_CONFIG_DIR, text, "o arquivo de CI ainda cita o nome antigo")


# ---------------------------------------------------------------- integração (IT-01, IT-02)

class OldMachineCliTest(RenameCase):
    def test_machine_and_atlas_from_the_previous_version_work_without_action(self):
        """SPEC-0070:IT-01"""
        old = self.old_machine()
        before = old.read_bytes()
        copy_state = snapshot(self.box.atlas / OLD_DIR)

        out = self.box.run_default("scan")
        self.assertExit(out, 0)
        self.assertTrue((self.box.atlas / "snapshots" / "facts.json").is_file(), output(out))

        self.assertExit(self.box.run_default("build"), 0)
        graph = json.loads((self.box.atlas / "graph.json").read_text(encoding="utf-8"))
        self.assertIn("service:payments-api", json.dumps(graph))

        out = self.box.run_default("lint", "--json")
        self.assertExit(out, 0)
        findings = json.loads(out.stdout)["findings"]
        self.assertEqual([x for x in findings if x["path"].startswith(OLD_SKILL_COPY)], [],
                         "a cópia antiga virou conteúdo do atlas")

        out = self.box.run_default("context", "payments", "--json")
        self.assertExit(out, 0)
        self.assertIn("payments-api", out.stdout)

        base = self.box.run("doctor", config_home=self.old)
        out = self.box.run_default("doctor")
        self.assertEqual(out.returncode, base.returncode, output(out))
        self.assertEqual(out.returncode, 0, output(out))
        self.assertTrue([line for line in joined(doctor_lines(out.stdout)) if OLD_COPY_CMD in line], out.stdout)

        self.assertEqual(old.read_bytes(), before, "a configuração antiga nunca é gravada")
        self.assertFalse(self.new.exists(), "comandos que não gravam a configuração não criam a pasta nova")
        self.assertEqual(snapshot(self.box.atlas / OLD_DIR), copy_state, f"{OLD_DIR}/ não é tocada")
        self.assertFalse((self.box.atlas / NEW_DIR).exists())


@unittest.skipUnless(HAS_GIT, "git não está no PATH")
class GeneratedCiScriptTest(RenameCase):
    def git(self, *args):
        env = dict(os.environ, HOME=str(self.box.home), XDG_CONFIG_HOME=str(self.box.home / ".config"),
                   GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="Teste", GIT_AUTHOR_EMAIL="teste@example.invalid",
                   GIT_COMMITTER_NAME="Teste", GIT_COMMITTER_EMAIL="teste@example.invalid")
        out = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
                             cwd=self.box.atlas, capture_output=True, text=True, env=env, check=False)
        self.assertEqual(out.returncode, 0, output(out))
        return out

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)

    def run_script(self):
        # pasta vazia nova a cada execução: sem configuração local na máquina do CI
        empty = Path(tempfile.mkdtemp(prefix="ci-config-", dir=self.box.root))
        env = dict(os.environ, HOME=str(self.box.home), XDG_CONFIG_HOME=str(self.box.home / ".config"),
                   ATLAS_CONFIG_HOME=str(empty))
        return subprocess.run(["bash", str(CI_FILES["generic"])], cwd=self.box.atlas, capture_output=True,
                              text=True, env=env, check=False)

    def test_vendor_generic_script_runs_the_new_copy(self):
        """SPEC-0070:IT-02"""
        self.new_atlas()
        out = self.box.run("vendor", "--ci", "generic")
        self.assertExit(out, 0)
        script = (self.box.atlas / CI_FILES["generic"]).read_text(encoding="utf-8")
        self.assertIn(NEW_CALL, script)
        self.assertNotIn(OLD_SKILL_COPY, script)
        self.assertTrue((self.box.atlas / NEW_SKILL_COPY / "scripts" / "atlas.py").is_file())
        self.assertFalse((self.box.atlas / OLD_DIR).exists(), "a CI só tem a cópia nova para rodar")
        self.git("init", "-q")
        self.commit("atlas")

        first = self.run_script()
        self.assertIn(first.returncode, (0, 10), output(first))
        self.assertEqual(first.returncode, 10, f"primeiro scan muda a árvore: {output(first)}")
        self.assertTrue((self.box.atlas / "snapshots" / "facts.json").is_file(), output(first))
        self.commit("scan")
        again = self.run_script()
        self.assertEqual(again.returncode, 0, f"mesma saída do coletor = sem mudança: {output(again)}")


if __name__ == "__main__":
    unittest.main()
