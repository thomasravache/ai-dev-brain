"""Ajustes da primeira retrospectiva (SPEC-0078): histórico de reprovações, entregue sem fechar, versão no modo
privado e ajustes do `retro`.

Contrato esperado de scripts/spec_graph.py (o Implementer segue estes testes):

Histórico de reprovações — subseção dentro da seção "Registro de Gates", abaixo da tabela:

    ### Histórico de reprovações
    - <G> FAIL <AAAA-MM-DD> — <evidência> — <sha|?>
    - <G> PASS <AAAA-MM-DD> — depois de <n> reprovação(ões)

    Escrita só pelo `gate`, com a data de `today()` (a mesma função que data a linha da tabela); criada na primeira
    reprovação; linhas antigas nunca são reescritas. <sha> é o SHA curto do HEAD (`head_ref`), ou "?" fora do git.
    (Emenda v2) A linha FAIL usa a evidência gravada na tabela: no `gate --run` ela já termina em " — <sha>" e entra
    como está, sem repetir o sha ("- G2 FAIL <data> — <evidência da tabela>"); o `--fail` acrescenta " — <sha|?>"
    ao motivo ("- G2 FAIL <data> — <motivo> — <sha|?>").

    gate_history(doc: Doc) -> list[dict]
        Linhas válidas da subseção, na ordem do arquivo. Sem subseção: [].
        FAIL: {"gate": "G4", "status": "FAIL", "date": "AAAA-MM-DD", "evidence": str, "sha": str}
              (evidence = texto entre a data e o ÚLTIMO " — "; sha = o que vem depois dele: hex de 7 a 40 ou "?")
        PASS: {"gate": "G4", "status": "PASS", "date": "AAAA-MM-DD", "after": int}
        Linha fora do formato é ignorada, sem erro: sem o marcador "- ", gate fora de GATE_ROWS, status que não é
        FAIL/PASS, data inválida ou sem os separadores " — ".

    consecutive_fails(doc: Doc, gate: str) -> int
        Linhas FAIL válidas do gate depois da última linha PASS válida desse gate (todas, se não houver PASS).

    gate SPEC-X <G> --fail "motivo" | --run que reprova
        tabela como hoje + linha FAIL no histórico. Com consecutive_fails >= 3, imprime no stdout:
        "⚠ <n> reprovações seguidas em <G> — registre `impede SPEC-X --type falha` e escale ao humano"
        O aviso sai sempre na 3ª reprovação seguida ou depois, com ou sem impedimento `falha` aberto (Emenda v2).
    gate SPEC-X <G> (PASS ou N/A) com consecutive_fails(G) > 0
        acrescenta "- <G> PASS <data> — depois de <n> reprovação(ões)"; sem reprovações antes, a spec só muda na tabela.

Entregue sem fechar e avisos do `status`/`next`:

    unclosed_specs(project: Project, today: datetime.date) -> list[tuple[str, int | None]]
        (ID, dias desde a data do G5) das specs não épicas em approved ou in-progress, G5 = PASS e G7 != PASS, ordenadas por
        ID; dias = None quando a data do G5 é inválida.

    status_body(project, ids, today: datetime.date | None = None)    (None = dt.date.today())
        Só sem IDs (com IDs, nenhum desses avisos), antes da lista das specs abertas (junto dos outros avisos "⚠"):
        "⚠ entregue sem fechar: SPEC-X — G5 há <d> dia(s); feche o G7 (Relatório de Entrega)"
        e, para cada spec in-progress com consecutive_fails >= 3 num gate e sem impedimento `falha` aberto:
        "⚠ SPEC-X: <n> reprovações seguidas em <G> — `impede SPEC-X --type falha`"

    print_next(project, plan, today: datetime.date | None = None)    (None = dt.date.today())
        Com specs entregues sem G7, uma linha que começa por "A fechar" seguida de uma linha por spec, indentada com
        dois espaços, com o ID e "<d> dia(s)" desde o G5 (ex.: "  SPEC-0001 — G5 há 9 dia(s)"). Sem nenhuma, a seção
        não aparece.

`private init`: ao criar o sdd-config.yml do spec_root, grava sdd_version = SDD_TOOL_VERSION (write_config_key);
um sdd-config.yml que já existe mantém o seu sdd_version.

`retro` (só acréscimos ao contrato da SPEC-0074; retro_version continua 1):

    retro_metrics(...)["tool"]["state"]   "atual" | "atrasada" | "desconhecida"
    retro_metrics(...)["fail_recorded"]   int: linhas FAIL válidas (gate_history) somadas em todas as specs
    retro_findings: R1 para atrasada (action cita "whats-new" e "vendor --force"; privado: "whats-new --ack") e
        desconhecida (action cita "whats-new --ack" e não cita "vendor --force"); R5 dispara só com
        fail_history == 0, fail_recorded == 0, nenhum FAIL atual e >= 20 PASS de G1–G5 (None nunca dispara).
    Markdown: fail_history None aparece como "sem histórico" na tabela de Projetos (sem git, sem commits, ilegível).
    impediments.old e R7: ID no formato IMP-<dígitos> é mantido como está; fora dele aparece como "IMP-?" (o texto
    da célula nunca sai).
    stale/unclosed: IDs repetidos (specs sem `id` com o mesmo prefixo SPEC-NNNN) aparecem uma vez.
    Registro com spec_root que não é texto: entrada em "Ignorados" com motivo "registro inválido", exit 0.
    A evidência do histórico nunca sai no Markdown nem no JSON.

Isolamento: diretórios temporários resolvidos; HOME, SDD_CONFIG_HOME, XDG_* e CLAUDE_CONFIG_DIR temporários e
GIT_CEILING_DIRECTORIES no diretório temporário. A data de hoje é fixa por parâmetro (ou por `today()` simulado)
sempre que o resultado depende dela.
"""
import datetime as dt
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
SKILL = TESTS.parent
SCRIPT = SKILL / "scripts" / "spec_graph.py"
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(TESTS))
import spec_graph as sg
from test_private_mode import PrivateEnv
from test_retro import (
    GEN,
    SHA,
    git,
    git_init,
    isolated_env,
    neutral_metrics,
    pass_all,
    run_retro,
    section,
    spec_md,
    write_spec,
)
from test_spec_graph import FILL

