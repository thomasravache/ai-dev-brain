"""Hook SessionStart do plugin fermion (SPEC-0058, ADR-0017).

Lê o JSON do hook no stdin (só o "cwd"), roda só comandos de leitura das CLIs do próprio plugin e imprime
`hookSpecificOutput.additionalContext` com até três blocos: o `status` do SDD (quando o projeto tem
docs/specs/sdd-config.yml), a linha do atlas e a linha do segundo cérebro (quando `config --json` sai com 0).
Prazo de 10 s por CLI e 20 s no total (Emenda v2). Sempre sai com 0: CLI ou cwd que falha tira só o bloco dela e
vira uma linha de diagnóstico no stderr. Só stdlib, Python 3.9+.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
SPEC_GRAPH = SKILLS / "gluon-spec" / "scripts" / "spec_graph.py"
ATLAS = SKILLS / "boson-atlas" / "scripts" / "atlas.py"
BRAIN = SKILLS / "photon-brain" / "scripts" / "brain.py"

CLI_TIMEOUT = 10
TOTAL_TIMEOUT = 20
NOT_CONFIGURED = 3
SDD_LIMIT = 6000
CONTEXT_LIMIT = 8000

SDD_HEADER = "## SDD (gluon-spec)\n"
CUT_NOTICE = "… (cortado; rode `status`)"
ATLAS_LINE = ("Atlas da organização (boson-atlas) configurado nesta máquina: para contexto de sistemas, use a skill "
              "boson-atlas ou a tool MCP atlas_context.")
BRAIN_LINE = ("Segundo cérebro (photon-brain) configurado nesta máquina: para notas e decisões do usuário, use a "
              "skill photon-brain.")


def run_cli(argv, cwd, timeout):
    """Único ponto que abre processo: argv em lista, sem shell, ambiente herdado. Não engole exceções."""
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout,
                          check=False)


class Unavailable(Exception):
    """CLI ausente, timeout, saída ilegível ou exit fora do esperado: o bloco some e vira uma linha no stderr."""


class Deadline:
    """Prazo total a partir da primeira leitura do relógio; cada CLI recebe min(CLI_TIMEOUT, restante)."""

    def __init__(self, clock):
        self.clock = clock
        self.end = clock() + TOTAL_TIMEOUT

    def next_timeout(self):
        remaining = self.end - self.clock()
        if remaining <= 0:
            raise Unavailable(f"sem tempo: prazo total de {TOTAL_TIMEOUT} s esgotado")
        return min(CLI_TIMEOUT, remaining)


def call(runner, deadline, script, args, cwd):
    """Roda uma CLI do plugin com o interpretador atual; Unavailable no lugar de exceção de processo."""
    timeout = deadline.next_timeout()
    argv = [sys.executable, str(script), *args]
    try:
        result = runner(argv, cwd, timeout)
    except subprocess.TimeoutExpired:
        raise Unavailable(f"timeout de {timeout:g} s") from None
    except UnicodeError:
        raise Unavailable("saída que não decodifica") from None
    except OSError as error:
        raise Unavailable(f"não executou: {error.strerror or type(error).__name__}") from None
    if not isinstance(result.stdout, (str, type(None))) or not isinstance(result.stderr, (str, type(None))):
        raise Unavailable("saída que não é texto")
    return result


def read_cwd(stdin):
    """Pasta do "cwd" do JSON do hook; o cwd do processo quando não há stdin, o JSON é inválido ou sem "cwd"."""
    try:
        data = json.loads(stdin.read()) if stdin is not None else None
    except (ValueError, OSError, AttributeError):
        data = None
    cwd = data.get("cwd") if isinstance(data, dict) else None
    if isinstance(cwd, str) and cwd:
        return Path(cwd)
    return Path.cwd()


def project_root(cwd):
    """A primeira pasta, do cwd para cima, que contém .git (arquivo ou pasta); sem .git, o próprio cwd."""
    for folder in (cwd, *cwd.parents):
        if (folder / ".git").exists():
            return folder
    return cwd


def locate(stdin):
    """(projeto, cwd das CLIs). Projeto None quando o cwd não existe; Unavailable quando não dá para ler."""
    try:
        cwd = read_cwd(stdin)
        if not cwd.is_dir():
            return None, None
        project = project_root(cwd.resolve())
        has_config = (project / "docs" / "specs" / "sdd-config.yml").is_file()
    except (OSError, ValueError) as error:
        raise Unavailable(f"cwd ilegível: {type(error).__name__}") from None
    return (project if has_config else None), str(project)


def first_line(text):
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "")


def sdd_block(runner, deadline, project):
    """Bloco SDD com o stdout do `status`, cortado em SDD_LIMIT contando o cabeçalho."""
    result = call(runner, deadline, SPEC_GRAPH, ["status"], str(project))
    if result.returncode != 0:
        reason = first_line(result.stderr) or f"exit {result.returncode}"
        return SDD_HEADER + f"status falhou: {reason}"
    body = (result.stdout or "").rstrip()
    if len(SDD_HEADER) + len(body) > SDD_LIMIT:
        room = SDD_LIMIT - len(SDD_HEADER) - len(CUT_NOTICE) - 1
        body = body[:room].rstrip() + "\n" + CUT_NOTICE
    return SDD_HEADER + body


def configured_line(runner, deadline, script, line, cwd):
    """A linha fixa quando `config --json` sai com 0; None quando sai com 3 (não configurado)."""
    result = call(runner, deadline, script, ["config", "--json"], cwd)
    if result.returncode == 0:
        return line
    if result.returncode == NOT_CONFIGURED:
        return None
    raise Unavailable(f"config saiu com {result.returncode}")


def report(stderr, name, error):
    try:
        print(f"session_start: {name} indisponível ({error})", file=stderr)
    except (OSError, ValueError, AttributeError):
        pass


def main(stdin=None, stdout=None, stderr=None, runner=run_cli, clock=time.monotonic):
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    deadline = Deadline(clock)

    blocks = []
    try:
        project, cli_cwd = locate(stdin)
    except Unavailable as error:
        report(stderr, "SDD", error)
        project = cli_cwd = None
    steps = (("SDD", lambda: sdd_block(runner, deadline, project) if project else None),
             ("Atlas", lambda: configured_line(runner, deadline, ATLAS, ATLAS_LINE, cli_cwd)),
             ("Brain", lambda: configured_line(runner, deadline, BRAIN, BRAIN_LINE, cli_cwd)))
    for name, step in steps:
        try:
            block = step()
        except Unavailable as error:
            report(stderr, name, error)
            continue
        if block:
            blocks.append(block)

    if blocks:
        context = "\n\n".join(blocks)[:CONTEXT_LIMIT]
        output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
        try:
            stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
        except (OSError, ValueError, AttributeError) as error:
            report(stderr, "SDD", f"stdout: {type(error).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
