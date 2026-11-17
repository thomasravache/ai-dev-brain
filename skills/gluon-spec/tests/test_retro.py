"""Retrospectiva entre projetos (SPEC-0074): `spec_graph.py retro [PASTA ...] [--registry] [--stale-days N] [--json]
[--out ARQUIVO]`, só de leitura.

Contrato esperado das funções puras de scripts/spec_graph.py (o Implementer segue estes testes):

    evidence_origin(evidence: str) -> str
        Origem da evidência de um gate PASS, pelo que o próprio `gate` escreve:
        "gerada"  formato do `gate --run` (gate_run): termina em " — <sha>" (hex de 7 a 40 caracteres, ou "?"),
                  opcionalmente seguido de " (árvore suja)", e começa por "validate: ", "verify G" ou
                  "Relatório de Entrega", ou contém "<chave> exit <n> (" (ex.: "build exit 0 (ok); test exit 0 (OK)
                  — abc1234").
        "manual"  começa com MANUAL_PREFIX ("MANUAL:").
        "humana"  começa com "aprovado por".
        "a_mao"   todo o resto (inclusive texto livre que termina num SHA).

    retro_metrics(project: Project, today: datetime.date, stale_days: int, name: str | None = None) -> dict
        Métricas de um projeto já carregado. `today` fixa a data de hoje (os testes nunca dependem do relógio).
        name = `name` ou, sem ele, o nome da pasta project.root. Chaves (as mesmas de cada item de "projects" no JSON):
        "name"            str
        "private"         bool (project.private)
        "specs"           {"total": int, "by_status": {status: int}, "by_tier": {tier: int}} — só chaves com valor > 0
        "tool"            {"project": versão de project_tool_version ou "desconhecida", "installed": SDD_TOOL_VERSION}
        "last_activity"   "AAAA-MM-DD": a data mais recente entre created, approved_at e as datas do Registro de Gates
        "stale"           IDs (ordenados) com status approved/in-progress cuja última atividade (created, approved_at,
                          datas de gate da spec) é de MAIS de stale_days dias antes de today (exatamente N não conta)
        "unclosed"        IDs (ordenados) approved/in-progress com G5 = PASS e G7 != PASS
        "lead_time_days"  {"median": número | None, "p90": int | None} — dias de approved_at até a data do G7 PASS
                          das specs implemented; mediana = statistics.median; p90 = nearest-rank
                          (valores ordenados, índice ceil(0.9 * n) - 1)
        "gates"           {gate: {"PASS": int, "FAIL": int, "N/A": int}} para todo gate de GATE_ROWS (G0–G7, H2)
        "fail_history"    retro_fail_history(project.specs_dir)
        "evidence"        {"gerada", "manual", "humana", "a_mao"}: contagem dos G0–G5 com PASS por evidence_origin
        "na_by_gate"      {gate: {"na": int, "total": int}} para todo gate de GATE_ROWS; total = linhas com status
                          registrado (PASS, FAIL ou N/A — PENDING e vazio não contam)
        "amendments"      {"total": int, "by_spec": {id: int}} — linhas da tabela de Emendas (só specs com > 0)
        "impediments"     {"total": int, "open": int, "old": ["SPEC-NNNN/IMP-NN", ...]} — old = abertos há MAIS de
                          stale_days dias (por "Aberto em"), ordenados

    retro_fail_history(specs_dir: Path) -> int | None
        Linhas removidas (diff "-") do Registro de Gates com status FAIL em `git log -p` da pasta de specs
        (GIT_OPTIONAL_LOCKS=0, só leitura). Linha de gate = primeira célula começa por um gate de GATE_ROWS; FAIL em
        outras tabelas (ex.: Verificação) não conta. None quando a pasta não está num repositório git.

    retro_findings(projects: list[dict]) -> list[dict]
        projects = lista de dicts de retro_metrics. Cada achado: {"rule", "project", "value", "action"}
        ("project" = name; "value" = o número ou os IDs que dispararam a regra, em texto ou número).
        R1  tool.project == "desconhecida" ou version_key(tool.project) < version_key(tool.installed)
            → action cita "whats-new" e "vendor --force"; projeto privado: "whats-new --ack"
        R2  stale não vazio (value cita os IDs) → action cita "deprecated"
        R3  unclosed não vazio (value cita os IDs) → action cita "G7"
        R4  (manual + a_mao) / (soma de evidence) > 30% e soma >= 10 → action cita "--run"
        R5  soma de gates[G1..G5]["PASS"] >= 20 e fail_history == 0 (None não dispara) → action cita "--fail"
        R6  por gate: na_by_gate[g]["total"] >= 5 e na / total >= 50% (um achado por gate; value cita o gate)
            → action cita "pillars.waived"
        R7  impediments.old não vazio (value cita os IDs) → action cita "resolve"

    retro_skill_suggestions(findings: list[dict], project_count: int) -> list[dict]
        Regra que dispara em >= 50% de project_count projetos distintos e em pelo menos 2 projetos vira
        {"rule", "projects": int (projetos distintos), "suggestion": texto não vazio (tabela de references/retro.md)}.
        Nunca cria arquivo.

Markdown (padrão): seções com cabeçalho Markdown cujos títulos contêm "Resumo", "Projetos" (tabela, uma linha por
projeto), "N/A por gate", "Achados", "O que ajustar na skill" e "Ignorados". Projeto sem git mostra "sem git" ou,
desde a Emenda v2 da SPEC-0078, "sem histórico". Chaves a mais em `tool` e em `projects[]` são aceitas (o JSON só
ganha chaves).
JSON: {"retro_version": 1, "generated_at", "installed_tool", "stale_days", "projects", "findings",
"skill_suggestions", "ignored": [{"path", "reason"}]}.

Os testes de CLI rodam o script como processo em diretórios temporários resolvidos, com HOME, SDD_CONFIG_HOME,
XDG_* e CLAUDE_CONFIG_DIR temporários e GIT_CEILING_DIRECTORIES no diretório temporário: nada lê ou grava o
registro real nem a configuração do usuário.
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
SKILL = TESTS.parent
SCRIPT = SKILL / "scripts" / "spec_graph.py"
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(TESTS))
import spec_graph as sg
from test_private_mode import PrivateEnv

VERSION = sg.SDD_TOOL_VERSION
TODAY = dt.date(2026, 11, 17)
GATES = ("G0", "G1", "G2", "G3", "G4", "G5", "H2", "G6", "G7")
GATE_NAMES = {"G0": "Spec", "G1": "Red", "G2": "Green", "G3": "Arquitetura", "G4": "Review", "G5": "Integração & CI",
              "H2": "Integração aprovada", "G6": "Deploy", "G7": "Pronto & Docs"}
SHA = "abc1234"
GEN = {
    "G0": f"validate: 0 erro(s) — {SHA}",
    "G1": f"verify G1: PASS; `make test` exit 1 (red: 1 failed) — {SHA}",
    "G2": f"build exit 0 (ok); test exit 0 (OK) — {SHA}",
    "G3": f"arch_test exit 0 (ok) — {SHA}",
    "G4": f"verify G1+G4: PASS; revisão: rev: APPROVED — {SHA}",
    "G5": f"build exit 0 (ok); test exit 0 (OK) — {SHA}",
    "G6": f"smoke_test exit 0 (ok) — {SHA}",
    "G7": f"Relatório de Entrega e Definição de Pronto: ok — {SHA}",
}
PROJECT_KEYS = {"name", "private", "specs", "tool", "last_activity", "stale", "unclosed", "lead_time_days", "gates",
                "fail_history", "evidence", "na_by_gate", "amendments", "impediments"}
REPORT_KEYS = {"retro_version", "generated_at", "installed_tool", "stale_days", "projects", "findings",
               "skill_suggestions", "ignored"}
PRIVATE_KEY = "github.com/Org/Repo"

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


def fn(name):
    """Função de spec_graph exigida pela SPEC-0074; ausente = o teste falha pelo motivo certo, sem quebrar a suíte."""
    f = getattr(sg, name, None)
    if f is None:
        raise AssertionError(f"spec_graph.{name} não existe (SPEC-0074)")
    return f


# --------------------------------------------------------------------------- dados sintéticos

def spec_md(sid, status, *, created, approved_at="", title="Funcionalidade", tier="full", gates=None,
            impediments=(), amendments=(), verification=()):
    """Spec sintética no formato do template: frontmatter, Registro de Gates, Impedimentos, Verificação e Emendas.

    gates: {gate: (status, evidência, data)}; impediments: (id, aberto_em, descrição, resolução, fechado_em);
    amendments: (versão, data, mudança); verification: (teste, resultado).
    """
    gates = gates or {}
    gate_rows = "\n".join(
        f"| {g} {GATE_NAMES[g]} | {gates.get(g, ('PENDING', '', ''))[0]} | {gates.get(g, ('PENDING', '', ''))[1]} "
        f"| {gates.get(g, ('PENDING', '', ''))[2]} |" for g in GATES)
    imp_rows = "\n".join(f"| {iid} | {opened} | G2 | externo | {desc} | 1 | thomas | {res} | {closed} |"
                         for iid, opened, desc, res, closed in impediments)
    ver_rows = "\n".join(f"| {tid} | comportamento | {res} | {SHA} |" for tid, res in verification)
    amd_rows = "\n".join(f"| {v} | {d} | {change} | motivo | — | thomas |" for v, d, change in amendments)
    return f"""---