VERSION = sg.SDD_TOOL_VERSION
TODAY = dt.date(2026, 11, 17)
HISTORY_TITLE = "### Histórico de reprovações"

_USER_ENV = {}


def setUpModule():
    """Isola o registro do usuário (projects.json) nas chamadas em processo, como as demais suítes."""
    _USER_ENV["SDD_CONFIG_HOME"] = os.environ.get("SDD_CONFIG_HOME")
    _USER_ENV["dir"] = tempfile.mkdtemp()
    os.environ["SDD_CONFIG_HOME"] = _USER_ENV["dir"]


def tearDownModule():
    if _USER_ENV["SDD_CONFIG_HOME"] is None:
        os.environ.pop("SDD_CONFIG_HOME", None)
    else:
        os.environ["SDD_CONFIG_HOME"] = _USER_ENV["SDD_CONFIG_HOME"]
    shutil.rmtree(_USER_ENV["dir"], ignore_errors=True)


def fn(name, *params):
    """Função de spec_graph exigida pela SPEC-0078 (com os parâmetros nomeados); ausente = falha pelo motivo certo."""
    f = getattr(sg, name, None)
    if f is None:
        raise AssertionError(f"spec_graph.{name} não existe (SPEC-0078)")
    missing = [p for p in params if p not in inspect.signature(f).parameters]
    if missing:
        raise AssertionError(f"spec_graph.{name} não aceita {', '.join(missing)} (SPEC-0078)")
    return f


def with_history(text: str, lines) -> str:
    """Acrescenta a subseção do histórico ao fim da seção Registro de Gates (antes do próximo cabeçalho '## ')."""
    head = re.search(r"^## .*Registro de Gates.*$", text, re.MULTILINE)
    end = text.index("\n## ", head.end())
    block = f"\n{HISTORY_TITLE}\n" + "".join(f"{line}\n" for line in lines)
    return text[:end] + block + text[end:]


def gates_section(text: str) -> str:
    """Texto da seção '## ... Registro de Gates' (com as subseções), até o próximo '## '."""
    head = re.search(r"^## .*Registro de Gates.*$", text, re.MULTILINE)
    end = text.find("\n## ", head.end())
    return text[head.end():end if end >= 0 else len(text)]


def call(*argv):
    """Roda a CLI em processo (para simular `today()`); devolve (exit, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = sg.main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


def capture(func, *args, **kwargs) -> str:
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        func(*args, **kwargs)
    return out.getvalue()


def load(root: Path, sid: str):
    return sg.Project(root).specs[sid]


def short_head(root: Path, env: dict) -> str:
    return git(root, env, "rev-parse", "--short", "HEAD").strip()


def commit_all(root: Path, env: dict, message: str):
    git(root, env, "add", "-A")
    git(root, env, "commit", "-qm", message)


class TempTest(unittest.TestCase):
    """Diretório temporário resolvido; o ambiente do processo aponta para HOME, config e XDG temporários."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = isolated_env(self.tmp)
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)


class CliProject:
    """Repositório git temporário com spec do template preenchida, rodando a CLI como processo (ADR-0002)."""

    def __init__(self, root: Path, env: dict, config_extra: str = ""):
        self.root, self.env = root, env
        (root / "docs" / "specs").mkdir(parents=True)
        (root / "docs/specs/sdd-config.yml").write_text(
            "base_branch: main\nmax_parallel: 2\ntest_paths:\n  - \"tests/**\"\n" + config_extra, encoding="utf-8")
        (root / "README.md").write_text("# demo\n", encoding="utf-8")
        git_init(root, env)

    def run(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.root, capture_output=True, text=True,
                              env=self.env, check=False)

    def ok(self, *args):
        res = self.run(*args)
        assert res.returncode == 0, " ".join(args) + "\n" + res.stdout + res.stderr
        return res

    def path(self, sid) -> Path:
        return next((self.root / "docs/specs").glob(f"{sid}-*.md"))

    def full_spec(self, title="Funcionalidade") -> str:
        sid = self.ok("new", "--tier", "full", "--title", title).stdout.split()[0]
        p = self.path(sid)
        text = p.read_text(encoding="utf-8")
        for a, b in FILL.items():
            text = text.replace(a, b)
        p.write_text(re.sub(r"\{\{([^{}]*)\}\}", lambda m: m.group(1), text), encoding="utf-8")
        self.ok("set", sid, "touches=[src/a/**, tests/a/**]")
        return sid

    def plan(self, sid):
        """Aprova, preenche o Checklist (fase PLAN) e marca in-progress, como uma spec pronta para executar."""
        self.ok("set", sid, "status=approved", "approved_by=t", "approved_at=today")
        p = self.path(sid)
        text = p.read_text(encoding="utf-8")
        text = re.sub(r"^(## .*Checklist.*)$", r"\1\n- [ ] Fase 1 (test-writer): testes do plano", text, count=1,
                      flags=re.MULTILINE)
        p.write_text(text, encoding="utf-8")
        self.ok("set", sid, "status=in-progress")

    def set_rows(self, sid, rows: dict):
        """rows: {gate: (status, evidência, data)} gravados direto na tabela, como um projeto que já andou."""
        p = self.path(sid)
        text = p.read_text(encoding="utf-8")
        for gate, (status, evidence, date) in rows.items():
            text, n = re.subn(rf"^\| ({gate} [^|]*)\| PENDING \| \| \|$", rf"| \1| {status} | {evidence} | {date} |",
                              text, flags=re.MULTILINE)
            assert n == 1, gate
        p.write_text(text, encoding="utf-8")

    def commit(self, message):
        commit_all(self.root, self.env, message)


