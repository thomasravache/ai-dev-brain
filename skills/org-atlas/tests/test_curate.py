"""Curadoria de convenções: propostas inferred a partir dos sinais, decisão humana por confirm/reject e o formato de
conventions/<id>.md (SPEC-0037: UT-01 a UT-04, IT-01 a IT-04 e CT-01; ADR-0012).

Contrato esperado das funções de scripts/atlas.py (o Implementer segue estes testes):

    propose_conventions(signals: list, curation: dict | None = None) -> list[dict]
        `signals` = os sinais dos snapshots (references/collectors/github.md), cada um com `repository`;
        `curation` = a chave `curation` do atlas-config.yml ({min_share, min_total}; None = 0.6 e 20).
        Um padrão domina num repositório quando tem pelo menos `min_share` de pelo menos `min_total` itens
        (pr-titles: `pattern_counts[p] / total`). Quando a maioria (mais da metade) dos repositórios com o sinal
        tem o mesmo padrão dominante, a proposta tem `scope: "organization"`; senão há uma proposta por
        repositório em que ele domina, com `scope: "repository:<org>/<nome>"`. Cada proposta é um dict com pelo
        menos `id` (inclui o padrão: "pr-title-conventional" no escopo organization), `title`, `kind`
        (pr-title | branch-prefix | merge-method | pr-template), `scope` e `evidence`.

CLI (seção 6; mensagens podem ir para stdout ou stderr):
    curate propose [--json]   — também roda no fim de todo scan; "N nova(s), M atualizada(s), K esperando decisão"
    curate list [--status inferred|confirmed|rejected] [--json]
    curate confirm ID --by NOME --via "PR #n"|local
    curate reject  ID --by NOME --via "PR #n"|local [--reason TEXTO]
    exit 2: "confirm exige --by e --via" | "convenção não encontrada: ID" | "--via aceita 'PR #<n>' ou 'local'"
            | "convenção já está <status>"
"""
import ast
import datetime
import json
import re
import unittest

from helpers import SCRIPT, SKILL, Sandbox, fn, output

SPEC = "SPEC-0037"
FAKE = "{skill}/tests/fixtures/curate/signals.py"
CURATION_REFERENCE = SKILL / "references" / "curation.md"
ID = "pr-title-conventional"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VIA_RE = re.compile(r"^(PR #\d+|local)$")
REGION_RE = re.compile(r"<!-- atlas:begin ([\w-]+) -->(.*?)<!-- atlas:end \1 -->", re.DOTALL)
SUMMARY_RE = re.compile(r"(\d+) nova\(s\), (\d+) atualizada\(s\), (\d+) esperando decisão")
KINDS = ("pr-title", "branch-prefix", "merge-method", "pr-template")
STATUSES = ("inferred", "confirmed", "rejected")
REQUIRED_KEYS = ("id", "title", "kind", "scope", "status", "proposed_at", "confirmed_by", "confirmed_at",
                 "confirmed_via")
ALLOWED_KEYS = REQUIRED_KEYS + ("reason",)
DECISION_KEYS = ("confirmed_by", "confirmed_at", "confirmed_via")
MISSING_ARGS = "confirm exige --by e --via"
MISSING_ARGS_RE = re.compile(r"(confirm|reject) exige --by e --via")
BAD_VIA = "--via aceita 'PR #<n>' ou 'local'"
SAMPLE = ["feat(api): add refunds endpoint", "fix: retry on 503"]
REPOS = [f"acme/{c}" for c in "abcde"]


def f(name):
    return fn(name, SPEC)


def today_values():
    return {datetime.date.today().isoformat(), datetime.datetime.now(datetime.timezone.utc).date().isoformat()}


def pr_titles(repo, total, conventional, ticket_key=0, sample=None):
    signal = {"type": "pr-titles", "repository": repo, "total": total,
              "pattern_counts": {"conventional": conventional, "ticket_key": ticket_key,
                                 "other": total - conventional - ticket_key}}
    if sample is not None:
        signal["sample"] = sample
    return signal


