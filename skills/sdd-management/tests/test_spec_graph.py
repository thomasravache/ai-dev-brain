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
    "{{E2E-01 — jornada do usuário: passos e resultado visível [jornada: <id em critical_journeys>] | N/A — por que nenhuma jornada de usuário é afetada (obrigatório com user_facing: false)}}": "**E2E-01** — jornada principal",
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

    def test_user_facing_false_needs_reason(self):
        sid = self.full(user_facing="false")
        self.p.edit(sid, "- **E2E-01** — jornada principal", "- N/A — user_facing: false")
        self.p.edit(sid, "UT-01, IT-01, E2E-01", "UT-01, IT-01")
        self.assertIn("ERROR SPEC-0001: user_facing: false sem justificativa", self.p.validate(sid).stdout)
        self.p.run("set", sid, "status=approved", "approved_by=t", "approved_at=today")
        self.assertIn("WARN  SPEC-0001: user_facing: false sem justificativa", self.p.validate(sid).stdout)
        self.p.edit(sid, "- N/A — user_facing: false", "- N/A — job interno de reprocessamento, sem tela nem API pública")
        self.assertNotIn("sem justificativa", self.p.validate(sid).stdout)

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


class PrTitleTest(GitChecksTest):
    def ready_pr(self):
        sid = self.prepare()
        spec = self.p.path(sid)
        self.p.run("set", sid, "status=approved", "approved_by=t", "approved_at=today")
        text = re.sub(r"\| (G[0-4] [^|]*)\| PENDING \| \| \|", r"| \1| PASS | ok | 2026-01-01 |", spec.read_text(encoding="utf-8"))
        spec.write_text(text, encoding="utf-8")
        self.commit({"tests/a/test_a.py": self.tags(sid)}, f"test(a): red\n\nRefs: {sid}")
        self.commit({"src/a/a.py": "x = 1"}, f"feat(a): green\n\nRefs: {sid}")
        return sid

    def check(self, title, sid, extra_env=None):
        env = {"PR_TITLE": title, "PR_BODY": f"## Como foi testado\nRefs: {sid}"}
        env.update(extra_env or {})
        return self.p.run("pr-check", "--base", "main", env=env)

    def test_bad_title_fails_and_policy_can_relax(self):
        sid = self.ready_pr()
        out = self.check(f"corpo escrito em: /dev/null [{sid}]", sid)
        self.assertEqual(out.returncode, 1)
        self.assertIn("[PR] FAIL  título fora do Conventional Commits", out.stdout)
        self.assertEqual(self.check(f"feat(a): coisa boa [{sid}]", sid).returncode, 0)
        self.assertIn("caracteres (máximo 100)", self.check("feat: " + "x" * 120 + f" [{sid}]", sid).stdout)
        cfg = self.tmp / "docs/specs/sdd-config.yml"
        cfg.write_text(cfg.read_text() + "pr_title_policy: warn\n", encoding="utf-8")
        self.assertEqual(self.check(f"titulo livre [{sid}]", sid).returncode, 0)

    def test_no_spec_tag_anywhere_is_accepted(self):
        sid = self.ready_pr()
        out = self.check("build(deps) [no-spec]: bump lib", sid)
        self.assertNotIn("título fora do Conventional Commits", out.stdout)

    def test_github_annotations(self):
        sid = self.ready_pr()
        out = self.check(f"errado [{sid}]", sid, {"GITHUB_ACTIONS": "true"})
        self.assertIn("::error title=SDD::[PR] título fora do Conventional Commits", out.stdout)

    def test_pr_out_prints_only_the_title(self):
        sid = self.ready_pr()
        out = self.p.run("pr", sid, "--out", str(self.tmp / "pr.md"))
        self.assertEqual(out.stderr, "")
        self.assertEqual(len(out.stdout.strip().splitlines()), 1)
        self.assertTrue(out.stdout.startswith("feat"))


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

    def test_vendor_keeps_customized_files_and_refreshes_tool(self):
        self.p.run("vendor", "--ci", "github")
        wf = self.tmp / ".github/workflows/sdd.yml"
        wf.write_text(wf.read_text().replace("actions/checkout@v5", "actions/checkout@abc123 # v5"), encoding="utf-8")
        tool = self.tmp / "tools/sdd/spec_graph.py"
        tool.write_text("# antigo\n", encoding="utf-8")
        out = self.p.run("vendor", "--ci", "github").stdout
        self.assertIn("mantido (customizado no projeto", out)
        self.assertIn("abc123", wf.read_text())
        self.assertIn("SDD_TOOL_VERSION", tool.read_text())
        self.p.run("vendor", "--ci", "github", "--overwrite")
        self.assertNotIn("abc123", wf.read_text())

    def test_status_reports_next_step(self):
        sid = self.full()
        self.assertIn("registre G0 = PASS", self.p.run("status", sid).stdout)