# --------------------------------------------------------------------------- testes de caracterização

class FirstTryTest(TempTest):
    def test_gate_passing_first_time_changes_only_the_table(self):
        """SPEC-0078:CH-01 — `--run` verde e `--na` na primeira tentativa: spec igual à de hoje, sem subseção nova.
        (guarda: passa antes da mudança)
        """
        p = CliProject(self.tmp / "proj", self.env, config_extra=(
            'test: "python3 -c \\"print(\'Ran 3 tests OK\')\\""\n'))
        sid = p.full_spec()
        other = p.full_spec("Suíte de arquitetura")
        p.set_rows(sid, {"G0": ("PASS", GEN["G0"], "2026-11-10"), "G1": ("PASS", GEN["G1"], "2026-11-10")})
        p.commit("docs: spec")
        before = p.path(sid).read_text(encoding="utf-8").split("\n")

        self.assertEqual(p.run("gate", sid, "G2", "--run").returncode, 0)
        self.assertEqual(p.run("gate", sid, "G3", "--na", f"suíte de arquitetura será criada na {other}").returncode, 0)

        text = p.path(sid).read_text(encoding="utf-8")
        self.assertNotIn("Histórico de reprovações", text)
        after = text.split("\n")
        self.assertEqual(len(after), len(before), "nenhuma linha acrescentada")
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual([b.split("|")[1].split()[0] for _, b in changed], ["G2", "G3"], changed)
        table = sg.gate_table(load(p.root, sid))
        self.assertEqual((table["G2"]["status"], table["G3"]["status"]), ("PASS", "N/A"))


class OldReadersTest(TempTest):
    def build(self, root: Path, history=()):
        """Spec aprovada com G0–G4 PASS e commits red/green no branch work; `history` vai abaixo da tabela."""
        p = CliProject(root, self.env)
        sid = p.full_spec()
        p.ok("set", sid, "status=approved", "approved_by=t", "approved_at=today")
        p.set_rows(sid, {g: ("PASS", GEN[g], "2026-11-10") for g in ("G0", "G1", "G2", "G3", "G4")})
        if history:
            spec = p.path(sid)
            spec.write_text(with_history(spec.read_text(encoding="utf-8"), history), encoding="utf-8")
        p.commit("docs: spec")
        git(root, self.env, "checkout", "-qb", "work")
        tags = "\n".join(f"# {sid}:{t}" for t in sg.plan_test_ids(load(root, sid)))
        (root / "tests/a").mkdir(parents=True)
        (root / "tests/a/test_a.py").write_text(tags + "\n", encoding="utf-8")
        p.commit(f"test(a): red\n\nRefs: {sid}")
        (root / "src/a").mkdir(parents=True)
        (root / "src/a/a.py").write_text("x = 1\n", encoding="utf-8")
        p.commit(f"feat(a): green\n\nRefs: {sid}")
        return p, sid

    def test_history_subsection_is_invisible_to_table_validate_and_pr_check(self):
        """SPEC-0078:CH-02 — com o histórico abaixo da tabela, gate_table, validate e pr-check dão o mesmo resultado.
        (guarda: passa antes da mudança)
        """
        a, sid = self.build(self.tmp / "a")
        b, _ = self.build(self.tmp / "b", history=[
            f"- G2 FAIL 2026-11-08 — build exit 1 (erro de compilação) — {SHA}",
            f"- G2 FAIL 2026-11-09 — test exit 1 (2 failed) — {SHA}",
            "- G2 PASS 2026-11-10 — depois de 2 reprovação(ões)",
            "- G4 FAIL 2026-11-10 — revisão pediu ajustes — ?",
            "- G4 PASS 2026-11-10 — depois de 1 reprovação(ões)",
        ])
        self.assertIn(HISTORY_TITLE, gates_section(b.path(sid).read_text(encoding="utf-8")))
        self.assertNotIn(HISTORY_TITLE, a.path(sid).read_text(encoding="utf-8"))

        self.assertEqual(sg.gate_table(load(b.root, sid)), sg.gate_table(load(a.root, sid)))
        body = f"## Como foi testado\nsuíte completa\n\nRefs: {sid}"
        pr_env = {"PR_TITLE": f"feat: funcionalidade [{sid}]", "PR_BODY": body}
        for args, extra in ((("validate",), {}), (("validate", sid), {}),
                            (("pr-check", "--base", "main"), pr_env)):
            results = []
            for proj in (a, b):
                res = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=proj.root, capture_output=True,
                                     text=True, env=dict(self.env, **extra), check=False)
                out = re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", res.stdout.replace(str(proj.root), "<raiz>"))
                results.append((res.returncode, out))
            self.assertEqual(results[0], results[1], args)


# --------------------------------------------------------------------------- testes unitários