def mixed(repo, total=30):
    """Sem padrão dominante: 40% other, 30% conventional, 30% ticket_key."""
    third = total * 3 // 10
    return pr_titles(repo, total, third, third)


def org_signals(total=30, conventional=21):
    """Os 5 repositórios com o mesmo padrão dominante (70% Conventional Commits em 30 PRs cada)."""
    return [pr_titles(repo, total, conventional, 3, SAMPLE if repo == "acme/a" else None) for repo in REPOS]


def per_repo_signals():
    """2 de 5 repositórios com Conventional Commits dominante: uma convenção por repositório."""
    return [pr_titles("acme/a", 30, 21), pr_titles("acme/b", 30, 24), mixed("acme/c"), mixed("acme/d"),
            mixed("acme/e")]


def frontmatter(text):
    """(frontmatter, resto) de um arquivo de convenção; sem frontmatter no início = AssertionError."""
    if not text.startswith("---\n"):
        raise AssertionError(f"o arquivo não começa com frontmatter ---:\n{text[:200]}")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise AssertionError("frontmatter sem o --- de fechamento")
    data = fn("parse_yaml", "SPEC-0032")(text[4:end + 1])
    return {k: "" if v is None else str(v) for k, v in data.items()}, text[end + 5:]


def regions(text):
    return {m.group(1): m.group(2) for m in REGION_RE.finditer(text)}


def outside(text):
    return REGION_RE.sub(lambda m: f"<!-- atlas:begin {m.group(1)} --><!-- atlas:end {m.group(1)} -->", text)


def add_team_notes(text, top_note, notes_note):
    """Uma linha do time logo depois do frontmatter e outra depois de "## Notas"."""
    end = text.find("\n---\n", 4) + 5
    text = text[:end] + f"\n{top_note}\n" + text[end:]
    lines = text.splitlines(keepends=True)
    marker = next(i for i, line in enumerate(lines) if line.strip() == "## Notas")
    lines.insert(marker + 1, f"\n{notes_note}\n")
    return "".join(lines)


# --------------------------------------------------------------------------- unitários


class ProposeTest(unittest.TestCase):
    def propose(self, signals, curation=None):
        return f("propose_conventions")(signals, curation)

    def test_dominant_pattern_becomes_a_convention_only_above_the_threshold(self):
        """SPEC-0037:UT-01"""
        proposals = self.propose([pr_titles("acme/api", 50, 35, 5)])  # 70% de 50
        self.assertEqual([p["id"] for p in proposals], [ID])
        self.assertEqual(proposals[0]["kind"], "pr-title")
        self.assertTrue(isinstance(proposals[0]["title"], str) and proposals[0]["title"].strip())
        self.assertIn("evidence", proposals[0])
        self.assertEqual(self.propose([pr_titles("acme/api", 50, 20, 15)]), [])  # 40% de 50
        self.assertEqual(self.propose([pr_titles("acme/api", 10, 7, 1)]), [])  # 70% de só 10

    def test_only_the_repository_above_the_threshold_gets_a_proposal(self):
        """SPEC-0037:UT-01"""
        signals = [pr_titles("acme/a", 50, 35, 5), pr_titles("acme/b", 50, 20, 15), pr_titles("acme/c", 10, 7, 1)]
        proposals = self.propose(signals)
        self.assertEqual(len(proposals), 1, proposals)
        self.assertEqual(proposals[0]["scope"], "repository:acme/a")
        self.assertIn("conventional", proposals[0]["id"])

    def test_threshold_limits_are_inclusive(self):
        """SPEC-0037:UT-01"""
        self.assertEqual([p["id"] for p in self.propose([pr_titles("acme/api", 20, 12)])], [ID])  # 60% de 20
        self.assertEqual(self.propose([pr_titles("acme/api", 20, 11)]), [])  # 55% de 20
        self.assertEqual(self.propose([pr_titles("acme/api", 19, 12)]), [])  # 63% de 19

    def test_thresholds_come_from_curation(self):
        """SPEC-0037:UT-01"""
        curation = {"min_share": 0.4, "min_total": 10}
        self.assertEqual([p["id"] for p in self.propose([pr_titles("acme/api", 50, 20, 15)], curation)], [ID])
        self.assertEqual([p["id"] for p in self.propose([pr_titles("acme/api", 10, 7, 1)], curation)], [ID])
        self.assertEqual(self.propose([pr_titles("acme/api", 50, 35, 5)], {"min_share": 0.8, "min_total": 20}), [])

    def test_missing_signals_give_no_proposal_and_no_error(self):
        """SPEC-0037:UT-01 (seção 5: sinal ausente para uma categoria -> nenhuma proposta, sem erro)"""
        self.assertEqual(self.propose([]), [])
        self.assertEqual(self.propose([], {"min_share": 0.6, "min_total": 20}), [])
        proposals = self.propose([pr_titles("acme/api", 50, 35, 5)])  # só pr-titles: nada dos outros tipos
        self.assertEqual([p["kind"] for p in proposals], ["pr-title"])