class GateTest(ProjectTest):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = Project(self.tmp, config_extra=(
            'build: "python3 -c \\"print(\'build ok\')\\""\n'
            'test: "python3 -c \\"import sys; print(\'Ran 3 tests OK\'); sys.exit(0)\\""\n'
            'arch_test: ""\n'))

    def gate(self, sid, *args):
        return self.p.run("gate", sid, *args)

    def committed_spec(self):
        sid = self.full()
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", "docs: spec")
        return sid

    def row(self, sid, gate):
        return sg.gate_table(sg.Project(self.tmp).specs[sid])[gate]

    def test_order_is_enforced(self):
        sid = self.committed_spec()
        out = self.gate(sid, "G2", "--run")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("só depois de G0, G1", out.stderr)

    def test_run_generates_evidence_and_manual_is_flagged(self):
        sid = self.committed_spec()
        self.assertEqual(self.gate(sid, "G0", "--run").returncode, 0)
        self.assertIn("validate: 0 erro", self.row(sid, "G0")["evidence"])
        self.gate(sid, "G1", "--manual", "--evidence", "red visto no terminal")
        self.assertTrue(self.row(sid, "G1")["evidence"].startswith("MANUAL:"))
        self.assertIn("evidência manual", self.p.validate(sid).stdout)
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", "docs: gates")
        self.assertEqual(self.gate(sid, "G2", "--run").returncode, 0)
        evidence = self.row(sid, "G2")["evidence"]
        self.assertIn("build exit 0", evidence)
        self.assertIn("Ran 3 tests OK", evidence)

    def test_pass_without_run_is_refused(self):
        sid = self.committed_spec()
        out = self.gate(sid, "G0")
        self.assertIn("--run", out.stderr)

    def test_na_for_architecture_needs_pointer_or_waiver(self):
        sid = self.committed_spec()
        for g in ("G0",):
            self.gate(sid, g, "--run")
        self.gate(sid, "G1", "--manual", "--evidence", "x")
        self.gate(sid, "G2", "--manual", "--evidence", "x")
        out = self.gate(sid, "G3", "--na", "não temos suíte de arquitetura")
        self.assertIn("precisa apontar", out.stderr)
        other = self.full("Suíte de arquitetura")
        self.assertEqual(self.gate(sid, "G3", "--na", f"suíte será criada na {other}").returncode, 0)

    def test_dirty_tree_is_refused_for_command_gates(self):
        sid = self.committed_spec()
        self.gate(sid, "G0", "--run")
        self.gate(sid, "G1", "--manual", "--evidence", "x")
        (self.tmp / "README.md").write_text("mudou\n", encoding="utf-8")
        out = self.gate(sid, "G2", "--run")
        self.assertIn("não commitadas", out.stderr)

    def test_human_gate_needs_approver(self):
        sid = self.committed_spec()
        out = self.gate(sid, "H2")
        self.assertNotEqual(out.returncode, 0)

    def test_duplicate_g2_evidence_is_warned(self):
        a, b = self.full("A"), self.full("B")
        for sid in (a, b):
            text = self.p.path(sid).read_text(encoding="utf-8")
            text = re.sub(r"\| (G2 [^|]*)\| PENDING \| \| \|", r"| \1| PASS | dotnet test (commit 24ed311) | 2026-01-01 |", text)
            self.p.path(sid).write_text(text, encoding="utf-8")
        self.assertIn("evidência de G2 idêntica", self.p.validate().stdout)