class HistoryWriteTest(TempTest):
    def test_fail_red_run_and_green_run_build_the_history(self):
        """SPEC-0078:UT-01 — G2 `--fail`, `--run` vermelho e `--run` verde: tabela em PASS; histórico com 2 FAIL
        (data, evidência e SHA) e o PASS "depois de 2 reprovação(ões)", na ordem. Emenda v2: o `--run` usa a evidência
        da tabela sem repetir o sha, o `--fail` acrescenta " — <sha>", e N/A depois de reprovação grava a linha PASS."""
        root = self.tmp / "proj"
        (root / "docs" / "specs").mkdir(parents=True)
        (root / "docs/specs/sdd-config.yml").write_text('base_branch: main\ntest: "python3 check.py"\n',
                                                        encoding="utf-8")
        (root / "check.py").write_text(
            "import os\nimport sys\n"
            "if os.path.exists('green.flag'):\n    print('Ran 4 tests OK')\n    sys.exit(0)\n"
            "print('FAILED (failures=1)')\nsys.exit(1)\n", encoding="utf-8")
        (root / ".gitignore").write_text("green.flag\n", encoding="utf-8")
        write_spec(root / "docs" / "specs", "SPEC-0001", spec_md(
            "SPEC-0001", "in-progress", created="2026-11-01", approved_at="2026-11-02",
            gates=pass_all("2026-11-14", upto=("G0", "G1"))))
        (root / "docs/specs/SPEC-0002-arquitetura.md").write_text(spec_md(
            "SPEC-0002", "approved", created="2026-11-01", approved_at="2026-11-02"), encoding="utf-8")
        git_init(root, self.env)

        sha1 = short_head(root, self.env)
        with mock.patch.object(sg, "today", return_value="2026-11-15"):
            code, out, err = call("--root", str(root), "gate", "SPEC-0001", "G2", "--fail", "testes de borda quebrados")
        self.assertEqual(code, 0, out + err)
        commit_all(root, self.env, "docs: G2 FAIL")
        sha2 = short_head(root, self.env)
        with mock.patch.object(sg, "today", return_value="2026-11-16"):
            code, out, err = call("--root", str(root), "gate", "SPEC-0001", "G2", "--run")
        self.assertEqual(code, 1, out + err)
        run_evidence = sg.gate_table(load(root, "SPEC-0001"))["G2"]["evidence"]
        self.assertTrue(run_evidence.endswith(f" — {sha2}"), run_evidence)
        commit_all(root, self.env, "docs: G2 FAIL (run)")
        (root / "green.flag").write_text("ok\n", encoding="utf-8")
        with mock.patch.object(sg, "today", return_value="2026-11-17"):
            code, out, err = call("--root", str(root), "gate", "SPEC-0001", "G2", "--run")
        self.assertEqual(code, 0, out + err)
        commit_all(root, self.env, "docs: G2 PASS")
        sha3 = short_head(root, self.env)
        with mock.patch.object(sg, "today", return_value="2026-11-17"):
            code, out, err = call("--root", str(root), "gate", "SPEC-0001", "G3", "--fail", "regra de camadas violada")
            self.assertEqual(code, 0, out + err)
            code, out, err = call("--root", str(root), "gate", "SPEC-0001", "G3", "--na",
                                  "suíte de arquitetura será criada na SPEC-0002")
            self.assertEqual(code, 0, out + err)

        doc = load(root, "SPEC-0001")
        self.assertEqual(sg.gate_table(doc)["G2"]["status"], "PASS")
        self.assertEqual(sg.gate_table(doc)["G3"]["status"], "N/A")
        section_text = gates_section(doc.text)
        self.assertIn(HISTORY_TITLE, section_text, "a subseção fica dentro do Registro de Gates")
        lines = [line for line in section_text.split(HISTORY_TITLE, 1)[1].splitlines() if line.startswith("- ")]
        self.assertEqual(len(lines), 5, lines)
        self.assertEqual(lines[0], f"- G2 FAIL 2026-11-15 — testes de borda quebrados — {sha1}")
        self.assertEqual(lines[1], f"- G2 FAIL 2026-11-16 — {run_evidence}", "evidência da tabela, sem repetir o sha")
        self.assertEqual(lines[1].count(sha2), 1, lines[1])
        self.assertEqual(lines[2], "- G2 PASS 2026-11-17 — depois de 2 reprovação(ões)")
        self.assertEqual(lines[3], f"- G3 FAIL 2026-11-17 — regra de camadas violada — {sha3}")
        self.assertEqual(lines[4], "- G3 PASS 2026-11-17 — depois de 1 reprovação(ões)", "N/A depois de reprovação")

        history = fn("gate_history")(doc)
        self.assertEqual([(h["gate"], h["status"], h["date"]) for h in history],
                         [("G2", "FAIL", "2026-11-15"), ("G2", "FAIL", "2026-11-16"), ("G2", "PASS", "2026-11-17"),
                          ("G3", "FAIL", "2026-11-17"), ("G3", "PASS", "2026-11-17")])
        self.assertIn("testes de borda quebrados", history[0]["evidence"])
        self.assertEqual((history[0]["sha"], history[1]["sha"]), (sha1, sha2))
        self.assertIn("test exit 1", history[1]["evidence"])
        self.assertEqual(history[2]["after"], 2)
        self.assertEqual(fn("consecutive_fails")(doc, "G2"), 0)
        self.assertEqual(fn("consecutive_fails")(doc, "G3"), 0)


UT02_SPEC1_HISTORY = [
    f"- G2 FAIL 2026-10-01 — build exit 1 (a) — {SHA}",
    f"- G2 FAIL 2026-10-02 — build exit 1 (b) — {SHA}",
    f"- G2 FAIL 2026-10-03 — build exit 1 (c) — {SHA}",
    "- G2 PASS 2026-10-04 — depois de 3 reprovação(ões)",
    f"- G4 FAIL 2026-11-01 — revisão antiga — {SHA}",
    "- G4 PASS 2026-11-02 — depois de 1 reprovação(ões)",
    f"- G4 FAIL 2026-11-10 — rev: CHANGES_REQUESTED — {SHA}",
    "- G4 FAIL 2026-11-11 — rev: CHANGES_REQUESTED de novo — ?",
    # fora do formato: não contam
    f"- G4 FAIL ontem — data inválida — {SHA}",
    "- G4 REPROVOU 2026-11-12 — texto livre",
    f"G4 FAIL 2026-11-12 — sem marcador de lista — {SHA}",
    f"- G9 FAIL 2026-11-12 — gate inexistente — {SHA}",
    "- G4 FAIL 2026-11-12 sem separadores",
]
UT02_SPEC2_HISTORY = [
    f"- G3 FAIL 2026-11-01 — arch_test exit 1 (x) — {SHA}",
    f"- G3 FAIL 2026-11-02 — arch_test exit 1 (y) — {SHA}",
    "- G3 PASS 2026-11-03 — depois de 2 reprovação(ões)",
    f"- G3 FAIL 2026-11-04 — arch_test exit 1 (z) — {SHA}",
]