class ScopeTest(unittest.TestCase):
    def propose(self, signals):
        return f("propose_conventions")(signals, None)

    def test_most_repositories_with_the_same_pattern_give_one_organization_convention(self):
        """SPEC-0037:UT-02"""
        signals = [pr_titles(repo, 30, 21, 3) for repo in REPOS[:4]] + [mixed("acme/e")]
        proposals = [p for p in self.propose(signals) if p["kind"] == "pr-title"]
        self.assertEqual([(p["id"], p["scope"]) for p in proposals], [(ID, "organization")])

    def test_a_minority_of_repositories_gives_one_convention_per_repository(self):
        """SPEC-0037:UT-02"""
        proposals = [p for p in self.propose(per_repo_signals()) if p["kind"] == "pr-title"]
        self.assertEqual(sorted(p["scope"] for p in proposals), ["repository:acme/a", "repository:acme/b"])
        ids = [p["id"] for p in proposals]
        self.assertEqual(len(set(ids)), 2, ids)
        for pid in ids:
            self.assertIn("conventional", pid)

    def test_majority_means_more_than_half(self):
        """SPEC-0037:UT-02"""
        three_of_five = [pr_titles(r, 30, 21) for r in REPOS[:3]] + [mixed(r) for r in REPOS[3:]]
        self.assertEqual([p["scope"] for p in self.propose(three_of_five)], ["organization"])
        two_of_four = [pr_titles(r, 30, 21) for r in REPOS[:2]] + [mixed(r) for r in REPOS[2:4]]
        self.assertEqual(sorted(p["scope"] for p in self.propose(two_of_four)),
                         ["repository:acme/a", "repository:acme/b"])


# ---- UT-04: só confirm/reject gravam confirmed/rejected (checagem estática do atlas.py)

DECIDED = ("confirmed", "rejected")
DECIDER_RE = re.compile(r"confirm|reject|decid")
STATUS_TEXT_RE = re.compile(r"status:\s*[\"']?(confirmed|rejected)\b")


def _is_decided(node):
    return isinstance(node, ast.Constant) and node.value in DECIDED


def _has_decided(node):
    """O valor é ou contém confirmed/rejected (x if c else "rejected", "confirmed" or y...)."""
    return any(_is_decided(n) for n in ast.walk(node))


def status_writes(source):
    """(linha, função, o que) de cada lugar que grava status confirmed/rejected: {"status": ...},
    x["status"] = ..., status=... numa chamada e texto "status: confirmed|rejected" (docstrings não contam)."""
    found = []

    def visit(node, func, docstring=False):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node.name
        what = None
        if isinstance(node, ast.Dict):
            if any(isinstance(k, ast.Constant) and k.value == "status" and _has_decided(v)
                   for k, v in zip(node.keys, node.values)):
                what = "{'status': ...}"
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                key = target.slice if isinstance(target, ast.Subscript) else None
                if type(key).__name__ == "Index":  # Python 3.8
                    key = key.value
                if isinstance(key, ast.Constant) and key.value == "status" and _has_decided(node.value):
                    what = "[...]['status'] = ..."
        elif isinstance(node, ast.keyword) and node.arg == "status" and _has_decided(node.value):
            what = "status=..."
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str) and not docstring
              and STATUS_TEXT_RE.search(node.value)):
            what = "texto status: ..."
        if what:
            found.append((getattr(node, "lineno", 0), func, what))
        for child in ast.iter_child_nodes(node):
            visit(child, func, isinstance(node, ast.Expr) and isinstance(child, ast.Constant))

    visit(ast.parse(source), "<módulo>")
    return found


