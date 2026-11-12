"""Documentos vivos (SPEC-0011): guia de jornadas e mapa do sistema.

Contrato esperado das funções puras de scripts/spec_graph.py (o Implementer segue estes testes):

    living_docs_findings(journeys, guide_text, adrs, map_text) -> list[tuple[str, str]]
        journeys   : dict {id da jornada crítica: título}  (o critical_journeys do sdd-config)
        guide_text : texto do guia de jornadas (str)
        adrs       : dict {ADR-NNNN: status}  (só "accepted" é exigido no mapa)
        map_text   : texto do mapa do sistema (str)
        devolve uma lista de achados (kind, value), sem ordem garantida:
            ("journey_missing", <id>)    jornada crítica sem "[jornada: <id>]" no guia
            ("journey_unknown", <id>)    guia cita "[jornada: <id>]" fora de critical_journeys
            ("adr_uncited", "ADR-NNNN")  ADR accepted cujo ID não aparece no mapa
        cobertura completa -> []

    living_docs_paths(project) -> dict[str, Path]
        lê living_docs do sdd-config de project; devolve {chave: caminho absoluto} só para os documentos ligados
        ("journeys", "system_map"); chave ausente ou "" -> fora do dict (living_docs ausente -> {}).
        Base: project.root no modo completo, project.spec_root no modo privado (SPEC-0003@1).
        Caminho absoluto ou que saia da base com ".." -> ValueError (erro de configuração).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
SKILL = TESTS.parent
SCRIPT = SKILL / "scripts" / "spec_graph.py"
REFS = SKILL / "references"
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(TESTS))
import spec_graph as sg
import test_private_mode as tpm
from test_private_mode import PrivateEnv
from test_spec_graph import Project, git

CONFIG = 'living_docs:\n  journeys: docs/jornadas.md\n  system_map: docs/arquitetura.md\n'
JOURNEYS = 'critical_journeys:\n  agenda: "Agendar consulta"\n  moderacao: "Moderar avaliações"\n'
LIVING_WARNINGS = ("living_docs", "living-docs", "guia de jornadas", "mapa do sistema", "documento vivo")

_USER_ENV = {}


def setUpModule():
    """Isola o registro do usuário (projects.json), como as demais suítes."""
    _USER_ENV["SDD_CONFIG_HOME"] = os.environ.get("SDD_CONFIG_HOME")
    _USER_ENV["dir"] = tempfile.mkdtemp()
    os.environ["SDD_CONFIG_HOME"] = _USER_ENV["dir"]


def tearDownModule():
    if _USER_ENV["SDD_CONFIG_HOME"] is None:
        os.environ.pop("SDD_CONFIG_HOME", None)
    else:
        os.environ["SDD_CONFIG_HOME"] = _USER_ENV["SDD_CONFIG_HOME"]
    shutil.rmtree(_USER_ENV["dir"], ignore_errors=True)


def fn(name):
    """Função de spec_graph exigida pela SPEC-0011; ausente = o teste falha pelo motivo certo, sem quebrar a suíte."""
    f = getattr(sg, name, None)
    if f is None:
        raise AssertionError(f"spec_graph.{name} não existe (SPEC-0011)")
    return f


def living_lines(out: str):
    return [line for line in out.splitlines() if any(w in line.lower() for w in LIVING_WARNINGS)]


def line_with(out: str, text: str) -> str:
    return next((line for line in out.splitlines() if text in line), "")


class LivingProject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.p = Project(self.tmp)
        self.cfg = self.tmp / "docs/specs/sdd-config.yml"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_config(self, text):
        self.cfg.write_text(self.cfg.read_text(encoding="utf-8") + text, encoding="utf-8")

    def adr(self, title, status):
        out = self.p.run("new-adr", "--title", title)
        self.assertEqual(out.returncode, 0, out.stderr)
        aid = out.stdout.split()[0]
        path = next((self.tmp / "docs/adr").glob(f"{aid}-*.md"))
        path.write_text(re.sub(r"\{\{([^{}]*)\}\}", lambda m: m.group(1), path.read_text(encoding="utf-8")),
                        encoding="utf-8")
        self.p.set(aid, status=status)
        return aid

    def write(self, rel, text):
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class FindingsTest(unittest.TestCase):
    def test_missing_unknown_and_uncited(self):
        """SPEC-0011:UT-01"""
        findings = fn("living_docs_findings")
        journeys = {"agenda": "Agendar consulta", "moderacao": "Moderar avaliações"}
        adrs = {"ADR-0001": "accepted", "ADR-0002": "accepted", "ADR-0003": "superseded"}
        guide = "# Jornadas\n\n## Agendar [jornada: agenda]\n\n## Antiga [jornada: velha]\n"
        mapa = "# Mapa\n\n## Decisões\n- ADR-0001 — Banco de dados\n"
        got = findings(journeys, guide, adrs, mapa)
        self.assertEqual(sorted(got), sorted([("journey_missing", "moderacao"), ("journey_unknown", "velha"),
                                              ("adr_uncited", "ADR-0002")]))
        self.assertNotIn("ADR-0003", str(got))

        guide = "## Agendar [jornada: agenda]\n## Moderar [jornada: moderacao]\n"
        mapa = "- ADR-0001 — Banco\n- ADR-0002 — Fila\n"
        self.assertEqual(list(findings(journeys, guide, adrs, mapa)), [])


class PathsTest(unittest.TestCase):
    def project(self, extra):
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        Project(tmp, extra)
        return sg.Project(tmp)

    def test_disabled_inside_and_invalid_paths(self):
        """SPEC-0011:UT-02"""
        paths = fn("living_docs_paths")
        self.assertEqual(dict(paths(self.project(""))), {})
        self.assertEqual(dict(paths(self.project('living_docs:\n  journeys: ""\n  system_map: ""\n'))), {})
        project = self.project("living_docs:\n  journeys: docs/jornadas.md\n")
        got = paths(project)
        self.assertEqual(set(got), {"journeys"})
        self.assertEqual(Path(got["journeys"]), project.root / "docs" / "jornadas.md")
        for bad in ("/etc/x.md", "../fora.md"):
            with self.assertRaises(ValueError, msg=bad):
                paths(self.project(f"living_docs:\n  journeys: {bad}\n"))


class InstructionsTest(unittest.TestCase):
    @staticmethod
    def read(rel):
        return (SKILL / rel).read_text(encoding="utf-8")

    @staticmethod
    def section(text, heading_re, stop_re=r"^#{1,3} "):
        m = re.search(heading_re, text, re.MULTILINE)
        if not m:
            return ""
        rest = text[m.end():]
        end = re.search(stop_re, rest, re.MULTILINE)
        return rest[:end.start()] if end else rest

    def test_instructions_carry_the_contract_snippets(self):
        """SPEC-0011:UT-03"""
        skill = self.read("SKILL.md")
        self.assertTrue(any(line.startswith("| `living-docs") for line in skill.splitlines()),
                        "SKILL.md: linha de living-docs na tabela de comandos")
        self.assertRegex(self.section(skill, r"^### 8\. CLOSE.*$", r"^##+ "), r"living[-_]docs",
                         "SKILL.md: CLOSE atualiza guia e mapa")
        self.assertIn("living_docs", self.section(self.read("references/gates.md"), r"^## G7\b.*$", r"^## "),
                      "gates.md: G7 cita guia/mapa e os avisos de living_docs")
        for rel in ("references/greenfield.md", "references/brownfield.md"):
            self.assertIn("living-docs --init", self.read(rel), rel)
        dod = self.section(self.read("references/template-full.md"), r"^### Definição de Pronto\s*$", r"^##+ ")
        self.assertTrue(any(line.startswith("- [ ]") and "Guia de jornadas e mapa do sistema" in line
                            for line in dod.splitlines()), "template-full.md: item da Definição de Pronto")
        config = sg.parse_yaml_subset(self.read("references/sdd-config.template.yml"))
        living = config.get("living_docs")
        self.assertIsInstance(living, dict, "sdd-config.template.yml: living_docs")
        self.assertTrue(living.get("journeys") and living.get("system_map"), living)
        private = self.read("references/private-mode.md")
        self.assertTrue(any(line.startswith("| Documentos vivos") and "<spec_root>/" in line
                            for line in private.splitlines()), "private-mode.md: linha Documentos vivos")


class ValidateWarningsTest(LivingProject):
    def timed_validate(self):
        start = time.monotonic()
        out = self.p.validate()
        return out, time.monotonic() - start

    def test_warnings_do_not_change_the_exit_code(self):
        """SPEC-0011:IT-01"""
        self.add_config(JOURNEYS)
        self.adr("Banco de dados", "accepted")
        self.adr("Fila de mensagens", "accepted")
        self.adr("Cache antigo", "proposed")
        before, base_time = self.timed_validate()

        self.add_config(CONFIG)
        self.write("docs/jornadas.md", "# Jornadas\n\n## Agendar [jornada: agenda]\n\n## Antiga [jornada: velha]\n")
        self.write("docs/arquitetura.md", "# Mapa\n\n## Decisões\n- ADR-0001 — Banco de dados\n")
        self.assertEqual(before.returncode, 0, before.stdout)
        out, elapsed = self.timed_validate()
        self.assertEqual(out.returncode, before.returncode, out.stdout)
        expected = ("guia de jornadas sem a jornada crítica moderacao — adicione a seção com [jornada: moderacao]",
                    "guia de jornadas cita [jornada: velha], que não está em critical_journeys",
                    "mapa do sistema não cita ADR-0002 (accepted) — diga onde a decisão aparece no sistema")
        for msg in expected:
            self.assertTrue(line_with(out.stdout, msg).startswith("WARN"), (msg, out.stdout))
        self.assertNotIn("não cita ADR-0001", out.stdout)
        self.assertNotIn("ADR-0003 (", out.stdout)
        self.assertNotIn("sem a jornada crítica agenda", out.stdout)
        self.assertFalse([line for line in living_lines(out.stdout) if line.startswith("ERROR")], out.stdout)
        self.assertLess(elapsed, base_time * 2 + 1.0, "validate com living_docs ficou lento demais")

        (self.tmp / "docs/arquitetura.md").unlink()
        out = self.p.validate()
        self.assertEqual(out.returncode, before.returncode, out.stdout)
        absent = line_with(out.stdout, "living_docs.system_map:")
        self.assertTrue(absent.startswith("WARN"), out.stdout)
        self.assertIn("docs/arquitetura.md", absent)
        self.assertIn("não existe — rode living-docs --init", absent)


class InitTest(LivingProject):
    def test_init_creates_skeletons_and_keeps_existing_files(self):
        """SPEC-0011:IT-02"""
        self.add_config(JOURNEYS + CONFIG)
        sid = self.p.new("full", "Agenda")
        self.p.fill(sid, touches="[src/a/**, tests/a/**]")
        self.p.edit(sid, "- **E2E-01** — jornada principal", "- **E2E-01** — jornada principal [jornada: agenda]")
        self.p.set(sid, status="implemented")
        self.adr("Banco de dados", "accepted")
        self.adr("Fila de mensagens", "accepted")

        out = self.p.run("living-docs", "--init")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("criado: docs/jornadas.md", out.stdout)
        self.assertIn("criado: docs/arquitetura.md", out.stdout)
        guide = (self.tmp / "docs/jornadas.md").read_text(encoding="utf-8")
        mapa = (self.tmp / "docs/arquitetura.md").read_text(encoding="utf-8")
        self.assertRegex(guide, r"(?m)^## .+ \[jornada: agenda\]")
        self.assertRegex(guide, r"(?m)^## .+ \[jornada: moderacao\]")
        for field in ("Perfil", "Passo a passo", "Como reproduzir localmente"):
            self.assertIn(field, guide)
        self.assertIn(f"Provada por: {sid} (E2E-01)", guide)
        self.assertIn("Provada por: — (sem E2E)", guide)
        for heading in ("Visão geral", "Componentes por camada", "Serviços externos", "Ambientes", "Rodar localmente",
                        "Caminho até produção", "Decisões"):
            self.assertIn(heading, mapa)
        self.assertIn("- ADR-0001 — Banco de dados", mapa)
        self.assertIn("- ADR-0002 — Fila de mensagens", mapa)

        self.assertEqual(living_lines(self.p.validate().stdout), [])

        again = self.p.run("living-docs", "--init")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("mantido: docs/jornadas.md", again.stdout)
        self.assertIn("mantido: docs/arquitetura.md", again.stdout)
        self.assertNotIn("criado:", again.stdout)
        self.assertEqual((self.tmp / "docs/jornadas.md").read_text(encoding="utf-8"), guide)
        self.assertEqual((self.tmp / "docs/arquitetura.md").read_text(encoding="utf-8"), mapa)


class CoverageCommandTest(LivingProject):
    def test_living_docs_prints_coverage(self):
        """SPEC-0011:IT-02"""
        self.add_config(JOURNEYS)
        self.adr("Banco de dados", "accepted")
        self.adr("Fila de mensagens", "accepted")
        self.adr("Cache antigo", "proposed")
        none = self.p.run("living-docs")
        self.assertEqual(none.returncode, 0, none.stdout + none.stderr)
        self.assertIn("Nenhum documento vivo em living_docs no sdd-config.yml.", none.stdout)

        self.add_config(CONFIG)
        self.write("docs/jornadas.md", "# Jornadas\n\n## Agendar [jornada: agenda]\n\n## Antiga [jornada: velha]\n")
        absent = self.p.run("living-docs")
        self.assertEqual(absent.returncode, 0, absent.stdout + absent.stderr)
        self.assertIn("existe", line_with(absent.stdout, "docs/jornadas.md"))
        self.assertIn("ausente", line_with(absent.stdout, "docs/arquitetura.md"))

        self.write("docs/arquitetura.md", "# Mapa\n\n## Decisões\n- ADR-0001 — Banco de dados\n")
        cover = self.p.run("living-docs")
        self.assertEqual(cover.returncode, 0, cover.stdout + cover.stderr)
        for mark in ("✅ agenda", "⚠ moderacao", "✖ velha", "✅ ADR-0001", "⚠ ADR-0002"):
            self.assertIn(mark, cover.stdout)
        self.assertNotIn("ADR-0003", cover.stdout)


class DisabledGuardTest(LivingProject):
    def test_without_living_docs_validate_is_unchanged(self):
        """SPEC-0011:IT-04 (guarda)"""
        self.add_config('critical_journeys:\n  agenda: "Agendar consulta"\n')
        sid = self.p.new("full", "Agenda")
        self.p.fill(sid, touches="[src/a/**, tests/a/**]")
        self.p.edit(sid, "- **E2E-01** — jornada principal", "- **E2E-01** — jornada principal [jornada: agenda]")
        self.write("docs/jornadas.md", "# Jornadas sem seções\n")
        out = self.p.validate()
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertEqual(living_lines(out.stdout), [], out.stdout)


class ScopeTest(LivingProject):
    def commit(self, files, message):
        for name, content in files.items():
            self.write(name, content)
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", message)

    def test_living_docs_are_never_out_of_scope(self):
        """SPEC-0011:IT-05"""
        self.add_config(CONFIG)
        sid = self.p.new("full", "Agenda")
        self.p.fill(sid, touches="[src/**, tests/**]")
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", "docs: spec")
        git(self.tmp, "checkout", "-qb", "work")
        tags = "\n".join(f"# {sid}:{t}" for t in ("UT-01", "UT-02", "IT-01", "E2E-01"))
        self.commit({"tests/a/test_a.py": tags}, f"test(a): red\n\nRefs: {sid}")
        self.commit({"src/a.py": "x = 1\n", "docs/jornadas.md": "## Agendar [jornada: agenda]\n"},
                    f"feat(a): green\n\nRefs: {sid}")
        out = self.p.run("verify", sid, "--base", "main")
        self.assertNotIn("docs/jornadas.md", line_with(out.stdout, "fora de touches"), out.stdout)
        self.assertEqual(out.returncode, 0, out.stdout)


class PrivateLivingDocsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.e = PrivateEnv(self.tmp)
        self.e.init()
        config = self.e.spec_root / "sdd-config.yml"
        config.write_text(config.read_text(encoding="utf-8") + "\n" + JOURNEYS + CONFIG, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_init_writes_only_to_the_spec_root(self):
        """SPEC-0011:IT-03"""
        status = self.e.run("living-docs")
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertIn("ausente", line_with(status.stdout, "docs/jornadas.md"))
        before = len(self.e.root_log())
        out = self.e.run("living-docs", "--init")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        for rel in ("docs/jornadas.md", "docs/arquitetura.md"):
            self.assertTrue((self.e.spec_root / rel).is_file(), rel)
            self.assertFalse((self.e.repo / rel).exists(), rel)
        self.assertGreater(len(self.e.root_log()), before)
        tracked = git_out(self.e, self.e.spec_root, "ls-files")
        self.assertIn("docs/jornadas.md", tracked)
        self.assertIn("docs/arquitetura.md", tracked)
        self.assertEqual(self.e.repo_status(), "")
        leak = self.e.run("leak-check")
        self.assertEqual(leak.returncode, 0, leak.stdout + leak.stderr)

    def test_paths_are_resolved_against_the_spec_root(self):
        """SPEC-0011:CT-01"""
        with mock.patch.dict(os.environ, self.e.env, clear=True):
            project = sg.Project(self.e.repo)
            self.assertTrue(project.private)
            got = fn("living_docs_paths")(project)
        self.assertEqual(Path(got["journeys"]), self.e.spec_root / "docs" / "jornadas.md")
        self.assertEqual(Path(got["system_map"]), self.e.spec_root / "docs" / "arquitetura.md")

        (self.e.repo / "docs").mkdir()
        (self.e.repo / "docs/jornadas.md").write_text("## [jornada: agenda]\n## [jornada: moderacao]\n", encoding="utf-8")
        out = self.e.run("validate")
        self.assertIn("living_docs.journeys:", out.stdout)
        (self.e.spec_root / "docs").mkdir()
        shutil.copy(self.e.repo / "docs/jornadas.md", self.e.spec_root / "docs/jornadas.md")
        out = self.e.run("validate")
        self.assertNotIn("living_docs.journeys:", out.stdout)
        self.assertNotIn("guia de jornadas sem a jornada crítica", out.stdout)
        self.assertIn("living_docs.system_map:", out.stdout)


def git_out(env, cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env.env).stdout


# ---------------------------------------------------------------- achados da revisão (G4, rodada 2)

class PathEdgeCasesTest(unittest.TestCase):
    def project(self, extra, base=None):
        tmp = base or Path(tempfile.mkdtemp()).resolve()
        if base is None:
            self.addCleanup(shutil.rmtree, tmp, True)
        Project(tmp, extra)
        return sg.Project(tmp)

    @unittest.skipUnless(hasattr(os, "symlink"), "os.symlink indisponível")
    def test_symlink_leaving_the_base_is_a_config_error(self):
        """SPEC-0011:UT-02"""
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        outside = tmp / "fora"
        outside.mkdir()
        repo = tmp / "repo"
        repo.mkdir()
        try:
            os.symlink(str(outside), str(repo / "out"), target_is_directory=True)
        except (OSError, NotImplementedError) as e:
            self.skipTest(f"symlink não suportado: {e}")
        project = self.project("living_docs:\n  journeys: out/j.md\n", base=repo)
        with self.assertRaises(ValueError):
            fn("living_docs_paths")(project)

    def test_directory_is_a_config_error(self):
        """SPEC-0011:UT-02"""
        paths = fn("living_docs_paths")
        for value in ('"."', "docs"):
            with self.assertRaises(ValueError, msg=value):
                paths(self.project(f"living_docs:\n  journeys: {value}\n"))


class InvalidPathCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.repo = self.tmp / "repo"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def files_on_disk(self):
        return sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*")
                      if p.is_file() and ".git" not in p.relative_to(self.tmp).parts)

    def test_directory_path_is_a_validate_error(self):
        """SPEC-0011:IT-01"""
        for value in ('"."', "docs"):
            shutil.rmtree(self.repo, ignore_errors=True)
            p = Project(self.repo, f"living_docs:\n  journeys: {value}\n")
            out = p.validate()
            error = [line for line in out.stdout.splitlines()
                     if line.startswith("ERROR") and "sdd-config" in line and "living_docs.journeys" in line]
            self.assertTrue(error, (value, out.stdout))
            self.assertNotIn("não existe — rode living-docs --init", out.stdout, value)
            self.assertEqual(out.returncode, 1, out.stdout)

    def test_path_leaving_the_base_is_refused_everywhere(self):
        """SPEC-0011:IT-02"""
        for value in ("../fora.md", "docs/../../x.md"):
            shutil.rmtree(self.repo, ignore_errors=True)
            p = Project(self.repo, f"living_docs:\n  journeys: {value}\n  system_map: docs/arquitetura.md\n")
            before = self.files_on_disk()
            out = p.validate()
            self.assertTrue([line for line in out.stdout.splitlines() if line.startswith("ERROR")
                             and "sdd-config" in line and "living_docs.journeys" in line], (value, out.stdout))
            for args in (("living-docs",), ("living-docs", "--init")):
                res = p.run(*args)
                self.assertEqual(res.returncode, 2, (value, args, res.stdout, res.stderr))
            self.assertEqual(self.files_on_disk(), before, value)
            self.assertFalse((self.tmp / "fora.md").exists())
            self.assertFalse((self.tmp / "x.md").exists())
            self.assertFalse((self.repo / "docs/arquitetura.md").exists())


class InitRenderingTest(LivingProject):
    def test_title_with_placeholder_text_is_kept(self):
        """SPEC-0011:IT-02"""
        self.add_config('critical_journeys:\n  agenda: "Fã vê {{id}} na agenda"\n' + CONFIG)
        out = self.p.run("living-docs", "--init")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        guide = (self.tmp / "docs/jornadas.md").read_text(encoding="utf-8")
        self.assertIn("Fã vê {{id}} na agenda", guide)
        self.assertNotIn("Fã vê agenda na agenda", guide)

    def test_coverage_lists_everything_when_documents_are_absent(self):
        """SPEC-0011:IT-02"""
        self.add_config(JOURNEYS + CONFIG)
        self.adr("Banco de dados", "accepted")
        self.adr("Fila de mensagens", "accepted")
        out = self.p.run("living-docs")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("ausente", line_with(out.stdout, "docs/jornadas.md"))
        self.assertIn("ausente", line_with(out.stdout, "docs/arquitetura.md"))
        for mark in ("⚠ agenda", "⚠ moderacao", "⚠ ADR-0001", "⚠ ADR-0002"):
            self.assertIn(mark, out.stdout)


class PrivateCoverageTest(unittest.TestCase):
    setUp = PrivateLivingDocsTest.setUp
    tearDown = PrivateLivingDocsTest.tearDown

    def test_plain_living_docs_does_not_commit(self):
        """SPEC-0011:IT-03"""
        (self.e.spec_root / "rascunho.md").write_text("x\n", encoding="utf-8")
        def count():
            return git_out(self.e, self.e.spec_root, "rev-list", "--count", "HEAD").strip()

        before = count()
        out = self.e.run("living-docs")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(count(), before)
        self.assertIn("rascunho.md", git_out(self.e, self.e.spec_root, "status", "--porcelain"))


class PrivateScopeTest(tpm.TraceTestCase):
    def test_living_doc_path_is_not_exempt_in_the_team_repo(self):
        """SPEC-0011:CT-01"""
        config = self.e.spec_root / "sdd-config.yml"
        config.write_text(config.read_text(encoding="utf-8") + "\n" + CONFIG, encoding="utf-8")
        self.red()
        for rel, text in (("src/soma.py", "def soma(a, b):\n    return a + b\n"),
                          ("docs/jornadas.md", "## Agendar [jornada: agenda]\n")):
            path = self.e.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        git_out(self.e, self.e.repo, "add", "-A")
        git_out(self.e, self.e.repo, "commit", "-qm", "implementa a soma")
        out = self.e.run("verify", "SPEC-0001")
        self.assertIn("docs/jornadas.md", line_with(out.stdout, "fora de touches"), out.stdout)
        self.assertNotEqual(out.returncode, 0, out.stdout)


if __name__ == "__main__":
    unittest.main()