class StreakTest(TempTest):
    def test_three_consecutive_fails_warn_in_gate_and_status(self):
        """SPEC-0078:UT-02 — 3º FAIL seguido de G4: aviso no `gate` e no `status` com `impede --type falha`; some com
        impedimento `falha` aberto; PASS no meio recomeça a contagem; linhas fora do formato não contam.
        Emenda v2: o aviso do `status` sai só sem IDs; o do `gate` sai mesmo com impedimento `falha` aberto."""
        root = self.tmp / "proj"
        specs = root / "docs" / "specs"
        specs.mkdir(parents=True)
        (specs / "sdd-config.yml").write_text("base_branch: main\n", encoding="utf-8")
        g4_failing = pass_all("2026-11-11", upto=("G0", "G1", "G2", "G3"),)
        g4_failing["G4"] = ("FAIL", "rev: CHANGES_REQUESTED", "2026-11-11")
        write_spec(specs, "SPEC-0001", with_history(spec_md(
            "SPEC-0001", "in-progress", created="2026-09-01", approved_at="2026-09-02", gates=g4_failing),
            UT02_SPEC1_HISTORY))
        g3_failing = pass_all("2026-11-04", upto=("G0", "G1", "G2"))
        g3_failing["G3"] = ("FAIL", "arch_test exit 1 (z)", "2026-11-04")
        (specs / "SPEC-0002-outra.md").write_text(with_history(spec_md(
            "SPEC-0002", "in-progress", created="2026-09-01", approved_at="2026-09-02", gates=g3_failing),
            UT02_SPEC2_HISTORY), encoding="utf-8")

        gate_history, consecutive_fails = fn("gate_history"), fn("consecutive_fails")
        doc = load(root, "SPEC-0001")
        history = gate_history(doc)
        self.assertEqual([(h["gate"], h["status"], h["date"]) for h in history], [
            ("G2", "FAIL", "2026-10-01"), ("G2", "FAIL", "2026-10-02"), ("G2", "FAIL", "2026-10-03"),
            ("G2", "PASS", "2026-10-04"), ("G4", "FAIL", "2026-11-01"), ("G4", "PASS", "2026-11-02"),
            ("G4", "FAIL", "2026-11-10"), ("G4", "FAIL", "2026-11-11")])
        self.assertEqual((history[6]["evidence"], history[6]["sha"]), ("rev: CHANGES_REQUESTED", SHA))
        self.assertEqual(history[7]["sha"], "?")
        self.assertEqual((history[3]["after"], history[5]["after"]), (3, 1))
        self.assertEqual(consecutive_fails(doc, "G4"), 2, "as linhas fora do formato não contam")
        self.assertEqual(consecutive_fails(doc, "G2"), 0, "o PASS recomeça a contagem")
        self.assertEqual(consecutive_fails(load(root, "SPEC-0002"), "G3"), 1, "PASS no meio recomeça a contagem")
        self.assertEqual(gate_history(load(root, "SPEC-0002"))[2]["after"], 2)

        code, out, err = call("--root", str(root), "status")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("reprovações seguidas", out, "2 FAIL válidos ainda não pedem parada")

        code, out, err = call("--root", str(root), "gate", "SPEC-0001", "G4", "--fail", "revisão reprovou de novo")
        self.assertEqual(code, 0, out + err)
        self.assertIn("⚠ 3 reprovações seguidas em G4 — registre `impede SPEC-0001 --type falha` e escale ao humano",
                      out)
        doc = load(root, "SPEC-0001")
        self.assertEqual(consecutive_fails(doc, "G4"), 3)
        last = gate_history(doc)[-1]
        self.assertEqual((last["gate"], last["status"], last["sha"]), ("G4", "FAIL", "?"), "fora do git: sha '?'")
        self.assertIn("revisão reprovou de novo", last["evidence"])
        for line in UT02_SPEC1_HISTORY:
            self.assertIn(line, doc.text, "linhas antigas, inclusive as malformadas, ficam como estão")

        code, out, err = call("--root", str(root), "status")
        self.assertEqual(code, 0, out + err)
        self.assertIn("⚠ SPEC-0001: 3 reprovações seguidas em G4 — `impede SPEC-0001 --type falha`", out)
        self.assertNotIn("em G2", out)
        self.assertNotIn("SPEC-0002: ", out.split("\nSPEC-0001 ")[0], "SPEC-0002 tem 1 FAIL depois do PASS")
        code, out, err = call("--root", str(root), "status", "SPEC-0001")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("reprovações seguidas", out, "com IDs, o `status` não mostra os avisos do topo")

        code, out, err = call("--root", str(root), "impede", "SPEC-0001", "--type", "falha", "--reason",
                              "diagnóstico do G4 pendente", "--owner", "thomas", "--phase", "G4")
        self.assertEqual(code, 0, out + err)
        code, out, err = call("--root", str(root), "status")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("reprovações seguidas", out, "impedimento `falha` aberto: o aviso some")

        code, out, err = call("--root", str(root), "gate", "SPEC-0001", "G4", "--fail", "quarta reprovação")
        self.assertEqual(code, 0, out + err)
        self.assertIn("⚠ 4 reprovações seguidas em G4 — registre `impede SPEC-0001 --type falha` e escale ao humano",
                      out, "o aviso do `gate` sai mesmo com impedimento `falha` aberto")
        code, out, err = call("--root", str(root), "status")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("reprovações seguidas", out)


