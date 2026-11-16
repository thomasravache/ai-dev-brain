"""Hook SessionStart do plugin fermion (SPEC-0058, ADR-0017).

Run: python3 -m unittest discover -s tests/plugin -p test_session_start.py

Interface que estes testes exigem de `hooks/session_start.py` (carregado por caminho, sem tocar no sys.path):

- `PLUGIN_ROOT`: a pasta acima de hooks/ (`Path(__file__)`), nunca o cwd.
- `run_cli(argv, cwd, timeout) -> subprocess.CompletedProcess`: único ponto que abre processo (lista de argumentos,
  sem shell, `capture_output`, `text`, `check=False`), como o `run_cli` de mcp/fermion_mcp.py. Não engole exceções.
- `main(stdin=None, stdout=None, stderr=None, runner=run_cli) -> int`: lê o JSON do hook de `stdin` (padrão
  sys.stdin), escreve o JSON do hook em `stdout` e as linhas de diagnóstico em `stderr`; devolve sempre 0.
  `runner` é o executor substituível (o dublê dos UT): chamado como `runner(argv, cwd, timeout)` (posicional ou
  por nome) com `argv = [<python>, <PLUGIN_ROOT>/skills/<skill>/scripts/<cli>.py, ...]`; pode levantar
  `FileNotFoundError` / `OSError` (CLI ausente) e `subprocess.TimeoutExpired`.
- Rodado como script (`python3 hooks/session_start.py`), faz `sys.exit(main())`.
- Emenda v2: `main(..., clock=time.monotonic)`. `clock()` devolve segundos (monotônico); o prazo total é de 20 s a
  partir da primeira leitura do relógio, cada chamada recebe `timeout <= min(10, restante)` e, sem tempo restante,
  a CLI é pulada (o executor não é chamado) com a linha `session_start: <bloco> indisponível (...)`. Falha de uma
  CLI (inclusive `UnicodeDecodeError` ou stdout que não é texto) ou do cwd (`PermissionError`) omite só o bloco
  dela. `stdin=None` com `sys.stdin` None (stdin fechado) usa o cwd do processo.

UT-07 testa as regras de arquitetura contra exemplos e contra o código real. As regras genéricas (só stdlib, nenhum
import de skills/ nem carregamento dinâmico, nenhum shell, processo só em `run_cli`) são as de
mcp/tests/architecture_rules.py (carregadas por caminho); a regra "processo só para as três CLIs" fica aqui.

IT-01 cria um projeto temporário com a CLI real da gluon-spec e roda o hook como processo, com HOME, XDG_CONFIG_HOME,
ATLAS_CONFIG_HOME e BRAIN_CONFIG_HOME temporários: nunca toca a configuração real de quem roda.

SPEC-0061 (ADR-0019): o hook também roda `<python> <PLUGIN_ROOT>/scripts/fermion_doctor.py --project <raiz do projeto>
--json` (cwd = a mesma raiz das CLIs), dentro do mesmo prazo (timeout <= min(10, restante); sem tempo, pulado), e
com achado acrescenta, depois dos blocos da SPEC-0058, o bloco "## Instalação desatualizada (fermion)\n" com uma linha
"- <detail> → <fix>" por achado, no máximo 1.500 caracteres (o que não cabe vira a última linha "… e mais N"). Sem
achado, nenhum bloco. Doctor que falha (exit diferente de 0, JSON ilegível, timeout, ausente) tira só esse bloco e vira
a linha `session_start: Doctor indisponível (...)` no stderr. O FakeRunner responde ao doctor com zero achados por
padrão, para que os testes da SPEC-0058 continuem valendo com o doctor no hook.
"""
import ast
import importlib.util
import inspect
import io
import json
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

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "session_start.py"
HOOK_NAME = "hooks/session_start.py"
SPEC_GRAPH = REPO / "skills" / "gluon-spec" / "scripts" / "spec_graph.py"
SDD_CONFIG_TEMPLATE = REPO / "skills" / "gluon-spec" / "references" / "sdd-config.template.yml"
MCP_RULES = REPO / "mcp" / "tests" / "architecture_rules.py"

CLIS = {
    "spec_graph.py": REPO / "skills" / "gluon-spec" / "scripts" / "spec_graph.py",
    "atlas.py": REPO / "skills" / "boson-atlas" / "scripts" / "atlas.py",
    "brain.py": REPO / "skills" / "photon-brain" / "scripts" / "brain.py",
}
READ_COMMANDS = {"spec_graph.py": ["status"], "atlas.py": ["config", "--json"], "brain.py": ["config", "--json"]}
DOCTOR = REPO / "scripts" / "fermion_doctor.py"  # SPEC-0061
NO_FINDINGS = json.dumps({"plugin_versions": {"gluon-spec": "2026.11.3", "photon-brain": "2026.11.6",
                                              "boson-atlas": "2026.11.6"}, "findings": []})

SDD_HEADER = "## SDD (gluon-spec)\n"
CUT_NOTICE = "… (cortado; rode `status`)"
ATLAS_LINE = ("Atlas da organização (boson-atlas) configurado nesta máquina: para contexto de sistemas, use a skill "
              "boson-atlas ou a tool MCP atlas_context.")
BRAIN_LINE = ("Segundo cérebro (photon-brain) configurado nesta máquina: para notas e decisões do usuário, use a "
              "skill photon-brain.")
UNAVAILABLE_RE = re.compile(r"^session_start: (SDD|Atlas|Brain|Doctor) indisponível \(.+\)$", re.IGNORECASE)
SDD_LIMIT, CONTEXT_LIMIT = 6000, 8000

