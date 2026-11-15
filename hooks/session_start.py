"""Hook SessionStart do plugin fermion (SPEC-0058, ADR-0017).

Lê o JSON do hook no stdin (só o "cwd"), roda só comandos de leitura das CLIs do próprio plugin e imprime
`hookSpecificOutput.additionalContext` com até três blocos: o `status` do SDD (quando o projeto tem
docs/specs/sdd-config.yml), a linha do atlas e a linha do segundo cérebro (quando `config --json` sai com 0).
Sempre sai com 0: CLI que falha vira bloco omitido e uma linha de diagnóstico no stderr. Só stdlib, Python 3.9+.
"""
import json
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
SPEC_GRAPH = SKILLS / "gluon-spec" / "scripts" / "spec_graph.py"
ATLAS = SKILLS / "boson-atlas" / "scripts" / "atlas.py"
BRAIN = SKILLS / "photon-brain" / "scripts" / "brain.py"

CLI_TIMEOUT = 10
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
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)


class Unavailable(Exception):
    """CLI ausente, timeout ou exit fora do esperado: o bloco some e vira uma linha no stderr."""


def call(runner, script, args, cwd):
    """Roda uma CLI do plugin com o interpretador atual; Unavailable no lugar de exceção de processo."""
    argv = [sys.executable, str(script), *args]
    try:
        return runner(argv, cwd, CLI_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise Unavailable(f"timeout de {CLI_TIMEOUT} s") from None
    except OSError as error:
        raise Unavailable(f"não executou: {error.strerror or type(error).__name__}") from None


def read_cwd(stdin):
    """Pasta do "cwd" do JSON do hook; o cwd do processo quando o JSON é inválido ou não traz "cwd"."""
    try:
        data = json.loads(stdin.read())
    except (ValueError, OSError):
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


def first_line(text):
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "")


def sdd_block(runner, project):
    """Bloco SDD com o stdout do `status` (cortado em SDD_LIMIT contando o cabeçalho), ou None sem sdd-config.yml."""
    if not (project / "docs" / "specs" / "sdd-config.yml").is_file():
        return None
    result = call(runner, SPEC_GRAPH, ["status"], str(project))
    if result.returncode != 0:
        reason = first_line(result.stderr) or f"exit {result.returncode}"
        return SDD_HEADER + f"status falhou: {reason}"
    body = (result.stdout or "").rstrip()
    if len(SDD_HEADER) + len(body) > SDD_LIMIT:
        room = SDD_LIMIT - len(SDD_HEADER) - len(CUT_NOTICE) - 1
        body = body[:room].rstrip() + "\n" + CUT_NOTICE
    return SDD_HEADER + body


def configured_line(runner, script, line, cwd):
    """A linha fixa quando `config --json` sai com 0; None quando sai com 3 (não configurado)."""
    result = call(runner, script, ["config", "--json"], cwd)
    if result.returncode == 0:
        return line
    if result.returncode == NOT_CONFIGURED:
        return None
    raise Unavailable(f"config saiu com {result.returncode}")


def main(stdin=None, stdout=None, stderr=None, runner=run_cli):
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    try:
        cwd = read_cwd(stdin)
        exists = cwd.is_dir()
        project = project_root(cwd.resolve()) if exists else None
        cli_cwd = str(project) if exists else None

        blocks = []
        steps = (("SDD", lambda: sdd_block(runner, project) if exists else None),
                 ("Atlas", lambda: configured_line(runner, ATLAS, ATLAS_LINE, cli_cwd)),
                 ("Brain", lambda: configured_line(runner, BRAIN, BRAIN_LINE, cli_cwd)))
        for name, step in steps:
            try:
                block = step()
            except Unavailable as error:
                print(f"session_start: {name} indisponível ({error})", file=stderr)
                continue
            if block:
                blocks.append(block)

        if blocks:
            context = "\n\n".join(blocks)[:CONTEXT_LIMIT]
            output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
            stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    except (OSError, ValueError) as error:  # cwd ilegível ou stdout fechado: o hook nunca atrapalha a sessão
        print(f"session_start: SDD indisponível ({type(error).__name__})", file=stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