class UnclosedTest(TempTest):
    def project(self) -> Path:
        root = self.tmp / "proj"
        specs = root / "docs" / "specs"
        specs.mkdir(parents=True)
        (specs / "sdd-config.yml").write_text("base_branch: main\n", encoding="utf-8")
        delivered = pass_all("2026-11-08")
        delivered["H2"] = ("PASS", "aprovado por thomas", "2026-11-08")
        write_spec(specs, "SPEC-0001", spec_md("SPEC-0001", "in-progress", created="2026-10-01",
                                               approved_at="2026-10-02", gates=delivered))
        closed = dict(delivered)
        closed["G6"] = ("N/A", "biblioteca sem deploy próprio", "2026-11-08")
        closed["G7"] = ("PASS", GEN["G7"], "2026-11-09")
        (specs / "SPEC-0002-fechada.md").write_text(spec_md(
            "SPEC-0002", "in-progress", created="2026-10-01", approved_at="2026-10-02", gates=closed), encoding="utf-8")
        (specs / "SPEC-0003-sem-g5.md").write_text(spec_md(
            "SPEC-0003", "in-progress", created="2026-10-01", approved_at="2026-10-02",
            gates=pass_all("2026-11-01", upto=("G0", "G1", "G2"))), encoding="utf-8")
        # Emenda v2: approved também conta; proposed e épico não
        (specs / "SPEC-0004-aprovada.md").write_text(spec_md(
            "SPEC-0004", "approved", created="2026-10-01", approved_at="2026-10-02",
            gates=pass_all("2026-11-12")), encoding="utf-8")
        (specs / "SPEC-0005-proposta.md").write_text(spec_md(
            "SPEC-0005", "proposed", created="2026-10-01", gates=pass_all("2026-11-08")), encoding="utf-8")
        (specs / "SPEC-0006-epico.md").write_text(spec_md(
            "SPEC-0006", "in-progress", created="2026-10-01", approved_at="2026-10-02", tier="epic",
            gates=pass_all("2026-11-08")), encoding="utf-8")
        return root

    def test_delivered_without_g7_is_flagged_with_its_age(self):
        """SPEC-0078:UT-03 — G5 PASS há 9 dias e G7 pendente: aviso no topo do `status` e seção "A fechar" no `next`;
        a spec com G7 PASS e a sem G5 não aparecem. Emenda v2: approved (há 5 dias) também aparece; proposed e épico
        não; com IDs, o `status` não mostra o aviso."""
        root = self.project()
        project = sg.Project(root)
        self.assertEqual(fn("unclosed_specs")(project, TODAY), [("SPEC-0001", 9), ("SPEC-0004", 5)])

        out = capture(fn("status_body", "today"), project, [], today=TODAY)
        warning = "⚠ entregue sem fechar: SPEC-0001 — G5 há 9 dia(s); feche o G7 (Relatório de Entrega)"
        self.assertIn(warning, out)
        lines = out.splitlines()
        first_spec = next(i for i, line in enumerate(lines) if line.startswith("SPEC-"))
        self.assertLess(lines.index(warning), first_spec, "o aviso vem no topo, antes da lista")
        self.assertIn("⚠ entregue sem fechar: SPEC-0004 — G5 há 5 dia(s); feche o G7 (Relatório de Entrega)", lines)
        flagged = [line for line in lines if "entregue sem fechar" in line]
        self.assertEqual(len(flagged), 2, flagged)
        out = capture(sg.status_body, project, ["SPEC-0001"], today=TODAY)
        self.assertNotIn("entregue sem fechar", out, "com IDs, nenhum aviso do topo")

        out = capture(fn("print_next", "today"), project, sg.require_plan(project), today=TODAY)
        lines = out.splitlines()
        heads = [i for i, line in enumerate(lines) if line.startswith("A fechar")]
        self.assertEqual(len(heads), 1, out)
        items = []
        for line in lines[heads[0] + 1:]:
            if not line.startswith("  "):
                break
            items.append(line)
        self.assertEqual(len(items), 2, out)
        self.assertIn("SPEC-0001", items[0])
        self.assertIn("9 dia(s)", items[0])
        self.assertIn("SPEC-0004", items[1])
        self.assertIn("5 dia(s)", items[1])


class PrivateInitVersionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def config(self, env: PrivateEnv) -> dict:
        return sg.parse_yaml_subset((env.spec_root / "sdd-config.yml").read_text(encoding="utf-8"))

    def test_private_init_records_the_skill_version(self):
        """SPEC-0078:UT-04 — `private init` sem sdd-config.yml grava sdd_version = SDD_TOOL_VERSION; um que já existe
        mantém a sua versão."""
        fresh = PrivateEnv(self.tmp / "novo")
        fresh.init()
        self.assertEqual(self.config(fresh).get("sdd_version"), VERSION)

        existing = PrivateEnv(self.tmp / "existente")
        existing.spec_root.mkdir(parents=True)
        (existing.spec_root / "sdd-config.yml").write_text('base_branch: main\nsdd_version: "2000.1.1"\n',
                                                           encoding="utf-8")
        existing.init()
        self.assertEqual(self.config(existing).get("sdd_version"), "2000.1.1")


MARKER = "MARCA-HIST-4d1e"


def ut05_project(root: Path, version):
    """Projeto com sdd_version `version` (None = sem a chave) e uma spec com histórico de reprovações."""
    specs = root / "docs" / "specs"
    specs.mkdir(parents=True)
    config = "base_branch: main\n" + (f'sdd_version: "{version}"\n' if version else "")
    (specs / "sdd-config.yml").write_text(config, encoding="utf-8")
    gates = pass_all("2026-11-10")
    write_spec(specs, "SPEC-0001", with_history(spec_md(
        "SPEC-0001", "in-progress", created="2026-11-01", approved_at="2026-11-02", gates=gates), [
        f"- G2 FAIL 2026-11-05 — build exit 1 ({MARKER}) — {SHA}",
        f"- G2 FAIL 2026-11-06 — test exit 1 ({MARKER}) — ?",
        "- G2 PASS 2026-11-07 — depois de 2 reprovação(ões)",
        f"- G4 FAIL ontem — {MARKER} — {SHA}",
    ]))
    (specs / "SPEC-0002-limpa.md").write_text(spec_md(
        "SPEC-0002", "approved", created="2026-11-01", approved_at="2026-11-02",
        gates={"G0": ("PASS", GEN["G0"], "2026-11-02")}), encoding="utf-8")
    return root