GIT_ENV = {
    "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


def load_module(path, name):
    """Importa um arquivo por caminho sem gravar __pycache__ ao lado dele."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def load_hook(test):
    """hooks/session_start.py como módulo; falha (não erro) com mensagem clara quando ainda não existe."""
    if not HOOK.is_file():
        test.fail(f"{HOOK_NAME} não existe (SPEC-0058)")
    module = load_module(HOOK, "fermion_session_start")
    for name in ("main", "run_cli"):
        if not callable(getattr(module, name, None)):
            test.fail(f"{HOOK_NAME} não define {name}()")
    return module


def completed(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


class FakeRunner:
    """Executor substituível: responde por CLI (`spec_graph.py`, `atlas.py`, `brain.py`, `fermion_doctor.py`) e grava
    cada chamada.

    Cada resposta é um CompletedProcess-like (returncode, stdout, stderr) ou uma exceção a levantar. O doctor
    (SPEC-0061) responde por padrão com zero achados.
    """

    def __init__(self, status=(0, "", ""), atlas=(3, "", ""), brain=(3, "", ""), doctor=(0, NO_FINDINGS, "")):
        self.answers = {"spec_graph.py": status, "atlas.py": atlas, "brain.py": brain, "fermion_doctor.py": doctor}
        self.calls = []

    def __call__(self, argv, cwd=None, timeout=None):
        self.calls.append({"argv": list(argv), "cwd": cwd, "timeout": timeout})
        cli = Path(str(argv[1])).name if len(argv) > 1 else ""
        answer = self.answers.get(cli)
        if answer is None:
            raise AssertionError(f"processo inesperado: {argv}")
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return answer(argv, timeout)
        code, out, err = answer
        return completed(argv, code, out, err)

    def calls_to(self, cli):
        return [c for c in self.calls if Path(str(c["argv"][1])).name == cli]


def make_project(root, git="dir", sdd=True):
    """Projeto temporário: .git como pasta ou arquivo (worktree) ou sem .git; docs/specs/sdd-config.yml opcional."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if git == "dir":
        (root / ".git").mkdir()
    elif git == "file":
        (root / ".git").write_text("gitdir: /em/outro/lugar\n", encoding="utf-8")
    if sdd:
        (root / "docs" / "specs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "specs" / "sdd-config.yml").write_text("base_branch: main\n", encoding="utf-8")
    return root


def same_dir(a, b):
    return a is not None and Path(a).resolve() == Path(b).resolve()


def has_git_above(path):
    return any((p / ".git").exists() for p in Path(path).resolve().parents)


class HookTestCase(unittest.TestCase):
    def setUp(self):
        self.hook = load_hook(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def call_main(self, **kwargs):
        """main() que levanta exceção é falha do teste (o hook nunca pode quebrar), não erro."""
        try:
            return self.hook.main(**kwargs)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"main() levantou {type(exc).__name__}: {exc}")

    def run_hook(self, runner, stdin_text=None, cwd=None):
        """Roda main() com streams em memória; devolve (exit, stdout, stderr)."""
        if stdin_text is None:
            stdin_text = json.dumps({"session_id": "s1", "hook_event_name": "SessionStart", "source": "startup",
                                     "cwd": str(cwd)})
        out, err = io.StringIO(), io.StringIO()
        code = self.call_main(stdin=io.StringIO(stdin_text), stdout=out, stderr=err, runner=runner)
        return code, out.getvalue(), err.getvalue()

    def context(self, stdout):
        """additionalContext do JSON do hook, conferindo o invólucro do contrato."""
        if not stdout.strip():
            self.fail("o hook não imprimiu o JSON (nenhum bloco)")
        try:
            data = json.loads(stdout)
        except ValueError as exc:
            self.fail(f"stdout do hook não é JSON ({exc}): {stdout[:200]!r}")
        self.assertEqual(set(data), {"hookSpecificOutput"}, data)
        output = data["hookSpecificOutput"]
        self.assertEqual(output.get("hookEventName"), "SessionStart", output)
        context = output.get("additionalContext")
        self.assertIsInstance(context, str)
        self.assertLessEqual(len(context), CONTEXT_LIMIT)
        return context

    def assert_timeouts(self, runner):
        for call in runner.calls:
            self.assertIsNotNone(call["timeout"], call)
            self.assertTrue(0 < call["timeout"] <= 10, f"timeout por CLI acima de 10 s: {call}")


# ---------------------------------------------------------------- UT-01

class SddBlockTest(HookTestCase):
    def test_sdd_block_carries_status_run_at_project_root(self):
        """SPEC-0058:UT-01"""
        cases = [("git-pasta", "dir", ("src", "app")), ("git-arquivo", "file", ("sub",)), ("raiz", "dir", ())]
        if not has_git_above(self.base):
            cases.append(("sem-git", None, ()))
        for label, git, nested in cases:
            with self.subTest(case=label):
                project = make_project(self.base / label, git=git)
                cwd = project.joinpath(*nested)
                cwd.mkdir(parents=True, exist_ok=True)
                runner = FakeRunner(status=(0, "SPEC-0001 proposed\n", ""))
                code, out, _ = self.run_hook(runner, cwd=cwd)
                self.assertEqual(code, 0)
                context = self.context(out)
                self.assertTrue(context.startswith(SDD_HEADER), context)
                self.assertIn("SPEC-0001 proposed", context)
                status_calls = runner.calls_to("spec_graph.py")
                self.assertEqual(len(status_calls), 1, runner.calls)
                self.assertEqual(status_calls[0]["argv"][2:], ["status"])
                expected_root = project if git else cwd
                self.assertTrue(same_dir(status_calls[0]["cwd"], expected_root),
                                f"status rodou em {status_calls[0]['cwd']}, esperado {expected_root}")
                self.assert_timeouts(runner)


# ---------------------------------------------------------------- UT-02

class NothingToSayTest(HookTestCase):
    def test_no_sdd_and_nothing_configured_prints_nothing(self):
        """SPEC-0058:UT-02"""
        project = make_project(self.base / "p", sdd=False)
        runner = FakeRunner(status=(0, "não devia rodar", ""), atlas=(3, "", "erro: x"), brain=(3, "", "erro: y"))
        code, out, _ = self.run_hook(runner, cwd=project)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(runner.calls_to("spec_graph.py"), [], "status rodou num projeto sem sdd-config.yml")


# ---------------------------------------------------------------- UT-03

class ConfiguredLinesTest(HookTestCase):
    def test_atlas_and_brain_lines_in_order_without_cli_output(self):
        """SPEC-0058:UT-03"""
        project = make_project(self.base / "p", sdd=False)
        runner = FakeRunner(atlas=(0, '{"atlas": "/caminho/SEGREDO-ATLAS"}', ""),
                            brain=(0, '{"vault": "/caminho/SEGREDO-BRAIN"}', ""))
        code, out, _ = self.run_hook(runner, cwd=project)
        self.assertEqual(code, 0)
        context = self.context(out)
        self.assertEqual(context.strip(), ATLAS_LINE + "\n\n" + BRAIN_LINE)
        self.assertNotIn("SEGREDO", context)
        for cli in ("atlas.py", "brain.py"):
            calls = runner.calls_to(cli)
            self.assertEqual(len(calls), 1, runner.calls)
            self.assertEqual(calls[0]["argv"][2:], ["config", "--json"])

    def test_sdd_block_comes_first_separated_by_blank_line(self):
        """SPEC-0058:UT-03 (ordem dos blocos: SDD, atlas, cérebro)"""
        project = make_project(self.base / "p")
        runner = FakeRunner(status=(0, "SPEC-0001 proposed\n", ""), atlas=(0, "{}", ""), brain=(0, "{}", ""))
        _, out, _ = self.run_hook(runner, cwd=project)
        context = self.context(out)
        self.assertTrue(context.startswith(SDD_HEADER))
        sdd_at, atlas_at, brain_at = (context.index(SDD_HEADER), context.index(ATLAS_LINE),
                                      context.index(BRAIN_LINE))
        self.assertLess(sdd_at, atlas_at)
        self.assertLess(atlas_at, brain_at)
        self.assertIn("\n\n" + ATLAS_LINE, context)
        self.assertIn(ATLAS_LINE + "\n\n" + BRAIN_LINE, context)


# ---------------------------------------------------------------- UT-04

class SizeLimitTest(HookTestCase):
    def test_long_status_is_cut_to_6000_and_context_to_8000(self):
        """SPEC-0058:UT-04"""
        project = make_project(self.base / "p")
        status = "".join(f"SPEC-{n:04d} proposed    SPEC (G0)    linha longa de status para o corte\n"
                         for n in range(400))[:20000]
        self.assertEqual(len(status), 20000)
        runner = FakeRunner(status=(0, status, ""), atlas=(0, "{}", ""), brain=(0, "{}", ""))
        code, out, _ = self.run_hook(runner, cwd=project)
        self.assertEqual(code, 0)
        context = self.context(out)
        self.assertLessEqual(len(context), CONTEXT_LIMIT)
        block = context.split("\n\n" + ATLAS_LINE)[0]
        self.assertIn(ATLAS_LINE, context, "o corte do SDD não pode derrubar as outras linhas")
        self.assertIn(BRAIN_LINE, context)
        self.assertTrue(block.startswith(SDD_HEADER), block[:100])
        self.assertLessEqual(len(block), SDD_LIMIT, f"bloco SDD com {len(block)} caracteres")
        self.assertTrue(block.rstrip().endswith(CUT_NOTICE), block[-200:])
        kept = block[len(SDD_HEADER):block.rstrip().rindex(CUT_NOTICE)].rstrip()
        self.assertGreater(len(kept), 1000, "o corte jogou fora quase todo o status")
        self.assertTrue(status.startswith(kept), "o bloco SDD não é o começo do stdout do status")

    def test_short_status_is_not_cut(self):
        """SPEC-0058:UT-04 (status curto entra inteiro, sem aviso)"""
        project = make_project(self.base / "p")
        runner = FakeRunner(status=(0, "SPEC-0001 proposed\n", ""))
        _, out, _ = self.run_hook(runner, cwd=project)
        self.assertNotIn("cortado", self.context(out))


# ---------------------------------------------------------------- UT-05

class CliFailureTest(HookTestCase):
    def unavailable_lines(self, stderr):
        lines = [line for line in stderr.splitlines() if line.strip()]
        for line in lines:
            self.assertRegex(line, UNAVAILABLE_RE)
        return [UNAVAILABLE_RE.match(line).group(1).lower() for line in lines]

    def test_missing_cli_and_timeout_omit_blocks_with_stderr_line(self):
        """SPEC-0058:UT-05 (FileNotFoundError e TimeoutExpired em todas as CLIs)"""
        project = make_project(self.base / "p")
        failures = {"ausente": lambda: FileNotFoundError(2, "No such file or directory", "python3"),
                    "timeout": lambda: subprocess.TimeoutExpired(["python3"], 10)}
        for label, make in failures.items():
            with self.subTest(case=label):
                runner = FakeRunner(status=make(), atlas=make(), brain=make())
                code, out, err = self.run_hook(runner, cwd=project)
                self.assertEqual(code, 0)
                self.assertEqual(out, "", "bloco de CLI que falhou não pode aparecer")
                self.assertEqual(sorted(self.unavailable_lines(err)), ["atlas", "brain", "sdd"], err)
                self.assertNotIn("Traceback", err)

    def test_failure_omits_only_the_failing_block(self):
        """SPEC-0058:UT-05 (atlas configurado, cérebro ausente: só a linha do atlas)"""
        project = make_project(self.base / "p", sdd=False)
        runner = FakeRunner(atlas=(0, "{}", ""), brain=FileNotFoundError(2, "No such file or directory"))
        code, out, err = self.run_hook(runner, cwd=project)
        self.assertEqual(code, 0)
        self.assertEqual(self.context(out).strip(), ATLAS_LINE)
        self.assertEqual(self.unavailable_lines(err), ["brain"], err)

    def test_unexpected_config_exit_omits_block_with_stderr_line(self):
        """SPEC-0058:UT-05 (config com exit 2)"""
        project = make_project(self.base / "p", sdd=False)
        runner = FakeRunner(atlas=(2, "", "uso: atlas.py ..."), brain=(2, "", "uso: brain.py ..."))
        code, out, err = self.run_hook(runner, cwd=project)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(sorted(self.unavailable_lines(err)), ["atlas", "brain"], err)

    def test_failing_status_becomes_first_stderr_line_in_sdd_block(self):
        """SPEC-0058:UT-05 (status com exit 1: o bloco SDD diz que falhou)"""
        project = make_project(self.base / "p")
        runner = FakeRunner(status=(1, "saída parcial\n", "erro: x\nsegunda linha do erro\n"))
        code, out, _ = self.run_hook(runner, cwd=project)
        self.assertEqual(code, 0)
        context = self.context(out)
        self.assertTrue(context.startswith(SDD_HEADER), context)
        self.assertIn("status falhou: erro: x", context)
        self.assertNotIn("segunda linha do erro", context)


# ---------------------------------------------------------------- UT-06

class BadStdinTest(HookTestCase):
    def test_bad_stdin_never_raises_and_falls_back_to_process_cwd(self):
        """SPEC-0058:UT-06"""
        project = make_project(self.base / "p")
        old = os.getcwd()
        os.chdir(project)
        self.addCleanup(os.chdir, old)
        for label, stdin_text in (("json inválido", "{"), ("vazio", ""), ("sem cwd", "{}"), ("lista", "[]")):
            with self.subTest(case=label):
                runner = FakeRunner(status=(0, "SPEC-0001 proposed\n", ""))
                code, out, _ = self.run_hook(runner, stdin_text=stdin_text)
                self.assertEqual(code, 0)
                self.assertIn("SPEC-0001 proposed", self.context(out))
                calls = runner.calls_to("spec_graph.py")
                self.assertEqual(len(calls), 1, runner.calls)
                self.assertTrue(same_dir(calls[0]["cwd"], project), calls[0])

    def test_nonexistent_cwd_has_no_sdd_block(self):
        """SPEC-0058:UT-06 (cwd inexistente)"""
        missing = self.base / "nao" / "existe"
        runner = FakeRunner(status=(0, "SPEC-0001 proposed\n", ""), atlas=(0, "{}", ""))
        code, out, _ = self.run_hook(runner, stdin_text=json.dumps({"cwd": str(missing)}))
        self.assertEqual(code, 0)
        self.assertNotIn(SDD_HEADER.strip(), out)
        self.assertEqual(runner.calls_to("spec_graph.py"), [])
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["additionalContext"].strip(), ATLAS_LINE)

    def test_hook_run_as_process_exits_zero_on_bad_stdin(self):
        """SPEC-0058:UT-06 (processo real: stdin '{' e cwd inexistente saem com 0)"""
        if not HOOK.is_file():
            self.fail(f"{HOOK_NAME} não existe (SPEC-0058)")
        env = isolated_env(self.base / "env")
        for stdin_text in ("{", json.dumps({"cwd": "/nao/existe"})):
            with self.subTest(stdin=stdin_text):
                result = subprocess.run([sys.executable, str(HOOK)], input=stdin_text, cwd=self.base, env=env,
                                        capture_output=True, text=True, timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn(SDD_HEADER.strip(), result.stdout)


# ---------------------------------------------------------------- UT-05 (Emenda v2: prazo total e isolamento)

TOTAL_BUDGET, PER_CLI = 20, 10
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


class FakeClock:
    """Relógio monotônico falso: o executor "gasta" tempo avançando-o, sem sleep real."""

    def __init__(self, start=1000.0):
        self.start = self.now = start

    def __call__(self):
        return self.now

    def elapsed(self):
        return self.now - self.start


def spends(clock, seconds=None, result=(0, "", "")):
    """Resposta do executor que consome `seconds` (ou o timeout inteiro, levantando TimeoutExpired)."""
    def answer(argv, timeout):
        if seconds is None:
            clock.now += timeout
            raise subprocess.TimeoutExpired(argv, timeout)
        clock.now += seconds
        return completed(argv, *result)
    return answer


class DeadlineTest(HookTestCase):
    def run_with_clock(self, runner, clock, cwd):
        if "clock" not in inspect.signature(self.hook.main).parameters:
            self.fail("main() não aceita clock= (relógio injetável da Emenda v2)")
        out, err = io.StringIO(), io.StringIO()
        stdin = io.StringIO(json.dumps({"cwd": str(cwd)}))
        code = self.call_main(stdin=stdin, stdout=out, stderr=err, runner=runner, clock=clock)
        return code, out.getvalue(), err.getvalue()

    def assert_budget(self, runner, clock_at_calls, all_time_out=False):
        """Cada timeout <= min(10, restante na hora da chamada); quando todas esgotam o tempo, a soma <= 20."""
        total = 0
        three = [c for c in runner.calls if Path(str(c["argv"][1])).name in CLIS]  # o doctor (SPEC-0061) vem depois
        for call, at in zip(three, clock_at_calls):
            remaining = TOTAL_BUDGET - at
            self.assertIsNotNone(call["timeout"], call)
            self.assertGreater(call["timeout"], 0, call)
            self.assertLessEqual(call["timeout"], min(PER_CLI, remaining) + 1e-6,
                                 f"timeout {call['timeout']} com {remaining} s restantes: {call['argv'][1:]}")
            total += call["timeout"]
        if all_time_out:
            self.assertLessEqual(total, TOTAL_BUDGET + 1e-6, f"soma dos timeouts {total} s passa de 20 s")

    def recording(self, clock, answer):
        moments = []

        def wrapped(argv, timeout):
            moments.append(clock.elapsed())
            return answer(argv, timeout)
        return wrapped, moments

    def test_three_stuck_clis_fit_in_20_seconds_and_the_last_is_skipped(self):
        """SPEC-0058:UT-05 (prazo total: três CLIs que esgotam o tempo)"""
        project = make_project(self.base / "p")
        clock = FakeClock()
        moments = []
        answers = {}
        for cli in ("status", "atlas", "brain"):
            answers[cli], m = self.recording(clock, spends(clock))
            moments.append(m)
        runner = FakeRunner(status=answers["status"], atlas=answers["atlas"], brain=answers["brain"])
        code, out, err = self.run_with_clock(runner, clock, project)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        at = [m[0] for m in moments if m]
        self.assert_budget(runner, at, all_time_out=True)
        self.assertLessEqual(clock.elapsed(), TOTAL_BUDGET + 1e-6, f"o hook gastou {clock.elapsed()} s")
        self.assertEqual(runner.calls_to("brain.py"), [], "sem tempo restante a CLI do cérebro deveria ser pulada")
        labels = [UNAVAILABLE_RE.match(line).group(1).lower() for line in err.splitlines()
                  if UNAVAILABLE_RE.match(line)]
        self.assertEqual(sorted(label for label in labels if label != "doctor"), ["atlas", "brain", "sdd"], err)

    def test_each_call_gets_at_most_the_remaining_time(self):
        """SPEC-0058:UT-05 (prazo total: status gasta 7 s, atlas esgota o tempo, cérebro recebe o resto)"""
        project = make_project(self.base / "p")
        clock = FakeClock()
        status, m1 = self.recording(clock, spends(clock, 7, (0, "SPEC-0001 proposed\n", "")))
        atlas, m2 = self.recording(clock, spends(clock))
        brain, m3 = self.recording(clock, spends(clock, 1, (0, "{}", "")))
        runner = FakeRunner(status=status, atlas=atlas, brain=brain)
        code, out, err = self.run_with_clock(runner, clock, project)
        self.assertEqual(code, 0)
        self.assertEqual(len([c for c in runner.calls if Path(str(c["argv"][1])).name in CLIS]), 3, runner.calls)
        self.assert_budget(runner, m1 + m2 + m3)
        self.assertLessEqual(runner.calls_to("brain.py")[0]["timeout"], 3 + 1e-6)
        context = self.context(out)
        self.assertIn("SPEC-0001 proposed", context)
        self.assertNotIn(ATLAS_LINE, context)
        self.assertIn(BRAIN_LINE, context)
        self.assertRegex(err, re.compile(r"^session_start: Atlas indisponível", re.IGNORECASE | re.MULTILINE))


class UndecodableOutputTest(HookTestCase):
    def labels(self, err):
        return [UNAVAILABLE_RE.match(line).group(1).lower() for line in err.splitlines()
                if UNAVAILABLE_RE.match(line)]

    def test_unicode_decode_error_omits_only_its_block(self):
        """SPEC-0058:UT-05 (saída que não decodifica: UnicodeDecodeError omite só o bloco da CLI)"""
        project = make_project(self.base / "p")
        def decode():
            return UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

        cases = {
            "sdd": ({"status": decode(), "atlas": (0, "{}", ""), "brain": (0, "{}", "")},
                    [ATLAS_LINE, BRAIN_LINE]),
            "atlas": ({"status": (0, "SPEC-0001 proposed\n", ""), "atlas": decode(), "brain": (0, "{}", "")},
                      [SDD_HEADER.strip(), BRAIN_LINE]),
            "brain": ({"status": (0, "SPEC-0001 proposed\n", ""), "atlas": (0, "{}", ""), "brain": decode()},
                      [SDD_HEADER.strip(), ATLAS_LINE]),
        }
        for failing, (answers, kept) in cases.items():
            with self.subTest(failing=failing):
                code, out, err = self.run_hook(FakeRunner(**answers), cwd=project)
                self.assertEqual(code, 0)
                context = self.context(out)
                for text in kept:
                    self.assertIn(text, context)
                self.assertEqual(self.labels(err), [failing], err)

    def test_bytes_stdout_from_status_omits_only_the_sdd_block(self):
        """SPEC-0058:UT-05 (executor devolve stdout em bytes inválidos)"""
        project = make_project(self.base / "p")
        runner = FakeRunner(status=lambda argv, timeout: completed(argv, 0, b"\xff\xfe\xfa", b""),
                            atlas=(0, "{}", ""), brain=(0, "{}", ""))
        code, out, err = self.run_hook(runner, cwd=project)
        self.assertEqual(code, 0)
        context = self.context(out)
        self.assertNotIn(SDD_HEADER.strip(), context)
        self.assertEqual(context.strip(), ATLAS_LINE + "\n\n" + BRAIN_LINE)
        self.assertEqual(self.labels(err), ["sdd"], err)


# ---------------------------------------------------------------- UT-06 (Emenda v2: cwd ilegível e stdin fechado)

class UnreadableCwdAndClosedStdinTest(HookTestCase):
    @unittest.skipIf(IS_ROOT, "root lê pastas sem permissão")
    def test_cwd_under_unreadable_folder_omits_only_sdd(self):
        """SPEC-0058:UT-06 (cwd sob pasta com chmod 000: Atlas e Brain continuam)"""
        locked = self.base / "trancada"
        project = make_project(locked / "p")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        runner = FakeRunner(status=(0, "SPEC-0001 proposed\n", ""), atlas=(0, "{}", ""), brain=(0, "{}", ""))
        code, out, _ = self.run_hook(runner, cwd=project)
        self.assertEqual(code, 0)
        self.assertEqual(runner.calls_to("spec_graph.py"), [])
        self.assertEqual(self.context(out).strip(), ATLAS_LINE + "\n\n" + BRAIN_LINE)

    def test_closed_stdin_uses_process_cwd(self):
        """SPEC-0058:UT-06 (stdin None: sai com 0 e usa o cwd do processo)"""
        project = make_project(self.base / "p")
        old = os.getcwd()
        os.chdir(project)
        self.addCleanup(os.chdir, old)
        runner = FakeRunner(status=(0, "SPEC-0001 proposed\n", ""))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(self.hook.sys, "stdin", None):
            code = self.call_main(stdin=None, stdout=out, stderr=err, runner=runner)
        self.assertEqual(code, 0)
        self.assertIn("SPEC-0001 proposed", self.context(out.getvalue()))
        calls = runner.calls_to("spec_graph.py")
        self.assertEqual(len(calls), 1, runner.calls)
        self.assertTrue(same_dir(calls[0]["cwd"], project), calls[0])


# ---------------------------------------------------------------- UT-07

RULE_THREE_CLIS = "processo só para as três CLIs"
ALLOWED_SCRIPTS = {"spec_graph.py", "atlas.py", "brain.py", "session_start.py",
                   "fermion_doctor.py"}  # SPEC-0061: scripts/fermion_doctor.py do plugin (ADR-0019)
SCRIPT_RE = re.compile(r"[\w.-]+\.py\b")
EXTERNAL_COMMAND_RE = re.compile(r"^(?:git|gh|sh|bash|zsh|fish|cmd|powershell|pwsh|jq|curl|wget|claude|npm|npx|node"
                                 r"|uv|uvx|pip|pip3|xdg-open)(?:\.exe)?(?:\s|$)")


def _docstring_nodes(tree):
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                nodes.add(id(first.value))
    return nodes


def three_cli_findings(source, filename):
    """Textos que apontam para processo diferente das três CLIs: comando externo (git, gh, sh, jq, ...) como
    texto, script .py que não seja spec_graph.py, atlas.py ou brain.py, e tools/sdd/ (docstrings não contam)."""
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    findings = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in docstrings:
            continue
        text = node.value
        others = [name for name in SCRIPT_RE.findall(text) if name not in ALLOWED_SCRIPTS]
        if EXTERNAL_COMMAND_RE.match(text.strip()) or others or re.search(r"(^|/)tools/sdd(/|$)", text):
            findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_THREE_CLIS} — '{text}'"))
    return [message for _, message in sorted(findings)]


def mcp_rules(test):
    if not MCP_RULES.is_file():
        test.fail(f"{MCP_RULES.relative_to(REPO)} não existe (regras do ADR-0017 da SPEC-0054)")
    return load_module(MCP_RULES, "fermion_mcp_architecture_rules")


def report(findings):
    return "\n".join(findings)


def hook_source(test):
    if not HOOK.is_file():
        test.fail(f"{HOOK_NAME} não existe (SPEC-0058)")
    return HOOK.read_text(encoding="utf-8")


class HookArchitectureTest(unittest.TestCase):
    def setUp(self):
        self.rules = mcp_rules(self)

    def test_rules_report_violating_example(self):
        """SPEC-0058:UT-07 (exemplo que viola cada regra)"""
        source = (
            "import json\n"                                                         # 1
            "import subprocess\n"                                                   # 2
            "import requests\n"                                                     # 3
            "import spec_graph\n"                                                   # 4
            "from atlas import main\n"                                              # 5
            "def run_cli(argv, cwd, timeout):\n"                                    # 6
            "    return subprocess.run(argv, cwd=cwd, timeout=timeout, shell=True)\n"  # 7
            "def project_root(cwd):\n"                                              # 8
            "    return run_cli(['git', 'rev-parse', '--show-toplevel'], cwd, 10)\n"  # 9
            "def other(cwd):\n"                                                     # 10
            "    subprocess.run(['python3', 'skills/gluon-spec/scripts/other.py'])\n"  # 11
            "OLD = 'tools/sdd/spec_graph.py'\n"                                     # 12
            "OK = 'skills/gluon-spec/scripts/spec_graph.py'\n"                      # 13
        )
        imports = self.rules.import_findings(source, HOOK_NAME)
        self.assertEqual([f.split(" — ")[0] for f in imports], [f"{HOOK_NAME}:{n}" for n in (3, 4, 5)],
                         report(imports))
        self.assertIn("biblioteca padrão", imports[0])
        shell = self.rules.shell_findings(source, HOOK_NAME)
        self.assertEqual([f.split(" — ")[0] for f in shell], [f"{HOOK_NAME}:7"], report(shell))
        process = self.rules.process_findings(source, HOOK_NAME, ("run_cli",))
        self.assertEqual([f.split(" — ")[0] for f in process], [f"{HOOK_NAME}:11"], report(process))
        clis = three_cli_findings(source, HOOK_NAME)
        self.assertEqual([f.split(" — ")[0] for f in clis], [f"{HOOK_NAME}:{n}" for n in (9, 11, 12)],
                         report(clis))

    def test_real_hook_uses_stdlib_no_skill_code_no_shell_and_only_the_three_clis(self):
        """SPEC-0058:UT-07 (código real sem achado)"""
        source = hook_source(self)
        findings = (self.rules.import_findings(source, HOOK_NAME)
                    + self.rules.dynamic_code_findings(source, HOOK_NAME)
                    + self.rules.shell_findings(source, HOOK_NAME)
                    + self.rules.process_findings(source, HOOK_NAME, ("run_cli",))
                    + three_cli_findings(source, HOOK_NAME))
        self.assertEqual(findings, [], report(findings))

    def test_real_hook_opens_only_read_commands_of_the_three_clis(self):
        """SPEC-0058:UT-07 (comportamento: subprocess.run substituído, nenhum argumento vindo do stdin)"""
        hook = load_hook(self)
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp).resolve() / "p")
            stdin_text = json.dumps({"cwd": str(project), "session_id": "INJETADO; rm -rf /",
                                     "source": "--write", "transcript_path": "/tmp/INJETADO"})
            def answer(argv, *args, **kwargs):
                doctor = Path(str(argv[1])).name == DOCTOR.name  # SPEC-0061
                return completed(argv, 0, stdout=NO_FINDINGS if doctor else "SPEC-0001 proposed\n")
            with mock.patch.object(hook.subprocess, "run", side_effect=answer) as run, \
                    mock.patch.object(hook.subprocess, "Popen", side_effect=AssertionError("Popen não é usado")):
                code = hook.main(stdin=io.StringIO(stdin_text), stdout=io.StringIO(), stderr=io.StringIO())
        self.assertEqual(code, 0)
        calls = [(args, kwargs) for args, kwargs in run.call_args_list
                 if Path(str((args[0] if args else kwargs.get("args"))[1])).name != DOCTOR.name]  # SPEC-0061: UT-07
        self.assertEqual(len(calls), 3, run.call_args_list)
        seen = set()
        for args, kwargs in calls:
            argv = args[0] if args else kwargs.get("args")
            self.assertIsInstance(argv, list, "argv tem de ser lista (sem shell)")
            self.assertFalse(kwargs.get("shell", False))
            self.assertIsNotNone(kwargs.get("timeout"), "toda CLI roda com timeout")
            self.assertTrue(Path(argv[0]).name.startswith("python"), argv)
            cli = Path(argv[1]).name
            self.assertIn(cli, CLIS, argv)
            self.assertEqual(Path(argv[1]).resolve(), CLIS[cli].resolve(), "CLI fora da raiz do plugin")
            self.assertEqual(argv[2:], READ_COMMANDS[cli], argv)
            self.assertNotIn("INJETADO", " ".join(map(str, argv)))
            seen.add(cli)
        self.assertEqual(seen, set(CLIS))

    def test_plugin_root_comes_from_file_not_cwd(self):
        """SPEC-0058:UT-07 (raiz do plugin por Path(__file__))"""
        hook = load_hook(self)
        self.assertEqual(Path(hook.PLUGIN_ROOT).resolve(), REPO.resolve())


