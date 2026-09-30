"""Tests for scripts/spec_graph.py. Run: python3 -m unittest discover -s tests (from the skill directory).

Optional read-only smoke test against real projects: SDD_REAL_PROJECTS=/path/a:/path/b
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "spec_graph.py"
sys.path.insert(0, str(SCRIPT.parent))
import spec_graph as sg  # noqa: E402

FILL = {
    "{{E2E-01 — jornada do usuário: passos e resultado visível | N/A — user_facing: false}}": "**E2E-01** — jornada principal",
    "{{CH-01 — comportamento atual que deve ser preservado | N/A — área já coberta por testes ou projeto novo}}": "N/A — projeto novo",
    "{{CT-01 — verificação do contrato fornecido/consumido | N/A — não há contrato entre specs}}": "N/A — sem contrato",
    "{{CH-01 — comportamento atual preservado | Caracterização: N/A — área já coberta}}": "Caracterização: N/A — coberta",
    "{{IT-01 ou E2E-01 — regressão no nível do defeito | Integração/E2E: N/A — motivo}}": "Integração: N/A — cálculo puro",
    "{{- [ ] dúvida que precisa de resposta e quem responde | Nenhuma}}": "Nenhuma",
    "| {{SPEC-NNNN}} | {{título}} | {{full}} | {{feature}} | {{M}} | {{—}} | {{—}} |": "| — | — | — | — | — | — | — |",
    "{{critério verificável — SPEC-NNNN:E2E-01}}": "critério",
}


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


class Project:
    def __init__(self, tmp: Path, config_extra: str = ""):
        self.root = tmp
        (tmp / "docs" / "specs").mkdir(parents=True)
        git(tmp, "init", "-q", "-b", "main")
        git(tmp, "config", "user.email", "t@t")
        git(tmp, "config", "user.name", "t")
        (tmp / "docs/specs/sdd-config.yml").write_text(
            "base_branch: main\nmax_parallel: 2\ntest_paths:\n  - \"tests/**\"\n" + config_extra, encoding="utf-8")
        (tmp / "README.md").write_text("# demo\n", encoding="utf-8")
        git(tmp, "add", "-A")
        git(tmp, "commit", "-qm", "chore: init")

    def run(self, *args, env=None):
        full_env = dict(os.environ, **(env or {}))
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.root, capture_output=True,
                              text=True, env=full_env)

    def new(self, tier, title, parent=None):
        args = ["new", "--tier", tier, "--title", title] + (["--parent", parent] if parent else [])
        out = self.run(*args)
        assert out.returncode == 0, out.stderr
        return out.stdout.split()[0]

    def path(self, sid):
        return next((self.root / "docs/specs").glob(f"{sid}-*.md"))

    def fill(self, sid, **meta):
        p = self.path(sid)
        text = p.read_text(encoding="utf-8")
        for a, b in FILL.items():
            text = text.replace(a, b)
        text = re.sub(r"\{\{([^{}]*)\}\}", lambda m: m.group(1), text)
        p.write_text(text, encoding="utf-8")
        if meta:
            self.set(sid, **meta)

    def set(self, sid, **meta):
        pairs = [f"{k}={v}" for k, v in meta.items()]
        out = self.run("set", sid, *pairs)
        assert out.returncode == 0, out.stderr

    def edit(self, sid, old, new):
        p = self.path(sid)
        text = p.read_text(encoding="utf-8")
        assert old in text, old
        p.write_text(text.replace(old, new, 1), encoding="utf-8")

    def validate(self, *ids):
        return self.run("validate", *ids)


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = Project(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def full(self, title="Feature", **meta):
        sid = self.p.new("full", title)
        meta.setdefault("touches", "[src/a/**, tests/a/**]")
        self.p.fill(sid, **meta)
        return sid


class ParserTest(unittest.TestCase):
    def test_nested_mappings_lists_and_quotes(self):
        data = sg.parse_yaml_subset('a: 1\nb:\n  c: "To Do"\n  in-progress: In Progress\nd:\n  - x\n  - y\n'
                                    'e:\n- z\nf: [p, q]\ng:\nh: "x: y"  # c\n')
        self.assertEqual(data, {"a": "1", "b": {"c": "To Do", "in-progress": "In Progress"}, "d": ["x", "y"],
                                "e": ["z"], "f": ["p", "q"], "g": "", "h": "x: y"})

    def test_set_meta_roundtrip(self):
        text = "---\nid: X\ntitle: a\n---\nbody"
        text = sg.set_meta(text, "title", "Foo: bar")
        text = sg.set_meta(text, "touches", ["a/**", "b"])
        fm, _ = sg.split_frontmatter(text)
        self.assertEqual(sg.parse_yaml_subset(fm), {"id": "X", "title": "Foo: bar", "touches": ["a/**", "b"]})


class GlobTest(unittest.TestCase):
    def test_glob_matching(self):
        self.assertTrue(sg.matches_any("src/a/b/c.cs", ["src/a/**"]))
        self.assertTrue(sg.matches_any("package.json", ["**/package.json"]))
        self.assertFalse(sg.matches_any("src/x.cs", ["src/a/**"]))
        self.assertTrue(sg.matches_any("src/a", ["src/a"]))

    def test_overlap_is_conservative(self):
        self.assertTrue(sg.patterns_overlap("src/Wallet/**", "src/Wallet/Totals.cs"))
        self.assertFalse(sg.patterns_overlap("src/*.cs", "src/Other/x.cs"))
        self.assertFalse(sg.patterns_overlap("src/Pay/**", "src/Payments/x.cs"))


class ValidateTest(ProjectTest):
    def test_filled_full_spec_passes(self):
        sid = self.full()
        out = self.p.validate(sid)
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_placeholders_fail(self):
        sid = self.p.new("full", "Rascunho")
        out = self.p.validate(sid)
        self.assertEqual(out.returncode, 1)
        self.assertIn("marcador", out.stdout)

    def test_open_question_blocks_g0(self):
        sid = self.full()
        self.p.edit(sid, "## 9. Questões em Aberto\n", "## 9. Questões em Aberto\n- [ ] Limite? (usuário)\n")
        self.assertIn("questão(ões) em aberto", self.p.validate(sid).stdout)

    def test_user_facing_requires_e2e(self):
        sid = self.full()
        self.p.edit(sid, "- **E2E-01** — jornada principal", "- N/A")
        self.p.edit(sid, "UT-01, IT-01, E2E-01", "UT-01, IT-01")
        self.assertIn("user_facing: true exige", self.p.validate(sid).stdout)

    def test_behavior_map_must_reference_planned_tests(self):
        sid = self.full()
        self.p.edit(sid, "| UT-02 |", "| UT-09 |")
        self.assertIn("teste ausente do plano: UT-09", self.p.validate(sid).stdout)

    def test_contract_version_requires_amendment(self):
        sid = self.full(contract_version="2")
        self.assertIn("exige 1 emenda", self.p.validate(sid).stdout)

    def test_lite_cannot_be_migration(self):
        sid = self.p.new("lite", "Pequeno")
        self.p.fill(sid, type="migration", touches="[src/x.cs]")
        self.assertIn("não é permitido no tier lite", self.p.validate(sid).stdout)

    def test_cycle_detected(self):
        a, b = self.full("A"), self.full("B")
        self.p.set(a, depends_on=f"[{b}]")
        self.p.set(b, depends_on=f"[{a}]")
        self.assertIn("ciclo em depends_on", self.p.validate().stdout)

    def test_decomposition_other_columns_do_not_warn(self):
        epic_a = self.p.new("epic", "Épico A")
        self.p.fill(epic_a)
        dep = self.p.new("full", "Filha de A", parent=epic_a)
        self.p.fill(dep, touches="[src/a/**]")
        epic_b = self.p.new("epic", "Épico B")
        self.p.fill(epic_b)
        kid = self.p.new("full", "Filha de B", parent=epic_b)
        self.p.fill(kid, touches="[src/b/**]")
        self.p.edit(epic_b, "| — | — | — | — | — | — | — |", f"| {kid} | Filha | full | feature | M | {dep} | — |")
        out = self.p.validate().stdout
        self.assertNotIn("não tem parent", out)
        self.p.edit(epic_b, f"| {kid} | Filha", f"| {dep} | Filha")
        self.assertIn(f"lista {dep} como filha", self.p.validate().stdout)


class PlanningTest(ProjectTest):
    def approve(self, *ids):
        out = self.p.run("set", *ids, "status=approved", "approved_by=t", "approved_at=today")
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_waves_respect_dependencies_conflicts_and_limit(self):
        a = self.full("A", touches="[src/auth/**]")
        b = self.full("B", touches="[src/orders/**]")
        c = self.full("C", touches="[src/orders/**]", depends_on=f"[{a}]")
        d = self.full("D", touches="[src/profile/**]")
        self.approve(a, b, c, d)
        project = sg.Project(self.tmp)
        wave, members, _ = sg.compute_waves(project)
        self.assertEqual((wave[a], wave[b]), (1, 1))
        self.assertEqual(wave[c], 2)
        self.assertEqual(wave[d], 2)  # max_parallel = 2
        running, batch, held = sg.next_batch(project, (wave, members, {}))
        self.assertEqual(sorted(batch), sorted([a, b]))

    def test_stale_contract_pin_blocks(self):
        provider = self.full("Provider", touches="[src/p/**]")
        consumer = self.full("Consumer", touches="[src/c/**]", consumes_contract=f"[{provider}@1]")
        self.approve(provider, consumer)
        self.p.set(provider, contract_version="2")
        state, label = sg.readiness(sg.Project(self.tmp), sg.Project(self.tmp).specs[consumer])
        self.assertEqual(state, "blocked")
        self.assertIn("mudou", label)


class ImpedimentTest(ProjectTest):
    def test_impede_resolve_lifecycle(self):
        sid = self.full()
        self.assertEqual(self.p.run("impede", sid, "--type", "decisao", "--reason", "a | b", "--owner", "u").returncode, 0)
        project = sg.Project(self.tmp)
        self.assertEqual(sg.readiness(project, project.specs[sid])[0], "blocked")
        item = sg.open_impediments(project.specs[sid])[0]
        self.assertEqual(item["Descrição"], "a | b")
        self.assertEqual(self.p.run("resolve", sid, "IMP-01", "--resolution", "ok").returncode, 0)
        self.assertNotEqual(self.p.run("resolve", sid, "IMP-01", "--resolution", "de novo").returncode, 0)

    def test_resolution_rules(self):
        sid = self.full()
        self.p.run("impede", sid, "--type", "trabalho", "--reason", "falta CI", "--owner", "a")
        self.assertNotEqual(self.p.run("resolve", sid, "IMP-01", "--resolution", "depois").returncode, 0)
        self.p.run("impede", sid, "--type", "spec", "--reason", "lacuna", "--owner", "a")
        self.assertNotEqual(self.p.run("resolve", sid, "IMP-02", "--resolution", "Emenda v2").returncode, 0)


class GitChecksTest(ProjectTest):
    def commit(self, files, message):
        for name, content in files.items():
            f = self.tmp / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content, encoding="utf-8")
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", message)

    def prepare(self):
        sid = self.full(touches="[src/a/**, tests/a/**]")
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", "docs: spec")
        git(self.tmp, "checkout", "-qb", "work")
        return sid

    def tags(self, sid):
        return "\n".join(f"# {sid}:{t}" for t in ("UT-01", "UT-02", "IT-01", "E2E-01"))

    def test_red_before_green_passes(self):
        sid = self.prepare()
        self.commit({"tests/a/test_a.py": self.tags(sid)}, f"test(a): red\n\nRefs: {sid}")
        self.commit({"src/a/a.py": "x = 1"}, f"feat(a): green\n\nRefs: {sid}")
        out = self.p.run("verify", sid, "--base", "main")
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_green_before_red_and_scope_fail(self):
        sid = self.prepare()
        self.commit({"src/a/a.py": "x = 1"}, f"feat(a): green\n\nRefs: {sid}")
        self.commit({"tests/a/test_a.py": self.tags(sid), "src/other.py": "y"}, f"test(a): red\n\nRefs: {sid}")
        out = self.p.run("verify", sid, "--base", "main").stdout
        self.assertIn("implementação antes dos testes", out)
        self.assertIn("fora de touches", out)

    def test_pr_check_ignores_narrative_refs_and_exempts_root_docs(self):
        other = self.full("Outra", touches="[src/b/**]")
        sid = self.prepare()
        self.p.run("set", sid, other, "status=approved", "approved_by=t", "approved_at=today")
        spec = self.p.path(sid)
        text = spec.read_text(encoding="utf-8")
        text = re.sub(r"\| (G[0-4] [^|]*)\| PENDING \| \| \|", r"| \1| PASS | ok | 2026-01-01 |", text)
        spec.write_text(text, encoding="utf-8")
        self.commit({"tests/a/test_a.py": self.tags(sid)}, f"test(a): red\n\nRefs: {sid}")
        self.commit({"src/a/a.py": "x = 1", "README.md": "# demo\natualizado\n"}, f"feat(a): green\n\nRefs: {sid}")
        body = f"## Como foi testado\nsegue o padrão da {other}\n\nRefs: {sid}"
        out = self.p.run("pr-check", "--base", "main", env={"PR_TITLE": f"feat: x [{sid}]", "PR_BODY": body})
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertNotIn(other + ":", out.stdout)


class CommandsTest(ProjectTest):
    def test_migrate_legacy_layout(self):
        legacy = self.tmp / "docs/specs/implemented"
        legacy.mkdir()
        (legacy / "2026-01-01-antiga.md").write_text("# Especificação Técnica: Antiga\n", encoding="utf-8")
        self.assertEqual(self.p.run("migrate", "--apply").returncode, 0)
        self.assertTrue(list((self.tmp / "docs/specs").glob("SPEC-0001-antiga.md")))

    def test_vendor_is_idempotent(self):
        first = self.p.run("vendor", "--agents", "--ci", "github", "--pr-template", "github", "--hooks").stdout
        self.assertIn("escrito: tools/sdd/spec_graph.py", first)
        second = self.p.run("vendor", "--agents", "--ci", "github", "--pr-template", "github", "--hooks").stdout
        self.assertNotIn("escrito:", second)
        self.assertEqual((self.tmp / "AGENTS.md").read_text().count("sdd:start"), 1)

    def test_status_reports_next_step(self):
        sid = self.full()
        self.assertIn("registre G0 = PASS", self.p.run("status", sid).stdout)


class RealProjectsTest(unittest.TestCase):
    """Read-only: runs the tool against real projects listed in SDD_REAL_PROJECTS (skipped when unset)."""

    def test_real_projects_do_not_crash(self):
        paths = [p for p in os.environ.get("SDD_REAL_PROJECTS", "").split(":") if p]
        if not paths:
            self.skipTest("SDD_REAL_PROJECTS not set")
        for path in paths:
            for command in (["validate"], ["waves"], ["status"], ["export"]):
                out = subprocess.run([sys.executable, str(SCRIPT), *command], cwd=path, capture_output=True, text=True)
                self.assertNotIn("Traceback", out.stderr, f"{path}: {command}\n{out.stderr}")


if __name__ == "__main__":
    unittest.main()