def r5_metrics(fail_history, fail_recorded):
    m = neutral_metrics()
    for g in ("G1", "G2", "G3", "G4", "G5"):
        m["gates"][g]["PASS"] = 4
    m["tool"]["state"] = "atual"
    m["fail_history"], m["fail_recorded"] = fail_history, fail_recorded
    return m


class RetroStateTest(TempTest):
    def rules(self, metrics) -> dict:
        return {f["rule"]: f for f in sg.retro_findings([metrics])}

    def test_tool_state_and_recorded_fails(self):
        """SPEC-0078:UT-05 — tool.state (desconhecida, atrasada, atual) com a ação certa na R1; fail_recorded conta as
        linhas FAIL; R5 não dispara com fail_recorded > 0; a evidência do histórico não sai no relatório."""
        projects = {"sem-versao": None, "atrasado": "2026.10.8", "atual": VERSION}
        for name, version in projects.items():
            ut05_project(self.tmp / name, version)
        metrics = {name: sg.retro_metrics(sg.Project(self.tmp / name), TODAY, 30) for name in projects}
        self.assertEqual({n: m["tool"].get("state") for n, m in metrics.items()},
                         {"sem-versao": "desconhecida", "atrasado": "atrasada", "atual": "atual"})
        self.assertEqual(metrics["atual"]["tool"]["project"], VERSION)
        for name, m in metrics.items():
            self.assertEqual(m.get("fail_recorded"), 2, f"{name}: só as 2 linhas FAIL válidas contam")

        unknown = self.rules(metrics["sem-versao"])["R1"]["action"]
        behind = self.rules(metrics["atrasado"])["R1"]["action"]
        self.assertIn("whats-new --ack", unknown)
        self.assertNotIn("vendor --force", unknown, "versão desconhecida só precisa ser registrada")
        self.assertIn("whats-new", behind)
        self.assertIn("vendor --force", behind)
        self.assertNotEqual(unknown, behind)
        self.assertNotIn("R1", self.rules(metrics["atual"]))
        private_behind = dict(metrics["atrasado"], private=True)
        self.assertIn("whats-new --ack", self.rules(private_behind)["R1"]["action"])

        self.assertIn("R5", self.rules(r5_metrics(0, 0)), "base: nenhum FAIL no git nem na spec")
        self.assertNotIn("R5", self.rules(r5_metrics(0, 1)), "FAIL registrado na spec: houve reprovação")
        self.assertNotIn("R5", self.rules(r5_metrics(None, 0)), "Emenda v2: fail_history None nunca dispara")
        self.assertNotIn("R5", self.rules(r5_metrics(None, 2)))

        folders = [str(self.tmp / name) for name in projects]
        md = run_retro(self.env, self.tmp, *folders)
        js = run_retro(self.env, self.tmp, *folders, "--json")
        for label, res in (("Markdown", md), ("JSON", js)):
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertNotIn(MARKER, res.stdout + res.stderr, f"evidência do histórico vazou na saída {label}")
        report = json.loads(js.stdout)
        self.assertEqual(report["retro_version"], 1)
        by_name = {p["name"]: p for p in report["projects"]}
        self.assertEqual({n: (p["tool"].get("state"), p.get("fail_recorded")) for n, p in by_name.items()},
                         {"sem-versao": ("desconhecida", 2), "atrasado": ("atrasada", 2), "atual": ("atual", 2)})


class RetroResiduesTest(TempTest):
    def test_registry_type_history_label_impediment_id_and_duplicate_ids(self):
        """SPEC-0078:UT-06 — spec_root numérico no registro, fail_history null, ID de impedimento livre e specs sem id
        repetidas: exit 0 sem traceback, "registro inválido", "sem histórico", IMP-? na R7 e o ID uma vez em stale.
        Emenda v2: IMP-<dígitos> é mantido (IMP-3 não vira IMP-03 nem IMP-?)."""
        (self.tmp / "config" / "projects.json").write_text(json.dumps({"projects": {
            "github.com/Org/Quebrado": {"mode": "private", "spec_root": 5, "sync": "none"}}}), encoding="utf-8")

        root = self.tmp / "residuos"
        specs = root / "docs" / "specs"
        specs.mkdir(parents=True)
        (specs / "sdd-config.yml").write_text("base_branch: main\n", encoding="utf-8")
        write_spec(specs, "SPEC-0001", spec_md(
            "SPEC-0001", "in-progress", created="2020-01-01", approved_at="2020-01-02",
            gates={"G0": ("PASS", GEN["G0"], "2020-01-02")},
            impediments=[("texto livre", "2020-01-03", "aguardando acesso", "", ""),
                         ("IMP-02", "2020-01-04", "ambiente fora", "", ""),
                         ("IMP-3", "2020-01-05", "chave expirada", "", "")]))
        for slug in ("alfa", "beta"):
            text = spec_md("SPEC-0009", "approved", created="2020-01-01", approved_at="2020-01-02",
                           gates=pass_all("2020-01-05"))
            (specs / f"SPEC-0009-{slug}.md").write_text(text.replace("id: SPEC-0009\n", "", 1), encoding="utf-8")
        # repositório sem commits: o histórico do git também não existe
        empty = self.tmp / "sem-commits"
        ut05_project(empty, VERSION)
        git(empty, self.env, "init", "-q", "-b", "main")

        md = run_retro(self.env, self.tmp, str(root), str(empty), "--registry")
        js = run_retro(self.env, self.tmp, str(root), str(empty), "--registry", "--json")
        for res in (md, js):
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertNotIn("Traceback", res.stderr)

        self.assertIn("registro inválido", section(md.stdout, "Ignorados"), md.stdout)
        report = json.loads(js.stdout)
        self.assertTrue(any("registro inválido" in item["reason"] for item in report["ignored"]), report["ignored"])
        self.assertEqual(sorted(p["name"] for p in report["projects"]), ["residuos", "sem-commits"])

        rows = [line for line in section(md.stdout, "Projetos").splitlines() if line.startswith("| ")]
        for name in ("residuos", "sem-commits"):
            row = next((line for line in rows if line.startswith(f"| {name} ")), "")
            self.assertIn("sem histórico", row, f"{name}: fail_history null\n{md.stdout}")

        project = next(p for p in report["projects"] if p["name"] == "residuos")
        self.assertIsNone(project["fail_history"])
        self.assertEqual(project["impediments"]["old"], ["SPEC-0001/IMP-02", "SPEC-0001/IMP-3", "SPEC-0001/IMP-?"],
                         "IMP-<dígitos> fica como está; fora do formato vira IMP-?")
        r7 = [f for f in report["findings"] if f["rule"] == "R7" and f["project"] == "residuos"]
        self.assertTrue(r7 and "SPEC-0001/IMP-?" in str(r7[0]["value"]), r7)
        self.assertIn("SPEC-0001/IMP-?", section(md.stdout, "Achados"))
        for res in (md, js):
            self.assertNotIn("texto livre", res.stdout, "o texto da célula de ID não sai")

        self.assertEqual(project["stale"], ["SPEC-0001", "SPEC-0009"])
        self.assertEqual(project["unclosed"], ["SPEC-0009"])
        r2 = next(f for f in report["findings"] if f["rule"] == "R2" and f["project"] == "residuos")
        self.assertEqual(str(r2["value"]).count("SPEC-0009"), 1, r2)