def decided_constants(source):
    """{"confirmed": {funções}, "rejected": {funções}} onde o texto aparece como constante."""
    result = {value: set() for value in DECIDED}

    def visit(node, func):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node.name
        if _is_decided(node):
            result[node.value].add(func)
        for child in ast.iter_child_nodes(node):
            visit(child, func)

    visit(ast.parse(source), "<módulo>")
    return result


class OnlyHumansDecideTest(unittest.TestCase):
    def test_the_checker_finds_a_status_write_outside_confirm_and_reject(self):
        """SPEC-0037:UT-04 (o próprio checador)"""
        planted = ('def propose(c):\n    c["status"] = "confirmed"\n    return {"status": "rejected"}\n'
                   'def render():\n    return "status: confirmed"\n'
                   'def cmd_curate(a, m):\n    m["status"] = "confirmed" if a else "rejected"\n'
                   'def cmd_curate_confirm(c):\n    c["status"] = "confirmed"\n')
        found = [(func, what) for _, func, what in status_writes(planted)]
        self.assertIn(("propose", "[...]['status'] = ..."), found)
        self.assertIn(("propose", "{'status': ...}"), found)
        self.assertIn(("render", "texto status: ..."), found)
        self.assertIn(("cmd_curate_confirm", "[...]['status'] = ..."), found)
        self.assertEqual(sorted({func for func, _ in found if not DECIDER_RE.search(func)}), ["cmd_curate", "propose", "render"])
        self.assertEqual(status_writes('def f():\n    """status: confirmed só por confirm."""\n'), [])

    def test_only_the_confirm_and_reject_functions_write_confirmed_or_rejected(self):
        """SPEC-0037:UT-04"""
        source = SCRIPT.read_text(encoding="utf-8")
        outside_deciders = [w for w in status_writes(source) if not DECIDER_RE.search(w[1])]
        self.assertEqual(outside_deciders, [], "só confirm/reject gravam status confirmed/rejected (ADR-0012)")
        constants = decided_constants(source)
        for value in DECIDED:
            deciders = sorted(func for func in constants[value] if DECIDER_RE.search(func))
            self.assertTrue(deciders, f"nenhuma função de confirm/reject grava {value!r} no atlas.py")


# --------------------------------------------------------------------------- integração (CLI)


def curate_config(curation=None):
    command = ["python3", FAKE, "signals", "{atlas}/facts/signals.json"]
    text = ("version: 1\norganization: Acme\nmode: local\nlanguage: auto\nstale_days: 14\n"
            "categories: [code, delivery]\ncollectors:\n  - id: signals\n    category: code\n"
            "    command: [" + ", ".join(json.dumps(a) for a in command) + "]\n    timeout: 60\n"
            "redaction: {extra_patterns: []}\n")
    if curation:
        text += f"curation: {{min_share: {curation[0]}, min_total: {curation[1]}}}\n"
    return text