# ---------------------------------------------------------------- SPEC-0061:UT-07 (bloco do doctor)

DOCTOR_HEADER = "## Instalação desatualizada (fermion)\n"
DOCTOR_LIMIT = 1500
MORE_RE = re.compile(r"^… e mais (\d+)$")


def doctor_findings(count, prefix="cópia"):
    return [{"check": "old-name-copy", "level": "warn", "path": f"/x/skills/antiga-{n:02d}",
             "detail": f"{prefix} {n:02d} em /x/skills/antiga-{n:02d} com o nome antigo; o plugin já traz a nova",
             "fix": f"remova a pasta /x/skills/antiga-{n:02d}"} for n in range(count)]


def doctor_answer(findings):
    return (0, json.dumps({"plugin_versions": {"gluon-spec": "2026.11.3", "photon-brain": "2026.11.6",
                                               "boson-atlas": "2026.11.6"}, "findings": findings},
                          ensure_ascii=False), "")


def doctor_line(finding):
    return f"- {finding['detail']} → {finding['fix']}"


class DoctorBlockTest(HookTestCase):
    def doctor_block(self, context):
        self.assertTrue(DOCTOR_HEADER in context, f"sem o bloco do doctor; fim do contexto: {context[-300:]!r}")
        block = context[context.index(DOCTOR_HEADER):].rstrip()
        self.assertLessEqual(len(block), DOCTOR_LIMIT, f"bloco do doctor com {len(block)} caracteres")
        return block

    def test_two_findings_give_the_block_with_two_lines_after_the_others(self):
        """SPEC-0061:UT-07 (dois achados: o bloco com as duas linhas, depois dos blocos da SPEC-0058)"""
        findings = doctor_findings(2)
        expected = DOCTOR_HEADER + "\n".join(doctor_line(f) for f in findings)
        with self.subTest(caso="só o doctor"):
            project = make_project(self.base / "so-doctor", sdd=False)
            code, out, err = self.run_hook(FakeRunner(doctor=doctor_answer(findings)), cwd=project)
            self.assertEqual(code, 0)
            self.assertEqual(self.context(out).strip(), expected)
            self.assertEqual(err.strip(), "")
        with self.subTest(caso="com SDD, atlas e cérebro"):
            project = make_project(self.base / "todos")
            runner = FakeRunner(status=(0, "SPEC-0001 proposed\n", ""), atlas=(0, "{}", ""), brain=(0, "{}", ""),
                                doctor=doctor_answer(findings))
            code, out, _ = self.run_hook(runner, cwd=project)
            self.assertEqual(code, 0)
            context = self.context(out)
            self.assertTrue(context.startswith(SDD_HEADER), context)
            self.assertTrue(context.rstrip().endswith(BRAIN_LINE + "\n\n" + expected), context)

    def test_whitespace_in_detail_and_fix_is_flattened_to_one_line_per_finding(self):
        """SPEC-0061:UT-07 (Emenda v2: quebra de linha, \\r e tab no detail/fix viram um espaço; nada de '#' injetado)"""
        findings = [{"check": "old-name-copy", "level": "warn", "path": "/x/a",
                     "detail": "cópia antiga\n## X injetado\r\tsegunda parte",
                     "fix": "remova\n## Y\ra\tpasta"},
                    doctor_findings(1)[0]]
        project = make_project(self.base / "p", sdd=False)
        code, out, _ = self.run_hook(FakeRunner(doctor=doctor_answer(findings)), cwd=project)
        self.assertEqual(code, 0)
        block = self.doctor_block(self.context(out))
        lines = block.split("\n")
        self.assertEqual(lines[0] + "\n", DOCTOR_HEADER)
        self.assertEqual(len(lines), 1 + len(findings), lines)
        self.assertEqual(lines[1], "- cópia antiga ## X injetado segunda parte → remova ## Y a pasta")
        for line in lines[1:]:
            self.assertTrue(line.startswith("- "), line)
            self.assertNotIn("\r", line)
            self.assertNotIn("\t", line)
        self.assertEqual([line for line in block.splitlines() if line.startswith("#")], [DOCTOR_HEADER.strip()])

    def test_doctor_runs_once_with_project_and_json_inside_the_budget(self):
        """SPEC-0061:UT-07 (linha de comando do doctor: --project <raiz do projeto> --json, cwd e timeout)"""
        project = make_project(self.base / "p", sdd=False)
        cwd = project / "src" / "app"
        cwd.mkdir(parents=True)
        runner = FakeRunner(doctor=doctor_answer(doctor_findings(2)))
        self.run_hook(runner, cwd=cwd)
        calls = runner.calls_to(DOCTOR.name)
        self.assertEqual(len(calls), 1, runner.calls)
        argv = calls[0]["argv"]
        self.assertTrue(Path(argv[0]).name.startswith("python"), argv)
        self.assertEqual(Path(argv[1]).resolve(), DOCTOR.resolve(), "doctor fora da raiz do plugin")
        self.assertEqual(argv[2], "--project", argv)
        self.assertTrue(same_dir(argv[3], project), f"--project {argv[3]}, esperado {project}")
        self.assertEqual(argv[4:], ["--json"], argv)
        self.assertTrue(same_dir(calls[0]["cwd"], project), calls[0])
        self.assert_timeouts(runner)

    def test_zero_findings_give_no_block(self):
        """SPEC-0061:UT-07 (zero achados: nenhum bloco)"""
        with self.subTest(caso="nada mais a dizer"):
            project = make_project(self.base / "vazio", sdd=False)
            code, out, err = self.run_hook(FakeRunner(doctor=doctor_answer([])), cwd=project)
            self.assertEqual(code, 0)
            self.assertEqual(out, "")
            self.assertEqual(err.strip(), "")
        with self.subTest(caso="com o atlas configurado"):
            project = make_project(self.base / "atlas", sdd=False)
            code, out, _ = self.run_hook(FakeRunner(atlas=(0, "{}", ""), doctor=doctor_answer([])), cwd=project)
            self.assertEqual(self.context(out).strip(), ATLAS_LINE)

    def test_forty_findings_are_cut_to_1500_characters_with_and_more(self):
        """SPEC-0061:UT-07 (40 achados: até 1.500 caracteres, terminando em "… e mais N")"""
        findings = doctor_findings(40)
        project = make_project(self.base / "p", sdd=False)
        code, out, _ = self.run_hook(FakeRunner(doctor=doctor_answer(findings)), cwd=project)
        self.assertEqual(code, 0)
        block = self.doctor_block(self.context(out))
        lines = block[len(DOCTOR_HEADER):].split("\n")
        more = MORE_RE.match(lines[-1])
        self.assertIsNotNone(more, f"última linha não é '… e mais N': {lines[-1]!r}")
        shown = lines[:-1]
        self.assertGreater(len(shown), 0, "nenhum achado coube no bloco")
        self.assertEqual(shown, [doctor_line(f) for f in findings[:len(shown)]], "os achados mostrados mudaram")
        self.assertEqual(len(shown) + int(more.group(1)), 40)
        room = DOCTOR_LIMIT - len(block)
        self.assertLess(room, len(doctor_line(findings[len(shown)])) + 1,
                        "cabia mais um achado no bloco antes do '… e mais N'")

    def test_doctor_block_survives_the_8000_cut_of_a_long_status(self):
        """SPEC-0061:UT-07 (status longo, atlas, cérebro e 40 achados: o bloco do doctor continua inteiro)"""
        project = make_project(self.base / "p")
        status = "".join(f"SPEC-{n:04d} proposed    linha longa de status para o corte\n" for n in range(400))
        runner = FakeRunner(status=(0, status, ""), atlas=(0, "{}", ""), brain=(0, "{}", ""),
                            doctor=doctor_answer(doctor_findings(40)))
        _, out, _ = self.run_hook(runner, cwd=project)
        context = self.context(out)
        block = self.doctor_block(context)
        self.assertIsNotNone(MORE_RE.match(block.split("\n")[-1]), block[-200:])
        self.assertIn(BRAIN_LINE, context)

    def test_failing_doctor_omits_only_its_block_with_stderr_line(self):
        """SPEC-0061:UT-07 (doctor que falha: sem bloco, linha 'Doctor indisponível' no stderr, o resto fica)"""
        failures = {
            "exit 1": (1, "", "erro: x\n"),
            "exit 1 com JSON válido": (1, doctor_answer(doctor_findings(1))[1], "erro"),  # Emenda v2
            "json ilegível": (0, "não é json", ""),
            "json sem findings": (0, json.dumps({"plugin_versions": {}}), ""),
            "timeout": subprocess.TimeoutExpired(["python3"], 10),
            "ausente": FileNotFoundError(2, "No such file or directory"),
        }
        for label, answer in failures.items():
            with self.subTest(caso=label):
                project = make_project(self.base / label.replace(" ", "-"), sdd=False)
                runner = FakeRunner(atlas=(0, "{}", ""), doctor=answer)
                code, out, err = self.run_hook(runner, cwd=project)
                self.assertEqual(code, 0)
                self.assertEqual(self.context(out).strip(), ATLAS_LINE)
                labels = [UNAVAILABLE_RE.match(line).group(1).lower() for line in err.splitlines()
                          if UNAVAILABLE_RE.match(line)]
                self.assertEqual(labels, ["doctor"], err)
                self.assertNotIn("Traceback", err)

    def test_no_time_left_skips_the_doctor(self):
        """SPEC-0061:UT-07 (prazo total da SPEC-0058: sem tempo restante o doctor não roda)"""
        if "clock" not in inspect.signature(self.hook.main).parameters:
            self.fail("main() não aceita clock=")
        project = make_project(self.base / "p")
        clock = FakeClock()
        runner = FakeRunner(status=spends(clock), atlas=spends(clock), brain=spends(clock, 1, (0, "{}", "")),
                            doctor=doctor_answer(doctor_findings(2)))
        out, err = io.StringIO(), io.StringIO()
        code = self.call_main(stdin=io.StringIO(json.dumps({"cwd": str(project)})), stdout=out, stderr=err,
                              runner=runner, clock=clock)
        self.assertEqual(code, 0)
        self.assertEqual(runner.calls_to(DOCTOR.name), [], "o doctor rodou sem tempo restante")
        self.assertNotIn(DOCTOR_HEADER.strip(), out.getvalue())
        self.assertRegex(err.getvalue(),
                         re.compile(r"^session_start: Doctor indisponível", re.IGNORECASE | re.MULTILINE))

    def test_real_hook_opens_the_doctor_with_read_only_arguments(self):
        """SPEC-0061:UT-07 (subprocess.run substituído: o doctor é o único processo além das três CLIs)"""
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp).resolve() / "p")

            def answer(argv, *args, **kwargs):
                if Path(str(argv[1])).name == DOCTOR.name:
                    return completed(argv, 0, stdout=doctor_answer(doctor_findings(1))[1])
                return completed(argv, 0, stdout="SPEC-0001 proposed\n")
            out = io.StringIO()
            with mock.patch.object(self.hook.subprocess, "run", side_effect=answer) as run:
                self.hook.main(stdin=io.StringIO(json.dumps({"cwd": str(project)})), stdout=out,
                               stderr=io.StringIO())
        doctor_calls = [c for c in run.call_args_list if Path(str((c[0][0] if c[0] else c[1]["args"])[1])).name
                        == DOCTOR.name]
        self.assertEqual(len(doctor_calls), 1, run.call_args_list)
        args, kwargs = doctor_calls[0]
        argv = args[0] if args else kwargs.get("args")
        self.assertIsInstance(argv, list)
        self.assertFalse(kwargs.get("shell", False))
        self.assertIsNotNone(kwargs.get("timeout"))
        self.assertEqual(Path(argv[1]).resolve(), DOCTOR.resolve())
        self.assertEqual([argv[2], argv[4:]], ["--project", ["--json"]], argv)
        self.assertIn(DOCTOR_HEADER.strip(), self.context(out.getvalue()))