class H2PolicyTest(ProjectTest):
    def test_auto_on_green_requires_recorded_decision(self):
        cfg = self.tmp / "docs/specs/sdd-config.yml"
        cfg.write_text(cfg.read_text() + "h2_policy: auto-on-green\n", encoding="utf-8")
        self.assertIn("exige h2_policy_approved_by", self.p.validate().stdout)
        cfg.write_text(cfg.read_text() + "h2_policy_approved_by: thomas\nh2_policy_approved_at: 2026-09-29\n", encoding="utf-8")
        self.assertNotIn("h2_policy", self.p.validate().stdout)

    def test_repeated_h2_text_suggests_policy(self):
        for name in ("A", "B", "C"):
            sid = self.full(name)
            text = self.p.path(sid).read_text(encoding="utf-8")
            text = re.sub(r"\| (H2 [^|]*)\| PENDING \| \| \|", r"| \1| PASS | Autorização permanente do usuário | 2026-01-01 |", text)
            self.p.path(sid).write_text(text, encoding="utf-8")
        self.assertIn("declare h2_policy: auto-on-green", self.p.validate().stdout)


class ChangeFlowTest(ProjectTest):
    def commit(self, name, content, message):
        (self.tmp / name).parent.mkdir(parents=True, exist_ok=True)
        (self.tmp / name).write_text(content, encoding="utf-8")
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", message)

    def test_direct_code_and_record_commits_are_distinguished(self):
        sid = self.full()
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", "docs: adota sdd")
        self.commit("src/a.py", "x", "feat: direto na main")
        self.commit(f"docs/specs/{self.p.path(sid).name}", self.p.path(sid).read_text() + "\n", "docs(specs): gate")
        out = self.p.validate().stdout
        self.assertIn("1 commit(s) de código direto(s)", out)
        self.assertRegex(out, r"\d+ commit\(s\) de registros SDD direto\(s\)")

    def test_local_merge_without_change_request_is_flagged(self):
        self.full()
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", "docs: adota sdd")
        git(self.tmp, "checkout", "-qb", "feature")
        self.commit("src/a.py", "x", "feat: a")
        git(self.tmp, "checkout", "-q", "main")
        git(self.tmp, "merge", "-q", "--no-ff", "feature", "-m", "merge: feature into main")
        self.assertIn("merge(s) na main sem PR/MR", self.p.validate().stdout)
        git(self.tmp, "checkout", "-qb", "feature2")
        self.commit("src/b.py", "y", "feat: b")
        git(self.tmp, "checkout", "-q", "main")
        git(self.tmp, "merge", "-q", "--no-ff", "feature2", "-m", "Merge pull request #7 from org/feature2")
        self.assertIn("1 merge(s) na main sem PR/MR", self.p.validate().stdout)

    def test_direct_flow_requires_reason(self):
        cfg = self.tmp / "docs/specs/sdd-config.yml"
        cfg.write_text(cfg.read_text() + "change_flow: direct\n", encoding="utf-8")
        self.assertIn("exige change_flow_reason", self.p.validate().stdout)

    def test_vendor_codeowners(self):
        self.assertNotEqual(self.p.run("vendor", "--codeowners", "github").returncode, 0)
        self.p.run("vendor", "--codeowners", "github", "--owner", "@thomas", "--ci", "github")
        owners = (self.tmp / ".github/CODEOWNERS").read_text()
        self.assertIn("/tools/sdd/ @thomas", owners)
        self.assertIn("/.github/workflows/sdd.yml @thomas", owners)