class CurateCase(unittest.TestCase):
    """Atlas novo (init --mode local) com um coletor falso que imprime os sinais de facts/signals.json."""

    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        out = self.sandbox.init(mode="local")
        self.assertEqual(out.returncode, 0, output(out))
        self.atlas = self.sandbox.atlas
        self.conventions = self.atlas / "conventions"
        self.configure()

    def configure(self, curation=None):
        (self.atlas / "atlas-config.yml").write_text(curate_config(curation), encoding="utf-8")

    def set_signals(self, signals):
        folder = self.atlas / "facts"
        folder.mkdir(exist_ok=True)
        (folder / "signals.json").write_text(json.dumps({"signals": signals}), encoding="utf-8")

    def run_cli(self, *args, code=0):
        result = self.sandbox.run(*args)
        self.assertNotIn("Traceback", output(result), output(result))
        self.assertEqual(result.returncode, code, output(result))
        return result

    def scan(self):
        return self.run_cli("scan")

    def curate(self, *args, code=0):
        return self.run_cli("curate", *args, code=code)

    def files(self):
        return sorted(p.name for p in self.conventions.glob("*.md")) if self.conventions.is_dir() else []

    def text(self, cid=ID):
        path = self.conventions / f"{cid}.md"
        self.assertTrue(path.is_file(), f"conventions/{cid}.md não existe: {self.files()}")
        return path.read_text(encoding="utf-8")

    def meta(self, cid=ID):
        return frontmatter(self.text(cid))[0]

    def summary(self, result):
        match = SUMMARY_RE.search(output(result))
        self.assertIsNotNone(match, f"sem a linha 'N nova(s), M atualizada(s), K esperando decisão':\n{output(result)}")
        return [int(n) for n in match.groups()]

    def ids_with_scope(self):
        return {frontmatter((self.conventions / name).read_text(encoding="utf-8"))[0]["scope"]: name[:-3]
                for name in self.files()}


class ProposeCliTest(CurateCase):
    def test_scan_creates_the_inferred_convention_with_its_evidence(self):
        """SPEC-0037:IT-01"""
        self.set_signals(org_signals())
        result = self.scan()
        self.assertEqual(self.files(), [f"{ID}.md"])
        meta = self.meta()
        self.assertEqual(meta["id"], ID)
        self.assertEqual(meta["status"], "inferred")
        self.assertEqual(meta["kind"], "pr-title")
        self.assertEqual(meta["scope"], "organization")
        self.assertTrue(meta["title"].strip())
        self.assertIn(meta["proposed_at"], today_values())
        for key in DECISION_KEYS:
            self.assertEqual(meta.get(key, ""), "", key)
        evidence = regions(self.text()).get("evidence")
        self.assertIsNotNone(evidence, "sem a região <!-- atlas:begin evidence -->")
        for word in ("150", "105", "70", *REPOS, SAMPLE[0]):
            self.assertIn(word, evidence)
        self.assertIn("## Notas", [line.strip() for line in self.text().splitlines()])
        self.assertEqual(self.summary(result), [1, 0, 1])

    def test_a_new_scan_with_the_same_signals_changes_nothing_and_new_evidence_updates(self):
        """SPEC-0037:IT-01"""
        self.set_signals(org_signals())
        self.scan()
        first = self.text()
        result = self.scan()
        self.assertEqual(self.text(), first)
        self.assertEqual(self.summary(result), [0, 0, 1])
        self.set_signals(org_signals(total=40, conventional=32))
        result = self.scan()
        self.assertEqual(self.summary(result), [0, 1, 1])
        self.assertIn("200", regions(self.text())["evidence"])
        self.assertEqual(self.files(), [f"{ID}.md"])

    def test_no_signal_or_no_dominant_pattern_gives_no_convention_and_no_error(self):
        """SPEC-0037:IT-01 (seção 5: sinal ausente -> nenhuma proposta, sem erro)"""
        self.set_signals([])
        self.assertEqual(self.summary(self.scan())[0], 0)
        self.assertEqual(self.files(), [])
        self.set_signals([mixed(repo) for repo in REPOS] + [pr_titles("acme/f", 10, 9)])
        self.scan()
        self.assertEqual(self.files(), [])

    def test_curation_in_atlas_config_sets_the_thresholds(self):
        """SPEC-0037:IT-01"""
        self.set_signals([pr_titles(repo, 10, 5, 2) for repo in REPOS])  # 50% de 10
        self.scan()
        self.assertEqual(self.files(), [])
        self.configure(curation=(0.5, 10))
        self.scan()
        self.assertEqual(self.files(), [f"{ID}.md"])

    def test_curate_propose_runs_alone(self):
        """SPEC-0037:IT-01"""
        self.set_signals(org_signals())
        self.scan()
        self.text()
        (self.conventions / f"{ID}.md").unlink()
        self.assertEqual(self.summary(self.curate("propose")), [1, 0, 1])
        self.assertEqual(self.meta()["status"], "inferred")
        self.assertIsInstance(json.loads(self.curate("propose", "--json").stdout), dict)

    def test_one_file_per_repository_when_the_pattern_is_not_the_organization_one(self):
        """SPEC-0037:IT-01"""
        self.set_signals(per_repo_signals())
        self.scan()
        scopes = self.ids_with_scope()
        self.assertEqual(sorted(scopes), ["repository:acme/a", "repository:acme/b"], self.files())
        for cid in scopes.values():
            self.assertEqual(self.meta(cid)["id"], cid)
            self.assertEqual(self.meta(cid)["status"], "inferred")