# --------------------------------------------------------------------------- testes de integração

class StreakIntegrationTest(TempTest):
    def test_three_fails_then_green_run_via_cli(self):
        """SPEC-0078:IT-01 — 3x `gate G2 --fail` com commit entre elas e `gate --run` verde: aviso na 3ª, parada no
        `status` até o PASS, histórico completo na spec e `validate` limpo."""
        p = CliProject(self.tmp / "proj", self.env, config_extra=(
            'test: "python3 -c \\"print(\'Ran 3 tests OK\')\\""\n'))
        sid = p.full_spec()
        p.plan(sid)
        p.commit("docs: spec aprovada")
        p.ok("gate", sid, "G0", "--run")
        p.ok("gate", sid, "G1", "--manual", "--evidence", "red visto no terminal")
        p.commit("docs: G0 e G1")

        for i in (1, 2, 3):
            out = p.ok("gate", sid, "G2", "--fail", f"reprovação número {i}").stdout
            p.commit(f"docs: G2 FAIL {i}")
            if i < 3:
                self.assertNotIn("reprovações seguidas", out, i)
        self.assertIn(f"⚠ 3 reprovações seguidas em G2 — registre `impede {sid} --type falha` e escale ao humano", out)
        status = p.ok("status").stdout
        self.assertIn(f"⚠ {sid}: 3 reprovações seguidas em G2 — `impede {sid} --type falha`", status)

        p.ok("gate", sid, "G2", "--run")
        p.commit("docs: G2 PASS")
        self.assertNotIn("reprovações seguidas", p.ok("status").stdout)

        text = p.path(sid).read_text(encoding="utf-8")
        self.assertEqual(sg.gate_table(load(p.root, sid))["G2"]["status"], "PASS")
        section_text = gates_section(text)
        self.assertIn(HISTORY_TITLE, section_text)
        lines = [line for line in section_text.split(HISTORY_TITLE, 1)[1].splitlines() if line.startswith("- ")]
        self.assertEqual(len(lines), 4, lines)
        for i, line in enumerate(lines[:3], start=1):
            self.assertRegex(line, rf"^- G2 FAIL \d{{4}}-\d{{2}}-\d{{2}} — reprovação número {i} — [0-9a-f]{{7,40}}$")
        self.assertRegex(lines[3], r"^- G2 PASS \d{4}-\d{2}-\d{2} — depois de 3 reprovação\(ões\)$")
        res = p.run("validate", sid)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


class UnclosedIntegrationTest(TempTest):
    def test_status_and_next_flag_until_g7(self):
        """SPEC-0078:IT-02 — spec entregue sem G7: aviso no `status` e seção "A fechar" no `next`; somem depois do G7."""
        p = CliProject(self.tmp / "proj", self.env)
        sid = p.full_spec()
        p.plan(sid)
        g5_date = (dt.date.today() - dt.timedelta(days=9)).isoformat()
        rows = {g: ("PASS", GEN[g], g5_date) for g in ("G0", "G1", "G2", "G3", "G4", "G5")}
        rows["H2"] = ("PASS", "aprovado por thomas", g5_date)
        rows["G6"] = ("N/A", "biblioteca sem deploy próprio", g5_date)
        p.set_rows(sid, rows)
        p.commit("docs: spec entregue")

        warning = f"⚠ entregue sem fechar: {sid} — G5 há 9 dia(s); feche o G7 (Relatório de Entrega)"
        self.assertIn(warning, p.ok("status").stdout)
        nxt = p.ok("next").stdout
        self.assertIn("A fechar", nxt)
        after = nxt.split("A fechar", 1)[1]
        self.assertIn(sid, after)
        self.assertIn("9 dia(s)", after)

        p.ok("gate", sid, "G7", "--manual", "--evidence", "Relatório de Entrega conferido")
        self.assertNotIn("entregue sem fechar", p.ok("status").stdout)
        self.assertNotIn("A fechar", p.ok("next").stdout)


if __name__ == "__main__":
    unittest.main()