# ---------------------------------------------------------------- IT-01

def isolated_env(base):
    """Ambiente herdado com HOME, XDG e as configurações do atlas e do cérebro em pastas temporárias vazias."""
    base = Path(base)
    folders = {"HOME": base / "home", "XDG_CONFIG_HOME": base / "home" / ".config",
               "XDG_DATA_HOME": base / "home" / ".local" / "share", "XDG_CACHE_HOME": base / "home" / ".cache",
               "XDG_STATE_HOME": base / "home" / ".local" / "state",
               "ATLAS_CONFIG_HOME": base / "atlas-config", "BRAIN_CONFIG_HOME": base / "brain-config"}
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "ATLAS_", "BRAIN_"))}
    env.update({k: str(v) for k, v in folders.items()})
    env.update(GIT_ENV)
    real_home = Path(os.environ.get("HOME") or Path.home()).resolve()
    assert Path(env["HOME"]).resolve() != real_home
    return env


def make_sdd_fixture(root, env):
    """Projeto de fixture com a CLI real: git init, docs/specs/sdd-config.yml do template e uma spec com `new`."""
    root = Path(root)
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, env=env, check=True, capture_output=True)
    (root / "docs" / "specs").mkdir(parents=True)
    shutil.copy(SDD_CONFIG_TEMPLATE, root / "docs" / "specs" / "sdd-config.yml")
    new = subprocess.run([sys.executable, str(SPEC_GRAPH), "new", "--tier", "lite", "--title", "Fixture do hook"],
                         cwd=root, env=env, capture_output=True, text=True, timeout=60, check=False)
    assert new.returncode == 0, new.stdout + new.stderr
    return root