class DecisionArgumentsTest(CurateCase):
    def setUp(self):
        super().setUp()
        self.set_signals(org_signals())
        self.scan()
        self.before = self.text()

    def assert_refused(self, args, message):
        result = self.curate(*args, code=2)
        if isinstance(message, re.Pattern):
            self.assertRegex(output(result), message)
        else:
            self.assertIn(message, output(result))
        self.assertEqual(self.text(), self.before, "a convenção mudou depois de um comando recusado")

    def test_confirm_without_by_or_via_exits_2(self):
        """SPEC-0037:UT-03"""
        for args in ((), ("--by", "thomas"), ("--via", "local"), ("--by", "", "--via", "local")):
            with self.subTest(args=args):
                self.assert_refused(("confirm", ID, *args), MISSING_ARGS)

    def test_reject_without_by_or_via_exits_2(self):
        """SPEC-0037:UT-03"""
        for args in ((), ("--by", "thomas"), ("--via", "local")):
            with self.subTest(args=args):
                self.assert_refused(("reject", ID, *args), MISSING_ARGS_RE)

    def test_invalid_via_exits_2(self):
        """SPEC-0037:UT-03"""
        for via in ("PR 3", "pr #3", "PR #", "#3", "PR #3a", "github", "Local"):
            for action in ("confirm", "reject"):
                with self.subTest(action=action, via=via):
                    self.assert_refused((action, ID, "--by", "thomas", "--via", via), BAD_VIA)

    def test_unknown_id_exits_2(self):
        """SPEC-0037:UT-03"""
        for action in ("confirm", "reject"):
            with self.subTest(action=action):
                self.assert_refused((action, "nope", "--by", "thomas", "--via", "local"),
                                    "convenção não encontrada: nope")


class ConfirmTest(CurateCase):
    def setUp(self):
        super().setUp()
        self.set_signals(org_signals())
        self.scan()

    def test_confirm_records_who_when_and_where_and_a_new_scan_keeps_it(self):
        """SPEC-0037:IT-02"""
        self.curate("confirm", ID, "--by", "thomas", "--via", "PR #3")
        meta = self.meta()
        self.assertEqual(meta["status"], "confirmed")
        self.assertEqual(meta["confirmed_by"], "thomas")
        self.assertIn(meta["confirmed_at"], today_values())
        self.assertEqual(meta["confirmed_via"], "PR #3")
        self.assertEqual(meta.get("reason", ""), "")
        result = self.scan()
        self.assertEqual(self.meta(), meta)
        self.assertEqual(self.summary(result)[2], 0)
        self.curate("propose")
        self.assertEqual(self.meta(), meta)

    def test_confirm_via_local(self):
        """SPEC-0037:IT-02"""
        self.curate("confirm", ID, "--by", "ana", "--via", "local")
        self.assertEqual((self.meta()["status"], self.meta()["confirmed_via"]), ("confirmed", "local"))

    def test_a_decided_convention_cannot_be_decided_again(self):
        """SPEC-0037:IT-02"""
        self.curate("confirm", ID, "--by", "thomas", "--via", "PR #3")
        before = self.text()
        for action in ("confirm", "reject"):
            with self.subTest(action=action):
                result = self.curate(action, ID, "--by", "ana", "--via", "local", code=2)
                self.assertIn("convenção já está confirmed", output(result))
                self.assertEqual(self.text(), before)

    def test_scan_and_propose_never_write_confirmed_or_rejected(self):
        """SPEC-0037:IT-02"""
        for _ in range(2):
            self.scan()
            self.curate("propose")
        self.set_signals(org_signals(total=40, conventional=36))
        self.scan()
        meta = self.meta()
        self.assertEqual(meta["status"], "inferred")
        for key in DECISION_KEYS:
            self.assertEqual(meta.get(key, ""), "", key)

    def test_list_filters_by_status(self):
        """SPEC-0037:IT-02"""
        self.assertIn(ID, output(self.curate("list", "--status", "inferred")))
        self.assertIn(ID, output(self.curate("list")))
        self.curate("confirm", ID, "--by", "thomas", "--via", "PR #3")
        self.assertIn(ID, output(self.curate("list", "--status", "confirmed")))
        self.assertNotIn(ID, output(self.curate("list", "--status", "inferred")))
        self.assertIn(ID, json.dumps(json.loads(self.curate("list", "--status", "confirmed", "--json").stdout)))
        self.assertNotIn(ID, json.dumps(json.loads(self.curate("list", "--status", "rejected", "--json").stdout)))