class PillarsTest(ProjectTest):
    def set_profile(self, profile, extra=""):
        cfg = self.tmp / "docs/specs/sdd-config.yml"
        cfg.write_text(cfg.read_text() + f"pillars:\n  profile: {profile}\n" + extra, encoding="utf-8")

    def test_catalog_and_baselines_are_consistent(self):
        for pid in sg.PILLARS:
            self.assertTrue((SKILL / "references" / "adr-baseline" / f"{pid}.md").exists(), pid)
            self.assertIn(f"`{pid}`", (SKILL / "references" / "pillars.md").read_text())

    def test_opt_in_and_coverage_states(self):
        self.assertNotIn("pilares", self.p.validate().stdout)
        self.set_profile("minimo", "  waived:\n    custo: \"protótipo interno sem orçamento\"\n")
        out = self.p.validate().stdout
        self.assertIn("sem decisão no perfil minimo", out)
        self.assertEqual(self.p.run("new-adr", "--baseline", "testes").returncode, 0)
        coverage = {pid: state for pid, _, state, _ in sg.pillar_coverage(sg.Project(self.tmp))}
        self.assertEqual(coverage["testes"], "proposto")
        self.assertEqual(coverage["entrega"], "sem decisão")
        self.assertNotIn("custo", coverage)  # custo is padrao-level, not required by minimo

    def test_test_tooling_table_per_level(self):
        self.set_profile("minimo")
        aid = self.p.run("new-adr", "--baseline", "testes").stdout.split()[0]
        path = next((self.tmp / "docs/adr").glob(f"{aid}-*.md"))
        text = re.sub(r"\{\{([^{}]*)\}\}", lambda m: m.group(1).split(" | ")[0], path.read_text(encoding="utf-8"))
        text = text.replace("- Opção A — ferramenta ou abordagem\n- Opção B", "- Ferramenta X\n- Ferramenta Y")
        text = text.replace("Referências neutras:", "Fonte: https://example.org (2026-10-02). Referências neutras:")
        path.write_text(text, encoding="utf-8")
        self.assertNotIn("pilar testes", self.p.validate().stdout)
        path.write_text(text.replace("| E2E | ferramenta |", "| E2E | N/A |"), encoding="utf-8")
        self.assertIn(f"ERROR {aid}: pilar testes: N/A no nível E2E sem motivo", self.p.validate().stdout)
        path.write_text(re.sub(r"\| Integração \|[^\n]*\n", "", text), encoding="utf-8")
        self.assertIn("sem decisão para o nível Integração", self.p.validate().stdout)
        self.p.run("set", aid, "status=accepted")
        self.assertIn(f"WARN  {aid}: pilar testes sem decisão para o nível Integração", self.p.validate().stdout)

    def test_foundation_epic_blocked_at_g0_with_missing_pillars(self):
        self.set_profile("minimo")
        epic = self.p.new("epic", "Fundação")
        self.p.fill(epic, type="foundation")
        self.assertIn("épico de fundação não passa do G0", self.p.validate(epic).stdout + self.p.validate().stdout)

    def test_waiver_needs_reason_and_unknown_pillar_fails(self):
        self.set_profile("minimo", "  waived:\n    entrega: curto\n    inventado: \"motivo suficientemente longo\"\n")
        out = self.p.validate().stdout
        self.assertIn("pillars.waived.entrega: motivo", out)
        self.assertIn("pilar desconhecido 'inventado'", out)

    def test_recurrent_na_is_reported(self):
        self.set_profile("minimo")
        for name in ("A", "B", "C"):
            sid = self.full(name)
            text = self.p.path(sid).read_text(encoding="utf-8")
            text = re.sub(r"\| (G6 [^|]*)\| PENDING \| \| \|", r"| \1| N/A | sem ambiente remoto por enquanto | 2026-01-01 |", text)
            self.p.path(sid).write_text(text, encoding="utf-8")
        self.assertIn("G6 N/A em 3 specs", self.p.validate().stdout)