id: {sid}
title: {title}
tier: {tier}
type: feature
user_facing: false
status: {status}
created: {created}
depends_on: []
touches: [src/a/**]
approved_by: {'thomas' if approved_at else ''}
approved_at: {approved_at}
---

# {sid} — {title}

## 1. Visão Geral
Texto.

## 12. Registro de Gates
| Gate | Status | Evidência | Data |
|---|---|---|---|
{gate_rows}

## 13. Registro de Impedimentos
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
{imp_rows}

## 14. Relatório de Entrega

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
{ver_rows}

## 15. Emendas
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
{amd_rows}
"""


def write_spec(specs_dir: Path, sid: str, text: str):
    specs_dir.mkdir(parents=True, exist_ok=True)
    (specs_dir / f"{sid}-funcionalidade.md").write_text(text, encoding="utf-8")


def pass_all(date, upto=("G0", "G1", "G2", "G3", "G4", "G5"), **override):
    """Gates `upto` com PASS e evidência gerada na data; override troca (status, evidência) de um gate."""
    out = {g: ("PASS", GEN[g], date) for g in upto}
    for g, (status, evidence) in override.items():
        out[g] = (status, evidence, date)
    return out


def ut01_project(root: Path, title="Funcionalidade", evidence_marker="", na_marker="", imp_marker=""):
    """Projeto do UT-01 (e, com marcadores, do UT-04) — veja os valores esperados em MetricsTest."""
    specs = root / "docs" / "specs"
    specs.mkdir(parents=True)
    (specs / "sdd-config.yml").write_text('base_branch: main\nsdd_version: "2026.10.8"\n', encoding="utf-8")
    na3 = f"sem regra de arquitetura no projeto {na_marker}".strip()
    na6 = f"biblioteca sem deploy próprio {na_marker}".strip()
    manual = f"MANUAL: CI verde no PR {evidence_marker}".strip()
    by_hand = f"rodei os testes, tudo verde {evidence_marker}".strip()
    write_spec(specs, "SPEC-0001", spec_md("SPEC-0001", "proposed", tier="lite", created="2026-11-10", title=title))
    write_spec(specs, "SPEC-0002", spec_md("SPEC-0002", "approved", created="2026-09-01", approved_at="2026-10-08",
                                           title=title, gates={"G0": ("PASS", GEN["G0"], "2026-10-08")}))
    g3 = pass_all("2026-11-10", G2=("PASS", f"MANUAL: rodei {evidence_marker}".strip()), G3=("N/A", na3))
    g3["G5"] = ("PASS", GEN["G5"], "2026-11-12")
    g3["H2"] = ("PASS", "aprovado por thomas", "2026-11-12")
    write_spec(specs, "SPEC-0003", spec_md("SPEC-0003", "approved", created="2026-10-01", approved_at="2026-10-02",
                                           title=title, gates=g3, amendments=[("2", "2026-10-05", "ajuste")]))
    write_spec(specs, "SPEC-0004", spec_md(
        "SPEC-0004", "in-progress", created="2026-10-10", approved_at="2026-10-18", title=title,
        gates={"G0": ("PASS", "aprovado por thomas", "2026-10-18"),
               "G1": ("FAIL", f"verify G1: FAIL — teste ausente — {SHA}", "2026-10-18")},
        impediments=[("IMP-01", "2026-10-01", f"aguardando acesso {imp_marker}".strip(), "", ""),
                     ("IMP-02", "2026-10-02", f"faltava chave {imp_marker}".strip(), "chave criada", "2026-10-05"),
                     ("IMP-03", "2026-10-18", f"ambiente fora {imp_marker}".strip(), "", "")]))
    impl = {"SPEC-0005": ("2026-08-01", "2026-08-11"), "SPEC-0006": ("2026-08-01", "2026-08-21"),
            "SPEC-0007": ("2026-07-01", "2026-08-10")}
    overrides = {"SPEC-0005": {"G2": ("PASS", by_hand), "G3": ("N/A", na3), "G6": ("N/A", na6)},
                 "SPEC-0006": {"G5": ("PASS", manual), "G6": ("N/A", na6)},
                 "SPEC-0007": {"G3": ("N/A", na3)}}
    for sid, (approved, closed) in impl.items():
        gates = pass_all(closed, upto=("G0", "G1", "G2", "G3", "G4", "G5", "G6"), **overrides[sid])
        gates["H2"] = ("PASS", "aprovado por thomas", closed)
        gates["G7"] = ("PASS", GEN["G7"], closed)
        amendments = [("2", "2026-08-05", "ajuste"), ("3", "2026-08-06", "outro")] if sid == "SPEC-0005" else []
        write_spec(specs, sid, spec_md(sid, "implemented", created=approved, approved_at=approved, title=title,
                                       gates=gates, amendments=amendments))
    return specs


def neutral_metrics(name="proj", private=False):
    """Métricas sintéticas em que nenhuma regra dispara (base do UT-03)."""
    return {
        "name": name, "private": private,
        "specs": {"total": 25, "by_status": {"implemented": 25}, "by_tier": {"full": 25}},
        "tool": {"project": VERSION, "installed": VERSION},
        "last_activity": "2026-11-10", "stale": [], "unclosed": [],
        "lead_time_days": {"median": 5, "p90": 9},
        "gates": {g: {"PASS": 0, "FAIL": 0, "N/A": 0} for g in GATES},
        "fail_history": 3,
        "evidence": {"gerada": 10, "manual": 0, "humana": 0, "a_mao": 0},
        "na_by_gate": {g: {"na": 0, "total": 0} for g in GATES},
        "amendments": {"total": 0, "by_spec": {}},
        "impediments": {"total": 0, "open": 0, "old": []},
    }


# --------------------------------------------------------------------------- CLI e git

def isolated_env(tmp: Path, base=None) -> dict:
    env = {k: v for k, v in (base or os.environ).items() if not k.startswith("CLAUDE_")}
    env.update(HOME=str(tmp / "home"), SDD_CONFIG_HOME=str(tmp / "config"), CLAUDE_CONFIG_DIR=str(tmp / "claude"),
               XDG_CONFIG_HOME=str(tmp / "xdg-config"), XDG_DATA_HOME=str(tmp / "xdg-data"),
               GIT_CEILING_DIRECTORIES=str(tmp), GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    for key in ("HOME", "SDD_CONFIG_HOME", "CLAUDE_CONFIG_DIR"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    return env


def run_retro(env: dict, cwd: Path, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "retro", *args], cwd=cwd, capture_output=True, text=True,
                          env=env, check=False)


def git(cwd: Path, env: dict, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


def git_init(root: Path, env: dict):
    git(root, env, "init", "-q", "-b", "main")
    git(root, env, "add", "-A")
    git(root, env, "commit", "-qm", "init")


def section(md: str, title: str) -> str:
    """Texto da seção Markdown cujo cabeçalho contém `title`, até o próximo cabeçalho."""
    out, inside = [], False
    for line in md.splitlines():
        if line.startswith("#"):
            if inside:
                break
            inside = title in line
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


def tree_state(root: Path) -> dict:
    """Conteúdo e mtime de todos os arquivos (inclusive .git)."""
    state = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            st = path.stat()
            state[path.relative_to(root).as_posix()] = (path.read_bytes(), st.st_mtime_ns)
    return state


def git_state(root: Path, env: dict) -> tuple:
    quiet = dict(env, GIT_OPTIONAL_LOCKS="0")
    return (git(root, quiet, "rev-parse", "HEAD").strip(),
            git(root, quiet, "status", "--porcelain", "--untracked-files=all"))


def all_files(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


class TempTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)


# --------------------------------------------------------------------------- testes unitários

class MetricsTest(TempTest):
    def test_project_metrics(self):
        """SPEC-0074:UT-01 — inventário, stale, unclosed, lead time, gates, evidência, N/A, emendas e impedimentos."""
        evidence_origin = fn("evidence_origin")
        for text, origin in ((GEN["G0"], "gerada"), (GEN["G1"], "gerada"), (GEN["G4"], "gerada"),
                             (GEN["G7"], "gerada"), (f"build exit 0 (ok); test exit 0 (OK) — {SHA} (árvore suja)",
                                                     "gerada"),
                             ("MANUAL: CI verde no PR", "manual"), ("aprovado por thomas — ok", "humana"),
                             ("rodei os testes, tudo verde", "a_mao"), (f"rodei os testes — {SHA}", "a_mao")):
            self.assertEqual(evidence_origin(text), origin, text)

        retro_metrics = fn("retro_metrics")
        root = self.tmp / "proj-ut01"
        ut01_project(root)
        m = retro_metrics(sg.Project(root), TODAY, 30)
        self.assertEqual(m["name"], "proj-ut01")
        self.assertIs(m["private"], False)
        self.assertEqual(m["specs"], {"total": 7, "by_status": {"proposed": 1, "approved": 2, "in-progress": 1,
                                                                "implemented": 3},
                                      "by_tier": {"lite": 1, "full": 6}})
        self.assertEqual((m["tool"]["project"], m["tool"]["installed"]), ("2026.10.8", VERSION))
        self.assertEqual(m["last_activity"], "2026-11-12")
        # SPEC-0002: 40 dias sem atividade; SPEC-0004: exatamente 30 dias (não conta); SPEC-0001 é proposed
        self.assertEqual(m["stale"], ["SPEC-0002"])
        self.assertEqual(m["unclosed"], ["SPEC-0003"])
        # lead times 10, 20 e 40 dias: mediana 20, p90 (nearest-rank) 40
        self.assertEqual(m["lead_time_days"]["median"], 20)
        self.assertEqual(m["lead_time_days"]["p90"], 40)
        self.assertEqual(set(m["gates"]), set(GATES))
        expected_gates = {"G0": (6, 0, 0), "G1": (4, 1, 0), "G2": (4, 0, 0), "G3": (1, 0, 3), "G4": (4, 0, 0),
                          "G5": (4, 0, 0), "H2": (4, 0, 0), "G6": (1, 0, 2), "G7": (3, 0, 0)}
        for g, (p, f, na) in expected_gates.items():
            self.assertEqual(m["gates"][g], {"PASS": p, "FAIL": f, "N/A": na}, g)
        self.assertIsNone(m["fail_history"], "pasta fora de repositório git")
        self.assertEqual(m["evidence"], {"gerada": 19, "manual": 2, "humana": 1, "a_mao": 1})
        self.assertEqual(set(m["na_by_gate"]), set(GATES))
        self.assertEqual(m["na_by_gate"]["G3"], {"na": 3, "total": 4})
        self.assertEqual(m["na_by_gate"]["G6"], {"na": 2, "total": 3})
        self.assertEqual(m["na_by_gate"]["G1"], {"na": 0, "total": 5})
        self.assertEqual(m["na_by_gate"]["G7"], {"na": 0, "total": 3})
        self.assertEqual(m["amendments"], {"total": 3, "by_spec": {"SPEC-0003": 1, "SPEC-0005": 2}})
        # IMP-01 aberto há 47 dias; IMP-03 há exatamente 30 (não conta); IMP-02 fechado
        self.assertEqual(m["impediments"], {"total": 3, "open": 2, "old": ["SPEC-0004/IMP-01"]})

        m10 = retro_metrics(sg.Project(root), TODAY, 10, name="outro-nome")
        self.assertEqual(m10["name"], "outro-nome")
        self.assertEqual(m10["stale"], ["SPEC-0002", "SPEC-0004"])
        self.assertEqual(m10["impediments"]["old"], ["SPEC-0004/IMP-01", "SPEC-0004/IMP-03"])


class FailHistoryTest(TempTest):
    def test_fail_removed_from_gate_register_is_counted_from_git(self):
        """SPEC-0074:UT-02 — G2 FAIL num commit e PASS no seguinte: fail_history = 1; fora do git: null e "sem git"."""
        retro_fail_history = fn("retro_fail_history")
        retro_metrics = fn("retro_metrics")
        env = isolated_env(self.tmp)
        root = self.tmp / "com-git"
        specs = root / "docs" / "specs"
        specs.mkdir(parents=True)
        (specs / "sdd-config.yml").write_text("base_branch: main\n", encoding="utf-8")
        (root / "README.md").write_text("# demo\n", encoding="utf-8")
        git_init(root, env)
        failing = pass_all("2026-11-01", upto=("G0", "G1"))
        failing["G2"] = ("FAIL", f"test exit 1 (1 failed) — {SHA}", "2026-11-01")
        write_spec(specs, "SPEC-0001", spec_md("SPEC-0001", "in-progress", created="2026-10-30",
                                               approved_at="2026-10-31", gates=failing,
                                               verification=[("UT-01", "FAIL")]))
        git(root, env, "add", "-A")
        git(root, env, "commit", "-qm", "test: G2 FAIL")
        passing = pass_all("2026-11-02", upto=("G0", "G1", "G2"))
        # a linha FAIL da Verificação também sai, mas não é do Registro de Gates
        write_spec(specs, "SPEC-0001", spec_md("SPEC-0001", "in-progress", created="2026-10-30",
                                               approved_at="2026-10-31", gates=passing,
                                               verification=[("UT-01", "PASS")]))
        git(root, env, "add", "-A")
        git(root, env, "commit", "-qm", "feat: G2 PASS")

        self.assertEqual(retro_fail_history(specs), 1)
        m = retro_metrics(sg.Project(root), TODAY, 30)
        self.assertEqual(m["fail_history"], 1)
        self.assertEqual(sum(v["FAIL"] for v in m["gates"].values()), 0)
        self.assertEqual(git(root, env, "status", "--porcelain"), "", "o histórico não pode mexer no repositório")

        copy = self.tmp / "sem-git"
        shutil.copytree(root, copy, ignore=shutil.ignore_patterns(".git"))
        self.assertIsNone(retro_fail_history(copy / "docs" / "specs"))
        self.assertIsNone(retro_metrics(sg.Project(copy), TODAY, 30)["fail_history"])
        res = run_retro(env, self.tmp, str(copy))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        projects_md = section(res.stdout, "Projetos")
        self.assertTrue("sem git" in projects_md or "sem histórico" in projects_md, res.stdout)
        res = run_retro(env, self.tmp, str(copy), "--json")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        project = json.loads(res.stdout)["projects"][0]
        self.assertIsNone(project["fail_history"])
        self.assertEqual(project["gates"]["G2"]["PASS"], 1)


class FindingsTest(unittest.TestCase):
    def rules(self, metrics) -> dict:
        retro_findings = fn("retro_findings")
        out = {}
        for finding in retro_findings([metrics]):
            self.assertEqual(set(finding), {"rule", "project", "value", "action"}, finding)
            self.assertEqual(finding["project"], metrics["name"])
            out.setdefault(finding["rule"], []).append(finding)
        return out

    def assert_fires(self, metrics, rule, *action_parts, value_part=None):
        found = self.rules(metrics).get(rule)
        self.assertTrue(found, f"{rule} deveria disparar: {metrics}")
        for part in action_parts:
            self.assertIn(part, found[0]["action"], rule)
        if value_part is not None:
            self.assertIn(value_part, " ".join(str(f["value"]) for f in found), rule)
        return found

    def assert_quiet(self, metrics, rule):
        self.assertNotIn(rule, self.rules(metrics), f"{rule} não deveria disparar: {metrics}")

    def test_rules_fire_at_the_limit_and_not_below(self):
        """SPEC-0074:UT-03 — R1 a R7 no limite e logo abaixo; sugestão para a skill em >= 50% (mín. 2)."""
        base = neutral_metrics()
        self.assertEqual(fn("retro_findings")([base]), [], "métricas neutras não disparam nenhuma regra")

        # R1 ferramenta atrasada
        m = neutral_metrics()
        m["tool"]["project"] = "2000.1.1"
        self.assert_fires(m, "R1", "whats-new", "vendor --force")
        m["tool"]["project"] = "desconhecida"
        self.assert_fires(m, "R1", "whats-new")
        m = neutral_metrics(private=True)
        m["tool"]["project"] = "2000.1.1"
        self.assert_fires(m, "R1", "whats-new --ack")
        self.assert_quiet(neutral_metrics(), "R1")  # versão igual à instalada
        m = neutral_metrics()
        m["tool"]["project"] = "2999.1.1"
        self.assert_quiet(m, "R1")

        # R2 spec parada / R3 entregue sem fechar / R7 impedimento velho
        for rule, key, ident, action in (("R2", "stale", "SPEC-0009", "deprecated"),
                                         ("R3", "unclosed", "SPEC-0008", "G7")):
            m = neutral_metrics()
            m[key] = [ident]
            self.assert_fires(m, rule, action, value_part=ident)
            self.assert_quiet(neutral_metrics(), rule)
        m = neutral_metrics()
        m["impediments"] = {"total": 1, "open": 1, "old": ["SPEC-0007/IMP-01"]}
        self.assert_fires(m, "R7", "resolve", value_part="SPEC-0007/IMP-01")
        m["impediments"] = {"total": 1, "open": 1, "old": []}
        self.assert_quiet(m, "R7")

        # R4 evidência à mão: > 30% com >= 10 PASS
        m = neutral_metrics()
        m["evidence"] = {"gerada": 5, "manual": 2, "humana": 1, "a_mao": 2}  # 4/10 = 40%
        self.assert_fires(m, "R4", "--run")
        m["evidence"] = {"gerada": 6, "manual": 3, "humana": 1, "a_mao": 0}  # 3/10 = 30%
        self.assert_quiet(m, "R4")
        m["evidence"] = {"gerada": 5, "manual": 2, "humana": 0, "a_mao": 2}  # 4/9, mas < 10 PASS
        self.assert_quiet(m, "R4")

        # R5 nenhuma reprovação: >= 20 PASS de G1–G5 e fail_history == 0
        m = neutral_metrics()
        for g in ("G1", "G2", "G3", "G4", "G5"):
            m["gates"][g]["PASS"] = 4
        m["gates"]["G0"]["PASS"] = 10
        m["fail_history"] = 0
        self.assert_fires(m, "R5", "--fail")
        m["gates"]["G5"]["PASS"] = 3  # 19 (G0 não conta)
        self.assert_quiet(m, "R5")
        m["gates"]["G5"]["PASS"] = 4
        m["fail_history"] = 1
        self.assert_quiet(m, "R5")
        m["fail_history"] = None  # sem git: não dá para concluir
        self.assert_quiet(m, "R5")

        # R6 N/A recorrente: >= 50% das specs que registram o gate, mínimo 5
        m = neutral_metrics()
        m["na_by_gate"]["G6"] = {"na": 3, "total": 6}
        self.assert_fires(m, "R6", "pillars.waived", value_part="G6")
        m["na_by_gate"]["G6"] = {"na": 2, "total": 5}
        self.assert_quiet(m, "R6")
        m["na_by_gate"]["G6"] = {"na": 2, "total": 4}
        self.assert_quiet(m, "R6")

        # O que ajustar na skill
        retro_skill_suggestions = fn("retro_skill_suggestions")
        findings = [{"rule": "R2", "project": "a", "value": "SPEC-0001", "action": "x"},
                    {"rule": "R2", "project": "b", "value": "SPEC-0002", "action": "x"},
                    {"rule": "R3", "project": "a", "value": "SPEC-0003", "action": "x"},
                    {"rule": "R6", "project": "c", "value": "G3", "action": "x"},
                    {"rule": "R6", "project": "c", "value": "G6", "action": "x"}]
        suggestions = retro_skill_suggestions(findings, 4)
        self.assertEqual([s["rule"] for s in suggestions], ["R2"], suggestions)
        self.assertEqual(set(suggestions[0]), {"rule", "projects", "suggestion"})
        self.assertEqual(suggestions[0]["projects"], 2)
        self.assertTrue(str(suggestions[0]["suggestion"]).strip())
        self.assertEqual(retro_skill_suggestions(findings[2:3], 2), [], "1 de 2 projetos: abaixo do mínimo de 2")
        self.assertEqual(retro_skill_suggestions(findings[:2], 5), [], "2 de 5 projetos: abaixo de 50%")


class PrivacyTest(TempTest):
    def test_report_never_carries_titles_evidence_na_reasons_or_impediments(self):
        """SPEC-0074:UT-04 — marcadores em títulos, evidências, motivos de N/A e impedimentos não saem no relatório."""
        markers = {"titulo": "MARCA-TITULO-7f3a", "evidencia": "MARCA-EVID-91c2", "na": "MARCA-NA-55d0",
                   "impedimento": "MARCA-IMP-0b8e"}
        root = self.tmp / "terceiro"
        ut01_project(root, title=f"Cobrança {markers['titulo']}", evidence_marker=markers["evidencia"],
                     na_marker=markers["na"], imp_marker=markers["impedimento"])
        env = isolated_env(self.tmp)
        md = run_retro(env, self.tmp, str(root))
        self.assertEqual(md.returncode, 0, md.stdout + md.stderr)
        self.assertIn("Projetos", md.stdout)
        js = run_retro(env, self.tmp, str(root), "--json")
        self.assertEqual(js.returncode, 0, js.stdout + js.stderr)
        self.assertEqual(json.loads(js.stdout)["retro_version"], 1)
        for kind, marker in markers.items():
            for label, res in (("Markdown", md), ("JSON", js)):
                self.assertNotIn(marker, res.stdout + res.stderr, f"{kind} vazou na saída {label}")


class FoldersTest(TempTest):
    def test_missing_ignored_and_nothing_to_analyse(self):
        """SPEC-0074:UT-05 — pasta inexistente (exit 2), sem specs e legado em Ignorados, nada analisável (exit 2)."""
        env = isolated_env(self.tmp)
        missing = self.tmp / "nao-existe"
        res = run_retro(env, self.tmp, str(missing))
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("pasta não encontrada", res.stderr)
        self.assertIn(str(missing), res.stderr)

        valid = self.tmp / "valido"
        ut01_project(valid)
        empty = self.tmp / "sem-specs"
        empty.mkdir()
        legacy = self.tmp / "legado"
        (legacy / "docs" / "specs" / "approved").mkdir(parents=True)
        (legacy / "docs" / "specs" / "approved" / "2025-01-01-antiga.md").write_text("# antiga\n", encoding="utf-8")

        res = run_retro(env, self.tmp, str(valid), str(empty), str(legacy))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        ignored = section(res.stdout, "Ignorados")
        self.assertIn("sem-specs", ignored, res.stdout)
        self.assertIn("legado", ignored, res.stdout)
        res = run_retro(env, self.tmp, str(valid), str(empty), str(legacy), "--json")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        report = json.loads(res.stdout)
        self.assertEqual([p["name"] for p in report["projects"]], ["valido"])
        reasons = {Path(item["path"]).name: item["reason"] for item in report["ignored"]}
        self.assertEqual(set(reasons), {"sem-specs", "legado"}, report["ignored"])
        self.assertTrue(reasons["sem-specs"].strip())
        self.assertIn("legado", reasons["legado"])

        res = run_retro(env, self.tmp, str(empty), str(legacy))
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        out = res.stdout + res.stderr
        self.assertIn("nenhum projeto SDD encontrado", out)
        self.assertIn("sem-specs", out)
        self.assertIn("legado", out)


class StaleDaysTest(TempTest):
    def test_invalid_stale_days(self):
        """SPEC-0074:UT-06 — --stale-days 0, negativo ou texto: exit 2 com mensagem de uso."""
        env = isolated_env(self.tmp)
        root = self.tmp / "proj"
        ut01_project(root)
        ok = run_retro(env, self.tmp, str(root), "--stale-days", "1")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        for value in ("0", "-3", "abc"):
            res = run_retro(env, self.tmp, str(root), f"--stale-days={value}")
            self.assertEqual(res.returncode, 2, value + res.stdout + res.stderr)
            self.assertIn("stale-days", res.stderr, value)
            self.assertNotIn("invalid choice", res.stderr, value)


class SlugPrivacyTest(TempTest):
    def test_spec_without_id_does_not_leak_the_file_slug(self):
        """SPEC-0074:UT-04 (Emenda v2) — spec sem `id`: o slug do nome do arquivo não sai; aparece só como SPEC-NNNN."""
        marker = "marcadorslugsecreto"
        root = self.tmp / "sem-id"
        specs = root / "docs" / "specs"
        specs.mkdir(parents=True)
        (specs / "sdd-config.yml").write_text("base_branch: main\n", encoding="utf-8")
        text = spec_md("SPEC-0009", "approved", created="2020-01-01", approved_at="2020-01-02",
                       gates={"G0": ("PASS", GEN["G0"], "2020-01-02")})
        text = text.replace("id: SPEC-0009\n", "", 1)
        (specs / f"SPEC-0009-{marker}.md").write_text(text, encoding="utf-8")
        env = isolated_env(self.tmp)
        md = run_retro(env, self.tmp, str(root))
        js = run_retro(env, self.tmp, str(root), "--json")
        for label, res in (("Markdown", md), ("JSON", js)):
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertNotIn(marker, res.stdout + res.stderr, f"slug do arquivo vazou na saída {label}")
        self.assertIn("SPEC-0009", md.stdout)
        report = json.loads(js.stdout)
        self.assertEqual(report["projects"][0]["stale"], ["SPEC-0009"])
        r2 = [f for f in report["findings"] if f["rule"] == "R2"]
        self.assertTrue(r2 and "SPEC-0009" in str(r2[0]["value"]), r2)


@unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() != 0, "chmod 000 não bloqueia leitura como root")
class UnreadableTest(TempTest):
    def lock(self, path: Path):
        """chmod 000, restaurado antes da limpeza do diretório temporário (addCleanup é LIFO)."""
        mode = path.stat().st_mode
        path.chmod(0)
        self.addCleanup(path.chmod, mode)

    def test_unreadable_projects_are_ignored_with_reason(self):
        """SPEC-0074:UT-07 (Emenda v2) — spec não UTF-8, arquivo e pasta de specs sem leitura: Ignorados, sem traceback."""
        env = isolated_env(self.tmp)
        valid = self.tmp / "valido"
        ut01_project(valid)

        not_utf8 = self.tmp / "nao-utf8"
        ut01_project(not_utf8)
        (not_utf8 / "docs" / "specs" / "SPEC-0010-binaria.md").write_bytes(b"\xff")

        locked_file = self.tmp / "arquivo-bloqueado"
        ut01_project(locked_file)
        self.lock(locked_file / "docs" / "specs" / "SPEC-0002-funcionalidade.md")

        locked_dir = self.tmp / "pasta-bloqueada"
        ut01_project(locked_dir)
        self.lock(locked_dir / "docs" / "specs")

        bad = ("nao-utf8", "arquivo-bloqueado", "pasta-bloqueada")
        args = [str(valid)] + [str(self.tmp / name) for name in bad]
        md = run_retro(env, self.tmp, *args)
        self.assertEqual(md.returncode, 0, md.stdout + md.stderr)
        self.assertNotIn("Traceback", md.stderr)
        self.assertIn("valido", section(md.stdout, "Projetos"), md.stdout)
        ignored_md = section(md.stdout, "Ignorados")
        for name in bad:
            self.assertIn(name, ignored_md, md.stdout)

        js = run_retro(env, self.tmp, *args, "--json")
        self.assertEqual(js.returncode, 0, js.stdout + js.stderr)
        self.assertNotIn("Traceback", js.stderr)
        report = json.loads(js.stdout)
        self.assertEqual([p["name"] for p in report["projects"]], ["valido"])
        reasons = {Path(item["path"]).name: item["reason"] for item in report["ignored"]}
        self.assertEqual(set(reasons), set(bad), report["ignored"])
        for name in bad:
            self.assertTrue(str(reasons[name]).strip(), f"{name} sem motivo")

    def test_non_utf8_history_only_nulls_fail_history(self):
        """SPEC-0074:UT-07 (Emenda v2) — arquivo latin-1 commitado na pasta de specs: só fail_history null."""
        env = isolated_env(self.tmp)
        root = self.tmp / "historico-latin1"
        specs = ut01_project(root)
        attachment = specs / "anexo.txt"
        attachment.write_bytes("versão inicial\n".encode("latin-1"))
        git_init(root, env)
        attachment.write_bytes("revisão com acentuação\n".encode("latin-1"))
        git(root, env, "add", "-A")
        git(root, env, "commit", "-qm", "anexo latin-1")

        with mock.patch.dict(os.environ, env):
            try:
                history = fn("retro_fail_history")(specs)
            except UnicodeDecodeError as e:
                self.fail(f"retro_fail_history caiu com histórico não UTF-8: {e}")
        self.assertIsNone(history)
        res = run_retro(env, self.tmp, str(root), "--json")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        report = json.loads(res.stdout)
        self.assertEqual(report["ignored"], [])
        project = report["projects"][0]
        self.assertEqual(project["name"], "historico-latin1")
        self.assertIsNone(project["fail_history"])
        self.assertEqual(project["specs"]["total"], 7)
        self.assertEqual(project["unclosed"], ["SPEC-0003"])
        self.assertEqual(project["evidence"], {"gerada": 19, "manual": 2, "humana": 1, "a_mao": 1})
        self.assertEqual(project["gates"]["G1"], {"PASS": 4, "FAIL": 1, "N/A": 0})


class CurrentFailTest(unittest.TestCase):
    def test_r5_quiet_with_current_fail(self):
        """SPEC-0074:UT-07 (Emenda v2) — R5 não dispara com FAIL atual na tabela, mesmo com fail_history 0."""
        retro_findings = fn("retro_findings")
        m = neutral_metrics()
        for g in ("G1", "G2", "G3", "G4", "G5"):
            m["gates"][g]["PASS"] = 4
        m["fail_history"] = 0
        self.assertIn("R5", [f["rule"] for f in retro_findings([m])], "base: R5 dispara sem FAIL atual")
        m["gates"]["G2"]["FAIL"] = 1
        self.assertNotIn("R5", [f["rule"] for f in retro_findings([m])], "FAIL atual em G2: houve reprovação")


class RepoShapeTest(TempTest):
    def test_worktree_of_private_project_and_repo_without_remote(self):
        """SPEC-0074:UT-08 (Emenda v2) — worktree de projeto privado conta uma vez como privado; sem remoto, público.
        (guarda: passa antes da mudança)
        """
        priv = PrivateEnv(self.tmp / "priv")
        env = isolated_env(self.tmp, base=priv.env)
        env.update(HOME=priv.env["HOME"], SDD_CONFIG_HOME=priv.env["SDD_CONFIG_HOME"])
        priv.env = env
        priv.init()
        write_spec(priv.spec_root / "specs", "SPEC-0001",
                   spec_md("SPEC-0001", "approved", created="2020-01-01", approved_at="2020-01-02",
                           gates={"G0": ("PASS", GEN["G0"], "2020-01-02")}))
        git(priv.spec_root, env, "add", "-A")
        git(priv.spec_root, env, "commit", "-qm", "sdd: spec")
        worktree = self.tmp / "wt"
        git(priv.repo, env, "worktree", "add", "-q", "-b", "feature", str(worktree))

        res = run_retro(env, self.tmp, str(worktree), "--registry", "--json")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        report = json.loads(res.stdout)
        self.assertEqual([(p["name"], p["private"]) for p in report["projects"]], [(PRIVATE_KEY, True)],
                         report["projects"])
        self.assertEqual(report["ignored"], [])

        bare = self.tmp / "sem-remoto"
        ut01_project(bare)
        git_init(bare, env)
        res = run_retro(env, self.tmp, str(bare), "--json")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        project = json.loads(res.stdout)["projects"][0]
        self.assertEqual((project["name"], project["private"]), ("sem-remoto", False))


# --------------------------------------------------------------------------- testes de integração

class IntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.private = PrivateEnv(self.tmp / "priv")
        self.env = isolated_env(self.tmp, base=self.private.env)
        self.env.update(HOME=self.private.env["HOME"], SDD_CONFIG_HOME=self.private.env["SDD_CONFIG_HOME"])
        self.private.env = self.env
        self.private.init()
        old = {"G0": ("PASS", GEN["G0"], "2020-01-02")}
        specs = self.private.spec_root / "specs"
        write_spec(specs, "SPEC-0001", spec_md("SPEC-0001", "approved", created="2020-01-01",
                                               approved_at="2020-01-02", gates=old))
        git(self.private.spec_root, self.env, "add", "-A")
        git(self.private.spec_root, self.env, "commit", "-qm", "sdd: spec parada")

        self.public = self.tmp / "publico"
        pub_specs = self.public / "docs" / "specs"
        pub_specs.mkdir(parents=True)
        (pub_specs / "sdd-config.yml").write_text("base_branch: main\n", encoding="utf-8")
        write_spec(pub_specs, "SPEC-0001", spec_md("SPEC-0001", "approved", created="2020-01-01",
                                                   approved_at="2020-01-02", gates=old))
        write_spec(pub_specs, "SPEC-0002", spec_md("SPEC-0002", "in-progress", created="2020-01-01",
                                                   approved_at="2020-01-02", gates=pass_all("2020-01-10")))
        git_init(self.public, self.env)
        self.roots = (self.public, self.private.repo, self.private.spec_root)

    def snapshot(self) -> dict:
        return {str(r): tree_state(r) for r in self.roots}

    def git_snapshot(self) -> dict:
        return {str(r): git_state(r, self.env) for r in self.roots}

    def test_report_over_public_and_private_projects_is_read_only(self):
        """SPEC-0074:IT-01 — público + privado (--registry): projetos, achados, sugestões; nada muda nos repositórios."""
        git_before = self.git_snapshot()
        files_before = self.snapshot()
        md = run_retro(self.env, self.tmp, str(self.public), "--registry")
        js = run_retro(self.env, self.tmp, str(self.public), "--registry", "--json")
        files_after = self.snapshot()
        git_after = self.git_snapshot()

        self.assertEqual(md.returncode, 0, md.stdout + md.stderr)
        out = md.stdout
        projects = [line for line in section(out, "Projetos").splitlines() if line.startswith("|")]
        self.assertEqual(len([line for line in projects if "publico" in line]), 1, out)
        self.assertEqual(len([line for line in projects if PRIVATE_KEY in line]), 1, out)
        findings = section(out, "Achados").splitlines()
        self.assertTrue(any("R2" in line and "publico" in line for line in findings), out)
        self.assertTrue(any("R2" in line and PRIVATE_KEY in line for line in findings), out)
        self.assertTrue(any("R3" in line and "publico" in line for line in findings), out)
        suggestions = section(out, "O que ajustar na skill")
        self.assertIn("R2", suggestions, out)
        self.assertNotIn("R3", suggestions, "R3 só em 1 de 2 projetos")

        self.assertEqual(js.returncode, 0, js.stdout + js.stderr)
        report = json.loads(js.stdout)
        by_private = {p["private"]: p for p in report["projects"]}
        self.assertEqual(len(report["projects"]), 2, report["projects"])
        self.assertEqual(by_private[True]["name"], PRIVATE_KEY)
        self.assertEqual(by_private[False]["name"], "publico")
        self.assertEqual(by_private[False]["unclosed"], ["SPEC-0002"])

        for root in self.roots:
            before, after = files_before[str(root)], files_after[str(root)]
            self.assertEqual(sorted(before), sorted(after), f"arquivos criados ou removidos em {root}")
            changed = [name for name in before if before[name] != after[name]]
            self.assertEqual(changed, [], f"conteúdo ou mtime mudou em {root}")
        self.assertEqual(git_before, git_after, "HEAD ou git status mudou")

    def test_json_out_writes_only_the_output_file(self):
        """SPEC-0074:IT-02 — --json --out: JSON com as chaves do contrato; só o arquivo de saída é criado."""
        target = self.tmp / "retro.json"
        before = all_files(self.tmp)
        res = run_retro(self.env, self.tmp, str(self.public), str(self.private.repo), "--registry", "--json",
                        "--out", str(target))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(str(target), res.stdout)
        self.assertEqual(all_files(self.tmp) - before, {"retro.json"}, "só o arquivo de saída pode ser criado")
        self.assertEqual(before - all_files(self.tmp), set())
        report = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(set(report), REPORT_KEYS)
        self.assertEqual(report["retro_version"], 1)
        self.assertEqual(report["installed_tool"], VERSION)
        self.assertEqual(report["stale_days"], 30)
        self.assertTrue(report["generated_at"])
        # o repositório privado passado como PASTA e o spec_root do registro são o mesmo projeto: conta uma vez
        self.assertEqual(len(report["projects"]), 2, [p["name"] for p in report["projects"]])
        self.assertEqual(sorted(p["private"] for p in report["projects"]), [False, True])
        for project in report["projects"]:
            self.assertTrue(PROJECT_KEYS <= set(project), (project["name"], PROJECT_KEYS - set(project)))
        self.assertTrue(report["findings"])
        for finding in report["findings"]:
            self.assertEqual(set(finding), {"rule", "project", "value", "action"})
        for suggestion in report["skill_suggestions"]:
            self.assertEqual(set(suggestion), {"rule", "projects", "suggestion"})
        self.assertIn("R2", [s["rule"] for s in report["skill_suggestions"]])
        self.assertEqual(report["ignored"], [])


if __name__ == "__main__":
    unittest.main()