def status_stdout(spec_graph, project, env):
    result = subprocess.run([sys.executable, str(spec_graph), "status"], cwd=project, env=env, capture_output=True,
                            text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip(), "status da fixture sem saída"
    return result.stdout


def hook_stdin(cwd):
    return json.dumps({"session_id": "it-01", "transcript_path": "/dev/null", "hook_event_name": "SessionStart",
                       "source": "startup", "cwd": str(cwd)})


class HookProcessTest(unittest.TestCase):
    def test_hook_process_returns_real_status_of_fixture_project(self):
        """SPEC-0058:IT-01"""
        if not HOOK.is_file():
            self.fail(f"{HOOK_NAME} não existe (SPEC-0058)")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            env = isolated_env(base / "env")
            project = make_sdd_fixture(base / "projeto com espaço", env)
            elsewhere = base / "outro"
            elsewhere.mkdir()
            expected = status_stdout(SPEC_GRAPH, project, env)

            started = time.monotonic()
            result = subprocess.run([sys.executable, str(HOOK)], input=hook_stdin(project), cwd=elsewhere, env=env,
                                    capture_output=True, text=True, timeout=30, check=False)
            elapsed = time.monotonic() - started

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLess(elapsed, 5, f"hook levou {elapsed:.1f} s")
            data = json.loads(result.stdout)
            self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "SessionStart")
            context = data["hookSpecificOutput"]["additionalContext"]
            self.assertTrue(context.startswith(SDD_HEADER), context)
            self.assertIn(expected.strip(), context)
            self.assertNotIn(ATLAS_LINE, context)
            self.assertNotIn(BRAIN_LINE, context)
            self.assertEqual(sorted(p.name for p in (base / "env" / "atlas-config").iterdir()), [],
                             "o hook gravou na configuração do atlas")
            self.assertEqual(sorted(p.name for p in (base / "env" / "brain-config").iterdir()), [],
                             "o hook gravou na configuração do cérebro")


if __name__ == "__main__":
    unittest.main()