class AdrQualityTest(ProjectTest):
    def adr(self, origin, options, sources, consequences="- **Ruim**, porque custa mais"):
        out = self.p.run("new-adr", "--title", f"Decisão {origin}")
        aid = out.stdout.split()[0]
        path = next((self.tmp / "docs/adr").glob(f"{aid}-*.md"))
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"## Opções Consideradas\n.*?(?=\n## )", "## Opções Consideradas\n" + options + "\n", text, flags=re.S)
        text = re.sub(r"## Mais Informações\n.*", "## Mais Informações\n" + sources + "\n", text, flags=re.S)
        text = re.sub(r"### Consequências\n.*?(?=\n### )", "### Consequências\n" + consequences + "\n", text, flags=re.S)
        text = re.sub(r"\{\{([^{}]*)\}\}", lambda m: m.group(1), text)
        path.write_text(text, encoding="utf-8")
        self.p.run("set", aid, f"origin={origin}")
        return aid

    def test_decision_needs_options_and_sources(self):
        aid = self.adr("decision", "- Opção A", "sem nada")
        out = self.p.validate(aid).stdout
        self.assertIn("menos de 2 opções", out)
        self.assertIn("sem fontes", out)
        ok = self.adr("decision", "- Opção A\n- Opção B", "https://example.org/docs (2026-09-30)")
        self.assertNotIn("WARN", self.p.validate(ok).stdout)

    def test_user_choice_is_respected_but_needs_risks(self):
        aid = self.adr("user", "- Vercel (escolhida pelo usuário)", "", consequences="- **Boa**, porque o time conhece")
        out = self.p.validate(aid).stdout
        self.assertNotIn("menos de 2 opções", out)
        self.assertIn("sem riscos registrados", out)


class JourneysTest(ProjectTest):
    def test_journey_states_and_unknown_ids(self):
        cfg = self.tmp / "docs/specs/sdd-config.yml"
        cfg.write_text(cfg.read_text() + 'critical_journeys:\n  checkout: "Compra"\n  login: "Entrar"\n', encoding="utf-8")
        out = self.p.validate().stdout
        self.assertIn("jornadas críticas sem E2E em nenhuma spec: checkout, login", out)
        sid = self.full()
        self.p.edit(sid, "- **E2E-01** — jornada principal", "- **E2E-01** — jornada principal [jornada: checkout]")
        rows, _ = sg.journey_coverage(sg.Project(self.tmp))
        self.assertEqual({jid: state for jid, _, state, _ in rows}, {"checkout": "planejada", "login": "descoberta"})
        self.p.edit(sid, "[jornada: checkout]", "[jornada: pagamento]")
        self.assertIn("[jornada: pagamento], que não está em critical_journeys", self.p.validate(sid).stdout + self.p.validate().stdout)


class BoardTest(ProjectTest):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = Project(self.tmp, config_extra=(
            "tracker:\n  provider: jira\n  project: PAY\n  statuses:\n    proposed: \"To Do\"\n    approved: \"Selected\"\n"
            "    in-progress: \"In Progress\"\n    implemented: \"Done\"\n    deprecated: \"Won't Do\"\n"
            "  issue_types:\n    epic: Epic\n    feature: Story\n"))

    def test_structure_and_drift(self):
        import json
        out = json.loads(self.p.run("sync", "--structure").stdout)
        self.assertIn("In Progress", out["structure"]["statuses"])
        self.assertIn("sdd-bloqueado", out["structure"]["labels"])
        sid = self.full()
        self.p.set(sid, external="[jira:PAY-1]")
        snap = self.tmp / "board.json"
        snap.write_text(json.dumps({"structure": {"statuses": ["To Do", "Done"], "issue_types": ["Story"], "labels": ["sdd"]},
                                    "items": [{"ref": "jira:PAY-1", "status": "Done", "blocked": False}]}), encoding="utf-8")
        result = self.p.run("sync", "--board", str(snap), "--json", "--check")
        self.assertEqual(result.returncode, 1)
        ops = {(o["op"], o.get("name") or o.get("to")) for o in json.loads(result.stdout)["operations"]}
        self.assertIn(("create_status", "In Progress"), ops)
        self.assertIn(("create_issue_type", "Epic"), ops)
        self.assertIn(("create_label", "sdd-bloqueado"), ops)
        self.assertIn(("transition", "To Do"), ops)

    def test_h1_via_pr_approval(self):
        cfg = self.tmp / "docs/specs/sdd-config.yml"
        cfg.write_text(cfg.read_text() + "h1_policy: pr-approval\n", encoding="utf-8")
        sid = self.full(external="[jira:PAY-2]")
        self.p.run("set", sid, "status=approved", "approved_by=revisora", "approved_at=today")
        self.assertIn("registre approved_via", self.p.validate().stdout)
        self.p.set(sid, approved_via='"PR #12"')
        self.assertNotIn("approved_via", self.p.validate().stdout)