class RejectTest(CurateCase):
    def setUp(self):
        super().setUp()
        self.set_signals(org_signals())
        self.scan()

    def test_rejected_convention_is_not_proposed_again_and_only_its_evidence_changes(self):
        """SPEC-0037:IT-03"""
        self.curate("reject", ID, "--by", "ana", "--via", "local", "--reason", "metade dos PRs é de bot")
        meta = self.meta()
        self.assertEqual(meta["status"], "rejected")
        self.assertEqual(meta["confirmed_by"], "ana")
        self.assertIn(meta["confirmed_at"], today_values())
        self.assertEqual(meta["confirmed_via"], "local")
        self.assertEqual(meta["reason"], "metade dos PRs é de bot")
        files = self.files()
        before = self.text()
        self.set_signals(org_signals(total=40, conventional=32))
        result = self.scan()
        self.assertEqual(self.files(), files, "a rejeitada voltou como outra proposta")
        self.assertEqual(self.meta(), meta)
        self.assertEqual(outside(self.text()), outside(before))
        self.assertNotEqual(regions(self.text())["evidence"], regions(before)["evidence"])
        self.assertIn("200", regions(self.text())["evidence"])
        new, _, waiting = self.summary(result)
        self.assertEqual((new, waiting), (0, 0))

    def test_same_signals_after_reject_keep_it_rejected(self):
        """SPEC-0037:IT-03"""
        self.curate("reject", ID, "--by", "ana", "--via", "PR #12")
        before = self.text()
        self.scan()
        self.curate("propose")
        self.assertEqual(self.text(), before)
        self.assertEqual(self.files(), [f"{ID}.md"])
        self.assertEqual(self.meta()["confirmed_via"], "PR #12")
        self.assertEqual(self.meta().get("reason", ""), "")

    def test_a_rejected_convention_cannot_be_decided_again(self):
        """SPEC-0037:IT-03"""
        self.curate("reject", ID, "--by", "ana", "--via", "local")
        for action in ("confirm", "reject"):
            with self.subTest(action=action):
                result = self.curate(action, ID, "--by", "thomas", "--via", "PR #3", code=2)
                self.assertIn("convenção já está rejected", output(result))
        self.assertEqual(self.meta()["status"], "rejected")
        self.assertNotIn(ID, output(self.curate("list", "--status", "inferred")))
        self.assertIn(ID, output(self.curate("list", "--status", "rejected")))


class TeamTextTest(CurateCase):
    def setUp(self):
        super().setUp()
        self.set_signals(org_signals())
        self.scan()
        self.path = self.conventions / f"{ID}.md"
        self.edited = add_team_notes(self.text(), "Contexto do time: vale também para os repositórios novos.",
                                     "Nota do time: PR de bot pode fugir do padrão.")
        self.path.write_text(self.edited, encoding="utf-8")

    def test_team_note_survives_a_new_scan(self):
        """SPEC-0037:IT-04"""
        self.set_signals(org_signals(total=40, conventional=32))
        self.scan()
        text = self.text()
        self.assertEqual(outside(text), outside(self.edited))
        self.assertIn("Nota do time: PR de bot pode fugir do padrão.", text)
        self.assertIn("200", regions(text)["evidence"])

    def test_team_note_survives_confirm_and_a_new_scan(self):
        """SPEC-0037:IT-04"""
        self.curate("confirm", ID, "--by", "thomas", "--via", "PR #3")
        self.scan()
        _, body = frontmatter(self.text())
        _, edited_body = frontmatter(self.edited)
        self.assertEqual(outside(body), outside(edited_body))
        self.assertIn("Contexto do time: vale também para os repositórios novos.", body)


# --------------------------------------------------------------------------- contrato


class ConventionContractTest(CurateCase):
    def assert_contract(self, path):
        text = path.read_text(encoding="utf-8")
        meta, body = frontmatter(text)
        for key in REQUIRED_KEYS:
            self.assertIn(key, meta, f"{path.name}: falta {key}")
        self.assertEqual(sorted(set(meta) - set(ALLOWED_KEYS)), [], f"{path.name}: chaves fora do contrato")
        self.assertEqual(meta["id"], path.stem)
        self.assertTrue(meta["title"].strip())
        self.assertIn(meta["kind"], KINDS)
        self.assertRegex(meta["scope"], r"^(organization|repository:[^/\s]+/\S+)$")
        self.assertIn(meta["status"], STATUSES)
        self.assertRegex(meta["proposed_at"], DATE_RE)
        if meta["status"] == "inferred":
            for key in (*DECISION_KEYS, "reason"):
                self.assertEqual(meta.get(key, ""), "", f"{path.name}: {key}")
        else:
            self.assertTrue(meta["confirmed_by"].strip())
            self.assertRegex(meta["confirmed_at"], DATE_RE)
            self.assertRegex(meta["confirmed_via"], VIA_RE)
        if meta["status"] != "rejected":
            self.assertEqual(meta.get("reason", ""), "", f"{path.name}: reason só em reject")
        found = REGION_RE.findall(body)
        self.assertEqual([name for name, _ in found], ["evidence"], f"{path.name}: regiões {found}")
        self.assertTrue(found[0][1].strip(), f"{path.name}: evidência vazia")
        self.assertIn("## Notas", [line.strip() for line in body.splitlines()])

    def test_generated_conventions_follow_the_contract(self):
        """SPEC-0037:CT-01"""
        self.set_signals(per_repo_signals())
        self.scan()
        ids = list(self.ids_with_scope().values())
        self.assertEqual(len(ids), 2, self.files())
        self.curate("confirm", ids[0], "--by", "thomas", "--via", "PR #7")
        self.curate("reject", ids[1], "--by", "ana", "--via", "local", "--reason", "repositório legado")
        self.scan()
        statuses = sorted(self.meta(cid)["status"] for cid in ids)
        self.assertEqual(statuses, ["confirmed", "rejected"])
        for name in self.files():
            with self.subTest(file=name):
                self.assert_contract(self.conventions / name)

    def test_inferred_organization_convention_follows_the_contract(self):
        """SPEC-0037:CT-01"""
        self.set_signals(org_signals())
        self.scan()
        self.assertEqual(self.files(), [f"{ID}.md"])
        self.assert_contract(self.conventions / f"{ID}.md")

    def test_reference_documents_the_convention_contract(self):
        """SPEC-0037:CT-01"""
        self.assertTrue(CURATION_REFERENCE.is_file(), "references/curation.md não existe")
        text = CURATION_REFERENCE.read_text(encoding="utf-8")
        for word in (*ALLOWED_KEYS, *KINDS, *STATUSES, "organization", "evidence", "min_share", "min_total",
                     "PR #", "local"):
            self.assertIn(word, text, word)


if __name__ == "__main__":
    unittest.main()