class WorktreeTest(ProjectTest):
    def test_default_path_is_outside_repo_and_create_works(self):
        sid = self.full("Minha feature")
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", "docs: spec")
        out = self.p.run("worktree", sid).stdout.split("\n")
        expected = (self.tmp.parent / f"{self.tmp.name}.worktrees" / f"{sid}-minha-feature").resolve()
        self.assertEqual(Path(out[0]), expected)
        self.assertEqual(out[1], f"sdd/{sid}-minha-feature")
        try:
            created = self.p.run("worktree", sid, "--create")
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertTrue((expected / "README.md").exists())
            self.p.run("set", sid, "status=deprecated")
            self.assertIn("worktree esquecida", self.p.validate().stdout)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(expected)], cwd=self.tmp, capture_output=True)
            shutil.rmtree(expected.parent, ignore_errors=True)

    def test_misplaced_worktrees_are_reported(self):
        sid = self.full("Outra feature")
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", "docs: spec")
        sibling = (self.tmp.parent / f"{self.tmp.name}-{sid}").resolve()
        inside = (self.tmp / ".worktrees" / "x").resolve()
        try:
            git(self.tmp, "worktree", "add", "-q", str(sibling), "-b", f"sdd/{sid}-outra-feature")
            git(self.tmp, "worktree", "add", "-q", str(inside), "-b", "tmp-inside")
            out = self.p.validate().stdout
            self.assertIn(f"worktree {sibling} fora do worktree_dir", out)
            self.assertIn(f"{self.tmp.name}.worktrees/{sid}-outra-feature", out)
            self.assertIn("DENTRO do repositório e fora do .gitignore", out)
            self.assertIn("fora do worktree_dir", self.p.run("status").stdout)
            cfg = self.tmp / "docs/specs/sdd-config.yml"
            cfg.write_text(cfg.read_text() + "worktree_allow:\n  - \".worktrees/**\"\n", encoding="utf-8")
            self.assertNotIn(str(inside), self.p.validate().stdout)
        finally:
            for path in (sibling, inside):
                subprocess.run(["git", "worktree", "remove", "--force", str(path)], cwd=self.tmp, capture_output=True)
            shutil.rmtree(sibling, ignore_errors=True)

    def test_inside_repo_must_be_ignored(self):
        cfg = self.tmp / "docs/specs/sdd-config.yml"
        cfg.write_text(cfg.read_text() + "worktree_dir: .worktrees\n", encoding="utf-8")
        self.assertIn("não está no .gitignore", self.p.validate().stdout)
        (self.tmp / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
        self.assertNotIn("não está no .gitignore", self.p.validate().stdout)


class UpgradeTest(ProjectTest):
    def test_upgrade_restores_sections_keys_and_gate_rows(self):
        sid = self.full()
        text = self.p.path(sid).read_text(encoding="utf-8")
        text = re.sub(r"## 9\. Questões em Aberto\n.*?(?=## 10\.)", "", text, flags=re.S)
        text = re.sub(r"## 13\. Registro de Impedimentos\n.*?(?=## 14\.)", "", text, flags=re.S)
        text = text.replace("external: []\n", "").replace("| G7 Pronto & Docs | PENDING | | |\n", "")
        self.p.path(sid).write_text(text, encoding="utf-8")
        before = self.p.validate(sid).stdout
        self.assertIn("seção obrigatória ausente", before)
        self.assertEqual(self.p.run("upgrade", sid).returncode, 0)
        self.assertEqual(self.p.path(sid).read_text(encoding="utf-8"), text)  # dry run changes nothing
        self.assertEqual(self.p.run("upgrade", sid, "--apply").returncode, 0)
        upgraded = self.p.path(sid).read_text(encoding="utf-8")
        self.assertIn("external: []", upgraded)
        self.assertIn("| G7 Pronto & Docs | PENDING | | |", upgraded)
        self.assertLess(upgraded.index("## Questões em Aberto"), upgraded.index("## 10. Aprovação"))
        self.assertNotIn("seção obrigatória ausente", self.p.validate(sid).stdout)


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
